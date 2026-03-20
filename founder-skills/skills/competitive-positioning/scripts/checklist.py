#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Competitive positioning checklist scorer.

Validates 25 criteria across 6 categories with pass/fail/warn/not_applicable
scoring and mode-based gating. Computes overall score percentage.

Always reads JSON from stdin.

Usage:
    echo '{"items": [...], "input_mode": "conversation", "metadata": {"run_id": "..."}}' \
        | python checklist.py --pretty

Output: JSON with validated items, score, and summary counts.
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
# Canonical 25 checklist items grouped by category.
# Must match checklist-criteria.md exactly.
# ---------------------------------------------------------------------------

CHECKLIST_ITEMS: list[dict[str, str]] = [
    # Competitor Coverage (5)
    {"id": "COVER_01", "category": "COVER", "label": "Minimum 5 competitors identified"},
    {"id": "COVER_02", "category": "COVER", "label": "Category diversity (direct + adjacent/do-nothing)"},
    {"id": "COVER_03", "category": "COVER", "label": "Emerging entrants considered"},
    {"id": "COVER_04", "category": "COVER", "label": "Do-nothing / status quo included"},
    {"id": "COVER_05", "category": "COVER", "label": "No obvious incumbents missing"},
    # Positioning Quality (5)
    {"id": "POS_01", "category": "POS", "label": "Primary axis pair is meaningful"},
    {"id": "POS_02", "category": "POS", "label": "Axes are non-vanity"},
    {"id": "POS_03", "category": "POS", "label": "Coordinates are evidence-backed"},
    {"id": "POS_04", "category": "POS", "label": "Startup is differentiated on at least one axis"},
    {"id": "POS_05", "category": "POS", "label": "Axis rationale explains differentiation value"},
    # Moat Assessment (4)
    {"id": "MOAT_01", "category": "MOAT", "label": "All 6 canonical moat types evaluated"},
    {"id": "MOAT_02", "category": "MOAT", "label": "Moat evidence meets quality floor"},
    {"id": "MOAT_03", "category": "MOAT", "label": "Trajectory included for each moat"},
    {"id": "MOAT_04", "category": "MOAT", "label": "Custom moats justified (if present)"},
    # Evidence Quality (4)
    {"id": "EVID_01", "category": "EVID", "label": "Per-competitor research depth recorded"},
    {"id": "EVID_02", "category": "EVID", "label": "Majority of competitors have sourced evidence"},
    {"id": "EVID_03", "category": "EVID", "label": "Evidence sources distinguished (researched vs. estimated)"},
    {"id": "EVID_04", "category": "EVID", "label": "Competitor financials/pricing sourced"},
    # Narrative Readiness (4)
    {"id": "NARR_01", "category": "NARR", "label": "Differentiation claims stress-tested"},
    {"id": "NARR_02", "category": "NARR", "label": "Investor-ready competitive framing"},
    {"id": "NARR_03", "category": "NARR", "label": "Competition slide alignment (deck cross-check)"},
    {"id": "NARR_04", "category": "NARR", "label": "Defensibility roadmap articulated"},
    # Common Mistakes (3)
    {"id": "MISS_01", "category": "MISS", "label": 'No "we have no competitors" claim'},
    {"id": "MISS_02", "category": "MISS", "label": "No vanity axes selected"},
    {"id": "MISS_03", "category": "MISS", "label": "No feature-checkbox thinking"},
]

VALID_IDS = {item["id"] for item in CHECKLIST_ITEMS}
VALID_STATUSES = {"pass", "fail", "warn", "not_applicable"}
ITEM_LOOKUP = {item["id"]: item for item in CHECKLIST_ITEMS}

# ---------------------------------------------------------------------------
# Mode-based gating table.
# Maps input_mode -> set of item IDs that are auto-gated to not_applicable.
# ---------------------------------------------------------------------------

MODE_GATING: dict[str, set[str]] = {
    "deck": {"EVID_04"},
    "conversation": {"NARR_03", "EVID_04"},
    "document": {"NARR_03"},
}

GATE_MESSAGE = "Auto-gated: not applicable in {mode} mode"


def _die(msg: str) -> None:
    """Print error to stderr and exit 1."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def validate_and_score(
    items: list[dict[str, Any]],
    input_mode: str,
    data_confidence: str,
) -> dict[str, Any]:
    """Validate checklist items, apply mode gating, compute score.

    Returns the full output dict. Calls sys.exit(1) on validation errors.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    # --- Structural validation ---
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

        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"Item '{item_id}' requires a non-empty evidence string")

    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing checklist items: {sorted(missing)}")

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # --- Mode gating ---
    gated_ids = MODE_GATING.get(input_mode, set())

    # Build item index for gating overrides
    items_by_id: dict[str, dict[str, Any]] = {item["id"]: item for item in items}

    # --- Enrich and score ---
    enriched: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    warn_count = 0
    na_count = 0

    for item_def in CHECKLIST_ITEMS:
        item_id = item_def["id"]
        src = items_by_id[item_id]
        status = src["status"]
        evidence = src["evidence"]
        notes = src.get("notes")

        # Apply mode gating — override regardless of agent-provided status
        if item_id in gated_ids:
            status = "not_applicable"
            evidence = GATE_MESSAGE.format(mode=input_mode)

        # Apply data confidence qualifier to non-gated items
        if data_confidence == "estimated" and status != "not_applicable":
            evidence = f"{evidence} (based on estimated inputs)"

        entry: dict[str, Any] = {
            "id": item_id,
            "category": item_def["category"],
            "label": item_def["label"],
            "status": status,
            "evidence": evidence,
        }
        if notes is not None:
            entry["notes"] = notes
        enriched.append(entry)

        if status == "pass":
            pass_count += 1
        elif status == "fail":
            fail_count += 1
        elif status == "warn":
            warn_count += 1
        elif status == "not_applicable":
            na_count += 1

    # Score: (pass_count + 0.5 * warn_count) / (total - not_applicable) * 100
    total = len(CHECKLIST_ITEMS)
    applicable = total - na_count
    score_pct = round(((pass_count + 0.5 * warn_count) / applicable) * 100, 1) if applicable > 0 else 0.0

    return {
        "items": enriched,
        "score_pct": score_pct,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "na_count": na_count,
        "total": total,
        "input_mode": input_mode,
        "metadata": {},  # placeholder, filled by caller
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Competitive positioning checklist scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            'Example: echo \'{"items": [...], "input_mode": "conversation"}\' | python checklist.py --pretty',
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        _die(f"invalid JSON input: {e}")

    if not isinstance(data, dict):
        _die("JSON must be an object")

    # --- Required fields ---
    if "items" not in data:
        _die("Missing required key: 'items'")
    if not isinstance(data["items"], list):
        _die("'items' must be an array")

    input_mode = data.get("input_mode", "conversation")
    if input_mode not in ("deck", "conversation", "document"):
        _die(f"Invalid input_mode '{input_mode}'. Must be 'deck', 'conversation', or 'document'")

    data_confidence = data.get("data_confidence", "exact")
    metadata = data.get("metadata", {})

    result = validate_and_score(data["items"], input_mode, data_confidence)
    result["metadata"] = metadata

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    summary = {
        "score_pct": result["score_pct"],
        "pass_count": result["pass_count"],
        "fail_count": result["fail_count"],
    }
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
