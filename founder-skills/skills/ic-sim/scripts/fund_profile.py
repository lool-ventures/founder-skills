#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Fund profile validator for IC simulation.

Validates fund profile structure: exactly 3 archetypes, valid check_size_range,
at least 1 thesis area, sources required for fund-specific mode, portfolio
array present with name fields.

Always reads JSON from stdin.

Usage:
    echo '{"fund_name": "...", "mode": "generic", ...}' \
        | python fund_profile.py --pretty

Output: JSON with validated profile including validation.status and validation.errors.
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


VALID_ROLES = {"visionary", "operator", "analyst"}
VALID_MODES = {"generic", "fund_specific"}


def validate_fund_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate fund profile and return enriched profile with validation results."""
    errors: list[str] = []

    # Required top-level fields
    for field in ["fund_name", "mode", "thesis_areas", "check_size_range", "stage_focus", "archetypes", "portfolio"]:
        if field not in profile:
            errors.append(f"Missing required field: {field}")

    # Mode validation
    mode = profile.get("mode", "")
    if mode not in VALID_MODES:
        errors.append(f"Invalid mode '{mode}'. Must be one of: {sorted(VALID_MODES)}")

    # Thesis areas: at least 1
    thesis = profile.get("thesis_areas", [])
    if not isinstance(thesis, list):
        errors.append("thesis_areas must be an array")
    elif len(thesis) < 1:
        errors.append("thesis_areas must contain at least 1 area")

    # Stage focus: must be non-empty list
    stage_focus = profile.get("stage_focus", [])
    if not isinstance(stage_focus, list) or len(stage_focus) < 1:
        errors.append("stage_focus must be a non-empty array")

    # Check size range validation
    check_size = profile.get("check_size_range", {})
    if isinstance(check_size, dict):
        min_size = check_size.get("min")
        max_size = check_size.get("max")
        if min_size is not None and max_size is not None:
            try:
                min_val = float(min_size)
                max_val = float(max_size)
                if min_val < 0:
                    errors.append(f"check_size_range.min must be non-negative, got {min_val}")
                if max_val < 0:
                    errors.append(f"check_size_range.max must be non-negative, got {max_val}")
                if min_val > max_val:
                    errors.append(f"check_size_range.min ({min_val}) must be <= max ({max_val})")
            except (TypeError, ValueError):
                errors.append("check_size_range.min and max must be numbers")
        else:
            if min_size is None:
                errors.append("check_size_range missing 'min' field")
            if max_size is None:
                errors.append("check_size_range missing 'max' field")
    else:
        errors.append(f"check_size_range must be an object (got {type(check_size).__name__})")

    # Archetypes: exactly 3, each with valid role
    archetypes = profile.get("archetypes", [])
    if not isinstance(archetypes, list):
        errors.append("archetypes must be an array")
    else:
        if len(archetypes) != 3:
            errors.append(f"Must have exactly 3 archetypes, got {len(archetypes)}")
        roles_seen: set[str] = set()
        for i, arch in enumerate(archetypes):
            if not isinstance(arch, dict):
                errors.append(f"Archetype {i} must be an object")
                continue
            role = arch.get("role", "")
            if role not in VALID_ROLES:
                errors.append(f"Archetype {i}: invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}")
            elif role in roles_seen:
                errors.append(f"Archetype {i}: duplicate role '{role}'")
            else:
                roles_seen.add(role)
            if not arch.get("name"):
                errors.append(f"Archetype {i}: missing 'name' field")

    # Portfolio: must be array, each entry must have 'name'
    portfolio = profile.get("portfolio", [])
    if not isinstance(portfolio, list):
        errors.append("portfolio must be an array")
    else:
        for i, entry in enumerate(portfolio):
            if not isinstance(entry, dict):
                errors.append(f"Portfolio entry {i} must be an object")
            elif not entry.get("name"):
                errors.append(f"Portfolio entry {i}: missing 'name' field")

    # Sources required for fund-specific mode
    if mode == "fund_specific":
        sources = profile.get("sources", [])
        if not isinstance(sources, list) or len(sources) == 0:
            errors.append("sources required for fund_specific mode (at least 1)")
        elif isinstance(sources, list):
            for i, source in enumerate(sources):
                if not isinstance(source, dict):
                    errors.append(f"Source {i} must be an object")
                elif not source.get("url") and not source.get("title"):
                    errors.append(f"Source {i} must have at least 'url' or 'title'")

    status = "valid" if not errors else "invalid"

    result = dict(profile)
    result["validation"] = {"status": status, "errors": errors}
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fund profile validator (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            'Example: echo \'{"fund_name": "...", ...}\' | python fund_profile.py --pretty',
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

    result = validate_fund_profile(data)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"validation": result["validation"]["status"]},
    )


if __name__ == "__main__":
    main()
