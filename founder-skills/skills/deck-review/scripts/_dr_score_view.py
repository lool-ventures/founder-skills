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


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    f = float(value)
    return f if math.isfinite(f) else 0.0


def band(summary: Mapping[str, Any] | None) -> tuple[float, str]:
    """(score, band). The score is clamped to 0-100; the band is the one `checklist.py` wrote, or, for a
    checklist with none or one this module does not know, the band its score falls in."""
    summary = summary if isinstance(summary, Mapping) else {}
    pct = max(0.0, min(100.0, _num(summary.get("score_pct"))))
    status = str(summary.get("overall_status") or "").strip()
    if status not in BAND_VERDICT:
        status = _thresholds.band_for(pct)
    return pct, status


def verdict(summary: Mapping[str, Any] | None) -> str:
    """The band's one-line verdict for this score."""
    _pct, name = band(summary)
    return BAND_VERDICT[name].format(scored=scored_criteria(summary))
