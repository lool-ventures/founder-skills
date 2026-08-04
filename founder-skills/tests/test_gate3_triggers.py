"""Exhaustive tests for the Gate 3 trigger predicate.

These exist because one of the four triggers is effectively unreachable in a live run. Two paid
Cowork runs both fired Gate 3 on the MEAN trigger (21% each), so the trade-off-shape trigger — added
after a measured real case (rank 10 of 11 on one axis, 3 of 11 on the other) — had no behavioural
evidence, and buying that evidence would mean engineering a deck whose scored map has a specific
shape. Offline, all four are exhaustively checkable for free.

The arithmetic is pinned in the script's docstring; each threshold below asserts one of those pins,
so a change to a threshold must break a test rather than silently re-grade every trigger.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "scripts" / "gate3_triggers.py"


def _view(
    *,
    view_id: str = "v1",
    x_rank: int = 3,
    y_rank: int = 3,
    competitor_count: int = 9,
    x_vanity: bool = False,
    y_vanity: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    v: dict[str, Any] = {
        "view_id": view_id,
        "startup_x_rank": x_rank,
        "startup_y_rank": y_rank,
        "competitor_count": competitor_count,
        "x_axis_vanity_flag": x_vanity,
        "y_axis_vanity_flag": y_vanity,
        "x_axis_name": "firmness",
        "y_axis_name": "integration burden",
    }
    if label is not None:
        v["label"] = label
    return v


def _run(scores: dict[str, Any], tmp_path: Path) -> tuple[int, dict[str, Any], str]:
    p = tmp_path / "positioning_scores.json"
    p.write_text(json.dumps(scores), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--scores", str(p)], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout), proc.stderr


def _ids(result: dict[str, Any]) -> set[str]:
    return {t["id"] for t in result["triggers"]}


# --- the trigger that could not be reached live ------------------------------


def test_trade_off_shape_fires_on_the_measured_real_shape(tmp_path: Path) -> None:
    """The live case: 10th of 11 on one axis, 3rd of 11 on the other.

    NOTE this is deliberately paired with a HEALTHY mean, which is the whole point: on the real run
    the mean trigger fired too and masked this one. With the mean above the threshold, only the
    trade-off trigger can catch the shape.
    """
    rc, res, _ = _run(
        {"views": [_view(x_rank=10, y_rank=3, competitor_count=10)], "overall_differentiation": 60.0},
        tmp_path,
    )
    assert rc == 0
    assert "trade_off_shape" in _ids(res)
    assert "low_overall_differentiation" not in _ids(res), "the mean is healthy; only the shape should fire"


def test_trade_off_needs_bottom_quartile_not_merely_bottom_half(tmp_path: Path) -> None:
    """n=10: bottom quartile is rank > 7.5, so rank 7 is bottom-half but NOT bottom-quartile."""
    _, res, _ = _run(
        {"views": [_view(x_rank=7, y_rank=1, competitor_count=9)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "trade_off_shape" not in _ids(res)


def test_trade_off_fires_in_either_axis_order(tmp_path: Path) -> None:
    for x, y in ((10, 2), (2, 10)):
        _, res, _ = _run(
            {"views": [_view(x_rank=x, y_rank=y, competitor_count=10)], "overall_differentiation": 60.0},
            tmp_path,
        )
        assert "trade_off_shape" in _ids(res), f"x={x} y={y}"


def test_trade_off_strong_side_boundary_is_the_top_TERCILE(tmp_path: Path) -> None:
    """The strong side is `rank <= n/3`, NOT `rank <= 2`.

    This test is why the threshold changed. The motivating live case is 10th of 11 on one axis and
    3rd of 11 on the other; `rank <= 2` excludes 3rd, so the trigger missed the exact shape it was
    created for. No live run would have surfaced that, because the mean trigger fires on that same
    data and masks the miss. n=11 gives a tercile bound of 3.67: rank 3 qualifies, rank 4 does not.
    """
    _, at_bound, _ = _run(
        {"views": [_view(x_rank=10, y_rank=3, competitor_count=10)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "trade_off_shape" in _ids(at_bound), "3rd of 11 is inside the top tercile"

    _, past_bound, _ = _run(
        {"views": [_view(x_rank=10, y_rank=4, competitor_count=10)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "trade_off_shape" not in _ids(past_bound), "4th of 11 is outside the top tercile"


def test_trade_off_description_names_both_sides(tmp_path: Path) -> None:
    """The founder-facing text must say which axis is strong and which is weak, since 'a trade-off'
    alone is not actionable."""
    _, res, _ = _run(
        {"views": [_view(x_rank=10, y_rank=3, competitor_count=10)], "overall_differentiation": 60.0}, tmp_path
    )
    desc = next(t["description"] for t in res["triggers"] if t["id"] == "trade_off_shape")
    assert "integration burden" in desc and "firmness" in desc
    assert "3rd of 11" in desc and "10th of 11" in desc


# --- small sets: not_evaluated, never "did not fire" ------------------------


def test_small_set_reports_not_evaluated_rather_than_silence(tmp_path: Path) -> None:
    """A quartile is meaningless on 3 points. 'We could not tell' and 'we checked and it is fine'
    are different claims to make to a founder."""
    _, res, stderr = _run(
        {"views": [_view(x_rank=3, y_rank=1, competitor_count=2)], "overall_differentiation": 60.0}, tmp_path
    )
    reasons = [ne["trigger"] for ne in res["not_evaluated"]]
    assert "trade_off_shape" in reasons
    assert "trade_off_shape" not in _ids(res)
    assert "Not evaluated" in stderr


def test_quartile_is_evaluated_at_the_minimum_set_size(tmp_path: Path) -> None:
    """n = competitor_count + 1, so competitor_count 3 gives n=4 — the floor."""
    _, res, _ = _run(
        {"views": [_view(x_rank=4, y_rank=1, competitor_count=3)], "overall_differentiation": 60.0}, tmp_path
    )
    assert [ne["trigger"] for ne in res["not_evaluated"]] == []
    assert "trade_off_shape" in _ids(res)


# --- the pre-existing triggers ----------------------------------------------


def test_bottom_half_on_both_axes(tmp_path: Path) -> None:
    _, res, _ = _run(
        {"views": [_view(x_rank=8, y_rank=9, competitor_count=9)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "bottom_half_both_axes" in _ids(res)


def test_bottom_half_boundary(tmp_path: Path) -> None:
    """n=10, bottom half is rank > 5. Rank 5 must not fire; rank 6 must."""
    _, a, _ = _run(
        {"views": [_view(x_rank=5, y_rank=5, competitor_count=9)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "bottom_half_both_axes" not in _ids(a)
    _, b, _ = _run(
        {"views": [_view(x_rank=6, y_rank=6, competitor_count=9)], "overall_differentiation": 60.0}, tmp_path
    )
    assert "bottom_half_both_axes" in _ids(b)


def test_flattering_pattern_needs_both_vanity_flags_false(tmp_path: Path) -> None:
    _, fires, _ = _run(
        {"views": [_view(x_rank=1, y_rank=2, competitor_count=9)], "overall_differentiation": 90.0}, tmp_path
    )
    assert "flattering_both_axes" in _ids(fires)
    _, suppressed, _ = _run(
        {
            "views": [_view(x_rank=1, y_rank=2, competitor_count=9, x_vanity=True)],
            "overall_differentiation": 90.0,
        },
        tmp_path,
    )
    assert "flattering_both_axes" not in _ids(suppressed), "a vanity-flagged axis explains the flattering result"


def test_low_overall_differentiation(tmp_path: Path) -> None:
    _, res, _ = _run(
        {"views": [_view(x_rank=5, y_rank=1, competitor_count=9)], "overall_differentiation": 21.0}, tmp_path
    )
    assert "low_overall_differentiation" in _ids(res)


def test_low_differentiation_boundary_is_strictly_below_25(tmp_path: Path) -> None:
    _, at, _ = _run(
        {"views": [_view(x_rank=5, y_rank=1, competitor_count=9)], "overall_differentiation": 25.0}, tmp_path
    )
    assert "low_overall_differentiation" not in _ids(at)


def test_file_level_trigger_reported_once_across_two_views(tmp_path: Path) -> None:
    """overall_differentiation is a mean across views, so reporting it per view would double-count."""
    _, res, _ = _run(
        {
            "views": [
                _view(view_id="v1", x_rank=5, y_rank=1, competitor_count=9),
                _view(view_id="v2", x_rank=4, y_rank=2, competitor_count=9),
            ],
            "overall_differentiation": 21.0,
        },
        tmp_path,
    )
    assert [t["id"] for t in res["triggers"]].count("low_overall_differentiation") == 1


# --- per-view evaluation and primary-view identification -------------------


def test_a_secondary_view_can_fire_on_its_own(tmp_path: Path) -> None:
    """The measured gap: evaluating only the primary view hides a trade-off on a secondary one."""
    _, res, _ = _run(
        {
            "views": [
                _view(view_id="clean", x_rank=4, y_rank=4, competitor_count=10),
                _view(view_id="tradeoff", x_rank=11, y_rank=1, competitor_count=10),
            ],
            "overall_differentiation": 60.0,
        },
        tmp_path,
    )
    fired = [t for t in res["triggers"] if t["id"] == "trade_off_shape"]
    assert len(fired) == 1
    assert fired[0]["view_id"] == "tradeoff"


def test_primary_view_is_views_zero_not_a_literal_id(tmp_path: Path) -> None:
    """Real runs use descriptive slug ids, so matching the literal 'primary' would find nothing."""
    _, res, _ = _run(
        {
            "views": [_view(view_id="firmness-x-burden"), _view(view_id="secondary")],
            "overall_differentiation": 60.0,
        },
        tmp_path,
    )
    assert res["views"][0]["primary"] is True
    assert res["views"][1]["primary"] is False


def test_label_is_used_for_display_but_is_not_a_primary_signal(tmp_path: Path) -> None:
    _, res, _ = _run(
        {"views": [_view(view_id="v-slug", label="Capacity firmness")], "overall_differentiation": 60.0},
        tmp_path,
    )
    assert res["views"][0]["label"] == "Capacity firmness"


# --- robustness -------------------------------------------------------------


def test_no_triggers_is_a_clean_report_not_a_failure(tmp_path: Path) -> None:
    rc, res, _ = _run(
        {"views": [_view(x_rank=4, y_rank=4, competitor_count=9)], "overall_differentiation": 60.0}, tmp_path
    )
    assert rc == 0
    assert res["fired"] is False
    assert res["triggers"] == []


def test_malformed_view_is_not_evaluated_rather_than_crashing(tmp_path: Path) -> None:
    rc, res, _ = _run({"views": [{"view_id": "broken"}], "overall_differentiation": 60.0}, tmp_path)
    assert rc == 0
    assert [ne["trigger"] for ne in res["not_evaluated"]] == ["all"]


def test_missing_overall_differentiation_is_silent(tmp_path: Path) -> None:
    _, res, _ = _run({"views": [_view(x_rank=4, y_rank=4, competitor_count=9)]}, tmp_path)
    assert "low_overall_differentiation" not in _ids(res)


def test_no_views_at_all(tmp_path: Path) -> None:
    rc, res, _ = _run({"views": []}, tmp_path)
    assert rc == 0 and res["fired"] is False
