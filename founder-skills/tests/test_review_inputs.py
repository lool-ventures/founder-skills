# founder-skills/tests/test_review_inputs.py
"""Tests for review_inputs.py — dual-mode review viewer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
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


def _load_review_inputs_module() -> types.ModuleType:
    """Import review_inputs.py as a module (unique sys.modules key to avoid collisions)."""
    key = "fmr_review_inputs_test"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _generate_static_stdout(inputs: dict[str, Any]) -> tuple[int, str, str, str]:
    """Write inputs to temp file, run script with --static, return (exit_code, html, stderr, stdout)."""
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
        return result.returncode, html, result.stderr, result.stdout


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


def _compute_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


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
        assert "BASE_HASH" in html
        assert "base_hash" in html
        assert "changes" in html

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
# Extraction Warnings Fixtures
# ---------------------------------------------------------------------------

_EXTRACTION_WARNINGS_WARN: dict[str, Any] = {
    "status": "warn",
    "checks": [
        {
            "id": "COMPANY_NAME",
            "status": "warn",
            "message": "Company name 'BadCo' not found in model data",
            "candidates": ["TestCo", "TestCorp"],
        },
        {
            "id": "SALARY_TRACEABILITY",
            "status": "pass",
            "message": "All salary values traceable",
        },
    ],
    "summary": {"total": 4, "pass": 3, "warn": 1, "skip": 0},
    "correction_hints": ["Company name mismatch"],
}

_EXTRACTION_WARNINGS_PASS: dict[str, Any] = {
    "status": "pass",
    "checks": [],
    "summary": {"total": 4, "pass": 4, "warn": 0, "skip": 0},
    "correction_hints": [],
}


def _generate_static_with_ew(inputs: dict[str, Any], ew: dict[str, Any] | None) -> tuple[int, str, str]:
    """Write inputs + extraction warnings, run script with --static, return (rc, html, stderr)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs_path = os.path.join(tmpdir, "inputs.json")
        output_path = os.path.join(tmpdir, "review.html")
        with open(inputs_path, "w") as f:
            json.dump(inputs, f)
        cmd = [sys.executable, _SCRIPT, inputs_path, "--static", output_path]
        if ew is not None:
            ew_path = os.path.join(tmpdir, "extraction_validation.json")
            with open(ew_path, "w") as f:
                json.dump(ew, f)
            cmd.extend(["--extraction-warnings", ew_path])
        result = subprocess.run(cmd, capture_output=True, text=True)
        html = ""
        if os.path.exists(output_path):
            with open(output_path) as f:
                html = f.read()
        return result.returncode, html, result.stderr


# ---------------------------------------------------------------------------
# Extraction Warning Tests — Static Mode
# ---------------------------------------------------------------------------


class TestExtractionWarningsStatic:
    def test_warn_renders_extraction_warnings_div(self) -> None:
        """Static mode with --extraction-warnings renders #extraction-warnings div."""
        rc, html, _ = _generate_static_with_ew(_FULL_INPUTS, _EXTRACTION_WARNINGS_WARN)
        assert rc == 0
        assert 'id="extraction-warnings"' in html
        assert "BadCo" in html
        assert "TestCo" in html  # candidate

    def test_pass_no_extraction_warnings_div(self) -> None:
        """Static mode with passing extraction warnings does not render banner."""
        rc, html, _ = _generate_static_with_ew(_FULL_INPUTS, _EXTRACTION_WARNINGS_PASS)
        assert rc == 0
        assert 'id="extraction-warnings"' not in html

    def test_no_flag_no_extraction_warnings(self) -> None:
        """Static mode without --extraction-warnings flag has no banner."""
        rc, html, _ = _generate_static(_FULL_INPUTS)
        assert rc == 0
        assert 'id="extraction-warnings"' not in html

    def test_extraction_warnings_separate_from_validation(self) -> None:
        """Extraction warnings div is separate from #warnings-container."""
        rc, html, _ = _generate_static_with_ew(_FULL_INPUTS, _EXTRACTION_WARNINGS_WARN)
        assert rc == 0
        # Both divs exist
        assert 'id="extraction-warnings"' in html
        assert 'id="warnings-container"' in html
        # extraction-warnings appears before warnings-container
        ew_pos = html.index('id="extraction-warnings"')
        wc_pos = html.index('id="warnings-container"')
        assert ew_pos < wc_pos

    def test_dismiss_button_present(self) -> None:
        """Each extraction warning has a dismiss button."""
        rc, html, _ = _generate_static_with_ew(_FULL_INPUTS, _EXTRACTION_WARNINGS_WARN)
        assert rc == 0
        assert "Dismiss" in html


# ---------------------------------------------------------------------------
# XSS / HTML-injection safety tests
# ---------------------------------------------------------------------------

_XSS_NAME = "</script><script>alert(1)</script>"


class TestScriptEmbedEscaping:
    def test_embedded_data_escapes_script_close(self) -> None:
        """A company name containing </script> must not terminate the data
        <script> block (page breakage at best, XSS at worst)."""
        inputs = json.loads(json.dumps(_FULL_INPUTS))
        inputs["company"]["company_name"] = _XSS_NAME
        rc, html, _ = _generate_static(inputs)
        assert rc == 0
        assert "</script><script>alert(1)" not in html
        assert "\\u003c/script" in html

    def test_extraction_warning_fields_html_escaped(self) -> None:
        """candidates / untraceable role strings come verbatim from the
        founder's spreadsheet — they must be HTML-escaped in the warnings
        banner."""
        ew: dict[str, Any] = {
            "status": "warn",
            "checks": [
                {
                    "id": "SALARY_TRACEABILITY",
                    "status": "warn",
                    "message": "salary not traceable",
                    "untraceable": [{"role": "<img src=x onerror=alert(1)>"}],
                }
            ],
        }
        rc, html, _ = _generate_static_with_ew(_FULL_INPUTS, ew)
        assert rc == 0
        assert "<img src=x" not in html
        assert "&lt;img src=x" in html


# ---------------------------------------------------------------------------
# Extraction Warning Tests — Server Mode
# ---------------------------------------------------------------------------


class TestExtractionWarningsServer:
    def test_server_renders_extraction_warnings(self) -> None:
        """Server mode GET / with extraction warnings renders #extraction-warnings div."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ew_path = os.path.join(tmpdir, "extraction_validation.json")
            with open(ew_path, "w") as f:
                json.dump(_EXTRACTION_WARNINGS_WARN, f)
            port, workspace, proc = _start_server(
                _FULL_INPUTS,
                extra_args=["--extraction-warnings", ew_path],
            )
            try:
                resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
                html = resp.read().decode()
                assert 'id="extraction-warnings"' in html
                assert "BadCo" in html
            finally:
                proc.terminate()
                proc.wait(timeout=5)


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
                    "base_hash": _compute_hash(_FULL_INPUTS),
                    "changes": [{"path": "revenue.mrr.value", "expected_old": 50000, "new": 75000}],
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
            assert saved["changes"][0]["path"] == "revenue.mrr.value"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_get_feedback_returns_405(self) -> None:
        """GET /api/feedback must return 405 — corrections are write-only over HTTP
        (regression: previously served stored founder data back to GET callers)."""
        port, tmpdir, proc = _start_server(_FULL_INPUTS)
        try:
            # First POST some feedback so there is data on disk
            payload = json.dumps({"test": "data"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/feedback",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req)
            # GET must return 405, not the stored data
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/feedback")
                raise AssertionError("Expected HTTP 405 but got 200")
            except urllib.error.HTTPError as e:
                assert e.code == 405, f"Expected 405, got {e.code}"
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
            # Simulate founder submission via server (new v2 payload shape)
            payload = json.dumps(
                {
                    "base_hash": _compute_hash(_FULL_INPUTS),
                    "changes": [
                        {"path": "cash.current_balance", "expected_old": 1000000, "new": 800000},
                    ],
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


# ---------------------------------------------------------------------------
# Task 13a — _kill_port must only kill prior review_inputs.py instances
# ---------------------------------------------------------------------------


def test_kill_port_spares_foreign_processes(monkeypatch: Any) -> None:
    """_kill_port must only SIGTERM prior review_inputs.py instances — never
    whatever unrelated process happens to own the port (regression: it killed
    any PID lsof returned)."""
    import time

    mod = _load_review_inputs_module()
    killed: list[int] = []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        class R:
            stdout = ""

        r = R()
        if cmd[0] == "lsof":
            r.stdout = "4242\n"
        elif cmd[0] == "ps":
            r.stdout = "/usr/bin/some-other-daemon --port 3117\n"
        return r

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mod._kill_port(3117)
    assert killed == []


def test_kill_port_kills_prior_instance(monkeypatch: Any) -> None:
    """_kill_port must SIGTERM a process whose command line contains review_inputs.py."""
    import time

    mod = _load_review_inputs_module()
    killed: list[int] = []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        class R:
            stdout = ""

        r = R()
        if cmd[0] == "lsof":
            r.stdout = "4242\n"
        elif cmd[0] == "ps":
            r.stdout = "python3 .../scripts/review_inputs.py inputs.json --workspace x\n"
        return r

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mod._kill_port(3117)
    assert killed == [4242]


# ---------------------------------------------------------------------------
# Task 13c — static receipt must include ok + bytes
# ---------------------------------------------------------------------------


def test_static_receipt_has_ok_and_bytes() -> None:
    """Static-mode receipt must match the visualize/explore receipt convention."""
    rc, _html, _stderr, stdout = _generate_static_stdout(_FULL_INPUTS)
    assert rc == 0
    receipt = json.loads(stdout)
    assert receipt["ok"] is True
    assert receipt["mode"] == "static"
    assert receipt["bytes"] > 0


def test_static_creates_missing_parent_dirs() -> None:
    """Static mode must create not-yet-existing parent directories (every other
    output writer in the skill runs os.makedirs first) and emit the receipt,
    not a raw FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs_path = os.path.join(tmpdir, "inputs.json")
        with open(inputs_path, "w") as f:
            json.dump(_FULL_INPUTS, f)
        # Parent subdir does NOT exist yet.
        output_path = os.path.join(tmpdir, "nested", "subdir", "review.html")
        result = subprocess.run(
            [sys.executable, _SCRIPT, inputs_path, "--static", output_path],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr
        assert os.path.exists(output_path)
        receipt = json.loads(result.stdout)
        assert receipt["ok"] is True
        assert receipt["mode"] == "static"
