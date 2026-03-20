#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Competitive positioning moat scorer.

Validates per-company moat assessments from positioning.json, computes
aggregates (moat_count, strongest_moat, overall_defensibility), and
produces a cross-company comparison by moat dimension.

Always reads JSON from stdin.

Usage:
    echo '{"moat_assessments": {...}, "metadata": {"run_id": "..."}}' \
        | python score_moats.py --pretty

Output: JSON with per-company scores, comparison, and warnings.
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANONICAL_MOAT_IDS = [
    "network_effects",
    "data_advantages",
    "switching_costs",
    "regulatory_barriers",
    "cost_structure",
    "brand_reputation",
]
CANONICAL_MOAT_SET = set(CANONICAL_MOAT_IDS)

VALID_STATUSES = {"strong", "moderate", "weak", "absent", "not_applicable"}
VALID_TRAJECTORIES = {"building", "stable", "eroding"}
VALID_EVIDENCE_SOURCES = {"researched", "agent_estimate", "founder_override"}

# Status ordering for ranking (higher = stronger)
STATUS_RANK: dict[str, int] = {
    "strong": 4,
    "moderate": 3,
    "weak": 2,
    "absent": 1,
    "not_applicable": 0,
}

EVIDENCE_MIN_LENGTH = 20


# ---------------------------------------------------------------------------
# Validation & scoring
# ---------------------------------------------------------------------------


def _validate_moat_entry(entry: dict[str, Any], company: str, errors: list[str]) -> bool:
    """Validate a single moat entry. Returns True if valid."""
    moat_id = entry.get("id", "")
    if not moat_id:
        errors.append(f"{company}: moat entry missing 'id'")
        return False

    # Accept canonical IDs or custom_{slug} pattern
    if moat_id not in CANONICAL_MOAT_SET and not moat_id.startswith("custom_"):
        errors.append(f"{company}: unknown moat ID '{moat_id}' (must be canonical or custom_*)")
        return False

    status = entry.get("status", "")
    if status not in VALID_STATUSES:
        errors.append(f"{company}: invalid status '{status}' for moat '{moat_id}'")
        return False

    trajectory = entry.get("trajectory", "")
    if trajectory not in VALID_TRAJECTORIES:
        errors.append(f"{company}: invalid trajectory '{trajectory}' for moat '{moat_id}'")
        return False

    evidence_source = entry.get("evidence_source", "")
    if evidence_source not in VALID_EVIDENCE_SOURCES:
        errors.append(f"{company}: invalid evidence_source '{evidence_source}' for moat '{moat_id}'")
        return False

    if "evidence" not in entry:
        errors.append(f"{company}: missing 'evidence' for moat '{moat_id}'")
        return False

    return True


def _compute_aggregates(moats: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute moat_count, strongest_moat, overall_defensibility for a company."""
    active_moats = [m for m in moats if m["status"] not in ("absent", "not_applicable")]
    moat_count = len(active_moats)

    # Find strongest moat
    strongest_moat: str | None = None
    best_rank = -1
    for m in moats:
        rank = STATUS_RANK.get(m["status"], 0)
        if rank > best_rank and m["status"] not in ("absent", "not_applicable"):
            best_rank = rank
            strongest_moat = m["id"]

    # Overall defensibility
    strong_count = sum(1 for m in moats if m["status"] == "strong")
    moderate_count = sum(1 for m in moats if m["status"] == "moderate")

    if strong_count >= 2:
        overall_defensibility = "high"
    elif strong_count >= 1 or moderate_count >= 2:
        overall_defensibility = "moderate"
    else:
        overall_defensibility = "low"

    return {
        "moat_count": moat_count,
        "strongest_moat": strongest_moat,
        "overall_defensibility": overall_defensibility,
    }


def _build_comparison(companies: dict[str, Any]) -> dict[str, Any]:
    """Build cross-company comparison by moat dimension."""
    by_dimension: dict[str, dict[str, str]] = {}
    startup_rank: dict[str, dict[str, int]] = {}

    # Collect status per company per canonical moat
    for mid in CANONICAL_MOAT_IDS:
        dim_statuses: dict[str, str] = {}
        for slug, co_data in companies.items():
            for m in co_data["moats"]:
                if m["id"] == mid:
                    dim_statuses[slug] = m["status"]
                    break
            else:
                # Company doesn't have this moat — treat as absent
                dim_statuses[slug] = "absent"
        by_dimension[mid] = dim_statuses

        # Compute startup rank: rank all companies by status strength, 1 = strongest
        if "_startup" in dim_statuses:
            startup_status = dim_statuses["_startup"]
            if startup_status == "not_applicable":
                # Can't rank if startup has no assessment for this dimension
                startup_rank[mid] = {"rank": -1, "total": 0}  # -1 = not rankable (n/a)
            else:
                startup_status_rank = STATUS_RANK.get(startup_status, 0)
                # Only rank among companies that have a rankable status
                rankable = {s: st for s, st in dim_statuses.items() if st != "not_applicable"}
                higher_count = sum(
                    1 for r in (STATUS_RANK.get(st, 0) for st in rankable.values()) if r > startup_status_rank
                )
                startup_rank[mid] = {
                    "rank": higher_count + 1,
                    "total": len(rankable),
                }

    return {
        "by_dimension": by_dimension,
        "startup_rank": startup_rank,
    }


def score_moats(data: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate moat assessments and produce scored output.

    Returns (result_dict, errors). On success errors is empty.
    On failure result is None and errors contains messages.
    """
    moat_assessments = data.get("moat_assessments", {})
    metadata = data.get("metadata", {})
    data_confidence = data.get("data_confidence")

    errors: list[str] = []
    warnings: list[dict[str, Any]] = []

    if not isinstance(moat_assessments, dict) or not moat_assessments:
        errors.append("'moat_assessments' must be a non-empty object")
        return None, errors

    # Data confidence qualifier
    confidence_suffix = ""
    if data_confidence == "estimated":
        confidence_suffix = " (based on estimated inputs)"
    elif data_confidence == "mixed":
        confidence_suffix = " (partially estimated)"

    companies: dict[str, Any] = {}

    for slug, company_data in moat_assessments.items():
        if not isinstance(company_data, dict) or "moats" not in company_data:
            errors.append(f"{slug}: missing 'moats' array")
            continue

        moats = company_data["moats"]
        if not isinstance(moats, list):
            errors.append(f"{slug}: 'moats' must be an array")
            continue

        # Validate each moat entry
        valid_moats: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for entry in moats:
            if not isinstance(entry, dict):
                errors.append(f"{slug}: moat entry must be an object")
                continue
            if not _validate_moat_entry(entry, slug, errors):
                continue
            moat_id = entry["id"]
            if moat_id in seen_ids:
                errors.append(f"{slug}: duplicate moat ID '{moat_id}'")
                continue
            seen_ids.add(moat_id)

            # Build output moat (copy + qualify evidence if needed)
            out_moat = {
                "id": moat_id,
                "status": entry["status"],
                "evidence": entry["evidence"] + confidence_suffix if confidence_suffix else entry["evidence"],
                "evidence_source": entry["evidence_source"],
                "trajectory": entry["trajectory"],
            }
            valid_moats.append(out_moat)

            # Quality check: strong with short evidence
            raw_evidence = entry.get("evidence", "")
            if entry["status"] == "strong" and len(raw_evidence) < EVIDENCE_MIN_LENGTH:
                warnings.append(
                    {
                        "code": "MOAT_WITHOUT_EVIDENCE",
                        "severity": "medium",
                        "message": (
                            f"{slug}: {moat_id} rated 'strong' with insufficient evidence ({len(raw_evidence)} chars)"
                        ),
                        "company": slug,
                        "moat_id": moat_id,
                    }
                )

        # Check for missing canonical moats (warning, not error)
        present_canonical = seen_ids & CANONICAL_MOAT_SET
        missing_canonical = CANONICAL_MOAT_SET - present_canonical
        for mid in sorted(missing_canonical):
            warnings.append(
                {
                    "code": "MISSING_CANONICAL_MOAT",
                    "severity": "medium",
                    "message": f"{slug}: missing canonical moat '{mid}'",
                    "company": slug,
                    "moat_id": mid,
                }
            )

        aggregates = _compute_aggregates(valid_moats)
        companies[slug] = {
            "moats": valid_moats,
            **aggregates,
        }

    # Check for hard errors after processing ALL companies
    if errors:
        return None, errors

    comparison = _build_comparison(companies)

    return {
        "companies": companies,
        "comparison": comparison,
        "warnings": warnings,
        "_produced_by": "score_moats",
        "metadata": metadata,
    }, []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Moat scorer (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: echo '{\"moat_assessments\": {...}}' | python score_moats.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict) or "moat_assessments" not in data:
        print("Error: JSON must be an object with a 'moat_assessments' key", file=sys.stderr)
        sys.exit(1)

    result, errs = score_moats(data)
    if errs:
        for err in errs:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    assert result is not None  # guaranteed by errs check above

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"

    startup_co = result["companies"].get("_startup", {})
    _write_output(
        out,
        args.output,
        summary={
            "startup_defensibility": startup_co.get("overall_defensibility"),
            "warning_count": len(result["warnings"]),
        }
        if startup_co
        else None,
    )


if __name__ == "__main__":
    main()
