"""CLI za pregled i rešavanje review_queue: `python -m aitracker.review`."""

import sys
from typing import Any, Literal

from aitracker.config import database_url
from aitracker.db import Conn, connect
from aitracker.sources.base import ModelItem
from aitracker.tracker import add_aliases, create_model

Action = Literal["merge", "new", "discard"]
_KEYS: dict[str, Action] = {"s": "merge", "n": "new", "o": "discard"}


class ReviewError(Exception):
    """Stavka ne postoji, već je rešena ili akcija nije primenljiva."""


def pending(conn: Conn) -> list[tuple[Any, ...]]:
    """Nerešene stavke: (id, ime, izvor, slug kandidata, URL stavke)."""
    return conn.execute(
        """
        SELECT q.id, q.raw_name, COALESCE(s.name, '?'), m.slug, q.payload->>'source_url'
        FROM review_queue q
        LEFT JOIN sources s ON s.id = q.source_id
        LEFT JOIN models m ON m.id = q.candidate_model_id
        WHERE q.resolved_at IS NULL AND q.reason = 'similar_name'
        ORDER BY q.id
        """
    ).fetchall()


def resolve_item(conn: Conn, item_id: int, action: Action) -> None:
    """Spaja stavku sa kandidatom, pravi od nje novi model ili je odbacuje."""
    with conn.transaction():
        row = conn.execute(
            """
            SELECT q.candidate_model_id, q.payload, s.name FROM review_queue q
            LEFT JOIN sources s ON s.id = q.source_id
            WHERE q.id = %s AND q.resolved_at IS NULL FOR UPDATE OF q
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            raise ReviewError(f"stavka {item_id} ne postoji ili je već rešena")
        candidate_id, payload, source = row
        if action != "discard":
            item = ModelItem.model_validate(payload)
            if action == "new":
                create_model(conn, source or "review", item)
            elif candidate_id is None:
                raise ReviewError(f"stavka {item_id} nema kandidata za spajanje")
            else:
                # Samo alias: polja popunjava sledeće pokretanje, sada kad se ime poklapa.
                add_aliases(conn, candidate_id, [item.raw_name, *item.aliases])
        conn.execute("UPDATE review_queue SET resolved_at = now() WHERE id = %s", (item_id,))


def main() -> int:
    with connect(database_url()) as conn:
        items = pending(conn)
        print(f"Nerešenih stavki: {len(items)}")
        for item_id, raw_name, source, candidate, url in items:
            print(f"\n[{item_id}] {raw_name}  ({source})\n    {url}\n    liči na: {candidate}")
            key = input("    (s)poji / (n)ovi model / (o)dbaci / Enter = preskoči / (k)raj: ")
            key = key.strip().lower()
            if key == "k":
                break
            if key in _KEYS:
                resolve_item(conn, item_id, _KEYS[key])
    return 0


if __name__ == "__main__":
    sys.exit(main())
