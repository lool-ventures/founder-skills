"""market-sizing names the founder's documents as the founder named them.

On the cloud-lane Cowork session every attachment is stored as `<8-hex>-<original name>`, and a
page citation read "from a1b2c3d4-market-study.pdf, page 1". `_upload_names.py` renames
at render time only; the coaching payload keeps the raw names, and these tests pin that as a
positive fact rather than an absence.
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
    """The payload builder is not touched: it is built from the artifacts, so the coach still sees
    the raw names. Whole-payload equality, not one field, so any path into it is covered."""
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
