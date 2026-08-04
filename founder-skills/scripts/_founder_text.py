"""Shared founder-facing text policy: what may appear in a report, and how to render it.

ONE module for the whole fleet, imported by each skill's `compose_report.py`; a per-skill copy would
drift.

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

A blanket "no internal tokens" rule is wrong because it would rewrite `safe_001` and cost a founder
the ability to find their own SAFE. Glossing everything is also insufficient: a legend beside a raw
token still makes the reader hold a mapping while reading a judgement about their company.

The test is whether the founder can ACT on the token. An identifier is a key; an enum is a password.
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


# Keys whose VALUES are identifiers by contract. Used by `identifier_values` below.
_ID_KEY_SUFFIXES = ("_id", "_ids", "_slug", "_slugs")


def identifier_values(obj: object, *, _depth: int = 0) -> frozenset[str]:
    """Collect identifier values out of a loaded artifact tree, for use as `extra_keep`.

    `_IDENTIFIER_RE` only recognises the `<prefix>_<digits>` form (`safe_001`), and plenty of real
    identifiers do not look like that (cap-table names a scenario `safe_conv`). Rewriting one is the
    traceability harm type 3 exists to prevent: the same id then reads one way in the JSON and another
    in the markdown, breaking correlation across the report, the explorer and the counsel packet.

    Derived from the DATA rather than hand-maintained, so it holds as new scenarios and instruments
    appear: an id present in the artifacts is an id, whatever its shape.
    """
    keep: set[str] = set()
    if _depth > 12:  # artifact trees are shallow; this only guards a pathological cycle-free depth
        return frozenset()
    if isinstance(obj, dict):
        # An ID-KEYED MAP: `per_safe: {safe_conv: {...}}`. The ids are the KEYS, so the `*_id`-value
        # rule below never sees them. Recognised by every value being a dict; a record has scalar
        # leaves (`as_converted_totals: {shares: 100}`) and is correctly not matched.
        #
        # Erring toward KEEPING is deliberate: over-keeping leaves a token raw, which the fleet ratchet
        # catches, while under-keeping rewrites an identifier and nothing catches it.
        values = list(obj.values())
        if values and all(isinstance(v, dict) for v in values):
            keep.update(k for k in obj if isinstance(k, str))
        for key, value in obj.items():
            is_id_key = isinstance(key, str) and (key == "id" or key.endswith(_ID_KEY_SUFFIXES))
            if is_id_key:
                if isinstance(value, str):
                    keep.add(value)
                elif isinstance(value, list):
                    keep.update(v for v in value if isinstance(v, str))
            keep |= identifier_values(value, _depth=_depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            keep |= identifier_values(item, _depth=_depth + 1)
    return frozenset(keep)


# ---------------------------------------------------------------------------
# Types 1 + 2 — humanize
# ---------------------------------------------------------------------------

# Abbreviated word-parts that read badly spelled out. `segment_pct` -> "segment %", matching the
# labels market-sizing already writes by hand ("**Serviceable %**").
_PART_REWRITES = {"pct": "%"}

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

# Known STATE vocabulary across the fleet — the type-1 private enums. Membership decides only
# CAPITALIZATION during bulk substitution. Position cannot decide it: `**Serviceable %**:
# partially_supported` and `— supports: customer_count` are the same markdown shape but want different
# cases, the first being a value and the second a field name in a list.
#
# An omission is COSMETIC — an unlisted enum renders lowercase, which is readable. This list must never
# become load-bearing for detection.
_ENUM_VALUES: frozenset[str] = frozenset(
    {
        # verdicts / recommendations
        "hard_pass",
        "more_diligence",
        "not_a_competitor",
        "do_nothing",
        # evidence + support strength
        "partially_supported",
        "fully_supported",
        "well_supported",
        "agent_estimate",
        "founder_provided",
        "founder_override",
        # claim outcomes
        "partially_holds",
        "does_not_hold",
        # section / stage types
        "purpose_traction",
        "business_model",
        "structural_only",
        "not_applicable",
    }
)

# LIMITATION: a SINGLE-WORD enum (`pass`, `invest`, `warn`) is undetectable here. `_CANDIDATE_RE`
# requires an underscore so the scanner does not flag every English word, so bare `pass` neither scans
# nor substitutes; dropping that requirement makes the false-positive rate unusable. Such tokens must
# be glossed by the emitting skill instead.

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
    parts = [_PART_REWRITES.get(p, p.upper() if p in _ACRONYMS else p) for p in token.split("_")]
    text = " ".join(parts)
    return text[0].upper() + text[1:] if capitalize and text else text


# ---------------------------------------------------------------------------
# The detector — for the compose-side scan (P6)
# ---------------------------------------------------------------------------

# A token shaped like our vocabulary: lowercase, at least one underscore, no digits-only tail.
#
# The lookarounds exclude a DOT-NAMESPACED identifier, and they are load-bearing: cap-table's rule ids
# are dotted (`safe.post_money_cap_conversion`) and are deliberately kept verbatim because counsel
# cites them, so a scanner without this reports all 85 of them as violations and a substituter without
# it rewrites a legal citation into prose.
#
# Why not the simpler `(?![\w.])` trailing guard: that also excludes a SENTENCE-FINAL token
# (`… is switching_costs.`), a real miss. Namespacing is specifically a dot ADJACENT TO a word char,
# so `(?!\.\w)` excludes `foo_bar.baz` while still matching a token that merely ends a sentence.
_CANDIDATE_RE = re.compile(r"(?<![\w.])[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+(?!\w)(?!\.\w)")

# Substrings whose presence means the match is a filename or path, reported separately: a founder
# cannot use `model_data.json` either, but the fix is different (drop the reference, not rename it).
_FILENAME_RE = re.compile(r"\b[a-z][a-z0-9_]*\.(?:json|py|md|html|xlsx|csv)\b")


def scan(text: str, *, extra_keep: frozenset[str] | None = None) -> dict[str, list[str]]:
    """Find founder-facing text that violates the policy.

    Returns {"enums": [...], "filenames": [...]} — sorted, de-duplicated. An empty result means the
    text carries no private enum, field name, or internal filename.

    `extra_keep` MUST accept the same set the caller passed to `substitute` — a skill that
    deliberately keeps a token (cap-table glosses its own vocabulary via `_labels.py`) would otherwise
    be warned about the exact string it chose to keep, which trains the reader to ignore the warning.

    Matches the TOKEN, never its surrounding markdown: a shape regex keyed on `**Label:** value` does
    not survive the fleet's differing report dialects (`**Label**: value` and others).
    """
    keep = (extra_keep or frozenset()) | DIAGNOSTIC_CODES
    filenames = sorted({m.group(0) for m in _FILENAME_RE.finditer(text)})
    # Strip filenames first so `model_data.json` is not also reported as the enum `model_data`.
    without_files = _FILENAME_RE.sub(" ", text)
    enums = sorted(
        {
            m.group(0)
            for m in _CANDIDATE_RE.finditer(without_files)
            if not is_verbatim_token(m.group(0)) and m.group(0) not in keep
        }
    )
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
            rf"(?<![\w.]){re.escape(token)}(?!\w)(?!\.\w)",
            humanize_token(token, capitalize=token in _ENUM_VALUES),
            text,
        )
    return text
