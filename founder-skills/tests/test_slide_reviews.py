from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

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
