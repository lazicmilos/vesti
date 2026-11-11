"""Interaktivna provera duplikata za eval/models_gold.csv (kapija F2).

Pokretanje (iz pipeline/):  uv run --env-file ../.env python ../eval/duplicate_candidates.py
Nastavak posle prekida:     ... duplicate_candidates.py --start 23

Za svaki model iz uzorka skripta nađe najsličnije modele iz cele `models` tabele, iz svih
organizacija, jer bag u identitetu može da upiše isti model pod drugom organizacijom. Vlasnik
bira: broj kandidata ako je isti model, Enter ako nije. Skripta upisuje samo `duplicate_of`,
i to samo ono što vlasnik izabere (SPEC 0.6). Sličnost je namerno nezavisna od
`aitracker.identity.normalize`: alat koji proverava identitet ne sme da deli njegove greške.
"""

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from rapidfuzz import fuzz, process

GOLD_CSV = Path(__file__).parent / "models_gold.csv"
LIMIT = 5
MIN_SCORE = 60
_NON_ALNUM = re.compile(r"[^a-z0-9.]+")


@dataclass(frozen=True)
class Model:
    slug: str
    name: str
    org: str | None
    source_url: str


def match_key(slug: str, name: str) -> str:
    """Ime i slug kao skup reči: redosled, crtice i velika slova ne utiču na sličnost."""
    return _NON_ALNUM.sub(" ", f"{name} {slug}".lower()).strip()


def candidates(target: Model, models: list[Model]) -> list[tuple[Model, float]]:
    """Najsličniji modeli osim samog `target`, od najsličnijeg; najviše LIMIT."""
    others = [m for m in models if m.slug != target.slug]
    hits = process.extract(
        match_key(target.slug, target.name),
        [match_key(m.slug, m.name) for m in others],
        scorer=fuzz.token_set_ratio,
        limit=LIMIT,
        score_cutoff=MIN_SCORE,
    )
    return [(others[index], score) for _, score, index in hits]


def save(rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    # Upis preko privremenog fajla: prekid usred upisa ne sme da pokvari već unete oznake.
    tmp = GOLD_CSV.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(GOLD_CSV)


def ask(row: dict[str, str], found: list[tuple[Model, float]]) -> str | None:
    """Vraća slug duplikata, "" ako nema duplikata, ili None za izlaz."""
    current = row["duplicate_of"]
    now = f", trenutno: {current}" if current else ""
    prompt = f"  izbor [Enter = nije duplikat{now}, p = preskoči, q = sačuvaj i izađi]: "
    while True:
        answer = input(prompt).strip().lower()
        if answer == "q":
            return None
        if answer == "p":
            return current
        if answer == "":
            return ""
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            return found[int(answer) - 1][0].slug
        print("  nepoznat izbor")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=int, default=1, help="redni broj modela od kog se kreće")
    args = parser.parse_args()

    with GOLD_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        models = [Model(*r) for r in conn.execute(
            "SELECT slug, name, org, source_url FROM models ORDER BY slug").fetchall()]
    print(f"{len(rows)} modela u uzorku, {len(models)} u trackeru.\n")

    for number, row in enumerate(rows, start=1):
        if number < args.start:
            continue
        target = Model(row["slug"], row["name"], row["org"] or None, row["source_url"])
        found = candidates(target, models)
        print(f"[{number}/{len(rows)}] {target.name}  ({target.org or '?'})  {target.slug}")
        print(f"  {target.source_url}")
        if not found:
            print("  nema sličnih modela\n")
            continue
        for index, (model, score) in enumerate(found, start=1):
            print(f"  {index}) {model.name}  ({model.org or '?'})  {model.slug}  [{score:.0f}]")
            print(f"     {model.source_url}")
        choice = ask(row, found)
        if choice is None:
            print(f"\nSačuvano. Nastavak: --start {number}")
            return 0
        row["duplicate_of"] = choice
        save(rows, fieldnames)
        print()

    duplicates = [r["slug"] for r in rows if r["duplicate_of"]]
    print(f"Gotovo. Duplikata: {len(duplicates)}" + (f" ({', '.join(duplicates)})" if duplicates
                                                    else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
