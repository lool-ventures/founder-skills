"""Shared founder-facing text policy: what may appear in a report, and how to render it.

ONE module for the whole fleet, imported by each skill's `compose_report.py`. It exists because the
same defect was found in four skills independently, and because a per-skill copy would drift.

THE POLICY (decided 2026-08-04; do not change it here without changing the decision).

Tokens that reach a founder are not all the same kind of thing, and a single rule is wrong for at
least three of them. Four types, three behaviours:

  1. PRIVATE ENUM — our vocabulary for a state. `more_diligence`, `partially_supported`,
     `purpose_traction`. A founder gains nothing from the raw form and cannot act on it.
     -> HUMANIZE. "More diligence", "Partially supported".

  2. FIELD NAME — our name for a slot. `evidence_source`, `switching_costs`, `customer_count`.
     Same argument as (1): it is our vocabulary, and the founder cannot act on the string.
     -> HUMANIZE. "evidence source", "switching costs".

  3. STABLE PUBLIC IDENTIFIER — `safe_001`. This is TRACEABILITY: the founder cross-references it
     against their own instrument. Humanizing it would actively harm them.
     -> KEEP VERBATIM.

  4. DIAGNOSTIC CODE — `ai_claimed_unverified`. A stable, greppable warning label whose value is
     that it does not change between runs.
     -> KEEP VERBATIM.

Why the split rather than "no internal tokens", which is what competitive-positioning shipped first:
that rule would delete `safe_001` and cost a founder the ability to find their own SAFE. And why not
"gloss everything" (cap-table's `_labels.py` convention): ic-sim already proves glossing does not
finish the job — it ships a verdict legend AND still puts `more_diligence` in five sentences, so the
reader has to hold a mapping while reading a judgement about their company.

The distinction that matters is not which skill produced the line. It is whether the token is
something the founder can ACT on. An identifier is a key; an enum is a password.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Type 3 + 4 — keep verbatim. Matched BEFORE humanization so nothing rewrites them.
# ---------------------------------------------------------------------------

# Stable public identifiers: a prefix plus digits, e.g. safe_001, note_002, holder_014.
_IDENTIFIER_RE = re.compile(r"\b[a-z][a-z0-9]*_\d+\b")

# Diagnostic codes are declared per skill rather than pattern-matched: they look exactly like private
# enums, so only the emitting skill knows which is which. A code NOT listed here is treated as a
# private enum and humanized — the safe default, since a humanized diagnostic is merely less
# greppable while a raw enum is unreadable.
DIAGNOSTIC_CODES: frozenset[str] = frozenset(
    {
        "ai_claimed_unverified",
    }
)


def is_verbatim_token(token: str) -> bool:
    """True when the token must reach the founder unchanged (types 3 and 4)."""
    return bool(_IDENTIFIER_RE.fullmatch(token)) or token in DIAGNOSTIC_CODES


# ---------------------------------------------------------------------------
# Types 1 + 2 — humanize
# ---------------------------------------------------------------------------

# Words that must not be title-cased or spaced when they appear inside a token.
_ACRONYMS = {"arpu", "tam", "sam", "som", "roi", "cac", "ltv", "mrr", "arr", "api", "ai", "url", "safe"}

# Enums whose plain de-underscoring reads wrong. Keep this small: it is a correction list, not a
# dictionary. Every entry should be one a reader would otherwise stumble over.
_OVERRIDES: dict[str, str] = {
    "hard_pass": "Decline — hard pass",
    "pass": "Decline",
    "more_diligence": "More diligence",
    "not_applicable": "Not applicable",
    "do_nothing": "Do nothing",
    "not_a_competitor": "Not a competitor",
    "partially_holds": "Partially holds",
    "does_not_hold": "Does not hold",
    "agent_estimate": "Agent estimate",
    "founder_provided": "Founder provided",
    "founder_override": "Founder override",
    # Compound slide/section types read wrong de-underscored ("Purpose traction").
    "purpose_traction": "Purpose / traction",
}

# A skill that already ships its own label map (cap-table's `_labels.py`) is the better authority for
# its own vocabulary — this module must not shadow it. Callers pass those tokens via `extra_keep` and
# apply their own map first; `structural_only` is cap-table's, and its own wording ("Structure only —
# no priced round yet") is better than anything a generic de-underscoring can produce.


def humanize_token(token: str, *, capitalize: bool = True) -> str:
    """Render one private enum or field name as founder-readable text.

    `capitalize=False` for mid-sentence use ("the switching costs evidence"), True for a value in a
    labelled field ("**Verdict:** Partially holds").
    """
    if is_verbatim_token(token):
        return token
    if token in _OVERRIDES:
        out = _OVERRIDES[token]
        return out if capitalize else out[0].lower() + out[1:]
    parts = [p.upper() if p in _ACRONYMS else p for p in token.split("_")]
    text = " ".join(parts)
    return text[0].upper() + text[1:] if capitalize and text else text


# ---------------------------------------------------------------------------
# The detector — for the compose-side scan (P6)
# ---------------------------------------------------------------------------

# A token shaped like our vocabulary: lowercase, at least one underscore, no digits-only tail.
_CANDIDATE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+\b")

# Substrings whose presence means the match is a filename or path, reported separately: a founder
# cannot use `model_data.json` either, but the fix is different (drop the reference, not rename it).
_FILENAME_RE = re.compile(r"\b[a-z][a-z0-9_]*\.(?:json|py|md|html|xlsx|csv)\b")


def scan(text: str) -> dict[str, list[str]]:
    """Find founder-facing text that violates the policy.

    Returns {"enums": [...], "filenames": [...]} — sorted, de-duplicated. An empty result means the
    text carries no private enum, field name, or internal filename.

    Deliberately NOT a markdown-shape regex. An earlier attempt matched `**Label:** value`, missed
    `**Label**: value`, and a corrected version missed the first — two regexes, two different single
    hits, neither catching both. Matching the TOKEN rather than its surrounding markdown is what
    makes this reliable across the fleet's differing report dialects.
    """
    filenames = sorted({m.group(0) for m in _FILENAME_RE.finditer(text)})
    # Strip filenames first so `model_data.json` is not also reported as the enum `model_data`.
    without_files = _FILENAME_RE.sub(" ", text)
    enums = sorted({m.group(0) for m in _CANDIDATE_RE.finditer(without_files) if not is_verbatim_token(m.group(0))})
    return {"enums": enums, "filenames": filenames}


def substitute(text: str, *, extra_keep: frozenset[str] | None = None) -> str:
    """Rewrite every policy-violating token in `text` to its founder-readable form.

    Identifiers and diagnostic codes are left alone. Filenames are NOT rewritten — renaming a file in
    prose would be a lie; the caller should stop mentioning it instead.

    Longest token first, so a token that is a prefix of another is not partially replaced.
    """
    keep = (extra_keep or frozenset()) | DIAGNOSTIC_CODES
    found = {m.group(0) for m in _CANDIDATE_RE.finditer(_FILENAME_RE.sub(" ", text))}
    for token in sorted(found, key=len, reverse=True):
        if is_verbatim_token(token) or token in keep:
            continue
        text = re.sub(
            rf"(?<![\w.]){re.escape(token)}(?![\w.])",
            humanize_token(token, capitalize=False),
            text,
        )
    return text
