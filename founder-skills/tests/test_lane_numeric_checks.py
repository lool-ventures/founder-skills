"""The numeric-operators lane: its deck through the real engine, and its checks against hand-built artifacts.

Free: nothing here calls the model. The paid lane (`test_e2e_deck_review.py::test_deck_review_numeric_operators_lane`,
opt-in) asks whether the model PROPOSES `runway` over a burn plan, `inverse_change` and `implied_base` from
`synthetic-numeric-operators-deck.txt`. Two things it relies on are settled here instead, before anyone pays:

  - the engine half of its golden file: given the proposals an analyst would make from this deck's own
    sentences, the real `reconcile.build()` gives the contradictions and the supersession the golden expects;
  - the check code: `_check_numeric_operators` passes on artifacts where every expectation holds, and names the
    failure where each one does not.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"
DECK = TESTS / "fixtures" / "decks" / "synthetic-numeric-operators-deck.txt"


@pytest.fixture(scope="module")
def deck_lane() -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location("_numeric_test_e2e_deck_review", TESTS / "test_e2e_deck_review.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rec() -> Any:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("_numeric_lane_test_reconcile", SCRIPTS / "reconcile.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # before exec: its dataclasses resolve annotations through it
    spec.loader.exec_module(mod)
    return mod


def _fig(fid: str, value: float, raw: str, unit: str, label: str, slide: int, quote: str, period: str = "") -> dict:
    out: dict[str, Any] = {
        "id": fid,
        "value": value,
        "raw": raw,
        "unit_kind": unit,
        "label": label,
        "slide": slide,
        "quote": quote,
    }
    if unit == "money":
        out["currency"] = "USD"
    if period:
        out["period"] = period
    return out


# The ledger an extraction of this deck should produce: every quote is the deck's own sentence.
LEDGER = {
    "figures": [
        _fig("revenue", 1_100_000, "$1.1M", "money", "annual revenue", 4, "Annual revenue of $1.1M", "year"),
        _fig(
            "revenue_share",
            5,
            "5%",
            "percent",
            "share of mid-market claims-audit software spend",
            4,
            "which is 5% of mid-market claims-audit software spend",
        ),
        _fig(
            "cost_cut",
            35,
            "35%",
            "percent",
            "reduction in cost per claim audited",
            4,
            "a 35% reduction in cost per claim audited",
        ),
        _fig(
            "per_dollar",
            12,
            "12%",
            "percent",
            "increase in claims audited per dollar of audit spend",
            4,
            "a 12% increase in claims audited per dollar of audit spend",
        ),
        _fig("cash", 3_100_000, "$3.1M", "money", "cash in the bank", 5, "Cash in the bank: $3.1M as of January 2027"),
        _fig(
            "burn_2027",
            120_000,
            "$120K per month",
            "money",
            "burn plan 2027",
            5,
            "Burn plan: $120K per month from January 2027 through December 2027",
            "month",
        ),
        _fig("burn_2028", 2_400_000, "$2.4M", "money", "2028 burn budget", 5, "2028 burn budget: $2.4M", "year"),
        _fig("runway", 44, "44 months", "duration", "runway", 5, "Runway: 44 months"),
        _fig("raise", 3_650_000, "$3.65M", "money", "seed raise", 7, "Raising $3.65M seed"),
        _fig("post_money", 14_000_000, "$14M", "money", "post-money valuation", 7, "at $14M post-money"),
    ]
}
SCHEDULE = [{"id": "burn_2027", "from": "2027-01", "to": "2027-12"}, {"id": "burn_2028", "from": "2028-01"}]
RUNWAY: dict[str, Any] = {
    "kind": "contradiction",
    "operator": "runway",
    "operands": ["cash", "burn_2027", "burn_2028"],
    "expected_id": "runway",
    "schedule": SCHEDULE,
    "start": "2027-01",
}
FLAT_MONTHLY: dict[str, Any] = {
    "kind": "derived_ratio",
    "operator": "ratio",
    "operands": ["cash", "burn_2027"],
    "expected_id": "runway",
}
FLAT_YEARLY: dict[str, Any] = {
    "kind": "derived_ratio",
    "operator": "ratio",
    "operands": ["cash", "burn_2028"],
    "expected_id": "runway",
}
INVERSE: dict[str, Any] = {
    "kind": "contradiction",
    "operator": "inverse_change",
    "operands": ["cost_cut"],
    "direction": "reduction",
    "expected_id": "per_dollar",
}
IMPLIED: dict[str, Any] = {
    "kind": "derived_ratio",
    "operator": "implied_base",
    "operands": ["revenue", "revenue_share"],
}
PROPOSALS: list[dict[str, Any]] = [RUNWAY, FLAT_MONTHLY, FLAT_YEARLY, INVERSE, IMPLIED]


def _build(rec: Any, proposals: list[dict]) -> dict:
    out, err = rec.build(LEDGER, DECK.read_text(encoding="utf-8"), proposals, None, [4, 5, 7])
    assert err is None, err
    assert out is not None
    return dict(out)


def test_every_ledger_quote_is_the_deck_s_own_text() -> None:
    deck = DECK.read_text(encoding="utf-8")
    assert [f["id"] for f in LEDGER["figures"] if f["quote"] not in deck] == []


# --- the engine half of the golden file ------------------------------------------------------------------


def test_the_deck_s_proposals_give_the_runway_and_reciprocal_contradictions(rec: Any) -> None:
    out = _build(rec, PROPOSALS)
    assert out["status"] == "checked"
    by_op = {r["operator"]: r for r in out["relations"]}
    assert by_op["runway"]["verdict"] == "contradiction"
    assert by_op["runway"]["computed"] == pytest.approx(20.3, abs=0.05)
    assert by_op["runway"]["expected_value"] == 44
    assert by_op["inverse_change"]["verdict"] == "contradiction"
    assert by_op["inverse_change"]["computed"] == pytest.approx(53.85, abs=0.01)
    assert by_op["implied_base"]["verdict"] == "derived"
    assert by_op["implied_base"]["confidence"] == "high"
    # Both flat divisions are the plan's own segments over the same stated runway, so both are retired.
    assert "ratio" not in by_op
    assert out["suppressed"].get("superseded") == 2
    # Most wrong first: 53.8% against 12% before 20.3 months against 44.
    assert [r["operator"] for r in out["relations"] if r["verdict"] == "contradiction"] == ["inverse_change", "runway"]


def test_the_raise_counted_as_cash_still_runs_short_of_the_stated_runway(rec: Any) -> None:
    with_raise = {**RUNWAY, "operands": ["cash", "raise", "burn_2027", "burn_2028"]}
    out = _build(rec, [with_raise])
    (runway,) = out["relations"]
    assert runway["verdict"] == "contradiction"
    assert runway["computed"] == pytest.approx(38.55, abs=0.05)
    assert runway["computed"] < runway["expected_value"]


def test_a_flat_division_alone_stands_as_its_own_contradiction(rec: Any) -> None:
    """The control for the supersession: without the runway over the plan, the flat line is what shows."""
    out = _build(rec, [FLAT_MONTHLY])
    assert [(r["operator"], r["verdict"]) for r in out["relations"]] == [("ratio", "contradiction")]


# --- the lane's check code, against artifacts written by hand ------------------------------------------------


def _write_run(tmp_path: Path, rec: Any, proposals: list[dict], *, recon: dict | None = None) -> Path:
    review_dir = tmp_path / "review"
    handoff = review_dir / "handoff" / "dr-numeric-run"
    handoff.mkdir(parents=True)
    (handoff / "relations_output.json").write_text(json.dumps({"relations": proposals}), encoding="utf-8")
    (review_dir / "ledger.json").write_text(json.dumps(LEDGER), encoding="utf-8")
    (review_dir / "second_read.json").write_text(
        json.dumps({"transcript": DECK.read_text(encoding="utf-8"), "slides_transcribed": [4, 5, 7]}), encoding="utf-8"
    )
    if recon is None:
        recon = _build(rec, proposals)
    recon = {**recon, "metadata": {"run_id": "dr-numeric-run"}}
    (review_dir / "reconciliation.json").write_text(json.dumps(recon), encoding="utf-8")
    item = {"id": "numbers_consistent", "status": "fail", "scored_by": "arithmetic"}
    (review_dir / "checklist.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    md = "## What Your Numbers Say About Each Other\n\n" + "".join(
        f"- {r['rendered']}\n" for r in recon.get("relations") or []
    )
    (review_dir / "report.md").write_text(md, encoding="utf-8")
    return review_dir


def _check(deck_lane: Any, review_dir: Path, findings: int = 2) -> tuple[list[str], dict]:
    assertions = json.loads(deck_lane.NUMERIC_GOLDEN.read_text(encoding="utf-8"))["assertions"]
    failures: list[str] = []
    observed: dict = {}
    report = {"coaching_payload": {"numeric_findings": [{"label": "x", "line": "y"}] * findings}}
    deck_lane._check_numeric_operators(
        review_dir=review_dir, report=report, assertions=assertions, observed=observed, failures=failures
    )
    return failures, observed


def test_the_golden_asks_for_the_three_operators(deck_lane: Any) -> None:
    assertions = json.loads(deck_lane.NUMERIC_GOLDEN.read_text(encoding="utf-8"))["assertions"]
    assert assertions["proposed_operators_required"] == ["runway", "inverse_change", "implied_base"]
    assert assertions["surfaced_contradiction_operators_required"] == ["runway", "inverse_change"]
    assert assertions["numbers_consistent_status"] == "fail"
    assert deck_lane.NUMERIC_DECK == DECK


def test_a_run_that_meets_every_expectation_passes_and_replays_the_engine(
    deck_lane: Any, rec: Any, tmp_path: Path
) -> None:
    failures, observed = _check(deck_lane, _write_run(tmp_path, rec, PROPOSALS))
    assert failures == []
    assert observed["numeric.proposed_operators"] == ["implied_base", "inverse_change", "ratio", "runway"]
    assert observed["numeric.superseded"] == 2
    replay = observed["numeric.engine_replay"]
    assert isinstance(replay, list)
    assert sorted((r["operator"], r["verdict"]) for r in replay) == [
        ("implied_base", "derived"),
        ("inverse_change", "contradiction"),
        ("ratio", "superseded"),
        ("ratio", "superseded"),
        ("runway", "contradiction"),
    ]


@pytest.mark.parametrize("missing", ["runway", "inverse_change", "implied_base"])
def test_an_operator_the_model_never_proposed_is_named(deck_lane: Any, rec: Any, tmp_path: Path, missing: str) -> None:
    proposals = [p for p in PROPOSALS if p["operator"] != missing]
    failures, _ = _check(deck_lane, _write_run(tmp_path, rec, proposals))
    assert any(f"the model never proposed `{missing}`" in f for f in failures), failures


def test_a_runway_with_no_schedule_is_named(deck_lane: Any, rec: Any, tmp_path: Path) -> None:
    flat_runway = {k: v for k, v in RUNWAY.items() if k not in ("schedule", "start")}
    flat_runway["operands"] = ["cash", "burn_2027"]
    failures, _ = _check(deck_lane, _write_run(tmp_path, rec, [flat_runway, INVERSE, IMPLIED]))
    assert any("without a `schedule`" in f for f in failures), failures


def test_a_proposed_runway_that_did_not_surface_points_at_the_engine_s_reason(
    deck_lane: Any, rec: Any, tmp_path: Path
) -> None:
    broken = {**RUNWAY, "start": "2026-06"}  # before the plan begins: the engine refuses it
    failures, observed = _check(deck_lane, _write_run(tmp_path, rec, [broken, INVERSE, IMPLIED]))
    assert any("no `runway` contradiction reached the founder: it was proposed but" in f for f in failures), failures
    replay = {r["operator"]: r for r in observed["numeric.engine_replay"]}
    assert replay["runway"]["verdict"] == "dropped"
    assert any("start month" in reason for reason in replay["runway"]["reasons"])


def test_a_flat_division_beside_the_runway_is_named(deck_lane: Any, rec: Any, tmp_path: Path) -> None:
    recon = _build(rec, PROPOSALS)
    flat = {
        "kind": "derived_ratio",
        "operator": "ratio",
        "operands": ["cash", "burn_2027"],
        "expected_id": "runway",
        "verdict": "contradiction",
        "computed": 25.8,
        "expected_value": 44.0,
        "rendered": "$3.1M ÷ $120K per month = 25.8 months  — but the deck states 44 months (runway)",
    }
    recon["relations"] = [*recon["relations"], flat]
    failures, _ = _check(deck_lane, _write_run(tmp_path, rec, PROPOSALS, recon=recon))
    assert any("supersede() should have retired it" in f for f in failures), failures


def test_a_runway_longer_than_stated_is_named(deck_lane: Any, rec: Any, tmp_path: Path) -> None:
    recon = _build(rec, PROPOSALS)
    for r in recon["relations"]:
        if r["operator"] == "runway":
            r["computed"] = 61.0
    failures, _ = _check(deck_lane, _write_run(tmp_path, rec, PROPOSALS, recon=recon))
    assert any("gives LESS runway than it states" in f for f in failures), failures


def test_a_withdrawn_runway_and_a_thin_payload_are_named(deck_lane: Any, rec: Any, tmp_path: Path) -> None:
    recon = _build(rec, PROPOSALS)
    recon["interpretation"] = {
        "status": "applied",
        "contradictions_before": 2,
        "downgraded": [
            {
                "operator": "runway",
                "operands": RUNWAY["operands"],
                "expected_id": "runway",
                "class": "approximate_stated_figure",
                "reason": "x",
                "rendered": "y",
            }
        ],
    }
    failures, _ = _check(deck_lane, _write_run(tmp_path, rec, PROPOSALS, recon=recon), findings=1)
    assert any("withdrew a `runway` contradiction" in f for f in failures), failures
    assert any("numeric_findings has 1" in f for f in failures), failures


def test_an_unreadable_hand_off_is_a_failure_not_a_pass(deck_lane: Any, rec: Any, tmp_path: Path) -> None:
    review_dir = _write_run(tmp_path, rec, PROPOSALS)
    (review_dir / "handoff" / "dr-numeric-run" / "relations_output.json").unlink()
    failures, _ = _check(deck_lane, review_dir)
    assert any("the proposer's hand-off cannot be read" in f for f in failures), failures
