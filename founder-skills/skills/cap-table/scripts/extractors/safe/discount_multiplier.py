"""Deterministic discount_multiplier extractor for SAFE documents.

This extractor MUST NOT decide the multiplier-vs-rate semantic when
ambiguity signals are present. Tiered discounts ("95% after 3 months, 90%
after 6 months") and conditional clauses ("lower of 20% or rate offered
to subsequent investors") cannot be resolved by a numeric threshold rule.

Strategy:
  1. Find all "Discount Rate is X%" / "discount of X%" candidates.
  2. Detect ambiguity signals (`tiered`, `conditional`, `multi_value`).
  3. If ambiguity present → emit with confidence="low" + signals in the
     ambiguity field. cross_checker treats ambiguity-tagged fields as
     non-disagreement (don't demote the sub-agent's read).
  4. If single unambiguous candidate → apply Gotcha #3 rule (X≥50 =
     multiplier, X<50 = rate) and emit with confidence="medium".
"""

from __future__ import annotations

import re

from extractors.types import ExtractionContext, FieldExtraction, SourceSpan

# "Discount Rate is X%" OR "Discount Rate of X%" OR "Discount Rate: X%" OR
# "discount equal to X%". Anchored to find numeric percent, capture X.
_PCT_PATTERN = re.compile(
    r"(?:Discount\s+Rate|Discounted\s+Price\s+Percentage|discount(?:\s+equal\s+to)?)"
    r"[\s:'\"“”]*(?:is\s+|of\s+)?(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# Ambiguity signals — phrases that indicate the discount is NOT a single
# scalar value. Per opus-2 review: extractor reports these, doesn't decide.
AMBIGUITY_PHRASES = (
    "lower of",
    "greater of",
    "years 1-",
    "year 1 ",
    "after 3 months",
    "after 6 months",
    "after 9 months",
    "after 12 months",
    "thereafter",
    "subject to",
    "tiered",
    "per annum",
    "annually",
    "in years",
)


def _has_ambiguity(text: str, around_match_start: int, around_match_end: int) -> list[str]:
    """Check a 200-char window around the match for ambiguity phrases."""
    window_start = max(0, around_match_start - 100)
    window_end = min(len(text), around_match_end + 100)
    window = text[window_start:window_end].lower()
    signals = []
    for phrase in AMBIGUITY_PHRASES:
        if phrase in window:
            signals.append(phrase)
    return signals


def _detect_global_ambiguity(text: str) -> list[str]:
    """Detect ambiguity phrases anywhere in the doc near 'discount' mentions.
    Used as a doc-level check independent of the anchored regex — catches
    conditional/tiered language that may not be syntactically adjacent to
    the percentage.
    """
    lower = text.lower()
    if "discount" not in lower:
        return []
    signals = []
    for phrase in AMBIGUITY_PHRASES:
        if phrase in lower:
            # Confirm the phrase is within 200 chars of a "discount" mention
            discount_pos = lower.find("discount")
            phrase_pos = lower.find(phrase)
            if abs(phrase_pos - discount_pos) < 200:
                signals.append(phrase)
    return signals


def extract(ctx: ExtractionContext) -> list[FieldExtraction]:
    text = ctx.source_text
    matches = list(_PCT_PATTERN.finditer(text))

    # If no anchored matches but doc has "discount" + ambiguity phrases,
    # emit a low-confidence "extractor refuses to decide" result.
    if not matches:
        global_amb = _detect_global_ambiguity(text)
        if global_amb:
            return [
                FieldExtraction(
                    name="discount_multiplier",
                    value=None,
                    evidence_quote=None,
                    span=None,
                    confidence="low",
                    ambiguity=(
                        f"conditional_or_tiered: discount language present but "
                        f"non-adjacent to percentage; ambiguity signals {global_amb}"
                    ),
                    extractor_id="regex:safe.discount_multiplier",
                )
            ]
        return []

    # De-dup: collect unique numeric values
    seen_values: dict[float, list[re.Match]] = {}
    for m in matches:
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        seen_values.setdefault(v, []).append(m)

    if len(seen_values) > 1:
        # Multi-value: tiered discount (95%/90%/85% pattern) or unrelated mentions
        # Emit ambiguity signal; let cross_checker treat as non-disagreement.
        m = matches[0]
        ambiguity = (
            f"multi_value: found {len(seen_values)} distinct discount percentages "
            f"({sorted(seen_values.keys())}). Extractor cannot determine which is "
            "canonical — likely tiered or referencing a different document."
        )
        return [
            FieldExtraction(
                name="discount_multiplier",
                value=None,
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="low",
                ambiguity=ambiguity,
                extractor_id="regex:safe.discount_multiplier",
            )
        ]

    # Single value across the doc — check for conditional/tiered phrases
    m = matches[0]
    pct = float(m.group(1))
    ambiguity_signals = _has_ambiguity(text, m.start(), m.end())

    if ambiguity_signals:
        ambiguity = f"conditional_or_tiered: detected ambiguity signals {ambiguity_signals}"
        return [
            FieldExtraction(
                name="discount_multiplier",
                value=None,  # extractor refuses to decide
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="low",
                ambiguity=ambiguity,
                extractor_id="regex:safe.discount_multiplier",
            )
        ]

    # Unambiguous single value — apply Gotcha #3 rule
    if pct >= 50:
        # Multiplier form: investor pays X% of price → discount = (100-X)%
        # Canonical field stores the multiplier itself
        multiplier = pct / 100.0
        gotcha_note = f"Gotcha #3 multiplier-form: '{pct}%' interpreted as multiplier (X≥50)"
    else:
        # Rate form: X% is the discount itself → multiplier = 1 - X/100
        multiplier = round(1.0 - (pct / 100.0), 4)
        gotcha_note = f"Gotcha #3 rate-form: '{pct}%' interpreted as discount rate (X<50)"

    return [
        FieldExtraction(
            name="discount_multiplier",
            value=multiplier,
            evidence_quote=m.group(0),
            span=SourceSpan(start=m.start(), end=m.end()),
            confidence="medium",
            ambiguity=gotcha_note,
            extractor_id="regex:safe.discount_multiplier",
        )
    ]
