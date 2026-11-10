from datetime import date
from decimal import Decimal

import httpx
import pytest
from conftest import fixture_bytes, offline_client

from aitracker.sources import huggingface, openrouter
from aitracker.sources.base import EmptySource, ModelItem, SourceError


def _openrouter() -> dict[str, ModelItem]:
    return {m.raw_name: m for m in openrouter.parse_models(fixture_bytes("openrouter.json"))}


def test_openrouter_cena_po_tokenu_se_pretvara_u_usd_po_milion() -> None:
    model = _openrouter()["anthropic/claude-fable-5.2"]

    # pricing.prompt = "0.000008", pricing.completion = "0.00004"
    assert (model.price_in, model.price_out) == (Decimal("8"), Decimal("40"))


def test_openrouter_mala_cena_ostaje_tacna_bez_greske_zaokruzivanja() -> None:
    model = _openrouter()["deepseek/deepseek-v4.1-flash-1017"]

    assert str(model.price_in) == "0.006"


def test_openrouter_naziv_i_organizacija_iz_prikaznog_imena() -> None:
    model = _openrouter()["anthropic/claude-sonnet-5.5"]

    assert (model.org, model.name) == ("Anthropic", "Claude Sonnet 5.5")
    assert model.context_window == 1_000_000
    assert model.source_url == "https://openrouter.ai/anthropic/claude-sonnet-5.5"


def test_openrouter_varijanta_se_preskace_kad_postoji_osnovni_model() -> None:
    models = _openrouter()

    assert "anthropic/claude-fable-5.2:batch" not in models
    # cena je osnovna (8), ne batch (4)
    assert models["anthropic/claude-fable-5.2"].price_in == Decimal("8")


def test_openrouter_varijanta_bez_osnovnog_modela_ulazi_pod_osnovnim_imenom() -> None:
    model = _openrouter()["thinkingmachines/inkling-2-small"]

    assert model.name == "Inkling 2 Small"


def test_openrouter_precica_latest_se_preskace() -> None:
    assert not any(name.startswith("~") for name in _openrouter())


def test_openrouter_router_sa_cenom_minus_jedan_ima_cenu_none() -> None:
    model = _openrouter()["openrouter/auto"]

    assert (model.price_in, model.price_out) == (None, None)
    assert model.org == "openrouter"


def test_openrouter_hugging_face_id_postaje_alias_i_open_weights() -> None:
    model = _openrouter()["qwen/qwen3-coder"]

    assert model.aliases == ["Qwen/Qwen3-Coder-480B-A35B-Instruct"]
    assert model.open_weights is True


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("anthropic/claude-sonnet-5", id="hugging-face-id-null"),
        pytest.param("openai/gpt-audio", id="hugging-face-id-prazan-string"),
    ],
)
def test_openrouter_bez_hugging_face_id_open_weights_je_nepoznato(name: str) -> None:
    model = _openrouter()[name]

    assert model.open_weights is None
    assert model.aliases == []


def test_openrouter_polja_koja_izvor_ne_daje_ostaju_none() -> None:
    model = _openrouter()["anthropic/claude-sonnet-5"]

    assert (model.params_b, model.license) == (None, None)


def test_openrouter_datum_dodavanja_je_priblizan_datum_izdanja() -> None:
    model = _openrouter()["nex-agi/nex-n2.6"]

    # created = 1794282379 → 2026-11-10 UTC
    assert model.released_at == date(2026, 11, 10)


def test_openrouter_bez_created_datum_je_none() -> None:
    body = b'{"data": [{"id": "lab/x", "name": "Lab: X"}]}'

    assert openrouter.parse_models(body)[0].released_at is None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<html>", id="nevazeca-nije-json"),
        pytest.param(b'{"error": "x"}', id="nevazeca-bez-data"),
        pytest.param(b'{"data": [{"id": "a/b"}]}', id="nevazeca-model-bez-imena"),
    ],
)
def test_openrouter_neispravan_odgovor_baca_source_error(body: bytes) -> None:
    with pytest.raises(SourceError, match="neispravan OpenRouter odgovor"):
        openrouter.parse_models(body)


def _huggingface(min_likes: int = 1000) -> dict[str, ModelItem]:
    items = huggingface.parse_models(fixture_bytes("huggingface.json"), min_likes)
    return {m.raw_name: m for m in items}


def test_huggingface_broj_parametara_u_milijardama_i_licenca() -> None:
    model = _huggingface()["mistralai/Mistral-7B-v0.1"]

    # safetensors.total = 7241732096
    assert model.params_b == Decimal("7.242")
    assert model.license == "apache-2.0"
    assert (model.org, model.name, model.open_weights) == ("mistralai", "Mistral-7B-v0.1", True)
    assert model.source_url == "https://huggingface.co/mistralai/Mistral-7B-v0.1"


def test_huggingface_kvantizovana_kopija_se_preskace() -> None:
    assert "prism-ml/Ternary-Bonsai-2-27B-gguf" not in _huggingface()


def test_huggingface_finetune_istog_laba_ostaje() -> None:
    assert "Qwen/Qwen3-8B" in _huggingface()


def test_huggingface_licenca_unknown_je_none() -> None:
    assert _huggingface()["tiiuae/falcon-180B"].license is None


@pytest.mark.parametrize(
    ("min_likes", "present"),
    [
        # tiiuae/falcon-180B ima 1153 lajka
        pytest.param(1153, True, id="bva-tacno-na-pragu"),
        pytest.param(1154, False, id="bva-jedan-ispod-praga"),
    ],
)
def test_huggingface_prag_popularnosti(min_likes: int, present: bool) -> None:
    assert ("tiiuae/falcon-180B" in _huggingface(min_likes)) is present


def test_huggingface_cena_i_context_window_se_ne_izmisljaju() -> None:
    model = _huggingface()["deepseek-ai/DeepSeek-R1"]

    assert (model.price_in, model.price_out, model.context_window) == (None, None, None)


def test_huggingface_neispravan_odgovor_baca_source_error() -> None:
    with pytest.raises(SourceError, match="neispravan Hugging Face odgovor"):
        huggingface.parse_models(b'{"error": "rate limited"}', 1000)


def _client(body: bytes, seen: list[httpx.Request]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(request)
        return httpx.Response(200, content=body)

    return offline_client(handler)


def test_huggingface_fetch_trazi_sortiranje_po_lajkovima() -> None:
    seen: list[httpx.Request] = []
    source = huggingface.HuggingFaceSource(
        "huggingface", "https://hf.example/api/models",
        _client(fixture_bytes("huggingface.json"), seen),  # type: ignore[arg-type]
    )

    models = source.fetch_models()

    assert len(models) == 5
    assert seen[0].url.params["sort"] == "likes"
    assert seen[0].url.params.get_list("expand[]") == ["safetensors", "tags", "likes", "author"]


def test_huggingface_fetch_nista_iznad_praga_baca_empty_source() -> None:
    source = huggingface.HuggingFaceSource(
        "huggingface", "https://hf.example/api/models",
        _client(b"[]", []),  # type: ignore[arg-type]
    )

    with pytest.raises(EmptySource, match="huggingface"):
        source.fetch_models()


def test_openrouter_fetch_prazan_spisak_baca_empty_source() -> None:
    source = openrouter.OpenRouterSource(
        "openrouter", "https://or.example/models",
        _client(b'{"data": []}', []),  # type: ignore[arg-type]
    )

    with pytest.raises(EmptySource, match="openrouter"):
        source.fetch_models()
