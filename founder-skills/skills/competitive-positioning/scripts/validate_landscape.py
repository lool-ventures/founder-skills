#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Validate and normalize competitor landscape.

Takes landscape_enriched.json (from stdin) and produces a validated,
normalized landscape.json. Validates structure, checks slug uniqueness,
preserves provenance fields, and emits warnings for quality issues.

Usage:
    echo '{"competitors": [...], ...}' | python validate_landscape.py --pretty
    echo '{"competitors": [...], ...}' | python validate_landscape.py -o landscape.json

Output: JSON with validated competitor list, warnings, and metadata.
Exit codes: 0 = success (may include warnings), 1 = validation error.
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
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"direct", "adjacent", "do_nothing", "emerging", "custom"}
VALID_RESEARCH_DEPTHS = {"full", "partial", "founder_provided"}
REQUIRED_COMPETITOR_FIELDS = {"name", "slug", "category", "description", "key_differentiators"}
PROVENANCE_FIELDS = {"research_depth", "evidence_source", "sourced_fields_count"}
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Hard structural floor. The checklist (COVER_01) sets the investor bar at 5+
# and fails below 4. This validator ensures a minimum viable landscape;
# the checklist evaluates whether it meets investor expectations.
MIN_COMPETITORS = 3
MAX_COMPETITORS = 10
RESERVED_SLUGS = {"_startup"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_landscape(enriched: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate landscape_enriched.json and return (output, errors).

    Returns (output_dict, []) on success, (None, error_list) on failure.
    """
    errors: list[str] = []
    warnings: list[dict[str, Any]] = []

    # Top-level structure
    competitors_raw = enriched.get("competitors")
    if not isinstance(competitors_raw, list):
        return None, ["'competitors' must be an array"]

    # Bounds check
    n = len(competitors_raw)
    if n < MIN_COMPETITORS:
        errors.append(f"Minimum {MIN_COMPETITORS} competitors required, got {n}")
    if n > MAX_COMPETITORS:
        errors.append(f"Maximum {MAX_COMPETITORS} competitors allowed, got {n}")

    # Per-competitor validation
    slugs_seen: set[str] = set()
    validated_competitors: list[dict[str, Any]] = []
    has_do_nothing = False
    has_adjacent = False

    for i, comp in enumerate(competitors_raw):
        if not isinstance(comp, dict):
            errors.append(f"Competitor {i}: must be an object")
            continue

        # Required fields
        for field in REQUIRED_COMPETITOR_FIELDS:
            if field not in comp:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): missing required field '{field}'")

        # Slug validation — auto-convert underscores to hyphens for kebab-case
        slug = comp.get("slug", "")
        if not slug:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug must be non-empty")
        else:
            # Auto-fix: convert underscores to hyphens (common agent mistake)
            if "_" in slug and slug not in RESERVED_SLUGS:
                original = slug
                slug = slug.replace("_", "-")
                comp["slug"] = slug  # fix in-place so output gets corrected slug
                print(f"Note: auto-converted slug '{original}' -> '{slug}'", file=sys.stderr)
            if slug in RESERVED_SLUGS:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug '{slug}' is reserved")
            elif not KEBAB_CASE_RE.match(slug):
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug '{slug}' must be kebab-case")
        if slug and slug not in RESERVED_SLUGS:
            if slug in slugs_seen:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): duplicate slug '{slug}'")
            slugs_seen.add(slug)

        # Category validation
        category = comp.get("category", "")
        if not category:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): category must be non-empty")
        elif category not in VALID_CATEGORIES:
            errors.append(
                f"Competitor {i} ({comp.get('name', '?')}): invalid category '{category}'. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )
        if category == "do_nothing":
            has_do_nothing = True
        if category == "adjacent":
            has_adjacent = True

        # key_differentiators must be a non-empty list (null is not valid)
        kd = comp.get("key_differentiators")
        if not isinstance(kd, list) or len(kd) == 0:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): key_differentiators must be a non-empty array")

        # Build validated competitor entry (only output fields)
        validated_comp: dict[str, Any] = {}
        for field in ("name", "slug", "category", "description", "key_differentiators"):
            if field in comp:
                validated_comp[field] = comp[field]

        # Preserve provenance fields
        for field in PROVENANCE_FIELDS:
            if field in comp:
                validated_comp[field] = comp[field]

        # Validate research_depth enum if present
        rd = validated_comp.get("research_depth")
        if rd is not None and rd not in VALID_RESEARCH_DEPTHS:
            errors.append(
                f"Competitor {i} ({comp.get('name', '?')}): research_depth '{rd}' "
                f"must be one of {sorted(VALID_RESEARCH_DEPTHS)}"
            )

        validated_competitors.append(validated_comp)

    # Bail on errors
    if errors:
        return None, errors

    # Quality warnings (non-blocking)
    if not has_do_nothing and not has_adjacent:
        warnings.append(
            {
                "code": "MISSING_DO_NOTHING",
                "severity": "medium",
                "message": "No competitor with category 'do_nothing' or 'adjacent' found. "
                "Consider adding a status-quo alternative.",
            }
        )

    # Metadata passthrough
    metadata = enriched.get("metadata", {})
    input_mode = enriched.get("input_mode", "conversation")

    output: dict[str, Any] = {
        "competitors": validated_competitors,
        "input_mode": input_mode,
        "warnings": warnings,
        "_produced_by": "validate_landscape",
        "metadata": metadata,
    }

    # Optional passthroughs
    if "research_depth" in enriched:
        output["research_depth"] = enriched["research_depth"]
    if "assessment_mode" in enriched:
        output["assessment_mode"] = enriched["assessment_mode"]
    if "data_confidence" in enriched:
        output["data_confidence"] = enriched["data_confidence"]

    return output, []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate competitor landscape (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--stdin", action="store_true", default=True, help="Read from stdin (default)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: cat landscape_enriched.json | python validate_landscape.py --pretty",
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

    result, errors = validate_landscape(data)

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    assert result is not None

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"

    warning_count = len(result.get("warnings", []))
    _write_output(
        out,
        args.output,
        summary={"warning_count": warning_count, "competitor_count": len(result["competitors"])},
    )


if __name__ == "__main__":
    main()
