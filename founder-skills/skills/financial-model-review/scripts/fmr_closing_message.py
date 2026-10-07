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

Exit 2 if the report cannot be read or carries no verdict; a failed handover.txt write is a stderr line.
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
# Printed with --cash-update, on the re-run after the founder answers that request. Without it the model
# announced the update in its own words around the hand-over on the re-run turn, which the Stop hook then
# corrected with a second message; the sentence it wanted to write is printed here instead.
CASH_UPDATE = "I've added the cash balance you gave me and recomputed your runway; the files above are updated."


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
    try:
        with open(a.report, encoding="utf-8") as fh:
            report = json.load(fh)
        if not isinstance(report, dict):
            raise ValueError("report.json is not an object")
        text = build(report, _deliverables(a.deliverable, link), cash_update=a.cash_update)
    except (OSError, ValueError) as e:
        print(f"Error: cannot build the hand-over from report {a.report}: {e}", file=sys.stderr)
        sys.exit(2)
    handover = os.path.join(os.path.dirname(os.path.abspath(a.report)), HANDOVER_FILENAME)
    try:
        with open(handover, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        print(f"Warning: could not write {handover}: {e}", file=sys.stderr)
    # A run with a gate ledger records when its hand-over was printed; nothing here changes stdout.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _fmr_gates  # noqa: PLC0415

    _fmr_gates.stamp_handed_over(a.report)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
