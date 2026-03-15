#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for deck review HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_deck_review.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECK_REVIEW_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts")


def run_script_raw(name: str, args: list[str] | None = None) -> tuple[int, str, str]:
    """Run a script and return (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(DECK_REVIEW_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# -- Fixture data --

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
            "headline": "TestCo -- Cloud Accounting",
            "content_summary": "Intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
    ],
}

_VALID_PROFILE = {
    "detected_stage": "seed",
    "confidence": "high",
    "evidence": ["Claims $2M ARR"],
    "is_ai_company": False,
    "stage_benchmarks": {
        "round_size_range": "$2M-$6M",
        "expected_traction": "$300K-$500K ARR",
        "runway_expectation": "18-24 months",
    },
}

_VALID_REVIEWS = {
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["Could add ICP"],
            "recommendations": ["Add target segment"],
            "best_practice_refs": ["Sequoia"],
        },
        {
            "slide_number": 2,
            "maps_to": "problem",
            "strengths": ["Good stats", "Relatable"],
            "weaknesses": [],
            "recommendations": [],
            "best_practice_refs": [],
        },
    ],
    "missing_slides": [],
    "overall_narrative_assessment": "Good flow.",
}

_VALID_REVIEWS_RICH = {
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["Could add ICP"],
            "recommendations": ["Add target segment"],
            "best_practice_refs": ["Sequoia"],
        },
        {
            "slide_number": 2,
            "maps_to": "problem",
            "strengths": ["Good stats", "Relatable", "Data-driven"],
            "weaknesses": [],
            "recommendations": ["Add customer quote"],
            "best_practice_refs": [],
        },
        {
            "slide_number": 3,
            "maps_to": "solution_product",
            "strengths": ["Clear demo"],
            "weaknesses": ["Too text-heavy", "No screenshot", "Missing workflow"],
            "recommendations": ["Add product screenshot", "Reduce text", "Show workflow"],
            "best_practice_refs": ["DocSend"],
        },
    ],
    "missing_slides": [
        {
            "expected_type": "traction_kpis",
            "importance": "critical",
            "recommendation": "Add traction slide with ARR data",
        },
    ],
    "overall_narrative_assessment": "Good opening, weak middle.",
}

_VALID_PROFILE_WITH_FRAMEWORK = {
    "detected_stage": "seed",
    "confidence": "high",
    "evidence": ["Claims $2M ARR"],
    "is_ai_company": False,
    "expected_framework": [
        "purpose_traction",
        "problem",
        "solution_product",
        "traction_kpis",
        "market",
    ],
    "stage_benchmarks": {
        "round_size_range": "$2M-$6M",
        "expected_traction": "$300K-$500K ARR",
        "runway_expectation": "18-24 months",
    },
}

_CHECKLIST_IDS = [
    "purpose_clear",
    "headlines_carry_story",
    "narrative_arc_present",
    "strongest_proof_early",
    "story_stands_alone",
    "problem_quantified",
    "solution_shows_workflow",
    "why_now_has_catalyst",
    "market_bottom_up",
    "competition_honest",
    "business_model_clear",
    "gtm_has_proof",
    "team_has_depth",
    "stage_appropriate_structure",
    "stage_appropriate_traction",
    "stage_appropriate_financials",
    "ask_ties_to_milestones",
    "round_size_realistic",
    "one_idea_per_slide",
    "minimal_text",
    "slide_count_appropriate",
    "consistent_design",
    "mobile_readable",
    "no_vague_purpose",
    "no_nice_to_have_problem",
    "no_hype_without_proof",
    "no_features_over_outcomes",
    "no_dodged_competition",
    "ai_retention_rebased",
    "ai_cost_to_serve_shown",
    "ai_defensibility_beyond_model",
    "ai_responsible_controls",
    "numbers_consistent",
    "data_room_ready",
    "contact_info_present",
]

_VALID_CHECKLIST = {
    "items": [
        {
            "id": cid,
            "category": "Test",
            "label": "Test",
            "status": "pass",
            "evidence": "test",
            "notes": None,
        }
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
        "by_category": {
            "Narrative Flow": {"pass": 5, "fail": 0, "warn": 0, "not_applicable": 0},
            "Slide Content": {"pass": 8, "fail": 0, "warn": 0, "not_applicable": 0},
            "Stage Fit": {"pass": 5, "fail": 0, "warn": 0, "not_applicable": 0},
            "Design & Readability": {"pass": 5, "fail": 0, "warn": 0, "not_applicable": 0},
            "Common Mistakes": {"pass": 5, "fail": 0, "warn": 0, "not_applicable": 0},
            "AI Company": {"pass": 4, "fail": 0, "warn": 0, "not_applicable": 0},
            "Diligence Readiness": {"pass": 3, "fail": 0, "warn": 0, "not_applicable": 0},
        },
        "failed_items": [],
        "warned_items": [],
    },
}


# -- Helpers --


def _make_artifact_dir(artifacts: dict[str, Any]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-viz-deck-")
    for name, data in artifacts.items():
        path = os.path.join(d, name)
        if isinstance(data, str):
            # Raw string (for corrupt artifacts)
            with open(path, "w") as f:
                f.write(data)
        else:
            with open(path, "w") as f:
                json.dump(data, f)
    return d


def _run_viz(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, str, str]:
    """Run visualize.py with given artifact dir."""
    args = ["--dir", artifact_dir]
    if extra_args:
        args.extend(extra_args)
    return run_script_raw("visualize.py", args)


def _all_artifacts() -> dict[str, dict]:
    """Return all 4 valid artifacts."""
    return {
        "deck_inventory.json": _VALID_INVENTORY,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": _VALID_REVIEWS,
        "checklist.json": _VALID_CHECKLIST,
    }


# -- Tests --


def test_complete_artifacts() -> None:
    """All 4 artifacts -> valid HTML with all chart SVGs."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, stderr = _run_viz(d)
    assert rc == 0, f"rc={rc}, stderr={stderr}"
    assert stdout.startswith("<!DOCTYPE html>")
    assert "<svg" in stdout
    assert "TestCo" in stdout


def test_missing_artifact() -> None:
    """No slide_reviews.json -> HTML renders with placeholder. Exit 0."""
    artifacts = _all_artifacts()
    del artifacts["slide_reviews.json"]
    d = _make_artifact_dir(artifacts)
    rc, stdout, stderr = _run_viz(d)
    assert rc == 0, f"rc={rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "No data available" in stdout


def test_missing_checklist() -> None:
    """No checklist.json -> HTML renders with placeholders for gauge, radar, breakdown."""
    artifacts = _all_artifacts()
    del artifacts["checklist.json"]
    d = _make_artifact_dir(artifacts)
    rc, stdout, stderr = _run_viz(d)
    assert rc == 0, f"rc={rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    # Three chart sections should have placeholders (gauge, radar, breakdown)
    assert stdout.count("No data available") >= 3


def test_corrupt_artifact() -> None:
    """Corrupt checklist.json -> no crash, placeholder shown. Exit 0."""
    artifacts: dict[str, dict | str] = {
        "deck_inventory.json": _VALID_INVENTORY,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": _VALID_REVIEWS,
        "checklist.json": "{corrupt json!!!}",
    }
    d = _make_artifact_dir(artifacts)
    rc, stdout, stderr = _run_viz(d)
    assert rc == 0, f"rc={rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Data unavailable" in stdout


def test_stub_artifact() -> None:
    """checklist.json = stub -> placeholder with reason. Exit 0."""
    artifacts: dict[str, dict | str] = {
        "deck_inventory.json": _VALID_INVENTORY,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": _VALID_REVIEWS,
        "checklist.json": {"skipped": True, "reason": "Not enough slides"},
    }
    d = _make_artifact_dir(artifacts)
    rc, stdout, stderr = _run_viz(d)
    assert rc == 0, f"rc={rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Not enough slides" in stdout


def test_output_flag() -> None:
    """-o /tmp/file.html writes to file, stdout empty."""
    d = _make_artifact_dir(_all_artifacts())
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = _run_viz(d, extra_args=["-o", tmp])
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp, encoding="utf-8") as fh:
            content = fh.read()
        assert "<!DOCTYPE html>" in content
        assert "<svg" in content
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src/href attributes."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    # Check that no src= or href= attributes reference external URLs
    # Allow xmlns references and internal anchors
    import re

    allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
    src_refs = re.findall(r'(?:src|href)="([^"]*)"', stdout)
    for ref in src_refs:
        if ref in allowed:
            continue
        assert not ref.startswith("http://"), f"External HTTP URL found: {ref}"
        assert not ref.startswith("https://"), f"External HTTPS URL found: {ref}"


def test_chart_data_values() -> None:
    """Score percentage 100.0 from fixture appears in output. Category names appear."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "100%" in stdout
    # All canonical categories should appear
    for cat in [
        "Narrative Flow",
        "Slide Content",
        "Stage Fit",
        "Design &amp; Readability",
        "Common Mistakes",
        "AI Company",
        "Diligence Readiness",
    ]:
        assert cat in stdout, f"Category {cat!r} not found in output"


def test_xss_safety_text() -> None:
    """Inventory with XSS in company_name -> properly escaped."""
    inventory = dict(_VALID_INVENTORY)
    inventory["company_name"] = "<script>alert(1)</script>"
    artifacts = _all_artifacts()
    artifacts["deck_inventory.json"] = inventory
    d = _make_artifact_dir(artifacts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "&lt;script&gt;" in stdout
    # Make sure no raw script tag from company name
    # (There may be no <script> tags at all in the HTML -- that's fine)
    assert "<script>alert(1)</script>" not in stdout


def test_xss_safety_attribute() -> None:
    """Slide review with XSS in weakness -> properly escaped."""
    reviews = {
        "reviews": [
            {
                "slide_number": 1,
                "maps_to": "purpose",
                "strengths": ["Good"],
                "weaknesses": ['foo" onload="alert(1)'],
                "recommendations": [],
                "best_practice_refs": [],
            },
        ],
        "missing_slides": [],
        "overall_narrative_assessment": "Ok.",
    }
    artifacts = _all_artifacts()
    artifacts["slide_reviews.json"] = reviews
    d = _make_artifact_dir(artifacts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    # The raw dangerous string should not appear unescaped
    assert 'onload="alert(1)"' not in stdout


def test_deterministic_output() -> None:
    """Run twice on identical artifacts -> identical HTML bytes."""
    d = _make_artifact_dir(_all_artifacts())
    rc1, stdout1, _ = _run_viz(d)
    rc2, stdout2, _ = _run_viz(d)
    assert rc1 == 0
    assert rc2 == 0
    assert stdout1 == stdout2


def test_html_structural_sanity() -> None:
    """Starts with DOCTYPE, balanced SVG tags, no raw script tags."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert stdout.startswith("<!DOCTYPE html>")
    # Balanced SVG tags
    open_svg = stdout.count("<svg")
    close_svg = stdout.count("</svg>")
    assert open_svg == close_svg, f"Unbalanced SVG tags: {open_svg} open, {close_svg} close"
    assert open_svg > 0, "Expected at least one SVG element"
    # Inline JS is allowed; verify script tags are balanced
    script_count = stdout.lower().count("<script")
    script_close = stdout.lower().count("</script>")
    assert script_count == script_close, "Unbalanced script tags"


def test_slide_map_diverging_bars() -> None:
    """Slide map renders SVG with diverging bars (green strengths, red weaknesses)."""
    arts = _all_artifacts()
    arts["slide_reviews.json"] = _VALID_REVIEWS_RICH
    arts["stage_profile.json"] = _VALID_PROFILE_WITH_FRAMEWORK
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "#10b981" in stdout, "Expected green (strength) bars"
    assert "#ef4444" in stdout, "Expected red (weakness) bars"
    assert "Purpose" in stdout
    assert "Problem" in stdout
    assert "Solution" in stdout


def test_slide_map_missing_slides() -> None:
    """Missing expected slides appear with dashed styling."""
    arts = _all_artifacts()
    arts["slide_reviews.json"] = _VALID_REVIEWS_RICH
    arts["stage_profile.json"] = _VALID_PROFILE_WITH_FRAMEWORK
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "Traction" in stdout
    assert "missing" in stdout.lower() or "critical" in stdout.lower()


def test_slide_map_recommendation_counts() -> None:
    """Recommendation counts appear per slide with actual count text."""
    arts = _all_artifacts()
    arts["slide_reviews.json"] = _VALID_REVIEWS_RICH
    arts["stage_profile.json"] = _VALID_PROFILE_WITH_FRAMEWORK
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "<svg" in stdout
    # _VALID_REVIEWS_RICH: slide 1 has 1 rec, slide 2 has 1 rec, slide 3 has 3 recs
    assert "1 rec<" in stdout or "1 rec</" in stdout, "Slide with 1 recommendation should show '1 rec'"
    assert "3 recs<" in stdout or "3 recs</" in stdout, "Slide with 3 recommendations should show '3 recs'"


def test_slide_map_no_stage_profile() -> None:
    """Slide map works without stage_profile.json (missing slides appended at bottom)."""
    arts = _all_artifacts()
    arts["slide_reviews.json"] = _VALID_REVIEWS_RICH
    del arts["stage_profile.json"]
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "Purpose" in stdout
    assert "Traction" in stdout


def test_slide_map_legend() -> None:
    """Slide map legend includes strength, weakness, and missing labels."""
    arts = _all_artifacts()
    arts["slide_reviews.json"] = _VALID_REVIEWS_RICH
    arts["stage_profile.json"] = _VALID_PROFILE_WITH_FRAMEWORK
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "Strengths" in stdout
    assert "Weaknesses" in stdout


def test_malformed_list_elements() -> None:
    """Non-dict items in slide reviews list don't crash."""
    arts = dict(_all_artifacts())
    reviews = dict(arts["slide_reviews.json"])
    reviews["reviews"] = [
        "bad_string",
        42,
        {
            "slide_number": 1,
            "strengths": ["good"],
            "weaknesses": [],
        },
    ]
    arts["slide_reviews.json"] = reviews
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout


def test_duplicate_slide_number_keeps_first() -> None:
    """Duplicate slide_number entries keep the first one, not the last."""
    arts = dict(_all_artifacts())
    reviews = dict(arts["slide_reviews.json"])
    reviews["reviews"] = [
        {"slide_number": 1, "strengths": ["a", "b"], "weaknesses": []},
        {"slide_number": 1, "strengths": [], "weaknesses": ["x", "y", "z"]},
    ]
    arts["slide_reviews.json"] = reviews
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    # First entry: 2 strengths, 0 weaknesses -> green (#10b981)
    # If second entry overwrote: 0 strengths, 3 weaknesses -> red
    assert "#10b981" in stdout, "First slide entry (green) should be kept"


# ---------------------------------------------------------------------------
# Gauge status humanization
# ---------------------------------------------------------------------------


def test_gauge_status_humanized() -> None:
    """overall_status 'needs_work' renders as 'Needs Work' (underscore replaced, title case)."""
    arts = _all_artifacts()
    checklist: dict[str, Any] = dict(_VALID_CHECKLIST)
    checklist["summary"] = dict(checklist["summary"])  # type: ignore[arg-type]
    checklist["summary"]["overall_status"] = "needs_work"  # type: ignore[index]
    checklist["summary"]["score_pct"] = 45.0  # type: ignore[index]
    arts["checklist.json"] = checklist
    d = _make_artifact_dir(arts)
    rc, stdout, _ = _run_viz(d)
    assert rc == 0
    assert "Needs Work" in stdout, "Snake_case status should be humanized to title case"
    assert "needs_work" not in stdout, "Raw snake_case should not appear in output"


# ---------------------------------------------------------------------------
# Framing disclaimer tests
# ---------------------------------------------------------------------------


def test_visualize_agent_framing() -> None:
    """HTML contains 'agent-generated' framing text."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _stderr = _run_viz(d)
    assert rc == 0
    assert "agent-generated" in stdout
