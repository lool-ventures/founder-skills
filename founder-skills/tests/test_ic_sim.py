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
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IC_SIM_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts")

# Producers that require --run-id (inject metadata.run_id). Tests that do not
# care about the run_id value get a default injected so the producer contract
# (required --run-id) is satisfied without rewriting every call site.
_RUN_ID_PRODUCERS = {"fund_profile.py", "detect_conflicts.py", "score_dimensions.py"}
_DEFAULT_RUN_ID = "20260101T000000Z"


def _build_cmd(name: str, args: list[str] | None) -> list[str]:
    cmd = [sys.executable, os.path.join(IC_SIM_DIR, name)]
    args = list(args) if args else []
    if name in _RUN_ID_PRODUCERS and "--run-id" not in args:
        args = [*args, "--run-id", _DEFAULT_RUN_ID]
    cmd.extend(args)
    return cmd


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = _build_cmd(name, args)
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
    cmd = _build_cmd(name, args)
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


def test_score_dealbreaker_forces_hard_pass_fund_specific_explicit() -> None:
    """Back-compat: --fund-mode fund_specific still forces hard_pass on a dealbreaker."""
    overrides = {
        "risk_single_point_failure": {"status": "dealbreaker", "evidence": "Single customer", "notes": "fatal"},
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty", "--fund-mode", "fund_specific"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["verdict"] == "hard_pass"
    assert data["summary"]["dealbreaker_blocking"] is True


def test_score_dealbreaker_generic_mode_fund_fit_non_blocking() -> None:
    """Generic-mode dealbreaker on a FUND FIT dimension is simulated/non-blocking:
    its evidence derives from the synthesized (illustrative) fund persona, not real
    fund data, so a fabricated portfolio conflict must not invert an otherwise strong
    verdict. Merits (conviction score) drive the verdict instead."""
    overrides = {
        "fit_portfolio_conflict": {
            "status": "dealbreaker",
            "evidence": "Fabricated portfolio conflict (invented competitor in synthesized fund)",
            "notes": "simulated",
        },
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty", "--fund-mode", "generic"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["dealbreaker"] == 1
    assert data["summary"]["verdict"] != "hard_pass"
    assert data["summary"]["verdict"] == "invest"  # 27/28 strong = 96.4% conviction
    assert data["summary"]["dealbreaker_blocking"] is False
    assert "fit_portfolio_conflict" in data["summary"]["simulated_dealbreaker_ids"]
    assert "GENERIC_MODE_DEALBREAKER_NON_BLOCKING" in data["summary"]["warnings"]


def test_score_dealbreaker_generic_mode_startup_evidence_still_blocks() -> None:
    """Source-based capping (WB-2): in generic mode a dealbreaker whose evidence is
    STARTUP-side (not a Fund Fit dimension) — e.g. zero traction, no unit economics —
    is REAL and MUST still force hard_pass. Only Fund-Fit dealbreakers are simulated.
    Regression guard against the blanket 'no generic dealbreaker blocks' rule that
    would have flipped a real, absence-based hard_pass to a false pass."""
    overrides = {
        "product_traction_evidence": {
            "status": "dealbreaker",
            "evidence": "Zero traction metrics of any kind disclosed",
            "notes": "real startup-side fatal flaw",
        },
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty", "--fund-mode", "generic"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["dealbreaker"] == 1
    assert data["summary"]["verdict"] == "hard_pass"
    assert data["summary"]["dealbreaker_blocking"] is True
    assert data["summary"]["simulated_dealbreaker_ids"] == []


def test_score_generic_mode_mixed_dealbreakers_startup_blocks() -> None:
    """A realistic mixed shape: generic mode with a fabricated Fund-Fit dealbreaker
    (fit_stage_match, from an invented check-size range) AND real startup dealbreakers
    (traction, unit economics). The startup dealbreakers block -> hard_pass preserved;
    the Fund-Fit one is recorded as simulated."""
    overrides = {
        "fit_stage_match": {
            "status": "dealbreaker",
            "evidence": "$8M ask exceeds fund's $500K-$5M check-size range (invented range)",
            "notes": "fabricated fund parameter",
        },
        "product_traction_evidence": {"status": "dealbreaker", "evidence": "No traction", "notes": "real"},
        "biz_unit_economics": {"status": "dealbreaker", "evidence": "No unit economics", "notes": "real"},
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty", "--fund-mode", "generic"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["dealbreaker"] == 3
    assert data["summary"]["verdict"] == "hard_pass"  # the 2 startup dealbreakers block
    assert data["summary"]["dealbreaker_blocking"] is True
    assert data["summary"]["simulated_dealbreaker_ids"] == ["fit_stage_match"]


# ============================================================
# IC-11: to_confirm status (honest degradation of undisclosed data)
# ============================================================


def test_score_to_confirm_excluded_from_denominator() -> None:
    """IC-11: an undisclosed dimension marked `to_confirm` is EXCLUDED from the conviction
    denominator (like not_applicable), so it does NOT drag the score down the way scoring it
    `concern` did (the observed 17.3%->decline harm). 20 strong + 5 concern + 3 to_confirm:
    applicable = 28 - 3 = 25; conviction = 20/25 = 80.0 -> invest. (If to_confirm counted like
    concern, applicable would be 28 -> 71.4% -> more_diligence.)"""
    overrides: dict[str, dict[str, Any]] = {}
    for did in ("team_founder_market_fit", "team_complementary_skills", "team_execution_speed"):
        overrides[did] = {"status": "to_confirm", "evidence": "deck does not disclose", "notes": "ask founder"}
    for did in (
        "market_size_credibility",
        "market_timing",
        "market_growth_trajectory",
        "market_entry_barriers",
        "product_differentiation",
    ):
        overrides[did] = {"status": "concern", "evidence": "weak", "notes": None}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, stderr = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0, f"to_confirm must be a valid status. stderr: {stderr}"
    assert data is not None
    s = data["summary"]
    assert s["to_confirm"] == 3
    assert s["applicable"] == 25  # to_confirm excluded; concern still counted
    assert s["conviction_score"] == 80.0
    assert s["verdict"] == "invest"
    assert s.get("coverage_capped") is False


def test_score_to_confirm_high_coverage_caps_verdict() -> None:
    """IC-11 coverage guard: when too many dimensions are `to_confirm` (>6, mirroring
    HIGH_NA_COUNT), the excluded-denominator would inflate conviction to a false `invest` on a
    thin deck. Cap the verdict at `more_diligence` and flag it. 20 strong + 8 to_confirm ->
    applicable 20, conviction 100 -> would be invest -> capped to more_diligence."""
    overrides = {}
    for did in (
        "team_founder_market_fit",
        "team_complementary_skills",
        "team_execution_speed",
        "team_coachability",
        "market_size_credibility",
        "market_timing",
        "market_growth_trajectory",
        "market_entry_barriers",
    ):
        overrides[did] = {"status": "to_confirm", "evidence": "deck does not disclose", "notes": None}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["to_confirm"] == 8
    assert s["conviction_score"] == 100.0  # the score itself is unchanged
    assert s["verdict"] == "more_diligence"  # capped, NOT invest
    assert s.get("coverage_capped") is True
    assert "LOW_COVERAGE_VERDICT_CAP" in s["warnings"]


def test_score_to_confirm_category_counter_no_keyerror() -> None:
    """A to_confirm status must not KeyError the per-category counter, and must appear in
    by_category so it isn't silently dropped from the report."""
    overrides = {"team_founder_market_fit": {"status": "to_confirm", "evidence": "n/a", "notes": None}}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["by_category"]["Team"]["to_confirm"] == 1


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
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("missing" in e.lower() for e in data["validation"]["errors"])


def test_score_duplicate_id() -> None:
    """Duplicate ID -> validation.status = invalid."""
    items = _make_dimension_items()
    items.append({"id": "team_founder_market_fit", "status": "strong_conviction", "evidence": "dup", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("duplicate" in e.lower() for e in data["validation"]["errors"])


def test_score_unknown_id() -> None:
    """Unknown ID -> validation.status = invalid."""
    items = _make_dimension_items()
    items[0] = {"id": "bogus_dimension", "status": "strong_conviction", "evidence": "test", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("bogus_dimension" in e.lower() for e in data["validation"]["errors"])


def test_score_invalid_status() -> None:
    """Invalid status -> validation.status = invalid."""
    overrides = {"team_founder_market_fit": {"status": "maybe", "evidence": "test", "notes": None}}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
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


def test_fund_profile_generic_portfolio_optional() -> None:
    """Generic mode does not require a portfolio — a synthesized fund has no real
    holdings, and forcing the field manufactures a fabricated portfolio (and with
    it, fabricated conflicts). fund_specific mode still requires it (real fund,
    real holdings)."""
    profile = dict(_VALID_GENERIC_PROFILE)
    del profile["portfolio"]
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["validation"]["errors"] == []


def test_fund_profile_specific_portfolio_still_required() -> None:
    """Back-compat: fund_specific mode still requires portfolio."""
    profile = dict(_VALID_FUND_SPECIFIC)
    del profile["portfolio"]
    payload = json.dumps(profile)
    rc, data, _ = run_script("fund_profile.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert any("portfolio" in e for e in data["validation"]["errors"])


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


def test_detect_conflicts_generic_stub_schema_parity() -> None:
    """--generic-stub emits the schema-valid, run_id-stamped 'clear' result for a
    synthesized (illustrative) fund that has no real holdings. A portfolio-conflict
    analysis against invented companies is circular, so generic mode skips the
    sub-agent and produces this deterministic stub instead. It must be byte-for-byte
    schema-compatible with the piped path: portfolio_size 0, empty conflicts, clear
    summary, valid status, metadata.run_id present."""
    rc, data, _ = run_script("detect_conflicts.py", ["--generic-stub", "--pretty"])
    assert rc == 0
    assert data is not None
    assert data["portfolio_size"] == 0
    assert data["conflicts"] == []
    assert data["summary"]["conflict_count"] == 0
    assert data["summary"]["has_blocking_conflict"] is False
    assert data["summary"]["overall_severity"] == "clear"
    assert data["validation"]["status"] == "valid"
    assert data["validation"]["errors"] == []
    assert data["metadata"] == {"run_id": _DEFAULT_RUN_ID}


def test_detect_conflicts_generic_stub_ignores_stdin() -> None:
    """--generic-stub must bypass BOTH the isatty gate and json.load(stdin): it
    reads no input at all, so even garbage on stdin is ignored (proves the stub
    short-circuits before the stdin machinery)."""
    rc, data, _ = run_script(
        "detect_conflicts.py",
        ["--generic-stub", "--pretty"],
        stdin_data="this is not valid json {{{",
    )
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["overall_severity"] == "clear"


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
    # Empty because this fixture's debate raised no dealbreakers. Present-and-empty
    # is a different state from absent: absent means the id-level channel does not
    # exist and no dealbreaker can be attributed at all.
    "debated_dealbreakers": [],
    "key_concerns": ["GTM unclear", "Need cohort data"],
    "diligence_requirements": ["Channel CAC", "Cohort curves"],
    "warnings": [],
    "_produced_by": "compose_discussion",
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

# ============================================================
# compose_discussion.py tests
# ============================================================

_VALID_REBUTTAL_VISIONARY = {
    "partner": "visionary",
    "revised_verdict": "invest",
    "verdict_changed": False,
    "changed_because": "",
    "responses": [
        {"to": "operator", "point": "Growth IS the GTM proof at this stage", "concedes": False},
        {"to": "analyst", "point": "Unit economics will follow scale", "concedes": False},
    ],
    "dealbreakers": [],
    "diligence_requirements": ["10-year vision doc"],
}

_VALID_REBUTTAL_OPERATOR = {
    "partner": "operator",
    "revised_verdict": "more_diligence",
    "verdict_changed": False,
    "changed_because": "",
    "responses": [
        {"to": "visionary", "point": "Need channel-level economics before calling it proof", "concedes": False},
        {"to": "analyst", "point": "Agreed on cohort data", "concedes": True},
    ],
    "dealbreakers": [],
    "diligence_requirements": ["Channel CAC"],
}

_VALID_REBUTTAL_ANALYST = {
    "partner": "analyst",
    "revised_verdict": "more_diligence",
    "verdict_changed": False,
    "changed_because": "",
    "responses": [
        {"to": "visionary", "point": "Vision doesn't substitute for unit economics", "concedes": False},
        {"to": "operator", "point": "Cohort data would help confirm this", "concedes": False},
    ],
    "dealbreakers": [],
    "diligence_requirements": ["Cohort curves"],
}


def _make_discussion_dir(
    assessments: dict[str, dict] | None = None,
    rebuttals: dict[str, dict] | None = None,
    *,
    omit_rebuttals: list[str] | None = None,
) -> str:
    """Build a temp dir with the 3 round-1 assessments + 3 round-2 rebuttals
    compose_discussion.py reads via --dir. `omit_rebuttals` drops named
    archetypes' rebuttal files entirely (for missing-artifact tests)."""
    assessments = (
        assessments
        if assessments is not None
        else {
            "visionary": _VALID_PARTNER_VISIONARY,
            "operator": _VALID_PARTNER_OPERATOR,
            "analyst": _VALID_PARTNER_ANALYST,
        }
    )
    rebuttals = (
        rebuttals
        if rebuttals is not None
        else {
            "visionary": _VALID_REBUTTAL_VISIONARY,
            "operator": _VALID_REBUTTAL_OPERATOR,
            "analyst": _VALID_REBUTTAL_ANALYST,
        }
    )
    omit_rebuttals = omit_rebuttals or []
    artifacts: dict[str, dict] = {}
    for archetype, data in assessments.items():
        artifacts[f"partner_assessment_{archetype}.json"] = data
    for archetype, data in rebuttals.items():
        if archetype in omit_rebuttals:
            continue
        artifacts[f"partner_rebuttal_{archetype}.json"] = data
    return _make_artifact_dir(artifacts)


def _run_compose_discussion(
    artifact_dir: str, run_id: str = _DEFAULT_RUN_ID, extra_args: list[str] | None = None
) -> tuple[int, dict | None, str]:
    args = ["--dir", artifact_dir, "--run-id", run_id, "--pretty", *(extra_args or [])]
    return run_script("compose_discussion.py", args)


def test_compose_discussion_valid_majority_consensus() -> None:
    """Two of three revised verdicts agree ('more_diligence') -> that value
    wins as consensus_verdict, even though the third ('invest') dissents."""
    d = _make_discussion_dir()
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["consensus_verdict"] == "more_diligence"
    assert data["assessment_mode"] == "sub-agent"
    assert data["_produced_by"] == "compose_discussion"
    assert data["metadata"] == {"run_id": _DEFAULT_RUN_ID}
    assert data["warnings"] == []

    verdicts = {pv["partner"]: pv["verdict"] for pv in data["partner_verdicts"]}
    assert verdicts == {"visionary": "invest", "operator": "more_diligence", "analyst": "more_diligence"}


def test_compose_discussion_no_majority_defaults_more_diligence() -> None:
    """All three revised verdicts distinct -> no majority -> more_diligence,
    never an invented tiebreak."""
    rebuttals = {
        "visionary": {**_VALID_REBUTTAL_VISIONARY, "revised_verdict": "invest"},
        "operator": {**_VALID_REBUTTAL_OPERATOR, "revised_verdict": "pass"},
        "analyst": {**_VALID_REBUTTAL_ANALYST, "revised_verdict": "hard_pass"},
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["consensus_verdict"] == "more_diligence"


def test_compose_discussion_unanimous_consensus() -> None:
    """All three agree -> that value is the consensus, trivially a majority."""
    rebuttals = {
        "visionary": {**_VALID_REBUTTAL_VISIONARY, "revised_verdict": "invest"},
        "operator": {**_VALID_REBUTTAL_OPERATOR, "revised_verdict": "invest"},
        "analyst": {**_VALID_REBUTTAL_ANALYST, "revised_verdict": "invest"},
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["consensus_verdict"] == "invest"


def test_compose_discussion_missing_rebuttal_rejected() -> None:
    """A missing rebuttal file for one archetype -> exit 1, named in the diagnostic."""
    d = _make_discussion_dir(omit_rebuttals=["analyst"])
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert data["error"] == "invalid_rebuttal_round"
    assert any("missing rebuttal for archetype: 'analyst'" in e for e in data["errors"])
    # Nothing is written to disk on rejection.
    assert not os.path.exists(os.path.join(d, "discussion.json"))


def test_compose_discussion_verdict_changed_without_reason_rejected() -> None:
    """verdict_changed: true with an empty changed_because is rejected — the
    fix this whole round-2 architecture exists to enforce."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {**_VALID_REBUTTAL_OPERATOR, "verdict_changed": True, "changed_because": ""},
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert any("changed_because is empty" in e for e in data["errors"])


def test_compose_discussion_invalid_revised_verdict_rejected() -> None:
    """A revised_verdict outside the four-value enum is rejected."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {**_VALID_REBUTTAL_OPERATOR, "revised_verdict": "strongly_invest"},
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert any("revised_verdict" in e and "strongly_invest" in e for e in data["errors"])


def test_compose_discussion_dealbreaker_missing_evidence_rejected() -> None:
    """A dealbreaker with empty evidence is rejected — round-1 assessments have
    no dealbreakers field at all, so every rebuttal dealbreaker is new and must
    be evidence-backed."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {
            **_VALID_REBUTTAL_OPERATOR,
            "dealbreakers": [{"dimension": "team_founder_market_fit", "reason": "no domain expertise", "evidence": ""}],
        },
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert any("dealbreakers[0] has no evidence" in e for e in data["errors"])


def test_compose_discussion_dealbreaker_invalid_dimension_id_rejected() -> None:
    """A dealbreaker citing a dimension id outside score_dimensions.py's 28
    canonical ids is rejected — imported, never hardcoded."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {
            **_VALID_REBUTTAL_OPERATOR,
            "dealbreakers": [{"dimension": "not_a_real_dimension", "reason": "x", "evidence": "y"}],
        },
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert any("not a recognized dimension id" in e for e in data["errors"])


def test_compose_discussion_duplicate_archetype_among_rebuttals_rejected() -> None:
    """A rebuttal file whose internal 'partner' field claims an archetype
    another file already claimed is rejected as a duplicate, and the archetype
    whose slot never got filled is separately reported missing."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        # This file lives at partner_rebuttal_operator.json but internally
        # claims to be 'analyst' — the same archetype partner_rebuttal_analyst.json
        # also claims.
        "operator": {**_VALID_REBUTTAL_OPERATOR, "partner": "analyst"},
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 1, f"stderr={err}"
    assert data is not None
    assert any("duplicate archetype among rebuttals: 'analyst'" in e for e in data["errors"])
    assert any("missing rebuttal for archetype: 'operator'" in e for e in data["errors"])


def test_compose_discussion_capitulation_warning_fires() -> None:
    """>= 2 of 3 verdicts changed and converged on the same value ->
    POSSIBLE_CAPITULATION, uncalibrated and non-blocking (rc still 0)."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,  # unchanged, stays 'invest'
        "operator": {
            **_VALID_REBUTTAL_OPERATOR,
            "revised_verdict": "invest",
            "verdict_changed": True,
            "changed_because": "The growth number is enough evidence for me now",
        },
        "analyst": {
            **_VALID_REBUTTAL_ANALYST,
            "revised_verdict": "invest",
            "verdict_changed": True,
            "changed_because": "Convinced by the other two",
        },
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert "POSSIBLE_CAPITULATION" in data["warnings"]
    # Uncalibrated and non-blocking: it neither changes consensus_verdict nor rc.
    assert data["consensus_verdict"] == "invest"


def test_compose_discussion_no_capitulation_warning_single_change() -> None:
    """Only ONE verdict changed -> the capitulation signal does not fire (it
    requires >= 2 changed AND converged)."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {
            **_VALID_REBUTTAL_OPERATOR,
            "revised_verdict": "invest",
            "verdict_changed": True,
            "changed_because": "New evidence changed my mind",
        },
        "analyst": _VALID_REBUTTAL_ANALYST,  # unchanged
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["warnings"] == []


def test_compose_discussion_no_capitulation_warning_diverging_changes() -> None:
    """Two verdicts changed but landed on DIFFERENT values -> not a
    convergence, so no capitulation signal."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": {
            **_VALID_REBUTTAL_OPERATOR,
            "revised_verdict": "invest",
            "verdict_changed": True,
            "changed_because": "New evidence A",
        },
        "analyst": {
            **_VALID_REBUTTAL_ANALYST,
            "revised_verdict": "pass",
            "verdict_changed": True,
            "changed_because": "New evidence B",
        },
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["warnings"] == []


def test_compose_discussion_debate_sections_grouped_by_target_in_canonical_order() -> None:
    """debate_sections group each rebuttal's responses by the archetype being
    addressed, in canonical archetype order (visionary, operator, analyst) —
    NOT the order responses happen to be written in."""
    d = _make_discussion_dir()
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    topics = [s["topic"] for s in data["debate_sections"]]
    assert topics == ["Responses to Visionary", "Responses to Operator", "Responses to Analyst"]

    to_visionary = next(s for s in data["debate_sections"] if s["topic"] == "Responses to Visionary")
    speakers = {e["partner"] for e in to_visionary["exchanges"]}
    assert speakers == {"operator", "analyst"}

    to_analyst = next(s for s in data["debate_sections"] if s["topic"] == "Responses to Analyst")
    conceding = next(e for e in to_analyst["exchanges"] if e["partner"] == "operator")
    assert conceding["position"].endswith("(concedes this point)")


def test_compose_discussion_diligence_requirements_union_across_rebuttals() -> None:
    """diligence_requirements is the union of the 3 rebuttals' lists, not
    round-1's — this is what visualize.py's Key Findings 'actions' reads."""
    d = _make_discussion_dir()
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert data["diligence_requirements"] == ["10-year vision doc", "Channel CAC", "Cohort curves"]


def test_compose_discussion_key_concerns_union_of_assessments_and_dealbreaker_reasons() -> None:
    """key_concerns unions round-1 key_concerns with round-2 dealbreaker reasons."""
    rebuttals = {
        "visionary": _VALID_REBUTTAL_VISIONARY,
        "operator": _VALID_REBUTTAL_OPERATOR,
        "analyst": {
            **_VALID_REBUTTAL_ANALYST,
            "dealbreakers": [
                {
                    "dimension": "biz_unit_economics",
                    "reason": "Negative unit economics with no path",
                    "evidence": "See financials",
                }
            ],
        },
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    assert "No channel economics" in data["key_concerns"]
    assert "No cohort data" in data["key_concerns"]
    assert "Negative unit economics with no path" in data["key_concerns"]


def test_compose_discussion_debated_dealbreakers_preserve_dimension_ids() -> None:
    """key_concerns keeps only the prose reason, so it cannot answer 'was this
    dimension argued?'. debated_dealbreakers is the id-level channel that can."""
    reb_op = json.loads(json.dumps(_VALID_REBUTTAL_OPERATOR))
    reb_op["dealbreakers"] = [
        {"dimension": "biz_unit_economics", "evidence": "CAC payback 65 months", "reason": "Economics are upside down"}
    ]
    reb_an = json.loads(json.dumps(_VALID_REBUTTAL_ANALYST))
    reb_an["dealbreakers"] = [
        {"dimension": "biz_unit_economics", "evidence": "LTV/CAC 0.6x", "reason": "Economics are upside down"},
        {"dimension": "risk_regulatory", "evidence": "PHI processed with no BAA", "reason": "Active HIPAA violation"},
    ]
    d = _make_discussion_dir(rebuttals={"visionary": _VALID_REBUTTAL_VISIONARY, "operator": reb_op, "analyst": reb_an})
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, err
    assert data is not None
    debated = data["debated_dealbreakers"]
    by_dim = {e["dimension"]: e for e in debated}
    # Deduped by dimension, not one entry per (partner, dimension) pair.
    assert sorted(by_dim) == ["biz_unit_economics", "risk_regulatory"]
    # raised_by accumulates every partner who argued it, in canonical order.
    assert by_dim["biz_unit_economics"]["raised_by"] == ["operator", "analyst"]
    assert by_dim["risk_regulatory"]["raised_by"] == ["analyst"]
    # Both partners' distinct evidence survives — neither overwrites the other.
    assert by_dim["biz_unit_economics"]["evidence"] == ["CAC payback 65 months", "LTV/CAC 0.6x"]


def test_compose_discussion_debated_dealbreakers_empty_when_none_raised() -> None:
    """Present-and-empty, never absent — absence means 'no channel', which
    compose_report.py treats as unverifiable rather than as 'none debated'."""
    d = _make_discussion_dir()
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, err
    assert data is not None
    assert data["debated_dealbreakers"] == []


def test_compose_discussion_output_flag() -> None:
    """-o writes discussion.json to file and prints a small receipt."""
    d = _make_discussion_dir()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, err = run_script_raw(
            "compose_discussion.py", ["--dir", d, "--run-id", _DEFAULT_RUN_ID, "--pretty", "-o", tmp]
        )
        assert rc == 0, f"stderr={err}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            written = json.load(fh)
        assert written["consensus_verdict"] == "more_diligence"
        assert written["_produced_by"] == "compose_discussion"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_compose_discussion_run_id_required() -> None:
    """compose_discussion.py exits non-zero when --run-id is omitted."""
    d = _make_discussion_dir()
    rc, _stdout, err = run_script_raw("compose_discussion.py", ["--dir", d, "--pretty"])
    assert rc != 0
    assert "run-id" in err.lower() or "run_id" in err.lower()


def test_compose_discussion_rejects_missing_directory() -> None:
    """A nonexistent --dir exits non-zero with a plain stderr message (no
    JSON diagnostic — this is a shell-level usage error, not a content
    rejection)."""
    rc, stdout, err = run_script_raw(
        "compose_discussion.py", ["--dir", "/nonexistent/ic-sim-dir-xyz", "--run-id", _DEFAULT_RUN_ID]
    )
    assert rc != 0
    assert stdout.strip() == ""
    assert "not found" in err.lower() or "directory" in err.lower()


def test_compose_discussion_malformed_response_entry_skipped_not_errored() -> None:
    """A response entry missing 'point', or targeting an unrecognized archetype,
    is silently dropped from debate_sections rather than rejecting the whole
    rebuttal round — only the 5 documented reject conditions are hard failures."""
    rebuttals = {
        "visionary": {
            **_VALID_REBUTTAL_VISIONARY,
            "responses": [
                {"to": "operator", "point": "", "concedes": False},  # empty point -> dropped
                {"to": "nobody", "point": "stray", "concedes": False},  # bad target -> dropped
                {"to": "analyst", "point": "Unit economics will follow scale", "concedes": False},
            ],
        },
        "operator": _VALID_REBUTTAL_OPERATOR,
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    to_analyst = next(s for s in data["debate_sections"] if s["topic"] == "Responses to Analyst")
    visionary_positions = [e["position"] for e in to_analyst["exchanges"] if e["partner"] == "visionary"]
    assert visionary_positions == ["Unit economics will follow scale"]


def test_compose_discussion_dropped_responses_emit_warning() -> None:
    """Dropping a response entry (empty point, unrecognized target, or a
    non-object entry) is not a hard-reject condition, but it must not be
    silent either — a DROPPED_REBUTTAL_RESPONSES warning names the count and
    the reasons so a failed round-two exchange is distinguishable from a
    genuinely one-sided debate. Non-blocking: rc stays 0, consensus_verdict
    is unaffected."""
    rebuttals = {
        "visionary": {
            **_VALID_REBUTTAL_VISIONARY,
            "responses": [
                {"to": "operator", "point": "", "concedes": False},  # empty point -> dropped
                {"to": "nobody", "point": "stray", "concedes": False},  # bad target -> dropped
                "not-an-object",  # malformed entry -> dropped
                {"to": "analyst", "point": "Unit economics will follow scale", "concedes": False},
            ],
        },
        "operator": _VALID_REBUTTAL_OPERATOR,
        "analyst": _VALID_REBUTTAL_ANALYST,
    }
    d = _make_discussion_dir(rebuttals=rebuttals)
    rc, data, err = _run_compose_discussion(d)
    assert rc == 0, f"stderr={err}"
    assert data is not None
    warnings = data["warnings"]
    assert len(warnings) == 1
    assert warnings[0].startswith("DROPPED_REBUTTAL_RESPONSES: 3 response entries dropped")
    assert "empty_point=1" in warnings[0]
    assert "unrecognized_target=1" in warnings[0]
    assert "entry_not_object=1" in warnings[0]


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


# ------------------------------------------------------------------
# Dealbreaker provenance — debate vs scoring pass.
#
# Scoring runs after the debate, over all 28 dimensions, and nothing but a
# sentence in the SCORE_DIMENSIONS dispatch ties the two together. A measured
# live run scored 4 dealbreakers against 3 the debate raised, and the report
# narrated all four as "independent fatal flaws". These lock in DISCLOSURE, not
# suppression: an undebated dealbreaker stays in the report and still forces
# hard_pass, it is just labelled for what it is.
# ------------------------------------------------------------------


def _score_with_dealbreakers(ids: list[str]) -> dict[str, Any]:
    """A score_dimensions.json body whose named dimensions are dealbreakers."""
    score = json.loads(json.dumps(_VALID_SCORE))
    for item in score["items"]:
        if item["id"] in ids:
            item["status"] = "dealbreaker"
            item["evidence"] = f"evidence for {item['id']}"
    score["summary"] = dict(score.get("summary", {}))
    score["summary"]["dealbreakers"] = [
        {
            "id": i,
            "category": "Risk",
            "label": i.replace("_", " ").title(),
            "evidence": f"evidence for {i}",
            "notes": None,
        }
        for i in ids
    ]
    typed_score: dict[str, Any] = score
    return typed_score


def _debated(dimension: str, raised_by: list[str]) -> dict[str, Any]:
    return {"dimension": dimension, "raised_by": raised_by, "evidence": [f"{dimension} is fatal"]}


def test_compose_undebated_dealbreaker_is_disclosed() -> None:
    """A dealbreaker the scoring pass produced but no partner argued -> named in
    UNDEBATED_DEALBREAKER and labelled as scoring-only in the report body."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["debated_dealbreakers"] = [_debated("risk_regulatory", ["analyst"])]
    arts["discussion.json"] = discussion
    arts["score_dimensions.json"] = _score_with_dealbreakers(["risk_regulatory", "risk_single_point_failure"])
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warnings = {w["code"]: w["message"] for w in data["validation"]["warnings"]}
    assert "UNDEBATED_DEALBREAKER" in warnings
    assert "risk_single_point_failure" in warnings["UNDEBATED_DEALBREAKER"]
    # The debated one must NOT be named as undebated.
    assert "risk_regulatory" not in warnings["UNDEBATED_DEALBREAKER"]
    md = data["report_markdown"]
    assert "no partner raised this as a dealbreaker in the debate" in md
    assert "Raised as a dealbreaker in the debate by: Analyst." in md


def test_compose_undebated_dealbreaker_is_not_suppressed() -> None:
    """Disclosure must not drop the finding: the undebated dealbreaker still
    appears in the report. Suppressing it would hide a fatal flaw."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["debated_dealbreakers"] = []
    arts["discussion.json"] = discussion
    arts["score_dimensions.json"] = _score_with_dealbreakers(["risk_single_point_failure"])
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "Risk Single Point Failure" in data["report_markdown"]
    # LOW severity — an undebated dealbreaker is an expected outcome, not an
    # integrity violation, and must never gate the report.
    sev = [w["severity"] for w in data["validation"]["warnings"] if w["code"] == "UNDEBATED_DEALBREAKER"]
    assert sev == ["low"]


def test_compose_fully_debated_dealbreakers_raise_no_warning() -> None:
    """Every scored dealbreaker traced to the debate -> no provenance warning."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["debated_dealbreakers"] = [
        _debated("risk_regulatory", ["analyst", "operator"]),
        _debated("biz_unit_economics", ["operator"]),
    ]
    arts["discussion.json"] = discussion
    arts["score_dimensions.json"] = _score_with_dealbreakers(["risk_regulatory", "biz_unit_economics"])
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNDEBATED_DEALBREAKER" not in codes
    assert "DEALBREAKER_PROVENANCE_UNVERIFIABLE" not in codes
    assert "Raised as a dealbreaker in the debate by: Analyst, Operator." in data["report_markdown"]


def test_compose_missing_provenance_channel_is_not_read_as_all_debated() -> None:
    """A discussion.json with NO debated_dealbreakers key cannot be compared.
    That must surface as its own warning, never as silence."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    del discussion["debated_dealbreakers"]
    arts["discussion.json"] = discussion
    arts["score_dimensions.json"] = _score_with_dealbreakers(["risk_regulatory"])
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "DEALBREAKER_PROVENANCE_UNVERIFIABLE" in codes
    assert "UNDEBATED_DEALBREAKER" not in codes
    assert "could not be traced to the partner debate" in data["report_markdown"]


def test_dealbreaker_provenance_unverifiable_founder_message_does_not_overclaim() -> None:
    """The trigger includes a by-design case (an older-format discussion.json with
    no 'debated_dealbreakers' key at all) -- the founder_message must not tell the
    founder to distrust every dealbreaker, only that provenance can't be shown.
    """
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    del discussion["debated_dealbreakers"]
    arts["discussion.json"] = discussion
    arts["score_dimensions.json"] = _score_with_dealbreakers(["risk_regulatory"])
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "DEALBREAKER_PROVENANCE_UNVERIFIABLE")
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    assert "discussion.json" not in founder_msg
    assert "Treat every dealbreaker" not in founder_msg, "must not overclaim distrust of every dealbreaker"
    assert founder_msg in data["report_markdown"]


def test_compose_no_dealbreakers_raises_no_provenance_warning() -> None:
    """No scored dealbreakers -> nothing to attribute, no warning either way."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNDEBATED_DEALBREAKER" not in codes
    assert "DEALBREAKER_PROVENANCE_UNVERIFIABLE" not in codes


def test_compose_unvalidated_discussion_missing_produced_by() -> None:
    """A discussion.json with no _produced_by stamp at all -> UNVALIDATED_ARTIFACT.
    This is exactly the hand-written-discussion.json failure mode compose_discussion.py
    now exists to close off."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    del discussion["_produced_by"]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNVALIDATED_ARTIFACT" in codes


def test_compose_unvalidated_discussion_wrong_produced_by() -> None:
    """A discussion.json stamped by a different producer (or hand-authored with
    a fabricated stamp) is caught the same as a missing stamp."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["_produced_by"] = "main_thread_heredoc"
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNVALIDATED_ARTIFACT" in codes


def test_compose_validated_discussion_no_unvalidated_warning() -> None:
    """A discussion.json correctly stamped by compose_discussion.py never
    trips UNVALIDATED_ARTIFACT (no false positive on the real pipeline output)."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNVALIDATED_ARTIFACT" not in codes


def test_compose_partner_capitulation_warning_surfaced() -> None:
    """discussion.json's warnings: ["POSSIBLE_CAPITULATION"] surfaces as a
    low-severity PARTNER_CAPITULATION warning in the composed report — never
    gating (status stays 'warnings', not an error; rc stays 0)."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["warnings"] = ["POSSIBLE_CAPITULATION"]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warnings_by_code = {w["code"]: w for w in data["validation"]["warnings"]}
    assert "PARTNER_CAPITULATION" in warnings_by_code
    assert warnings_by_code["PARTNER_CAPITULATION"]["severity"] == "low"


def test_compose_no_partner_capitulation_warning_when_absent() -> None:
    """An empty discussion.json warnings list (the normal case) never emits
    PARTNER_CAPITULATION."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "PARTNER_CAPITULATION" not in codes


def test_compose_report_unanimous_check_documented_as_near_dormant() -> None:
    """The UNANIMOUS_VERDICT_MISMATCH check must carry a comment explaining it
    is now structurally near-unfireable against a real, producer-derived
    discussion.json (consensus_verdict is a majority vote over partner_verdicts
    itself) so a future reader doesn't mistake a quiet run for a broken check."""
    with open(os.path.join(IC_SIM_DIR, "compose_report.py"), encoding="utf-8") as f:
        text = f.read()
    idx = text.index("# 4c. UNANIMOUS_VERDICT_MISMATCH")
    section = text[idx : idx + 1200]
    assert "DORMANT" in section or "near-impossible" in section or "near-unfireable" in section


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


def test_compose_verdict_score_mismatch_suppressed_by_coverage_cap() -> None:
    """IC-11: a coverage-capped verdict (more_diligence at an invest-band conviction, because too
    many dimensions are to_confirm) is INTENTIONAL — compose must NOT flag VERDICT_SCORE_MISMATCH,
    and must surface a LOW_COVERAGE_VERDICT_CAP warning so the founder knows why."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["conviction_score"] = 100.0
    arts["score_dimensions.json"]["summary"]["verdict"] = "more_diligence"
    arts["score_dimensions.json"]["summary"]["coverage_capped"] = True
    arts["score_dimensions.json"]["summary"]["to_confirm"] = 8
    arts["score_dimensions.json"]["summary"]["warnings"] = ["LOW_COVERAGE_VERDICT_CAP"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "VERDICT_SCORE_MISMATCH" not in codes
    assert "LOW_COVERAGE_VERDICT_CAP" in codes


def test_low_coverage_verdict_cap_founder_message_reaches_report_md() -> None:
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["conviction_score"] = 100.0
    arts["score_dimensions.json"]["summary"]["verdict"] = "more_diligence"
    arts["score_dimensions.json"]["summary"]["coverage_capped"] = True
    arts["score_dimensions.json"]["summary"]["to_confirm"] = 8
    arts["score_dimensions.json"]["summary"]["warnings"] = ["LOW_COVERAGE_VERDICT_CAP"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "LOW_COVERAGE_VERDICT_CAP")
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    assert "to_confirm" not in founder_msg
    assert founder_msg in data["report_markdown"]


def test_low_coverage_verdict_floor_founder_message_reaches_report_md() -> None:
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["conviction_score"] = 30.0
    arts["score_dimensions.json"]["summary"]["verdict"] = "more_diligence"
    arts["score_dimensions.json"]["summary"]["coverage_floored"] = True
    arts["score_dimensions.json"]["summary"]["to_confirm"] = 20
    arts["score_dimensions.json"]["summary"]["warnings"] = ["LOW_COVERAGE_VERDICT_FLOOR"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "LOW_COVERAGE_VERDICT_FLOOR")
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    assert "to_confirm" not in founder_msg
    assert founder_msg in data["report_markdown"]


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


def test_zero_applicable_founder_message_reaches_report_md() -> None:
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = dict(_VALID_SCORE)
    arts["score_dimensions.json"]["summary"] = dict(_VALID_SCORE["summary"])
    arts["score_dimensions.json"]["summary"]["warnings"] = ["ZERO_APPLICABLE_DIMENSIONS"]
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "ZERO_APPLICABLE")
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    assert "not_applicable" not in founder_msg
    assert founder_msg in data["report_markdown"]


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
    """WARNING_SEVERITY contains all expected codes (kept in sync with the list below)."""
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
        "FOUNDER_TEXT_TOKEN",
        # A producer rejected its input, so the artifact carries no analysis.
        "ARTIFACT_INVALID",
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
        "MARKER_COLLISION",
        "LOW_COVERAGE_VERDICT_CAP",
        "LOW_COVERAGE_VERDICT_FLOOR",
        "LOW_CONVICTION_BASIS",
        "LOW_COVERAGE_VERDICT_HELD",
        "UNVALIDATED_ARTIFACT",
        "PARTNER_CAPITULATION",
        "UNDEBATED_DEALBREAKER",
        "DEALBREAKER_PROVENANCE_UNVERIFIABLE",
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
    assert sev_map["MARKER_COLLISION"] == "low"
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
    assert "## Founder Coaching" not in report


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


def test_compose_no_schema_drift_generic_fund_without_portfolio() -> None:
    """A generic-mode fund profile with no portfolio (optional per fund_profile.py)
    must not self-flag a missing-required-key SCHEMA_DRIFT warning."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["mode"] = "generic"
    del fund["portfolio"]
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    drift_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "SCHEMA_DRIFT"]
    assert not any("portfolio" in m for m in drift_msgs), drift_msgs


def test_compose_generic_stub_conflict_no_spurious_warnings() -> None:
    """End-to-end guard for the generic-mode conflict stub: a generic fund with NO
    portfolio + a zero-conflict stub (portfolio_size 0, empty conflicts) must not
    raise any conflict cross-check warning. This is what proves the stub path needs
    no compose changes — ORPHANED_CONFLICT (conflict company not in portfolio),
    INCOMPLETE_PORTFOLIO_REVIEW (portfolio_size < len(portfolio)), and SCHEMA_DRIFT
    must all be absent."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["mode"] = "generic"
    del fund["portfolio"]
    arts["fund_profile.json"] = fund
    arts["conflict_check.json"] = {
        "portfolio_size": 0,
        "conflicts": [],
        "summary": {
            "total_checked": 0,
            "conflict_count": 0,
            "has_blocking_conflict": False,
            "overall_severity": "clear",
        },
        "validation": {"status": "valid", "errors": []},
    }
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "ORPHANED_CONFLICT" not in codes, codes
    assert "INCOMPLETE_PORTFOLIO_REVIEW" not in codes, codes
    assert "SCHEMA_DRIFT" not in codes, codes


def test_compose_no_schema_drift_for_metadata_run_id() -> None:
    """Every producer artifact carries metadata.run_id per artifact-schemas.md —
    that must NOT self-flag SCHEMA_DRIFT on every single run."""
    arts = _all_required_artifacts()
    for name in list(arts.keys()):
        art = dict(arts[name])
        art["metadata"] = {"run_id": "20260101T000000Z"}
        arts[name] = art
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes


def test_compose_no_schema_drift_for_agent_notes_keys() -> None:
    """The Step-7 agent commonly appends narrative keys (competitive_notes / gtm_notes)
    and, under the Auto-pilot carve-out, a to_confirm object to startup_profile. These
    are benign; they must not raise a noisy SCHEMA_DRIFT warning every run."""
    arts = _all_required_artifacts()
    startup: dict[str, Any] = dict(_VALID_STARTUP)
    startup["competitive_notes"] = "Crowded but differentiated on X"
    startup["gtm_notes"] = "PLG motion, expanding to sales-led"
    startup["to_confirm"] = {"geography": "inferred from +972 phone"}
    arts["startup_profile.json"] = startup
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SCHEMA_DRIFT" not in codes, [
        w["message"] for w in data["validation"]["warnings"] if w["code"] == "SCHEMA_DRIFT"
    ]


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
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
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
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
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
# v0.4.2 Phase 3 Task 7: coaching_payload + uuid insertion marker tests
# ---------------------------------------------------------------------------


def test_compose_emits_coaching_payload() -> None:
    """compose emits a coaching_payload block with all v0.4.2-ic-sim fields."""
    import re

    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "coaching_payload" in data, "report.json missing coaching_payload block"

    payload = data["coaching_payload"]
    assert payload["schema_version"] == "v0.4.2-ic-sim"

    # All expected top-level keys present
    for key in (
        "schema_version",
        "summary",
        "dealbreakers",
        "concerns",
        "high_severity_warnings",
        "company_name",
        "review_dir",
        "report_path",
        "insertion_marker",
    ):
        assert key in payload, f"coaching_payload missing key: {key}"

    # Summary mirrors score_dimensions conviction counts
    s = payload["summary"]
    for sk in (
        "verdict",
        "conviction_score",
        "strong_conviction_count",
        "moderate_conviction_count",
        "concern_count",
        "dealbreaker_count",
    ):
        assert sk in s, f"coaching_payload.summary missing {sk}"

    # Company name surfaced from startup_profile
    assert payload["company_name"] == "TestCo"

    # Insertion marker matches uuid format
    assert re.fullmatch(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", payload["insertion_marker"]), (
        f"unexpected marker shape: {payload['insertion_marker']}"
    )

    # Backward-compat: existing top-level keys still present
    assert "report_markdown" in data
    assert "validation" in data


def test_compose_inserts_uuid_marker() -> None:
    """report.md contains exactly one uuid marker matching coaching_payload.insertion_marker."""
    import re

    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    md = data["report_markdown"]
    matches = re.findall(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", md)
    assert len(matches) == 1, f"expected exactly one marker, found {len(matches)}: {matches}"
    assert matches[0] == data["coaching_payload"]["insertion_marker"], (
        "marker in report.md must equal coaching_payload.insertion_marker"
    )


def test_compose_warns_on_marker_collision() -> None:
    """Body content containing the marker substring triggers MARKER_COLLISION (non-fatal)."""
    # Adversarial: a debate exchange position that contains the literal marker substring.
    # The discussion section renders exchange positions directly into report.md.
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["debate_sections"] = [
        {
            "topic": "GTM Motion",
            "exchanges": [
                {
                    "partner": "operator",
                    "position": ("Sneaky body content with <!-- COACHING_INSERTION_POINT_aaaaaaaa --> embedded"),
                },
            ],
        },
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    # Compose still succeeds (warning, not error)
    assert rc == 0, err
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes, f"expected MARKER_COLLISION in warnings, got: {codes}"


def test_payload_summary_counts_match_score_dimensions() -> None:
    """coaching_payload.summary.dealbreaker_count == len(dealbreakers); concern_count == len(concerns)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["dealbreakers"] = [
        {
            "id": "risk_single_point_failure",
            "label": "Single Point",
            "category": "Risk",
            "evidence": "No redundancy",
            "notes": None,
        },
    ]
    score["summary"]["top_concerns"] = [
        {
            "id": "biz_unit_economics",
            "label": "Unit Economics",
            "category": "Business Model",
            "evidence": "CAC > LTV",
            "notes": None,
        },
        {"id": "market_timing", "label": "Timing", "category": "Market", "evidence": "Market nascent", "notes": None},
    ]
    score["summary"]["dealbreaker"] = 1
    score["summary"]["concern"] = 2
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert payload["summary"]["dealbreaker_count"] == len(payload["dealbreakers"]) == 1
    assert payload["summary"]["concern_count"] == len(payload["concerns"]) == 2


def test_payload_dealbreakers_have_severity() -> None:
    """Every dealbreaker entry in coaching_payload has severity == 'high'."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["dealbreakers"] = [
        {
            "id": "risk_single_point_failure",
            "label": "Single Point",
            "category": "Risk",
            "evidence": "Key person dependency",
            "notes": None,
        },
        {
            "id": "biz_unit_economics",
            "label": "Unit Economics",
            "category": "Business Model",
            "evidence": "Negative margin",
            "notes": None,
        },
    ]
    score["summary"]["dealbreaker"] = 2
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert len(payload["dealbreakers"]) == 2
    for db in payload["dealbreakers"]:
        assert db.get("severity") == "high", f"dealbreaker entry missing severity:high — got: {db}"


def test_payload_concerns_have_description() -> None:
    """Every concern entry in coaching_payload has a non-empty description."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["top_concerns"] = [
        {
            "id": "market_timing",
            "label": "Timing",
            "category": "Market",
            "evidence": "Market still nascent",
            "notes": None,
        },
        {
            "id": "fin_runway_plan",
            "label": "Runway Plan",
            "category": "Financials",
            "evidence": "",
            "notes": "No runway plan provided",
        },
    ]
    score["summary"]["concern"] = 2
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert len(payload["concerns"]) == 2
    for c in payload["concerns"]:
        assert "description" in c, f"concern entry missing description key — got: {c}"
        assert isinstance(c["description"], str) and len(c["description"]) > 0, (
            f"concern entry has empty description — got: {c}"
        )


def test_payload_dealbreakers_precede_concerns_in_serialization() -> None:
    """When serialized to JSON, dealbreakers key comes before concerns key (insertion order)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    score["summary"] = dict(_VALID_SCORE["summary"])
    score["summary"]["dealbreakers"] = [
        {
            "id": "risk_single_point_failure",
            "label": "Single Point",
            "category": "Risk",
            "evidence": "No redundancy",
            "notes": None,
        },
    ]
    score["summary"]["top_concerns"] = [
        {"id": "market_timing", "label": "Timing", "category": "Market", "evidence": "Market nascent", "notes": None},
    ]
    score["summary"]["dealbreaker"] = 1
    score["summary"]["concern"] = 1
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    # Serialize with sort_keys=False to preserve insertion order (Python 3.7+ guarantee)
    serialized = json.dumps(payload, sort_keys=False)
    db_pos = serialized.find('"dealbreakers"')
    concerns_pos = serialized.find('"concerns"')
    assert db_pos != -1, '"dealbreakers" key not found in serialized payload'
    assert concerns_pos != -1, '"concerns" key not found in serialized payload'
    assert db_pos < concerns_pos, (
        f'"dealbreakers" should appear before "concerns" in JSON (got positions {db_pos} vs {concerns_pos})'
    )


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
    assert "founder_message" in na_w[0]
    founder_msg = na_w[0]["founder_message"]
    assert "not_applicable" not in founder_msg
    assert "7" in founder_msg
    assert founder_msg in data["report_markdown"]


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


# === v0.4.1 Phase 3 Task 10: compose on-disk verification + tolerant JSON extraction ===


def test_compose_writes_md_flag(tmp_path: Any) -> None:
    """After successful compose with --write-md, both report.json and report.md must exist on disk."""
    d = _make_artifact_dir(_all_required_artifacts())
    json_path = os.path.join(d, "report.json")
    md_path = os.path.join(d, "report.md")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", d, "-o", json_path, "--write-md", md_path],
    )
    assert rc == 0, err
    assert os.path.isfile(json_path)
    assert os.path.isfile(md_path)
    assert os.path.getsize(json_path) > 0
    assert os.path.getsize(md_path) > 0


def test_compose_exits_nonzero_if_write_md_path_unwritable(tmp_path: Any) -> None:
    """Compose must exit nonzero if --write-md target dir doesn't exist and can't be created."""
    import pathlib

    d = _make_artifact_dir(_all_required_artifacts())
    # Point --write-md at a path inside a read-only parent
    ro_parent = pathlib.Path(str(tmp_path)) / "readonly"
    ro_parent.mkdir(mode=0o555)
    bad_md_path = str(ro_parent / "no-write" / "report.md")
    json_path = os.path.join(d, "report.json")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", d, "-o", json_path, "--write-md", bad_md_path],
    )
    assert rc != 0, "compose should exit nonzero when --write-md target is unwritable"
    # Cleanup: restore writable mode so tmp_path can be deleted
    os.chmod(str(ro_parent), 0o755)


# === v0.4.1 Phase 3 Task 10: tolerant JSON extraction from sub-agent messages ===


def test_extract_dispatch_json_raw_object() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_dispatch_json_fenced() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_dispatch_json_nested() -> None:
    """Critical regression test: must not truncate on inner }."""
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = '```json\n{"a": {"b": 1}, "c": 2}\n```'
    assert extract_dispatch_json(text) == {"a": {"b": 1}, "c": 2}


def test_extract_dispatch_json_embedded_in_prose() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = 'Here is the result:\n{"a": 1, "b": 2}\nLet me know if anything is wrong.'
    assert extract_dispatch_json(text) == {"a": 1, "b": 2}


def test_extract_dispatch_json_raises_when_no_json() -> None:
    import sys

    import pytest

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    with pytest.raises(ValueError):
        extract_dispatch_json("Just some prose with no JSON object anywhere.")


# ============================================================
# Regression: producer --run-id injection (metadata.run_id)
# ============================================================


def _run_producer_explicit(name: str, args: list[str], stdin_data: str) -> tuple[int, dict | None, str]:
    """Run a producer WITHOUT the test-helper run-id auto-injection (raw cmd)."""
    cmd = [sys.executable, os.path.join(IC_SIM_DIR, name), *args]
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def test_fund_profile_run_id_required() -> None:
    """fund_profile.py exits non-zero when --run-id is omitted."""
    payload = json.dumps(_VALID_GENERIC_PROFILE)
    rc, _data, err = _run_producer_explicit("fund_profile.py", ["--pretty"], payload)
    assert rc != 0
    assert "run-id" in err.lower() or "run_id" in err.lower()


def test_fund_profile_injects_metadata_run_id() -> None:
    """fund_profile.py writes metadata.run_id from --run-id."""
    payload = json.dumps(_VALID_GENERIC_PROFILE)
    rc, data, _err = _run_producer_explicit("fund_profile.py", ["--pretty", "--run-id", "RID-FUND"], payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-FUND"}


def test_fund_profile_run_id_overrides_stdin_metadata() -> None:
    """--run-id overrides any metadata block supplied via stdin (last-write-wins)."""
    profile = dict(_VALID_GENERIC_PROFILE)
    profile["metadata"] = {"run_id": "STALE", "extra": "ignored"}
    payload = json.dumps(profile)
    rc, data, _err = _run_producer_explicit("fund_profile.py", ["--pretty", "--run-id", "FRESH"], payload)
    assert rc == 0
    assert data is not None
    assert data["metadata"] == {"run_id": "FRESH"}


def test_detect_conflicts_run_id_required() -> None:
    """detect_conflicts.py exits non-zero when --run-id is omitted."""
    payload = json.dumps({"portfolio_size": 2, "conflicts": []})
    rc, _data, err = _run_producer_explicit("detect_conflicts.py", ["--pretty"], payload)
    assert rc != 0
    assert "run-id" in err.lower() or "run_id" in err.lower()


def test_detect_conflicts_injects_metadata_run_id() -> None:
    """detect_conflicts.py writes metadata.run_id from --run-id."""
    payload = json.dumps({"portfolio_size": 2, "conflicts": []})
    rc, data, _err = _run_producer_explicit("detect_conflicts.py", ["--pretty", "--run-id", "RID-CONF"], payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-CONF"}


def test_score_dimensions_run_id_required() -> None:
    """score_dimensions.py exits non-zero when --run-id is omitted."""
    payload = json.dumps({"items": _make_dimension_items()})
    rc, _data, err = _run_producer_explicit("score_dimensions.py", ["--pretty"], payload)
    assert rc != 0
    assert "run-id" in err.lower() or "run_id" in err.lower()


def test_score_dimensions_injects_metadata_run_id() -> None:
    """score_dimensions.py writes metadata.run_id from --run-id."""
    payload = json.dumps({"items": _make_dimension_items()})
    rc, data, _err = _run_producer_explicit("score_dimensions.py", ["--pretty", "--run-id", "RID-SCORE"], payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-SCORE"}


# ============================================================
# Regression: detect_conflicts dedup tolerates non-string company
# ============================================================


def test_detect_conflicts_non_string_company_no_crash() -> None:
    """A non-string 'company' value degrades to a validation error, not an AttributeError crash."""
    payload = json.dumps(
        {
            "portfolio_size": 2,
            "conflicts": [
                {"company": 12345, "type": "direct", "severity": "manageable", "rationale": "x"},
            ],
        }
    )
    rc, data, err = run_script("detect_conflicts.py", ["--pretty"], stdin_data=payload)
    # Before the fix the dedup loop called .strip() on the int and crashed with
    # an AttributeError traceback before structured validation could run.
    assert rc == 0, err
    assert data is not None
    assert "Traceback" not in err
    assert "validation" in data


# ============================================================
# Regression: score_dimensions reports correct non-dict item index
# ============================================================


def test_score_non_dict_item_reports_position_index() -> None:
    """Index in 'Item N must be an object' is the list position, not len(seen_ids)."""
    items = _make_dimension_items()
    # Replace the SECOND item with a non-dict; the first remains a valid dict with an id.
    items[1] = "not_a_dict"  # type: ignore[call-overload]
    payload = json.dumps({"items": items})
    rc, data, _err = run_script("score_dimensions.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    msgs = [e for e in data["validation"]["errors"] if "must be an object" in e]
    assert msgs, data["validation"]["errors"]
    # Position is index 1; the buggy version reported index 1 too only by luck —
    # use two non-dict items to force divergence.
    items2 = _make_dimension_items()
    items2[1] = "nope"  # type: ignore[call-overload]
    items2[3] = "nope2"  # type: ignore[call-overload]
    payload2 = json.dumps({"items": items2})
    _rc2, data2, _ = run_script("score_dimensions.py", [], stdin_data=payload2)
    assert data2 is not None
    bad_msgs = [e for e in data2["validation"]["errors"] if "must be an object" in e]
    assert any("Item 1 " in e for e in bad_msgs), bad_msgs
    assert any("Item 3 " in e for e in bad_msgs), bad_msgs


# ============================================================
# Regression: consensus_strength derived into coaching_payload
# ============================================================


def test_coaching_payload_consensus_strength_strong() -> None:
    """Three identical partner verdicts -> consensus_strength 'strong'."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "a"},
        {"partner": "operator", "verdict": "invest", "rationale": "b"},
        {"partner": "analyst", "verdict": "invest", "rationale": "c"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["consensus_strength"] == "strong"


def test_coaching_payload_consensus_strength_mixed() -> None:
    """A 2-1 split -> consensus_strength 'mixed'."""
    arts = _all_required_artifacts()
    # _VALID_DISCUSSION is already invest/more_diligence/more_diligence (2-1).
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["consensus_strength"] == "mixed"


def test_coaching_payload_consensus_strength_weak_when_three_way() -> None:
    """Three distinct verdicts -> consensus_strength 'weak'."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "a"},
        {"partner": "operator", "verdict": "pass", "rationale": "b"},
        {"partner": "analyst", "verdict": "more_diligence", "rationale": "c"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["consensus_strength"] == "weak"


def test_coaching_payload_consensus_strength_weak_when_missing() -> None:
    """Missing/fewer-than-3 partner verdicts -> consensus_strength 'weak'."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "a"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["consensus_strength"] == "weak"


# ============================================================
# Regression: marker-collision ordering — status, warnings section,
# validation.warnings, coaching_payload all agree
# ============================================================


def test_marker_collision_reflected_in_status_and_warnings_section() -> None:
    """When MARKER_COLLISION fires, status != 'clean', it appears in the rendered
    Warnings section, and validation.warnings + the report body agree."""
    arts = _all_required_artifacts()
    # Otherwise-clean set: align consensus to score verdict and use rich partners.
    discussion = dict(_VALID_DISCUSSION)
    discussion["consensus_verdict"] = "invest"
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Large market with clear timing catalyst"},
        {"partner": "operator", "verdict": "invest", "rationale": "Strong product-market fit and retention"},
        {"partner": "analyst", "verdict": "invest", "rationale": "Healthy unit economics and capital efficiency"},
    ]
    discussion["debate_sections"] = [
        {
            "topic": "GTM Motion",
            "exchanges": [
                {
                    "partner": "operator",
                    "position": "Body with <!-- COACHING_INSERTION_POINT_aaaaaaaa --> embedded substring",
                },
            ],
        },
    ]
    arts["discussion.json"] = discussion
    arts["partner_assessment_visionary.json"] = _VALID_PARTNER_VISIONARY
    arts["partner_assessment_operator.json"] = _VALID_PARTNER_OPERATOR
    arts["partner_assessment_analyst.json"] = _VALID_PARTNER_ANALYST
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes, codes
    # Status must reflect the appended warning (not stale "clean").
    assert data["validation"]["status"] == "warnings"
    # The Warnings section must be rendered in the report body and include the collision.
    md = data["report_markdown"]
    assert "## Warnings" in md
    assert "Marker Collision" in md


# ============================================================
# Regression: compose renderers tolerate malformed list elements
# ============================================================


def test_compose_tolerates_non_dict_partner_verdict() -> None:
    """A non-dict partner_verdicts element must not crash compose (executive summary
    + PARTNER_UNANIMITY both guard)."""
    arts = _all_required_artifacts()
    discussion = dict(_VALID_DISCUSSION)
    discussion["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "a"},
        "a_bare_string",
        {"partner": "analyst", "verdict": "pass", "rationale": "c"},
    ]
    arts["discussion.json"] = discussion
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "Traceback" not in err


def test_compose_tolerates_non_dict_archetype_and_counts() -> None:
    """Non-dict archetype and non-dict by_category value must not crash rendering."""
    arts = _all_required_artifacts()
    fund = json.loads(json.dumps(_VALID_FUND))
    fund["archetypes"].append("bogus_archetype_string")
    fund["check_size_range"] = "not-a-dict"
    arts["fund_profile.json"] = fund
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["by_category"] = {"Team": "not-a-dict-counts"}
    score["items"].append("bogus_item_string")
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "Traceback" not in err


# ============================================================
# Artifact self-sufficiency fixes (items 10-14)
# ============================================================


def _all_required_with_rich_partners() -> dict[str, dict]:
    """Required artifacts plus all 3 rich partner assessments."""
    arts = _all_required_artifacts()
    arts["partner_assessment_visionary.json"] = {
        "partner": "visionary",
        "verdict": "invest",
        "rationale": "Large market with clear timing and strong founder-market fit",
        "conviction_points": ["Big TAM with clear timing", "Founder has 10yr domain experience"],
        "key_concerns": ["No enterprise references yet"],
        "questions_for_founders": [
            "What's the 10-year vision?",
            "How do you think about competition from incumbents?",
        ],
        "diligence_requirements": ["Reference calls"],
    }
    arts["partner_assessment_operator.json"] = {
        "partner": "operator",
        "verdict": "more_diligence",
        "rationale": "Strong PMF indicators but GTM motion is unclear and uncosted",
        "conviction_points": ["Good retention (NRR >110%)", "Short sales cycle"],
        "key_concerns": ["No channel economics", "AE capacity unclear"],
        "questions_for_founders": [
            "Walk me through last 5 customer wins",
            "What's your CAC payback period?",
        ],
        "diligence_requirements": ["Channel CAC analysis"],
    }
    arts["partner_assessment_analyst.json"] = {
        "partner": "analyst",
        "verdict": "more_diligence",
        "rationale": "Unit economics are emerging but need cohort data to confirm",
        "conviction_points": ["Growing revenue", "Improving margins"],
        "key_concerns": ["No cohort data", "LTV assumptions aggressive"],
        "questions_for_founders": [
            "Show me retention curves",
            "What's the assumed LTV and why?",
        ],
        "diligence_requirements": ["Cohort retention data"],
    }
    return arts


def test_compose_scorecard_has_evidence_column() -> None:
    """Dimension scorecard includes an Evidence column with truncated text."""
    arts = _all_required_artifacts()
    # Give one item long evidence to test truncation
    score = json.loads(json.dumps(_VALID_SCORE))
    score["items"][0]["evidence"] = "A" * 200  # 200-char evidence string
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    scorecard = md.split("## Dimension Scorecard")[1].split("##")[0]
    # Evidence column header must appear
    assert "| Evidence |" in scorecard
    # Truncated evidence must end with ellipsis
    assert "..." in scorecard


def test_compose_scorecard_evidence_empty_safe() -> None:
    """Scorecard renders cleanly when evidence is None."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    for item in score["items"]:
        item["evidence"] = None
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "## Dimension Scorecard" in data["report_markdown"]


def test_compose_scorecard_committee_note() -> None:
    """Scorecard section includes the committee-scored note."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "scored once by the committee as a whole" in md


def test_compose_exec_summary_conviction_footnote() -> None:
    """Executive summary includes the conviction score formula footnote."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Conviction score = (strong" in md or "strong × 1.0" in md
    assert "Decline — hard pass" in md  # humanized by the shared founder-text policy (_founder_text.py)
    assert "applicable dimensions" in md


def test_compose_partner_questions_rendered() -> None:
    """Partner assessments produce a 'Questions the Partners Would Ask You' section."""
    arts = _all_required_with_rich_partners()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "## Questions the Partners Would Ask You" in md
    # Partner names rendered
    assert "Visionary" in md or "visionary" in md.lower()
    assert "Operator" in md or "operator" in md.lower()
    # Conviction points, concerns, questions rendered
    assert "Big TAM with clear timing" in md
    assert "No channel economics" in md
    assert "Walk me through last 5 customer wins" in md


def test_compose_partner_questions_graceful_when_absent() -> None:
    """When no partner assessments are present, the section is omitted gracefully."""
    arts = _all_required_artifacts()  # no partner assessment files
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Section must NOT appear when assessments missing
    assert "## Questions the Partners Would Ask You" not in md


def test_compose_discussion_key_concerns_rendered() -> None:
    """discussion.json key_concerns are rendered in the Discussion section."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Extract the content from Discussion Summary up to (not including) the next top-level ## section
    import re

    discussion_match = re.search(r"## Discussion Summary\n(.*?)(?=\n## )", md, re.DOTALL)
    assert discussion_match is not None, "Discussion Summary section not found"
    discussion_section = discussion_match.group(1)
    # _VALID_DISCUSSION has key_concerns: ["GTM unclear", "Need cohort data"]
    assert "GTM unclear" in discussion_section
    assert "Need cohort data" in discussion_section


def test_compose_concerns_include_evidence() -> None:
    """Dealbreakers and key concerns in Concerns section include evidence as Basis line."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    # Add a dealbreaker with evidence
    score["items"][0] = {
        "id": _DIMENSION_IDS[0],
        "category": "Team",
        "label": "Founder Market Fit",
        "status": "dealbreaker",
        "evidence": "No relevant domain experience found",
        "notes": "Fatal — domain experience is non-negotiable",
    }
    score["summary"]["verdict"] = "hard_pass"
    score["summary"]["dealbreaker"] = 1
    score["summary"]["strong_conviction"] = 27
    score["summary"]["dealbreakers"] = [
        {
            "id": _DIMENSION_IDS[0],
            "category": "Team",
            "label": "Founder Market Fit",
            "evidence": "No relevant domain experience found",
            "notes": "Fatal — domain experience is non-negotiable",
        }
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Evidence must appear as Basis line in Concerns section
    assert "*Basis: No relevant domain experience found*" in md


# ============================================================
# Generic-mode illustrative-fund disclaimer
# ============================================================


def test_compose_generic_mode_illustrative_disclaimer() -> None:
    """fund_profile.mode == generic -> report carries an explicit
    illustrative/not-a-real-fund disclaimer."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["mode"] = "generic"
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"].lower()
    assert "illustrative" in md
    assert "not a real fund" in md or "not a real fund's" in md


def test_compose_fund_specific_mode_no_illustrative_disclaimer() -> None:
    """Back-compat: a real, named fund (fund_specific mode) does NOT get the
    generic-mode illustrative disclaimer."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["mode"] = "fund_specific"
    fund["sources"] = [{"url": "https://example.com"}]
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"].lower()
    assert "illustrative" not in md


# ============================================================
# Unambiguous headline verdict rendering
# ============================================================


def test_compose_headline_verdict_pass_says_decline_not_bare_pass() -> None:
    """A 'pass' verdict must render as an unambiguous decline in the
    founder-facing headline — never a bare 'Pass'."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = "pass"
    score["summary"]["conviction_score"] = 30.0
    score["summary"]["strong_conviction"] = 8
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    headline = next(line for line in md.splitlines() if line.startswith("**Conviction Score:**"))
    assert "Decline" in headline
    # No bare "Pass" as a standalone word in the headline (e.g. "— Pass —" or "Pass ").
    # "Hard Pass" is fine — it's unambiguous on its own; a bare "Pass" is not.
    assert re.search(r"(?<!Hard )\bPass\b", headline) is None, headline


def test_compose_headline_verdict_hard_pass_says_decline() -> None:
    """A 'hard_pass' verdict renders 'Decline' alongside 'Hard Pass', not a bare
    'Pass'."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = "hard_pass"
    score["summary"]["dealbreaker"] = 1
    score["summary"]["strong_conviction"] = 27
    score["summary"]["dealbreakers"] = [
        {"id": _DIMENSION_IDS[0], "category": "Team", "label": "Test", "evidence": "test", "notes": "fatal"}
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    headline = next(line for line in md.splitlines() if line.startswith("**Conviction Score:**"))
    assert "Decline" in headline
    assert "Hard Pass" in headline
    assert re.search(r"(?<!Hard )\bPass\b", headline) is None, headline


def test_compose_headline_verdict_invest_unchanged() -> None:
    """Back-compat: 'invest' verdict still renders 'Invest' (no regression)."""
    arts = _all_required_artifacts()  # _VALID_SCORE verdict is already "invest"
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    exec_summary = md.split("## Executive Summary")[1].split("\n## ")[0]
    assert "Invest" in exec_summary


def test_compose_headline_verdict_more_diligence_unchanged() -> None:
    """Back-compat: 'more_diligence' verdict still renders 'More Diligence'."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = "more_diligence"
    score["summary"]["conviction_score"] = 60.0
    score["summary"]["strong_conviction"] = 17
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    exec_summary = md.split("## Executive Summary")[1].split("\n## ")[0]
    assert "More Diligence" in exec_summary


def test_compose_generic_mode_dealbreaker_non_blocking_note() -> None:
    """When fund mode is generic and score_dimensions reports the dealbreaker
    as non-blocking (dealbreaker_blocking: false), the report explains that
    the merits-based score — not the simulated conflict — drove the verdict."""
    arts = _all_required_artifacts()
    fund = dict(_VALID_FUND)
    fund["mode"] = "generic"
    arts["fund_profile.json"] = fund
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["dealbreaker"] = 1
    score["summary"]["dealbreaker_blocking"] = False
    score["summary"]["fund_mode"] = "generic"
    score["summary"]["strong_conviction"] = 27
    score["summary"]["warnings"] = ["GENERIC_MODE_DEALBREAKER_NON_BLOCKING"]
    score["summary"]["dealbreakers"] = [
        {"id": _DIMENSION_IDS[0], "category": "Team", "label": "Test", "evidence": "sim conflict", "notes": None}
    ]
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert data["coaching_payload"]["summary"]["verdict"] != "hard_pass"
    exec_summary = md.split("## Executive Summary")[1].split("\n## ")[0]
    assert "non-blocking" in exec_summary.lower() or "simulated" in exec_summary.lower()


# ============================================================
# SKILL.md / agent-body contract tests
# ============================================================

_ICSIM_SKILL_DIR = os.path.dirname(IC_SIM_DIR)  # .../skills/ic-sim
_SKILL_MD_PATH = os.path.join(_ICSIM_SKILL_DIR, "SKILL.md")
_AGENT_MD_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "agents", "ic-sim.md")
_ARTIFACT_SCHEMAS_MD_PATH = os.path.join(_ICSIM_SKILL_DIR, "references", "artifact-schemas.md")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _skill_md_section(heading: str) -> str:
    """Return the SKILL.md body from `heading` (e.g. '### Step 1:') up to the
    next '### ' or '## ' heading of the same-or-higher level."""
    text = _read(_SKILL_MD_PATH)
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end_match = re.search(r"\n### |\n## ", rest)
    end = end_match.start() if end_match else len(rest)
    return heading + rest[:end]


def test_skill_md_stage_enum_inlined() -> None:
    """Step 1 must inline founder_context.py's full --stage enum (7 hyphenated
    values) so the agent doesn't have to guess or re-derive it — same pattern
    already applied in market-sizing/competitive-positioning SKILL.md."""
    step1 = _skill_md_section("### Step 1: Read or Create Founder Context")
    for value in ("pre-seed", "seed", "series-a", "series-b", "series-c", "series-d", "later"):
        assert f"`{value}`" in step1, f"Step 1 is missing --stage enum value {value!r}"


def test_skill_md_sector_type_enum_inlined() -> None:
    """Step 1 must inline founder_context.py's full --sector-type enum (9
    hyphenated values)."""
    step1 = _skill_md_section("### Step 1: Read or Create Founder Context")
    for value in (
        "saas",
        "ai-native",
        "marketplace",
        "hardware",
        "hardware-subscription",
        "consumer-subscription",
        "usage-based",
        "transactional-fintech",
        "retail",
    ):
        assert f"`{value}`" in step1, f"Step 1 is missing --sector-type enum value {value!r}"


def test_skill_md_step1_autopilot_crossreferenced() -> None:
    """Step 1's founder-context gate must cross-reference Auto-pilot: a true
    unattended run shouldn't be forced through AskUserQuestion when the
    provided materials already answer name/stage/sector/geography."""
    step1 = _skill_md_section("### Step 1: Read or Create Founder Context")
    assert "Auto-pilot" in step1
    assert "AskUserQuestion" in step1


def test_skill_md_step1_carveout_is_non_binary() -> None:
    """Step 1's Auto-pilot carve-out must derive the four basics field-by-field, NOT
    all-or-nothing: deriving three and missing one must not re-gate all four. A
    missing-but-implied field should be inferred from a clear signal (geography from a
    phone country code, stage from a fundraise signal, etc.) rather than gated. This is
    the ic-sim copy of the same X-5 carve-out fixed in competitive-positioning."""
    step1 = _skill_md_section("### Step 1: Read or Create Founder Context").lower()
    assert any(phrase in step1 for phrase in ("field-by-field", "independently", "never all-or-nothing")), (
        "Step 1 carve-out must state the four basics are derived independently (non-binary)"
    )
    assert "infer" in step1, "Step 1 carve-out must describe inferring a missing field from a signal"
    assert "+972" in step1 or "phone country code" in step1 or "fundraise signal" in step1, (
        "Step 1 carve-out must give a concrete inference signal (e.g. phone country code, fundraise signal)"
    )


def test_skill_md_consensus_score_mismatch_disposition_rule() -> None:
    """Step 9 must state a disposition rule for CONSENSUS_SCORE_MISMATCH (a
    medium warning with no prior guidance beyond 'fix high-severity and
    re-run') — the mechanical score is authoritative for the headline, the
    mismatch stays a noted caveat."""
    step8 = _skill_md_section("### Step 9: Compose and Validate Report")
    assert "CONSENSUS_SCORE_MISMATCH" in step8
    assert "authoritative" in step8.lower()


def test_skill_md_partner_analysis_dedup_guidance() -> None:
    """Step 6 must instruct exactly one dispatch per archetype with an
    explicit dedup/idempotency check — the fleet observed a double 'visionary'
    dispatch (4 dispatches for 3 archetypes) with no guard against it."""
    step5 = _skill_md_section("### Step 6: Partner Assessments (PARTNER_ANALYSIS × 3 in parallel)")
    assert "exactly one dispatch per" in step5.lower() or "dedup" in step5.lower()
    for archetype in ("visionary", "operator", "analyst"):
        assert archetype in step5


def test_skill_md_step7_inlines_conflict_check() -> None:
    """Step 8's SCORE_DIMENSIONS dispatch must inline conflict_check.json so
    fit_portfolio_conflict can reflect real conflicts instead of defaulting to
    not_applicable."""
    step7 = _skill_md_section("### Step 8: Score Dimensions -> `score_dimensions.json` (Context A dispatch)")
    assert "conflict_check.json" in step7
    assert "CONFLICT_CHECK:" in step7


def test_skill_md_step4_partner_archetypes_read_is_fund_specific() -> None:
    """The Step-4 REQUIRED read of partner-archetypes.md is for mapping a REAL fund's
    partners to archetype roles — pointless in generic mode (which uses the three
    canonical archetypes). The read must be scoped to fund-specific mode, not demanded
    unconditionally (a wasted read + a contradiction with the reference-list note)."""
    step4 = _skill_md_section("### Step 4: Build Fund Profile -> `fund_profile.json`")
    # Find the partner-archetypes read instruction and confirm it's mode-scoped.
    assert "partner-archetypes.md" in step4
    idx = step4.index("partner-archetypes.md")
    window = step4[max(0, idx - 200) : idx + 200].lower()
    assert "fund-specific" in window, "the partner-archetypes.md read must be scoped to fund-specific mode"
    assert "generic" in window, "the partner-archetypes.md read must state generic mode does not need it"


def test_skill_md_step4_generic_mode_omits_portfolio() -> None:
    """Step 4 must explicitly instruct the agent to OMIT the portfolio in generic
    mode (prose, not just an example). A synthesized/illustrative fund has no real
    holdings; fabricating a portfolio manufactures conflicts against invented
    companies. The prose is the behavior driver — an example alone is too weak."""
    step4 = _skill_md_section("### Step 4: Build Fund Profile -> `fund_profile.json`")
    low = step4.lower()
    assert "omit" in low, "Step 4 must instruct portfolio omission in generic mode"
    assert "portfolio" in low
    assert "generic" in low


def test_skill_md_step5a_generic_mode_uses_stub() -> None:
    """Step 5 must be mode-conditional: in generic mode it runs detect_conflicts.py
    --generic-stub directly (no sub-agent dispatch — conflicts against a self-invented
    portfolio are circular), and that invocation must carry --run-id so metadata is
    stamped. Fund-specific mode keeps the existing sub-agent flow."""
    step5a = _skill_md_section("### Step 5: Check Portfolio Conflicts -> `conflict_check.json` (Context A dispatch)")
    assert "--generic-stub" in step5a, "Step 5 is missing the generic-mode stub branch"
    stub_lines = [ln for ln in step5a.splitlines() if "detect_conflicts.py" in ln and "--generic-stub" in ln]
    assert stub_lines, "no detect_conflicts.py --generic-stub invocation line found"
    assert all("--run-id" in ln for ln in stub_lines), (
        "the --generic-stub invocation must carry --run-id (test_producer_pipes_carry_run_id "
        "and detect_conflicts.py's required --run-id both demand it)"
    )
    # POSIX-sh mode branch (dash), never bash `[[ ]]`.
    assert "[[" not in step5a, "Step 5 mode branch must be POSIX sh ([ ] or case), not [[ ]]"


def test_skill_md_step7_wires_fund_mode_into_score_dimensions() -> None:
    """The mode-aware dealbreaker override is dead in production
    unless the main thread actually passes --fund-mode (derived from
    fund_profile.json's mode field) to score_dimensions.py — this is the
    production wiring for the score_dimensions.py behavior change."""
    step7 = _skill_md_section("### Step 8: Score Dimensions -> `score_dimensions.json` (Context A dispatch)")
    assert "--fund-mode" in step7
    assert "fund_profile.json" in step7


def test_agent_score_dimensions_rubric_mentions_conflict_check() -> None:
    """agents/ic-sim.md's SCORE_DIMENSIONS section must also document
    conflict_check.json as an inlined input, matching the SKILL.md dispatch
    template update."""
    agent_body = _read(_AGENT_MD_PATH)
    idx = agent_body.index("#### SCORE_DIMENSIONS subtype")
    section = agent_body[idx : idx + 4000]
    assert "conflict_check.json" in section or "CONFLICT_CHECK" in section


def test_agent_coaching_writes_raw_markdown_no_json_escaping() -> None:
    """R2 coaching-transport fix: agents/ic-sim.md's Context B section must
    instruct the sub-agent to write RAW markdown (no JSON envelope, no
    hand-escaping) — the escaping moves into md_to_commentary.py's
    json.dumps, which cannot emit malformed JSON. The old
    'escape every newline as \\n / every quote as \\"' guardrail (the thing
    that broke ~17-22% of the time) must be gone."""
    agent_body = _read(_AGENT_MD_PATH)
    idx = agent_body.index("### Context B")
    section = agent_body[idx : idx + 4000]
    assert "plain markdown" in section.lower()
    assert "do not escape anything" in section.lower() or "do not escape" in section.lower()
    # The old hand-escaping instruction must not survive anywhere in the file.
    assert "escaped as `\\n`" not in agent_body
    assert 'escaped as `\\"`' not in agent_body
    assert "no pretty-print" not in agent_body.lower()


def test_skill_md_coaching_pipe_uses_format_markdown_adapter() -> None:
    """R2 coaching-transport fix: Step 10's Context-B pipe must gate the raw
    .md hand-off with check_handoff.py --format=markdown and transform it
    through the shared md_to_commentary.py adapter before insert_coaching.py
    — never hand the sub-agent a JSON-escaping burden."""
    step10 = _skill_md_section(
        "### Step 10: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)"
    )
    assert "--format=markdown" in step10
    assert "md_to_commentary.py" in step10
    assert "OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md" in step10
    assert "coaching_commentary_output.json" not in step10


def test_skill_md_coaching_exit7_repair_dispatch() -> None:
    """The content-shape gate's new exit 7 (shape-invalid: receipt-shaped or
    marker-bearing hand-off) must branch to a repair-dispatch, mirroring the
    other typed exits."""
    step10 = _skill_md_section(
        "### Step 10: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)"
    )
    assert "Exit 7" in step10
    assert "repair-dispatch" in step10.lower()
    idx = step10.index("Exit 7")
    window = step10[idx : idx + 300].lower()
    assert "coaching commentary" in window or "coaching markdown" in window


def test_skill_md_heredoc_dollar_guardrail() -> None:
    """SKILL.md must carry a general guardrail: always single-quote
    $-bearing heredoc delimiters, even for ad-hoc/improvised writes outside
    the provided templates (an unquoted heredoc silently shell-expanded away
    a literal '$8M' in a fleet run)."""
    text = _read(_SKILL_MD_PATH)
    assert "shell-expand" in text.lower() or "shell expansion" in text.lower()
    assert "ad-hoc" in text.lower() or "ad hoc" in text.lower()


def test_skill_md_stage_token_reconciliation_documented() -> None:
    """SKILL.md must document the stage-token mismatch between
    founder_context.py's hyphenated --stage enum (pre-seed, series-a, ...)
    and startup_profile.json's underscored stage tokens (pre_seed, series_a)
    that compose_report.py's KNOWN_STAGES actually checks against — otherwise
    an agent that copies the founder-context stage verbatim trips
    STAGE_OUT_OF_SCOPE on a stage that IS in scope."""
    text = _read(_SKILL_MD_PATH)
    assert "pre_seed" in text and "pre-seed" in text
    assert "underscor" in text.lower() or "hyphen" in text.lower()


def test_skill_md_step8_inlines_fund_profile() -> None:
    """Three of the 28 dimensions (fit_thesis_alignment, fit_stage_match,
    fit_value_add) are defined against the fund's actual thesis/stage/check
    size/partners — the SCORE_DIMENSIONS dispatch must inline fund_profile.json
    alongside the other six artifacts so the sub-agent scores against real data
    instead of inventing a hypothetical fund thesis (true in BOTH generic and
    fund-specific mode, since Step 4 builds a real fund_profile.json either
    way)."""
    step8 = _skill_md_section("### Step 8: Score Dimensions -> `score_dimensions.json` (Context A dispatch)")
    assert 'cat "$SIM_DIR/fund_profile.json"' in step8, (
        "Step 8 must cat fund_profile.json alongside the other inlined artifacts"
    )
    assert "FUND_PROFILE:" in step8, "the dispatch prompt template must carry a FUND_PROFILE: marker"
    # The FUND_PROFILE: marker must appear inside the actual dispatch prompt
    # template (paired with the other markers), not just in prose elsewhere.
    template_start = step8.index("CONTEXT: SCORE_DIMENSIONS")
    template = step8[template_start : template_start + 3000]
    assert "FUND_PROFILE:" in template
    assert "STARTUP_PROFILE:" in template
    # "ZERO file reads" framing must still hold — inlined, not a path reference.
    assert "ZERO file reads" in step8


def test_skill_md_step8_seven_artifacts_not_six() -> None:
    """The 'largest inline' framing must be updated from 6 to 7 artifacts now
    that fund_profile.json is added — a stale '6' would misdescribe the
    dispatch to a future editor."""
    step8 = _skill_md_section("### Step 8: Score Dimensions -> `score_dimensions.json` (Context A dispatch)")
    assert "7 JSON artifacts" in step8 or "seven" in step8.lower()
    assert "6 JSON artifacts" not in step8


def test_agent_score_dimensions_rubric_mentions_fund_profile() -> None:
    """agents/ic-sim.md's SCORE_DIMENSIONS section must document FUND_PROFILE
    as an inlined input, matching the SKILL.md dispatch template update."""
    agent_body = _read(_AGENT_MD_PATH)
    idx = agent_body.index("#### SCORE_DIMENSIONS subtype")
    section = agent_body[idx : idx + 4000]
    assert "FUND_PROFILE" in section


def test_agent_fund_fit_scores_against_supplied_profile_not_hypothetical() -> None:
    """The Fund Fit rubric previously told the sub-agent to evaluate against
    'a hypothetical early-stage fund thesis' in generic mode — but Step 4
    builds a REAL fund_profile.json in generic mode too (portfolio omitted,
    not the whole profile). The rubric must now point at the supplied
    FUND_PROFILE in both modes and must not instruct inventing one."""
    agent_body = _read(_AGENT_MD_PATH)
    idx = agent_body.index("**Fund Fit**")
    section = agent_body[idx : idx + 1500]
    assert "FUND_PROFILE" in section, "Fund Fit rubric must point at the inlined FUND_PROFILE"
    assert "hypothetical early-stage fund thesis" not in agent_body, (
        "the old 'invent a hypothetical thesis' instruction must be removed — "
        "generic mode has a real (if synthesized) fund_profile.json on disk"
    )
    low = section.lower()
    assert "not invent" in low or "do not invent" in low or "never invent" in low


def test_artifact_schemas_portfolio_conditional_matches_code() -> None:
    """artifact-schemas.md must document fund_profile.json's `portfolio` as
    conditionally required (fund_specific mode only), matching
    fund_profile.py's actual validation (which only requires it when
    mode == 'fund_specific') and compose_report.py's REQUIRED_KEYS (which
    omits it entirely, by design, per its own inline comment)."""
    text = _read(_ARTIFACT_SCHEMAS_MD_PATH)
    idx = text.index("## fund_profile.json")
    section = text[idx : idx + 2000]
    portfolio_row = next(
        (line for line in section.splitlines() if line.strip().startswith("| `portfolio`")),
        None,
    )
    assert portfolio_row is not None, "fund_profile.json section must have a `portfolio` row"
    assert "| yes |" not in portfolio_row, (
        "portfolio must NOT be documented as unconditionally required — "
        "fund_profile.py and compose_report.py both treat it as optional in generic mode"
    )
    assert "fund_specific" in portfolio_row or "generic" in portfolio_row


def test_artifact_schemas_debate_sections_not_unconditionally_required() -> None:
    """artifact-schemas.md must not mark discussion.json's `debate_sections`
    as unconditionally required — compose_report.py's REQUIRED_KEYS for
    discussion.json is {assessment_mode, partner_verdicts, consensus_verdict}
    only; debate_sections is not enforced."""
    text = _read(_ARTIFACT_SCHEMAS_MD_PATH)
    idx = text.index("## discussion.json")
    section = text[idx : idx + 2000]
    row = next(
        (line for line in section.splitlines() if line.strip().startswith("| `debate_sections`")),
        None,
    )
    assert row is not None, "discussion.json section must have a `debate_sections` row"
    assert "| yes |" not in row, (
        "debate_sections must not be documented as unconditionally required — "
        "compose_report.py's REQUIRED_KEYS for discussion.json omits it"
    )


def test_skill_md_decline_gate_conditional_on_producer_verdict() -> None:
    """A hard_pass/decline verdict must never ship without a confirmation
    gate. The gate must be CONDITIONAL (skip on invest/more_diligence, fire
    on pass/hard_pass) and must read the trigger from score_dimensions.json
    (producer data), never from the agent's own prose judgement of the
    discussion."""
    gate = _skill_md_section("### Step 8.5: Decline Confirmation Gate (conditional)")
    assert "score_dimensions.json" in gate
    assert '["summary"]["verdict"]' in gate, "the gate must read summary.verdict from the producer's JSON output"
    assert "pass" in gate and "hard_pass" in gate
    assert "invest" in gate and "more_diligence" in gate
    low = gate.lower()
    assert "skip" in low, "the gate must be explicitly skippable on non-decline verdicts"


def test_skill_md_decline_gate_two_step_pattern() -> None:
    """The gate must follow this fleet's mandatory two-step shape: a plain
    chat message first, then a SEPARATE one-sentence AskUserQuestion call —
    not a single combined prompt (AskUserQuestion renders as plain text, so
    detailed content must live in the preceding chat message)."""
    gate = _skill_md_section("### Step 8.5: Decline Confirmation Gate (conditional)")
    assert "Step A" in gate and "Step B" in gate
    assert "chat message" in gate.lower()
    assert "AskUserQuestion" in gate
    a_idx = gate.index("Step A")
    b_idx = gate.index("Step B")
    assert a_idx < b_idx, "Step A (chat message) must precede Step B (AskUserQuestion)"


def test_skill_md_decline_gate_never_shows_bare_verdict_token_to_founder() -> None:
    """The gate's founder-facing chat message and AskUserQuestion text must
    render the verdict in words ('Decline'), never the bare pass/hard_pass
    enum a founder could misread as approval — same rule as the rest of this
    skill's founder-facing narration."""
    gate = _skill_md_section("### Step 8.5: Decline Confirmation Gate (conditional)")
    assert "Decline" in gate
    # The literal founder-facing example message/question must not surface a
    # bare pass/hard_pass token as the rendered outcome word.
    example_start = gate.index("Example:")
    question_start = gate.index("with a one-sentence, plain-text")
    founder_facing = gate[example_start:question_start] + gate[question_start : question_start + 400]
    assert '"pass"' not in founder_facing
    assert "hard_pass" not in founder_facing


def test_skill_md_decline_gate_does_not_alter_consensus_mismatch_rule() -> None:
    """The new gate must sit ALONGSIDE the existing CONSENSUS_SCORE_MISMATCH
    disposition rule in Step 9, not replace or weaken it — that rule's
    'present the mechanical verdict, never re-run to force agreement'
    guidance must survive byte-for-byte."""
    step9 = _skill_md_section("### Step 9: Compose and Validate Report")
    assert "CONSENSUS_SCORE_MISMATCH disposition rule" in step9
    assert "do NOT re-run anything or try to make" in step9
    assert "mechanical score is authoritative for the headline verdict" in step9
    # And the new gate must explicitly disclaim replacing it.
    gate = _skill_md_section("### Step 8.5: Decline Confirmation Gate (conditional)")
    assert "CONSENSUS_SCORE_MISMATCH" in gate


def test_skill_md_decline_gate_hold_off_branch_does_not_delete_artifacts() -> None:
    """Choosing to hold off must never touch already-written artifacts under
    $SIM_DIR (the append-only outputs-mount rule from Step 0 applies here
    too) and must not silently continue to Step 9+."""
    gate = _skill_md_section("### Step 8.5: Decline Confirmation Gate (conditional)")
    hold_idx = gate.index('If "Hold off"')
    hold_section = gate[hold_idx : hold_idx + 700]
    assert "do NOT run" in hold_section or "do not run" in hold_section.lower()
    assert "compose_report.py" in hold_section


# ============================================================
# IC-11 coverage FLOOR — you cannot decline a company you were told nothing about
#
# The cap (invest -> more_diligence on thin coverage) shipped one-directional, so
# the same excluded denominator that inflates conviction was free to deflate it: a
# founder who supplied almost nothing left a handful of applicable dimensions, a
# couple of concerns among them, and the deliverable returned a hard "Decline" at
# 18.2% conviction. Low coverage is an absence of information, not a negative
# finding, and the two must never read the same to a founder.
# ============================================================


def _thin_coverage_items(concerns: int = 2, to_confirm: int = 20) -> list[dict]:
    """Mostly-undisclosed payload: `to_confirm` unknowns plus a few concerns.

    Reproduces the live shape — enough to_confirm to exceed HIGH_TO_CONFIRM_COUNT,
    and a low conviction among the few dimensions that were assessable.
    """
    overrides: dict[str, dict] = {}
    for did in _DIMENSION_IDS[:to_confirm]:
        overrides[did] = {"status": "to_confirm", "evidence": "not disclosed", "notes": None}
    for did in _DIMENSION_IDS[to_confirm : to_confirm + concerns]:
        overrides[did] = {"status": "concern", "evidence": "weak", "notes": "concern"}
    return _make_dimension_items(overrides=overrides)


def test_thin_coverage_never_returns_a_decline() -> None:
    """The regression: low conviction from missing data must not read as `pass`."""
    payload = json.dumps({"items": _thin_coverage_items(concerns=5, to_confirm=20)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["to_confirm"] == 20
    assert s["conviction_score"] < 50.0, "fixture must land in the pass band to exercise the floor"
    assert s["verdict"] == "more_diligence", f"thin coverage produced a decline: {s['verdict']}"
    assert s["coverage_floored"] is True
    assert "LOW_COVERAGE_VERDICT_FLOOR" in s["warnings"]


def test_coverage_floor_is_flagged_not_silent() -> None:
    """A silently-raised verdict is its own defect — the founder must see why."""
    payload = json.dumps({"items": _thin_coverage_items(concerns=5, to_confirm=20)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "LOW_COVERAGE_VERDICT_FLOOR" in data["summary"]["warnings"]


def test_coverage_floor_does_not_soften_a_dealbreaker() -> None:
    """A blocking dealbreaker is a substantive finding, not an absence of data.

    hard_pass must survive thin coverage untouched — the floor exists to stop a
    data-availability decline, not to make every thin review inconclusive.
    """
    overrides: dict[str, dict] = {
        did: {"status": "to_confirm", "evidence": "not disclosed", "notes": None} for did in _DIMENSION_IDS[:20]
    }
    overrides[_DIMENSION_IDS[20]] = {
        "status": "dealbreaker",
        "evidence": "hard blocker",
        "notes": "blocking",
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["verdict"] == "hard_pass", "a blocking dealbreaker must not be floored away"
    assert s["coverage_floored"] is False


def test_coverage_floor_leaves_good_coverage_alone() -> None:
    """A genuine pass on well-covered dimensions stays a pass."""
    overrides = {did: {"status": "concern", "evidence": "test", "notes": "concern"} for did in _DIMENSION_IDS[:15]}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["to_confirm"] == 0
    assert s["verdict"] == "pass", "an assessed decline must remain a decline"
    assert s["coverage_floored"] is False
    assert "LOW_COVERAGE_VERDICT_FLOOR" not in s["warnings"]


def test_coverage_cap_still_holds_in_the_other_direction() -> None:
    """The pre-existing cap must be unaffected by adding the floor."""
    overrides = {
        did: {"status": "to_confirm", "evidence": "not disclosed", "notes": None} for did in _DIMENSION_IDS[:20]
    }
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["conviction_score"] == 100.0, "8 strong of 8 applicable"
    assert s["verdict"] == "more_diligence"
    assert s["coverage_capped"] is True
    assert s["coverage_floored"] is False, "cap and floor are mutually exclusive"


# ============================================================
# Thin scoring base — misleading precision
#
# Found by a live critique run of the verdict-floor fix: 23 to_confirm + 3 n/a
# left 2 applicable dimensions, one strong, and the report headlined "50.0% —
# More Diligence — promising but needs more evidence". Arithmetically correct;
# reads as a considered midpoint arrived at across the whole framework.
#
# The cap and floor guard the VERDICT. Nothing guarded the SCORE's precision, and
# the decimal place is what does the damage.
# ============================================================


def _thin_base_items(applicable: int = 2, na: int = 3) -> list[dict]:
    """Leave exactly `applicable` scoreable dimensions; the rest undisclosed/na."""
    overrides: dict[str, dict] = {}
    to_confirm = len(_DIMENSION_IDS) - applicable - na
    for did in _DIMENSION_IDS[:to_confirm]:
        overrides[did] = {"status": "to_confirm", "evidence": "not disclosed", "notes": None}
    for did in _DIMENSION_IDS[to_confirm : to_confirm + na]:
        overrides[did] = {"status": "not_applicable", "evidence": "n/a", "notes": None}
    # First applicable strong, remainder concern -> a round-looking percentage.
    for i, did in enumerate(_DIMENSION_IDS[to_confirm + na :]):
        overrides[did] = (
            {"status": "strong_conviction", "evidence": "strong", "notes": None}
            if i == 0
            else {"status": "concern", "evidence": "weak", "notes": "concern"}
        )
    return _make_dimension_items(overrides=overrides)


def test_thin_scoring_base_is_flagged_with_its_denominator() -> None:
    """The exact live shape: 2 of 28 applicable, scoring a tidy 50.0%."""
    payload = json.dumps({"items": _thin_base_items(applicable=2, na=3)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["applicable"] == 2
    assert s["conviction_score"] == 50.0
    assert s["conviction_basis"] == {"applicable": 2, "total": 28, "sufficient": False}
    assert "LOW_CONVICTION_BASIS" in s["warnings"]


def test_thin_base_changes_neither_the_score_nor_the_verdict() -> None:
    """This guards PRESENTATION only.

    Moving the score would destroy the transparency the to_confirm design exists
    for, and moving the verdict would duplicate the cap/floor with a third rule
    interacting with both.
    """
    payload = json.dumps({"items": _thin_base_items(applicable=2, na=3)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["conviction_score"] == 50.0, "the score must be reported unchanged"
    assert s["verdict"] == "more_diligence", "50.0 is genuinely in the more_diligence band"
    assert s["coverage_floored"] is False
    assert s["coverage_capped"] is False


def test_sufficient_base_is_not_flagged() -> None:
    """A fully-scored company must not carry the thin-base flag."""
    payload = json.dumps({"items": _make_dimension_items()})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["conviction_basis"]["sufficient"] is True
    assert "LOW_CONVICTION_BASIS" not in s["warnings"]


def test_thin_base_threshold_boundary() -> None:
    """8 applicable is sufficient; 7 is not. Pins the constant's meaning."""
    for applicable, expected in ((8, True), (7, False)):
        payload = json.dumps({"items": _thin_base_items(applicable=applicable, na=0)})
        rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
        assert rc == 0
        assert data is not None
        s = data["summary"]
        assert s["applicable"] == applicable
        assert s["conviction_basis"]["sufficient"] is expected, (
            f"applicable={applicable} sufficiency should be {expected}"
        )


def test_zero_applicable_does_not_also_raise_thin_base() -> None:
    """ZERO_APPLICABLE_DIMENSIONS already covers all-n/a — don't double-warn."""
    overrides = {did: {"status": "not_applicable", "evidence": "n/a", "notes": None} for did in _DIMENSION_IDS}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert "ZERO_APPLICABLE_DIMENSIONS" in s["warnings"]
    assert "LOW_CONVICTION_BASIS" not in s["warnings"]


# ============================================================
# A0 — the coverage guards are conditioned on COVERAGE, not on the verdict
#
# Found by adversarial review of the fix plan. The cap and floor were each
# conditioned on the verdict they moved (== "invest" / == "pass"), which left the
# middle uncovered: a live run with 23 of 28 undisclosed and 2 applicable scored
# 50.0%, landed in the more_diligence band unaided, tripped neither guard, and was
# reported as "promising but needs more evidence" with ZERO warnings.
# ============================================================


def test_thin_coverage_in_band_is_flagged_as_held() -> None:
    """The observed live shape: 23 to_confirm, 3 n/a, 2 applicable, 50.0%."""
    payload = json.dumps({"items": _thin_base_items(applicable=2, na=3)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["conviction_score"] == 50.0
    assert s["verdict"] == "more_diligence"
    # Neither mover fires — nothing needed moving — but it must not read as merits.
    assert s["coverage_capped"] is False
    assert s["coverage_floored"] is False
    assert s["coverage_held"] is True
    assert "LOW_COVERAGE_VERDICT_HELD" in s["warnings"]


def test_held_verdict_never_reads_as_promising() -> None:
    """The report headline is the whole point of the flag."""
    payload = json.dumps({"items": _thin_base_items(applicable=2, na=3)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0 and data is not None
    # Rendering is asserted through compose in test_ic_sim_report_* ; here pin the
    # contract the renderer keys on, so a renderer change cannot silently regress.
    assert data["summary"]["coverage_held"] is True


def test_good_coverage_in_band_is_NOT_held() -> None:
    """A genuine merits-based more_diligence keeps the merits wording."""
    overrides = {did: {"status": "concern", "evidence": "t", "notes": "c"} for did in _DIMENSION_IDS[:14]}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0 and data is not None
    s = data["summary"]
    assert s["verdict"] == "more_diligence" and s["conviction_score"] == 50.0
    assert s["applicable"] == 28
    assert s["coverage_held"] is False
    assert "LOW_COVERAGE_VERDICT_HELD" not in s["warnings"]


def test_thin_via_not_applicable_alone_still_counts_as_thin() -> None:
    """`to_confirm` alone cannot see a company thinned out by not_applicable.

    This is why the condition includes `applicable`, not just the to_confirm count:
    5 n/a-heavy dimensions leave the same near-empty scorecard.
    """
    overrides: dict[str, dict] = {
        did: {"status": "not_applicable", "evidence": "n/a", "notes": None} for did in _DIMENSION_IDS[:22]
    }
    overrides[_DIMENSION_IDS[22]] = {"status": "strong_conviction", "evidence": "s", "notes": None}
    for did in _DIMENSION_IDS[23:]:
        overrides[did] = {"status": "concern", "evidence": "w", "notes": "c"}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0 and data is not None
    s = data["summary"]
    assert s["to_confirm"] == 0, "no to_confirm at all — the old condition could not fire"
    assert 0 < s["applicable"] < 8
    assert s["coverage_held"] or s["coverage_floored"], "thin-by-n/a must still be caught"


def test_dealbreaker_survives_all_three_coverage_guards() -> None:
    """A substantive finding is never softened by thin coverage."""
    overrides: dict[str, dict] = {
        did: {"status": "to_confirm", "evidence": "nd", "notes": None} for did in _DIMENSION_IDS[:20]
    }
    overrides[_DIMENSION_IDS[20]] = {"status": "dealbreaker", "evidence": "blocker", "notes": "b"}
    payload = json.dumps({"items": _make_dimension_items(overrides=overrides)})
    rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=payload)
    assert rc == 0 and data is not None
    s = data["summary"]
    assert s["verdict"] == "hard_pass"
    assert (s["coverage_capped"], s["coverage_floored"], s["coverage_held"]) == (False, False, False)


def test_the_three_coverage_flags_are_mutually_exclusive() -> None:
    """They partition one condition by which verdict it met; never two at once."""
    cases = [
        _thin_base_items(applicable=2, na=3),  # held
        [  # capped: 20 to_confirm, rest strong -> 100%
            {"id": d, "status": ("to_confirm" if i < 20 else "strong_conviction"), "evidence": "e", "notes": None}
            for i, d in enumerate(_DIMENSION_IDS)
        ],
        [  # floored: 20 to_confirm, 1 strong + 7 concern -> 12.5%
            {
                "id": d,
                "status": ("to_confirm" if i < 20 else "strong_conviction" if i == 20 else "concern"),
                "evidence": "e",
                "notes": None,
            }
            for i, d in enumerate(_DIMENSION_IDS)
        ],
    ]
    for items in cases:
        rc, data, _ = run_script("score_dimensions.py", ["--pretty"], stdin_data=json.dumps({"items": items}))
        assert rc == 0 and data is not None
        s = data["summary"]
        set_count = sum(bool(s[k]) for k in ("coverage_capped", "coverage_floored", "coverage_held"))
        assert set_count == 1, f"expected exactly one flag, got {set_count}: {s['verdict']}"


# --- producer refusal + downstream detection (fleet-wide loud-failure pass) ----


def test_score_dimensions_invalid_input_exits_nonzero_and_writes_nothing() -> None:
    """`score_dimensions.py` refuses loudly instead of clobbering its own artifact.

    It shared a defect with every other producer in the fleet: exit 0, an `{"ok":true}` receipt,
    and an analysis-free stub written over the canonical file. SKILL.md's producer-error branch
    is written as "the pipe fails next", so with exit 0 it could never fire — a rejected run and
    a successful one were indistinguishable to the caller.
    """
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "score_dimensions.json")
        with open(out, "w") as f:
            f.write('{"sentinel": true}')
        payload = json.dumps({"items": [{"id": "bogus", "status": "concern", "rationale": "x"}]})
        rc, data, stderr = run_script("score_dimensions.py", ["--run-id", "RID", "-o", out], stdin_data=payload)
        assert rc == 1, "a rejected dimension set must exit non-zero"
        assert stderr.strip(), "a rejected run must say so on stderr"
        assert data is not None and data["validation"]["status"] == "invalid"
        with open(out) as f:
            assert json.load(f) == {"sentinel": True}, "the canonical artifact was clobbered"


def test_compose_flags_an_invalid_score_dimensions_at_high_severity() -> None:
    """A rejected scoring step must not surface only as a medium symptom."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = {"validation": {"status": "invalid", "errors": ["bad input"]}}
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert data is not None, err
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "ARTIFACT_INVALID"]
    assert hits, "a rejected producer artifact must raise ARTIFACT_INVALID"
    assert hits[0]["severity"] == "high", "must not be acceptable-away"
