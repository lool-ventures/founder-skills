"""Founder-facing wording for the adversarial review's prose.

The reviewer writes `claim_attacked`, `what_is_true` and each `could_not_check` line as free text, and
every word is printed to the founder. It reads this run's own files, so it names things the way it read
them: a competitor by its slug ("carbon-robotics"), the startup as `_startup`, a moat by its field name
(`switching_costs`), a file by its filename (`moat_scores.json`). The report shows none of those
anywhere else -- a slug in a table was the leak both baseline runs reproduced -- so the review may not
be the way they come back.

The wording is fixed where the review is produced, deterministically, before anyone else can see it:
nothing is left for the reviewed party to edit. The review's own quote (`evidence_quote`) is never
touched -- it is a quotation, and a reworded quotation is a false one. The founder's own document names
and URLs are left as written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

INTERNAL_FILE_PHRASES: dict[str, str] = {
    "landscape.json": "the competitor research",
    "landscape_draft.json": "the first list of competitors",
    "positioning.json": "the positioning inputs",
    "positioning_scores.json": "the positioning map",
    "moat_scores.json": "the moat ratings",
    "product_profile.json": "the profile of your company",
    "startup_research.json": "the research on your company's public record",
    "competitor_verification.json": "the challenge to the competitor list",
    "checklist.json": "the quality checklist",
    "report.json": "the report",
    "report.md": "the report",
}
_OTHER_FILE_PHRASE = "the analysis's working files"
# Before a possessive, a phrase that ends in its own possessive or preposition reads badly ("the research
# on your company's public record's searches"), so these use a compact noun instead.
COMPACT_FILE_PHRASES: dict[str, str] = {
    "startup_research.json": "the public-record research",
    "product_profile.json": "the company profile",
    "competitor_verification.json": "the competitor-list challenge",
}
_POSSESSIVE_RE = re.compile(r"['\u2019]s\b")
# Field names a reviewer quotes back. Anything else snake_case becomes its words.
FIELD_WORDS: dict[str, str] = {
    "network_effects": "network effects",
    "data_advantages": "data advantages",
    "switching_costs": "switching costs",
    "regulatory_barriers": "regulatory barriers",
    "cost_structure": "cost structure",
    "brand_reputation": "brand reputation",
    # Article-free, like the rest: a field name is used as a noun or a modifier ("the analysis's checked
    # differentiation_claims list"), and a phrase carrying its own article reads "checked the claims…".
    "differentiation_claims": "differentiation claims",
    "product_availability": "product availability",
}

# Left boundary excludes `-`, `.`, `/` and word characters: `founder-notes.md` and a path segment are
# not ours to rewrite.
_B_L = r"(?<![\w.\-/$])"
_FILE_RE = re.compile(_B_L + r"[a-z][a-z0-9_]*\.(?:json|py|md|html)(?![\w\-])")
_STARTUP_RE = re.compile(r"(?<![\w\-])_startup(?![\w\-])")
_IDENT_RE = re.compile(_B_L + r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\.[a-z][a-z0-9_]*)*(?![\w\-/])")
_URL_RE = re.compile(r"https?://\S+")
_SLUG_SHAPED = re.compile(r"[-_0-9]")
_ABBREVIATIONS = frozenset({"vs.", "e.g.", "i.e.", "etc.", "approx.", "u.s.", "no."})
# A reviewer writes "the moat_scores.json rating": its own determiner already stands before the name, so
# the replacement's leading "the" is dropped rather than doubled ("the the moat ratings").
_DETERMINERS = frozenset({"the", "a", "an", "this", "that", "these", "those", "its", "their", "your", "our"})


def _at_sentence_start(src: str, pos: int) -> bool:
    """A replacement that opens a sentence is capitalised -- never after "vs." or "e.g."."""
    before = src[:pos]
    if not before.strip():
        return True
    m = re.search(r"(\S+)\s+$", before)
    return bool(m and m.group(1)[-1] in ".!?" and m.group(1).lower() not in _ABBREVIATIONS)


def _after_determiner(src: str, pos: int) -> bool:
    m = re.search(r"([A-Za-z]+)\s+$", src[:pos])
    return bool(m and m.group(1).lower() in _DETERMINERS)


def _fit(src: str, pos: int, phrase: str) -> str:
    """A replacement phrase fitted to where it lands: its "the" dropped after the writer's own
    determiner, capitalised at the start of a sentence."""
    if phrase.startswith("the ") and _after_determiner(src, pos):
        return phrase[len("the ") :]
    return phrase[:1].upper() + phrase[1:] if _at_sentence_start(src, pos) else phrase


def _mask_urls(text: str, slots: list[str]) -> str:
    def _mask(m: re.Match[str]) -> str:
        slots.append(m.group(0))
        return f"\x00{len(slots) - 1}\x00"

    return _URL_RE.sub(_mask, text)


def _unmask(text: str, slots: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)


def file_phrase(src: str, m: re.Match[str], fallback: str | None = None) -> str | None:
    """The plain-words phrase for the file name `m` matched in `src`: its compact form before a possessive,
    else its usual one; `fallback` for a file that is not ours (None leaves it as written)."""
    name = m.group(0)
    if _POSSESSIVE_RE.match(src, m.end()) and name in COMPACT_FILE_PHRASES:
        return COMPACT_FILE_PHRASES[name]
    return INTERNAL_FILE_PHRASES.get(name, fallback)


def reword_our_files(text: str) -> tuple[str, int]:
    """Only OUR file names (INTERNAL_FILE_PHRASES) become plain words; any other file name -- a founder's
    `notes.md` -- and every URL are left as written. For text a scorer writes, where a founder's own
    document may be named and no list of them is at hand."""
    slots: list[str] = []
    masked = _mask_urls(text, slots)
    count = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal count
        phrase = file_phrase(masked, m)
        if phrase is None:
            return m.group(0)
        count += 1
        return _fit(masked, m.start(), phrase)

    return _unmask(_FILE_RE.sub(_sub, masked), slots), count


# Fields a scorer writes as prose about its sources. Quotes and sources are never reworded: a quote is
# someone else's words, and a source is where to check them.
_PROSE_KEY_RE = re.compile(r"(?:^|_)(?:evidence|rationale)$")


def reword_evidence(data: object) -> int:
    """Reword our file names in every evidence / rationale string under `data`, in place. Returns the count.

    Run by each scorer on its input, at pipe time: the report's final wording pass flags a file name it
    finds, and a scored artifact edited after the outside review to remove one reads as an analysis that
    changed after it was reviewed (both runs of the first live check did exactly that)."""
    total = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and isinstance(key, str) and _PROSE_KEY_RE.search(key):
                data[key], n = reword_our_files(value)
                total += n
            else:
                total += reword_evidence(value)
    elif isinstance(data, list):
        for item in data:
            total += reword_evidence(item)
    return total


def _ident_words(tok: str) -> str:
    words: list[str] = []
    for part in (p for p in tok.split(".") if p):
        if part in FIELD_WORDS:
            words.append(FIELD_WORDS[part])
        elif part.startswith("custom_"):
            words.append(part[len("custom_") :].replace("_", " "))
        else:
            words.append(part.replace("_", " "))
    return " ".join(words)


def humanize_review_text(
    text: str,
    protected: Iterable[str] = (),
    *,
    name_by_slug: Mapping[str, str] | None = None,
    startup_name: str | None = None,
) -> tuple[str, int]:
    """Rewrite our slugs, file names and identifiers in one review field. Returns (text, replacements).

    `protected` is the founder's own document names: an uploaded `notes.md` is theirs, not ours. URL
    spans are left alone too. Deterministic, and applied to prose fields only.
    """
    keep = sorted({p for p in protected if p}, key=len, reverse=True)
    slots: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        slots.append(m.group(0))
        return f"\x00{len(slots) - 1}\x00"

    masked = _URL_RE.sub(_mask, text)
    for name in keep:
        masked = re.sub(re.escape(name), _mask, masked)

    count = 0

    # Only OUR replacements are fitted -- never the author's own words (`_fit`).
    def _emit(src: str, m: re.Match[str], phrase: str) -> str:
        nonlocal count
        count += 1
        return _fit(src, m.start(), phrase)

    out = _FILE_RE.sub(lambda m: _emit(masked, m, file_phrase(masked, m, _OTHER_FILE_PHRASE) or ""), masked)
    who = startup_name.strip() if isinstance(startup_name, str) and startup_name.strip() else "your company"
    out = _STARTUP_RE.sub(lambda m: _emit(out, m, who), out)
    # Longest slug first, so a slug that is a prefix of another is never partly replaced. A name is a
    # proper noun and is never re-cased; each replacement is masked so a later slug cannot rewrite
    # inside a name already substituted. Only a slug that cannot be an ordinary word is replaced: a
    # one-word slug ("notion") in the reviewer's prose is far likelier to be the English word, and the
    # reviewer is told to name competitors, so rewriting it would put a company where none was meant.
    slugs = (s for s in (name_by_slug or {}) if s and s != "_startup" and _SLUG_SHAPED.search(s))
    for slug in sorted(slugs, key=len, reverse=True):
        name = str((name_by_slug or {})[slug])

        def _named(m: re.Match[str], name: str = name) -> str:
            nonlocal count
            count += 1
            slots.append(name)
            return f"\x00{len(slots) - 1}\x00"

        out = re.sub(rf"(?<![\w\-]){re.escape(slug)}(?![\w\-])", _named, out)
    out = _IDENT_RE.sub(lambda m: _emit(out, m, _ident_words(m.group(0))), out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], out)
    return out, count
