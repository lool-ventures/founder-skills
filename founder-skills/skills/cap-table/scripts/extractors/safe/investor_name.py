"""Deterministic investor_name extractor for SAFE documents.

Pattern: `payment by <NAME> (the "Investor")` is the canonical YC SAFE
preamble. We capture the NAME between "payment by" and the parenthetical.

Sub-agent typically returns a legally-precise long-form name; extractor
returns whatever appears between the anchors. cross_checker's bidirectional
substring match treats prefix/suffix variations as agreement.
"""

from __future__ import annotations

import re

from extractors.types import ExtractionContext, FieldExtraction, SourceSpan

# "in exchange for the payment by <NAME> (the "Investor")" — capture NAME.
# Stop at the opening paren so we don't grab the parenthetical.
INVESTOR_PATTERN = re.compile(
    r"payment\s+by\s+(?P<name>[A-Z][A-Za-z0-9 .,&\-/']{2,80}?)\s*\(\s*"
    r"(?:the\s+)?[\"“](?:the\s+)?Investor[\"”]\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def extract(ctx: ExtractionContext) -> list[FieldExtraction]:
    text = ctx.source_text
    m = INVESTOR_PATTERN.search(text)
    if not m:
        return []
    name = m.group("name").strip().strip(",").strip()
    if not name or len(name) < 3:
        return []
    return [
        FieldExtraction(
            name="investor_name",
            value=name,
            evidence_quote=m.group(0),
            span=SourceSpan(start=m.start(), end=m.end()),
            confidence="medium",
            extractor_id="regex:safe.investor_name",
        )
    ]
