#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for market sizing calculation scripts.

Run: pytest founder-skills/tests/test_market_sizing.py -v
All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Market-sizing scripts are colocated with the skill
FOUNDER_SKILLS_DIR = os.path.dirname(SCRIPT_DIR)
MARKET_SIZING_DIR = os.path.join(FOUNDER_SKILLS_DIR, "skills", "market-sizing", "scripts")
MARKET_SIZING_SKILL_MD = os.path.join(FOUNDER_SKILLS_DIR, "skills", "market-sizing", "SKILL.md")
MARKET_SIZING_AGENT_MD = os.path.join(FOUNDER_SKILLS_DIR, "agents", "market-sizing.md")
MARKET_SIZING_ARTIFACT_SCHEMAS_MD = os.path.join(
    FOUNDER_SKILLS_DIR, "skills", "market-sizing", "references", "artifact-schemas.md"
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    script_dir: str | None = None,
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    base = script_dir or MARKET_SIZING_DIR
    cmd = [sys.executable, os.path.join(base, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def run_script_raw(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    script_dir: str | None = None,
) -> tuple[int, str, str]:
    """Like run_script but returns (exit_code, raw_stdout, stderr)."""
    base = script_dir or MARKET_SIZING_DIR
    cmd = [sys.executable, os.path.join(base, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def test_market_sizing_bottom_up() -> None:
    """B2B SaaS example from playbook."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "bottom-up",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert "bottom_up" in data
    bu = data["bottom_up"]
    assert bu["tam"]["value"] == 67_500_000_000.0
    assert bu["sam"]["value"] == 23_625_000_000.0
    assert bu["som"]["value"] == 118_125_000.0


def test_market_sizing_top_down() -> None:
    """Enterprise software example."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "100000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    td = data["top_down"]
    assert td["tam"]["value"] == 100_000_000_000.0
    assert td["sam"]["value"] == 6_000_000_000.0
    assert td["som"]["value"] == 300_000_000.0


def test_market_sizing_both_comparison() -> None:
    """Cross-validation with expected discrepancy."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "both",
            "--industry-total",
            "100000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "5",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert "comparison" in data
    assert data["comparison"]["tam_delta_pct"] > 30
    assert "warning" in data["comparison"]


def test_market_sizing_sam_som_divergence_gated() -> None:
    """compare() must gate SAM and SOM divergence the same way it gates TAM — previously only TAM
    was checked, so an order-of-magnitude SAM/SOM gap between top-down and bottom-up could be
    presented as equally defensible."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "both",
            "--industry-total",
            "100000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "5",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None
    comparison = data["comparison"]
    assert comparison["sam_delta_pct"] > 30
    assert "sam_warning" in comparison
    assert comparison["som_delta_pct"] > 30
    assert "som_warning" in comparison


def test_market_sizing_stdin_string_coercion() -> None:
    """JSON with string values should be coerced to numbers."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "customer_count": "4500000",
            "arpu": "15000",
            "serviceable_pct": "35",
            "target_pct": "0.5",
        }
    )
    rc, data, _ = run_script("market_sizing.py", ["--stdin", "--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert data["bottom_up"]["tam"]["value"] == 67_500_000_000.0


def _assert_validation_errors(data: dict | None, *fragments: str) -> None:
    """Assert data has validation.status == 'invalid' and errors contain all fragments."""
    assert data is not None, "expected JSON output with validation errors"
    assert data["validation"]["status"] == "invalid"
    joined = " ".join(data["validation"]["errors"]).lower()
    for frag in fragments:
        assert frag.lower() in joined, f"expected '{frag}' in validation errors: {data['validation']['errors']}"


def test_market_sizing_negative_pct_error() -> None:
    """Negative percentage should produce validation error."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "1000000",
            "--segment-pct",
            "-5",
            "--share-pct",
            "10",
        ],
    )
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "negative")


def test_market_sizing_fractional_pct_warns_top_down() -> None:
    """A fractional segment_pct (0.35 meaning 35%) should compute as given (not hard-rejected)
    but must emit a non-fatal plausibility warning to stderr — this is the exact class of
    silent ~100x error the founder hit: 0.35 was meant to be 35% but was accepted at face value."""
    rc, data, stderr = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "1000000000",
            "--segment-pct",
            "0.35",
            "--share-pct",
            "5",
        ],
    )
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert data["validation"]["status"] == "valid", "a fractional pct must NOT be hard-rejected"
    # Computed using 0.35 as given (not auto-corrected) — the warning is the safeguard, not a fix.
    assert abs(data["top_down"]["sam"]["raw_value"] - 1000000000 * 0.0035) < 1e-6
    # WB-1: the warning MUST persist into the artifact (validation.warnings), not just stderr —
    # a stderr-only warning leaves validation.status "valid" and the founder never sees it (the
    # exact silent-100x class). It's still ALSO on stderr per script convention.
    warns = data["validation"]["warnings"]
    assert any(w.get("field") == "segment_pct" and w.get("code") == "IMPLAUSIBLE_PCT_SCALE" for w in warns)
    assert "segment_pct" in stderr


def test_market_sizing_fractional_pct_no_warning_for_normal_values() -> None:
    """A legitimate percentage-points value (5, meaning 5%) must not trigger the fraction warning."""
    rc, data, stderr = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "1000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "5",
        ],
    )
    assert rc == 0
    assert data is not None
    assert data["validation"]["warnings"] == []
    assert "fraction" not in stderr.lower()


def test_market_sizing_fractional_pct_warns_bottom_up() -> None:
    """serviceable_pct/target_pct fractional inputs must also trigger the plausibility warning."""
    rc, data, stderr = run_script(
        "market_sizing.py",
        [
            "--approach",
            "bottom-up",
            "--customer-count",
            "1000",
            "--arpu",
            "1000",
            "--serviceable-pct",
            "0.5",
            "--target-pct",
            "10",
        ],
    )
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    warns = data["validation"]["warnings"]
    assert any(w.get("field") == "serviceable_pct" and w.get("code") == "IMPLAUSIBLE_PCT_SCALE" for w in warns)
    assert "serviceable_pct" in stderr


def test_market_sizing_sub_one_pct_not_hard_rejected() -> None:
    """A genuinely tiny but legitimate share (e.g. 0.5% meant as points, not a fraction of 1) still
    computes — the plausibility check is a warning, never a rejection, since a legit sub-1% share exists."""
    rc, data, stderr = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "1000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "0.3",
        ],
    )
    assert rc == 0
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert "share_pct" in stderr


def test_market_sizing_non_integer_customer_count() -> None:
    """Non-integer customer_count via stdin should produce validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "customer_count": "3.9",
            "arpu": "15000",
            "serviceable_pct": "35",
            "target_pct": "0.5",
        }
    )
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "whole number")


def test_sensitivity_basic() -> None:
    """Basic sensitivity with SaaS example."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
            "ranges": {
                "customer_count": {"low_pct": -30, "high_pct": 20},
                "arpu": {"low_pct": -20, "high_pct": 15},
                "target_pct": {"low_pct": -50, "high_pct": 100},
            },
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert len(data.get("scenarios", [])) == 3
    assert len(data.get("sensitivity_ranking", [])) == 3
    assert data.get("most_sensitive") == "target_pct"
    assert data["base_result"]["som"] == 118_125_000.0


def test_sensitivity_no_stdin_error() -> None:
    """Running without stdin should error helpfully."""
    rc, _, stderr = run_script("sensitivity.py", ["--pretty"])
    # Note: isatty() may return False in subprocess, so this tests the JSON parse path
    assert rc != 0 or "error" in stderr.lower()


def test_sensitivity_approach_normalization() -> None:
    """Hyphenated approach name should be normalized."""
    payload = json.dumps(
        {
            "approach": "bottom-up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None, "stdout was empty or not valid JSON"
    assert data.get("approach") == "bottom_up"


# -- Helpers for checklist.py tests --

# All 22 canonical checklist IDs
_CHECKLIST_IDS = [
    "structural_tam_gt_sam_gt_som",
    "structural_definitions_correct",
    "tam_matches_product_scope",
    "source_segments_match",
    "som_share_defensible",
    "som_backed_by_gtm",
    "som_consistent_with_projections",
    "data_current",
    "sources_reputable",
    "figures_triangulated",
    "unsupported_figures_flagged",
    "validated_used_precisely",
    "assumptions_categorized",
    "both_approaches_used",
    "approaches_reconciled",
    "growth_dynamics_considered",
    "market_properly_segmented",
    "competitive_landscape_acknowledged",
    "sam_expansion_path_noted",
    "assumptions_explicit",
    "formulas_shown",
    "sources_cited",
]


def _make_checklist_items(
    overrides: dict[str, dict] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Build a 22-item checklist payload. overrides: {id: {status, notes}}. exclude: IDs to omit."""
    overrides = overrides or {}
    exclude = exclude or []
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in exclude:
            continue
        if cid in overrides:
            items.append({"id": cid, **overrides[cid]})
        else:
            items.append({"id": cid, "status": "pass", "notes": None})
    return items


def test_checklist_all_pass() -> None:
    """All 22 items pass."""
    payload = json.dumps({"items": _make_checklist_items()})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["overall_status"] == "pass"
    assert s["pass"] == 22
    assert s["fail"] == 0
    assert len(s["failed_items"]) == 0


def test_checklist_some_fail() -> None:
    """19 pass, 2 fail, 1 not_applicable."""
    overrides = {
        "tam_matches_product_scope": {"status": "fail", "notes": "TAM too broad"},
        "som_share_defensible": {"status": "fail", "notes": "No justification"},
        "sources_cited": {"status": "not_applicable", "notes": "Pure calculation"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["overall_status"] == "fail"
    assert s["fail"] == 2
    assert s["not_applicable"] == 1
    failed_ids = {f["id"] for f in s["failed_items"]}
    assert failed_ids == {"tam_matches_product_scope", "som_share_defensible"}


def test_checklist_missing_items() -> None:
    """Only 19 items -- should produce validation error."""
    items = _make_checklist_items(exclude=["data_current", "sources_reputable", "figures_triangulated"])
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "missing")


def test_checklist_duplicate_id() -> None:
    """23 items with a duplicate -- should produce validation error."""
    items = _make_checklist_items()
    items.append({"id": "data_current", "status": "pass", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "duplicate")


def test_checklist_unknown_id() -> None:
    """Unknown ID 'bogus' -- should produce validation error."""
    items = _make_checklist_items()
    # Replace one valid item with bogus
    items[0] = {"id": "bogus", "status": "pass", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "unknown")


def test_checklist_invalid_status() -> None:
    """Status 'maybe' -- should produce validation error."""
    overrides = {"data_current": {"status": "maybe", "notes": None}}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "invalid")


def test_checklist_not_applicable() -> None:
    """5 not_applicable -- should not count as failures."""
    na_ids = [
        "both_approaches_used",
        "approaches_reconciled",
        "growth_dynamics_considered",
        "sources_cited",
        "sam_expansion_path_noted",
    ]
    overrides = {cid: {"status": "not_applicable", "notes": "N/A"} for cid in na_ids}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["not_applicable"] == 5
    assert s["overall_status"] == "pass"
    assert s["fail"] == 0


def test_checklist_score_pct() -> None:
    """checklist.py summary includes score_pct matching SKILL.md spec."""
    overrides = {
        "tam_matches_product_scope": {"status": "fail", "notes": "TAM too broad"},
        "sources_cited": {"status": "not_applicable", "notes": "Pure calculation"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert "score_pct" in s, "Expected score_pct in summary"
    # 22 total, 1 fail, 1 NA → 20 pass, 21 applicable → 20/21*100 = 95.2
    expected = round((s["pass"] / (s["total"] - s["not_applicable"])) * 100, 1)
    assert s["score_pct"] == expected


# -- Helpers for compose_report.py tests --


def _make_artifact_dir(artifacts: dict[str, Any]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-compose-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)
    return d


# Minimal valid fixture data for each artifact type
_VALID_INPUTS = {
    "company_name": "TestCo",
    "analysis_date": "2026-01-15",
    "materials_provided": ["pitch deck"],
}

_VALID_METHODOLOGY = {
    "approach_chosen": "both",
    "rationale": "Both data sources available",
    "reference_file_read": True,
}

_VALID_VALIDATION = {
    "sources": [
        {
            "title": "Gartner Report",
            "publisher": "Gartner",
            "url": "https://example.com",
            "date_accessed": "2026-01-15",
            "supported": "TAM figure",
        },
    ],
    "figure_validations": [
        {"figure": "TAM", "status": "validated", "source_count": 2},
        {"figure": "SAM", "status": "partially_supported", "source_count": 1},
    ],
    "assumptions": [
        {"name": "customer_count", "value": 4500000, "category": "sourced"},
        {"name": "arpu", "value": 15000, "category": "derived"},
    ],
}

# Annotated because the new market-size payload tests index three levels deep
# (_VALID_SIZING["bottom_up"]["tam"]["value"]); without it mypy infers the value
# type as Collection[str] from the mixed str/dict literal and the index fails.
_VALID_SIZING: dict[str, Any] = {
    "approach": "both",
    "top_down": {
        "tam": {"value": 100000000000, "formula": "industry_total", "inputs": {"industry_total": 100000000000}},
        "sam": {
            "value": 6000000000,
            "formula": "tam * segment_pct",
            "inputs": {"tam": 100000000000, "segment_pct": 6},
        },
        "som": {"value": 300000000, "formula": "sam * share_pct", "inputs": {"sam": 6000000000, "share_pct": 5}},
    },
    "bottom_up": {
        "tam": {
            "value": 67500000000,
            "formula": "customer_count * arpu",
            "inputs": {"customer_count": 4500000, "arpu": 15000},
        },
        "sam": {
            "value": 23625000000,
            "formula": "serviceable_customers * arpu",
            "inputs": {"serviceable_customers": 1575000, "arpu": 15000},
        },
        "som": {
            "value": 118125000,
            "formula": "target_customers * arpu",
            "inputs": {"target_customers": 7875, "arpu": 15000},
        },
    },
    "comparison": {"tam_delta_pct": 15.2, "note": "Moderate discrepancy"},
}

_VALID_SENSITIVITY = {
    "approach": "bottom_up",
    "base_result": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
    "scenarios": [
        {
            "parameter": "customer_count",
            "confidence": "sourced",
            "original_range": {"low_pct": -30, "high_pct": 20},
            "effective_range": {"low_pct": -30, "high_pct": 20},
            "range_widened": False,
            "base_value": 4500000,
            "low": {"som": 82687500},
            "base": {"som": 118125000},
            "high": {"som": 141750000},
        },
        {
            "parameter": "arpu",
            "confidence": "derived",
            "original_range": {"low_pct": -20, "high_pct": 15},
            "effective_range": {"low_pct": -30, "high_pct": 30},
            "range_widened": True,
            "base_value": 15000,
            "low": {"som": 82687500},
            "base": {"som": 118125000},
            "high": {"som": 153562500},
        },
        {
            "parameter": "target_pct",
            "confidence": "agent_estimate",
            "original_range": {"low_pct": -50, "high_pct": 100},
            "effective_range": {"low_pct": -50, "high_pct": 100},
            "range_widened": False,
            "base_value": 0.5,
            "low": {"som": 59062500},
            "base": {"som": 118125000},
            "high": {"som": 236250000},
        },
    ],
    "sensitivity_ranking": [{"parameter": "target_pct", "som_swing_pct": 150.0}],
    "most_sensitive": "target_pct",
}

_VALID_CHECKLIST = {
    "items": [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "notes": None} for cid in _CHECKLIST_IDS
    ],
    "summary": {
        "total": 22,
        "pass": 22,
        "fail": 0,
        "not_applicable": 0,
        "overall_status": "pass",
        "failed_items": [],
    },
}


def _run_compose(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, dict | None, str]:
    """Run compose_report.py with given artifact dir."""
    args = ["--dir", artifact_dir, "--pretty"]
    if extra_args:
        args.extend(extra_args)
    return run_script("compose_report.py", args)


def _all_artifacts() -> dict[str, Any]:
    """The canonical complete artifact set, for tests that vary one artifact."""
    return {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "sensitivity.json": _VALID_SENSITIVITY,
        "checklist.json": _VALID_CHECKLIST,
    }


def test_compose_complete_set() -> None:
    """All 6 artifacts valid -> no missing artifacts, report non-empty."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    v = data["validation"]
    assert len(v["artifacts_missing"]) == 0
    assert len(data["report_markdown"]) > 100
    # Should have no MISSING_ARTIFACT warnings
    codes = [w["code"] for w in v["warnings"]]
    assert "MISSING_ARTIFACT" not in codes


def test_compose_missing_required() -> None:
    """No validation.json -> MISSING_ARTIFACT warning."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" in codes


def test_compose_missing_sensitivity() -> None:
    """No sensitivity.json -> MISSING_ARTIFACT (sensitivity is required)."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" in codes
    missing_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    assert any("sensitivity.json" in m for m in missing_msgs)


def test_compose_checklist_failures() -> None:
    """Checklist with overall_status fail -> CHECKLIST_FAILURES."""
    failed_checklist = dict(_VALID_CHECKLIST)
    failed_checklist["summary"] = {
        "total": 22,
        "pass": 20,
        "fail": 2,
        "not_applicable": 0,
        "overall_status": "fail",
        "failed_items": [
            {
                "id": "tam_matches_product_scope",
                "category": "TAM Scoping",
                "label": "TAM matches product scope",
                "notes": "Too broad",
            },
            {
                "id": "som_share_defensible",
                "category": "SOM Realism",
                "label": "SOM share defensible",
                "notes": "No justification",
            },
        ],
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": failed_checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CHECKLIST_FAILURES" in codes


def test_compose_overclaimed_validation() -> None:
    """Figure validated with source_count=1 -> OVERCLAIMED_VALIDATION."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {"figure": "TAM", "status": "validated", "source_count": 1},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "OVERCLAIMED_VALIDATION" in codes


def test_compose_approach_mismatch() -> None:
    """Methodology says 'both', sizing has only top_down -> APPROACH_MISMATCH."""
    sizing_only_td = {"approach": "both", "top_down": _VALID_SIZING["top_down"]}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing_only_td,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "APPROACH_MISMATCH" in codes


def test_compose_sam_discrepancy_warning() -> None:
    """comparison.sam_delta_pct > 30 -> SAM_DISCREPANCY (mirrors TAM_DISCREPANCY, gate #7)."""
    import copy

    sizing = copy.deepcopy(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 10, "sam_delta_pct": 45, "som_delta_pct": 10}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SAM_DISCREPANCY" in codes
    assert "TAM_DISCREPANCY" not in codes
    assert "SOM_DISCREPANCY" not in codes


def test_compose_surfaces_implausible_pct_scale_warning() -> None:
    """WB-1 render half: an IMPLAUSIBLE_PCT_SCALE warning recorded in sizing.json's
    validation block must be surfaced by compose into the report (not left on stderr)."""
    import copy

    sizing: dict[str, Any] = copy.deepcopy(_VALID_SIZING)
    sizing.setdefault("validation", {"status": "valid", "errors": []})
    sizing["validation"]["warnings"] = [
        {
            "code": "IMPLAUSIBLE_PCT_SCALE",
            "field": "segment_pct",
            "message": "segment_pct=0.35 looks like a fraction; percentage points expected",
        }
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "IMPLAUSIBLE_PCT_SCALE" in codes
    assert "segment %" in data["report_markdown"]  # humanized by the shared founder-text policy (_founder_text.py)


def test_compose_som_discrepancy_warning() -> None:
    """comparison.som_delta_pct > 30 -> SOM_DISCREPANCY."""
    import copy

    sizing = copy.deepcopy(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 10, "sam_delta_pct": 10, "som_delta_pct": 60}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SOM_DISCREPANCY" in codes


def test_compose_strict_mode() -> None:
    """Artifacts with warnings + --strict -> exit 1."""
    # Missing validation.json will trigger MISSING_ARTIFACT
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d, extra_args=["--strict"])
    assert rc == 1
    # Should still produce output even in strict mode
    assert data is not None


def test_compose_severity_map_complete() -> None:
    """WARNING_SEVERITY contains all 29 codes with correct severities."""
    # Import WARNING_SEVERITY and ACCEPTIBLE_SEVERITIES by running a small Python snippet
    snippet = (
        f"import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath('{MARKET_SIZING_DIR}'))); "
        f"sys.path.insert(0, '{MARKET_SIZING_DIR}'); "
        "from compose_report import WARNING_SEVERITY, ACCEPTIBLE_SEVERITIES; "
        "import json; print(json.dumps({'severity': WARNING_SEVERITY, 'acceptible': list(ACCEPTIBLE_SEVERITIES)}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
        sev_map = data["severity"]
        acceptible = set(data["acceptible"])
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise AssertionError(f"can't import WARNING_SEVERITY: stdout={result.stdout}, stderr={result.stderr}") from exc

    expected_codes = [
        "FOUNDER_TEXT_TOKEN",
        "CORRUPT_ARTIFACT",
        "MISSING_ARTIFACT",
        "STALE_ARTIFACT",
        "CHECKLIST_FAILURES",
        "OVERCLAIMED_VALIDATION",
        "UNVALIDATED_CLAIMS",
        "MISSING_OPTIONAL_ARTIFACT",
        "UNSOURCED_ASSUMPTIONS",
        "APPROACH_MISMATCH",
        "TAM_DISCREPANCY",
        "SAM_DISCREPANCY",
        "SOM_DISCREPANCY",
        "CHECKLIST_INCOMPLETE",
        "FEW_SENSITIVITY_PARAMS",
        "NARROW_AGENT_ESTIMATE_RANGE",
        "LOW_CHECKLIST_COVERAGE",
        "REFUTED_CLAIMS",
        "REFUTED_MISSING_REASON",
        "DECK_CLAIM_MISMATCH",
        "PROVENANCE_UNRESOLVED",
        "EXISTING_CLAIMS_SHAPE",
        "MARKER_COLLISION",
        "IMPLAUSIBLE_PCT_SCALE",
        "CURRENCY_MISMATCH",
        "FOUNDER_VALUE_OVERRIDDEN",
        # A rejected sizing step used to reach compose with no code naming the cause.
        "SIZING_INVALID",
        # Emitted instead of a guaranteed-false FOUNDER_VALUE_OVERRIDDEN / DECK_CLAIM_MISMATCH
        # when a money input was FX-converted and the comparand declares no currency.
        "COMPARISON_CURRENCY_UNKNOWN",
        # A rejected sensitivity/checklist step, same class as SIZING_INVALID.
        "ARTIFACT_INVALID",
    ]
    assert len(sev_map) == 29, f"expected 29 codes, got {len(sev_map)}"
    for code in expected_codes:
        assert code in sev_map, f"{code} missing from severity map"
    # All values are "high", "medium", or "low"
    valid_severities = {"high", "medium", "low"}
    assert all(v in valid_severities for v in sev_map.values())
    assert sev_map.get("STALE_ARTIFACT") == "high"
    assert sev_map.get("UNVALIDATED_CLAIMS") == "high"
    assert sev_map.get("CORRUPT_ARTIFACT") == "high"
    assert sev_map.get("MISSING_OPTIONAL_ARTIFACT") == "low"
    assert sev_map.get("DECK_CLAIM_MISMATCH") == "low"
    assert sev_map.get("PROVENANCE_UNRESOLVED") == "low"
    assert sev_map.get("EXISTING_CLAIMS_SHAPE") == "medium"
    assert sev_map.get("MARKER_COLLISION") == "low"
    assert sev_map.get("TAM_DISCREPANCY") == "medium"
    assert sev_map.get("SAM_DISCREPANCY") == "medium"
    assert sev_map.get("SOM_DISCREPANCY") == "medium"
    # Safety constraint: all high-severity codes must NOT be in ACCEPTIBLE_SEVERITIES
    high_codes = [c for c, s in sev_map.items() if s == "high"]
    for code in high_codes:
        assert sev_map[code] not in acceptible, f"high-severity {code} should not be acceptible"


def test_compose_stale_artifact_mismatched_run_ids() -> None:
    """Mismatched run_id across artifacts triggers STALE_ARTIFACT warning."""
    import copy

    inputs: dict[str, Any] = copy.deepcopy(_VALID_INPUTS)
    inputs["metadata"] = {"run_id": "run-001"}
    methodology: dict[str, Any] = copy.deepcopy(_VALID_METHODOLOGY)
    methodology["metadata"] = {"run_id": "run-001"}
    validation: dict[str, Any] = copy.deepcopy(_VALID_VALIDATION)
    validation["metadata"] = {"run_id": "run-001"}
    sizing: dict[str, Any] = copy.deepcopy(_VALID_SIZING)
    sizing["metadata"] = {"run_id": "run-002"}  # stale!
    sensitivity: dict[str, Any] = copy.deepcopy(_VALID_SENSITIVITY)
    sensitivity["metadata"] = {"run_id": "run-001"}
    checklist: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    checklist["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(
        {
            "inputs.json": inputs,
            "methodology.json": methodology,
            "validation.json": validation,
            "sizing.json": sizing,
            "sensitivity.json": sensitivity,
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

    artifacts: dict[str, dict[str, Any]] = {
        "inputs.json": copy.deepcopy(_VALID_INPUTS),
        "methodology.json": copy.deepcopy(_VALID_METHODOLOGY),
        "validation.json": copy.deepcopy(_VALID_VALIDATION),
        "sizing.json": copy.deepcopy(_VALID_SIZING),
        "sensitivity.json": copy.deepcopy(_VALID_SENSITIVITY),
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
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_low_checklist_coverage() -> None:
    """Checklist with 8 not_applicable items -> LOW_CHECKLIST_COVERAGE."""
    low_coverage_checklist = dict(_VALID_CHECKLIST)
    low_coverage_checklist["summary"] = {
        "total": 22,
        "pass": 14,
        "fail": 0,
        "not_applicable": 8,
        "overall_status": "pass",
        "failed_items": [],
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": low_coverage_checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "LOW_CHECKLIST_COVERAGE" in codes


# -- Sensitivity confidence tests --


def test_sensitivity_confidence_sourced() -> None:
    """'sourced' + narrow range -> NOT widened."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "sourced"
    assert s["range_widened"] is False
    assert s["effective_range"]["low_pct"] == -10
    assert s["effective_range"]["high_pct"] == 10


def test_sensitivity_confidence_derived_widened() -> None:
    """'derived' + +/-15% -> widened to +/-30%."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -15, "high_pct": 15, "confidence": "derived"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "derived"
    assert s["range_widened"] is True
    assert s["effective_range"]["low_pct"] == -30
    assert s["effective_range"]["high_pct"] == 30
    assert s["original_range"]["low_pct"] == -15


def test_sensitivity_confidence_estimate_widened() -> None:
    """'agent_estimate' + +/-20% -> widened to +/-50%."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -20, "high_pct": 20, "confidence": "agent_estimate"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "agent_estimate"
    assert s["range_widened"] is True
    assert s["effective_range"]["low_pct"] == -50
    assert s["effective_range"]["high_pct"] == 50


def test_sensitivity_confidence_default() -> None:
    """No confidence field -> same as current behavior (backward compat)."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "sourced"
    assert s["range_widened"] is False
    assert "defaulting" in stderr.lower()


def test_sensitivity_confidence_invalid() -> None:
    """'guessed' -> validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10, "confidence": "guessed"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "confidence")


def test_sensitivity_confidence_no_narrowing() -> None:
    """'agent_estimate' + +/-60% -> NOT narrowed to +/-50%."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -60, "high_pct": 60, "confidence": "agent_estimate"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["range_widened"] is False
    assert s["effective_range"]["low_pct"] == -60
    assert s["effective_range"]["high_pct"] == 60


# -- validation_confidence cross-reference tests (item 26d) --
#
# ITEM 26d: a range with no 'confidence' key defaults to 'sourced' (no
# auto-widening), even when the parameter is tagged 'derived'/'agent_estimate'
# in validation.json elsewhere. compose_report.py's UNSOURCED_ASSUMPTIONS check
# only back-stops the 'agent_estimate' tier (it checks assumptions with
# category == "agent_estimate" against sensitivity scenarios with
# confidence == "agent_estimate") — a 'derived'-tagged parameter has no
# downstream check at all. These tests pin the optional 'validation_confidence'
# cross-reference: a {parameter: confidence_tier} map the caller can build from
# validation.json's assumptions[].category and pass alongside 'ranges', so a
# range that omits its own 'confidence' still gets the right auto-widening floor.


def test_sensitivity_validation_confidence_derived_widened() -> None:
    """A range with NO 'confidence' key, but the param IS tagged 'derived' in
    validation_confidence -> gets the +/-30% floor (the genuinely unguarded
    residue from item 26d, now closed)."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -15, "high_pct": 15}},
            "validation_confidence": {"arpu": "derived"},
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "derived"
    assert s["range_widened"] is True
    assert s["effective_range"]["low_pct"] == -30
    assert s["effective_range"]["high_pct"] == 30
    assert s["original_range"]["low_pct"] == -15
    # Cross-reference is noted but distinct wording from the plain-missing
    # 'defaulting to sourced' warning — never claim it fell back to sourced.
    assert "cross-referenced" in stderr.lower()
    assert "defaulting" not in stderr.lower()


def test_sensitivity_validation_confidence_agent_estimate_widened() -> None:
    """Same cross-reference, 'agent_estimate' tier -> +/-50% floor."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -20, "high_pct": 20}},
            "validation_confidence": {"arpu": "agent_estimate"},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "agent_estimate"
    assert s["range_widened"] is True
    assert s["effective_range"]["low_pct"] == -50
    assert s["effective_range"]["high_pct"] == 50


def test_sensitivity_validation_confidence_never_overrides_explicit_range_confidence() -> None:
    """A range's own explicit 'confidence' always wins over validation_confidence,
    even when they disagree — the range is authoritative when present at all."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}},
            "validation_confidence": {"arpu": "agent_estimate"},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "sourced"
    assert s["range_widened"] is False
    assert s["effective_range"]["low_pct"] == -10
    assert s["effective_range"]["high_pct"] == 10


def test_sensitivity_validation_confidence_missing_param_falls_back_to_default() -> None:
    """A range with no confidence, and validation_confidence present but WITHOUT
    an entry for this param -> plain backward-compatible 'sourced' default with
    the original 'defaulting' warning (test_sensitivity_confidence_default's
    documented behavior is unchanged when the cross-reference has no answer)."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
            "validation_confidence": {"customer_count": "derived"},
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "sourced"
    assert s["range_widened"] is False
    assert "defaulting" in stderr.lower()


def test_sensitivity_validation_confidence_plain_missing_everywhere_unchanged() -> None:
    """No validation_confidence key at all, no range confidence -> byte-for-byte
    the same documented backward-compatible behavior as
    test_sensitivity_confidence_default. Guards against the cross-reference
    feature accidentally changing the no-op case."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "sourced"
    assert s["range_widened"] is False
    assert "defaulting" in stderr.lower()


def test_sensitivity_validation_confidence_invalid_value_errors() -> None:
    """validation_confidence.<param> not one of the canonical 3 tiers -> validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
            "validation_confidence": {"arpu": "guessed"},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "validation_confidence")


def test_sensitivity_validation_confidence_not_an_object_errors() -> None:
    """validation_confidence must be an object, not e.g. a list."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
            "validation_confidence": ["derived"],
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "validation_confidence")


# -- Refuted figure tests --


def test_compose_refuted_figure() -> None:
    """Figure with status 'refuted' and refutation -> REFUTED_CLAIMS (medium), NOT UNVALIDATED_CLAIMS."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {"figure": "TAM", "status": "validated", "source_count": 2},
        {
            "figure": "20K sites claim",
            "status": "refuted",
            "source_count": 0,
            "refutation": "Aerospace industry data shows only 3,000 sites globally",
        },
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "REFUTED_CLAIMS" in codes
    assert "UNVALIDATED_CLAIMS" not in codes
    assert "REFUTED_MISSING_REASON" not in codes
    refuted_w = [w for w in data["validation"]["warnings"] if w["code"] == "REFUTED_CLAIMS"][0]
    assert refuted_w["severity"] == "medium"


def test_compose_refuted_not_unvalidated() -> None:
    """Mix of refuted and unsupported -> REFUTED_CLAIMS for refuted, UNVALIDATED_CLAIMS for unsupported."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {
            "figure": "20K sites claim",
            "status": "refuted",
            "source_count": 0,
            "refutation": "Only 3,000 sites globally",
        },
        {"figure": "growth_rate", "status": "unsupported", "source_count": 0},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "REFUTED_CLAIMS" in codes
    assert "UNVALIDATED_CLAIMS" in codes


def test_compose_refuted_missing_reason() -> None:
    """Refuted figure without refutation field -> REFUTED_CLAIMS AND REFUTED_MISSING_REASON."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {"figure": "bogus claim", "status": "refuted", "source_count": 0},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "REFUTED_CLAIMS" in codes
    assert "REFUTED_MISSING_REASON" in codes


# -- Sensitivity "both" approach tests --


def test_sensitivity_both_approach() -> None:
    """Approach 'both' with all 7 params, ranges for customer_count (BU) and segment_pct (TD)."""
    payload = json.dumps(
        {
            "approach": "both",
            "base": {
                "customer_count": 4500000,
                "arpu": 15000,
                "serviceable_pct": 35,
                "target_pct": 0.5,
                "industry_total": 100000000000,
                "segment_pct": 6,
                "share_pct": 5,
            },
            "ranges": {
                "customer_count": {"low_pct": -30, "high_pct": 20},
                "segment_pct": {"low_pct": -20, "high_pct": 20},
            },
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert len(data.get("scenarios", [])) == 2
    s0 = data["scenarios"][0]
    s1 = data["scenarios"][1]
    assert s0.get("approach_used") == "bottom_up"
    assert s1.get("approach_used") == "top_down"
    assert data.get("approach") == "both"


def test_sensitivity_both_missing_params() -> None:
    """Approach 'both' but missing industry_total -> exit 1."""
    payload = json.dumps(
        {
            "approach": "both",
            "base": {
                "customer_count": 4500000,
                "arpu": 15000,
                "serviceable_pct": 35,
                "target_pct": 0.5,
                "segment_pct": 6,
                "share_pct": 5,
            },
            "ranges": {"customer_count": {"low_pct": -30, "high_pct": 20}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "industry_total")


def test_sensitivity_both_base_result_nested() -> None:
    """Approach 'both' -> base_result has top_down and bottom_up sub-objects."""
    payload = json.dumps(
        {
            "approach": "both",
            "base": {
                "customer_count": 4500000,
                "arpu": 15000,
                "serviceable_pct": 35,
                "target_pct": 0.5,
                "industry_total": 100000000000,
                "segment_pct": 6,
                "share_pct": 5,
            },
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    br = data.get("base_result", {})
    assert "top_down" in br
    assert "bottom_up" in br
    assert "tam" in br.get("top_down", {})
    assert "som" in br.get("bottom_up", {})


# -- Accepted warnings tests --


def test_compose_accepted_warning() -> None:
    """methodology with accepted_warnings -> warning severity downgraded to acknowledged."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "TAM_DISCREPANCY", "reason": "Different scopes intended", "match": "differ by"},
    ]
    sizing = dict(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 45, "warning": "Large discrepancy"}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    tam_w = [w for w in data["validation"]["warnings"] if w["code"] == "TAM_DISCREPANCY"]
    assert len(tam_w) == 1
    assert tam_w[0]["severity"] == "acknowledged"
    assert "Accepted" in tam_w[0]["message"]


def test_compose_accepted_warning_strict_passes() -> None:
    """Accepted warning with --strict -> exit 0 (acknowledged warnings don't block)."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "TAM_DISCREPANCY", "reason": "Expected", "match": "differ by"},
    ]
    sizing = dict(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 45, "warning": "Large discrepancy"}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d, extra_args=["--strict"])
    assert rc == 0
    assert data is not None


def test_compose_accepted_high_severity_ignored() -> None:
    """accepted_warnings with high-severity code -> NOT downgraded, stderr mentions cannot accept."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "CHECKLIST_FAILURES", "reason": "Trust me", "match": "failures"},
    ]
    failed_checklist = dict(_VALID_CHECKLIST)
    failed_checklist["summary"] = {
        "total": 22,
        "pass": 20,
        "fail": 2,
        "not_applicable": 0,
        "overall_status": "fail",
        "failed_items": [
            {
                "id": "tam_matches_product_scope",
                "category": "TAM Scoping",
                "label": "TAM matches product scope",
                "notes": "Too broad",
            },
            {
                "id": "som_share_defensible",
                "category": "SOM Realism",
                "label": "SOM share defensible",
                "notes": "No justification",
            },
        ],
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": failed_checklist,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    checklist_w = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES"]
    assert len(checklist_w) == 1
    assert checklist_w[0]["severity"] == "high"
    assert "cannot accept" in stderr


def test_compose_accepted_unknown_code() -> None:
    """accepted_warnings with unknown code -> no crash, no effect."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "BOGUS", "reason": "test", "match": "anything"},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None


def test_compose_accepted_match_scoping() -> None:
    """accepted_warnings for high-severity code -> not downgraded (only medium is acceptible)."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "MISSING_ARTIFACT", "reason": "Sensitivity not needed", "match": "sensitivity.json"},
    ]
    # Missing required artifact -> MISSING_ARTIFACT warning (high severity)
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    missing_w = [
        w
        for w in data["validation"]["warnings"]
        if w["code"] == "MISSING_ARTIFACT" and "sensitivity.json" in w["message"]
    ]
    assert len(missing_w) == 1
    # High-severity warnings are not acceptible — stays at "high", not downgraded
    assert missing_w[0]["severity"] == "high"


def test_compose_accepted_missing_match() -> None:
    """accepted_warnings with code and reason but no match -> skipped, warning NOT downgraded."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "TAM_DISCREPANCY", "reason": "no match field"},
    ]
    sizing = dict(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 45, "warning": "Large discrepancy"}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    tam_w = [w for w in data["validation"]["warnings"] if w["code"] == "TAM_DISCREPANCY"]
    assert tam_w[0]["severity"] == "medium"
    assert "missing" in stderr.lower()


def test_compose_top_down_narrative_segment_pct() -> None:
    """Top-down narrative should show 'targeting 6%' not 'targeting ?%' (segment_pct is in SAM inputs)."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "targeting 6%" in report
    assert "targeting ?%" not in report


def test_compose_key_assumptions_tam_label() -> None:
    """Key assumptions in sizing table should show 'TAM: $' not 'Tam:' for TAM input values."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    # SAM inputs include "tam" as a key — should be labeled "TAM" not "Tam"
    assert "Tam:" not in report
    # The SAM row should format TAM as USD (not raw number with commas)
    assert "TAM: $" in report


def test_compose_sensitivity_approach_display() -> None:
    """Sensitivity table should show 'Top-down'/'Bottom-up' not 'top_down'/'bottom_up'."""
    sensitivity_both = {
        "approach": "both",
        "base_result": {
            "top_down": {"tam": 100000000000, "sam": 6000000000, "som": 300000000},
            "bottom_up": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
        },
        "scenarios": [
            {
                "parameter": "customer_count",
                "confidence": "sourced",
                "original_range": {"low_pct": -30, "high_pct": 20},
                "effective_range": {"low_pct": -30, "high_pct": 20},
                "range_widened": False,
                "base_value": 4500000,
                "approach_used": "bottom_up",
                "low": {"som": 82687500},
                "base": {"som": 118125000},
                "high": {"som": 141750000},
            },
            {
                "parameter": "segment_pct",
                "confidence": "derived",
                "original_range": {"low_pct": -20, "high_pct": 20},
                "effective_range": {"low_pct": -30, "high_pct": 30},
                "range_widened": True,
                "base_value": 6,
                "approach_used": "top_down",
                "low": {"som": 210000000},
                "base": {"som": 300000000},
                "high": {"som": 390000000},
            },
        ],
        "sensitivity_ranking": [
            {"parameter": "segment_pct", "som_swing_pct": 60.0},
            {"parameter": "customer_count", "som_swing_pct": 50.0},
        ],
        "most_sensitive": "segment_pct",
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": sensitivity_both,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "Bottom-up" in report
    assert "Top-down" in report
    assert "bottom_up" not in report.split("## Sensitivity Analysis")[1]
    assert "top_down" not in report.split("## Sensitivity Analysis")[1]


def test_compose_validation_figure_with_label() -> None:
    """Validation section should use agent-provided label for display."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {"figure": "TAM", "status": "validated", "source_count": 3},
        {
            "figure": "passenger_count_y5",
            "label": "Passenger Count (Year 5)",
            "status": "unsupported",
            "source_count": 0,
        },
        {
            "figure": "avg_ticket_price",
            "label": "Average Ticket Price",
            "status": "partially_supported",
            "source_count": 1,
        },
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    # Extract just the Validation section (between "## Validation" and the next "##")
    validation_start = report.index("## Validation\n")
    validation_end = report.index("\n## ", validation_start + 1)
    validation_section = report[validation_start:validation_end]
    # Label should be used instead of raw figure name
    assert "Passenger Count (Year 5)" in validation_section
    assert "passenger_count_y5" not in validation_section
    assert "Average Ticket Price" in validation_section
    assert "avg_ticket_price" not in validation_section
    # Already-readable names without label should be preserved as-is
    assert "**TAM**" in validation_section


def test_compose_validation_figure_no_label_fallback() -> None:
    """Old-style figure_validations without label should render raw figure name (backward compat)."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = [
        {"figure": "TAM", "status": "validated", "source_count": 3},
        {"figure": "passenger_count_y5", "status": "unsupported", "source_count": 0},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    validation_start = report.index("## Validation\n")
    validation_end = report.index("\n## ", validation_start + 1)
    validation_section = report[validation_start:validation_end]
    # Without label, raw figure name should appear
    assert "passenger count y5" in validation_section  # humanized by the shared founder-text policy (_founder_text.py)
    assert "**TAM**" in validation_section


def test_compose_assumptions_label() -> None:
    """Assumption with label uses it instead of _humanize_param fallback."""
    validation = dict(_VALID_VALIDATION)
    validation["assumptions"] = [
        {"name": "customer_count", "value": 4500000, "category": "sourced"},
        {"name": "avg_ticket_price", "label": "Average Ticket Price", "value": 250, "category": "derived"},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assumptions_start = report.index("## Assumptions\n")
    assumptions_end = report.index("\n## ", assumptions_start + 1)
    assumptions_section = report[assumptions_start:assumptions_end]
    # Label should be used for avg_ticket_price
    assert "Average Ticket Price" in assumptions_section
    assert "avg_ticket_price" not in assumptions_section
    # Standard name without label falls back to _humanize_param
    assert "Customer Count" in assumptions_section


def test_compose_accepted_malformed() -> None:
    """accepted_warnings with missing code field -> silently skipped, no crash."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"reason": "no code", "match": "x"},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "missing" in stderr.lower()


# -- Output flag tests --


def test_market_sizing_output_flag() -> None:
    """market_sizing.py with -o writes to file, stdout empty."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "market_sizing.py",
            [
                "--approach",
                "bottom-up",
                "--customer-count",
                "4500000",
                "--arpu",
                "15000",
                "--serviceable-pct",
                "35",
                "--target-pct",
                "0.5",
                "--pretty",
                "-o",
                tmp,
            ],
        )
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        assert os.path.exists(tmp)
        with open(tmp) as fh:
            data = json.load(fh)
        assert "bottom_up" in data
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_sensitivity_output_flag() -> None:
    """sensitivity.py with -o writes to file, stdout empty."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
            "ranges": {"customer_count": {"low_pct": -30, "high_pct": 20}},
        }
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "sensitivity.py",
            [
                "--pretty",
                "-o",
                tmp,
            ],
            stdin_data=payload,
        )
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "scenarios" in data
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_checklist_output_flag() -> None:
    """checklist.py with -o writes to file, stdout empty."""
    payload = json.dumps({"items": _make_checklist_items()})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "checklist.py",
            [
                "--pretty",
                "-o",
                tmp,
            ],
            stdin_data=payload,
        )
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "summary" in data
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_output_flag_missing_parent_dir() -> None:
    """Output to nonexistent parent dir -> auto-creates dir and writes file."""
    with tempfile.TemporaryDirectory() as td:
        bad_path = os.path.join(td, "nonexistent-child", "file.json")
        rc, stdout, stderr = run_script_raw(
            "market_sizing.py",
            [
                "--approach",
                "bottom-up",
                "--customer-count",
                "1000",
                "--arpu",
                "100",
                "--serviceable-pct",
                "10",
                "--target-pct",
                "1",
                "-o",
                bad_path,
            ],
        )
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        assert os.path.isfile(bad_path)


def test_output_flag_pretty_format() -> None:
    """sensitivity.py with --pretty -o produces indented JSON in file."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, _, _ = run_script_raw(
            "sensitivity.py",
            [
                "--pretty",
                "-o",
                tmp,
            ],
            stdin_data=payload,
        )
        assert rc == 0
        with open(tmp) as fh:
            content = fh.read()
        assert "\n  " in content
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_sensitivity_non_dict_range_entry() -> None:
    """Range entry that is not a dict (e.g. integer) -> validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
            "ranges": {"arpu": 42},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "must be an object")


def test_checklist_non_dict_item() -> None:
    """Non-dict item in checklist items array -> validation error."""
    payload = json.dumps({"items": ["not_a_dict"]})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "must be an object")


def test_compose_corrupt_artifact() -> None:
    """Corrupt JSON artifact -> CORRUPT_ARTIFACT warning, not MISSING_ARTIFACT."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    # Write corrupt JSON to sensitivity.json
    with open(os.path.join(d, "sensitivity.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes
    assert "MISSING_OPTIONAL_ARTIFACT" not in codes


def test_compose_corrupt_required_artifact() -> None:
    """Corrupt required artifact -> CORRUPT_ARTIFACT (not MISSING_ARTIFACT)."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    # Write corrupt JSON to sizing.json
    with open(os.path.join(d, "sizing.json"), "w") as f:
        f.write("not valid json")
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes
    # sizing.json should NOT appear as MISSING_ARTIFACT
    missing_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    assert not any("sizing.json" in m for m in missing_msgs)


def test_compose_strict_mode_all_required_present() -> None:
    """Strict mode succeeds when all required artifacts are present."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": _VALID_SENSITIVITY,
        }
    )
    rc, data, _ = _run_compose(d, extra_args=["--strict"])
    assert rc == 0
    assert data is not None


def test_output_flag_root_path_blocked() -> None:
    """Output to root directory -> exit 1 with error."""
    rc, stdout, stderr = run_script_raw(
        "market_sizing.py",
        [
            "--approach",
            "bottom-up",
            "--customer-count",
            "1000",
            "--arpu",
            "100",
            "--serviceable-pct",
            "10",
            "--target-pct",
            "1",
            "-o",
            "/sensitivity.json",
        ],
    )
    assert rc == 1, f"rc={rc}"
    assert "root directory" in stderr


# -- New regression tests --


def test_market_sizing_stdin_non_string_approach() -> None:
    """Non-string approach in stdin JSON should produce validation error."""
    payload = json.dumps({"approach": 123})
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "string")


def test_market_sizing_growth_rate_below_minus_100() -> None:
    """Growth rate below -100% should produce validation error."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "1000000",
            "--segment-pct",
            "10",
            "--share-pct",
            "5",
            "--growth-rate",
            "-150",
            "--years",
            "5",
        ],
    )
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "-100")


def test_market_sizing_zero_industry_total() -> None:
    """Zero industry_total should produce validation error (validate_positive rejects <= 0)."""
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--approach", "top-down", "--industry-total", "0", "--segment-pct", "10", "--share-pct", "5"],
    )
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "positive")


def test_compose_strict_mode_writes_output_file() -> None:
    """--strict -o should write output file THEN exit 1."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, _, _ = run_script_raw(
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


def test_compose_malformed_field_types() -> None:
    """Artifact with wrong field type (string instead of list) should not crash."""
    validation = dict(_VALID_VALIDATION)
    validation["figure_validations"] = "not a list"
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None


def test_sensitivity_customer_count_fractional() -> None:
    """Fractional customer_count in sensitivity base should produce validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 3.7, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "whole number")


def test_sensitivity_irrelevant_param_warned() -> None:
    """Single-approach mode warns about irrelevant range params."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {
                "industry_total": {"low_pct": -10, "high_pct": 10},
                "customer_count": {"low_pct": -10, "high_pct": 10},
            },
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "ignoring" in stderr.lower()
    params_in_scenarios = [s["parameter"] for s in data["scenarios"]]
    assert "customer_count" in params_in_scenarios
    assert "industry_total" not in params_in_scenarios


def test_sensitivity_all_irrelevant_error() -> None:
    """Single-approach mode with ONLY irrelevant params -> validation error."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"industry_total": {"low_pct": -10, "high_pct": 10}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", [], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "no relevant")


def test_sensitivity_pct_clamping_warned() -> None:
    """Percentage param clamped to 100 emits warning."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 50},
            "ranges": {"target_pct": {"low_pct": -10, "high_pct": 150}},
        }
    )
    rc, data, stderr = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "clamped" in stderr.lower()


def test_compose_accepted_warning_case_insensitive() -> None:
    """Case-insensitive matching in accepted_warnings."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "TAM_DISCREPANCY", "reason": "Expected difference", "match": "DIFFER BY"},
    ]
    sizing = dict(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 45, "warning": "Large discrepancy"}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    tam_w = [w for w in data["validation"]["warnings"] if w["code"] == "TAM_DISCREPANCY"]
    assert len(tam_w) == 1
    assert tam_w[0]["severity"] == "acknowledged"


def test_compose_unnamed_sources_not_collapsed() -> None:
    """Two no-URL/no-title sources should both appear."""
    validation = dict(_VALID_VALIDATION)
    validation["sources"] = [
        {"publisher": "Source A", "supported": "TAM"},
        {"publisher": "Source B", "supported": "SAM"},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "Source A" in report
    assert "Source B" in report


def test_compose_accepted_warning_missing_reason_skipped() -> None:
    """Accepted warning without reason field is skipped."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "TAM_DISCREPANCY", "match": "differ"},
    ]
    sizing = dict(_VALID_SIZING)
    sizing["comparison"] = {"tam_delta_pct": 45, "warning": "Large discrepancy"}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": sizing,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    tam_w = [w for w in data["validation"]["warnings"] if w["code"] == "TAM_DISCREPANCY"]
    assert len(tam_w) == 1
    assert tam_w[0]["severity"] == "medium"  # NOT acknowledged
    assert "reason" in stderr.lower()


def test_compose_checklist_extra_items() -> None:
    """Checklist with >22 items -> CHECKLIST_INCOMPLETE."""
    checklist = dict(_VALID_CHECKLIST)
    # Add 3 extra items
    extra_items = list(_VALID_CHECKLIST["items"]) + [
        {"id": "extra_1", "category": "Extra", "label": "Extra", "status": "pass", "notes": None},
        {"id": "extra_2", "category": "Extra", "label": "Extra", "status": "pass", "notes": None},
        {"id": "extra_3", "category": "Extra", "label": "Extra", "status": "pass", "notes": None},
    ]
    checklist["items"] = extra_items
    checklist["summary"] = dict(_VALID_CHECKLIST["summary"])  # type: ignore[arg-type]
    checklist["summary"]["total"] = 25  # type: ignore[index]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CHECKLIST_INCOMPLETE" in codes


def test_compare_uses_raw_values() -> None:
    """compare() uses raw_value instead of rounded value."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "both",
            "--industry-total",
            "100000000000",
            "--segment-pct",
            "6",
            "--share-pct",
            "5",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None
    # raw_value should exist
    assert "raw_value" in data["top_down"]["tam"]
    assert "raw_value" in data["bottom_up"]["tam"]
    assert isinstance(data["top_down"]["tam"]["raw_value"], (int, float))


def test_checklist_output_canonical_order() -> None:
    """Items in reverse order should output in canonical order."""
    items = list(reversed(_make_checklist_items()))
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    output_ids = [item["id"] for item in data["items"]]
    assert output_ids == _CHECKLIST_IDS


def test_checklist_notes_coerced() -> None:
    """Integer notes should be coerced to string."""
    overrides = {"data_current": {"status": "pass", "notes": 42}}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    dc_item = [i for i in data["items"] if i["id"] == "data_current"][0]
    assert dc_item["notes"] == "42"
    assert isinstance(dc_item["notes"], str)


# --- Triage #3 fixes ---


def test_market_sizing_stdin_empty_object() -> None:
    """Empty JSON object via stdin should read keys as None and error clearly, not fall to CLI."""
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin", "--pretty"],
        stdin_data="{}",
    )
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "requires")


def test_market_sizing_stdin_empty_object_bottom_up() -> None:
    """Empty JSON object with bottom_up approach should read fields from JSON (all None)."""
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin", "--pretty"],
        stdin_data='{"approach": "bottom_up"}',
    )
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    _assert_validation_errors(data, "bottom-up requires")


# ---------------------------------------------------------------------------
# Provenance tracking tests
# ---------------------------------------------------------------------------


def test_compose_deck_claim_comparison() -> None:
    """Artifacts with existing_claims in inputs.json → comparison table in markdown."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": 50000000000, "sam": 8000000000, "som": 200000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Deck Claims vs. Our Estimates" in md
    assert "$50.0B" in md  # deck claim for TAM


def test_compose_deck_claim_mismatch_warning() -> None:
    """>50% delta between deck claim and calculated → DECK_CLAIM_MISMATCH warning."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    # Bottom-up TAM is 67.5B, deck claim of 10B → >50% delta
    inputs["existing_claims"] = {"tam": 10000000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "DECK_CLAIM_MISMATCH" in codes


def test_compose_deck_claim_no_warning_under_threshold() -> None:
    """<50% delta between deck claim and calculated → no DECK_CLAIM_MISMATCH."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    # TD TAM=100B, BU TAM=67.5B; claim of 80B → TD delta=+25%, BU delta=-15.6%, both under 50%
    inputs["existing_claims"] = {"tam": 80000000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "DECK_CLAIM_MISMATCH" not in codes


def test_compose_provenance_column() -> None:
    """Figures with assumption categories → Provenance column in sizing table."""
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "| Provenance |" in md or "Provenance" in md


def test_compose_provenance_unknown() -> None:
    """validation.json missing assumption for a quantitative param → 'unknown' + PROVENANCE_UNRESOLVED."""
    # validation has NO assumptions at all
    validation: dict[str, Any] = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [],
    }
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": validation,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "PROVENANCE_UNRESOLVED" in codes
    # Provenance should report 'unknown' for metrics
    provenance = data.get("provenance", {})
    if provenance:
        for approach_data in provenance.values():
            for metric_prov in approach_data.values():
                assert metric_prov["classification"] == "unknown"


def test_compose_provenance_intermediate_keys_skipped() -> None:
    """sizing.json with tam, serviceable_customers in SAM/SOM inputs → silently ignored."""
    # The default _VALID_SIZING has intermediates like 'tam', 'sam', 'serviceable_customers'
    # in SAM/SOM inputs. These should NOT trigger PROVENANCE_UNRESOLVED.
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    # Should NOT have PROVENANCE_UNRESOLVED for intermediate keys like 'tam', 'sam'
    unresolved = [w for w in warnings if w["code"] == "PROVENANCE_UNRESOLVED"]
    if unresolved:
        # If there's a PROVENANCE_UNRESOLVED, it should NOT mention 'tam' or 'sam' or 'serviceable_customers'
        for w in unresolved:
            assert "tam " not in w["message"].lower() or "tam," not in w["message"].lower()


def test_compose_provenance_classification_correctness() -> None:
    """Known fixture: all-sourced → sourced; mixed with agent_estimate → agent_estimate."""
    # Create validation with known categories
    validation_all_sourced = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [
            {"name": "industry_total", "value": 100000000000, "category": "sourced"},
            {"name": "segment_pct", "value": 6, "category": "sourced"},
            {"name": "share_pct", "value": 5, "category": "sourced"},
            {"name": "customer_count", "value": 4500000, "category": "sourced"},
            {"name": "arpu", "value": 15000, "category": "sourced"},
        ],
    }
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": validation_all_sourced,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    provenance = data.get("provenance", {})
    assert provenance, "Expected provenance in output"
    # Top-down TAM uses industry_total (sourced) → sourced
    td = provenance.get("top_down", {})
    assert td.get("tam", {}).get("classification") == "sourced"
    # Bottom-up TAM uses customer_count (sourced) + arpu (sourced) → sourced
    bu = provenance.get("bottom_up", {})
    assert bu.get("tam", {}).get("classification") == "sourced"

    # Now test with one agent_estimate
    validation_mixed = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [
            {"name": "industry_total", "value": 100000000000, "category": "sourced"},
            {"name": "segment_pct", "value": 6, "category": "sourced"},
            {"name": "share_pct", "value": 5, "category": "sourced"},
            {"name": "customer_count", "value": 4500000, "category": "agent_estimate"},
            {"name": "arpu", "value": 15000, "category": "sourced"},
        ],
    }
    arts["validation.json"] = validation_mixed
    d2 = _make_artifact_dir(arts)
    rc2, data2, _stderr2 = run_script("compose_report.py", ["--dir", d2])
    assert rc2 == 0
    assert data2 is not None
    provenance2 = data2.get("provenance", {})
    # Bottom-up TAM uses customer_count (agent_estimate) + arpu (sourced) → agent_estimate
    bu2 = provenance2.get("bottom_up", {})
    assert bu2.get("tam", {}).get("classification") == "agent_estimate"
    # Top-down TAM uses industry_total (sourced) → still sourced
    td2 = provenance2.get("top_down", {})
    assert td2.get("tam", {}).get("classification") == "sourced"


def test_compose_deck_claim_zero() -> None:
    """existing_claims: {tam: 0} → no comparison row for TAM (delta is None)."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": 0}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    # No DECK_CLAIM_MISMATCH since delta is None for zero claim
    warnings = data["validation"]["warnings"]
    mismatch = [w for w in warnings if w["code"] == "DECK_CLAIM_MISMATCH"]
    assert not mismatch


def test_compose_deck_claim_non_numeric() -> None:
    """existing_claims: {tam: 'big'} → no comparison row, no crash."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": "big"}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None


def test_compose_deck_claim_partial() -> None:
    """existing_claims: {tam: 50B} (SAM/SOM missing) → only TAM row in comparison."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": 50000000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    if "Deck Claims" in md:
        # Should have TAM but not SAM/SOM in comparison table
        assert "TAM" in md


def test_compose_deck_claim_negative() -> None:
    """existing_claims: {tam: -100} → no comparison row."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": -100}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    mismatch = [w for w in warnings if w["code"] == "DECK_CLAIM_MISMATCH"]
    assert not mismatch


def test_compose_deck_claim_both_mode_labels_approaches() -> None:
    """Both-mode sizing with deck claims → notes label each approach, no duplicates."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    # TD TAM=100B, BU TAM=67.5B; claim of 84B → both differ by >50%? No.
    # Use a very small claim so both approaches exceed 50% delta.
    inputs["existing_claims"] = {"tam": 1000000000}  # $1B claim
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,  # approach: "both"
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Should produce ONE consolidated note with both approach labels, not two separate notes
    note_count = md.count("TAM estimate")
    assert note_count == 1, f"Expected 1 consolidated TAM note, got {note_count}"
    assert "Both TAM estimates" in md
    assert "Top-down:" in md
    assert "Bottom-up:" in md


def test_compose_deck_claim_both_mode_single_mismatch() -> None:
    """Both-mode where only one approach exceeds 50% delta → labels which approach."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    # TD TAM=100B; claim of 80B → delta +25% (under threshold)
    # BU TAM=67.5B; claim of 80B → delta -15.6% (under threshold)
    # Need claim where only one crosses 50%:
    # TD TAM=100B vs 40B → +150% (over); BU TAM=67.5B vs 40B → +68.75% (also over)
    # Try: 60B → TD delta +66.7% (over), BU delta +12.5% (under)
    inputs["existing_claims"] = {"tam": 60000000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Only top-down exceeds 50% threshold — note should label the approach
    assert "top-down TAM estimate differs" in md
    # Should NOT say "Both TAM estimates" since only one approach exceeds threshold
    assert "Both TAM estimates" not in md


def test_compose_deck_claim_mismatch_low_severity() -> None:
    """>50% delta → DECK_CLAIM_MISMATCH with severity 'low'; --strict does NOT exit 1."""
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": 10000000000}
    arts = {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    # First check severity is low
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0
    assert data is not None
    mismatch = [w for w in data["validation"]["warnings"] if w["code"] == "DECK_CLAIM_MISMATCH"]
    assert len(mismatch) > 0
    assert mismatch[0]["severity"] == "low"

    # --strict should NOT exit 1 for low-severity warnings (only high/medium)
    rc_strict, _, _stderr_strict = run_script("compose_report.py", ["--dir", d, "--strict"])
    assert rc_strict == 0, "Low-severity DECK_CLAIM_MISMATCH should not block --strict"


# === v0.4.1 Phase 3 Task 11: compose on-disk verification + tolerant JSON extraction ===

from pathlib import Path  # noqa: E402


def _make_full_sizing_dir(review_dir: Path) -> None:
    """Write all 6 required artifacts plus valid checklist into review_dir."""
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "sensitivity.json": _VALID_SENSITIVITY,
        "checklist.json": _VALID_CHECKLIST,
    }
    for name, data in arts.items():
        with open(review_dir / name, "w") as f:
            json.dump(data, f)


def test_compose_verifies_outputs_exist_after_write(tmp_path: Path) -> None:
    """After successful compose, both report.json and report.md must exist on disk."""
    sizing_dir = tmp_path / "market-sizing-testco"
    sizing_dir.mkdir()
    _make_full_sizing_dir(sizing_dir)
    json_path = str(sizing_dir / "report.json")
    md_path = str(sizing_dir / "report.md")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", str(sizing_dir), "-o", json_path, "--write-md", md_path],
    )
    assert rc == 0, err
    assert os.path.isfile(json_path)
    assert os.path.isfile(md_path)
    assert os.path.getsize(json_path) > 0
    assert os.path.getsize(md_path) > 0


def test_compose_exits_nonzero_if_write_md_path_unwritable(tmp_path: Path) -> None:
    """Compose must exit nonzero if --write-md target dir doesn't exist and can't be created."""
    sizing_dir = tmp_path / "market-sizing-testco"
    sizing_dir.mkdir()
    _make_full_sizing_dir(sizing_dir)
    # Point --write-md at a path inside a read-only parent
    ro_parent = tmp_path / "readonly"
    ro_parent.mkdir(mode=0o555)
    bad_md_path = str(ro_parent / "no-write" / "report.md")
    json_path = str(sizing_dir / "report.json")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", str(sizing_dir), "-o", json_path, "--write-md", bad_md_path],
    )
    assert rc != 0, "compose should exit nonzero when --write-md target is unwritable"
    # Cleanup: restore writable mode so tmp_path can be deleted
    os.chmod(ro_parent, 0o755)


# === v0.4.1 Phase 3 Task 11: tolerant JSON extraction ===


def test_extract_dispatch_json_raw_object() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_dispatch_json_fenced() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_dispatch_json_nested() -> None:
    """Critical regression test: must not truncate on inner }."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = '```json\n{"a": {"b": 1}, "c": 2}\n```'
    assert extract_dispatch_json(text) == {"a": {"b": 1}, "c": 2}


def test_extract_dispatch_json_embedded_in_prose() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = 'Here is the result:\n{"a": 1, "b": 2}\nLet me know if anything is wrong.'
    assert extract_dispatch_json(text) == {"a": 1, "b": 2}


def test_extract_dispatch_json_raises_when_no_json() -> None:
    import sys

    import pytest

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    with pytest.raises(ValueError):
        extract_dispatch_json("Just some prose with no JSON object anywhere.")


# === v0.4.2 Phase 3 Task 8: coaching_payload + uuid insertion marker ===


def _make_full_sizing_arts() -> dict[str, Any]:
    """Return a dict of all 6 required artifacts for compose tests."""
    return {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "sensitivity.json": _VALID_SENSITIVITY,
        "checklist.json": _VALID_CHECKLIST,
    }


def test_compose_emits_coaching_payload() -> None:
    """compose emits a coaching_payload block with all v0.4.2-market-sizing fields."""
    import re

    d = _make_artifact_dir(_make_full_sizing_arts())
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "coaching_payload" in data, "report.json missing coaching_payload block"

    payload = data["coaching_payload"]
    assert payload["schema_version"] == "v0.4.2-market-sizing"

    # All expected top-level keys present
    for key in (
        "schema_version",
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "company_name",
        "methodology",
        "review_dir",
        "report_path",
        "insertion_marker",
    ):
        assert key in payload, f"coaching_payload missing key: {key}"

    # Summary mirrors checklist counts (no warn key — market-sizing only has pass/fail/na)
    s = payload["summary"]
    for sk in ("score_pct", "overall_status", "total", "pass", "fail", "not_applicable"):
        assert sk in s, f"coaching_payload.summary missing {sk}"

    # company_name and methodology surfaced from artifacts
    assert payload["company_name"] == "TestCo"
    assert payload["methodology"] == "both"

    # warned_items is always an explicit empty list
    assert payload["warned_items"] == [], "warned_items must be explicit empty list"

    # Insertion marker matches uuid format
    assert re.fullmatch(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", payload["insertion_marker"]), (
        f"unexpected marker shape: {payload['insertion_marker']}"
    )

    # Backward-compat: existing top-level keys still present
    assert "report_markdown" in data
    assert "validation" in data


# === Finding 26/27 fix: coaching_payload.tam/sam/som + currency ===
#
# The Context B coaching sub-agent is told to reason from the headline market
# values in coaching_payload and NEVER refetch from disk. Before this fix,
# compose_report.py never put tam/sam/som/currency in the payload at all —
# a compliant sub-agent could not ground coaching in the actual market size.
# sizing.json never carries a top-level scalar "tam"/"sam"/"som"; the real
# numbers are nested at top_down.tam.value / bottom_up.tam.value etc.


def test_coaching_payload_market_size_bottom_up_mode() -> None:
    """bottom_up-only mode: tam/sam/som resolve from sizing.bottom_up.*.value, currency labelled."""
    arts = _make_full_sizing_arts()
    arts["methodology.json"] = {**_VALID_METHODOLOGY, "approach_chosen": "bottom_up"}
    arts["sizing.json"] = {
        "approach": "bottom_up",
        "currency": "USD",
        "bottom_up": _VALID_SIZING["bottom_up"],
    }
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    payload = data["coaching_payload"]
    assert payload["tam"] == _VALID_SIZING["bottom_up"]["tam"]["value"]
    assert payload["sam"] == _VALID_SIZING["bottom_up"]["sam"]["value"]
    assert payload["som"] == _VALID_SIZING["bottom_up"]["som"]["value"]
    assert payload["currency"] == "USD"
    assert payload["market_size_approach"] == "bottom_up"


def test_coaching_payload_market_size_top_down_mode() -> None:
    """top_down-only mode: tam/sam/som resolve from sizing.top_down.*.value (bottom_up absent)."""
    arts = _make_full_sizing_arts()
    arts["methodology.json"] = {**_VALID_METHODOLOGY, "approach_chosen": "top_down"}
    arts["sizing.json"] = {
        "approach": "top_down",
        "currency": "ILS",
        "top_down": _VALID_SIZING["top_down"],
    }
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    payload = data["coaching_payload"]
    assert payload["tam"] == _VALID_SIZING["top_down"]["tam"]["value"]
    assert payload["sam"] == _VALID_SIZING["top_down"]["sam"]["value"]
    assert payload["som"] == _VALID_SIZING["top_down"]["som"]["value"]
    assert payload["currency"] == "ILS"
    assert payload["market_size_approach"] == "top_down"


def test_coaching_payload_market_size_both_mode_prefers_bottom_up() -> None:
    """both mode: two competing TAMs exist (top_down and bottom_up); the documented
    selection rule (references/tam-sam-som-methodology.md's "prefer bottom-up for
    accuracy" convention) picks bottom_up as the headline figure, not top_down and
    not an average of the two.
    """
    d = _make_artifact_dir(_make_full_sizing_arts())  # _VALID_SIZING is "both" mode
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    payload = data["coaching_payload"]
    assert payload["tam"] == _VALID_SIZING["bottom_up"]["tam"]["value"]
    assert payload["sam"] == _VALID_SIZING["bottom_up"]["sam"]["value"]
    assert payload["som"] == _VALID_SIZING["bottom_up"]["som"]["value"]
    # Must NOT be the top_down figure, and must NOT be an average of the two.
    assert payload["tam"] != _VALID_SIZING["top_down"]["tam"]["value"]
    assert payload["currency"] == "USD"  # _VALID_SIZING carries no currency; default
    assert payload["market_size_approach"] == "bottom_up"


def test_coaching_payload_market_size_null_when_sizing_missing() -> None:
    """No sizing.json at all: tam/sam/som/market_size_approach are null, not fabricated."""
    arts = _make_full_sizing_arts()
    del arts["sizing.json"]
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    payload = data["coaching_payload"]
    assert payload["tam"] is None
    assert payload["sam"] is None
    assert payload["som"] is None
    assert payload["market_size_approach"] is None
    # Currency still defaults to USD even with no sizing.json to read it from.
    assert payload["currency"] == "USD"


def test_compose_inserts_uuid_marker() -> None:
    """report.md contains exactly one uuid marker matching coaching_payload.insertion_marker."""
    import re

    d = _make_artifact_dir(_make_full_sizing_arts())
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
    import copy

    # Inject the marker substring into a source title, which is rendered in _section_sources.
    validation: dict[str, Any] = copy.deepcopy(_VALID_VALIDATION)
    validation["sources"] = [
        {
            "title": "Sneaky body content with <!-- COACHING_INSERTION_POINT_aaaaaaaa --> embedded",
            "publisher": "Test",
            "url": "https://example.com",
            "date_accessed": "2026-01-15",
            "supported": "TAM figure",
        }
    ]

    arts = _make_full_sizing_arts()
    arts["validation.json"] = validation
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    # Compose still succeeds (warning, not error)
    assert rc == 0, err
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes, f"expected MARKER_COLLISION in warnings, got: {codes}"


def test_payload_failed_items_match_summary_fail() -> None:
    """coaching_payload.failed_items length matches summary.fail count."""
    import copy

    checklist: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    items = checklist["items"]
    # Make 3 items fail
    for i in range(3):
        items[i] = dict(items[i])
        items[i]["status"] = "fail"
    failed_items = [
        {"id": items[i]["id"], "category": items[i]["category"], "label": items[i]["label"], "notes": None}
        for i in range(3)
    ]
    checklist["summary"] = {
        "total": 22,
        "pass": 19,
        "fail": 3,
        "not_applicable": 0,
        "score_pct": 86.4,
        "overall_status": "fail",
        "failed_items": failed_items,
    }

    arts = _make_full_sizing_arts()
    arts["checklist.json"] = checklist
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert len(payload["failed_items"]) == payload["summary"]["fail"] == 3


def test_payload_warned_items_always_empty() -> None:
    """coached_payload.warned_items is always [] even if checklist had warn entries (schema parity).

    market-sizing's checklist has no warn status. This test verifies the field is
    invariantly an explicit empty list regardless of what's in checklist data.
    """
    import copy

    # Construct a checklist summary that (hypothetically) has a warned_items list —
    # market-sizing can't produce this but the schema should be robust against it.
    checklist: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    checklist["summary"] = dict(checklist["summary"])
    # Inject warned_items into the summary (not a valid market-sizing output,
    # but we're testing the compose layer's invariant)
    checklist["summary"]["warned_items"] = [
        {"id": "some_item", "category": "Test", "label": "Test warn", "notes": None}
    ]

    arts = _make_full_sizing_arts()
    arts["checklist.json"] = checklist
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    # Must always be empty list regardless of checklist content
    assert payload["warned_items"] == [], (
        "coached_payload.warned_items must always be [] for market-sizing (no warn status)"
    )


# ---------------------------------------------------------------------------
# EXISTING_CLAIMS_SHAPE — non-canonical keys silently bypass reconciliation
# ---------------------------------------------------------------------------


def _make_basic_arts(inputs_overrides: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal valid artifact set with custom inputs overrides."""
    import copy

    inputs = copy.deepcopy(_VALID_INPUTS)
    inputs.update(inputs_overrides)
    return {
        "inputs.json": inputs,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }


def test_existing_claims_shape_warns_on_non_canonical_keys() -> None:
    """Non-canonical keys → EXISTING_CLAIMS_SHAPE warning that lists them."""
    arts = _make_basic_arts({"existing_claims": {"SAM_Israel_only": 16800000}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    matching = [w for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]
    assert len(matching) == 1
    assert "SAM_Israel_only" in matching[0]["message"]
    assert matching[0]["severity"] == "medium"


def test_existing_claims_shape_warns_on_uppercase_canonical() -> None:
    """Uppercase canonical (TAM) is non-canonical (case-sensitive) → warn."""
    arts = _make_basic_arts({"existing_claims": {"TAM": 12000000000}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" in codes


def test_existing_claims_shape_warns_on_mixed_canonical_and_custom() -> None:
    """Mixed canonical + custom → warn lists only the custom key."""
    arts = _make_basic_arts({"existing_claims": {"tam": 1e9, "SAM_Israel_only": 2e6}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    matching = [w for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]
    assert len(matching) == 1
    assert "SAM_Israel_only" in matching[0]["message"]
    assert "tam" not in matching[0]["message"].split(": ", 1)[1].split(".")[0]


def test_existing_claims_shape_no_warn_on_canonical() -> None:
    """All-canonical keys with values → no warning."""
    arts = _make_basic_arts({"existing_claims": {"tam": 1e9, "sam": 8e8, "som": 2e7}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" not in codes


def test_existing_claims_shape_no_warn_on_null_canonical_template() -> None:
    """All-canonical-null (the new heredoc template) → no warning.

    Locks the PR B happy path: agents using the canonical template must
    not trip EXISTING_CLAIMS_SHAPE.
    """
    arts = _make_basic_arts({"existing_claims": {"tam": None, "sam": None, "som": None}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" not in codes


def test_existing_claims_shape_no_warn_on_empty_dict() -> None:
    """Empty dict (legacy template) → no warning (backward compat)."""
    arts = _make_basic_arts({"existing_claims": {}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" not in codes


def test_existing_claims_shape_no_warn_on_field_absent() -> None:
    """Field absent from inputs → no warning."""
    # _VALID_INPUTS has no existing_claims field by default
    arts = _make_basic_arts({})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" not in codes


def test_existing_claims_shape_no_warn_on_null_field() -> None:
    """existing_claims: null → no warning (treated as absent via _as_dict)."""
    arts = _make_basic_arts({"existing_claims": None})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" not in codes


def test_existing_claims_shape_warns_on_list_type() -> None:
    """existing_claims as a list → warn with type message."""
    arts = _make_basic_arts({"existing_claims": ["TAM is $12B"]})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    matching = [w for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]
    assert len(matching) == 1
    assert "list" in matching[0]["message"]


def test_existing_claims_shape_warns_on_string_type() -> None:
    """existing_claims as a string → warn with type message."""
    arts = _make_basic_arts({"existing_claims": "TAM is $12B"})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    matching = [w for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]
    assert len(matching) == 1
    assert "str" in matching[0]["message"]


# ---------------------------------------------------------------------------
# _compute_provenance — canonical-key contract (TRIPWIRE)
# ---------------------------------------------------------------------------


def test_compute_provenance_populates_deck_claim_on_canonical_keys() -> None:
    """Canonical lowercase keys → deck_claim populated, delta computed."""
    arts = _make_basic_arts({"existing_claims": {"tam": 50000000000, "sam": 5000000000, "som": 100000000}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    prov = data.get("provenance", {})
    # top_down sam is 6_000_000_000 (from _VALID_SIZING); deck claim 5e9.
    td_sam = prov["top_down"]["sam"]
    assert td_sam["deck_claim"] == 5000000000
    assert td_sam["delta_vs_deck_pct"] is not None


def test_compute_provenance_returns_none_deck_claim_on_non_canonical_keys() -> None:
    """Non-canonical keys → deck_claim is None.

    Documents the CONTRACTED division of labor between two signals:
    - EXISTING_CLAIMS_SHAPE warning is the shape signal — surfaces
      non-canonical keys to the agent.
    - _compute_provenance is the numerical signal — stays neutral on shape
      errors and reports None when it cannot compute a comparison.

    TRIPWIRE: if a future change adds case-insensitive matching or auto-
    coercion of uppercase keys, this test will fail — forcing a conscious
    decision about whether to drop the warning or keep both safeguards.
    """
    arts = _make_basic_arts({"existing_claims": {"SAM_Israel_only": 16800000}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    prov = data.get("provenance", {})
    for approach in ("top_down", "bottom_up"):
        for metric in ("tam", "sam", "som"):
            assert prov[approach][metric]["deck_claim"] is None
            assert prov[approach][metric]["delta_vs_deck_pct"] is None


# ---------------------------------------------------------------------------
# existing_claims_detail — narrative renderer
# ---------------------------------------------------------------------------


def test_deck_claims_narrative_rendered_when_detail_present() -> None:
    """Populated existing_claims_detail dict → narrative sub-section appears."""
    arts = _make_basic_arts(
        {
            "existing_claims": {"tam": None, "sam": None, "som": None},
            "existing_claims_detail": {
                "regional_sam_north_america": 4500000000,
                "som_year_3_target": 350000000,
            },
        }
    )
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "## Deck Claims (Narrative)" in md
    assert "regional SAM north america" in md  # humanized by the shared founder-text policy (_founder_text.py)
    assert "som_year_3_target" in md


def test_claims_narrative_attributes_to_the_founder_when_no_deck() -> None:
    """A conversational run must not credit the founder's own words to a deck.

    market-sizing supports runs with no upload at all (materials_provided: ["text"]).
    The claims section used to say "The deck stated ..." unconditionally, so a founder
    who typed "our TAM is $50B, validate it" read their own sentence attributed to a
    document that never existed — a wrong provenance statement about their own input.
    """
    arts = _make_basic_arts(
        {
            "materials_provided": ["text"],
            "existing_claims_detail": {"regional_sam_north_america": "$2B"},
        }
    )
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "## Your Stated Figures (Narrative)" in md
    assert "You stated" in md
    assert "The deck stated" not in md
    assert "## Deck Claims (Narrative)" not in md


def test_claims_narrative_still_says_deck_when_a_deck_was_provided() -> None:
    """No false positive: a real deck keeps the deck-attributed wording."""
    arts = _make_basic_arts(
        {
            "materials_provided": ["pitch deck"],
            "existing_claims_detail": {"regional_sam_north_america": "$2B"},
        }
    )
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "## Deck Claims (Narrative)" in md
    assert "The deck stated" in md


def test_deck_claims_narrative_omitted_when_detail_null() -> None:
    """existing_claims_detail: null → section absent."""
    arts = _make_basic_arts({"existing_claims_detail": None})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "## Deck Claims (Narrative)" not in data["report_markdown"]


def test_deck_claims_narrative_omitted_when_detail_empty() -> None:
    """existing_claims_detail: {} → section absent."""
    arts = _make_basic_arts({"existing_claims_detail": {}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "## Deck Claims (Narrative)" not in data["report_markdown"]


# ---------------------------------------------------------------------------
# coaching_payload.deck_coverage — additive in v0.4.2-market-sizing
# ---------------------------------------------------------------------------


def test_coaching_payload_deck_coverage_partial() -> None:
    """One canonical figure stated → stated/missing populated correctly."""
    arts = _make_basic_arts({"existing_claims": {"tam": 12000000000, "sam": None, "som": None}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    cov = data["coaching_payload"]["deck_coverage"]
    assert cov == {"deck_reviewed": True, "stated": ["tam"], "missing": ["sam", "som"]}


def test_coaching_payload_deck_coverage_full() -> None:
    """All three canonical figures stated → missing is empty list."""
    arts = _make_basic_arts({"existing_claims": {"tam": 1e10, "sam": 5e9, "som": 1e8}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    cov = data["coaching_payload"]["deck_coverage"]
    assert cov is not None
    assert cov["deck_reviewed"] is True
    assert cov["stated"] == ["tam", "sam", "som"]
    assert cov["missing"] == []


def test_coaching_payload_deck_coverage_none_when_all_null() -> None:
    """Canonical-null template (no figures actually stated) → deck_coverage is None."""
    arts = _make_basic_arts({"existing_claims": {"tam": None, "sam": None, "som": None}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["coaching_payload"]["deck_coverage"] is None


def test_coaching_payload_deck_coverage_none_when_empty_dict() -> None:
    """Legacy empty-dict template → deck_coverage is None (backward compat)."""
    arts = _make_basic_arts({"existing_claims": {}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["coaching_payload"]["deck_coverage"] is None


def test_coaching_payload_deck_coverage_none_when_field_absent() -> None:
    """existing_claims field absent entirely → deck_coverage is None."""
    arts = _make_basic_arts({})  # _VALID_INPUTS has no existing_claims
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["coaching_payload"]["deck_coverage"] is None


def test_coaching_payload_deck_coverage_none_when_only_non_canonical() -> None:
    """Only non-canonical keys (no canonical figure stated) → deck_coverage is None.

    Documents the contracted interaction with EXISTING_CLAIMS_SHAPE:
    the warning surfaces the shape error; deck_coverage stays neutral.
    Coaching must branch on the warning's presence (per SKILL.md).
    """
    arts = _make_basic_arts({"existing_claims": {"SAM_Israel_only": 16800000}})
    d = _make_artifact_dir(arts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["coaching_payload"]["deck_coverage"] is None
    # And the warning is present — confirming the interaction the coaching
    # template branches on.
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "EXISTING_CLAIMS_SHAPE" in codes


# === run_id stamping (Step 8 Context B depends on metadata.run_id) ===


def test_market_sizing_run_id_stamped() -> None:
    """market_sizing.py --run-id stamps metadata.run_id into output."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "bottom-up",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--run-id",
            "RID-123",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-123"}


def test_market_sizing_run_id_absent_no_metadata() -> None:
    """Without --run-id, no metadata key is emitted (backward compatible)."""
    rc, data, _ = run_script(
        "market_sizing.py",
        [
            "--approach",
            "bottom-up",
            "--customer-count",
            "4500000",
            "--arpu",
            "15000",
            "--serviceable-pct",
            "35",
            "--target-pct",
            "0.5",
            "--pretty",
        ],
    )
    assert rc == 0
    assert data is not None
    assert "metadata" not in data


def test_market_sizing_run_id_stamped_on_validation_error() -> None:
    """run_id is stamped even when validation fails (error path still carries provenance)."""
    payload = json.dumps({"approach": "bottom_up", "customer_count": "not-a-number"})
    rc, data, _ = run_script("market_sizing.py", ["--stdin", "--run-id", "RID-ERR", "--pretty"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    assert data["validation"]["status"] == "invalid"
    assert data.get("metadata") == {"run_id": "RID-ERR"}


def test_sensitivity_run_id_stamped() -> None:
    """sensitivity.py --run-id stamps metadata.run_id into output."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
            "ranges": {"customer_count": {"low_pct": -30, "high_pct": 20, "confidence": "sourced"}},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--run-id", "RID-S", "--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-S"}


def test_checklist_run_id_stamped() -> None:
    """checklist.py --run-id stamps metadata.run_id into output."""
    payload = json.dumps({"items": _make_checklist_items()})
    rc, data, _ = run_script("checklist.py", ["--run-id", "RID-C", "--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata") == {"run_id": "RID-C"}


# === ic-sim+market-sizing-12: both-mode double coercion ===


def test_both_mode_invalid_growth_single_error() -> None:
    """In 'both' stdin mode, an invalid years value yields exactly one error, not two.

    Regression: top-down and bottom-up blocks both re-read growth_rate/years and
    used to append identical coercion errors twice.
    """
    payload = json.dumps(
        {
            "approach": "both",
            "industry_total": 100000000000,
            "segment_pct": 6,
            "share_pct": 5,
            "customer_count": 4500000,
            "arpu": 15000,
            "serviceable_pct": 35,
            "target_pct": 0.5,
            "years": 2.5,  # non-integer → coerce_int error
        }
    )
    rc, data, _ = run_script("market_sizing.py", ["--stdin", "--pretty"], stdin_data=payload)
    assert rc == 1  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert data is not None
    errors = data["validation"]["errors"]
    years_errors = [e for e in errors if "years" in e]
    assert len(years_errors) == 1, f"expected single 'years' error, got: {years_errors}"


# === ic-sim+market-sizing-13: -o receipt parameter count ===


def test_sensitivity_receipt_counts_only_analyzed_params() -> None:
    """The -o receipt 'parameters' count reflects analyzed scenarios, not raw input ranges.

    An irrelevant range param (top_down param for a bottom_up approach) is filtered
    with a warning and must NOT inflate the receipt count.
    """
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
            "ranges": {
                "customer_count": {"low_pct": -30, "high_pct": 20, "confidence": "sourced"},
                "industry_total": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"},
            },
        }
    )
    with tempfile.TemporaryDirectory() as d:
        out_path = os.path.join(d, "sensitivity.json")
        rc, stdout, _ = run_script_raw("sensitivity.py", ["-o", out_path], stdin_data=payload)
        assert rc == 0
        receipt = json.loads(stdout)
        # industry_total is irrelevant for bottom_up and filtered out → only 1 analyzed.
        assert receipt["parameters"] == 1, f"receipt should count analyzed params only: {receipt}"


# === market-sizing-3: coaching_payload.confidence derived from score_pct ===


def _checklist_with_score(score_pct: float) -> dict[str, Any]:
    import copy

    cl: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    cl["summary"] = dict(cl["summary"])
    cl["summary"]["score_pct"] = score_pct
    return cl


def test_coaching_confidence_high() -> None:
    """score_pct >= 85 → coaching_payload.confidence == 'high'."""
    arts = _make_full_sizing_arts()
    arts["checklist.json"] = _checklist_with_score(90.0)
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["confidence"] == "high"


def test_coaching_confidence_medium() -> None:
    """60 <= score_pct < 85 → 'medium'."""
    arts = _make_full_sizing_arts()
    arts["checklist.json"] = _checklist_with_score(72.0)
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["confidence"] == "medium"


def test_coaching_confidence_low() -> None:
    """score_pct < 60 → 'low'."""
    arts = _make_full_sizing_arts()
    arts["checklist.json"] = _checklist_with_score(40.0)
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert data["coaching_payload"]["confidence"] == "low"


def test_coaching_confidence_none_when_score_absent() -> None:
    """No score_pct in checklist summary → confidence is null (not fabricated)."""
    arts = _make_full_sizing_arts()  # _VALID_CHECKLIST summary has no score_pct
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "confidence" in data["coaching_payload"]
    assert data["coaching_payload"]["confidence"] is None


# === ic-sim+market-sizing-6: MARKER_COLLISION reflected in status + Warnings section ===


def test_marker_collision_reflected_in_status_and_section() -> None:
    """A MARKER_COLLISION must flip validation.status to 'warnings' AND appear in
    the rendered Warnings section — not just the JSON warnings array.

    Regression: status was computed and the Warnings section rendered before the
    marker pre-scan appended MARKER_COLLISION, so a clean status could coexist with
    a non-empty warnings list and the warning was absent from the report body.
    """
    import copy

    validation: dict[str, Any] = copy.deepcopy(_VALID_VALIDATION)
    validation["sources"] = [
        {
            "title": "Body content with <!-- COACHING_INSERTION_POINT_bbbbbbbb --> embedded",
            "publisher": "Test",
            "url": "https://example.com",
            "date_accessed": "2026-01-15",
            "supported": "TAM figure",
        }
    ]
    arts = _make_full_sizing_arts()
    arts["validation.json"] = validation
    d = _make_artifact_dir(arts)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes
    # Status must reflect the warning (not "clean").
    assert data["validation"]["status"] == "warnings", (
        "status must account for MARKER_COLLISION appended during the marker pre-scan"
    )
    # The warning must be visible in the rendered Warnings section of the report.
    md = data["report_markdown"]
    assert "Marker Collision" in md or "MARKER_COLLISION" in md, (
        "MARKER_COLLISION must be spliced into the report's Warnings section"
    )


def test_compose_survives_malformed_list_elements() -> None:
    """Agent-supplied artifacts may carry non-dict elements in assumption /
    scenario / figure_validation lists. compose must flag/skip them, not crash
    with AttributeError (parity with the ic-sim twin's isinstance guards)."""
    import copy

    bad_validation = copy.deepcopy(_VALID_VALIDATION)
    bad_validation["assumptions"] = ["not-a-dict", 123, {"category": "agent_estimate", "name": "industry_total"}]
    bad_validation["figure_validations"] = ["oops", {"status": "validated", "source_count": 3}]
    bad_sensitivity = copy.deepcopy(_VALID_SENSITIVITY)
    bad_sensitivity["scenarios"] = [None, 42, {"confidence": "agent_estimate"}]  # type: ignore[list-item]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": bad_validation,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": bad_sensitivity,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, err = _run_compose(d)
    assert rc in (0, 2), f"compose crashed on malformed list elements: rc={rc}, stderr={err}"
    assert "Traceback" not in err and "AttributeError" not in err


# ============================================================
# Artifact self-sufficiency fixes (items 6-8)
# ============================================================


_VALID_SENSITIVITY_WITH_ALL_TIERS = {
    "approach": "bottom_up",
    "base_result": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
    "scenarios": [
        {
            "parameter": "customer_count",
            "confidence": "sourced",
            "original_range": {"low_pct": -30, "high_pct": 20},
            "effective_range": {"low_pct": -30, "high_pct": 20},
            "range_widened": False,
            "base_value": 4500000,
            "low": {"value": 3150000, "tam": 47250000000, "sam": 16537500000, "som": 82687500},
            "base": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
            "high": {"value": 5400000, "tam": 81000000000, "sam": 28350000000, "som": 141750000},
        },
        {
            "parameter": "arpu",
            "confidence": "agent_estimate",
            "original_range": {"low_pct": -50, "high_pct": 100},
            "effective_range": {"low_pct": -50, "high_pct": 100},
            "range_widened": False,
            "base_value": 15000,
            "low": {"value": 7500, "tam": 33750000000, "sam": 11812500000, "som": 59062500},
            "base": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
            "high": {"value": 30000, "tam": 135000000000, "sam": 47250000000, "som": 236250000},
        },
    ],
    "sensitivity_ranking": [{"parameter": "arpu", "som_swing_pct": 150.0}],
    "most_sensitive": "arpu",
}


def _make_all_artifacts(**overrides: Any) -> dict[str, Any]:
    base = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "sensitivity.json": _VALID_SENSITIVITY,
        "checklist.json": _VALID_CHECKLIST,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_compose_sensitivity_shows_tam_sam_when_present() -> None:
    """When sensitivity has tam/sam fields, the table includes TAM and SAM columns."""
    d = _make_artifact_dir(_make_all_artifacts(**{"sensitivity.json": _VALID_SENSITIVITY_WITH_ALL_TIERS}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    sens_section = md.split("## Sensitivity Analysis")[1].split("##")[0]
    # TAM and SAM columns must appear
    assert "| Low TAM |" in sens_section or "Low TAM" in sens_section
    assert "| Low SAM |" in sens_section or "Low SAM" in sens_section
    assert "| Low SOM |" in sens_section or "Low SOM" in sens_section


def test_compose_sensitivity_shows_value_columns_when_present() -> None:
    """When base_value / low.value / high.value are present, a Value column appears."""
    d = _make_artifact_dir(_make_all_artifacts(**{"sensitivity.json": _VALID_SENSITIVITY_WITH_ALL_TIERS}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    sens_section = md.split("## Sensitivity Analysis")[1].split("##")[0]
    # Value columns must appear
    assert "| Low Value |" in sens_section or "Low Value" in sens_section


def test_compose_sensitivity_falls_back_without_tam_sam() -> None:
    """When sensitivity only has som fields, table stays SOM-only (backward compat)."""
    d = _make_artifact_dir(_make_all_artifacts(**{"sensitivity.json": _VALID_SENSITIVITY}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    sens_section = md.split("## Sensitivity Analysis")[1].split("##")[0]
    # Low TAM should NOT appear when not in fixture
    assert "Low TAM" not in sens_section


_VALID_SENSITIVITY_MIXED_UNITS = {
    "approach": "bottom_up",
    "base_result": {"tam": 67500000000, "sam": 23625000000, "som": 118125000},
    "scenarios": [
        {
            "parameter": "industry_total",  # currency
            "confidence": "sourced",
            "original_range": {"low_pct": -20, "high_pct": 20},
            "effective_range": {"low_pct": -20, "high_pct": 20},
            "range_widened": False,
            "base_value": 2800000000,
            "low": {"value": 2240000000, "tam": 2240000000, "sam": 235200000, "som": 8232000},
            "base": {"tam": 2800000000, "sam": 294000000, "som": 10290000},
            "high": {"value": 3360000000, "tam": 3360000000, "sam": 352800000, "som": 12348000},
        },
        {
            "parameter": "customer_count",  # count
            "confidence": "derived",
            "original_range": {"low_pct": -30, "high_pct": 30},
            "effective_range": {"low_pct": -30, "high_pct": 30},
            "range_widened": False,
            "base_value": 185000,
            "low": {"value": 129500, "tam": 466200000, "sam": 163170000, "som": 6526800},
            "base": {"tam": 666000000, "sam": 233100000, "som": 9324000},
            "high": {"value": 240500, "tam": 865800000, "sam": 303030000, "som": 12121200},
        },
        {
            "parameter": "serviceable_pct",  # percent
            "confidence": "derived",
            "original_range": {"low_pct": -30, "high_pct": 30},
            "effective_range": {"low_pct": -30, "high_pct": 30},
            "range_widened": False,
            "base_value": 35,
            "low": {"value": 24.5, "tam": 666000000, "sam": 163170000, "som": 6526800},
            "base": {"tam": 666000000, "sam": 233100000, "som": 9324000},
            "high": {"value": 45.5, "tam": 666000000, "sam": 303030000, "som": 12121200},
        },
    ],
    "sensitivity_ranking": [{"parameter": "serviceable_pct", "som_swing_pct": 60.0}],
    "most_sensitive": "serviceable_pct",
}


def _sens_row(sens_section: str, label: str) -> str:
    """Return the rendered table row whose first cell is `label`."""
    for line in sens_section.splitlines():
        if line.strip().startswith(f"| {label} |"):
            return line
    raise AssertionError(f"row for {label!r} not found in:\n{sens_section}")


def test_compose_sensitivity_value_columns_are_unit_aware() -> None:
    """Low/Base/High Value cells format by parameter unit (currency / count / percent),
    and the Base cell uses the SAME unit as Low/High (no raw-number inconsistency)."""
    d = _make_artifact_dir(_make_all_artifacts(**{"sensitivity.json": _VALID_SENSITIVITY_MIXED_UNITS}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    sens_section = md.split("## Sensitivity Analysis")[1].split("##")[0]

    # Currency param: all three Value cells are abbreviated USD (incl. Base — the bug was Base raw).
    currency = _sens_row(sens_section, "Industry Total")
    assert "| $2.2B | $2.8B | $3.4B |" in currency, currency

    # Count param: all three are grouped integers, NO dollar sign anywhere in the Value trio.
    count = _sens_row(sens_section, "Customer Count")
    assert "| 129,500 | 185,000 | 240,500 |" in count, count
    # The buggy version rendered counts as USD ($129.5K / $240.5K); guard against regression.
    assert "$129" not in count and "$240" not in count, count

    # Percent param: all three end with %, none rendered as dollars.
    pct = _sens_row(sens_section, "Serviceable %")
    assert "| 24.5% | 35% | 45.5% |" in pct, pct
    assert "$24" not in pct and "$45" not in pct, pct


def test_compose_analysis_checklist_shows_failed_labels() -> None:
    """When checklist has failed items, they appear labeled below the count line."""
    checklist_with_fails = {
        "items": [
            {"id": cid, "category": "Test", "label": "Test", "status": "pass", "notes": None} for cid in _CHECKLIST_IDS
        ],
        "summary": {
            "total": 22,
            "pass": 20,
            "fail": 2,
            "not_applicable": 0,
            "overall_status": "pass",
            "failed_items": [
                {
                    "id": "tam_matches_product_scope",
                    "category": "TAM Scoping",
                    "label": "TAM matches product scope",
                    "notes": "TAM appears 10x too large",
                },
                {
                    "id": "som_share_defensible",
                    "category": "SOM Realism",
                    "label": "SOM share is defensible",
                    "notes": "No GTM justification",
                },
            ],
        },
    }
    d = _make_artifact_dir(_make_all_artifacts(**{"checklist.json": checklist_with_fails}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    checklist_section = md.split("## Analysis Checklist")[1].split("##")[0]
    assert "TAM matches product scope" in checklist_section
    assert "TAM appears 10x too large" in checklist_section
    assert "SOM share is defensible" in checklist_section


def test_compose_analysis_checklist_appendix_table_present() -> None:
    """Analysis checklist section includes a 22-row appendix table."""
    d = _make_artifact_dir(_make_all_artifacts(**{"checklist.json": _VALID_CHECKLIST}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Appendix header must exist
    assert "### Appendix: Full Self-Check" in md
    # Extract only the appendix table (between ### Appendix: Full Self-Check and the next section)
    appendix_section = md.split("### Appendix: Full Self-Check")[1].split("##")[0]
    # Count table rows (pipe-separated, excluding header and separator)
    table_rows = [
        line
        for line in appendix_section.splitlines()
        if line.startswith("| ") and not line.startswith("| #") and "---" not in line
    ]
    assert len(table_rows) == 22, f"expected 22 appendix rows, got {len(table_rows)}"


# === Doc/contract tests: SKILL.md / agents/market-sizing.md conventions ===
#
# These guard against the agent inventing non-canonical values or misreading
# input conventions because a step's inline example didn't spell out the
# canonical enum/unit. Grep-based rather than behavioral because the content
# under test is a prose instruction consumed by an LLM, not executable code.


def test_skill_md_topdown_template_states_percentage_points_convention() -> None:
    """The TOP_DOWN_METHODOLOGY dispatch template must state that segment_pct/share_pct
    are percentage POINTS (35 means 35%), not fractions — a fractional input (0.35) was
    silently accepted and computed ~100x low before the market_sizing.py plausibility
    warning existed, and the dispatch template is the agent's only spec for the field."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    # Isolate the TOP_DOWN_METHODOLOGY dispatch prompt template block
    start = skill_md.index("Full dispatch prompt template (TOP_DOWN_METHODOLOGY)")
    end = skill_md.index("Full dispatch prompt template (BOTTOM_UP_METHODOLOGY)")
    block = skill_md[start:end]
    assert "segment_pct" in block and "share_pct" in block
    assert "points" in block.lower(), "expected the percentage-POINTS convention spelled out inline"
    assert "0.35" in block or "not 0.35" in block.lower() or "not a fraction" in block.lower()


def test_skill_md_bottomup_template_states_percentage_points_convention() -> None:
    """Same convention must be inlined in the BOTTOM_UP_METHODOLOGY template
    (serviceable_pct/target_pct)."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("Full dispatch prompt template (BOTTOM_UP_METHODOLOGY)")
    end = skill_md.index("After both sub-agents return")
    block = skill_md[start:end]
    assert "serviceable_pct" in block and "target_pct" in block
    assert "points" in block.lower()


def test_agent_md_topdown_schema_states_percentage_points_convention() -> None:
    """agents/market-sizing.md's TOP_DOWN_METHODOLOGY subtype schema must inline the same
    percentage-points convention (this is the sub-agent's own copy of the contract)."""
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    start = agent_md.index("TOP_DOWN_METHODOLOGY subtype")
    end = agent_md.index("BOTTOM_UP_METHODOLOGY subtype")
    block = agent_md[start:end]
    assert "points" in block.lower()


def test_agent_md_bottomup_schema_states_percentage_points_convention() -> None:
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    start = agent_md.index("BOTTOM_UP_METHODOLOGY subtype")
    end = agent_md.index("SENSITIVITY_TEST subtype")
    block = agent_md[start:end]
    assert "points" in block.lower()


def test_skill_md_step1_lists_full_stage_enum() -> None:
    """Step 1's founder_context.py init example must inline the full --stage enum so the
    agent doesn't guess a token (e.g. 'seriesa') and hit an argparse error/retry."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Steps 2-3")
    block = skill_md[start:end]
    for stage in ("pre-seed", "seed", "series-a", "series-b", "series-c", "series-d", "later"):
        assert stage in block, f"--stage enum value '{stage}' not inlined in Step 1"


def test_skill_md_step1_carveout_is_non_binary() -> None:
    """Step 1's deck/materials carve-out must derive the four basics field-by-field,
    NOT all-or-nothing: deriving three and missing one must not re-gate all four. A
    missing-but-implied field should be inferred from a clear signal (geography from a
    phone country code, stage from a fundraise signal, etc.) rather than gated, and
    AskUserQuestion reserved for only the genuinely underivable field(s). This is the
    market-sizing copy of the same X-5 carve-out fixed in competitive-positioning."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Steps 2-3")
    block = skill_md[start:end].lower()
    assert any(phrase in block for phrase in ("field-by-field", "independently", "never all-or-nothing")), (
        "Step 1 carve-out must state the four basics are derived independently (non-binary)"
    )
    assert "only those" in block or "only the missing" in block or "only for" in block, (
        "Step 1 carve-out must instruct asking AskUserQuestion for only the underivable field(s)"
    )
    assert "infer" in block, "Step 1 carve-out must describe inferring a missing field from a signal"
    assert "+972" in block or "phone country code" in block or "fundraise signal" in block, (
        "Step 1 carve-out must give a concrete inference signal (e.g. phone country code, fundraise signal)"
    )


def test_skill_md_heredoc_rationale_present() -> None:
    """The heredoc examples use single-quoted delimiters (<<'INPUTS_EOF'); the SKILL.md
    must EXPLAIN why (a `$`-bearing value like `$8M` shell-expands away under an unquoted
    delimiter), so a paraphrasing agent doesn't drop the quoting and silently lose a
    dollar figure. Mirrors ic-sim's heredoc guardrail."""
    text = _read(MARKET_SIZING_SKILL_MD).lower()
    assert "shell-expand" in text or "shell expand" in text, (
        "market-sizing SKILL.md must explain the single-quoted-heredoc rationale (shell expansion)"
    )
    assert "single-quot" in text or "<<'" in _read(MARKET_SIZING_SKILL_MD), (
        "the rationale must reference quoting the heredoc delimiter"
    )


def test_skill_md_step1_lists_sector_type_enum() -> None:
    """Step 1 must also mention --sector-type and its enum so the agent knows the override
    exists before hitting the runtime 'set explicitly with --sector-type' warning."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Steps 2-3")
    block = skill_md[start:end]
    assert "--sector-type" in block
    for sector_type in ("saas", "ai-native", "marketplace", "hardware", "hardware-subscription"):
        assert sector_type in block, f"--sector-type enum value '{sector_type}' not inlined in Step 1"


def test_skill_md_step4_lists_figure_validations_enum() -> None:
    """Step 4's validation.json example must inline the full 4-value figure_validations status
    enum (validated/partially_supported/unsupported/refuted) — the hostloop run showed the
    agent inventing non-canonical statuses (validated_with_caveat/unverified) when only one
    example status was shown, tripping OVERCLAIMED_VALIDATION until relabeled."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 4: External Validation")
    end = skill_md.index("### Context A hand-off protocol")
    block = skill_md[start:end]
    for status in ("validated", "partially_supported", "unsupported", "refuted"):
        assert status in block, f"figure_validations status '{status}' not inlined in Step 4"


def test_skill_md_reconciliation_covers_sam_som_not_just_tam() -> None:
    """The Step 5 reconciliation guidance must explicitly extend the >30% discrepancy check to
    SAM/SOM, not just TAM — an evaluator found a ~10x top-down-vs-bottom-up SAM gap presented as
    equally defensible because only TAM discrepancy was called out in the prose. Must not be the
    old TAM-only sentence ('a >30% TAM discrepancy means investigating...')."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 5: Calculate TAM/SAM/SOM")
    end = skill_md.index("### Steps 6a & 6b")
    block = skill_md[start:end]
    assert (
        "TAM/SAM/SOM discrepancy" in block
        or "TAM, SAM, or SOM discrepancy" in block
        or ("SAM discrepancy" in block and "SOM discrepancy" in block)
    ), f"expected the >30% discrepancy check extended to SAM/SOM by name, got: {block}"


def test_skill_md_documents_competitive_landscape_input_field() -> None:
    """CHECKLIST scores competitive_landscape_acknowledged but only reads inputs/methodology/
    validation/sizing.json — never the deck. SKILL.md must document that deck competitive
    content gets carried into a dedicated inputs.json field the CHECKLIST sub-agent can see.
    Uses a distinct field name (not a substring of the existing 'competitive_landscape_acknowledged'
    checklist ID) so this assertion can't pass on pre-existing checklist-ID text."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    assert "competitive_landscape_notes" in skill_md


def test_skill_md_documents_late_edit_recompose_rule() -> None:
    """A late inputs.json edit (e.g. adding competitor data found after the initial pass) must
    require re-dispatching the affected steps + recompose — otherwise checklist.json/report.md
    go stale relative to the edited inputs.json (the exact staleness the hostloop run hit).
    Matches a distinctive phrase, not generic pre-existing 'redo-dispatch'/'repair-dispatch'
    retry-budget prose which is about a different mechanism (gate failures, not stale artifacts)."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    lower = skill_md.lower()
    assert "late edit" in lower and "inputs.json" in skill_md
    assert "recompose" in lower


def test_artifact_schemas_documents_competitive_landscape_field() -> None:
    """The inputs.json schema reference must document the new field (distinct name — see above)."""
    schemas_md = _read(MARKET_SIZING_ARTIFACT_SCHEMAS_MD)
    assert "competitive_landscape_notes" in schemas_md


def test_skill_md_topdown_template_states_funnel_narrowing_semantics() -> None:
    """segment_pct narrows TAM->SAM and share_pct narrows SAM->SOM — an agent inverted this
    (applied share_pct at TAM->SAM) producing a $1B SOM that forced a corrective re-dispatch.
    The authoritative narrowing order lives only in market_sizing.py; inline it in the template."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("Full dispatch prompt template (TOP_DOWN_METHODOLOGY)")
    end = skill_md.index("Full dispatch prompt template (BOTTOM_UP_METHODOLOGY)")
    block = skill_md[start:end].lower()
    assert "segment_pct narrows tam" in block or "segment_pct narrows tam to sam" in block
    assert "share_pct narrows sam" in block or "share_pct narrows sam to som" in block


def test_agent_md_states_funnel_narrowing_semantics() -> None:
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    start = agent_md.index("TOP_DOWN_METHODOLOGY subtype")
    end = agent_md.index("BOTTOM_UP_METHODOLOGY subtype")
    block = agent_md[start:end].lower()
    assert "segment_pct narrows tam" in block
    assert "share_pct narrows sam" in block


def test_compose_checklist_headline_shows_percent_not_bare_fraction() -> None:
    """The Analysis Checklist section headline must render as '<score>% (<pass>/<applicable>
    pass, ...)' — a bare 'pass/total' rendering (e.g. '100/22') reads as a malformed fraction,
    not 100% across 22 items. Previously the section didn't surface score_pct at all."""
    checklist_with_score: dict[str, Any] = dict(_VALID_CHECKLIST)
    summary_with_score: dict[str, Any] = dict(_VALID_CHECKLIST["summary"])  # type: ignore[arg-type]
    summary_with_score["score_pct"] = 100.0
    checklist_with_score["summary"] = summary_with_score
    d = _make_artifact_dir(_make_all_artifacts(**{"checklist.json": checklist_with_score}))
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "100% (22/22 pass" in md, f"expected a clear percent+fraction headline, report had: {md[:2000]}"


# ============================================================
# R2 coaching-transport fix: raw-markdown Context-B pipe
# ============================================================


def test_skill_md_coaching_pipe_uses_format_markdown_adapter() -> None:
    """R2 coaching-transport fix: Step 8's Context-B pipe must gate the raw
    .md hand-off with check_handoff.py --format=markdown and transform it
    through the shared md_to_commentary.py adapter before insert_coaching.py
    — never hand the sub-agent a JSON-escaping burden."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 8: Post-Compose Coaching Commentary")
    end = skill_md.index("### Step 9") if "### Step 9" in skill_md else len(skill_md)
    step8 = skill_md[start:end]
    assert "--format=markdown" in step8
    assert "md_to_commentary.py" in step8
    assert "OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md" in step8
    assert "coaching_commentary_output.json" not in step8


def test_skill_md_coaching_exit7_repair_dispatch() -> None:
    """The content-shape gate's new exit 7 (shape-invalid: receipt-shaped or
    marker-bearing hand-off) must branch to a repair-dispatch, mirroring the
    other typed exits."""
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    start = skill_md.index("### Step 8: Post-Compose Coaching Commentary")
    end = skill_md.index("### Step 9") if "### Step 9" in skill_md else len(skill_md)
    step8 = skill_md[start:end]
    assert "Exit 7" in step8
    assert "repair-dispatch" in step8.lower()
    idx = step8.index("Exit 7")
    window = step8[idx : idx + 300].lower()
    assert "coaching commentary" in window or "coaching markdown" in window


def test_agent_coaching_writes_raw_markdown_no_json_escaping() -> None:
    """R2 coaching-transport fix: agents/market-sizing.md's Context B section
    must instruct the sub-agent to write RAW markdown (no JSON envelope, no
    hand-escaping) — the escaping moves into md_to_commentary.py's
    json.dumps, which cannot emit malformed JSON."""
    agent_body = _read(MARKET_SIZING_AGENT_MD)
    idx = agent_body.index("### Context B")
    section = agent_body[idx : idx + 6000]
    assert "plain markdown" in section.lower()
    assert "do not escape anything" in section.lower() or "do not escape" in section.lower()
    assert "escaped as `\\n`" not in agent_body
    assert 'escaped as `\\"`' not in agent_body
    assert "no pretty-print" not in agent_body.lower()


# ---------------------------------------------------------------------------
# Currency labelling + founder value fidelity
#
# A wrong UNIT on a headline TAM is not a cosmetic defect: the founder carries
# it into a deck, where no downstream reviewer can tell it is wrong. And a
# researched figure silently replacing a founder-stated one makes the report's
# arithmetic look broken to the one person who knows the real number.
# ---------------------------------------------------------------------------


def _sizing_with(customer_count: float, currency: str | None = None) -> dict[str, Any]:
    """Bottom-up sizing artifact whose math consumed `customer_count`."""
    sizing: dict[str, Any] = {
        "approach": "bottom_up",
        "bottom_up": {
            "tam": {
                "value": customer_count * 15000,
                "formula": "customer_count * arpu",
                "inputs": {"customer_count": customer_count, "arpu": 15000},
            },
            "sam": {
                "value": customer_count * 15000 * 0.35,
                "formula": "serviceable_customers * arpu",
                "inputs": {"serviceable_pct": 35, "arpu": 15000},
            },
            "som": {
                "value": customer_count * 15000 * 0.35 * 0.02,
                "formula": "target_customers * arpu",
                "inputs": {"target_pct": 2, "arpu": 15000},
            },
        },
        "validation": {"status": "valid", "errors": [], "warnings": []},
    }
    if currency is not None:
        sizing["currency"] = currency
    return sizing


def _codes(result: dict | None) -> list[str]:
    assert result is not None
    return [w["code"] for w in result["validation"]["warnings"]]


def test_non_usd_currency_labels_money_figures_and_never_bare_dollar() -> None:
    """A EUR analysis must not render a single money figure with a bare "$"."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "currency": "EUR"},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(18000, "EUR"),
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert result is not None
    md = result["report_markdown"]
    assert "270.0M EUR" in md, "TAM must carry the EUR label"
    # No "$" immediately followed by a digit anywhere in the report.
    assert not re.search(r"\$\d", md), f"bare dollar figure in a EUR report: {md[:400]}"
    # And the no-FX limitation must be stated, not merely implied by the label.
    assert "no FX conversion is applied" in md.lower() or "no fx conversion" in md.lower()


def test_usd_analysis_keeps_dollar_prefix_and_no_currency_notice() -> None:
    """Back-compat: absent/USD currency renders "$" and adds no FX disclosure."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(18000),
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert result is not None
    md = result["report_markdown"]
    assert "$270.0M" in md
    assert "no FX conversion" not in md


def test_currency_mismatch_between_inputs_and_sizing_is_reported() -> None:
    """Disagreeing currencies mean one figure is mislabelled — say so, don't pick."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "currency": "EUR"},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(18000, "USD"),
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert "CURRENCY_MISMATCH" in _codes(result)


def test_founder_stated_value_substituted_is_reported() -> None:
    """The live failure: founder said 18,000; the math used a researched 16,601."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "founder_stated_inputs": {"customer_count": 18000}},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(16601),
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert result is not None
    assert "FOUNDER_VALUE_OVERRIDDEN" in _codes(result)
    msg = next(w["message"] for w in result["validation"]["warnings"] if w["code"] == "FOUNDER_VALUE_OVERRIDDEN")
    assert "18,000" in msg and "16,601" in msg, "must name BOTH figures so the founder can adjudicate"


def test_founder_stated_value_honoured_is_not_reported() -> None:
    """No false positive when the math used exactly what the founder stated."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "founder_stated_inputs": {"customer_count": 18000, "arpu": 15000}},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(18000),
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert "FOUNDER_VALUE_OVERRIDDEN" not in _codes(result)


def test_founder_value_tolerance_allows_unit_normalization() -> None:
    """18000 vs 18000.0 (or a 0.1% rounding) is normalization, not substitution."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "founder_stated_inputs": {"customer_count": 18000}},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _sizing_with(18010),  # 0.06% off
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0
    assert "FOUNDER_VALUE_OVERRIDDEN" not in _codes(result)


def test_founder_value_check_is_opt_in_on_empty_object() -> None:
    """Absent/empty founder_stated_inputs disables the check rather than failing."""
    stated: dict[str, Any] | None
    for stated in ({}, None):
        inputs: dict[str, Any] = {**_VALID_INPUTS}
        if stated is not None:
            inputs["founder_stated_inputs"] = stated
        d = _make_artifact_dir(
            {
                "inputs.json": inputs,
                "methodology.json": _VALID_METHODOLOGY,
                "validation.json": _VALID_VALIDATION,
                "sizing.json": _sizing_with(16601),
            }
        )
        code, result, _ = _run_compose(d)
        assert code == 0
        assert "FOUNDER_VALUE_OVERRIDDEN" not in _codes(result)


def test_producer_honours_currency_from_stdin_and_flag_wins() -> None:
    """market_sizing.py: stdin `currency` is honoured; an explicit flag outranks it."""
    payload = {
        "approach": "bottom_up",
        "customer_count": 100,
        "arpu": 100,
        "serviceable_pct": 50,
        "target_pct": 10,
        "currency": "eur",
    }
    code, result, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert code == 0 and result is not None
    assert result["currency"] == "EUR", "lowercase stdin currency must normalize to ISO upper"

    code, result, _ = run_script("market_sizing.py", ["--stdin", "--currency", "ILS"], stdin_data=json.dumps(payload))
    assert code == 0 and result is not None
    assert result["currency"] == "ILS", "explicit --currency must outrank the stdin value"

    del payload["currency"]
    code, result, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert code == 0 and result is not None
    assert result["currency"] == "USD", "absent currency must still default to USD"


# ---------------------------------------------------------------------------
# Regression: agent-body sensitivity confidence wording must match SKILL.md
# and sensitivity.py's CONFIDENCE_MIN_RANGE (sourced == no auto-widen).
# ---------------------------------------------------------------------------


def test_agent_md_sensitivity_sourced_no_fabricated_default_range() -> None:
    """The agent body's SENSITIVITY_TEST subtype previously told the sub-agent to
    fabricate a +/-20% range on a 'sourced' figure absent a researcher-provided
    range. SKILL.md and sensitivity.py's CONFIDENCE_MIN_RANGE (0 for 'sourced')
    both say the range must NEVER be widened or invented for a sourced figure —
    the agent body is the copy resident in context on every dispatch, so a
    contradiction there is the one likely to win in practice. Must now match."""
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    assert "do not invent one" in agent_md
    assert "whatever the source states" in agent_md
    assert "20% default" not in agent_md, "the old fabricated-default wording must be gone"


# ---------------------------------------------------------------------------
# sizing_basis: current-year vs. forecast-year convention (declared, carried
# through market_sizing.py into sizing.json, rendered but never defaulted).
# ---------------------------------------------------------------------------

MARKET_SIZING_METHODOLOGY_MD = os.path.join(
    FOUNDER_SKILLS_DIR, "skills", "market-sizing", "references", "tam-sam-som-methodology.md"
)
MARKET_SIZING_PITFALLS_MD = os.path.join(
    FOUNDER_SKILLS_DIR, "skills", "market-sizing", "references", "pitfalls-checklist.md"
)


def test_tam_sam_som_methodology_declares_sizing_basis() -> None:
    """The methodology reference must define the sizing_basis convention — the
    industry commonly quotes both a current-year and a forecast-year figure for
    the same market, and nothing said which one this analysis used."""
    ref = _read(MARKET_SIZING_METHODOLOGY_MD)
    assert "sizing_basis" in ref
    assert "current_year" in ref
    assert "forecast_year" in ref
    assert "mixed" in ref


def test_market_sizing_sizing_basis_passthrough_and_never_defaulted() -> None:
    """market_sizing.py must pass a declared sizing_basis through to sizing.json,
    and must NEVER fabricate one when the run never declared it — an absent
    sizing_basis key downstream is what lets compose_report.py/visualize.py
    render "Not declared" instead of asserting a convention that wasn't in force."""
    payload: dict[str, Any] = {
        "approach": "bottom_up",
        "customer_count": 100,
        "arpu": 100,
        "serviceable_pct": 50,
        "target_pct": 10,
        "sizing_basis": "forecast_year",
    }
    code, result, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert code == 0 and result is not None
    assert result["sizing_basis"] == "forecast_year"

    del payload["sizing_basis"]
    code, result, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert code == 0 and result is not None
    assert "sizing_basis" not in result, "an undeclared basis must never be defaulted into the artifact"


def test_market_sizing_sizing_basis_flag_wins_over_stdin() -> None:
    """Mirrors the existing --currency-vs-stdin precedent."""
    payload = {
        "approach": "bottom_up",
        "customer_count": 100,
        "arpu": 100,
        "serviceable_pct": 50,
        "target_pct": 10,
        "sizing_basis": "current_year",
    }
    code, result, _ = run_script(
        "market_sizing.py", ["--stdin", "--sizing-basis", "forecast_year"], stdin_data=json.dumps(payload)
    )
    assert code == 0 and result is not None
    assert result["sizing_basis"] == "forecast_year", "explicit --sizing-basis must outrank the stdin value"


def test_market_sizing_sizing_basis_invalid_value_rejected() -> None:
    payload = {
        "approach": "bottom_up",
        "customer_count": 100,
        "arpu": 100,
        "serviceable_pct": 50,
        "target_pct": 10,
        "sizing_basis": "next_quarter",
    }
    code, result, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert (
        code == 1 and result is not None
    )  # rejected input now exits 1 (loud refusal); the diagnostic still lands on stdout
    assert result["validation"]["status"] == "invalid"
    assert any("sizing_basis" in e for e in result["validation"]["errors"])


def test_compose_renders_sizing_basis_not_declared_when_absent() -> None:
    """A run that never declared sizing_basis must render 'Not declared' — never
    a silent default to current_year, which would assert a convention that was
    never actually in force for the run."""
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    md = result["report_markdown"]
    assert "Sizing basis" in md
    assert "Not declared" in md
    assert "Current-year" not in md and "current_year" not in md


def test_compose_renders_declared_sizing_basis_from_sizing_json() -> None:
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": {**_VALID_SIZING, "sizing_basis": "forecast_year"},
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    assert "Forecast-year" in result["report_markdown"]


def test_compose_sizing_basis_falls_back_to_inputs_when_sizing_lacks_it() -> None:
    """sizing.json is authoritative when present; inputs.json is the fallback —
    matching the resolution order documented for the analogous scoring_basis
    field in the competitive-positioning skill."""
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "sizing_basis": "mixed"},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    assert "Mixed" in result["report_markdown"]


def test_visualize_renders_sizing_basis() -> None:
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": {**_VALID_SIZING, "sizing_basis": "current_year"},
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, stdout, stderr = run_script_raw("visualize.py", ["--dir", d])
    assert rc == 0, stderr
    assert "Sizing basis" in stdout
    assert "Current-year" in stdout


def test_skill_md_documents_sizing_basis() -> None:
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    assert "sizing_basis" in skill_md
    assert "--sizing-basis" in skill_md


def test_agent_md_documents_sizing_basis() -> None:
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    assert "SIZING_BASIS" in agent_md


def test_artifact_schemas_documents_sizing_basis() -> None:
    schemas_md = _read(MARKET_SIZING_ARTIFACT_SCHEMAS_MD)
    assert "sizing_basis" in schemas_md


# ---------------------------------------------------------------------------
# CHECKLIST evidentiary channels for som_backed_by_gtm and
# som_consistent_with_projections (deck-blind sub-agent, same problem as the
# existing competitive_landscape_notes precedent — two DIFFERENT fields
# because the two items need two different kinds of evidence).
# ---------------------------------------------------------------------------


def test_pitfalls_checklist_documents_gtm_and_projections_evidence_fields() -> None:
    ref = _read(MARKET_SIZING_PITFALLS_MD)
    assert "gtm_evidence_notes" in ref
    assert "projections_alignment_notes" in ref


def test_skill_md_checklist_dispatch_documents_gtm_and_projections_fields() -> None:
    skill_md = _read(MARKET_SIZING_SKILL_MD)
    assert "gtm_evidence_notes" in skill_md
    assert "projections_alignment_notes" in skill_md


def test_agent_md_checklist_reads_gtm_and_projections_fields() -> None:
    agent_md = _read(MARKET_SIZING_AGENT_MD)
    assert "gtm_evidence_notes" in agent_md
    assert "projections_alignment_notes" in agent_md


def test_artifact_schemas_documents_gtm_and_projections_fields() -> None:
    schemas_md = _read(MARKET_SIZING_ARTIFACT_SCHEMAS_MD)
    assert "gtm_evidence_notes" in schemas_md
    assert "projections_alignment_notes" in schemas_md


# ---------------------------------------------------------------------------
# Source strength and per-assumption attribution
#
# The sub-agent is asked to judge each source's tier and segment match, and to attribute each
# assumption to a source. All four fields were collected and none reached the report, leaving the
# founder unable to weigh a figure they are being asked to defend.
# ---------------------------------------------------------------------------


def test_compose_renders_source_quality_tier_and_segment_match() -> None:
    validation = json.loads(json.dumps(_VALID_VALIDATION))
    validation["sources"][0]["quality_tier"] = "analyst_firm"
    validation["sources"][0]["segment_match"] = "adjacent"
    arts = dict(_all_artifacts())
    arts["validation.json"] = validation
    d = _make_artifact_dir(arts)
    rc, data, stderr = _run_compose(d)
    assert rc == 0, stderr
    assert data is not None
    md = data["report_markdown"]
    assert "Analyst Firm" in md, "source quality tier did not reach the report"
    assert "Adjacent segment match" in md, "segment match did not reach the report"
    assert "analyst_firm" not in md, "the raw token leaked instead of being humanized"


def test_compose_renders_assumption_source_attribution() -> None:
    validation = json.loads(json.dumps(_VALID_VALIDATION))
    validation["assumptions"][0]["source_title"] = "Census SMB Table"
    validation["assumptions"][0]["source_url"] = "https://example.com/census"
    arts = dict(_all_artifacts())
    arts["validation.json"] = validation
    d = _make_artifact_dir(arts)
    rc, data, stderr = _run_compose(d)
    assert rc == 0, stderr
    assert data is not None
    md = data["report_markdown"]
    assert "[Census SMB Table](https://example.com/census)" in md, (
        "a sourced assumption's attribution did not reach the report — 'Sourced' without the source is "
        "a claim the founder cannot check"
    )


def test_compose_omits_source_strength_when_absent() -> None:
    """Absent fields must not render empty parentheses or stray separators."""
    d = _make_artifact_dir(_all_artifacts())
    rc, data, stderr = _run_compose(d)
    assert rc == 0, stderr
    assert data is not None
    assert ", )" not in data["report_markdown"]
    assert " — [" not in data["report_markdown"].split("## Sources Used")[0]


# ---------------------------------------------------------------------------
# Producer-side FX + the loud-refusal contract it depends on.
#
# Two defects motivated this block, and the first one is the reason the second is
# even reachable:
#
#   1. market_sizing.py used to exit 0 on a validation error, print an
#      `{"ok":true}` receipt, and write a figure-less stub over the canonical
#      sizing.json. SKILL.md's producer-error branch is written as "the pipe
#      fails next", so it could never fire, and compose rendered an empty sizing
#      table with no code naming the cause.
#   2. The dispatch prompts told a NETWORK-LESS sub-agent to convert currencies
#      with no rate supplied — i.e. from memory. FX now lives here, where a
#      missing rate is a refusal rather than a guess.
#
# The refusal is the only non-prose guarantee in the design, so several of these
# assert the EXIT CODE, not just the status string.
# ---------------------------------------------------------------------------


def _fx_stdin(**over: object) -> str:
    base: dict[str, object] = {
        "approach": "top_down",
        "industry_total": 5_200_000_000,
        "segment_pct": 12,
        "share_pct": 3,
        "currency": "ILS",
    }
    base.update(over)
    return json.dumps(base)


def test_fx_invalid_input_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    """A rejected run must FAIL LOUDLY and leave the canonical artifact alone.

    Both halves are load-bearing. Exit 1 is what makes SKILL.md's "the pipe fails"
    branch reachable at all; not writing `-o` is what stops a figure-less stub
    replacing a good sizing.json, which compose would then read as truth.
    """
    out = tmp_path / "sizing.json"
    out.write_text('{"sentinel": true}')
    rc, data, stderr = run_script(
        "market_sizing.py",
        ["--stdin", "-o", str(out)],
        stdin_data=_fx_stdin(industry_total=-5),
    )
    assert rc == 1, "a validation error must exit non-zero, or the caller cannot detect it"
    assert stderr.strip(), "a rejected run must say so on stderr"
    _assert_validation_errors(data, "industry_total must be positive")
    assert json.loads(out.read_text()) == {"sentinel": True}, "the canonical artifact was clobbered"


def test_fx_absent_tag_is_byte_identical_passthrough() -> None:
    """No `<field>_currency` anywhere => no conversion, no `fx` key.

    This is the backwards-compatibility pin: every pre-existing caller supplies no
    tag, so the whole feature must be inert for them.
    """
    rc, data, err = run_script("market_sizing.py", ["--stdin"], stdin_data=_fx_stdin())
    assert rc == 0, err
    assert data is not None
    assert "fx" not in data
    assert data["top_down"]["tam"]["inputs"]["industry_total"] == 5_200_000_000


def test_fx_tag_equal_to_analysis_currency_does_not_convert() -> None:
    """Tagging a field with the analysis currency is a no-op, not a 1.0 conversion."""
    rc, data, err = run_script("market_sizing.py", ["--stdin"], stdin_data=_fx_stdin(industry_total_currency="ILS"))
    assert rc == 0, err
    assert data is not None and "fx" not in data


def test_fx_conversion_applied_and_recorded() -> None:
    """A supplied rate converts the figure and records the full provenance."""
    rc, data, err = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(
            industry_total_currency="USD",
            fx={"rates": {"USD:ILS": 3.72}, "as_of": "2026-08-01", "source": "https://example"},
        ),
    )
    assert rc == 0, err
    assert data is not None
    conv = data["fx"]["conversions"]
    assert len(conv) == 1
    assert conv[0] == {
        "field": "industry_total",
        "from": "USD",
        "to": "ILS",
        "rate": 3.72,
        "original_value": 5_200_000_000.0,
        "converted_value": 19_344_000_000.0,
    }
    assert data["fx"]["as_of"] == "2026-08-01"
    assert data["validation"]["status"] == "valid"


def test_fx_recorded_value_is_the_value_the_math_consumed() -> None:
    """`converted_value` must BE the number the sizing used, not a rounded echo of it.

    compose_report.py compares founder-stated figures through this record; if it
    drifted from the value the math consumed, that comparison would be against a
    number that never existed.
    """
    rc, data, err = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(
            industry_total=1_234_567_891,
            industry_total_currency="USD",
            fx={"rates": {"USD:ILS": 3.7213}, "as_of": "d", "source": "s"},
        ),
    )
    assert rc == 0, err
    assert data is not None
    assert data["fx"]["conversions"][0]["converted_value"] == data["top_down"]["tam"]["inputs"]["industry_total"]


def test_fx_missing_rate_is_a_refusal_not_a_guess() -> None:
    """The central safety property: no rate => stop, with an actionable remedy."""
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=_fx_stdin(industry_total_currency="USD"))
    assert rc == 1, "a conversion with no supplied rate must exit non-zero"
    _assert_validation_errors(data, "E_FX_RATE_MISSING", "USD:ILS", "--fx-rate")


def test_fx_inverse_pair_is_never_inferred() -> None:
    """Supplying ILS:USD does NOT license converting USD->ILS by inversion.

    Silent inversion is a bug class ("which direction did they mean?"), so the
    pair must match exactly.
    """
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(industry_total_currency="USD", fx={"rates": {"ILS:USD": 0.27}}),
    )
    assert rc == 1
    _assert_validation_errors(data, "E_FX_RATE_MISSING")


@pytest.mark.parametrize("bad", [0, -3.72, "abc", True, None, [3.72]])
def test_fx_rate_must_be_a_positive_finite_number(bad: object) -> None:
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(industry_total_currency="USD", fx={"rates": {"USD:ILS": bad}}),
    )
    assert rc == 1
    _assert_validation_errors(data, "E_FX_RATE_INVALID")


def test_fx_rate_infinity_is_rejected() -> None:
    """`Infinity` parses through json.load and passes `> 0` — isfinite is required."""
    payload = (
        '{"approach":"top_down","industry_total":5.2e9,"segment_pct":12,"share_pct":3,'
        '"currency":"ILS","industry_total_currency":"USD","fx":{"rates":{"USD:ILS":Infinity}}}'
    )
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc == 1
    _assert_validation_errors(data, "E_FX_RATE_INVALID")


@pytest.mark.parametrize("bad", ["dollars", "US", "usd1", 12, ""])
def test_fx_field_currency_must_be_an_iso_code(bad: object) -> None:
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=_fx_stdin(industry_total_currency=bad))
    assert rc == 1
    _assert_validation_errors(data, "E_FX_CURRENCY_INVALID")


def test_fx_both_approach_converts_only_the_foreign_field() -> None:
    """`both` with ONE foreign field must convert exactly that one.

    An implementation that applies a single supplied rate to every money field
    passes the all-foreign and no-foreign cases and fails only here.
    """
    payload = json.dumps(
        {
            "approach": "both",
            "industry_total": 5_200_000_000,
            "segment_pct": 12,
            "share_pct": 3,
            "customer_count": 1000,
            "arpu": 100,
            "arpu_currency": "USD",
            "serviceable_pct": 35,
            "target_pct": 5,
            "currency": "ILS",
            "fx": {"rates": {"USD:ILS": 3.72}, "as_of": "d", "source": "s"},
        }
    )
    rc, data, err = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc == 0, err
    assert data is not None
    fields = [c["field"] for c in data["fx"]["conversions"]]
    assert fields == ["arpu"], f"only arpu was foreign, but converted: {fields}"
    assert data["top_down"]["tam"]["inputs"]["industry_total"] == 5_200_000_000
    assert data["bottom_up"]["tam"]["inputs"]["arpu"] == 372.0


def test_fx_unsourced_conversion_warns_but_stays_valid() -> None:
    """A rate with no date/source is a disclosure gap, not a fabrication risk."""
    rc, data, err = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(industry_total_currency="USD", fx={"rates": {"USD:ILS": 3.72}}),
    )
    assert rc == 0, err
    assert data is not None
    assert data["validation"]["status"] == "valid"
    assert "FX_UNSOURCED" in [w["code"] for w in data["validation"]["warnings"]]


def test_fx_flag_beats_stdin_rate() -> None:
    """--fx-rate wins over a stdin rate, matching --currency/--sizing-basis precedence."""
    rc, data, err = run_script(
        "market_sizing.py",
        ["--stdin", "--fx-rate", "USD:ILS=4.0", "--fx-as-of", "d", "--fx-source", "s"],
        stdin_data=_fx_stdin(
            industry_total_currency="USD", fx={"rates": {"USD:ILS": 3.72}, "as_of": "x", "source": "y"}
        ),
    )
    assert rc == 0, err
    assert data is not None
    assert data["fx"]["conversions"][0]["rate"] == 4.0


def test_fx_reachable_from_the_pure_cli_path() -> None:
    """FX must work without --stdin, or the flags are decoration."""
    rc, data, err = run_script(
        "market_sizing.py",
        [
            "--approach",
            "top-down",
            "--industry-total",
            "5200000000",
            "--segment-pct",
            "12",
            "--share-pct",
            "3",
            "--currency",
            "ILS",
            "--industry-total-currency",
            "USD",
            "--fx-rate",
            "USD:ILS=3.72",
            "--fx-as-of",
            "2026-08-01",
            "--fx-source",
            "https://example",
        ],
    )
    assert rc == 0, err
    assert data is not None
    assert data["fx"]["conversions"][0]["converted_value"] == 19_344_000_000.0


def test_fx_string_money_value_is_coerced_before_conversion() -> None:
    """Conversion runs on COERCED numbers, never on raw stdin.

    Converting before _validate_inputs would do `"5200000000" * 3.72` and raise
    TypeError; the stdin harness legitimately sends numbers as strings.
    """
    rc, data, err = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=_fx_stdin(
            industry_total="5200000000",
            industry_total_currency="USD",
            fx={"rates": {"USD:ILS": 3.72}, "as_of": "d", "source": "s"},
        ),
    )
    assert rc == 0, err
    assert data is not None
    assert data["fx"]["conversions"][0]["converted_value"] == 19_344_000_000.0


def test_fx_empty_currency_reports_the_real_error_not_a_missing_rate() -> None:
    """An unusable analysis currency must not be masked by an FX complaint.

    FX resolution runs before the currency is validated, so a naive version looks
    up the pair "USD:" and reports E_FX_RATE_MISSING instead of the actual fault.
    """
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin", "--currency", " "],
        stdin_data=_fx_stdin(industry_total_currency="USD"),
    )
    assert rc == 1
    _assert_validation_errors(data, "currency must be a non-empty string")


# --- compose-side: FX disclosure and the two comparison classes ---------------


def _fx_dir(tmp_path: Path, *, converted: bool, **inputs_over: object) -> Path:
    """A full sizing dir whose sizing.json is FX-converted (or not)."""
    d = tmp_path / "market-sizing-testco"
    d.mkdir()
    _make_full_sizing_dir(d)
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["currency"] = "ILS"
    inputs.update(inputs_over)
    (d / "inputs.json").write_text(json.dumps(inputs))
    sizing = json.loads((d / "sizing.json").read_text())
    sizing["currency"] = "ILS"
    if converted:
        used = _as_float(sizing["top_down"]["tam"]["inputs"]["industry_total"])
        sizing["fx"] = {
            "as_of": "2026-08-01",
            "source": "https://example",
            "conversions": [
                {
                    "field": "industry_total",
                    "from": "USD",
                    "to": "ILS",
                    "rate": 3.72,
                    "original_value": round(used / 3.72, 2),
                    "converted_value": used,
                }
            ],
        }
    (d / "sizing.json").write_text(json.dumps(sizing))
    return d


def _as_float(v: object) -> float:
    return float(v)  # type: ignore[arg-type]


def _compose_codes(d: Path) -> list[str]:
    rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
    assert data is not None, err
    return [w["code"] for w in data.get("validation", {}).get("warnings", [])]


def test_compose_discloses_the_rate_on_a_converted_run(tmp_path: Path) -> None:
    """A converted run must state the rate, its date and its source in the report.

    And must NOT keep claiming no FX happened — that sentence was unconditional.
    """
    d = _fx_dir(tmp_path, converted=True)
    md = d / "report.md"
    rc, _, err = run_script("compose_report.py", ["--dir", str(d), "--write-md", str(md)])
    assert rc == 0, err
    text = md.read_text()
    assert "no FX conversion is applied anywhere" not in text
    assert "1 USD = 3.72 ILS" in text
    assert "2026-08-01" in text


def test_compose_keeps_the_no_fx_notice_when_nothing_was_converted(tmp_path: Path) -> None:
    """The unconverted path is unchanged — this is the regression pin for the edit."""
    d = _fx_dir(tmp_path, converted=False)
    md = d / "report.md"
    rc, _, err = run_script("compose_report.py", ["--dir", str(d), "--write-md", str(md)])
    assert rc == 0, err
    assert "no FX conversion is applied anywhere" in md.read_text()


def test_compose_cannot_compare_undeclared_founder_currency(tmp_path: Path) -> None:
    """An undeclared comparand currency must yield an honest "cannot check".

    Comparing a founder figure against a converted one diverges by exactly the FX
    rate, so both FOUNDER_VALUE_OVERRIDDEN and DECK_CLAIM_MISMATCH would fire on a
    perfectly correct analysis.
    """
    d = _fx_dir(tmp_path, converted=True, founder_stated_inputs={"industry_total": 5_200_000_000})
    codes = _compose_codes(d)
    assert "COMPARISON_CURRENCY_UNKNOWN" in codes
    assert "FOUNDER_VALUE_OVERRIDDEN" not in codes


def test_compose_compares_properly_when_founder_currency_is_declared(tmp_path: Path) -> None:
    """Declaring the currency restores the real check — and it passes when faithful."""
    d = _fx_dir(tmp_path, converted=True)
    sizing = json.loads((d / "sizing.json").read_text())
    original = sizing["fx"]["conversions"][0]["original_value"]
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["founder_stated_inputs"] = {"industry_total": original}
    inputs["founder_stated_inputs_currency"] = "USD"
    (d / "inputs.json").write_text(json.dumps(inputs))
    codes = _compose_codes(d)
    assert "FOUNDER_VALUE_OVERRIDDEN" not in codes
    assert "COMPARISON_CURRENCY_UNKNOWN" not in codes


def test_compose_still_catches_a_genuine_override_across_a_conversion(tmp_path: Path) -> None:
    """The suppression must not be blanket.

    Without this, disabling the check entirely would pass every other case here.
    """
    d = _fx_dir(tmp_path, converted=True)
    sizing = json.loads((d / "sizing.json").read_text())
    original = sizing["fx"]["conversions"][0]["original_value"]
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["founder_stated_inputs"] = {"industry_total": original * 0.5}
    inputs["founder_stated_inputs_currency"] = "USD"
    (d / "inputs.json").write_text(json.dumps(inputs))
    assert "FOUNDER_VALUE_OVERRIDDEN" in _compose_codes(d)


def test_compose_flags_a_figureless_sizing_artifact_at_high_severity(tmp_path: Path) -> None:
    """A rejected sizing step must be loud downstream too.

    market_sizing.py no longer writes this stub, so reaching compose means a stale
    or hand-edited artifact — but the old silent path rendered an empty table with
    no code naming the cause, so the detector stays.
    """
    d = tmp_path / "market-sizing-testco"
    d.mkdir()
    _make_full_sizing_dir(d)
    (d / "sizing.json").write_text(
        json.dumps({"validation": {"status": "invalid", "errors": ["industry_total must be positive"]}})
    )
    rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
    assert data is not None, err
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "SIZING_INVALID"]
    assert hits, "a figure-less sizing.json must raise SIZING_INVALID"
    assert hits[0]["severity"] == "high", "must not be acceptable-away"


# --- regressions found by adversarial review of the FX implementation ----------


def test_fx_conversion_result_must_be_a_usable_figure() -> None:
    """The PRODUCT is re-validated, not just the rate.

    validate_positive runs pre-conversion, so a legitimately positive input can
    land on 0.0 after a small rate and 2dp rounding, or on Infinity after a huge
    one, and still report status "valid" with real-looking zeros in the artifact.
    """
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "customer_count": 1000,
            "arpu": 0.5,
            "arpu_currency": "JPY",
            "serviceable_pct": 35,
            "target_pct": 5,
            "currency": "USD",
            "fx": {"rates": {"JPY:USD": 0.0067}, "as_of": "d", "source": "s"},
        }
    )
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc == 1
    _assert_validation_errors(data, "E_FX_RESULT_INVALID")


def test_fx_dispatch_templates_ask_for_the_currency_tag() -> None:
    """The tag must be in the JSON SHAPE, not only in prose around it.

    The sub-agent copies the shape. With the tag absent from it, a compliant run
    emits no tag, so nothing converts AND nothing refuses — the pre-fix silent
    mislabelling path stays live and the whole feature is unreachable.
    """
    skill = (Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "SKILL.md").read_text(encoding="utf-8")
    agent = (Path(__file__).resolve().parents[1] / "agents" / "market-sizing.md").read_text(encoding="utf-8")
    for name, text in (("SKILL.md", skill), ("agents/market-sizing.md", agent)):
        assert "industry_total_currency" in text, f"{name}: TOP_DOWN shape must request the tag"
        assert "arpu_currency" in text, f"{name}: BOTTOM_UP shape must request the tag"


def test_compose_honours_a_declared_currency_for_an_unconverted_field(tmp_path: Path) -> None:
    """A declared currency applies to every founder-stated money figure.

    The declaration is object-level, but only SOME fields may have a conversion
    record. Gating on "was this field converted" made a declared-USD arpu compare
    against an ILS figure and reported the founder's own number as overridden.
    """
    d = tmp_path / "market-sizing-testco"
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    sizing["currency"] = "ILS"
    arpu_ils = _as_float(sizing["bottom_up"]["tam"]["inputs"]["arpu"])
    it_ils = _as_float(sizing["top_down"]["tam"]["inputs"]["industry_total"])
    # industry_total was converted; arpu was sourced domestically (no record).
    sizing["fx"] = {
        "as_of": "2026-08-01",
        "source": "s",
        "conversions": [
            {
                "field": "industry_total",
                "from": "USD",
                "to": "ILS",
                "rate": 3.72,
                "original_value": round(it_ils / 3.72, 2),
                "converted_value": it_ils,
            }
        ],
    }
    (d / "sizing.json").write_text(json.dumps(sizing))
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["currency"] = "ILS"
    inputs["founder_stated_inputs"] = {"arpu": round(arpu_ils / 3.72, 2)}
    inputs["founder_stated_inputs_currency"] = "USD"
    (d / "inputs.json").write_text(json.dumps(inputs))
    codes = _compose_codes(d)
    assert "FOUNDER_VALUE_OVERRIDDEN" not in codes, "a faithful USD-declared arpu must not read as overridden"


def test_compose_matches_the_rate_by_currency_pair_not_by_first_record(tmp_path: Path) -> None:
    """With two source currencies, a claim in the SECOND one is still comparable.

    Picking `next(iter(conversions))` refused a check that was fully computable
    and told the founder their currency was unrecognised.
    """
    d = tmp_path / "market-sizing-testco"
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    sizing["currency"] = "ILS"
    tam = _as_float(sizing["top_down"]["tam"]["value"])
    sizing["fx"] = {
        "as_of": "2026-08-01",
        "source": "s",
        "conversions": [
            {
                "field": "industry_total",
                "from": "USD",
                "to": "ILS",
                "rate": 3.72,
                "original_value": 1.0,
                "converted_value": 3.72,
            },
            {"field": "arpu", "from": "EUR", "to": "ILS", "rate": 4.0, "original_value": 1.0, "converted_value": 4.0},
        ],
    }
    (d / "sizing.json").write_text(json.dumps(sizing))
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["currency"] = "ILS"
    # A EUR claim equal to the computed TAM once converted at the recorded EUR rate.
    inputs["existing_claims"] = {"tam": round(tam / 4.0, 2)}
    inputs["existing_claims_currency"] = "EUR"
    (d / "inputs.json").write_text(json.dumps(inputs))
    codes = _compose_codes(d)
    assert "COMPARISON_CURRENCY_UNKNOWN" not in codes, "EUR is a recorded source currency here"
    assert "DECK_CLAIM_MISMATCH" not in codes, "the converted claim matches the computed TAM"


def test_compose_new_warnings_do_not_name_internal_fields(tmp_path: Path) -> None:
    """The new founder-facing messages must not leak artifact or field names.

    SIZING_INVALID named `sizing.json` and tripped the skill's own founder-text
    detector; COMPARISON_CURRENCY_UNKNOWN named `inputs.founder_stated_inputs_currency`,
    which slipped past it because the dotted form escapes the substitution guard.
    """
    d = tmp_path / "market-sizing-testco"
    d.mkdir()
    _make_full_sizing_dir(d)
    (d / "sizing.json").write_text(json.dumps({"validation": {"status": "invalid", "errors": ["bad"]}}))
    rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
    assert data is not None, err
    # Scoped to the codes this change introduced. `APPROACH_MISMATCH` also names sizing.json —
    # a PRE-EXISTING leak, out of scope here rather than silently folded in, and FOUNDER_TEXT_TOKEN
    # must name the offending token to be actionable at all.
    mine = {"SIZING_INVALID", "COMPARISON_CURRENCY_UNKNOWN"}
    msgs = " ".join(w["message"] for w in data["validation"]["warnings"] if w["code"] in mine)
    assert msgs, "expected at least one of the new warnings in this fixture"
    for leaked in ("sizing.json", "founder_stated_inputs_currency", "existing_claims_currency"):
        assert leaked not in msgs, f"founder-facing warning text names {leaked}"


def test_sensitivity_invalid_input_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    """`sensitivity.py` refuses loudly, like `market_sizing.py`.

    It had the same defect: exit 0, an `{"ok":true}` receipt, and a figure-less stub written over
    the canonical artifact — so the pipe never "failed next" and the prior good file was gone.
    """
    out = tmp_path / "sensitivity.json"
    out.write_text('{"sentinel": true}')
    rc, data, stderr = run_script(
        "sensitivity.py",
        ["-o", str(out)],
        stdin_data=json.dumps({"approach": "bottom_up", "base": {"customer_count": "x"}, "ranges": {}}),
    )
    assert rc == 1
    assert stderr.strip()
    assert data is not None and data["validation"]["status"] == "invalid"
    assert json.loads(out.read_text()) == {"sentinel": True}, "the canonical artifact was clobbered"


def test_checklist_invalid_input_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    """`checklist.py` refuses loudly — both of its invalid paths."""
    out = tmp_path / "checklist.json"
    out.write_text('{"sentinel": true}')
    rc, data, stderr = run_script("checklist.py", ["-o", str(out)], stdin_data=json.dumps({"notitems": 1}))
    assert rc == 1
    assert stderr.strip()
    assert data is not None and data["validation"]["status"] == "invalid"
    assert json.loads(out.read_text()) == {"sentinel": True}

    # Second path: well-formed `items`, rejected by validate_checklist.
    rc2, data2, _ = run_script(
        "checklist.py",
        ["-o", str(out)],
        stdin_data=json.dumps({"items": [{"id": "not_a_real_criterion", "status": "pass", "evidence": "x"}]}),
    )
    assert rc2 == 1
    assert data2 is not None and data2["validation"]["status"] == "invalid"
    assert json.loads(out.read_text()) == {"sentinel": True}


def test_compose_flags_an_invalid_sensitivity_or_checklist_at_high_severity(tmp_path: Path) -> None:
    """A rejected sensitivity/checklist step must not surface only as a medium symptom.

    Before this, the sole signals were FEW_SENSITIVITY_PARAMS / CHECKLIST_INCOMPLETE — both
    medium, so both acceptable-away via accepted_warnings, and both naming a symptom.
    """
    for name in ("sensitivity.json", "checklist.json"):
        d = tmp_path / f"market-sizing-{name.split('.')[0]}"
        d.mkdir()
        _make_full_sizing_dir(d)
        (d / name).write_text(json.dumps({"validation": {"status": "invalid", "errors": ["bad input"]}}))
        rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
        assert data is not None, err
        hits = [w for w in data["validation"]["warnings"] if w["code"] == "ARTIFACT_INVALID"]
        assert hits, f"{name}: a rejected producer artifact must raise ARTIFACT_INVALID"
        assert hits[0]["severity"] == "high", f"{name}: must not be acceptable-away"


# --- P0.8: non-finite and boolean numeric inputs -------------------------------------------
#
# `coerce_float`/`coerce_int` caught only (TypeError, ValueError), which `float()` does not
# raise for bool, "nan" or "inf". All three reached a delivered artifact: bool as a silently
# wrong number, NaN/Infinity as bare non-JSON literals beside `"status": "valid"`.
#
# Reproduced before the fix, on the shipped script:
#   industry_total=true   -> exit 0, status "valid"
#   industry_total="nan"  -> exit 0, status "valid", body contains bare NaN
#   industry_total="inf"  -> exit 0, status "valid", body contains bare Infinity
#
# Containers were ALWAYS rejected (float({}) raises TypeError) — the guard that was missing
# is scalar, not structural, so the container cases below are pinned as controls.


@pytest.mark.parametrize(
    ("value", "expect_fragment"),
    [
        ("true", "must be numeric"),
        ("false", "must be numeric"),
        ('"nan"', "must be a finite number"),
        ('"NaN"', "must be a finite number"),
        ('"inf"', "must be a finite number"),
        ('"-inf"', "must be a finite number"),
        ('"Infinity"', "must be a finite number"),
    ],
)
def test_non_finite_and_boolean_numerics_are_rejected(value: str, expect_fragment: str) -> None:
    """Each must fail loudly, not compute a number from it."""
    payload = f'{{"approach":"top-down","industry_total":{value},"segment_pct":50,"share_pct":5}}'
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc != 0, f"industry_total={value} was accepted (exit 0)"
    assert data is not None and data["validation"]["status"] == "invalid"
    assert any(expect_fragment in e for e in data["validation"]["errors"]), data["validation"]["errors"]


@pytest.mark.parametrize("field", ["segment_pct", "share_pct"])
def test_boolean_percentages_are_rejected(field: str) -> None:
    """`float(True)` is 1.0, so a bool here silently computed a 1% figure."""
    fields = {"industry_total": "1000", "segment_pct": "50", "share_pct": "5"}
    fields[field] = "true"
    payload = '{"approach":"top-down",' + ",".join(f'"{k}":{v}' for k, v in fields.items()) + "}"
    rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc != 0, f"{field}=true was accepted (exit 0)"
    assert data is not None and data["validation"]["status"] == "invalid"


def test_rejected_numerics_never_emit_non_standard_json_literals() -> None:
    """NaN/Infinity are not legal JSON; Python emits them bare.

    A body carrying one is unparseable by a strict reader while `validation.status` reads
    "valid" — so this asserts the raw text, which `json.loads` would silently accept.
    """
    payload = '{"approach":"top-down","industry_total":"nan","segment_pct":50,"share_pct":5}'
    rc, out, _ = run_script_raw("market_sizing.py", ["--stdin"], stdin_data=payload)
    assert rc != 0
    assert "NaN" not in out and "Infinity" not in out, "non-standard JSON literal reached stdout"


def test_valid_and_container_inputs_are_unaffected() -> None:
    """Control: the fix must not narrow what already worked, nor widen what already failed."""
    ok = '{"approach":"top-down","industry_total":1000,"segment_pct":50,"share_pct":5}'
    rc, data, err = run_script("market_sizing.py", ["--stdin"], stdin_data=ok)
    assert rc == 0, err
    assert data is not None and data["validation"]["status"] == "valid"

    for container in ('{"value":1000}', "[1000]"):
        payload = f'{{"approach":"top-down","industry_total":{container},"segment_pct":50,"share_pct":5}}'
        rc, data, _ = run_script("market_sizing.py", ["--stdin"], stdin_data=payload)
        assert rc != 0, f"container {container} must still be rejected"
