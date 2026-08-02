#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic pre-round warrant exercise pump (Option A per contract §6.1).

This producer is a thin deterministic step (NOT a coupled fixed-point solver).
For each warrant whose `exercise_event_date < scenario.transaction_event_date`
and `exercised_flag == false`, it computes the new-share delta and the
implicit FMV used, returning a pump result that `run_scenario.py` applies to
cap_state BEFORE the priced-round solver runs.

Settlement-type handling:
- `cash_exercise`: shares_added = shares_underlying (the holder exercises in
  cash at the strike). FMV is not used for share-count math.
- `net_share_settlement`: shares_added = round(shares_underlying × (FMV − strike) / FMV).
  FMV is the last-known priced-round PPS (passed in by the orchestrator) or
  `pre_money / pre_pump_FD` as an approximation when no prior priced round.
  When the approximation is used, the result's `fmv_approximation_used: true`
  triggers the counsel item `warrant.net_share_pre_round_fmv_approximation`.
- `holder_election`: requires `holder_election_choice ∈ {"cash", "net_share"}`
  (validated upstream at canonicalization, §4.5). Dispatches to the chosen
  path.

Output (per warrant): {warrant_id, settlement_type, exercised_at_pps,
shares_added, fmv_approximation_used}. The orchestrator collects these into
`scenarios[].computed_outputs.warrant_exercise_events[]` (§5.4).

This file is intentionally small — the math is straightforward.
"""

from __future__ import annotations

from typing import Any


class WarrantPumpError(ValueError):
    """Raised when a warrant cannot be exercised (e.g., missing FMV for net-share)."""


def warrant_has_usable_exercise_price(warrant: dict[str, Any]) -> bool:
    """True when the warrant carries a usable strike for exercise math.

    A warrant whose strike is genuinely not stated in the source is kept as a partial
    (exercise_price null): its shares still count in fully-diluted, but exercise/pump math
    cannot run. >= 0 (not > 0): a zero/nominal strike is a legitimate warrant.
    """
    ep = warrant.get("exercise_price")
    return isinstance(ep, (int, float)) and not isinstance(ep, bool) and ep >= 0


def _resolve_fmv(
    *,
    settlement_type: str,
    last_priced_round_pps: float | None,
    pre_money: float | None,
    pre_pump_fully_diluted: int | None,
) -> tuple[float, bool]:
    """Resolve FMV used for net-share settlement.

    Returns (fmv, fmv_approximation_used).

    Precedence:
      1. last_priced_round_pps (from a prior chained priced-round scenario)
      2. pre_money / pre_pump_fully_diluted (approximation; counsel item fires)
    """
    if settlement_type == "cash_exercise":
        return 0.0, False  # not used; cash exercise math ignores FMV
    if last_priced_round_pps is not None and last_priced_round_pps > 0:
        return float(last_priced_round_pps), False
    if pre_money is None or pre_pump_fully_diluted is None or pre_pump_fully_diluted <= 0:
        raise WarrantPumpError(
            "E_WARRANT_NET_SHARE_NO_FMV: net_share_settlement requires either a "
            "prior priced-round PPS (from a chained scenario) OR a pre_money + "
            "pre_pump_fully_diluted from the current scenario's parameters; "
            "neither was provided."
        )
    return float(pre_money) / int(pre_pump_fully_diluted), True


def exercise_warrant(
    warrant: dict[str, Any],
    *,
    last_priced_round_pps: float | None = None,
    pre_money: float | None = None,
    pre_pump_fully_diluted: int | None = None,
) -> dict[str, Any]:
    """Compute the pump result for a single warrant.

    Args:
        warrant: cap_state.outstanding_warrants[i] item shape.
        last_priced_round_pps: from prior chained priced-round scenario, if any.
        pre_money: current scenario's pre_money (for approximation fallback).
        pre_pump_fully_diluted: pre-pump cap_state.as_converted_totals.fully_diluted_shares.

    Returns:
        {warrant_id, settlement_type, exercised_at_pps, shares_added,
         fmv_approximation_used, exercise_path}.
    """
    settlement = warrant["settlement_type"]
    if settlement == "holder_election":
        choice = warrant.get("holder_election_choice")
        if choice not in ("cash", "net_share"):
            raise WarrantPumpError(
                f"E_WARRANT_HOLDER_ELECTION_UNSPECIFIED: warrants[{warrant.get('warrant_id', '?')}] "
                f"holder_election_choice={choice!r}; expected 'cash' or 'net_share'."
            )
        effective = "cash_exercise" if choice == "cash" else "net_share_settlement"
        exercise_path = f"holder_election -> {effective}"
    else:
        effective = settlement
        exercise_path = settlement

    shares_underlying = int(warrant["shares_underlying"])
    if not warrant_has_usable_exercise_price(warrant):
        raise WarrantPumpError(
            f"E_WARRANT_EXERCISE_PRICE_MISSING: warrants[{warrant.get('warrant_id', '?')}] has no usable "
            "exercise_price (strike not stated in the source). Supply the strike to model exercise; the "
            "warrant's shares still count in the fully-diluted total."
        )
    strike = float(warrant["exercise_price"])

    if effective == "cash_exercise":
        return {
            "warrant_id": warrant["warrant_id"],
            "settlement_type": settlement,
            "exercised_at_pps": strike,
            "shares_added": shares_underlying,
            "fmv_approximation_used": False,
            "exercise_path": exercise_path,
        }

    # net_share_settlement
    fmv, approx_used = _resolve_fmv(
        settlement_type=effective,
        last_priced_round_pps=last_priced_round_pps,
        pre_money=pre_money,
        pre_pump_fully_diluted=pre_pump_fully_diluted,
    )
    # Underwater (FMV <= strike) means the net-share calc yields 0 or negative;
    # clamp to 0 but still mark exercised so the warrant doesn't re-pump.
    shares_added = 0 if fmv <= strike else int(round(shares_underlying * (fmv - strike) / fmv))
    return {
        "warrant_id": warrant["warrant_id"],
        "settlement_type": settlement,
        "exercised_at_pps": fmv,
        "shares_added": shares_added,
        "fmv_approximation_used": approx_used,
        "exercise_path": exercise_path,
    }


def collect_pre_round_pump_warrants(
    cap_state: dict[str, Any],
    transaction_event_date: str | None,
) -> list[dict[str, Any]]:
    """Return the warrants whose pre-round pump should fire for this scenario.

    A warrant fires when:
      * `exercise_event_date < transaction_event_date` (strict; concurrent
        exercise — equal dates — is explicitly NOT pumped per §6.1)
      * `exercised_flag == false`
      * `vested_flag == true` (unvested warrants can't exercise; §4.5 invariant
        ensures they don't carry an exercise_event_date either)
    """
    if not transaction_event_date:
        return []
    out = []
    for w in cap_state.get("outstanding_warrants", []) or []:
        eed = w.get("exercise_event_date")
        if not eed:
            continue
        if w.get("exercised_flag", False):
            continue
        if not w.get("vested_flag", False):
            continue
        if eed >= transaction_event_date:
            continue  # strict < check (concurrent not pumped)
        out.append(w)
    return out


def apply_pump_results(
    cap_state: dict[str, Any],
    pump_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply pump results to cap_state. Returns the mutated state.

    For each pump result:
      * For `warrant_type=common_stock`: increment `as_converted_totals.common_shares`
        by `shares_added`.
      * For `warrant_type=preferred_stock_series`: increment the matching
        `preferred_series[i].shares` (where i.series_id == warrant.preferred_series_id)
        AND increment `as_converted_totals.preferred_shares_as_converted` by the
        as-converted-share equivalent (`shares_added * OCP / CCP`). This keeps
        subsequent AD-on-that-series correctly proportional. The §4.5 invariant
        E_WARRANT_PREFERRED_SERIES_ID_REQUIRED catches null preferred_series_id
        at canonicalization, so we can assume the id is non-null here.
      * Decrement `as_converted_totals.warrants_underlying_total` by the
        warrant's underlying (it's no longer in the "pre-exercise FD" basket).
      * Re-derive `as_converted_totals.fully_diluted_shares` from components
        rather than delta-mutating (avoids a double-count: the pre-pump FD
        already included warrants_underlying_total, so incrementing by
        shares_added on top of it would over-count the exercised underlying).
      * Mark warrant's `exercised_flag=true`.
      * Append a `cap_table_history` event of type `warrant_exercised`.
    """
    import copy

    state = copy.deepcopy(cap_state)
    state.setdefault("cap_table_history", [])

    results_by_id = {r["warrant_id"]: r for r in pump_results}
    warrants = state.get("outstanding_warrants", []) or []
    totals = state.get("as_converted_totals", {})
    preferred_series_list = state.get("preferred_series", []) or []
    preferred_by_id = {s.get("series_id"): s for s in preferred_series_list}

    for w in warrants:
        wid = w.get("warrant_id")
        if wid not in results_by_id:
            continue
        result = results_by_id[wid]
        shares_added = int(result["shares_added"])
        wtype = w.get("warrant_type")
        # Route shares to the correct bucket
        if wtype == "common_stock":
            totals["common_shares"] = int(totals.get("common_shares", 0)) + shares_added
        elif wtype == "preferred_stock_series":
            psid = w.get("preferred_series_id")
            target_series = preferred_by_id.get(psid)
            if target_series is None:
                # The §4.5 invariant should have caught this at canonicalization;
                # defensive guard for runtime mutations.
                raise ValueError(
                    f"E_WARRANT_PREFERRED_SERIES_ID_UNKNOWN: warrants[{wid}] has "
                    f"warrant_type=preferred_stock_series + preferred_series_id={psid!r} "
                    f"but no matching series exists in cap_state.preferred_series[]."
                )
            # Add raw shares to the series (so subsequent AD on this series
            # correctly affects them) AND increment the as-converted scalar
            # using the series's current OCP/CCP ratio.
            target_series["shares"] = int(target_series.get("shares", 0)) + shares_added
            ocp = float(target_series.get("original_conversion_price", 1.0))
            ccp = float(target_series.get("current_conversion_price", ocp))
            as_converted_delta = shares_added if ccp == 0 else int(round(shares_added * (ocp / ccp)))
            totals["preferred_shares_as_converted"] = (
                int(totals.get("preferred_shares_as_converted", 0)) + as_converted_delta
            )
        # preferred_stock_blank_check: not modeled in v0.5.0 (rare; deferred)
        # Remove from warrants_underlying_total
        totals["warrants_underlying_total"] = max(
            0, int(totals.get("warrants_underlying_total", 0)) - int(w["shares_underlying"])
        )
        # Mark warrant exercised
        w["exercised_flag"] = True
        # Append cap_table_history event
        state["cap_table_history"].append(
            {
                "event_type": "warrant_exercised",
                "warrant_id": wid,
                "applied_at": w.get("exercise_event_date"),
                "shares_added": shares_added,
                "exercised_at_pps": float(result["exercised_at_pps"]),
                "series_id": w.get("preferred_series_id"),
            }
        )

    # Re-derive FD from components rather than delta-mutating. Pre-pump FD
    # already included warrants_underlying_total; incrementing by shares_added
    # on top of it would double-count (e.g., 13.7M would become 13.9M instead
    # of staying at 13.7M — the underlying 200k moved from
    # warrants_underlying_total into common, so FD is unchanged).
    totals["fully_diluted_shares"] = (
        int(totals.get("common_shares", 0))
        + int(totals.get("preferred_shares_as_converted", 0))
        + int(totals.get("options_outstanding", 0))
        + int(totals.get("options_available", 0))
        + int(totals.get("warrants_underlying_total", 0))
    )

    state["as_converted_totals"] = totals
    state["preferred_series"] = preferred_series_list
    return state


def run_pre_round_pump(
    cap_state: dict[str, Any],
    transaction_event_date: str | None,
    *,
    last_priced_round_pps: float | None = None,
    pre_money: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Top-level pump entry point.

    Args:
        cap_state: pre-pump canonical cap_state.
        transaction_event_date: scenario.transaction_event_date.
        last_priced_round_pps: from prior chained scenario (None if independent).
        pre_money: current scenario.parameters.pre_money (for FMV approximation
                   fallback when last_priced_round_pps is None).

    Returns (post_pump_cap_state, warrant_exercise_events). When no warrants
    fire, returns (cap_state unchanged, []).
    """
    due = collect_pre_round_pump_warrants(cap_state, transaction_event_date)
    if not due:
        return cap_state, []

    pre_pump_fd = int((cap_state.get("as_converted_totals") or {}).get("fully_diluted_shares", 0))

    events = [
        exercise_warrant(
            w,
            last_priced_round_pps=last_priced_round_pps,
            pre_money=pre_money,
            pre_pump_fully_diluted=pre_pump_fd,
        )
        for w in due
    ]

    post_pump_state = apply_pump_results(cap_state, events)
    return post_pump_state, events


if __name__ == "__main__":
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cap-state", required=True)
    p.add_argument("--transaction-event-date", required=True)
    p.add_argument("--last-priced-round-pps", type=float, default=None)
    p.add_argument("--pre-money", type=float, default=None)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)

    try:
        post_state, events = run_pre_round_pump(
            cap_state,
            args.transaction_event_date,
            last_priced_round_pps=args.last_priced_round_pps,
            pre_money=args.pre_money,
        )
    except WarrantPumpError as e:
        sys.stderr.write(f"warrant_exercise.py: {e}\n")
        sys.exit(1)

    out = {
        "ok": True,
        "warrants_pumped": len(events),
        "warrant_exercise_events": events,
        "post_pump_fully_diluted_shares": post_state["as_converted_totals"]["fully_diluted_shares"],
    }
    print(json.dumps(out, indent=2 if args.pretty else None))
