"""Hacker News (Algolia API): signal popularnosti, popunjava `documents.hn_points`."""

from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from aitracker.sources.base import EmptySource, PoliteClient, RawItem, SourceError


class _Hit(BaseModel):
    title: str | None = None
    url: str | None = None  # Ask HN i slične priče nemaju URL
    points: int | None = None
    created_at_i: int


class _Response(BaseModel):
    hits: list[_Hit]


def parse_hits(body: bytes) -> list[RawItem]:
    try:
        response = _Response.model_validate_json(body)
    except ValidationError as exc:
        raise SourceError(f"neispravan HN odgovor: {exc.error_count()} grešaka") from exc
    return [
        RawItem(
            url=hit.url,
            title=hit.title or "",
            published_at=datetime.fromtimestamp(hit.created_at_i, tz=UTC),
            hn_points=hit.points,
        )
        for hit in response.hits
        if hit.url and hit.points is not None
    ]


class HackerNewsSource:
    def __init__(self, name: str, url: str, client: PoliteClient, min_points: int = 20) -> None:
        self.name = name
        self._url = url
        self._client = client
        self._min_points = min_points

    def fetch(self, since: datetime) -> list[RawItem]:
        # ponytail: jedna strana od 1000 pogodaka (izmereno ~200 za 72 h uz points>=20).
        # Dodati paginaciju ako `nbPages` pređe 1.
        params = {
            "tags": "story",
            "numericFilters": f"created_at_i>{int(since.timestamp())},points>={self._min_points}",
            "hitsPerPage": "1000",
        }
        items = parse_hits(self._client.get(self._url, params).content)
        if not items:
            raise EmptySource(f"{self.name}: nema priča")
        return items
