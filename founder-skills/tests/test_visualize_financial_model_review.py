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
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")
_VISUALIZE_SCRIPT = os.path.join(FMR_SCRIPTS_DIR, "visualize.py")


def _load_visualize_module() -> types.ModuleType:
    """Import visualize.py as a module (unique sys.modules key to avoid collisions)."""
    key = "fmr_visualize_test"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _VISUALIZE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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


def test_brand_theme_present() -> None:
    """Output carries the brand tokens, embedded font, and footer credit."""
    d = _make_artifact_dir()
    rc, stdout, _stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0
    assert "--lool-blue: #0D549D" in stdout
    assert "font-family: 'Sora'" in stdout
    assert "founder-skills by lool ventures" in stdout


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


# ---------------------------------------------------------------------------
# Task 14 — _fmt_usd negative values
# ---------------------------------------------------------------------------


def test_fmt_usd_negative_values() -> None:
    """Runway-chart Y-axes can go negative (min(all_cash, 0)); negatives must
    format compactly, not fall through to '$-200,000.00'."""
    mod = _load_visualize_module()
    assert mod._fmt_usd(-200_000) == "-$200.0K"
    assert mod._fmt_usd(-10_000_000) == "-$10.0M"
    assert mod._fmt_usd(1_500_000) == "$1.5M"  # positive path unchanged


# ===========================================================================
# Key-coverage tests: producer output keys ⊆ renderer known sets
# ===========================================================================
#
# Invariant: when unit_economics.py adds a new metric name, visualize.py's
# _METRIC_LABELS must gain a matching entry; when runway.py adds a new
# scenario name, _SCENARIO_COLORS / _SCENARIO_LABELS must cover it.
# These tests pin the current complete sets so any new emitted key causes
# a loud failure with the offending name listed.
# ===========================================================================


def _load_fmr_visualize() -> types.ModuleType:
    """Import FMR visualize.py with a unique sys.modules key (no _theme needed at module level)."""
    key = "_fmr_keycov_visualize"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _VISUALIZE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _VISUALIZE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Test A: unit_economics metric names → visualize._METRIC_LABELS coverage
# ---------------------------------------------------------------------------


class TestUnitEconMetricLabelCoverage:
    """Every metric name that unit_economics.py can emit must appear in
    visualize.py's _METRIC_LABELS so the dashboard shows the curated label
    (the fallback is a mechanical title-cased name, e.g. "Ltv Cac Ratio").

    Derived from: the 11 canonical metric IDs hardcoded by _compute_metrics
    (cac, ltv, ltv_cac_ratio, cac_payback, burn_multiple, magic_number,
    gross_margin, nrr, grr, rule_of_40, arr_per_fte).  These are the only
    names ever written to the `name` field of a metrics[] entry.
    """

    # All metric names emitted by unit_economics._compute_metrics.
    # Derived directly from the 11 _metric() calls in that function.
    PRODUCER_METRIC_NAMES: set[str] = {
        "cac",
        "ltv",
        "ltv_cac_ratio",
        "cac_payback",
        "burn_multiple",
        "magic_number",
        "gross_margin",
        "nrr",
        "grr",
        "rule_of_40",
        "arr_per_fte",
    }

    def test_all_producer_metric_names_in_metric_labels(self) -> None:
        """Every metric name the producer emits must have a display label."""
        viz = _load_fmr_visualize()
        label_keys: set[str] = set(viz._METRIC_LABELS.keys())

        missing = self.PRODUCER_METRIC_NAMES - label_keys
        assert not missing, (
            f"visualize._METRIC_LABELS is missing a display label for metric name(s) "
            f"emitted by unit_economics.py: {sorted(missing)}. "
            f"Add entries to _METRIC_LABELS for each."
        )

    def test_producer_metric_names_min_count(self) -> None:
        """Guard against vacuous tests: producer set must have the expected 11 names."""
        assert len(self.PRODUCER_METRIC_NAMES) == 11, (
            f"PRODUCER_METRIC_NAMES expected 11 entries, got {len(self.PRODUCER_METRIC_NAMES)}. "
            f"Update the test fixture when unit_economics.py adds or removes a metric."
        )

    def test_metric_labels_min_count(self) -> None:
        """_METRIC_LABELS must cover at least the 11 producer names (extras are fine)."""
        viz = _load_fmr_visualize()
        label_keys: set[str] = set(viz._METRIC_LABELS.keys())
        assert len(label_keys) >= 11, f"visualize._METRIC_LABELS has only {len(label_keys)} entries; expected >= 11."

    def test_live_producer_output_metric_names_subset_of_labels(self) -> None:
        """Live unit_economics.py output metric names must all appear in _METRIC_LABELS.

        Runs unit_economics.py on a full SaaS inputs fixture that exercises every
        non-not_applicable metric branch (all 11 metrics attempt computation).
        """
        full_saas_inputs = {
            "company": {
                "company_name": "TestCo",
                "stage": "seed",
                "sector": "B2B SaaS",
                "geography": "US",
                "revenue_model_type": "saas-sales-led",
            },
            "revenue": {
                "arr": {"value": 600_000, "as_of": "2025-12"},
                "mrr": {"value": 50_000, "as_of": "2025-12"},
                "growth_rate_monthly": 0.08,
                "churn_monthly": 0.03,
                "nrr": 1.10,
                "grr": 0.90,
            },
            "cash": {"current_balance": 2_000_000, "monthly_net_burn": 80_000},
            "unit_economics": {
                "cac": {"total": 1_500, "fully_loaded": True},
                "ltv": {"value": 6_000, "method": "formula", "observed_vs_assumed": "assumed"},
                "payback_months": 10,
                "gross_margin": 0.75,
            },
            "expenses": {"headcount": [{"role": "sales", "count": 2, "salary_annual": 80_000, "burden_pct": 0.20}]},
        }
        import subprocess as _sp

        ue_script = os.path.join(FMR_SCRIPTS_DIR, "unit_economics.py")
        result = _sp.run(
            [sys.executable, ue_script],
            input=json.dumps(full_saas_inputs),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"unit_economics.py failed: {result.stderr}"
        ue_data = json.loads(result.stdout)

        live_names = {m["name"] for m in ue_data.get("metrics", []) if isinstance(m, dict) and "name" in m}
        assert len(live_names) >= 11, (
            f"Expected >= 11 metric names from live producer, got {len(live_names)}: {sorted(live_names)}"
        )

        viz = _load_fmr_visualize()
        label_keys: set[str] = set(viz._METRIC_LABELS.keys())

        missing = live_names - label_keys
        assert not missing, (
            f"visualize._METRIC_LABELS is missing a display label for live-produced metric(s): "
            f"{sorted(missing)}. Add entries to _METRIC_LABELS for each."
        )


# ---------------------------------------------------------------------------
# Test B: unit_economics rating values → visualize._RATING_COLORS coverage
# ---------------------------------------------------------------------------


class TestUnitEconRatingColorCoverage:
    """Every rating value that unit_economics.py can write to a metric's
    'rating' field must have a colour entry in visualize._RATING_COLORS
    OR be one of the known no-bar ratings (not_rated, not_applicable,
    contextual) that the chart renders using the primary colour fallback.

    Derived from the _metric() helper: ratings come from _rate_metric(),
    which returns 'strong'|'acceptable'|'warning'|'fail', or are hardcoded
    as 'not_rated', 'not_applicable', 'contextual'.
    """

    # Ratings that must have an explicit colour entry in _RATING_COLORS.
    MUST_HAVE_COLOR: set[str] = {"strong", "acceptable", "warning", "fail"}

    # Ratings where the chart intentionally falls back to _CLR_PRIMARY.
    EXPLICIT_FALLBACK: set[str] = {"not_rated", "not_applicable", "contextual"}

    def test_rated_values_have_color_entries(self) -> None:
        """strong/acceptable/warning/fail must each map to a colour."""
        viz = _load_fmr_visualize()
        missing = self.MUST_HAVE_COLOR - set(viz._RATING_COLORS.keys())
        assert not missing, (
            f"visualize._RATING_COLORS missing entry for rating(s): {sorted(missing)}. "
            f"Add a colour for each rating value that unit_economics.py can emit."
        )

    def test_fallback_ratings_not_required_in_color_map(self) -> None:
        """not_rated/not_applicable/contextual should NOT be in _RATING_COLORS
        (they are displayed using the primary-colour fallback, not a distinct colour).

        If this test fails it means a colour was added for a fallback rating —
        fine intentionally, but this test pins the current design.
        """
        viz = _load_fmr_visualize()
        unexpectedly_present = self.EXPLICIT_FALLBACK & set(viz._RATING_COLORS.keys())
        assert not unexpectedly_present, (
            f"visualize._RATING_COLORS unexpectedly contains fallback rating(s): "
            f"{sorted(unexpectedly_present)}. If this is intentional, remove them from "
            f"EXPLICIT_FALLBACK and add to MUST_HAVE_COLOR."
        )


# ---------------------------------------------------------------------------
# Test C: runway scenario names → visualize._SCENARIO_COLORS / _SCENARIO_LABELS
# ---------------------------------------------------------------------------


class TestRunwayScenarioNameCoverage:
    """Every scenario name that runway.py can emit must appear in both
    visualize._SCENARIO_COLORS and visualize._SCENARIO_LABELS so the chart
    draws a coloured line and the legend shows a human label.

    Producer emits: 'base', 'slow', 'crisis' (auto-generated), 'threshold'
    (minimum-viable-growth result), plus user-defined names from inputs.scenarios.
    The first four are canonical; user-defined names fall back to _CLR_PRIMARY
    and name.title(), which is intentional — this test only pins the canonical
    four that must always be explicitly covered.
    """

    # Canonical scenario names runway.py always emits when inputs allow.
    CANONICAL_SCENARIO_NAMES: set[str] = {"base", "slow", "crisis", "threshold"}

    def test_canonical_names_in_scenario_colors(self) -> None:
        """All four canonical scenario names must have a colour entry."""
        viz = _load_fmr_visualize()
        missing = self.CANONICAL_SCENARIO_NAMES - set(viz._SCENARIO_COLORS.keys())
        assert not missing, (
            f"visualize._SCENARIO_COLORS missing entry for canonical scenario name(s): "
            f"{sorted(missing)}. Add a colour for each name that runway.py can emit."
        )

    def test_canonical_names_in_scenario_labels(self) -> None:
        """All four canonical scenario names must have a human-readable label."""
        viz = _load_fmr_visualize()
        missing = self.CANONICAL_SCENARIO_NAMES - set(viz._SCENARIO_LABELS.keys())
        assert not missing, (
            f"visualize._SCENARIO_LABELS missing entry for canonical scenario name(s): "
            f"{sorted(missing)}. Add a label for each name that runway.py can emit."
        )

    def test_scenario_colors_and_labels_consistent(self) -> None:
        """Every key in _SCENARIO_COLORS should also be in _SCENARIO_LABELS
        (same set — a scenario with a colour but no label produces a blank legend item)."""
        viz = _load_fmr_visualize()
        color_keys = set(viz._SCENARIO_COLORS.keys())
        label_keys = set(viz._SCENARIO_LABELS.keys())
        color_only = color_keys - label_keys
        label_only = label_keys - color_keys
        assert not color_only, (
            f"Scenario name(s) have a colour but no label in _SCENARIO_LABELS: "
            f"{sorted(color_only)}. Add matching entries to _SCENARIO_LABELS."
        )
        assert not label_only, (
            f"Scenario name(s) have a label but no colour in _SCENARIO_COLORS: "
            f"{sorted(label_only)}. Add matching entries to _SCENARIO_COLORS."
        )

    def test_live_producer_scenario_names_covered(self) -> None:
        """Live runway.py output scenario names must all appear in _SCENARIO_COLORS.

        Runs runway.py on a full fixture that triggers all four canonical scenarios
        (base/slow/crisis auto-generated + threshold from minimum-viable-growth search).
        """
        import subprocess as _sp

        full_inputs = {
            "company": {"company_name": "TestCo", "stage": "seed"},
            "revenue": {
                "arr": {"value": 600_000, "as_of": "2025-12"},
                "mrr": {"value": 50_000, "as_of": "2025-12"},
                "growth_rate_monthly": 0.08,
            },
            "cash": {"current_balance": 2_000_000, "monthly_net_burn": 80_000},
        }
        runway_script = os.path.join(FMR_SCRIPTS_DIR, "runway.py")
        result = _sp.run(
            [sys.executable, runway_script],
            input=json.dumps(full_inputs),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"runway.py failed: {result.stderr}"
        runway_data = json.loads(result.stdout)

        live_names = {s["name"] for s in runway_data.get("scenarios", []) if isinstance(s, dict) and "name" in s}
        assert len(live_names) >= 4, (
            f"Expected >= 4 scenario names from live producer, got {len(live_names)}: {sorted(live_names)}"
        )

        viz = _load_fmr_visualize()
        color_keys = set(viz._SCENARIO_COLORS.keys())

        missing = live_names - color_keys
        assert not missing, (
            f"visualize._SCENARIO_COLORS is missing an entry for live-produced scenario(s): "
            f"{sorted(missing)}. Add a colour for each scenario name that runway.py can emit."
        )


# ---------------------------------------------------------------------------
# Test D: runway scenario keys → explore._build_data_payload scenarios pass-through
# ---------------------------------------------------------------------------


def _load_fmr_explore() -> types.ModuleType:
    """Import FMR explore.py with a unique sys.modules key.

    explore.py inserts FMR_SCRIPTS_DIR into sys.path at module level and
    imports from unit_economics.py.  _theme is only imported inside
    _build_html_string(), so module-level import is safe without a stub.
    """
    key = "_fmr_keycov_explore"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    explore_script = os.path.join(FMR_SCRIPTS_DIR, "explore.py")
    spec = importlib.util.spec_from_file_location(key, explore_script)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = explore_script  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestExploreLensDataCoverage:
    """explore._build_data_payload passes scenario objects through to the JS
    DATA payload unmodified.  The JS engine reads specific fields from each
    scenario object; if the payload builder starts filtering scenarios, the
    fields the JS consumes must survive.
    """

    # Fields the explore.py JS actually reads from each scenario object
    # (grep the embedded JS for `s.name` / `scenario.<field>` accesses before
    # extending this set — pinning fields the JS does not read would mislead
    # a maintainer slimming the payload).
    JS_READS_FROM_SCENARIO: set[str] = {
        "name",
        "runway_months",
        "default_alive",
    }

    def test_scenario_fields_pass_through_payload(self) -> None:
        """_build_data_payload must carry JS-required scenario fields through
        to the data payload without dropping them."""
        explore = _load_fmr_explore()

        # Minimal inputs + runway with a single scenario that has all fields
        inputs: dict[str, Any] = {
            "company": {"company_name": "TestCo", "stage": "seed"},
            "revenue": {"mrr": {"value": 50_000}, "growth_rate_monthly": 0.08},
            "cash": {"current_balance": 2_000_000, "monthly_net_burn": 80_000},
        }
        runway: dict[str, Any] = {
            "company": {"name": "TestCo"},
            "baseline": {"net_cash": 2_000_000, "monthly_burn": 80_000, "monthly_revenue": 50_000},
            "scenarios": [
                {
                    "name": "base",
                    "runway_months": 25,
                    "cash_out_date": "2028-01",
                    "decision_point": "2027-01",
                    "default_alive": True,
                    "monthly_projections": [{"month": 1, "cash_balance": 1_950_000}],
                    "became_profitable": False,
                    "growth_rate": 0.08,
                    "burn_change": 0.0,
                    "note": None,
                }
            ],
            "risk_assessment": "OK",
            "limitations": [],
            "warnings": [],
        }

        payload = explore._build_data_payload(
            inputs,
            runway,
            None,  # ue
            None,  # checklist
            None,  # commentary
            stub_reasons={},
        )

        scenarios = payload.get("scenarios", [])
        assert len(scenarios) >= 1, "Payload must contain at least one scenario."

        scenario = scenarios[0]
        present = set(scenario.keys())
        missing = self.JS_READS_FROM_SCENARIO - present
        assert not missing, (
            f"explore._build_data_payload dropped scenario field(s) that the JS engine reads: "
            f"{sorted(missing)}. The payload builder must pass these fields through unchanged."
        )


# ---------------------------------------------------------------------------
# explore.py JS burn-multiple formula: must annualize ΔMRR
# ---------------------------------------------------------------------------
#
# Source: David Sacks, "The Burn Multiple"
#   "Burn Multiple = Net Burn / Net New ARR" — period-matched.
# Net New ARR (monthly) = ΔMRR × 12 = mrr × growth_rate × 12.
# The JS must divide monthly burn by (mrr × growth_rate × 12), NOT by
# (mrr × growth_rate) alone — the latter overstates by 12x.
#
# Worked example: burn=80K, MRR=50K, growth=8%
#   correct = 80K / (50K × 0.08 × 12) = 80K / 48K ≈ 1.67
#   old bug  = 80K / (50K × 0.08)     = 80K / 4K  = 20.0  (12x overstated)
#
# This is a source-pin test: it reads the explore.py source and asserts
# the annualisation factor (* 12 or equivalent) is present in the
# calcBurnMultiple function body.
# ---------------------------------------------------------------------------


class TestExploreBurnMultipleFormula:
    """explore.py JS calcBurnMultiple must annualise ΔMRR (× 12)."""

    def test_calc_burn_multiple_annualises_delta_mrr(self) -> None:
        """calcBurnMultiple JS body must contain '* 12' (or '* 12.0') to annualise ΔMRR.

        Without annualisation the denominator is monthly ΔMRR, not net-new ARR,
        making the result 12x too high.
        """
        explore_script = os.path.join(FMR_SCRIPTS_DIR, "explore.py")
        with open(explore_script) as f:
            source = f.read()

        # Isolate the calcBurnMultiple function body
        import re as _re

        m = _re.search(r"function calcBurnMultiple\([^)]*\)\s*\{(.+?)\}", source, _re.DOTALL)
        assert m is not None, "calcBurnMultiple function not found in explore.py"
        body = m.group(1)

        # The denominator must include annualisation: mrr * growth_rate * 12
        # Accept either literal '* 12' or '* 12.0'
        assert _re.search(r"\*\s*12(?:\.0)?\b", body), (
            f"calcBurnMultiple in explore.py must multiply ΔMRR by 12 to get net-new ARR. "
            f"Found body:\n{body}\n"
            f"Expected pattern: 'mrr * growth_rate * 12' or equivalent."
        )
