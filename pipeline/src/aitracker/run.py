"""CLI orkestrator dnevnog pipeline-a: `python -m aitracker.run`."""

import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from aitracker.config import SourceConfig, SourcesFile, database_url, load_sources, setup_logging
from aitracker.db import Conn, connect, migrate
from aitracker.dedup import insert_new, update_hn_points
from aitracker.sources.base import (
    EmptySource,
    ModelSource,
    PoliteClient,
    Source,
    SourceError,
)
from aitracker.sources.hackernews import HackerNewsSource
from aitracker.sources.huggingface import HuggingFaceSource
from aitracker.sources.openrouter import OpenRouterSource
from aitracker.sources.rss import RssSource
from aitracker.tracker import upsert_models

log = logging.getLogger("aitracker.run")
EMPTY_DAYS_LIMIT = 3  # NFR-R-003


@dataclass
class Ctx:
    now: datetime
    config: SourcesFile
    client: PoliteClient


@dataclass
class StepResult:
    new_docs: int = 0
    new_models: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


def build_source(cfg: SourceConfig, client: PoliteClient) -> Source:
    if cfg.kind == "rss":
        return RssSource(cfg.name, cfg.url, client)
    if cfg.name == "hackernews":
        return HackerNewsSource(cfg.name, cfg.url, client, cfg.min_points)
    raise SourceError(f"nema klijenta za izvor {cfg.name}")


def build_model_source(cfg: SourceConfig, client: PoliteClient) -> ModelSource:
    if cfg.name == "openrouter":
        return OpenRouterSource(cfg.name, cfg.url, client)
    if cfg.name == "huggingface":
        return HuggingFaceSource(cfg.name, cfg.url, client, cfg.min_likes)
    raise SourceError(f"nema klijenta za izvor {cfg.name}")


def sync_sources(conn: Conn, config: SourcesFile) -> dict[str, int]:
    """Usklađuje tabelu `sources` sa sources.yaml; vraća mapu ime → id."""
    ids = {}
    for cfg in config.sources:
        row = conn.execute(
            """
            INSERT INTO sources (name, kind, role, url, weight, enabled)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET kind = EXCLUDED.kind, role = EXCLUDED.role,
                url = EXCLUDED.url, weight = EXCLUDED.weight, enabled = EXCLUDED.enabled
            RETURNING id
            """,
            (cfg.name, cfg.kind, cfg.role, cfg.url, cfg.weight, cfg.enabled),
        ).fetchone()
        assert row is not None
        ids[cfg.name] = row[0]
    return ids


def ingest(conn: Conn, ctx: Ctx) -> StepResult:
    """Preuzimanje po izvoru (izolovano), upis dokumenata bez duplikata i upis modela."""
    result = StepResult()
    ids = sync_sources(conn, ctx.config)
    since = ctx.now - timedelta(hours=ctx.config.lookback_hours)
    # Signal izvori idu poslednji da bi videli i dokumente upisane u ovom pokretanju.
    enabled = sorted((c for c in ctx.config.sources if c.enabled), key=lambda c: c.role == "signal")
    for cfg in enabled:
        try:
            if cfg.role == "tracker":
                models = build_model_source(cfg, ctx.client).fetch_models()
                with conn.transaction():
                    count, queued = upsert_models(
                        conn, cfg.name, ids[cfg.name], models, ctx.config.org_aliases
                    )
                result.new_models += count
                fetched, extra = len(models), {"review_queue": queued}
            else:
                items = build_source(cfg, ctx.client).fetch(since)
                with conn.transaction():
                    if cfg.role == "signal":
                        count = update_hn_points(conn, items)
                    else:
                        count = insert_new(conn, ids[cfg.name], items)
                        result.new_docs += count
                fetched, extra = len(items), {}
        except EmptySource as exc:
            result.errors.append({"source": cfg.name, "kind": "empty", "message": str(exc)})
        except SourceError as exc:
            result.errors.append({"source": cfg.name, "kind": "error", "message": str(exc)})
        else:
            log.info("izvor obrađen", extra={"data": {
                "source": cfg.name, "items": fetched, "written": count, **extra}})
    return result


def empty_streak(conn: Conn, run_id: int, source: str, now: datetime) -> bool:
    """Da li je izvor bio prazan i u svakom od prethodnih dana do granice NFR-R-003."""
    today = now.astimezone(UTC).date()
    row = conn.execute(
        """
        SELECT count(DISTINCT (started_at AT TIME ZONE 'UTC')::date) FROM runs
        WHERE id <> %s
          AND (started_at AT TIME ZONE 'UTC')::date >= %s
          AND (started_at AT TIME ZONE 'UTC')::date < %s
          AND errors @> %s
        """,
        (run_id, today - timedelta(days=EMPTY_DAYS_LIMIT - 1), today,
         Jsonb([{"source": source, "kind": "empty"}])),
    ).fetchone()
    assert row is not None
    return bool(row[0] == EMPTY_DAYS_LIMIT - 1)


def run(conn: Conn, ctx: Ctx) -> str:
    """Izvršava pipeline, upisuje red u `runs` (NFR-O-001) i vraća status."""
    migrate(conn)
    row = conn.execute("INSERT INTO runs (started_at) VALUES (%s) RETURNING id", (ctx.now,))
    run_id: int = row.fetchone()[0]  # type: ignore[index]
    try:
        result = ingest(conn, ctx)
    except Exception as exc:
        fatal = [{"kind": "fatal", "message": type(exc).__name__}]
        _close_run(conn, run_id, "failed", StepResult(), fatal)
        raise
    partial = False
    for error in result.errors:
        if error["kind"] == "error":
            partial = True
        elif empty_streak(conn, run_id, error["source"], ctx.now):
            partial = True
            error["message"] += f" ({EMPTY_DAYS_LIMIT} dana zaredom)"
    status = "partial" if partial else "ok"
    _close_run(conn, run_id, status, result, result.errors)
    log.info("pokretanje završeno", extra={"data": {
        "run_id": run_id, "status": status, "new_docs": result.new_docs,
        "new_models": result.new_models, "errors": result.errors}})
    return status


def _close_run(
    conn: Conn, run_id: int, status: str, result: StepResult, errors: list[dict[str, str]]
) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = now(), status = %s, new_docs = %s, new_models = %s, "
        "errors = %s WHERE id = %s",
        (status, result.new_docs, result.new_models, Jsonb(errors), run_id),
    )


def main() -> int:
    setup_logging()
    with connect(database_url()) as conn:
        run(conn, Ctx(now=datetime.now(UTC), config=load_sources(), client=PoliteClient()))
    # `partial` je ispravan ishod (izlaz 0); `failed` izlazi kroz izuzetak.
    return 0


if __name__ == "__main__":
    sys.exit(main())
