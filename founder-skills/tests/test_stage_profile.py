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
    "stage_profile.py",
)


def _run(args: list[str], stdin_data: str) -> tuple[int, str, str]:
    res = subprocess.run([sys.executable, SCRIPT, *args], input=stdin_data, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


_VALID = {
    "detected_stage": "seed",
    "confidence": "high",
    "evidence": ["Claims $2M ARR", "500 customers"],
    "is_ai_company": False,
    "expected_framework": [
        "purpose_traction",
        "problem",
        "solution_product",
        "traction_kpis",
        "market",
        "competition",
        "business_model_pricing",
        "gtm",
        "unit_economics",
        "team",
        "financials",
        "ask_milestones",
    ],
    "stage_benchmarks": {
        "round_size_range": "$2M-$6M",
        "expected_traction": "$300K-$500K ARR",
        "runway_expectation": "18-24 months",
    },
    "reference_file_read": ["deck-best-practices.md", "checklist-criteria.md", "artifact-schemas.md"],
}


def test_stage_profile_writes_validated_artifact() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--pretty"], json.dumps(_VALID))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert written["detected_stage"] == "seed"


def test_stage_profile_rejects_unknown_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        bad = {**_VALID, "detected_stage": "pre_seed_v2"}
        rc, _, err = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "detected_stage" in err and "enum" in err.lower()


def test_stage_profile_rebuild_mode_replaces_framework_and_benchmarks() -> None:
    """When --rebuild-stage is passed, framework/benchmarks come from the script's table, overriding stdin."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        # Stdin has SEED data; we ask for series_a rebuild
        rc, _, err = _run(
            ["--run-id", "r1", "-o", out, "--rebuild-stage", "series_a"],
            json.dumps(_VALID),
        )
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["detected_stage"] == "series_a"
        # Framework should now contain series_a-specific slides
        assert "cohort_data" in written["expected_framework"] or "ltv_cac" in str(written["expected_framework"])
        # Founder-correction note added to evidence
        assert any("Founder corrected stage" in e for e in written["evidence"])
        # confidence should be high (founder confirmed)
        assert written["confidence"] == "high"


def test_stage_profile_rebuild_default_confidence_is_high() -> None:
    """--rebuild-stage without --confidence defaults to high (founder picked a different stage)."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        rc, _, err = _run(["--run-id", "r1", "-o", out, "--rebuild-stage", "series_a"], json.dumps(_VALID))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["confidence"] == "high"


def test_stage_profile_rebuild_low_confidence_for_unsure_founder() -> None:
    """--rebuild-stage <detected> --confidence low records low confidence + an 'unsure' evidence line."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        # Founder unsure: rebuild to the SAME (detected) stage at low confidence.
        rc, _, err = _run(
            ["--run-id", "r1", "-o", out, "--rebuild-stage", "seed", "--confidence", "low"],
            json.dumps(_VALID),
        )
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["detected_stage"] == "seed"
        assert written["confidence"] == "low"
        assert any("unsure" in e.lower() for e in written["evidence"])


def test_stage_profile_rebuild_low_confidence_best_effort_different_stage() -> None:
    """--rebuild-stage <other> --confidence low (best-effort) records low confidence + correction note."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        rc, _, err = _run(
            ["--run-id", "r1", "-o", out, "--rebuild-stage", "series_a", "--confidence", "low"],
            json.dumps(_VALID),
        )
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["confidence"] == "low"
        assert any("Founder corrected stage" in e for e in written["evidence"])


def test_stage_profile_rebuild_to_out_of_scope_stage_keeps_stub_benchmarks() -> None:
    """series_b/growth: detected_stage set, but framework/benchmarks not synthesized."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "stage_profile.json")
        rc, _, err = _run(
            ["--run-id", "r1", "-o", out, "--rebuild-stage", "growth"],
            json.dumps(_VALID),
        )
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["detected_stage"] == "growth"
        # Stub benchmarks still satisfy schema (required object with required string fields)
        assert "round_size_range" in written["stage_benchmarks"]
