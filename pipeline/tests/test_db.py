import pytest

from aitracker.db import Conn, migrate

TABLES = {
    "schema_migrations", "sources", "documents", "events", "event_documents", "models",
    "model_aliases", "model_price_history", "model_events", "review_queue", "llm_cache", "runs",
}


@pytest.mark.db
def test_migrate_pravi_sve_tabele_iz_specifikacije(conn: Conn) -> None:
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    ).fetchall()

    assert {row[0] for row in rows} == TABLES


@pytest.mark.db
def test_migrate_ponovno_pokretanje_ne_primenjuje_nista(conn: Conn) -> None:
    # fixture je već primenio migracije
    assert migrate(conn) == []
    assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [("001_init",)]
