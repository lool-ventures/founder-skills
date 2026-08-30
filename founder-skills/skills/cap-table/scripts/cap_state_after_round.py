#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
STATUS: UNREACHED BY ANY WORKFLOW. Nothing in any SKILL.md, reference or agent body invokes this
producer, and the loader that would validate its output (`_artifact_io.load_cap_state`) has no
production callers either. It is kept because multi-round modelling is a product decision that
has not been taken, not because it is live. Before wiring it up: route the write through
`_artifact_writer.write_artifact` (which validates on write, unlike the raw `json.dump` here),
stamp fresh metadata rather than deep-copying the pre-round `run_id`, and add a round-trip test
through `load_cap_state`. Its four tests call the builder directly and would not catch any of
those. The null-date defect below was found exactly that way.
Builds cap_state_after_round.json — the post-round cap-state snapshot.

Per v3 design §4.5: when a priced_round scenario applies AD adjustments, the
solver emits `ccp_mutations` (per-series CCP after the round). This script
takes the pre-round cap_state + the converged scenario output and produces
a post-round cap_state with:
  * preferred_series[].current_conversion_price updated to AD-adjusted CCP
  * as_converted_totals recomputed via shares × OCP / CCP
  * cap_table_history[] extended with one anti_dilution_applied event per
    series that experienced an AD adjustment

The post-round artifact lets the next round's solver start from the correct
mutated state, and feeds the stale-CCP guard on subsequent rounds.

Usage:
    python3 cap_state_after_round.py \
        --cap-state pre/cap_state.json \
        --scenarios pre/scenarios.json \
        --scenario-id series_a \
        -o post/cap_state_after_round.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import (  # type: ignore[import-not-found]  # noqa: E402
    ArtifactValidationError,
    load_schema,
    write_artifact,
)

CAP_STATE_SCHEMA_VERSION = "v0.5.0-cap-state"
_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references", "schemas")


def _recompute_as_converted_totals(cap_state: dict[str, Any]) -> None:
    """Recompute as_converted_totals after CCP mutations.

    Mirrors cap_state.py:_compute_as_converted_totals (shares × OCP / CCP)
    so this script doesn't import from sibling modules — keeps it
    standalone-runnable.
    """
    preferred_series = cap_state.get("preferred_series", [])
    new_preferred = 0
    for s in preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp == 0:
            new_preferred += shares
        else:
            new_preferred += int(round(shares * (ocp / ccp)))
    ats = cap_state["as_converted_totals"]
    old_preferred = ats["preferred_shares_as_converted"]
    ats["preferred_shares_as_converted"] = new_preferred
    ats["fully_diluted_shares"] = ats["fully_diluted_shares"] + (new_preferred - old_preferred)


def build_cap_state_after_round(
    pre_cap_state: dict[str, Any],
    scenario_output: dict[str, Any],
    *,
    round_id: str,
    applied_at: str | None = None,
    rule_pack_version: str = "0.4.0",
) -> dict[str, Any]:
    """Construct the post-round cap_state.

    Args:
        pre_cap_state: the cap_state.json that fed solve_priced_round.
        scenario_output: the scenario's computed_outputs (from scenarios.json).
            Reads ccp_mutations + anti_dilution_breakdown.
        round_id: the scenario_id / round label for cap_table_history.
        applied_at: optional ISO date for the history record.

    Returns:
        A new cap_state dict with mutated CCP, recomputed as_converted_totals,
        and an extended cap_table_history.
    """
    post = copy.deepcopy(pre_cap_state)

    # A null history on the way IN must not become a null on the way OUT: the schema types this field
    # as an array, so copying the null through produced an artifact that fails its own validation.
    # Same rule the rest of this skill follows -- an absent optional is absent, never a null. Placed
    # before the no-mutation early return below, which otherwise hands the null straight to disk.
    if post.get("cap_table_history", ...) is None:
        del post["cap_table_history"]

    ccp_mutations = scenario_output.get("ccp_mutations") or {}
    ad_breakdown = scenario_output.get("anti_dilution_breakdown") or []

    if not ccp_mutations and not ad_breakdown:
        # No AD applied; return the pre-round snapshot unchanged
        return post

    # A null history on the way IN must not become a null on the way OUT: the schema types this field
    # as an array, so copying the null through produced an artifact that fails its own validation.
    # Same rule the rest of the skill follows -- an absent optional is absent, never a null. Placed
    # before the no-mutation early return, which otherwise passes the null straight to disk.
    # Apply CCP mutations
    for s in post.get("preferred_series", []):
        sid = s.get("series_id")
        if sid in ccp_mutations:
            s["current_conversion_price"] = float(ccp_mutations[sid])

    # Recompute as_converted_totals to reflect new CCP values
    _recompute_as_converted_totals(post)

    # Extend cap_table_history with one event per AD-adjusted series
    history = post.get("cap_table_history") or []
    series_with_change: dict[str, dict[str, Any]] = {}
    for bd in ad_breakdown:
        sid = bd.get("series_id")
        if sid in ccp_mutations and bd.get("ccp_before") != bd.get("ccp_after"):
            series_with_change[sid] = bd
    for sid, bd in series_with_change.items():
        history.append(
            {
                "event_type": "anti_dilution_applied",
                "round_id": round_id,
                # Omitted, not null, when no date is supplied. The schema types this `string`, so
                # writing null produced an artifact that failed its own validation under the usage
                # this file documents at the top. Same rule the rest of the skill now follows: an
                # absent optional is absent, never a null.
                **({"applied_at": applied_at} if applied_at is not None else {}),
                "series_id": sid,
                "previous_ccp": bd.get("ccp_before"),
                "new_ccp": bd.get("ccp_after"),
                "rule_id": bd.get("rule_id"),
                "rule_pack_version": rule_pack_version,
            }
        )
    if history:
        post["cap_table_history"] = history

    return post


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cap-state", required=True, help="Path to pre-round cap_state.json")
    p.add_argument("--scenarios", required=True, help="Path to scenarios.json")
    p.add_argument("--scenario-id", required=True, help="Which scenario to apply (priced_round)")
    p.add_argument("--run-id", required=True, help="Run id stamped on the produced artifact")
    p.add_argument("--applied-at", default=None, help="ISO date for cap_table_history event (default null)")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.scenarios, encoding="utf-8") as f:
        scenarios_data = json.load(f)

    target = None
    for s in scenarios_data.get("scenarios", []):
        if s.get("scenario_id") == args.scenario_id:
            target = s
            break
    if target is None:
        sys.stderr.write(f"scenario_id {args.scenario_id!r} not found in {args.scenarios}\n")
        return 1

    out = build_cap_state_after_round(
        cap_state,
        target["computed_outputs"],
        round_id=args.scenario_id,
        applied_at=args.applied_at,
    )

    # Written through `write_artifact`, which VALIDATES against the schema before touching disk, so
    # this producer physically cannot emit an artifact its own schema rejects. It used to raw-dump,
    # and shipped exactly that: a null `applied_at` where the schema requires a string, reachable
    # from the usage documented at the top of this file. Its four unit tests all call the builder
    # directly, so none of them could see it.
    #
    # `run_id` is stamped fresh rather than inherited: `build_cap_state_after_round` deep-copies the
    # pre-round metadata, so without this the post-round artifact would claim to be the run that
    # produced its INPUT.
    try:
        write_artifact(
            data=out,
            schema=load_schema(os.path.join(_SCHEMA_DIR, "cap_state.schema.json")),
            run_id=args.run_id,
            output_path=args.output,
            pretty=bool(args.pretty),
            schema_version=CAP_STATE_SCHEMA_VERSION,
        )
    except ArtifactValidationError as exc:
        sys.stderr.write(f"cap_state_after_round.py: refusing to write an invalid artifact: {exc}\n")
        print(json.dumps({"ok": False, "error": "E_CAP_STATE_SCHEMA_INVALID", "detail": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "output": args.output,
                "ad_events_added": (
                    len(out.get("cap_table_history") or []) - len(cap_state.get("cap_table_history") or [])
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
