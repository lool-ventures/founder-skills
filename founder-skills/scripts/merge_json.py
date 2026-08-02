#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Shallow-merge JSON object files for producer pipes (branch C hand-off).

When a step's producer consumes the union of several sub-agent hand-off
files (e.g. market-sizing "both": top-down + bottom-up), the main thread
must NOT re-type values into a heredoc — that is the LLM re-emission
hazard the file hand-off exists to remove. This script merges the files
deterministically and prints the result to stdout for the producer pipe.

Usage:
    python merge_json.py a.json b.json [--set key=value ...] [--pretty]

Semantics:
    - Each input file must contain a JSON object; merged left-to-right
      (later files win on key collisions).
    - --set key=value forces a top-level string value AFTER the merge
      (e.g. --set approach=both). Repeatable.
    - Output goes to stdout (pipe it into the producer's --stdin).
"""

from __future__ import annotations

import argparse
import json
import sys


def merge_objects(objects: list[dict[str, object]]) -> dict[str, object]:
    merged: dict[str, object] = {}
    for obj in objects:
        merged.update(obj)
    return merged


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Shallow-merge JSON object files to stdout")
    p.add_argument("files", nargs="+", help="JSON object files, merged left-to-right (later wins)")
    p.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Force a top-level string value after the merge (repeatable)",
    )
    p.add_argument("--pretty", action="store_true", help="Indent the output")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    objects: list[dict[str, object]] = []
    for path in args.files:
        try:
            with open(path, encoding="utf-8-sig") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"merge_json: cannot read {path}: {exc}\n")
            return 1
        if not isinstance(loaded, dict):
            sys.stderr.write(f"merge_json: {path} is not a JSON object\n")
            return 1
        objects.append(loaded)

    merged = merge_objects(objects)

    for override in args.overrides:
        key, sep, value = override.partition("=")
        if not sep or not key:
            sys.stderr.write(f"merge_json: --set expects KEY=VALUE, got {override!r}\n")
            return 1
        merged[key] = value

    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(merged, indent=indent) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
