#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Evaluate the Gate 3 positioning-reality-check triggers.

Reads `positioning_scores.json` and reports which triggers fire, per view, plus a plain-language
description for the founder-facing gate message.

WHY THIS IS A SCRIPT AND NOT PROSE.

The four triggers were previously prose the model evaluated per run. That had two costs. The first
is testability: a trigger can only be observed firing on data a live run happened to produce, and
one of the four — the trade-off shape — is effectively unreachable that way. Two paid live runs
both fired Gate 3 on the *mean* trigger (21% and 21%), so the trade-off trigger added to catch a
measured real case (rank 10 of 11 on one axis, 3 of 11 on the other) had no behavioural evidence at
all, and buying that evidence would mean engineering a deck whose scored map has a specific shape.
The second cost is arithmetic drift: "bottom quartile" has no single reading, so each run could
interpret it differently and nothing would notice.

Moving the predicate here makes all four exhaustively testable on synthetic inputs, for free, and
pins the arithmetic once. It does NOT make the model call the script — that remains an instruction,
and this file should not pretend otherwise. What it removes is the chance of the arithmetic being
wrong or inconsistent when it IS called.

THE ARITHMETIC, PINNED (do not "simplify" these — an exhaustive test suite asserts each one, so a
change here silently re-grades every trigger):

  * DENOMINATOR `n` = the number of entities ranked, INCLUDING `_startup` — i.e.
    `competitor_count + 1`. `_compute_rank` in score_positioning.py counts competitors strictly
    ahead and adds 1, so rank `competitor_count + 1` is reachable and means "behind every
    competitor". Using `competitor_count` as the denominator is what once printed
    "Y=11 (of 10 competitors)".
  * BOTTOM HALF: `rank > n / 2`.
  * BOTTOM QUARTILE: `rank > 0.75 * n`.
  * TOP 2: `rank <= 2` — used by the flattering-result trigger only.
  * TOP TERCILE: `rank <= n / 3` — the STRONG side of the trade-off trigger. This started as
    "top-2" and was WRONG: the motivating live case is 10th of 11 on one axis and 3rd of 11 on the
    other, and `rank <= 2` excludes 3rd, so the trigger missed the exact shape it was added for.
    An exhaustive test caught it; no live run would have, because the mean trigger fires on that
    data anyway and masks the miss. Top-tercile admits 3rd of 11 and still excludes 4th.
  * TIES take the WORSE rank. `_compute_rank` already does this (it counts strictly-ahead
    competitors), so a tie yields the higher — worse — rank number and needs no handling here.
  * SMALL SETS: a quartile is meaningless on very few points, so the two quartile-dependent
    readings are NOT EVALUATED when `n < 4`. That is reported as `not_evaluated`, never as
    "did not fire" — the distinction matters, because "we could not tell" and "we checked and it
    is fine" are different claims to make to a founder.

Usage:
    python gate3_triggers.py --scores <positioning_scores.json> [--pretty] [-o <file>]

Output (stdout JSON):
    {"fired": bool, "triggers": [...], "views": [...], "not_evaluated": [...]}
    Exit 0 always — this reports, it does not gate. Gate 3 is a founder decision, not a failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# --- pinned thresholds (see the module docstring) ---------------------------
_TOP_N = 2
_BOTTOM_HALF = 0.5
_BOTTOM_QUARTILE = 0.75
_TOP_TERCILE_DIVISOR = 3
_MIN_N_FOR_QUARTILE = 4
_LOW_DIFFERENTIATION_PCT = 25.0


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _ranked_total(view: dict[str, Any]) -> int | None:
    """n = entities ranked, startup included. None when the view cannot be evaluated."""
    count = view.get("competitor_count")
    if not isinstance(count, int) or count < 1:
        return None
    return count + 1


def _is_bottom_half(rank: int, n: int) -> bool:
    return rank > n * _BOTTOM_HALF


def _is_bottom_quartile(rank: int, n: int) -> bool:
    return rank > n * _BOTTOM_QUARTILE


def _is_top(rank: int) -> bool:
    return rank <= _TOP_N


def _is_top_tercile(rank: int, n: int) -> bool:
    """The strong side of a trade-off. See the docstring: `rank <= 2` misses the measured case."""
    return rank <= n / _TOP_TERCILE_DIVISOR


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def evaluate_view(view: dict[str, Any], overall_differentiation: float | None) -> dict[str, Any]:
    """Evaluate every trigger for one scored view."""
    vid = str(view.get("view_id", "?"))
    label = str(view.get("label") or "").strip() or vid
    x_rank = view.get("startup_x_rank")
    y_rank = view.get("startup_y_rank")
    n = _ranked_total(view)

    out: dict[str, Any] = {
        "view_id": vid,
        "label": label,
        "ranked_total": n,
        "startup_x_rank": x_rank,
        "startup_y_rank": y_rank,
        "triggers": [],
        "not_evaluated": [],
    }

    if n is None or not isinstance(x_rank, int) or not isinstance(y_rank, int):
        out["not_evaluated"].append(
            {
                "trigger": "all",
                "reason": "view lacks an integer competitor_count and both startup ranks",
            }
        )
        return out

    x_name = str(view.get("x_axis_name", "the X axis"))
    y_name = str(view.get("y_axis_name", "the Y axis"))

    # --- 1. bottom half on BOTH axes (PROVISIONAL) --------------------------
    if _is_bottom_half(x_rank, n) and _is_bottom_half(y_rank, n):
        out["triggers"].append(
            {
                "id": "bottom_half_both_axes",
                "provisional": True,
                "description": (
                    f"the scored position puts you in the bottom half of the set on both axes "
                    f"({_ordinal(x_rank)} of {n} on {x_name}, {_ordinal(y_rank)} of {n} on {y_name})"
                ),
            }
        )

    # --- 2. top-2 on BOTH axes with no vanity flag --------------------------
    x_vanity = bool(view.get("x_axis_vanity_flag"))
    y_vanity = bool(view.get("y_axis_vanity_flag"))
    if _is_top(x_rank) and _is_top(y_rank) and not x_vanity and not y_vanity:
        out["triggers"].append(
            {
                "id": "flattering_both_axes",
                "provisional": False,
                "description": (
                    "the scored position puts you top-2 on both axes with neither axis flagged as "
                    "undifferentiating — a result worth double-checking before you rely on it"
                ),
            }
        )

    # --- 3. trade-off shape: bottom quartile one axis, top-2 the other ------
    if n < _MIN_N_FOR_QUARTILE:
        out["not_evaluated"].append(
            {
                "trigger": "trade_off_shape",
                "reason": f"a quartile is not meaningful with {n} ranked entities (needs {_MIN_N_FOR_QUARTILE})",
            }
        )
    else:
        x_bq, y_bq = _is_bottom_quartile(x_rank, n), _is_bottom_quartile(y_rank, n)
        if (x_bq and _is_top_tercile(y_rank, n)) or (y_bq and _is_top_tercile(x_rank, n)):
            weak_axis, weak_rank = (x_name, x_rank) if x_bq else (y_name, y_rank)
            strong_axis, strong_rank = (y_name, y_rank) if x_bq else (x_name, x_rank)
            out["triggers"].append(
                {
                    "id": "trade_off_shape",
                    "provisional": True,
                    "description": (
                        f"the scored position is a genuine trade-off rather than a middling one — "
                        f"{_ordinal(strong_rank)} of {n} on {strong_axis} but {_ordinal(weak_rank)} of {n} "
                        f"on {weak_axis}"
                    ),
                }
            )

    # --- 4. low overall differentiation (PROVISIONAL) -----------------------
    # Reported once, on the view being evaluated, because the value is per-FILE (a mean across
    # views) rather than per-view. The caller de-duplicates.
    if isinstance(overall_differentiation, (int, float)) and overall_differentiation < _LOW_DIFFERENTIATION_PCT:
        out["triggers"].append(
            {
                "id": "low_overall_differentiation",
                "provisional": True,
                "file_level": True,
                "description": (
                    f"overall differentiation across the map came out at {overall_differentiation:.0f}%, on the low end"
                ),
            }
        )

    return out


def evaluate(scores: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every view. The primary view is views[0] — never a literal id match."""
    views = [_as_dict(v) for v in _as_list(scores.get("views"))]
    overall = scores.get("overall_differentiation")

    per_view: list[dict[str, Any]] = []
    for idx, view in enumerate(views):
        # The file-level differentiation trigger is offered to the primary view only, so a
        # two-view map does not report it twice.
        result = evaluate_view(view, overall if idx == 0 else None)
        result["primary"] = idx == 0
        per_view.append(result)

    fired = [{**t, "view_id": v["view_id"], "label": v["label"]} for v in per_view for t in v["triggers"]]
    not_evaluated = [{**ne, "view_id": v["view_id"]} for v in per_view for ne in v["not_evaluated"]]

    return {
        "fired": bool(fired),
        "triggers": fired,
        "views": per_view,
        "not_evaluated": not_evaluated,
        "overall_differentiation": overall,
        "_produced_by": "gate3_triggers",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate the Gate 3 positioning-reality-check triggers")
    p.add_argument("--scores", required=True, help="Path to positioning_scores.json")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        with open(args.scores, encoding="utf-8") as f:
            scores = json.load(f)
    except OSError as e:
        print(f"Error: could not read {args.scores}: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: {args.scores} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(scores, dict):
        print(f"Error: {args.scores} must be a JSON object", file=sys.stderr)
        sys.exit(1)

    result = evaluate(scores)
    out = json.dumps(result, indent=2 if args.pretty else None) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stdout.write(
            json.dumps({"ok": True, "path": args.output, "fired": result["fired"]}, separators=(",", ":")) + "\n"
        )
    else:
        sys.stdout.write(out)

    for t in result["triggers"]:
        print(f"Trigger: [{t['id']}] {t['description']}", file=sys.stderr)
    for ne in result["not_evaluated"]:
        print(f"Not evaluated: [{ne['trigger']}] {ne['reason']}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
