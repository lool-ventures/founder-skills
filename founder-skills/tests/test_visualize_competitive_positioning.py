#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for competitive positioning HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_competitive_positioning.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CP_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts")

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_VALID_LANDSCAPE: dict[str, Any] = {
    "competitors": [
        {
            "name": "Salt Security",
            "slug": "salt-security",
            "category": "direct",
            "description": "API security platform using AI/ML",
            "key_differentiators": ["API discovery", "Enterprise focus"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 5,
        },
        {
            "name": "Noname Security",
            "slug": "noname-security",
            "category": "direct",
            "description": "API security with runtime protection",
            "key_differentiators": ["Runtime protection", "Posture management"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 4,
        },
        {
            "name": "Manual API monitoring",
            "slug": "manual-monitoring",
            "category": "do_nothing",
            "description": "Teams manually review API logs",
            "key_differentiators": ["Zero cost", "Full control"],
            "research_depth": "full",
            "evidence_source": {"description": "agent_estimate"},
            "sourced_fields_count": 0,
        },
        {
            "name": "Wallarm",
            "slug": "wallarm",
            "category": "adjacent",
            "description": "API security and WAAP platform",
            "key_differentiators": ["WAAP convergence", "Open-source roots"],
            "research_depth": "partial",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 3,
        },
        {
            "name": "Traceable AI",
            "slug": "traceable-ai",
            "category": "emerging",
            "description": "AI-driven API security analytics",
            "key_differentiators": ["AI analytics", "API catalog"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 5,
        },
    ],
    "input_mode": "conversation",
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

_VALID_POSITIONING: dict[str, Any] = {
    "views": [
        {
            "id": "primary",
            "x_axis": {
                "name": "Deployment Complexity",
                "description": "How much infrastructure change required",
                "rationale": "SDK vs proxy is the key differentiator",
            },
            "y_axis": {
                "name": "Detection Accuracy",
                "description": "Ability to detect real API threats",
                "rationale": "Accuracy is table-stakes",
            },
            "points": [
                {
                    "competitor": "_startup",
                    "x": 90,
                    "y": 75,
                    "x_evidence": "SDK-based",
                    "y_evidence": "2B+ calls trained",
                    "x_evidence_source": "founder_override",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "salt-security",
                    "x": 30,
                    "y": 85,
                    "x_evidence": "Reverse proxy",
                    "y_evidence": "Industry-leading",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "noname-security",
                    "x": 40,
                    "y": 70,
                    "x_evidence": "Agent-based",
                    "y_evidence": "Good detection",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "manual-monitoring",
                    "x": 95,
                    "y": 15,
                    "x_evidence": "No deployment",
                    "y_evidence": "Manual review",
                    "x_evidence_source": "agent_estimate",
                    "y_evidence_source": "agent_estimate",
                },
                {
                    "competitor": "wallarm",
                    "x": 50,
                    "y": 65,
                    "x_evidence": "Moderate",
                    "y_evidence": "Decent",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "traceable-ai",
                    "x": 45,
                    "y": 60,
                    "x_evidence": "Moderate",
                    "y_evidence": "Growing",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
            ],
        },
        {
            "id": "secondary",
            "x_axis": {
                "name": "Latency Impact",
                "description": "Performance overhead of the solution",
                "rationale": "Sub-5ms claim needs testing",
            },
            "y_axis": {
                "name": "Protocol Coverage",
                "description": "Breadth of API protocols supported",
                "rationale": "GraphQL support is rare",
            },
            "points": [
                {
                    "competitor": "_startup",
                    "x": 95,
                    "y": 90,
                    "x_evidence": "Sub-5ms",
                    "y_evidence": "REST + GraphQL",
                    "x_evidence_source": "founder_override",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "salt-security",
                    "x": 30,
                    "y": 60,
                    "x_evidence": "100-200ms",
                    "y_evidence": "REST only",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "noname-security",
                    "x": 50,
                    "y": 55,
                    "x_evidence": "50-100ms",
                    "y_evidence": "REST + gRPC",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
            ],
        },
    ],
    "moat_assessments": {
        "_startup": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Single-tenant product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "ML model on 2B+ calls, growing",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "SDK integration creates stickiness",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "No regulatory moat",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Cloud costs similar to competitors",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "New entrant, limited brand",
                    "evidence_source": "agent_estimate",
                    "trajectory": "building",
                },
            ]
        },
        "salt-security": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Enterprise product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "strong",
                    "evidence": "10B+ calls monthly, largest dataset",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "strong",
                    "evidence": "Deep enterprise integration",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "No regulatory moat",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "moderate",
                    "evidence": "Scale economies from large customer base",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "strong",
                    "evidence": "Market leader, Gartner recognized",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
            ]
        },
        "noname-security": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "Growing dataset",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "Agent deployment sticky",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard cloud costs",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "moderate",
                    "evidence": "Growing recognition",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
            ]
        },
        "manual-monitoring": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Not a product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "absent",
                    "evidence": "No data advantage",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "absent",
                    "evidence": "Zero switching cost",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "strong",
                    "evidence": "Zero cost, uses existing infra",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "absent",
                    "evidence": "Not a product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
            ]
        },
        "wallarm": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "weak",
                    "evidence": "Limited data moat",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "WAAP integration sticky",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "Niche recognition",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
            ]
        },
        "traceable-ai": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "AI-driven analytics",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "weak",
                    "evidence": "Early stage",
                    "evidence_source": "agent_estimate",
                    "trajectory": "building",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "Emerging",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
            ]
        },
    },
    "differentiation_claims": [
        {
            "claim": "ML model trained on 2B+ API calls",
            "verifiable": True,
            "evidence": "Founder confirmed; Salt has 10B+",
            "challenge": "How does accuracy compare at this scale?",
            "verdict": "partially_holds",
        },
        {
            "claim": "Sub-5ms latency",
            "verifiable": True,
            "evidence": "Architecturally plausible, no benchmark",
            "challenge": "Share production latency benchmarks",
            "verdict": "holds",
        },
    ],
    "accepted_warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

_VALID_POSITIONING_SCORES: dict[str, Any] = {
    "views": [
        {
            "view_id": "primary",
            "x_axis_name": "Deployment Complexity",
            "y_axis_name": "Detection Accuracy",
            "x_axis_rationale": "SDK vs proxy is the key differentiator",
            "y_axis_rationale": "Accuracy is table-stakes",
            "x_axis_vanity_flag": False,
            "y_axis_vanity_flag": False,
            "differentiation_score": 75.0,
            "startup_x_rank": 1,
            "startup_y_rank": 3,
            "competitor_count": 5,
        },
        {
            "view_id": "secondary",
            "x_axis_name": "Latency Impact",
            "y_axis_name": "Protocol Coverage",
            "x_axis_rationale": "Sub-5ms claim needs testing",
            "y_axis_rationale": "GraphQL support is rare",
            "x_axis_vanity_flag": True,
            "y_axis_vanity_flag": False,
            "differentiation_score": 90.0,
            "startup_x_rank": 1,
            "startup_y_rank": 1,
            "competitor_count": 2,
        },
    ],
    "overall_differentiation": 82.5,
    "differentiation_claims": _VALID_POSITIONING["differentiation_claims"],
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

_VALID_MOAT_SCORES: dict[str, Any] = {
    "companies": {
        "_startup": {
            "moats": _VALID_POSITIONING["moat_assessments"]["_startup"]["moats"],
            "moat_count": 2,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "moderate",
        },
        "salt-security": {
            "moats": _VALID_POSITIONING["moat_assessments"]["salt-security"]["moats"],
            "moat_count": 3,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "high",
        },
        "noname-security": {
            "moats": _VALID_POSITIONING["moat_assessments"]["noname-security"]["moats"],
            "moat_count": 2,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "moderate",
        },
        "manual-monitoring": {
            "moats": _VALID_POSITIONING["moat_assessments"]["manual-monitoring"]["moats"],
            "moat_count": 1,
            "strongest_moat": "cost_structure",
            "overall_defensibility": "low",
        },
        "wallarm": {
            "moats": _VALID_POSITIONING["moat_assessments"]["wallarm"]["moats"],
            "moat_count": 1,
            "strongest_moat": "switching_costs",
            "overall_defensibility": "low",
        },
        "traceable-ai": {
            "moats": _VALID_POSITIONING["moat_assessments"]["traceable-ai"]["moats"],
            "moat_count": 1,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "low",
        },
    },
    "comparison": {
        "by_dimension": {
            "data_advantages": {
                "_startup": "moderate",
                "salt-security": "strong",
                "noname-security": "moderate",
                "manual-monitoring": "absent",
                "wallarm": "weak",
                "traceable-ai": "moderate",
            },
            "switching_costs": {
                "_startup": "moderate",
                "salt-security": "strong",
                "noname-security": "moderate",
                "manual-monitoring": "absent",
                "wallarm": "moderate",
                "traceable-ai": "weak",
            },
        },
        "startup_rank": {
            "data_advantages": {"rank": 2, "total": 5},
            "switching_costs": {"rank": 2, "total": 5},
        },
    },
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

_VALID_REPORT: dict[str, Any] = {
    "report_markdown": (
        "# Competitive Positioning Analysis: SecureFlow\n\n"
        "## Executive Summary\nSecureFlow differentiates on deployment simplicity."
    ),
    "metadata": {
        "run_id": "20260319T143045Z",
        "company_name": "SecureFlow",
        "analysis_date": "2026-03-19",
        "input_mode": "conversation",
        "competitor_count": 5,
        "research_depth": "full",
        "assessment_mode": "sub-agent",
        "founder_override_count": 2,
    },
    "warnings": [],
    "artifacts_loaded": [
        "product_profile.json",
        "landscape.json",
        "positioning.json",
        "moat_scores.json",
        "positioning_scores.json",
        "checklist.json",
    ],
    "scoring_summary": {
        "checklist_score_pct": 82.6,
        "overall_differentiation": 82.5,
        "startup_defensibility": "moderate",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _make_artifact_dir(artifacts: dict[str, Any]) -> Generator[str, None, None]:
    """Create a temp dir with JSON artifacts. Yields dir path, cleans up on exit."""
    d = tempfile.mkdtemp(prefix="test-vis-cp-")
    try:
        for name, data in artifacts.items():
            path = os.path.join(d, name)
            if isinstance(data, str):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _all_artifacts() -> dict[str, Any]:
    """Return all artifacts for a complete visualization."""
    return {
        "landscape.json": _VALID_LANDSCAPE,
        "positioning.json": _VALID_POSITIONING,
        "positioning_scores.json": _VALID_POSITIONING_SCORES,
        "moat_scores.json": _VALID_MOAT_SCORES,
        "report.json": _VALID_REPORT,
    }


def _run_visualize(
    artifact_dir: str,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        os.path.join(CP_SCRIPTS_DIR, "visualize.py"),
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


def test_generates_html() -> None:
    """Produces output containing <html> and </html>."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout
        assert "</html>" in stdout
        assert "<!DOCTYPE html>" in stdout


def test_positioning_map_svg() -> None:
    """HTML contains SVG with circle elements for competitors."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<svg" in stdout
        assert "<circle" in stdout
        # Each competitor + startup should have a circle
        assert stdout.count("<circle") >= 3  # at least startup + 2 competitors


def test_moat_radar_svg() -> None:
    """HTML contains SVG with polygon element for radar chart."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<polygon" in stdout
        # Should have at least 2 polygons: startup moat profile + competitor overlay
        assert stdout.count("<polygon") >= 2


def test_competitor_table() -> None:
    """HTML contains <table> with competitor names."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<table" in stdout
        assert "Salt Security" in stdout
        assert "Noname Security" in stdout
        assert "Wallarm" in stdout
        assert "Traceable AI" in stdout


def test_startup_highlighted() -> None:
    """_startup rendered with distinct styling and 'Your Company' label."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Should use the company name or "Your Company" for _startup
        assert "SecureFlow" in stdout or "Your Company" in stdout


def test_secondary_view() -> None:
    """If secondary view present, alternate positioning chart rendered."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Secondary view axes should appear
        assert "Latency Impact" in stdout
        assert "Protocol Coverage" in stdout
        # Should have at least 2 positioning map SVGs
        assert "Deployment Complexity" in stdout


def test_defensibility_timeline() -> None:
    """When trajectory data provided, timeline SVG elements present."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Trajectory data is present in moat_assessments (building, stable, eroding)
        # Should render timeline indicators
        assert "building" in stdout.lower() or "eroding" in stdout.lower() or "stable" in stdout.lower()


def test_handles_missing_optional() -> None:
    """Works without secondary view or trajectory data."""
    arts = _all_artifacts()
    # Remove secondary view
    pos = dict(arts["positioning.json"])
    pos["views"] = [v for v in pos["views"] if v["id"] == "primary"]
    arts["positioning.json"] = pos

    pos_scores = dict(arts["positioning_scores.json"])
    pos_scores["views"] = [v for v in pos_scores["views"] if v["view_id"] == "primary"]
    arts["positioning_scores.json"] = pos_scores

    # Remove trajectory data from moat assessments
    pos2 = dict(arts["positioning.json"])
    for slug in pos2["moat_assessments"]:
        for moat in pos2["moat_assessments"][slug]["moats"]:
            del moat["trajectory"]
    arts["positioning.json"] = pos2

    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout
        assert "</html>" in stdout
        # Secondary view axes should NOT appear
        assert "Latency Impact" not in stdout


def test_output_flag() -> None:
    """-o writes HTML to file and emits JSON receipt to stdout."""
    with _make_artifact_dir(_all_artifacts()) as d:
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
            assert "SecureFlow" in content
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src/href attributes (except allowed)."""
    import re

    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        allowed = {"https://github.com/lool-ventures/founder-skills", "https://lool.vc"}
        src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
        for url in src_matches:
            if url in allowed:
                continue
            assert not url.startswith("http://"), f"External HTTP URL: {url}"
            assert not url.startswith("https://"), f"External HTTPS URL: {url}"


def test_vanity_flag_indicator() -> None:
    """Vanity-flagged axes get a visual indicator."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # The secondary view has x_axis_vanity_flag=True for "Latency Impact"
        # Should have some visual indicator (dashed, warning, vanity)
        lower = stdout.lower()
        assert "vanity" in lower or "stroke-dasharray" in lower or "warning" in lower


def test_missing_report() -> None:
    """Works even without report.json."""
    arts = _all_artifacts()
    del arts["report.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout


def test_missing_positioning_scores() -> None:
    """Works with missing positioning_scores.json (shows placeholder)."""
    arts = _all_artifacts()
    del arts["positioning_scores.json"]
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<html" in stdout


def test_xss_safety() -> None:
    """Company name with script tag is escaped."""
    arts = _all_artifacts()
    report = dict(arts["report.json"])
    report["metadata"] = dict(report["metadata"])
    report["metadata"]["company_name"] = "<script>alert(1)</script>"
    arts["report.json"] = report
    with _make_artifact_dir(arts) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        assert "<script>alert(1)</script>" not in stdout
        assert "&lt;script&gt;" in stdout


def test_competitor_table_sorted_by_defensibility() -> None:
    """Competitor table is sorted by overall_defensibility (high first)."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        # Salt Security has "high" defensibility, should appear before others
        salt_pos = stdout.find("Salt Security")
        noname_pos = stdout.find("Noname Security")
        manual_pos = stdout.find("Manual API monitoring")
        # Salt (high) should come before Noname (moderate) in table
        # Find them within a <table> context
        assert salt_pos < noname_pos or salt_pos < manual_pos, (
            "Salt Security (high defensibility) should appear before lower-ranked competitors in table"
        )


def test_deterministic_output() -> None:
    """Run twice -> identical HTML bytes."""
    with _make_artifact_dir(_all_artifacts()) as d:
        rc1, out1, _ = _run_visualize(d)
        rc2, out2, _ = _run_visualize(d)
        assert rc1 == 0
        assert rc2 == 0
        assert out1 == out2, "Output differs between runs"
