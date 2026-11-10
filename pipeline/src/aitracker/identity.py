"""Identitet modela (SPEC 10.1): normalizacija imena i odluka postojeći / sličan / novi."""

import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz

SIMILARITY_THRESHOLD = 90
_MMDD = r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
# Redom: -YYYY-MM-DD, -YYYYMMDD, -YYYY-MM, -MMDD; samo na kraju imena.
_DATE_SUFFIX = re.compile(rf"-(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{4}}{_MMDD}|\d{{4}}-\d{{2}}|{_MMDD})$")
_SEPARATORS = re.compile(r"[_\s]+")
_DASHES = re.compile(r"-{2,}")


def normalize(name: str) -> str:
    """Ime bez prefiksa organizacije i datumskog sufiksa, malim slovima, sa crticama."""
    text = name.strip().lower().rsplit("/", 1)[-1]
    text = _DASHES.sub("-", _SEPARATORS.sub("-", text))
    return _DATE_SUFFIX.sub("", text)


def org_key(org: str | None, aliases: dict[str, str]) -> str | None:
    """Ključ za poređenje organizacija: isti lab se u izvorima zove različito."""
    if not org:
        return None
    key = org.strip().lower()
    return aliases.get(key, key)


@dataclass
class Registry:
    """Poznati aliasi (alias_norm → model_id) i organizacija svakog modela."""

    aliases: dict[str, int] = field(default_factory=dict)
    orgs: dict[int, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Match:
    kind: Literal["existing", "similar", "new"]
    model_id: int | None = None


def resolve(names: list[str], org: str | None, registry: Registry) -> Match:
    """Primenjuje pravila 1–3 iz SPEC 10.1; `names[0]` je glavno ime, ostalo su aliasi izvora."""
    normalized = [normalize(name) for name in names]
    for alias in normalized:
        if alias in registry.aliases:
            return Match("existing", registry.aliases[alias])
    if org is not None:
        for alias, model_id in registry.aliases.items():
            same_org = registry.orgs.get(model_id) == org
            if same_org and fuzz.ratio(normalized[0], alias) >= SIMILARITY_THRESHOLD:
                return Match("similar", model_id)
    return Match("new")
