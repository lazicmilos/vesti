"""LLM klijent (SPEC 11.1): keš, pa budžet, pa poziv provajdera, pa validacija kroz šemu."""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, TypedDict, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from aitracker.budget import Budget
from aitracker.config import PIPELINE_ROOT, ConfigError
from aitracker.db import Conn
from aitracker.llm import cache

log = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).parent / "prompts"
PRICES_PATH = PIPELINE_ROOT / "config" / "llm_prices.yaml"
MAX_OUTPUT_TOKENS = 1024
OVERHEAD_TOKENS = 100  # rezerva za tokene koje provajder dodaje oko poruka
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
T = TypeVar("T", bound=BaseModel)


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    """Jedan LLM API. Implementacija šalje `temperature = 0` (SPEC 11.1)."""

    model: str

    def complete(self, messages: list[Message], max_tokens: int) -> Completion: ...


@dataclass(frozen=True)
class Price:
    input: Decimal  # USD po 1M tokena
    output: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (self.input * input_tokens + self.output * output_tokens) / 1_000_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    cached: bool


class ValidationFailed(Exception):
    """Ni posle jednog ponovnog pokušaja izlaz ne odgovara šemi; ide u `review_queue`."""

    def __init__(self, prompt_name: str, outputs: list[str], error: str) -> None:
        super().__init__(f"{prompt_name}: izlaz ne odgovara šemi ({error})")
        self.outputs = outputs
        self.error = error


def load_prices(path: Path = PRICES_PATH) -> dict[str, Price]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {model: Price(Decimal(str(p["input"])), Decimal(str(p["output"])))
            for model, p in (data.get("models") or {}).items()}


def render(template: str, variables: dict[str, str]) -> str:
    """Zamenjuje `{{ime}}`; promenljiva koja nedostaje ili višak promenljivih je greška."""
    names = set(_PLACEHOLDER.findall(template))
    if names != variables.keys():
        raise ConfigError(f"promenljive prompta {sorted(names)}, dato {sorted(variables)}")
    return _PLACEHOLDER.sub(lambda m: variables[m.group(1)], template)


def worst_case_input_tokens(messages: list[Message]) -> int:
    """Gornja granica: byte-level tokenizer ne može da napravi više tokena nego bajtova."""
    return sum(len(m["content"].encode()) for m in messages) + OVERHEAD_TOKENS


class LlmClient:
    def __init__(
        self, conn: Conn, provider: Provider, budget: Budget, prices: dict[str, Price],
        prompts_dir: Path = PROMPTS_DIR, max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        if provider.model not in prices:
            # Bez cene trošak bi se računao kao 0 i budžet ne bi štitio ništa.
            raise ConfigError(f"model {provider.model} nema cenu u llm_prices.yaml")
        self.conn, self.provider, self.budget = conn, provider, budget
        self.price = prices[provider.model]
        self.prompts_dir, self.max_tokens = prompts_dir, max_tokens

    def complete_json(
        self, prompt_name: str, variables: dict[str, str], schema: type[T]
    ) -> tuple[T, Usage]:
        """Vraća izlaz validiran kroz `schema`; diže `BudgetExceeded` ili `ValidationFailed`."""
        json_schema = schema.model_json_schema()
        model = self.provider.model
        key = cache.cache_key(cache.content_hash(variables, json_schema), prompt_name, model)
        hit = cache.get(self.conn, key)
        if hit is not None:
            return schema.model_validate(hit), Usage(0, 0, Decimal(0), cached=True)

        template = (self.prompts_dir / f"{prompt_name}.md").read_text(encoding="utf-8")
        prompt = (f"{render(template, variables)}\n\nJSON šema izlaza:\n"
                  f"{json.dumps(json_schema, ensure_ascii=False)}")
        messages: list[Message] = [{"role": "user", "content": prompt}]
        outputs: list[str] = []
        input_tokens = output_tokens = 0
        for attempt in range(2):
            completion = self._call(messages)
            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens
            outputs.append(completion.text)
            try:
                result = schema.model_validate_json(_FENCE.sub("", completion.text))
            except ValidationError as exc:
                error = str(exc.errors(include_url=False, include_input=False))
                log.warning("izlaz ne odgovara šemi", extra={"data": {
                    "prompt": prompt_name, "model": model, "attempt": attempt + 1}})
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {"role": "user", "content": f"Odgovor ne odgovara šemi: {error}. "
                                                "Vrati samo ispravan JSON po šemi."},
                ]
                continue
            cost = self.price.cost(input_tokens, output_tokens)
            cache.put(self.conn, key, prompt_name, model, cache.CachedCall(
                result.model_dump(mode="json"), input_tokens, output_tokens, cost))
            return result, Usage(input_tokens, output_tokens, cost, cached=False)
        raise ValidationFailed(prompt_name, outputs, error)

    def _call(self, messages: list[Message]) -> Completion:
        worst = self.price.cost(worst_case_input_tokens(messages), self.max_tokens)
        self.budget.check(worst)
        completion = self.provider.complete(messages, self.max_tokens)
        cost = self.price.cost(completion.input_tokens, completion.output_tokens)
        self.budget.add(cost)
        log.info("LLM poziv", extra={"data": {
            "model": self.provider.model, "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens, "cost_usd": str(cost)}})
        return completion
