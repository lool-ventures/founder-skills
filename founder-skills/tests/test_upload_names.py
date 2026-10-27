"""market-sizing names the founder's documents as the founder named them.

On the cloud-lane Cowork session every attachment is stored as `<8-hex>-<original name>`, and a
page citation read "from a1b2c3d4-market-study.pdf, page 1". `_upload_names.py` renames at
render time, and `red_team.py` maps the review's prose once when it is piped (tests at the end).
The payload builder is not touched: built from a hand-written review, it carries the names that
review carries, and these tests pin that as a positive fact rather than an absence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_market_sizing import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_METHODOLOGY,
    _VALID_SENSITIVITY,
    _VALID_SIZING,
    _VALID_VALIDATION,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"_upload_names_test_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


names = _load("_upload_names")

DECK = "a1b2c3d4-deck.pdf"
QA = "e5f6a7b8-Founder's Q&A.pdf"  # an apostrophe and an ampersand: HTML escaping must not hide it
NOTES = "c9d0e1f2-notes.md"
PREFIXES = ("a1b2c3d4-", "e5f6a7b8-", "c9d0e1f2-")

REDTEAM: dict[str, Any] = {
    "findings": [
        {
            "claim_attacked": "segment_pct",
            "what_is_true": f"The deck says 6.1%; see {QA} for the payer split.",
            "evidence_quote": "Six point one percent of employers offered the benefit.",
            "source_url": f"document:{DECK}#page=3",
            "source_title": "",
            "severity": "high",
            "quote_verified": True,
        },
        {
            "claim_attacked": "arpu",
            "what_is_true": "The price is monthly.",
            "evidence_quote": "Billed monthly.",
            "source_url": f"document:{QA}#page=2",
            "source_title": "",
            "severity": "medium",
            "quote_verified": True,
        },
    ],
    "rejected": [],
    "could_not_check": [f"{DECK} page 5, because the machine read recovered only the axis labels"],
    "sources_read": [DECK, QA],
    "sources_unread": [NOTES],
    "summary": {"accepted": 2, "rejected": 0, "unchecked": 1, "by_severity": {"high": 1, "medium": 1, "low": 0}},
    "validation": {"status": "valid", "errors": []},
}


def _dir(tmp_path: Path, redteam: dict[str, Any]) -> str:
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
        "redteam.json": redteam,
    }
    for fname, data in arts.items():
        (tmp_path / fname).write_text(json.dumps(data), encoding="utf-8")
    return str(tmp_path)


# --- the rule ------------------------------------------------------------------------------------


def test_a_platform_prefixed_batch_is_renamed() -> None:
    assert names.display_map([DECK, QA]) == {DECK: "deck.pdf", QA: "Founder's Q&A.pdf"}


def test_an_all_digit_prefix_in_a_prefixed_batch_is_the_platforms() -> None:
    assert names.display_map(["12345678-a.pdf", DECK]) == {"12345678-a.pdf": "a.pdf", DECK: "deck.pdf"}


def test_a_single_date_named_file_is_left_alone() -> None:
    assert names.display_map(["20240115-deck.pdf"]) == {}
    assert names.display_map(["deadbeef-deck.pdf"]) == {"deadbeef-deck.pdf": "deck.pdf"}


def test_one_unprefixed_name_means_the_batch_is_the_founders_own_naming() -> None:
    assert names.display_map(["deadbeef-notes.pdf", "deck.pdf"]) == {}


def test_a_collision_keeps_both_prefixes() -> None:
    """Two uploads of deck.pdf: the prefix is then the only thing saying which one is meant."""
    assert names.display_map(["a1b2c3d4-deck.pdf", "b2c3d4e5-deck.pdf", QA]) == {QA: "Founder's Q&A.pdf"}


def test_free_text_is_rewritten_only_where_a_known_name_appears() -> None:
    m = names.display_map([DECK])
    assert (
        names.humanize(f"see {DECK}, and token deadbeef-other.pdf", m) == "see deck.pdf, and token deadbeef-other.pdf"
    )


def test_known_names_come_from_read_unread_and_citations() -> None:
    assert set(names.known_names(REDTEAM)) == {DECK, QA, NOTES}
    assert names.known_names(None) == [] and names.known_names("corrupt") == []


# --- the renderers -------------------------------------------------------------------------------


def _compose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, rename: bool) -> dict[str, Any]:
    compose = _load("compose_report")
    if not rename:
        monkeypatch.setattr(compose._upload_names, "for_redteam", lambda _rt: {})
    result: dict[str, Any] = compose.compose(_dir(tmp_path, REDTEAM))
    return result


def test_fixture_carries_the_prefixes_it_tests() -> None:
    """Precondition: a test whose input never carried a prefix passes for the wrong reason."""
    blob = json.dumps(REDTEAM)
    assert all(p in blob for p in PREFIXES)


def test_report_md_and_verdict_name_documents_as_uploaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "new").mkdir()
    raw = _compose(tmp_path / "raw", monkeypatch, rename=False)
    monkeypatch.undo()
    out = _compose(tmp_path / "new", monkeypatch, rename=True)
    # Anchor: without the renaming, every site this test reads carries a prefix.
    assert DECK in raw["verdict"] and DECK in raw["report_markdown"] and NOTES in raw["report_markdown"]
    assert "e5f6a7b8-Founder's Q&A.pdf" in raw["report_markdown"]
    for text in (out["verdict"], out["report_markdown"]):
        assert not any(p in text for p in PREFIXES), text
    assert "deck.pdf, page 3" in out["verdict"]
    md = out["report_markdown"]
    assert "— deck.pdf, page 3" in md and "Founder's Q&A.pdf, page 2" in md
    assert "- deck.pdf page 5, because" in md  # the red team's own "not checked" prose
    assert "notes.md" in md  # sources_unread, in the outcome line and the warning


def test_coaching_payload_and_warnings_are_unchanged_by_the_renaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The render-time renaming does not reach the payload: it is built from the artifacts, so it
    carries what the review carries. Whole-payload equality, not one field, so any path into it is
    covered. (A review piped by red_team.py already carries the uploaded names in its prose.)"""
    (tmp_path / "raw").mkdir()
    (tmp_path / "new").mkdir()
    raw = _compose(tmp_path / "raw", monkeypatch, rename=False)
    monkeypatch.undo()
    out = _compose(tmp_path / "new", monkeypatch, rename=True)
    volatile = ("insertion_marker", "review_dir", "report_path")
    strip = lambda p: {k: v for k, v in p.items() if k not in volatile}  # noqa: E731
    assert strip(out["coaching_payload"]) == strip(raw["coaching_payload"])
    assert out["validation"]["warnings"] == raw["validation"]["warnings"]
    assert f"document:{DECK}#page=3" in json.dumps(out["coaching_payload"])  # raw, as a positive fact


def test_report_html_names_documents_as_uploaded(tmp_path: Path) -> None:
    viz = _load("visualize")
    page = viz.compose_html(_dir(tmp_path, REDTEAM))
    assert not any(p in page for p in PREFIXES), [p for p in PREFIXES if p in page]
    assert "deck.pdf, page 3" in page
    assert "Founder&#x27;s Q&amp;A.pdf, page 2" in page
    assert "deck.pdf page 5, because" in page


def test_report_html_anchor_carries_the_prefix_without_renaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    viz = _load("visualize")
    monkeypatch.setattr(viz._upload_names, "for_redteam", lambda _rt: {})
    page = viz.compose_html(_dir(tmp_path, REDTEAM))
    assert DECK in page and "e5f6a7b8-Founder&#x27;s Q&amp;A.pdf" in page


# --- the review's prose, when it is piped ----------------------------------------------------------
# The policy's substitute rewords the prose at pipe time and rewrites a word inside a prefixed name
# (`pitch_deck` -> `pitch deck`), which no renderer can match afterwards. So red_team.py maps the
# stored names to the uploaded ones first; citations, quotes and source lists keep the stored names.

SNAKE = "85451e6d-pitch_deck (1).pdf"  # snake_case and a space: the case the render-time map cannot reach
STUDY = "a3b2c1d0-market_study.md"
STUDY_TEXT = "Our study counts nine hundred regional freight brokers operating in the region today."
LINK = "https://files.example.com/85451e6d-pitch_deck"


# What red_team.py stored for this unprefixed batch before the pipe-time mapping existed (checked
# against the earlier script): the mapping must not change a byte of it. The summary's counts do not
# depend on names, so the test takes them from the same review piped under prefixed names.
UNPREFIXED_EXPECTED: dict[str, Any] = {
    "findings": [
        {
            "claim_attacked": "The SAM assumes every broker buys",
            "what_is_true": (
                "Your own study, market_study.md, counts brokers; pitch deck (1).pdf does not, nor does the sizing"
                " calculation. See https://files.example.com/85451e6d-pitch_deck"
            ),
            "evidence_quote": "counts nine hundred regional freight brokers operating in the region",
            "source_url": "document:market_study.md",
            "source_title": "pitch deck (1).pdf",
            "severity": "medium",
            "quote_verified": True,
        }
    ],
    "rejected": [],
    "could_not_check": ["pitch deck (1).pdf page 2, a chart only"],
    "sources_read": ["market_study.md"],
    "sources_unread": ["pitch_deck (1).pdf"],
    "validation": {"status": "valid", "errors": []},
    "inputs_reviewed": {"sizing": {}, "record": {}},
}


def _pipe(tmp_path: Path, docs: dict[str, str]) -> dict[str, Any]:
    return _pipe_named(tmp_path, docs, deck=SNAKE, study=STUDY)


def _pipe_named(tmp_path: Path, docs: dict[str, str], *, deck: str, study: str) -> dict[str, Any]:
    import subprocess

    uploads = tmp_path / "docs"
    uploads.mkdir()
    for name, text in docs.items():
        (uploads / name).write_text(text, encoding="utf-8")
    finding = {
        "claim_attacked": "The SAM assumes every broker buys",
        "what_is_true": f"Your own study, {study}, counts brokers; {deck} does not, nor does sizing.json. See {LINK}",
        "evidence_quote": "counts nine hundred regional freight brokers operating in the region",
        "source_url": f"document:{study}",
        "source_title": deck,
        "severity": "medium",
    }
    data = {"findings": [finding], "sources_read": [study], "could_not_check": [f"{deck} page 2, a chart only"]}
    out = tmp_path / "redteam.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "red_team.py"), "--run-id", "20260101T000000Z"]
        + ["--uploads-dir", str(uploads), "-o", str(out)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr[-600:]
    assert deck in json.dumps(data)  # the lever: the input really carries the name under test
    result: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return result


def test_the_stored_review_names_uploads_as_uploaded_but_keeps_its_citations(tmp_path: Path) -> None:
    rt = _pipe(tmp_path, {SNAKE: "deck", STUDY: STUDY_TEXT})
    f = rt["findings"][0]
    prose = f["what_is_true"] + f["source_title"] + f["claim_attacked"] + " ".join(rt["could_not_check"])
    assert "85451e6d-pitch" not in prose.replace(LINK, "") and "a3b2c1d0" not in prose
    assert "pitch deck (1).pdf does not" in f["what_is_true"] and f["source_title"] == "pitch deck (1).pdf"
    assert rt["could_not_check"] == ["pitch deck (1).pdf page 2, a chart only"]
    assert LINK in f["what_is_true"]  # a link is the link
    assert "the sizing calculation" in f["what_is_true"]  # our own file is still reworded
    assert f["source_url"] == f"document:{STUDY}" and rt["sources_read"] == [STUDY]
    assert f["evidence_quote"] == "counts nine hundred regional freight brokers operating in the region"


def test_an_upload_named_like_our_file_does_not_shield_our_mention_of_it(tmp_path: Path) -> None:
    ours = "b1c2d3e4-sizing.json"
    rt = _pipe(tmp_path, {SNAKE: "deck", STUDY: STUDY_TEXT, ours: "{}"})
    text = rt["findings"][0]["what_is_true"]
    assert "nor does the sizing calculation" in text, text


def test_a_batch_with_one_unprefixed_upload_keeps_every_prefix(tmp_path: Path) -> None:
    docs = {SNAKE: "deck", STUDY: STUDY_TEXT, "notes.pdf": "notes"}
    assert names.display_map(list(docs)) == {}  # the mapping does not engage
    rt = _pipe(tmp_path, docs)
    assert f"Your own study, {STUDY}, counts brokers" in rt["findings"][0]["what_is_true"]
    assert rt["findings"][0]["source_title"] == "85451e6d-pitch deck (1).pdf"  # as before this change


def test_a_piped_review_reaches_both_pages_and_the_payload_as_uploaded(tmp_path: Path) -> None:
    rt = _pipe(tmp_path, {SNAKE: "deck", STUDY: STUDY_TEXT})
    redteam = {k: v for k, v in rt.items() if k != "metadata"}
    (tmp_path / "run").mkdir()
    d = _dir(tmp_path / "run", redteam)
    out = _load("compose_report").compose(d)
    page = _load("visualize").compose_html(d)
    for name, text in (("report.md", out["report_markdown"]), ("report.html", page)):
        assert "85451e6d" not in text.replace(LINK, "") and "a3b2c1d0" not in text, name
        assert "pitch deck (1).pdf does not" in text, name
    payload = json.dumps(out["coaching_payload"])
    assert "pitch deck (1).pdf does not" in payload and "85451e6d-pitch deck" not in payload
    assert f"document:{STUDY}" in payload  # the citation keeps the stored name


def test_an_unprefixed_batch_is_stored_exactly_as_before(tmp_path: Path) -> None:
    """The local lanes: no upload carries a prefix, so the review is stored as it always was."""
    plain = {"pitch_deck (1).pdf": "deck", "market_study.md": STUDY_TEXT}
    assert names.display_map(list(plain)) == {}
    (tmp_path / "plain").mkdir()
    (tmp_path / "cloud").mkdir()
    rt = _pipe_named(tmp_path / "plain", plain, deck="pitch_deck (1).pdf", study="market_study.md")
    counts = _pipe(tmp_path / "cloud", {SNAKE: "deck", STUDY: STUDY_TEXT})["summary"]
    assert rt.pop("summary") == counts and counts["accepted"] == 1
    assert {k: v for k, v in rt.items() if k != "metadata"} == UNPREFIXED_EXPECTED
