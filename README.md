# AI Tracker (radni naziv)

Tracker AI modela i dnevni feed tech vesti na srpskom. Pipeline se pokreće jednom dnevno,
prikuplja podatke iz izvora, i (od faze F5) izvozi statički sajt. Specifikacija je u
[SPEC.md](SPEC.md), arhitektonske odluke u [docs/adr/](docs/adr/).

**Stanje:** faza F1 (temelji, ingest, deduplikacija). Tracker modela, LLM obrada, vesti i sajt
dolaze u fazama F2–F5.

## Preduslovi

- [uv](https://docs.astral.sh/uv/) (sam instalira Python 3.12)
- Docker (za lokalni Postgres 16 sa `pgvector`)

## Pokretanje lokalno

```bash
docker compose up -d
```

```bash
cp .env.example .env
```

```bash
cd pipeline && uv sync
```

```bash
uv run --env-file ../.env python -m aitracker.run
```

Pokretanje samo primenjuje migracije, preuzima stavke iz izvora u `config/sources.yaml` i upisuje
red u tabelu `runs`. Ponovno pokretanje ne pravi duplikate.

## Testovi i provere

```bash
cd pipeline && uv run --env-file ../.env pytest --cov=aitracker --cov-branch
```

```bash
uv run ruff check . && uv run mypy
```

Testovi ne pristupaju mreži: rade nad stvarnim odgovorima izvora sačuvanim u
`pipeline/tests/fixtures/`. Testovi označeni sa `db` traže `TEST_DATABASE_URL` (rade u privremenoj
šemi koju brišu za sobom) i preskaču se ako promenljiva nije postavljena.

## Struktura

```
pipeline/
  config/sources.yaml     izvori, težine, uloge
  migrations/             numerisani SQL fajlovi
  src/aitracker/
    run.py                orkestrator, upis u `runs`
    db.py                 konekcija i runner migracija
    normalize.py          kanonski URL, hash sadržaja
    dedup.py              upis dokumenata bez duplikata
    sources/              klijenti izvora (RSS, Hacker News)
  tests/fixtures/         stvarni odgovori izvora
.github/workflows/        ci.yml (ruff, mypy, pytest), daily.yml (cron 05:00 UTC)
```

## Dnevno pokretanje (GitHub Actions)

`daily.yml` traži secret `DATABASE_URL` (Postgres 16 sa `pgvector` ekstenzijom, npr. Neon).
`schedule` radi samo sa podrazumevane grane repozitorijuma.

## Kako doprineti

Jedan zadatak = jedna grana = jedan PR do ~400 linija. Commit poruke po
[Conventional Commits](https://www.conventionalcommits.org/). Pravila rada su u SPEC.md, odeljak 0.
