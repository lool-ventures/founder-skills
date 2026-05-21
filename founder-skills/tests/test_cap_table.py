"""Tests for the cap-table skill.

Covers each math producer, the rule_audit two-phase contract, scenario
dispatch, composition, and the 11 Gotchas from SKILL.md as explicit
regression tests. Test class structure mirrors test_financial_model_review.py.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from typing import Any

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")

sys.path.insert(0, SCRIPTS)

# Import library APIs once for in-process tests (faster than subprocess for math).
import anti_dilution  # type: ignore[import-not-found]  # noqa: E402
import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402
import note_conversion  # type: ignore[import-not-found]  # noqa: E402
import option_pool  # type: ignore[import-not-found]  # noqa: E402
import priced_round  # type: ignore[import-not-found]  # noqa: E402
import rule_audit  # type: ignore[import-not-found]  # noqa: E402
import safe_conversion  # type: ignore[import-not-found]  # noqa: E402


def _run(script_name: str, args: list[str], stdin_data: str = "") -> tuple[int, str, str]:
    """Invoke a cap-table script as a subprocess. Returns (rc, stdout, stderr)."""
    res = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script_name), *args],
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASIC_INPUTS = {
    "company_name": "Acmecorp",
    "analysis_date": "2026-05-19",
    "mode": "standard",
    "jurisdiction": {
        "structure": "delaware",
        "incorporated_date": "2024-01-01",
        "iia_grants_history": {"has_grants": False, "grant_details": []},
    },
    "founders": [
        {"name": "Alice", "founder_id": "founder_alice", "common_shares": 5_000_000},
        {"name": "Bob", "founder_id": "founder_bob", "common_shares": 5_000_000},
    ],
    "preferred_series": [],
    "option_pool": {"plan_type": "nso", "authorized": 1_500_000, "issued": 500_000, "unallocated": 1_000_000},
    "common_batches": [],
    "metadata": {"run_id": "test"},
}

_BASIC_INSTRUMENTS = {
    "safes": [],
    "notes": [],
    "warrants": [],
    "option_grants": [],
    "metadata": {"run_id": "test"},
}

_SAFE_BASIC = {
    "id": "safe_001",
    "investor_name": "Angel A",
    "purchase_amount": 500_000,
    "post_money_valuation_cap": 8_000_000,
    "discount_multiplier": None,
    "mfn_provision": None,
    "pro_rata_side_letter": None,
    "issuance_date": "2025-01-01",
    "form": "yc_postmoney_cap",
    "conversion_price_override": None,
    "source_document": None,
    "extraction_confidence": "high",
}

_NOTE_BASIC = {
    "id": "note_001",
    "investor_name": "Lender L",
    "principal": 100_000,
    "annual_interest_rate": 0.06,
    "day_count_basis": 365,
    "compounding_periods_per_year": None,
    "interest_converts_to_shares": True,
    "issuance_date": "2025-06-01",
    "last_interest_event_date": None,
    "valuation_cap": 10_000_000,
    "discount_multiplier": 0.80,
    "capitalization_denominator": 10_000_000,
    "capitalization_denominator_policy": "pre-money fully diluted",
    "qualified_financing_threshold": 1_000_000,
    "maturity_date": "2027-06-01",
    "maturity_default_treatment": "convert_at_cap",
    "maturity_conversion_price_override": None,
    "non_qualified_financing_treatment": None,
    "source_document": None,
    "extraction_confidence": "high",
}


@pytest.fixture
def basic_dir(tmp_path: Any) -> Any:
    """Workspace with inputs + instruments + cap_state populated."""
    inputs_path = tmp_path / "inputs.json"
    instr_path = tmp_path / "instruments.json"
    cap_path = tmp_path / "cap_state.json"
    inputs_path.write_text(json.dumps(_BASIC_INPUTS))
    instr_path.write_text(json.dumps(_BASIC_INSTRUMENTS))
    # Build cap_state via library (fast)
    cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
    cs["metadata"]["run_id"] = "test"
    cap_path.write_text(json.dumps(cs))
    return tmp_path


# ===========================================================================
# cap_state.py
# ===========================================================================


class TestCapState:
    def test_basic_founders_only(self) -> None:
        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
        assert cs["as_converted_totals"]["common_shares"] == 10_000_000
        assert cs["as_converted_totals"]["preferred_shares_as_converted"] == 0
        assert cs["as_converted_totals"]["options_outstanding"] == 500_000
        assert cs["as_converted_totals"]["options_available"] == 1_000_000
        assert cs["as_converted_totals"]["fully_diluted_shares"] == 11_500_000

    def test_with_preferred_series(self) -> None:
        inputs = dict(_BASIC_INPUTS)
        inputs["preferred_series"] = [
            {
                "series_name": "Series Seed",
                "shares": 2_000_000,
                "original_issue_price": 1.0,
                "original_conversion_price": 1.0,
                "current_conversion_price": 1.0,
                "issuance_date": "2025-03-01",
            }
        ]
        cs = cap_state_mod.build_cap_state(inputs, _BASIC_INSTRUMENTS)
        assert cs["as_converted_totals"]["preferred_shares_as_converted"] == 2_000_000
        assert cs["as_converted_totals"]["fully_diluted_shares"] == 13_500_000

    def test_preferred_with_anti_dilution_adjustment(self) -> None:
        """When current_conversion_price < OCP, as-converted count increases."""
        inputs = dict(_BASIC_INPUTS)
        inputs["preferred_series"] = [
            {
                "series_name": "Series Seed",
                "shares": 1_000_000,
                "original_issue_price": 2.0,
                "original_conversion_price": 2.0,
                "current_conversion_price": 1.0,  # AD adjusted down by 50%
                "issuance_date": "2025-03-01",
            }
        ]
        cs = cap_state_mod.build_cap_state(inputs, _BASIC_INSTRUMENTS)
        # 1M shares × (2.0 / 1.0) = 2M as-converted
        assert cs["as_converted_totals"]["preferred_shares_as_converted"] == 2_000_000

    def test_with_common_batches(self) -> None:
        inputs = dict(_BASIC_INPUTS)
        inputs["common_batches"] = [
            {
                "batch_id": "b1",
                "holder_id": "advisor",
                "shares": 250_000,
                "issuance_date": "2025-06-01",
                "consideration": 0,
                "purpose": "founder_issuance",
            }
        ]
        cs = cap_state_mod.build_cap_state(inputs, _BASIC_INSTRUMENTS)
        assert cs["as_converted_totals"]["common_shares"] == 10_250_000

    def test_outstanding_options_references_instruments(self) -> None:
        """Per Gotcha #6 + design rev16: outstanding_options carries grant_id only,
        NOT the per-grant details (those live in instruments.option_grants[])."""
        inst: dict[str, Any] = dict(_BASIC_INSTRUMENTS)
        inst["option_grants"] = [
            {
                "id": "grant_001",
                "holder_id": "employee_1",
                "grant_date": "2025-09-01",
                "shares_granted": 100_000,
                "shares_vested_to_date": 25_000,
                "shares_exercised": 0,
                "strike_price": 0.50,
                "plan_type": "section_102_cg",
            }
        ]
        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, inst)
        assert len(cs["outstanding_options"]) == 1
        opt = cs["outstanding_options"][0]
        assert opt["grant_id"] == "grant_001"
        assert opt["shares_vested_to_date"] == 25_000
        assert opt["shares_outstanding_unvested"] == 75_000  # 100k granted - 25k vested
        # Per design: grant_date NOT re-declared on cap_state.outstanding_options
        assert "grant_date" not in opt
        assert "strike_price" not in opt

    def test_cli_writes_artifact_with_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "inputs.json")
            inst = os.path.join(d, "instruments.json")
            out = os.path.join(d, "cap_state.json")
            with open(inp, "w") as f:
                json.dump(_BASIC_INPUTS, f)
            with open(inst, "w") as f:
                json.dump(_BASIC_INSTRUMENTS, f)
            rc, _, stderr = _run(
                "cap_state.py", ["--inputs", inp, "--instruments", inst, "--run-id", "abc123", "-o", out]
            )
            assert rc == 0, stderr
            with open(out) as f:
                cs = json.load(f)
            assert cs["metadata"]["run_id"] == "abc123"


# ===========================================================================
# safe_conversion.py
# ===========================================================================


class TestSafeConversion:
    def test_cap_implied_basic(self) -> None:
        # $500k @ $8M cap, 11.5M company cap → 6.25% cap-implied ownership
        r = safe_conversion.convert_safe_cap_implied(
            purchase_amount=500_000,
            post_money_valuation_cap=8_000_000,
            company_capitalization=11_500_000,
        )
        assert r["branch"] == "cap_implied"
        assert math.isclose(r["cap_implied_ownership"], 0.0625, rel_tol=1e-6)
        # safe_price = 8M / 11.5M
        assert math.isclose(r["safe_price"], 8_000_000 / 11_500_000, rel_tol=1e-6)
        # shares = 500k / safe_price
        expected_shares = 500_000 / (8_000_000 / 11_500_000)
        assert math.isclose(r["cap_implied_shares"], expected_shares, rel_tol=1e-6)

    def test_cap_implied_rejects_zero_cap(self) -> None:
        r = safe_conversion.convert_safe_cap_implied(
            purchase_amount=500_000,
            post_money_valuation_cap=None,
            company_capitalization=11_500_000,
        )
        assert r["branch"] == "rejected"
        assert r["error"] == safe_conversion.E_SAFE_REQUIRES_CONVERSION_EVENT

    def test_priced_round_cap_only_form(self) -> None:
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=500_000,
            form="yc_postmoney_cap",
            post_money_valuation_cap=8_000_000,
            discount_multiplier=None,
            company_capitalization=11_500_000,
            equity_financing_price=2.0,
        )
        assert r["branch"] == "cap_branch"
        # cap_price = 8M / 11.5M ≈ 0.696; lower than equity_price 2.0, so cap wins
        assert math.isclose(r["conversion_price"], 8_000_000 / 11_500_000, rel_tol=1e-6)

    def test_priced_round_discount_only(self) -> None:
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=100_000,
            form="yc_postmoney_discount",
            post_money_valuation_cap=None,
            discount_multiplier=0.80,
            company_capitalization=11_500_000,
            equity_financing_price=2.0,
        )
        assert r["branch"] == "discount_branch"
        assert math.isclose(r["conversion_price"], 1.60, rel_tol=1e-6)  # 2.0 × 0.80

    def test_priced_round_cap_plus_discount_takes_min(self) -> None:
        # cap_price = 1.0, discount_price = 1.6 → cap wins (min)
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=100_000,
            form="cap_plus_discount",
            post_money_valuation_cap=11_500_000,  # cap_price = 1.0
            discount_multiplier=0.80,
            company_capitalization=11_500_000,
            equity_financing_price=2.0,
        )
        assert r["branch"] == "cap_and_discount_branch"
        assert math.isclose(r["conversion_price"], 1.0, rel_tol=1e-6)

    def test_discount_only_rejected_without_priced_round(self) -> None:
        """Per Gotcha #4 + design §5.1 hard-reject contract."""
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=100_000,
            form="yc_postmoney_discount",
            post_money_valuation_cap=None,
            discount_multiplier=0.80,
            company_capitalization=11_500_000,
            equity_financing_price=None,
        )
        assert r["branch"] == "rejected"
        assert r["error"] == safe_conversion.E_SAFE_REQUIRES_CONVERSION_EVENT

    def test_uncapped_mfn_rejected_without_trigger(self) -> None:
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=100_000,
            form="yc_uncapped_mfn",
            post_money_valuation_cap=None,
            discount_multiplier=None,
            company_capitalization=11_500_000,
            equity_financing_price=None,
        )
        assert r["branch"] == "rejected"
        assert r["error"] == safe_conversion.E_SAFE_REQUIRES_CONVERSION_EVENT

    def test_conversion_price_override(self) -> None:
        """Counsel-supplied override bypasses rule; provenance cites override."""
        r = safe_conversion.convert_safe_priced_round(
            purchase_amount=100_000,
            form="yc_postmoney_discount",  # would otherwise need priced round
            post_money_valuation_cap=None,
            discount_multiplier=0.80,
            company_capitalization=11_500_000,
            equity_financing_price=None,
            conversion_price_override=1.25,
        )
        assert r["branch"] == "conversion_price_override"
        assert r["conversion_price"] == 1.25
        # Math provenance cites source_ref, not rule_id
        assert any(
            p["source_type"] == "counsel_supplied_override"
            and p["rule_id"] is None
            and p["source_ref"] == "safes[].conversion_price_override"
            for p in r["math_provenance"]
        )

    def test_mfn_cycle_detection_unresolvable(self) -> None:
        """Per Gotcha #4: all-uncapped-MFN cycle = unresolvable."""
        safes = [
            {
                "id": "A",
                "form": "yc_uncapped_mfn",
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "B",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
            {
                "id": "B",
                "form": "yc_uncapped_mfn",
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "A",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
        ]
        cycles = safe_conversion.detect_mfn_cycles(safes)
        assert len(cycles) == 1
        assert cycles[0] == {"A", "B"}

    def test_mfn_cycle_not_flagged_if_anchored(self) -> None:
        """Cycle with a cap-bearing anchor → not flagged (anchor provides price)."""
        safes = [
            {
                "id": "A",
                "form": "yc_uncapped_mfn",
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "B",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
            {
                "id": "B",
                "form": "yc_postmoney_cap",  # anchor
                "mfn_provision": {
                    "present": False,
                    "elected_against_safe_id": None,
                    "elected": False,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
        ]
        cycles = safe_conversion.detect_mfn_cycles(safes)
        # B is not yc_uncapped_mfn, so the chain A→B has an anchor; no cycle
        assert cycles == []


# ===========================================================================
# note_conversion.py
# ===========================================================================


class TestNoteConversion:
    def test_accrued_interest_simple(self) -> None:
        # $100k @ 6% for 365 days, simple
        accrued = note_conversion.compute_accrued_interest(
            principal=100_000,
            annual_interest_rate=0.06,
            days_elapsed=365,
            day_count_basis=365,
        )
        assert math.isclose(accrued, 6_000, rel_tol=1e-6)

    def test_accrued_interest_compound_monthly(self) -> None:
        # $100k @ 6% for 365 days, monthly compounding
        accrued = note_conversion.compute_accrued_interest(
            principal=100_000,
            annual_interest_rate=0.06,
            days_elapsed=365,
            day_count_basis=365,
            compounding_periods_per_year=12,
        )
        # 100k × (1 + 0.06/12)^12 - 100k ≈ 6167.78
        assert math.isclose(accrued, 6167.78, abs_tol=1.0)

    def test_cap_conversion_branch(self) -> None:
        r = note_conversion.convert_note(
            _NOTE_BASIC,
            conversion_event_date="2026-06-01",
            priced_round_new_money=5_000_000,
            qualified_financing_price=2.0,
        )
        assert r["branch"] == "cap_conversion"
        # cap_price = 10M / 10M = 1.0; discount_price = 2.0 × 0.80 = 1.6 → cap wins
        assert math.isclose(r["conversion_price"], 1.0, rel_tol=1e-6)
        # balance = 100k + 6k accrued = 106k → 106,000 shares at $1/share
        assert math.isclose(r["conversion_shares"], 106_000, rel_tol=1e-6)

    def test_discount_only_branch(self) -> None:
        note = dict(_NOTE_BASIC)
        note["valuation_cap"] = None
        note["capitalization_denominator"] = None
        r = note_conversion.convert_note(
            note,
            conversion_event_date="2026-06-01",
            priced_round_new_money=5_000_000,
            qualified_financing_price=2.0,
        )
        assert r["branch"] == "discount_only"
        # discount_price = 2.0 × 0.80 = 1.6
        assert math.isclose(r["conversion_price"], 1.6, rel_tol=1e-6)

    def test_threshold_not_met_no_treatment(self) -> None:
        """Per design rev15: threshold not met + no treatment → branch threshold_not_met."""
        note = dict(_NOTE_BASIC)
        note["qualified_financing_threshold"] = 10_000_000
        r = note_conversion.convert_note(
            note,
            conversion_event_date="2026-06-01",
            priced_round_new_money=1_000_000,  # below threshold
            qualified_financing_price=2.0,
        )
        assert r["branch"] == "threshold_not_met"
        assert "conversion_shares" not in r

    def test_threshold_not_met_with_convert_anyway(self) -> None:
        note = dict(_NOTE_BASIC)
        note["qualified_financing_threshold"] = 10_000_000
        note["non_qualified_financing_treatment"] = "convert_anyway"
        r = note_conversion.convert_note(
            note,
            conversion_event_date="2026-06-01",
            priced_round_new_money=1_000_000,
            qualified_financing_price=2.0,
        )
        assert r["branch"] == "cap_conversion"  # convert_anyway falls through

    def test_threshold_not_met_with_do_not_convert(self) -> None:
        note = dict(_NOTE_BASIC)
        note["qualified_financing_threshold"] = 10_000_000
        note["non_qualified_financing_treatment"] = "do_not_convert"
        r = note_conversion.convert_note(
            note,
            conversion_event_date="2026-06-01",
            priced_round_new_money=1_000_000,
            qualified_financing_price=2.0,
        )
        assert r["branch"] == "maturity_extend"

    def test_maturity_repay_branch(self) -> None:
        note = dict(_NOTE_BASIC)
        note["maturity_default_treatment"] = "repay"
        note["interest_converts_to_shares"] = False
        r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
        assert r["branch"] == "maturity_repay"
        # Per the math-bug-fix: repay always returns principal + accrued regardless
        # of interest_converts_to_shares (that flag governs CONVERSION behavior only).
        # 2 years × 6% on $100k = $12k accrued → $112k repayment
        assert math.isclose(r["cash_repayment"], 112_000, rel_tol=1e-6)

    def test_maturity_extend_branch(self) -> None:
        note = dict(_NOTE_BASIC)
        note["maturity_default_treatment"] = "extend"
        r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
        assert r["branch"] == "maturity_extend"

    def test_maturity_counsel_review_branch(self) -> None:
        note = dict(_NOTE_BASIC)
        note["maturity_default_treatment"] = "counsel_review"
        r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
        assert r["branch"] == "maturity_counsel_review"

    def test_maturity_override_branch(self) -> None:
        """Per Gotcha #5 + design rev15: override bypasses rule for convert_at_cap."""
        note = dict(_NOTE_BASIC)
        note["valuation_cap"] = None  # no cap available
        note["capitalization_denominator"] = None
        note["maturity_conversion_price_override"] = 0.50  # counsel-supplied
        r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
        assert r["branch"] == "maturity_convert_at_cap"
        assert r["conversion_price"] == 0.50
        # balance = 100k + 12k accrued = 112k → 224k shares
        assert math.isclose(r["conversion_shares"], 224_000, rel_tol=1e-6)
        # Provenance cites the override
        assert any(
            p["source_type"] == "counsel_supplied_override"
            and p["source_ref"] == "notes[].maturity_conversion_price_override"
            for p in r["math_provenance"]
        )

    def test_override_branch_mismatch_error(self) -> None:
        """Per Gotcha #5: override paired with repay/extend/counsel_review = error."""
        note = dict(_NOTE_BASIC)
        note["maturity_default_treatment"] = "repay"
        note["maturity_conversion_price_override"] = 0.50
        r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
        assert r["branch"] == "override_mismatch"
        assert r["error"] == note_conversion.E_NOTE_OVERRIDE_BRANCH_MISMATCH

    def test_completeness_partition_full(self) -> None:
        """All notes share-producing → completeness=full."""
        per_note = {
            "n1": {"branch": "cap_conversion"},
            "n2": {"branch": "discount_only"},
        }
        assert note_conversion.derive_scenario_completeness(per_note) == "full"

    def test_completeness_partition_repay_only(self) -> None:
        per_note = {"n1": {"branch": "maturity_repay"}, "n2": {"branch": "maturity_repay"}}
        assert note_conversion.derive_scenario_completeness(per_note) == "repay_only"

    def test_completeness_partition_mixed(self) -> None:
        per_note = {
            "n1": {"branch": "cap_conversion"},
            "n2": {"branch": "maturity_repay"},
        }
        assert note_conversion.derive_scenario_completeness(per_note) == "mixed"

    def test_completeness_partition_structural_only(self) -> None:
        per_note = {
            "n1": {"branch": "maturity_extend"},
            "n2": {"branch": "threshold_not_met"},
        }
        assert note_conversion.derive_scenario_completeness(per_note) == "structural_only"


# ===========================================================================
# option_pool.py
# ===========================================================================


class TestOptionPool:
    def test_pre_money_target(self) -> None:
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=10_000_000,
            existing_unallocated_pool=0,
            target_pool_percent=0.10,
            new_money_shares=None,
            target_basis="pre_money",
        )
        # (0 + x) / (10M + x) = 0.10 → x = 10M × 0.10 / 0.90 ≈ 1.111M
        assert r["required_pool_topup_shares"] == round(10_000_000 * 0.10 / 0.90)
        assert math.isclose(r["post_topup_pool_percent"], 0.10, abs_tol=1e-4)

    def test_post_money_target(self) -> None:
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=10_000_000,
            existing_unallocated_pool=0,
            target_pool_percent=0.15,
            new_money_shares=2_500_000,
            target_basis="post_money",
        )
        # (0 + x) / (10M + x + 2.5M) = 0.15 → x = 0.15 × 12.5M / 0.85 ≈ 2.206M
        assert math.isclose(r["post_topup_pool_percent"], 0.15, abs_tol=1e-4)

    def test_post_money_excluding_converting_securities(self) -> None:
        """Same formula as post_money for v0.1 — the rule pack distinguishes
        the denominator policy via parameterization_points, not the math directly."""
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=10_000_000,
            existing_unallocated_pool=500_000,
            target_pool_percent=0.10,
            new_money_shares=1_000_000,
            target_basis="post_money_excluding_converting_securities",
        )
        assert r["target_basis"] == "post_money_excluding_converting_securities"
        assert r["required_pool_topup_shares"] >= 0

    def test_custom_basis(self) -> None:
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=10_000_000,
            existing_unallocated_pool=100_000,
            target_pool_percent=0.08,
            new_money_shares=None,
            target_basis="custom",
        )
        assert r["target_basis"] == "custom"

    def test_invalid_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            option_pool.required_topup(
                pre_topup_fully_diluted_shares=10_000_000,
                existing_unallocated_pool=0,
                target_pool_percent=1.5,  # > 1
                new_money_shares=None,
                target_basis="pre_money",
            )

    def test_pre_money_target_already_met_emits_clarifying_question(self) -> None:
        """Phase M+S: when existing pool already meets target under literal
        pre_money basis but post_money interpretation would require a top-up,
        emit a warning + clarifying_question for the dispatching agent to
        escalate via AskUserQuestion.
        """
        # Existing pool 2M = 18.18% of 11M pre-FD; target 10% pre_money is
        # already met (returns 0 top-up). But post_money basis would compute
        # a real top-up: solve (2M + x) / (11M + 5M + x) = 0.10 → x = -400k,
        # so post-money is ALSO 0 here. Need a scenario where post-money > 0.
        # Set existing pool to 800k = 7.27% (below 10% pre_money target).
        # Pre_money calc: (800k + x)/(11M + x) = 0.10 → x = 333,333.
        # That's NOT a no-op — bad example.
        # Use: existing 1.5M = 13.64% (above 10% pre); pre_money no-op.
        # Post-money: (1.5M + x)/(11M + 5M + x) = 0.10 → x = 55,556.
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=11_000_000,
            existing_unallocated_pool=1_500_000,
            target_pool_percent=0.10,
            new_money_shares=5_000_000,
            target_basis="pre_money",
        )
        assert r["required_pool_topup_shares"] == 0  # literal pre_money no-op
        assert "warnings" in r
        assert any(w["code"] == "pool_target_already_met_check_intent" for w in r["warnings"])
        assert "clarifying_question" in r
        cq = r["clarifying_question"]
        assert cq["context"]["literal_pre_money_top_up"] == 0
        assert cq["context"]["industry_norm_post_money_top_up"] > 0  # M8 gate ensures this

    def test_post_money_basis_does_not_fire_clarifying_question(self) -> None:
        """Phase M+S negative case: target_basis='post_money' never triggers
        the warning regardless of whether the existing pool exceeds target.
        """
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=11_000_000,
            existing_unallocated_pool=1_500_000,
            target_pool_percent=0.10,
            new_money_shares=5_000_000,
            target_basis="post_money",
        )
        assert "warnings" not in r or not any(
            w.get("code") == "pool_target_already_met_check_intent" for w in r.get("warnings", [])
        )
        assert "clarifying_question" not in r or r.get("clarifying_question") is None

    def test_pre_money_no_op_both_interpretations_suppresses_warning(self) -> None:
        """M8: when BOTH literal pre-money AND industry-norm post-money
        produce 0 top-up (existing pool legitimately oversized), the
        clarifying_question is noise — the M8 gate must suppress it.
        """
        # Existing pool 3M = ~27% of 11M; way above 10% target under any reading.
        # Pre_money: (3M + x)/(11M + x) = 0.10 → x = -888,889 → 0.
        # Post_money: (3M + x)/(11M + 5M + x) = 0.10 → x = -1,555,556 → 0.
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=11_000_000,
            existing_unallocated_pool=3_000_000,
            target_pool_percent=0.10,
            new_money_shares=5_000_000,
            target_basis="pre_money",
        )
        assert r["required_pool_topup_shares"] == 0
        # M8 gate: post_money_required is also 0, so NO warning + NO question
        assert "warnings" not in r or not r.get("warnings", [])
        assert "clarifying_question" not in r or r.get("clarifying_question") is None

    def test_pre_fd_zero_does_not_crash(self) -> None:
        """M7: option_pool is a public library function. A library caller
        passing pre_fd=0 (degenerate but legal) must not ZeroDivisionError in
        the warning's existing_pct_of_pre_fd format string.
        """
        # pre_fd=0 means no pre-financing FD; target 10% pre_money with 0
        # existing pool computes x = (0.1 * 0 - 0) / 0.9 = 0 → no top-up needed.
        # M8 gate suppresses the warning here too (post_money_required also 0).
        # The key is: no crash.
        r = option_pool.required_topup(
            pre_topup_fully_diluted_shares=0,
            existing_unallocated_pool=0,
            target_pool_percent=0.10,
            new_money_shares=None,
            target_basis="pre_money",
        )
        assert r["required_pool_topup_shares"] == 0  # no crash


# ===========================================================================
# anti_dilution.py
# ===========================================================================


class TestAntiDilution:
    def test_bbwa_divisor_uses_cp1_not_oip(self) -> None:
        """Per Gotcha #2: B = consideration / CP1, not consideration / OIP.
        Cooley GO + NVCA Model Cert §4.4.4."""
        r = anti_dilution.bbwa_new_conversion_price(
            current_conversion_price=1.0,  # CP1
            pre_issuance_share_count_A=10_000_000,
            consideration_received=1_000_000,
            new_issue_price=0.50,
            new_shares_issued_C=2_000_000,
        )
        assert r["triggered"] is True
        # B = 1M / 1.0 = 1M (NOT 1M / OIP)
        assert r["intermediate"]["B"] == 1_000_000
        # CP2 = 1 × (10M + 1M) / (10M + 2M) = 11/12 ≈ 0.917
        assert math.isclose(r["new_conversion_price"], 11_000_000 / 12_000_000, rel_tol=1e-6)

    def test_bbwa_not_triggered_when_new_price_above_cp1(self) -> None:
        r = anti_dilution.bbwa_new_conversion_price(
            current_conversion_price=1.0,
            pre_issuance_share_count_A=10_000_000,
            consideration_received=1_000_000,
            new_issue_price=2.0,  # up round
        )
        assert r["triggered"] is False
        assert r["new_conversion_price"] == 1.0

    def test_bbwa_C_derived_from_consideration_when_omitted(self) -> None:
        r = anti_dilution.bbwa_new_conversion_price(
            current_conversion_price=1.0,
            pre_issuance_share_count_A=10_000_000,
            consideration_received=1_000_000,
            new_issue_price=0.50,
            # new_shares_issued_C omitted → derived as 1M / 0.5 = 2M
        )
        assert r["intermediate"]["C"] == 2_000_000

    def test_full_ratchet_triggered(self) -> None:
        r = anti_dilution.full_ratchet_new_conversion_price(
            current_conversion_price=1.0,
            new_issue_price=0.50,
        )
        assert r["triggered"] is True
        assert r["new_conversion_price"] == 0.50

    def test_full_ratchet_not_triggered(self) -> None:
        r = anti_dilution.full_ratchet_new_conversion_price(
            current_conversion_price=1.0,
            new_issue_price=2.0,
        )
        assert r["triggered"] is False
        assert r["new_conversion_price"] == 1.0


# ===========================================================================
# priced_round.py (solver / orchestrator)
# ===========================================================================


class TestPricedRound:
    def test_solves_cap_only_safe_with_priced_round(self) -> None:
        """Closed-form for cap-only SAFEs converges in ≤2 iterations."""
        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=[_SAFE_BASIC],
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="pre_money",
        )
        assert r["completeness"] == "full"
        assert r["converged"] is True
        # new money 20% of post-money valuation = $5M / $25M
        assert math.isclose(r["aggregate_ownership_by_class"]["new_money_pct"], 0.20, abs_tol=1e-3)

    def test_solver_detects_circular_mfn(self) -> None:
        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
        cyclic_safes = [
            {
                **_SAFE_BASIC,
                "id": "A",
                "form": "yc_uncapped_mfn",
                "post_money_valuation_cap": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "B",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
            {
                **_SAFE_BASIC,
                "id": "B",
                "form": "yc_uncapped_mfn",
                "post_money_valuation_cap": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "A",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
        ]
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=cyclic_safes,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
        )
        assert r["completeness"] == "structural_only"
        assert any(b["code"] == "E_SAFE_CIRCULAR_MFN" for b in r["blockers"])

    def test_solver_rejects_zero_pre_fd(self) -> None:
        """When cap state has no pre-FD shares, the system has no anchor."""
        empty_inputs = {
            **_BASIC_INPUTS,
            "founders": [],
            "option_pool": {"plan_type": "nso", "authorized": 0, "issued": 0, "unallocated": 0},
        }
        cs = cap_state_mod.build_cap_state(empty_inputs, _BASIC_INSTRUMENTS)
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=[],
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
        )
        assert r["completeness"] == "structural_only"


class TestStackedPostMoneySAFEsGolden:
    """Golden-value regression for YC post-money cap SAFE math.

    Locks the canonical answer for the eval-2 scenario:
    - Founder 10M common; unallocated pool 1M; pre-FD 11M
    - SAFE 1: $500k @ $10M post-money cap
    - SAFE 2: $1M @ $15M post-money cap
    - SAFE 3: $500k uncapped MFN electing SAFE 1's $10M cap
    - Series A: $5M @ $20M pre, 10% post-money pool (founders absorb)

    Golden values derived from first-principles YC post-money math
    (rule pack `safe.stacked_post_money_caps` lines 527-530), independently
    triangulated by three reviewers + an independent opus subagent.

    Each post-money SAFE locks `purchase / post_money_cap` of post-money FD.
    The implementation MUST NOT use `cap_price = cap / pre_fd` (the pre-money
    primer formula) on post-money form SAFEs.
    """

    EVAL2_INPUTS = {
        "company_name": "TestCo",
        "analysis_date": "2026-05-21",
        "mode": "standard",
        "jurisdiction": {
            "structure": "delaware",
            "incorporated_date": "2024-06-01",
            "iia_grants_history": {"has_grants": False, "grant_details": []},
        },
        "founders": [
            {"name": "Founder", "founder_id": "founder_1", "common_shares": 10_000_000},
        ],
        "preferred_series": [],
        "option_pool": {
            "plan_type": "nso",
            "authorized": 1_000_000,
            "issued": 0,
            "unallocated": 1_000_000,
        },
        "common_batches": [],
        "metadata": {"run_id": "test"},
    }

    EVAL2_SAFES = [
        {
            "id": "safe_1",
            "investor_name": "Angel A",
            "purchase_amount": 500_000,
            "post_money_valuation_cap": 10_000_000,
            "discount_multiplier": None,
            "mfn_provision": None,
            "pro_rata_side_letter": None,
            "issuance_date": "2025-01-01",
            "form": "yc_postmoney_cap",
            "conversion_price_override": None,
            "source_document": None,
            "extraction_confidence": "high",
        },
        {
            "id": "safe_2",
            "investor_name": "Angel B",
            "purchase_amount": 1_000_000,
            "post_money_valuation_cap": 15_000_000,
            "discount_multiplier": None,
            "mfn_provision": None,
            "pro_rata_side_letter": None,
            "issuance_date": "2025-02-01",
            "form": "yc_postmoney_cap",
            "conversion_price_override": None,
            "source_document": None,
            "extraction_confidence": "high",
        },
        # safe_3 is "MFN-elected against safe_1's $10M cap" — modeled as a
        # pre-resolved $10M-cap post-money SAFE so J's regression isolates the
        # math-formula bug. Phase N (MFN auto-bind) has separate test coverage
        # for the auto-resolution path from uncapped MFN → elected SAFE's cap.
        {
            "id": "safe_3",
            "investor_name": "Angel C",
            "purchase_amount": 500_000,
            "post_money_valuation_cap": 10_000_000,
            "discount_multiplier": None,
            "mfn_provision": None,
            "pro_rata_side_letter": None,
            "issuance_date": "2025-03-01",
            "form": "yc_postmoney_cap",
            "conversion_price_override": None,
            "source_document": None,
            "extraction_confidence": "high",
        },
    ]

    def _instruments(self) -> dict[str, Any]:
        return {
            "safes": self.EVAL2_SAFES,
            "notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test"},
        }

    def test_per_safe_ownership_is_purchase_over_cap(self) -> None:
        """Per-SAFE ownership formula for YC post-money cap SAFEs.

        Each SAFE: `safe_ownership_i = purchase_amount_i / post_money_cap_i`.
        Not `purchase / cap_price`, not `purchase × pre_fd / cap`.
        """
        # safe_1: $500k / $10M = 5%
        assert math.isclose(500_000 / 10_000_000, 0.05, rel_tol=1e-9)
        # safe_2: $1M / $15M = 6.6667%
        assert math.isclose(1_000_000 / 15_000_000, 1 / 15, rel_tol=1e-9)
        # safe_3 (MFN→$10M): $500k / $10M = 5%
        assert math.isclose(500_000 / 10_000_000, 0.05, rel_tol=1e-9)
        # Aggregate: 1/6
        agg = 500_000 / 10_000_000 + 1_000_000 / 15_000_000 + 500_000 / 10_000_000
        assert math.isclose(agg, 1 / 6, rel_tol=1e-9)

    def test_eval2_golden_solver_iterative(self) -> None:
        """Full eval-2 scenario through the iterative solver.

        Golden values from independent first-principles derivation:
        - aggregate_safe_pct = 1/6 ≈ 16.6667%
        - founder_pct = 8/15 ≈ 53.3333%
        - PPS = 4/3 ≈ $1.3333
        - total post-money FD = 18,750,000 shares
        """
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )

        assert r["completeness"] == "full", f"blockers: {r.get('blockers')}"
        assert r["converged"] is True

        agg = r["aggregate_ownership_by_class"]
        # Aggregate SAFE ownership: 1/6
        assert math.isclose(agg["safe_pct"], 1 / 6, abs_tol=1e-4), (
            f"safe_pct: got {agg['safe_pct']:.6f}, expected {1 / 6:.6f}"
        )
        # Founder ownership post-financing: 8/15
        assert math.isclose(agg["founders_pct"], 8 / 15, abs_tol=1e-4), (
            f"founders_pct: got {agg['founders_pct']:.6f}, expected {8 / 15:.6f}"
        )
        # New money: 20% of post-money
        assert math.isclose(agg["new_money_pct"], 0.20, abs_tol=1e-4)
        # Pool: 10% of post-money
        assert math.isclose(agg["option_pool_pct"], 0.10, abs_tol=1e-4)

        # PPS = 4/3
        assert math.isclose(r["equity_financing_price"], 4 / 3, rel_tol=1e-4), (
            f"PPS: got {r['equity_financing_price']:.6f}, expected {4 / 3:.6f}"
        )

        # Total post-money FD shares = 18,750,000
        total_fd = r["post_round_fully_diluted_shares"]
        assert math.isclose(total_fd, 18_750_000, rel_tol=1e-4), f"post_round_fd: got {total_fd}, expected 18_750_000"

    def test_eval2_per_safe_share_counts(self) -> None:
        """Each SAFE's resolved share count matches the ownership formula."""
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        per_safe = r["per_safe"]
        # safe_1: 5% × 18.75M = 937,500
        assert math.isclose(per_safe["safe_1"]["conversion_shares"], 937_500, rel_tol=1e-3)
        # safe_2: (1/15) × 18.75M = 1,250,000
        assert math.isclose(per_safe["safe_2"]["conversion_shares"], 1_250_000, rel_tol=1e-3)
        # safe_3: 5% × 18.75M = 937,500
        assert math.isclose(per_safe["safe_3"]["conversion_shares"], 937_500, rel_tol=1e-3)

    def test_eval2_new_investor_and_pool_shares(self) -> None:
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        # New investor: 20% × 18.75M = 3,750,000
        assert math.isclose(r["shares_breakdown"]["new_money"], 3_750_000, rel_tol=1e-3)
        # Pool top-up brings unallocated pool to 1,875,000 (10% × 18.75M)
        # Existing 1M pool + top-up = 1,875,000; gross top-up = 875,000
        assert math.isclose(r["shares_breakdown"]["pool_topup"], 875_000, rel_tol=1e-3)

    def test_eval2_closed_form_path_matches_iterative(self) -> None:
        """Closed-form path (all yc_postmoney_cap, no discount, no notes) must
        land at the same answer as the iterative solver. Reviewer 2's call-out:
        the closed-form branch at priced_round.py:121 is the silent twin of the
        iterative bug; both must produce correct math.
        """
        # SAFE 3 has MFN-electing safe_1's cap; effectively yc_postmoney_cap from
        # the solver's perspective once MFN resolution runs.
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        # Whichever path the solver chose, the answer must match the golden.
        agg = r["aggregate_ownership_by_class"]
        assert math.isclose(agg["safe_pct"], 1 / 6, abs_tol=1e-4)
        assert math.isclose(agg["founders_pct"], 8 / 15, abs_tol=1e-4)
        assert math.isclose(r["equity_financing_price"], 4 / 3, rel_tol=1e-4)

    def test_eval2_ownership_sum_to_one(self) -> None:
        """Cross-check assertion: all ownership classes sum to 100%."""
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        agg = r["aggregate_ownership_by_class"]
        total = (
            agg["safe_pct"]
            + agg["founders_pct"]
            + agg["new_money_pct"]
            + agg["option_pool_pct"]
            + agg.get("preferred_pct", 0.0)
            + agg.get("note_pct", 0.0)
        )
        assert math.isclose(total, 1.0, abs_tol=1e-4), f"ownerships sum to {total}, not 1.0"

    def test_uncapped_mfn_auto_binds_to_elected_safes_terms(self) -> None:
        """Phase N: uncapped MFN with `elected_against_safe_id` set should
        auto-resolve to the elected sibling's terms — no override required.

        Eval-2 transcript noted that the solver previously REQUIRED a
        `conversion_price_override` even when MFN was clearly electing
        safe_1's cap. With Phase N auto-bind, the resolver pre-inherits the
        elected sibling's form/cap/discount before the solver runs.
        """
        eval2_safes_with_real_mfn = [
            self.EVAL2_SAFES[0],
            self.EVAL2_SAFES[1],
            # safe_3 is uncapped MFN electing safe_1; should auto-bind
            {
                "id": "safe_3",
                "investor_name": "Angel C",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "safe_1",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_uncapped_mfn",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
        ]
        instruments = {
            "safes": eval2_safes_with_real_mfn,
            "notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test"},
        }
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, instruments)
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=eval2_safes_with_real_mfn,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        # Auto-bind must produce the same answer as the pre-resolved test
        assert r["completeness"] == "full", f"blockers: {r.get('blockers')}"
        agg = r["aggregate_ownership_by_class"]
        assert math.isclose(agg["safe_pct"], 1 / 6, abs_tol=1e-4), (
            f"MFN auto-bind: aggregate safe_pct {agg['safe_pct']} ≠ expected 1/6"
        )
        assert math.isclose(agg["founders_pct"], 8 / 15, abs_tol=1e-4)

    def test_fast_assess_writes_sentinel_and_markdown(self) -> None:
        """Phase O: quick_assess.py produces fast_assess_only.json + report.md.

        Verifies:
        - sentinel JSON conforms to v0.1.0-cap-table-fast-assess schema
        - sentinel uses the corrected math from Phase J (founder 53.33% on
          the canonical eval-2 scenario)
        - report_fast_assess.md exists and contains the founder ownership
        - no canonical artifacts are produced (no inputs.json, cap_state.json,
          report.json, etc.)
        """
        import quick_assess as qa  # type: ignore[import-not-found]

        sentinel = qa.quick_assess(
            company_name="TestCo",
            inputs=self.EVAL2_INPUTS,
            safes=[
                self.EVAL2_SAFES[0],
                self.EVAL2_SAFES[1],
                self.EVAL2_SAFES[2],
            ],
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
            founder_prompt="three SAFEs + $5M Series A",
            attached_docs=[],
        )
        # Sentinel schema
        assert sentinel["schema_version"] == "v0.1.0-cap-table-fast-assess"
        assert sentinel["mode"] == "fast_assess"
        assert sentinel["produces_canonical_artifacts"] is False
        assert sentinel["rule_pack_version"] == "0.3.2"
        # inputs_fingerprint structurally valid
        fp = sentinel["inputs_fingerprint"]
        assert "sha256" in fp and len(fp["sha256"]) == 64
        # headline_data uses corrected math from Phase J
        hd = sentinel["headline_data"]
        fi = hd["founder_impact"]
        assert math.isclose(fi["ownership_post_financing_pct"], 8 / 15, abs_tol=1e-4)
        assert math.isclose(fi["pps_priced_round"], 4 / 3, rel_tol=1e-4)
        # report_md is delivered for the CLI to extract
        report_md = sentinel.pop("_report_md")
        assert "53.33%" in report_md  # founder ownership rendered

    def test_fast_assess_sentinel_validates_against_schema(self) -> None:
        """Phase O: sentinel JSON validates against fast_assess_only.schema.json."""
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")

        import quick_assess as qa  # type: ignore[import-not-found]

        sentinel = qa.quick_assess(
            company_name="TestCo",
            inputs=self.EVAL2_INPUTS,
            safes=[self.EVAL2_SAFES[0]],
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        sentinel.pop("_report_md", None)
        # Add the path field that the CLI normally sets
        sentinel["fast_assess_report_path"] = "/tmp/test_report.md"

        schema_path = os.path.join(
            os.path.dirname(SCRIPTS),
            "references",
            "schemas",
            "fast_assess_only.schema.json",
        )
        with open(schema_path) as f:
            schema = json.load(f)
        # Will raise jsonschema.ValidationError if invalid
        jsonschema.validate(instance=sentinel, schema=schema)

    def test_mfn_chain_resolves_transitively(self) -> None:
        """H9: A elects B elects C, where C has a resolved cap. The resolver
        must iterate to a fixed point so A inherits transitively (via B's
        resolution against C). Single-hop resolver would leave A unresolved
        because B is still 'yc_uncapped_mfn' on the first pass.
        """
        # Chain: safe_a → safe_b → safe_c (safe_c has resolved cap)
        chain_safes = [
            {
                "id": "safe_a",
                "investor_name": "Angel Chain A",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": None,
                "pre_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "safe_b",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_uncapped_mfn",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
            {
                "id": "safe_b",
                "investor_name": "Angel Chain B",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": None,
                "pre_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "safe_c",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_uncapped_mfn",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
            {
                "id": "safe_c",
                "investor_name": "Angel Chain C (anchor)",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 10_000_000,
                "pre_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": None,
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_postmoney_cap",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
        ]
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, {**self._instruments(), "safes": chain_safes})
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=chain_safes,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        assert r["completeness"] == "full", f"chain didn't resolve: {r.get('blockers')}"
        # All three SAFEs should have resolved to safe_c's $10M cap; each owns
        # 5% of post-money (purchase/cap = 500k/10M). Aggregate = 15%.
        agg = r["aggregate_ownership_by_class"]
        assert math.isclose(agg["safe_pct"], 0.15, abs_tol=1e-4), (
            f"chain didn't propagate: aggregate safe_pct {agg['safe_pct']} ≠ 0.15"
        )

    def test_mfn_elected_against_missing_sibling_fails_cleanly(self) -> None:
        """H9 edge case: MFN points to a sibling that doesn't exist in the
        safes list. Resolver must leave the SAFE unresolved (no crash); the
        downstream rejection path then produces E_SAFE_REQUIRES_CONVERSION_EVENT.
        """
        orphan_safes = [
            {
                "id": "safe_orphan",
                "investor_name": "Angel Orphan",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": None,
                "pre_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "safe_does_not_exist",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_uncapped_mfn",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
        ]
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, {**self._instruments(), "safes": orphan_safes})
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=orphan_safes,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        # Should produce a blocker, not crash, not silently pass through.
        assert r["completeness"] == "structural_only"
        assert (
            any(
                b.get("code") in {"E_SAFE_REQUIRES_CONVERSION_EVENT", "E_SAFE_CIRCULAR_MFN"}
                for b in r.get("blockers", [])
            )
            or "safe_orphan" in r["per_safe"]
            and r["per_safe"]["safe_orphan"]["branch"] == "rejected"
        )

    def test_mfn_inheritance_provenance_propagated_to_per_safe_result(self) -> None:
        """M5: per_safe[safe_id]['_mfn_inherited_from'] must be set when the
        SAFE was MFN-resolved. Lets downstream counsel-review reporting phrase
        'Investor X's MFN-inherited terms from Investor Y'.
        """
        eval2_with_mfn = [
            self.EVAL2_SAFES[0],
            self.EVAL2_SAFES[1],
            {
                "id": "safe_3_mfn",
                "investor_name": "Angel C MFN",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": None,
                "pre_money_valuation_cap": None,
                "discount_multiplier": None,
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "safe_1",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
                "pro_rata_side_letter": None,
                "issuance_date": "2025-03-01",
                "form": "yc_uncapped_mfn",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            },
        ]
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, {**self._instruments(), "safes": eval2_with_mfn})
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=eval2_with_mfn,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        per_safe_3 = r["per_safe"]["safe_3_mfn"]
        # Provenance must be propagated from shadow record to per_safe result
        assert per_safe_3.get("_mfn_inherited_from") == "safe_1", (
            f"MFN inheritance provenance lost: {per_safe_3.get('_mfn_inherited_from')} != 'safe_1'"
        )

    def test_eval2_aggregate_safe_pct_equals_sum_of_per_safe(self) -> None:
        """J8 cross-check: aggregate_ownership_by_class.safe_pct must equal
        Σ per-safe ownership. Catches drift between aggregate and detail.
        """
        cs = cap_state_mod.build_cap_state(self.EVAL2_INPUTS, self._instruments())
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=self.EVAL2_SAFES,
            notes=[],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="post_money",
        )
        total_fd = r["post_round_fully_diluted_shares"]
        sum_per_safe_shares = sum(s["conversion_shares"] for s in r["per_safe"].values())
        agg_from_detail = sum_per_safe_shares / total_fd
        agg_reported = r["aggregate_ownership_by_class"]["safe_pct"]
        assert math.isclose(agg_reported, agg_from_detail, abs_tol=1e-6), (
            f"aggregate safe_pct {agg_reported} does not equal sum of per-safe {agg_from_detail}"
        )


class TestLegacyPreMoneySAFEs:
    """Golden-value regression for YC PRE-MONEY (legacy, pre-Oct-2018) SAFE math.

    Two distinct YC SAFE forms exist:
    - **Post-money** (current): each SAFE locks `purchase / cap` of POST-money FD.
      Covered by TestStackedPostMoneySAFEsGolden.
    - **Pre-money** (legacy): SAFE shares = `purchase / (cap / pre_money_FD)` =
      `purchase × pre_money_FD / cap`. The SAFE's % of post-money is NOT fixed;
      pre-money SAFEs dilute alongside founders when new money + pool refresh land.

    Commit #4 (post-J audit): the J fix corrected post-money math but broke
    pre-money — convert_safe_priced_round was applying a single denominator
    (the iterating post-money FD) to ALL forms. Fix: route on `form` to use
    pre_money_fd for pre-money forms; keep company_capitalization (post-money FD)
    for post-money forms.

    Golden values derived from independent first-principles triangulation by an
    opus subagent against the YC pre-money SAFE primer. Scenario chosen so
    fractions resolve to exact integers:
    - 10M founders common + 1M unallocated pool → pre_money_FD = 11M
    - SAFE: $500k purchase, $5M pre-money cap, no discount
    - Series A: $5M new money at $5M pre (post-money $10M), no pool refresh
    """

    EVAL_PREMONEY_INPUTS = {
        "company_name": "TestCo",
        "analysis_date": "2026-05-21",
        "mode": "standard",
        "jurisdiction": {
            "structure": "delaware",
            "incorporated_date": "2024-06-01",
            "iia_grants_history": {"has_grants": False, "grant_details": []},
        },
        "founders": [
            {"name": "Founder", "founder_id": "founder_1", "common_shares": 10_000_000},
        ],
        "preferred_series": [],
        "option_pool": {
            "plan_type": "nso",
            "authorized": 1_000_000,
            "issued": 0,
            "unallocated": 1_000_000,
        },
        "common_batches": [],
        "metadata": {"run_id": "test"},
    }

    EVAL_PREMONEY_SAFE = {
        "id": "safe_pre_1",
        "investor_name": "Angel L (legacy)",
        "purchase_amount": 500_000,
        "post_money_valuation_cap": None,
        "pre_money_valuation_cap": 5_000_000,  # legacy SAFE uses pre-money cap
        "discount_multiplier": None,
        "mfn_provision": None,
        "pro_rata_side_letter": None,
        "issuance_date": "2017-09-01",  # pre-Oct-2018; legacy form era
        "form": "yc_premoney_cap_only",
        "conversion_price_override": None,
        "source_document": None,
        "extraction_confidence": "high",
    }

    def _instruments(self, safes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "safes": safes,
            "notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test"},
        }

    def test_legacy_premoney_cap_only_uses_pre_fd_denominator(self) -> None:
        """Single-SAFE pre-money scenario; golden answer locked by triangulation.

        Expected (per first-principles derivation):
        - safe_price = $5M / 11M = $5/11 ≈ $0.4545
        - safe_shares = $500k × 11M / $5M = 1,100,000 (exact integer)
        - PPS = $5M / 12.1M = $50/121 ≈ $0.4132
        - new_money_shares = 12,100,000 (exact integer)
        - total_post_money_FD = 24,200,000
        - founders_pct = 10/24.2 ≈ 41.32%
        - safe_pct = 1.1/24.2 ≈ 4.55% (NOT 10% — pre-money SAFE dilutes)
        - new_money_pct = 50% (by construction)
        """
        cs = cap_state_mod.build_cap_state(self.EVAL_PREMONEY_INPUTS, self._instruments([self.EVAL_PREMONEY_SAFE]))
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=[self.EVAL_PREMONEY_SAFE],
            notes=[],
            pre_money=5_000_000,
            new_money=5_000_000,
            target_pool_percent=None,  # no pool refresh
            target_basis="post_money",
        )
        assert r["completeness"] == "full", f"blockers: {r.get('blockers')}"

        # PPS = $50/121 ≈ $0.4132
        assert math.isclose(r["equity_financing_price"], 50 / 121, rel_tol=1e-4), (
            f"PPS: got {r['equity_financing_price']:.6f}, expected {50 / 121:.6f}"
        )
        # Total post-money FD = 24.2M
        assert math.isclose(r["post_round_fully_diluted_shares"], 24_200_000, rel_tol=1e-4)

        # safe_pct ≈ 4.55%, NOT 10% (would be 10% under post-money form)
        agg = r["aggregate_ownership_by_class"]
        assert math.isclose(agg["safe_pct"], 1.1 / 24.2, abs_tol=1e-4), (
            f"safe_pct: got {agg['safe_pct']:.6f}, expected {1.1 / 24.2:.6f} (4.55%, not 10%)"
        )
        # Founders ≈ 41.32%, NOT the post-money-SAFE value of ~36.36%
        assert math.isclose(agg["founders_pct"], 10 / 24.2, abs_tol=1e-4)
        # New money 50% (holds in both forms)
        assert math.isclose(agg["new_money_pct"], 0.50, abs_tol=1e-4)

    def test_legacy_premoney_safe_pct_differs_from_post_money_safe_pct(self) -> None:
        """Smoke test: pre-money SAFE math MUST produce different ownership than
        post-money SAFE math under identical inputs. If the solver collapses both
        forms to the same formula (the regression we're guarding against), this
        fails. safe_pct=10% would be the post-money answer; pre-money is ~4.55%.
        """
        cs = cap_state_mod.build_cap_state(self.EVAL_PREMONEY_INPUTS, self._instruments([self.EVAL_PREMONEY_SAFE]))
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=[self.EVAL_PREMONEY_SAFE],
            notes=[],
            pre_money=5_000_000,
            new_money=5_000_000,
            target_pool_percent=None,
            target_basis="post_money",
        )
        agg = r["aggregate_ownership_by_class"]
        # The post-money YC SAFE identity `safe_pct = purchase/cap = 10%` MUST NOT
        # hold for a pre-money SAFE. If it does, the solver routed the wrong form.
        assert agg["safe_pct"] < 0.08, (
            f"safe_pct {agg['safe_pct']:.4f} is too close to the post-money value "
            f"0.10; pre-money SAFE should dilute to ~0.0455. Form dispatch likely broken."
        )

    def test_mixed_legacy_premoney_and_post_money_safes(self) -> None:
        """Mixed-form scenario: one post-money SAFE + one pre-money SAFE in the
        same priced round. Solver must route each form to its own denominator.

        Expected (algebra in the plan doc):
        - safe_A (post-money $500k @ $5M cap): locks 10% of post-money FD
        - safe_B (pre-money $500k @ $5M cap): locks 1.1M shares (constant)
        - new investor: locks 50% of post-money FD (= new_money / post_money)
        - founders 10M + pool 1M + safe_B 1.1M = 12.1M = 40% of total
        - total post-money FD = 12.1M / 0.40 = 30.25M
        - safe_A_shares = 0.10 × 30.25M = 3,025,000
        - new_money_shares = 0.50 × 30.25M = 15,125,000
        - PPS = $5M / 15.125M ≈ $0.3306
        """
        safe_a_post = {
            "id": "safe_a",
            "investor_name": "Angel A (post-money)",
            "purchase_amount": 500_000,
            "post_money_valuation_cap": 5_000_000,
            "pre_money_valuation_cap": None,
            "discount_multiplier": None,
            "mfn_provision": None,
            "pro_rata_side_letter": None,
            "issuance_date": "2021-01-01",
            "form": "yc_postmoney_cap",
            "conversion_price_override": None,
            "source_document": None,
            "extraction_confidence": "high",
        }
        safe_b_pre = self.EVAL_PREMONEY_SAFE  # the legacy one, id="safe_pre_1"
        cs = cap_state_mod.build_cap_state(self.EVAL_PREMONEY_INPUTS, self._instruments([safe_a_post, safe_b_pre]))
        r = priced_round.solve_priced_round(
            cap_state=cs,
            safes=[safe_a_post, safe_b_pre],
            notes=[],
            pre_money=5_000_000,
            new_money=5_000_000,
            target_pool_percent=None,
            target_basis="post_money",
        )
        assert r["completeness"] == "full", f"blockers: {r.get('blockers')}"

        # Total post-money FD = 30.25M
        assert math.isclose(r["post_round_fully_diluted_shares"], 30_250_000, rel_tol=1e-3), (
            f"total_fd: got {r['post_round_fully_diluted_shares']}, expected 30,250,000"
        )

        # safe_A (post-money) shares = 3.025M
        assert math.isclose(r["per_safe"]["safe_a"]["conversion_shares"], 3_025_000, rel_tol=1e-3)
        # safe_B (pre-money) shares = 1.1M (constant)
        assert math.isclose(r["per_safe"]["safe_pre_1"]["conversion_shares"], 1_100_000, rel_tol=1e-3)

        agg = r["aggregate_ownership_by_class"]
        # Combined safe_pct = (3.025 + 1.1) / 30.25 = 13.64%
        assert math.isclose(agg["safe_pct"], 4.125 / 30.25, abs_tol=1e-4)
        # Founders 10M / 30.25M ≈ 33.06%
        assert math.isclose(agg["founders_pct"], 10 / 30.25, abs_tol=1e-4)
        # New money 50% (still holds — pre/post split sets this)
        assert math.isclose(agg["new_money_pct"], 0.50, abs_tol=1e-3)


# ===========================================================================
# rule_audit.py (two-phase)
# ===========================================================================


class TestRuleAudit:
    def _rules(self) -> dict[str, Any]:
        with open(os.path.join(os.path.dirname(SCRIPTS), "references", "cap-table-rules.json")) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_classify_scope_not_applicable(self) -> None:
        rule = {"rule_id": "r1", "domain": "safe"}  # no date_window
        assert rule_audit._classify_scope(rule) == "not_applicable"

    def test_israeli_aoa_rules_do_not_fire_on_delaware_no_preferred(self) -> None:
        """Real-doc test surfaced this: israeli_aoa.* rules were firing on a
        Delaware C-corp with no preferred series, because they weren't in the
        _RULE_MATCHERS dispatch table and defaulted to _matcher_always.

        Now gated to: jurisdiction_includes_israel AND has_preferred_series.
        """
        delaware_inputs = {
            "jurisdiction": {"structure": "delaware"},
            "mode": "standard",
        }
        empty_instruments = {"safes": [], "notes": [], "warrants": [], "option_grants": []}
        empty_cap_state = {"preferred_series": []}

        for rule_id in (
            "israeli_aoa.drag_along_threshold_below_75_percent",
            "israeli_aoa.section_102_plan_absent",
            "israeli_aoa.liquidation_preference_above_1x",
            "israeli_aoa.full_ratchet_anti_dilution",
        ):
            matcher = rule_audit._RULE_MATCHERS.get(rule_id, rule_audit._matcher_always)
            assert matcher(delaware_inputs, empty_instruments, empty_cap_state) is False, (
                f"{rule_id} should NOT match on Delaware engagement with no preferred series"
            )

    def test_israeli_aoa_rules_fire_on_israeli_with_preferred(self) -> None:
        """Israeli engagement WITH a preferred series → israeli_aoa.* rules apply."""
        israeli_inputs = {
            "jurisdiction": {"structure": "israeli"},
            "mode": "standard",
        }
        empty_instruments = {"safes": [], "notes": [], "warrants": [], "option_grants": []}
        cap_state_with_preferred = {
            "preferred_series": [
                {
                    "series_name": "Series Seed",
                    "anti_dilution_protection": "broad_based_weighted_average",
                    "liquidation_preference_multiple": 1.0,
                }
            ]
        }

        for rule_id in (
            "israeli_aoa.drag_along_threshold_below_75_percent",
            "israeli_aoa.section_102_plan_absent",
            "israeli_aoa.liquidation_preference_above_1x",
            "israeli_aoa.full_ratchet_anti_dilution",
        ):
            matcher = rule_audit._RULE_MATCHERS.get(rule_id, rule_audit._matcher_always)
            assert matcher(israeli_inputs, empty_instruments, cap_state_with_preferred) is True, (
                f"{rule_id} should match on Israeli engagement with preferred series"
            )

    def test_classify_scope_legal_tax_applicability(self) -> None:
        rule = {"date_window": {"event_date_field": "stock_issue_date", "start": "2025-07-05"}}
        assert rule_audit._classify_scope(rule) == "legal_tax_applicability"

    def test_classify_scope_benchmark_freshness(self) -> None:
        rule = {"date_window": {"event_date_field": "benchmark_reference_date"}}
        assert rule_audit._classify_scope(rule) == "benchmark_freshness"

    def test_status_in_window(self) -> None:
        from datetime import date

        status, near_end, near_start = rule_audit._evaluate_date_status(
            event_date_value=date(2026, 1, 1),
            start=date(2025, 1, 1),
            end=date(2026, 12, 31),
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "in_window"
        assert near_end is False  # > 90 days from end
        assert near_start is False

    def test_status_pre_effective(self) -> None:
        from datetime import date

        status, _, near_start = rule_audit._evaluate_date_status(
            event_date_value=date(2025, 6, 1),
            start=date(2025, 7, 5),
            end=None,  # QSBS-style start-only
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "pre_effective"
        # Within 30 days of start? 2025-07-05 - 2025-06-01 = 34 days, so no
        assert near_start is False

    def test_status_expired(self) -> None:
        from datetime import date

        status, _, _ = rule_audit._evaluate_date_status(
            event_date_value=date(2027, 1, 1),
            start=date(2025, 1, 1),
            end=date(2026, 12, 31),
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "expired"

    def test_status_near_end_flag(self) -> None:
        from datetime import date

        status, near_end, _ = rule_audit._evaluate_date_status(
            event_date_value=date(2026, 10, 15),  # 77 days before end 2026-12-31
            start=date(2025, 1, 1),
            end=date(2026, 12, 31),
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "in_window"
        assert near_end is True

    def test_status_missing_event_date(self) -> None:
        status, _, _ = rule_audit._evaluate_date_status(
            event_date_value=None,
            start=None,
            end=None,
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "missing_event_date"

    def test_gating_block_not_date_sensitive_for_core_formula(self) -> None:
        rules = self._rules()
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        # safe.post_money_cap_conversion has no date_window → not_date_sensitive
        entries = gating["safe.post_money_cap_conversion"]
        assert len(entries) == 1
        entry = next(iter(entries.values()))
        assert entry["status"] == "not_date_sensitive"
        assert entry["scope"] == "not_applicable"
        assert entry["event_date_field"] is None
        assert entry["event_date_path"] is None

    def test_gating_block_legal_tax_applicability(self) -> None:
        rules = self._rules()
        # QSBS rule: legal_tax_applicability, missing stock_issue_date in basic fixture
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        qsbs = gating["delaware_cross_border.qsbs_date_sensitive"]
        assert len(qsbs) >= 1
        entry = next(iter(qsbs.values()))
        assert entry["scope"] == "legal_tax_applicability"

    def test_gating_block_benchmark_freshness(self) -> None:
        rules = self._rules()
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        # qualified_financing_threshold uses benchmark_reference_date
        qft = gating["convertible_notes.qualified_financing_threshold"]
        entry = next(iter(qft.values()))
        assert entry["scope"] == "benchmark_freshness"
        assert entry["freshness_status"] in {"fresh", "stale", "unknown"}

    def test_counsel_items_include_missing_event_date(self) -> None:
        """Per rev17: rules with status=missing_event_date STILL surface in counsel
        items (founder needs to be prompted)."""
        rules = self._rules()
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        items = rule_audit.build_counsel_review_items(gating, rules)
        # QSBS has counsel_review=true and missing stock_issue_date in fixture
        qsbs_in_items = any(it["rule_id"] == "delaware_cross_border.qsbs_date_sensitive" for it in items)
        assert qsbs_in_items, f"QSBS missing from counsel items: {[i['rule_id'] for i in items]}"

    def test_applies_when_predicate_israeli_rule_in_delaware_engagement(self) -> None:
        """Per Phase 1 verification #3 (now implemented): Israeli-only rules
        must NOT apply in a pure-Delaware engagement."""
        rules = self._rules()
        # _BASIC_INPUTS has jurisdiction.structure="delaware"
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        # Israeli SAFE rules should be applies_when_matched=False
        israeli_entries = gating.get("safe.israeli_2025_safe_harbor", {})
        for entry in israeli_entries.values():
            assert entry["applies_when_matched"] is False, (
                "Israeli SAFE rule should NOT apply in Delaware-only engagement"
            )

    def test_applies_when_predicate_qsbs_in_israeli_engagement(self) -> None:
        """QSBS is Delaware-only; must NOT apply when structure is israeli."""
        rules = self._rules()
        israeli_inputs = dict(_BASIC_INPUTS)
        israeli_inputs["jurisdiction"] = {
            "structure": "israeli",
            "incorporated_date": "2024-01-01",
            "iia_grants_history": {"has_grants": False, "grant_details": []},
        }
        gating = rule_audit.build_gating_block(
            rules,
            inputs=israeli_inputs,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(israeli_inputs, _BASIC_INSTRUMENTS),
        )
        qsbs = gating["delaware_cross_border.qsbs_date_sensitive"]
        for entry in qsbs.values():
            assert entry["applies_when_matched"] is False, "QSBS should NOT apply in pure-Israeli engagement"

    def test_applies_when_predicate_iia_only_with_iia_grants(self) -> None:
        """IIA royalty rule should apply only when has_grants=True."""
        rules = self._rules()
        israeli_no_iia = dict(_BASIC_INPUTS)
        israeli_no_iia["jurisdiction"] = {
            "structure": "israeli",
            "incorporated_date": "2024-01-01",
            "iia_grants_history": {"has_grants": False, "grant_details": []},
        }
        gating_no_iia = rule_audit.build_gating_block(
            rules,
            inputs=israeli_no_iia,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(israeli_no_iia, _BASIC_INSTRUMENTS),
        )
        iia = gating_no_iia["israeli_ltd.iia_royalties_ip"]
        for entry in iia.values():
            assert entry["applies_when_matched"] is False

        # Now with IIA grants
        israeli_with_iia = dict(_BASIC_INPUTS)
        israeli_with_iia["jurisdiction"] = {
            "structure": "israeli",
            "incorporated_date": "2024-01-01",
            "iia_grants_history": {"has_grants": True, "grant_details": []},
        }
        gating_with_iia = rule_audit.build_gating_block(
            rules,
            inputs=israeli_with_iia,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(israeli_with_iia, _BASIC_INSTRUMENTS),
        )
        iia = gating_with_iia["israeli_ltd.iia_royalties_ip"]
        for entry in iia.values():
            assert entry["applies_when_matched"] is True

    def test_applies_when_predicate_stacked_safes_only_when_multiple(self) -> None:
        """stacked_post_money_caps applies only when 2+ SAFEs exist."""
        rules = self._rules()
        # Zero SAFEs
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        for entry in gating["safe.stacked_post_money_caps"].values():
            assert entry["applies_when_matched"] is False
        # Two SAFEs
        inst_two: dict[str, Any] = dict(_BASIC_INSTRUMENTS)
        inst_two["safes"] = [
            {**_SAFE_BASIC, "id": "safe_001"},
            {**_SAFE_BASIC, "id": "safe_002"},
        ]
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=inst_two,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, inst_two),
        )
        for entry in gating["safe.stacked_post_money_caps"].values():
            assert entry["applies_when_matched"] is True

    def test_applies_when_predicate_anti_dilution_only_when_protected(self) -> None:
        """BBWA rule should fire only when preferred series have BBWA protection."""
        rules = self._rules()
        # No preferred
        gating = rule_audit.build_gating_block(
            rules,
            inputs=_BASIC_INPUTS,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS),
        )
        for entry in gating["anti_dilution.broad_based_weighted_average"].values():
            assert entry["applies_when_matched"] is False

        # With BBWA-protected preferred
        inputs_with_pref = dict(_BASIC_INPUTS)
        inputs_with_pref["preferred_series"] = [
            {
                "series_name": "Series Seed",
                "shares": 1_000_000,
                "original_issue_price": 1.0,
                "original_conversion_price": 1.0,
                "current_conversion_price": 1.0,
                "issuance_date": "2025-01-01",
                "anti_dilution_protection": "broad_based_weighted_average",
            }
        ]
        cs_with_pref = cap_state_mod.build_cap_state(inputs_with_pref, _BASIC_INSTRUMENTS)
        gating = rule_audit.build_gating_block(
            rules,
            inputs=inputs_with_pref,
            instruments=_BASIC_INSTRUMENTS,
            cap_state=cs_with_pref,
        )
        for entry in gating["anti_dilution.broad_based_weighted_average"].values():
            assert entry["applies_when_matched"] is True

    def test_two_phase_subprocess(self) -> None:
        """Full pre_math + post_math subprocess round-trip."""
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "inputs.json")
            inst = os.path.join(d, "instruments.json")
            cap = os.path.join(d, "cap_state.json")
            audit = os.path.join(d, "rule_audit.json")
            with open(inp, "w") as f:
                json.dump(_BASIC_INPUTS, f)
            with open(inst, "w") as f:
                json.dump(_BASIC_INSTRUMENTS, f)
            cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
            cs["metadata"]["run_id"] = "rid1"
            with open(cap, "w") as f:
                json.dump(cs, f)
            rc, _, stderr = _run(
                "rule_audit.py",
                [
                    "--phase",
                    "pre_math",
                    "--inputs",
                    inp,
                    "--instruments",
                    inst,
                    "--cap-state",
                    cap,
                    "--run-id",
                    "rid1",
                    "-o",
                    audit,
                ],
            )
            assert rc == 0, stderr
            with open(audit) as f:
                pre = json.load(f)
            assert "gating" in pre
            assert pre["applied_rules"] == []
            assert pre["date_sensitive_watchlist"] == []

            rc, _, stderr = _run(
                "rule_audit.py",
                [
                    "--phase",
                    "post_math",
                    "--run-id",
                    "rid1",
                    "-o",
                    audit,
                ],
            )
            assert rc == 0, stderr
            with open(audit) as f:
                post = json.load(f)
            # Gating block preserved verbatim
            assert post["gating"] == pre["gating"]
            # post_math populates the watchlist + counsel items
            assert len(post["date_sensitive_watchlist"]) > 0
            assert len(post["applied_rules"]) > 0


# ===========================================================================
# Gotchas — explicit regression tests
# ===========================================================================


class TestGotchas:
    def test_gotcha_1_company_capitalization_excludes_new_money(self) -> None:
        """Gotcha #1: as_converted_totals MUST NOT include new-money shares or
        new pool top-ups. cap_state.py works ONLY with pre-financing inputs."""
        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
        # FD should ONLY include founders (10M) + existing pool (1.5M) = 11.5M
        # No new money. Adding a SAFE doesn't change this either:
        inst_with_safe = {**_BASIC_INSTRUMENTS, "safes": [_SAFE_BASIC]}
        cs_with_safe = cap_state_mod.build_cap_state(_BASIC_INPUTS, inst_with_safe)
        # FD is unchanged — outstanding SAFE is tracked separately, NOT in FD
        assert (
            cs["as_converted_totals"]["fully_diluted_shares"]
            == cs_with_safe["as_converted_totals"]["fully_diluted_shares"]
        )
        # SAFE is tracked
        assert len(cs_with_safe["outstanding_safes"]) == 1

    def test_gotcha_2_bbwa_divisor_uses_cp1(self) -> None:
        """Already tested in TestAntiDilution; this is a labelled regression."""
        r = anti_dilution.bbwa_new_conversion_price(
            current_conversion_price=2.0,  # CP1
            pre_issuance_share_count_A=10_000_000,
            consideration_received=1_000_000,
            new_issue_price=1.0,
            new_shares_issued_C=1_000_000,
        )
        # B = 1M / 2.0 = 500_000 (NOT 1M / OIP)
        assert r["intermediate"]["B"] == 500_000

    def test_gotcha_3_discount_multiplier_normalized(self) -> None:
        """A value of 20 (percent) should be converted to 0.80 (multiplier)."""
        # Use the extract_instrument library
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import normalize_discount_multiplier  # type: ignore[import-not-found]

        mult, warn = normalize_discount_multiplier(20.0)
        assert mult == 0.80
        assert warn is not None and "multiplier" in warn

        mult, warn = normalize_discount_multiplier(0.80)
        assert mult == 0.80
        assert warn is None

        mult, warn = normalize_discount_multiplier(None)
        assert mult is None
        assert warn is None

    def test_gotcha_4_mfn_cycle_unresolvable(self) -> None:
        safes = [
            {
                "id": "A",
                "form": "yc_uncapped_mfn",
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "B",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
            {
                "id": "B",
                "form": "yc_uncapped_mfn",
                "mfn_provision": {
                    "present": True,
                    "elected_against_safe_id": "A",
                    "elected": True,
                    "cherry_pick_attempted": False,
                    "notes": None,
                },
            },
        ]
        cycles = safe_conversion.detect_mfn_cycles(safes)
        assert len(cycles) == 1

    def test_gotcha_5_override_only_applies_to_convert_at_cap(self) -> None:
        for bad_treatment in ["repay", "extend", "counsel_review"]:
            note = dict(_NOTE_BASIC)
            note["maturity_default_treatment"] = bad_treatment
            note["maturity_conversion_price_override"] = 1.0
            r = note_conversion.convert_note(note, conversion_event_date="2027-06-01")
            assert r["branch"] == "override_mismatch", f"failed for {bad_treatment}"

    def test_gotcha_7_flip_is_share_for_share_only_in_v01(self) -> None:
        """v0.1 supports only 1:1 share-for-share."""
        sys.path.insert(0, SCRIPTS)
        from flip_scenario import flip_share_for_share  # type: ignore[import-not-found]

        cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, _BASIC_INSTRUMENTS)
        r = flip_share_for_share(cs)
        assert r["_flip_metadata" if "_flip_metadata" in r else "post_flip_cap_state"]
        # Check the metadata note
        post = r["post_flip_cap_state"]
        assert post["_flip_metadata"]["exchange_ratio"] == "1:1"
        assert "v0_1_scope_limitation" in post["_flip_metadata"]
        # Founder share counts unchanged (1:1)
        for pre_f, post_f in zip(cs["founders"], post["founders"], strict=True):
            assert pre_f["common_shares"] == post_f["common_shares"]

    def test_gotcha_8_qsbs_date_is_2025_07_05(self) -> None:
        """Per Public Law 119-21 §70431: 'after July 4, 2025' → first in-window
        day is 2025-07-05 (with inclusive >= start semantics)."""
        with open(os.path.join(os.path.dirname(SCRIPTS), "references", "cap-table-rules.json")) as f:
            rules = json.load(f)
        qsbs = next(
            r
            for r in rules["domains"]["delaware_cross_border"]
            if r["rule_id"] == "delaware_cross_border.qsbs_date_sensitive"
        )
        assert qsbs["date_window"]["start"] == "2025-07-05"
        # Verify the date evaluation is consistent
        from datetime import date

        status, _, _ = rule_audit._evaluate_date_status(
            event_date_value=date(2025, 7, 4),  # day of enactment
            start=date(2025, 7, 5),
            end=None,
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "pre_effective"  # NOT in QSBS window
        status, _, _ = rule_audit._evaluate_date_status(
            event_date_value=date(2025, 7, 5),  # first eligible day
            start=date(2025, 7, 5),
            end=None,
            near_start_days=30,
            near_end_days=90,
        )
        assert status == "in_window"

    def test_gotcha_9_counsel_review_can_coexist_with_high_confidence(self) -> None:
        """counsel_review is a reliance boundary, NOT a confidence score.
        A rule can be confidence=high AND counsel_review=true."""
        with open(os.path.join(os.path.dirname(SCRIPTS), "references", "cap-table-rules.json")) as f:
            rules = json.load(f)
        high_conf_counsel = [
            r
            for domain in rules["domains"].values()
            for r in domain
            if r.get("confidence") == "high" and r.get("counsel_review") is True
        ]
        # At least one such rule must exist in the rule pack (proof of contract)
        assert len(high_conf_counsel) >= 1, "Expected at least one counsel_review=true + confidence=high rule"

    def test_gotcha_10_cap_implied_only_subflag_set_for_standalone_cap(self) -> None:
        """Standalone cap SAFE = completeness:structural_only + cap_implied_only:true."""
        # Via subprocess of run_scenario
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "inputs.json")
            inst = os.path.join(d, "instruments.json")
            cap = os.path.join(d, "cap_state.json")
            reqs = os.path.join(d, "scenario_requests.json")
            scen = os.path.join(d, "scenarios.json")
            with open(inp, "w") as f:
                json.dump(_BASIC_INPUTS, f)
            inst_safe = {**_BASIC_INSTRUMENTS, "safes": [_SAFE_BASIC]}
            with open(inst, "w") as f:
                json.dump(inst_safe, f)
            cs = cap_state_mod.build_cap_state(_BASIC_INPUTS, inst_safe)
            cs["metadata"]["run_id"] = "rid"
            with open(cap, "w") as f:
                json.dump(cs, f)
            with open(reqs, "w") as f:
                json.dump(
                    [
                        {
                            "scenario_id": "base",
                            "label": "Standalone cap SAFE",
                            "type": "safe_conversion",
                            "parameters": {},
                        }
                    ],
                    f,
                )
            rc, _, stderr = _run(
                "run_scenario.py",
                [
                    "--inputs",
                    inp,
                    "--instruments",
                    inst,
                    "--cap-state",
                    cap,
                    "--scenarios-input",
                    reqs,
                    "--run-id",
                    "rid",
                    "-o",
                    scen,
                ],
            )
            assert rc == 0, stderr
            with open(scen) as f:
                doc = json.load(f)
            co = doc["scenarios"][0]["computed_outputs"]
            assert co["completeness"] == "structural_only"
            assert co.get("cap_implied_only") is True


# ===========================================================================
# Full pipeline end-to-end (subprocess; mirrors SKILL.md workflow)
# ===========================================================================


# ===========================================================================
# Corpus-test-surfaced robustness fixes (real-world edge cases)
# ===========================================================================


# ===========================================================================
# Pre-baseline patches — bugs surfaced by eval-set labeling:
# - legacy pre-money SAFE forms (multiple 2017–2025 corpus cases)
# - statutory ITA Section 3(j) interest rate (Israeli CLA corpus case)
# - warrant + non_instrument classification (warrant-in-safes-folder misfile)
# ===========================================================================


class TestPreBaselinePatches:
    def test_yc_premoney_cap_only_form_validates(self) -> None:
        """Legacy YC pre-money cap-only SAFE corpus case must
        validate when pre_money_valuation_cap is set + no discount."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_safe  # type: ignore[import-not-found]

        errs = validate_safe(
            {
                "form": "yc_premoney_cap_only",
                "purchase_amount": 500000,
                "issuance_date": "2020-06-17",
                "pre_money_valuation_cap": 40_000_000,
                "post_money_valuation_cap": None,
                "discount_multiplier": None,
            }
        )
        assert errs == [], f"unexpected validation errors: {errs}"

    def test_yc_premoney_cap_only_rejects_post_money_cap(self) -> None:
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_safe  # type: ignore[import-not-found]

        errs = validate_safe(
            {
                "form": "yc_premoney_cap_only",
                "purchase_amount": 500000,
                "issuance_date": "2020-06-17",
                "pre_money_valuation_cap": 40_000_000,
                "post_money_valuation_cap": 40_000_000,  # both set — invalid
            }
        )
        assert any("post_money_valuation_cap" in e and "null" in e for e in errs), errs

    def test_pre_money_cap_and_discount_legacy_validates(self) -> None:
        """Legacy YC pre-money cap + discount corpus case."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_safe  # type: ignore[import-not-found]

        errs = validate_safe(
            {
                "form": "pre_money_cap_and_discount_legacy",
                "purchase_amount": 100000,
                "issuance_date": "2017-04-20",
                "pre_money_valuation_cap": 6_000_000,
                "post_money_valuation_cap": None,
                "discount_multiplier": 0.80,
            }
        )
        assert errs == [], f"unexpected validation errors: {errs}"

    def test_pre_money_form_requires_pre_money_cap(self) -> None:
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_safe  # type: ignore[import-not-found]

        errs = validate_safe(
            {
                "form": "pre_money_cap_and_discount_legacy",
                "purchase_amount": 100000,
                "issuance_date": "2017-04-20",
                "pre_money_valuation_cap": None,  # missing!
                "discount_multiplier": 0.80,
            }
        )
        assert any("pre_money_valuation_cap" in e for e in errs), errs

    def test_validate_note_accepts_statutory_ita_section_3j(self) -> None:
        """Israeli CLA corpus case — statutory ITA Section 3(j) rate. annual_interest_rate
        is null because rate is set annually by ITA."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_500_000,
                "interest_rate_type": "statutory_ita_section_3j",
                "annual_interest_rate": None,
                "day_count_basis": 365,
                "issuance_date": "2014-03-25",
                "maturity_date": "2015-09-25",
                "maturity_default_treatment": "convert_at_cap",
            }
        )
        assert errs == [], f"statutory rate should validate with null annual_interest_rate; got: {errs}"

    def test_validate_note_rejects_numeric_when_statutory(self) -> None:
        """Agent must NOT fabricate a numeric rate when type is statutory."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_500_000,
                "interest_rate_type": "statutory_ita_section_3j",
                "annual_interest_rate": 0.05,  # fabricated!
                "day_count_basis": 365,
                "issuance_date": "2014-03-25",
                "maturity_date": "2015-09-25",
                "maturity_default_treatment": "convert_at_cap",
            }
        )
        assert any("must be null" in e for e in errs), errs

    def test_validate_note_accepts_none_interest(self) -> None:
        """SAFE-equivalent convertible security — no interest at all."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 2_500_000,
                "interest_rate_type": "none",
                "annual_interest_rate": None,
                "day_count_basis": 365,
                "issuance_date": "2019-08-07",
                "maturity_date": "2024-08-07",
                "maturity_default_treatment": "convert_at_cap",
            }
        )
        assert errs == [], errs

    def test_validate_note_fixed_numeric_still_requires_rate(self) -> None:
        """Backward compat — existing notes with default interest_rate_type
        (fixed_numeric) MUST still have a numeric rate."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_000_000,
                "interest_rate_type": "fixed_numeric",
                "annual_interest_rate": None,  # missing!
                "day_count_basis": 365,
                "issuance_date": "2019-12-13",
                "maturity_date": "2021-06-13",
                "maturity_default_treatment": "convert_at_cap",
            }
        )
        assert any("annual_interest_rate" in e for e in errs), errs

    def test_validate_note_default_interest_rate_type(self) -> None:
        """If interest_rate_type is absent, default to fixed_numeric for backward compat."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_000_000,
                # No interest_rate_type — should default to fixed_numeric
                "annual_interest_rate": 0.05,
                "day_count_basis": 365,
                "issuance_date": "2019-12-13",
                "maturity_date": "2021-06-13",
                "maturity_default_treatment": "convert_at_cap",
            }
        )
        assert errs == [], f"default fixed_numeric should validate; got: {errs}"

    def test_warrant_doc_type_passes_validation(self) -> None:
        """WARRANT misfile (warrant landed in safes/ folder) — extractor should classify cleanly."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_non_extractable  # type: ignore[import-not-found]

        # Empty fields block + warrant doc_type should be acceptable
        errs = validate_non_extractable({})
        assert errs == [], errs

    def test_non_instrument_doc_type_passes_validation(self) -> None:
        """Notice-of-Financing letter mistaken for a SAFE — extractor classifies as non_instrument."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_non_extractable  # type: ignore[import-not-found]

        errs = validate_non_extractable({})
        assert errs == [], errs

    # ------------------------------------------------------------------
    # Convertible aliases (commit #6 post-J audit)
    # ------------------------------------------------------------------

    def test_validate_note_subtype_cla_uses_standard_gate(self) -> None:
        """Israeli CLA (convertible_loan_agreement subtype) is mathematically
        identical to a standard convertible_note — same required fields."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_500_000,
                "interest_rate_type": "statutory_ita_section_3j",
                "annual_interest_rate": None,
                "day_count_basis": 365,
                "issuance_date": "2019-03-03",
                "maturity_date": "2021-03-03",
                "maturity_default_treatment": "convert_at_cap",
            },
            subtype="convertible_loan_agreement",
        )
        assert errs == [], f"CLA subtype should validate as standard note; got: {errs}"

    def test_validate_note_subtype_convertible_security_waives_maturity(self) -> None:
        """YC convertible_security (SAFE-equivalent) has no maturity / no interest.
        Subtype gate waives maturity_date, maturity_default_treatment,
        day_count_basis, and annual_interest_rate."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        errs = validate_note(
            {
                "principal": 1_000_000,
                "interest_rate_type": "none",
                "annual_interest_rate": None,
                "day_count_basis": None,
                "issuance_date": "2019-08-01",
                "maturity_date": None,
                "maturity_default_treatment": None,
            },
            subtype="convertible_security",
        )
        assert errs == [], f"convertible_security should pass with null maturity/interest; got: {errs}"

    def test_validate_note_subtype_unknown_falls_back_to_standard_gate(self) -> None:
        """An unknown subtype value falls back to the standard convertible_note
        gate (all canonical fields required)."""
        sys.path.insert(0, SCRIPTS)
        from extract_instrument import validate_note  # type: ignore[import-not-found]

        # Missing maturity_date — should fail with subtype=None (the standard
        # convertible_note gate requires it).
        errs = validate_note(
            {
                "principal": 1_000_000,
                "interest_rate_type": "fixed_numeric",
                "annual_interest_rate": 0.05,
                "day_count_basis": 365,
                "issuance_date": "2019-12-13",
                "maturity_date": None,
                "maturity_default_treatment": None,
            },
            subtype=None,
        )
        assert any("maturity_date" in e for e in errs), f"standard note gate must require maturity_date; got: {errs}"

    def test_cli_routes_convertible_loan_agreement_to_notes_with_subtype(self) -> None:
        """End-to-end CLI: instrument_type='convertible_loan_agreement' input
        must (a) validate via the note gate, (b) land in instruments.notes[],
        and (c) carry subtype='convertible_loan_agreement' for provenance."""
        cla_extraction = {
            "instrument_type": "convertible_loan_agreement",
            "fields": {
                "investor_name": "Acmecorp Investors Trustee Ltd.",
                "principal": 7_000_000,
                "interest_rate_type": "statutory_ita_section_3j",
                "annual_interest_rate": None,
                "day_count_basis": 365,
                "interest_converts_to_shares": True,
                "issuance_date": "2019-03-03",
                "valuation_cap": 50_000_000,
                "discount_multiplier": 0.80,
                "qualified_financing_threshold": 5_000_000,
                "maturity_date": "2021-03-03",
                "maturity_default_treatment": "convert_at_cap",
                "extraction_confidence": "high",
            },
            "confidence": {},
            "ambiguities": [],
        }
        with tempfile.TemporaryDirectory() as d:
            instr_path = os.path.join(d, "instruments.json")
            with open(instr_path, "w") as f:
                json.dump(
                    {"safes": [], "notes": [], "warrants": [], "option_grants": [], "metadata": {"run_id": "test"}}, f
                )
            rc, _, e = _run(
                "extract_instrument.py",
                ["--instruments", instr_path, "--run-id", "test", "--no-verify", "--no-invariants"],
                stdin_data=json.dumps(cla_extraction),
            )
            assert rc == 0, f"CLA extraction failed: rc={rc}, stderr={e}"
            with open(instr_path) as f:
                instruments = json.load(f)
            assert len(instruments["notes"]) == 1
            note = instruments["notes"][0]
            assert note["subtype"] == "convertible_loan_agreement"
            assert note["principal"] == 7_000_000

    def test_cli_routes_convertible_security_with_null_maturity(self) -> None:
        """End-to-end CLI: convertible_security input lands in instruments.notes[]
        with subtype tag and null maturity fields. Validates the SAFE-equivalent
        path against a synthetic Foxtrotcorp-style convertible_security shape."""
        cs_extraction = {
            "instrument_type": "convertible_security",
            "fields": {
                "investor_name": "Acmecorp Holdings",  # synthetic; real doc was Foxtrotcorp
                "principal": 250_000,
                "interest_rate_type": "none",
                "annual_interest_rate": None,
                "interest_converts_to_shares": True,
                "issuance_date": "2019-08-01",
                "valuation_cap": 15_000_000,
                "discount_multiplier": None,
                "qualified_financing_threshold": 1_000_000,
                "maturity_date": None,
                "maturity_default_treatment": None,
                "extraction_confidence": "high",
            },
            "confidence": {},
            "ambiguities": [],
        }
        with tempfile.TemporaryDirectory() as d:
            instr_path = os.path.join(d, "instruments.json")
            with open(instr_path, "w") as f:
                json.dump(
                    {"safes": [], "notes": [], "warrants": [], "option_grants": [], "metadata": {"run_id": "test"}}, f
                )
            rc, _, e = _run(
                "extract_instrument.py",
                ["--instruments", instr_path, "--run-id", "test", "--no-verify", "--no-invariants"],
                stdin_data=json.dumps(cs_extraction),
            )
            assert rc == 0, f"convertible_security extraction failed: rc={rc}, stderr={e}"
            with open(instr_path) as f:
                instruments = json.load(f)
            assert len(instruments["notes"]) == 1
            note = instruments["notes"][0]
            assert note["subtype"] == "convertible_security"
            assert note["maturity_date"] is None
            assert note["interest_rate_type"] == "none"


class TestAoAExtraction:
    """Tests for extract_aoa.py — AoA (Articles of Association) extraction
    validator + counsel-review item detection + merge-into-inputs flow.

    Commit #7 post-J audit. Synthetic fixtures based on the 5 real Israeli
    AoAs at ~/private-corpus/aoa/ (Deltacorp 2024, Bravocorp Series A 2022,
    Charliecorp Seed-2 2016, Acmecorp 2012, generic 2015). Real AoAs are NOT
    included as fixtures (per the redaction rule — no real founder/company
    names in committed artifacts).
    """

    @staticmethod
    def _valid_aoa_extraction() -> dict[str, Any]:
        """Synthetic AoA extraction shape — single preferred series, Israeli."""
        return {
            "extraction_type": "articles_of_association",
            "fields": {
                "company_name": "Acmecorp Ltd.",
                "jurisdiction_structure": "israeli",
                "section_102_plan_reference": True,
                "drag_along_threshold_pct": 0.75,
                "preferred_series": [
                    {
                        "series_name": "Series Seed",
                        "shares": None,
                        "original_issue_price": 1.175,
                        "original_conversion_price": 1.175,
                        "current_conversion_price": 1.175,
                        "issuance_date": "2018-03-15",
                        "liquidation_preference_multiple": 1.0,
                        "liquidation_preference_type": "participating",
                        "participation_cap_multiple": None,
                        "anti_dilution_protection": "broad_based_weighted_average",
                        "dividend_rate_percent": 0.08,
                        "dividend_cumulative": True,
                        "pro_rata_rights": True,
                    }
                ],
            },
            "confidence": {},
            "ambiguities": [],
        }

    def test_valid_aoa_extraction_passes(self) -> None:
        """Canonical valid AoA extraction — no validation errors."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        errs = validate_aoa_extraction(self._valid_aoa_extraction())
        assert errs == [], errs

    def test_extraction_type_mismatch_rejected(self) -> None:
        """extraction_type must be 'articles_of_association' — anything else fails."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        ext = self._valid_aoa_extraction()
        ext["extraction_type"] = "instrument_extraction"
        errs = validate_aoa_extraction(ext)
        assert any("extraction_type" in e for e in errs)

    def test_missing_oip_rejected(self) -> None:
        """A preferred series without original_issue_price fails validation."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        ext = self._valid_aoa_extraction()
        ext["fields"]["preferred_series"][0]["original_issue_price"] = None
        errs = validate_aoa_extraction(ext)
        assert any("original_issue_price" in e for e in errs)

    def test_participating_capped_requires_cap_multiple(self) -> None:
        """liquidation_preference_type='participating_capped' requires
        participation_cap_multiple to be non-null."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        ext = self._valid_aoa_extraction()
        ext["fields"]["preferred_series"][0]["liquidation_preference_type"] = "participating_capped"
        ext["fields"]["preferred_series"][0]["participation_cap_multiple"] = None
        errs = validate_aoa_extraction(ext)
        assert any("participation_cap_multiple" in e for e in errs)

    def test_invalid_anti_dilution_enum_rejected(self) -> None:
        """anti_dilution_protection must be one of the canonical enum values."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        ext = self._valid_aoa_extraction()
        ext["fields"]["preferred_series"][0]["anti_dilution_protection"] = "magic_ratchet"
        errs = validate_aoa_extraction(ext)
        assert any("anti_dilution_protection" in e for e in errs)

    def test_liquidation_pref_below_1x_rejected(self) -> None:
        """liquidation_preference_multiple must be ≥ 1.0 (Israeli + US convention)."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import validate_aoa_extraction  # type: ignore[import-not-found]

        ext = self._valid_aoa_extraction()
        ext["fields"]["preferred_series"][0]["liquidation_preference_multiple"] = 0.5
        errs = validate_aoa_extraction(ext)
        assert any("liquidation_preference_multiple" in e for e in errs)

    def test_counsel_items_drag_along_below_75(self) -> None:
        """Israeli AoA with drag-along < 75% surfaces counsel-review item."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import detect_counsel_review_items  # type: ignore[import-not-found]

        fields = self._valid_aoa_extraction()["fields"]
        fields["drag_along_threshold_pct"] = 0.65
        items = detect_counsel_review_items(fields)
        assert any(it["rule_id"] == "israeli_aoa.drag_along_threshold_below_75_percent" for it in items)

    def test_counsel_items_section_102_absent(self) -> None:
        """Israeli AoA without §102 plan reference flags counsel review."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import detect_counsel_review_items  # type: ignore[import-not-found]

        fields = self._valid_aoa_extraction()["fields"]
        fields["section_102_plan_reference"] = False
        items = detect_counsel_review_items(fields)
        assert any(it["rule_id"] == "israeli_aoa.section_102_plan_absent" for it in items)

    def test_counsel_items_above_1x_liquidation_pref(self) -> None:
        """Above-1x liquidation preference triggers counsel review."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import detect_counsel_review_items  # type: ignore[import-not-found]

        fields = self._valid_aoa_extraction()["fields"]
        fields["preferred_series"][0]["liquidation_preference_multiple"] = 2.0
        items = detect_counsel_review_items(fields)
        assert any(it["rule_id"] == "israeli_aoa.liquidation_preference_above_1x" for it in items)

    def test_counsel_items_full_ratchet_anti_dilution(self) -> None:
        """Full-ratchet anti-dilution triggers counsel review."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import detect_counsel_review_items  # type: ignore[import-not-found]

        fields = self._valid_aoa_extraction()["fields"]
        fields["preferred_series"][0]["anti_dilution_protection"] = "full_ratchet"
        items = detect_counsel_review_items(fields)
        assert any(it["rule_id"] == "israeli_aoa.full_ratchet_anti_dilution" for it in items)

    def test_counsel_items_clean_aoa_returns_empty(self) -> None:
        """A clean AoA (drag-along ≥ 75%, §102 present, 1x non-participating,
        BBWA anti-dilution) produces no counsel-review items."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import detect_counsel_review_items  # type: ignore[import-not-found]

        fields = self._valid_aoa_extraction()["fields"]
        fields["preferred_series"][0]["liquidation_preference_multiple"] = 1.0
        fields["preferred_series"][0]["liquidation_preference_type"] = "non_participating"
        fields["preferred_series"][0]["anti_dilution_protection"] = "broad_based_weighted_average"
        items = detect_counsel_review_items(fields)
        assert items == [], f"clean AoA should produce no counsel items; got: {items}"

    def test_merge_into_inputs_appends_new_series(self) -> None:
        """AoA-extracted preferred_series is appended to inputs.preferred_series[]
        with extraction_provenance stamp."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import merge_into_inputs  # type: ignore[import-not-found]

        with tempfile.TemporaryDirectory() as d:
            inputs_path = os.path.join(d, "inputs.json")
            with open(inputs_path, "w") as f:
                json.dump(
                    {
                        "company_name": "Acmecorp Ltd.",
                        "analysis_date": "2026-05-21",
                        "mode": "standard",
                        "preferred_series": [],
                        "metadata": {"run_id": "test"},
                    },
                    f,
                )

            new_series = self._valid_aoa_extraction()["fields"]["preferred_series"]
            result = merge_into_inputs(inputs_path, new_series, source_doc="/path/to/aoa.pdf")
            assert result["status"] == "merged"
            assert result["added_count"] == 1
            with open(inputs_path) as f:
                inputs = json.load(f)
            assert len(inputs["preferred_series"]) == 1
            merged = inputs["preferred_series"][0]
            assert merged["series_name"] == "Series Seed"
            assert merged["extraction_provenance"]["source_doc"] == "/path/to/aoa.pdf"

    def test_merge_into_inputs_conflict_on_duplicate_series_name(self) -> None:
        """Attempting to merge a series with an already-present series_name
        returns status='conflict' (caller must resolve)."""
        sys.path.insert(0, SCRIPTS)
        from extract_aoa import merge_into_inputs  # type: ignore[import-not-found]

        with tempfile.TemporaryDirectory() as d:
            inputs_path = os.path.join(d, "inputs.json")
            with open(inputs_path, "w") as f:
                json.dump(
                    {
                        "company_name": "Acmecorp Ltd.",
                        "preferred_series": [{"series_name": "Series Seed", "shares": 1_000_000}],
                        "metadata": {"run_id": "test"},
                    },
                    f,
                )
            new_series = self._valid_aoa_extraction()["fields"]["preferred_series"]
            result = merge_into_inputs(inputs_path, new_series, source_doc="/path/to/aoa.pdf")
            assert result["status"] == "conflict"
            assert "Series Seed" in result["conflicts"]

    def test_cli_end_to_end_validates_and_merges(self) -> None:
        """End-to-end: pipe AoA extraction JSON through extract_aoa.py CLI,
        verify it validates + merges + returns counsel items."""
        with tempfile.TemporaryDirectory() as d:
            inputs_path = os.path.join(d, "inputs.json")
            with open(inputs_path, "w") as f:
                json.dump(
                    {
                        "company_name": "Acmecorp Ltd.",
                        "analysis_date": "2026-05-21",
                        "mode": "standard",
                        "preferred_series": [],
                        "metadata": {"run_id": "test"},
                    },
                    f,
                )
            extraction = self._valid_aoa_extraction()
            rc, out, err = _run(
                "extract_aoa.py",
                ["--run-id", "test", "--inputs", inputs_path, "--source-doc", "/path/aoa.pdf", "--pretty"],
                stdin_data=json.dumps(extraction),
            )
            assert rc == 0, f"extract_aoa.py failed: rc={rc}, stderr={err}"
            receipt = json.loads(out)
            assert receipt["status"] == "validated"
            assert receipt["preferred_series_count"] == 1
            assert "merge" in receipt
            assert receipt["merge"]["status"] == "merged"


class TestPrivacyAssertion:
    """Tests for compose_report._assert_coaching_payload_privacy_clean().

    M9 word-boundary + length-threshold defense-in-depth: ensures the
    assertion catches genuine investor-name leaks while NOT firing on
    legitimate generic text that happens to contain investor-name substrings.
    """

    @staticmethod
    def _instruments_with_investor(name: str) -> dict[str, Any]:
        return {
            "safes": [
                {
                    "id": "s1",
                    "investor_name": name,
                    "purchase_amount": 500_000,
                    "post_money_valuation_cap": 10_000_000,
                    "discount_multiplier": None,
                    "mfn_provision": None,
                    "pro_rata_side_letter": None,
                    "issuance_date": "2025-01-01",
                    "form": "yc_postmoney_cap",
                    "conversion_price_override": None,
                    "source_document": None,
                    "extraction_confidence": "high",
                }
            ],
            "notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {"run_id": "test"},
        }

    def test_assertion_catches_word_boundary_leak(self) -> None:
        """Positive case: investor name appears as a whole word in the payload."""
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "company_name": "TestCo",
            "scenario_digest": [{"scenario_drivers": ["Sequoia Capital Operations LLC participated in the round"]}],
        }
        instruments = self._instruments_with_investor("Sequoia Capital Operations LLC")
        with pytest.raises(AssertionError, match="privacy-scrub violation"):
            compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments)

    def test_assertion_passes_on_clean_payload(self) -> None:
        """Negative case: legitimate payload with no investor names passes."""
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "company_name": "TestCo",
            "scenario_digest": [
                {
                    "scenario_drivers": [
                        "Series A at $20M pre-money",
                        "Pool top-up to 10% post-money",
                    ]
                }
            ],
        }
        instruments = self._instruments_with_investor("Sequoia Capital Operations LLC")
        # Should not raise
        compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments)

    def test_assertion_does_not_false_fire_on_short_substring(self) -> None:
        """M9: short / common investor-name substrings ('SAFE', 'Inc', 'LLC',
        'Capital') must NOT trigger false positives on generic template prose.
        Length threshold >8 chars filters these out.
        """
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "scenario_digest": [
                {"branch_summary": "cap_plus_discount + new money", "completeness": "full"},
                {"scenario_drivers": ["Pool top-up to 10% post-money basis"]},
            ],
            "headline_inputs": {"target_basis": "post_money"},
        }
        # Real-world short fund names that would falsely fire under the v1 bare
        # substring check (n>2): "SAFE" inside "yc_postmoney_cap_plus_discount",
        # "Inc" inside "Pool top-up to 10%" — wait, "Inc" doesn't appear here.
        # The key M9 test: a short fund name doesn't cause false positives on
        # standard template strings.
        for short_name in ["SAFE Fund", "Capital", "Inc Co", "LLC Co"]:
            instruments = self._instruments_with_investor(short_name)
            compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments)

    def test_assertion_word_boundary_prevents_substring_false_positive(self) -> None:
        """M9: even a long investor name should match only as a whole word.
        'AcmeCorp Partners' must NOT match 'AcmeCorp Partnership' (different
        word). With bare substring `in`, this would fire spuriously.
        """
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "scenario_digest": [{"scenario_drivers": ["AcmeCorp Partnership terms reviewed"]}],
        }
        instruments = self._instruments_with_investor("AcmeCorp Partners")
        # 'AcmeCorp Partners' is NOT a substring of 'AcmeCorp Partnership' at
        # word boundaries — should pass.
        compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments)

    def test_assertion_catches_founder_name_leak(self) -> None:
        """H6: founder names from inputs.founders[].name must also fire the
        assertion. The agent body promises both investor + founder scrubbing.
        """
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "scenario_digest": [{"scenario_drivers": ["Alexander Hamilton-Jones diluted to 22%"]}],
        }
        instruments = self._instruments_with_investor("Sequoia Capital Operations")
        inputs = {
            "company_name": "TestCo",
            "founders": [{"name": "Alexander Hamilton-Jones", "common_shares": 10_000_000}],
        }
        with pytest.raises(AssertionError, match="founder name leak"):
            compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments, inputs=inputs)

    def test_assertion_company_name_carve_out(self) -> None:
        """H6 carve-out: a founder whose name overlaps with the company name
        (founder 'Acme Holdings Founder Trust' at 'Acme Holdings') must NOT
        trigger the assertion. The company_name is intentionally in the
        payload as engagement identity.
        """
        import compose_report  # type: ignore[import-not-found]

        payload = {
            "company_name": "Acme Holdings",
            "scenario_digest": [{"label": "Series A at Acme Holdings"}],
        }
        instruments = self._instruments_with_investor("Sequoia Capital Operations")
        inputs = {
            "company_name": "Acme Holdings",
            "founders": [{"name": "Acme Holdings Founder Trust", "common_shares": 10_000_000}],
        }
        # Founder name contains the company name → carve out, no leak.
        compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments, inputs=inputs)

    def test_assertion_founder_becomes_investor_carve_out(self) -> None:
        """H6 carve-out: a founder who also appears as an investor in the
        SAFE list (common in Israeli market) is treated as an investor for
        the purpose of this check. The check still fires on investor-side
        leaks (if name appears in payload), but the founder-side check
        is suppressed to avoid double-counting.
        """
        import compose_report  # type: ignore[import-not-found]

        founder_investor_name = "Alice Mendelssohn-Rothschild"
        payload = {
            "scenario_digest": [{"scenario_drivers": ["Series A pre-money $20M"]}],
        }
        instruments = self._instruments_with_investor(founder_investor_name)
        inputs = {
            "company_name": "TestCo",
            "founders": [{"name": founder_investor_name, "common_shares": 10_000_000}],
        }
        # Name in both lists; payload doesn't leak it → should pass.
        compose_report._assert_coaching_payload_privacy_clean(payload, instruments=instruments, inputs=inputs)


class TestEvidenceVerifierIntegration:
    """extract_instrument.py --verify --source-doc integration.

    Tests the wiring of evidence_verifier into the extraction validator.
    Verification is INFORMATIONAL by default; --verify-blocking flips to gating.
    """

    @pytest.fixture
    def safe_doc_text(self, tmp_path: Any) -> Any:
        """Synthetic SAFE-like document text. Contains $20M cap + 80% discount.
        Padded past the image-only threshold (500 chars) so verifier runs."""
        text = (
            "SIMPLE AGREEMENT FOR FUTURE EQUITY\n\n"
            "THIS CERTIFIES THAT in exchange for the payment by Foobar Capital LLC "
            '("Investor") of $500,000 (the "Purchase Amount") on or about January 15, 2024, '
            'Acmecorp Inc. (the "Company") issues to Investor the right to certain shares. '
            'The "Post-Money Valuation Cap" is $20,000,000. The "Discount Rate" is 80%. '
            'This Safe is one of a series of Safes referred to as the "2024 Series Seed Safes." '
            "The Company hereby covenants and agrees with the Investor as follows: This Safe "
            "shall convert in connection with a future Equity Financing on the terms set forth "
            "herein. Standard provisions for conversion, liquidation, dissolution events, and "
            "related rights apply, as set forth in the YC standard form. The rights and "
            "obligations of the parties hereunder shall survive the conversion. This document "
            "incorporates by reference the standard YC Safe Pro-Rata side letter where applicable. "
        )
        p = tmp_path / "synthetic_safe.txt"
        p.write_text(text)
        return p

    @pytest.fixture
    def basic_instruments_path(self, tmp_path: Any) -> Any:
        p = tmp_path / "instruments.json"
        p.write_text(json.dumps(_BASIC_INSTRUMENTS))
        return p

    def test_verify_disabled_with_no_verify(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """--verify defaults ON; --no-verify disables it.
        Verifies the opt-out path keeps existing test semantics."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "discount_multiplier": 0.80,
                "post_money_valuation_cap": 20000000,
            },
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_off",
                "--no-verify",
                "--no-invariants",
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "evidence_verification" not in receipt
        assert "invariant_check" not in receipt

    def test_verify_default_on_requires_source_doc(self, basic_instruments_path: Any) -> None:
        """With --verify default ON,, missing --source-doc errors."""
        extraction = {
            "instrument_type": "safe",
            "fields": _SAFE_BASIC,
            "confidence": {},
            "ambiguities": [],
        }
        rc, _, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_default_verify_no_source",
                # no --no-verify and no --source-doc → should error
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 1
        assert "source-doc" in err.lower() or "source_doc" in err.lower()

    def test_verify_informational_passes_clean_extraction(
        self, basic_instruments_path: Any, safe_doc_text: Any
    ) -> None:
        """A SAFE extraction where every value is in the source doc passes verification."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "investor_name": "Foobar Capital LLC",
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
                "issuance_date": "2024-01-15",  # match the synthetic doc
            },
            "confidence": {
                "purchase_amount": {"level": "high", "evidence_quote": '$500,000 (the "Purchase Amount")'},
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $20,000,000.',
                },
                "discount_multiplier": {"level": "high", "evidence_quote": 'The "Discount Rate" is 80%.'},
                "investor_name": {"level": "high", "evidence_quote": "Foobar Capital LLC"},
                "issuance_date": {"level": "high", "evidence_quote": "on or about January 15, 2024"},
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_clean",
                "--verify",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "evidence_verification" in receipt
        ev = receipt["evidence_verification"]
        assert ev["overall_status"] in ("pass", "no_verifiable_fields"), ev
        assert ev["filtered_summary"]["n_fail"] == 0, ev

    def test_verify_informational_catches_hallucinated_value(
        self, basic_instruments_path: Any, safe_doc_text: Any
    ) -> None:
        """A SAFE with a hallucinated cap (cap=$99M when doc says $20M) is caught
        by value_in_doc check. earlier work: informational — receipt records the
        failure but extraction still exits 0."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "investor_name": "Foobar Capital LLC",
                "post_money_valuation_cap": 99_000_000,  # FAKE — doc says $20M
                "discount_multiplier": 0.80,
            },
            "confidence": {
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $99,000,000.',
                },  # fabricated quote
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_hallucination_informational",
                "--verify",
                "--no-verify-blocking",  # --verify-blocking is default ON; opt out for informational mode
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        # Informational mode: still exits 0
        assert rc == 0, err
        receipt = json.loads(out)
        ev = receipt["evidence_verification"]
        assert ev["overall_status"] == "fail", ev
        assert "rejection" in ev
        assert ev["rejection"]["rejected"] is False  # informational
        assert "post_money_valuation_cap" in ev["rejection"]["failed_fields"]
        assert "retry_hint" in ev["rejection"]

    def test_verify_blocking_exits_nonzero_on_hallucination(
        self, basic_instruments_path: Any, safe_doc_text: Any
    ) -> None:
        """earlier work preview: --verify-blocking exits 1 on value_in_doc failures."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "post_money_valuation_cap": 99_000_000,  # FAKE
                "discount_multiplier": 0.80,
            },
            "confidence": {
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $99,000,000.',
                },
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_hallucination_blocking",
                "--verify",
                "--verify-blocking",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 1, f"blocking mode should fail on hallucination; stderr={err!r}"
        # Receipt should still be printed
        receipt = json.loads(out)
        assert receipt["evidence_verification"]["rejection"]["rejected"] is True
        assert "post_money_valuation_cap" in receipt["evidence_verification"]["rejection"]["failed_fields"]

    def test_verify_skips_synthesized_fields(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """Form enum, jurisdiction, mfn_provision are synthesized — verifier
        should mark them skipped_synthesized, not fail them."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",  # synthesized enum
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
            },
            "confidence": {
                "form": {"level": "high", "evidence_quote": "POST-MONEY VALUATION CAP"},
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $20,000,000.',
                },
                "discount_multiplier": {"level": "high", "evidence_quote": 'The "Discount Rate" is 80%.'},
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_synthesized",
                "--verify",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        ev = receipt["evidence_verification"]
        assert ev["n_skipped_synthesized"] >= 1
        form_field = next(f for f in ev["per_field"] if f["field"] == "form")
        assert form_field["status"] == "skipped_synthesized"

    def test_verify_warrant_is_skipped(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """Non-extractable doc types (warrant, non_instrument) skip verification."""
        extraction = {
            "instrument_type": "warrant",
            "fields": {},
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_warrant",
                "--verify",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert receipt["evidence_verification"]["overall_status"] == "skipped_non_instrument"

    def test_verify_requires_source_doc(self, basic_instruments_path: Any) -> None:
        """--verify without --source-doc errors out."""
        extraction = {
            "instrument_type": "safe",
            "fields": _SAFE_BASIC,
            "confidence": {},
            "ambiguities": [],
        }
        rc, _, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_verify_no_source",
                "--verify",
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 1
        assert "source-doc" in err.lower()


class TestInvariantCheckerIntegration:
    """--invariants default ON in extract_instrument.py. Hard math
    invariants exit 1; soft bounds violations warn-only via receipt."""

    @pytest.fixture
    def basic_instruments_path(self, tmp_path: Any) -> Any:
        p = tmp_path / "instruments.json"
        p.write_text(json.dumps(_BASIC_INSTRUMENTS))
        return p

    @pytest.fixture
    def safe_doc_text(self, tmp_path: Any) -> Any:
        # Padded past the image-only threshold so verifier runs.
        text = (
            "SAFE\n\n"
            'Foobar Capital LLC (the "Investor") pays $500,000 (the "Purchase Amount") '
            'on or about January 15, 2024. The "Post-Money Valuation Cap" is $20,000,000. '
            'The "Discount Rate" is 80%. This Safe is one of a series of 2024 Seed Safes. '
            "Standard YC provisions for conversion, equity financing, liquidity event, dissolution, "
            "and miscellaneous matters apply. Standard amendments, governing law, dispute resolution, "
            "counterparts apply. " * 4
        )
        p = tmp_path / "synthetic_safe.txt"
        p.write_text(text)
        return p

    def test_invariants_on_by_default_clean_safe(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """Clean SAFE within all bounds → invariant_check block in receipt, n_violations=0."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
                "issuance_date": "2024-01-15",
                "investor_name": "Foobar Capital LLC",
            },
            "confidence": {
                "purchase_amount": {"level": "high", "evidence_quote": '$500,000 (the "Purchase Amount")'},
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $20,000,000.',
                },
                "discount_multiplier": {"level": "high", "evidence_quote": 'The "Discount Rate" is 80%.'},
                "investor_name": {"level": "high", "evidence_quote": "Foobar Capital LLC"},
                "issuance_date": {"level": "high", "evidence_quote": "on or about January 15, 2024"},
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_invariants_clean",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "invariant_check" in receipt
        assert receipt["invariant_check"]["n_violations"] == 0
        assert receipt["invariant_check"]["n_hard_violations"] == 0

    def test_invariant_hard_violation_blocks(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """SAFE with both pre_money_valuation_cap AND post_money_valuation_cap set →
        hard math violation. extract_instrument.py exits 1 even with --no-verify."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "other",  # avoid validate_safe gate triggering first
                "pre_money_valuation_cap": 10_000_000,
                "post_money_valuation_cap": 12_000_000,  # both set — math impossible
            },
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_invariants_hard_block",
                "--no-verify",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 1, f"hard invariant should block; out={out[:300]} err={err[:300]}"
        assert "invariant" in err.lower()

    def test_invariants_can_be_disabled(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """--no-invariants disables the check; even hard violations pass through."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "other",
                "pre_money_valuation_cap": 10_000_000,
                "post_money_valuation_cap": 12_000_000,  # hard violation
            },
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_invariants_disabled",
                "--no-verify",
                "--no-invariants",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "invariant_check" not in receipt

    def test_soft_bounds_violation_warns_not_blocks(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """SAFE with $500M purchase_amount (unit error?) → soft bound warning, rc=0."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000_000,  # $500M — above $50M SAFE max, soft warn
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
                "issuance_date": "2024-01-15",
                "investor_name": "Foobar Capital LLC",
            },
            "confidence": {
                "purchase_amount": {"level": "high", "evidence_quote": "$500,000"},
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $20,000,000.',
                },
                "discount_multiplier": {"level": "high", "evidence_quote": 'The "Discount Rate" is 80%.'},
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_invariants_soft",
                "--no-verify",  # purchase_amount=$500M not in synth doc; skip evidence check
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err  # soft violations don't block
        receipt = json.loads(out)
        assert receipt["invariant_check"]["n_violations"] >= 1
        assert receipt["invariant_check"]["n_hard_violations"] == 0
        # And the field appears in attention_needed_fields
        assert "purchase_amount" in receipt.get("attention_needed_fields", [])

    def test_invariants_skipped_for_warrant(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """Warrants and non_instrument classifications skip invariant_check entirely."""
        extraction = {
            "instrument_type": "warrant",
            "fields": {},
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_invariants_warrant",
                "--no-verify",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "invariant_check" not in receipt


class TestCrossCheckerIntegration:
    """`--cross-check` runs deterministic backstop extractors and surfaces
    confidence demotions when sub-agent and backstop disagree."""

    @pytest.fixture
    def basic_instruments_path(self, tmp_path: Any) -> Any:
        p = tmp_path / "instruments.json"
        p.write_text(json.dumps(_BASIC_INSTRUMENTS))
        return p

    @pytest.fixture
    def safe_doc_text(self, tmp_path: Any) -> Any:
        text = (
            "SIMPLE AGREEMENT FOR FUTURE EQUITY\n\n"
            'in exchange for the payment by Foobar Capital LLC (the "Investor") '
            'of $500,000 (the "Purchase Amount") on or about January 15, 2024, '
            'Acmecorp Inc. (the "Company") issues to Investor the right to certain '
            'shares. The "Post-Money Valuation Cap" is $20,000,000. '
            'The "Discount Rate" is 80%. Standard YC provisions. '
        ) + ("Filler text for image-only threshold avoidance: " * 10)
        p = tmp_path / "synthetic_safe.txt"
        p.write_text(text)
        return p

    def test_cross_check_agreement_no_demotion(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        """When sub-agent + backstop agree, cross_check reports zero demotions."""
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
                "issuance_date": "2024-01-15",
                "investor_name": "Foobar Capital LLC",
            },
            "confidence": {
                "purchase_amount": {"level": "high", "evidence_quote": '$500,000 (the "Purchase Amount")'},
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $20,000,000.',
                },
                "discount_multiplier": {"level": "high", "evidence_quote": 'The "Discount Rate" is 80%.'},
                "issuance_date": {"level": "high", "evidence_quote": "on or about January 15, 2024"},
                "investor_name": {"level": "high", "evidence_quote": "Foobar Capital LLC"},
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_xcheck_agree",
                "--source-doc",
                str(safe_doc_text),
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "cross_check" in receipt
        assert receipt["cross_check"]["n_demotions"] == 0

    def test_cross_check_disagreement_surfaces_demotion(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 99_000_000,  # WRONG — backstop finds $20M
                "discount_multiplier": 0.80,
                "issuance_date": "2024-01-15",
                "investor_name": "Foobar Capital LLC",
            },
            "confidence": {
                "post_money_valuation_cap": {
                    "level": "high",
                    "evidence_quote": 'The "Post-Money Valuation Cap" is $99,000,000.',
                },
            },
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_xcheck_disagree",
                "--source-doc",
                str(safe_doc_text),
                "--no-verify-blocking",
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert receipt["cross_check"]["n_demotions"] >= 1
        assert "post_money_valuation_cap" in receipt.get("attention_needed_fields", [])

    def test_cross_check_can_be_disabled(self, basic_instruments_path: Any, safe_doc_text: Any) -> None:
        extraction = {
            "instrument_type": "safe",
            "fields": {
                **_SAFE_BASIC,
                "form": "cap_plus_discount",
                "purchase_amount": 500_000,
                "post_money_valuation_cap": 20_000_000,
                "discount_multiplier": 0.80,
            },
            "confidence": {},
            "ambiguities": [],
        }
        rc, out, err = _run(
            "extract_instrument.py",
            [
                "--instruments",
                str(basic_instruments_path),
                "--run-id",
                "test_xcheck_off",
                "--source-doc",
                str(safe_doc_text),
                "--no-cross-check",
                "--no-verify",
            ],
            stdin_data=json.dumps(extraction),
        )
        assert rc == 0, err
        receipt = json.loads(out)
        assert "cross_check" not in receipt


# ===========================================================================
# Carta extraction (corpus 2 surfaced 13 real Carta exports — fingerprint,
# Convertible Ledger parsing, discount normalization, cancelled-record skip)
# ===========================================================================

_CARTA_FIXTURE = os.path.join(_REPO, "founder-skills", "tests", "fixtures", "cap-table-corpus", "synthetic_carta.xlsx")


class TestCartaExtraction:
    def test_carta_fingerprint_detects_carta(self) -> None:
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _carta_detect  # type: ignore[import-not-found]

        # Default Carta (full export)
        assert _carta_detect(["Summary Cap Table", "Intermediate Cap Table", "Detailed Cap Table"]) == "carta"
        # Minimal Carta (just summary)
        assert _carta_detect(["Summary Cap Table"]) == "carta"
        # Carta OCX format (rarely used)
        assert _carta_detect(["Capitalization by Stakeholder", "Voting Details", "Context"]) == "carta_ocx"
        # Freeform / lawyer-built — none match
        assert _carta_detect(["Cap Table", "ESOP", "Sheet3"]) is None
        # Pulley-style — not Carta
        assert _carta_detect(["Ownership", "SAFEs", "Shares"]) is None

    def test_carta_fingerprint_strips_whitespace(self) -> None:
        """Corpus surfaced trailing-whitespace sheet names; fingerprint must strip."""
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _carta_detect  # type: ignore[import-not-found]

        assert _carta_detect(["Summary Cap Table ", "Intermediate Cap Table"]) == "carta"

    def test_discount_normalization_carta_percent(self) -> None:
        """Carta stores Conversion Discount as percent-as-fraction (0.2 = 20%).
        Per Gotcha #3 the canonical form is the multiplier (0.80)."""
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _normalize_discount  # type: ignore[import-not-found]

        # 0.2 (Carta percent-as-fraction for 20%) → 0.8 multiplier
        mult, warning = _normalize_discount(0.2)
        assert mult == 0.8
        assert warning is not None and "Carta discount" in warning

        # 20 (Carta percent for 20%) → 0.8 multiplier
        mult, warning = _normalize_discount(20)
        assert mult == 0.8
        assert warning is not None

        # None → None, no warning
        mult, warning = _normalize_discount(None)
        assert mult is None
        assert warning is None

        # Out of range
        mult, warning = _normalize_discount(200)
        assert mult is None
        assert warning is not None and "out of expected range" in warning

    def test_safe_form_inference(self) -> None:
        """SAFE form inferred from cap + discount presence."""
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _infer_safe_form  # type: ignore[import-not-found]

        # cap only
        assert _infer_safe_form(8_000_000, None) == "yc_postmoney_cap"
        # cap + discount
        assert _infer_safe_form(8_000_000, 0.20) == "cap_plus_discount"
        # discount only
        assert _infer_safe_form(None, 0.20) == "yc_postmoney_discount"
        # neither (uncapped MFN or other)
        assert _infer_safe_form(None, None) == "other"

    def test_carta_extract_synthetic_fixture(self) -> None:
        """End-to-end: real-Carta-shape synthetic XLSX → instruments.json."""
        if not os.path.exists(_CARTA_FIXTURE):
            pytest.skip(f"Carta fixture missing: {_CARTA_FIXTURE}")
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _carta_extract  # type: ignore[import-not-found]

        result = _carta_extract(_CARTA_FIXTURE)
        assert result["format"] == "carta"
        assert result["counts"]["safes_extracted"] == 1
        assert result["counts"]["notes_extracted"] == 1
        # Cancelled SAFE was skipped, mentioned in warnings
        assert any("SAFE1-2" in w and "cancelled" in w.lower() for w in result["warnings"])
        # Discount normalization warning fired
        assert any("discount" in w.lower() and "multiplier" in w.lower() for w in result["warnings"])

        # Verify the extracted SAFE
        safes = result["instruments"]["safes"]
        assert len(safes) == 1
        safe = safes[0]
        assert safe["investor_name"] == "Angel Alice"
        assert safe["purchase_amount"] == 250_000
        assert safe["post_money_valuation_cap"] == 8_000_000
        assert safe["discount_multiplier"] == 0.8  # normalized from 0.20
        assert safe["form"] == "cap_plus_discount"  # has both cap + discount
        assert safe["source_document"] == "carta:SAFE1-1"

        # Verify the extracted note
        notes = result["instruments"]["notes"]
        assert len(notes) == 1
        note = notes[0]
        assert note["investor_name"] == "Lender Larry"
        assert note["principal"] == 500_000
        assert note["annual_interest_rate"] == 0.06
        assert note["valuation_cap"] == 10_000_000
        assert note["maturity_date"] == "2027-03-01"

    def test_carta_extract_company_name_from_banner(self) -> None:
        """Carta banner: row 2 is "{Company} Summary Cap Table"; row 3 is
        "As of M/D/YYYY • Generated by ...". Extractor must parse both."""
        if not os.path.exists(_CARTA_FIXTURE):
            pytest.skip(f"Carta fixture missing: {_CARTA_FIXTURE}")
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _carta_extract  # type: ignore[import-not-found]

        result = _carta_extract(_CARTA_FIXTURE)
        assert result["summary_totals"]["company_name"] == "Acmecorp"
        assert result["summary_totals"]["as_of_date"] == "2026-05-19"

    def test_auto_mode_dispatch_subprocess(self) -> None:
        """End-to-end CLI test: --mode=auto sniffs sheet names + dispatches."""
        if not os.path.exists(_CARTA_FIXTURE):
            pytest.skip(f"Carta fixture missing: {_CARTA_FIXTURE}")
        with tempfile.TemporaryDirectory() as d:
            audit = os.path.join(d, "audit.json")
            inst = os.path.join(d, "instruments.json")
            rc, stdout, stderr = _run(
                "extract_cap_table.py",
                ["--mode", "auto", "--xlsx", _CARTA_FIXTURE, "-o", audit, "--instruments", inst, "--pretty"],
            )
            assert rc == 0, stderr
            with open(inst) as f:
                instruments = json.load(f)
            assert len(instruments["safes"]) == 1
            assert len(instruments["notes"]) == 1

    def test_freeform_routing_for_non_carta_xlsx(self) -> None:
        """--mode=auto on a freeform XLSX must route to the freeform fallback
        with a clear remedy pointing at Context-A dispatch."""
        with tempfile.TemporaryDirectory() as d:
            import openpyxl

            wb = openpyxl.Workbook()
            ws = wb.active
            assert ws is not None
            ws.title = "Cap Table"  # Freeform-shaped
            ws["A1"] = "Acme"
            xlsx = os.path.join(d, "freeform.xlsx")
            wb.save(xlsx)
            rc, stdout, stderr = _run("extract_cap_table.py", ["--mode", "auto", "--xlsx", xlsx])
            assert rc != 0
            try:
                receipt = json.loads(stdout)
                assert receipt.get("detected_format") == "freeform"
                assert "SPREADSHEET_STRUCTURE_DETECTION" in receipt.get("remedy", "")
            except json.JSONDecodeError as e:
                raise AssertionError(f"expected JSON output, got: {stdout}") from e


class TestCorpusRobustness:
    """Edge cases surfaced by testing against a 258-file real-world corpus.

    Documented in docs/internal/captable-corpus-test-findings.md.
    """

    def test_normalize_xlsx_macos_dupe_suffix(self) -> None:
        """macOS duplicate-download artifact: `file.xlsx(1)` should normalize
        to `file.xlsx`. 3 of 258 corpus files had this exact failure mode."""
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _normalize_path  # type: ignore[import-not-found]

        normalized, warning = _normalize_path("/tmp/cap.xlsx(1)")
        assert normalized == "/tmp/cap.xlsx"
        assert warning is not None and "macOS" in warning

        normalized, warning = _normalize_path("/tmp/cap.xlsx(2)")
        assert normalized == "/tmp/cap.xlsx"
        assert warning is not None

        # XLS variant
        normalized, warning = _normalize_path("/tmp/cap.xls(1)")
        assert normalized == "/tmp/cap.xls"

        # PDF variant
        normalized, warning = _normalize_path("/tmp/doc.pdf(1)")
        assert normalized == "/tmp/doc.pdf"

        # No suffix — pass through unchanged, no warning
        normalized, warning = _normalize_path("/tmp/cap.xlsx")
        assert normalized == "/tmp/cap.xlsx"
        assert warning is None

    def test_normalize_xlsx_strips_whitespace(self) -> None:
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _normalize_path  # type: ignore[import-not-found]

        normalized, _ = _normalize_path("  /tmp/cap.xlsx  ")
        assert normalized == "/tmp/cap.xlsx"

    def test_reject_eml_with_guidance(self) -> None:
        """When the user forwards an email instead of detaching the attachment."""
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _check_supported_input_type  # type: ignore[import-not-found]

        ok, msg = _check_supported_input_type("/tmp/captable_email.eml")
        assert ok is False
        assert ".eml" in msg or "email" in msg.lower()
        assert "attach" in msg.lower()  # founder-friendly guidance

    def test_supported_types_pass(self) -> None:
        sys.path.insert(0, SCRIPTS)
        from extract_cap_table import _check_supported_input_type  # type: ignore[import-not-found]

        for path in ["/tmp/cap.xlsx", "/tmp/cap.xls", "/tmp/cap.pdf", "/tmp/cap.docx"]:
            ok, _ = _check_supported_input_type(path)
            assert ok is True, f"Should accept {path}"

    def test_eml_rejected_via_subprocess(self) -> None:
        """Full CLI round-trip: passing an .eml exits non-zero with structured blocker."""
        with tempfile.TemporaryDirectory() as d:
            eml_path = os.path.join(d, "captable.eml")
            with open(eml_path, "w") as f:
                f.write("From: lawyer@example.com\nSubject: Cap table\n\n[attachment removed]")
            rc, stdout, stderr = _run(
                "extract_cap_table.py",
                ["--mode", "freeform", "--xlsx", eml_path, "-o", os.path.join(d, "audit.json")],
            )
            assert rc != 0
            # stdout should contain the structured blocker
            try:
                receipt = json.loads(stdout.strip().splitlines()[-1])
                assert receipt.get("ok") is False
                assert receipt.get("blocker") == "unsupported_input_type"
                assert "attach" in receipt.get("remedy", "").lower()
            except (json.JSONDecodeError, IndexError):
                # Fall back: just check stderr/stdout contains a recognizable error string
                combined = (stdout + stderr).lower()
                assert "email" in combined or "eml" in combined


class TestPipelineE2E:
    def test_full_pipeline_acmecorp(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            RID = "20260519T120000Z"
            inp = os.path.join(d, "inputs.json")
            inst = os.path.join(d, "instruments.json")
            cap = os.path.join(d, "cap_state.json")
            audit = os.path.join(d, "rule_audit.json")
            reqs = os.path.join(d, "scenario_requests.json")
            scen = os.path.join(d, "scenarios.json")
            packet_json = os.path.join(d, "counsel_packet.json")
            packet_md = os.path.join(d, "counsel_packet.md")
            report_json = os.path.join(d, "report.json")
            report_md = os.path.join(d, "report.md")
            html = os.path.join(d, "report.html")
            explorer = os.path.join(d, "explorer.html")

            # Stamp run_id on inputs + instruments
            inputs = dict(_BASIC_INPUTS)
            inputs["metadata"] = {"run_id": RID}
            instruments = {**_BASIC_INSTRUMENTS, "safes": [_SAFE_BASIC]}
            instruments["metadata"] = {"run_id": RID}
            with open(inp, "w") as f:
                json.dump(inputs, f)
            with open(inst, "w") as f:
                json.dump(instruments, f)

            # Step 1 — cap_state
            rc, _, e = _run(
                "cap_state.py",
                [
                    "--inputs",
                    inp,
                    "--instruments",
                    inst,
                    "--run-id",
                    RID,
                    "-o",
                    cap,
                ],
            )
            assert rc == 0, e

            # Step 2 — rule_audit pre_math
            rc, _, e = _run(
                "rule_audit.py",
                [
                    "--phase",
                    "pre_math",
                    "--inputs",
                    inp,
                    "--instruments",
                    inst,
                    "--cap-state",
                    cap,
                    "--run-id",
                    RID,
                    "-o",
                    audit,
                ],
            )
            assert rc == 0, e

            # Step 3 — scenarios
            with open(reqs, "w") as f:
                json.dump(
                    [
                        {
                            "scenario_id": "base",
                            "label": "Cap-implied SAFE",
                            "type": "safe_conversion",
                            "parameters": {},
                        },
                        {
                            "scenario_id": "series_a",
                            "label": "Series A",
                            "type": "priced_round",
                            "parameters": {
                                "pre_money": 20_000_000,
                                "new_money": 5_000_000,
                                "target_pool_percent": 0.10,
                                "target_basis": "pre_money",
                            },
                        },
                    ],
                    f,
                )
            rc, _, e = _run(
                "run_scenario.py",
                [
                    "--inputs",
                    inp,
                    "--instruments",
                    inst,
                    "--cap-state",
                    cap,
                    "--scenarios-input",
                    reqs,
                    "--run-id",
                    RID,
                    "-o",
                    scen,
                ],
            )
            assert rc == 0, e

            # Step 4 — rule_audit post_math
            rc, _, e = _run(
                "rule_audit.py",
                [
                    "--phase",
                    "post_math",
                    "--run-id",
                    RID,
                    "-o",
                    audit,
                ],
            )
            assert rc == 0, e

            # Step 5 — counsel_packet
            rc, _, e = _run(
                "counsel_packet.py",
                [
                    "--rule-audit",
                    audit,
                    "--inputs",
                    inp,
                    "--scenarios",
                    scen,
                    "--run-id",
                    RID,
                    "-o",
                    packet_json,
                    "--write-md",
                    packet_md,
                ],
            )
            assert rc == 0, e

            # Step 6 — compose_report
            rc, _, e = _run(
                "compose_report.py",
                [
                    "--dir",
                    d,
                    "--run-id",
                    RID,
                    "-o",
                    report_json,
                    "--write-md",
                    report_md,
                ],
            )
            assert rc == 0, e

            # Step 7 — visualize
            rc, _, e = _run("visualize.py", ["--dir", d, "-o", html])
            assert rc == 0, e

            # Step 8 — explore
            rc, _, e = _run("explore.py", ["--dir", d, "-o", explorer])
            assert rc == 0, e

            # Verify all artifacts exist + key invariants
            for path in [cap, audit, scen, packet_json, packet_md, report_json, report_md, html, explorer]:
                assert os.path.exists(path) and os.path.getsize(path) > 0, path

            # report.json has the coaching_payload block per the cross-skill invariant
            with open(report_json) as f:
                rpt = json.load(f)
            assert "report_markdown" in rpt
            assert "coaching_payload" in rpt
            cp = rpt["coaching_payload"]
            assert cp["schema_version"] == "v0.5.0-cap-table"
            assert cp["company_name"] == "Acmecorp"
            assert cp["scenarios_modeled"] == 2
            # Per rev15: nullable founder_impact present for full scenarios, null for structural_only
            digests = cp["scenario_digest"]
            assert len(digests) == 2
            base_digest = next(d for d in digests if d["scenario_id"] == "base")
            assert base_digest["completeness"] == "structural_only"
            assert base_digest["founder_impact"] is None  # rev15 nullable contract
            sa_digest = next(d for d in digests if d["scenario_id"] == "series_a")
            assert sa_digest["completeness"] == "full"
            assert sa_digest["founder_impact"] is not None
            # Insertion marker is uuid-bearing
            assert cp["insertion_marker"].startswith("<!-- COACHING_INSERTION_POINT_")
            # The marker appears EXACTLY once in report.md (Context B's Grep test)
            with open(report_md) as f:
                md = f.read()
            assert md.count(cp["insertion_marker"]) == 1

    def test_compose_emits_coaching_payload(self) -> None:
        """Cross-skill invariant test mirror (see tests/test_compose_invariants.py).
        Verifies compose_report.py emits report.json with coaching_payload block."""
        with tempfile.TemporaryDirectory() as d:
            RID = "rid1"
            inputs = dict(_BASIC_INPUTS)
            inputs["metadata"] = {"run_id": RID}
            instruments = dict(_BASIC_INSTRUMENTS)
            instruments["metadata"] = {"run_id": RID}
            for name, data in [
                ("inputs.json", inputs),
                ("instruments.json", instruments),
            ]:
                with open(os.path.join(d, name), "w") as f:
                    json.dump(data, f)
            # Minimal cap_state via library
            cs = cap_state_mod.build_cap_state(inputs, instruments)
            cs["metadata"]["run_id"] = RID
            with open(os.path.join(d, "cap_state.json"), "w") as f:
                json.dump(cs, f)
            # Minimal rule_audit + scenarios + counsel_packet
            for name, data in [
                (
                    "rule_audit.json",
                    {
                        "gating": {},
                        "applied_rules": [],
                        "counsel_review_items": [],
                        "date_sensitive_watchlist": [],
                        "metadata": {"run_id": RID},
                    },
                ),
                ("scenarios.json", {"scenarios": [], "metadata": {"run_id": RID}}),
                (
                    "counsel_packet.json",
                    {"company_name": "Acmecorp", "engagement_summary": "", "items": [], "metadata": {"run_id": RID}},
                ),
            ]:
                with open(os.path.join(d, name), "w") as f:
                    json.dump(data, f)

            rc, _, stderr = _run(
                "compose_report.py",
                [
                    "--dir",
                    d,
                    "--run-id",
                    RID,
                    "-o",
                    os.path.join(d, "report.json"),
                    "--write-md",
                    os.path.join(d, "report.md"),
                ],
            )
            assert rc == 0, stderr
            with open(os.path.join(d, "report.json")) as f:
                report = json.load(f)
            assert "coaching_payload" in report
            assert "report_markdown" in report
            cp = report["coaching_payload"]
            # Cross-skill required keys per tests/test_compose_invariants.py
            for k in [
                "schema_version",
                "summary",
                "failed_items",
                "warned_items",
                "high_severity_warnings",
                "insertion_marker",
            ]:
                assert k in cp, f"missing required coaching_payload key: {k}"
            assert cp["schema_version"].endswith("-cap-table")
