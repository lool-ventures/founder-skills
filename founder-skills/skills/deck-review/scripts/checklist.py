#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Deck review checklist scorer.

Validates 35 criteria across 7 categories with pass/fail/warn/not_applicable
scoring. Computes overall score percentage and status.

Always reads JSON from stdin.

Usage:
    echo '{"items": [{"id": "purpose_clear", "status": "pass", "evidence": "...", "notes": "..."}, ...]}' \
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


# Canonical 35 checklist items grouped by category.
# Why 35: covers narrative, content, stage-fit, design, common mistakes,
# AI-specific, and diligence readiness — the full best-practices surface area.
CHECKLIST_ITEMS: list[dict[str, str]] = [
    # Narrative Flow (5)
    {"id": "purpose_clear", "category": "Narrative Flow", "label": "Company purpose is clear and specific"},
    {
        "id": "headlines_carry_story",
        "category": "Narrative Flow",
        "label": "Slide headlines are conclusions, not topics",
    },
    {
        "id": "narrative_arc_present",
        "category": "Narrative Flow",
        "label": "Narrative follows Problem-Solution-Proof-Ask arc",
    },
    {"id": "strongest_proof_early", "category": "Narrative Flow", "label": "Strongest proof appears by slide 4"},
    {"id": "story_stands_alone", "category": "Narrative Flow", "label": "Deck tells story without narration"},
    # Slide Content (8)
    {"id": "problem_quantified", "category": "Slide Content", "label": "Problem slide quantifies pain"},
    {
        "id": "solution_shows_workflow",
        "category": "Slide Content",
        "label": "Solution shows before→after, not feature list",
    },
    {"id": "why_now_has_catalyst", "category": "Slide Content", "label": "Why-now has genuine macro catalyst"},
    {"id": "market_bottom_up", "category": "Slide Content", "label": "Market sizing uses bottom-up approach"},
    {"id": "competition_honest", "category": "Slide Content", "label": "Competition section is honest and substantive"},
    {
        "id": "business_model_clear",
        "category": "Slide Content",
        "label": "Business model explains money flow and margins",
    },
    {"id": "gtm_has_proof", "category": "Slide Content", "label": "GTM slide has ICP, channel, and early proof"},
    {"id": "team_has_depth", "category": "Slide Content", "label": "Team slide demonstrates founder-market fit"},
    # Stage Fit (5)
    {
        "id": "stage_appropriate_structure",
        "category": "Stage Fit",
        "label": "Slide order matches stage-specific framework",
    },
    {"id": "stage_appropriate_traction", "category": "Stage Fit", "label": "Traction metrics match stage expectations"},
    {"id": "stage_appropriate_financials", "category": "Stage Fit", "label": "Financial projections match stage depth"},
    {"id": "ask_ties_to_milestones", "category": "Stage Fit", "label": "Ask ties dollars to milestones to next round"},
    {
        "id": "round_size_realistic",
        "category": "Stage Fit",
        "label": "Fundraising amount aligns with current benchmarks",
    },
    # Design & Readability (5)
    {"id": "one_idea_per_slide", "category": "Design & Readability", "label": "One idea per slide"},
    {"id": "minimal_text", "category": "Design & Readability", "label": "Big type, minimal paragraphs"},
    {"id": "slide_count_appropriate", "category": "Design & Readability", "label": "Core deck is 10-12 slides"},
    {"id": "consistent_design", "category": "Design & Readability", "label": "Consistent visual design language"},
    {"id": "mobile_readable", "category": "Design & Readability", "label": "Readable on mobile without zoom"},
    # Common Mistakes (5)
    {"id": "no_vague_purpose", "category": "Common Mistakes", "label": "No vague or buzzwordy purpose statement"},
    {
        "id": "no_nice_to_have_problem",
        "category": "Common Mistakes",
        "label": "Problem shows urgency, not a nice-to-have",
    },
    {"id": "no_hype_without_proof", "category": "Common Mistakes", "label": "No hype without supporting evidence"},
    {"id": "no_features_over_outcomes", "category": "Common Mistakes", "label": "Focuses on outcomes, not features"},
    {
        "id": "no_dodged_competition",
        "category": "Common Mistakes",
        "label": "Competition slide exists and is substantive",
    },
    # AI Company (4) — mark not_applicable for non-AI companies
    {"id": "ai_retention_rebased", "category": "AI Company", "label": "AI retention measured from Month 3"},
    {
        "id": "ai_cost_to_serve_shown",
        "category": "AI Company",
        "label": "Compute economics and margin trajectory shown",
    },
    {
        "id": "ai_defensibility_beyond_model",
        "category": "AI Company",
        "label": "Defensibility beyond 'we use [foundation model]'",
    },
    {"id": "ai_responsible_controls", "category": "AI Company", "label": "Responsible AI / risk controls addressed"},
    # Diligence Readiness (3)
    {
        "id": "numbers_consistent",
        "category": "Diligence Readiness",
        "label": "Claims in deck are internally consistent",
    },
    {
        "id": "data_room_ready",
        "category": "Diligence Readiness",
        "label": "Diligence materials referenced or available",
    },
    {
        "id": "contact_info_present",
        "category": "Diligence Readiness",
        "label": "Contact information visible and correct",
    },
]

VALID_IDS = {item["id"] for item in CHECKLIST_ITEMS}
VALID_STATUSES = {"pass", "fail", "warn", "not_applicable"}
ITEM_LOOKUP = {item["id"]: item for item in CHECKLIST_ITEMS}


def validate_checklist(items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
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
            evidence = item.get("evidence")
            if not evidence or (isinstance(evidence, str) and not evidence.strip()):
                print(
                    f"Warning: {item['id']} has status '{item['status']}' but no evidence",
                    file=sys.stderr,
                )

    # Score: pass / (total - not_applicable) * 100
    # Why no weighting: keeps scoring simple and defensible — each applicable
    # criterion counts equally, avoiding subjective weight arguments.
    applicable = len(CHECKLIST_ITEMS) - na_count
    score_pct = round((pass_count / applicable) * 100, 1) if applicable > 0 else 0.0

    # Overall status thresholds — chosen to give actionable signal:
    # "strong" means investor-ready, "major_revision" means fundamental rework needed.
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
            "overall_status": overall_status,
            "by_category": categories,
            "failed_items": failed_items,
            "warned_items": warned_items,
        },
    }, []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deck review checklist scorer (reads JSON from stdin)")
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
