#!/usr/bin/env python3
"""Revenue per paying customer against a stated average contract value: reconcile.py's one-way floor.

Annual recurring revenue over the paying customers who produce it is at least their average annual
contract, so a quotient below the stated ACV is a contradiction and one above it only confirms the
floor. The test fires only on the label table in `_per_customer_floor`; every negative here is a
label, slide or period shape the table must refuse, because a wrong pair tells a founder their deck
is inconsistent when it is not. The cases are constructed and the figures synthetic.

Run: uv run pytest founder-skills/tests/test_reconcile_per_customer.py -q
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

HERE = pathlib.Path(__file__).parent
SCRIPTS = HERE.parent / "skills" / "deck-review" / "scripts"
sys.path[:0] = [str(SCRIPTS)]

from reconcile import Figure, compute, detect_bound, parse_range  # type: ignore[import-not-found]  # noqa: E402


def fig(fid: str, raw: str, value: float, unit_kind: str, label: str, slide: int = 4, **kw: Any) -> Figure:
    lo_hi = parse_range(raw)
    return Figure(
        id=fid,
        value=value,
        raw=raw,
        unit_kind=unit_kind,
        label=label,
        slide=slide,
        quote="",
        verified=True,
        bound=kw.pop("bound", detect_bound(raw, label)),
        **(dict(zip(("lo", "hi"), lo_hi, strict=True)) if lo_hi else {}),
        **kw,
    )


def run(
    num_label: str = "ARR Sep 2026",
    den_label: str = "Paid pilots",
    exp_label: str = "Average contract ACV (pilot pricing)",
    *,
    num: tuple[str, float] = ("$180K", 180_000.0),
    den: tuple[str, float] = ("4", 4.0),
    exp: tuple[str, float] = ("$60K", 60_000.0),
    num_kw: dict[str, Any] | None = None,
    den_kw: dict[str, Any] | None = None,
    exp_kw: dict[str, Any] | None = None,
    extra: list[Figure] | None = None,
    spec: dict[str, Any] | None = None,
) -> Any:
    n = fig("n", num[0], num[1], "money", num_label, **{"period": "year", **(num_kw or {})})
    d = fig("d", den[0], den[1], "count", den_label, **(den_kw or {}))
    e = fig("e", exp[0], exp[1], "money", exp_label, **{"slide": 6, "period": "year", **(exp_kw or {})})
    by = {f.id: f for f in [n, d, e, *(extra or [])]}
    rel = {"operator": "ratio", "operands": ["n", "d"], "kind": "derived_ratio", "expected_id": "e", **(spec or {})}
    return compute(rel, by)


# --- the pair fires -----------------------------------------------------------------------------------------


def test_below_the_stated_acv_is_a_contradiction_with_its_wording() -> None:
    r = run()
    assert r.verdict == "contradiction"
    assert r.rendered == (
        "$180K ÷ 4 = $45K per paid pilot  — below the average contract of $60K the deck states "
        "(Average contract ACV (pilot pricing)); revenue per paying customer is normally at least the average contract"
    )


def test_at_or_above_the_stated_acv_confirms_the_floor() -> None:
    r = run("Annual recurring revenue", "Paying customers", "ACV", num=("$254K", 254_000.0), den=("2", 2.0))
    assert r.verdict != "contradiction"
    assert r.rendered == "$254K ÷ 2 = $127K per customer  — at least the stated average contract of $60K"


@pytest.mark.parametrize(
    ("num_label", "den_label", "exp_label"),
    [
        ("Annual recurring revenue", "Pilots converted to paid", "ACV"),
        ("ARR", "Customers", "Annual contract value"),
        ("Run-rate revenue", "Paying logos", "ACV (current)"),
        ("ARR", "Paying customers", "Avg. ACV"),
        ("ARR", "Paying customers", "Average deal size"),
    ],
)
def test_the_listed_labels_pair(num_label: str, den_label: str, exp_label: str) -> None:
    assert run(num_label, den_label, exp_label).verdict == "contradiction"


def test_a_range_numerator_renders_its_span() -> None:
    r = run(num=("$160K–$180K", 170_000.0), num_kw={"lo": 160_000.0, "hi": 180_000.0})
    assert r.verdict == "contradiction"
    assert r.rendered.startswith("$160K–$180K ÷ 4 = $40K–$45K per paid pilot  — below")


# --- the pair is refused -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("num_label", "den_label", "exp_label"),
    [
        # Not the revenue the contracts produce.
        ("CAC", "Paying customers", "ACV"),
        ("Revenue FY2025", "Paying customers", "ACV"),
        ("Average salary", "Paying customers", "ACV"),
        ("List price", "Paying customers", "ACV"),
        # Not the customers who pay.
        ("ARR", "Users", "ACV"),
        ("ARR", "Target paying customers", "ACV"),
        ("ARR", "M18 target customers", "ACV"),
        ("ARR", "Functions per customer", "ACV"),
        ("ARR", "Pilot customers", "ACV"),
        ("ARR", "Customer interviews", "ACV"),
        ("ARR", "Paying customers (Oct 2026)", "ACV"),
        ("ARR", "Customers 2027", "ACV"),
        # Not the average contract today.
        ("ARR", "Paying customers", "ACV (target)"),
        ("ARR", "Paying customers", "ACV (projected)"),
        ("ARR", "Paying customers", "Enterprise ACV"),
        ("ARR", "Paying customers", "ACV 2028"),
        ("ARR", "Paying customers", "Contract value"),
        # A paid pilot count pairs only with pilot pricing.
        ("ARR", "Paid pilots", "ACV"),
    ],
)
def test_other_labels_never_pair(num_label: str, den_label: str, exp_label: str) -> None:
    assert run(num_label, den_label, exp_label).verdict != "contradiction"


FLOOR = "revenue per paying customer is normally at least the average contract"


def test_a_deal_size_with_no_period_is_not_the_floor() -> None:
    # The generic comparison still runs on it, as it did before the floor existed.
    assert FLOOR not in run("ARR", "Paying customers", "Average deal size", exp_kw={"period": None}).rendered


def test_a_plain_acv_with_no_period_is_the_floor() -> None:
    r = run("ARR", "Paying customers", "ACV", exp_kw={"period": None})
    assert r.verdict == "contradiction"
    assert FLOOR in r.rendered


def test_parts_on_different_slides_never_pair() -> None:
    assert run(den_kw={"slide": 5}).verdict != "contradiction"


def test_a_slide_with_two_recurring_revenue_figures_never_pairs() -> None:
    other = fig("n2", "$240K", 240_000.0, "money", "ARR Dec 2026", period="year")
    assert run(extra=[other]).verdict != "contradiction"


def test_currencies_that_differ_never_pair_and_one_missing_still_does() -> None:
    assert run(num_kw={"currency": "USD"}, exp_kw={"currency": "EUR"}).verdict != "contradiction"
    assert run(num_kw={"currency": "USD"}).verdict == "contradiction"


@pytest.mark.parametrize(
    ("period", "reason"),
    [(None, "the revenue figure carries no period"), ("month", "a monthly figure against an annual contract value")],
)
def test_a_revenue_figure_that_is_not_annual_is_incomparable(period: str | None, reason: str) -> None:
    r = run("MRR", "Paying customers", "ACV", num_kw={"period": period})
    assert r.verdict == "incomparable"
    assert reason in r.reasons


def test_a_ceiling_is_incomparable() -> None:
    assert run(spec={"relation": "at_most"}).verdict == "incomparable"
    assert run(exp=("up to $60K", 60_000.0)).verdict == "incomparable"
