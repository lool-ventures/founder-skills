"""Founder-facing labels for internal cap-table enums.

Single source of truth shared by the three user-facing generators
(``visualize.py`` / ``explore.py`` / ``compose_report.py``). We lead with a
plain-language label and keep the friendly label or a
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

# How an instrument converted. These reached founders UNGLOSSED in every release: `humanize()`
# has no `branch` category, so it fell through to the underscore-to-space transform and delivered
# `cap and discount branch` — the enum respelled, not a label. The code-span change in the
# founder-text policy then preserved the raw form instead, which made the same defect visible.
# Neither spelling is a founder-facing sentence; this map is.
BRANCH = {
    # SAFE conversion
    "cap_branch": "Converted at the valuation cap",
    "discount_branch": "Converted at the discount",
    "cap_and_discount_branch": "Cap and discount both applied — whichever gave more shares",
    "round_price_branch": "Converted at the round price",
    "round_price_and_discount_branch": "Round price with the discount applied",
    "cap_implied": "Cap-implied ownership (pre-financing snapshot)",
    "cap_implied_set": "Cap-implied ownership across all SAFEs",
    "conversion_price_override": "Converted at a price you supplied",
    "terms_only_excluded": "Terms recorded, not converted",
    "rejected": "Not converted — see the blocker",
    # Convertible note
    "cap_conversion": "Converted at the valuation cap",
    "discount_only": "Converted at the discount",
    "maturity_convert_at_cap": "Matured — converted at the cap",
    "maturity_extend": "Matured — term extended",
    "maturity_repay": "Matured — repaid in cash",
    "maturity_counsel_review": "Matured — needs counsel to decide",
    "maturity_conversion_price_override": "Matured — converted at a price you supplied",
    "threshold_not_met": "Round too small to trigger conversion",
    "override_mismatch": "Your stated terms disagree with the document",
    # Warrant settlement
    "cash_exercise": "Exercised for cash",
    "net_share_settlement": "Net-settled in shares",
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
    "branch": BRANCH,
    "settlement_type": BRANCH,
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
