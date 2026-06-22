#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate sweep.json — a parametric pre-money sweep for the explorer slider.

Re-runs the priced-round solver across a range of pre-money valuations (holding
``new_money`` and every other parameter fixed), producing K real solver frames
the explorer's slider scrubs between. Every frame is real solver output — the
slider snaps to discrete frames, so no fabricated in-between ownership is ever
shown ("we don't make the numbers up").

No new math: it builds a list of ``priced_round`` requests that vary
``parameters.pre_money`` and runs them through the existing
``run_all_scenarios`` path (which re-runs the pre-round warrant pump + solver
per frame).

Input: an artifact dir with inputs/instruments/cap_state/scenarios.json. Picks a
base ``priced_round`` scenario that has both ``parameters.pre_money`` and
``parameters.new_money``. Output: sweep.json (schema-locked); JSON receipt to
stdout. When no eligible base scenario exists, writes an empty sweep (the
explorer simply renders no slider).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402
from run_scenario import run_all_scenarios  # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(_HERE), "references", "schemas")

DEFAULT_STEPS = 13
# Sweep ±50% around the base pre-money.
_RANGE_LO = 0.5
_RANGE_HI = 1.5
# Only the fields the slider view consumes — keeps the inlined payload small.
_SLIDER_FIELDS = (
    "completeness",
    "cap_implied_only",
    "aggregate_ownership_by_class",
    "equity_financing_price",
    "post_round_fully_diluted_shares",
    "shares_breakdown",
    "founder_impact",
    "blockers",
)


def _find_base_scenario(scenarios: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First priced_round scenario carrying both pre_money and new_money."""
    for s in scenarios:
        if s.get("type") == "priced_round":
            p = s.get("parameters") or {}
            if p.get("pre_money") is not None and p.get("new_money") is not None:
                return s
    return None


def build_sweep_requests(base: dict[str, Any], *, steps: int) -> list[dict[str, Any]]:
    """K priced_round requests varying pre_money, holding every other param fixed."""
    base_params = dict(base.get("parameters") or {})
    base_pre = float(base_params["pre_money"])
    lo, hi = base_pre * _RANGE_LO, base_pre * _RANGE_HI
    requests: list[dict[str, Any]] = []
    for i in range(steps):
        # steps==1 → the base value (frac 0.5), not the low end.
        frac = i / (steps - 1) if steps > 1 else 0.5
        pre = round(lo + (hi - lo) * frac, 2)
        params = dict(base_params)
        params["pre_money"] = pre
        requests.append(
            {
                "scenario_id": f"sweep_{i:02d}",
                "label": f"Pre ${pre / 1e6:.1f}M",
                "type": "priced_round",
                "parameters": params,
            }
        )
    return requests


def _trim_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    return {k: outputs.get(k) for k in _SLIDER_FIELDS if k in outputs}


def build_sweep(
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    scenarios: list[dict[str, Any]],
    steps: int,
) -> dict[str, Any]:
    base = _find_base_scenario(scenarios)
    if base is None:
        return {
            "axis": "pre_money",
            "base_scenario_id": None,
            "base_pre_money": None,
            "note": "No priced_round scenario with pre_money + new_money; no sweep generated.",
            "frames": [],
        }
    requests = build_sweep_requests(base, steps=steps)
    results = run_all_scenarios(
        inputs=inputs,
        instruments=instruments,
        cap_state=cap_state,
        scenario_requests=requests,
    )
    frames: list[dict[str, Any]] = []
    for req, res in zip(requests, results, strict=True):
        co = res["computed_outputs"]
        valid = co.get("completeness") in ("full", "mixed") and not co.get("blockers")
        frames.append(
            {
                "pre_money": req["parameters"]["pre_money"],
                "new_money": req["parameters"].get("new_money"),
                "valid": bool(valid),
                "outputs": _trim_outputs(co),
            }
        )
    return {
        "axis": "pre_money",
        "base_scenario_id": base["scenario_id"],
        "base_pre_money": float(base["parameters"]["pre_money"]),
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="Artifact dir with inputs/instruments/cap_state/scenarios.json")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    def _read(name: str) -> Any:
        with open(os.path.join(args.dir, name), encoding="utf-8") as f:
            return json.load(f)

    inputs = _read("inputs.json")
    instruments = _read("instruments.json")
    cap_state = _read("cap_state.json")
    scen = _read("scenarios.json")
    scenarios = scen.get("scenarios", []) if isinstance(scen, dict) else scen

    data = build_sweep(
        inputs=inputs,
        instruments=instruments,
        cap_state=cap_state,
        scenarios=scenarios,
        steps=args.steps,
    )
    schema = load_schema(os.path.join(_SCHEMA_DIR, "sweep.schema.json"))
    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"sweep.py: schema validation failed: {e}\n")
        return 1
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
