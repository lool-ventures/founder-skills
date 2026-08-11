"""Deck-craft score bands — the single definition, shared by the scorer and the gauge.

`checklist.py` selects the band; `visualize.py` paints the gauge arcs and ticks. Those
used to be independent literals, so the HTML could render a needle in the red zone under
a caption saying "Needs Work". Same numbers, one place.

WHY A LOCAL MODULE AND NOT `import checklist`: `checklist.py` is the same filename in
four skills and `sys.modules` is process-global — the first importer in an in-process
pytest session would win for all of them. `_`-prefixed and deck-review-local, matching
`_notes.py` / `_theme.py`.

WHY THESE VALUES DO NOT MOVE (measured, 2026-08-11 — read before "recalibrating"):

  * `SOLID` sits above the `CHECKLIST_FAILURES_CRITICAL` gate. That warning fires at
    high severity when `fail > 10`, and with 11 failures the maximum attainable score is
    68.6% — under this formula and under any partial credit for `warn`, since the
    maximum is attained at `warn == 0`. Any threshold above 68.6 preserves the property
    that a deck cannot be called "solid" while carrying a critical-failures warning.
    Lowering `SOLID` breaks it: a proposed 42 would have printed "Solid — good
    foundation" beside "12 failures (>10 — critical threshold)".

  * `NEEDS_WORK` was NOT lowered to spread the corpus, though every deck measured lands
    below it. Four distinct decks span 28.6-38.6 (10 points), while the SAME deck moved
    up to 7.1 points between two runs that changed no scoring code. A boundary inside a
    cluster narrower than its own run-to-run noise flips bands on re-runs of an
    unchanged deck, which reads as arbitrary to the founder receiving it.

REVISIT WHEN, and not before: a deck scores >= 50 (an observation outside the cluster),
or the corpus sample reaches ~10 decks — enough to place a boundary with more than one
grid step of clearance. The grid step is 100/(2*applicable): 1.43 points at 35
applicable, so 85.0 is not even attainable there (84.3 / 85.7 straddle it).
"""

from __future__ import annotations

STRONG = 85.0
SOLID = 70.0
NEEDS_WORK = 50.0

# High -> low, for the gauge's zone arcs and for band selection.
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


def zone_edges() -> tuple[float, ...]:
    """Ascending gauge-zone boundaries, DERIVED from BANDS.

    Derived, not restated: `band_for` iterates BANDS while this used to read the
    constants, so editing BANDS alone would have moved the label without moving the
    arc — the needle-contradicts-caption failure this module exists to prevent.
    """
    return (0.0, *sorted(t for t, _ in BANDS), 100.0)
