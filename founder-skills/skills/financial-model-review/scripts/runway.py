#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Multi-scenario runway stress-test for financial model review.

Projects monthly cash balance forward under base/slow/crisis scenarios.
Computes decision points, default-alive analysis, and risk assessment.

Usage:
    echo '{"company": {...}, "cash": {...}, ...}' | python runway.py --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


# ---------------------------------------------------------------------------
# Safe accessor
# ---------------------------------------------------------------------------


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _add_months(base_date: str, months: int) -> str:
    """Add months to a YYYY-MM date string, returning YYYY-MM."""
    year, month = map(int, base_date.split("-")[:2])
    total = year * 12 + (month - 1) + months
    new_year = total // 12
    new_month = total % 12 + 1
    return f"{new_year:04d}-{new_month:02d}"


# ---------------------------------------------------------------------------
# Scenario generation
# ---------------------------------------------------------------------------


def _build_scenarios(
    inputs: dict[str, Any],
    base_growth_rate: float,
    *,
    has_fx_exposure: bool = False,
) -> list[dict[str, Any]]:
    """Build scenario list from inputs or auto-generate defaults."""
    user_scenarios = inputs.get("scenarios")

    scenarios: list[dict[str, Any]] = []

    if user_scenarios and isinstance(user_scenarios, dict):
        # User provided scenarios as a dict of name -> params
        for name, params in user_scenarios.items():
            scenarios.append(
                {
                    "name": name,
                    "growth_rate": params.get("growth_rate", base_growth_rate),
                    "burn_change": params.get("burn_change", 0.0),
                    "fx_adjustment": params.get("fx_adjustment", 0.0),
                }
            )
        # Ensure base is present
        names = {s["name"] for s in scenarios}
        if "base" not in names:
            scenarios.insert(
                0,
                {
                    "name": "base",
                    "growth_rate": base_growth_rate,
                    "burn_change": 0.0,
                    "fx_adjustment": 0.0,
                },
            )
    else:
        # Auto-generate base, slow, crisis
        scenarios = [
            {
                "name": "base",
                "growth_rate": base_growth_rate,
                "burn_change": 0.0,
                "fx_adjustment": 0.0,
            },
            {
                "name": "slow",
                "growth_rate": base_growth_rate / 2,
                "burn_change": 0.10,
                "fx_adjustment": 0.05 if has_fx_exposure else 0.0,
            },
            {
                "name": "crisis",
                "growth_rate": 0.0,
                "burn_change": 0.20,
                "fx_adjustment": 0.10 if has_fx_exposure else 0.0,
            },
        ]

    return scenarios


# ---------------------------------------------------------------------------
# Projection engine
# ---------------------------------------------------------------------------

_MAX_MONTHS = 60
_GROWTH_DECAY = 0.97  # 3% monthly decay


def _project_scenario(
    scenario: dict[str, Any],
    cash0: float,
    revenue0: float,
    opex0: float,
    balance_date: str,
    *,
    grant_monthly: float = 0.0,
    grant_start_month: int = 1,
    grant_end_month: int = 0,
    ils_expense_fraction: float = 0.0,
) -> dict[str, Any]:
    """Run monthly projection for a single scenario.

    Returns the scenario result dict with runway_months, cash_out_date,
    decision_point, default_alive, and monthly_projections.
    """
    growth_rate = scenario["growth_rate"]
    burn_change = scenario["burn_change"]
    fx_adjustment = scenario.get("fx_adjustment", 0.0)
    name = scenario["name"]

    projections: list[dict[str, Any]] = []
    cash = cash0
    revenue = revenue0
    opex = opex0 * (1 + burn_change)  # one-time step-up at scenario start
    cash_out_month: int | None = None
    default_alive = False
    became_profitable = False

    for t in range(1, _MAX_MONTHS + 1):
        effective_growth = growth_rate * (_GROWTH_DECAY ** (t - 1))
        revenue = revenue * (1 + effective_growth)

        # FX adjustment on ILS-denominated expenses
        if ils_expense_fraction > 0 and fx_adjustment != 0:
            effective_opex = opex * (1 - ils_expense_fraction) + opex * ils_expense_fraction * (1 + fx_adjustment)
        else:
            effective_opex = opex

        net_burn = effective_opex - revenue

        # IIA grant disbursement
        grant = 0.0
        if grant_monthly > 0 and grant_start_month <= t <= grant_end_month:
            grant = grant_monthly

        cash = cash - net_burn + grant

        projections.append(
            {
                "month": t,
                "cash_balance": round(cash, 2),
                "revenue": round(revenue, 2),
                "expenses": round(effective_opex, 2),
                "net_burn": round(net_burn, 2),
            }
        )

        # Check if company becomes cash-flow positive (revenue >= expenses)
        if net_burn <= 0 and not became_profitable:
            became_profitable = True
        if net_burn <= 0 and not default_alive:
            default_alive = True

        if cash <= 0 and cash_out_month is None:
            cash_out_month = t
            break

    # If we never ran out of cash, the company is default alive
    if cash_out_month is None:
        default_alive = True

    # Sanity check: if initial net_burn was positive (company burning cash) but
    # final cash > starting cash AND the company never reached operational
    # profitability (revenue >= expenses), inputs are inconsistent — flag it.
    # Skip when became_profitable is True because growth-driven profitability
    # legitimately causes cash accumulation.  Note: we intentionally do NOT
    # use default_alive here — default_alive is also set when cash never runs
    # out (e.g., due to grant inflows), which doesn't indicate profitability.
    initial_net_burn = opex0 * (1 + burn_change) - revenue0
    cash_direction_warning: str | None = None
    if initial_net_burn > 0 and not became_profitable and len(projections) > 0:
        final_cash = projections[-1]["cash_balance"]
        if final_cash > cash0 * 1.01:  # allow 1% rounding tolerance
            cash_direction_warning = (
                f"Cash increased from {cash0:,.0f} to {final_cash:,.0f} despite "
                f"initial net burn of {initial_net_burn:,.0f}/mo — inputs may be inconsistent"
            )

    # Compute dates
    runway_months = cash_out_month
    cash_out_date: str | None = None
    decision_point: str | None = None

    if runway_months is not None:
        cash_out_date = _add_months(balance_date, runway_months)
        # Decision point = 12 months before cash-out (fundraising lead time)
        dp_months = max(runway_months - 12, 0)
        decision_point = _add_months(balance_date, dp_months)
    else:
        # Never runs out within projection window
        decision_point = None

    result: dict[str, Any] = {
        "name": name,
        "growth_rate": growth_rate,
        "burn_change": burn_change,
        "fx_adjustment": fx_adjustment,
        "runway_months": runway_months,
        "cash_out_date": cash_out_date,
        "decision_point": decision_point,
        "default_alive": default_alive,
        "became_profitable": became_profitable,
        "monthly_projections": projections,
    }
    if cash_direction_warning:
        result["cash_direction_warning"] = cash_direction_warning
    return result


# ---------------------------------------------------------------------------
# Minimum viable growth binary search
# ---------------------------------------------------------------------------


def _find_minimum_viable_growth(
    cash0: float,
    revenue0: float,
    opex0: float,
    balance_date: str,
    base_growth_rate: float,
    *,
    grant_monthly: float = 0.0,
    grant_start_month: int = 1,
    grant_end_month: int = 0,
    ils_expense_fraction: float = 0.0,
    target_runway: int = 18,
) -> dict[str, Any]:
    """Binary search for the minimum growth rate that achieves target_runway months or default-alive."""
    lo = 0.0
    hi = max(base_growth_rate, 0.01)  # floor at 1% to avoid stuck-at-zero when base is 0%
    precision = 0.001  # 0.1% MoM

    # With growth decay, the needed initial rate may exceed base_growth_rate.
    # Expand upper bound adaptively until viable or cap at 50% MoM.
    max_hi = 0.50
    while hi < max_hi:
        probe: dict[str, Any] = {
            "name": "_probe",
            "growth_rate": hi,
            "burn_change": 0.0,
            "fx_adjustment": 0.0,
        }
        probe_result = _project_scenario(
            probe,
            cash0,
            revenue0,
            opex0,
            balance_date,
            grant_monthly=grant_monthly,
            grant_start_month=grant_start_month,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_expense_fraction,
        )
        if probe_result["default_alive"] or (
            probe_result["runway_months"] is not None and probe_result["runway_months"] >= target_runway
        ):
            break
        hi = min(hi * 2, max_hi)

    # After adaptive expansion: if even max_hi is not viable, report failure
    if hi >= max_hi:
        cap_probe: dict[str, Any] = {
            "name": "_probe",
            "growth_rate": max_hi,
            "burn_change": 0.0,
            "fx_adjustment": 0.0,
        }
        cap_result = _project_scenario(
            cap_probe,
            cash0,
            revenue0,
            opex0,
            balance_date,
            grant_monthly=grant_monthly,
            grant_start_month=grant_start_month,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_expense_fraction,
        )
        if not cap_result["default_alive"] and (
            cap_result["runway_months"] is not None and cap_result["runway_months"] < target_runway
        ):
            return {
                "name": "threshold",
                "label": "Minimum viable growth",
                "growth_rate": None,
                "burn_change": 0.0,
                "fx_adjustment": 0.0,
                "runway_months": cap_result["runway_months"],
                "cash_out_date": cap_result.get("cash_out_date"),
                "decision_point": cap_result.get("decision_point"),
                "default_alive": False,
                "monthly_projections": [],
                "note": (f"Even {max_hi:.0%} MoM growth (with decay) does not achieve {target_runway}-month runway"),
            }

    # Binary search between 0% and upper bound
    for _ in range(50):
        if hi - lo < precision:
            break
        mid = (lo + hi) / 2
        mid_probe: dict[str, Any] = {
            "name": "_probe",
            "growth_rate": mid,
            "burn_change": 0.0,
            "fx_adjustment": 0.0,
        }
        result = _project_scenario(
            mid_probe,
            cash0,
            revenue0,
            opex0,
            balance_date,
            grant_monthly=grant_monthly,
            grant_start_month=grant_start_month,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_expense_fraction,
        )
        if result["default_alive"] or (
            result["runway_months"] is not None and result["runway_months"] >= target_runway
        ):
            hi = mid
        else:
            lo = mid

    # Run final scenario at the threshold rate
    final: dict[str, Any] = {
        "name": "threshold",
        "growth_rate": round(hi, 4),
        "burn_change": 0.0,
        "fx_adjustment": 0.0,
    }
    final_result = _project_scenario(
        final,
        cash0,
        revenue0,
        opex0,
        balance_date,
        grant_monthly=grant_monthly,
        grant_start_month=grant_start_month,
        grant_end_month=grant_end_month,
        ils_expense_fraction=ils_expense_fraction,
    )
    final_result["label"] = "Minimum viable growth"
    return final_result


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


def _assess_risk(scenario_results: list[dict[str, Any]]) -> str:
    """Generate a risk assessment string based on scenario outcomes."""
    if not scenario_results:
        return "Insufficient data for risk assessment."

    base = next((s for s in scenario_results if s["name"] == "base"), scenario_results[0])
    threshold = next((s for s in scenario_results if s["name"] == "threshold"), None)

    # Build threshold suffix
    threshold_suffix = ""
    if threshold and threshold.get("growth_rate") is not None:
        threshold_suffix = f" You need at least {threshold['growth_rate']:.1%} MoM growth to stay default-alive."

    if base["default_alive"]:
        if base.get("became_profitable"):
            base_text = "Low risk: company reaches profitability under base scenario before running out of cash."
        else:
            base_text = (
                "Low risk: company does not run out of cash under base scenario "
                "within projection window, though operational profitability is not reached."
            )
        return base_text + threshold_suffix

    runway = base.get("runway_months")
    if runway is not None:
        if runway >= 24:
            base_text = (
                f"Moderate risk: {runway} months of runway under base scenario. "
                f"Adequate time for fundraising but not yet default alive."
            )
        elif runway >= 12:
            base_text = (
                f"Elevated risk: {runway} months of runway under base scenario. Fundraising should begin immediately."
            )
        else:
            base_text = (
                f"Critical risk: only {runway} months of runway under base scenario. "
                f"Immediate action required (cut burn, bridge financing, or emergency raise)."
            )
        return base_text + threshold_suffix

    return "Unable to determine risk level from available data."


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def _compute_runway(inputs: dict[str, Any]) -> dict[str, Any]:
    """Compute multi-scenario runway analysis from structured inputs."""
    company = inputs.get("company", {})
    data_confidence = company.get("data_confidence", "exact")
    cash_data = inputs.get("cash", {})
    revenue_data = inputs.get("revenue", {})
    warnings: list[str] = []
    limitations: list[str] = []

    # --- Check for sufficient data ---
    current_balance = cash_data.get("current_balance")
    monthly_net_burn = cash_data.get("monthly_net_burn")

    if current_balance is None and monthly_net_burn is None:
        # Both missing — no analysis possible
        warnings.append("Cash balance and monthly burn data both missing; cannot compute runway.")
        return {
            "company": {
                "name": company.get("company_name", "Unknown"),
                "slug": company.get("slug", ""),
                "stage": company.get("stage", ""),
            },
            "baseline": None,
            "scenarios": [],
            "post_raise": None,
            "risk_assessment": "Insufficient data for runway analysis.",
            "insufficient_data": True,
            "limitations": limitations,
            "warnings": warnings,
        }

    if current_balance is None and monthly_net_burn is not None:
        # Burn known but no cash balance — produce sensitivity table
        burn = abs(monthly_net_burn)
        warnings.append(
            "Missing: cash.current_balance — producing burn-based sensitivity "
            "table instead of full projection. Ask the founder for current cash balance."
        )
        cash_scenarios = [500_000, 1_000_000, 2_000_000, 3_000_000, 5_000_000]
        sensitivity: list[dict[str, Any]] = []
        for starting_cash in cash_scenarios:
            months = round(starting_cash / burn, 1) if burn > 0 else None
            sensitivity.append(
                {
                    "starting_cash": starting_cash,
                    "runway_months": months,
                }
            )
        return {
            "company": {
                "name": company.get("company_name", "Unknown"),
                "slug": company.get("slug", ""),
                "stage": company.get("stage", ""),
            },
            "baseline": {
                "net_cash": None,
                "monthly_burn": burn,
                "monthly_revenue": None,
            },
            "scenarios": [],
            "post_raise": None,
            "risk_assessment": f"Monthly burn is ${burn:,.0f}. Cash balance unknown — ask founder.",
            "insufficient_data": True,
            "partial_analysis": True,
            "burn_sensitivity": sensitivity,
            "limitations": limitations,
            "warnings": warnings,
        }

    if monthly_net_burn is None:
        # Cash balance known but burn unknown
        warnings.append("Missing: cash.monthly_net_burn — cannot project runway without burn rate.")
        return {
            "company": {
                "name": company.get("company_name", "Unknown"),
                "slug": company.get("slug", ""),
                "stage": company.get("stage", ""),
            },
            "baseline": {
                "net_cash": current_balance,
                "monthly_burn": None,
                "monthly_revenue": None,
            },
            "scenarios": [],
            "post_raise": None,
            "risk_assessment": f"Cash balance is ${current_balance:,.0f} but burn rate unknown.",
            "insufficient_data": True,
            "limitations": limitations,
            "warnings": warnings,
        }

    # --- Derive baselines ---
    debt = cash_data.get("debt", 0)
    cash0 = current_balance - debt

    # Revenue
    mrr_value = _deep_get(revenue_data, "mrr", "value")
    arr_value = _deep_get(revenue_data, "arr", "value")
    monthly_total = revenue_data.get("monthly_total")
    if mrr_value is not None:
        revenue0 = mrr_value
    elif arr_value is not None:
        revenue0 = arr_value / 12
        print(
            f"Warning: using ARR/12 (${revenue0:,.0f}) as MRR proxy — revenue.mrr.value not provided",
            file=sys.stderr,
        )
        warnings.append(f"Using ARR/12 (${revenue0:,.0f}) as MRR proxy (no MRR provided).")
    elif monthly_total is not None:
        revenue0 = monthly_total
        warnings.append("Using revenue.monthly_total (no MRR provided).")
    else:
        revenue0 = 0.0
        warnings.append("No revenue data found; assuming $0 monthly revenue.")

    # OpEx: back-solve from net_burn = opex - revenue => opex = revenue + net_burn
    opex0 = revenue0 + monthly_net_burn

    # Validate at t=0
    check_burn = opex0 - revenue0
    if abs(check_burn - monthly_net_burn) > 0.01:
        warnings.append(
            f"Internal check: computed burn ({check_burn:.2f}) does not match "
            f"monthly_net_burn ({monthly_net_burn:.2f})."
        )

    if monthly_net_burn < 0:
        warnings.append(
            f"Monthly net burn is negative (${monthly_net_burn:,.0f}), indicating the company is cash-flow positive."
        )

    # Balance date
    balance_date = cash_data.get("balance_date", datetime.now().strftime("%Y-%m"))

    # Growth rate
    growth_rate = revenue_data.get("growth_rate_monthly", 0.0)
    if growth_rate is None:
        growth_rate = 0.0
        warnings.append("No growth rate provided; defaulting to 0%.")

    # --- IIA grant disbursement ---
    grants = cash_data.get("grants", {})
    iia_approved = grants.get("iia_approved", 0) or 0
    iia_disburse_months = grants.get("iia_disbursement_months", 12)
    iia_start = grants.get("iia_start_month", 1)
    if iia_approved > 0 and iia_disburse_months > 0:
        grant_monthly = iia_approved / iia_disburse_months
        grant_end_month = iia_start + iia_disburse_months - 1
    else:
        grant_monthly = 0.0
        grant_end_month = 0

    # --- FX exposure ---
    israel = inputs.get("israel_specific", {})
    fx_rate = israel.get("fx_rate_ils_usd")
    ils_fraction = israel.get("ils_expense_fraction", 0.5) if fx_rate is not None else 0.0
    has_fx = fx_rate is not None

    # --- Build & run scenarios ---
    scenarios = _build_scenarios(inputs, growth_rate, has_fx_exposure=has_fx)
    scenario_results: list[dict[str, Any]] = []

    for scenario in scenarios:
        scenario_out = _project_scenario(
            scenario,
            cash0,
            revenue0,
            opex0,
            balance_date,
            grant_monthly=grant_monthly,
            grant_start_month=iia_start,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_fraction,
        )
        scenario_results.append(scenario_out)
        # Surface per-scenario cash direction warnings
        if scenario_out.get("cash_direction_warning"):
            warnings.append(f"Scenario '{scenario_out['name']}': {scenario_out['cash_direction_warning']}")

    # --- Compute minimum viable growth threshold ---
    if growth_rate >= 0:
        threshold = _find_minimum_viable_growth(
            cash0,
            revenue0,
            opex0,
            balance_date,
            growth_rate,
            grant_monthly=grant_monthly,
            grant_start_month=iia_start,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_fraction,
        )
        scenario_results.append(threshold)

    # --- Risk assessment ---
    risk_assessment = _assess_risk(scenario_results)

    # --- Post-raise computation ---
    fundraising = cash_data.get("fundraising", {})
    target_raise = fundraising.get("target_raise")
    bridge = inputs.get("bridge", {})
    runway_target = bridge.get("runway_target_months", 24)
    post_raise: dict[str, Any] | None = None

    if target_raise is not None and target_raise > 0:
        base_scenario = next((s for s in scenarios if s["name"] == "base"), scenarios[0])
        new_cash = cash0 + target_raise
        pr_result = _project_scenario(
            base_scenario,
            new_cash,
            revenue0,
            opex0,
            balance_date,
            grant_monthly=grant_monthly,
            grant_start_month=iia_start,
            grant_end_month=grant_end_month,
            ils_expense_fraction=ils_fraction,
        )
        post_raise = {
            "raise_amount": target_raise,
            "new_cash": round(new_cash, 2),
            "new_runway_months": pr_result["runway_months"],
            "new_cash_out_date": pr_result["cash_out_date"],
            "meets_target": (pr_result["runway_months"] is None or pr_result["runway_months"] >= runway_target),
        }

    # --- Standard limitations ---
    limitations.extend(
        [
            "Growth rate decays 3% per month (compounding deceleration); burn rate is constant (no seasonality).",
            "Does not account for one-time events (fundraise closings, large contracts, etc.).",
            "Tax obligations and working capital timing not modeled.",
        ]
    )
    if iia_approved > 0:
        limitations.append(
            f"IIA grant of ${iia_approved:,.0f} disbursed evenly over {iia_disburse_months} months "
            f"starting month {iia_start}."
        )
    if has_fx:
        limitations.append(f"FX adjustment applied to {ils_fraction:.0%} of expenses (ILS-denominated).")

    result: dict[str, Any] = {
        "company": {
            "name": company.get("company_name", "Unknown"),
            "slug": company.get("slug", ""),
            "stage": company.get("stage", ""),
        },
        "baseline": {
            "net_cash": round(cash0, 2),
            "monthly_burn": monthly_net_burn,
            "monthly_revenue": revenue0,
        },
        "scenarios": scenario_results,
        "post_raise": post_raise,
        "risk_assessment": risk_assessment,
        "limitations": limitations,
        "warnings": warnings,
    }
    if data_confidence != "exact":
        result["data_confidence"] = data_confidence
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-scenario runway stress-test (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"company\": {...}, ...}' | python runway.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON input must be an object", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None

    if "company" not in data:
        result: dict[str, Any] = {"validation": {"status": "invalid", "errors": ["Missing required key: 'company'"]}}
        _write_output(json.dumps(result, indent=indent) + "\n", args.output)
        return

    result = _compute_runway(data)
    # Propagate run_id from inputs metadata into output for stale-artifact detection
    _input_metadata = data.get("metadata")
    if isinstance(_input_metadata, dict) and isinstance(_input_metadata.get("run_id"), str):
        result.setdefault("metadata", {})["run_id"] = _input_metadata["run_id"]
    out = json.dumps(result, indent=indent) + "\n"
    scenarios = result.get("scenarios", [])
    base_s = next((s for s in scenarios if s["name"] == "base"), None)
    _write_output(
        out,
        args.output,
        summary={
            "scenarios": len(scenarios),
            "base_runway_months": base_s["runway_months"] if base_s else None,
        },
    )


if __name__ == "__main__":
    main()
