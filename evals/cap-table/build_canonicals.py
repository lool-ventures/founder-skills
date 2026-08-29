#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Derive the reliability bench's computation-case canonical numbers from the
deterministic producers, instead of hand-typing them.

For each ``computation_case`` that has a reproducible recipe, this builds a
structured scenario in a temp dir, runs the real producers
(``cap_state.py`` -> ``rule_audit.py --phase=pre_math`` -> ``run_scenario.py``,
or ``anti_dilution.py`` directly for the closed-form anti-dilution cases),
extracts the canonical numeric values, and records them under a
``canonical_values`` key on that case in ``reliability-bench.json``.

The recipe logic lives in ``derive_canonicals()`` so the per-PR drift-guard
test can import it and re-derive the same numbers without duplicating recipes.

Default mode is dry-run: prints the derived values as JSON. ``--write``
records them into the bench in place, preserving every existing key on each
case untouched and only adding/replacing ``canonical_values``. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Bench lives at repo-root evals/cap-table/ (outside the distributed plugin); the cap-table producer
# scripts are under founder-skills/. parents[2] = repo root.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "founder-skills" / "skills" / "cap-table" / "scripts"
BENCH_PATH = Path(__file__).resolve().parent / "reliability-bench.json"

RUN_ID = "BENCH"

# ---------------------------------------------------------------------------
# Scenario building blocks
# ---------------------------------------------------------------------------

_FOUNDERS_10M = [{"name": "Founder A", "founder_id": "founder_a", "common_shares": 10000000}]


def _base_inputs(founders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A minimal-but-schema-valid Delaware inputs.json payload."""
    return {
        "company_name": "BenchCo",
        "analysis_date": "2026-06-22",
        "mode": "standard",
        "jurisdiction": {
            "structure": "delaware",
            "incorporated_date": "2024-06-01",
            "iia_grants_history": {"has_grants": False, "grant_details": []},
        },
        "event_dates": {
            "restructuring_effective_date": None,
            "restructuring_approval_date": None,
            "filing_date": None,
            "tax_position_date": None,
            "flip_closing_date": None,
            "benchmark_reference_date": None,
        },
        "founders": founders if founders is not None else _FOUNDERS_10M,
        "option_pool": {"plan_type": "iso", "authorized": 0, "issued": 0, "unallocated": 0},
        "engagement_questions": [],
        "metadata": {"run_id": RUN_ID, "schema_version": "v0.5.0-inputs"},
    }


def _base_instruments(safes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "safes": safes or [],
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": RUN_ID, "schema_version": "v0.5.0-instruments"},
    }


def _run(script: str, *args: str) -> None:
    """Run a producer script; raise on failure (producers emit JSON receipts)."""
    cmd = [sys.executable, str(SCRIPTS_DIR / script), *args]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _run_pipeline(
    tmp: Path,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    scenario_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """cap_state -> rule_audit --phase=pre_math -> run_scenario.

    Returns ``scenarios[0].computed_outputs`` from the produced scenarios.json.
    """
    inputs_p = tmp / "inputs.json"
    instruments_p = tmp / "instruments.json"
    scenarios_in_p = tmp / "scenario_requests.json"
    cap_state_p = tmp / "cap_state.json"
    rule_audit_p = tmp / "rule_audit.json"
    scenarios_p = tmp / "scenarios.json"

    inputs_p.write_text(json.dumps(inputs), encoding="utf-8")
    instruments_p.write_text(json.dumps(instruments), encoding="utf-8")
    scenarios_in_p.write_text(json.dumps(scenario_requests), encoding="utf-8")

    _run(
        "cap_state.py",
        "--inputs",
        str(inputs_p),
        "--instruments",
        str(instruments_p),
        "--run-id",
        RUN_ID,
        "-o",
        str(cap_state_p),
    )
    # rule_audit --scenarios expects a {"scenarios": [...]} object; the run_scenario
    # request file is a bare list. The pre_math gating block is not consumed by
    # run_scenario in this version, so wrap the requests for the audit step to keep
    # the documented pipeline order intact without crashing the audit.
    audit_scenarios_p = tmp / "rule_audit_scenarios.json"
    audit_scenarios_p.write_text(json.dumps({"scenarios": scenario_requests}), encoding="utf-8")
    _run(
        "rule_audit.py",
        "--phase=pre_math",
        "--inputs",
        str(inputs_p),
        "--instruments",
        str(instruments_p),
        "--cap-state",
        str(cap_state_p),
        "--scenarios",
        str(audit_scenarios_p),
        "--run-id",
        RUN_ID,
        "-o",
        str(rule_audit_p),
    )
    _run(
        "run_scenario.py",
        "--inputs",
        str(inputs_p),
        "--instruments",
        str(instruments_p),
        "--cap-state",
        str(cap_state_p),
        "--scenarios-input",
        str(scenarios_in_p),
        "--run-id",
        RUN_ID,
        "-o",
        str(scenarios_p),
    )
    data = json.loads(scenarios_p.read_text(encoding="utf-8"))
    return data["scenarios"][0]["computed_outputs"]  # type: ignore[no-any-return]


def _run_anti_dilution(subcommand: str, *args: str) -> dict[str, Any]:
    """Run anti_dilution.py and return its parsed JSON payload (stdout)."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "anti_dilution.py"), subcommand, *args]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


# ---------------------------------------------------------------------------
# Per-case recipes
# ---------------------------------------------------------------------------


def _derive_discount_only_iterative(tmp: Path) -> dict[str, Any]:
    inputs = _base_inputs()
    instruments = _base_instruments(
        [
            {
                "id": "safe_disc",
                "investor_name": "Disc Investor",
                "purchase_amount": 1000000,
                "post_money_valuation_cap": None,
                "discount_multiplier": 0.80,
                "form": "yc_postmoney_discount",
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            }
        ]
    )
    requests = [
        {
            "scenario_id": "a",
            "label": "Series A",
            "type": "priced_round",
            "parameters": {"pre_money": 10000000, "new_money": 4000000},
        }
    ]
    out = _run_pipeline(tmp, inputs, instruments, requests)
    agg = out["aggregate_ownership_by_class"]
    return {
        "equity_financing_price": _round(out["equity_financing_price"], 3),
        "safe_conversion_price": _round(out["per_safe"]["safe_disc"]["conversion_price"], 3),
        "safe_conversion_shares": round(out["per_safe"]["safe_disc"]["conversion_shares"]),
        "founders_pct": _round(agg["founders_pct"], 4),
        "safe_pct": _round(agg["safe_pct"], 4),
        "new_money_pct": _round(agg["new_money_pct"], 4),
    }


def _derive_stacked_safes(tmp: Path) -> dict[str, Any]:
    inputs = _base_inputs()
    instruments = _base_instruments(
        [
            {
                "id": "safe_5",
                "investor_name": "I5",
                "purchase_amount": 500000,
                "post_money_valuation_cap": 5000000,
                "discount_multiplier": None,
                "form": "yc_postmoney_cap",
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            },
            {
                "id": "safe_8",
                "investor_name": "I8",
                "purchase_amount": 750000,
                "post_money_valuation_cap": 8000000,
                "discount_multiplier": None,
                "form": "yc_postmoney_cap",
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            },
            {
                "id": "safe_6",
                "investor_name": "I6",
                "purchase_amount": 250000,
                "post_money_valuation_cap": 6000000,
                "discount_multiplier": None,
                "form": "yc_postmoney_cap",
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            },
        ]
    )
    requests = [{"scenario_id": "s", "label": "SAFE conversion", "type": "safe_conversion", "parameters": {}}]
    out = _run_pipeline(tmp, inputs, instruments, requests)
    per_safe = out["per_safe"]
    # safe_conversion yields per-SAFE cap-implied ownership; the canonical total is
    # the SUM of these (they stack), and founders retain the complement.
    fractions = {sid: _round(per_safe[sid]["cap_implied_ownership"]) for sid in per_safe}
    total_given = _round(sum(fractions.values()), 4)
    return {
        "per_safe_cap_implied_ownership": fractions,
        "total_given_away": total_given,
        "founders_retained": _round(1.0 - total_given, 4),
    }


def _derive_pool_shuffle(tmp: Path) -> dict[str, Any]:
    inputs = _base_inputs()
    instruments = _base_instruments([])
    requests = [
        {
            "scenario_id": "p",
            "label": "Series A pool",
            "type": "priced_round",
            "parameters": {
                "pre_money": 20000000,
                "new_money": 5000000,
                "target_pool_percent": 0.10,
                "target_basis": "post_money",
            },
        }
    ]
    out = _run_pipeline(tmp, inputs, instruments, requests)
    return {
        "price_per_share": _round(out["equity_financing_price"], 3),
        "pool_shares": round(out["shares_breakdown"]["pool_topup"]),
    }


def _derive_bbwa_downround(_tmp: Path) -> dict[str, Any]:
    # CP1 = 2.00; broad-based A = 8M common + 2M preferred (as-converted) + 1M pool = 11M;
    # consideration = $3M; C = shares issued in the down round at $1.00 = 3M.
    out = _run_anti_dilution(
        "bbwa",
        "--cp1",
        "2.00",
        "--A",
        "11000000",
        "--consideration",
        "3000000",
        "--new-price",
        "1.00",
        # C is derived (3,000,000 / 1.00), which is the value this used to pass explicitly via
        # --shares-C. The override is gone: a caller-supplied C can break B/C == new_price/CP1, the
        # identity that makes CP2 <= CP1 arithmetic rather than hopeful.
    )
    return {"cp2": _round(out["new_conversion_price"], 3)}


def _derive_full_ratchet(_tmp: Path) -> dict[str, Any]:
    out = _run_anti_dilution("full-ratchet", "--cp1", "2.00", "--new-price", "1.00")
    return {"cp2": _round(out["new_conversion_price"], 3)}


def _derive_mfn_circular(tmp: Path) -> dict[str, Any]:
    inputs = _base_inputs()
    instruments = _base_instruments(
        [
            {
                "id": "safe_x",
                "investor_name": "X",
                "purchase_amount": 500000,
                "post_money_valuation_cap": None,
                "discount_multiplier": None,
                "form": "yc_uncapped_mfn",
                "mfn_provision": {"has_mfn": True, "elected_against_safe_id": "safe_y"},
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            },
            {
                "id": "safe_y",
                "investor_name": "Y",
                "purchase_amount": 500000,
                "post_money_valuation_cap": None,
                "discount_multiplier": None,
                "form": "yc_uncapped_mfn",
                "mfn_provision": {"has_mfn": True, "elected_against_safe_id": "safe_x"},
                "issuance_date": "2025-06-01",
                "extraction_confidence": "high",
            },
        ]
    )
    requests = [{"scenario_id": "m", "label": "MFN circular", "type": "safe_conversion", "parameters": {}}]
    out = _run_pipeline(tmp, inputs, instruments, requests)
    blockers = out.get("blockers", [])
    codes = [b.get("code") for b in blockers]
    return {
        "raises_circular": "E_SAFE_CIRCULAR_MFN" in codes,
        "blocker_code": "E_SAFE_CIRCULAR_MFN",
        # The producer must NOT surface a numeric conversion price for the cycle.
        "has_conversion_price": any(v.get("conversion_price") is not None for v in out.get("per_safe", {}).values()),
    }


# case_id -> recipe function. Each takes a temp dir Path and returns the
# canonical_values dict recorded on that case.
RECIPES = {
    "comp_discount_only_iterative": _derive_discount_only_iterative,
    "comp_stacked_safes": _derive_stacked_safes,
    "comp_pool_shuffle": _derive_pool_shuffle,
    "comp_bbwa_downround": _derive_bbwa_downround,
    "comp_full_ratchet": _derive_full_ratchet,
    "comp_mfn_circular": _derive_mfn_circular,
}


def derive_canonicals() -> dict[str, dict[str, Any]]:
    """Run every recipe and return {case_id: canonical_values}.

    Importable by the drift-guard test so recipe logic is not duplicated.
    """
    results: dict[str, dict[str, Any]] = {}
    for case_id, recipe in RECIPES.items():
        with tempfile.TemporaryDirectory() as td:
            results[case_id] = recipe(Path(td))
    return results


# ---------------------------------------------------------------------------
# Bench write path
# ---------------------------------------------------------------------------


def write_bench(derived: dict[str, dict[str, Any]]) -> list[str]:
    """Record canonical_values onto matching computation_cases in the bench.

    Preserves every existing key on every case; only adds/replaces
    ``canonical_values``. Returns the list of case ids updated.
    """
    bench = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    updated: list[str] = []
    for case in bench.get("computation_cases", []):
        cid = case.get("id")
        if cid in derived:
            case["canonical_values"] = derived[cid]
            updated.append(cid)
    BENCH_PATH.write_text(json.dumps(bench, indent=2) + "\n", encoding="utf-8")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Record canonical_values into reliability-bench.json in place (default: dry-run).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    derived = derive_canonicals()

    if args.write:
        updated = write_bench(derived)
        receipt = {"ok": True, "path": str(BENCH_PATH), "updated_cases": updated}
        print(json.dumps(receipt, indent=2 if args.pretty else None))
    else:
        print(json.dumps(derived, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
