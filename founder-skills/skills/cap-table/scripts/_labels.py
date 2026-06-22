"""Founder-facing labels for internal cap-table enums.

Single source of truth shared by the three user-facing generators
(``visualize.py`` / ``explore.py`` / ``compose_report.py``). We lead with a
plain-language label and preserve the raw code — as an HTML hover tooltip or a
Markdown small-print parenthetical — so counsel and power users keep the exact
term. Rule ids are deliberately NOT mapped here: they are stable references
counsel cites, so they stay visible verbatim.
"""

from __future__ import annotations

COMPLETENESS = {
    "full": "Fully modeled",
    "mixed": "Partially modeled",
    "structural_only": "Structure only — no priced round yet",
    "repay_only": "Repayment only",
}

SCENARIO_TYPE = {
    "safe_conversion": "SAFE conversion",
    "note_conversion": "Convertible note",
    "priced_round": "Priced round",
    "flip": "Entity flip",
}

SCOPE = {
    "legal_tax_applicability": "Legal/tax window",
    "benchmark_freshness": "Benchmark freshness",
    "not_applicable": "—",
}

STATUS = {
    "in_window": "Active now",
    "pre_effective": "Not yet in effect",
    "expired": "Window has passed",
    "date_tracking_only": "Tracking a date",
    "missing_event_date": "Needs a date from you",
    "not_date_sensitive": "Not time-sensitive",
    "near_end_flag": "Window closing soon",
    "near_start_flag": "Window opening soon",
}

# Keyed by category name used at the call sites.
MAPS: dict[str, dict[str, str]] = {
    "completeness": COMPLETENESS,
    "scenario_type": SCENARIO_TYPE,
    "scope": SCOPE,
    "status": STATUS,
}

# One-line gloss for jargon that has no single-word substitute.
CAP_IMPLIED_GLOSS = (
    "Cap-implied: the ownership each SAFE locks in from its valuation cap, "
    "before a priced round sets the actual share price."
)


def humanize(category: str, value: str | None) -> str:
    """Plain-language label for a raw enum value; de-underscores unknowns."""
    if value is None or value == "":
        return "—"
    return MAPS.get(category, {}).get(value, value.replace("_", " "))


def html_term(category: str, value: str | None) -> str:
    """`<span>` with the friendly label; the raw code is the hover tooltip.

    Values come from closed enum sets (no user input), so no escaping is needed.
    """
    label = humanize(category, value)
    if value is None or value == "":
        return label
    return f'<span class="term" title="{value}">{label}</span>'


def md_term(category: str, value: str | None) -> str:
    """Markdown: friendly label with the raw code as a small-print parenthetical.

    Omits the parenthetical when there is no real mapping (avoids ``foo (`foo`)``).
    """
    if value is None or value == "":
        return "—"
    label = humanize(category, value)
    if label == value.replace("_", " "):  # no mapping → nothing extra to show
        return label
    return f"{label} (`{value}`)"
