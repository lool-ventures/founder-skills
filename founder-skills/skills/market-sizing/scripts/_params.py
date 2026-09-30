"""What each market-sizing figure IS: its unit, and how to print one.

ONE OWNER. `market_sizing.py`, `sensitivity.py`, `compose_report.py` and `visualize.py` all read
this module, so a unit, a period or a money format cannot mean one thing to the calculator and
another to the page the founder reads.

A unit is a dimension, not a label. A head-count recorded as the top-down industry total was once
consumed as money and printed in dollars, because nothing anywhere said what the number measured.
Every sizing input now resolves to exactly the unit its parameter requires, or it is refused
(`_provenance.py`).
"""

from __future__ import annotations

import math
from typing import Any

MONEY_TOTAL = "money_total_per_year"  # a whole market's money, per year
MONEY_PER_CUSTOMER = "money_per_customer"  # a price or revenue per customer; carries a period
COUNT = "count"  # people, accounts, seats
FRACTION = "fraction"  # 0-1
RATIO = "ratio"  # dimensionless, unbounded (seats per account, one count over another)
PERCENT_POINTS = "percent_points"  # 0-100; 35 means 35%
PERCENT_CHANGE = "percent_change"  # a signed growth rate, >= -100
YEARS = "years"
FX_RATE = "fx_rate"  # one unit of `from` in `to`; carries from / to / as_of

UNITS: frozenset[str] = frozenset(
    {MONEY_TOTAL, MONEY_PER_CUSTOMER, COUNT, FRACTION, RATIO, PERCENT_POINTS, PERCENT_CHANGE, YEARS, FX_RATE}
)
MONEY_UNITS: frozenset[str] = frozenset({MONEY_TOTAL, MONEY_PER_CUSTOMER})

# The unit each sizing input must RESOLVE to. `market_sizing.py`'s formulas assume these:
# tam = industry_total; sam = tam x segment_pct/100; tam = customer_count x arpu (per year).
PARAM_UNITS: dict[str, str] = {
    "industry_total": MONEY_TOTAL,
    "segment_pct": PERCENT_POINTS,
    "share_pct": PERCENT_POINTS,
    "customer_count": COUNT,
    "arpu": MONEY_PER_CUSTOMER,
    "serviceable_pct": PERCENT_POINTS,
    "target_pct": PERCENT_POINTS,
}
TOP_DOWN_PARAMS: tuple[str, ...] = ("industry_total", "segment_pct", "share_pct")
BOTTOM_UP_PARAMS: tuple[str, ...] = ("customer_count", "arpu", "serviceable_pct", "target_pct")

# The optional projection inputs (growth_rate, years) have no unit here on purpose: they move no
# TAM/SAM/SOM figure, stay plain numbers in the hand-off, and no page renders the projection they feed.
# A page that starts rendering it must give them references first; a test holds that line.

# What the sizing produces.
# The sizing's outputs, including the two customer counts it derives on the way to SAM and SOM. A
# derived count is fractional in the math (population x share x share); without a unit here it fell
# through to the generic number format and reached the report as a fractional "Target Customers" count.
_OUTPUT_UNITS: dict[str, str] = {
    "tam": MONEY_TOTAL,
    "sam": MONEY_TOTAL,
    "som": MONEY_TOTAL,
    "serviceable_customers": COUNT,
    "target_customers": COUNT,
}


def unit_of(name: str) -> str | None:
    """The unit a sizing input or output measures, or None for a name the sizing does not define."""
    return PARAM_UNITS.get(name) or _OUTPUT_UNITS.get(name)


# A per-customer money figure's period, to the analysis's annual basis. The one table: compose's
# founder-figure check imports it rather than keeping its own.
PERIOD_TO_YEAR: dict[str, float] = {"year": 1.0, "annual": 1.0, "quarter": 4.0, "month": 12.0, "week": 52.0}


def fmt_money(value: float | int, currency: str = "USD") -> str:
    """A compact currency string: "$1.2M" for USD, "1.2M ILS" otherwise, bare for "" (unknown)."""
    if value < 0:
        return "-" + fmt_money(-value, currency)
    prefix = "$" if currency == "USD" else ""
    suffix = "" if currency in ("USD", "") else f" {currency}"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.1f}B{suffix}"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}M{suffix}"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:,.1f}K{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def fmt_number(value: Any) -> str:
    """Commas, no needless decimals, and never "0.00" for a small non-zero rate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if value == int(value):
        return f"{int(value):,}"
    if abs(value) < 0.01:
        decimals = 1 - math.floor(math.log10(abs(value)))
        return f"{value:.{decimals}f}".rstrip("0")
    return f"{value:,.2f}"


def fmt_percent(value: float | int) -> str:
    """Percentage points as a percent: 0.27 -> "0.27%", 35 -> "35%"."""
    if abs(value) < 0.01 and value != 0:
        return fmt_number(float(value)) + "%"
    return f"{float(value):.2f}".rstrip("0").rstrip(".") + "%"


def fmt_delta(value: float | int, signed: bool = False) -> str:
    """A percent difference between two figures, always to one decimal: 179.0 -> "179.0%".

    Not fmt_percent: that trims trailing zeros, so a delta of 179.0 beside one of 64.6 would print
    as "179%". `signed` keeps the direction where the sentence needs it ("+12.0%").
    """
    return f"{float(value):{'+' if signed else ''}.1f}%"


def gap_factor(top_down: Any, bottom_up: Any) -> str | None:
    """How far apart the two builds are, as "a factor of 6.5" (larger over smaller), or None when
    either figure is missing or not positive. A percentage of the two figures' average caps at 200%
    and reads as growth: a gap under 200% was taken for a small multiple on a far wider pair."""
    nums = [v for v in (top_down, bottom_up) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(nums) != 2 or min(nums) <= 0:
        return None
    return f"a factor of {max(nums) / min(nums):.1f}"


def gap_sentence(metric: str, top_down: Any, bottom_up: Any) -> str | None:
    """ "Top-down and bottom-up SAM differ by a factor of 6.5 (bottom-up is higher).", or None."""
    factor = gap_factor(top_down, bottom_up)
    if factor is None:
        return None
    if factor == "a factor of 1.0":
        return f"Top-down and bottom-up {metric.upper()} are within 5% of each other."
    higher = "bottom-up" if bottom_up > top_down else "top-down"
    return f"Top-down and bottom-up {metric.upper()} differ by {factor} ({higher} is higher)."


def format_value(unit: str | None, value: Any, currency: str = "USD") -> str:
    """Print a value by what it measures. An unknown unit prints the bare number, never money."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value) if value is not None else "—"
    if unit in MONEY_UNITS:
        return fmt_money(float(value), currency)
    if unit in (PERCENT_POINTS, PERCENT_CHANGE):
        return fmt_percent(value)
    if unit == COUNT:
        # A derived count (population x share x share) is fractional in the math; nobody reaches
        # 13,239.6 customers. The math keeps the fraction, the page shows the whole number.
        return fmt_number(int(round(value)))
    return fmt_number(value)


def is_percent(unit: str | None) -> bool:
    return unit in (PERCENT_POINTS, PERCENT_CHANGE)
