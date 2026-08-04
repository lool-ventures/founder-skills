"""Shared axis-rationale reader for competitive-positioning artifacts.

Two shapes exist in the wild for a positioning view's axis rationale:

- Canonical (nested), per ``references/artifact-schemas.md``:
  ``view["x_axis"]["rationale"]`` / ``view["y_axis"]["rationale"]``.
- Sibling, produced by an earlier version of the dispatch templates that
  instructed the sub-agent to emit the rationale alongside the axis object
  instead of inside it: ``view["x_axis_rationale"]`` / ``view["y_axis_rationale"]``.

A large body of already-written artifacts uses the sibling shape. Every
consumer that renders an axis rationale (score_positioning.py, visualize.py,
explore.py) must read tolerantly through this one helper so the three stay
in lockstep — no per-file reimplementation.
"""

from __future__ import annotations

from typing import Any


def axis_rationale(view: dict[str, Any], axis: str) -> str:
    """Read an axis rationale tolerantly. `axis` is "x" or "y".

    Canonical shape is nested: view["x_axis"]["rationale"] (references/artifact-schemas.md).
    A large body of already-written artifacts carries it as a view-level sibling
    (view["x_axis_rationale"]) because the dispatch templates instructed that shape. Prefer
    the nested value; fall back to the sibling. Returns "" when neither is present.
    """
    axis_key = f"{axis}_axis"
    sibling_key = f"{axis}_axis_rationale"

    axis_obj = view.get(axis_key)
    if isinstance(axis_obj, dict):
        nested = axis_obj.get("rationale")
        if isinstance(nested, str) and nested:
            return nested

    sibling = view.get(sibling_key)
    if isinstance(sibling, str) and sibling:
        return sibling

    return ""
