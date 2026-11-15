import gzip
from datetime import UTC, datetime

import httpx
import pytest
from conftest import fixture_bytes, offline_client

from aitracker.config import SourceConfig, SourcesFile
from aitracker.db import Conn
from aitracker.normalize import canonical_url, content_hash
from aitracker.run import Ctx, run
from aitracker.sources.fulltext import MAX_CHARS, extract_text
from aitracker.sources.rss import parse_feed

LE_CHONK = "https://mistral.ai/news/mistral-large-4-oss/"


def _page(name: str) -> str:
    return gzip.decompress(fixture_bytes(name)).decode()


def test_extract_text_mistral_najava_ima_naslov_licencu_i_cene() -> None:
    text = extract_text(_page("mistral_page.html.gz"))

    assert text.splitlines()[0] == "Mistral Large 4 (Le Chonk) is now open weight | Mistral"
    assert "Apache 2.0" in text and "/M Tokens" in text
    assert "function(" not in text and "{" not in text.splitlines()[0]
    assert len(text) <= MAX_CHARS


def test_extract_text_deepmind_naslov_je_prvi_red() -> None:
    lines = extract_text(_page("deepmind_page.html.gz")).splitlines()

    assert lines[0] == "Gemini Omni 1.2 Flash: 15-second video and lower pricing"
    assert "Today, we’re rolling out" in lines


@pytest.mark.db
def test_run_zamenjuje_rss_tekst_punim_a_hash_ostaje(conn: Conn) -> None:
    config = SourcesFile(lookback_hours=100_000, sources=[SourceConfig(
        name="mistral-blog", kind="rss", role="both", fulltext=True,
        url="https://mistral.ai/rss.xml")])
    page = gzip.decompress(fixture_bytes("mistral_page.html.gz"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/rss.xml":
            return httpx.Response(200, content=fixture_bytes("mistral.xml"))
        if request.url.path.rstrip("/") == "/news/mistral-large-4-oss":
            return httpx.Response(200, content=page, headers={"content-type": "text/html"})
        return httpx.Response(403)

    ctx = Ctx(now=datetime(2026, 11, 15, tzinfo=UTC), config=config, client=offline_client(handler))
    assert run(conn, ctx) == "ok"  # neuspelo preuzimanje stranice ne menja status

    item = next(i for i in parse_feed(fixture_bytes("mistral.xml")) if i.url == LE_CHONK)
    content, digest = conn.execute(
        "SELECT content, content_hash FROM documents WHERE url_canonical = %s",
        (canonical_url(LE_CHONK),)
    ).fetchone() or (None, None)
    assert content.startswith("Mistral Large 4 (Le Chonk) is now open weight")
    assert digest == content_hash(f"{item.title}\n{item.content}")

    errors = conn.execute("SELECT errors FROM runs").fetchone()[0]  # type: ignore[index]
    kinds = {e["kind"] for e in errors if e["source"] == "mistral-blog"}
    assert kinds == {"fulltext"}
