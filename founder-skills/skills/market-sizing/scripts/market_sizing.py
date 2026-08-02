#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
TAM/SAM/SOM market sizing calculator.

Computes market size using top-down, bottom-up, or both approaches.
All calculations are deterministic — no LLM inference.

Usage:
    python market_sizing.py --approach top-down \
        --industry-total 100000000000 --segment-pct 6 --share-pct 5

    python market_sizing.py --approach bottom-up \
        --customer-count 4500000 --arpu 15000 \
        --serviceable-pct 35 --target-pct 0.5

    python market_sizing.py --approach both \
        --industry-total 100000000000 --segment-pct 6 --share-pct 5 \
        --customer-count 4500000 --arpu 15000 \
        --serviceable-pct 35 --target-pct 0.5

    echo '{"approach":"bottom_up","customer_count":4500000,"arpu":15000,...}' | python market_sizing.py --stdin

Output: JSON to stdout, warnings to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Convention this analysis' headline figures follow — see
# references/tam-sam-som-methodology.md §5. Optional and NOT defaulted here: an
# unset sizing_basis must surface downstream (compose_report.py / visualize.py)
# as "not declared", never silently as "current_year" — see market_sizing.py's
# resolution logic in main() for why no fallback value is assigned.
VALID_SIZING_BASIS = {"current_year", "forecast_year", "mixed"}


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


def fmt(value: float) -> float:
    """Round to 2 decimal places for currency values."""
    return round(value, 2)


def validate_pct(name: str, value: float) -> str | None:
    """Validate percentage inputs (must be 0-100). Returns error message or None."""
    if value < 0:
        return f"{name} cannot be negative (got {value})"
    if value > 100:
        return f"{name} cannot exceed 100% (got {value}%)"
    return None


def check_pct_plausibility(name: str, value: float) -> str | None:
    """Flag a value that looks like a fraction mistaken for percentage POINTS.

    All *_pct inputs are percentage POINTS (35 means 35%), not fractions (0.35).
    A value strictly between 0 and 1 is the classic silent ~100x error: the caller
    meant e.g. 35% and wrote 0.35, which this calculator would otherwise divide by
    100 again, producing 0.35%. This is a WARNING, never a hard rejection — a
    legitimate sub-1% share/segment value exists (e.g. share_pct=0.3 meaning 0.3%),
    and this function cannot distinguish that case from the fraction mistake.
    Returns a warning message or None.
    """
    if 0 < value < 1:
        return (
            f"{name}={value} is between 0 and 1 — percentage inputs are POINTS, not "
            f"fractions (35 means 35%, not 0.35). If you meant {value * 100:g}%, pass "
            f"{value * 100:g} instead. If {value} is really the intended value "
            f"(e.g. a {value}% share), this warning is expected — no action needed."
        )
    return None


def validate_positive(name: str, value: float) -> str | None:
    """Validate positive numeric inputs. Returns error message or None."""
    if value <= 0:
        return f"{name} must be positive (> 0) (got {value})"
    return None


def coerce_float(name: str, value: Any) -> tuple[float, str | None]:
    """Coerce a JSON value to float. Returns (value, error_or_None)."""
    try:
        return float(value), None
    except (TypeError, ValueError):
        return 0.0, f"{name} must be numeric (got {value!r})"


def coerce_int(name: str, value: Any) -> tuple[int, str | None]:
    """Coerce a JSON value to int. Returns (value, error_or_None).

    Rejects non-integer floats like 3.9 to avoid silent truncation.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0, f"{name} must be numeric (got {value!r})"
    if f != int(f):
        return 0, f"{name} must be a whole number (got {value!r})"
    return int(f), None


def top_down(
    industry_total: float,
    segment_pct: float,
    share_pct: float,
    growth_rate: float | None = None,
    years: int = 0,
) -> dict[str, Any]:
    """Top-down market sizing: start from industry total, narrow down."""
    seg = segment_pct / 100
    shr = share_pct / 100

    tam = industry_total
    sam = tam * seg
    som = sam * shr

    # Apply growth if specified
    if years < 0:
        print(f"Warning: years is negative ({years}), ignoring growth projection", file=sys.stderr)
        years = 0
    tam_projected: float | None
    sam_projected: float | None
    som_projected: float | None
    if growth_rate is not None and years > 0:
        g = 1 + growth_rate / 100
        tam_projected = tam * (g**years)
        sam_projected = sam * (g**years)
        som_projected = som * (g**years)
    else:
        tam_projected = None
        sam_projected = None
        som_projected = None

    result: dict[str, Any] = {
        "tam": {
            "value": fmt(tam),
            "raw_value": tam,
            "formula": "industry_total",
            "inputs": {"industry_total": industry_total},
        },
        "sam": {
            "value": fmt(sam),
            "raw_value": sam,
            "formula": "tam * segment_pct",
            "inputs": {"tam": fmt(tam), "segment_pct": segment_pct},
        },
        "som": {
            "value": fmt(som),
            "raw_value": som,
            "formula": "sam * share_pct",
            "inputs": {"sam": fmt(sam), "share_pct": share_pct},
        },
    }

    if tam_projected is not None:
        assert sam_projected is not None
        assert som_projected is not None
        result["projected"] = {
            "years": years,
            "growth_rate_pct": growth_rate,
            "tam": fmt(tam_projected),
            "sam": fmt(sam_projected),
            "som": fmt(som_projected),
        }

    return result


def bottom_up(
    customer_count: int,
    arpu: float,
    serviceable_pct: float,
    target_pct: float,
    growth_rate: float | None = None,
    years: int = 0,
) -> dict[str, Any]:
    """Bottom-up market sizing: start from customers and pricing."""
    svc = serviceable_pct / 100
    tgt = target_pct / 100

    tam = customer_count * arpu
    serviceable_customers = customer_count * svc
    sam = serviceable_customers * arpu
    target_customers = serviceable_customers * tgt
    som = target_customers * arpu

    result: dict[str, Any] = {
        "tam": {
            "value": fmt(tam),
            "raw_value": tam,
            "formula": "customer_count * arpu",
            "inputs": {"customer_count": customer_count, "arpu": arpu},
        },
        "sam": {
            "value": fmt(sam),
            "raw_value": sam,
            "formula": "serviceable_customers * arpu",
            "inputs": {
                "serviceable_customers": serviceable_customers,
                "serviceable_pct": serviceable_pct,
                "arpu": arpu,
            },
        },
        "som": {
            "value": fmt(som),
            "raw_value": som,
            "formula": "target_customers * arpu",
            "inputs": {
                "target_customers": target_customers,
                "target_pct": target_pct,
                "arpu": arpu,
            },
        },
    }

    if years < 0:
        print(f"Warning: years is negative ({years}), ignoring growth projection", file=sys.stderr)
        years = 0
    if growth_rate is not None and years > 0:
        g = 1 + growth_rate / 100
        result["projected"] = {
            "years": years,
            "growth_rate_pct": growth_rate,
            "tam": fmt(tam * (g**years)),
            "sam": fmt(sam * (g**years)),
            "som": fmt(som * (g**years)),
        }

    return result


def compare(td: dict[str, Any], bu: dict[str, Any]) -> dict[str, Any]:
    """Compare top-down and bottom-up TAM/SAM/SOM estimates.

    TAM is always compared (both approaches always produce it). SAM and SOM are
    compared whenever both approaches produced them (always true for top_down()/
    bottom_up() output) — previously only TAM was gated, so an order-of-magnitude
    SAM/SOM gap between the two methods could be presented as equally defensible.
    """
    td_tam = td["tam"].get("raw_value", td["tam"]["value"])
    bu_tam = bu["tam"].get("raw_value", bu["tam"]["value"])

    if td_tam == 0 and bu_tam == 0:
        result: dict[str, Any] = {"tam_delta_pct": 0, "note": "Both TAM values are zero."}
    else:
        avg = (td_tam + bu_tam) / 2
        delta_pct = abs(td_tam - bu_tam) / avg * 100 if avg != 0 else 0

        result = {
            "top_down_tam": td_tam,
            "bottom_up_tam": bu_tam,
            "tam_delta_pct": round(delta_pct, 1),
        }

        if delta_pct > 30:
            result["warning"] = (
                f"Top-down and bottom-up TAM differ by {result['tam_delta_pct']}% "
                f"(>{30}%). Review assumptions — one approach likely has a flawed input."
            )
        elif delta_pct > 15:
            result["note"] = (
                f"TAM estimates differ by {result['tam_delta_pct']}%. "
                "Moderate discrepancy — worth investigating but not alarming."
            )
        else:
            result["note"] = f"TAM estimates differ by only {result['tam_delta_pct']}%. Good convergence."

    for metric in ("sam", "som"):
        td_metric = td.get(metric)
        bu_metric = bu.get(metric)
        if not td_metric or not bu_metric:
            continue
        td_val = td_metric.get("raw_value", td_metric.get("value"))
        bu_val = bu_metric.get("raw_value", bu_metric.get("value"))

        if td_val == 0 and bu_val == 0:
            result[f"{metric}_delta_pct"] = 0
            result[f"{metric}_note"] = f"Both {metric.upper()} values are zero."
            continue

        m_avg = (td_val + bu_val) / 2
        m_delta_pct = abs(td_val - bu_val) / m_avg * 100 if m_avg != 0 else 0

        result[f"top_down_{metric}"] = td_val
        result[f"bottom_up_{metric}"] = bu_val
        result[f"{metric}_delta_pct"] = round(m_delta_pct, 1)

        if m_delta_pct > 30:
            result[f"{metric}_warning"] = (
                f"Top-down and bottom-up {metric.upper()} differ by {result[f'{metric}_delta_pct']}% "
                f"(>{30}%). Review assumptions — one approach likely has a flawed input."
            )
        elif m_delta_pct > 15:
            result[f"{metric}_note"] = (
                f"{metric.upper()} estimates differ by {result[f'{metric}_delta_pct']}%. "
                "Moderate discrepancy — worth investigating but not alarming."
            )
        else:
            result[f"{metric}_note"] = (
                f"{metric.upper()} estimates differ by only {result[f'{metric}_delta_pct']}%. Good convergence."
            )

    return result


def _validate_inputs(
    data: dict[str, Any] | None,
    args: argparse.Namespace,
    approach: str,
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    """Validate and parse all inputs. Returns (parsed, errors, warnings).

    Handles coercion (stdin strings → numeric) and range validation.
    """
    errors: list[str] = []
    warnings: list[dict[str, str]] = []
    parsed: dict[str, Any] = {}

    def _pct_warn(field: str, value: float) -> None:
        # WB-1: a fractional-percentage plausibility warning must PERSIST into the
        # artifact (validation.warnings), not just stderr — a stderr-only warning
        # leaves validation.status "valid" and the founder never sees it (the exact
        # silent-100x class). Emit to both.
        w = check_pct_plausibility(field, value)
        if w:
            warnings.append({"code": "IMPLAUSIBLE_PCT_SCALE", "field": field, "message": w})
            print(f"Warning: {w}", file=sys.stderr)

    if not isinstance(args.currency, str) or not args.currency.strip():
        errors.append("currency must be a non-empty string")

    # sizing_basis is optional — None (not declared) is valid. Only a non-None,
    # non-enum value is an error; there is no "must be present" requirement here,
    # unlike currency, because omission has a defined meaning downstream (render
    # as "not declared") rather than needing a fallback.
    sizing_basis = getattr(args, "sizing_basis", None)
    if sizing_basis is not None and sizing_basis not in VALID_SIZING_BASIS:
        errors.append(f"sizing_basis must be one of {sorted(VALID_SIZING_BASIS)} (got {sizing_basis!r})")

    if approach in ("top-down", "both"):
        if data is not None:
            it = data.get("industry_total")
            sp = data.get("segment_pct")
            shp = data.get("share_pct")
            gr = data.get("growth_rate")
            yr = data.get("years", 0)
        else:
            it, sp, shp = args.industry_total, args.segment_pct, args.share_pct
            gr, yr = args.growth_rate, args.years

        if it is None or sp is None or shp is None:
            missing = [k for k, v in [("industry_total", it), ("segment_pct", sp), ("share_pct", shp)] if v is None]
            if data is not None:
                errors.append(f"top-down requires JSON keys: {', '.join(missing)}")
            else:
                errors.append("top-down requires --industry-total, --segment-pct, --share-pct")
        else:
            # Coerce JSON string values to numeric types
            td_ok = True
            if data is not None:
                it, err = coerce_float("industry_total", it)
                if err:
                    errors.append(err)
                    td_ok = False
                sp, err = coerce_float("segment_pct", sp)
                if err:
                    errors.append(err)
                    td_ok = False
                shp, err = coerce_float("share_pct", shp)
                if err:
                    errors.append(err)
                    td_ok = False
                if gr is not None:
                    gr, err = coerce_float("growth_rate", gr)
                    if err:
                        errors.append(err)
                        td_ok = False
                yr, err = coerce_int("years", yr)
                if err:
                    errors.append(err)
                    td_ok = False

            # Validate ranges only if coercion succeeded
            if td_ok:
                err = validate_positive("industry_total", it)
                if err:
                    errors.append(err)
                err = validate_pct("segment_pct", sp)
                if err:
                    errors.append(err)
                else:
                    _pct_warn("segment_pct", sp)
                err = validate_pct("share_pct", shp)
                if err:
                    errors.append(err)
                else:
                    _pct_warn("share_pct", shp)
                if gr is not None and gr < -100:
                    errors.append(f"growth_rate cannot be below -100% (got {gr}%)")

            parsed["td"] = (it, sp, shp, gr, yr)

    if approach in ("bottom-up", "both"):
        if data is not None:
            cc = data.get("customer_count")
            arpu = data.get("arpu")
            svcp = data.get("serviceable_pct")
            tgtp = data.get("target_pct")
            gr = data.get("growth_rate")
            yr = data.get("years", 0)
        else:
            cc, arpu = args.customer_count, args.arpu
            svcp, tgtp = args.serviceable_pct, args.target_pct
            gr, yr = args.growth_rate, args.years

        if cc is None or arpu is None or svcp is None or tgtp is None:
            pairs = [("customer_count", cc), ("arpu", arpu), ("serviceable_pct", svcp), ("target_pct", tgtp)]
            missing = [k for k, v in pairs if v is None]
            if data is not None:
                errors.append(f"bottom-up requires JSON keys: {', '.join(missing)}")
            else:
                errors.append("bottom-up requires --customer-count, --arpu, --serviceable-pct, --target-pct")
        else:
            # In "both" mode the top-down block already coerced and range-checked
            # growth_rate/years from the same raw keys — reuse its result to avoid
            # appending identical errors twice.
            growth_already_validated = approach == "both" and "td" in parsed
            if growth_already_validated:
                gr, yr = parsed["td"][3], parsed["td"][4]

            # Coerce JSON string values to numeric types
            bu_ok = True
            if data is not None:
                cc, err = coerce_int("customer_count", cc)
                if err:
                    errors.append(err)
                    bu_ok = False
                arpu, err = coerce_float("arpu", arpu)
                if err:
                    errors.append(err)
                    bu_ok = False
                svcp, err = coerce_float("serviceable_pct", svcp)
                if err:
                    errors.append(err)
                    bu_ok = False
                tgtp, err = coerce_float("target_pct", tgtp)
                if err:
                    errors.append(err)
                    bu_ok = False
                if not growth_already_validated:
                    if gr is not None:
                        gr, err = coerce_float("growth_rate", gr)
                        if err:
                            errors.append(err)
                            bu_ok = False
                    yr, err = coerce_int("years", yr)
                    if err:
                        errors.append(err)
                        bu_ok = False

            # Validate ranges only if coercion succeeded
            if bu_ok:
                err = validate_positive("customer_count", cc)
                if err:
                    errors.append(err)
                err = validate_positive("arpu", arpu)
                if err:
                    errors.append(err)
                err = validate_pct("serviceable_pct", svcp)
                if err:
                    errors.append(err)
                else:
                    _pct_warn("serviceable_pct", svcp)
                err = validate_pct("target_pct", tgtp)
                if err:
                    errors.append(err)
                else:
                    _pct_warn("target_pct", tgtp)
                if not growth_already_validated and gr is not None and gr < -100:
                    errors.append(f"growth_rate cannot be below -100% (got {gr}%)")

            parsed["bu"] = (cc, arpu, svcp, tgtp, gr, yr)

    return parsed, errors, warnings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TAM/SAM/SOM market sizing calculator")
    p.add_argument(
        "--approach",
        choices=["top-down", "bottom-up", "both"],
        default="both",
        help="Calculation approach",
    )
    p.add_argument("--stdin", action="store_true", help="Read JSON input from stdin")

    # Top-down args
    p.add_argument("--industry-total", type=float, help="Total industry revenue ($)")
    p.add_argument("--segment-pct", type=float, help="Target segment as %% of TAM")
    p.add_argument("--share-pct", type=float, help="Expected market share as %% of SAM")

    # Bottom-up args
    p.add_argument("--customer-count", type=int, help="Total potential customers")
    p.add_argument("--arpu", type=float, help="Average revenue per user/customer ($)")
    p.add_argument("--serviceable-pct", type=float, help="Serviceable customers as %% of total")
    p.add_argument("--target-pct", type=float, help="Target customers as %% of serviceable")

    # Growth projection
    p.add_argument("--growth-rate", type=float, help="Annual growth rate %%")
    p.add_argument("--years", type=int, default=0, help="Years to project forward")

    # Output
    p.add_argument(
        "--currency",
        default=None,
        help=(
            "ISO currency label for every money figure, e.g. EUR / ILS (default: USD). "
            "No FX conversion is ever performed — this labels the figures you supply."
        ),
    )
    p.add_argument(
        "--sizing-basis",
        default=None,
        help=(
            "Convention this analysis' figures follow: current_year | forecast_year | mixed. "
            "No default — an unset basis is omitted from the output and must render as "
            "'not declared' downstream, never silently as current_year."
        ),
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", help="Inject metadata.run_id into output (for stale-artifact detection)")

    return p.parse_args()


def _stamp_run_id(result: dict[str, Any], run_id: str | None) -> dict[str, Any]:
    """Stamp metadata.run_id into a result dict (last step before serialization)."""
    if run_id:
        result["metadata"] = {"run_id": run_id}
    return result


def main() -> None:
    args = parse_args()
    indent = 2 if args.pretty else None

    if args.stdin:
        # --- Infrastructure checks (sys.exit(1)) ---
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON input: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, dict):
            print("Error: JSON input must be an object", file=sys.stderr)
            sys.exit(1)

        # --- Validation starts here (JSON error dict, exit 0) ---
        raw_approach = data.get("approach", "both")
        if not isinstance(raw_approach, str):
            result: dict[str, Any] = {
                "validation": {
                    "status": "invalid",
                    "errors": [f"approach must be a string (got {type(raw_approach).__name__})"],
                }
            }
            _write_output(json.dumps(_stamp_run_id(result, args.run_id), indent=indent) + "\n", args.output)
            return
        approach = raw_approach.replace("_", "-")
    else:
        data = None
        approach = args.approach

    valid_approaches = {"top-down", "bottom-up", "both"}
    if approach not in valid_approaches:
        result = {
            "validation": {
                "status": "invalid",
                "errors": [f"approach must be one of {sorted(valid_approaches)} (got '{approach}')"],
            }
        }
        _write_output(json.dumps(_stamp_run_id(result, args.run_id), indent=indent) + "\n", args.output)
        return

    # Resolve the currency label. An explicit --currency always wins; otherwise a
    # `currency` key in the piped JSON is honoured, so a sub-agent's hand-off (or a
    # merge_json.py --set) can carry the analysis currency through without the
    # caller having to remember the flag. Falls back to USD.
    if args.currency is None:
        stdin_currency = data.get("currency") if isinstance(data, dict) else None
        args.currency = stdin_currency if isinstance(stdin_currency, str) and stdin_currency.strip() else "USD"
    if isinstance(args.currency, str) and args.currency.strip():
        args.currency = args.currency.strip().upper()

    # Resolve sizing_basis the same way (explicit --flag wins, then the piped
    # JSON's key) but WITHOUT a fallback default — unlike currency there is no
    # "USD" equivalent to fall back to; an unset basis stays None and is simply
    # omitted from the output (see VALID_SIZING_BASIS comment above).
    if args.sizing_basis is None:
        stdin_sizing_basis = data.get("sizing_basis") if isinstance(data, dict) else None
        args.sizing_basis = (
            stdin_sizing_basis if isinstance(stdin_sizing_basis, str) and stdin_sizing_basis.strip() else None
        )
    if isinstance(args.sizing_basis, str):
        args.sizing_basis = args.sizing_basis.strip().lower() or None

    parsed, errors, input_warnings = _validate_inputs(data, args, approach)

    if errors:
        result = {"validation": {"status": "invalid", "errors": errors, "warnings": input_warnings}}
    else:
        result = {"approach": approach, "currency": args.currency}
        if args.sizing_basis is not None:
            result["sizing_basis"] = args.sizing_basis

        if approach in ("top-down", "both"):
            it, sp, shp, gr, yr = parsed["td"]
            result["top_down"] = top_down(it, sp, shp, gr, yr)

        if approach in ("bottom-up", "both"):
            cc, arpu_val, svcp, tgtp, gr, yr = parsed["bu"]
            result["bottom_up"] = bottom_up(cc, arpu_val, svcp, tgtp, gr, yr)

        if approach == "both" and "top_down" in result and "bottom_up" in result:
            result["comparison"] = compare(result["top_down"], result["bottom_up"])

        result["validation"] = {"status": "valid", "errors": [], "warnings": input_warnings}

    _stamp_run_id(result, args.run_id)
    out = json.dumps(result, indent=indent) + "\n"
    _write_output(out, args.output, summary={"approach": approach})


if __name__ == "__main__":
    main()
