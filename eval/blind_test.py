"""Blind test LLM kandidata (SPEC 13, F3): isti izvori kroz 2–3 modela, anonimno za ocenjivanje.

Pokretanje (iz pipeline/):  uv run --env-file ../.env python ../eval/blind_test.py
Drugi kandidati:            ... blind_test.py --models anthropic/claude-haiku-5.5,openai/gpt-6-luna

Skripta piše `blind_test.csv` (vlasnik ocenjuje) i `blind_test_key.json` (mapiranje oznaka na
modele i trošak po modelu). Ključ se otvara tek posle ocenjivanja. Ocene upisuje samo vlasnik
(SPEC 0.6). Trošak ide u novi red `runs`, pa ulazi u mesečni budžet (NFR-C-001).
"""

import argparse
import csv
import html
import json
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from aitracker.budget import Budget, BudgetExceeded
from aitracker.config import database_url, llm_settings
from aitracker.db import Conn, connect
from aitracker.llm.client import LLMClient, LLMError
from aitracker.llm.schemas import EventSummary

HERE = Path(__file__).parent
OUT_CSV = HERE / "blind_test.csv"
OUT_KEY = HERE / "blind_test_key.json"
SAMPLE_SIZE = 30
LAB_SHARE = 15  # najave laboratorija su glavni ulaz trackera, pa čine pola uzorka
LAB_SOURCES = ("openai-blog", "deepmind-blog", "mistral-blog")
SEED = 20261115
MAX_CHARS = 8000  # ponytail: grubo sečenje teksta; dovoljno dok su ulazi RSS sažeci i članci
DEFAULT_MODELS = (
    "anthropic/claude-haiku-5.5", "openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash",
)
LABELS = "ABC"
HEADER = ["doc_id", "source_url", "source_text", "label", "title_sr", "summary_sr", "category",
          "mentioned_models", "error", "unsupported_claim", "serbian_quality", "notes"]
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Doc:
    id: int
    source: str
    url: str
    text: str  # tačno ono što model dobija


@dataclass(frozen=True)
class Output:
    """Izlaz jednog modela za jedan dokument; `error` je ime izuzetka ako izlaza nema."""

    summary: EventSummary | None = None
    error: str = ""


def plain_text(title: str, content: str) -> str:
    text = html.unescape(_TAG.sub(" ", content))
    return f"{title}\n\n{' '.join(text.split())}"[:MAX_CHARS]


def select(docs: list[Doc], rng: random.Random, size: int = SAMPLE_SIZE) -> list[Doc]:
    """Do LAB_SHARE dokumenata laboratorija, ostatak iz vesti; manjak jedne grupe puni druga."""
    lab = [d for d in docs if d.source in LAB_SOURCES]
    news = [d for d in docs if d.source not in LAB_SOURCES]
    picked = rng.sample(lab, min(LAB_SHARE, len(lab)))
    picked += rng.sample(news, min(size - len(picked), len(news)))
    rest = [d for d in lab if d not in picked]
    picked += rng.sample(rest, min(size - len(picked), len(rest)))
    return picked


def anonymize(
    docs: list[Doc], outputs: dict[tuple[int, str], Output], models: list[str],
    rng: random.Random,
) -> tuple[list[list[str]], dict[str, dict[str, str]]]:
    """Redovi za CSV i ključ {doc_id: {oznaka: model}}.

    Mapiranje je nasumično za svaki dokument, pa stil jednog modela ne vezuje stalno slovo.
    Redosled dokumenata je promešan; unutar dokumenta redovi idu A, B, C radi poređenja.
    """
    order = docs[:]
    rng.shuffle(order)
    rows, key = [], {}
    for doc in order:
        shuffled = models[:]
        rng.shuffle(shuffled)
        key[str(doc.id)] = dict(zip(LABELS, shuffled, strict=False))
        for label, model in zip(LABELS, shuffled, strict=False):
            out = outputs[(doc.id, model)]
            s = out.summary
            rows.append([
                str(doc.id), doc.url, doc.text, label,
                s.title_sr if s else "", s.summary_sr if s else "",
                (s.category or "") if s else "", "; ".join(s.mentioned_models) if s else "",
                out.error, "", "", "",
            ])
    return rows, key


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)


def _run_cost(conn: Conn, run_id: int) -> Decimal:
    row = conn.execute("SELECT cost_usd FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert row is not None
    return Decimal(row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    models = parser.parse_args().models.split(",")
    if not 2 <= len(models) <= len(LABELS):
        print(f"Treba 2–{len(LABELS)} modela, dato {len(models)}.")
        return 1
    if OUT_CSV.exists() or OUT_KEY.exists():
        print(f"{OUT_CSV.name} ili {OUT_KEY.name} već postoji; obriši ručno za novo pokretanje.")
        return 1
    _, api_key = llm_settings()
    rng = random.Random(SEED)
    now = datetime.now(UTC)
    with connect(database_url()) as conn:
        rows = conn.execute(
            "SELECT d.id, s.name, d.url_canonical, d.title, d.content FROM documents d "
            "JOIN sources s ON s.id = d.source_id "
            "WHERE d.content IS NOT NULL AND d.content <> '' ORDER BY d.id"
        ).fetchall()
        docs = select([Doc(r[0], r[1], r[2], plain_text(r[3], r[4])) for r in rows], rng)
        run_id = conn.execute(
            "INSERT INTO runs (started_at) VALUES (%s) RETURNING id", (now,)
        ).fetchone()[0]  # type: ignore[index]
        budget = Budget(conn, run_id, now)
        clients = {m: LLMClient(conn, budget, m, api_key) for m in models}
        outputs: dict[tuple[int, str], Output] = {}
        ok: Counter[str] = Counter()
        failed: Counter[str] = Counter()
        cost = dict.fromkeys(models, Decimal(0))
        status = "ok"
        try:
            for i, doc in enumerate(docs, 1):
                print(f"[{i}/{len(docs)}] dokument {doc.id}")
                for model in models:
                    before = _run_cost(conn, run_id)
                    try:
                        summary, _ = clients[model].complete_json(
                            "event_summary_v1", {"text": doc.text}, EventSummary)
                        outputs[(doc.id, model)] = Output(summary)
                        ok[model] += 1
                    except LLMError as exc:
                        outputs[(doc.id, model)] = Output(error=type(exc).__name__)
                        failed[model] += 1
                        status = "partial"
                    cost[model] += _run_cost(conn, run_id) - before
        except BudgetExceeded as exc:
            status = "partial"
            print(f"Prekinuto: {exc}")
            done = {d for d, _ in outputs}
            docs = [d for d in docs if d.id in done and all((d.id, m) in outputs for m in models)]
        finally:
            conn.execute("UPDATE runs SET finished_at = now(), status = %s WHERE id = %s",
                         (status, run_id))
    csv_rows, mapping = anonymize(docs, outputs, models, rng)
    write_csv(OUT_CSV, csv_rows)
    stats = {m: {"ok": ok[m], "failed": failed[m], "cost_usd": str(cost[m])} for m in models}
    OUT_KEY.write_text(json.dumps({"mapping": mapping, "stats": stats}, indent=2,
                                  ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Upisano {len(docs)} dokumenata u {OUT_CSV.name}; ključ je u {OUT_KEY.name}.")
    for model, s in stats.items():
        print(f"  {model}: uspešno {s['ok']}, neuspelo {s['failed']}, trošak {s['cost_usd']} USD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
