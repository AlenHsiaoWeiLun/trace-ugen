import json
from pathlib import Path

from traceai.ask import Asker, retrieve

RUN = json.loads((Path(__file__).resolve().parent.parent / "data/run_metro.json").read_text())
ZONES = {z["id"]: z["name"] for z in RUN["site"]["zones"]}


def test_zone_phrase_selects_that_zone():
    hits = retrieve("What happened on Platform 1?", RUN["incidents"], ZONES)
    assert hits and all(any(s["zone"] == "D" for s in sigs) for _, sigs in hits)


def test_transcript_words_are_searchable():
    hits = retrieve("was anyone injured?", RUN["incidents"], ZONES)
    assert any(s["source"] == "radio" for _, sigs in hits for s in sigs)


def test_citations_are_real_ids_without_llm():
    out = Asker().ask("anything near exit C?", RUN["incidents"], ZONES)
    known = {i["id"] for i in RUN["incidents"]} | {s["id"] for i in RUN["incidents"] for s in i["signals"]}
    assert out["citations"] and set(out["citations"]) <= known
