from datetime import UTC, datetime

import httpx
import pytest
from conftest import fixture_bytes, offline_client

from aitracker.sources.base import EmptySource, SourceError
from aitracker.sources.rss import RssSource, parse_feed

EMPTY_FEED = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'


@pytest.mark.parametrize(
    ("fixture", "count", "first_url"),
    [
        ("openai.xml", 3, "https://openai.com/index/closing-ai-guidance-gap-education"),
        ("mistral.xml", 3, "https://mistral.ai/news/build-with-studio/"),
        ("techcrunch.xml", 3, "https://techcrunch.com/2026/11/09/"
                              "otter-ai-can-now-follow-conversations-across-30-languages/"),
        ("ars.xml", 3, "https://arstechnica.com/culture/2026/11/"
                       "dcu-shake-up-james-gunn-and-peter-safran-out-post-merger/"),
        ("verge.xml", 3, "https://www.theverge.com/tech/1029665/"
                         "seagate-firecuda-forge-hybrid-ssd-hard-drive-storage-alkemi-technology"),
    ],
)
def test_parse_feed_stvarni_feed_vraca_sve_stavke(fixture: str, count: int, first_url: str) -> None:
    items = parse_feed(fixture_bytes(fixture))

    assert len(items) == count
    assert items[0].url == first_url
    assert all(item.title and item.published_at is not None for item in items)


def test_parse_feed_deepmind_feed_u_jednoj_liniji_vraca_sve_stavke() -> None:
    items = parse_feed(fixture_bytes("deepmind.xml"))

    assert len(items) == 3
    assert items[0].title.startswith("Gemini Omni 1.2 Flash")


def test_parse_feed_rss_datum_pretvara_u_utc() -> None:
    items = parse_feed(fixture_bytes("openai.xml"))

    assert items[0].published_at == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def test_parse_feed_atom_sa_vremenskom_zonom_pretvara_u_utc() -> None:
    items = parse_feed(fixture_bytes("verge.xml"))

    # <published>2026-11-10T06:01:00-05:00</published>
    assert items[0].published_at == datetime(2026, 11, 10, 11, 1, tzinfo=UTC)


def test_parse_feed_atom_uzima_ceo_sadrzaj_umesto_sazetka() -> None:
    items = parse_feed(fixture_bytes("verge.xml"))

    assert "<figure>" in items[0].content


def test_parse_feed_stavka_bez_linka_se_preskace() -> None:
    body = (b'<rss version="2.0"><channel><item><title>Bez linka</title></item>'
            b"<item><title>Sa linkom</title><link>https://example.com/a</link></item>"
            b"</channel></rss>")

    items = parse_feed(body)

    assert [item.title for item in items] == ["Sa linkom"]


def test_parse_feed_stavka_bez_datuma_ima_none() -> None:
    body = (b'<rss version="2.0"><channel><item><title>T</title>'
            b"<link>https://example.com/a</link></item></channel></rss>")

    assert parse_feed(body)[0].published_at is None


def test_parse_feed_ispravan_feed_bez_stavki_vraca_praznu_listu() -> None:
    assert parse_feed(EMPTY_FEED) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<!DOCTYPE html><html><body>404", id="pogadjanje-html-stranica-greske"),
        pytest.param(b"", id="bva-prazno-telo"),
    ],
)
def test_parse_feed_neispravan_odgovor_baca_source_error(body: bytes) -> None:
    with pytest.raises(SourceError, match="neispravan feed"):
        parse_feed(body)


def _feed_client(body: bytes) -> RssSource:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    return RssSource("test-feed", "https://example.com/feed", offline_client(handler))


@pytest.mark.parametrize(
    ("since", "expected"),
    [
        pytest.param(datetime(2026, 11, 10, 9, 0, tzinfo=UTC), 1, id="bva-tacno-na-granici"),
        pytest.param(datetime(2026, 11, 10, 9, 0, 1, tzinfo=UTC), 0, id="bva-sekund-posle"),
        pytest.param(datetime(2026, 1, 1, tzinfo=UTC), 3, id="ep-sve-novije"),
    ],
)
def test_fetch_filtrira_stavke_starije_od_since(since: datetime, expected: int) -> None:
    source = _feed_client(fixture_bytes("openai.xml"))

    assert len(source.fetch(since)) == expected


def test_fetch_feed_bez_stavki_baca_empty_source() -> None:
    source = _feed_client(EMPTY_FEED)

    with pytest.raises(EmptySource, match="test-feed"):
        source.fetch(datetime(2026, 1, 1, tzinfo=UTC))
