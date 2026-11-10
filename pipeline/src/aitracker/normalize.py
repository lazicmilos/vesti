"""Kanonizacija URL-a i hash sadržaja (SPEC odeljak 9), osnova za deduplikaciju."""

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {"ref", "fbclid", "gclid"}
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    """Lowercase host bez `www.`, bez tracking parametara, fragmenta i završne kose crte."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"nije http(s) URL: {url!r}")
    host = parts.hostname.lower().removeprefix("www.")
    if parts.port:
        host = f"{host}:{parts.port}"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def normalize_text(text: str) -> str:
    """Tekst bez HTML-a, sa spojenim razmacima, malim slovima."""
    # ponytail: regex umesto HTML parsera; dovoljno za hash, nije za prikaz teksta.
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text))).strip().lower()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
