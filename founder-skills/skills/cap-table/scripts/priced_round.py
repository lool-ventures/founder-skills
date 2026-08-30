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
import math
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
ACQUISITION_RULE_ID = "acquisition.consideration_shares"

# Bracketed-root-find fallback for acquisition deals near the feasibility fold.
# See docs/internal/2026-06-30-solver-convergence-hardening.md. Only the
# negotiated-% acquisition path uses these; non-acquisition deals are untouched.
#   * ACQ_GRID_POINTS — dense log-spaced grid over [floor, pre_money/pre_fd] on
#     which the 1-D residual F(PPS)=PPS-price_update(PPS) is scanned for a sign
#     change. No sign change anywhere ⇒ the deal is infeasible (no positive root).
#   * ACQ_BISECT_MAX_ITERS — hard cap on the hand-rolled bisection (no scipy: this
#     module's PEP-723 dependencies are []). ~50 iters already reaches machine
#     precision on the bracket; 100 is defensive so it can never hang.
#   * ACQ_INNER_MAX_ITERS — cap on the inner fixed-point that resolves the fast
#     couplings (SAFE company-capitalization, pool↔C) at a FIXED trial PPS. These
#     contract at rates independent of the outer PPS fold, so they converge in a
#     few tens of iters; the cap only guards a pathological input.
ACQ_GRID_POINTS = 512
ACQ_BISECT_MAX_ITERS = 100
# Backstop for the bounded `cc` iteration on the non-affine residual only
# (cap_plus_discount kink / pre-money-form SAFEs). The common post-money case is
# solved in closed form (affine `cc` + closed-form pool), so it never iterates.
ACQ_INNER_MAX_ITERS = 2000


def _acquisition_pool_C(
    *,
    pre_pool: float,
    nm: float,
    target: float,
    acq_t: float,
    existing: float,
    target_basis: str,
    pool_basis: str,
) -> tuple[float, float] | None:
    """Closed-form real-valued option-pool top-up `x` and acquisition consideration
    `C` at a FIXED equity-financing price.

    `pre_pool = adj_pre_fd + safe_shares + note_shares`; `nm = new_money/PPS`. The
    consideration is `C = (t/(1−t))·(pre_pool + x + nm)`; the pool top-up mirrors
    `option_pool.required_topup` on real (un-rounded) values. When the consideration
    sits in the pool denominator (`pool_basis="include"` AND a post-money-family
    `target_basis`) the two form a 2×2 linear system solved directly; otherwise the
    pool is independent of `C` and solved sequentially. Returns `(x, C)` with `x`
    clamped to `≥ 0`, or `None` when the system is infeasible (`det ≤ 0` or `C < 0`).
    The caller rounds via a single `required_topup` call for the final share counts.
    See design 2026-07-01 §D1.
    """
    a = target / (1.0 - target)
    b = acq_t / (1.0 - acq_t) if 0.0 < acq_t < 1.0 else 0.0
    base = pre_pool + nm
    post_money = target_basis in ("post_money", "post_money_excluding_converting_securities")
    if post_money and pool_basis == "include":
        det = 1.0 - a * b
        if det <= 0.0:
            return None
        r1 = a * base - existing / (1.0 - target)
        r2 = b * base
        x = (r1 + a * r2) / det
        C = (r2 + b * r1) / det
    elif post_money:  # exclude: consideration is not in the pool denominator
        x = a * base - existing / (1.0 - target)
        C = b * (base + x)
    else:  # pre_money / custom: pool numerator excludes nm and C entirely
        x = (target * pre_pool - existing) / (1.0 - target)
        C = b * (pre_pool + x + nm)
    if x < 0.0:
        # A negative computed top-up means the existing pool already meets target →
        # top-up 0; the include coupling collapses so C recomputes from x=0.
        x = 0.0
        C = b * base
    if C < 0.0:
        return None
    return x, C


def _affine_cc_solve(
    safe_total_fn: Any,
    adj: float,
    note: float,
    *,
    tol: float = 1e-6,
) -> float | None:
    """Solve the SAFE company-capitalization fixed point `cc = adj + note +
    safe_total(cc)` in closed form when `safe_total(cc)` is affine in `cc`.

    At a fixed PPS a pure post-money cap SAFE contributes `purchase·cc/cap` (∝ `cc`)
    and a discount / round-price SAFE contributes a `cc`-independent count, so
    `safe_total(cc) = m·cc + k`. Two evaluations recover `(m, k)` (reusing the real
    SAFE math as a black box — no branch re-implementation), giving the exact,
    rate-independent `cc* = (adj + note + k)/(1 − m)`. A third evaluation confirms
    affinity: if `safe_total(cc*) ≠ m·cc* + k` the map has a `cap_plus_discount`
    `min(cap,disc)` kink (or a pre-money-form pool coupling) and this returns None so
    the caller falls back to bounded iteration. Also returns None when `m ≥ 1` (cap
    SAFEs demand ≥100%) or the solution is non-positive / non-finite.
    See design 2026-07-01 §D2.
    """
    if adj <= 0.0:
        return None
    s0 = float(safe_total_fn(adj))
    s1 = float(safe_total_fn(2.0 * adj))
    m = (s1 - s0) / adj
    if not math.isfinite(m) or m >= 1.0:
        return None
    k = s0 - m * adj
    cc = (adj + note + k) / (1.0 - m)
    if not math.isfinite(cc) or cc <= 0.0:
        return None
    s2 = float(safe_total_fn(cc))
    if abs(s2 - (m * cc + k)) <= tol * max(1.0, cc):
        return cc
    return None


# Import sibling math producers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _artifact_io  # type: ignore[import-not-found]  # noqa: E402
from _emit import add_output_args, emit  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402
from anti_dilution import (  # noqa: E402
    bbwa_new_conversion_price,
    full_ratchet_new_conversion_price,
)
from note_conversion import convert_note, note_has_usable_math_inputs  # noqa: E402
from option_pool import required_topup  # noqa: E402
from safe_conversion import (  # noqa: E402
    PRE_MONEY_FORMS,
    convert_safe_priced_round,
    detect_mfn_cycles,
    safe_has_usable_purchase_amount,
)

# Absolute tolerance for anti-dilution price comparisons. Conversion prices are dollars-per-share
# in the 0.01--100 range, so a fixed epsilon is well-conditioned here; a relative one would make the
# ratchet-down post-condition weaker for cheap shares, which is exactly where a ratchet-up hides.
_AD_EPS = 1e-9


class AntiDilutionContradiction(ValueError):
    """An anti-dilution computation produced a result the domain forbids.

    Raised, not returned. This signals a PRODUCER DEFECT: the one contradictory-input case
    (`ad_cp2_floor` above CP1) is rejected at the solver entry point with a blocker, so anything
    reaching here is arithmetic the code should not have been able to produce. Crashing beats
    emitting numbers a founder would act on -- the defect this replaces shipped a silent
    W_CP2_FLOOR_APPLIED warning naming the symptom instead.
    """

    def __init__(self, code: str, message: str, *, series_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.series_id = series_id


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
            # Audit fields so the resolved election is visible in per_safe (cap_state can't
            # distinguish two scenarios that elect different siblings — see fix plan §3c).
            if anchor.get("post_money_valuation_cap") is not None:
                shadow["_mfn_inherited_cap"] = anchor.get("post_money_valuation_cap")
                shadow["_mfn_inherited_cap_type"] = "post_money"
            elif anchor.get("pre_money_valuation_cap") is not None:
                shadow["_mfn_inherited_cap"] = anchor.get("pre_money_valuation_cap")
                shadow["_mfn_inherited_cap_type"] = "pre_money"
            shadow["_mfn_inherited_discount"] = anchor.get("discount_multiplier")
            # The override pre-pass stamps "scenario_override"; default to "instrument" otherwise.
            shadow.setdefault("_mfn_election_source", "instrument")
            out[i] = shadow
            changed = True
        if not changed:
            break
    return out


def _apply_mfn_election_overrides(
    safes: list[dict[str, Any]], elections: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply scenario-level MFN election overrides onto a shadow copy of safes.

    `elections` is a map ``{electing_safe_id: elected_against_safe_id}`` carried on
    a scenario's ``parameters.mfn_elections``. For each entry the electing
    ``yc_uncapped_mfn`` SAFE's ``mfn_provision.elected_against_safe_id`` is set on a
    shadow record (the scenario override REPLACES any instrument-baked election), so
    the downstream ``_resolve_mfn_elections`` inherits the chosen sibling's terms.

    Returns ``(shadow_safes, blockers, warnings)`` and NEVER mutates the caller's
    records (the nested ``mfn_provision`` dict is copied before mutation — a bare
    ``dict(s)`` would share the original ref). A no-op (``None``/``{}``) returns the
    input list unchanged. Any other malformed shape, or a semantically invalid
    election, returns a structural blocker rather than crashing or silently ignoring.
    """
    if elections is None or elections == {}:
        return safes, [], []
    if not isinstance(elections, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in elections.items()
    ):
        return (
            safes,
            [
                {
                    "code": "E_MFN_ELECTIONS_BAD_SHAPE",
                    "instance_id": None,
                    "remedy": "mfn_elections must be a {electing_safe_id: elected_against_safe_id} "
                    "object with string keys and values.",
                }
            ],
            [],
        )
    by_id = {s.get("id"): s for s in safes}
    out = [dict(s) for s in safes]
    out_by_id = {s.get("id"): s for s in out}
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for electing_id, elected_id in elections.items():
        s = out_by_id.get(electing_id)
        if s is None:
            blockers.append(
                {
                    "code": "E_SAFE_MFN_ELECTION_UNKNOWN_SAFE",
                    "instance_id": electing_id,
                    "remedy": f"mfn_elections references unknown SAFE id {electing_id!r}.",
                }
            )
            continue
        if s.get("form") != "yc_uncapped_mfn":
            blockers.append(
                {
                    "code": "E_SAFE_MFN_ELECTION_NOT_MFN",
                    "instance_id": electing_id,
                    "remedy": f"mfn_elections set on {electing_id!r}, which is not a yc_uncapped_mfn SAFE.",
                }
            )
            continue
        if elected_id == electing_id or elected_id not in by_id:
            blockers.append(
                {
                    "code": "E_SAFE_MFN_ELECTION_BAD_TARGET",
                    "instance_id": electing_id,
                    "remedy": f"mfn election target {elected_id!r} is the SAFE itself or not a known SAFE id "
                    "(if filtered by safe_ids, the target must be in the active set).",
                }
            )
            continue
        mfn = dict(s.get("mfn_provision") or {})
        prior = mfn.get("elected_against_safe_id")
        mfn["elected_against_safe_id"] = elected_id
        mfn["elected"] = True
        s["mfn_provision"] = mfn
        s["_mfn_election_source"] = "scenario_override"
        if prior is not None and prior != elected_id:
            warnings.append(
                {
                    "code": "W_MFN_ELECTION_OVERRIDES_INSTRUMENT",
                    "instance_id": electing_id,
                    "detail": f"scenario election against {elected_id!r} overrides the instrument's "
                    f"baked election against {prior!r} (counterfactual).",
                }
            )
    return out, blockers, warnings


def _mfn_not_most_favorable_warnings(
    safes: list[dict[str, Any]], per_safe: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Post-solve check: flag any MFN-resolved SAFE that did NOT elect the most-favorable
    (lowest realized conversion price) sibling available to it.

    Must run after convergence because the effective price is
    ``min(cap_price, pps*discount, pps)`` — price-dependent. The candidate set for an
    MFN holder is every other resolved, non-`yc_uncapped_mfn`, non-rejected SAFE (each
    has a realized ``conversion_price`` in ``per_safe``). Under a real YC MFN the holder
    always takes most-favorable, so a non-most-favorable election is a counterfactual.
    """
    candidate_prices: dict[str, float] = {}
    for s in safes:
        sid = s.get("id")
        # Candidates are the real anchor siblings an MFN could elect — exclude unresolved
        # uncapped MFNs AND already-resolved MFN holders (their post-resolution form mirrors an
        # anchor, but they are not themselves an electable sibling).
        if sid is None or s.get("form") == "yc_uncapped_mfn" or s.get("_mfn_inherited_from"):
            continue
        entry = per_safe.get(sid) or {}
        if entry.get("branch") == "rejected":
            continue
        cp = entry.get("conversion_price")
        if cp is not None:
            candidate_prices[str(sid)] = float(cp)
    warnings: list[dict[str, Any]] = []
    for s in safes:
        elected = s.get("_mfn_inherited_from")
        if not elected:
            continue
        sid = s.get("id")
        if sid is None:
            continue
        elected_price = (per_safe.get(sid) or {}).get("conversion_price")
        others = {k: v for k, v in candidate_prices.items() if k != sid}
        if elected_price is None or not others:
            continue
        best = min(others.values())
        if float(elected_price) > best + 1e-9:
            warnings.append(
                {
                    "code": "W_MFN_NOT_MOST_FAVORABLE",
                    "instance_id": sid,
                    "detail": f"MFN SAFE {sid!r} elected {elected!r} (conversion price "
                    f"{float(elected_price):.6f}) but a more favorable sibling exists "
                    f"(best {best:.6f}). Real YC MFN would take the most-favorable terms; "
                    "treat this election as a counterfactual.",
                }
            )
    return warnings


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
    """Prior anti-dilution event for this series, via the SHARED predicate.

    Delegated rather than reimplemented. This module's copy and the cap-state builder's were two
    independent statements of one rule, free to drift -- and the solver-side stale-CCP warning that
    depends on it is gated behind three unrelated conditions, so a divergence here would have been
    invisible. Same reasoning as `rule_audit._derived_a_basis`, which was a third copy of a different
    derivation and had already gone wrong.
    """
    return bool(_artifact_io.series_has_prior_ad_event(series_id, cap_table_history))


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

        # `or`, not `.get(k, default)`. An explicitly-null value means "not specified", exactly like
        # an absent key -- the authoring skeleton writes `null` for every optional field a founder has
        # not filled in. The schemas were widened to accept that null and `cap_state.py` was fixed to
        # honour it, while this call site was not: a schema-VALID cap state then reached
        # `_compute_a_denominator(None)` and died with a raw ValueError. Widening a schema without
        # sweeping every consumer is how that happens.
        a_basis = series.get("ad_a_denominator_basis") or _default_a_basis(protection)
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

        # CP2 floor enforcement (per-series).
        #
        # A CHARTER FLOOR LIMITS HOW FAR CP2 MAY FALL. It is not a target and not a re-price, so a
        # floor above the CURRENT conversion price is a contradictory term, not a binding one --
        # clamping to it turns an anti-dilution protection into a conversion-price INCREASE. Rule
        # `anti_dilution.ratchet_down_only`; the sibling rule `anti_dilution.cp2_floor_applicable`
        # states the intent in the charter's own words ("CP2 cannot fall below OIP / 2").
        #
        # This was reachable with schema-valid founder input: `ad_cp2_floor` is typed
        # `["number","null"]` with no bound in either inputs.schema.json or cap_state.schema.json,
        # and cap_state.py copies it through unvalidated. A floor of 2.50 against a CP1 of 1.00
        # produced CP2 = 2.50, which `cap_state_after_round.py` then persisted as an
        # `anti_dilution_applied` event -- a record the repo's own loader rejects as
        # E_AD_RATCHET_UP_NOT_ALLOWED. The only signal was W_CP2_FLOOR_APPLIED, which names the
        # symptom ("clamped") rather than the cause, so nothing downstream could act on it.
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

        # POST-CONDITION, after the clamp because the clamp is what could violate it. Anti-dilution
        # adjusts DOWNWARD only (`anti_dilution.ratchet_down_only`). Belt-and-braces against the
        # rejection above: this catches any future path that produces a CP2 above CP1, not just the
        # floor one.
        if cp2 > cp1 + _AD_EPS:
            raise AntiDilutionContradiction(
                "E_AD_RATCHET_UP_NOT_ALLOWED",
                f"series {sid!r} computed CP2 {cp2:.6f} above CP1 {cp1:.6f}. Anti-dilution reduces "
                "the conversion price; an adjustment that raises it is not a protection "
                "(anti_dilution.ratchet_down_only). Reaching this means a producer defect, not bad "
                "input -- the contradictory-floor case is rejected at the entry point.",
                series_id=sid,
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
        for _mfn_key in (
            "_mfn_inherited_from",
            "_mfn_election_source",
            "_mfn_inherited_cap",
            "_mfn_inherited_cap_type",
            "_mfn_inherited_discount",
        ):
            if s.get(_mfn_key) is not None:
                r[_mfn_key] = s[_mfn_key]
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


def _duplicate_id_blockers(safes: list[dict[str, Any]], notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Refuse instrument sets whose ids collapse the per-instrument output.

    Separate from a schema `uniqueItems` because nothing upstream enforces one: the instruments
    schema declares no uniqueness, `cap_state` does not dedupe, and the extraction-lane guard covers
    only its own lane -- so a hand-authored or freeform-mapped instruments.json reaches the solver
    directly.

    A MISSING id is reported as its own defect rather than folded in as a duplicate of `None`. They
    need different fixes ("give it an id" vs "make the ids distinct"), and two id-less SAFEs are not
    two SAFEs with the same id -- reporting the founder a duplicated id of `None` names a value that
    appears nowhere in their documents.
    """
    out: list[dict[str, Any]] = []
    for label, items in (("safes", safes), ("convertible_notes", notes)):
        missing = sum(1 for i in items if i.get("id") in (None, ""))
        if missing:
            out.append(
                {
                    "code": "E_INSTRUMENT_ID_MISSING",
                    "instance_id": None,
                    "remedy": (
                        f"{missing} of {len(items)} {label} carry no id. Ids key the per-instrument "
                        "output, so an instrument without one cannot be reported separately from the "
                        "others. Give each one a distinct id."
                    ),
                }
            )
        ids = [i.get("id") for i in items if i.get("id") not in (None, "")]
        dupes = sorted({str(i) for i in ids if ids.count(i) > 1})
        if dupes:
            out.append(
                {
                    "code": "E_INSTRUMENT_DUPLICATE_ID",
                    "instance_id": ",".join(dupes),
                    "remedy": (
                        f"{len(items)} {label} carry {len(dupes)} duplicated id(s): {', '.join(dupes)}. "
                        "Ids key the per-instrument output, so a repeat would show one row for two "
                        "instruments while both count toward the totals -- the summary and the detail "
                        "would disagree. Give each one a distinct id."
                    ),
                }
            )
    return out


def solve_priced_round(
    *,
    cap_state: dict[str, Any],
    safes: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    pre_money: float,
    new_money: float,
    target_pool_percent: float | None = None,
    target_basis: str = "pre_money",
    pre_money_basis: str = "includes_safe_conversion",
    acquisition: dict[str, Any] | None = None,
    pool_consideration_basis: str = "include",
    conversion_event_date: str | None = None,
    mfn_elections: dict[str, Any] | None = None,
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
    # Terms-only SAFEs (no usable purchase amount, e.g. a blank template) cannot convert — exclude them
    # from the coupled solve so a degraded SAFE never reaches s["purchase_amount"]. Single chokepoint for
    # all priced callers (orchestrator priced scenario, cap-implied delegate, and the CLI).
    safes = [s for s in safes if safe_has_usable_purchase_amount(s)]

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
            "math_provenance": [],
        }

    # Terms-only notes (null principal / missing issuance_date, e.g. a blank Note template whose
    # amount lives in a Schedule of Lenders) cannot convert — exclude them so a partial note never
    # reaches note_conversion math (crash). Placed AFTER the no-date structural check so a date-less
    # partial still yields the E_NOTE_NO_CONVERSION_DATE blocker. Same chokepoint
    # role as the SAFE filter; covers quick_assess, which calls solve_priced_round directly.
    notes = [n for n in notes if note_has_usable_math_inputs(n)]

    # After the guard above, conversion_event_date is non-None whenever notes
    # are present. Narrow to a non-Optional local for the note-conversion calls
    # (the bare assert is avoided so -O cannot strip note conversions).
    note_conversion_date: str = conversion_event_date or ""

    # Scenario-level MFN election overrides (parameters.mfn_elections) — apply BEFORE
    # structural resolution so the elected sibling's terms are the ones inherited.
    # The structural override-conflict warning is held here and merged into
    # solver_warnings once that list exists (W_MFN_NOT_MOST_FAVORABLE is computed
    # later, post-convergence, since it is price-dependent).
    safes, _mfn_override_blockers, _mfn_override_warnings = _apply_mfn_election_overrides(safes, mfn_elections)
    if _mfn_override_blockers:
        return {
            "completeness": "structural_only",
            "blockers": _mfn_override_blockers,
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }

    # DUPLICATE INSTRUMENT IDS MUST BE REFUSED HERE TOO, AND THIS PATH IS THE WORSE ONE.
    # `_safe_shares_at_price` / `_note_shares_at_price` build `per_safe`/`per_note` keyed by id, so
    # two instruments sharing one leave a single row. The DENOMINATOR is unaffected — `total`
    # accumulates per iteration, so both are counted — which is exactly what makes it dangerous:
    # measured, two identical SAFEs produced `safe_pct` 16% in the aggregate beside ONE per-instrument
    # row carrying half of it, `completeness: "full"`, zero blockers. The founder reconciles the
    # summary against the detail and the detail is missing an instrument.
    #
    # The cap-implied path refuses the same shape (`convert_safes_cap_implied`) and at least reported
    # `structural_only`; this path reported `full`. Fixing one and not the other left the more
    # confident of the two lying.
    _dupe_blockers = _duplicate_id_blockers(safes, notes)
    if _dupe_blockers:
        return {
            "completeness": "structural_only",
            "blockers": _dupe_blockers,
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }

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
            "math_provenance": [],
        }

    pre_fd = float(working_cap_state["as_converted_totals"]["fully_diluted_shares"])

    if pre_fd <= 0:
        blockers.append(
            {
                "code": "E_SCENARIO_NO_PRE_FD",
                "instance_id": None,
                "remedy": "the cap table has no shares in it -- founder holdings, preferred series or the option pool "
                "must be filled in before a round can be modelled",
            }
        )
        return {
            "completeness": "structural_only",
            "blockers": blockers,
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }

    # D0 — option-pool target domain guard. `required_topup` rejects
    # target ∉ (0,1) with a ValueError; the acquisition closed-form pool (D1)
    # bypasses that check, and only the include+post_money branch is otherwise
    # backstopped (by E_ACQUISITION_POOL_OVERDETERMINED). Guard here so an
    # out-of-range target is a typed blocker on every path/basis rather than a
    # silent nonsense result or an uncaught crash. Truthiness — a legitimate
    # explicit target_pool_percent == 0.0 is a valid no-pool deal.
    if target_pool_percent and not (0.0 < float(target_pool_percent) < 1.0):
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_POOL_TARGET_OUT_OF_RANGE",
                    "instance_id": None,
                    "remedy": (
                        f"target_pool_percent must be a fraction in (0, 1); got {target_pool_percent}. "
                        f"Express the option-pool target as e.g. 0.10 for 10%."
                    ),
                }
            ],
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
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

    # A CP2 floor ABOVE the CURRENT conversion price is a contradictory charter term: clamping to it
    # would RAISE the conversion price, and anti-dilution only ever lowers it
    # (`anti_dilution.ratchet_down_only`). Strictly above, matching the check below and the rule's own
    # wording ("greater than the current conversion price"). A floor EQUAL to CP1 is a different case
    # and is deliberately allowed: it clamps CP2 back to exactly CP1, so no ratchet-up occurs and no
    # event is written. `test_golden_10c` pins that boundary from the permissive side -- tightening
    # this to `>=` to match a looser comment would break it.
    # Rejected here, loudly, rather than clamped: the clamp below
    # is what silently produced a ratchet-UP, recorded as an `anti_dilution_applied` event that the
    # repo's own loader rejects. Validated at the entry point so the per-series math can treat the
    # ratchet-down post-condition as an invariant rather than an input check.
    if has_ad_protection:
        for _s in preferred_series:
            if _s.get("anti_dilution_protection", "none") == "none":
                continue
            _floor = _s.get("ad_cp2_floor")
            if _floor is None:
                continue
            _cp1 = pre_financing_cp1_snapshots[_s["series_id"]]
            if float(_floor) > _cp1 + _AD_EPS:
                blockers.append(
                    {
                        "code": "E_AD_CP2_FLOOR_ABOVE_CURRENT_PRICE",
                        "instance_id": _s["series_id"],
                        "rule_id": "anti_dilution.ratchet_down_only",
                        "rule_pack_version": RULE_PACK_VERSION,
                        "remedy": (
                            f"ad_cp2_floor for {_s['series_id']!r} is {float(_floor):.6f}, above its current "
                            f"conversion price of {_cp1:.6f}. A floor above the current price would RAISE the "
                            "conversion price, which is dilution, not protection. Check the charter: the floor "
                            "is usually the original issue price of an EARLIER series, or the term does not apply."
                        ),
                    }
                )
        if blockers:
            return {
                "completeness": "structural_only",
                "blockers": blockers,
                "per_safe": {},
                "per_note": {},
                "math_provenance": [],
            }

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
    solver_warnings: list[dict[str, Any]] = []
    # Structural MFN override-conflict warnings collected pre-solve; merged here so
    # they survive the AD direct-assign at result["warnings"] below and reach the sink.
    solver_warnings.extend(_mfn_override_warnings)

    # Initialize per-iter outputs (used in convergence-loop scope). The per-SAFE /
    # per-note maps and the AD breakdown are recomputed by the final-assembly helper
    # (_finalize) at the converged/bracketed PPS, so the loop discards them.
    safe_shares: float = 0.0
    note_shares: float = 0.0
    new_money_shares: float = 0.0
    pool_topup_shares: float = 0.0
    acquisition_shares: float = 0.0

    acq_t = float(acquisition["consideration_pct"]) if acquisition else 0.0
    k_factor = 1.0 + (new_money / pre_money if pre_money else 0.0)
    # Defensive: the router never passes BOTH a concurrent `acquisition` kwarg AND a pre-folded
    # cap_state (pre_round_closed), but guard against a direct caller doing so (would double-count C).
    if (
        acquisition
        and float(working_cap_state["as_converted_totals"].get("acquisition_consideration_shares", 0) or 0) > 0
    ):
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_ACQUISITION_DOUBLE_SPECIFIED",
                    "instance_id": None,
                    "remedy": "Both a concurrent acquisition kwarg and a pre-folded cap_state acquisition "
                    "block are present; pass exactly one (concurrent → kwarg; pre_round_closed → cap_state).",
                }
            ],
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }
    if acquisition and acq_t * k_factor >= 1.0:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_ACQUISITION_OVERDETERMINED",
                    "instance_id": None,
                    "remedy": (
                        f"Acquisition consideration is over-determined: t·k = {acq_t * k_factor:.3f} ≥ 1 "
                        f"(t={acq_t}, k=1+new_money/pre_money={k_factor:.3f}). The negotiated % cannot be "
                        f"satisfied at this new-money level; reduce consideration_pct or new_money."
                    ),
                }
            ],
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }

    # 2×2 pool/C singularity: the acquisition consideration C sits in the pool
    # denominator, so the pool top-up x and C form a linear system with
    # det = 1 − a·b (a=target/(1−target), b=t/(1−t)). det ≤ 0 ⟺ t+target ≥ 1 (the
    # acquirer and the pool alone demand ≥100%). This coupling exists ONLY when C is
    # actually in the pool denominator — i.e. pool_consideration_basis="include" AND
    # a post-money-family target_basis (required_topup folds the consideration into
    # the post_money / post_money_excluding_converting_securities denominators only;
    # the pre_money / custom formulas ignore it, so there is no singularity and this
    # guard must NOT fire for them). Distinct from the t·k≥1 overdetermination — its
    # remedy is "reduce the pool target", not "reduce new_money". See §5 of the
    # solver-convergence-hardening design.
    if (
        acquisition
        and target_pool_percent
        and float(target_pool_percent) > 0
        and pool_consideration_basis == "include"
        and target_basis in {"post_money", "post_money_excluding_converting_securities"}
        and (acq_t + float(target_pool_percent)) >= 1.0
    ):
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_ACQUISITION_POOL_OVERDETERMINED",
                    "instance_id": None,
                    "remedy": (
                        f"Acquisition consideration and the option pool are jointly over-determined: "
                        f"t + pool_target = {acq_t + float(target_pool_percent):.3f} ≥ 1 "
                        f"(t={acq_t}, pool_target={float(target_pool_percent)}). With the consideration in the "
                        f"pool denominator (pool_consideration_basis='include') the two demand ≥100% of the "
                        f"company; reduce consideration_pct or the pool target."
                    ),
                }
            ],
            "per_safe": {},
            "per_note": {},
            "math_provenance": [],
        }

    # Cap-SAFE singularity: a post-money cap SAFE's converted share count solves
    # safe = purchase·company_capitalization/cap, i.e. company_capitalization =
    # base/(1 − Σ purchase_i/cap_i). Σ purchase_i/cap_i ≥ 1 ⇒ no finite share
    # count (the cap SAFEs alone demand ≥100%). Only pure `yc_postmoney_cap` forms
    # are PPS-independent here; cap_plus_discount is branch-dependent and left to
    # the inner solve. Scoped to acquisition deals (the fallback's domain).
    if acquisition:
        _cap_q = 0.0
        for s in safes:
            if s.get("form") == "yc_postmoney_cap":
                cap = s.get("post_money_valuation_cap")
                if cap and float(cap) > 0:
                    _cap_q += float(s["purchase_amount"]) / float(cap)
        if _cap_q >= 1.0:
            return {
                "completeness": "structural_only",
                "blockers": [
                    {
                        "code": "E_ACQUISITION_CAP_SAFE_OVERDETERMINED",
                        "instance_id": None,
                        "remedy": (
                            f"The post-money cap SAFEs are over-determined: Σ purchase/cap = {_cap_q:.3f} ≥ 1. "
                            f"Their converted shares have no finite fixed point (the cap SAFEs alone demand "
                            f"≥100% of the company). Verify each SAFE's purchase_amount < post_money_valuation_cap."
                        ),
                    }
                ],
                "per_safe": {},
                "per_note": {},
                "math_provenance": [],
            }

    converged = False
    for i in range(max_iterations):
        iterations = i + 1

        # === Stage 1: adjust_cap_state (AntiDilutionAdjuster) ===
        # The breakdown/warnings are recomputed by _finalize at the converged PPS, so
        # the loop only needs the CCP mutations to drive as-converted totals.
        if has_ad_protection:
            ccp_mutations, _, _ = _apply_anti_dilution(
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
        safe_shares, _ = _safe_shares_at_price(
            safes,
            company_capitalization=company_cap_estimate,
            pre_money_fd=pm_pre_money_fd_estimate,
            equity_financing_price=price,
            pre_money_valuation=pre_money,
        )
        if notes:
            # conversion_event_date guaranteed non-None by the structural guard
            # at the top of solve_priced_round (returns early otherwise).
            note_shares, _ = _note_shares_at_price(
                notes,
                conversion_event_date=note_conversion_date,
                priced_round_new_money=new_money,
                qualified_financing_price=price,
            )
        else:
            note_shares = 0.0

        # === Stage 3: size_round (Pool + NewMoney) ===
        # NewMoneyAdjuster: this iteration's INPUT PPS basis. The orchestrator's
        # post-loop block overwrites with the CONVERGED PPS basis.
        # Both are correct in their context.
        new_money_shares = new_money / price if price > 0 else 0.0
        prev_pool_topup = pool_topup_shares  # capture before reset; used for acquisition_shares recompute
        pool_topup_shares = 0.0
        if acquisition:
            _pfx = adj_pre_fd + safe_shares + note_shares + prev_pool_topup + (new_money / price if price > 0 else 0.0)
            acquisition_shares = (acq_t / (1.0 - acq_t)) * _pfx if 0.0 < acq_t < 1.0 else 0.0
        if target_pool_percent and target_pool_percent > 0:
            existing_unallocated = float(working_cap_state["option_pool"]["available_for_grant"])
            _acq_for_pool = acquisition_shares if (acquisition and pool_consideration_basis == "include") else 0.0
            topup_result = required_topup(
                pre_topup_fully_diluted_shares=adj_pre_fd + safe_shares + note_shares,
                existing_unallocated_pool=existing_unallocated,
                target_pool_percent=target_pool_percent,
                new_money_shares=new_money_shares,
                target_basis=target_basis,
                acquisition_shares=_acq_for_pool,
            )
            pool_topup_shares = float(topup_result["required_pool_topup_shares"])

        # Recompute PPS
        _safe_in_denom = safe_shares if pre_money_basis == "includes_safe_conversion" else 0.0
        denom = adj_pre_fd + _safe_in_denom + note_shares + pool_topup_shares
        if denom <= 0:
            break
        if acquisition:
            # Per-iteration acquisition price-update rule (design spec §3.3a). The two basis
            # forms have DIFFERENT numerators — the safe coefficient is 1 (includes) vs t (excludes):
            #   includes: D = (pre_FD + safe + note + pool) / (1 - t*k)
            #   excludes: D = (pre_FD + t*safe + note + pool) / (1 - t*k)
            if pre_money_basis == "includes_safe_conversion":
                acq_numerator = adj_pre_fd + safe_shares + note_shares + pool_topup_shares
            else:
                acq_numerator = adj_pre_fd + acq_t * safe_shares + note_shares + pool_topup_shares
            d_acq = acq_numerator / (1.0 - acq_t * k_factor)
            if d_acq <= 0:
                break
            new_price = pre_money / d_acq
        else:
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

    # ========================================================================
    # Acquisition bracketed-root-find fallback (design 2026-06-30)
    # ========================================================================
    # The negotiated-% acquisition path has a narrow feasible-but-slow band just
    # inside the pool-adjusted feasibility fold where the fixed-point iteration
    # contracts too slowly to finish within max_iterations and false-fails. These
    # nested helpers replicate the main loop's price update as a pure function of a
    # trial PPS (the slow inter-iteration coupling is through PPS; the inner
    # couplings — SAFE company-capitalization, pool↔C, AD — are resolved to a fixed
    # point at each trial PPS, where they contract fast) and bracket-solve the 1-D
    # residual F(PPS) = PPS − price_update(PPS). Only acquisition deals ever enter
    # this path, so every other deal type is bit-for-bit unchanged.

    def _resolve_at_pps(trial_price: float) -> dict[str, Any]:
        """One fully-inner-converged price update at a FIXED trial PPS.

        Returns {feasible, new_price, cc, pm} where new_price is the price update
        evaluated with the SAFE/pool/C/AD couplings resolved (closed-form pool + affine
        cc, or bounded iteration for the non-affine residual). On failure returns
        {feasible: False, reason} where reason is "no_root" (degenerate denominator —
        genuinely no positive resolution) or "nonconvergent" (the residual iteration
        exhausted its cap — indeterminate, → counsel review, not a hard infeasibility).
        """
        if trial_price <= 0.0:
            return {"feasible": False, "reason": "no_root"}
        # Stage 1: AD at this trial PPS. Reset each protected series' working CCP to
        # its frozen cp1 snapshot BEFORE re-applying so every evaluation is a pure
        # function of trial_price (out-of-order grid/bisection evals can't inherit a
        # stale cp2 from a prior evaluation). Scoped to the fallback only — the main
        # loop stays monotone. _refresh_as_converted_totals telescopes, so this is
        # idempotent across evaluations.
        if has_ad_protection:
            for s in preferred_series:
                s["current_conversion_price"] = pre_financing_cp1_snapshots[s["series_id"]]
            _refresh_as_converted_totals(working_cap_state)
            _ccp_mut, _bd, _w = _apply_anti_dilution(
                preferred_series=preferred_series,
                cp1_snapshots=pre_financing_cp1_snapshots,
                new_pps=trial_price,
                consideration=new_money,
                a_components=pre_financing_a_components,
                cap_table_history=working_cap_state.get("cap_table_history", []),
            )
            if _ccp_mut:
                for s in preferred_series:
                    if s["series_id"] in _ccp_mut:
                        s["current_conversion_price"] = _ccp_mut[s["series_id"]]
                _refresh_as_converted_totals(working_cap_state)
        adj = float(working_cap_state["as_converted_totals"]["fully_diluted_shares"])
        nm = new_money / trial_price
        if notes:
            note_sh, _pn = _note_shares_at_price(
                notes,
                conversion_event_date=note_conversion_date,
                priced_round_new_money=new_money,
                qualified_financing_price=trial_price,
            )
        else:
            note_sh = 0.0
        existing_pool = float(working_cap_state["option_pool"]["available_for_grant"])
        tpp = float(target_pool_percent) if (target_pool_percent and target_pool_percent > 0) else 0.0

        def _finish(safe_sh: float) -> tuple[float, float, float] | None:
            """Closed-form pool/C + price update given a resolved safe-share count.
            Returns (x, C, new_price) or None on a degenerate denominator (no_root)."""
            if tpp > 0:
                res = _acquisition_pool_C(
                    pre_pool=adj + safe_sh + note_sh,
                    nm=nm,
                    target=tpp,
                    acq_t=acq_t,
                    existing=existing_pool,
                    target_basis=target_basis,
                    pool_basis=pool_consideration_basis,
                )
                if res is None:
                    return None
                x, cval = res
            else:
                x = 0.0
                cval = (acq_t / (1.0 - acq_t)) * (adj + safe_sh + note_sh + nm) if 0.0 < acq_t < 1.0 else 0.0
            _safe_denom = safe_sh if pre_money_basis == "includes_safe_conversion" else 0.0
            if adj + _safe_denom + note_sh + x <= 0:
                return None
            if pre_money_basis == "includes_safe_conversion":
                acq_num = adj + safe_sh + note_sh + x
            else:
                acq_num = adj + acq_t * safe_sh + note_sh + x
            d_acq = acq_num / (1.0 - acq_t * k_factor)
            if d_acq <= 0:
                return None
            return x, cval, pre_money / d_acq

        # Fast path — closed-form scalar `cc` when `safe_total(cc)` is affine. Valid
        # only when no pre-money SAFE form is present (those read pre_money_fd=pm,
        # which couples cc↔pool). pm is irrelevant to post-money forms, so probe with
        # pm=adj. The affinity check inside _affine_cc_solve rejects a cap_plus_discount
        # kink and this falls through to the bounded iteration below.
        if not any(s.get("form") in PRE_MONEY_FORMS for s in safes):

            def _safe_total(cc_val: float) -> float:
                s, _ = _safe_shares_at_price(
                    safes,
                    company_capitalization=cc_val,
                    pre_money_fd=adj,
                    equity_financing_price=trial_price,
                    pre_money_valuation=pre_money,
                )
                return s

            cc_star = _affine_cc_solve(_safe_total, adj, note_sh)
            if cc_star is not None:
                safe_sh = _safe_total(cc_star)
                fin = _finish(safe_sh)
                if fin is None:
                    return {"feasible": False, "reason": "no_root"}
                x, _c, new_price = fin
                return {"feasible": True, "new_price": new_price, "cc": adj + safe_sh + note_sh, "pm": adj + x}

        # Residual — bounded `cc` iteration for the non-affine cases (cap_plus_discount
        # kink, pre-money-form pool coupling). Pool/C is still closed-form each pass.
        cc = adj
        pm = adj
        prev_np: float | None = None
        for _ in range(ACQ_INNER_MAX_ITERS):
            safe_sh, _ps = _safe_shares_at_price(
                safes,
                company_capitalization=cc,
                pre_money_fd=pm,
                equity_financing_price=trial_price,
                pre_money_valuation=pre_money,
            )
            fin = _finish(safe_sh)
            if fin is None:
                return {"feasible": False, "reason": "no_root"}
            x, _c, new_price = fin
            cc = adj + safe_sh + note_sh
            pm = adj + x
            if prev_np is not None and abs(new_price - prev_np) <= 1e-12 * max(1.0, abs(new_price)):
                return {"feasible": True, "new_price": new_price, "cc": cc, "pm": pm}
            prev_np = new_price
        return {"feasible": False, "reason": "nonconvergent"}

    def _acq_infeasible_remedy() -> str:
        if target_pool_percent and target_pool_percent > 0:
            return (
                "The acquisition round has no positive economic root at this new-money level: with the "
                "negotiated consideration % AND the option-pool top-up both feeding the post-money "
                "denominator, the deal is past its feasibility fold (t·k is below 1 but above the "
                "pool-adjusted limit ~0.83). Reduce new_money, consideration_pct, or the pool target."
            )
        return (
            "The acquisition round has no positive economic root at this new-money level: the negotiated "
            "consideration % cannot be satisfied against the converting instruments (past the feasibility "
            "fold). Reduce new_money or consideration_pct."
        )

    def _bracketed_solve() -> tuple[Any, ...]:
        """Grid-scan F(PPS) on [floor, pre_money/pre_fd]; bisect the LARGEST (highest
        -PPS) sign-changed sub-bracket = the stable root the fast path lands on.

        Returns ("ok", root) — and commits company_cap_estimate / pm_pre_money_fd_
        estimate + working_cap_state to the root — or ("infeasible", code, remedy)
        when F never crosses zero (no positive root)."""
        nonlocal company_cap_estimate, pm_pre_money_fd_estimate
        remedy = _acq_infeasible_remedy()
        # D3: an all-indeterminate scan (the residual iteration exhausted its cap at
        # every point — only reachable for the exotic non-affine cap_plus_discount /
        # pre-money residual) is relabeled "could not resolve near a singularity;
        # counsel review" rather than a hard infeasibility. saw_nonconvergent is a
        # clean global signal because the residual rate is PPS-independent.
        saw_nonconvergent = False

        def _no_bracket() -> tuple[Any, ...]:
            if saw_nonconvergent:
                return (
                    "infeasible",
                    "E_ACQUISITION_SOLVER_NONCONVERGENT",
                    "The acquisition round's inner sub-solve did not converge near a cap/pool "
                    "near-singularity (a cap_plus_discount SAFE at its kink, or a legacy pre-money "
                    "SAFE with a pool refresh). The economics are marginal; counsel should review "
                    "the conversion mechanics rather than treat this as a clean infeasibility.",
                )
            return ("infeasible", "E_ACQUISITION_INFEASIBLE", remedy)

        hi = pre_money / pre_fd  # frozen, un-AD pre_fd (the AD-inflated adj_pre_fd is circular)
        lo = PPS_SANITY_FLOOR
        if not (hi > lo):
            return _no_bracket()
        ratio = hi / lo
        n = ACQ_GRID_POINTS
        fvals: list[tuple[float, float | None]] = []
        for i in range(n):
            p = lo * (ratio ** (i / (n - 1)))
            res = _resolve_at_pps(p)
            if res.get("reason") == "nonconvergent":
                saw_nonconvergent = True
            fvals.append((p, (p - res["new_price"]) if res.get("feasible") else None))
        # Largest-PPS negative→positive crossing (F' > 0 there = the stable attractor;
        # the fast path initialises at hi and descends onto it). Scanning low→high and
        # keeping the last such bracket yields the highest-PPS crossing.
        bracket: tuple[float, float] | None = None
        for i in range(n - 1):
            _p0, f0 = fvals[i]
            _p1, f1 = fvals[i + 1]
            if f0 is None or f1 is None:
                continue
            if f0 <= 0.0 and f1 > 0.0:
                bracket = (_p0, _p1)
        if bracket is None:
            return _no_bracket()
        a, b = bracket
        _ra = _resolve_at_pps(a)
        fa = a - _ra["new_price"]
        root = 0.5 * (a + b)
        for _ in range(ACQ_BISECT_MAX_ITERS):
            m = 0.5 * (a + b)
            rm = _resolve_at_pps(m)
            if not rm.get("feasible"):
                break
            fm = m - rm["new_price"]
            root = m
            if fm == 0.0 or (b - a) <= 1e-12 * max(1.0, m):
                break
            if (fa < 0.0) == (fm < 0.0):
                a, fa = m, fm
            else:
                b = m
        # Commit: leave working_cap_state (AD/totals) and the lagged denominators at
        # the root so the shared final assembly recomputes consistently.
        final = _resolve_at_pps(root)
        if not final.get("feasible"):
            if final.get("reason") == "nonconvergent":
                saw_nonconvergent = True
            return _no_bracket()
        company_cap_estimate = float(final["cc"])
        pm_pre_money_fd_estimate = float(final["pm"])
        return ("ok", root)

    def _finalize(
        fin_price: float,
        *,
        fin_converged: bool,
        bracketed: bool,
        seed_blockers: list[dict[str, Any]],
        acq_infeasible: bool,
    ) -> dict[str, Any]:
        """Assemble the result at fin_price. `bracketed` carves out the founders%≤0
        rejection (the fold band is defined by founders%→0). `acq_infeasible` omits
        quantitative fields without appending the generic NO_VALID_FIXED_POINT (the
        caller has seeded a typed E_ACQUISITION_INFEASIBLE)."""
        fin_blockers: list[dict[str, Any]] = list(seed_blockers)
        fin_warnings: list[dict[str, Any]] = list(solver_warnings)
        ad_breakdown: list[dict[str, Any]] = []
        ad_warnings: list[dict[str, Any]] = []

        # === Final pass at fin_price ===
        if has_ad_protection:
            ccp_mutations, ad_breakdown, ad_warnings = _apply_anti_dilution(
                preferred_series=preferred_series,
                cp1_snapshots=pre_financing_cp1_snapshots,
                new_pps=fin_price,
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
            equity_financing_price=fin_price,
            pre_money_valuation=pre_money,
        )
        # W_MFN_NOT_MOST_FAVORABLE is price-dependent (effective price = min(cap, pps*disc, pps)),
        # so it can only be computed AFTER convergence, from the realized per_safe prices.
        fin_warnings.extend(_mfn_not_most_favorable_warnings(safes, per_safe))
        if notes:
            note_shares, per_note = _note_shares_at_price(
                notes,
                conversion_event_date=note_conversion_date,
                priced_round_new_money=new_money,
                qualified_financing_price=fin_price,
            )
        else:
            note_shares = 0.0
            per_note = {}

        # Post-loop NewMoneyAdjuster write: CONVERGED PPS basis. The pool top-up and
        # the acquisition consideration C couple only when pool_consideration_basis is
        # "include" (C sits in the pool denominator). Resolve C in CLOSED FORM
        # (rate-independent — the iterative version under-converged the reported
        # numbers at high a·b), then a SINGLE required_topup call gives the int-rounded
        # pool + its warnings. Non-acquisition / exclude / no-pool are single-pass.
        new_money_shares = new_money / fin_price if fin_price > 0 else 0.0
        pool_topup_shares = 0.0
        acquisition_shares = 0.0
        _tpp = float(target_pool_percent) if (target_pool_percent and target_pool_percent > 0) else 0.0
        if _tpp > 0:
            existing_unallocated = float(working_cap_state["option_pool"]["available_for_grant"])
            _c_for_pool = 0.0
            if acquisition and pool_consideration_basis == "include":
                _res = _acquisition_pool_C(
                    pre_pool=adj_pre_fd + safe_shares + note_shares,
                    nm=new_money_shares,
                    target=_tpp,
                    acq_t=acq_t,
                    existing=existing_unallocated,
                    target_basis=target_basis,
                    pool_basis="include",
                )
                if _res is not None:
                    _c_for_pool = _res[1]
            topup_result = required_topup(
                pre_topup_fully_diluted_shares=adj_pre_fd + safe_shares + note_shares,
                existing_unallocated_pool=existing_unallocated,
                target_pool_percent=_tpp,
                new_money_shares=new_money_shares,
                target_basis=target_basis,
                acquisition_shares=_c_for_pool,
            )
            pool_topup_shares = float(topup_result["required_pool_topup_shares"])
        if acquisition:
            # post_FD must satisfy C = t * post_FD ; solve with the converged pool.
            post_fd_excl_c = adj_pre_fd + safe_shares + note_shares + pool_topup_shares + new_money_shares
            acquisition_shares = (acq_t / (1.0 - acq_t)) * post_fd_excl_c if 0.0 < acq_t < 1.0 else 0.0
        post_fd = adj_pre_fd + safe_shares + note_shares + pool_topup_shares + new_money_shares + acquisition_shares

        # Per-class aggregate ownership
        founders_shares = sum(int(f["common_shares"]) for f in working_cap_state["founders"])
        final_ats = working_cap_state["as_converted_totals"]
        preferred_as_conv = final_ats["preferred_shares_as_converted"]
        pool_total = final_ats["options_outstanding"] + final_ats["options_available"] + pool_topup_shares

        founders_by_class: dict[str, float] = {}
        # Per-HOLDER post-round ownership, from the same division. "What does this round do to ME" is
        # the most common question a multi-founder company asks, and it used to be unanswerable: the
        # only output was the founders' aggregate, and splitting an aggregate in chat is banned (and
        # would be wrong). The arithmetic is exact rather than an estimate -- a priced round does not
        # change a founder's share COUNT, so dilution is denominator growth and each holder's post-round
        # share is simply their shares over the same post_fd used for every other class here.
        # Keyed on founder_id (schema-required) rather than name: two founders can share a name, and a
        # founder holding two classes must not silently merge into one row.
        founders_by_holder: dict[str, Any] = {}
        for f in working_cap_state["founders"]:
            cls = f.get("common_class") or "class_a"
            pct = int(f["common_shares"]) / post_fd if post_fd else 0.0
            founders_by_class[cls] = founders_by_class.get(cls, 0.0) + pct
            fid = str(f.get("founder_id") or f.get("name") or f"holder_{len(founders_by_holder)}")
            prior = founders_by_holder.get(fid)
            if prior is None:
                founders_by_holder[fid] = {
                    "name": f.get("name"),
                    "common_shares": int(f["common_shares"]),
                    "pct": pct,
                }
            else:
                prior["common_shares"] += int(f["common_shares"])
                prior["pct"] += pct

        aggregate: dict[str, Any] = {
            "founders_pct": founders_shares / post_fd if post_fd else 0.0,
            "founders_by_class": founders_by_class,
            # Nested INSIDE aggregate_ownership_by_class deliberately: that field is emitted only when
            # `not _degenerate`, so a solver-rejected scenario cannot leak a per-holder table for free,
            # and the renderers already filter nested dicts out of scalar chart data.
            "founders_by_holder": founders_by_holder,
            "preferred_pct": preferred_as_conv / post_fd if post_fd else 0.0,
            "option_pool_pct": pool_total / post_fd if post_fd else 0.0,
            "safe_pct": safe_shares / post_fd if post_fd else 0.0,
            "note_pct": note_shares / post_fd if post_fd else 0.0,
            "new_money_pct": new_money_shares / post_fd if post_fd else 0.0,
        }
        _acq_closed = float(working_cap_state["as_converted_totals"].get("acquisition_consideration_shares", 0) or 0)
        if acquisition:
            aggregate["acquisition_pct"] = acquisition_shares / post_fd if post_fd else 0.0
        elif _acq_closed > 0:
            aggregate["acquisition_pct"] = _acq_closed / post_fd if post_fd else 0.0

        # Pre-AD baseline (only meaningful when AD fired)
        if has_ad_protection and ad_breakdown:
            pre_ad_new_money_shares = new_money / pre_pps if pre_pps > 0 else 0.0
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

        # Post-convergence economic-validity guard. The bracketed path CARVES OUT the
        # founders_pct≤0 rejection: the feasible-but-slow band is *defined* by
        # founders%→0, so re-blocking on it would defeat the fallback. A bracketed
        # root with a verified sign change is feasible by construction; only
        # price<floor and out-of-[0,1] fractions remain as defense-in-depth. The
        # acq_infeasible path omits quantitative fields without the generic blocker
        # (the caller seeded a typed E_ACQUISITION_INFEASIBLE).
        _fraction_fields = ("founders_pct", "preferred_pct", "safe_pct", "note_pct", "new_money_pct")
        if acq_infeasible:
            _degenerate = True
        else:
            _founders_bad = (aggregate["founders_pct"] <= 0.0) and not bracketed
            _degenerate = (
                fin_price < PPS_SANITY_FLOOR
                or _founders_bad
                or any(not (0.0 <= aggregate[k] <= 1.0) for k in _fraction_fields)
            )
            if _degenerate:
                fin_blockers.append(
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
        if _degenerate:
            fin_converged = False

        # Determine scenario completeness — bucket rejected SAFEs by error code.
        rejected_safes = {s: r for s, r in per_safe.items() if r.get("branch") == "rejected"}
        if rejected_safes:
            from collections import defaultdict  # noqa: PLC0415 (local import to avoid top-level dep)

            by_code: dict[str, list[str]] = defaultdict(list)
            for sid, rr in rejected_safes.items():
                by_code[rr.get("error", "E_SAFE_REQUIRES_CONVERSION_EVENT")].append(sid)
            for code, ids in by_code.items():
                if code == "E_UNKNOWN_SAFE_FORM":
                    sample_reason = per_safe[ids[0]].get("reason", "")
                    fin_blockers.append(
                        {"code": "E_UNKNOWN_SAFE_FORM", "instance_id": ",".join(ids), "remedy": sample_reason}
                    )
                else:
                    fin_blockers.append(
                        {
                            "code": code,
                            "instance_id": ",".join(ids),
                            "remedy": "One or more SAFEs could not resolve to a conversion price; check forms + inputs.",
                        }
                    )

        completeness = "full" if not fin_blockers else "structural_only"

        result: dict[str, Any] = {
            "completeness": completeness,
            "blockers": fin_blockers,
            "equity_financing_price": fin_price,
            "iterations": iterations,
            "converged": fin_converged,
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

        if not _degenerate:
            result["post_round_fully_diluted_shares"] = int(round(post_fd))
            result["shares_breakdown"] = {
                "pre_round_fully_diluted": int(pre_fd),
                "ad_delta": int(round(adj_pre_fd - pre_fd)),
                "safe_converted": int(round(safe_shares)),
                "note_converted": int(round(note_shares)),
                "pool_topup": int(round(pool_topup_shares)),
                "new_money": int(round(new_money_shares)),
            }
            if acquisition:
                result["shares_breakdown"]["acquisition_consideration"] = int(round(acquisition_shares))
            elif _acq_closed > 0:
                result["shares_breakdown"]["acquisition_consideration"] = int(round(_acq_closed))
            result["aggregate_ownership_by_class"] = aggregate

        if acquisition:
            result["math_provenance"].append(
                {
                    "output_field": "shares_breakdown.acquisition_consideration",
                    "source_type": "rule",
                    "rule_id": ACQUISITION_RULE_ID,
                    "rule_pack_version": RULE_PACK_VERSION,
                    "source_ref": None,
                }
            )

        if has_ad_protection:
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

        if aitken_engaged or aitken_fallback_engaged or damping_engaged:
            result["convergence_diagnostics"] = {
                "aitken_engaged": aitken_engaged,
                "aitken_fallback_engaged": aitken_fallback_engaged,
                "damping_engaged": damping_engaged,
            }

        if fin_warnings:
            result.setdefault("warnings", [])
            result["warnings"].extend(fin_warnings)

        return result

    # === Trigger orchestration (design §6) ===
    # Trigger 1: the loop did not converge. For acquisition deals this is the
    # typical slow-band case (always burns all iters) → try the bracketed solve.
    _bracketed_solved = False
    _acq_infeasible = False
    if acquisition and not converged:
        outcome = _bracketed_solve()
        if outcome[0] == "ok":
            price = float(outcome[1])
            converged = True
            _bracketed_solved = True
        else:
            _acq_infeasible = True
            blockers.append({"code": outcome[1], "instance_id": None, "remedy": outcome[2]})

    if not converged and not _bracketed_solved and not _acq_infeasible:
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

    result = _finalize(
        price,
        fin_converged=converged,
        bracketed=_bracketed_solved,
        seed_blockers=blockers,
        acq_infeasible=_acq_infeasible,
    )

    # Trigger 2 (design §6): the loop CONVERGED but to a degenerate root (rather than
    # burning all iters). Mutually exclusive with Trigger 1. Re-solve via the bracket.
    if (
        acquisition
        and not _bracketed_solved
        and not _acq_infeasible
        and result.get("converged") is False
        and any(b["code"] == "E_SOLVER_NO_VALID_FIXED_POINT" for b in result["blockers"])
    ):
        outcome = _bracketed_solve()
        if outcome[0] == "ok":
            result = _finalize(
                float(outcome[1]),
                fin_converged=True,
                bracketed=True,
                seed_blockers=[],
                acq_infeasible=False,
            )
        else:
            result = _finalize(
                price,
                fin_converged=False,
                bracketed=False,
                seed_blockers=[{"code": outcome[1], "instance_id": None, "remedy": outcome[2]}],
                acq_infeasible=True,
            )

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
    p.add_argument(
        "--mfn-elections",
        default=None,
        help="JSON map {electing_safe_id: elected_against_safe_id} of scenario MFN elections.",
    )
    add_output_args(p)
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)

    mfn_elections = json.loads(args.mfn_elections) if args.mfn_elections else None

    result = solve_priced_round(
        cap_state=cap_state,
        safes=instruments.get("safes", []),
        notes=instruments.get("convertible_notes", []),
        pre_money=args.pre_money,
        new_money=args.new_money,
        target_pool_percent=args.target_pool_pct,
        target_basis=args.target_basis,
        conversion_event_date=args.conversion_date,
        mfn_elections=mfn_elections,
        max_iterations=args.max_iter,
        convergence_threshold=args.threshold,
    )
    emit(result, args, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
