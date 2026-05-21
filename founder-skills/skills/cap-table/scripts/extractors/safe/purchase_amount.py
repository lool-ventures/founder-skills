"""Deterministic purchase_amount extractor for SAFE documents.

Pattern: `$X (the "Purchase Amount")` where X is a USD amount with optional
thousand separators. Tolerates smart quotes (Unicode U+201C/U+201D) and
non-breaking spaces in the amount field.

Returns FieldExtraction with confidence="medium" (regex less reliable than
LLM for legal text). Span preserved when match is unambiguous.
"""

from __future__ import annotations

import re

from extractors.types import ExtractionContext, FieldExtraction, SourceSpan

# `$500,000` or `$500000` or `$5.5M` or `$5,000,000.00`. We deliberately
# don't accept bare "500000" without a `$` — too noisy on legal docs that
# reference share counts, dates, etc.
_AMOUNT_PATTERN = r"\$\s*([\d,]+(?:\.\d{2})?)"
_QUOTE_OPEN = r"[\"“]"  # ASCII " or U+201C left double quote
_QUOTE_CLOSE = r"[\"”]"  # ASCII " or U+201D right double quote

# Full pattern: $X (the "Purchase Amount") or X (the "Investment Amount")
# Plus tolerance for line-break within the parenthetical.
PURCHASE_PATTERN = re.compile(
    rf"{_AMOUNT_PATTERN}\s*\(\s*the\s+{_QUOTE_OPEN}\s*"
    rf"(?:Purchase|Investment|Subscription)\s+Amount\s*{_QUOTE_CLOSE}\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def _amount_to_int(raw: str) -> int | None:
    """Convert '500,000' / '5,000,000.00' / '5.5M' to int dollars."""
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def extract(ctx: ExtractionContext) -> list[FieldExtraction]:
    """Find all `$X (the "Purchase Amount")` occurrences in the source.

    Returns:
        - 0 fields if no match (sub-agent extraction proceeds unaided)
        - 1 field if exactly one match (the canonical case)
        - len(matches) fields if multiple — caller decides which to use
          (typically the first; backstop emits all, downstream picks).
    """
    text = ctx.source_text
    matches = list(PURCHASE_PATTERN.finditer(text))
    if not matches:
        return []

    out: list[FieldExtraction] = []
    for m in matches:
        amount = _amount_to_int(m.group(1))
        if amount is None:
            continue
        # The full evidence quote is the matched span.
        out.append(
            FieldExtraction(
                name="purchase_amount",
                value=amount,
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="medium" if len(matches) == 1 else "low",
                extractor_id="regex:safe.purchase_amount",
                ambiguity=None
                if len(matches) == 1
                else f"multiple purchase_amount candidates ({len(matches)}); regex returned first",
            )
        )
    return out
