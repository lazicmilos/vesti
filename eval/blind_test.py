"""Blind test LLM kandidata (SPEC 13): isti izvori kroz sve kandidate, anonimno ocenjivanje.

Pokretanje (iz pipeline/, treba DATABASE_URL za keš i OPENROUTER_API_KEY):
  uv run --env-file ../.env python ../eval/blind_test.py generate
  uv run python ../eval/blind_test.py score

`generate` preuzima sveže članke iz RSS izvora vesti, za svaki pravi sažetak sa svakim kandidatom
(prompt `event_summary_v1`) i piše `blind_test_rate.csv` sa oznakama A/B/C, izmešanim posebno za
svaki izvor. Koja oznaka je koji model piše u `blind_test_key.b64` (base64, da se ne pročita
slučajno); ne otvaraj ga pre ocenjivanja. Tekst članaka se ne čuva u repou (NFR-L-001): za
proveru vernosti otvori link. `score` posle ocenjivanja otkriva mapiranje i ispisuje tabelu.
"""

import base64
import csv
import html
import json
import os
import random
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aitracker.budget import Budget, BudgetExceeded
from aitracker.config import database_url, load_glossary, load_sources
from aitracker.db import connect, migrate
from aitracker.llm.client import LlmClient, ValidationFailed, load_prices
from aitracker.llm.openrouter import OpenRouterProvider, ProviderError
from aitracker.llm.schemas import EventSummary
from aitracker.sources.base import PoliteClient, RawItem, SourceError
from aitracker.sources.rss import RssSource

HERE = Path(__file__).parent
RATE = HERE / "blind_test_rate.csv"
KEY = HERE / "blind_test_key.b64"
CANDIDATES = ["anthropic/claude-haiku-5.5", "google/gemini-3.1-flash-lite",
              "deepseek/deepseek-v4.1-flash"]
SAMPLE_SIZE = 30
MIN_CHARS, MAX_CHARS = 600, 6000  # dovoljno za sažetak; gornja granica drži trošak malim
SEED = 20261111
SCORES = {"1", "2", "3", "4", "5"}
HEADER = ["id", "label", "source_title", "source_url", "title_sr", "summary_sr", "category",
          "faithful", "serbian", "notes"]
_TAG, _SPACE = re.compile(r"<[^>]*>"), re.compile(r"\s+")


def plain_text(raw: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()


def collect_articles() -> list[RawItem]:
    """Članci iz omogućenih RSS izvora vesti sa dovoljno teksta, nasumičan uzorak."""
    client, since = PoliteClient(), datetime.now(UTC) - timedelta(days=14)
    items: list[RawItem] = []
    for cfg in load_sources().sources:
        if not (cfg.enabled and cfg.kind == "rss"):
            continue
        try:
            items += RssSource(cfg.name, cfg.url, client).fetch(since)
        except SourceError as exc:
            print(f"izvor {cfg.name} preskočen: {exc}")
    usable = [i for i in items if len(plain_text(i.content)) >= MIN_CHARS]
    return random.Random(SEED).sample(usable, min(SAMPLE_SIZE, len(usable)))


def generate() -> int:
    if RATE.exists():
        print(f"{RATE.name} već postoji; obriši ga ručno za novi test.")
        return 1
    articles = collect_articles()
    print(f"{len(articles)} članaka; kandidati: {', '.join(CANDIDATES)}")
    glossary, prices = load_glossary(), load_prices()
    rows: list[list[object]] = []
    labels_by_id: dict[str, dict[str, str]] = {}
    failures: dict[str, int] = defaultdict(int)
    costs: dict[str, Decimal] = defaultdict(Decimal)
    rng = random.Random(SEED)
    # U cloud sesiji ključ ubacuje mrežni proxy; lokalno dolazi iz .env.
    api_key = os.environ.get("OPENROUTER_API_KEY", "proxy-injected")
    with connect(database_url()) as conn:
        migrate(conn)
        budget = Budget.from_db(conn, datetime.now(UTC))
        clients = {m: LlmClient(conn, OpenRouterProvider(m, api_key), budget, prices)
                   for m in CANDIDATES}
        for number, article in enumerate(articles, start=1):
            text = (f"Naslov: {article.title}\nIzvor: {article.url}\n\n"
                    f"{plain_text(article.content)[:MAX_CHARS]}")
            labels = rng.sample("ABC", len(CANDIDATES))
            labels_by_id[str(number)] = dict(zip(labels, CANDIDATES, strict=True))
            for label, model in sorted(zip(labels, CANDIDATES, strict=True)):
                try:
                    summary, usage = clients[model].complete_json(
                        "event_summary_v1", {"text": text, "glossary": glossary}, EventSummary)
                except (ValidationFailed, ProviderError) as exc:
                    failures[model] += 1
                    rows.append([number, label, article.title, article.url,
                                 "", f"GREŠKA: {exc}", "", "", "", ""])
                    continue
                except BudgetExceeded as exc:
                    print(f"budžet: {exc}")
                    return 1
                costs[model] += usage.cost_usd
                rows.append([number, label, article.title, article.url, summary.title_sr,
                             summary.summary_sr, summary.category or "", "", "", ""])
            print(f"[{number}/{len(articles)}] {article.title[:70]}")
    key = {"labels": labels_by_id, "failures": failures,
           "cost_usd": {m: str(c) for m, c in costs.items()}}
    with RATE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    KEY.write_text(base64.b64encode(json.dumps(key).encode()).decode() + "\n")
    print(f"Upisano {len(rows)} sažetaka u {RATE.name}; ukupan trošak {sum(costs.values())} USD")
    return 0


def score() -> int:
    key = json.loads(base64.b64decode(KEY.read_text()))
    with RATE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    unrated = [r for r in rows if not r["summary_sr"].startswith("GREŠKA")
               and (r["faithful"] not in ("da", "ne") or r["serbian"] not in SCORES)]
    if unrated:
        print(f"Neocenjeno ili neispravno ocenjeno: {len(unrated)} redova "
              f"(faithful = da/ne, serbian = 1–5), npr. id {unrated[0]['id']}{unrated[0]['label']}")
        return 1
    stats: dict[str, list[tuple[bool, int]]] = defaultdict(list)
    for row in rows:
        if not row["summary_sr"].startswith("GREŠKA"):
            model = key["labels"][row["id"]][row["label"]]
            stats[model].append((row["faithful"] == "da", int(row["serbian"])))
    print("| Model | Vernih | Srpski (1–5) | Neuspešnih | Trošak (USD) |")
    print("| --- | --- | --- | --- | --- |")
    for model in CANDIDATES:
        rated = stats[model]
        faithful = sum(f for f, _ in rated) / len(rated) if rated else 0.0
        serbian = sum(s for _, s in rated) / len(rated) if rated else 0.0
        print(f"| {model} | {faithful:.0%} | {serbian:.2f} | {key['failures'].get(model, 0)} "
              f"| {key['cost_usd'].get(model, '0')} |")
    return 0


if __name__ == "__main__":
    commands = {"generate": generate, "score": score}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(2)
    sys.exit(commands[sys.argv[1]]())
