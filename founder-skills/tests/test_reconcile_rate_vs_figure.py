#!/usr/bin/env python3
"""A rate tested against a bare figure: reconcile.py compares the two only when the figure IS that rate.

A cross-unit ratio (money per customer, customers per year) used to be compared two-sided with any figure of
its numerator's kind that states no period, so revenue per customer "contradicted" a deal size, an order value
or a target. `_stated_is_the_rate` admits only a figure written per the denominator's own words, a time rate in
the denominator's time unit, a closed table of named rates, a deal size over a count of deals, pilot revenue
over paid pilots, and a period-less ACV that revenue per paying buyer falls below. Everything else is refused.
Over a count, known mismatches are refused before any admission: a stated CAC over anything but an acquisition-spend
label and a count of new customers (two closed lists), gross transaction value or bookings against revenue, recurring
revenue over units against a selling price, part of spending against burn per head, money of another kind than the
stated figure names, CAC over the whole customer base, and an ARPU-like figure that writes no period over a numerator
whose period is known. Each has an exact-reason row.

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
}

# A period-less ACV that revenue per PAYING buyer falls below. "Revenue" is outside the stated-annual floor's
# numerators, so each row reaches `_stated_is_the_rate`.
REVENUE_BELOW = money("Revenue", "$180K", 180_000.0)
ADMITTED.update(
    {
        f"period-less ACV below, {label}": (REVENUE_BELOW, count(label, "4", 4.0), money("ACV", "$60K", 6e4))
        for label in (
            "Paying customers",
            "# paying customers",
            "Total paying customers",
            "Paying accounts",
            "Paid logos",
        )
    }
)
ADMITTED["period-less ACV below, ARR over # paying customers"] = (
    money("ARR", "$180K", 180_000.0, period="year"),
    count("# paying customers", "4", 4.0),
    money("ACV", "$60K", 6e4),
)

# The numerator and the stated figure name the same kind of money.
ADMITTED.update(
    {
        "cost per employee over opex": (
            money("Opex", "$3M", 3e6, period="year"),
            count("Employees"),
            money("Cost per employee", "$120K", 1.2e5),
        ),
        "CAC over new paying customers": (
            CAC_SPEND_A,
            count("New paying customers", "100", 100.0),
            money("CAC", "$2K", 2e3),
        ),
        "monthly ARPU over monthly revenue": (
            money("MRR", "$20K", 2e4, period="month"),
            count("Users", "1,000", 1000.0),
            money("ARPU", "$3.7/mo", 3.7),
        ),
        "GMV over orders": (money("GMV"), count("Orders", "1,000", 1000.0), money("AOV", "$1K", 1e3)),
        "unknown-kind numerator": (money("Platform fees"), count("Users", "1,000", 1000.0), money("ARPU", "$1K", 1e3)),
        "two-kind numerator": (
            money("Marketing spend revenue"),
            count("Users", "1,000", 1000.0),
            money("ARPU", "$1K", 1e3),
        ),
        "spend per customer over GMV": (money("GMV"), count("Customers"), money("Spend per customer", "$120K", 1.2e5)),
    }
)

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


def rate(num: str, den: str, stated: str, raw: str = "$2K") -> tuple[Side, Side, Side]:
    """$500K over 100 against a stated $2K: off-value, so a comparison reports a contradiction."""
    return money(num, "$500K", 5e5), count(den, "100", 100.0), money(stated, raw, 2e3)


def add_rows(table: dict[str, Any], rows: dict[str, Any]) -> None:
    assert not set(rows) & set(table), set(rows) & set(table)
    table.update(rows)


# CAC is compared only over an acquisition-spend label and a count of new customers, both closed lists. These are
# the labels they read; "Marketing & sales", "Marketing/sales", "Marketing + sales" and "Marketing (cash)" were
# refused before as revenue or cash.
CAC_SPEND_LABELS = (
    "Sales & marketing expenses",
    "Marketing + sales",
    "Marketing/sales",
    "Marketing & sales",
    "Paid marketing",
    "Marketing",
    "Demand generation spend",
    "Customer acquisition spend",
    "Total CAC spend",
    "Advertising costs",
    "Digital marketing",
    "Online marketing",
    "Growth marketing",
    "User acquisition",
    "UA spend",
    "Acquisition spend",
    "Ads spend",
    "Yearly S&M",
    "S&M ($000)",
    "Sales & marketing (S&M)",
    "Marketing (cash)",
    "S&M (cash basis)",
)
NEW_CUSTOMER_LABELS = (
    "New paying logos",
    "Customers acquired",
    "Customer additions",
    "Newly added users",
    "Number of new customers",
    "# of new customers",
    "Total new customers",
    "New customers acquired",
    "New enterprise customers",
    "New customer accounts",
    "Paid users acquired",
)
add_rows(ADMITTED, {f"CAC spend {label}": rate(label, "New customers", "CAC") for label in CAC_SPEND_LABELS})
add_rows(ADMITTED, {f"CAC count {label}": rate("S&M spend", label, "CAC") for label in NEW_CUSTOMER_LABELS})
add_rows(
    ADMITTED,
    {
        "CAC marketing spend over customers acquired": rate("Marketing spend", "Customers acquired", "CAC"),
        # Not CAC over buyers, so neither grammar reads it: written per the count's own words.
        "CAC per lead over leads": rate("S&M spend", "Leads", "CAC per lead"),
        "CAC written per new trial": rate("S&M spend", "New trials", "CAC", "$2K per new trial"),
        # Gross value against an order value or a unit price, and revenue that is not gross value.
        **{
            f"{label} over {den} vs {stated}": rate(label, den, stated)
            for label in (
                "Gross merchandise volume",
                "GTV",
                "TPV",
                "Total processing volume",
                "Payments volume",
                "Total payments processed",
            )
            for den, stated in (("Orders", "AOV"), ("Units", "ASP"))
        },
        "non-GMV revenue vs ARPC": rate("Non-GMV revenue", "Customers", "ARPC"),
        "revenue on GMV vs ARPC": rate("Revenue on GMV", "Customers", "ARPC"),
        "booking fees vs ARPC": rate("Booking fees", "Customers", "ARPC"),
        "non-recurring revenue vs ASP": rate("Non-recurring revenue", "Units", "ASP"),
        "MRR over monthly orders vs AOV": rate("MRR", "Monthly orders", "AOV"),
        # Burn per head against a whole cost line, not a part of spending.
        "opex incl. payroll vs burn per employee": rate("Opex (incl. payroll)", "Employees", "Burn per employee"),
        "burn ex-payroll vs burn per employee": rate("Burn ex-payroll", "Employees", "Burn per employee"),
        "opex vs burn per employee": rate("Opex", "Employees", "Burn per employee"),
        "opex vs gross burn per employee": rate("Opex", "Employees", "Gross burn per employee"),
        "payroll vs cost per employee": rate("Payroll", "Employees", "Cost per employee"),
    },
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
        "target word before the rate": (ARR, count("Customers"), money("Target ARR per customer", "$120K", 1.2e5)),
        "target word after a comma": (ARR, count("Customers"), money("ARR per customer, target", "$120K", 1.2e5)),
        "a year in the stated label": (ARR, count("Customers"), money("ARR per customer in 2027", "$120K", 1.2e5)),
        "monthly revenue under a period-less ACV": (
            money("MRR", "$20K", 2e4, period="month"),
            count("Customers", "4", 4.0),
            money("ACV", "$65K", 6.5e4),
        ),
        "forecast revenue under a period-less ACV": (
            money("ARR 2027E", "$180K", 1.8e5, period="year"),
            count("Customers", "4", 4.0),
            money("ACV", "$65K", 6.5e4),
        ),
        "plan bookings over deals": (
            money("Bookings plan", "$500K", 5e5),
            count("Deals", "10", 10.0),
            money("Average deal size", "$65K", 6.5e4),
        ),
        "forecast in a time rate": (
            money("Contract value", "$4M", 4e6),
            YEARS,
            money("Value per year (2027E)", "$650K", 6.5e5),
        ),
        "recurring revenue over deals": (
            ARR,
            count("Deals closed", "40", 40.0),
            money("Average deal size", "$57K", 5.7e4),
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
# A bare buyer count may hold free, trial or churned accounts: never compared below a period-less ACV.
BARE_BUYERS = ("Customers", "Customer accounts", "Logos", "Accounts", "Active customers", "Customer logos")
REFUSED.update(
    {f"period-less ACV below, {label}": (ACV_BELOW[0], count(label, "4", 4.0), ACV_BELOW[1]) for label in BARE_BUYERS}
)
# Another kind of money than the stated figure names.
KIND_REFUSED = {
    "ARR over users vs CAC": (ARR, count("Users", "1,000", 1e3), money("CAC", "$3.7K", 3.7e3)),
    "funding over customers vs CAC": (money("Total funding"), count("Customers"), money("CAC", "$3.7K", 3.7e3)),
    "burn over customers vs ARPC": (money("Burn"), count("Customers"), money("ARPC", "$3.7K", 3.7e3)),
    "payroll over employees vs revenue per employee": (
        money("Payroll", "$3M", 3e6, period="year"),
        count("Employees"),
        money("Revenue per employee", "$3.7K", 3.7e3),
    ),
    "burn over employees vs revenue per employee": (
        money("Burn"),
        count("Employees"),
        money("Revenue per employee", "$3.7K", 3.7e3),
    ),
    "ARR over employees vs cost per employee": (ARR, count("Employees"), money("Cost per employee", "$3.7K", 3.7e3)),
    "cash over customers vs ARPC": (money("Cash"), count("Customers"), money("ARPC", "$3.7K", 3.7e3)),
    "funding over accounts vs ARPA": (money("Total funding"), count("Accounts"), money("ARPA", "$3.7K", 3.7e3)),
    "gross profit over units vs ASP": (money("Gross profit"), count("Units"), money("ASP", "$3.7K", 3.7e3)),
    "opex over orders vs AOV": (money("Opex"), count("Orders"), money("AOV", "$3.7K", 3.7e3)),
    "burn over closed deals vs deal size": (
        money("Burn"),
        count("Closed deals"),
        money("Average deal size", "$3.7K", 3.7e3),
    ),
    "sales and marketing over employees vs revenue per employee": (
        money("Sales and marketing"),
        count("Employees"),
        money("Revenue per employee", "$3.7K", 3.7e3),
    ),
    "revenue over customers vs burn per customer": (
        money("Revenue"),
        count("Customers"),
        money("Burn per customer", "$3.7K", 3.7e3),
    ),
}
REFUSED.update(KIND_REFUSED)
# CAC is spending per new customer: never over a count marked as the whole base.
REFUSED.update(
    {
        f"CAC over {label}": (CAC_SPEND, count(label, "100", 100.0), CAC)
        for label in ("Total customers", "Paying customers", "Active users", "Customer base")
    }
)
# ARPU and its kin with no written period, over a numerator whose period is known.
REFUSED.update(
    {
        "ARPU over ARR": (ARR, count("Users", "1,000", 1e3), money("ARPU", "$1K", 1e3)),
        "ARPU over MRR": (money("MRR", "$20K", 2e4), count("Users", "1,000", 1e3), money("ARPU", "$1K", 1e3)),
        "ARPA over yearly revenue": (
            money("Revenue", "$3M", 3e6, period="year"),
            count("Accounts", "1,000", 1e3),
            money("ARPA", "$1K", 1e3),
        ),
        "ARPC over ARR": (ARR, count("Customers", "1,000", 1e3), money("Blended ARPC", "$1K", 1e3)),
    }
)
# Refused before this change too, with the reason kept: an ACV that revenue per customer is at or above.
ALREADY_REFUSED = {
    "ACV above revenue per customer": (ARR, count("Customers", "4", 4.0), money("ACV", "$60K", 60_000.0)),
}


# Four more known mismatches over a count, each refused with its own reason.
def not_spend(noun: str, raw: str = "$2K") -> str:
    return (
        f"a figure per {noun} is not among the acquisition-spend labels this check reads, and {raw} is a cost per new"
        " customer"
    )


def not_new(noun: str, raw: str = "$2K") -> str:
    return f"a figure per {noun} is not a count this check reads as new customers, and {raw} is a cost per new customer"


def whole_base(noun: str) -> str:
    return f"a figure per {noun} counts the whole base, and $2K is a cost per new customer"


def net_of(noun: str) -> str:
    return (
        f"$2K is stated net of or after acquisition cost, so it is not one quantity a figure per {noun} can be tested"
        " against"
    )


MISMATCH_REFUSED: dict[str, tuple[Side, Side, Side, str]] = {
    # CAC over a numerator that is not acquisition spend ("CAC" alone is already a cost per customer).
    **{
        f"CAC over {label}": (*rate(label, "New customers", "CAC"), not_spend("New customers"))
        for label in (
            "Opex incl. marketing",
            "Payroll and marketing",
            "Sales, marketing and G&A",
            "Marketing and R&D",
            "Acquisition of Company X",
            "Commissions earned",
            "GTM spend",
            "Selling expenses",
            "CAC",
            "Total CAC",
            "Paid CAC",
            "Monthly CAC",
            "Revenue",
            "Acquisition (cash)",
        )
    },
    # CAC over a count that is not of new customers.
    **{
        f"CAC over the count {label}": (*rate("S&M spend", label, "CAC"), not_new(label))
        for label in (
            "Customers",
            "Net-new customers",
            "Net new customers",
            "Net adds",
            "Net customer adds",
            "Net new paid logos",
            "Total signed customers",
            "Customers onboarded",
            "Customers won",
            "Signed renewals",
            "Customers won back",
            "Total acquisitions",
            "Acquisitions",
            "Company acquisitions",
            "Customers converted",
            "Reactivated customers added",
            "Returning users acquired",
        )
    },
    # A label that is not CAC over buyers keeps the whole-base and kind refusals.
    "fully-loaded CAC per paying customer": (
        *rate("S&M", "Paying customers", "Fully-loaded CAC per paying customer"),
        whole_base("Paying customers"),
    ),
    "paid CAC over active customers": (
        *rate("S&M spend", "Active customers", "Paid CAC"),
        whole_base("Active customers"),
    ),
    "gross profit net of CAC": (
        *rate("Gross profit", "Customers", "Gross profit per customer, net of CAC"),
        net_of("Customers"),
    ),
    "gross profit after CAC": (
        *rate("Gross profit", "New customers", "Gross profit per new customer, after CAC"),
        net_of("New customers"),
    ),
    "revenue net of CAC": (
        *rate("Revenue", "New customers", "Revenue per new customer, net of CAC"),
        net_of("New customers"),
    ),
    # Gross transaction value is not revenue, a contract value or a deal size; bookings are not revenue earned.
    **{
        f"{label} over customers vs ARPC": (
            *rate(label, "Customers", "ARPC"),
            "a figure per Customers is gross transaction value, and $2K is revenue",
        )
        for label in (
            "GMV",
            "Gross merchandise volume",
            "GTV",
            "TPV",
            "Total processing volume",
            "Payments volume",
            "Total payments processed",
        )
    },
    "GMV vs revenue per customer": (
        *rate("GMV", "Customers", "Revenue per customer"),
        "a figure per Customers is gross transaction value, and $2K is revenue",
    ),
    "GMV vs ACV": (
        *rate("GMV", "Customers", "ACV"),
        "a figure per Customers is gross transaction value, and $2K is revenue",
    ),
    "GMV over deals vs deal size": (
        *rate("GMV", "Deals", "Average deal size"),
        "a figure per Deals is gross transaction value, and $2K is a deal or contract value",
    ),
    "bookings vs ARPC": (
        *rate("Bookings", "Customers", "ARPC"),
        "a figure per Customers is bookings, and $2K is revenue earned",
    ),
    "bookings vs revenue per customer": (
        *rate("Bookings", "Customers", "Revenue per customer"),
        "a figure per Customers is bookings, and $2K is revenue earned",
    ),
    # Recurring revenue over units is not a price per unit sold.
    **{
        f"{label} over units vs ASP": (
            *rate(label, "Units", "ASP"),
            "a figure per Units is recurring revenue, and $2K is a price per unit sold",
        )
        for label in ("ARR", "Run rate", "Subscriptions revenue", "Annualized revenue")
    },
    # Part of spending over heads is not burn per head.
    **{
        f"{label} vs {stated}": (
            *rate(label, "Employees", stated),
            "a figure per Employees is part of spending, and $2K is burn",
        )
        for label, stated in (
            ("Marketing spend", "Burn per employee"),
            ("Payroll", "Burn per employee"),
            ("Personnel costs", "Burn per employee"),
            ("S&M", "Burn per employee"),
            ("Payroll", "Net burn per employee"),
        )
    },
}
add_rows(REFUSED, {case: row[:3] for case, row in MISMATCH_REFUSED.items()})


@pytest.mark.parametrize("case", sorted(REFUSED) + sorted(ALREADY_REFUSED))
def test_a_figure_that_is_not_the_rate_is_refused(case: str) -> None:
    num, den, exp = {**REFUSED, **ALREADY_REFUSED}[case]
    r = run(num, den, exp)
    assert r.verdict == "incomparable", (case, r.verdict, r.reasons)
    # Reached the rate decision, not a refusal from elsewhere.
    assert "_per_" in (r.computed_unit or ""), case
    assert r.reasons and (
        r.reasons[-1] == KEPT_REASON
        or r.reasons[-1].startswith(("a figure per ", "a share or multiple divided by "))
        or " is stated net of or after acquisition cost, " in r.reasons[-1]
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


@pytest.mark.parametrize("case", sorted(ADMITTED))
def test_lever_forced_closed_every_admitted_row_is_refused(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The admitted rows reach `_stated_is_the_rate`: with it forced closed, none is compared."""
    monkeypatch.setattr(reconcile, "_stated_is_the_rate", lambda *a, **k: False)
    assert run(*ADMITTED[case]).verdict == "incomparable", case


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


def test_a_kind_refusal_says_which_kinds_differ() -> None:
    r = run(*KIND_REFUSED["payroll over employees vs revenue per employee"])
    assert r.reasons[-1] == "a figure per Employees is a cost, and $3.7K is revenue: they are not the same quantity"


def test_cac_over_the_whole_base_and_arpu_of_no_period_say_why() -> None:
    r = run(*REFUSED["CAC over Total customers"])
    assert r.reasons[-1] == not_new("Total customers")
    r = run(*REFUSED["paid CAC over active customers"])
    assert r.reasons[-1] == whole_base("Active customers")
    r = run(*REFUSED["ARPU over ARR"])
    assert r.reasons[-1] == "a figure per Users is for one year, and $1K does not state its period"


@pytest.mark.parametrize("stated", ["Monthly burn", "Burn per month"])
@pytest.mark.parametrize("numerator", ["Cash", "Total funding raised"])
def test_cash_over_runway_months_is_still_compared_with_a_monthly_burn(numerator: str, stated: str) -> None:
    """The kind check reads money over a count only: cash over a runway in months is a burn rate."""
    r = run(
        money(numerator, "$180K", 1.8e5),
        ("duration", "4 months", 4.0, "Runway (months)", {}),
        money(stated, "$60K", 6e4),
    )
    assert r.verdict == "contradiction", (numerator, stated, r.verdict, r.reasons)


@pytest.mark.parametrize("case", sorted(MISMATCH_REFUSED))
def test_a_known_mismatch_says_which(case: str) -> None:
    num, den, exp, reason = MISMATCH_REFUSED[case]
    assert run(num, den, exp).reasons[-1] == reason


def test_a_stated_cac_over_another_kind_of_money_names_the_spend_it_reads() -> None:
    r = run(*KIND_REFUSED["ARR over users vs CAC"])
    assert r.reasons[-1] == not_spend("Users", "$3.7K")
    r = run(*KIND_REFUSED["funding over customers vs CAC"])
    assert r.reasons[-1] == not_spend("Customers", "$3.7K")


@pytest.mark.parametrize("num", ["S&M spend", "Marketing & sales"])
def test_a_cac_ceiling_over_a_count_not_of_new_customers_is_refused(num: str, monkeypatch: pytest.MonkeyPatch) -> None:
    row = rate(num, "Customers", "Max CAC")
    r = run(*row, "at_most")
    assert r.verdict == "incomparable", (num, r.verdict, r.reasons)
    assert r.reasons[-1] == not_new("Customers")
    # Reached the rate decision: forced open, the ceiling is tested.
    monkeypatch.setattr(reconcile, "_stated_is_the_rate", lambda *a, **k: True)
    assert run(*row, "at_most").verdict == "exceeds_stated_limit"


def test_gross_adds_are_not_read_as_new_customers_by_any_admission() -> None:
    """The count grammar takes "Gross adds", but no admission reads it for CAC: refused with the plain reason."""
    r = run(*rate("S&M spend", "Gross adds", "CAC"))
    assert r.reasons[-1] == "a figure per Gross adds cannot be tested against $2K, which is not stated per Gross adds"
