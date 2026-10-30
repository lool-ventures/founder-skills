#!/usr/bin/env python3
"""A rate tested against a bare figure: reconcile.py compares the two only when the figure IS that rate.

A cross-unit ratio (money per customer, customers per year) used to be compared two-sided with any figure of
its numerator's kind that states no period, so revenue per customer "contradicted" a deal size, an order value
or a target. `_stated_is_the_rate` admits only a figure written per the denominator's own words, a time rate in
the denominator's time unit, a closed table of named rates, a deal size over a count of deals, pilot revenue
over paid pilots, and a period-less ACV that revenue per buyer falls below. Everything else is refused.

Each refusal row is built off-value, and the lever test forces the admission open to prove the row reaches
that decision rather than a refusal from elsewhere. The cases are constructed and the figures synthetic.

Run: uv run pytest founder-skills/tests/test_reconcile_rate_vs_figure.py -q
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

HERE = pathlib.Path(__file__).parent
SCRIPTS = HERE.parent / "skills" / "deck-review" / "scripts"
sys.path[:0] = [str(SCRIPTS)]

import reconcile  # type: ignore[import-not-found]  # noqa: E402
from reconcile import Figure, compute, detect_bound, parse_range  # type: ignore[import-not-found]  # noqa: E402

KEPT_REASON = "a deal or contract size with no stated period cannot be tested against revenue per customer"


def fig(fid: str, raw: str, value: float, unit_kind: str, label: str, **kw: Any) -> Figure:
    lo_hi = parse_range(raw)
    return Figure(
        id=fid,
        value=value,
        raw=raw,
        unit_kind=unit_kind,
        label=label,
        slide=kw.pop("slide", 4),
        quote="",
        verified=True,
        bound=kw.pop("bound", detect_bound(raw, label)),
        **(dict(zip(("lo", "hi"), lo_hi, strict=True)) if lo_hi else {}),
        **kw,
    )


Side = tuple[str, str, float, str, dict[str, Any]]  # kind, raw, value, label, extra fields


def run(num: Side, den: Side, exp: Side, relation: str | None = None) -> Any:
    n = fig("n", num[1], num[2], num[0], num[3], **num[4])
    d = fig("d", den[1], den[2], den[0], den[3], **den[4])
    e = fig("e", exp[1], exp[2], exp[0], exp[3], **{"slide": 6, **exp[4]})
    spec: dict[str, Any] = {"operator": "ratio", "operands": ["n", "d"], "kind": "derived_ratio", "expected_id": "e"}
    if relation:
        spec["relation"] = relation
    return compute(spec, {"n": n, "d": d, "e": e})


def money(label: str, raw: str = "$3M", value: float = 3_000_000.0, **kw: Any) -> Side:
    return ("money", raw, value, label, kw)


def count(label: str, raw: str = "17", value: float = 17.0, **kw: Any) -> Side:
    return ("count", raw, value, label, kw)


ARR = money("ARR", period="year")
YEARS: Side = ("duration", "3 years", 3.0, "Contract term", {})


# --- admitted: the figure is that rate (each off-value, so the comparison reports a contradiction) ------------

CAC_SPEND_A = money("S&M spend", "$500K", 5e5)
BOOKINGS = money("Bookings", "$500K", 5e5)

ADMITTED = {
    "per employee": (ARR, count("Employees"), money("ARR per employee", "$120K", 120_000.0)),
    "per paying customer": (ARR, count("Paying customers"), money("Revenue per paying customer", "$120K", 120_000.0)),
    "per active user": (ARR, count("Active users"), money("ARR per active user", "$120K", 120_000.0)),
    "comma unit FTE": (ARR, count("Employees, FTE"), money("ARR per employee", "$120K", 120_000.0)),
    "plural hires": (money("Recruiting spend"), count("Hires"), money("Cost per hire", "$120K", 120_000.0)),
    "plural companies": (ARR, count("Companies"), money("Revenue per company", "$120K", 120_000.0)),
    "raw slash form": (ARR, count("Employees"), money("Revenue efficiency", "$31K/employee", 31_000.0)),
    "raw slash then year": (ARR, count("Employees"), money("Revenue efficiency", "$31K/employee/yr", 31_000.0)),
    "total number of": (ARR, count("Total number of customers"), money("ARR per customer", "$120K", 120_000.0)),
    "hash of": (ARR, count("# of customers"), money("ARR per customer", "$120K", 120_000.0)),
    "per year over years": (money("Contract value", "$4M", 4e6), YEARS, money("Value per year", "$650K", 650_000.0)),
    "quarterly over quarters": (
        money("Revenue", "$2M", 2e6),
        ("duration", "4 quarters", 4.0, "Period", {}),
        money("Quarterly revenue", "$300K", 300_000.0),
    ),
    "CAC": (money("S&M spend", "$500K", 5e5), count("New customers", "100", 100.0), money("CAC", "$2K", 2000.0)),
    "CAC customers acquired": (
        money("S&M spend", "$500K", 5e5),
        count("Customers acquired", "100", 100.0),
        money("CAC", "$2K", 2000.0),
    ),
    "CAC new logos": (money("S&M spend", "$500K", 5e5), count("New logos", "100", 100.0), money("CAC", "$2K", 2000.0)),
    "blended CAC": (
        money("S&M spend", "$500K", 5e5),
        count("New customers", "100", 100.0),
        money("Blended CAC", "$2K", 2000.0),
    ),
    "ARPU": (money("Revenue"), count("Users", "1,000", 1000.0), money("ARPU", "$1K", 1000.0)),
    "ASP": (money("Product revenue"), count("Units sold", "1,000", 1000.0), money("ASP", "$1K", 1000.0)),
    "AOV": (money("GMV"), count("Orders", "1,000", 1000.0), money("Average order value", "$1K", 1000.0)),
    "deal size over deals": (
        money("Bookings", "$500K", 5e5),
        count("Deals", "10", 10.0),
        money("Average deal size", "$60K", 60_000.0),
    ),
    "pilot revenue over paid pilots": (
        money("Pilot revenue", "$300K", 3e5),
        count("Paid pilots", "6", 6.0),
        money("Average deal size (pilot pricing)", "$80K", 80_000.0),
    ),
    "period-less ACV below, customers": (
        money("ARR", "$180K", 180_000.0, period="year"),
        count("Customers", "4", 4.0),
        money("ACV", "$60K", 60_000.0),
    ),
    "period-less ACV below, customer accounts": (
        money("ARR", "$180K", 180_000.0, period="year"),
        count("Customer accounts", "4", 4.0),
        money("ACV", "$60K", 60_000.0),
    ),
}

# ARPC over clients, and a deal size naming which deals.
ADMITTED.update(
    {
        "ARPC over clients": (money("Revenue"), count("Clients", "1,000", 1000.0), money("ARPC", "$1K", 1e3)),
        "currency scale paren": (ARR, count("Employees"), money("ARR per employee ($K)", "$120K", 120_000.0)),
        "fully loaded CAC": (
            CAC_SPEND_A,
            count("New customers", "100", 100.0),
            money("CAC (fully loaded)", "$2K", 2e3),
        ),
        "average closed deal size": (
            BOOKINGS,
            count("Deals", "10", 10.0),
            money("Average closed deal size", "$60K", 6e4),
        ),
        "average signed contract value": (
            BOOKINGS,
            count("Contracts", "10", 10.0),
            money("Average signed contract value", "$60K", 6e4),
        ),
        "deals with new customers": (
            BOOKINGS,
            count("Deals with new customers", "10", 10.0),
            money("Average deal size", "$60K", 6e4),
        ),
    }
)


@pytest.mark.parametrize("case", sorted(ADMITTED))
def test_a_figure_that_is_the_rate_is_compared(case: str) -> None:
    r = run(*ADMITTED[case])
    assert r.verdict == "contradiction", (case, r.verdict, r.reasons)


@pytest.mark.parametrize("label", ["CAC budget", "Target CAC", "Max CAC"])
def test_a_cac_ceiling_keeps_its_limit_test(label: str) -> None:
    r = run(
        money("S&M spend", "$500K", 5e5), count("New customers", "100", 100.0), money(label, "$3.7K", 3700.0), "at_most"
    )
    assert r.verdict == "exceeds_stated_limit", (label, r.verdict, r.reasons)


# --- refused: the figure is not that rate (each off-value; the lever test below forces them open) ---------------

ACV_BELOW = (money("ARR", "$180K", 180_000.0, period="year"), money("ACV", "$60K", 60_000.0))
CAC_SPEND, CAC = money("S&M spend", "$500K", 5e5), money("CAC", "$2K", 2000.0)
PER_CUSTOMER = money("ARR per customer", "$120K", 120_000.0)

REFUSED = {
    # money per count: the coverage pass's wordings
    "deal size over customers": (ARR, count("Customers"), money("Deal size", "$60K", 60_000.0)),
    "target ACV over customers": (ARR, count("Customers"), money("Target ACV", "$60K", 60_000.0)),
    "order value over customers": (ARR, count("Customers"), money("Average order value", "$60K", 60_000.0)),
    "average deal size over hospitals": (ARR, count("Hospitals"), money("Average deal size", "$60K", 60_000.0)),
    # (1) precision
    "per paying user over paying customers": (
        ARR,
        count("Paying customers"),
        money("Revenue per paying user", "$1K", 1e3),
    ),
    "per customer over paying customers": (ARR, count("Paying customers"), PER_CUSTOMER),
    "rate denominator": (ARR, count("Functions per customer"), PER_CUSTOMER),
    "target customers": (ARR, count("Target customers"), PER_CUSTOMER),
    "customers in pipeline": (ARR, count("Customers in pipeline"), PER_CUSTOMER),
    "pilot customers": (ARR, count("Pilot customers"), PER_CUSTOMER),
    "customers 2027E": (ARR, count("Customers (2027E)"), PER_CUSTOMER),
    "employees in a place": (ARR, count("Number of employees in Israel"), money("ARR per employee", "$120K", 1.2e5)),
    "comma forecast": (ARR, count("Customers, forecast"), PER_CUSTOMER),
    "comma year": (ARR, count("Customers, 2024"), PER_CUSTOMER),
    "monthly figure, annual revenue": (ARR, count("Customers"), money("Revenue per customer per month", "$1K", 1e3)),
    # (3) precision
    "CAC over target customers": (CAC_SPEND, count("Target customers", "100", 100.0), CAC),
    "CAC over customers in pipeline": (CAC_SPEND, count("Customers in pipeline", "100", 100.0), CAC),
    "CAC over customers 2027E": (CAC_SPEND, count("Customers (2027E)", "100", 100.0), CAC),
    "CAC comma target": (CAC_SPEND, count("Customers, target", "100", 100.0), CAC),
    "ARPU over target users": (money("Revenue"), count("Target users", "1,000", 1000.0), money("ARPU", "$1K", 1e3)),
    "target CAC as an equality": (CAC_SPEND, count("New customers", "100", 100.0), money("Target CAC", "$2K", 2000.0)),
    "paid CAC": (CAC_SPEND, count("New customers", "100", 100.0), money("Paid CAC", "$2K", 2000.0)),
    # (6) precision
    "ACV over employees": (ACV_BELOW[0], count("Employees", "4", 4.0), ACV_BELOW[1]),
    "ACV over target customers": (ACV_BELOW[0], count("Target customers", "4", 4.0), ACV_BELOW[1]),
    "ACV over customers in pipeline": (ACV_BELOW[0], count("Customers in pipeline", "4", 4.0), ACV_BELOW[1]),
    "ACV over customers 2027E": (ACV_BELOW[0], count("Customers (2027E)", "4", 4.0), ACV_BELOW[1]),
    "ACV over M18 target customers": (ACV_BELOW[0], count("M18 target customers", "4", 4.0), ACV_BELOW[1]),
    "ACV comma projected": (ACV_BELOW[0], count("Paying customers, projected", "4", 4.0), ACV_BELOW[1]),
    "ACV comma 2027E": (ACV_BELOW[0], count("Customers, 2027E", "4", 4.0), ACV_BELOW[1]),
    # the other reachable units
    "money per year, no time word": (
        money("Contract value", "$4M", 4e6),
        YEARS,
        money("Contract value", "$650K", 650_000.0),
    ),
    "count per year": (count("Customers", "1,200", 1200.0), YEARS, count("Customers", "500", 500.0)),
    "count per money": (
        count("Customers", "1,200", 1200.0),
        money("Spend", "$2M", 2e6),
        count("New customers", "500", 500.0),
    ),
    "percent per year": (
        ("percent", "30%", 30.0, "Cumulative churn", {}),
        YEARS,
        ("percent", "7%", 7.0, "Annual churn", {}),
    ),
    "percent per count": (
        ("percent", "30%", 30.0, "Utilisation", {}),
        count("Sites", "10", 10.0),
        ("percent", "5%", 5.0, "Utilisation per site", {}),
    ),
    "percent per money": (
        ("percent", "30%", 30.0, "Conversion", {}),
        money("Spend", "$2M", 2e6),
        ("percent", "5%", 5.0, "Conversion", {}),
    ),
    "multiple per year": (
        ("multiple", "4x", 4.0, "Return", {}),
        YEARS,
        ("multiple", "2x", 2.0, "Yearly multiple", {}),
    ),
    "multiple per count": (
        ("multiple", "4x", 4.0, "Return", {}),
        count("Funds", "10", 10.0),
        ("multiple", "2x", 2.0, "Return per fund", {}),
    ),
    "multiple per money": (
        ("multiple", "4x", 4.0, "Return", {}),
        money("Invested", "$2M", 2e6),
        ("multiple", "7x", 7.0, "Return", {}),
    ),
}

# Not that rate: a target, a forecast, today's price, a term, a cumulative or pipeline count, or a deal size that
# names a kind of contract rather than which deals. The last block are wordings refused on purpose: a later
# widening has to delete them deliberately.
REFUSED.update(
    {
        "CAC (2027E)": (CAC_SPEND, count("New customers", "100", 100.0), money("CAC (2027E)", "$2K", 2e3)),
        "CAC (projected)": (CAC_SPEND, count("New customers", "100", 100.0), money("CAC (projected)", "$2K", 2e3)),
        "ARPA (target)": (money("Revenue"), count("Accounts", "1,000", 1e3), money("ARPA (target)", "$1K", 1e3)),
        "ARPA (target, monthly)": (
            money("Revenue"),
            count("Accounts", "1,000", 1e3),
            money("ARPA (target, monthly)", "$1K", 1e3),
        ),
        "ARPU over customers": (money("Revenue"), count("Customers", "1,000", 1e3), money("ARPU", "$1K", 1e3)),
        "ARPA over customers": (money("Revenue"), count("Customers", "1,000", 1e3), money("ARPA", "$1K", 1e3)),
        "per customer (target)": (ARR, count("Customers"), money("ARR per customer (target)", "$120K", 1.2e5)),
        "per customer (2027E)": (ARR, count("Customers"), money("Revenue per customer (2027E)", "$120K", 1.2e5)),
        "per employee (goal)": (ARR, count("Employees"), money("ARR per employee (goal)", "$120K", 1.2e5)),
        "ACV (target) below": (ACV_BELOW[0], count("Customers", "4", 4.0), money("ACV (target)", "$60K", 6e4)),
        "ACV (2027E) below": (ACV_BELOW[0], count("Customers", "4", 4.0), money("ACV (2027E)", "$60K", 6e4)),
        "ACV (current) below": (ACV_BELOW[0], count("Customers", "4", 4.0), money("ACV (current)", "$60K", 6e4)),
        "ACV (today) below": (ACV_BELOW[0], count("Active customers", "4", 4.0), money("ACV (today)", "$60K", 6e4)),
        "deal size (current)": (
            BOOKINGS,
            count("Deals", "10", 10.0),
            money("Average deal size (current)", "$60K", 6e4),
        ),
        "deal size (target)": (BOOKINGS, count("Deals", "10", 10.0), money("Average deal size (target)", "$60K", 6e4)),
        "deal size (TCV)": (BOOKINGS, count("Deals", "10", 10.0), money("Average deal size (TCV)", "$60K", 6e4)),
        "average total contract value": (
            BOOKINGS,
            count("Contracts", "10", 10.0),
            money("Average total contract value", "$60K", 6e4),
        ),
        "average annual contract value over contracts": (
            BOOKINGS,
            count("Contracts", "10", 10.0),
            money("Average annual contract value", "$60K", 6e4),
        ),
        "average first-year contract value": (
            BOOKINGS,
            count("Contracts", "10", 10.0),
            money("Average first-year contract value", "$60K", 6e4),
        ),
        "average three-year contract value": (
            BOOKINGS,
            count("Contracts", "10", 10.0),
            money("Average three-year contract value", "$60K", 6e4),
        ),
        "average enterprise deal size": (
            BOOKINGS,
            count("Deals", "10", 10.0),
            money("Average enterprise deal size", "$60K", 6e4),
        ),
        "deal size over pipeline deals": (
            BOOKINGS,
            count("Pipeline deals", "10", 10.0),
            money("Average deal size", "$60K", 6e4),
        ),
        "deal size over deals in pipeline": (
            BOOKINGS,
            count("Deals in pipeline", "10", 10.0),
            money("Average deal size", "$60K", 6e4),
        ),
        "deal size over contracts signed to date": (
            BOOKINGS,
            count("Contracts signed to date", "10", 10.0),
            money("Average contract value", "$60K", 6e4),
        ),
        "bare deal size over deals": (ARR, count("Deals closed", "10", 10.0), money("Deal size", "$60K", 6e4)),
        "bare contract value over contracts": (
            ARR,
            count("Contracts", "10", 10.0),
            money("Contract value", "$60K", 6e4),
        ),
        "ACV over deals": (ARR, count("Deals", "10", 10.0), money("ACV", "$60K", 6e4)),
        "MRR over customers, stated ARR per customer": (
            money("MRR", "$250K", 2.5e5, period="month"),
            count("Customers"),
            money("ARR per customer", "$120K", 1.2e5),
        ),
        "ARR label, no period, stated MRR per customer": (
            money("ARR", "$3M", 3e6),
            count("Customers"),
            money("MRR per customer", "$9K", 9e3),
        ),
        "forecast numerator": (
            money("ARR 2027E", "$3M", 3e6, period="year"),
            count("Customers"),
            money("ARR per customer", "$120K", 1.2e5),
        ),
        "plan numerator": (
            money("ARR plan", "$3M", 3e6, period="year"),
            count("Customers"),
            money("ARR per customer", "$120K", 1.2e5),
        ),
        "lost: bare # count": (ARR, count("# Customers"), money("ARR per customer", "$120K", 120_000.0)),
        "lost: combined parenthetical": (
            BOOKINGS,
            count("Deals", "10", 10.0),
            money("Average deal size (USD, blended)", "$60K", 6e4),
        ),
        "lost: to date over to date": (
            money("S&M spend to date", "$500K", 5e5),
            count("Customers acquired to date", "100", 100.0),
            money("CAC", "$2K", 2e3),
        ),
    }
)
# Refused before this change too, with the reason kept: an ACV that revenue per customer is at or above.
ALREADY_REFUSED = {
    "ACV above revenue per customer": (ARR, count("Customers", "4", 4.0), money("ACV", "$60K", 60_000.0)),
}


@pytest.mark.parametrize("case", sorted(REFUSED) + sorted(ALREADY_REFUSED))
def test_a_figure_that_is_not_the_rate_is_refused(case: str) -> None:
    num, den, exp = {**REFUSED, **ALREADY_REFUSED}[case]
    r = run(num, den, exp)
    assert r.verdict == "incomparable", (case, r.verdict, r.reasons)
    # Reached the rate decision, not a refusal from elsewhere.
    assert "_per_" in (r.computed_unit or "") and "period" not in exp[4], case
    assert r.reasons and (
        r.reasons[-1] == KEPT_REASON or r.reasons[-1].startswith(("a figure per ", "a share or multiple divided by "))
    ), (case, r.reasons)


def test_the_refusal_names_the_denominator_in_the_decks_words() -> None:
    r = run(*REFUSED["deal size over customers"])
    assert r.reasons[-1] == "a figure per Customers cannot be tested against $60K, which is not stated per Customers"
    r = run(*REFUSED["percent per year"])
    assert r.reasons[-1] == "a share or multiple divided by year is a simple average, not a rate 7% states"


def test_a_deal_size_over_customers_keeps_its_reason() -> None:
    r = run(ARR, count("Customers"), money("Average deal size", "$60K", 60_000.0))
    assert r.reasons[-1] == KEPT_REASON


@pytest.mark.parametrize("case", sorted(REFUSED) + sorted(ALREADY_REFUSED))
def test_lever_forced_open_every_refusal_row_contradicts(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal rows reach `_stated_is_the_rate`: with it forced open, each becomes a contradiction."""
    monkeypatch.setattr(reconcile, "_stated_is_the_rate", lambda *a, **k: True)
    r = run(*{**REFUSED, **ALREADY_REFUSED}[case])
    assert r.verdict == "contradiction", (case, r.verdict, r.reasons)


def test_a_duration_per_count_is_still_refused_for_its_time_unit() -> None:
    """Unchanged: the duration arm refuses days over hires before the rate decision is reached."""
    r = run(
        ("duration", "300 days", 300.0, "Total hiring days", {}),
        count("Hires", "10", 10.0),
        (
            "duration",
            "5 days",
            5.0,
            "Time to hire",
            {},
        ),
    )
    assert r.verdict == "incomparable"
    assert any("time unit" in x for x in r.reasons), r.reasons


def test_a_rate_against_a_figure_with_a_period_is_untouched() -> None:
    """A stated figure that carries a period never reaches the rate decision."""
    r = run(ARR, count("Customers"), money("Deal size", "$60K", 60_000.0, period="year"))
    assert r.verdict == "incomparable"
    assert not any(x.startswith("a figure per ") for x in r.reasons), r.reasons
