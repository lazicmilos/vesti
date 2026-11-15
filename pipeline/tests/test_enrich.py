import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from conftest import fixture_bytes

from aitracker import enrich
from aitracker.budget import Budget
from aitracker.config import SourcesFile
from aitracker.db import Conn
from aitracker.enrich import enrich_models, find_pairs, mentions
from aitracker.llm.client import MAX_TOKENS, LLMClient
from aitracker.run import Ctx, run
from aitracker.sources.base import ModelItem
from aitracker.tracker import upsert_models

NOW = datetime(2026, 11, 15, 5, tzinfo=UTC)
URL = "https://mistral.ai/news/mistral-large-4-oss"
FIELDS = {
    "org": "Mistral AI", "released_at": None, "params_b": 1000, "context_window": 999,
    "price_in": 0.7, "price_out": 2.1, "license": "Apache 2.0", "open_weights": True,
    "summary_sr": "Mistral Large 4 je multimodalni model sa otvorenim težinama za programiranje.",
}


def test_mentions_trazi_tacan_alias() -> None:
    text = "uvod o gpt-5. i gpt-5-mini, gemini omni 1.2 flash:"
    assert mentions(text, "gpt-5")
    assert mentions(text, "gemini-omni-1.2-flash")
    assert not mentions("chatgpt-5 i gpt-5-mini i gpt-5.1", "gpt-5")
    assert not mentions("introducing mistral large 4 instruct", "mistral-large-4")
    assert not mentions("mistral large\n4", "mistral-large-4")  # naslovi se ne spajaju


@pytest.mark.parametrize("text", [
    "gpt-5 is here",
    "mistral large 4 is now open weight",
    "the weights of mistral large 4\nare open",
    "introducing mistral_large_4.",
    "mistral\u00a0large\u20114 je tu",
])
def test_mentions_pogadja_obican_tekst(text: str) -> None:
    alias = "gpt-5" if text.startswith("gpt") else "mistral-large-4"
    assert mentions(text, alias)


PAGE = "Mistral Large 4 (Le Chonk) is now open weight | Mistral\nThe weights are now open."


def _setup(conn: Conn, content: str = PAGE) -> int:
    """Model iz OpenRouter-a sa context_window i cenama, i najava koja ga pominje."""
    upsert_models(conn, "openrouter", _source(conn, "openrouter", "tracker"), [ModelItem(
        raw_name="mistralai/mistral-large-4", name="Mistral Large 4", org=None,
        context_window=262144, price_in=Decimal(1), price_out=Decimal(3),
        source_url="https://openrouter.ai/x",
    )], {})
    conn.execute(
        "INSERT INTO documents (source_id, url_canonical, title, content_hash, content) "
        "VALUES (%s, %s, 'Le Chonk: Built for Coders', %s, %s)",
        (_source(conn, "mistral-blog", "both"), URL, "a" * 64, content),
    )
    row = conn.execute("INSERT INTO runs (started_at) VALUES (%s) RETURNING id", (NOW,))
    return int(row.fetchone()[0])  # type: ignore[index]


def _source(conn: Conn, name: str, role: str) -> int:
    row = conn.execute(
        "INSERT INTO sources (name, kind, role, url) VALUES (%s, 'rss', %s, 'u') RETURNING id",
        (name, role),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _llm(conn: Conn, run_id: int, replies: list[httpx.Response]) -> tuple[LLMClient, list[Any]]:
    calls: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return replies.pop(0)

    client = LLMClient(conn, Budget(conn, run_id, NOW), "m", "k",
                       transport=httpx.MockTransport(handler), sleep=lambda _: None)
    return client, calls


def _reply(content: str, finish_reason: str = "stop") -> httpx.Response:
    body = json.loads(fixture_bytes("openrouter_chat.json"))
    body["choices"][0]["message"]["content"] = content
    body["choices"][0]["finish_reason"] = finish_reason
    return httpx.Response(200, json=body)


def _model(conn: Conn) -> dict[str, Any]:
    cur = conn.execute("SELECT * FROM models")
    row = cur.fetchone()
    assert row is not None and cur.description is not None
    return dict(zip([c.name for c in cur.description], row, strict=True))


@pytest.mark.db
def test_dopuna_popunjava_samo_null_polja_i_belezi_izvor(conn: Conn) -> None:
    llm, calls = _llm(conn, _setup(conn), [_reply(json.dumps(FIELDS))])

    assert enrich_models(conn, llm) == []
    assert enrich_models(conn, llm) == []  # ponovno pokretanje: keš, bez novog poziva

    model = _model(conn)
    assert len(calls) == 1
    assert "Mistral Large 4" in calls[0]["messages"][0]["content"]
    assert (model["context_window"], float(model["price_in"])) == (262144, 1.0)  # FR-004
    assert (model["org"], model["license"], model["open_weights"]) == ("Mistral AI", "Apache 2.0",
                                                                      True)
    assert model["summary_sr"] == FIELDS["summary_sr"]
    assert model["field_sources"]["license"] == f"llm:{URL}"
    assert model["field_sources"]["context_window"] == "openrouter"


@pytest.mark.db
def test_strukturirani_izvor_prepisuje_llm_vrednost(conn: Conn) -> None:
    llm, _ = _llm(conn, _setup(conn), [_reply(json.dumps(FIELDS))])
    enrich_models(conn, llm)

    upsert_models(conn, "openrouter", 1, [ModelItem(
        raw_name="mistralai/mistral-large-4", name="Mistral Large 4", license="mit",
        source_url="https://openrouter.ai/x")], {})

    model = _model(conn)
    assert (model["license"], model["field_sources"]["license"]) == ("mit", "openrouter")


@pytest.mark.db
def test_model_pomenut_samo_na_kraju_stranice_se_ne_dopunjuje(conn: Conn) -> None:
    _setup(conn, content="Gemini Omni 1.2 Flash | Google\n" + "x" * 300 + "\nMistral Large 4")
    assert find_pairs(conn) == []


@pytest.mark.db
def test_neuspela_ekstrakcija_ide_u_review_queue_i_ne_ponavlja_se(conn: Conn) -> None:
    run_id = _setup(conn)
    llm, calls = _llm(conn, run_id, [_reply("{}"), _reply("{}")])

    assert enrich_models(conn, llm) == []
    assert enrich_models(conn, llm) == []  # sutrašnje pokretanje: par se preskače

    assert len(calls) == 2  # jedan poziv i jedan retry, samo prvi put
    row = conn.execute("SELECT reason, payload->>'url' FROM review_queue").fetchone()
    assert row == ("extraction_failed", URL)


@pytest.mark.db
def test_greska_provajdera_se_belezi_i_ne_upisuje_nista(conn: Conn) -> None:
    llm, _ = _llm(conn, _setup(conn), [httpx.Response(400)])

    errors = enrich_models(conn, llm)

    assert [(e["source"], e["kind"]) for e in errors] == [("llm", "error")]
    assert _model(conn)["license"] is None


@pytest.mark.db
def test_potrosen_budzet_daje_partial_bez_poziva(conn: Conn) -> None:
    _setup(conn)
    conn.execute("INSERT INTO runs (started_at, cost_usd) VALUES (%s, 5)", (NOW,))
    calls: list[Any] = []

    def make_llm(c: Conn, budget: Budget) -> LLMClient:
        llm, recorded = _llm(c, budget.run_id, [])
        calls.extend(recorded)
        return llm

    ctx = Ctx(now=NOW, config=SourcesFile(sources=[]), client=None, llm=make_llm)  # type: ignore[arg-type]
    assert run(conn, ctx) == "partial"  # FR-019
    assert calls == []
    errors = conn.execute("SELECT errors FROM runs ORDER BY id DESC").fetchone()[0]  # type: ignore[index]
    assert [e["kind"] for e in errors] == ["budget"]


@pytest.mark.db
def test_limit_poziva_po_pokretanju(conn: Conn, monkeypatch: pytest.MonkeyPatch) -> None:
    llm, calls = _llm(conn, _setup(conn), [])
    monkeypatch.setattr(enrich, "MAX_CALLS", 0)

    assert [e["kind"] for e in enrich_models(conn, llm)] == ["limit"]
    assert calls == []


def _another_model(conn: Conn, raw_name: str, name: str, complete: bool) -> None:
    fields: dict[str, Any] = {}
    if complete:
        fields = {"org": "Mistral AI", "released_at": "2026-11-01", "params_b": Decimal(100),
                  "context_window": 1000, "price_in": Decimal(1), "price_out": Decimal(2),
                  "license": "mit", "open_weights": True}
    upsert_models(conn, "openrouter", 1, [ModelItem(
        raw_name=raw_name, name=name, source_url="https://openrouter.ai/y", **fields)], {})
    if complete:
        conn.execute("UPDATE models SET summary_sr = 's' WHERE name = %s", (name,))


@pytest.mark.db
@pytest.mark.parametrize("complete", [True, False])
def test_najava_drugog_modela_ne_daje_par(conn: Conn, complete: bool) -> None:
    _setup(conn, content="Following Mistral Large 4, we introduce Mistral Medium 4.")
    conn.execute("UPDATE documents SET title = 'Introducing Mistral Medium 4'")
    _another_model(conn, "mistralai/mistral-medium-4", "Mistral Medium 4", complete)
    # U naslovu je Medium 4: Large 4 (iz uvoda) nikad ne dobija tuđi sažetak.
    expected = [] if complete else ["Mistral Medium 4"]
    assert [p[1] for p in find_pairs(conn)] == expected


@pytest.mark.db
@pytest.mark.parametrize(("title", "content"), [
    ("Introducing Mistral Medium 4",
     "Introducing Mistral Medium 4 | Mistral\nFollowing Mistral Large 4, we go further."),
    ("Introducing the Decisions API",
     "Decisions API | Mistral\nThe API is powered by Mistral Large 4."),
    ("Introducing Mistral Large 4 Instruct", "Mistral Large 4 Instruct | Mistral\nText."),
    ("Le Chonk: Built for Coders", "Following Mistral Large 4, a single RSS line."),
])
def test_model_van_naslova_ne_dobija_najavu(conn: Conn, title: str, content: str) -> None:
    # Jedini model u trackeru je Large 4; najava je o modelu koji tracker još ne zna.
    _setup(conn, content=content)
    conn.execute("UPDATE documents SET title = %s", (title,))
    assert find_pairs(conn) == []


@pytest.mark.db
def test_odseceni_izlaz_ide_u_review_queue_i_ne_placa_se_ponovo(conn: Conn) -> None:
    llm, calls = _llm(conn, _setup(conn), [_reply('{"org": "Mis', "length")])

    assert enrich_models(conn, llm) == []
    assert enrich_models(conn, llm) == []  # sutra: par se preskače

    assert len(calls) == 1 and MAX_TOKENS > 0
    assert conn.execute("SELECT reason FROM review_queue").fetchone() == ("extraction_failed",)


@pytest.mark.db
@pytest.mark.parametrize("bad_field", [
    {"context_window": 3_000_000_000}, {"price_out": -1}, {"params_b": 0},
    {"license": "MIT\u0000"},  # schema ga prima, a JSONB i TEXT ne: DataError
    {"price_in": "INF"},
])
def test_vrednost_van_opsega_se_ne_upisuje_ni_ne_kesira(
    conn: Conn, bad_field: dict[str, Any]
) -> None:
    # 1e999 je u JSON-u beskonačno; json.dumps bi ga upisao kao nestandardno `Infinity`.
    bad = json.dumps(FIELDS | bad_field).replace('"INF"', "1e999")
    llm, _ = _llm(conn, _setup(conn), [_reply(bad), _reply(bad)])

    assert enrich_models(conn, llm) == []  # ranije: NumericValueOutOfRange i pad svakog dana

    assert conn.execute("SELECT count(*) FROM llm_cache").fetchone() == (0,)
    assert conn.execute("SELECT reason FROM review_queue").fetchone() == ("extraction_failed",)
    assert _model(conn)["license"] is None


@pytest.mark.db
def test_limit_broji_i_retry(conn: Conn, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = _setup(conn)
    _another_model(conn, "mistralai/mistral-large-4-instruct", "Mistral Large 4 Instruct", False)
    conn.execute("UPDATE documents SET title = 'Mistral Large 4 i Mistral Large 4 Instruct'")
    monkeypatch.setattr(enrich, "MAX_CALLS", 2)
    llm, calls = _llm(conn, run_id, [_reply("{}"), _reply("{}")])

    errors = enrich_models(conn, llm)

    # Prvi par potroši 2 plaćena poziva (pokušaj i retry), pa drugi par ne dobija poziv.
    assert len(calls) == 2
    assert [e["kind"] for e in errors] == ["limit"]


@pytest.mark.db
def test_duzi_naziv_drugog_modela_nije_pomen_kraceg(conn: Conn) -> None:
    _setup(conn, content="Today we release it for chat.")
    conn.execute("UPDATE documents SET title = 'Introducing Mistral Large 4 Instruct'")
    _another_model(conn, "mistralai/mistral-large-4-instruct", "Mistral Large 4 Instruct", True)
    # U naslovu je samo Instruct (potpun), pa Mistral Large 4 ne dobija tuđu najavu.
    assert find_pairs(conn) == []
