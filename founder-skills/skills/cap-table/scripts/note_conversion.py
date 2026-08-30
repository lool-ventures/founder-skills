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
import os
import sys
from datetime import date
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _emit import add_output_args, emit  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402

E_NOTE_NO_CONVERSION_PATH = "E_NOTE_NO_CONVERSION_PATH"
E_NOTE_OVERRIDE_BRANCH_MISMATCH = "E_NOTE_OVERRIDE_BRANCH_MISMATCH"
E_NOTE_INVALID_PRICE_INPUT = "E_NOTE_INVALID_PRICE_INPUT"
E_NOTE_PRICED_ROUND_NO_CAP_OR_DISCOUNT = "E_NOTE_PRICED_ROUND_NO_CAP_OR_DISCOUNT"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


def note_has_usable_math_inputs(note: dict[str, Any]) -> bool:
    """True iff the note has the fields note-conversion math accesses unconditionally — a real,
    positive ``principal`` and an ``issuance_date`` — so its conversion can run without crashing.

    A partial/blank note (null principal — e.g. the amount lives in a Schedule of Lenders, not the
    blank Note template — or a missing issuance_date) is terms-only and non-convertible; callers
    exclude it from the coupled/note math (mirrors ``safe_has_usable_purchase_amount``).
    """
    principal = note.get("principal")
    if not (isinstance(principal, (int, float)) and not isinstance(principal, bool) and principal > 0):
        return False
    issuance = note.get("issuance_date")
    return isinstance(issuance, str) and bool(issuance.strip())


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
) -> tuple[str, bool]:
    """Decide which branch this note falls into based on inputs.

    Order matters: maturity_* branches take precedence when no priced-round
    inputs are supplied. Priced-round branches only fire when both new_money
    and the resolved qualified_financing_price are present.

    Returns (branch_name, maturity_default_treatment_was_absent) so the
    caller can emit a disclosure warning when the field was defaulted.
    """
    cap = note.get("valuation_cap")
    denom = note.get("capitalization_denominator")
    discount = note.get("discount_multiplier")
    threshold = note.get("qualified_financing_threshold")
    nqft = note.get("non_qualified_financing_treatment")
    override = note.get("maturity_conversion_price_override")
    # NOT SUPPLIED means absent OR an explicit null, and the two must behave identically. The schema
    # types this field `["string", "null"]` with null in its enum, and three surfaces deliberately
    # write that null: the lane-1 doc tells the extractor to set the field to null when the note does
    # not state a treatment, its enum lists null, and the Carta importer emits one.
    #
    # Read with `.get(key, default)` the null came through as the value, which did two things. The
    # branch flipped -- measured, an otherwise identical note went from `maturity_convert_at_cap` to
    # `no_conversion_path`, because a None matches none of the `mdt ==` arms below. And
    # `mdt_absent` was False, suppressing the one warning written to tell a founder this treatment
    # was ASSUMED rather than read from their document. So the input class that most needs the
    # disclosure was the class that silently lost it.
    mdt_supplied = note.get("maturity_default_treatment")
    mdt_absent = mdt_supplied is None
    mdt = mdt_supplied or "convert_at_cap"

    # A note evaluated with priced-round inputs but NEITHER a cap NOR a discount has no conversion
    # price for the round — a more specific diagnosis than the maturity-default no_conversion_path
    # fallthrough. The `or` (vs the strict both-present gate below) deliberately covers the boundary
    # where new_money is supplied but the round price hasn't resolved yet: the caller still meant a
    # priced round and the note still lacks both terms, so the attribution holds there too.
    priced_context = priced_round_new_money is not None or qualified_financing_price is not None

    # Priced-round path — mdt_absent is irrelevant here (maturity path not taken)
    if priced_round_new_money is not None and qualified_financing_price is not None:
        if threshold is not None and priced_round_new_money < threshold:
            if nqft == "convert_anyway":
                # Threshold bypassed by counsel; fall through to cap/discount path
                pass
            elif nqft == "do_not_convert":
                return "maturity_extend", False
            elif nqft == "negotiate":
                return "maturity_counsel_review", False
            else:  # null
                return "threshold_not_met", False

        # Threshold met or bypassed — pick cap_conversion vs discount_only
        if cap is not None and denom is not None and denom > 0:
            return "cap_conversion", False
        if cap is None and discount is not None:
            return "discount_only", False
        # Otherwise we'll be flagged as no-path below

    # Maturity path — mdt_absent is relevant when we enter this path
    if mdt == "convert_at_cap":
        if override is not None:
            return "maturity_convert_at_cap", mdt_absent
        if cap is not None and denom is not None and denom > 0:
            return "maturity_convert_at_cap", mdt_absent
        # cap missing + no override → error caller handles. Mid-priced-round with neither cap nor
        # discount is the more specific diagnosis (return False so no spurious maturity-default warning).
        if priced_context and cap is None and discount is None:
            return "priced_round_no_cap_or_discount", False
        return "no_conversion_path", mdt_absent
    if mdt == "repay":
        if override is not None:
            return "override_mismatch", mdt_absent
        return "maturity_repay", mdt_absent
    if mdt == "extend":
        if override is not None:
            return "override_mismatch", mdt_absent
        return "maturity_extend", mdt_absent
    if mdt == "counsel_review":
        if override is not None:
            return "override_mismatch", mdt_absent
        return "maturity_counsel_review", mdt_absent
    if priced_context and cap is None and discount is None:
        return "priced_round_no_cap_or_discount", False
    return "no_conversion_path", mdt_absent


# Default proxy rate for statutory ITA Section 3(j) when no
# counsel-supplied value is available. Historic range 2024-2025 ≈ 4.27-5.00%;
# 5% is a conservative upper bound. Counsel should always supply the current
# published ITA rate for binding math (the rate is republished quarterly).
# Real-doc end-to-end test (May 2026) surfaced that math producers can't run
# with annual_interest_rate=null even when interest_rate_type='none' (no interest)
# or 'statutory_ita_section_3j' (rate set by ITA, not the document).
STATUTORY_ITA_DEFAULT_RATE = 0.05


def convert_note(
    note: dict[str, Any],
    *,
    conversion_event_date: str,
    priced_round_new_money: float | None = None,
    qualified_financing_price: float | None = None,
) -> dict[str, Any]:
    """Single-note conversion. Returns per-note outputs matching the design's
    branch enum + per-note schema fields.

    Per the post-J audit (commit #5+) + real-doc calibration (May 2026):
    `annual_interest_rate` may legitimately be null when:
      - `interest_rate_type="none"` (SAFE-equivalent convertible_security
        subtype): treat as 0% (no interest accrues).
      - `interest_rate_type="statutory_ita_section_3j"` (Israeli CLAs
        referencing the ITA-set quarterly rate): use STATUTORY_ITA_DEFAULT_RATE
        (5%) as proxy and surface a warning so counsel supplies the actual
        published rate.
    """
    days = _days_elapsed(note, conversion_event_date)

    # Resolve interest rate when document defers to statute or has no interest.
    effective_rate = note.get("annual_interest_rate")
    interest_rate_type = note.get("interest_rate_type", "fixed_numeric")
    warnings: list[dict[str, Any]] = []
    if effective_rate is None:
        if interest_rate_type == "none":
            # SAFE-equivalent: no interest accrues.
            effective_rate = 0.0
        elif interest_rate_type == "statutory_ita_section_3j":
            effective_rate = STATUTORY_ITA_DEFAULT_RATE
            warnings.append(
                {
                    "code": "statutory_ita_3j_proxy_rate_used",
                    "severity": "high",
                    "message": (
                        f"This convertible note's interest_rate_type is "
                        f"statutory_ita_section_3j (rate set quarterly by the "
                        f"Israeli Tax Authority — not stated in the document). "
                        f"Math producer used proxy rate "
                        f"{STATUTORY_ITA_DEFAULT_RATE:.1%}/yr to compute accrued "
                        f"interest. Counsel must supply the actual published "
                        f"ITA §3(j) rate for the conversion window before "
                        f"relying on the conversion shares figure. Historic "
                        f"range 2024-2025 ≈ 4.27-5.0%."
                    ),
                }
            )
        else:
            # fixed_numeric / fixed_numeric_simple with null rate should have
            # been caught by the validator. Defensive: treat as 0 + warn.
            effective_rate = 0.0
            warnings.append(
                {
                    "code": "missing_numeric_interest_rate",
                    "severity": "high",
                    "message": (
                        f"interest_rate_type={interest_rate_type!r} requires a "
                        f"numeric annual_interest_rate but received null. "
                        f"Math producer used 0% — this is almost certainly "
                        f"wrong. Validator should have rejected this earlier."
                    ),
                }
            )

    accrued = compute_accrued_interest(
        principal=note["principal"],
        annual_interest_rate=effective_rate,
        days_elapsed=days,
        # coalesce an explicit-null day_count_basis (a blank note field) to the 365 default
        day_count_basis=note.get("day_count_basis") or 365,
        compounding_periods_per_year=note.get("compounding_periods_per_year"),
    )
    balance = _conversion_balance(note, accrued)

    branch, mdt_was_absent = _classify_branch(
        note,
        priced_round_new_money=priced_round_new_money,
        qualified_financing_price=qualified_financing_price,
    )

    # Disclosure warning when maturity_default_treatment was absent and the
    # maturity path was entered via the default ("convert_at_cap").  Standard
    # note forms (e.g. Fenwick seed-stage template) default to repayment on
    # majority-holder demand at maturity; the convert_at_cap default is an
    # unsourced convention.  Founders must confirm the actual note text.
    if mdt_was_absent:
        warnings.append(
            {
                "code": "maturity_default_treatment_defaulted",
                "severity": "medium",
                "message": (
                    "maturity_default_treatment was not specified in this note's "
                    "inputs; the math producer defaulted to 'convert_at_cap'. "
                    "Standard note forms (e.g. Fenwick seed-stage template) "
                    "commonly default to repayment on majority-holder demand at "
                    "maturity — the note text must be confirmed before relying on "
                    "the convert_at_cap path."
                ),
            }
        )

    base: dict[str, Any] = {
        "note_id": note["id"],
        "branch": branch,
        "accrued_interest": accrued,
        "days_elapsed": days,
    }
    if warnings:
        base["warnings"] = warnings

    if branch == "priced_round_no_cap_or_discount":
        base["error"] = E_NOTE_PRICED_ROUND_NO_CAP_OR_DISCOUNT
        base["reason"] = (
            "This note has neither a valuation_cap nor a discount_multiplier, so no conversion price "
            "exists for the priced round. Confirm the note's conversion mechanics (a cap and/or a "
            "discount, or a counsel-supplied conversion price) with the founder or the note text — "
            "do NOT assume a cap or discount."
        )
        return base

    if branch == "no_conversion_path":
        base["error"] = E_NOTE_NO_CONVERSION_PATH
        base["reason"] = (
            "convert_at_cap requires non-null valuation_cap + capitalization_denominator "
            "(the share count defined by the note's 'Company Capitalization' clause — "
            "ask the founder; commonly the pre-financing fully-diluted count) "
            "OR maturity_conversion_price_override; neither provided. "
            "Do NOT default to cap_state fully-diluted — the denominator definition "
            "is note-text-specific and must be confirmed with the founder or note text."
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
        if override <= 0:
            base["branch"] = "rejected"
            base["error"] = E_NOTE_INVALID_PRICE_INPUT
            base["reason"] = f"maturity_conversion_price_override must be > 0; got {override!r}"
            return base
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
        if discount <= 0:
            base["branch"] = "rejected"
            base["error"] = E_NOTE_INVALID_PRICE_INPUT
            base["reason"] = f"discount_multiplier must be > 0; got {discount!r}"
            return base
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
    if any(b in {"no_conversion_path", "override_mismatch", "priced_round_no_cap_or_discount"} for b in branches):
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
    add_output_args(shared)

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

    emit(result, args)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
