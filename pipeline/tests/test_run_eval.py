from datetime import date
from decimal import Decimal
from typing import Any

from run_eval import FIELDS, markdown, same, score


def _gold(slug: str, labeled: bool = True, **gold: str) -> dict[str, str]:
    row = {"slug": slug, "official_url": "https://lab.example" if labeled else "",
           "duplicate_of": ""}
    return row | {f"gold_{f}": gold.get(f, "") for f in FIELDS}


def _tracked(**fields: tuple[Any, str]) -> dict[str, tuple[Any, str]]:
    return {f: fields.get(f, (None, "")) for f in FIELDS}


def test_same_normalizuje_po_tipu_polja() -> None:
    assert same("price_in", Decimal("0.70"), "0.7")
    assert same("context_window", 128000, "128000")
    assert not same("params_b", Decimal(70), "7")
    assert same("released_at", date(2026, 11, 1), "2026-11-01")
    assert same("open_weights", False, "false") and not same("open_weights", True, "false")
    assert same("org", "mistralai", "Mistral AI") and same("license", "Apache-2.0", "apache 2.0")


def test_score_razdvaja_llm_polja_i_broji_izmisljene() -> None:
    llm = "llm:https://mistral.ai/news/x"
    gold = [
        _gold("a", org="Mistral AI", license="Apache 2.0", price_in="1"),
        _gold("b", license="MIT"),
        _gold("c", license="MIT"),  # nije označen dole: official_url prazan
    ]
    gold[2]["official_url"] = ""
    gold[1]["duplicate_of"] = "a"
    tracker = {
        "a": _tracked(org=("mistralai", "openrouter"), license=("Apache 2.0", llm),
                      price_in=(Decimal(2), "openrouter"), params_b=(Decimal(1000), llm)),
        "b": _tracked(license=("GPL", llm)),
        "c": _tracked(license=("GPL", llm)),
    }

    every, only_llm, labeled, duplicates = score(gold, tracker)

    assert (labeled, duplicates) == (2, 1)
    # Sva polja: org tačno, license 1 tačno + 1 pogrešno, price_in pogrešno.
    assert every.correct == {"org": 1, "license": 1}
    assert every.wrong == {"license": 1, "price_in": 1}
    # LLM: license a tačno, license b pogrešno; params_b a nije u zvaničnom izvoru: izmišljeno.
    assert only_llm.correct == {"license": 1} and only_llm.wrong == {"license": 1}
    assert only_llm.invented == {"params_b": 1}
    assert "params_b" not in every.invented  # izmišljeno se računa samo za LLM

    table = markdown(every, only_llm, labeled, duplicates)
    assert "| **ukupno** | 50.0% (2/4) | 50.0% (1/2) | 1 |" in table


def test_null_u_trackeru_nije_greska() -> None:
    every, only_llm, _, _ = score([_gold("a", license="MIT")], {"a": _tracked()})
    assert not (every.correct or every.wrong or only_llm.invented)
