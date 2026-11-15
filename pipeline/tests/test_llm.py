import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from conftest import fixture_bytes
from pydantic import BaseModel

from aitracker.budget import Budget, BudgetExceeded
from aitracker.db import Conn
from aitracker.llm.client import LLMClient, LLMError, ValidationFailed

pytestmark = pytest.mark.db
NOW = datetime(2026, 11, 15, 5, tzinfo=UTC)
COST = Decimal("0.00007047")  # usage.cost iz fixture-a


class Fields(BaseModel):
    org: str | None
    context_window: int | None


def _reply(content: str) -> httpx.Response:
    body = json.loads(fixture_bytes("openrouter_chat.json"))
    body["choices"][0]["message"]["content"] = content
    return httpx.Response(200, json=body)


def _client(
    conn: Conn, tmp_path: Path, responses: list[httpx.Response]
) -> tuple[LLMClient, list[httpx.Request], Budget]:
    (tmp_path / "fields_v1.md").write_text("Izvuci polja iz: $text", encoding="utf-8")
    run_id = conn.execute("INSERT INTO runs (started_at) VALUES (%s) RETURNING id", (NOW,))
    budget = Budget(conn, run_id.fetchone()[0], NOW)  # type: ignore[index]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    client = LLMClient(conn, budget, "deepseek/deepseek-v4.1-flash", "dummy",
                       transport=httpx.MockTransport(handler), sleep=lambda _: None,
                       prompts=tmp_path)
    return client, requests, budget


def test_success_is_cached_and_charged(conn: Conn, tmp_path: Path) -> None:
    ok = httpx.Response(200, content=fixture_bytes("openrouter_chat.json"))
    client, requests, budget = _client(conn, tmp_path, [ok])

    result, usage = client.complete_json("fields_v1", {"text": "Primer Lab"}, Fields)
    again, cached = client.complete_json("fields_v1", {"text": "Primer Lab"}, Fields)

    assert result == again == Fields(org="Primer Lab", context_window=200000)
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (118, 101, COST)
    assert cached.cached and cached.cost_usd == 0
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["temperature"] == 0 and body["max_tokens"] > 0
    assert body["messages"][0]["content"] == "Izvuci polja iz: Primer Lab"
    assert budget.spent() == COST


def test_invalid_output_gets_one_retry_with_error(conn: Conn, tmp_path: Path) -> None:
    responses = [_reply('{"org": 1}'), _reply('{"org": "X", "context_window": null}')]
    client, requests, budget = _client(conn, tmp_path, responses)

    result, usage = client.complete_json("fields_v1", {"text": "t"}, Fields)

    assert result == Fields(org="X", context_window=None)
    retry = json.loads(requests[1].content)["messages"]
    assert retry[1] == {"role": "assistant", "content": '{"org": 1}'}
    assert "context_window" in retry[2]["content"]
    assert usage.cost_usd == budget.spent() == 2 * COST


def test_second_invalid_output_raises(conn: Conn, tmp_path: Path) -> None:
    client, _, budget = _client(conn, tmp_path, [_reply("nije json"), _reply("{}")])
    with pytest.raises(ValidationFailed):
        client.complete_json("fields_v1", {"text": "t"}, Fields)
    assert budget.spent() == 2 * COST
    assert conn.execute("SELECT count(*) FROM llm_cache").fetchone() == (0,)


def test_exhausted_budget_blocks_call(conn: Conn, tmp_path: Path) -> None:
    client, requests, budget = _client(conn, tmp_path, [])
    conn.execute("INSERT INTO runs (started_at, cost_usd) VALUES (%s, 4.96)", (NOW,))
    conn.execute("INSERT INTO runs (started_at, cost_usd) VALUES ('2026-10-31', 4)")  # prošli mesec
    assert budget.spent() == Decimal("4.96")
    with pytest.raises(BudgetExceeded):
        client.complete_json("fields_v1", {"text": "t"}, Fields)
    assert requests == []


def test_server_errors_retried_client_errors_not(conn: Conn, tmp_path: Path) -> None:
    ok = httpx.Response(200, content=fixture_bytes("openrouter_chat.json"))
    client, requests, _ = _client(conn, tmp_path, [httpx.Response(503), ok])
    client.complete_json("fields_v1", {"text": "a"}, Fields)
    assert len(requests) == 2

    client, requests, budget = _client(conn, tmp_path, [httpx.Response(402)])
    with pytest.raises(LLMError, match="402"):
        client.complete_json("fields_v1", {"text": "b"}, Fields)
    assert len(requests) == 1
