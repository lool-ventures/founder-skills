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
VALID_STATUSES = {"strong_conviction", "moderate_conviction", "concern", "dealbreaker", "not_applicable"}
ITEM_LOOKUP = {item["id"]: item for item in DIMENSION_ITEMS}


def validate_dimensions(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate dimension input and produce scored summary."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"Item {len(seen_ids)} must be an object (got {type(item).__name__})")
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

    applicable = len(DIMENSION_ITEMS) - na_count
    warnings: list[str] = []

    # Conviction score: (strong*1.0 + moderate*0.5) / applicable * 100
    if applicable > 0:
        conviction_score = round((strong_count * 1.0 + moderate_count * 0.5) / applicable * 100, 1)
    else:
        conviction_score = 0.0
        warnings.append("ZERO_APPLICABLE_DIMENSIONS")

    # Verdict determination
    if dealbreaker_count > 0:
        verdict = "hard_pass"
    elif applicable == 0:
        verdict = "more_diligence"
    elif conviction_score >= 75:
        verdict = "invest"
    elif conviction_score >= 50:
        verdict = "more_diligence"
    else:
        verdict = "pass"

    return {
        "items": enriched,
        "summary": {
            "total": len(DIMENSION_ITEMS),
            "strong_conviction": strong_count,
            "moderate_conviction": moderate_count,
            "concern": concern_count,
            "dealbreaker": dealbreaker_count,
            "not_applicable": na_count,
            "applicable": applicable,
            "conviction_score": conviction_score,
            "verdict": verdict,
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

    result = validate_dimensions(data["items"])

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    s = result["summary"]
    _write_output(
        out,
        args.output,
        summary={"conviction_score": s.get("conviction_score"), "verdict": s.get("verdict")} if s else None,
    )


if __name__ == "__main__":
    main()
