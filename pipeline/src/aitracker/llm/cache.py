"""Keš LLM izlaza u tabeli `llm_cache`: isti sadržaj, prompt i model se ne plaćaju dvaput."""

import hashlib
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from aitracker.db import Conn


def cache_key(content: str, prompt_version: str, model: str) -> str:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return hashlib.sha256(f"{content_hash}{prompt_version}{model}".encode()).hexdigest()


def get(conn: Conn, key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT output FROM llm_cache WHERE key = %s", (key,)).fetchone()
    return row[0] if row else None


def put(
    conn: Conn, key: str, prompt_version: str, model: str, output: dict[str, Any],
    input_tokens: int, output_tokens: int, cost_usd: Decimal,
) -> None:
    conn.execute(
        "INSERT INTO llm_cache (key, prompt_version, model, output, input_tokens, output_tokens, "
        "cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET output = EXCLUDED.output",
        (key, prompt_version, model, Jsonb(output), input_tokens, output_tokens, cost_usd),
    )
