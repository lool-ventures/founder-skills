#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
IC simulation dimension scorer.

Scores 28 dimensions across 7 categories with conviction-based scoring.
A single dealbreaker forces hard_pass regardless of score.

Always reads JSON from stdin.

Usage:
    echo '{"items": [{"id": "team_founder_market_fit", "status": "strong_conviction", ...}, ...]}' \
        | python score_dimensions.py --pretty

Output: JSON with validated items and summary including verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn


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


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    """Emit a validation-error result and exit NON-ZERO, without touching `output_path`.

    Mirrors the helper in every other producer, for the same two reasons.

    The error JSON still goes to STDOUT so the caller can read the diagnostic; only the exit
    code and stderr are new. It is deliberately NOT written to `--output`, because that path is
    a canonical artifact: overwriting it with a figure-less stub destroys the prior good file
    AND reads as truth to `compose_report.py`.

    Exit 1 is what makes the failure reachable. Each SKILL.md's producer-error branch is written
    as "the pipe fails next" — with exit 0 and an `{{"ok":true}}` receipt, that branch could never
    fire, so a rejected run was indistinguishable from a successful one.
    """
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


# Canonical 28 dimensions grouped by category.
DIMENSION_ITEMS: list[dict[str, str]] = [
    # Team (4)
    {"id": "team_founder_market_fit", "category": "Team", "label": "Founder-Market Fit"},
    {"id": "team_complementary_skills", "category": "Team", "label": "Complementary Skills"},
    {"id": "team_execution_speed", "category": "Team", "label": "Execution Speed"},
    {"id": "team_coachability", "category": "Team", "label": "Coachability"},
    # Market (4)
    {"id": "market_size_credibility", "category": "Market", "label": "Size Credibility"},
    {"id": "market_timing", "category": "Market", "label": "Timing"},
    {"id": "market_growth_trajectory", "category": "Market", "label": "Growth Trajectory"},
    {"id": "market_entry_barriers", "category": "Market", "label": "Entry Barriers"},
    # Product (4)
    {"id": "product_differentiation", "category": "Product", "label": "Differentiation"},
    {"id": "product_traction_evidence", "category": "Product", "label": "Traction Evidence"},
    {"id": "product_technical_moat", "category": "Product", "label": "Technical Moat"},
    {"id": "product_user_love", "category": "Product", "label": "User Love"},
    # Business Model (4)
    {"id": "biz_unit_economics", "category": "Business Model", "label": "Unit Economics"},
    {"id": "biz_pricing_power", "category": "Business Model", "label": "Pricing Power"},
    {"id": "biz_scalability", "category": "Business Model", "label": "Scalability"},
    {"id": "biz_gross_margins", "category": "Business Model", "label": "Gross Margins"},
    # Financials (4)
    {"id": "fin_capital_efficiency", "category": "Financials", "label": "Capital Efficiency"},
    {"id": "fin_runway_plan", "category": "Financials", "label": "Runway Plan"},
    {"id": "fin_path_to_next_round", "category": "Financials", "label": "Path to Next Round"},
    {"id": "fin_revenue_quality", "category": "Financials", "label": "Revenue Quality"},
    # Risk (4)
    {"id": "risk_single_point_failure", "category": "Risk", "label": "Single Point of Failure"},
    {"id": "risk_regulatory", "category": "Risk", "label": "Regulatory Risk"},
    {"id": "risk_competitive_response", "category": "Risk", "label": "Competitive Response"},
    {"id": "risk_customer_concentration", "category": "Risk", "label": "Customer Concentration"},
    # Fund Fit (4)
    {"id": "fit_thesis_alignment", "category": "Fund Fit", "label": "Thesis Alignment"},
    {"id": "fit_portfolio_conflict", "category": "Fund Fit", "label": "Portfolio Conflict"},
    {"id": "fit_stage_match", "category": "Fund Fit", "label": "Stage Match"},
    {"id": "fit_value_add", "category": "Fund Fit", "label": "Value-Add Potential"},
]

VALID_IDS = {item["id"] for item in DIMENSION_ITEMS}
VALID_STATUSES = {
    "strong_conviction",
    "moderate_conviction",
    "concern",
    "dealbreaker",
    "not_applicable",
    # IC-11: the deck genuinely does not disclose the data to judge this dimension — UNKNOWN,
    # needs founder confirmation. NOT a negative judgment (that is `concern`) and NOT structurally
    # inapplicable (that is `not_applicable`). Excluded from the conviction denominator so honest
    # non-disclosure doesn't deflate the score; guarded by the coverage cap below so it can't
    # inflate it either.
    "to_confirm",
}

# Coverage guard: when more than this many dimensions are `to_confirm` (mirrors HIGH_NA_COUNT's
# >6), too much is unconfirmed to responsibly reach `invest` — cap the verdict at more_diligence.
# Structural `not_applicable` is NOT counted here (it's inapplicability, not a data gap).
HIGH_TO_CONFIRM_COUNT = 6

# Minimum applicable dimensions for a conviction PERCENTAGE to carry meaning. The
# 28 dimensions span 7 categories, so 8 is "more than one category's worth on
# average" — below that the percentage is arithmetic on a handful of points and its
# decimal place overstates the evidence. This gates PRESENTATION, never the score
# itself and never the verdict.
MIN_APPLICABLE_FOR_SCORE = 8
ITEM_LOOKUP = {item["id"]: item for item in DIMENSION_ITEMS}

# The Fund Fit dimensions (thesis/portfolio/stage/value-add) are the ones whose
# evidence derives from the FUND PROFILE. In generic mode that profile is a
# synthesized/illustrative persona (invented portfolio, check size, thesis), so a
# dealbreaker on one of these is "simulated" and must NOT override the merits-based
# verdict. Every other category is STARTUP-side evidence and always blocks.
FUND_FIT_CATEGORY = "Fund Fit"


def validate_dimensions(items: list[dict[str, Any]], fund_mode: str = "fund_specific") -> dict[str, Any]:
    """Validate dimension input and produce scored summary.

    fund_mode: "fund_specific" (default, back-compat) or "generic". In generic
    mode the fund profile is a synthesized/illustrative persona, not a real
    fund's actual holdings — a dealbreaker sourced from a fabricated portfolio
    conflict must not override the merits-based verdict. In fund_specific mode
    (a real, named fund) a dealbreaker always forces hard_pass, unchanged.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"Item {idx} must be an object (got {type(item).__name__})")
            continue
        item_id = item.get("id", "")
        if item_id not in VALID_IDS:
            errors.append(f"Unknown dimension ID '{item_id}'")
        if item_id in seen_ids:
            errors.append(f"Duplicate dimension ID '{item_id}'")
        seen_ids.add(item_id)

        status = item.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"Invalid status '{status}' for '{item_id}'")

    missing = VALID_IDS - seen_ids
    if missing:
        errors.append(f"Missing dimensions: {sorted(missing)}")

    if errors:
        return {"items": [], "summary": {}, "validation": {"status": "invalid", "errors": errors}}

    # Build enriched items and summary
    enriched: list[dict[str, Any]] = []
    strong_count = 0
    moderate_count = 0
    concern_count = 0
    dealbreaker_count = 0
    na_count = 0
    to_confirm_count = 0
    dealbreakers: list[dict[str, Any]] = []
    top_concerns: list[dict[str, Any]] = []

    # Per-category tracking
    categories: dict[str, dict[str, int]] = {}

    for item in items:
        item_id = item["id"]
        meta = ITEM_LOOKUP[item_id]
        status = item["status"]
        evidence = item.get("evidence")
        notes = item.get("notes")
        category = meta["category"]

        enriched.append(
            {
                "id": item_id,
                "category": category,
                "label": meta["label"],
                "status": status,
                "evidence": evidence,
                "notes": notes,
            }
        )

        # Initialize category counters
        if category not in categories:
            categories[category] = {
                "strong_conviction": 0,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
                "to_confirm": 0,
            }

        categories[category][status] += 1

        if status == "strong_conviction":
            strong_count += 1
        elif status == "moderate_conviction":
            moderate_count += 1
        elif status == "concern":
            concern_count += 1
            top_concerns.append(
                {
                    "id": item_id,
                    "category": category,
                    "label": meta["label"],
                    "evidence": evidence,
                    "notes": notes,
                }
            )
        elif status == "dealbreaker":
            dealbreaker_count += 1
            dealbreakers.append(
                {
                    "id": item_id,
                    "category": category,
                    "label": meta["label"],
                    "evidence": evidence,
                    "notes": notes,
                }
            )
        elif status == "not_applicable":
            na_count += 1
        elif status == "to_confirm":
            to_confirm_count += 1

    # to_confirm is excluded from the denominator (like not_applicable) so honest non-disclosure
    # neither earns credit nor deflates the score.
    applicable = len(DIMENSION_ITEMS) - na_count - to_confirm_count
    warnings: list[str] = []

    # Conviction score: (strong*1.0 + moderate*0.5) / applicable * 100
    if applicable > 0:
        conviction_score = round((strong_count * 1.0 + moderate_count * 0.5) / applicable * 100, 1)
    else:
        conviction_score = 0.0
        warnings.append("ZERO_APPLICABLE_DIMENSIONS")

    # Basis guard — MISLEADING PRECISION, which the verdict cap and floor do not
    # address. Those guard the verdict; this guards the SCORE. One strong dimension
    # out of two applicable is "50.0%", and a founder reads that as a considered
    # midpoint arrived at across the whole framework rather than a coin-flip over
    # two data points. The decimal place is the problem: it implies more evidence
    # than exists.
    #
    # The score is still reported unchanged (transparency), and the verdict is
    # untouched — a thin base is not itself a reason to move a verdict. What changes
    # is that the score must never be presented without its denominator.
    conviction_basis = {
        "applicable": applicable,
        "total": len(DIMENSION_ITEMS),
        "sufficient": applicable >= MIN_APPLICABLE_FOR_SCORE,
    }
    if 0 < applicable < MIN_APPLICABLE_FOR_SCORE:
        warnings.append("LOW_CONVICTION_BASIS")

    # Verdict determination — SOURCE-BASED dealbreaker capping (WB-2).
    # A dealbreaker forces hard_pass UNLESS it is "simulated": in generic mode a
    # dealbreaker on a FUND FIT dimension derives from the synthesized fund persona
    # (invented portfolio/check-size/thesis), not real fund data, so it must not
    # override the merits-based verdict. STARTUP-side dealbreakers (Team, Market,
    # Product, Business Model, Financials, Risk) always block, in EVERY mode — a real
    # fatal flaw (zero traction, no unit economics) is a real decline. In
    # fund_specific mode the fund is real, so Fund Fit dealbreakers block too.
    if fund_mode == "generic":
        simulated_dealbreakers = [d for d in dealbreakers if d["category"] == FUND_FIT_CATEGORY]
        blocking_dealbreakers = [d for d in dealbreakers if d["category"] != FUND_FIT_CATEGORY]
    else:
        simulated_dealbreakers = []
        blocking_dealbreakers = list(dealbreakers)
    dealbreaker_blocking = len(blocking_dealbreakers) > 0

    if dealbreaker_blocking:
        verdict = "hard_pass"
    elif applicable == 0:
        verdict = "more_diligence"
    elif conviction_score >= 75:
        verdict = "invest"
    elif conviction_score >= 50:
        verdict = "more_diligence"
    else:
        verdict = "pass"

    if simulated_dealbreakers:
        warnings.append("GENERIC_MODE_DEALBREAKER_NON_BLOCKING")

    # IC-11 coverage cap: too much undisclosed to responsibly reach `invest`. The excluded-
    # denominator can inflate conviction on a thin deck (e.g. 3 strong + 24 to_confirm = 100%);
    # when to_confirm exceeds the threshold, cap the verdict at more_diligence. The conviction
    # SCORE is left unchanged (transparent); only the verdict is capped, and we flag it so
    # compose can exempt the VERDICT_SCORE_MISMATCH check for this intentional divergence.
    # IC-11 coverage guards. THIN COVERAGE IS THE CONDITION — not the verdict.
    #
    # The cap and the floor were each conditioned on the verdict they moved
    # (`== "invest"` / `== "pass"`), which left the middle uncovered: a run with 23
    # of 28 dimensions undisclosed and only 2 applicable scored 50.0%, landed in the
    # `more_diligence` band on its own, and so tripped neither guard. It was reported
    # as "More Diligence — promising but needs more evidence" with zero warnings —
    # reassuring language on a scorecard nobody had filled in. Conditioning on
    # coverage instead closes the middle, and makes the three cases one family.
    #
    # `applicable` is part of the condition, not just `to_confirm`: a company can be
    # thinly covered because almost everything was marked not_applicable, which the
    # to_confirm count alone does not see.
    thin_coverage = to_confirm_count > HIGH_TO_CONFIRM_COUNT or 0 < applicable < MIN_APPLICABLE_FOR_SCORE

    # A blocking dealbreaker is a substantive finding about the company, never an
    # absence of information, and must survive thin coverage untouched.
    coverage_capped = thin_coverage and verdict == "invest" and not dealbreaker_blocking
    coverage_floored = thin_coverage and verdict == "pass" and not dealbreaker_blocking
    # The third case: already more_diligence, but arrived there under coverage so
    # thin that "promising but needs more evidence" overstates what was assessed.
    # Nothing moves; the LABEL has to change, which is what this flag is for.
    coverage_held = thin_coverage and verdict == "more_diligence" and not dealbreaker_blocking

    if coverage_capped:
        verdict = "more_diligence"
        warnings.append("LOW_COVERAGE_VERDICT_CAP")
    if coverage_floored:
        verdict = "more_diligence"
        warnings.append("LOW_COVERAGE_VERDICT_FLOOR")
    if coverage_held:
        warnings.append("LOW_COVERAGE_VERDICT_HELD")

    return {
        "items": enriched,
        "summary": {
            "total": len(DIMENSION_ITEMS),
            "strong_conviction": strong_count,
            "moderate_conviction": moderate_count,
            "concern": concern_count,
            "dealbreaker": dealbreaker_count,
            "not_applicable": na_count,
            "to_confirm": to_confirm_count,
            "applicable": applicable,
            "conviction_score": conviction_score,
            "conviction_basis": conviction_basis,
            "verdict": verdict,
            "coverage_capped": coverage_capped,
            "coverage_floored": coverage_floored,
            "coverage_held": coverage_held,
            "fund_mode": fund_mode,
            "dealbreaker_blocking": dealbreaker_blocking,
            "blocking_dealbreaker_count": len(blocking_dealbreakers),
            "simulated_dealbreaker_ids": [d["id"] for d in simulated_dealbreakers],
            "by_category": categories,
            "dealbreakers": dealbreakers,
            "top_concerns": top_concerns,
            "warnings": warnings,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IC dimension scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", required=True, help="Run identifier injected into metadata.run_id")
    p.add_argument(
        "--fund-mode",
        choices=["generic", "fund_specific"],
        default="fund_specific",
        help=(
            "fund_profile.json's mode. 'fund_specific' (default, back-compat): a dealbreaker "
            "always forces hard_pass. 'generic': the fund is a synthesized/illustrative persona, "
            "so a dealbreaker is simulated/non-blocking and does not override the merits-based verdict."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"items\": [...]}' | python score_dimensions.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict) or "items" not in data:
        print("Error: JSON must be an object with an 'items' key", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data["items"], list):
        print("Error: 'items' must be an array", file=sys.stderr)
        sys.exit(1)

    result = validate_dimensions(data["items"], fund_mode=args.fund_mode)

    # Inject metadata.run_id as the last step before serialization (overrides any stdin metadata).
    result["metadata"] = {"run_id": args.run_id}

    indent = 2 if args.pretty else None
    if result.get("validation", {}).get("status") == "invalid":
        _fail_invalid(result, args.output, indent)
    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    _write_output(
        out,
        args.output,
        summary={"conviction_score": s.get("conviction_score"), "verdict": s.get("verdict")} if s else None,
    )


if __name__ == "__main__":
    main()
