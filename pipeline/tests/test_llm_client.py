import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aitracker.budget import Budget, BudgetExceeded
from aitracker.config import ConfigError
from aitracker.db import Conn
from aitracker.llm.client import (
    Completion,
    LlmClient,
    Message,
    Price,
    ValidationFailed,
    load_prices,
    render,
    worst_case_input_tokens,
)
from aitracker.llm.schemas import EventSummary, ModelFields

PRICE = Price(input=Decimal("1"), output=Decimal("2"))
FIELDS: dict[str, Any] = {
    "org": "Primer Lab", "released_at": "2026-11-01", "params_b": None,
    "context_window": 200000, "price_in": None, "price_out": None, "license": None,
    "open_weights": False, "summary_sr": "Primer Model 1 je jezički model laboratorije Primer Lab.",
}


class FakeProvider:
    """Vraća unapred zadate odgovore i beleži poruke koje je dobio."""

    model = "fake-1"

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], max_tokens: int) -> Completion:
        self.calls.append(list(messages))
        return Completion(self.texts.pop(0), input_tokens=1000, output_tokens=500)


@pytest.fixture
def prompts(tmp_path: Path) -> Path:
    (tmp_path / "model_fields_v1.md").write_text("Izvuci polja iz teksta:\n{{text}}")
    return tmp_path


def _client(conn: Conn, provider: FakeProvider, prompts: Path,
            budget: Budget | None = None) -> LlmClient:
    budget = budget or Budget(spent_before=Decimal(0))
    return LlmClient(conn, provider, budget, {"fake-1": PRICE}, prompts, max_tokens=500)


def test_render_zamenjuje_promenljive() -> None:
    assert render("A {{x}} B {{y}} {{x}}", {"x": "1", "y": "2"}) == "A 1 B 2 1"


@pytest.mark.parametrize("variables", [{}, {"x": "1", "visak": "2"}])
def test_render_odbija_promenljive_koje_se_ne_poklapaju(variables: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        render("{{x}}", variables)


def test_worst_case_broji_bajtove_a_ne_znakove() -> None:
    messages: list[Message] = [{"role": "user", "content": "čćž"}]  # 3 znaka, 6 bajtova

    assert worst_case_input_tokens(messages) == 6 + 100


def test_price_cost_je_po_milion_tokena() -> None:
    assert PRICE.cost(1_000_000, 500_000) == Decimal("2")


def test_load_prices_cita_yaml(tmp_path: Path) -> None:
    path = tmp_path / "prices.yaml"
    path.write_text("models:\n  m:\n    input: 0.25\n    output: 1.25\n")

    assert load_prices(path) == {"m": Price(Decimal("0.25"), Decimal("1.25"))}


def test_load_prices_iz_repoa_ima_cenu_za_svakog_kandidata() -> None:
    prices = load_prices()

    assert prices["anthropic/claude-haiku-5.5"] == Price(Decimal("0.10"), Decimal("0.50"))
    assert len(prices) == 3


def test_model_fields_traze_eksplicitan_null_i_odbijaju_visak() -> None:
    without_org = {k: v for k, v in FIELDS.items() if k != "org"}
    with pytest.raises(ValidationError):
        ModelFields.model_validate(without_org)
    with pytest.raises(ValidationError):
        ModelFields.model_validate(FIELDS | {"benchmark": 90})


def test_event_summary_ogranicava_naslov_i_kategoriju() -> None:
    valid = {"title_sr": "Naslov", "summary_sr": "x" * 80, "category": "ai",
             "mentioned_models": []}
    EventSummary.model_validate(valid)
    with pytest.raises(ValidationError):
        EventSummary.model_validate(valid | {"title_sr": "x" * 91})
    with pytest.raises(ValidationError):
        EventSummary.model_validate(valid | {"category": "sport"})


def test_klijent_bez_cene_modela_ne_pocinje(prompts: Path) -> None:
    with pytest.raises(ConfigError):
        LlmClient(None, FakeProvider(), Budget(Decimal(0)), {}, prompts)  # type: ignore[arg-type]


@pytest.mark.db
def test_uspesan_poziv_vraca_semu_racuna_trosak_i_upisuje_kes(conn: Conn, prompts: Path) -> None:
    provider = FakeProvider("```json\n" + json.dumps(FIELDS) + "\n```")
    client = _client(conn, provider, prompts)

    result, usage = client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert result.context_window == 200000 and result.params_b is None
    assert (usage.cost_usd, usage.cached) == (Decimal("0.002"), False)
    assert client.budget.spent_now == Decimal("0.002")
    assert "najava" in provider.calls[0][0]["content"]
    assert "JSON šema izlaza" in provider.calls[0][0]["content"]
    row = conn.execute("SELECT prompt_version, model, cost_usd FROM llm_cache").fetchone()
    assert row == ("model_fields_v1", "fake-1", Decimal("0.002"))


@pytest.mark.db
def test_isti_ulaz_drugi_put_ide_iz_kesa_bez_poziva(conn: Conn, prompts: Path) -> None:
    provider = FakeProvider(json.dumps(FIELDS))
    client = _client(conn, provider, prompts)
    client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    result, usage = client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert len(provider.calls) == 1
    assert usage.cached and usage.cost_usd == 0
    assert result.org == "Primer Lab"


@pytest.mark.db
def test_neispravan_izlaz_dobija_jedan_ponovni_pokusaj(conn: Conn, prompts: Path) -> None:
    provider = FakeProvider("nije json", json.dumps(FIELDS))
    client = _client(conn, provider, prompts)

    _, usage = client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert len(provider.calls) == 2
    retry = provider.calls[1]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert "ne odgovara šemi" in retry[2]["content"]
    assert usage.cost_usd == Decimal("0.004")  # plaćena su oba poziva


@pytest.mark.db
def test_drugi_neuspeh_dize_validation_failed_i_trosak_ostaje(conn: Conn, prompts: Path) -> None:
    provider = FakeProvider("nije json", json.dumps(FIELDS | {"org": 5}))
    client = _client(conn, provider, prompts)

    with pytest.raises(ValidationFailed) as exc:
        client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert exc.value.outputs[0] == "nije json"
    assert client.budget.spent_now == Decimal("0.004")
    assert conn.execute("SELECT count(*) FROM llm_cache").fetchone() == (0,)


@pytest.mark.db
def test_prekoracen_budzet_ne_zove_provajdera(conn: Conn, prompts: Path) -> None:
    provider = FakeProvider(json.dumps(FIELDS))
    client = _client(conn, provider, prompts, Budget(spent_before=Decimal("4.999")))

    with pytest.raises(BudgetExceeded):
        client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert provider.calls == []


@pytest.mark.db
def test_stvarna_naplata_provajdera_ima_prednost_nad_cenovnikom(conn: Conn, prompts: Path) -> None:
    class BilledProvider(FakeProvider):
        def complete(self, messages: list[Message], max_tokens: int) -> Completion:
            completion = super().complete(messages, max_tokens)
            return Completion(completion.text, 1000, 500, cost_usd=Decimal("0.0123"))

    client = _client(conn, BilledProvider(json.dumps(FIELDS)), prompts)

    _, usage = client.complete_json("model_fields_v1", {"text": "najava"}, ModelFields)

    assert usage.cost_usd == client.budget.spent_now == Decimal("0.0123")
