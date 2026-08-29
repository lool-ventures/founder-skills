"""Property-based invariants over the priced-round solver.

WHY THIS EXISTS.

The example-based suite pins the solver at points a human chose, and a human chooses points where
the code is expected to work. The cap-implied SAFE defect and the anti-dilution ratchet-UP both sat
in regions nobody picked: a floor above the current conversion price, a self-referential denominator
under a cap that binds. Both are cases where a RELATIONSHIP between outputs breaks while every
individual number still looks plausible -- which is precisely what an example test cannot notice and
a property test is for. Hypothesis found the ratchet-up.

WHAT BELONGS HERE, AND WHAT DOES NOT.

Only relationships that are FALSIFIABLE BY THE IMPLEMENTATION. A property that restates how the code
computes something is theatre with extra machinery: it cannot fail, and it costs seconds per run. The
test to apply before adding one is "name the line I could change to break this". Every property below
names it.

Explicitly REJECTED as tautologies while writing this file:
  * "the ownership percentages sum to 1" IS kept -- but only because the numerators (founders,
    preferred-as-converted, pool) come from the itemised cap state while the denominator `post_fd`
    is accumulated separately at priced_round.py:1694. They can disagree, and that disagreement is
    the defect class this file exists for.
  * "new_money_shares * price == new_money" was DROPPED. `new_money_shares` is defined as
    new_money / price, so the identity is arithmetic and holds however wrong the price is.

MUTATION-VERIFIED, and one of these was a real save. Each property below was checked by breaking the
line it names and confirming the red:

  * phantom share added to `post_fd` (:1694)              -> partition, headline-terms
  * dilution inverted at `new_money_shares` (:1662)       -> monotonicity, headline-terms
  * entry-point floor rejection disabled (:1022)          -> anti-dilution ratchet-down

The save: the anti-dilution property originally PASSED against a reintroduced ratchet-up, because its
strategy omitted `ad_cp2_floor` and so never reached the clamp it named. A property test can be
vacuous in a way a coverage report cannot see -- the lines all execute. Measured after the fix, 49 of
60 examples reach the conversion-price assertion and 10 draw a floor above CP1, all correctly refused.

One mutation that did NOT kill anything, recorded so it is not re-derived as a gap: contaminating
`price = pre_money / pre_fd` (:992) with new money. That line is the fixed point's SEED, not its
answer -- the iteration converges to the same result from a different start. Mutating a seed proves
nothing about a solver.

DETERMINISM. `derandomize=True` fixes the seed so a green is reproducible and a red lands on the
commit that caused it, not on whichever examples CI drew that morning. That makes the `hypothesis`
pin in pyproject.toml load-bearing: the seed is ours, the generator is the library's.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from test_coupled_solver_goldens import solve  # noqa: E402

# Deliberately modest. These properties are cheap per example but each runs a full fixed-point solve;
# the value is in covering REGIONS, not in example count. Raise it when hunting, not in CI.
SETTINGS = settings(
    max_examples=60,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Ranges chosen to span real pre-seed/Series-A rounds and then some: a $250k friends-and-family on a
# 4M-share company through a $50M round on 100M shares.
_shares = st.integers(min_value=1_000_000, max_value=100_000_000)
_pool = st.integers(min_value=0, max_value=20_000_000)
_money = st.floats(min_value=250_000, max_value=50_000_000, allow_nan=False, allow_infinity=False)


def _ownership(r: dict[str, Any]) -> dict[str, Any]:
    agg: dict[str, Any] = r["aggregate_ownership_by_class"]
    return agg


@given(common=_shares, pool=_pool, pre_money=_money, new_money=_money)
@SETTINGS
def test_ownership_percentages_partition_unity(common: int, pool: int, pre_money: float, new_money: float) -> None:
    """Every share in the post-round denominator is attributed to exactly one class.

    THE LINE THIS CATCHES: `post_fd` (priced_round.py:1694) is accumulated from the round's deltas,
    while `founders_pct` / `preferred_pct` / `option_pool_pct` (:1729-1739) divide independently
    itemised counts by it. Nothing forces the two to describe the same company. If a holder class is
    dropped from the numerators, double-counted, or the denominator picks up shares no class owns,
    this sum drifts off 1 while every individual percentage still reads as a plausible number -- the
    exact signature of the cap-implied SAFE defect, where a self-referential denominator disagreed
    with the shares it was supposed to contain.
    """
    r = solve(
        common_shares=common,
        preferred_series=[],
        options_available=pool,
        pre_money=pre_money,
        new_money=new_money,
    )
    assume(r["completeness"] == "full")

    agg = _ownership(r)
    total = (
        agg["founders_pct"]
        + agg["preferred_pct"]
        + agg["option_pool_pct"]
        + agg["safe_pct"]
        + agg["note_pct"]
        + agg["new_money_pct"]
    )
    assert math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9), (
        f"ownership sums to {total!r}, not 1. post-round FD is "
        f"{r['post_round_fully_diluted_shares']:,} against breakdown {r['shares_breakdown']}"
    )


@given(common=_shares, pool=_pool, pre_money=_money, new_money=_money, extra=_money)
@SETTINGS
def test_more_new_money_never_increases_an_existing_holders_stake(
    common: int, pool: int, pre_money: float, new_money: float, extra: float
) -> None:
    """Selling more of the company at a fixed valuation cannot leave founders owning more of it.

    THE LINE THIS CATCHES: anything that mis-signs or mis-orders the dilution arithmetic -- a
    numerator/denominator swap, a topup charged to the wrong side, an AD adjustment applied with the
    wrong polarity. It is a statement about the ECONOMICS, so no rearrangement of the implementation
    can make it vacuous, and unlike a golden it holds across the whole input space rather than at one
    chosen point.

    Stated as a weak inequality on purpose: at very small `extra` the two solves can round to the
    same founder percentage, and demanding a strict decrease would fail on arithmetic, not on a bug.
    """
    base = solve(
        common_shares=common,
        preferred_series=[],
        options_available=pool,
        pre_money=pre_money,
        new_money=new_money,
    )
    more = solve(
        common_shares=common,
        preferred_series=[],
        options_available=pool,
        pre_money=pre_money,
        new_money=new_money + extra,
    )
    assume(base["completeness"] == "full" and more["completeness"] == "full")

    before = _ownership(base)["founders_pct"]
    after = _ownership(more)["founders_pct"]
    assert after <= before + 1e-9, (
        f"raising new money from ${new_money:,.0f} to ${new_money + extra:,.0f} at a fixed "
        f"${pre_money:,.0f} pre-money moved founders from {before:.6%} UP to {after:.6%}"
    )


@given(common=_shares, pool=_pool, pre_money=_money, new_money=_money)
@SETTINGS
def test_new_investor_ownership_equals_the_headline_terms(
    common: int, pool: int, pre_money: float, new_money: float
) -> None:
    """With nothing converting, the new investor owns exactly new / (pre + new).

    THE LINE THIS CATCHES: the price basis. `equity_financing_price` is pre_money divided by a
    pre-round fully-diluted count, and which count that is -- with or without the in-connection pool
    top-up, with or without converting securities -- is the single most consequential judgement call
    in the file. Get it wrong and every number downstream is internally consistent and collectively
    wrong, which is why this is asserted against the round's TERMS rather than against another
    computed output. It is the same shape of check as the cap-implied fix: tie the answer to
    something outside the computation.

    Scoped to rounds with no SAFEs or notes, where the identity is exact. With converting securities
    the new investor is diluted by them and the relation becomes an inequality, which is a materially
    weaker assertion; the goldens cover those paths at fixed points.
    """
    r = solve(
        common_shares=common,
        preferred_series=[],
        options_available=pool,
        pre_money=pre_money,
        new_money=new_money,
    )
    assume(r["completeness"] == "full")

    expected = new_money / (pre_money + new_money)
    actual = _ownership(r)["new_money_pct"]
    assert math.isclose(actual, expected, rel_tol=1e-6), (
        f"${new_money:,.0f} into a ${pre_money:,.0f} pre-money round should buy "
        f"{expected:.4%}; the solver priced it at {actual:.4%} "
        f"(PPS ${r['equity_financing_price']:.6f}, post-FD {r['post_round_fully_diluted_shares']:,})"
    )


@given(
    common=_shares,
    pool=_pool,
    pre_money=_money,
    new_money=_money,
    cp1=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
    pref_shares=st.integers(min_value=100_000, max_value=20_000_000),
    # THE POINT OF THIS STRATEGY. The floor is drawn across the whole range INCLUDING values above
    # CP1, because that is the region the defect lived in and the region no golden covered. An
    # earlier draft of this property omitted the floor entirely; it passed against a deliberately
    # reintroduced ratchet-up, since the un-floored BBWA path cannot produce one. A property that
    # cannot reach the guard it names is theatre, and this file's own docstring says so.
    floor_mult=st.one_of(st.none(), st.floats(min_value=0.1, max_value=3.0, allow_nan=False)),
)
@SETTINGS
def test_anti_dilution_never_raises_a_conversion_price(
    common: int,
    pool: int,
    pre_money: float,
    new_money: float,
    cp1: float,
    pref_shares: int,
    floor_mult: float | None,
) -> None:
    """Anti-dilution protects the holder; it can only ever lower the conversion price.

    THE LINE THIS CATCHES: the CP2 floor clamp (priced_round.py:576ff) and the entry-point rejection
    that now guards it. This property is the reason the file exists -- it FOUND the ratchet-up, where
    `ad_cp2_floor` sits above CP1 and the clamp raised CP2 past the price it was protecting.

    Two acceptable outcomes, and the assertion allows exactly these two: the solver REFUSES the round
    (a floor above CP1 is a contradictory charter term), or it solves and every adjusted conversion
    price is at or below where it started. What is forbidden is a converged, confident answer
    carrying a conversion price that moved up -- which is what shipped, warned about with a
    medium-severity code naming the clamp rather than the contradiction.
    """
    series: dict[str, Any] = {
        "series_id": "series_seed",
        "shares": pref_shares,
        "original_issue_price": cp1,
        "original_conversion_price": cp1,
        "current_conversion_price": cp1,
        "anti_dilution_protection": "broad_based_weighted_average",
    }
    if floor_mult is not None:
        series["ad_cp2_floor"] = cp1 * floor_mult

    r = solve(
        common_shares=common,
        preferred_series=[series],
        options_available=pool,
        pre_money=pre_money,
        new_money=new_money,
    )

    if r["completeness"] != "full":
        # Refusing is a valid outcome, but only for the stated reason. A round blocked by something
        # unrelated would let this property pass by accident on every example.
        # Constrained to a CLASS, not waved through: a round blocked for an unrelated reason (a
        # schema error, a bad instrument) would mean the strategy is generating nonsense and would let
        # this property pass by accident on every example. `E_SOLVER_*` is the family for "the fixed
        # point has no valid economic solution" -- random extremes reach it, e.g. a $50.00 conversion
        # price on 2M preferred shares against a $250k pre-money, where the preferred alone outvalues
        # the company by 400x. Declining to answer there is correct behaviour, not a miss.
        codes = {b.get("code") for b in (r.get("blockers") or [])}
        assert all(c == "E_AD_CP2_FLOOR_ABOVE_CURRENT_PRICE" or c.startswith("E_SOLVER_") for c in codes), codes
        return

    for sid, cp2 in (r.get("ccp_mutations") or {}).items():
        assert cp2 <= cp1 + 1e-9, (
            f"{sid}: anti-dilution moved the conversion price UP, ${cp1:.6f} -> ${cp2:.6f} "
            f"(floor {series.get('ad_cp2_floor')!r}). That is dilution wearing a protection's name."
        )


if __name__ == "__main__":  # pragma: no cover - convenience for hunting outside pytest
    pytest.main([__file__, "-q"])
