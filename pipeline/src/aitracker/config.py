"""Učitava konfiguraciju iz env promenljivih i YAML fajlova i podešava JSON logovanje."""

import json
import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# ponytail: putanje se računaju od izvornog stabla, pa paket radi samo iz kloniranog repoa
# (uv sync ga instalira kao editable). Prebaciti u package data ako se ikad bude pakovao.
PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/lazicmilos/vesti"


class ConfigError(Exception):
    """Konfiguracija nedostaje ili je neispravna."""


class SourceConfig(BaseModel):
    name: str
    kind: Literal["api", "rss"]
    role: Literal["tracker", "news", "signal", "both"]
    url: str
    weight: float = Field(default=1.0, ge=0.5, le=1.5)
    enabled: bool = True
    min_points: int = 20  # samo za Hacker News
    min_likes: int = 1000  # samo za Hugging Face


class SourcesFile(BaseModel):
    lookback_hours: int = 72
    org_aliases: dict[str, str] = {}
    sources: list[SourceConfig]


def load_sources(path: Path = PIPELINE_ROOT / "config" / "sources.yaml") -> SourcesFile:
    return SourcesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_glossary(path: Path = PIPELINE_ROOT / "config" / "glossary.yaml") -> str:
    """Rečnik (SPEC 11.4) kao lista za promptove: jedan red `- engleski → srpski`."""
    terms: dict[str, str] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return "\n".join(f"- {en} → {sr}" for en, sr in terms.items())


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL nije postavljen (videti .env.example)")
    return url


class JsonFormatter(logging.Formatter):
    """Jedan JSON objekat po liniji; dodatna polja idu kroz `extra={"data": {...}}`."""

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **getattr(record, "data", {}),
        }
        return json.dumps(line, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
