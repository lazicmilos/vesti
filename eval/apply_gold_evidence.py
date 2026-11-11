"""Prenosi vrednosti koje je vlasnik potvrdio iz models_gold_evidence.csv u models_gold.csv.

Pokretanje (iz pipeline/):  uv run python ../eval/apply_gold_evidence.py

Kandidate (vrednost, zvanični URL, doslovan citat) sme da prikupi asistent; u zlatni skup ulazi
samo red sa `owner_check = da` (SPEC 0.6). Kolone `gold_*` i `official_url` se svaki put pišu
iznova iz evidence fajla, pa je on jedini izvor istine; ostale kolone se ne diraju.
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
EVIDENCE = HERE / "models_gold_evidence.csv"
GOLD = HERE / "models_gold.csv"
FORMATS = {
    "released_at": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "params_b": re.compile(r"\d+(\.\d+)?"),
    "context_window": re.compile(r"\d+"),
    "price_in": re.compile(r"\d+(\.\d+)?"),
    "price_out": re.compile(r"\d+(\.\d+)?"),
    "open_weights": re.compile(r"true|false"),
    "license": re.compile(r"[a-z0-9.+-]+"),
}


def problems(row: dict[str, str]) -> list[str]:
    """Greške u jednom redu; prazna vrednost je ispravna i znači da izvor ne navodi polje."""
    value, check = row["value"].strip(), row["owner_check"].strip()
    found = []
    if check not in ("", "da", "ne"):
        found.append(f"owner_check mora biti da, ne ili prazno, a ne {check!r}")
    if not value:
        return found
    pattern = FORMATS.get(row["field"])
    if pattern and not pattern.fullmatch(value):
        found.append(f"vrednost {value!r} nije u formatu za {row['field']}")
    if not row["official_url"].strip() or not row["quote"].strip():
        found.append("vrednost bez official_url ili citata")
    return found


def main() -> int:
    with EVIDENCE.open(newline="", encoding="utf-8") as handle:
        evidence = list(csv.DictReader(handle))
    errors = [f"red {n}: {p}" for n, row in enumerate(evidence, start=2) for p in problems(row)]
    if errors:
        print("\n".join(errors))
        return 1

    gold: dict[str, dict[str, str]] = defaultdict(dict)
    urls: dict[str, list[str]] = defaultdict(list)
    pending = 0
    for row in evidence:
        value = row["value"].strip()
        if value and row["owner_check"].strip() == "":
            pending += 1
        if value and row["owner_check"].strip() == "da":
            gold[row["slug"]][f"gold_{row['field']}"] = value
            if row["official_url"] not in urls[row["slug"]]:
                urls[row["slug"]].append(row["official_url"].strip())

    with GOLD.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        for name in fieldnames:
            if name.startswith("gold_"):
                row[name] = gold[row["slug"]].get(name, "")
        row["official_url"] = " ".join(urls[row["slug"]])
    with GOLD.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    applied = sum(len(values) for values in gold.values())
    print(f"Upisano {applied} potvrđenih vrednosti; čeka proveru vlasnika: {pending}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
