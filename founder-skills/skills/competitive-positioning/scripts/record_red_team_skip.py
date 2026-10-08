#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record that this run's adversarial review did not run, and why.

The report is composed only when a review ran for this run or its absence was recorded here. There is no
field to hand-write for it: the reason is checked against a closed list when it is written, because each
reason is a different sentence the founder reads ("you asked us not to", "we tried and could not"), and
there is deliberately no reason meaning "it did not seem necessary".

Under a request that said not to ask (FS_HOST_NO_ASK), `founder_declined` is refused (code
NO_ASK_FOUNDER_DECLINED): nobody was asked, so nobody declined.

Rejects loudly: diagnostic JSON to stdout, a line to stderr, `-o` untouched, exit 1.

Usage:
    python record_red_team_skip.py --reason dispatch_failed --run-id R -o A/red_team_skip.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn

from _cp_redteam_copy import SKIP_REASONS


def _fail_invalid(errors: list[str], output_path: str | None, code: str | None = None) -> NoReturn:
    """`code`, when given, is printed at the top level and under `validation`, as compose prints it."""
    validation: dict[str, object] = {"status": "invalid", "errors": errors}
    out: dict[str, object] = {"validation": validation}
    if code is not None:
        validation["code"] = code
        out = {"code": code, **out}
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Record why this run's adversarial review did not run")
    p.add_argument("--reason", required=True, help=f"one of: {', '.join(SKIP_REASONS)}")
    p.add_argument("--run-id", required=True)
    p.add_argument("--pretty", action="store_true")
    p.add_argument("-o", "--output", required=True, help="the analysis dir's red_team_skip.json")
    a = p.parse_args()
    if a.reason not in SKIP_REASONS:
        _fail_invalid([f"--reason must be one of {', '.join(SKIP_REASONS)}; got {a.reason!r}"], a.output)
    if not a.run_id.strip():
        _fail_invalid(["--run-id must not be empty"], a.output)
    path = os.path.abspath(a.output)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _cp_gates

    ledger = _cp_gates.open_ledger_or_exit(os.path.dirname(path), a.run_id)
    if ledger is not None and a.reason == "founder_declined":
        gates, paths = ledger
        try:
            quiet = gates.no_ask(gates.load_ledger(paths))
        except Exception as e:  # noqa: BLE001 -- an unreadable ledger is the shared failure, before any write
            _cp_gates.exit_on_rejection(gates, e)
        if quiet:
            # The request said not to ask, so nobody was asked and nobody could decline.
            others = ", ".join(r for r in SKIP_REASONS if r != "founder_declined")
            _fail_invalid(
                [
                    "the request said not to ask (FS_HOST_NO_ASK), so nobody could decline the outside review; "
                    f"run it, or record why it did not run with one of: {others}"
                ],
                a.output,
                code="NO_ASK_FOUNDER_DECLINED",
            )
    record = {
        "reason": a.reason,
        "_produced_by": "record_red_team_skip",
        "metadata": {"run_id": a.run_id},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2 if a.pretty else None) + "\n")
    # The review will not run: a documents question it opened no longer applies (with the run's ledger).
    _cp_gates.close_upload_question(os.path.dirname(path), a.run_id, a.reason)
    print(json.dumps({"ok": True, "path": path, "reason": a.reason}))


if __name__ == "__main__":
    main()
