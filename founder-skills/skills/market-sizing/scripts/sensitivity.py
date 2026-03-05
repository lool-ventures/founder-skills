#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Sensitivity analysis for market sizing assumptions.

Stress-tests TAM/SAM/SOM by varying each assumption independently
within specified ranges, then ranks assumptions by impact.

Always reads JSON from stdin (input is too complex for CLI args).

Usage:
    echo '{
      "approach": "bottom_up",
      "base": {"customer_count": 4500000, "arpu": 15000, "serviceable_pct": 35, "target_pct": 0.5},
      "ranges": {
        "customer_count": {"low_pct": -30, "high_pct": 20},
        "arpu": {"low_pct": -20, "high_pct": 15}
      }
    }' | python sensitivity.py --pretty

Output: JSON with scenario table and sensitivity ranking.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

VALID_APPROACHES = {"bottom_up", "top_down", "both"}
TD_PARAMS = {"industry_total", "segment_pct", "share_pct"}
BU_PARAMS = {"customer_count", "arpu", "serviceable_pct", "target_pct"}
PCT_PARAMS = {"segment_pct", "share_pct", "serviceable_pct", "target_pct"}
CONFIDENCE_MIN_RANGE = {
    "sourced": 0,
    "derived": 30,
    "agent_estimate": 50,
}
REQUIRED_FIELDS = {
    "top_down": {"industry_total", "segment_pct", "share_pct"},
    "bottom_up": {"customer_count", "arpu", "serviceable_pct", "target_pct"},
}


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def calc_top_down(params: dict[str, float]) -> dict[str, float]:
    """Calculate TAM/SAM/SOM using top-down approach."""
    tam = params["industry_total"]
    sam = tam * params["segment_pct"] / 100
    som = sam * params["share_pct"] / 100
    return {"tam": tam, "sam": sam, "som": som}


def calc_bottom_up(params: dict[str, float]) -> dict[str, float]:
    """Calculate TAM/SAM/SOM using bottom-up approach (matches market_sizing.py logic)."""
    tam = params["customer_count"] * params["arpu"]
    serviceable = params["customer_count"] * params["serviceable_pct"] / 100
    sam = serviceable * params["arpu"]
    target = serviceable * params["target_pct"] / 100
    som = target * params["arpu"]
    return {"tam": tam, "sam": sam, "som": som}


def fmt(v: float) -> float:
    return round(v, 2)


def _validate_config(data: dict[str, Any]) -> tuple[str, dict[str, float], dict[str, dict[str, float]], list[str]]:
    """Validate sensitivity config. Returns (approach, base_params, ranges, errors).

    Consolidates all validation from main() and run_sensitivity() into one pass.
    """
    errors: list[str] = []

    # Validate 'base' key
    if "base" not in data:
        errors.append("Missing required key: 'base'")
        return "", {}, {}, errors

    if not isinstance(data["base"], dict):
        errors.append(f"'base' must be an object (got {type(data['base']).__name__})")
        return "", {}, {}, errors

    if "ranges" in data and not isinstance(data["ranges"], dict):
        errors.append(f"'ranges' must be an object (got {type(data['ranges']).__name__})")
        return "", {}, {}, errors

    # Normalize approach
    approach = data.get("approach", "bottom_up").replace("-", "_")
    if approach not in VALID_APPROACHES:
        errors.append(f"approach must be one of {sorted(VALID_APPROACHES)} (got '{approach}')")
        return approach, {}, {}, errors

    base_params = data["base"]
    ranges = data.get("ranges", {})

    if not ranges:
        errors.append("'ranges' is required with at least one parameter to vary")

    # Validate required fields per approach
    if approach == "both":
        required = REQUIRED_FIELDS["bottom_up"] | REQUIRED_FIELDS["top_down"]
    else:
        required = REQUIRED_FIELDS.get(approach, set())
    missing = required - set(base_params.keys())
    if missing:
        errors.append(f"approach '{approach}' requires these fields in 'base': {sorted(missing)}")

    # Coerce all base_params values to float
    coerce_ok = True
    for key in list(base_params.keys()):
        val = base_params[key]
        try:
            base_params[key] = float(val)
        except (TypeError, ValueError):
            errors.append(f"base.{key} must be numeric (got {val!r})")
            coerce_ok = False

    if coerce_ok:
        # customer_count must be a whole number
        if "customer_count" in base_params:
            cc = base_params["customer_count"]
            if cc != int(cc):
                errors.append(f"base.customer_count must be a whole number (got {cc})")

        # Validate base percentage params are in [0, 100]
        for key in PCT_PARAMS & set(base_params.keys()):
            val = base_params[key]
            if val < 0 or val > 100:
                errors.append(f"base.{key} must be between 0 and 100 (got {val})")

        # Validate base non-negative params
        for key in set(base_params.keys()) - PCT_PARAMS:
            if base_params[key] < 0:
                errors.append(f"base.{key} cannot be negative (got {base_params[key]})")

    # Determine relevant params for single-approach mode
    if approach == "both":
        relevant_params = TD_PARAMS | BU_PARAMS
    elif approach in REQUIRED_FIELDS:
        relevant_params = TD_PARAMS if approach == "top_down" else BU_PARAMS
    else:
        relevant_params = set()

    # Validate and coerce range specs (only for relevant params)
    relevant_range_count = 0
    for param_name, range_spec in ranges.items():
        if param_name not in relevant_params:
            # Irrelevant params will be filtered with warnings in run_sensitivity()
            continue
        relevant_range_count += 1

        if not isinstance(range_spec, dict):
            errors.append(f"range for '{param_name}' must be an object (got {type(range_spec).__name__})")
            continue

        # Check required keys
        for required_key in ("low_pct", "high_pct"):
            if required_key not in range_spec:
                errors.append(f"range for '{param_name}' missing '{required_key}'")

        # Coerce pct values to float
        for pct_key in ("low_pct", "high_pct"):
            if pct_key in range_spec:
                val = range_spec[pct_key]
                try:
                    range_spec[pct_key] = float(val)
                except (TypeError, ValueError):
                    errors.append(f"ranges.{param_name}.{pct_key} must be numeric (got {val!r})")

        # Validate range key exists in base params
        if param_name not in base_params:
            errors.append(f"range key '{param_name}' not found in base params (available: {list(base_params.keys())})")

        # Validate confidence level
        raw_confidence = range_spec.get("confidence")
        if raw_confidence is not None:
            confidence = str(raw_confidence)
            if confidence not in CONFIDENCE_MIN_RANGE:
                errors.append(f"confidence must be one of {list(CONFIDENCE_MIN_RANGE)} (got '{confidence}')")

    # Check relevance for single-approach mode
    if not errors and approach != "both" and ranges and relevant_range_count == 0:
        errors.append(f"no relevant parameters for {approach} approach")

    return approach, base_params, ranges, errors


def run_sensitivity(
    approach: str,
    base_params: dict[str, float],
    ranges: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Run sensitivity analysis by varying each parameter independently.

    Assumes inputs are pre-validated by _validate_config().
    """
    if approach == "both":
        td_base = {k: base_params[k] for k in TD_PARAMS}
        bu_base = {k: base_params[k] for k in BU_PARAMS}
        base_result_td = calc_top_down(td_base)
        base_result_bu = calc_bottom_up(bu_base)
        base_result: dict[str, Any] = {"top_down": base_result_td, "bottom_up": base_result_bu}
    else:
        calc = calc_bottom_up if approach == "bottom_up" else calc_top_down
        base_result = calc(base_params)

    # Filter irrelevant params for single-approach mode
    if approach != "both":
        relevant_params = TD_PARAMS if approach == "top_down" else BU_PARAMS
        filtered_keys = set(ranges.keys()) - relevant_params
        for key in sorted(filtered_keys):
            print(f"Warning: ignoring '{key}' — not relevant for {approach} approach", file=sys.stderr)
        ranges = {k: v for k, v in ranges.items() if k in relevant_params}

    scenarios: list[dict[str, Any]] = []
    sensitivity_ranking: list[dict[str, Any]] = []

    for param_name, range_spec in ranges.items():
        # For "both" approach, determine which sub-approach this param belongs to
        if approach == "both":
            if param_name in TD_PARAMS:
                param_approach = "top_down"
            elif param_name in BU_PARAMS:
                param_approach = "bottom_up"
            else:
                continue
            calc = calc_top_down if param_approach == "top_down" else calc_bottom_up
            calc_base_params = td_base if param_approach == "top_down" else bu_base
            calc_base_result: dict[str, Any] = base_result_td if param_approach == "top_down" else base_result_bu
        else:
            param_approach = approach
            calc_base_params = base_params
            calc_base_result = base_result

        low_pct = range_spec["low_pct"]
        high_pct = range_spec["high_pct"]

        # Confidence-based range widening
        raw_confidence = range_spec.get("confidence")
        if raw_confidence is None:
            print(f"Warning: '{param_name}' missing confidence level, defaulting to 'sourced'", file=sys.stderr)
            confidence = "sourced"
        else:
            confidence = str(raw_confidence)
        min_range = CONFIDENCE_MIN_RANGE[confidence]
        original_low_pct = low_pct
        original_high_pct = high_pct
        if min_range > 0:
            if abs(low_pct) < min_range:
                low_pct = -min_range
            if abs(high_pct) < min_range:
                high_pct = min_range

        base_val = base_params[param_name]

        # Low scenario
        low_val = base_val * (1 + low_pct / 100)
        # High scenario
        high_val = base_val * (1 + high_pct / 100)

        # Domain validation: clamp to valid ranges
        if low_val < 0:
            print(
                f"Warning: {param_name} low scenario ({low_pct}%) produces negative value ({low_val}), clamping to 0",
                file=sys.stderr,
            )
            low_val = 0
        if high_val < 0:
            print(
                f"Warning: {param_name} high scenario ({high_pct}%) produces negative "
                f"value ({high_val}), clamping to 0",
                file=sys.stderr,
            )
            high_val = 0
        if param_name in PCT_PARAMS:
            if low_val > 100:
                print(f"Warning: {param_name} low scenario clamped from {low_val} to 100", file=sys.stderr)
                low_val = 100
            if high_val > 100:
                print(f"Warning: {param_name} high scenario clamped from {high_val} to 100", file=sys.stderr)
                high_val = 100

        low_params = dict(calc_base_params)
        low_params[param_name] = low_val
        low_result = calc(low_params)

        high_params = dict(calc_base_params)
        high_params[param_name] = high_val
        high_result = calc(high_params)

        scenario = {
            "parameter": param_name,
            "confidence": confidence,
            "original_range": {"low_pct": original_low_pct, "high_pct": original_high_pct},
            "effective_range": {"low_pct": low_pct, "high_pct": high_pct},
            "range_widened": (low_pct != original_low_pct or high_pct != original_high_pct),
            "base_value": base_val,
            "low": {
                "adjustment_pct": low_pct,
                "value": fmt(low_val),
                "tam": fmt(low_result["tam"]),
                "sam": fmt(low_result["sam"]),
                "som": fmt(low_result["som"]),
            },
            "base": {
                "tam": fmt(calc_base_result["tam"]),
                "sam": fmt(calc_base_result["sam"]),
                "som": fmt(calc_base_result["som"]),
            },
            "high": {
                "adjustment_pct": high_pct,
                "value": fmt(high_val),
                "tam": fmt(high_result["tam"]),
                "sam": fmt(high_result["sam"]),
                "som": fmt(high_result["som"]),
            },
        }
        if approach == "both":
            scenario["approach_used"] = param_approach
        scenarios.append(scenario)

        # Impact = max swing in SOM (most relevant metric for near-term planning)
        som_swing = abs(high_result["som"] - low_result["som"])
        som_swing_pct = som_swing / calc_base_result["som"] * 100 if calc_base_result["som"] > 0 else 0

        sensitivity_ranking.append(
            {
                "parameter": param_name,
                "som_swing": fmt(som_swing),
                "som_swing_pct": fmt(som_swing_pct),
                "tam_swing_pct": fmt(
                    abs(high_result["tam"] - low_result["tam"]) / calc_base_result["tam"] * 100
                    if calc_base_result["tam"] > 0
                    else 0
                ),
            }
        )

    # Sort by SOM swing (descending) — most impactful assumptions first
    sensitivity_ranking.sort(key=lambda x: x["som_swing_pct"], reverse=True)

    formatted_base: dict[str, Any]
    if approach == "both":
        formatted_base = {
            "top_down": {k: fmt(v) for k, v in base_result["top_down"].items()},
            "bottom_up": {k: fmt(v) for k, v in base_result["bottom_up"].items()},
        }
    else:
        formatted_base = {k: fmt(v) for k, v in base_result.items()}

    return {
        "approach": approach,
        "base_result": formatted_base,
        "scenarios": scenarios,
        "sensitivity_ranking": sensitivity_ranking,
        "most_sensitive": sensitivity_ranking[0]["parameter"] if sensitivity_ranking else None,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market sizing sensitivity analysis (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    indent = 2 if args.pretty else None

    # --- Infrastructure checks (sys.exit(1)) ---
    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print("Example: echo '{...}' | python sensitivity.py --pretty", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        sys.exit(1)

    # --- Validation (JSON error dict, exit 0) ---
    approach, base_params, ranges, errors = _validate_config(data)

    if errors:
        result: dict[str, Any] = {"validation": {"status": "invalid", "errors": errors}}
    else:
        result = run_sensitivity(approach, base_params, ranges)
        result["validation"] = {"status": "valid", "errors": []}

    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"approach": approach, "parameters": len(ranges)},
    )


if __name__ == "__main__":
    main()
