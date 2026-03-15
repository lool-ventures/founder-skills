#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for market sizing HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_market_sizing.py -v
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
MARKET_SIZING_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "market-sizing", "scripts")


# ---------------------------------------------------------------------------
# Fixture data (same as test_market_sizing.py)
# ---------------------------------------------------------------------------

_VALID_INPUTS: dict = {
    "company_name": "TestCo",
    "analysis_date": "2026-01-15",
    "materials_provided": ["pitch deck"],
}

_VALID_METHODOLOGY: dict = {
    "approach_chosen": "both",
    "rationale": "Both data sources available",
    "reference_file_read": True,
}

_VALID_VALIDATION: dict = {
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

_VALID_SIZING: dict = {
    "approach": "both",
    "top_down": {
        "tam": {
            "value": 100000000000,
            "formula": "industry_total",
            "inputs": {"industry_total": 100000000000},
        },
        "sam": {
            "value": 6000000000,
            "formula": "tam * segment_pct",
            "inputs": {"tam": 100000000000, "segment_pct": 6},
        },
        "som": {
            "value": 300000000,
            "formula": "sam * share_pct",
            "inputs": {"sam": 6000000000, "share_pct": 5},
        },
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

_VALID_SENSITIVITY: dict = {
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

_BOTH_SENSITIVITY: dict = {
    "approach": "both",
    "base_result": {
        "top_down": {"tam": 1300000000, "sam": 390000000, "som": 58500000},
        "bottom_up": {"tam": 73500000000, "sam": 3675000000, "som": 294000000},
    },
    "scenarios": [
        {
            "parameter": "segment_pct",
            "approach_used": "top_down",
            "confidence": "agent_estimate",
            "low": {"som": 29250000},
            "base": {"som": 58500000},
            "high": {"som": 87750000},
        },
        {
            "parameter": "share_pct",
            "approach_used": "top_down",
            "confidence": "agent_estimate",
            "low": {"som": 29250000},
            "base": {"som": 58500000},
            "high": {"som": 87750000},
        },
        {
            "parameter": "industry_total",
            "approach_used": "top_down",
            "confidence": "sourced",
            "low": {"som": 49725000},
            "base": {"som": 58500000},
            "high": {"som": 76050000},
        },
        {
            "parameter": "serviceable_pct",
            "approach_used": "bottom_up",
            "confidence": "agent_estimate",
            "low": {"som": 117600000},
            "base": {"som": 294000000},
            "high": {"som": 588000000},
        },
        {
            "parameter": "target_pct",
            "approach_used": "bottom_up",
            "confidence": "agent_estimate",
            "low": {"som": 147000000},
            "base": {"som": 294000000},
            "high": {"som": 441000000},
        },
        {
            "parameter": "customer_count",
            "approach_used": "bottom_up",
            "confidence": "sourced",
            "low": {"som": 235200000},
            "base": {"som": 294000000},
            "high": {"som": 441000000},
        },
        {
            "parameter": "arpu",
            "approach_used": "bottom_up",
            "confidence": "derived",
            "low": {"som": 176400000},
            "base": {"som": 294000000},
            "high": {"som": 382200000},
        },
    ],
    "sensitivity_ranking": [
        {"parameter": "serviceable_pct"},
        {"parameter": "segment_pct"},
        {"parameter": "share_pct"},
        {"parameter": "target_pct"},
        {"parameter": "customer_count"},
        {"parameter": "arpu"},
        {"parameter": "industry_total"},
    ],
    "most_sensitive": "serviceable_pct",
}

_VALID_CHECKLIST: dict = {
    "items": [
        {"id": "test", "category": "Test", "label": "Test", "status": "pass", "notes": None},
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


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_artifact_dir(artifacts: dict[str, Any]) -> str:
    """Create a temp dir with JSON artifacts (or raw strings for corrupt data)."""
    d = tempfile.mkdtemp(prefix="test-viz-ms-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            if isinstance(data, str):
                f.write(data)  # For corrupt artifacts
            else:
                json.dump(data, f)
    return d


def _run_visualize(
    artifact_dir: str,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        os.path.join(MARKET_SIZING_DIR, "visualize.py"),
        "--dir",
        artifact_dir,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _all_artifacts() -> dict[str, dict]:
    """Return dict of all 6 valid artifacts."""
    return {
        "inputs.json": _VALID_INPUTS,
        "methodology.json": _VALID_METHODOLOGY,
        "validation.json": _VALID_VALIDATION,
        "sizing.json": _VALID_SIZING,
        "sensitivity.json": _VALID_SENSITIVITY,
        "checklist.json": _VALID_CHECKLIST,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_complete_artifacts() -> None:
    """All 6 artifacts present produces valid HTML with SVG charts."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert stdout.startswith("<!DOCTYPE html>")
    assert "<svg" in stdout
    assert "TestCo" in stdout


def test_missing_optional_artifact() -> None:
    """No sensitivity.json -- HTML renders with placeholder, exit 0."""
    arts = _all_artifacts()
    del arts["sensitivity.json"]
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout
    assert "No data available" in stdout


def test_missing_required_artifact() -> None:
    """No sizing.json -- HTML renders with placeholder for funnel, exit 0."""
    arts = _all_artifacts()
    del arts["sizing.json"]
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout
    assert "No data available" in stdout


def test_corrupt_artifact() -> None:
    """Corrupt JSON for sizing.json -- no crash, placeholder shown."""
    arts: dict[str, dict | str] = dict(_all_artifacts())
    arts["sizing.json"] = "{corrupt json!!!}"
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Data unavailable" in stdout


def test_stub_artifact() -> None:
    """Stub sizing.json with reason -- placeholder shows reason."""
    arts = dict(_all_artifacts())
    arts["sizing.json"] = {"skipped": True, "reason": "Not enough data"}
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Not enough data" in stdout


def test_output_flag() -> None:
    """-o flag writes to file, stdout empty."""
    d = _make_artifact_dir(_all_artifacts())
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, _stderr = _run_visualize(d, extra_args=["-o", tmp])
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
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Find all src="..." and href="..." attributes
    allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
    src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
    for url in src_matches:
        if url in allowed:
            continue
        assert not url.startswith("http://"), f"External HTTP URL in attribute: {url}"
        assert not url.startswith("https://"), f"External HTTPS URL in attribute: {url}"


def test_chart_data_values() -> None:
    """TAM/SAM/SOM formatted values appear in the output."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Top-down TAM = 100B
    assert "$100.0B" in stdout
    # Bottom-up TAM = 67.5B
    assert "$67.5B" in stdout


def test_xss_safety_text() -> None:
    """XSS in company_name is escaped in output."""
    arts = dict(_all_artifacts())
    arts["inputs.json"] = {
        "company_name": "<script>alert(1)</script>",
        "analysis_date": "2026-01-15",
        "materials_provided": ["pitch deck"],
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "&lt;script&gt;" in stdout
    # Injected XSS payload must not appear as a raw HTML element
    assert "<script>alert(" not in stdout


def test_xss_safety_attribute() -> None:
    """XSS in assumption category with attribute injection is escaped."""
    arts = dict(_all_artifacts())
    arts["validation.json"] = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [
            {
                "name": "evil_param",
                "value": 100,
                "category": '"foo" onload="alert(1)"',
            },
        ],
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # The quotes should be escaped -- category becomes a legend label
    assert 'onload="alert(1)"' not in stdout
    assert "&quot;" in stdout


def test_deterministic_output() -> None:
    """Two runs on identical artifacts produce identical HTML bytes."""
    d = _make_artifact_dir(_all_artifacts())
    rc1, stdout1, _ = _run_visualize(d)
    rc2, stdout2, _ = _run_visualize(d)
    assert rc1 == 0
    assert rc2 == 0
    assert stdout1 == stdout2


def test_html_structural_sanity() -> None:
    """Output starts with DOCTYPE, SVG tags are balanced, no raw script tags."""
    d = _make_artifact_dir(_all_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert stdout.startswith("<!DOCTYPE html>")
    # Count SVG open/close tags
    open_count = stdout.count("<svg")
    close_count = stdout.count("</svg>")
    assert open_count == close_count, f"<svg count={open_count} != </svg> count={close_count}"
    assert open_count > 0, "Expected at least one SVG element"
    # Inline JS is allowed; verify script tags are balanced
    script_count = stdout.lower().count("<script")
    script_close = stdout.lower().count("</script>")
    assert script_count == script_close, "Unbalanced script tags"


def test_single_approach_funnel() -> None:
    """Single top_down approach renders one funnel, no bottom_up section."""
    arts = dict(_all_artifacts())
    arts["sizing.json"] = {
        "approach": "top_down",
        "top_down": _VALID_SIZING["top_down"],
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Top-Down" in stdout
    # Should not contain bottom-up funnel label
    assert "Bottom-Up" not in stdout
    # Cross-validation should show placeholder since only one approach
    assert "Cross-validation requires both approaches" in stdout


def test_malformed_list_elements() -> None:
    """Non-dict items in sensitivity scenarios/ranking and assumptions lists don't crash."""
    arts = dict(_all_artifacts())
    # Inject non-dict elements into sensitivity ranking and scenarios
    sens = dict(arts["sensitivity.json"])
    sens["sensitivity_ranking"] = [
        "bad_string",
        {"parameter": "arpu"},
        42,
    ]
    sens["scenarios"] = [
        "also_bad",
        None,
        {
            "parameter": "arpu",
            "low": {"som": 50000},
            "base": {"som": 100000},
            "high": {"som": 150000},
        },
    ]
    arts["sensitivity.json"] = sens
    # Inject non-dict elements into validation assumptions
    val = dict(arts["validation.json"])
    val["assumptions"] = [
        "bad_assumption",
        {"category": "sourced", "name": "arpu"},
        123,
    ]
    arts["validation.json"] = val
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout


def test_unhashable_field_values() -> None:
    """Non-string values in parameter/category fields don't crash (unhashable types)."""
    arts = dict(_all_artifacts())
    # parameter as a list (unhashable)
    sens = dict(arts["sensitivity.json"])
    sens["sensitivity_ranking"] = [
        {"parameter": ["list", "not", "string"]},
    ]
    sens["scenarios"] = [
        {"parameter": ["list", "val"], "low": {"som": 1}, "base": {"som": 2}, "high": {"som": 3}},
    ]
    arts["sensitivity.json"] = sens
    # category as a list (unhashable)
    val = dict(arts["validation.json"])
    val["assumptions"] = [
        {"category": ["not", "a", "string"], "name": "bad"},
    ]
    arts["validation.json"] = val
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout


def test_duplicate_ranking_parameters() -> None:
    """Duplicate parameters in sensitivity_ranking don't produce duplicate bars."""
    arts = dict(_all_artifacts())
    sens = dict(arts["sensitivity.json"])
    sens["sensitivity_ranking"] = [
        {"parameter": "arpu"},
        {"parameter": "arpu"},
        {"parameter": "customer_count"},
    ]
    sens["scenarios"] = [
        {
            "parameter": "arpu",
            "low": {"som": 50000},
            "base": {"som": 100000},
            "high": {"som": 150000},
        },
        {
            "parameter": "customer_count",
            "low": {"som": 60000},
            "base": {"som": 100000},
            "high": {"som": 140000},
        },
    ]
    arts["sensitivity.json"] = sens
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # "arpu" should appear exactly once as a bar label, not twice
    # Labels are title-cased with underscores replaced: "arpu" -> "Arpu"
    arpu_count = stdout.count(">Arpu<")
    assert arpu_count == 1, f"Expected 1 arpu bar, found {arpu_count}"


def test_negative_sam_som_no_crash() -> None:
    """Negative SAM/SOM values don't crash the funnel (no math domain error)."""
    arts = dict(_all_artifacts())
    arts["sizing.json"] = {
        "approach": "top_down",
        "top_down": {
            "tam": {"value": 100000000000, "formula": "total", "inputs": {}},
            "sam": {"value": -5000000000, "formula": "bad", "inputs": {}},
            "som": {"value": -100000000, "formula": "bad", "inputs": {}},
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout


# ---------------------------------------------------------------------------
# Provenance tracking visualization tests
# ---------------------------------------------------------------------------


def test_visualize_provenance_summary_table_has_classification() -> None:
    """validation.json with assumption categories → classification column appears in summary table."""
    arts = _all_artifacts()
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # The provenance summary table should have Classification column
    assert "Classification" in stdout


def test_visualize_provenance_xss() -> None:
    """Provenance notes with <script> → properly escaped."""
    arts = _all_artifacts()
    arts["inputs.json"] = dict(_VALID_INPUTS)
    arts["inputs.json"]["existing_claims"] = {"tam": 50000000000}
    arts["inputs.json"]["company_name"] = '<script>alert("xss")</script>'
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "<script>alert(" not in stdout
    assert "&lt;script&gt;" in stdout


def test_visualize_provenance_summary_table() -> None:
    """When existing_claims exist, provenance summary table is rendered."""
    arts = _all_artifacts()
    arts["inputs.json"] = dict(_VALID_INPUTS)
    arts["inputs.json"]["existing_claims"] = {"tam": 50000000000, "sam": 8000000000}
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Deck Claim" in stdout
    assert "Delta" in stdout
    assert "$50.0B" in stdout


def test_provenance_table_shows_estimate_column() -> None:
    """AC-14: Provenance table has 'Our Estimate' column with correct values."""
    arts = _all_artifacts()
    arts["inputs.json"] = dict(_VALID_INPUTS)
    arts["inputs.json"]["existing_claims"] = {"tam": 50000000000, "sam": 8000000000}
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Column header must be present
    assert "Our Estimate" in stdout
    # Top-down TAM = $100.0B (from _VALID_SIZING["top_down"]["tam"]["value"] = 100000000000)
    assert "$100.0B" in stdout
    # Top-down SAM = $6.0B
    assert "$6.0B" in stdout
    # Top-down SOM = $300.0M
    assert "$300.0M" in stdout
    # Bottom-up TAM = $67.5B
    assert "$67.5B" in stdout
    # Bottom-up SAM = $23.6B (23625000000 → $23.6B)
    assert "$23.6B" in stdout
    # Bottom-up SOM = $118.1M
    assert "$118.1M" in stdout


# ---------------------------------------------------------------------------
# Cross-renderer provenance drift guard
# ---------------------------------------------------------------------------

COMPOSE_REPORT_SCRIPT = os.path.join(MARKET_SIZING_DIR, "compose_report.py")


def _run_compose(artifact_dir: str) -> tuple[int, dict | None, str]:
    """Run compose_report.py and return (exit_code, parsed_json, stderr)."""
    result = subprocess.run(
        [sys.executable, COMPOSE_REPORT_SCRIPT, "--dir", artifact_dir],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def _extract_provenance_from_html(html_text: str) -> dict[str, str]:
    """Extract provenance classifications from the HTML provenance summary table.

    Parses the table rows to get metric -> classification mapping.
    Returns {"TAM (Top-down)": "sourced", ...}.
    """
    provenance: dict[str, str] = {}
    # Find table rows in provenance summary (between <tr> tags after Classification header)
    in_table = False
    for line in html_text.split("\n"):
        if "Classification" in line and "<th" in line:
            in_table = True
            continue
        if in_table and "<tr>" in line:
            # Extract metric and classification from <td> elements
            import re as _re

            cells = _re.findall(r"<td[^>]*>([^<]*)</td>", line)
            if len(cells) >= 2:
                metric = cells[0].strip()
                classification = cells[1].strip()
                if metric and classification:
                    provenance[metric] = classification
        if in_table and "</table>" in line:
            break
    return provenance


def test_provenance_correctness_golden() -> None:
    """Golden test: known fixture → exact expected classifications in compose_report output."""
    validation = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [
            {"name": "industry_total", "value": 100000000000, "category": "sourced"},
            {"name": "segment_pct", "value": 6, "category": "sourced"},
            {"name": "share_pct", "value": 5, "category": "derived"},
            {"name": "customer_count", "value": 4500000, "category": "sourced"},
            {"name": "arpu", "value": 15000, "category": "agent_estimate"},
        ],
    }
    arts = _all_artifacts()
    arts["validation.json"] = validation
    d = _make_artifact_dir(arts)

    rc, data, _stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    provenance = data.get("provenance", {})
    assert provenance, "Expected provenance in output"

    # Top-down TAM: industry_total(sourced) → sourced
    assert provenance["top_down"]["tam"]["classification"] == "sourced"
    # Top-down SAM: segment_pct(sourced) → sourced (tam is intermediate, skipped)
    assert provenance["top_down"]["sam"]["classification"] == "sourced"
    # Top-down SOM: share_pct(derived) → derived (sam is intermediate, skipped)
    assert provenance["top_down"]["som"]["classification"] == "derived"
    # Bottom-up TAM: customer_count(sourced) + arpu(agent_estimate) → agent_estimate
    assert provenance["bottom_up"]["tam"]["classification"] == "agent_estimate"
    # Bottom-up SAM: arpu(agent_estimate) → agent_estimate (serviceable_customers is intermediate)
    assert provenance["bottom_up"]["sam"]["classification"] == "agent_estimate"
    # Bottom-up SOM: arpu(agent_estimate) → agent_estimate (target_customers is intermediate)
    assert provenance["bottom_up"]["som"]["classification"] == "agent_estimate"


def test_provenance_consistency_across_renderers() -> None:
    """Drift guard: compose_report and visualize produce same provenance classifications."""
    validation = {
        "sources": [],
        "figure_validations": [],
        "assumptions": [
            {"name": "industry_total", "value": 100000000000, "category": "sourced"},
            {"name": "segment_pct", "value": 6, "category": "derived"},
            {"name": "share_pct", "value": 5, "category": "sourced"},
            {"name": "customer_count", "value": 4500000, "category": "agent_estimate"},
            {"name": "arpu", "value": 15000, "category": "sourced"},
        ],
    }
    inputs = dict(_VALID_INPUTS)
    inputs["existing_claims"] = {"tam": 50000000000, "sam": 8000000000, "som": 200000000}
    arts = _all_artifacts()
    arts["validation.json"] = validation
    arts["inputs.json"] = inputs
    d = _make_artifact_dir(arts)

    # Run compose_report → get provenance from JSON output
    rc_compose, compose_data, _ = _run_compose(d)
    assert rc_compose == 0
    assert compose_data is not None
    compose_prov = compose_data.get("provenance", {})
    assert compose_prov, "Expected provenance in compose_report output"

    # Run visualize → parse provenance from HTML
    rc_viz, viz_html, _ = _run_visualize(d)
    assert rc_viz == 0

    # Compare at the semantic level: classification per approach/metric
    for approach_key in ("top_down", "bottom_up"):
        if approach_key not in compose_prov:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            compose_class = compose_prov[approach_key][metric]["classification"]
            compose_delta = compose_prov[approach_key][metric].get("delta_vs_deck_pct")

            # Check that the classification appears in the HTML (normalized,
            # since visualize renders human-readable labels like "Agent Estimate")
            normalized = compose_class.lower().replace("_", " ")
            assert normalized in viz_html.lower(), (
                f"Classification '{compose_class}' for {metric.upper()} ({method}) not found in visualize output"
            )

            # Check that delta values appear if they exist
            if compose_delta is not None:
                delta_str = f"{compose_delta:+.1f}%"
                assert delta_str in viz_html, (
                    f"Delta '{delta_str}' for {metric.upper()} ({method}) not found in visualize output"
                )


# ---------------------------------------------------------------------------
# Tornado "both" mode tests
# ---------------------------------------------------------------------------


def test_tornado_both_mode_splits_by_approach() -> None:
    """AC-1/AC-3: 'both' mode renders two tornado sub-sections, partitioned by approach."""
    arts = _all_artifacts()
    arts["sensitivity.json"] = _BOTH_SENSITIVITY
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # AC-1: Two sub-section headings within the Sensitivity section.
    # First extract the Sensitivity section to avoid matching funnel/cross-val labels.
    sens_match = re.search(
        r"<h2[^>]*>Sensitivity Analysis</h2>(.*?)</section>",
        stdout,
        re.DOTALL,
    )
    assert sens_match, "Sensitivity section not found"
    sens_html = sens_match.group(1)
    assert "Top-Down" in sens_html, "Expected Top-Down heading in Sensitivity section"
    assert "Bottom-Up" in sens_html, "Expected Bottom-Up heading in Sensitivity section"
    # AC-3: TD params only in TD tornado, BU params only in BU tornado.
    # Split at the BU h3 heading within the already-extracted sensitivity section
    parts = re.split(r"<h3[^>]*>Bottom-Up</h3>", sens_html, maxsplit=1)
    assert len(parts) == 2, "Expected Top-Down and Bottom-Up sub-sections in tornado"
    td_tornado = parts[0]
    bu_tornado = parts[1]
    assert "Segment Pct" in td_tornado
    assert "Share Pct" in td_tornado
    assert "Industry Total" in td_tornado
    assert "Serviceable Pct" in bu_tornado
    assert "Target Pct" in bu_tornado
    assert "Customer Count" in bu_tornado
    assert "Arpu" in bu_tornado
    # TD params should NOT appear in BU tornado
    assert "Segment Pct" not in bu_tornado
    assert "Industry Total" not in bu_tornado


def test_tornado_both_mode_separate_baselines() -> None:
    """AC-2: Each sub-chart has its own base SOM center line."""
    arts = _all_artifacts()
    arts["sensitivity.json"] = _BOTH_SENSITIVITY
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # TD base SOM = $58.5M, BU base SOM = $294.0M
    assert "Base: $58.5M" in stdout
    assert "Base: $294.0M" in stdout


def test_tornado_single_approach_unchanged() -> None:
    """AC-4: Single-approach sensitivity renders as before (backward compat)."""
    arts = _all_artifacts()
    # _VALID_SENSITIVITY is bottom_up only, no approach_used field
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Base: $118.1M" in stdout  # base_result.som = 118125000
    # Should have bars for customer_count, arpu, target_pct
    assert "Customer Count" in stdout
    assert "Arpu" in stdout
    assert "Target Pct" in stdout


def test_tornado_both_mode_missing_approach_used_skipped() -> None:
    """Scenario without approach_used in 'both' mode is silently skipped with a warning."""
    import copy

    both_sens = copy.deepcopy(_BOTH_SENSITIVITY)
    # Remove approach_used from the "segment_pct" scenario (a top_down param)
    for s in both_sens["scenarios"]:
        if s.get("parameter") == "segment_pct":
            del s["approach_used"]
            break

    arts = _all_artifacts()
    arts["sensitivity.json"] = both_sens
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)

    # 1. Still renders successfully
    assert rc == 0
    assert "<!DOCTYPE html>" in stdout

    # 2. The removed scenario's parameter should NOT appear in either sub-chart
    sens_match = re.search(
        r"<h2[^>]*>Sensitivity Analysis</h2>(.*?)</section>",
        stdout,
        re.DOTALL,
    )
    assert sens_match, "Sensitivity section not found"
    sens_html = sens_match.group(1)
    assert "Segment Pct" not in sens_html, (
        "Expected 'Segment Pct' to be absent from tornado after removing its approach_used"
    )

    # 3. stderr contains a warning about the skipped scenario
    assert "Warning" in stderr or "warning" in stderr
    assert "segment_pct" in stderr


def test_tornado_narrow_bar_labels_no_overlap() -> None:
    """AC-5: Narrow bars have separated low/high labels (no text collision)."""
    arts = _all_artifacts()
    # Create scenario with very narrow range -> tiny bar, plus a wide-range
    # parameter so the scale is stretched and the narrow bar is truly tiny.
    arts["sensitivity.json"] = {
        "approach": "top_down",
        "base_result": {"tam": 1000000000, "sam": 300000000, "som": 50000000},
        "scenarios": [
            {
                "parameter": "industry_total",
                "confidence": "sourced",
                "low": {"som": 49000000},
                "base": {"som": 50000000},
                "high": {"som": 51000000},
            },
            {
                "parameter": "share_pct",
                "confidence": "derived",
                "low": {"som": 10000000},
                "base": {"som": 50000000},
                "high": {"som": 90000000},
            },
        ],
        "sensitivity_ranking": [{"parameter": "industry_total"}, {"parameter": "share_pct"}],
        "most_sensitive": "share_pct",
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # Both labels should appear as separate text elements
    assert "$49.0M" in stdout
    assert "$51.0M" in stdout
    # Parse the two text elements and verify x positions differ by at least
    # the minimum gap (_TORNADO_LABEL_FONT * 5 = 40px).
    label_positions = re.findall(r'<text x="([\d.]+)"[^>]*>\$49\.0M</text>', stdout)
    high_positions = re.findall(r'<text x="([\d.]+)"[^>]*>\$51\.0M</text>', stdout)
    assert label_positions, "Low label ($49.0M) text element not found"
    assert high_positions, "High label ($51.0M) text element not found"
    low_x = float(label_positions[0])
    high_x = float(high_positions[0])
    # Minimum gap should be at least font_size * 5 = 40px
    assert high_x - low_x >= 40.0, f"Labels too close: low_x={low_x}, high_x={high_x}"


def test_cross_validation_per_metric_scaling() -> None:
    """AC-7/AC-8: Extreme ratio between TD and BU still produces visible bars with scale labels."""
    arts = _all_artifacts()
    # Override with MarsGate-like extreme ratios
    arts["sizing.json"] = {
        "approach": "both",
        "top_down": {
            "tam": {"value": 1300000000, "inputs": {}},
            "sam": {"value": 390000000, "inputs": {}},
            "som": {"value": 58500000, "inputs": {}},
        },
        "bottom_up": {
            "tam": {"value": 73500000000, "inputs": {}},
            "sam": {"value": 3675000000, "inputs": {}},
            "som": {"value": 294000000, "inputs": {}},
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # AC-7: All 6 bar values appear in output (meaning bars rendered)
    assert "$1.3B" in stdout
    assert "$73.5B" in stdout
    assert "$390.0M" in stdout
    assert "$3.7B" in stdout  # 3675000000 rounds to $3.7B
    assert "$58.5M" in stdout
    assert "$294.0M" in stdout
    # AC-8: Per-group max scale labels present
    # Each group should have a "max:" label showing its ceiling
    max_labels = re.findall(r"max:\s*\$[\d,.]+[BKMGT]?", stdout)
    assert len(max_labels) >= 3, f"Expected 3 max-scale labels, found {len(max_labels)}: {max_labels}"
    # Bars should have non-trivial heights — extract cross-validation
    # section precisely using the h2 heading and section boundary
    cv_match = re.search(
        r"<h2[^>]*>Cross-Validation Comparison</h2>(.*?)</section>",
        stdout,
        re.DOTALL,
    )
    assert cv_match, "Cross-Validation section not found"
    cv_html = cv_match.group(1)
    # Extract only bar rects (have rx="3" attribute, distinguishing them from
    # scale ceiling lines which are <line> elements)
    cv_bars = re.findall(r'<rect[^>]*height="([\d.]+)"[^>]*rx="3"', cv_html)
    assert len(cv_bars) == 6, f"Expected 6 bars (2 per metric), found {len(cv_bars)}"
    for h in cv_bars:
        assert float(h) > 1.0, f"Bar height {h}px is sub-pixel in cross-validation chart"
    # Within each metric pair, verify per-metric scaling is working
    for i in range(0, 6, 2):
        h_td = float(cv_bars[i])
        h_bu = float(cv_bars[i + 1])
        max_h = max(h_td, h_bu)
        min_h = min(h_td, h_bu)
        assert max_h > 50, f"Metric pair {i // 2}: tallest bar {max_h}px should be near chart_height"
        assert min_h > 0.5, f"Metric pair {i // 2}: shortest bar {min_h}px is not visible"


# ---------------------------------------------------------------------------
# Funnel label overlap and clamped circle tests
# ---------------------------------------------------------------------------


def test_funnel_label_no_overlap_extreme_ratio() -> None:
    """AC-11/AC-13: SAM label moves outside when SAM/TAM ratio is extreme."""
    arts = _all_artifacts()
    arts["sizing.json"] = {
        "approach": "bottom_up",
        "bottom_up": {
            "tam": {"value": 73500000000, "inputs": {}},
            "sam": {"value": 3675000000, "inputs": {}},  # 5% of TAM -> small circle
            "som": {"value": 294000000, "inputs": {}},
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # SAM label should have moved outside — look for leader line with its
    # specific dash pattern (2,2), distinct from tornado baseline (4,3) and
    # clamped-circle (3,2) patterns.
    assert 'stroke-dasharray="2,2"' in stdout, "Expected leader line with dash pattern 2,2"
    # Both SAM and SOM labels should be present
    assert "SAM: $3.7B" in stdout  # 3675000000 -> $3.7B
    assert "SOM: $294.0M" in stdout
    # Verify leader line exists
    leader_lines = re.findall(r'<line[^>]*stroke-dasharray="2,2"[^>]*/>', stdout)
    assert len(leader_lines) >= 1, "Expected at least one leader line"


def test_funnel_clamped_circle_dashed_stroke() -> None:
    """AC-12: Floor-clamped circles have dashed stroke."""
    arts = _all_artifacts()
    arts["sizing.json"] = {
        "approach": "bottom_up",
        "bottom_up": {
            "tam": {"value": 73500000000, "inputs": {}},
            "sam": {"value": 3675000000, "inputs": {}},  # proportional r ~ 22, above min 15
            "som": {"value": 294000000, "inputs": {}},  # proportional r ~ 6.3, below min 8 -> clamped
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # SOM circle should have dashed stroke (it's clamped).
    # Verify by finding the circle with smallest radius and checking it has the dash pattern.
    # Parse all circles with their radii and dash attributes
    circle_matches = re.findall(r'<circle[^>]*r="([\d.]+)"([^>]*)/?>', stdout)
    assert len(circle_matches) >= 3, f"Expected at least 3 circles, found {len(circle_matches)}"
    # Find the smallest-radius circle (should be SOM, clamped to r=8)
    smallest = min(circle_matches, key=lambda m: float(m[0]))
    smallest_r = float(smallest[0])
    smallest_attrs = smallest[1]
    assert smallest_r <= 8.0, f"Smallest circle r={smallest_r}, expected <=8 (clamped SOM)"
    assert 'stroke-dasharray="3,2"' in smallest_attrs, (
        f"Smallest circle (r={smallest_r}) should have dashed stroke for clamped SOM"
    )
    # SAM circle (r~22) should NOT be dashed (it's above the 15px floor)
    sam_circle = [m for m in circle_matches if 20 < float(m[0]) < 30]
    for _r, attrs in sam_circle:
        assert 'stroke-dasharray="3,2"' not in attrs, "SAM circle should not be dashed"


def test_funnel_normal_ratio_no_leader_line() -> None:
    """AC-13: Normal ratio (SAM large relative to TAM) has no leader line."""
    arts = _all_artifacts()
    # Use a single-approach fixture where SAM/TAM ratio is high enough
    # that r_sam stays above the outside-label threshold.
    # Threshold: r_sam < _SAM_LABEL_FONT * 3.5 = 10 * 3.5 = 35
    # Need SAM/TAM >= (35/100)^2 = 12.25%.
    # Use SAM = 25B, TAM = 67.5B -> ratio = 37% -> r_sam = sqrt(0.37)*100 ~ 60.8 > 35
    arts["sizing.json"] = {
        "approach": "bottom_up",
        "bottom_up": {
            "tam": {"value": 67500000000, "inputs": {}},
            "sam": {"value": 25000000000, "inputs": {}},  # 37% of TAM -> r_sam ~ 60.8
            "som": {"value": 5000000000, "inputs": {}},  # 7.4% of TAM -> r_som ~ 27.2 > 8 (not clamped)
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # No leader lines should appear — SAM circle is large enough for inside label
    leader_lines = re.findall(r'<line[^>]*stroke-dasharray="2,2"[^>]*/>', stdout)
    assert len(leader_lines) == 0, f"Expected no leader lines, found {len(leader_lines)}"


# ---------------------------------------------------------------------------
# Key Findings section tests
# ---------------------------------------------------------------------------


def test_key_findings_checklist_failures() -> None:
    """AC-15/AC-17/AC-19: Key Findings shows checklist failures with label and text prefix."""
    arts = _all_artifacts()
    arts["checklist.json"] = {
        "items": [
            {
                "id": "tam_matches_product_scope",
                "category": "Scope",
                "label": "TAM matches product scope",
                "status": "fail",
                "notes": "Scope mismatch",
            },
            {
                "id": "source_segments_match",
                "category": "Data Quality",
                "label": "Source segments match",
                "status": "fail",
                "notes": None,
            },
            {
                "id": "data_current",
                "category": "Data Quality",
                "label": "Data is current",
                "status": "pass",
                "notes": None,
            },
        ],
        "summary": {
            "total": 3,
            "pass": 1,
            "fail": 2,
            "not_applicable": 0,
            "overall_status": "fail",
            "failed_items": [
                "tam_matches_product_scope",
                "source_segments_match",
            ],
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Key Findings" in stdout
    # AC-19: Shows label, not just ID
    assert "TAM matches product scope" in stdout
    assert "Source segments match" in stdout
    # AC-17: Attention subsection present for failures
    assert "needs attention" in stdout.lower()
    # Passing items should NOT appear in attention section
    kf_match = re.search(r"Key Findings</h2>(.*?)</section>", stdout, re.DOTALL)
    assert kf_match, "Key Findings section not found"
    kf_html = kf_match.group(1)
    assert "Data is current" not in kf_html


def test_key_findings_refuted_claims() -> None:
    """AC-15: Key Findings shows refuted/unsupported claims from validation."""
    arts = _all_artifacts()
    arts["validation.json"] = {
        "sources": [],
        "figure_validations": [
            {"figure": "TAM", "status": "refuted", "source_count": 5, "notes": "Conflated market definitions"},
            {"figure": "SAM", "status": "unsupported", "source_count": 0, "notes": "No sources found"},
            {"figure": "SOM", "status": "validated", "source_count": 3},
        ],
        "assumptions": [
            {"name": "customer_count", "value": 4500000, "category": "sourced"},
        ],
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Key Findings" in stdout
    assert "Refuted" in stdout
    assert "TAM" in stdout
    assert "Unsupported" in stdout
    assert "SAM" in stdout
    # Validated items should NOT appear in Key Findings.
    kf_match = re.search(r"Key Findings</h2>(.*?)</section>", stdout, re.DOTALL)
    assert kf_match, "Key Findings section not found"
    kf_html = kf_match.group(1)
    assert "SOM" not in kf_html, "Validated figure SOM should not appear in Key Findings"


def test_key_findings_large_deltas() -> None:
    """AC-15: Key Findings surfaces deltas > +/-50% from provenance."""
    arts = _all_artifacts()
    arts["inputs.json"] = dict(_VALID_INPUTS)
    arts["inputs.json"]["existing_claims"] = {"tam": 50000000000}
    # TD TAM = 100B (from _VALID_SIZING), claim = 50B -> delta = +100%
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "Key Findings" in stdout
    assert "+100.0%" in stdout


def test_key_findings_absent_when_no_signals() -> None:
    """AC-16: Key Findings section has no attention/action items when all pass."""
    arts = _all_artifacts()
    # Default fixtures: all pass, no claims, no refuted
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # With all-passing data, "needs attention" subsection should not appear
    assert "needs attention" not in stdout.lower()
    assert "Top actions" not in stdout


def test_key_findings_structured_subsections() -> None:
    """Key Findings uses structured subsections (attention, actions)."""
    arts = _all_artifacts()
    arts["checklist.json"] = {
        "items": [
            {
                "id": "data_current",
                "category": "Data Quality",
                "label": "Data is current",
                "status": "fail",
                "notes": "Outdated",
            },
        ],
        "summary": {
            "total": 1,
            "pass": 0,
            "fail": 1,
            "not_applicable": 0,
            "overall_status": "fail",
            "failed_items": ["data_current"],
        },
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "finding-attention" in stdout
    assert "Data is current" in stdout
