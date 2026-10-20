#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the founder-facing hand-over message from report.json, and write it to handover.txt.

The main thread sends this output as its final message, unchanged: the links, the report's own
verdict paragraph, and the offer of the working data. The hand-over used to be written by the model
from the coaching payload's headline fields, so runway and the model's rating reached the founder
restated or recomputed in chat -- the one founder-facing surface with no script between the model and
the reader. The shared Stop hook (founder-skills/scripts/stop_handover_check.py) compares the final
message against handover.txt, or against this script's output as the transcript recorded it when no
file is reachable -- so the last line printed must stay the offer. SKILL.md does not depend on it.

The same contract as market-sizing's closing_message.py and competitive-positioning's
cp_closing_message.py -- link forms per surface, the file written beside the report -- under its own
name, so the Stop hook tells the skills apart by script name.

The quick check (`financial-model-review-<slug>-quickcheck`) has no closer and writes no handover.txt,
so the hook's glob finds only the full review's file. If the quick check ever gets one, the hook reads
the newest handover.txt, which is the run just closed.

Usage:
    fmr_closing_message.py --report R --deliverable "LABEL=PATH" [--deliverable ...]
                           [--link auto|computer|path|none] [--cash-update]

Exit 2 if the report cannot be read, carries no verdict, or was composed for another run than this
folder's inputs (`RUN_ID_MISMATCH`: stdout empty, no handover.txt, no hand-over time); a failed
handover.txt write is a stderr line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HANDOVER_FILENAME = "handover.txt"
# report.json's `runway_status` when runway was not computed only for want of the cash balance
# (compose_report.py `_runway_status`). Kept out of the verdict: the verdict also opens the report, a
# document read later, where a request for the balance would point at nobody. Worded for any input --
# a spreadsheet, a deck or figures given in chat. SKILL.md Step 12 says how the balance is recorded and
# the review re-run when the founder replies.
NO_CASH_BALANCE = "no_cash_balance"
ASK_FOR_CASH_BALANCE = (
    "The figures you shared don't include your cash balance today, so I couldn't work out your runway; "
    "tell me your current cash balance and the date it's as of, and I'll recompute it."
)
# Printed when report.json's `disclosures` (a run with a gate ledger) says the extracted values went on
# unreviewed: compose_report.py's EXTRACTION_UNREVIEWED_TEXT, word for word (a test holds them equal). After
# the verdict, never in it: the verdict is also the report's opening paragraph.
EXTRACTION_UNREVIEWED = (
    "The figures this review used were not checked with you before the analysis ran, so check them against "
    "your model before relying on these numbers."
)
# Printed with --cash-update, on the re-run after the founder gives a cash balance (asked for, or a newer one
# or its date after delivery). Without it the model announced the update in its own words around the hand-over
# on the re-run turn, which the Stop hook then corrected with a second message; the sentence it wanted to
# write is printed here instead. "Used", not "added": the balance may replace one the review already had.
CASH_UPDATE = "I've used the cash balance you gave me and recomputed your runway; the files above are updated."


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
    A missing id on either side is not compared: a report from before the stamp, or inputs with no run id."""
    theirs = report.get("run_id")
    if isinstance(theirs, str) and theirs and ours and theirs != ours:
        print(
            f"Error: {REFUSAL['code']}: this report was written by an earlier run ({theirs}), not this one "
            f"({ours}). Compose the report again for this run, then run this again. Nothing was printed.",
            file=sys.stderr,
        )
        sys.exit(2)


def build(report: dict[str, Any], deliverables: list[tuple[str, str | None]], cash_update: bool = False) -> str:
    verdict = report.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise ValueError("report.json carries no verdict")
    parts: list[str] = []
    for i, (label, href) in enumerate(deliverables):
        tail = " — every check scored, with the evidence behind it" if i == 0 else ""
        parts.append((f"[{label}]({href})" if href else label) + tail)
    lines = [
        f"Here's your finished financial model review: {'; '.join(parts)}.",
        "",
    ]
    if cash_update:
        lines += [CASH_UPDATE, ""]
    lines.append(verdict.strip())
    # Optional sentences go here, after the verdict and BEFORE the offer: the Stop hook's fallback takes
    # this message from the transcript as the slice from the opener line to the offer's end, so anything
    # printed after the offer is invisible to it, and the offer must stay the last line.
    if "EXTRACTION_UNREVIEWED" in (report.get("disclosures") or []):
        lines += ["", EXTRACTION_UNREVIEWED]
    if report.get("runway_status") == NO_CASH_BALANCE:
        lines += ["", ASK_FOR_CASH_BALANCE]
    lines += [
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
    p.add_argument(
        "--cash-update", action="store_true", help="the re-run after the founder gave the cash balance it asked for"
    )
    a = p.parse_args()
    link = detect_link_form(os.getcwd(), dict(os.environ)) if a.link == "auto" else a.link
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _fmr_gates  # noqa: PLC0415

    try:
        with open(a.report, encoding="utf-8") as fh:
            report = json.load(fh)
        if not isinstance(report, dict):
            raise ValueError("report.json is not an object")
        refuse_another_runs_report(report, _fmr_gates.run_id_of(os.path.dirname(os.path.abspath(a.report))))
        refuse_report_of_another_folder_run(report, os.path.dirname(os.path.abspath(a.report)))
        text = build(report, _deliverables(a.deliverable, link), cash_update=a.cash_update)
    except (OSError, ValueError) as e:
        print(f"Error: cannot build the hand-over from report {a.report}: {e}", file=sys.stderr)
        sys.exit(2)
    host_run = _fmr_gates.host_delivers(a.report)
    if host_run is not None:
        # FS_HOST_NO_HANDOVER: the host delivers its own output. After every refusal above, so a report that
        # cannot build never prints the line. A failed write removes this folder's older handover.txt instead,
        # so an earlier hand-over is never left as the newest; only a failed removal too exits 2.
        line = _fmr_gates.host_delivers_line() + "\n"
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
        _fmr_gates.stamp_handed_over(a.report, host=host_run)
        sys.stdout.write(line)
        return
    handover = os.path.join(os.path.dirname(os.path.abspath(a.report)), HANDOVER_FILENAME)
    try:
        with open(handover, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        print(f"Warning: could not write {handover}: {e}", file=sys.stderr)
    # A run with a gate ledger records when its hand-over was printed; nothing here changes stdout.
    _fmr_gates.stamp_handed_over(a.report)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
