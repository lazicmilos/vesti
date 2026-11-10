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
