"""Metrike evaluacije (SPEC 13): poredi tracker sa oznakama vlasnika i ispisuje Markdown tabelu.

Pokretanje (iz pipeline/):  uv run --env-file ../.env python ../eval/run_eval.py

Za sada samo `models_gold.csv` (kapije F2 i F3). Red se računa kao označen kad vlasnik upiše
`official_url`; prazna `gold_*` ćelija u označenom redu znači da zvanični izvor ne navodi
vrednost. Skupovi `cluster_pairs.csv` i `summaries_review.csv` dolaze u F4.
"""

import csv
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aitracker.config import database_url
from aitracker.db import connect

GOLD_CSV = Path(__file__).parent / "models_gold.csv"
FIELDS = ("org", "released_at", "params_b", "context_window", "price_in", "price_out",
          "license", "open_weights")
NUMERIC = {"params_b", "context_window", "price_in", "price_out"}
TARGET_ACCURACY = 0.95


def same(name: str, tracked: Any, gold: str) -> bool:
    """Da li vrednost iz trackera odgovara zlatnoj vrednosti iz CSV-a."""
    if name in NUMERIC:
        return math.isclose(float(tracked), float(gold), rel_tol=1e-9, abs_tol=1e-9)
    if name == "open_weights":
        return bool(tracked) == (gold.strip().lower() == "true")
    if name == "released_at":
        return str(tracked) == gold.strip()
    # Naziv organizacije i licence: bez razlike u velikim slovima, razmacima i interpunkciji
    # („mistralai“ = „Mistral AI“, „Apache-2.0“ = „Apache 2.0“).
    return re.sub(r"[^a-z0-9]", "", str(tracked).lower()) == re.sub(r"[^a-z0-9]", "", gold.lower())


@dataclass
class Score:
    correct: Counter[str] = field(default_factory=Counter)
    wrong: Counter[str] = field(default_factory=Counter)
    # Vrednost koju je upisao LLM, a zvanični izvor je ne navodi: izmišljena (cilj: 0).
    invented: Counter[str] = field(default_factory=Counter)
    mismatches: list[str] = field(default_factory=list)


def score(
    gold_rows: list[dict[str, str]], tracker: dict[str, dict[str, tuple[Any, str]]]
) -> tuple[Score, Score, int, int]:
    """(sva polja, samo LLM polja, broj označenih redova, broj duplikata).

    `tracker` je slug → polje → (vrednost, izvor iz `field_sources`).
    """
    every, llm = Score(), Score()
    labeled = [r for r in gold_rows if r["official_url"].strip()]
    for row in labeled:
        values = tracker.get(row["slug"], {})
        for name in FIELDS:
            value, source = values.get(name, (None, ""))
            if value is None:
                continue  # meri se tačnost ne-null polja (FR-003: NULL nije greška)
            gold = row[f"gold_{name}"].strip()
            targets = [every, llm] if source.startswith("llm:") else [every]
            for s in targets:
                if not gold:
                    if s is llm:
                        s.invented[name] += 1
                        s.mismatches.append(f"{row['slug']}.{name}: {value!r}, izvor ne navodi")
                elif same(name, value, gold):
                    s.correct[name] += 1
                else:
                    s.wrong[name] += 1
                    s.mismatches.append(f"{row['slug']}.{name}: {value!r} ≠ {gold!r} ({source})")
    duplicates = sum(1 for r in labeled if r["duplicate_of"].strip())
    return every, llm, len(labeled), duplicates


def _count(counter: Counter[str], name: str | None) -> int:
    """Broj za jedno polje, ili zbir svih kad je `name` None (red „ukupno“)."""
    return counter[name] if name else sum(counter.values())


def _ratio(correct: int, total: int) -> str:
    return f"{correct / total:.1%} ({correct}/{total})" if total else "—"


def markdown(every: Score, llm: Score, labeled: int, duplicates: int) -> str:
    lines = [
        f"Označenih modela: {labeled}. Duplikata: {duplicates} (cilj 0).",
        "",
        "| Polje | Tačno, sva polja | Tačno, LLM polja | Izmišljeno (LLM) |",
        "| --- | --- | --- | --- |",
    ]
    for name in (*FIELDS, None):
        ok, bad = _count(every.correct, name), _count(every.wrong, name)
        llm_ok, llm_bad = _count(llm.correct, name), _count(llm.wrong, name)
        lines.append(f"| {name or '**ukupno**'} | {_ratio(ok, ok + bad)} "
                     f"| {_ratio(llm_ok, llm_ok + llm_bad)} | {_count(llm.invented, name)} |")
    llm_total = sum(llm.correct.values()) + sum(llm.wrong.values())
    lines.append("")
    lines.append(
        f"Kapija F3: LLM tačnost ≥ {TARGET_ACCURACY:.0%} i 0 izmišljenih. "
        f"LLM vrednosti u uzorku: {llm_total + sum(llm.invented.values())}."
    )
    return "\n".join(lines)


def load_tracker() -> dict[str, dict[str, tuple[Any, str]]]:
    columns = ", ".join(FIELDS)
    with connect(database_url()) as conn:
        rows = conn.execute(
            f"SELECT slug, field_sources, {columns} FROM models"  # noqa: S608 — konstante
        ).fetchall()
    return {
        slug: {name: (value, sources.get(name, "")) for name, value in zip(FIELDS, rest,
                                                                             strict=True)}
        for slug, sources, *rest in rows
    }


def main() -> int:
    with GOLD_CSV.open(encoding="utf-8") as handle:
        gold_rows = list(csv.DictReader(handle))
    every, llm, labeled, duplicates = score(gold_rows, load_tracker())
    if not labeled:
        print("Nijedan red nema `official_url`; prvo označi modele u models_gold.csv.")
        return 1
    print(markdown(every, llm, labeled, duplicates))
    if every.mismatches or llm.mismatches:
        print("\nRazlike (za proveru):")
        for line in dict.fromkeys(every.mismatches + llm.mismatches):
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
