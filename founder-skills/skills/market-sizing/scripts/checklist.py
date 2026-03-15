#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Self-check validator for market sizing analysis.

Validates a 22-item checklist (from pitfalls-checklist.md) with pass/fail
per item. Ensures all items are present, reports summary with failed items.

Always reads JSON from stdin.

Usage:
    echo '{"items": [{"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null}, ...]}' \
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


# Canonical 22 checklist items — IDs match pitfalls-checklist.md
CHECKLIST_ITEMS: list[dict[str, str]] = [
    # Structural Checks
    {"id": "structural_tam_gt_sam_gt_som", "category": "Structural Checks", "label": "TAM > SAM > SOM"},
    {"id": "structural_definitions_correct", "category": "Structural Checks", "label": "Definitions used correctly"},
    # TAM Scoping
    {"id": "tam_matches_product_scope", "category": "TAM Scoping", "label": "TAM matches product scope"},
    {"id": "source_segments_match", "category": "TAM Scoping", "label": "Source segments match product segments"},
    # SOM Realism
    {"id": "som_share_defensible", "category": "SOM Realism", "label": "SOM share is defensible"},
    {"id": "som_backed_by_gtm", "category": "SOM Realism", "label": "SOM backed by go-to-market plan"},
    {
        "id": "som_consistent_with_projections",
        "category": "SOM Realism",
        "label": "SOM consistent with financial projections",
    },
    # Data Quality
    {"id": "data_current", "category": "Data Quality", "label": "Data is current"},
    {"id": "sources_reputable", "category": "Data Quality", "label": "Sources are reputable"},
    {"id": "figures_triangulated", "category": "Data Quality", "label": "Key figures triangulated"},
    {"id": "unsupported_figures_flagged", "category": "Data Quality", "label": "Unsupported figures flagged"},
    {"id": "validated_used_precisely", "category": "Data Quality", "label": "Validated used precisely"},
    {"id": "assumptions_categorized", "category": "Data Quality", "label": "Assumptions categorized"},
    # Methodology
    {"id": "both_approaches_used", "category": "Methodology", "label": "Both approaches used"},
    {"id": "approaches_reconciled", "category": "Methodology", "label": "Top-down and bottom-up reconciled"},
    {"id": "growth_dynamics_considered", "category": "Methodology", "label": "Market growth dynamics considered"},
    # Market Understanding
    {"id": "market_properly_segmented", "category": "Market Understanding", "label": "Market properly segmented"},
    {
        "id": "competitive_landscape_acknowledged",
        "category": "Market Understanding",
        "label": "Competitive landscape acknowledged",
    },
    {"id": "sam_expansion_path_noted", "category": "Market Understanding", "label": "SAM expansion path noted"},
    # Presentation
    {"id": "assumptions_explicit", "category": "Presentation", "label": "Assumptions explicit"},
    {"id": "formulas_shown", "category": "Presentation", "label": "Formulas shown"},
    {"id": "sources_cited", "category": "Presentation", "label": "Sources cited"},
]

VALID_IDS = {item["id"] for item in CHECKLIST_ITEMS}
VALID_STATUSES = {"pass", "fail", "not_applicable"}
ITEM_LOOKUP = {item["id"]: item for item in CHECKLIST_ITEMS}


def validate_checklist(items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Validate checklist input and produce summary. Returns (result, errors)."""
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

    # Check all 22 IDs present
    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing checklist items: {sorted(missing)}")

    if errors:
        return {"items": [], "summary": None}, errors

    # Build enriched items and summary
    enriched: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    na_count = 0
    failed_items: list[dict[str, Any]] = []

    for item in items:
        item_id = item["id"]
        meta = ITEM_LOOKUP[item_id]
        status = item["status"]
        raw_notes = item.get("notes")
        notes = str(raw_notes) if raw_notes is not None else None

        enriched.append(
            {
                "id": item_id,
                "category": meta["category"],
                "label": meta["label"],
                "status": status,
                "notes": notes,
            }
        )

        if status == "pass":
            pass_count += 1
        elif status == "fail":
            fail_count += 1
            failed_items.append(
                {
                    "id": item_id,
                    "category": meta["category"],
                    "label": meta["label"],
                    "notes": notes,
                }
            )
        elif status == "not_applicable":
            na_count += 1

    # Sort by canonical order
    canonical_order = {item["id"]: i for i, item in enumerate(CHECKLIST_ITEMS)}
    enriched.sort(key=lambda x: canonical_order.get(x["id"], 999))

    overall = "pass" if fail_count == 0 else "fail"

    applicable = len(CHECKLIST_ITEMS) - na_count
    score_pct = round((pass_count / applicable) * 100, 1) if applicable > 0 else 0.0

    return {
        "items": enriched,
        "summary": {
            "total": len(CHECKLIST_ITEMS),
            "pass": pass_count,
            "fail": fail_count,
            "not_applicable": na_count,
            "score_pct": score_pct,
            "overall_status": overall,
            "failed_items": failed_items,
        },
    }, []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market sizing self-check validator (reads JSON from stdin)")
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

    result, errors = validate_checklist(data["items"])

    if errors:
        result["validation"] = {"status": "invalid", "errors": errors}
    else:
        result["validation"] = {"status": "valid", "errors": []}

    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    summary = {"score_pct": s["score_pct"], "pass": s["pass"], "fail": s["fail"]} if s else {}
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
