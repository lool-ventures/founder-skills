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
    Figure,
    Relation,
    _is_exact_count,
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
        quote="",
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
        ("1,700", "trial signups per month", None),
    ],
)
def test_detect_bound(raw: str, label: str, expected: str | None) -> None:
    assert detect_bound(raw, label) == expected


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
