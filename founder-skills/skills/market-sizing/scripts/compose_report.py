#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose market sizing report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./market-sizing-acme-corp/ --pretty

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

# Canonical warning severity map — stable API, tested for completeness
WARNING_SEVERITY: dict[str, str] = {
    # High severity — agent must fix before presenting report
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    "CHECKLIST_FAILURES": "high",
    "OVERCLAIMED_VALIDATION": "high",
    "UNVALIDATED_CLAIMS": "high",
    # Medium severity — include in Warnings section of report
    "MISSING_OPTIONAL_ARTIFACT": "low",
    "UNSOURCED_ASSUMPTIONS": "medium",
    "APPROACH_MISMATCH": "medium",
    "TAM_DISCREPANCY": "medium",
    "CHECKLIST_INCOMPLETE": "medium",
    "FEW_SENSITIVITY_PARAMS": "medium",
    "NARROW_AGENT_ESTIMATE_RANGE": "medium",
    "LOW_CHECKLIST_COVERAGE": "medium",
    "REFUTED_CLAIMS": "medium",
    "REFUTED_MISSING_REASON": "medium",
    "DECK_CLAIM_MISMATCH": "low",
    "PROVENANCE_UNRESOLVED": "low",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}

# Quantitative params that should appear in sensitivity analysis if agent_estimate
QUANTITATIVE_PARAMS = {
    "customer_count",
    "arpu",
    "serviceable_pct",
    "target_pct",
    "industry_total",
    "segment_pct",
    "share_pct",
}

REQUIRED_ARTIFACTS = [
    "inputs.json",
    "methodology.json",
    "validation.json",
    "sizing.json",
    "checklist.json",
    "sensitivity.json",
]
OPTIONAL_ARTIFACTS: list[str] = []

# Human-readable parameter names for report presentation
PARAM_LABELS: dict[str, str] = {
    "customer_count": "Customer Count",
    "arpu": "ARPU",
    "serviceable_pct": "Serviceable %",
    "target_pct": "Target Capture %",
    "industry_total": "Industry Total",
    "segment_pct": "Segment %",
    "share_pct": "Market Share %",
    "tam": "TAM",
    "sam": "SAM",
}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "CHECKLIST_FAILURES": "Checklist Failures",
    "OVERCLAIMED_VALIDATION": "Overclaimed Validation",
    "UNVALIDATED_CLAIMS": "Unvalidated Claims",
    "MISSING_OPTIONAL_ARTIFACT": "Missing Optional Artifact",
    "UNSOURCED_ASSUMPTIONS": "Unsourced Assumptions",
    "APPROACH_MISMATCH": "Approach Mismatch",
    "TAM_DISCREPANCY": "TAM Discrepancy",
    "CHECKLIST_INCOMPLETE": "Checklist Incomplete",
    "FEW_SENSITIVITY_PARAMS": "Few Sensitivity Parameters",
    "NARROW_AGENT_ESTIMATE_RANGE": "Narrow Agent-Estimate Range",
    "LOW_CHECKLIST_COVERAGE": "Low Checklist Coverage",
    "REFUTED_CLAIMS": "Refuted Claims",
    "REFUTED_MISSING_REASON": "Refuted Claim Missing Reason",
    "DECK_CLAIM_MISMATCH": "Deck Claim Mismatch",
    "PROVENANCE_UNRESOLVED": "Provenance Unresolved",
}


def _humanize_param(name: str) -> str:
    """Convert a parameter name to human-readable label."""
    return PARAM_LABELS.get(name, name.replace("_", " ").title())


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


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list — returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict — returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


def _fmt_usd(value: float | int) -> str:
    """Format a number as USD currency string."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.2f}"


def _md_safe(text: str) -> str:
    """Escape text for safe markdown table cell interpolation."""
    return text.replace("|", "\\|").replace("\n", " ")


def _compute_delta(calculated: float, deck_claim: Any) -> float | None:
    """Returns signed percentage delta, or None if claim is invalid."""
    try:
        claim = float(deck_claim)
    except (TypeError, ValueError):
        return None
    if claim <= 0:
        return None
    return round((calculated - claim) / claim * 100, 1)


def _compute_provenance(
    sizing: dict[str, Any],
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Compute provenance classification for each TAM/SAM/SOM figure.

    Cross-references validation.json assumptions with sizing.json inputs
    and inputs.json existing_claims.
    """
    # Build assumption name -> category map from validation
    assumption_map: dict[str, str] = {}
    if validation is not None and not _is_stub(validation):
        for assumption in _as_list(validation.get("assumptions")):
            if isinstance(assumption, dict):
                name = assumption.get("name", "")
                cat = assumption.get("category", "")
                if name and cat:
                    assumption_map[name] = cat

    # Get deck claims from inputs
    existing_claims: dict[str, Any] = {}
    if inputs is not None and not _is_stub(inputs):
        existing_claims = _as_dict(inputs.get("existing_claims"))

    provenance: dict[str, dict[str, Any]] = {}
    unresolved: list[tuple[str, str]] = []  # (param, metric) pairs

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        approach_prov: dict[str, Any] = {}
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            figure_inputs = _as_dict(m.get("inputs"))
            # Filter to quantitative params only (skip intermediates like tam, sam, etc.)
            relevant_inputs = {k: v for k, v in figure_inputs.items() if k in QUANTITATIVE_PARAMS}

            # Look up each input's category
            input_provenances: dict[str, str] = {}
            for param_name in relevant_inputs:
                if param_name in assumption_map:
                    input_provenances[param_name] = assumption_map[param_name]
                else:
                    unresolved.append((param_name, metric.upper()))

            # Classify the figure
            if not input_provenances:
                classification = "unknown"
            else:
                categories = set(input_provenances.values())
                if "agent_estimate" in categories:
                    classification = "agent_estimate"
                elif categories == {"sourced"}:
                    classification = "sourced"
                else:
                    classification = "derived"

            # Confidence breakdown
            breakdown: dict[str, int] = {"sourced": 0, "derived": 0, "agent_estimate": 0}
            for cat in input_provenances.values():
                if cat in breakdown:
                    breakdown[cat] += 1

            # Deck claim and delta
            deck_claim = existing_claims.get(metric)
            value = m.get("value", 0)
            delta = _compute_delta(float(value), deck_claim) if deck_claim is not None else None

            approach_prov[metric] = {
                "classification": classification,
                "confidence_breakdown": breakdown,
                "deck_claim": deck_claim,
                "delta_vs_deck_pct": delta,
                "input_provenances": input_provenances,
            }
        provenance[approach_key] = approach_prov

    return provenance, unresolved


def _warn(code: str, message: str) -> dict[str, str]:
    """Create a warning dict with code, message, and severity from canonical map."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run all 16 validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    methodology = artifacts.get("methodology.json")
    validation = artifacts.get("validation.json")
    sizing = artifacts.get("sizing.json")
    sensitivity = artifacts.get("sensitivity.json")
    checklist = artifacts.get("checklist.json")

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 2. CORRUPT_ARTIFACT / MISSING_OPTIONAL_ARTIFACT — optional artifacts
    for name in OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_OPTIONAL_ARTIFACT", f"Optional artifact missing: {name}"))

    # 2b. STALE_ARTIFACT — run_id mismatch across artifacts
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifact_data = artifacts.get(name)
        if _usable(artifact_data):
            assert artifact_data is not None
            rid = _as_dict(artifact_data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_ids[name] = rid
    if run_ids:
        primary_rid = next(iter(run_ids.values()))
        for name, rid in run_ids.items():
            if rid != primary_rid:
                warnings.append(
                    _warn(
                        "STALE_ARTIFACT",
                        f"{name} has run_id '{rid}' but expected '{primary_rid}'",
                    )
                )

    # 3. UNSOURCED_ASSUMPTIONS — agent_estimate assumptions not in sensitivity
    if _usable(validation):
        agent_estimate_names: set[str] = set()
        for assumption in _as_list(validation.get("assumptions")):
            if assumption.get("category") == "agent_estimate":
                name = assumption.get("name", "")
                if name in QUANTITATIVE_PARAMS:
                    agent_estimate_names.add(name)

        sensitivity_params: set[str] = set()
        if _usable(sensitivity):
            for scenario in _as_list(sensitivity.get("scenarios")):
                if scenario.get("confidence") == "agent_estimate":
                    sensitivity_params.add(scenario.get("parameter", ""))

        unsourced = agent_estimate_names - sensitivity_params
        if unsourced:
            warnings.append(
                _warn(
                    "UNSOURCED_ASSUMPTIONS",
                    "Agent-estimate assumptions not stress-tested in sensitivity: "
                    f"{[_humanize_param(p) for p in sorted(unsourced)]}",
                )
            )

    # 4. UNVALIDATED_CLAIMS
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if fig.get("status") == "unsupported":
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                warnings.append(
                    _warn(
                        "UNVALIDATED_CLAIMS",
                        f"Unsupported figure: {fig_display}",
                    )
                )

    # 5. REFUTED_CLAIMS — surfaces refuted figures in warnings section
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if fig.get("status") == "refuted":
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                refutation = fig.get("refutation")
                if not refutation:
                    # 6. REFUTED_MISSING_REASON — refuted claim without explanation
                    warnings.append(
                        _warn(
                            "REFUTED_MISSING_REASON",
                            f"Refuted figure '{fig_display}' has no refutation explanation",
                        )
                    )
                warnings.append(
                    _warn(
                        "REFUTED_CLAIMS",
                        f"Refuted figure: {fig_display} — {refutation or 'no explanation provided'}",
                    )
                )

    # 7. APPROACH_MISMATCH
    if _usable(methodology) and _usable(sizing):
        approach = methodology.get("approach_chosen", "")
        if approach == "both":
            if "top_down" not in sizing or "bottom_up" not in sizing:
                warnings.append(
                    _warn(
                        "APPROACH_MISMATCH",
                        "Methodology says 'both' but sizing.json missing top_down or bottom_up",
                    )
                )
        elif approach in ("top_down", "bottom_up") and approach not in sizing:
            warnings.append(
                _warn(
                    "APPROACH_MISMATCH",
                    f"Methodology says '{approach}' but sizing.json missing {approach} key",
                )
            )

    # 8. TAM_DISCREPANCY
    if _usable(sizing):
        comparison = _as_dict(sizing.get("comparison"))
        if comparison.get("tam_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "TAM_DISCREPANCY",
                    f"Top-down and bottom-up TAM differ by {comparison['tam_delta_pct']}% (>30%)",
                )
            )

    # 9. CHECKLIST_FAILURES
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        if summary.get("overall_status") == "fail":
            failed = _as_list(summary.get("failed_items"))
            failed_ids = [f.get("id", "?") for f in failed]
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES",
                    f"Checklist has {len(failed)} failures: {failed_ids}",
                )
            )

    # 10. CHECKLIST_INCOMPLETE
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        if len(items) != 22:
            warnings.append(
                _warn(
                    "CHECKLIST_INCOMPLETE",
                    f"Checklist has {len(items)} items (expected 22)",
                )
            )

    # 11. LOW_CHECKLIST_COVERAGE
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        na_count = summary.get("not_applicable", 0)
        if na_count > 7:
            warnings.append(
                _warn(
                    "LOW_CHECKLIST_COVERAGE",
                    f"Checklist has {na_count} not_applicable items (>7 of 22)",
                )
            )

    # 12. FEW_SENSITIVITY_PARAMS
    if _usable(sensitivity):
        scenarios = _as_list(sensitivity.get("scenarios"))
        if len(scenarios) < 3:
            warnings.append(
                _warn(
                    "FEW_SENSITIVITY_PARAMS",
                    f"Sensitivity analysis has {len(scenarios)} parameters (recommend 3+)",
                )
            )

    # 13. NARROW_AGENT_ESTIMATE_RANGE
    if _usable(sensitivity):
        for scenario in _as_list(sensitivity.get("scenarios")):
            if scenario.get("confidence") == "agent_estimate":
                eff = _as_dict(scenario.get("effective_range"))
                low = abs(eff.get("low_pct", 0))
                high = abs(eff.get("high_pct", 0))
                if low < 50 or high < 50:
                    warnings.append(
                        _warn(
                            "NARROW_AGENT_ESTIMATE_RANGE",
                            f"Agent-estimate parameter '{scenario.get('parameter')}' has effective range "
                            f"[{eff.get('low_pct')}%, +{eff.get('high_pct')}%] — should be at least +/-50%",
                        )
                    )

    # 14. OVERCLAIMED_VALIDATION
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if fig.get("status") == "validated" and fig.get("source_count", 0) < 2:
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                warnings.append(
                    _warn(
                        "OVERCLAIMED_VALIDATION",
                        f"Figure '{fig_display}' marked validated but source_count={fig.get('source_count')}",
                    )
                )

    # 15. DECK_CLAIM_MISMATCH — deck claim differs from calculated by >50%
    inputs_art = artifacts.get("inputs.json")
    if _usable(sizing) and _usable(inputs_art):
        existing_claims = _as_dict(inputs_art.get("existing_claims"))
        for approach_key in ("top_down", "bottom_up"):
            approach_data = sizing.get(approach_key)
            if approach_data is None:
                continue
            for metric in ("tam", "sam", "som"):
                m = _as_dict(approach_data.get(metric))
                val = m.get("value", 0)
                claim = existing_claims.get(metric)
                delta = _compute_delta(float(val), claim)
                if delta is not None and abs(delta) > 50 and claim is not None:
                    warnings.append(
                        _warn(
                            "DECK_CLAIM_MISMATCH",
                            f"{metric.upper()} differs from deck claim by {delta:+.1f}% "
                            f"(deck: {_fmt_usd(float(claim))}, calculated: {_fmt_usd(val)})",
                        )
                    )

    # 16. PROVENANCE_UNRESOLVED — quantitative param in sizing inputs without matching assumption
    if _usable(sizing) and _usable(validation):
        provenance_result, unresolved = _compute_provenance(sizing, validation, artifacts.get("inputs.json"))
        if unresolved:
            # Aggregate: param -> list of metrics
            param_metrics: dict[str, list[str]] = {}
            for param, metric_name in unresolved:
                param_metrics.setdefault(param, []).append(metric_name)
            parts = [f"{p} (used in {', '.join(ms)})" for p, ms in sorted(param_metrics.items())]
            warnings.append(
                _warn(
                    "PROVENANCE_UNRESOLVED",
                    "Quantitative inputs without matching assumptions in validation.json: " + ", ".join(parts),
                )
            )

    return warnings


def _section_title_provenance(inputs: dict[str, Any] | None) -> str:
    """Section 1: Title and provenance."""
    if inputs is None:
        return "# Market Sizing Report\n\n*No inputs artifact found.*\n"
    company = inputs.get("company_name", "Unknown Company")
    date = inputs.get("analysis_date", "unknown date")
    materials = _as_list(inputs.get("materials_provided"))
    mat_str = ", ".join(str(m) for m in materials) if materials else "none"
    lines = [
        f"# Market Sizing: {company}\n",
        f"**Date:** {date}  ",
        f"**Materials:** {mat_str}  ",
        "**Generated by:** [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent\n",
    ]
    return "\n".join(lines)


def _section_executive_summary(
    sizing: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Executive summary with key metrics from sizing and sensitivity."""
    if sizing is None or _is_stub(sizing):
        return "## Executive Summary\n\n*No sizing data available for summary.*\n"

    lines = ["## Executive Summary\n"]
    lines.append("| Metric | Value | Method |")
    lines.append("|--------|-------|--------|")

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            val = m.get("value", 0)
            lines.append(f"| {metric.upper()} | {_fmt_usd(val)} | {method} |")

    if sensitivity is not None and not _is_stub(sensitivity):
        most = sensitivity.get("most_sensitive")
        if most:
            lines.append(f"| Most Sensitive Parameter | {_humanize_param(most)} | — |")

    # Flag significant deck claim deltas
    if provenance:
        both_mode = "top_down" in provenance and "bottom_up" in provenance
        for metric in ("tam", "sam", "som"):
            # Collect mismatches across approaches for this metric
            mismatches: list[tuple[str, float, float]] = []  # (label, val, deck_claim)
            for approach_key in ("top_down", "bottom_up"):
                if approach_key not in provenance:
                    continue
                prov = provenance[approach_key].get(metric, {})
                delta = prov.get("delta_vs_deck_pct")
                deck_claim = prov.get("deck_claim")
                if delta is not None and abs(delta) > 50 and deck_claim is not None:
                    approach_data = _as_dict(sizing.get(approach_key)) if sizing else {}
                    m_data = _as_dict(approach_data.get(metric))
                    val = m_data.get("value", 0)
                    label = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    mismatches.append((label, float(val), float(deck_claim)))
            if mismatches:
                claim_str = _fmt_usd(mismatches[0][2])
                if both_mode and len(mismatches) > 1:
                    parts = ", ".join(f"{lbl}: {_fmt_usd(v)}" for lbl, v, _ in mismatches)
                    lines.append(
                        f"\n**Note:** Both {metric.upper()} estimates differ significantly "
                        f"from the deck's claim of {claim_str} ({parts})."
                    )
                elif both_mode:
                    lbl, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {lbl.lower()} {metric.upper()} estimate differs significantly "
                        f"from the deck's claim ({_fmt_usd(val)} vs {claim_str})."
                    )
                else:
                    _, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {metric.upper()} estimate differs significantly "
                        f"from the deck's claim ({_fmt_usd(val)} vs {claim_str})."
                    )

    return "\n".join(lines) + "\n"


def _section_methodology(methodology: dict[str, Any] | None) -> str:
    """Methodology section showing approach and rationale."""
    if methodology is None:
        return "## Methodology\n\n*No methodology artifact found.*\n"
    if _is_stub(methodology):
        return f"## Methodology\n\n*Methodology not recorded — {methodology.get('reason', 'unknown reason')}*\n"

    approach = methodology.get("approach_chosen", "unknown")
    rationale = methodology.get("rationale", "")
    approach_label = {
        "both": "Both (top-down and bottom-up cross-validation)",
        "top_down": "Top-down",
        "bottom_up": "Bottom-up",
    }.get(approach, approach)

    lines = ["## Methodology\n"]
    lines.append(f"**Approach:** {approach_label}")
    if rationale:
        lines.append(f"**Rationale:** {rationale}")
    return "\n".join(lines) + "\n"


def _section_analysis_checklist(checklist: dict[str, Any] | None, artifacts_found: list[str]) -> str:
    """Analysis checklist."""
    lines = ["## Analysis Checklist\n"]
    lines.append(f"- Artifacts produced: {', '.join(artifacts_found)}")
    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        pass_ct = summary.get("pass", 0)
        fail_ct = summary.get("fail", 0)
        na_ct = summary.get("not_applicable", 0)
        lines.append(f"- Self-check: {pass_ct} pass, {fail_ct} fail, {na_ct} N/A")
    return "\n".join(lines) + "\n"


def _section_definitions() -> str:
    """Section 3: Brief TAM/SAM/SOM definitions."""
    return (
        "## Definitions\n\n"
        "- **TAM** (Total Addressable Market): Total market demand for the "
        "product/service if 100% market share were achieved.\n"
        "- **SAM** (Serviceable Available Market): The segment of TAM targeted "
        "by your products and services that is within your geographical reach.\n"
        "- **SOM** (Serviceable Obtainable Market): The portion of SAM that you "
        "can realistically capture in the near term.\n"
    )


def _section_sizing_table(
    sizing: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Section 4: Market sizing table."""
    if sizing is None:
        return "## Market Sizing\n\n*No sizing data available.*\n"
    if _is_stub(sizing):
        return f"## Market Sizing\n\n*Sizing not performed — {sizing.get('reason', 'unknown reason')}*\n"

    lines = ["## Market Sizing\n"]

    # One-line narrative per approach
    td_data = sizing.get("top_down")
    bu_data = sizing.get("bottom_up")
    if td_data:
        tam_inputs = _as_dict(_as_dict(td_data.get("tam")).get("inputs"))
        td_sam_inputs = _as_dict(_as_dict(td_data.get("sam")).get("inputs"))
        industry = _fmt_usd(tam_inputs.get("industry_total", 0)) if "industry_total" in tam_inputs else "?"
        seg = td_sam_inputs.get("segment_pct", "?") if "segment_pct" in td_sam_inputs else "?"
        share_inputs = _as_dict(_as_dict(td_data.get("som")).get("inputs"))
        share = share_inputs.get("share_pct", "?") if "share_pct" in share_inputs else "?"
        lines.append(
            f"**Top-down:** Starting from industry total of {industry}, "
            f"targeting {seg}% segment with {share}% market share.\n"
        )
    if bu_data:
        tam_inputs = _as_dict(_as_dict(bu_data.get("tam")).get("inputs"))
        cust = tam_inputs.get("customer_count", "?")
        arpu_val = _fmt_usd(tam_inputs.get("arpu", 0)) if "arpu" in tam_inputs else "?"
        sam_inputs = _as_dict(_as_dict(bu_data.get("sam")).get("inputs"))
        serv = tam_inputs.get("serviceable_pct", sam_inputs.get("serviceable_pct", "?"))
        som_inputs = _as_dict(_as_dict(bu_data.get("som")).get("inputs"))
        tgt = tam_inputs.get("target_pct", som_inputs.get("target_pct", "?"))
        if isinstance(cust, (int, float)):
            bu_line = (
                f"**Bottom-up:** {cust:,} potential customers x "
                f"{arpu_val} ARPU, {serv}% serviceable, {tgt}% target capture.\n"
            )
        else:
            bu_line = (
                f"**Bottom-up:** {cust} potential customers x "
                f"{arpu_val} ARPU, {serv}% serviceable, {tgt}% target capture.\n"
            )
        lines.append(bu_line)

    lines.append("| Metric | Value | Method | Provenance | Key Assumptions |")
    lines.append("|--------|-------|--------|------------|-----------------|")

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            val = m.get("value", 0)
            inputs_data = _as_dict(m.get("inputs"))
            assumption_parts = []
            for k, v in inputs_data.items():
                label = _humanize_param(k)
                formatted = _fmt_usd(v) if k in ("industry_total", "arpu", "tam", "sam") else _fmt_number(v)
                assumption_parts.append(f"{label}: {formatted}")
            assumptions = ", ".join(assumption_parts)
            # Look up provenance classification
            prov_label = ""
            if provenance and approach_key in provenance:
                prov = provenance[approach_key].get(metric, {})
                prov_label = _md_safe(prov.get("classification", ""))
            lines.append(f"| {metric.upper()} | {_fmt_usd(val)} | {method} | {prov_label} | {assumptions} |")

    comparison = sizing.get("comparison")
    if comparison:
        delta = comparison.get("tam_delta_pct", 0)
        note = comparison.get("warning") or comparison.get("note", "")
        lines.append(f"\n**Cross-validation:** TAM delta = {delta}%. {note}")

    # Deck Claims comparison table
    if provenance:
        comparison_rows: list[str] = []
        for approach_key in ("top_down", "bottom_up"):
            if approach_key not in provenance:
                continue
            for metric in ("tam", "sam", "som"):
                prov = provenance[approach_key].get(metric, {})
                deck_claim = prov.get("deck_claim")
                delta_pct = prov.get("delta_vs_deck_pct")
                classification = prov.get("classification", "")
                if deck_claim is not None and delta_pct is not None:
                    approach_data = sizing.get(approach_key, {})
                    m = _as_dict(approach_data.get(metric))
                    val = m.get("value", 0)
                    method = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    comparison_rows.append(
                        f"| {metric.upper()} ({method}) | {_fmt_usd(float(deck_claim))} "
                        f"| {_fmt_usd(val)} | {delta_pct:+.1f}% | {_md_safe(classification)} |"
                    )
        if comparison_rows:
            lines.append("\n### Deck Claims vs. Our Estimates\n")
            lines.append("| Metric | Deck Claim | Our Estimate | Delta | Classification |")
            lines.append("|--------|-----------|--------------|-------|----------------|")
            lines.extend(comparison_rows)

    return "\n".join(lines) + "\n"


def _section_assumptions(validation: dict[str, Any] | None) -> str:
    """Section 5: Assumptions."""
    if validation is None:
        return "## Assumptions\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return f"## Assumptions\n\n*Validation not performed — {validation.get('reason', 'unknown reason')}*\n"

    assumptions = _as_list(validation.get("assumptions"))
    if not assumptions:
        return "## Assumptions\n\n*No assumptions recorded.*\n"

    lines = ["## Assumptions\n"]
    cat_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    # Params whose values are monetary
    monetary_params = {"industry_total", "arpu"}
    for a in assumptions:
        cat = a.get("category", "unknown")
        cat_display = cat_labels.get(cat, cat)
        name = a.get("name", "unnamed")
        display_name = a.get("label", _humanize_param(name))
        value = a.get("value", "")
        if isinstance(value, (int, float)) and name in monetary_params:
            formatted_val = _fmt_usd(value)
        elif isinstance(value, (int, float)):
            formatted_val = _fmt_number(value)
        else:
            formatted_val = str(value)
        lines.append(f"- **{display_name}** = {formatted_val} ({cat_display})")
    return "\n".join(lines) + "\n"


def _section_validation(validation: dict[str, Any] | None) -> str:
    """Section 6: Figure validation."""
    if validation is None:
        return "## Validation\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return f"## Validation\n\n*Validation not performed — {validation.get('reason', 'unknown reason')}*\n"

    figs = _as_list(validation.get("figure_validations"))
    if not figs:
        return "## Validation\n\n*No figures validated.*\n"

    lines = ["## Validation\n"]
    for fig in figs:
        figure = fig.get("label") or fig.get("figure", "unknown")
        status = fig.get("status", "unknown")
        source_count = fig.get("source_count", 0)
        lines.append(f"- **{figure}**: {status} ({source_count} source{'s' if source_count != 1 else ''})")
    return "\n".join(lines) + "\n"


def _section_sensitivity(sensitivity: dict[str, Any] | None) -> str:
    """Section 7: Sensitivity analysis."""
    if sensitivity is None:
        return "## Sensitivity Analysis\n\n*No sensitivity analysis available.*\n"
    if _is_stub(sensitivity):
        reason = sensitivity.get("reason", "unknown reason")
        return f"## Sensitivity Analysis\n\n*Sensitivity analysis not performed — {reason}*\n"

    scenarios = _as_list(sensitivity.get("scenarios"))
    if not scenarios:
        return "## Sensitivity Analysis\n\n*No scenarios analyzed.*\n"

    lines = [
        "## Sensitivity Analysis\n",
        "The table below shows how SOM changes when each assumption moves between"
        " its low and high estimate. Parameters tagged *Estimate* have wider ranges"
        " because they lack external sourcing — they tend to dominate the sensitivity,"
        " which highlights exactly where better data would most strengthen the analysis.\n",
    ]
    has_approach_used = any(s.get("approach_used") for s in scenarios)
    if has_approach_used:
        lines.append("| Parameter | Approach | Confidence | Low SOM | Base SOM | High SOM | Range |")
        lines.append("|-----------|----------|------------|---------|----------|----------|-------|")
    else:
        lines.append("| Parameter | Confidence | Low SOM | Base SOM | High SOM | Range |")
        lines.append("|-----------|------------|---------|----------|----------|-------|")

    conf_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    for s in scenarios:
        param = _humanize_param(s.get("parameter", "?"))
        conf = conf_labels.get(s.get("confidence", "sourced"), s.get("confidence", "sourced"))
        low_som = _fmt_usd(s.get("low", {}).get("som", 0))
        base_som = _fmt_usd(s.get("base", {}).get("som", 0))
        high_som = _fmt_usd(s.get("high", {}).get("som", 0))
        eff = _as_dict(s.get("effective_range"))
        range_str = f"[{eff.get('low_pct', 0)}%, +{eff.get('high_pct', 0)}%]"
        widened = " (widened)" if s.get("range_widened") else ""
        if has_approach_used:
            approach_labels = {"top_down": "Top-down", "bottom_up": "Bottom-up"}
            approach_used = approach_labels.get(s.get("approach_used", "?"), s.get("approach_used", "?"))
            lines.append(
                f"| {param} | {approach_used} | {conf} | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
            )
        else:
            lines.append(f"| {param} | {conf} | {low_som} | {base_som} | {high_som} | {range_str}{widened} |")

    ranking = _as_list(sensitivity.get("sensitivity_ranking"))
    if ranking:
        most = _humanize_param(ranking[0].get("parameter", "?"))
        lines.append(f"\n**Most sensitive parameter:** {most}")

    return "\n".join(lines) + "\n"


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Section 8: Warnings/errors."""
    if not warnings:
        return ""

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i", "info": "~"}
    lines = ["## Warnings\n"]
    for w in warnings:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


def _section_sources(validation: dict[str, Any] | None) -> str:
    """Section 9: Sources used."""
    if validation is None:
        return "## Sources Used\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return "## Sources Used\n\n*No sources — validation not performed.*\n"

    sources = _as_list(validation.get("sources"))
    if not sources:
        return (
            "## Sources Used\n\nSources Used: none — pure calculation from "
            "user-provided inputs (no market size claims to validate)\n"
        )

    # Deduplicate by URL or title
    seen: set[str] = set()
    lines = ["## Sources Used\n"]
    for i, s in enumerate(sources):
        key = s.get("url") or s.get("title", "") or f"__unnamed_{i}"
        if key in seen:
            continue
        seen.add(key)
        title = s.get("title", "Untitled")
        publisher = s.get("publisher", "")
        url = s.get("url", "")
        date = s.get("date_accessed", "")
        supported = s.get("supported", "")
        # Title as clickable link if URL available, otherwise bold
        title_part = f"[{title}]({url})" if url else f"**{title}**"
        parts = [title_part]
        if publisher:
            parts.append(publisher)
        if date:
            parts.append(f"accessed {date}")
        line = f"- {parts[0]}"
        meta = [p for p in parts[1:]]
        if meta:
            line += f" ({', '.join(meta)})"
        if supported:
            line += f" — supports: {supported}"
        lines.append(line)
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

    # Apply accepted_warnings from methodology (medium-severity only, instance-scoped)
    methodology_art = artifacts.get("methodology.json")
    if _usable(methodology_art):
        acceptances: list[dict[str, str]] = []
        for aw in _as_list(methodology_art.get("accepted_warnings")):
            code = aw.get("code", "")
            match_str = aw.get("match", "")
            if not code or not match_str:
                print("Warning: accepted_warnings entry missing 'code' or 'match' — skipped", file=sys.stderr)
                continue
            reason = aw.get("reason", "")
            if not isinstance(reason, str) or not reason.strip():
                print(f"Warning: accepted_warnings entry for '{code}' missing 'reason' — skipped", file=sys.stderr)
                continue
            if code in WARNING_SEVERITY and WARNING_SEVERITY[code] in ACCEPTIBLE_SEVERITIES:
                acceptances.append(
                    {
                        "code": code,
                        "reason": reason,
                        "match": match_str,
                    }
                )
            elif code in WARNING_SEVERITY:
                print(f"Warning: cannot accept high-severity code '{code}' — ignored", file=sys.stderr)
        for w in warnings:
            for acc in acceptances:
                if w["code"] == acc["code"] and acc["match"].lower() in w.get("message", "").lower():
                    w["severity"] = "acknowledged"
                    w["message"] += f" [Accepted: {acc['reason']}]"
                    break

    # Determine status
    status = "clean" if not warnings else "warnings"

    # Assemble report — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inputs = _render_safe(artifacts.get("inputs.json"))
    methodology = _render_safe(artifacts.get("methodology.json"))
    validation_data = _render_safe(artifacts.get("validation.json"))
    sizing = _render_safe(artifacts.get("sizing.json"))
    sensitivity = _render_safe(artifacts.get("sensitivity.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))

    # Compute provenance
    provenance_data: dict[str, dict[str, Any]] | None = None
    if _usable(sizing) and not _is_stub(sizing):
        provenance_data, _ = _compute_provenance(sizing, validation_data, inputs)

    sections = [
        _section_title_provenance(inputs),
        _section_executive_summary(sizing, sensitivity, provenance_data),
        _section_analysis_checklist(checklist, artifacts_found),
        _section_methodology(methodology),
        _section_definitions(),
        _section_sizing_table(sizing, provenance_data),
        _section_assumptions(validation_data),
        _section_validation(validation_data),
        _section_sensitivity(sensitivity),
        _section_warnings(warnings),
        _section_sources(validation_data),
    ]

    report_markdown = "\n".join(sections)
    report_markdown += (
        "\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent*\n"
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

    result = {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
        },
    }

    if provenance_data:
        result["provenance"] = provenance_data

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose market sizing report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--strict", action="store_true", help="Exit 1 if any warnings (CI mode)")
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

    if args.strict:
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] in ("high", "medium")]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
