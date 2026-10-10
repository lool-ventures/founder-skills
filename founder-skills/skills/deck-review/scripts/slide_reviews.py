#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer for slide_reviews.json. See deck_inventory.py for the pattern."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


def _check_reconciliation(path: str, run_id: str) -> tuple[str | None, dict[str, Any]]:
    """Gate the numeric-reconciliation chain. Returns (an error message or None, the loaded artifact).

    WHY THIS GATE IS HERE and not in compose. The obvious home for "a required artifact
    is missing" is `compose_report.py`'s `MISSING_ARTIFACT` warning, and it does not
    work: measured, removing an artifact leaves compose exiting **0** with a complete
    report. A step whose only downstream consumer is a warning is a step that gets
    skipped in silence — which is exactly what happened to the claim-check step, passed
    over in a live run with no narration and no trace.

    So the gate sits on the step the model will never skip, because it produces the
    deliverable. That makes the ledger chain a precondition for work the model wants to
    do, the same shape as `checklist.py --inventory`.

    Parity, not mere presence: a stale reconciliation from a previous review of the same
    company satisfies an absence check while the whole chain was skipped this run, and the
    cleanup delete that would prevent that can be refused (older Cowork hosts did) and is
    deliberately tolerated.
    """
    if not os.path.exists(path):
        return (
            f"reconciliation artifact not found at {path} — run the ledger chain (Steps 3.5-3.8) before this step",
            {},
        )
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return f"reconciliation artifact at {path} is unreadable: {exc}", {}
    if not isinstance(data, dict):
        return f"reconciliation artifact at {path} is not a JSON object", {}
    found = (data.get("metadata") or {}).get("run_id")
    if found != run_id:
        return (
            f"reconciliation artifact at {path} belongs to run {found!r}, not {run_id!r} — "
            "it is left over from an earlier review and says nothing about this deck"
        ), {}
    if not data.get("status"):
        return f"reconciliation artifact at {path} carries no status", {}
    return None, data


# ---------------------------------------------------------------------------
# NUMERIC LINT: a slide review saying two figures disagree when the arithmetic did not find it.
#
# The reviewer reads the deck by eye. In kept runs it has called figures inconsistent that are not:
# a metric and its inverse, a part of a later total, a figure the deck itself labels conservative.
# The arithmetic (reconcile.py, whose `select()` decides what survives) is the authority on whether
# two stated figures disagree. So a review string that claims a disagreement is BACKED when one of
# its numerals appears in the rendered line of a surviving contradiction, exceeds_stated_limit or
# rounding_gap, and UNBACKED otherwise.
#
# WARN-ONLY, deliberately. The vocabulary below is an enumerated list, porous both ways: a neutral
# wording ("told in two metrics") passes it, and a real finding the engine cannot compute (the same
# quantity written two ways) fires it. Measured over kept runs, unbacked hits include real findings,
# so this never fails the step, never changes the artifact and never reaches the founder: one stderr
# line per unbacked hit and a count in the receipt, for measurement. "Backed" is loose: one shared
# numeral suffices, so a small integer or a year can back a hit by coincidence, and the unbacked
# count is a floor. Matching is per string (one weakness, one recommendation, ...), and "slide N"
# references are stripped before numerals are counted, so a sentence pointing at two slides is not
# a sentence stating two figures. Benchmark comparisons ("well below the seed median", "vs.") are
# deliberately not in the vocabulary: over kept runs every one of them compared a deck figure with
# an outside benchmark, never the deck with itself.
# ---------------------------------------------------------------------------

CONTRA_RE = re.compile(
    r"\b(?:contradict\w*|inconsisten\w*|disagree\w*|conflict\w*|mismatch\w*|discrepanc\w*"
    r"|(?:does|do|did)\s+not\s+(?:match|agree|reconcile|add\s+up|tie)"
    r"|(?:doesn|don|didn)['’]t\s+(?:match|agree|reconcile|add\s+up|tie)"
    r"|at\s+odds|choose\s+one)\b",
    re.IGNORECASE,
)
_SLIDE_REF_RE = re.compile(
    # "s4" is a slide reference only written solid: "s 40" would also strip "it's 40%".
    r"\b(?:(?:slides?|pages?|p\.)\s*#?|s(?=\d))\d+(?:\s*(?:,|and|&|or|-|–|to)\s*\d+)*",
    re.IGNORECASE,
)
_NUMERAL_RE = re.compile(r"\d+(?:[.,]\d+)*")
_BACKING_VERDICTS = frozenset({"contradiction", "exceeds_stated_limit", "rounding_gap"})


def _numerals(text: str) -> list[str]:
    """The numerals a text states, slide references removed and thousands separators dropped."""
    return [n.replace(",", "") for n in _NUMERAL_RE.findall(_SLIDE_REF_RE.sub(" ", text))]


def _review_strings(data: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for review in data.get("reviews") or []:
        if not isinstance(review, dict):
            continue
        for field in ("strengths", "weaknesses", "recommendations"):
            for i, text in enumerate(review.get(field) or []):
                if isinstance(text, str):
                    out.append((f"slide {review.get('slide_number')} {field}[{i}]", text))
    for i, missing in enumerate(data.get("missing_slides") or []):
        if isinstance(missing, dict) and isinstance(missing.get("recommendation"), str):
            out.append((f"missing_slides[{i}]", missing["recommendation"]))
    overall = data.get("overall_narrative_assessment")
    if isinstance(overall, str):
        out.append(("overall_narrative_assessment", overall))
    return out


def numeric_lint(data: dict[str, Any], recon: dict[str, Any]) -> list[dict[str, Any]]:
    """Every review string that states a numeric disagreement, each marked backed or not.

    A hit is the disagreement vocabulary plus two or more numerals once slide references are
    removed. It is backed when one of its numerals is in the rendered line of a surviving relation
    the arithmetic reports as a disagreement. Pure: reads nothing from disk.
    """
    backing: set[str] = set()
    for rel in recon.get("relations") or []:
        if isinstance(rel, dict) and rel.get("verdict") in _BACKING_VERDICTS:
            backing.update(_numerals(str(rel.get("rendered") or "")))
    hits: list[dict[str, Any]] = []
    for where, text in _review_strings(data):
        match = CONTRA_RE.search(text)
        if match is None:
            continue
        numerals = _numerals(text)
        if len(numerals) < 2:
            continue
        hits.append({"where": where, "phrase": match.group(0), "backed": bool(backing.intersection(numerals))})
    return hits


def main() -> int:
    p = argparse.ArgumentParser(description="Producer for slide_reviews.json")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--reconciliation",
        required=True,
        help="reconciliation.json for this run; the numeric chain must have run before slide reviews",
    )
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    gate_error, recon = _check_reconciliation(args.reconciliation, args.run_id)
    if gate_error:
        print(f"Error: {gate_error}", file=sys.stderr)
        return 1

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("Error: stdin must be a JSON object", file=sys.stderr)
        return 1

    schema = load_schema(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "references",
            "schemas",
            "slide_reviews.schema.json",
        )
    )

    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        print(f"Error: slide_reviews validation failed: {e}", file=sys.stderr)
        return 1

    # Warn-only (see NUMERIC LINT above): after the write, so it never changes the artifact or the exit code.
    hits = numeric_lint(data, recon)
    unbacked = [hit for hit in hits if not hit["backed"]]
    for hit in unbacked:
        print(
            f"Warning: numeric_lint: {hit['where']} says figures disagree ({hit['phrase']!r}) "
            "and reconciliation.json reports no such disagreement",
            file=sys.stderr,
        )
    receipt["numeric_lint"] = {"hits": len(hits), "unbacked": len(unbacked)}
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
