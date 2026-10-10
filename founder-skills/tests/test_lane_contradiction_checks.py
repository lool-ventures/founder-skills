"""The contradiction lane's checks, run against hand-built artifacts.

Free: nothing here calls the model. The paid lane (`test_e2e_deck_review.py`, opt-in) evaluates its
golden file's assertions after a live run; an assertion whose code is wrong reds or greens that run for
the wrong reason, at the price of a run. Here the same check function reads artifacts written by hand,
once where every assertion should hold and once where each should fail. Invented figures.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent


@pytest.fixture
def deck_lane() -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location("_contra_test_e2e_deck_review", TESTS / "test_e2e_deck_review.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _review_dir(tmp_path: Path, *, scored_by: str | None, status: str) -> Path:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    rendered = "433 × $87 = $37,671 — but the deck states $23.9K (MRR)"
    recon = {
        "status": "checked",
        "relations": [
            {"verdict": "contradiction", "rendered": rendered, "computed": 37_671.0, "expected_value": 23_900.0}
        ],
        "suppressed": {},
    }
    (review_dir / "reconciliation.json").write_text(json.dumps(recon), encoding="utf-8")
    item: dict[str, Any] = {"id": "numbers_consistent", "status": status}
    if scored_by:
        item["scored_by"] = scored_by
    (review_dir / "checklist.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    md = "## What Your Numbers Say About Each Other\n\n- " + rendered + "\n"
    (review_dir / "report.md").write_text(md, encoding="utf-8")
    return review_dir


def _failures(deck_lane: Any, review_dir: Path, findings: list[dict[str, str]]) -> list[str]:
    assertions = json.loads(deck_lane.CONTRADICTION_GOLDEN.read_text(encoding="utf-8"))["assertions"]
    failures: list[str] = []
    report = {"coaching_payload": {"numeric_findings": findings}}
    deck_lane._check_contradictions(
        review_dir=review_dir, report=report, assertions=assertions, observed={}, failures=failures
    )
    return failures


def test_the_golden_asks_for_the_scored_criterion_and_the_payload(deck_lane: Any) -> None:
    assertions = json.loads(deck_lane.CONTRADICTION_GOLDEN.read_text(encoding="utf-8"))["assertions"]
    assert assertions["numbers_consistent_status"] == "fail"
    assert assertions["numeric_findings_min"] == 1


def test_a_scored_fail_with_findings_passes_every_check(deck_lane: Any, tmp_path: Path) -> None:
    review_dir = _review_dir(tmp_path, scored_by="arithmetic", status="fail")
    assert _failures(deck_lane, review_dir, [{"label": "Figures that disagree", "line": "x"}]) == []


def test_an_unscored_criterion_and_an_empty_payload_each_fail(deck_lane: Any, tmp_path: Path) -> None:
    review_dir = _review_dir(tmp_path, scored_by=None, status="pass")
    failures = _failures(deck_lane, review_dir, [])
    assert any("without --reconciliation" in f for f in failures), failures
    assert any("expected 'fail'" in f for f in failures), failures
    assert any("numeric_findings has 0" in f for f in failures), failures
