"""Upis modela iz strukturiranih izvora: modeli, aliasi, istorija cena i review_queue."""

import logging
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from aitracker.db import Conn
from aitracker.identity import Registry, normalize, org_key, resolve
from aitracker.sources.base import ModelItem

log = logging.getLogger(__name__)
# Polja koja strukturirani izvor sme da popuni; ime, slug i organizacija se postavljaju jednom.
FIELDS = ("released_at", "params_b", "context_window", "price_in", "price_out",
          "license", "open_weights")


def load_registry(conn: Conn, org_aliases: dict[str, str]) -> Registry:
    registry = Registry()
    for model_id, org in conn.execute("SELECT id, org FROM models"):
        registry.orgs[model_id] = org_key(org, org_aliases)
    for alias, model_id in conn.execute("SELECT alias_norm, model_id FROM model_aliases"):
        registry.aliases[alias] = model_id
    return registry


def create_model(conn: Conn, source: str, item: ModelItem) -> int:
    """Novi model sa `verified = FALSE`, aliasima i početnim redom istorije cena."""
    values = {name: getattr(item, name) for name in FIELDS}
    field_sources = {name: source for name, value in values.items() if value is not None}
    row = conn.execute(
        """
        INSERT INTO models (slug, name, org, released_at, params_b, context_window, price_in,
                            price_out, license, open_weights, source_url, field_sources)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (normalize(item.raw_name), item.name, item.org, *values.values(), item.source_url,
         Jsonb(field_sources)),
    ).fetchone()
    assert row is not None
    model_id: int = row[0]
    add_aliases(conn, model_id, [item.raw_name, *item.aliases])
    if item.price_in is not None or item.price_out is not None:
        _record_price(conn, model_id, item.price_in, item.price_out)
    return model_id


def add_aliases(conn: Conn, model_id: int, names: list[str]) -> None:
    for name in names:
        conn.execute(
            "INSERT INTO model_aliases (alias_norm, alias_raw, model_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (normalize(name), name, model_id),
        )


def update_model(conn: Conn, model_id: int, source: str, item: ModelItem) -> bool:
    """Popunjava NULL polja i osvežava ona koja je isti izvor ranije postavio (FR-006).

    Vrednost koju je postavio drugi izvor se ne dira: prvi strukturirani izvor ima prednost.
    """
    columns = sql.SQL(", ").join(sql.Identifier(name) for name in FIELDS)
    row = conn.execute(
        sql.SQL("SELECT field_sources, {} FROM models WHERE id = %s").format(columns), (model_id,)
    ).fetchone()
    assert row is not None
    field_sources: dict[str, str] = row[0]
    current: dict[str, Any] = dict(zip(FIELDS, row[1:], strict=True))
    changes = {
        name: getattr(item, name)
        for name in FIELDS
        if getattr(item, name) is not None
        and getattr(item, name) != current[name]
        and (current[name] is None or field_sources.get(name) == source)
    }
    if not changes:
        return False
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(name)) for name in changes
    )
    conn.execute(
        sql.SQL("UPDATE models SET {}, field_sources = %s, updated_at = now() WHERE id = %s")
        .format(assignments),
        (*changes.values(), Jsonb(field_sources | dict.fromkeys(changes, source)), model_id),
    )
    if "price_in" in changes or "price_out" in changes:
        merged = current | changes
        _record_price(conn, model_id, merged["price_in"], merged["price_out"])
    return True


def _record_price(conn: Conn, model_id: int, price_in: Any, price_out: Any) -> None:
    conn.execute(
        "INSERT INTO model_price_history (model_id, price_in, price_out) VALUES (%s, %s, %s)",
        (model_id, price_in, price_out),
    )


def queue_similar(conn: Conn, source_id: int, candidate_id: int, item: ModelItem) -> bool:
    """Upisuje u review_queue jednom po imenu, i kad je stavka već rešena (npr. odbačena)."""
    cur = conn.execute(
        """
        INSERT INTO review_queue (raw_name, source_id, candidate_model_id, reason, payload)
        SELECT %s, %s, %s, 'similar_name', %s
        WHERE NOT EXISTS (SELECT 1 FROM review_queue WHERE raw_name = %s)
        """,
        (item.raw_name, source_id, candidate_id, Jsonb(item.model_dump(mode="json")),
         item.raw_name),
    )
    return cur.rowcount == 1


def upsert_models(
    conn: Conn, source: str, source_id: int, items: list[ModelItem], org_aliases: dict[str, str]
) -> tuple[int, int]:
    """Primenjuje SPEC 10.1 na stavke jednog izvora; vraća (novi modeli, novi u review_queue)."""
    registry = load_registry(conn, org_aliases)
    created = queued = 0
    touched: set[int] = set()
    # Kraća imena prva: "x" se obradi pre "x-1017", pa datirani snimak ne nadjača cenu modela.
    # Redosled je i deterministički, što odlučuje ko je model, a ko ide na pregled.
    for item in sorted(items, key=lambda i: (len(i.raw_name), i.raw_name)):
        org = org_key(item.org, org_aliases)
        match = resolve([item.raw_name, *item.aliases], org, registry)
        if match.kind == "similar":
            assert match.model_id is not None
            queued += queue_similar(conn, source_id, match.model_id, item)
            continue
        if match.kind == "existing":
            assert match.model_id is not None
            model_id = match.model_id
            add_aliases(conn, model_id, [item.raw_name, *item.aliases])
            if model_id not in touched:
                update_model(conn, model_id, source, item)
        else:
            model_id = create_model(conn, source, item)
            registry.orgs[model_id] = org
            created += 1
        touched.add(model_id)
        for name in (item.raw_name, *item.aliases):
            registry.aliases.setdefault(normalize(name), model_id)
    return created, queued
