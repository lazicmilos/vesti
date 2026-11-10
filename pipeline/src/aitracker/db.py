"""Konekcija na Postgres i runner za numerisane SQL migracije."""

from pathlib import Path
from typing import Any

import psycopg

from aitracker.config import PIPELINE_ROOT

Conn = psycopg.Connection[tuple[Any, ...]]


def connect(url: str) -> Conn:
    # autocommit: transakcije se otvaraju eksplicitno (`with conn.transaction()`), po izvoru.
    return psycopg.connect(url, autocommit=True)


def migrate(conn: Conn, directory: Path = PIPELINE_ROOT / "migrations") -> list[str]:
    """Primenjuje migracije koje još nisu u `schema_migrations`; vraća primenjene verzije."""
    # Tabelu schema_migrations pravi tek 001_init.sql, pa pre nje nema šta da se čita.
    exists = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()
    done: set[str] = set()
    if exists and exists[0]:
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.stem in done:
            continue
        with conn.transaction():
            conn.execute(path.read_bytes())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
        applied.append(path.stem)
    return applied
