#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Deck review checklist scorer.

Validates 35 criteria across 7 categories with pass/fail/warn/not_applicable
scoring. Computes overall score percentage and status over the 34 that carry
weight (see ZERO_WEIGHT).

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
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _thresholds  # noqa: E402


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

# CRITERIA THAT ARE GRADED BUT CARRY NO WEIGHT, each mapped to the criterion it duplicates.
#
# `no_dodged_competition` asks the question `competition_honest` asks: the same Fail
# condition ("no competition slide" / "we have no competitors") and overlapping Pass/Warn.
# Over the kept review checklists the two never split fail/pass, and every
# `competition_honest` fail came with a `no_dodged_competition` fail -- so one weakness was
# counted twice, and a deck that dodged competition lost two criteria for it.
#
# The grader still scores all 35 (the id list is the artifact contract, and downstream readers
# list ids). The duplicate then MIRRORS the canonical status, is stamped `weight: 0`, and is
# left out of every count, the score, `by_category` and the fail/warn lists, so the weakness
# reaches the fixes once. `status_by_id` keeps it. Only this producer decides weight;
# renderers read the stamped `weight`, never this table.
ZERO_WEIGHT: dict[str, str] = {"no_dodged_competition": "competition_honest"}

# How many criteria the score is computed over. `total` stays the number of criteria listed.
SCORED_COUNT = len(CHECKLIST_ITEMS) - len(ZERO_WEIGHT)


def _is_zero_weight(item: dict[str, Any]) -> bool:
    return bool(item.get("weight", 1) == 0)


def _mirror_zero_weight(items: list[dict[str, Any]]) -> None:
    """Make each zero-weight item show its canonical criterion's status. Mutates in place.

    Idempotent and re-derived from the canonical item every time, so a gate that changes the
    canonical status before the summary is recomputed still leaves the two in agreement. The
    duplicate's own evidence and fix are dropped: the canonical item carries the finding.
    """
    by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
    for dup_id, canonical_id in ZERO_WEIGHT.items():
        dup = by_id.get(dup_id)
        canonical = by_id.get(canonical_id)
        if dup is None or canonical is None:
            continue
        dup["status"] = canonical.get("status")
        dup["weight"] = 0
        dup["evidence"] = f"Scored once, under '{ITEM_LOOKUP[canonical_id]['label']}'"
        dup.pop("notes", None)
        dup.pop("verified_by", None)


# The 4 AI-criteria IDs that are gated by ai_company_status.
_AI_CRITERIA_IDS = frozenset(
    {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
)

# Formats with no rendered page, so a visual criterion cannot be assessed. Derived from
# deck_inventory.schema.json's input_format enum ["pdf","pptx","markdown","text"] — pdf and
# pptx render; these two do not.
_UNRENDERED_FORMATS = frozenset({"text", "markdown"})

# A format that renders is necessary but NOT sufficient: a PDF whose slides are images with
# no text layer, or whose pages were never all read, cannot support a design judgement
# either. Gating on `input_format` alone let a partially-read deck score design criteria as
# if every slide had been seen -- the same defect as scoring a PowerPoint nobody converted,
# one layer down.
_UNRENDERED_QUALITY = frozenset({"image_only", "partial"})

# The Design & Readability IDs gated when there is no rendered page: scoring them fail/warn
# would penalize the founder for evidence that cannot exist.
#
# FOUR, not five. `slide_count_appropriate` is deliberately NOT here — counting slides is
# arithmetic, not a visual judgement, and `total_slides` is already in the inventory. Gating
# it discarded an answer we hold, and the model then made the criticism anyway: a live run
# marked it not_applicable and still told the founder "the deck runs long at 25 slides
# against a ~10-12 slide pre-seed norm" — reaching them outside the rubric, unscored and
# without evidence. The choice was never whether to say it, only whether it counts.
#
# The other four stay gated. Word count is likewise knowable, which makes `minimal_text`
# the tempting next one, but "big type, minimal paragraphs" is half a question about type
# size — under-claiming is the safer error where a founder's score is concerned.
_VERIFIED_BY_VALUES = frozenset({"measured", "inferred", "not_possible"})

# WHICH CRITERIA REST ON SEEING SOMETHING. The design gate above keys on whether slides were
# SEEN; this keys on whether a property was MEASURED. Different questions, and a run can
# satisfy the first and fail the second -- the checklist sub-agent's tools are
# Read/Write/Edit/Glob/Grep, which cannot render a phone viewport.
#
# Seeded from the visual design set because those are the four whose judgement rests on an
# observation the assigned reviewer may be unable to make.
_MEASUREMENT_DEPENDENT_IDS: frozenset[str]

_DESIGN_CRITERIA_IDS = frozenset(
    {
        "one_idea_per_slide",
        "minimal_text",
        "consistent_design",
        "mobile_readable",
    }
)


_MEASUREMENT_DEPENDENT_IDS = frozenset(_DESIGN_CRITERIA_IDS)


def _recompute_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the summary block from a (possibly gated) items list.

    Side effect: re-mirrors the zero-weight items first, so every path that rescores (the
    producer, the AI gate, the design gate) leaves them showing their canonical status.
    """
    _mirror_zero_weight(items)
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

        if _is_zero_weight(item):
            # Listed and shown, never counted: it mirrors a criterion already counted.
            continue

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

    # A `warn` earns HALF, not nothing. Every one of the 35 criteria defines its Warn as
    # partial satisfaction ("Mostly single-idea but 1-2 slides are overloaded"), so
    # scoring it identically to `fail` contradicts the rubric's own text — and warns are
    # most of the scale on real decks (11-17 of 35 measured).
    #
    # 0.5 is a CHOICE, not a measurement: warn sits between pass and fail in a 3-outcome
    # ordinal (not_applicable leaves the denominator), and the midpoint assumes least.
    #
    # Still no per-CRITERION weighting — that is a different question, deliberately
    # refused below to avoid subjective weight arguments. This is partial credit for a
    # STATUS, which the rubric already defines.
    applicable = SCORED_COUNT - na_count
    score_pct = round(((pass_count + 0.5 * warn_count) / applicable) * 100, 1) if applicable > 0 else 0.0

    overall_status = _thresholds.band_for(score_pct)

    return {
        "total": len(CHECKLIST_ITEMS),
        # pass + fail + warn + not_applicable == scored, never total: a zero-weight item is
        # listed (total) but not counted (scored).
        "scored": SCORED_COUNT,
        "pass": pass_count,
        "fail": fail_count,
        "warn": warn_count,
        "not_applicable": na_count,
        "score_pct": score_pct,
        "overall_status": overall_status,
        "by_category": categories,
        "failed_items": failed_items,
        "warned_items": warned_items,
        # Each criterion's status by id. `items` is in the order the grader wrote it, so a
        # check that names a criterion (a scenario's artifact_json path) cannot index into it.
        "status_by_id": {item["id"]: item["status"] for item in items},
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


def _every_slide_was_seen(inventory: dict[str, Any] | None) -> bool:
    """False when any slide explicitly reports it was not rendered.

    ABSENCE IS NOT DENIAL. The per-slide flag is optional and older inventories omit it, so
    only an explicit `false` counts -- reading omission as "unseen" would gate design
    criteria on every deck produced before the field existed.
    """
    slides = (inventory or {}).get("slides")
    if not isinstance(slides, list):
        return True
    return not any(isinstance(s, dict) and s.get("visual_evidence_captured") is False for s in slides)


def _apply_design_gating(
    result: dict[str, Any],
    input_format: str,
    input_quality: str = "",
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply deterministic Design & Readability gating based on input_format.

    Force the 4 VISUAL Design & Readability criteria to not_applicable when there is no
    RENDERED SLIDE to assess visual design against, rather than letting them score
    fail for evidence that structurally cannot exist.

    That is true of two formats, not one:
      * "text"     — the founder described the deck in conversation.
      * "markdown" — a file, but a plain-text one. It has no fonts, no colours and no
                     rendered page, so "24pt+ body text" and the phone test cannot be
                     assessed any more than they can for "text". Only "text" was gated
                     originally, so markdown decks were scored on all four.

    "pdf" and "pptx" render, and pass through unchanged.
    """
    quality = str(input_quality or "").lower()
    # A THIRD AXIS. `input_quality: good` asserts every page rendered; the per-slide flag
    # asserts it per slide, and nothing compared them -- so a deck could claim good quality
    # while carrying a slide the ingesting agent says it never saw, and all four design
    # criteria were scored off it anyway.
    every_slide_seen = _every_slide_was_seen(inventory)
    if input_format not in _UNRENDERED_FORMATS and quality not in _UNRENDERED_QUALITY and every_slide_seen:
        return result
    # The evidence string is PARSED downstream, not just displayed: compose_report's
    # `design_gate_reason` reads the `input_` prefix and then a `format=`/`quality=` tail,
    # and visualize.py keys its category charts on the same prefix. A reason outside that
    # shape makes the disclosure vanish while the scope note still claims design was
    # reviewed -- so the new reason wears the `quality=` shape deliberately.
    if input_format in _UNRENDERED_FORMATS:
        reason = f"input_format={input_format}"
    elif quality in _UNRENDERED_QUALITY:
        reason = f"input_quality={quality}"
    else:
        reason = "input_quality=slide_not_rendered"

    items: list[dict[str, Any]] = result.get("items", [])
    _force_not_applicable(items, _DESIGN_CRITERIA_IDS, f"Auto-gated: not_applicable — {reason}")

    # A GATED CRITERION IS NO LONGER SCORED, so it can no longer be scored-without-measuring.
    # `validate_checklist` raises UNVERIFIED_MEASUREMENT before this runs, and on the gate's
    # COMMON path -- a deck with no rendered page -- the two statements contradict each other
    # in one report: "4 design criteria could not be reviewed" beside "these judgements were
    # reasoned rather than measured". The second is about a score that no longer exists.
    gated_ids = {item["id"] for item in items if item.get("status") == "not_applicable"}
    warnings = result.get("validation", {}).get("warnings")
    if isinstance(warnings, list):
        result["validation"]["warnings"] = [
            w
            for w in warnings
            if not (
                isinstance(w, str)
                and w.startswith("UNVERIFIED_MEASUREMENT")
                and any(f": {gid} " in w for gid in gated_ids)
            )
        ]

    if result.get("summary") is not None:
        result["summary"] = _recompute_summary(items)
    return result


def validate_checklist(
    items: list[dict[str, Any]], *, numbers_from_arithmetic: bool = False
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Validate checklist input and produce scored summary. Returns (result, errors, warnings).

    `numbers_from_arithmetic` (set when `--reconciliation` is given) means `numbers_consistent`'s
    status and evidence are replaced by the arithmetic afterwards, so a reviewer's fail on it
    needs no notes: demanding them would cost a corrective dispatch for text that is discarded.

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
        vb = item.get("verified_by")
        if vb is not None and vb not in _VERIFIED_BY_VALUES:
            # An unknown value is an ERROR, not a kept string: a typo would otherwise read as
            # a real claim about how the judgement was reached. Same shape as the status check.
            errors.append(f"Item '{item_id}' has unknown verified_by '{vb}'")
            continue

        status = item.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"Invalid status '{status}' for item '{item_id}'. Must be one of: {sorted(VALID_STATUSES)}")

    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing checklist items: {sorted(missing)}")

    if errors:
        return {"items": [], "summary": None}, errors, []

    # Build enriched items. Counting happens ONCE, in _recompute_summary(enriched)
    # below — this loop used to maintain its own parallel tallies, which after the
    # summary was centralised became dead stores that ruff cannot flag (augmented
    # assignment). A bug fixed in that copy would have had no effect and no warning.
    enriched: list[dict[str, Any]] = []

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
        if item.get("verified_by") is not None:
            enriched_item["verified_by"] = item["verified_by"]
        enriched.append(enriched_item)

    # Evidence is required for fail/warn items at checklist generation time.
    evidence_errors: list[str] = []
    # Pass items get the same emptiness check, but advisory-only: a self-graded
    # 'pass' with no evidence is the cheapest way to inflate a score, and unlike
    # fail/warn (scrutinized above) it was previously never checked at all.
    pass_evidence_warnings: list[str] = []
    for item in enriched:
        if item["id"] in ZERO_WEIGHT:
            # Its evidence and fix are replaced by the mirror, so requiring them would spend a
            # corrective dispatch on text nobody reads.
            continue
        if item["status"] in ("fail", "warn"):
            ev = item.get("evidence")
            if not ev or (isinstance(ev, str) and not ev.strip()):
                msg = f"{item['id']} has status '{item['status']}' but no evidence"
                print(f"Warning: {msg}", file=sys.stderr)
                evidence_errors.append(msg)
            # `notes` carries the founder-facing FIX and is contracted as required on
            # fail/warn. Fatal, symmetric with evidence above, because every run is
            # fresh: a missing fix is this run's sub-agent ignoring the contract, not a
            # legacy artifact to tolerate — and the corrective-dispatch budget exists at
            # exactly this step. Rendering the criterion label instead is what made the
            # fixes section contain no fixes.
            nt = item.get("notes")
            replaced = numbers_from_arithmetic and item["id"] == NUMBERS_CRITERION
            if not replaced and (not nt or (isinstance(nt, str) and not nt.strip())):
                msg = f"{item['id']} has status '{item['status']}' but no notes (the founder-facing fix)"
                print(f"Warning: {msg}", file=sys.stderr)
                evidence_errors.append(msg)
        elif item["status"] == "pass":
            ev = item.get("evidence")
            if not ev or (isinstance(ev, str) and not ev.strip()):
                msg = f"{item['id']} has status 'pass' but no evidence"
                print(f"Warning: {msg}", file=sys.stderr)
                pass_evidence_warnings.append(msg)

    # A MEASUREMENT CRITERION SCORED WITHOUT A MEASUREMENT. Warning, not gating: a
    # `not_possible` FAIL reached by real reasoning is still information, and forcing it to
    # not_applicable would discard it -- the same mistake already recorded above for
    # slide_count_appropriate. What the founder gains is that a guess and a measurement stop
    # looking identical in the artifact.
    for item in enriched:
        if (
            item["id"] in _MEASUREMENT_DEPENDENT_IDS
            and item["status"] in ("pass", "fail")
            and item.get("verified_by") in ("inferred", "not_possible")
        ):
            msg = (
                f"UNVERIFIED_MEASUREMENT: {item['id']} is scored '{item['status']}' but "
                f"verified_by is '{item['verified_by']}' — the judgement rests on an "
                "observation that was not made"
            )
            print(f"Warning: {msg}", file=sys.stderr)
            pass_evidence_warnings.append(msg)

    # ONE summary implementation. This used to be a second, inline copy of
    # _recompute_summary's body; the two drifting apart is a whole bug class, and the
    # --inventory gating path already calls _recompute_summary, so a divergence would
    # have shown up only on gated decks.
    #
    # MUST be `enriched`, never the raw `items`: _recompute_summary trusts each item's
    # own `category`/`label`, while this function derives them from ITEM_LOOKUP.
    # Measured — against raw input the two disagree on 200/200 adversarial inputs;
    # against `enriched` they are byte-identical, key order included, across 2,000.
    return (
        {
            "items": enriched,
            "summary": _recompute_summary(enriched),
        },
        evidence_errors,
        pass_evidence_warnings,
    )


# ---------------------------------------------------------------------------
# `numbers_consistent` IS SCORED FROM THE ARITHMETIC, not from the reviewer's reading.
#
# The reviewer reads the deck by eye and, in kept runs, has both called a deck consistent while
# the arithmetic found a figure its own inputs refute, and failed one on a disagreement nothing
# computed. The reconciliation artifact carries the engine's decision (`select()` in
# reconcile.py is the one place that decides what a founder sees), so this criterion reads only
# its surviving `relations` and its suppressed COUNTS -- never a second opinion on what survived.
#
# The verdicts that mean a comparison against a figure the deck states actually ran. `derived`
# (a figure worked out with nothing to compare it to), `incomparable` and `dropped` (no
# comparison made) and `superseded` (replaced by a comparison counted on its own) establish
# nothing about consistency. A `downgraded` contradiction was compared and then withdrawn on
# review: it counts as a comparison, never as a disagreement.
_COMPARISON_VERDICTS = frozenset(
    {
        "confirmation",
        "restatement",
        "contradiction",
        "exceeds_stated_limit",
        "rounding_gap",
        "convention_differs",
        "downgraded",
    }
)
NUMBERS_CRITERION = "numbers_consistent"

# Why the criterion could not be scored, by reconciliation status, in the founder's terms.
_UNCHECKED_REASON = {
    "no_figures": "no figures could be read off the deck to compare",
    "gate_failed": "the figures read off the deck could not be confirmed by a second read, so none could be compared",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def count_comparisons(reconciliation: dict[str, Any]) -> int:
    """How many comparisons against a stated figure ran, selected or suppressed."""
    shown = sum(
        1 for rel in _as_list(reconciliation.get("relations")) if _as_dict(rel).get("verdict") in _COMPARISON_VERDICTS
    )
    withheld = sum(
        count
        for key, count in _as_dict(reconciliation.get("suppressed")).items()
        if key in _COMPARISON_VERDICTS and isinstance(count, int)
    )
    return shown + withheld


def _rendered(relations: list[dict[str, Any]]) -> list[str]:
    return [line for line in (str(r.get("rendered", "")).strip() for r in relations) if line]


def _untested_tail(reconciliation: dict[str, Any]) -> str:
    claims = [str(c).strip() for c in _as_list(reconciliation.get("untested_claims")) if str(c).strip()]
    if not claims:
        return ""
    return f" It could not test: {'; '.join(claims)}."


def _apply_numeric_scoring(result: dict[str, Any], reconciliation: dict[str, Any]) -> dict[str, Any]:
    """Score `numbers_consistent` from the reconciliation, then recompute the summary.

    Rules, in order:
      * the reconciliation did not check the figures -> not_applicable;
      * it checked them but ran ZERO comparisons -> not_applicable. A pass there would say the
        figures agree when the arithmetic established nothing either way;
      * any surviving contradiction, or a plan passing a limit the deck states -> fail;
      * else any total off by more than its own rounding -> warn;
      * else pass, saying how many comparisons ran and naming any claim it could not test.

    A contradiction withdrawn on review has verdict `downgraded` and is not in `relations`, so
    it does not fail the item. A fail or warn carries `notes` written here: without them the
    criterion never reaches the fixes list, and "your deck disagrees with itself" is the one
    finding that most needs to. Every outcome, not_applicable included, is stamped
    `scored_by: "arithmetic"` -- compose warns on a checked run whose item carries no stamp.
    The reviewer's own status is kept as `reviewer_status`, for measuring how often the two
    disagree; it is never rendered.
    """
    items: list[dict[str, Any]] = result.get("items", [])
    item = next((i for i in items if isinstance(i, dict) and i.get("id") == NUMBERS_CRITERION), None)
    if item is None:
        return result
    reviewer_status = item.get("status")
    status_value = reconciliation.get("status")
    relations = [_as_dict(r) for r in _as_list(reconciliation.get("relations"))]
    disagree = _rendered([r for r in relations if r.get("verdict") == "contradiction"])
    exceeded = _rendered([r for r in relations if r.get("verdict") == "exceeds_stated_limit"])
    rounding = _rendered([r for r in relations if r.get("verdict") == "rounding_gap"])
    comparisons = count_comparisons(reconciliation)

    notes: str | None = None
    if status_value != "checked":
        reason = _UNCHECKED_REASON.get(str(status_value), "the deck's figures could not be cross-checked")
        status = "not_applicable"
        evidence = f"Not scored: {reason}."
    elif comparisons == 0:
        status = "not_applicable"
        evidence = (
            "Not scored: no figure on the deck could be compared against another figure it states, "
            "so the arithmetic established nothing either way." + _untested_tail(reconciliation)
        )
    elif disagree or exceeded:
        status = "fail"
        found = disagree + exceeded
        evidence = "Scored from the arithmetic: " + "; ".join(found) + "."
        if _as_dict(reconciliation.get("interpretation")).get("status") == "not_run":
            # Failing is the right incentive (skipping the review pass must not improve the
            # score), but the founder must not read an un-reviewed disagreement as settled.
            evidence += (
                " Nobody reviewed these for cases where the comparison itself does not hold, so treat "
                "them as questions to check rather than settled problems."
            )
        notes = (
            "Reconcile these figures so the deck agrees with itself: "
            + "; ".join(found)
            + ". Correct whichever figure is wrong, or state the basis each one is computed on."
        )
    elif rounding:
        status = "warn"
        evidence = "Scored from the arithmetic: " + "; ".join(rounding) + "."
        notes = (
            "Check these totals against the unrounded parts and print figures that add up: " + "; ".join(rounding) + "."
        )
    else:
        status = "pass"
        plural = "comparison" if comparisons == 1 else "comparisons"
        evidence = (
            f"Scored from the arithmetic: {comparisons} {plural} between figures the deck states "
            f"{'was' if comparisons == 1 else 'were'} computed, and none disagrees." + _untested_tail(reconciliation)
        )

    item["status"] = status
    item["evidence"] = evidence
    if notes is None:
        item.pop("notes", None)
    else:
        item["notes"] = notes
    item.pop("verified_by", None)
    item["scored_by"] = "arithmetic"
    if isinstance(reviewer_status, str):
        item["reviewer_status"] = reviewer_status

    if result.get("summary") is not None:
        result["summary"] = _recompute_summary(items)
    return result


def load_reconciliation(path: str, run_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read the reconciliation this checklist is scored against. Returns (data, error).

    A PRECONDITION, not an input to skip on: a file that is unreadable, from another run, or has
    no status would otherwise score this criterion from nothing -- or from an earlier review of
    the same company -- and the delivered report would carry it as this deck's arithmetic.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"reconciliation artifact at {path} is unreadable: {exc}"
    if not isinstance(data, dict):
        return None, f"reconciliation artifact at {path} is not a JSON object"
    found = _as_dict(data.get("metadata")).get("run_id")
    if found != run_id:
        return None, (
            f"reconciliation artifact at {path} belongs to run {found!r}, not {run_id!r} — "
            "it is left over from an earlier review and says nothing about this deck"
        )
    status = data.get("status")
    if not isinstance(status, str) or not status:
        return None, f"reconciliation artifact at {path} carries no status"
    return data, None


def _fail_invalid(errors: list[str], output_path: str | None, indent: int | None) -> NoReturn:
    """Reject loudly: diagnostic on stdout, a line on stderr, `-o` untouched, exit 1.

    Copy of market-sizing's helper (sibling scripts are standalone).
    """
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": errors}}, indent=indent) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


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
    p.add_argument(
        "--reconciliation",
        help=(
            "Path to this run's reconciliation.json; when provided, numbers_consistent is scored"
            " from the arithmetic. An unreadable file, another run's, or one with no status is"
            " refused (exit 1, -o untouched). A what-if rerun omits it."
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

    # The reconciliation is checked FIRST, before the items: a refused precondition must not
    # depend on whether the sub-agent's hand-off also happened to be valid.
    reconciliation: dict[str, Any] | None = None
    if args.reconciliation:
        reconciliation, recon_error = load_reconciliation(args.reconciliation, args.run_id)
        if recon_error:
            _fail_invalid([recon_error], args.output, indent)

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
        result, errors, pass_warnings = validate_checklist(
            data["items"], numbers_from_arithmetic=reconciliation is not None
        )
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
            result = _apply_design_gating(
                result,
                inventory_data.get("input_format", ""),
                inventory_data.get("input_quality", ""),
                inventory_data,
            )

    # After every other gate, so nothing later can overwrite the arithmetic's status.
    if reconciliation is not None:
        result = _apply_numeric_scoring(result, reconciliation)

    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    summary = {"score_pct": s["score_pct"], "pass": s["pass"], "fail": s["fail"]} if s else {}
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
