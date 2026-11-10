"""OpenRouter: lista modela sa cenama i context window-om (glavni izvor trackera)."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from aitracker.sources.base import EmptySource, ModelItem, PoliteClient, SourceError

_PER_MILLION = Decimal(1_000_000)  # API daje USD po jednom tokenu


class _Pricing(BaseModel):
    prompt: Decimal | None = None
    completion: Decimal | None = None


class _Model(BaseModel):
    id: str
    name: str
    hugging_face_id: str | None = None
    created: int | None = None  # unix vreme dodavanja na OpenRouter
    context_length: int | None = None
    pricing: _Pricing = _Pricing()


class _Response(BaseModel):
    data: list[_Model]


def _price(per_token: Decimal | None) -> Decimal | None:
    # Routeri (openrouter/auto) imaju cenu -1: cena zavisi od izabranog modela, dakle nepoznata.
    if per_token is None or per_token < 0:
        return None
    return (per_token * _PER_MILLION).normalize()


def parse_models(body: bytes) -> list[ModelItem]:
    try:
        models = _Response.model_validate_json(body).data
    except ValidationError as exc:
        raise SourceError(f"neispravan OpenRouter odgovor: {exc.error_count()} grešaka") from exc
    base_ids = {m.id for m in models if ":" not in m.id}
    items: dict[str, ModelItem] = {}
    for model in models:
        # "~org/x-latest" su prečice ka drugim modelima, ne modeli.
        if model.id.startswith("~"):
            continue
        # "org/x:free" i "org/x:batch" su drugi cenovnik istog modela: preskaču se kad
        # osnovni zapis postoji, inače predstavljaju model pod osnovnim imenom.
        base_id, _, variant = model.id.partition(":")
        if (variant and base_id in base_ids) or base_id in items:
            continue
        org, sep, name = model.name.partition(": ")
        if not sep:
            org, name = base_id.split("/")[0], model.name
        if variant:
            name = name.removesuffix(f" ({variant})")
        hf_id = model.hugging_face_id or None
        items[base_id] = ModelItem(
            raw_name=base_id,
            name=name,
            org=org,
            aliases=[hf_id] if hf_id else [],
            # Odluka vlasnika (SPEC 17): datum dodavanja na OpenRouter važi kao približan
            # datum izdanja dok ga LLM dopuna iz zvanične najave ne potvrdi (F3).
            released_at=(
                datetime.fromtimestamp(model.created, tz=UTC).date() if model.created else None
            ),
            context_window=model.context_length,
            price_in=_price(model.pricing.prompt),
            price_out=_price(model.pricing.completion),
            open_weights=True if hf_id else None,
            source_url=f"https://openrouter.ai/{base_id}",
        )
    return list(items.values())


class OpenRouterSource:
    def __init__(self, name: str, url: str, client: PoliteClient) -> None:
        self.name = name
        self._url = url
        self._client = client

    def fetch_models(self) -> list[ModelItem]:
        items = parse_models(self._client.get(self._url).content)
        if not items:
            raise EmptySource(f"{self.name}: nema modela")
        return items
