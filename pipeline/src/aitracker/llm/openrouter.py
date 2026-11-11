"""Provajder preko OpenRouter chat completions API-ja, prema stvarnim odgovorima u fixtures."""

import os
from decimal import Decimal

import httpx
from pydantic import BaseModel, ValidationError

from aitracker.config import REPO_URL, ConfigError
from aitracker.llm.client import Completion, Message

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_S = 90  # duže od 20 s za izvore: generisanje traje


class ProviderError(Exception):
    """Provajder nije vratio upotrebljiv odgovor; poziv se ne ponavlja da se ne plati dvaput."""


class _Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int  # uključuje i tokene rezonovanja
    cost: float | None = None  # stvarna naplata u USD


class _Content(BaseModel):
    content: str | None


class _Choice(BaseModel):
    message: _Content
    finish_reason: str | None


class _Response(BaseModel):
    choices: list[_Choice]
    usage: _Usage


class OpenRouterProvider:
    def __init__(
        self, model: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.model = model
        self._http = httpx.Client(
            transport=transport,
            timeout=TIMEOUT_S,
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": REPO_URL},
        )

    def complete(self, messages: list[Message], max_tokens: int) -> Completion:
        # Bez skrivenog rezonovanja: troši max_tokens pre odgovora (prazan ili odsečen JSON),
        # a za ekstrakciju i sažetak nije potrebno. Provereno na sva tri kandidata.
        body = {"model": self.model, "messages": messages, "temperature": 0,
                "max_tokens": max_tokens, "reasoning": {"enabled": False}}
        try:
            response = self._http.post(URL, json=body)
        except httpx.TransportError as exc:
            raise ProviderError(f"{type(exc).__name__} za {self.model}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"HTTP {response.status_code} za {self.model}")
        try:
            parsed = _Response.model_validate_json(response.content)
        except ValidationError as exc:
            raise ProviderError(f"neočekivan format odgovora za {self.model}") from exc
        if not parsed.choices:
            raise ProviderError(f"odgovor bez izbora za {self.model}")
        usage = parsed.usage
        # Prazan ili odsečen sadržaj ide dalje: validacija šeme ga odbija i daje ponovni pokušaj.
        return Completion(
            text=parsed.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=None if usage.cost is None else Decimal(str(usage.cost)),
        )


def provider_from_env() -> OpenRouterProvider:
    """Provajder i model iz `LLM_PROVIDER` i `LLM_MODEL` (SPEC 4), ključ iz `OPENROUTER_API_KEY`."""
    provider = os.environ.get("LLM_PROVIDER", "openrouter")
    if provider != "openrouter":
        raise ConfigError(f"LLM_PROVIDER={provider} nije podržan")
    model, key = os.environ.get("LLM_MODEL"), os.environ.get("OPENROUTER_API_KEY")
    if not model or not key:
        raise ConfigError("LLM_MODEL i OPENROUTER_API_KEY moraju biti postavljeni")
    return OpenRouterProvider(model, key)
