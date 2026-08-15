#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Financial model review checklist scorer.

Validates 46 criteria across 7 categories with pass/fail/warn/not_applicable
scoring. Supports profile-based auto-gating by stage, geography, and sector.

Always reads JSON from stdin.

Usage:
    echo '{"items": [...], "company": {"stage": "seed", ...}}' \
        | python checklist.py --pretty

Output: JSON with validated items and summary.
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


# Canonical 46 checklist items grouped by category.
# Each item has gate fields for profile-based auto-gating:
#   stage_gate: "all" | "seed+" (seed and later stages)
#   geography_gate: "all" | list of matching geographies/traits
#   sector_gate: "all" | list of matching sectors/traits
CHECKLIST_ITEMS: list[dict[str, Any]] = [
    # Structure & Presentation (9)
    {
        "id": "STRUCT_01",
        "category": "Structure & Presentation",
        "label": "Assumptions isolated on dedicated tab",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_02",
        "category": "Structure & Presentation",
        "label": "Tab structure is navigable",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_03",
        "category": "Structure & Presentation",
        "label": "Actuals vs. projections separated",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_04",
        "category": "Structure & Presentation",
        "label": "Scenario toggles (base/up/down)",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_05",
        "category": "Structure & Presentation",
        "label": "Model matches pitch deck",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_06",
        "category": "Structure & Presentation",
        "label": "Version/date included",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_07",
        "category": "Structure & Presentation",
        "label": "Monthly granularity appropriate to stage",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_08",
        "category": "Structure & Presentation",
        "label": "No structural errors",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "STRUCT_09",
        "category": "Structure & Presentation",
        "label": "Professional formatting",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    # Revenue & Unit Economics (10)
    {
        "id": "UNIT_10",
        "category": "Revenue & Unit Economics",
        "label": "Revenue is bottom-up",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_11",
        "category": "Revenue & Unit Economics",
        "label": "Churn modeled explicitly",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_12",
        "category": "Revenue & Unit Economics",
        "label": "Pricing logic explicit",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_13",
        "category": "Revenue & Unit Economics",
        "label": "Expansion revenue modeled",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_14",
        "category": "Revenue & Unit Economics",
        "label": "COGS/margin matches model type",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_15",
        "category": "Revenue & Unit Economics",
        "label": "CAC fully loaded",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_16",
        "category": "Revenue & Unit Economics",
        "label": "CAC payback computed",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_17",
        "category": "Revenue & Unit Economics",
        "label": "LTV/CAC shown",
        "stage_gate": "seed+",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_18",
        "category": "Revenue & Unit Economics",
        "label": "Sales capacity constrains revenue",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "UNIT_19",
        "category": "Revenue & Unit Economics",
        "label": "Conversion rates grounded",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    # Expenses, Cash & Runway (13)
    {
        "id": "CASH_20",
        "category": "Expenses, Cash & Runway",
        "label": "Headcount plan drives expenses",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_21",
        "category": "Expenses, Cash & Runway",
        "label": "Benefits/tax burden included",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_22",
        "category": "Expenses, Cash & Runway",
        "label": "Working capital modeled",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_23",
        "category": "Expenses, Cash & Runway",
        "label": "Cash runway computed correctly",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_24",
        "category": "Expenses, Cash & Runway",
        "label": "Runway length adequate",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_25",
        "category": "Expenses, Cash & Runway",
        "label": "Cash-out date explicit",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_26",
        "category": "Expenses, Cash & Runway",
        "label": "Step costs captured",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_27",
        "category": "Expenses, Cash & Runway",
        "label": "OpEx scales with revenue",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_28",
        "category": "Expenses, Cash & Runway",
        "label": "FX sensitivity modeled",
        "stage_gate": "all",
        "geography_gate": ["multi-currency"],
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_29",
        "category": "Expenses, Cash & Runway",
        "label": "Entity-level cash solvent",
        "stage_gate": "all",
        "geography_gate": ["israel", "multi-entity"],
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_30",
        "category": "Expenses, Cash & Runway",
        "label": "Israel statutory costs itemized",
        "stage_gate": "all",
        "geography_gate": ["israel"],
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_31",
        "category": "Expenses, Cash & Runway",
        "label": "Government grants modeled",
        "stage_gate": "all",
        "geography_gate": ["israel"],
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    {
        "id": "CASH_32",
        "category": "Expenses, Cash & Runway",
        "label": "VAT/indirect tax cash timing",
        "stage_gate": "all",
        "geography_gate": ["israel"],
        "sector_gate": "all",
        "model_format_gate": "spreadsheet",
    },
    # Metrics & Efficiency (3)
    {
        "id": "METRIC_33",
        "category": "Metrics & Efficiency",
        "label": "KPI summary visible",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "METRIC_34",
        "category": "Metrics & Efficiency",
        "label": "Burn multiple tracked",
        "stage_gate": "seed+",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "METRIC_35",
        "category": "Metrics & Efficiency",
        "label": "Benchmark awareness",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    # Fundraising Bridge (3)
    {
        "id": "BRIDGE_36",
        "category": "Fundraising Bridge",
        "label": "Raise-runway-milestones-next round",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "BRIDGE_37",
        "category": "Fundraising Bridge",
        "label": "Next-round milestones identified",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "BRIDGE_38",
        "category": "Fundraising Bridge",
        "label": "Dilution/ownership shown",
        "stage_gate": "seed+",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    # Sector-Specific (6)
    {
        "id": "SECTOR_39",
        "category": "Sector-Specific",
        "label": "Marketplace: two-sided mechanics",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["marketplace"],
        "model_format_gate": "all",
    },
    {
        "id": "SECTOR_40",
        "category": "Sector-Specific",
        "label": "AI: inference costs modeled",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["ai-native", "usage-based", "ai-powered"],
        "model_format_gate": "all",
    },
    {
        "id": "SECTOR_41",
        "category": "Sector-Specific",
        "label": "Hardware/deep-tech: milestones + capex",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["hardware", "hardware-subscription"],
        "model_format_gate": "all",
    },
    {
        "id": "SECTOR_42",
        "category": "Sector-Specific",
        "label": "Usage-based: margin at scale",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["usage-based"],
        "model_format_gate": "all",
    },
    {
        "id": "SECTOR_43",
        "category": "Sector-Specific",
        "label": "Consumer: retention curves",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["consumer-subscription"],
        "model_format_gate": "all",
    },
    {
        "id": "SECTOR_44",
        "category": "Sector-Specific",
        "label": "Deferred revenue",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": ["annual-contracts"],
        "model_format_gate": "all",
    },
    # Overall (2)
    {
        "id": "OVERALL_45",
        "category": "Overall",
        "label": "5-minute audit possible",
        "stage_gate": "all",
        "geography_gate": "all",
        "sector_gate": "all",
        "model_format_gate": "all",
    },
    {
        "id": "OVERALL_46",
        "category": "Overall",
        "label": "Country-level metrics tracked",
        "stage_gate": "all",
        "geography_gate": ["multi-market"],
        "sector_gate": "all",
        "model_format_gate": "all",
    },
]

VALID_IDS = {item["id"] for item in CHECKLIST_ITEMS}
VALID_STATUSES = {"pass", "fail", "warn", "not_applicable"}
ITEM_LOOKUP: dict[str, dict[str, Any]] = {item["id"]: item for item in CHECKLIST_ITEMS}

# --- Profile normalization maps ---

# Note: a few of these 2-letter codes are ambiguous outside a geography context
# ("ca" -> California, "de" -> Delaware, "in" -> the English preposition "in",
# not just Canada/Germany/India). Harmless today because only "israel" is
# gated by any checklist item — but a future gate keyed on ca/de/in geography
# would need a smarter disambiguation than this flat lookup.
_GEOGRAPHY_NORMALIZATION: dict[str, str] = {
    "israel": "israel",
    "il": "israel",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "uk": "uk",
    "united kingdom": "uk",
    "eu": "eu",
    "europe": "eu",
    "india": "india",
    "in": "india",
    "germany": "germany",
    "de": "germany",
    "france": "france",
    "fr": "france",
    "canada": "canada",
    "ca": "canada",
    "singapore": "singapore",
    "sg": "singapore",
    "australia": "australia",
    "au": "australia",
}

_SEED_PLUS_STAGES = {
    "seed",
    "series-a",
    "series_a",
    "series-b",
    "series_b",
    "series-c",
    "series_c",
    "series-d",
    "series_d",
    "later",
    "growth",
}

_AI_COST_KEYS = {"inference_costs", "ai_infrastructure", "ai_compute", "gpu_costs", "model_inference"}

_REVENUE_MODEL_TO_SECTOR: dict[str, str] = {
    "saas-plg": "saas",
    "saas-sales-led": "saas",
    "marketplace": "marketplace",
    "ai-native": "ai-native",
    "usage-based": "usage-based",
    "hardware": "hardware",
    "hardware-subscription": "hardware-subscription",
    "consumer-subscription": "consumer-subscription",
    "transactional-fintech": "saas",
    "annual-contracts": "annual-contracts",
    # Like "saas", "retail" matches no sector-specific item today — the mapping
    # exists so retail companies stop mis-firing hardware gates or warnings.
    "retail": "retail",
}


def _has_ai_costs(inputs: dict[str, Any] | None) -> bool:
    """Check if expenses.cogs contains AI-related cost items."""
    if inputs is None:
        return False
    cogs = inputs.get("expenses", {}).get("cogs", {})
    if not isinstance(cogs, dict):
        return False
    return bool(_AI_COST_KEYS & cogs.keys())


def _normalize_profile(company: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Normalize free-form company profile values.

    Returns the normalized profile and the set of gate types whose field could not be resolved.
    A value that fails to normalize matches no gate value, so every criterion keyed to that
    gate is excluded — silently, and indistinguishably from a criterion that genuinely does not
    apply. The caller records which exclusions rest on an unresolved field rather than on a
    real answer about the company.
    """
    result = dict(company)
    unresolved: set[str] = set()

    raw_geo = str(company.get("geography", "")).strip().lower()
    if raw_geo:
        if raw_geo in _GEOGRAPHY_NORMALIZATION:
            result["geography"] = _GEOGRAPHY_NORMALIZATION[raw_geo]
        else:
            print(
                f"Warning: geography '{company.get('geography')}' not in normalization map; using as-is",
                file=sys.stderr,
            )
            result["geography"] = raw_geo
            unresolved.add("geography_gate")

    # Derive sector_type from revenue_model_type if not explicitly provided
    if not result.get("sector_type"):
        rmt = str(result.get("revenue_model_type", "")).strip().lower()
        derived = _REVENUE_MODEL_TO_SECTOR.get(rmt)
        if derived:
            result["sector_type"] = derived
        elif rmt:
            print(
                f"Warning: could not derive sector_type from revenue_model_type '{rmt}'",
                file=sys.stderr,
            )
            unresolved.add("sector_gate")
        else:
            print(
                "Warning: sector_type not set and revenue_model_type not provided; sector gates may not match.",
                file=sys.stderr,
            )
            unresolved.add("sector_gate")

    result["traits"] = [t.strip().lower() for t in company.get("traits", [])]
    result["stage"] = str(company.get("stage", "")).strip().lower()
    return result, unresolved


def _gate_matches(
    gate_value: Any,
    gate_type: str,
    company: dict[str, Any],
) -> bool:
    """Check whether a single gate matches the company profile.

    Returns True if the item is applicable (gate matches), False if it should be auto-gated.
    """
    if gate_value == "all":
        return True

    if gate_value == "seed+":
        return company.get("stage", "") in _SEED_PLUS_STAGES

    if isinstance(gate_value, list):
        # For geography_gate: check against geography and traits
        # For sector_gate: check against sector_type and traits
        field_val = company.get("geography", "") if gate_type == "geography_gate" else company.get("sector_type", "")
        traits = company.get("traits", [])
        return any(val == field_val or val in traits for val in gate_value)

    # Single string gate (not used in current schema but handle defensively)
    if gate_type == "geography_gate":
        return bool(gate_value == company.get("geography", ""))
    elif gate_type == "sector_gate":
        return bool(gate_value == company.get("sector_type", ""))
    return True


# Founder-facing wording for each gate. The description reaches report.md and report.html as the
# evidence line on a skipped item, so it must read as a reason and not as our field name.
_GATE_LABELS = {
    "stage_gate": "applies at a different stage",
    "geography_gate": "applies to a different geography",
    "sector_gate": "applies to a different sector",
    "model_format_gate": "needs a spreadsheet model",
}

# Founder-facing wording for a gate whose profile field never RESOLVED. Deliberately separate
# from _GATE_LABELS: those say something about the company, these say we could not tell.
#
# The field named here is the one the founder can act on, not the one that failed to normalize.
# For the sector gate those differ -- the unresolved input is `revenue_model_type`, which is an
# internal token the founder-text policy flags, and HTML is NOT run through `substitute()`
# (test_html_founder_text.py), so naming it accurately would leak it into report.html and red the
# fleet ratchet. "your revenue model" is the same fact in founder language.
_UNRESOLVED_GATE_FIELDS = {
    "geography_gate": "geography",
    "sector_gate": "revenue model",
}


def _unresolved_gate_reason(gate_type: str, company: dict[str, Any] | None) -> str:
    """Explain that a gate could not be evaluated, quoting what the founder actually supplied."""
    field = _UNRESOLVED_GATE_FIELDS.get(gate_type, gate_type.removesuffix("_gate"))
    raw = ""
    if company is not None:
        source_key = "revenue_model_type" if gate_type == "sector_gate" else field
        raw = str(company.get(source_key, "") or "").strip()
    seen = f" ('{raw}')" if raw else ""
    return f"we could not match your {field}{seen}, so we could not tell whether this applies to you"


def _gate_depends_on_unresolved(meta: dict[str, Any], gate_type: str) -> bool:
    """Could resolving this profile field have changed whether the item applies?

    Geography and sector gates are arrays matched against the profile field OR the company's
    traits. A gate keyed to a TRAIT ("multi-currency", "multi-market") was answered by the
    traits list, which resolved fine — so its exclusion is a real answer and must not be blamed
    on the unresolved field. Only a gate naming a value from the field's own vocabulary could
    have gone the other way. Without this the report accuses the profile of dropping criteria
    it did not drop, which is the same class of false statement this is meant to prevent.
    """
    values = meta.get(gate_type, "all")
    if not isinstance(values, list):
        return False
    if gate_type == "geography_gate":
        return any(str(v).strip().lower() in _GEOGRAPHY_NORMALIZATION.values() for v in values)
    if gate_type == "sector_gate":
        return any(str(v).strip().lower() in _REVENUE_MODEL_TO_SECTOR.values() for v in values)
    return False


def _item_applicable(meta: dict[str, Any], company: dict[str, Any]) -> tuple[bool, str, str]:
    """Check all four gates for an item.

    Returns (applicable, gate_description, gate_type). The gate TYPE is returned alongside the
    founder-facing description because the caller must tell an exclusion that rests on a real
    answer about the company from one that rests on a profile field it could not resolve.
    """
    for gate_type in ("stage_gate", "geography_gate", "sector_gate"):
        gate_value = meta.get(gate_type, "all")
        if not _gate_matches(gate_value, gate_type, company):
            return False, _GATE_LABELS[gate_type], gate_type
    # Model format gate: items gated to "spreadsheet" are N/A for deck/conversational.
    # "partial" = incomplete spreadsheet — structure is still assessable, so it evaluates
    # all 46 items just like "spreadsheet". Only deck/conversational remain fully gated.
    model_format = company.get("model_format", "spreadsheet")
    mf_gate = meta.get("model_format_gate", "all")
    if mf_gate == "spreadsheet" and model_format in ("deck", "conversational"):
        return False, _GATE_LABELS["model_format_gate"], "model_format_gate"
    return True, "", ""


# Criteria whose own label carries an applicability qualifier ("where applicable", "where
# material", "if applicable", "where mature enough"). For these, not_applicable is a judgement
# about the company, which the assessor is entitled to make. Everywhere else, applicability is
# decided after the assessment, from the company profile — never during it.
_JUDGEMENT_NOT_APPLICABLE: frozenset[str] = frozenset({"UNIT_13", "UNIT_17", "CASH_22", "SECTOR_44"})


_STRUCTURAL_CATEGORIES = {"Structure & Presentation", "Expenses, Cash & Runway"}

# Per-criterion severity classification (v0.4.2 Phase 1 Task 2).
# Used by Phase 3's coaching_payload to enable severity-sorted truncation
# (top 15 high + top 15 medium when failed_items + warned_items > 30).
#
# Mapping rules:
#   - high:   cash/runway/burn (core viability) and fundraising bridge.
#   - medium: revenue/unit-economics, headline metrics, sector-specific,
#             overall. Default for any future/unknown category.
#   - low:    structural/formatting issues — cosmetic, not viability-critical.
_CATEGORY_SEVERITY: dict[str, str] = {
    "Structure & Presentation": "low",
    "Revenue & Unit Economics": "medium",
    "Expenses, Cash & Runway": "high",
    "Metrics & Efficiency": "medium",
    "Fundraising Bridge": "high",
    "Sector-Specific": "medium",
    "Overall": "medium",
}


def _severity_for_category(category: str) -> str:
    """Return severity (high|medium|low) for a checklist category. Defaults to medium."""
    return _CATEGORY_SEVERITY.get(category, "medium")


def validate_checklist(
    items: list[dict[str, Any]],
    company: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate checklist input and produce scored summary. Returns (result, errors)."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"Item {i} must be an object (got {type(item).__name__})")
            continue
        item_id = item.get("id", "")
        if item_id not in VALID_IDS:
            errors.append(f"Unknown checklist ID '{item_id}'")
            continue
        if item_id in seen_ids:
            errors.append(f"Duplicate checklist ID '{item_id}'")
            continue
        seen_ids.add(item_id)

        status = item.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"Invalid status '{status}' for item '{item_id}'. Must be one of: {sorted(VALID_STATUSES)}")

    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing checklist items: {sorted(missing)}")

    if errors:
        return {"items": [], "summary": None}, errors

    # Normalize company profile if provided
    norm_company, unresolved_gates = _normalize_profile(company) if company else (None, set())

    # Build enriched items and summary
    enriched: list[dict[str, Any]] = []
    self_gated: list[str] = []
    unresolved_exclusions: dict[str, list[str]] = {}
    pass_count = 0
    fail_count = 0
    warn_count = 0
    na_count = 0
    failed_items: list[dict[str, Any]] = []
    warned_items: list[dict[str, Any]] = []

    # Per-category tracking
    categories: dict[str, dict[str, int]] = {}

    for item in items:
        item_id = item["id"]
        meta = ITEM_LOOKUP[item_id]
        status = item["status"]
        evidence = item.get("evidence")
        notes = item.get("notes")
        category = meta["category"]

        # Auto-gate based on company profile
        original_status = status
        original_evidence = evidence
        if norm_company is not None:
            is_applicable, gate_desc, gate_type = _item_applicable(meta, norm_company)
            if not is_applicable:
                status = "not_applicable"
                if gate_type in unresolved_gates and _gate_depends_on_unresolved(meta, gate_type):
                    # Excluded by a gate whose profile field never resolved, so this is not an
                    # answer about the company — it is the absence of one. Stamping the SAME
                    # evidence as a genuine exclusion made the artifact assert a fact it did not
                    # have: an Israeli company whose geography read "Israel/US" was told
                    # "applies to a different geography" on every Israel-keyed criterion, while
                    # report.md said the field could not be matched. The distinction has to live
                    # in the artifact, because every renderer reads the evidence string from it.
                    field = gate_type.removesuffix("_gate")
                    unresolved_exclusions.setdefault(field, []).append(item_id)
                    # `company`, not `norm_company`: quote the founder's own string back to them.
                    # Normalization lowercases, and "israel/us" reads like a typo of what they wrote.
                    evidence = f"Not assessed — {_unresolved_gate_reason(gate_type, company)}"
                else:
                    evidence = f"Not applicable — {gate_desc}"
            elif status == "not_applicable" and item_id not in _JUDGEMENT_NOT_APPLICABLE:
                # The profile says this criterion applies, yet it came back excluded. That
                # removes it from the score's denominator on a decision this script owns.
                # Recorded, not overridden: a self-excluded item carries no assessment to
                # fall back on, and inventing one would be worse than reporting the gap.
                self_gated.append(item_id)

        # Special-case: SECTOR_40 (AI inference costs) should apply when
        # expenses.cogs contains AI-related cost keys, even if the sector
        # gate doesn't match (e.g. saas company with heavy inference costs).
        if item_id == "SECTOR_40" and status == "not_applicable" and _has_ai_costs(inputs):
            status = original_status
            evidence = original_evidence

        enriched.append(
            {
                "id": item_id,
                "category": category,
                "label": meta["label"],
                "status": status,
                "evidence": evidence,
                "notes": notes,
            }
        )

        # Initialize category counters
        if category not in categories:
            categories[category] = {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 0}

        if status == "pass":
            pass_count += 1
            categories[category]["pass"] += 1
        elif status == "fail":
            fail_count += 1
            categories[category]["fail"] += 1
            failed_items.append(
                {
                    "id": item_id,
                    "category": category,
                    "label": meta["label"],
                    "evidence": evidence,
                    "notes": notes,
                    "severity": _severity_for_category(category),
                }
            )
        elif status == "warn":
            warn_count += 1
            categories[category]["warn"] += 1
            warned_items.append(
                {
                    "id": item_id,
                    "category": category,
                    "label": meta["label"],
                    "evidence": evidence,
                    "notes": notes,
                    "severity": _severity_for_category(category),
                }
            )
        elif status == "not_applicable":
            na_count += 1
            categories[category]["not_applicable"] += 1

    # Advisory warning: fail/warn without evidence
    for item in enriched:
        if item["status"] in ("fail", "warn"):
            ev = item.get("evidence")
            if not ev or (isinstance(ev, str) and not ev.strip()):
                print(
                    f"Warning: {item['id']} has status '{item['status']}' but no evidence",
                    file=sys.stderr,
                )

    # Score: (pass * 1.0 + warn * 0.5) / applicable * 100
    # Pass gets full credit, warn gets partial credit, fail gets zero.
    applicable = len(CHECKLIST_ITEMS) - na_count
    if applicable > 0:
        points = pass_count * 1.0 + warn_count * 0.5
        score_pct = round((points / applicable) * 100, 1)
    else:
        score_pct = 0.0

    # Sub-scores: business quality vs model maturity
    struct_pass = 0
    struct_warn = 0
    struct_applicable = 0
    biz_pass = 0
    biz_warn = 0
    biz_applicable = 0
    for item in enriched:
        if item["status"] == "not_applicable":
            continue
        if item["category"] in _STRUCTURAL_CATEGORIES:
            struct_applicable += 1
            if item["status"] == "pass":
                struct_pass += 1
            elif item["status"] == "warn":
                struct_warn += 1
        else:
            biz_applicable += 1
            if item["status"] == "pass":
                biz_pass += 1
            elif item["status"] == "warn":
                biz_warn += 1

    if biz_applicable > 0:
        business_quality_pct: float | None = round((biz_pass + 0.5 * biz_warn) / biz_applicable * 100, 1)
    else:
        business_quality_pct = None

    if struct_applicable > 0:
        model_maturity_pct: float | None = round((struct_pass + 0.5 * struct_warn) / struct_applicable * 100, 1)
    else:
        model_maturity_pct = None

    # Overall status thresholds
    if score_pct >= 85:
        overall_status = "strong"
    elif score_pct >= 70:
        overall_status = "solid"
    elif score_pct >= 50:
        overall_status = "needs_work"
    else:
        overall_status = "major_revision"

    return {
        "items": enriched,
        "summary": {
            "total": len(CHECKLIST_ITEMS),
            "pass": pass_count,
            "fail": fail_count,
            "warn": warn_count,
            "not_applicable": na_count,
            "score_pct": score_pct,
            "business_quality_pct": business_quality_pct,
            "model_maturity_pct": model_maturity_pct,
            "overall_status": overall_status,
            "by_category": categories,
            "failed_items": failed_items,
            "warned_items": warned_items,
            "self_gated_items": self_gated,
            "unresolved_profile_exclusions": unresolved_exclusions,
        },
    }, []


def _resolve_company(
    payload_company: dict[str, Any] | None,
    inputs_doc: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Pick the authoritative company profile and report where the two sources disagree.

    Which criteria count toward the score is an applicability decision, so the profile that
    drives it must not be one a model re-typed by hand. The payload's copy is re-typed;
    inputs.json is producer-written. Where both exist the file wins, and each divergent field
    is reported — a profile that drifted is a signal about the hand-off, not something to
    silently absorb.
    """
    file_company = (inputs_doc or {}).get("company")
    if not isinstance(file_company, dict):
        return payload_company, []
    warnings: list[str] = []
    if isinstance(payload_company, dict):
        for key in sorted(set(file_company) | set(payload_company)):
            if file_company.get(key) != payload_company.get(key):
                warnings.append(
                    f"company.{key} differs between the review inputs and the returned "
                    f"assessment; using the inputs value"
                )
    return file_company, warnings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Financial model review checklist scorer (reads JSON from stdin)")
    p.add_argument(
        "--inputs",
        help=(
            "Path to inputs.json, used only to fingerprint what this scoring was computed from. The "
            "sub-agent's payload carries `company` but not the full inputs, so without this the "
            "fingerprint is null and staleness cannot be detected for this artifact."
        ),
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
            "Example: echo '{\"items\": [...]}' | python checklist.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None

    # --- Validation (JSON error dict, exit 0) ---
    errors: list[str] = []
    if "items" not in data:
        errors.append("Missing required key: 'items'")
    elif not isinstance(data["items"], list):
        errors.append("'items' must be an array")

    if errors:
        result: dict[str, Any] = {"validation": {"status": "invalid", "errors": errors}, "items": [], "summary": None}
        _fail_invalid(result, args.output, indent)

    # Read --inputs BEFORE grading, not just for the fingerprint below: it carries the company
    # profile that decides which criteria apply, and that decision must not rest on a copy a
    # model re-typed. Unreadable is not fatal here — the payload copy still gates, and the
    # fingerprint step below reports the read failure.
    _inputs_file_doc: dict[str, Any] | None = None
    if getattr(args, "inputs", None):
        try:
            with open(args.inputs, encoding="utf-8") as _f:
                _loaded = json.load(_f)
            if isinstance(_loaded, dict):
                _inputs_file_doc = _loaded
        except (OSError, json.JSONDecodeError):
            _inputs_file_doc = None

    company, _company_warnings = _resolve_company(data.get("company"), _inputs_file_doc)
    for _w in _company_warnings:
        print(f"Warning: {_w}", file=sys.stderr)

    inputs_data = data.get("inputs")
    # Hash the payload's inputs BEFORE validate_checklist sees them: it may consume or annotate the
    # object, and the verifier hashes the file on disk. This is the same ordering trap that made
    # unit_economics stamp a document that never existed on disk. Only used when --inputs is absent.
    _fp_payload = _fingerprint.fingerprint(inputs_data) if inputs_data is not None else None
    result, errors = validate_checklist(data["items"], company, inputs=inputs_data)

    _rejected = bool(errors)
    result["validation"] = {"status": "invalid", "errors": errors} if _rejected else {"status": "valid", "errors": []}

    _self_gated = (result.get("summary") or {}).get("self_gated_items") or []
    if _self_gated:
        print(
            "Warning: these criteria came back not applicable, but the company profile says they "
            f"apply: {', '.join(_self_gated)}. They are excluded from the score, so the score is "
            "computed over a smaller set of criteria than it should be.",
            file=sys.stderr,
        )

    # Provenance is stamped BEFORE the refusal below, deliberately: a rejected run writes no
    # artifact, but its diagnostic still goes to stdout, and a diagnostic that names the inputs it
    # was graded against is more actionable than a bare list of errors.
    # Propagate run_id from input metadata into output for stale-artifact detection
    _input_metadata = data.get("metadata") or (data.get("inputs") or {}).get("metadata")
    if isinstance(_input_metadata, dict) and isinstance(_input_metadata.get("run_id"), str):
        result.setdefault("metadata", {})["run_id"] = _input_metadata["run_id"]
    if getattr(args, "run_id", None):  # CLI run_id overrides stdin passthrough
        result.setdefault("metadata", {})["run_id"] = args.run_id
    # Prefer --inputs (the file the main thread pipes from) over the payload's partial `inputs`, since
    # the payload carries `company` but not the whole document. Absent both, None records "cannot
    # compare" rather than a false match.
    # Prefer --inputs (the file the verifier will hash) over the payload's partial `inputs`; fall back
    # to the pre-validation hash captured above. Absent both, None records "cannot compare".
    _fp_digest = _fp_payload
    if getattr(args, "inputs", None):
        try:
            with open(args.inputs, encoding="utf-8") as _f:
                _fp_digest = _fingerprint.fingerprint(json.load(_f))
        except (OSError, json.JSONDecodeError) as _e:
            print(f"Warning: --inputs unreadable, fingerprint will be null: {_e}", file=sys.stderr)
            _fp_digest = None
    _fingerprint.stamp_hashes(result, {"inputs.json": _fp_digest})

    if _rejected:
        _fail_invalid(result, args.output, indent)

    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    summary = {"score_pct": s["score_pct"], "pass": s["pass"], "fail": s["fail"]} if s else {}
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
