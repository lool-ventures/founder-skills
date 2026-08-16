"""Sizing-quality score bands — the fleet vocabulary, in one place.

`checklist.py` selects the band; anything that renders a grade reads it from here.

WHY A LOCAL MODULE AND NOT AN IMPORT: `checklist.py` is the same filename in four skills
and `sys.modules` is process-global, so the first importer in an in-process pytest session
would win for all of them. `_`-prefixed and market-sizing-local, matching `_theme.py`.

WHY THESE NUMBERS ARE NOT MARKET-SIZING'S TO TUNE. 85/70/50 are the fleet's, already
literal in competitive-positioning (`checklist.py:284-291`), financial-model-review
(`:966-971`) and deck-review (via its own `_thresholds.py`). A founder who runs two skills
gets two grades, and the words have to mean the same thing in both. If these move, they
move everywhere at once and for a reason that is about all four.

WHAT MARKET-SIZING ADDS: `all_pass`, and it is not a fifth band. The band answers "how
good is this sizing"; the boolean answers "is anything still outstanding". They are
genuinely independent — 21 of 22 items passing is 95.5%, a `strong` sizing that still has
one open item — and collapsing them is exactly what this file exists to undo. The producer
emitted the boolean alone, so 21/22 and 1/22 were the same word ("fail") and the
`score_pct` it already computed decided nothing.

THE 70 BOUNDARY IS LOAD-BEARING, and `compose_report.py`'s critical threshold is derived
from it rather than chosen: 7 failures cap the score at 15/22 = 68.2%, under 70; 6 can
still reach 72.7%. So "more than 6 failures" is precisely "cannot be called solid however
the rest scores". Changing SOLID without re-deriving that threshold decouples the two.
"""

from __future__ import annotations

STRONG = 85.0
SOLID = 70.0
NEEDS_WORK = 50.0

# High -> low, for band selection.
BANDS: tuple[tuple[float, str], ...] = (
    (STRONG, "strong"),
    (SOLID, "solid"),
    (NEEDS_WORK, "needs_work"),
)

FLOOR_BAND = "major_revision"


def band_for(score_pct: float) -> str:
    """The band a score falls in. The only place this comparison is written."""
    for threshold, name in BANDS:
        if score_pct >= threshold:
            return name
    return FLOOR_BAND
