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
import sys

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


def _check_reconciliation(path: str, run_id: str) -> str | None:
    """Gate the numeric-reconciliation chain. Returns an error message, or None.

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
    company satisfies an absence check while the whole chain was skipped this run, and in
    Cowork the cleanup delete that would prevent that is denied and deliberately
    tolerated.
    """
    if not os.path.exists(path):
        return f"reconciliation artifact not found at {path} — run the ledger chain (Steps 3.5-3.8) before this step"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return f"reconciliation artifact at {path} is unreadable: {exc}"
    if not isinstance(data, dict):
        return f"reconciliation artifact at {path} is not a JSON object"
    found = (data.get("metadata") or {}).get("run_id")
    if found != run_id:
        return (
            f"reconciliation artifact at {path} belongs to run {found!r}, not {run_id!r} — "
            "it is left over from an earlier review and says nothing about this deck"
        )
    if not data.get("status"):
        return f"reconciliation artifact at {path} carries no status"
    return None


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

    gate_error = _check_reconciliation(args.reconciliation, args.run_id)
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

    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
