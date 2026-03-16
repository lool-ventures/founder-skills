#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Unit economics calculator and benchmarker for financial model review.

Reads inputs.json from stdin, computes metrics, rates against stage-appropriate benchmarks.

Usage:
    echo '{"company": {...}, "revenue": {...}, ...}' | python unit_economics.py --pretty
"""

from __future__ import annotations

import argparse
import json
import os
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
# Stage benchmarks
# ---------------------------------------------------------------------------

STAGE_BENCHMARKS: dict[str, dict[str, dict[str, Any]]] = {
    "pre-seed": {
        "burn_multiple": {
            "strong": 3.0,
            "acceptable": 4.0,
            "warning": 5.0,
            "source": "CFO Advisors 2025",
            "as_of": "2025-Q1",
        },
        "gross_margin": {
            "strong": 0.70,
            "acceptable": 0.60,
            "warning": 0.50,
            "source": "KeyBanc SaaS Survey 2024",
            "as_of": "2024-Q4",
        },
    },
    "seed": {
        "burn_multiple": {
            "strong": 2.0,
            "acceptable": 2.5,
            "warning": 3.0,
            "source": "CFO Advisors 2025 / best-practices resolution",
            "as_of": "2025-Q1",
        },
        "gross_margin": {
            "strong": 0.75,
            "acceptable": 0.70,
            "warning": 0.60,
            "source": "KeyBanc SaaS Survey 2024",
            "as_of": "2024-Q4",
        },
        "nrr": {
            "strong": 1.10,
            "acceptable": 1.00,
            "warning": 0.90,
            "source": "Bessemer / OpenView 2024",
            "as_of": "2024-Q4",
        },
        "grr": {
            "strong": 0.90,
            "acceptable": 0.85,
            "warning": 0.80,
            "source": "Bessemer 2024",
            "as_of": "2024-Q4",
        },
        "magic_number": {
            "strong": 1.0,
            "acceptable": 0.75,
            "warning": 0.5,
            "source": "Scale VP 2024",
            "as_of": "2024-Q4",
        },
        "rule_of_40": {
            "strong": 40,
            "acceptable": 30,
            "warning": 20,
            "source": "Bessemer 2024",
            "as_of": "2024-Q4",
        },
    },
    "series-a": {
        "burn_multiple": {
            "strong": 1.5,
            "acceptable": 2.0,
            "warning": 2.5,
            "source": "CFO Advisors 2025 / best-practices resolution",
            "as_of": "2025-Q1",
        },
        "gross_margin": {
            "strong": 0.75,
            "acceptable": 0.70,
            "warning": 0.60,
            "source": "KeyBanc SaaS Survey 2024",
            "as_of": "2024-Q4",
        },
        "nrr": {
            "strong": 1.15,
            "acceptable": 1.05,
            "warning": 0.95,
            "source": "Bessemer / OpenView 2024",
            "as_of": "2024-Q4",
        },
        "grr": {
            "strong": 0.92,
            "acceptable": 0.88,
            "warning": 0.82,
            "source": "Bessemer 2024",
            "as_of": "2024-Q4",
        },
        "magic_number": {
            "strong": 1.0,
            "acceptable": 0.75,
            "warning": 0.5,
            "source": "Scale VP 2024",
            "as_of": "2024-Q4",
        },
        "rule_of_40": {
            "strong": 40,
            "acceptable": 30,
            "warning": 20,
            "source": "Bessemer 2024",
            "as_of": "2024-Q4",
        },
    },
}

# ---------------------------------------------------------------------------
# CAC payback benchmarks by ACV tier
# ---------------------------------------------------------------------------

CAC_PAYBACK_BY_ACV: dict[str, dict[str, Any]] = {
    "smb": {
        "strong": 6,
        "acceptable": 9,
        "warning": 15,
        "source": "Mosaic 2023 / KeyBanc 2024",
        "as_of": "2024-Q4",
    },
    "mid-market": {
        "strong": 12,
        "acceptable": 15,
        "warning": 21,
        "source": "Mosaic 2023 / KeyBanc 2024",
        "as_of": "2024-Q4",
    },
    "enterprise": {
        "strong": 15,
        "acceptable": 20,
        "warning": 30,
        "source": "Mosaic 2023 / KeyBanc 2024",
        "as_of": "2024-Q4",
    },
    "large-ent": {
        "strong": 18,
        "acceptable": 24,
        "warning": 36,
        "source": "Mosaic 2023 / KeyBanc 2024",
        "as_of": "2024-Q4",
    },
    "default": {
        "strong": 12,
        "acceptable": 18,
        "warning": 24,
        "source": "composite (best-practices doc)",
        "as_of": "2024-Q4",
    },
}

# SaaS model types
_SAAS_MODEL_TYPES = {"saas-plg", "saas-sales-led", "annual-contracts"}

# Metrics only applicable to SaaS
_SAAS_ONLY_METRICS = {"nrr", "grr", "magic_number", "rule_of_40", "arr_per_fte"}

# AI-related sectors that get gross margin threshold adjustment
_AI_SECTORS = {"ai-native", "ai", "ai native"}

# Lower-is-better metrics (for rating direction)
_LOWER_IS_BETTER = {"burn_multiple", "cac_payback", "cac"}


# ---------------------------------------------------------------------------
# Rating helpers
# ---------------------------------------------------------------------------


def _rate_higher_is_better(
    value: float,
    bench: dict[str, Any],
) -> str:
    """Rate a metric where higher values are better."""
    if value >= bench["strong"]:
        return "strong"
    if value >= bench["acceptable"]:
        return "acceptable"
    if value >= bench["warning"]:
        return "warning"
    return "fail"


def _rate_lower_is_better(
    value: float,
    bench: dict[str, Any],
) -> str:
    """Rate a metric where lower values are better."""
    if value <= bench["strong"]:
        return "strong"
    if value <= bench["acceptable"]:
        return "acceptable"
    if value <= bench["warning"]:
        return "warning"
    return "fail"


def _rate_metric(
    name: str,
    value: float,
    bench: dict[str, Any],
) -> str:
    """Rate a metric using its benchmark, choosing direction automatically."""
    if name in _LOWER_IS_BETTER:
        return _rate_lower_is_better(value, bench)
    return _rate_higher_is_better(value, bench)


def _get_stage_benchmarks(stage: str) -> dict[str, dict[str, Any]]:
    """Get benchmarks for a stage, falling back to series-a for later stages."""
    if stage in STAGE_BENCHMARKS:
        return STAGE_BENCHMARKS[stage]
    # Fall back to series-a for unknown / later stages
    print(
        f"Warning: no benchmarks for stage '{stage}'; falling back to series-a",
        file=sys.stderr,
    )
    return STAGE_BENCHMARKS["series-a"]


def _is_saas(model_type: str) -> bool:
    """Check if the revenue model type is SaaS."""
    return model_type.lower() in _SAAS_MODEL_TYPES


def _is_ai_company(sector: str, model_type: str, traits: list[str] | None = None) -> bool:
    """Check if the company is AI-related (gets gross margin threshold adjustment).

    Checks three signals: sector, revenue_model_type, and traits.
    """
    if sector.lower() in _AI_SECTORS:
        return True
    if model_type.lower() == "ai-native":
        return True
    return bool(traits and "ai-powered" in traits)


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


# ---------------------------------------------------------------------------
# Time-series net new ARR helpers
# ---------------------------------------------------------------------------


def _net_new_arr_from_monthly(entries: list[dict[str, Any]]) -> float | None:
    """Compute net new ARR from monthly time-series (≥13 entries for full TTM).

    Uses ``arr`` field if present, otherwise approximates as ``total * 12``.
    With exactly 12 entries, computes over 11-month span (best available).
    Returns None if fewer than 12 entries.
    """
    if len(entries) < 12:
        return None
    sorted_entries = sorted(entries, key=lambda e: e.get("month", ""))

    def _arr_value(entry: dict[str, Any]) -> float | None:
        arr = entry.get("arr")
        if isinstance(arr, (int, float)):
            return float(arr)
        total = entry.get("total")
        if isinstance(total, (int, float)):
            return float(total) * 12
        return None

    latest_arr = _arr_value(sorted_entries[-1])
    # Look back 12 months (13th entry from end) for true TTM; fall back to
    # oldest available if fewer than 13 entries.
    lookback_idx = -13 if len(sorted_entries) >= 13 else 0
    earliest_arr = _arr_value(sorted_entries[lookback_idx])
    if latest_arr is None or earliest_arr is None:
        return None
    net_new = latest_arr - earliest_arr
    return net_new if net_new > 0 else None


def _net_new_arr_from_quarterly(entries: list[dict[str, Any]]) -> float | None:
    """Compute net new ARR from quarterly time-series (≥5 entries for full YoY).

    Uses ``arr`` field (annualized run-rate). With exactly 4 entries, computes
    over 3-quarter span (best available). Returns None if fewer than 4 entries.
    """
    if len(entries) < 4:
        return None
    sorted_entries = sorted(entries, key=lambda e: e.get("quarter", ""))

    def _arr_value(entry: dict[str, Any]) -> float | None:
        arr = entry.get("arr")
        if isinstance(arr, (int, float)):
            return float(arr)
        total = entry.get("total")
        if isinstance(total, (int, float)):
            return float(total) * 4  # quarterly revenue → annualized
        return None

    latest_arr = _arr_value(sorted_entries[-1])
    # Look back 4 quarters (5th entry from end) for true YoY; fall back to
    # oldest available if fewer than 5 entries.
    lookback_idx = -5 if len(sorted_entries) >= 5 else 0
    earliest_arr = _arr_value(sorted_entries[lookback_idx])
    if latest_arr is None or earliest_arr is None:
        return None
    net_new = latest_arr - earliest_arr
    return net_new if net_new > 0 else None


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_metrics(inputs: dict[str, Any]) -> dict[str, Any]:
    """Compute all unit economics metrics from structured inputs."""
    company = inputs.get("company", {})
    revenue = inputs.get("revenue", {})
    expenses = inputs.get("expenses", {})
    unit_econ = inputs.get("unit_economics", {})

    stage = company.get("stage", "seed").lower()
    sector = company.get("sector", "").lower()
    model_type = company.get("revenue_model_type", "").lower()
    saas = _is_saas(model_type)
    traits = company.get("traits", []) or []
    ai_sector = _is_ai_company(sector, model_type, traits if isinstance(traits, list) else [])
    data_confidence = company.get("data_confidence", "exact")

    benchmarks = _get_stage_benchmarks(stage)
    metrics: list[dict[str, Any]] = []
    ue_warnings: list[dict[str, str]] = []
    bench: dict[str, Any] | None  # reused across metric sections

    _CONFIDENCE_QUALIFIERS: dict[str, str] = {
        "estimated": " (based on estimated inputs)",
        "mixed": " (partially estimated)",
    }

    # --- Helper to build a metric entry ---
    def _metric(
        name: str,
        value: float | None,
        rating: str,
        evidence: str,
        benchmark_source: Any = "",
        benchmark_as_of: Any = "",
        bench: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Append confidence qualifier to rated metrics
        final_evidence = evidence
        if data_confidence != "exact" and rating not in ("not_rated", "not_applicable"):
            qualifier = _CONFIDENCE_QUALIFIERS.get(data_confidence, "")
            final_evidence = evidence + qualifier
        entry: dict[str, Any] = {
            "id": name,
            "name": name,
            "value": value,
            "rating": rating,
            "evidence": final_evidence,
            "benchmark_source": str(benchmark_source),
            "benchmark_as_of": str(benchmark_as_of),
        }
        if data_confidence != "exact" and rating not in ("not_rated", "not_applicable"):
            entry["confidence"] = data_confidence
        if bench is not None:
            entry["benchmark"] = {
                "target": bench.get("strong"),
                "source": bench.get("source", ""),
                "as_of": bench.get("as_of", ""),
            }
        return entry

    # 1. CAC
    cac_total = _deep_get(unit_econ, "cac", "total")
    cac_fully_loaded = _deep_get(unit_econ, "cac", "fully_loaded", default=False)
    if cac_total is not None:
        loaded_note = "Fully loaded" if cac_fully_loaded else "Partial"
        # CAC doesn't have stage benchmarks; use contextual rating for non-SaaS
        if not saas and model_type in ("hardware", "hardware-subscription", "marketplace"):
            rating = "contextual"
            evidence = (
                f"{loaded_note} CAC of ${cac_total:,.0f}; CAC benchmarks vary significantly for {model_type} models"
            )
        else:
            # Use default payback benchmark source for CAC rating reference
            rating = "not_rated"
            evidence = f"{loaded_note} CAC of ${cac_total:,.0f}"
        metrics.append(_metric("cac", cac_total, rating, evidence))
    else:
        metrics.append(_metric("cac", None, "not_rated", "CAC data not provided"))

    # 2. LTV — synthesize inputs from revenue-level fields if ltv.inputs is missing
    ltv_inputs = _deep_get(unit_econ, "ltv", "inputs")
    _ltv_value_synthesized = False  # True when we computed ltv.value from revenue fields
    _ltv_inputs_synthesized = False  # True when we filled ltv.inputs from revenue fields
    if not isinstance(ltv_inputs, dict) or not ltv_inputs:
        # Try to build ltv.inputs from revenue-level data
        _synth_churn = _deep_get(revenue, "churn_monthly")
        if _synth_churn is None:
            _synth_churn = _deep_get(revenue, "churn")
        _synth_customers = _deep_get(revenue, "customers")
        _synth_gm = _deep_get(unit_econ, "gross_margin")
        _synth_mrr = _deep_get(revenue, "mrr", "value")
        if (
            _synth_mrr is not None
            and isinstance(_synth_mrr, (int, float))
            and _synth_customers is not None
            and isinstance(_synth_customers, (int, float))
            and _synth_customers > 0
            and _synth_churn is not None
            and isinstance(_synth_churn, (int, float))
            and _synth_churn >= 0
            and _synth_gm is not None
            and isinstance(_synth_gm, (int, float))
            and 0 <= _synth_gm <= 1
        ):
            _synth_arpu = _synth_mrr / _synth_customers
            # Compute LTV: arpu * gross_margin / churn (or 60-month cap if churn=0)
            if _synth_churn == 0:
                _synth_ltv = round(_synth_arpu * _synth_gm * 60, 2)
            else:
                _synth_ltv = round(_synth_arpu * _synth_gm / _synth_churn, 2)
            # Inject into unit_econ so downstream code (LTV/CAC, etc.) works
            ltv_node = _deep_get(unit_econ, "ltv")
            if not isinstance(ltv_node, dict):
                unit_econ["ltv"] = {}
            # Only set ltv.value if not already provided by extraction
            existing_ltv = _deep_get(unit_econ, "ltv", "value")
            if existing_ltv is None:
                unit_econ["ltv"]["value"] = _synth_ltv
                _ltv_value_synthesized = True
            # Always fill inputs (that's what was missing)
            unit_econ["ltv"]["inputs"] = {
                "arpu_monthly": round(_synth_arpu, 2),
                "churn_monthly": _synth_churn,
                "gross_margin": _synth_gm,
            }
            _ltv_inputs_synthesized = True
            # Only set observed_vs_assumed if not already present
            if "observed_vs_assumed" not in unit_econ["ltv"]:
                unit_econ["ltv"]["observed_vs_assumed"] = "assumed"

    ltv_value = _deep_get(unit_econ, "ltv", "value")
    ltv_observed = _deep_get(unit_econ, "ltv", "observed_vs_assumed", default="assumed")
    if ltv_value is not None:
        # Cap LTV at 60-month horizon when churn is 0%
        ltv_churn = _deep_get(unit_econ, "ltv", "inputs", "churn_monthly")
        if ltv_churn is None:
            ltv_churn = _deep_get(unit_econ, "ltv", "inputs", "churn")
        ltv_unreliable = False
        if ltv_churn is not None and ltv_churn == 0:
            arpu = _deep_get(unit_econ, "ltv", "inputs", "arpu_monthly")
            if arpu is None:
                arpu = _deep_get(unit_econ, "ltv", "inputs", "arpu")
            gm_input = _deep_get(unit_econ, "ltv", "inputs", "gross_margin")
            obs_note = "observed" if ltv_observed == "observed" else "assumed"
            if _ltv_value_synthesized:
                obs_note = "synthesized from revenue.customers and revenue.churn_monthly"
            elif _ltv_inputs_synthesized:
                obs_note += "; inputs synthesized from revenue fields"
            if arpu is not None and gm_input is not None:
                ltv_value = round(arpu * gm_input * 60, 2)
                evidence = f"LTV of ${ltv_value:,.0f} ({obs_note}; capped at 5-year horizon, 0% churn assumed)"
            else:
                ltv_unreliable = True
                evidence = (
                    f"LTV of ${ltv_value:,.0f} ({obs_note}; 0% churn — "
                    "could not apply 5-year cap, missing arpu or gross_margin inputs; value may be unreliable)"
                )
                ue_warnings.append(
                    {
                        "code": "LTV_CAP_MISSING_INPUTS",
                        "message": "Cannot compute 60-month LTV cap: missing arpu_monthly or gross_margin",
                        "field": "unit_economics.ltv",
                    }
                )
        else:
            obs_note = "observed" if ltv_observed == "observed" else "assumed"
            if _ltv_value_synthesized:
                obs_note = "synthesized from revenue.customers and revenue.churn_monthly"
            elif _ltv_inputs_synthesized:
                obs_note += "; inputs synthesized from revenue fields"
            evidence = f"LTV of ${ltv_value:,.0f} ({obs_note})"
        # LTV doesn't have standalone stage benchmarks; report as not_rated
        if ltv_unreliable:
            rating = "not_rated"
        elif not saas and model_type in ("hardware", "hardware-subscription", "marketplace"):
            rating = "contextual"
            evidence += f"; LTV benchmarks vary significantly for {model_type} models"
        else:
            rating = "not_rated"
        metrics.append(_metric("ltv", ltv_value, rating, evidence))
    else:
        metrics.append(_metric("ltv", None, "not_rated", "LTV data not provided"))

    # 3. LTV/CAC ratio
    if ltv_value is not None and cac_total is not None and cac_total > 0:
        ltv_cac = round(ltv_value / cac_total, 2)
        if ltv_observed == "assumed":
            rating = "contextual"
            evidence = (
                f"LTV/CAC of {ltv_cac:.1f}x (based on assumed inputs); "
                f"treat as directional until cohort data validates LTV"
            )
        else:
            # Rate against standard benchmarks: 3x strong, 2x acceptable, 1x warning
            bench = {"strong": 3.0, "acceptable": 2.0, "warning": 1.0}
            rating = _rate_higher_is_better(ltv_cac, bench)
            evidence = f"LTV/CAC of {ltv_cac:.1f}x (observed data); benchmark strong >= 3x"
        # bench may be set (observed path) or unset (assumed path)
        ltv_cac_bench = bench if ltv_observed != "assumed" else None
        metrics.append(
            _metric(
                "ltv_cac_ratio",
                ltv_cac,
                rating,
                evidence,
                "Mosaic 2023 / KeyBanc 2024",
                "2024-Q4",
                bench=ltv_cac_bench,
            )
        )
    else:
        reason = "Insufficient data to compute LTV/CAC"
        metrics.append(_metric("ltv_cac_ratio", None, "not_rated", reason))

    # 4. CAC payback
    payback = _deep_get(unit_econ, "payback_months")
    if payback is not None:
        acv_tier = _deep_get(company, "acv_tier", default="default")
        bench = CAC_PAYBACK_BY_ACV.get(acv_tier, CAC_PAYBACK_BY_ACV["default"])
        rating = _rate_lower_is_better(payback, bench)
        evidence = f"CAC payback of {payback} months; {acv_tier} tier benchmark strong <= {bench['strong']} months"
        metrics.append(_metric("cac_payback", payback, rating, evidence, bench["source"], bench["as_of"], bench=bench))
    else:
        metrics.append(_metric("cac_payback", None, "not_rated", "Payback data not provided"))

    # 5. Burn multiple
    monthly_burn_raw = _deep_get(inputs, "cash", "monthly_net_burn")
    # Defensive: take absolute value — schema says positive = cash outgoing,
    # but extraction may produce negative values (accounting convention).
    monthly_burn = abs(monthly_burn_raw) if monthly_burn_raw is not None else None
    if monthly_burn_raw is not None and monthly_burn_raw < 0:
        print(
            f"Warning: monthly_net_burn is negative ({monthly_burn_raw:,.0f}); "
            f"using absolute value ({monthly_burn:,.0f}). "
            f"Schema convention: positive = cash outgoing.",
            file=sys.stderr,
        )
    mrr = _deep_get(revenue, "mrr", "value")
    growth_rate = _deep_get(revenue, "growth_rate_monthly")
    _compute_inputs_present = monthly_burn is not None and mrr is not None and growth_rate is not None

    # ARR floor — burn multiple not meaningful at very low ARR
    arr_val_for_bm = _deep_get(revenue, "arr", "value")
    _arr_below_floor = arr_val_for_bm is not None and arr_val_for_bm < 500_000

    # Try time-series-based net new ARR (more accurate for enterprise/lumpy growth)
    monthly_entries = revenue.get("monthly", [])
    quarterly_entries = revenue.get("quarterly", [])
    _ts_net_new_arr: float | None = None
    _ts_method: str = ""
    if isinstance(monthly_entries, list):
        _ts_net_new_arr = _net_new_arr_from_monthly(monthly_entries)
        if _ts_net_new_arr is not None:
            _ts_method = "TTM"
    if _ts_net_new_arr is None and isinstance(quarterly_entries, list):
        _ts_net_new_arr = _net_new_arr_from_quarterly(quarterly_entries)
        if _ts_net_new_arr is not None:
            _ts_method = "YoY (quarterly)"

    if _arr_below_floor:
        metrics.append(
            _metric(
                "burn_multiple",
                None,
                "not_applicable",
                f"Burn multiple not meaningful below $500K ARR (current: ${arr_val_for_bm:,.0f})",
            )
        )
    elif monthly_burn is not None and _ts_net_new_arr is not None and _ts_net_new_arr > 0:
        # Time-series path (preferred): TTM or YoY quarterly
        burn_mult = round((monthly_burn * 12) / _ts_net_new_arr, 2)
        _bm_method_label = f"{_ts_method} actual"
        if burn_mult < 0:
            metrics.append(
                _metric(
                    "burn_multiple",
                    burn_mult,
                    "not_rated",
                    f"Burn multiple is negative ({burn_mult:.1f}x, {_bm_method_label}) — likely a sign/input error",
                )
            )
        elif burn_mult > 50:
            metrics.append(
                _metric(
                    "burn_multiple",
                    burn_mult,
                    "not_rated",
                    f"Burn multiple of {burn_mult:.1f}x ({_bm_method_label}) is implausibly high "
                    f"— check input consistency",
                )
            )
        else:
            bench = benchmarks.get("burn_multiple")
            if bench:
                rating = _rate_lower_is_better(burn_mult, bench)
                evidence = (
                    f"Burn multiple of {burn_mult:.1f}x ({_bm_method_label}); "
                    f"stage benchmark strong <= {bench['strong']}x"
                )
                metrics.append(
                    _metric(
                        "burn_multiple",
                        burn_mult,
                        rating,
                        evidence,
                        bench["source"],
                        bench["as_of"],
                        bench=bench,
                    )
                )
            else:
                metrics.append(
                    _metric(
                        "burn_multiple",
                        burn_mult,
                        "not_rated",
                        f"Burn multiple of {burn_mult:.1f}x ({_bm_method_label}); no benchmark for stage '{stage}'",
                    )
                )
        # Divergence check: if growth-rate method is also available, compare
        if _compute_inputs_present and growth_rate > 0:
            _gr_net_new_arr = mrr * growth_rate * 12
            if _gr_net_new_arr > 0:
                _gr_burn_mult = round((monthly_burn * 12) / _gr_net_new_arr, 2)
                ratio = max(burn_mult, _gr_burn_mult) / max(min(burn_mult, _gr_burn_mult), 0.01)
                if ratio > 2.0:
                    ue_warnings.append(
                        {
                            "code": "BURN_MULTIPLE_DIVERGENCE",
                            "message": (
                                f"{_bm_method_label} burn multiple ({burn_mult:.1f}x) diverges >2x "
                                f"from growth-rate estimate ({_gr_burn_mult:.1f}x) — "
                                f"review for lumpy deal timing or data issues"
                            ),
                            "field": "burn_multiple",
                        }
                    )
    elif _compute_inputs_present and growth_rate > 0:
        # Growth-rate fallback (less accurate for enterprise/lumpy growth)
        net_new_arr = mrr * growth_rate * 12
        if net_new_arr > 0:
            burn_mult = round(monthly_burn / (net_new_arr / 12), 2)
            # --- divergence check: prefer provided when growth-rate estimate is unreliable ---
            # Only compare positive values; negative burn_mult flows to existing sign-error handler
            provided_bm = _deep_get(unit_econ, "burn_multiple")
            if burn_mult > 0 and provided_bm is not None and isinstance(provided_bm, (int, float)) and provided_bm > 0:
                ratio = max(burn_mult, provided_bm) / min(burn_mult, provided_bm)
                if ratio > 2.0:
                    burn_mult_original = burn_mult
                    ue_warnings.append(
                        {
                            "code": "BURN_MULTIPLE_REPORTED_DIVERGENCE",
                            "message": (
                                f"Growth-rate burn multiple ({burn_mult_original:.1f}x) diverges >2x "
                                f"from reported value ({provided_bm:.1f}x) — "
                                f"using reported value (growth-rate method unreliable without time-series)"
                            ),
                            "field": "burn_multiple",
                        }
                    )
                    burn_mult = provided_bm
            if burn_mult < 0:
                metrics.append(
                    _metric(
                        "burn_multiple",
                        burn_mult,
                        "not_rated",
                        f"Burn multiple is negative ({burn_mult:.1f}x) — likely a sign/input error",
                    )
                )
            elif burn_mult > 50:
                metrics.append(
                    _metric(
                        "burn_multiple",
                        burn_mult,
                        "not_rated",
                        f"Burn multiple of {burn_mult:.1f}x is implausibly high — check input consistency",
                    )
                )
            elif ((1 + growth_rate) ** 12) - 1 > 2.0:
                growth_annualized_bm = (((1 + growth_rate) ** 12) - 1) * 100
                metrics.append(
                    _metric(
                        "burn_multiple",
                        burn_mult,
                        "contextual",
                        f"Burn multiple of {burn_mult:.1f}x; "
                        f"growth is {growth_annualized_bm:.0f}% annualized (hyper-growth) — "
                        f"not benchmark-compared",
                    )
                )
            else:
                bench = benchmarks.get("burn_multiple")
                if bench:
                    rating = _rate_lower_is_better(burn_mult, bench)
                    evidence = f"Burn multiple of {burn_mult:.1f}x; stage benchmark strong <= {bench['strong']}x"
                    metrics.append(
                        _metric(
                            "burn_multiple",
                            burn_mult,
                            rating,
                            evidence,
                            bench["source"],
                            bench["as_of"],
                            bench=bench,
                        )
                    )
                else:
                    metrics.append(
                        _metric(
                            "burn_multiple",
                            burn_mult,
                            "not_rated",
                            f"Burn multiple of {burn_mult:.1f}x; no benchmark for stage '{stage}'",
                        )
                    )
        else:
            # Inputs present but economics undefined (net new ARR <= 0) — no fallback
            metrics.append(_metric("burn_multiple", None, "not_rated", "Net new ARR is zero or negative"))
    elif not _compute_inputs_present:
        # Compute inputs missing — use founder-provided value as fallback
        provided_bm = _deep_get(unit_econ, "burn_multiple")
        if provided_bm is not None:
            metrics.append(
                _metric(
                    "burn_multiple",
                    provided_bm,
                    "not_rated",
                    f"Burn multiple of {provided_bm:.2f}x (reported, not independently computed)",
                )
            )
        else:
            metrics.append(_metric("burn_multiple", None, "not_rated", "Insufficient data for burn multiple"))
    else:
        # Inputs present but growth_rate <= 0 — economics undefined, no fallback
        metrics.append(
            _metric("burn_multiple", None, "not_rated", "Growth rate is zero or negative; burn multiple undefined")
        )

    # 6. Magic number (SaaS only)
    if saas:
        # Magic number = net new ARR (annualized QoQ delta) / S&M spend
        # Simplified: net new ARR = MRR * growth_rate * 12
        # S&M spend: sum of sales headcount costs
        headcount = _deep_get(expenses, "headcount", default=[])
        sm_spend_annual = 0.0
        for person in headcount:
            role = str(person.get("role", "")).lower()
            if role in ("sales", "marketing", "sales & marketing", "s&m", "growth"):
                count = person.get("count", 0)
                salary = person.get("salary_annual", 0)
                burden = person.get("burden_pct", 0.0)
                sm_spend_annual += count * salary * (1 + burden)

        if mrr is not None and growth_rate is not None and growth_rate > 0 and sm_spend_annual > 0:
            net_new_arr = mrr * growth_rate * 12
            magic = round(net_new_arr / sm_spend_annual, 2)
            bench = benchmarks.get("magic_number")
            if bench:
                rating = _rate_higher_is_better(magic, bench)
                evidence = f"Magic number of {magic:.2f}; stage benchmark strong >= {bench['strong']}"
                metrics.append(
                    _metric(
                        "magic_number",
                        magic,
                        rating,
                        evidence,
                        bench["source"],
                        bench["as_of"],
                        bench=bench,
                    )
                )
            else:
                metrics.append(
                    _metric(
                        "magic_number",
                        magic,
                        "not_rated",
                        f"Magic number of {magic:.2f}; no benchmark for stage '{stage}'",
                    )
                )
        else:
            metrics.append(_metric("magic_number", None, "not_rated", "Insufficient data for magic number"))
    else:
        metrics.append(_metric("magic_number", None, "not_applicable", "Magic number applies to SaaS models only"))

    # 7. Gross margin
    gm = _deep_get(unit_econ, "gross_margin")
    if gm is not None:
        bench = benchmarks.get("gross_margin")
        if bench:
            # AI companies get -5pt threshold adjustment
            if ai_sector:
                ai_adj = 0.10 if stage in ("series-a", "series-b", "later") else 0.05
                adjusted_bench = {
                    "strong": bench["strong"] - ai_adj,
                    "acceptable": bench["acceptable"] - ai_adj,
                    "warning": bench["warning"] - ai_adj,
                    "source": bench["source"],
                    "as_of": bench["as_of"],
                }
                rating = _rate_higher_is_better(gm, adjusted_bench)
                evidence = (
                    f"Gross margin of {gm:.0%}; AI-adjusted ({ai_adj:.0%} discount) "
                    f"benchmark strong >= {adjusted_bench['strong']:.0%}"
                )
                metrics.append(
                    _metric(
                        "gross_margin",
                        gm,
                        rating,
                        evidence,
                        adjusted_bench["source"],
                        adjusted_bench["as_of"],
                        bench=adjusted_bench,
                    )
                )
            else:
                rating = _rate_higher_is_better(gm, bench)
                evidence = f"Gross margin of {gm:.0%}; stage benchmark strong >= {bench['strong']:.0%}"
                metrics.append(
                    _metric(
                        "gross_margin",
                        gm,
                        rating,
                        evidence,
                        bench["source"],
                        bench["as_of"],
                        bench=bench,
                    )
                )
        else:
            metrics.append(
                _metric(
                    "gross_margin",
                    gm,
                    "not_rated",
                    f"Gross margin of {gm:.0%}; no benchmark for stage '{stage}'",
                )
            )
    else:
        metrics.append(_metric("gross_margin", None, "not_rated", "Gross margin not provided"))

    # 8. NRR (SaaS only)
    if saas:
        nrr = _deep_get(revenue, "nrr")
        if nrr is not None:
            bench = benchmarks.get("nrr")
            if bench:
                rating = _rate_higher_is_better(nrr, bench)
                evidence = f"NRR of {nrr:.0%}; stage benchmark strong >= {bench['strong']:.0%}"
                metrics.append(_metric("nrr", nrr, rating, evidence, bench["source"], bench["as_of"], bench=bench))
            else:
                metrics.append(
                    _metric(
                        "nrr",
                        nrr,
                        "not_rated",
                        f"NRR of {nrr:.0%}; no benchmark for stage '{stage}'",
                    )
                )
        else:
            metrics.append(_metric("nrr", None, "not_rated", "NRR not provided"))
    else:
        metrics.append(_metric("nrr", None, "not_applicable", "NRR applies to SaaS/subscription models only"))

    # 9. GRR (SaaS only)
    if saas:
        grr = _deep_get(revenue, "grr")
        if grr is not None:
            bench = benchmarks.get("grr")
            if bench:
                rating = _rate_higher_is_better(grr, bench)
                evidence = f"GRR of {grr:.0%}; stage benchmark strong >= {bench['strong']:.0%}"
                metrics.append(_metric("grr", grr, rating, evidence, bench["source"], bench["as_of"], bench=bench))
            else:
                metrics.append(
                    _metric(
                        "grr",
                        grr,
                        "not_rated",
                        f"GRR of {grr:.0%}; no benchmark for stage '{stage}'",
                    )
                )
        else:
            metrics.append(_metric("grr", None, "not_rated", "GRR not provided"))
    else:
        metrics.append(_metric("grr", None, "not_applicable", "GRR applies to SaaS/subscription models only"))

    # 10. Rule of 40 (SaaS only)
    if saas:
        arr_val_for_r40 = _deep_get(revenue, "arr", "value")
        if arr_val_for_r40 is not None and arr_val_for_r40 < 1_000_000:
            metrics.append(
                _metric(
                    "rule_of_40",
                    None,
                    "not_applicable",
                    f"Rule of 40 not meaningful below $1M ARR (current: ${arr_val_for_r40:,.0f})",
                )
            )
        elif growth_rate is not None and (
            gm is not None or (monthly_burn_raw is not None and mrr is not None and mrr > 0)
        ):
            # Annualize monthly growth rate
            growth_annualized = ((1 + growth_rate) ** 12 - 1) * 100

            # Prefer operating margin (burn-derived, closer to FCF margin)
            if monthly_burn_raw is not None and mrr is not None and mrr > 0:
                op_margin = -monthly_burn_raw / mrr
                if op_margin > 1.0:
                    # > 100% operating margin is implausible — likely sign error
                    print(
                        f"Warning: computed operating margin {op_margin:.0%} exceeds 100%, "
                        f"likely sign error in monthly_net_burn ({monthly_burn_raw:,.0f}); "
                        f"falling back to gross margin for R40",
                        file=sys.stderr,
                    )
                    if gm is None:
                        metrics.append(
                            _metric(
                                "rule_of_40",
                                None,
                                "not_rated",
                                "Insufficient data for Rule of 40 "
                                "(operating margin implausible, no gross margin available)",
                            )
                        )
                        margin_value = None
                        margin_label = "skipped"
                    else:
                        margin_value = gm
                        margin_label = "gross"
                else:
                    margin_value = op_margin
                    margin_label = "operating"
            else:
                margin_value = gm
                margin_label = "gross"

            if margin_label == "skipped":
                pass  # already appended not_rated metric above
            else:
                r40 = round(growth_annualized + margin_value * 100, 1)  # type: ignore[operator]

                # Priority: hyper-growth → margin type → benchmark availability
                if growth_annualized > 200:
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            "contextual",
                            f"Rule of 40 score: {r40:.0f} "
                            f"(growth {growth_annualized:.0f}% + {margin_label} margin {margin_value:.0%}); "
                            f"score is inflated by hyper-early growth and not comparable "
                            f"to the >= 40 benchmark used for scaled companies",
                        )
                    )
                elif margin_label == "gross":
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            "contextual",
                            f"Rule of 40 score: {r40:.0f} "
                            f"(growth {growth_annualized:.0f}% + gross margin {margin_value:.0%}); "
                            f"using gross margin as proxy — overstates R40 vs. FCF-based standard",
                        )
                    )
                elif arr_val_for_r40 is not None and arr_val_for_r40 < 5_000_000:
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            "contextual",
                            f"Rule of 40: components — growth {growth_annualized:.0f}%, "
                            f"{margin_label} margin {margin_value:.0%} "
                            f"(composite {r40:.0f}); "
                            f"not benchmark-compared below $5M ARR",
                        )
                    )
                elif bench := benchmarks.get("rule_of_40"):
                    rating = _rate_higher_is_better(r40, bench)
                    evidence = (
                        f"Rule of 40 score: {r40:.0f} "
                        f"(growth {growth_annualized:.0f}% + operating margin (burn-derived) {margin_value:.0%}); "
                        f"benchmark strong >= {bench['strong']}"
                    )
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            rating,
                            evidence,
                            bench["source"],
                            bench["as_of"],
                            bench=bench,
                        )
                    )
                else:
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            "not_rated",
                            f"Rule of 40 score: {r40:.0f} "
                            f"(using operating margin (burn-derived)); no benchmark for stage '{stage}'",
                        )
                    )
        elif arr_val_for_r40 is not None and arr_val_for_r40 < 1_000_000:
            metrics.append(
                _metric(
                    "rule_of_40",
                    None,
                    "not_applicable",
                    f"Rule of 40 not meaningful below $1M ARR (current: ${arr_val_for_r40:,.0f})",
                )
            )
        else:
            metrics.append(_metric("rule_of_40", None, "not_rated", "Insufficient data for Rule of 40"))
    else:
        metrics.append(_metric("rule_of_40", None, "not_applicable", "Rule of 40 applies to SaaS models only"))

    # 11. ARR per FTE (SaaS only)
    if saas:
        arr_val = _deep_get(revenue, "arr", "value")
        headcount = _deep_get(expenses, "headcount", default=[])
        total_fte = sum(p.get("count", 0) for p in headcount) if headcount else 0
        if arr_val is not None and total_fte > 0:
            arr_fte = round(arr_val / total_fte)
            # No stage benchmark for arr_per_fte; use general SaaS benchmark
            evidence = f"ARR/FTE of ${arr_fte:,} (ARR ${arr_val:,} / {total_fte} FTEs)"
            metrics.append(_metric("arr_per_fte", arr_fte, "not_rated", evidence))
        else:
            metrics.append(_metric("arr_per_fte", None, "not_rated", "Insufficient data for ARR per FTE"))
    else:
        metrics.append(_metric("arr_per_fte", None, "not_applicable", "ARR/FTE applies to SaaS models only"))

    # --- Build summary ---
    computed = sum(1 for m in metrics if m["value"] is not None)
    rating_counts: dict[str, int] = {
        "strong": 0,
        "acceptable": 0,
        "warning": 0,
        "fail": 0,
        "not_rated": 0,
        "contextual": 0,
        "not_applicable": 0,
    }
    for m in metrics:
        r = m["rating"]
        if r in rating_counts:
            rating_counts[r] += 1

    summary = {"computed": computed, **rating_counts}

    result: dict[str, Any] = {"metrics": metrics, "summary": summary}
    if ue_warnings:
        result["warnings"] = ue_warnings
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Unit economics calculator for financial model review (reads JSON from stdin)"
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"company\": {...}, ...}' | python unit_economics.py --pretty",
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

    if "company" not in data:
        result: dict[str, Any] = {"validation": {"status": "invalid", "errors": ["Missing required key: 'company'"]}}
        _write_output(json.dumps(result, indent=indent) + "\n", args.output)
        return

    result = _compute_metrics(data)
    # Propagate run_id from inputs metadata into output for stale-artifact detection
    _input_metadata = data.get("metadata")
    if isinstance(_input_metadata, dict) and isinstance(_input_metadata.get("run_id"), str):
        result.setdefault("metadata", {})["run_id"] = _input_metadata["run_id"]
    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    _write_output(
        out,
        args.output,
        summary={"computed": s["computed"], "strong": s["strong"], "fail": s["fail"]},
    )


if __name__ == "__main__":
    main()
