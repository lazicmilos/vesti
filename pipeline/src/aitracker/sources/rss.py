"""RSS/Atom izvor: parsira feed u RawItem stavke."""

import calendar
from datetime import UTC, datetime

import feedparser

from aitracker.sources.base import EmptySource, PoliteClient, RawItem, SourceError


def parse_feed(body: bytes) -> list[RawItem]:
    feed = feedparser.parse(body)
    items = []
    for entry in feed.entries:
        url, title = entry.get("link"), entry.get("title")
        if not url or not title:
            continue
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        content = entry.content[0].value if entry.get("content") else entry.get("summary", "")
        items.append(
            RawItem(
                url=url,
                title=" ".join(title.split()),
                published_at=(
                    datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC) if parsed else None
                ),
                content=content,
            )
        )
    # Bez stavki i bez zaglavlja kanala odgovor nije feed (HTML stranica greške, prazno telo).
    if not items and (feed.bozo or not feed.feed):
        raise SourceError("neispravan feed: odgovor nije RSS/Atom")
    return items


class RssSource:
    def __init__(self, name: str, url: str, client: PoliteClient) -> None:
        self.name = name
        self._url = url
        self._client = client

    def fetch(self, since: datetime) -> list[RawItem]:
        items = parse_feed(self._client.get(self._url).content)
        if not items:
            raise EmptySource(f"{self.name}: feed nema stavki")
        # Stavka bez datuma se zadržava; deduplikacija sprečava ponovni upis.
        return [i for i in items if i.published_at is None or i.published_at >= since]
