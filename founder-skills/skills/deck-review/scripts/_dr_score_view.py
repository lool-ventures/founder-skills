"""The deck-craft score and its verdict, worded once for report.md and the report page.

`compose_report.py` and `visualize.py` both print the score, the band's one-line verdict and the number of
criteria the score is taken over. Each is decided here and nowhere else, so the two deliverables cannot
state the same review two ways.

Standard library only, no CLI, no output, and no `_ui` import: compose loads this module, and the report
builder must not start loading the page module. It decides no score: `checklist.py` wrote the score and the
band, and a band this module does not know is re-derived from the score by `_thresholds.band_for`, the one
place the band edges are written (called here, never re-typed).
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Mapping
from typing import Any

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# By bare name, as compose and the page load it. market-sizing ships its own `_thresholds.py`, and
# `sys.modules` is process-global: a test that calls `band()` in-process after importing a market-sizing
# module would get market-sizing's edges. Production runs one skill per process; in-process tests call only
# `score_text` (the subprocess composes exercise `band()`).
import _thresholds  # noqa: E402

# The one-line verdict printed after the score, keyed on the band. Craft language only: these used to
# promise investability ("investor-ready"), which the report disclaims one line below, and half credit for
# a warn widened that string's reach (25 pass / 10 warn moved Solid -> Strong). A deck can meet every craft
# criterion and still be uninvestable. `{scored}` is the criteria count the score is taken over.
BAND_VERDICT: dict[str, str] = {
    "strong": "Strong — meets nearly all {scored} scored craft criteria; what is left is polish",
    "solid": "Solid — a well-built deck with a few craft gaps to close",
    "needs_work": "Needs Work — several craft gaps to close before sending",
    "major_revision": "Major Revision — worth reworking before it goes out; see the fixes below",
}


def score_text(pct: Any) -> str:
    """The score as both surfaces print it, without the percent sign: one decimal at most and no trailing
    zero ("63", "95.6"). The fleet's format; a test holds it equal to `_ui.score_text`."""
    return f"{round(float(pct), 1):g}"


def scored_criteria(summary: Mapping[str, Any] | None) -> int:
    """How many criteria the score counts, read from the artifact (`summary.scored`).

    Not `total`: one of the 35 listed criteria duplicates another and carries no weight, so the founder is
    told the number the score is actually taken over. A checklist written before `scored` existed counted
    every listed criterion, so its `total` is the honest figure there.
    """
    summary = summary if isinstance(summary, Mapping) else {}
    for key in ("scored", "total"):
        value = summary.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 34


def score(summary: Mapping[str, Any] | None) -> float | None:
    """The score, clamped to 0-100; None when `score_pct` is not a finite number (a checklist compose flags as
    a schema violation but still renders), so no surface prints a figure the artifact does not hold."""
    summary = summary if isinstance(summary, Mapping) else {}
    value = summary.get("score_pct")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return max(0.0, min(100.0, float(value)))


def band(summary: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    """(score, band). The band is the one `checklist.py` wrote, or, for a checklist with none or one this
    module does not know, the band its score falls in; None when there is neither."""
    summary = summary if isinstance(summary, Mapping) else {}
    pct = score(summary)
    status: str | None = str(summary.get("overall_status") or "").strip()
    if status not in BAND_VERDICT:
        status = _thresholds.band_for(pct) if pct is not None else None
    return pct, status


def verdict(summary: Mapping[str, Any] | None) -> str:
    """The band's one-line verdict for this score; "" when there is no band."""
    _pct, name = band(summary)
    return BAND_VERDICT[name].format(scored=scored_criteria(summary)) if name else ""


def score_line(summary: Mapping[str, Any] | None) -> str:
    """The figure and verdict report.md prints after "Deck-craft score:" ("63% — Needs Work — …"); "not
    recorded" in place of the figure when the checklist holds no number."""
    pct = score(summary)
    shown = f"{score_text(pct)}%" if pct is not None else "not recorded"
    said = verdict(summary)
    return f"{shown} — {said}" if said else shown
