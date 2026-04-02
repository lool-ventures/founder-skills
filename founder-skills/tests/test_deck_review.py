#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for deck review scripts.

Run: pytest founder-skills/tests/test_deck_review.py -v
All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECK_REVIEW_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts")


def run_script(name: str, args: list[str] | None = None, stdin_data: str | None = None) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(DECK_REVIEW_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def run_script_raw(name: str, args: list[str] | None = None, stdin_data: str | None = None) -> tuple[int, str, str]:
    """Like run_script but returns (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(DECK_REVIEW_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# -- All 35 canonical checklist IDs --

_CHECKLIST_IDS = [
    # Narrative Flow
    "purpose_clear",
    "headlines_carry_story",
    "narrative_arc_present",
    "strongest_proof_early",
    "story_stands_alone",
    # Slide Content
    "problem_quantified",
    "solution_shows_workflow",
    "why_now_has_catalyst",
    "market_bottom_up",
    "competition_honest",
    "business_model_clear",
    "gtm_has_proof",
    "team_has_depth",
    # Stage Fit
    "stage_appropriate_structure",
    "stage_appropriate_traction",
    "stage_appropriate_financials",
    "ask_ties_to_milestones",
    "round_size_realistic",
    # Design & Readability
    "one_idea_per_slide",
    "minimal_text",
    "slide_count_appropriate",
    "consistent_design",
    "mobile_readable",
    # Common Mistakes
    "no_vague_purpose",
    "no_nice_to_have_problem",
    "no_hype_without_proof",
    "no_features_over_outcomes",
    "no_dodged_competition",
    # AI Company
    "ai_retention_rebased",
    "ai_cost_to_serve_shown",
    "ai_defensibility_beyond_model",
    "ai_responsible_controls",
    # Diligence Readiness
    "numbers_consistent",
    "data_room_ready",
    "contact_info_present",
]


def _make_checklist_items(
    overrides: dict[str, dict] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Build a 35-item checklist payload."""
    overrides = overrides or {}
    exclude = exclude or []
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in exclude:
            continue
        if cid in overrides:
            items.append({"id": cid, **overrides[cid]})
        else:
            items.append({"id": cid, "status": "pass", "evidence": "test", "notes": None})
    return items


# -- Checklist tests --


def test_checklist_all_pass() -> None:
    """All 35 items pass."""
    payload = json.dumps({"items": _make_checklist_items()})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["total"] == 35
    assert s["pass"] == 35
    assert s["fail"] == 0
    assert s["warn"] == 0
    assert s["score_pct"] == 100.0
    assert s["overall_status"] == "strong"
    assert len(s["failed_items"]) == 0
    assert len(s["warned_items"]) == 0


def test_checklist_score_thresholds() -> None:
    """Test all four overall_status thresholds."""
    # Strong: >=85% -- with 4 AI N/A, 31 applicable, need 27 pass = 87.1%
    ai_na = {
        cid: {"status": "not_applicable", "evidence": "N/A", "notes": "Not AI"}
        for cid in [
            "ai_retention_rebased",
            "ai_cost_to_serve_shown",
            "ai_defensibility_beyond_model",
            "ai_responsible_controls",
        ]
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=ai_na)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "strong"
        assert data["summary"]["score_pct"] == 100.0

    # Needs work: 50-69% -- 15 pass out of 31 applicable = 48.4% -> major_revision
    # Let's do 16 pass = 51.6% -> needs_work
    fail_ids = _CHECKLIST_IDS[5:20]  # 15 items fail
    overrides = dict(ai_na)
    for cid in fail_ids:
        overrides[cid] = {"status": "fail", "evidence": "test", "notes": "test fail"}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "needs_work"

    # Major revision: <50% -- 14 pass out of 31 = 45.2%
    fail_ids_more = _CHECKLIST_IDS[4:21]  # 17 items fail
    overrides2 = dict(ai_na)
    for cid in fail_ids_more:
        overrides2[cid] = {"status": "fail", "evidence": "test", "notes": "test fail"}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides2)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "major_revision"


def test_checklist_warn_status() -> None:
    """Warn items counted correctly and listed in warned_items."""
    overrides = {
        "headlines_carry_story": {"status": "warn", "evidence": "test", "notes": "Mixed headlines"},
        "minimal_text": {"status": "warn", "evidence": "test", "notes": "Some dense slides"},
        "competition_honest": {"status": "fail", "evidence": "test", "notes": "Missing"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["warn"] == 2
    assert s["fail"] == 1
    assert s["pass"] == 32
    warned_ids = {w["id"] for w in s["warned_items"]}
    assert warned_ids == {"headlines_carry_story", "minimal_text"}
    failed_ids = {f["id"] for f in s["failed_items"]}
    assert failed_ids == {"competition_honest"}


def test_checklist_by_category() -> None:
    """by_category counts are correct."""
    overrides = {
        "purpose_clear": {"status": "fail", "evidence": "test", "notes": "Vague"},
        "headlines_carry_story": {"status": "warn", "evidence": "test", "notes": "Mixed"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    cat = data["summary"]["by_category"]
    nf = cat.get("Narrative Flow", {})
    assert nf.get("pass") == 3
    assert nf.get("fail") == 1
    assert nf.get("warn") == 1


def _assert_validation_errors(data: dict | None, *fragments: str) -> None:
    """Assert data has validation.status == 'invalid' and errors contain all fragments."""
    assert data is not None, "expected JSON output with validation errors"
    assert data["validation"]["status"] == "invalid"
    joined = " ".join(data["validation"]["errors"]).lower()
    for frag in fragments:
        assert frag.lower() in joined, f"expected '{frag}' in validation errors: {data['validation']['errors']}"


def test_checklist_missing_items() -> None:
    """Only 32 items -- should produce validation error."""
    items = _make_checklist_items(exclude=["data_room_ready", "contact_info_present", "numbers_consistent"])
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "missing")


def test_checklist_duplicate_id() -> None:
    """36 items with a duplicate -- should produce validation error."""
    items = _make_checklist_items()
    items.append({"id": "purpose_clear", "status": "pass", "evidence": "dup", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "duplicate")


def test_checklist_unknown_id() -> None:
    """Unknown ID -- should produce validation error."""
    items = _make_checklist_items()
    items[0] = {"id": "bogus_criterion", "status": "pass", "evidence": "test", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "unknown")


def test_checklist_invalid_status() -> None:
    """Status 'maybe' -- should produce validation error."""
    overrides = {"purpose_clear": {"status": "maybe", "evidence": "test", "notes": None}}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "invalid")


def test_checklist_non_dict_item() -> None:
    """Non-dict item in checklist items array -> validation error."""
    payload = json.dumps({"items": ["not_a_dict"]})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "must be an object")


def test_checklist_output_flag() -> None:
    """checklist.py with -o writes to file, stdout empty."""
    payload = json.dumps({"items": _make_checklist_items()})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw("checklist.py", ["--pretty", "-o", tmp], stdin_data=payload)
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "summary" in data
        assert len(data["items"]) == 35
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# -- Compose report tests --


def _make_artifact_dir(artifacts: dict[str, dict]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-deck-review-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)
    return d


_VALID_INVENTORY = {
    "company_name": "TestCo",
    "review_date": "2026-02-20",
    "input_format": "pdf",
    "total_slides": 11,
    "claimed_stage": "seed",
    "claimed_raise": "$4M",
    "slides": [
        {
            "number": 1,
            "headline": "TestCo -- Cloud Accounting for SMBs",
            "content_summary": "Company intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
    ],
}

_VALID_PROFILE = {
    "detected_stage": "seed",
    "confidence": "high",
    "evidence": ["Claims $2M ARR", "Raising $4M"],
    "is_ai_company": False,
    "ai_evidence": "No AI mentioned",
    "expected_framework": ["purpose_traction", "problem", "solution"],
    "stage_benchmarks": {
        "round_size_range": "$2M-$6M",
        "expected_traction": "$300K-$500K ARR",
        "runway_expectation": "18-24 months",
    },
    "reference_file_read": ["deck-best-practices.md"],
}

_VALID_REVIEWS = {
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["Could add ICP specificity"],
            "recommendations": ["Add target customer segment"],
            "best_practice_refs": ["Sequoia: single declarative sentence"],
        },
    ],
    "missing_slides": [],
    "overall_narrative_assessment": "Good flow overall.",
}

_VALID_CHECKLIST = {
    "items": [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test", "notes": None}
        for cid in _CHECKLIST_IDS
    ],
    "summary": {
        "total": 35,
        "pass": 35,
        "fail": 0,
        "warn": 0,
        "not_applicable": 0,
        "score_pct": 100.0,
        "overall_status": "strong",
        "by_category": {},
        "failed_items": [],
        "warned_items": [],
    },
}


def _run_compose(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, dict | None, str]:
    """Run compose_report.py with given artifact dir."""
    args = ["--dir", artifact_dir, "--pretty"]
    if extra_args:
        args.extend(extra_args)
    return run_script("compose_report.py", args)


def test_compose_complete_set() -> None:
    """All 4 artifacts valid -> no missing artifacts, report non-empty."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    v = data["validation"]
    assert len(v["artifacts_missing"]) == 0
    assert len(data["report_markdown"]) > 100
    codes = [w["code"] for w in v["warnings"]]
    assert "MISSING_ARTIFACT" not in codes


def test_compose_missing_required() -> None:
    """No checklist.json -> MISSING_ARTIFACT warning."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" in codes


def test_compose_stage_mismatch() -> None:
    """Inventory claims pre_seed, profile detects series_a -> STAGE_MISMATCH."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "pre_seed"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" in codes


def test_compose_slide_count_extreme_low() -> None:
    """3 slides -> SLIDE_COUNT_EXTREME."""
    inventory = dict(_VALID_INVENTORY)
    inventory["total_slides"] = 3
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SLIDE_COUNT_EXTREME" in codes


def test_compose_slide_count_extreme_high() -> None:
    """25 slides -> SLIDE_COUNT_EXTREME."""
    inventory = dict(_VALID_INVENTORY)
    inventory["total_slides"] = 25
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SLIDE_COUNT_EXTREME" in codes


def test_compose_uncited_critique() -> None:
    """Slide review with weaknesses but no best_practice_refs -> UNCITED_CRITIQUE."""
    reviews = {
        "reviews": [
            {
                "slide_number": 1,
                "maps_to": "purpose",
                "strengths": [],
                "weaknesses": ["Purpose is vague"],
                "recommendations": ["Make it clearer"],
                "best_practice_refs": [],
            }
        ],
        "missing_slides": [],
        "overall_narrative_assessment": "Weak.",
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": reviews,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNCITED_CRITIQUE" in codes


def test_compose_ai_criteria_skipped() -> None:
    """AI company detected but all AI criteria not_applicable -> AI_CRITERIA_SKIPPED."""
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = True
    # Checklist with AI items as not_applicable
    ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in ai_ids:
            items.append(
                {
                    "id": cid,
                    "category": "AI",
                    "label": "AI",
                    "status": "not_applicable",
                    "evidence": "N/A",
                    "notes": None,
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 31,
            "fail": 0,
            "warn": 0,
            "not_applicable": 4,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "AI_CRITERIA_SKIPPED" in codes


def test_compose_checklist_critical() -> None:
    """Checklist with 12 failures -> CHECKLIST_FAILURES_CRITICAL."""
    fail_ids = _CHECKLIST_IDS[:12]
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in fail_ids:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "fail",
                    "evidence": "test",
                    "notes": "bad",
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,  # type: ignore[dict-item]
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 23,
            "fail": 12,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 65.7,
            "overall_status": "needs_work",
            "by_category": {},
            "failed_items": [{"id": cid} for cid in fail_ids],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CHECKLIST_FAILURES_CRITICAL" in codes


def test_compose_strict_mode() -> None:
    """Missing artifact + --strict -> exit 1."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    rc, data, _ = _run_compose(d, extra_args=["--strict"])
    assert rc == 1
    assert data is not None


def test_compose_accepted_warning() -> None:
    """Accepted warning -> severity downgraded to acknowledged."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "reason": "Intentional -- raising Series A early", "match": "claims"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "acknowledged"


def test_compose_corrupt_artifact() -> None:
    """Corrupt JSON artifact -> CORRUPT_ARTIFACT warning, not MISSING_ARTIFACT."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    # Write corrupt JSON to checklist.json
    with open(os.path.join(d, "checklist.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes
    # checklist.json should NOT appear as MISSING_ARTIFACT
    missing_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    assert not any("checklist.json" in m for m in missing_msgs)


def test_compose_severity_map_complete() -> None:
    """WARNING_SEVERITY contains all expected codes."""
    snippet = (
        f"import sys, os; sys.path.insert(0, '{DECK_REVIEW_DIR}'); "
        "from compose_report import WARNING_SEVERITY; "
        "import json; print(json.dumps(WARNING_SEVERITY))"
    )
    result = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True)
    try:
        sev_map = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(f"can't import WARNING_SEVERITY: stdout={result.stdout}, stderr={result.stderr}") from exc

    expected = [
        "CORRUPT_ARTIFACT",
        "MISSING_ARTIFACT",
        "STALE_ARTIFACT",
        "CHECKLIST_FAILURES_CRITICAL",
        "STAGE_MISMATCH",
        "SLIDE_COUNT_EXTREME",
        "UNCITED_CRITIQUE",
        "AI_CRITERIA_SKIPPED",
        "STAGE_OUT_OF_SCOPE",
        "UNSUPPORTED_CHECKLIST_CRITIQUE",
        "CHECKLIST_VALIDATION_FAILED",
        "AI_CRITERIA_ON_NON_AI",
        "AI_CRITERIA_MISSING",
    ]
    assert len(sev_map) == len(expected), f"expected {len(expected)} codes, got {len(sev_map)}"
    for code in expected:
        assert code in sev_map, f"{code} missing from severity map"
    assert sev_map["STALE_ARTIFACT"] == "high"
    assert sev_map["STAGE_OUT_OF_SCOPE"] == "low"


def test_compose_stale_artifact_mismatched_run_ids() -> None:
    """Mismatched run_id across artifacts triggers STALE_ARTIFACT warning."""
    import copy

    inventory = copy.deepcopy(_VALID_INVENTORY)
    inventory["metadata"] = {"run_id": "run-001"}
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["metadata"] = {"run_id": "run-001"}
    reviews = copy.deepcopy(_VALID_REVIEWS)
    reviews["metadata"] = {"run_id": "run-002"}  # stale!
    checklist = copy.deepcopy(_VALID_CHECKLIST)
    checklist["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": reviews,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" in codes


def test_compose_matching_run_ids_no_stale_warning() -> None:
    """Matching run_id across all artifacts produces no STALE_ARTIFACT warning."""
    import copy

    artifacts = {
        "deck_inventory.json": copy.deepcopy(_VALID_INVENTORY),
        "stage_profile.json": copy.deepcopy(_VALID_PROFILE),
        "slide_reviews.json": copy.deepcopy(_VALID_REVIEWS),
        "checklist.json": copy.deepcopy(_VALID_CHECKLIST),
    }
    for art in artifacts.values():
        art["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(artifacts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_no_run_ids_graceful() -> None:
    """No run_id in any artifact -> graceful degradation, no STALE_ARTIFACT."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_stage_out_of_scope_detected() -> None:
    """detected_stage 'series_b' -> STAGE_OUT_OF_SCOPE warning."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_b"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_OUT_OF_SCOPE"]
    assert stage_w[0]["severity"] == "low"


def test_compose_stage_out_of_scope_claimed() -> None:
    """claimed_stage 'growth' + detected_stage 'series_a' -> STAGE_OUT_OF_SCOPE warning."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "growth"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes


def test_compose_stage_in_scope() -> None:
    """detected_stage 'seed' -> no STAGE_OUT_OF_SCOPE warning."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_report_sections() -> None:
    """Report markdown contains expected section headers."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "Pitch Deck Review: TestCo" in report
    assert "## Executive Summary" in report
    assert "## Stage Context" in report
    assert "## Slide-by-Slide Feedback" in report
    assert "## Checklist Results" in report
    assert "## Top 5 Priority Fixes" in report
    assert "## Appendix: Full Checklist" in report


def test_compose_strict_mode_writes_output_file() -> None:
    """--strict -o should write output file THEN exit 1."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "compose_report.py",
            ["--dir", d, "--pretty", "--strict", "-o", tmp],
        )
        assert rc == 1
        assert os.path.exists(tmp)
        with open(tmp) as fh:
            data = json.load(fh)
        assert "report_markdown" in data
        assert "_strict_failed" not in json.dumps(data)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_compose_stage_mismatch_normalized() -> None:
    """pre-seed (hyphen) vs pre_seed (underscore) should NOT trigger STAGE_MISMATCH."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "pre-seed"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "pre_seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes


def test_compose_malformed_field_types() -> None:
    """Artifact with wrong field type (string instead of list) should not crash."""
    checklist = dict(_VALID_CHECKLIST)
    checklist["items"] = "not a list"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None


def test_compose_ai_criteria_missing_no_warning() -> None:
    """AI company with checklist missing AI items -> NO AI_CRITERIA_SKIPPED."""
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = True
    # Checklist with NO ai_ items at all (items list doesn't contain them)
    ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    items = [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test", "notes": None}
        for cid in _CHECKLIST_IDS
        if cid not in ai_ids
    ]
    # Also need the AI items to be absent. But the checklist validator requires all 35.
    # The compose script reads checklist.json as an artifact - it doesn't re-validate.
    # So we can provide a checklist artifact with items that exclude AI items.
    checklist = {
        "items": items,
        "summary": {
            "total": 31,
            "pass": 31,
            "fail": 0,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "AI_CRITERIA_SKIPPED" not in codes


def test_compose_accepted_warning_case_insensitive() -> None:
    """Case-insensitive matching in accepted_warnings."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "reason": "Intentional raise", "match": "CLAIMS"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "acknowledged"


def test_compose_accepted_warning_missing_reason_skipped() -> None:
    """Accepted warning without reason field is skipped."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "match": "claims"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "medium"  # NOT acknowledged
    assert "reason" in stderr.lower()


def test_checklist_fail_without_evidence_warned() -> None:
    """Fail item with empty evidence -> advisory stderr warning."""
    overrides = {
        "purpose_clear": {"status": "fail", "evidence": "", "notes": "bad"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "evidence" in stderr.lower()


# ---------------------------------------------------------------------------
# Framing disclaimer tests
# ---------------------------------------------------------------------------


def _complete_artifacts() -> dict[str, dict]:
    """Return all 4 valid deck-review artifacts."""
    return {
        "deck_inventory.json": _VALID_INVENTORY,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": _VALID_REVIEWS,
        "checklist.json": _VALID_CHECKLIST,
    }


def test_compose_benchmarks_framing() -> None:
    """Report contains 'reference data' framing for stage benchmarks."""
    d = _make_artifact_dir(_complete_artifacts())
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d, "--pretty"])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "reference data" in md


def test_compose_slide_framing() -> None:
    """Report contains agent evaluation framing for slide reviews."""
    d = _make_artifact_dir(_complete_artifacts())
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d, "--pretty"])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "agent" in md.lower()
