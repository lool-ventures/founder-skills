#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Signal-based, deterministic structure detector / router.

Reads inputs.json + instruments.json, emits the required primitives and the
coverage result. No NLP guessing: every primitive is keyed off a concrete field.
See design spec §3.2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage as coverage_mod  # type: ignore[import-not-found]  # noqa: E402


def detect(
    inputs: dict[str, Any], instruments: dict[str, Any], registry: dict[str, Any] | None = None
) -> dict[str, Any]:
    reg = registry or coverage_mod.load_registry()
    required: list[str] = []

    if instruments.get("safes"):
        required.append("safe_conversion")
    if instruments.get("convertible_notes"):
        required.append("note_conversion")
    # A priced round is implied by an acquisition or any new-money / financing signal.
    has_acq = isinstance(inputs.get("acquisition"), dict)
    if has_acq:
        required.append("acquisition_consideration")
    if (
        has_acq
        # event_dates has no priced_round field in inputs.schema.json; this branch is
        # intentionally inert — priced_round is already covered via safes/notes/acquisition above.
        or inputs.get("event_dates", {}).get("priced_round")
        or instruments.get("safes")
        or instruments.get("convertible_notes")
    ):
        required.append("priced_round")
    # target_pool_percent is a scenario param, not a field in inputs.schema.json; this branch
    # is intentionally inert — option_pool top-up is driven by the scenario request, not inputs.
    if (inputs.get("option_pool") or {}).get("target_pool_percent"):
        required.append("option_pool")
    if any(s.get("anti_dilution_protection", "none") != "none" for s in inputs.get("preferred_series", [])):
        required.append("anti_dilution")
    # Real flip signals from inputs.schema.json: mode=="flip_focused", jurisdiction.structure=="mid_flip",
    # or event_dates.flip_closing_date set. The old fields (jurisdiction_change / event_dates.flip)
    # do not exist in the schema and caused flip to never be detected.
    if (
        inputs.get("mode") == "flip_focused"
        or (inputs.get("jurisdiction") or {}).get("structure") == "mid_flip"
        or (inputs.get("event_dates") or {}).get("flip_closing_date")
    ):
        required.append("flip")

    # De-dup, preserve order.
    seen: set[str] = set()
    deduped: list[str] = []
    for p in required:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    required = deduped

    cov = coverage_mod.is_covered(required, reg)
    route: dict[str, Any] = {"scenario_requests": []}
    if cov["covered"]:
        route["scenario_requests"] = _build_requests(required, inputs)
    return {
        "required_primitives": required,
        "covered": cov["covered"],
        "uncovered_parts": cov["uncovered_parts"],
        "route": route,
    }


def _build_requests(required: list[str], inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Map covered primitives to an ordered run_scenario plan. Flip (if present) runs
    first as its own scenario, then the priced round (carrying safe/note/pool/AD/acquisition)."""
    reqs: list[dict[str, Any]] = []
    if "flip" in required:
        reqs.append(
            {
                "scenario_id": "s_flip",
                "label": "Jurisdiction flip",
                "type": "flip",
                "parameters": {},
                # Discoverability only -- this detector reads inputs.json + instruments.json, so it
                # cannot know answers that live with the founder. Naming them beats an empty dict that
                # looks complete. run_scenario.py is what actually blocks on absence.
                "parameters_required": ["iia_grants_in_history", "section_102_grants_outstanding"],
            }
        )
    if "priced_round" in required:
        params: dict[str, Any] = {}
        if isinstance(inputs.get("acquisition"), dict):
            params["acquisition"] = inputs["acquisition"]
        reqs.append(
            {
                "scenario_id": "s_round",
                "label": "Priced round",
                "type": "priced_round",
                "chained_from_scenario_id": "s_flip" if "flip" in required else None,
                "parameters": params,
                # See the flip note above: round terms are the founder's, not derivable here.
                "parameters_required": ["pre_money", "new_money"],
            }
        )
    return reqs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True)
    p.add_argument("--instruments", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)
    result = detect(inputs, instruments)
    result["run_id"] = args.run_id
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2 if args.pretty else None)
        f.write("\n")
    receipt = {"ok": True, "path": os.path.abspath(args.output), "bytes": os.path.getsize(args.output)}
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        sys.stderr.write(f"detect_structure: required={result['required_primitives']} covered={result['covered']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
