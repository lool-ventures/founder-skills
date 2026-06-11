"""Deterministic valuation_cap extractor — distinguishes pre/post-money form.

Reports BOTH candidates separately when the document is ambiguous:
  - `post_money_valuation_cap` if "Post-Money Valuation Cap" definition found
  - `pre_money_valuation_cap` if bare "Valuation Cap" without "Post-Money" prefix

cross_checker uses this to detect when the sub-agent picked the wrong field.
When BOTH appear in the doc (overlap pattern: bare term + post-money formulas),
the extractor returns BOTH with ambiguity signals; cross_checker treats this
as non-disagreement vs. the sub-agent's classification.
"""

from __future__ import annotations

import re

from extractors.types import ExtractionContext, FieldExtraction, SourceSpan

# Capture the magnitude suffix in its own group so scaling is driven by the
# matched suffix only — never by stray substrings (e.g. the ' m' inside
# ' money') elsewhere in the surrounding text.
_AMOUNT = r"(?:US)?\$\s*([\d,]+(?:\.\d+)?)\s*(million|MM|M|billion|bn|B)?"

# Post-money pattern: "Post-Money Valuation Cap" is $X
POST_MONEY_PATTERN = re.compile(
    rf"[\"“]?Post[- ]Money\s+Valuation\s+Cap[\"”]?\s+(?:is|of|=)\s+{_AMOUNT}",
    re.IGNORECASE,
)

# Standalone "Post-Money Valuation Cap" mentions (without trailing amount).
# Used to detect the hybrid-terminology pattern where the defined term is
# bare "Valuation Cap" but the formulas reference "Post-Money Valuation Cap".
POST_MONEY_MENTION_PATTERN = re.compile(
    r"Post[- ]Money\s+Valuation\s+Cap",
    re.IGNORECASE,
)

# Bare "Valuation Cap" is $X — used by pre-money form. Negative lookbehind
# would be cleaner but Python requires fixed-width — we filter after match.
BARE_CAP_PATTERN = re.compile(
    rf"[\"“]?Valuation\s+Cap[\"”]?\s+(?:is|of|=)\s+{_AMOUNT}",
    re.IGNORECASE,
)


def _parse_amount(raw: str, suffix: str | None = None) -> int | None:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        n = float(cleaned)
    except ValueError:
        return None
    s = (suffix or "").lower()
    if s in {"million", "mm", "m"}:
        n *= 1_000_000
    elif s in {"billion", "bn", "b"}:
        n *= 1_000_000_000
    return int(n)


def extract(ctx: ExtractionContext) -> list[FieldExtraction]:
    text = ctx.source_text

    # Find "Post-Money Valuation Cap" is $X matches first (full pattern with amount)
    post_matches = list(POST_MONEY_PATTERN.finditer(text))
    post_match_spans = {(m.start(), m.end()) for m in post_matches}

    # Find any standalone "Post-Money Valuation Cap" mentions (no amount required).
    # Used to detect hybrid terminology where the defined term is bare but the
    # formulas reference post-money.
    all_post_mentions = list(POST_MONEY_MENTION_PATTERN.finditer(text))
    has_post_money_anywhere = len(all_post_mentions) > 0

    # Find bare "Valuation Cap" is $X matches, excluding those that overlap a
    # full Post-Money match.
    bare_matches = []
    for m in BARE_CAP_PATTERN.finditer(text):
        if any(ps <= m.start() < pe for ps, pe in post_match_spans):
            continue
        prefix = text[max(0, m.start() - 30) : m.start()].lower()
        if "post-money" in prefix or "post money" in prefix:
            continue
        bare_matches.append(m)

    out: list[FieldExtraction] = []

    if post_matches:
        # Standard case: "Post-Money Valuation Cap" is $X
        m = post_matches[0]
        val = _parse_amount(m.group(1), m.group(2))
        amb = None
        if bare_matches:
            amb = (
                f"hybrid_terminology: doc uses both 'Post-Money Valuation Cap' "
                f"({len(post_matches)}x with amount) and bare 'Valuation Cap' "
                f"({len(bare_matches)}x). Post-money classification preferred; "
                "see hybrid-terminology guidance in the extraction docs."
            )
        out.append(
            FieldExtraction(
                name="post_money_valuation_cap",
                value=val,
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="medium",
                ambiguity=amb,
                extractor_id="regex:safe.valuation_cap.post_money",
            )
        )
    elif bare_matches and has_post_money_anywhere:
        # Hybrid case: bare defined term but post-money references in formulas
        # (the bare-term + post-money overlap pattern seen in real SAFEs).
        # Take the value from the bare match but classify
        # as post-money on the basis of the formula references.
        m = bare_matches[0]
        val = _parse_amount(m.group(1), m.group(2))
        out.append(
            FieldExtraction(
                name="post_money_valuation_cap",
                value=val,
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="medium",
                ambiguity=(
                    f"hybrid_terminology: bare 'Valuation Cap' is the defined "
                    f"term, but doc has {len(all_post_mentions)} 'Post-Money "
                    "Valuation Cap' references (likely in price formulas). "
                    "Classified as post-money per structural-signal precedence."
                ),
                extractor_id="regex:safe.valuation_cap.hybrid",
            )
        )
    elif bare_matches:
        # Pure pre-money: bare "Valuation Cap" with no "Post-Money" anywhere
        m = bare_matches[0]
        val = _parse_amount(m.group(1), m.group(2))
        out.append(
            FieldExtraction(
                name="pre_money_valuation_cap",
                value=val,
                evidence_quote=m.group(0),
                span=SourceSpan(start=m.start(), end=m.end()),
                confidence="medium",
                ambiguity="bare 'Valuation Cap' with no 'Post-Money' references → pre-money form",
                extractor_id="regex:safe.valuation_cap.pre_money",
            )
        )

    return out
