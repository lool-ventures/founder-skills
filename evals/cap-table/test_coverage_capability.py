"""Capability-canary CI check: a `full` primitive must actually emit its capability,
not merely name an existing producer file. See design spec §3.1 (R4-C1)."""

from __future__ import annotations

import json
import math
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import cap_state as cap_state_mod  # noqa: E402
import priced_round  # noqa: E402
from compose_report import compute_reconciliation_status  # noqa: E402


def _registry() -> dict:
    with open(os.path.join(_REPO, "founder-skills", "skills", "cap-table", "references", "coverage.json")) as f:
        return json.load(f)


def test_acquisition_capability_token_actually_emits() -> None:
    reg = _registry()
    acq = reg["primitives"]["acquisition_consideration"]
    assert acq.get("capability_token") == "acquisition_consideration_v1"
    # Canary: a producer that merely existed would NOT produce an acquisition_pct bucket.
    inputs = {
        "company_name": "Acmecorp",
        "analysis_date": "2026-01-01",
        "mode": "standard",
        "founders": [{"founder_id": "f1", "name": "Founder", "common_shares": 8_000_000}],
        "preferred_series": [],
        "option_pool": {"issued_and_outstanding": 0, "available_for_grant": 0},
        "metadata": {"run_id": "R1", "schema_version": "v0.5.0-inputs"},
    }
    instruments = {
        "safes": [],
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": "R1", "schema_version": "v0.5.0-instruments"},
    }
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    r = priced_round.solve_priced_round(
        cap_state=cs,
        safes=[],
        notes=[],
        pre_money=10_000_000,
        new_money=2_000_000,
        pre_money_basis="excludes_safe_conversion",
        acquisition={"consideration_pct": 0.2},
    )
    assert "acquisition_pct" in r["aggregate_ownership_by_class"], "capability declared full but not emitted"
    assert math.isclose(r["aggregate_ownership_by_class"]["acquisition_pct"], 0.2, abs_tol=1e-4)


def _fixture_solve():
    inputs = {
        "company_name": "Acmecorp",
        "analysis_date": "2026-01-01",
        "mode": "standard",
        "founders": [{"founder_id": "f1", "name": "Founder", "common_shares": 8_000_000}],
        "preferred_series": [],
        "option_pool": {"issued_and_outstanding": 0, "available_for_grant": 0},
        "metadata": {"run_id": "R1", "schema_version": "v0.5.0-inputs"},
    }
    instruments = {
        "safes": [],
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": "R1", "schema_version": "v0.5.0-instruments"},
    }
    cs = cap_state_mod.build_cap_state(inputs, instruments)
    return priced_round.solve_priced_round(
        cap_state=cs,
        safes=[],
        notes=[],
        pre_money=10_000_000,
        new_money=2_000_000,
        pre_money_basis="excludes_safe_conversion",
        acquisition={"consideration_pct": 0.2},
    )


def _recompute_matches(stored_pps: float, fresh_pps: float, tol_ppm: float = 1000.0) -> bool:
    if fresh_pps == 0:
        return stored_pps == 0
    return abs(stored_pps - fresh_pps) / abs(fresh_pps) * 1_000_000.0 <= tol_ppm


def test_recompute_is_deterministic() -> None:
    a, b = _fixture_solve(), _fixture_solve()
    assert math.isclose(a["equity_financing_price"], b["equity_financing_price"], rel_tol=1e-9)


def test_recompute_gate_passes_matching_report() -> None:
    fresh = _fixture_solve()["equity_financing_price"]
    assert _recompute_matches(fresh, fresh) is True


def test_recompute_gate_fails_tampered_report() -> None:
    fresh = _fixture_solve()["equity_financing_price"]
    tampered = fresh * 1.10  # someone hand-edited report.json
    assert _recompute_matches(tampered, fresh) is False


def test_no_stated_terms_degrades_to_not_applicable() -> None:
    # A report with no source-stated terms cannot be reconciled → existence-only, not a false fail.
    status, ppm = compute_reconciliation_status(computed={"pps": 1.23}, stated=None)
    assert status == "not_applicable"
    assert ppm == 0.0
