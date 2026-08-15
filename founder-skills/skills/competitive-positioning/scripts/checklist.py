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


def _normalize_label(text: str) -> str:
    """Fold a criterion label for comparison: case, whitespace and punctuation drift are not signal.

    A model that rewords "Do-nothing / status quo included" as "Do nothing / status-quo included" has
    not mis-assigned anything. Only a genuinely different criterion should raise CRITERION_MISMATCH —
    a noisy signal is one nobody reads.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


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

        # Mode-gated items are exempt: their evidence is OVERWRITTEN with
        # GATE_MESSAGE below, so demanding a non-empty string here rejects the
        # whole batch over a value we are about to discard. A live run hit exactly
        # that — the sub-agent reasonably left EVID_04/NARR_03 empty in
        # conversation mode (they do not apply), the batch hard-failed, and the
        # run paid a repair dispatch to write text that never reached the output.
        evidence = item.get("evidence")
        if item_id not in MODE_GATING.get(input_mode, set()) and (
            not isinstance(evidence, str) or not evidence.strip()
        ):
            errors.append(f"Item '{item_id}' requires a non-empty evidence string")

    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing checklist items: {sorted(missing)}")

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Non-fatal signals surfaced to the founder-facing composer. Distinct from `errors`
    # above, which reject the batch.
    warnings: list[dict[str, Any]] = []

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
        evidence = src.get("evidence") or ""
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

        # Second signal against evidence landing on the wrong criterion.
        #
        # The label is canonical (from CHECKLIST_ITEMS); the evidence is the sub-agent's. They are
        # joined by id, so if the sub-agent attaches evidence to the wrong id, the join silently
        # produces a real label above someone else's justification — measured on two archived runs,
        # e.g. COVER_04 "Do-nothing / status quo included" carrying "Five direct competitors named
        # ... exceeds 2-3 minimum". Nothing could catch it: the id was valid and the evidence
        # non-empty, so each half looked correct alone.
        #
        # `criterion` is the sub-agent echoing which criterion it believes it graded. Disagreement
        # with the canonical label is a deterministic tell for a semantic slip, needing no judgement
        # about the evidence text.
        #
        # WARN, not fail, and deliberately so: this signal is new and uncalibrated, with two known
        # true positives and no measured false-positive rate. A hard failure on an unmeasured signal
        # blocks delivery on the strength of a guess. Ratchet to an error once it has run clean over a
        # meaningful number of real runs.
        echoed = src.get("criterion")
        if (
            isinstance(echoed, str)
            and echoed.strip()
            and _normalize_label(echoed) != _normalize_label(item_def["label"])
        ):
            warnings.append(
                {
                    "code": "CRITERION_MISMATCH",
                    "severity": "medium",
                    "message": (
                        f"{item_id}: graded as '{echoed.strip()}' but {item_id} is "
                        f"'{item_def['label']}'. The evidence recorded here may belong to a "
                        f"different criterion, which makes this grading unauditable."
                    ),
                }
            )

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

    # Overall status thresholds — match SKILL.md "## Scoring" section and
    # deck-review/checklist.py:267-273 for cross-skill parity.
    if score_pct >= 85:
        overall_status = "strong"
    elif score_pct >= 70:
        overall_status = "solid"
    elif score_pct >= 50:
        overall_status = "needs_work"
    else:
        overall_status = "major_revision"

    # Build failed/warned items arrays (flattened with id/category/criterion/status/evidence/principle).
    # `criterion` mirrors the human-readable label; `principle` is left empty
    # because competitive-positioning checklist items don't carry a separate
    # principle field — agents fill this in narratively if needed.
    failed_items: list[dict[str, Any]] = []
    warned_items: list[dict[str, Any]] = []
    for entry in enriched:
        if entry["status"] == "fail":
            failed_items.append(
                {
                    "id": entry["id"],
                    "category": entry["category"],
                    "criterion": entry["label"],
                    "status": entry["status"],
                    "evidence": entry["evidence"],
                    "principle": "",
                }
            )
        elif entry["status"] == "warn":
            warned_items.append(
                {
                    "id": entry["id"],
                    "category": entry["category"],
                    "criterion": entry["label"],
                    "status": entry["status"],
                    "evidence": entry["evidence"],
                    "principle": "",
                }
            )

    summary: dict[str, Any] = {
        "score_pct": score_pct,
        "overall_status": overall_status,
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warn": warn_count,
        "not_applicable": na_count,
        "failed_items": failed_items,
        "warned_items": warned_items,
    }

    return {
        # New unified summary block (parity with deck-review/financial-model-review).
        "summary": summary,
        # Legacy flat fields — keep for backward compatibility with pre-v0.4.2 consumers.
        "items": enriched,
        "score_pct": score_pct,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "na_count": na_count,
        "total": total,
        "input_mode": input_mode,
        "warnings": warnings,
        "metadata": {},  # placeholder, filled by caller
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Competitive positioning checklist scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--input-mode",
        choices=("deck", "conversation", "document"),
        help="Input mode for mode gating. Overrides 'input_mode' in the stdin JSON. "
        "Defaults to the stdin value, then 'conversation'.",
    )
    p.add_argument(
        "--run-id",
        help="Run identifier stamped into result.metadata.run_id. Overrides any "
        "'metadata' in the stdin JSON (the sub-agent returns items only).",
    )
    p.add_argument(
        "--positioning-scores",
        help="Path to positioning_scores.json. When given, its top-level "
        "'views_fingerprint' is copied verbatim into this checklist's output as "
        "graded_against.views_fingerprint — a record of which scored map this "
        "checklist run graded. Never recomputed here (score_positioning.py owns "
        "the one implementation). Absent flag: graded_against is omitted "
        "entirely. Missing/unparseable file or missing key: graded_against is "
        "omitted and a note is printed to stderr — this is an optional "
        "provenance read and must never block the checklist, which is "
        "deliverable-critical.",
    )
    return p.parse_args()


def _read_views_fingerprint(path: str) -> str | None:
    """Read 'views_fingerprint' verbatim from a positioning_scores.json file.

    Returns None (never raises) on any failure — missing file, unreadable
    file, invalid JSON, non-dict content, or a missing/non-string key. Prints
    a stderr note describing the failure so the omission is visible without
    blocking the (deliverable-critical) checklist run.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        print(f"Note: --positioning-scores file could not be read ({e}); omitting graded_against", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Note: --positioning-scores file is not valid JSON ({e}); omitting graded_against", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(
            "Note: --positioning-scores file is not a JSON object; omitting graded_against",
            file=sys.stderr,
        )
        return None

    fingerprint = data.get("views_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        print(
            "Note: --positioning-scores file has no 'views_fingerprint' string; omitting graded_against",
            file=sys.stderr,
        )
        return None

    return fingerprint


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

    # input_mode precedence: CLI flag > stdin JSON > default ("conversation").
    # The CHECKLIST sub-agent returns items only, so the main thread stamps the
    # real input_mode via --input-mode; without it deck/document runs would
    # silently default to "conversation" and mis-gate NARR_03/EVID_04.
    input_mode = args.input_mode or data.get("input_mode", "conversation")
    if input_mode not in ("deck", "conversation", "document"):
        _die(f"Invalid input_mode '{input_mode}'. Must be 'deck', 'conversation', or 'document'")

    data_confidence = data.get("data_confidence", "exact")

    # metadata precedence: --run-id (CLI) wins over any 'metadata' in stdin JSON.
    # The CHECKLIST sub-agent returns items only — the main thread stamps run_id
    # via --run-id so checklist.json carries the run_id the Context B verifier
    # greps for.
    if args.run_id:
        metadata: dict[str, Any] = {"run_id": args.run_id}
    else:
        metadata = data.get("metadata", {})

    result = validate_and_score(data["items"], input_mode, data_confidence)
    result["_produced_by"] = "checklist"
    result["metadata"] = metadata
    result["input_mode"] = input_mode

    # graded_against: optional provenance recording which scored positioning
    # map this checklist run graded against. Absent flag -> absent field
    # (never inferred). A missing/unparseable file or missing key also omits
    # the field (with a stderr note) rather than blocking this deliverable-
    # critical producer.
    if args.positioning_scores:
        fingerprint = _read_views_fingerprint(args.positioning_scores)
        if fingerprint is not None:
            result["graded_against"] = {"views_fingerprint": fingerprint}

    if result["fail_count"] == 0 and result["warn_count"] == 0:
        print("Note: all items passed — verify assessments are evidence-based, not defaulting to pass", file=sys.stderr)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    summary = {
        "score_pct": result["score_pct"],
        "pass_count": result["pass_count"],
        "fail_count": result["fail_count"],
    }
    _write_output(out, args.output, summary=summary)

    # Summary to stderr for visibility in batch runs
    print(
        f"checklist: score={result['score_pct']:.1f}%"
        f", pass={result['pass_count']}"
        f", fail={result['fail_count']}"
        f", warn={result.get('warn_count', 0)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
