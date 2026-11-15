"""LLM klijent: keš, budžet, poziv OpenRouter-a i validacija JSON izlaza (SPEC 11.1)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from string import Template

import httpx
from pydantic import BaseModel, Field, ValidationError

from aitracker.budget import Budget
from aitracker.db import Conn
from aitracker.llm import cache

API_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPTS = Path(__file__).parent / "prompts"
log = logging.getLogger("aitracker.llm")
# Bez max_tokens OpenRouter rezerviše ceo izlazni limit modela i odbija poziv (402) kad je
# stanje na računu malo. Modeli za rezonovanje troše deo ovoga na razmišljanje.
MAX_TOKENS = 2048
ATTEMPTS = 3
# Duže od 20 s za izvore: model za rezonovanje sporo odgovara, a prekinut poziv može biti naplaćen.
TIMEOUT_S = 60


class LLMError(Exception):
    """Provajder nije odgovorio ili je vratio neispravan odgovor."""


class ValidationFailed(LLMError):
    """Izlaz modela ni posle ponovljenog pokušaja ne prolazi šemu."""


@dataclass(frozen=True)
class Usage:
    """Šta je ovaj poziv potrošio; pogodak u kešu ne troši ništa."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    cached: bool = False


class _Message(BaseModel):
    content: str | None


class _Choice(BaseModel):
    message: _Message
    finish_reason: str | None = None


class _Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal  # stvarno naplaćeno; cena zavisi od provajdera na koji OpenRouter rutira


class _Response(BaseModel):
    choices: list[_Choice] = Field(min_length=1)
    usage: _Usage


class LLMClient:
    def __init__(
        self, conn: Conn, budget: Budget, model: str, api_key: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        prompts: Path = PROMPTS,
    ) -> None:
        self._conn, self._budget, self.model = conn, budget, model
        self._http = httpx.Client(
            transport=transport, timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {api_key}"}
        )
        self._sleep = sleep
        self._prompts = prompts

    def complete_json[T: BaseModel](
        self, prompt_name: str, variables: dict[str, str], schema: type[T]
    ) -> tuple[T, Usage]:
        """Keš → budžet → poziv; neispravan izlaz dobija jedan retry sa porukom o grešci."""
        template = Template((self._prompts / f"{prompt_name}.md").read_text(encoding="utf-8"))
        prompt = template.substitute(variables)
        key = cache.cache_key(prompt, prompt_name, self.model)
        if (hit := cache.get(self._conn, key)) is not None:
            try:
                return schema.model_validate(hit), Usage(cached=True)
            except ValidationError:
                pass  # zapis po staroj šemi: tretira se kao promašaj i prepisuje se novim
        messages = [{"role": "user", "content": prompt}]
        total = Usage()
        for _ in range(2):
            self._budget.check()
            content, truncated, usage = self._call(messages)
            self._budget.charge(usage.cost_usd)
            if truncated:
                # Retry sa istim limitom bi pao isto i bio plaćen drugi put.
                raise LLMError(f"{prompt_name}: izlaz odsečen na {MAX_TOKENS} tokena")
            total = Usage(
                total.input_tokens + usage.input_tokens,
                total.output_tokens + usage.output_tokens,
                total.cost_usd + usage.cost_usd,
            )
            try:
                result = schema.model_validate_json(content)
            except ValidationError as exc:
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"Izlaz ne prolazi šemu:\n{exc}\n"
                     "Vrati samo ispravljen JSON."},
                ]
                continue
            cache.put(self._conn, key, prompt_name, self.model, result.model_dump(mode="json"),
                      total.input_tokens, total.output_tokens, total.cost_usd)
            return result, total
        raise ValidationFailed(f"{prompt_name}: izlaz ne prolazi {schema.__name__} posle retry-ja")

    def _call(self, messages: list[dict[str, str]]) -> tuple[str, bool, Usage]:
        """Vraća (sadržaj, da li je izlaz odsečen, potrošnja)."""
        body = {
            "model": self.model, "messages": messages, "temperature": 0,
            "max_tokens": MAX_TOKENS, "response_format": {"type": "json_object"},
        }
        error = "nepoznata greška"
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(2.0**attempt)
            try:
                response = self._http.post(API_URL, json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                error = type(exc).__name__
                continue
            except httpx.TransportError as exc:
                # Zahtev je možda stigao i naplaćen je; ponavljanje bi platilo još jednom.
                raise LLMError(f"{type(exc).__name__} posle slanja zahteva") from exc
            if response.status_code == 429 or response.status_code >= 500:
                error = f"HTTP {response.status_code}"
                continue
            if response.status_code >= 400:
                # Bez tela odgovora: sadrži user_id i identifikator ključa (pravilo 0.7).
                raise LLMError(f"HTTP {response.status_code}")
            try:
                parsed = _Response.model_validate_json(response.content)
            except ValidationError as exc:
                # Poziv je verovatno naplaćen, a trošak je nepoznat i ne ulazi u budžet.
                log.error("odgovor provajdera bez očekivanih polja; trošak nije upisan")
                raise LLMError(f"neispravan odgovor provajdera ({exc.error_count()})") from exc
            u = parsed.usage
            usage = Usage(u.prompt_tokens, u.completion_tokens, u.cost)
            choice = parsed.choices[0]
            return choice.message.content or "", choice.finish_reason == "length", usage
        raise LLMError(f"{error} posle {ATTEMPTS} pokušaja")
