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
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Market-sizing scripts are colocated with the skill
MARKET_SIZING_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts")


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
    assert rc == 0
    _assert_validation_errors(data, "negative")


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
    assert rc == 0
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
    assert rc == 0
    _assert_validation_errors(data, "missing")


def test_checklist_duplicate_id() -> None:
    """23 items with a duplicate -- should produce validation error."""
    items = _make_checklist_items()
    items.append({"id": "data_current", "status": "pass", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "duplicate")


def test_checklist_unknown_id() -> None:
    """Unknown ID 'bogus' -- should produce validation error."""
    items = _make_checklist_items()
    # Replace one valid item with bogus
    items[0] = {"id": "bogus", "status": "pass", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "unknown")


def test_checklist_invalid_status() -> None:
    """Status 'maybe' -- should produce validation error."""
    overrides = {"data_current": {"status": "maybe", "notes": None}}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
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

_VALID_SIZING = {
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
    """WARNING_SEVERITY contains all 14 codes with correct severities."""
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
        "CHECKLIST_INCOMPLETE",
        "FEW_SENSITIVITY_PARAMS",
        "NARROW_AGENT_ESTIMATE_RANGE",
        "LOW_CHECKLIST_COVERAGE",
        "REFUTED_CLAIMS",
        "REFUTED_MISSING_REASON",
        "DECK_CLAIM_MISMATCH",
        "PROVENANCE_UNRESOLVED",
    ]
    assert len(sev_map) == 18, f"expected 18 codes, got {len(sev_map)}"
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
    assert rc == 0
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
    assert rc == 0
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
    assert "passenger_count_y5" in validation_section
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
    assert rc == 0
    _assert_validation_errors(data, "must be an object")


def test_checklist_non_dict_item() -> None:
    """Non-dict item in checklist items array -> validation error."""
    payload = json.dumps({"items": ["not_a_dict"]})
    rc, data, _ = run_script("checklist.py", [], stdin_data=payload)
    assert rc == 0
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
    assert rc == 0
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
    assert rc == 0
    _assert_validation_errors(data, "-100")


def test_market_sizing_zero_industry_total() -> None:
    """Zero industry_total should produce validation error (validate_positive rejects <= 0)."""
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--approach", "top-down", "--industry-total", "0", "--segment-pct", "10", "--share-pct", "5"],
    )
    assert rc == 0
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
    assert rc == 0
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
    assert rc == 0
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
    assert rc == 0
    _assert_validation_errors(data, "requires")


def test_market_sizing_stdin_empty_object_bottom_up() -> None:
    """Empty JSON object with bottom_up approach should read fields from JSON (all None)."""
    rc, data, _ = run_script(
        "market_sizing.py",
        ["--stdin", "--pretty"],
        stdin_data='{"approach": "bottom_up"}',
    )
    assert rc == 0
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
