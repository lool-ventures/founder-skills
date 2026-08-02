"""Per-slot capture targets for the landing page gallery.

This is the part that DRIFTS. When a skill's report template changes, a capture
starts framing the wrong thing — and the page's caption silently becomes a lie,
because the caption asserts what the image proves. Isolating the selectors here
means a re-shoot is a config edit rather than a rewrite.

`anchor` is matched case-insensitively against heading text. The capture scrolls
so that heading sits `offset` px below the top of the viewport, then shoots
1000x750 at deviceScaleFactor 1.6 -> 1600x1200 intrinsic.

`proves` is the page caption this frame has to support. If a capture stops
showing that, fix the capture or change the caption — do not quietly ship it.
"""

TARGETS = {
    "deck-review": {
        "file": "deck-review.html",
        "anchor": "overall score",
        "offset": 12,
        "proves": "The critique names the slide and the fix, not the category.",
    },
    "cap-table": {
        "file": "cap-table.html",
        "anchor": "series a:",
        "offset": 12,
        "proves": "Every line of math points at the rule it came from.",
    },
    "financial-model-review": {
        "file": "financial-model-review.html",
        "anchor": "runway",
        "offset": 12,
        "proves": "A date, not an adjective — and the decision points before it.",
    },
    "market-sizing": {
        "file": "market-sizing.html",
        "anchor": "sensitivity",
        "offset": 12,
        "proves": "A range you can defend beats a number you cannot.",
    },
    "competitive-positioning": {
        "file": "competitive-positioning.html",
        "anchor": "positioning map: primary",
        "offset": 12,
        "proves": "Where you actually sit, including the competitors you did not list.",
    },
    "ic-simulation": {
        "file": "ic-simulation.html",
        "anchor": "partner",
        "offset": 12,
        "proves": "Two partners, one deck, opposite conclusions.",
    },
}

# Intrinsic output is 1600x1200. Rendering at 1000x750 with DPR 1.6 gets there
# with the report's own content column (max-width 960-1100px) filling the frame.
# A flat 1600px viewport would leave ~320px of empty band each side.
VIEWPORT = (1000, 750)
DPR = 1.6
