"""Hugging Face Hub: popularni open-weight modeli (licenca, broj parametara)."""

from decimal import Decimal

from pydantic import BaseModel, TypeAdapter, ValidationError

from aitracker.sources.base import EmptySource, ModelItem, PoliteClient, SourceError

# `expand[]` vraća samo tražena polja (~50 KB); `full=true` vraća i config (~700 KB).
_QUERY = (
    "pipeline_tag=text-generation&sort=likes&direction=-1&limit=100"
    "&expand[]=safetensors&expand[]=tags&expand[]=likes&expand[]=author"
)
_BILLION = Decimal(10**9)


class _Safetensors(BaseModel):
    total: int | None = None


class _Repo(BaseModel):
    id: str
    author: str | None = None
    likes: int = 0
    tags: list[str] = []
    safetensors: _Safetensors | None = None


_REPOS = TypeAdapter(list[_Repo])


def parse_models(body: bytes, min_likes: int) -> list[ModelItem]:
    try:
        repos = _REPOS.validate_json(body)
    except ValidationError as exc:
        raise SourceError(f"neispravan Hugging Face odgovor: {exc.error_count()} grešaka") from exc
    items = []
    for repo in repos:
        # Kvantizovane kopije (GGUF i slično) tuđeg modela nisu novi model.
        if repo.likes < min_likes or any(t.startswith("base_model:quantized:") for t in repo.tags):
            continue
        license_ = next((t.removeprefix("license:") for t in repo.tags
                         if t.startswith("license:")), None)
        total = repo.safetensors.total if repo.safetensors else None
        items.append(
            ModelItem(
                raw_name=repo.id,
                name=repo.id.split("/")[-1],
                org=repo.author or repo.id.split("/")[0],
                params_b=round(Decimal(total) / _BILLION, 3) if total else None,
                license=None if license_ == "unknown" else license_,
                open_weights=True,
                source_url=f"https://huggingface.co/{repo.id}",
            )
        )
    return items


class HuggingFaceSource:
    def __init__(self, name: str, url: str, client: PoliteClient, min_likes: int = 1000) -> None:
        self.name = name
        self._url = url
        self._client = client
        self._min_likes = min_likes

    def fetch_models(self) -> list[ModelItem]:
        # ponytail: samo prvih 100 po lajkovima. Pratiti `Link: rel="next"` ako prag
        # `min_likes` jednom bude ispunjavalo više od 100 modela.
        items = parse_models(self._client.get(f"{self._url}?{_QUERY}").content, self._min_likes)
        if not items:
            raise EmptySource(f"{self.name}: nema modela iznad praga")
        return items
