"""Zajedničke fixture: fixture fajlovi, HTTP klijent bez mreže i baza u privremenoj šemi."""

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from aitracker.db import Conn, connect, migrate
from aitracker.sources.base import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"
Handler = Callable[[httpx.Request], httpx.Response]


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def offline_client(handler: Handler, sleeps: list[float] | None = None) -> PoliteClient:
    """Klijent čiji zahtevi idu u `handler`; pauze se beleže umesto da se čekaju."""
    record = sleeps if sleeps is not None else []
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=record.append)


@pytest.fixture
def conn() -> Iterator[Conn]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL nije postavljen")
    schema = f"test_{uuid.uuid4().hex}"
    with connect(url) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute(f"CREATE SCHEMA {schema}")  # noqa: S608 — ime je generisano ovde
        connection.execute(f"SET search_path TO {schema}, public")  # noqa: S608
        try:
            migrate(connection)
            yield connection
        finally:
            connection.execute(f"DROP SCHEMA {schema} CASCADE")  # noqa: S608
