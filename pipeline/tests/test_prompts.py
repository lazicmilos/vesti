from pathlib import Path
from string import Template

import pytest

from aitracker.llm.client import GLOSSARY, PROMPTS, render_glossary

# Promenljive koje pozivalac daje; `glossary` dodaje klijent.
VARIABLES = {
    "model_fields_v1": {"name", "text", "glossary"},
    "event_summary_v1": {"text", "glossary"},
}


@pytest.mark.parametrize("path", sorted(PROMPTS.glob("*.md")), ids=lambda p: p.stem)
def test_prompt_renders_with_declared_variables(path: Path) -> None:
    template = Template(path.read_text(encoding="utf-8"))
    # `$` van promenljive (npr. „$5“) ruši substitute u produkciji; piše se kao `$$`.
    assert template.is_valid()
    assert set(template.get_identifiers()) == VARIABLES[path.stem]


def test_glossary_renders_every_term() -> None:
    lines = render_glossary(GLOSSARY).splitlines()
    assert "- context window → kontekstni prozor" in lines
    assert len(lines) == 8
