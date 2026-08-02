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

# The 4 AI-criteria IDs that are gated by ai_company_status.
_AI_CRITERIA_IDS = frozenset(
    {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
)

# The 5 Design & Readability IDs that are gated by input_format=="text" — a deck
# described in conversation has no slides to score for visual design, so scoring
# them fail/warn would penalize the founder for evidence that cannot exist.
_DESIGN_CRITERIA_IDS = frozenset(
    {
        "one_idea_per_slide",
        "minimal_text",
        "slide_count_appropriate",
        "consistent_design",
        "mobile_readable",
    }
)


def _recompute_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the summary block from a (possibly gated) items list."""
    pass_count = 0
    fail_count = 0
    warn_count = 0
    na_count = 0
    failed_items: list[dict[str, Any]] = []
    warned_items: list[dict[str, Any]] = []
    categories: dict[str, dict[str, int]] = {}

    for item in items:
        status = item["status"]
        item_id = item["id"]
        meta = ITEM_LOOKUP.get(item_id, {})
        category = item.get("category", meta.get("category", "Unknown"))
        evidence = item.get("evidence")
        notes = item.get("notes")

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
                    "label": item.get("label", ""),
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
                    "label": item.get("label", ""),
                    "evidence": evidence,
                    "notes": notes,
                }
            )
        elif status == "not_applicable":
            na_count += 1
            categories[category]["not_applicable"] += 1

    applicable = len(CHECKLIST_ITEMS) - na_count
    score_pct = round((pass_count / applicable) * 100, 1) if applicable > 0 else 0.0

    if score_pct >= 85:
        overall_status = "strong"
    elif score_pct >= 70:
        overall_status = "solid"
    elif score_pct >= 50:
        overall_status = "needs_work"
    else:
        overall_status = "major_revision"

    return {
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
    }


def _force_not_applicable(items: list[dict[str, Any]], criteria_ids: frozenset[str], auto_evidence: str) -> None:
    """Force the given criteria ids to not_applicable, stamping Auto-gated evidence
    and dropping any stale sub-agent notes. Mutates items in place."""
    for item in items:
        if item.get("id") in criteria_ids:
            item["status"] = "not_applicable"
            item["evidence"] = auto_evidence
            item.pop("notes", None)


def _apply_ai_gating(result: dict[str, Any], ai_company_status: str) -> dict[str, Any]:
    """Apply deterministic AI-criteria gating based on ai_company_status.

    Rules:
    - not_ai: force the 4 AI criteria to not_applicable with Auto-gated evidence.
    - ai_core: keep sub-agent statuses (scored).
    - ai_claimed_unverified: keep sub-agent statuses (scored; they will likely
      fail for lack of evidence — the bar is relevant because they claim it).

    Evidence prefix 'Auto-gated:' distinguishes producer gating from sub-agent phrasing.
    """
    if ai_company_status not in ("not_ai",):
        # ai_core and ai_claimed_unverified: keep sub-agent statuses unchanged.
        return result

    items: list[dict[str, Any]] = result.get("items", [])
    _force_not_applicable(items, _AI_CRITERIA_IDS, "Auto-gated: not_applicable — ai_company_status=not_ai")

    if result.get("summary") is not None:
        result["summary"] = _recompute_summary(items)
    return result


def _apply_design_gating(result: dict[str, Any], input_format: str) -> dict[str, Any]:
    """Apply deterministic Design & Readability gating based on input_format.

    When the founder described the deck in conversation (input_format=="text")
    rather than uploading a file, there is no rendered slide to assess visual
    design against — force the 5 Design & Readability criteria to
    not_applicable rather than letting them score fail for lack of evidence
    that structurally cannot exist. Any other input_format (or none) is a
    no-op: the sub-agent's scored statuses pass through unchanged.
    """
    if input_format != "text":
        return result

    items: list[dict[str, Any]] = result.get("items", [])
    _force_not_applicable(items, _DESIGN_CRITERIA_IDS, "Auto-gated: not_applicable — input_format=text")

    if result.get("summary") is not None:
        result["summary"] = _recompute_summary(items)
    return result


def validate_checklist(items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Validate checklist input and produce scored summary. Returns (result, errors, warnings).

    `errors` is fatal (missing/duplicate/unknown IDs, invalid status, or a
    fail/warn item with no evidence) — a non-empty `errors` blocks the run.
    `warnings` is advisory only and never blocks the run; it currently covers
    `pass` items with no evidence (a self-graded pass costs nothing to fabricate,
    so it gets a warning rather than the silent free pass it had before)."""
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
        return {"items": [], "summary": None}, errors, []

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

        # Omit evidence/notes when absent — the schema types both as plain
        # strings (no null), so emitting None would trip a false-positive
        # SCHEMA_VIOLATION in compose_report. Evidence is only required for
        # fail/warn items (checked below).
        enriched_item: dict[str, Any] = {
            "id": item_id,
            "category": category,
            "label": meta["label"],
            "status": status,
        }
        if evidence is not None:
            enriched_item["evidence"] = evidence
        if notes is not None:
            enriched_item["notes"] = notes
        enriched.append(enriched_item)

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

    # Evidence is required for fail/warn items at checklist generation time.
    evidence_errors: list[str] = []
    # Pass items get the same emptiness check, but advisory-only: a self-graded
    # 'pass' with no evidence is the cheapest way to inflate a score, and unlike
    # fail/warn (scrutinized above) it was previously never checked at all.
    pass_evidence_warnings: list[str] = []
    for item in enriched:
        if item["status"] in ("fail", "warn"):
            ev = item.get("evidence")
            if not ev or (isinstance(ev, str) and not ev.strip()):
                msg = f"{item['id']} has status '{item['status']}' but no evidence"
                print(f"Warning: {msg}", file=sys.stderr)
                evidence_errors.append(msg)
        elif item["status"] == "pass":
            ev = item.get("evidence")
            if not ev or (isinstance(ev, str) and not ev.strip()):
                msg = f"{item['id']} has status 'pass' but no evidence"
                print(f"Warning: {msg}", file=sys.stderr)
                pass_evidence_warnings.append(msg)

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

    return (
        {
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
        },
        evidence_errors,
        pass_evidence_warnings,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deck review checklist scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", required=True, help="Inject metadata.run_id into output")
    p.add_argument(
        "--inventory",
        help=(
            "Path to deck_inventory.json; when provided, applies deterministic"
            " AI-criteria gating from ai_company_status and deterministic"
            " Design-criteria gating from input_format"
        ),
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

    # --- Validation ---
    # On stdout (no -o): emit the JSON error dict and exit 0 (the caller pipes
    # and inspects it). On -o (artifact-producer mode): match the sibling
    # producers — print errors to stderr, write NO artifact, exit 1. Writing an
    # error-shaped artifact with an "ok": true receipt would let a caller that
    # checks the exit code or receipt proceed with a broken checklist.json.
    errors: list[str] = []
    pass_warnings: list[str] = []
    if "items" not in data:
        errors.append("Missing required key: 'items'")
    elif not isinstance(data["items"], list):
        errors.append("'items' must be an array")

    if not errors:
        result, errors, pass_warnings = validate_checklist(data["items"])
    else:
        result = {"items": [], "summary": None}

    if errors:
        if args.output:
            for err in errors:
                print(f"Error: checklist validation failed: {err}", file=sys.stderr)
            sys.exit(1)
        result["validation"] = {"status": "invalid", "errors": errors, "warnings": pass_warnings}
        _write_output(json.dumps(result, indent=indent) + "\n", None)
        return

    result["validation"] = {"status": "valid", "errors": [], "warnings": pass_warnings}
    result["metadata"] = {"run_id": args.run_id}

    # Apply deterministic gating when --inventory is provided. Gating belongs to
    # the producer, not the sub-agent; the sub-agent scores all 35 criteria and
    # does not self-gate — this covers both AI-criteria gating (ai_company_status)
    # and Design-criteria gating (input_format=="text": a text-described deck has
    # no rendered slide to score visual design against).
    if args.inventory:
        try:
            with open(args.inventory, encoding="utf-8") as inv_f:
                inventory_data = json.load(inv_f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: could not read --inventory file: {e} — gating skipped", file=sys.stderr)
        else:
            ai_company_status = inventory_data.get("ai_company_status", "")
            if ai_company_status in ("not_ai", "ai_core", "ai_claimed_unverified"):
                result = _apply_ai_gating(result, ai_company_status)
            else:
                print(
                    f"Warning: --inventory ai_company_status '{ai_company_status}'"
                    " is not a recognised value — gating skipped",
                    file=sys.stderr,
                )
            result = _apply_design_gating(result, inventory_data.get("input_format", ""))

    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    summary = {"score_pct": s["score_pct"], "pass": s["pass"], "fail": s["fail"]} if s else {}
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
