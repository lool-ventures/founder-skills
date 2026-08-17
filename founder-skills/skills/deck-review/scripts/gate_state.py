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


def _read_existing(path: str) -> object:
    """The gate already on disk, or None. Unreadable is treated as absent: this feeds the
    history carry-forward, and refusing to emit because an old file is corrupt would strand
    the run with no way to ask the question again."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _as_run_id(gate: dict[str, object]) -> object:
    meta = gate.get("metadata")
    return meta.get("run_id") if isinstance(meta, dict) else None


def validate_answered_gate(gate: object) -> list[str]:
    """Every rule an ANSWERED gate must satisfy, in one place, for all three readers.

    THE SHARED VALIDATOR EXISTS BECAUSE THE RULES KEPT BEING ENFORCED AT ONE READER. The
    auto-satisfy restriction lived only in `cmd_answer` and was reachable through `emit`;
    once that was closed, `setup_run.py` and `compose_report.py` still accepted anything
    that parsed as a JSON object, so a gate that was never answered at all -- the founder
    asked, no reply -- composed cleanly with the stage presented as settled. Three readers,
    one rule set, and the rule set is here.

    Returns a list of human-readable problems; empty means the gate is a legitimate
    answered state. Callers decide severity: `answer` refuses at write time, `setup_run`
    declines to resume, `compose_report` refuses to compose.

    A PENDING gate is not an error and is not this function's business -- ask
    `is_answered()` first. This validates the answered state only.
    """
    problems: list[str] = []
    if not isinstance(gate, dict):
        return ["gate_state is not a JSON object"]

    # The record's own required fields, not just its answer. A gate missing `gate_id` is
    # not a smaller gate -- it is one `emit` could never have written, and `gate_id` is
    # exactly what the transition below depends on, so accepting it silently means
    # resolving an unknown gate's answer against no rule at all.
    for field in ("metadata", "gate_id", "question", "options", "context_summary"):
        if field not in gate:
            problems.append(f"gate_state is missing the required field {field!r}")
    if not isinstance(_as_run_id(gate), str) or not _as_run_id(gate):
        problems.append("gate_state has no metadata.run_id")

    answer = gate.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        problems.append("gate_state carries no answer: the gate was emitted and never answered")
        return problems

    options = gate.get("options")
    gate_id = str(gate.get("gate_id") or "")
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        problems.append("gate_state has no options array, so its answer cannot be checked against one")
    else:
        if answer not in options:
            problems.append(f"answer {answer!r} is not one of the gate's own options {options!r}")
        # And the options themselves must be the GATE's, not the emitter's -- see
        # CANONICAL_OPTIONS for why a caller-defined choice set is not consent.
        if gate_id in CANONICAL_OPTIONS:
            expected = CANONICAL_OPTIONS[gate_id]
            if tuple(options) != expected:
                problems.append(
                    f"{gate_id} was offered {options!r}, not its own options {list(expected)!r} — "
                    "the choices a gate presents are not the asker's to pick"
                )
        elif gate_id == "stage_choice":
            outside = [o for o in options if o not in STAGE_CHOICE_OPTIONS]
            if outside:
                problems.append(f"stage_choice offered {outside!r}, which are not stages")

    source = gate.get("answer_source")
    if source is None:
        problems.append("gate_state records no answer_source, so who answered it cannot be established")
    elif source not in ANSWER_SOURCES:
        problems.append(f"answer_source {source!r} is not one of {list(ANSWER_SOURCES)}")
    elif source == AUTO_SATISFIED:
        if gate.get("gate_id") != AUTO_SATISFIABLE_GATE:
            problems.append(
                f"answer_source auto_satisfied is only legal on the {AUTO_SATISFIABLE_GATE!r} gate, "
                f"not {gate.get('gate_id')!r}"
            )
        elif answer != AUTO_SATISFIABLE_ANSWER:
            problems.append(
                f"answer_source auto_satisfied is only legal for {AUTO_SATISFIABLE_ANSWER!r}, not {answer!r}"
            )
    return problems


def is_answered(gate: object) -> bool:
    """Has this gate been answered at all? Distinguishes pending from malformed."""
    return isinstance(gate, dict) and isinstance(gate.get("answer"), str) and bool(gate["answer"].strip())


# What each answer AUTHORIZES, from SKILL.md's own transition table. Kept beside the
# validator because the two questions kept being conflated: `validate_answered_gate` says
# a record is a well-formed ANSWER, which is not the same as saying that answer permits a
# report to be written. Three valid answered gates composed a clean report before this
# existed -- "Stop review" (the founder said do not), "Different stage" (a rebuild is owed
# first) and an intermediate `stage_choice` pick (re-confirmation is owed). The first of
# those produced a review for a founder who had asked for none.
# THE GATE'S OWN OPTIONS, not the caller's. Validation used to check the answer against
# whatever list the emitter supplied, which makes consent caller-defined: an
# `out_of_scope_choice` offering ONLY "Proceed anyway (best-effort)" validated and
# authorised a clean report, with "Stop review" simply never presented. A gate whose
# choices the asker picks is not a gate.
CANONICAL_OPTIONS: dict[str, tuple[str, ...]] = {
    "stage_confirmation": ("Looks right", "Different stage", "Not sure — proceed anyway"),
    "out_of_scope_choice": ("Stop review", "Different stage", "Proceed anyway (best-effort)"),
}

# `stage_choice` is the one gate whose options are chosen at RUN TIME -- four of the five
# stages, minus the one the founder just rejected -- so it cannot have a fixed list. It is
# held to the enum instead.
STAGE_CHOICE_OPTIONS: frozenset[str] = frozenset({"Pre-seed", "Seed", "Series A", "Series B", "Growth"})

# Answers that authorise the rest of the pipeline OUTRIGHT.
CONTINUE_ANSWERS: dict[str, frozenset[str]] = {
    "stage_confirmation": frozenset({"Looks right"}),
    "out_of_scope_choice": frozenset(),
    # `stage_choice` has NO continuing answer by construction: every pick rebuilds the
    # profile and re-emits `stage_confirmation`, so a stage_choice answer is always an
    # intermediate state.
    "stage_choice": frozenset(),
}

# Answers that continue ONLY IF the profile was first rebuilt at low confidence. SKILL.md
# requires that rebuild for both; calling them terminal authorised a report whose stage
# profile may never have been downgraded, so a founder who said "not sure" got a review
# graded as though they had confirmed. The rebuild is a checkable POSTCONDITION -- the
# profile's own confidence -- rather than something to take on trust; `compose_report.py`
# verifies it.
CONTINUE_IF_REBUILT_ANSWERS: frozenset[str] = frozenset({"Not sure — proceed anyway", "Proceed anyway (best-effort)"})

STOP_ANSWERS: frozenset[str] = frozenset({"Stop review"})

# Stages whose selection puts the deck out of scope. Confirming one of these through
# `stage_confirmation` skips the only gate that offers a way to decline.
OUT_OF_SCOPE_STAGES: frozenset[str] = frozenset({"Series B", "Growth"})


def gate_action(gate: object) -> str:
    """What this gate authorises: `continue` | `stop` | `rebuild` | `reask`.

    THE ONE PLACE THE TRANSITION IS DECIDED. Callers must not infer it from the answer
    string themselves -- that inference is what every reader was doing implicitly by
    treating "answered" as "may proceed".

      continue  a terminal answer that authorises the rest of the pipeline
      stop      the founder declined the review; nothing downstream should run
      rebuild   an intermediate answer; the profile is rebuilt and the gate re-emitted,
                so this run is not finished asking
      reask     unanswered, or an answered record that does not validate
    """
    # A STOP IN THIS RUN'S HISTORY OUTRANKS EVERYTHING, including a pending replacement.
    # Checked before the answered-ness test, because re-emitting after a decline leaves a
    # PENDING gate -- which read as "just ask again" rather than "they already said no".
    if isinstance(gate, dict):
        this_run = _as_run_id(gate)
        for entry in gate.get("history", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("answer") in STOP_ANSWERS and entry.get("run_id") == this_run:
                return "stop"
    if not is_answered(gate) or validate_answered_gate(gate):
        return "reask"
    assert isinstance(gate, dict)  # is_answered established this
    answer = str(gate.get("answer"))
    if answer in STOP_ANSWERS:
        return "stop"
    # A decline earlier in THIS run is still a decline. See the carry-forward in `emit`:
    # without this the history would be recorded and ignored, which is worse than not
    # recording it — an audit trail nothing consults reads as a control that exists.
    this_run = _as_run_id(gate)
    for entry in gate.get("history", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("answer") in STOP_ANSWERS and entry.get("run_id") == this_run:
            return "stop"
    if answer in CONTINUE_ANSWERS.get(str(gate.get("gate_id")), frozenset()):
        # THE CHAIN MATTERS, not just this record. Picking an out-of-scope stage at
        # `stage_choice` and then confirming through `stage_confirmation` composed a growth
        # report at high confidence -- the out-of-scope question, the only one offering
        # "Stop review", was never asked. The prior pick is in this run's history, so the
        # skipped step is checkable rather than trusted.
        for entry in gate.get("history", []):
            if not isinstance(entry, dict) or entry.get("run_id") != _as_run_id(gate):
                continue
            if entry.get("gate_id") == "stage_choice" and entry.get("answer") in OUT_OF_SCOPE_STAGES:
                return "rebuild"
        return "continue"
    if answer in CONTINUE_IF_REBUILT_ANSWERS:
        return "continue_if_rebuilt"
    return "rebuild"


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

    # THE RUN REMEMBERS. This file was overwritten wholesale on every emit, so a founder's
    # decision could be erased by asking a different question: answer "Stop review", emit a
    # fresh stage_confirmation over the top, self-answer it, and compose exits 0. Every
    # record in that sequence is individually valid, which is why canonical options and
    # answer validation did not touch it — what was missing is that nothing remembered.
    #
    # Append-only, and only within a run: a prior completed review that was declined says
    # nothing about a fresh one (and `setup_run.py --clean` removes the file anyway).
    prior = _read_existing(args.output)
    if is_answered(prior):
        assert isinstance(prior, dict)
        history = [h for h in prior.get("history", []) if isinstance(h, dict)]
        history.append(
            {
                "gate_id": prior.get("gate_id"),
                "answer": prior.get("answer"),
                "answer_source": prior.get("answer_source"),
                "run_id": _as_run_id(prior),
            }
        )
        data["history"] = history
    elif isinstance(prior, dict) and prior.get("history"):
        data["history"] = [h for h in prior["history"] if isinstance(h, dict)]

    # THE OPTIONS ARE CHECKED WHERE THE QUESTION IS WRITTEN. Validating them only at
    # ANSWER time meant a rigged gate still reached the founder and was refused afterwards
    # -- after they had been shown a choice that omitted "Stop review".
    gate_id = str(data.get("gate_id") or "")
    options = data.get("options")
    if isinstance(options, list) and all(isinstance(o, str) for o in options):
        if gate_id in CANONICAL_OPTIONS and tuple(options) != CANONICAL_OPTIONS[gate_id]:
            print(
                f"Error: {gate_id} must offer exactly {list(CANONICAL_OPTIONS[gate_id])!r} — "
                "the choices a gate presents are not the asker's to pick",
                file=sys.stderr,
            )
            return 1
        if gate_id == "stage_choice":
            outside = [o for o in options if o not in STAGE_CHOICE_OPTIONS]
            if outside:
                print(f"Error: stage_choice offered {outside!r}, which are not stages", file=sys.stderr)
                return 1
            if len(options) != 4:
                # Four is what AskUserQuestion renders and what SKILL.md offers: the enum
                # minus the stage just rejected. Fewer hides a stage the founder may want.
                print(
                    f"Error: stage_choice must offer exactly 4 stages (the enum minus the one just "
                    f"rejected), got {len(options)}",
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
    # THE PAYLOAD THE FOUNDER SEES, produced by the code that validated it. Canonical
    # options are enforced on the FILE, and SKILL.md retyped the `needs_input` block by
    # hand -- so a record containing "Stop review" could sit beside a displayed choice that
    # omitted it. Validation then guarantees what was recorded, not what was asked.
    receipt["needs_input"] = {
        "gate_state_path": os.path.abspath(args.output),
        "gate_id": data.get("gate_id"),
        "question": data.get("question"),
        "options": data.get("options"),
        "context_summary": data.get("context_summary"),
    }
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

    # COMPARE-AND-SET. `emit` was taught to carry an answered gate into history; this path
    # was not, and it overwrote the answer in place -- so the erasure closed through one
    # door and stayed open through the one beside it: answer "Stop review", answer again
    # with "Proceed anyway", and the decline is gone with no trace. An answer is a founder's
    # decision, and a decision is not something a later call gets to replace.
    #
    # Idempotent on an identical re-answer: the gate round-trip re-invokes the sub-agent and
    # a caller cannot always tell whether its previous write landed, so a retry must not
    # fail the run.
    existing = gate.get("answer")
    if isinstance(existing, str) and existing.strip():
        if existing == args.answer:
            sys.stdout.write(json.dumps({"ok": True, "path": args.file, "unchanged": True}) + "\n")
            return 0
        print(
            f"Error: this gate was already answered {existing!r} and cannot be re-answered "
            f"{args.answer!r} — emit a new gate if another question is genuinely being asked",
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
