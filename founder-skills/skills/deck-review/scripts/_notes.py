"""Shared predicate for the checklist `notes` field — the founder-facing fix.

`notes` is contracted (see `references/artifact-schemas.md` and the CHECKLIST dispatch
in SKILL.md) as *the specific change the founder should make*: imperative, concrete,
particular to this deck. It is required on `fail`/`warn` and omitted on `pass`.

Two renderers read it — `compose_report.py` (markdown) and `visualize.py` (HTML) — and
they must agree, so the predicate lives here rather than being duplicated. A duplicated
check drifts, and the drift is invisible: the same string would be suppressed in one
delivered artifact and rendered in the other.

WHAT THIS CANNOT DO: decide whether prose is genuinely an action. That is semantic, and
a script cannot judge it. `looks_like_methodology` is a deliberately narrow tripwire for
the ONE shape observed in the wild — a past-tense reporting verb opening, e.g.
"Checked slides 1 and 2, the only two slides with purpose-defining language." It will be
evaded by any rephrasing. Do NOT grow the verb list when it misses: an enumerated
blocklist is unwinnable (the same conclusion `cowork-tests/leak_scan.py` reached), and a
longer list buys a false sense of coverage. The real guarantee is the live acceptance
run, not this function.
"""

from __future__ import annotations

import re
from typing import Any

# Past-tense reporting verbs that open a methodology note rather than a fix. Narrow by
# design — see the module docstring on why this list must not grow.
_METHODOLOGY_OPENERS = (
    "checked",
    "reviewed",
    "verified",
    "confirmed",
    "examined",
    "assessed",
    "looked at",
    "inspected",
)

_LEADING_PUNCT = re.compile(r"^[\s\-*_>`\"'(\[]+")

# What may follow the verb and still be that verb. Whitespace of any kind (a tab or a
# newline is not a rephrasing), plus the punctuation a sentence or a markdown emphasis
# run can put there — "**Checked** slides" leaves the closing "*" in this position once
# the opening one is stripped.
_BOUNDARY = frozenset(" \t\n\r\f\v,:;.*—–-")


def looks_like_methodology(notes: Any) -> bool:
    """True when `notes` opens like a record of what was checked, not a fix.

    Advisory only. A true result means "suppress this and warn", never "fail the run" —
    the check is a heuristic and can false-positive, and the cost asymmetry favours
    suppression: a false positive drops one candidate (another backfills it), while a
    false negative delivers bookkeeping to a founder as advice.
    """
    if not isinstance(notes, str):
        return False
    head = _LEADING_PUNCT.sub("", notes).lower()
    return any(
        head.startswith(verb) and (len(head) == len(verb) or head[len(verb)] in _BOUNDARY)
        for verb in _METHODOLOGY_OPENERS
    )


def usable_fix(notes: Any) -> str | None:
    """Return `notes` when it can be presented to a founder as a fix, else None.

    Callers MUST treat None as "no fix available for this item" and skip the candidate —
    never fall back to the criterion label. A label ("Company purpose is clear and
    specific") is a criterion name, not a change to make, and rendering one both misleads
    and consumes a slot that a real fix could have used.
    """
    if not isinstance(notes, str):
        return None
    text = notes.strip()
    if not text:
        return None
    if looks_like_methodology(text):
        return None
    return text
