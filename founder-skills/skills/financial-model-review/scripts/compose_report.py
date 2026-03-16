#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose financial model review report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./fmr-testco/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, TypeGuard

# Sentinel for corrupt (unparseable) artifact files
_CORRUPT: dict[str, Any] = {"__corrupt__": True}

# Canonical warning severity map -- stable API, tested for completeness
WARNING_SEVERITY: dict[str, str] = {
    # High severity -- agent must fix before presenting report
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    # Checklist failures are review findings, not data errors — present, don't block
    "CHECKLIST_FAILURES": "medium",
    # Low severity -- informational
    "MISSING_OPTIONAL_ARTIFACT": "low",
    # Medium severity -- include in Warnings section of report
    "CHECKLIST_INCOMPLETE": "medium",
    "RUNWAY_INCONSISTENCY": "medium",
    "METRICS_GAPS": "medium",
}

REQUIRED_ARTIFACTS = ["inputs.json", "checklist.json", "unit_economics.json", "runway.json"]
OPTIONAL_ARTIFACTS = ["model_data.json"]

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "STALE_ARTIFACT": "Stale Artifact",
    "CHECKLIST_FAILURES": "Checklist Failures",
    "MISSING_OPTIONAL_ARTIFACT": "Missing Optional Artifact",
    "CHECKLIST_INCOMPLETE": "Checklist Incomplete",
    "RUNWAY_INCONSISTENCY": "Runway Inconsistency",
    "METRICS_GAPS": "Metrics Gaps",
}

# Rating display labels
RATING_LABELS: dict[str, str] = {
    "strong": "Strong",
    "acceptable": "Acceptable",
    "warning": "Warning",
    "fail": "Fail",
    "not_rated": "Not Rated",
    "contextual": "Contextual",
    "not_applicable": "N/A",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


def _fmt_number(value: Any) -> str:
    """Format a numeric value for display (with commas, no unnecessary decimals)."""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _fmt_usd(value: float | int) -> str:
    """Format a number as USD currency string."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.2f}"


def _fmt_pct(value: float | int) -> str:
    """Format a value as a percentage string."""
    if isinstance(value, float) and value <= 1.0:
        return f"{value * 100:.1f}%"
    return f"{value}%"


def _md_safe(text: str | None) -> str:
    """Escape text for safe markdown table cell interpolation."""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("\n", " ")


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


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact. Returns None if missing, _CORRUPT if unparseable."""
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return _CORRUPT


def _is_stub(data: dict[str, Any] | None) -> bool:
    """Check if artifact is a stub (intentionally skipped)."""
    return isinstance(data, dict) and data.get("skipped") is True


def _format_runway_months(months: Any) -> str:
    """Format runway months, handling None (infinite/profitable) gracefully."""
    if months is None:
        return "Infinite (reaches profitability)"
    return f"{months} months"


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list -- returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict -- returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


def _warn(code: str, message: str) -> dict[str, str]:
    """Create a warning dict with code, message, and severity from canonical map."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    checklist = artifacts.get("checklist.json")
    unit_economics = artifacts.get("unit_economics.json")
    runway = artifacts.get("runway.json")
    inputs = artifacts.get("inputs.json")

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT -- required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 1b. STALE_ARTIFACT -- run_id mismatch across artifacts
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if _usable(data):
            assert data is not None  # for type narrowing
            rid = _as_dict(data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_ids[name] = rid
    if len(run_ids) >= 2:
        unique_ids = set(run_ids.values())
        if len(unique_ids) > 1:
            mismatched = [f"{n} ({rid})" for n, rid in run_ids.items()]
            warnings.append(
                _warn(
                    "STALE_ARTIFACT",
                    f"Run ID mismatch across artifacts — possible stale data: {', '.join(mismatched)}",
                )
            )

    # 2. CORRUPT_ARTIFACT / MISSING_OPTIONAL_ARTIFACT -- optional artifacts
    for name in OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_OPTIONAL_ARTIFACT", f"Optional artifact missing: {name}"))

    # 3. CHECKLIST_FAILURES -- checklist overall_status indicates failure
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        if summary.get("overall_status") == "major_revision":
            failed = _as_list(summary.get("failed_items"))
            failed_ids = [f.get("id", "?") for f in failed]
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES",
                    f"Checklist has {len(failed)} failures: {failed_ids}",
                )
            )

    # 4. CHECKLIST_INCOMPLETE -- unexpected item count
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        if len(items) != 46:
            warnings.append(
                _warn(
                    "CHECKLIST_INCOMPLETE",
                    f"Checklist has {len(items)} items (expected 46)",
                )
            )

    # 5. RUNWAY_INCONSISTENCY -- runway cash doesn't match inputs cash
    if _usable(runway) and _usable(inputs):
        baseline = _as_dict(runway.get("baseline"))
        cash_data = _as_dict(inputs.get("cash"))
        runway_cash = baseline.get("net_cash")
        raw_balance = cash_data.get("current_balance")
        raw_debt = cash_data.get("debt")
        inputs_cash = (raw_balance if isinstance(raw_balance, (int, float)) else 0) - (
            raw_debt if isinstance(raw_debt, (int, float)) else 0
        )
        if (
            runway_cash is not None
            and isinstance(runway_cash, (int, float))
            and isinstance(raw_balance, (int, float))
            and inputs_cash != 0
        ):
            delta_pct = abs(runway_cash - inputs_cash) / abs(inputs_cash) * 100
            if delta_pct > 10:
                warnings.append(
                    _warn(
                        "RUNWAY_INCONSISTENCY",
                        f"Runway net_cash ({_fmt_usd(runway_cash)}) differs from inputs "
                        f"net cash ({_fmt_usd(inputs_cash)}) by {delta_pct:.0f}%",
                    )
                )

    # 6. CHECKLIST_RUNWAY_CONTRADICTION -- CASH_* failures + default_alive: true
    if _usable(checklist) and _usable(runway):
        items = _as_list(checklist.get("items"))
        cash_fails = [
            i
            for i in items
            if isinstance(i, dict) and str(i.get("id", "")).startswith("CASH_") and i.get("status") == "fail"
        ]
        scenarios = _as_list(runway.get("scenarios"))
        base_scenario = next((s for s in scenarios if s.get("name") == "base"), None)
        if cash_fails and base_scenario and base_scenario.get("default_alive") is True:
            fail_ids = [str(f.get("id", "?")) for f in cash_fails]
            warnings.append(
                _warn(
                    "RUNWAY_INCONSISTENCY",
                    f"Checklist items {fail_ids} failed (cash/burn issues) but runway "
                    f"base scenario shows default_alive: true — review inputs for consistency",
                )
            )
        # Also flag cash direction warnings from runway scenarios
        for s in scenarios:
            cdw = s.get("cash_direction_warning")
            if cdw:
                warnings.append(
                    _warn(
                        "RUNWAY_INCONSISTENCY",
                        f"Scenario '{s.get('name', '?')}': {cdw}",
                    )
                )

    # 7. METRICS_GAPS -- unit economics has few computed metrics
    if _usable(unit_economics):
        ue_summary = _as_dict(unit_economics.get("summary"))
        computed = ue_summary.get("computed", 0)
        if isinstance(computed, int) and computed < 2:
            warnings.append(
                _warn(
                    "METRICS_GAPS",
                    f"Unit economics computed only {computed} metrics (recommend 2+)",
                )
            )

    # Downgrade CHECKLIST_FAILURES severity for non-spreadsheet formats
    if _usable(inputs):
        model_format = _as_dict(inputs.get("company")).get("model_format", "spreadsheet")
        if model_format in ("deck", "conversational"):
            for w in warnings:
                if w["code"] == "CHECKLIST_FAILURES":
                    w["severity"] = "medium"

    return warnings


def _section_title(inputs: dict[str, Any] | None) -> str:
    """Title section with company name."""
    if inputs is None:
        return "# Financial Model Review\n\n*No inputs artifact found.*\n"
    company = _as_dict(inputs.get("company"))
    company_name = company.get("company_name", "Unknown Company")
    return f"# Financial Model Review: {company_name}\n"


def _section_executive_summary(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    unit_economics: dict[str, Any] | None,
    runway: dict[str, Any] | None,
) -> str:
    """Executive summary with stage, overall status, and key metrics."""
    lines = ["## Executive Summary\n"]
    data_confidence = "exact"  # safe default; overwritten if inputs present

    if inputs is not None and not _is_stub(inputs):
        company = _as_dict(inputs.get("company"))
        stage = company.get("stage", "unknown")
        sector = company.get("sector", "unknown")
        data_confidence = company.get("data_confidence", "exact")
        model_format = company.get("model_format", "spreadsheet")
        lines.append(f"**Stage:** {stage}  ")
        lines.append(f"**Sector:** {sector}  ")
        if data_confidence != "exact":
            dq_label = "Mixed" if data_confidence == "mixed" else "Estimated"
            lines.append(f"**Data Quality:** {dq_label} — review based on {model_format}, not audited financials  ")

    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        status = summary.get("overall_status", "unknown")
        score = summary.get("score_pct", 0)
        model_maturity = summary.get("model_maturity_pct")
        if model_maturity is None and data_confidence != "exact":
            bq_score = summary.get("business_quality_pct", score)
            lines.append(
                f"**Deck Financial Readiness:** {status} ({bq_score:.0f}%) "
                f"(business quality only — no spreadsheet model)  "
            )
        else:
            lines.append(f"**Model Quality:** {status} ({score:.0f}%)  ")

    if unit_economics is not None and not _is_stub(unit_economics):
        metrics = _as_list(unit_economics.get("metrics"))
        key_names = {"cac", "ltv", "gross_margin", "ltv_cac_ratio", "burn_multiple"}
        key_metrics = [m for m in metrics if m.get("name") in key_names and m.get("value") is not None]
        if key_metrics:
            parts = []
            for m in key_metrics:
                name = m["name"].upper().replace("_", " ")
                val = m["value"]
                rating = m.get("rating", "")
                if isinstance(val, float) and val < 10:
                    parts.append(f"{name}: {val:.2f} ({rating})")
                else:
                    parts.append(f"{name}: {_fmt_number(val)} ({rating})")
            lines.append(f"**Key Metrics:** {', '.join(parts)}  ")

    if runway is not None and not _is_stub(runway):
        scenarios = _as_list(runway.get("scenarios"))
        base = next((s for s in scenarios if s.get("name") == "base"), None)
        if base:
            months = base.get("runway_months", "?")
            alive = base.get("default_alive", None)
            alive_str = "Yes" if alive else "No" if alive is not None else "Unknown"
            lines.append(f"**Base Runway:** {_format_runway_months(months)} (Default Alive: {alive_str})  ")

    return "\n".join(lines) + "\n"


def _section_checklist(checklist: dict[str, Any] | None) -> str:
    """Checklist results section."""
    if checklist is None:
        return "## Checklist Results\n\n*No checklist data available.*\n"
    if _is_stub(checklist):
        return f"## Checklist Results\n\n*Checklist not performed -- {checklist.get('reason', 'unknown reason')}*\n"

    summary = _as_dict(checklist.get("summary"))
    lines = ["## Checklist Results\n"]

    score = summary.get("score_pct", 0)
    total = summary.get("total", 0)
    pass_ct = summary.get("pass", 0)
    fail_ct = summary.get("fail", 0)
    warn_ct = summary.get("warn", 0)
    na_ct = summary.get("not_applicable", 0)
    status = summary.get("overall_status", "unknown")

    lines.append(f"**Overall:** {status} ({score:.0f}%)  ")
    lines.append(f"**Breakdown:** {pass_ct} pass, {fail_ct} fail, {warn_ct} warn, {na_ct} N/A out of {total} items\n")

    # Failed items
    failed_items = _as_list(summary.get("failed_items"))
    if failed_items:
        lines.append("### Failed Items\n")
        for item in failed_items:
            item_id = item.get("id", "?")
            label = item.get("label", item_id)
            evidence = item.get("evidence", "")
            lines.append(f"- **{item_id}** ({label}): {_md_safe(evidence)}")
        lines.append("")

    # Warned items
    warned_items = _as_list(summary.get("warned_items"))
    if warned_items:
        lines.append("### Warned Items\n")
        for item in warned_items:
            item_id = item.get("id", "?")
            label = item.get("label", item_id)
            evidence = item.get("evidence", "")
            lines.append(f"- **{item_id}** ({label}): {_md_safe(evidence)}")
        lines.append("")

    # By category summary
    by_category = _as_dict(summary.get("by_category"))
    if by_category:
        lines.append("### By Category\n")
        lines.append("| Category | Pass | Fail | Warn | N/A |")
        lines.append("|----------|------|------|------|-----|")
        for cat_name, cat_data in by_category.items():
            cd = _as_dict(cat_data)
            lines.append(
                f"| {_md_safe(cat_name)} | {cd.get('pass', 0)} | {cd.get('fail', 0)} "
                f"| {cd.get('warn', 0)} | {cd.get('not_applicable', 0)} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_unit_economics(unit_economics: dict[str, Any] | None) -> str:
    """Unit economics section with metrics table."""
    if unit_economics is None:
        return "## Unit Economics\n\n*No unit economics data available.*\n"
    if _is_stub(unit_economics):
        return (
            f"## Unit Economics\n\n*Unit economics not computed -- {unit_economics.get('reason', 'unknown reason')}*\n"
        )

    metrics = _as_list(unit_economics.get("metrics"))
    if not metrics:
        return "## Unit Economics\n\n*No metrics computed.*\n"

    lines = ["## Unit Economics\n"]

    # Check if metrics are based on estimated inputs
    if metrics:
        has_estimated = any(m.get("confidence") in ("estimated", "mixed") for m in metrics)
        if has_estimated:
            lines.append("\n*Metrics below are based on estimated inputs.*\n")

    lines.append("| Metric | Value | Rating | Evidence |")
    lines.append("|--------|-------|--------|----------|")

    for m in metrics:
        name = m.get("name", "?").upper().replace("_", " ")
        val = m.get("value")
        rating = RATING_LABELS.get(m.get("rating", ""), m.get("rating", ""))
        evidence = _md_safe(m.get("evidence", ""))

        if val is None:
            val_str = "N/A"
        elif isinstance(val, float) and val <= 1.0 and m.get("name") in ("gross_margin", "nrr", "grr"):
            val_str = _fmt_pct(val)
        elif isinstance(val, (int, float)) and m.get("name") in ("cac", "ltv"):
            val_str = _fmt_usd(val)
        elif isinstance(val, float):
            val_str = f"{val:.2f}"
        else:
            val_str = _fmt_number(val)

        lines.append(f"| {name} | {val_str} | {rating} | {evidence} |")

    # Summary
    ue_summary = _as_dict(unit_economics.get("summary"))
    if ue_summary:
        strong = ue_summary.get("strong", 0)
        acceptable = ue_summary.get("acceptable", 0)
        warning = ue_summary.get("warning", 0)
        fail = ue_summary.get("fail", 0)
        lines.append(f"\n**Summary:** {strong} strong, {acceptable} acceptable, {warning} warning, {fail} fail")

    return "\n".join(lines) + "\n"


def _section_runway(runway: dict[str, Any] | None) -> str:
    """Runway analysis section with scenarios table."""
    if runway is None:
        return "## Runway Analysis\n\n*No runway data available.*\n"
    if _is_stub(runway):
        return f"## Runway Analysis\n\n*Runway analysis not performed -- {runway.get('reason', 'unknown reason')}*\n"

    lines = ["## Runway Analysis\n"]

    # Baseline
    baseline = _as_dict(runway.get("baseline"))
    if baseline:
        net_cash = baseline.get("net_cash")
        burn = baseline.get("monthly_burn")
        rev = baseline.get("monthly_revenue")
        if net_cash is not None:
            lines.append(f"**Net Cash:** {_fmt_usd(net_cash)}  ")
        if burn is not None:
            lines.append(f"**Monthly Burn:** {_fmt_usd(burn)}  ")
        if rev is not None:
            lines.append(f"**Monthly Revenue:** {_fmt_usd(rev)}  ")
        lines.append("")

    # Burn sensitivity table (partial analysis when cash balance unknown)
    burn_sensitivity = _as_list(runway.get("burn_sensitivity"))
    if burn_sensitivity:
        lines.append("### Burn-Based Sensitivity (Cash Balance Unknown)\n")
        lines.append("| Starting Cash | Estimated Runway |")
        lines.append("|---------------|-----------------|")
        for row in burn_sensitivity:
            cash_val = row.get("starting_cash", 0)
            rw = row.get("runway_months")
            rw_str = f"{rw:.1f} months" if rw is not None else "Infinite"
            lines.append(f"| {_fmt_usd(cash_val)} | {rw_str} |")
        lines.append("")

    # Scenarios table
    scenarios = _as_list(runway.get("scenarios"))
    if scenarios:
        lines.append("### Scenarios\n")
        lines.append("| Scenario | Runway (months) | Cash-Out Date | Decision Point | Default Alive |")
        lines.append("|----------|----------------|---------------|----------------|---------------|")
        for s in scenarios:
            name = s.get("name", "?")
            months_raw = s.get("runway_months")
            months = _format_runway_months(months_raw) if months_raw is None else months_raw
            cash_out = s.get("cash_out_date", "?")
            decision = s.get("decision_point", "?")
            alive = s.get("default_alive", None)
            alive_str = "Yes" if alive else "No" if alive is not None else "?"
            lines.append(f"| {name} | {months} | {cash_out} | {decision} | {alive_str} |")
        lines.append("")

    # Post-raise
    post_raise = _as_dict(runway.get("post_raise"))
    if post_raise and post_raise.get("raise_amount"):
        lines.append("### Post-Raise Projection\n")
        lines.append(f"**Raise Amount:** {_fmt_usd(post_raise['raise_amount'])}  ")
        lines.append(f"**New Cash:** {_fmt_usd(post_raise.get('new_cash', 0))}  ")
        new_rw = post_raise.get("new_runway_months")
        lines.append(f"**New Runway:** {new_rw if new_rw else '∞'} months  ")
        meets = post_raise.get("meets_target")
        if meets is not None:
            lines.append(f"**Meets Target:** {'Yes' if meets else 'No'}  ")
        lines.append("")

    # Risk assessment
    risk = runway.get("risk_assessment")
    if risk:
        lines.append(f"**Risk Assessment:** {risk}\n")

    return "\n".join(lines) + "\n"


_MODEL_PREREQS: dict[str, str] = {
    "Structure & Presentation": "A dedicated spreadsheet model with separate tabs",
    "Expenses, Cash & Runway": "Detailed expense breakdown, headcount plan, and cash flow projections",
}


def _section_model_completeness(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> str:
    """Model completeness section for non-spreadsheet reviews."""
    if inputs is None:
        return ""
    model_format = _as_dict(inputs.get("company")).get("model_format", "spreadsheet")
    if model_format == "spreadsheet":
        return ""

    lines = ["## Model Completeness\n"]
    lines.append(f"*This review was based on a {model_format} — not a full spreadsheet model.*\n")

    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        na_items = [i for i in items if isinstance(i, dict) and i.get("status") == "not_applicable"]
        by_cat: dict[str, list[str]] = {}
        for item in na_items:
            cat = str(item.get("category", "Other"))
            by_cat.setdefault(cat, []).append(str(item.get("label", item.get("id", "?"))))

        if by_cat:
            lines.append("### Items Not Evaluated\n")
            for cat, labels in by_cat.items():
                prereq = _MODEL_PREREQS.get(cat, "Additional financial data")
                lines.append(f"**{cat}** ({len(labels)} items) — requires: {prereq}")
                for label in labels[:5]:
                    lines.append(f"  - {_md_safe(label)}")
                if len(labels) > 5:
                    lines.append(f"  - ...and {len(labels) - 5} more")
                lines.append("")

        lines.append("### What to Build Next\n")
        lines.append("1. **Start with a basic 3-tab model:** Assumptions, P&L, Cash Flow")
        lines.append("2. **Add headcount-driven expenses:** Map team growth to burn rate")
        lines.append("3. **Include scenario toggles:** Base, optimistic, and downside cases")
        lines.append("4. **Model runway explicitly:** Monthly cash balance projections to cash-out date")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_overrides(inputs: dict[str, Any] | None) -> str:
    """Warning overrides section for audit transparency."""
    if inputs is None:
        return ""
    overrides = _as_list(_as_dict(inputs.get("metadata")).get("warning_overrides"))
    if not overrides:
        return ""

    # Separate agent vs founder overrides.
    # Dedupe by code alone (legacy overrides lack 'field'), so a code-only
    # legacy/agent override and a code+field founder override for the same
    # warning are not shown in both sections.
    agent_overrides = [o for o in overrides if isinstance(o, dict) and o.get("reviewed_by") == "agent"]
    legacy = [o for o in overrides if isinstance(o, dict) and not o.get("reviewed_by")]
    acknowledged_codes = {o.get("code") for o in agent_overrides + legacy if o.get("code")}
    founder_only = [
        o
        for o in overrides
        if isinstance(o, dict) and o.get("reviewed_by") == "founder" and o.get("code") not in acknowledged_codes
    ]

    lines: list[str] = []
    if agent_overrides or legacy:
        lines.append("## Acknowledged Warnings\n")
        lines.append("The following validation warnings were reviewed and acknowledged:\n")
        for o in agent_overrides + legacy:
            code = o.get("code", "?")
            reason = o.get("reason", "No reason provided")
            lines.append(f"- **{_humanize_warning(code)}** (`{code}`): {_md_safe(reason)}")

    if founder_only:
        lines.append("\n## Founder-Reported Context\n")
        lines.append("The following were noted by the founder during extraction review (not agent-verified):\n")
        for o in founder_only:
            code = o.get("code", "?")
            reason = o.get("reason", "No reason provided")
            lines.append(f"- **{_humanize_warning(code)}** (`{code}`): {_md_safe(reason)} *(founder-reported)*")

    return "\n".join(lines) + "\n" if lines else ""


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Validation warnings section."""
    if not warnings:
        return ""

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i", "info": "~"}
    lines = ["## Validation Warnings\n"]
    for w in warnings:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


def compose(dir_path: str) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    # Load all artifacts
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    artifacts_found = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in all_names if artifacts[n] is None]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # Determine status
    status = "clean" if not warnings else "warnings"

    # Assemble report -- treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inputs = _render_safe(artifacts.get("inputs.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))
    unit_economics = _render_safe(artifacts.get("unit_economics.json"))
    runway = _render_safe(artifacts.get("runway.json"))

    sections = [
        _section_title(inputs),
        _section_executive_summary(inputs, checklist, unit_economics, runway),
        _section_checklist(checklist),
        _section_model_completeness(inputs, checklist),
        _section_unit_economics(unit_economics),
        _section_runway(runway),
        _section_overrides(inputs),
        _section_warnings(warnings),
    ]

    report_markdown = "\n".join(sections)
    report_markdown += (
        "\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Financial Model Review Agent*\n"
    )

    # Stderr summary
    print(f"Artifacts found: {len(artifacts_found)}/{len(all_names)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        print(f"Warnings: {len(high)} high, {len(medium)} medium", file=sys.stderr)
        for w in warnings:
            print(f"  [{w['severity'].upper()}] {w['code']}: {w['message']}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)

    # Determine model_format for --strict context
    model_format = "spreadsheet"
    if _usable(inputs):
        model_format = _as_dict(inputs.get("company")).get("model_format", "spreadsheet")

    return {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
            "model_format": model_format,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose financial model review report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--strict", action="store_true", help="Exit 1 if any high/medium warnings (CI mode)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    result = compose(args.dir)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    v = result["validation"]
    _write_output(
        out,
        args.output,
        summary={"validation": v["status"], "warnings": len(v["warnings"])},
    )

    # Exit 1 if any required artifacts are missing (regardless of strict mode)
    missing_required = [w for w in result["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    if missing_required:
        print("Exiting with code 1: required artifacts missing", file=sys.stderr)
        sys.exit(1)

    if args.strict:
        # Strict blocks on high-severity data/structural warnings only.
        # CHECKLIST_FAILURES (medium) are review findings, not data errors.
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] == "high"]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
