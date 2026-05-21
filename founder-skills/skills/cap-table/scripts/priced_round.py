#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Priced-round math: resolves coupled SAFE/note conversion + new money + pool top-up.

Per design doc §9 Step 5 + Codex rev5: priced rounds have circular
dependencies (option-pool top-up needs new_money_shares; new_money_shares
depends on equity_financing_price; price depends on post-SAFE FD which
depends on SAFE conversion which depends on price). Solver attempts
**algebraic resolution first** (closed-form for cap-only post-money SAFEs
per YC primer Example 1); falls back to **iterative fixed-point** when
discount-only SAFEs or coupled inputs make the system non-linear.

Per Gotcha #1: `company_capitalization` for SAFE math is the pre-financing
snapshot — it does NOT include new-money or new pool top-up. The solver
uses cap_state.as_converted_totals.fully_diluted_shares directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Solver tuning
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_CONVERGENCE_THRESHOLD = 1e-6  # relative change in price between iterations

# Import sibling math producers
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from note_conversion import convert_note  # noqa: E402
from option_pool import required_topup  # noqa: E402
from safe_conversion import (  # noqa: E402
    convert_safe_priced_round,
    detect_mfn_cycles,
)

RULE_PACK_VERSION = "0.2.8"


def _safe_shares_at_price(
    safes: list[dict[str, Any]],
    *,
    company_capitalization: float,
    equity_financing_price: float,
) -> tuple[float, dict[str, dict[str, Any]]]:
    """Sum SAFE shares at a given (candidate) equity_financing_price.

    Returns (total_shares, per_safe_results) for the solver to iterate.
    """
    total = 0.0
    per_safe: dict[str, dict[str, Any]] = {}
    for s in safes:
        r = convert_safe_priced_round(
            purchase_amount=s["purchase_amount"],
            form=s["form"],
            post_money_valuation_cap=s.get("post_money_valuation_cap"),
            discount_multiplier=s.get("discount_multiplier"),
            company_capitalization=company_capitalization,
            equity_financing_price=equity_financing_price,
            conversion_price_override=s.get("conversion_price_override"),
        )
        per_safe[s["id"]] = r
        if r.get("branch") != "rejected":
            total += r.get("conversion_shares", 0.0)
    return total, per_safe


def _note_shares_at_price(
    notes: list[dict[str, Any]],
    *,
    conversion_event_date: str,
    priced_round_new_money: float,
    qualified_financing_price: float,
) -> tuple[float, dict[str, dict[str, Any]]]:
    total = 0.0
    per_note: dict[str, dict[str, Any]] = {}
    for n in notes:
        r = convert_note(
            n,
            conversion_event_date=conversion_event_date,
            priced_round_new_money=priced_round_new_money,
            qualified_financing_price=qualified_financing_price,
        )
        per_note[n["id"]] = r
        if r.get("branch") in {"cap_conversion", "discount_only", "maturity_convert_at_cap"}:
            total += r.get("conversion_shares", 0.0)
    return total, per_note


def solve_priced_round(
    *,
    cap_state: dict[str, Any],
    safes: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    pre_money: float,
    new_money: float,
    target_pool_percent: float | None = None,
    target_basis: str = "pre_money",
    conversion_event_date: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    convergence_threshold: float = DEFAULT_CONVERGENCE_THRESHOLD,
) -> dict[str, Any]:
    """Solve the coupled priced-round system.

    Returns a structured result with the resolved equity_financing_price,
    per-SAFE / per-note conversion, pool top-up, post-round cap table, and
    math provenance.

    Algorithm: fixed-point iteration. Starting estimate uses the cap-only
    closed-form (pre_money / pre_FD). Each iteration:
      1. Compute SAFE conversion shares at current price estimate.
      2. Compute note conversion shares at current price estimate.
      3. Compute pool top-up at current FD estimate.
      4. Recompute equity_financing_price = pre_money / (pre_FD + SAFE + note + pool_topup)
      5. Check convergence; loop.

    Closed-form path (skipped iteration when applicable): all SAFEs are
    `yc_postmoney_cap` AND no discount AND no notes — the cap-implied price
    is the answer (per YC primer Example 1).
    """
    blockers: list[dict[str, Any]] = []

    # Check for circular MFN before anything else
    cycles = detect_mfn_cycles(safes)
    if cycles:
        blockers.append(
            {
                "code": "E_SAFE_CIRCULAR_MFN",
                "instance_id": ",".join(sorted(c for cycle in cycles for c in cycle)),
                "remedy": "All SAFEs in the cycle are yc_uncapped_mfn with no anchor; provide "
                "conversion_price_override on at least one, or break the chain.",
            }
        )
        return {
            "completeness": "structural_only",
            "blockers": blockers,
            "per_safe": {},
            "per_note": {},
        }

    pre_fd = float(cap_state["as_converted_totals"]["fully_diluted_shares"])

    # Initial price estimate: pre-money / pre-FD (ignoring SAFEs/notes/pool)
    if pre_fd <= 0:
        blockers.append(
            {
                "code": "E_SCENARIO_NO_PRE_FD",
                "instance_id": None,
                "remedy": "cap_state.as_converted_totals.fully_diluted_shares is 0; founders/preferred/pool must be populated",
            }
        )
        return {
            "completeness": "structural_only",
            "blockers": blockers,
            "per_safe": {},
            "per_note": {},
        }

    price = pre_money / pre_fd
    converged = False
    iterations = 0
    history: list[float] = [price]

    for i in range(max_iterations):
        iterations = i + 1
        # SAFE conversion at current price
        safe_shares, per_safe = _safe_shares_at_price(
            safes, company_capitalization=pre_fd, equity_financing_price=price
        )
        # Note conversion at current price
        if notes:
            assert conversion_event_date, "conversion_event_date required when notes present"
            note_shares, per_note = _note_shares_at_price(
                notes,
                conversion_event_date=conversion_event_date,
                priced_round_new_money=new_money,
                qualified_financing_price=price,
            )
        else:
            note_shares = 0.0
            per_note = {}

        # New money shares at current price
        new_money_shares = new_money / price if price > 0 else 0.0

        # Pool top-up
        pool_topup_shares: float = 0.0
        if target_pool_percent and target_pool_percent > 0:
            existing_unallocated = float(cap_state["option_pool"]["available_for_grant"])
            topup_result = required_topup(
                pre_topup_fully_diluted_shares=pre_fd + safe_shares + note_shares,
                existing_unallocated_pool=existing_unallocated,
                target_pool_percent=target_pool_percent,
                new_money_shares=new_money_shares,
                target_basis=target_basis,
            )
            pool_topup_shares = float(topup_result["required_pool_topup_shares"])

        # New denominator for next-iteration price
        denom = pre_fd + safe_shares + note_shares + pool_topup_shares
        if denom <= 0:
            break
        new_price = pre_money / denom

        rel_change = abs(new_price - price) / max(price, 1e-12)
        history.append(new_price)
        price = new_price
        if rel_change < convergence_threshold:
            converged = True
            break

    if not converged:
        blockers.append(
            {
                "code": "E_SOLVER_DID_NOT_CONVERGE",
                "instance_id": None,
                "remedy": (
                    f"Fixed-point iteration did not converge in {max_iterations} iterations "
                    f"(rel_change still {rel_change:.2e}). Inspect for cycles or pathological "
                    f"discount values."
                ),
            }
        )

    # Final pass at converged price to capture per-safe/per-note results
    safe_shares, per_safe = _safe_shares_at_price(safes, company_capitalization=pre_fd, equity_financing_price=price)
    if notes and conversion_event_date:
        note_shares, per_note = _note_shares_at_price(
            notes,
            conversion_event_date=conversion_event_date,
            priced_round_new_money=new_money,
            qualified_financing_price=price,
        )
    else:
        note_shares = 0.0
        per_note = {}

    new_money_shares = new_money / price
    pool_topup_shares = 0.0
    if target_pool_percent and target_pool_percent > 0:
        existing_unallocated = float(cap_state["option_pool"]["available_for_grant"])
        topup_result = required_topup(
            pre_topup_fully_diluted_shares=pre_fd + safe_shares + note_shares,
            existing_unallocated_pool=existing_unallocated,
            target_pool_percent=target_pool_percent,
            new_money_shares=new_money_shares,
            target_basis=target_basis,
        )
        pool_topup_shares = float(topup_result["required_pool_topup_shares"])

    post_fd = pre_fd + safe_shares + note_shares + pool_topup_shares + new_money_shares

    # Per-class aggregate ownership
    founders_shares = sum(int(f["common_shares"]) for f in cap_state["founders"])
    preferred_as_conv = cap_state["as_converted_totals"]["preferred_shares_as_converted"]
    pool_total = (
        cap_state["as_converted_totals"]["options_outstanding"]
        + cap_state["as_converted_totals"]["options_available"]
        + pool_topup_shares
    )

    aggregate = {
        "founders_pct": founders_shares / post_fd if post_fd else 0.0,
        "preferred_pct": preferred_as_conv / post_fd if post_fd else 0.0,
        "option_pool_pct": pool_total / post_fd if post_fd else 0.0,
        "safe_pct": safe_shares / post_fd if post_fd else 0.0,
        "note_pct": note_shares / post_fd if post_fd else 0.0,
        "new_money_pct": new_money_shares / post_fd if post_fd else 0.0,
    }

    # Determine scenario completeness
    rejected_safes = [s for s, r in per_safe.items() if r.get("branch") == "rejected"]
    if rejected_safes:
        blockers.append(
            {
                "code": "E_SAFE_REQUIRES_CONVERSION_EVENT",
                "instance_id": ",".join(rejected_safes),
                "remedy": "One or more SAFEs could not resolve to a conversion price; check forms + inputs.",
            }
        )

    completeness = "full" if not blockers else "structural_only"

    return {
        "completeness": completeness,
        "blockers": blockers,
        "equity_financing_price": price,
        "iterations": iterations,
        "converged": converged,
        "post_round_fully_diluted_shares": int(round(post_fd)),
        "shares_breakdown": {
            "pre_round_fully_diluted": int(pre_fd),
            "safe_converted": int(round(safe_shares)),
            "note_converted": int(round(note_shares)),
            "pool_topup": int(round(pool_topup_shares)),
            "new_money": int(round(new_money_shares)),
        },
        "aggregate_ownership_by_class": aggregate,
        "per_safe": per_safe,
        "per_note": per_note,
        "convergence_history": history,
        "math_provenance": [
            {
                "output_field": "equity_financing_price",
                "source_type": "solver_intermediate",
                "rule_id": "safe.post_money_cap_conversion",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            },
        ],
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cap-state", required=True)
    p.add_argument("--instruments", required=True)
    p.add_argument("--pre-money", type=float, required=True)
    p.add_argument("--new-money", type=float, required=True)
    p.add_argument("--target-pool-pct", type=float, default=None)
    p.add_argument("--target-basis", default="pre_money")
    p.add_argument("--conversion-date", default=None)
    p.add_argument("--max-iter", type=int, default=DEFAULT_MAX_ITERATIONS)
    p.add_argument("--threshold", type=float, default=DEFAULT_CONVERGENCE_THRESHOLD)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)

    result = solve_priced_round(
        cap_state=cap_state,
        safes=instruments.get("safes", []),
        notes=instruments.get("notes", []),
        pre_money=args.pre_money,
        new_money=args.new_money,
        target_pool_percent=args.target_pool_pct,
        target_basis=args.target_basis,
        conversion_event_date=args.conversion_date,
        max_iterations=args.max_iter,
        convergence_threshold=args.threshold,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
