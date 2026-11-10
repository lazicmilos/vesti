from datetime import UTC, datetime

import httpx
import pytest
from conftest import fixture_bytes, offline_client

from aitracker.sources.base import EmptySource, SourceError
from aitracker.sources.hackernews import HackerNewsSource, parse_hits


def test_parse_hits_stvarni_odgovor_vraca_price_sa_urlom_i_poenima() -> None:
    items = parse_hits(fixture_bytes("hackernews.json"))

    assert [(item.url, item.hn_points) for item in items] == [
        ("https://www.wired.com/story/meet-the-sad-wives-of-ai/", 49),
        ("https://evanxmerz.com/post/ai-usage-generates-a-fragile-codebase/", 29),
        ("https://connect.queenslibrary.org/", 47),
    ]


def test_parse_hits_prica_bez_urla_se_preskace() -> None:
    body = b'{"hits": [{"title": "Ask HN", "url": null, "points": 111, "created_at_i": 1}]}'

    assert parse_hits(body) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<html>502 Bad Gateway</html>", id="nevazeca-nije-json"),
        pytest.param(b'{"message": "rate limited"}', id="nevazeca-bez-hits"),
        pytest.param(b'{"hits": [{"url": "https://a.com", "points": 5}]}',
                     id="nevazeca-hit-bez-vremena"),
    ],
)
def test_parse_hits_neispravan_odgovor_baca_source_error(body: bytes) -> None:
    with pytest.raises(SourceError, match="neispravan HN odgovor"):
        parse_hits(body)


def _source(body: bytes, seen: list[httpx.Request]) -> HackerNewsSource:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(request)
        return httpx.Response(200, content=body)

    return HackerNewsSource("hackernews", "https://hn.example/search_by_date",
                            offline_client(handler), min_points=20)


def test_fetch_salje_filter_po_vremenu_i_poenima() -> None:
    seen: list[httpx.Request] = []
    source = _source(fixture_bytes("hackernews.json"), seen)

    source.fetch(datetime.fromtimestamp(1794051504, tz=UTC))

    assert seen[0].url.params["numericFilters"] == "created_at_i>1794051504,points>=20"
    assert seen[0].url.params["tags"] == "story"


def test_fetch_bez_pogodaka_baca_empty_source() -> None:
    source = _source(b'{"hits": []}', [])

    with pytest.raises(EmptySource, match="hackernews"):
        source.fetch(datetime(2026, 1, 1, tzinfo=UTC))
