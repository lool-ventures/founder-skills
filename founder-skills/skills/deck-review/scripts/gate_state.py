#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer + answer-writer for gate_state.json.

Two subcommands:

  emit    — read gate body from stdin (gate_id, question, options, context_summary),
            schema-validate, inject metadata.run_id, write to -o, print receipt.
  answer  — read existing gate_state.json, set `answer` (validated against options),
            re-validate, write back.

Used by SKILL.md to keep gate state on disk and out of model-message drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


def _schema_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references",
        "schemas",
        "gate_state.schema.json",
    )


def cmd_emit(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("Error: stdin must be a JSON object", file=sys.stderr)
        return 1

    schema = load_schema(_schema_path())
    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        print(f"Error: gate_state validation failed: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.file):
        print(f"Error: gate_state file not found: {args.file}", file=sys.stderr)
        return 1
    try:
        with open(args.file, encoding="utf-8") as f:
            gate = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: gate_state file is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(gate, dict):
        print("Error: gate_state file must contain a JSON object", file=sys.stderr)
        return 1

    options = gate.get("options", [])
    if args.answer not in options:
        print(
            f"Error: answer {args.answer!r} is not in options {options!r}",
            file=sys.stderr,
        )
        return 1

    gate["answer"] = args.answer

    pretty = getattr(args, "pretty", True)
    schema = load_schema(_schema_path())
    try:
        receipt = write_artifact(
            data=gate,
            schema=schema,
            run_id=gate.get("metadata", {}).get("run_id", ""),
            output_path=args.file,
            pretty=pretty,
        )
    except ArtifactValidationError as e:
        print(f"Error: gate_state validation failed after answer: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="gate_state.json producer and answer-writer")
    sub = p.add_subparsers(dest="command", required=True)

    sp_emit = sub.add_parser("emit", help="Write a fresh gate_state.json from stdin body")
    sp_emit.add_argument("--run-id", required=True)
    sp_emit.add_argument("-o", "--output", required=True)
    sp_emit.add_argument("--pretty", action="store_true")
    sp_emit.set_defaults(func=cmd_emit)

    sp_ans = sub.add_parser("answer", help="Set the founder's answer on an existing gate_state.json")
    sp_ans.add_argument("--file", required=True)
    sp_ans.add_argument("--answer", required=True)
    sp_ans.add_argument("--pretty", action="store_true", help="Pretty-print the artifact JSON")
    sp_ans.set_defaults(func=cmd_answer)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
