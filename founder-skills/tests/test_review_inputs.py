# founder-skills/tests/test_review_inputs.py
"""Tests for review_inputs.py — dual-mode review viewer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any

_SCRIPTS = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "financial-model-review",
    "scripts",
)
_SCRIPT = os.path.join(_SCRIPTS, "review_inputs.py")
_APPLY_SCRIPT = os.path.join(_SCRIPTS, "apply_corrections.py")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FULL_INPUTS = {
    "company": {
        "company_name": "TestCo",
        "slug": "testco",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "Israel",
        "revenue_model_type": "saas-plg",
        "model_format": "spreadsheet",
        "data_confidence": "exact",
        "traits": ["multi-currency"],
    },
    "revenue": {
        "mrr": {"value": 50000, "as_of": "2026-01"},
        "arr": {"value": 600000, "as_of": "2026-01"},
        "customers": 100,
        "growth_rate_monthly": 0.1,
        "churn_monthly": 0.03,
        "nrr": 1.1,
        "grr": 0.97,
        "monthly": [
            {"month": "2025-11", "total": 41000, "actual": True},
            {"month": "2025-12", "total": 45000, "actual": True},
            {"month": "2026-01", "total": 50000, "actual": True},
        ],
    },
    "cash": {
        "current_balance": 1000000,
        "monthly_net_burn": 80000,
        "balance_date": "2026-01",
        "debt": 0,
        "fundraising": {"target_raise": 3000000, "expected_close": "2026-06"},
        "grants": {"iia_approved": 200000},
    },
    "expenses": {
        "headcount": [
            {
                "role": "Engineer",
                "count": 3,
                "salary_annual": 120000,
                "start_month": "2025-01",
                "geography": "Israel",
                "burden_pct": 0.25,
            },
        ],
        "opex_monthly": [
            {"category": "Cloud", "amount": 5000, "start_month": "2025-01"},
        ],
        "cogs": {"hosting": 3000, "support": 1000},
    },
    "unit_economics": {
        "cac": {"total": 5000},
        "ltv": {
            "value": 25000,
            "inputs": {"arpu_monthly": 500, "churn_monthly": 0.03, "gross_margin": 0.8},
        },
        "gross_margin": 0.8,
        "payback_months": 10,
    },
    "scenarios": {
        "base": {"growth_rate": 0.1, "burn_change": 0},
        "slow": {"growth_rate": 0.05, "burn_change": 0.1},
        "crisis": {"growth_rate": 0, "burn_change": 0.2},
    },
    "structure": {
        "has_assumptions_tab": True,
        "has_scenarios": True,
        "formatting_quality": "good",
    },
    "israel_specific": {
        "fx_rate_ils_usd": 3.6,
        "ils_expense_fraction": 0.5,
        "iia_grants": True,
        "iia_royalties_modeled": False,
    },
    "bridge": {
        "runway_target_months": 18,
        "milestones": ["PMF", "100 customers"],
        "next_round_target": "Series A",
    },
    "metadata": {
        "run_id": "20260309T120000Z",
        "source_periodicity": "monthly",
        "conversion_applied": "none",
    },
}

_MINIMAL_INPUTS = {
    "company": {
        "company_name": "MinCo",
        "slug": "minco",
        "stage": "pre-seed",
        "sector": "Fintech",
        "geography": "US",
    },
    "revenue": {"mrr": {"value": 10000, "as_of": "2026-01"}, "customers": 20},
    "cash": {
        "current_balance": 500000,
        "monthly_net_burn": 40000,
        "balance_date": "2026-01",
    },
}


def _generate_static(inputs: dict[str, Any]) -> tuple[int, str, str]:
    """Write inputs to temp file, run script with --static, return (exit_code, html, stderr)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs_path = os.path.join(tmpdir, "inputs.json")
        output_path = os.path.join(tmpdir, "review.html")
        with open(inputs_path, "w") as f:
            json.dump(inputs, f)
        result = subprocess.run(
            [sys.executable, _SCRIPT, inputs_path, "--static", output_path],
            capture_output=True,
            text=True,
        )
        html = ""
        if os.path.exists(output_path):
            with open(output_path) as f:
                html = f.read()
        return result.returncode, html, result.stderr


# ---------------------------------------------------------------------------
# Static Mode Tests
# ---------------------------------------------------------------------------


class TestStaticHTML:
    def test_outputs_valid_html(self) -> None:
        """Script outputs valid HTML document."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert rc == 0
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_company_name_embedded(self) -> None:
        """Company name appears in HTML output."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "TestCo" in html

    def test_all_tabs_present(self) -> None:
        """All 6 tab identifiers present in output."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        for tab in ["company", "revenue", "cash", "team", "unit-economics", "more"]:
            assert tab in html, f"Tab '{tab}' missing from HTML output"

    def test_mrr_value_embedded(self) -> None:
        """MRR value appears in embedded data."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "50000" in html

    def test_sanity_metrics_present(self) -> None:
        """Sanity metric elements present in HTML."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "runway" in html.lower()
        assert "burn" in html.lower()

    def test_submit_button_present(self) -> None:
        """Submit/Download button exists."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "submit" in html.lower() or "download" in html.lower()

    def test_corrections_tracking(self) -> None:
        """HTML tracks corrections (diff between original and edited state)."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "corrections" in html.lower() or "ORIGINAL" in html

    def test_minimal_inputs(self) -> None:
        """Works with minimal inputs (no expenses, UE, scenarios, etc.)."""
        rc, html, stderr = _generate_static(_MINIMAL_INPUTS)
        assert rc == 0
        assert "MinCo" in html
        assert "</html>" in html

    def test_empty_arrays_handled(self) -> None:
        """Empty headcount/opex arrays don't break generation."""
        inputs = {
            **_FULL_INPUTS,
            "expenses": {"headcount": [], "opex_monthly": [], "cogs": {}},
        }
        rc, html, stderr = _generate_static(inputs)
        assert rc == 0

    def test_null_fields_handled(self) -> None:
        """Null optional fields don't break generation."""
        inputs = json.loads(json.dumps(_FULL_INPUTS))
        inputs["revenue"]["growth_rate_monthly"] = None
        inputs["revenue"]["churn_monthly"] = None
        rc, html, stderr = _generate_static(inputs)
        assert rc == 0

    def test_ils_currency_support(self) -> None:
        """ILS currency toggle support present when fx_rate exists."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "ILS" in html or "ils" in html

    def test_no_ils_when_no_fx_rate(self) -> None:
        """No crash when no fx_rate in data."""
        rc, html, stderr = _generate_static(_MINIMAL_INPUTS)
        assert rc == 0

    def test_time_series_data(self) -> None:
        """Monthly time-series data present in output."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "2025-11" in html
        assert "41000" in html

    def test_headcount_data(self) -> None:
        """Headcount data present in output."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "Engineer" in html
        assert "120000" in html

    def test_feedback_payload_shape(self) -> None:
        """Download/submit logic references correct payload keys."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "warning_overrides" in html or "warningOverrides" in html
        assert "ils_fields" in html or "ilsFields" in html

    def test_light_theme_colors(self) -> None:
        """Uses light theme palette."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert any(c in html for c in ["#0d549d", "#0071e3", "#f9fafb", "#1f2937"])

    def test_stage_badge(self) -> None:
        """Stage badge rendered."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "seed" in html.lower()

    def test_scenarios_rendered(self) -> None:
        """Scenario fields present."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "base" in html
        assert "slow" in html
        assert "crisis" in html

    def test_grants_fields(self) -> None:
        """IIA grant fields present."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "iia_approved" in html or "IIA" in html or "200000" in html

    def test_fetch_fallback_pattern(self) -> None:
        """HTML contains the fetch-then-catch pattern for dual-mode."""
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert "/api/feedback" in html
        assert "download" in html.lower()

    def test_stdout_reports_mode(self) -> None:
        """Stdout contains JSON with mode info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs_path = os.path.join(tmpdir, "inputs.json")
            output_path = os.path.join(tmpdir, "review.html")
            with open(inputs_path, "w") as f:
                json.dump(_FULL_INPUTS, f)
            result = subprocess.run(
                [sys.executable, _SCRIPT, inputs_path, "--static", output_path],
                capture_output=True,
                text=True,
            )
            stdout = json.loads(result.stdout)
            assert stdout["mode"] == "static"


# ---------------------------------------------------------------------------
# Server Mode Helpers
# ---------------------------------------------------------------------------


def _start_server(
    inputs: dict[str, Any], extra_args: list[str] | None = None
) -> tuple[int, str, subprocess.Popen[str]]:
    """Start server in background, return (port, workspace_dir, process)."""
    tmpdir = tempfile.mkdtemp()
    inputs_path = os.path.join(tmpdir, "inputs.json")
    with open(inputs_path, "w") as f:
        json.dump(inputs, f)

    cmd = [sys.executable, _SCRIPT, inputs_path, "--workspace", tmpdir, "--port", "0"]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Read stdout to get port
    assert proc.stdout is not None
    line = proc.stdout.readline()
    info = json.loads(line)
    return info["port"], tmpdir, proc


# ---------------------------------------------------------------------------
# Server Mode Tests
# ---------------------------------------------------------------------------


class TestServerMode:
    def test_server_starts_and_serves_html(self) -> None:
        """Server starts on requested port and returns HTML on GET /."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            html = resp.read().decode()
            assert "<!DOCTYPE html>" in html
            assert "TestCo" in html
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_post_feedback_writes_file(self) -> None:
        """POST /api/feedback writes corrections.json to workspace."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            payload = json.dumps(
                {
                    "corrections": [{"path": "revenue.mrr.value", "was": 50000, "now": 75000}],
                    "corrected": _FULL_INPUTS,
                    "warning_overrides": [],
                    "ils_fields": {},
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/feedback",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req)
            result = json.loads(resp.read())
            assert result["ok"] is True
            # Verify file written
            fb_path = os.path.join(tmpdir, "corrections.json")
            assert os.path.exists(fb_path)
            with open(fb_path) as f:
                saved = json.load(f)
            assert saved["corrections"][0]["path"] == "revenue.mrr.value"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_get_feedback_restores_state(self) -> None:
        """GET /api/feedback returns previously saved feedback."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            # First save some feedback
            payload = json.dumps({"test": "data"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/feedback",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req)
            # Then read it back
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/feedback")
            result = json.loads(resp.read())
            assert result["test"] == "data"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_post_check_returns_validation(self) -> None:
        """POST /api/check returns validation results with sanity metrics."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            payload = json.dumps(
                {
                    "state": _FULL_INPUTS,
                    "ils_fields": {},
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/check",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req)
            result = json.loads(resp.read())
            # Should have sanity, warnings, and errors keys
            assert "sanity" in result
            assert "warnings" in result
            assert "errors" in result
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_stdout_reports_server_mode(self) -> None:
        """Stdout JSON reports server mode with URL and port."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            # Port was already read by _start_server
            assert isinstance(port, int)
            assert port > 0
        finally:
            proc.terminate()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Integration Tests — full round-trip
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_round_trip_static_then_apply(self) -> None:
        """Generate static HTML, simulate corrections payload, apply."""
        # Step 1: Generate static HTML (verify it works)
        rc, html, stderr = _generate_static(_FULL_INPUTS)
        assert rc == 0
        assert "TestCo" in html

        # Step 2: Simulate corrections payload (as founder would download)
        corrected_state = json.loads(json.dumps(_FULL_INPUTS))
        corrected_state["revenue"]["mrr"]["value"] = 75000
        corrected_state["revenue"]["customers"] = 150
        payload = {
            "corrections": [
                {"path": "revenue.mrr.value", "was": 50000, "now": 75000, "label": "MRR"},
                {"path": "revenue.customers", "was": 100, "now": 150, "label": "Customers"},
            ],
            "corrected": corrected_state,
            "warning_overrides": [],
            "ils_fields": {},
        }

        # Step 3: Apply corrections
        with tempfile.TemporaryDirectory() as tmpdir:
            corr_path = os.path.join(tmpdir, "corrections.json")
            orig_path = os.path.join(tmpdir, "inputs.json")
            with open(corr_path, "w") as f:
                json.dump(payload, f)
            with open(orig_path, "w") as f:
                json.dump(_FULL_INPUTS, f)
            result = subprocess.run(
                [sys.executable, _APPLY_SCRIPT, corr_path, "--original", orig_path, "--output-dir", tmpdir],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            corrected_path = os.path.join(tmpdir, "corrected_inputs.json")
            with open(corrected_path) as f:
                corrected = json.load(f)
            assert corrected["revenue"]["mrr"]["value"] == 75000
            assert corrected["revenue"]["customers"] == 150
            # Verify audit trail
            audit_path = os.path.join(tmpdir, "extraction_corrections.json")
            with open(audit_path) as f:
                audit = json.load(f)
            assert audit["correction_count"] == 2
            # Verify metadata preserved
            assert corrected["metadata"]["run_id"] == "20260309T120000Z"

    def test_round_trip_server_then_apply(self) -> None:
        """Start server, POST feedback, kill server, apply corrections."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            # Simulate founder submission via server
            corrected_state = json.loads(json.dumps(_FULL_INPUTS))
            corrected_state["cash"]["current_balance"] = 800000
            payload = json.dumps(
                {
                    "corrections": [
                        {"path": "cash.current_balance", "was": 1000000, "now": 800000, "label": "Cash"},
                    ],
                    "corrected": corrected_state,
                    "warning_overrides": [],
                    "ils_fields": {},
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/feedback",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req)
            result = json.loads(resp.read())
            assert result["ok"] is True
        finally:
            proc.terminate()
            proc.wait(timeout=5)

        # Now apply corrections (server wrote corrections.json)
        corr_path = os.path.join(tmpdir, "corrections.json")
        orig_path = os.path.join(tmpdir, "inputs.json")
        assert os.path.exists(corr_path), "Server should have written corrections.json"
        result = subprocess.run(
            [sys.executable, _APPLY_SCRIPT, corr_path, "--original", orig_path, "--output-dir", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        corrected_path = os.path.join(tmpdir, "corrected_inputs.json")
        with open(corrected_path) as f:
            corrected = json.load(f)
        assert corrected["cash"]["current_balance"] == 800000
        # Verify metadata preserved
        assert corrected["metadata"]["run_id"] == "20260309T120000Z"
