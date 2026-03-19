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
