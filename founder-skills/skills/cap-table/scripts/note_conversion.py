#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Convertible note conversion math.

Implements `convertible_notes.accrued_interest`,
`convertible_notes.cap_discount_conversion`, and
`convertible_notes.qualified_financing_threshold` from `cap-table-rules.json`
(v0.2.8+). Binds rule pack inputs per design doc §5.2 binding table.

Branch contract (mutually exclusive per-note):
  * cap_conversion — priced-round + threshold met + valuation_cap non-null
  * discount_only — priced-round + threshold met + valuation_cap null
  * maturity_convert_at_cap — maturity branch with non-null cap (or override)
  * maturity_repay — maturity branch with maturity_default_treatment=repay
  * maturity_extend — maturity branch with =extend
  * maturity_counsel_review — maturity branch with =counsel_review
  * threshold_not_met — priced-round, threshold below qualified_financing_threshold
                        AND no non_qualified_financing_treatment override

Per Gotcha #5: maturity_conversion_price_override ONLY applies to convert_at_cap.
Per design doc §5.2: rule-pack-input names used verbatim (valuation_cap,
capitalization_denominator, qualified_financing_price) so binding is mechanical.

Usage as a library: see convert_note() at the bottom — the single entrypoint
that dispatches to the correct branch based on the note + scenario context.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

RULE_PACK_VERSION = "0.3.0"

E_NOTE_NO_CONVERSION_PATH = "E_NOTE_NO_CONVERSION_PATH"
E_NOTE_OVERRIDE_BRANCH_MISMATCH = "E_NOTE_OVERRIDE_BRANCH_MISMATCH"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


def compute_accrued_interest(
    *,
    principal: float,
    annual_interest_rate: float,
    days_elapsed: int,
    day_count_basis: int = 365,
    compounding_periods_per_year: int | None = None,
) -> float:
    """Per convertible_notes.accrued_interest rule.

    simple_interest = principal * rate * days / day_count_basis
    compound_balance = principal * (1 + rate / n) ^ (n * days / day_count_basis)
    """
    if compounding_periods_per_year and compounding_periods_per_year > 0:
        n = compounding_periods_per_year
        balance: float = principal * ((1 + annual_interest_rate / n) ** (n * days_elapsed / day_count_basis))
        return balance - principal
    result: float = principal * annual_interest_rate * days_elapsed / day_count_basis
    return result


def _days_elapsed(note: dict[str, Any], conversion_event_date: str) -> int:
    issuance = _parse_date(note["issuance_date"])
    last_event = _parse_date(note.get("last_interest_event_date")) or issuance
    target = _parse_date(conversion_event_date)
    if last_event is None or target is None:
        return 0
    return max(0, (target - last_event).days)


def _conversion_balance(note: dict[str, Any], accrued: float) -> float:
    """Principal + accrued (if interest converts) else principal only."""
    converts = note.get("interest_converts_to_shares", True)
    bal: float = note["principal"] + (accrued if converts else 0.0)
    return bal


def _classify_branch(
    note: dict[str, Any],
    *,
    priced_round_new_money: float | None,
    qualified_financing_price: float | None,
) -> str:
    """Decide which branch this note falls into based on inputs.

    Order matters: maturity_* branches take precedence when no priced-round
    inputs are supplied. Priced-round branches only fire when both new_money
    and the resolved qualified_financing_price are present.
    """
    cap = note.get("valuation_cap")
    denom = note.get("capitalization_denominator")
    discount = note.get("discount_multiplier")
    threshold = note.get("qualified_financing_threshold")
    nqft = note.get("non_qualified_financing_treatment")
    override = note.get("maturity_conversion_price_override")
    mdt = note.get("maturity_default_treatment", "convert_at_cap")

    # Priced-round path
    if priced_round_new_money is not None and qualified_financing_price is not None:
        if threshold is not None and priced_round_new_money < threshold:
            if nqft == "convert_anyway":
                # Threshold bypassed by counsel; fall through to cap/discount path
                pass
            elif nqft == "do_not_convert":
                return "maturity_extend"  # treats as extension past financing
            elif nqft == "negotiate":
                return "maturity_counsel_review"
            else:  # null
                return "threshold_not_met"

        # Threshold met or bypassed — pick cap_conversion vs discount_only
        if cap is not None and denom is not None and denom > 0:
            return "cap_conversion"
        if cap is None and discount is not None:
            return "discount_only"
        # Otherwise we'll be flagged as no-path below

    # Maturity path
    if mdt == "convert_at_cap":
        if override is not None:
            return "maturity_convert_at_cap"  # override branch (same label)
        if cap is not None and denom is not None and denom > 0:
            return "maturity_convert_at_cap"
        # cap missing + no override → error caller handles
        return "no_conversion_path"
    if mdt == "repay":
        if override is not None:
            return "override_mismatch"
        return "maturity_repay"
    if mdt == "extend":
        if override is not None:
            return "override_mismatch"
        return "maturity_extend"
    if mdt == "counsel_review":
        if override is not None:
            return "override_mismatch"
        return "maturity_counsel_review"
    return "no_conversion_path"


def convert_note(
    note: dict[str, Any],
    *,
    conversion_event_date: str,
    priced_round_new_money: float | None = None,
    qualified_financing_price: float | None = None,
) -> dict[str, Any]:
    """Single-note conversion. Returns per-note outputs matching the design's
    branch enum + per-note schema fields.
    """
    days = _days_elapsed(note, conversion_event_date)
    accrued = compute_accrued_interest(
        principal=note["principal"],
        annual_interest_rate=note["annual_interest_rate"],
        days_elapsed=days,
        day_count_basis=note.get("day_count_basis", 365),
        compounding_periods_per_year=note.get("compounding_periods_per_year"),
    )
    balance = _conversion_balance(note, accrued)

    branch = _classify_branch(
        note,
        priced_round_new_money=priced_round_new_money,
        qualified_financing_price=qualified_financing_price,
    )

    base: dict[str, Any] = {
        "note_id": note["id"],
        "branch": branch,
        "accrued_interest": accrued,
        "days_elapsed": days,
    }

    if branch == "no_conversion_path":
        base["error"] = E_NOTE_NO_CONVERSION_PATH
        base["reason"] = (
            "convert_at_cap requires non-null valuation_cap + capitalization_denominator "
            "OR maturity_conversion_price_override; neither provided"
        )
        return base

    if branch == "override_mismatch":
        base["error"] = E_NOTE_OVERRIDE_BRANCH_MISMATCH
        base["reason"] = (
            f"maturity_conversion_price_override is non-null but treatment is "
            f"'{note.get('maturity_default_treatment')}'; override only applies to convert_at_cap"
        )
        return base

    if branch == "threshold_not_met":
        return base  # structural-only

    if branch == "maturity_extend":
        return base

    if branch == "maturity_counsel_review":
        return base

    if branch == "maturity_repay":
        # On repayment, holder receives principal + accrued interest regardless
        # of `interest_converts_to_shares` (which only governs CONVERSION
        # behavior — at maturity payout, accrued interest is always owed).
        base["cash_repayment"] = note["principal"] + accrued
        base["math_provenance"] = [
            {
                "output_field": "cash_repayment",
                "source_type": "rule",
                "rule_id": "convertible_notes.accrued_interest",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        ]
        return base

    # Share-producing branches
    cap = note.get("valuation_cap")
    denom = note.get("capitalization_denominator")
    discount = note.get("discount_multiplier")
    override = note.get("maturity_conversion_price_override")
    candidate_prices: list[tuple[str, float]] = []
    provenance: list[dict[str, Any]] = []

    if branch == "maturity_convert_at_cap" and override is not None:
        # Override branch — bypass rule
        conversion_price = override
        base["conversion_price"] = conversion_price
        base["conversion_shares"] = balance / conversion_price
        base["math_provenance"] = [
            {
                "output_field": "conversion_price",
                "source_type": "counsel_supplied_override",
                "rule_id": None,
                "rule_pack_version": None,
                "source_ref": "notes[].maturity_conversion_price_override",
            },
            {
                "output_field": "conversion_shares",
                "source_type": "counsel_supplied_override",
                "rule_id": None,
                "rule_pack_version": None,
                "source_ref": "notes[].maturity_conversion_price_override",
            },
        ]
        return base

    if cap is not None and denom is not None and denom > 0:
        cap_price = cap / denom
        candidate_prices.append(("cap_price", cap_price))
        provenance.append(
            {
                "output_field": "cap_price",
                "source_type": "rule",
                "rule_id": "convertible_notes.cap_discount_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )

    if branch != "maturity_convert_at_cap" and discount is not None and qualified_financing_price is not None:
        discount_price = qualified_financing_price * discount
        candidate_prices.append(("discount_price", discount_price))
        provenance.append(
            {
                "output_field": "discount_price",
                "source_type": "rule",
                "rule_id": "convertible_notes.cap_discount_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )

    if not candidate_prices:
        base["branch"] = "no_conversion_path"
        base["error"] = E_NOTE_NO_CONVERSION_PATH
        base["reason"] = "no usable conversion price computed"
        return base

    _, conversion_price = min(candidate_prices, key=lambda kv: kv[1])
    base["candidates"] = dict(candidate_prices)
    base["conversion_price"] = conversion_price
    base["conversion_shares"] = balance / conversion_price
    provenance.append(
        {
            "output_field": "conversion_price",
            "source_type": "rule",
            "rule_id": "convertible_notes.cap_discount_conversion",
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )
    provenance.append(
        {
            "output_field": "conversion_shares",
            "source_type": "rule",
            "rule_id": "convertible_notes.cap_discount_conversion",
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )
    base["math_provenance"] = provenance
    return base


def derive_scenario_completeness(per_note: dict[str, dict[str, Any]]) -> str:
    """Per design rev14: derive scenario-level completeness from per-note branches.

    Returns one of: full | repay_only | structural_only | mixed.
    """
    share_set = {"cap_conversion", "discount_only", "maturity_convert_at_cap"}
    cash_set = {"maturity_repay"}
    struct_set = {"maturity_extend", "maturity_counsel_review", "threshold_not_met"}

    branches = {p["branch"] for p in per_note.values() if "branch" in p}
    # Errors are not in any set; they're hard rejects
    if any(b in {"no_conversion_path", "override_mismatch"} for b in branches):
        return "structural_only"  # caller should also surface the error

    if branches <= share_set:
        return "full"
    if branches <= cash_set:
        return "repay_only"
    if branches <= struct_set:
        return "structural_only"
    return "mixed"


def _cli() -> int:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--pretty", action="store_true")

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("convert-one", parents=[shared], help="Convert a single note (JSON on stdin)")
    one.add_argument("--conversion-date", required=True)
    one.add_argument("--priced-round-new-money", type=float, default=None)
    one.add_argument("--qualified-financing-price", type=float, default=None)

    accr = sub.add_parser("accrued", parents=[shared], help="Compute accrued interest only")
    accr.add_argument("--principal", type=float, required=True)
    accr.add_argument("--rate", type=float, required=True, help="annual rate, e.g. 0.06")
    accr.add_argument("--days", type=int, required=True)
    accr.add_argument("--basis", type=int, default=365)
    accr.add_argument("--compound-n", type=int, default=None)

    args = p.parse_args()

    if args.cmd == "convert-one":
        note = json.load(sys.stdin)
        result = convert_note(
            note,
            conversion_event_date=args.conversion_date,
            priced_round_new_money=args.priced_round_new_money,
            qualified_financing_price=args.qualified_financing_price,
        )
    else:
        accrued = compute_accrued_interest(
            principal=args.principal,
            annual_interest_rate=args.rate,
            days_elapsed=args.days,
            day_count_basis=args.basis,
            compounding_periods_per_year=args.compound_n,
        )
        result = {"accrued_interest": accrued}

    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
