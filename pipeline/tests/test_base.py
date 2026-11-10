import httpx
import pytest
from conftest import offline_client

from aitracker.sources.base import USER_AGENT, SourceError

ROBOTS = "User-agent: *\nDisallow: /privatno/\n"


def _handler(calls: list[str], statuses: dict[str, list[int]]) -> httpx.MockTransport | object:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        queue = statuses.get(request.url.path, [200])
        return httpx.Response(queue.pop(0) if len(queue) > 1 else queue[0], text="ok")

    return handle


def test_get_salje_identifikacioni_user_agent_sa_urlom_repoa() -> None:
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["User-Agent"])
        return httpx.Response(200, text="")

    offline_client(handler).get("https://example.com/feed")

    assert set(agents) == {USER_AGENT}
    assert "github.com/lazicmilos/vesti" in USER_AGENT


def test_get_putanja_zabranjena_u_robots_txt_baca_source_error() -> None:
    calls: list[str] = []
    client = offline_client(_handler(calls, {}))  # type: ignore[arg-type]

    with pytest.raises(SourceError, match="robots.txt zabranjuje"):
        client.get("https://example.com/privatno/feed")

    assert calls == ["/robots.txt"]


def test_get_robots_txt_se_cita_jednom_po_hostu() -> None:
    calls: list[str] = []
    client = offline_client(_handler(calls, {}))  # type: ignore[arg-type]

    client.get("https://example.com/a")
    client.get("https://example.com/b")

    assert calls == ["/robots.txt", "/a", "/b"]


def test_get_robots_txt_ne_postoji_dozvoljava_zahtev() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200, text="ok")

    assert offline_client(handler).get("https://example.com/a").text == "ok"


def test_get_robots_txt_vraca_5xx_baca_source_error() -> None:
    client = offline_client(lambda request: httpx.Response(503))

    with pytest.raises(SourceError, match="robots.txt nedostupan"):
        client.get("https://example.com/a")


def test_get_uzastopni_zahtevi_istom_hostu_cekaju_najmanje_sekundu() -> None:
    sleeps: list[float] = []
    client = offline_client(_handler([], {}), sleeps)  # type: ignore[arg-type]

    client.get("https://example.com/a")

    # robots.txt pa /a: drugi zahtev istom hostu mora da sačeka ~1 s
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1.0, abs=0.05)


def test_get_5xx_pa_uspeh_ponavlja_sa_backoffom() -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    client = offline_client(_handler(calls, {"/a": [503, 200]}), sleeps)  # type: ignore[arg-type]

    response = client.get("https://example.com/a")

    assert response.status_code == 200
    assert calls.count("/a") == 2
    assert 2.0 in sleeps


def test_get_trajni_5xx_baca_source_error_posle_tri_pokusaja() -> None:
    calls: list[str] = []
    client = offline_client(_handler(calls, {"/a": [500]}))  # type: ignore[arg-type]

    with pytest.raises(SourceError, match="HTTP 500"):
        client.get("https://example.com/a")

    assert calls.count("/a") == 3


def test_get_4xx_baca_source_error_bez_ponavljanja() -> None:
    calls: list[str] = []
    client = offline_client(_handler(calls, {"/a": [404]}))  # type: ignore[arg-type]

    with pytest.raises(SourceError, match="HTTP 404"):
        client.get("https://example.com/a")

    assert calls.count("/a") == 1


def test_get_mrezna_greska_baca_source_error_posle_tri_pokusaja() -> None:
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(request.url.path)
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(SourceError, match="ConnectTimeout .* posle 3 pokušaja"):
        offline_client(handler).get("https://example.com/a")

    assert len(attempts) == 3
