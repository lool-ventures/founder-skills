from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
    "slide_reviews.py",
)


def _run(args: list[str], stdin_data: str) -> tuple[int, str, str]:
    res = subprocess.run([sys.executable, SCRIPT, *args], input=stdin_data, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


_VALID = {
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["No ICP specificity"],
            "recommendations": ["Add ICP"],
            "best_practice_refs": ["Sequoia: declarative sentence"],
        }
    ],
    "missing_slides": [{"expected_type": "why_now", "importance": "important", "recommendation": "Add why-now"}],
    "overall_narrative_assessment": "Strong opening, weak middle.",
}

_RECONCILIATION = {
    "metadata": {"run_id": "r1"},
    "status": "checked",
    "figures_total": 0,
    "figures_verified": 0,
    "relations": [],
    "validation": {"status": "valid", "errors": [], "warnings": []},
}


def _write_reconciliation(dir_path: str, *, run_id: str = "r1", body: dict | None = None) -> str:
    path = os.path.join(dir_path, "reconciliation.json")
    data = json.loads(json.dumps(_RECONCILIATION)) if body is None else body
    if body is None:
        data["metadata"]["run_id"] = run_id
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def test_slide_reviews_writes_validated_artifact() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = _write_reconciliation(d)
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec, "--pretty"], json.dumps(_VALID))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert len(written["reviews"]) == 1


def test_slide_reviews_rejects_invalid_importance() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = _write_reconciliation(d)
        bad = json.loads(json.dumps(_VALID))
        bad["missing_slides"][0]["importance"] = "very_critical"
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(bad))
        assert rc != 0
        assert "importance" in err


def test_slide_reviews_rejects_review_missing_recommendations() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = _write_reconciliation(d)
        bad = json.loads(json.dumps(_VALID))
        del bad["reviews"][0]["recommendations"]
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(bad))
        assert rc != 0
        assert "recommendations" in err


# ---------------------------------------------------------------------------
# The reconciliation gate.
#
# This is the mechanism that makes the numeric chain unskippable, and it exists
# because the obvious alternative was measured NOT to work: a missing required
# artifact raises MISSING_ARTIFACT in compose and compose still exits 0 with a
# complete report. A step whose only consequence is a warning gets skipped in
# silence. So the gate sits on the producer of the deliverable instead, and these
# four tests are what keep it load-bearing.
# ---------------------------------------------------------------------------


def test_gate_blocks_when_reconciliation_absent() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        missing = os.path.join(d, "reconciliation.json")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", missing], json.dumps(_VALID))
        assert rc != 0
        assert "not found" in err
        assert not os.path.exists(out), "the deliverable must not be written when the gate fails"


def test_gate_blocks_on_foreign_run_id() -> None:
    """A stale artifact from an earlier review of the same company must not satisfy it.

    Presence alone is not enough: in Cowork the cleanup delete that would remove a prior
    run's file is denied and deliberately tolerated, so a skipped chain would otherwise
    sail past an existence check.
    """
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = _write_reconciliation(d, run_id="an-earlier-run")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(_VALID))
        assert rc != 0
        assert "earlier" in err or "not 'r1'" in err
        assert not os.path.exists(out)


def test_gate_blocks_on_unparseable_reconciliation() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = os.path.join(d, "reconciliation.json")
        with open(rec, "w", encoding="utf-8") as f:
            f.write("{not json")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(_VALID))
        assert rc != 0
        assert "unreadable" in err
        assert not os.path.exists(out)


def test_gate_blocks_when_status_is_absent() -> None:
    """A well-formed file that never ran the chain is still a skipped chain."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rec = _write_reconciliation(d, body={"metadata": {"run_id": "r1"}})
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(_VALID))
        assert rc != 0
        assert "status" in err
        assert not os.path.exists(out)


def test_gate_accepts_no_figures_status() -> None:
    """A deck with nothing to reconcile is a legitimate outcome, not a gate failure."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        body = json.loads(json.dumps(_RECONCILIATION))
        body["status"] = "no_figures"
        rec = _write_reconciliation(d, body=body)
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(_VALID))
        assert rc == 0, err
        assert os.path.exists(out)


# ---------------------------------------------------------------------------
# The numeric lint (warn-only).
#
# A slide review that says two figures disagree is checked against the arithmetic: backed when one of
# its numerals is in the rendered line of a surviving contradiction / exceeds_stated_limit /
# rounding_gap, unbacked otherwise. It never fails the step and never changes the artifact -- the
# vocabulary is an enumerated list, porous both ways, and unbacked hits include real findings -- so
# what these tests pin is the measurement (receipt + stderr) and that nothing else moves.
# All figures below are invented.
# ---------------------------------------------------------------------------


def _load_module() -> ModuleType:
    scripts = os.path.dirname(SCRIPT)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("dr_slide_reviews_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reviews_with_weakness(text: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(json.dumps(_VALID))
    data["reviews"][0]["weaknesses"] = [text]
    return data


_UNBACKED_LINE = "Gross margin of 47% is inconsistent with the 31% the unit-economics slide shows."
_BACKED_LINE = "The stated 11% take rate does not match $730K of revenue on $9.7M of volume."
_BACKING_RELATION = {
    "verdict": "contradiction",
    "rendered": "$730K ÷ $9.7M = 7.5%  — but the deck states 11% (Take rate)",
}


def test_lint_flags_a_disagreement_the_arithmetic_did_not_find() -> None:
    mod = _load_module()
    hits = mod.numeric_lint(_reviews_with_weakness(_UNBACKED_LINE), _RECONCILIATION)
    assert hits == [{"where": "slide 1 weaknesses[0]", "phrase": "inconsistent", "backed": False}]


def test_lint_backs_a_disagreement_the_arithmetic_found() -> None:
    mod = _load_module()
    recon = dict(_RECONCILIATION, relations=[_BACKING_RELATION])
    hits = mod.numeric_lint(_reviews_with_weakness(_BACKED_LINE), recon)
    assert [h["backed"] for h in hits] == [True]


def test_lint_backing_needs_a_verdict_that_reaches_the_founder() -> None:
    """A confirmation, a withdrawn contradiction or a derived figure carries the same numerals and backs nothing."""
    mod = _load_module()
    for verdict in ("confirmation", "downgraded", "derived"):
        recon = dict(_RECONCILIATION, relations=[dict(_BACKING_RELATION, verdict=verdict)])
        hits = mod.numeric_lint(_reviews_with_weakness(_BACKED_LINE), recon)
        assert [h["backed"] for h in hits] == [False], verdict


def test_lint_slide_references_are_not_figures() -> None:
    """Two slide numbers are not two stated figures; the same sentence with figures is a hit."""
    mod = _load_module()
    refs_only = "Slide 3 and slide 9 contradict each other on when the hiring plan starts."
    assert mod.numeric_lint(_reviews_with_weakness(refs_only), _RECONCILIATION) == []
    with_figures = "Slides 3 and 9 contradict each other: 14 hires on one, 22 on the other."
    assert len(mod.numeric_lint(_reviews_with_weakness(with_figures), _RECONCILIATION)) == 1


def test_lint_needs_the_vocabulary_and_two_figures() -> None:
    mod = _load_module()
    no_verb = "Revenue grew from $310K to $590K, a strong year."
    one_figure = "The 47% margin is inconsistent with the narrative."
    for text in (no_verb, one_figure):
        assert mod.numeric_lint(_reviews_with_weakness(text), _RECONCILIATION) == [], text


def test_lint_is_warn_only_receipt_and_stderr() -> None:
    """Exit 0, the artifact is the input plus metadata, the receipt carries the count."""
    with tempfile.TemporaryDirectory() as d:
        rec = _write_reconciliation(d)
        payload = _reviews_with_weakness(_UNBACKED_LINE)
        out = os.path.join(d, "slide_reviews.json")
        rc, stdout, err = _run(["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(payload))
        assert rc == 0, err
        receipt = json.loads(stdout)
        assert receipt["numeric_lint"] == {"hits": 1, "unbacked": 1}
        assert "numeric_lint" in err and "slide 1 weaknesses[0]" in err
        # The reviewer's sentence is not echoed: stderr names where, not what.
        assert "47%" not in err
        with open(out, encoding="utf-8") as fh:
            written = json.load(fh)
        assert written == dict(payload, metadata={"run_id": "r1"})


def test_lint_backed_hit_prints_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        body = json.loads(json.dumps(_RECONCILIATION))
        body["relations"] = [_BACKING_RELATION]
        rec = _write_reconciliation(d, body=body)
        out = os.path.join(d, "slide_reviews.json")
        rc, stdout, err = _run(
            ["--run-id", "r1", "-o", out, "--reconciliation", rec], json.dumps(_reviews_with_weakness(_BACKED_LINE))
        )
        assert rc == 0, err
        assert json.loads(stdout)["numeric_lint"] == {"hits": 1, "unbacked": 0}
        assert "numeric_lint" not in err
