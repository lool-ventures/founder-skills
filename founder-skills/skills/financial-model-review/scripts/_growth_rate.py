"""The monthly growth rate, computed one way from the model's monthly revenue series.

WHY. `revenue.growth_rate_monthly` feeds the burn multiple, the runway projection and the explorer.
The extraction sub-agent has no shell, so it worked the compound rate out by hand, and the method
varied from run to run: over the same synthetic six-month series, kept runs stored 0.147 (a
five-interval rate), 0.1427 (a trailing three-month rate) and 0.091 (two intervals with a cube
root taken), and the burn multiple moved from 0.40 to 0.65 with it. This module computes the rate
the same way every time, at Step 3.5 (`validate_extraction.py --fix`), so the figure the founder
confirms on the review page is the one every later step reads.

WHY A SCORING FILE. The window and the minimum below decide a figure the burn multiple is graded
on, so this file is listed in the release's scoring-file registry: a change to a threshold has to
be declared. Keep the thresholds here, never as literals at the call site.

THE RULE.
- Not for a project builder (its growth rate is null by the extraction rules), and never over a
  stored value that is null, zero or negative: those are decisions, not hand arithmetic. Only an
  absent key or a positive number is replaced.
- The series is `revenue.monthly[]`, up to and including the MRR date (`revenue.mrr.as_of`, else
  `cash.balance_date`). The last month with revenue must BE that date; a series that stops earlier
  is stale and nothing is computed. `actual` is not read: runs have flagged every historical month
  `actual: false`.
- The window is the months with revenue within `K_MAX` calendar months of that date; it needs at
  least `N_MIN` of them. The rate is the compound monthly growth from the window's first month to
  its last, over the calendar span between them (a dropped month does not shorten the exponent).
- Each end is the month's `arr` / 12 when both ends carry an `arr`, else the month's `total`: one
  basis for both ends, never one of each.
- `revenue.quarterly` is not read.

THE MARKER. `metadata.growth_rate_derivation` records what was computed (no timestamp, so a re-run
on unchanged inputs leaves the file byte-identical). On a re-run the rate is computed again only
while the stored value is still the marker's: a different stored value is the founder's
correction, and it is kept.
"""

from __future__ import annotations

import math
import re
from typing import Any

#: The longest window, in calendar months between its first and last month.
K_MAX = 6
#: The fewest months with revenue the window must hold (so at least three intervals).
N_MIN = 4
#: Decimal places the rate is stored to.
DECIMALS = 4

MARKER_KEY = "growth_rate_derivation"

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")
_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_index(value: Any) -> int | None:
    """`"YYYY-MM"` as a month count, or None when it is not one."""
    if not isinstance(value, str):
        return None
    match = _MONTH_RE.match(value.strip())
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return year * 12 + (month - 1)


def _month_text(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_label(month: Any) -> str:
    """`"2026-01"` as "Jan 2026" for a founder; the input unchanged when it is not a month."""
    index = _month_index(month)
    if index is None:
        return str(month)
    return f"{_MONTH_NAMES[index % 12]} {index // 12}"


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _same(a: Any, b: Any) -> bool:
    """Whether a stored rate is the marker's value (never true for a bool or a non-number)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)


def derive(inputs: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """The computed rate and how it was computed, or (None, why it was not)."""
    revenue = _as_dict(inputs.get("revenue"))
    as_of = _month_index(_as_dict(revenue.get("mrr")).get("as_of"))
    if as_of is None:
        as_of = _month_index(_as_dict(inputs.get("cash")).get("balance_date"))
    if as_of is None:
        return None, "no MRR date or balance date to end the window at"
    series = revenue.get("monthly")
    if not isinstance(series, list) or not series:
        return None, "no monthly revenue series"

    by_month: dict[int, dict[str, Any]] = {}
    for entry in series:
        if not isinstance(entry, dict):
            return None, "the monthly series has an entry that is not a month"
        index = _month_index(entry.get("month"))
        if index is None:
            return None, "the monthly series has an entry with no readable month"
        if index > as_of:
            continue
        if index in by_month:
            return None, "the monthly series lists a month twice"
        if _positive(entry.get("total")) is not None or _positive(entry.get("arr")) is not None:
            by_month[index] = entry

    if as_of not in by_month:
        return None, "the monthly series has no revenue in the month of the MRR date"
    window = sorted(index for index in by_month if as_of - index <= K_MAX)
    if len(window) < N_MIN:
        return None, f"fewer than {N_MIN} months with revenue up to the MRR date"

    first, last = by_month[window[0]], by_month[window[-1]]
    start_arr, end_arr = _positive(first.get("arr")), _positive(last.get("arr"))
    if start_arr is not None and end_arr is not None:
        basis, start, end = "arr", start_arr / 12, end_arr / 12
    else:
        start_total, end_total = _positive(first.get("total")), _positive(last.get("total"))
        if start_total is None or end_total is None:
            return None, "the window's first or last month has no revenue on one basis"
        basis, start, end = "total", start_total, end_total

    intervals = window[-1] - window[0]
    value = round((end / start) ** (1.0 / intervals) - 1.0, DECIMALS)
    return (
        {
            "method": "compound_monthly_growth",
            "basis": basis,
            "from_month": _month_text(window[0]),
            "to_month": _month_text(window[-1]),
            "intervals": intervals,
            "value": value,
        },
        "",
    )


def apply(inputs: dict[str, Any]) -> dict[str, Any]:
    """Set `revenue.growth_rate_monthly` from the series where the rule allows, in place.

    Returns `{"action", "reason", "derivation"}`; `action` is `set` (the inputs changed),
    `unchanged` (already the computed value, marker current), `founder_value_kept` (the stored value
    differs from the marker's, so the founder corrected it) or `skipped`.
    """
    revenue = inputs.get("revenue")
    if not isinstance(revenue, dict):
        return {"action": "skipped", "reason": "no revenue section", "derivation": None}
    company = _as_dict(inputs.get("company"))
    if str(company.get("revenue_model_type") or "").strip().lower() == "project-builder":
        return {"action": "skipped", "reason": "a project builder carries no growth rate", "derivation": None}

    metadata = _as_dict(inputs.get("metadata"))
    marker = metadata.get(MARKER_KEY)
    marker = marker if isinstance(marker, dict) else None
    has_key = "growth_rate_monthly" in revenue
    current = revenue.get("growth_rate_monthly")

    if marker is not None:
        if not has_key or not _same(current, marker.get("value")):
            return {"action": "founder_value_kept", "reason": "the stored rate was corrected", "derivation": marker}
    elif has_key and _positive(current) is None:
        return {"action": "skipped", "reason": "the stored rate is null, zero or negative", "derivation": None}

    computed, why = derive(inputs)
    if computed is None:
        return {"action": "skipped", "reason": why, "derivation": None}
    if computed["value"] == 0.0:
        # A flat series. A stored 0.0 with revenue is a critical extraction warning at Step 3.5, so the
        # computed zero is not written over whatever the extraction stated.
        return {"action": "skipped", "reason": "the monthly series is flat", "derivation": None}

    replaced = marker.get("replaced") if marker is not None else (current if has_key else None)
    new_marker = dict(computed, replaced=replaced)
    if marker == new_marker and _same(current, computed["value"]):
        return {"action": "unchanged", "reason": "", "derivation": new_marker}

    revenue["growth_rate_monthly"] = computed["value"]
    if not isinstance(inputs.get("metadata"), dict):
        inputs["metadata"] = {}
    inputs["metadata"][MARKER_KEY] = new_marker
    return {"action": "set", "reason": "", "derivation": new_marker}


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def disclosure(inputs: dict[str, Any] | None) -> str | None:
    """The founder-facing sentence for a computed rate still in use, or None.

    None when no rate was computed, or the founder's correction replaced it.
    """
    if not isinstance(inputs, dict):
        return None
    marker = _as_dict(inputs.get("metadata")).get(MARKER_KEY)
    if not isinstance(marker, dict):
        return None
    current = _as_dict(inputs.get("revenue")).get("growth_rate_monthly")
    value = marker.get("value")
    if not _same(current, value):
        return None
    sentence = (
        f"Monthly growth of {_pct(value)} was computed from your monthly revenue, "
        f"{month_label(marker.get('from_month'))} to {month_label(marker.get('to_month'))}"
    )
    replaced = marker.get("replaced")
    if isinstance(replaced, (int, float)) and not isinstance(replaced, bool) and _pct(replaced) != _pct(value):
        sentence += f", in place of an earlier estimate of {_pct(replaced)}"
    return sentence + "."


def founder_kept_message(marker: dict[str, Any]) -> str:
    """The review-page line when the founder's corrected rate is kept over the computed one."""
    value = marker.get("value")
    computed = _pct(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else "the computed rate"
    return (
        f"Monthly growth: your corrected figure is kept. Your monthly revenue gives {computed} "
        f"({month_label(marker.get('from_month'))} to {month_label(marker.get('to_month'))})."
    )
