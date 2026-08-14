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

WHAT THE GATE ESTABLISHES, precisely. A figure passes if its verbatim quote appears in
an INDEPENDENT second reading of the deck (a fresh vision transcription that never saw
the ledger). Measured on three decks: 95.7-100% true-pass, 0.0% cross-deck false-pass,
0.0% on invented quotes. Two independent reads agreeing is strong evidence a figure was
not invented. It is NOT proof of provenance -- both reads can misread the same ambiguous
chart identically -- and it says nothing about ATTRIBUTION, which is tracked separately
below and is the weaker link.
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
_AT_MOST_WORDS = re.compile(r"\b(fewer than|less than|under|up to|at most|no more than|below)\b", re.I)
_AT_LEAST_WORDS = re.compile(r"\b(at least|more than|over|exceeds|minimum|or more)\b", re.I)
_APPROX_WORDS = re.compile(
    r"(~|\bapprox\w*|\babout\b|\baround\b|\broughly\b|\best\b|\bestimated\b|\btarget\w*|\bprojected\b)", re.I
)


def detect_bound(raw: str, label: str) -> str | None:
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
    raw, label = raw or "", label or ""
    votes: set[str] = set()
    if _PLUS_RE.search(raw):
        votes.add("at_least")
    if _LEAD_AT_MOST.search(raw):
        votes.add("at_most")
    if _LEAD_AT_LEAST.search(raw):
        votes.add("at_least")
    if _AT_MOST_WORDS.search(label):
        votes.add("at_most")
    if _AT_LEAST_WORDS.search(label):
        votes.add("at_least")
    if {"at_least", "at_most"} <= votes:
        return None  # contradictory signals -- fall back to the plain two-sided test
    if votes:
        return next(iter(votes))
    return "approximate" if (_APPROX_WORDS.search(raw) or _APPROX_WORDS.search(label)) else None


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
                bound=detect_bound(str(raw.get("raw", "")), str(raw.get("label", ""))),
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
    this figure invented?". Attribution asks "does the label belong to this number?" --
    which the gate cannot see, because roughly half of all figures take their label from
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
            f.drop_reason = "quote not found in the independent second read"
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
        # not find in an independent read is unfounded, not weak.
        r.dropped = True
        r.reasons = [f"operand {i} failed verification" for i in unverified]
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
            if _growth_convention(mid, exp, tol, r.computed_unit):
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
    contradictions = [r for r in live if r.verdict == "contradiction"]
    derived = [r for r in live if r.verdict == "derived" and r.confidence == "high"]
    return contradictions + derived[:max_derived]


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
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the gate, compute every proposed relation, and select what a founder sees.

    Returns (result, error). Exactly one is None. Kept separate from `main` so the
    offline corpus parity check can call it without a filesystem.
    """
    figures = load_figures(ledger)
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
    computed = [compute(spec, by_id) for spec in rel_specs] if status == "checked" else []
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
    ap.add_argument("--second-read", required=True, help="second_read.json — the independent transcription")
    ap.add_argument("--inventory", help="deck_inventory.json; enables the no_figures refusal")
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

    assert ledger is not None
    result, err = build(ledger, transcript, rel_specs, inventory, slides_transcribed)
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
