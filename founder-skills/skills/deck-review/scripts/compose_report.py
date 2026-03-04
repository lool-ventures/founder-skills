#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose deck review report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./deck-review-acme-corp/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, TypeGuard

# Canonical warning severity map.
# High severity = agent must fix before presenting report.
# Medium severity = include in report's Warnings section.
_CORRUPT: dict[str, Any] = {"__corrupt__": True}
KNOWN_STAGES = {"pre_seed", "seed", "series_a"}

WARNING_SEVERITY: dict[str, str] = {
    # High — structural integrity violations
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "CHECKLIST_FAILURES_CRITICAL": "high",
    # Medium — quality concerns worth surfacing
    "STAGE_MISMATCH": "medium",
    "SLIDE_COUNT_EXTREME": "medium",
    "UNCITED_CRITIQUE": "medium",
    "AI_CRITERIA_SKIPPED": "medium",
    # Low — minor notes
    "STAGE_OUT_OF_SCOPE": "low",
}

ACCEPTIBLE_SEVERITIES = {"medium"}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "CHECKLIST_FAILURES_CRITICAL": "Checklist Failures (Critical)",
    "STAGE_MISMATCH": "Stage Mismatch",
    "SLIDE_COUNT_EXTREME": "Slide Count",
    "UNCITED_CRITIQUE": "Uncited Critique",
    "AI_CRITERIA_SKIPPED": "AI Criteria Skipped",
    "STAGE_OUT_OF_SCOPE": "Stage Out of Scope",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


REQUIRED_ARTIFACTS = [
    "deck_inventory.json",
    "stage_profile.json",
    "slide_reviews.json",
    "checklist.json",
]
OPTIONAL_ARTIFACTS: list[str] = []  # No optional artifacts for deck review


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


def _warn(code: str, message: str) -> dict[str, str]:
    """Create a warning dict with code, message, and severity."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    inventory = artifacts.get("deck_inventory.json")
    profile = artifacts.get("stage_profile.json")
    reviews = artifacts.get("slide_reviews.json")
    checklist = artifacts.get("checklist.json")

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 3. CHECKLIST_FAILURES_CRITICAL — more than 10 failed items
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        fail_count = summary.get("fail", 0)
        if fail_count > 10:
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES_CRITICAL",
                    f"Checklist has {fail_count} failures (>10 — critical threshold)",
                )
            )

    # 4. STAGE_MISMATCH — inventory signals suggest different stage than profile
    if _usable(inventory) and _usable(profile):
        claimed = (inventory.get("claimed_stage") or "").lower().replace("-", "_").replace(" ", "_")
        detected = (profile.get("detected_stage") or "").lower().replace("-", "_").replace(" ", "_")
        # Only flag when both exist and differ
        if claimed and detected and claimed != detected:
            warnings.append(
                _warn(
                    "STAGE_MISMATCH",
                    f"Deck claims '{claimed}' but analysis detected '{detected}'",
                )
            )

    # 5. STAGE_OUT_OF_SCOPE — check both detected and claimed stage
    out_of_scope_stages: list[str] = []
    if _usable(profile):
        detected = (profile.get("detected_stage") or "").lower().replace("-", "_").replace(" ", "_")
        if detected and detected not in KNOWN_STAGES:
            out_of_scope_stages.append(detected)
    if _usable(inventory):
        claimed = (inventory.get("claimed_stage") or "").lower().replace("-", "_").replace(" ", "_")
        if claimed and claimed not in KNOWN_STAGES and claimed not in out_of_scope_stages:
            out_of_scope_stages.append(claimed)
    if out_of_scope_stages:
        stages_str = ", ".join(out_of_scope_stages)
        warnings.append(
            _warn(
                "STAGE_OUT_OF_SCOPE",
                f"Stage '{stages_str}' is outside calibrated range "
                f"(pre_seed, seed, series_a). Results may be less precise.",
            )
        )

    # 6. SLIDE_COUNT_EXTREME — fewer than 5 or more than 20
    if _usable(inventory):
        total = inventory.get("total_slides", 0)
        if total < 5:
            warnings.append(
                _warn(
                    "SLIDE_COUNT_EXTREME",
                    f"Deck has only {total} slides (<5 — too few for a complete pitch)",
                )
            )
        elif total > 20:
            warnings.append(
                _warn(
                    "SLIDE_COUNT_EXTREME",
                    f"Deck has {total} slides (>20 — sharp engagement drop-off after ~18)",
                )
            )

    # 7. UNCITED_CRITIQUE — slide review has weaknesses without best_practice_refs
    if _usable(reviews):
        for review in _as_list(reviews.get("reviews")):
            weaknesses = _as_list(review.get("weaknesses"))
            refs = _as_list(review.get("best_practice_refs"))
            if weaknesses and not refs:
                warnings.append(
                    _warn(
                        "UNCITED_CRITIQUE",
                        f"Slide {review.get('slide_number', '?')} has critiques without best-practice citations",
                    )
                )

    # 8. AI_CRITERIA_SKIPPED — AI company detected but AI criteria all not_applicable
    if _usable(profile) and _usable(checklist):
        is_ai = profile.get("is_ai_company", False)
        if is_ai:
            ai_ids = {
                "ai_retention_rebased",
                "ai_cost_to_serve_shown",
                "ai_defensibility_beyond_model",
                "ai_responsible_controls",
            }
            items = _as_list(checklist.get("items"))
            ai_items = [i for i in items if i.get("id") in ai_ids]
            if ai_items and all(i.get("status") == "not_applicable" for i in ai_items):
                warnings.append(
                    _warn(
                        "AI_CRITERIA_SKIPPED",
                        "Company detected as AI-first but all AI criteria marked not_applicable",
                    )
                )

    return warnings


def _section_title(inventory: dict[str, Any] | None) -> str:
    """Report title."""
    if inventory is None:
        return "# Pitch Deck Review\n\n*No deck inventory found.*\n"
    company = inventory.get("company_name", "Unknown Company")
    date = inventory.get("review_date", "unknown date")
    total = inventory.get("total_slides", "?")
    fmt = inventory.get("input_format", "unknown")
    return (
        f"# Pitch Deck Review: {company}\n\n"
        f"**Date:** {date} | **Slides:** {total} | **Format:** {fmt}  \n"
        "**Generated by:** [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Deck Review Agent\n"
    )


def _section_executive_summary(
    profile: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
) -> str:
    """Executive summary with stage, score, and one-line verdict."""
    lines = ["## Executive Summary\n"]

    if profile is not None and not _is_stub(profile):
        stage = (profile.get("detected_stage") or "unknown").replace("_", " ").title()
        confidence = profile.get("confidence", "unknown")
        is_ai = profile.get("is_ai_company", False)
        lines.append(f"**Stage:** {stage} (confidence: {confidence})")
        if is_ai:
            lines.append("**AI Company:** Yes")

    if inventory is not None and not _is_stub(inventory):
        total = inventory.get("total_slides", "?")
        lines.append(f"**Slide Count:** {total}")

    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        score = summary.get("score_pct", 0)
        status = summary.get("overall_status", "unknown")
        pass_c = summary.get("pass", 0)
        fail_c = summary.get("fail", 0)
        warn_c = summary.get("warn", 0)
        na_c = summary.get("not_applicable", 0)

        status_label = {
            "strong": "Strong — your deck is investor-ready with minor polish",
            "solid": "Solid — good foundation, a few targeted improvements will make this shine",
            "needs_work": "Needs Work — the business may be strong but the deck has gaps to close before sending",
            "major_revision": "Major Revision — worth reworking before it goes out; see priority fixes below",
        }.get(status, status)

        lines.append(f"**Overall Score:** {score}% — {status_label}")
        lines.append(f"**Breakdown:** {pass_c} pass, {fail_c} fail, {warn_c} warn, {na_c} N/A")

    return "\n".join(lines) + "\n"


def _section_stage_context(profile: dict[str, Any] | None) -> str:
    """Stage-specific context for what investors expect."""
    if profile is None or _is_stub(profile):
        return "## Stage Context\n\n*No stage profile available.*\n"

    stage = profile.get("detected_stage", "unknown")
    benchmarks = _as_dict(profile.get("stage_benchmarks"))
    evidence = _as_list(profile.get("evidence"))

    lines = ["## Stage Context\n"]
    stage_label = stage.replace("_", " ").title()
    lines.append(f"**Detected Stage:** {stage_label}\n")

    if evidence:
        lines.append("**Evidence:**")
        for e in evidence:
            lines.append(f"- {e}")
        lines.append("")

    if benchmarks:
        round_range = benchmarks.get("round_size_range", "N/A")
        traction = benchmarks.get("expected_traction", "N/A")
        runway = benchmarks.get("runway_expectation", "N/A")
        lines.append(f"**Typical Round Size:** {round_range}")
        lines.append(f"**Expected Traction:** {traction}")
        lines.append(f"**Runway Expectation:** {runway}")

    lines.append(
        "\n*Stage benchmarks are reference data from industry standards "
        "(Sequoia, DocSend, YC, a16z, Carta). They represent typical ranges, not recommendations.*"
    )

    return "\n".join(lines) + "\n"


def _section_slide_feedback(reviews: dict[str, Any] | None) -> str:
    """Per-slide feedback with strengths, areas to improve, and recommendations."""
    if reviews is None or _is_stub(reviews):
        return "## Slide-by-Slide Feedback\n\n*No slide reviews available.*\n"

    lines = ["## Slide-by-Slide Feedback\n"]
    lines.append(
        "*Each slide assessment is the agent's evaluation against best-practice frameworks. "
        "Strengths and weaknesses are the agent's analysis, not investor quotes.*\n"
    )

    for review in _as_list(reviews.get("reviews")):
        num = review.get("slide_number", "?")
        maps_to = review.get("maps_to", "unknown")
        lines.append(f"### Slide {num} ({maps_to})\n")

        strengths = _as_list(review.get("strengths"))
        if strengths:
            lines.append("**What's working:**")
            for s in strengths:
                lines.append(f"- {s}")

        weaknesses = _as_list(review.get("weaknesses"))
        if weaknesses:
            lines.append("**What investors will question:**")
            for w in weaknesses:
                lines.append(f"- {w}")

        recommendations = _as_list(review.get("recommendations"))
        if recommendations:
            lines.append("")
            lines.append("**How to fix:**")
            for r in recommendations:
                lines.append(f"- {r}")

        lines.append("")

    # Missing slides
    missing = _as_list(reviews.get("missing_slides"))
    if missing:
        lines.append("### Slides to Add\n")
        lines.append("Investors at your stage will expect these:\n")
        for m in missing:
            imp = m.get("importance", "important")
            expected = m.get("expected_type", "unknown")
            rec = m.get("recommendation", "")
            lines.append(f"- **[{imp.upper()}]** {expected}: {rec}")
        lines.append("")

    # Overall narrative
    narrative = reviews.get("overall_narrative_assessment", "")
    if narrative:
        lines.append(f"### Overall Narrative\n\n{narrative}\n")

    return "\n".join(lines) + "\n"


def _section_checklist(checklist: dict[str, Any] | None) -> str:
    """Checklist results by category — helps founders see where they're strong and where to focus."""
    if checklist is None or _is_stub(checklist):
        return "## Checklist Results\n\n*No checklist data available.*\n"

    summary = _as_dict(checklist.get("summary"))
    by_cat = _as_dict(summary.get("by_category"))

    lines = ["## Checklist Results\n"]

    # Category summary table
    lines.append("| Category | Pass | Fail | Warn | N/A |")
    lines.append("|----------|------|------|------|-----|")
    for cat, counts in by_cat.items():
        lines.append(
            f"| {cat} | {counts.get('pass', 0)} | {counts.get('fail', 0)} "
            f"| {counts.get('warn', 0)} | {counts.get('not_applicable', 0)} |"
        )
    lines.append("")

    # Failed items detail
    failed = _as_list(summary.get("failed_items"))
    if failed:
        lines.append("### Areas That Need Attention\n")
        for f in failed:
            notes = f.get("notes", "")
            evidence = f.get("evidence", "")
            lines.append(f"- **{f.get('label', f.get('id', '?'))}** ({f.get('category', '?')})")
            if notes:
                lines.append(f"  - {notes}")
            if evidence:
                lines.append(f"  - *Basis: {evidence}*")
        lines.append("")

    # Warned items detail
    warned = _as_list(summary.get("warned_items"))
    if warned:
        lines.append("### Items Needing Attention\n")
        for w in warned:
            notes = w.get("notes", "")
            lines.append(f"- **{w.get('label', w.get('id', '?'))}** ({w.get('category', '?')})")
            if notes:
                lines.append(f"  - {notes}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_priority_fixes(
    checklist: dict[str, Any] | None,
    reviews: dict[str, Any] | None,
) -> str:
    """Top 5 priority fixes — the highest-leverage changes the founder can make."""
    lines = ["## Top 5 Priority Fixes\n"]
    lines.append("These are the changes that will have the biggest impact on investor response:\n")

    fixes: list[str] = []

    # Draw from failed checklist items (highest priority)
    if checklist is not None and not _is_stub(checklist):
        for f in _as_list(_as_dict(checklist.get("summary")).get("failed_items")):
            label = f.get("label", f.get("id", "?"))
            notes = f.get("notes", "")
            fix = f"{label}: {notes}" if notes else label
            fixes.append(fix)

    # Draw from missing slides
    if reviews is not None and not _is_stub(reviews):
        for m in reviews.get("missing_slides", []):
            if m.get("importance") == "critical":
                fixes.append(f"Add missing {m.get('expected_type', 'slide')}: {m.get('recommendation', '')}")

    # Draw from warned items
    if checklist is not None and not _is_stub(checklist):
        for w in _as_list(_as_dict(checklist.get("summary")).get("warned_items")):
            label = w.get("label", w.get("id", "?"))
            notes = w.get("notes", "")
            fix = f"{label}: {notes}" if notes else label
            fixes.append(fix)

    if not fixes:
        lines.append("No critical fixes identified.\n")
    else:
        for i, fix in enumerate(fixes[:5], 1):
            lines.append(f"{i}. {fix}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Validation warnings from cross-artifact checks."""
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


def _section_full_checklist(checklist: dict[str, Any] | None) -> str:
    """Appendix: full checklist table."""
    if checklist is None or _is_stub(checklist):
        return ""

    items = _as_list(checklist.get("items"))
    if not items:
        return ""

    lines = ["## Appendix: Full Checklist\n"]
    lines.append("| # | Category | Criterion | Status |")
    lines.append("|---|----------|-----------|--------|")

    status_icons = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "not_applicable": "N/A"}

    for i, item in enumerate(items, 1):
        cat = item.get("category", "?")
        label = item.get("label", item.get("id", "?"))
        status = status_icons.get(item.get("status", "?"), "?")
        lines.append(f"| {i} | {cat} | {label} | {status} |")

    return "\n".join(lines) + "\n"


def compose(dir_path: str) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    artifacts_found = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in all_names if artifacts[n] is None]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # Apply accepted_warnings from stage_profile (medium-severity only)
    profile = artifacts.get("stage_profile.json")
    if _usable(profile):
        acceptances: list[dict[str, str]] = []
        for aw in _as_list(profile.get("accepted_warnings")):
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

    status = "clean" if not warnings else "warnings"

    # Assemble report sections — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inventory = _render_safe(artifacts.get("deck_inventory.json"))
    stage_profile = _render_safe(artifacts.get("stage_profile.json"))
    slide_reviews = _render_safe(artifacts.get("slide_reviews.json"))
    checklist_data = _render_safe(artifacts.get("checklist.json"))

    sections = [
        _section_title(inventory),
        _section_executive_summary(stage_profile, checklist_data, inventory),
        _section_stage_context(stage_profile),
        _section_slide_feedback(slide_reviews),
        _section_checklist(checklist_data),
        _section_priority_fixes(checklist_data, slide_reviews),
        _section_warnings(warnings),
        _section_full_checklist(checklist_data),
    ]

    report_markdown = "\n".join(sections)
    report_markdown += (
        "\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Deck Review Agent*\n"
    )

    # Stderr summary
    print(f"Artifacts found: {len(artifacts_found)}/{len(all_names)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        low = [w for w in warnings if w["severity"] == "low"]
        info = [w for w in warnings if w["severity"] == "info"]
        print(f"Warnings: {len(high)} high, {len(medium)} medium, {len(low)} low, {len(info)} info", file=sys.stderr)
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

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose deck review report from artifacts")
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
