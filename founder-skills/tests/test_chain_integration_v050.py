"""Chain-integration fixtures (v0.5.0 contract §9.3).

These tests exercise the producer chain end-to-end (in-process, no SDK
spawning) covering the most-recently-bug-prone integration paths. They
catch the class of bugs that the in-process math goldens can't catch —
canonicalization drift, schema-version mismatch, mirror-drift, and the
v0.4.x → v0.5.0 hard-reject migration boundary.

Fixtures map to the v0.5.0 contract §9.3:
  1. Single SAFE → priced round (baseline)
  4. Warrants in FD + cash-exercise pre-round
  5. §102 grants + flip
  6. Cumulative-preferred rejection (E_DIVIDEND_FIELDS_REMOVED)
  7. `notes` → `convertible_notes` rename (E_DEPRECATED_KEY_NOTES)
  9. §102 canonicalization end-to-end
 10. Cumulative-dividend + AoA extraction (aoa_findings.dividend_provisions_present)
 11. Inputs has top-level `pay_to_play_detected` (v0.4.10 hotfix migration carve-out)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

# After the path manipulation above
import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402
import warrant_exercise  # type: ignore[import-not-found]  # noqa: E402
from _artifact_io import ArtifactIOError, load_cap_state, load_inputs  # type: ignore[import-not-found]  # noqa: E402


def _write(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _minimal_inputs(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "company_name": "TestCo",
        "analysis_date": "2026-05-22",
        "mode": "standard",
        "founders": [{"name": "Alice", "common_shares": 10_000_000}],
        "preferred_series": [],
        "option_pool": {"plan_type": "nso", "authorized": 1_000_000, "issued": 0, "unallocated": 1_000_000},
        "metadata": {"run_id": "test_chain", "schema_version": "v0.5.0-inputs"},
    }
    if extra:
        base.update(extra)
    return base


def _minimal_instruments(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "safes": [],
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": "test_chain", "schema_version": "v0.5.0-instruments"},
    }
    if extra:
        base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Fixture 1 — baseline: single SAFE produces a valid cap_state through the
# typed loader.
# ---------------------------------------------------------------------------


def test_chain_1_single_safe_baseline() -> None:
    inputs = _minimal_inputs()
    instruments = _minimal_instruments(
        {
            "safes": [
                {
                    "id": "safe_001",
                    "investor_name": "Acme Ventures",
                    "purchase_amount": 500_000,
                    "post_money_valuation_cap": 10_000_000,
                    "issuance_date": "2025-09-01",
                    "form": "yc_postmoney_cap",
                    "extraction_confidence": "high",
                }
            ]
        }
    )

    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        _write(ws / "inputs.json", inputs)
        _write(ws / "instruments.json", instruments)
        cs = cap_state_mod.build_cap_state(inputs, instruments)
        # cap_state.py runs invariants; build a stamped cap_state for load
        cs["metadata"]["schema_version"] = "v0.5.0-cap-state"
        cs["metadata"]["run_id"] = "test_chain"
        _write(ws / "cap_state.json", cs)

        loaded = load_cap_state(ws)
        assert loaded["as_converted_totals"]["fully_diluted_shares"] == 11_000_000
        assert loaded["outstanding_safes"][0]["mfn_status"] == "absent"


# ---------------------------------------------------------------------------
# Fixture 4 — warrants visible in FD + cash-exercise pre-round pump
# ---------------------------------------------------------------------------


def test_chain_4_warrants_in_fd_and_cash_exercise() -> None:
    inputs = _minimal_inputs()
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "investor_name": "Lender",
                    "shares_underlying": 100_000,
                    "exercise_price": 0.50,
                    "warrant_type": "common_stock",
                    "vested_flag": True,
                    "issuance_date": "2024-06-01",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    # Vested warrants are included in FD per contract §6.1
    assert cs["as_converted_totals"]["warrants_underlying_total"] == 100_000
    assert cs["as_converted_totals"]["fully_diluted_shares"] == 10_000_000 + 1_000_000 + 100_000

    # Pump: warrant has no exercise_event_date, so pump doesn't fire
    post, events = warrant_exercise.run_pre_round_pump(cs, "2026-01-01")
    assert events == []

    # Now add an exercise_event_date and verify pump fires
    instruments["warrants"][0]["exercise_event_date"] = "2025-12-15"
    cs2 = cap_state_mod.build_cap_state(inputs, instruments)
    post, events = warrant_exercise.run_pre_round_pump(cs2, "2026-01-01")
    assert len(events) == 1
    assert events[0]["shares_added"] == 100_000  # cash_exercise
    assert events[0]["exercised_at_pps"] == 0.50  # strike
    assert post["as_converted_totals"]["common_shares"] == 10_000_000 + 100_000  # founder + new warrant shares
    # warrants_underlying_total shrinks
    assert post["as_converted_totals"]["warrants_underlying_total"] == 0


# ---------------------------------------------------------------------------
# Fixture 5 — §102 grants are visible end-to-end
# ---------------------------------------------------------------------------


def test_chain_5_section_102_grants_visible_end_to_end() -> None:
    inputs = _minimal_inputs(
        {
            "jurisdiction": {"structure": "delaware_with_israeli_sub"},
            "mode": "flip_focused",
        }
    )
    instruments = _minimal_instruments(
        {
            "option_grants": [
                {
                    "id": "grant_001",
                    "holder_id": "employee_1",
                    "grant_date": "2024-06-01",
                    "shares_granted": 100_000,
                    "shares_vested_to_date": 50_000,
                    "shares_exercised": 0,
                    "strike_price": 0.10,
                    "plan_type": "section_102_cg",
                    "section_102_trustee_deposit_date": "2024-06-15",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    # plan_type carried through to cap_state.outstanding_options per §3.2
    assert cs["outstanding_options"][0]["plan_type"] == "section_102_cg"
    assert cs["outstanding_options"][0]["section_102_trustee_deposit_date"] == "2024-06-15"


# ---------------------------------------------------------------------------
# Fixture 6 — cumulative-preferred dividend hard-reject (E_DIVIDEND_FIELDS_REMOVED)
# ---------------------------------------------------------------------------


def test_chain_6_dividend_fields_rejected() -> None:
    inputs = _minimal_inputs(
        {
            "preferred_series": [
                {
                    "series_name": "Series Seed",
                    "shares": 2_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "issuance_date": "2024-09-01",
                    "anti_dilution_protection": "none",
                    "dividend_rate_percent": 0.08,
                    "dividend_cumulative": True,
                }
            ]
        }
    )
    instruments = _minimal_instruments()
    with pytest.raises(cap_state_mod.CapStateInvariantError) as exc_info:
        cap_state_mod.build_cap_state(inputs, instruments)
    assert "E_DIVIDEND_FIELDS_REMOVED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Fixture 7 — notes → convertible_notes hard-reject (E_DEPRECATED_KEY_NOTES)
# ---------------------------------------------------------------------------


def test_chain_7_deprecated_notes_key_rejected_by_loader() -> None:
    # Write an instruments.json with the old `notes` key
    bad_instruments = {
        "safes": [],
        "notes": [
            {
                "id": "note_001",
                "investor_name": "X",
                "principal": 100_000,
                "interest_rate_type": "fixed_numeric",
                "issuance_date": "2024-09-01",
                "extraction_confidence": "high",
            }
        ],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": "test", "schema_version": "v0.5.0-instruments"},
    }
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        _write(ws / "instruments.json", bad_instruments)
        # Note: schema validation catches "notes" not being a known property
        # AFTER our typed loader's explicit check fires for the deprecated key.
        with pytest.raises(ArtifactIOError) as exc_info:
            from _artifact_io import load_instruments

            load_instruments(ws, validate_schema=False)
        assert exc_info.value.code == "E_DEPRECATED_KEY_NOTES"


# ---------------------------------------------------------------------------
# Fixture 11 — v0.4.10 pay_to_play_detected at top level is rewritten under
# aoa_findings (the one back-compat carve-out per §10.2)
# ---------------------------------------------------------------------------


def test_chain_11_pay_to_play_top_level_rewritten() -> None:
    legacy_inputs = _minimal_inputs(
        {
            "pay_to_play_detected": True,  # v0.4.10 hotfix shape — top-level
        }
    )
    # Note: not part of v0.5.0 schema; loader silently rewrites under aoa_findings
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        _write(ws / "inputs.json", legacy_inputs)
        # The schema validation will fail because pay_to_play_detected isn't a
        # documented top-level field, so disable strict schema validation. The
        # loader's `pay_to_play_detected` rewrite hook fires before the structural
        # check.
        loaded = load_inputs(ws, validate_schema=False)
        # Top-level key gone
        assert "pay_to_play_detected" not in loaded
        # Rewritten under aoa_findings
        assert loaded["aoa_findings"]["pay_to_play_detected"] is True


# ---------------------------------------------------------------------------
# Fixture: holder_election unspecified rejection (§4.5 invariant)
# ---------------------------------------------------------------------------


def test_chain_holder_election_unspecified_rejected() -> None:
    inputs = _minimal_inputs()
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 100_000,
                    "exercise_price": 0.50,
                    "warrant_type": "common_stock",
                    "vested_flag": True,
                    "issuance_date": "2024-06-01",
                    "settlement_type": "holder_election",
                    # holder_election_choice NOT set — invariant should reject
                }
            ]
        }
    )
    with pytest.raises(cap_state_mod.CapStateInvariantError) as exc_info:
        cap_state_mod.build_cap_state(inputs, instruments)
    assert "E_WARRANT_HOLDER_ELECTION_UNSPECIFIED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Fixture: mirror-drift detected by typed loader (§2.1 enforcement point)
# ---------------------------------------------------------------------------


def test_chain_mirror_drift_detected_on_load() -> None:
    inputs = _minimal_inputs()
    instruments = _minimal_instruments(
        {
            "option_grants": [
                {
                    "id": "grant_001",
                    "holder_id": "employee_1",
                    "grant_date": "2024-06-01",
                    "shares_granted": 100_000,
                    "strike_price": 0.10,
                    "plan_type": "iso",
                }
            ]
        }
    )
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        _write(ws / "inputs.json", inputs)
        _write(ws / "instruments.json", instruments)
        cs = cap_state_mod.build_cap_state(inputs, instruments)
        cs["metadata"]["schema_version"] = "v0.5.0-cap-state"
        cs["metadata"]["run_id"] = "test_chain"
        # Tamper: change plan_type in cap_state to disagree with instruments
        cs["outstanding_options"][0]["plan_type"] = "section_102_cg"
        _write(ws / "cap_state.json", cs)

        with pytest.raises(ArtifactIOError) as exc_info:
            load_cap_state(ws)
        assert exc_info.value.code == "E_MIRRORED_FIELD_DRIFT"


# ---------------------------------------------------------------------------
# Fixture: warrant pump idempotency (§6.1.5 property)
# ---------------------------------------------------------------------------


def test_chain_warrant_pump_idempotent() -> None:
    inputs = _minimal_inputs()
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 100_000,
                    "exercise_price": 0.50,
                    "warrant_type": "common_stock",
                    "vested_flag": True,
                    "issuance_date": "2024-06-01",
                    "exercise_event_date": "2025-12-15",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    post1, events1 = warrant_exercise.run_pre_round_pump(cs, "2026-01-01")
    assert len(events1) == 1
    # Re-run pump on post-pump cap_state — should be a no-op (warrant has
    # exercised_flag=True now)
    post2, events2 = warrant_exercise.run_pre_round_pump(post1, "2026-01-01")
    assert events2 == []
    assert post1["as_converted_totals"]["fully_diluted_shares"] == post2["as_converted_totals"]["fully_diluted_shares"]


# ---------------------------------------------------------------------------
# Post-pump FD-sum invariant (no double-count regression)
# ---------------------------------------------------------------------------


def test_chain_warrant_pump_fd_sum_invariant_holds() -> None:
    """Regression: after cash-exercise pump, fully_diluted_shares must equal
    sum(components). A delta-mutation approach produced 13.9M when components
    summed to 13.7M because the underlying was already counted in
    warrants_underlying_total before the pump."""
    inputs = _minimal_inputs(
        {
            "preferred_series": [
                {
                    "series_name": "Series Seed",
                    "shares": 2_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "issuance_date": "2024-09-01",
                    "anti_dilution_protection": "none",
                }
            ]
        }
    )
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 200_000,
                    "exercise_price": 0.50,
                    "warrant_type": "common_stock",
                    "vested_flag": True,
                    "issuance_date": "2024-12-01",
                    "exercise_event_date": "2026-04-15",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    # Pre-pump: 10M founder + 2M preferred + 1M pool + 200k warrants = 13.2M
    assert cs["as_converted_totals"]["fully_diluted_shares"] == 13_200_000
    post, events = warrant_exercise.run_pre_round_pump(cs, "2026-06-01")
    assert len(events) == 1
    t = post["as_converted_totals"]
    # Post-pump components: 10.2M common + 2M preferred + 0 + 1M pool + 0 warrants = 13.2M
    expected_components = (
        t["common_shares"]
        + t["preferred_shares_as_converted"]
        + t["options_outstanding"]
        + t["options_available"]
        + t["warrants_underlying_total"]
    )
    assert t["fully_diluted_shares"] == expected_components, (
        f"FD-sum invariant violated: stored FD {t['fully_diluted_shares']} != component sum {expected_components}"
    )
    # FD should be unchanged from pre-pump (200k moved from warrants to common, no net add)
    assert t["fully_diluted_shares"] == 13_200_000


def test_chain_preferred_stock_series_warrant_routes_to_series() -> None:
    """v0.5.0 contract Q1 / §4.5: a warrant_type=preferred_stock_series warrant
    must declare preferred_series_id. On exercise, shares enter that series's
    preferred_series[].shares (not a free-floating preferred bucket), and the
    as-converted scalar gets the OCP/CCP-ratio increment."""
    inputs = _minimal_inputs(
        {
            "preferred_series": [
                {
                    "series_id": "series_seed",
                    "series_name": "Series Seed",
                    "shares": 2_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "issuance_date": "2024-09-01",
                    "anti_dilution_protection": "broad_based_weighted_average",
                }
            ]
        }
    )
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 100_000,
                    "exercise_price": 1.00,
                    "warrant_type": "preferred_stock_series",
                    "preferred_series_id": "series_seed",
                    "vested_flag": True,
                    "issuance_date": "2024-12-01",
                    "exercise_event_date": "2026-04-15",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    post, events = warrant_exercise.run_pre_round_pump(cs, "2026-06-01")
    assert len(events) == 1
    # Series Seed shares grew from 2.0M → 2.1M (the warrant exercised into the series)
    series = next(s for s in post["preferred_series"] if s["series_id"] == "series_seed")
    assert series["shares"] == 2_100_000
    # FD-sum invariant still holds
    t = post["as_converted_totals"]
    expected_components = (
        t["common_shares"]
        + t["preferred_shares_as_converted"]
        + t["options_outstanding"]
        + t["options_available"]
        + t["warrants_underlying_total"]
    )
    assert t["fully_diluted_shares"] == expected_components


def test_chain_phase_f_cap_state_after_pump_embedded() -> None:
    """Phase F (v0.5.0): when the pre-round warrant pump fires, run_scenario
    embeds the post-pump delta under scenarios[i].computed_outputs.cap_state_after_pump
    so the §4.5 FD-sum invariant can trip on future regressions and downstream
    debugging is trivial."""
    import run_scenario  # type: ignore[import-not-found]

    inputs = _minimal_inputs(
        {
            "preferred_series": [
                {
                    "series_name": "Series Seed",
                    "shares": 2_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "issuance_date": "2024-09-01",
                    "anti_dilution_protection": "broad_based_weighted_average",
                }
            ]
        }
    )
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 200_000,
                    "exercise_price": 0.50,
                    "warrant_type": "common_stock",
                    "vested_flag": True,
                    "issuance_date": "2024-12-01",
                    "exercise_event_date": "2026-04-15",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    scenario = {
        "scenario_id": "round_a",
        "type": "priced_round",
        "parameters": {
            "pre_money": 15_000_000,
            "new_money": 5_000_000,
            "target_pool_percent": 0.10,
            "target_basis": "post_money",
            "transaction_event_date": "2026-06-01",
        },
    }
    result = run_scenario.run_priced_round_scenario(scenario, instruments=instruments, cap_state=cs)
    # Pump fired
    assert "warrant_exercise_events" in result
    assert len(result["warrant_exercise_events"]) == 1
    # Post-pump delta embedded
    assert "cap_state_after_pump" in result
    delta = result["cap_state_after_pump"]
    assert set(delta.keys()) >= {"as_converted_totals", "outstanding_warrants", "cap_table_history"}
    # FD-sum invariant holds in the embedded snapshot (no double-count)
    t = delta["as_converted_totals"]
    expected = (
        t["common_shares"]
        + t["preferred_shares_as_converted"]
        + t["options_outstanding"]
        + t["options_available"]
        + t["warrants_underlying_total"]
    )
    assert t["fully_diluted_shares"] == expected
    # Warrant marked exercised
    assert delta["outstanding_warrants"][0]["exercised_flag"] is True
    # cap_table_history extended
    assert any(h.get("event_type") == "warrant_exercised" for h in delta["cap_table_history"])


def test_chain_preferred_stock_series_warrant_without_series_id_rejected() -> None:
    """§4.5 invariant E_WARRANT_PREFERRED_SERIES_ID_REQUIRED: a preferred-series
    warrant with null preferred_series_id is rejected at canonicalization, so
    the pump never has to handle the case."""
    inputs = _minimal_inputs(
        {
            "preferred_series": [
                {
                    "series_name": "Series Seed",
                    "shares": 1_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "issuance_date": "2024-09-01",
                    "anti_dilution_protection": "none",
                }
            ]
        }
    )
    instruments = _minimal_instruments(
        {
            "warrants": [
                {
                    "id": "warrant_001",
                    "shares_underlying": 50_000,
                    "exercise_price": 1.00,
                    "warrant_type": "preferred_stock_series",
                    # preferred_series_id intentionally absent
                    "vested_flag": True,
                    "issuance_date": "2024-12-01",
                    "settlement_type": "cash_exercise",
                }
            ]
        }
    )
    with pytest.raises(cap_state_mod.CapStateInvariantError) as exc_info:
        cap_state_mod.build_cap_state(inputs, instruments)
    assert "E_WARRANT_PREFERRED_SERIES_ID_REQUIRED" in str(exc_info.value)
