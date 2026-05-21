"""SAFE-specific deterministic extractors.

Regex-based field extractors that serve as backstops to the Lane-1
sub-agent. Used by `cross_checker.py` to demote sub-agent confidence when
extractors disagree.

Extractors default to `confidence="medium"` because regex is less reliable
than full LLM reading. The `discount_multiplier` extractor specifically
refuses to decide the multiplier-vs-rate semantic when tiered or
conditional clauses are present — it emits ambiguity signals instead, and
the cross_checker treats ambiguity-tagged fields as non-disagreement.
"""

from __future__ import annotations

from . import (
    discount_multiplier,
    investor_name,
    issuance_date,
    purchase_amount,
    valuation_cap,
)

# Registry: each module exposes an `extract(ctx)` function returning
# list[FieldExtraction]. Cross-checker enumerates these and pipes through
# the sub-agent comparison.
SAFE_EXTRACTORS = [
    purchase_amount,
    discount_multiplier,
    valuation_cap,
    issuance_date,
    investor_name,
]

__all__ = ["SAFE_EXTRACTORS"]
