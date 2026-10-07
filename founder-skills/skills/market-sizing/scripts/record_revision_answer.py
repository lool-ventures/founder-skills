#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record the founder's answer to Step 6d's question: deliver with the challenges shown, or revise.

The question is asked only when the review's accepted findings include a `high` one naming a `parameter`.
A live run skipped it silently. compose_report.py now discloses REVISION_NOT_OFFERED when such a finding
exists and this record does not, so the answer is written here, into the run's hand-off dir beside the gate
records, with the parameters it answers for. The record carries this run's id: a record from an earlier run
of the same analysis, or one for other findings, does not answer this review.

`--source no_questions` is the founder-asked-not-to-be-asked path (option 1 taken, listed in
`gate_defaults`); it is recorded too, or that run would read as "never offered".

What this proves, and what it does not: that the question step ran this recorder -- not that the question
was put to the founder, which only the transcript shows.

With a run ledger the answer is recorded there first (`ms_revision`) and this file is its mirror.
`--from-pre-answer` is the step's open, before it asks: when the review raises the question it opens the gate
and applies an answer the request carried (`FS_HOST_ANSWER ms_revision=deliver`), printing `"applied": true`
(ask nothing) or `false` (ask). When the review raises no question it prints `"owed": false` and touches
nothing. With no ledger it prints `"applied": false` and writes nothing.

Rejects loudly: diagnostic JSON to stdout, a line to stderr, nothing written, exit 1.

Usage:
    python record_revision_answer.py --dir "$ANALYSIS_DIR" --answer deliver --source founder
    python record_revision_answer.py --dir "$ANALYSIS_DIR" --from-pre-answer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402
from _revision_answer import ANSWERS, SOURCES, qualifying_parameters, record_path  # noqa: E402

# `host` is written only by --from-pre-answer, from the request's own line.
_CLI_SOURCES = tuple(x for x in SOURCES if x != "host")


def _fail_invalid(errors: list[str]) -> NoReturn:
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": errors}}, indent=2) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(errors)}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Record the answer to the revise-or-deliver question (Step 6d)")
    p.add_argument("--dir", required=True, help="the analysis dir ($ANALYSIS_DIR)")
    p.add_argument("--answer", help=f"one of: {', '.join(ANSWERS)}")
    p.add_argument("--source", help=f"one of: {', '.join(_CLI_SOURCES)}")
    p.add_argument(
        "--from-pre-answer",
        action="store_true",
        help="open the question and apply an answer the request carried, before asking",
    )
    p.add_argument("--pretty", action="store_true")
    a = p.parse_args()
    if a.from_pre_answer:
        if a.answer is not None or a.source is not None:
            _fail_invalid(["--from-pre-answer takes neither --answer nor --source"])
        _from_pre_answer(a.dir, a.pretty)
        return
    if a.answer is None or a.source is None:
        _fail_invalid(["--answer and --source are both required (or --from-pre-answer)"])
    if a.answer not in ANSWERS:
        _fail_invalid([f"--answer must be one of {', '.join(ANSWERS)}; got {a.answer!r}"])
    if a.source not in _CLI_SOURCES:
        _fail_invalid([f"--source must be one of {', '.join(_CLI_SOURCES)}; got {a.source!r}"])
    try:
        with open(os.path.join(a.dir, "redteam.json"), encoding="utf-8") as fh:
            redteam = json.load(fh)
    except (OSError, ValueError) as e:
        _fail_invalid([f"no readable redteam.json in {a.dir}: {e}"])
    parameters = qualifying_parameters(redteam)
    if not parameters:
        _fail_invalid(["the review has no accepted high finding naming a parameter, so there is no question to answer"])
    run_id = (redteam.get("metadata") or {}).get("run_id") if isinstance(redteam, dict) else None
    if not isinstance(run_id, str) or not run_id.strip():
        _fail_invalid(["redteam.json carries no metadata.run_id"])
    path = record_path(a.dir, run_id)
    if not os.path.isdir(os.path.dirname(path)):
        _fail_invalid([f"no hand-off dir for this run at {os.path.dirname(path)} (Step 0 creates it)"])
    # The run's gate ledger, when it has one, records the answer first; the file below is its mirror.
    # `no_questions` is the default a founder who asked not to be asked gets, recorded as that default.
    try:
        ledger = _run_ref.open_ledger(a.dir, run_id)
        if ledger is not None:
            gates, paths = ledger
            if a.source == "no_questions":
                gates.record_from_writer(
                    paths,
                    "ms_revision",
                    a.answer,
                    "record_revision_answer.py",
                    resolution="default_taken",
                    default_reason="asked_not_to_be_asked",
                )
            else:
                gates.record_from_writer(paths, "ms_revision", a.answer, "record_revision_answer.py")
    except Exception as e:  # noqa: BLE001 -- RUN_FINISHED or an unreachable ledger: printed, nothing written
        sys.exit(_rejected(e))
    _write_mirror(path, a.answer, a.source, parameters, run_id, a.pretty)
    print(json.dumps({"ok": True, "path": path, "answer": a.answer, "parameters": parameters}))


def _rejected(e: BaseException) -> int:
    import _ms_gates  # noqa: PLC0415

    if type(e).__name__ == "GateRejection" and getattr(e, "code", None) == "RUN_FINISHED":
        sys.stdout.write(
            json.dumps({"status": "rejected", "code": "RUN_FINISHED", "message": _ms_gates.FINISHED_MESSAGE}) + "\n"
        )
        print(f"Error: {_ms_gates.FINISHED_MESSAGE}; nothing was written", file=sys.stderr)
        return 1
    return _run_ref.report_failure(e)


def _write_mirror(path: str, answer: str, source: str, parameters: list[str], run_id: str, pretty: bool) -> None:
    record = {
        "answer": answer,
        "source": source,
        "parameters": parameters,
        "_produced_by": "record_revision_answer",
        "metadata": {"run_id": run_id},
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2 if pretty else None) + "\n")


def _from_pre_answer(analysis_dir: str, pretty: bool) -> None:
    """Open the question and apply the request's answer, when the review raises the question."""
    try:
        with open(os.path.join(analysis_dir, "redteam.json"), encoding="utf-8") as fh:
            redteam = json.load(fh)
    except (OSError, ValueError):
        redteam = None
    parameters = qualifying_parameters(redteam)
    run_id = (redteam.get("metadata") or {}).get("run_id") if isinstance(redteam, dict) else None
    if not parameters or not isinstance(run_id, str):
        print(json.dumps({"applied": False, "owed": False}))
        return
    try:
        ledger = _run_ref.open_ledger(analysis_dir, run_id)
        if ledger is None:
            print(json.dumps({"applied": False}))
            return
        gates, paths = ledger
        gates.open_from_writer(paths, ["ms_revision"], "record_revision_answer.py")
        got = gates.apply_writer_pre_answer(paths, "ms_revision", "record_revision_answer.py", list(ANSWERS))
    except Exception as e:  # noqa: BLE001
        sys.exit(_rejected(e))
    if isinstance(got, dict) and got.get("answer_id") in ANSWERS:
        path = record_path(analysis_dir, run_id)
        if os.path.isdir(os.path.dirname(path)):
            _write_mirror(path, str(got["answer_id"]), "host", parameters, run_id, pretty)
        print(json.dumps({"applied": True, "answer": got["answer_id"], "parameters": parameters}))
        return
    print(json.dumps({"applied": False, "owed": True, "parameters": parameters}))


if __name__ == "__main__":
    main()
