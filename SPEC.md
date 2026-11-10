# SPEC — Tracker AI modela i tech vesti na srpskom

```
Naziv dokumenta:  Specifikacija za implementaciju — AI Tracker (radni naziv)
Oznaka:           SPEC-AIT-001
Verzija:          1.1
Datum:            10.11.2026.
Autor:            Miloš Lazić
Status:           Odobreno za implementaciju
```

| Verzija | Datum | Autor | Opis izmene |
| --- | --- | --- | --- |
| 1.0 | 10.11.2026. | Miloš Lazić | Prva verzija za implementaciju |
| 1.1 | 10.11.2026. | Miloš Lazić | Dodato pravilo 0.10: podela uloga modela (pisanje koda / pregled) |

---

## 0. Uputstvo za agenta koji implementira

Ovaj dokument je jedini izvor istine za projekat. Pročitaj ga ceo pre prvog commita.

**Pravila rada (obavezna):**

1. Radi **strogo po fazama** iz odeljka 14. Ne počinji fazu N+1 dok kapija faze N nije prošla i dok vlasnik projekta to ne potvrdi.
2. Na kraju svake faze **stani** i napiši izveštaj: šta je urađeno, rezultat kapije (brojevi), otvoreni problemi, šta tražiš od vlasnika. Ne nastavljaj samoinicijativno.
3. Jedan zadatak = jedna grana = jedan PR do ~400 linija. Commit poruke po Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
4. **Ne menjaj šemu baze, format JSON izvoza ni javne interfejse modula** bez novog ADR-a u `docs/adr/` i odobrenja vlasnika.
5. **Ne izmišljaj činjenice o eksternim API-jima.** Pre pisanja klijenta za izvor, pozovi endpoint, sačuvaj stvarni odgovor kao fixture u `pipeline/tests/fixtures/` i piši parser prema njemu. Ako se endpoint razlikuje od onoga što ovaj dokument pretpostavlja, zabeleži razliku u PR-u.
6. **Ne pravi zlatne oznake za evaluaciju.** Skupove u `eval/` označava vlasnik ručno. Ti praviš šablone (CSV sa kandidatima) i skripte koje računaju metrike. Oznake koje generiše model čine evaluaciju besmislenom.
7. Tajne idu isključivo u env promenljive i GitHub Secrets. `.env` je u `.gitignore`. Nikad ne loguj ključeve.
8. Kad naiđeš na odluku koju ovaj dokument ne pokriva: ako je reverzibilna i lokalna, odluči i zapiši je u opis PR-a; ako utiče na šemu, troškove, izvore ili javni interfejs, **pitaj**.
9. Testovi nikad ne pristupaju mreži. Svi testovi rade nad fixture fajlovima.
10. **Podela uloga modela.** Kod piše Opus 5.5 (`/model opus 5.5`). Fable 5.2 (`/model fable 5.2`) pregleda velike i bitne delove pre spajanja u `main`. Model menja vlasnik; agent ne može sam da ga promeni. Pregled je obavezan za:
    - svaki PR na kapiji faze (odeljak 14);
    - šemu baze i migracije (odeljak 8);
    - identitet modela (10.1) i upis u `review_queue`;
    - LLM klijent, keš i budžet (odeljak 11, NFR-C-001);
    - format JSON izvoza (12.1);
    - svaki PR veći od ~400 linija.

    Nalaz pregleda se upisuje u PR kao komentar; autor odgovara na svaki nalaz izmenom ili obrazloženjem.

---

## 1. Pregled proizvoda

Web aplikacija na srpskom (latinica) sa dva povezana dela:

- **Tracker modela (jezgro):** svaki novi AI model je strukturirani zapis — organizacija, datum, broj parametara, context window, cena, licenca, open-weights, srpski sažetak, linkovi na izvore. Lista sa filterima, stranica modela, poređenje.
- **Dnevni feed vesti (sekundarno):** najviše 10 najvažnijih tech događaja dnevno, sa srpskim naslovom i sažetkom.

Spoj: događaj koji pominje model vodi na stranicu tog modela; stranica modela prikazuje sve povezane događaje.

**Diferencijator:** strukturirani tracker modela na srpskom ne postoji. Opšte AI vesti na srpskom već pokrivaju veliki portali, zato feed vesti ostaje uzak.

---

## 2. Obim

**U v1:** tracker (lista, filteri, stranica modela, poređenje 2–3 modela), dnevni feed, arhiva po danima, srpski sažeci, automatski pipeline jednom dnevno, javni statički sajt, evaluacija sa objavljenim metrikama.

**Van obima v1 (ne implementirati, ni delimično):** korisnički nalozi i login, komentari, email i push notifikacije, ćirilica, mobilna aplikacija, X/Twitter i Reddit kao izvori, sopstveno pokretanje benchmarka, monetizacija, API server.

---

## 3. Pretpostavke i ograničenja

- Budžet za LLM API: **tvrda granica 5 USD mesečno** (videti NFR-C-001).
- Hosting: sve komponente rade na besplatnim planovima (Cloudflare Pages, Neon Free, GitHub Actions). Nijedan deo sistema ne zahteva server koji stalno radi: pipeline se pokreće jednom dnevno i gasi se, sajt su statički fajlovi, a baza se uspavljuje kad se ne koristi.
- Pipeline se izvršava u GitHub Actions (CPU, bez GPU).
- Ceo tekst članaka se nikad ne objavljuje. Interno se čuva samo onoliko dugo koliko traje obrada.
- Benchmark rezultati se prenose samo iz zvaničnih izvora, uvek sa linkom.

---

## 4. Tehnički stack

| Sloj | Izbor | Napomena |
| --- | --- | --- |
| Jezik pipeline-a | Python 3.12 | `uv` za zavisnosti, `pyproject.toml` |
| HTTP | `httpx` | timeout 20 s, retry sa eksponencijalnim backoff-om (3 pokušaja) |
| Validacija | `pydantic` v2 | svaki LLM izlaz i svaki API odgovor prolazi kroz šemu |
| Baza | PostgreSQL 16 + `pgvector` | pristup preko `psycopg` 3, **bez ORM-a** |
| Migracije | numerisani SQL fajlovi + tabela `schema_migrations` | mali runner u `db.py` |
| RSS | `feedparser` | |
| Fuzzy poređenje | `rapidfuzz` | za identitet modela |
| Embeddinzi | `sentence-transformers`, podrazumevano `intfloat/multilingual-e5-small` | proveri dimenziju vektora pri implementaciji i uskladi `vector(N)` u migraciji |
| LLM | apstraktni klijent; provajder i model iz env (`LLM_PROVIDER`, `LLM_MODEL`) | konačan model bira se blind testom u F3 |
| Frontend | Next.js (App Router), TypeScript strict, `output: 'export'` | statički sajt, bez serverskog koda |
| Stil | Tailwind CSS | |
| Kvalitet | `ruff`, `mypy --strict`, `pytest`; ESLint + `tsc --noEmit` | sve u CI-ju |
| Raspored | GitHub Actions `schedule` | jednom dnevno, 05:00 UTC |
| Lokalni razvoj | `docker-compose.yml` sa `pgvector/pgvector:pg16` | |

**ADR-001 (već odlučeno):** v1 nema API server. Pipeline posle obrade izvozi statičke JSON fajlove, a sajt ih čita. Filtriranje i poređenje rade u pregledaču. FastAPI se uvodi tek kad izvoz preraste nekoliko MB ili zatreba pretraga arhive. Napiši ovaj ADR u `docs/adr/0001-staticki-izvoz.md` u F1.

---

## 5. Struktura repozitorijuma

```
.
├── SPEC.md
├── README.md
├── docker-compose.yml
├── .env.example
├── docs/
│   └── adr/
├── pipeline/
│   ├── pyproject.toml
│   ├── migrations/
│   │   └── 001_init.sql
│   ├── config/
│   │   ├── sources.yaml        # izvori, težine, uloge
│   │   ├── ranking.yaml        # parametri skora i klasterisanja
│   │   ├── glossary.yaml       # rečnik termina za promptove
│   │   └── llm_prices.yaml     # cena po tokenu po modelu, za obračun troška
│   ├── src/aitracker/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── run.py              # CLI orkestrator: `python -m aitracker.run`
│   │   ├── budget.py
│   │   ├── sources/
│   │   │   ├── base.py         # Protocol Source
│   │   │   ├── openrouter.py
│   │   │   ├── huggingface.py
│   │   │   ├── rss.py
│   │   │   └── hackernews.py
│   │   ├── normalize.py
│   │   ├── dedup.py
│   │   ├── identity.py
│   │   ├── embed.py
│   │   ├── cluster.py
│   │   ├── rank.py
│   │   ├── link.py
│   │   ├── export.py
│   │   └── llm/
│   │       ├── client.py
│   │       ├── cache.py
│   │       ├── schemas.py
│   │       └── prompts/
│   │           ├── model_fields_v1.md
│   │           └── event_summary_v1.md
│   └── tests/
│       └── fixtures/
├── eval/
│   ├── README.md
│   ├── cluster_pairs.csv
│   ├── models_gold.csv
│   ├── summaries_review.csv
│   └── run_eval.py
├── web/
│   ├── public/data/            # generiše export.py, ne menja se ručno
│   └── src/app/
└── .github/workflows/
    ├── ci.yml
    └── daily.yml
```

---

## 6. Funkcionalni zahtevi

Prioritet: **M** = mora u v1, **S** = treba ako stigne, **C** = može (backlog).

### 6.1 Tracker

| ID | Zahtev (EARS) | Prioritet |
| --- | --- | --- |
| FR-001 | Kada se pipeline pokrene, sistem mora preuzeti listu modela iz OpenRouter i Hugging Face izvora. | M |
| FR-002 | Sistem mora za svaki model čuvati: naziv, organizaciju, datum izdanja, broj parametara (u milijardama), context window (tokeni), cenu ulaza i izlaza (USD po 1M tokena), licencu, open-weights (da/ne), srpski sažetak i link na izvor. | M |
| FR-003 | Ako izvor ne navodi vrednost polja, onda sistem mora sačuvati `NULL` i nikad ne sme proceniti vrednost. | M |
| FR-004 | Ako vrednost polja daje strukturirani API, onda sistem ne sme da je prepiše vrednošću iz LLM ekstrakcije. | M |
| FR-005 | Ako naziv modela nije tačno poklopljen sa postojećim aliasom, a sličan je postojećem modelu iste organizacije, onda sistem mora upisati zapis u `review_queue` umesto da kreira novi model. | M |
| FR-006 | Kada se cena postojećeg modela promeni, sistem mora upisati novi red u `model_price_history`. | M |
| FR-007 | Sistem mora prikazati listu modela sa filterima: organizacija, licenca, open-weights, raspon cene ulaza, minimalni context window; i sortiranjem po datumu izdanja i ceni. | M |
| FR-008 | Sistem mora prikazati stranicu modela sa svim poljima, linkovima na izvore, istorijom cene i povezanim događajima. | S |
| FR-009 | Sistem mora omogućiti poređenje 2–3 modela jedan pored drugog preko URL-a `/uporedi?m=slug1,slug2,slug3`. | S |

### 6.2 Vesti

| ID | Zahtev (EARS) | Prioritet |
| --- | --- | --- |
| FR-010 | Kada se pipeline pokrene, sistem mora preuzeti nove stavke iz svih omogućenih RSS izvora i Hacker News API-ja. | M |
| FR-011 | Ako dokument ima isti kanonski URL ili isti hash sadržaja kao postojeći, onda sistem mora da ga preskoči. | M |
| FR-012 | Sistem mora grupisati dokumente o istom događaju u jedan događaj (pravila u 10.2). | M |
| FR-013 | Sistem mora za svaki događaj sačuvati srpski naslov (do 90 znakova), sažetak od 2–4 rečenice, kategoriju i linkove na sve izvorne dokumente. | M |
| FR-014 | Sistem mora prikazati dnevni feed sa najviše 10 događaja iznad praga skora, najviše 4 po kategoriji. | M |
| FR-015 | Ako događaj pominje model koji postoji u trackeru, onda sistem mora povezati događaj sa tim modelom u `model_events`. | M |
| FR-016 | Sistem mora prikazati arhivu feeda po danima. | S |
| FR-017 | Sistem može izvoziti dnevni feed kao RSS. | C |

### 6.3 Ostalo

| ID | Zahtev (EARS) | Prioritet |
| --- | --- | --- |
| FR-018 | Sistem mora imati stranicu „Kako radi“ koja navodi da sažetke generiše AI, nabraja izvore i objašnjava formulu skora. | M |
| FR-019 | Ako mesečni trošak LLM-a dostigne budžet, onda sistem mora preskočiti sve LLM korake do kraja meseca i označiti pokretanje kao `partial`. | M |

---

## 7. Nefunkcionalni zahtevi

| ID | Zahtev |
| --- | --- |
| NFR-C-001 | Ukupan trošak LLM API-ja mora biti ≤ 5 USD po kalendarskom mesecu; provera pre svakog LLM poziva (`budget.py`). |
| NFR-R-001 | Pipeline mora raditi 30 uzastopnih dana bez ručne intervencije. |
| NFR-R-002 | Ako jedan izvor ne odgovori ili vrati neispravan odgovor, onda ostali izvori moraju biti obrađeni normalno, a greška upisana u `runs.errors`. |
| NFR-R-003 | Ako izvor 3 uzastopna dana vrati 0 stavki, onda pokretanje mora biti označeno kao `partial` sa porukom koja imenuje izvor. |
| NFR-R-004 | Ponovno pokretanje istog dana ne sme napraviti duplikate niti potrošiti nove LLM pozive za već obrađen sadržaj (idempotentnost). |
| NFR-F-001 | Novi model mora biti vidljiv na sajtu najkasnije 24 h nakon pojave u izvoru. |
| NFR-P-001 | Stranica liste modela mora se učitati za < 1,5 s na emulaciji „Fast 4G“ u Lighthouse-u; Lighthouse Performance ≥ 90. |
| NFR-L-001 | Javno se objavljuju samo naslov, metapodaci, sopstveni sažetak i link. Interni tekst dokumenta (`documents.content`) mora biti obrisan (`NULL`) 7 dana posle obrade i nikad ne ulazi u izvoz. |
| NFR-L-002 | Klijenti izvora moraju poštovati `robots.txt`, slati identifikacioni `User-Agent` sa kontakt URL-om repozitorijuma i čekati najmanje 1 s između zahteva istom hostu. |
| NFR-T-001 | Svako polje modela i svaki sažetak na sajtu ima link na izvor. |
| NFR-M-001 | `mypy --strict` i `tsc --noEmit` prolaze bez grešaka; `ruff` bez upozorenja. |
| NFR-M-002 | Pokrivenost testovima ≥ 80% za `normalize.py`, `dedup.py`, `identity.py`, `rank.py`, `cluster.py` i sve parsere izvora. |
| NFR-O-001 | Svako pokretanje upisuje red u `runs`: vreme, status, broj novih dokumenata i modela, greške, broj LLM poziva, trošak u USD. |
| NFR-U-001 | Sav tekst interfejsa je na srpskom, latinicom. Datumi u formatu `10. 11. 2026.` |
| NFR-A-001 | Sajt ispunjava WCAG 2.1 AA za kontrast i navigaciju tastaturom; Lighthouse Accessibility ≥ 95. |

---

## 8. Model podataka

`pipeline/migrations/001_init.sql` — implementiraj tačno ovako. Dimenziju vektora (`384`) uskladi sa stvarnim embedding modelom.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id       SERIAL PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE,
  kind     TEXT NOT NULL CHECK (kind IN ('api', 'rss')),
  role     TEXT NOT NULL CHECK (role IN ('tracker', 'news', 'signal', 'both')),
  url      TEXT NOT NULL,
  weight   REAL NOT NULL DEFAULT 1.0 CHECK (weight BETWEEN 0.5 AND 1.5),
  enabled  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE documents (
  id             BIGSERIAL PRIMARY KEY,
  source_id      INT NOT NULL REFERENCES sources(id),
  url_canonical  TEXT NOT NULL UNIQUE,
  title          TEXT NOT NULL,
  published_at   TIMESTAMPTZ,
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  content_hash   CHAR(64) NOT NULL UNIQUE,     -- sha256 normalizovanog teksta
  content        TEXT,                         -- interno; briše se po NFR-L-001
  hn_points      INT,
  embedding      vector(384),
  processed_at   TIMESTAMPTZ
);
CREATE INDEX documents_published_idx ON documents (published_at);

CREATE TABLE events (
  id          BIGSERIAL PRIMARY KEY,
  title_sr    TEXT,
  summary_sr  TEXT,
  category    TEXT CHECK (category IN ('ai', 'hardware', 'big_tech', 'security')),
  score       REAL NOT NULL DEFAULT 0,
  centroid    vector(384) NOT NULL,
  first_seen  TIMESTAMPTZ NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  feed_date   DATE                                -- dan u čijem feedu se pojavio; NULL = nije ušao
);

CREATE TABLE event_documents (
  event_id     BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  PRIMARY KEY (event_id, document_id)
);

CREATE TABLE models (
  id              SERIAL PRIMARY KEY,
  slug            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  org             TEXT,
  released_at     DATE,
  params_b        NUMERIC,
  context_window  INT,
  price_in        NUMERIC,      -- USD po 1M ulaznih tokena
  price_out       NUMERIC,      -- USD po 1M izlaznih tokena
  license         TEXT,
  open_weights    BOOLEAN,
  summary_sr      TEXT,
  source_url      TEXT NOT NULL,
  field_sources   JSONB NOT NULL DEFAULT '{}',  -- {"price_in": "openrouter", "params_b": "llm:<url>"}
  verified        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_aliases (
  alias_norm  TEXT PRIMARY KEY,
  alias_raw   TEXT NOT NULL,
  model_id    INT NOT NULL REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE model_price_history (
  id           BIGSERIAL PRIMARY KEY,
  model_id     INT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  price_in     NUMERIC,
  price_out    NUMERIC,
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_events (
  model_id  INT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  event_id  BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  PRIMARY KEY (model_id, event_id)
);

CREATE TABLE review_queue (
  id                  BIGSERIAL PRIMARY KEY,
  raw_name            TEXT NOT NULL,
  source_id           INT REFERENCES sources(id),
  candidate_model_id  INT REFERENCES models(id),
  reason              TEXT NOT NULL CHECK (reason IN ('similar_name', 'extraction_failed', 'conflicting_value')),
  payload             JSONB NOT NULL DEFAULT '{}',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at         TIMESTAMPTZ
);

CREATE TABLE llm_cache (
  key             CHAR(64) PRIMARY KEY,   -- sha256(content_hash + prompt_version + model)
  prompt_version  TEXT NOT NULL,
  model           TEXT NOT NULL,
  output          JSONB NOT NULL,
  input_tokens    INT NOT NULL,
  output_tokens   INT NOT NULL,
  cost_usd        NUMERIC NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE runs (
  id           BIGSERIAL PRIMARY KEY,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  status       TEXT CHECK (status IN ('ok', 'partial', 'failed')),
  new_docs     INT NOT NULL DEFAULT 0,
  new_models   INT NOT NULL DEFAULT 0,
  llm_calls    INT NOT NULL DEFAULT 0,
  cost_usd     NUMERIC NOT NULL DEFAULT 0,
  errors       JSONB NOT NULL DEFAULT '[]'
);
```

Za dodelu klastera koristi linearno pretraživanje nad događajima iz poslednjih 72 h (stotine redova). HNSW indeks dodaj tek ako merenje pokaže potrebu.

---

## 9. Izvori podataka

Izvori su definisani u `config/sources.yaml`, ne u kodu. Svaki klijent implementira:

```python
class Source(Protocol):
    name: str
    def fetch(self, since: datetime) -> list[RawItem]: ...
```

| Izvor | Uloga | Pristup | Napomena |
| --- | --- | --- | --- |
| OpenRouter | tracker | REST lista modela (pretpostavka: `GET https://openrouter.ai/api/v1/models`) | Glavni izvor cena i context window-a. Proveri jedinicu cene u odgovoru i konvertuj u USD po 1M tokena. |
| Hugging Face Hub | tracker | REST API za modele | Samo open-weight modeli iznad praga popularnosti iz `sources.yaml`; inače šum. Proveri tačne parametre sortiranja. |
| Blogovi laboratorija: OpenAI, Anthropic, Google DeepMind, Meta AI, Mistral | both | RSS gde postoji | Težina 1.5. Ako lab nema RSS, izvor ostaje isključen i to se navodi u PR-u. Bez HTML scrapinga u v1. |
| The Verge, Ars Technica, TechCrunch | news | RSS | Težina 1.0. |
| Hacker News | signal | Algolia HN API | Popunjava `documents.hn_points` za dokumente čiji URL se poklapa. Ne pravi samostalne događaje. |

URL kanonizacija (`normalize.py`): lowercase host, ukloni `www.`, ukloni `utm_*`, `ref`, `fbclid`, `gclid` parametre, ukloni fragment i završnu kosu crtu, sortiraj preostale query parametre.

Hash sadržaja: sha256 nad tekstom posle uklanjanja HTML-a, spajanja razmaka i lowercase-a.

---

## 10. Pipeline

`python -m aitracker.run` izvršava korake redom. Svaki korak je funkcija `step(conn, ctx) -> StepResult`; greška u jednom koraku za jedan izvor ne prekida ostale (NFR-R-002).

1. **Ingest** — svi omogućeni izvori, izolovano po izvoru.
2. **Normalizacija i deduplikacija** — kanonski URL, hash, FR-011.
3. **Tok trackera:**
    1. Upis i ažuriranje modela iz strukturiranih izvora (bez LLM-a, osim za `summary_sr`).
    2. Identitet modela (10.1).
    3. LLM dopuna `NULL` polja iz zvaničnih najava laboratorija (FR-004).
4. **Tok vesti:**
    1. Embedding novih dokumenata.
    2. Klasterisanje (10.2).
    3. LLM sažetak za nove ili izmenjene događaje.
    4. Skor (10.3) i izbor feeda za današnji dan.
5. **Povezivanje** (`link.py`) — `mentioned_models` iz sažetka se normalizuju i traže u `model_aliases`; samo tačno poklapanje pravi red u `model_events`. Nema kreiranja modela.
6. **Čišćenje** — `documents.content = NULL` za dokumente obrađene pre više od 7 dana.
7. **Izvoz** (`export.py`) — JSON fajlovi (odeljak 12).
8. **Zatvaranje runa** — upis u `runs`.

### 10.1 Identitet modela

```
normalize(name):
  lowercase
  ukloni prefiks organizacije do "/" ("openai/gpt-5" → "gpt-5")
  ukloni datumske sufikse: -YYYY-MM-DD, -YYYYMMDD, -YYYY-MM, -MMDD
  zameni "_" i razmake sa "-", spoji uzastopne "-"
```

Pravila, tim redom:

1. `alias_norm` postoji → postojeći model; ako `alias_raw` nije zabeležen, ne dodaje se novi red (PK je `alias_norm`).
2. Nema poklapanja, a postoji model iste organizacije sa `rapidfuzz.fuzz.ratio ≥ 90` nad normalizovanim imenom → `review_queue` sa razlogom `similar_name`. **Ne kreira se model.**
3. Nema poklapanja i nema sličnog → novi model sa `verified = FALSE` + alias. Dozvoljeno **samo** za strukturirane izvore (OpenRouter, HF).
4. LLM nikad ne kreira model.

Napomena za testove: `-preview`, `-mini`, `-pro` i slični sufiksi **nisu** datumski i ostaju deo imena; to su različiti modeli.

### 10.2 Klasterisanje

- Kandidati: događaji sa `first_seen` u poslednjih `cluster_window_hours` (podrazumevano 72).
- Dokument ide u događaj sa najvećom kosinusnom sličnošću prema `centroid`, ako je ona ≥ `cluster_similarity` (podrazumevano 0,85); inače otvara novi događaj.
- Posle dodele, `centroid` = normalizovani prosek embeddinga svih dokumenata događaja.
- Parametri su u `config/ranking.yaml`; konačne vrednosti se podešavaju na `eval/cluster_pairs.csv` u F4.

### 10.3 Skor i feed

```
score = n_sources × mean_weight × (1 + log10(1 + hn_points_max)) × exp(−age_hours / tau_hours)
```

- `n_sources` = broj **različitih izvora** u događaju (ne broj dokumenata).
- `mean_weight` = prosečna `sources.weight` tih izvora.
- `hn_points_max` = najveći `hn_points` među dokumentima događaja (0 ako nema).
- `age_hours` = sati od `first_seen` do trenutka pokretanja; `tau_hours` podrazumevano 24.

Feed za dan D: događaji sa `score ≥ min_score` koji još nisu bili u feedu, sortirani po skoru, najviše `max_per_day` (10) ukupno i `max_per_category` (4) po kategoriji. Izabrani dobijaju `feed_date = D`. Događaj sa `category IS NULL` ne ulazi u feed. Prazan ili kratak feed je ispravno ponašanje.

---

## 11. LLM obrada

### 11.1 Klijent

- `llm/client.py` izlaže jednu funkciju: `complete_json(prompt_name, variables, schema) -> (BaseModel, Usage)`.
- Pre poziva: provera keša (`llm_cache`), pa provera budžeta (`budget.py`). Prekoračen budžet → `BudgetExceeded`, korak se preskače (FR-019).
- Izlaz se parsira u Pydantic šemu. Neuspela validacija → jedan retry sa porukom o grešci; drugi neuspeh → `review_queue` (`extraction_failed`).
- Trošak se računa iz broja tokena i `config/llm_prices.yaml`.
- `temperature = 0`.

### 11.2 Šeme (`llm/schemas.py`)

```python
class ModelFields(BaseModel):
    org: str | None
    released_at: date | None
    params_b: float | None
    context_window: int | None
    price_in: float | None          # USD po 1M tokena
    price_out: float | None
    license: str | None
    open_weights: bool | None
    summary_sr: str = Field(min_length=40, max_length=400)

Category = Literal["ai", "hardware", "big_tech", "security"]

class EventSummary(BaseModel):
    title_sr: str = Field(max_length=90)
    summary_sr: str = Field(min_length=80, max_length=700)   # 2–4 rečenice
    category: Category | None
    mentioned_models: list[str]     # imena tačno kako se pojavljuju u tekstu
```

### 11.3 Pravila promptova

Promptovi su Markdown fajlovi u `llm/prompts/` sa verzijom u imenu (`_v1`). Promena teksta = nova verzija = novi ključ keša. Svaki prompt mora sadržati:

1. Koristi isključivo priloženi tekst izvora. Bez znanja van teksta.
2. Polje koje tekst ne navodi eksplicitno vraća `null`. Ne procenjuj, ne zaokružuj, ne izvodi.
3. Piši na srpskom, latinicom, u neutralnom informativnom tonu, bez superlativa i reklamnog jezika.
4. Koristi termine iz priloženog rečnika (`glossary.yaml`) dosledno.
5. Vrati samo JSON po šemi, bez dodatnog teksta.

### 11.4 Rečnik (`config/glossary.yaml`, početna verzija)

```yaml
context window: kontekstni prozor
open-weight: otvorene težine
fine-tuning: fino podešavanje
inference: inferencija
reasoning model: model za rezonovanje
multimodal: multimodalni
benchmark: benchmark
token: token
```

---

## 12. Izvoz i frontend

### 12.1 JSON izvoz (`web/public/data/`)

| Fajl | Sadržaj |
| --- | --- |
| `meta.json` | `{ "generated_at", "model_count", "last_run_status" }` |
| `models.json` | niz svih modela, samo polja potrebna za listu i filtere |
| `models/{slug}.json` | pun zapis modela + `price_history` + `events` (id, datum, naslov) |
| `feed/{YYYY-MM-DD}.json` | događaji tog dana sa izvorima i povezanim modelima |
| `feed/index.json` | lista dostupnih datuma, najnoviji prvi |

Primer stavke u `models.json`:

```json
{
  "slug": "primer-model-1",
  "name": "Primer Model 1",
  "org": "Primer Lab",
  "released_at": "2026-11-01",
  "params_b": null,
  "context_window": 200000,
  "price_in": 1.0,
  "price_out": 5.0,
  "license": "proprietary",
  "open_weights": false,
  "verified": true
}
```

Izvoz je deterministički (sortirani ključevi, stabilan redosled), tako da `git diff` pokazuje samo stvarne promene.

### 12.2 Rute

| Ruta | Sadržaj |
| --- | --- |
| `/` | današnji feed + 5 najnovijih modela |
| `/modeli` | lista sa filterima i sortiranjem (FR-007), stanje filtera u URL query parametrima |
| `/modeli/[slug]` | stranica modela (FR-008) |
| `/uporedi` | poređenje preko `?m=` (FR-009), klijentska komponenta u `Suspense` |
| `/arhiva` i `/arhiva/[datum]` | arhiva feeda (FR-016) |
| `/kako-radi` | FR-018 |

Dizajn: čist, tipografski, bez dekoracije. Tabela modela je glavni element sajta i mora biti čitljiva na telefonu (horizontalni skrol unutar tabele, ne cele stranice). Light i dark tema po `prefers-color-scheme`.

---

## 13. Evaluacija

Sve u `eval/`. Agent piše `run_eval.py` i šablone; **vlasnik popunjava oznake.**

| Skup | Šta vlasnik označava | Metrika | Cilj |
| --- | --- | --- | --- |
| `cluster_pairs.csv` | 100 parova dokumenata: isti / različit događaj | preciznost, odziv | P ≥ 0,90, R ≥ 0,80 |
| `models_gold.csv` | 50 modela: tačne vrednosti polja sa zvaničnih stranica | duplikati; tačnost ne-null polja; broj izmišljenih vrednosti | 0; ≥ 95%; 0 |
| `summaries_review.csv` | 30 sažetaka: ima li nepodržanu tvrdnju (da/ne), ocena srpskog 1–5 | udeo vernih; prosečna ocena | ≥ 90%; ≥ 4,0 |

`run_eval.py` ispisuje Markdown tabelu rezultata koja se kopira u README. Za `cluster_pairs.csv` agent bira kandidate parove tako da otprilike polovina ima sličnost iznad praga, a polovina ispod, da skup ne bude trivijalan.

Blind test LLM-a (F3): isti 30 izvora kroz 2–3 kandidata; izlazi se mešaju i anonimizuju (`A`, `B`, `C`) pre ocenjivanja; mapiranje se otkriva tek posle ocena.

---

## 14. Faze, zadaci i kapije

Kapija = merljiv kriterijum. Na kapiji agent staje i podnosi izveštaj (pravilo 0.2).

### F1 — Temelji, ingest i deduplikacija

- [ ] Repo struktura, `pyproject.toml`, `docker-compose.yml`, `.env.example`, `.gitignore`
- [ ] `ci.yml`: ruff, mypy, pytest, (kasnije) web lint i build
- [ ] Migracija `001_init.sql` + runner
- [ ] `docs/adr/0001-staticki-izvoz.md`
- [ ] Fixtures za svaki izvor (stvarni odgovori), pa klijenti: RSS, Hacker News
- [ ] `normalize.py`, `dedup.py` sa testovima
- [ ] `run.py` sa upisom u `runs`
- [ ] `daily.yml` sa cron-om i `workflow_dispatch`

**Kapija F1:** daily workflow radi 7 uzastopnih dana sa statusom `ok` ili opravdanim `partial`; 0 duplikata u `documents`.

### F2 — Tracker modela

- [ ] Klijenti OpenRouter i Hugging Face (fixtures prvo)
- [ ] `identity.py` sa testovima za svako pravilo iz 10.1, uključujući sufikse koji nisu datumi
- [ ] Upis modela, aliasa i istorije cena; `review_queue`
- [ ] CLI `python -m aitracker.review` za pregled i rešavanje `review_queue` (spoji sa modelom / napravi novi / odbaci)
- [ ] Šablon `eval/models_gold.csv` sa 50 nasumičnih modela

**Kapija F2:** vlasnik je proverio 50 modela — 0 duplikata.

### F3 — LLM obrada i srpski

- [ ] `llm/client.py`, `cache.py`, `budget.py`, `schemas.py`
- [ ] Promptovi `model_fields_v1.md`, `event_summary_v1.md`
- [ ] Skripta za blind test 2–3 kandidata
- [ ] LLM dopuna `NULL` polja i `summary_sr` za modele

**Kapija F3:** blind test ocenjen, izabran model upisan u `.env.example` i README sa obrazloženjem; ekstrakcija ≥ 95% tačnih ne-null polja i 0 izmišljenih na `models_gold.csv`.

### F4 — Vesti

- [ ] `embed.py`, `cluster.py`, `rank.py`, `link.py` sa testovima
- [ ] Šablon `eval/cluster_pairs.csv` (100 parova)
- [ ] Podešavanje praga sličnosti na označenom skupu
- [ ] Sažeci događaja; šablon `eval/summaries_review.csv`

**Kapija F4:** klasterisanje P ≥ 0,90 i R ≥ 0,80; ≥ 90% vernih sažetaka; prosečna ocena srpskog ≥ 4,0.

### F5 — Frontend i deploy

- [ ] `export.py` po 12.1, deterministički
- [ ] Next.js sajt, sve rute iz 12.2
- [ ] Daily workflow posle izvoza commituje `web/public/data/` (bot nalog) i pokreće deploy
- [ ] Lighthouse provera

**Kapija F5:** javni link radi; NFR-P-001 i NFR-A-001 ispunjeni.

### F6 — 30 dana u produkciji

- [ ] Praćenje `runs`, ispravke grešaka kao issue + PR
- [ ] README: opis, arhitektonski dijagram, uputstvo za lokalno pokretanje, rezultati evaluacije, ograničenja

**Kapija F6:** 30 od 30 dana uspešno; trošak ≤ 5 USD mesečno; README kompletan.

---

## 15. Konvencije koda

- Python: tipovi na svim funkcijama, `mypy --strict`, bez `Any` osim na granici sa eksternim JSON-om (odmah validirati Pydantic-om). Funkcije kratke, čiste gde je moguće; I/O na ivicama.
- SQL: samo parametrizovani upiti. Nikad f-string sa vrednostima.
- Greške: specifični izuzeci (`SourceError`, `BudgetExceeded`, `ValidationFailed`), bez golog `except:`.
- Logovanje: strukturirano (JSON linije), bez tajni i bez punog teksta članaka.
- TypeScript: `strict: true`, tipovi za JSON izvoz u `web/src/lib/types.ts` usklađeni sa 12.1.
- Svaki modul u `pipeline/src` ima docstring sa jednom rečenicom o svrsi.
- README i ADR-ovi se ažuriraju u istom PR-u kao izmena koju opisuju.

---

## 16. Registar rizika

| ID | Rizik | V (1–5) | U (1–5) | V×U | Odgovor |
| --- | --- | --- | --- | --- | --- |
| R-01 | Širenje obima, vesti pojedu vreme trackera | 4 | 5 | 20 | Kapija F2 pre F4; sve van obima u backlog |
| R-02 | Duplikati modela zbog haosa u imenima | 4 | 5 | 20 | 10.1, `review_queue`, LLM ne kreira modele |
| R-03 | Izvor promeni format ili ugasi RSS | 3 | 3 | 9 | Izolacija po izvoru, fixtures, NFR-R-003 |
| R-04 | Halucinacije u sažecima | 3 | 5 | 15 | 11.3, eval vernosti, link uz svaki sažetak |
| R-05 | Loš srpski kod jeftinih modela | 3 | 3 | 9 | Blind test, rečnik |
| R-06 | Promena besplatnog tiera hostinga | 3 | 2 | 6 | Standardni Postgres, statički sajt |
| R-07 | Rast troška API-ja | 2 | 3 | 6 | Keš, budžet sa tvrdom granicom |
| R-08 | Autorska prava | 2 | 5 | 10 | NFR-L-001, samo sopstveni sažetak i link |

---

## 17. Otvorena pitanja i podrazumevano ponašanje

Dok vlasnik ne odluči, agent koristi podrazumevanu vrednost i ne blokira se.

| Pitanje | Podrazumevano dok se ne odluči |
| --- | --- |
| Konačno ime i domen | Radni naziv „AI Tracker“, paket `aitracker`; ime je u jednoj konstanti u `web/src/lib/site.ts`. Domen: .com preko Cloudflare Registrara, kupuje se pre F5; do tada sajt radi na `*.pages.dev` |
| Provajder produkcione baze | Lokalno Docker; produkcija preko `DATABASE_URL` secreta, provajder bira vlasnik pre F1 kapije |
| Hosting sajta | Odlučeno: Cloudflare Pages (besplatni tier dozvoljava komercijalnu upotrebu; Vercel Hobby ne). Ne koristiti funkcionalnosti specifične za Vercel |
| LLM provajder i model | Odluka posle blind testa u F3 |
| Rečnik: srpski ili engleski termin | Početna verzija iz 11.4 |

---

## 18. Definicija završenog (v1)

V1 je gotov kad su prošle sve kapije F1–F6, i kad osoba koja nije autor može da klonira repo, prati README, pokrene pipeline lokalno i dobije isti sajt — bez pitanja upućenih autoru.
