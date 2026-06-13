#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Coupled priced-round solver with anti-dilution.

Priced rounds have circular dependencies (option-pool top-up needs
new_money_shares; new_money_shares depends on equity_financing_price;
price depends on post-SAFE/note/pool FD; anti-dilution to existing
preferred series depends on the new PPS AND changes total FD via mutated
current_conversion_price). The solver iterates to a fixed point with all
adjusters in a single Banach loop.

Architecture (Adjuster Protocol):
  * Each adjuster wraps an existing math producer (anti_dilution.py,
    safe_conversion.py, note_conversion.py, option_pool.py) and runs in
    one of three stages per iteration:
      - adjust_cap_state: AntiDilutionAdjuster mutates CCP on each
        AD-protected preferred series. The mutation flows through
        cap_state._compute_as_converted_totals into total_FD.
      - convert_securities: SafeConversionAdjuster + NoteConversionAdjuster
        compute conversion shares against AD-adjusted total_FD and PPS.
      - size_round: PoolTopUpAdjuster + NewMoneyAdjuster size the new
        round shares.
  * Adjusters are pure functions of SolverState; the orchestrator applies
    their returned state_mutations.
  * MFN resolution stays STRUCTURAL (one-time pre-pass, not per-iter) —
    inheritance is PPS-independent.
  * CP1 (the original CCP per AD-protected series) is FROZEN at iter 0
    in `pre_financing_cp1_snapshots` to avoid ratchet-on-ratchet.
  * A denominator components are FROZEN at iter 0 in
    `pre_financing_a_components` per NVCA §4.4.4 "immediately prior to
    such issue."

Convergence:
  * Bare fixed-point iteration when |f'_est| < 0.9 (the typical regime).
  * Sign-flip detection triggers under-relaxation (α=0.5) on 3+ alternations.
  * Aitken Δ² acceleration engages when |f'_est| > 0.9 for 3+ iterations.
  * Aitken fallback fence: if projected step moves > 20× vanilla step,
    abort acceleration and revert to vanilla; emit warning.
  * Hard 200-iteration cap.
  * Convergence threshold: |Δp/p| < 1e-6 AND |Δp| < 1e-9.

Backwards compatibility:
  * When no preferred series has anti_dilution_protection != none, the
    AntiDilutionAdjuster short-circuits — output is semantically
    identical to a no-AD solver. Old-shape fields bit-for-bit; new optional
    fields (anti_dilution_breakdown, founders_pct_pre_anti_dilution) are
    added with no-op values.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from typing import Any

# Solver tuning
DEFAULT_MAX_ITERATIONS = 200
DEFAULT_CONVERGENCE_THRESHOLD = 1e-6  # relative change in price between iterations
DEFAULT_ABS_THRESHOLD = 1e-9
AITKEN_TRIGGER_CONTRACTION = 0.9
AITKEN_FALLBACK_STEP_RATIO = 20.0
SIGN_FLIP_DAMP_ALPHA = 0.5
SIGN_FLIP_DETECTION_WINDOW = 3
# PPS sanity floor: a converged price below this value has no valid economic
# interpretation.  Any realistic instrument conversion results in a PPS of at
# least a fraction of a cent ($0.000001); sub-floor values indicate the
# iteration collapsed toward zero because the instruments collectively demand
# ≥100% of the company (purchase amounts exceed caps / combined fractions ≥ 1).
PPS_SANITY_FLOOR = 1e-6

# Import sibling math producers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _emit import add_output_args, emit  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402
from anti_dilution import (  # noqa: E402
    bbwa_new_conversion_price,
    full_ratchet_new_conversion_price,
)
from note_conversion import convert_note  # noqa: E402
from option_pool import required_topup  # noqa: E402
from safe_conversion import (  # noqa: E402
    convert_safe_priced_round,
    detect_mfn_cycles,
)

# ============================================================================
# Adjuster Protocol — types
# ============================================================================
# Per v3 design §3.1. Each adjuster wraps an existing math producer and runs
# in one of three stages within a single iteration. The orchestrator
# (solve_priced_round) reads adjuster results and applies state_mutations.


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

    MFN resolution is STRUCTURAL (one-time pre-pass, NOT per-iteration).
    Inheritance is PPS-independent, so it never needs to be redone inside
    the fixed-point loop.

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
                # Anchor not yet resolved; wait for next pass.
                continue
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


# ============================================================================
# AntiDilutionAdjuster (stage: adjust_cap_state)
# ============================================================================
# Per v3 design §3.4. Mutates current_conversion_price on each AD-protected
# preferred series. AD does NOT mint new preferred shares — it changes the
# conversion ratio. cap_state._compute_as_converted_totals then derives the
# higher as-converted share count via shares × OCP / CCP.


def _default_a_basis(protection: str) -> str:
    """Per-series default A denominator basis derived from protection enum.

    NVCA-default: BBWA uses broad-based A; narrow-based uses narrow.
    full_ratchet doesn't use an A denominator (returns p* directly).
    """
    return "nvca_broad" if protection == "broad_based_weighted_average" else "nvca_narrow"


def _compute_a_denominator(components: dict[str, int], basis: str) -> float:
    """Compute A from frozen pre-financing components per NVCA §4.4.4.

    nvca_broad: common + preferred-as-converted + options outstanding + options reserved
                + warrants_underlying_total.
                NVCA §4.4.4 includes "Options outstanding" in A, and the NVCA
                definition of "Option" expressly includes warrants ("rights,
                options or warrants to purchase shares of Common Stock").
                Outstanding warrants therefore belong in the broad basis.
    nvca_narrow: common + preferred-as-converted only (excludes options and
                warrants per the NVCA footnote's narrow-variant description).
    """
    if basis == "nvca_broad":
        return float(
            components["common_shares"]
            + components["preferred_shares_as_converted"]
            + components["options_outstanding"]
            + components["options_available"]
            + components.get("warrants_underlying_total", 0)
        )
    elif basis == "nvca_narrow":
        return float(components["common_shares"] + components["preferred_shares_as_converted"])
    raise ValueError(f"Unknown ad_a_denominator_basis: {basis}. (Custom A-basis is a future extension.)")


def _prior_down_round_in_history(series_id: str, cap_table_history: list[dict[str, Any]]) -> bool:
    """Check cap_table_history for prior anti_dilution_applied event on this series."""
    return any(
        ev.get("event_type") == "anti_dilution_applied" and ev.get("series_id") == series_id for ev in cap_table_history
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
    """AntiDilutionAdjuster.compute() core. Returns (ccp_mutations, breakdown, warnings).

    `cp1_snapshots` is FROZEN at iter 0 to avoid ratchet-on-ratchet.
    Within a single round, CP1 stays constant; only new_pps moves through the
    fixed-point iteration.

    Does NOT mutate preferred_series in place. Caller applies ccp_mutations.
    """
    ccp_mutations: dict[str, float] = {}
    breakdown: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for series in preferred_series:
        protection = series.get("anti_dilution_protection", "none")
        if protection == "none":
            continue

        sid = series["series_id"]
        oip = float(series["original_issue_price"])
        ocp = float(series.get("original_conversion_price", oip))
        # CP1 is the FROZEN original CCP from iter 0, NOT the working CCP.
        cp1 = cp1_snapshots[sid]

        trigger_basis = series.get("ad_trigger_basis", "original_issue_price")
        trigger_price = oip if trigger_basis == "original_issue_price" else cp1

        if new_pps >= trigger_price:
            continue  # not a dilutive issuance for this series

        # Stale-CCP guard (checked against the FROZEN cp1)
        if cp1 == ocp and _prior_down_round_in_history(sid, cap_table_history):
            warnings.append({"code": "W_STALE_CCP_SUSPECTED", "series_id": sid})

        a_basis = series.get("ad_a_denominator_basis", _default_a_basis(protection))
        A = _compute_a_denominator(a_components, a_basis)

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

        # CP2 floor enforcement (per-series)
        floor = series.get("ad_cp2_floor")
        cp2_unfloored = cp2
        floor_applied = False
        if floor is not None and cp2 < floor:
            cp2 = float(floor)
            floor_applied = True
            warnings.append(
                {
                    "code": "W_CP2_FLOOR_APPLIED",
                    "series_id": sid,
                    "cp2_unfloored": cp2_unfloored,
                    "cp2_floor": floor,
                }
            )

        ccp_mutations[sid] = cp2
        breakdown.append(
            {
                "series_id": sid,
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
                "rule_pack_version": RULE_PACK_VERSION,
            }
        )

    return ccp_mutations, breakdown, warnings


def _preferred_as_converted_total(preferred_series: list[dict[str, Any]]) -> int:
    """preferred_as_converted using the CURRENT CCP on each series.

    Matches cap_state.py:_compute_as_converted_totals semantics (uses
    int(round) on each per-series contribution — cap tables can't hold
    fractional preferred shares).
    """
    total = 0
    for s in preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp <= 0:
            raise ValueError(
                f"E_PREFERRED_SERIES_INVALID_PRICE: preferred_series[{s.get('series_id', '?')}]"
                f".current_conversion_price resolves to {ccp} (must be > 0)."
            )
        total += int(round(shares * (ocp / ccp)))
    return total


def _refresh_as_converted_totals(cap_state: dict[str, Any]) -> None:
    """Recompute cap_state.as_converted_totals after CCP mutations.

    Called by the orchestrator after AntiDilutionAdjuster applies CCP changes
    so subsequent stage-2 adjusters (SAFE/note conversion) see AD-adjusted
    preferred-as-converted in total_FD.
    """
    preferred_series = cap_state.get("preferred_series", [])
    new_preferred_as_converted = _preferred_as_converted_total(preferred_series)
    ats = cap_state["as_converted_totals"]
    old_preferred = ats["preferred_shares_as_converted"]
    delta = new_preferred_as_converted - old_preferred
    ats["preferred_shares_as_converted"] = new_preferred_as_converted
    ats["fully_diluted_shares"] = ats["fully_diluted_shares"] + delta


# ============================================================================
# Convergence guards (sign-flip damping + Aitken Δ²)
# ============================================================================
# Per v3 design §3.3. The composed map can be positive-feedback with |f'|
# close to 1 in pathological regimes. These guards prevent oscillation /
# slow convergence / divergence.


def _detect_sign_flip(history: list[float], window: int) -> bool:
    """Returns True if the last `window+1` PPS deltas have alternating signs."""
    if len(history) < window + 2:
        return False
    deltas = [history[i + 1] - history[i] for i in range(len(history) - 1)]
    recent = deltas[-window:]
    # All recent deltas must alternate
    for i in range(len(recent) - 1):
        if recent[i] == 0 or recent[i + 1] == 0:
            return False
        if (recent[i] > 0) == (recent[i + 1] > 0):
            return False
    return True


def _estimate_contraction(history: list[float]) -> float | None:
    """Empirical |f'_est| ≈ |Δp_n / Δp_{n-1}| from the last 3 PPS values.

    Returns None if history is too short or recent step is zero.
    """
    if len(history) < 3:
        return None
    d1 = history[-1] - history[-2]
    d0 = history[-2] - history[-3]
    if abs(d0) < 1e-15:
        return None
    return abs(d1 / d0)


def _aitken_projection(history: list[float]) -> float | None:
    """Aitken Δ² projection of the fixed point from the last 3 PPS values.

    Per the Shanks transformation anchored at p_{n-2}:
        p* ≈ p_{n-2} - (Δp_{n-2})² / Δ²p_{n-2}
    where:
        Δp_{n-2}  = p_{n-1} - p_{n-2}        (first forward difference)
        Δ²p_{n-2} = p_n - 2 p_{n-1} + p_{n-2} (second forward difference)

    Returns None if catastrophic cancellation (Δ² near zero — near a 2-cycle).

    A reviewer caught an earlier numerator bug: a prior version used
    `(p_n - p_{n-2})²` which overshoots by a factor of ~(1+r)² where r is the
    convergence rate. The 20× fallback fence masked the divergence on most
    realistic inputs but would have slowed convergence rather than
    accelerated it. The correct numerator is the first forward difference
    squared, NOT the two-step span.
    """
    if len(history) < 3:
        return None
    p_nm2, p_nm1, p_n = history[-3], history[-2], history[-1]
    delta = p_nm1 - p_nm2
    delta_squared = p_n - 2 * p_nm1 + p_nm2
    if abs(delta_squared) < 1e-15:
        return None
    return p_nm2 - (delta * delta) / delta_squared


# ============================================================================
# SAFE / Note conversion stages
# ============================================================================
# These wrap existing math producers and are called by the orchestrator inside
# the iteration loop. Behavior matches the legacy no-AD solver verbatim — the
# wrapping is structural, not semantic.


def _safe_shares_at_price(
    safes: list[dict[str, Any]],
    *,
    company_capitalization: float,
    pre_money_fd: float,
    equity_financing_price: float,
    pre_money_valuation: float | None = None,
) -> tuple[float, dict[str, dict[str, Any]]]:
    """Sum SAFE shares at a given (candidate) equity_financing_price.

    Passes BOTH `company_capitalization` (YC "Company Capitalization" measured
    immediately prior to the equity financing = adj_pre_fd + converting
    securities, EXCLUDING new-money shares and in-connection pool top-ups; per
    rule `safe.company_capitalization_yc_post_money`) AND `pre_money_fd`
    (pre-financing FD including in-connection pool top-up for pre-money forms,
    per the YC pre-money SAFE "Company Capitalization" definition). The math
    producer routes on form: post-money forms use company_capitalization;
    pre-money (legacy) forms use pre_money_fd.

    `pre_money_valuation` is forwarded to `convert_safe_priced_round` so the
    §(a)(1)/§(a)(2) branch selection can fire for pre-money SAFE forms.
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
            pre_money_valuation=pre_money_valuation,
        )
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


# ============================================================================
# Main orchestrator
# ============================================================================


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
    """Solve the coupled priced-round system with anti-dilution.

    Implements the coupled-AD priced-round equilibrium via fixed-point iteration.

    Returns a structured result with the resolved equity_financing_price,
    per-SAFE / per-note conversion, pool top-up, post-round cap table,
    AD breakdown (if any), and math provenance.

    Convergence:
      * Bare fixed-point iteration when |f'_est| < 0.9.
      * Sign-flip detection → α=0.5 under-relaxation on 3+ alternations.
      * Aitken Δ² acceleration when |f'_est| > 0.9 for 3+ iterations.
      * Aitken fallback fence: revert if projected step > 20× vanilla.
      * Hard 200-iter cap; |Δp/p| < 1e-6 AND |Δp| < 1e-9 termination.

    Backwards compat:
      * When no preferred series has AD protection, output is semantically
        identical to a no-AD solver — old-shape fields bit-for-bit.
    """
    # DEEP-COPY BOUNDARY: every adjuster operates on this working copy.
    # The caller's cap_state is never touched.
    working_cap_state = copy.deepcopy(cap_state)

    blockers: list[dict[str, Any]] = []

    # Notes present but no conversion date → structural-only blocker (never
    # crash). Mirrors run_scenario's note-path E_NOTE_NO_CONVERSION_DATE shape.
    if notes and not conversion_event_date:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_NOTE_NO_CONVERSION_DATE",
                    "instance_id": None,
                    "remedy": "Provide conversion_event_date when convertible notes are present.",
                }
            ],
            "per_safe": {},
            "per_note": {},
        }

    # After the guard above, conversion_event_date is non-None whenever notes
    # are present. Narrow to a non-Optional local for the note-conversion calls
    # (the bare assert is avoided so -O cannot strip note conversions).
    note_conversion_date: str = conversion_event_date or ""

    # MFN resolution is STRUCTURAL — one-time pre-pass, not per-iter.
    safes = _resolve_mfn_elections(safes)

    # MFN cycle guard
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

    pre_fd = float(working_cap_state["as_converted_totals"]["fully_diluted_shares"])

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

    # IMMUTABLE A SNAPSHOT — frozen at iteration zero per NVCA §4.4.4
    # "immediately prior to such issue."  Includes warrants_underlying_total
    # per NVCA's Option definition (which expressly includes warrants).
    pre_ats = working_cap_state["as_converted_totals"]
    pre_financing_a_components = {
        "common_shares": int(pre_ats["common_shares"]),
        "preferred_shares_as_converted": int(pre_ats["preferred_shares_as_converted"]),
        "options_outstanding": int(pre_ats["options_outstanding"]),
        "options_available": int(pre_ats["options_available"]),
        "warrants_underlying_total": int(pre_ats.get("warrants_underlying_total", 0)),
    }

    # IMMUTABLE CP1 SNAPSHOTS — frozen at iter 0 per AD-protected series.
    # Without freezing, AntiDilutionAdjuster would read the iter-mutated CCP
    # and apply AD on top of itself (ratchet-on-ratchet — a future extension).
    preferred_series = working_cap_state.get("preferred_series", [])
    # cap_state guarantees current_conversion_price is always written (fallback
    # chain current → original_conversion_price), so the second slot is
    # unreachable in practice; it exists only as a defensive guard.
    pre_financing_cp1_snapshots: dict[str, float] = {
        s["series_id"]: float(
            s.get(
                "current_conversion_price",
                s.get("original_conversion_price", 1.0),
            )
        )
        for s in preferred_series
    }

    # Pre-AD baseline: snapshot the un-AD-adjusted preferred-as-converted so we
    # can compute founder_pct_pre_anti_dilution at the end.
    pre_ad_preferred_as_converted = pre_financing_a_components["preferred_shares_as_converted"]

    # Detect whether ANY series carries AD protection. When none, the
    # AntiDilutionAdjuster short-circuits and we never call
    # _refresh_as_converted_totals — preserves the no-AD output bit-for-bit.
    has_ad_protection = any(s.get("anti_dilution_protection", "none") != "none" for s in preferred_series)

    # Initial price estimate: pre_money / pre_FD
    price = pre_money / pre_fd
    pre_pps = price  # frozen no-AD baseline for founder_pct_pre_ad
    iterations = 0
    history: list[float] = [price]
    rel_change = float("inf")
    abs_change = float("inf")
    # company_cap_estimate tracks the YC post-money SAFE denominator:
    # "Company Capitalization" measured immediately prior to the equity financing
    # = existing shares + pre-existing unissued pool + ALL converting securities
    # (SAFEs + notes, self-referential via the fixed-point loop).
    # Per the YC post-money SAFE definition and rule
    # `safe.company_capitalization_yc_post_money`, this EXCLUDES new-money
    # financing shares and in-connection pool top-ups.
    company_cap_estimate = float(pre_fd)
    # pm_pre_money_fd_estimate tracks the denominator for pre-money SAFE forms:
    # per the YC pre-money SAFE "Company Capitalization" clause, this INCLUDES
    # the in-connection pool top-up. Initialised to pre_fd (0 topup at iteration 0);
    # updated at the end of each iteration once pool_topup_shares is known.
    pm_pre_money_fd_estimate = float(pre_fd)
    aitken_engaged = False
    aitken_fallback_engaged = False
    damping_engaged = False
    ad_breakdown: list[dict[str, Any]] = []
    ad_warnings: list[dict[str, Any]] = []
    solver_warnings: list[dict[str, Any]] = []

    # Initialize per-iter outputs (used in convergence-loop scope)
    safe_shares: float = 0.0
    note_shares: float = 0.0
    new_money_shares: float = 0.0
    pool_topup_shares: float = 0.0
    per_safe: dict[str, dict[str, Any]] = {}
    per_note: dict[str, dict[str, Any]] = {}

    converged = False
    for i in range(max_iterations):
        iterations = i + 1

        # === Stage 1: adjust_cap_state (AntiDilutionAdjuster) ===
        if has_ad_protection:
            ccp_mutations, ad_breakdown, ad_warnings = _apply_anti_dilution(
                preferred_series=preferred_series,
                cp1_snapshots=pre_financing_cp1_snapshots,
                new_pps=price,
                consideration=new_money,  # NVCA-default carve-outs only
                a_components=pre_financing_a_components,
                cap_table_history=working_cap_state.get("cap_table_history", []),
            )
            if ccp_mutations:
                # Apply mutations to working preferred_series
                for s in preferred_series:
                    sid = s["series_id"]
                    if sid in ccp_mutations:
                        s["current_conversion_price"] = ccp_mutations[sid]
                # Refresh as_converted_totals so downstream adjusters see
                # AD-adjusted preferred-as-converted in pre_fd.
                _refresh_as_converted_totals(working_cap_state)

        # The working pre_fd may have changed due to AD CCP mutations.
        adj_pre_fd = float(working_cap_state["as_converted_totals"]["fully_diluted_shares"])

        # === Stage 2: convert_securities (SAFE + Note) ===
        # company_cap_estimate is the YC "Company Capitalization" denominator:
        # adj_pre_fd + safe_shares + note_shares from the previous iteration.
        # It excludes new-money shares and pool top-ups per the YC post-money
        # SAFE definition. The fixed-point loop self-consistently resolves the
        # circular dependency (converting securities appear in both the numerator
        # share count and the denominator they convert against).
        # pm_pre_money_fd_estimate is the denominator for pre-money SAFE forms:
        # adj_pre_fd + pool_topup_shares from the previous iteration, per the YC
        # pre-money SAFE "Company Capitalization" clause (includes in-connection
        # pool increase; rule `safe.pre_money_cap_conversion`).
        safe_shares, per_safe = _safe_shares_at_price(
            safes,
            company_capitalization=company_cap_estimate,
            pre_money_fd=pm_pre_money_fd_estimate,
            equity_financing_price=price,
            pre_money_valuation=pre_money,
        )
        if notes:
            # conversion_event_date guaranteed non-None by the structural guard
            # at the top of solve_priced_round (returns early otherwise).
            note_shares, per_note = _note_shares_at_price(
                notes,
                conversion_event_date=note_conversion_date,
                priced_round_new_money=new_money,
                qualified_financing_price=price,
            )
        else:
            note_shares = 0.0
            per_note = {}

        # === Stage 3: size_round (Pool + NewMoney) ===
        # NewMoneyAdjuster: this iteration's INPUT PPS basis. The orchestrator's
        # post-loop block overwrites with the CONVERGED PPS basis.
        # Both are correct in their context.
        new_money_shares = new_money / price if price > 0 else 0.0
        pool_topup_shares = 0.0
        if target_pool_percent and target_pool_percent > 0:
            existing_unallocated = float(working_cap_state["option_pool"]["available_for_grant"])
            topup_result = required_topup(
                pre_topup_fully_diluted_shares=adj_pre_fd + safe_shares + note_shares,
                existing_unallocated_pool=existing_unallocated,
                target_pool_percent=target_pool_percent,
                new_money_shares=new_money_shares,
                target_basis=target_basis,
            )
            pool_topup_shares = float(topup_result["required_pool_topup_shares"])

        # Recompute PPS
        denom = adj_pre_fd + safe_shares + note_shares + pool_topup_shares
        if denom <= 0:
            break
        new_price = pre_money / denom

        # Update company_cap_estimate for the next iteration: adj_pre_fd + the
        # converting securities just computed. This is the YC post-money SAFE
        # "Company Capitalization" — it EXCLUDES new-money shares and the
        # in-connection pool top-up per the YC post-money SAFE definition
        # (rule `safe.company_capitalization_yc_post_money`).
        company_cap_estimate = adj_pre_fd + safe_shares + note_shares
        # Update pm_pre_money_fd_estimate for the next iteration: adj_pre_fd +
        # the in-connection pool top-up just computed. Per the YC pre-money SAFE
        # "Company Capitalization" clause, the pool increase in connection with
        # the equity financing IS included in the denominator for pre-money SAFEs.
        pm_pre_money_fd_estimate = adj_pre_fd + pool_topup_shares

        rel_change = abs(new_price - price) / max(price, 1e-12)
        abs_change = abs(new_price - price)
        history.append(new_price)
        prev_price = price
        price = new_price

        # === Convergence guards (per v3 §3.3) ===
        # Sign-flip detection → under-relaxation
        if not damping_engaged and _detect_sign_flip(history, SIGN_FLIP_DETECTION_WINDOW):
            damping_engaged = True
            price = SIGN_FLIP_DAMP_ALPHA * price + (1 - SIGN_FLIP_DAMP_ALPHA) * prev_price
            history[-1] = price

        # Aitken acceleration when contraction is slow
        if not aitken_engaged:
            f_est = _estimate_contraction(history)
            if f_est is not None and f_est > AITKEN_TRIGGER_CONTRACTION:
                projection = _aitken_projection(history)
                vanilla_step = abs(price - prev_price)
                if projection is not None and vanilla_step > 0:
                    aitken_step = abs(projection - price)
                    if aitken_step <= AITKEN_FALLBACK_STEP_RATIO * vanilla_step:
                        aitken_engaged = True
                        # Apply Aitken projection as the next-iter starting point
                        price = projection
                        history[-1] = price
                    elif not aitken_fallback_engaged:
                        # Fence tripped: projected step exceeds the 20× vanilla
                        # bound. Abort acceleration and revert to vanilla
                        # iteration; record + warn so the watchlist rule
                        # anti_dilution.solver_aitken_fallback_engaged can fire.
                        aitken_fallback_engaged = True
                        solver_warnings.append(
                            {
                                "code": "W_SOLVER_AITKEN_FALLBACK",
                                "detail": (
                                    "Aitken acceleration projected a step > 20× the vanilla "
                                    "step; reverted to unaccelerated fixed-point iteration."
                                ),
                            }
                        )

        # Termination
        if rel_change < convergence_threshold and abs_change < DEFAULT_ABS_THRESHOLD:
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

    # === Final pass at converged PPS ===
    if has_ad_protection:
        # Final AD pass to capture the breakdown at converged PPS
        ccp_mutations, ad_breakdown, ad_warnings = _apply_anti_dilution(
            preferred_series=preferred_series,
            cp1_snapshots=pre_financing_cp1_snapshots,
            new_pps=price,
            consideration=new_money,
            a_components=pre_financing_a_components,
            cap_table_history=working_cap_state.get("cap_table_history", []),
        )
        if ccp_mutations:
            for s in preferred_series:
                sid = s["series_id"]
                if sid in ccp_mutations:
                    s["current_conversion_price"] = ccp_mutations[sid]
            _refresh_as_converted_totals(working_cap_state)

    adj_pre_fd = float(working_cap_state["as_converted_totals"]["fully_diluted_shares"])
    safe_shares, per_safe = _safe_shares_at_price(
        safes,
        company_capitalization=company_cap_estimate,
        pre_money_fd=pm_pre_money_fd_estimate,
        equity_financing_price=price,
        pre_money_valuation=pre_money,
    )
    if notes:
        # conversion_event_date guaranteed non-None by the structural guard
        # at the top of solve_priced_round (returns early otherwise).
        note_shares, per_note = _note_shares_at_price(
            notes,
            conversion_event_date=note_conversion_date,
            priced_round_new_money=new_money,
            qualified_financing_price=price,
        )
    else:
        note_shares = 0.0
        per_note = {}

    # Post-loop NewMoneyAdjuster write: CONVERGED PPS basis. Overwrites the
    # last iter's input-PPS-basis value from line 657. This is the value that
    # flows into shares_breakdown and aggregate_ownership_by_class. See the
    # comment block at line 657 for the convention rationale.
    new_money_shares = new_money / price if price > 0 else 0.0
    pool_topup_shares = 0.0
    if target_pool_percent and target_pool_percent > 0:
        existing_unallocated = float(working_cap_state["option_pool"]["available_for_grant"])
        topup_result = required_topup(
            pre_topup_fully_diluted_shares=adj_pre_fd + safe_shares + note_shares,
            existing_unallocated_pool=existing_unallocated,
            target_pool_percent=target_pool_percent,
            new_money_shares=new_money_shares,
            target_basis=target_basis,
        )
        pool_topup_shares = float(topup_result["required_pool_topup_shares"])

    post_fd = adj_pre_fd + safe_shares + note_shares + pool_topup_shares + new_money_shares

    # Per-class aggregate ownership
    founders_shares = sum(int(f["common_shares"]) for f in working_cap_state["founders"])
    final_ats = working_cap_state["as_converted_totals"]
    preferred_as_conv = final_ats["preferred_shares_as_converted"]
    pool_total = final_ats["options_outstanding"] + final_ats["options_available"] + pool_topup_shares

    # Per-class founder breakdown as a map. Always emitted so downstream
    # consumers (compose_report, visualize, explore) have a stable shape
    # regardless of whether the engagement is dual-class. N-class
    # extensibility for engagements with class_c or beyond.
    founders_by_class: dict[str, float] = {}
    for f in working_cap_state["founders"]:
        cls = f.get("common_class") or "class_a"
        founders_by_class[cls] = founders_by_class.get(cls, 0.0) + (
            int(f["common_shares"]) / post_fd if post_fd else 0.0
        )

    aggregate: dict[str, Any] = {
        "founders_pct": founders_shares / post_fd if post_fd else 0.0,
        "founders_by_class": founders_by_class,
        "preferred_pct": preferred_as_conv / post_fd if post_fd else 0.0,
        "option_pool_pct": pool_total / post_fd if post_fd else 0.0,
        "safe_pct": safe_shares / post_fd if post_fd else 0.0,
        "note_pct": note_shares / post_fd if post_fd else 0.0,
        "new_money_pct": new_money_shares / post_fd if post_fd else 0.0,
    }

    # Pre-AD baseline (only meaningful when AD fired)
    if has_ad_protection and ad_breakdown:
        # pre_pps is the iteration-0 price estimate, not the converged PPS — the pre-AD baseline is an illustrative counterfactual, accurate to ~tenths of a pp.
        pre_ad_new_money_shares = new_money / pre_pps if pre_pps > 0 else 0.0
        # Reconstruct the pre-AD FD denominator from the SAME components the
        # post-AD post_fd uses (via final_ats) so the only difference is the
        # frozen pre-AD preferred-as-converted. final_ats["common_shares"]
        # already includes common_batches; warrants_underlying_total is included
        # in FD per §6.1. Omitting batches/warrants overstates the pre-AD
        # baseline and corrupts the headline AD delta.
        pre_ad_post_fd = (
            final_ats["common_shares"]
            + pre_ad_preferred_as_converted
            + final_ats["options_outstanding"]
            + final_ats["options_available"]
            + final_ats.get("warrants_underlying_total", 0)
            + pool_topup_shares
            + safe_shares
            + note_shares
            + pre_ad_new_money_shares
        )
        founder_pct_pre_ad = founders_shares / pre_ad_post_fd if pre_ad_post_fd > 0 else 0.0
        preferred_pct_pre_ad = pre_ad_preferred_as_converted / pre_ad_post_fd if pre_ad_post_fd > 0 else 0.0
        aggregate["founders_pct_pre_anti_dilution"] = founder_pct_pre_ad
        aggregate["preferred_pct_pre_anti_dilution"] = preferred_pct_pre_ad
        aggregate["anti_dilution_delta_pct_points"] = (aggregate["founders_pct"] - founder_pct_pre_ad) * 100

    # Post-convergence economic-validity guard.
    #
    # The fixed-point iteration terminates when |Δp/p| < 1e-6 AND |Δp| < 1e-9.
    # When instruments collectively demand ≥100% of the company (e.g. a post-money
    # SAFE whose purchase_amount exceeds its post_money_cap), the iteration drives
    # PPS toward zero.  At near-zero PPS both thresholds pass trivially (abs_change
    # is tiny because the price is tiny; rel_change divides by max(price,1e-12)).
    # The function then falsely reports converged=True / completeness="full" with
    # astronomically large share counts.
    #
    # Guard conditions (any one is sufficient):
    #   1. Converged PPS < PPS_SANITY_FLOOR — a price below a fraction of a cent
    #      across any realistic cap has no valid economic interpretation; it can only
    #      arise when the iteration collapsed toward zero.
    #   2. founders_pct ≤ 0 — the pre-existing shareholders have been completely
    #      displaced, which is algebraically impossible for a finite instrument set.
    #   3. Any ownership fraction outside (0, 1) — sanity check against negative
    #      or >100% individual-class fractions that indicate a degenerate solution.
    _fraction_fields = ("founders_pct", "preferred_pct", "safe_pct", "note_pct", "new_money_pct")
    _degenerate = (
        price < PPS_SANITY_FLOOR
        or aggregate["founders_pct"] <= 0.0
        or any(not (0.0 <= aggregate[k] <= 1.0) for k in _fraction_fields)
    )
    if _degenerate:
        converged = False
        blockers.append(
            {
                "code": "E_SOLVER_NO_VALID_FIXED_POINT",
                "instance_id": None,
                "remedy": (
                    "The round as specified has no valid economic solution: the instruments "
                    "and/or new money collectively demand ≥100% of the company (purchase "
                    "amounts exceed post-money caps, or combined cap fractions ≥ 1). "
                    "Verify that each SAFE's purchase_amount < post_money_cap and that the "
                    "aggregate SAFE fractions (Σ purchase_i/cap_i) leave room for founders "
                    "and new investors. Counsel or the cap-table model should be reviewed."
                ),
            }
        )

    # Determine scenario completeness — bucket rejected SAFEs by error code so
    # E_UNKNOWN_SAFE_FORM surfaces a clear blocker (not the generic fallback).
    rejected_safes = {s: r for s, r in per_safe.items() if r.get("branch") == "rejected"}
    if rejected_safes:
        # Group by error code; emit one blocker per code so each has a clear remedy.
        from collections import defaultdict  # noqa: PLC0415 (local import to avoid top-level dep)

        by_code: dict[str, list[str]] = defaultdict(list)
        for sid, rr in rejected_safes.items():
            by_code[rr.get("error", "E_SAFE_REQUIRES_CONVERSION_EVENT")].append(sid)
        for code, ids in by_code.items():
            if code == "E_UNKNOWN_SAFE_FORM":
                # Include the per-SAFE reason (first one) for the valid-forms hint.
                sample_reason = per_safe[ids[0]].get("reason", "")
                blockers.append(
                    {
                        "code": "E_UNKNOWN_SAFE_FORM",
                        "instance_id": ",".join(ids),
                        "remedy": sample_reason,
                    }
                )
            else:
                blockers.append(
                    {
                        "code": code,
                        "instance_id": ",".join(ids),
                        "remedy": "One or more SAFEs could not resolve to a conversion price; check forms + inputs.",
                    }
                )

    completeness = "full" if not blockers else "structural_only"

    result: dict[str, Any] = {
        "completeness": completeness,
        "blockers": blockers,
        "equity_financing_price": price,
        "iterations": iterations,
        "converged": converged,
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

    # Quantitative share-count fields are omitted when the economic-validity
    # guard fired: the computed values are degenerate (astronomically large)
    # and emitting them would propagate garbage to downstream consumers.
    # Callers should inspect completeness / blockers before reading share counts.
    if not _degenerate:
        result["post_round_fully_diluted_shares"] = int(round(post_fd))
        result["shares_breakdown"] = {
            "pre_round_fully_diluted": int(pre_fd),
            # AD ratcheting mutates CCP, inflating preferred-as-converted; this
            # is the delta between the pre-AD pre_fd and the AD-adjusted
            # adj_pre_fd. Without it the breakdown does not reconcile to
            # post_round_fully_diluted_shares whenever AD fires.
            "ad_delta": int(round(adj_pre_fd - pre_fd)),
            "safe_converted": int(round(safe_shares)),
            "note_converted": int(round(note_shares)),
            "pool_topup": int(round(pool_topup_shares)),
            "new_money": int(round(new_money_shares)),
        }
        result["aggregate_ownership_by_class"] = aggregate

    # Additive AD outputs (emitted whenever ≥1 series carries AD protection,
    # so callers can inspect CCP state regardless of whether AD triggered)
    if has_ad_protection:
        # CCP per series — reflects post-round state for downstream
        # cap_state_after_round.json. Unchanged from input if no AD triggered.
        result["ccp_mutations"] = {s["series_id"]: float(s["current_conversion_price"]) for s in preferred_series}
        if ad_breakdown:
            result["anti_dilution_breakdown"] = ad_breakdown
            for bd in ad_breakdown:
                result["math_provenance"].append(
                    {
                        "output_field": f"preferred_series.{bd['series_id']}.current_conversion_price",
                        "source_type": "rule",
                        "rule_id": bd["rule_id"],
                        "rule_pack_version": RULE_PACK_VERSION,
                        "source_ref": None,
                    }
                )
        if ad_warnings:
            result["warnings"] = ad_warnings

    # Convergence diagnostics (emitted when sign-flip damping or Aitken/fence engaged)
    if aitken_engaged or aitken_fallback_engaged or damping_engaged:
        result["convergence_diagnostics"] = {
            "aitken_engaged": aitken_engaged,
            "aitken_fallback_engaged": aitken_fallback_engaged,
            "damping_engaged": damping_engaged,
        }

    if solver_warnings:
        result.setdefault("warnings", [])
        result["warnings"].extend(solver_warnings)

    return result


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
    add_output_args(p)
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)

    result = solve_priced_round(
        cap_state=cap_state,
        safes=instruments.get("safes", []),
        notes=instruments.get("convertible_notes", []),
        pre_money=args.pre_money,
        new_money=args.new_money,
        target_pool_percent=args.target_pool_pct,
        target_basis=args.target_basis,
        conversion_event_date=args.conversion_date,
        max_iterations=args.max_iter,
        convergence_threshold=args.threshold,
    )
    emit(result, args, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
