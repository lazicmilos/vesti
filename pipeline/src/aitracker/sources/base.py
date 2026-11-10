"""Zajednički tipovi izvora i HTTP klijent koji poštuje robots.txt i razmak između zahteva."""

import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel

from aitracker.config import REPO_URL

USER_AGENT = f"aitracker/0.1 (+{REPO_URL})"
MIN_DELAY_S = 1.0  # NFR-L-002
ATTEMPTS = 3


class SourceError(Exception):
    """Izvor nije odgovorio ili je vratio neispravan odgovor."""


class EmptySource(SourceError):
    """Izvor je odgovorio ispravno, ali bez ijedne stavke (NFR-R-003)."""


class RawItem(BaseModel):
    url: str
    title: str
    published_at: datetime | None = None
    content: str = ""
    hn_points: int | None = None


class Source(Protocol):
    name: str

    def fetch(self, since: datetime) -> list[RawItem]: ...


class ModelItem(BaseModel):
    """Model kako ga opisuje strukturirani izvor; polje koje izvor ne navodi je None (FR-003)."""

    raw_name: str  # identifikator u izvoru, npr. "openai/gpt-5"
    name: str
    org: str | None = None
    aliases: list[str] = []  # drugi nazivi istog modela koje izvor sam navodi
    released_at: date | None = None
    params_b: Decimal | None = None
    context_window: int | None = None
    price_in: Decimal | None = None  # USD po 1M tokena
    price_out: Decimal | None = None
    license: str | None = None
    open_weights: bool | None = None
    source_url: str


class ModelSource(Protocol):
    name: str

    def fetch_models(self) -> list[ModelItem]: ...


class PoliteClient:
    """GET sa identifikacionim User-Agent-om, robots.txt proverom, pauzom po hostu i retry-jem."""

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = httpx.Client(
            transport=transport,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        if not self._allowed(url):
            raise SourceError(f"robots.txt zabranjuje {url}")
        response = self._request(url, params)
        if response.status_code >= 400:
            raise SourceError(f"HTTP {response.status_code} za {url}")
        return response

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            response = self._request(f"{origin}/robots.txt", None)
            if response.status_code >= 500:
                raise SourceError(f"robots.txt nedostupan za {origin}")
            parser = RobotFileParser()
            # 4xx znači da robots.txt ne postoji: sve je dozvoljeno.
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def _request(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        """Do tri pokušaja sa eksponencijalnim backoff-om; 4xx se ne ponavlja."""
        host = urlsplit(url).netloc
        error = "nepoznata greška"
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(2.0**attempt)
            wait = MIN_DELAY_S - (self._clock() - self._last_request.get(host, -MIN_DELAY_S))
            if wait > 0:
                self._sleep(wait)
            self._last_request[host] = self._clock()
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as exc:
                error = type(exc).__name__
                continue
            if response.status_code < 500:
                return response
            error = f"HTTP {response.status_code}"
        if error.startswith("HTTP"):
            return response
        raise SourceError(f"{error} za {url} posle {ATTEMPTS} pokušaja")
