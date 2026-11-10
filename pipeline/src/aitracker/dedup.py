"""Deduplikacija dokumenata po kanonskom URL-u i hashu sadržaja (FR-011)."""

import logging
from dataclasses import dataclass
from datetime import datetime

from aitracker.db import Conn
from aitracker.normalize import canonical_url, content_hash
from aitracker.sources.base import RawItem

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Document:
    url_canonical: str
    title: str
    published_at: datetime | None
    content_hash: str
    content: str


def to_document(item: RawItem) -> Document | None:
    """Vraća None za stavku čiji URL nije upotrebljiv."""
    try:
        url = canonical_url(item.url)
    except ValueError:
        log.warning("preskočen neispravan URL", extra={"data": {"url": item.url}})
        return None
    return Document(
        url_canonical=url,
        title=item.title,
        published_at=item.published_at,
        # Naslov ulazi u hash: feed bez opisa inače bi dao isti hash za sve stavke.
        content_hash=content_hash(f"{item.title}\n{item.content}"),
        content=item.content,
    )


def insert_new(conn: Conn, source_id: int, items: list[RawItem]) -> int:
    """Upisuje samo nove dokumente; UNIQUE ograničenja u bazi odlučuju šta je duplikat."""
    inserted = 0
    for item in items:
        doc = to_document(item)
        if doc is None:
            continue
        cur = conn.execute(
            """
            INSERT INTO documents (source_id, url_canonical, title, published_at,
                                   content_hash, content)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (source_id, doc.url_canonical, doc.title, doc.published_at,
             doc.content_hash, doc.content),
        )
        inserted += cur.rowcount
    return inserted


def update_hn_points(conn: Conn, items: list[RawItem]) -> int:
    """Upisuje HN poene u dokumente sa istim kanonskim URL-om; ne pravi dokumente."""
    updated = 0
    for item in items:
        doc = to_document(item)
        if doc is None or item.hn_points is None:
            continue
        cur = conn.execute(
            """
            UPDATE documents SET hn_points = GREATEST(COALESCE(hn_points, 0), %s)
            WHERE url_canonical = %s
            """,
            (item.hn_points, doc.url_canonical),
        )
        updated += cur.rowcount
    return updated
