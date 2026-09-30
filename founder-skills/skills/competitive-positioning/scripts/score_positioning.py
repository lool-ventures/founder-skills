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
import hashlib
import json
import os
import sys
from typing import Any

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import _axis_compat  # noqa: E402


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


_HIGHER_IS_BETTER = "higher_is_better"
_LOWER_IS_BETTER = "lower_is_better"


def _axis_polarity(view: dict[str, Any], axis: str) -> str:
    """Which direction is GOOD on this axis. `axis` is "x" or "y".

    Canonical shape is nested: view["x_axis"]["polarity"]. A view-level sibling
    (view["x_axis_polarity"]) is accepted for the same reason `_axis_compat` accepts one for
    rationale — dispatch templates have instructed both shapes over time.

    Defaults to higher-is-better. That is not a preference: every artifact written before this field
    existed omits it, and the default is what keeps them scoring exactly as they did.
    """
    axis_obj = view.get(f"{axis}_axis")
    raw = axis_obj.get("polarity") if isinstance(axis_obj, dict) else None
    if not raw:
        raw = view.get(f"{axis}_axis_polarity")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return _HIGHER_IS_BETTER
    # Anything present but unrecognised is REJECTED upstream by _validate_input rather than
    # coerced here. Coercing sent "lower is better" — a plausible way for a model to say the
    # opposite — to higher_is_better, silently, which is the exact defect polarity exists to prevent.
    # That guarantee holds only while _validate_input's nested->sibling fallback uses the same
    # falsy test this one does; when it tested `is None` instead, an empty nested value hid an
    # invalid sibling from validation and this line coerced it after all. Change both together.
    return _LOWER_IS_BETTER if str(raw).strip().lower() == _LOWER_IS_BETTER else _HIGHER_IS_BETTER


def _compute_rank(startup_val: float, competitor_vals: list[float], lower_is_better: bool = False) -> int:
    """Compute 1-based rank of startup among competitors (1 = BEST).

    "Best" depends on the axis. This function counted competitors with a higher value and returned
    that, which is correct only when higher is better. On a price axis it inverted: a live run placed
    a startup second-cheapest of nine and reported it as ranking last, and the same number feeds
    `differentiation_score` at 50% weight, so the formula rewarded being expensive.
    """
    rank = 1
    for cv in competitor_vals:
        if (cv < startup_val) if lower_is_better else (cv > startup_val):
            rank += 1
    return rank


def _geometry(
    startup_point: dict[str, Any],
    competitor_points: list[dict[str, Any]],
    x_lower_better: bool,
    y_lower_better: bool,
) -> dict[str, Any]:
    """Who beats the startup on both axes, who is nearest, and the lead over the best rival per axis.

    `dominated_by`: competitors at least as good on both axes and strictly better on one -- "no
    competitor beats you on both axes" is the direct answer to an investor's "why won't X crush
    you". `x_lead_over_best` / `y_lead_over_best`: the startup's value minus the best competitor's,
    signed so positive means ahead; negative means that many points behind the leader.
    `nearest_competitor` / `nearest_distance`: straight-line distance on the two 0-100 axes.
    `x_best_competitors` / `y_best_competitors`: the competitor(s) the lead is measured against.
    """
    sx, sy = float(startup_point["x"]), float(startup_point["y"])

    def better(a: float, b: float, lower: bool) -> bool:
        return a < b if lower else a > b

    def at_least(a: float, b: float, lower: bool) -> bool:
        return a <= b if lower else a >= b

    dominated_by: list[str] = []
    nearest: str | None = None
    nearest_d: float | None = None
    for p in competitor_points:
        px, py = float(p["x"]), float(p["y"])
        slug = str(p["competitor"])
        if (
            at_least(px, sx, x_lower_better)
            and at_least(py, sy, y_lower_better)
            and (better(px, sx, x_lower_better) or better(py, sy, y_lower_better))
        ):
            dominated_by.append(slug)
        d = ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5
        if nearest_d is None or d < nearest_d or (d == nearest_d and slug < str(nearest)):
            nearest, nearest_d = slug, d

    def lead(values: list[float], own: float, lower: bool) -> float | None:
        if not values:
            return None
        best = min(values) if lower else max(values)
        return round(best - own if lower else own - best, 1)

    def best_of(axis: str, lower: bool) -> list[str]:
        values = [float(p[axis]) for p in competitor_points]
        if not values:
            return []
        best = min(values) if lower else max(values)
        return sorted(str(p["competitor"]) for p in competitor_points if float(p[axis]) == best)

    return {
        "x_best_competitors": best_of("x", x_lower_better),
        "y_best_competitors": best_of("y", y_lower_better),
        "dominated_by": sorted(dominated_by),
        "nearest_competitor": nearest,
        "nearest_distance": None if nearest_d is None else round(nearest_d, 1),
        "x_lead_over_best": lead([float(p["x"]) for p in competitor_points], sx, x_lower_better),
        "y_lead_over_best": lead([float(p["y"]) for p in competitor_points], sy, y_lower_better),
    }


CLAIM_VERDICTS = ("holds", "partially_holds", "does_not_hold", "unproven")


def _verdict_counts(claims: Any) -> dict[str, int]:
    """Tally of stress-test verdicts. `unrecognised` holds anything outside CLAIM_VERDICTS, so the
    parts always sum to `total`."""
    counts = dict.fromkeys(CLAIM_VERDICTS, 0)
    counts["unrecognised"] = 0
    items = claims if isinstance(claims, list) else []
    for claim in items:
        verdict = claim.get("verdict") if isinstance(claim, dict) else None
        counts[verdict if verdict in CLAIM_VERDICTS else "unrecognised"] += 1
    counts["total"] = len(items)
    return counts


PROOF_LEVELS = ("shipping", "customer_validated", "demonstrated", "claimed")
AVAILABILITY = ("concept", "poc", "pilot", "shipping")


def _planned(point: dict[str, Any]) -> tuple[float, float] | None:
    px, py = point.get("planned_x"), point.get("planned_y")
    if isinstance(px, (int, float)) and isinstance(py, (int, float)):
        return float(px), float(py)
    return None


def _today_block(
    today_point: dict[str, Any],
    competitor_points: list[dict[str, Any]],
    x_lower_better: bool,
    y_lower_better: bool,
    availability: str | None,
) -> dict[str, Any]:
    """Where the startup is today, when a planned point is the scored one.

    Built only from today's `x`/`y` -- never a planned value -- because scoring the plan as the
    present is the failure this separation exists to prevent. Ranked only when availability says
    there is something to buy.
    """
    tx, ty = float(today_point["x"]), float(today_point["y"])
    return {
        "x": tx,
        "y": ty,
        "ranked": availability == "shipping",
        "startup_x_rank": _compute_rank(tx, [float(p["x"]) for p in competitor_points], x_lower_better),
        "startup_y_rank": _compute_rank(ty, [float(p["y"]) for p in competitor_points], y_lower_better),
        "startup_x_tied_with": sorted(str(p["competitor"]) for p in competitor_points if float(p["x"]) == tx),
        "startup_y_tied_with": sorted(str(p["competitor"]) for p in competitor_points if float(p["y"]) == ty),
        **_geometry({"x": tx, "y": ty}, competitor_points, x_lower_better, y_lower_better),
    }


def _score_view(view: dict[str, Any], availability: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score a single positioning view. Returns (scored_view, warnings).

    PLAN-STAGE STARTUPS. Most users raise on a plan, not a shipping product, and a baseline run
    placed a pre-product startup's planned price and claimed abilities as its position TODAY. When
    `_startup` carries `planned_x`/`planned_y`, the PLANNED point is the scored one: rank, ties,
    geometry and the score are computed on it, so every reader (Gate 3 included) sees the plan and no
    field chooses a headline. Today's coordinates are scored separately into `today`, which carries
    no planned value, and is `ranked: false` unless `product_availability` is "shipping".
    RESIDUAL: availability is recorded by the analysis; a false "shipping" ranks today's point, which
    recreates the baseline's failure on the today view (the headline still says "if delivered").
    """
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

    today_point = startup_point
    planned = _planned(startup_point)
    if planned is not None:
        startup_point = {**startup_point, "x": planned[0], "y": planned[1]}

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
    x_polarity = _axis_polarity(view, "x")
    y_polarity = _axis_polarity(view, "y")
    x_lower_better = x_polarity == _LOWER_IS_BETTER
    y_lower_better = y_polarity == _LOWER_IS_BETTER
    rank_x = _compute_rank(startup_x, comp_x_vals, x_lower_better)
    rank_y = _compute_rank(startup_y, comp_y_vals, y_lower_better)

    # Distance-weighted formula: rank contributes 50%, gap contributes 50%.
    # This distinguishes "barely ahead" (rank 1, gap 2%) from "dramatically
    # ahead" (rank 1, gap 40%).
    if n > 0:
        x_rank_score = (n - rank_x + 1) / n * 50
        y_rank_score = (n - rank_y + 1) / n * 50

        # Gap: how far ahead the startup is from the next-best competitor
        # on each axis (0-1 scale, clamped to 0 if startup is behind).
        #
        # Polarity applies HERE TOO, and this is the half that is easy to miss: "next best" is the
        # MAXIMUM competitor only when higher is better. On a lower-is-better axis the strongest rival
        # is the cheapest one, and the gap runs the other way. Fixing the rank alone would leave the
        # other 50% of the score still rewarding the wrong direction.
        best_x = (min(comp_x_vals) if x_lower_better else max(comp_x_vals)) if comp_x_vals else startup_x
        best_y = (min(comp_y_vals) if y_lower_better else max(comp_y_vals)) if comp_y_vals else startup_y
        gap_x = max(0.0, (best_x - startup_x if x_lower_better else startup_x - best_x) / 100)
        gap_y = max(0.0, (best_y - startup_y if y_lower_better else startup_y - best_y) / 100)

        x_gap_score = gap_x * 50
        y_gap_score = gap_y * 50

        diff_score = min(100.0, round((x_rank_score + x_gap_score + y_rank_score + y_gap_score) / 2, 1))
    else:
        diff_score = 0.0

    # Axis rationale — read tolerantly through the shared helper. Canonical shape is
    # nested (view["x_axis"]["rationale"]); a large body of already-written artifacts
    # carries it as a view-level sibling (view["x_axis_rationale"]) because the dispatch
    # templates used to instruct that shape. See _axis_compat.py.
    x_rationale = _axis_compat.axis_rationale(view, "x")
    y_rationale = _axis_compat.axis_rationale(view, "y")

    if not x_rationale:
        warnings.append(
            {
                "code": "RATIONALE_MISSING",
                "severity": "medium",
                "message": (
                    f"View '{view['id']}': the X-axis has no stated rationale — "
                    "explain what the axis measures and why it separates these companies"
                ),
            }
        )
    if not y_rationale:
        warnings.append(
            {
                "code": "RATIONALE_MISSING",
                "severity": "medium",
                "message": (
                    f"View '{view['id']}': the Y-axis has no stated rationale — "
                    "explain what the axis measures and why it separates these companies"
                ),
            }
        )

    scored_view = {
        "view_id": view["id"],
        "x_axis_name": view.get("x_axis", {}).get("name", "X"),
        "y_axis_name": view.get("y_axis", {}).get("name", "Y"),
        "x_axis_rationale": x_rationale,
        "y_axis_rationale": y_rationale,
        # RESOLVED polarity, always emitted, never absent. Two jobs. Downstream consumers stop
        # re-deriving "which end is good" from an input view they may not be holding; and
        # `views_fingerprint` reads it back through `_axis_polarity`'s sibling branch, so the
        # hash covers scoring semantics and not just coordinates. Before this, flipping an axis
        # changed rank and differentiation_score while the fingerprint stayed byte-identical,
        # which let a checklist graded against the OLD orientation still read fresh.
        "x_axis_polarity": x_polarity,
        "y_axis_polarity": y_polarity,
        "x_axis_vanity_flag": x_vanity,
        "y_axis_vanity_flag": y_vanity,
        "differentiation_score": diff_score,
        "startup_x_rank": rank_x,
        "startup_y_rank": rank_y,
        # Competitors at exactly the startup's value. `startup_*_rank` counts only those strictly
        # ahead, so a tie takes the better place; these lists let every reader state the tie
        # instead (the rank and the score are unchanged, so fixtures and gates keep their numbers).
        "startup_x_tied_with": sorted(str(p["competitor"]) for p in competitor_points if float(p["x"]) == startup_x),
        "startup_y_tied_with": sorted(str(p["competitor"]) for p in competitor_points if float(p["y"]) == startup_y),
        "competitor_count": n,
        # Geometry, computed here so no renderer derives it and no model writes it. Polarity-aware:
        # "ahead" always means better on the axis. Used to state the startup's position in words
        # instead of the differentiation score, which reads as a percentage and is blind to spacing
        # (two maps at the same rank but with the nearest rival 3 vs 10 points away score the same).
        **_geometry(startup_point, competitor_points, x_lower_better, y_lower_better),
        "scored_point": "planned" if planned is not None else "today",
        **(
            {"today": _today_block(today_point, competitor_points, x_lower_better, y_lower_better, availability)}
            if planned is not None
            else {}
        ),
        # Passthrough of the input view's per-competitor coordinates. Coordinates are
        # assigned upstream (by the founder/main thread, or refined by the POSITIONING_SCORING
        # sub-agent) and validated, never recomputed here — this just makes
        # positioning_scores.json a self-contained record of them alongside the aggregates,
        # instead of forcing every downstream consumer back to positioning.json for points[].
        "points": points,
    }

    # Optional human-readable view label (e.g. "Speed vs. Price") passed through when the
    # main thread supplied one on the input view. Absent must stay absent — never inferred
    # from `id`, never required. Consumers title-case `id` when this key is missing.
    if isinstance(view.get("label"), str) and view["label"].strip():
        scored_view["label"] = view["label"]

    return scored_view, warnings


# ---------------------------------------------------------------------------
# Views fingerprint
# ---------------------------------------------------------------------------


def _fingerprint_row(p: dict[str, Any]) -> list[Any]:
    row: list[Any] = [
        str(p.get("competitor", "")),
        round(float(p.get("x", 0) or 0), 4),
        round(float(p.get("y", 0) or 0), 4),
    ]
    plan = _planned(p)
    if plan is not None:
        row += [round(plan[0], 4), round(plan[1], 4)]
    return row


def views_fingerprint(views: list[dict]) -> str:
    """Stable hash of the scored map's identity. Excludes ALL prose (evidence, rationale,
    provenance) so a reworded evidence string is not a moved map. Order-insensitive over
    views and over points.

    Includes resolved axis POLARITY, which is not prose: it decides which end of an axis is
    good, and therefore rank and `differentiation_score`. Omitting it made the hash blind to
    a real change in meaning — same points, same axis names, opposite scoring — so a
    `checklist.json` graded before the flip still compared equal and read fresh.

    Polarity is encoded ONLY when it is not the default, and resolved through `_axis_polarity`
    so every accepted input shape lands on the same value. That keeps two properties at once:
    a flip to lower-is-better moves the hash (the defect this closes), while an artifact
    written before the field existed — and one that states `higher_is_better` explicitly —
    hash identically, because their scoring semantics ARE identical. Without that, adding the
    key would have re-stamped every fingerprint in flight and reported a map as moved when
    nothing about it changed.
    """
    payload = []
    for v in sorted(views, key=lambda d: str(d.get("view_id", d.get("id", "")))):
        # A planned point is identity too (it is the scored one); encoded only when present, so a map
        # with no plan hashes as it did before the field existed.
        pts = sorted([_fingerprint_row(p) for p in v.get("points", []) or [] if isinstance(p, dict)])
        entry = {
            "view_id": str(v.get("view_id", v.get("id", ""))),
            "x_axis_name": str(v.get("x_axis_name", "")),
            "y_axis_name": str(v.get("y_axis_name", "")),
            "points": pts,
        }
        for axis in ("x", "y"):
            if _axis_polarity(v, axis) == _LOWER_IS_BETTER:
                entry[f"{axis}_axis_polarity"] = _LOWER_IS_BETTER
        payload.append(entry)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_positioning_input(data: dict[str, Any]) -> list[str]:
    """Normalize common LLM output shape mismatches in-place.
    Fixes: String axes → {name: <string>}, points[].slug → points[].competitor
    Returns list of error strings (empty on success).
    """
    normalized = False
    errors: list[str] = []
    views = data.get("views")
    if not isinstance(views, list):
        return errors

    for i, view in enumerate(views):
        if not isinstance(view, dict):
            continue
        # Normalize string axes to objects (reject blank strings)
        for axis_key in ("x_axis", "y_axis"):
            val = view.get(axis_key)
            if isinstance(val, str):
                if not val.strip():
                    errors.append(f"views[{i}].{axis_key}: axis name is blank")
                    continue
                view[axis_key] = {"name": val}
                normalized = True
        # Normalize slug → competitor in points
        points = view.get("points")
        if not isinstance(points, list):
            continue
        for j, point in enumerate(points):
            if not isinstance(point, dict):
                continue
            if "slug" in point and "competitor" not in point:
                slug_val = point["slug"]
                if not isinstance(slug_val, str) or not slug_val.strip():
                    errors.append(f"views[{i}].points[{j}]: 'slug' is empty/blank, cannot normalize to 'competitor'")
                    continue
                point["competitor"] = point.pop("slug")
                normalized = True
            elif "slug" in point and "competitor" in point:
                slug_val = point.pop("slug")
                if slug_val != point["competitor"]:
                    errors.append(
                        f"views[{i}].points[{j}]: conflicting 'slug' ('{slug_val}')"
                        f" and 'competitor' ('{point['competitor']}')"
                    )
                else:
                    normalized = True
    if errors:
        return errors
    if normalized:
        print("score_positioning: normalized input (string axes or slug→competitor)", file=sys.stderr)
    return []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_SCORING_BASIS = ("shipped", "roadmap_12mo", "mixed")
_VALID_POLARITY = (_HIGHER_IS_BETTER, _LOWER_IS_BETTER)


def _validate_input(data: dict[str, Any]) -> list[str]:
    """Validate input structure. Returns list of error messages."""
    errors: list[str] = []

    if "scoring_basis" in data and data["scoring_basis"] not in _VALID_SCORING_BASIS:
        errors.append(
            "'scoring_basis' must be one of: " + ", ".join(_VALID_SCORING_BASIS) + f" (got {data['scoring_basis']!r})"
        )

    if "views" not in data or not isinstance(data.get("views"), list):
        errors.append("'views' must be a non-empty array")
        return errors

    # Polarity decides what rank 1 MEANS, so an unrecognised value must not fall through to the
    # default. Measured: "lower is better", "Lower Is Better", "low_is_better" and "banana" all
    # resolved to higher_is_better — the first three being plausible attempts to say the opposite,
    # and the result being the founder told they rank last while second-cheapest. Rejected here for
    # the same reason `scoring_basis` above is: a wrong rank ships, a failed batch is repaired.
    for _vi, _view in enumerate(data["views"]):
        if not isinstance(_view, dict):
            continue
        for _ax in ("x", "y"):
            _obj = _view.get(f"{_ax}_axis")
            _raw = _obj.get("polarity") if isinstance(_obj, dict) else None
            # This fallback condition MUST mirror `_axis_polarity`'s (`if not raw:`), not test
            # `is None`. They disagreed, and the gap was silent: with a nested polarity of ""
            # this loop kept the empty string, treated it as absent on the next line, and never
            # looked at the sibling — while `_axis_polarity` fell through to the sibling and
            # coerced an unrecognised value to higher_is_better. Measured, `x_axis.polarity: ""`
            # plus `x_axis_polarity: "lower is better"` was ACCEPTED and scored a price axis
            # upside-down: the founder is told they rank 1st where they rank 6th. The fingerprint
            # cannot catch it either, since scoring and hashing share this resolution.
            if not _raw:
                _raw = _view.get(f"{_ax}_axis_polarity")
            if _raw is None or (isinstance(_raw, str) and not _raw.strip()):
                continue  # absent is legal and means higher_is_better
            if not isinstance(_raw, str) or _raw.strip().lower() not in _VALID_POLARITY:
                errors.append(
                    f"view {_vi} {_ax}_axis 'polarity' must be one of: "
                    + ", ".join(_VALID_POLARITY)
                    + f" (got {_raw!r}) — omit it for {_HIGHER_IS_BETTER}"
                )

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
                errors.append(
                    f"views[{i}].{axis_key} must be an object with at least a 'name' field, "
                    f'e.g. {{"name": "..."}}, got {type(axis).__name__}'
                )
            elif isinstance(axis, dict) and "name" not in axis:
                errors.append(
                    f"views[{i}].{axis_key} missing required field 'name'. "
                    'Expected: {"name": "Axis Name", "description": "...", "rationale": "..."} '
                    "(description and rationale are recommended but not enforced)"
                )

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

            comp = p.get("competitor")
            if not isinstance(comp, str) or not comp.strip():
                errors.append(f"views[{i}].points[{j}]: 'competitor' must be a non-empty string")
                continue

            if p.get("competitor") == "_startup":
                has_startup = True

            comp_slug = p.get("competitor", "")
            if comp_slug:
                if comp_slug in seen_competitors:
                    errors.append(f"views[{i}].points[{j}]: duplicate competitor '{comp_slug}'")
                seen_competitors.add(comp_slug)

            # Planned coordinates and proof levels: `_startup` only, both or neither, 0-100.
            has_plan = [k for k in ("planned_x", "planned_y") if k in p]
            if has_plan and p.get("competitor") != "_startup":
                errors.append(f"views[{i}].points[{j}]: planned coordinates are for _startup only")
            elif len(has_plan) == 1:
                errors.append(f"views[{i}].points[{j}]: planned_x and planned_y go together")
            for coord in has_plan:
                val = p.get(coord)
                if not isinstance(val, (int, float)) or isinstance(val, bool) or not 0 <= val <= 100:
                    errors.append(f"views[{i}].points[{j}].{coord} must be a number in 0-100")
            for proof in ("x_proof", "y_proof"):
                if proof in p and p[proof] not in PROOF_LEVELS:
                    errors.append(f"views[{i}].points[{j}].{proof} must be one of {list(PROOF_LEVELS)}")

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


def _read_availability(path: str | None) -> tuple[str | None, str | None]:
    """product_availability and its quote from product_profile.json; (None, None) when absent or unknown."""
    if not path:
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
    except (OSError, ValueError):
        return None, None
    if not isinstance(profile, dict):
        return None, None
    value = profile.get("product_availability")
    quote = profile.get("availability_quote")
    return (value if value in AVAILABILITY else None), (quote if isinstance(quote, str) and quote.strip() else None)


def _apply_run_id(result: dict, run_id: str | None) -> None:
    """CLI run_id overrides stdin-passthrough metadata.run_id (CLI > stdin)."""
    if not run_id:
        return
    md = result.get("metadata")
    if not isinstance(md, dict):
        md = {}
    md["run_id"] = run_id
    result["metadata"] = md


def _keep_first_copy(output_path: str, result: dict[str, Any]) -> None:
    """Keep this run's first scored copy beside the output (see `_cp_first_copy`)."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _cp_first_copy

    _cp_first_copy.keep_first(output_path, result)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Positioning scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--run-id",
        default=None,
        help="Stamp metadata.run_id (overrides any run_id from stdin metadata)",
    )
    p.add_argument(
        "--product-profile",
        default=None,
        help="product_profile.json: its product_availability decides whether today's point is ranked",
    )
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
    # Our own file names in the scorer's evidence become plain words HERE, at pipe time: the report's
    # wording pass flags any it finds, and removing one by hand after the outside review reads as an
    # analysis changed after it was reviewed. One table, shared with the review (`_cp_redteam_text`).
    import _cp_redteam_text

    _cp_redteam_text.reword_evidence(data)

    norm_errors = _normalize_positioning_input(data)
    if norm_errors:
        for err in norm_errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    errors = _validate_input(data)
    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Score each view
    availability, availability_quote = _read_availability(args.product_profile)
    scored_views: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []

    for view in data["views"]:
        sv, warns = _score_view(view, availability)
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
        # Counted here, once, so every surface states the same tally and the parts always sum to
        # the total: a fourth verdict (`unproven`) used to vanish from a three-way count that
        # still printed "(of N tested)" with N including it.
        "verdict_counts": _verdict_counts(data.get("differentiation_claims", [])),
        "warnings": all_warnings,
        "_produced_by": "score_positioning",
        "metadata": data.get("metadata", {}),
        # Order-insensitive identity hash of the scored map (views + points only, no
        # prose). checklist.py copies this verbatim into checklist.json's
        # graded_against.views_fingerprint rather than recomputing it — one
        # implementation, no drift. See views_fingerprint() above.
        "views_fingerprint": views_fingerprint(scored_views),
    }

    # Passthrough data_confidence if present
    if "data_confidence" in data:
        result["data_confidence"] = data["data_confidence"]

    # How far the product has got, as recorded in the product profile, with its quote. It decides
    # only whether a separate today point is ranked (see `_score_view`); stated so it can be checked.
    if availability is not None:
        result["product_availability"] = availability
        if availability_quote:
            result["availability_quote"] = availability_quote

    # Passthrough scoring_basis if present. Deliberately NOT defaulted when absent —
    # artifacts produced before this convention existed have a genuinely undefined
    # basis, and stamping "shipped" on them would assert a convention that was never
    # in force. Absence must stay distinguishable from an explicit declaration.
    if "scoring_basis" in data:
        result["scoring_basis"] = data["scoring_basis"]

    _apply_run_id(result, args.run_id)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    summary = {"overall_differentiation": overall} if scored_views else None
    _write_output(out, args.output, summary=summary)
    if args.output:
        _keep_first_copy(args.output, result)

    # Summary to stderr for visibility in batch runs
    if scored_views:
        print(
            f"score_positioning: overall_differentiation={overall:.1f}%"
            f", views={len(scored_views)}"
            f", warnings={len(result.get('warnings', []))}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
