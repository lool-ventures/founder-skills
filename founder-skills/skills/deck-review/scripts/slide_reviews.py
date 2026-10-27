#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer for slide_reviews.json. See deck_inventory.py for the pattern."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

import _deck_text_file
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


def _reject(code: str, message: str) -> int:
    """A loud refusal: one JSON diagnostic on stdout, one line on stderr, `-o` untouched."""
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message}) + "\n")
    print(f"Error ({code}): {message}; nothing was written", file=sys.stderr)
    return 1


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


_OCR_FIX = "run Step 3.95 (deck_ocr.py until it prints complete, then ocr_check.py), then this pipe again"
_WRONG_DECK_FIX = (
    "the deck file changed since its text was read: run Step 2's conversion block (for PowerPoint or Keynote) and "
    "deck_text.py again, then Steps 3.5-3.95, then this pipe"
)


def _check_ocr(
    ledger_path: str,
    deck_text_path: str,
    reconciliation_path: str,
    ocr_check_path: str | None,
    reconciliation: dict[str, Any],
    run_id: str,
) -> tuple[str, str] | None:
    """Gate Step 3.95: when a figure the numbers section uses sits on a slide read from how it looks, this run's
    machine-read check must exist for this reconciliation. (code, message) when it does not, else None. A deck
    with no such figure needs no file."""
    import _ocr_scope

    try:
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)
        if not isinstance(ledger, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return "LEDGER_UNREADABLE", f"cannot read {ledger_path}: {exc}"
    with open(deck_text_path, encoding="utf-8") as fh:
        pages_source = _deck_text_file.pages_source(_deck_text_file.front_matter(fh.read()))
    if not _ocr_scope.in_scope(ledger, reconciliation, pages_source):
        return None
    if not ocr_check_path or not os.path.exists(ocr_check_path):
        return "OCR_CHECK_MISSING", f"figures on image slides were not machine-read; {_OCR_FIX}"
    try:
        with open(ocr_check_path, encoding="utf-8") as fh:
            check = json.load(fh)
        if not isinstance(check, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError):
        return "OCR_CHECK_MISSING", f"{ocr_check_path} is unreadable; {_OCR_FIX}"
    raw_meta = check.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    if meta.get("run_id") != run_id:
        return "OCR_CHECK_OTHER_RUN", f"{ocr_check_path} belongs to run {meta.get('run_id')!r}; {_OCR_FIX}"
    with open(reconciliation_path, "rb") as fh:
        current = hashlib.sha256(fh.read()).hexdigest()
    if meta.get("reconciliation_sha256") != current:
        return "OCR_CHECK_STALE", f"{ocr_check_path} was made for an earlier reconciliation; {_OCR_FIX}"
    if check.get("status") == "not_applicable" and check.get("reason") == "deck_mismatch":
        return "OCR_CHECK_WRONG_DECK", _WRONG_DECK_FIX
    return None


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


# A STRENGTH THE ARITHMETIC REFUTES: a slide review praising a figure that reconciliation.json
# shows the deck got wrong (a kept relation with verdict "contradiction", its stated figure).
# Warn-only, like the lint above: the reviewer is told not to (Step 4's template), and a strength
# that cites the figure neutrally ("Runway: 22 months is stated") is common enough that a refusal
# would stop runs nothing is wrong with. A hit is a strength on the stated figure's own slide that
# writes its numerals; spelled small numbers do not count ("two founders" is not "2 customers").
def contradicted_strengths(data: dict[str, Any], recon: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    """Where each strength citing a contradicted stated figure is. Pure: reads nothing from disk."""
    import ocr_check

    by_id = {
        str(f.get("id")): f for f in ledger.get("figures") or [] if isinstance(f, dict) and f.get("id") is not None
    }
    stated: dict[int, list[str]] = {}
    for rel in recon.get("relations") or []:
        if not isinstance(rel, dict) or rel.get("verdict") != "contradiction":
            continue
        fig = by_id.get(str(rel.get("expected_id")))
        if fig and isinstance(fig.get("slide"), int) and isinstance(fig.get("raw"), str):
            stated.setdefault(fig["slide"], []).append(fig["raw"])
    out: list[str] = []
    for review in data.get("reviews") or []:
        if not isinstance(review, dict) or review.get("slide_number") not in stated:
            continue
        for i, text in enumerate(review.get("strengths") or []):
            if isinstance(text, str) and any(
                ocr_check.found(raw, text, allow_spelled=False) for raw in stated[review["slide_number"]]
            ):
                out.append(f"slide {review['slide_number']} strengths[{i}]")
    return out


# ---------------------------------------------------------------------------
# READ TOKEN: proof that Step 5's grader opened this file.
#
# The CHECKLIST grader copies `metadata.read_token` into its hand-off, and `checklist.py
# --slide-reviews` refuses a grade whose echo differs. The token exists only in this file, so a
# grader whose Read failed cannot produce it, and the grader has no shell to derive it. Derived from
# the content and the run id, not drawn at random: re-piping the same reviews yields the same token,
# so a repeat pipe never stales a correct checklist, and compose uses it as the staleness key. Any
# token a hand-off carries is overwritten, and the receipt never prints it.
# ---------------------------------------------------------------------------

READ_TOKEN_HEX = 12


def read_token(run_id: str, data: dict[str, Any]) -> str:
    """First 12 hex chars of sha256(run_id, a newline, the body without `metadata` as canonical JSON)."""
    body = {k: v for k, v in data.items() if k != "metadata"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{run_id}\n{canonical}".encode()).hexdigest()[:READ_TOKEN_HEX]


def main() -> int:
    p = argparse.ArgumentParser(description="Producer for slide_reviews.json")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--reconciliation",
        required=True,
        help="reconciliation.json for this run; the numeric chain must have run before slide reviews",
    )
    p.add_argument("--deck-text", required=True, help="deck_text.md; its body hash is stamped into metadata")
    p.add_argument("--ledger", required=True, help="ledger.json: with the deck text, decides whether Step 3.95 ran")
    p.add_argument("--ocr-check", help="ocr_check.json, required when a figure the numbers use is on an image slide")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    import _out_guard

    _out_guard.refuse_output_onto_input([args.output], script="slide_reviews.py")
    # In a folder that belongs to a run: only that folder's current run, reading only its own files.
    import _run_ref

    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)) if args.output else None,
        args.run_id,
        [args.reconciliation, args.deck_text, args.ledger],
        noun="review dir",
    )

    gate_error, recon = _check_reconciliation(args.reconciliation, args.run_id)
    if gate_error:
        print(f"Error: {gate_error}", file=sys.stderr)
        return 1

    deck_text_sha256: str | None = None
    if args.deck_text:
        deck_text_sha256, problem = _deck_text_file.stamp(args.deck_text, args.run_id)
        if problem is not None:
            return _reject(problem["code"], problem["message"])
    ocr_problem = _check_ocr(args.ledger, args.deck_text, args.reconciliation, args.ocr_check, recon, args.run_id)
    if ocr_problem is not None:
        return _reject(*ocr_problem)

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

    meta = data.get("metadata")
    meta = (
        {k: v for k, v in meta.items() if k not in ("read_token", "deck_text_sha256")} if isinstance(meta, dict) else {}
    )
    meta["read_token"] = read_token(args.run_id, data)
    if deck_text_sha256 is not None:
        meta["deck_text_sha256"] = deck_text_sha256
    data = {**data, "metadata": meta}

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
    # Warn-only as well, and never allowed to fail the pipe: the artifact is already written.
    try:
        with open(args.ledger, encoding="utf-8") as fh:
            ledger = json.load(fh)
        praised = contradicted_strengths(data, recon or {}, ledger if isinstance(ledger, dict) else {})
    except Exception as exc:  # noqa: BLE001 -- a warning that cannot be computed is no warning
        print(f"Warning: contradicted_strengths: not checked ({type(exc).__name__})", file=sys.stderr)
    else:
        for where in praised:
            print(
                f"Warning: contradicted_strengths: {where} praises a figure reconciliation.json shows "
                "the deck got wrong; say on that slide what the numbers found",
                file=sys.stderr,
            )
        receipt["contradicted_strengths"] = {"hits": len(praised)}
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
