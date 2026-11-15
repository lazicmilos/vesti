import csv
import random
from pathlib import Path

from blind_test import HEADER, Doc, Output, anonymize, plain_text, select, write_csv

from aitracker.llm.schemas import EventSummary

MODELS = ["m/one", "m/two", "m/three"]
SUMMARY = EventSummary(title_sr="Naslov", summary_sr="x" * 80, category="ai",
                       mentioned_models=["GPT-5", "Le Chonk"])


def _docs(lab: int, news: int) -> list[Doc]:
    sources = ["mistral-blog"] * lab + ["the-verge"] * news
    return [Doc(i, s, f"https://e.com/{i}", f"tekst {i}") for i, s in enumerate(sources)]


def test_select_favors_labs_is_reproducible_and_fills_shortage() -> None:
    docs = _docs(lab=40, news=40)
    picked = select(docs, random.Random(1))
    assert len(picked) == 30 and len({d.id for d in picked}) == 30
    assert sum(d.source == "mistral-blog" for d in picked) == 15
    assert picked == select(docs, random.Random(1))

    few_news = select(_docs(lab=40, news=5), random.Random(1))
    assert len(few_news) == 30 and sum(d.source == "the-verge" for d in few_news) == 5
    assert len(select(_docs(lab=3, news=4), random.Random(1))) == 7


def test_anonymize_hides_models_and_key_restores_them() -> None:
    docs = _docs(lab=5, news=5)
    outputs = {(d.id, m): Output(SUMMARY) for d in docs for m in MODELS}
    outputs[(docs[0].id, "m/two")] = Output(error="ValidationFailed")

    rows, key = anonymize(docs, outputs, MODELS, random.Random(7))

    assert len(rows) == 30
    assert not any(m in cell for row in rows for cell in row for m in MODELS)
    for doc in docs:
        assert sorted(key[str(doc.id)].values()) == sorted(MODELS)
        assert [r[3] for r in rows if r[0] == str(doc.id)] == ["A", "B", "C"]
    failed = next(r for r in rows if r[8] == "ValidationFailed")
    assert key[failed[0]][failed[3]] == "m/two" and failed[4] == ""
    # Mapiranje se menja po dokumentu, pa slovo ne otkriva model.
    assert len({tuple(v.values()) for v in key.values()}) > 1
    assert {r[9] + r[10] + r[11] for r in rows} == {""}  # ocene upisuje samo vlasnik


def test_write_csv_round_trips(tmp_path: Path) -> None:
    rows, _ = anonymize(_docs(1, 0), {(0, m): Output(SUMMARY) for m in MODELS}, MODELS,
                        random.Random(0))
    write_csv(tmp_path / "b.csv", rows)
    with (tmp_path / "b.csv").open(encoding="utf-8") as handle:
        read = list(csv.reader(handle))
    assert read[0] == HEADER and read[1:] == rows
    assert read[1][7] == "GPT-5; Le Chonk"


def test_plain_text_strips_html_and_truncates() -> None:
    assert plain_text("Naslov", "<p>Prvi &amp; <b>drugi</b></p>") == "Naslov\n\nPrvi & drugi"
    assert len(plain_text("t", "x" * 20000)) == 8000
