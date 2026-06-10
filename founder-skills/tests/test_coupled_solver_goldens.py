"""Sprint 1 goldens — coupled-AD solver math verification.

Per docs/internal/2026-05-21-priced-round-coupled-solver-design.md §7.2,
v3 design. 15 active goldens (5, 14, 15 deferred per the same §7.2).

These tests now run against `priced_round.solve_priced_round` (Sprint 1's
AdjusterProtocol-wired solver). Sprint 0's spike has been absorbed; the
goldens persist as the v0.4.0 regression suite.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

# Import priced_round.solve_priced_round
SOLVER_PATH = pathlib.Path(__file__).parent.parent / "skills" / "cap-table" / "scripts" / "priced_round.py"
spec = importlib.util.spec_from_file_location("priced_round", SOLVER_PATH)
assert spec and spec.loader
priced_round = importlib.util.module_from_spec(spec)
spec.loader.exec_module(priced_round)


def _make_cap_state(
    common_shares: int,
    preferred_series: list[dict[str, Any]],
    options_outstanding: int = 0,
    options_available: int = 0,
    cap_table_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a cap_state dict in the canonical shape for solve_priced_round."""
    preferred_as_converted = 0
    for s in preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", s.get("original_issue_price", 1.0)))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp == 0:
            preferred_as_converted += shares
        else:
            preferred_as_converted += int(round(shares * (ocp / ccp)))

    fd = common_shares + preferred_as_converted + options_outstanding + options_available

    cap_state = {
        "founders": [{"name": "Founder A", "common_shares": common_shares}],
        "preferred_series": preferred_series,
        "as_converted_totals": {
            "common_shares": common_shares,
            "preferred_shares_as_converted": preferred_as_converted,
            "options_outstanding": options_outstanding,
            "options_available": options_available,
            "fully_diluted_shares": fd,
        },
        "option_pool": {
            "plan_type": "iso",
            "authorized": options_outstanding + options_available,
            "issued_and_outstanding": options_outstanding,
            "available_for_grant": options_available,
        },
    }
    if cap_table_history:
        cap_state["cap_table_history"] = cap_table_history
    return cap_state


def solve(
    *,
    common_shares: int,
    preferred_series: list[dict[str, Any]],
    options_outstanding: int = 0,
    options_available: int = 0,
    safes: list[dict[str, Any]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    pre_money: float,
    new_money: float,
    target_pool_percent: float | None = None,
    cap_table_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper bridging the spike's call signature to solve_priced_round."""
    cs = _make_cap_state(
        common_shares=common_shares,
        preferred_series=preferred_series,
        options_outstanding=options_outstanding,
        options_available=options_available,
        cap_table_history=cap_table_history,
    )
    return priced_round.solve_priced_round(  # type: ignore[no-any-return]
        cap_state=cs,
        safes=safes or [],
        notes=notes or [],
        pre_money=pre_money,
        new_money=new_money,
        target_pool_percent=target_pool_percent,
    )


# ---------------------------------------------------------------------------
# Goldens 4 and 18 are SPRINT 0 DEFERRED — they require SAFE/note conversion
# math wired into the spike's `convert_securities` stage. Sprint 1's
# AdjusterProtocol (SafeConversionAdjuster + NoteConversionAdjuster) provides
# this; these tests are now active.
# ---------------------------------------------------------------------------
def test_golden_4_ad_plus_safe_conversion() -> None:
    """AD + SAFE @ $10M post-money cap: SAFE converts at cap-implied; AD
    triggers off new PPS only (SAFE conversion is NVCA-default-carved-out).

    Inputs: founder 10M + Series Seed 2M (OIP=$1, BBWA broad) + 1M pool,
    one SAFE: $500k @ $10M post-money cap (yc_postmoney_cap), $5M @ $5M pre.
    """
    safe = {
        "id": "safe_a",
        "investor_name": "Angel A",
        "purchase_amount": 500_000.0,
        "form": "yc_postmoney_cap",
        "post_money_valuation_cap": 10_000_000.0,
        "pre_money_valuation_cap": None,
        "discount_multiplier": None,
    }
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        safes=[safe],
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
    )

    assert r["converged"], f"did not converge: {r.get('blockers')}"
    # SAFE conversion fired (cap-implied price < equity_financing_price)
    assert r["per_safe"]["safe_a"]["branch"] != "rejected"
    assert r["shares_breakdown"]["safe_converted"] > 0
    # AD adjustment fired on Series Seed (new_pps < OIP=$1.00)
    assert len(r.get("anti_dilution_breakdown", [])) == 1
    assert r["anti_dilution_breakdown"][0]["series_id"] == "series_seed"
    # SAFE conversion did NOT enter AD's B/C — verify B uses only new_money
    bd = r["anti_dilution_breakdown"][0]
    # B = consideration / CP1; consideration in v0.4.0 = new_money only.
    assert abs(bd["B"] - 5_000_000.0) < 1.0  # 5M / 1.00 = 5M shares


def test_golden_18_ad_plus_note_convert_at_cap_maturity() -> None:
    """Note converts at cap on the round + AD-protected preferred series.

    Note conversion is NVCA-default carved-out from AD trigger. Verify the
    note's conversion shares don't re-trigger or amplify AD on Series Seed.

    Inputs: founder 10M + Series Seed 2M (OIP=$1, BBWA broad) + 1M pool,
    one note: $1M principal @ $8M cap, 0% interest, qualified financing.
    $5M @ $5M pre.
    """
    note = {
        "id": "note_a",
        "investor_name": "Lender L",
        "principal": 1_000_000.0,
        "annual_interest_rate": 0.0,
        "day_count_basis": 365,
        "compounding_periods_per_year": None,
        "interest_converts_to_shares": True,
        "issuance_date": "2024-01-01",
        "valuation_cap": 8_000_000.0,
        "discount_multiplier": None,
        "capitalization_denominator": 13_000_000,
        "capitalization_denominator_policy": "pre-money fully diluted",
        "qualified_financing_threshold": 1_000_000.0,
        "maturity_date": "2026-01-01",
        "maturity_default_treatment": "convert_at_cap",
        "maturity_conversion_price_override": None,
        "non_qualified_financing_treatment": "negotiate",
    }
    # solve() wrapper doesn't pass conversion_event_date; call priced_round directly.
    cs = _make_cap_state(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
    )
    r = priced_round.solve_priced_round(
        cap_state=cs,
        safes=[],
        notes=[note],
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
        conversion_event_date="2025-06-01",
    )

    assert r["converged"], f"did not converge: {r.get('blockers')}"
    # Note converted
    assert r["per_note"]["note_a"]["branch"] in {
        "cap_conversion",
        "discount_only",
        "maturity_convert_at_cap",
    }
    assert r["shares_breakdown"]["note_converted"] > 0
    # AD fired on Series Seed
    assert len(r.get("anti_dilution_breakdown", [])) == 1
    bd = r["anti_dilution_breakdown"][0]
    # B = consideration / CP1; consideration in v0.4.0 = new_money only (note carved out)
    assert abs(bd["B"] - 5_000_000.0) < 1.0


# ---------------------------------------------------------------------------
# Golden 1 — Test A (BBWA broad, fully coupled)
# Per v3 §3.8: p* = 5/14 = 0.35714, CP2 = 0.66667, founder = 35.71%, f'(p*) = 0.111
# ---------------------------------------------------------------------------
def test_golden_1_bbwa_test_a() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
    )

    assert r["converged"] is True
    assert r["iterations"] <= 20
    assert abs(r["equity_financing_price"] - 0.357142857) < 1e-6
    agg = r["aggregate_ownership_by_class"]
    assert abs(agg["founders_pct"] - 0.357142857) < 1e-6
    assert abs(agg["founders_pct_pre_anti_dilution"] - 0.384615385) < 1e-6
    assert abs(agg["anti_dilution_delta_pct_points"] - (-2.747)) < 0.01

    cp2 = r["ccp_mutations"]["series_seed"]
    assert abs(cp2 - 0.666666667) < 1e-6

    bd = r["anti_dilution_breakdown"]
    assert len(bd) == 1
    assert bd[0]["series_id"] == "series_seed"
    assert bd[0]["protection_type"] == "broad_based_weighted_average"
    assert abs(bd[0]["ccp_after"] - 0.666666667) < 1e-6
    assert bd[0]["floor_applied"] is False
    assert bd[0]["A"] == 13_000_000


# ---------------------------------------------------------------------------
# Golden 2 — Full ratchet. Per v3 §3.9: p* = 3/11 = 0.27273, founder = 27.27%.
# ---------------------------------------------------------------------------
def test_golden_2_full_ratchet() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "full_ratchet",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
    )

    assert r["converged"] is True
    assert abs(r["equity_financing_price"] - 0.272727273) < 1e-6
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.272727273) < 1e-6
    cp2 = r["ccp_mutations"]["series_seed"]
    assert abs(cp2 - 0.272727273) < 1e-6
    bd = r["anti_dilution_breakdown"]
    assert len(bd) == 1
    assert bd[0]["protection_type"] == "full_ratchet"
    assert bd[0]["B"] is None
    assert bd[0]["C"] is None


# ---------------------------------------------------------------------------
# Golden 3 — Multi-series mixed (BBWA broad + full ratchet).
# Closed-form via opus subagent: p* = 113/333.
# ---------------------------------------------------------------------------
def test_golden_3_multi_series_mixed() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_a",
                "shares": 1_000_000,
                "original_issue_price": 2.00,
                "original_conversion_price": 2.00,
                "current_conversion_price": 2.00,
                "anti_dilution_protection": "broad_based_weighted_average",
                "ad_a_denominator_basis": "nvca_broad",
            },
            {
                "series_id": "series_b",
                "shares": 500_000,
                "original_issue_price": 1.50,
                "original_conversion_price": 1.50,
                "current_conversion_price": 1.50,
                "anti_dilution_protection": "full_ratchet",
            },
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=3_000_000.0,
    )

    assert r["converged"]
    assert abs(r["equity_financing_price"] - 113.0 / 333.0) < 1e-5
    assert abs(r["ccp_mutations"]["series_a"] - 1.312072) < 1e-3
    assert abs(r["ccp_mutations"]["series_b"] - 113.0 / 333.0) < 1e-5
    agg = r["aggregate_ownership_by_class"]
    assert abs(agg["founders_pct"] - 0.4242) < 1e-3
    assert abs(agg["founders_pct_pre_anti_dilution"] - 0.50) < 1e-5
    assert agg["anti_dilution_delta_pct_points"] < -7.0
    assert len(r["anti_dilution_breakdown"]) == 2


# ---------------------------------------------------------------------------
# Golden 6 — No-AD control. Pre-v0.4.0-compatible output (no AD fields).
# ---------------------------------------------------------------------------
def test_golden_6_no_ad_control() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "none",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
    )

    assert abs(r["equity_financing_price"] - 0.384615385) < 1e-6
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.384615385) < 1e-6
    # No AD breakdown emitted
    assert "anti_dilution_breakdown" not in r
    assert "founders_pct_pre_anti_dilution" not in r["aggregate_ownership_by_class"]


# ---------------------------------------------------------------------------
# Golden 7 — Up round (no trigger).
# ---------------------------------------------------------------------------
def test_golden_7_up_round_no_trigger() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=30_000_000.0,
        new_money=5_000_000.0,
    )

    # Adjuster ran but no series triggered → no AD breakdown emitted
    assert "anti_dilution_breakdown" not in r
    assert abs(r["equity_financing_price"] - 2.307692308) < 1e-6
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.659340659) < 1e-6


# ---------------------------------------------------------------------------
# Golden 8 — Pre-existing AD-adjusted CCP=$0.80 from prior round.
# Spike-verified: PPS=$0.343625, CP2=$0.563322 (closed-form) / $0.563265 (spike).
# ---------------------------------------------------------------------------
def test_golden_8_preexisting_ad_adjusted_ccp() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 0.80,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
        cap_table_history=[
            {
                "event_type": "anti_dilution_applied",
                "series_id": "series_seed",
                "previous_ccp": 1.00,
                "new_ccp": 0.80,
            }
        ],
    )

    assert r["converged"]
    assert abs(r["equity_financing_price"] - 0.343625) < 1e-4
    # CP2 closed-form is 0.563322; solver returns ~0.563265 (Δ=5.7e-5) due
    # to per-iter int(round) on preferred_as_converted (production semantic).
    assert abs(r["ccp_mutations"]["series_seed"] - 0.563265) < 1e-4
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.343625) < 1e-4
    # No stale-CCP warning (cap_table_history records the prior CCP change)
    warnings = r.get("warnings", [])
    assert all(w.get("code") != "W_STALE_CCP_SUSPECTED" for w in warnings)
    bd = r["anti_dilution_breakdown"][0]
    assert abs(bd["B"] - 6_250_000.0) < 1.0  # 5M / 0.80 = 6.25M shares
    assert bd["A"] == 13_500_000  # 10M + 2.5M + 1M


# ---------------------------------------------------------------------------
# Golden 9 — ad_trigger_basis override (CCP vs OIP).
# ---------------------------------------------------------------------------
def test_golden_9_ad_trigger_basis_override() -> None:
    base = dict(
        common_shares=10_000_000,
        options_available=1_000_000,
        pre_money=12_150_000.0,
        new_money=5_000_000.0,
    )
    series_template = {
        "series_id": "series_seed",
        "shares": 2_000_000,
        "original_issue_price": 1.00,
        "original_conversion_price": 1.00,
        "current_conversion_price": 0.80,
        "anti_dilution_protection": "broad_based_weighted_average",
    }

    r_ccp = solve(
        preferred_series=[{**series_template, "ad_trigger_basis": "current_conversion_price"}],
        **base,  # type: ignore[arg-type]
    )
    r_oip = solve(preferred_series=[series_template], **base)  # type: ignore[arg-type]

    assert abs(r_ccp["equity_financing_price"] - 0.90) < 1e-5
    assert abs(r_oip["equity_financing_price"] - 0.90) < 1e-5
    # CCP-trigger: no breakdown (no AD trigger fires; new_pps > CCP)
    assert "anti_dilution_breakdown" not in r_ccp
    # OIP-trigger: breakdown emitted (trigger fires; but BBWA inner short-circuits since new_pps > CP1=CCP=$0.80)
    assert len(r_oip.get("anti_dilution_breakdown", [])) == 1
    # CP2 unchanged in both (BBWA's inner short-circuit: new_pps > CP1)
    assert r_ccp["ccp_mutations"]["series_seed"] == 0.80
    assert r_oip["ccp_mutations"]["series_seed"] == 0.80


# ---------------------------------------------------------------------------
# Golden 10 — CP2 floor enforcement.
# ---------------------------------------------------------------------------
def test_golden_10_cp2_floor_enforcement() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
                "ad_cp2_floor": 0.50,
            }
        ],
        options_available=1_000_000,
        pre_money=1_000_000.0,
        new_money=5_000_000.0,
    )

    assert r["converged"]
    assert abs(r["equity_financing_price"] - 0.066667) < 1e-5
    bd = r["anti_dilution_breakdown"][0]
    assert bd["floor_applied"] is True
    assert abs(bd["ccp_unfloored"] - 0.204545) < 1e-5
    assert bd["ccp_after"] == 0.50
    warnings = r.get("warnings", [])
    assert any(w.get("code") == "W_CP2_FLOOR_APPLIED" for w in warnings)


# ---------------------------------------------------------------------------
# Golden 11 — Stale-CCP guard fires.
# ---------------------------------------------------------------------------
def test_golden_11_stale_ccp_guard_fires() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,  # == OCP, looks fresh
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
        cap_table_history=[
            {
                "event_type": "anti_dilution_applied",
                "series_id": "series_seed",
                "previous_ccp": 1.00,
                "new_ccp": 0.80,
            }
        ],
    )

    warnings = r.get("warnings", [])
    assert any(w.get("code") == "W_STALE_CCP_SUSPECTED" for w in warnings)
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.357143) < 1e-5


# ---------------------------------------------------------------------------
# Golden 12 — Multi-series, different a_denominator_basis (broad vs narrow).
# ---------------------------------------------------------------------------
def test_golden_12_multi_series_different_a_basis() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_a",
                "shares": 1_000_000,
                "original_issue_price": 2.00,
                "original_conversion_price": 2.00,
                "current_conversion_price": 2.00,
                "anti_dilution_protection": "broad_based_weighted_average",
                "ad_a_denominator_basis": "nvca_broad",
            },
            {
                "series_id": "series_b",
                "shares": 500_000,
                "original_issue_price": 1.50,
                "original_conversion_price": 1.50,
                "current_conversion_price": 1.50,
                "anti_dilution_protection": "narrow_based_weighted_average",
                "ad_a_denominator_basis": "nvca_narrow",
            },
        ],
        options_outstanding=200_000,
        options_available=800_000,
        pre_money=5_000_000.0,
        new_money=3_000_000.0,
    )

    assert r["converged"]
    assert abs(r["equity_financing_price"] - 0.379470) < 1e-5
    assert abs(r["ccp_mutations"]["series_a"] - 1.372164) < 1e-3
    assert abs(r["ccp_mutations"]["series_b"] - 1.043476) < 1e-3
    assert abs(r["aggregate_ownership_by_class"]["founders_pct"] - 0.4743) < 1e-3
    bd_a = next(b for b in r["anti_dilution_breakdown"] if b["series_id"] == "series_a")
    bd_b = next(b for b in r["anti_dilution_breakdown"] if b["series_id"] == "series_b")
    assert bd_a["A"] == 12_500_000
    assert bd_b["A"] == 11_500_000
    assert bd_a["A"] > bd_b["A"]


# ---------------------------------------------------------------------------
# Golden 13 — anti_dilution_protection=none despite cap_table_history.
# ---------------------------------------------------------------------------
def test_golden_13_none_protection_despite_history() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 0.80,
                "anti_dilution_protection": "none",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=5_000_000.0,
        cap_table_history=[
            {
                "event_type": "anti_dilution_applied",
                "series_id": "series_seed",
                "previous_ccp": 1.00,
                "new_ccp": 0.80,
            }
        ],
    )

    # No AD applied (protection=none short-circuits at the has_ad_protection gate)
    assert "anti_dilution_breakdown" not in r
    warnings = r.get("warnings", [])
    assert all(w.get("code") != "W_STALE_CCP_SUSPECTED" for w in warnings)


# ---------------------------------------------------------------------------
# Golden 16 — Zero new_money (extension via SAFE only; AD essentially no-op).
# ---------------------------------------------------------------------------
def test_golden_16_zero_new_money_safe_only() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=5_000_000.0,
        new_money=1.0,  # negligible
    )

    cp2 = r["ccp_mutations"]["series_seed"]
    assert cp2 > 0.99999


# ---------------------------------------------------------------------------
# Golden 17 — Boundary case new_pps == OIP. Strict `<` → no trigger.
# ---------------------------------------------------------------------------
def test_golden_17_boundary_new_pps_equals_oip() -> None:
    r = solve(
        common_shares=10_000_000,
        preferred_series=[
            {
                "series_id": "series_seed",
                "shares": 2_000_000,
                "original_issue_price": 1.00,
                "original_conversion_price": 1.00,
                "current_conversion_price": 1.00,
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ],
        options_available=1_000_000,
        pre_money=13_000_000.0,
        new_money=13_000_000.0,
    )

    assert abs(r["equity_financing_price"] - 1.00) < 1e-6
    assert r["ccp_mutations"]["series_seed"] == 1.00
    assert "anti_dilution_breakdown" not in r
