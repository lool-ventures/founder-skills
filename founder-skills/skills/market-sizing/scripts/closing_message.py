#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the founder-facing hand-over message from report.json.

WHY. The closing message used to be composed in chat, from memory, after a rule that said never to
compute a figure there. On a live run it said "$4.66M ... about 2% of the illustrative $100M" -- it
is 4.7% -- and nothing checked it. A first cut printed the headline figures here; measured at
hostloop, the model kept one line of four, rewrote two, deleted one and appended its own verdict
paragraph with ratios it rounded itself. The paragraph was the verdict, and nothing on the page
carried it. A second cut moved the verdict to the report's first paragraph and made this message
the links, one pointer at that page, and the offer -- no figure. Measured 0/2 at hostloop: the model
dropped the pointer and wrote the verdict itself, in front of the links, with its own rounding. Each
time it wrote the answer to the question it was asked, in the channel it was asked in, because no
printed message yet contained one. So this message now carries the report's own verdict paragraph
(compose_report.py's `verdict`, the same words the page opens with), with a legend for the marks it
quotes. What it prints is also written to `handover.txt` beside the report, for the check that runs
after the model's final turn.

WHICH LINK FORM. Measured in a real cloud-lane Cowork session (2026-09-22, the default lane for new
sessions): `computer://` links render as PLAIN TEXT, and a bare path becomes a broken
`https://claude.ai/<path>` URL -- no link form opens a file there; the share card is the only
delivery. On the desktop-local lane (`/sessions/<id>` tree) `computer://` links open. On the CLI a
bare path is right. So `--link auto` (the default) decides from the shell's cwd and the lane's env
markers, and `none` prints each label with its path in a code span rather than three dead links
above a working card -- the path is still stated, since a stated path is the one thing that survives
every surface.

Usage:
    closing_message.py --report R --deliverable "LABEL=PATH" [--deliverable ...]
                       [--link auto|computer|path|none]

Exit 2 if the report cannot be read; a failed `handover.txt` write is a stderr line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


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
            href = None  # rendered as "label (`path`)": the path is still stated, just not linked
        else:
            href = path.strip()
        out.append((label.strip(), href if href else f"`{path.strip()}`"))
    return out


HANDOVER_FILENAME = "handover.txt"

# The verdict is written for the page; in chat "see Warnings" names a section the reader cannot see.
_PAGE_PHRASES = (
    ("see Warnings", "see the report's warnings"),
    ("see Adversarial Findings", "see the report's adversarial findings"),
)
_MARK_LEGEND = (
    ("\u2020", "one computation shown two ways, not two that agree"),
    ("\u2021", "both builds narrow this figure by the same number, so their agreement is no cross-check"),
    ("\u00a7", "built on a figure you stated that a cited source contradicts"),
)


def verdict_for_chat(verdict: str) -> str:
    """The report's verdict paragraph as chat text: page-relative phrases rewritten, marks explained."""
    text = verdict.strip()
    for page, chat in _PAGE_PHRASES:
        text = text.replace(page, chat)
    legend = [f"{mark} {gloss}" for mark, gloss in _MARK_LEGEND if mark in text]
    if legend:
        text += "\n(" + "; ".join(legend) + ".)"
    return text


def build(report: dict[str, Any], deliverables: list[tuple[str, str | None]]) -> str:
    verdict = report.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise ValueError("report.json carries no verdict")
    parts: list[str] = []
    for i, (label, href) in enumerate(deliverables):
        tail = ""
        if i == 0:
            tail = (
                " \u2014 it opens with the verdict: what your materials claim, what each build found, "
                "and the strongest challenge to it"
            )
        elif label.lower().startswith("the interactive"):
            tail = " has the charts"
        # `none` arrives as a backticked path: state the path even when no link form opens it,
        # because the stated path is the one thing that survives every surface (ccinternals.dev/
        # cowork, "delivery.name-the-path-anyway").
        parts.append((f"{label} ({href})" if href and href.startswith("`") else f"[{label}]({href})") + tail)
    lines = [
        f"Here's your finished market sizing: {'; '.join(parts)}.",
        "",
        verdict_for_chat(verdict),
        "",
        "If you want to keep the working data behind this \u2014 to pick it up later, or feed it into "
        "another analysis \u2014 say so and I'll send it as a single archive.",
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
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
