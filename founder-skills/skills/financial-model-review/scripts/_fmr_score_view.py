"""The review's headline score: which figure, under which name, printed which way.

report.md (its verdict, which is also the printed hand-over, and its Executive Summary), the report page's
ring and the explorer's ring all state the review's score. A deck-only review (no structural criterion
applied, and figures that are not exact) is headlined on its business-quality score as "Deck Financial
Readiness"; every other review on the checklist score. That choice is made here and nowhere else: the
pages used to make it on a different test, or not at all, so one review could show three scores under
three names.

Standard library only, no CLI, no output, and no `_ui` import: compose loads this module, and the report
builder must not start loading the page module. It decides no score: `checklist.py` wrote both figures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODEL_LABEL = "Model Quality"
DECK_LABEL = "Deck Financial Readiness"


def score_text(pct: Any) -> str:
    """A score as every surface prints it, without the percent sign: one decimal at most and no trailing zero
    ("63", "95.6"). The fleet's format; a test holds it equal to `_ui.score_text`."""
    return f"{round(float(pct), 1):g}"


def data_confidence(company: Any) -> str:
    """inputs.json's `company.data_confidence` as report.md has always read it ("exact" when absent)."""
    return str(company.get("data_confidence", "exact")) if isinstance(company, Mapping) else "exact"


def deck_only(summary: Mapping[str, Any] | None, confidence: str) -> bool:
    """Whether the review headlines its business-quality score: no structural criterion applied, the figures
    are not exact, and a business-quality score exists."""
    summary = summary if isinstance(summary, Mapping) else {}
    return (
        summary.get("model_maturity_pct") is None
        and confidence != "exact"
        and summary.get("business_quality_pct") is not None
    )


def headline(summary: Mapping[str, Any] | None, confidence: str) -> tuple[str, Any]:
    """(label, score) the review is headlined with. The score is the artifact's own value, None when the
    checklist carries none."""
    summary = summary if isinstance(summary, Mapping) else {}
    if deck_only(summary, confidence):
        return DECK_LABEL, summary.get("business_quality_pct")
    return MODEL_LABEL, summary.get("score_pct")
