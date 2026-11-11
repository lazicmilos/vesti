import json
from decimal import Decimal

import httpx
import pytest
from conftest import fixture_bytes

from aitracker.config import ConfigError
from aitracker.llm.client import Message
from aitracker.llm.openrouter import OpenRouterProvider, ProviderError, provider_from_env

MESSAGES: list[Message] = [{"role": "user", "content": "Vrati samo JSON."}]


def _provider(handler: httpx.MockTransport) -> OpenRouterProvider:
    return OpenRouterProvider("anthropic/claude-haiku-5.5", "kljuc", transport=handler)


def _fixture(name: str) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _: httpx.Response(200, content=fixture_bytes(name)))


@pytest.mark.parametrize(("name", "tokens", "cost"), [
    ("openrouter_chat_claude-haiku-5.5.json", (47, 20), "0.0000147"),
    ("openrouter_chat_gemini-3.1-flash-lite.json", (26, 16), "0.0000305"),
    # DeepSeek rezonuje: 53 od 76 izlaznih tokena su rezonovanje i naplaćuju se kao izlaz.
    ("openrouter_chat_deepseek-v4.1-flash.json", (56, 76), "0.000045948"),
])
def test_stvarni_odgovori_daju_tekst_tokene_i_naplatu(
    name: str, tokens: tuple[int, int], cost: str
) -> None:
    completion = _provider(_fixture(name)).complete(MESSAGES, 200)

    assert json.loads(completion.text) == {"jezik": "srpski", "broj": 7}
    assert (completion.input_tokens, completion.output_tokens) == tokens
    assert completion.cost_usd == Decimal(cost)


def test_zahtev_salje_model_temperaturu_nula_i_kljuc() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=fixture_bytes("openrouter_chat_claude-haiku-5.5.json"))

    _provider(httpx.MockTransport(handler)).complete(MESSAGES, 300)

    body = json.loads(seen[0].content)
    assert body == {"model": "anthropic/claude-haiku-5.5", "messages": MESSAGES,
                    "temperature": 0, "max_tokens": 300}
    assert seen[0].headers["Authorization"] == "Bearer kljuc"


def test_odgovor_bez_naplate_vraca_none_za_trosak() -> None:
    payload = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))

    assert _provider(transport).complete(MESSAGES, 10).cost_usd is None


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": "rate limit"}),
    httpx.Response(200, content=b"nije json"),
    httpx.Response(200, json={"choices": [], "usage": {"prompt_tokens": 1,
                                                       "completion_tokens": 0}}),
])
def test_neupotrebljiv_odgovor_dize_provider_error(response: httpx.Response) -> None:
    with pytest.raises(ProviderError):
        _provider(httpx.MockTransport(lambda _: response)).complete(MESSAGES, 10)


def test_mrezna_greska_dize_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(ProviderError):
        _provider(httpx.MockTransport(handler)).complete(MESSAGES, 10)


def test_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
    monkeypatch.setenv("OPENROUTER_API_KEY", "kljuc")

    assert provider_from_env().model == "google/gemini-3.1-flash-lite"

    monkeypatch.setenv("LLM_PROVIDER", "drugi")
    with pytest.raises(ConfigError):
        provider_from_env()
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(ConfigError):
        provider_from_env()
