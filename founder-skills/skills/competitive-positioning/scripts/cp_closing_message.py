#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the founder-facing hand-over message from report.json, and write it to handover.txt.

The main thread sends this output as its final message, unchanged: the links, the report's own
verdict paragraph, and the offer of the working data. A run that composed its own chat summary
restated positions with its own wording ("ahead of the large printers" for a startup the map ranked
last), and a chat summary is the one founder-facing surface with no script between the model and
the reader. The shared Stop hook (founder-skills/scripts/stop_handover_check.py) compares the final
message against handover.txt, or against this script's output as the transcript recorded it when no
file is reachable -- so the last line printed must stay the offer. SKILL.md does not depend on it.

The same contract as market-sizing's closing_message.py -- link forms per surface, the file written
beside the report -- under its own name, so the Stop hook tells the two skills apart by script name.

Usage:
    cp_closing_message.py --report R --deliverable "LABEL=PATH" [--deliverable ...]
                          [--link auto|computer|path|none]

Exit 2 if the report cannot be read, carries no verdict, or was composed for another run than the one
this folder's artifacts carry (`RUN_ID_MISMATCH`: stdout empty, no handover.txt, no hand-over time); a
failed handover.txt write is a stderr line.

Under FS_HOST_NO_HANDOVER (recorded in the ledger of the run that holds this folder): after every refusal
above, print only the host line ("The analysis is complete. The host delivers its output."), write it to
handover.txt and stamp `handover: "host"` beside `handed_over_at` on that run. A failed write removes the
older handover.txt and still prints; exit 2 when neither works, or when the folder is bound but its current
run cannot be told or its ledger read (`LEDGER_MISSING` / `REGISTRY_UNREACHABLE`, a JSON line on stdout).
In a bound folder the ledger is opened whether or not the line was sent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HANDOVER_FILENAME = "handover.txt"


def detect_link_form(cwd: str, env: dict[str, str]) -> str:
    """`computer` on a Cowork session tree, `none` on Cowork's remote lane, `path` on the CLI."""
    if cwd.startswith("/sessions/"):
        return "computer"
    if env.get("CLAUDE_CODE_REMOTE") == "true" or env.get("CLAUDE_CODE_ENTRYPOINT") == "remote_cowork":
        return "none"
    return "path"


def _deliverables(specs: list[str], link: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for spec in specs:
        label, sep, path = spec.partition("=")
        if not sep or not label.strip() or not path.strip():
            raise ValueError(f"--deliverable must be LABEL=PATH, got {spec!r}")
        href: str | None
        if link == "computer":
            href = f"computer://{path.strip()}"
        elif link == "none":
            href = None  # the label alone: the cloud lane delivers a card, and a path beside it is dead
        else:
            href = path.strip()
        out.append((label.strip(), href))
    return out


# The code a refused report prints. Kept as a literal so the host contract's code scan sees it.
REFUSAL = {"code": "RUN_ID_MISMATCH"}


# The codes a report composed for a run that does not hold the folder prints (literals: the contract's code scan
# reads them).
FOLDER_REFUSALS = {"superseded": {"code": "RUN_SUPERSEDED"}, "not_bound": {"code": "RUN_NOT_BOUND"}}


def refuse_report_of_another_folder_run(report: dict[str, Any], run_dir: str) -> None:
    """In a folder that belongs to a run: exit 2, nothing printed or written, when report.json was composed for a
    run that no longer holds the folder (`RUN_SUPERSEDED`: a later run was bound here) or is not bound here at all
    (`RUN_NOT_BOUND`). A folder with no ref, or a report with no run id, is not checked here."""
    import _run_ref

    current = _run_ref.folder_current_run(run_dir)
    theirs = report.get("run_id")
    if current is None or not isinstance(theirs, str) or not theirs or theirs == current:
        return
    which = "superseded" if _run_ref.has_ledger(run_dir, theirs) else "not_bound"
    print(
        f"Error: {FOLDER_REFUSALS[which]['code']}: this report was composed for run {theirs}, but this folder belongs "
        f"to run {current}. Compose the report again for {current}, then run this again. Nothing was printed.",
        file=sys.stderr,
    )
    sys.exit(2)


def refuse_another_runs_report(report: dict[str, Any], ours: str | None) -> None:
    """Exit 2, nothing printed or written, when report.json was composed for another run than this folder's.
    A missing id on either side is not compared: a report from before the stamp, or artifacts with no run id."""
    theirs = report.get("run_id")
    if isinstance(theirs, str) and theirs and ours and theirs != ours:
        print(
            f"Error: {REFUSAL['code']}: this report was written by an earlier run ({theirs}), not this one "
            f"({ours}). Compose the report again for this run, then run this again. Nothing was printed.",
            file=sys.stderr,
        )
        sys.exit(2)


def build(report: dict[str, Any], deliverables: list[tuple[str, str | None]]) -> str:
    verdict = report.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise ValueError("report.json carries no verdict")
    parts: list[str] = []
    for i, (label, href) in enumerate(deliverables):
        tail = ""
        if i == 0:
            tail = " — where you stand against each competitor, and the evidence behind every placement"
        parts.append((f"[{label}]({href})" if href else label) + tail)
    lines = [
        f"Here's your finished competitive positioning analysis: {'; '.join(parts)}.",
        "",
        verdict.strip(),
        "",
        "If you want to keep the working data behind this — to pick it up later, or feed it into "
        "another analysis — say so and I'll send it as a single archive.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Print the founder-facing hand-over message from report.json")
    p.add_argument("--report", required=True)
    p.add_argument(
        "--deliverable", action="append", default=[], help="LABEL=PATH, repeatable, in the order to list them"
    )
    p.add_argument("--link", choices=["auto", "computer", "path", "none"], default="auto")
    a = p.parse_args()
    link = detect_link_form(os.getcwd(), dict(os.environ)) if a.link == "auto" else a.link
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _cp_gates

    try:
        with open(a.report, encoding="utf-8") as fh:
            report = json.load(fh)
        if not isinstance(report, dict):
            raise ValueError("report.json is not an object")
        refuse_another_runs_report(report, _cp_gates.run_id_of(os.path.dirname(os.path.abspath(a.report))))
        refuse_report_of_another_folder_run(report, os.path.dirname(os.path.abspath(a.report)))
        text = build(report, _deliverables(a.deliverable, link))
    except (OSError, ValueError) as e:
        print(f"Error: cannot build the hand-over from report {a.report}: {e}", file=sys.stderr)
        sys.exit(2)
    host_run = _cp_gates.host_delivers(a.report)
    if host_run is not None:
        # FS_HOST_NO_HANDOVER: the host delivers its own output. After every refusal above, so a report that
        # cannot build never prints the line. A failed write removes this folder's older handover.txt instead,
        # so an earlier hand-over is never left as the newest; only a failed removal too exits 2.
        line = _cp_gates.host_delivers_line() + "\n"
        handover = os.path.join(os.path.dirname(os.path.abspath(a.report)), HANDOVER_FILENAME)
        try:
            with open(handover, "w", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as e:
            try:
                if os.path.lexists(handover):
                    os.remove(handover)
            except OSError as e2:
                print(f"Error: could not write {handover} ({e}) or remove it ({e2})", file=sys.stderr)
                sys.exit(2)
            print(f"Warning: could not write {handover} ({e}); removed the older one", file=sys.stderr)
        _cp_gates.stamp_handed_over(a.report, host=host_run)
        sys.stdout.write(line)
        return
    handover = os.path.join(os.path.dirname(os.path.abspath(a.report)), HANDOVER_FILENAME)
    try:
        with open(handover, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        print(f"Warning: could not write {handover}: {e}", file=sys.stderr)
    try:
        # With a run ledger, the status records when the hand-over was printed; nothing here changes stdout.
        _cp_gates.stamp_handed_over(a.report)
    except Exception as e:  # noqa: BLE001 -- the hand-over is printed whatever happens here
        print(f"warning: the hand-over time was not recorded in the run status: {e}", file=sys.stderr)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
