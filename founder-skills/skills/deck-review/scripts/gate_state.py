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
import contextlib
import fcntl
import json
import os
import re
import sys

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact

FOUNDER, AUTO_SATISFIED = "founder", "auto_satisfied"
ANSWER_SOURCES = (FOUNDER, AUTO_SATISFIED)

# Auto-satisfy is scoped to the one gate and the one answer it has a rationale for; see
# the enforcement in `cmd_answer` for why the other two gate_ids are excluded.
AUTO_SATISFIABLE_GATE = "stage_confirmation"
AUTO_SATISFIABLE_ANSWER = "Looks right"


class UnreadablePriorGate(Exception):
    """A gate file exists but cannot be parsed."""


def _read_existing(path: str) -> object:
    """The gate already on disk, or None if there is none.

    UNREADABLE IS NOT ABSENT. It used to be, so a run could not be stranded by a corrupt
    file — but the same tolerance is an erasure path: answer "Stop review", truncate the
    file, emit a fresh gate, answer that, and the decline is gone. The history carry-forward
    is exactly what a truncated file destroys.

    Writes are atomic now, so the writer does not produce this state; if it appears anyway,
    something outside the CLI wrote it and the run must not proceed as though the record had
    always been empty.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise UnreadablePriorGate(str(e)) from e


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
    # PRESENCE IS NOT VALIDITY. Only the field's existence was checked, so a hand-written
    # `gate_id: frobnicate` validated — and because `gate_action` classified the ANSWER
    # without reference to the gate, an unknown gate carrying a recognised answer reached
    # the permit at the bottom of `authorize`.
    if gate.get("gate_id") not in KNOWN_GATE_IDS:
        problems.append(f"gate_id {gate.get('gate_id')!r} is not one of {sorted(KNOWN_GATE_IDS)}")
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

# The one mapping between the token the machinery uses and the words a founder reads. Both
# the option contract and the contradiction check below need it, and deriving it twice is how
# the two drift.
STAGE_LABELS: dict[str, str] = {
    "pre_seed": "Pre-seed",
    "seed": "Seed",
    "series_a": "Series A",
    "series_b": "Series B",
    "growth": "Growth",
}

# Stage tokens that are ALSO ordinary English words. A bare substring match over
# STAGE_LABELS refused correct gates because of these two: measured on a live run, a correct
# Series A summary was rejected for saying "~4x YoY growth". They require a stage-NAMING
# construction (below); the other three tokens never occur innocently and keep the strict
# whole-word match, so prose that really names a different stage is still refused.
_AMBIGUOUS_STAGE_WORDS = frozenset({"seed", "growth"})

# What turns an ordinary word into a STAGE CLAIM. Deliberately adjacency, not a distance
# window: "Detected stage: Series A. 12 seed customers." puts a cue four words from "seed",
# so any window wide enough to catch "stage: Seed" also catches that false positive. These
# patterns allow only non-word characters between cue and stage word.
_STAGE_CUES = ("stage", "round", "detected", "detect", "confirming", "confirm")


def _norm_stage_text(text: str) -> str:
    """Collapse the separators a stage name is spelled with, so all spellings compare equal.

    "Series A", "Series-A", "series_a" and "Series  A" are ONE claim to a reader, so they must
    be one string here. Without this, whole-word matching sees "series-a" and "series a" as
    unrelated -- which LOST a refusal the old bare-substring match caught by accident: "this is
    a pre seed company" on a series_a gate matched bare "seed", and once matching became
    whole-word the space-separated spelling slipped through. `-`, `_` and runs of whitespace all
    become a single space; other punctuation is left alone, because the naming-construction
    patterns rely on it ("stage: Seed").
    """
    return re.sub(r"[-_\s]+", " ", text.lower())


def _stage_forms(stage: str) -> tuple[str, ...]:
    """Every separator-normalised spelling of one stage: its token and its founder label.

    Both collapse to one string for some stages (`pre_seed` and "Pre-seed" both give
    "pre seed"); de-duplicating keeps the caller's loop from testing the same form twice.
    """
    forms = (_norm_stage_text(stage), _norm_stage_text(STAGE_LABELS[stage]))
    return (forms[0],) if forms[0] == forms[1] else forms


def prose_names_stage(prose: str, stage: str) -> bool:
    """Does `prose` NAME `stage`, as opposed to merely containing an English word?

    Four rules, each closing a measured false result. `prose` is normalised here.

    * SUPERSTRING MASKING. "seed" is a substring of "pre-seed", so a `pre_seed` gate whose
      summary correctly read "Detected stage: Pre-seed" was refused for naming Seed --
      SKILL.md's own template was un-emittable for an in-scope stage. Longer stage
      spellings are removed before a shorter one is looked for. Word boundaries do NOT fix
      this on their own: `\bseed\b` matches inside "pre-seed", because `-` IS a boundary.
    * WHOLE WORDS. "Seeded in 2019" is not a stage claim.
    * A NAMING CONSTRUCTION, for the two tokens that are ordinary English. "~4x YoY growth"
      is prose; "Growth stage", "stage: Growth" and "Confirming Growth" are claims.
    * SEPARATOR NORMALISATION (`_norm_stage_text`). "Series-A" and "series_a" are the same
      claim as "Series A". Without it, whole-word matching lost a refusal the old substring
      match caught by accident -- see that helper.
    """
    prose = _norm_stage_text(prose)
    longer = [f for other in STAGE_LABELS for f in _stage_forms(other)]
    for form in _stage_forms(stage):
        haystack = prose
        for other in longer:
            # Strictly longer spellings only -- a form never masks itself.
            if len(other) > len(form) and form in other:
                haystack = haystack.replace(other, " ")
        word = re.escape(form)
        if form in _AMBIGUOUS_STAGE_WORDS:
            cues = "|".join(_STAGE_CUES)
            named = re.search(rf"(?:{cues})\W{{0,3}}{word}\b", haystack) or re.search(
                rf"\b{word}[\s\-]{{0,3}}(?:stage|round)\b", haystack
            )
        else:
            named = re.search(rf"\b{word}\b", haystack)
        if named:
            return True
    return False


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
    if isinstance(gate, dict) and _reduce_history(gate, str(_as_run_id(gate) or "")) == "stop":
        return "stop"
    if not is_answered(gate) or validate_answered_gate(gate):
        return "reask"
    assert isinstance(gate, dict)  # is_answered established this
    answer = str(gate.get("answer"))
    if answer in STOP_ANSWERS:
        return "stop"
    if answer in CONTINUE_ANSWERS.get(str(gate.get("gate_id")), frozenset()):
        # THE CHAIN MATTERS, not just this record. Picking an out-of-scope stage at
        # `stage_choice` and then confirming through `stage_confirmation` composed a growth
        # report at high confidence -- the out-of-scope question, the only one offering
        # "Stop review", was never asked. The prior pick is in this run's history, so the
        # skipped step is checkable rather than trusted.
        if _reduce_history(gate, str(_as_run_id(gate) or "")) == "out_of_scope_pick":
            return "rebuild"
        return "continue"
    if answer in CONTINUE_IF_REBUILT_ANSWERS:
        return "continue_if_rebuilt"
    return "rebuild"


OUT_OF_SCOPE_STAGE_TOKENS: frozenset[str] = frozenset({"series_b", "growth"})
KNOWN_GATE_IDS: frozenset[str] = frozenset({"stage_confirmation", "out_of_scope_choice", "stage_choice"})
IN_SCOPE_STAGE_TOKENS: frozenset[str] = frozenset({"pre_seed", "seed", "series_a"})

# THE COMPLETE SET OF TRANSITIONS THAT AUTHORIZE A REPORT.
#
# Keyed on the stage the gate ASKED about, because for one of these rows the answer's whole
# purpose is to CHANGE the stage. The previous version keyed on (gate_id, answer) and then
# required the asked stage to equal the stage being graded — which made the documented
# out-of-scope flow impossible: that gate asks about growth, and "Proceed anyway" rebuilds
# to series_a (SKILL.md:535). I shipped that false refusal, and my own positive tests hid it
# by fabricating `confirmed_stage: series_a` on an `out_of_scope_choice` gate, a record no
# writer can produce because that gate is only emitted for out-of-scope stages.
#
# A row is (asked-stage class, gate_id, answer) -> what the profile must have become.
# `resulting_stage` of None means "unchanged from what was asked".
_ASKED_IN_SCOPE, _ASKED_OUT_OF_SCOPE = "in_scope", "out_of_scope"

TRANSITIONS: dict[tuple[str, str, str], dict[str, str | None]] = {
    # Confirming an in-scope detection changes nothing.
    (_ASKED_IN_SCOPE, "stage_confirmation", "Looks right"): {
        "resulting_stage": None,
        "confidence": None,
    },
    # "Not sure" keeps the stage and downgrades confidence.
    (_ASKED_IN_SCOPE, "stage_confirmation", "Not sure — proceed anyway"): {
        "resulting_stage": None,
        "confidence": "low",
    },
    # THE ROW THAT MOVES THE STAGE. Out of scope, the founder says proceed, and SKILL.md
    # rebuilds to series_a at low confidence. Requiring exactly that is what stops the
    # rebuild landing somewhere more favourable.
    (_ASKED_OUT_OF_SCOPE, "out_of_scope_choice", "Proceed anyway (best-effort)"): {
        "resulting_stage": "series_a",
        "confidence": "low",
    },
}


def _asked_class(stage: str) -> str | None:
    """Which side of the scope line the gate was asked about, or None if unrecognised."""
    if stage in IN_SCOPE_STAGE_TOKENS:
        return _ASKED_IN_SCOPE
    if stage in OUT_OF_SCOPE_STAGE_TOKENS:
        return _ASKED_OUT_OF_SCOPE
    return None


def _reduce_history(gate: dict[str, object], run_id: str) -> str | None:
    """The operative earlier transition for this run, reduced IN ORDER.

    The scan used to be existential, so an out-of-scope stage pick the founder later
    CORRECTED still forced a rebuild for the rest of the run — a multi-round correction
    could never finish. Order matters: the last stage pick is the operative one.

    A stop is ABSORBING. Reduction must not let a later answer overwrite a decline, which
    is the one place "last wins" would be exactly wrong.
    """
    operative: str | None = None
    entries = gate.get("history", [])
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("run_id") != run_id:
            continue
        answer = entry.get("answer")
        if answer in STOP_ANSWERS:
            return "stop"
        if entry.get("superseded"):
            continue
        if entry.get("gate_id") == "stage_choice":
            operative = "out_of_scope_pick" if answer in OUT_OF_SCOPE_STAGES else "in_scope_pick"
    return operative


class Authorization:
    """Whether this gate permits a report, and if not, why not in one sentence."""

    __slots__ = ("permitted", "reason")

    def __init__(self, permitted: bool, reason: str = "") -> None:
        self.permitted = permitted
        self.reason = reason

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.permitted


def authorize(gate: object, stage_profile: object, run_id: str) -> Authorization:
    """THE ONE PLACE A GATE BECOMES PERMISSION TO PRODUCE A REPORT — a closed allow table.

    Two earlier shapes failed, and the difference between them is the lesson. First the
    rules were spread across four call sites and grew a fifth every review round. Then they
    were consolidated here but written as refusal-predicates-then-permit, which SOUNDS like
    deny-by-default and is not: falling off the bottom was still success, so `gate_id:
    frobnicate` carrying the globally-recognised answer "Not sure — proceed anyway"
    authorized a clean report. The predicates were all correct; the default was wrong.

    Now the PERMITTED set is written out (`TERMINAL_ROWS`) and a state absent from it is
    refused because nothing permits it, not because a check happened to catch it.

    `_out_of_scope_consent` is gone rather than fixed. Every path through SKILL.md either
    exits on "Stop review" or rebuilds to series_a at low confidence, so an out-of-scope
    profile reaching compose is always wrong whatever history records — which replaces a
    four-property search through history with one check on the artifact being composed, and
    closes the case where historical consent skipped the rebuild it was supposed to trigger.

    Honest boundary, unchanged: none of this proves a founder spoke. The record is written
    by the same agent that would misuse it, on a filesystem it can write to directly. What
    is enforceable — and what every defect found across eight rounds actually was — is that
    the record is internally coherent and consistent with the artifacts being composed.
    """
    if not isinstance(gate, dict):
        return Authorization(False, "gate_state is not a JSON object")
    profile = stage_profile if isinstance(stage_profile, dict) else {}

    # --- the record and the profile must both belong to this run
    gate_run = _as_run_id(gate)
    if gate_run != run_id:
        return Authorization(False, f"the gate is from run {gate_run!r} but this report is run {run_id!r}")
    prof_run = _as_run_id(profile)
    if prof_run != run_id:
        return Authorization(
            False,
            f"the stage profile is from run {prof_run!r}, not this run {run_id!r} — the gate confirms "
            "a stage this report is not being graded against",
        )

    # --- the record must be coherent, and its answer must be one the run can act on
    action = gate_action(gate)
    if action == "stop":
        return Authorization(False, "the founder declined the review, so no report is to be produced")
    if action == "reask":
        problems = validate_answered_gate(gate) if is_answered(gate) else ["it was never answered"]
        return Authorization(False, "the gate carries no usable answer: " + "; ".join(problems))
    if action == "rebuild":
        return Authorization(
            False,
            f"{gate.get('answer')!r} on the {gate.get('gate_id')!r} gate is an intermediate answer — "
            "the profile is rebuilt and the gate re-asked before a report is composed",
        )

    if action not in ("continue", "continue_if_rebuilt"):
        # NOT decorative, and removing it was a mistake worth recording: the allow table
        # keys on (gate_id, answer), so an unrecognised ACTION falls straight through to a
        # matching row. The table constrains what the answer is; this constrains what the
        # run may do with it. Both are needed.
        return Authorization(False, f"unrecognised gate action {action!r}")

    # --- the transition. One row must match, or nothing authorizes this.
    asked = str(gate.get("confirmed_stage") or "").lower()
    if not asked:
        return Authorization(
            False,
            "the gate does not record which stage it asked about, so its answer cannot be checked "
            "against the profile this report is graded on",
        )
    asked_class = _asked_class(asked)
    if asked_class is None:
        return Authorization(False, f"the gate records an unrecognised stage {asked!r}")

    stage = str(profile.get("detected_stage") or "").lower()
    row = TRANSITIONS.get((asked_class, str(gate.get("gate_id")), str(gate.get("answer"))))
    if row is None:
        return Authorization(
            False,
            f"{gate.get('answer')!r} on the {gate.get('gate_id')!r} gate, asked about {asked!r}, is not "
            "a transition that authorizes a report",
        )

    expected_stage = row["resulting_stage"] or asked
    if stage != expected_stage:
        return Authorization(
            False,
            f"{gate.get('answer')!r} resolves to a {expected_stage!r} profile — the one being composed "
            f"holds {profile.get('detected_stage')!r}",
        )
    # The resulting stage must itself be reviewable. Every row lands in scope, so this is a
    # backstop against a future row that does not.
    if stage not in IN_SCOPE_STAGE_TOKENS:
        return Authorization(
            False,
            f"the profile being composed is {stage!r}, which is not a stage this review covers",
        )
    # REACHING series_a/low FROM OUT OF SCOPE REQUIRES THE FOUNDER TO HAVE SAID SO. The
    # transition above verifies the profile is what the answer resolves to, and that is not
    # enough on its own: emit the out-of-scope question, never answer it, rebuild to
    # series_a/low anyway, then emit a plain confirmation and answer THAT. Every record is
    # individually fine and the founder was never offered "Stop review". So a
    # series_a/low profile carrying a superseded out-of-scope question in its history must
    # show that question was answered.
    if asked_class == _ASKED_IN_SCOPE:
        # CONSENT ATTACHES TO THE QUESTION THAT WAS PUT. This reduced history to two
        # booleans — "some out-of-scope gate was answered" / "some was not" — so an answered
        # question NEUTRALISED a later abandoned one: growth asked and answered, series_b
        # asked and dropped, and the run proceeded as though both had been settled. Each
        # unanswered out-of-scope question is tracked by the stage it asked about, so
        # answering one cannot stand in for another.
        unanswered: set[str] = set()
        answered: set[str] = set()
        entries = gate.get("history", [])
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get("run_id") != run_id:
                continue
            if entry.get("gate_id") != "out_of_scope_choice":
                continue
            about = str(entry.get("confirmed_stage") or "")
            if isinstance(entry.get("answer"), str) and entry["answer"].strip():
                answered.add(about)
            else:
                unanswered.add(about)
        outstanding = sorted(unanswered - answered)
        if outstanding:
            return Authorization(
                False,
                f"an out-of-scope question about {', '.join(repr(s) for s in outstanding)} was put to "
                "the founder in this run and never answered — answering a different one does not "
                "settle it",
            )

    required_confidence = row["confidence"]
    if required_confidence is not None and profile.get("confidence") != required_confidence:
        return Authorization(
            False,
            f"{gate.get('answer')!r} continues only against a profile rebuilt at {required_confidence} "
            f"confidence — this one has {profile.get('confidence')!r}",
        )

    # --- auto-satisfy: the checkable half of its documented precondition
    if gate.get("answer_source") == AUTO_SATISFIED and profile.get("confidence") == "low":
        return Authorization(
            False,
            "auto-satisfy claims the detected stage agrees with what the founder said, but the "
            "detection is low confidence — ask them",
        )

    return Authorization(True)


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
    try:
        prior = _read_existing(args.output)
    except UnreadablePriorGate as e:
        print(
            f"Error: a gate file at {args.output} exists but is unreadable ({e}) — it may hold a "
            "decision this run already made, so it is not overwritten. Repair or remove it "
            "deliberately.",
            file=sys.stderr,
        )
        return 1
    if isinstance(prior, dict) and (is_answered(prior) or prior.get("gate_id")):
        history = [h for h in prior.get("history", []) if isinstance(h, dict)]
        entry: dict[str, object] = {
            "gate_id": prior.get("gate_id"),
            "answer": prior.get("answer"),
            "answer_source": prior.get("answer_source"),
            "run_id": _as_run_id(prior),
        }
        if not is_answered(prior):
            # WHAT THE FOUNDER WAS ASKED IS PART OF THE RECORD, not only what they said.
            # Only answered priors were carried, so a PENDING out-of-scope question
            # replaced by a different emit vanished without trace — the run could no longer
            # show that the question had been put at all.
            entry = {k: v for k, v in entry.items() if v is not None}
            entry["superseded"] = True
        data["history"] = [*history, entry]
    elif isinstance(prior, dict) and prior.get("history"):
        data["history"] = [h for h in prior["history"] if isinstance(h, dict)]

    # THE OPTIONS ARE CHECKED WHERE THE QUESTION IS WRITTEN. Validating them only at
    # ANSWER time meant a rigged gate still reached the founder and was refused afterwards
    # -- after they had been shown a choice that omitted "Stop review".
    # The stage this gate is about travels WITH the record, so a later profile rebuild
    # cannot silently re-point a founder's answer at a different stage.
    data["confirmed_stage"] = args.stage

    gate_id = str(data.get("gate_id") or "")
    # THE GATE AND THE STAGE IT ASKS ABOUT MUST AGREE. `out_of_scope_choice` exists for
    # series_b/growth, so one emitted about seed asks an out-of-scope question about an
    # in-scope deck — an incoherent record, and exactly what my own tests fabricated to make
    # a broken authorization rule look correct.
    if gate_id == "out_of_scope_choice" and args.stage not in OUT_OF_SCOPE_STAGE_TOKENS:
        print(
            f"Error: out_of_scope_choice is for {sorted(OUT_OF_SCOPE_STAGE_TOKENS)}, not {args.stage!r} "
            "— an in-scope deck gets stage_confirmation",
            file=sys.stderr,
        )
        return 1
    if gate_id == "stage_confirmation" and args.stage in OUT_OF_SCOPE_STAGE_TOKENS:
        print(
            f"Error: {args.stage!r} is out of scope, so the founder must be asked through "
            "out_of_scope_choice — stage_confirmation offers no way to decline",
            file=sys.stderr,
        )
        return 1

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
            if len(set(options)) != len(options):
                print(
                    f"Error: stage_choice offered duplicate options {options!r} — duplicates hide the "
                    "alternatives the founder is supposed to choose between",
                    file=sys.stderr,
                )
                return 1
            rejected = STAGE_LABELS.get(args.stage)
            expected_set = STAGE_CHOICE_OPTIONS - {rejected} if rejected else STAGE_CHOICE_OPTIONS
            if set(options) != expected_set:
                # THE CONTRACT, not just the shape. Uniqueness and a count of four accepted
                # `Pre-seed, Seed, Series A, Series B` for `--stage seed`: it reoffered the
                # stage the founder had just rejected and hid Growth entirely.
                print(
                    f"Error: stage_choice must offer exactly the stages other than {rejected!r} "
                    f"({sorted(expected_set)}), got {sorted(set(options))} — reaching this gate means "
                    "the founder rejected that stage, so it cannot be among the choices",
                    file=sys.stderr,
                )
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
    # THE STAGE IS PART OF WHAT THE FOUNDER IS SHOWN. `--stage` was a hidden token: the
    # summary was caller-written and the artifact carried something else, so emitting
    # `--stage series_a` behind "Detected stage: Seed" let a "Looks right" authorize a
    # Series A report. The producer appends the stage it will authorize, so the sentence the
    # founder reads and the token that authorizes cannot disagree.
    # THE PROSE MAY NOT NAME A DIFFERENT STAGE. Appending the structured stage left both in
    # the payload — "Detected stage: Seed" beside "(Confirming stage: series_a.)" — with the
    # hidden token deciding. A founder reading the first sentence has been told something
    # the record contradicts.
    prose = f"{data.get('question') or ''} {data.get('context_summary') or ''}".lower()
    for token, label in STAGE_LABELS.items():
        if token == args.stage:
            continue
        if prose_names_stage(prose, token):
            print(
                f"Error: this gate confirms {args.stage!r} but its question or summary names "
                f"{label!r} — a founder cannot be shown one stage and asked to authorize another",
                file=sys.stderr,
            )
            return 1

    summary = str(data.get("context_summary") or "")
    stated = f"{summary}\n(Confirming stage: {args.stage}.)" if summary else f"Confirming stage: {args.stage}."
    receipt["needs_input"] = {
        "gate_state_path": os.path.abspath(args.output),
        "gate_id": data.get("gate_id"),
        "question": data.get("question"),
        "options": data.get("options"),
        "context_summary": stated,
        "confirmed_stage": args.stage,
    }
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    # HELD ACROSS READ-CHECK-WRITE. `os.replace` makes the write atomic, which prevents a
    # TORN file and does nothing about a LOST UPDATE: two calls both read an unanswered gate,
    # both pass the "already answered?" check, and the later write wins — so a founder's
    # decline could be overwritten by a self-answered proceed. Atomicity of the write was the
    # wrong tool for a read-modify-write.
    #
    # A race test that passes is weak evidence (the window is small); the lock is what makes
    # the property hold rather than usually hold.
    if not os.path.isfile(args.file):
        print(f"Error: gate_state file not found: {args.file}", file=sys.stderr)
        return 1
    lock_path = f"{args.file}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock:
        # No advisory locking available (some network filesystems) is not fatal: proceed
        # rather than strand the run, since the compare-and-set below still catches the
        # common case of two writers.
        with contextlib.suppress(OSError):
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _answer_locked(args, gate_path=args.file)


def _answer_locked(args: argparse.Namespace, gate_path: str) -> int:
    try:
        with open(gate_path, encoding="utf-8") as f:
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
    sp_emit.add_argument(
        "--stage",
        required=True,
        help="The stage token this gate is asking about (pre_seed|seed|series_a|series_b|growth). "
        "Recorded as `confirmed_stage` so the answer can be checked against the profile the report "
        "is graded on — nothing tied the two together, so confirming Seed, rebuilding to Series A "
        "and composing against the original gate produced a clean Series A report.",
    )
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
