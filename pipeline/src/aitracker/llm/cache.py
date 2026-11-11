"""Keš LLM izlaza u `llm_cache`: isti ulaz, prompt i model ne plaćaju drugi poziv (NFR-R-004)."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from aitracker.db import Conn


def content_hash(variables: dict[str, str], schema: dict[str, Any]) -> str:
    """Hash ulaza: promenljive prompta i JSON šema izlaza, u kanonskom obliku.

    Šema je deo hasha da izmena `schemas.py` bez nove verzije prompta ne vrati star izlaz.
    """
    canonical = json.dumps([variables, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def cache_key(content: str, prompt_version: str, model: str) -> str:
    """sha256(content_hash + prompt_version + model), po SPEC 8."""
    return hashlib.sha256(f"{content}{prompt_version}{model}".encode()).hexdigest()


@dataclass(frozen=True)
class CachedCall:
    output: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


def get(conn: Conn, key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT output FROM llm_cache WHERE key = %s", (key,)).fetchone()
    return None if row is None else dict(row[0])


def put(conn: Conn, key: str, prompt_version: str, model: str, call: CachedCall) -> None:
    conn.execute(
        """
        INSERT INTO llm_cache (key, prompt_version, model, output, input_tokens, output_tokens,
                               cost_usd)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (key) DO NOTHING
        """,
        (key, prompt_version, model, Jsonb(call.output), call.input_tokens, call.output_tokens,
         call.cost_usd),
    )
