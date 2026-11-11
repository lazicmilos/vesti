import pytest

from aitracker.config import load_glossary
from aitracker.llm.client import PROMPTS_DIR, render

VARIABLES = {
    "model_fields_v1": {"model_name", "source_url", "text", "glossary"},
    "event_summary_v1": {"text", "glossary"},
}


def test_recnik_ima_sve_termine_iz_speca() -> None:
    glossary = load_glossary()

    assert len(glossary.splitlines()) == 8
    assert "- context window → kontekstni prozor" in glossary


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_prompt_se_renderuje_sa_tacno_svojim_promenljivim(name: str) -> None:
    template = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

    text = render(template, {var: f"<{var}>" for var in VARIABLES[name]})

    assert "{{" not in text and "<text>" in text and "kontekstni" not in text


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_prompt_sadrzi_obavezna_pravila_iz_speca(name: str) -> None:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

    # SPEC 11.3: samo tekst izvora, null umesto procene, srpski latinicom, rečnik, samo JSON.
    for rule in ("isključivo priložen", "`null`", "latinicom", "rečnika", "samo JSON"):
        assert rule in text
