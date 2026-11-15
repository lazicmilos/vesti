"""LLM dopuna NULL polja modela iz najava laboratorija (SPEC 10, korak 3.3; FR-004)."""

import re
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from aitracker.budget import BudgetExceeded
from aitracker.db import Conn
from aitracker.llm.client import LLMClient, LLMError, ValidationFailed
from aitracker.llm.schemas import ModelFields
from aitracker.tracker import FIELDS

LLM_FIELDS = ("org", *FIELDS, "summary_sr")
MAX_CALLS = 50  # plaćenih poziva po pokretanju; dodatna ograda uz mesečni budžet
# Model se traži samo u naslovu i početku teksta: stranice na kraju navode druge članke
# i modele, a poziv za pogrešan model bi napisao pogrešan sažetak.
LEAD_CHARS = 300
MIN_ALIAS_LEN = 4  # kraći aliasi („o1“, „r1“) daju lažna poklapanja u običnom tekstu


def _lead(title: str, content: str) -> str:
    return re.sub(r"[_\s]+", "-", f"{title}\n{content[:LEAD_CHARS]}".lower())


def mentions(lead: str, alias: str) -> bool:
    """Tačno poklapanje normalizovanog aliasa: „gpt-5“ ne pogađa „gpt-5-mini“ ni „chatgpt-5“."""
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9]|[.-][a-z0-9])", lead) is not None


def find_pairs(conn: Conn) -> list[tuple[int, str, int, str, str]]:
    """(model_id, ime, document_id, url, tekst) za modele sa NULL poljem i najave koje ih pominju.

    Par sa nerešenim `extraction_failed` u review_queue se preskače (NFR-R-004).
    """
    missing = sql.SQL(" OR ").join(sql.SQL("{} IS NULL").format(sql.Identifier(f))
                                   for f in LLM_FIELDS)
    aliases = conn.execute(sql.SQL(
        "SELECT a.alias_norm, m.id, m.name FROM model_aliases a JOIN models m ON m.id = a.model_id "
        "WHERE {} ORDER BY m.id").format(missing)).fetchall()
    docs = conn.execute(
        "SELECT d.id, d.url_canonical, d.title, d.content FROM documents d "
        "JOIN sources s ON s.id = d.source_id "
        "WHERE s.role = 'both' AND d.content IS NOT NULL ORDER BY d.id"
    ).fetchall()
    failed = set(conn.execute(
        "SELECT candidate_model_id, (payload->>'document_id')::bigint FROM review_queue "
        "WHERE reason = 'extraction_failed' AND resolved_at IS NULL"
    ).fetchall())
    pairs = []
    for doc_id, url, title, content in docs:
        lead = _lead(title, content)
        matched = {(model_id, name) for alias, model_id, name in aliases
                   if len(alias) >= MIN_ALIAS_LEN and mentions(lead, alias)}
        pairs += [(model_id, name, doc_id, url, content) for model_id, name in sorted(matched)
                  if (model_id, doc_id) not in failed]
    return pairs


def apply_fields(conn: Conn, model_id: int, fields: ModelFields, url: str) -> list[str]:
    """Upisuje samo vrednosti u NULL polja; vraća imena popunjenih polja (FR-004)."""
    columns = sql.SQL(", ").join(sql.Identifier(f) for f in LLM_FIELDS)
    row = conn.execute(
        sql.SQL("SELECT field_sources, {} FROM models WHERE id = %s").format(columns), (model_id,)
    ).fetchone()
    assert row is not None
    current: dict[str, Any] = dict(zip(LLM_FIELDS, row[1:], strict=True))
    found = fields.model_dump()
    changes = {f: found[f] for f in LLM_FIELDS if current[f] is None and found[f] is not None}
    if not changes:
        return []
    assignments = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(f)) for f in changes)
    conn.execute(
        sql.SQL("UPDATE models SET {}, field_sources = %s, updated_at = now() WHERE id = %s")
        .format(assignments),
        (*changes.values(), Jsonb(row[0] | dict.fromkeys(changes, f"llm:{url}")), model_id),
    )
    return list(changes)


def enrich_models(conn: Conn, llm: LLMClient) -> list[dict[str, str]]:
    """Dopuna za svaki par iz `find_pairs`; vraća greške za `runs.errors`."""
    errors: list[dict[str, str]] = []
    calls = 0
    for model_id, name, doc_id, url, content in find_pairs(conn):
        if calls >= MAX_CALLS:
            errors.append({"source": "llm", "kind": "limit",
                           "message": f"dostignut limit od {MAX_CALLS} poziva po pokretanju"})
            break
        try:
            fields, usage = llm.complete_json(
                "model_fields_v1", {"name": name, "text": content}, ModelFields
            )
        except BudgetExceeded as exc:  # FR-019: ostatak meseca bez LLM koraka
            errors.append({"source": "llm", "kind": "budget", "message": str(exc)})
            break
        except ValidationFailed:
            conn.execute(
                "INSERT INTO review_queue (raw_name, candidate_model_id, reason, payload) "
                "VALUES (%s, %s, 'extraction_failed', %s)",
                (name, model_id, Jsonb({"document_id": doc_id, "url": url})),
            )
            calls += 1
            continue
        except LLMError as exc:
            errors.append({"source": "llm", "kind": "error", "message": f"{name}: {exc}"})
            calls += 1
            continue
        calls += not usage.cached
        apply_fields(conn, model_id, fields, url)
    return errors
