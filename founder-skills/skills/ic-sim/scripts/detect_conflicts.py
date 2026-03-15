#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Conflict check validator for IC simulation.

Role: validator, not detector. The agent (LLM) determines conflicts using its
judgment about market adjacency, customer overlap, etc. This script validates
the structure and computes summary stats.

Always reads JSON from stdin.

Usage:
    echo '{"portfolio_size": 15, "conflicts": [...]}' \
        | python detect_conflicts.py --pretty

Output: JSON with validated input + computed summary + validation.status/errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


def _normalize_company(name: str) -> str:
    """Normalize company name: strip legal suffixes, lowercase, collapse whitespace."""
    name = name.strip().lower()
    for suffix in (" inc.", " inc", " llc", " ltd.", " ltd", " corp.", " corp"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"\s+", " ", name).strip()


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


VALID_TYPES = {"direct", "adjacent", "customer_overlap"}
VALID_SEVERITIES = {"blocking", "manageable"}


def validate_conflicts(data: dict[str, Any]) -> dict[str, Any]:
    """Validate conflict check input and compute summary."""
    errors: list[str] = []

    # Required fields
    if "portfolio_size" not in data:
        errors.append("Missing required field: portfolio_size")
    if "conflicts" not in data:
        errors.append("Missing required field: conflicts")

    portfolio_size = data.get("portfolio_size", 0)
    if isinstance(portfolio_size, float) and portfolio_size == int(portfolio_size):
        portfolio_size = int(portfolio_size)
    if not isinstance(portfolio_size, int) or portfolio_size < 0:
        errors.append(f"portfolio_size must be a non-negative integer, got {portfolio_size!r}")
        portfolio_size = 0

    conflicts = data.get("conflicts", [])
    if not isinstance(conflicts, list):
        errors.append("conflicts must be an array")
        conflicts = []

    # Deduplicate conflicts by normalized (company, type) pair
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            deduped.append(conflict)  # let validation catch non-dict
            continue
        company = _normalize_company(conflict.get("company") or "")
        ctype = (conflict.get("type") or "").strip().lower()
        key = (company, ctype)
        if company and key in seen_keys:
            print(
                f"Warning: duplicate conflict for '{conflict.get('company')}'"
                f" (type: {ctype}) — keeping first occurrence",
                file=sys.stderr,
            )
            continue
        if company:
            seen_keys.add(key)
        deduped.append(conflict)
    conflicts = deduped
    data["conflicts"] = conflicts

    # Validate each conflict entry
    has_blocking = False
    for i, conflict in enumerate(conflicts):
        if not isinstance(conflict, dict):
            errors.append(f"Conflict {i} must be an object")
            continue

        # Required fields per conflict
        for field in ["company", "type", "severity", "rationale"]:
            if not conflict.get(field):
                errors.append(f"Conflict {i}: missing required field '{field}'")

        # Type enum
        ctype = conflict.get("type", "")
        if ctype not in VALID_TYPES:
            errors.append(f"Conflict {i}: invalid type '{ctype}'. Must be one of: {sorted(VALID_TYPES)}")

        # Severity enum
        severity = conflict.get("severity", "")
        if severity not in VALID_SEVERITIES:
            errors.append(f"Conflict {i}: invalid severity '{severity}'. Must be one of: {sorted(VALID_SEVERITIES)}")

        if severity == "blocking":
            has_blocking = True

    # portfolio_size must be >= len(conflicts)
    if isinstance(portfolio_size, int) and portfolio_size < len(conflicts):
        errors.append(f"portfolio_size ({portfolio_size}) must be >= number of conflicts ({len(conflicts)})")

    status = "valid" if not errors else "invalid"

    result = dict(data)
    if errors:
        result["summary"] = None
        result["validation"] = {"status": status, "errors": errors}
        return result

    # Compute summary (only reached when valid)
    conflict_count = len(conflicts)
    if has_blocking:
        overall_severity = "blocking"
    elif conflict_count > 0:
        overall_severity = "manageable"
    else:
        overall_severity = "clear"

    summary = {
        "total_checked": portfolio_size,
        "conflict_count": conflict_count,
        "has_blocking_conflict": has_blocking,
        "overall_severity": overall_severity,
    }

    result["summary"] = summary
    result["validation"] = {"status": status, "errors": errors}
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Conflict check validator (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            'Example: echo \'{"portfolio_size": 15, "conflicts": [...]}\' | python detect_conflicts.py --pretty',
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

    result = validate_conflicts(data)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    sm = result.get("summary")
    _write_output(
        out,
        args.output,
        summary={
            "validation": result["validation"]["status"],
            **({"conflicts": sm["conflict_count"]} if sm else {}),
        },
    )


if __name__ == "__main__":
    main()
