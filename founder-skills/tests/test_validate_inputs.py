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


# ---------------------------------------------------------------------------
# EXPENSE_COVERAGE_SUSPECT on a SPARSE-BY-DESIGN source.
#
# The two tests above bracket the 50% threshold, but BOTH fixtures are
# extraction-shaped: one is a parser bug (salary_annual: 0), the other a fully
# populated model. A CONVERSATIONAL source falls in the gap between them — real
# salaries stated, no opex breakdown, which is that intake mode working normally.
# Firing `critical` there made the gate satisfiable only by inventing the missing
# expenses, which is exactly what happened in a live run. Anti-hallucination
# gates must never be clearable by fabrication.
# ---------------------------------------------------------------------------


def _sparse_conversational_inputs() -> dict:
    """Founder gives total burn + headcount, no opex breakdown. ~34% coverage."""
    inputs = _base_inputs()
    inputs["company"]["model_format"] = "conversational"
    inputs["cash"]["monthly_net_burn"] = 900000
    inputs["revenue"] = {"mrr": {"value": 420000}}
    inputs["expenses"] = {
        "headcount": [
            {"role": "All", "count": 14, "start_month": "2026-01", "salary_annual": 384000},
        ],
    }
    return inputs


def _suspect(result: dict) -> dict | None:
    hits = [w for w in result["warnings"] if w["code"] == "EXPENSE_COVERAGE_SUSPECT"]
    return hits[0] if hits else None


def test_expense_coverage_not_critical_for_conversational_source() -> None:
    w = _suspect(validate(_sparse_conversational_inputs()))
    assert w is not None, "the advisory should still fire — it is informative, just not a STOP"
    assert w["critical"] is False, "a conversational source lacking an opex breakdown is expected"


def test_expense_coverage_not_critical_for_partial_source() -> None:
    inputs = _sparse_conversational_inputs()
    inputs["company"]["model_format"] = "partial"
    w = _suspect(validate(inputs))
    assert w is not None and w["critical"] is False


def test_expense_coverage_stays_critical_for_spreadsheet_source() -> None:
    """Regression guard: the gate must keep its teeth where a breakdown DOES exist."""
    inputs = _sparse_conversational_inputs()
    inputs["company"]["model_format"] = "spreadsheet"
    w = _suspect(validate(inputs))
    assert w is not None and w["critical"] is True


def test_expense_coverage_defaults_to_critical_when_format_unstated() -> None:
    """model_format defaults to `spreadsheet`, so an unstated format keeps the STOP."""
    inputs = _sparse_conversational_inputs()
    del inputs["company"]["model_format"]
    w = _suspect(validate(inputs))
    assert w is not None and w["critical"] is True


def test_expense_coverage_message_tells_the_model_not_to_fabricate() -> None:
    """The live failure was a synthesized opex line. Say so explicitly."""
    w = _suspect(validate(_sparse_conversational_inputs()))
    assert w is not None
    assert "do not invent" in w["message"].lower()


def test_expense_coverage_message_is_currency_neutral() -> None:
    """A hardcoded `$` in this message leaked a bare dollar sign into a non-USD review."""
    inputs = _sparse_conversational_inputs()
    inputs["currency"] = "ILS"
    w = _suspect(validate(inputs))
    assert w is not None
    assert "$" not in w["message"], f"bare $ in a non-USD message: {w['message']}"
    assert "ILS" in w["message"]


def test_expense_coverage_message_keeps_dollar_sign_for_usd() -> None:
    inputs = _sparse_conversational_inputs()
    inputs["currency"] = "USD"
    w = _suspect(validate(inputs))
    assert w is not None and "$" in w["message"]


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


# ---------------------------------------------------------------------------
# Null-coercion regression: the validator must REPORT bad input, not crash.
# ---------------------------------------------------------------------------


def test_null_headcount_count_reported_not_crashed() -> None:
    """A headcount entry with count: null must produce a TYPE_ERROR rather than
    raising a TypeError out of the Layer-3 sanity arithmetic."""
    inputs = _base_inputs(expenses={"headcount": [{"role": "eng", "count": None, "salary_annual": 150000}]})
    result = validate(inputs)
    codes = [e["code"] for e in result["errors"]]
    assert "TYPE_ERROR" in codes
    fields = [e["field"] for e in result["errors"] if e["code"] == "TYPE_ERROR"]
    assert any("headcount[0].count" in f for f in fields)


def test_null_headcount_salary_reported() -> None:
    """A headcount entry with salary_annual: null must produce a TYPE_ERROR."""
    inputs = _base_inputs(expenses={"headcount": [{"role": "eng", "count": 5, "salary_annual": None}]})
    result = validate(inputs)
    fields = [e["field"] for e in result["errors"] if e["code"] == "TYPE_ERROR"]
    assert any("headcount[0].salary_annual" in f for f in fields)


def test_metadata_null_does_not_crash() -> None:
    """validate() must guard metadata == null instead of raising AttributeError
    on inputs.get('metadata', {}).get(...)."""
    inputs = _base_inputs(metadata=None)
    result = validate(inputs)
    # Should return a structured result, not raise.
    assert "errors" in result
    assert "warnings" in result
