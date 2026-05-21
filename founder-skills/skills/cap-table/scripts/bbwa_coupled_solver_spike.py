#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Sprint 0 math spike: coupled priced-round solver with anti-dilution.

THIS IS A SPRINT-0 SPIKE. It is throwaway code that exists solely to:
(1) nail the math against the 15 active goldens in
    docs/internal/2026-05-21-priced-round-coupled-solver-design.md §7.2,
(2) provide a known-correct reference implementation that Sprint 1's
    Adjuster protocol wraps + replaces.

Sprint 1 deletes this file and routes the same math through the
AntiDilutionAdjuster + SafeConversionAdjuster + ... chain. The goldens
in test_coupled_solver_goldens.py persist as the v0.4.0 regression suite.

Architecture (per v3 design §3.4-§3.7):
- AD does NOT mint preferred shares. It MUTATES current_conversion_price.
  preferred_as_converted is derived via `shares × OCP / CCP` (matches
  cap_state.py:_compute_as_converted_totals).
- A denominator (NVCA §4.4.4) is an IMMUTABLE pre-financing snapshot;
  frozen at iter 0; never recomputed.
- Trigger threshold: OIP by NVCA default; per-series override via
  ad_trigger_basis ∈ {original_issue_price, current_conversion_price}.
- Carve-outs: NVCA-default ONLY in v0.4.0 (consideration = new_money).
  Custom carve-outs deferred to v0.5.0.
- Fixed-point solver: starts at PPS = pre_money / pre_FD; iterates with
  per-series CCP mutation in the inner loop.
"""

from __future__ import annotations

import sys
from typing import Any

# Import the standalone math producers — single source of truth.
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from anti_dilution import (  # noqa: E402
    bbwa_new_conversion_price,
    full_ratchet_new_conversion_price,
)

# Convergence tuning (Sprint 1 will move these into the solver framework
# with sign-flip + Aitken guards per design §3.3).
DEFAULT_MAX_ITERATIONS = 200
DEFAULT_REL_THRESHOLD = 1e-6
DEFAULT_ABS_THRESHOLD = 1e-9


def _compute_pre_financing_a_components(
    common_shares: int,
    preferred_series: list[dict[str, Any]],
    options_outstanding: int,
    options_available: int,
) -> dict[str, int]:
    """Compute the NVCA-broad A denominator components from pre-financing state.

    Per NVCA §4.4.4(a), A is the "Common Stock Deemed Outstanding immediately
    prior to such issue." Components:
      - common_shares (founder common + common_batches)
      - preferred_shares_as_converted (at current CCP, frozen at iter 0)
      - options_outstanding (issued and outstanding under the plan)
      - options_available (unallocated / reserved under the plan)

    These are FROZEN at solver entry and never recomputed — A is a snapshot,
    not an iterating quantity.
    """
    preferred_as_converted = 0
    for s in preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp == 0:
            preferred_as_converted += shares
        else:
            preferred_as_converted += int(round(shares * (ocp / ccp)))
    return {
        "common_shares": int(common_shares),
        "preferred_shares_as_converted": int(preferred_as_converted),
        "options_outstanding": int(options_outstanding),
        "options_available": int(options_available),
    }


def _compute_A(components: dict[str, int], basis: str) -> float:
    """Compute the BBWA / narrow-based A denominator from frozen components."""
    if basis == "nvca_broad":
        return float(
            components["common_shares"]
            + components["preferred_shares_as_converted"]
            + components["options_outstanding"]
            + components["options_available"]
        )
    elif basis == "nvca_narrow":
        return float(components["common_shares"] + components["preferred_shares_as_converted"])
    raise ValueError(f"Unknown ad_a_denominator_basis: {basis}")


def _default_a_basis(protection: str) -> str:
    return "nvca_broad" if protection == "broad_based_weighted_average" else "nvca_narrow"


def _prior_down_round_in_history(series: dict[str, Any], cap_table_history: list[dict[str, Any]]) -> bool:
    """Check cap_table_history for prior anti_dilution_applied event on this series."""
    sid = series.get("series_id")
    return any(
        ev.get("event_type") == "anti_dilution_applied" and ev.get("series_id") == sid for ev in cap_table_history
    )


def _apply_anti_dilution(
    *,
    preferred_series: list[dict[str, Any]],
    cp1_snapshots: dict[str, float],
    new_pps: float,
    consideration: float,
    a_components: dict[str, int],
    cap_table_history: list[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply AD per-series. Returns (ccp_mutations, breakdown, warnings).

    `cp1_snapshots` is a per-series frozen-at-iter-0 map of original CCP
    values. The AD math uses these as CP1 each iteration (CP1 is fixed for
    the round; only new_pps moves in the fixed-point loop). Without this
    snapshot the spike would apply AD-on-AD-on-AD across iterations
    (ratchet-on-ratchet), which is explicitly v0.5.0 scope per design §9.

    Does NOT mutate preferred_series in place. Caller applies ccp_mutations.
    """
    ccp_mutations: dict[str, float] = {}
    breakdown: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for series in preferred_series:
        protection = series.get("anti_dilution_protection", "none")
        if protection == "none":
            continue

        oip = float(series["original_issue_price"])
        ocp = float(series.get("original_conversion_price", oip))
        # CP1 is the FROZEN original CCP from iter 0, not the working CCP.
        cp1 = cp1_snapshots[series["series_id"]]

        trigger_basis = series.get("ad_trigger_basis", "original_issue_price")
        trigger_price = oip if trigger_basis == "original_issue_price" else cp1

        if new_pps >= trigger_price:
            continue  # not a dilutive issuance for this series

        # Stale-CCP guard (checked against the FROZEN cp1, not the working CCP)
        if cp1 == ocp and _prior_down_round_in_history(series, cap_table_history):
            warnings.append(
                {
                    "code": "W_STALE_CCP_SUSPECTED",
                    "series_id": series["series_id"],
                }
            )

        a_basis = series.get("ad_a_denominator_basis", _default_a_basis(protection))
        A = _compute_A(a_components, a_basis)

        B: float | None = None
        C: float | None = None

        if protection in ("broad_based_weighted_average", "narrow_based_weighted_average"):
            B = consideration / cp1 if cp1 > 0 else 0.0
            C = consideration / new_pps if new_pps > 0 else 0.0
            result = bbwa_new_conversion_price(
                current_conversion_price=cp1,
                pre_issuance_share_count_A=A,
                consideration_received=consideration,
                new_issue_price=new_pps,
                new_shares_issued_C=C,
            )
            cp2 = result["new_conversion_price"]
            rule_id = f"anti_dilution.{protection}_coupled"
        elif protection == "full_ratchet":
            result = full_ratchet_new_conversion_price(
                current_conversion_price=cp1,
                new_issue_price=new_pps,
            )
            cp2 = result["new_conversion_price"]
            rule_id = "anti_dilution.full_ratchet_coupled"
        else:
            raise ValueError(f"Unknown anti_dilution_protection: {protection}")

        # CP2 floor
        floor = series.get("ad_cp2_floor")
        cp2_unfloored = cp2
        floor_applied = False
        if floor is not None and cp2 < floor:
            cp2 = float(floor)
            floor_applied = True
            warnings.append(
                {
                    "code": "W_CP2_FLOOR_APPLIED",
                    "series_id": series["series_id"],
                    "cp2_unfloored": cp2_unfloored,
                    "cp2_floor": floor,
                }
            )

        ccp_mutations[series["series_id"]] = cp2
        breakdown.append(
            {
                "series_id": series["series_id"],
                "protection_type": protection,
                "ad_trigger_basis": trigger_basis,
                "ad_a_denominator_basis": a_basis,
                "trigger_price": trigger_price,
                "new_pps": new_pps,
                "ccp_before": cp1,
                "ccp_after": cp2,
                "ccp_unfloored": cp2_unfloored,
                "floor_applied": floor_applied,
                "A": A,
                "B": B,
                "C": C,
                "rule_id": rule_id,
            }
        )

    return ccp_mutations, breakdown, warnings


def _preferred_as_converted_total(preferred_series: list[dict[str, Any]]) -> int:
    """preferred_as_converted using the CURRENT CCP on each series.

    Matches cap_state.py:_compute_as_converted_totals semantics.
    """
    total = 0
    for s in preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp == 0:
            total += shares
        else:
            total += int(round(shares * (ocp / ccp)))
    return total


def solve_coupled_priced_round(
    *,
    common_shares: int,
    preferred_series: list[dict[str, Any]],
    options_outstanding: int,
    options_available: int,
    safes: list[dict[str, Any]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    pre_money: float,
    new_money: float,
    target_pool_percent: float | None = None,
    target_basis: str = "pre_money",
    cap_table_history: list[dict[str, Any]] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    rel_threshold: float = DEFAULT_REL_THRESHOLD,
    abs_threshold: float = DEFAULT_ABS_THRESHOLD,
) -> dict[str, Any]:
    """Spike: coupled fixed-point solver with AD as the first stage.

    Sprint 0 scope:
      - AD adjustment (BBWA / narrow / full_ratchet) via per-series CCP mutation
      - new-money issuance
      - pool top-up (basic; matches existing option_pool.required_topup contract)
      - SAFE conversion (deferred to Sprint 1; goldens 4, 18 use Sprint 0's
        ad-hoc input shape and the spike returns pre-computed SAFE shares)
      - note conversion (same as SAFE)

    Returns a dict with converged PPS, CP2 per series, breakdown, founder %,
    and convergence diagnostics.
    """
    safes = safes or []
    notes = notes or []
    cap_table_history = cap_table_history or []

    # Working copy — never mutate caller's data
    working_preferred = [dict(s) for s in preferred_series]

    # Frozen A snapshot for AD (NVCA §4.4.4: "immediately prior to such issue")
    a_components = _compute_pre_financing_a_components(
        common_shares=common_shares,
        preferred_series=working_preferred,
        options_outstanding=options_outstanding,
        options_available=options_available,
    )

    # Frozen CP1 snapshot per series. CP1 is the original CCP at iter 0;
    # it's the fixed input to BBWA each iteration. Without this snapshot,
    # we'd apply AD-on-AD across iters (ratchet-on-ratchet — v0.5.0 scope).
    cp1_snapshots: dict[str, float] = {
        s["series_id"]: float(
            s.get("current_conversion_price", s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        )
        for s in working_preferred
    }

    # Pre-financing FD (with initial CCP)
    pre_preferred_as_converted = _preferred_as_converted_total(working_preferred)
    pre_fd = common_shares + pre_preferred_as_converted + options_outstanding + options_available
    if pre_fd <= 0:
        return {"completeness": "structural_only", "blockers": ["pre_fd <= 0"]}

    # Initial PPS estimate
    pps = pre_money / pre_fd
    pre_pps = pps
    history: list[dict[str, Any]] = [{"iteration": 0, "pps": pps}]

    all_warnings: list[dict[str, Any]] = []
    ad_breakdown: list[dict[str, Any]] = []

    # NVCA-default carve-outs: consideration = new_money only (v0.4.0)
    consideration = new_money

    converged = False
    for n in range(max_iterations):
        # Stage 1: adjust_cap_state — AD CCP mutations (uses FROZEN cp1_snapshots)
        ccp_mutations, ad_breakdown, ad_warnings = _apply_anti_dilution(
            preferred_series=working_preferred,
            cp1_snapshots=cp1_snapshots,
            new_pps=pps,
            consideration=consideration,
            a_components=a_components,
            cap_table_history=cap_table_history,
        )
        all_warnings = ad_warnings  # only keep latest iter's warnings (avoid duplicates)

        # Apply CCP mutations to working_preferred
        for series in working_preferred:
            sid = series["series_id"]
            if sid in ccp_mutations:
                series["current_conversion_price"] = ccp_mutations[sid]

        # Recompute as_converted_totals after CCP mutation
        adj_preferred = _preferred_as_converted_total(working_preferred)
        adj_pre_fd = common_shares + adj_preferred + options_outstanding + options_available

        # Stage 2: convert_securities — SAFE + note (Sprint 0 stub: caller supplies shares)
        safe_shares_total = sum(float(s.get("conversion_shares", 0.0)) for s in safes)
        note_shares_total = sum(float(n.get("conversion_shares", 0.0)) for n in notes)

        # Stage 3: size_round — pool top-up + new money
        pool_topup_shares = 0.0
        if target_pool_percent and target_pool_percent > 0:
            # Sprint 0 spike does NOT implement pool top-up math. The Sprint 1
            # PoolTopUpAdjuster will wrap option_pool.required_topup with the
            # correct (target × pre_fd − existing) / (1 − target) formula. The
            # spike's previous simplification had three bugs (pre_money vs
            # post_money branches identical, missing /(1-target) factor, wrong
            # existing baseline). Sprint-0 Goldens 1-3, 6-13, 16, 17 don't
            # exercise this parameter. Fail loud rather than silently produce
            # wrong numbers.
            raise NotImplementedError(
                "target_pool_percent > 0 is Sprint 1 scope (PoolTopUpAdjuster "
                "wraps option_pool.required_topup). The Sprint 0 spike does "
                "not implement pool top-up math."
            )

        denom = adj_pre_fd + safe_shares_total + note_shares_total + pool_topup_shares
        if denom <= 0:
            break
        new_pps = pre_money / denom

        # Convergence
        rel_change = abs(new_pps - pps) / max(pps, 1e-12)
        abs_change = abs(new_pps - pps)
        history.append({"iteration": n + 1, "pps": new_pps, "rel_change": rel_change})
        pps = new_pps

        if rel_change < rel_threshold and abs_change < abs_threshold:
            converged = True
            break

    # Final per-series CCP map and breakdown (use the converged-iteration's breakdown)
    new_money_shares = new_money / pps if pps > 0 else 0.0
    final_preferred = _preferred_as_converted_total(working_preferred)
    post_fd = (
        common_shares
        + final_preferred
        + options_outstanding
        + options_available
        + pool_topup_shares
        + safe_shares_total
        + note_shares_total
        + new_money_shares
    )

    # founder_pct calculations
    founder_pct = common_shares / post_fd if post_fd > 0 else 0.0

    # Pre-AD baseline: what founder % WOULD be if AD had not applied.
    # Uses pre-AD PPS (the no-AD equilibrium, which is just pre_money/pre_fd
    # in the simple case with no SAFEs/notes; the iterative loop still
    # converges because pool_topup may have its own non-linearity). For
    # Sprint 0 spike with no SAFEs/notes/pool-target, this is just the
    # initial pps estimate.
    pre_ad_new_money_shares = new_money / pre_pps if pre_pps > 0 else 0.0
    pre_ad_post_fd = (
        common_shares
        + pre_preferred_as_converted
        + options_outstanding
        + options_available
        + pool_topup_shares
        + safe_shares_total
        + note_shares_total
        + pre_ad_new_money_shares
    )
    founder_pct_pre_ad = common_shares / pre_ad_post_fd if pre_ad_post_fd > 0 else 0.0

    return {
        "converged": converged,
        "iterations": len(history) - 1,
        "equity_financing_price": pps,
        "post_fd_shares": post_fd,
        "founder_pct": founder_pct,
        "founder_pct_pre_anti_dilution": founder_pct_pre_ad,
        "anti_dilution_delta_pct_points": (founder_pct - founder_pct_pre_ad) * 100,
        "anti_dilution_breakdown": ad_breakdown,
        "ccp_mutations": {s["series_id"]: float(s["current_conversion_price"]) for s in working_preferred},
        "new_money_shares": new_money_shares,
        "preferred_as_converted_total": final_preferred,
        "pre_financing_a_components": a_components,
        "convergence_history": history,
        "warnings": all_warnings,
    }
