#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Scenario orchestrator — dispatches to the right math producer per type.

Reads a scenario request (type + parameters), routes to the appropriate
math producer (safe_conversion, note_conversion, priced_round, flip),
collects results into a scenarios.json entry per the rev15 conditional
schema, and writes the combined scenarios.json.

Per design doc §9 Step 5: the solver respects the §6 apply contract by
consuming rule_audit.json.gating (NOT the rule pack directly). For v0.1
the gating is permissive (all applicable rules apply) and the solver
focuses on math correctness; structured `applies_when_match` predicates
are a Phase 2 deliverable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402
from flip_scenario import flip_share_for_share  # noqa: E402
from note_conversion import convert_note, derive_scenario_completeness  # noqa: E402
from priced_round import solve_priced_round  # noqa: E402
from safe_conversion import (  # noqa: E402
    convert_safe_cap_implied,
    detect_mfn_cycles,
)

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)


def _compute_founder_impact(
    aggregate: dict[str, float],
    cap_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Compute founder impact (before/after %) — rendered as plain language."""
    founders = cap_state.get("founders", [])
    if not founders:
        return None
    founder_total = sum(int(f.get("common_shares", 0)) for f in founders)
    pre_fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    before_pct = founder_total / pre_fd if pre_fd else 0.0
    after_pct = aggregate.get("founders_pct", 0.0)
    delta_pp = (after_pct - before_pct) * 100  # percentage points
    plain = (
        f"Founders collectively held {before_pct:.1%} of fully-diluted shares before this scenario; "
        f"after, {after_pct:.1%}. That's {delta_pp:+.1f} percentage points."
    )
    return {
        "before_pct": before_pct,
        "after_pct": after_pct,
        "delta_pp": delta_pp,
        "plain_language": plain,
    }


def run_safe_conversion_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    safes_filter = params.get("safe_ids")
    all_safes = instruments.get("safes", [])
    safes = [s for s in all_safes if not safes_filter or s["id"] in safes_filter]

    blockers: list[dict[str, Any]] = []

    # Check for circular MFN
    cycles = detect_mfn_cycles(safes)
    if cycles:
        blockers.append(
            {
                "code": "E_SAFE_CIRCULAR_MFN",
                "instance_id": ",".join(sorted(c for cycle in cycles for c in cycle)),
                "remedy": "Break the circular MFN chain or provide conversion_price_override.",
            }
        )

    pre_fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    priced_pre = params.get("priced_round_pre_money")
    priced_new = params.get("priced_round_new_money")

    per_safe: dict[str, dict[str, Any]] = {}
    if priced_pre is None or priced_new is None:
        # Cap-implied path only
        for s in safes:
            r = convert_safe_cap_implied(
                purchase_amount=s["purchase_amount"],
                post_money_valuation_cap=s.get("post_money_valuation_cap"),
                company_capitalization=pre_fd,
            )
            per_safe[s["id"]] = r
            if r.get("branch") == "rejected":
                blockers.append(
                    {
                        "code": r.get("error", "E_UNKNOWN"),
                        "instance_id": s["id"],
                        "remedy": r.get("reason", "unspecified"),
                    }
                )

        outputs: dict[str, Any] = {
            "completeness": "structural_only",
            "cap_implied_only": True,
            "blockers": blockers,
            "per_safe": per_safe,
            "math_provenance": [
                {
                    "output_field": "cap_implied_outputs",
                    "source_type": "rule",
                    "rule_id": "safe.post_money_cap_conversion",
                    "rule_pack_version": "0.3.0",
                    "source_ref": None,
                }
            ],
        }
        return outputs

    # Has a priced round — delegate to solver
    return solve_priced_round(
        cap_state=cap_state,
        safes=safes,
        notes=[],
        pre_money=priced_pre,
        new_money=priced_new,
        target_pool_percent=params.get("target_pool_percent"),
        target_basis=params.get("target_basis", "pre_money"),
        conversion_event_date=params.get("transaction_event_date"),
    )


def run_note_conversion_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    notes_filter = params.get("note_ids")
    all_notes = instruments.get("notes", [])
    notes = [n for n in all_notes if not notes_filter or n["id"] in notes_filter]

    conv_date = params.get("transaction_event_date")
    if not conv_date:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_NOTE_NO_CONVERSION_DATE",
                    "instance_id": None,
                    "remedy": "Provide transaction_event_date for note conversion.",
                }
            ],
            "per_note": {},
            "math_provenance": [],
        }

    priced_new = params.get("priced_round_new_money")
    qfp = params.get("qualified_financing_price")
    per_note: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    for n in notes:
        r = convert_note(
            n,
            conversion_event_date=conv_date,
            priced_round_new_money=priced_new,
            qualified_financing_price=qfp,
        )
        per_note[n["id"]] = r
        if "error" in r:
            blockers.append(
                {
                    "code": r["error"],
                    "instance_id": n["id"],
                    "remedy": r.get("reason", ""),
                }
            )

    completeness = derive_scenario_completeness(per_note)
    out: dict[str, Any] = {
        "completeness": completeness,
        "blockers": blockers,
        "per_note": per_note,
        "math_provenance": [],
    }

    # Aggregate cash repayment when at least one note hit repay branch
    cash = sum(p.get("cash_repayment", 0.0) for p in per_note.values() if p.get("branch") == "maturity_repay")
    if cash > 0:
        out["aggregate_cash_repayment"] = cash

    return out


def run_priced_round_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    result = solve_priced_round(
        cap_state=cap_state,
        safes=instruments.get("safes", []),
        notes=instruments.get("notes", []),
        pre_money=params["pre_money"],
        new_money=params["new_money"],
        target_pool_percent=params.get("target_pool_percent"),
        target_basis=params.get("target_basis", "pre_money"),
        conversion_event_date=params.get("transaction_event_date"),
    )
    # Augment with founder_impact when completeness is full/mixed
    if result.get("completeness") in {"full", "mixed"}:
        result["founder_impact"] = _compute_founder_impact(result.get("aggregate_ownership_by_class", {}), cap_state)
    return result


def run_flip_scenario(
    scenario: dict[str, Any],
    *,
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    return flip_share_for_share(
        cap_state,
        iia_grants_in_history=params.get("iia_grants_in_history", False),
        section_102_grants_outstanding=params.get("section_102_grants_outstanding", 0),
    )


def run_all_scenarios(
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    scenario_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dispatch each scenario_request to the right runner and collect outputs."""
    results = []
    for req in scenario_requests:
        stype = req.get("type")
        if stype == "safe_conversion":
            outputs = run_safe_conversion_scenario(req, instruments=instruments, cap_state=cap_state)
        elif stype == "note_conversion":
            outputs = run_note_conversion_scenario(req, instruments=instruments, cap_state=cap_state)
        elif stype == "priced_round":
            outputs = run_priced_round_scenario(req, instruments=instruments, cap_state=cap_state)
        elif stype == "flip":
            outputs = run_flip_scenario(req, cap_state=cap_state)
        else:
            outputs = {
                "completeness": "structural_only",
                "blockers": [
                    {
                        "code": "E_UNKNOWN_SCENARIO_TYPE",
                        "instance_id": req.get("scenario_id"),
                        "remedy": f"Unknown scenario type: {stype}",
                    }
                ],
                "math_provenance": [],
            }
        results.append(
            {
                "scenario_id": req["scenario_id"],
                "label": req.get("label", req["scenario_id"]),
                "type": stype,
                "parameters": req.get("parameters", {}),
                "computed_outputs": outputs,
            }
        )
    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True)
    p.add_argument("--instruments", required=True)
    p.add_argument("--cap-state", required=True)
    p.add_argument("--scenarios-input", required=True, help="JSON file with list of scenario requests")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)
    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.scenarios_input, encoding="utf-8") as f:
        scenario_requests = json.load(f)
    if isinstance(scenario_requests, dict):
        scenario_requests = scenario_requests.get("scenarios", [])

    scenarios = run_all_scenarios(
        inputs=inputs,
        instruments=instruments,
        cap_state=cap_state,
        scenario_requests=scenario_requests,
    )

    data = {"scenarios": scenarios}
    schema = load_schema(os.path.join(_SCHEMA_DIR, "scenarios.schema.json"))
    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"run_scenario.py: schema validation failed: {e}\n")
        return 1
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        for s in scenarios:
            co = s["computed_outputs"]
            sys.stderr.write(
                f"  {s['scenario_id']} ({s['type']}): "
                f"completeness={co.get('completeness')} | "
                f"blockers={len(co.get('blockers', []))}\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
