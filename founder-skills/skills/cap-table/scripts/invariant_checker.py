#!/usr/bin/env python3
"""Real-world-bounds invariant checker for cap-table Lane-1 extraction.

Forward verification (`evidence_verifier`) catches HALLUCINATIONS:
value-not-in-source. Backward verification (`backward_verifier`) catches
SEMANTIC CONFUSION: right value, wrong field. Invariant checking (this
script) catches a third failure class:

  IMPLAUSIBLE VALUES — values that pass both forward and backward
  verification (they ARE in the source) but violate real-world bounds:
  e.g., a SAFE purchase_amount of $5 billion, a discount_multiplier of
  10.0, an annual_interest_rate of 75%, an options_granted_count
  exceeding total_authorized_shares.

These are usually unit / format errors (e.g., $500,000 mis-extracted as
500,000,000 by dropping a decimal point or confusing thousands with
millions) or rare structural confusions the other verifiers can't catch.

Two modes:
  --mode=warn   Emit warnings for any invariant violation (default)
  --mode=block  Exit 1 on hard-fail invariants (clear data errors)

Hard-fail (block-mode candidates):
  - Math invariants: options_granted ≤ total_authorized
  - Form-required-field violations (already enforced by validate_safe)

Soft-fail (always warn, never block):
  - Range bounds (purchase_amount < $100M etc.) — real outliers exist
    (large secondary SAFEs, mega-rounds). Flag for human review.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

# Per-field real-world bounds. These are SOFT — outliers exist, so violation
# triggers a warning, not a block. Tuned against the 69-doc eval set.
#
# Format: (field_name, (min, max), instrument_type, stake)
#   stake = "hard" → flag in block-mode; "soft" → warn-only
SOFT_BOUNDS: dict[str, dict[str, dict[str, Any]]] = {
    "safe": {
        # Cap range: $1M (very early angel) to $1B (mega-secondary). >$1B = flag.
        "post_money_valuation_cap": {"min": 100_000, "max": 1_000_000_000},
        "pre_money_valuation_cap": {"min": 100_000, "max": 1_000_000_000},
        # SAFE purchase: $1K (friends/family) to $50M (mega-SAFE). >$50M = flag.
        "purchase_amount": {"min": 1_000, "max": 50_000_000},
        # Discount multiplier MUST be in (0, 1]. The extract_instrument
        # normalize_discount step handles percent-form, so by this point it
        # should be a multiplier.
        "discount_multiplier": {"min": 0.50, "max": 1.0},
    },
    "convertible_note": {
        "principal": {"min": 1_000, "max": 100_000_000},
        "valuation_cap": {"min": 100_000, "max": 2_000_000_000},
        # Interest rate: 0% (SAFE-equivalent) to 20% (steep but seen on bridge
        # notes). >20% is loan-shark territory; statutory_ita_section_3j has
        # value=null and is excluded.
        "annual_interest_rate": {"min": 0.0, "max": 0.20},
        "discount_multiplier": {"min": 0.50, "max": 1.0},
        "qualified_financing_threshold": {"min": 100_000, "max": 100_000_000},
        # Maturity 6 months to 7 years. Most CLAs are 18-36 months.
        "maturity_months": {"min": 6, "max": 84},
        "day_count_basis": {"min": 360, "max": 365},  # 360 (banker's) or 365
    },
    "term_sheet": {
        "pre_money_valuation": {"min": 100_000, "max": 50_000_000_000},
        "post_money_valuation": {"min": 100_000, "max": 50_000_000_000},
        "investment_amount": {"min": 10_000, "max": 5_000_000_000},
        "discount_multiplier": {"min": 0.50, "max": 1.0},
        # Liquidation pref multiple: 1x to 3x is normal; >3x is highly unusual
        "liq_pref_multiple": {"min": 0.5, "max": 5.0},
        # Option pool 0% (uncommon) to 30% (large reserve at Series A)
        "option_pool_pct_postfinancing": {"min": 0.0, "max": 0.40},
        # Exclusivity: 7 days (rushed) to 90 days (extreme). Most are 30-60.
        "exclusivity_days": {"min": 0, "max": 90},
    },
}

# Cross-field math invariants. Violations are HARD — these can't be true
# simultaneously by construction. Block-mode rejects.
HARD_INVARIANTS = {
    "captable_math": [
        # options_granted_count must not exceed total_authorized_shares
        ("options_granted_count", "<=", "total_authorized_shares"),
        # total_issued_shares must not exceed total_authorized_shares
        ("total_issued_shares", "<=", "total_authorized_shares"),
    ],
    "term_sheet_math": [
        # pre_money + investment_amount ≈ post_money (within 2% tolerance)
        # encoded specially below since it's an equality not an inequality
    ],
}

# Form-conditional invariants per SKILL.md §5.1, already enforced by
# validate_safe — but checking again here surfaces them as warnings in
# extractions that bypass validate_safe (e.g. eval label scoring).
FORM_CONDITIONAL_HINT = "form-dependent gates enforced by extract_instrument.validate_safe; see SAFE_FORM_GATES"


@dataclass
class InvariantViolation:
    field: str
    value: Any
    bound: str  # "below_min" | "above_max" | "math_invariant"
    expected: str
    stake: str  # "hard" | "soft"
    reason: str = ""


@dataclass
class InvariantReport:
    instrument_type: str
    n_checks: int
    n_violations: int
    n_hard_violations: int
    violations: list[InvariantViolation] = field(default_factory=list)


def check_bounds(instrument_type: str, fields: dict[str, Any]) -> list[InvariantViolation]:
    """Per-field range checks. All soft-stake — warn but don't block."""
    out = []
    bounds = SOFT_BOUNDS.get(instrument_type, {})
    for fname, b in bounds.items():
        v = fields.get(fname)
        if v is None or isinstance(v, (dict, list, bool)):
            continue
        try:
            v_num = float(v)
        except (TypeError, ValueError):
            continue
        mn, mx = b["min"], b["max"]
        if v_num < mn:
            out.append(
                InvariantViolation(
                    field=fname,
                    value=v,
                    bound="below_min",
                    expected=f">= {mn}",
                    stake="soft",
                    reason=f"{fname}={v!r} is below typical range minimum {mn} for {instrument_type}",
                )
            )
        elif v_num > mx:
            out.append(
                InvariantViolation(
                    field=fname,
                    value=v,
                    bound="above_max",
                    expected=f"<= {mx}",
                    stake="soft",
                    reason=(
                        f"{fname}={v!r} is above typical range maximum {mx} "
                        f"for {instrument_type} — possible unit error (e.g. $ vs $K vs $M)"
                    ),
                )
            )
    return out


def check_math(instrument_type: str, fields: dict[str, Any]) -> list[InvariantViolation]:
    """Cross-field math invariants. Hard-stake — block-mode rejects."""
    out = []
    # Cap-table math
    options = fields.get("options_granted_count")
    issued = fields.get("total_issued_shares")
    authorized = fields.get("total_authorized_shares")

    if (
        options is not None
        and authorized is not None
        and isinstance(options, (int, float))
        and isinstance(authorized, (int, float))
        and options > authorized
    ):
        out.append(
            InvariantViolation(
                field="options_granted_count",
                value=options,
                bound="math_invariant",
                expected=f"<= total_authorized_shares ({authorized})",
                stake="hard",
                reason=(
                    f"options_granted_count={options} exceeds total_authorized_shares={authorized} — math impossible"
                ),
            )
        )
    if (
        issued is not None
        and authorized is not None
        and isinstance(issued, (int, float))
        and isinstance(authorized, (int, float))
        and issued > authorized
    ):
        out.append(
            InvariantViolation(
                field="total_issued_shares",
                value=issued,
                bound="math_invariant",
                expected=f"<= total_authorized_shares ({authorized})",
                stake="hard",
                reason=(f"total_issued_shares={issued} exceeds total_authorized_shares={authorized} — math impossible"),
            )
        )

    # Term sheet: pre + investment ≈ post (within 2% tolerance)
    if instrument_type == "term_sheet":
        pre = fields.get("pre_money_valuation")
        inv = fields.get("investment_amount")
        post = fields.get("post_money_valuation")
        if (
            isinstance(pre, (int, float))
            and isinstance(inv, (int, float))
            and isinstance(post, (int, float))
            and not isinstance(pre, bool)
        ):
            expected_post = pre + inv
            tolerance = 0.02 * max(expected_post, post)
            if abs(post - expected_post) > tolerance:
                out.append(
                    InvariantViolation(
                        field="post_money_valuation",
                        value=post,
                        bound="math_invariant",
                        expected=f"~= pre_money + investment_amount ({expected_post:,.0f})",
                        stake="hard",
                        reason=f"post_money_valuation={post} does not equal pre_money + investment within 2% tolerance",
                    )
                )

    # SAFE form-dependent: pre_money_cap and post_money_cap mutually exclusive
    if instrument_type == "safe":
        pre = fields.get("pre_money_valuation_cap")
        post = fields.get("post_money_valuation_cap")
        if pre is not None and post is not None:
            out.append(
                InvariantViolation(
                    field="post_money_valuation_cap",
                    value=post,
                    bound="math_invariant",
                    expected="either pre_money_valuation_cap OR post_money_valuation_cap is null (got both)",
                    stake="hard",
                    reason="SAFE form requires exactly one of pre_money / post_money cap; both populated",
                )
            )

    return out


def check_instrument(extraction: dict[str, Any]) -> InvariantReport:
    """Run all bounds + math invariants for one extracted instrument."""
    instrument_type = extraction.get("instrument_type", "")
    fields = extraction.get("fields") or {}
    bounds_violations = check_bounds(instrument_type, fields)
    math_violations = check_math(instrument_type, fields)
    all_v = bounds_violations + math_violations
    return InvariantReport(
        instrument_type=instrument_type,
        n_checks=len(SOFT_BOUNDS.get(instrument_type, {})) + 3,  # ~3 math checks
        n_violations=len(all_v),
        n_hard_violations=sum(1 for v in all_v if v.stake == "hard"),
        violations=all_v,
    )


def report_to_dict(report: InvariantReport) -> dict[str, Any]:
    return {
        "instrument_type": report.instrument_type,
        "n_checks": report.n_checks,
        "n_violations": report.n_violations,
        "n_hard_violations": report.n_hard_violations,
        "violations": [
            {
                "field": v.field,
                "value": v.value,
                "bound": v.bound,
                "expected": v.expected,
                "stake": v.stake,
                "reason": v.reason,
            }
            for v in report.violations
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", required=True)
    parser.add_argument(
        "--mode",
        choices=("warn", "block"),
        default="warn",
        help="warn (default): always exit 0, surface violations in receipt. "
        "block: exit 1 on hard-stake violations (math impossibilities).",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()

    with open(args.extraction) as f:
        extraction = json.loads(f.read())
    report = check_instrument(extraction)
    out = report_to_dict(report)

    payload = json.dumps(out, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w") as f:
            f.write(payload)
    else:
        print(payload)

    if args.mode == "block" and report.n_hard_violations > 0:
        sys.stderr.write(
            f"invariant_checker.py: {report.n_hard_violations} hard invariant violation(s); rejecting in block-mode\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
