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


def _fail_invalid(errors: list[str], output_path: str | None) -> NoReturn:
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": errors}}, indent=2) + "\n")
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
    record = {
        "reason": a.reason,
        "_produced_by": "record_red_team_skip",
        "metadata": {"run_id": a.run_id},
    }
    path = os.path.abspath(a.output)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2 if a.pretty else None) + "\n")
    # The review will not run: a documents question it opened no longer applies (with the run's ledger).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _cp_gates

    _cp_gates.close_upload_question(os.path.dirname(path), a.run_id, a.reason)
    print(json.dumps({"ok": True, "path": path, "reason": a.reason}))


if __name__ == "__main__":
    main()
