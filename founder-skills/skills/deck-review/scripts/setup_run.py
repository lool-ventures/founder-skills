#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
r"""Resolve REVIEW_DIR for a deck review run.

Replaces the bash path heuristic in SKILL.md Step 0. Output is a JSON
object the agent can source into shell variables:

    eval "$(python setup_run.py --slug acme-corp --artifacts-root ./artifacts \
        | jq -r '@sh "REVIEW_DIR=\(.review_dir) RUN_ID=\(.run_id)"')"

Or simply parsed by a sub-agent that calls this once and uses the values.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime, timezone

_CLEANABLE_NAMES = {
    # Context B stages the coaching payload here for the sub-agent to Read.
    "coaching_payload.json",
    "deck_inventory.json",
    "stage_profile.json",
    "slide_reviews.json",
    "checklist.json",
    "ledger.json",
    "second_read.json",
    "reconciliation.json",
    "report.json",
    "report.md",
    "report.html",
    "coaching_commentary.json",  # Context-B coaching scratch, now staged under the review dir (F4)
    # gate_state.json is handled separately: it must persist across a gate
    # round-trip (same run_id) but be deleted when --clean runs for a fresh
    # run (resume is false). See _read_gate_state / the --clean block below.
}
_GATE_STATE_NAME = "gate_state.json"


_AUDITABLE_SOURCES = ("founder", "auto_satisfied")

# Auto-satisfy is legal on exactly one gate and one answer, and `gate_state.py` enforces
# that at write time. This is the same rule re-checked at READ time, deliberately
# duplicated: the write-time check was routable around through `emit`, and a rule that
# authorises skipping a founder's decision should not rest on a single choke point.
# Whatever put the file there, an auto_satisfied source that does not match this pair is
# not something to resume on.
_AUTO_SATISFIABLE_GATE = "stage_confirmation"
_AUTO_SATISFIABLE_ANSWER = "Looks right"


def _read_gate_state(review_dir: str) -> tuple[str, str, str]:
    """Return (answer, run_id, answer_source); ("", "", "") if absent/unreadable."""
    path = os.path.join(review_dir, _GATE_STATE_NAME)
    if not os.path.isfile(path):
        return "", "", ""
    try:
        with open(path, encoding="utf-8") as f:
            gate = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "", "", ""
    if not isinstance(gate, dict):
        return "", "", ""
    answer = str(gate.get("answer") or "")
    run_id = ""
    meta = gate.get("metadata")
    if isinstance(meta, dict):
        run_id = meta.get("run_id") or ""
    source = str(gate.get("answer_source") or "")
    # Re-check the auto-satisfy pair at read time; see the constants above for why this
    # is duplicated rather than trusted from the writer. Reported as an unrecorded source
    # rather than as an error: the effect that matters is that the run does not resume on
    # it and asks the founder instead.
    if source == "auto_satisfied" and (
        gate.get("gate_id") != _AUTO_SATISFIABLE_GATE or answer != _AUTO_SATISFIABLE_ANSWER
    ):
        source = ""
    return answer, str(run_id), source


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve REVIEW_DIR and run_id.")
    p.add_argument("--artifacts-root", required=True, help="Path to artifacts root directory")
    p.add_argument("--slug", required=True, help="Company slug")
    p.add_argument("--run-id", help="Override run_id (default: ISO timestamp)")
    p.add_argument("--clean", action="store_true", help="Remove stale review artifacts before starting")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    artifacts_root = os.path.abspath(args.artifacts_root)
    review_dir = os.path.join(artifacts_root, f"deck-review-{args.slug}")
    os.makedirs(review_dir, exist_ok=True)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Resume detection lives here (not in SKILL.md bash) so it cannot drift.
    # A resume is ONLY valid when gate_state.json carries an answer AND its
    # run_id matches the current run_id. An answered gate from a *prior*
    # completed run (different run_id) is stale and must NOT trigger a resume —
    # otherwise a fresh review of the same company reuses the old run's
    # artifacts.
    #
    # Preservation contract: when resume is true, artifacts from _CLEANABLE_NAMES
    # are same-run checkpoints (Steps 2-3 already ran for this run_id).  --clean
    # must NOT delete them — skipping re-runs avoids redundant LLM calls on gate
    # round-trips.  compose_report.py's run_id parity check is the safety net
    # against stale content from a different run.  On a fresh (non-resume) run
    # _CLEANABLE_NAMES are deleted unconditionally so no prior run's artifacts
    # pollute the new run.
    #
    # RESUME ELIGIBILITY AND CHECKPOINT PRESERVATION ARE SEPARATE DECISIONS, and were one
    # variable until an answer arrived that was same-run but unauditable. The skill always
    # passes --clean, and the rule was `if args.clean and not resume: delete`, so "re-ask
    # the gate but keep the checkpoints" could not be expressed: turning resume off deleted
    # the very artifacts it wanted kept. Steps 2-3 are three dispatches, two of which read
    # the deck; throwing them away to re-ask one question is the wrong trade.
    #
    #   same_run_answered  — this gate belongs to THIS run and has been answered, so the
    #                        checkpoints beside it are this run's. Governs deletion.
    #   resume             — the answer can be acted on, which additionally requires that
    #                        it record where it came from. Governs skipping the re-ask.
    #
    # An answered same-run gate with no `answer_source` was written by a path that bypassed
    # `gate_state.py answer` or predates the field. It cannot be audited, so it is not
    # resumed — but it is also not evidence that the checkpoints are stale, so they stay.
    gate_answer, gate_run_id, answer_source = _read_gate_state(review_dir)
    same_run_answered = bool(gate_answer) and gate_run_id == run_id
    resume = same_run_answered and answer_source in _AUDITABLE_SOURCES

    if args.clean and not same_run_answered:
        # Fresh run: remove all cleanable pipeline artifacts so no stale
        # content from a prior run contaminates this invocation.
        #
        # In Cowork the review dir is the promoted outputs/ tree, where a delete
        # can be DENIED ("Operation not permitted").  A denied delete must not be
        # fatal: tolerate it and fall back to compose_report.py's run_id parity
        # check (STALE_ARTIFACT) — the same backstop the other skills rely on for
        # overwrite-in-place.  (Each pipeline step overwrites its artifact via -o
        # with the fresh run_id, so a surviving prior-run artifact that a later
        # step does not regenerate is caught as a run_id mismatch.)
        for name in _CLEANABLE_NAMES:
            path = os.path.join(review_dir, name)
            if os.path.isfile(path):
                with contextlib.suppress(OSError):
                    os.remove(path)
        # Also remove a stale answered gate_state.json so it cannot be
        # misread as a resume signal on a later invocation.
        gate_path = os.path.join(review_dir, _GATE_STATE_NAME)
        if os.path.isfile(gate_path):
            with contextlib.suppress(OSError):
                os.remove(gate_path)
            gate_answer, gate_run_id, answer_source, resume = "", "", "", False
    # same_run_answered is true: _CLEANABLE_NAMES artifacts are same-run checkpoints —
    # leave them intact, whether or not the answer beside them can be resumed on.
    # gate_state.json is also preserved (an unauditable answer is re-asked, and
    # `gate_state.py emit` overwrites the file when the gate is put again).

    out = {
        "review_dir": review_dir,
        "run_id": run_id,
        "slug": args.slug,
        "artifacts_root": artifacts_root,
        "gate_answer": gate_answer,
        "gate_run_id": gate_run_id,
        "answer_source": answer_source,
        "resume": resume,
        # Whether this invocation removed the cleanable artifacts. Reported rather than
        # inferred from `resume`: the two diverge exactly in the case this split exists
        # for — an unauditable same-run answer keeps its checkpoints and is not resumed.
        "cleaned": bool(args.clean and not same_run_answered),
        # MAY STEPS 2-3 BE SKIPPED? Reported by name because the consumer needs it by name.
        # Splitting the decision inside this script bought nothing while SKILL.md still
        # keyed its skip on `resume`: the unauditable-answer case preserved the checkpoints
        # and then re-ran them anyway, spending the exact three dispatches the preservation
        # exists to protect. `resume` answers "may the gate be skipped"; this answers "are
        # the artifacts on disk this run's".
        "reuse_checkpoints": same_run_answered,
    }
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(out, indent=indent) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
