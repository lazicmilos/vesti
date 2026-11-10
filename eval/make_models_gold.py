"""Pravi šablon eval/models_gold.csv: 50 nasumičnih modela iz baze, sa praznim zlatnim kolonama.

Pokretanje (iz pipeline/):  uv run --env-file ../.env python ../eval/make_models_gold.py
Zlatne kolone popunjava vlasnik ručno, sa zvaničnih stranica (SPEC 0.6). Skripta zato ne
upisuje vrednosti koje je pipeline izvukao i odbija da pregazi postojeći fajl.
"""

import csv
import os
import random
import sys
from pathlib import Path

import psycopg

OUT = Path(__file__).parent / "models_gold.csv"
SAMPLE_SIZE = 50
SEED = 20261110  # isti uzorak pri ponovnom pokretanju nad istom bazom
GOLD = ["gold_org", "gold_released_at", "gold_params_b", "gold_context_window", "gold_price_in",
        "gold_price_out", "gold_license", "gold_open_weights"]
HEADER = ["slug", "name", "org", "source_url", *GOLD, "duplicate_of", "official_url", "notes"]


def main() -> int:
    if OUT.exists():
        print(f"{OUT} već postoji; obriši ga ručno ako stvarno hoćeš novi uzorak.")
        return 1
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute("SELECT slug, name, org, source_url FROM models ORDER BY slug").fetchall()
    sample = sorted(random.Random(SEED).sample(rows, min(SAMPLE_SIZE, len(rows))))
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows([*row, *[""] * (len(HEADER) - len(row))] for row in sample)
    print(f"Upisano {len(sample)} modela u {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
