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
from datetime import datetime, timezone
from typing import Any

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact

# Optional fields typed bare `"string"` in the schema, so `null` is a TYPE ERROR while omission
# is fine. That distinction is invisible to the sub-agent producing this payload -- "the deck
# states no ask" is naturally written `claimed_raise: null`, and it failed the producer with
# "expected ['string'], got NoneType", costing a round-trip. `claimed_stage` in the same schema is
# `["string", "null"]`, so one schema taught both spellings at once.
#
# Normalized here rather than loosened in the schema: the schema stays strict for every other
# reader, and no downstream consumer has to learn null-vs-absent. Note the same shape exists in
# cap-table (`jurisdiction.incorporated_date`, `common_batches[].issuance_date` are optional and
# bare `"string"`), so this is a class, not a one-off -- survey before calling it settled.
_NULLABLE_AS_ABSENT = ("claimed_raise", "ai_evidence", "prior_rounds")
_NULLABLE_AS_ABSENT_PER_SLIDE = ("visuals", "word_count_estimate", "visual_evidence_captured")


def _drop_nulls_from_optional_fields(data: dict[str, Any]) -> None:
    """Treat an explicit `null` on an optional string field as absence. Mutates in place."""
    for field in _NULLABLE_AS_ABSENT:
        if data.get(field, "") is None:
            del data[field]
    # `prior_rounds`: an empty list is absence too; a round keeps only `stage` and `year` (nothing else is
    # shown, and an amount or a note stored here would read as checked); a year written as a string ("2023")
    # is the same fact, normalised like a null rather than loosened in the schema.
    rounds = data.get("prior_rounds")
    if rounds == []:
        del data["prior_rounds"]
    elif isinstance(rounds, list):
        for r in rounds:
            if isinstance(r, dict):
                for key in [k for k in r if k not in ("stage", "year")]:
                    del r[key]
                year = r.get("year", 0)
                if year is None:
                    del r["year"]
                elif isinstance(year, str) and year.strip().isdigit() and len(year.strip()) == 4:
                    r["year"] = int(year.strip())
    slides = data.get("slides")
    if isinstance(slides, list):
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            for field in _NULLABLE_AS_ABSENT_PER_SLIDE:
                if slide.get(field, "") is None:
                    del slide[field]


PRIOR_ROUND_FIRST_YEAR = 1990


def _prior_round_year_errors(data: dict[str, Any]) -> list[str]:
    """A round's year must be one the founder could have closed: 1990 through next year. The schema validator
    ignores `minimum`/`maximum`, so the bound lives here, checked before anything is written."""
    last = datetime.now(timezone.utc).year + 1
    errors = []
    rounds = data.get("prior_rounds")
    for i, r in enumerate(rounds if isinstance(rounds, list) else []):
        year = r.get("year") if isinstance(r, dict) else None
        if isinstance(year, int) and not isinstance(year, bool) and not PRIOR_ROUND_FIRST_YEAR <= year <= last:
            errors.append(
                f"prior_rounds[{i}].year: {year} is not a year a round closed in "
                f"({PRIOR_ROUND_FIRST_YEAR}-{last}); omit it when the deck does not say"
            )
    return errors


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

    _drop_nulls_from_optional_fields(data)

    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references",
        "schemas",
        "deck_inventory.schema.json",
    )
    schema = load_schema(schema_path)

    year_errors = _prior_round_year_errors(data)
    if year_errors:
        print(f"Error: deck_inventory validation failed: {'; '.join(year_errors)}", file=sys.stderr)
        return 1

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
