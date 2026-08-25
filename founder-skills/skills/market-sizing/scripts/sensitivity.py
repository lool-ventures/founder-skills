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

Optional top-level key ``validation_confidence``: a ``{parameter_name:
confidence_tier}`` map, typically built from validation.json's
``assumptions[].category``. It is consulted when a range omits its own ``confidence``, so a
parameter tagged 'derived'/'agent_estimate' there still gets its auto-widening floor even if the
range didn't repeat the tag.

It also RECONCILES against a range's explicit ``confidence``, and the stricter tier wins. The
range used to be absolute, which deferred to the caller on the one field the caller has an
incentive to understate: tag a medium-confidence parameter 'sourced' and it was never widened,
whatever validation concluded. Reconciling can only ever WIDEN (the tiers are ordered by
``CONFIDENCE_MIN_RANGE``), which is the safe direction. ``confidence_source`` on each scenario
records where the tier came from: range | validation | reconciled | default.

Omitting the map entirely preserves the 'sourced' default (with a stderr warning) for a range
with no confidence anywhere — reported as ``confidence_source: "default"``, because "no widening
happened" and "no widening was called for" are not the same statement.

Output: JSON with scenario table and sensitivity ranking.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

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


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    """Emit a validation-error result and exit NON-ZERO, without touching `output_path`.

    Mirrors `market_sizing.py`'s helper, for the same two reasons.

    The error JSON still goes to STDOUT so the caller can read the diagnostic; only the exit
    code and stderr are new. It is deliberately NOT written to `--output`, because that path is
    a canonical artifact: overwriting it with a figure-less stub destroys the prior good file
    AND reads as truth to `compose_report.py`.

    Exit 1 is what makes the failure reachable. SKILL.md's producer-error branch is written as
    "the pipe fails next" — with exit 0 and an `{{"ok":true}}` receipt, that branch could never
    fire, so a rejected run was indistinguishable from a successful one.
    """
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


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


def _validate_config(
    data: dict[str, Any],
) -> tuple[str, dict[str, float], dict[str, dict[str, float]], dict[str, str], list[str]]:
    """Validate sensitivity config. Returns (approach, base_params, ranges, validation_confidence, errors).

    Consolidates all validation from main() and run_sensitivity() into one pass.

    ``validation_confidence`` is an optional top-level input key: a
    ``{parameter_name: confidence_tier}`` map the caller builds from
    ``validation.json``'s ``assumptions[].category`` (the authoritative
    per-parameter confidence source per the skill's SENSITIVITY_TEST dispatch
    contract). When a range omits its own ``confidence``, run_sensitivity()
    cross-references this map before falling back to the 'sourced' default —
    see run_sensitivity() for the fallback chain.
    """
    errors: list[str] = []

    # Validate 'base' key
    if "base" not in data:
        errors.append("Missing required key: 'base'")
        return "", {}, {}, {}, errors

    if not isinstance(data["base"], dict):
        errors.append(f"'base' must be an object (got {type(data['base']).__name__})")
        return "", {}, {}, {}, errors

    if "ranges" in data and not isinstance(data["ranges"], dict):
        errors.append(f"'ranges' must be an object (got {type(data['ranges']).__name__})")
        return "", {}, {}, {}, errors

    # Normalize approach
    approach_raw = data.get("approach", "bottom_up")
    if not isinstance(approach_raw, str):
        errors.append(f"'approach' must be a string (got {type(approach_raw).__name__})")
        return "", {}, {}, {}, errors
    approach = approach_raw.replace("-", "_")
    if approach not in VALID_APPROACHES:
        errors.append(f"approach must be one of {sorted(VALID_APPROACHES)} (got '{approach}')")
        return approach, {}, {}, {}, errors

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

    # Validate optional 'validation_confidence' cross-reference map. Malformed
    # entries are dropped (not fatal) so a caller's typo in one param doesn't
    # block the whole run — the per-range 'confidence' key still applies, reconciled against
    # whatever survives here, and is unaffected by problems in a sibling entry.
    validation_confidence: dict[str, str] = {}
    raw_validation_confidence = data.get("validation_confidence", {})
    if raw_validation_confidence and not isinstance(raw_validation_confidence, dict):
        errors.append(f"'validation_confidence' must be an object (got {type(raw_validation_confidence).__name__})")
    elif raw_validation_confidence:
        for param_name, raw_conf in raw_validation_confidence.items():
            conf = str(raw_conf)
            if conf not in CONFIDENCE_MIN_RANGE:
                errors.append(
                    f"validation_confidence.{param_name} must be one of {list(CONFIDENCE_MIN_RANGE)} (got '{conf}')"
                )
                continue
            validation_confidence[param_name] = conf

    return approach, base_params, ranges, validation_confidence, errors


def run_sensitivity(
    approach: str,
    base_params: dict[str, float],
    ranges: dict[str, dict[str, float]],
    validation_confidence: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run sensitivity analysis by varying each parameter independently.

    Assumes inputs are pre-validated by _validate_config().

    ``validation_confidence`` (optional): a ``{parameter_name: confidence_tier}``
    map cross-referenced when a range omits its own ``confidence`` key, and reconciled
    against it when both are present (the stricter tier wins; see the module docstring).
    Intended to be built by the caller from ``validation.json``'s
    ``assumptions[].category``, so a parameter tagged 'derived' or 'agent_estimate'
    there doesn't silently lose its auto-widening floor just because the range
    itself didn't repeat the tag. Plain missing-everywhere (no range confidence
    AND no entry here) keeps the documented 'sourced' backward-compatible default.
    """
    validation_confidence = validation_confidence or {}
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

        # Confidence-based range widening.
        #
        # `confidence_source` records WHERE the tier came from, because "no widening happened"
        # and "no widening was called for" were previously indistinguishable in the artifact.
        raw_confidence = range_spec.get("confidence")
        if raw_confidence is None:
            xref_confidence = validation_confidence.get(param_name)
            if xref_confidence is not None:
                print(
                    f"Note: '{param_name}' missing confidence level in range; "
                    f"using '{xref_confidence}' cross-referenced from validation_confidence",
                    file=sys.stderr,
                )
                confidence = xref_confidence
                confidence_source = "validation"
            else:
                print(f"Warning: '{param_name}' missing confidence level, defaulting to 'sourced'", file=sys.stderr)
                confidence = "sourced"
                confidence_source = "default"
        else:
            confidence = str(raw_confidence)
            confidence_source = "range"

        # RECONCILE, DO NOT DEFER. The range's own `confidence` used to be absolute: the
        # cross-reference map was consulted only when the range omitted one. That deferred to the
        # caller on the single field the caller has an incentive to understate -- tag a parameter
        # `sourced` and it is never widened, whatever the validation step concluded about it. The
        # instruction to tier honestly then lived only in prose, unenforced AND invisible, since
        # an explicit `confidence` also made this look like a deliberate choice rather than a
        # default.
        #
        # So a stricter cross-referenced tier now wins over a laxer declared one. It can only ever
        # WIDEN a range (the tiers are ordered by `CONFIDENCE_MIN_RANGE`), which is the safe
        # direction: the failure this closes is an uncertain input going unstressed.
        xref = validation_confidence.get(param_name)
        if (
            confidence_source == "range"
            and xref is not None
            and CONFIDENCE_MIN_RANGE.get(xref, 0) > CONFIDENCE_MIN_RANGE.get(confidence, 0)
        ):
            print(
                f"Note: '{param_name}' declared confidence '{confidence}' but validation graded it "
                f"'{xref}'; using the stricter tier (a declared tier cannot narrow a validated one)",
                file=sys.stderr,
            )
            confidence = xref
            confidence_source = "reconciled"

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
            # Where the tier came from: "range" (declared), "validation" (cross-referenced),
            # "reconciled" (declared, but validation graded it stricter), "default" (nothing
            # said, fell back to the tier that widens nothing). Without this, an unwidened
            # range and an untiered one are indistinguishable downstream.
            "confidence_source": confidence_source,
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
    p.add_argument("--run-id", help="Inject metadata.run_id into output (for stale-artifact detection)")
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

    # --- Validation (JSON error dict on stdout, exit 1, no file written) ---
    approach, base_params, ranges, validation_confidence, errors = _validate_config(data)

    if errors:
        result: dict[str, Any] = {"validation": {"status": "invalid", "errors": errors}}
        if args.run_id:
            result["metadata"] = {"run_id": args.run_id}
        _fail_invalid(result, args.output, indent)

    result = run_sensitivity(approach, base_params, ranges, validation_confidence)
    result["validation"] = {"status": "valid", "errors": []}
    # Count scenarios actually analyzed (irrelevant range params are filtered
    # out with stderr warnings inside run_sensitivity), not the raw input count.
    analyzed_params = len(result.get("scenarios", []))

    if args.run_id:
        result["metadata"] = {"run_id": args.run_id}

    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"approach": approach, "parameters": analyzed_params},
    )


if __name__ == "__main__":
    main()
