#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Priced-round math: resolves coupled SAFE/note conversion + new money + pool top-up.

Per design doc §9 Step 5: priced rounds have circular dependencies (option-pool
top-up needs new_money_shares; new_money_shares depends on
equity_financing_price; price depends on post-SAFE FD which depends on SAFE
conversion which depends on price). Solver attempts algebraic resolution first
(closed-form for cap-only post-money SAFEs per YC primer Example 1); falls back
to iterative fixed-point when discount-only SAFEs or coupled inputs make the
system non-linear.

YC post-money SAFE denominator (`company_capitalization`): per rule
`safe.post_money_cap_conversion` (rule pack v0.3.0+), the denominator passed to
the per-SAFE conversion formula is the FULL post-money fully-diluted snapshot
INCLUDING new-money shares. This is the denominator that makes the YC primer's
load-bearing identity `safe_ownership = purchase / cap` hold for post-money
SAFEs (`safe_shares = purchase / (cap / company_cap) = purchase × company_cap
/ cap = ownership × company_cap`). The solver iterates `company_capitalization`
toward the converged post-money FD.

Implementation history: pre-v0.3.0, `company_capitalization` was the
pre-financing snapshot (`cap_state.as_converted_totals.fully_diluted_shares`),
which applied the pre-money YC SAFE formula to post-money instruments and
under-allocated SAFE shares by `1 - new_money_pct`. Golden-test coverage in
`TestStackedPostMoneySAFEsGolden` locks the correct behavior.
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

RULE_PACK_VERSION = "0.3.1"


def _resolve_mfn_elections(safes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pre-resolve MFN-electing SAFEs against their elected siblings.

    Per the YC MFN provision, a SAFE that has `mfn_provision.elected_against_safe_id`
    pointing to a sibling SAFE with a resolved cap (and possibly discount)
    inherits that sibling's terms. Without auto-binding, the solver would
    require `conversion_price_override` on every MFN-electing SAFE — needless
    friction for the canonical case.

    Multi-hop resolution: A→B→C chains are resolved transitively by iterating
    to a fixed point. Each pass resolves any `yc_uncapped_mfn` whose election
    target now has a resolved (non-uncapped-MFN) form; iteration continues
    until no further resolutions happen. Bounded by `len(safes)` iterations
    since each pass either resolves at least one SAFE or terminates.

    Truly unresolvable cases (election to a missing sibling, all-uncapped
    cycles) are left unchanged — `detect_mfn_cycles` and the rejection path
    in `convert_safe_priced_round` handle them per Gotcha #4.

    The `_mfn_inherited_from` field records the immediate election anchor
    (not the transitive root), so a 3-hop chain A→B→C resolves to: A inherits
    B's resolved form (which itself inherited C's). Downstream reporting can
    trace the chain by walking each SAFE's `_mfn_inherited_from`.

    The original instrument records are NOT mutated — this returns a new list
    of shadow records.
    """
    out: list[dict[str, Any]] = [dict(s) for s in safes]
    max_iterations = len(out) + 1  # safety bound; can never need more than N hops
    for _ in range(max_iterations):
        by_id = {s["id"]: s for s in out}
        changed = False
        for i, s in enumerate(out):
            if s.get("form") != "yc_uncapped_mfn":
                continue
            mfn = s.get("mfn_provision") or {}
            elected_id = mfn.get("elected_against_safe_id")
            if not elected_id or elected_id not in by_id:
                continue
            anchor = by_id[elected_id]
            if anchor.get("form") == "yc_uncapped_mfn":
                # Anchor not yet resolved (chain not terminated at a capped
                # SAFE on this pass). Wait for next iteration; if cycle, the
                # cycle guard catches it.
                continue
            # Anchor has a resolved form (cap-only, cap+discount, discount-only,
            # or one of the pre-money legacy forms). Inherit form + cap + discount.
            shadow = dict(s)
            shadow["form"] = anchor["form"]
            shadow["post_money_valuation_cap"] = anchor.get("post_money_valuation_cap")
            shadow["pre_money_valuation_cap"] = anchor.get("pre_money_valuation_cap")
            shadow["discount_multiplier"] = anchor.get("discount_multiplier")
            shadow["_mfn_inherited_from"] = elected_id
            out[i] = shadow
            changed = True
        if not changed:
            break
    return out


def _safe_shares_at_price(
    safes: list[dict[str, Any]],
    *,
    company_capitalization: float,
    pre_money_fd: float,
    equity_financing_price: float,
) -> tuple[float, dict[str, dict[str, Any]]]:
    """Sum SAFE shares at a given (candidate) equity_financing_price.

    Returns (total_shares, per_safe_results) for the solver to iterate.

    Passes BOTH `company_capitalization` (post-money FD, iterates each round)
    AND `pre_money_fd` (pre-financing FD, constant). The math producer routes
    on form to pick the right denominator: post-money forms use
    company_capitalization; pre-money (legacy) forms use pre_money_fd.
    """
    total = 0.0
    per_safe: dict[str, dict[str, Any]] = {}
    for s in safes:
        r = convert_safe_priced_round(
            purchase_amount=s["purchase_amount"],
            form=s["form"],
            post_money_valuation_cap=s.get("post_money_valuation_cap"),
            pre_money_valuation_cap=s.get("pre_money_valuation_cap"),
            discount_multiplier=s.get("discount_multiplier"),
            company_capitalization=company_capitalization,
            pre_money_fd=pre_money_fd,
            equity_financing_price=equity_financing_price,
            conversion_price_override=s.get("conversion_price_override"),
        )
        # Propagate MFN inheritance provenance from shadow record to result
        # (M5 — without this, downstream reporting can't phrase "Investor X's
        # MFN-inherited terms from Investor Y").
        if s.get("_mfn_inherited_from"):
            r["_mfn_inherited_from"] = s["_mfn_inherited_from"]
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

    Algorithm: fixed-point iteration. Starting estimate uses
    `pre_money / pre_FD`. Each iteration:
      1. Compute SAFE conversion shares at current price estimate (post-money
         FD estimate passed as `company_capitalization` for post-money forms;
         constant `pre_money_fd` passed for pre-money legacy forms).
      2. Compute note conversion shares at current price estimate.
      3. Compute pool top-up at current FD estimate.
      4. Recompute equity_financing_price = pre_money / (pre_FD + SAFE + note + pool_topup).
      5. Update total_fd_estimate (add new_money_shares).
      6. Check convergence; loop.

    Convergence is typically 3-7 iterations for realistic cap tables
    (milliseconds wall-clock). No closed-form short-circuit; the iterative
    solver is fast enough that the maintenance cost of a parallel symbolic
    path is not worth the speedup.
    """
    blockers: list[dict[str, Any]] = []

    # Pre-resolve MFN-electing SAFEs against their elected siblings before the
    # solver runs. The resolver produces shadow records with inherited form +
    # cap + discount; the original list is unchanged. Truly uncapped MFNs
    # (no election or unresolvable chain) flow through untouched and hit the
    # cycle guard / rejection paths below.
    safes = _resolve_mfn_elections(safes)

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
    # Defensive init: if max_iterations=0 (degenerate input), rel_change is
    # referenced in the non-convergence blocker message below and would
    # NameError without this. (R4 LOW.a — Reviewer 4's audit finding.)
    rel_change = float("inf")
    # Initial estimate of post-money FD (used as company_capitalization for the
    # YC post-money SAFE formula). Refined each iteration.
    #
    # The YC post-money SAFE math requires `safe_price = cap / total_post_money_FD`
    # so that `safe_shares = purchase / safe_price = purchase × total_FD / cap`,
    # i.e., each SAFE locks `purchase/cap` of post-money_FD (per rule
    # `safe.stacked_post_money_caps` and the YC primer's worked examples). Using
    # `company_capitalization=pre_fd` (the pre-financing snapshot) would apply
    # the pre-money YC SAFE formula to post-money instruments — a math error
    # that under-allocates SAFE shares and over-states founder ownership.
    total_fd_estimate = pre_fd

    for i in range(max_iterations):
        iterations = i + 1
        # SAFE conversion at current price. Post-money forms use the
        # latest total-FD estimate as denominator; pre-money (legacy) forms
        # use the constant pre-financing FD. The math producer routes on form.
        safe_shares, per_safe = _safe_shares_at_price(
            safes,
            company_capitalization=total_fd_estimate,
            pre_money_fd=pre_fd,
            equity_financing_price=price,
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

        # New denominator for next-iteration price.
        # `denom` is the pre-new-money fully-diluted snapshot (post-SAFE,
        # post-pool-topup) — pre_money / denom = price-per-share that new
        # money pays.
        denom = pre_fd + safe_shares + note_shares + pool_topup_shares
        if denom <= 0:
            break
        new_price = pre_money / denom

        # Update total-FD estimate for the NEXT iteration's SAFE math. The YC
        # post-money formula's `company_capitalization` denominator is the FULL
        # post-money_FD INCLUDING the new-money shares (so that per-SAFE
        # ownership = purchase/cap of post-money_FD, per the YC primer worked
        # examples). new_money_shares = pre_money / new_price × (new_money/pre_money) = new_money / new_price.
        new_money_shares_for_fd = new_money / new_price if new_price > 0 else 0.0
        total_fd_estimate = denom + new_money_shares_for_fd

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

    # Final pass at converged price to capture per-safe/per-note results.
    # Form-dispatched: post-money SAFEs use total_fd_estimate (post-money FD
    # including new money); pre-money (legacy) SAFEs use pre_fd (pre-financing
    # snapshot, constant).
    safe_shares, per_safe = _safe_shares_at_price(
        safes,
        company_capitalization=total_fd_estimate,
        pre_money_fd=pre_fd,
        equity_financing_price=price,
    )
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
