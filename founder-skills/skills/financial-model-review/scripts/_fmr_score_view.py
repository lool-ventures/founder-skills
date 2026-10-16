"""The review's headline score: which figure, under which name, printed which way.

report.md (its verdict, which is also the printed hand-over, and its Executive Summary), the report page's
ring and the explorer's ring all state the review's score under one name. A deck-only review is headlined
on its business-quality score as "Deck Financial Readiness"; every other review on the checklist score as
"Model Quality". That choice is made here and nowhere else: the pages used to make it on a different test,
or not at all, and named the checklist score each their own way, so one review could show three scores
under three names.

Standard library only, no CLI, no output, and no `_ui` import: compose loads this module, and the report
builder must not start loading the page module. It decides no score: `checklist.py` wrote both figures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODEL_LABEL = "Model Quality"
DECK_LABEL = "Deck Financial Readiness"

# The formats whose structural criteria are gated off (`references/schema-inputs.md`, "model_format pipeline
# effects"): a review of one is a review of the business, headlined as such whatever its figures' confidence.
_DECK_FORMATS = frozenset({"deck", "conversational"})


def score_text(pct: Any) -> str:
    """A score as every surface prints it, without the percent sign: one decimal at most and no trailing zero
    ("63", "95.6"). The fleet's format; a test holds it equal to `_ui.score_text`."""
    return f"{round(float(pct), 1):g}"


def deck_only(summary: Mapping[str, Any] | None, company: Any) -> bool:
    """Whether the review headlines its business-quality score: a business-quality score exists, no structural
    criterion applied, and either the figures are not exact (inputs.json's `company.data_confidence`, "exact"
    when absent) or the review is of a deck or a conversation (`company.model_format`)."""
    summary = summary if isinstance(summary, Mapping) else {}
    company = company if isinstance(company, Mapping) else {}
    if summary.get("model_maturity_pct") is not None or summary.get("business_quality_pct") is None:
        return False
    return str(company.get("data_confidence", "exact")) != "exact" or company.get("model_format") in _DECK_FORMATS


def headline(summary: Mapping[str, Any] | None, company: Any) -> tuple[str, Any]:
    """(label, score) the review is headlined with, on every surface. The score is the artifact's own value,
    None when the checklist carries none."""
    summary = summary if isinstance(summary, Mapping) else {}
    if deck_only(summary, company):
        return DECK_LABEL, summary.get("business_quality_pct")
    return MODEL_LABEL, summary.get("score_pct")
