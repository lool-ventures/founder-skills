#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Validate the numeric ledger a sub-agent extracted from the deck.

The sub-agent does the extraction — reading a chart axis and deciding that "$493K" is
2024 GMV is judgment, and no script can do it. This file does the part that is checkable
against the text the model itself returned, and refuses the ledger when it does not hold.

THE CHECK THAT EARNS ITS PLACE is `raw` against `value`. Every scale-sensitive failure in
this domain looks the same: the model reads "$493K" correctly, writes the quote
correctly, and records `value: 493`. Downstream arithmetic is then flawless and wrong by
a thousand. Because `raw` and `value` are two independent statements about the same
figure, disagreement between them is detectable without ever seeing the deck — which is
what makes it a validation rather than a second opinion.

WHAT THIS IS NOT. It is not the provenance gate. Whether a figure's quote can be re-found
in the deck's slides is settled later, in `reconcile.py`, against a second reading that
never saw the ledger — checking a quote against the prompt the model was handed would be
checking the model against itself. Nothing here reads the deck.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402
from _artifact_writer import load_schema, write_artifact  # type: ignore[import-not-found]  # noqa: E402
from reconcile import (  # type: ignore[import-not-found]  # noqa: E402
    _NUM_RE,
    _RANGE_RE,
    CAP,
    DATE,
    MONEY,
    _precision,
    _raw_scale,
    bps_factor,
    numeral_form,
    parse_range,
    quote_is_identifying,
    strip_group_marks,
)

UNIT_KINDS = {"money", "count", "percent", "multiple", "duration", "date"}

SIGFIG_ONLY = True
"""`value` must agree with `raw` to within RAW'S OWN precision, capped at `CAP`. No floor.

There used to be a 2% floor here, applied as a `max()` over the significant-figure
tolerance, and it was the reason a real defect shipped. A live deck recorded
`raw: "15873.2"` with `value: 15873` — extraction silently dropped a decimal — and the
0.0012% discrepancy vanished inside a 2% floor. Downstream that truncation moved a sum
0.54 off its stated total against a tolerance of 0.555, and a founder was told their
revenue disagreed with itself by 1 part in 16,904.

Significant figures alone discriminate correctly on every case the floor was meant to
cover, which is why the floor is gone rather than tuned. Measured:

    raw          value      sigfig tol   capped tol      gap      verdict
    15873.2      15873        0.0003%      0.0003%   0.0013%     reject   <- the precision loss
    $1.2M      1238400        4.1667%      4.1667%   3.2000%     accept   <- a genuinely rounded figure
    $493K            493      0.1014%      0.1014%  99.9000%     reject   <- the 1000x scale slip
    100               97     50.0000%      5.0000%   3.0000%     accept   <- a round figure, rounded
    10                14     50.0000%      5.0000%  40.0000%     reject   <- not the number printed

The floor was introduced when this check used a FLAT percentage, which genuinely could not
express "$1.2M legitimately covers 1.15M-1.25M". Switching to significant figures solved
that; keeping the floor afterwards was leftover scaffolding that only ever loosened.

Significant figures alone over-claim in the other direction, on round numbers: "10" is one
significant figure, which claims +/-5, so a value of 14 passed as a reading of "10", and "$1M"
covered 1.4M. So the window is capped at `CAP` (5%), the same ceiling `reconcile.py` puts on
the same ratio in `figure_tolerance`. Unlike `figure_tolerance`, there is no implied-tolerance
floor under it: that floor answers whether a computed sum contradicts a stated total, and
`implied_tolerance("$1M")` is half a million, which would reopen "$1M" as 1.4M. This check asks
only whether `value` is the number `raw` prints, which needs no floor. A window of exactly
`CAP` is inside it (the test is `>`), as in `reconcile.py`.

A range is accepted at either of its two numbers and no other; reconcile reads it from its low
end, which is what makes either safe. So "10-12" is recorded as 10 or 12, never 11, and a number
printed before the range ("5 of 10-12 pilots") is not a reading of it.
"""


def _parsed_magnitude(raw: str) -> float | None:
    """What `raw` says the figure is, read independently of `value`."""
    raw = numeral_form(raw)
    match = _NUM_RE.search(raw)
    if not match or not match.group("int"):
        return None
    # Strip every grouping mark the shared mantissa admits, not just the comma: "$20 000"
    # is twenty thousand, and reading it as 20 made the correct value look like a 1000x error.
    digits = strip_group_marks(match.group("int"))
    frac = match.group("frac")
    try:
        magnitude = float(f"{digits}.{frac}") if frac else float(digits)
    except ValueError:
        return None
    return magnitude * _raw_scale(raw)


def _printed(number: float) -> str:
    """A magnitude as a slide would print it: group marks, no exponent, no trailing zeros."""
    return f"{number:,.0f}" if number == int(number) else f"{number:,.10g}"


def _numeric_tokens(raw: str) -> list[float]:
    """Every number the raw string prints, in the order printed, scale suffixes ignored.

    `_parsed_magnitude` reads the FIRST token and applies a scale to it, which is right
    for a magnitude and wrong for a date: "Q4 2025" reads as 4, so a correctly-extracted
    2025 was rejected as a 506x scale error. A date has no scale — it is one of the
    numbers on the slide — so the date check compares against all of them.
    """
    out: list[float] = []
    for match in _NUM_RE.finditer(numeral_form(raw)):
        digits = strip_group_marks(match.group("int") or "")
        if not digits:
            continue
        frac = match.group("frac")
        try:
            out.append(float(f"{digits}.{frac}") if frac else float(digits))
        except ValueError:
            continue
    return out


# Date SYNTAX, not a value range. The first cut accepted any printed token in 1-12 or
# 1000-9999, which narrowed the example and left the misbinding: a headcount still
# masqueraded as a date whenever it fell in one of those ranges ("Founded 2025; 12
# employees" -> 12, "; 3000 employees" -> 3000). It also made the year forms decks actually
# print -- FY25, Q4 '25 -- unrepresentable, which pushes the model toward recording
# something else.
#
# So bind to what the raw string MARKS as a date: a four-digit year, a two-digit year
# behind FY or an apostrophe, or an ordinal behind a quarter/month marker.
# A CLOSED DATE GRAMMAR, matched against the WHOLE raw string.
#
# Three earlier attempts inferred dates from substrings and each narrowed the example
# rather than the defect: a value range let a headcount be a year, token boundaries still
# let any isolated 1900-2100 number be one ("Headcount 2000", "Revenue $2000"), and the
# boundary characters simultaneously rejected ordinary punctuation ("Founded 2025.") while
# accepting "FY25users" and "Q4ever". Substring inference cannot decide what a number
# MEANS, so it is the wrong instrument.
#
# The rule instead: a `date` raw must BE a date expression, not prose containing one. A
# short leading word ("Founded", "in") and trailing punctuation are tolerated because decks
# print them; anything else fails and the model is told to record the date's own string.
# Lead words a DATE may carry. Closed and small on purpose: "Headcount 2000" is
# syntactically identical to "Founded 2025" -- four digits in range behind one short word --
# so the only thing separating a year from a quantity is which word it is. An allowlist
# fails safe: an unlisted lead means the model is told to record the date's own string,
# which is what the field is supposed to hold anyway.
_DATE_LEAD_WORDS = (
    "founded",
    "since",
    "by",
    "in",
    "from",
    "until",
    "through",
    "as",
    "of",
    "at",
    "on",
    "launch",
    "launched",
    "launching",
    "target",
    "targeting",
    "est",
    "established",
    "expected",
    "projected",
    "starting",
    "start",
    "begins",
    "began",
    "ends",
    "ending",
    "incorporated",
    "inception",
    "close",
    "closing",
    "closed",
)
_DATE_LEAD = rf"(?:(?:{'|'.join(_DATE_LEAD_WORDS)})\s+){{0,2}}"
_DATE_TRAIL = r"[\s.,;:)\]]*"
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
# Decks print abbreviations ("Oct 2026") as often as full names, and a day-precision date
# ("Oct 4, 2026") is unrepresentable without them. The three-letter prefix is the shortest
# unambiguous form across the twelve (jan..dec are all distinct), so it is the abbreviation.
_MONTH_NUMBERS = {name: index + 1 for index, name in enumerate(_MONTH_NAMES)}
_MONTH_NUMBERS.update({name[:3]: index + 1 for index, name in enumerate(_MONTH_NAMES)})
_MONTH_ALT = "|".join([*_MONTH_NAMES, *[name[:3] for name in _MONTH_NAMES]])

# Each alternative captures the components it licenses, named so the value can be bound to
# one of them rather than to "some number that appeared".
_DATE_FORMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ISO 8601: 2026-10-04
    (r"(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})", ("iy", "im", "id")),
    # 2024-2030 (a range of two years)
    (r"(?P<y1>\d{4})\s*[-–—/]\s*(?P<y2>\d{4})", ("y1", "y2")),
    # Q4 2025 / Q4 '25 / Q4
    (r"Q\s?(?P<q>[1-4])(?:\s*(?:FY|')?\s?(?P<qy>\d{4}|\d{2}))?", ("q", "qy")),
    # October 4, 2026 / Oct 4, 2026 / October 4 2026
    (
        rf"(?P<mon2>{_MONTH_ALT})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<dy>\d{{4}})",
        ("mon2", "day", "dy"),
    ),
    # 4 October 2026 / 4 Oct 2026
    (
        rf"(?P<day2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon3>{_MONTH_ALT}),?\s+(?P<dy2>\d{{4}})",
        ("day2", "mon3", "dy2"),
    ),
    # March 2026 / Mar 2026 / March
    (rf"(?P<mon>{_MONTH_ALT})(?:\s+(?P<my>\d{{4}}))?", ("mon", "my")),
    # FY25 / FY2025 / '25
    (r"(?:FY|')\s?(?P<fy>\d{4}|\d{2})", ("fy",)),
    # A bare four-digit year, and nothing else in the string.
    (r"(?P<y>\d{4})", ("y",)),
)

_DATE_RES = tuple((re.compile(rf"^{_DATE_LEAD}(?:{body}){_DATE_TRAIL}$", re.I), groups) for body, groups in _DATE_FORMS)


def _date_values(raw: str) -> set[float] | None:
    """The numbers this raw states as date components, or None if it is not a date at all.

    None and the empty set mean different things: None is "this string is not a date
    expression" (record the date's own string), while a match with no numeric component
    -- "March" alone -- yields the month.
    """
    text = (raw or "").strip()
    for pattern, groups in _DATE_RES:
        match = pattern.match(text)
        if not match:
            continue
        values: set[float] = set()
        for name in groups:
            captured = match.groupdict().get(name)
            if captured is None:
                continue
            if name in ("mon", "mon2", "mon3"):
                values.add(float(_MONTH_NUMBERS[captured.lower()]))
                continue
            number = int(captured)
            if name in ("y", "y1", "y2", "my", "dy", "dy2", "iy") and not 1900 <= number <= 2100:
                # A four-digit token outside plausible years is not a year, and this is the
                # form that let "Headcount 2000" through when the bound was missing.
                return None
            if name in ("day", "day2", "id") and not 1 <= number <= 31:
                # A day outside 1-31 is not a day: "October 41, 2026" is a typo or a
                # misbinding, and every component of a day-precision date is range-checked.
                return None
            if name == "im" and not 1 <= number <= 12:
                return None
            values.add(float(number))
        return values
    return None


_BARE_SUFFIX = re.compile(r"\d\s*[kKmMbBtT]\s*$")


def _ambiguous_suffix(raw: str, value: float, unit_kind: object, currency: object) -> bool:
    """Is the trailing letter a UNIT (metres, months) rather than a multiplier?

    Undecidable from the numbers alone, which is the whole point. Measured:

        raw          value        value == mantissa   truth
        200-400m       200              True          metres, correct
        $493K          493              True          1000x scale error
        32.5m          32.5             True          scale error

    So this does not try to decide. It narrows to the shape where the question ARISES --
    a bare k/m/b/t at the end of the raw, on a figure that is not money, whose value
    equals a mantissa it prints (either end of a range) -- and swaps in a message that tells the model how to resolve it
    instead of telling it to inflate a building.

    Money is excluded because a currency marker settles it: "$493K" is thousands, always.
    """
    if unit_kind == MONEY or currency:
        return False
    raw = numeral_form(raw)
    if not _BARE_SUFFIX.search(raw):
        return False
    # Every mantissa the raw prints: a range's second number is as much "the mantissa" as
    # its first, and "200-400m" recorded as 400 is the same metres question.
    return any(abs(abs(value) - m) <= max(abs(m) * 1e-9, 1e-9) for m in _numeric_tokens(raw))


def _ambiguous_message(where: str, raw: str, parsed: float | None, value: float) -> str:
    """The refusal for a trailing suffix that may be a unit (see `_ambiguous_suffix`)."""
    reading = f" ({parsed:,.4g})" if parsed is not None else ""
    return (
        f"{where} raw {raw!r} is ambiguous: the trailing suffix reads as a "
        f"multiplier{reading} but value is {value!r}. If the suffix is a "
        f"UNIT rather than a multiplier, spell it out in raw (e.g. "
        f"'200-400 metres', '18 months'); if it is a multiplier, record value "
        f"at full scale"
    )


def _bps_remedy(raw: str) -> str:
    """What to record instead, for a basis-point raw recorded as a percent.

    A BASIS POINT IS A PERCENT TIMES 100, and the number in the message is built from the
    raw's own parsed magnitude, so it always names the figure the slide prints rather than a
    value hard-coded here.
    """
    factor = bps_factor(raw)
    rng = parse_range(raw)
    if rng is not None:
        points = f"{_printed(rng[0] / factor)}–{_printed(rng[1] / factor)}"
        return (
            f"{points} basis points is {_printed(rng[0])}–{_printed(rng[1])} percent; "
            f"record value {_printed(rng[0])} or {_printed(rng[1])}"
        )
    parsed = _parsed_magnitude(raw)
    if parsed is None:
        return "record the figure's value as a percent"
    return f"{_printed(parsed / factor)} basis points is {_printed(parsed)} percent; record value {_printed(parsed)}"


def _reads_as(observed: float, end: float, relative: float) -> bool:
    """Is `observed` a reading of one printed number, within the raw's own window? Zero absolutely."""
    if end == 0:
        return abs(observed) <= 1e-9
    return abs(observed - end) / abs(end) <= relative


def validate_ledger(data: dict[str, Any], total_slides: int | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). A non-empty errors list means the ledger is refused."""
    errors: list[str] = []
    warnings: list[str] = []

    figures = data.get("figures")
    if not isinstance(figures, list):
        return ["'figures' must be an array"], warnings

    seen: set[str] = set()
    for index, fig in enumerate(figures):
        where = f"figures[{index}]"
        if not isinstance(fig, dict):
            errors.append(f"{where} must be an object")
            continue

        fig_id = fig.get("id")
        if not isinstance(fig_id, str) or not fig_id.strip():
            errors.append(f"{where} has no id")
        elif fig_id in seen:
            errors.append(f"{where} duplicates id {fig_id!r}; relations address figures by id")
        else:
            seen.add(fig_id)

        value = fig.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{where} value must be a number, got {value!r}")
            value = None

        unit_kind = fig.get("unit_kind")
        if unit_kind not in UNIT_KINDS:
            errors.append(f"{where} unit_kind {unit_kind!r} is not one of {sorted(UNIT_KINDS)}")

        quote = fig.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            errors.append(f"{where} has no quote; the verbatim quote is what the second read checks")
        elif not quote_is_identifying(quote):
            # The schema asks for "the verbatim sentence or table row"; this checked only
            # non-empty. A quote of "$80B" or "58.5% | $585K" satisfies that and identifies
            # nothing — the gate it feeds matches TEXT against the second read, so a bare
            # token matches wherever that token happens to appear on any slide.
            #
            # Every measured wrong-page verification on the corpus is this class, and
            # narrowing the match to the figure's claimed slide does NOT fix it: a one-token
            # needle is not made identifying by a smaller haystack. Probed — a quote of
            # "2010" against a claimed slide reading "Founded 2010. Team of 12." verifies
            # under a slide-scoped rule exactly as it does under a whole-deck one.
            #
            # WARN, never error. This is ~7.5% of a real corpus, too large to refuse without
            # a migration, and some table rows are legitimately terse. Promote after
            # observation.
            #
            # KNOWN GAP: this catches a quote that is too THIN, not one that is not a quote
            # at all. Chart descriptions ("the third bar, unlabelled") carry plenty of words
            # and are ~16% of one live ledger. They need the extracting agent to distinguish
            # a printed string from a reading of a picture, which no shape test can do.
            warnings.append(
                f"{where} quote {quote!r} carries no word — the second read matches this as text, so a "
                f"bare figure matches on any slide that happens to print it. Quote the sentence or the "
                f"whole table row, label included."
            )

        raw = fig.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"{where} has no raw; without the slide's own string, scale cannot be checked")
        elif not _NUM_RE.search(numeral_form(raw)):
            # A `raw` WITH NO NUMBER IN IT IS NOT THE FIGURE'S PRINTED STRING. A count the
            # slide SPELLS OUT ("three", "Fifteen years") is a number: `numeral_form` reads
            # it as digits for every parser here, so it is validated rather than refused.
            # What is refused is a raw with no magnitude at all -- and on one of those,
            # every check that depends on `raw` quietly does nothing. The scale check —
            # the whole reason the field is required — needs a magnitude to compare, and
            # the date rule needs tokens to match against; both simply skip. So the one
            # guarantee `raw` carries is absent exactly where nothing announces it.
            #
            # Measured downstream: `raw="about"` with `value=100` also reads as an
            # approximation, widening tolerance by 10%, which turned a summed 108 against
            # a stated 100 from a contradiction into a confirmation. `raw="TBD"` on a date
            # passed for the mirror reason — an empty token list is not agreement.
            errors.append(
                f"{where} raw {raw!r} contains no number, so it is not the figure's printed string — "
                f"record what the slide prints, or omit the figure"
            )

        # A BASIS-POINT FIGURE IS A PERCENT, and its own unit says so. The scale check below
        # reads the mantissa through `_raw_scale`, which now applies `bps_factor`, so a
        # bps figure recorded as a percent validates; recording it as money or a count is
        # the mismatch this refuses, by name, whatever its value.
        if isinstance(raw, str) and unit_kind != "percent" and bps_factor(raw) != 1.0:
            errors.append(
                f"{where} raw {raw!r} is written in basis points — a basis-point figure is a percent; "
                f"set unit_kind to 'percent' and record its value as a percent"
            )

        # A money figure with no currency divides fine and compares meaninglessly.
        if unit_kind == MONEY and not fig.get("currency"):
            warnings.append(f"{where} is money with no currency; cross-currency relations will be refused")

        slide = fig.get("slide")
        if slide is None:
            warnings.append(f"{where} names no slide; it will not be covered by the second read")
        elif not isinstance(slide, int) or isinstance(slide, bool):
            errors.append(f"{where} slide must be an integer, got {slide!r}")
        elif slide < 1:
            errors.append(f"{where} slide {slide} is below 1")
        elif total_slides is not None and slide > total_slides:
            errors.append(f"{where} slide {slide} is past the deck's last slide ({total_slides})")

        if value is not None and isinstance(raw, str) and unit_kind == DATE:
            # A DATE IS NOT A MAGNITUDE WITH A SCALE, and the check below assumes it is.
            # It reads the first numeric token and applies a scale rule to it, so "Q4 2025"
            # recorded as 2025 — the correct extraction — was refused as a 506x error, while
            # "2024-2030" recorded as its later endpoint was refused as a 1.003x one.
            #
            # The rule that fits a date is token equality: the value has to be a number the
            # slide actually prints. That still catches the two classes this check exists
            # for — a fabricated year, and the 10x slip ("2024" recorded as 20240) — without
            # a scale rule a date has no use for.
            #
            # BOTH readings of "Q4 2025" are admitted, the quarter and the year, on the
            # strength of the figure's label. That would be an ambiguity if anything
            # computed with dates: `Q4 − Q2` would yield "2 years". Nothing does —
            # `reconcile.py` refuses every relation with a date participant, operands and
            # stated side alike — so the ambiguity is unreachable, and neither restricting
            # dates to four-digit years nor adding a self-attested resolution field buys
            # anything here. If date arithmetic is ever un-refused, this is the second place
            # to revisit.
            #
            # BUT THE TOKEN MUST ALSO LOOK LIKE A DATE COMPONENT, and the first cut of this
            # rule left that out. `raw="Founded 2025; 50 employees"` with `value=50` is a
            # headcount recorded as a date, and it passed because 50 is printed. The cost
            # was not the "computes nothing" this was first defended with: measured, adding
            # that one row flipped a reconciliation from `no_figures` to `checked` with
            # `figures_total=2, figures_verified=2`, so a bogus DATE row moves the gate and
            # the founder-facing verified count even though the arithmetic refuses it.
            #
            # A date component is a four-digit year or a small quarter/month ordinal. That
            # keeps both readings of "Q4 2025" — which is what closed the resolution
            # question — and rejects a headcount that happens to share the string.
            # SIGN IS PRESERVED. The token comparison used abs(value), so -2025 passed as
            # a year. There is no negative date.
            allowed = _date_values(raw)
            if allowed is None:
                errors.append(
                    f"{where} raw {raw!r} is not a date expression — record the date's own printed "
                    f"string (a year, FY25, Q4 2025, March 2026, October 4, 2026), not the sentence "
                    f"around it"
                )
            elif value not in allowed:
                printed = ", ".join(f"{v:g}" for v in sorted(allowed)) or "nothing numeric"
                errors.append(f"{where} value {value!r} is not a date the raw {raw!r} states (it states {printed})")
        elif value is not None and isinstance(raw, str):
            is_bps = bps_factor(raw) != 1.0
            if is_bps and unit_kind != "percent":
                # The unit-kind error above already says what to fix; a scale-disagreement
                # message here would only restate it in a vocabulary the figure is not in.
                continue
            parsed = _parsed_magnitude(raw)
            rng = parse_range(raw)
            if rng is not None:
                # EITHER END, AND NO OTHER NUMBER. This REPLACES the first-token test for a raw
                # that states a range: reconcile reads every range from its low end, so either
                # printed end is a safe recording, and anything else (a number printed before the
                # range, a value between its ends, a scale slip) is refused. The window is the
                # range's own precision, read from its first end (not the raw's first number,
                # which in "5 of 37-41" is not an end) and applied to both: right within rounding,
                # since the two ends are printed to the same place.
                span_text = _RANGE_RE.search(numeral_form(raw))
                precision = _precision(span_text.group(0) if span_text else raw)
                relative = min(precision[0] / precision[1], CAP) if precision and precision[1] else 0.0
                if not any(_reads_as(abs(value), end, relative) for end in rng):
                    if is_bps:
                        errors.append(
                            f"{where} value {value!r} disagrees with raw {raw!r}, a basis-point range — "
                            f"{_bps_remedy(raw)}"
                        )
                    elif _ambiguous_suffix(raw, value, unit_kind, fig.get("currency")):
                        errors.append(_ambiguous_message(where, raw, parsed, value))
                    else:
                        ends = [e for e in rng if e] or [0.0]
                        nearest = min(ends, key=lambda e: abs(abs(value) - e))
                        ratio = abs(value) / nearest if nearest else 0
                        sentence = (
                            f"a range is recorded as either of its two numbers: record "
                            f"{_printed(rng[0])} or {_printed(rng[1])}"
                        )
                        # A value that is the number printed BESIDE the range ("$1.2M (FY2024-2026)"
                        # recorded as 1,200,000) is no slip: the range is probably not the figure, and
                        # "full scale" would invite recording a year. Say what to fix instead.
                        own = _precision(raw)
                        own_rel = min(own[0] / own[1], CAP) if own and own[1] else 0.0
                        beside = (
                            parsed is not None
                            and not any(_reads_as(parsed, end, 1e-9) for end in rng)
                            and _reads_as(abs(value), parsed, own_rel)
                        )
                        # The slide prints two numbers, so "the number the slide prints" does not
                        # say which; the range sentence does, after the rescale for a slip.
                        slip = not beside and (ratio <= 0 or abs(math.log10(ratio)) >= 1)
                        remedy = f"record the figure at full scale; {sentence}" if slip else sentence
                        if beside:
                            remedy += "; if the range is not this figure, make raw the figure's own printed string"
                        errors.append(
                            f"{where} value {value!r} disagrees with raw {raw!r}, a range from "
                            f"{_printed(rng[0])} to {_printed(rng[1])} — {remedy}"
                        )
            elif parsed == 0:
                # ZERO NEEDS AN ABSOLUTE COMPARISON, NOT A SKIPPED ONE. The guard used to be
                # `parsed is not None and parsed != 0`, so a zero `raw` bypassed the whole
                # check: `raw="$0"` with `value=100` validated. The relative test is
                # undefined at zero, which is a reason to compare differently, not a reason
                # to stop comparing — and `raw="about $0"` re-opens the tolerance-widening
                # path from the other end.
                if abs(value) > 1e-9:
                    errors.append(
                        f"{where} raw {raw!r} reads as zero but value is {value!r} — record the figure the slide prints"
                    )
            elif parsed is not None:
                observed = abs(value)
                # Tolerance from the raw string's OWN significant figures, capped at CAP.
                # "$1.2M" claims two figures and covers 1.15M-1.25M; "$1,238,400" claims
                # seven and covers almost nothing. One constant cannot serve both. The cap
                # stops a round number over-claiming ("10" is not +/-5), and there is no
                # implied-tolerance floor under it (see SIGFIG_ONLY for why).
                precision = _precision(raw)
                relative = min(precision[0] / precision[1], CAP) if precision and precision[1] else 0.0
                if observed == 0 or abs(observed - parsed) / parsed > relative:
                    ratio = observed / parsed if parsed else 0
                    if is_bps:
                        # A BASIS POINT IS NOT A SCALE SLIP TOLD TO RESCALE. The 100x gap
                        # here is exactly the notation's own, so name the percent the raw
                        # states instead of asking the model to infer it from "full scale".
                        errors.append(f"{where} value {value!r} disagrees with raw {raw!r}: {_bps_remedy(raw)}")
                    elif _ambiguous_suffix(raw, value, unit_kind, fig.get("currency")):
                        # NOT a scale error, and the usual advice would make it one. A real
                        # deck stated tower heights as "200-400m" and the model recorded 200
                        # with a label saying "(metres)" -- correct, and "record at full
                        # scale" would have pushed it to 200,000,000.
                        #
                        # The code cannot resolve this: "32.5m businesses" recorded as 32.5
                        # (a genuine scale error) is structurally IDENTICAL to "200-400m"
                        # metres recorded as 200. `value == mantissa` holds for both. The
                        # disambiguating fact lives on the slide, so the model has to state
                        # it -- and the existing word-boundary guard already reads the
                        # spelled-out form correctly ("200-400 metres" -> 200). Note a bare
                        # space does NOT help: "200-400 m" still parses as millions.
                        errors.append(_ambiguous_message(where, raw, parsed, value))
                    else:
                        # A scale slip is a power of ten (1000x, a percent as a fraction);
                        # anything closer is a wrong reading, and "record the figure at full
                        # scale" asks a model that wrote 12 or 30 for "10" to make a correction
                        # it cannot make. A range never reaches here (its branch is above).
                        scale_slip = ratio <= 0 or abs(math.log10(ratio)) >= 1
                        if scale_slip:
                            remedy = "record the figure at full scale"
                        else:
                            remedy = (
                                "record the number the slide prints, or, if this figure is printed "
                                "elsewhere more precisely, use that string as raw"
                            )
                        errors.append(
                            f"{where} value {value!r} disagrees with raw {raw!r}, which reads as "
                            f"{parsed:,.4g} (ratio {ratio:,.4g}) — {remedy}"
                        )

    return errors, warnings


def _print_slides(path: str) -> int:
    """Print the distinct slide numbers a ledger covers, ascending, as one comma-joined line.

    Step 3.6 has to tell the second reader WHICH slides to transcribe, and the numbers are not
    figures: the ledger itself must never reach that sub-agent, but the slide list is what
    scopes its read. Reading the ledger in the main thread and hand-copying the numbers is the
    step this replaces — the parse is the same one `validate_ledger` does, so the scope cannot
    drift from the artifact the arithmetic consumes.

    Writes only the one line to stdout; every failure (missing, unreadable, non-JSON, no slide
    numbers at all) is a stderr-only refusal with a non-zero exit, so the caller never mistakes
    an error for an empty list.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: could not read ledger {path!r}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("Error: ledger JSON must be an object", file=sys.stderr)
        return 1
    figures = data.get("figures")
    if not isinstance(figures, list):
        print("Error: ledger has no 'figures' array", file=sys.stderr)
        return 1
    slides: set[int] = set()
    for fig in figures:
        if isinstance(fig, dict) and isinstance(fig.get("slide"), int) and not isinstance(fig["slide"], bool):
            slides.add(fig["slide"])
    if not slides:
        print("Error: ledger records no slide numbers, so there is nothing to re-read", file=sys.stderr)
        return 1
    print(",".join(str(slide) for slide in sorted(slides)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a deck's extracted numeric ledger.")
    ap.add_argument("--inventory", help="deck_inventory.json; enables the slide-bounds check")
    ap.add_argument("--deck-text", help="deck_text.md; its body hash is recorded in metadata")
    ap.add_argument("--run-id")
    ap.add_argument("-o", "--output")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument(
        "--print-slides",
        metavar="LEDGER",
        help="print the distinct slide numbers a ledger covers, ascending, and exit",
    )
    args = ap.parse_args()

    if args.print_slides is not None:
        # A read-and-print mode writes no artifact, so an output path is a contradiction, not
        # a no-op: refuse rather than silently ignore it.
        if args.output:
            print("Error: --print-slides reads a ledger and writes nothing; drop -o", file=sys.stderr)
            return 2
        return _print_slides(args.print_slides)

    if args.run_id is None:
        # `--run-id` is required only when writing the artifact; kept as argparse's own message
        # so the missing-flag error reads identically to a `required=True` parser.
        ap.error("the following arguments are required: --run-id")

    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    import _out_guard

    _out_guard.refuse_output_onto_input([args.output], script="ledger.py")
    # In a folder that belongs to a run: only that folder's current run, reading only its own files.
    import _run_ref

    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)) if args.output else None,
        args.run_id,
        [args.inventory, args.deck_text],
        noun="review dir",
    )

    if sys.stdin.isatty():
        print("Error: pipe the extracted ledger as JSON via stdin", file=sys.stderr)
        return 1
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON input: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        return 1

    total_slides = None
    if args.inventory:
        try:
            with open(args.inventory, encoding="utf-8") as fh:
                inventory = json.load(fh)
            slides = inventory.get("slides")
            if isinstance(slides, list):
                total_slides = len(slides)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error: could not read inventory: {exc}", file=sys.stderr)
            return 1

    errors, warnings = validate_ledger(data, total_slides)

    if errors:
        # Reject loudly and leave `-o` untouched: an invalid-shaped artifact written
        # through `-o` destroys the prior good one and makes SKILL.md's error branch
        # unreachable.
        rejected: dict[str, Any] = {
            "figures": [],
            "validation": {"status": "invalid", "errors": errors, "warnings": warnings},
        }
        print(json.dumps(rejected, indent=2))
        for err in errors:
            print(f"Error: ledger validation failed: {err}", file=sys.stderr)
        return 1

    deck_text_sha256: str | None = None
    if args.deck_text:
        deck_text_sha256, refusal = _deck_text_file.stamp(args.deck_text, args.run_id)
        if refusal is not None:
            print(json.dumps({"status": "rejected", "code": refusal["code"], "message": refusal["message"]}))
            print(f"Error ({refusal['code']}): {refusal['message']}; nothing was written", file=sys.stderr)
            return 1

    result: dict[str, Any] = {
        "figures": data["figures"],
        "figures_total": len(data["figures"]),
        "validation": {"status": "valid", "errors": [], "warnings": warnings},
    }
    if deck_text_sha256 is not None:
        result.setdefault("metadata", {})["deck_text_sha256"] = deck_text_sha256

    if args.output:
        schema_path = pathlib.Path(__file__).resolve().parents[1] / "references" / "schemas" / "ledger.schema.json"
        receipt = write_artifact(
            data=result,
            schema=load_schema(str(schema_path)),
            run_id=args.run_id,
            output_path=args.output,
            pretty=True,
        )
        print(json.dumps(receipt, indent=2))
        return 0

    result.setdefault("metadata", {})["run_id"] = args.run_id
    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
