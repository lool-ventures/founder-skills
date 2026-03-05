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
}

_SEED_PLUS_STAGES = {"seed", "series-a", "series_a", "series-b", "series_b", "later", "growth"}

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
}


def _has_ai_costs(inputs: dict[str, Any] | None) -> bool:
    """Check if expenses.cogs contains AI-related cost items."""
    if inputs is None:
        return False
    cogs = inputs.get("expenses", {}).get("cogs", {})
    if not isinstance(cogs, dict):
        return False
    return bool(_AI_COST_KEYS & cogs.keys())


def _normalize_profile(company: dict[str, Any]) -> dict[str, Any]:
    """Normalize free-form company profile values. Unknown values pass through with a warning."""
    result = dict(company)

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
        else:
            print(
                "Warning: sector_type not set and revenue_model_type not provided; sector gates may not match.",
                file=sys.stderr,
            )

    result["traits"] = [t.strip().lower() for t in company.get("traits", [])]
    result["stage"] = str(company.get("stage", "")).strip().lower()
    return result


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


def _item_applicable(meta: dict[str, Any], company: dict[str, Any]) -> tuple[bool, str]:
    """Check all four gates for an item. Returns (applicable, gate_description)."""
    for gate_type in ("stage_gate", "geography_gate", "sector_gate"):
        gate_value = meta.get(gate_type, "all")
        if not _gate_matches(gate_value, gate_type, company):
            return False, f"{gate_type} '{gate_value}'"
    # Model format gate: items gated to "spreadsheet" are N/A for deck/conversational
    model_format = company.get("model_format", "spreadsheet")
    mf_gate = meta.get("model_format_gate", "all")
    if mf_gate == "spreadsheet" and model_format in ("deck", "conversational"):
        return False, f"model_format_gate '{mf_gate}' does not match format '{model_format}'"
    return True, ""


_STRUCTURAL_CATEGORIES = {"Structure & Presentation", "Expenses, Cash & Runway"}


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
    norm_company = _normalize_profile(company) if company else None

    # Build enriched items and summary
    enriched: list[dict[str, Any]] = []
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
            is_applicable, gate_desc = _item_applicable(meta, norm_company)
            if not is_applicable:
                status = "not_applicable"
                evidence = f"Auto-gated: {gate_desc} does not match company profile"

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
        business_quality_pct = 0.0

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
        },
    }, []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Financial model review checklist scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
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
        _write_output(json.dumps(result, indent=indent) + "\n", args.output)
        return

    company = data.get("company")
    inputs_data = data.get("inputs")
    result, errors = validate_checklist(data["items"], company, inputs=inputs_data)

    if errors:
        result["validation"] = {"status": "invalid", "errors": errors}
    else:
        result["validation"] = {"status": "valid", "errors": []}

    # Propagate run_id from input metadata into output for stale-artifact detection
    _input_metadata = data.get("metadata") or (data.get("inputs") or {}).get("metadata")
    if isinstance(_input_metadata, dict) and isinstance(_input_metadata.get("run_id"), str):
        result.setdefault("metadata", {})["run_id"] = _input_metadata["run_id"]

    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    summary = {"score_pct": s["score_pct"], "pass": s["pass"], "fail": s["fail"]} if s else {}
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
