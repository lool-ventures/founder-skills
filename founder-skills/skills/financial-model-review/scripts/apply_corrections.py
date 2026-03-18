#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Apply founder corrections from the review playground artifact.

Reads a corrections JSON file (downloaded by the founder from the JSX artifact),
performs coercion, ILS normalization, time-series canonicalization, override
merging, and writes corrected_inputs.json + extraction_corrections.json.

Usage:
    python apply_corrections.py <corrections.json> --original <inputs.json> --output-dir <dir>

Output:
    stdout: {"status": "completed"|"error", "correction_count": N, ...}
    files:  corrected_inputs.json, extraction_corrections.json (in output-dir)
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Path navigation (shared with review_inputs.py)
# ---------------------------------------------------------------------------


def _navigate_part(obj: Any, part: str) -> Any:
    if obj is None or not isinstance(obj, dict):
        return None
    if "[" not in part:
        return obj.get(part)
    name, rest = part.split("[", 1)
    selector = rest.rstrip("]")
    arr = obj.get(name)
    if not isinstance(arr, list):
        return None
    if "=" in selector:
        k, v = selector.split("=", 1)
        return next((item for item in arr if isinstance(item, dict) and str(item.get(k)) == v), None)
    idx = int(selector) if selector.isdigit() else -1
    return arr[idx] if 0 <= idx < len(arr) else None


def _deep_get(data: dict[str, Any], dotted_path: str) -> Any:
    obj: Any = data
    for part in dotted_path.split("."):
        obj = _navigate_part(obj, part)
    return obj


def _set_by_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    obj: Any = data
    for part in parts[:-1]:
        nxt = _navigate_part(obj, part)
        if nxt is None:
            if "[" not in part and isinstance(obj, dict):
                obj[part] = {}
                nxt = obj[part]
            else:
                return
        obj = nxt
    last = parts[-1]
    if "[" not in last and isinstance(obj, dict):
        obj[last] = value


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------

_NUMERIC_PATHS = [
    "cash.current_balance",
    "cash.monthly_net_burn",
    "cash.debt",
    "revenue.mrr.value",
    "revenue.arr.value",
    "revenue.customers",
    "revenue.growth_rate_monthly",
    "revenue.churn_monthly",
    "revenue.nrr",
    "revenue.grr",
    "revenue.monthly_total",
    "cash.fundraising.target_raise",
    "cash.grants.iia_approved",
    "cash.grants.iia_pending",
    "cash.grants.iia_disbursement_months",
    "cash.grants.iia_start_month",
    "cash.grants.royalty_rate",
    "unit_economics.cac.total",
    "unit_economics.ltv.value",
    "unit_economics.ltv.inputs.arpu_monthly",
    "unit_economics.ltv.inputs.churn_monthly",
    "unit_economics.ltv.inputs.gross_margin",
    "unit_economics.gross_margin",
    "unit_economics.payback_months",
    "unit_economics.burn_multiple",
    "israel_specific.fx_rate_ils_usd",
    "israel_specific.ils_expense_fraction",
    "scenarios.base.growth_rate",
    "scenarios.base.burn_change",
    "scenarios.slow.growth_rate",
    "scenarios.slow.burn_change",
    "scenarios.crisis.growth_rate",
    "scenarios.crisis.burn_change",
    "bridge.runway_target_months",
]


def _coerce_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for path in _NUMERIC_PATHS:
        val = _deep_get(state, path)
        if val is None or isinstance(val, (int, float)):
            continue
        if isinstance(val, str):
            cleaned = val.strip().replace(",", "")
            if not cleaned or cleaned == "-" or cleaned == "\u2014":
                _set_by_path(state, path, None)
                continue
            try:
                n = float(cleaned)
                _set_by_path(state, path, int(n) if n == int(n) else n)
            except (ValueError, OverflowError):
                errors.append(
                    {
                        "code": "COERCION_ERROR",
                        "message": f"Cannot convert '{val}' to number",
                        "field": path,
                        "layer": 0,
                    }
                )
        else:
            errors.append(
                {
                    "code": "COERCION_ERROR",
                    "message": f"Expected number, got {type(val).__name__}",
                    "field": path,
                    "layer": 0,
                }
            )

    # Headcount array
    headcount = _deep_get(state, "expenses.headcount")
    if isinstance(headcount, list):
        for i, h in enumerate(headcount):
            if not isinstance(h, dict):
                continue
            for fld in ("count", "salary_annual", "burden_pct"):
                val = h.get(fld)
                if val is None or isinstance(val, (int, float)):
                    continue
                if isinstance(val, str):
                    cleaned = val.strip().replace(",", "")
                    if not cleaned or cleaned == "-":
                        h[fld] = None
                        continue
                    try:
                        n = float(cleaned)
                        h[fld] = int(n) if n == int(n) else n
                    except (ValueError, OverflowError):
                        errors.append(
                            {
                                "code": "COERCION_ERROR",
                                "message": f"Cannot convert '{val}' to number",
                                "field": f"expenses.headcount[{i}].{fld}",
                                "layer": 0,
                            }
                        )

    # Opex array
    opex = _deep_get(state, "expenses.opex_monthly")
    if isinstance(opex, list):
        for i, e in enumerate(opex):
            if not isinstance(e, dict):
                continue
            val = e.get("amount")
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if not cleaned or cleaned == "-":
                    e["amount"] = None
                    continue
                try:
                    n = float(cleaned)
                    e["amount"] = int(n) if n == int(n) else n
                except (ValueError, OverflowError):
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number",
                            "field": f"expenses.opex_monthly[{i}].amount",
                            "layer": 0,
                        }
                    )

    # COGS dict
    cogs = _deep_get(state, "expenses.cogs")
    if isinstance(cogs, dict):
        for k, val in cogs.items():
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if not cleaned or cleaned == "-":
                    cogs[k] = None
                    continue
                try:
                    n = float(cleaned)
                    cogs[k] = int(n) if n == int(n) else n
                except (ValueError, OverflowError):
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number",
                            "field": f"expenses.cogs.{k}",
                            "layer": 0,
                        }
                    )

    # Boolean coercion for time-series actual fields
    for ts_path in ("revenue.monthly", "revenue.quarterly"):
        arr = _deep_get(state, ts_path)
        if not isinstance(arr, list):
            continue
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            actual = entry.get("actual")
            if isinstance(actual, str):
                if actual.lower() == "true":
                    entry["actual"] = True
                elif actual.lower() == "false":
                    entry["actual"] = False

    return errors


# ---------------------------------------------------------------------------
# ILS normalization
# ---------------------------------------------------------------------------


def _normalize_to_usd(state: dict[str, Any], ils_fields: dict[str, bool]) -> None:
    fx = _deep_get(state, "israel_specific.fx_rate_ils_usd")
    if not isinstance(fx, (int, float)) or fx <= 0:
        return
    for field, is_ils in ils_fields.items():
        if not is_ils:
            continue
        val = _deep_get(state, field)
        if isinstance(val, (int, float)):
            _set_by_path(state, field, round(val / fx, 2))


# ---------------------------------------------------------------------------
# Time-series
# ---------------------------------------------------------------------------


def _canonicalize_time_series(state: dict[str, Any]) -> None:
    monthly = _deep_get(state, "revenue.monthly")
    if isinstance(monthly, list):
        monthly.sort(key=lambda e: e.get("month", "") if isinstance(e, dict) else "")
    quarterly = _deep_get(state, "revenue.quarterly")
    if isinstance(quarterly, list):
        quarterly.sort(key=lambda e: e.get("quarter", "") if isinstance(e, dict) else "")


_YYYY_MM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_YYYY_QN_RE = re.compile(r"^\d{4}-Q[1-4]$")


def _validate_time_series_keys(state: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    monthly = _deep_get(state, "revenue.monthly")
    if isinstance(monthly, list):
        for i, entry in enumerate(monthly):
            if not isinstance(entry, dict):
                continue
            m = entry.get("month")
            if m is not None and not _YYYY_MM_RE.match(str(m)):
                errors.append(
                    {
                        "code": "DATE_FORMAT_ERROR",
                        "message": f"Invalid month '{m}', expected YYYY-MM",
                        "field": f"revenue.monthly[{i}].month",
                        "layer": 0,
                    }
                )
    quarterly = _deep_get(state, "revenue.quarterly")
    if isinstance(quarterly, list):
        for i, entry in enumerate(quarterly):
            if not isinstance(entry, dict):
                continue
            q = entry.get("quarter")
            if q is not None and not _YYYY_QN_RE.match(str(q)):
                errors.append(
                    {
                        "code": "DATE_FORMAT_ERROR",
                        "message": f"Invalid quarter '{q}', expected YYYY-QN",
                        "field": f"revenue.quarterly[{i}].quarter",
                        "layer": 0,
                    }
                )
    return errors


# ---------------------------------------------------------------------------
# Override merging
# ---------------------------------------------------------------------------


def _merge_overrides(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, Any] = {}
    agent_keys: set[str] = set()
    for o in existing:
        k = f"{o.get('code', '')}|{o.get('field', '')}"
        merged[k] = o
        if o.get("reviewed_by") == "agent":
            agent_keys.add(k)
    for o in incoming:
        k = f"{o.get('code', '')}|{o.get('field', '')}"
        if k in agent_keys and o.get("reviewed_by") != "agent":
            continue
        merged[k] = o
    return list(merged.values())


# ---------------------------------------------------------------------------
# Row ID stripping
# ---------------------------------------------------------------------------

_ARRAY_PATHS = (
    "expenses.headcount",
    "expenses.opex_monthly",
    "revenue.monthly",
    "revenue.quarterly",
)


def _strip_row_ids(state: dict[str, Any]) -> None:
    for arr_path in _ARRAY_PATHS:
        arr = _deep_get(state, arr_path)
        if isinstance(arr, list):
            for entry in arr:
                if isinstance(entry, dict):
                    entry.pop("_row_id", None)


# ---------------------------------------------------------------------------
# Patch-based flow
# ---------------------------------------------------------------------------


def _canonical_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _apply_patches(
    original: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply patch-based changes to a deep copy of original.

    Returns (patched_state, corrections_for_audit, errors).
    """
    errors: list[dict[str, Any]] = []

    # Verify base_hash — required for new-style payloads
    base_hash = payload.get("base_hash")
    if base_hash is None:
        errors.append(
            {
                "code": "MISSING_BASE_HASH",
                "message": "base_hash is required for patch-based corrections",
                "field": "",
                "layer": 0,
            }
        )
        return {}, [], errors
    actual_hash = _canonical_hash(original)
    if base_hash != actual_hash:
        errors.append(
            {
                "code": "STALE_BASE",
                "message": f"Base hash mismatch — original has changed since review page was loaded. "
                f"Expected {base_hash[:20]}..., got {actual_hash[:20]}...",
                "field": "",
                "layer": 0,
            }
        )
        return {}, [], errors

    state = copy.deepcopy(original)
    changes = payload.get("changes", [])
    corrections: list[dict[str, Any]] = []

    for ch in changes:
        path = ch.get("path", "")
        expected_old = ch.get("expected_old")
        new_val = ch.get("new")
        change_type = ch.get("type", "scalar")

        # --- Path validation (applies to ALL change types) ---
        # Verify the path exists in original before writing.
        # _set_by_path auto-creates missing dict segments, so a typo like
        # "revenue.mrr.valeu" or "expenses.headcout" would silently add a
        # new key. We check the leaf key exists in its parent object.
        # This correctly handles null values (key exists, value is None).
        parts = path.split(".")
        leaf = parts[-1]
        parent_path = ".".join(parts[:-1])
        parent_obj = _deep_get(original, parent_path) if parent_path else original
        if not isinstance(parent_obj, dict) or leaf not in parent_obj:
            errors.append(
                {
                    "code": "PATH_ERROR",
                    "message": f"Path '{path}' does not exist in original — possible typo",
                    "field": path,
                    "layer": 0,
                }
            )
            continue

        actual_old = _deep_get(state, path)

        if change_type == "replace_array":
            # For array replacements, expected_old is the array length
            actual_len = len(actual_old) if isinstance(actual_old, list) else 0
            if expected_old is not None and actual_len != expected_old:
                errors.append(
                    {
                        "code": "STALE_EDIT",
                        "message": f"Stale array edit at '{path}': expected length {expected_old}, found {actual_len}",
                        "field": path,
                        "layer": 0,
                    }
                )
                continue
            _set_by_path(state, path, new_val)
            new_len = len(new_val) if isinstance(new_val, list) else 0
            corrections.append(
                {
                    "path": path,
                    "type": "replace_array",
                    "was_length": actual_len,
                    "now_length": new_len,
                }
            )
            continue

        # Scalar change — verify expected_old matches (skip check if None)
        if expected_old is not None and actual_old != expected_old:
            # Tolerance for float comparison
            if isinstance(actual_old, (int, float)) and isinstance(expected_old, (int, float)):
                if abs(float(actual_old) - float(expected_old)) <= 0.01:
                    pass  # within tolerance, proceed
                else:
                    errors.append(
                        {
                            "code": "STALE_EDIT",
                            "message": f"Stale edit at '{path}': expected {expected_old}, found {actual_old}",
                            "field": path,
                            "layer": 0,
                        }
                    )
                    continue
            else:
                errors.append(
                    {
                        "code": "STALE_EDIT",
                        "message": f"Stale edit at '{path}': expected {expected_old}, found {actual_old}",
                        "field": path,
                        "layer": 0,
                    }
                )
                continue

        _set_by_path(state, path, new_val)
        corrections.append({"path": path, "was": actual_old, "now": new_val})

    if errors:
        return {}, [], errors

    return state, corrections, []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply founder corrections")
    parser.add_argument("corrections", help="Path to corrections JSON file")
    parser.add_argument("--original", required=True, help="Path to original inputs.json")
    parser.add_argument("--output-dir", required=True, help="Directory for output files")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON")
    args = parser.parse_args()

    with open(args.corrections, encoding="utf-8") as f:
        payload = json.load(f)
    with open(args.original, encoding="utf-8") as f:
        original = json.load(f)

    # Detect payload shape: new (changes[]) vs legacy (corrected{})
    if "changes" in payload:
        corrected, corrections, patch_errors = _apply_patches(original, payload)
        if patch_errors:
            json.dump({"status": "error", "errors": patch_errors}, sys.stdout, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            sys.exit(1)
    elif "corrected" in payload:
        print("Warning: legacy payload format — using 'corrected' object directly", file=sys.stderr)
        corrections = payload.get("corrections", [])
        corrected = payload["corrected"]
    else:
        err = {
            "status": "error",
            "errors": [
                {
                    "code": "INVALID_PAYLOAD",
                    "message": "Payload must contain 'changes' or 'corrected'",
                    "field": "",
                    "layer": 0,
                }
            ],
        }
        json.dump(err, sys.stdout, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        sys.exit(1)

    overrides = payload.get("warning_overrides", [])
    ils_fields = payload.get("ils_fields", {})

    # 1. Coerce
    coercion_errors = _coerce_state(corrected)

    # 2. Validate time-series keys
    ts_errors = _validate_time_series_keys(corrected)

    all_errors = coercion_errors + ts_errors
    if all_errors:
        json.dump({"status": "error", "errors": all_errors}, sys.stdout, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        sys.exit(1)

    # 3. Normalize ILS → USD
    _normalize_to_usd(corrected, ils_fields)

    # 4. Canonicalize time-series
    _canonicalize_time_series(corrected)

    # 5. Preserve run_id
    orig_metadata = original.get("metadata", {})
    corrected_metadata = corrected.get("metadata", {})
    if not isinstance(corrected_metadata, dict):
        corrected_metadata = {}
    if "run_id" in orig_metadata and "run_id" not in corrected_metadata:
        corrected_metadata["run_id"] = orig_metadata["run_id"]

    # 6. Merge overrides
    existing_overrides = orig_metadata.get("warning_overrides", [])
    if overrides or existing_overrides:
        corrected_metadata["warning_overrides"] = _merge_overrides(existing_overrides, overrides)
    corrected["metadata"] = corrected_metadata

    # 7. Strip _row_ids
    _strip_row_ids(corrected)

    # 8. Write files
    os.makedirs(args.output_dir, exist_ok=True)

    corrected_path = os.path.join(args.output_dir, "corrected_inputs.json")
    with open(corrected_path, "w", encoding="utf-8") as f:
        json.dump(corrected, f, indent=2)

    overrides_added = [{"code": o.get("code"), "field": o.get("field"), "reason": o.get("reason")} for o in overrides]
    audit = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_file": "inputs.json",
        "correction_count": len(corrections),
        "corrections": corrections,
        "override_count": len(overrides_added),
        "overrides_added": overrides_added,
    }
    audit_path = os.path.join(args.output_dir, "extraction_corrections.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)

    # 9. Stdout result
    result = {
        "status": "completed",
        "correction_count": len(corrections),
        "corrected_inputs": corrected_path,
        "extraction_corrections": audit_path,
    }
    json.dump(result, sys.stdout, indent=2 if args.pretty else None)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
