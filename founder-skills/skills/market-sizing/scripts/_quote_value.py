"""Does a recorded research figure appear in the passage quoted for it?

Step 4 may record, on a research entry, a `quote`: the passage of the source that states the figure.
`market_sizing.py` stamps the answer per entry (`quote_checks` in sizing.json), and the report says for how
many of the figures it uses a passage containing the figure was recorded.

WHAT THIS PROVES, AND WHAT IT DOES NOT. Only that the recorded text contains the recorded number. The text is
typed by the model: a search snippet copied into `quote` passes, and so does a paraphrase, since a fetch tool
returns a processed rendering of the page. A round number can also match by chance ("50%" in an unrelated
sentence). The report's wording therefore claims a recorded passage, never a checked page.

THE MATCH. A number written in the quote matches when the recorded value lies within that number's own written
precision ("$7.83 billion" covers 7.825e9 to 7.835e9), capped at 5% of it, with no floor, so "1 billion" covers
0.95e9 to 1.05e9 and not 0.5e9 to 1.5e9. That is the rule deck-review's `ledger.py` applies to `raw` against
`value`, re-implemented here because skill scripts cannot import across skills. The unit decides which written
numbers are candidates:

    money, count         a number not followed by a percent sign, with any scale word or suffix
    ratio, years         a number not followed by a percent sign
    percent_points       a number followed by "%" or "percent", compared on magnitude
    percent_change       the same: a recorded -5 matches "declined 5%", and also "grew 5%" (sign not checked)
    fraction             the value times 100, against a number followed by "%" or "percent"
    fx_rate, any other   never a match (exchange rates are not counted)

A quote longer than `QUOTE_MAX` characters is not matched; it is never refused, so a long quote cannot stop
a run.
"""

from __future__ import annotations

import math
import re
from typing import Any

QUOTE_MAX = 1000
CAP = 0.05

_SCALE = {
    "thousand": 1e3,
    "k": 1e3,
    "million": 1e6,
    "mn": 1e6,
    "mm": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
    "t": 1e12,
}
_NUMBER = re.compile(
    r"(?<![\w.])(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<dec>\d+))?"
    r"(?:\s?(?P<scale>thousand|million|billion|trillion|mn|mm|bn|tn|[kmbt])(?![a-z]))?"
    r"(?P<pct>\s?(?:%|percent\b|per cent\b))?",
    re.IGNORECASE,
)
_PLAIN_UNITS = frozenset({"money_total_per_year", "money_per_customer", "count"})
_BARE_UNITS = frozenset({"ratio", "years"})
_PERCENT_UNITS = frozenset({"percent_points", "percent_change"})


def _written(quote: str) -> list[tuple[float, float, bool, bool]]:
    """Each number in the quote as (value, half-unit of its last written digit, has a scale, is a percent)."""
    out = []
    for m in _NUMBER.finditer(quote):
        digits = m.group("int").replace(",", "")
        dec = m.group("dec") or ""
        scale_word = (m.group("scale") or "").lower()
        scale = _SCALE.get(scale_word, 1.0)
        value = float(f"{digits}.{dec}" if dec else digits) * scale
        if dec:
            half = 0.5 * 10 ** (-len(dec)) * scale
        else:
            zeros = len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0
            half = 0.5 * 10**zeros * scale
        out.append((value, half, bool(scale_word), bool(m.group("pct"))))
    return out


def _within(recorded: float, written: float, half: float) -> bool:
    tol = min(half, CAP * abs(written))
    return abs(abs(recorded) - written) <= tol + 1e-9 * max(1.0, abs(written))


def quote_matches(entry: Any) -> bool:
    """True when the entry's recorded `value` is written in its `quote`, by the rules in the module docstring."""
    if not isinstance(entry, dict):
        return False
    quote = entry.get("quote")
    value = entry.get("value")
    unit = entry.get("unit")
    if not isinstance(quote, str) or not quote.strip() or len(quote) > QUOTE_MAX:
        return False
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    numbers = _written(quote)
    if unit in _PLAIN_UNITS:
        return any(_within(value, w, h) for w, h, _s, pct in numbers if not pct)
    if unit in _BARE_UNITS:
        return any(_within(value, w, h) for w, h, s, pct in numbers if not pct and not s)
    if unit in _PERCENT_UNITS:
        return any(_within(value, w, h) for w, h, s, pct in numbers if pct and not s)
    if unit == "fraction":
        pct_value = float(f"{value * 100:.10g}")
        return any(_within(pct_value, w, h) for w, h, s, pct in numbers if pct and not s)
    return False


def quote_checks(validation: Any) -> dict[str, bool] | None:
    """`{assumption name: quote_matches}` for every named research entry, or None when a name repeats.

    A repeated name would collapse two entries into one key, so the stamp is not written at all and the
    report shows no sentence.
    """
    entries = validation.get("assumptions") if isinstance(validation, dict) else None
    if not isinstance(entries, list):
        return {}
    names = [a.get("name") for a in entries if isinstance(a, dict) and isinstance(a.get("name"), str)]
    if len(names) != len(set(names)):
        return None
    return {str(a["name"]): quote_matches(a) for a in entries if isinstance(a, dict) and isinstance(a.get("name"), str)}
