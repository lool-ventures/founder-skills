#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tests for validate_inputs.py.

Run:  pytest founder-skills/tests/test_validate_inputs.py -v
"""

from __future__ import annotations

import os
import sys
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")

# Import the validate function directly for unit testing
sys.path.insert(0, FMR_SCRIPTS_DIR)
from validate_inputs import validate  # type: ignore[import-not-found,import-untyped]  # noqa: E402


def _base_inputs(**overrides: Any) -> dict[str, Any]:
    """Minimal valid inputs for testing."""
    data: dict[str, Any] = {
        "company": {"stage": "seed"},
        "revenue": {
            "mrr": {"value": 50000},
            "arr": {"value": 600000},
            "growth_rate_monthly": 0.08,
        },
        "cash": {
            "current_balance": 2000000,
            "monthly_net_burn": 80000,
        },
        "unit_economics": {
            "gross_margin": 0.75,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and k in data and isinstance(data[k], dict):
            data[k].update(v)
        else:
            data[k] = v
    return data


# ---------------------------------------------------------------------------
# Layer 1 — Structural
# ---------------------------------------------------------------------------


def test_structural_burn_sign_error() -> None:
    """Negative burn should produce BURN_SIGN_ERROR."""
    inputs = _base_inputs()
    inputs["cash"]["monthly_net_burn"] = -50000
    result = validate(inputs)
    assert not result["valid"]
    codes = [e["code"] for e in result["errors"]]
    assert "BURN_SIGN_ERROR" in codes


def test_structural_null_mrr_no_error() -> None:
    """Null MRR is not a structural error (it's a completeness warning)."""
    inputs = _base_inputs()
    inputs["revenue"]["mrr"]["value"] = None
    result = validate(inputs)
    # No structural errors for null values
    error_codes = [e["code"] for e in result["errors"]]
    assert "TYPE_ERROR" not in error_codes


def test_structural_null_cash_no_error() -> None:
    """Null cash balance is not a structural error."""
    inputs = _base_inputs()
    inputs["cash"]["current_balance"] = None
    result = validate(inputs)
    error_codes = [e["code"] for e in result["errors"]]
    assert "TYPE_ERROR" not in error_codes


def test_structural_type_error() -> None:
    """Non-numeric values should produce TYPE_ERROR."""
    inputs = _base_inputs()
    inputs["cash"]["monthly_net_burn"] = "not a number"
    result = validate(inputs)
    assert not result["valid"]
    codes = [e["code"] for e in result["errors"]]
    assert "TYPE_ERROR" in codes


# ---------------------------------------------------------------------------
# Layer 2 — Consistency
# ---------------------------------------------------------------------------


def test_consistency_arpu_inconsistent() -> None:
    """ARPU × customers should roughly equal MRR."""
    inputs = _base_inputs()
    inputs["revenue"]["customers"] = 100
    inputs["unit_economics"]["ltv"] = {
        "inputs": {"arpu_monthly": 200},  # 200 × 100 = 20000 vs MRR 50000
    }
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "ARPU_INCONSISTENT" in codes


def test_consistency_arr_mrr_mismatch() -> None:
    """ARR/12 should roughly equal MRR."""
    inputs = _base_inputs()
    inputs["revenue"]["arr"]["value"] = 1200000  # 1.2M/12 = 100K vs MRR 50K
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "ARR_MRR_MISMATCH" in codes


def test_consistency_both_pass() -> None:
    """Consistent values should not produce warnings."""
    inputs = _base_inputs()
    inputs["revenue"]["arr"]["value"] = 600000  # 600K/12 = 50K = MRR
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "ARR_MRR_MISMATCH" not in codes


# ---------------------------------------------------------------------------
# Layer 3 — Sanity
# ---------------------------------------------------------------------------


def test_sanity_arpu_suspect() -> None:
    """ARPU >= MRR with multiple customers is suspect."""
    inputs = _base_inputs()
    inputs["revenue"]["customers"] = 10
    inputs["unit_economics"]["ltv"] = {
        "inputs": {"arpu_monthly": 60000},  # ARPU > MRR
    }
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "ARPU_SUSPECT" in codes


def test_sanity_growth_rate_suspect() -> None:
    """Growth rate >= 50% monthly is suspicious."""
    inputs = _base_inputs()
    inputs["revenue"]["growth_rate_monthly"] = 0.55
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "GROWTH_RATE_SUSPECT" in codes


def test_sanity_valid_passthrough() -> None:
    """Normal values should not produce sanity warnings."""
    inputs = _base_inputs()
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "ARPU_SUSPECT" not in codes
    assert "GROWTH_RATE_SUSPECT" not in codes


# ---------------------------------------------------------------------------
# Layer 4 — Completeness
# ---------------------------------------------------------------------------


def test_completeness_seed_missing_cash() -> None:
    """Seed+ should warn when cash balance is missing."""
    inputs = _base_inputs()
    inputs["cash"]["current_balance"] = None
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "MISSING_CASH_BALANCE" in codes


def test_completeness_series_a_missing_retention() -> None:
    """Series-a+ should warn when NRR and GRR both missing."""
    inputs = _base_inputs()
    inputs["company"]["stage"] = "series-a"
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "MISSING_RETENTION" in codes


def test_completeness_seed_missing_gross_margin() -> None:
    """Seed+ should warn when gross_margin is missing."""
    inputs = _base_inputs()
    del inputs["unit_economics"]["gross_margin"]
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "MISSING_GROSS_MARGIN" in codes


# ---------------------------------------------------------------------------
# --fix mode
# ---------------------------------------------------------------------------


def test_sanity_expense_coverage_suspect() -> None:
    """Headcount with $0 salary vs significant burn should flag EXPENSE_COVERAGE_SUSPECT."""
    inputs = _base_inputs()
    inputs["expenses"] = {
        "headcount": [
            {"role": "Engineering", "count": 11, "start_month": "2026-01", "salary_annual": 0},
        ],
        "cogs": {"hosting": 500},
    }
    # burn is 80K, revenue is 50K, so expected expenses = 130K
    # extracted expenses = 0 (salary) + 500 (hosting) = 500 — way below 50%
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "EXPENSE_COVERAGE_SUSPECT" in codes
    # Verify it's critical
    suspect = [w for w in result["warnings"] if w["code"] == "EXPENSE_COVERAGE_SUSPECT"][0]
    assert suspect["critical"] is True


def test_sanity_expense_coverage_ok() -> None:
    """Well-populated headcount should not flag EXPENSE_COVERAGE_SUSPECT."""
    inputs = _base_inputs()
    inputs["expenses"] = {
        "headcount": [
            {"role": "Engineering", "count": 5, "start_month": "2026-01", "salary_annual": 120000},
            {"role": "G&A", "count": 2, "start_month": "2026-01", "salary_annual": 80000},
        ],
        "opex_monthly": [
            {"category": "Rent", "amount": 5000, "start_month": "2026-01"},
        ],
        "cogs": {"hosting": 2000},
    }
    # burn=80K, revenue=50K → expected=130K
    # extracted = 5*10K + 2*6.67K + 5K + 2K = 50K + 13.3K + 7K = 70.3K → 54% of 130K → above 50%
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "EXPENSE_COVERAGE_SUSPECT" not in codes


def test_sanity_expense_coverage_no_headcount() -> None:
    """No headcount entries should not trigger EXPENSE_COVERAGE_SUSPECT."""
    inputs = _base_inputs()
    # No expenses block at all — should not crash or flag
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "EXPENSE_COVERAGE_SUSPECT" not in codes


def test_sanity_expense_coverage_with_burden() -> None:
    """Burden percentage should be included in expense coverage calculation."""
    inputs = _base_inputs()
    inputs["cash"]["monthly_net_burn"] = 200000
    inputs["expenses"] = {
        "headcount": [
            {
                "role": "Engineering",
                "count": 10,
                "start_month": "2026-01",
                "salary_annual": 180000,
                "burden_pct": 0.30,
            },
        ],
    }
    # burn=200K, revenue=50K → expected=250K
    # extracted = 10 * 15K * 1.30 = 195K → 78% of 250K → above 50%
    result = validate(inputs)
    codes = [w["code"] for w in result["warnings"]]
    assert "EXPENSE_COVERAGE_SUSPECT" not in codes


def test_fix_sign_applied() -> None:
    """--fix should correct negative burn and report the fix."""
    inputs = _base_inputs()
    inputs["cash"]["monthly_net_burn"] = -50000
    result = validate(inputs, fix=True)
    assert result["valid"]  # error is fixed
    assert len(result["auto_fixes"]) == 1
    fix = result["auto_fixes"][0]
    assert fix["code"] == "BURN_SIGN_ERROR"
    assert fix["old_value"] == -50000
    assert fix["new_value"] == 50000
    # The inputs dict should also be mutated
    assert inputs["cash"]["monthly_net_burn"] == 50000


def test_fix_clean_passthrough() -> None:
    """Clean inputs should pass through unchanged with --fix."""
    inputs = _base_inputs()
    result = validate(inputs, fix=True)
    assert result["valid"]
    assert len(result["auto_fixes"]) == 0
    assert len(result["errors"]) == 0
