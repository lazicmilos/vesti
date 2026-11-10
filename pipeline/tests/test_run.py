from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from conftest import fixture_bytes, offline_client

from aitracker.config import SourceConfig, SourcesFile, load_sources
from aitracker.db import Conn
from aitracker.run import Ctx, run

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
EMPTY_FEED = b'<rss version="2.0"><channel><title>x</title></channel></rss>'
HN_BODY = (b'{"hits": [{"title": "t", "points": 300, "created_at_i": 1794300000, "url": '
           b'"https://www.openai.com/index/closing-ai-guidance-gap-education/?ref=hn"}]}')

CONFIG = SourcesFile(sources=[
    SourceConfig(name="openai-blog", kind="rss", role="both", weight=1.5,
                 url="https://openai.example/rss.xml"),
    SourceConfig(name="techcrunch", kind="rss", role="news", url="https://tc.example/feed"),
    SourceConfig(name="iskljucen", kind="rss", role="news", enabled=False,
                 url="https://off.example/feed"),
    SourceConfig(name="hackernews", kind="api", role="signal", url="https://hn.example/search"),
])


def _ctx(overrides: dict[str, httpx.Response] | None = None) -> Ctx:
    responses = {
        "openai.example": httpx.Response(200, content=fixture_bytes("openai.xml")),
        "tc.example": httpx.Response(200, content=fixture_bytes("techcrunch.xml")),
        "hn.example": httpx.Response(200, content=HN_BODY),
        **(overrides or {}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return responses[request.url.host]

    return Ctx(now=NOW, config=CONFIG, client=offline_client(handler))


def _last_run(conn: Conn) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, new_docs, errors, finished_at IS NOT NULL FROM runs ORDER BY id DESC"
    ).fetchone()
    assert row is not None
    return row


def test_sources_yaml_je_ispravan_i_ima_omogucene_izvore() -> None:
    config = load_sources()

    assert {s.name for s in config.sources if s.enabled} >= {"openai-blog", "hackernews"}
    assert not any(s.enabled for s in config.sources if s.name in {"anthropic-blog",
                                                                   "meta-ai-blog"})


@pytest.mark.db
def test_run_svi_izvori_rade_status_ok_i_dokumenti_upisani(conn: Conn) -> None:
    status = run(conn, _ctx())

    assert status == "ok"
    assert _last_run(conn) == ("ok", 6, [], True)


@pytest.mark.db
def test_run_hn_poeni_se_upisuju_u_dokument_sa_istim_urlom(conn: Conn) -> None:
    run(conn, _ctx())

    rows = conn.execute("SELECT url_canonical FROM documents WHERE hn_points = 300").fetchall()
    assert rows == [("https://openai.com/index/closing-ai-guidance-gap-education",)]


@pytest.mark.db
def test_run_ponovno_pokretanje_ne_pravi_duplikate(conn: Conn) -> None:
    run(conn, _ctx())

    run(conn, _ctx())

    assert _last_run(conn)[:2] == ("ok", 0)
    assert conn.execute("SELECT count(*) FROM documents").fetchone() == (6,)
    assert conn.execute("SELECT count(*) FROM sources").fetchone() == (4,)


@pytest.mark.db
@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(httpx.Response(500), id="izvor-ne-odgovara"),
        pytest.param(httpx.Response(200, content=b"<html>greska"), id="neispravan-odgovor"),
    ],
)
def test_run_jedan_izvor_otkaze_ostali_obradjeni_status_partial(
    conn: Conn, broken: httpx.Response
) -> None:
    status = run(conn, _ctx({"openai.example": broken}))

    run_status, new_docs, errors, _ = _last_run(conn)
    assert status == run_status == "partial"
    assert new_docs == 3
    assert [(e["source"], e["kind"]) for e in errors] == [("openai-blog", "error")]


@pytest.mark.db
def test_run_iskljucen_izvor_se_ne_poziva(conn: Conn) -> None:
    # handler nema odgovor za off.example: poziv bi bacio KeyError
    assert run(conn, _ctx()) == "ok"


def _insert_empty_run(conn: Conn, days_ago: int, source: str = "techcrunch") -> None:
    conn.execute(
        "INSERT INTO runs (started_at, status, errors) VALUES (%s, 'ok', %s::jsonb)",
        (NOW - timedelta(days=days_ago),
         f'[{{"source": "{source}", "kind": "empty", "message": "m"}}]'),
    )


@pytest.mark.db
@pytest.mark.parametrize(
    ("previous_empty_days", "expected"),
    [
        pytest.param([], "ok", id="bva-prvi-prazan-dan"),
        pytest.param([1], "ok", id="bva-drugi-prazan-dan"),
        pytest.param([1, 2], "partial", id="bva-treci-prazan-dan"),
        pytest.param([2, 3], "ok", id="pogadjanje-juce-nije-bio-prazan"),
    ],
)
def test_run_prazan_izvor_tek_treci_dan_zaredom_daje_partial(
    conn: Conn, previous_empty_days: list[int], expected: str
) -> None:
    for days_ago in previous_empty_days:
        _insert_empty_run(conn, days_ago)

    status = run(conn, _ctx({"tc.example": httpx.Response(200, content=EMPTY_FEED)}))

    assert status == expected
    errors = _last_run(conn)[2]
    assert [(e["source"], e["kind"]) for e in errors] == [("techcrunch", "empty")]


@pytest.mark.db
def test_run_poruka_o_trodnevnoj_praznini_imenuje_izvor(conn: Conn) -> None:
    _insert_empty_run(conn, 1)
    _insert_empty_run(conn, 2)

    run(conn, _ctx({"tc.example": httpx.Response(200, content=EMPTY_FEED)}))

    message = _last_run(conn)[2][0]["message"]
    assert "techcrunch" in message and "3 dana zaredom" in message


@pytest.mark.db
def test_run_tudji_prazni_dani_se_ne_racunaju(conn: Conn) -> None:
    _insert_empty_run(conn, 1, source="drugi-izvor")
    _insert_empty_run(conn, 2, source="drugi-izvor")

    status = run(conn, _ctx({"tc.example": httpx.Response(200, content=EMPTY_FEED)}))

    assert status == "ok"


@pytest.mark.db
def test_run_neocekivan_izuzetak_oznacava_run_kao_failed(conn: Conn) -> None:
    ctx = _ctx()
    del ctx.config  # izaziva AttributeError usred ingest-a

    with pytest.raises(AttributeError):
        run(conn, ctx)

    assert _last_run(conn)[0] == "failed"
