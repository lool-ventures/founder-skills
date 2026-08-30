#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Validates inputs.json for the financial model review skill.

Runs 4 validation layers: structural, consistency, sanity, completeness.
Reads JSON from stdin, outputs validation JSON to stdout.

Usage:
    echo '{"company": {...}, "cash": {...}, ...}' \
        | python validate_inputs.py --pretty

    echo '{"cash": {"monthly_net_burn": -50000}, ...}' \
        | python validate_inputs.py --fix --pretty

Output: {"valid": bool, "errors": [...], "warnings": [...], "auto_fixes": [...]}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


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


# ---------------------------------------------------------------------------
# Safe accessors
# ---------------------------------------------------------------------------


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _num(x: Any, default: float) -> float:
    """Coerce x to a numeric value, falling back to default for null/non-numeric.

    The dict.get() default only applies to missing keys, not to keys present
    with an explicit JSON null. Used inside sanity arithmetic so a present-but-
    null headcount cell is reported (Layer 1 TYPE_ERROR) rather than crashing.
    """
    if isinstance(x, bool):
        return default
    if isinstance(x, (int, float)):
        return x
    return default


def _deep_get_by_path(data: dict[str, Any], dotted_path: str) -> Any:
    """Navigate nested dict by dotted path like 'cash.monthly_net_burn'."""
    obj: Any = data
    for part in dotted_path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

# The stage ladder, lowest to highest. Every stage the shared founder context
# admits appears here, and the seed+/series-a+ groups below are DERIVED from it
# rather than written out — a hand-written membership set omits whatever stage
# nobody thought about, and it fails open: an unlisted stage falls through to
# the lowest branch and is silently held to no threshold at all.
_STAGE_LADDER = (
    "pre-seed",
    "seed",
    "series-a",
    "series-b",
    "series-c",
    "series-d",
    "later",
)

# Fields that feed a COMPUTATION rather than merely describing the company, so a
# silently-defaulted value changes an output the founder reads. Kept short and
# explicit — this is a disclosure list, not a schema.
_COMPUTATION_FEEDING_FIELDS = (
    "bridge.runway_target_months",
    "bridge.raise_amount",
    "fundraising.target_raise",
    "fundraising.expected_close",
    "growth.growth_rate_monthly",
)


def _stages_at_or_above(stage: str) -> frozenset[str]:
    """Every ladder stage from *stage* upward.

    Excluding a stage below the floor is the point — pre-seed is absent from
    _SEED_PLUS by construction, not by omission, and stays absent when the
    ladder grows.
    """
    return frozenset(_STAGE_LADDER[_STAGE_LADDER.index(stage) :])


_SEED_PLUS = _stages_at_or_above("seed")
_SERIES_A_PLUS = _stages_at_or_above("series-a")


def _stage_in(stage: str | None, group: frozenset[str]) -> bool:
    """Return True if *stage* (lowercased) is in *group*."""
    if stage is None:
        return False
    return stage.lower().strip() in group


def _arpu_monthly(inputs: dict[str, Any]) -> Any:
    """Read ARPU with fallback from old schema name."""
    val = _deep_get(inputs, "unit_economics", "ltv", "inputs", "arpu_monthly")
    if val is None:
        val = _deep_get(inputs, "unit_economics", "ltv", "inputs", "arpu")
    return val


# ---------------------------------------------------------------------------
# Layer 1 — Structural
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS: list[tuple[str, ...]] = [
    ("cash", "current_balance"),
    ("cash", "monthly_net_burn"),
    ("revenue", "mrr", "value"),
    ("revenue", "arr", "value"),
    ("revenue", "growth_rate_monthly"),
    ("revenue", "nrr"),
    ("revenue", "grr"),
    ("unit_economics", "gross_margin"),
    ("unit_economics", "payback_months"),
]


def _validate_structural(
    inputs: dict[str, Any],
    *,
    fix: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Layer 1: type correctness and sign checks."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []

    # --- Type correctness for numeric fields ---
    for path in _NUMERIC_FIELDS:
        val = _deep_get(inputs, *path)
        if val is None:
            continue
        if not isinstance(val, (int, float)):
            errors.append(
                {
                    "code": "TYPE_ERROR",
                    "message": f"Field '{'.'.join(path)}' must be numeric, got {type(val).__name__}",
                    "field": ".".join(path),
                    "layer": 1,
                }
            )

    # --- Type correctness for headcount numeric cells ---
    # Present-but-null count/salary_annual cells (produced by the corrections
    # coercion layer for blank fields) make the entry unusable and would crash
    # the downstream Layer-3 sanity arithmetic; report them here as TYPE_ERROR.
    headcount_entries = _deep_get(inputs, "expenses", "headcount")
    if isinstance(headcount_entries, list):
        for idx, entry in enumerate(headcount_entries):
            if not isinstance(entry, dict):
                continue
            for hc_field in ("count", "salary_annual"):
                if hc_field not in entry:
                    continue
                cell = entry[hc_field]
                if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                    field_path = f"expenses.headcount[{idx}].{hc_field}"
                    got = "null" if cell is None else type(cell).__name__
                    errors.append(
                        {
                            "code": "TYPE_ERROR",
                            "message": f"Field '{field_path}' must be numeric, got {got}",
                            "field": field_path,
                            "layer": 1,
                        }
                    )

    # --- Burn sign check ---
    burn = _deep_get(inputs, "cash", "monthly_net_burn")
    if isinstance(burn, (int, float)) and burn < 0:
        if fix:
            new_val = abs(burn)
            fixes.append(
                {
                    "code": "BURN_SIGN_ERROR",
                    "field": "cash.monthly_net_burn",
                    "old_value": burn,
                    "new_value": new_val,
                }
            )
            # Apply the fix in-place
            if isinstance(inputs.get("cash"), dict):
                inputs["cash"]["monthly_net_burn"] = new_val
        else:
            errors.append(
                {
                    "code": "BURN_SIGN_ERROR",
                    "message": "Monthly net burn must be a positive number (auto-fix can correct the sign)",
                    "field": "cash.monthly_net_burn",
                    "layer": 1,
                }
            )

    # --- warning_overrides structural validation ---
    metadata = inputs.get("metadata")
    if isinstance(metadata, dict):
        overrides = metadata.get("warning_overrides")
        if isinstance(overrides, list):
            _REQUIRED_OVERRIDE_KEYS = {"code", "reason", "reviewed_by", "timestamp"}
            _VALID_REVIEWERS = {"agent", "founder"}
            for i, entry in enumerate(overrides):
                if not isinstance(entry, dict):
                    errors.append(
                        {
                            "code": "OVERRIDE_MALFORMED",
                            "message": f"Warning override #{i + 1} must be an object",
                            "field": f"metadata.warning_overrides[{i}]",
                            "layer": 1,
                        }
                    )
                    continue
                missing = _REQUIRED_OVERRIDE_KEYS - set(entry.keys())
                if missing:
                    errors.append(
                        {
                            "code": "OVERRIDE_MISSING_KEYS",
                            "message": f"Warning override #{i + 1} is missing required keys: {sorted(missing)}",
                            "field": f"metadata.warning_overrides[{i}]",
                            "layer": 1,
                        }
                    )
                reviewer = entry.get("reviewed_by")
                if isinstance(reviewer, str) and reviewer not in _VALID_REVIEWERS:
                    errors.append(
                        {
                            "code": "OVERRIDE_INVALID_REVIEWER",
                            "message": (
                                f"Warning override #{i + 1}: reviewer must be 'agent' or 'founder', got '{reviewer}'"
                            ),
                            "field": f"metadata.warning_overrides[{i}].reviewed_by",
                            "layer": 1,
                        }
                    )

    # --- Date format checks (YYYY-MM) ---
    _YYYY_MM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
    _DATE_FIELDS: list[tuple[str, ...]] = [
        ("cash", "balance_date"),
        ("cash", "fundraising", "expected_close"),
        ("revenue", "mrr", "as_of"),
        ("revenue", "arr", "as_of"),
    ]
    for path in _DATE_FIELDS:
        val = _deep_get(inputs, *path)
        if val is None:
            continue
        if not isinstance(val, str) or not _YYYY_MM.match(val):
            errors.append(
                {
                    "code": "DATE_FORMAT_ERROR",
                    "message": f"Field '{'.'.join(path)}' must be YYYY-MM format, got '{val}'",
                    "field": ".".join(path),
                    "layer": 1,
                }
            )

    # Date checks inside time-series arrays
    monthly = _deep_get(inputs, "revenue", "monthly")
    if isinstance(monthly, list):
        for i, entry in enumerate(monthly):
            if isinstance(entry, dict):
                m = entry.get("month")
                if isinstance(m, str) and not _YYYY_MM.match(m):
                    errors.append(
                        {
                            "code": "DATE_FORMAT_ERROR",
                            "message": f"Monthly revenue entry #{i + 1}: month must be YYYY-MM, got '{m}'",
                            "field": f"revenue.monthly[{i}].month",
                            "layer": 1,
                        }
                    )
                start = entry.get("start_month")
                if isinstance(start, str) and not _YYYY_MM.match(start):
                    errors.append(
                        {
                            "code": "DATE_FORMAT_ERROR",
                            "message": f"Monthly revenue entry #{i + 1}: start month must be YYYY-MM, got '{start}'",
                            "field": f"revenue.monthly[{i}].start_month",
                            "layer": 1,
                        }
                    )

    _YYYY_QN = re.compile(r"^\d{4}-Q[1-4]$")
    quarterly = _deep_get(inputs, "revenue", "quarterly")
    if isinstance(quarterly, list):
        for i, entry in enumerate(quarterly):
            if isinstance(entry, dict):
                q = entry.get("quarter")
                if isinstance(q, str) and not _YYYY_QN.match(q):
                    errors.append(
                        {
                            "code": "DATE_FORMAT_ERROR",
                            "message": f"Quarterly revenue entry #{i + 1}: quarter must be YYYY-QN, got '{q}'",
                            "field": f"revenue.quarterly[{i}].quarter",
                            "layer": 1,
                        }
                    )

    # Date checks inside headcount arrays
    headcount = _deep_get(inputs, "expenses", "headcount")
    if isinstance(headcount, list):
        for i, entry in enumerate(headcount):
            if isinstance(entry, dict):
                sm = entry.get("start_month")
                if isinstance(sm, str) and not _YYYY_MM.match(sm):
                    errors.append(
                        {
                            "code": "DATE_FORMAT_ERROR",
                            "message": f"Headcount entry #{i + 1}: start month must be YYYY-MM, got '{sm}'",
                            "field": f"expenses.headcount[{i}].start_month",
                            "layer": 1,
                        }
                    )

    # --- Currency field type check ---
    # Top-level `currency` is an optional ISO 4217 code (e.g., "USD", "INR").
    # Absent is the back-compat default (treated as USD-equivalent downstream);
    # when present, only the type is validated here — the code isn't matched
    # against a fixed enum since ISO 4217 has ~180 valid codes.
    currency = inputs.get("currency")
    if currency is not None and not isinstance(currency, str):
        errors.append(
            {
                "code": "TYPE_ERROR",
                "message": f"Field 'currency' must be a string (ISO 4217 code), got {type(currency).__name__}",
                "field": "currency",
                "layer": 1,
            }
        )

    # --- Enum field checks ---
    _ENUM_FIELDS: dict[str, tuple[tuple[str, ...], list[str]]] = {
        "stage": (("company", "stage"), list(_STAGE_LADDER)),
        "revenue_model_type": (
            ("company", "revenue_model_type"),
            [
                "saas-plg",
                "saas-sales-led",
                "marketplace",
                "usage-based",
                "ai-native",
                "hardware",
                "hardware-subscription",
                "consumer-subscription",
                "transactional-fintech",
                "annual-contracts",
                "retail",
            ],
        ),
        "model_format": (
            ("company", "model_format"),
            ["spreadsheet", "deck", "conversational", "partial"],
        ),
        "data_confidence": (("company", "data_confidence"), ["exact", "estimated", "mixed"]),
        "gross_margin_basis": (
            ("unit_economics", "gross_margin_basis"),
            ["product", "store_contribution", "net_revenue", "gross_revenue", "blended"],
        ),
        "formatting_quality": (("structure", "formatting_quality"), ["good", "acceptable", "poor"]),
        "source_periodicity": (
            ("metadata", "source_periodicity"),
            ["monthly", "quarterly", "annual", "mixed", "unknown"],
        ),
        "conversion_applied": (
            ("metadata", "conversion_applied"),
            ["none", "divided_by_3", "divided_by_12"],
        ),
    }
    for _name, (path, allowed) in _ENUM_FIELDS.items():
        val = _deep_get(inputs, *path)
        if val is None:
            continue
        if not isinstance(val, str) or val not in allowed:
            errors.append(
                {
                    "code": "ENUM_ERROR",
                    "message": f"Field '{'.'.join(path)}' must be one of {allowed}, got '{val}'",
                    "field": ".".join(path),
                    "layer": 1,
                }
            )

    return errors, warnings, fixes


# ---------------------------------------------------------------------------
# Layer 2 — Consistency
# ---------------------------------------------------------------------------


def _approx_eq(a: float, b: float, tol: float = 0.20) -> bool:
    """Return True when *a* and *b* are within *tol* relative difference."""
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


def _validate_consistency(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Layer 2: cross-field consistency checks."""
    warnings: list[dict[str, Any]] = []

    arpu = _arpu_monthly(inputs)
    customers = _deep_get(inputs, "revenue", "customers")
    mrr = _deep_get(inputs, "revenue", "mrr", "value")
    arr = _deep_get(inputs, "revenue", "arr", "value")

    # ARPU x customers ~ MRR
    if (
        isinstance(arpu, (int, float))
        and isinstance(customers, (int, float))
        and isinstance(mrr, (int, float))
        and mrr != 0
    ):
        expected_mrr = arpu * customers
        if not _approx_eq(expected_mrr, mrr):
            warnings.append(
                {
                    "code": "ARPU_INCONSISTENT",
                    "message": (
                        f"ARPU ({arpu}) x customers ({customers}) = {expected_mrr}, but MRR is {mrr} (>20% gap)"
                    ),
                    "field": "unit_economics.ltv.inputs.arpu_monthly",
                    "layer": 2,
                }
            )

    # ARR/12 ~ MRR
    if isinstance(arr, (int, float)) and isinstance(mrr, (int, float)) and mrr != 0:
        arr_monthly = arr / 12
        if not _approx_eq(arr_monthly, mrr):
            warnings.append(
                {
                    "code": "ARR_MRR_MISMATCH",
                    "message": (f"ARR/12 ({arr_monthly:.2f}) does not match MRR ({mrr}) within 20%"),
                    "field": "revenue.arr.value",
                    "layer": 2,
                }
            )

    # Latest monthly revenue total ~ MRR
    revenue = inputs.get("revenue") or {}
    monthly_series = revenue.get("monthly") if isinstance(revenue, dict) else None
    if isinstance(monthly_series, list) and monthly_series:
        # Find the latest entry with a total
        sorted_months = sorted(
            [e for e in monthly_series if isinstance(e, dict) and isinstance(e.get("total"), (int, float))],
            key=lambda e: e.get("month", ""),
            reverse=True,
        )
        if sorted_months:
            latest = sorted_months[0]
            latest_total = latest["total"]
            latest_month = latest.get("month", "?")
            if isinstance(mrr, (int, float)) and mrr != 0 and not _approx_eq(latest_total, mrr):
                warnings.append(
                    {
                        "code": "TIMESERIES_MRR_MISMATCH",
                        "message": (
                            f"Latest monthly revenue ({latest_month}: {latest_total:,.0f}) "
                            f"does not match MRR ({mrr:,.0f}) within 20%"
                        ),
                        "field": "revenue.monthly",
                        "layer": 2,
                    }
                )
            if isinstance(arr, (int, float)) and arr != 0:
                annualized = latest_total * 12
                if not _approx_eq(annualized, arr):
                    warnings.append(
                        {
                            "code": "TIMESERIES_ARR_MISMATCH",
                            "message": (
                                f"Latest monthly revenue * 12 ({annualized:,.0f}) "
                                f"does not match ARR ({arr:,.0f}) within 20%"
                            ),
                            "field": "revenue.monthly",
                            "layer": 2,
                        }
                    )

    return warnings


# ---------------------------------------------------------------------------
# Layer 3 — Sanity
# ---------------------------------------------------------------------------


def _validate_sanity(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Layer 3: reasonableness checks on individual values."""
    warnings: list[dict[str, Any]] = []

    arpu = _arpu_monthly(inputs)
    mrr = _deep_get(inputs, "revenue", "mrr", "value")
    customers = _deep_get(inputs, "revenue", "customers")

    # ARPU should be < MRR when there are multiple customers
    if (
        isinstance(arpu, (int, float))
        and isinstance(mrr, (int, float))
        and isinstance(customers, (int, float))
        and customers > 1
        and arpu >= mrr
    ):
        warnings.append(
            {
                "code": "ARPU_SUSPECT",
                "message": (
                    f"ARPU ({arpu}) >= MRR ({mrr}) with {customers} customers — "
                    "ARPU should be less than MRR when customers > 1"
                ),
                "field": "unit_economics.ltv.inputs.arpu_monthly",
                "layer": 3,
                "critical": True,
            }
        )

    # Growth rate sanity
    growth = _deep_get(inputs, "revenue", "growth_rate_monthly")
    if isinstance(growth, (int, float)) and growth >= 0.50:
        warnings.append(
            {
                "code": "GROWTH_RATE_SUSPECT",
                "message": (f"Monthly growth rate ({growth:.0%}) is unusually high (>= 50%)"),
                "field": "revenue.growth_rate_monthly",
                "layer": 3,
            }
        )

    # Growth rate zero but company has revenue — likely missing, not truly flat
    if isinstance(growth, (int, float)) and growth == 0.0:
        _mrr_val = _deep_get(inputs, "revenue", "mrr", "value")
        _customers = _deep_get(inputs, "revenue", "customers")
        _has_revenue = isinstance(_mrr_val, (int, float)) and _mrr_val > 0
        _has_customers = isinstance(_customers, (int, float)) and _customers > 1
        if _has_revenue and _has_customers:
            warnings.append(
                {
                    "code": "GROWTH_RATE_ZERO_SUSPECT",
                    "message": (
                        f"Monthly growth rate is 0.0 but the company has"
                        f" ${_mrr_val:,.0f} MRR and {int(_customers)}"
                        f" customers. Leave it blank if the growth rate is"
                        f" unknown, or record a warning override to confirm"
                        f" it really is zero."
                    ),
                    "field": "revenue.growth_rate_monthly",
                    "layer": 3,
                    "critical": True,
                }
            )

    # Burn-to-revenue sanity (data-error detector, not metric scorer)
    burn = _deep_get(inputs, "cash", "monthly_net_burn")
    stage = _deep_get(inputs, "company", "stage")
    if isinstance(burn, (int, float)) and isinstance(mrr, (int, float)) and mrr > 0:
        # Stage-aware thresholds
        if _stage_in(stage, _SERIES_A_PLUS):
            threshold = 5
        elif _stage_in(stage, _SEED_PLUS):
            threshold = 10
        else:
            threshold = 0  # pre-seed: skip

        if threshold > 0 and burn > threshold * mrr:
            warnings.append(
                {
                    "code": "BURN_REVENUE_SUSPECT",
                    "message": (
                        f"Monthly burn ({burn:,.0f}) is {burn / mrr:.0f}x MRR ({mrr:,.0f}) "
                        f"— exceeds {threshold}x threshold for {stage}. "
                        "Likely data error (e.g., quarterly figures treated as monthly)."
                    ),
                    "field": "cash.monthly_net_burn",
                    "layer": 3,
                    "critical": True,
                }
            )

    # GRR > 1.0 is impossible by definition: gross revenue retention nets out churn
    # and downgrades but does not include expansion, so it is bounded by 1.0.
    grr_val = _deep_get(inputs, "revenue", "grr")
    if isinstance(grr_val, (int, float)) and grr_val > 1.0:
        warnings.append(
            {
                "code": "GRR_ABOVE_ONE",
                "message": (
                    f"GRR ({grr_val:.2%}) exceeds 100% — impossible by definition. "
                    "GRR only nets out churn and downgrades; it cannot include expansion revenue. "
                    "Check whether NRR was entered instead of GRR."
                ),
                "field": "revenue.grr",
                "layer": 3,
                "critical": True,
            }
        )

    # Burn multiple sanity (data-error detector — checklist scores the metric)
    # Prefer time-series net new ARR over growth-rate shortcut to avoid
    # false positives for enterprise SaaS with lumpy deal flow.
    _ts_net_new_arr: float | None = None
    _bm_method = ""
    revenue = inputs.get("revenue")
    if isinstance(revenue, dict):
        monthly = revenue.get("monthly")
        if isinstance(monthly, list) and len(monthly) >= 12:
            sorted_m = sorted(monthly, key=lambda e: e.get("month", ""))
            lookback = -13 if len(sorted_m) >= 13 else 0

            def _arr_val(entry: dict[str, Any]) -> float | None:
                a = entry.get("arr")
                if isinstance(a, (int, float)):
                    return float(a)
                t = entry.get("total")
                if isinstance(t, (int, float)):
                    return float(t) * 12
                return None

            latest = _arr_val(sorted_m[-1])
            earliest = _arr_val(sorted_m[lookback])
            if latest is not None and earliest is not None and latest > earliest:
                _ts_net_new_arr = latest - earliest
                _bm_method = "TTM"
        if _ts_net_new_arr is None:
            quarterly = revenue.get("quarterly")
            if isinstance(quarterly, list) and len(quarterly) >= 4:
                sorted_q = sorted(quarterly, key=lambda e: e.get("quarter", ""))
                q_lookback = -5 if len(sorted_q) >= 5 else 0

                def _arr_val_q(entry: dict[str, Any]) -> float | None:
                    a = entry.get("arr")
                    if isinstance(a, (int, float)):
                        return float(a)
                    t = entry.get("total")
                    if isinstance(t, (int, float)):
                        return float(t) * 4
                    return None

                q_latest = _arr_val_q(sorted_q[-1])
                q_earliest = _arr_val_q(sorted_q[q_lookback])
                if q_latest is not None and q_earliest is not None and q_latest > q_earliest:
                    _ts_net_new_arr = q_latest - q_earliest
                    _bm_method = "YoY quarterly"

    if isinstance(burn, (int, float)) and burn > 0:
        net_new_arr: float | None = None
        if _ts_net_new_arr is not None and _ts_net_new_arr > 0:
            net_new_arr = _ts_net_new_arr
        elif isinstance(mrr, (int, float)) and isinstance(growth, (int, float)) and growth > 0 and mrr > 0:
            # The divisor below is annual burn, so the estimate must be ANNUAL
            # net-new ARR: ΔMRR per month (mrr*growth) adds 12x that to ARR each
            # month, sustained over 12 months.
            net_new_arr = mrr * growth * 12 * 12
            _bm_method = "growth-rate estimate"
        if net_new_arr is not None and net_new_arr > 0:
            burn_multiple = (burn * 12) / net_new_arr
            if burn_multiple > 10:
                warnings.append(
                    {
                        "code": "BURN_MULTIPLE_SUSPECT",
                        "message": (
                            f"Burn multiple ({burn_multiple:.0f}x, {_bm_method}) exceeds 10x "
                            "— likely data error rather than poor unit economics."
                        ),
                        "field": "cash.monthly_net_burn",
                        "layer": 3,
                        "critical": True,
                    }
                )

    # Expense coverage: headcount costs should roughly account for stated burn
    headcount = _deep_get(inputs, "expenses", "headcount")
    if isinstance(burn, (int, float)) and burn > 0 and isinstance(headcount, list) and len(headcount) > 0:
        total_hc = sum(_num(h.get("count", 0), 0) for h in headcount if isinstance(h, dict))
        total_salary_monthly = sum(
            h.get("salary_annual", 0) / 12 * _num(h.get("count", 1), 1)
            for h in headcount
            if isinstance(h, dict) and isinstance(h.get("salary_annual"), (int, float))
        )
        # Include burden if specified
        for h in headcount:
            if isinstance(h, dict):
                burden = h.get("burden_pct")
                if isinstance(burden, (int, float)) and burden > 0:
                    sal = h.get("salary_annual", 0)
                    cnt = _num(h.get("count", 1), 1)
                    if isinstance(sal, (int, float)):
                        total_salary_monthly += sal / 12 * cnt * burden
        # Sum opex and COGS for total extracted expenses
        total_opex = 0.0
        opex_entries = _deep_get(inputs, "expenses", "opex_monthly")
        if isinstance(opex_entries, list):
            total_opex = sum(
                e.get("amount", 0)
                for e in opex_entries
                if isinstance(e, dict) and isinstance(e.get("amount"), (int, float))
            )
        cogs = _deep_get(inputs, "expenses", "cogs")
        total_cogs = 0.0
        if isinstance(cogs, dict):
            total_cogs = sum(v for v in cogs.values() if isinstance(v, (int, float)))
        total_extracted = total_salary_monthly + total_opex + total_cogs
        # Expected total expenses = burn + revenue (since burn = expenses - revenue)
        rev = _deep_get(inputs, "revenue", "mrr", "value")
        if not isinstance(rev, (int, float)):
            rev = _deep_get(inputs, "revenue", "monthly_total")
        if not isinstance(rev, (int, float)):
            rev = 0
        expected_expenses = burn + rev
        if total_hc > 0 and expected_expenses > 0 and total_extracted < expected_expenses * 0.50:
            # A CONVERSATIONAL / partial source legitimately lacks an opex breakdown: the founder gives
            # total burn plus headcount and nothing else. That is the intake mode working as designed, not
            # a missed extraction — so this must NOT be critical there. Firing critical on a conversational
            # source made the gate self-defeating: the only way to clear a STOP is to produce the missing
            # expenses, and with nothing to extract from, a reconciling opex line gets INVENTED. An
            # anti-hallucination gate must never be satisfiable only by fabrication.
            #
            # `spreadsheet`/`deck` sources DO carry a breakdown, so there the gate keeps its teeth: sub-50%
            # coverage means the extractor missed department-level payroll or a non-payroll block.
            fmt = _deep_get(inputs, "company", "model_format") or "spreadsheet"
            sparse_by_design = fmt in ("conversational", "partial")
            # Currency-neutral: the figures are whatever `inputs.currency` says. Hardcoding `$` here
            # leaked a bare dollar sign into a non-USD review (the report itself is otherwise clean).
            cur = inputs.get("currency") or "USD"
            unit = "" if cur == "USD" else f" {cur}"
            money = "$" if cur == "USD" else ""
            if sparse_by_design:
                message = (
                    f"Only {total_extracted / expected_expenses:.0%} of implied total expenses are itemized "
                    f"({money}{total_extracted:,.0f}{unit}/mo from headcount + opex + COGS, against "
                    f"{money}{expected_expenses:,.0f}{unit}/mo = burn {money}{burn:,.0f}{unit} + revenue "
                    f"{money}{rev:,.0f}{unit}). Expected for a {fmt} source — the remainder is unitemized "
                    "non-payroll opex. Totals are used as stated; per-category analysis is limited to what "
                    "was itemized. Do NOT invent a reconciling opex line to close the gap."
                )
            else:
                message = (
                    f"Extracted expenses ({money}{total_extracted:,.0f}{unit}/mo from headcount + opex + "
                    f"COGS) cover only {total_extracted / expected_expenses:.0%} of implied total expenses "
                    f"({money}{expected_expenses:,.0f}{unit}/mo = burn {money}{burn:,.0f}{unit} + revenue "
                    f"{money}{rev:,.0f}{unit}). Major cost categories likely missed — check for "
                    "department-level payroll (R&D, S&M, G&A) and non-payroll opex."
                )
            warnings.append(
                {
                    "code": "EXPENSE_COVERAGE_SUSPECT",
                    "message": message,
                    "field": "expenses",
                    "layer": 3,
                    "critical": not sparse_by_design,
                }
            )

    # UNDECLARED_AGENT_VALUE — a field the founder never stated, recorded
    # indistinguishably from one they did.
    #
    # Observed live: a conversational run wrote `bridge.runway_target_months: 24`
    # after a founder who never mentioned a runway target. The VALUE was harmless
    # (runway.py defaults to 24 anyway), but inputs.json records it as founder
    # input, and the next reader — a sub-agent, the checklist, or the founder
    # reviewing their own file — cannot tell the difference. That is the same
    # defect market-sizing fixed with `founder_stated_inputs`.
    #
    # The fix is provenance, not prohibition: the agent MAY supply a default, and
    # must declare it in `agent_supplied` so the report can disclose it. An absent
    # declaration on a conversational run is the thing we flag — the founder was
    # never asked whether these are right.
    fmt = _deep_get(inputs, "company", "model_format") or "spreadsheet"
    if fmt in ("conversational", "deck"):
        declared = inputs.get("agent_supplied")
        undeclared = [path for path in _COMPUTATION_FEEDING_FIELDS if _deep_get(inputs, *path.split(".")) is not None]
        if undeclared and declared is None:
            warnings.append(
                {
                    "code": "UNDECLARED_AGENT_VALUE",
                    "message": (
                        "On a conversational/deck run, inputs.json carries "
                        + ", ".join(undeclared)
                        + " but no `agent_supplied` declaration, so there is no way to tell which of "
                        "these the founder actually stated. Set `agent_supplied` to the list of field "
                        "paths you defaulted (or `[]` if the founder stated all of them) and surface "
                        "every entry in the Step 3.6 Path B confirmation table before the math runs."
                    ),
                    "field": "agent_supplied",
                    "layer": 3,
                    "critical": False,
                }
            )

    # Cash balance of exactly $0 at seed+ is almost always extraction failure
    current_balance = _deep_get(inputs, "cash", "current_balance")
    if current_balance == 0 and _stage_in(stage, _SEED_PLUS):
        warnings.append(
            {
                "code": "CASH_ZERO_SUSPECT",
                "message": (
                    "Cash balance is exactly $0 — likely missing from extraction. "
                    "Confirm with founder or set to null if unknown."
                ),
                "field": "cash.current_balance",
                "layer": 3,
                "critical": True,
            }
        )

    # Warn when burn_multiple is provided but script can compute independently
    provided_bm = _deep_get(inputs, "unit_economics", "burn_multiple")
    if provided_bm is not None and isinstance(burn, (int, float)):
        monthly_entries = inputs.get("revenue", {}).get("monthly", [])
        quarterly_entries = inputs.get("revenue", {}).get("quarterly", [])
        has_ts = (isinstance(monthly_entries, list) and len(monthly_entries) >= 12) or (
            isinstance(quarterly_entries, list) and len(quarterly_entries) >= 4
        )
        has_growth = isinstance(mrr, (int, float)) and isinstance(growth, (int, float))
        if has_ts or has_growth:
            warnings.append(
                {
                    "code": "DERIVED_METRIC_REDUNDANT",
                    "message": (
                        f"burn_multiple ({provided_bm}) provided but compute inputs are present — "
                        "script will likely compute independently (provided value used only as fallback)"
                    ),
                    "field": "unit_economics.burn_multiple",
                    "layer": 3,
                }
            )

    return warnings


# ---------------------------------------------------------------------------
# Layer 4 — Completeness (stage-aware)
# ---------------------------------------------------------------------------


def _validate_completeness(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Layer 4: required fields by stage."""
    warnings: list[dict[str, Any]] = []
    stage = _deep_get(inputs, "company", "stage")

    # cash.current_balance at seed+
    if _stage_in(stage, _SEED_PLUS) and _deep_get(inputs, "cash", "current_balance") is None:
        warnings.append(
            {
                "code": "MISSING_CASH_BALANCE",
                "message": "Current cash balance should be provided at seed stage and later",
                "field": "cash.current_balance",
                "layer": 4,
            }
        )

    # revenue.mrr.value when revenue key exists and no monthly_total fallback
    if (
        "revenue" in inputs
        and isinstance(inputs["revenue"], dict)
        and _deep_get(inputs, "revenue", "mrr", "value") is None
        and _deep_get(inputs, "revenue", "monthly_total") is None
    ):
        warnings.append(
            {
                "code": "MISSING_MRR",
                "message": "Either MRR or a monthly revenue total should be provided when revenue data is present",
                "field": "revenue.mrr.value",
                "layer": 4,
            }
        )

    # cash.monthly_net_burn always expected
    if _deep_get(inputs, "cash", "monthly_net_burn") is None:
        warnings.append(
            {
                "code": "MISSING_BURN",
                "message": "Monthly net burn should be provided",
                "field": "cash.monthly_net_burn",
                "layer": 4,
            }
        )

    # NRR or GRR at series-a+
    if _stage_in(stage, _SERIES_A_PLUS):
        nrr = _deep_get(inputs, "revenue", "nrr")
        grr = _deep_get(inputs, "revenue", "grr")
        if nrr is None and grr is None:
            warnings.append(
                {
                    "code": "MISSING_RETENTION",
                    "message": "NRR or GRR should be populated at series-a+",
                    "field": "revenue.nrr",
                    "layer": 4,
                }
            )

    # gross_margin at seed+
    if _stage_in(stage, _SEED_PLUS) and _deep_get(inputs, "unit_economics", "gross_margin") is None:
        warnings.append(
            {
                "code": "MISSING_GROSS_MARGIN",
                "message": "gross_margin should be populated at seed+",
                "field": "unit_economics.gross_margin",
                "layer": 4,
            }
        )

    # Customer count needed for ARPU validation when LTV inputs present
    ltv_inputs = _deep_get(inputs, "unit_economics", "ltv", "inputs")
    customers = _deep_get(inputs, "revenue", "customers")
    if isinstance(ltv_inputs, dict) and ltv_inputs and customers is None and _stage_in(stage, _SEED_PLUS):
        warnings.append(
            {
                "code": "CUSTOMERS_MISSING",
                "message": "LTV inputs present but customer count is missing — the ARPU sanity check cannot run",
                "field": "revenue.customers",
                "layer": 4,
            }
        )

    return warnings


# ---------------------------------------------------------------------------
# Override helpers
# ---------------------------------------------------------------------------


def _snapshot_stale(snapshot: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """Check if any snapshot value changed by >20% (numbers) or differs (strings)."""
    for path, old_val in snapshot.items():
        current = _deep_get_by_path(inputs, path)
        if isinstance(old_val, (int, float)) and isinstance(current, (int, float)):
            if old_val == 0 and current == 0:
                continue
            if old_val == 0 or abs(current - old_val) / max(abs(old_val), 1) > 0.2:
                return True
        elif old_val != current:
            return True
    return False


def _is_overridden(warning: dict[str, Any], overrides: list[dict[str, Any]], inputs: dict[str, Any]) -> bool:
    """Only agent-reviewed overrides clear has_critical_warnings."""
    for o in overrides:
        if o.get("reviewed_by") != "agent":
            continue  # founder overrides are informational, not blocking
        if o.get("code") != warning.get("code"):
            continue
        if "field" in o and o["field"] != warning.get("field", ""):
            continue
        if "snapshot" in o and isinstance(o["snapshot"], dict) and _snapshot_stale(o["snapshot"], inputs):
            continue  # stale override — underlying data changed
        return True
    return False


# ---------------------------------------------------------------------------
# Main validation orchestrator
# ---------------------------------------------------------------------------


def validate(inputs: dict[str, Any], *, fix: bool = False) -> dict[str, Any]:
    """Run all 4 validation layers and return results."""
    all_errors: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    all_fixes: list[dict[str, Any]] = []

    # Layer 1
    l1_errors, l1_warnings, l1_fixes = _validate_structural(inputs, fix=fix)
    all_errors.extend(l1_errors)
    all_warnings.extend(l1_warnings)
    all_fixes.extend(l1_fixes)

    # Layer 2
    all_warnings.extend(_validate_consistency(inputs))

    # Layer 3
    all_warnings.extend(_validate_sanity(inputs))

    # Layer 4
    all_warnings.extend(_validate_completeness(inputs))

    metadata = inputs.get("metadata")
    overrides = metadata.get("warning_overrides", []) if isinstance(metadata, dict) else []

    return {
        "valid": len(all_errors) == 0,
        "has_critical_warnings": any(
            w.get("critical") and not _is_overridden(w, overrides, inputs) for w in all_warnings
        ),
        "errors": all_errors,
        "warnings": all_warnings,
        "auto_fixes": all_fixes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate inputs.json for financial model review (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix correctable issues; emit corrected JSON to stdout, summary to stderr",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"company\": {...}, ...}' | python validate_inputs.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON input must be an object", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None

    result = validate(data, fix=args.fix)

    if args.fix:
        # --fix mode: corrected JSON to stdout, validation summary to stderr
        corrected_out = json.dumps(data, indent=indent) + "\n"
        summary_out = json.dumps(result, indent=indent) + "\n"
        print(summary_out, file=sys.stderr, end="")
        _write_output(corrected_out, args.output)
    else:
        out = json.dumps(result, indent=indent) + "\n"
        _write_output(
            out,
            args.output,
            summary={
                "valid": result["valid"],
                "errors": len(result["errors"]),
                "warnings": len(result["warnings"]),
            },
        )


if __name__ == "__main__":
    main()
