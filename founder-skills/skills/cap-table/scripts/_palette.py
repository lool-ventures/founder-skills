#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Single source of truth for cap-table ownership-class colors, labels, and
render order. Imported by both visualize.py (report) and explore.py (explorer)
so the two artifacts can never drift on color (design finding E3).

Class colors: four are brand tokens (founders/preferred=blue family,
option_pool=warning amber, new_money=success green); safe (violet) and note
(terracotta) are categorical hues chosen for distinguishability; other_common
is a muted slate shown only when non-founder common stock exists.
"""

from __future__ import annotations

# Zero-cutoff: a class below this fraction (0.05%) is dropped from BOTH the
# donut and the legend so the two views never disagree.
EPS = 0.0005

PALETTE: dict[str, str] = {
    "founders": "#0D549D",
    "other_common": "#5E6E82",
    "preferred": "#365A8A",
    "option_pool": "#C9892B",
    "safe": "#7A5EA8",
    "note": "#B0563C",
    "new_money": "#2F8A56",
    "warrants": "#48B4EA",
    "neutral": "#A6AEB5",
}

LABELS: dict[str, str] = {
    "founders": "Founders",
    "other_common": "Other common",
    "new_money": "New investors",
    "option_pool": "Option pool",
    "safe": "SAFEs (converted)",
    "preferred": "Preferred",
    "note": "Notes (converted)",
    "warrants": "Warrants",
}

# Wedge / row order. other_common sits directly after founders in both.
# Every renderable class (all PALETTE keys except neutral) MUST appear here —
# the renderers iterate these lists and silently drop any key not listed.
ORDER_DONUT = ["founders", "other_common", "preferred", "option_pool", "safe", "note", "new_money", "warrants"]
ORDER_LEGEND = ["founders", "other_common", "new_money", "option_pool", "safe", "preferred", "note", "warrants"]


def _strip(cat: str) -> str:
    return cat.removesuffix("_pct")


def slice_color(cat: str) -> str:
    """Color for an ownership class, tolerating the `_pct` suffix the producer
    aggregate keys carry (e.g. ``founders_pct``). Unknown → neutral."""
    return PALETTE.get(_strip(cat), PALETTE["neutral"])


def slice_label(cat: str) -> str:
    """Human label for an ownership class, tolerating the `_pct` suffix.
    Unknown → de-underscored title."""
    return LABELS.get(_strip(cat), _strip(cat).replace("_", " "))
