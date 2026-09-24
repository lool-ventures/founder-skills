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
import shutil
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
    # The band, not a boolean: 22/22 is 100%, which is `strong`. `all_pass` carries what
    # the old "pass" word meant, and the two are asserted separately on purpose.
    assert s["overall_status"] == "strong"
    assert s["all_pass"] is True
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
    # 19/21 applicable = 90.5%, still `strong`; the two failures show up in `all_pass`.
    assert s["overall_status"] == "strong"
    assert s["all_pass"] is False
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
    assert s["overall_status"] == "strong"
    assert s["all_pass"] is True
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
    # A recorded decision, because the adversarial-review gate refuses to compose without one.
    # These fixtures predate the red-team step, so they represent a run where someone chose not to
    # attack the figures -- which is a legitimate state, and is exactly what the enum is for. The
    # gate's own tests omit this field deliberately.
    "red_team_skipped": "founder_declined",
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
        "score_pct": 100.0,
        "overall_status": "strong",
        "all_pass": True,
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
        "score_pct": 90.9,
        "overall_status": "strong",
        "all_pass": False,
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


def _compose_with_sizing_warning(fx: dict[str, Any], extra: dict[str, Any] | None = None) -> Any:
    """Run the real producer with `fx`, optionally inject `extra`, and compose."""
    rc, sizing, err = run_script(
        "market_sizing.py", ["--stdin"], stdin_data=_fx_stdin(industry_total_currency="USD", fx=fx)
    )
    assert rc == 0, err
    assert sizing is not None
    if extra is not None:
        sizing["validation"]["warnings"].append(extra)
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
    return _run_compose(d)


def test_compose_forwards_fx_unsourced() -> None:
    """FX_UNSOURCED must reach the founder-facing Warnings section.

    It was emitted into sizing.json and read by nothing: the forwarding loop matched the
    single literal "IMPLAUSIBLE_PCT_SCALE", so the code was silently dropped for the two
    releases it existed. The currency callout disclosed the gap inline, but the warning
    itself never reached the Warnings list or report.json.
    """
    rc, data, _ = _compose_with_sizing_warning({"rates": {"USD:ILS": 3.72}})
    assert rc == 0
    assert data is not None
    forwarded = [w for w in data["validation"]["warnings"] if w["code"] == "FX_UNSOURCED"]
    assert forwarded, f"FX_UNSOURCED was not forwarded; got {[w['code'] for w in data['validation']['warnings']]}"
    assert forwarded[0]["severity"] == "low", (
        "low is deliberate: the inline currency callout already states the gap, so this is an "
        "authoring task, not a blocker. Medium would fail --strict and SKILL.md then stops the "
        "run before the coaching step, on a condition the agent usually cannot fix."
    )


def test_fx_unsourced_message_names_which_half_is_missing() -> None:
    """The warning must not contradict the inline currency disclosure.

    The warning fires when EITHER the rate's date or its source is absent, and the callout
    renders whichever is present ("Rate as of 2026-01-15 (source not stated)"). A message
    saying "no date or source" when a date IS shown puts two lines of one report in direct
    conflict — worse than the silence it replaced.
    """
    base: dict[str, Any] = {"rates": {"USD:ILS": 3.72}}
    cases: list[tuple[dict[str, Any], str, str]] = [
        (base, "neither a date nor a source", "date not stated"),
        ({**base, "as_of": "2026-01-15"}, "no source", "2026-01-15"),
        ({**base, "source": "ECB"}, "no date", "ECB"),
    ]
    for fx, expected_phrase, inline_token in cases:
        rc, data, _ = _compose_with_sizing_warning(fx)
        assert rc == 0
        assert data is not None
        msg = next(w["message"] for w in data["validation"]["warnings"] if w["code"] == "FX_UNSOURCED")
        assert expected_phrase in msg, f"fx={fx} -> {msg!r}"
        callout = next(line for line in data["report_markdown"].splitlines() if "Currency:" in line)
        assert inline_token in callout, "precondition: the inline callout must show the half that IS present"
        # The JSON path must not reach the founder. _founder_text.scan() passes `fx.as_of`
        # (the dot defeats it) while flagging a bare `as_of`, so no scanner guards this.
        assert "fx.as_of" not in msg and "fx.source" not in msg


def test_blank_fx_provenance_is_absent_not_supplied() -> None:
    """Whitespace-only `--fx-as-of` / `--fx-source` must count as ABSENT.

    The warning gates on `not (as_of and source)`, and a blank string is truthy. So
    `--fx-as-of "   "` suppressed the warning AND rendered the callout as
    `Rate as of     (  ).` — a converted figure that looks sourced, warns nobody, and
    prints a blank where the date belongs. It is the state an agent reaches by filling in
    flags SKILL.md presents as a set when it has a rate but no citation, which makes it
    likelier than the honestly-omitted case the warning was written for.
    """
    rc, sizing, err = run_script(
        "market_sizing.py",
        ["--stdin", "--fx-as-of", "   ", "--fx-source", "  "],
        stdin_data=_fx_stdin(industry_total_currency="USD", fx={"rates": {"USD:ILS": 3.72}}),
    )
    assert rc == 0, err
    assert sizing is not None
    assert sizing["fx"]["as_of"] is None, f"blank as_of must normalise to None, got {sizing['fx']['as_of']!r}"
    assert sizing["fx"]["source"] is None, f"blank source must normalise to None, got {sizing['fx']['source']!r}"
    codes = [w["code"] for w in sizing["validation"]["warnings"]]
    assert "FX_UNSOURCED" in codes, "blank provenance is unsourced provenance"

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
    callout = next(line for line in data["report_markdown"].splitlines() if "Currency:" in line)
    assert "date not stated" in callout, f"blank date must render as unstated, got: {callout}"
    assert "Rate as of  " not in callout, f"blank rendered into the callout: {callout}"


def test_compose_does_not_forward_a_code_it_owns_itself() -> None:
    """A producer artifact must not be able to assert a compose-owned code.

    This is what keeps `_PRODUCER_FORWARDABLE` a subset rather than all of WARNING_SEVERITY.
    Measured under blanket forwarding: a sizing.json carrying MISSING_ARTIFACT with all six
    artifacts present emits `[HIGH] MISSING_ARTIFACT`, which cannot be accepted away
    (ACCEPTIBLE_SEVERITIES is medium-only) and drags a FOUNDER_TEXT_TOKEN leak with it.
    """
    rc, data, _ = _compose_with_sizing_warning(
        {"rates": {"USD:ILS": 3.72}},
        extra={"code": "MISSING_ARTIFACT", "message": "sensitivity.json was not produced"},
    )
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" not in codes, (
        "a sizing.json claim of MISSING_ARTIFACT was forwarded despite all six artifacts being "
        "present — the forwarding set must stay a producer-owned subset"
    )
    assert "FX_UNSOURCED" in codes, "precondition: real producer warnings still forward"


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
        "FOUNDER_PERIOD_UNKNOWN",
        # A rejected sizing step used to reach compose with no code naming the cause.
        "SIZING_INVALID",
        # Emitted instead of a guaranteed-false FOUNDER_VALUE_OVERRIDDEN / DECK_CLAIM_MISMATCH
        # when a money input was FX-converted and the comparand declares no currency.
        "COMPARISON_CURRENCY_UNKNOWN",
        # A rejected sensitivity/checklist step, same class as SIZING_INVALID.
        "ARTIFACT_INVALID",
        # The unacceptable half of the checklist split: more failures than the sizing can
        # score as solid with, which is a statement about the run rather than about items.
        "CHECKLIST_FAILURES_CRITICAL",
        # A parameter the sizing math consumed that the sensitivity pass never varied. Nothing
        # could see this class before: UNSOURCED_ASSUMPTIONS covers only `agent_estimate`
        # assumptions and FEW_SENSITIVITY_PARAMS fires below 3 scenarios.
        "SENSITIVITY_OMITS_PARAM",
        # The sibling: the parameter IS stress-tested, but at a tier nothing graded, so the
        # fallback (`sourced`) widens nothing and the band shown is the caller's own.
        "SENSITIVITY_DEFAULTED_CONFIDENCE",
        # The two builds agreeing because they are not independent — the opposite case from the
        # *_DISCREPANCY codes above, and the more dangerous one.
        "SHARED_TAM_IDENTITY",
        "PAIRED_SLOT_SAME_VALUE",
        # Two figures for different periods are incomparable, not in disagreement.
        "HORIZON_MISMATCH",
        # A derivation that does not multiply to its own value, and one that cannot be checked
        # at all because it was never itemized.
        "FACTOR_PRODUCT_MISMATCH",
        "UNSTRUCTURED_DERIVATION",
        # The two narrowing chains built from overlapping figures — the detector this whole
        # change set exists for, and the one slot-value identity could never see.
        "SHARED_FACTOR_OVERLAP",
        # The adversarial review: what it found, and what it filed without a source.
        "RED_TEAM_FINDINGS",
        "RED_TEAM_FINDINGS_DROPPED",
        "RED_TEAM_SOURCES_UNREAD",
        "FOUNDER_STATED_MARKET_FIGURE",
    ]
    # +4: the adversarial review read from its append-only copy (REDTEAM_ALTERED,
    # RED_TEAM_RERUN_UNAPPROVED, REVIEW_COPY_MISSING, RED_TEAM_SKIP_CONTRADICTED); +1 for a review
    # from an earlier run of the same analysis (EARLIER_REVIEW_THIS_ANALYSIS); +1 for a founder figure
    # changed after the review without confirmation (FOUNDER_INPUT_REWRITTEN).
    assert len(sev_map) == 51, f"expected 51 codes, got {len(sev_map)}"
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
        "score_pct": 100.0,
        "overall_status": "strong",
        "all_pass": True,
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


def test_a_declared_confidence_cannot_narrow_a_validated_one() -> None:
    """REVERSED DELIBERATELY, and the old rule is the reason.

    This test used to assert that a range's own `confidence` "always wins over
    validation_confidence, even when they disagree -- the range is authoritative when present at
    all". That deferred to the caller on the one field the caller has an incentive to understate:
    tag a parameter `sourced` and it is never widened, whatever the validation step concluded.
    The payload below IS the exploit -- declared `sourced`, validated `agent_estimate`, zero
    stress-testing -- and it was pinned as correct.

    The tiers are ordered by `CONFIDENCE_MIN_RANGE`, so reconciliation can only ever WIDEN, which
    is the safe direction: the failure being closed is an uncertain input going unstressed.
    """
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
    assert s["confidence"] == "agent_estimate", "the stricter validated tier must win"
    assert s["confidence_source"] == "reconciled"
    assert s["range_widened"] is True
    assert s["effective_range"]["low_pct"] == -50
    assert s["effective_range"]["high_pct"] == 50


def test_a_declared_confidence_is_kept_when_it_is_already_the_stricter_one() -> None:
    """Reconciliation only widens. A declared tier stricter than the validated one stands."""
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2},
            "ranges": {"arpu": {"low_pct": -60, "high_pct": 60, "confidence": "agent_estimate"}},
            "validation_confidence": {"arpu": "sourced"},
        }
    )
    rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["scenarios"][0]
    assert s["confidence"] == "agent_estimate"
    assert s["confidence_source"] == "range"
    assert s["effective_range"]["high_pct"] == 60


def test_confidence_source_distinguishes_a_default_from_a_choice() -> None:
    """ "No widening happened" and "no widening was called for" were indistinguishable."""
    base = {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2}
    cases = {
        "range": ({"arpu": {"low_pct": -10, "high_pct": 10, "confidence": "sourced"}}, {}),
        "validation": ({"arpu": {"low_pct": -10, "high_pct": 10}}, {"arpu": "sourced"}),
        "default": ({"arpu": {"low_pct": -10, "high_pct": 10}}, {}),
    }
    for expected, (ranges, xref) in cases.items():
        payload = json.dumps({"approach": "bottom_up", "base": base, "ranges": ranges, "validation_confidence": xref})
        rc, data, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
        assert rc == 0 and data is not None
        assert data["scenarios"][0]["confidence_source"] == expected, expected


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
    """accepted_warnings with high-severity code -> NOT downgraded, stderr mentions cannot accept.

    Uses CHECKLIST_FAILURES_CRITICAL rather than CHECKLIST_FAILURES: the latter is now
    MEDIUM and therefore acceptable by design, which is the whole point of the split. A
    test about what cannot be accepted has to name a code that still cannot be.
    """
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "CHECKLIST_FAILURES_CRITICAL", "reason": "Trust me", "match": "failures"},
    ]
    # 9 failures, past CHECKLIST_CRITICAL_FAILURES, so the unacceptable half fires.
    failed_checklist = _checklist_artifact(9)
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
    checklist_w = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES_CRITICAL"]
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
    warns = data["validation"]["warnings"]
    codes = [w["code"] for w in warns]
    assert "CORRUPT_ARTIFACT" in codes
    # A corrupt REQUIRED artifact must not be reclassified as a missing optional one. This
    # assertion was vacuous until market-sizing had an optional artifact at all — the optional
    # warning now fires legitimately (no adversarial review ran), so pin the SUBJECT rather than
    # the code's absence, which is the part that was ever load-bearing.
    optional = [w for w in warns if w["code"] == "MISSING_OPTIONAL_ARTIFACT"]
    assert len(optional) == 1 and "adversarial" in optional[0]["message"].lower(), optional
    assert "sensitivity" not in optional[0]["message"].lower()


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
    """compose emits a coaching_payload block with all v0.7.0-market-sizing fields."""
    import re

    d = _make_artifact_dir(_make_full_sizing_arts())
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "coaching_payload" in data, "report.json missing coaching_payload block"

    payload = data["coaching_payload"]
    # Bumped with the band: `summary` gained `overall_status` and `all_pass`, and
    # `overall_status`'s vocabulary changed from a pass/fail boolean to the fleet's 4 bands.
    assert payload["schema_version"] == "v0.7.0-market-sizing"
    assert payload["summary"]["overall_status"] in {"strong", "solid", "needs_work", "major_revision"}
    assert isinstance(payload["summary"]["all_pass"], bool)

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
        "overall_status": "strong",
        "all_pass": False,
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
    """No score_pct in checklist summary → confidence is null (not fabricated).

    The absence is set up EXPLICITLY rather than inherited from the shared fixture. It used
    to rely on `_VALID_CHECKLIST` happening to omit `score_pct`, so adding the field to that
    fixture silently changed what this test was testing.
    """
    arts = _make_full_sizing_arts()
    checklist = dict(arts["checklist.json"])
    summary = {k: v for k, v in dict(checklist["summary"]).items() if k != "score_pct"}
    checklist["summary"] = summary
    arts["checklist.json"] = checklist
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
            "score_pct": 90.9,
            "overall_status": "strong",
            "all_pass": False,
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
    # Bound on STRUCTURE, not a fixed character count. The Context B section is ~9,200 chars,
    # longer than every fixed window previously used against it, so an additive edit to the
    # payload key list pushed a string past the boundary and failed this test on content that
    # is still present. The section ends at the next level-2 heading; CLAUDE.md prescribes
    # exactly this over widening N, which only defers the next break.
    _end = agent_body.find("\n## ", idx)
    section = agent_body[idx : _end if _end != -1 else len(agent_body)]
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


def _sizing_with_arpu(customer_count: float, arpu: float) -> dict[str, Any]:
    """`_sizing_with`, with every block's `arpu` input set to `arpu` (the math's annual figure)."""
    sizing = _sizing_with(customer_count)
    for block in sizing["bottom_up"].values():
        if isinstance(block, dict) and "arpu" in _as_dict_local(block.get("inputs")):
            block["inputs"]["arpu"] = arpu
    return sizing


def _as_dict_local(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def test_no_subagent_dispatch_is_a_skip_reason_that_does_not_promise_a_re_run() -> None:
    """MEASURED on claude.ai: the run could not dispatch a reviewer at all, wrote
    `dispatch_failed` (the closest value), and the founder was told the review "was attempted and
    did not complete ... worth re-running". Nothing was attempted; re-running there cannot help."""
    meth = {**_VALID_METHODOLOGY, "approach_chosen": "both", "red_team_skipped": "no_subagent_dispatch"}
    rc, data, d = _compose_with_sizing(_VALID_SIZING, methodology=meth)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    section = md.split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "single agent" in section and "cannot dispatch" in section, section
    assert "worth re-running" not in section
    assert "Claude Cowork or Claude Code" in section
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert "single agent" in html_text


def test_founder_stated_monthly_figure_is_normalised_before_the_fidelity_check() -> None:
    """MEASURED live: the founder stated $203 per patient-month, the sizing consumed the annual
    $2,436, FOUNDER_VALUE_OVERRIDDEN called the correct x12 an override, and its remedy text told
    the constructor to "update inputs.founder_stated_inputs" -- which it did, with no founder in
    the loop. A stated period normalises the comparison; the figure is not the same as the value
    the math used, and the check has to know which period it was quoted per."""
    arpu_sizing = _sizing_with_arpu(18000, 2436)
    d = _make_artifact_dir(
        {
            "inputs.json": {
                **_VALID_INPUTS,
                "founder_stated_inputs": {"arpu": 203, "customer_count": 18000},
                "founder_stated_inputs_period": {"arpu": "month"},
            },
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": arpu_sizing,
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    assert "FOUNDER_VALUE_OVERRIDDEN" not in _codes(result), _codes(result)
    assert "FOUNDER_PERIOD_UNKNOWN" not in _codes(result)


def test_founder_stated_figure_without_a_period_still_reports_but_never_tells_the_model_to_edit() -> None:
    """Without a period the 203-vs-2436 case still reports (it cannot know), but the remedy no
    longer says "update inputs.founder_stated_inputs": that sentence was followed literally."""
    arpu_sizing = _sizing_with_arpu(18000, 2436)
    d = _make_artifact_dir(
        {
            "inputs.json": {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 203, "customer_count": 18000}},
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": arpu_sizing,
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    msg = next(w["message"] for w in result["validation"]["warnings"] if w["code"] == "FOUNDER_VALUE_OVERRIDDEN")
    assert "203" in msg and "2,436" in msg
    assert "update inputs.founder_stated_inputs" not in msg
    assert "Do not edit founder_stated_inputs" in msg and "founder_stated_inputs_period" in msg


def test_founder_stated_period_unknown_is_named_and_compared_as_annual() -> None:
    arpu_sizing = _sizing_with_arpu(18000, 2436)
    d = _make_artifact_dir(
        {
            "inputs.json": {
                **_VALID_INPUTS,
                "founder_stated_inputs": {"arpu": 203, "customer_count": 18000},
                "founder_stated_inputs_period": {"arpu": "fortnight"},
            },
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": arpu_sizing,
        }
    )
    code, result, _ = _run_compose(d)
    assert code == 0 and result is not None
    codes = _codes(result)
    assert "FOUNDER_PERIOD_UNKNOWN" in codes and "FOUNDER_VALUE_OVERRIDDEN" in codes
    msg = next(w["message"] for w in result["validation"]["warnings"] if w["code"] == "FOUNDER_VALUE_OVERRIDDEN")
    assert "203 per fortnight" in msg


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


# ---------------------------------------------------------------------------
# Close-agreement footnote, degenerate narrowing, and widest-stressed tie.
#
# Every numeric fixture below is a REAL value measured from the 3-deck A/B corpus
# (see docs/internal/2026-08-10-market-sizing-circularity-findings.md). They are
# not invented shapes: a previous fix plan shipped tests built from hand-made
# fixtures that encoded the fix's own premise, and they passed while the fix was
# inert on every real run.
# ---------------------------------------------------------------------------

# deck-01: top-down TAM reproduced the founder's own $22B exactly (delta 0.0%).
# deck-02: +22.8%. deck-03: -8.6%. All three were rendered with no caveat, and in
# report.html the deck-01 row was the ONLY item under "What's strong".
_MEASURED_CLOSE_DELTAS = (0.0, 22.8, -8.6)
# Every |delta| the same corpus produced outside the band.
_MEASURED_DISTANT_DELTAS = (-43.2, -73.0, -76.3, -88.8, -95.9, -98.5, -99.4, -100.0)


def _claim_dir_for_delta(tmp_path: Path, delta_pct: float, name: str) -> Path:
    """Artifact dir whose top-down TAM sits `delta_pct` away from the deck's claim."""
    d = tmp_path / name
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    tam = _as_float(sizing["top_down"]["tam"]["value"])
    inputs = json.loads((d / "inputs.json").read_text())
    # claim such that (tam - claim)/claim == delta_pct/100.
    # -100.0 is unreachable exactly (it needs an infinite claim); in the corpus it is a rounded
    # -99.96%, so reproduce it as a claim three orders larger rather than skipping the case.
    factor = 1.0 + delta_pct / 100.0
    claim = tam * 1000.0 if abs(factor) < 1e-9 else tam / factor
    inputs["existing_claims"] = {"tam": round(claim, 2)}
    (d / "inputs.json").write_text(json.dumps(inputs))
    return d


def _compose_md_text(d: Path) -> str:
    md = d / "report.md"
    rc, _, err = run_script("compose_report.py", ["--dir", str(d), "-o", str(d / "report.json"), "--write-md", str(md)])
    assert rc == 0, err
    return md.read_text()


@pytest.mark.parametrize("delta", _MEASURED_CLOSE_DELTAS)
def test_close_agreement_row_is_footnoted(tmp_path: Path, delta: float) -> None:
    """Each delta measured as a silent close agreement now carries a caveat."""
    d = _claim_dir_for_delta(tmp_path, delta, f"ms-close-{abs(delta)}")
    md = _compose_md_text(d)
    assert "Agreement on a number is not independent confirmation" in md
    # the marker must be on the TAM row itself, not just floating in the section
    tam_rows = [ln for ln in md.splitlines() if ln.startswith("| TAM (Top-down)")]
    assert tam_rows and "*" in tam_rows[0], tam_rows


@pytest.mark.parametrize("delta", _MEASURED_DISTANT_DELTAS)
def test_distant_row_is_not_footnoted(tmp_path: Path, delta: float) -> None:
    """Deltas outside the band get no caveat — that is DECK_CLAIM_MISMATCH's job."""
    d = _claim_dir_for_delta(tmp_path, delta, f"ms-far-{abs(delta)}")
    md = _compose_md_text(d)
    assert "Agreement on a number is not independent confirmation" not in md


def test_footnote_suppressed_when_fx_comparison_is_refused(tmp_path: Path) -> None:
    """A converted run with no declared claim currency must not assert closeness.

    compose already refuses this comparison (COMPARISON_CURRENCY_UNKNOWN) because the raw delta
    carries the exchange rate's magnitude on a perfectly correct analysis. The footnote must not
    contradict that refusal. Built as its own fixture: the pre-existing FX tests use inputs with
    no `existing_claims` at all, so no comparison row renders and any assertion about the
    footnote would pass vacuously.
    """
    d = _fx_dir(tmp_path, converted=True)
    sizing = json.loads((d / "sizing.json").read_text())
    tam = _as_float(sizing["top_down"]["tam"]["value"])
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["existing_claims"] = {"tam": tam}  # numerically identical => raw delta 0.0%
    inputs.pop("existing_claims_currency", None)  # ...but undeclared, so not comparable
    (d / "inputs.json").write_text(json.dumps(inputs))
    md = _compose_md_text(d)
    assert "COMPARISON_CURRENCY_UNKNOWN" in _compose_codes(d)
    assert "Agreement on a number is not independent confirmation" not in md


def test_degenerate_narrowing_fires_when_sam_equals_tam(tmp_path: Path) -> None:
    """deck-01's real shape: bottom-up TAM == SAM == $900M, serviceable_pct 100.

    The 22-item self-check has an item for this and the agent returned `pass` on that very run,
    with evidence text describing the failure. There is no code check anywhere; this is it.
    """
    d = tmp_path / "ms-degenerate"
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    sizing["bottom_up"]["sam"]["value"] = sizing["bottom_up"]["tam"]["value"]
    (d / "sizing.json").write_text(json.dumps(sizing))
    assert "DEGENERATE_NARROWING" in _compose_codes(d)


def test_degenerate_narrowing_tolerates_float_noise(tmp_path: Path) -> None:
    """These artifacts really do carry values like 12670000000.000002."""
    d = tmp_path / "ms-degenerate-noise"
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    tam = _as_float(sizing["bottom_up"]["tam"]["value"])
    sizing["bottom_up"]["sam"]["value"] = tam * (1 + 1e-12)
    (d / "sizing.json").write_text(json.dumps(sizing))
    assert "DEGENERATE_NARROWING" in _compose_codes(d)


def test_degenerate_narrowing_silent_when_sam_narrows(tmp_path: Path) -> None:
    """deck-02 ($7T -> $560B) and deck-03 ($181B -> $12.67B) both narrow properly."""
    d = tmp_path / "ms-narrowing-ok"
    d.mkdir()
    _make_full_sizing_dir(d)
    assert "DEGENERATE_NARROWING" not in _compose_codes(d)


def test_widest_stressed_tie_is_disclosed(tmp_path: Path) -> None:
    """Measured 3-, 4- and 3-way ties at identical swing on the three decks.

    `most_sensitive` is ranking[0], so the winner was decided by sub-agent authoring order. The
    report must not present one arbitrary member of a tie as *the* answer.
    """
    d = tmp_path / "ms-tie"
    d.mkdir()
    _make_full_sizing_dir(d)
    sens = json.loads((d / "sensitivity.json").read_text())
    ranking = sens.get("sensitivity_ranking") or []
    if len(ranking) < 2:
        # A skipped test is a vacuous test. Build the measured shape instead: deck-02 had four
        # parameters tied at exactly 100.0, the winner decided by list order.
        ranking = [
            {"parameter": "segment_pct", "som_swing_pct": 100.0},
            {"parameter": "share_pct", "som_swing_pct": 100.0},
            {"parameter": "serviceable_pct", "som_swing_pct": 100.0},
            {"parameter": "target_pct", "som_swing_pct": 100.0},
        ]
    for r in ranking[:2]:
        r["som_swing_pct"] = 100.0
    sens["sensitivity_ranking"] = ranking
    sens["most_sensitive"] = ranking[0].get("parameter")
    (d / "sensitivity.json").write_text(json.dumps(sens))
    md = _compose_md_text(d)
    assert "Widest-Stressed Parameters (tied)" in md
    assert "Widest-stressed parameters:" in md


def test_report_does_not_claim_leverage(tmp_path: Path) -> None:
    """Positive assertion first, then absence — scoped to the sensitivity wording.

    Ranges are assigned by confidence class, not leverage, so 'most sensitive' cannot mean 'what
    the answer most depends on'. Asserting only the absence of phrases would pass on a no-op.
    """
    d = tmp_path / "ms-leverage"
    d.mkdir()
    _make_full_sizing_dir(d)
    md = _compose_md_text(d)
    assert "Widest-stressed parameter" in md or "Widest-Stressed Parameter" in md
    assert "Most sensitive parameter:" not in md
    assert "Most Sensitive Parameter |" not in md


def _fx_claim_dir(tmp_path: Path, *, declared: bool, name: str) -> Path:
    """A converted run whose deck claim sits close to the TAM *before* conversion.

    Reproduces the shape that shipped a self-contradicting report: raw delta +11.1% (inside the
    footnote band) against a converted delta of -72.2% (a mismatch warning) for one figure.
    """
    d = tmp_path / name
    d.mkdir()
    _make_full_sizing_dir(d)
    sizing = json.loads((d / "sizing.json").read_text())
    tam = _as_float(sizing["top_down"]["tam"]["value"])
    sizing["currency"] = "ILS"
    sizing["fx"] = {
        "as_of": "2026-08-01",
        "source": "s",
        "conversions": [
            {"field": "arpu", "from": "EUR", "to": "ILS", "rate": 4.0, "original_value": 1.0, "converted_value": 4.0}
        ],
    }
    (d / "sizing.json").write_text(json.dumps(sizing))
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["currency"] = "ILS"
    inputs["existing_claims"] = {"tam": round(tam * 0.9, 2)}
    if declared:
        inputs["existing_claims_currency"] = "EUR"
    else:
        inputs.pop("existing_claims_currency", None)
    (d / "inputs.json").write_text(json.dumps(inputs))
    return d


def test_fx_table_delta_matches_the_warning_delta(tmp_path: Path) -> None:
    """The comparison table and the mismatch warning must not disagree about one figure.

    Regression for a shipped defect: the table computed its delta from the RAW claim while the
    warning block computed it from the CONVERTED one, so a single report read "+11.1% *" in the
    table and "-72.2%" in the warnings. The footnote must not fire either.
    """
    d = _fx_claim_dir(tmp_path, declared=True, name="ms-fx-declared")
    md = _compose_md_text(d)
    tam_row = next(ln for ln in md.splitlines() if ln.startswith("| TAM (Top-down)"))
    assert "-72.2%" in tam_row, tam_row
    assert "+11.1%" not in tam_row, "table still using the unconverted claim"
    warn = next(ln for ln in md.splitlines() if "differs from deck claim" in ln)
    assert "-72.2%" in warn, warn
    assert "Agreement on a number is not independent confirmation" not in md


def test_fx_footnote_suppressed_when_claim_currency_undeclared(tmp_path: Path) -> None:
    """Undeclared claim currency: the pipeline refuses the comparison, so assert nothing."""
    d = _fx_claim_dir(tmp_path, declared=False, name="ms-fx-undeclared")
    md = _compose_md_text(d)
    assert "COMPARISON_CURRENCY_UNKNOWN" in _compose_codes(d)
    assert "Agreement on a number is not independent confirmation" not in md


# ---------------------------------------------------------------------------
# Convergence is not evidence: the producer note, the report label, and the
# checklist criterion all used to reward the two builds agreeing.
#
# Measured on 13 real runs: >=4 coaching sections presented that agreement as
# corroboration, one telling the founder to "say so directly in the room";
# exactly 1 got it right. The pipeline does not track where each input came
# from, so it cannot tell whether the builds are independent.
# ---------------------------------------------------------------------------


def _comparison_note(customer_count: int, arpu: int) -> dict[str, Any]:
    """Real producer output — not a hand-written note string.

    Existing fixtures hard-code `"Moderate discrepancy"`, so a test built on them would pass
    against the old text forever.
    """
    payload = {
        "approach": "both",
        "currency": "USD",
        "industry_total": 100e9,
        "segment_pct": 10,
        "share_pct": 5,
        "customer_count": customer_count,
        "arpu": arpu,
        "serviceable_pct": 60,
        "target_pct": 2,
    }
    rc, data, err = run_script("market_sizing.py", ["--stdin"], stdin_data=json.dumps(payload))
    assert rc == 0, err
    assert data is not None
    comp = data.get("comparison")
    return comp if isinstance(comp, dict) else {}


@pytest.mark.parametrize("cc,ar,band", [(5_000_000, 20_000, "converging"), (5_000_000, 24_000, "moderate")])
def test_convergence_note_does_not_claim_evidence(cc: int, ar: int, band: str) -> None:
    note = str(_comparison_note(cc, ar).get("note") or "")
    assert note, f"{band} band produced no note"
    # positive first — the note must say what it cannot conclude
    assert "Closeness is not confirmation" in note, note
    assert "rest on the same underlying figures" in note, note
    # then the retired reassurances
    assert "Good convergence" not in note
    assert "not alarming" not in note


def test_large_delta_branch_still_warns(cc: int = 50_000, ar: int = 18_000) -> None:
    """The >30% branch is a real warning and must survive untouched."""
    comp = _comparison_note(cc, ar)
    assert "Review assumptions" in str(comp.get("warning") or "")


def test_report_does_not_label_the_comparison_a_validation(tmp_path: Path) -> None:
    """`**Cross-validation:**` asserted the comparison validates something. Rendered 13/13."""
    d = tmp_path / "ms-xval"
    d.mkdir()
    _make_full_sizing_dir(d)
    md = _compose_md_text(d)
    assert "Top-down vs bottom-up:" in md  # positive first
    assert "Cross-validation:" not in md


def test_checklist_criterion_rewards_explanation_not_agreement() -> None:
    """Item 15 awarded a point for the two builds being close."""
    # Read the criterion from source rather than a CLI flag -- a skipped test is a vacuous test.
    src = (Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts" / "checklist.py").read_text()
    line = next(ln for ln in src.splitlines() if '"approaches_reconciled"' in ln)
    assert "explained" in line.lower(), line
    assert "reconciled" not in line.split('"label"')[1].lower(), line

    rubric = (
        Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "references" / "pitfalls-checklist.md"
    ).read_text()
    section = rubric.split("### `approaches_reconciled`")[1].split("###")[0]
    assert "Agreement is **not** a pass on its own" in section, section
    assert "within 30%" not in section, section


def test_blocked_comparison_keeps_the_row_and_prints_no_delta(tmp_path: Path) -> None:
    """A refused cross-check must not produce a delta — and must not delete the table.

    Two defects in one shape. The delta was computed against the RAW claim exactly when
    conversion was refused, so the table read "+11.1%" beside a warning saying the figure
    could not be cross-checked at all. And the row was gated on the delta, so suppressing
    the delta would have dropped the row, emptied `comparison_rows`, and taken the whole
    section — including the founder's own stated figure — out of the report.
    """
    d = _fx_claim_dir(tmp_path, declared=False, name="ms-fx-blocked-row")
    md = _compose_md_text(d)
    assert "### Deck Claims vs. Our Estimates" in md, "the blocked comparison deleted the whole section"
    tam_row = next(ln for ln in md.splitlines() if ln.startswith("| TAM (Top-down)"))
    assert "+11.1%" not in tam_row, f"delta computed across a refused comparison: {tam_row}"
    assert "|" in tam_row and "—" in tam_row, f"blocked row has no em-dash delta cell: {tam_row}"
    assert "90.0B" in tam_row, "the founder's own stated figure vanished from the row"
    # And it must NOT be stamped with the analysis currency: this row exists because we do not
    # know what currency the figure is in, so labelling it ILS contradicts the line below it.
    assert "90.0B ILS" not in tam_row, f"blocked row asserts a currency we just said is unknown: {tam_row}"
    assert "currency not stated" in tam_row, f"blocked row does not say the currency is unknown: {tam_row}"
    assert "could not compare the two figures" in md, "the em-dash is unexplained"
    # We cannot know the currencies DIFFER -- only that one was never stated.
    assert "are in different currencies" not in md, "asserts a currency fact the pipeline refuses to assert"
    assert "COMPARISON_CURRENCY_UNKNOWN" in _compose_codes(d)


def test_every_surface_prints_one_figure_for_the_deck_claim(tmp_path: Path) -> None:
    """The table, the mismatch note and the warning must agree — and carry the right currency.

    One report carried three figures for one field: 90.0B ILS in the note (raw claim),
    360.0B ILS in the table (converted), and `$360.0B` in the warning — a dollar sign on an
    ILS analysis, because validation runs before `_set_currency()`.
    """
    d = _fx_claim_dir(tmp_path, declared=True, name="ms-fx-one-figure")
    md = _compose_md_text(d)
    note = next(ln for ln in md.splitlines() if "differ significantly" in ln)
    warn = next(ln for ln in md.splitlines() if "differs from deck claim" in ln)
    tam_row = next(ln for ln in md.splitlines() if ln.startswith("| TAM (Top-down)"))
    for line, where in ((note, "note"), (warn, "warning"), (tam_row, "table")):
        assert "360.0B ILS" in line, f"{where} is not showing the converted claim: {line}"
        assert "$360.0B" not in line, f"{where} prints a dollar sign on an ILS analysis: {line}"


def test_methodology_never_claims_the_two_builds_validate_each_other(tmp_path: Path) -> None:
    """ "cross-validation" asserts an independence the pipeline cannot establish.

    The pipeline does not track where each input came from, so it cannot tell whether the
    two builds are independent — the reason the word is refused at the comparison note and
    in visualize.py. This was the last site, and it sat on the Methodology line a founder
    quotes into a deck footnote.
    """
    d = tmp_path / "ms-methodology"
    d.mkdir()
    _make_full_sizing_dir(d)
    md = _compose_md_text(d)
    assert "cross-validation" not in md.lower(), "report.md still claims the two approaches cross-validate each other"
    assert "## Methodology" in md


def test_a_non_positive_deck_claim_renders_no_row_and_no_currency_note(tmp_path: Path) -> None:
    """A zero claim has no delta for arithmetic reasons, not currency ones.

    Regression: the row gate moved off `delta_pct is not None` so a refused comparison would
    keep its row — but `_compute_delta` also returns None for a claim of zero, so a plain
    single-currency run rendered `$0.00 | —` under a note explaining that the two figures were
    in different currencies. There was no conversion anywhere in that run.
    """
    d = tmp_path / "ms-zero-claim"
    d.mkdir()
    _make_full_sizing_dir(d)
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["existing_claims"] = {"tam": 0}
    (d / "inputs.json").write_text(json.dumps(inputs))
    md = _compose_md_text(d)
    assert "$0.00" not in md, "a zero deck claim rendered as a comparison row"
    assert "could not compare the two figures" not in md, (
        "a currency explanation on a run with no currency conversion in it"
    )


# ---------------------------------------------------------------------------
# The checklist band. Three of the fleet's four checklists emit a 4-band score
# (strong/solid/needs_work/major_revision); market-sizing emitted a zero-defect boolean —
# "pass" iff nothing failed. So 21 of 22 passing and 1 of 22 passing were the same word,
# and the score_pct the producer already computes decided nothing.
#
# `all_pass` keeps the boolean, which is a real and separate fact: it is what the
# CHECKLIST_FAILURES warning keys on. The band says how good; the boolean says whether
# anything is outstanding. Conflating them is what cost the band.
# ---------------------------------------------------------------------------


def _checklist_summary(overrides: dict) -> dict:
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, err = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0, err
    assert data is not None
    summary: dict = data["summary"]
    return summary


def test_a_flawless_checklist_scores_strong_and_all_pass() -> None:
    s = _checklist_summary({})
    assert s["overall_status"] == "strong"
    assert s["all_pass"] is True
    assert s["score_pct"] == 100.0


def test_one_failure_out_of_twenty_two_is_still_strong_but_not_all_pass() -> None:
    """The case that proves the band and the boolean are independent, and the reason both
    are kept. 21/22 is 95.5% — a strong sizing with one outstanding item, which the old
    single word rendered as a flat "fail"."""
    s = _checklist_summary({"tam_matches_product_scope": {"status": "fail", "notes": "too broad"}})
    assert s["score_pct"] == 95.5
    assert s["overall_status"] == "strong"
    assert s["all_pass"] is False


def test_six_failures_land_in_solid() -> None:
    """16/22 = 72.7%, which is where the live run scored."""
    fail_ids = [item["id"] for item in _make_checklist_items()][:6]
    s = _checklist_summary({cid: {"status": "fail", "notes": "n"} for cid in fail_ids})
    assert s["score_pct"] == 72.7
    assert s["overall_status"] == "solid"
    assert s["all_pass"] is False


def test_the_band_uses_the_same_vocabulary_as_the_rest_of_the_fleet() -> None:
    fail_ids = [item["id"] for item in _make_checklist_items()]
    bands = set()
    for n in (0, 1, 6, 9, 14, 22):
        s = _checklist_summary({cid: {"status": "fail", "notes": "n"} for cid in fail_ids[:n]})
        bands.add(s["overall_status"])
    assert bands <= {"strong", "solid", "needs_work", "major_revision"}, bands
    assert len(bands) >= 3, f"the band never moves across 0..22 failures: {bands}"


# ---------------------------------------------------------------------------
# The checklist warning, split by whether a founder can act on it.
#
# `CHECKLIST_FAILURES` fired at HIGH for any failure at all, which had two costs. It made
# one outstanding item indistinguishable from twelve, and because ACCEPTIBLE_SEVERITIES is
# exactly {"medium"} it could never be accepted with a stated reason — so SKILL.md's advice
# for a high warning ("fix the underlying issue and re-run") was being given for a content
# finding, which is an instruction to re-run until a true finding disappears.
#
# Split on attainability, not on a ratio: 7 failures cap the score at 15/22 = 68.2%, below
# the 70 that "solid" requires, while 6 can still reach 72.7%. So above 6 the sizing cannot
# be called solid however the rest scores, and that is a different kind of statement.
# ---------------------------------------------------------------------------


def _checklist_artifact(fail_count: int) -> dict:
    ids = [item["id"] for item in _make_checklist_items()]
    failed = ids[:fail_count]
    art = dict(_VALID_CHECKLIST)
    applicable = 22
    art["summary"] = {
        "total": 22,
        "pass": applicable - fail_count,
        "fail": fail_count,
        "not_applicable": 0,
        "score_pct": round(((applicable - fail_count) / applicable) * 100, 1),
        "overall_status": "strong" if fail_count == 0 else "solid",
        "all_pass": fail_count == 0,
        "failed_items": [{"id": i, "category": "c", "label": i, "notes": "n"} for i in failed],
    }
    return art


def _compose_with_checklist(fail_count: int, methodology: dict | None = None) -> tuple[int, dict | None, str]:
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology or _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": _checklist_artifact(fail_count),
        }
    )
    return _run_compose(d)


def test_a_handful_of_failures_is_a_medium_content_finding() -> None:
    rc, data, _ = _compose_with_checklist(6)
    assert rc == 0
    assert data is not None
    warnings = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES"]
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "medium"
    assert "CHECKLIST_FAILURES_CRITICAL" not in _codes(data)


def test_past_the_attainability_threshold_it_becomes_critical() -> None:
    rc, data, _ = _compose_with_checklist(7)
    assert rc == 0
    assert data is not None
    critical = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES_CRITICAL"]
    assert len(critical) == 1
    assert critical[0]["severity"] == "high"


def test_the_two_checklist_warnings_are_mutually_exclusive() -> None:
    """Both firing would show a founder the same failures twice under two severities."""
    for fail_count in (1, 6, 7, 12):
        rc, data, _ = _compose_with_checklist(fail_count)
        assert rc == 0
        assert data is not None
        codes = _codes(data)
        assert not ("CHECKLIST_FAILURES" in codes and "CHECKLIST_FAILURES_CRITICAL" in codes), (
            f"both fired at {fail_count} failures"
        )


def test_a_clean_checklist_fires_neither() -> None:
    rc, data, _ = _compose_with_checklist(0)
    assert rc == 0
    assert data is not None
    codes = _codes(data)
    assert "CHECKLIST_FAILURES" not in codes
    assert "CHECKLIST_FAILURES_CRITICAL" not in codes


def test_the_trigger_reads_the_failure_count_not_the_band() -> None:
    """The warning used to key on `overall_status == "fail"`, a value the band change
    removes from the vocabulary. Left alone it would have become dead code and the warning
    would have stopped firing silently — the failure mode this whole split exists to avoid."""
    art = _checklist_artifact(3)
    art["summary"]["overall_status"] = "strong"  # a band that is not and never was "fail"
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": art,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "CHECKLIST_FAILURES" in _codes(data)


def test_a_content_finding_can_now_be_accepted_with_a_stated_reason() -> None:
    """The point of medium. ACCEPTIBLE_SEVERITIES is {"medium"}, so at high this could not
    be accepted at all and the only way past it was to re-run until it went away."""
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "CHECKLIST_FAILURES", "reason": "SOM share is deliberately conservative", "match": "failures"},
    ]
    rc, data, _ = _compose_with_checklist(2, methodology=methodology)
    assert rc == 0
    assert data is not None
    accepted = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES"]
    assert len(accepted) == 1
    assert accepted[0]["severity"] == "acknowledged", f"still blocking: {accepted}"
    assert "SOM share is deliberately conservative" in accepted[0]["message"]


def test_the_critical_half_can_never_be_accepted_away() -> None:
    methodology = dict(_VALID_METHODOLOGY)
    methodology["accepted_warnings"] = [
        {"code": "CHECKLIST_FAILURES_CRITICAL", "reason": "Trust me", "match": "failures"},
    ]
    rc, data, stderr = _compose_with_checklist(9, methodology=methodology)
    assert rc == 0
    assert data is not None
    critical = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES_CRITICAL"]
    assert len(critical) == 1
    assert critical[0]["severity"] == "high"
    assert "cannot accept" in stderr


def test_the_critical_split_follows_the_band_not_an_item_count() -> None:
    """The threshold was an absolute count derived on the assumption that all 22 criteria
    apply. With `not_applicable` items the applicable set shrinks and the count at which
    "cannot reach solid" begins drops with it — at 7 N/A it is 5, not 7.

    Measured: pass=10, fail=5, na=7 scores 66.7%, band `needs_work` — below solid — and
    fired the MEDIUM, acceptable warning, contradicting the rule the split states. The
    severity has to come from the band the score actually lands in.
    """
    art = dict(_VALID_CHECKLIST)
    art["summary"] = {
        "total": 22,
        "pass": 10,
        "fail": 5,
        "not_applicable": 7,
        "score_pct": 66.7,
        "overall_status": "needs_work",
        "all_pass": False,
        "failed_items": [{"id": f"i{n}", "category": "c", "label": f"i{n}", "notes": "n"} for n in range(5)],
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": art,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = _codes(data)
    assert "CHECKLIST_FAILURES_CRITICAL" in codes, (
        f"a sizing scoring below solid was filed as an acceptable content finding: {codes}"
    )
    assert "CHECKLIST_FAILURES" not in codes


def test_the_all_applicable_boundary_is_unchanged() -> None:
    """The band rule must reproduce the documented 6/7 boundary when nothing is N/A, or it
    is a different rule wearing the same justification."""
    rc6, d6, _ = _compose_with_checklist(6)
    assert rc6 == 0 and d6 is not None
    assert "CHECKLIST_FAILURES" in _codes(d6) and "CHECKLIST_FAILURES_CRITICAL" not in _codes(d6)
    rc7, d7, _ = _compose_with_checklist(7)
    assert rc7 == 0 and d7 is not None
    assert "CHECKLIST_FAILURES_CRITICAL" in _codes(d7)


def test_not_applicable_items_do_not_count_against_the_band() -> None:
    """The discriminating case, and the reason the previous test was not enough.

    pass=12, fail=3, na=7 is 12/15 = 80% — `solid`, so a medium content finding. Score it
    against all 22 instead and it reads 54.5% (`needs_work`) and fires the unacceptable
    warning on a sizing that is fine. Mutation-tested: hardcoding the denominator to 22
    left the other N/A test green, because that one is below solid under both readings.
    """
    art = dict(_VALID_CHECKLIST)
    art["summary"] = {
        "total": 22,
        "pass": 12,
        "fail": 3,
        "not_applicable": 7,
        "score_pct": 80.0,
        "overall_status": "solid",
        "all_pass": False,
        "failed_items": [{"id": f"i{n}", "category": "c", "label": f"i{n}", "notes": "n"} for n in range(3)],
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "sensitivity.json": _VALID_SENSITIVITY,
            "checklist.json": art,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = _codes(data)
    assert "CHECKLIST_FAILURES" in codes, f"a solid sizing lost its acceptable warning: {codes}"
    assert "CHECKLIST_FAILURES_CRITICAL" not in codes, f"N/A items were counted as failures against the band: {codes}"


def test_compose_flags_a_consumed_parameter_the_sensitivity_pass_never_varied() -> None:
    """The measured defect: `arpu` consumed by the math, absent from `ranges`, invisible everywhere.

    Nothing could see this class. UNSOURCED_ASSUMPTIONS checks only `agent_estimate` assumptions;
    FEW_SENSITIVITY_PARAMS fires below 3 scenarios and the real run had 6. The delivered report
    carried ten warnings and none about the single most commercially uncertain input in the model
    -- it was found by hand-diffing the base and ranges key sets.

    The grading detail is load-bearing: `arpu` was `category: sourced` with `confidence: medium`,
    and the tier system reads `category` and never `confidence`, which is how a corroborated-but-
    imprecise figure reached zero stress-testing.
    """
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sensitivity = json.loads(json.dumps(_VALID_SENSITIVITY))
    sensitivity["approach"] = "bottom_up"
    sensitivity["scenarios"] = [s for s in sensitivity["scenarios"] if s["parameter"] != "arpu"]
    validation = json.loads(json.dumps(_VALID_VALIDATION))
    validation["assumptions"] = [
        {"name": "customer_count", "value": 4500000, "category": "sourced", "confidence": "high"},
        {"name": "arpu", "value": 15000, "category": "sourced", "confidence": "medium"},
    ]
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": sizing,
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": sensitivity,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    omitted = [w for w in data["validation"]["warnings"] if w["code"] == "SENSITIVITY_OMITS_PARAM"]
    assert len(omitted) == 1, [w["message"] for w in data["validation"]["warnings"]]
    assert "ARPU" in omitted[0]["message"]
    assert omitted[0]["severity"] == "medium", "must stay acceptable via accepted_warnings"


def test_compose_exempts_only_a_high_confidence_sourced_omission() -> None:
    """The dispatch contract permits omitting a `sourced` figure whose source states no range.

    Honoured ONLY at `confidence: high`. No artifact records whether the source actually stated a
    range, so a blanket `sourced` exemption would have silently excused the very case this exists
    to catch -- the measured one was `sourced` at MEDIUM confidence.
    """
    for confidence, expect_warning in (("high", False), ("medium", True), ("low", True), (None, True)):
        sensitivity = json.loads(json.dumps(_VALID_SENSITIVITY))
        sensitivity["approach"] = "bottom_up"
        sensitivity["scenarios"] = [s for s in sensitivity["scenarios"] if s["parameter"] != "arpu"]
        assumption: dict[str, Any] = {"name": "arpu", "value": 15000, "category": "sourced"}
        if confidence is not None:
            assumption["confidence"] = confidence
        validation = json.loads(json.dumps(_VALID_VALIDATION))
        validation["assumptions"] = [assumption]
        d = _make_artifact_dir(
            {
                "inputs.json": _VALID_INPUTS,
                "methodology.json": _VALID_METHODOLOGY,
                "validation.json": validation,
                "sizing.json": _VALID_SIZING,
                "checklist.json": _VALID_CHECKLIST,
                "sensitivity.json": sensitivity,
            }
        )
        rc, data, _ = _run_compose(d)
        assert rc == 0 and data is not None
        fired = any(w["code"] == "SENSITIVITY_OMITS_PARAM" for w in data["validation"]["warnings"])
        assert fired is expect_warning, f"confidence={confidence!r} expected fired={expect_warning}"


def test_compose_does_not_flag_the_other_approachs_parameters() -> None:
    """A `both` sizing with a single-approach sensitivity run is legitimate.

    `sensitivity.py` drops the other approach's parameters as irrelevant, so comparing against
    every consumed parameter would flag three untestable ones on every such run -- a false
    positive this detector hit on its first draft, caught by the existing fixtures.
    """
    sensitivity = json.loads(json.dumps(_VALID_SENSITIVITY))
    sensitivity["approach"] = "bottom_up"
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,  # approach "both"
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": sensitivity,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0 and data is not None
    flagged = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "SENSITIVITY_OMITS_PARAM"]
    for td_param in ("Industry Total", "Segment", "Share"):
        assert not any(td_param in m for m in flagged), flagged


def test_compose_flags_a_scenario_whose_confidence_came_from_nowhere() -> None:
    """A parameter can be listed as stress-tested while nothing graded it.

    `sensitivity.py` falls back to `sourced` when neither the range nor `validation_confidence`
    supplies a tier, and `sourced` widens nothing — so the band the founder sees is whatever the
    caller wrote, presented alongside parameters whose bands a grade justifies. `confidence_source`
    exists to make the two distinguishable; this is the warning that uses it.
    """
    base = {"customer_count": 1000000, "arpu": 500, "serviceable_pct": 20, "target_pct": 2}
    payload = json.dumps(
        {
            "approach": "bottom_up",
            "base": base,
            "ranges": {
                "arpu": {"low_pct": -2, "high_pct": 2},  # no confidence, and none cross-referenced
                "customer_count": {"low_pct": -30, "high_pct": 30, "confidence": "derived"},
                "serviceable_pct": {"low_pct": -30, "high_pct": 30, "confidence": "derived"},
            },
        }
    )
    rc, sens, _ = run_script("sensitivity.py", ["--pretty"], stdin_data=payload)
    assert rc == 0 and sens is not None
    assert {s["parameter"]: s["confidence_source"] for s in sens["scenarios"]}["arpu"] == "default"

    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": sens,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0 and data is not None
    ungraded = [w for w in data["validation"]["warnings"] if w["code"] == "SENSITIVITY_DEFAULTED_CONFIDENCE"]
    assert len(ungraded) == 1, [w["message"] for w in data["validation"]["warnings"]]
    assert "ARPU" in ungraded[0]["message"]
    assert ungraded[0]["severity"] == "medium"


def test_compose_is_silent_when_every_scenario_is_graded() -> None:
    """The counter-test: a fully graded sensitivity pass must produce no ungraded warning."""
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
    rc, data, _ = _run_compose(d)
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "SENSITIVITY_DEFAULTED_CONFIDENCE"]


# === Task 1: the SAM/SOM comparison notes the producer computes and nothing rendered ===

# The producer's own wording, verbatim (market_sizing.py). Hoisted so the three fixtures below
# stay inside the line limit and cannot drift from each other.
_CAVEAT = (
    "Closeness is not confirmation: the pipeline cannot tell whether the two builds rest on "
    "the same underlying figures. Check whether they do."
)


def test_compose_renders_sam_and_som_comparison_notes() -> None:
    """The producer computes sam_note/som_note; the report used to drop them.

    Measured on a real run: a 9.4% SAM delta reached the founder ONLY through two LLM-written
    prose channels, both of which called it corroboration. The producer's own caveat for SAM was
    computed and never rendered — recorded as "shipped but INERT, zero consumers".
    """
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sizing["comparison"] = {
        "top_down_tam": 100.0,
        "bottom_up_tam": 100.0,
        "tam_delta_pct": 0.0,
        "note": f"TAM estimates differ by 0.0%. {_CAVEAT}",
        "top_down_sam": 10.0,
        "bottom_up_sam": 9.1,
        "sam_delta_pct": 9.4,
        "sam_note": f"SAM estimates differ by 9.4%. {_CAVEAT}",
        "top_down_som": 31.0,
        "bottom_up_som": 30.1,
        "som_delta_pct": 3.0,
        "som_note": f"SOM estimates differ by 3.0%. {_CAVEAT}",
    }
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": sizing,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    md = _compose_md_text(Path(_make_artifact_dir(arts)))
    para = [ln for ln in md.splitlines() if ln.startswith("**Top-down vs bottom-up:**")]
    assert len(para) == 1, md
    line = para[0]
    # Every metric's own finding is present...
    assert "TAM estimates differ by 0.0%." in line, line
    assert "SAM estimates differ by 9.4%." in line, line
    assert "SOM estimates differ by 3.0%." in line, line
    # ...the deltas lead, and the caveat they all share is said ONCE, at the end.
    assert line.index("SOM estimates differ") < line.index("Closeness is not confirmation"), line
    assert line.count("Closeness is not confirmation") == 1, line
    assert line.count("Check whether they do.") == 1, line


def test_compose_comparison_line_uses_warning_over_note_per_metric() -> None:
    """A >30% metric carries `<metric>_warning`, not `<metric>_note`; render whichever exists."""
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sizing["comparison"] = {
        "tam_delta_pct": 15.2,
        "note": f"TAM estimates differ by 15.2%. {_CAVEAT}",
        "sam_delta_pct": 58.0,
        "sam_warning": (
            "Top-down and bottom-up SAM differ by 58.0% (>30%). "
            "Review assumptions — one approach likely has a flawed input."
        ),
        "som_delta_pct": 3.0,
        "som_note": f"SOM estimates differ by 3.0%. {_CAVEAT}",
    }
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": sizing,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    md = _compose_md_text(Path(_make_artifact_dir(arts)))
    line = next(ln for ln in md.splitlines() if ln.startswith("**Top-down vs bottom-up:**"))
    # The >30% metric contributes its WARNING, not a note, and it leads like the others.
    assert "Top-down and bottom-up SAM differ by 58.0% (>30%)." in line, line
    assert "SOM estimates differ by 3.0%." in line, line
    # Its distinct advice survives; the caveat the other two share still appears once.
    assert "Review assumptions — one approach likely has a flawed input." in line, line
    assert line.count("Closeness is not confirmation") == 1, line


def test_compose_comparison_line_skips_a_metric_the_producer_did_not_compare() -> None:
    """A single-approach run has no sam/som delta keys — the line must not invent them."""
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sizing["comparison"] = {
        "tam_delta_pct": 4.0,
        "note": f"TAM estimates differ by 4.0%. {_CAVEAT}",
    }
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": sizing,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    md = _compose_md_text(Path(_make_artifact_dir(arts)))
    line = next(ln for ln in md.splitlines() if ln.startswith("**Top-down vs bottom-up:**"))
    assert "TAM estimates differ by 4.0%." in line, line
    assert "SAM estimates" not in line, line
    assert "SOM estimates" not in line, line


# === Task 2: inputs the two builds share BY VALUE ===


def _both_sizing(
    td_tam: float, sp: float, shp: float, cc: float, arpu: float, svc: float, tgt: float
) -> dict[str, Any]:
    """A `both`-mode sizing.json with the inputs spelled out, so identity checks can read them.

    _VALID_SIZING cannot serve: its bottom-up blocks carry no `serviceable_pct`/`target_pct` in
    `inputs`, so every paired-slot branch would be skipped and the silent tests below would pass
    without ever executing the code they exist to pin.
    """
    td_sam = td_tam * sp / 100
    bu_tam = cc * arpu
    bu_sam = cc * svc / 100 * arpu
    return {
        "approach": "both",
        "top_down": {
            "tam": {"value": td_tam, "formula": "industry_total", "inputs": {"industry_total": td_tam}},
            "sam": {
                "value": td_sam,
                "formula": "tam * segment_pct",
                "inputs": {"tam": td_tam, "segment_pct": sp},
            },
            "som": {
                "value": td_sam * shp / 100,
                "formula": "sam * share_pct",
                "inputs": {"sam": td_sam, "share_pct": shp},
            },
        },
        "bottom_up": {
            "tam": {
                "value": bu_tam,
                "formula": "customer_count * arpu",
                "inputs": {"customer_count": cc, "arpu": arpu},
            },
            "sam": {
                "value": bu_sam,
                "formula": "serviceable_customers * arpu",
                "inputs": {"serviceable_customers": cc * svc / 100, "serviceable_pct": svc, "arpu": arpu},
            },
            "som": {
                "value": cc * tgt / 100 * arpu,
                "formula": "target_customers * arpu",
                "inputs": {"target_customers": cc * tgt / 100, "target_pct": tgt, "arpu": arpu},
            },
        },
        "comparison": {"tam_delta_pct": 0.0, "note": f"TAM estimates differ by 0.0%. {_CAVEAT}"},
    }


def _compose_with_sizing(
    sizing: dict[str, Any],
    inputs: dict[str, Any] | None = None,
    methodology: dict[str, Any] | None = None,
    redteam: dict[str, Any] | None = None,
) -> tuple[int, dict | None, str]:
    arts = {
        "inputs.json": inputs or _VALID_INPUTS,
        "methodology.json": methodology or {**_VALID_METHODOLOGY, "approach_chosen": "both"},
        "validation.json": _VALID_VALIDATION,
        "sizing.json": sizing,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    if redteam is not None:
        arts["redteam.json"] = redteam
    d = _make_artifact_dir(arts)
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    return rc, data, d


def test_shared_tam_identity_fires_and_is_medium() -> None:
    """industry_total == customer_count * arpu exactly — the real run's 42.4M x 2,436."""
    rc, data, d = _compose_with_sizing(_both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_TAM_IDENTITY"]
    assert len(hits) == 1, [w["code"] for w in data["validation"]["warnings"]]
    assert hits[0]["severity"] == "medium"
    # Founder-facing prose, never a raw field name.
    assert "customer_count" not in hits[0]["message"] and "industry_total" not in hits[0]["message"]
    assert "Customer Count" in hits[0]["message"] and "ARPU" in hits[0]["message"]
    md = _compose_md_text(Path(d))
    exec_block = md.split("## Executive Summary")[1].split("\n## ")[0]
    assert "| TAM | $103.3B | Top-down † |" in exec_block, exec_block
    assert "| TAM | $103.3B | Bottom-up † |" in exec_block, exec_block
    assert "one computation, shown two ways" in exec_block.lower(), exec_block


def test_paired_slot_same_value_is_medium_and_separate() -> None:
    """segment_pct == serviceable_pct: the arm August cut for coverage, not for being wrong."""
    rc, data, _d = _compose_with_sizing(_both_sizing(100e9, 12.0, 2.0, 5e6, 15_000, 12.0, 1.0))
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "PAIRED_SLOT_SAME_VALUE"]
    assert len(hits) == 1 and hits[0]["severity"] == "medium", data["validation"]["warnings"]
    assert "Segment %" in hits[0]["message"] and "Serviceable %" in hits[0]["message"]
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_TAM_IDENTITY"]


def test_shared_input_checks_silent_on_independent_builds() -> None:
    """Must-not-trip: distinct TAM inputs, distinct narrowing, distinct capture."""
    rc, data, d = _compose_with_sizing(_both_sizing(100e9, 6.0, 5.0, 4.5e6, 15_000, 35.0, 0.5))
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SHARED_TAM_IDENTITY" not in codes and "PAIRED_SLOT_SAME_VALUE" not in codes, codes
    assert "one computation" not in _compose_md_text(Path(d))


def test_shared_tam_identity_is_an_identity_check_not_a_closeness_one() -> None:
    """4.0e6 x 25,000 = 1.0e11 against an industry_total of 100.5e9 — 0.5% apart, must NOT fire.

    Honest near-agreement is what the comparison caveat is for; this check is for exact identity.
    """
    rc, data, _d = _compose_with_sizing(_both_sizing(100.5e9, 6.0, 5.0, 4.0e6, 25_000, 35.0, 0.5))
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_TAM_IDENTITY"]


# === Task 4: a stated figure on a different horizon is not a mismatch ===


def _inputs_with_horizon(
    claims: dict[str, Any], horizons: dict[str, Any] | None, capture: int | None
) -> dict[str, Any]:
    # Annotated: _VALID_INPUTS narrows to Sequence[str] values, so the horizon dict and the
    # integer capture would both be assignment errors without it.
    inputs: dict[str, Any] = dict(_VALID_INPUTS)
    inputs["existing_claims"] = claims
    if horizons is not None:
        inputs["existing_claims_horizon_months"] = horizons
    if capture is not None:
        inputs["capture_horizon_months"] = capture
    return inputs


def test_horizon_mismatch_replaces_deck_claim_mismatch_for_som() -> None:
    """An 18-month plan SOM against a 60-month capture SOM is a different period, not the
    +564.9% understatement the real run reported."""
    inputs = _inputs_with_horizon(
        {"tam": None, "sam": None, "som": 4_660_000}, {"tam": None, "sam": None, "som": 18}, 60
    )
    rc, data, d = _compose_with_sizing(
        _both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32), inputs=inputs
    )
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "HORIZON_MISMATCH" in codes, codes
    assert "DECK_CLAIM_MISMATCH" not in codes, codes
    hm = [w for w in data["validation"]["warnings"] if w["code"] == "HORIZON_MISMATCH"]
    # Block 15 loops both approaches; the founder must not read the same sentence twice.
    assert len(hm) == 1, hm
    assert hm[0]["severity"] == "low"
    assert "18" in hm[0]["message"] and "60" in hm[0]["message"]
    md = _compose_md_text(Path(d))
    assert "+564.9%" not in md and "+545.4%" not in md
    assert "different horizon" in md.lower(), md


def test_horizon_mismatch_does_not_suppress_a_real_sam_finding() -> None:
    """SOM-scoped: capture_horizon_months describes what share_pct/target_pct represent, so a
    stated SAM horizon must not blank the SAM comparison — the one real deck finding on that run."""
    inputs = _inputs_with_horizon(
        {"tam": None, "sam": 37_300_000_000, "som": None}, {"tam": None, "sam": 12, "som": None}, 60
    )
    rc, data, _d = _compose_with_sizing(
        _both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32), inputs=inputs
    )
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "DECK_CLAIM_MISMATCH" in codes, codes
    assert "HORIZON_MISMATCH" not in codes, codes


def test_horizon_mismatch_absent_when_horizons_agree_or_unstated() -> None:
    """Opt-in and symmetrical: same period, or no period stated, both leave behaviour unchanged."""
    for horizons, capture in (({"tam": None, "sam": None, "som": 60}, 60), (None, None)):
        inputs = _inputs_with_horizon({"tam": None, "sam": None, "som": 4_660_000}, horizons, capture)
        rc, data, _d = _compose_with_sizing(
            _both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32), inputs=inputs
        )
        assert rc == 0 and data is not None
        codes = [w["code"] for w in data["validation"]["warnings"]]
        assert "HORIZON_MISMATCH" not in codes, (horizons, codes)
        assert "DECK_CLAIM_MISMATCH" in codes, (horizons, codes)


# === Task 3: hand the coach what the two builds share ===


def test_payload_approach_comparison_from_both_mode() -> None:
    rc, data, _d = _compose_with_sizing(_both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0 and data is not None
    ac = data["coaching_payload"]["approach_comparison"]
    assert ac["tam_delta_pct"] == 0.0
    assert ac["caveat"].startswith("Closeness is not confirmation")
    assert len(ac["shared_inputs"]) == 1, ac["shared_inputs"]
    item = ac["shared_inputs"][0]
    assert set(item) == {"metric", "detail"}, item
    assert item["metric"] == "tam"
    assert "one computation, shown two ways" in item["detail"]


def test_payload_approach_comparison_null_on_single_approach() -> None:
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sizing["approach"] = "bottom_up"
    sizing.pop("top_down")
    sizing.pop("comparison")
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": sizing,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    rc, data, _err = run_script("compose_report.py", ["--dir", _make_artifact_dir(arts)])
    assert rc == 0 and data is not None
    assert data["coaching_payload"]["approach_comparison"] is None


def test_caveat_stops_saying_cannot_tell_once_a_shared_figure_was_seen() -> None:
    """The producer's caveat is true only while nothing is itemized.

    Measured on the run that motivated the shared-figure check: the paragraph read "the pipeline
    cannot tell whether the two builds rest on the same underlying figures. Check whether they
    do. Your Industry Total equals Customer Count x ARPU exactly ..." -- a claim of blindness
    followed by the thing it had seen. All three surfaces that render the caveat must agree:
    report.md, report.html, and the coach's `caveat`.
    """
    rc, data, d = _compose_with_sizing(_both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    line = next(ln for ln in md.splitlines() if ln.startswith("**Top-down vs bottom-up:**"))
    assert "cannot tell" not in line, line
    assert "Check whether they do." not in line, line
    assert "Closeness is not confirmation" in line, line
    # The caveat INTRODUCES the shared list rather than sitting beside it.
    assert line.index("Closeness is not confirmation") < line.index("one computation, shown two ways"), line
    caveat = data["coaching_payload"]["approach_comparison"]["caveat"]
    assert caveat.startswith("Closeness is not confirmation") and "cannot tell" not in caveat, caveat
    # Same paragraph on the HTML surface -- a second renderer nobody reads is where this class
    # of defect survives.
    rc_html, html, _ = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0
    assert "cannot tell" not in html and "one computation, shown two ways" in html


def test_caveat_still_says_cannot_tell_when_nothing_is_shared() -> None:
    """The untouched branch: with no identity and no factor overlap, the producer's own words stand."""
    rc, data, d = _compose_with_sizing(_both_sizing(90_000_000_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    line = next(ln for ln in md.splitlines() if ln.startswith("**Top-down vs bottom-up:**"))
    assert _CAVEAT in line, line
    assert "cannot tell" in data["coaching_payload"]["approach_comparison"]["caveat"]


def test_payload_carries_no_internal_field_names() -> None:
    """A raw id in coaching_payload is a defect the fleet has already fixed once elsewhere.

    The coach echoes this payload into commentary a founder reads, so `kind`, `code` and every
    snake_case parameter name are stripped on the way in — only the humanized sentence crosses.
    """
    rc, data, _d = _compose_with_sizing(_both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0 and data is not None
    blob = json.dumps(data["coaching_payload"]["approach_comparison"])
    for token in ("industry_total", "customer_count", "segment_pct", "serviceable_pct", "identity", "code"):
        assert token not in blob, (token, blob)


# --- Task 5: factors[] on derived assumptions -------------------------------------------------
#
# Generic slugs throughout. The VALUES come from the debug pack's must-trip fixture; the names
# never do.
_FACTORS_TD = [
    {"factor_id": "has_adult_child", "value": 0.61, "source_id": "company_stated"},
    {"factor_id": "caregiver_employed", "value": 0.60, "source_id": "caregiving_survey_2025"},
    {"factor_id": "worker_benefit_access", "value": 0.61, "source_id": "labour_stats_2024"},
    {"factor_id": "fee_for_service_share", "value": 0.45, "source_id": "health_policy_2026"},
]


def _validation_with(assumptions: list[dict[str, Any]]) -> dict[str, Any]:
    v: dict[str, Any] = json.loads(json.dumps(_VALID_VALIDATION))
    v["assumptions"] = assumptions
    return v


def _compose_with_validation(validation: dict[str, Any]) -> tuple[int, dict | None, str]:
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": validation,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": _VALID_SENSITIVITY,
        }
    )
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    return rc, data, d


def test_factor_product_mismatch_fires_when_chain_does_not_reproduce_value() -> None:
    """0.61*0.60*0.61*0.45 = 10.047 percentage points, not 12."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 12.0, "category": "derived", "factors": _FACTORS_TD}])
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]
    assert len(hit) == 1 and hit[0]["severity"] == "medium", data["validation"]["warnings"]
    assert "10.0" in hit[0]["message"] and "12" in hit[0]["message"]
    # Founder-facing prose, never the raw parameter name.
    assert "segment_pct" not in hit[0]["message"] and "Segment %" in hit[0]["message"]


def test_factor_product_within_rounding_is_silent() -> None:
    """10.047 stated as 10.0 is how the real run rounds. Tolerance is 2% relative."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 10.0, "category": "derived", "factors": _FACTORS_TD}])
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]


def test_factor_product_on_absolute_assumption_uses_raw_product() -> None:
    """A non-percent assumption reconciles against the plain product, not x100."""
    rc, data, _d = _compose_with_validation(
        _validation_with(
            [
                {
                    "name": "customer_count",
                    "value": 42_372_000,
                    "category": "derived",
                    "factors": [
                        {"factor_id": "enrollees", "value": 64_200_000, "source_id": "health_policy_2026"},
                        {"factor_id": "two_plus_chronic", "value": 0.66, "source_id": "policy_paper_2023"},
                    ],
                }
            ]
        )
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]


def test_unstructured_derivation_is_low_and_reads_to_the_founder() -> None:
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 10.0, "category": "derived"}])
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "UNSTRUCTURED_DERIVATION"]
    assert len(hit) == 1 and hit[0]["severity"] == "low"
    assert "Segment %" in hit[0]["message"]
    # Founder-facing: no instruction addressed to a sub-agent, no raw field name.
    assert "List the factors" not in hit[0]["message"]
    assert "segment_pct" not in hit[0]["message"]


def test_unstructured_derivation_aggregates_to_one_warning_naming_every_figure() -> None:
    """One warning per run, not one per assumption — CHECKLIST_FAILURES is the precedent.

    Both forms report the same figures by name, so aggregating loses no signal; four
    near-identical paragraphs would crowd out the mediums beside them.
    """
    rc, data, _d = _compose_with_validation(
        _validation_with(
            [
                {"name": "industry_total", "value": 1.0e11, "category": "derived"},
                {"name": "segment_pct", "value": 10.0, "category": "derived"},
                {"name": "arpu", "value": 2436, "category": "derived"},
                {"name": "serviceable_pct", "value": 9.1, "category": "derived"},
                {"name": "customer_count", "value": 42_400_000, "category": "sourced"},
            ]
        )
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "UNSTRUCTURED_DERIVATION"]
    assert len(hit) == 1, [w["code"] for w in data["validation"]["warnings"]]
    for label in ("Industry Total", "Segment %", "ARPU", "Serviceable %"):
        assert label in hit[0]["message"], (label, hit[0]["message"])
    # The `sourced` assumption is not a derivation and must not be named.
    assert "Customer Count" not in hit[0]["message"]


def test_malformed_factors_is_unstructured_not_a_crash() -> None:
    for bad in (
        "0.61 x 0.60",
        [],
        [{"factor_id": "a", "value": "lots", "source_id": "s"}],
        [{"value": 0.5}],
        [{"factor_id": "a", "value": True, "source_id": "s"}],
        [{"factor_id": "a", "value": float("inf"), "source_id": "s"}],
    ):
        rc, data, _d = _compose_with_validation(
            _validation_with([{"name": "segment_pct", "value": 10.0, "category": "derived", "factors": bad}])
        )
        assert rc == 0 and data is not None, bad
        codes = [w["code"] for w in data["validation"]["warnings"]]
        assert "UNSTRUCTURED_DERIVATION" in codes and "FACTOR_PRODUCT_MISMATCH" not in codes, (bad, codes)


def test_report_md_prints_the_factor_chain_under_the_assumption() -> None:
    """The chain a founder can check, on the surface they read."""
    _rc, _data, d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 10.0, "category": "derived", "factors": _FACTORS_TD}])
    )
    md = _compose_md_text(Path(d))
    assert "0.61 × 0.6 × 0.61 × 0.45" in md, md


# --- Task 6: SHARED_FACTOR_OVERLAP ------------------------------------------------------------
_FACTORS_BU = [
    {"factor_id": "caregivers_per_recipient_composite", "value": 0.5513, "source_id": "caregiving_survey_2025"},
    {"factor_id": "caregiver_employed", "value": 0.60, "source_id": "caregiving_survey_2025"},
    {"factor_id": "worker_benefit_access", "value": 0.61, "source_id": "labour_stats_2024"},
    {"factor_id": "fee_for_service_share", "value": 0.45, "source_id": "health_policy_2026"},
]


def _compose_both_with_factors(
    td_factors: list[dict[str, Any]],
    bu_factors: list[dict[str, Any]],
    sp: float = 10.0,
    svc: float = 9.1,
) -> tuple[int, dict | None]:
    v = _validation_with(
        [
            {"name": "segment_pct", "value": sp, "category": "derived", "factors": td_factors},
            {"name": "serviceable_pct", "value": svc, "category": "derived", "factors": bu_factors},
        ]
    )
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": {**_VALID_METHODOLOGY, "approach_chosen": "both"},
        "validation.json": v,
        "sizing.json": _both_sizing(103_286_400_000, sp, 0.3, 42_400_000, 2436, svc, 0.32),
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    rc, data, _err = run_script("compose_report.py", ["--dir", _make_artifact_dir(arts)])
    return rc, data


def test_shared_factor_overlap_fires_on_three_of_four_identical_factors() -> None:
    """The motivating run: 0.60 x 0.61 x 0.45 on both sides.

    The reported "9.4% delta between two independent chains" is the substitution of one factor
    and nothing else. Value identity on the slot cannot see it — 10.0 and 9.1 are different
    numbers — which is exactly why the detector August cut would have stayed silent here.
    """
    rc, data = _compose_both_with_factors(_FACTORS_TD, _FACTORS_BU)
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_FACTOR_OVERLAP"]
    assert len(hit) == 1 and hit[0]["severity"] == "medium", data["validation"]["warnings"]
    assert "3 of the 4 figures" in hit[0]["message"], hit[0]["message"]
    assert "caregiver employed" in hit[0]["message"].lower()
    # The coach sees it, projected to the same two keys as every other shared input.
    ac = data["coaching_payload"]["approach_comparison"]
    sf = [s for s in ac["shared_inputs"] if s["metric"] == "sam"]
    assert len(sf) == 1 and set(sf[0]) == {"metric", "detail"}, sf


def test_shared_factor_overlap_silent_on_disjoint_chains() -> None:
    rc, data = _compose_both_with_factors(
        [
            {"factor_id": "a", "value": 0.5, "source_id": "s1"},
            {"factor_id": "b", "value": 0.2, "source_id": "s2"},
        ],
        [
            {"factor_id": "c", "value": 0.7, "source_id": "s3"},
            {"factor_id": "d", "value": 0.13, "source_id": "s4"},
        ],
        sp=10.0,
        svc=9.1,
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_FACTOR_OVERLAP"]


def test_shared_factor_matches_on_id_or_on_source_and_value() -> None:
    """The same figure under two ids is still the same figure — but only when the SOURCE agrees.

    Two coincidentally-equal fractions from DIFFERENT sources are not shared.
    """
    rc, data = _compose_both_with_factors(
        [
            {"factor_id": "employed", "value": 0.60, "source_id": "caregiving_survey_2025"},
            {"factor_id": "x", "value": 0.1667, "source_id": "s"},
        ],
        [
            {"factor_id": "caregiver_is_employed", "value": 0.60, "source_id": "caregiving_survey_2025"},
            {"factor_id": "y", "value": 0.1667, "source_id": "different_source"},
        ],
        sp=10.0,
        svc=10.0,
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "SHARED_FACTOR_OVERLAP"]
    assert len(hit) == 1 and "1 of the 2 figures" in hit[0]["message"], hit


def test_shared_factor_overlap_needs_both_chains() -> None:
    """One side itemized and the other not is UNSTRUCTURED, never an overlap claim."""
    v = _validation_with(
        [
            {"name": "segment_pct", "value": 10.0, "category": "derived", "factors": _FACTORS_TD},
            {"name": "serviceable_pct", "value": 9.1, "category": "derived"},
        ]
    )
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": {**_VALID_METHODOLOGY, "approach_chosen": "both"},
        "validation.json": v,
        "sizing.json": _both_sizing(103_286_400_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32),
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    rc, data, _err = run_script("compose_report.py", ["--dir", _make_artifact_dir(arts)])
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SHARED_FACTOR_OVERLAP" not in codes and "UNSTRUCTURED_DERIVATION" in codes, codes


# --- Task 7: red_team.py ----------------------------------------------------------------------
_GOOD_FINDING = {
    "claim_attacked": "segment_pct",
    "what_is_true": "The published share is 6.1%, not the 10% the analysis uses.",
    "evidence_quote": "Six point one percent of employers offered the benefit in 2025.",
    "source_url": "https://example.org/benefits-2025",
    "source_title": "Benefits Survey 2025",
    "severity": "high",
}


def _red_team(payload: dict[str, Any]) -> tuple[int, dict | None, str]:
    return run_script("red_team.py", [], stdin_data=json.dumps(payload))


def test_red_team_accepts_a_fully_evidenced_finding() -> None:
    rc, data, err = _red_team({"findings": [_GOOD_FINDING]})
    assert rc == 0 and data is not None, err
    assert data["summary"]["accepted"] == 1 and data["summary"]["rejected"] == 0
    assert data["findings"][0]["source_url"] == "https://example.org/benefits-2025"
    assert data["summary"]["by_severity"] == {"high": 1, "medium": 0, "low": 0}


def test_red_team_rejects_ONE_finding_and_keeps_the_rest() -> None:
    """Per-finding, never whole-payload.

    The rejected design discarded the entire hand-off when any finding named something absent
    from the artifacts — and every finding about what the analysis OMITTED is outside that
    vocabulary by construction, so it would have thrown away the most valuable findings.
    """
    rc, data, err = _red_team(
        {"findings": [_GOOD_FINDING, {"claim_attacked": "cost-sharing", "what_is_true": "seems high"}]}
    )
    assert rc == 0 and data is not None, err
    assert data["summary"]["accepted"] == 1 and data["summary"]["rejected"] == 1
    assert data["rejected"][0]["claim_attacked"] == "cost-sharing"
    assert "evidence_quote" in data["rejected"][0]["reason"]
    # The good one survived -- worded for the founder by the producer, never dropped.
    assert data["findings"][0]["claim_attacked"] == "Segment %"


def test_red_team_never_checks_claim_attacked_against_a_vocabulary() -> None:
    """A finding about what the analysis LEFT OUT has no parameter name, and is the most
    valuable shape this step produces. It must pass on its evidence alone."""
    rc, data, err = _red_team(
        {"findings": [{**_GOOD_FINDING, "claim_attacked": "cost-sharing is not modelled at all"}]}
    )
    assert rc == 0 and data is not None, err
    assert data["summary"]["accepted"] == 1, data["rejected"]


def test_red_team_keeps_a_correction_that_states_a_number() -> None:
    """The regex this replaced REFUSED exactly this shape — a source quoted to correct a misread.

    It also accepted two unsourced hedges that state numbers. The difference is not in the
    grammar, which is why the requirement is positive (carry a source) rather than negative.
    """
    rc, data, err = _red_team(
        {
            "findings": [
                {
                    **_GOOD_FINDING,
                    "what_is_true": "The recurring rate is actually $203 on n=17, not $66.",
                }
            ]
        }
    )
    assert rc == 0 and data is not None, err
    assert data["summary"]["accepted"] == 1, data["rejected"]


def test_red_team_rejects_a_finding_with_no_source_url() -> None:
    for bad_url in ("", "   ", "not-a-url", "example.org/x", "ftp://example.org/x"):
        rc, data, err = _red_team({"findings": [{**_GOOD_FINDING, "source_url": bad_url}]})
        assert rc == 0 and data is not None, err
        assert data["summary"]["accepted"] == 0 and data["summary"]["rejected"] == 1, bad_url


def test_red_team_rejects_an_unknown_severity() -> None:
    rc, data, err = _red_team({"findings": [{**_GOOD_FINDING, "severity": "critical"}]})
    assert rc == 0 and data is not None, err
    assert data["summary"]["rejected"] == 1
    assert "severity" in data["rejected"][0]["reason"]


def test_red_team_finding_nothing_is_a_valid_result_not_an_error() -> None:
    """A red team that always finds three things is a red team nobody believes, and making zero
    findings an error is how a step learns to manufacture them."""
    rc, data, err = _red_team({"findings": []})
    assert rc == 0 and data is not None, err
    assert data["validation"]["status"] == "valid"
    assert data["summary"]["accepted"] == 0 and data["summary"]["rejected"] == 0


def test_red_team_carries_what_it_could_not_check() -> None:
    """An unchecked claim presented as checked is the defect the whole skill exists to avoid."""
    rc, data, err = _red_team(
        {
            "findings": [],
            "could_not_check": ["The data-room deck, because the PDF has no text layer", "  ", ""],
        }
    )
    assert rc == 0 and data is not None, err
    assert data["could_not_check"] == ["The data-room deck, because the PDF has no text layer"]
    assert data["summary"]["unchecked"] == 1


def test_red_team_survives_a_malformed_findings_entry() -> None:
    rc, data, err = _red_team({"findings": ["a string", None, 7, _GOOD_FINDING]})
    assert rc == 0 and data is not None, err
    assert data["summary"]["accepted"] == 1 and data["summary"]["rejected"] == 3
    assert all(r["claim_attacked"] == "(unnamed)" for r in data["rejected"])


def _compose_with_redteam(redteam: dict[str, Any] | None) -> tuple[int, dict | None, str]:
    arts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    if redteam is not None:
        arts["redteam.json"] = redteam
    d = _make_artifact_dir(arts)
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    return rc, data, d


_REDTEAM_ARTIFACT: dict[str, Any] = {
    "findings": [
        {
            "claim_attacked": "segment_pct",
            "what_is_true": "The published share is 6.1%, not the 10% the analysis uses.",
            "evidence_quote": "Six point one percent of employers offered the benefit in 2025.",
            "source_url": "https://example.org/benefits-2025",
            "source_title": "Benefits Survey 2025",
            "severity": "high",
        }
    ],
    "rejected": [{"claim_attacked": "cost-sharing", "reason": "missing or empty: source_url"}],
    "could_not_check": ["The data-room deck, because the PDF has no text layer"],
    "summary": {"accepted": 1, "rejected": 1, "unchecked": 1, "by_severity": {"high": 1, "medium": 0, "low": 0}},
    "validation": {"status": "valid", "errors": []},
}


def test_report_md_carries_the_adversarial_findings_with_their_sources() -> None:
    """A finding with a source reaches report.md — the disclosure, not the judgement."""
    rc, _data, d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0
    md = _compose_md_text(Path(d))
    assert "## Adversarial Findings" in md
    assert "Six point one percent of employers offered the benefit in 2025." in md
    assert "https://example.org/benefits-2025" in md
    # Founder-facing: the internal parameter name is humanized.
    assert "segment_pct" not in md.split("## Adversarial Findings")[1].split("\n## ")[0]


def test_report_md_surfaces_what_the_red_team_could_not_check() -> None:
    rc, _data, d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "no text layer" in section, section


def test_a_dropped_finding_is_disclosed_not_silently_discarded() -> None:
    """A finding set aside for lack of evidence must still be COUNTED where the founder sees it.

    Silence here would make a red team that filed five findings and kept one look like a red
    team that found one.
    """
    rc, data, d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "RED_TEAM_FINDINGS_DROPPED"]
    assert len(hits) == 1 and hits[0]["severity"] == "low", data["validation"]["warnings"]
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "1" in section


def test_red_team_findings_raise_a_warning_the_founder_cannot_miss() -> None:
    rc, data, _d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "RED_TEAM_FINDINGS"]
    assert len(hits) == 1 and hits[0]["severity"] == "medium"
    assert "outside" in hits[0]["message"] or "challenge" in hits[0]["message"].lower()


def test_an_empty_red_team_is_reported_as_having_run_and_found_nothing() -> None:
    """Ran-and-found-nothing and never-ran are different facts and must read differently."""
    rc, data, d = _compose_with_redteam(
        {
            "findings": [],
            "rejected": [],
            "could_not_check": [],
            "summary": {"accepted": 0, "rejected": 0, "unchecked": 0},
            "validation": {"status": "valid", "errors": []},
        }
    )
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "RED_TEAM_FINDINGS" not in codes and "MISSING_OPTIONAL_ARTIFACT" not in codes
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "nothing" in section.lower()


def test_no_red_team_artifact_says_so_rather_than_omitting_the_section() -> None:
    rc, data, d = _compose_with_redteam(None)
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "MISSING_OPTIONAL_ARTIFACT"]
    assert len(hits) == 1 and hits[0]["severity"] == "low"
    # Disclosure, never a filename.
    assert "redteam" not in hits[0]["message"] and ".json" not in hits[0]["message"]


def test_red_team_claim_never_reaches_the_coach_as_a_raw_field_name() -> None:
    """`claim_attacked` is free text and is routinely a bare parameter name — the agent body
    invites it. The coach echoes this payload into prose a founder reads, so it is humanized
    here exactly as the renderer humanizes it. Caught by reading a paid run's payload, where
    the field happened to be null and the defect was one real finding away from shipping."""
    rc, data, _d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    blob = json.dumps(data["coaching_payload"]["red_team_findings"])
    assert "segment_pct" not in blob, blob
    assert "Segment %" in blob, blob


def test_red_team_findings_reach_the_coaching_payload() -> None:
    rc, data, _d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    rt = data["coaching_payload"]["red_team_findings"]
    assert rt is not None and len(rt["findings"]) == 1
    assert rt["findings"][0]["source_url"] == "https://example.org/benefits-2025"
    assert rt["dropped"] == 1 and rt["unchecked"] == 1


# --- Task 7: the adversarial-review gate ------------------------------------------------------
def _compose_gated(
    redteam: dict[str, Any] | None = None,
    skip_reason: Any = "__omit__",
    redteam_run_id: str | None = None,
) -> tuple[int, dict | None, str]:
    """Compose with an explicit red-team state. Returns (rc, data, dir)."""
    methodology = dict(_VALID_METHODOLOGY)
    # The shared fixture records a decision so the other ~350 compose tests are not all gate
    # tests. These ARE gate tests, so the default here is the opposite: no decision at all.
    methodology.pop("red_team_skipped", None)
    if skip_reason != "__omit__":
        methodology["red_team_skipped"] = skip_reason
    arts: dict[str, Any] = {
        "inputs.json": {**_VALID_INPUTS, "metadata": {"run_id": "20260101T000000Z"}},
        "methodology.json": {**methodology, "metadata": {"run_id": "20260101T000000Z"}},
        "validation.json": {**_VALID_VALIDATION, "metadata": {"run_id": "20260101T000000Z"}},
        "sizing.json": {**_VALID_SIZING, "metadata": {"run_id": "20260101T000000Z"}},
        "checklist.json": {**_VALID_CHECKLIST, "metadata": {"run_id": "20260101T000000Z"}},
        "sensitivity.json": {**_VALID_SENSITIVITY, "metadata": {"run_id": "20260101T000000Z"}},
    }
    if redteam is not None:
        arts["redteam.json"] = {**redteam, "metadata": {"run_id": redteam_run_id or "20260101T000000Z"}}
    d = _make_artifact_dir(arts)
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    return rc, data, d


def test_compose_refuses_when_nobody_decided_about_the_adversarial_review() -> None:
    """Silence is not a third option.

    Measured cause: the step shipped as "optional" with a low-severity disclosure as its only
    downstream consumer, and a live paid run skipped it outright. Severity cannot fix this —
    Step 7 runs compose without --strict, so even `high` halts nothing. Only a non-zero exit
    reaches SKILL.md's stop-and-report branch.
    """
    rc, data, _d = _compose_gated()
    assert rc != 0, "compose must REFUSE, not warn, when no decision was recorded"
    assert data is not None
    errs = " ".join(data["validation"]["errors"])
    assert "no decision to skip one was recorded" in errs, errs
    # The refusal names the way forward.
    assert "red_team_skipped" in errs and "founder_declined" in errs


def test_compose_refuses_a_skip_reason_outside_the_enum() -> None:
    """Free text would let the agent write a rationalization that reads like a reason."""
    rc, data, _d = _compose_gated(skip_reason="not needed for this analysis")
    assert rc != 0
    assert data is not None
    errs = " ".join(data["validation"]["errors"])
    assert "not a recognised reason" in errs, errs


def test_compose_leaves_report_md_untouched_when_it_refuses() -> None:
    """A stub over the canonical report is worse than writing nothing."""
    _rc, _data, d = _compose_gated(redteam=_REDTEAM_ARTIFACT)
    md = Path(d) / "report.md"
    md.write_text("PRIOR GOOD REPORT", encoding="utf-8")
    rc, _data2, _err = run_script("compose_report.py", ["--dir", d, "--write-md", str(md)])
    assert rc == 0
    # Now remove the decision and re-run: the refusal must not clobber it.
    (Path(d) / "redteam.json").unlink()
    good = md.read_text(encoding="utf-8")
    rc2, _d2, _e2 = run_script("compose_report.py", ["--dir", d, "--write-md", str(md)])
    assert rc2 != 0
    assert md.read_text(encoding="utf-8") == good, "the refusal clobbered the prior good report"


@pytest.mark.parametrize(
    "reason,marker",
    [
        ("founder_declined", "you asked us not to"),
        ("dispatch_failed", "attempted and did not complete"),
        ("no_network_available", "no access to outside sources"),
    ],
)
def test_each_recorded_reason_reads_differently_to_the_founder(reason: str, marker: str) -> None:
    """A decision and a failure are different disclosures; collapsing them is what hid the skip."""
    rc, data, d = _compose_gated(skip_reason=reason)
    assert rc == 0, data
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert marker in section, section


def test_a_stale_redteam_artifact_does_not_satisfy_the_gate() -> None:
    """Parity, not presence. A redteam.json from an earlier analysis of the same company
    describes different figures entirely — deck-review's reconciliation gate carries this rule
    for the same reason."""
    rc, data, _d = _compose_gated(redteam=_REDTEAM_ARTIFACT, redteam_run_id="20250101T000000Z")
    assert rc != 0, "a stale findings artifact satisfied an existence check"
    assert data is not None


def test_a_fresh_redteam_artifact_satisfies_the_gate() -> None:
    rc, data, _d = _compose_gated(redteam=_REDTEAM_ARTIFACT)
    assert rc == 0, data
    assert data is not None
    assert data["coaching_payload"]["red_team_findings"] is not None


def test_a_prose_claim_is_not_title_cased_into_nonsense() -> None:
    """`claim_attacked` is free text and is usually a sentence, not a parameter name.

    Caught on a live run, not by a unit test: every fixture here says `claim_attacked:
    "segment_pct"`, which is the one shape `_humanize_param` handles. A real agent wrote
    "...top-down SAM of $60M from a $3B TAM" and the report rendered "Top-Down Sam Of $60M From
    A $3B Tam" — Title-Casing the sentence and downcasing the two acronyms the skill is about.
    """
    prose = "segment_pct = 2% used to derive top-down SAM of $60M from a $3B TAM"
    rc, data, d = _compose_with_redteam(
        {**_REDTEAM_ARTIFACT, "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "claim_attacked": prose}]}
    )
    assert rc == 0 and data is not None
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "SAM" in section and "TAM" in section, section
    assert "Sam Of" not in section and "$3B Tam" not in section, section
    # The payload the coach reads gets the same treatment.
    assert "SAM" in json.dumps(data["coaching_payload"]["red_team_findings"])


def test_a_token_embedded_in_a_prose_claim_is_humanized_in_place() -> None:
    """Measured on the e2e lane with the hook: the verdict a founder read FIRST said
    "The most serious: existing_claims.tam = $3.2B — recorded from the founder's message…", and
    the shared founder-text scan did not fire — it skips `word.word` by design (URLs, filenames).
    The model's own rewrite of that sentence was more readable than ours, which is the wrong way
    round. Each embedded token becomes its label or its words; the sentence stays the agent's."""
    prose = "existing_claims.tam = $3.2B — recorded from the founder's message as a TAM figure their deck states"
    rc, data, d = _compose_with_redteam(
        {
            **_REDTEAM_ARTIFACT,
            "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "claim_attacked": prose, "severity": "high"}],
        }
    )
    assert rc == 0 and data is not None
    assert "existing_claims" not in data["verdict"], data["verdict"]
    assert "the TAM your materials state = $3.2B" in data["verdict"], data["verdict"]
    md = _compose_md_text(Path(d))
    assert "existing_claims" not in md.split("## Adversarial Findings")[1].split("\n## ")[0]
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert "existing_claims" not in html_text and "the TAM your materials state" in html_text
    # A filename inside a claim is left for the founder-text scan to name, not mangled into words.
    rc2, data2, _ = _compose_with_redteam(
        {**_REDTEAM_ARTIFACT, "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "claim_attacked": "see notes_v2.json"}]}
    )
    assert data2 is not None and "notes_v2.json" in json.dumps(data2["coaching_payload"]["red_team_findings"])


def test_a_bare_parameter_name_is_still_humanized() -> None:
    """The other half of the same rule — a real parameter name must not reach a founder raw."""
    rc, data, d = _compose_with_redteam(_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "Segment %" in section and "segment_pct" not in section, section


def test_a_rationale_passes_through_verbatim_while_compose_labels_stay_clean() -> None:
    """The SPLIT that the paid lane's whole-file assert could not express.

    `methodology.rationale` is free text the model writes and compose renders verbatim. The
    existing guards at :6081 and :6150 are non-vacuous for compose's OWN labels but have never
    exercised this channel — their fixture rationale is the four-word "Both data sources
    available", so a word arriving through the rationale was untested until a paid run hit it.

    Two things are asserted together because only their conjunction is the contract: what the
    model wrote reaches the founder unedited (compose does not silently rewrite a founder-facing
    field), AND compose's own vocabulary is unaffected by it. A scan that forbade the word
    anywhere in report.md conflated those, and gated a release on a model's word choice.
    """
    loaded = "Both approaches are used for cross-validation of the deck's TAM claim."
    methodology = {**_VALID_METHODOLOGY, "approach_chosen": "both", "rationale": loaded}
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": methodology,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": _VALID_CHECKLIST,
            "sensitivity.json": _VALID_SENSITIVITY,
        }
    )
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))

    # 1. Verbatim. Compose must not edit a founder-facing field the model authored.
    assert loaded in md, "compose altered the rationale it was given"

    # 2. Compose's own labels are clean regardless of what the rationale said.
    assert "**Cross-validation:**" not in md
    approach_line = next(ln for ln in md.splitlines() if ln.startswith("**Approach:**"))
    assert "cross-validation" not in approach_line.lower(), approach_line


def test_the_methodology_reference_does_not_teach_the_word_compose_refuses() -> None:
    """The reference the model reads before writing `rationale` must not prescribe the term.

    Measured cause: a live run transcribed the schema example almost verbatim, and across the
    deduplicated live-run corpus roughly a third of rationales carry the exact spelling. A
    producer that refuses a word its own reference material prescribes is teaching one thing
    and grading another.
    """
    refs = Path(__file__).resolve().parent.parent / "skills" / "market-sizing" / "references"
    for name in ("artifact-schemas.md", "tam-sam-som-methodology.md"):
        text = (refs / name).read_text(encoding="utf-8")
        assert "cross-validation" not in text.lower(), (
            f"{name} still teaches the exact term compose refuses in its own labels"
        )


def test_checklist_failures_are_listed_as_prose_not_as_a_python_list() -> None:
    """`['source segments match', 'figures triangulated']` is a repr, not a sentence.

    Found by reading a replayed report by eye, which is the only thing that finds this class:
    the ids are already humanized, so the founder-text scan sees nothing wrong, and every
    assertion about this warning matched on the count or a substring rather than the shape.
    A founder reads the brackets and quotes as a glitch, on the line telling them what failed.
    """
    failing = {
        "items": [
            {"id": "source_segments_match", "status": "fail", "notes": "x"},
            {"id": "figures_triangulated", "status": "fail", "notes": "y"},
        ]
        + [{"id": f"filler_{i}", "status": "pass", "notes": None} for i in range(20)],
        "summary": {
            "score_pct": 90.9,
            "pass": 20,
            "fail": 2,
            "overall_status": "solid",
            "all_pass": False,
            # The warning reads `failed_items`, not the items array — a fixture that sets only
            # the latter renders "2 failures: " with nothing after the colon.
            "failed_items": [{"id": "source segments match"}, {"id": "figures triangulated"}],
        },
    }
    d = _make_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "methodology.json": _VALID_METHODOLOGY,
            "validation.json": _VALID_VALIDATION,
            "sizing.json": _VALID_SIZING,
            "checklist.json": failing,
            "sensitivity.json": _VALID_SENSITIVITY,
        }
    )
    rc, data, _err = run_script("compose_report.py", ["--dir", d])
    assert rc == 0 and data is not None
    hits = [w for w in data["validation"]["warnings"] if w["code"].startswith("CHECKLIST_FAILURES")]
    assert hits, [w["code"] for w in data["validation"]["warnings"]]
    for w in hits:
        msg = w["message"]
        for glyph in ("[", "]", "'"):
            assert glyph not in msg, (glyph, msg)
        assert "source segments match, figures triangulated" in msg, msg


# --- 2.4: a finding grounded in the run's own output ------------------------------------------
_INTERNAL_FINDING = {
    "claim_attacked": "TAM convergence at ~$45M is presented as validation",
    "what_is_true": "The two builds share an ARPU anchor, so a 0.7% delta is not independence.",
    "evidence_quote": "Top-down and bottom-up SOM differ by 67.3% (>30%).",
    "source_url": "internal:analysis",
    "source_title": "This analysis' own comparison",
    "severity": "medium",
}


def test_a_finding_from_the_runs_own_output_is_accepted_and_labelled_not_linked() -> None:
    """A finding can be grounded in the analysis itself, and saying so must be possible.

    Run 4 produced exactly this shape — the red team quoted the run's OWN comparison note back
    at it — and, with only http(s) allowed, attached an unrelated external URL to carry it. The
    founder-facing promise of this step is that every finding carries the sentence it relies on;
    a link that does not contain the quote breaks that quietly.
    """
    rc, data, d = _compose_with_redteam({**_REDTEAM_ARTIFACT, "findings": [_INTERNAL_FINDING]})
    assert rc == 0 and data is not None
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "Top-down and bottom-up SOM differ by 67.3%" in section
    # Labelled as internal, never rendered as a clickable link to nowhere.
    assert "internal:analysis" not in section, section
    assert "(internal" not in section and "](" not in section.split("**Not checked**")[0], section
    assert "from this analysis" in section.lower(), section


def test_an_internal_finding_is_distinguishable_from_an_externally_sourced_one() -> None:
    """Different kinds of evidence, and the founder has to be able to tell which is which.

    An outside source contradicting a figure and the analysis contradicting itself are both
    worth knowing and are not interchangeable — one is corroboration from elsewhere, the other
    is an internal inconsistency with no outside check at all.
    """
    rc, _data, d = _compose_with_redteam(
        {**_REDTEAM_ARTIFACT, "findings": [_INTERNAL_FINDING, _REDTEAM_ARTIFACT["findings"][0]]}
    )
    assert rc == 0
    section = _compose_md_text(Path(d)).split("## Adversarial Findings")[1].split("\n## ")[0]
    assert "https://example.org/benefits-2025" in section, "the external finding lost its link"
    assert "from this analysis" in section.lower(), "the internal finding lost its label"


def test_internal_is_the_only_non_web_provenance_accepted() -> None:
    """A closed value, for the same reason the skip reason is closed: an open one lets a finding
    claim a provenance nobody can check, which is what this field exists to prevent."""
    for bad in ("internal", "internal:", "internal:whatever", "file:///etc/passwd", "INTERNAL:ANALYSIS"):
        rc, data, _err = _red_team({"findings": [{**_INTERNAL_FINDING, "source_url": bad}]})
        assert rc == 0 and data is not None, bad
        assert data["summary"]["accepted"] == 0, (bad, data["findings"])


def test_internal_provenance_survives_the_producer() -> None:
    rc, data, _err = _red_team({"findings": [_INTERNAL_FINDING]})
    assert rc == 0 and data is not None
    assert data["summary"]["accepted"] == 1, data["rejected"]
    assert data["findings"][0]["source_url"] == "internal:analysis"


# === dispatch_prompt.py: the red-team prompt is generated, documents first, with no target list ===


def _dispatch(args: list[str]) -> tuple[int, str, str]:
    return run_script_raw("dispatch_prompt.py", args)


def _analysis_dir(tmp_path: Path) -> Path:
    a = tmp_path / "analysis"
    a.mkdir()
    for f in ("inputs.json", "sizing.json", "validation.json"):
        (a / f).write_text("{}")
    return a


def test_dispatch_prompt_lists_documents_before_artifacts_and_no_targets(tmp_path: Path) -> None:
    """Documents first, so the red team writes down what the page says before it reads the analysis's
    reading of it; and no slot for a hypothesis list -- the live run's hand-written prompt carried one
    and every finding came off it. Paths are RENDERED in the agent's namespace and CHECKED in the
    caller's: a sub-agent's read of a /sessions path is denied on Cowork."""
    a = _analysis_dir(tmp_path)
    h = tmp_path / "handoff"
    (h / "docs").mkdir(parents=True)
    (h / "ocr").mkdir()
    (h / "docs" / "deck.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (h / "docs" / "notes.md").write_text("# notes")
    (h / "docs" / ".DS_Store").write_bytes(b"\0")
    (h / "ocr" / "deck.pdf.p2.txt").write_text("n=17")
    (h / "ocr" / "deck.pdf.p10.txt").write_text("page ten")
    rc, out, err = _dispatch(
        [
            "red_team",
            "--run-id",
            "20260101T000000Z",
            "--analysis-dir",
            str(a),
            "--handoff-dir",
            str(h),
            "--analysis-dir-agent",
            "artifacts/market-sizing-co",
            "--handoff-agent",
            "artifacts/market-sizing-co/handoff/20260101T000000Z",
        ]
    )
    assert rc == 0, err
    head = "CONTEXT: RED_TEAM\nOUTPUT_PATH: artifacts/market-sizing-co/handoff/20260101T000000Z/redteam_output.json\n"
    assert out.startswith(head + "RUN_ID: 20260101T000000Z\n")
    assert "  artifacts/market-sizing-co/handoff/20260101T000000Z/docs/deck.pdf" in out
    assert "  artifacts/market-sizing-co/inputs.json" in out
    assert str(tmp_path) not in out, "a caller-namespace path reached the sub-agent"
    assert out.index("/docs/deck.pdf") < out.index("/inputs.json")
    # sidecars listed beside their document, in page order (10 after 2, not before)
    assert out.index("/ocr/deck.pdf.p2.txt") < out.index("/ocr/deck.pdf.p10.txt")
    assert ".DS_Store" not in out
    assert "worth attacking" not in out and "Key things" not in out
    assert "before you open any of the analysis's artifacts" in out


def test_dispatch_prompt_renders_the_real_path_when_no_agent_form_is_given(tmp_path: Path) -> None:
    a = _analysis_dir(tmp_path)
    h = tmp_path / "handoff"
    h.mkdir()
    rc, out, _ = _dispatch(
        ["red_team", "--run-id", "x", "--analysis-dir", str(a), "--handoff-dir", str(h), "--handoff-agent", str(h)]
    )
    assert rc == 0
    assert f"  {a}/inputs.json" in out
    assert "The founder supplied no documents" in out


def test_dispatch_prompt_is_deterministic(tmp_path: Path) -> None:
    a = _analysis_dir(tmp_path)
    args = [
        "red_team",
        "--run-id",
        "x",
        "--analysis-dir",
        str(a),
        "--handoff-dir",
        str(tmp_path),
        "--handoff-agent",
        "/h",
    ]
    assert _dispatch(args)[1] == _dispatch(args)[1]


def test_dispatch_prompt_refuses_missing_artifact(tmp_path: Path) -> None:
    a = tmp_path / "analysis"
    a.mkdir()
    (a / "inputs.json").write_text("{}")
    rc, _, err = _dispatch(
        ["red_team", "--run-id", "x", "--analysis-dir", str(a), "--handoff-dir", str(tmp_path), "--handoff-agent", "/h"]
    )
    assert rc == 2 and "sizing.json" in err


# === ocr_uploads.py: a text sidecar per scanned page, degrading to "unavailable" without binaries ===

_SCANNED_DECK = Path(FOUNDER_SKILLS_DIR) / "tests" / "fixtures" / "market-sizing" / "synthetic-deck-scanned.pdf"


def test_ocr_uploads_degrades_to_available_false_without_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # no pdftoppm / tesseract reachable
    u = tmp_path / "u"
    u.mkdir()
    (u / "deck.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    rc, data, _ = run_script("ocr_uploads.py", ["--uploads-dir", str(u), "--out", str(tmp_path / "o")])
    assert rc == 0
    assert data == {"ok": True, "ocr_available": False, "pages_written": 0, "skipped": ["deck.pdf"], "documents": {}}
    # The receipt is written even so: "OCR ran and could not" and "OCR never ran" must read differently
    # to dispatch_prompt.py, which refuses the second.
    receipt = json.loads((tmp_path / "o" / "receipt.json").read_text())
    assert receipt["ocr_available"] is False and receipt["complete"] is True
    assert not list((tmp_path / "o").glob("*.txt"))


@pytest.mark.skipif(shutil.which("tesseract") is None or shutil.which("pdftoppm") is None, reason="OCR binaries absent")
def test_ocr_uploads_writes_one_sidecar_per_scanned_page(tmp_path: Path) -> None:
    u = tmp_path / "u"
    u.mkdir()
    shutil.copy(_SCANNED_DECK, u / "deck.pdf")
    (u / "notes.md").write_text("not a pdf")
    rc, data, _ = run_script("ocr_uploads.py", ["--uploads-dir", str(u), "--out", str(tmp_path / "o")])
    assert rc == 0 and data is not None
    assert data["ocr_available"] and data["pages_written"] == 2, data
    assert "n=17" in (tmp_path / "o" / "deck.pdf.p2.txt").read_text()
    receipt = json.loads((tmp_path / "o" / "receipt.json").read_text())
    assert receipt["complete"] is True and receipt["documents"] == {"deck.pdf": {"pages": 2, "written": 2}}


@pytest.mark.skipif(shutil.which("tesseract") is None or shutil.which("pdftoppm") is None, reason="OCR binaries absent")
def test_ocr_uploads_resumes_from_its_receipt(tmp_path: Path) -> None:
    """A killed OCR (the 120 s tool limit, measured live) leaves a partial receipt; the re-run must
    skip what is done, so recovery costs only the remaining documents."""
    u = tmp_path / "u"
    u.mkdir()
    shutil.copy(_SCANNED_DECK, u / "a.pdf")
    shutil.copy(_SCANNED_DECK, u / "b.pdf")
    o = tmp_path / "o"
    o.mkdir()
    (o / "a.pdf.p1.txt").write_text("PRIOR")
    (o / "receipt.json").write_text(
        json.dumps(
            {
                "ok": True,
                "ocr_available": True,
                "pages_written": 1,
                "skipped": [],
                "documents": {"a.pdf": {"pages": 2, "written": 1}},
                "complete": False,
            }
        )
    )
    rc, data, err = run_script("ocr_uploads.py", ["--uploads-dir", str(u), "--out", str(o)])
    assert rc == 0 and data is not None
    assert "a.pdf: already read" in err
    assert (o / "a.pdf.p1.txt").read_text() == "PRIOR"  # not re-OCR'd
    assert data["complete"] is True and set(data["documents"]) == {"a.pdf", "b.pdf"}
    assert "n=17" in (o / "b.pdf.p2.txt").read_text()


def _scanned_handoff(tmp_path: Path) -> tuple[Path, Path]:
    a = _analysis_dir(tmp_path)
    h = tmp_path / "handoff"
    (h / "docs").mkdir(parents=True)
    shutil.copy(_SCANNED_DECK, h / "docs" / "deck.pdf")
    return a, h


def _dispatch_scanned(a: Path, h: Path) -> tuple[int, str, str]:
    return _dispatch(
        ["red_team", "--run-id", "x", "--analysis-dir", str(a), "--handoff-dir", str(h), "--handoff-agent", "/h"]
    )


def test_dispatch_prompt_refuses_an_image_only_pdf_the_ocr_receipt_does_not_cover(tmp_path: Path) -> None:
    """Measured live: OCR killed by the tool timeout, prompt generated from the sidecars that existed,
    red team told two documents had 'no machine-read copy'. A receipt that does not name the PDF
    -- absent, or partial and stopped before it -- is a refusal that names the document."""
    a, h = _scanned_handoff(tmp_path)
    rc, out, err = _dispatch_scanned(a, h)  # no ocr dir at all: OCR never ran
    assert rc == 2 and "deck.pdf" in err and "receipt.json" in err and out == "", (out, err)
    (h / "ocr").mkdir()
    (h / "ocr" / "receipt.json").write_text(
        json.dumps(
            {"ok": True, "ocr_available": True, "documents": {"other.pdf": {}}, "skipped": [], "complete": False}
        )
    )
    rc, out, err = _dispatch_scanned(a, h)  # partial receipt, stopped before this document
    assert rc == 2 and "deck.pdf" in err, err


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "ok": True,
            "ocr_available": True,
            "documents": {"deck.pdf": {"pages": 2, "written": 2}},
            "skipped": [],
            "complete": True,
        },
        {"ok": True, "ocr_available": True, "documents": {}, "skipped": ["deck.pdf"], "complete": True},
        {"ok": True, "ocr_available": False, "documents": {}, "skipped": ["deck.pdf"], "complete": True},
    ],
    ids=["read", "skipped-by-ocr", "no-binaries"],
)
def test_dispatch_prompt_accepts_a_receipt_that_covers_the_pdf(tmp_path: Path, receipt: dict[str, Any]) -> None:
    a, h = _scanned_handoff(tmp_path)
    (h / "ocr").mkdir()
    (h / "ocr" / "receipt.json").write_text(json.dumps(receipt))
    rc, out, err = _dispatch_scanned(a, h)
    assert rc == 0, err
    assert "/docs/deck.pdf  (NO TEXT LAYER, 2 pages" in out


# === red_team.py: a finding may cite the founder's own page, and the quote is checked ===

_RUN = "20260101T000000Z"


def _doc_finding(**kw: Any) -> dict[str, Any]:
    base = {
        "claim_attacked": "arpu evidence base",
        "what_is_true": "the recurring figure rests on n=17, not n=47",
        "evidence_quote": "RECURRING (M2+) n=17 patient-months -- $203 per patient month",
        "source_url": "document:notes.md#page=1",
        "source_title": "founder notes",
        "severity": "high",
    }
    return {**base, **kw}


def _run_red_team(tmp_path: Path, payload: dict[str, Any], extra: list[str]) -> tuple[int, str, dict[str, Any] | None]:
    out = tmp_path / "redteam.json"
    rc, stdout, _ = run_script_raw(
        "red_team.py", ["--run-id", _RUN, "-o", str(out), *extra], stdin_data=json.dumps(payload)
    )
    return rc, stdout, (json.loads(out.read_text()) if out.exists() else None)


def test_red_team_document_citation_is_checked_against_the_text_layer(tmp_path: Path) -> None:
    """Today the ONLY legal provenances are a web address and `internal:analysis`, so a finding whose
    evidence is the founder's own deck is dropped as unsourced -- the step that should catch a misread
    of slide 8 is forbidden from citing slide 8."""
    u = tmp_path / "u"
    u.mkdir()
    (u / "notes.md").write_text("Slide 8. RECURRING (M2+) n=17 patient-months -- $203 per patient month\n")
    payload = {
        "findings": [
            _doc_finding(),
            _doc_finding(evidence_quote="47 patient-months from 30 distinct patients here"),
            _doc_finding(source_url="document:missing.pdf#page=8"),
            _doc_finding(evidence_quote="n=17"),
            _doc_finding(source_url="document:notes.md#page=0"),
        ],
        "could_not_check": [],
        "sources_read": ["notes.md"],
        "metadata": {"run_id": _RUN},
    }
    rc, stdout, rt = _run_red_team(tmp_path, payload, ["--uploads-dir", str(u)])
    assert rc == 0 and rt is not None, stdout
    assert [f["quote_verified"] for f in rt["findings"]] == [True, False]
    assert [r["reason"] for r in rt["rejected"]] == [
        "source_url names a document that was not supplied: missing.pdf",
        "quote the sentence, not a token (6 words minimum for a document citation)",
        "source_url for a document must be exactly document:<filename>#page=<n>",
    ]


def test_red_team_document_citation_page_is_optional_for_a_file_with_no_pages(tmp_path: Path) -> None:
    """Live: the red team cited `document:meeting-notes-2026-09-09.md` -- a markdown file has no
    pages -- and the rule demanding `#page=<n>` set a real finding aside. A PDF still needs the page."""
    u = tmp_path / "u"
    u.mkdir()
    (u / "notes.md").write_text("Total addressable channel: ~60 EAPs in the US, of which only a handful are large.\n")
    (u / "deck.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    q = "Total addressable channel: ~60 EAPs in the US, of which only a handful are large."
    payload = {
        "findings": [
            _doc_finding(source_url="document:notes.md", evidence_quote=q),  # no page: fine for .md
            _doc_finding(source_url="document:notes.md#page=1", evidence_quote=q),  # page given: also fine
            _doc_finding(source_url="document:deck.pdf", evidence_quote=q),  # a PDF needs its page
        ],
        "could_not_check": [],
        "sources_read": ["notes.md", "deck.pdf"],
        "metadata": {"run_id": _RUN},
    }
    rc, stdout, rt = _run_red_team(tmp_path, payload, ["--uploads-dir", str(u)])
    assert rc == 0 and rt is not None, stdout
    assert [(f["source_url"], f["quote_verified"]) for f in rt["findings"]] == [
        ("document:notes.md", True),
        ("document:notes.md#page=1", True),
    ]
    assert rt["rejected"] == [
        {
            "claim_attacked": "arpu evidence base",
            "reason": "a citation to a PDF must name the page: document:<filename>#page=<n>",
        }
    ]


def test_red_team_document_citation_uses_the_ocr_sidecar_for_a_scanned_page(tmp_path: Path) -> None:
    u = tmp_path / "u"
    u.mkdir()
    (u / "deck.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    o = tmp_path / "o"
    o.mkdir()
    (o / "deck.pdf.p8.txt").write_text("RECURRING (M2+) n=17 patient-months -- $203 per patient month")
    payload = {
        "findings": [
            _doc_finding(source_url="document:deck.pdf#page=8"),
            _doc_finding(source_url="document:deck.pdf#page=9"),
        ],
        "could_not_check": [],
        "sources_read": ["deck.pdf"],
        "metadata": {"run_id": _RUN},
    }
    rc, stdout, rt = _run_red_team(tmp_path, payload, ["--uploads-dir", str(u), "--ocr-dir", str(o)])
    assert rc == 0 and rt is not None, stdout
    assert [f["quote_verified"] for f in rt["findings"]] == [True, None]  # page 9 has no sidecar


def test_red_team_web_findings_carry_quote_verified_null_and_document_citations_need_uploads(tmp_path: Path) -> None:
    web = _doc_finding(source_url="https://example.gov/x")
    doc = _doc_finding()  # no --uploads-dir at all → nothing to check it against
    rc, stdout, rt = _run_red_team(
        tmp_path, {"findings": [web, doc], "could_not_check": [], "metadata": {"run_id": _RUN}}, []
    )
    assert rc == 0 and rt is not None, stdout
    assert [f["quote_verified"] for f in rt["findings"]] == [None]
    assert rt["rejected"][0]["reason"] == "source_url names a document that was not supplied: notes.md"


def test_document_citation_without_a_page_renders_the_filename_alone() -> None:
    finding = {**_REDTEAM_ARTIFACT["findings"][0], "source_url": "document:notes.md", "quote_verified": True}
    rc, data, d = _compose_with_redteam({**_REDTEAM_ARTIFACT, "findings": [finding]})
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    assert "— notes.md\n" in md and "notes.md, page" not in md
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert "&mdash; notes.md</p>" in html_text


@pytest.mark.parametrize(
    ("verified", "suffix"),
    [
        (True, ""),
        (False, " (this sentence was not found on that page)"),
        (None, " (quoted from a page that could not be machine-read)"),
    ],
)
def test_document_citation_renders_as_a_named_page_on_both_surfaces(verified: bool | None, suffix: str) -> None:
    """The founder's own page is named, never linked, and the check's outcome is shown with it."""
    finding = {**_REDTEAM_ARTIFACT["findings"][0], "source_url": "document:deck.pdf#page=8", "quote_verified": verified}
    rt = {**_REDTEAM_ARTIFACT, "findings": [finding]}
    rc, data, d = _compose_with_redteam(rt)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    assert f"— deck.pdf, page 8{suffix}\n" in md, md[md.index("## Adversarial Findings") :][:800]
    assert "document:" not in md
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert f"deck.pdf, page 8{suffix}" in html_text
    assert "document:deck.pdf" not in html_text


# === sources_read / sources_unread: what the red team opened, and what the report says it did not ===


def test_red_team_records_which_uploads_were_read_and_which_were_not(tmp_path: Path) -> None:
    u = tmp_path / "u"
    u.mkdir()
    for n in ("deck.pdf", "notes.md", "financials.pdf", ".DS_Store"):
        (u / n).write_text("x")
    payload = {
        "findings": [],
        "could_not_check": ["financials.pdf p1-6, scanned tables"],
        # As the prompt lists them: agent-namespace paths, and a sidecar for the deck. Reading the
        # machine-read text of a page IS reading that document.
        "sources_read": [
            "artifacts/x/handoff/r/docs/deck.pdf.p2.txt",
            "artifacts/x/handoff/r/docs/financials.pdf",
            "ghost.pdf",
        ],
        "metadata": {"run_id": _RUN},
    }
    rc, stdout, rt = _run_red_team(tmp_path, payload, ["--uploads-dir", str(u)])
    assert rc == 0 and rt is not None, stdout
    assert rt["sources_read"] == ["deck.pdf", "financials.pdf"]  # ghost.pdf was never supplied
    assert rt["sources_unread"] == ["notes.md"]  # .DS_Store is not a document
    assert rt["summary"]["sources_unread"] == 1


def test_compose_names_documents_the_red_team_did_not_open() -> None:
    rt = {
        **_REDTEAM_ARTIFACT,
        "sources_read": ["deck.pdf"],
        "sources_unread": ["financials.pdf"],
        "summary": {**_REDTEAM_ARTIFACT["summary"], "sources_unread": 1},
    }
    rc, data, _ = _compose_with_redteam(rt)
    assert rc == 0 and data is not None
    w = [x for x in data["validation"]["warnings"] if x["code"] == "RED_TEAM_SOURCES_UNREAD"]
    assert len(w) == 1 and w[0]["severity"] == "high", w
    assert "financials.pdf" in w[0]["message"] and "deck.pdf" not in w[0]["message"]
    assert data["coaching_payload"]["red_team_findings"]["unread"] == ["financials.pdf"]


def test_compose_is_silent_when_every_document_was_opened() -> None:
    rt = {
        **_REDTEAM_ARTIFACT,
        "sources_read": ["deck.pdf"],
        "sources_unread": [],
        "summary": {**_REDTEAM_ARTIFACT["summary"], "sources_unread": 0},
    }
    rc, data, _ = _compose_with_redteam(rt)
    assert rc == 0 and data is not None
    assert not [x for x in data["validation"]["warnings"] if x["code"] == "RED_TEAM_SOURCES_UNREAD"]
    assert data["coaching_payload"]["red_team_findings"]["unread"] == []


# === shared-figure marks survive acceptance; one figure is not a chain ===


def test_equal_value_rows_are_marked_even_when_the_warning_is_accepted() -> None:
    """Live: PAIRED_SLOT_SAME_VALUE fired on 37.32 used on both SAM sides and the constructor accepted
    it away -- its own reason conceding "not fully independent corroboration ... which the report
    should say plainly" -- while the summary table said nothing. The mark comes from the detector, not
    the warning list, so acceptance explains and no longer hides."""
    sizing = _both_sizing(90_000_000_000, 37.32, 0.3, 42_400_000, 2436, 37.32, 0.32)  # equal SAM slots, no TAM identity
    meth = {
        **_VALID_METHODOLOGY,
        "approach_chosen": "both",
        "accepted_warnings": [
            {
                "code": "PAIRED_SLOT_SAME_VALUE",
                "match": "37.32",
                "reason": "deliberate reuse of the deck's reach figure",
            }
        ],
    }
    rc, data, d = _compose_with_sizing(sizing, methodology=meth)
    assert rc == 0 and data is not None
    assert [w["severity"] for w in data["validation"]["warnings"] if w["code"] == "PAIRED_SLOT_SAME_VALUE"] == [
        "acknowledged"
    ]
    table = _compose_md_text(Path(d)).split("## Analysis Checklist")[0]
    assert "| SAM | $33.6B | Top-down ‡ |" in table, table
    assert "| SAM | $38.5B | Bottom-up ‡ |" in table, table
    assert "| TAM | $90.0B | Top-down |" in table, table
    assert "‡ Both builds narrow this figure by the same number" in table
    # ...and on the HTML surface, which nobody reads and where this class of defect survives.
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert "‡" in html_text and "narrow this figure by the same number" in html_text


def test_no_shared_figure_means_no_mark() -> None:
    rc, data, d = _compose_with_sizing(_both_sizing(90_000_000_000, 10.0, 0.3, 42_400_000, 2436, 9.1, 0.32))
    assert rc == 0
    table = _compose_md_text(Path(d)).split("## Analysis Checklist")[0]
    assert "‡" not in table and "†" not in table


def test_a_single_factor_is_unstructured_not_itemized() -> None:
    """Live: segment_pct carried factors=[{serviceable_population_share: 0.3732}] -- the value under
    another name. It reconciled trivially and was reported as itemized."""
    v = json.loads(json.dumps(_VALID_VALIDATION))
    v["assumptions"].append(
        {
            "name": "segment_pct",
            "value": 37.32,
            "category": "derived",
            "label": "Reachable share",
            "factors": [{"factor_id": "same_number", "value": 0.3732, "source_id": "company_stated"}],
        }
    )
    rc, data, _ = _compose_with_validation(v)
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "FACTOR_PRODUCT_MISMATCH" not in codes
    unstructured = [w for w in data["validation"]["warnings"] if w["code"] == "UNSTRUCTURED_DERIVATION"]
    assert unstructured and "Segment %" in unstructured[0]["message"], unstructured


# === closing_message.py: the hand-over is copied from the report, and computes nothing ===

_NUM = re.compile(r"\$?\d[\d,.]*\s?(?:[KMBx%]|billion|million)?")


def _numbers(s: str) -> set[str]:
    return {m.group(0).strip() for m in _NUM.finditer(s)}


def _closing(report_path: str, *extra: str) -> tuple[int, str, str]:
    return run_script_raw("closing_message.py", ["--report", report_path, *extra])


def _write_report(d: str, data: dict[str, Any]) -> str:
    """The compose helpers run without -o; persist the JSON the way Step 7 does."""
    path = Path(d) / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


_LT = re.compile(r"\]\([^)]*\)")


def test_report_json_carries_the_verdict_the_report_opens_with() -> None:
    """`verdict` is the Executive Summary's first paragraph, verbatim, so the chat copy and the page
    copy cannot drift. A message that carried no figure was rewritten into one 0/2 at hostloop
    (local_1ifk47sasu, local_1ishvlzhir); this REVERSES cf78aed's "no figure, no count" decision."""
    rc, data, _ = _compose_with_sizing(_verdict_sizing(), redteam=_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    verdict = data["verdict"]
    assert isinstance(verdict, str) and verdict
    summary = data["report_markdown"].split("## Executive Summary\n\n", 1)[1]
    assert summary.startswith(verdict + "\n"), summary[:300]
    assert "The two builds differ by" in verdict and "An outside review raised" in verdict


def _compose_without_sizing() -> tuple[dict[str, Any] | None, str]:
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    _rc, data, _err = run_script("compose_report.py", ["--dir", d])
    return data, d


def test_report_json_verdict_is_never_empty_without_a_sizing() -> None:
    data, _ = _compose_without_sizing()
    assert data is not None
    assert data["verdict"].startswith("No sizing was produced; see Warnings.")
    assert data["report_markdown"].split("## Executive Summary\n\n", 1)[1].startswith(data["verdict"])


def test_closing_message_carries_the_verdict_whole_and_nothing_else_numeric() -> None:
    """Links, the report's own verdict (marks explained, page phrases rewritten), the offer. Every
    digit in the message is a digit of the verdict; the pointer sentence is gone (the verdict already
    states the review's outcome). The e2e lane asserts the founder received this text whole."""
    rc, data, d = _compose_with_sizing(_verdict_sizing(), redteam=_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    rc2, out, err = _closing(
        _write_report(d, data),
        "--link",
        "computer",
        "--deliverable",
        "the written report=/abs/X_Market_Sizing.md",
        "--deliverable",
        "the interactive version=/abs/X_Market_Sizing.html",
    )
    assert rc2 == 0, err
    assert "[the written report](computer:///abs/X_Market_Sizing.md)" in out
    assert "[the interactive version](computer:///abs/X_Market_Sizing.html)" in out
    assert "it opens with the verdict" in out
    assert "If you want to keep the working data" in out
    assert "on that page too" not in out and "the page says" not in out
    body = _LT.sub("]()", out)
    verdict_chat = body.split("\n\n")[1]
    assert _numbers(verdict_chat) == _numbers(data["verdict"]), (verdict_chat, data["verdict"])
    assert _numbers(body) == _numbers(data["verdict"])
    for mark in ("\u2020", "\u2021", "\u00a7"):
        assert (mark in data["verdict"]) == (f"{mark} " in verdict_chat.rsplit("(", 1)[-1]), verdict_chat
    assert "see Warnings" not in out and "see Adversarial Findings" not in out
    assert (Path(d) / "handover.txt").read_text(encoding="utf-8") == out
    _, out_path, _ = _closing(_write_report(d, data), "--link", "path", "--deliverable", "the written report=/abs/r.md")
    assert "[the written report](/abs/r.md)" in out_path and "computer://" not in out_path


def test_closing_message_explains_each_mark_the_verdict_quotes() -> None:
    """A figure quoted with § in chat needs the page's footnote beside it; a mark that never appears
    gets no legend line (the legend is derived from the text, not from the report's state)."""
    inputs = {
        **_VALID_INPUTS,
        "founder_stated_inputs": {"arpu": 2436},
        "existing_claims": {"tam": 80_000_000_000},
        "existing_claims_currency": "USD",
    }
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "severity": "high", "parameter": "arpu"}],
    }
    rc, data, d = _compose_with_sizing(
        _both_sizing(7e9, 37.32, 3, 41_000_000, 2436, 22.33, 0.268), inputs=inputs, redteam=rt
    )
    assert rc == 0 and data is not None
    assert "$99.9B \u00a7 (bottom-up)" in data["verdict"], data["verdict"]
    _, out, err = _closing(_write_report(d, data), "--link", "path", "--deliverable", "the written report=/abs/r.md")
    assert "$99.9B \u00a7 (bottom-up)" in out, (err, out)
    assert "(\u00a7 built on a figure you stated that a cited source contradicts.)" in out, out
    assert "\u2020 " not in out.rsplit("(", 1)[-1] and "\u2021 " not in out.rsplit("(", 1)[-1]


def test_closing_message_link_form_follows_the_lane() -> None:
    """Measured 2026-09-22 in a real cloud-lane session: `computer://` renders as plain text and a
    bare path becomes a broken claude.ai URL -- no link form opens there; the share card delivers.
    The desktop-local tree opens `computer://`; the CLI wants a bare path."""
    rc, data, d = _compose_with_sizing(_verdict_sizing(), redteam=_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    rp = _write_report(d, data)
    _, none_out, _ = _closing(rp, "--link", "none", "--deliverable", "the written report=/abs/r.md")
    assert "the written report (`/abs/r.md`) — it opens with the verdict" in none_out and "](" not in none_out, none_out
    _, computer_out, _ = _closing(rp, "--deliverable", "the written report=/abs/r.md", "--link", "computer")
    assert "[the written report](computer:///abs/r.md)" in computer_out
    # `auto` from the env markers, no flag on the command line:
    env_remote = {**os.environ, "CLAUDE_CODE_REMOTE": "true"}
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(MARKET_SIZING_DIR, "closing_message.py"),
            "--report",
            rp,
            "--deliverable",
            "x=/abs/r.md",
        ],
        capture_output=True,
        text=True,
        env=env_remote,
    )
    assert r.returncode == 0 and "](" not in r.stdout, r.stdout
    env_cli = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_ENTRYPOINT")}
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(MARKET_SIZING_DIR, "closing_message.py"),
            "--report",
            rp,
            "--deliverable",
            "x=/abs/r.md",
        ],
        capture_output=True,
        text=True,
        env=env_cli,
        cwd=d,
    )
    assert "[x](/abs/r.md)" in r.stdout, r.stdout


def test_closing_message_states_the_no_sizing_verdict() -> None:
    data, d = _compose_without_sizing()
    assert data is not None
    _, out, err = _closing(_write_report(d, data), "--link", "path", "--deliverable", "the written report=/abs/r.md")
    assert "No sizing was produced; see the report's warnings." in out, (err, out)
    assert "see Warnings" not in out


def test_closing_message_refuses_an_unreadable_report(tmp_path: Path) -> None:
    rc, _, err = _closing(str(tmp_path / "nope.json"), "--deliverable", "x=/abs/x.md")
    assert rc == 2 and "report" in err


def test_closing_message_refuses_a_report_without_a_verdict(tmp_path: Path) -> None:
    """An older report.json (no `verdict`) must not produce a message with nothing in it."""
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"coaching_payload": {}}), encoding="utf-8")
    rc, _, err = _closing(str(p), "--deliverable", "x=/abs/x.md")
    assert rc == 2 and "verdict" in err


# === a stated figure an outside source contradicts marks every row built on it ===


def test_contested_stated_input_marks_the_rows_built_on_it() -> None:
    """The founder's $203 PMPM was the base case, an outside source said $66, and nothing in the
    summary table said which rows rested on the contested figure. No number field, no re-basing: the
    red team may not propose figures, and the live finding quoted a monthly rate against an annual
    ARPU -- a value field would launder that unit mismatch into a warning."""
    inputs = {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 2436}}
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "severity": "high", "parameter": "arpu"}],
    }
    rc, data, d = _compose_with_sizing(
        _both_sizing(7e9, 37.32, 3, 41_000_000, 2436, 22.33, 0.268), inputs=inputs, redteam=rt
    )
    assert rc == 0 and data is not None
    table = _compose_md_text(Path(d)).split("## Analysis Checklist")[0]
    assert "| TAM | $99.9B | Bottom-up § |" in table, table
    assert "| SAM | $22.3B | Bottom-up § |" in table, table
    assert "| SOM | $267.7M | Bottom-up § |" in table, table
    assert "| TAM | $7.0B | Top-down |" in table, table  # top-down did not consume arpu
    assert "§ Built on a figure you stated that a cited source contradicts" in table
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    assert "§" in html_text and "a cited source contradicts" in html_text


def test_contested_mark_needs_a_high_finding_on_a_stated_input() -> None:
    inputs = {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 2436}}
    medium = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "severity": "medium", "parameter": "arpu"}],
    }
    _, _, d1 = _compose_with_sizing(
        _both_sizing(7e9, 37.32, 3, 41_000_000, 2436, 37.32, 0.268), inputs=inputs, redteam=medium
    )
    assert "§" not in _compose_md_text(Path(d1)).split("## Analysis Checklist")[0]
    not_stated = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "severity": "high", "parameter": "customer_count"}],
    }
    _, _, d2 = _compose_with_sizing(
        _both_sizing(7e9, 37.32, 3, 41_000_000, 2436, 37.32, 0.268), inputs=inputs, redteam=not_stated
    )
    assert "§" not in _compose_md_text(Path(d2)).split("## Analysis Checklist")[0]


def test_red_team_keeps_a_known_parameter_and_drops_an_unknown_one(tmp_path: Path) -> None:
    known = _doc_finding(source_url="https://example.gov/pfs", parameter="arpu")
    unknown = _doc_finding(source_url="https://example.gov/pfs", parameter="not_a_sizing_input")
    rc, stdout, rt = _run_red_team(
        tmp_path, {"findings": [known, unknown], "could_not_check": [], "metadata": {"run_id": _RUN}}, []
    )
    assert rc == 0 and rt is not None, stdout
    assert rt["findings"][0]["parameter"] == "arpu"
    assert "parameter" not in rt["findings"][1]
    assert rt["rejected"] == []


# === the Executive Summary opens with the verdict a reader would otherwise be told in chat ===


def _verdict_sizing() -> dict[str, Any]:
    """Top-down SOM $19.2M, bottom-up SOM $56.8M, deltas set as the producer would (the helper pins
    comparison to a 0.0 TAM delta; compose never recomputes)."""
    s = _both_sizing(2e9, 8.0, 12.0, 233_000, 2436, 25.0, 10.0)
    tail = "Review assumptions — one approach likely has a flawed input."
    s["comparison"] = {
        "tam_delta_pct": 111.6,
        "sam_delta_pct": 12.0,
        "som_delta_pct": 98.9,
        "warning": f"Top-down and bottom-up TAM differ by 111.6% (>30%). {tail}",
        "sam_note": f"SAM estimates differ by 12.0%. {_CAVEAT}",
        "som_warning": f"Top-down and bottom-up SOM differ by 98.9% (>30%). {tail}",
    }
    return s


def _summary_head(md: str) -> str:
    return md[md.index("## Executive Summary") : md.index("| Metric | Value | Method |")]


def test_summary_opens_with_the_verdict_from_fields() -> None:
    """Live, 2/2 hostloop runs: the model wrote this paragraph in chat, with ratios it rounded
    itself. It now exists on the page, from fields, above the marked table."""
    inputs = {**_VALID_INPUTS, "existing_claims": {"tam": None, "sam": None, "som": 100_000_000}}
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "source_url": "internal:analysis", "severity": "high"}],
    }
    rc, data, d = _compose_with_sizing(_verdict_sizing(), inputs=inputs, redteam=rt)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    head = _summary_head(md)
    assert "Your materials state SOM $100.0M; this analysis finds $19.2M (top-down) and $56.8M (bottom-up)." in head, (
        head
    )
    assert (
        "The two builds differ by 111.6% on TAM and 98.9% on SOM — one approach likely has a flawed input." in head
    ), head
    assert "An outside review raised 1 challenge: 1 from this analysis's own output." in head, head
    assert "from published sources" not in head  # the finding is internal; the old wording said "published"
    assert "The most serious:" in head and "(from this analysis's own output)" in head, head
    assert data["coaching_payload"]["self_check_line"] in head
    # one section: the marked table follows within a short distance
    assert md.index("| Metric | Value | Method |") - md.index("## Executive Summary") < 1400, head


def test_verdict_quotes_a_marked_figure_with_its_mark() -> None:
    """A figure the table marks § (built on a contested stated input) carries the mark in the sentence."""
    inputs = {
        **_VALID_INPUTS,
        "existing_claims": {"tam": None, "sam": None, "som": 100_000_000},
        "founder_stated_inputs": {"arpu": 2436},
    }
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "severity": "high", "parameter": "arpu"}],
    }
    rc, data, d = _compose_with_sizing(_verdict_sizing(), inputs=inputs, redteam=rt)
    assert rc == 0
    head = _summary_head(_compose_md_text(Path(d)))
    assert "$56.8M § (bottom-up)" in head, head
    assert "$19.2M (top-down)" in head, head


def test_verdict_single_approach_and_no_claims() -> None:
    sizing = json.loads(json.dumps(_VALID_SIZING))
    sizing["approach"] = "bottom_up"
    sizing.pop("top_down")
    sizing.pop("comparison")
    inputs = {**_VALID_INPUTS, "existing_claims": {"tam": None, "sam": None, "som": 100_000_000}}
    rc, data, d = _compose_with_sizing(
        sizing, inputs=inputs, methodology={**_VALID_METHODOLOGY, "approach_chosen": "bottom_up"}
    )
    assert rc == 0
    head = _summary_head(_compose_md_text(Path(d)))
    assert "Your materials state SOM $100.0M; this analysis finds" in head and "(bottom-up)." in head, head
    assert "The two builds differ" not in head
    rc2, _, d2 = _compose_with_sizing(_verdict_sizing())  # _VALID_INPUTS states no claim
    head2 = _summary_head(_compose_md_text(Path(d2)))
    assert "Your materials state" not in head2
    assert "The two builds differ by 111.6% on TAM and 98.9% on SOM" in head2


def test_verdict_when_no_sizing_was_produced() -> None:
    arts = {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    d = _make_artifact_dir(arts)
    run_script("compose_report.py", ["--dir", d])
    md = _compose_md_text(Path(d))
    assert "No sizing was produced; see Warnings." in md[md.index("## Executive Summary") :][:400]


@pytest.mark.parametrize(
    ("urls", "rejected", "expected"),
    [
        (["https://a.gov/x"], 0, "An outside review raised 1 challenge: 1 from published sources."),
        (
            ["https://a.gov/x", "internal:analysis", "document:deck.pdf#page=2"],
            0,
            "An outside review raised 3 challenges: 1 from published sources, 1 from this analysis's own output, "
            "1 from your own documents.",
        ),
        ([], 0, "An outside review ran against this analysis and found nothing it could evidence."),
        ([], 2, "An outside review raised 2 challenges but could evidence none of them."),
    ],
)
def test_adversarial_outcome_counts_by_source_class_on_every_surface(
    urls: list[str], rejected: int, expected: str
) -> None:
    findings = [{**_REDTEAM_ARTIFACT["findings"][0], "source_url": u} for u in urls]
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": findings,
        "rejected": [{"claim_attacked": "x", "reason": "r"}] * rejected,
        "summary": {**_REDTEAM_ARTIFACT["summary"], "accepted": len(findings), "rejected": rejected},
    }
    rc, data, d = _compose_with_sizing(_verdict_sizing(), redteam=rt)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    assert expected in _summary_head(md), _summary_head(md)
    section = md[md.index("## Adversarial Findings") :]
    assert expected in section[:600], section[:600]
    if findings:
        w = next(x for x in data["validation"]["warnings"] if x["code"] == "RED_TEAM_FINDINGS")
        assert expected in w["message"], w["message"]


def test_verdict_when_the_review_was_skipped() -> None:
    meth = {**_VALID_METHODOLOGY, "approach_chosen": "both", "red_team_skipped": "founder_declined"}
    rc, _, d = _compose_with_sizing(_verdict_sizing(), methodology=meth)
    assert rc == 0
    head = _summary_head(_compose_md_text(Path(d)))
    assert "No adversarial review ran, because you asked us not to run one." in head
    assert "No outside review ran:" not in head  # the reason sentence stands alone, not doubled


def test_verdict_paragraph_renders_in_the_html_hero() -> None:
    """Sliced between </h1> and <main>, so the funnel label further down cannot satisfy it."""
    inputs = {**_VALID_INPUTS, "existing_claims": {"tam": None, "sam": None, "som": 100_000_000}}
    rt = {
        **_REDTEAM_ARTIFACT,
        "findings": [{**_REDTEAM_ARTIFACT["findings"][0], "source_url": "internal:analysis", "severity": "high"}],
    }
    rc, _, d = _compose_with_sizing(_verdict_sizing(), inputs=inputs, redteam=rt)
    assert rc == 0
    rc_html, html_text, err = run_script_raw("visualize.py", ["--dir", d])
    assert rc_html == 0, err
    hero = html_text[html_text.index("</h1>") : html_text.index("<main")]
    assert 'class="verdict"' in hero
    assert "Your materials state SOM $100.0M; this analysis finds $19.2M (top-down) and $56.8M (bottom-up)." in hero
    assert "The two builds differ by 111.6% on TAM and 98.9% on SOM" in hero
    # visualize escapes the apostrophe; assert the class phrase without it
    assert "An outside review raised 1 challenge: 1 from this analysis" in hero


# === a market figure from the deck is a claim to test, not a stated input to protect ===


def test_a_market_figure_in_founder_stated_inputs_is_flagged_high() -> None:
    """Live (critique of a real-world run, the agent's own words): the deck's 64M population and 0.27%
    capture were recorded as founder-stated, the value-fidelity rule then forbade the bottom-up
    build from departing from them, and the "independent" build replayed the deck's math. Only
    arpu is a fact about the founder's own business; the rest are market figures."""
    inputs = {
        **_VALID_INPUTS,
        "founder_stated_inputs": {"arpu": 2436, "customer_count": 64_000_000, "target_pct": 0.27},
    }
    rc, data, d = _compose_with_sizing(_verdict_sizing(), inputs=inputs)
    assert rc == 0 and data is not None
    w = [x for x in data["validation"]["warnings"] if x["code"] == "FOUNDER_STATED_MARKET_FIGURE"]
    assert len(w) == 1 and w[0]["severity"] == "high", w
    assert (
        "Customer Count" in w[0]["message"] and "Target Capture %" in w[0]["message"] and "ARPU" not in w[0]["message"]
    )
    assert "claim" in w[0]["message"]
    md = _compose_md_text(Path(d))
    assert "customer_count" not in md and "target_pct" not in md  # humanized, never the raw name


def test_arpu_alone_in_founder_stated_inputs_is_not_flagged() -> None:
    inputs = {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 2436}}
    rc, data, _ = _compose_with_sizing(_verdict_sizing(), inputs=inputs)
    assert rc == 0 and data is not None
    assert not [x for x in data["validation"]["warnings"] if x["code"] == "FOUNDER_STATED_MARKET_FIGURE"]


# === red_team.py words the review for the founder, before anyone else can see it ===============
#
# Our file names in the review's prose invite the analysis's main thread to rewrite the review to
# remove them (measured, substance included). The producer words the three prose fields itself, so
# there is nothing left for the reviewed party to edit. The quote is never touched.

_RUN_SHAPED_FINDING = {
    "claim_attacked": "Bottom-up TAM/SAM/SOM are all built on arpu=$4,620 (the deck's $385 blended PPPM)",
    "what_is_true": (
        "sizing.json's actual bottom_up.tam.value is $46.2B, not $33.7B, and validation.json's "
        "'date_accessed' field is only when the page was retrieved. The checklist step (data_current) "
        "and existing_claims.tam disagree (14.5M vs. the prior 10.593M)."
    ),
    "evidence_quote": "validation.json figure_validations lists arpu_founder_$385_pppm as refuted",
    "source_url": "internal:analysis",
    "source_title": "validation.json figure_validations (arpu_founder_$385_pppm, status: refuted) vs. sizing.json",
    "severity": "high",
    "parameter": "arpu",
}


def test_red_team_words_our_files_and_identifiers_for_the_founder(tmp_path: Path) -> None:
    rc, _stdout, data = _run_red_team(tmp_path, {"findings": [_RUN_SHAPED_FINDING]}, [])
    assert rc == 0 and data is not None
    f = data["findings"][0]
    prose = " ".join(f[k] for k in ("claim_attacked", "what_is_true", "source_title"))
    for leaked in (
        "sizing.json",
        "validation.json",
        "bottom_up",
        "date_accessed",
        "data_current",
        "existing_claims",
        "figure_validations",
        "arpu_founder",
        "arpu=",
    ):
        assert leaked not in prose, f"{leaked!r} reached the founder: {prose}"
    assert "The sizing calculation's actual bottom-up TAM is $46.2B" in f["what_is_true"]
    assert "ARPU=$4,620" in f["claim_attacked"]
    # The author's own words are not re-cased: "vs. the prior" stays lower-case.
    assert "vs. the prior" in f["what_is_true"]
    # A quotation is never reworded: a reworded quote is a false one.
    assert f["evidence_quote"] == _RUN_SHAPED_FINDING["evidence_quote"]
    assert data["summary"]["humanized"] >= 8


def test_red_team_wording_passes_the_fleet_founder_text_scan(tmp_path: Path) -> None:
    """Measured against this run shape: nothing the shared scan would flag survives the producer."""
    import importlib

    shared = str(Path(__file__).resolve().parent.parent / "scripts")
    sys.path.insert(0, shared)
    try:
        ft = importlib.import_module("_founder_text")
    finally:
        sys.path.remove(shared)
    rc, _stdout, data = _run_red_team(tmp_path, {"findings": [_RUN_SHAPED_FINDING]}, [])
    assert rc == 0 and data is not None
    for k in ("claim_attacked", "what_is_true", "source_title"):
        found = ft.scan(data["findings"][0][k])
        assert found == {"enums": [], "filenames": []}, (k, found)


def test_red_team_wording_leaves_the_founders_files_and_urls_alone(tmp_path: Path) -> None:
    uploads = tmp_path / "docs"
    uploads.mkdir()
    (uploads / "notes.md").write_text("RECURRING (M2+) n=17 patient-months -- $203 per patient month\n")
    finding = _doc_finding(
        what_is_true="notes.md and founder-notes.md say otherwise; see https://kff.org/a_b/page.html e.g. here",
        source_title="notes.md, page 1",
    )
    rc, _stdout, data = _run_red_team(tmp_path, {"findings": [finding]}, ["--uploads-dir", str(uploads)])
    assert rc == 0 and data is not None, _stdout
    f = data["findings"][0]
    assert f["what_is_true"] == finding["what_is_true"]
    assert f["source_title"] == "notes.md, page 1"


def test_red_team_fails_loudly_when_the_shared_scripts_are_missing(tmp_path: Path) -> None:
    """A broken install must not produce an unworded review that looks worded."""
    import shutil

    scripts = Path(__file__).resolve().parent.parent / "skills" / "market-sizing" / "scripts"
    lone = tmp_path / "a" / "b" / "c" / "scripts"
    lone.mkdir(parents=True)
    for name in ("red_team.py", "_redteam_text.py", "_redteam_copy.py", "_quote_match.py"):
        shutil.copy(scripts / name, lone / name)
    out = tmp_path / "redteam.json"
    out.write_text('{"sentinel": true}')
    proc = subprocess.run(
        [sys.executable, str(lone / "red_team.py"), "--run-id", _RUN, "-o", str(out)],
        input=json.dumps({"findings": [_GOOD_FINDING]}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert json.loads(out.read_text()) == {"sentinel": True}, "-o must be left untouched"
    assert "shared scripts" in proc.stdout


# === A red-team quote reaches the founder exactly as the source wrote it ========================


def _redteam_quoting(quote: str) -> dict[str, Any]:
    finding = {**_REDTEAM_ARTIFACT["findings"][0], "evidence_quote": quote}
    return {**_REDTEAM_ARTIFACT, "findings": [finding]}


def test_red_team_quote_is_not_reworded_by_the_founder_text_pass() -> None:
    """The report's rewrite of internal tokens used to reach inside quotations too.

    A red team that quotes a source using a word shaped like one of ours (here `gross_margin`) was
    shown to the founder as saying "gross margin" -- a quotation the source never contained.
    """
    quote = "Vendors report gross_margin above 70% for care-management software in 2025."
    rc, data, _d = _compose_with_redteam(_redteam_quoting(quote))
    assert rc == 0 and data is not None
    md = data["report_markdown"]
    assert f"> {quote}" in md
    msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "FOUNDER_TEXT_TOKEN"]
    assert any("gross_margin" in m and "do not edit it" in m for m in msgs), msgs
    # The actionable (edit-this) message is NOT raised for a token that lives only in a quote.
    assert not any("gross_margin" in m and "render it through" in m for m in msgs), msgs


def test_red_team_multi_line_quote_stays_inside_the_blockquote() -> None:
    quote = "INITIATION (M0-M1) n=30 patient-months -- $488 per patient month\nRECURRING (M2+) n=17 -- $203"
    rc, data, _d = _compose_with_redteam(_redteam_quoting(quote))
    assert rc == 0 and data is not None
    md = data["report_markdown"]
    assert "> INITIATION (M0-M1) n=30 patient-months -- $488 per patient month\n> RECURRING (M2+) n=17 -- $203" in md
    assert "" not in md and "" not in md


def test_red_team_rejects_a_json_shaped_quote_of_the_analysis_per_finding(tmp_path: Path) -> None:
    json_quote = {
        **_RUN_SHAPED_FINDING,
        "evidence_quote": '"existing_claims": {"tam": 12000000000, "som": 60000000}',
    }
    sentence = {**_RUN_SHAPED_FINDING, "evidence_quote": "The founder's $12B figure is not investigated anywhere."}
    rc, _stdout, data = _run_red_team(tmp_path, {"findings": [json_quote, sentence]}, [])
    assert rc == 0 and data is not None
    assert data["summary"]["accepted"] == 1 and data["summary"]["rejected"] == 1
    assert "not as JSON" in data["rejected"][0]["reason"]


def test_red_team_keeps_a_sentence_that_happens_to_quote_a_word_and_a_colon(tmp_path: Path) -> None:
    finding = {**_RUN_SHAPED_FINDING, "evidence_quote": 'The deck labels it "blended": $385 per patient month.'}
    rc, _stdout, data = _run_red_team(tmp_path, {"findings": [finding]}, [])
    assert rc == 0 and data is not None and data["summary"]["accepted"] == 1


# === The review the founder sees is its append-only copy, and reruns are counted ================
#
# Twice the analysis's main thread changed the review after it was written, with a SKILL.md rule
# against it in context both times. red_team.py now writes a copy per round under the run's
# hand-off dir; compose and visualize render from it, so an edit to redteam.json changes nothing the
# founder reads, and it is reported.

_CRUN = "20260101T000000Z"


def _gated_dir(methodology_extra: dict[str, Any] | None = None) -> Path:
    methodology = {k: v for k, v in _VALID_METHODOLOGY.items() if k != "red_team_skipped"}
    methodology.update(methodology_extra or {})
    arts = {
        name: {**base, "metadata": {"run_id": _CRUN}}
        for name, base in (
            ("inputs.json", {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 203}}),
            ("methodology.json", methodology),
            ("validation.json", _VALID_VALIDATION),
            ("sizing.json", _VALID_SIZING),
            ("checklist.json", _VALID_CHECKLIST),
            ("sensitivity.json", _VALID_SENSITIVITY),
        )
    }
    return Path(_make_artifact_dir(arts))


def _pipe_review(d: Path, what_is_true: str) -> dict[str, Any]:
    finding = {**_GOOD_FINDING, "what_is_true": what_is_true}
    rc, stdout, _err = run_script_raw(
        "red_team.py",
        ["--run-id", _CRUN, "-o", str(d / "redteam.json")],
        stdin_data=json.dumps({"findings": [finding]}),
    )
    assert rc == 0, stdout
    receipt: dict[str, Any] = json.loads(stdout)
    return receipt


def _compose_dir(d: Path) -> dict[str, Any]:
    rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
    assert rc == 0 and data is not None, err
    return data


def _warning_codes(data: dict[str, Any]) -> list[str]:
    return [w["code"] for w in data["validation"]["warnings"]]


_REVIEW_CODES = {"REDTEAM_ALTERED", "RED_TEAM_RERUN_UNAPPROVED", "REVIEW_COPY_MISSING", "RED_TEAM_SKIP_CONTRADICTED"}


def test_red_team_writes_a_copy_per_round_and_counts_rounds_by_hand_off(tmp_path: Path) -> None:
    d = _gated_dir()
    assert _pipe_review(d, "Round one says the share is 6.1%.")["round"] == 1
    copy1 = json.loads((d / "handoff" / _CRUN / "redteam.r1.json").read_text())
    assert copy1["_review_copy"]["inputs_at_review"]["founder_stated_inputs"] == {"arpu": 203}
    # The same hand-off again (e.g. corrected documents dir) is the same round, not a new one.
    assert _pipe_review(d, "Round one says the share is 6.1%.")["round"] == 1
    assert _pipe_review(d, "Round two says something else.")["round"] == 2
    assert sorted(p.name for p in (d / "handoff" / _CRUN).iterdir()) == ["redteam.r1.json", "redteam.r2.json"]


def test_an_honest_single_review_raises_none_of_the_review_codes() -> None:
    d = _gated_dir()
    _pipe_review(d, "The published share is 6.1%.")
    data = _compose_dir(d)
    assert not _REVIEW_CODES & set(_warning_codes(data)), _warning_codes(data)
    assert "The published share is 6.1%." in data["report_markdown"]


def test_an_edited_review_changes_nothing_the_founder_reads_and_is_reported() -> None:
    """The observed act: the main thread wrote over redteam.json after the producer ran."""
    d = _gated_dir()
    _pipe_review(d, "The published share is 6.1%, not the 10% the analysis uses.")
    rt = json.loads((d / "redteam.json").read_text())
    rt["findings"][0]["what_is_true"] = "An earlier draft of this analysis has been corrected."
    (d / "redteam.json").write_text(json.dumps(rt))
    data = _compose_dir(d)
    md = data["report_markdown"]
    assert "not the 10% the analysis uses" in md
    assert "has been corrected" not in md
    assert "REDTEAM_ALTERED" in _warning_codes(data)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "REDTEAM_ALTERED")
    assert w["severity"] == "high"
    # It reaches report.md itself, where the founder reads it -- not only the warnings list.
    assert "The Outside Review Was Changed After It Was Written" in md
    # The coach is handed the review as written, too.
    assert "has been corrected" not in json.dumps(data.get("coaching_payload", {}))
    # And the second renderer.
    rc, html, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0, err
    assert "not the 10% the analysis uses" in html and "has been corrected" not in html


def test_a_deleted_review_is_reported_and_still_shown() -> None:
    d = _gated_dir()
    _pipe_review(d, "The published share is 6.1%.")
    (d / "redteam.json").unlink()
    data = _compose_dir(d)
    assert "REDTEAM_ALTERED" in _warning_codes(data)
    assert "The published share is 6.1%." in data["report_markdown"]


def test_an_unapproved_second_review_is_reported_and_the_first_is_shown() -> None:
    d = _gated_dir()
    _pipe_review(d, "The first review found the share is 6.1%.")
    _pipe_review(d, "A second review found nothing much.")
    data = _compose_dir(d)
    assert "RED_TEAM_RERUN_UNAPPROVED" in _warning_codes(data)
    assert "REDTEAM_ALTERED" not in _warning_codes(data)
    assert "The first review found" in data["report_markdown"]
    assert "A second review found" not in data["report_markdown"]


def test_an_approved_second_review_is_shown_without_a_warning() -> None:
    d = _gated_dir({"red_team_revision": {"approved_by_founder": True, "founder_words": "yes, revise"}})
    _pipe_review(d, "The first review found the share is 6.1%.")
    _pipe_review(d, "The revised analysis still overstates the share.")
    data = _compose_dir(d)
    assert not _REVIEW_CODES & set(_warning_codes(data)), _warning_codes(data)
    assert "still overstates" in data["report_markdown"]


def test_a_third_review_is_reported_even_with_approval() -> None:
    d = _gated_dir({"red_team_revision": {"approved_by_founder": True, "founder_words": "yes"}})
    for text in ("First review.", "Second review.", "Third review."):
        _pipe_review(d, text)
    data = _compose_dir(d)
    assert "RED_TEAM_RERUN_UNAPPROVED" in _warning_codes(data)
    assert "First review." in data["report_markdown"]


def test_a_review_with_a_hand_off_dir_but_no_copy_is_reported() -> None:
    """A pipe of the old shape (no copy) cannot be vouched for once the run has a hand-off dir."""
    d = _gated_dir()
    (d / "handoff" / _CRUN).mkdir(parents=True)
    (d / "redteam.json").write_text(json.dumps({**_REDTEAM_ARTIFACT, "metadata": {"run_id": _CRUN}}))
    assert "REVIEW_COPY_MISSING" in _warning_codes(_compose_dir(d))


def test_a_legacy_review_with_no_hand_off_dir_raises_nothing_new() -> None:
    d = _gated_dir()
    (d / "redteam.json").write_text(json.dumps({**_REDTEAM_ARTIFACT, "metadata": {"run_id": _CRUN}}))
    assert not _REVIEW_CODES & set(_warning_codes(_compose_dir(d)))


def test_a_skip_recorded_beside_a_review_that_ran_is_contradicted() -> None:
    """ "We tried and could not" must not be claimable while the review's copy exists."""
    d = _gated_dir({"red_team_skipped": "dispatch_failed"})
    _pipe_review(d, "The published share is 6.1%.")
    (d / "redteam.json").write_text(json.dumps({"skipped": True}))
    data = _compose_dir(d)
    assert {"RED_TEAM_SKIP_CONTRADICTED", "REDTEAM_ALTERED"} <= set(_warning_codes(data))
    assert "The published share is 6.1%." in data["report_markdown"]


def test_red_team_refuses_minus_o_without_a_run_id(tmp_path: Path) -> None:
    out = tmp_path / "redteam.json"
    out.write_text('{"sentinel": true}')
    rc, stdout, _err = run_script_raw(
        "red_team.py", ["-o", str(out)], stdin_data=json.dumps({"findings": [_GOOD_FINDING]})
    )
    assert rc != 0 and "--run-id" in stdout
    assert json.loads(out.read_text()) == {"sentinel": True}


# === A review is final: the messages carry the remedy, because a message is printed at the moment
# of action and a rule further down SKILL.md is not ================================================


def test_red_team_findings_message_says_they_cannot_be_fixed_by_rerunning_or_editing() -> None:
    d = _gated_dir()
    _pipe_review(d, "The published share is 6.1%.")
    data = _compose_dir(d)
    msg = next(w["message"] for w in data["validation"]["warnings"] if w["code"] == "RED_TEAM_FINDINGS")
    assert "cannot fix a finding that is true" in msg and "the founder decides" in msg


def test_a_file_name_in_the_report_names_who_fixes_it_and_never_the_review() -> None:
    """The old remedy -- "drop the reference" -- was satisfiable only by editing the review."""
    assumptions: list[dict[str, Any]] = [dict(a) for a in _VALID_VALIDATION["assumptions"]]  # type: ignore[attr-defined]
    assumptions[0]["label"] = f"{assumptions[0].get('label', assumptions[0]['name'])} (see sizing.json)"
    validation = {**_VALID_VALIDATION, "assumptions": assumptions}
    rc, data, _d = _compose_with_validation(validation)
    assert rc == 0 and data is not None
    msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "FOUNDER_TEXT_TOKEN"]
    assert any("sizing.json" in m for m in msgs), msgs
    m = next(m for m in msgs if "sizing.json" in m)
    assert "drop the reference" not in m
    assert "label or note you wrote" in m and "never edited" in m


def test_a_review_from_an_earlier_run_today_is_disclosed(tmp_path: Path) -> None:
    """Restarting under a new run id is how the round count would otherwise be escaped."""
    d = _gated_dir()
    other = d / "handoff" / "20251231T000000Z"
    other.mkdir(parents=True)
    (other / "redteam.r1.json").write_text(json.dumps({"findings": []}))
    _pipe_review(d, "The published share is 6.1%.")
    data = _compose_dir(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "EARLIER_REVIEW_THIS_ANALYSIS")
    assert w["severity"] == "medium" and "20251231T000000Z" in w["message"]


def test_a_review_from_an_earlier_run_days_ago_is_not_disclosed(tmp_path: Path) -> None:
    d = _gated_dir()
    other = d / "handoff" / "20251231T000000Z"
    other.mkdir(parents=True)
    old = other / "redteam.r1.json"
    old.write_text(json.dumps({"findings": []}))
    stale = old.stat().st_mtime - 3 * 24 * 3600
    os.utime(old, (stale, stale))
    _pipe_review(d, "The published share is 6.1%.")
    assert "EARLIER_REVIEW_THIS_ANALYSIS" not in _warning_codes(_compose_dir(d))


# === One founder-approved revision round ========================================================


def _set_inputs(d: Path, **founder: Any) -> None:
    inputs = json.loads((d / "inputs.json").read_text())
    inputs.update(founder)
    (d / "inputs.json").write_text(json.dumps(inputs))


def _set_methodology(d: Path, **extra: Any) -> None:
    m = json.loads((d / "methodology.json").read_text())
    m.update(extra)
    (d / "methodology.json").write_text(json.dumps(m))


def test_a_founder_figure_changed_after_the_review_without_confirmation_is_high() -> None:
    """The measured edit: a stated 203 rewritten to 385 on a red-team finding's say-so, no founder asked."""
    d = _gated_dir()
    _pipe_review(d, "The deck's blended figure is $385.")
    _set_inputs(d, founder_stated_inputs={"arpu": 385})
    data = _compose_dir(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "FOUNDER_INPUT_REWRITTEN")
    assert w["severity"] == "high" and "203" in w["message"] and "385" in w["message"]
    assert "A Figure You Gave Was Changed Without Your Confirmation" in data["report_markdown"]


def test_a_changed_period_is_a_changed_figure() -> None:
    d = _gated_dir()
    _pipe_review(d, "Something.")
    _set_inputs(d, founder_stated_inputs_period={"arpu": "month"})
    assert "FOUNDER_INPUT_REWRITTEN" in _warning_codes(_compose_dir(d))


def test_a_change_the_founder_confirmed_in_the_revision_is_not_reported() -> None:
    d = _gated_dir()
    _pipe_review(d, "The deck's blended figure is $385.")
    _set_inputs(d, founder_stated_inputs={"arpu": 385})
    _set_methodology(
        d,
        red_team_revision={
            "approved_by_founder": True,
            "founder_words": "use the blended $385",
            "changes": [{"field": "arpu", "from": 203, "to": 385}],
        },
    )
    _pipe_review(d, "The revised analysis still overstates the share.")
    data = _compose_dir(d)
    assert "FOUNDER_INPUT_REWRITTEN" not in _warning_codes(data)
    assert "revised once, with your approval" in data["report_markdown"]
    rc, html, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0 and "revised once, with your approval" in html, err


def test_a_blanket_approval_does_not_cover_an_unlisted_change() -> None:
    d = _gated_dir()
    _pipe_review(d, "Something.")
    _set_inputs(d, founder_stated_inputs={"arpu": 385})
    _set_methodology(d, red_team_revision={"approved_by_founder": True, "founder_words": "revise", "changes": []})
    assert "FOUNDER_INPUT_REWRITTEN" in _warning_codes(_compose_dir(d))


def test_an_approved_revision_with_no_new_review_says_so() -> None:
    d = _gated_dir({"red_team_revision": {"approved_by_founder": True, "founder_words": "revise", "changes": []}})
    _pipe_review(d, "Only one review ran.")
    md = _compose_dir(d)["report_markdown"]
    assert "no new review of it completed" in md


def test_answers_that_could_not_change_the_analysis_are_shown_not_restated_in_chat() -> None:
    d = _gated_dir(
        {"founder_notes": ["You said the share is 0.5%, as given."], "gate_defaults": ["the revision question"]}
    )
    _pipe_review(d, "Something.")
    md = _compose_dir(d)["report_markdown"]
    assert "## Your Answers" in md and "0.5%, as given" in md and "default was taken for: the revision question" in md


def test_founder_value_overridden_names_the_route_after_the_review() -> None:
    fx = {**_VALID_INPUTS, "founder_stated_inputs": {"arpu": 999999}}
    arts = {
        "inputs.json": fx,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "checklist.json": _VALID_CHECKLIST,
        "sensitivity.json": _VALID_SENSITIVITY,
    }
    rc, data, err = run_script("compose_report.py", ["--dir", _make_artifact_dir(arts)])
    assert rc == 0 and data is not None, err
    msg = next(w["message"] for w in data["validation"]["warnings"] if w["code"] == "FOUNDER_VALUE_OVERRIDDEN")
    assert "Step 6d" in msg and "Recompute from the founder's figure, or put" not in msg


def test_a_revision_round_reads_the_founders_documents_from_the_first_round(tmp_path: Path) -> None:
    """Round 2's own hand-off dir has no docs/: without the flag the prompt would silently say the
    founder supplied nothing, and every document citation would then be refused."""
    d = _gated_dir()
    r1 = d / "handoff" / _CRUN
    (r1 / "docs").mkdir(parents=True)
    (r1 / "docs" / "notes.md").write_text("Recurring $203 per patient month.\n")
    r2 = r1 / "r2"
    r2.mkdir()
    base = [
        "red_team",
        "--run-id",
        _CRUN,
        "--analysis-dir",
        str(d),
        "--handoff-dir",
        str(r2),
        "--handoff-agent",
        "agent/r2",
    ]
    rc, _out, err = run_script_raw("dispatch_prompt.py", base)
    assert rc == 2 and "--review-docs-dir" in err
    rc, out, err = run_script_raw(
        "dispatch_prompt.py", [*base, "--review-docs-dir", str(r1), "--review-docs-agent", "agent"]
    )
    assert rc == 0, err
    assert "agent/docs/notes.md" in out and "OUTPUT_PATH: agent/r2/redteam_output.json" in out


# === Two founder figures for one input: the founder chooses, the other is shown =================


def test_a_founder_figure_the_analysis_did_not_use_is_shown_beside_the_one_it_did() -> None:
    d = _gated_dir()
    _set_inputs(
        d,
        founder_stated_inputs={"arpu": 203},
        founder_stated_inputs_period={"arpu": "month"},
        founder_stated_inputs_source={"arpu": "chat"},
        founder_stated_choice={"arpu": "the $203 I gave you"},
        founder_stated_alternatives={
            "arpu": [
                {
                    "value": 385,
                    "period": "month",
                    "source": "document:deck.pdf#page=2",
                    "label": "blended net collectible",
                }
            ]
        },
    )
    _pipe_review(d, "Something.")
    data = _compose_dir(d)
    md = data["report_markdown"]
    assert "You also gave ARPU $385.00 per month (from deck.pdf, page 2: blended net collectible)" in md
    assert "this analysis uses ARPU $203.00 per month (you gave it in chat), the one you chose" in md
    codes = _warning_codes(data)
    # FOUNDER_VALUE_OVERRIDDEN is not in the list: the fixture's sizing does not use $2,436/yr.
    for code in ("FOUNDER_STATED_MARKET_FIGURE", "EXISTING_CLAIMS_SHAPE", "FOUNDER_TEXT_TOKEN"):
        assert code not in codes, (code, codes)


def test_the_two_figures_question_comes_before_step_a_in_the_skill_text() -> None:
    text = (Path(MARKET_SIZING_DIR).parent / "SKILL.md").read_text(encoding="utf-8")
    q = text.index("**Two figures for one input.**")
    assert q < text.index("**Step A: Output a chat message**")
    block = text[q : text.index("\n\n", q)]
    for needle in (
        "`AskUserQuestion`",
        "`founder_stated_inputs_source`",
        "`founder_stated_alternatives`",
        "never drop one",
    ):
        assert needle in block, needle
    six_d = text[text.index("### Step 6d") : text.index("### Step 7")]
    assert "two-figures question" in six_d


def test_compose_own_warnings_never_name_an_internal_file() -> None:
    """FOUNDER_TEXT_TOKEN's remedy tells the model to fix a label or note IT wrote; a file name in
    compose's own message text would have no such author, and the founder would read it anyway.

    The static (AST) half of this check now lives fleet-wide in
    `test_compose_warn_messages_name_no_files.py`, which covers all six skills including
    market-sizing -- see that file's module docstring for what it can and cannot see (in
    particular: it catches a literal `*.json` token in a message's source, not a filename
    interpolated at runtime). This is the live-compose half: it drives the real producer and
    asserts FOUNDER_TEXT_TOKEN never fires, which the static half cannot do on its own -- a
    fixture-driven run is the only way to see what the fleet founder-text policy actually scans
    at render time, and it can only see a filename that fires in this fixture's fixed inputs
    (so it is not a substitute for the static check's broader, input-independent coverage
    either).
    """
    d = _gated_dir()
    _pipe_review(d, "Something.")
    assert "FOUNDER_TEXT_TOKEN" not in _warning_codes(_compose_dir(d))


# --- Task 8: ratios in factors[] (role: divisor) -----------------------------------------------
#
# A real run needed a RATIO -- "share of X" = 15,000,000 / 64,200,000 x100 = 23.36 -- and had no
# way to itemize it except as two multiplicands, so the reconciliation warning read as a
# nonsensical product ("multiply to 96300000000000000.0"). `factors[]` entries now accept an
# optional `"role": "divisor"`; the derived value is (product of non-divisor entries) / (product
# of divisor entries).
_RATIO_FACTORS = [
    {"factor_id": "target_segment", "value": 15_000_000, "source_id": "company_stated"},
    {"factor_id": "total_market", "value": 64_200_000, "source_id": "health_policy_2026", "role": "divisor"},
]


def test_factor_ratio_reconciles_when_stated_value_matches_the_division() -> None:
    """15,000,000 / 64,200,000 x100 = 23.36 -- a RATIO, not a product of the two raw counts."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 23.36, "category": "derived", "factors": _RATIO_FACTORS}])
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"], data[
        "validation"
    ]["warnings"]


def test_factor_ratio_mismatch_shows_division_and_formatted_numbers() -> None:
    """A stated value that does not reconcile to the division still fires the warning -- and the
    message shows the division (÷), never a nonsensical product, and no raw float leaks
    through: every number in the message is run through the report's own formatter."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 40.0, "category": "derived", "factors": _RATIO_FACTORS}])
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]
    assert len(hit) == 1 and hit[0]["severity"] == "medium", data["validation"]["warnings"]
    msg = hit[0]["message"]
    assert "÷" in msg, msg
    assert "×" not in msg, msg  # two factors, one of them a divisor -- no multiplication sign
    assert "15,000,000" in msg and "64,200,000" in msg, msg
    # The division comes to 23.36..., formatted to two decimals -- not the raw 17-digit float and
    # not the nonsensical "96300000000000000.0" a plain product of the two counts would print.
    assert "23.36" in msg, msg
    assert "e+" not in msg.lower(), msg
    assert "96300000000000000" not in msg, msg


def test_factor_zero_divisor_does_not_crash_and_is_silently_skipped() -> None:
    """A divisor product of zero makes the ratio undefined. compose must not crash (ZeroDivisionError)
    and must not raise a bogus FACTOR_PRODUCT_MISMATCH from an unusable chain."""
    rc, data, _d = _compose_with_validation(
        _validation_with(
            [
                {
                    "name": "segment_pct",
                    "value": 10.0,
                    "category": "derived",
                    "factors": [
                        {"factor_id": "target_segment", "value": 15_000_000, "source_id": "company_stated"},
                        {"factor_id": "total_market", "value": 0, "source_id": "health_policy_2026", "role": "divisor"},
                    ],
                }
            ]
        )
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"], data[
        "validation"
    ]["warnings"]


def test_factor_product_only_chain_still_reconciles_as_before() -> None:
    """A product-only chain (no `role` on any entry) behaves exactly as before role existed."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 10.0, "category": "derived", "factors": _FACTORS_TD}])
    )
    assert rc == 0 and data is not None
    assert not [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]


def test_factor_product_only_chain_still_mismatches_as_before() -> None:
    """0.61*0.60*0.61*0.45 = 10.047 percentage points, not 12 -- unchanged by adding `role`."""
    rc, data, _d = _compose_with_validation(
        _validation_with([{"name": "segment_pct", "value": 12.0, "category": "derived", "factors": _FACTORS_TD}])
    )
    assert rc == 0 and data is not None
    hit = [w for w in data["validation"]["warnings"] if w["code"] == "FACTOR_PRODUCT_MISMATCH"]
    assert len(hit) == 1 and hit[0]["severity"] == "medium", data["validation"]["warnings"]
    assert "10.0" in hit[0]["message"] and "12" in hit[0]["message"]


def test_report_md_shows_division_for_a_ratio_chain() -> None:
    """The 'built from' line under the assumption uses ÷ for a divisor-role factor."""
    _rc, _data, d = _compose_with_validation(
        _validation_with(
            [
                {
                    "name": "segment_pct",
                    "value": 20.0,
                    "category": "derived",
                    "factors": [
                        {"factor_id": "narrow_share", "value": 0.4, "source_id": "company_stated"},
                        {
                            "factor_id": "wide_share",
                            "value": 2.0,
                            "source_id": "health_policy_2026",
                            "role": "divisor",
                        },
                    ],
                }
            ]
        )
    )
    md = _compose_md_text(Path(d))
    assert "built from: 0.4 ÷ 2" in md, md


def test_factor_chain_rejects_an_unrecognized_role() -> None:
    """A `role` value that is neither absent nor `"divisor"` is malformed -- same treatment as a
    missing factor_id: UNSTRUCTURED_DERIVATION, never a crash, never a silent misinterpretation."""
    rc, data, _d = _compose_with_validation(
        _validation_with(
            [
                {
                    "name": "segment_pct",
                    "value": 10.0,
                    "category": "derived",
                    "factors": [
                        {"factor_id": "a", "value": 0.5, "source_id": "s1", "role": "quotient"},
                        {"factor_id": "b", "value": 0.2, "source_id": "s2"},
                    ],
                }
            ]
        )
    )
    assert rc == 0 and data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNSTRUCTURED_DERIVATION" in codes and "FACTOR_PRODUCT_MISMATCH" not in codes, codes


def test_a_ratio_is_shown_in_numbers_a_founder_can_check() -> None:
    """The ratio case this change exists for: `:g` printed it as "1.5e+07 ÷ 6.42e+07" in the one line
    meant to let a founder redo the arithmetic, and a two-place formatter rounded a 0.3732 share."""
    _rc, _data, d = _compose_with_validation(
        _validation_with(
            [
                {"name": "segment_pct", "value": 23.36, "category": "derived", "factors": _RATIO_FACTORS},
                {
                    "name": "serviceable_pct",
                    "value": 99.0,
                    "category": "derived",
                    "factors": [
                        {"factor_id": "a", "value": 0.3732, "source_id": "company_stated"},
                        {"factor_id": "b", "value": 0.5, "source_id": "company_stated"},
                    ],
                },
            ]
        )
    )
    md = _compose_md_text(Path(d))
    assert "built from: 15,000,000 ÷ 64,200,000" in md, md
    assert "e+0" not in md
    assert "0.3732 × 0.5" in md


def test_the_report_never_claims_a_choice_the_founder_was_not_offered() -> None:
    """Measured live: the two-figures question was skipped, and the report still told the founder
    "this analysis uses ARPU $203.00 per month, the one you chose". A choice is claimed only when the
    founder's answer is recorded; otherwise the report says they were not asked."""
    base = {
        "founder_stated_inputs": {"arpu": 203},
        "founder_stated_inputs_period": {"arpu": "month"},
        "founder_stated_alternatives": {
            "arpu": [{"value": 385, "period": "month", "source": "document:deck.pdf#page=2", "label": "blended"}]
        },
    }
    d = _gated_dir()
    _set_inputs(d, **base)  # the live shape: no source, no recorded answer
    _pipe_review(d, "Something.")
    md = _compose_dir(d)["report_markdown"]
    assert "the one you chose" not in md
    assert "You also gave ARPU $385.00 per month" in md
    assert "you were not asked which to use" in md

    d2 = _gated_dir()
    _set_inputs(d2, **base, founder_stated_inputs_source={"arpu": "chat"})  # a source alone is not a choice
    _pipe_review(d2, "Something.")
    assert "the one you chose" not in _compose_dir(d2)["report_markdown"]

    d3 = _gated_dir()
    _set_inputs(d3, **base, founder_stated_choice={"arpu": "Use the $203 recurring rate"})
    _pipe_review(d3, "Something.")
    md3 = _compose_dir(d3)["report_markdown"]
    assert "the one you chose" in md3 and "not asked" not in md3
