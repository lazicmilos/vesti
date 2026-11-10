import pytest

from aitracker.identity import Match, Registry, normalize, org_key, resolve


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("GPT-5", "gpt-5", id="ep-mala-slova"),
        pytest.param("openai/gpt-5", "gpt-5", id="ep-prefiks-organizacije"),
        pytest.param("Qwen/Qwen3-VL-8B-Instruct", "qwen3-vl-8b-instruct", id="ep-hf-oblik"),
        pytest.param("gpt-4o-2024-08-06", "gpt-4o", id="ep-sufiks-yyyy-mm-dd"),
        pytest.param("claude-sonnet-5-20260630", "claude-sonnet-5", id="ep-sufiks-yyyymmdd"),
        pytest.param("mistral-large-2026-11", "mistral-large", id="ep-sufiks-yyyy-mm"),
        pytest.param("deepseek-v4.1-flash-1017", "deepseek-v4.1-flash", id="ep-sufiks-mmdd"),
        pytest.param("Claude Sonnet 5", "claude-sonnet-5", id="ep-razmaci"),
        pytest.param("llama_3_8b", "llama-3-8b", id="ep-donje-crte"),
        pytest.param("a__b -  c", "a-b-c", id="ep-spajanje-crtica"),
        pytest.param("gpt-5-preview", "gpt-5-preview", id="nije-datum-preview"),
        pytest.param("gpt-5-mini", "gpt-5-mini", id="nije-datum-mini"),
        pytest.param("gpt-5-pro", "gpt-5-pro", id="nije-datum-pro"),
        pytest.param("gemini-3.6-flash", "gemini-3.6-flash", id="nije-datum-verzija-sa-tackom"),
        pytest.param("model-0101", "model", id="bva-mmdd-najmanji"),
        pytest.param("model-1231", "model", id="bva-mmdd-najveci"),
        pytest.param("model-0100", "model-0100", id="bva-mmdd-dan-nula"),
        pytest.param("model-0132", "model-0132", id="bva-mmdd-dan-32"),
        pytest.param("model-0001", "model-0001", id="bva-mmdd-mesec-nula"),
        pytest.param("model-1301", "model-1301", id="bva-mmdd-mesec-13"),
        pytest.param("llama-3-8192", "llama-3-8192", id="pogadjanje-cetiri-cifre-nisu-datum"),
        pytest.param("model-123", "model-123", id="bva-tri-cifre"),
        pytest.param("model-12345", "model-12345", id="bva-pet-cifara"),
        pytest.param("gpt-4-0613-preview", "gpt-4-0613-preview", id="datum-nije-na-kraju"),
        pytest.param("  openai/GPT-5  ", "gpt-5", id="pogadjanje-razmaci-oko-imena"),
    ],
)
def test_normalize_ime_modela_vraca_kanonski_alias(name: str, expected: str) -> None:
    assert normalize(name) == expected


def test_normalize_vec_normalizovano_ime_ostaje_isto() -> None:
    once = normalize("OpenAI/GPT_5 Mini-2026-11-10")

    assert normalize(once) == once == "gpt-5-mini"


@pytest.mark.parametrize(
    ("org", "expected"),
    [
        pytest.param("meta-llama", "meta", id="ep-alias"),
        pytest.param("Meta-Llama", "meta", id="ep-alias-velika-slova"),
        pytest.param("OpenAI", "openai", id="ep-bez-aliasa"),
        pytest.param(None, None, id="bva-none"),
        pytest.param("", None, id="bva-prazno"),
    ],
)
def test_org_key_vraca_zajednicki_kljuc(org: str | None, expected: str | None) -> None:
    assert org_key(org, {"meta-llama": "meta"}) == expected


def _registry() -> Registry:
    return Registry(aliases={"claude-sonnet-5": 1, "gpt-5": 2}, orgs={1: "anthropic", 2: "openai"})


def test_resolve_pravilo_1_tacan_alias_vraca_postojeci_model() -> None:
    match = resolve(["anthropic/claude-sonnet-5-20260630"], "anthropic", _registry())

    assert match == Match("existing", 1)


def test_resolve_pravilo_1_poklapanje_preko_aliasa_izvora() -> None:
    match = resolve(["openai/novo-ime", "OpenAI/GPT-5"], "openai", _registry())

    assert match == Match("existing", 2)


def test_resolve_pravilo_1_ima_prednost_nad_slicnoscu_u_drugoj_organizaciji() -> None:
    # tačno poklapanje važi i kad izvor navodi drugu organizaciju
    match = resolve(["reseller/gpt-5"], "reseller", _registry())

    assert match == Match("existing", 2)


def test_resolve_pravilo_2_slicno_ime_iste_organizacije_ide_na_pregled() -> None:
    # ratio("claude-sonnet-5.5", "claude-sonnet-5") = 93,75
    match = resolve(["anthropic/claude-sonnet-5.5"], "anthropic", _registry())

    assert match == Match("similar", 1)


def test_resolve_pravilo_3_slicno_ime_druge_organizacije_je_novi_model() -> None:
    match = resolve(["drugi-lab/claude-sonnet-5.5"], "drugi-lab", _registry())

    assert match == Match("new")


def test_resolve_pravilo_3_bez_organizacije_nema_provere_slicnosti() -> None:
    match = resolve(["claude-sonnet-5.5"], None, _registry())

    assert match == Match("new")


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        # ratio("gpt-5", ...) : "gpt-5-mini" 66,7; "gpt-5-pro" 71,4; "gpt-5-preview" 55,6
        pytest.param("gpt-5-mini", "new", id="sufiks-mini-je-drugi-model"),
        pytest.param("gpt-5-pro", "new", id="sufiks-pro-je-drugi-model"),
        pytest.param("gpt-5-preview", "new", id="sufiks-preview-je-drugi-model"),
    ],
)
def test_resolve_sufiksi_koji_nisu_datum_ne_spajaju_modele(name: str, kind: str) -> None:
    assert resolve([f"openai/{name}"], "openai", _registry()).kind == kind


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        # prema aliasu "abcdefghij" (10 znakova): 2*9/(10+10) = 90,0 i 2*9/(10+11) = 85,7
        pytest.param("abcdefghiX", "similar", id="bva-ratio-tacno-90"),
        pytest.param("abcdefghiXY", "new", id="bva-ratio-ispod-90"),
    ],
)
def test_resolve_prag_slicnosti_je_ukljucivo_90(name: str, kind: str) -> None:
    registry = Registry(aliases={"abcdefghij": 7}, orgs={7: "lab"})

    assert resolve([name], "lab", registry).kind == kind


def test_resolve_prazan_registar_daje_novi_model() -> None:
    assert resolve(["openai/gpt-5"], "openai", Registry()) == Match("new")
