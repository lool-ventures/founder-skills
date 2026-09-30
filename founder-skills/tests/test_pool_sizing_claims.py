"""The judge the paid cap-table lane uses on the coach's pool-sizing sentences, tested for free.

`assert_pool_basis_commentary_matches_inputs`, the check it replaces, was measured wrong both ways:
it failed two correct sentences that cite the computed figure (each judged the second sentence alone, or
flagged "pre-money pool" as a claim about this deal) and passed a wrong one (any sentence naming both
bases was exempt) and a bullet list stating a wrong basis (it split only on sentence punctuation). A paid
lane judged by an unfalsified instrument can red on the very fix it is meant to confirm, so the judge is
pinned here on a labelled table before any paid run relies on it.

Every case below: modeled sizing post-money, founders 63.0% as modeled and 64.8% on the other sizing -- the
numbers the real e2e fixture produces.
"""

from __future__ import annotations

from typing import Any

import pytest
from _pool_sizing_claims import (
    FOOTER_PREFIX,
    INCREASE_LINE_LEAD,
    REPORT_LINE_LEAD,
    coaching_body,
    counterfactual_lever_problems,
    increase_reading_lever_problems,
    pool_sizing_problems,
)

MODELED = "post_money"
OTHER_FOUNDERS_PCT = 64.8

# The coaching paragraph a real run delivered: it named no number, gave the wrong mechanism, and was
# flagged by the old check for the wrong reason ("advises negotiating for what the founder already has").
REAL_FAILED_RUN = (
    "The number to protect in negotiation is the pool basis: if you can negotiate a pre-money pool "
    "(where the pool is sized before the pre-money valuation is struck, not after), the dilution from "
    "the top-up shifts slightly."
)

SYNTHETIC_CORRECT = (
    "Your option pool is sized as 10% of the post-round share count (post-money basis), and founders "
    "finish at 63.0%.\n"
    "- Sized as 10% of the pre-round share count instead (pre-money basis), the pool would be smaller and "
    "founders would hold 64.8%.\n"
    "- Under both sizings the pool is created before the round's price is set, so the holders before the "
    "round carry it."
)

CASES = [
    # (label, text, expected_ok)
    (
        "cited, two sentences",
        "Your pool is sized post-money, leaving founders at 63.0%. A pre-money pool would leave founders at 64.8% "
        "instead.",
        True,
    ),
    (
        "cited, one sentence",
        "If you can negotiate a pre-money pool, founders would hold 64.8% rather than 63.0%.",
        True,
    ),
    ("cited within rounding", "A pre-money pool would leave founders at about 64.7%.", True),
    ("wrong basis, names both", "The pool is sized pre-money, not post-money, so founders bear it.", False),
    ("wrong basis in a bullet with no full stop", "- pool is pre-money\n- valuation is post-money", False),
    ("uncited other-sizing advice", "Negotiating a pre-money pool would help you.", False),
    ("wrong number", "A pre-money pool would give founders 66.0%.", False),
    ("the real failed run", REAL_FAILED_RUN, False),
    ("wrong mechanism alone", "The pool is carved out after the round, so investors share it.", False),
    ("synthetic correct commentary", SYNTHETIC_CORRECT, True),
    (
        "valuation, not a pool claim",
        "At a $12M pre-money valuation with a 10% post-money pool, founders finish at 63.0%.",
        True,
    ),
    ("fallback sentence", "Confirm that the term sheet's pool basis matches the one modeled (post-money).", True),
    ("no pool talk at all", "The SAFE converts at its cap, and the round prices at $1.18 a share.", True),
    # The old check exempted these two on purpose; under the grounded rule the coach may raise the other
    # sizing only with its computed numbers, so an uncited explainer or question is a problem.
    (
        "uncited general explainer",
        "Pre-money pool sizing lands the dilution on existing shareholders; post-money spreads it.",
        False,
    ),
    ("uncited question to the founder", "Is your pool sized pre-money or post-money?", False),
    # The payload's own labels never say "pool"; a sentence built from them is still judged on its number.
    (
        "label phrasing, wrong figure",
        "Sized as unallocated options equal to 10% of the pre-round share count (pre-money basis) instead, founders "
        "would hold 70.0% (vs 63.0% as modeled).",
        False,
    ),
    ("basis phrasing, wrong figure", "On a pre-money basis instead, founders would hold 70.0%.", False),
    (
        "label phrasing, right figure",
        "On the other sizing (unallocated options equal to 10% of the pre-round share count (pre-money basis)), "
        "founders would hold 64.8% instead of 63.0%.",
        True,
    ),
    ("recommends the other sizing", "Push your lead to size the pool pre-money: founders would hold 64.8%.", False),
    (
        "new investors carry the pool",
        "A post-money pool is shared with the new investors; on a pre-money pool founders would hold 64.8%.",
        False,
    ),
    (
        "negation restates the modeled basis",
        "Your pool is sized post-money, not pre-money, so founders hold 63.0%.",
        True,
    ),
    ("negation alone", "The pool is sized post-money, not pre-money.", True),
    (
        "conditional about the other sizing",
        "Your option pool would be smaller if sized pre-money: founders 64.8% instead of 63.0%.",
        True,
    ),
    ("two-decimal citation", "A pre-money pool would leave founders at 64.83%.", True),
]


@pytest.mark.parametrize(("label", "text", "expected_ok"), CASES, ids=[c[0] for c in CASES])
def test_pool_sizing_judgement(label: str, text: str, expected_ok: bool) -> None:
    problems = pool_sizing_problems(text, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT)
    assert (not problems) is expected_ok, (label, problems)


def test_with_no_computed_figure_any_other_sizing_advice_is_a_problem() -> None:
    """When the counterfactual was not computed, the coach's only option is the fallback sentence."""
    cited = "A pre-money pool would leave founders at 64.8%."
    assert pool_sizing_problems(cited, modeled_basis=MODELED, other_founders_pct=None)
    fallback = "Confirm that the term sheet's pool basis matches the one modeled (post-money)."
    assert not pool_sizing_problems(fallback, modeled_basis=MODELED, other_founders_pct=None)


def test_the_judge_is_symmetric_for_a_pre_money_deal() -> None:
    wrong = "Your pool is sized post-money."
    assert pool_sizing_problems(wrong, modeled_basis="pre_money", other_founders_pct=61.2)
    cited = "A post-money pool would leave founders at 61.2%."
    assert not pool_sizing_problems(cited, modeled_basis="pre_money", other_founders_pct=61.2)


def _scenarios(*statuses: str | None) -> dict[str, Any]:
    return {
        "scenarios": [
            {"computed_outputs": {} if s is None else {"pool_sizing_counterfactual": {"status": s}}} for s in statuses
        ]
    }


def test_the_lever_check_needs_a_computed_block_and_the_report_line() -> None:
    line = f"{REPORT_LINE_LEAD} Sized as 10% of the pre-round share count (pre-money basis) instead: founders 64.8%."
    assert not counterfactual_lever_problems(_scenarios("computed"), line)
    assert counterfactual_lever_problems(_scenarios("unavailable", None), line)
    assert counterfactual_lever_problems(_scenarios(), line)
    assert counterfactual_lever_problems(_scenarios("computed"), "no such line")


def test_with_several_scenarios_a_citation_may_match_any_computed_figure() -> None:
    text = "A pre-money pool would leave founders at 61.2%."
    assert not pool_sizing_problems(text, modeled_basis=MODELED, other_founders_pct=[64.8, 61.2])
    assert pool_sizing_problems(text, modeled_basis=MODELED, other_founders_pct=[64.8, 59.0])


# ---------------------------------------------------------------------------
# The "only the new options" reading. When a post-money target sits beside existing unallocated options and
# the founder never said what the percentage counts, the model reads it as the pool available after the round
# and computes the other reading (new options alone) beside it. The coach may state that reading's figure only
# by citing it. Every case: modeled founders 63.6%, new-options-only reading 62.2%, pre-money comparison 64.8%.
# ---------------------------------------------------------------------------

MODELED_FOUNDERS = 63.6
INCREASE_FOUNDERS = 62.2
# The label the payload hands the coach for this reading -- pinned from the code below, so a label change that
# the judge no longer recognises reds this table instead of silently skipping the coach's sentences.
INCREASE_LABEL = (
    "new options equal to 10% of the fully diluted share count after the round, on top of the existing unallocated "
    "options"
)

INCREASE_CASES = [
    (
        "label phrasing, cited",
        f"If your term sheet means {INCREASE_LABEL}, founders would hold 62.2% instead of 63.6%.",
        True,
    ),
    ("paraphrase, cited", "If the 10% counts only the new options, founders would hold 62.2%.", True),
    (
        "the caveat with no figure",
        "The pool was read as the pool available after the round; confirm with counsel whether your term sheet "
        "sizes only the new options.",
        True,
    ),
    (
        "pre-money comparison figure attached to this reading",
        "If the 10% counts only the new options, founders would hold 64.8%.",
        False,
    ),
    (
        "the comparison's figure beside this one, with no words for the comparison",
        "If the 10% counts only the new options, founders would hold 62.2% or 64.8%.",
        False,
    ),
    (
        "all three readings in one sentence, each named",
        "If it sizes only the new options, founders would hold 62.2% instead of 63.6%; on the pre-round share "
        "count they would hold 64.8%.",
        True,
    ),
    (
        "this reading, cited, set apart from the comparison by name",
        "Separately from the pre-money comparison, if your term sheet sizes only the new options, founders would "
        "hold 62.2% instead of 63.6%.",
        True,
    ),
    (
        "the comparison, cited, contrasted with this reading",
        "If the pool were sized pre-money, founders would hold 64.8%; that is different from a term sheet that "
        "sizes only the new options.",
        True,
    ),
    (
        "the comparison, cited, using the words 'the new options added'",
        "On a pre-money pool the new options added are fewer, so founders would hold 64.8%.",
        True,
    ),
    (
        "this reading, cited, recommending the other sizing",
        "If it sizes only the new options, founders would hold 62.2%, so push for a pre-money pool.",
        False,
    ),
    (
        "modeled figure passed off as this reading",
        "If it sizes only the new options, founders would hold 63.6%.",
        False,
    ),
    ("estimate", "If the 10% counts only the new options, founders would hold roughly 61%.", False),
    ("paraphrased estimate outside the phrase list", "The top-up would be larger, leaving founders near 60%.", False),
]


@pytest.mark.parametrize(("label", "text", "expected_ok"), INCREASE_CASES, ids=[c[0] for c in INCREASE_CASES])
def test_increase_reading_judgement(label: str, text: str, expected_ok: bool) -> None:
    problems = pool_sizing_problems(
        text,
        modeled_basis=MODELED,
        other_founders_pct=OTHER_FOUNDERS_PCT,
        increase_founders_pct=INCREASE_FOUNDERS,
        target_pct=10.0,
        known_figures=[MODELED_FOUNDERS, OTHER_FOUNDERS_PCT, INCREASE_FOUNDERS, 10.0],
    )
    assert (not problems) is expected_ok, (label, problems)


def test_the_pinned_label_is_the_one_the_payload_hands_the_coach() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[1] / "skills" / "cap-table" / "scripts"))
    try:
        import compose_report  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    assert compose_report._pool_sizing_label("post_money_increase", 0.10) == INCREASE_LABEL


def test_with_no_increase_figure_computed_any_figure_for_that_reading_is_a_problem() -> None:
    text = "If the 10% counts only the new options, founders would hold 62.2%."
    kw: dict[str, Any] = {"modeled_basis": MODELED, "other_founders_pct": OTHER_FOUNDERS_PCT, "target_pct": 10.0}
    assert pool_sizing_problems(text, increase_founders_pct=None, **kw)
    # With none computed, the reading is not the commentary's to raise at all, figure or not: a coach invented
    # "or only the new options being added" for a deal where nothing asked it, and no figure was there to catch.
    caveat = "Confirm with counsel whether the 10% in your term sheet sizes only the new options."
    assert pool_sizing_problems(caveat, increase_founders_pct=None, **kw)
    invented = "The pool question is whether the 10% covers the pool as a whole or only the new options being added."
    assert pool_sizing_problems(invented, increase_founders_pct=None, **kw)
    # With the reading computed, the caveat stays grounded.
    assert not pool_sizing_problems(caveat, increase_founders_pct=62.2, **kw)


def test_the_closed_world_check_is_off_unless_known_figures_are_given() -> None:
    """Existing callers pass no `known_figures`; their behaviour must not change."""
    text = "The top-up would be larger, leaving founders near 60%."
    assert not pool_sizing_problems(text, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT)
    assert pool_sizing_problems(
        text, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT, known_figures=[MODELED_FOUNDERS]
    )


def _increase_scenarios(status: str | None, *, disclosed: bool = True) -> dict[str, Any]:
    co: dict[str, Any] = {"warnings": [{"code": "W_POOL_BASIS_READING_NOT_CONFIRMED"}] if disclosed else []}
    if status is not None:
        co["pool_increase_reading"] = {"status": status}
    return {"scenarios": [{"computed_outputs": co}]}


def test_the_increase_lever_check_needs_the_disclosure_a_computed_block_and_the_report_line() -> None:
    page = f"{INCREASE_LINE_LEAD} 1,285,714 new options instead of 1,057,143; founders 62.2% (vs 63.6% as modeled)."
    assert not increase_reading_lever_problems(_increase_scenarios("computed"), page)
    assert increase_reading_lever_problems(_increase_scenarios("computed", disclosed=False), page)
    assert increase_reading_lever_problems(_increase_scenarios("unavailable"), page)
    assert increase_reading_lever_problems(_increase_scenarios(None), page)
    assert increase_reading_lever_problems(_increase_scenarios("computed"), "no such line")


# --- a bare "pre-money" used as the valuation is not a sizing claim --------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_ok"),
    [
        ("That math is straightforward and non-negotiable once pre-money and raise size are agreed.", True),
        ("Once the pre-money is agreed, the pool top-up follows.", True),
        ("The pool is set once the pre-money valuation is fixed.", True),
        # Still sizing claims: the valuation cue must not open a hole.
        ('This is the standard "pre-money pool" dynamic: founders pay for the option pool.', False),
        ("Confirm with counsel which pool sizing the term sheet uses: post-money (as modeled) or pre-money.", False),
        ("The pool is sized on a pre-money basis.", False),
    ],
)
def test_a_valuation_pre_money_is_not_the_other_sizing(text: str, expected_ok: bool) -> None:
    problems = pool_sizing_problems(text, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT)
    assert (not problems) is expected_ok, (text, problems)


def test_raise_size_does_not_make_a_sentence_about_pool_sizing() -> None:
    """ "size" in "raise size" is not the pool being sized; "sized" about the pool still is."""
    ok = "The raise size and the round size are both set by the lead."
    assert not pool_sizing_problems(ok, modeled_basis=MODELED, other_founders_pct=None)
    assert pool_sizing_problems(
        "The options are sized on a pre-money basis.", modeled_basis=MODELED, other_founders_pct=None
    )


# --- the whole commentary is judged ------------------------------------------------------------------------


def test_the_commentary_is_judged_past_its_own_horizontal_rules() -> None:
    """The lanes cut the commentary at its first "\n---", so one run was judged on 490 of 4,570 characters.
    The cut is the report's generated footer, which follows the commentary."""
    md = (
        "# Report\n\n## Coaching Commentary\n\nFirst part.\n\n---\n\nA pre-money pool, said after a rule.\n\n"
        f"---\n\n{FOOTER_PREFIX}(https://x) by lool ventures*\n"
    )
    body = coaching_body(md)
    assert body is not None
    assert "said after a rule" in body and FOOTER_PREFIX not in body
    assert pool_sizing_problems(body, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT)


def test_the_footer_prefix_is_the_one_insert_coaching_writes() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "insert_coaching.py"
    spec = importlib.util.spec_from_file_location("insert_coaching_footer", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.FOOTER_PREFIX == FOOTER_PREFIX


def test_a_report_with_no_commentary_has_no_body() -> None:
    assert coaching_body("# Report\n\nNo commentary here.\n") is None


# --- the report's own measure words are the other sizing too ---------------------------------------------------


def test_the_measure_named_by_its_share_count_is_the_other_sizing() -> None:
    """The report names the measures by the share count they count ("the fully diluted share count before the
    round"); a coach echoing those words about the other measure is judged like one saying "pre-money"."""
    bare = "The pool could also be 10% of the fully diluted share count before the round."
    assert pool_sizing_problems(bare, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT)
    cited = "If the pool were 10% of the fully diluted share count before the round, founders would hold 64.8%."
    assert not pool_sizing_problems(
        cited, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT, target_pct=10.0
    )
    # The modeled measure's own words are not the other sizing.
    own = "The pool is 10% of the fully diluted share count after the round."
    assert not pool_sizing_problems(own, modeled_basis=MODELED, other_founders_pct=OTHER_FOUNDERS_PCT, target_pct=10.0)
