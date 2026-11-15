"""Pydantic šeme LLM izlaza (SPEC 11.2); svaki odgovor modela se validira kroz njih."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

INT_MAX = 2**31 - 1  # kolona INT u Postgres-u


class ModelFields(BaseModel):
    org: str | None
    released_at: date | None
    # Granice odbijaju vrednost koju baza ne prima ili koja je besmislena, pre keša i upisa.
    params_b: float | None = Field(gt=0)
    context_window: int | None = Field(gt=0, le=INT_MAX)
    price_in: float | None = Field(ge=0)  # USD po 1M tokena
    price_out: float | None = Field(ge=0)
    license: str | None
    open_weights: bool | None
    summary_sr: str = Field(min_length=40, max_length=400)


Category = Literal["ai", "hardware", "big_tech", "security"]


class EventSummary(BaseModel):
    title_sr: str = Field(max_length=90)
    summary_sr: str = Field(min_length=80, max_length=700)  # 2–4 rečenice
    category: Category | None
    mentioned_models: list[str]  # imena tačno kako se pojavljuju u tekstu
