from decimal import Decimal
from typing import Any

import pytest

from aitracker.db import Conn
from aitracker.review import ReviewError, pending, resolve_item
from aitracker.sources.base import ModelItem
from aitracker.tracker import upsert_models

pytestmark = pytest.mark.db
ORG_ALIASES = {"meta-llama": "meta"}


def _item(raw_name: str = "openai/gpt-5", **fields: Any) -> ModelItem:
    defaults: dict[str, Any] = {
        "name": raw_name.split("/")[-1], "org": "OpenAI",
        "source_url": f"https://example.com/{raw_name}",
    }
    return ModelItem(raw_name=raw_name, **(defaults | fields))


def _source_id(conn: Conn, name: str = "openrouter") -> int:
    row = conn.execute(
        "INSERT INTO sources (name, kind, role, url) VALUES (%s, 'api', 'tracker', 'u') "
        "ON CONFLICT (name) DO UPDATE SET url = 'u' RETURNING id", (name,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _upsert(conn: Conn, items: list[ModelItem], source: str = "openrouter") -> tuple[int, int]:
    return upsert_models(conn, source, _source_id(conn, source), items, ORG_ALIASES)


def _one(conn: Conn, query: str) -> tuple[Any, ...]:
    row = conn.execute(query.encode()).fetchone()
    assert row is not None
    return row


def test_upsert_novi_model_dobija_slug_alias_i_nije_verifikovan(conn: Conn) -> None:
    result = _upsert(conn, [_item("openai/gpt-5-2026-11-01", price_in=Decimal("1.5"))])

    assert result == (1, 0)
    assert _one(conn, "SELECT slug, verified, price_in, source_url FROM models") == (
        "gpt-5", False, Decimal("1.5"), "https://example.com/openai/gpt-5-2026-11-01")
    assert _one(conn, "SELECT alias_norm, alias_raw FROM model_aliases") == (
        "gpt-5", "openai/gpt-5-2026-11-01")


def test_upsert_polje_koje_izvor_ne_navodi_ostaje_null(conn: Conn) -> None:
    _upsert(conn, [_item(context_window=1000)])

    assert _one(conn, "SELECT params_b, license, released_at, price_in FROM models") == (
        None, None, None, None)
    assert _one(conn, "SELECT field_sources FROM models") == ({"context_window": "openrouter"},)


def test_upsert_ponovno_pokretanje_ne_pravi_duplikate_ni_novu_istoriju(conn: Conn) -> None:
    items = [_item(price_in=Decimal("1"), price_out=Decimal("5"))]
    _upsert(conn, items)
    before = _one(conn, "SELECT updated_at FROM models")

    result = _upsert(conn, items)

    assert result == (0, 0)
    assert _one(conn, "SELECT count(*) FROM models") == (1,)
    assert _one(conn, "SELECT count(*) FROM model_price_history") == (1,)
    assert _one(conn, "SELECT updated_at FROM models") == before


def test_upsert_pravilo_1_datirani_naziv_pogadja_postojeci_model(conn: Conn) -> None:
    _upsert(conn, [_item("openai/gpt-5")])

    result = _upsert(conn, [_item("openai/gpt-5-20261101")])

    assert result == (0, 0)
    assert _one(conn, "SELECT count(*) FROM models") == (1,)


def test_upsert_pravilo_2_slicno_ime_ide_u_review_queue_bez_novog_modela(conn: Conn) -> None:
    _upsert(conn, [_item("anthropic/claude-sonnet-5", org="Anthropic")])

    result = _upsert(conn, [_item("anthropic/claude-sonnet-5.5", org="Anthropic")])

    assert result == (0, 1)
    assert _one(conn, "SELECT count(*) FROM models") == (1,)
    assert _one(conn, "SELECT raw_name, reason, m.slug FROM review_queue q "
                      "JOIN models m ON m.id = q.candidate_model_id") == (
        "anthropic/claude-sonnet-5.5", "similar_name", "claude-sonnet-5")


def test_upsert_slicno_ime_se_upisuje_u_review_queue_samo_jednom(conn: Conn) -> None:
    items = [_item("anthropic/claude-sonnet-5", org="Anthropic"),
             _item("anthropic/claude-sonnet-5.5", org="Anthropic")]
    _upsert(conn, items)

    result = _upsert(conn, items)

    assert result == (0, 0)
    assert _one(conn, "SELECT count(*) FROM review_queue") == (1,)


def test_upsert_slicnost_vazi_i_preko_aliasa_organizacije(conn: Conn) -> None:
    _upsert(conn, [_item("meta/llama-4-70b-instruct", org="Meta")])

    result = _upsert(conn, [_item("meta-llama/Llama-4-70B-Instruct2", org="meta-llama")],
                     source="huggingface")

    assert result == (0, 1)


def test_upsert_pravilo_3_slicno_ime_druge_organizacije_pravi_novi_model(conn: Conn) -> None:
    _upsert(conn, [_item("anthropic/claude-sonnet-5", org="Anthropic")])

    result = _upsert(conn, [_item("drugi/claude-sonnet-5.5", org="Drugi")])

    assert result == (1, 0)


def test_upsert_promena_cene_upisuje_novi_red_istorije(conn: Conn) -> None:
    _upsert(conn, [_item(price_in=Decimal("1"), price_out=Decimal("5"))])

    _upsert(conn, [_item(price_in=Decimal("0.8"), price_out=Decimal("5"))])

    rows = conn.execute(
        "SELECT price_in, price_out FROM model_price_history ORDER BY id"
    ).fetchall()
    assert rows == [(Decimal("1"), Decimal("5")), (Decimal("0.8"), Decimal("5"))]
    assert _one(conn, "SELECT price_in FROM models") == (Decimal("0.8"),)


def test_upsert_model_bez_cene_nema_red_istorije(conn: Conn) -> None:
    _upsert(conn, [_item()])

    assert _one(conn, "SELECT count(*) FROM model_price_history") == (0,)


def test_upsert_drugi_izvor_popunjava_null_ali_ne_prepisuje_tudju_vrednost(conn: Conn) -> None:
    _upsert(conn, [_item(context_window=1000)])

    _upsert(conn, [_item("OpenAI/GPT-5", context_window=2000, license="mit")],
            source="huggingface")

    assert _one(conn, "SELECT context_window, license, field_sources FROM models") == (
        1000, "mit", {"context_window": "openrouter", "license": "huggingface"})


def test_upsert_none_iz_izvora_ne_brise_postojecu_vrednost(conn: Conn) -> None:
    _upsert(conn, [_item(context_window=1000)])

    _upsert(conn, [_item(context_window=None)])

    assert _one(conn, "SELECT context_window FROM models") == (1000,)


def test_upsert_alias_izvora_spaja_zapise_dva_izvora_u_jedan_model(conn: Conn) -> None:
    _upsert(conn, [_item("qwen/qwen3-coder", org="Qwen",
                         aliases=["Qwen/Qwen3-Coder-480B-A35B-Instruct"])])

    result = _upsert(conn, [_item("Qwen/Qwen3-Coder-480B-A35B-Instruct", org="Qwen",
                                  params_b=Decimal("480"))], source="huggingface")

    assert result == (0, 0)
    assert _one(conn, "SELECT slug, params_b FROM models") == ("qwen3-coder", Decimal("480"))


def test_upsert_datirani_snimak_u_istoj_seriji_ne_prepisuje_cenu_modela(conn: Conn) -> None:
    result = _upsert(conn, [
        _item("deepseek/deepseek-v4-1017", org="DeepSeek", price_in=Decimal("9")),
        _item("deepseek/deepseek-v4", org="DeepSeek", price_in=Decimal("2")),
    ])

    assert result == (1, 0)
    assert _one(conn, "SELECT price_in FROM models") == (Decimal("2"),)
    assert _one(conn, "SELECT count(*) FROM model_price_history") == (1,)


def _queued(conn: Conn) -> int:
    _upsert(conn, [_item("anthropic/claude-sonnet-5", org="Anthropic"),
                   _item("anthropic/claude-sonnet-5.5", org="Anthropic", context_window=500)])
    return int(pending(conn)[0][0])


def test_pending_vraca_neresene_stavke_sa_kandidatom(conn: Conn) -> None:
    item_id = _queued(conn)

    assert pending(conn) == [(item_id, "anthropic/claude-sonnet-5.5", "openrouter",
                              "claude-sonnet-5",
                              "https://example.com/anthropic/claude-sonnet-5.5")]


def test_resolve_item_new_pravi_model_iz_sacuvanih_podataka(conn: Conn) -> None:
    resolve_item(conn, _queued(conn), "new")

    assert _one(conn, "SELECT context_window, field_sources FROM models "
                      "WHERE slug = 'claude-sonnet-5.5'") == (
        500, {"context_window": "openrouter"})
    assert pending(conn) == []


def test_resolve_item_merge_dodaje_alias_kandidatu(conn: Conn) -> None:
    resolve_item(conn, _queued(conn), "merge")

    assert _one(conn, "SELECT count(*) FROM models") == (1,)
    assert _one(conn, "SELECT m.slug FROM model_aliases a JOIN models m ON m.id = a.model_id "
                      "WHERE a.alias_norm = 'claude-sonnet-5.5'") == ("claude-sonnet-5",)


def test_resolve_item_discard_ne_menja_modele_i_ne_vraca_se_u_red(conn: Conn) -> None:
    resolve_item(conn, _queued(conn), "discard")

    again = _upsert(conn, [_item("anthropic/claude-sonnet-5.5", org="Anthropic")])

    assert again == (0, 0)
    assert _one(conn, "SELECT count(*) FROM models") == (1,)
    assert pending(conn) == []


def test_resolve_item_posle_new_sledece_pokretanje_pogadja_model(conn: Conn) -> None:
    resolve_item(conn, _queued(conn), "new")

    again = _upsert(conn, [_item("anthropic/claude-sonnet-5.5", org="Anthropic")])

    assert again == (0, 0)
    assert _one(conn, "SELECT count(*) FROM models") == (2,)


@pytest.mark.parametrize("item_id", [pytest.param(999_999, id="nevazeca-nepostojeca-stavka")])
def test_resolve_item_nepostojeca_stavka_baca_review_error(conn: Conn, item_id: int) -> None:
    with pytest.raises(ReviewError, match="ne postoji ili je već rešena"):
        resolve_item(conn, item_id, "discard")


def test_resolve_item_vec_resena_stavka_baca_review_error(conn: Conn) -> None:
    item_id = _queued(conn)
    resolve_item(conn, item_id, "discard")

    with pytest.raises(ReviewError, match="već rešena"):
        resolve_item(conn, item_id, "new")
