#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Review completeness gate for financial model review.

Validates artifact existence, content quality, and cross-artifact consistency.
Exit 0 = publishable, exit 1 = gaps remain.

Usage:
    python verify_review.py --dir <artifacts_dir> [--gate {1,2}] [--pretty] [-o <file>]

Output:
    stdout: JSON with status, artifacts, cross_checks, summary
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_artifact(dir_path: str, name: str) -> tuple[dict[str, Any] | None, bool, bool]:
    """Load a JSON artifact from dir.

    Returns (data, is_valid, is_corrupt).
    - File exists and parses: (data, True, False)
    - File missing: (None, False, False)
    - File exists but invalid JSON: (None, False, True)
    """
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None, False, False
    try:
        with open(path) as f:
            data = json.load(f)
        return data, True, False
    except (json.JSONDecodeError, ValueError):
        return None, False, True


def _is_skipped(data: dict[str, Any] | None) -> bool:
    """Check if an artifact is a skipped stub."""
    return isinstance(data, dict) and data.get("skipped") is True


def _deep_get(data: dict[str, Any] | None, *keys: str) -> Any:
    """Safely traverse nested dicts."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _approx_eq(a: float | int | None, b: float | int | None, threshold: float = 0.2) -> bool:
    """Check if two values are within threshold relative difference."""
    if a is None or b is None:
        return True  # can't compare, not a divergence
    if a == 0 and b == 0:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom <= threshold


def _issue(level: str, message: str) -> dict[str, str]:
    """Create an issue dict."""
    return {"severity": level, "message": message}


# ---------------------------------------------------------------------------
# Tier 1 — Existence checks
# ---------------------------------------------------------------------------

_ALWAYS_REQUIRED = [
    "inputs.json",
    "checklist.json",
    "unit_economics.json",
    "runway.json",
    "report.json",
]

_OPTIONAL = ["model_data.json", "report.html", "explore.html"]


def _check_existence(dir_path: str, gate: int, model_format: str | None) -> dict[str, dict[str, Any]]:
    """Check artifact existence. Returns per-artifact status dicts."""
    results: dict[str, dict[str, Any]] = {}

    # Determine which artifacts to check
    required = list(_ALWAYS_REQUIRED)

    # commentary.json is required at Gate 2 for spreadsheet/partial formats
    if gate >= 2 and model_format in ("spreadsheet", "partial"):
        required.append("commentary.json")

    all_names = required + _OPTIONAL
    # Also include commentary.json if not already required (so it appears in output)
    if "commentary.json" not in all_names:
        all_names.append("commentary.json")

    for name in all_names:
        is_required = name in required

        # HTML files: check existence only, no JSON parsing
        if name.endswith(".html"):
            path = os.path.join(dir_path, name)
            exists = os.path.isfile(path)
            entry: dict[str, Any] = {
                "exists": exists,
                "valid": exists,
                "issues": [],
                "_data": None,
                "_skipped": False,
            }
            if not exists and is_required:
                entry["issues"].append(_issue("error", f"{name}: missing (required)"))
            results[name] = entry
            continue

        data, is_valid, is_corrupt = _load_artifact(dir_path, name)
        exists = is_valid or is_corrupt  # file exists even if corrupt

        entry = {
            "exists": exists,
            "valid": is_valid,
            "issues": [],
        }

        if is_corrupt:
            entry["issues"].append(_issue("error", f"{name}: corrupt JSON"))
        elif not exists and is_required:
            entry["issues"].append(_issue("error", f"{name}: missing (required)"))

        # Store data for downstream checks
        entry["_data"] = data
        entry["_skipped"] = _is_skipped(data)

        results[name] = entry

    return results


# ---------------------------------------------------------------------------
# Tier 2 — Quality checks
# ---------------------------------------------------------------------------


def _check_inputs_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate inputs.json content quality."""
    issues: list[dict[str, str]] = []

    # Errors for null critical fields
    error_fields = [
        (("company", "company_name"), "company.company_name"),
        (("company", "stage"), "company.stage"),
        (("revenue", "mrr", "value"), "revenue.mrr.value"),
    ]
    for keys, label in error_fields:
        if _deep_get(data, *keys) is None:
            issues.append(_issue("error", f"{label} is null"))

    # Warnings for null fields
    warning_fields = [
        (("cash", "current_balance"), "cash.current_balance"),
        (("cash", "monthly_net_burn"), "cash.monthly_net_burn"),
    ]
    for keys, label in warning_fields:
        if _deep_get(data, *keys) is None:
            issues.append(_issue("warning", f"{label} is null"))

    return issues


def _check_checklist_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate checklist.json content quality."""
    issues: list[dict[str, str]] = []
    items = data.get("items", [])

    # Exactly 46 items
    if len(items) != 46:
        issues.append(_issue("error", f"Expected 46 checklist items, got {len(items)}"))

    # Every item with pass/fail/warn status must have non-empty evidence
    for item in items:
        status = item.get("status")
        if status is None:
            issues.append(_issue("error", f"Item {item.get('id', '?')}: null status"))
            continue
        if status in ("pass", "fail", "warn"):
            evidence = item.get("evidence")
            if not evidence:
                issues.append(
                    _issue(
                        "error",
                        f"Item {item.get('id', '?')}: empty evidence for status '{status}'",
                    )
                )

    return issues


def _check_ue_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate unit_economics.json content quality."""
    issues: list[dict[str, str]] = []
    metrics = data.get("metrics", [])

    computed = 0
    for m in metrics:
        rating = m.get("rating")
        value = m.get("value")
        if rating not in ("not_rated", "not_applicable") and value is not None:
            computed += 1

    if computed < 2:
        issues.append(_issue("error", f"Only {computed} computed metrics (need >= 2)"))

    return issues


def _check_runway_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate runway.json content quality."""
    issues: list[dict[str, str]] = []

    # If partial_analysis or insufficient_data, accept with warning
    if data.get("partial_analysis") or data.get("insufficient_data"):
        issues.append(_issue("warning", "Runway analysis is partial or has insufficient data"))
        return issues

    # At least 1 scenario with non-null runway_months
    scenarios = data.get("scenarios", [])
    has_runway = any(s.get("runway_months") is not None for s in scenarios)
    if not has_runway:
        issues.append(_issue("error", "No scenario has non-null runway_months"))

    # baseline.net_cash null is a warning
    net_cash = _deep_get(data, "baseline", "net_cash")
    if net_cash is None:
        issues.append(_issue("warning", "baseline.net_cash is null"))

    return issues


def _check_report_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate report.json content quality."""
    issues: list[dict[str, str]] = []

    report_md = data.get("report_markdown")
    if not report_md:
        issues.append(_issue("error", "report_markdown is empty"))

    if _deep_get(data, "validation", "status") is None:
        issues.append(_issue("error", "validation.status is missing"))

    return issues


def _check_commentary_quality(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate commentary.json content quality."""
    issues: list[dict[str, str]] = []

    headline = data.get("headline")
    if not headline:
        issues.append(_issue("error", "headline is empty or missing"))

    lenses = data.get("lenses", {})
    if not isinstance(lenses, dict) or len(lenses) < 1:
        issues.append(_issue("error", "lenses must have >= 1 key"))

    return issues


_QUALITY_CHECKS: dict[str, Any] = {
    "inputs.json": _check_inputs_quality,
    "checklist.json": _check_checklist_quality,
    "unit_economics.json": _check_ue_quality,
    "runway.json": _check_runway_quality,
    "report.json": _check_report_quality,
    "commentary.json": _check_commentary_quality,
}


# ---------------------------------------------------------------------------
# Tier 3 — Cross-artifact consistency
# ---------------------------------------------------------------------------


def _check_cross_consistency(
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Check consistency across artifacts."""
    checks: list[dict[str, str]] = []

    # Collect run_ids from non-skipped, valid artifacts
    run_ids: dict[str, str] = {}
    for name, entry in artifacts.items():
        data = entry.get("_data")
        if data is None or entry.get("_skipped"):
            continue
        rid = _deep_get(data, "metadata", "run_id")
        if rid is not None:
            run_ids[name] = rid

    # Check run_id consistency
    unique_ids = set(run_ids.values())
    if len(unique_ids) > 1:
        checks.append(
            _issue(
                "error",
                f"run_id mismatch across artifacts: {dict(run_ids)}",
            )
        )

    # Get inputs data for cross-checks
    inputs_data = artifacts.get("inputs.json", {}).get("_data")
    if inputs_data is None or artifacts.get("inputs.json", {}).get("_skipped"):
        return checks

    # runway.baseline.net_cash vs inputs.cash.current_balance
    runway_entry = artifacts.get("runway.json", {})
    runway_data = runway_entry.get("_data")
    if runway_data and not runway_entry.get("_skipped"):
        runway_cash = _deep_get(runway_data, "baseline", "net_cash")
        inputs_cash = _deep_get(inputs_data, "cash", "current_balance")
        if not _approx_eq(runway_cash, inputs_cash):
            checks.append(
                _issue(
                    "warning",
                    f"runway baseline.net_cash ({runway_cash}) diverges >20% "
                    f"from inputs cash.current_balance ({inputs_cash})",
                )
            )

    # Latest monthly total vs MRR
    mrr_value = _deep_get(inputs_data, "revenue", "mrr", "value")
    monthly = _deep_get(inputs_data, "revenue", "monthly")
    if isinstance(monthly, list) and monthly and mrr_value is not None:
        latest = monthly[-1]
        latest_total = latest.get("total") if isinstance(latest, dict) else None
        if not _approx_eq(latest_total, mrr_value):
            checks.append(
                _issue(
                    "warning",
                    f"Latest monthly timeseries total ({latest_total}) diverges "
                    f">20% from revenue.mrr.value ({mrr_value})",
                )
            )

    # ARR/12 vs MRR
    arr_value = _deep_get(inputs_data, "revenue", "arr", "value")
    if arr_value is not None and mrr_value is not None:
        arr_monthly = arr_value / 12
        if not _approx_eq(arr_monthly, mrr_value):
            checks.append(
                _issue(
                    "warning",
                    f"ARR/12 ({arr_monthly:.0f}) diverges >20% from revenue.mrr.value ({mrr_value})",
                )
            )

    return checks


# ---------------------------------------------------------------------------
# Main verification
# ---------------------------------------------------------------------------


def verify(dir_path: str, gate: int = 2) -> dict[str, Any]:
    """Run all verification checks and return the result dict."""
    # First, try to load inputs.json to get model_format (needed for existence checks)
    inputs_data, inputs_valid, inputs_corrupt = _load_artifact(dir_path, "inputs.json")
    model_format = _deep_get(inputs_data, "company", "model_format") if inputs_data else None

    # Tier 1: existence
    artifacts = _check_existence(dir_path, gate, model_format)

    # Tier 2: quality checks on valid, non-skipped artifacts
    for name, check_fn in _QUALITY_CHECKS.items():
        entry = artifacts.get(name)
        if entry is None:
            continue
        data = entry.get("_data")
        if data is None or entry.get("_skipped"):
            continue
        quality_issues = check_fn(data)
        entry["issues"].extend(quality_issues)

    # Tier 3: cross-artifact consistency
    cross_checks = _check_cross_consistency(artifacts)

    # Build summary
    all_errors: list[str] = []
    all_warnings: list[str] = []
    total_checks = 0
    passed = 0
    failed = 0

    for _name, entry in artifacts.items():
        for issue in entry.get("issues", []):
            total_checks += 1
            if issue["severity"] == "error":
                all_errors.append(issue["message"])
                failed += 1
            else:
                all_warnings.append(issue["message"])
                passed += 1

    for cc in cross_checks:
        total_checks += 1
        if cc["severity"] == "error":
            all_errors.append(cc["message"])
            failed += 1
        else:
            all_warnings.append(cc["message"])
            passed += 1

    # Count artifact-level passes (valid artifacts with no issues count as passed checks)
    for _name, entry in artifacts.items():
        if entry["valid"] and not entry.get("issues"):
            total_checks += 1
            passed += 1

    status = "pass" if not all_errors else "fail"

    # Clean internal fields from output
    clean_artifacts: dict[str, Any] = {}
    for name, entry in artifacts.items():
        clean_artifacts[name] = {
            "exists": entry["exists"],
            "valid": entry["valid"],
            "issues": entry["issues"],
        }

    return {
        "status": status,
        "artifacts": clean_artifacts,
        "cross_checks": [{"severity": cc["severity"], "message": cc["message"]} for cc in cross_checks],
        "summary": {
            "total_checks": total_checks,
            "passed": passed,
            "failed": failed,
            "errors": all_errors,
            "warnings": all_warnings,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review completeness gate for financial model review")
    parser.add_argument("--dir", required=True, help="Artifacts directory")
    parser.add_argument(
        "--gate",
        type=int,
        choices=[1, 2],
        default=2,
        help="Gate level: 1=after compose, 2=final (default)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("-o", dest="output_file", help="Write output to file")
    args = parser.parse_args()

    result = verify(args.dir, gate=args.gate)

    indent = 2 if args.pretty else None
    output = json.dumps(result, indent=indent)

    if args.output_file:
        with open(args.output_file, "w") as f:
            f.write(output)
            f.write("\n")
    else:
        print(output)

    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
