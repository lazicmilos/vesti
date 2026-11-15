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


def spans(text: str, alias: str) -> list[tuple[int, int]]:
    """Pozicije normalizovanog aliasa u tekstu malim slovima.

    Crtica u aliasu pogađa razmak, crticu ili `_` („mistral-large-4“ ↔ „Mistral Large 4“), a
    nastavak spojen crticom ili tačkom se odbija: „gpt-5“ ne pogađa „gpt-5-mini“, „gpt-5.1“ ni
    „chatgpt-5“. Nastavak posle razmaka („Large 4 Instruct“) rešava `_longest`.
    """
    body = r"[\s_-]+".join(map(re.escape, alias.split("-")))
    pattern = rf"(?<![a-z0-9]){body}(?![a-z0-9]|[.-][a-z0-9])"
    return [m.span() for m in re.finditer(pattern, text)]


def mentions(text: str, alias: str) -> bool:
    return bool(spans(text, alias))


Row = tuple[str, int, str, bool]  # alias_norm, model_id, ime, nepotpun


def _longest(text: str, aliases: list[Row]) -> set[tuple[int, str, bool]]:
    """Modeli pomenuti u tekstu; pomen sadržan u dužem pomenu drugog modela se ne računa.

    „Mistral Large 4 Instruct“ je pomen modela Instruct, ne i modela „Mistral Large 4“.
    """
    # ponytail: ako duži model nije u trackeru, kraći se ipak računa; ograda je pravilo naslova
    # i dvosmislenosti u find_pairs.
    hits = [(a, b, row) for row in aliases for a, b in spans(text, row[0])]
    return {
        row[1:] for a, b, row in hits
        if not any(c <= a and b <= d and (c, d) != (a, b) and other[1] != row[1]
                   for c, d, other in hits)
    }


def find_pairs(conn: Conn) -> list[tuple[int, str, int, str, str]]:
    """(model_id, ime, document_id, url, tekst) za modele sa NULL poljem i najave o njima.

    Najava novog modela često pominje i prethodni („Following Mistral Large 4…“). Zato par
    nastaje za modele imenovane u naslovu, a bez njih samo ako uvod pominje tačno jedan model.
    Par sa nerešenim `extraction_failed` u review_queue se preskače (NFR-R-004).
    """
    missing = sql.SQL(" OR ").join(sql.SQL("m.{} IS NULL").format(sql.Identifier(f))
                                   for f in LLM_FIELDS)
    # Svi modeli, ne samo nepotpuni: pomen potpunog modela takođe čini najavu dvosmislenom.
    aliases: list[Row] = conn.execute(sql.SQL(
        "SELECT a.alias_norm, m.id, m.name, {} FROM model_aliases a "
        "JOIN models m ON m.id = a.model_id WHERE length(a.alias_norm) >= %s ORDER BY m.id"
    ).format(missing), (MIN_ALIAS_LEN,)).fetchall()
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
        matched = _longest(title.lower(), aliases)
        if not matched:
            matched = _longest(f"{title}\n{content[:LEAD_CHARS]}".lower(), aliases)
            if len({model_id for model_id, _, _ in matched}) > 1:
                continue
        pairs += [(model_id, name, doc_id, url, content)
                  for model_id, name, incomplete in sorted(matched)
                  if incomplete and (model_id, doc_id) not in failed]
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
    start = llm.budget.calls()
    for model_id, name, doc_id, url, content in find_pairs(conn):
        # Iz `runs.llm_calls`: tačno broji i retry i plaćene neuspele pokušaje.
        if llm.budget.calls() - start >= MAX_CALLS:
            errors.append({"source": "llm", "kind": "limit",
                           "message": f"dostignut limit od {MAX_CALLS} poziva po pokretanju"})
            break
        try:
            fields, _ = llm.complete_json(
                "model_fields_v1", {"name": name, "text": content}, ModelFields
            )
        except BudgetExceeded as exc:  # FR-019: ostatak meseca bez LLM koraka
            errors.append({"source": "llm", "kind": "budget", "message": str(exc)})
            break
        except ValidationFailed:  # i odsečen izlaz: plaćen je, pa se ne ponavlja sutra
            conn.execute(
                "INSERT INTO review_queue (raw_name, candidate_model_id, reason, payload) "
                "VALUES (%s, %s, 'extraction_failed', %s)",
                (name, model_id, Jsonb({"document_id": doc_id, "url": url})),
            )
            continue
        except LLMError as exc:
            errors.append({"source": "llm", "kind": "error", "message": f"{name}: {exc}"})
            continue
        apply_fields(conn, model_id, fields, url)
    return errors
