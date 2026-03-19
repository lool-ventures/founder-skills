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
