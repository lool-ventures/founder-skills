#!/usr/bin/env python3
"""`ledger.py` — the extraction-side validation of the deck's numeric ledger.

The checks worth testing are the ones that catch a plausible-looking ledger, not the ones
that catch garbage. A missing key is obvious; a figure recorded as 493 when the slide says
"$493K" looks completely normal and makes every downstream calculation wrong by a factor
of a thousand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
)
SCRIPT = os.path.join(SCRIPTS, "ledger.py")


def _fig(**over: object) -> dict:
    base = {
        "id": "gmv_2024",
        "value": 493000,
        "raw": "$493K",
        "unit_kind": "money",
        "label": "GMV 2024",
        "slide": 6,
        "quote": "GMV of $493K in 2024",
        "currency": "USD",
        "period": "year",
    }
    base.update(over)
    return base


def _run(payload: dict, extra: list[str] | None = None) -> tuple[int, str, str]:
    res = subprocess.run(
        [sys.executable, SCRIPT, "--run-id", "r1", *(extra or [])],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


def test_accepts_a_well_formed_ledger() -> None:
    rc, out, err = _run({"figures": [_fig(), _fig(id="rev", value=9000, raw="$9K", quote="net revenue of $9K")]})
    assert rc == 0, err
    assert json.loads(out)["validation"]["status"] == "valid"


# ---------------------------------------------------------------------------
# The scale check. `raw` and `value` are two independent statements about the same
# number, so their disagreement is detectable without ever seeing the deck — which is
# what makes this a validation rather than a second opinion.
# ---------------------------------------------------------------------------


def test_rejects_value_a_thousand_times_too_small() -> None:
    rc, _, err = _run({"figures": [_fig(value=493)]})
    assert rc != 0
    assert "full scale" in err


def test_rejects_value_a_thousand_times_too_large() -> None:
    rc, _, err = _run({"figures": [_fig(value=493_000_000)]})
    assert rc != 0
    assert "disagrees with raw" in err


def test_tolerates_the_rounding_a_slide_actually_does() -> None:
    """ "$1.2M" for 1,238,400 is a correct extraction of a rounded slide figure.

    An exact-match rule would reject it, which is why the check has a tolerance at all —
    but the tolerance is far tighter than the error class it guards against.
    """
    rc, _, err = _run({"figures": [_fig(value=1_238_400, raw="$1.2M", quote="$1.2M in bookings")]})
    assert rc == 0, err


def test_scale_check_survives_a_raw_string_with_no_scale_suffix() -> None:
    rc, _, err = _run({"figures": [_fig(id="seats", value=120, raw="120", unit_kind="count", quote="120 seats")]})
    assert rc == 0, err


# ---------------------------------------------------------------------------
# Structural refusals
# ---------------------------------------------------------------------------


def test_rejects_duplicate_ids() -> None:
    """Relations address figures by id, so a duplicate silently redirects an operand."""
    rc, _, err = _run({"figures": [_fig(), _fig(value=9000, raw="$9K", quote="net revenue of $9K")]})
    assert rc != 0
    assert "duplicates id" in err


def test_rejects_a_figure_with_no_quote() -> None:
    """The quote is what the second read is checked against."""
    rc, _, err = _run({"figures": [_fig(quote="")]})
    assert rc != 0
    assert "quote" in err


def test_rejects_an_unknown_unit_kind() -> None:
    rc, _, err = _run({"figures": [_fig(unit_kind="dollars")]})
    assert rc != 0
    assert "unit_kind" in err


def test_rejects_a_slide_past_the_end_of_the_deck() -> None:
    with tempfile.TemporaryDirectory() as d:
        inv = os.path.join(d, "deck_inventory.json")
        with open(inv, "w", encoding="utf-8") as f:
            json.dump({"slides": [{"slide_number": n} for n in range(1, 9)]}, f)
        rc, _, err = _run({"figures": [_fig(slide=42)]}, ["--inventory", inv])
    assert rc != 0
    assert "past the deck's last slide" in err


def test_warns_but_accepts_money_with_no_currency() -> None:
    """A warning, not a refusal: the relation that needs it is refused later, by name."""
    fig = _fig()
    del fig["currency"]
    rc, out, err = _run({"figures": [fig]})
    assert rc == 0, err
    assert any("currency" in w for w in json.loads(out)["validation"]["warnings"])


def test_rejects_a_value_that_drops_precision_the_raw_string_carries() -> None:
    """The deck-H defect: `raw: "16661.2"` recorded as `value: 16661`.

    A 0.0012% discrepancy, invisible to any relative floor — and it does real damage
    downstream. That lost 0.2 moved a sum 0.54 off its stated total against a tolerance of
    0.555, and a founder was told their revenue disagreed with itself by 1 part in 17,772.

    A figure printed to six significant figures is a claim to six significant figures, so
    `value` must match `raw` to `raw`'s own precision and no looser.
    """
    rc, _, err = _run(
        {"figures": [_fig(id="rev_mix", value=16661, raw="16661.2", quote="Subscription revenue 16661.2")]}
    )
    assert rc != 0
    assert "disagrees with raw" in err


def test_an_exact_match_on_a_precise_raw_is_accepted() -> None:
    """The counter-test: the rule must be satisfiable, not merely strict."""
    rc, _, err = _run(
        {"figures": [_fig(id="rev_mix", value=16661.2, raw="16661.2", quote="Subscription revenue 16661.2")]}
    )
    assert rc == 0, err


def test_a_coarse_raw_still_tolerates_the_rounding_it_implies() -> None:
    """Removing the floor must not make a genuinely rounded slide figure a failure.

    "$1.2M" claims two significant figures and legitimately covers 1.15M-1.25M — the
    significant-figure band already expresses that, which is why no floor is needed.
    """
    rc, _, err = _run({"figures": [_fig(value=1_238_400, raw="$1.2M", quote="$1.2M in bookings")]})
    assert rc == 0, err
    rc, _, err = _run({"figures": [_fig(id="c", value=97, raw="100", unit_kind="count", quote="about 100 users")]})
    assert rc == 0, err


def test_a_unit_suffix_is_not_reported_as_a_scale_error() -> None:
    """ "200-400m" of building height, recorded as 200, is CORRECT extraction.

    The old message told the model to "record the figure at full scale", which for a
    200-metre tower means 200,000,000. The code cannot decide this — "32.5m businesses"
    recorded as 32.5 (a genuine scale error) is structurally identical — so it stops
    pretending to and tells the model how to disambiguate instead.
    """
    fig = _fig(
        id="h",
        value=200,
        raw="200-400m",
        unit_kind="count",
        label="tower height range (metres)",
        quote="towers of 200-400m",
    )
    del fig["currency"]  # a height is not money; the default helper supplies one
    rc, _, err = _run({"figures": [fig]})
    assert rc != 0
    assert "ambiguous" in err and "spell it out" in err
    assert "record the figure at full scale" not in err.split("ambiguous")[1]


def test_spelling_the_unit_out_resolves_it() -> None:
    """The escape hatch has to work, or the message sends the model in a circle."""
    fig = _fig(
        id="h",
        value=200,
        raw="200-400 metres",
        unit_kind="count",
        label="tower height range",
        quote="towers of 200-400 metres",
    )
    del fig["currency"]
    rc, _, err = _run({"figures": [fig]})
    assert rc == 0, err


def test_a_currency_marker_still_means_the_suffix_is_a_multiplier() -> None:
    """Money is never ambiguous: "$493K" is thousands, so 493 stays a scale error."""
    rc, _, err = _run({"figures": [_fig(value=493, raw="$493K")]})
    assert rc != 0
    assert "full scale" in err
    assert "ambiguous" not in err


# ---------------------------------------------------------------------------
# Dates. The scale check reads the FIRST numeric token in `raw`, which is the wrong
# token for a date: "Q4 2025" reads as 4, so a correctly-extracted year is rejected as
# a 506x scale error. A date is not a magnitude with a scale — it is one of the tokens
# printed on the slide, and the check has to say so.
# ---------------------------------------------------------------------------


def _date(**over: object) -> dict:
    base = _fig(
        id="founded",
        value=2025,
        raw="Q4 2025",
        unit_kind="date",
        label="target launch",
        quote="Launch in Q4 2025",
    )
    del base["currency"]
    del base["period"]
    base.update(over)
    return base


def test_a_quarter_prefix_no_longer_rejects_a_correctly_extracted_year() -> None:
    """The motivating case. "Q4 2025" recorded as 2025 is right, and was refused."""
    rc, _, err = _run({"figures": [_date()]})
    assert rc == 0, err


def test_a_year_range_accepts_either_printed_endpoint() -> None:
    """ "2024-2030" carries two years; recording the later one is not a scale error."""
    rc, _, err = _run({"figures": [_date(raw="2024-2030", value=2030, quote="2024-2030")]})
    assert rc == 0, err


def test_a_quarter_recorded_as_the_quarter_is_still_accepted() -> None:
    """4 IS a token printed in "Q4 2025". The label is what disambiguates it, and no
    date arithmetic runs (see test_reconcile.py), so admitting both readings is free."""
    rc, _, err = _run({"figures": [_date(value=4, label="launch quarter")]})
    assert rc == 0, err


def test_a_date_value_matching_no_printed_token_is_rejected() -> None:
    """The check still has to catch a fabricated year."""
    rc, _, err = _run({"figures": [_date(value=2019)]})
    assert rc != 0
    assert "2019" in err


def test_a_date_off_by_a_factor_of_ten_is_still_rejected() -> None:
    """The scale-slip class the check exists for does not get an exemption."""
    rc, _, err = _run({"figures": [_date(raw="2024", value=20240, quote="2024")]})
    assert rc != 0


def test_the_date_rule_does_not_leak_into_money() -> None:
    """A money figure whose value equals a later token in raw is still a scale error:
    the token-equality rule is scoped to `date` and nothing else."""
    rc, _, err = _run({"figures": [_fig(value=493, raw="$493K in 2024", quote="$493K in 2024")]})
    assert rc != 0
    assert "full scale" in err


# ---------------------------------------------------------------------------
# Quote shape. The schema calls `quote` "the verbatim sentence or table row the figure was
# read from", and the validator checked only that it was a non-empty string. A quote of
# "$80B" or "2010" satisfies that and identifies nothing: the gate it feeds matches text
# against the second read, so a single token matches wherever that token happens to appear.
#
# This is the class every measured wrong-page verification on the corpus belongs to, and it
# is NOT fixed by checking the claimed slide instead of the whole deck — narrowing the
# haystack does not make a one-token needle identifying. Probed: a quote of "2010" against
# a claimed slide reading "Founded 2010. Team of 12." verifies under both rules.
#
# WARN, never error. 7.5% of a real corpus is too large a population to refuse without a
# migration, and some table rows are legitimately terse.
# ---------------------------------------------------------------------------


def test_a_single_token_quote_is_warned_about_but_accepted() -> None:
    rc, out, err = _run({"figures": [_fig(quote="$493K")]})
    assert rc == 0, err
    warnings = json.loads(out)["validation"]["warnings"]
    assert any("quote" in w for w in warnings), f"no quote-shape warning: {warnings}"


def test_a_quote_with_no_real_word_is_warned_about() -> None:
    """ "63.5% | $635K" is a table row with the row's own name stripped off — the part that
    would have made it identifying."""
    rc, out, err = _run({"figures": [_fig(quote="63.5% | $635K")]})
    assert rc == 0, err
    assert any("quote" in w for w in json.loads(out)["validation"]["warnings"])


def test_a_verbatim_sentence_is_not_warned_about() -> None:
    """The counter-test. A real quote must pass silently or the warning is noise."""
    rc, out, err = _run({"figures": [_fig(quote="GMV of $493K in 2024, up from $210K")]})
    assert rc == 0, err
    assert not [w for w in json.loads(out)["validation"]["warnings"] if "quote" in w]


def test_a_terse_but_identifying_table_row_is_not_warned_about() -> None:
    """A table row that keeps its label is exactly what the schema asks for, and it is
    short. The predicate keys on whether the quote carries a WORD, not on its length."""
    rc, out, err = _run({"figures": [_fig(quote="Net revenue $493K")]})
    assert rc == 0, err
    assert not [w for w in json.loads(out)["validation"]["warnings"] if "quote" in w]


def test_a_bad_quote_shape_never_fails_the_ledger() -> None:
    """The whole population would fail. Warn and let the run continue."""
    rc, _, err = _run({"figures": [_fig(quote="$80B"), _fig(id="b", quote="2010", value=2010, raw="2010")]})
    assert rc == 0, err


def test_a_numberless_raw_is_refused_on_a_non_date_figure() -> None:
    """`raw="about"` with `value=100` passed, then read as `approximate` downstream and
    turned `60 + 48 = 108` against a stated 100 from a contradiction into a confirmation.

    `raw` is supposed to be the figure's own printed string. A `raw` with no parseable
    magnitude is not one, and the scale check — the whole reason `raw` is required —
    silently does nothing on it, so the field's one guarantee is absent exactly where it
    is least visible.
    """
    fig = _fig(value=100, raw="about", quote="about one hundred in total")
    rc, _, err = _run({"figures": [fig]})
    assert rc != 0
    assert "about" in err


def test_a_date_still_needs_a_number_in_its_raw() -> None:
    """`raw="TBD"` with `value=2025` passed: the token list is empty, and the date rule
    only compares against tokens that exist. An empty list is not agreement."""
    rc, _, err = _run({"figures": [_date(raw="TBD", value=2025, quote="launch TBD")]})
    assert rc != 0


def test_a_real_figure_with_a_parseable_raw_is_untouched() -> None:
    """The counter-test — every legitimate shape still passes."""
    for raw, value, kind in (("$493K", 493000, "money"), ("2024", 2024, "date"), ("18 months", 18, "duration")):
        fig = _fig(value=value, raw=raw, unit_kind=kind, quote=f"the figure is {raw}")
        if kind != "money":
            fig.pop("currency", None)
        rc, _, err = _run({"figures": [fig]})
        assert rc == 0, f"{raw!r} rejected: {err}"


def test_a_raw_of_zero_does_not_bypass_the_scale_check() -> None:
    """The scale check ran only `if parsed != 0`, so a zero `raw` skipped it entirely.

    `raw="$0"` with `value=100` validated. Worse in combination: `raw="about $0"` also
    reads as an approximation now that a word needs a number beside it, which re-opens the
    contradiction-suppression path from the other end. Zero needs an absolute comparison,
    not a skipped one — the one figure where a relative test is undefined is exactly the
    one where it must not be silently dropped.
    """
    fig = _fig(value=100, raw="$0", quote="total of $0 here")
    rc, _, err = _run({"figures": [fig]})
    assert rc != 0, "raw='$0' with value=100 validated"

    fig2 = _fig(value=100, raw="about $0", quote="about $0 in total")
    rc2, _, _ = _run({"figures": [fig2]})
    assert rc2 != 0


def test_a_genuine_zero_still_validates() -> None:
    """The counter-test: 18 corpus figures are zero and one is an operand of a live
    contradiction, so zero itself must stay legal."""
    rc, _, err = _run({"figures": [_fig(value=0, raw="$0", quote="net loss of $0")]})
    assert rc == 0, err


def test_a_date_value_must_look_like_a_date_component() -> None:
    """A headcount recorded as a date passed, and the blast radius was not "computes
    nothing" as previously claimed.

    Measured: `raw="Founded 2025; 50 employees"`, `value=50`, `unit_kind=date` validated,
    and adding that one row flipped a reconciliation from `no_figures` to `checked` with
    `figures_total=2, figures_verified=2`. DATE rows are refused by the ARITHMETIC but
    still count toward the gate and the founder-facing verified count.

    The rule stays permissive about WHICH token — that is what closed F2's resolution
    question, and both readings of "Q4 2025" are still legal — but a date component is
    either a four-digit year or a small quarter/month ordinal. 50 is neither.
    """
    rc, _, err = _run({"figures": [_date(raw="Founded 2025; 50 employees", value=50, label="founding year")]})
    assert rc != 0, "a headcount validated as a date"

    # Both readings of a quarter-prefixed year remain legal.
    for value in (2025, 4):
        rc_ok, _, err_ok = _run({"figures": [_date(value=value)]})
        assert rc_ok == 0, f"{value} rejected: {err_ok}"
    # And a plain year range.
    rc_r, _, err_r = _run({"figures": [_date(raw="2024-2030", value=2030, quote="2024-2030")]})
    assert rc_r == 0, err_r


def test_a_date_binds_to_date_syntax_not_to_a_value_range() -> None:
    """The range heuristic narrowed the example and left the misbinding.

    `1-12 or 1000-9999` accepts any printed token in those ranges, so a headcount still
    masqueraded as a date whenever it happened to fall in one — `"Founded 2025; 12
    employees"` recorded as 12, and `"Founded 2025; 3000 employees"` as 3000. It also
    compared `abs(value)`, so -2025 passed, and it made the years decks actually print —
    `FY25`, `Q4 '25` — unrepresentable.

    Bind to the SYNTAX instead: the value must be a year the raw prints as four digits, or
    a quarter/month the raw marks as one.
    """
    for value in (12, 3000):
        rc, _, _ = _run(
            {"figures": [_date(raw=f"Founded 2025; {value} employees", value=value, label="founding year")]}
        )
        assert rc != 0, f"a headcount of {value} validated as a date"

    rc_neg, _, _ = _run({"figures": [_date(raw="2025", value=-2025, quote="2025")]})
    assert rc_neg != 0, "a negative year validated"


def test_the_year_forms_decks_actually_print_are_representable() -> None:
    for raw, value in (("FY25", 25), ("Q4 '25", 25), ("Q4 2025", 2025), ("Q4 2025", 4), ("2024-2030", 2030)):
        rc, _, err = _run({"figures": [_date(raw=raw, value=value, quote=f"target {raw}")]})
        assert rc == 0, f"{raw!r}/{value} rejected: {err}"


def test_date_syntax_does_not_scan_arbitrary_prose() -> None:
    """The syntax rule was a SUBSTRING scan, so ordinary prose produced date components.

    `Maybe 5 employees` matched the month pattern on the "M" of "Maybe"; `Marching with 3`
    matched "March"; `Unify25 users` matched `FY25`; and any four-digit quantity in
    1900-2100 became a year, so `Founded 2025; 2000 employees` still admitted 2000. Each
    bogus DATE row then inflates `figures_total`, `figures_verified` and the checked gate.

    A marker only marks a date when it stands as its own token.
    """
    for raw, value in (
        ("Founded 2025; 2000 employees", 2000),
        ("Maybe 5 employees", 5),
        ("Marching with 3 employees", 3),
        ("Unify25 users", 25),
    ):
        rc, _, _ = _run({"figures": [_date(raw=raw, value=value, label="x", quote=raw)]})
        assert rc != 0, f"{raw!r} admitted {value} as a date"


def test_real_date_syntax_still_parses() -> None:
    for raw, value in (
        ("Q4 2025", 2025),
        ("Q4 2025", 4),
        ("FY25", 25),
        ("Q4 '25", 25),
        ("2024-2030", 2030),
        ("March 2026", 3),
        ("March 2026", 2026),
        ("Founded 2025", 2025),
    ):
        rc, _, err = _run({"figures": [_date(raw=raw, value=value, quote=f"as of {raw}")]})
        assert rc == 0, f"{raw!r}/{value} rejected: {err}"


def test_a_date_raw_must_be_a_date_expression_not_prose_containing_one() -> None:
    """Fourth attempt at this, and the previous three all narrowed examples.

    Substring inference cannot decide what a number MEANS: any isolated 1900-2100 token
    became a year, so `Headcount 2000` and `Revenue $2000` validated as dates and inflated
    the verified count. The same boundaries rejected ordinary punctuation (`Founded 2025.`)
    while accepting `FY25users` and `Q4ever`.

    A `date` raw must therefore BE a date expression, not prose that contains one.
    """
    for raw, value in (("Headcount 2000", 2000), ("Revenue $2000", 2000), ("FY25users", 25), ("Q4ever", 4)):
        rc, _, _ = _run({"figures": [_date(raw=raw, value=value, label="x", quote=raw)]})
        assert rc != 0, f"{raw!r} validated as a date"


def test_real_date_expressions_including_trailing_punctuation() -> None:
    for raw, value in (
        ("2025", 2025),
        ("Founded 2025", 2025),
        ("Founded 2025.", 2025),
        ("FY25", 25),
        ("FY25.", 25),
        ("Q4 2025", 4),
        ("Q4 2025", 2025),
        ("Q4.", 4),
        ("Q4 '25", 25),
        ("2024-2030", 2024),
        ("2024-2030", 2030),
        ("March 2026", 3),
        ("March 2026", 2026),
        ("in Q1 2027", 2027),
    ):
        rc, _, err = _run({"figures": [_date(raw=raw, value=value, quote=f"as of {raw}")]})
        assert rc == 0, f"{raw!r}/{value} rejected: {err}"


def test_the_scale_forms_the_quote_grammar_knows_are_the_ones_the_ledger_validates() -> None:
    """ "One grammar" was claimed and was still false for three forms.

    The quote lexeme learned `crore`, `lakh` and `×10⁶` so a figure would stop inheriting a
    larger number's approximation; `_parsed_magnitude` — the authoritative parser the ledger
    validates against — did not. Measured: `raw="$20 crore"` with the CORRECT value
    200,000,000 was rejected while the wrong 20 was accepted, and the same for `$20×10⁶`.
    Every one of those is the direction that admits a scale error.
    """
    for raw, correct in (("$20 crore", 200_000_000), ("$2 lakh", 200_000), ("$20×10⁶", 20_000_000)):
        fig = _fig(value=correct, raw=raw, quote=f"total of {raw}")
        rc, _, err = _run({"figures": [fig]})
        assert rc == 0, f"{raw!r} with its correct value {correct} was rejected: {err}"

        wrong = _fig(value=20, raw=raw, quote=f"total of {raw}")
        rc_wrong, _, _ = _run({"figures": [wrong]})
        assert rc_wrong != 0, f"{raw!r} accepted a bare mantissa as its value"


def test_every_numeric_form_the_quote_grammar_knows_is_one_the_ledger_validates() -> None:
    """Third attempt, and the point of this one is that the grammars now SHARE their pieces.

    Previous rounds fixed the named forms and left the next: `MM/Mn/bn`, then `crore/lakh`,
    then `$20e6`, space-grouped `$20 000`, and ranges with a shared suffix (`$20-30MM`).
    Four independent regexes — `_NUM_RE`, `_RANGE_RE`, `_PLUS_RE`, `_NUMERIC_LEXEME` — each
    knew a different subset, and every mismatch admitted a scale error: the CORRECT value
    rejected, the bare mantissa accepted.

    They are built from shared constants now, so a form one recognises cannot be a form
    another does not.
    """
    for raw, correct in (
        ("$20e6", 20_000_000),
        ("$20 000", 20_000),
        ("$20-30MM", 20_000_000),
        ("$20–30 crore", 200_000_000),
        ("$20 lac", 2_000_000),
        ("$20MM", 20_000_000),
        ("$20 crore", 200_000_000),
        ("$20×10⁶", 20_000_000),
    ):
        fig = _fig(value=correct, raw=raw, quote=f"total of {raw}")
        rc, _, err = _run({"figures": [fig]})
        assert rc == 0, f"{raw!r} with its correct value {correct} was rejected: {err}"

        bare = _fig(value=20, raw=raw, quote=f"total of {raw}")
        rc_bare, _, _ = _run({"figures": [bare]})
        assert rc_bare != 0, f"{raw!r} accepted a bare mantissa of 20 as its value"
