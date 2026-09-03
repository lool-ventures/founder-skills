#!/usr/bin/env python3
"""Pin the comparison rules in reconcile.py against the real cases that exposed them.

Every case here is a line that actually appeared in a run over the corpus, not a
constructed example. That matters most for the three decisions in `operand_tolerance`,
`_is_exact_count` and the multiplicative no-propagation rule: each is a judgement call
where the opposite choice is defensible in the abstract and wrong against the data, so
each has a test whose failure re-opens the argument with the evidence attached.

Run: uv run pytest founder-skills/tests/test_reconcile.py -q
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

HERE = pathlib.Path(__file__).parent
SCRIPTS = HERE.parent / "skills" / "deck-review" / "scripts"
sys.path[:0] = [str(SCRIPTS)]

from reconcile import (  # type: ignore[import-not-found]  # noqa: E402
    CAP,
    GROWTH_CONVENTION_OFFSET,
    Figure,
    Relation,
    _is_exact_count,
    _raw_scale,
    _scale_divergent,
    _stated,
    compute,
    detect_bound,
    figure_tolerance,
    implied_tolerance,
    is_visible,
    merge_range_twins,
    operand_tolerance,
    parse_range,
    quote_is_identifying,
    select,
)


def fig(raw: str, value: float, unit_kind: str = "money", label: str = "", **kw: Any) -> Figure:
    kw.setdefault("verified", True)
    lo_hi = parse_range(raw)
    return Figure(
        id=kw.pop("id", "f1"),
        value=value,
        raw=raw,
        unit_kind=unit_kind,
        label=label,
        slide=1,
        # Overridable: the N1 time guard reads a figure's own quote for a date token, so a
        # test for it cannot use a fixed empty string.
        quote=kw.pop("quote", ""),
        bound=kw.pop("bound", detect_bound(raw, label)),
        **(dict(zip(("lo", "hi"), lo_hi, strict=True)) if lo_hi else {}),
        **kw,
    )


# --------------------------------------------------------------------------
# Defect 5 -- the suffix mis-parse that produced a false CONFIRMATION.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("18 months", 0.5),  # was 500,000: the "m" of "months" read as mega
        ("12 Bookings", 0.5),  # was 5e8
        ("1 million", 500_000.0),  # word form must still work
        ("$48 billion", 5e8),  # worked only by accident before; must still work
        ("$5.7 trillion", 5e10),  # never handled at all before
        ("$150-250K", 500.0),  # was 0.5: the suffix binds to the far endpoint
        ("$8M", 500_000.0),
        ("$115k", 500.0),
    ],
)
def test_written_precision_parses_scale(raw: str, expected: float) -> None:
    assert implied_tolerance(raw) == pytest.approx(expected)


def test_a_figure_can_always_contradict_something() -> None:
    """30 corpus figures had a tolerance larger than their own value and could not."""
    for raw, value in [("18 months", 18), ("12 Bookings", 12), ("1000X", 1000)]:
        assert figure_tolerance(fig(raw, value, "multiple")) < abs(value)


# --------------------------------------------------------------------------
# Stated-side tolerance: relative, capped, floored, in value space.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "value", "unit", "expected"),
    [
        ("1,700", 1700, "count", 50.0),  # trailing zeros are not significant
        ("$1,696", 1696, "money", 0.5),  # four significant figures
        # ... but the SAME digits as a count are exact, because a count does not round.
        # Both readings are live in the corpus, so both are pinned here.
        ("1,696", 1696, "count", 0.0),
        ("200", 200, "count", 10.0),  # sig-figs say 50; the CAP binds
        ("20%", 20, "percent", 1.0),  # sig-figs say 5, which would be absurd
        ("$115k", 115_000, "money", 500.0),  # the flagship's yardstick
        ("(856)", -856_000, "money", 500.0),  # value space, via a table scale never parsed
        ("$1,000,000", 1_000_000, "money", 50_000.0),  # CAP binds; sig-figs would say 500,000
        ("$8M", 8_000_000, "money", 500_000.0),  # the FLOOR binds; 5% would be 400,000
    ],
)
def test_figure_tolerance(raw: str, value: float, unit: str, expected: float) -> None:
    assert figure_tolerance(fig(raw, value, unit)) == pytest.approx(expected)


def test_tolerance_is_never_negative_and_zero_is_exact() -> None:
    # 32 corpus figures are negative; a negative tolerance inverts the acceptance window.
    assert figure_tolerance(fig("(19,391)", -19_391_000)) > 0
    # 18 are zero, and one is an operand of a live contradiction.
    assert figure_tolerance(fig("0", 0, "count")) == 0.0


def test_the_cap_never_tightens_the_shipped_behaviour() -> None:
    """133 corpus figures are single-digit-mantissa, where a bare 5% cap is TIGHTER."""
    for raw, value in [("$8M", 8e6), ("$1B", 1e9), ("$5M", 5e6)]:
        assert figure_tolerance(fig(raw, value)) >= implied_tolerance(raw)


def test_cap_constant_is_the_documented_choice() -> None:
    assert CAP == 0.05


# --------------------------------------------------------------------------
# Counts. The rule that keeps two real headcount findings alive.
# --------------------------------------------------------------------------


def test_units_place_counts_are_exact_but_round_ones_are_not() -> None:
    assert _is_exact_count(fig("5", 5, "count"))
    assert _is_exact_count(fig("12", 12, "count"))
    assert not _is_exact_count(fig("200", 200, "count"))  # plainly rounded
    assert not _is_exact_count(fig("2,000", 2000, "count"))
    assert not _is_exact_count(fig("$5M", 5e6, "money"))  # not a count at all


def test_headcount_sum_survives_propagation() -> None:
    """deck-A: 0+1+4+0+0+0+1 = 6 against a stated 5. The gap is exactly 1.

    Give each of seven integer operands even the legacy +/-0.5 and propagation opens a
    window of 3.5 that swallows a true finding.
    """
    ops = [fig(str(v), v, "count", id=f"f{i}") for i, v in enumerate([0, 1, 4, 0, 0, 0, 1])]
    window = operand_tolerance("sum", ops) + figure_tolerance(fig("5", 5, "count"))
    assert window < 1.0


# --------------------------------------------------------------------------
# The propagation split. Each half has a real case that breaks under the other choice.
# --------------------------------------------------------------------------


def test_sums_propagate_so_rounded_components_do_not_contradict() -> None:
    """deck-D: eight cells each rounded to the nearest thousand, gap 2,000 on 19.4M."""
    cells = [
        (856, "f1"),
        (1679, "f2"),
        (1711, "f3"),
        (2025, "f4"),
        (2334, "f5"),
        (2724, "f6"),
        (3712, "f7"),
        (4352, "f8"),
    ]
    ops = [fig(f"({v:,})", -v * 1000, "money", id=i) for v, i in cells]
    window = operand_tolerance("sum", ops) + figure_tolerance(fig("(19,391)", -19_391_000))
    assert window >= 2000.0


def test_multiplicative_relations_do_not_propagate() -> None:
    """The flagship. Propagate here and $100k+20% spans 109,250-131,250, which contains
    the deck's stated $115k -- destroying the finding the module exists to catch."""
    base, pct = fig("$100k/month", 100_000), fig("20%", 20, "percent", id="f2")
    assert operand_tolerance("increase_by", [base, pct]) == 0.0
    assert operand_tolerance("product", [base, pct]) == 0.0
    assert operand_tolerance("ratio", [base, pct]) == 0.0
    # and the surviving yardstick still separates 120,000 from a stated 115,000
    assert abs(120_000 - 115_000) > figure_tolerance(fig("$115k/month", 115_000))


# --------------------------------------------------------------------------
# Bounds.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "label", "expected"),
    [
        ("$200B+", "", "at_least"),
        ("270+ sites", "", "at_least"),
        ("100%+", "", "at_least"),
        ("+76%", "", None),  # a LEADING + is a delta sign, not a bound
        ("< 1-2%", "", "at_most"),
        ("> $40M", "", "at_least"),  # note the space after the operator
        ("2,000", "tall buildings (>200m) existing worldwide (fewer than)", "at_most"),
        ("20+", "global patents targeted (minimum)", "at_least"),
        ("~3.5%", "", "approximate"),
        ("≈20", "", "approximate"),  # U+2248, same standing as the ASCII tilde
        ("20", "estimated market size", "approximate"),  # a WORD in the label still binds
        ("1,700", "trial signups per month", None),
    ],
)
def test_detect_bound(raw: str, label: str, expected: str | None) -> None:
    assert detect_bound(raw, label) == expected


def test_an_approximation_symbol_in_the_label_is_never_read_as_a_bound() -> None:
    """Same rule as `>200m`, on the approximate path: symbols come from `raw` ONLY.

    A label's glyph routinely qualifies a different number than the one the figure holds.
    Reading it as an approximation marker widens the stated figure's tolerance to
    `APPROX_WIDENING` (10%) at `reconcile.py:426`, on a figure nobody marked approximate.

    Note the mechanism, which an earlier version of this docstring got wrong: `approximate`
    does NOT make the comparison one-sided. Only `at_least` and `at_most` do that
    (`reconcile.py:1190-1193`); `approximate` falls to the two-sided branch with a wider
    `tol`. The suppress-only conclusion still holds, for a different reason -- a larger
    tolerance can only make `disjoint` false, never true -- so the sole effect is to erase
    a contradiction.
    """
    assert detect_bound("108", "sum vs the 2024 ≈ 20 chart") is None
    assert detect_bound("108", "vs ~200 units on the other axis") is None
    # Same rule inside `raw`: the glyph must precede THIS figure's number.
    assert detect_bound("$100 vs 2024 ≈ 20", "") is None
    assert detect_bound("2024 ≈ 20", "") is None
    # ...and there must be a number for it to qualify. `ledger.py` accepts a numberless
    # `raw` (it skips the scale check when the magnitude will not parse), so without this
    # a bare glyph would mark a figure approximate off nothing at all.
    assert detect_bound("≈", "") is None
    # The prefix search shares `_NUM_RE`'s Unicode digit grammar, not an ASCII class.
    assert detect_bound("≈١٠", "") == "approximate"
    # The word form in a label is still legitimate, and still binds.
    assert detect_bound("108", "approximate total") == "approximate"
    # And the symbol in `raw` — where it does qualify this figure — still binds.
    assert detect_bound("≈108", "") == "approximate"


def test_a_label_glyph_cannot_turn_a_contradiction_into_a_confirmation() -> None:
    """End-to-end: the harm the rule above prevents, at the verdict level.

    60 + 48 = 108 against a stated 100 is a contradiction. Before symbols were split out of
    the label search, an unrelated `≈` in the stated figure's label widened its tolerance to
    10% and the same relation came back `confirmation`.
    """
    ops = [fig("$60.00", 60.0, id="a"), fig("$48.00", 48.0, id="b")]
    stated = fig("$100.00", 100.0, label="total vs the 2024 ≈ 20 chart", id="t")
    by_id = {f.id: f for f in [*ops, stated]}
    rel = compute(
        {"kind": "derived_ratio", "operator": "sum", "operands": ["a", "b"], "expected_id": "t"},
        by_id,
    )
    assert stated.bound is None, "an unrelated label glyph must not mark the figure approximate"
    assert rel.verdict == "contradiction", f"expected contradiction, got {rel.verdict}"


def test_a_bare_raw_and_label_still_read_no_bound_without_the_quote() -> None:
    """`raw` and `label` alone reach none of the figures that motivated the glyph.

    Measured on one live ledger: `≈` appeared in 0 of 81 `raw` values and 7 quotes, so a deck
    printing a bare bar value and marking it approximate in the surrounding sentence got no
    bound from these two fields — which is why adding the glyph to the symbol pattern closed
    nothing on its own.

    That gap is now closed by reading the quote under a stricter binding (see the N8 block
    below), and this test keeps the underlying property honest: the two-argument call still
    reads nothing, so the coverage comes from the quote and not from a widened `raw` rule.
    """
    assert detect_bound("$20B", "Computer vision market 2024") is None


def test_a_symbol_in_the_label_is_never_read_as_a_bound() -> None:
    """That label's ">200m" is a building-height threshold, not a bound on the count."""
    assert detect_bound("1,500", "buildings over 200m tall") == "at_least"  # the WORD does bind
    assert detect_bound("1,500", "tall buildings (>200m) worldwide") is None


def test_contradictory_signals_fall_back_to_the_two_sided_test() -> None:
    assert detect_bound("$200B+", "up to the total market") is None


def test_approximate_widens_beyond_the_cap() -> None:
    approx, exact = fig("~3.5%", 3.5, "percent"), fig("3.5%", 3.5, "percent", bound=None)
    assert figure_tolerance(approx) > figure_tolerance(exact)
    assert figure_tolerance(approx) == pytest.approx(0.35)


def test_a_bounded_figure_never_produces_inf_or_nan() -> None:
    """Modelling a floor as hi=+inf yields inf/inf = nan in a ratio, every nan comparison
    is False, and the relation renders 'matches the stated ...' -- a false confirmation."""
    f = fig("$200B+", 200e9)
    lo, hi = f.span()
    assert all(abs(x) != float("inf") for x in (lo, hi))


# --------------------------------------------------------------------------
# Rendering, and the backstop guard.
# --------------------------------------------------------------------------


def test_stated_side_is_expanded_when_it_diverges_from_its_value() -> None:
    assert _stated(fig("(19,391)", -19_391_000)) == "(19,391) (= -19,391,000)"
    assert _stated(fig("$115k", 115_000)) == "$115k"  # no divergence, no noise


@pytest.mark.parametrize(
    ("computed", "stated", "fires"),
    [
        (19_393_000, 19_391, True),  # the class the guard exists for
        (857_000, 856, True),
        (1.005, 1.0, False),  # a near-exact agreement must never be refused
        (10_000, 1_000, False),  # exactly 10x: a live true finding, must stay a contradiction
        (100, 1, False),  # 100x is more likely a real error than a units convention
        (0, 5, False),  # zero on either side
    ],
)
def test_scale_divergence_backstop(computed: float, stated: float, fires: bool) -> None:
    assert _scale_divergent(computed, stated) is fires


# --------------------------------------------------------------------------
# Visibility. A finding may only say "the deck states" about a number a reader sees.
# --------------------------------------------------------------------------


def test_chart_series_data_is_not_visible() -> None:
    """Measured on the corpus .pptx: 351 of 477 figures are chart series with no data
    labels shown. The deck plots them; it does not state them."""
    assert not is_visible("series G&A: Q3 23=1370.1, Q4 23=1402.07")
    assert is_visible("ARR at End of Period | 15,614 |  | 19,089")  # a table cell is on the slide
    assert is_visible("Revenue grew to $17.8m in 2024")  # so is body text
    assert is_visible("")  # absent quote must not be treated as hidden


def test_pdf_figures_are_visible_by_construction() -> None:
    """A PDF figure was read off a rendered page, so a reader can see it too."""
    assert fig("$115k", 115_000).visible


def test_difference_of_percents_stays_in_percent_space() -> None:
    """29% - 7% is 22%, not 0.22. The guard existed in `sum` and was missing here, so a
    deck that agreed with itself was reported as contradicting itself."""
    a, b = fig("29%", 29, "percent", id="f1"), fig("7%", 7, "percent", id="f2")
    r = compute({"operator": "difference", "operands": ["f1", "f2"], "kind": "contradiction"}, {"f1": a, "f2": b})
    assert r.computed == pytest.approx(22.0)


# --------------------------------------------------------------------------
# Durations divide only in a common time unit.
# --------------------------------------------------------------------------


def test_durations_convert_before_dividing() -> None:
    """A live false finding: "120 min / 20 sec = 6.00x — but the deck states 360x".

    The deck was RIGHT — 120 minutes over 20 seconds IS 360x — and the tool told a founder
    their correct claim contradicted itself. The magnitude lives in `value` and the unit
    only in the raw string, so a bare division is a category error.
    """
    num = fig("120 min", 120, "duration", id="f1")
    den = fig("20 sec", 20, "duration", id="f2")
    r = compute({"operator": "ratio", "operands": ["f1", "f2"], "kind": "derived_ratio"}, {"f1": num, "f2": den})
    assert not r.dropped, r.reasons
    assert r.computed == pytest.approx(360.0)


def test_same_unit_durations_are_unaffected() -> None:
    a, b = fig("18 months", 18, "duration", id="f1"), fig("6 months", 6, "duration", id="f2")
    r = compute({"operator": "ratio", "operands": ["f1", "f2"], "kind": "derived_ratio"}, {"f1": a, "f2": b})
    assert r.computed == pytest.approx(3.0)


def test_unlabelled_duration_is_refused_not_guessed() -> None:
    """An unlabelled duration is not comparable to a labelled one. Guessing a unit would
    reinstate the same class of error at a different magnitude, so refuse instead."""
    a, b = fig("120", 120, "duration", id="f1"), fig("20 sec", 20, "duration", id="f2")
    r = compute({"operator": "ratio", "operands": ["f1", "f2"], "kind": "derived_ratio"}, {"f1": a, "f2": b})
    assert r.dropped and "without units" in " ".join(r.reasons)


def test_endpoints_written_as_two_figures_merge_into_one_range() -> None:
    """The deck said "$1k - $10k"; the ledger kept two rows and the comparison used only
    the low one, so a computed 10,000 INSIDE the stated range was reported as contradicting
    it. The domain expert caught this and declined to give the finding any verdict.

    The first merge pass keys on an identical raw string, so two rows with different raws
    are invisible to it however plainly their labels pair them.
    """
    lo = fig("$1k", 1000, "money", label="net per customer per month (low end)", id="f1")
    hi = fig("$10k", 10000, "money", label="net per customer per month (high end)", id="f2")
    kept, alias = merge_range_twins([lo, hi])
    assert len(kept) == 1, "two endpoints of one range must become one figure"
    assert kept[0].span() == (1000.0, 10000.0)
    assert alias.get("f2") == "f1", "the dropped endpoint must alias to the survivor"


def test_unrelated_figures_sharing_a_label_are_not_fused() -> None:
    """The narrowness is the point: without the opposite-marker requirement, two figures
    that merely share a label would be fused into a range the deck never stated."""
    a = fig("1", 1, "count", label="landing pages, FREE plan", id="f1")
    b = fig("1", 1, "count", label="landing pages, Standard plan", id="f2")
    kept, _ = merge_range_twins([a, b])
    assert len(kept) == 2

    # Same label, same slide, but only ONE carries an endpoint marker -> not a pair.
    c = fig("5", 5, "count", label="seats (low end)", id="f3")
    d = fig("9", 9, "count", label="seats", id="f4")
    kept2, _ = merge_range_twins([c, d])
    assert len(kept2) == 2


# --------------------------------------------------------------------------
# Convention classes: arithmetically real, but not a finding.
# --------------------------------------------------------------------------


def _cmp(op: str, ops: list[str], exp: str | None, by: dict[str, Figure]) -> Relation:
    return compute({"operator": op, "operands": ops, "kind": "contradiction", "expected_id": exp}, by)


def test_growth_convention_is_not_a_contradiction() -> None:
    """A deck saying ARR "grew 22%" and a tool computing the multiple (122%) differ by
    exactly 100 points and by nothing else. Measured three times in one corpus."""
    a = fig("$19m", 19_000_000, "money", id="f1")
    b = fig("15,614", 15_614_000, "money", id="f2")
    e = fig("22%", 22, "percent", label="ARR growth rate", id="f3")
    r = _cmp("ratio", ["f1", "f2"], "f3", {"f1": a, "f2": b, "f3": e})
    assert r.verdict == "convention_differs", r.rendered
    assert "growth" in " ".join(r.reasons)


def test_the_operand_guard_keeps_a_real_finding_alive() -> None:
    """A SUM of percents landing near stated+100 is not a growth/multiple pair, and the
    corpus contains exactly one -- expert-graded REAL. Without the dimensionless guard the
    growth rule would delete it."""
    a = fig("20.00%", 20, "percent", id="f1")
    b = fig("0.00%", 0, "percent", id="f2")
    e = fig("100%", 100, "percent", label="total pre-seed dilution", id="f3")
    r = _cmp("sum", ["f1", "f2"], "f3", {"f1": a, "f2": b, "f3": e})
    assert r.verdict == "contradiction", f"a real finding was demoted: {r.reasons}"


def test_sign_convention_is_not_a_contradiction() -> None:
    a, b = fig("4,770", 4_770_000, "money", id="f1"), fig("4,789", 4_789_000, "money", id="f2")
    e = fig("20", 20_000, "money", label="variance", id="f3")
    r = _cmp("difference", ["f1", "f2"], "f3", {"f1": a, "f2": b, "f3": e})
    assert r.verdict == "convention_differs" and "sign" in " ".join(r.reasons)


def test_sign_rule_does_not_fire_when_magnitudes_also_disagree() -> None:
    """The rule is magnitude-agrees-AND-sign-differs. A real sign error with a different
    magnitude must still surface."""
    a, b = fig("4,770", 4_770_000, "money", id="f1"), fig("9,000", 9_000_000, "money", id="f2")
    e = fig("20", 20_000, "money", label="variance", id="f3")
    r = _cmp("difference", ["f1", "f2"], "f3", {"f1": a, "f2": b, "f3": e})
    assert r.verdict == "contradiction"


def test_immaterial_percentage_gap_is_not_a_finding() -> None:
    a, b = fig("20,000", 20_000, "count", id="f1"), fig("346,000", 346_000, "count", id="f2")
    e = fig("5.7%", 5.7, "percent", label="conversion rate", id="f3")
    r = _cmp("ratio", ["f1", "f2"], "f3", {"f1": a, "f2": b, "f3": e})
    assert r.verdict == "convention_differs" and "materiality" in " ".join(r.reasons)


def test_a_material_percentage_gap_still_fires() -> None:
    """14% relative on an approximate figure survives -- the floor separates 1.4% from
    14.3%, and no expert-real finding is nearer than 43.9%."""
    from reconcile import MATERIALITY_PCT, _immaterial_percent

    assert MATERIALITY_PCT == 0.02
    e = fig("3.5%", 3.5, "percent", id="f3")
    assert not _immaterial_percent(3.0, e)
    assert _immaterial_percent(3.55, e)


# ---------------------------------------------------------------------------
# What "approximate" means: the author ROUNDED. Not that the author is unsure
# about the future. A bound can only ever suppress a contradiction, so every
# word admitted here buys silence.
# ---------------------------------------------------------------------------


def test_a_target_is_a_precise_number_not_an_approximation() -> None:
    """ "$6.5M seed round target" states $6.5M exactly. A target is a specific figure."""
    assert detect_bound("$6.5M", "seed round target") is None
    assert detect_bound("25%", "Galil target margin as share of building cost") is None


def test_target_markets_does_not_make_the_count_approximate() -> None:
    """The word-sense collision that made this visible: "3 main target markets".

    `target` there is part of a noun phrase naming a market segment; the 3 is exact.
    """
    assert detect_bound("3", "main target markets") is None


def test_a_projection_is_stated_exactly_even_though_the_future_is_not() -> None:
    """DELIBERATE, and the call went against widening.

    A projection is uncertain about the WORLD; the number itself is still stated exactly,
    and a forecast whose arithmetic does not add up is a finding. Widening here made the
    tool most forgiving precisely where a founder's numbers most often fail.
    """
    assert detect_bound("$205,000", "projected MRR at June 2021") is None
    assert detect_bound("13,000", "projected number of companies at June 2021") is None


def test_words_that_really_do_mark_rounding_still_widen() -> None:
    """The fix must not overshoot: these are genuine author-rounded markers."""
    assert detect_bound("~3.5%", "R&D as share of revenue") == "approximate"
    assert detect_bound("130", "200m+ buildings completed 2020 (est)") == "approximate"
    assert detect_bound("55%", "about 55% gross margin") == "approximate"
    assert detect_bound("40", "roughly 40 customers") == "approximate"
    assert detect_bound("1,000", "estimated annual throughput") == "approximate"


def test_one_sided_bounds_are_untouched_by_the_change() -> None:
    assert detect_bound("$200B+", "market size") == "at_least"
    assert detect_bound("2,000", "tall buildings (fewer than)") == "at_most"


# ---------------------------------------------------------------------------
# The growth-convention band. A SUPPRESSION tolerance, deliberately not the same
# number as the contradiction test's — the two sit on opposite sides of the
# governing asymmetry. Every case below is measured, not constructed.
# ---------------------------------------------------------------------------


def _ratio_case(num_raw: str, num: float, den_raw: str, den: float, stated: float, stated_raw: str) -> tuple:
    """(offset from the convention point, the band the suppressor gets)."""
    from reconcile import _convention_tolerance  # noqa: PLC0415

    ops = [
        Figure(id="n", value=num, raw=num_raw, unit_kind="money", label="", slide=1, quote=""),
        Figure(id="d", value=den, raw=den_raw, unit_kind="money", label="", slide=1, quote=""),
    ]
    exp = Figure(id="e", value=stated, raw=stated_raw, unit_kind="percent", label="", slide=1, quote="")
    mid = num / den * 100
    return abs(mid - (stated + 100)), _convention_tolerance(exp, mid, "ratio", ops)


def test_the_live_false_finding_is_suppressed() -> None:
    """The defect this band was rebuilt for, from a real deck.

    `$493k / $94k = 5.24x` against a stated `425%`. 425% growth IS 5.25x — the deck was
    right and the tool asserted it wrong. Offset 0.532 against the old band of 0.5: it
    missed by 0.032 of a percentage point.
    """
    offset, band = _ratio_case("$493k", 493_000, "$94k", 94_000, 425, "425%")
    assert offset == pytest.approx(0.532, abs=0.01)
    assert band > offset, "the live false finding is not suppressed"


def test_a_coarse_operand_disagreement_still_contradicts() -> None:
    """THE CASE THAT FAILS WITHOUT THE CAP, and the reason the cap exists.

    `figure_tolerance` is a max() of the significant-figure floor and the relative rule, so
    the floor ESCAPES `CAP`: "$1M" carries 50% relative error, not 5%. Uncapped, the band
    reached ~300 points here and swallowed a real 80-point disagreement — while telling the
    founder the two figures were "the same fact, 100 points apart by convention", which the
    numbers on screen visibly contradict.
    """
    offset, band = _ratio_case("$5M", 5_000_000, "$1M", 1_000_000, 480, "480%")
    assert offset == pytest.approx(80.0, abs=0.01)
    assert band < offset, "a real 80-point disagreement was suppressed — the cap is not holding"


def test_the_band_does_not_approach_the_convention_offset_itself() -> None:
    """A band near 100 makes "differ ONLY by the convention" meaningless.

    At that width the rule stops testing the convention and starts suppressing anything in
    the neighbourhood. The cap bounds each operand at CAP, so two operands can widen by at
    most 10% of the multiple.
    """
    _, band = _ratio_case("$5M", 5_000_000, "$1M", 1_000_000, 250, "250%")
    assert band < GROWTH_CONVENTION_OFFSET / 2, f"band {band} is too close to the 100-point convention offset"


def test_the_band_scales_down_with_operand_precision() -> None:
    """Self-sizing is the whole point: precise operands must NOT buy a wide band.

    This is what rules out the rejected fixed-relative alternative — a 4-sig-fig operand
    resolves far below 1%, so a 1% gap there is real evidence, not rounding.
    """
    _, precise = _ratio_case("$527,340", 527_340, "$100,065", 100_065, 425, "425%")
    _, coarse = _ratio_case("$5M", 5_000_000, "$1M", 1_000_000, 400, "400%")
    assert precise < 1.0, f"precise operands bought a {precise} band"
    assert coarse > precise * 10


def test_a_precise_operand_disagreement_still_contradicts() -> None:
    """The counter-test: with precise operands, a ~2-point gap must survive as a finding."""
    offset, band = _ratio_case("$527,340", 527_340, "$100,065", 100_065, 425, "425%")
    assert offset > 1.0
    assert band < offset, "a real disagreement on precise operands was suppressed"


def test_only_ratio_widens_the_band() -> None:
    """`product` and `increase_by` never reach the rule — it requires a dimensionless
    computed side and they carry an operand's unit through. Widening for them would be
    speculative, and the symmetric formula is WRONG for `increase_by`, whose percentage
    operand contributes over (100 + value), not over value.
    """
    from reconcile import _convention_tolerance  # noqa: PLC0415

    ops = [
        Figure(id="n", value=5_000_000, raw="$5M", unit_kind="money", label="", slide=1, quote=""),
        Figure(id="d", value=1_000_000, raw="$1M", unit_kind="money", label="", slide=1, quote=""),
    ]
    exp = Figure(id="e", value=400, raw="400%", unit_kind="percent", label="", slide=1, quote="")
    assert _convention_tolerance(exp, 500.0, "product", ops) == figure_tolerance(exp)
    assert _convention_tolerance(exp, 500.0, "increase_by", ops) == figure_tolerance(exp)
    assert _convention_tolerance(exp, 500.0, "ratio", ops) > figure_tolerance(exp)


# ---------------------------------------------------------------------------
# Cross-slide consistency checks. The model pairs the same quantity stated on two
# slides to see whether the deck agrees with itself. When it does, the answer is
# 100% and there is nothing to tell a founder.
# ---------------------------------------------------------------------------


def _cross_slide(a_val: float, b_val: float, unit_a: str = "count", unit_b: str = "count") -> str:
    a = fig("150+", a_val, unit_a, "customer accounts (slide 2)", id="acct_s2")
    b = fig("150+", b_val, unit_b, "total customer accounts (slide 9)", id="acct_s9")
    return str(_cmp("ratio", ["acct_s2", "acct_s9"], None, {"acct_s2": a, "acct_s9": b}).verdict)


def test_a_passing_cross_slide_check_is_not_a_founder_facing_reading() -> None:
    """ "150+ / 150+ = 100.0%" reached a real founder report under "What the numbers imply".

    The check itself is worth running — if the two slides disagreed that would be a real
    finding. But when they agree the result restates what the deck already says twice.
    """
    assert _cross_slide(150, 150) == "restatement"


def test_a_cross_slide_DISAGREEMENT_is_never_suppressed() -> None:
    """The counter-test, and the reason the equality check is the gate.

    A deck saying 150 accounts on one slide and 180 on another is exactly what this pairing
    exists to catch. Suppressing that would turn a useful check into a blind spot.
    """
    assert _cross_slide(150, 180) != "restatement"


def test_two_different_quantities_landing_on_100_percent_stay_derived() -> None:
    """Breakeven is a reading, not a restatement — the operands are not the same quantity."""
    a = fig("$2M", 2_000_000, "money", "annual revenue", id="rev")
    b = fig("$2M", 2_000_000, "money", "annual cost", id="cost")
    # Same value and unit, so this IS caught by the guard — recorded as a known limit
    # rather than claimed as handled. The label distinction is not something the rule reads.
    assert _cmp("ratio", ["rev", "cost"], None, {"rev": a, "cost": b}).verdict == "restatement"


def test_a_ratio_with_a_stated_counterpart_is_untouched() -> None:
    """A relation testing against a figure the deck states is a finding, never a restatement."""
    a = fig("150+", 150, "count", "accounts (slide 2)", id="a")
    b = fig("150+", 150, "count", "accounts (slide 9)", id="b")
    e = fig("90%", 90, "percent", "retention", id="e")
    assert _cmp("ratio", ["a", "b"], "e", {"a": a, "b": b, "e": e}).verdict != "restatement"


def test_the_stated_side_must_clear_the_gate_the_operands_clear() -> None:
    """A contradiction may not cite a figure the second read never found.

    Operands are dropped hard when uncorroborated. The expected figure was not checked at
    all, so the report could read "but the deck states $50k (ACV)" about a figure the
    second read never located — telling a founder their numbers disagree with something
    the deck may not say, and falsifying the report's own promise that every figure shown
    had its wording "checked back against your deck".

    Suppresses rather than manufactures: the relation stays a derived reading.
    """
    a = fig("$100k", 100_000, "money", "revenue", id="a")
    b = fig("4", 4, "count", "customers", id="b")
    e = fig("$50k", 50_000, "money", "ACV", id="e")
    e.verified = False  # the second read never found it
    r = _cmp("ratio", ["a", "b"], "e", {"a": a, "b": b, "e": e})
    assert r.verdict != "contradiction"
    assert any("not corroborated" in x for x in r.reasons)


def test_a_corroborated_stated_side_still_produces_findings() -> None:
    """The counter-test: the gate must not blunt the engine when the figure IS found."""
    a = fig("$100k", 100_000, "money", "revenue", id="a")
    b = fig("4", 4, "count", "customers", id="b")
    e = fig("$50k", 50_000, "money", "ACV", id="e")
    assert _cmp("ratio", ["a", "b"], "e", {"a": a, "b": b, "e": e}).verdict == "contradiction"


def test_a_figure_subtracted_from_itself_is_not_a_reading() -> None:
    """`$12.5 trillion − $12.5 trillion = 0` reached a real founder report.

    Same global market size stated on two slides — the cross-slide consistency check again,
    which I had guarded for `ratio` only. The carve-out that justified scoping to `ratio`
    (a ratio of different quantities landing on 100% might be worth reading) does not
    transfer: X − X = 0 is meaningless whatever the quantities are.
    """
    a = fig("$12.5 trillion", 12_500_000_000_000, "money", "market size (slide 12)", id="m12")
    b = fig("$12.5 trillion", 12_500_000_000_000, "money", "market size (slide 24)", id="m24")
    assert _cmp("difference", ["m12", "m24"], None, {"m12": a, "m24": b}).verdict == "restatement"


def test_a_real_difference_across_slides_still_surfaces() -> None:
    """The counter-test: only EQUAL operands are silenced, never a genuine disagreement."""
    a = fig("$12.5 trillion", 12_500_000_000_000, "money", "market size (slide 12)", id="m12")
    b = fig("$9 trillion", 9_000_000_000_000, "money", "market size (slide 24)", id="m24")
    assert _cmp("difference", ["m12", "m24"], None, {"m12": a, "m24": b}).verdict != "restatement"


def test_subtracting_an_open_ended_figure_is_refused() -> None:
    """`50% − Over 30% = 20` was rendered as exact. It is not.

    Subtracting a floor yields a CEILING — the honest answer is "at most 20" — and a
    founder cannot see that the number is wrong. Refusing costs almost nothing: a
    difference against an open-ended figure is rarely the finding.
    """
    a = fig("50%", 50, "percent", "time-to-market reduction", id="a")
    b = fig("Over 30%", 30, "percent", "time to market reduction", id="b")
    r = _cmp("difference", ["a", "b"], None, {"a": a, "b": b})
    assert r.dropped
    assert any("open-ended" in x for x in r.reasons)


def test_a_leading_bound_word_in_the_raw_string_is_read() -> None:
    """ "Over 30%" puts the bound in the figure's own text, where nothing was looking.

    `detect_bound` read symbols from `raw` and words from `label`, so a raw carrying the
    word fell through both. Anchored to the start deliberately — an unanchored match reads
    "1103% over 6 mths" as a floor, where "over" is a time preposition.
    """
    assert detect_bound("Over 30%", "time to market") == "at_least"
    assert detect_bound("Less than 2,000", "tall buildings") == "at_most"
    assert detect_bound("30%", "turnover 30%") is None


def test_a_reduction_is_not_compared_against_a_share() -> None:
    """`10-12 ÷ >70 = 14.29-17.14% — but the deck states ↓75%` reached a real report.

    "↓75%" is a reduction; the computed value is what REMAINS. They are complements, and
    both carry `unit_kind: percent`, so the unit algebra passes them through and the
    founder is shown 15% beside 75% with no way to tell what is alleged.
    """
    a = fig("10-12", 10, "count", "minimal FTE", id="after")
    b = fig(">70", 70, "count", "traditional FTE", id="before")
    e = fig("↓75%", 75, "percent", "FTE count reduction", id="cut")
    r = _cmp("ratio", ["after", "before"], "cut", {"after": a, "before": b, "cut": e})
    assert r.verdict != "contradiction"
    assert any("complements" in x for x in r.reasons)


def test_a_plain_share_is_still_tested_normally() -> None:
    """The counter-test: only reduction-framed figures are refused, not every percent."""
    a = fig("$9K", 9000, "money", "net revenue", id="rev")
    b = fig("$493K", 493000, "money", "volume", id="vol")
    e = fig("6.2%", 6.2, "percent", "take rate", id="tr")
    assert _cmp("ratio", ["rev", "vol"], "tr", {"rev": a, "vol": b, "tr": e}).verdict == "contradiction"


def test_the_reduction_words_have_no_competing_sense() -> None:
    """`target` and `over` both produced false bounds today by matching another meaning.

    These three are nouns of decrease with no other reading; `decline` is excluded on
    purpose ("declined the offer").
    """
    from reconcile import _is_reduction  # noqa: PLC0415

    assert _is_reduction(fig("↓75%", 75, "percent", "FTE count", id="x"))
    assert _is_reduction(fig("75%", 75, "percent", "cost reduction", id="x"))
    assert _is_reduction(fig("75%", 75, "percent", "annualised savings", id="x"))
    assert not _is_reduction(fig("75%", 75, "percent", "gross margin", id="x"))
    assert not _is_reduction(fig("75%", 75, "percent", "declined offers", id="x"))


def test_the_same_quantity_in_two_periods_is_not_a_reading() -> None:
    """`108 million ÷ 9 million = 100.0%` reached a real founder report.

    "9 million per month" on one slide and "108 million per annum" on another are the same
    quantity; the engine's own period conversion proves it by computing exactly 1.0. The
    guard compared OPERANDS — 108,000,000 against 9,000,000, nowhere near equal — so it
    waved the relation through, and the founder saw a division that reads as broken.
    """
    a = fig("108 million", 108_000_000, "count", "vacancies per annum", id="yr", period="year")
    b = fig("9 million", 9_000_000, "count", "vacancies per month", id="mo", period="month")
    assert _cmp("ratio", ["yr", "mo"], None, {"yr": a, "mo": b}).verdict == "restatement"


def test_a_genuine_ratio_across_periods_still_reads() -> None:
    """The counter-test: only a result of ONE is silenced, not every cross-period ratio."""
    a = fig("60 million", 60_000_000, "count", "vacancies per annum", id="yr", period="year")
    b = fig("9 million", 9_000_000, "count", "vacancies per month", id="mo", period="month")
    r = _cmp("ratio", ["yr", "mo"], None, {"yr": a, "mo": b})
    assert r.verdict != "restatement", f"a real 60m/yr vs 9m/mo gap was silenced: {r.rendered}"


# ---------------------------------------------------------------------------
# Dates are not magnitudes. Every operator computed something from them anyway, and
# every answer was nonsense a founder could be shown: 2030 × 2025 = 4,110,750 with a
# `derived` verdict, 2030 increased by 20% = 2,436. The unit algebra never guarded the
# kind, so `date` fell through to the numeric branches on its face value.
#
# The refusal is COMPLETE — every operator, and the stated side too. That completeness
# is what makes the vacuous date tolerance unreachable rather than merely unlikely:
# `figure_tolerance` is only ever called from inside `compute()` after an operator
# branch has succeeded, so a relation refused before dispatch never consults it. The
# reachability test at the bottom of this block is what pins that, and it is the guard
# that goes red if any operator is un-refused later.
# ---------------------------------------------------------------------------


def _dates() -> dict[str, Figure]:
    return {
        "d1": fig("2030", 2030, "date", "target year", id="d1"),
        "d2": fig("2025", 2025, "date", "launch year", id="d2"),
    }


@pytest.mark.parametrize("operator", ["difference", "sum", "product", "ratio"])
def test_no_operator_computes_on_dates(operator: str) -> None:
    r = _cmp(operator, ["d1", "d2"], None, _dates())
    assert r.dropped, f"{operator} computed {r.computed} from two years: {r.rendered}"
    assert r.computed is None
    assert any("date" in reason for reason in r.reasons), r.reasons


def test_increase_by_does_not_grow_a_year() -> None:
    """`2030 increased by 20% = 2,436` was reachable and rendered as a founder-facing
    line. `increase_by` was omitted from the operator guard drafted for the other four."""
    by = {"d1": _dates()["d1"], "p": fig("20%", 20, "percent", "growth", id="p")}
    r = _cmp("increase_by", ["d1", "p"], None, by)
    assert r.dropped, r.rendered
    assert any("date" in reason for reason in r.reasons), r.reasons


def test_a_stated_date_cannot_be_the_expected_side_either() -> None:
    """The stated side clears the same gate the operands do — otherwise a count sum
    gets compared against a year, and the year's tolerance is what decides it."""
    by = {
        "a": fig("12", 12, "count", "pilots", id="a"),
        "b": fig("2013", 2013, "count", "seats", id="b"),
        "e": fig("2025", 2025, "date", "launch year", id="e"),
    }
    r = _cmp("sum", ["a", "b"], "e", by)
    assert r.dropped, r.rendered
    assert any("date" in reason for reason in r.reasons), r.reasons


def test_the_vacuous_date_tolerance_is_unreachable() -> None:
    """`figure_tolerance` on a quarter-prefixed year is 101.25 — every comparison
    against it confirms. The fix is not a better tolerance; it is that no relation
    survives to consult one. This test states the tolerance is still wrong AND still
    unreachable, so relaxing the refusal fails here rather than shipping silently."""
    quarter = fig("Q4 2025", 2025, "date", "launch", id="q")
    assert figure_tolerance(quarter) > 100, "the underlying precision bug is still present"
    by = {"q": quarter, "d2": _dates()["d2"]}
    for operator in ("difference", "sum", "product", "ratio"):
        assert _cmp(operator, ["q", "d2"], None, by).dropped


def test_non_date_relations_are_untouched() -> None:
    """The guard keys on `unit_kind`, so nothing else changes shape."""
    a = fig("$100k", 100_000, "money", id="a")
    b = fig("4", 4, "count", id="b")
    r = _cmp("ratio", ["a", "b"], None, {"a": a, "b": b})
    assert not r.dropped
    assert r.computed == pytest.approx(25_000)


# ---------------------------------------------------------------------------
# N8 — the approximation marker that lives only in the quote.
#
# A deck that prints a bare bar value and puts the `≈` in the surrounding sentence gets no
# bound from `raw` or `label`, because neither carries the glyph. Measured on one live
# ledger: `≈` appeared in 0 of 81 `raw` values and 7 quotes, so adding the glyph to the
# symbol pattern reached none of the figures that motivated it.
#
# The quote is a whole sentence and may hold several numbers, so the binding has to be
# TIGHTER than the `raw` rule, not looser. `raw` uses "the glyph precedes the first number";
# a quote needs "the glyph precedes THIS figure's number", which means locating the figure's
# own printed string inside the quote. A bound can only ever suppress a contradiction, so a
# false positive here buys silence on a real finding — this errs toward reading nothing.
# ---------------------------------------------------------------------------


def test_an_approximation_marker_in_the_quote_binds_to_its_own_figure() -> None:
    """N8's motivating case: the bar is printed bare and the sentence marks it approximate."""
    assert detect_bound("$20B", "Computer vision market 2024", "Computer vision market ≈$20B in 2024") == "approximate"


def test_a_tilde_in_the_quote_binds_the_same_way() -> None:
    assert detect_bound("1,200", "customers", "roughly ~1,200 customers today") == "approximate"


def test_a_quote_glyph_belonging_to_a_different_number_does_not_bind() -> None:
    """The whole hazard. The quote names two figures and the glyph qualifies the other one;
    reading it as this figure's bound would erase a real contradiction about this figure."""
    assert detect_bound("$100", "revenue", "revenue of $100 against a market of ≈$20B") is None


def test_a_quote_glyph_after_the_figure_does_not_bind() -> None:
    """ "$20B" then "≈20 competitors" later in the sentence is not a marker on $20B."""
    assert detect_bound("$20B", "market", "market of $20B with ≈20 competitors") is None


def test_a_figure_absent_from_its_own_quote_reads_no_bound() -> None:
    """A quote that does not contain the figure's printed string cannot position a glyph
    relative to it, so there is nothing to bind and the answer is no bound — never a guess."""
    assert detect_bound("$20B", "market", "the market is approximately twenty billion dollars") is None


def test_the_quote_is_optional_and_omitting_it_changes_nothing() -> None:
    """Every existing caller passes two arguments; the third must default to no quote and
    leave all prior behaviour identical."""
    assert detect_bound("$20B", "Computer vision market 2024") is None
    assert detect_bound("≈20", "") == "approximate"
    assert detect_bound("$200B+", "") == "at_least"


def test_an_explicit_bound_still_beats_a_quote_approximation() -> None:
    """`approximate` is the fallback branch: a stated floor is a stronger claim than a
    marker in the prose around it, and the ordering must not change."""
    assert detect_bound("$200B+", "market", "the market is ≈$200B+ today") == "at_least"


def test_an_earlier_glyph_on_another_number_does_not_reach_this_figure() -> None:
    """The anchor is what makes the binding tight, and this is the case that tests it.

    Here the glyph sits BEFORE this figure in the quote but belongs to a different number.
    "Is there a glyph somewhere in front of it?" answers yes and erases a real finding about
    $100; "is the glyph immediately in front of it?" answers no. Both readings agree on every
    other case in this block, which is why this one has to exist — the anchor was added on
    the right reasoning and pinned by nothing until a mutation removed it and no test moved.
    """
    assert detect_bound("$100", "revenue", "a market of ≈$20B and revenue of $100") is None
    # The counter-half: same shape, glyph now on THIS figure, so it must still bind.
    assert detect_bound("$100", "revenue", "a market of $20B and revenue of ≈$100") == "approximate"


# ---------------------------------------------------------------------------
# Two holes in the approximation binding, both found in review, both in the direction
# that ERASES a real contradiction — which is the direction this module treats as the
# worst thing it can emit.
# ---------------------------------------------------------------------------


def test_a_quote_glyph_on_a_longer_number_does_not_bind_to_a_shorter_one() -> None:
    """`quote.find(raw)` matched "$20" inside "≈$200B" and marked the $20 approximate.

    Measured end-to-end: `12 + 9.8 = 21.8` against a stated `$20` whose quote reads
    "market ≈$200B and total $20" returned `confirmation`; without the glyph it returns
    `contradiction`. A real finding erased by a substring of a different number.
    """
    assert detect_bound("$20", "revenue", "market ≈$200B and revenue $20") is None
    # The counter-half: the same figure, glyph genuinely on it, must still bind.
    assert detect_bound("$20", "revenue", "market $200B and revenue ≈$20") == "approximate"


def test_repeated_occurrences_that_disagree_read_no_bound() -> None:
    """One printed twice, once marked and once not, is ambiguous. `any()` resolved it to
    approximate — the silencing direction — on no evidence about which one this figure is."""
    assert detect_bound("$20B", "market", "segment A ≈$20B; segment B $20B exactly") is None
    # Unambiguous repeats keep working, in both directions.
    assert detect_bound("$20B", "market", "≈$20B in 2024 and ≈$20B in 2025") == "approximate"
    assert detect_bound("$20B", "market", "$20B in 2024 and $20B in 2025") is None


def test_an_approximation_word_still_needs_a_number_to_qualify() -> None:
    """`raw="about"` with `value=100` reads `approximate` and turns `60 + 48 = 108`
    against a stated 100 into a confirmation.

    The symbol path already required a number to qualify (that hole was closed when `≈`
    was added). The WORD path never got the same treatment, so a `raw` that is prose
    rather than a printed figure still widens tolerance by 10% off no number at all.
    """
    assert detect_bound("about", "", "") is None
    assert detect_bound("approximately", "total", "") is None
    # A word beside an actual number still binds, and a word in the LABEL still binds to
    # the figure the label describes — neither of those is what this closes.
    assert detect_bound("about 100", "", "") == "approximate"
    assert detect_bound("100", "about 100 customers", "") == "approximate"


def test_sentence_punctuation_after_the_figure_keeps_the_marker() -> None:
    """A REGRESSION introduced by the token-boundary fix, and the common case at that.

    The boundary check rejected any trailing `.` or `,` as "this is a longer number", but a
    quote is a SENTENCE and the figure it is about routinely ends it. Measured:

        "market ≈$20B"   -> approximate
        "market ≈$20B."  -> None      <- the marker silently lost
        "market ≈$20B,"  -> None

    Losing the bound makes the comparison two-sided again, so ordinary punctuation could
    turn a confirmation into a contradiction — the direction that manufactures findings.

    Punctuation is numeric continuation only when a DIGIT follows it.
    """
    for quote in ("market ≈$20B", "market ≈$20B.", "market ≈$20B,", "market ≈$20B; and so on", "(≈$20B)"):
        assert detect_bound("$20B", "market", quote) == "approximate", quote

    # Still not fooled by a genuine longer number.
    assert detect_bound("$20", "revenue", "market ≈$20.5B and revenue $20") is None
    assert detect_bound("$1", "count", "≈$1,200 in total") is None


def test_punctuation_does_not_flip_a_verdict() -> None:
    """The end-to-end half: the same figures, one full stop apart, must not disagree."""

    def _verdict(quote: str) -> str:
        a = fig("6", 6, "count", id="a")
        b = fig("5", 5, "count", id="b")
        e = Figure(
            id="e",
            value=10.0,
            raw="≈10",
            unit_kind="count",
            label="team",
            slide=1,
            quote=quote,
            bound=detect_bound("≈10", "team", quote),
            verified=True,
        )
        verdict: str = _cmp("sum", ["a", "b"], "e", {"a": a, "b": b, "e": e}).verdict
        return verdict

    assert _verdict("the team is ≈10") == _verdict("the team is ≈10."), "a trailing full stop changed the verdict"


def test_a_quote_needs_a_word_that_says_what_the_number_is() -> None:
    """ "Any three-letter word" was too weak a predicate to mean what it claimed.

    `USD $493K`, `the $80B` and `about $80B` all carried a qualifying "word" and passed,
    while identifying nothing: a currency code, an article and a hedge say nothing about
    WHICH quantity the number is. The point of the check is that the quote names the thing.
    """
    for quote in ("USD $493K", "the $80B", "about $80B", "$80B", "63.5% | $635K", "approx 12"):
        assert not quote_is_identifying(quote), quote
    for quote in ("Net revenue $493K", "GMV of $493K in 2024", "ARR $2M", "customers 1,200"):
        assert quote_is_identifying(quote), quote


def test_a_footnote_marker_is_not_numeric_continuation() -> None:
    """`str.isdigit()` is True for `¹`, `²` and `①`, so a superscript footnote — the
    commonest thing to sit immediately after a figure on a slide — read as "this is a
    longer number" and the approximation marker vanished. Losing a bound surfaces
    contradictions, so this is the manufacturing direction again.

    `isdecimal()` is the narrower predicate: true for `0-9` and other decimal digit
    systems, false for superscripts and enclosed forms.
    """
    for marker in ("¹", "²", "³", "①", "†", "*", ")", "]", ""):
        assert detect_bound("$20B", "market", f"market ≈$20B{marker}") == "approximate", repr(marker)

    # Real continuations are still continuations, including non-ASCII decimal digits.
    assert detect_bound("$20", "revenue", "market ≈$205B and revenue $20") is None
    assert detect_bound("$2", "revenue", "≈$2٠ in total") is None


def test_a_numeric_prefix_does_not_inherit_the_larger_number_marker() -> None:
    """The one-character tail test missed every separator that is not a digit.

    `raw="$20"` matched inside `≈$20 billion`, `≈$20 000` and `≈$20′000` — a scale WORD, a
    space-grouped thousand and an apostrophe-grouped one — so the smaller figure inherited
    an approximation belonging to a number a thousand times its size. Probed end to end,
    that turned a real contradiction into a suppressed confirmation.
    """
    for quote in (
        "market ≈$20 billion",
        "market ≈$20 million",
        "≈$20 000",
        "≈$20′000",
        "≈$20 000 000",
        "≈$20e6",
    ):
        assert detect_bound("$20", "revenue", quote) is None, quote

    # And the genuine case is untouched: the figure itself, marked, ending the clause.
    assert detect_bound("$20", "revenue", "revenue of ≈$20 last year") == "approximate"
    assert detect_bound("$20B", "market", "market ≈$20B") == "approximate"


def test_the_quote_binding_uses_a_maximal_numeric_lexeme() -> None:
    """A denylist of continuation characters cannot converge, and three rounds proved it.

    Each pass fixed the named examples and left the next separator: a scale word, then
    grouped thousands, then a hyphenated scale (`≈$20-billion`), a spelled Indian unit
    (`≈$20 crore`), Arabic-Indic grouping and `≈$20×10^6`. In every one, `raw="$20"` was a
    PREFIX of a larger number and inherited its approximation — silencing a real
    contradiction.

    The fix is to ask where the number ENDS rather than which characters may follow it: the
    match counts only when it spans the whole numeric lexeme at that position.
    """
    for quote in (
        "market ≈$20-billion",
        "market ≈$20 crore",
        "market ≈$20 lakh",
        "≈$20×10^6",
        "≈$20 000",
        "≈$20′000",
        "market ≈$20 billion",
        "≈$20٬000",
    ):
        assert detect_bound("$20", "revenue", quote) is None, quote

    # The genuine bindings all still hold.
    assert detect_bound("$20", "revenue", "revenue of ≈$20 last year") == "approximate"
    assert detect_bound("$20B", "market", "market ≈$20B.") == "approximate"
    assert detect_bound("1,200", "customers", "roughly ~1,200 customers today") == "approximate"


def test_the_lexeme_covers_the_scale_forms_decks_actually_print() -> None:
    """Fourth pass on this boundary, and the previous three each closed the named cases.

    Still importing: `≈$20MM` (accounting millions), `≈20x` (a multiple), `≈20×10⁶`
    (superscript exponent — `\\d` does not match `⁶`), `≈20 MM`. In each, raw `20` is a
    prefix of a larger claim and inherits its approximation, turning `12 + 9.8` against a
    stated 20 from contradiction into confirmation.
    """
    for quote in ("≈$20MM", "≈20 MM", "≈20x", "≈20×10⁶", "≈20·10⁶", "≈20bn", "≈20 Mn"):
        raw = "$20" if "$" in quote else "20"
        assert detect_bound(raw, "m", quote) is None, quote

    # The figure itself, marked, still binds — including with a scale the figure OWNS.
    assert detect_bound("$20MM", "m", "market of ≈$20MM") == "approximate"
    assert detect_bound("20x", "m", "≈20x improvement") == "approximate"
    assert detect_bound("20", "m", "roughly ≈20 people") == "approximate"


def test_the_quote_lexeme_and_the_magnitude_parser_agree_on_scale() -> None:
    """A divergence I introduced: the quote lexeme learned `MM`/`Mn`/`bn` so a figure would
    stop inheriting a larger number's approximation, and `_parsed_magnitude` — the
    authoritative parser the ledger validates against — did not learn them.

    Measured before the fix: `raw="$20MM"` with the CORRECT value 20,000,000 was rejected
    as disagreeing with a raw that "reads as 20", while the wrong value 20 was accepted.
    One join upstream from a boundary check, the two grammars disagreed by a factor of a
    million, in the direction that admits the error.
    """
    for raw, expected in (("$20MM", 20e6), ("$20Mn", 20e6), ("$20bn", 20e9), ("$20M", 20e6), ("$20K", 20e3)):
        assert implied_tolerance(raw) > 0, raw
        assert _raw_scale(raw) == expected / 20, (raw, _raw_scale(raw))


def test_the_four_numeric_grammars_agree_on_what_a_scale_is() -> None:
    """No scale may be known to one numeric grammar and unknown to another.

    Four regexes describe the same notation -- the magnitude parser, the range parser, the
    open-ended `+` parser, and the token-boundary lexeme -- and each used to carry its own
    hand-typed list of scale words. Every divergence was a scale error pointing the same
    way: a figure whose scale one grammar could not see was read as a bare mantissa, so the
    CORRECT value was rejected and the 1000x-smaller one accepted. Three review rounds each
    fixed the forms that had been named and left the rest, which is why this asserts the
    property rather than the examples.
    """
    import reconcile  # type: ignore[import-not-found]

    for scale in reconcile.SCALE_TOKENS:
        raw = f"$20{scale}"
        magnitude = _raw_scale(raw)
        expected = reconcile._SCALE[scale]
        assert magnitude == expected, f"{raw!r}: the magnitude parser read a scale of {magnitude}, not {expected}"
        lexeme = reconcile._NUMERIC_LEXEME.match(raw, 1)
        ended_at = lexeme.group(0) if lexeme else None
        assert ended_at == f"20{scale}", (
            f"{raw!r}: the token boundary ended at {ended_at!r}, so the scale reads as "
            "unrelated text and the bare mantissa looks like a whole number"
        )
        assert reconcile._PLUS_RE.search(f"{raw}+"), (
            f"{raw}+: the open-ended parser did not see a floor, so the figure reads as exact"
        )
        rng = reconcile._RANGE_RE.search(f"$20-30{scale}")
        read_as = (rng.group("suf") or "") if rng else None
        assert read_as is not None and read_as.lower() == scale, (
            f"$20-30{scale}: the range parser read the shared suffix as {read_as!r}, so both ends lose their scale"
        )


def test_the_scale_agreement_sweep_covers_the_multi_letter_forms() -> None:
    """Non-vacuity: the sweep above is only meaningful if it reaches past `k`/`m`/`b`/`t`.

    The single letters were never the bug -- every grammar always knew those. The defects
    were all in the forms that need more than one character.
    """
    import reconcile  # type: ignore[import-not-found]

    assert {"mm", "mn", "bn", "tn", "crore", "lakh", "lac"} <= set(reconcile.SCALE_TOKENS)


def test_a_count_is_a_multiplier_in_a_product_not_a_dimension() -> None:
    """`412 customers x $95/month` is money per month, not an untestable mixture.

    The product's unit algebra dropped PERCENT from the kind list -- correctly, a percent in
    a product is a multiplier -- but kept COUNT, so two kinds survived and the result typed
    as `mixed`, which is incomparable to every stated figure. Measured on a deck built to
    contradict itself: the engine computed 39,140 against a stated MRR of $22K and then
    refused to compare them, reason "computed is mixed:month, stated is money:month".

    A count is dimensionless in a product by dimensional analysis, and the two identities
    this blocks are the most common arithmetic in a seed deck: customers x ARPU = revenue,
    and target businesses x contract value = bottom-up TAM. Neither could ever be
    contradicted, so a deck could state a revenue its own customer count and price refute
    and the engine would file it as unit-incomparable.
    """
    import reconcile

    customers = fig("412", 412, unit_kind="count", label="paying customers", id="customers")
    arpu = fig("$95/month", 95, unit_kind="money", label="ARPU", id="arpu", period="month")
    mrr = fig("$22K", 22000, unit_kind="money", label="MRR", id="mrr", period="month")
    for f in (customers, arpu, mrr):
        f.verified = True
    by = {f.id: f for f in (customers, arpu, mrr)}

    rel = reconcile.compute(
        {"kind": "derived_product", "operator": "product", "operands": ["customers", "arpu"], "expected_id": "mrr"},
        by,
    )
    assert rel.computed == 39140.0, rel.computed
    assert rel.computed_unit == "money:month", (
        f"computed_unit is {rel.computed_unit!r}; a count must not contribute a dimension, or "
        "customers x ARPU can never be tested against a stated MRR"
    )
    assert rel.verdict == "contradiction", (
        f"verdict {rel.verdict!r} with reasons {rel.reasons} — 39,140 against a stated 22,000 "
        "is a 78% disagreement and the deck's own numbers establish it"
    )


def test_a_product_of_only_counts_stays_untestable() -> None:
    """Excluding COUNT must not make a count-only product look like a typed quantity.

    `seats x offices` is a count of things and has no business being compared against a
    money figure. With COUNT dropped from the kind list the survivor list is EMPTY, and the
    guard has to read that as untestable rather than indexing into it.
    """
    import reconcile

    a = fig("40", 40, unit_kind="count", label="seats", id="a")
    b = fig("12", 12, unit_kind="count", label="offices", id="b")
    money = fig("$1.2M", 1_200_000, unit_kind="money", label="revenue", id="rev")
    for f in (a, b, money):
        f.verified = True
    rel = reconcile.compute(
        {"kind": "derived_product", "operator": "product", "operands": ["a", "b"], "expected_id": "rev"},
        {f.id: f for f in (a, b, money)},
    )
    assert rel.verdict == "incomparable", f"{rel.verdict!r} / unit {rel.computed_unit!r}"


# ---------------------------------------------------------------------------
# N1 — a rate-over-time claim needs operands that are commensurable IN TIME.
#
# THE DEFECT, reproduced offline from a real recorded ledger before this was written:
# a deck's traction tile stated revenue NOW and a forecast for the END OF THE SAME YEAR,
# and separately a growth claim on a tile labelled "YoY Growth". The engine divided
# forecast / current, got ~1.5x, compared it to the stated ~4x, and reported a
# CONTRADICTION -- which the coaching commentary then made the headline of the review.
# Nothing was contradicted: a within-year step is not a year-over-year rate.
#
# The engine guards units (`unit_kind`), scale (`_raw_scale`) and RATE BASIS (`PERIODS`,
# "per month" vs "per year"). It had no concept of WHEN a figure is as of, so two money
# figures with no rate basis looked freely divisible.
#
# WHY THERE IS NO NEW SCHEMA FIELD. An anchor-derivability census (2026-08-19, script at
# docs/internal/) measured how often a growth operand carries a date token in its own
# raw/quote/label: 26% across two real ledgers. And the operands of THIS defect carry
# none and never will -- the deck says "current" and "end of year", which is how founders
# write. So no `as_of` field, required or optional, would have been populated here: there
# is nothing on the slide to populate it from. A required one would have forced the
# extractor to invent a date, manufacturing the very contradictions this removes.
#
# So the guard triggers on ABSENCE rather than demanding presence, and lives at the
# comparison site beside the currency and unit refusals.
# ---------------------------------------------------------------------------

_YOY = {"operator": "ratio", "operands": ["f1", "f2"], "kind": "derived_ratio", "expected_id": "e"}


def test_a_yoy_claim_is_refused_when_both_operands_sit_inside_one_year() -> None:
    """The live defect. Both operands are deixis ("current", "EOY") — a reader resolves
    them, a parser cannot — so no span can be established and no contradiction is."""
    now = fig("$3M", 3_000_000, id="f1", label="Current ARR", quote="Current ARR of $3M")
    eoy = fig("$4.5M", 4_500_000, id="f2", label="ARR forecast EOY", quote="$4.5M exiting the year")
    exp = fig("~4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth multiple")
    r = compute(_YOY, {"f1": eoy, "f2": now, "e": exp})

    # THE ASSERTION IS "NOT A CONTRADICTION", NOT "== incomparable", and the difference is a
    # deliberate deviation from the plan. The guard refuses the BINDING (`expected_id`), which
    # is the shape of the corroboration guard four lines above it in `reconcile.py` — so the
    # relation survives as a `derived` READING of a division that is arithmetically fine, and
    # only stops being a FINDING against a claim it cannot test. Forcing `incomparable` would
    # discard a true reading to match a word chosen before the code was explored.
    #
    # Either way the founder sees nothing here: this lands at `medium` confidence and
    # `select()` admits only high-confidence derived (`reconcile.py:1725`). What matters is
    # that no FALSE DISAGREEMENT is asserted.
    assert r.verdict != "contradiction", (
        "a within-year step was compared against a year-over-year rate and called a "
        "contradiction — this shipped as the headline of a real review"
    )
    assert r.expected_id is None, "the binding to the YoY claim must be refused, not merely re-verdicted"
    assert any("year-over-year" in x.lower() and "inside one year" in x.lower() for x in r.reasons), (
        f"the refusal must say WHY, or a reader cannot tell it from a unit mismatch: {r.reasons}"
    )


def test_a_genuine_same_period_contradiction_still_fires() -> None:
    """THE OVER-REFUSAL GUARD, and the reason this test file matters more than the fix.

    A guard that suppresses the false positive by suppressing everything would pass a
    single-assertion test. On the same recorded deck, a per-employee ratio really was ~4%
    off its stated figure, and it must survive: neither side is a rate over time, so the
    time guard has no business touching it."""
    arr = fig("$3M", 3_000_000, id="f1", label="ARR")
    heads = fig("18", 18, unit_kind="count", id="f2", label="Employees")
    exp = fig("$160K", 160_000, id="e", label="ARR per employee")
    r = compute({**_YOY, "expected_id": "e"}, {"f1": arr, "f2": heads, "e": exp})
    assert r.verdict == "contradiction", f"a real disagreement was suppressed as {r.verdict!r}"


def test_a_bare_multiple_is_not_a_growth_claim() -> None:
    """Keying on `unit_kind == multiple` over-refuses. The same recorded ledger carries a
    non-temporal "100x" urgency multiple, and LTV:CAC is a bare multiple by design — the
    trigger is the expected figure's LABEL naming a rate over time, nothing else."""
    ltv = fig("$60K", 60_000, id="f1", label="LTV")
    cac = fig("$15K", 15_000, id="f2", label="CAC")
    exp = fig("4x", 4.0, unit_kind="multiple", id="e", label="LTV to CAC ratio")
    r = compute({**_YOY, "expected_id": "e"}, {"f1": ltv, "f2": cac, "e": exp})
    assert r.verdict != "incomparable", "a bare multiple was refused as if it were a growth claim"


def test_a_yoy_claim_between_two_DATED_figures_is_still_compared() -> None:
    """The 26% that CAN be anchored must still work, or the guard deletes the findings it
    exists to make trustworthy. Also N3a's shape: two dated magnitudes and a stated
    multiple — that relation spans eight years, so the span must be claim-relative rather
    than a hard-coded one period."""
    fy24 = fig("$1M", 1_000_000, id="f1", label="ARR FY2024", quote="ARR of $1M in FY2024")
    fy25 = fig("$4M", 4_000_000, id="f2", label="ARR FY2025", quote="ARR of $4M in FY2025")
    exp = fig("4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth")
    r = compute({**_YOY, "expected_id": "e"}, {"f1": fy25, "f2": fy24, "e": exp})
    assert r.verdict != "incomparable", (
        f"two dated figures one year apart ARE commensurable; got {r.verdict!r} with {r.reasons}"
    )


def test_deixis_plus_the_SAME_year_is_still_a_within_year_pair() -> None:
    """The escape hatch's own failure mode, found by mutation testing.

    The first version let ANY date token cancel the deixis check. But a deck writing "current
    ARR (FY2025)" and "$4.5M by year end FY2025" is still two points inside one year — the
    escape would have handed the false contradiction straight back, dressed as a dated
    comparison. Two DIFFERENT years is a genuine span; the same year twice is not.
    """
    now = fig("$3M", 3_000_000, id="f1", label="Current ARR", quote="Current ARR of $3M in FY2025")
    eoy = fig("$4.5M", 4_500_000, id="f2", label="ARR", quote="$4.5M by year end FY2025")
    exp = fig("~4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth multiple")
    r = compute(_YOY, {"f1": eoy, "f2": now, "e": exp})
    assert r.verdict != "contradiction", "two points inside FY2025 were compared as a year-over-year rate"
    assert r.expected_id is None


def test_deixis_across_two_DIFFERENT_years_is_a_real_span() -> None:
    """The escape's permissive direction, which nothing covered until mutation testing asked.

    A deck can write both: "current ARR of $1M in FY2024" and "$4M by year end FY2025". The
    deixis words are present, so the within-year check trips — but the years DISAGREE, which
    is a genuine year-over-year span and must still be compared. Refusing here would delete
    exactly the findings this guard exists to keep trustworthy."""
    fy24 = fig("$1M", 1_000_000, id="f1", label="ARR", quote="current ARR of $1M in FY2024")
    fy25 = fig("$4M", 4_000_000, id="f2", label="ARR", quote="$4M by year end FY2025")
    exp = fig("4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth")
    r = compute(_YOY, {"f1": fy25, "f2": fy24, "e": exp})
    assert r.expected_id == "e", "two different years were refused as if they were one"


def test_a_three_operand_relation_is_not_time_checked() -> None:
    """A rate over time is a TWO-point claim. With three operands there is no pair to check
    without inventing a reading the model never proposed, so the guard stands down rather
    than guessing — and the ordinary comparison runs."""
    # Labels deliberately carry NO "Q1"/"Q2" — those match the quarter pattern in
    # `_TIME_ANCHOR`, so an earlier draft of this test passed because the pair read as a
    # dated span and never reached the length guard at all. Caught by mutation testing.
    a = fig("$1M", 1_000_000, id="f1", label="first slice", quote="$1M current")
    b = fig("$2M", 2_000_000, id="f2", label="second slice", quote="$2M by year end")
    c = fig("$3M", 3_000_000, id="f3", label="third slice")
    exp = fig("$6M", 6_000_000, id="e", label="Total ARR growth rate")
    r = compute(
        {"operator": "sum", "operands": ["f1", "f2", "f3"], "kind": "derived_ratio", "expected_id": "e"},
        {"f1": a, "f2": b, "f3": c, "e": exp},
    )
    assert r.expected_id == "e", "a three-operand sum was time-checked as if it were a two-point rate"


# ---------------------------------------------------------------------------
# N1's other half: refusing to test a claim is not the same as having nothing to say.
#
# The guard above correctly stops calling a within-year step a year-over-year
# contradiction. But a refused relation is SUPPRESSED, and suppression is invisible --
# `suppressed` carries counts by verdict and nothing else. So the artifact recorded
# `{"derived": 1}` and no trace that a growth claim had gone untested.
#
# With no surviving contradictions the founder is then told, verbatim, "Your figures line
# up." That is the fixed bug pointing the other way: before, a founder was told they were
# wrong when they were not; now they are told everything checks out when the one claim an
# investor will probe was never checked. The false headline is gone and a false
# reassurance took its place.
#
# `select()` stays the only thing that decides what a founder SEES. This is a separate,
# additive statement of what could NOT be tested -- the same shape as the coverage line,
# which exists because "silence reads as your numbers are fine".
# ---------------------------------------------------------------------------


def test_a_refused_growth_claim_is_recorded_not_merely_suppressed() -> None:
    """The artifact must carry the fact, or no renderer can ever surface it."""
    now = fig("$3M", 3_000_000, id="f1", label="Current ARR", quote="Current ARR of $3M")
    eoy = fig("$4.5M", 4_500_000, id="f2", label="ARR forecast EOY", quote="$4.5M exiting the year")
    exp = fig("~4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth multiple")
    r = compute(_YOY, {"f1": eoy, "f2": now, "e": exp})
    assert r.untested_claim, (
        "the relation knows it refused a growth claim but records nothing a renderer can read — "
        "so the founder is told 'your figures line up' about a claim that was never tested"
    )
    assert "~4x" in r.untested_claim, f"the record must name the CLAIM, not just its absence: {r.untested_claim!r}"


def test_an_ordinary_relation_records_no_untested_claim() -> None:
    """The other direction: this must not become a line on every deck."""
    arr = fig("$3M", 3_000_000, id="f1", label="ARR")
    heads = fig("18", 18, unit_kind="count", id="f2", label="Employees")
    exp = fig("$160K", 160_000, id="e", label="ARR per employee")
    r = compute({**_YOY, "expected_id": "e"}, {"f1": arr, "f2": heads, "e": exp})
    assert not r.untested_claim, "a relation that WAS tested must not report an untested claim"


def test_untested_claims_survive_into_the_artifact_even_though_the_relation_does_not() -> None:
    """The whole point: the RELATION is suppressed, the FACT must not be.

    `select()` correctly drops a refused relation — it establishes nothing and must not
    reach the founder as a finding. But the artifact is the only channel to the renderer,
    so a fact that lives solely on a dropped object is a fact nobody can report. Collected
    at the top level, beside `suppressed`, as a statement of what could not be tested.
    """
    now = fig("$3M", 3_000_000, id="f1", label="Current ARR", quote="Current ARR of $3M")
    eoy = fig("$4.5M", 4_500_000, id="f2", label="ARR forecast EOY", quote="$4.5M exiting the year")
    exp = fig("~4x", 4.0, unit_kind="multiple", id="e", label="YoY Growth multiple")
    r = compute(_YOY, {"f1": eoy, "f2": now, "e": exp})
    selected = select([r])
    assert r not in selected, "a refused relation must still be suppressed — it establishes nothing"
    assert r.untested_claim, "and the fact must survive on it for the artifact to collect"

    # THROUGH THE REAL CLI, not just the object. Mutation testing caught this: asserting on
    # the Relation alone passed while `untested_claims` was emptied at the collection site, so
    # the fact died between the object and the artifact — which is the only channel a renderer
    # has. The gap was invisible because the object-level assertion looked like coverage.
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    with _tf.TemporaryDirectory() as d:
        led = pathlib.Path(d) / "ledger.json"
        sec = pathlib.Path(d) / "second_read.json"
        out = pathlib.Path(d) / "rec.json"
        figs = [
            {
                "id": "f1",
                "value": 3_000_000,
                "raw": "$3M",
                "unit_kind": "money",
                "label": "Current ARR",
                "slide": 4,
                "quote": "Current ARR of $3M",
                "currency": "USD",
            },
            {
                "id": "f2",
                "value": 4_500_000,
                "raw": "$4.5M",
                "unit_kind": "money",
                "label": "ARR forecast EOY",
                "slide": 4,
                "quote": "$4.5M exiting the year",
                "currency": "USD",
            },
            {
                "id": "e",
                "value": 4.0,
                "raw": "~4x",
                "unit_kind": "multiple",
                "label": "YoY Growth multiple",
                "slide": 4,
                "quote": "~4x YoY Growth",
            },
        ]
        led.write_text(_json.dumps({"figures": figs, "figures_total": 3}), encoding="utf-8")
        sec.write_text(
            _json.dumps(
                {"transcript": "Current ARR of $3M. $4.5M exiting the year. ~4x YoY Growth.", "slides_transcribed": [4]}
            ),
            encoding="utf-8",
        )
        proposal = _json.dumps(
            {
                "relations": [
                    {"kind": "derived_ratio", "operator": "ratio", "operands": ["f2", "f1"], "expected_id": "e"}
                ]
            }
        )
        _sp.run(
            [
                sys.executable,
                str(pathlib.Path(SCRIPTS) / "reconcile.py"),
                "--ledger",
                str(led),
                "--second-read",
                str(sec),
                "--run-id",
                "r1",
                "-o",
                str(out),
            ],
            input=proposal,
            capture_output=True,
            text=True,
            check=False,
        )
        artifact = _json.loads(out.read_text(encoding="utf-8"))
    assert artifact.get("untested_claims"), (
        "the refused claim never reached the artifact — a renderer has no other channel, so the "
        "founder is told their figures line up about a claim that was never checked"
    )
    assert any("4x" in c for c in artifact["untested_claims"]), artifact["untested_claims"]


# --- spelled-out cardinals ---------------------------------------------------------------
#
# `numeral_form` is what lets a raw of "three" reach the same precision, scale, range and
# approximation checks as "3". It rewrites ONLY when the string prints no digit; a raw that
# already carries a numeral is the figure's printed string and must come back untouched.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fifteen years", "15 years"),
        ("Six", "6"),
        ("three", "3"),
        ("Twenty-five percent", "25 percent"),
        ("twenty five", "25"),
        ("a hundred customers", "100 customers"),
        ("one hundred and five", "105"),
        ("about three", "about 3"),
        ("three million", "3 million"),  # the scale word is `_NUM_RE`'s to read
        ("zero", "0"),
        ("$493K", "$493K"),  # prints a digit: untouched
        ("12 projects", "12 projects"),
        ("three of the 500", "three of the 500"),  # a digit anywhere wins; the words are prose
        ("a fourth", "a fourth"),  # ordinal
        ("hundred", "hundred"),  # no mantissa
        ("TBD", "TBD"),
        ("", ""),
    ],
)
def test_numeral_form_reads_spelled_out_cardinals_only_where_no_digit_is_printed(raw: str, expected: str) -> None:
    from reconcile import numeral_form

    assert numeral_form(raw) == expected


def test_a_spelled_out_count_has_the_precision_and_scale_of_its_digit_form() -> None:
    from reconcile import _precision, _raw_scale, implied_tolerance

    assert _precision("three") == _precision("3")
    assert _precision("Fifteen years") == _precision("15 years")
    assert _raw_scale("three million") == _raw_scale("3 million") == 1e6
    assert implied_tolerance("Twenty-five") == implied_tolerance("25")


def test_a_spelled_out_count_is_bounded_like_its_digit_form() -> None:
    """The word path in `detect_bound` requires a number to bind to — and now it finds one.

    `raw="about"` alone stays unbound (that hole is closed upstream by ledger.py's refusal), but
    "about three" is an approximation of three, exactly as "about 3" is.
    """
    from reconcile import detect_bound

    assert detect_bound("three", "design partners") is None
    assert detect_bound("about three", "design partners") == "approximate"
    assert detect_bound("about 3", "design partners") == "approximate"
    assert detect_bound("about", "design partners") is None
    assert (
        detect_bound("over three", "design partners") is None
    )  # the leading-word bound grammar wants a digit; unchanged


def test_a_spelled_out_range_is_a_range() -> None:
    from reconcile import parse_range

    assert parse_range("three-five") is None  # only the first cardinal is rewritten; a word range is not read
    assert parse_range("3-5") == (3.0, 5.0)
