"""Quote matching for the numeric ledger's second-read gate.

WHY THIS IS A COPY AND NOT AN IMPORT. Skill scripts are standalone — they are run by
path, from a skill directory, with no package context — so deck-review cannot import
cap-table's `evidence_verifier`. `_theme.py` is copied across every skill for the same
reason, and `tests/test_theme_sync.py` is the precedent for keeping copies honest.

WHAT WAS COPIED, and the correction that decided it. An earlier note in the R5 design said
to copy `_normalize.py`. That is the wrong half: `_normalize.py` holds normalization and
tokenization, and ALL the matching logic — the five-step fallback, the two fuzzy passes,
and the calibrated threshold — lives in `evidence_verifier.py`. Copying only the stable
half would have locked the part that will not drift and left the part that will unguarded.
So both halves are here, and `tests/test_quote_match_sync.py` compares this file's
functions against cap-table's originals rather than against `_normalize.py` alone.

WHAT IS DELIBERATELY ABSENT. `_value_in_text` and the value-token machinery are not copied,
because on decks they do not gate. Measured by the reviewer: `value_in_doc` false-passes
**5.7%** cross-deck and **37%** on plausible round numbers, because a slide deck is dense
with round integers, page numbers and axis labels. `quote_in_doc` false-passes **0.8%**.
A number alone is not evidence in this document class; a quoted sentence is. Adding a
value check here later would be re-importing the thing this gate was inverted to avoid.
"""

from __future__ import annotations

import difflib
import re

# Calibrated in cap-table against a private evaluation set. Keep in sync; do not retune
# from deck data without re-running that evaluation, since the constant is shared.
DEFAULT_FUZZY_THRESHOLD = 0.85


def normalize_text(s: str) -> str:
    """Aggressive normalization for fuzzy text match.

    Handles pdfplumber/DocuSign-specific extraction artifacts:
      - Smart quotes → ASCII
      - Em/en dashes → hyphen
      - CID-encoded font tokens stripped
      - Hyphenation across line breaks (`foo-\\nbar` → `foobar`)
      - Whitespace collapsed
    """
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\(cid:\d+\)", "", s)
    s = re.sub(r"([a-zA-Z])-\s*\n\s*([a-zA-Z])", r"\1\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compact_form(s: str) -> str:
    """Strip everything except letters and digits.

    Last-resort matcher for pdfplumber's stuck-together-words extraction
    (e.g. `is80%` instead of `is 80%`).
    """
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


def quote_in_doc(
    quote: str,
    doc_text: str,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> tuple[bool, str, float | None]:
    """5-step fallback chain:
        1. exact substring
        2. normalized substring
        3. anchored fuzzy match (find anchor, compute ratio)
        4. compact-form substring (handles space-stripping)
        5. give up

    Returns (found, match_kind, fuzzy_ratio_if_used).
    """
    if not quote or not doc_text:
        return False, "skipped", None

    # 1. Exact substring
    if quote in doc_text:
        return True, "exact", None

    # 2. Normalized
    qn = normalize_text(quote)
    dn = normalize_text(doc_text)
    if qn in dn:
        return True, "normalized", None

    # 3. Anchored fuzzy: take first 30 chars of quote as anchor, find in doc,
    # then check SequenceMatcher ratio on the surrounding window.
    if len(qn) >= 30:
        anchor = qn[:30]
        idx = dn.find(anchor)
        if idx != -1:
            window = dn[idx : idx + len(qn) + 50]
            ratio = difflib.SequenceMatcher(None, qn, window).ratio()
            if ratio >= fuzzy_threshold:
                return True, "fuzzy_anchored", ratio

    # 3b. Sliding window fuzzy for short quotes
    if len(qn) < 200:
        win_size = max(len(qn) + 30, 50)
        best_ratio = 0.0
        step = max(win_size // 4, 1)
        for i in range(0, max(len(dn) - win_size + 1, 1), step):
            r = difflib.SequenceMatcher(None, qn, dn[i : i + win_size]).ratio()
            if r > best_ratio:
                best_ratio = r
        if best_ratio >= fuzzy_threshold:
            return True, "fuzzy_window", best_ratio

    # 4. Compact-form fallback
    qc = compact_form(quote)
    dc = compact_form(doc_text)
    if qc and qc in dc:
        return True, "compact", None

    return False, "not_found", None
