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


def test_slide_reviews_writes_validated_artifact() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--pretty"], json.dumps(_VALID))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert len(written["reviews"]) == 1


def test_slide_reviews_rejects_invalid_importance() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        bad = json.loads(json.dumps(_VALID))
        bad["missing_slides"][0]["importance"] = "very_critical"
        rc, _, err = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "importance" in err


def test_slide_reviews_rejects_review_missing_recommendations() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "slide_reviews.json")
        bad = json.loads(json.dumps(_VALID))
        del bad["reviews"][0]["recommendations"]
        rc, _, err = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "recommendations" in err
