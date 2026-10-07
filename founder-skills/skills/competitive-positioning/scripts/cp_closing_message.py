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

Exit 2 if the report cannot be read or carries no verdict; a failed handover.txt write is a stderr line.
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
    try:
        with open(a.report, encoding="utf-8") as fh:
            report = json.load(fh)
        if not isinstance(report, dict):
            raise ValueError("report.json is not an object")
        text = build(report, _deliverables(a.deliverable, link))
    except (OSError, ValueError) as e:
        print(f"Error: cannot build the hand-over from report {a.report}: {e}", file=sys.stderr)
        sys.exit(2)
    handover = os.path.join(os.path.dirname(os.path.abspath(a.report)), HANDOVER_FILENAME)
    try:
        with open(handover, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        print(f"Warning: could not write {handover}: {e}", file=sys.stderr)
    try:
        # With a run ledger, the status records when the hand-over was printed; nothing here changes stdout.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import _cp_gates

        _cp_gates.stamp_handed_over(a.report)
    except Exception as e:  # noqa: BLE001 -- the hand-over is printed whatever happens here
        print(f"warning: the hand-over time was not recorded in the run status: {e}", file=sys.stderr)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
