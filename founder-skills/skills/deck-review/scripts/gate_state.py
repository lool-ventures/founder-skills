#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer + answer-writer for gate_state.json.

Two subcommands:

  emit    — read gate body from stdin (gate_id, question, options, context_summary),
            schema-validate, inject metadata.run_id, write to -o, print receipt.
  answer  — read existing gate_state.json, set `answer` (validated against options) and
            `answer_source` (required), re-validate, write back.

Used by SKILL.md to keep gate state on disk and out of model-message drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact

FOUNDER, AUTO_SATISFIED = "founder", "auto_satisfied"
ANSWER_SOURCES = (FOUNDER, AUTO_SATISFIED)

# Auto-satisfy is scoped to the one gate and the one answer it has a rationale for; see
# the enforcement in `cmd_answer` for why the other two gate_ids are excluded.
AUTO_SATISFIABLE_GATE = "stage_confirmation"
AUTO_SATISFIABLE_ANSWER = "Looks right"


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

    # AN EMIT WRITES A GATE TO BE ASKED, so a gate that already carries an answer is not
    # one. The schema makes `answer`/`answer_source` optional (a pending gate has neither
    # and an old artifact may lack the source), which left `emit` accepting both — and the
    # auto-satisfy restriction below lives in `cmd_answer`, so it was routable around
    # entirely. Measured: emitting an `out_of_scope_choice` already answered "Proceed
    # anyway (best-effort)" with `answer_source: auto_satisfied` succeeded, and
    # `setup_run.py` then reported `resume: true`. The deck proceeds, self-authorised, on
    # the one answer a founder most needs to give themselves.
    #
    # Enforced here rather than in the schema because the schema is shared with the
    # post-answer artifact, where both fields are legitimate.
    for field in ("answer", "answer_source"):
        if field in data:
            print(
                f"Error: emit writes a gate to be ASKED and must not carry {field!r} — "
                f"set it with `gate_state.py answer`, which is where the rules on it are enforced",
                file=sys.stderr,
            )
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

    # Run-id parity: if a --run-id was supplied, refuse to answer a gate from a different run (matches the
    # skill's resume-parity rule — never answer a stale gate left by a prior completed run).
    gate_run_id = gate.get("metadata", {}).get("run_id", "")
    if getattr(args, "run_id", None) and gate_run_id and args.run_id != gate_run_id:
        print(
            f"Error: --run-id {args.run_id!r} does not match gate_state metadata.run_id {gate_run_id!r} "
            "(refusing to answer a gate from a different run)",
            file=sys.stderr,
        )
        return 1

    options = gate.get("options", [])
    if args.answer not in options:
        print(
            f"Error: answer {args.answer!r} is not in options {options!r}",
            file=sys.stderr,
        )
        return 1

    # WHERE THE ANSWER CAME FROM. A live run had the gate self-answer "Looks right" with no
    # founder input, and nothing downstream could tell that apart from a real answer — once
    # written the two artifacts are byte-identical.
    #
    # This is OBSERVABILITY, NOT PROVENANCE. The flag is supplied by the same model that
    # would self-answer, so it cannot prove a founder spoke; real provenance needs a host
    # event this architecture does not expose. What it buys is that the auto-satisfy path
    # has to state itself, and an answer written by some other path states nothing — which
    # `setup_run.py` reads as unauditable and re-asks.
    #
    # Required rather than defaulted, in both directions. Defaulting to `founder` mints
    # false provenance for exactly the case this exists to expose; defaulting to nothing
    # leaves the artifact as ambiguous as before. Omitting the flag writes nothing at all,
    # so the failure mode is a re-ask, not a wrong record.
    if args.source == AUTO_SATISFIED:
        # Auto-satisfy has ONE rationale: the founder named the stage in Step 1 and
        # detection agrees, so re-asking reads as not listening. That rationale covers
        # exactly one gate and one answer on it. The schema admits two other gate_ids, and
        # without this restriction the model could self-record "Proceed anyway
        # (best-effort)" on a deck it has just judged out of scope — the single answer a
        # founder most needs to give themselves.
        if gate.get("gate_id") != AUTO_SATISFIABLE_GATE:
            print(
                f"Error: --source auto_satisfied is only valid on the {AUTO_SATISFIABLE_GATE!r} gate, "
                f"not {gate.get('gate_id')!r} (that answer is the founder's to give)",
                file=sys.stderr,
            )
            return 1
        if args.answer != AUTO_SATISFIABLE_ANSWER:
            print(
                f"Error: --source auto_satisfied is only valid for the answer {AUTO_SATISFIABLE_ANSWER!r}, "
                f"not {args.answer!r} (any other option is a decision the founder has not made)",
                file=sys.stderr,
            )
            return 1

    gate["answer"] = args.answer
    gate["answer_source"] = args.source

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
    # Accept `-o`/`--output` as aliases for `--file`: the model naturally copies `emit`'s `-o` flag onto
    # `answer`. And accept `--run-id` (used for a parity check below) — it is likewise carried over from
    # `emit`. Without these, an `answer -o <path> --run-id <id>` invocation errored (argparse exit 2).
    sp_ans.add_argument("--file", "-o", dest="file", required=True)
    sp_ans.add_argument("--answer", required=True)
    sp_ans.add_argument("--run-id", dest="run_id", default=None, help="If given, must match the gate's metadata.run_id")
    sp_ans.add_argument(
        "--source",
        required=True,
        choices=ANSWER_SOURCES,
        help="Who produced this answer: 'founder' (they were asked and replied) or "
        "'auto_satisfied' (Step 1 already captured a matching stage, so the gate was not put to them)",
    )
    sp_ans.add_argument("--pretty", action="store_true", help="Pretty-print the artifact JSON")
    sp_ans.set_defaults(func=cmd_answer)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
