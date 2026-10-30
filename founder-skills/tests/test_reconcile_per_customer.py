#!/usr/bin/env python3
"""Revenue per paying customer against a stated average contract value: reconcile.py's one-way floor.

Annual recurring revenue over the paying customers who produce it is at least their average annual
contract, so a quotient below the stated ACV is a contradiction and one above it only confirms the
floor. The test fires only on the label table in `_per_customer_floor`; every negative here is a
label, slide or period shape the table must refuse, because a wrong pair tells a founder their deck
is inconsistent when it is not. An average deal or contract size with no stated period is refused instead
(`_stated_is_the_rate`): never compared, unless the floor already decided or the count is of deals.
The cases are constructed and the figures synthetic.

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
        ("ARR", "Paying customers", "Annual contract value"),
        ("Run-rate revenue", "Paying logos", "ACV (blended)"),
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
        # A bare count may include free or unpaid logos.
        ("ARR", "Customers", "ACV"),
        ("ARR", "Logos", "ACV"),
        # Not the average contract today.
        ("ARR", "Paying customers", "ACV (target)"),
        ("ARR", "Paying customers", "ACV (projected)"),
        ("ARR", "Paying customers", "Enterprise ACV"),
        ("ARR", "Paying customers", "ACV 2028"),
        # Today's price for new deals, which older customers may not pay.
        ("ARR", "Paying customers", "ACV (current)"),
        ("ARR", "Paying customers", "ACV (today)"),
        ("ARR", "Paying customers", "Contract value"),
        # A paid pilot count pairs only with pilot pricing.
        ("ARR", "Paid pilots", "ACV"),
    ],
)
def test_other_labels_never_pair(num_label: str, den_label: str, exp_label: str) -> None:
    assert run(num_label, den_label, exp_label).verdict != "contradiction"


FLOOR = "revenue per paying customer is normally at least the average contract"


NO_PERIOD = "a deal or contract size with no stated period cannot be tested against revenue per customer"
_NONE = {"period": None}


@pytest.mark.parametrize("num", [("$180K", 180_000.0), ("$508K", 508_000.0)])  # below and above $60K
@pytest.mark.parametrize(
    ("num_label", "den_label", "exp_label"),
    [
        ("ARR", "Paying customers", "Average deal size"),
        ("ARR", "Paying customers", "Average contract value"),
        ("ARR", "Paying customers", "Average contract size"),
        ("ARR", "Paying customers", "Average deal value"),
        ("ARR", "Paying customers", "Median deal size"),
        ("ARR", "Paying customers", "Average deal size (USD)"),
        ("ARR", "Paying customers", "Average enterprise deal size"),
        ("ARR", "Paying customers", "Average annual deal size"),
        ("ARR", "Paid pilots", "Average contract"),
        # The refusal does not need the floor's tables: these never reach the floor.
        ("Revenue FY2025", "Paying customers", "Average deal size"),
        ("ARR", "Enterprise customers", "Average deal size"),
        ("ARR", "Enterprise accounts", "Average deal size"),
        ("ARR", "Customers under contract", "Average deal size"),
        ("ARR", "Customers (Sep 2026)", "Average deal size"),
    ],
)
def test_a_deal_size_with_no_period_is_never_compared(
    num_label: str, den_label: str, exp_label: str, num: tuple[str, float]
) -> None:
    r = run(num_label, den_label, exp_label, num=num, exp_kw=_NONE)
    assert r.verdict == "incomparable" and NO_PERIOD in r.reasons, (r.verdict, r.reasons)


@pytest.mark.parametrize(
    "kw",
    [
        {"den_kw": {"slide": 5}},  # another slide
        {"extra": [fig("n2", "$240K", 240_000.0, "money", "ARR Dec 2026", period="year")]},  # a second ARR
        {"num_kw": {"currency": "USD"}, "exp_kw": {"period": None, "currency": "EUR"}},
    ],
)
def test_the_refusal_does_not_need_the_floors_slide_or_currency_rules(kw: dict[str, Any]) -> None:
    kw = {"exp_kw": _NONE, **kw}
    r = run("ARR", "Paying customers", "Average deal size", **kw)
    assert r.verdict == "incomparable" and NO_PERIOD in r.reasons, (r.verdict, r.reasons)


@pytest.mark.parametrize(
    ("num_label", "den_label", "exp_label", "num", "den", "exp"),
    [
        # Total value over a number of deals IS the average deal size: a real identity.
        ("Total contract value", "Customer contracts", "Average contract value", 500_000.0, 10.0, 60_000.0),
        ("Bookings", "Deals with new customers", "Average deal size", 500_000.0, 10.0, 60_000.0),
        ("Bookings", "Deals", "Average deal size", 500_000.0, 10.0, 60_000.0),
        # Pilot revenue over paid pilots is one deal each.
        ("Pilot revenue", "Paid pilots", "Average deal size (pilot pricing)", 300_000.0, 6.0, 80_000.0),
    ],
)
def test_a_count_of_deals_keeps_the_two_sided_comparison(
    num_label: str, den_label: str, exp_label: str, num: float, den: float, exp: float
) -> None:
    def money(v: float) -> str:
        return f"${v / 1000:g}K"

    r = run(
        num_label,
        den_label,
        exp_label,
        num=(money(num), num),
        den=(f"{den:g}", den),
        exp=(money(exp), exp),
        num_kw={"period": None},
        exp_kw=_NONE,
    )
    assert r.verdict == "contradiction", (r.verdict, r.reasons)
    assert NO_PERIOD not in r.reasons


def test_a_count_of_deals_matching_the_stated_size_is_no_contradiction() -> None:
    r = run(
        "Total contract value",
        "Customer contracts",
        "Average contract value",
        num=("$600K", 600_000.0),
        den=("10", 10.0),
        num_kw={"period": None},
        exp_kw=_NONE,
    )
    assert r.verdict != "contradiction" and NO_PERIOD not in r.reasons


def test_a_spelled_out_acv_with_no_period_stays_on_the_floor() -> None:
    # The refusal's wide label list also matches "average annual contract value"; the floor decides first.
    for label in ("Average annual contract value", "Avg. annual contract value"):
        r = run("ARR", "Paying customers", label, exp_kw=_NONE)
        assert r.verdict == "contradiction" and FLOOR in r.rendered, (label, r.verdict, r.reasons)


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


@pytest.mark.parametrize(
    "kw",
    [
        {"den_kw": {"slide": 5}},  # another slide: the floor does not take it
        {"extra": [fig("n2", "$240K", 240_000.0, "money", "ARR Dec 2026", period="year")]},  # a second ARR
    ],
)
def test_a_period_less_acv_the_floor_skips_is_refused_only_above_it(kw: dict[str, Any]) -> None:
    above = run(
        "ARR",
        "Paying customers",
        "ACV",
        num=("$1.5M", 1_500_000.0),
        den=("40", 40.0),
        exp=("$31K", 31_000.0),
        exp_kw=_NONE,
        **kw,
    )
    assert above.verdict == "incomparable" and NO_PERIOD in above.reasons, (above.verdict, above.reasons)
    below = run(
        "ARR",
        "Paying customers",
        "ACV",
        num=("$600K", 600_000.0),
        den=("40", 40.0),
        exp=("$31K", 31_000.0),
        exp_kw=_NONE,
        **kw,
    )
    assert NO_PERIOD not in below.reasons  # below keeps the comparison it had


def test_a_period_less_acv_against_another_customer_count_is_refused_above_it() -> None:
    r = run(
        "ARR",
        "Active customers",
        "ACV",
        num=("$1.5M", 1_500_000.0),
        den=("40", 40.0),
        exp=("$31K", 31_000.0),
        exp_kw=_NONE,
    )
    assert r.verdict == "incomparable" and NO_PERIOD in r.reasons, (r.verdict, r.reasons)
