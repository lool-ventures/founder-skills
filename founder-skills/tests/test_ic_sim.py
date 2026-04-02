#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for IC simulation scripts.

Run: pytest founder-skills/tests/test_ic_sim.py -v
All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IC_SIM_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts")


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(IC_SIM_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def run_script_raw(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, str, str]:
    """Like run_script but returns (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(IC_SIM_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# -- All 28 canonical dimension IDs --

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


def _make_dimension_items(
    overrides: dict[str, dict] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Build a 28-item dimension payload."""
    overrides = overrides or {}
    exclude = exclude or []
    items = []
    for did in _DIMENSION_IDS:
        if did in exclude:
            continue
        if did in overrides:
            items.append({"id": did, **overrides[did]})
        else:
            items.append({"id": did, "status": "strong_conviction", "evidence": "test evidence", "notes": None})
    return items


# ============================================================
# score_dimensions.py tests
# ============================================================


def test_score_all_strong() -> None:
    """All 28 items strong_conviction -> invest, 100%."""
    payload = json.dumps({"items": _make_dimension_items()})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["total"] == 28
    assert s["strong_conviction"] == 28
    assert s["conviction_score"] == 100.0
    assert s["verdict"] == "invest"
    assert len(s["dealbreakers"]) == 0
    assert len(s["top_concerns"]) == 0
    assert s["warnings"] == []


def test_score_invest_threshold() -> None:
    """75% conviction -> invest."""
    # 28 items, make 7 concern (0 score) -> 21 strong -> 21/28 = 75%
    overrides = {did: {"status": "concern", "evidence": "test", "notes": "concern"} for did in _DIMENSION_IDS[:7]}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["verdict"] == "invest"
    assert data["summary"]["conviction_score"] == 75.0


def test_score_more_diligence_threshold() -> None:
    """50-74.9% conviction -> more_diligence."""
    # 14 strong, 14 concern -> 14/28 = 50%
    overrides = {did: {"status": "concern", "evidence": "test", "notes": "concern"} for did in _DIMENSION_IDS[:14]}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["verdict"] == "more_diligence"
    assert data["summary"]["conviction_score"] == 50.0


def test_score_pass_threshold() -> None:
    """<50% conviction -> pass."""
    # 13 strong, 15 concern -> 13/28 = 46.4%
    overrides = {did: {"status": "concern", "evidence": "test", "notes": "concern"} for did in _DIMENSION_IDS[:15]}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["verdict"] == "pass"
    assert data["summary"]["conviction_score"] < 50


def test_score_dealbreaker_forces_hard_pass() -> None:
    """One dealbreaker forces hard_pass regardless of score."""
    overrides = {
        "risk_single_point_failure": {"status": "dealbreaker", "evidence": "Single customer", "notes": "fatal"},
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["verdict"] == "hard_pass"
    assert data["summary"]["dealbreaker"] == 1
    assert len(data["summary"]["dealbreakers"]) == 1
    assert data["summary"]["dealbreakers"][0]["id"] == "risk_single_point_failure"


def test_score_moderate_conviction_half_weight() -> None:
    """moderate_conviction items contribute 0.5 to score."""
    # All moderate: 28 * 0.5 / 28 = 50% -> more_diligence
    overrides = {did: {"status": "moderate_conviction", "evidence": "test", "notes": None} for did in _DIMENSION_IDS}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["conviction_score"] == 50.0
    assert data["summary"]["verdict"] == "more_diligence"


def test_score_not_applicable_excluded() -> None:
    """not_applicable items are excluded from scoring."""
    # 4 N/A, 24 strong -> 24/24 = 100%
    overrides = {
        did: {"status": "not_applicable", "evidence": "N/A", "notes": "Not relevant"} for did in _DIMENSION_IDS[:4]
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["not_applicable"] == 4
    assert data["summary"]["applicable"] == 24
    assert data["summary"]["conviction_score"] == 100.0
    assert data["summary"]["verdict"] == "invest"


def test_score_zero_applicable_guard() -> None:
    """All not_applicable -> score 0.0, verdict more_diligence, warning emitted."""
    overrides = {did: {"status": "not_applicable", "evidence": "N/A", "notes": None} for did in _DIMENSION_IDS}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["conviction_score"] == 0.0
    assert data["summary"]["verdict"] == "more_diligence"
    assert "ZERO_APPLICABLE_DIMENSIONS" in data["summary"]["warnings"]


def test_score_by_category() -> None:
    """by_category counts are correct."""
    overrides = {
        "team_founder_market_fit": {"status": "concern", "evidence": "test", "notes": "weak"},
        "team_complementary_skills": {"status": "moderate_conviction", "evidence": "test", "notes": "ok"},
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    cat = data["summary"]["by_category"]
    team = cat.get("Team", {})
    assert team.get("strong_conviction") == 2
    assert team.get("moderate_conviction") == 1
    assert team.get("concern") == 1


def test_score_missing_items() -> None:
    """Only 25 items -> validation.status = invalid."""
    items = _make_dimension_items(exclude=_DIMENSION_IDS[-3:])
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("missing" in e.lower() for e in data["validation"]["errors"])


def test_score_duplicate_id() -> None:
    """Duplicate ID -> validation.status = invalid."""
    items = _make_dimension_items()
    items.append({"id": "team_founder_market_fit", "status": "strong_conviction", "evidence": "dup", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("duplicate" in e.lower() for e in data["validation"]["errors"])


def test_score_unknown_id() -> None:
    """Unknown ID -> validation.status = invalid."""
    items = _make_dimension_items()
    items[0] = {"id": "bogus_dimension", "status": "strong_conviction", "evidence": "test", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("bogus_dimension" in e.lower() for e in data["validation"]["errors"])


def test_score_invalid_status() -> None:
    """Invalid status -> validation.status = invalid."""
    overrides = {"team_founder_market_fit": {"status": "maybe", "evidence": "test", "notes": None}}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("maybe" in e.lower() for e in data["validation"]["errors"])


def test_score_output_flag() -> None:
    """score_dimensions.py with -o writes to file, stdout empty."""
    payload = json.dumps({"items": _make_dimension_items()})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw("score_dimensions.py", ["--pretty", "-o", tmp], stdin_data=payload)
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "summary" in data
        assert len(data["items"]) == 28
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ============================================================
# fund_profile.py tests
# ============================================================

_VALID_GENERIC_PROFILE: dict[str, Any] = {
    "fund_name": "Generic Early-Stage Fund",
    "mode": "generic",
    "thesis_areas": ["B2B SaaS", "Fintech"],
    "check_size_range": {"min": 500000, "max": 5000000, "currency": "USD"},
    "stage_focus": ["pre_seed", "seed"],
    "archetypes": [
        {"role": "visionary", "name": "The Visionary", "background": "Ex-founder", "focus_areas": ["market"]},
        {"role": "operator", "name": "The Operator", "background": "Ex-COO", "focus_areas": ["execution"]},
        {"role": "analyst", "name": "The Analyst", "background": "Ex-banker", "focus_areas": ["unit economics"]},
    ],
    "portfolio": [
        {"name": "FinLedger", "sector": "Fintech", "status": "active"},
        {"name": "DataPipe", "sector": "Data", "status": "active"},
    ],
    "sources": [],
}

_VALID_FUND_SPECIFIC: dict[str, Any] = {
    "fund_name": "Sequoia Capital",
    "mode": "fund_specific",
    "thesis_areas": ["Consumer", "Enterprise", "Crypto"],
    "check_size_range": {"min": 1000000, "max": 10000000, "currency": "USD"},
    "stage_focus": ["seed", "series_a"],
    "archetypes": [
        {"role": "visionary", "name": "Alfred Lin", "background": "Ex-Zappos COO", "focus_areas": ["market"]},
        {"role": "operator", "name": "Jess Lee", "background": "Ex-Polyvore CEO", "focus_areas": ["product"]},
        {"role": "analyst", "name": "Pat Grady", "background": "Growth investor", "focus_areas": ["metrics"]},
    ],
    "portfolio": [
        {"name": "Stripe", "sector": "Fintech"},
        {"name": "DoorDash", "sector": "Logistics"},
    ],
    "sources": [{"url": "https://sequoiacap.com"}, {"title": "Crunchbase"}],
}


def test_fund_profile_valid_generic() -> None:
    """Valid generic profile -> validation.status = valid."""
    payload = json.dumps(_VALID_GENERIC_PROFILE)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["validation"]["errors"] == []


def test_fund_profile_valid_fund_specific() -> None:
    """Valid fund-specific profile -> validation.status = valid."""
    payload = json.dumps(_VALID_FUND_SPECIFIC)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["validation"]["errors"] == []


def test_fund_profile_invalid_check_size() -> None:
    """check_size_range.min > max -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["check_size_range"] = {"min": 10000000, "max": 500000, "currency": "USD"}
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("min" in e and "max" in e for e in data["validation"]["errors"])


def test_fund_profile_wrong_archetype_count() -> None:
    """2 archetypes instead of 3 -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["archetypes"] = profile["archetypes"][:2]
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("3 archetypes" in e for e in data["validation"]["errors"])


def test_fund_profile_missing_sources_fund_specific() -> None:
    """Fund-specific mode with no sources -> validation error."""
    profile = dict(_VALID_FUND_SPECIFIC)
    profile["sources"] = []
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("sources" in e for e in data["validation"]["errors"])


def test_fund_profile_empty_thesis() -> None:
    """Empty thesis_areas -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["thesis_areas"] = []
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("thesis_areas" in e for e in data["validation"]["errors"])


def test_fund_profile_invalid_role() -> None:
    """Invalid archetype role -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["archetypes"] = [
        {"role": "dreamer", "name": "Test", "background": "Test", "focus_areas": []},
        {"role": "operator", "name": "Test", "background": "Test", "focus_areas": []},
        {"role": "analyst", "name": "Test", "background": "Test", "focus_areas": []},
    ]
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("dreamer" in e for e in data["validation"]["errors"])


def test_fund_profile_output_flag() -> None:
    """fund_profile.py with -o writes to file."""
    payload = json.dumps(_VALID_GENERIC_PROFILE)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw("fund_profile.py", ["--pretty", "-o", tmp], stdin_data=payload)
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert data["validation"]["status"] == "valid"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ============================================================
# detect_conflicts.py tests
# ============================================================


def test_conflicts_valid_no_conflicts() -> None:
    """Empty conflicts -> overall_severity = clear."""
    payload = json.dumps({"portfolio_size": 10, "conflicts": []})
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["conflict_count"] == 0
    assert data["summary"]["overall_severity"] == "clear"
    assert data["summary"]["has_blocking_conflict"] is False


def test_conflicts_valid_manageable() -> None:
    """Manageable conflict -> overall_severity = manageable."""
    payload = json.dumps(
        {
            "portfolio_size": 10,
            "conflicts": [
                {"company": "FinLedger", "type": "adjacent", "severity": "manageable", "rationale": "Related market"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["overall_severity"] == "manageable"
    assert data["summary"]["has_blocking_conflict"] is False


def test_conflicts_valid_blocking() -> None:
    """Blocking conflict -> overall_severity = blocking."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "DirectComp", "type": "direct", "severity": "blocking", "rationale": "Same market"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["overall_severity"] == "blocking"
    assert data["summary"]["has_blocking_conflict"] is True


def test_conflicts_invalid_type() -> None:
    """Invalid type enum -> validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "tangential", "severity": "manageable", "rationale": "test"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("tangential" in e for e in data["validation"]["errors"])


def test_conflicts_invalid_severity() -> None:
    """Invalid severity enum -> validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "direct", "severity": "minor", "rationale": "test"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("minor" in e for e in data["validation"]["errors"])


def test_conflicts_missing_required_fields() -> None:
    """Missing rationale -> validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "direct", "severity": "blocking"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("rationale" in e for e in data["validation"]["errors"])


def test_conflicts_portfolio_size_too_small() -> None:
    """portfolio_size < len(conflicts) -> validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 1,
            "conflicts": [
                {"company": "A", "type": "direct", "severity": "blocking", "rationale": "r1"},
                {"company": "B", "type": "adjacent", "severity": "manageable", "rationale": "r2"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("portfolio_size" in e for e in data["validation"]["errors"])


def test_conflicts_output_flag() -> None:
    """detect_conflicts.py with -o writes to file."""
    payload = json.dumps({"portfolio_size": 5, "conflicts": []})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw("detect_conflicts.py", ["--pretty", "-o", tmp], stdin_data=payload)
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert data["summary"]["overall_severity"] == "clear"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ============================================================
# compose_report.py tests
# ============================================================


def _make_artifact_dir(artifacts: dict[str, dict]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-ic-sim-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)
    return d


_VALID_STARTUP = {
    "company_name": "TestCo",
    "simulation_date": "2026-02-22",
    "stage": "seed",
    "one_liner": "Cloud accounting for SMBs",
    "sector": "Fintech",
    "geography": "United States",
    "business_model": "SaaS",
    "materials_provided": ["pitch deck"],
}

_VALID_FUND = {
    "fund_name": "Test Fund",
    "mode": "generic",
    "thesis_areas": ["B2B SaaS"],
    "check_size_range": {"min": 500000, "max": 5000000, "currency": "USD"},
    "stage_focus": ["seed"],
    "archetypes": [
        {"role": "visionary", "name": "V", "background": "b", "focus_areas": ["market"]},
        {"role": "operator", "name": "O", "background": "b", "focus_areas": ["execution"]},
        {"role": "analyst", "name": "A", "background": "b", "focus_areas": ["numbers"]},
    ],
    "portfolio": [
        {"name": "FinLedger", "sector": "Fintech", "status": "active"},
        {"name": "DataPipe", "sector": "Data", "status": "active"},
    ],
    "sources": [],
    "validation": {"status": "valid", "errors": []},
}

_VALID_CONFLICT = {
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

_VALID_DISCUSSION = {
    "assessment_mode": "sub-agent",
    "partner_verdicts": [
        {"partner": "visionary", "verdict": "invest", "rationale": "Large market, clear timing catalyst"},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Strong PMF but GTM unclear"},
        {"partner": "analyst", "verdict": "more_diligence", "rationale": "Unit economics emerging, need cohorts"},
    ],
    "debate_sections": [
        {
            "topic": "GTM Motion",
            "exchanges": [
                {"partner": "operator", "position": "Need channel economics"},
                {"partner": "visionary", "position": "Growth IS the GTM proof"},
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
            "category": "Test",
            "label": "Test",
            "status": "strong_conviction",
            "evidence": "test evidence",
            "notes": None,
        }
        for did in _DIMENSION_IDS
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
        "by_category": {},
        "dealbreakers": [],
        "top_concerns": [],
        "warnings": [],
    },
}

_VALID_PARTNER_VISIONARY = {
    "partner": "visionary",
    "verdict": "invest",
    "rationale": "Large market with clear timing",
    "conviction_points": ["Big TAM"],
    "key_concerns": [],
    "questions_for_founders": ["What's the 10-year vision?"],
    "diligence_requirements": [],
}

_VALID_PARTNER_OPERATOR = {
    "partner": "operator",
    "verdict": "more_diligence",
    "rationale": "Strong PMF but GTM unclear",
    "conviction_points": ["Good retention"],
    "key_concerns": ["No channel economics"],
    "questions_for_founders": ["Walk me through last 5 customer wins"],
    "diligence_requirements": ["Channel CAC"],
}

_VALID_PARTNER_ANALYST = {
    "partner": "analyst",
    "verdict": "more_diligence",
    "rationale": "Unit economics emerging, need cohort data",
    "conviction_points": ["Growing revenue"],
    "key_concerns": ["No cohort data"],
    "questions_for_founders": ["Show me retention curves"],
    "diligence_requirements": ["Cohort curves"],
}


def _run_compose(artifact_dir: str) -> tuple[int, dict | None, str]:
    """Run compose_report.py with given artifact dir."""
    return run_script("compose_report.py", ["--dir", artifact_dir, "--pretty"])


def _all_required_artifacts() -> dict[str, dict]:
    """Return all 5 required artifacts."""
    return {
        "startup_profile.json": _VALID_STARTUP,
        "fund_profile.json": _VALID_FUND,
        "conflict_check.json": _VALID_CONFLICT,
        "discussion.json": _VALID_DISCUSSION,
        "score_dimensions.json": _VALID_SCORE,
    }


def test_compose_complete_set() -> None:
    """All required + optional artifacts -> no missing artifact warnings, report non-empty."""
    arts = _all_required_artifacts()
    arts["prior_artifacts.json"] = {"imported": []}
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    arts["partner_assessment_analyst.json"] = _VALID_PARTNER_ANALYST
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    v = data["validation"]
    assert len(v["artifacts_missing"]) == 0
    assert len(data["report_markdown"]) > 100
    codes = [w["code"] for w in v["warnings"]]
    assert "MISSING_ARTIFACT" not in codes


def test_compose_missing_artifact() -> None:
    """Missing discussion.json -> MISSING_ARTIFACT warning."""
    arts = _all_required_artifacts()
    del arts["discussion.json"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" in codes


def test_compose_blocking_conflict() -> None:
    """Blocking conflict -> BLOCKING_CONFLICT warning."""
    arts = _all_required_artifacts()
    arts["conflict_check.json"] = {
        "portfolio_size": 5,
        "conflicts": [
            {"company": "FinLedger", "type": "direct", "severity": "blocking", "rationale": "Same market"},
        ],
        "summary": {
            "total_checked": 5,
            "conflict_count": 1,
            "has_blocking_conflict": True,
            "overall_severity": "blocking",
        },
        "validation": {"status": "valid", "errors": []},
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "BLOCKING_CONFLICT" in codes


def test_compose_orphaned_conflict() -> None:
    """Conflict company not in fund portfolio -> ORPHANED_CONFLICT."""
    arts = _all_required_artifacts()
    arts["conflict_check.json"] = {
        "portfolio_size": 2,
        "conflicts": [
            {"company": "GhostCo", "type": "direct", "severity": "manageable", "rationale": "test"},
        ],
        "summary": {
            "total_checked": 2,
            "conflict_count": 1,
            "has_blocking_conflict": False,
            "overall_severity": "manageable",
        },
        "validation": {"status": "valid", "errors": []},
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "ORPHANED_CONFLICT" in codes


def test_compose_verdict_score_mismatch() -> None:
    """Verdict 'invest' but score < 75% -> VERDICT_SCORE_MISMATCH."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["conviction_score"] = 45.0
    arts["score_dimensions.json"]["summary"]["verdict"] = "invest"
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "VERDICT_SCORE_MISMATCH" in codes


def test_compose_verdict_score_mismatch_suppressed_by_zero_applicable() -> None:
    """VERDICT_SCORE_MISMATCH suppressed when ZERO_APPLICABLE_DIMENSIONS present."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["conviction_score"] = 0.0
    arts["score_dimensions.json"]["summary"]["verdict"] = "more_diligence"
    arts["score_dimensions.json"]["summary"]["warnings"] = ["ZERO_APPLICABLE_DIMENSIONS"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "VERDICT_SCORE_MISMATCH" not in codes
    assert "ZERO_APPLICABLE" in codes


def test_compose_partner_unanimity() -> None:
    """All 3 partners same verdict + identical rationales -> PARTNER_UNANIMITY."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Great company, strong team."},
        {"partner": "operator", "verdict": "invest", "rationale": "Great company, strong team."},
        {"partner": "analyst", "verdict": "invest", "rationale": "Different analysis, solid numbers."},
    ]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "PARTNER_UNANIMITY" in codes


def test_compose_partner_convergence_sub_agent() -> None:
    """All same verdict, distinct rationales, sub-agent mode -> PARTNER_CONVERGENCE."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["assessment_mode"] = "sub-agent"
    arts["discussion.json"]["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Large market, clear timing catalyst."},
        {"partner": "operator", "verdict": "invest", "rationale": "Strong execution speed and customer love."},
        {"partner": "analyst", "verdict": "invest", "rationale": "Clean unit economics and growing revenue."},
    ]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "PARTNER_CONVERGENCE" in codes
    assert "PARTNER_UNANIMITY" not in codes


def test_compose_partner_convergence_not_emitted_sequential() -> None:
    """All same verdict, distinct rationales, sequential mode -> NO PARTNER_CONVERGENCE."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["assessment_mode"] = "sequential"
    arts["discussion.json"]["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Large market."},
        {"partner": "operator", "verdict": "invest", "rationale": "Strong execution."},
        {"partner": "analyst", "verdict": "invest", "rationale": "Clean numbers."},
    ]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "PARTNER_CONVERGENCE" not in codes


def test_compose_zero_applicable() -> None:
    """Score warnings contain ZERO_APPLICABLE_DIMENSIONS -> ZERO_APPLICABLE."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["warnings"] = ["ZERO_APPLICABLE_DIMENSIONS"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "ZERO_APPLICABLE" in codes


def test_compose_stale_import() -> None:
    """Import date > 7 days old -> STALE_IMPORT."""
    arts = _all_required_artifacts()
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    arts["prior_artifacts.json"] = {
        "imported": [
            {"source_skill": "market-sizing", "artifact_name": "sizing.json", "import_date": old_date, "summary": {}},
        ],
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_IMPORT" in codes


def test_compose_low_evidence() -> None:
    """Applicable dimension with empty evidence -> LOW_EVIDENCE."""
    arts = _all_required_artifacts()
    items = list(_VALID_SCORE["items"])
    items[0] = dict(items[0])
    items[0]["evidence"] = ""
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["items"] = items
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "LOW_EVIDENCE" in codes


def test_compose_fund_validation_error() -> None:
    """Fund validation status != valid -> FUND_VALIDATION_ERROR."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["validation"] = {"status": "invalid", "errors": ["Missing thesis areas"]}
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "FUND_VALIDATION_ERROR" in codes


def test_compose_degraded_assessment() -> None:
    """Sub-agent mode but missing partner file -> DEGRADED_ASSESSMENT."""
    arts = _all_required_artifacts()
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    # Missing partner_assessment_analyst.json
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "DEGRADED_ASSESSMENT" in codes


def test_compose_degraded_assessment_not_for_sequential() -> None:
    """Sequential mode with missing partner file -> NO DEGRADED_ASSESSMENT."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["assessment_mode"] = "sequential"
    # No partner assessment files at all
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "DEGRADED_ASSESSMENT" not in codes


def test_compose_schema_drift() -> None:
    """Artifact with unexpected key -> SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    arts["startup_profile.json"] = dict(_VALID_STARTUP)
    arts["startup_profile.json"]["unexpected_field"] = "surprise"
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" in codes


def test_compose_sequential_fallback() -> None:
    """Sequential mode -> SEQUENTIAL_FALLBACK info."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["assessment_mode"] = "sequential"
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SEQUENTIAL_FALLBACK" in codes
    # Check it's info severity
    seq_w = [w for w in data["validation"]["warnings"] if w["code"] == "SEQUENTIAL_FALLBACK"]
    assert seq_w[0]["severity"] == "info"


def test_compose_severity_map_complete() -> None:
    """WARNING_SEVERITY contains all 23 expected codes."""
    snippet = (
        f"import sys, os; sys.path.insert(0, '{IC_SIM_DIR}'); "
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
        "BLOCKING_CONFLICT",
        "ORPHANED_CONFLICT",
        "VERDICT_SCORE_MISMATCH",
        "PARTNER_UNANIMITY",
        "ZERO_APPLICABLE",
        "STALE_IMPORT",
        "LOW_EVIDENCE",
        "FUND_VALIDATION_ERROR",
        "DEGRADED_ASSESSMENT",
        "CONSENSUS_SCORE_MISMATCH",
        "UNANIMOUS_VERDICT_MISMATCH",
        "SHALLOW_ASSESSMENT",
        "HIGH_NA_COUNT",
        "SCHEMA_DRIFT",
        "STAGE_OUT_OF_SCOPE",
        "PARTNER_CONVERGENCE",
        "SEQUENTIAL_FALLBACK",
        "CONFLICT_CHECK_VALIDATION_ERROR",
        "SCORE_DIMENSIONS_VALIDATION_ERROR",
        "INCOMPLETE_PORTFOLIO_REVIEW",
        "INVALID_PARTNER_COUNT",
    ]
    assert len(sev_map) == len(expected), (
        f"expected {len(expected)} codes, got {len(sev_map)}: {sorted(sev_map.keys())}"
    )
    for code in expected:
        assert code in sev_map, f"{code} missing from severity map"

    # Verify severity levels
    assert sev_map["MISSING_ARTIFACT"] == "high"
    assert sev_map["STALE_ARTIFACT"] == "high"
    assert sev_map["BLOCKING_CONFLICT"] == "high"
    assert sev_map["ORPHANED_CONFLICT"] == "high"
    assert sev_map["VERDICT_SCORE_MISMATCH"] == "high"
    assert sev_map["PARTNER_UNANIMITY"] == "medium"
    assert sev_map["CONSENSUS_SCORE_MISMATCH"] == "medium"
    assert sev_map["UNANIMOUS_VERDICT_MISMATCH"] == "medium"
    assert sev_map["SHALLOW_ASSESSMENT"] == "medium"
    assert sev_map["HIGH_NA_COUNT"] == "medium"
    assert sev_map["SCHEMA_DRIFT"] == "low"
    assert sev_map["STAGE_OUT_OF_SCOPE"] == "low"
    assert sev_map["SEQUENTIAL_FALLBACK"] == "info"
    assert sev_map["PARTNER_CONVERGENCE"] == "info"


def test_compose_stale_artifact_mismatched_run_ids() -> None:
    """Mismatched run_id across artifacts triggers STALE_ARTIFACT warning."""
    import copy

    arts = _all_required_artifacts()
    for key in arts:
        arts[key] = copy.deepcopy(arts[key])
        arts[key]["metadata"] = {"run_id": "run-001"}
    # Stamp one artifact with a different run_id
    arts["discussion.json"]["metadata"] = {"run_id": "run-002"}  # stale!
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" in codes


def test_compose_matching_run_ids_no_stale_warning() -> None:
    """Matching run_id across all artifacts produces no STALE_ARTIFACT warning."""
    import copy

    arts = _all_required_artifacts()
    for key in arts:
        arts[key] = copy.deepcopy(arts[key])
        arts[key]["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_no_run_ids_graceful() -> None:
    """No run_id in any artifact -> graceful degradation, no STALE_ARTIFACT."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_stage_out_of_scope() -> None:
    """Stage 'series_b' -> STAGE_OUT_OF_SCOPE warning."""
    arts = _all_required_artifacts()
    startup = dict(_VALID_STARTUP)
    startup["stage"] = "series_b"
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_OUT_OF_SCOPE"]
    assert stage_w[0]["severity"] == "low"


def test_compose_stage_in_scope() -> None:
    """Stage 'seed' -> no STAGE_OUT_OF_SCOPE warning."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_report_sections() -> None:
    """Report markdown contains expected section headers."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "IC Simulation: TestCo" in report
    assert "## Executive Summary" in report
    assert "## Fund Profile" in report
    assert "## Conflict Check" in report
    assert "## Discussion Summary" in report
    assert "## Dimension Scorecard" in report
    assert "## Founder Coaching" in report


def test_compose_sub_agent_all_partner_files_clean() -> None:
    """Sub-agent mode with all partner files -> no DEGRADED_ASSESSMENT."""
    arts = _all_required_artifacts()
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    arts["partner_assessment_analyst.json"] = _VALID_PARTNER_ANALYST
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "DEGRADED_ASSESSMENT" not in codes


def test_compose_conflict_company_matches_portfolio() -> None:
    """Conflict company found in portfolio -> no ORPHANED_CONFLICT."""
    arts = _all_required_artifacts()
    arts["conflict_check.json"] = {
        "portfolio_size": 2,
        "conflicts": [
            {"company": "FinLedger", "type": "adjacent", "severity": "manageable", "rationale": "Related market"},
        ],
        "summary": {
            "total_checked": 2,
            "conflict_count": 1,
            "has_blocking_conflict": False,
            "overall_severity": "manageable",
        },
        "validation": {"status": "valid", "errors": []},
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "ORPHANED_CONFLICT" not in codes


def test_compose_low_evidence_not_applicable_excluded() -> None:
    """not_applicable items with missing evidence should NOT trigger LOW_EVIDENCE."""
    arts = _all_required_artifacts()
    items = []
    for did in _DIMENSION_IDS:
        items.append(
            {
                "id": did,
                "category": "Test",
                "label": "Test",
                "status": "not_applicable",
                "evidence": None,
                "notes": None,
            }
        )
    arts["score_dimensions.json"] = {
        "items": items,
        "summary": dict(_VALID_SCORE["summary"]),
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "LOW_EVIDENCE" not in codes


# ============================================================
# Regression tests for bug fixes and robustness gaps
# ============================================================


# -- BUG 1: compose_report check_size with non-numeric values --


def test_compose_check_size_missing_min_max() -> None:
    """Fund profile with missing min/max check_size should not crash compose."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["check_size_range"] = {"currency": "USD"}
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "?" in data["report_markdown"]


def test_compose_check_size_string_values() -> None:
    """Fund profile with string check_size values should not crash compose."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["check_size_range"] = {"min": "unknown", "max": "unknown", "currency": "USD"}
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "unknown" in data["report_markdown"]


# -- BUG 2: compose_report .title() on None partner --


def test_compose_null_partner_in_verdicts() -> None:
    """Discussion with null partner in partner_verdicts should not crash."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = {
        "assessment_mode": "sequential",
        "partner_verdicts": [
            {"partner": None, "verdict": "invest", "rationale": "Good"},
            {"partner": "operator", "verdict": "invest", "rationale": "Fine"},
            {"partner": "analyst", "verdict": "invest", "rationale": "OK"},
        ],
        "debate_sections": [
            {
                "topic": "Test",
                "exchanges": [
                    {"partner": None, "position": "test position"},
                ],
            },
        ],
        "consensus_verdict": "invest",
        "key_concerns": [],
        "diligence_requirements": [],
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "?" in data["report_markdown"]


# -- BUG 3: Empty string bypasses enum validation --


def test_fund_profile_empty_mode() -> None:
    """Empty string mode should produce validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["mode"] = ""
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("mode" in e.lower() for e in data["validation"]["errors"])


def test_conflicts_empty_type() -> None:
    """Empty string type should produce validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "", "severity": "manageable", "rationale": "test"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("type" in e.lower() for e in data["validation"]["errors"])


def test_conflicts_empty_severity() -> None:
    """Empty string severity should produce validation error."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "direct", "severity": "", "rationale": "test"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("severity" in e.lower() for e in data["validation"]["errors"])


# -- BUG 4: Float portfolio_size rejected --


def test_conflicts_float_portfolio_size() -> None:
    """Float portfolio_size like 15.0 should be accepted and coerced to int."""
    payload = json.dumps({"portfolio_size": 15.0, "conflicts": []})
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["total_checked"] == 15


# -- GAP 5: EXPECTED_KEYS too narrow for startup_profile --


def test_compose_no_schema_drift_for_common_fields() -> None:
    """startup_profile with founded/team should NOT trigger SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    startup: dict[str, Any] = dict(_VALID_STARTUP)
    startup["founded"] = "2024"
    startup["team"] = [{"name": "Alice", "role": "CEO"}]
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes


def test_compose_no_schema_drift_for_team_highlights() -> None:
    """startup_profile with team_highlights should NOT trigger SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    startup = dict(_VALID_STARTUP)
    startup["team_highlights"] = ["Former SpaceX engineer", "PhD in ML"]
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes


def test_compose_no_schema_drift_for_accepted_warnings() -> None:
    """fund_profile with accepted_warnings should NOT trigger SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["accepted_warnings"] = [
        {"code": "PARTNER_UNANIMITY", "match": "all 3", "reason": "Expected"},
    ]
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes


def test_compose_no_schema_drift_for_assessment_mode_intentional() -> None:
    """discussion with assessment_mode_intentional should NOT trigger SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["assessment_mode_intentional"] = False  # type: ignore[assignment]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes


def test_compose_schema_drift_truly_unexpected() -> None:
    """startup_profile with truly unexpected field should still trigger SCHEMA_DRIFT."""
    arts = _all_required_artifacts()
    startup = dict(_VALID_STARTUP)
    startup["zodiac_sign"] = "leo"
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" in codes


# -- GAP 6: Non-list thesis_areas/archetypes/portfolio silently passes --


def test_fund_profile_thesis_areas_string() -> None:
    """thesis_areas as string should produce validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["thesis_areas"] = "B2B SaaS"
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("thesis_areas" in e and "array" in e for e in data["validation"]["errors"])


def test_fund_profile_archetypes_string() -> None:
    """archetypes as string should produce validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["archetypes"] = "visionary, operator, analyst"
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("archetypes" in e and "array" in e for e in data["validation"]["errors"])


def test_fund_profile_portfolio_string() -> None:
    """portfolio as string should produce validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["portfolio"] = "FinLedger, DataPipe"
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("portfolio" in e and "array" in e for e in data["validation"]["errors"])


# -- GAP 7: STALE_IMPORT only handles YYYY-MM-DD --


def test_compose_stale_import_iso_datetime() -> None:
    """ISO datetime import_date should still trigger STALE_IMPORT when old."""
    arts = _all_required_artifacts()
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
    arts["prior_artifacts.json"] = {
        "imported": [
            {"source_skill": "market-sizing", "artifact_name": "sizing.json", "import_date": old_date, "summary": {}},
        ],
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_IMPORT" in codes


# -- GAP 8: score_dimensions.py fail-fast prevents multiple errors --


def test_score_multiple_errors_reported() -> None:
    """Input with unknown ID and invalid status should report both errors."""
    items = _make_dimension_items()
    items[0] = {"id": "bogus_dimension", "status": "maybe", "evidence": "test", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    errors_str = " ".join(data["validation"]["errors"]).lower()
    assert "bogus_dimension" in errors_str
    assert "maybe" in errors_str


# -- GAP 9: compose_report.py missing -o flag --


def test_score_non_dict_item() -> None:
    """Non-dict item in dimension items array -> validation error with consistent shape."""
    payload = json.dumps({"items": ["not_a_dict"]})
    rc, data, _ = run_script("score_dimensions.py", [], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("must be an object" in e for e in data["validation"]["errors"])
    assert data["items"] == []
    assert data["summary"] == {}


def test_compose_corrupt_artifact() -> None:
    """Corrupt JSON artifact -> CORRUPT_ARTIFACT warning, not MISSING_ARTIFACT."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    # Write corrupt JSON to discussion.json (overwrite)
    with open(os.path.join(d, "discussion.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes
    # discussion.json should NOT appear as MISSING_ARTIFACT
    missing_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    assert not any("discussion.json" in m for m in missing_msgs)


def test_compose_output_flag() -> None:
    """compose_report.py with -o writes JSON to file, stdout empty."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw("compose_report.py", ["--dir", d, "--pretty", "-o", tmp])
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "report_markdown" in data
        assert "validation" in data
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _run_compose_with_args(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, dict | None, str]:
    """Run compose_report.py with given artifact dir and extra args."""
    args = ["--dir", artifact_dir, "--pretty"]
    if extra_args:
        args.extend(extra_args)
    return run_script("compose_report.py", args)


def test_compose_strict_mode() -> None:
    """Missing required artifact + --strict -> exit 1 with output."""
    arts = _all_required_artifacts()
    del arts["discussion.json"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose_with_args(d, extra_args=["--strict"])
    assert rc == 1
    assert data is not None


def test_compose_strict_clean() -> None:
    """All valid artifacts + --strict -> exit 0."""
    arts = _all_required_artifacts()
    arts["prior_artifacts.json"] = {"imported": []}
    # Override consensus to match score verdict (both "invest") to avoid CONSENSUS_SCORE_MISMATCH
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "invest"
    arts["discussion.json"] = discussion
    # Use partner assessments with adequate content to avoid SHALLOW_ASSESSMENT
    _rich_partner = {
        "conviction_points": ["Point one with detail", "Point two with detail"],
        "key_concerns": ["Concern one explained", "Concern two explained"],
        "rationale": "A" * 100,
        "questions_for_founders": ["Q1"],
        "diligence_requirements": [],
    }
    arts["partner_assessment_visionary.json"] = {"partner": "visionary", "verdict": "invest", **_rich_partner}
    arts["partner_assessment_operator.json"] = {"partner": "operator", "verdict": "more_diligence", **_rich_partner}
    arts["partner_assessment_analyst.json"] = {"partner": "analyst", "verdict": "more_diligence", **_rich_partner}
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose_with_args(d, extra_args=["--strict"])
    assert rc == 0
    assert data is not None


def test_fund_profile_check_size_not_dict() -> None:
    """check_size_range as string -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["check_size_range"] = "5M"
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("object" in e.lower() for e in data["validation"]["errors"])


def test_fund_profile_empty_stage_focus() -> None:
    """Empty stage_focus -> validation error."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["stage_focus"] = []
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("stage_focus" in e for e in data["validation"]["errors"])


def test_fund_profile_source_without_url_or_title() -> None:
    """Fund-specific source without url or title -> validation error."""
    profile = dict(_VALID_FUND_SPECIFIC)
    profile["sources"] = [{}]
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("url" in e.lower() or "title" in e.lower() for e in data["validation"]["errors"])


def test_conflicts_duplicate_company_deduped() -> None:
    """Duplicate company+type in conflicts -> deduplicated with warning."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "FinLedger", "type": "direct", "severity": "blocking", "rationale": "Same market"},
                {"company": "FinLedger", "type": "direct", "severity": "manageable", "rationale": "Related"},
            ],
        }
    )
    rc, data, stderr = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert len(data["conflicts"]) == 1
    assert "duplicate" in stderr.lower()


def test_compose_orphaned_conflict_normalized() -> None:
    """Conflict 'FinLedger' vs portfolio 'FinLedger Inc.' -> no ORPHANED_CONFLICT after normalization."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["portfolio"] = [
        {"name": "FinLedger Inc.", "sector": "Fintech", "status": "active"},
        {"name": "DataPipe", "sector": "Data", "status": "active"},
    ]
    arts["fund_profile.json"] = fund
    arts["conflict_check.json"] = {
        "portfolio_size": 2,
        "conflicts": [
            {"company": "FinLedger", "type": "adjacent", "severity": "manageable", "rationale": "Related"},
        ],
        "summary": {
            "total_checked": 2,
            "conflict_count": 1,
            "has_blocking_conflict": False,
            "overall_severity": "manageable",
        },
        "validation": {"status": "valid", "errors": []},
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "ORPHANED_CONFLICT" not in codes


def test_compose_schema_drift_missing_required_key() -> None:
    """startup_profile.json without company_name -> SCHEMA_DRIFT for missing required key."""
    arts = _all_required_artifacts()
    startup = dict(_VALID_STARTUP)
    del startup["company_name"]
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" in codes
    drift_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "SCHEMA_DRIFT"]
    assert any("company_name" in m for m in drift_msgs)


def test_compose_sequential_fallback_intentional_suppressed() -> None:
    """Sequential mode with assessment_mode_intentional -> NO SEQUENTIAL_FALLBACK."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["assessment_mode"] = "sequential"
    discussion["assessment_mode_intentional"] = True  # type: ignore[assignment]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SEQUENTIAL_FALLBACK" not in codes


def test_compose_accepted_warning() -> None:
    """fund_profile with accepted_warnings -> warning severity downgraded to acknowledged."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["accepted_warnings"] = [
        {"code": "PARTNER_UNANIMITY", "reason": "Intentional convergence", "match": "all 3"},
    ]
    arts["fund_profile.json"] = fund
    # Trigger PARTNER_UNANIMITY: all 3 same verdict + identical rationales
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Great company, strong team."},
        {"partner": "operator", "verdict": "invest", "rationale": "Great company, strong team."},
        {"partner": "analyst", "verdict": "invest", "rationale": "Different analysis, solid numbers."},
    ]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    unanimity_w = [w for w in data["validation"]["warnings"] if w["code"] == "PARTNER_UNANIMITY"]
    assert len(unanimity_w) == 1
    assert unanimity_w[0]["severity"] == "acknowledged"


def test_compose_malformed_field_types() -> None:
    """Artifact with wrong field type (string instead of list) should not crash."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["items"] = "not a list"
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None


def test_conflicts_summary_null_on_error() -> None:
    """Invalid conflict -> summary is None."""
    payload = json.dumps(
        {
            "portfolio_size": 5,
            "conflicts": [
                {"company": "Test", "type": "direct", "severity": "blocking"},
            ],
        }
    )
    rc, data, _ = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert data["summary"] is None


# --- Triage #3 fixes ---


def test_conflicts_multi_type_same_company_kept() -> None:
    """Same company with different conflict types should NOT be deduped."""
    payload = json.dumps(
        {
            "portfolio_size": 10,
            "conflicts": [
                {
                    "company": "FinLedger",
                    "type": "direct",
                    "severity": "blocking",
                    "rationale": "Direct competitor",
                },
                {
                    "company": "FinLedger",
                    "type": "adjacent",
                    "severity": "manageable",
                    "rationale": "Adjacent market",
                },
            ],
        }
    )
    rc, data, stderr = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    # Both conflicts should be kept
    assert len(data["conflicts"]) == 2
    assert "duplicate" not in stderr.lower()


def test_conflicts_same_company_same_type_deduped() -> None:
    """Same company with same type should be deduped."""
    payload = json.dumps(
        {
            "portfolio_size": 10,
            "conflicts": [
                {
                    "company": "FinLedger",
                    "type": "direct",
                    "severity": "blocking",
                    "rationale": "First entry",
                },
                {
                    "company": "FinLedger",
                    "type": "direct",
                    "severity": "manageable",
                    "rationale": "Duplicate entry",
                },
            ],
        }
    )
    rc, data, stderr = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    # Should dedup to 1
    assert len(data["conflicts"]) == 1
    assert "duplicate" in stderr.lower()


def test_conflicts_normalize_company_dedup() -> None:
    """'Acme Inc.' and 'acme' with same type should dedup via normalization."""
    payload = json.dumps(
        {
            "portfolio_size": 10,
            "conflicts": [
                {
                    "company": "Acme Inc.",
                    "type": "adjacent",
                    "severity": "manageable",
                    "rationale": "First entry",
                },
                {
                    "company": "acme",
                    "type": "adjacent",
                    "severity": "manageable",
                    "rationale": "Duplicate after normalization",
                },
            ],
        }
    )
    rc, data, stderr = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert len(data["conflicts"]) == 1
    assert "duplicate" in stderr.lower()


# ---------------------------------------------------------------------------
# AI simulation disclaimer tests
# ---------------------------------------------------------------------------


def test_compose_simulation_disclaimer() -> None:
    """Report contains 'AI simulation' disclaimer text."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, data, _stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "AI simulation" in md


def test_compose_scorecard_disclaimer() -> None:
    """Report contains agent-generated scorecard disclaimer."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, data, _stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "agent" in md.lower() and "generated" in md.lower()


# ---------------------------------------------------------------------------
# Fix 1: CONSENSUS_SCORE_MISMATCH tests
# ---------------------------------------------------------------------------


def test_compose_consensus_score_mismatch() -> None:
    """Discussion consensus 'more_diligence' vs score verdict 'invest' -> CONSENSUS_SCORE_MISMATCH."""
    arts = _all_required_artifacts()
    # _VALID_DISCUSSION has consensus_verdict="more_diligence", _VALID_SCORE has verdict="invest"
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CONSENSUS_SCORE_MISMATCH" in codes


def test_compose_consensus_score_match_no_warning() -> None:
    """Discussion and score verdicts agree -> no CONSENSUS_SCORE_MISMATCH."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "invest"
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CONSENSUS_SCORE_MISMATCH" not in codes


def test_compose_executive_summary_notes_consensus_mismatch() -> None:
    """Report markdown contains mismatch note when consensus and score verdicts disagree."""
    arts = _all_required_artifacts()
    # Default fixtures have consensus=more_diligence, score=invest
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "differs from the quantitative score verdict" in md


# ---------------------------------------------------------------------------
# Fix 2: Coaching ordering test
# ---------------------------------------------------------------------------


def test_compose_coaching_includes_evidence_and_prepare() -> None:
    """Dealbreaker coaching items should include evidence and 'Prepare:' guidance."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["items"] = list(_VALID_SCORE["items"])
    # Make first item a dealbreaker with evidence
    score["items"][0] = dict(score["items"][0])
    score["items"][0]["status"] = "dealbreaker"
    score["items"][0]["evidence"] = "No founding team disclosed in materials"
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["dealbreakers"] = [
        {
            "id": "team_founder_market_fit",
            "label": "Founder-Market Fit",
            "category": "Team",
            "evidence": "No founding team disclosed in materials",
        },
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "No founding team disclosed" in md
    assert "Prepare:" in md


def test_compose_coaching_evidence_fallback_from_items() -> None:
    """When summary.dealbreakers lacks evidence, coaching falls back to items_by_id."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["items"] = list(_VALID_SCORE["items"])
    # Make first item a dealbreaker WITH evidence in the items array
    score["items"][0] = dict(score["items"][0])
    score["items"][0]["id"] = "team_founder_market_fit"
    score["items"][0]["status"] = "dealbreaker"
    score["items"][0]["evidence"] = "Founded by a solo non-technical founder"
    score["summary"] = dict(_VALID_SCORE["summary"])
    # Dealbreaker entry in summary has NO evidence (empty string)
    score["summary"]["dealbreakers"] = [
        {
            "id": "team_founder_market_fit",
            "label": "Founder-Market Fit",
            "category": "Team",
            "evidence": "",
        },
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Should have pulled evidence from items array via fallback
    assert "solo non-technical founder" in md, "Evidence from items_by_id fallback should appear in coaching"
    assert "Prepare:" in md


def test_compose_coaching_dealbreakers_before_concerns() -> None:
    """Dealbreakers appear before concerns in coaching section."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["dealbreakers"] = [
        {"id": "risk_single_point_failure", "label": "Single Point", "category": "Risk"},
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    db_pos = md.find("CRITICAL")
    concern_pos = md.find("Address this concern proactively")
    assert db_pos != -1, "Dealbreaker text not found"
    assert concern_pos != -1, "Concern text not found"
    assert db_pos < concern_pos, "Dealbreakers should appear before concerns in coaching"


# ---------------------------------------------------------------------------
# Fix 3: SHALLOW_ASSESSMENT tests
# ---------------------------------------------------------------------------


def test_compose_shallow_assessment() -> None:
    """Thin partner assessment in sub-agent mode -> SHALLOW_ASSESSMENT with file name."""
    arts = _all_required_artifacts()
    # thin: 1 conviction, 0 concerns, short rationale
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    arts["partner_assessment_analyst.json"] = _VALID_PARTNER_ANALYST
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    shallow_warnings = [w for w in data["validation"]["warnings"] if w["code"] == "SHALLOW_ASSESSMENT"]
    assert len(shallow_warnings) > 0
    # At least one should mention a partner file
    assert any("partner_assessment_" in w["message"] for w in shallow_warnings)


def test_compose_no_shallow_assessment_for_good_files() -> None:
    """Adequate partner assessments -> no SHALLOW_ASSESSMENT."""
    arts = _all_required_artifacts()
    rich = {
        "conviction_points": ["Point one with detail", "Point two with detail"],
        "key_concerns": ["Concern one explained", "Concern two explained"],
        "rationale": "A" * 100,
        "questions_for_founders": ["Q1"],
        "diligence_requirements": [],
    }
    arts["partner_assessment_visionary.json"] = {"partner": "visionary", "verdict": "invest", **rich}
    arts["partner_assessment_operator.json"] = {"partner": "operator", "verdict": "more_diligence", **rich}
    arts["partner_assessment_analyst.json"] = {"partner": "analyst", "verdict": "more_diligence", **rich}
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SHALLOW_ASSESSMENT" not in codes


def test_compose_no_shallow_assessment_sequential_mode() -> None:
    """Sequential mode with thin partner files -> no SHALLOW_ASSESSMENT (gated by sub-agent mode)."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["assessment_mode"] = "sequential"
    arts["discussion.json"] = discussion
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY  # thin
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    arts["partner_assessment_analyst.json"] = _VALID_PARTNER_ANALYST
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SHALLOW_ASSESSMENT" not in codes


# ---------------------------------------------------------------------------
# Fix 5: HIGH_NA_COUNT tests
# ---------------------------------------------------------------------------


def _make_score_with_na(na_count: int) -> dict[str, Any]:
    """Build score_dimensions with na_count N/A items, rest strong_conviction."""
    items = []
    for i, did in enumerate(_DIMENSION_IDS):
        if i < na_count:
            items.append(
                {
                    "id": did,
                    "category": "Test",
                    "label": "Test",
                    "status": "not_applicable",
                    "evidence": "N/A",
                    "notes": None,
                }
            )
        else:
            items.append(
                {
                    "id": did,
                    "category": "Test",
                    "label": "Test",
                    "status": "strong_conviction",
                    "evidence": "test evidence",
                    "notes": None,
                }
            )
    return {"items": items, "summary": dict(_VALID_SCORE["summary"])}


def test_compose_high_na_count() -> None:
    """7 N/A dimensions -> HIGH_NA_COUNT warning."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = _make_score_with_na(7)
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "HIGH_NA_COUNT" in codes
    na_w = [w for w in data["validation"]["warnings"] if w["code"] == "HIGH_NA_COUNT"]
    assert "7" in na_w[0]["message"]


def test_compose_no_high_na_count_below_threshold() -> None:
    """6 N/A dimensions -> no HIGH_NA_COUNT warning."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = _make_score_with_na(6)
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "HIGH_NA_COUNT" not in codes


# ---------------------------------------------------------------------------
# Fix 8: UNANIMOUS_VERDICT_MISMATCH tests
# ---------------------------------------------------------------------------


def test_compose_unanimous_verdict_mismatch_all_positive_negative_consensus() -> None:
    """All partners positive but consensus negative -> UNANIMOUS_VERDICT_MISMATCH."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "hard_pass"
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Great team"},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Strong signals"},
        {"partner": "analyst", "verdict": "invest", "rationale": "Good numbers"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNANIMOUS_VERDICT_MISMATCH" in codes


def test_compose_unanimous_verdict_mismatch_all_negative_positive_consensus() -> None:
    """All partners negative but consensus positive -> UNANIMOUS_VERDICT_MISMATCH."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "invest"
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "pass", "rationale": "Too early"},
        {"partner": "operator", "verdict": "hard_pass", "rationale": "No traction"},
        {"partner": "analyst", "verdict": "pass", "rationale": "Weak unit econ"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNANIMOUS_VERDICT_MISMATCH" in codes


def test_compose_no_unanimous_verdict_mismatch_with_dissent() -> None:
    """One dissenter with negative consensus -> NO warning (normal disagreement)."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "pass"
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Strong conviction"},
        {"partner": "operator", "verdict": "pass", "rationale": "Too many concerns"},
        {"partner": "analyst", "verdict": "pass", "rationale": "No financials"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNANIMOUS_VERDICT_MISMATCH" not in codes, "Single dissenter is normal IC dynamics"


def test_compose_no_unanimous_verdict_mismatch_aligned() -> None:
    """All partners and consensus aligned -> NO warning."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "more_diligence"
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Strong"},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Need data"},
        {"partner": "analyst", "verdict": "more_diligence", "rationale": "Need cohorts"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNANIMOUS_VERDICT_MISMATCH" not in codes
