"""Unit tests for invariant_checker.py — Sprint 4a."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"))

from invariant_checker import (  # noqa: E402
    check_bounds,
    check_instrument,
    check_math,
)


class TestSoftBounds:
    def test_typical_safe_passes(self):
        violations = check_bounds(
            "safe",
            {
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
            },
        )
        assert violations == []

    def test_purchase_amount_above_max_warns(self):
        violations = check_bounds("safe", {"purchase_amount": 100_000_000})
        assert len(violations) == 1
        assert violations[0].stake == "soft"
        assert violations[0].bound == "above_max"

    def test_discount_multiplier_below_min(self):
        # 0.30 is way below — discount of 70% is implausible
        violations = check_bounds("safe", {"discount_multiplier": 0.30})
        assert len(violations) == 1
        assert violations[0].field == "discount_multiplier"

    def test_unit_error_giant_cap(self):
        """$5B cap on a SAFE — likely $5M mis-extracted with units off by 3."""
        violations = check_bounds("safe", {"post_money_valuation_cap": 5_000_000_000})
        assert len(violations) == 1
        assert "unit error" in violations[0].reason

    def test_high_interest_rate_warns(self):
        violations = check_bounds("convertible_note", {"annual_interest_rate": 0.35})
        assert any(v.field == "annual_interest_rate" for v in violations)

    def test_null_value_ignored(self):
        violations = check_bounds("safe", {"purchase_amount": None})
        assert violations == []


class TestMathInvariants:
    def test_captable_options_exceed_authorized_hard_fail(self):
        violations = check_math(
            "captable",
            {
                "options_granted_count": 5_000_000,
                "total_authorized_shares": 1_000_000,
            },
        )
        assert len(violations) == 1
        assert violations[0].stake == "hard"
        assert "math impossible" in violations[0].reason

    def test_term_sheet_post_pre_inv_consistency(self):
        # pre=$10M + inv=$5M should equal post=$15M
        ok_violations = check_math(
            "term_sheet",
            {
                "pre_money_valuation": 10_000_000,
                "investment_amount": 5_000_000,
                "post_money_valuation": 15_000_000,
            },
        )
        assert ok_violations == []

    def test_term_sheet_math_mismatch_flags(self):
        # pre=$10M + inv=$5M should equal post=$15M, but post=$20M provided
        violations = check_math(
            "term_sheet",
            {
                "pre_money_valuation": 10_000_000,
                "investment_amount": 5_000_000,
                "post_money_valuation": 20_000_000,
            },
        )
        assert len(violations) == 1
        assert violations[0].stake == "hard"

    def test_term_sheet_2pct_tolerance(self):
        # Within 2% rounding tolerance — passes
        violations = check_math(
            "term_sheet",
            {
                "pre_money_valuation": 10_000_000,
                "investment_amount": 5_000_000,
                "post_money_valuation": 15_100_000,  # ~0.7% off
            },
        )
        assert violations == []

    def test_safe_both_caps_set_hard_fail(self):
        violations = check_math(
            "safe",
            {
                "pre_money_valuation_cap": 10_000_000,
                "post_money_valuation_cap": 12_000_000,  # both set — impossible
            },
        )
        assert len(violations) == 1
        assert violations[0].stake == "hard"


class TestCheckInstrument:
    def test_clean_safe_reports_no_violations(self):
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
            },
        }
        report = check_instrument(extraction)
        assert report.n_violations == 0
        assert report.n_hard_violations == 0

    def test_unit_error_flagged_soft(self):
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "purchase_amount": 500_000_000,  # $500M — unit error?
                "post_money_valuation_cap": 20_000_000,
            },
        }
        report = check_instrument(extraction)
        assert report.n_violations == 1
        assert report.n_hard_violations == 0  # soft

    def test_math_violation_flagged_hard(self):
        extraction = {
            "instrument_type": "safe",
            "fields": {
                "pre_money_valuation_cap": 10_000_000,
                "post_money_valuation_cap": 12_000_000,  # both set — math hard fail
                "purchase_amount": 500_000,
            },
        }
        report = check_instrument(extraction)
        assert report.n_hard_violations == 1
