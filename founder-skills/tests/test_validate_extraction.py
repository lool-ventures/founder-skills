#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tests for validate_extraction.py — anti-hallucination gate.

Run:  pytest founder-skills/tests/test_validate_extraction.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")


def _load_validate_extraction_module() -> Any:
    """Import validate_extraction.py as a module for direct function access."""
    script_path = os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py")
    spec = importlib.util.spec_from_file_location("fmr_validate_extraction_test", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run(
    inputs: dict[str, Any] | None,
    model_data: dict[str, Any] | None,
    extra_args: list[str] | None = None,
) -> tuple[int, dict[str, Any], str]:
    """Write temp files, run validate_extraction.py, return (exit_code, json, stderr)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs_path = os.path.join(tmpdir, "inputs.json")
        model_data_path = os.path.join(tmpdir, "model_data.json")

        if inputs is not None:
            with open(inputs_path, "w") as f:
                json.dump(inputs, f)
        if model_data is not None:
            with open(model_data_path, "w") as f:
                json.dump(model_data, f)

        cmd = [
            sys.executable,
            os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py"),
            "--inputs",
            inputs_path,
            "--model-data",
            model_data_path,
            "--pretty",
        ]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}
        return result.returncode, data, result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODEL_DATA: dict[str, Any] = {
    "sheets": [
        {
            "name": "P&L",
            "headers": ["Line Item", "Jan 2025", "Feb 2025", "Mar 2025"],
            "rows": [
                ["Revenue", 50000, 55000, 60000],
                ["Payroll - R&D", 120000, 120000, 120000],
                ["Payroll - S&M", 80000, 80000, 80000],
                ["Cash Balance", 1000000, 920000, 840000],
            ],
            "detected_type": "pnl",
            "periodicity": "monthly",
            "row_count": 4,
            "col_count": 4,
            "pre_header_rows": [["Acme Corp", None, None, None]],
        }
    ],
    "source_format": "xlsx",
    "source_file": "acme-model.xlsx",
    "periodicity_summary": "monthly",
}

_INPUTS: dict[str, Any] = {
    "company": {
        "company_name": "Acme Corp",
        "slug": "acme-corp",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "US",
        "model_format": "spreadsheet",
    },
    "revenue": {
        "mrr": {"value": 60000, "as_of": "2025-03"},
        "customers": 100,
    },
    "cash": {
        "current_balance": 840000,
        "monthly_net_burn": 80000,
    },
    "expenses": {
        "headcount": [
            {"role": "R&D", "count": 5, "salary_annual": 120000},
            {"role": "S&M", "count": 3, "salary_annual": 80000},
        ],
    },
}


# ---------------------------------------------------------------------------
# Skip tests
# ---------------------------------------------------------------------------


class TestSkipConditions:
    def test_skip_missing_model_data_file(self) -> None:
        """Skip when model_data file doesn't exist."""
        rc, data, _ = _run(_INPUTS, None)
        assert rc == 0
        assert data["status"] == "skip"

    def test_skip_stub_model_data(self) -> None:
        """Skip when model_data is a stub."""
        stub = {"skipped": True, "reason": "no file provided"}
        rc, data, _ = _run(_INPUTS, stub)
        assert rc == 0
        assert data["status"] == "skip"

    def test_skip_conversational_format(self) -> None:
        """Skip when model_format is conversational."""
        inputs = {**_INPUTS, "company": {**_INPUTS["company"], "model_format": "conversational"}}
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        assert data["status"] == "skip"
        assert "conversational" in data["summary"]["skip_reason"]

    def test_skip_deck_format(self) -> None:
        """Skip when model_format is deck."""
        inputs = {**_INPUTS, "company": {**_INPUTS["company"], "model_format": "deck"}}
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        assert data["status"] == "skip"

    def test_skip_empty_sheets(self) -> None:
        """Skip when model_data has no sheets."""
        rc, data, _ = _run(_INPUTS, {"sheets": []})
        assert rc == 0
        assert data["status"] == "skip"


# ---------------------------------------------------------------------------
# Pass tests
# ---------------------------------------------------------------------------


class TestPassConditions:
    def test_all_values_traceable(self) -> None:
        """Pass when all inputs values appear in model_data."""
        rc, data, _ = _run(_INPUTS, _MODEL_DATA)
        assert rc == 0
        assert data["status"] == "pass"
        assert data["summary"]["warn"] == 0
        assert len(data["correction_hints"]) == 0

    def test_output_flag(self) -> None:
        """The -o flag writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs_path = os.path.join(tmpdir, "inputs.json")
            model_data_path = os.path.join(tmpdir, "model_data.json")
            out_path = os.path.join(tmpdir, "result.json")
            with open(inputs_path, "w") as f:
                json.dump(_INPUTS, f)
            with open(model_data_path, "w") as f:
                json.dump(_MODEL_DATA, f)
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py"),
                    "--inputs",
                    inputs_path,
                    "--model-data",
                    model_data_path,
                    "-o",
                    out_path,
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            receipt = json.loads(result.stdout)
            assert receipt["ok"] is True
            with open(out_path) as f:
                written = json.load(f)
            assert written["status"] == "pass"


# ---------------------------------------------------------------------------
# Warn tests
# ---------------------------------------------------------------------------


class TestWarnConditions:
    def test_company_name_mismatch(self) -> None:
        """Warn when company name doesn't match model_data."""
        inputs = {**_INPUTS, "company": {**_INPUTS["company"], "company_name": "ZetaCorp Industries"}}
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["COMPANY_NAME"]["status"] == "warn"
        assert "candidates" in checks_by_id["COMPANY_NAME"]
        assert any("company name" in h.lower() or "Company name" in h for h in data["correction_hints"])

    def test_company_name_absent_not_mismatch(self) -> None:
        """When company name is absent from model (no plausible candidate strings),
        the check should skip/pass-with-note rather than warn — absence is not a mismatch signal."""
        # Model with only numeric rows and no company-name-like strings
        model_numeric_only = {
            "sheets": [
                {
                    "name": "P&L",
                    "headers": ["Jan 2025", "Feb 2025", "Mar 2025"],
                    "rows": [
                        [50000, 55000, 60000],
                        [120000, 120000, 120000],
                        [840000, 920000, 1000000],
                    ],
                    "detected_type": "pnl",
                    "periodicity": "monthly",
                    "row_count": 3,
                    "col_count": 3,
                    "pre_header_rows": [],
                }
            ],
            "source_format": "xlsx",
            "source_file": "template-model.xlsx",
            "periodicity_summary": "monthly",
        }
        inputs = {**_INPUTS, "company": {**_INPUTS["company"], "company_name": "MyStartup"}}
        rc, data, _ = _run(inputs, model_numeric_only)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        company_check = checks_by_id["COMPANY_NAME"]
        # Absent name must NOT warn — only a conflicting candidate name warrants a warn
        assert company_check["status"] != "warn", (
            f"Company name absent from model should not warn; got status={company_check['status']!r}, "
            f"message={company_check.get('message', '')!r}"
        )
        # Should be skip (nothing to cross-check) or pass
        assert company_check["status"] in ("skip", "pass"), (
            f"Expected skip or pass for absent company name, got {company_check['status']!r}"
        )

    def test_salary_untraceable(self) -> None:
        """Warn when salary values aren't found in model_data."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["expenses"]["headcount"] = [
            {"role": "Engineer", "count": 5, "salary_annual": 250000},
        ]
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SALARY_TRACEABILITY"]["status"] == "warn"
        assert any("salary" in h.lower() or "Salary" in h for h in data["correction_hints"])

    def test_revenue_untraceable(self) -> None:
        """Warn when revenue values aren't found in model_data."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["revenue"]["mrr"]["value"] = 777777
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["REVENUE_TRACEABILITY"]["status"] == "warn"
        assert any("revenue" in h.lower() or "Revenue" in h for h in data["correction_hints"])

    def test_cash_not_found(self) -> None:
        """Warn when cash balance isn't found in model_data."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"]["current_balance"] = 555555
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["CASH_BALANCE"]["status"] == "warn"

    def test_scale_plausibility_low_cash(self) -> None:
        """Warn when cash balance is implausibly low for stage."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"]["current_balance"] = 4000  # $4K — model in thousands?
        rc, data, _ = _run(inputs, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "warn"
        assert any("thousand" in h.lower() or "million" in h.lower() for h in data["correction_hints"])

    def test_scale_plausibility_indicator_in_header(self) -> None:
        """Warn when model has ($000) scale indicator."""
        model = json.loads(json.dumps(_MODEL_DATA))
        model["sheets"][0]["headers"][0] = "Line Item ($000)"
        rc, data, _ = _run(_INPUTS, model)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "warn"
        assert any("($000)" in s for s in checks_by_id["SCALE_PLAUSIBILITY"].get("signals", []))

    def test_scale_plausibility_pass(self) -> None:
        """Pass when values are plausible for stage."""
        rc, data, _ = _run(_INPUTS, _MODEL_DATA)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "pass"


class TestScalePlausibilityCurrency:
    """SCALE_PLAUSIBILITY's absolute-dollar floors (cash-balance stage range,
    $2K/person/month gross expense, $10K/year salary) are USD-tuned and don't
    read `currency`. A legitimate non-USD value can look "too low" purely
    because it's a different currency, not because the model is mis-scaled —
    these floors must not fire (or feed --fix) for a non-USD model."""

    def test_low_cash_balance_not_flagged_for_non_usd(self) -> None:
        """$4K cash balance would warn for a USD seed-stage company (floor
        $50K) — for a non-USD model the raw number isn't a USD reading, so
        the floor must not fire."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["currency"] = "INR"
        inputs["cash"]["current_balance"] = 4000
        rc, data, stderr = _run(inputs, _MODEL_DATA)
        assert rc == 0, stderr
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "pass"

    def test_low_salary_not_flagged_for_non_usd(self) -> None:
        """A $5K/year salary would warn as implausibly low for USD (floor
        $10K) — for a non-USD model the floor must not fire."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["currency"] = "INR"
        inputs["expenses"]["headcount"][0]["salary_annual"] = 5000
        rc, data, stderr = _run(inputs, _MODEL_DATA)
        assert rc == 0, stderr
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "pass"

    def test_low_per_person_expense_not_flagged_for_non_usd(self) -> None:
        """The $2K/person/month gross-expense floor must not fire for a
        non-USD model."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["currency"] = "INR"
        inputs["expenses"]["headcount"] = [
            {"role": "R&D", "count": 5, "salary_annual": 6000},
        ]
        rc, data, stderr = _run(inputs, _MODEL_DATA)
        assert rc == 0, stderr
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "pass"

    def test_scale_plausibility_usd_explicit_matches_absent(self) -> None:
        """Back-compat: currency: 'USD' behaves identically to absent."""
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"]["current_balance"] = 4000
        rc1, data1, stderr1 = _run(inputs, _MODEL_DATA)
        inputs_usd = json.loads(json.dumps(inputs))
        inputs_usd["currency"] = "USD"
        rc2, data2, stderr2 = _run(inputs_usd, _MODEL_DATA)
        assert rc1 == 0, stderr1
        assert rc2 == 0, stderr2
        checks1 = {c["id"]: c for c in data1["checks"]}
        checks2 = {c["id"]: c for c in data2["checks"]}
        assert checks1["SCALE_PLAUSIBILITY"] == checks2["SCALE_PLAUSIBILITY"]

    def test_plausibility_vote_non_usd_never_blocks_or_triggers_fix(self) -> None:
        """The vote that gates --fix must return "plausible" (no USD floors
        applied) for a non-USD model, even with USD-implausible raw numbers —
        this is what prevents --fix from ever firing off a USD floor for a
        non-USD model."""
        mod = _load_validate_extraction_module()
        non_usd_inputs = {
            "company": {"stage": "seed"},
            "currency": "INR",
            "cash": {"current_balance": 4000, "monthly_net_burn": 500},
            "revenue": {"mrr": {"value": 200}},
            "expenses": {"headcount": [{"salary_annual": 5000}]},
        }
        ok, checked = mod._plausibility_vote(non_usd_inputs)
        assert ok is True
        assert checked == 0

    def test_fix_never_triggers_for_non_usd_model(self) -> None:
        """--fix must never scale a non-USD model off the USD plausibility
        vote, even when a scale indicator (e.g. "($000)") is present."""
        inputs_inr = json.loads(json.dumps(_INPUTS_UNSCALED))
        inputs_inr["currency"] = "INR"
        rc, data, modified, stderr = _run_fix(inputs_inr, _MODEL_THOUSANDS)
        assert rc == 0, stderr
        assert modified["cash"]["current_balance"] == 3900  # unchanged
        assert not modified.get("metadata", {}).get("scale_correction")


# ---------------------------------------------------------------------------
# Pre-header tests
# ---------------------------------------------------------------------------


class TestPreHeaderRows:
    def test_company_name_in_pre_header(self) -> None:
        """Company name found via pre_header_rows passes."""
        # Model data has "Acme Corp" only in pre_header_rows
        model = json.loads(json.dumps(_MODEL_DATA))
        # Remove "Acme Corp" from data rows
        model["sheets"][0]["rows"] = [
            ["Revenue", 50000, 55000, 60000],
            ["Payroll", 120000, 120000, 120000],
            ["Cash Balance", 840000, 920000, 1000000],
        ]
        # Company name is in pre_header_rows
        model["sheets"][0]["pre_header_rows"] = [["Acme Corp", None, None, None]]

        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"]["current_balance"] = 840000
        inputs["expenses"]["headcount"] = [
            {"role": "Payroll", "count": 5, "salary_annual": 120000},
        ]
        rc, data, _ = _run(inputs, model)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["COMPANY_NAME"]["status"] == "pass"


# ---------------------------------------------------------------------------
# Periodicity tests
# ---------------------------------------------------------------------------


class TestPeriodicity:
    def test_quarterly_salary_traceable(self) -> None:
        """Quarterly salary × 3 found when periodicity is quarterly."""
        model = {
            "sheets": [
                {
                    "name": "P&L",
                    "headers": ["Line Item", "Q1 2025", "Q2 2025"],
                    "rows": [
                        ["Revenue", 150000, 165000],
                        ["R&D Payroll", 360000, 360000],
                        ["Cash Balance", 1000000, 850000],
                    ],
                    "detected_type": "pnl",
                    "periodicity": "quarterly",
                    "row_count": 3,
                    "col_count": 3,
                    "pre_header_rows": [["TestCo", None, None]],
                }
            ],
            "source_format": "xlsx",
            "source_file": "test.xlsx",
            "periodicity_summary": "quarterly",
        }
        inputs = {
            "company": {
                "company_name": "TestCo",
                "slug": "testco",
                "stage": "seed",
                "sector": "SaaS",
                "geography": "US",
                "model_format": "spreadsheet",
            },
            "revenue": {"mrr": {"value": 55000, "as_of": "2025-06"}, "customers": 50},
            "cash": {"current_balance": 850000, "monthly_net_burn": 50000},
            "expenses": {
                "headcount": [
                    {"role": "R&D", "count": 5, "salary_annual": 120000},
                ],
            },
        }
        rc, data, _ = _run(inputs, model)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        # salary_annual=120000, monthly=10000, quarterly=30000
        # Model has 360000 quarterly. 120000 * 3 = 360000. Should be traceable.
        assert checks_by_id["SALARY_TRACEABILITY"]["status"] == "pass"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cell ref provenance tests
# ---------------------------------------------------------------------------


class TestCellRefProvenance:
    def test_pass_includes_source_refs(self) -> None:
        """When cell_refs available, pass results include source_refs."""
        model = json.loads(json.dumps(_MODEL_DATA))
        model["sheets"][0]["cell_refs"] = [
            {"row_index": 0, "label": "Revenue", "cols": {"Mar 2025": "D2"}},
            {"row_index": 1, "label": "Payroll - R&D", "cols": {"Mar 2025": "D3"}},
            {"row_index": 3, "label": "Cash Balance", "cols": {"Mar 2025": "D5"}},
        ]
        rc, data, _ = _run(_INPUTS, model)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        # Revenue check should include structured source_refs
        rev_check = checks_by_id["REVENUE_TRACEABILITY"]
        assert rev_check["status"] == "pass"
        assert "source_refs" in rev_check
        mrr_ref = rev_check["source_refs"].get("MRR")
        assert mrr_ref is not None
        assert mrr_ref["confidence"] == "best_match"
        assert "!" in mrr_ref["ref"]  # e.g. "P&L!D2"

        # Cash check should include structured source_refs
        cash_check = checks_by_id["CASH_BALANCE"]
        assert cash_check["status"] == "pass"
        assert "source_refs" in cash_check
        cb_ref = cash_check["source_refs"]["current_balance"]
        assert cb_ref["confidence"] == "best_match"

        # Salary check should include structured source_refs
        sal_check = checks_by_id["SALARY_TRACEABILITY"]
        assert sal_check["status"] == "pass"
        assert "source_refs" in sal_check
        for role_ref in sal_check["source_refs"].values():
            assert role_ref["confidence"] == "best_match"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_missing_pre_header_rows_key(self) -> None:
        """Missing pre_header_rows key treated as empty array."""
        model = json.loads(json.dumps(_MODEL_DATA))
        del model["sheets"][0]["pre_header_rows"]
        rc, data, _ = _run(_INPUTS, model)
        assert rc == 0
        assert data["status"] in ("pass", "warn")


class TestNullOptionalBlocks:
    """Schema-legal null optional blocks (present with value null) must not crash.

    dict.get(key, {}) returns None when the key is present-with-null (the default
    only applies when the key is absent), so a downstream .get() raised
    AttributeError. Null blocks are schema-legal (only company is required).
    """

    def test_plausibility_vote_null_blocks_no_crash(self) -> None:
        mod = _load_validate_extraction_module()
        ok, _n = mod._plausibility_vote({"company": {"stage": "seed"}, "cash": None, "revenue": None, "expenses": None})
        # Nothing checkable -> never fix blindly; returns the "no vote" result.
        assert ok is True

    def test_fix_path_null_cash_block_no_crash(self) -> None:
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"] = None
        rc, data, stderr = _run(inputs, _MODEL_DATA, extra_args=["--fix"])
        assert rc == 0, stderr
        assert "Traceback" not in stderr
        assert data.get("status") in ("pass", "warn", "skip")

    def test_validate_null_blocks_all_checks_no_crash(self) -> None:
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["cash"] = None
        inputs["revenue"] = None
        inputs["expenses"] = None
        rc, data, stderr = _run(inputs, _MODEL_DATA)
        assert rc == 0, stderr
        assert "Traceback" not in stderr
        assert all("status" in c for c in data.get("checks", []))

    def test_null_headcount_list_no_crash(self) -> None:
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["expenses"] = {"headcount": None}
        rc, data, stderr = _run(inputs, _MODEL_DATA)
        assert rc == 0, stderr
        assert "Traceback" not in stderr

    def test_null_metadata_no_crash(self) -> None:
        inputs = json.loads(json.dumps(_INPUTS))
        inputs["metadata"] = None
        rc, data, stderr = _run(inputs, _MODEL_DATA, extra_args=["--fix"])
        assert rc == 0, stderr
        assert "Traceback" not in stderr


# ---------------------------------------------------------------------------
# --fix scale correction tests
# ---------------------------------------------------------------------------


def _run_fix(
    inputs: dict[str, Any],
    model_data: dict[str, Any],
    extra_args: list[str] | None = None,
) -> tuple[int, dict[str, Any], dict[str, Any], str]:
    """Run with --fix, return (exit_code, result_json, modified_inputs, stderr)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs_path = os.path.join(tmpdir, "inputs.json")
        model_data_path = os.path.join(tmpdir, "model_data.json")
        with open(inputs_path, "w") as f:
            json.dump(inputs, f)
        with open(model_data_path, "w") as f:
            json.dump(model_data, f)

        cmd = [
            sys.executable,
            os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py"),
            "--inputs",
            inputs_path,
            "--model-data",
            model_data_path,
            "--fix",
            "--pretty",
        ]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}

        # Re-read the (possibly modified) inputs
        with open(inputs_path) as f:
            modified_inputs = json.load(f)

        return result.returncode, data, modified_inputs, result.stderr


# Model in thousands — ($000) indicator, unscaled values
_MODEL_THOUSANDS: dict[str, Any] = {
    "sheets": [
        {
            "name": "Summary",
            "headers": ["Line Item ($000)", "Jan 2025", "Feb 2025"],
            "rows": [
                ["Revenue", 50, 55],
                ["Payroll", 120, 120],
                ["Cash Balance", 4000, 3900],
            ],
            "detected_type": "summary",
            "periodicity": "monthly",
            "row_count": 3,
            "col_count": 3,
            "pre_header_rows": [["Acme Corp", None, None]],
            "cell_refs": [],
        }
    ],
    "source_format": "xlsx",
    "source_file": "model.xlsx",
    "periodicity_summary": "monthly",
}

# Inputs with unscaled values (model is in $000 but values not multiplied)
_INPUTS_UNSCALED: dict[str, Any] = {
    "company": {
        "company_name": "Acme Corp",
        "slug": "acme-corp",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "US",
        "model_format": "spreadsheet",
    },
    "revenue": {
        "mrr": {"value": 55, "as_of": "2025-02"},
        "customers": 100,
    },
    "cash": {
        "current_balance": 3900,
        "monthly_net_burn": 65,
    },
    "expenses": {
        "headcount": [
            {"role": "R&D", "count": 5, "salary_annual": 120, "burden_pct": 0.25},
        ],
        "opex_monthly": [
            {"category": "Cloud", "amount": 10},
        ],
        "cogs": {"hosting": 5},
    },
    "unit_economics": {
        "cac": {"total": 8, "components": {"ad_spend": 3, "sales_salary": 5}},
        "ltv": {"value": 20, "inputs": {"arpu_monthly": 0.55, "churn_monthly": 0.03, "gross_margin": 0.8}},
        "gross_margin": 0.8,
    },
}


class TestScaleFix:
    def test_fix_applies_multiplier(self) -> None:
        """--fix scales monetary values by 1000x when ($000) indicator found."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        assert modified["cash"]["current_balance"] == 3_900_000
        assert modified["cash"]["monthly_net_burn"] == 65_000
        assert modified["revenue"]["mrr"]["value"] == 55_000
        assert data.get("fixed") is True

    def test_fix_scales_array_fields(self) -> None:
        """--fix scales headcount salary and opex amount, not count/burden_pct."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        hc = modified["expenses"]["headcount"][0]
        assert hc["salary_annual"] == 120_000
        assert hc["count"] == 5  # not scaled
        assert hc["burden_pct"] == 0.25  # not scaled
        assert modified["expenses"]["opex_monthly"][0]["amount"] == 10_000
        assert modified["expenses"]["cogs"]["hosting"] == 5_000

    def test_fix_scales_cac_components(self) -> None:
        """--fix scales CAC total and components."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        assert modified["unit_economics"]["cac"]["total"] == 8_000
        assert modified["unit_economics"]["cac"]["components"]["ad_spend"] == 3_000
        assert modified["unit_economics"]["cac"]["components"]["sales_salary"] == 5_000

    def test_fix_skips_non_monetary(self) -> None:
        """--fix does not scale rates, counts, or percentages."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        assert modified["revenue"]["customers"] == 100  # count, not scaled
        assert modified["unit_economics"]["gross_margin"] == 0.8  # rate
        assert modified["unit_economics"]["ltv"]["inputs"]["churn_monthly"] == 0.03
        assert modified["unit_economics"]["ltv"]["inputs"]["gross_margin"] == 0.8

    def test_fix_records_metadata(self) -> None:
        """--fix writes scale_correction to metadata."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        sc = modified["metadata"]["scale_correction"]
        assert sc["factor"] == 1000
        assert sc["fields_corrected"] > 0
        assert data["scale_correction"]["factor"] == 1000

    def test_fix_noop_when_already_plausible(self) -> None:
        """--fix does not double-scale when values are already plausible."""
        # Scale inputs to full dollars first
        already_scaled = json.loads(json.dumps(_INPUTS_UNSCALED))
        already_scaled["cash"]["current_balance"] = 3_900_000
        already_scaled["cash"]["monthly_net_burn"] = 65_000
        already_scaled["revenue"]["mrr"]["value"] = 55_000
        already_scaled["expenses"]["headcount"][0]["salary_annual"] = 120_000

        rc, data, modified, stderr = _run_fix(already_scaled, _MODEL_THOUSANDS)
        assert rc == 0
        # Values should NOT have been multiplied again
        assert modified["cash"]["current_balance"] == 3_900_000
        assert modified["expenses"]["headcount"][0]["salary_annual"] == 120_000
        assert data.get("fixed") is not True

    def test_fix_noop_when_no_indicator(self) -> None:
        """--fix does nothing when model has no scale indicator."""
        rc, data, modified, stderr = _run_fix(_INPUTS, _MODEL_DATA)
        assert rc == 0
        # Values unchanged
        assert modified["cash"]["current_balance"] == _INPUTS["cash"]["current_balance"]
        assert data.get("fixed") is not True

    def test_fix_revalidation_passes(self) -> None:
        """After --fix, re-running validation passes SCALE_PLAUSIBILITY."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        assert checks_by_id["SCALE_PLAUSIBILITY"]["status"] == "pass"

    def test_fix_traceability_passes_after_scale(self) -> None:
        """After --fix, traceability checks pass (scale-aware lookup)."""
        rc, data, modified, stderr = _run_fix(_INPUTS_UNSCALED, _MODEL_THOUSANDS)
        assert rc == 0
        checks_by_id = {c["id"]: c for c in data["checks"]}
        # Cash was 3900 in model, now 3900000 in inputs — should still trace
        assert checks_by_id["CASH_BALANCE"]["status"] == "pass"

    def test_fix_noop_when_already_corrected(self) -> None:
        """--fix skips if metadata.scale_correction already present."""
        already_corrected = json.loads(json.dumps(_INPUTS_UNSCALED))
        already_corrected["metadata"] = {"scale_correction": {"factor": 1000, "fields_corrected": 10}}
        rc, data, modified, stderr = _run_fix(already_corrected, _MODEL_THOUSANDS)
        assert rc == 0
        # Values should NOT have been changed
        assert modified["cash"]["current_balance"] == 3900
        assert data.get("fixed") is not True


# ---------------------------------------------------------------------------
# Scale-fix guard tests (minor 14)
# ---------------------------------------------------------------------------


def _model_with_scale_indicator(indicator: str = "($000)") -> dict[str, Any]:
    """Minimal model_data with the given scale indicator string in a header."""
    return {
        "sheets": [
            {
                "name": "Summary",
                "headers": [f"Line Item {indicator}", "Jan 2025"],
                "rows": [
                    ["Cash Balance", 30],
                ],
                "detected_type": "summary",
                "periodicity": "monthly",
                "row_count": 1,
                "col_count": 2,
                "pre_header_rows": [],
                "cell_refs": [],
            }
        ],
        "source_format": "xlsx",
        "source_file": "model.xlsx",
        "periodicity_summary": "monthly",
    }


class TestScaleFixGuards:
    def test_scale_fix_skipped_on_single_checked_field(self, tmp_path: Any) -> None:
        """One implausibly-low field + a ($000) indicator is too weak a signal for
        a x1000 auto-rewrite — require >= 2 checked monetary fields (regression:
        a majority vote of one corrupted correct values).

        cash_balance=30_000 is below the seed lower bound (50_000), but it's the
        ONLY checked monetary field.  The fix must be skipped.
        """
        inputs: dict[str, Any] = {
            "company": {"stage": "seed", "model_format": "spreadsheet"},
            "cash": {"current_balance": 30_000},
        }
        model = _model_with_scale_indicator("($000)")

        inputs_path = str(tmp_path / "inputs.json")
        model_path = str(tmp_path / "model.json")
        with open(inputs_path, "w") as f:
            json.dump(inputs, f)
        with open(model_path, "w") as f:
            json.dump(model, f)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py"),
                "--inputs",
                inputs_path,
                "--model-data",
                model_path,
                "--fix",
            ],
            capture_output=True,
            text=True,
        )
        with open(inputs_path) as f:
            written = json.load(f)

        assert written["cash"]["current_balance"] == 30_000, (
            f"Expected 30_000 (untouched) but got {written['cash']['current_balance']}; stderr: {result.stderr}"
        )
        assert not written.get("metadata", {}).get("scale_correction"), (
            "scale_correction should not be written when only one field checked"
        )

    def test_scale_fix_skipped_when_post_fix_implausible(self, tmp_path: Any) -> None:
        """If applying the factor lands values OUTSIDE plausible ranges, the fix
        must be skipped with a warning, not written.

        For seed stage:
          cash_balance range: (50_000, 100_000_000)
          monthly_burn range: (5_000, 2_000_000)

        We pick values that are BOTH implausible before AND after x1000:
          cash_balance=500_000_000  → pre: 500M > 100M (implausible)
                                    → post x1000: 500B > 100M (still implausible)
          monthly_burn=5_000_000   → pre: 5M > 2M (implausible)
                                    → post x1000: 5B > 2M (still implausible)

        checked_count == 2, pre-fix majority implausible → enters the fix branch.
        post-fix majority still implausible → must skip with warning.
        """
        inputs: dict[str, Any] = {
            "company": {"stage": "seed", "model_format": "spreadsheet"},
            "cash": {
                "current_balance": 500_000_000,  # above 100M seed cap → implausible
                "monthly_net_burn": 5_000_000,  # above 2M seed cap → implausible
            },
        }
        model = _model_with_scale_indicator("($000)")

        inputs_path = str(tmp_path / "inputs.json")
        model_path = str(tmp_path / "model.json")
        with open(inputs_path, "w") as f:
            json.dump(inputs, f)
        with open(model_path, "w") as f:
            json.dump(model, f)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(FMR_SCRIPTS_DIR, "validate_extraction.py"),
                "--inputs",
                inputs_path,
                "--model-data",
                model_path,
                "--fix",
            ],
            capture_output=True,
            text=True,
        )
        with open(inputs_path) as f:
            written = json.load(f)

        assert written["cash"]["current_balance"] == 500_000_000, (
            f"Expected 500_000_000 (untouched) but got {written['cash']['current_balance']}; stderr: {result.stderr}"
        )
        assert not written.get("metadata", {}).get("scale_correction"), (
            "scale_correction should not be written when post-fix values are implausible"
        )
        # Should emit a warning to stderr
        assert "implausible" in result.stderr.lower() or "warning" in result.stderr.lower(), (
            f"Expected warning in stderr but got: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Mixed/unknown periodicity tests (minor 15)
# ---------------------------------------------------------------------------


class TestMixedPeriodicity:
    def test_traceability_tries_quarterly_and_annual_for_mixed_periodicity(self) -> None:
        """periodicity_summary 'mixed' must try x3 and x12 scaling — a monthly
        inputs value sourced from a quarterly sheet is traceable (regression:
        'mixed' was treated as monthly, producing spurious warns)."""
        mod = _load_validate_extraction_module()
        # Model has a quarterly figure: 300_000 (= 100_000 * 3)
        model_data: dict[str, Any] = {
            "periodicity_summary": "mixed",
            "sheets": [{"name": "Sheet1", "rows": [[300_000]]}],
        }
        # inputs has monthly value 100_000; quarterly = 300_000 → traceable
        assert mod._find_numeric_in_model(100_000, model_data, periodicity_aware=True), (
            "_find_numeric_in_model should find 100_000 via x3 scaling in a 'mixed' model"
        )

    def test_traceability_tries_annual_for_mixed_periodicity(self) -> None:
        """periodicity_summary 'mixed' must try x12 — a monthly inputs value
        sourced from an annual sheet is traceable."""
        mod = _load_validate_extraction_module()
        # Model has an annual figure: 1_200_000 (= 100_000 * 12)
        model_data: dict[str, Any] = {
            "periodicity_summary": "mixed",
            "sheets": [{"name": "Sheet1", "rows": [[1_200_000]]}],
        }
        assert mod._find_numeric_in_model(100_000, model_data, periodicity_aware=True), (
            "_find_numeric_in_model should find 100_000 via x12 scaling in a 'mixed' model"
        )

    def test_unknown_periodicity_tries_quarterly_and_annual(self) -> None:
        """periodicity_summary 'unknown' must also try x3 and x12."""
        mod = _load_validate_extraction_module()
        model_data: dict[str, Any] = {
            "periodicity_summary": "unknown",
            "sheets": [{"name": "Sheet1", "rows": [[360_000]]}],
        }
        # 30_000 * 12 = 360_000
        assert mod._find_numeric_in_model(30_000, model_data, periodicity_aware=True), (
            "_find_numeric_in_model should find 30_000 via x12 in an 'unknown' model"
        )


# ---------------------------------------------------------------------------
# Null-coercion + anti-hallucination regressions
# ---------------------------------------------------------------------------


def test_null_headcount_count_does_not_crash() -> None:
    """validate_extraction.py must not raise on a headcount entry with count: null
    in the scale-plausibility headcount sum."""
    inputs = {
        "company": {"name": "TestCo", "stage": "seed"},
        "cash": {"current_balance": 1_000_000, "monthly_net_burn": 100_000},
        "expenses": {"headcount": [{"role": "eng", "count": None}]},
    }
    model_data = {
        "sheets": [
            {
                "name": "S",
                "headers": ["a"],
                "rows": [["TestCo"]],
                "detected_type": None,
                "periodicity": None,
                "row_count": 1,
                "col_count": 1,
                "pre_header_rows": [],
                "cell_refs": [],
            }
        ],
        "source_format": "xlsx",
        "source_file": "x.xlsx",
        "periodicity_summary": "unknown",
    }
    rc, data, stderr = _run(inputs, model_data)
    assert rc in (0, 1), f"unexpected exit on null count: {stderr}"
    assert data, f"validate_extraction emitted no JSON (likely crashed): {stderr}"


def test_fuzzy_match_rejects_short_substring() -> None:
    """A 1-2 char cell that is a substring of the company name must NOT fuzzy-
    match — otherwise the COMPANY_NAME anti-hallucination gate false-passes."""
    mod = _load_validate_extraction_module()
    # '-' is a substring of any hyphenated name; must not match.
    assert mod._fuzzy_match("-", "Acme-Corp Industries") is False
    # 2-char fragment must not match.
    assert mod._fuzzy_match("Ac", "Acme Corp") is False
    # Legitimate full / first-word match still passes.
    assert mod._fuzzy_match("Acme", "Acme Corp Ltd") is True
    assert mod._fuzzy_match("Acme Corp", "Acme Corp Ltd Inc") is True
