#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Competitive positioning scorer.

Takes pair-centric positioning views from positioning.json and produces
scored output with rank-based differentiation scores, vanity axis detection,
and stress-test passthrough.

Always reads JSON from stdin.

Usage:
    echo '{"views": [...], "differentiation_claims": [...], ...}' \
        | python score_positioning.py --pretty

Output: JSON with per-view scores, overall differentiation, and warnings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


# ---------------------------------------------------------------------------
# Vanity axis detection
# ---------------------------------------------------------------------------


def _is_vanity_axis(competitor_values: list[float]) -> bool:
    """Check if >80% of competitor values cluster within 20% of the 0-100 range.

    The axis range is always 0-100, so 20% of the range = 20 units.
    We check whether >80% of competitors fall within any 20-unit window.
    """
    if len(competitor_values) < 2:
        return False

    threshold = 0.8
    window = 20  # 20% of the 0-100 range
    n = len(competitor_values)
    sorted_vals = sorted(competitor_values)

    # Sliding window: check if >80% fit within any 20-unit span
    for i in range(n):
        count = 0
        for j in range(n):
            if sorted_vals[i] <= sorted_vals[j] <= sorted_vals[i] + window:
                count += 1
        if count / n > threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Rank-based differentiation
# ---------------------------------------------------------------------------


def _compute_rank(startup_val: float, competitor_vals: list[float]) -> int:
    """Compute 1-based rank of startup among competitors (1 = highest value)."""
    rank = 1
    for cv in competitor_vals:
        if cv > startup_val:
            rank += 1
    return rank


def _score_view(view: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score a single positioning view. Returns (scored_view, warnings)."""
    warnings: list[dict[str, Any]] = []
    points = view["points"]

    # Separate startup from competitors
    startup_point = None
    competitor_points = []
    for p in points:
        if p["competitor"] == "_startup":
            startup_point = p
        else:
            competitor_points.append(p)

    if startup_point is None:
        # Caller should have validated this already
        raise ValueError("_startup not found in view points")

    n = len(competitor_points)
    startup_x = float(startup_point["x"])
    startup_y = float(startup_point["y"])

    comp_x_vals = [float(p["x"]) for p in competitor_points]
    comp_y_vals = [float(p["y"]) for p in competitor_points]

    # Vanity detection (competitors only)
    x_vanity = _is_vanity_axis(comp_x_vals)
    y_vanity = _is_vanity_axis(comp_y_vals)

    if x_vanity:
        warnings.append(
            {
                "code": "VANITY_AXIS_WARNING",
                "severity": "medium",
                "message": (
                    f"View '{view['id']}': X-axis '{view.get('x_axis', {}).get('name', 'X')}'"
                    " flagged as vanity — >80% of competitors cluster within 20% of the axis range"
                ),
            }
        )
    if y_vanity:
        warnings.append(
            {
                "code": "VANITY_AXIS_WARNING",
                "severity": "medium",
                "message": (
                    f"View '{view['id']}': Y-axis '{view.get('y_axis', {}).get('name', 'Y')}'"
                    " flagged as vanity — >80% of competitors cluster within 20% of the axis range"
                ),
            }
        )

    # Rank-based differentiation with distance weighting
    rank_x = _compute_rank(startup_x, comp_x_vals)
    rank_y = _compute_rank(startup_y, comp_y_vals)

    # Distance-weighted formula: rank contributes 50%, gap contributes 50%.
    # This distinguishes "barely ahead" (rank 1, gap 2%) from "dramatically
    # ahead" (rank 1, gap 40%).
    if n > 0:
        x_rank_score = (n - rank_x + 1) / n * 50
        y_rank_score = (n - rank_y + 1) / n * 50

        # Gap: how far ahead the startup is from the next-best competitor
        # on each axis (0-1 scale, clamped to 0 if startup is behind).
        sorted_x_desc = sorted(comp_x_vals, reverse=True)
        sorted_y_desc = sorted(comp_y_vals, reverse=True)
        next_best_x = sorted_x_desc[0] if sorted_x_desc else startup_x
        next_best_y = sorted_y_desc[0] if sorted_y_desc else startup_y
        gap_x = max(0.0, (startup_x - next_best_x) / 100)
        gap_y = max(0.0, (startup_y - next_best_y) / 100)

        x_gap_score = gap_x * 50
        y_gap_score = gap_y * 50

        diff_score = min(100.0, round((x_rank_score + x_gap_score + y_rank_score + y_gap_score) / 2, 1))
    else:
        diff_score = 0.0

    scored_view = {
        "view_id": view["id"],
        "x_axis_name": view.get("x_axis", {}).get("name", "X"),
        "y_axis_name": view.get("y_axis", {}).get("name", "Y"),
        "x_axis_rationale": view.get("x_axis", {}).get("rationale", ""),
        "y_axis_rationale": view.get("y_axis", {}).get("rationale", ""),
        "x_axis_vanity_flag": x_vanity,
        "y_axis_vanity_flag": y_vanity,
        "differentiation_score": diff_score,
        "startup_x_rank": rank_x,
        "startup_y_rank": rank_y,
        "competitor_count": n,
    }
    return scored_view, warnings


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_input(data: dict[str, Any]) -> list[str]:
    """Validate input structure. Returns list of error messages."""
    errors: list[str] = []

    if "views" not in data or not isinstance(data.get("views"), list):
        errors.append("'views' must be a non-empty array")
        return errors

    if len(data["views"]) == 0:
        errors.append("At least one view is required")
        return errors

    for i, view in enumerate(data["views"]):
        if not isinstance(view, dict):
            errors.append(f"views[{i}] must be an object")
            continue

        for field in ("id", "x_axis", "y_axis", "points"):
            if field not in view:
                errors.append(f"views[{i}] missing required field '{field}'")

        for axis_key in ("x_axis", "y_axis"):
            axis = view.get(axis_key)
            if axis is not None and not isinstance(axis, dict):
                errors.append(f"views[{i}].{axis_key} must be an object")
            elif isinstance(axis, dict) and "name" not in axis:
                errors.append(f"views[{i}].{axis_key} missing required field 'name'")

        if "points" not in view:
            continue

        points = view["points"]
        if not isinstance(points, list):
            errors.append(f"views[{i}].points must be an array, got {type(points).__name__}")
            continue

        has_startup = False
        seen_competitors: set[str] = set()
        for j, p in enumerate(points):
            if not isinstance(p, dict):
                errors.append(f"views[{i}].points[{j}] must be an object")
                continue

            if p.get("competitor") == "_startup":
                has_startup = True

            comp_slug = p.get("competitor", "")
            if comp_slug:
                if comp_slug in seen_competitors:
                    errors.append(f"views[{i}].points[{j}]: duplicate competitor '{comp_slug}'")
                seen_competitors.add(comp_slug)

            # Coordinate validation — x and y are required
            for coord in ("x", "y"):
                val = p.get(coord)
                if val is None:
                    errors.append(f"views[{i}].points[{j}].{coord} is required")
                elif not isinstance(val, (int, float)):
                    errors.append(f"views[{i}].points[{j}].{coord} must be a number")
                elif val < 0 or val > 100:
                    errors.append(f"views[{i}].points[{j}].{coord}={val} out of range 0-100")

        if not has_startup:
            errors.append(f"views[{i}] missing '_startup' in points")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Positioning scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"views\": [...]}' | python score_positioning.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        sys.exit(1)

    errors = _validate_input(data)
    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Score each view
    scored_views: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []

    for view in data["views"]:
        sv, warns = _score_view(view)
        scored_views.append(sv)
        all_warnings.extend(warns)

    # Aggregate differentiation
    if scored_views:
        overall = round(sum(v["differentiation_score"] for v in scored_views) / len(scored_views), 1)
    else:
        overall = 0.0

    result: dict[str, Any] = {
        "views": scored_views,
        "overall_differentiation": overall,
        "differentiation_claims": data.get("differentiation_claims", []),
        "warnings": all_warnings,
        "_produced_by": "score_positioning",
        "metadata": data.get("metadata", {}),
    }

    # Passthrough data_confidence if present
    if "data_confidence" in data:
        result["data_confidence"] = data["data_confidence"]

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"overall_differentiation": overall} if scored_views else None,
    )


if __name__ == "__main__":
    main()
