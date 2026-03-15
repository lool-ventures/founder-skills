#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for financial model review HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_financial_model_review.py -v
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
    },
    "revenue": {
        "arr": {"value": 600000, "as_of": "2025-12"},
        "mrr": {"value": 50000, "as_of": "2025-12"},
        "growth_rate_monthly": 0.08,
        "churn_monthly": 0.03,
    },
    "cash": {
        "current_balance": 2000000,
        "monthly_net_burn": 80000,
    },
    "unit_economics": {
        "cac": {"total": 1500, "fully_loaded": True},
        "ltv": {"value": 6000, "method": "formula", "observed_vs_assumed": "assumed"},
        "payback_months": 10,
        "gross_margin": 0.75,
    },
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
            "evidence": "1.8x",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
    ],
    "summary": {"computed": 6, "strong": 5, "acceptable": 1, "warning": 0, "fail": 0},
}

_VALID_RUNWAY: dict[str, Any] = {
    "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
    "baseline": {"net_cash": 2000000, "monthly_burn": 80000, "monthly_revenue": 50000},
    "scenarios": [
        {
            "name": "base",
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


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_artifact_dir(overrides: dict[str, Any] | None = None) -> str:
    """Create a temp dir with all valid FMR artifacts. Override or remove with overrides dict."""
    artifacts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "checklist.json": _VALID_CHECKLIST,
        "unit_economics.json": _VALID_UNIT_ECONOMICS,
        "runway.json": _VALID_RUNWAY,
    }
    if overrides is not None:
        for k, v in overrides.items():
            if v is None:
                artifacts.pop(k, None)
            else:
                artifacts[k] = v
    d = tempfile.mkdtemp(prefix="test-viz-fmr-")
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_complete_artifacts() -> None:
    """All 4 artifacts present produces valid HTML with SVG charts."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert stdout.startswith("<!DOCTYPE html>")
    assert "<svg" in stdout
    assert "TestCo" in stdout


def test_missing_optional_artifact() -> None:
    """Missing runway.json (optional for viz) -- HTML renders with placeholder, exit 0."""
    d = _make_artifact_dir(overrides={"runway.json": None})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout
    assert "No data available" in stdout or "Data unavailable" in stdout


def test_corrupt_artifact() -> None:
    """Corrupt JSON for checklist.json -- no crash, placeholder shown."""
    d = _make_artifact_dir(overrides={"checklist.json": "{corrupt json!!!}"})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "Data unavailable" in stdout


def test_stub_artifact() -> None:
    """Stub checklist.json with reason -- placeholder shows reason."""
    d = _make_artifact_dir(overrides={"checklist.json": {"skipped": True, "reason": "Not enough data"}})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "Not enough data" in stdout


def test_output_flag() -> None:
    """-o flag writes to file, stdout empty."""
    d = _make_artifact_dir()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d, "-o", tmp])
        assert rc == 0
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        assert os.path.exists(tmp)
        with open(tmp) as fh:
            content = fh.read()
        assert content.startswith("<!DOCTYPE html>")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src= or href= attributes."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
    src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
    for url in src_matches:
        if url in allowed:
            continue
        assert not url.startswith("http://"), f"External HTTP URL in attribute: {url}"
        assert not url.startswith("https://"), f"External HTTPS URL in attribute: {url}"


def test_xss_safety() -> None:
    """XSS in company name is escaped in output."""
    xss_inputs = dict(_VALID_INPUTS)
    xss_inputs["company"] = dict(_VALID_INPUTS["company"])
    xss_inputs["company"]["company_name"] = "<script>alert('xss')</script>"
    d = _make_artifact_dir(overrides={"inputs.json": xss_inputs})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "&lt;script&gt;" in stdout
    # Injected XSS payload must not appear as a raw HTML element
    assert "<script>alert(" not in stdout


def test_deterministic_output() -> None:
    """Two runs with same data produce identical output."""
    d = _make_artifact_dir()
    rc1, stdout1, _ = run_script_raw("visualize.py", ["--dir", d])
    rc2, stdout2, _ = run_script_raw("visualize.py", ["--dir", d])
    assert rc1 == 0
    assert rc2 == 0
    assert stdout1 == stdout2


def test_html_structural_sanity() -> None:
    """DOCTYPE present, balanced SVG tags, balanced script tags."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert stdout.startswith("<!DOCTYPE html>")
    open_count = stdout.count("<svg")
    close_count = stdout.count("</svg>")
    assert open_count == close_count, f"<svg count={open_count} != </svg> count={close_count}"
    assert open_count > 0, "Expected at least one SVG element"
    # Inline JS is allowed; verify script tags are balanced
    # (XSS safety is verified by the separate test_xss_safety test)
    script_count = stdout.lower().count("<script")
    script_close = stdout.lower().count("</script>")
    assert script_count == script_close, "Unbalanced script tags"


def test_checklist_heatmap() -> None:
    """Checklist heatmap chart present with category names."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    # Check for category names from the checklist fixture
    assert "Structure" in stdout
    assert "Revenue" in stdout


def test_unit_economics_dashboard() -> None:
    """Unit economics dashboard present with metric names."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    # Check for metric names (displayed as title case)
    assert "CAC" in stdout or "Cac" in stdout
    assert "LTV" in stdout or "Ltv" in stdout


def test_runway_chart() -> None:
    """Runway scenarios chart present with scenario names."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    # Check for scenario names
    lower = stdout.lower()
    assert "base" in lower
    assert "slow" in lower
    assert "crisis" in lower


def test_deck_format_summary_cards() -> None:
    """Deck format shows Business Quality and deck-only label in HTML."""
    inputs_deck = dict(_VALID_INPUTS)
    inputs_deck["company"] = dict(_VALID_INPUTS["company"])
    inputs_deck["company"]["model_format"] = "deck"
    checklist_deck = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist_deck["summary"]["business_quality_pct"] = 95.0
    checklist_deck["summary"]["model_maturity_pct"] = None
    d = _make_artifact_dir(overrides={"inputs.json": inputs_deck, "checklist.json": checklist_deck})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "Business Quality" in stdout
    assert "deck" in stdout.lower() or "N/A" in stdout


def test_threshold_scenario_in_chart() -> None:
    """Threshold scenario appears in runway chart with dashed purple line."""
    runway_with_threshold = json.loads(json.dumps(_VALID_RUNWAY))
    runway_with_threshold["scenarios"].append(
        {
            "name": "threshold",
            "label": "Minimum viable growth",
            "growth_rate": 0.042,
            "runway_months": 18,
            "cash_out_date": "2027-06",
            "decision_point": "2026-06",
            "default_alive": True,
            "monthly_projections": [
                {"month": 1, "cash_balance": 1945000},
                {"month": 2, "cash_balance": 1890000},
            ],
        }
    )
    d = _make_artifact_dir(overrides={"runway.json": runway_with_threshold})
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "break-even" in stdout.lower()
    # Verify purple color and dashed line for threshold scenario
    assert "#8b5cf6" in stdout, "Expected purple color (#8b5cf6) for threshold scenario"
    assert 'stroke-dasharray="6,3"' in stdout, "Expected dashed line for threshold scenario"
