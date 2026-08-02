#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer for deck_inventory.json.

Reads JSON from stdin, validates against deck_inventory.schema.json,
injects metadata.run_id, writes to --output (-o), prints a receipt.

Replaces the heredoc pattern in SKILL.md Step 2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


def main() -> int:
    p = argparse.ArgumentParser(description="Producer for deck_inventory.json")
    p.add_argument("--run-id", required=True, help="Run identifier injected into metadata")
    p.add_argument("-o", "--output", required=True, help="Output path")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = p.parse_args()

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print(f"Error: stdin must be a JSON object, got {type(data).__name__}", file=sys.stderr)
        return 1

    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references",
        "schemas",
        "deck_inventory.schema.json",
    )
    schema = load_schema(schema_path)

    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        print(f"Error: deck_inventory validation failed: {e}", file=sys.stderr)
        return 1

    # Non-fatal integrity notes on slide numbering. Duplicates are usually a real
    # defect in the source deck (worth surfacing to the founder), so the inventory
    # still records them honestly; the warning tells the main thread to double-check
    # the extraction and disambiguate slide references downstream. Malformed number
    # types are the schema's job, so only int values are inspected here.
    numbers = [s["number"] for s in data.get("slides", []) if isinstance(s.get("number"), int)]
    slide_warnings: list[str] = []
    seen: set[int] = set()
    dupes: list[int] = []
    for n in numbers:
        if n in seen and n not in dupes:
            dupes.append(n)
        seen.add(n)
    if dupes:
        dupes_str = ", ".join(str(n) for n in dupes)
        slide_warnings.append(f"duplicate slide number(s): {dupes_str}")
        print(f"Warning: duplicate slide number(s): {dupes_str}", file=sys.stderr)
    unique_sorted = sorted(seen)
    if unique_sorted and unique_sorted != list(range(unique_sorted[0], unique_sorted[-1] + 1)):
        seq_str = ", ".join(str(n) for n in unique_sorted)
        slide_warnings.append(f"non-sequential slide numbers: {seq_str}")
        print(f"Warning: non-sequential slide numbers: {seq_str}", file=sys.stderr)
    if slide_warnings:
        receipt["warnings"] = slide_warnings

    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
