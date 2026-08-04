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
from typing import Any, NoReturn

# Sibling helper: fingerprints of this producer's inputs, so a later verifier can detect an output
# computed against inputs that have since changed (run_id parity cannot see that — corrections rewrite
# inputs.json within a single run).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fingerprint  # noqa: E402


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

    Mirrors the helper in every other producer, for the same two reasons.

    The error JSON still goes to STDOUT so the caller can read the diagnostic; only the exit
    code and stderr are new. It is deliberately NOT written to `--output`, because that path is
    a canonical artifact: overwriting it with a figure-less stub destroys the prior good file
    AND reads as truth to `compose_report.py`.

    Exit 1 is what makes the failure reachable. Each SKILL.md's producer-error branch is written
    as "the pipe fails next" — with exit 0 and an `{{"ok":true}}` receipt, that branch could never
    fire, so a rejected run was indistinguishable from a successful one.
    """
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Stage benchmarks
# ---------------------------------------------------------------------------

STAGE_BENCHMARKS: dict[str, dict[str, dict[str, Any]]] = {
    "pre-seed": {
        "burn_multiple": {
            "strong": 3.0,
            "acceptable": 4.0,
            "warning": 5.0,
            "source": "CFO Advisors 2025 / best-practices resolution (extrapolated to pre-seed)",
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
            "source": "commonly cited R40 tiers; see references/benchmarks.md",
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
            "source": "commonly cited R40 tiers; see references/benchmarks.md",
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
        "source": "Benchmarkit 2025 (ACV-segmented payback) / KeyBanc Sapphire 2024",
        "as_of": "2024-Q4",
    },
    "mid-market": {
        "strong": 12,
        "acceptable": 15,
        "warning": 21,
        "source": "Benchmarkit 2025 (ACV-segmented payback) / KeyBanc Sapphire 2024",
        "as_of": "2024-Q4",
    },
    "enterprise": {
        "strong": 15,
        "acceptable": 20,
        "warning": 30,
        "source": "Benchmarkit 2025 (ACV-segmented payback) / KeyBanc Sapphire 2024",
        "as_of": "2024-Q4",
    },
    "large-ent": {
        "strong": 18,
        "acceptable": 24,
        "warning": 36,
        "source": "Benchmarkit 2025 (ACV-segmented payback) / KeyBanc Sapphire 2024",
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

# ---------------------------------------------------------------------------
# Sector gross-margin benchmarks
# ---------------------------------------------------------------------------
# The stage-keyed tables above are SaaS-survey-based and only valid for
# software-margin businesses. Physical-goods and consumer sectors get their
# own tables. Tiers are constructed anchors, not published tiers: strong =
# the sector's canonical operating rule or best-category public aggregate;
# acceptable = the core sector aggregate; warning = the thinnest published
# adjacent-category aggregate (rounded to 5pts). Stage-invariant because none
# of the sources segment by startup stage.

GM_BENCHMARKS_BY_SECTOR: dict[str, dict[str, Any]] = {
    "hardware": {
        "strong": 0.50,
        "acceptable": 0.40,
        "warning": 0.25,
        "source": (
            "Hardware >=50% GM rule (Barros, Adafruit hardware-startup guide); "
            "tiers derived from NYU Stern Damodaran sector margins (Jan 2026)"
        ),
        "as_of": "2026-01",
    },
    "consumer-subscription": {
        "strong": 0.65,
        "acceptable": 0.45,
        "warning": 0.30,
        "source": (
            "Derived from NYU Stern Damodaran Software (Entertainment) margins (Jan 2026) "
            "and FY2024 public comps (Duolingo / Netflix / Spotify filings)"
        ),
        "as_of": "2026-01",
    },
    "retail": {
        "strong": 0.50,
        "acceptable": 0.35,
        "warning": 0.25,
        "source": "Derived from NYU Stern Damodaran retail sector margins (Jan 2026)",
        "as_of": "2026-01",
    },
}

# revenue_model_type -> sector table key. The hardware table applies to pure
# devices only: the >=50% rule it anchors on explicitly excludes products
# with ongoing service revenue, so hardware-subscription is contextual below.
_GM_SECTOR_TABLE: dict[str, str] = {
    "hardware": "hardware",
    "consumer-subscription": "consumer-subscription",
    "retail": "retail",
}

# Model types whose gross margin is rated contextual, never pass/fail:
# - marketplace / transactional-fintech: GM depends on the revenue-recognition
#   basis (net take-rate vs gross GMV/GTV), which inputs.json cannot express,
#   and healthy net-basis comps span ~40pts.
# - hardware-subscription: a single GM number cannot be decomposed into the
#   hardware vs service margin split a blend must be judged on.
# - usage-based: healthy consumption models span passthrough-heavy CPaaS
#   (~51%) to software-margin platforms (~72%+); one bar mis-rates one end.
_GM_CONTEXTUAL_TYPES = frozenset({"marketplace", "transactional-fintech", "hardware-subscription", "usage-based"})

_GM_CONTEXTUAL_SOURCES: dict[str, str] = {
    "marketplace": "FY2024 public comps, net-revenue basis (Airbnb ~83% vs DoorDash ~46%, 10-K filings)",
    "transactional-fintech": "FY2024 public comps, net-revenue basis (Airbnb ~83% vs DoorDash ~46%, 10-K filings)",
    "hardware-subscription": "Hardware >=50% GM rule (Barros, Adafruit hardware-startup guide) — device-only scope",
    "usage-based": "FY2024 public comps (Twilio 10-K ~51% GAAP GM) vs KeyBanc SaaS Survey 2024 (median ~72%)",
}

_GM_CONTEXTUAL_EVIDENCE: dict[str, str] = {
    "marketplace": (
        "margins depend on the revenue-recognition basis (net take-rate vs gross volume) "
        "and healthy net-basis comps span ~40pts, so no single benchmark applies"
    ),
    "transactional-fintech": (
        "margins depend on the revenue-recognition basis (net take-rate vs gross volume) "
        "and healthy net-basis comps span ~40pts, so no single benchmark applies"
    ),
    "hardware-subscription": (
        "blended hardware+subscription margins need the hardware vs service revenue split — "
        "the >=50% device rule excludes products with ongoing service revenue"
    ),
    "usage-based": (
        "consumption models span passthrough-heavy infrastructure to software-margin platforms; "
        "a single benchmark would mis-rate one end"
    ),
}

# Valid gross_margin_basis values. All threshold tables assume product/service
# gross margin; any other declared basis (store contribution, gross-revenue
# booking, blends) is not comparable and rates contextual.
_GM_BASIS_VALUES = ("product", "store_contribution", "net_revenue", "gross_revenue", "blended")

# AI cost keys in expenses.cogs — keep in sync with checklist.py's
# _AI_COST_KEYS (SECTOR_40 gate uses the same set).
_AI_COGS_KEYS = frozenset({"inference_costs", "ai_infrastructure", "ai_compute", "gpu_costs", "model_inference"})

# SaaS model types
_SAAS_MODEL_TYPES = {"saas-plg", "saas-sales-led", "annual-contracts"}

# Types that legitimately use the SaaS gross-margin table without an
# assumption disclosure; any other type reaching the SaaS fallback is
# unknown and the evidence says so.
_KNOWN_SAAS_LIKE_TYPES = frozenset({"saas-plg", "saas-sales-led", "annual-contracts", "ai-native"})

# Metrics only applicable to SaaS
_SAAS_ONLY_METRICS = {"nrr", "grr", "magic_number", "rule_of_40", "arr_per_fte"}

# AI-related sectors that get gross margin threshold adjustment
_AI_SECTORS = {"ai-native", "ai", "ai native"}

# Lower-is-better metrics (for rating direction)
_LOWER_IS_BETTER = {"burn_multiple", "cac_payback", "cac"}

# opex_monthly categories counted in the S&M denominator for magic number.
# Source: Scale VP "Magic Number Math" — denominator is ALL S&M spend.
SM_OPEX_CATEGORIES: frozenset[str] = frozenset(
    {
        "marketing",
        "ads",
        "advertising",
        "demand gen",
        "demand generation",
        "growth",
        "s&m",
        "sales & marketing",
        "sales and marketing",
    }
)


# ---------------------------------------------------------------------------
# Rating helpers
# ---------------------------------------------------------------------------


# Above these, a value is far more likely a units or sign error than a real
# figure — the same reasoning as the burn-multiple and operating-margin guards.
# A scale where higher is better rates an absurd number "strong" and stops
# checking, so the one input most worth a second look is the one that sails
# through. Structural where a ceiling exists; otherwise set where a value stops
# being achievable rather than merely elite. This detects mis-scaled input, it
# does not grade a business.
_IMPLAUSIBLE_ABOVE: dict[str, float] = {
    "gross_margin": 1.0,  # COGS cannot be negative
    "grr": 1.0,  # gross retention excludes expansion by definition
    "nrr": 3.0,  # 300% net retention is a decimal-point error, not a company
    "ltv_cac_ratio": 50.0,  # same magnitude the burn-multiple guard treats as implausible
    "magic_number": 10.0,  # $10 of new ARR per $1 of S&M reads as a period mismatch in the inputs
}

# The mirror for scales where lower is better. A value at or below these is not
# merely excellent, it is impossible: a payback period cannot be zero or negative,
# because the cost is incurred before any of it is recovered. Without this the
# best possible rating is what an input error earns.
_IMPLAUSIBLE_AT_OR_BELOW: dict[str, float] = {
    "cac_payback": 0.0,
}


def _implausibility_note(metric_id: str, value: float, *, pct: bool) -> str | None:
    """Explain why *value* reads as an input error, or None when it is in range."""
    floor = _IMPLAUSIBLE_AT_OR_BELOW.get(metric_id)
    if floor is not None and value <= floor:
        unit = "months" if metric_id == "cac_payback" else ""
        return (
            f"Not rated: {value:g} {unit}".rstrip()
            + " is at or below zero, which cannot happen — the cost is incurred before any of "
            "it is recovered, so this reads as a sign or units error in the source"
        )
    ceiling = _IMPLAUSIBLE_ABOVE.get(metric_id)
    if ceiling is None or value <= ceiling:
        return None
    shown = f"{value:.0%}" if pct else f"{value:.1f}x"
    limit = f"{ceiling:.0%}" if pct else f"{ceiling:.0f}x"
    return (
        f"Not rated: {shown} exceeds {limit}, which reads as a units or sign error in the "
        f"source rather than a real figure — check the input before treating it as a strength"
    )


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


def _resolve_stage_benchmarks(stage: str) -> tuple[dict[str, dict[str, Any]], dict[str, str] | None]:
    """Benchmarks for *stage*, plus the resolution when one had to be substituted.

    Published medians do not exist for every stage, and substituting a
    neighbouring stage's is better than inventing a number. But the substitution
    changes every rating computed from it, so it is returned as data for the
    artifact to carry rather than announced on stderr, which no founder reads.
    """
    if stage in STAGE_BENCHMARKS:
        return STAGE_BENCHMARKS[stage], None
    return STAGE_BENCHMARKS["series-a"], {
        "requested": stage,
        "resolved_to": "series-a",
        "reason": "no published benchmarks for this stage",
    }


def _get_stage_benchmarks(stage: str) -> dict[str, dict[str, Any]]:
    """Benchmarks for *stage*, discarding the resolution detail."""
    return _resolve_stage_benchmarks(stage)[0]


def _is_saas(model_type: str) -> bool:
    """Check if the revenue model type is SaaS."""
    return model_type.lower() in _SAAS_MODEL_TYPES


def has_ai_cogs(inputs: dict[str, Any]) -> bool:
    """Check whether expenses.cogs carries material AI cost line items."""
    cogs = (inputs.get("expenses") or {}).get("cogs")
    if not isinstance(cogs, dict):
        return False
    return bool(_AI_COGS_KEYS & cogs.keys())


def _ai_discount_applies(sector: str, model_type: str, traits: list[str] | None, ai_cogs: bool) -> bool:
    """Whether the AI gross-margin threshold adjustment applies.

    An AI-native model/sector qualifies outright; the ai-powered trait alone
    is a scrutiny signal, not a concession — it discounts the bar only when
    AI costs are actually present in COGS.
    """
    if sector.lower() in _AI_SECTORS or model_type.lower() == "ai-native":
        return True
    return bool(traits and "ai-powered" in traits) and ai_cogs


def _ai_gm_adjustment(stage: str) -> float:
    """Gross-margin threshold discount for AI companies (larger at later stages)."""
    return 0.10 if stage.lower() in ("series-a", "series-b", "series-c", "series-d", "later") else 0.05


def gm_contextual_reason(model_type: str, basis: str | None = None) -> str | None:
    """Why a gross margin is rated contextual, or None if it is threshold-ratable.

    Contextual when the model type is a take-rate/blend/consumption type, or
    when a declared gross_margin_basis is anything other than product-basis
    (the threshold tables all assume product/service gross margin).
    """
    mt = model_type.lower()
    if mt in _GM_CONTEXTUAL_TYPES:
        return mt
    if basis and basis != "product":
        return "basis"
    return None


def gm_benchmark_for(
    model_type: str,
    stage: str,
    sector: str = "",
    traits: list[str] | None = None,
    basis: str | None = None,
    ai_cogs: bool = False,
) -> dict[str, Any] | None:
    """Resolve the fully-adjusted gross-margin benchmark for a company profile.

    Selects the sector table when one exists, the stage-keyed SaaS table for
    SaaS-like or unknown model types, and applies the AI threshold adjustment
    when it is earned (carried as an "ai_adjustment" key). Returns None when
    the gross margin is rated contextual (see gm_contextual_reason). Shared
    with explore.py so the interactive explorer re-rates against the same bar
    as the review.
    """
    mt = model_type.lower()
    if gm_contextual_reason(mt, basis) is not None:
        return None
    sector_key = _GM_SECTOR_TABLE.get(mt)
    bench: dict[str, Any] | None
    if sector_key:
        bench = GM_BENCHMARKS_BY_SECTOR[sector_key]
    else:
        bench = _get_stage_benchmarks(stage.lower()).get("gross_margin")
    if bench is None:
        return None
    if _ai_discount_applies(sector, mt, traits or [], ai_cogs):
        ai_adj = _ai_gm_adjustment(stage)
        return {
            "strong": bench["strong"] - ai_adj,
            "acceptable": bench["acceptable"] - ai_adj,
            "warning": bench["warning"] - ai_adj,
            "source": bench["source"],
            "as_of": bench["as_of"],
            "ai_adjustment": ai_adj,
        }
    return bench


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


def _currency_code(inputs: dict[str, Any]) -> str:
    """Return the model's native currency code, defaulting to 'USD'.

    Absent or non-string `currency` is the back-compat default (USD-equivalent);
    downstream USD-denominated benchmarks apply unchanged in that case.
    """
    currency = inputs.get("currency")
    if isinstance(currency, str) and currency.strip():
        return currency.strip().upper()
    return "USD"


def _fmt_money(value: float, currency_code: str) -> str:
    """Format a monetary value, tagging non-USD currencies instead of a bare '$'."""
    if currency_code == "USD":
        return f"${value:,.0f}"
    return f"{value:,.0f} {currency_code}"


def _apply_non_usd_benchmark_caveat(metric_entry: dict[str, Any], currency_code: str) -> None:
    """Downgrade a USD-calibrated benchmark rating to `contextual` for a
    non-USD-denominated model.

    burn_multiple and rule_of_40 are currency-agnostic RATIOS (net burn / net-new
    ARR; growth% + margin%) — the ratio itself is valid and meaningful regardless
    of currency. Only the ARR materiality floor ($500K / $1M / $5M) is an absolute
    USD amount that cannot be verified against a native non-USD value. So the
    ratio is always computed and shown; a rating that would otherwise apply the
    USD benchmark (strong/acceptable/warning/fail) is downgraded to `contextual`
    with a caveat. Ratings that are already not_rated/not_applicable/contextual
    for an unrelated reason (insufficient data, implausible sign, hyper-growth,
    etc.) are left untouched.

    The downgraded grade is PRESERVED as `benchmark_reference_rating` (plus its
    benchmark, source and as-of) so a non-USD review still carries graded signal.
    That is deliberately a reference and never the verdict — see the inline note
    on why the withholding is about USD-market CALIBRATION, not about units.
    """
    if metric_entry["rating"] not in ("strong", "acceptable", "warning", "fail"):
        return

    # The grade the benchmark comparison ALREADY produced, captured before it is discarded. Preserving
    # it as a clearly-labelled REFERENCE (never as the verdict) is what keeps a non-USD review from
    # losing nearly all of its graded feedback: with the ARR floors correctly suppressed, LTV/CAC, burn
    # multiple and Rule of 40 otherwise ALL land contextual/not_rated at once, and the founder gets a
    # page of numbers with no assessment. That matters most for exactly the audience most likely to file
    # in a local currency.
    #
    # No FX rate is needed, and none is invented. These thresholds are DIMENSIONLESS — burn multiple
    # 2.0x/2.5x/3.0x, gross margin 0.70/0.60/0.50, Rule of 40 as a sum of percentages. A ratio of 1.5x is
    # 1.5x in any currency, so the comparison is exact rather than converted. What genuinely does need an
    # FX rate is any ABSOLUTE threshold — the $500K/$1M/$5M ARR materiality floors and the ACV-tier
    # boundaries that select a CAC-payback band — and those stay suppressed.
    reference_rating = metric_entry["rating"]
    reference_benchmark = metric_entry.get("benchmark")

    metric_entry["rating"] = "contextual"
    metric_entry["evidence"] += (
        f"; ratio shown but not benchmark-compared — the stage benchmark and ARR "
        f"materiality floor are USD-denominated and not verifiable against a "
        f"{currency_code}-denominated model"
    )
    # The primary rating stays `contextual`: it is a reliance boundary, not a confidence score, and the
    # USD-calibrated benchmark set was not established against local-currency-market companies. The
    # reference grade says what the ratio WOULD score, and says so as a reference.
    metric_entry["benchmark_reference_rating"] = reference_rating
    metric_entry["benchmark_reference_note"] = (
        f"Reference only, not a verdict: the ratio scores '{reference_rating}' against the "
        f"stage benchmark, which is a dimensionless threshold and so compares exactly without any "
        f"currency conversion. Withheld from the rating because the benchmark set is calibrated on "
        f"USD-market companies, not because the number is unit-incompatible."
    )
    if reference_benchmark is not None:
        metric_entry["benchmark_reference"] = reference_benchmark
    # Keep the provenance discoverable on the reference rather than blanking it outright — a founder who
    # is shown a reference grade is entitled to see what it was measured against.
    metric_entry["benchmark_reference_source"] = metric_entry.get("benchmark_source") or ""
    metric_entry["benchmark_reference_as_of"] = metric_entry.get("benchmark_as_of") or ""
    metric_entry["benchmark_source"] = ""
    metric_entry["benchmark_as_of"] = ""
    metric_entry.pop("benchmark", None)


def _num(x: Any, default: float) -> float:
    """Coerce x to a numeric value, falling back to default for null/non-numeric.

    The dict.get() default only applies to missing keys, not to keys present
    with an explicit JSON null. Blank/cleared headcount cells are coerced to
    None by the corrections layer, so numeric reads must guard against None.
    """
    if isinstance(x, bool):
        return default
    if isinstance(x, (int, float)):
        return x
    return default


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


def _realized_yoy_growth_pct_from_monthly(entries: list[dict[str, Any]]) -> float | None:
    """Compute realized YoY revenue growth % from monthly time-series (≥12 entries).

    Source: Brad Feld canonical R40 — growth = "year-over-year growth rate".
    Uses the same lookback logic as ``_net_new_arr_from_monthly``.
    Returns None if fewer than 12 entries or if year-ago ARR is zero/None.
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
    lookback_idx = -13 if len(sorted_entries) >= 13 else 0
    year_ago_arr = _arr_value(sorted_entries[lookback_idx])
    if latest_arr is None or year_ago_arr is None or year_ago_arr == 0:
        return None
    return (latest_arr - year_ago_arr) / year_ago_arr * 100


def _realized_yoy_growth_pct_from_quarterly(entries: list[dict[str, Any]]) -> float | None:
    """Compute realized YoY revenue growth % from quarterly time-series (≥5 entries).

    Uses the same lookback logic as ``_net_new_arr_from_quarterly`` (true 4-quarter window
    when ≥5 entries exist). Returns None if fewer than 5 entries or if year-ago ARR is zero/None.
    """
    if len(entries) < 5:
        return None
    sorted_entries = sorted(entries, key=lambda e: e.get("quarter", ""))

    def _arr_value(entry: dict[str, Any]) -> float | None:
        arr = entry.get("arr")
        if isinstance(arr, (int, float)):
            return float(arr)
        total = entry.get("total")
        if isinstance(total, (int, float)):
            return float(total) * 4
        return None

    latest_arr = _arr_value(sorted_entries[-1])
    year_ago_arr = _arr_value(sorted_entries[-5])
    if latest_arr is None or year_ago_arr is None or year_ago_arr == 0:
        return None
    return (latest_arr - year_ago_arr) / year_ago_arr * 100


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
    data_confidence = company.get("data_confidence", "exact")

    benchmarks, benchmark_basis = _resolve_stage_benchmarks(stage)
    metrics: list[dict[str, Any]] = []
    ue_warnings: list[dict[str, str]] = []
    bench: dict[str, Any] | None = None  # reused across metric sections

    # Currency determinism: absent/`"USD"` keeps today's behavior exactly;
    # a native non-USD currency disables the USD-absolute ARR floor gates below.
    currency_code = _currency_code(inputs)
    is_non_usd_currency = currency_code != "USD"

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
        if not saas and model_type in ("hardware", "hardware-subscription", "marketplace", "retail"):
            rating = "contextual"
            evidence = (
                f"{loaded_note} CAC of {_fmt_money(cac_total, currency_code)}; "
                f"CAC benchmarks vary significantly for {model_type} models"
            )
        else:
            # Use default payback benchmark source for CAC rating reference
            rating = "not_rated"
            evidence = f"{loaded_note} CAC of {_fmt_money(cac_total, currency_code)}"
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
                evidence = (
                    f"LTV of {_fmt_money(ltv_value, currency_code)} "
                    f"({obs_note}; capped at 5-year horizon, 0% churn assumed)"
                )
            else:
                ltv_unreliable = True
                evidence = (
                    f"LTV of {_fmt_money(ltv_value, currency_code)} ({obs_note}; 0% churn — "
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
            evidence = f"LTV of {_fmt_money(ltv_value, currency_code)} ({obs_note})"
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
            _note = _implausibility_note("ltv_cac_ratio", ltv_cac, pct=False)
            if _note:
                rating, evidence = "not_rated", _note
        # bench may be set (observed path) or unset (assumed path)
        ltv_cac_bench = bench if ltv_observed != "assumed" else None
        metrics.append(
            _metric(
                "ltv_cac_ratio",
                ltv_cac,
                rating,
                evidence,
                "KeyBanc/Sapphire 2024",
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
        _pb_note = _implausibility_note("cac_payback", payback, pct=False)
        evidence = f"CAC payback of {payback} months; {acv_tier} tier benchmark strong <= {bench['strong']} months"
        if _pb_note:
            rating, evidence = "not_rated", _pb_note
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

    # ARR floor — burn multiple not meaningful at very low ARR.
    # This floor is denominated in USD; a native non-USD ARR value cannot be
    # compared against it without conversion (see currency determinism note in
    # schema-inputs.md). For a non-USD model we don't know whether the raw
    # number clears the floor, so the gate is skipped entirely (rather than
    # withholding the metric) and the ratio is computed normally below — the
    # non-USD downgrade to `contextual` happens once, uniformly, after the
    # metric is built (see _apply_non_usd_benchmark_caveat).
    arr_val_for_bm = _deep_get(revenue, "arr", "value")
    _arr_below_floor = not is_non_usd_currency and arr_val_for_bm is not None and arr_val_for_bm < 500_000

    def _implausible_bm_evidence(mult: float, method: str = "") -> str:
        """Evidence for an implausibly-high burn multiple.

        Skipping the USD $500K materiality floor for a non-USD model is deliberate (see above), but the
        consequence has to be stated honestly: an immaterial ARR base inflates the ratio, and for a
        non-USD model that base was never gated because the floor is USD-denominated. Blaming "input
        consistency" there sends the founder to look for a data error that does not exist. The uniform
        non-USD caveat cannot repair it either — it early-returns on `not_rated`.
        """
        suffix = f" ({method})" if method else ""
        if is_non_usd_currency:
            return (
                f"Burn multiple of {mult:.1f}x{suffix} is implausibly high. The most likely cause is a "
                f"small net-new-ARR base: the materiality floor that would normally withhold this metric "
                f"is USD-denominated and cannot be applied to a {currency_code} model without an FX rate. "
                f"Confirm the ARR base is material before reading anything into the ratio."
            )
        return f"Burn multiple of {mult:.1f}x{suffix} is implausibly high — check input consistency"

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

    _bm_metric_start = len(metrics)
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
                    _implausible_bm_evidence(burn_mult, _bm_method_label),
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
        # Divergence check: if growth-rate method is also available, compare.
        # Period-matched: monthly_burn / (ΔMRR*12) — same convention as the standalone
        # fallback below. Example (mrr=50K, g=0.08, burn=80K):
        #   _gr_net_new_arr = 50K*0.08*12 = 48K (ARR added per month)
        #   _gr_burn_mult = 80K/48K = 1.67x
        if _compute_inputs_present and growth_rate > 0:
            _gr_net_new_arr = mrr * growth_rate * 12
            if _gr_net_new_arr > 0:
                _gr_burn_mult = round(monthly_burn / _gr_net_new_arr, 2)
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
        net_new_arr = mrr * growth_rate * 12  # ARR added per month = ΔMRR*12
        if net_new_arr > 0:
            # period-matched: burn for the month ÷ ARR added in the month (ΔMRR×12)
            burn_mult = round(monthly_burn / net_new_arr, 2)
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
                        _implausible_bm_evidence(burn_mult),
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

    if is_non_usd_currency:
        _apply_non_usd_benchmark_caveat(metrics[_bm_metric_start], currency_code)

    # 6. Magic number (SaaS only)
    # Source: Scale VP "Magic Number Math" — denominator is ALL S&M (headcount + marketing opex).
    if saas:
        # S&M headcount spend
        headcount = _deep_get(expenses, "headcount", default=[])
        sm_hc_annual = 0.0
        for person in headcount:
            role = str(person.get("role", "")).lower()
            if role in ("sales", "marketing", "sales & marketing", "s&m", "growth"):
                count = _num(person.get("count", 0), 0)
                salary = _num(person.get("salary_annual", 0), 0)
                burden = _num(person.get("burden_pct", 0.0), 0.0)
                sm_hc_annual += count * salary * (1 + burden)

        # Non-headcount marketing/S&M opex (opex_monthly.amount is monthly → × 12)
        opex_monthly_entries = _deep_get(expenses, "opex_monthly", default=[]) or []
        sm_opex_annual = 0.0
        for entry in opex_monthly_entries:
            cat = str(entry.get("category", "")).lower().strip()
            if cat in SM_OPEX_CATEGORIES:
                sm_opex_annual += _num(entry.get("amount", 0), 0) * 12

        sm_spend_annual = sm_hc_annual + sm_opex_annual

        if mrr is not None and growth_rate is not None and growth_rate > 0 and sm_spend_annual > 0:
            net_new_arr = mrr * growth_rate * 12  # ΔMRR × 12 = monthly net-new ARR
            sm_spend_monthly = sm_spend_annual / 12
            magic = round(net_new_arr / sm_spend_monthly, 2)
            bench = benchmarks.get("magic_number")
            _sm_base_desc = (
                "sales/marketing headcount + marketing opex" if sm_opex_annual > 0 else "sales/marketing headcount"
            )
            if bench:
                rating = _rate_higher_is_better(magic, bench)
                evidence = (
                    f"Magic number of {magic:.2f} "
                    f"(monthly net-new ARR ÷ monthly S&M ({_sm_base_desc})); "
                    f"stage benchmark strong >= {bench['strong']}"
                )
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
                        f"Magic number of {magic:.2f} "
                        f"(monthly net-new ARR ÷ monthly S&M ({_sm_base_desc})); "
                        f"no benchmark for stage '{stage}'",
                    )
                )
        else:
            metrics.append(_metric("magic_number", None, "not_rated", "Insufficient data for magic number"))
    else:
        metrics.append(_metric("magic_number", None, "not_applicable", "Magic number applies to SaaS models only"))

    # 7. Gross margin — benchmarked against the sector-appropriate table
    gm = _deep_get(unit_econ, "gross_margin")
    gm_basis = _deep_get(unit_econ, "gross_margin_basis")
    if gm is not None:
        contextual_reason = gm_contextual_reason(model_type, gm_basis if isinstance(gm_basis, str) else None)
        if contextual_reason == "basis":
            # A declared non-product basis (store contribution, gross-revenue
            # booking, blends) is not comparable to any threshold table.
            evidence = (
                f"Gross margin of {gm:.0%} on a {gm_basis} basis; not comparable to the product "
                f"gross-margin tables — assess store-level contribution, buildout payback, and "
                f"same-store trends instead"
            )
            sector_key = _GM_SECTOR_TABLE.get(model_type)
            src = GM_BENCHMARKS_BY_SECTOR[sector_key]["source"] if sector_key else "declared gross_margin_basis"
            metrics.append(_metric("gross_margin", gm, "contextual", evidence, src, ""))
        elif contextual_reason is not None:
            evidence = f"Gross margin of {gm:.0%}; {model_type} {_GM_CONTEXTUAL_EVIDENCE[contextual_reason]}"
            metrics.append(
                _metric("gross_margin", gm, "contextual", evidence, _GM_CONTEXTUAL_SOURCES[contextual_reason], "FY2024")
            )
        else:
            bench = gm_benchmark_for(
                model_type,
                stage,
                sector,
                traits if isinstance(traits, list) else [],
                gm_basis if isinstance(gm_basis, str) else None,
                has_ai_cogs(inputs),
            )
            if bench:
                rating = _rate_higher_is_better(gm, bench)
                ai_adj = bench.get("ai_adjustment")
                bar_kind = "sector" if model_type in _GM_SECTOR_TABLE else "stage"
                if ai_adj:
                    evidence = (
                        f"Gross margin of {gm:.0%}; AI-adjusted ({ai_adj:.0%} discount) "
                        f"benchmark strong >= {bench['strong']:.0%}"
                    )
                else:
                    evidence = f"Gross margin of {gm:.0%}; {bar_kind} benchmark strong >= {bench['strong']:.0%}"
                if model_type in _GM_SECTOR_TABLE and gm_basis is None:
                    evidence += (
                        "; assumes product/merchandise gross margin (set gross_margin_basis "
                        "if this is store-level contribution)"
                    )
                elif bar_kind == "stage" and model_type not in _KNOWN_SAAS_LIKE_TYPES:
                    qualifier = "not provided" if not model_type else "not recognized"
                    evidence += f"; SaaS benchmark assumed (revenue model type {qualifier})"
                _note = _implausibility_note("gross_margin", gm, pct=True)
                if _note:
                    rating, evidence = "not_rated", _note
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
                _note = _implausibility_note("nrr", nrr, pct=True)
                if _note:
                    rating, evidence = "not_rated", _note
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
                _note = _implausibility_note("grr", grr, pct=True)
                if _note:
                    rating, evidence = "not_rated", _note
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
        # This floor is denominated in USD; for a non-USD model we don't know
        # whether the raw number clears it, so the gate is skipped (see the
        # matching burn_multiple comment above) and the score is computed
        # normally below — the non-USD downgrade to `contextual` happens once,
        # uniformly, after the metric is built.
        _r40_metric_start = len(metrics)
        if not is_non_usd_currency and arr_val_for_r40 is not None and arr_val_for_r40 < 1_000_000:
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
            # Growth basis: use realized YoY when ≥12 monthly (or ≥5 quarterly) entries exist;
            # fall back to annualized-MoM (forward annualization of current growth_rate).
            # Source: Brad Feld canonical R40 — growth = "year-over-year growth rate".
            _r40_yoy: float | None = None
            _r40_growth_basis: str = "annualized from current MoM rate"
            if isinstance(monthly_entries, list):
                _r40_yoy = _realized_yoy_growth_pct_from_monthly(monthly_entries)
                if _r40_yoy is not None:
                    _r40_growth_basis = "realized YoY"
            if _r40_yoy is None and isinstance(quarterly_entries, list):
                _r40_yoy = _realized_yoy_growth_pct_from_quarterly(quarterly_entries)
                if _r40_yoy is not None:
                    _r40_growth_basis = "realized YoY"

            growth_annualized = _r40_yoy if _r40_yoy is not None else ((1 + growth_rate) ** 12 - 1) * 100

            # Prefer operating margin (burn-derived, closer to FCF margin)
            if monthly_burn_raw is not None and mrr is not None and mrr > 0:
                # Negative monthly_net_burn below MRR yields a positive op margin — that is also
                # what a genuinely cash-flow-positive company looks like; validate_inputs --fix
                # handles sign errors upstream, and the >100% guard below catches the implausible cases.
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
                            f"(growth {growth_annualized:.0f}% {_r40_growth_basis}"
                            f" + {margin_label} margin {margin_value:.0%}); "
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
                            f"(growth {growth_annualized:.0f}% {_r40_growth_basis}"
                            f" + gross margin {margin_value:.0%}); "
                            f"using gross margin as proxy — overstates R40 vs. FCF-based standard",
                        )
                    )
                elif not is_non_usd_currency and arr_val_for_r40 is not None and arr_val_for_r40 < 5_000_000:
                    # USD-denominated $5M floor: skip for a non-USD model (its raw
                    # ARR can't be compared to a USD threshold) — falls through to the
                    # benchmark branch and gets the uniform non-USD contextual caveat.
                    metrics.append(
                        _metric(
                            "rule_of_40",
                            r40,
                            "contextual",
                            f"Rule of 40: components — "
                            f"growth {growth_annualized:.0f}% ({_r40_growth_basis}), "
                            f"{margin_label} margin {margin_value:.0%} "
                            f"(composite {r40:.0f}); "
                            f"not benchmark-compared below $5M ARR",
                        )
                    )
                elif bench := benchmarks.get("rule_of_40"):
                    rating = _rate_higher_is_better(r40, bench)
                    evidence = (
                        f"Rule of 40 score: {r40:.0f} "
                        f"(growth {growth_annualized:.0f}% {_r40_growth_basis}"
                        f" + operating margin (burn-derived) {margin_value:.0%}); "
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
                            f"(growth {_r40_growth_basis}; "
                            f"operating margin (burn-derived)); no benchmark for stage '{stage}'",
                        )
                    )
        else:
            # Note: the < $1M ARR not_applicable case is handled by the first
            # branch above (line ~972); arr_val_for_r40 is not reassigned, so
            # only the insufficient-data fallthrough remains here.
            metrics.append(_metric("rule_of_40", None, "not_rated", "Insufficient data for Rule of 40"))

        if is_non_usd_currency:
            _apply_non_usd_benchmark_caveat(metrics[_r40_metric_start], currency_code)
    else:
        metrics.append(_metric("rule_of_40", None, "not_applicable", "Rule of 40 applies to SaaS models only"))

    # 11. ARR per FTE (SaaS only)
    if saas:
        arr_val = _deep_get(revenue, "arr", "value")
        headcount = _deep_get(expenses, "headcount", default=[])
        total_fte = sum(_num(p.get("count", 0), 0) for p in headcount) if headcount else 0
        if arr_val is not None and total_fte > 0:
            arr_fte = round(arr_val / total_fte)
            # No stage benchmark for arr_per_fte; use general SaaS benchmark
            evidence = (
                f"ARR/FTE of {_fmt_money(arr_fte, currency_code)} "
                f"(ARR {_fmt_money(arr_val, currency_code)} / {total_fte} FTEs)"
            )
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

    result: dict[str, Any] = {"metrics": metrics, "summary": summary, "currency": currency_code}
    if benchmark_basis is not None:
        result["benchmark_basis"] = benchmark_basis
    if ue_warnings:
        result["warnings"] = ue_warnings
    # Self-declare insufficiency when fewer than two metrics are computable, so
    # the downstream gate can accept-with-warning (mirrors runway.py's flag).
    if computed < 2:
        result["insufficient_data"] = True
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
    p.add_argument(
        "--run-id",
        default=None,
        help="Stamp metadata.run_id (overrides any run_id from stdin metadata)",
    )
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
        _fail_invalid(result, args.output, indent)

    result = _compute_metrics(data)
    # Propagate run_id from inputs metadata into output for stale-artifact detection
    _input_metadata = data.get("metadata")
    if isinstance(_input_metadata, dict) and isinstance(_input_metadata.get("run_id"), str):
        result.setdefault("metadata", {})["run_id"] = _input_metadata["run_id"]
    if getattr(args, "run_id", None):  # CLI run_id overrides stdin passthrough
        result.setdefault("metadata", {})["run_id"] = args.run_id
    _fingerprint.stamp(result, {"inputs.json": data})
    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    _write_output(
        out,
        args.output,
        summary={"computed": s["computed"], "strong": s["strong"], "fail": s["fail"]},
    )


if __name__ == "__main__":
    main()
