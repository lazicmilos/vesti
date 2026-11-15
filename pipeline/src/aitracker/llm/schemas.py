"""Pydantic šeme LLM izlaza (SPEC 11.2); svaki odgovor modela se validira kroz njih."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ModelFields(BaseModel):
    org: str | None
    released_at: date | None
    params_b: float | None
    context_window: int | None
    price_in: float | None  # USD po 1M tokena
    price_out: float | None
    license: str | None
    open_weights: bool | None
    summary_sr: str = Field(min_length=40, max_length=400)


Category = Literal["ai", "hardware", "big_tech", "security"]


class EventSummary(BaseModel):
    title_sr: str = Field(max_length=90)
    summary_sr: str = Field(min_length=80, max_length=700)  # 2–4 rečenice
    category: Category | None
    mentioned_models: list[str]  # imena tačno kako se pojavljuju u tekstu
