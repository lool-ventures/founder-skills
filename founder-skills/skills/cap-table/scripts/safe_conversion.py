#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""SAFE conversion math (YC post-money primer + Cooley/NVCA references).

Implements `safe.post_money_cap_conversion` and `safe.discount_rate_semantics`
from `cap-table-rules.json` (v0.2.8+). The `company_capitalization` denominator
is supplied by the caller (typically `cap_state.as_converted_totals.fully_diluted_shares`
per the §5.1 binding table) and MUST be the pre-financing snapshot.

Per Gotcha #3: `discount_multiplier = 0.80` means 20% discount (multiplier
form, not percent). Per Gotcha #1: never include new-money or post-financing
pool increases in `company_capitalization`.

Two output sets (per §5.1 cap-implied vs post-financing split):

  * Cap-implied set — works standalone with cap + company_capitalization
    only. Produces cap_implied_ownership, safe_price, cap-implied shares.
  * Post-financing set — requires a priced-round price (equity_financing_price)
    OR conversion_price_override. Produces conversion shares + ownership %.

Hard-rejected cases (see Gotcha #4):
  * yc_postmoney_discount with no priced round / override → caller's job
    (E_SAFE_REQUIRES_CONVERSION_EVENT).
  * yc_uncapped_mfn with no priced round / override / MFN trigger → same.

Usage as a library:
    from safe_conversion import convert_safe_cap_implied, convert_safe_priced_round
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Rule pack version this script targets. Bumped when math semantics change.
RULE_PACK_VERSION = "0.3.1"

# Typed error codes (mirror design doc §5.1)
E_SAFE_REQUIRES_CONVERSION_EVENT = "E_SAFE_REQUIRES_CONVERSION_EVENT"
E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR"
E_SAFE_CIRCULAR_MFN = "E_SAFE_CIRCULAR_MFN"


def convert_safe_cap_implied(
    *,
    purchase_amount: float,
    post_money_valuation_cap: float | None,
    company_capitalization: int | float,
) -> dict[str, Any]:
    """Cap-implied output set (standalone; no priced round needed).

    Returns:
        cap_implied_ownership: purchase_amount / cap
        safe_price: cap / company_capitalization
        cap_implied_shares: purchase_amount / safe_price

    Math provenance: safe.post_money_cap_conversion (cap-only path).
    """
    if post_money_valuation_cap is None or post_money_valuation_cap <= 0:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": "cap-implied path requires a non-null post_money_valuation_cap",
        }
    if company_capitalization is None or company_capitalization <= 0:
        return {
            "branch": "rejected",
            "error": E_SAFE_CAP_MISSING_DENOMINATOR,
            "reason": "company_capitalization must be > 0 (pre-financing FD share count)",
        }

    cap_implied_ownership = purchase_amount / post_money_valuation_cap
    safe_price = post_money_valuation_cap / company_capitalization
    cap_implied_shares = purchase_amount / safe_price

    return {
        "branch": "cap_implied",
        "cap_implied_ownership": cap_implied_ownership,
        "safe_price": safe_price,
        "cap_implied_shares": cap_implied_shares,
        "math_provenance": [
            {
                "output_field": "safe_price",
                "source_type": "rule",
                "rule_id": "safe.post_money_cap_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            },
            {
                "output_field": "cap_implied_ownership",
                "source_type": "rule",
                "rule_id": "safe.post_money_cap_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            },
            {
                "output_field": "cap_implied_shares",
                "source_type": "rule",
                "rule_id": "safe.post_money_cap_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            },
        ],
    }


# Form classification for denominator routing.
# Post-money forms: each SAFE locks `purchase / cap` of POST-money FD. The
# operational denominator passed via `company_capitalization` is the converged
# post-money FD (including new money). See rule `safe.post_money_cap_conversion`
# v0.3.0 clarification.
POST_MONEY_FORMS: set[str] = {
    "yc_postmoney_cap",
    "yc_postmoney_discount",
    "yc_uncapped_mfn",
    "cap_plus_discount",
}
# Pre-money (legacy, pre-Oct-2018) forms: cap_price = cap / pre_money_FD where
# pre_money_FD is the PRE-FINANCING fully-diluted snapshot (constant, NOT the
# iterating post-money FD). These SAFEs dilute alongside founders when new money
# and pool refresh land — they do NOT have the locked-% property of post-money.
PRE_MONEY_FORMS: set[str] = {
    "yc_premoney_cap_only",
    "pre_money_cap_and_discount_legacy",
}


def convert_safe_priced_round(
    *,
    purchase_amount: float,
    form: str,
    post_money_valuation_cap: float | None,
    discount_multiplier: float | None,
    company_capitalization: int | float,
    equity_financing_price: float | None,
    conversion_price_override: float | None = None,
    pre_money_valuation_cap: float | None = None,
    pre_money_fd: float | None = None,
) -> dict[str, Any]:
    """Post-financing output set (requires a real conversion event).

    Branches:
        * conversion_price_override → branch = "conversion_price_override"
        * yc_postmoney_cap → cap branch (post-money denominator)
        * cap_plus_discount → min(cap_price, discount_price)
        * yc_postmoney_discount → discount branch only
        * yc_uncapped_mfn → REJECTED (caller must resolve MFN trigger first)
        * yc_premoney_cap_only → cap branch (pre-money denominator)
        * pre_money_cap_and_discount_legacy → min(cap_price[pre-money], discount_price)

    Denominator routing: post-money forms use `company_capitalization`
    (= converged post-money FD); pre-money forms use `pre_money_fd`
    (= pre-financing FD constant). See `POST_MONEY_FORMS` / `PRE_MONEY_FORMS`.

    Caller is responsible for resolving MFN cherry-pick BEFORE calling this
    function (yc_uncapped_mfn with a trigger should be re-presented as if
    it were the triggering SAFE's form).
    """
    # Override branch — counsel-supplied price; bypass rule
    if conversion_price_override is not None:
        if conversion_price_override <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
                "reason": "conversion_price_override must be > 0",
            }
        conversion_price = conversion_price_override
        shares = purchase_amount / conversion_price
        return {
            "branch": "conversion_price_override",
            "conversion_price": conversion_price,
            "conversion_shares": shares,
            "math_provenance": [
                {
                    "output_field": "conversion_price",
                    "source_type": "counsel_supplied_override",
                    "rule_id": None,
                    "rule_pack_version": None,
                    "source_ref": "safes[].conversion_price_override",
                },
                {
                    "output_field": "conversion_shares",
                    "source_type": "counsel_supplied_override",
                    "rule_id": None,
                    "rule_pack_version": None,
                    "source_ref": "safes[].conversion_price_override",
                },
            ],
        }

    # yc_uncapped_mfn without override needs MFN trigger resolution upstream
    if form == "yc_uncapped_mfn" and post_money_valuation_cap is None and discount_multiplier is None:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": (
                "yc_uncapped_mfn requires MFN trigger resolution upstream OR "
                "conversion_price_override; caller did not provide either"
            ),
        }

    # Forms requiring a priced-round price
    needs_price = form in {"yc_postmoney_discount", "yc_uncapped_mfn"} or (
        form == "cap_plus_discount" and discount_multiplier is not None
    )
    if needs_price and equity_financing_price is None:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": (
                f"{form} requires equity_financing_price (priced round) or conversion_price_override; neither provided"
            ),
        }

    candidate_prices: list[tuple[str, float]] = []

    # Cap candidate — route denominator on form.
    # Post-money forms use the iterating post-money FD as denominator
    # (`company_capitalization`); pre-money forms use the constant pre-financing
    # FD (`pre_money_fd`). This is the load-bearing distinction between the two
    # SAFE families.
    cap_value: float | None = None
    cap_denom: float | None = None
    cap_provenance_rule_id: str = "safe.post_money_cap_conversion"

    if form in POST_MONEY_FORMS and post_money_valuation_cap is not None and post_money_valuation_cap > 0:
        cap_value = post_money_valuation_cap
        cap_denom = company_capitalization
        cap_provenance_rule_id = "safe.post_money_cap_conversion"
    elif form in PRE_MONEY_FORMS and pre_money_valuation_cap is not None and pre_money_valuation_cap > 0:
        cap_value = pre_money_valuation_cap
        cap_denom = pre_money_fd
        # Pre-money SAFE math is the LEGACY YC SAFE conversion (pre-Oct-2018).
        # The rule pack rule `safe.pre_money_cap_conversion` (added in v0.3.0)
        # documents this branch.
        cap_provenance_rule_id = "safe.pre_money_cap_conversion"

    if cap_value is not None:
        if cap_denom is None or cap_denom <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_CAP_MISSING_DENOMINATOR,
                "reason": (
                    f"cap branch requires non-zero denominator "
                    f"({'pre_money_fd' if form in PRE_MONEY_FORMS else 'company_capitalization'}); "
                    f"got {cap_denom!r}"
                ),
            }
        cap_price = cap_value / cap_denom
        candidate_prices.append(("cap_price", cap_price))

    # Discount candidate (rule: safe.discount_rate_semantics)
    if discount_multiplier is not None and equity_financing_price is not None:
        discount_price = equity_financing_price * discount_multiplier
        candidate_prices.append(("discount_price", discount_price))

    if not candidate_prices:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": f"no usable conversion price for form={form}",
        }

    # min(valid_price_candidates) wins (lower price → more shares for SAFE holder)
    winning_label, conversion_price = min(candidate_prices, key=lambda kv: kv[1])
    shares = purchase_amount / conversion_price

    branch = "cap_branch" if winning_label == "cap_price" else "discount_branch"
    if len(candidate_prices) == 2:
        branch = "cap_and_discount_branch"

    provenance = []
    if any(label == "cap_price" for label, _ in candidate_prices):
        provenance.append(
            {
                "output_field": "cap_price",
                "source_type": "rule",
                "rule_id": cap_provenance_rule_id,
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )
    if any(label == "discount_price" for label, _ in candidate_prices):
        provenance.append(
            {
                "output_field": "discount_price",
                "source_type": "rule",
                "rule_id": "safe.discount_rate_semantics",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )
    provenance.append(
        {
            "output_field": "conversion_price",
            "source_type": "rule",
            "rule_id": cap_provenance_rule_id,
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )
    provenance.append(
        {
            "output_field": "conversion_shares",
            "source_type": "rule",
            "rule_id": cap_provenance_rule_id,
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )

    return {
        "branch": branch,
        "candidates": dict(candidate_prices),
        "conversion_price": conversion_price,
        "conversion_shares": shares,
        "math_provenance": provenance,
    }


def detect_mfn_cycles(safes: list[dict[str, Any]]) -> list[set[str]]:
    """Detect circular MFN-election chains.

    Returns a list of cycles (each cycle is a set of safe IDs). Empty list
    means no cycles. Per Gotcha #4: yc_uncapped_mfn A → B → ... → A with no
    anchor SAFE in the cycle is unresolvable.
    """
    # Build directed graph: A → B iff A.mfn.elected_against_safe_id == B
    graph: dict[str, str | None] = {}
    forms: dict[str, str] = {}
    for s in safes:
        sid = s["id"]
        forms[sid] = s.get("form", "other")
        mfn = s.get("mfn_provision") or {}
        elected = mfn.get("elected_against_safe_id")
        graph[sid] = elected

    cycles = []
    visited = set()
    for sid in list(graph.keys()):
        if sid in visited:
            continue
        path: list[str] = []
        current: str | None = sid
        seen_in_walk: dict[str, int] = {}
        while current is not None and current not in visited:
            if current in seen_in_walk:
                # Found a cycle starting at seen_in_walk[current]
                cycle_start = seen_in_walk[current]
                cycle = set(path[cycle_start:])
                # Only flag as unresolvable if EVERY SAFE in the cycle is
                # yc_uncapped_mfn (no anchor with intrinsic price)
                if all(forms.get(c) == "yc_uncapped_mfn" for c in cycle):
                    cycles.append(cycle)
                break
            seen_in_walk[current] = len(path)
            path.append(current)
            current = graph.get(current)
        visited.update(path)
    return cycles


# ---------------------------------------------------------------------------
# CLI entrypoint (for ad-hoc testing; production callers use the library API)
# ---------------------------------------------------------------------------


def _cli() -> int:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--pretty", action="store_true")

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("cap-implied", parents=[shared], help="Cap-implied output (standalone)")
    cap.add_argument("--purchase", type=float, required=True)
    cap.add_argument("--cap", type=float, required=True)
    cap.add_argument("--company-cap", type=float, required=True)

    pr = sub.add_parser("priced-round", parents=[shared], help="Post-financing output")
    pr.add_argument("--purchase", type=float, required=True)
    pr.add_argument(
        "--form",
        required=True,
        choices=["yc_postmoney_cap", "yc_postmoney_discount", "yc_uncapped_mfn", "cap_plus_discount", "other"],
    )
    pr.add_argument("--cap", type=float, default=None)
    pr.add_argument("--discount", type=float, default=None, help="Multiplier form: 0.80 = 20%% discount")
    pr.add_argument("--company-cap", type=float, required=True)
    pr.add_argument("--equity-price", type=float, default=None)
    pr.add_argument("--override", type=float, default=None, help="Conversion price override (counsel-supplied)")

    cycles = sub.add_parser("detect-mfn-cycles", parents=[shared], help="Detect circular MFN chains")
    cycles.add_argument("--instruments", required=True)

    args = p.parse_args()

    if args.cmd == "cap-implied":
        result = convert_safe_cap_implied(
            purchase_amount=args.purchase,
            post_money_valuation_cap=args.cap,
            company_capitalization=args.company_cap,
        )
    elif args.cmd == "priced-round":
        result = convert_safe_priced_round(
            purchase_amount=args.purchase,
            form=args.form,
            post_money_valuation_cap=args.cap,
            discount_multiplier=args.discount,
            company_capitalization=args.company_cap,
            equity_financing_price=args.equity_price,
            conversion_price_override=args.override,
        )
    else:  # detect-mfn-cycles
        with open(args.instruments, encoding="utf-8") as f:
            inst = json.load(f)
        cycle_list = detect_mfn_cycles(inst.get("safes", []))
        result = {
            "cycles": [sorted(c) for c in cycle_list],
            "error": E_SAFE_CIRCULAR_MFN if cycle_list else None,
        }

    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
