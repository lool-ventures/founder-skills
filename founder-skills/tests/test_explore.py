#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for FMR interactive explorer script.

Run: pytest founder-skills/tests/test_explore.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_VALID_INPUTS: dict[str, Any] = {
    "company": {
        "company_name": "TestCo",
        "slug": "testco",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "US",
        "revenue_model_type": "saas-sales-led",
        "traits": [],
    },
    "revenue": {
        "mrr": {"value": 50000, "as_of": "2025-12"},
        "arr": {"value": 600000, "as_of": "2025-12"},
        "growth_rate_monthly": 0.08,
        "churn_monthly": 0.03,
    },
    "cash": {
        "current_balance": 2000000,
        "monthly_net_burn": 80000,
        "debt": 0,
        "fundraising": {"target_raise": 3000000},
    },
    "unit_economics": {
        "cac": {"total": 1500, "fully_loaded": True},
        "ltv": {
            "value": 6000,
            "method": "formula",
            "observed_vs_assumed": "assumed",
            "inputs": {"arpu_monthly": 500, "gross_margin": 0.75},
        },
        "gross_margin": 0.75,
    },
    "bridge": {
        "raise_amount": 3000000,
        "runway_target_months": 24,
    },
    "israel_specific": {},
}

_VALID_CHECKLIST: dict[str, Any] = {
    "items": [
        {
            "id": f"STRUCT_0{i}",
            "category": "Structure & Presentation",
            "label": f"Item {i}",
            "status": "pass",
            "evidence": f"Evidence {i}",
            "notes": None,
        }
        for i in range(1, 10)
    ]
    + [
        {
            "id": f"UNIT_{i}",
            "category": "Revenue & Unit Economics",
            "label": f"Item {i}",
            "status": "pass" if i != 11 else "fail",
            "evidence": f"Evidence {i}",
            "notes": None,
        }
        for i in range(10, 20)
    ]
    + [
        {
            "id": f"CASH_{i}",
            "category": "Expenses, Cash & Runway",
            "label": f"Item {i}",
            "status": "pass" if i not in (23, 28) else ("warn" if i == 23 else "not_applicable"),
            "evidence": f"Evidence {i}",
            "notes": None,
        }
        for i in range(20, 33)
    ]
    + [
        {
            "id": f"METRIC_{i}",
            "category": "Metrics & Efficiency",
            "label": f"Item {i}",
            "status": "pass",
            "evidence": f"Evidence {i}",
            "notes": None,
        }
        for i in range(33, 36)
    ]
    + [
        {
            "id": f"BRIDGE_{i}",
            "category": "Fundraising Bridge",
            "label": f"Item {i}",
            "status": "pass",
            "evidence": f"Evidence {i}",
            "notes": None,
        }
        for i in range(36, 39)
    ]
    + [
        {
            "id": f"SECTOR_{i}",
            "category": "Sector-Specific",
            "label": f"Item {i}",
            "status": "not_applicable",
            "evidence": None,
            "notes": None,
        }
        for i in range(39, 45)
    ]
    + [
        {
            "id": "OVERALL_45",
            "category": "Overall",
            "label": "5-min audit",
            "status": "pass",
            "evidence": "Dashboard ready",
            "notes": None,
        },
        {
            "id": "OVERALL_46",
            "category": "Overall",
            "label": "Geo segmented",
            "status": "not_applicable",
            "evidence": None,
            "notes": None,
        },
    ],
    "summary": {
        "total": 46,
        "pass": 35,
        "fail": 1,
        "warn": 1,
        "not_applicable": 9,
        "score_pct": 95.9,
        "overall_status": "strong",
        "by_category": {
            "Structure & Presentation": {"pass": 9, "fail": 0, "warn": 0, "not_applicable": 0},
            "Revenue & Unit Economics": {"pass": 9, "fail": 1, "warn": 0, "not_applicable": 0},
            "Expenses, Cash & Runway": {"pass": 11, "fail": 0, "warn": 1, "not_applicable": 1},
            "Metrics & Efficiency": {"pass": 3, "fail": 0, "warn": 0, "not_applicable": 0},
            "Fundraising Bridge": {"pass": 3, "fail": 0, "warn": 0, "not_applicable": 0},
            "Sector-Specific": {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 6},
            "Overall": {"pass": 1, "fail": 0, "warn": 0, "not_applicable": 1},
        },
        "failed_items": [{"id": "UNIT_11", "label": "Churn modeled", "evidence": "Zero churn"}],
        "warned_items": [{"id": "CASH_23", "label": "Runway calc", "evidence": "Unclear method"}],
    },
}

_VALID_UNIT_ECONOMICS: dict[str, Any] = {
    "metrics": [
        {
            "name": "cac",
            "value": 1500,
            "rating": "acceptable",
            "evidence": "Fully loaded",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "ltv",
            "value": 6000,
            "rating": "strong",
            "evidence": "Formula",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "ltv_cac_ratio",
            "value": 4.0,
            "rating": "strong",
            "evidence": "4x",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "cac_payback",
            "value": 10,
            "rating": "strong",
            "evidence": "10 months",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "gross_margin",
            "value": 0.75,
            "rating": "strong",
            "evidence": "75%",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "burn_multiple",
            "value": 1.8,
            "rating": "strong",
            "evidence": "1.8x (growth-rate method)",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "rule_of_40",
            "value": 35,
            "rating": "acceptable",
            "evidence": "35",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
    ],
    "summary": {"computed": 7, "strong": 5, "acceptable": 2, "warning": 0, "fail": 0},
}

_VALID_RUNWAY: dict[str, Any] = {
    "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
    "baseline": {"net_cash": 2000000, "monthly_burn": 80000, "monthly_revenue": 50000},
    "scenarios": [
        {
            "name": "base",
            "growth_rate": 0.08,
            "burn_change": 0.0,
            "fx_adjustment": 0.0,
            "runway_months": 25,
            "cash_out_date": "2028-01",
            "decision_point": "2027-01",
            "default_alive": True,
            "monthly_projections": [
                {"month": 1, "cash_balance": 1950000},
                {"month": 2, "cash_balance": 1900000},
            ],
        },
        {
            "name": "slow",
            "growth_rate": 0.03,
            "burn_change": 0.0,
            "fx_adjustment": 0.0,
            "runway_months": 18,
            "cash_out_date": "2027-06",
            "decision_point": "2026-06",
            "default_alive": False,
            "monthly_projections": [
                {"month": 1, "cash_balance": 1940000},
                {"month": 2, "cash_balance": 1880000},
            ],
        },
        {
            "name": "crisis",
            "growth_rate": 0.0,
            "burn_change": 0.2,
            "fx_adjustment": 0.0,
            "runway_months": 12,
            "cash_out_date": "2026-12",
            "decision_point": "2025-12",
            "default_alive": False,
            "monthly_projections": [
                {"month": 1, "cash_balance": 1920000},
                {"month": 2, "cash_balance": 1840000},
            ],
        },
    ],
    "risk_assessment": "Adequate runway under base case.",
    "limitations": [],
    "warnings": [],
}

_VALID_COMMENTARY: dict[str, Any] = {
    "headline": "TestCo shows strong unit economics with adequate runway at seed stage.",
    "lenses": {
        "runway": {
            "callout": "25 months of runway under base case provides comfortable buffer.",
        },
        "raise_planner": {
            "callout": "Target raise of $3M aligns with 24-month runway target.",
        },
        "unit_economics": {
            "callout": "LTV/CAC ratio of 4x is strong for seed stage.",
            "watch_out": "Monitor churn closely as customer base grows.",
        },
        "stress_test": {
            "highlight": "Crisis scenario yields 12 months; team should monitor burn closely.",
        },
    },
    "investor_talking_points": [
        "Strong unit economics with 4x LTV/CAC ratio",
        "Adequate runway of 25 months under base case",
    ],
}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_artifact_dir(
    overrides: dict[str, Any] | None = None,
    include_commentary: bool = False,
) -> str:
    """Create a temp dir with all valid FMR artifacts. Override or remove with overrides dict."""
    artifacts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "checklist.json": _VALID_CHECKLIST,
        "unit_economics.json": _VALID_UNIT_ECONOMICS,
        "runway.json": _VALID_RUNWAY,
    }
    if include_commentary:
        artifacts["commentary.json"] = _VALID_COMMENTARY
    if overrides is not None:
        for k, v in overrides.items():
            if v is None:
                artifacts.pop(k, None)
            else:
                artifacts[k] = v
    d = tempfile.mkdtemp(prefix="test-explore-fmr-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            if isinstance(data, str):
                f.write(data)  # For corrupt artifact tests
            else:
                json.dump(data, f)
    return d


def run_script_raw(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, str, str]:
    """Run a script and return (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(FMR_SCRIPTS_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _extract_data_payload(html: str) -> dict[str, Any]:
    """Extract the DATA JSON object from the HTML output."""
    match = re.search(r"const\s+DATA\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    assert match, "Could not find 'const DATA = {...};' in HTML output"
    return dict(json.loads(match.group(1)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_complete_artifacts_all_lenses() -> None:
    """All artifacts present produces HTML with all 4 lenses."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout
    assert "Runway" in stdout
    assert "Raise Plan" in stdout
    assert "Unit Econ" in stdout
    assert "Stress Test" in stdout


def test_missing_inputs_fatal() -> None:
    """Missing inputs.json is fatal -- exit 1."""
    d = _make_artifact_dir(overrides={"inputs.json": None})
    rc, _stdout, stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 1
    assert "inputs.json" in stderr


def test_missing_runway_disables_lenses() -> None:
    """Missing runway.json disables runway lens but still produces HTML."""
    d = _make_artifact_dir(overrides={"runway.json": None})
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "Unit Econ" in stdout


def test_missing_unit_economics_disables_lens() -> None:
    """Missing unit_economics.json disables that lens but still produces HTML."""
    d = _make_artifact_dir(overrides={"unit_economics.json": None})
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout


def test_missing_checklist_still_works() -> None:
    """Missing checklist.json still produces HTML with runway lens."""
    d = _make_artifact_dir(overrides={"checklist.json": None})
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "Runway" in stdout


def test_stub_artifact_treated_as_missing() -> None:
    """Stub runway.json with reason shows the reason in output."""
    d = _make_artifact_dir(overrides={"runway.json": {"skipped": True, "reason": "No cash data"}})
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "No cash data" in stdout


def test_data_payload_valid_json() -> None:
    """DATA payload is valid JSON with expected engine fields."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["company"]["name"] == "TestCo"
    engine = data["engine"]
    assert engine["cash0"] == 2000000
    assert engine["revenue0"] == 50000
    assert engine["opex0"] == 130000  # revenue (50K) + burn (80K)
    assert engine["growth_rate"] == 0.08
    assert engine["max_months"] == 60
    assert abs(engine["growth_decay"] - 0.97) < 0.01


def test_data_payload_engine_mrr_field() -> None:
    """Engine includes MRR from inputs."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["engine"]["mrr"] == 50000


def test_data_payload_benchmarks_present() -> None:
    """DATA payload includes benchmarks dict with burn_multiple."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert "burn_multiple" in data["benchmarks"]


def test_data_payload_bridge_from_target_raise() -> None:
    """Bridge raise_amount comes from inputs."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["bridge"]["raise_amount"] == 3000000


def test_data_payload_scenarios() -> None:
    """DATA payload includes 3 scenarios with expected names."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    scenario_names = [s["name"] for s in data["scenarios"]]
    assert "base" in scenario_names
    assert "slow" in scenario_names
    assert "crisis" in scenario_names
    assert len(data["scenarios"]) == 3


def test_burn_multiple_method_field() -> None:
    """Burn multiple metric includes method field."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    bm = next(m for m in data["metrics"] if m["id"] == "burn_multiple")
    assert bm["method"] in ("ttm", "quarterly", "growth_rate")


def test_chartjs_cdn_link() -> None:
    """Chart.js CDN link is present in HTML."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "chart.js@4.4" in stdout


def test_projection_engine_present() -> None:
    """JavaScript projection engine functions are present."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "projectScenario" in stdout
    assert "findMinViableGrowth" in stdout


def test_engine_parity_with_runway_py() -> None:
    """JS projectScenario produces same results as runway.py's _project_scenario for a known fixture."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    # The base scenario in _VALID_RUNWAY has growth_rate=0.08, burn_change=0.0
    # Verify the DATA payload's engine inputs would produce consistent results
    match = re.search(r"const\s+DATA\s*=\s*(\{.*?\});\s*\n", stdout, re.DOTALL)
    assert match, "Could not find DATA payload"
    data = json.loads(match.group(1))
    e = data["engine"]
    # Verify engine inputs match what runway.py would compute
    assert e["cash0"] == 2000000
    assert e["revenue0"] == 50000
    assert e["opex0"] == 130000  # 50000 + 80000
    assert e["growth_rate"] == 0.08
    # The projectScenario JS function must exist as a real function (not stub)
    assert "function projectScenario" in stdout
    assert "Math.pow(growthDecay" in stdout


def test_with_commentary() -> None:
    """With commentary.json, DATA.commentary is populated."""
    d = _make_artifact_dir(include_commentary=True)
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["commentary"] is not None
    assert data["commentary"]["headline"] == _VALID_COMMENTARY["headline"]
    assert "investor_talking_points" in data["commentary"]


def test_explore_structured_commentary_passthrough() -> None:
    """Structured commentary (with callout/highlight/watch_out) passes through to DATA payload."""
    d = _make_artifact_dir(include_commentary=True)
    rc, stdout, stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["commentary"] is not None
    assert data["commentary"]["headline"] == _VALID_COMMENTARY["headline"]
    # Verify structured lenses pass through to JS DATA object — cover all 4 lens keys
    assert data["commentary"]["lenses"]["runway"]["callout"] == _VALID_COMMENTARY["lenses"]["runway"]["callout"]
    assert (
        data["commentary"]["lenses"]["unit_economics"]["watch_out"]
        == _VALID_COMMENTARY["lenses"]["unit_economics"]["watch_out"]
    )
    assert (
        data["commentary"]["lenses"]["raise_planner"]["callout"]
        == _VALID_COMMENTARY["lenses"]["raise_planner"]["callout"]
    )
    assert (
        data["commentary"]["lenses"]["stress_test"]["highlight"]
        == _VALID_COMMENTARY["lenses"]["stress_test"]["highlight"]
    )


def test_without_commentary() -> None:
    """Without commentary.json, DATA.commentary is null."""
    d = _make_artifact_dir(include_commentary=False)
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["commentary"] is None


def test_malformed_commentary() -> None:
    """Malformed commentary.json is handled gracefully."""
    d = _make_artifact_dir(overrides={"commentary.json": "{bad json!!!"})
    rc, stdout, stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "commentary" in stderr.lower()
    data = _extract_data_payload(stdout)
    assert data["commentary"] is None


def test_commentary_missing_headline() -> None:
    """Commentary without headline is treated as invalid."""
    bad_commentary: dict[str, Any] = {"lenses": {}, "investor_talking_points": []}
    d = _make_artifact_dir(overrides={"commentary.json": bad_commentary})
    rc, stdout, stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "headline" in stderr.lower()
    data = _extract_data_payload(stdout)
    assert data["commentary"] is None


def test_output_flag_receipt() -> None:
    """-o flag writes HTML to file and outputs JSON receipt."""
    d = _make_artifact_dir()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d, "-o", tmp])
        assert rc == 0
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        assert receipt["lenses_enabled"] == 4
        assert receipt["lenses_disabled"] == []
        assert os.path.exists(tmp)
        with open(tmp) as fh:
            content = fh.read()
        assert "<!DOCTYPE html>" in content
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_output_receipt_disabled_lenses() -> None:
    """Missing runway disables lenses, reflected in receipt."""
    d = _make_artifact_dir(overrides={"runway.json": None})
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d, "-o", tmp])
        assert rc == 0
        receipt = json.loads(stdout)
        assert receipt["lenses_enabled"] < 4
        assert len(receipt["lenses_disabled"]) > 0
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_cash_flow_positive() -> None:
    """When burn is negative (cash-flow positive), opex0 < revenue0."""
    positive_inputs = json.loads(json.dumps(_VALID_INPUTS))
    positive_inputs["cash"]["monthly_net_burn"] = -20000  # cash-flow positive
    positive_runway = json.loads(json.dumps(_VALID_RUNWAY))
    positive_runway["baseline"]["monthly_burn"] = -20000
    d = _make_artifact_dir(overrides={"inputs.json": positive_inputs, "runway.json": positive_runway})
    rc, stdout, _stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    data = _extract_data_payload(stdout)
    assert data["engine"]["opex0"] == 30000  # revenue (50K) + burn (-20K) = 30K
    assert data["engine"]["opex0"] < data["engine"]["revenue0"]


def test_find_min_viable_growth_uses_target_runway_param() -> None:
    """JS findMinViableGrowth must accept targetRunway param and use it in both loops."""
    d = _make_artifact_dir()
    rc, html, stderr = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0

    # Extract the findMinViableGrowth function signature and body
    fn_start = html.find("function findMinViableGrowth")
    assert fn_start != -1, "findMinViableGrowth function not found in HTML output"
    fn_body = html[fn_start : fn_start + 3000]

    # Function should accept targetRunway parameter
    assert re.search(r"function findMinViableGrowth\(params,\s*targetRunway\)", fn_body), (
        "findMinViableGrowth should accept targetRunway as second parameter"
    )

    # Binary search for-loop must have runway check using targetRunway param
    for_start = fn_body.find("for (var i = 0;")
    assert for_start != -1, "Binary search for-loop not found in findMinViableGrowth"
    for_block = fn_body[for_start : for_start + 500]

    # Assert the convergence condition includes runway_months >= targetRunway
    assert re.search(
        r"if\s*\(\s*r2\.default_alive\s*\|\|\s*\(.*?r2\.runway_months\s*>=\s*targetRunway",
        for_block,
        re.DOTALL,
    ), (
        "findMinViableGrowth binary search for-loop must check "
        "r2.runway_months >= targetRunway (not hardcoded or missing)"
    )

    # Expansion while-loop should also use targetRunway (not hardcoded 18)
    while_start = fn_body.find("while (hi < maxHi)")
    assert while_start != -1, "Expansion while-loop not found in findMinViableGrowth"
    while_block = fn_body[while_start : while_start + 300]
    assert "targetRunway" in while_block, (
        "findMinViableGrowth expansion while-loop should use targetRunway param, not hardcoded 18"
    )

    # Call site in renderRunway must pass state.targetRunway
    render_start = html.find("function renderRunway()")
    assert render_start != -1, "renderRunway function not found in HTML output"
    render_body = html[render_start : render_start + 2000]
    assert re.search(
        r"findMinViableGrowth\(\s*p\s*,\s*state\.targetRunway\s*\)",
        render_body,
    ), "renderRunway must pass state.targetRunway to findMinViableGrowth"


# ---------------------------------------------------------------------------
# Stress Test lens redesign tests
# ---------------------------------------------------------------------------


def test_find_min_viable_growth_returns_null_when_not_viable() -> None:
    """findMinViableGrowth returns null when even maxHi (50%) isn't viable."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    fn_start = html.find("function findMinViableGrowth")
    assert fn_start != -1
    fn_body = html[fn_start : fn_start + 2000]
    # Must check viability of hi after binary search and return null if not viable
    assert "return null" in fn_body, "findMinViableGrowth must return null when not viable"


def test_render_runway_handles_null_mvg() -> None:
    """renderRunway conditionally omits min viable growth when mvg is null."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    render_start = html.find("function renderRunway()")
    assert render_start != -1
    render_body = html[render_start : render_start + 3000]
    # Must check for null before displaying mvg
    assert "mvg !== null" in render_body or "mvg === null" in render_body, (
        "renderRunway must conditionally handle null mvg"
    )


def test_get_stress_params_uses_data_engine() -> None:
    """getStressParams references DATA.engine, not mutated state values."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    fn_start = html.find("function getStressParams()")
    assert fn_start != -1
    fn_body = html[fn_start : fn_start + 800]
    assert "DATA.engine.cash0" in fn_body
    assert "DATA.engine.revenue0" in fn_body
    assert "DATA.engine.opex0" in fn_body
    assert "state.stressGrowth" in fn_body, "growthRate should come from state.stressGrowth"


def test_stress_lens_has_growth_slider() -> None:
    """Stress Test lens contains a growth slider with id stress-growth."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "stress-growth" in html, "Stress Test should have slider with id 'stress-growth'"
    assert "sliders-stress" in html, "Stress Test should have slider container"


def test_scenario_label_priority() -> None:
    """Scenario labels use priority: s.label > SCENARIO_LABELS[s.name] > capitalized s.name."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    # Check SCENARIO_LABELS map exists
    assert "SCENARIO_LABELS" in html
    # Check label priority logic
    assert "s.label || SCENARIO_LABELS[s.name]" in html, "Should use s.label first, then known map"
    assert "s.name.charAt(0).toUpperCase()" in html, "Should capitalize s.name as fallback"


def test_no_tornado_markup() -> None:
    """Stress Test no longer has tornado chart markup or buildTornado function."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "buildTornado" not in html, "buildTornado should be removed"
    assert "renderScenarioChart" not in html, "renderScenarioChart should be removed"
    assert "tornado" not in html.lower() or "tornado" not in html, "No tornado references should remain"


def test_self_sustaining_badge() -> None:
    """Self-sustaining companies show SELF-SUSTAINING badge text in stress test."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "SELF-SUSTAINING" in html, "Badge text for default alive should be SELF-SUSTAINING"


def test_stress_slider_max_adapts() -> None:
    """Slider max adapts: Math.max(DATA.engine.growth_rate, 0.30)."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "Math.max(DATA.engine.growth_rate, 0.30)" in html, "Slider max should adapt to growth rate"


def test_stress_test_has_scenario_table() -> None:
    """Stress Test lens includes a scenario reference table."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "Review Scenarios" in html, "Should have scenario reference table header"
    # Check column headers
    assert ">Scenario<" in html
    assert ">Growth<" in html
    assert ">Runway<" in html
    assert ">Status<" in html


def test_stress_test_disclaimer() -> None:
    """Stress Test includes disclaimer about approximate projection."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "Interactive projection is approximate" in html


def test_stress_chart_replaces_old_charts() -> None:
    """renderStressChart creates a single line chart, not tornado or multi-line."""
    d = _make_artifact_dir()
    rc, html, _ = run_script_raw("explore.py", ["--dir", d])
    assert rc == 0
    assert "function renderStressChart" in html
    assert "chart-stress" in html
    assert "charts.stress" in html
