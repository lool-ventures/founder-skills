"""Deterministic issuance_date extractor for SAFE documents.

Prefers body-of-doc patterns ("on or about Month DD, YYYY", "as of Month DD,
YYYY", "dated Month DD, YYYY") over signature-page dates, which are often
later than the effective date and may be a DocuSign timestamp rather than
the issuance date counsel intended.

Returns None (with ambiguity) when the body has a template blank (e.g.,
"as of __________, 2024"). Enforces the anti-fabrication rule: don't
fabricate a default for a blank placeholder.
"""

from __future__ import annotations

import re
from datetime import date

from extractors.types import ExtractionContext, FieldExtraction, SourceSpan

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

# Body-of-doc anchor patterns: "on or about <date>", "as of <date>", "dated <date>"
_DATE_BODY_PATTERN = re.compile(
    r"(?:on\s+or\s+about|as\s+of|dated|effective\s+(?:as\s+of)?)\s+"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# Template-blank detection
_TEMPLATE_BLANK_PATTERN = re.compile(
    r"(?:on\s+or\s+about|as\s+of|dated)\s+_+,?\s*(?:20\d{2}|\d{4})",
    re.IGNORECASE,
)


def extract(ctx: ExtractionContext) -> list[FieldExtraction]:
    text = ctx.source_text

    # Template blank → return None with ambiguity (template-blank archetype)
    blank_match = _TEMPLATE_BLANK_PATTERN.search(text)
    if blank_match:
        return [
            FieldExtraction(
                name="issuance_date",
                value=None,
                evidence_quote=blank_match.group(0),
                span=SourceSpan(start=blank_match.start(), end=blank_match.end()),
                confidence="absent",
                ambiguity=(
                    "template_blank: source has an unfilled date placeholder. "
                    "Anti-fabrication rule applies — do not invent a default."
                ),
                extractor_id="regex:safe.issuance_date",
            )
        ]

    matches = list(_DATE_BODY_PATTERN.finditer(text))
    if not matches:
        return []

    # Prefer the FIRST body-of-doc occurrence (typically the cover/preamble).
    m = matches[0]
    month_name = m.group("month").lower()
    if month_name not in _MONTHS:
        return []
    try:
        d = date(int(m.group("year")), _MONTHS[month_name], int(m.group("day")))
    except ValueError:
        return []

    amb = None
    if len(matches) > 1:
        amb = (
            f"multiple_dates: doc has {len(matches)} body-of-doc dates; using first occurrence. "
            "Later occurrences may be signature dates or amendment dates."
        )

    return [
        FieldExtraction(
            name="issuance_date",
            value=d.isoformat(),
            evidence_quote=m.group(0),
            span=SourceSpan(start=m.start(), end=m.end()),
            confidence="medium",
            ambiguity=amb,
            extractor_id="regex:safe.issuance_date",
        )
    ]
