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
    # no_edge is not evaluated here for a different reason (the fixture view carries no geometry).
    assert [ne["trigger"] for ne in res["not_evaluated"] if ne["trigger"] != "no_edge"] == []
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


# --- ties -------------------------------------------------------------------
# `startup_*_rank` counts only competitors strictly ahead, so a tie takes the better place. The
# scorer records who the startup is tied with, and a trigger reads a tie in the direction that makes
# it harder to fire. The docstring once claimed ties take the worse rank; they never did.


def test_flattering_fires_on_an_untied_top_two(tmp_path: Path) -> None:
    """Positive control for the tie tests below."""
    _, out, _ = _run({"views": [_view(x_rank=1, y_rank=2)]}, tmp_path)
    assert "flattering_both_axes" in _ids(out)


def test_a_tie_does_not_make_a_result_flattering(tmp_path: Path) -> None:
    """1st on firmness, but level with two competitors: 1st-3rd, not top-2."""
    v = _view(x_rank=1, y_rank=2)
    v["startup_x_tied_with"] = ["acme", "bolt"]
    _, out, _ = _run({"views": [v]}, tmp_path)
    assert "flattering_both_axes" not in _ids(out)


def test_a_tie_does_not_push_a_result_into_the_bottom_half(tmp_path: Path) -> None:
    """6th of 10 is bottom half; tied 5th-6th is not bottom half on every reading, so no fire."""
    control = _view(x_rank=6, y_rank=6, competitor_count=9)
    _, out, _ = _run({"views": [control]}, tmp_path)
    assert "bottom_half_both_axes" in _ids(out), "control: untied 6th of 10 on both axes fires"
    v = _view(x_rank=5, y_rank=6, competitor_count=9)
    v["startup_x_tied_with"] = ["acme"]
    _, out, _ = _run({"views": [v]}, tmp_path)
    assert "bottom_half_both_axes" not in _ids(out)


def test_a_fired_trigger_states_the_tie(tmp_path: Path) -> None:
    v = _view(x_rank=7, y_rank=8, competitor_count=9)
    v["startup_y_tied_with"] = ["acme"]
    _, out, _ = _run({"views": [v]}, tmp_path)
    desc = next(t["description"] for t in out["triggers"] if t["id"] == "bottom_half_both_axes")
    assert "tied 8th–9th of 10" in desc, desc


# --- no_edge: the crowded middle ---------------------------------------------


def _geo(view: dict[str, Any], nearest: float, x_lead: float, y_lead: float) -> dict[str, Any]:
    view.update({"nearest_distance": nearest, "x_lead_over_best": x_lead, "y_lead_over_best": y_lead})
    return view


def test_no_edge_fires_on_a_crowded_middle_no_rank_trigger_sees(tmp_path: Path) -> None:
    """5th of 10 on both axes: not bottom half, not top -- and a rival right next to you."""
    v = _geo(_view(x_rank=5, y_rank=5, competitor_count=9), nearest=7.0, x_lead=-20.0, y_lead=-15.0)
    _, out, _ = _run({"views": [v], "overall_differentiation": 40.0}, tmp_path)
    assert _ids(out) == {"no_edge"}
    trig = next(t for t in out["triggers"] if t["id"] == "no_edge")
    assert trig["provisional"] is True
    assert "firmness vs integration burden" in trig["description"], "the view is named by its axes, not its id"


def test_no_edge_does_not_fire_with_clear_space(tmp_path: Path) -> None:
    v = _geo(_view(x_rank=5, y_rank=5, competitor_count=9), nearest=20.0, x_lead=-20.0, y_lead=-15.0)
    _, out, _ = _run({"views": [v], "overall_differentiation": 40.0}, tmp_path)
    assert "no_edge" not in _ids(out)


def test_no_edge_does_not_fire_with_a_clear_lead_on_one_axis(tmp_path: Path) -> None:
    v = _geo(_view(x_rank=5, y_rank=1, competitor_count=9), nearest=7.0, x_lead=-20.0, y_lead=12.0)
    _, out, _ = _run({"views": [v], "overall_differentiation": 40.0}, tmp_path)
    assert "no_edge" not in _ids(out)


def test_no_edge_is_not_evaluated_without_geometry(tmp_path: Path) -> None:
    _, out, _ = _run({"views": [_view()], "overall_differentiation": 40.0}, tmp_path)
    assert "no_edge" not in _ids(out)
    assert any(ne["trigger"] == "no_edge" for ne in out["not_evaluated"])


def test_no_edge_edges_match_the_report_wording() -> None:
    """The gate's "right next to you" and "clear lead" must be the report's, or the founder is told two things."""
    import importlib.util

    scripts = SCRIPT.parent
    specs = {}
    for name in ("gate3_triggers", "_cp_view"):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        specs[name] = mod
    assert specs["gate3_triggers"]._NO_EDGE_NEAREST == specs["_cp_view"].NEAR_NEXT_TO
    assert specs["gate3_triggers"]._NO_EDGE_LEAD == specs["_cp_view"].LEAD_LEVEL


def test_low_differentiation_description_carries_no_number(tmp_path: Path) -> None:
    _, out, _ = _run({"views": [_view()], "overall_differentiation": 12.0}, tmp_path)
    trig = next(t for t in out["triggers"] if t["id"] == "low_overall_differentiation")
    assert "%" not in trig["description"] and "12" not in trig["description"]


# --- a scored plan (D1) -------------------------------------------------------


def _planned(view: dict[str, Any], today_ranked: bool = False) -> dict[str, Any]:
    view["scored_point"] = "planned"
    view["today"] = {"ranked": today_ranked}
    return view


def test_a_flattering_plan_always_says_it_is_a_plan(tmp_path: Path) -> None:
    _, out, _ = _run({"views": [_planned(_view(x_rank=1, y_rank=2))]}, tmp_path)
    trig = next(t for t in out["triggers"] if t["id"] == "flattering_both_axes")
    assert "this is your plan, if delivered" in trig["description"]
    assert "rests on claims not yet shown" in trig["description"]
    assert " -- " not in trig["description"], "a founder reads a real dash, not two hyphens"


def test_a_flattering_result_that_is_not_a_plan_has_no_caveat(tmp_path: Path) -> None:
    """Positive control: the lever is scored_point."""
    _, out, _ = _run({"views": [_view(x_rank=1, y_rank=2)]}, tmp_path)
    trig = next(t for t in out["triggers"] if t["id"] == "flattering_both_axes")
    assert "if delivered" not in trig["description"]


def test_a_low_plan_still_fires_and_says_even_if_delivered(tmp_path: Path) -> None:
    view = _planned(_view(x_rank=7, y_rank=8, competitor_count=9))
    _, out, _ = _run({"views": [view], "overall_differentiation": 10.0}, tmp_path)
    ids = _ids(out)
    assert {"bottom_half_both_axes", "low_overall_differentiation"} <= ids
    for t in out["triggers"]:
        assert t["description"].startswith("even if everything in the plan is delivered, "), t


def test_an_unranked_today_is_not_evaluated_not_passed(tmp_path: Path) -> None:
    _, out, _ = _run({"views": [_planned(_view())]}, tmp_path)
    assert any(ne["trigger"] == "today_position" for ne in out["not_evaluated"])
    _, ranked, _ = _run({"views": [_planned(_view(), today_ranked=True)]}, tmp_path)
    assert not any(ne["trigger"] == "today_position" for ne in ranked["not_evaluated"])
