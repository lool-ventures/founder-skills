"""Detect a 'times' comparison an evidence sentence's own cited figures contradict.

WHY A SIBLING MODULE AND NOT A FUNCTION IN compose_report.py. Three producers render the SAME
assessor-written evidence and none of them sees compose's output: `compose_report.py` into
`report.md`, `visualize.py` into `report.html`, `explore.py` into `explorer.html`. A check that
lives in only one of them warns on one surface while the other two ship the unsupported number
plain -- which is the "verify against every delivered surface" failure this repo has hit before,
and which the first cut of this check reproduced.

THE DEFECT. A CHECKLIST sub-agent reviewing a real 12-sheet model asserted the projections were
"roughly 2,000x" the actuals while citing, in the same sentence, the two figures whose ratio is
6.8x -- wrong by ~293x. It reached every founder-facing surface and two criteria were scored FAIL
on it.

WHY IT IS THIS NARROW, measured rather than argued. Over 2,854 real CHECKLIST evidence/notes
strings harvested from every kept run dir (289 financial-model-review, 1,563 deck-review, 694
competitive-positioning, 308 market-sizing), only 39 state a multiple at all and exactly ONE fires:
the defect. SILENT ON THE OTHER 38 -- which is the claim the measurement supports. It is not "zero
false positives" in general: constructed prose can still fire it, and the caveat wording is written
to stay true when it does. A broader rule -- "does SOME pair in the sentence support the
multiple" -- measured 36% precision on hand-written probes, below the bar
`compose_report._check_metric_self_contradiction` documents when it explains why it dropped whole
metric classes: a check that fires on well-written prose trains the reader to ignore it.
`founder-skills/tests/evidence_multiple_corpus.py` re-runs that measurement; it imports THIS module,
so the tool and production cannot drift apart.
"""

from __future__ import annotations

import re
from typing import Any

# Space-free ON PURPOSE. `deck-review/scripts/reconcile.py`'s `_MANTISSA` carries an internal
# space group, so copying it reads "Revenue in 2024 100x" as 2,024,100x -- a spurious multiple
# that large beside two real figures fires with certainty, which inverts the safety argument
# instead of supporting it. Do not "unify" this with the operand grammar below.
MULTIPLE_RE = re.compile(r"(?<![\w.$€£₹])(\d[\d,]*(?:\.\d+)?)\s?[x×](?![\w\d])")

# An operand must be currency-, scale- or grouping-marked. A bare integer is not one: that
# exclusion is what keeps years, counts and criterion numbers out of the comparison.
OPERAND_RE = re.compile(r"(?<![\w.])(?:[$€£₹]\s?)?(\d[\d,]*(?:\.\d+)?)\s*([KMB]|bn|mn)?\b")
_SCALE = {None: 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "bn": 1e9, "mn": 1e6}

# The multiple must be BOUND to its operands by a comparison connective ("2,000x THE FY23 actual").
# Without this the check asks "does some pair here support the multiple", whose complement is
# dominated by correct prose.
# The `(?<![A-Za-z])` is load-bearing: without it this matched any WORD ending in x followed by a
# stopword -- "Tax the", "Capex the", "mix the" -- so the multiple was not bound to anything and
# three of four constructed false-positive shapes fired through it.
CONNECTIVE_RE = re.compile(r"(?<![A-Za-z])[x×]\s+(?:of|vs\.?|versus|against|compared to|the|than|over)\b")
WINDOW_CHARS = 90
DIVERGENCE_THRESHOLD = 10.0

#: Appended to a flagged string on every founder-facing surface. Stays TRUE if the flag is a false
#: positive, which is what makes an uncalibrated warning shippable at all.
CAVEAT = "[The 'times' comparison here is not supported by the figures quoted beside it — do not repeat it.]"


_SENTENCE_END_RE = re.compile(r"[.!?;](?:\s|$)")


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """The sentence containing [start, end). Abbreviations are not special-cased.

    A missed boundary (e.g. "vs." mid-sentence) only NARROWS the window, which costs recall and
    never adds a false fire -- the safe direction for a check whose whole justification is a
    measured false-positive rate.
    """
    lo = 0
    for m in _SENTENCE_END_RE.finditer(text[:start]):
        lo = m.end()
    tail = _SENTENCE_END_RE.search(text, end)
    return lo, (tail.start() + 1 if tail else len(text))


def marked_operands(text: str) -> list[tuple[float, int]]:
    """Currency/scale/grouping-marked numbers in `text`, with their offsets."""
    found: list[tuple[float, int]] = []
    for match in OPERAND_RE.finditer(text):
        raw, suffix = match.group(1), match.group(2)
        # `OPERAND_RE` CONSUMES the currency prefix, so `match.start()` lands on the `$` -- testing
        # a slice two characters earlier made this branch true only at string index 0, i.e. dead.
        # Measured while dead: "Cash of $500 against $900" yielded ZERO operands, so the rule the
        # module documented was not the rule it ran. Test the match's own text.
        currency = bool(re.match(r"[$€£₹]", match.group(0)))
        if not (currency or suffix or "," in raw):
            continue
        if MULTIPLE_RE.match(text, match.start()):
            continue
        found.append((float(raw.replace(",", "")) * _SCALE[suffix], match.start()))
    return found


def divergence(multiple: float, operands: list[tuple[float, int]]) -> float | None:
    """How far a stated multiple sits from the nearest ratio its cited operands support.

    A pair containing 0 is dropped BEFORE dividing: `$0` is currency-marked and therefore a legal
    operand -- a pre-revenue model states one -- and `max/min` over it raises. An earlier revision
    omitted this guard and crashed here, inside report assembly, which takes down the whole review.
    """
    candidates: list[float] = []
    for i, (a, _) in enumerate(operands):
        for b, _ in operands[i + 1 :]:
            if a == 0 or b == 0 or a == b:
                continue
            ratio = max(a, b) / min(a, b)
            candidates += [ratio, ratio - 1]
    candidates = [c for c in candidates if c > 0]
    if not candidates:
        return None
    # Direction-blind by construction: a reciprocal error ("0.15x" where the truth is 6.8x) is a
    # KNOWN blind spot, recorded rather than quietly fixed -- removing this needs its own
    # measurement of what legitimate sub-1 phrasings then do.
    normalized = multiple if multiple >= 1 else 1 / multiple
    return min(max(normalized / c, c / normalized) for c in candidates)


def unsupported_multiple(text: Any) -> float | None:
    """The divergence when `text` states a multiple its own cited operands contradict, else None."""
    if not isinstance(text, str) or not text:
        return None
    # EVERY multiple, not just the first. A real finding is a paragraph, so an earlier unrelated
    # "LTV/CAC is 3x" made the actual claim invisible. Measured at zero cost: scanning all of them
    # leaves the corpus at 1 fire and adds none on constructed legitimate prose.
    worst: float | None = None
    for match in MULTIPLE_RE.finditer(text):
        # SENTENCE-SCOPED, which is the design's own premise: "the same sentence carries both the
        # claim and its operands" is what makes this decidable at all. Without it a multiple in one
        # sentence pairs with figures from the next -- measured, that was the one constructed
        # false-positive shape the connective fix did not kill.
        lo, hi = _sentence_bounds(text, match.start(), match.end())
        lo = max(lo, match.start() - WINDOW_CHARS)
        hi = min(hi, match.end() + WINDOW_CHARS)
        if not CONNECTIVE_RE.search(text[match.start() : hi]):
            continue
        operands = [o for o in marked_operands(text) if lo <= o[1] <= hi]
        if len(operands) != 2:
            continue
        multiple = float(match.group(1).replace(",", ""))
        # A multiple of 0 divides by zero at normalization. Reachable: a space-grouped "2 000x"
        # parses as the token `000x`, because the mantissa deliberately stops at the space.
        if multiple <= 0:
            continue
        found = divergence(multiple, operands)
        if found is None or found < DIVERGENCE_THRESHOLD:
            continue
        # Not infinite: a >308-digit multiple overflows to inf, and inf is not valid JSON if this
        # value is ever carried into an artifact.
        if found == float("inf"):
            continue
        worst = found if worst is None else max(worst, found)
    return worst


def caveat(text: Any) -> Any:
    """`text` with the caveat appended when it states an unsupported multiple; unchanged otherwise.

    Idempotent, because three renderers may each call it on the same string.
    """
    if unsupported_multiple(text) is None or (isinstance(text, str) and CAVEAT in text):
        return text
    return f"{text} {CAVEAT}"
