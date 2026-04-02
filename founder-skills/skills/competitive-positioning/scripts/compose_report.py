#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose competitive positioning report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./cp-testco/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any, TypeGuard

# Sentinel for corrupt artifacts
_CORRUPT: dict[str, Any] = {"__corrupt__": True}

# Canonical warning severity map.
# high = must fix before presenting, medium = warn in report,
# low = note in appendix, info = note in report metadata.
WARNING_SEVERITY: dict[str, str] = {
    # High — block under --strict
    "MISSING_LANDSCAPE": "high",
    "MISSING_POSITIONING_SCORES": "high",
    "MISSING_MOAT_SCORES": "high",
    "MISSING_CHECKLIST": "high",
    "MISSING_POSITIONING": "high",
    "CORRUPT_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    "UNVALIDATED_ARTIFACT": "high",
    # Medium — show in report
    "SHALLOW_COMPETITOR_PROFILE": "medium",
    "VANITY_AXIS_WARNING": "medium",
    "MOAT_WITHOUT_EVIDENCE": "medium",
    "MISSING_DO_NOTHING": "medium",
    "RESEARCH_DEPTH_LOW": "medium",
    "MISSING_CANONICAL_MOAT": "medium",
    "INCOMPLETE_SCORING": "medium",
    # Low
    "FOUNDER_OVERRIDE_COUNT": "low",
    # Info
    "SEQUENTIAL_FALLBACK": "info",
    "CHECKLIST_ALL_PASS": "info",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "UNVALIDATED_ARTIFACT": "Unvalidated Artifact",
    "MISSING_LANDSCAPE": "Missing Landscape",
    "MISSING_POSITIONING_SCORES": "Missing Positioning Scores",
    "MISSING_MOAT_SCORES": "Missing Moat Scores",
    "MISSING_POSITIONING": "Missing Positioning",
    "MISSING_CHECKLIST": "Missing Checklist",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "STALE_ARTIFACT": "Stale Artifact",
    "SHALLOW_COMPETITOR_PROFILE": "Shallow Competitor Profile",
    "VANITY_AXIS_WARNING": "Vanity Axis Warning",
    "MOAT_WITHOUT_EVIDENCE": "Moat Without Evidence",
    "MISSING_DO_NOTHING": "Missing Do-Nothing Alternative",
    "RESEARCH_DEPTH_LOW": "Research Depth Low",
    "MISSING_CANONICAL_MOAT": "Missing Canonical Moat",
    "INCOMPLETE_SCORING": "Incomplete Scoring",
    "FOUNDER_OVERRIDE_COUNT": "Founder Override Count",
    "SEQUENTIAL_FALLBACK": "Sequential Fallback",
    "CHECKLIST_ALL_PASS": "Checklist All Pass",
}

# Required artifacts — missing any of these produces a high-severity warning.
REQUIRED_ARTIFACTS = [
    "landscape.json",
    "positioning.json",
    "moat_scores.json",
    "positioning_scores.json",
    "checklist.json",
]

# Optional artifacts — nice to have for richer report.
OPTIONAL_ARTIFACTS = [
    "product_profile.json",
]

# Map artifact filename to missing-warning code.
MISSING_CODES: dict[str, str] = {
    "landscape.json": "MISSING_LANDSCAPE",
    "positioning.json": "MISSING_POSITIONING",
    "moat_scores.json": "MISSING_MOAT_SCORES",
    "positioning_scores.json": "MISSING_POSITIONING_SCORES",
    "checklist.json": "MISSING_CHECKLIST",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    """Coerce to list — returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict — returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


def _humanize(value: str) -> str:
    """Convert machine IDs to human-readable labels for report output."""
    _LABELS: dict[str, str] = {
        "full": "Full",
        "partial": "Partial",
        "founder_provided": "Founder Provided",
        "researched": "Researched",
        "agent_estimate": "Agent Estimate",
        "founder_override": "Founder Override",
        "direct": "Direct",
        "adjacent": "Adjacent",
        "do_nothing": "Do Nothing",
        "emerging": "Emerging",
        "custom": "Custom",
        "building": "Building",
        "stable": "Stable",
        "eroding": "Eroding",
        "strong": "Strong",
        "moderate": "Moderate",
        "weak": "Weak",
        "absent": "Absent",
        "not_applicable": "N/A",
        "high": "High",
        "low": "Low",
        "network_effects": "Network Effects",
        "data_advantages": "Data Advantages",
        "switching_costs": "Switching Costs",
        "regulatory_barriers": "Regulatory Barriers",
        "cost_structure": "Cost Structure",
        "brand_reputation": "Brand Reputation",
        "pre-seed": "Pre-Seed",
        "seed": "Seed",
        "series-a": "Series A",
        "series-b": "Series B",
        "series_a": "Series A",
        "series_b": "Series B",
        "later": "Later",
        "growth": "Growth",
        "deck": "Deck",
        "conversation": "Conversation",
        "document": "Document",
    }
    return _LABELS.get(value, value.replace("_", " ").title() if value else "?")


def _warn(code: str, message: str) -> dict[str, Any]:
    """Create a warning dict with code, message, and severity."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


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


def _write_output(
    data: str,
    output_path: str | None,
    *,
    summary: dict[str, Any] | None = None,
) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(
                f"Error: output path resolves to root directory: {output_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {
            "ok": True,
            "path": abs_path,
            "bytes": len(data.encode("utf-8")),
        }
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


# ---------------------------------------------------------------------------
# Positioning normalization
# ---------------------------------------------------------------------------


def _normalize_positioning(positioning: dict[str, Any]) -> None:
    """Best-effort normalization of common LLM shape mismatches in positioning.json.

    Unlike the strict normalizers in score_moats.py/score_positioning.py, this
    skips malformed entries silently — compose is a report assembler, not a gate.
    The strict scoring scripts already validate upstream.

    Fixes:
    - moat_assessments: array-of-objects → dict keyed by slug
    - views[].x_axis/y_axis: string → {name: string}
    - views[].points[].slug → competitor
    """
    # Normalize moat_assessments array → dict
    raw_moats = positioning.get("moat_assessments")
    if isinstance(raw_moats, list):
        result: dict[str, Any] = {}
        for entry in raw_moats:
            if not isinstance(entry, dict):
                continue
            slug = entry.get("slug", "")
            if not isinstance(slug, str) or not slug.strip():
                continue
            if slug in result:
                continue
            value = {k: v for k, v in entry.items() if k != "slug"}
            result[slug] = value
        if result:
            positioning["moat_assessments"] = result

    # Normalize views
    for view in _as_list(positioning.get("views")):
        view = _as_dict(view)
        for axis_key in ("x_axis", "y_axis"):
            val = view.get(axis_key)
            if isinstance(val, str) and val.strip():
                view[axis_key] = {"name": val}
        for point in _as_list(view.get("points")):
            point = _as_dict(point)
            if "slug" in point and "competitor" not in point:
                slug_val = point.get("slug")
                if isinstance(slug_val, str) and slug_val.strip():
                    point["competitor"] = point.pop("slug")


# ---------------------------------------------------------------------------
# Cross-artifact validation
# ---------------------------------------------------------------------------


def _count_founder_overrides(positioning: dict[str, Any]) -> int:
    """Count evidence_source == 'founder_override' across positioning points and moat assessments."""
    count = 0
    # Count in views -> points
    for view in _as_list(positioning.get("views")):
        for point in _as_list(_as_dict(view).get("points")):
            p = _as_dict(point)
            if p.get("x_evidence_source") == "founder_override":
                count += 1
            if p.get("y_evidence_source") == "founder_override":
                count += 1
    # Count in moat_assessments
    for _slug, company_data in _as_dict(positioning.get("moat_assessments")).items():
        for moat in _as_list(_as_dict(company_data).get("moats")):
            if _as_dict(moat).get("evidence_source") == "founder_override":
                count += 1
    return count


def validate_artifacts(
    artifacts: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Run validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, Any]] = []

    landscape = artifacts.get("landscape.json")
    positioning = artifacts.get("positioning.json")
    moat_scores = artifacts.get("moat_scores.json")
    positioning_scores = artifacts.get("positioning_scores.json")

    # 0. UNVALIDATED_ARTIFACT — script provenance check
    EXPECTED_PRODUCERS = {
        "landscape.json": "validate_landscape",
        "moat_scores.json": "score_moats",
        "positioning_scores.json": "score_positioning",
        "checklist.json": "checklist",
    }
    for name, expected in EXPECTED_PRODUCERS.items():
        data = artifacts.get(name)
        if _usable(data) and data.get("_produced_by") != expected:
            warnings.append(
                _warn(
                    "UNVALIDATED_ARTIFACT",
                    f"Artifact '{name}' exists but was not produced by {expected}.py — "
                    f"run the script instead of writing the file directly",
                )
            )

    # 1. MISSING / CORRUPT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            code = MISSING_CODES.get(name, "CORRUPT_ARTIFACT")
            warnings.append(_warn(code, f"Required artifact missing: {name}"))

    # 2. STALE_ARTIFACT — run_id consistency
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if _usable(data):
            rid = _as_dict(data.get("metadata")).get("run_id")
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

    # 3. Orphan competitor check — scoring slugs must exist in landscape
    # _startup is EXEMPT from this check
    if _usable(landscape):
        landscape_slugs = {c.get("slug") for c in _as_list(landscape.get("competitors")) if isinstance(c, dict)}

        # Check moat_scores companies
        if _usable(moat_scores):
            for slug in _as_dict(moat_scores.get("companies")):
                if slug == "_startup":
                    continue
                if slug not in landscape_slugs:
                    warnings.append(
                        _warn(
                            "CORRUPT_ARTIFACT",
                            f"Orphan competitor '{slug}' in moat_scores.json — not in landscape",
                        )
                    )

        # Check positioning.json views[].points and moat_assessments
        if _usable(positioning):
            for view in _as_list(positioning.get("views")):
                for point in _as_list(_as_dict(view).get("points")):
                    p_slug = _as_dict(point).get("competitor", "")
                    if p_slug == "_startup":
                        continue
                    if p_slug and p_slug not in landscape_slugs:
                        warnings.append(
                            _warn(
                                "CORRUPT_ARTIFACT",
                                f"Orphan competitor '{p_slug}' in positioning.json views — not in landscape",
                            )
                        )
            for slug in _as_dict(positioning.get("moat_assessments")):
                if slug == "_startup":
                    continue
                if slug not in landscape_slugs:
                    warnings.append(
                        _warn(
                            "CORRUPT_ARTIFACT",
                            f"Orphan competitor '{slug}' in positioning.json moat_assessments — not in landscape",
                        )
                    )

        # Reverse check: landscape competitors missing from scoring
        if _usable(moat_scores):
            scored_slugs = set(_as_dict(moat_scores.get("companies")).keys())
            for ls in landscape_slugs:
                if ls and ls not in scored_slugs:
                    warnings.append(
                        _warn(
                            "INCOMPLETE_SCORING",
                            f"Competitor '{ls}' in landscape but missing from moat_scores — may distort rankings",
                        )
                    )

        # Reverse check: landscape competitors missing from positioning views
        if _usable(positioning):
            positioned_slugs: set[str] = set()
            for view in _as_list(positioning.get("views")):
                for point in _as_list(_as_dict(view).get("points")):
                    cs = _as_dict(point).get("competitor", "")
                    if cs and cs != "_startup":
                        positioned_slugs.add(cs)
            for ls in landscape_slugs:
                if ls and ls not in positioned_slugs:
                    warnings.append(
                        _warn(
                            "INCOMPLETE_SCORING",
                            f"Competitor '{ls}' in landscape but missing from positioning views — map is incomplete",
                        )
                    )

    # 3b. Axis consistency — positioning view IDs must match positioning_scores view IDs
    if _usable(positioning) and _usable(positioning_scores):
        pos_view_ids = {_as_dict(v).get("id") for v in _as_list(positioning.get("views"))}
        score_view_ids = {_as_dict(v).get("view_id") for v in _as_list(positioning_scores.get("views"))}
        missing_in_scores = pos_view_ids - score_view_ids - {None}
        if missing_in_scores:
            warnings.append(
                _warn(
                    "CORRUPT_ARTIFACT",
                    f"Positioning views {missing_in_scores} not found in positioning_scores — axis mismatch",
                )
            )

    # 4. Forward warnings from sub-artifacts
    # Forward from moat_scores
    if _usable(moat_scores):
        for w in _as_list(moat_scores.get("warnings")):
            w = _as_dict(w)
            code = w.get("code", "")
            if code in WARNING_SEVERITY:
                warnings.append(_warn(code, w.get("message", f"Forwarded from moat_scores: {code}")))

    # Forward from landscape
    if _usable(landscape):
        for w in _as_list(landscape.get("warnings")):
            w = _as_dict(w)
            code = w.get("code", "")
            if code in WARNING_SEVERITY:
                warnings.append(_warn(code, w.get("message", f"Forwarded from landscape: {code}")))

    # Forward from positioning_scores (skip VANITY_AXIS_WARNING — compose generates it
    # directly from vanity flags with more detail)
    if _usable(positioning_scores):
        for w in _as_list(positioning_scores.get("warnings")):
            w = _as_dict(w)
            code = w.get("code", "")
            if code in WARNING_SEVERITY and code != "VANITY_AXIS_WARNING":
                warnings.append(_warn(code, w.get("message", f"Forwarded from positioning_scores: {code}")))

    # 5. SHALLOW_COMPETITOR_PROFILE — competitor with sourced_fields_count < 3
    if _usable(landscape):
        for comp in _as_list(landscape.get("competitors")):
            comp = _as_dict(comp)
            sfc = comp.get("sourced_fields_count", 0)
            if isinstance(sfc, int) and sfc < 3:
                slug = comp.get("slug", "?")
                rd = comp.get("research_depth", "unknown")
                if rd in ("partial", "founder_provided"):
                    warnings.append(
                        _warn(
                            "SHALLOW_COMPETITOR_PROFILE",
                            f"Competitor '{slug}' has research_depth='{rd}' with only "
                            f"{sfc} sourced fields (minimum 3 expected)",
                        )
                    )

    # 6. VANITY_AXIS_WARNING — view with vanity flag
    if _usable(positioning_scores):
        for view in _as_list(positioning_scores.get("views")):
            view = _as_dict(view)
            vid = view.get("view_id", "?")
            if view.get("x_axis_vanity_flag") is True:
                x_name = view.get("x_axis_name", "X")
                warnings.append(
                    _warn(
                        "VANITY_AXIS_WARNING",
                        f"View '{vid}': x-axis '{x_name}' flagged as vanity "
                        "(>80% of competitors cluster within 20% range)",
                    )
                )
            if view.get("y_axis_vanity_flag") is True:
                y_name = view.get("y_axis_name", "Y")
                warnings.append(
                    _warn(
                        "VANITY_AXIS_WARNING",
                        f"View '{vid}': y-axis '{y_name}' flagged as vanity "
                        "(>80% of competitors cluster within 20% range)",
                    )
                )

    # 7. RESEARCH_DEPTH_LOW — founder_provided with <4 sourced competitors
    if _usable(landscape):
        global_rd = landscape.get("research_depth", "")
        if global_rd == "founder_provided":
            sourced_count = sum(
                1
                for c in _as_list(landscape.get("competitors"))
                if isinstance(c, dict) and (c.get("sourced_fields_count") or 0) >= 3
            )
            if sourced_count < 4:
                warnings.append(
                    _warn(
                        "RESEARCH_DEPTH_LOW",
                        f"Global research_depth is 'founder_provided' and only "
                        f"{sourced_count} competitors have 3+ sourced fields "
                        f"(minimum 4 expected for reliable analysis)",
                    )
                )

    # 8. SEQUENTIAL_FALLBACK — assessment_mode == "sequential"
    is_sequential = (_usable(positioning) and positioning.get("assessment_mode") == "sequential") or (
        _usable(landscape) and landscape.get("assessment_mode") == "sequential"
    )
    if is_sequential:
        warnings.append(
            _warn(
                "SEQUENTIAL_FALLBACK",
                "Research performed sequentially (no sub-agents) — not an error, just transparency",
            )
        )

    # 9. CHECKLIST_ALL_PASS — suspicious perfect score
    checklist = artifacts.get("checklist.json")
    if _usable(checklist) and checklist.get("fail_count", 0) == 0 and checklist.get("warn_count", 0) == 0:
        warnings.append(_warn("CHECKLIST_ALL_PASS", "All checklist items passed — review for self-grading bias"))

    # 10. FOUNDER_OVERRIDE_COUNT
    if _usable(positioning):
        override_count = _count_founder_overrides(positioning)
        if override_count > 0:
            warnings.append(
                _warn(
                    "FOUNDER_OVERRIDE_COUNT",
                    f"{override_count} positioning coordinates or moat ratings have evidence_source='founder_override'",
                )
            )

    return warnings


# ---------------------------------------------------------------------------
# Markdown report sections
# ---------------------------------------------------------------------------


def _section_title(
    product_profile: dict[str, Any] | None,
    landscape: dict[str, Any] | None,
) -> str:
    """Report title."""
    company = "Unknown Company"
    if product_profile is not None and not _is_stub(product_profile):
        company = product_profile.get("company_name", company)
    return f"# Competitive Positioning Analysis: {company}\n"


def _section_executive_summary(
    product_profile: dict[str, Any] | None,
    positioning_scores: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> str:
    """Executive summary with key metrics."""
    lines = ["## Executive Summary\n"]

    if product_profile is not None and not _is_stub(product_profile):
        lines.append(f"**Company:** {product_profile.get('company_name', '?')}")
        lines.append(f"**Product:** {product_profile.get('product_description', '?')}")
        lines.append(f"**Stage:** {_humanize(str(product_profile.get('stage', '?')))}")
        lines.append(f"**Sector:** {product_profile.get('sector', '?')}")
        lines.append("")

    # Key scores
    diff_score = None
    if positioning_scores is not None and not _is_stub(positioning_scores):
        diff_score = positioning_scores.get("overall_differentiation")
        if diff_score is not None:
            # Add context: rank + gap = score
            if diff_score >= 75:
                diff_label = "Strong — clearly differentiated from the competitive set"
            elif diff_score >= 50:
                diff_label = "Moderate — differentiated but the lead is narrow"
            elif diff_score >= 25:
                diff_label = "Weak — positioned close to competitors on key axes"
            else:
                diff_label = "Undifferentiated — clustered with competitors"
            lines.append(f"**Overall Differentiation Score:** {diff_score}% ({diff_label})")

    defensibility = None
    if moat_scores is not None and not _is_stub(moat_scores):
        startup_data = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        defensibility = startup_data.get("overall_defensibility")
        if defensibility:
            lines.append(f"**Startup Defensibility:** {defensibility.replace('_', ' ').title()}")

    checklist_score = None
    if checklist is not None and not _is_stub(checklist):
        checklist_score = checklist.get("score_pct")
        if checklist_score is not None:
            lines.append(f"**Analysis Quality Score:** {checklist_score}%")

    # Summary paragraph
    lines.append("")
    if diff_score is not None and defensibility is not None:
        if diff_score >= 70 and defensibility in ("high", "moderate"):
            lines.append(
                "The startup shows strong competitive differentiation with "
                f"{defensibility} defensibility. The positioning analysis "
                "suggests a clear value proposition relative to the competitive set."
            )
        elif diff_score >= 50:
            lines.append(
                "The startup demonstrates moderate differentiation in the market. "
                "Key areas for strengthening competitive position are identified below."
            )
        else:
            lines.append(
                "The startup's differentiation is limited relative to the current "
                "competitive set. Strategic repositioning or moat-building may be needed."
            )

    return "\n".join(lines) + "\n"


def _section_competitor_landscape(landscape: dict[str, Any] | None) -> str:
    """Competitor landscape table."""
    if landscape is None or _is_stub(landscape):
        return "## Competitor Landscape\n\n*No landscape data available.*\n"

    competitors = _as_list(landscape.get("competitors"))
    lines = ["## Competitor Landscape\n"]
    lines.append(f"**Competitors Analyzed:** {len(competitors)}")
    lines.append(f"**Input Mode:** {_humanize(str(landscape.get('input_mode', '?')))}")
    lines.append("")

    lines.append("| Name | Category | Research Depth | Sourced Fields |")
    lines.append("|------|----------|---------------|----------------|")
    for c in competitors:
        c = _as_dict(c)
        name = c.get("name", "?")
        cat = _humanize(str(c.get("category", "?")))
        rd = _humanize(str(c.get("research_depth", "?")))
        sfc = c.get("sourced_fields_count", "?")
        lines.append(f"| {name} | {cat} | {rd} | {sfc} |")

    return "\n".join(lines) + "\n"


def _section_positioning(
    positioning_scores: dict[str, Any] | None,
) -> str:
    """Positioning analysis with per-view details."""
    if positioning_scores is None or _is_stub(positioning_scores):
        return "## Positioning Analysis\n\n*No positioning scores available.*\n"

    lines = ["## Positioning Analysis\n"]
    overall = positioning_scores.get("overall_differentiation")
    if overall is not None:
        lines.append(f"**Overall Differentiation:** {overall}%\n")

    for view in _as_list(positioning_scores.get("views")):
        view = _as_dict(view)
        vid = view.get("view_id", "?").title()
        lines.append(f"### {vid} View\n")
        lines.append(f"- **X-Axis:** {view.get('x_axis_name', '?')}")
        lines.append(f"  - Rationale: {view.get('x_axis_rationale', '?')}")
        vanity_x = "Yes — axis may not reveal meaningful differentiation" if view.get("x_axis_vanity_flag") else "No"
        lines.append(f"  - Vanity axis: {vanity_x}")
        lines.append(f"- **Y-Axis:** {view.get('y_axis_name', '?')}")
        lines.append(f"  - Rationale: {view.get('y_axis_rationale', '?')}")
        vanity_y = "Yes — axis may not reveal meaningful differentiation" if view.get("y_axis_vanity_flag") else "No"
        lines.append(f"  - Vanity axis: {vanity_y}")
        lines.append(f"- **Differentiation Score:** {view.get('differentiation_score', '?')}%")
        lines.append(
            f"- **Startup Rank:** X={view.get('startup_x_rank', '?')}, "
            f"Y={view.get('startup_y_rank', '?')} "
            f"(of {view.get('competitor_count', '?')} competitors)"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_moat_assessment(moat_scores: dict[str, Any] | None) -> str:
    """Moat assessment section."""
    if moat_scores is None or _is_stub(moat_scores):
        return "## Moat Assessment\n\n*No moat scores available.*\n"

    lines = ["## Moat Assessment\n"]

    companies = _as_dict(moat_scores.get("companies"))
    startup = _as_dict(companies.get("_startup"))

    if startup:
        defensibility = _humanize(str(startup.get("overall_defensibility", "?")))
        strongest = _humanize(str(startup.get("strongest_moat", "none")))
        lines.append(f"**Overall Defensibility:** {defensibility}")
        lines.append(f"**Strongest Moat:** {strongest}")
        lines.append("")

        # Moat table for _startup
        lines.append("| Moat | Status | Trajectory | Evidence Source |")
        lines.append("|------|--------|------------|----------------|")
        for moat in _as_list(startup.get("moats")):
            moat = _as_dict(moat)
            mid = _humanize(str(moat.get("id", "?")))
            status = _humanize(str(moat.get("status", "?")))
            traj = _humanize(str(moat.get("trajectory", "?")))
            src = _humanize(str(moat.get("evidence_source", "?")))
            lines.append(f"| {mid} | {status} | {traj} | {src} |")
        lines.append("")

    # Comparison highlights
    comparison = _as_dict(moat_scores.get("comparison"))
    startup_rank = _as_dict(comparison.get("startup_rank"))
    if startup_rank:
        lines.append("### Startup Ranking by Moat Dimension\n")
        for dim, rank_info in startup_rank.items():
            ri = _as_dict(rank_info)
            lines.append(f"- **{_humanize(dim)}:** Rank {ri.get('rank', '?')} of {ri.get('total', '?')}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_stress_test(positioning_scores: dict[str, Any] | None) -> str:
    """Differentiation stress-test section."""
    if positioning_scores is None or _is_stub(positioning_scores):
        return ""

    claims = _as_list(positioning_scores.get("differentiation_claims"))
    if not claims:
        return ""

    lines = ["## Differentiation Stress-Test\n"]

    for claim_data in claims:
        c = _as_dict(claim_data)
        claim = c.get("claim", "?")
        verdict = c.get("verdict", "?")
        verifiable = "Yes" if c.get("verifiable") else "No"
        lines.append(f"### {claim}\n")
        lines.append(f"- **Verdict:** {verdict}")
        lines.append(f"- **Verifiable:** {verifiable}")
        lines.append(f"- **Evidence:** {c.get('evidence', '?')}")
        lines.append(f"- **Investor Challenge:** {c.get('challenge', '?')}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_key_findings(
    positioning_scores: dict[str, Any] | None,
    moat_scores: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> str:
    """Script-generated key findings from scoring data."""
    lines = ["## Key Findings\n"]
    findings: list[str] = []

    # From positioning scores
    if positioning_scores is not None and not _is_stub(positioning_scores):
        overall = positioning_scores.get("overall_differentiation")
        if isinstance(overall, (int, float)):
            if overall >= 75:
                findings.append(
                    f"Strong differentiation ({overall}%) — the startup occupies "
                    "a distinct position in the competitive landscape."
                )
            elif overall >= 50:
                findings.append(
                    f"Moderate differentiation ({overall}%) — some positioning overlap exists with competitors."
                )
            else:
                findings.append(
                    f"Limited differentiation ({overall}%) — the startup is "
                    "closely clustered with competitors on key axes."
                )

        # Vanity axis findings
        for view in _as_list(positioning_scores.get("views")):
            view = _as_dict(view)
            if view.get("x_axis_vanity_flag") or view.get("y_axis_vanity_flag"):
                findings.append(
                    f"Vanity axis detected in {view.get('view_id', '?')} view — "
                    "axis may not reveal meaningful differentiation."
                )

        # Stress-test findings
        claims = _as_list(positioning_scores.get("differentiation_claims"))
        holds = sum(1 for c in claims if _as_dict(c).get("verdict") == "holds")
        partial = sum(1 for c in claims if _as_dict(c).get("verdict") == "partially_holds")
        fails = sum(1 for c in claims if _as_dict(c).get("verdict") == "does_not_hold")
        if claims:
            findings.append(
                f"Differentiation claims: {holds} hold, {partial} partially hold, "
                f"{fails} do not hold (of {len(claims)} tested)."
            )

    # From moat scores
    if moat_scores is not None and not _is_stub(moat_scores):
        startup = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        defensibility = startup.get("overall_defensibility")
        if defensibility == "high":
            findings.append("High defensibility — the startup has multiple strong moats.")
        elif defensibility == "moderate":
            findings.append("Moderate defensibility — moats exist but need strengthening.")
        elif defensibility == "low":
            findings.append(
                "Low defensibility — the startup lacks meaningful competitive moats. "
                "This is a significant risk for investors."
            )

    # From checklist
    if checklist is not None and not _is_stub(checklist):
        score = checklist.get("score_pct")
        if isinstance(score, (int, float)):
            if score >= 80:
                findings.append(f"Analysis quality score of {score}% indicates a thorough competitive analysis.")
            elif score >= 60:
                findings.append(f"Analysis quality score of {score}% — some gaps remain in the competitive analysis.")
            else:
                findings.append(
                    f"Analysis quality score of {score}% — significant gaps in the competitive analysis need attention."
                )

    if not findings:
        lines.append("No key findings generated.\n")
    else:
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. {f}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_warnings(warnings: list[dict[str, Any]]) -> str:
    """Validation warnings from cross-artifact checks."""
    # Only show medium+ warnings in the report
    reportable = [w for w in warnings if w.get("severity") in ("high", "medium", "acknowledged")]
    if not reportable:
        return ""

    sev_icons = {
        "high": "!!!",
        "medium": "!!",
        "acknowledged": "~",
        "low": "i",
        "info": "~",
    }
    lines = ["## Warnings\n"]
    for w in reportable:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main composition
# ---------------------------------------------------------------------------


def compose(dir_path: str) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    # Normalize positioning.json before validation (best-effort)
    positioning_raw = artifacts.get("positioning.json")
    if _usable(positioning_raw):
        _normalize_positioning(positioning_raw)

    artifacts_loaded = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # Apply accepted_warnings from positioning.json (medium-severity only)
    positioning = artifacts.get("positioning.json")
    if _usable(positioning):
        acceptances: list[dict[str, Any]] = []
        for aw in _as_list(positioning.get("accepted_warnings")):
            aw = _as_dict(aw)
            code = aw.get("code", "")
            match_str = aw.get("match", "")
            reason = aw.get("reason", "")
            if not code or not match_str:
                print(
                    "Warning: accepted_warnings entry missing 'code' or 'match' — skipped",
                    file=sys.stderr,
                )
                continue
            if not isinstance(reason, str) or not reason.strip():
                print(
                    f"Warning: accepted_warnings entry for '{code}' missing 'reason' — skipped",
                    file=sys.stderr,
                )
                continue
            if code in WARNING_SEVERITY and WARNING_SEVERITY[code] in ACCEPTIBLE_SEVERITIES:
                acceptances.append({"code": code, "reason": reason, "match": match_str})
            elif code in WARNING_SEVERITY:
                print(
                    f"Warning: cannot accept high-severity code '{code}' — ignored",
                    file=sys.stderr,
                )
        for w in warnings:
            for acc in acceptances:
                if w["code"] == acc["code"] and acc["match"].lower() in w.get("message", "").lower():
                    w["severity"] = "acknowledged"
                    w["acknowledged"] = True
                    w["acknowledge_reason"] = acc["reason"]
                    w["message"] += f" [Accepted: {acc['reason']}]"
                    break

    # Extract data for rendering (treat corrupt as None)
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    product_profile = _render_safe(artifacts.get("product_profile.json"))
    landscape = _render_safe(artifacts.get("landscape.json"))
    positioning_safe = _render_safe(artifacts.get("positioning.json"))
    moat_scores = _render_safe(artifacts.get("moat_scores.json"))
    positioning_scores = _render_safe(artifacts.get("positioning_scores.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))

    # Assemble report sections
    sections = [
        _section_title(product_profile, landscape),
        _section_executive_summary(product_profile, positioning_scores, moat_scores, checklist),
        _section_competitor_landscape(landscape),
        _section_positioning(positioning_scores),
        _section_moat_assessment(moat_scores),
        _section_stress_test(positioning_scores),
        _section_key_findings(positioning_scores, moat_scores, checklist),
        _section_warnings(warnings),
    ]

    report_markdown = "\n".join(s for s in sections if s)
    report_markdown += (
        "\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Competitive Positioning Coach*\n"
    )

    # Build metadata
    company_name = "Unknown"
    if product_profile is not None and not _is_stub(product_profile):
        company_name = product_profile.get("company_name", "Unknown")

    input_mode = "unknown"
    if landscape is not None and not _is_stub(landscape):
        input_mode = landscape.get("input_mode", "unknown")
    elif product_profile is not None and not _is_stub(product_profile):
        input_mode = product_profile.get("input_mode", "unknown")

    competitor_count = 0
    if landscape is not None and not _is_stub(landscape):
        competitor_count = len(_as_list(landscape.get("competitors")))

    research_depth = "unknown"
    if landscape is not None and not _is_stub(landscape):
        research_depth = landscape.get("research_depth", "unknown")

    assessment_mode = "unknown"
    if positioning_safe is not None and not _is_stub(positioning_safe):
        assessment_mode = positioning_safe.get("assessment_mode", "unknown")
    if assessment_mode == "unknown" and landscape is not None and not _is_stub(landscape):
        assessment_mode = landscape.get("assessment_mode", "unknown")

    founder_override_count = 0
    if positioning_safe is not None and not _is_stub(positioning_safe):
        founder_override_count = _count_founder_overrides(positioning_safe)

    # Extract run_id from first usable artifact
    run_id = ""
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if _usable(data):
            rid = _as_dict(data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_id = rid
                break

    # Scoring summary
    checklist_score_pct = 0.0
    if checklist is not None and not _is_stub(checklist):
        checklist_score_pct = checklist.get("score_pct", 0.0)

    overall_differentiation = 0.0
    if positioning_scores is not None and not _is_stub(positioning_scores):
        overall_differentiation = positioning_scores.get("overall_differentiation", 0.0)

    startup_defensibility = "unknown"
    if moat_scores is not None and not _is_stub(moat_scores):
        startup_data = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        startup_defensibility = startup_data.get("overall_defensibility", "unknown")

    # Stderr summary
    print(
        f"Artifacts loaded: {len(artifacts_loaded)}/{len(all_names)}",
        file=sys.stderr,
    )
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        low = [w for w in warnings if w["severity"] == "low"]
        info = [w for w in warnings if w["severity"] == "info"]
        ack = [w for w in warnings if w["severity"] == "acknowledged"]
        print(
            f"Warnings: {len(high)} high, {len(medium)} medium, "
            f"{len(low)} low, {len(info)} info, {len(ack)} acknowledged",
            file=sys.stderr,
        )
        for w in warnings:
            print(
                f"  [{w['severity'].upper()}] {w['code']}: {w['message']}",
                file=sys.stderr,
            )
    else:
        print("No warnings.", file=sys.stderr)

    return {
        "report_markdown": report_markdown,
        "metadata": {
            "run_id": run_id,
            "company_name": company_name,
            "analysis_date": date.today().isoformat(),
            "input_mode": input_mode,
            "competitor_count": competitor_count,
            "research_depth": research_depth,
            "assessment_mode": assessment_mode,
            "founder_override_count": founder_override_count,
        },
        "warnings": warnings,
        "artifacts_loaded": artifacts_loaded,
        "scoring_summary": {
            "checklist_score_pct": checklist_score_pct,
            "overall_differentiation": overall_differentiation,
            "startup_defensibility": startup_defensibility,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose competitive positioning report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any high-severity warnings",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    result = compose(args.dir)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"

    _write_output(
        out,
        args.output,
        summary={
            "warnings": len(result["warnings"]),
            "artifacts_loaded": len(result["artifacts_loaded"]),
        },
    )

    if args.strict:
        blocking = [w for w in result["warnings"] if w["severity"] == "high"]
        if blocking:
            print(
                "STRICT MODE: Exiting with code 1 due to high-severity warnings",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
