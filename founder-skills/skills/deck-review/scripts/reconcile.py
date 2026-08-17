#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Verify a deck's numeric ledger and compute the relations proposed over it.

The skill has always scored `numbers_consistent` as one of its 35 criteria on the model's
say-so, and has never done arithmetic. This is where the arithmetic happens.

THE DIVISION OF LABOUR, and why it is this way:

  the model  chooses WHICH figures relate      -- judgment, and the thing F5 needs
  this file  does the arithmetic               -- deterministic, correct by construction
  this file  refuses relations it cannot trust -- gate + unit algebra
  the model  interprets the result             -- judgment, labelled as such

The failure this addresses is OMISSION, not miscalculation: the reviewer held every
operand and never multiplied. So the behaviour change comes from asking for relations at
all. This file's contribution is that the resulting number is right, that it is
traceable, and that SKILL.md's "never arithmetic in prose" rule has a sanctioned outlet.

WHAT THE GATE ESTABLISHES, precisely. A figure's quote passes if it is re-found by a
second reader who never saw the ledger. That catches a quote that is not in the deck at
all -- invented, or composed out of a chart. It does NOT catch rewording: matching falls
back to a similarity ratio at 0.85 (`_quote_match.py`), and measured against the shipped
matcher, "increased" vs "decreased", "double" vs "decline" and "$45 billion" vs
"$46 billion" all pass.
It does NOT establish that the figure's VALUE is correct -- the matcher deliberately
omits value binding, see `_quote_match.py` -- and the second reader does not read the
deck independently of the first: both are handed the same main-thread-extracted text,
so the two readings descend from one act of reading, not two. It says nothing about
ATTRIBUTION either, which is tracked separately below and is the weaker link.

The calibration numbers this docstring used to cite here (95.7-100% true-pass, 0.0%
cross-deck false-pass, 0.0% on invented quotes) described a PROTOTYPE design -- a
genuinely independent vision transcription -- that was never shipped. They are kept
here, marked as such, rather than deleted, because they describe a design that was
considered, not the gate that runs today.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _artifact_writer import load_schema, write_artifact  # type: ignore[import-not-found]  # noqa: E402
from _quote_match import quote_in_doc  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Unit algebra. This is where "correct by construction" actually breaks: a script
# divides flawlessly and is off by 1000x if one operand was recorded in thousands.
# Every F5 example is scale-sensitive ($493k / $8M, $60k/mo x 12, 500k vs 360,000).
# ---------------------------------------------------------------------------

MONEY, COUNT, PERCENT, MULTIPLE, DURATION, DATE = "money", "count", "percent", "multiple", "duration", "date"


@dataclass
class Figure:
    id: str
    value: float
    raw: str
    unit_kind: str
    label: str
    slide: int | None
    quote: str
    currency: str | None = None
    period: str | None = None
    lo: float | None = None  # stated range low; None when the figure is a point value
    hi: float | None = None
    verified: bool = False
    attribution: str = "layout_attributed"
    # "at_least" | "at_most" | "approximate" | None. NOT expressed as an infinite lo/hi:
    # span() feeds operand interval arithmetic, where an infinity yields inf/inf = nan,
    # every nan comparison is False, and the relation renders "matches the stated ..." --
    # a false confirmation. It would also make json.dumps emit bare Infinity/NaN, which
    # is not valid JSON. So the openness lives here and is read ONLY when comparing.
    bound: str | None = None
    # Can a person reading the slide SEE this number? For a PDF, yes by construction --
    # it was read off a rendered page. For a .pptx read out of the file, often NOT:
    # measured on the one .pptx in the corpus, 73% of extracted figures (351 of 477) come
    # from chart series data with no value labels shown. Those numbers are real and worth
    # checking, but a finding built on them must never say "the deck states", because the
    # deck states no such thing -- its chart merely plots it.
    visible: bool = True

    def span(self) -> tuple[float, float]:
        """The figure as an interval. A point value is a zero-width one."""
        return (self.lo, self.hi) if self.lo is not None and self.hi is not None else (self.value, self.value)

    drop_reason: str | None = None


@dataclass
class Relation:
    kind: str  # "derived_ratio" | "contradiction"
    operands: list[str]
    operator: str
    computed: float | None = None
    rendered: str = ""
    confidence: str = "high"
    reasons: list[str] = field(default_factory=list)
    dropped: bool = False
    # Selection (see classify/select below). `verdict` is what decides whether a founder
    # ever sees this relation, and for contradictions it is COMPUTED, not judged.
    computed_unit: str | None = None  # dimension of `computed`, for the comparison below
    span_lo: float | None = None  # interval result when any operand was a range
    span_hi: float | None = None
    expected_id: str | None = None
    expected_value: float | None = None
    verdict: str = "derived"  # contradiction | confirmation | derived | restatement


# A single-letter suffix must not be the first letter of a WORD. Without this guard
# "18 months" read as 18 megadollars and returned a tolerance of 500,000 -- and 30 of the
# 708 corpus figures ended up with a tolerance LARGER THAN THEIR OWN VALUE, unable to
# contradict anything. That is not a symmetric bug: it produced a false CONFIRMATION,
# "1 million / 2,000 = 500.00x -- matches the stated 1000X", certifying a factor-of-two
# gap as consistent. _RANGE_RE below has carried exactly this guard, with a comment
# saying why, the whole time.
#
# The guard alone is not enough. "$48 billion" and "1 million" parse correctly TODAY only
# by accident -- because "billion" and "million" happen to start with the right letter --
# so adding the guard without also parsing the words would regress them. Both are needed,
# and "trillion" was never handled at all.
_SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12, **_SCALE_WORDS}

_NUM_RE = re.compile(
    r"(?P<int>\d[\d,]*)(?:\.(?P<frac>\d+))?\s*"
    r"(?P<suf>thousand|million|billion|trillion|[kKmMbBtT](?![a-zA-Z]))?",
    re.I,
)

CAP = 0.05
"""Ceiling on relative precision. A CHOICE, not a derivation.

Significant figures alone are far too generous on small round integers -- "200" is one
significant figure, which claims only +/-50, i.e. 25%. Decks routinely round to two
significant figures and 5% is roughly the granularity of "about", so the cap binds
exactly where sig-figs stop being informative and never where they are.
"""

APPROX_WIDENING = 0.10
"""Tolerance for a figure the author explicitly marked approximate ("~55%"). A CHOICE.

Applied OUTSIDE the CAP: the cap exists to stop significant figures over-claiming, and an
explicit "~" is the author overriding that concern in the other direction.
"""


def _raw_scale(raw: str) -> float:
    """The scale multiplier written on a raw string, preferring a range's shared suffix.

    "$150-250K" is 150k to 250k -- the suffix binds to BOTH endpoints, but it sits after
    the second one, where a left-to-right scan never reaches it. That scan returned a
    tolerance of 0.5 on a figure denominated in thousands, 1000x too small, on a class
    that is 26% of every ledger.
    """
    rng = _RANGE_RE.search(raw or "")
    if rng and rng.group("suf"):
        return _SCALE.get(rng.group("suf").lower(), 1.0)
    m = _NUM_RE.search(raw or "")
    return _SCALE.get((m.group("suf") or "").lower(), 1.0) if m else 1.0


def implied_tolerance(raw: str) -> float:
    """Written precision of a raw string, in the units the raw string itself is written in.

    Retained as the FLOOR under `figure_tolerance` so that the relative rule below can
    only ever relax, never tighten. On its own it is not the comparison tolerance: it
    reads the raw string, and the comparison runs on values -- `implied_tolerance
    ("(19,391)")` is 0.5 while the value being compared is 19,391,000.
    """
    m = _NUM_RE.search(raw or "")
    if not m:
        return 0.0
    decimals = len(m.group("frac") or "")
    return float(0.5 * _raw_scale(raw) / (10**decimals))


def _precision(raw: str) -> tuple[float, float] | None:
    """(half the last significant unit, the number) in the raw string's OWN space.

    Deliberately scale-free: the ratio of these two is what gets applied to the figure's
    value, so it does not matter whether a `k`, the word "trillion", or a table header
    carried the scale, or whether anything did. That is what makes this survive the 52
    corpus figures whose value is >=10x their raw-parsed magnitude -- almost all of them
    legitimate, and none of them recoverable by parsing the string harder.

    Trailing zeros are NOT significant: "1,700" claims two figures and tolerates +/-50,
    while "1,696" claims four and tolerates +/-0.5.
    """
    m = _NUM_RE.search(raw or "")
    if not m:
        return None
    ints = (m.group("int") or "").replace(",", "")
    frac = m.group("frac") or ""
    if not ints:
        return None
    if frac:
        last = 10.0 ** (-len(frac))
    else:
        stripped = ints.rstrip("0")
        last = 10.0 ** (len(ints) - len(stripped)) if stripped else 10.0 ** (len(ints) - 1)
    return 0.5 * last, float(ints) + (float("0." + frac) if frac else 0.0)


_RANGE_RE = re.compile(
    # The suffix must not be the first letter of a WORD: "12-14 Months" is twelve to
    # fourteen months, not twelve to fourteen million. Requiring a non-letter after it
    # is what separates "$150-250K" from "0–18 Months".
    r"(?P<a>\d[\d,]*(?:\.\d+)?)\s*[-–—]\s*\$?\s*(?P<b>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suf>thousand|million|billion|trillion|[kKmMbBtT](?![a-zA-Z]))?",
    re.I,
)


def parse_range(raw: str) -> tuple[float, float] | None:
    """Pull (low, high) out of a stated range: "$200–$260", "12–18%", "$150-250K".

    26% of all figures extracted from real decks are ranges, so treating one as a single
    number is not an edge case -- it is a quarter of the ledger. Collapsing "$200–$260"
    to 200 silently discards the author's own statement of uncertainty, and it is why
    the model proposed the same comparison twice with different endpoints and the script
    reported both as contradictions.

    A trailing scale suffix binds to BOTH endpoints: "$150-250K" is 150k to 250k, not
    150 to 250,000.
    """
    m = _RANGE_RE.search(raw or "")
    if not m:
        return None
    scale = _SCALE.get((m.group("suf") or "").lower(), 1.0)
    lo = float(m.group("a").replace(",", "")) * scale
    hi = float(m.group("b").replace(",", "")) * scale
    return (lo, hi) if lo <= hi else (hi, lo)


# A trailing "+" is a floor; a LEADING "+" is a delta sign and not a bound at all. The
# corpus carries "+76%" and "100%+" on the same deck as "$200B+", so requiring a digit
# before the "+" is what separates them. Not end-anchored: "270+ sites" is a floor too.
_PLUS_RE = re.compile(r"\d\s*[kKmMbBtT%]?\s*\+")
_LEAD_AT_MOST = re.compile(r"^\s*[<≤]")
_LEAD_AT_LEAST = re.compile(r"^\s*[>≥]")
# A bound word LEADING the raw string qualifies the figure itself: "Over 30%", "at least
# $2M". Anchored deliberately -- an unanchored word match reads "1103% over 6 mths" as a
# floor on 1103%, where "over" is a time preposition. The label path stays word-based and
# unanchored because a label is prose about the figure; the raw string is the figure.
_LEAD_AT_LEAST_WORDS = re.compile(r"^\s*(over|above|at least|more than|minimum of|no less than)\s+\$?\d", re.I)
_LEAD_AT_MOST_WORDS = re.compile(r"^\s*(under|below|fewer than|less than|at most|up to|no more than)\s+\$?\d", re.I)
_AT_MOST_WORDS = re.compile(r"\b(fewer than|less than|under|up to|at most|no more than|below)\b", re.I)
_AT_LEAST_WORDS = re.compile(r"\b(at least|more than|over|exceeds|minimum|or more)\b", re.I)
# These words mean the AUTHOR ROUNDED. They do not mean the author is unsure about the
# future, and conflating the two is what `target` and `projected` did here.
#
# `target` was the clearer error of the two. "$6.5M seed round target" and "25% target
# margin" are precise stated numbers -- a target is a specific figure, not a rounded one --
# and `\btarget\w*` also collided with an unrelated word sense: "3 main TARGET MARKETS"
# marked the 3 approximate. Measured on the corpus, `target|projected|est` alone accounted
# for 57 of 81 approximations (70%), 24 of them load-bearing inside a computed relation.
#
# `projected` is the deliberate call, and it went the other way on purpose. A projection is
# uncertain about the WORLD; the figure itself is still stated exactly, and a forecast that
# does not add up is a finding. Widening tolerance there made the tool most forgiving
# exactly where a founder's arithmetic most often fails. "Projected MRR $205,000" now gets
# the tolerance its own significant figures earn and nothing more.
#
# A bound can only ever suppress a contradiction (see detect_bound), so every entry here
# buys silence. Add one only for a word that genuinely marks rounding.
#
# SYMBOLS AND WORDS ARE SEPARATE BECAUSE THEY ARE READ FROM DIFFERENT PLACES. `detect_bound`
# states the rule -- symbols come from `raw` ONLY, because a label's symbol routinely
# qualifies something other than the figure. The approximate branch used to search a single
# combined pattern against `raw` AND `label`, so a `~` anywhere in a label widened tolerance
# by `APPROX_WIDENING` on a figure that was never marked approximate. Measured: a summed
# 108 against a stated 100 returns `contradiction`, but with an unrelated `~` or `≈` in the
# label it returns `confirmation` -- a real finding erased by a glyph belonging to a
# different number. The `>200m` case pinned in `test_a_symbol_in_the_label_is_never_read_as_a_bound`
# was already guarded; this closes the same hole on the approximate path.
#
# `≈` (U+2248) sits with `~`, and reaches less than it looks like it should: this function
# sees `raw` and `label`, never `quote`. A deck that prints a bare bar value and carries the
# `≈` only in the surrounding sentence puts the glyph where nothing here can read it. Binding
# an approximation marker from the quote to the figure is a separate problem.
# The symbol must qualify THIS figure's number, so it has to appear BEFORE the first
# numeric token -- the same token `_parsed_magnitude` reads the magnitude from -- and there
# has to be a number for it to qualify. `raw` is supposed to be one figure's own printed
# string, but the schema permits any string and nothing enforces it, so a whole-string
# search marks "$100 vs 2024 ≈ 20" approximate off a glyph belonging to a different number,
# and a bare "≈" (which `ledger.py` also accepts, since it skips the scale check when `raw`
# has no parseable magnitude) marks a figure approximate off no number at all. Both widen
# tolerance to 10% and can only erase a contradiction. No corpus instance of either shape
# exists; this is a contract guard.
#
# The prefix is located with `_NUM_RE` rather than an inline digit class, so this shares the
# parser's Unicode `\d` grammar instead of duplicating it as ASCII `[0-9]`.
_APPROX_SYMBOLS = re.compile(r"[~≈]")


def _approx_symbol_marks_this_figure(raw: str) -> bool:
    """Is there an approximation glyph before this figure's own number?"""
    match = _NUM_RE.search(raw)
    if not match:
        return False
    return bool(_APPROX_SYMBOLS.search(raw[: match.start()]))


_APPROX_WORDS = re.compile(r"(\bapprox\w*|\babout\b|\baround\b|\broughly\b|\best\b|\bestimated\b)", re.I)

# Only whitespace may sit between the glyph and the figure it qualifies.
_QUOTE_APPROX_PREFIX = re.compile(r"[~≈]\s*$")

# WHERE THE NUMBER ENDS, rather than which characters may not follow it. A denylist of
# continuation characters could not converge: three rounds each fixed the named examples
# and left the next separator -- a scale word, then grouped thousands, then a hyphenated
# scale ("≈$20-billion"), a spelled Indian unit ("≈$20 crore"), Arabic-Indic grouping,
# "≈$20×10^6". In every one, `raw="$20"` was a PREFIX of a bigger number and inherited its
# approximation, silencing a real contradiction.
#
# So match the maximal numeric lexeme at the position instead and require the figure to BE
# it. `\d` is Unicode-aware, which covers Arabic-Indic digits; the separator class covers
# the grouping marks decks actually use.
_NUMERIC_LEXEME = re.compile(
    r"\d[\d\u0660-\u0669\u06f0-\u06f9]*"
    # Grouped thousands. A plain SPACE separator is admitted only before exactly three
    # digits ("20 000"), so it cannot swallow an unrelated number two words later; the
    # non-space marks are unambiguous and take \d+.
    r"(?:[.,\u00a0\u202f\u2009'\u2019\u2032\u066c]\d[\d\u0660-\u0669\u06f0-\u06f9]*|\ \d{3}(?!\d))*"
    r"(?:\s*[×xX*]\s*10\s*[\^]?\s*[-+]?\d+)?"
    r"(?:[eE][-+]?\d+)?"
    r"(?:\s*%|\s*[-\u2010-\u2015]?\s*(?:thousand|million|billion|trillion|crore|lakh|k|m|bn|b|tn|t)\b)?",
    re.I,
)


def _numeric_lexeme_end(text: str, start: int) -> int:
    """Where the number beginning at `start` actually ends."""
    match = _NUMERIC_LEXEME.match(text, start)
    return match.end() if match else start


def _approx_symbol_marks_this_figure_in_quote(raw: str, quote: str) -> bool:
    """Does the QUOTE carry an approximation glyph attached to this figure's own number?

    Measured on one live ledger: `≈` appeared in **0 of 81 `raw` values and 7 quotes** — the
    seven chart bars a deck printed bare while marking them approximate in the surrounding
    sentence. Reading `raw` and `label` alone reaches none of them, so those figures were
    carried as exact claims and could be reported as contradicting a number the deck itself
    said was approximate. That is the false-contradiction direction this module treats as
    the worst thing it can emit.

    THE BINDING IS TIGHTER THAN THE `raw` RULE, NOT LOOSER, and it has to be. `raw` is
    supposed to be one figure's own printed string, so "the glyph precedes the first number"
    is nearly always the right reading there. A quote is a whole sentence and routinely names
    several figures, so the same rule would let a glyph belonging to one number qualify
    another -- the exact hole that was closed on the `raw` path, reopened one field over.
    Here the figure's own printed string must be located inside the quote and the glyph must
    sit IMMEDIATELY before it, whitespace only.

    A figure whose `raw` does not appear verbatim in its own quote reads NO bound. The quote
    is required to be verbatim, so that is either a paraphrase or a differently-formatted
    number, and neither lets a glyph be positioned relative to the figure. Guessing is not
    available: every bound makes the comparison one-sided, so a false positive here buys
    silence on a real finding.

    THE MATCH MUST BE A WHOLE TOKEN, and a bare `find` is not. `"$20"` occurs inside
    `"≈$200B"`, so a quote reading "market ≈$200B and total $20" marked the $20 approximate
    off the larger number's glyph -- measured end-to-end, `12 + 9.8 = 21.8` against that
    stated $20 flipped from `contradiction` to `confirmation`. The character after the match
    must not continue the number.

    REPEATED OCCURRENCES THAT DISAGREE READ NOTHING. If the same string is printed twice,
    once marked and once not, which one this figure is cannot be decided here -- and `any()`
    resolved that toward `approximate`, i.e. toward silence, on no evidence. Unanimity or no
    bound.
    """
    needle = (raw or "").strip()
    if not needle or not quote:
        return False
    marked: list[bool] = []
    start = quote.find(needle)
    while start != -1:
        end = start + len(needle)
        # The figure must span the WHOLE numeric lexeme here, not merely start it. See
        # `_NUMERIC_LEXEME` for why this is a parse rather than a character denylist.
        digit_at = re.search(r"\d", needle)
        if digit_at is not None:
            lex_start = start + digit_at.start()
            if _numeric_lexeme_end(quote, lex_start) > end:
                start = quote.find(needle, start + 1)
                continue
            marked.append(bool(_QUOTE_APPROX_PREFIX.search(quote[:start])))
        start = quote.find(needle, start + 1)
    if not marked:
        return False
    return all(marked)
    return False


def detect_bound(raw: str, label: str, quote: str = "") -> str | None:
    """Is this figure a floor, a ceiling, an approximation, or an exact claim?

    A quarter of the harm this module can do comes from reading "$200B+" as exactly
    $200B: a computed $212.3B then contradicts a figure it in fact satisfies. Bounds
    arrive two ways and BOTH are common -- as punctuation in the raw string, and as prose
    in the label ("tall buildings existing worldwide (fewer than)").

    Symbols are read from `raw` ONLY. A label may contain a symbol that qualifies
    something else entirely: one deck's label carries ">200m", which is a building-height
    threshold, not a bound on the count the figure holds.

    Every bound makes the comparison ONE-SIDED, which is strictly weaker than the
    two-sided test. So a false positive here can only ever suppress a contradiction, and
    never manufacture one -- which is the direction this whole module errs in.
    """
    raw, label, quote = raw or "", label or "", quote or ""
    votes: set[str] = set()
    if _PLUS_RE.search(raw):
        votes.add("at_least")
    if _LEAD_AT_MOST.search(raw):
        votes.add("at_most")
    if _LEAD_AT_LEAST.search(raw):
        votes.add("at_least")
    if _LEAD_AT_LEAST_WORDS.search(raw):
        votes.add("at_least")
    if _LEAD_AT_MOST_WORDS.search(raw):
        votes.add("at_most")
    if _AT_MOST_WORDS.search(label):
        votes.add("at_most")
    if _AT_LEAST_WORDS.search(label):
        votes.add("at_least")
    if {"at_least", "at_most"} <= votes:
        return None  # contradictory signals -- fall back to the plain two-sided test
    if votes:
        return next(iter(votes))
    # Symbols from `raw` only (the rule stated above); words from either side. The quote is
    # read for symbols too, but under a stricter binding -- see
    # `_approx_symbol_marks_this_figure_in_quote`. Words are NOT read from the quote: a
    # sentence saying "about" attaches to whatever it is about, and unlike a glyph there is
    # no positional test that says which figure that is.
    #
    # A WORD IN `raw` ALSO NEEDS A NUMBER TO QUALIFY. The symbol path requires one -- that
    # hole was closed when `≈` was added, because a bare "≈" (which `ledger.py` accepts,
    # since it skips the scale check on an unparseable magnitude) marked a figure
    # approximate off no number at all. The word path never got the same treatment, so
    # `raw="about"` with `value=100` still read `approximate` and turned a summed 108
    # against a stated 100 from a contradiction into a confirmation.
    #
    # The LABEL is deliberately exempt: a label is prose ABOUT the figure, so "about 100
    # customers" as a label qualifies the figure it describes whether or not the label
    # itself repeats the number. `raw` is supposed to BE the figure's printed string.
    raw_word_binds = bool(_APPROX_WORDS.search(raw) and _NUM_RE.search(raw))
    if (
        _approx_symbol_marks_this_figure(raw)
        or raw_word_binds
        or _APPROX_WORDS.search(label)
        or _approx_symbol_marks_this_figure_in_quote(raw, quote)
    ):
        return "approximate"
    return None


_QUOTE_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)

# Words that are three letters long and say nothing about WHICH quantity the number is:
# currency codes, articles, prepositions, and the hedges that already have their own
# meaning elsewhere in this module. "USD $493K" and "the $80B" passed the bare word test
# while identifying exactly as little as "$493K" does.
_NON_IDENTIFYING_WORDS = frozenset(
    {
        "usd",
        "eur",
        "gbp",
        "ils",
        "nis",
        "chf",
        "jpy",
        "cad",
        "aud",
        "the",
        "and",
        "for",
        "per",
        "was",
        "are",
        "our",
        "its",
        "his",
        "her",
        "their",
        "approx",
        "approximately",
        "about",
        "around",
        "roughly",
        "circa",
        "est",
        "over",
        "under",
        "near",
        "nearly",
        "some",
        "than",
        "with",
        "from",
        "into",
        "onto",
    }
)


def quote_is_identifying(quote: str) -> bool:
    """Does this quote carry a WORD, rather than only figures and punctuation?

    LIVES HERE, NOT IN `ledger.py`, because both need it and the dependency runs one way:
    `ledger.py` already imports from this module, so the predicate cannot sit there
    without a cycle. `ledger.py` warns on it at extraction time; `build()` counts it into
    `reconciliation.json`, which is the first artifact downstream that compose actually
    reads.

    The test is the presence of a word, not a length. A short quote that keeps its row
    label -- "Net revenue $493K" -- is exactly what the schema asks for and is three words
    long; a word-count floor would flag it. Conversely "63.5% | $635K" is two tokens and
    identifies nothing. What separates them is whether anything in the string says what
    the number IS.

    Three letters, so a scale suffix cannot pass for a label: "493K" and "$80B" carry no
    word, "GMV of $493K" carries two.

    AND THE WORD HAS TO SAY SOMETHING. "Any three-letter word" was the first cut and it was
    too weak to mean what it claimed: `USD $493K`, `the $80B` and `about $80B` all passed
    while identifying nothing. A currency code, an article and a hedge are not what the
    number IS. They are subtracted rather than enumerated positively, because the set of
    words that DO identify a quantity is the whole language.
    """
    words = {w.lower() for w in _QUOTE_WORD.findall(quote or "")}
    return bool(words - _NON_IDENTIFYING_WORDS)


def is_visible(quote: str) -> bool:
    """Would a reader of the slide see this number, or is it only in the file?

    Coupled by design to `pptx_transcribe.py`'s output format, which is the only source
    that can produce an invisible figure: a line beginning "series " is chart data read
    from the presentation XML, and a chart plots its series without printing the numbers
    unless data labels are switched on -- measured, zero of 351 points in the corpus .pptx
    have them. Table rows and text frames are on the slide and are visible.

    A PDF figure is always visible: it was read off a rendered page, so if the extractor
    could see it, so can a reader.
    """
    return not (quote or "").strip().startswith("series ")


# Longest-first, so "minutes" is not matched by "min" inside "minimum" and "hrs" beats "hr".
# Word-bounded at the call site for the same reason.
_TIME_UNITS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("seconds", "second", "secs", "sec"), 1.0),
    (("minutes", "minute", "mins", "min"), 60.0),
    (("hours", "hour", "hrs", "hr"), 3600.0),
    (("days", "day"), 86_400.0),
    (("weeks", "week"), 604_800.0),
    (("months", "month", "mos", "mo"), 2_629_800.0),
    (("quarters", "quarter"), 7_889_400.0),
    (("years", "year", "yrs", "yr"), 31_557_600.0),
)


def time_scale(raw: str) -> float | None:
    """Seconds per unit for a duration's written unit, or None if it does not say.

    A duration's magnitude is meaningless without its unit, and the ledger stores the two
    apart: `value` is the number, the unit lives only in the raw string. Dividing one
    duration by another therefore divides bare numbers — which produced a live false
    finding: "120 min / 20 sec = 6.00x — but the deck states 360x". The deck was RIGHT
    (120 minutes over 20 seconds IS 360x) and the tool told a founder otherwise.

    Returning None rather than assuming a unit is deliberate. An unlabelled duration is not
    comparable to a labelled one, and guessing would put the same class of error back with
    a different magnitude.
    """
    low = (raw or "").lower()
    for names, secs in _TIME_UNITS:
        for n in names:
            if re.search(rf"\b{n}\b", low):
                return secs
    return None


def _is_exact_count(fig: Figure) -> bool:
    """An integer count written to the units place is exact -- there is no rounding.

    Load-bearing, and the reason is not obvious. A deck's headcount table summing to 6
    against a stated 5 is a real finding with a gap of exactly 1. Give each of its seven
    integer operands even the legacy +/-0.5 and propagation opens a window of 3.5 that
    swallows it whole. "4 engineers" is not 4 to one significant figure; it is 4.

    Restricted to the units place on purpose: "200 customers" IS rounded, and gets the
    ordinary relative treatment.
    """
    if fig.unit_kind != COUNT or not float(fig.value).is_integer():
        return False
    p = _precision(fig.raw)
    return bool(p and p[0] == 0.5 and _raw_scale(fig.raw) == 1.0)


def figure_tolerance(fig: Figure) -> float:
    """How far a value may differ from this figure before the gap is real -- IN VALUE SPACE.

    The comparison runs on values, so the tolerance must too. `implied_tolerance` alone
    cannot do this: it sees "(19,391)" and returns 0.5 while the value being compared is
    19,391,000. So take the figure's precision as a RATIO in its own space and apply that
    ratio to its value.

    Floored at the written precision so this can only relax. That floor is not decorative:
    133 corpus figures are single-digit-mantissa ("$8M"), where an uncapped 5% would be
    TIGHTER than the shipped behaviour and would manufacture new false contradictions out
    of a change whose whole purpose is to remove them.
    """
    if fig.value == 0 or _is_exact_count(fig):
        return 0.0
    p = _precision(fig.raw)
    rel = min(p[0] / p[1], CAP) if p and p[1] else CAP
    # abs(): 32 corpus figures are negative, including an entire cashflow table. A
    # negative tolerance gives the disjointness test a negative-width window and turns
    # very nearly every comparison into a contradiction.
    tol = max(implied_tolerance(fig.raw), abs(fig.value) * rel)
    if fig.bound == "approximate":
        lo, hi = fig.span()
        tol = max(tol, APPROX_WIDENING * max(abs(lo), abs(hi)))
    return tol


def operand_tolerance(operator: str, figs: list[Figure]) -> float:
    """Imprecision the operands contribute to the computed side -- for SUMS only.

    The split is a decision with evidence behind it, not an oversight:

      sum / difference   absolute errors ADD, and the total stays small relative to the
                         result. A cashflow table of eight components each rounded to the
                         nearest thousand carries +/-4,000 against a 19,391,000 total --
                         which is exactly the gap that was being reported as a
                         contradiction, and no per-figure tolerance can absorb it,
                         because the discrepancy is an accumulation across eight figures.

      product / ratio    relative errors COMPOUND, and honest propagation swallows real
      increase_by        findings. Propagated through "$100k/month increased by 20%" it
                         gives 109,250-131,250, which contains the deck's stated $115k --
                         destroying the exact finding this module was written to catch.
                         For multiplicative relations the stated figure's own precision
                         is the only yardstick.
    """
    return sum(figure_tolerance(f) for f in figs) if operator in ("sum", "difference") else 0.0


def _norm(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _range_kwargs(raw: str) -> dict[str, Any]:
    """`lo`/`hi` for a raw string that states a range, or nothing for a point value."""
    rng = parse_range(raw)
    return {"lo": rng[0], "hi": rng[1]} if rng else {}


def load_figures(ledger: dict[str, Any]) -> list[Figure]:
    out: list[Figure] = []
    for raw in ledger.get("figures", []):
        v = _norm(raw.get("value"))
        if v is None:
            continue
        out.append(
            Figure(
                id=str(raw.get("id", "")),
                value=v,
                raw=str(raw.get("raw", "")),
                unit_kind=str(raw.get("unit_kind", "")),
                label=str(raw.get("label", "")),
                slide=raw.get("slide"),
                quote=str(raw.get("quote", "")),
                currency=raw.get("currency"),
                period=raw.get("period"),
                # Phase 2 will have the extraction model report this directly, validated
                # against the verbatim quote; until those ledgers exist, and permanently
                # as the fallback for a figure the model says nothing about, it is read
                # off the raw string and the label.
                bound=detect_bound(str(raw.get("raw", "")), str(raw.get("label", "")), str(raw.get("quote", ""))),
                visible=is_visible(str(raw.get("quote", ""))),
                **_range_kwargs(str(raw.get("raw", ""))),
            )
        )
    return out


# The marker is not always last: "runway secured — low bound (months)" carries a unit
# after it, and an end-anchored pattern silently failed to strip that whole class --
# leaving the twins unmerged and the duplicate finding in the report.
_BOUND_RE = re.compile(
    r"\s*(?:[(\[,—-]\s*)?(?:at\s+the\s+)?(?:low|high|lower|upper)(?:\s*(?:end|bound|side))?\s*[)\]]?"
    r"(?P<tail>\s*\([^)]*\))?\s*$",
    re.I,
)


_LOW_RE = re.compile(r"\b(low|lower)(\s*(end|bound|side))?\b", re.I)
_HIGH_RE = re.compile(r"\b(high|higher|upper)(\s*(end|bound|side))?\b", re.I)


def _endpoint_marker(label: str) -> str | None:
    """Which end of a range this figure claims to be, from its own label."""
    lo, hi = bool(_LOW_RE.search(label or "")), bool(_HIGH_RE.search(label or ""))
    return "low" if lo and not hi else "high" if hi and not lo else None


def _strip_bound(label: str) -> str:
    """Drop a trailing low/high marker: "raise for X (low end)" -> "raise for X"."""
    # Keep a trailing unit parenthetical so "(months)" is not lost with the marker.
    return _BOUND_RE.sub(lambda m: (" " + m.group("tail").strip()) if m.group("tail") else "", label or "").strip(
        " ,—-"
    )


def merge_range_twins(figures: list[Figure]) -> tuple[list[Figure], dict[str, str]]:
    """Collapse a range extracted as two entries back into one interval figure.

    The extractor emits "$150-250K raise (low end)" and "(high end)" as SEPARATE ledger
    rows -- 10 such groups on one deck, 36 on another. Downstream the model then proposes
    the same relation once per endpoint, and the report shows one finding twice with two
    different answers ("1-3% x $1M = 10,000" and "= 30,000").

    Merging at the source is the fix; deduping the relations afterwards would only hide
    it, and would still leave each relation comparing against half a range.

    Deliberately narrow. Two rows merge only when the raw string is genuinely a range,
    they sit on the same slide, and their labels are identical once a low/high marker is
    removed. Without that last condition "1" on slide 9 -- landing pages for the FREE
    plan and for the Standard plan, two different facts that share a value -- would be
    silently fused.
    """
    groups: dict[tuple[str, Any, str], list[Figure]] = {}
    for f in figures:
        groups.setdefault((f.raw, f.slide, _strip_bound(f.label)), []).append(f)

    kept: list[Figure] = []
    alias: dict[str, str] = {}
    for (raw, _slide, base_label), members in groups.items():
        rng = parse_range(raw)
        if len(members) < 2 or rng is None:
            kept.extend(members)
            continue
        head = members[0]
        head.lo, head.hi = rng
        head.value = rng[0]
        head.label = base_label or head.label
        kept.append(head)
        for dup in members[1:]:
            alias[dup.id] = head.id

    # SECOND PASS: endpoints written as two SEPARATE figures with different raw strings.
    # The pass above keys on an identical raw ("$150-250K" appearing twice), so it cannot
    # see "$1k (low end)" and "$10k (high end)" -- two rows, two raws, one range. Measured
    # consequence: the deck stated "$1k - $10k", the ledger kept only $1k, and a computed
    # 10,000 that sits INSIDE the stated range was reported to the founder as contradicting
    # it. The domain expert caught it and declined to give the finding a verdict at all.
    #
    # Deliberately narrow, for the same reason the first pass is: merge only when the two
    # sit on one slide, their labels are identical once the marker is stripped, and those
    # labels explicitly claim OPPOSITE ends. Without that last condition two unrelated
    # figures that happen to share a label would be fused into a fictitious range.
    by_label: dict[tuple[Any, str], list[Figure]] = {}
    for f in kept:
        if f.lo is None and _endpoint_marker(f.label):
            by_label.setdefault((f.slide, _strip_bound(f.label)), []).append(f)
    merged: set[str] = set()
    for members2 in by_label.values():
        marks = {_endpoint_marker(f.label): f for f in members2}
        if len(members2) != 2 or set(marks) != {"low", "high"}:
            continue
        lo_f, hi_f = marks["low"], marks["high"]
        if lo_f.value == hi_f.value or lo_f.unit_kind != hi_f.unit_kind:
            continue
        lo_f.lo, lo_f.hi = min(lo_f.value, hi_f.value), max(lo_f.value, hi_f.value)
        lo_f.value = lo_f.lo
        lo_f.raw = f"{lo_f.raw}-{hi_f.raw}"
        lo_f.label = _strip_bound(lo_f.label) or lo_f.label
        alias[hi_f.id] = lo_f.id
        merged.add(hi_f.id)
    return [f for f in kept if f.id not in merged], alias


def verify(figures: list[Figure], transcript: str, quote_in_doc: Any) -> None:
    """Gate on the quote, and classify ATTRIBUTION separately.

    These are different questions and conflating them is the trap. The gate asks "was
    this QUOTE invented?" -- not whether the VALUE is right, which it cannot see at all.
    Attribution asks "does the label belong to this number?" --
    which the gate cannot see either, because roughly half of all figures take their label from
    slide LAYOUT (a table column, a header above) rather than from the quoted string.
    Measured on real extractions: layout reading was correct everywhere it could be
    checked, but one case was unverifiable from any text source at all.

    A layout-attributed figure is NOT dropped -- that would discard most table data,
    which is where F5's operands live. It is marked, and the mark propagates to every
    relation built on it.
    """
    for f in figures:
        if not f.quote:
            f.drop_reason = "no quote"
            continue
        if not quote_in_doc(f.quote, transcript)[0]:
            f.drop_reason = "quote not found in the second read"
            continue
        f.verified = True
        label_words = {w for w in f.label.lower().split() if len(w) > 3}
        quote_l = f.quote.lower()
        hits = sum(1 for w in label_words if w in quote_l)
        f.attribution = (
            "quote_carries_label" if label_words and hits >= max(1, len(label_words) // 2) else "layout_attributed"
        )


MATERIALITY_PCT = 0.02
"""Relative gap below which a PERCENTAGE disagreement is not worth a founder's attention.

Tolerance and materiality are different questions, and the engine only had the first.
Tolerance asks "might these be the same number?"; materiality asks "even if they differ,
does anyone care?" The expert's scope rule names the second explicitly -- findings must be
"material, and not open to interpretations" -- so it gets its own mechanism rather than a
quietly widened tolerance.

A CHOICE, and one that cannot be validated from the data that motivated it: every threshold
between 1.42% and 14.28% behaves identically on the corpus. What IS measured is that no
expert-confirmed real finding comes close -- the smallest percent-space relative gap on a
real finding is 43.9%, twenty times this floor.

Scoped to percentages on purpose. A 2% gap on a cash or headcount figure can matter, and
there is no evidence here for a general materiality floor.
"""

GROWTH_CONVENTION_OFFSET = 100.0
"""A deck saying a figure "grew 22%" and a tool computing the multiple (122%) differ by
exactly this, and by nothing else.

Measured three times in one corpus at offsets of 100.0, 99.7 and 99.9 points -- the
definitional gap between a growth rate and a multiple, not a coincidence.
"""


_UNIT_NOUNS = {
    COUNT: "unit",
    MONEY: "dollar",
    PERCENT: "percentage point",
    MULTIPLE: "multiple",
    DURATION: "period",
    DATE: "date",
}


def _denominator_noun(den: Figure) -> str:
    """What to call the denominator of a rate, in words a founder recognises.

    A DURATION denominator is named by its time unit, not its label. "$4M over 3 years"
    is $1.33M per YEAR; naming it by the label gives "per payback period high end", which
    is both unreadable and wrong about what the rate measures.

    Everything else takes the deck's own label, unaltered. An earlier version stripped a
    trailing "s" to singularise it, which is not a rule English obeys: measured on the
    corpus it turned "businesses in the United States" into "businesses in the United
    State". A slightly-off plural ("per paying seats") is a blemish; a mangled noun is an
    error, and the two are not worth trading.
    """
    if den.unit_kind == DURATION:
        match = _NUM_RE.search(den.raw or "")
        tail = (den.raw or "")[match.end() :].strip().lower() if match else ""
        for unit in ("month", "year", "quarter", "week", "day"):
            if tail.startswith(unit):
                return unit
        return "period"
    label = (den.label or "").strip()
    return label if label else _UNIT_NOUNS.get(den.unit_kind, "unit")


MAX_CONVENTION_WIDENING = GROWTH_CONVENTION_OFFSET / 4
"""Ceiling on how far the growth-convention band may be widened. A SEMANTIC bound.

The rule claims two figures "differ ONLY by the convention" -- that they sit 100 points
apart and nowhere else. That claim is only meaningful while the band is small relative to
100. The per-operand CAP alone does not deliver this: it bounds each operand at 5%, but the
widening is `mid x sum(rel)`, so it grows with the multiple and reaches 100 at a 10x growth
figure. At that width the rule stops testing the convention and starts suppressing anything
in the neighbourhood -- and tells the founder the two numbers are the same fact, which they
visibly are not.

A quarter of the offset keeps the test recognisably about the convention. It is a choice,
and it binds only in the coarse-operand regime: the case that motivated this whole band
widens by 3.3, nowhere near it.
"""


_REDUCTION_GLYPH = re.compile(r"[↓▼]")
_REDUCTION_WORDS = re.compile(r"\b(reduction|decrease|savings)\b", re.I)


def _is_reduction(exp: Figure) -> bool:
    """Does this stated percent describe a DECREASE rather than a share?

    "↓75%" and a computed 15% share are complements, not disagreeing measurements of one
    thing, and both carry `unit_kind: percent` so the unit algebra waves them through.

    The glyph is the primary signal because it is unambiguous. The three words are chosen
    for having no competing sense -- unlike `target` and `over`, both of which produced
    false bounds in this file today by matching a different meaning of the same string.
    `decline` is deliberately absent ("declined the offer").
    """
    return bool(_REDUCTION_GLYPH.search(exp.raw or "") or _REDUCTION_WORDS.search(exp.label or ""))


def _is_self_comparison(r: Relation, operands: list[Figure]) -> bool:
    """Is this a cross-slide consistency check that came back clean?

    Two operands holding the SAME quantity — same value within tolerance, same unit — with
    no stated figure to test against. The model builds these deliberately, pairing "150+
    accounts" on slide 2 against "150+ accounts" on slide 9 to see whether the deck agrees
    with itself. A DISAGREEMENT there surfaces on its own merits and must not be caught
    here, which is why the equality test is the gate.

    COVERS `ratio` AND `difference`, and the second was a gap I created. This started as
    `ratio`-only, on the argument that a ratio of two genuinely different quantities
    landing on 100% — breakeven, say — might be worth reading. That argument does not
    transfer, and scoping to it let a real deck ship

        $12.5 trillion − $12.5 trillion = 0

    to a founder: the same global market size stated on slides 12 and 24, subtracted from
    itself. `X − X = 0` is meaningless whatever the quantities are, so `difference` needs
    no equivalent escape hatch. The `ratio` carve-out stays, and is pinned by a test.

    Requires exactly two operands, no `expected_id`, matching `unit_kind`, and equality
    within the operands' own tolerance.
    """
    if r.operator not in ("ratio", "difference") or r.expected_id or len(operands) != 2:
        return False
    a, b = operands
    if a.unit_kind != b.unit_kind or r.computed is None:
        return False
    if r.operator == "ratio" and b.value == 0:
        return False
    # TEST THE RESULT, NOT THE OPERANDS. Comparing operand values missed the case that
    # matters most: a deck stating "9 million per month" on one slide and "108 million per
    # annum" on another. Those are the same quantity, the engine's OWN period conversion
    # proves it by computing exactly 1.0 — and 108,000,000 vs 9,000,000 are nowhere near
    # equal, so an operand test waves it through. It shipped as
    #
    #     108 million ÷ 9 million = 100.0%
    #
    # which reads as a arithmetic failure to anyone who divides it in their head.
    #
    # The result IS the general form: a ratio of one, or a difference of zero, means the
    # two sides are the same quantity however they were expressed. Operand equality was
    # only ever a proxy for it, and a lossy one.
    identity = 1.0 if r.operator == "ratio" else 0.0
    tol = max(figure_tolerance(a), figure_tolerance(b))
    scale = abs(a.value) or 1.0
    return abs(r.computed - identity) <= (tol / scale if r.operator == "ratio" else tol)


def _convention_tolerance(exp: Figure, mid: float, operator: str, operands: list[Figure]) -> float:
    """How close to the convention point counts as "only the convention differs".

    A SUPPRESSION band, and deliberately not the same number as the contradiction test's.
    The two sit on opposite sides of the governing asymmetry: asserting a false
    contradiction is loud and damaging, so the disjointness test is kept tight; withdrawing
    one is silent, so the suppressor should err toward withdrawing. Handing the suppressor
    the assertion test's tolerance inverted that, and is what let a false finding through:

        $493k / $94k = 5.24x  — but the deck states 425% (GP growth)

    425% growth IS 5.25x. The offset was 0.532 percentage points against a band of 0.5 --
    it missed by 0.032. The band was the STATED figure's precision alone, because
    `operand_tolerance` contributes nothing for multiplicative operators (deliberately, and
    correctly, for disjointness -- see its docstring). But the computed side is built from
    rounded operands: $493k and $94k carry 0.101% and 0.532%, and a ratio's relative errors
    add, so the honest excursion is +/-3.3 points. A fixed 0.5 band against a 3.3 spread
    could only ever miss, and it misses MORE as multiples grow and operands coarsen.

    THE CAP IS LOAD-BEARING, not tidiness. `figure_tolerance` is a `max()` of the
    significant-figure floor and the relative rule, so the FLOOR ESCAPES `CAP`: "$1M"
    carries 50% relative error, not 5%. Uncapped, this band reached ~300 points and
    swallowed real disagreements of 80 and even 150 points -- while telling the founder the
    two figures were "the same fact, 100 points apart by convention", which the numbers on
    screen visibly contradict. Capping each operand's contribution at CAP keeps the live
    case suppressed (band 3.8 vs offset 0.53) and returns every one of those to a
    contradiction (band 50.5 vs offsets 80 and 150).

    Built from `figure_tolerance(exp)` rather than the caller's `tol` so that a future
    multiplicative branch in `operand_tolerance` cannot double-count into this band.

    KNOWN HOLE, recorded rather than fixed: a DECLINE ("fell 40%") is stored as a positive
    percent throughout the corpus, so `stated + 100` is the wrong convention point for it
    and no band width helps. No committed relation trips it today.
    """
    band = figure_tolerance(exp)
    # `ratio` is the only operator that yields a dimensionless computed side, which
    # `_growth_convention` requires -- `product` and `increase_by` carry an operand's unit
    # through and are rejected before tolerance is consulted. Restricted rather than
    # written speculatively: the symmetric form below is WRONG for `increase_by`, whose
    # percentage operand contributes over (100 + value), not over value.
    if operator == "ratio":
        widening = abs(mid) * sum(min(figure_tolerance(f) / abs(f.value), CAP) for f in operands if f.value)
        band += min(widening, MAX_CONVENTION_WIDENING)
    return band


def _growth_convention(computed: float, exp: Figure, tol: float, computed_unit: str | None) -> bool:
    """Do these two differ ONLY by the growth-rate / multiple convention?

    Guarded to DIMENSIONLESS computed sides -- ratios and increases scaled into percent
    space. The guard is load-bearing rather than tidy: a SUM of percents can land near
    stated+100 without being a growth/multiple pair at all, and the corpus contains exactly
    such a finding ("20% + 0% = 20" against a stated "100%") that the expert graded REAL.
    Without the restriction this rule would be defined over cases where it means nothing,
    and would delete a true finding.
    """
    if computed_unit != "dimensionless" or exp.unit_kind != PERCENT:
        return False
    return abs(computed - (exp.value + GROWTH_CONVENTION_OFFSET)) <= tol


def _sign_convention(computed: float, exp: Figure, tol: float) -> bool:
    """Same magnitude, opposite sign -- a reporting convention, not a disagreement.

    Measured: fires on 5 findings in the corpus, all on one deck, none expert-real. The
    expert judged sign differences not-a-problem on two separate passes, including budget
    variance rows initially graded real and corrected on closer reading.

    KNOWN RESIDUAL RISK: a deck reporting a gain where it has a loss is material, and this
    rule hides it. No such case exists in the corpus. If one appears it belongs to the
    interpretation gate, which can weigh context, not to a deterministic rule that cannot.
    """
    if computed == 0 or exp.value == 0 or (computed > 0) == (exp.value > 0):
        return False
    return abs(abs(computed) - abs(exp.value)) <= tol


def _immaterial_percent(computed: float, exp: Figure) -> bool:
    """A percentage gap too small to act on. See MATERIALITY_PCT."""
    if exp.unit_kind != PERCENT or exp.value == 0:
        return False
    return abs(computed - exp.value) / abs(exp.value) < MATERIALITY_PCT


def _stated(exp: Figure) -> str:
    """Render the stated side in the SAME number space as the computed side.

    The computed side always prints fully expanded, while the stated side printed from
    `.raw`. On a cashflow table denominated in thousands that produced

        (856) + (1,679) + ... = -19,393,000  — but the deck states (19,391)

    a founder-visible line that looks off by a factor of a thousand describing figures
    that disagree by 0.01%. It is also what made this look like a scale-extraction bug for
    two rounds of analysis when the ledger had been right all along.
    """
    p = _precision(exp.raw)
    magnitude = (p[1] if p else 0.0) * _raw_scale(exp.raw)
    if magnitude and abs(exp.value) / magnitude >= 9.5:
        return f"{exp.raw} (= {exp.value:,.0f})"
    return exp.raw


def _scale_divergent(computed: float, stated: float) -> bool:
    """Do these two differ by very nearly an exact power of a thousand?

    Deliberately narrow. Exponent 0 is excluded or a near-exact agreement would be
    refused rather than confirmed. Exponents 1 and 2 are excluded because a genuine 10x
    or 100x discrepancy is far more likely a real error than a units convention -- and
    that exclusion is pinned by a live case: one deck's "1-3% x $1M per month = 10,000"
    against a stated "$1k" has a ratio of exactly 10 and is a true finding.
    """
    a, b = abs(computed), abs(stated)
    if a == 0 or b == 0:
        return False
    ratio = max(a, b) / min(a, b)
    return any(abs(ratio / 10**n - 1.0) < 0.01 for n in (3, 6, 9))


def compute(rel_spec: dict[str, Any], by_id: dict[str, Figure]) -> Relation:
    """Compute one proposed relation, or refuse it.

    Refusals are as important as results. A relation this function cannot justify must
    not reach a founder at reduced confidence -- it must not reach them at all.
    """
    alias: dict[str, str] = rel_spec.get("_alias") or {}
    ops = [alias.get(str(x), str(x)) for x in rel_spec.get("operands", [])]
    r = Relation(
        kind=str(rel_spec.get("kind", "derived_ratio")), operands=ops, operator=str(rel_spec.get("operator", ""))
    )

    figs = [by_id.get(o) for o in ops]
    missing = [o for o, f in zip(ops, figs, strict=True) if f is None]
    if missing:
        r.dropped, r.reasons = True, [f"unknown operand id: {', '.join(missing)}"]
        return r
    real = [f for f in figs if f is not None]

    unverified = [f.id for f in real if not f.verified]
    if unverified:
        # Not "reduced confidence" -- dropped. A relation resting on a figure we could
        # not find in the second read is unfounded, not weak.
        r.dropped = True
        r.reasons = [f"operand {i} failed verification" for i in unverified]
        return r

    # A DATE IS NOT A MAGNITUDE, and every operator computed one anyway. The unit algebra
    # below never consulted `unit_kind` for dates, so a year fell through to the numeric
    # branches on its face value: 2030 x 2025 gave 4,110,750 carrying a `derived` verdict,
    # and "2030 increased by 20% = 2,436" rendered as a founder-facing line.
    #
    # REFUSED, not converted -- including `difference`, which is the one date relation with
    # an obvious meaning. Computing it is still unsafe: the result carries `unit_kind: date`,
    # `time_scale` normalizes time units in the `ratio` branch ONLY, and the comparison gate
    # matches a bare duration against ANY stated DURATION regardless of the unit written on
    # the slide. So "10 years - 5 years = 5" against a stated "60 months" would return a
    # CONTRADICTION where today it returns incomparable, and a false contradiction is the
    # worst thing this module can emit. Generic duration normalization has to land first,
    # as its own change; until then a date difference computes nothing, which is safe.
    #
    # THE STATED SIDE IS INCLUDED. Otherwise a count sum gets compared against a year and
    # that year's tolerance decides it -- and a quarter-prefixed year's tolerance is 101.25,
    # because `_precision` reads the leading token and so takes "Q4 2025" to be precise to
    # half a unit of FOUR. Every comparison against it would confirm. Refusing every
    # participant is what makes that vacuous tolerance unreachable rather than merely
    # unlikely, and is why there is no separate date-tolerance rule here.
    exp_ref = rel_spec.get("expected_id")
    exp_fig = by_id.get(str(alias.get(str(exp_ref), exp_ref))) if exp_ref else None
    dated = [f.id for f in [*real, *([exp_fig] if exp_fig is not None else [])] if f.unit_kind == DATE]
    if dated:
        r.dropped, r.reasons = True, [f"{', '.join(dated)} is a date, and date arithmetic is refused"]
        return r

    # ---- unit algebra -------------------------------------------------------
    # Two defects this replaced, both found by computing REAL model proposals rather
    # than hand-picked ones:
    #
    #  1. `product` multiplied a percent as a raw number: 100,000 x 20% gave 2,000,000
    #     instead of 20,000. Every money x percent relation was out by 100x -- and those
    #     are precisely the "check this against the figure the deck states" relations, so
    #     the tool would have reported its own arithmetic error AS an inconsistency
    #     finding. A 100x-wrong number presented as a discovered contradiction is the
    #     worst output this feature could produce.
    #
    #  2. Refusals were far too broad. money/count was rejected as a "unit mismatch",
    #     which throws away gross-profit-per-customer, ARPA and cost-per-contract -- core
    #     metrics, and 5 of deck-C's 9 refusals. money/duration and per-month vs per-year
    #     were likewise refused instead of converted.
    #
    # Refuse only what is genuinely meaningless; convert what is merely inconvenient.
    PERIODS = {"month": 1.0, "year": 12.0, "quarter": 3.0, "week": 1 / 4.345, "day": 1 / 30.44}

    def as_fraction(f: Figure) -> float:
        """A percent participates in arithmetic as a fraction, never as its face value."""
        return f.value / 100.0 if f.unit_kind == PERCENT else f.value

    def as_fraction_v(v: float, f: Figure) -> float:
        return v / 100.0 if f.unit_kind == PERCENT else v

    def to_month(f: Figure) -> float | None:
        return PERIODS.get(f.period) if f.period else None

    if r.operator == "ratio":
        if len(real) != 2:
            r.dropped, r.reasons = True, ["ratio needs exactly 2 operands"]
            return r
        num, den = real
        if den.value == 0:
            r.dropped, r.reasons = True, ["division by zero"]
            return r
        if num.unit_kind == MONEY and den.unit_kind == MONEY and num.currency != den.currency:
            r.dropped, r.reasons = True, [f"currency mismatch: {num.currency} / {den.currency}"]
            return r

        # A percent or a multiple is a SCALAR, not a denominator you can divide by to
        # get a rate: "$4,600 per percent" is not a quantity. Refuse those, narrowly --
        # the first fix here swung from over-refusing (money/count) to refusing nothing
        # at all, which let this class straight through.
        # percent/percent and multiple/multiple stay legal: comparing two rates is fine.
        if den.unit_kind in (PERCENT, MULTIPLE) and num.unit_kind != den.unit_kind:
            r.dropped, r.reasons = (
                True,
                [f"{den.unit_kind} is a scalar, not a denominator: {num.unit_kind} / {den.unit_kind} has no unit"],
            )
            return r

        # Two durations divide only after they are in the SAME time unit. Their magnitudes
        # sit in `value` while their units sit in the raw string, so a bare division is a
        # category error, not an approximation — see `time_scale`.
        dur_factor = 1.0
        if num.unit_kind == DURATION and den.unit_kind == DURATION:
            ns, ds = time_scale(num.raw), time_scale(den.raw)
            if ns is None or ds is None:
                r.dropped, r.reasons = (
                    True,
                    [f"cannot compare durations without units on both sides: {num.raw!r} / {den.raw!r}"],
                )
                return r
            if ns != ds:
                dur_factor = ns / ds
                r.reasons.append(f"converted {num.raw} and {den.raw} to a common time unit")

        # INTERVAL arithmetic. A quarter of real figures are ranges, and a ratio of two
        # ranges is a range: $200–$260 over $6–$12 is 16.7x to 43.3x, not one number.
        # This is what makes the contradiction test honest -- the deck claiming "20–40x"
        # is CONSISTENT with that interval, and pairing single endpoints reported it as
        # a contradiction twice, with two different answers.
        n_lo, n_hi = (as_fraction_v(v, num) for v in num.span())
        d_lo, d_hi = (as_fraction_v(v, den) for v in den.span())
        nv, dv = as_fraction(num), as_fraction(den)
        nm, dm = to_month(num), to_month(den)
        if nm and dm and nm != dm:
            # per-month vs per-year is a conversion, not an error. Normalise to the
            # denominator's period and say so, rather than refusing a real comparison.
            nv = nv * (dm / nm)
            r.reasons.append(f"converted {num.raw} from per-{num.period} to per-{den.period}")
        r.computed = (nv / dv) * dur_factor
        if d_lo > 0 and d_hi > 0:
            r.span_lo, r.span_hi = (n_lo / d_hi) * dur_factor, (n_hi / d_lo) * dur_factor

        if den.period and not num.period and num.unit_kind == den.unit_kind:
            r.rendered = f"{num.raw} ÷ {den.raw} = {r.computed:,.1f} {den.period}s"
            r.computed_unit = f"duration:{den.period}"
        elif num.unit_kind != den.unit_kind:
            # A cross-unit ratio is a RATE, and the unit is the pair. $ / customers is
            # dollars per customer -- meaningful, and previously refused outright.
            #
            # Name the denominator in the DECK'S words, not ours. `unit_kind` is an
            # internal enum, and interpolating it produced "$493K / 120 = 4,108.33 per
            # count" -- a founder-facing line whose unit is a token from our own
            # vocabulary. The label is what the deck called the figure ("paying seats"),
            # which is both correct and readable; the enum stays as the fallback for a
            # figure with no label, humanized rather than raw.
            r.rendered = f"{num.raw} ÷ {den.raw} = {r.computed:,.2f} per {_denominator_noun(den)}"
            r.computed_unit = f"{num.unit_kind}_per_{den.unit_kind}"
        elif r.computed >= 2:
            # 240% reads as a percentage of something; 2.4x reads as the multiple it is.
            r.rendered = f"{num.raw} ÷ {den.raw} = {r.computed:,.2f}x"
            r.computed_unit = "dimensionless"
        else:
            r.rendered = f"{num.raw} ÷ {den.raw} = {r.computed * 100:.1f}%"
            r.computed_unit = "dimensionless"

    elif r.operator == "product":
        acc = 1.0
        for f in real:
            acc *= as_fraction(f)
        r.computed, r.rendered = acc, " × ".join(f.raw for f in real) + f" = {acc:,.2f}".rstrip("0").rstrip(".")
        kinds = [f.unit_kind for f in real if f.unit_kind != PERCENT]
        pers = [f.period for f in real if f.period]
        r.computed_unit = (kinds[0] if len(kinds) == 1 else "mixed") + (f":{pers[0]}" if len(pers) == 1 else "")
    elif r.operator == "sum":
        sum_kinds = {f.unit_kind for f in real}
        if len(sum_kinds) > 1:
            r.dropped, r.reasons = True, [f"cannot sum across units: {sorted(sum_kinds)}"]
            return r
        periods = {f.period for f in real if f.period}
        if len(periods) > 1:
            r.dropped, r.reasons = True, [f"cannot sum across periods: {sorted(periods)}"]
            return r
        # Summing percents keeps them in percent space: 20% + 0% is 20%, not 0.2. The
        # fraction conversion exists for percent-as-MULTIPLIER (product), and applying it
        # here put the result in a different space from the figure it gets compared to.
        all_pct = all(f.unit_kind == PERCENT for f in real)
        acc = sum(f.value if all_pct else as_fraction(f) for f in real)
        r.computed, r.rendered = acc, " + ".join(f.raw for f in real) + f" = {acc:,.2f}".rstrip("0").rstrip(".")
        pers2 = {f.period for f in real if f.period}
        r.computed_unit = real[0].unit_kind + (f":{pers2.pop()}" if len(pers2) == 1 else "")
    elif r.operator == "increase_by":
        # The vocabulary had no way to say "grew BY 20%", so the model reached for
        # `product` -- which means "20% OF" -- and a $100k base became $20k instead of
        # $120k, then got reported as contradicting the deck's stated $115k. The missing
        # word created a false finding.
        if len(real) != 2:
            r.dropped, r.reasons = True, ["increase_by needs a base and a percentage"]
            return r
        base, pct = real
        if pct.unit_kind != PERCENT:
            r.dropped, r.reasons = True, [f"increase_by needs a percent, got {pct.unit_kind}"]
            return r
        b_lo, b_hi = base.span()
        p_lo, p_hi = pct.span()
        r.computed = base.value * (1 + pct.value / 100.0)
        r.span_lo, r.span_hi = b_lo * (1 + p_lo / 100.0), b_hi * (1 + p_hi / 100.0)
        r.computed_unit = base.unit_kind + (f":{base.period}" if base.period else "")
        r.rendered = f"{base.raw} increased by {pct.raw} = {r.computed:,.0f}"
    elif r.operator == "difference":
        if len(real) != 2:
            r.dropped, r.reasons = True, ["difference needs exactly 2 operands"]
            return r
        a, b = real
        if a.unit_kind != b.unit_kind:
            r.dropped, r.reasons = True, [f"cannot subtract {b.unit_kind} from {a.unit_kind}"]
            return r
        # Percent stays in percent space, exactly as in `sum` above. The fraction
        # conversion exists for percent-as-MULTIPLIER; applying it here computed
        # "29% - 7% = 0.22" and then compared 0.22 against a stated 22%, reporting a deck
        # that agrees with itself as contradicting itself. The guard was added to `sum`
        # when this was first found and `difference` was missed -- the same bug, one
        # branch over.
        # A BOUNDED OPERAND MAKES THE DIFFERENCE BOUNDED, not exact. A real deck stated
        # "Over 30%" against a "50%" and this rendered "50% - Over 30% = 20", which is
        # wrong in a way a founder cannot see: subtracting a floor gives a CEILING, so the
        # honest answer is "at most 20". Refusing is the safe direction and costs almost
        # nothing -- a difference against an open-ended figure is rarely the finding, and
        # asserting a precise number from an imprecise input is how this module does harm.
        bounded = [f for f in (a, b) if f.bound in ("at_least", "at_most")]
        if bounded:
            r.dropped, r.reasons = (
                True,
                [f"cannot subtract an open-ended figure ({bounded[0].raw}) and call the result exact"],
            )
            return r
        both_pct = a.unit_kind == PERCENT and b.unit_kind == PERCENT
        r.computed = (a.value - b.value) if both_pct else (as_fraction(a) - as_fraction(b))
        r.computed_unit = a.unit_kind + (f":{a.period}" if a.period else "")
        r.rendered = f"{a.raw} − {b.raw} = {r.computed:,.2f}".rstrip("0").rstrip(".")
    else:
        r.dropped, r.reasons = True, [f"unsupported operator: {r.operator!r}"]
        return r

    # ---- classification: what KIND of thing did we just compute? ----------------
    # This is the selection rule, and the point of it is that "contradiction" is a fact
    # a machine can establish, while "important" is not. A relation that disagrees with a
    # figure the deck ITSELF states is a finding, no judgement required. Everything else
    # is either an opinion (derived), a non-event (confirmation), or noise (restatement).
    exp_id = rel_spec.get("expected_id")
    exp_id = alias.get(str(exp_id), exp_id) if exp_id else exp_id
    if exp_id and (exp := by_id.get(str(exp_id))) is not None and not exp.verified:
        # THE STATED SIDE MUST CLEAR THE SAME GATE THE OPERANDS DO. Operands are dropped
        # hard when the second read cannot find them (above); the expected figure was
        # not checked at all, so a contradiction could read
        #
        #     $100k / 4 = 25,000 per customer  — but the deck states $50k (ACV)
        #
        # where "$50k" is a figure the second read never found. Reproduced. That tells a
        # founder their numbers disagree with something the deck may not say, and it makes
        # the report's own promise -- that a figure's wording was "checked back against
        # your deck" -- false in the one direction that matters.
        #
        # Refusing the binding leaves the relation as a derived reading rather than a
        # finding: it suppresses, never manufactures, which is what lets this be a silent
        # guard rather than a new failure mode.
        r.reasons.append("the stated figure was not corroborated by the second read")
        exp_id = None
    if exp_id and (exp := by_id.get(str(exp_id))) is not None and r.computed is not None:
        r.expected_id, r.expected_value = exp.id, exp.value
        # BRING BOTH SIDES INTO THE SAME UNIT BEFORE COMPARING, or refuse to compare.
        # Skipping this produced false contradictions on real decks -- "18.40x ... but the
        # deck states 1,740%" (a multiple against a percent: 18.4 vs 1740), and
        # "20% + 0% = 0.2 ... but the deck states 100%" (my own fraction normalisation
        # against a raw percent). A false contradiction is the worst thing this feature
        # can emit: it tells a founder their deck disagrees with itself when it does not.
        exp_unit = exp.unit_kind + (f":{exp.period}" if exp.period else "")
        cu = r.computed_unit or ""
        comparable: float | None = None
        if cu == exp_unit or (cu.startswith(exp.unit_kind) and not exp.period):
            comparable = r.computed
        elif cu == "dimensionless" and exp.unit_kind == PERCENT and _is_reduction(exp):
            # A REDUCTION AND A REMAINING RATIO ARE NOT THE SAME QUANTITY. They are
            # complements -- reduction% = 100 - remaining% -- and both wear the `percent`
            # unit, so nothing above catches it. A real deck stated "↓75%" for FTE count
            # against 10-12 people down from >70, and the report read
            #
            #     10-12 ÷ >70 = 14.29-17.14%  — but the deck states ↓75%
            #
            # putting 15% beside 75% as though they should match. A founder cannot tell
            # what is being alleged. (There IS tension underneath -- 11 of 70 is an 84%
            # reduction, not 75% -- but that is a different comparison from the one shown,
            # and it runs in the founder's favour.)
            #
            # REFUSED rather than converted. Converting means asserting that this stated
            # figure is a reduction on the strength of a glyph and a couple of label
            # words, and a wrong read there MANUFACTURES a contradiction by flipping the
            # comparison. Refusing suppresses. The codebase already resolves this class
            # the same way for currency and period mismatches: where a rule cannot decide,
            # refuse the comparison rather than assert one.
            r.reasons.append(
                f"cannot test a computed share against {exp.raw}, which states a reduction — "
                "they are complements, not the same quantity"
            )
        elif cu == "dimensionless" and exp.unit_kind in (PERCENT, MULTIPLE):
            # a bare ratio IS a percent, once scaled
            comparable = r.computed * 100 if exp.unit_kind == PERCENT else r.computed
        elif cu.startswith("duration:") and exp.unit_kind == DURATION:
            comparable = r.computed

        if comparable is None:
            r.verdict = "incomparable"
            r.reasons.append(f"cannot test against {exp.raw}: computed is {cu or 'unknown'}, stated is {exp_unit}")
            return r
        # Tolerance comes from the STATED figure, plus -- for sums only -- what the
        # operands contribute. The shipped rule was
        #     max(implied_tolerance(exp.raw), implied_tolerance(real[0].raw))
        # and the second term is a unit-space leak: it let a $1.2B operand donate a
        # tolerance of 50,000,000 to a comparison being made in PERCENT space, so a 3.0%
        # computed against a stated 3.5% was certified as matching. Under any
        # significant-figures rule it also becomes actively destructive -- a $57,000
        # operand would donate +/-500 and silently absorb a genuine 34% error.
        tol = figure_tolerance(exp) + operand_tolerance(r.operator, real)
        # Compare INTERVALS, not points. A contradiction exists only when the computed
        # range and the stated range cannot both be true -- if they overlap, the deck is
        # consistent with itself and there is nothing to report. Point values are
        # zero-width intervals, so this subsumes the simple case.
        scale = 100.0 if (r.computed_unit == "dimensionless" and exp.unit_kind == PERCENT) else 1.0
        c_lo = (r.span_lo if r.span_lo is not None else r.computed) * scale
        c_hi = (r.span_hi if r.span_hi is not None else r.computed) * scale
        c_lo, c_hi = min(c_lo, c_hi), max(c_lo, c_hi)
        e_lo, e_hi = exp.span()
        # A bounded figure gets a ONE-SIDED test. "$200B+" is satisfied by anything at or
        # above it, so a computed $212.3B confirms it rather than contradicting it.
        if exp.bound == "at_least":
            disjoint = c_hi < e_lo - tol
        elif exp.bound == "at_most":
            disjoint = c_lo > e_hi + tol
        else:
            disjoint = c_hi < e_lo - tol or c_lo > e_hi + tol
        # Render the computed side in the STATED figure's unit. "145.5%" printed beside
        # "20–40×" is arithmetically right and reads as apples to oranges; 1.45x beside
        # 20–40x is the same fact, comparable at a glance.
        if exp.unit_kind == MULTIPLE and r.computed_unit == "dimensionless":
            span = f"{c_lo:,.2f}–{c_hi:,.2f}x" if c_lo != c_hi else f"{c_lo:,.2f}x"
            r.rendered = r.rendered.split(" = ")[0] + f" = {span}"
        elif r.span_lo is not None and r.span_lo != r.span_hi:
            # Carry over whatever unit the point rendering used ("months", "per count"):
            # dropping it turned "6.2 months" into a bare "3.75–6.25".
            head, _, tail = r.rendered.partition(" = ")
            suffix = "".join(ch for ch in tail if not (ch.isdigit() or ch in ",.-–")).strip()
            r.rendered = f"{head} = {c_lo:,.2f}–{c_hi:,.2f}" + (f" {suffix}" if suffix else "")
        # CONVENTION CLASSES. A disagreement can be arithmetically real and still not be a
        # finding, because the two sides express the same fact under different conventions.
        # Measured on 30 expert-adjudicated findings: these three classes account for six of
        # the eight false positives, and none of them is a tolerance problem -- widening
        # tolerance far enough to absorb them would delete real findings many times over.
        #
        # Ordered before the scale guard and the contradiction verdict, and each records WHY
        # rather than silently dropping: a founder who is told nothing learns nothing, and a
        # maintainer who sees a bare suppression will remove it.
        conv: str | None = None
        if disjoint:
            mid = (c_lo + c_hi) / 2.0
            if _growth_convention(mid, exp, _convention_tolerance(exp, mid, r.operator, real), r.computed_unit):
                conv = (
                    f"the deck reports growth ({exp.raw}) where this computes the multiple "
                    f"({mid:,.1f}%) — the same fact, 100 points apart by convention"
                )
            elif _sign_convention(mid, exp, tol):
                conv = f"magnitudes agree with the stated {exp.raw}; only the sign convention differs"
            elif _immaterial_percent(mid, exp):
                conv = (
                    f"differs from the stated {exp.raw} by {abs(mid - exp.value) / abs(exp.value):.1%} "
                    f"— below the materiality floor for a percentage"
                )
        if conv:
            r.verdict = "convention_differs"
            r.reasons.append(conv)
            return r
        if disjoint and _scale_divergent(c_lo, e_lo):
            # BACKSTOP ONLY. Measured, this fires on nothing in the current corpus -- the
            # deck-D cashflow rows it was originally written for disagree by 0.01%, not
            # by 1000x, and the 1000x appearance was the rendering defect fixed above. It
            # is kept small against the one failure mode that would produce the class: an
            # extraction that expands some cells of a scaled table and not others.
            #
            # `incomparable`, never a silent rescale. Rescaling would hide a genuine
            # 1000x error in a deck, which is precisely the thing a founder most needs
            # told.
            r.verdict = "incomparable"
            r.reasons.append(
                f"computed and stated differ by very nearly a power of a thousand "
                f"({exp.raw}); these are probably not in the same units, so no "
                f"disagreement is established"
            )
        elif disjoint:
            r.verdict = "contradiction"
            # "the deck states X" is a claim about what the document SAYS, and it must
            # only be made about a number a reader can see. A chart series that is plotted
            # but never labelled is not something the deck states -- asserting otherwise
            # would describe the deck falsely while sounding maximally confident.
            src = "the deck states" if exp.visible else "the underlying data behind that chart gives"
            r.rendered += f"  — but {src} {_stated(exp)} ({exp.label})"
            if exp.visible and any(not f.visible for f in real):
                # The most useful shape this produces: a claim printed on the slide that
                # its own chart data contradicts.
                r.reasons.append(
                    "computed from chart data that is plotted but not printed on the slide, "
                    "and it disagrees with a figure the deck does print"
                )
        else:
            r.verdict = "confirmation"
            # A satisfied bound is not a match. 1,195 against "fewer than 2,000" agrees
            # with the deck without equalling anything it says, and calling that a match
            # misdescribes what was established.
            verb = "is consistent with the stated" if exp.bound in ("at_least", "at_most") else "matches the stated"
            r.rendered += f"  — {verb} {_stated(exp)}"
    elif r.operator == "sum" and len(real) == 2 and r.kind != "contradiction":
        # "52 + 3 = 55 customers" restates the deck rather than testing it.
        r.verdict = "restatement"
    elif _is_self_comparison(r, real):
        # A CROSS-SLIDE CONSISTENCY CHECK THAT PASSED. The model pairs the same quantity
        # stated on two slides -- "150+ accounts" on slide 2 against "150+ accounts" on
        # slide 9 -- to see whether the deck contradicts itself. That is a good check, and
        # when the two DIFFER the disagreement surfaces on its own merits.
        #
        # When they agree the answer is 100%, and rendering that as a founder-facing
        # reading produced "150+ / 150+ = 100.0%" under "What the numbers imply". It tells
        # a founder nothing and reads as a malfunction. Same principle as the sum branch
        # above: a relation that reproduces what the deck already says is not a finding.
        r.verdict = "restatement"

    if any(f.attribution == "layout_attributed" for f in real):
        # Confidence is bounded by the WEAKEST operand's attribution, not by whether the
        # arithmetic worked.
        r.confidence = "medium"
        r.reasons.append("one or more operands take their label from slide layout, not from the quoted text")
    return r


def select(relations: list[Relation], max_derived: int = 3) -> list[Relation]:
    """Decide what a founder actually sees.

    Every material CONTRADICTION, because those are established rather than judged, and
    there are naturally few of them -- roughly 3-6 per deck, which is why this needs no
    "top N" ranking. Then a bounded handful of DERIVED characterisations, which are the
    model's judgement and must be labelled as such; the flagship take-rate finding lives
    in this class, which is why the class cannot simply be dropped.

    Confirmations and restatements are withheld from the main section: nothing is wrong,
    so there is nothing to act on, and volume is the enemy of the few findings that count.

    max_derived is a CAP, not a target -- if only one derived ratio clears high
    confidence, one is what shows. The value 3 is provisional and should be set from a
    wider sample rather than kept because it was the first number written down.
    """
    live: list[Relation] = []
    seen: set[tuple] = set()
    for r in relations:
        if r.dropped:
            continue
        sig = (r.operator, tuple(sorted(r.operands)), r.expected_id)
        if sig in seen:  # same relation reached twice via merged endpoint twins
            continue
        seen.add(sig)
        live.append(r)

    # Order contradictions MOST-WRONG FIRST, by how far the computed value sits from the
    # stated one in relative terms. A 50% discrepancy deserves the founder's attention
    # before a 3% one, and until now the order was whatever the model happened to propose.
    #
    # Ordering rather than capping, deliberately. The docstring above assumes "roughly 3-6
    # per deck", and one live deck delivered NINE -- but that was the pre-fix engine; on the
    # current one the four scored decks give 4/2/0/1, back inside the premise. A cap today
    # would fire on nothing, so it would be untested code written for a lever that has not
    # landed. It becomes necessary if proposal-ensembling ships, because that is what breaks
    # the volume assumption; add it then, with the volume it actually has to manage.
    def _wrongness(r: Relation) -> float:
        if r.expected_value in (None, 0) or r.computed is None:
            return 0.0
        return abs(r.computed - r.expected_value) / abs(r.expected_value)

    contradictions = sorted((r for r in live if r.verdict == "contradiction"), key=_wrongness, reverse=True)
    derived = [r for r in live if r.verdict == "derived" and r.confidence == "high"]
    return contradictions + derived[:max_derived]


DOWNGRADE_CLASSES = {
    "partial_enumeration": (
        "A sum of listed components against a stated total, where the deck never claimed the "
        "list was exhaustive. Whether a breakdown was PRESENTED as complete is a layout "
        "question, not an arithmetic one, which is why no deterministic rule can answer it."
    ),
    "approximate_stated_figure": (
        "The deck marked the stated side approximate and the gap is within what that "
        "approximation covers. Distinct from the materiality floor, which is a fixed "
        "percentage: this weighs how loose the author's own '~' was meant to be."
    ),
}
"""The only reasons a surviving contradiction may be withdrawn. A CLOSED SET, and short.

Each class is here because the corpus contains a finding the expert graded not-a-problem for
exactly that reason, and because the convention-classes work established that no deterministic
rule can catch it: partial enumeration needs to know whether a breakdown was presented as
complete, and the approximate case sits at 14.3% relative, above any materiality floor that
does not also swallow genuine 12% errors.

WHAT IS DELIBERATELY ABSENT, and this is the important part. The original Phase 3 spec's
motivating class was "the relation was mis-specified" -- the model picked `increase_by` where
the deck meant a multiple -- with `$26B increased by 400% = 130B vs a stated $104B` as the
example, since 26 x 4 = 104 EXACTLY under the sibling operator. That is a compelling mechanical
tell and it is wrong: the expert graded BOTH deck-F items **real**, two days after the spec was
written. A deck writing "400%" where it means 4x has made exactly the kind of imprecision an
analyst catches, which is what this skill exists to surface.

So the corpus contains zero positive evidence for a mis-specification class and one strong
counterexample. Adding it would invite the model to withdraw precisely the findings the expert
kept -- the same mistake the sign-convention rule nearly made before review caught it. If a
future corpus produces a real mis-specified relation, add the class then, with the case attached.
"""

MIN_FIGURES = 2
"""Below this a deck states too few numbers for any relation to exist.

Two, not one, because every relation this engine supports takes at least two operands.
A one-figure deck is not a gate failure and not an error — there is simply nothing to
reconcile, which `status: no_figures` says.
"""

_DIGIT_RUN = re.compile(r"\d")
NUMERAL_REFUSAL_THRESHOLD = 40
"""How many numerals in the deck make `no_figures` implausible enough to refuse.

The cheapest way to skip this whole chain is to return an empty ledger, and an empty
ledger is indistinguishable from a genuinely wordless deck unless something else has
looked at the deck. `--inventory` is that something else. The threshold is a CHOICE
sized well above slide numbers and a date — a deck with forty numerals in its text is
not a deck with nothing to reconcile.
"""


def _inventory_numerals(inventory: dict[str, Any]) -> int:
    """Count numerals in the inventory's slide text, for the `no_figures` refusal."""
    slides = inventory.get("slides")
    if not isinstance(slides, list):
        return 0
    total = 0
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for key in ("headline", "summary", "content", "text"):
            value = slide.get(key)
            if isinstance(value, str):
                total += len(_DIGIT_RUN.findall(value))
    return total


def _fail(message: str) -> int:
    """Reject loudly: diagnostic on stdout, a line on stderr, `-o` left untouched.

    Six producers across four skills independently got this wrong by writing an
    invalid-shaped artifact THROUGH `-o` and returning 0, which destroyed the prior good
    artifact and made every SKILL.md error branch unreachable.
    """
    print(json.dumps({"validation": {"status": "invalid", "errors": [message]}}, indent=2))
    print(f"Error: {message}", file=sys.stderr)
    return 1


def _signature(operator: str, operands: list[str], expected_id: str | None) -> tuple[Any, ...]:
    """How a downgrade names the relation it withdraws.

    The same triple `select()` dedupes on, so a downgrade addresses exactly one relation and
    cannot be written to match a family of them.
    """
    return (operator, tuple(sorted(operands)), expected_id or None)


def apply_downgrades(
    relations: list[Relation], downgrades: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Withdraw contradictions the interpretation pass judged not to be findings.

    DEMOTE-ONLY, in the same shape as cap-table's `cross_checker.py`: this can move a relation
    out of the founder's view and can do nothing else. It never upgrades, never converts a
    contradiction into a confirmation, never edits a number, and never touches a relation that
    is not currently a contradiction. The deterministic verdict is what it was; `downgraded`
    records that a judgement was laid on top of it.

    That makes a wrong downgrade FAIL SILENT — it suppresses a finding rather than manufacturing
    one — which is the second half of the rule governing everything that crosses the code/model
    boundary here. The first half is that the code can check the claim, and it can: the class
    must come from a closed set, and the relation named must actually exist and actually be a
    contradiction.

    An unmatched downgrade is an ERROR, not a no-op. A downgrade that silently matches nothing
    is indistinguishable from one that worked, and the whole pass would report success while
    changing nothing.
    """
    errors: list[str] = []
    applied: list[dict[str, Any]] = []
    by_sig = {_signature(r.operator, r.operands, r.expected_id): r for r in relations if not r.dropped}

    for index, entry in enumerate(downgrades):
        where = f"downgrades[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object")
            continue
        klass = entry.get("class")
        if klass not in DOWNGRADE_CLASSES:
            errors.append(f"{where} class {klass!r} is not one of {sorted(DOWNGRADE_CLASSES)}")
            continue
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{where} has no reason; a withdrawal with no stated ground is not auditable")
            continue
        operands = entry.get("operands")
        if not isinstance(operands, list) or not all(isinstance(o, str) for o in operands):
            errors.append(f"{where} operands must be an array of figure ids")
            continue
        sig = _signature(str(entry.get("operator", "")), operands, entry.get("expected_id"))
        target = by_sig.get(sig)
        if target is None:
            errors.append(f"{where} names no relation in this reconciliation: {sig}")
            continue
        if target.verdict != "contradiction":
            errors.append(f"{where} targets a {target.verdict!r} relation; only a contradiction can be withdrawn")
            continue
        target.verdict = "downgraded"
        applied.append(
            {
                "operator": target.operator,
                "operands": target.operands,
                "expected_id": target.expected_id,
                "class": klass,
                "reason": reason.strip(),
                "rendered": target.rendered,
            }
        )

    return applied, errors


def _coverage(figures: list[Figure], slides_transcribed: list[Any]) -> dict[str, Any]:
    """Which figure-bearing slides the second read actually covered.

    WHY THIS IS NOT COSMETIC. A figure fails the gate for two very different reasons and
    they are indistinguishable from the gate's own output: the extracting agent invented
    it, or the second read never looked at its slide. The first means the ledger cannot
    be trusted. The second means WE did not check, and reporting it as a trust failure
    would blame the deck for our own coverage gap.

    Recording it also closes the cheapest way to fake this step — transcribing one slide
    and claiming the read is done leaves a visible hole here rather than a quiet pile of
    unverified figures.
    """
    named = sorted({f.slide for f in figures if isinstance(f.slide, int)})
    seen = {s for s in slides_transcribed if isinstance(s, int)}
    return {
        "slides_named": named,
        "slides_transcribed": sorted(seen),
        "slides_missing": [s for s in named if s not in seen],
    }


def build(
    ledger: dict[str, Any],
    transcript: str,
    rel_specs: list[dict[str, Any]],
    inventory: dict[str, Any] | None = None,
    slides_transcribed: list[Any] | None = None,
    downgrades: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the gate, compute every proposed relation, and select what a founder sees.

    Returns (result, error). Exactly one is None. Kept separate from `main` so the
    offline corpus parity check can call it without a filesystem.
    """
    figures = load_figures(ledger)
    # DATE ROWS ARE NOT CHECKABLE FIGURES. Every operator refuses a date participant, so a
    # date can never support or contradict anything -- yet it counted toward
    # `figures_total`, `figures_verified` and the minimum-figures gate. Measured: one real
    # figure alone yields `no_figures`, and adding a date turns the run `checked` with two
    # "verified" figures. The date contributed nothing and moved the gate, which is the one
    # place a bogus date could still do damage once the arithmetic refused it.
    #
    # Excluded, not hidden: the count is reported so a deck whose ledger is mostly dates is
    # visible rather than quietly thin.
    dates_excluded = sum(1 for f in figures if f.unit_kind == DATE)
    figures = [f for f in figures if f.unit_kind != DATE]
    # Fuse endpoint twins into one interval BEFORE anything compares them. Extraction
    # routinely splits a stated range across two rows -- the deck says "40-60x throughput"
    # and the ledger comes back with a "low end" figure of 40x and a "high end" of 60x.
    # Without this, each endpoint is compared as a POINT: a computed 50x contradicts the
    # stated 40 and again the stated 60, while sitting comfortably inside the range the
    # deck actually claims. Measured on one live deck: 9 contradictions reached the
    # founder, 7 of them this artifact, and restoring the fuse left exactly the 2 an
    # expert graded real.
    #
    # This step existed in the prototype pipeline and was dropped in the port -- the call
    # lived in the eval DRIVER (surface.py), not in reconcile.py, so writing build() from
    # this file's shape lost it at the file boundary. `compute()` has been reaching for
    # `_alias` and finding nothing ever since.
    figures, alias = merge_range_twins(figures)
    verify(figures, transcript, quote_in_doc)
    verified = [f for f in figures if f.verified]
    coverage = _coverage(figures, slides_transcribed or [])

    if len(figures) < MIN_FIGURES:
        if inventory is not None and _inventory_numerals(inventory) >= NUMERAL_REFUSAL_THRESHOLD:
            return None, (
                f"ledger holds {len(figures)} figure(s) but the deck's own text carries "
                f">= {NUMERAL_REFUSAL_THRESHOLD} numerals — extract the deck's figures rather "
                "than reporting that it has none"
            )
        status = "no_figures"
    elif len(verified) < MIN_FIGURES:
        status = "gate_failed"
    else:
        status = "checked"

    by_id = {f.id: f for f in figures}
    # Copy each spec before stamping the alias map: the caller's payload is not ours to
    # mutate, and a re-run with the same specs must behave identically.
    computed = [compute({**spec, "_alias": alias}, by_id) for spec in rel_specs] if status == "checked" else []

    # The interpretation pass runs AFTER the arithmetic and BEFORE selection, so `select()`
    # stays the single place that decides what a founder sees. A downgrade is an input to
    # that decision, never an edit to its output.
    contradictions_before = sum(1 for r in computed if not r.dropped and r.verdict == "contradiction")
    applied: list[dict[str, Any]] = []
    if downgrades:
        applied, downgrade_errors = apply_downgrades(computed, downgrades)
        if downgrade_errors:
            return None, "; ".join(downgrade_errors)
    if contradictions_before == 0:
        interpretation = "not_needed"
    elif downgrades is None:
        interpretation = "not_run"
    else:
        interpretation = "applied"

    selected = select(computed)

    # Counts, not contents. A suppressed relation must not be reachable from the
    # artifact: `select()` is the one place that decides what a founder sees, and
    # shipping the full list beside it invites a renderer to reach past it.
    suppressed: dict[str, int] = {}
    for rel in computed:
        if rel in selected:
            continue
        key = "dropped" if rel.dropped else rel.verdict
        suppressed[key] = suppressed.get(key, 0) + 1

    return {
        "status": status,
        "figures_total": len(figures),
        "figures_verified": len(verified),
        "second_read_coverage": coverage,
        # A quote that carries no word identifies nothing: the gate matches TEXT, so "$80B"
        # is re-found on any slide that prints $80B. `ledger.py` warns at extraction time,
        # but that warning landed in `ledger.json`, which the receipt does not summarise,
        # this script does not read for validation, and compose does not load at all — so
        # it reached no human. Counted here because reconciliation IS read downstream.
        "dates_excluded": dates_excluded,
        "quote_quality": {
            "thin": sum(1 for f in figures if not quote_is_identifying(f.quote)),
            "total": len(figures),
        },
        "attribution": {
            "quote_carries_label": sum(1 for f in verified if f.attribution == "quote_carries_label"),
            "layout_attributed": sum(1 for f in verified if f.attribution == "layout_attributed"),
        },
        # Optional fields are OMITTED when absent, never emitted as null. The schema
        # validator types them (`expected_id` is a string, `span_lo` a number) and a
        # JSON null is neither, so emitting one turns "this relation has no stated
        # counterpart" — the normal case for a derived ratio — into a validation error
        # that fails the whole artifact.
        "relations": [
            {
                key: value
                for key, value in (
                    ("kind", r.kind),
                    ("operator", r.operator),
                    ("operands", r.operands),
                    ("computed", r.computed),
                    ("rendered", r.rendered),
                    ("confidence", r.confidence),
                    ("verdict", r.verdict),
                    ("expected_id", r.expected_id),
                    ("expected_value", r.expected_value),
                    ("span_lo", r.span_lo),
                    ("span_hi", r.span_hi),
                )
                if value is not None
            }
            for r in selected
        ],
        "suppressed": suppressed,
        "relations_proposed": len(rel_specs),
        # not_needed = nothing to interpret. not_run = contradictions survived and no
        # interpretation pass was supplied, so the founder is seeing the un-reviewed set.
        # applied = the pass ran; every withdrawal it made is recorded below by class and
        # reason, because a suppression with no stated ground cannot be audited later.
        "interpretation": {
            "status": interpretation,
            "contradictions_before": contradictions_before,
            "downgraded": applied,
        },
    }, None


def _read_json(path: str, label: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, f"{label} not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"{label} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{label} must be a JSON object"
    return data, None


def main() -> int:
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="Verify a deck's numeric ledger and reconcile it against itself.")
    ap.add_argument("--ledger", required=True, help="ledger.json from LEDGER_EXTRACTION")
    ap.add_argument("--second-read", required=True, help="second_read.json — the second-read transcript")
    ap.add_argument("--inventory", help="deck_inventory.json; enables the no_figures refusal")
    ap.add_argument(
        "--downgrades",
        help="the INTERPRETATION pass's hand-off; withdraws contradictions it judged not to be findings",
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if sys.stdin.isatty():
        print("Error: pipe the proposed relations as JSON via stdin", file=sys.stderr)
        return 1
    try:
        proposal = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        return _fail(f"invalid JSON on stdin: {exc}")
    if not isinstance(proposal, dict):
        return _fail("stdin JSON must be an object")
    rel_specs = proposal.get("relations", [])
    if not isinstance(rel_specs, list):
        return _fail("'relations' must be an array")

    ledger, err = _read_json(args.ledger, "ledger")
    if err:
        return _fail(err)
    second, err = _read_json(args.second_read, "second read")
    if err:
        return _fail(err)
    inventory = None
    if args.inventory:
        inventory, err = _read_json(args.inventory, "inventory")
        if err:
            return _fail(err)

    transcript = second.get("transcript", "") if second else ""
    if not isinstance(transcript, str):
        return _fail("second read's 'transcript' must be a string")
    slides_transcribed = second.get("slides_transcribed", []) if second else []
    if not isinstance(slides_transcribed, list):
        return _fail("second read's 'slides_transcribed' must be an array")

    downgrades = None
    if args.downgrades:
        payload, err = _read_json(args.downgrades, "downgrades")
        if err:
            return _fail(err)
        assert payload is not None
        downgrades = payload.get("downgrades", [])
        if not isinstance(downgrades, list):
            return _fail("'downgrades' must be an array")

    assert ledger is not None
    result, err = build(ledger, transcript, rel_specs, inventory, slides_transcribed, downgrades)
    if err or result is None:
        return _fail(err or "reconciliation failed")

    result["validation"] = {"status": "valid", "errors": [], "warnings": []}
    result["metadata"] = {"run_id": args.run_id}

    if args.output:
        schema_path = (
            pathlib.Path(__file__).resolve().parents[1] / "references" / "schemas" / "reconciliation.schema.json"
        )
        receipt = write_artifact(
            data=result,
            schema=load_schema(str(schema_path)),
            run_id=args.run_id,
            output_path=args.output,
            pretty=True,
        )
        print(json.dumps(receipt, indent=2))
        return 0

    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
