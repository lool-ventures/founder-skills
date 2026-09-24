#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Does the founder's message carry the printed hand-over whole, and add nothing numeric?

ONE OWNER. The e2e lane and the Stop hook (`stop_handover_check.py`) both ask this question, and a
rule with two copies drifts: the lane greens on one reading while the hook blocks on another. Both
load this file by path (plugin-root `scripts/` has no package), so the rule lives here and nowhere
else.

THE RULE. Link targets are dropped (`](…)` -> `]()`), because the two runtimes render different
links for the same file and a rewritten `computer://` path is not a rewritten message; whitespace
is squashed, because a re-typed indent is not a change. Then (1) the printed text must appear in
the message as one contiguous run -- a dropped line or a reordered sentence fails -- and (2) what
remains once it is removed may carry no digit. Containment rather than digit-absence because a
message is also wrong when it DELETES: at hostloop the model kept one printed line of four and
rewrote two, one of them without a digit, which no digit check can see.

Deliberately blind to a digit-free paraphrase around the message ("a greeting before it is fine").
"""

from __future__ import annotations

import re

_LINK_TARGET = re.compile(r"\]\([^)]*\)")
_DIGIT = re.compile(r"\d")


def squash(text: str) -> str:
    """Whitespace-normalised, link targets dropped."""
    return " ".join(_LINK_TARGET.sub("]()", text).split())


def contained(printed: str, final: str) -> tuple[bool, str]:
    """(ok, reason). `reason` is empty when ok, otherwise one line naming which rule failed."""
    want = squash(printed)
    got = squash(final)
    if not want:
        return False, "the printed hand-over is empty"
    if want not in got:
        return False, "the printed hand-over was not sent whole"
    remainder = got.replace(want, "", 1)
    m = _DIGIT.search(remainder)
    if m:
        start = max(0, m.start() - 40)
        snippet = remainder[start : m.start() + 60]
        return False, f"text with a figure was added around the printed hand-over: …{snippet}…"
    return True, ""
