"""Unit tests for verify_one.py — the single-question cited rule-pack lookup.

Guards the allowlist-by-data invariant: a rule is answered ONLY when it carries
a recognized structured constant; rules without one (e.g. the Section 102
capital-gains holding clock) escalate instead of echoing a non-constant field
(like grant_date) as the answer.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "cap-table" / "scripts" / "verify_one.py"
RULES = REPO / "skills" / "cap-table" / "data" / "cap-table-rules.json"


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("verify_one", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VO = _load_module()
PACK = json.loads(RULES.read_text(encoding="utf-8"))


# --- real-rule behavior against the shipped rule pack ---


def test_qsbs_answers_with_structured_constant() -> None:
    r = VO.lookup(PACK, "delaware_cross_border.qsbs_date_sensitive")
    assert r["lookup_status"] == "answered"
    assert r["constant"]["value"] == "2025-07-05"
    assert r["counsel_review"] is True
    assert r["citations"], "expected at least one resolved citation"
    assert "2025-07-05" in r["answer"]


def test_section_102_escalates_and_never_echoes_grant_date() -> None:
    r = VO.lookup(PACK, "israel_equity_tax.section_102_capital_gains")
    assert r["lookup_status"] == "escalate"
    assert r["constant"] is None
    # the whole point: do NOT surface grant_date as "the fact"
    assert "grant_date" not in r["answer"]
    assert r["counsel_review"] is True
    assert r["escalation_reason"]


def test_unknown_rule_is_not_found() -> None:
    r = VO.lookup(PACK, "does.not.exist")
    assert r["lookup_status"] == "not_found"


# --- extract_constant: the allowlist-by-data core ---


def test_extract_constant_recognizes_date_window_start() -> None:
    rule = {"date_window": {"start": "2025-07-05", "event_date_field": "stock_issue_date"}}
    const = VO.extract_constant(rule)
    assert const and const["value"] == "2025-07-05"
    assert const["keyed_on"] == "stock_issue_date"


def test_extract_constant_rejects_event_field_only_window() -> None:
    # the §102 shape: a date_window with NO start → no constant → escalate
    rule = {"date_window": {"event_date_field": "grant_date", "notes": "..."}}
    assert VO.extract_constant(rule) is None


def test_extract_constant_rejects_missing_window() -> None:
    assert VO.extract_constant({"summary": "no dates here"}) is None


# --- citation resolution ---


def test_resolve_citations_maps_source_ids() -> None:
    pack = {
        "source_bibliography": [
            {"source_id": "SRC-A", "title": "Title A", "publisher": "Pub", "url": "http://a"},
        ]
    }
    rule = {"source_ids": ["SRC-A", "SRC-MISSING"]}
    cites = VO.resolve_citations(pack, rule)
    assert cites[0]["title"] == "Title A"
    # an unresolved id still appears, with null fields (never silently dropped)
    assert cites[1]["source_id"] == "SRC-MISSING"
    assert cites[1]["title"] is None
