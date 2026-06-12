#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for IC simulation HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_ic_sim.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IC_SIM_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts")

_DIMENSION_IDS = [
    # Team
    "team_founder_market_fit",
    "team_complementary_skills",
    "team_execution_speed",
    "team_coachability",
    # Market
    "market_size_credibility",
    "market_timing",
    "market_growth_trajectory",
    "market_entry_barriers",
    # Product
    "product_differentiation",
    "product_traction_evidence",
    "product_technical_moat",
    "product_user_love",
    # Business Model
    "biz_unit_economics",
    "biz_pricing_power",
    "biz_scalability",
    "biz_gross_margins",
    # Financials
    "fin_capital_efficiency",
    "fin_runway_plan",
    "fin_path_to_next_round",
    "fin_revenue_quality",
    # Risk
    "risk_single_point_failure",
    "risk_regulatory",
    "risk_competitive_response",
    "risk_customer_concentration",
    # Fund Fit
    "fit_thesis_alignment",
    "fit_portfolio_conflict",
    "fit_stage_match",
    "fit_value_add",
]

_CATEGORY_FOR_DIM = (
    ["Team"] * 4
    + ["Market"] * 4
    + ["Product"] * 4
    + ["Business Model"] * 4
    + ["Financials"] * 4
    + ["Risk"] * 4
    + ["Fund Fit"] * 4
)

_VALID_STARTUP: dict[str, Any] = {
    "company_name": "TestCo",
    "simulation_date": "2026-02-22",
    "stage": "seed",
    "one_liner": "Cloud accounting for SMBs",
    "sector": "Fintech",
    "geography": "United States",
    "business_model": "SaaS",
    "materials_provided": ["pitch deck"],
}

_VALID_FUND: dict[str, Any] = {
    "fund_name": "Test Fund",
    "mode": "generic",
    "thesis_areas": ["B2B SaaS"],
    "check_size_range": {"min": 500000, "max": 5000000, "currency": "USD"},
    "stage_focus": ["seed"],
    "archetypes": [
        {
            "role": "visionary",
            "name": "V",
            "background": "b",
            "focus_areas": ["market"],
        },
        {
            "role": "operator",
            "name": "O",
            "background": "b",
            "focus_areas": ["execution"],
        },
        {
            "role": "analyst",
            "name": "A",
            "background": "b",
            "focus_areas": ["numbers"],
        },
    ],
    "portfolio": [
        {"name": "FinLedger", "sector": "Fintech"},
        {"name": "DataPipe", "sector": "Data"},
    ],
    "sources": [],
    "validation": {"status": "valid", "errors": []},
}

_VALID_CONFLICT: dict[str, Any] = {
    "portfolio_size": 2,
    "conflicts": [],
    "summary": {
        "total_checked": 2,
        "conflict_count": 0,
        "has_blocking_conflict": False,
        "overall_severity": "clear",
    },
    "validation": {"status": "valid", "errors": []},
}

_VALID_DISCUSSION: dict[str, Any] = {
    "assessment_mode": "sub-agent",
    "partner_verdicts": [
        {
            "partner": "visionary",
            "verdict": "invest",
            "rationale": "Large market, clear timing catalyst",
        },
        {
            "partner": "operator",
            "verdict": "more_diligence",
            "rationale": "Strong PMF but GTM unclear",
        },
        {
            "partner": "analyst",
            "verdict": "more_diligence",
            "rationale": "Unit economics emerging, need cohorts",
        },
    ],
    "debate_sections": [
        {
            "topic": "GTM Motion",
            "exchanges": [
                {"partner": "operator", "position": "Need channel economics"},
            ],
        },
    ],
    "consensus_verdict": "more_diligence",
    "key_concerns": ["GTM unclear", "Need cohort data"],
    "diligence_requirements": ["Channel CAC", "Cohort curves"],
}

_VALID_SCORE: dict[str, Any] = {
    "items": [
        {
            "id": did,
            "category": cat,
            "label": "Test",
            "status": "strong_conviction",
            "evidence": "test",
            "notes": None,
        }
        for did, cat in zip(_DIMENSION_IDS, _CATEGORY_FOR_DIM, strict=True)
    ],
    "summary": {
        "total": 28,
        "strong_conviction": 28,
        "moderate_conviction": 0,
        "concern": 0,
        "dealbreaker": 0,
        "not_applicable": 0,
        "applicable": 28,
        "conviction_score": 100.0,
        "verdict": "invest",
        "by_category": {
            "Team": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Market": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Product": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Business Model": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Financials": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Risk": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Fund Fit": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
        },
        "dealbreakers": [],
        "top_concerns": [],
        "warnings": [],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_artifact_dir(artifacts: dict[str, Any]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-vis-ic-sim-")
    for name, data in artifacts.items():
        path = os.path.join(d, name)
        if isinstance(data, str):
            # Raw string (e.g. corrupt JSON)
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
    return d


def _all_required_artifacts() -> dict[str, Any]:
    """Return all 5 required artifacts."""
    return {
        "startup_profile.json": _VALID_STARTUP,
        "fund_profile.json": _VALID_FUND,
        "conflict_check.json": _VALID_CONFLICT,
        "discussion.json": _VALID_DISCUSSION,
        "score_dimensions.json": _VALID_SCORE,
    }


def _run_visualize(
    artifact_dir: str,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        os.path.join(IC_SIM_DIR, "visualize.py"),
        "--dir",
        artifact_dir,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_complete_artifacts() -> None:
    """All 5 required artifacts -> valid HTML with all chart SVGs."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "<svg" in stdout
    assert "TestCo" in stdout


def test_missing_optional_artifact() -> None:
    """No partner assessment files -> HTML renders fine."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout


def test_missing_required_artifact() -> None:
    """No score_dimensions.json -> HTML renders with placeholders."""
    arts = _all_required_artifacts()
    del arts["score_dimensions.json"]
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    # Should contain placeholder text
    assert "not available" in stdout.lower() or "placeholder" in stdout.lower()


def test_corrupt_artifact() -> None:
    """Corrupt discussion.json -> no crash, placeholder."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    # Overwrite discussion.json with corrupt content
    with open(os.path.join(d, "discussion.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Data unavailable" in stdout


def test_stub_artifact() -> None:
    """score_dimensions.json = stub -> placeholder with reason."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = {
        "skipped": True,
        "reason": "Insufficient data",
    }
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Insufficient data" in stdout


def test_output_flag() -> None:
    """-o /tmp/file.html writes to file, stdout empty."""
    d = _make_artifact_dir(_all_required_artifacts())
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = _run_visualize(d, extra_args=["-o", tmp])
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp, encoding="utf-8") as fh:
            content = fh.read()
        assert "<!DOCTYPE html>" in content
        assert "TestCo" in content
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src/href attributes."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"

    # Find all src="..." and href="..." attributes
    allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
    src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
    for url in src_matches:
        if url in allowed:
            continue
        assert not url.startswith("http://"), f"External HTTP URL: {url}"
        assert not url.startswith("https://"), f"External HTTPS URL: {url}"


def test_chart_data_values() -> None:
    """Conviction score 100.0 appears, partner verdicts appear."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # Score value
    assert "100.0" in stdout
    # Partner verdicts
    assert "Invest" in stdout
    assert "More Diligence" in stdout


def test_xss_safety_text() -> None:
    """company_name with script tag -> escaped in output."""
    arts = _all_required_artifacts()
    arts["startup_profile.json"] = dict(_VALID_STARTUP)
    arts["startup_profile.json"]["company_name"] = "<script>alert(1)</script>"
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # Raw script tag must NOT appear
    assert "<script>alert(1)</script>" not in stdout
    # Escaped version should be present
    assert "&lt;script&gt;" in stdout


def test_xss_safety_attribute() -> None:
    """Partner rationale with attribute injection -> properly escaped."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["partner_verdicts"] = [
        {
            "partner": "visionary",
            "verdict": "invest",
            "rationale": '"foo" onload="alert(1)"',
        },
        {
            "partner": "operator",
            "verdict": "more_diligence",
            "rationale": "Normal text",
        },
        {
            "partner": "analyst",
            "verdict": "pass",
            "rationale": "Normal text",
        },
    ]
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # The raw dangerous attribute must not appear
    assert 'onload="alert(1)"' not in stdout
    # Escaped quotes should appear
    assert "&quot;foo&quot;" in stdout


def test_deterministic_output() -> None:
    """Run twice -> identical HTML bytes."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc1, out1, _ = _run_visualize(d)
    rc2, out2, _ = _run_visualize(d)
    assert rc1 == 0
    assert rc2 == 0
    assert out1 == out2, "Output differs between runs"


def test_html_structural_sanity() -> None:
    """DOCTYPE present, balanced SVG tags, no script tags."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _ = _run_visualize(d)
    assert rc == 0
    assert stdout.strip().startswith("<!DOCTYPE html>")

    # Balanced SVG tags
    open_count = len(re.findall(r"<svg[\s>]", stdout))
    close_count = stdout.count("</svg>")
    assert open_count == close_count, f"Unbalanced SVG tags: {open_count} opens vs {close_count} closes"

    # Inline JS is allowed; verify script tags are balanced
    script_count = stdout.lower().count("<script")
    script_close = stdout.lower().count("</script>")
    assert script_count == script_close, "Unbalanced script tags"


def test_dealbreaker_verdict() -> None:
    """score_dimensions with verdict=hard_pass and dealbreaker -> gauge shows hard_pass."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    items = list(_VALID_SCORE["items"])
    # Replace first item with a dealbreaker
    items[0] = dict(items[0])
    items[0]["status"] = "dealbreaker"
    score["items"] = items

    summary = dict(_VALID_SCORE["summary"])
    summary["verdict"] = "hard_pass"
    summary["conviction_score"] = 96.4
    summary["dealbreaker"] = 1
    summary["strong_conviction"] = 27
    summary["dealbreakers"] = [
        {
            "id": _DIMENSION_IDS[0],
            "category": "Team",
            "label": "Test",
            "evidence": "test",
            "notes": "fatal",
        },
    ]
    score["summary"] = summary
    arts["score_dimensions.json"] = score

    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # Should show "Hard Pass" text
    assert "Hard Pass" in stdout
    # hard_pass color (#92301F) should appear
    assert "#92301F" in stdout


def test_malformed_list_elements() -> None:
    """Non-dict items in partner_verdicts and conflicts don't crash."""
    arts = dict(_all_required_artifacts())
    # Inject non-dict elements into partner_verdicts
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        "bad_string",
        {"partner": "visionary", "verdict": "invest", "rationale": "Great team"},
        42,
    ]
    arts["discussion.json"] = disc
    # Inject non-dict elements into conflicts
    conflict = dict(arts["conflict_check.json"])
    conflict["conflicts"] = [
        "not_a_dict",
        {"company": "SomeComp", "type": "adjacent", "severity": "manageable"},
    ]
    arts["conflict_check.json"] = conflict
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout


def test_partner_role_case_insensitive() -> None:
    """Partner verdicts with mixed-case roles still match canonical cards."""
    arts = dict(_all_required_artifacts())
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "Visionary", "verdict": "invest", "rationale": "Great"},
        {"partner": " OPERATOR ", "verdict": "more_diligence", "rationale": "Ok"},
        {"partner": "Analyst", "verdict": "pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # All 3 canonical partners should have real verdicts (not "No verdict")
    assert stdout.count("No verdict") == 0, "Mixed-case roles should match canonical partners"
    assert "Invest" in stdout
    assert "More Diligence" in stdout


def test_verdict_color_case_insensitive() -> None:
    """Capitalized verdict like 'Invest' still gets correct color, not gray fallback."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "Invest", "rationale": "Great"},
        {"partner": "operator", "verdict": "MORE_DILIGENCE", "rationale": "Ok"},
        {"partner": "analyst", "verdict": "Pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Invest -> green (#2F8A56), not gray fallback (#A6AEB5)
    assert "#2F8A56" in stdout, "Invest verdict should map to green color"


def test_severity_color_case_insensitive() -> None:
    """Capitalized severity like 'Blocking' still gets correct color."""
    arts = _all_required_artifacts()
    arts["conflict_check.json"] = {
        "conflicts": [
            {
                "company": "CompetitorCo",
                "type": "direct_competitor",
                "severity": "Blocking",
                "detail": "Same market",
            },
        ],
        "summary": {"overall_severity": "Blocking", "total": 1},
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Blocking -> red (#C0392B), not gray fallback
    assert "#C0392B" in stdout, "Blocking severity should map to red color"


def test_empty_partner_role_skipped() -> None:
    """Empty string partner role doesn't produce a blank card."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "", "verdict": "invest", "rationale": "Ghost"},
        {"partner": "visionary", "verdict": "invest", "rationale": "Great"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # The empty-role entry should not appear as a card
    assert "Ghost" not in stdout, "Empty partner role should be skipped"


# ---------------------------------------------------------------------------
# AI simulation disclaimer tests
# ---------------------------------------------------------------------------


def test_visualize_partner_disclaimer() -> None:
    """HTML contains 'AI-simulated' text in partner verdicts section."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "AI-simulated" in stdout


def test_dealbreaker_color_visible() -> None:
    """Dealbreaker bars use visible color (#92301F), not near-invisible #7f1d1d."""
    arts = _all_required_artifacts()
    # Create a score with dealbreakers to trigger bar rendering
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    summary["by_category"] = dict(summary["by_category"])
    summary["by_category"]["Team"] = {
        "strong_conviction": 0,
        "moderate_conviction": 0,
        "concern": 1,
        "dealbreaker": 2,
        "not_applicable": 1,
    }
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # New visible color should appear; old invisible color should not
    assert "#92301F" in stdout, "Dealbreaker should use visible #92301F"
    assert "#7f1d1d" not in stdout, "Old invisible dealbreaker color should be gone"


def test_visualize_conviction_disclaimer() -> None:
    """HTML contains 'AI-generated assessment' below conviction gauge."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "AI-generated assessment" in stdout


def test_radar_zero_score_not_at_center() -> None:
    """Categories with 0% score should NOT collapse to exact center (minimum floor)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    # Team has 0 strong, 0 moderate -> 0% weighted score
    summary["by_category"] = {
        "Team": {"strong_conviction": 0, "moderate_conviction": 0, "concern": 3, "dealbreaker": 1, "not_applicable": 0},
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 0,
            "moderate_conviction": 0,
            "concern": 4,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # The data polygon has fill-opacity="0.2" — find it loosely
    polygon_match = re.search(r'<polygon points="([^"]+)"[^>]*fill-opacity="0\.2"', stdout)
    assert polygon_match, "Radar data polygon not found"
    points_str = polygon_match.group(1)
    # Derive center and radius from SVG so the test doesn't hardcode geometry.
    # Every spoke line originates from center (x1, y1) and ends at the rim (x2, y2).
    spoke = re.search(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', stdout)
    assert spoke, "No spoke line found in radar chart"
    cx, cy = float(spoke.group(1)), float(spoke.group(2))
    sx, sy = float(spoke.group(3)), float(spoke.group(4))
    max_r = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
    # Allow 0.1px tolerance for :.2f coordinate rounding.
    min_dist = max_r * 0.05 - 0.1
    pairs = [p.strip() for p in points_str.split(" ") if "," in p]
    for pair in pairs:
        x, y = (float(v) for v in pair.split(","))
        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        assert dist >= min_dist, f"Data point {pair} is {dist:.1f}px from center, need >= {min_dist:.1f}px (5% floor)"


def test_html_title_includes_company() -> None:
    """HTML <title> should include company name, not be generic."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<title>IC Simulation: TestCo</title>" in stdout


def test_css_has_responsive_breakpoint() -> None:
    """CSS media query should collapse chart-grid and partner-grid to single column."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "@media" in stdout, "Should have at least one media query"
    assert "max-width" in stdout, "Should have max-width breakpoint"
    # Extract the @media block by matching braces (handles nested rules).
    media_start = stdout.find("@media")
    assert media_start != -1, "Media query not found"
    open_brace = stdout.index("{", media_start)
    depth, pos = 1, open_brace + 1
    while depth > 0 and pos < len(stdout):
        if stdout[pos] == "{":
            depth += 1
        elif stdout[pos] == "}":
            depth -= 1
        pos += 1
    media_body = stdout[open_brace:pos]
    assert ".chart-grid" in media_body, "chart-grid should be restyled in media query"
    assert ".partner-grid" in media_body, "partner-grid should be restyled in media query"
    assert "grid-template-columns" in media_body, "Grids should collapse to single column"


def test_svg_scales_on_mobile() -> None:
    """SVGs should have max-width:100% so they don't overflow containers."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "max-width: 100%" in stdout or "max-width:100%" in stdout


def test_h2_border_visible_in_chart_box() -> None:
    """h2 inside chart-box should use a visible border color, not a bg-matching one."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert ".chart-box h2" in stdout
    match = re.search(r"\.chart-box h2\s*\{([^}]+)\}", stdout)
    assert match, ".chart-box h2 CSS rule not found"
    rule_body = match.group(1)
    assert "var(--lool-line-2)" in rule_body, "h2 border should use visible var(--lool-line-2), not bg-matching #1e293b"


def test_rationale_truncation_respects_sentences() -> None:
    """Rationale truncation should break at sentence boundary when possible."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    long_rationale = (
        "The market opportunity is genuinely massive with multiple secular tailwinds driving adoption. "
        "The founding team brings deep domain expertise from a decade at top-tier enterprise companies. "
        "However the unit economics are entirely unproven and require significant further validation."
    )
    assert len(long_rationale) > 250, f"Test rationale must exceed 250 chars, got {len(long_rationale)}"
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": long_rationale},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Short."},
        {"partner": "analyst", "verdict": "pass", "rationale": "Short."},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "enterprise companies." in stdout, "Should include up to the second sentence"
    assert "further validation" not in stdout, "Third sentence should not appear"


def test_summary_bar_present() -> None:
    """HTML should include a text summary with one-liner, sector, breakdown, and partner verdicts."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert _VALID_STARTUP["one_liner"] in stdout, "One-liner should appear in summary bar"
    assert _VALID_STARTUP["sector"] in stdout, "Sector should appear in summary bar"
    strong_count = _VALID_SCORE["summary"]["strong_conviction"]
    moderate_count = _VALID_SCORE["summary"]["moderate_conviction"]
    concern_count = _VALID_SCORE["summary"]["concern"]
    db_count = _VALID_SCORE["summary"]["dealbreaker"]
    assert f"{strong_count} strong" in stdout, "Strong count should appear"
    assert f"{moderate_count} moderate" in stdout, "Moderate count should appear"
    assert f"{concern_count} concern" in stdout, "Concern count should appear"
    assert f"{db_count} dealbreaker" in stdout, "Dealbreaker count should appear"
    assert "Visionary: Invest" in stdout, "Summary bar should show Visionary verdict"
    assert "Operator: More Diligence" in stdout, "Summary bar should show Operator verdict"
    assert "Analyst: More Diligence" in stdout, "Summary bar should show Analyst verdict"


def test_radar_outer_labels_show_scores() -> None:
    """Outer category labels should include percentage scores beneath category names."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    summary["by_category"] = {
        "Team": {"strong_conviction": 1, "moderate_conviction": 1, "concern": 2, "dealbreaker": 0, "not_applicable": 0},
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    # Team: (1*1.0 + 1*0.5) / 4 * 100 = 37.5% -> renders as "38%" (rounded)
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "38%" in stdout, "Team's 37.5% rounded to 38% should appear as outer label"
    assert "Team" in stdout, "Category name should appear as outer label"


def test_key_findings_distinguishes_mixed_strong_from_all_strong() -> None:
    """A category with strong AND moderate convictions (no concerns) must read
    'leans strong with no concerns', not the inaccurate 'scores all strong
    conviction' (which is reserved for categories that are purely strong)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    summary["by_category"] = {
        # mixed positive: strong present, moderate present, no concerns
        "Team": {"strong_conviction": 2, "moderate_conviction": 2, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        # purely strong
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Team leans strong with no concerns" in stdout
    assert "Team scores all strong conviction" not in stdout
    # a purely-strong category still uses the original phrasing
    assert "Market scores all strong conviction" in stdout


# ===========================================================================
# Key-coverage tests: producer output keys ⊆ renderer known sets
# ===========================================================================
#
# Invariant: when score_dimensions.py / detect_conflicts.py adds a new
# status, verdict, or severity value, the corresponding visualize.py color
# map must be updated. These tests pin the current complete sets so any new
# emitted key causes a loud failure with the offending name listed.
# ===========================================================================

_IC_SIM_VISUALIZE_SCRIPT = os.path.join(IC_SIM_DIR, "visualize.py")
_IC_SIM_SCORE_DIMENSIONS_SCRIPT = os.path.join(IC_SIM_DIR, "score_dimensions.py")
_IC_SIM_DETECT_CONFLICTS_SCRIPT = os.path.join(IC_SIM_DIR, "detect_conflicts.py")


def _load_ic_sim_visualize() -> types.ModuleType:
    """Import ic-sim visualize.py with a unique sys.modules key.

    _theme is imported lazily inside a render function, so no stub is needed
    at module load time.
    """
    key = "_ic_sim_keycov_visualize"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_VISUALIZE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_VISUALIZE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_ic_sim_score_dimensions() -> types.ModuleType:
    """Import ic-sim score_dimensions.py with a unique sys.modules key."""
    key = "_ic_sim_keycov_score_dimensions"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_SCORE_DIMENSIONS_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_SCORE_DIMENSIONS_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_ic_sim_detect_conflicts() -> types.ModuleType:
    """Import ic-sim detect_conflicts.py with a unique sys.modules key."""
    key = "_ic_sim_keycov_detect_conflicts"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_DETECT_CONFLICTS_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_DETECT_CONFLICTS_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Test A: dimension statuses → visualize._STATUS_COLORS coverage
# ---------------------------------------------------------------------------


class TestIcSimDimensionStatusColorCoverage:
    """Every dimension status that score_dimensions.py can emit must appear
    in visualize.py's _STATUS_COLORS so category bars receive the correct colour.

    Produced set is derived live from score_dimensions.VALID_STATUSES.
    """

    def test_all_dimension_statuses_in_status_colors(self) -> None:
        """Every dimension status the producer emits must map to a colour."""
        produced = _load_ic_sim_score_dimensions().VALID_STATUSES
        viz = _load_ic_sim_visualize()
        color_keys: set[str] = set(viz._STATUS_COLORS.keys())

        missing = produced - color_keys
        assert not missing, (
            f"visualize._STATUS_COLORS is missing a colour entry for dimension status(es) "
            f"emitted by score_dimensions.py: {sorted(missing)}. "
            f"Add entries to _STATUS_COLORS for each."
        )

    def test_producer_dimension_statuses_min_count(self) -> None:
        """Guard against vacuous tests: VALID_STATUSES must have at least 5 statuses."""
        produced = _load_ic_sim_score_dimensions().VALID_STATUSES
        assert len(produced) >= 5, (
            f"VALID_STATUSES expected >= 5 entries, got {len(produced)}. Check score_dimensions.VALID_STATUSES."
        )

    def test_status_colors_min_count(self) -> None:
        """_STATUS_COLORS must cover at least the producer statuses."""
        produced = _load_ic_sim_score_dimensions().VALID_STATUSES
        viz = _load_ic_sim_visualize()
        assert len(viz._STATUS_COLORS) >= len(produced), (
            f"visualize._STATUS_COLORS has only {len(viz._STATUS_COLORS)} entries; expected >= {len(produced)}."
        )


# ---------------------------------------------------------------------------
# Test B: partner verdict values → visualize._VERDICT_COLORS coverage
# ---------------------------------------------------------------------------


class TestIcSimPartnerVerdictColorCoverage:
    """Every verdict value that score_dimensions.py's summary can emit must
    appear in visualize.py's _VERDICT_COLORS so the conviction gauge shows
    the correct colour instead of the neutral fallback.

    The 4 verdicts come from _summarize() branches in score_dimensions.py —
    there is no exported constant, so they are pinned here. A source-grep
    guard ensures each literal is still present in the source so a rename
    fails loudly.
    """

    # Verdict strings emitted by score_dimensions._summarize() branches.
    PRODUCER_VERDICTS: set[str] = {
        "invest",
        "more_diligence",
        "pass",
        "hard_pass",
    }

    def test_verdict_literals_present_in_source(self) -> None:
        """Each hardcoded verdict must appear as a string literal in score_dimensions.py.

        Guards against silent renames: if a verdict string is removed from the
        source, this test fails before any runtime path needs to exercise it.
        """
        with open(_IC_SIM_SCORE_DIMENSIONS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        for verdict in self.PRODUCER_VERDICTS:
            assert f'"{verdict}"' in src or f"'{verdict}'" in src, (
                f"Verdict string {verdict!r} not found as a literal in score_dimensions.py. "
                f"Update PRODUCER_VERDICTS if _summarize() was changed."
            )

    def test_all_verdicts_in_verdict_colors(self) -> None:
        """Every verdict the producer emits must map to a colour."""
        viz = _load_ic_sim_visualize()
        color_keys: set[str] = set(viz._VERDICT_COLORS.keys())

        missing = self.PRODUCER_VERDICTS - color_keys
        assert not missing, (
            f"visualize._VERDICT_COLORS is missing a colour entry for verdict(s) "
            f"emitted by score_dimensions.py: {sorted(missing)}. "
            f"Add entries to _VERDICT_COLORS for each."
        )

    def test_producer_verdicts_min_count(self) -> None:
        """Guard against vacuous tests: producer set must have exactly 4 verdicts."""
        assert len(self.PRODUCER_VERDICTS) == 4, (
            f"PRODUCER_VERDICTS expected 4 entries, got {len(self.PRODUCER_VERDICTS)}."
        )

    def test_verdict_colors_min_count(self) -> None:
        """_VERDICT_COLORS must cover at least the 4 producer verdicts."""
        viz = _load_ic_sim_visualize()
        assert len(viz._VERDICT_COLORS) >= 4, (
            f"visualize._VERDICT_COLORS has only {len(viz._VERDICT_COLORS)} entries; expected >= 4."
        )

    def test_verdict_colors_pairwise_distinct(self) -> None:
        """Each producer verdict must have a colour distinct from every other
        verdict's colour — in particular hard_pass must NOT share pass's colour,
        or the gauge cannot distinguish the two most severe outcomes.
        """
        viz = _load_ic_sim_visualize()
        colors = {v: viz._VERDICT_COLORS.get(v) for v in self.PRODUCER_VERDICTS}
        seen: dict[str, str] = {}
        for verdict, color in sorted(colors.items()):
            assert color is not None, f"_VERDICT_COLORS missing entry for {verdict!r}."
            assert color not in seen, (
                f"_VERDICT_COLORS gives {verdict!r} the same colour {color!r} as {seen[color]!r}. "
                f"Each verdict on the spectrum needs a visually distinct colour."
            )
            seen[color] = verdict


# ---------------------------------------------------------------------------
# Test C: conflict severity values → visualize._SEVERITY_COLORS coverage
# ---------------------------------------------------------------------------


class TestIcSimConflictSeverityColorCoverage:
    """Every conflict severity value that detect_conflicts.py can emit must
    appear in visualize.py's _SEVERITY_COLORS so the conflict summary chart
    shows the correct colour instead of the neutral fallback.

    VALID_SEVERITIES ({"blocking", "manageable"}) is loaded live.
    "clear" is not in VALID_SEVERITIES (it is computed in overall_severity
    when no conflicts exist); it is pinned here with a source-grep guard.
    """

    # "clear" is emitted in detect_conflicts.py but is not in VALID_SEVERITIES.
    _HARDCODED_EXTRA: set[str] = {"clear"}

    def _producer_severities(self) -> set[str]:
        """VALID_SEVERITIES union hardcoded extras."""
        return set[str](_load_ic_sim_detect_conflicts().VALID_SEVERITIES) | self._HARDCODED_EXTRA

    def test_clear_literal_present_in_source(self) -> None:
        """'clear' must appear as a string literal in detect_conflicts.py source."""
        with open(_IC_SIM_DETECT_CONFLICTS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        assert '"clear"' in src or "'clear'" in src, (
            "'clear' not found as a literal in detect_conflicts.py. "
            "Update _HARDCODED_EXTRA if the severity was renamed."
        )

    def test_all_severities_in_severity_colors(self) -> None:
        """Every conflict severity the producer emits must map to a colour."""
        produced = self._producer_severities()
        viz = _load_ic_sim_visualize()
        color_keys: set[str] = set(viz._SEVERITY_COLORS.keys())

        missing = produced - color_keys
        assert not missing, (
            f"visualize._SEVERITY_COLORS is missing a colour entry for severity value(s) "
            f"emitted by detect_conflicts.py: {sorted(missing)}. "
            f"Add entries to _SEVERITY_COLORS for each."
        )

    def test_producer_severities_min_count(self) -> None:
        """Guard against vacuous tests: produced set must have at least 3 severities."""
        produced = self._producer_severities()
        assert len(produced) >= 3, f"VALID_SEVERITIES + extras expected >= 3 entries, got {len(produced)}."

    def test_severity_colors_min_count(self) -> None:
        """_SEVERITY_COLORS must cover at least the producer severities."""
        produced = self._producer_severities()
        viz = _load_ic_sim_visualize()
        assert len(viz._SEVERITY_COLORS) >= len(produced), (
            f"visualize._SEVERITY_COLORS has only {len(viz._SEVERITY_COLORS)} entries; expected >= {len(produced)}."
        )


# ---------------------------------------------------------------------------
# Test D: score_dimensions categories → visualize._CANONICAL_CATEGORIES coverage
# ---------------------------------------------------------------------------


class TestIcSimCategoryCoverage:
    """Every category name that score_dimensions.py can emit must appear in
    visualize.py's _CANONICAL_CATEGORIES so radar and bar charts include all
    spokes/bars in the correct order.

    Produced set is derived live from score_dimensions.DIMENSION_ITEMS.
    """

    @staticmethod
    def _producer_categories() -> set[str]:
        """Derive emittable category names live from DIMENSION_ITEMS."""
        sd = _load_ic_sim_score_dimensions()
        return {item["category"] for item in sd.DIMENSION_ITEMS}

    def test_all_producer_categories_in_canonical_list(self) -> None:
        """Every category the score producer emits must appear in _CANONICAL_CATEGORIES."""
        produced = self._producer_categories()
        viz = _load_ic_sim_visualize()
        canonical: set[str] = set(viz._CANONICAL_CATEGORIES)

        missing = produced - canonical
        assert not missing, (
            f"visualize._CANONICAL_CATEGORIES is missing category(ies) "
            f"emitted by score_dimensions.py: {sorted(missing)}. "
            f"Add them to _CANONICAL_CATEGORIES in the correct order."
        )

    def test_producer_categories_min_count(self) -> None:
        """Guard against vacuous tests: produced set must have at least 7 categories."""
        produced = self._producer_categories()
        assert len(produced) >= 7, (
            f"DIMENSION_ITEMS expected >= 7 distinct categories, got {len(produced)}. "
            f"Check score_dimensions.DIMENSION_ITEMS."
        )

    def test_canonical_categories_min_count(self) -> None:
        """_CANONICAL_CATEGORIES must list at least the producer categories."""
        produced = self._producer_categories()
        viz = _load_ic_sim_visualize()
        assert len(viz._CANONICAL_CATEGORIES) >= len(produced), (
            f"visualize._CANONICAL_CATEGORIES has only {len(viz._CANONICAL_CATEGORIES)} entries; "
            f"expected >= {len(produced)}."
        )
