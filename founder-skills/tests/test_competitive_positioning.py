#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for competitive positioning scripts.

Run: pytest founder-skills/tests/test_competitive_positioning.py -v
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
CP_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts")


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(CP_SCRIPTS_DIR, name)]
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
    cmd = [sys.executable, os.path.join(CP_SCRIPTS_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Factory: valid landscape_enriched.json input
# ---------------------------------------------------------------------------


def _make_competitor(
    name: str,
    slug: str,
    category: str = "direct",
    *,
    research_depth: str = "full",
    sourced_fields_count: int = 5,
    evidence_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single enriched competitor entry."""
    return {
        "name": name,
        "slug": slug,
        "category": category,
        "description": f"{name} is a competitor in the market.",
        "key_differentiators": ["Feature A", "Feature B"],
        "pricing_model": "SaaS, $99/mo",
        "funding": "Series A, $10M",
        "strengths": ["Good product"],
        "weaknesses": ["Small team"],
        "evidence_source": evidence_source or {"description": "researched", "pricing_model": "researched"},
        "research_depth": research_depth,
        "sourced_fields_count": sourced_fields_count,
    }


def _make_valid_landscape(
    *,
    competitors: list[dict[str, Any]] | None = None,
    input_mode: str = "conversation",
    research_depth: str = "full",
    run_id: str = "20260319T143045Z",
    data_confidence: float | None = None,
) -> dict[str, Any]:
    """Build a valid landscape_enriched.json payload with 5 competitors."""
    if competitors is None:
        competitors = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Manual Process", "manual-process", "do_nothing"),
        ]
    result: dict[str, Any] = {
        "competitors": competitors,
        "assessment_mode": "sub-agent",
        "research_depth": research_depth,
        "input_mode": input_mode,
        "metadata": {"run_id": run_id},
    }
    if data_confidence is not None:
        result["data_confidence"] = data_confidence
    return result


# ===========================================================================
# validate_landscape.py tests
# ===========================================================================


class TestValidateLandscape:
    """Tests for validate_landscape.py."""

    # 1. Well-formed input passes
    def test_valid_landscape_passes(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "competitors" in data
        assert len(data["competitors"]) == 5
        assert "warnings" in data
        assert isinstance(data["warnings"], list)
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        assert data["input_mode"] == "conversation"

    # 2. Missing required field fails
    def test_missing_required_field_fails(self) -> None:
        payload = _make_valid_landscape()
        del payload["competitors"][0]["slug"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 3. Duplicate slugs fails
    def test_duplicate_slugs_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][1]["slug"] = payload["competitors"][0]["slug"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 4. Missing do_nothing warns
    def test_missing_do_nothing_warns(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "direct"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Epsilon SA", "epsilon-sa", "direct"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_DO_NOTHING" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MISSING_DO_NOTHING")
        assert warn["severity"] == "medium"

    # 5. Adjacent only suppresses warning
    def test_adjacent_only_suppresses_warning(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Epsilon SA", "epsilon-sa", "direct"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_DO_NOTHING" not in codes

    # 6. Invalid category fails
    def test_invalid_category_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["category"] = "bogus"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 7. Bounds min fails (2 competitors)
    def test_bounds_min_fails(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "do_nothing"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 8. Bounds max fails (11 competitors)
    def test_bounds_max_fails(self) -> None:
        comps = [_make_competitor(f"Comp {i}", f"comp-{i}", "direct") for i in range(11)]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 9. Preserves provenance fields
    def test_preserves_provenance(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        for comp in data["competitors"]:
            assert "research_depth" in comp, f"Missing research_depth in {comp['slug']}"
            assert "evidence_source" in comp, f"Missing evidence_source in {comp['slug']}"
            assert "sourced_fields_count" in comp, f"Missing sourced_fields_count in {comp['slug']}"
        # Check specific values
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["research_depth"] == "full"
        assert alpha["sourced_fields_count"] == 5
        assert alpha["evidence_source"]["description"] == "researched"

    # 10. _startup slug rejected
    def test_startup_slug_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["slug"] = "_startup"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 10b. Invalid research_depth enum value fails
    def test_invalid_research_depth_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["research_depth"] = "high"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "research_depth" in stderr
        assert "high" in stderr

    # 10c. empty slug rejected
    def test_empty_slug_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["slug"] = ""
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "non-empty" in stderr.lower()

    # 11. data_confidence passthrough
    def test_data_confidence_passthrough(self) -> None:
        payload = _make_valid_landscape(data_confidence=0.85)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("data_confidence") == 0.85

    # 12. --pretty flag produces indented JSON
    def test_pretty_flag(self) -> None:
        payload = _make_valid_landscape()
        rc, raw_stdout, stderr = run_script_raw(
            "validate_landscape.py",
            args=["--pretty"],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        # Pretty-printed JSON contains newlines and indentation
        assert "\n " in raw_stdout
        # Should still be valid JSON
        data = json.loads(raw_stdout)
        assert "competitors" in data

    # 13. -o writes to file, receipt JSON to stdout
    def test_output_file(self) -> None:
        payload = _make_valid_landscape()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            rc, data, stderr = run_script(
                "validate_landscape.py",
                args=["-o", tmp_path],
                stdin_data=json.dumps(payload),
            )
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            # stdout should be a receipt
            assert data is not None
            assert data["ok"] is True
            assert data["path"] == os.path.abspath(tmp_path)
            assert "bytes" in data
            # File should contain the full landscape JSON
            with open(tmp_path, encoding="utf-8") as f:
                file_data = json.load(f)
            assert "competitors" in file_data
            assert len(file_data["competitors"]) == 5
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Factory: valid moat_assessments input for score_moats.py
# ---------------------------------------------------------------------------

CANONICAL_MOAT_IDS = [
    "network_effects",
    "data_advantages",
    "switching_costs",
    "regulatory_barriers",
    "cost_structure",
    "brand_reputation",
]


def _make_moat_entry(
    moat_id: str,
    *,
    status: str = "moderate",
    evidence: str = "Sufficient evidence for this moat dimension assessment.",
    evidence_source: str = "researched",
    trajectory: str = "stable",
) -> dict[str, Any]:
    """Build a single moat entry."""
    return {
        "id": moat_id,
        "status": status,
        "evidence": evidence,
        "evidence_source": evidence_source,
        "trajectory": trajectory,
    }


def _make_company_moats(
    *,
    statuses: dict[str, str] | None = None,
    extra_moats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a moats object for one company."""
    statuses = statuses or {}
    moats = []
    for mid in CANONICAL_MOAT_IDS:
        moats.append(_make_moat_entry(mid, status=statuses.get(mid, "moderate")))
    if extra_moats:
        moats.extend(extra_moats)
    return {"moats": moats}


def _make_valid_moat_input(
    *,
    startup_statuses: dict[str, str] | None = None,
    competitor_statuses: dict[str, str] | None = None,
    extra_startup_moats: list[dict[str, Any]] | None = None,
    data_confidence: str | None = None,
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a valid score_moats.py input with _startup + 1 competitor."""
    result: dict[str, Any] = {
        "moat_assessments": {
            "_startup": _make_company_moats(statuses=startup_statuses, extra_moats=extra_startup_moats),
            "acme-corp": _make_company_moats(statuses=competitor_statuses),
        },
        "metadata": {"run_id": run_id},
    }
    if data_confidence is not None:
        result["data_confidence"] = data_confidence
    return result


# ===========================================================================
# score_moats.py tests
# ===========================================================================


class TestScoreMoats:
    """Tests for score_moats.py."""

    # 1. Well-formed input passes
    def test_score_moats_valid_passes(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "companies" in data
        assert "_startup" in data["companies"]
        assert "acme-corp" in data["companies"]
        assert "comparison" in data
        assert "warnings" in data
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        # Each company should have moats + aggregates
        for slug in ("_startup", "acme-corp"):
            co = data["companies"][slug]
            assert "moats" in co
            assert "moat_count" in co
            assert "strongest_moat" in co
            assert "overall_defensibility" in co

    # 2. Custom moat accepted
    def test_score_moats_custom_moat_accepted(self) -> None:
        custom = _make_moat_entry("custom_ip_patents", status="strong")
        payload = _make_valid_moat_input(extra_startup_moats=[custom])
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        startup_ids = [m["id"] for m in data["companies"]["_startup"]["moats"]]
        assert "custom_ip_patents" in startup_ids

    # 3. Missing canonical moat produces warning
    def test_score_moats_missing_canonical_warns(self) -> None:
        payload = _make_valid_moat_input()
        # Remove one canonical moat from _startup
        payload["moat_assessments"]["_startup"]["moats"] = [
            m for m in payload["moat_assessments"]["_startup"]["moats"] if m["id"] != "brand_reputation"
        ]
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_CANONICAL_MOAT" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MISSING_CANONICAL_MOAT")
        assert "_startup" in warn["message"]
        assert "brand_reputation" in warn["message"]

    # 4. Strong without evidence warns
    def test_score_moats_strong_without_evidence_warns(self) -> None:
        payload = _make_valid_moat_input(startup_statuses={"network_effects": "strong"})
        # Shorten the evidence for the strong moat
        for m in payload["moat_assessments"]["_startup"]["moats"]:
            if m["id"] == "network_effects":
                m["evidence"] = "Short."
                break
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MOAT_WITHOUT_EVIDENCE" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MOAT_WITHOUT_EVIDENCE")
        assert warn["severity"] == "medium"
        assert "_startup" in warn.get("company", "")

    # 5. Per-company aggregates
    def test_score_moats_per_company_aggregates(self) -> None:
        payload = _make_valid_moat_input(
            startup_statuses={
                "network_effects": "strong",
                "data_advantages": "strong",
                "switching_costs": "moderate",
                "regulatory_barriers": "absent",
                "cost_structure": "not_applicable",
                "brand_reputation": "weak",
            }
        )
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        startup = data["companies"]["_startup"]
        # moat_count: non-absent, non-na => strong(2) + moderate(1) + weak(1) = 4
        assert startup["moat_count"] == 4
        assert startup["strongest_moat"] == "network_effects"
        assert startup["overall_defensibility"] == "high"  # 2+ strong

    # 6. Comparison section present
    def test_score_moats_comparison_section(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        comp = data["comparison"]
        assert "by_dimension" in comp
        assert "startup_rank" in comp
        # Each canonical moat should be in by_dimension
        for mid in CANONICAL_MOAT_IDS:
            assert mid in comp["by_dimension"], f"Missing {mid} in by_dimension"
            assert "_startup" in comp["by_dimension"][mid]
            assert "acme-corp" in comp["by_dimension"][mid]
        # startup_rank should have entries for canonical moats
        for mid in CANONICAL_MOAT_IDS:
            assert mid in comp["startup_rank"], f"Missing {mid} in startup_rank"
            rank_info = comp["startup_rank"][mid]
            assert "rank" in rank_info
            assert "total" in rank_info

    # 7. _startup key processed correctly
    def test_score_moats_startup_included(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "_startup" in data["companies"]
        startup = data["companies"]["_startup"]
        assert len(startup["moats"]) == 6

    # 8. Data confidence qualifier
    def test_score_moats_data_confidence_qualifier(self) -> None:
        payload = _make_valid_moat_input(data_confidence="estimated")
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # Evidence strings should be qualified
        for m in data["companies"]["_startup"]["moats"]:
            assert "(based on estimated inputs)" in m["evidence"]

    # 9. Invalid trajectory fails
    def test_score_moats_invalid_trajectory_fails(self) -> None:
        payload = _make_valid_moat_input()
        payload["moat_assessments"]["_startup"]["moats"][0]["trajectory"] = "declining"
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"


# ---------------------------------------------------------------------------
# Factory: valid positioning input for score_positioning.py
# ---------------------------------------------------------------------------


def _make_positioning_point(
    competitor: str,
    x: int | float,
    y: int | float,
) -> dict[str, Any]:
    """Build a single positioning point entry."""
    return {
        "competitor": competitor,
        "x": x,
        "y": y,
        "x_evidence": f"Evidence for {competitor} on x-axis",
        "y_evidence": f"Evidence for {competitor} on y-axis",
        "x_evidence_source": "researched",
        "y_evidence_source": "researched",
    }


def _make_valid_positioning_input(
    *,
    views: list[dict[str, Any]] | None = None,
    differentiation_claims: list[dict[str, Any]] | None = None,
    data_confidence: str = "exact",
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a valid score_positioning.py input with primary view + 5 competitors + _startup."""
    if views is None:
        views = [
            {
                "id": "primary",
                "x_axis": {
                    "name": "Deployment Speed",
                    "description": "How fast the solution can be deployed",
                    "rationale": "Speed-to-value is a key differentiator for SMB buyers",
                },
                "y_axis": {
                    "name": "Data Privacy Level",
                    "description": "Degree of data privacy guarantees",
                    "rationale": "Privacy is a growing concern in the target market",
                },
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                    _make_positioning_point("delta-co", 20, 60),
                    _make_positioning_point("epsilon-sa", 70, 30),
                ],
            }
        ]
    if differentiation_claims is None:
        differentiation_claims = [
            {
                "claim": "Sub-5ms latency vs. competitors' 50-200ms",
                "verifiable": True,
                "evidence": "SDK-based approach avoids network hop",
                "challenge": "No independent benchmark found",
                "verdict": "holds",
            }
        ]
    return {
        "views": views,
        "differentiation_claims": differentiation_claims,
        "metadata": {"run_id": run_id},
        "data_confidence": data_confidence,
    }


# ===========================================================================
# score_positioning.py tests
# ===========================================================================


class TestScorePositioning:
    """Tests for score_positioning.py."""

    # 1. Well-formed input passes
    def test_score_positioning_valid_passes(self) -> None:
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "views" in data
        assert len(data["views"]) == 1
        assert "overall_differentiation" in data
        assert "differentiation_claims" in data
        assert "warnings" in data
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        view = data["views"][0]
        assert view["view_id"] == "primary"
        assert view["competitor_count"] == 5
        assert "differentiation_score" in view
        assert "startup_x_rank" in view
        assert "startup_y_rank" in view
        assert "x_axis_vanity_flag" in view
        assert "y_axis_vanity_flag" in view

    # 2. Vanity axis detected when >80% of competitors cluster within 20% range
    def test_score_positioning_vanity_axis_detected(self) -> None:
        # 5 competitors all with x in [40, 60] (within 20% range), _startup at 90
        points = [
            _make_positioning_point("_startup", 90, 85),
            _make_positioning_point("acme-corp", 42, 40),
            _make_positioning_point("beta-inc", 45, 70),
            _make_positioning_point("gamma-ltd", 50, 50),
            _make_positioning_point("delta-co", 48, 60),
            _make_positioning_point("epsilon-sa", 55, 30),
        ]
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points,
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        view = data["views"][0]
        # All 5 competitors (100% > 80%) are within [42, 55] — range of 13 < 20
        assert view["x_axis_vanity_flag"] is True
        # y-axis has spread [30, 70] — range 40 > 20, not vanity
        assert view["y_axis_vanity_flag"] is False
        # Should have VANITY_AXIS_WARNING
        codes = [w["code"] for w in data["warnings"]]
        assert "VANITY_AXIS_WARNING" in codes

    # 3. Non-vanity axis — spread competitors don't trigger vanity
    def test_score_positioning_non_vanity_axis(self) -> None:
        points = [
            _make_positioning_point("_startup", 90, 85),
            _make_positioning_point("acme-corp", 10, 20),
            _make_positioning_point("beta-inc", 30, 80),
            _make_positioning_point("gamma-ltd", 50, 50),
            _make_positioning_point("delta-co", 70, 40),
            _make_positioning_point("epsilon-sa", 90, 10),
        ]
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points,
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        view = data["views"][0]
        assert view["x_axis_vanity_flag"] is False
        assert view["y_axis_vanity_flag"] is False

    # 4. Rank-based differentiation — startup ranked 1st scores high; middle scores low
    #    Uses distance-weighted formula: rank 50% + gap 50%
    def test_score_positioning_rank_based_differentiation(self) -> None:
        # Startup at top of both axes (rank 1 on both) with moderate gap
        points_top = [
            _make_positioning_point("_startup", 95, 95),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
            _make_positioning_point("delta-co", 20, 20),
        ]
        views_top = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_top,
            }
        ]
        payload_top = _make_valid_positioning_input(views=views_top)
        rc, data_top, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload_top))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data_top is not None

        # Startup in middle of both axes
        points_mid = [
            _make_positioning_point("_startup", 50, 50),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
            _make_positioning_point("delta-co", 20, 20),
        ]
        views_mid = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_mid,
            }
        ]
        payload_mid = _make_valid_positioning_input(views=views_mid)
        rc2, data_mid, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload_mid))
        assert rc2 == 0, f"Expected exit 0, got {rc2}. stderr: {stderr2}"
        assert data_mid is not None

        top_score = data_top["views"][0]["differentiation_score"]
        mid_score = data_mid["views"][0]["differentiation_score"]
        assert top_score > mid_score, f"Top score {top_score} should exceed mid score {mid_score}"
        # Distance-weighted: rank 1 of 4 => rank_score = 50, gap (95-80)/100 = 0.15 => gap_score = 7.5
        # Per axis: 57.5, average of two axes: 57.5
        assert top_score == 57.5
        # Mid: rank 3 of 4 => rank_score = 25, gap = 0 (behind top competitor)
        # Per axis: 25.0, average: 25.0
        assert mid_score == 25.0

    # 4b. Distance-weighted scoring: larger gap produces higher score at same rank
    def test_score_positioning_gap_distinguishes_barely_vs_dramatically_ahead(self) -> None:
        # Scenario A: startup barely ahead (rank 1, gap 2%)
        points_barely = [
            _make_positioning_point("_startup", 82, 82),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
        ]
        views_barely = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_barely,
            }
        ]
        payload_barely = _make_valid_positioning_input(views=views_barely)
        rc1, data_barely, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(payload_barely))
        assert rc1 == 0, f"stderr: {stderr1}"
        assert data_barely is not None

        # Scenario B: startup dramatically ahead (rank 1, gap 40%)
        points_dramatic = [
            _make_positioning_point("_startup", 95, 95),
            _make_positioning_point("acme-corp", 55, 55),
            _make_positioning_point("beta-inc", 40, 40),
            _make_positioning_point("gamma-ltd", 20, 20),
        ]
        views_dramatic = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_dramatic,
            }
        ]
        payload_dramatic = _make_valid_positioning_input(views=views_dramatic)
        rc2, data_dramatic, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload_dramatic))
        assert rc2 == 0, f"stderr: {stderr2}"
        assert data_dramatic is not None

        barely_score = data_barely["views"][0]["differentiation_score"]
        dramatic_score = data_dramatic["views"][0]["differentiation_score"]
        # Both are rank 1, but dramatic gap should score meaningfully higher
        assert dramatic_score > barely_score, (
            f"Dramatic gap score {dramatic_score} should exceed barely-ahead score {barely_score}"
        )

    # 5. Secondary view gets its own scores
    def test_score_positioning_secondary_view_scored(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X1", "description": "...", "rationale": "x1 rationale"},
                "y_axis": {"name": "Y1", "description": "...", "rationale": "y1 rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 80),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            },
            {
                "id": "secondary",
                "x_axis": {"name": "X2", "description": "...", "rationale": "x2 rationale"},
                "y_axis": {"name": "Y2", "description": "...", "rationale": "y2 rationale"},
                "points": [
                    _make_positioning_point("_startup", 20, 30),
                    _make_positioning_point("acme-corp", 80, 90),
                    _make_positioning_point("beta-inc", 50, 60),
                ],
            },
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert len(data["views"]) == 2
        ids = [v["view_id"] for v in data["views"]]
        assert "primary" in ids
        assert "secondary" in ids
        # Each view has its own scores
        for v in data["views"]:
            assert "differentiation_score" in v
            assert "startup_x_rank" in v
            assert "startup_y_rank" in v

    # 6. Aggregate differentiation computed across views
    def test_score_positioning_aggregate_differentiation(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X1", "description": "...", "rationale": "x1 rationale"},
                "y_axis": {"name": "Y1", "description": "...", "rationale": "y1 rationale"},
                "points": [
                    _make_positioning_point("_startup", 95, 95),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            },
            {
                "id": "secondary",
                "x_axis": {"name": "X2", "description": "...", "rationale": "x2 rationale"},
                "y_axis": {"name": "Y2", "description": "...", "rationale": "y2 rationale"},
                "points": [
                    _make_positioning_point("_startup", 20, 30),
                    _make_positioning_point("acme-corp", 80, 90),
                    _make_positioning_point("beta-inc", 50, 60),
                ],
            },
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # overall_differentiation should be average of per-view scores
        scores = [v["differentiation_score"] for v in data["views"]]
        expected = round(sum(scores) / len(scores), 1)
        assert data["overall_differentiation"] == expected

    # 7. Missing _startup fails
    def test_score_positioning_missing_startup_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 8. Stress-test passthrough — differentiation_claims passed through
    def test_score_positioning_stress_test_passthrough(self) -> None:
        claims = [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data shows <5ms",
                "challenge": "No third-party validation",
                "verdict": "holds",
            },
            {
                "claim": "Only GraphQL support",
                "verifiable": True,
                "evidence": "Competitor analysis confirms",
                "challenge": "Others may add it soon",
                "verdict": "partially_holds",
            },
        ]
        payload = _make_valid_positioning_input(differentiation_claims=claims)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert len(data["differentiation_claims"]) == 2
        assert data["differentiation_claims"][0]["claim"] == "Best latency in market"
        assert data["differentiation_claims"][1]["verdict"] == "partially_holds"

    # 9. Data confidence passthrough
    def test_score_positioning_data_confidence_passthrough(self) -> None:
        payload = _make_valid_positioning_input(data_confidence="estimated")
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("data_confidence") == "estimated"


# ---------------------------------------------------------------------------
# Factory: valid checklist input for checklist.py
# ---------------------------------------------------------------------------

# Canonical 25 checklist item IDs — must match checklist-criteria.md exactly.
CHECKLIST_IDS: list[str] = [
    # Competitor Coverage (5)
    "COVER_01",
    "COVER_02",
    "COVER_03",
    "COVER_04",
    "COVER_05",
    # Positioning Quality (5)
    "POS_01",
    "POS_02",
    "POS_03",
    "POS_04",
    "POS_05",
    # Moat Assessment (4)
    "MOAT_01",
    "MOAT_02",
    "MOAT_03",
    "MOAT_04",
    # Evidence Quality (4)
    "EVID_01",
    "EVID_02",
    "EVID_03",
    "EVID_04",
    # Narrative Readiness (4)
    "NARR_01",
    "NARR_02",
    "NARR_03",
    "NARR_04",
    # Common Mistakes (3)
    "MISS_01",
    "MISS_02",
    "MISS_03",
]


def _make_checklist_item(
    item_id: str,
    *,
    status: str = "pass",
    evidence: str = "Sufficient evidence for this checklist item.",
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a single checklist item entry."""
    result: dict[str, Any] = {
        "id": item_id,
        "status": status,
        "evidence": evidence,
    }
    if notes is not None:
        result["notes"] = notes
    return result


def _make_valid_checklist_input(
    *,
    input_mode: str = "conversation",
    data_confidence: str = "exact",
    run_id: str = "20260319T143045Z",
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a valid checklist.py input with all 25 items.

    ``overrides`` maps item ID to status, e.g. {"COVER_01": "fail"}.
    """
    overrides = overrides or {}
    items = []
    for item_id in CHECKLIST_IDS:
        status = overrides.get(item_id, "pass")
        evidence = (
            f"Evidence for {item_id} (status={status})" if status != "not_applicable" else f"Auto-gated: {item_id}"
        )
        items.append(_make_checklist_item(item_id, status=status, evidence=evidence))
    return {
        "items": items,
        "input_mode": input_mode,
        "data_confidence": data_confidence,
        "metadata": {"run_id": run_id},
    }


# ===========================================================================
# checklist.py tests
# ===========================================================================


class TestChecklist:
    """Tests for checklist.py."""

    # 1. All items assessed with valid statuses, exits 0
    def test_checklist_valid_passes(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "items" in data
        assert len(data["items"]) == 25
        assert "score_pct" in data
        assert "pass_count" in data
        assert "fail_count" in data
        assert "warn_count" in data
        assert "na_count" in data
        assert "total" in data
        assert data["total"] == 25
        assert "input_mode" in data
        assert data["input_mode"] == "conversation"
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"

    # 2. Score computation: (pass_count + 0.5 * warn_count) / (total - na) * 100
    def test_checklist_score_computation(self) -> None:
        # Use document mode which only gates NARR_03 (1 auto-gated).
        # Override 3 items to fail and 1 to warn.
        # Result: 20 pass, 3 fail, 1 warn, 1 na (NARR_03 gated)
        # score = (20 + 0.5 * 1) / (25 - 1) * 100 = 85.4
        overrides = {
            "COVER_01": "fail",
            "COVER_02": "fail",
            "COVER_03": "fail",
            "POS_01": "warn",
        }
        payload = _make_valid_checklist_input(input_mode="document", overrides=overrides)
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["pass_count"] == 20
        assert data["fail_count"] == 3
        assert data["warn_count"] == 1
        assert data["na_count"] == 1
        assert data["total"] == 25
        # warn counts as 0.5 points (matches deck-review pattern)
        expected_score = round((20 + 0.5 * 1) / (25 - 1) * 100, 1)
        assert data["score_pct"] == expected_score

    # 3. Deck mode auto-gates EVID_02 and EVID_04
    def test_checklist_mode_gating_deck(self) -> None:
        payload = _make_valid_checklist_input(input_mode="deck")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        items_by_id = {item["id"]: item for item in data["items"]}
        # EVID_02 and EVID_04 should be auto-gated to not_applicable
        assert items_by_id["EVID_02"]["status"] == "not_applicable"
        assert items_by_id["EVID_04"]["status"] == "not_applicable"
        # NARR_03 should remain active in deck mode
        assert items_by_id["NARR_03"]["status"] != "not_applicable"
        assert data["na_count"] >= 2

    # 4. Conversation mode gates NARR_03 and EVID_04
    def test_checklist_mode_gating_conversation(self) -> None:
        payload = _make_valid_checklist_input(input_mode="conversation")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        items_by_id = {item["id"]: item for item in data["items"]}
        # NARR_03 and EVID_04 should be auto-gated
        assert items_by_id["NARR_03"]["status"] == "not_applicable"
        assert items_by_id["EVID_04"]["status"] == "not_applicable"
        # EVID_02 should remain active in conversation mode
        assert items_by_id["EVID_02"]["status"] != "not_applicable"

    # 5. Missing required item ID exits 1
    def test_checklist_missing_item_fails(self) -> None:
        payload = _make_valid_checklist_input()
        # Remove one item
        payload["items"] = [i for i in payload["items"] if i["id"] != "COVER_01"]
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 6. Invalid status exits 1
    def test_checklist_invalid_status_fails(self) -> None:
        payload = _make_valid_checklist_input()
        payload["items"][0]["status"] = "maybe"
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 7. Data confidence qualifier appended when estimated
    def test_checklist_data_confidence_qualifier(self) -> None:
        payload = _make_valid_checklist_input(data_confidence="estimated")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # Non-gated items should have the qualifier appended
        for item in data["items"]:
            if item["status"] != "not_applicable":
                assert "(based on estimated inputs)" in item["evidence"], (
                    f"Item {item['id']} missing confidence qualifier in evidence"
                )


# ===========================================================================
# compose_report.py tests
# ===========================================================================


def _make_product_profile(
    *,
    company_name: str = "TestCo",
    slug: str = "testco",
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a product_profile.json artifact."""
    return {
        "company_name": company_name,
        "slug": slug,
        "product_description": "A test product for automated testing.",
        "target_customers": ["SMBs", "Enterprise"],
        "value_propositions": ["Fast deployment", "High accuracy"],
        "differentiation_claims": ["Best-in-class latency"],
        "stage": "seed",
        "sector": "SaaS",
        "business_model": "SaaS",
        "input_mode": "conversation",
        "source_materials": ["founder conversation"],
        "metadata": {"run_id": run_id},
    }


def _make_landscape_artifact(
    *,
    run_id: str = "20260319T143045Z",
    competitors: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a landscape.json artifact (output of validate_landscape)."""
    if competitors is None:
        competitors = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Manual Process", "manual-process", "do_nothing"),
        ]
    return {
        "competitors": competitors,
        "input_mode": "conversation",
        "warnings": warnings or [],
        "metadata": {"run_id": run_id},
    }


def _make_positioning_artifact(
    *,
    run_id: str = "20260319T143045Z",
    accepted_warnings: list[dict[str, Any]] | None = None,
    assessment_mode: str | None = None,
    views: list[dict[str, Any]] | None = None,
    moat_assessments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a positioning.json artifact."""
    if views is None:
        views = [
            {
                "id": "primary",
                "x_axis": {
                    "name": "Deployment Speed",
                    "description": "How fast to deploy",
                    "rationale": "Key differentiator for SMBs",
                },
                "y_axis": {
                    "name": "Detection Accuracy",
                    "description": "Threat detection accuracy",
                    "rationale": "Table-stakes dimension",
                },
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("alpha-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                    _make_positioning_point("delta-co", 20, 60),
                    _make_positioning_point("manual-process", 95, 15),
                ],
            }
        ]
    if moat_assessments is None:
        moat_assessments = {}
        for slug in ["_startup", "alpha-corp", "beta-inc", "gamma-ltd", "delta-co", "manual-process"]:
            moat_assessments[slug] = {
                "moats": [
                    _make_moat_entry("network_effects", status="moderate"),
                    _make_moat_entry("data_advantages", status="moderate"),
                    _make_moat_entry("switching_costs", status="moderate"),
                    _make_moat_entry("regulatory_barriers", status="absent"),
                    _make_moat_entry("cost_structure", status="weak"),
                    _make_moat_entry("brand_reputation", status="weak"),
                ]
            }
    result: dict[str, Any] = {
        "views": views,
        "moat_assessments": moat_assessments,
        "differentiation_claims": [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data shows <5ms",
                "challenge": "No third-party validation",
                "verdict": "holds",
            }
        ],
        "metadata": {"run_id": run_id},
    }
    if accepted_warnings is not None:
        result["accepted_warnings"] = accepted_warnings
    if assessment_mode is not None:
        result["assessment_mode"] = assessment_mode
    return result


def _make_moat_scores_artifact(
    *,
    run_id: str = "20260319T143045Z",
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a moat_scores.json artifact."""
    return {
        "companies": {
            "_startup": {
                "moats": [
                    _make_moat_entry("network_effects", status="moderate"),
                    _make_moat_entry("data_advantages", status="strong"),
                ],
                "moat_count": 2,
                "strongest_moat": "data_advantages",
                "overall_defensibility": "moderate",
            },
            "alpha-corp": {
                "moats": [
                    _make_moat_entry("network_effects", status="strong"),
                    _make_moat_entry("data_advantages", status="strong"),
                ],
                "moat_count": 2,
                "strongest_moat": "network_effects",
                "overall_defensibility": "high",
            },
        },
        "comparison": {
            "by_dimension": {
                "network_effects": {"_startup": "moderate", "alpha-corp": "strong"},
                "data_advantages": {"_startup": "strong", "alpha-corp": "strong"},
            },
            "startup_rank": {
                "network_effects": {"rank": 2, "total": 2},
                "data_advantages": {"rank": 1, "total": 2},
            },
        },
        "warnings": warnings or [],
        "metadata": {"run_id": run_id},
    }


def _make_positioning_scores_artifact(
    *,
    run_id: str = "20260319T143045Z",
    views: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a positioning_scores.json artifact."""
    if views is None:
        views = [
            {
                "view_id": "primary",
                "x_axis_name": "Deployment Speed",
                "y_axis_name": "Detection Accuracy",
                "x_axis_rationale": "Key differentiator for SMBs",
                "y_axis_rationale": "Table-stakes dimension",
                "x_axis_vanity_flag": False,
                "y_axis_vanity_flag": False,
                "differentiation_score": 75.0,
                "startup_x_rank": 1,
                "startup_y_rank": 3,
                "competitor_count": 5,
            }
        ]
    return {
        "views": views,
        "overall_differentiation": 75.0,
        "differentiation_claims": [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data",
                "challenge": "No validation",
                "verdict": "holds",
            }
        ],
        "warnings": warnings or [],
        "metadata": {"run_id": run_id},
    }


def _make_checklist_artifact(
    *,
    run_id: str = "20260319T143045Z",
    score_pct: float = 82.6,
) -> dict[str, Any]:
    """Build a checklist.json artifact."""
    items = []
    for item_id in CHECKLIST_IDS:
        items.append(
            {
                "id": item_id,
                "category": item_id.split("_")[0],
                "label": f"Label for {item_id}",
                "status": "pass",
                "evidence": f"Evidence for {item_id}",
            }
        )
    return {
        "items": items,
        "score_pct": score_pct,
        "pass_count": 22,
        "warn_count": 1,
        "fail_count": 1,
        "na_count": 1,
        "total": 25,
        "input_mode": "conversation",
        "metadata": {"run_id": run_id},
    }


def _make_artifact_dir(
    tmp_path: str,
    *,
    run_id: str = "20260319T143045Z",
    include_product_profile: bool = True,
    include_landscape: bool = True,
    include_positioning: bool = True,
    include_moat_scores: bool = True,
    include_positioning_scores: bool = True,
    include_checklist: bool = True,
    landscape_overrides: dict[str, Any] | None = None,
    positioning_overrides: dict[str, Any] | None = None,
    moat_scores_overrides: dict[str, Any] | None = None,
    positioning_scores_overrides: dict[str, Any] | None = None,
    checklist_overrides: dict[str, Any] | None = None,
    product_profile_overrides: dict[str, Any] | None = None,
) -> str:
    """Write all required artifacts to a temp dir and return the path."""
    os.makedirs(tmp_path, exist_ok=True)

    if include_product_profile:
        pp = _make_product_profile(run_id=run_id)
        if product_profile_overrides:
            pp.update(product_profile_overrides)
        with open(os.path.join(tmp_path, "product_profile.json"), "w") as f:
            json.dump(pp, f)

    if include_landscape:
        ls = _make_landscape_artifact(run_id=run_id)
        if landscape_overrides:
            ls.update(landscape_overrides)
        with open(os.path.join(tmp_path, "landscape.json"), "w") as f:
            json.dump(ls, f)

    if include_positioning:
        pos = _make_positioning_artifact(run_id=run_id)
        if positioning_overrides:
            pos.update(positioning_overrides)
        with open(os.path.join(tmp_path, "positioning.json"), "w") as f:
            json.dump(pos, f)

    if include_moat_scores:
        ms = _make_moat_scores_artifact(run_id=run_id)
        if moat_scores_overrides:
            ms.update(moat_scores_overrides)
        with open(os.path.join(tmp_path, "moat_scores.json"), "w") as f:
            json.dump(ms, f)

    if include_positioning_scores:
        ps = _make_positioning_scores_artifact(run_id=run_id)
        if positioning_scores_overrides:
            ps.update(positioning_scores_overrides)
        with open(os.path.join(tmp_path, "positioning_scores.json"), "w") as f:
            json.dump(ps, f)

    if include_checklist:
        cl = _make_checklist_artifact(run_id=run_id)
        if checklist_overrides:
            cl.update(checklist_overrides)
        with open(os.path.join(tmp_path, "checklist.json"), "w") as f:
            json.dump(cl, f)

    return tmp_path


class TestCompose:
    """Tests for compose_report.py."""

    # 1. All artifacts present — exits 0, has report_markdown
    def test_compose_valid_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            assert "report_markdown" in data
            assert "metadata" in data
            assert "warnings" in data
            assert "artifacts_loaded" in data
            assert "scoring_summary" in data
            assert data["metadata"]["company_name"] == "TestCo"
            assert data["scoring_summary"]["checklist_score_pct"] == 82.6
            assert data["scoring_summary"]["overall_differentiation"] == 75.0
            assert data["scoring_summary"]["startup_defensibility"] == "moderate"

    # 2. Missing landscape.json -> MISSING_LANDSCAPE (high)
    def test_compose_missing_landscape_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_landscape=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_LANDSCAPE" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_LANDSCAPE")
            assert warn["severity"] == "high"

    # 3. Missing positioning_scores.json -> high severity
    def test_compose_missing_optional_artifact_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_positioning_scores=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_POSITIONING_SCORES" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_POSITIONING_SCORES")
            assert warn["severity"] == "high"

    # 4. --strict exits 1 on high-severity warning
    def test_compose_strict_mode_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_landscape=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--strict"])
            assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 5. Scoring slug not in landscape -> orphan warning
    def test_compose_orphan_competitor_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Use only 3 competitors in landscape but positioning has slugs not in landscape
            sparse_comps = [
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "direct"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
                _make_competitor("Delta Co", "delta-co", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": sparse_comps})
            # Add an orphan slug in moat_scores
            orphan_moat = _make_moat_scores_artifact()
            orphan_moat["companies"]["orphan-slug"] = {
                "moats": [_make_moat_entry("network_effects")],
                "moat_count": 1,
                "strongest_moat": "network_effects",
                "overall_defensibility": "low",
            }
            with open(os.path.join(tmp, "moat_scores.json"), "w") as f:
                json.dump(orphan_moat, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            # Should have an orphan warning for orphan-slug (not for _startup)
            messages = " ".join(w["message"] for w in data["warnings"])
            assert "orphan-slug" in messages

    # 6. Mismatched run_id -> STALE_ARTIFACT
    def test_compose_stale_artifact_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite checklist with a different run_id
            cl = _make_checklist_artifact(run_id="20260101T000000Z")
            with open(os.path.join(tmp, "checklist.json"), "w") as f:
                json.dump(cl, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "STALE_ARTIFACT" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "STALE_ARTIFACT")
            assert warn["severity"] == "high"

    # 7. Competitor with sourced_fields_count < 3 -> SHALLOW_COMPETITOR_PROFILE
    def test_compose_shallow_profile_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shallow = _make_competitor(
                "Shallow Co",
                "shallow-co",
                "direct",
                research_depth="partial",
                sourced_fields_count=1,
            )
            comps = [
                shallow,
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            # Update positioning/moat artifacts to include shallow-co
            pos = _make_positioning_artifact()
            pos["views"][0]["points"].append(_make_positioning_point("shallow-co", 40, 40))
            pos["moat_assessments"]["shallow-co"] = {"moats": [_make_moat_entry("network_effects")]}
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                json.dump(pos, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "SHALLOW_COMPETITOR_PROFILE" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "SHALLOW_COMPETITOR_PROFILE")
            assert warn["severity"] == "medium"
            assert "shallow-co" in warn["message"].lower() or "Shallow Co" in warn["message"]

    # 8. Vanity-flagged view -> VANITY_AXIS_WARNING
    def test_compose_vanity_axis_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vanity_views = [
                {
                    "view_id": "primary",
                    "x_axis_name": "Speed",
                    "y_axis_name": "Quality",
                    "x_axis_rationale": "rationale",
                    "y_axis_rationale": "rationale",
                    "x_axis_vanity_flag": True,
                    "y_axis_vanity_flag": False,
                    "differentiation_score": 60.0,
                    "startup_x_rank": 1,
                    "startup_y_rank": 2,
                    "competitor_count": 5,
                }
            ]
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": vanity_views},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "VANITY_AXIS_WARNING" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "VANITY_AXIS_WARNING")
            assert warn["severity"] == "medium"

    # 9. MOAT_WITHOUT_EVIDENCE forwarded from moat_scores warnings
    def test_compose_moat_without_evidence_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            moat_warns = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "severity": "medium",
                    "message": "alpha-corp: network_effects rated 'strong' with insufficient evidence",
                    "company": "alpha-corp",
                    "moat_id": "network_effects",
                }
            ]
            _make_artifact_dir(
                tmp,
                moat_scores_overrides={"warnings": moat_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MOAT_WITHOUT_EVIDENCE" in codes

    # 10. MISSING_DO_NOTHING forwarded from landscape warnings
    def test_compose_missing_do_nothing_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            land_warns = [
                {
                    "code": "MISSING_DO_NOTHING",
                    "severity": "medium",
                    "message": "No do_nothing or adjacent competitor found",
                }
            ]
            _make_artifact_dir(
                tmp,
                landscape_overrides={"warnings": land_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_DO_NOTHING" in codes

    # 11. RESEARCH_DEPTH_LOW: founder_provided + few sourced competitors
    def test_compose_research_depth_low_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # All competitors with low sourced_fields_count
            comps = [
                _make_competitor("A", "a", "direct", research_depth="founder_provided", sourced_fields_count=1),
                _make_competitor("B", "b", "direct", research_depth="founder_provided", sourced_fields_count=1),
                _make_competitor("C", "c", "adjacent", research_depth="founder_provided", sourced_fields_count=2),
                _make_competitor("D", "d", "emerging", research_depth="founder_provided", sourced_fields_count=0),
                _make_competitor("E", "e", "do_nothing", research_depth="founder_provided", sourced_fields_count=0),
            ]
            # landscape enriched has research_depth; compose reads it from landscape metadata
            # landscape.json doesn't have top-level research_depth, but the enriched one does
            # Actually, looking at the schema: landscape_enriched.json has research_depth but
            # landscape.json (output of validate_landscape) does not have a top-level research_depth.
            # The compose should look at competitor-level research_depth.
            # Per the task spec: "landscape research_depth == 'founder_provided' AND fewer than 4..."
            # We need the metadata-level research_depth. Let me add it to the landscape.
            _make_artifact_dir(
                tmp,
                landscape_overrides={
                    "competitors": comps,
                    "research_depth": "founder_provided",
                },
            )
            # Update positioning to match slugs
            pos = _make_positioning_artifact(
                views=[
                    {
                        "id": "primary",
                        "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                        "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                        "points": [
                            _make_positioning_point("_startup", 90, 85),
                            _make_positioning_point("a", 60, 40),
                            _make_positioning_point("b", 30, 70),
                            _make_positioning_point("c", 50, 50),
                            _make_positioning_point("d", 20, 60),
                            _make_positioning_point("e", 95, 15),
                        ],
                    }
                ],
                moat_assessments={
                    slug: {"moats": [_make_moat_entry("network_effects")]}
                    for slug in ["_startup", "a", "b", "c", "d", "e"]
                },
            )
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                json.dump(pos, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "RESEARCH_DEPTH_LOW" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "RESEARCH_DEPTH_LOW")
            assert warn["severity"] == "medium"

    # 12. SEQUENTIAL_FALLBACK: assessment_mode == "sequential"
    def test_compose_sequential_fallback_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_overrides={"assessment_mode": "sequential"})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "SEQUENTIAL_FALLBACK" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "SEQUENTIAL_FALLBACK")
            assert warn["severity"] == "info"

    # 13. Accepted warnings downgrades medium to acknowledged
    def test_compose_accepted_warnings_downgrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create a scenario with MOAT_WITHOUT_EVIDENCE forwarded from moat_scores
            moat_warns = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "severity": "medium",
                    "message": "alpha-corp: network_effects rated 'strong' with insufficient evidence",
                    "company": "alpha-corp",
                    "moat_id": "network_effects",
                }
            ]
            accepted = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "match": "alpha-corp",
                    "reason": "Acceptable given source constraints",
                }
            ]
            _make_artifact_dir(
                tmp,
                moat_scores_overrides={"warnings": moat_warns},
                positioning_overrides={"accepted_warnings": accepted},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            moat_w = next(w for w in data["warnings"] if w["code"] == "MOAT_WITHOUT_EVIDENCE")
            assert moat_w["severity"] == "acknowledged"

    # 14. High-severity code in accepted_warnings is ignored
    def test_compose_high_severity_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            accepted = [
                {
                    "code": "MISSING_LANDSCAPE",
                    "match": "landscape",
                    "reason": "We know it's missing",
                }
            ]
            _make_artifact_dir(
                tmp,
                include_landscape=False,
                positioning_overrides={"accepted_warnings": accepted},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            land_w = next(w for w in data["warnings"] if w["code"] == "MISSING_LANDSCAPE")
            # Should NOT be acknowledged — high severity cannot be accepted
            assert land_w["severity"] == "high"

    # 15. FOUNDER_OVERRIDE_COUNT counts founder_override evidence sources
    def test_compose_founder_override_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create positioning with some founder_override evidence_sources
            views = [
                {
                    "id": "primary",
                    "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                    "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                    "points": [
                        {
                            "competitor": "_startup",
                            "x": 90,
                            "y": 85,
                            "x_evidence": "e1",
                            "y_evidence": "e2",
                            "x_evidence_source": "founder_override",
                            "y_evidence_source": "founder_override",
                        },
                        {
                            "competitor": "alpha-corp",
                            "x": 60,
                            "y": 40,
                            "x_evidence": "e1",
                            "y_evidence": "e2",
                            "x_evidence_source": "researched",
                            "y_evidence_source": "founder_override",
                        },
                        _make_positioning_point("beta-inc", 30, 70),
                        _make_positioning_point("gamma-ltd", 50, 50),
                        _make_positioning_point("delta-co", 20, 60),
                        _make_positioning_point("manual-process", 95, 15),
                    ],
                }
            ]
            # Also add founder_override in moat assessments
            moat_assessments: dict[str, Any] = {}
            for slug in ["_startup", "alpha-corp", "beta-inc", "gamma-ltd", "delta-co", "manual-process"]:
                moat_assessments[slug] = {
                    "moats": [
                        _make_moat_entry(
                            "network_effects",
                            evidence_source="founder_override" if slug == "_startup" else "researched",
                        ),
                        _make_moat_entry("data_advantages"),
                    ]
                }
            _make_artifact_dir(
                tmp,
                positioning_overrides={
                    "views": views,
                    "moat_assessments": moat_assessments,
                },
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            # 3 founder_override in positioning points (2 for _startup + 1 for alpha-corp y)
            # + 1 founder_override in moat assessments (_startup network_effects)
            # = 4 total
            assert data["metadata"]["founder_override_count"] == 4
            codes = [w["code"] for w in data["warnings"]]
            assert "FOUNDER_OVERRIDE_COUNT" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "FOUNDER_OVERRIDE_COUNT")
            assert warn["severity"] == "low"

    # 16. Report markdown has expected sections
    def test_compose_report_markdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            md = data["report_markdown"]
            assert "# Competitive Positioning Analysis" in md
            assert "TestCo" in md
            assert "## Executive Summary" in md
            assert "## Competitor Landscape" in md
            assert "## Positioning Analysis" in md
            assert "## Moat Assessment" in md
            assert "## Differentiation Stress-Test" in md
            assert "## Key Findings" in md
            assert "founder skills" in md
            assert "lool ventures" in md
            assert "Competitive Positioning Coach" in md

    # 17. Missing positioning.json -> MISSING_POSITIONING (high)
    def test_compose_missing_positioning_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_positioning=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_POSITIONING" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_POSITIONING")
            assert warn["severity"] == "high"

    # 18. Orphan slugs in positioning.json views/moat_assessments -> CORRUPT_ARTIFACT
    def test_compose_orphan_positioning_slug_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # positioning.json has an orphan slug in views[].points
            views = [
                {
                    "id": "primary",
                    "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                    "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                    "points": [
                        _make_positioning_point("_startup", 90, 85),
                        _make_positioning_point("alpha-corp", 60, 40),
                        _make_positioning_point("beta-inc", 30, 70),
                        _make_positioning_point("gamma-ltd", 50, 50),
                        _make_positioning_point("delta-co", 20, 60),
                        _make_positioning_point("manual-process", 95, 15),
                        _make_positioning_point("orphan-view-slug", 70, 70),
                    ],
                }
            ]
            moat_assessments: dict[str, Any] = {}
            for slug in [
                "_startup",
                "alpha-corp",
                "beta-inc",
                "gamma-ltd",
                "delta-co",
                "manual-process",
                "orphan-moat-slug",
            ]:
                moat_assessments[slug] = {"moats": [_make_moat_entry("network_effects")]}
            _make_artifact_dir(
                tmp,
                positioning_overrides={
                    "views": views,
                    "moat_assessments": moat_assessments,
                },
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            messages = " ".join(w["message"] for w in data["warnings"])
            assert "orphan-view-slug" in messages
            assert "orphan-moat-slug" in messages

    # 19. INCOMPLETE_SCORING: landscape competitor missing from moat_scores
    def test_compose_incomplete_scoring_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # landscape has foo, but moat_scores.companies does not
            comps = [
                _make_competitor("Foo Corp", "foo", "direct"),
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            # moat_scores only has _startup and alpha-corp (no foo)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            incomplete = [w for w in data["warnings"] if w["code"] == "INCOMPLETE_SCORING"]
            assert len(incomplete) > 0, "Expected at least one INCOMPLETE_SCORING warning"
            assert all(w["severity"] == "medium" for w in incomplete)
            foo_warns = [w for w in incomplete if "foo" in w["message"]]
            # foo is missing from both moat_scores and positioning views
            assert len(foo_warns) >= 1, f"Expected INCOMPLETE_SCORING for 'foo', got: {incomplete}"


class TestScorePositioningValidation:
    """Additional validation tests for score_positioning.py."""

    # Malformed axis (missing name) exits 1
    def test_score_positioning_malformed_axis_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {},  # missing 'name'
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "name" in stderr.lower()

    # Duplicate competitor slugs within a view exits 1
    def test_score_positioning_duplicate_points_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("acme-corp", 50, 50),  # duplicate
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "duplicate" in stderr.lower()
