"""Pydantic šeme LLM izlaza (SPEC 11.2); svaki LLM odgovor prolazi kroz jednu od njih."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["ai", "hardware", "big_tech", "security"]


class ModelFields(BaseModel):
    """Polja modela iz zvanične najave; bez podrazumevanih vrednosti, pa `null` mora eksplicitno."""

    model_config = ConfigDict(extra="forbid")

    org: str | None
    released_at: date | None
    params_b: float | None
    context_window: int | None
    price_in: float | None  # USD po 1M tokena
    price_out: float | None
    license: str | None
    open_weights: bool | None
    summary_sr: str = Field(min_length=40, max_length=400)


class EventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_sr: str = Field(max_length=90)
    summary_sr: str = Field(min_length=80, max_length=700)  # 2–4 rečenice
    category: Category | None
    mentioned_models: list[str]  # imena tačno kako se pojavljuju u tekstu
