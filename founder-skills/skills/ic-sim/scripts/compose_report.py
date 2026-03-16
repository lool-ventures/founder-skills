#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose IC simulation report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./ic-sim-acme-corp/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, TypeGuard

# Canonical warning severity map.
# high = must fix before presenting, medium = warn in report,
# low = note in appendix, info = note in report metadata.
_CORRUPT: dict[str, Any] = {"__corrupt__": True}
KNOWN_STAGES = {"pre_seed", "seed", "series_a"}

WARNING_SEVERITY: dict[str, str] = {
    # High — structural integrity violations
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "BLOCKING_CONFLICT": "high",
    "ORPHANED_CONFLICT": "high",
    "VERDICT_SCORE_MISMATCH": "high",
    "INVALID_PARTNER_COUNT": "high",
    # Medium — quality concerns worth surfacing
    "PARTNER_UNANIMITY": "medium",
    "ZERO_APPLICABLE": "medium",
    "STALE_IMPORT": "medium",
    "LOW_EVIDENCE": "medium",
    "FUND_VALIDATION_ERROR": "medium",
    "CONFLICT_CHECK_VALIDATION_ERROR": "medium",
    "SCORE_DIMENSIONS_VALIDATION_ERROR": "medium",
    "DEGRADED_ASSESSMENT": "medium",
    "CONSENSUS_SCORE_MISMATCH": "medium",
    "UNANIMOUS_VERDICT_MISMATCH": "medium",
    "SHALLOW_ASSESSMENT": "medium",
    "HIGH_NA_COUNT": "medium",
    "INCOMPLETE_PORTFOLIO_REVIEW": "medium",
    # Low — minor notes
    "SCHEMA_DRIFT": "low",
    "STAGE_OUT_OF_SCOPE": "low",
    # Info — transparency, no action needed
    "PARTNER_CONVERGENCE": "info",
    "SEQUENTIAL_FALLBACK": "info",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "BLOCKING_CONFLICT": "Blocking Conflict",
    "ORPHANED_CONFLICT": "Orphaned Conflict",
    "VERDICT_SCORE_MISMATCH": "Verdict/Score Mismatch",
    "PARTNER_UNANIMITY": "Partner Unanimity",
    "ZERO_APPLICABLE": "Zero Applicable Dimensions",
    "STALE_IMPORT": "Stale Import",
    "LOW_EVIDENCE": "Low Evidence",
    "FUND_VALIDATION_ERROR": "Fund Validation Error",
    "DEGRADED_ASSESSMENT": "Degraded Assessment",
    "CONSENSUS_SCORE_MISMATCH": "Consensus/Score Verdict Mismatch",
    "UNANIMOUS_VERDICT_MISMATCH": "Unanimous Verdict Mismatch",
    "SHALLOW_ASSESSMENT": "Shallow Assessment",
    "HIGH_NA_COUNT": "High N/A Count",
    "SCHEMA_DRIFT": "Schema Drift",
    "STAGE_OUT_OF_SCOPE": "Stage Out of Scope",
    "PARTNER_CONVERGENCE": "Partner Convergence",
    "SEQUENTIAL_FALLBACK": "Sequential Fallback",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


REQUIRED_ARTIFACTS = [
    "startup_profile.json",
    "fund_profile.json",
    "conflict_check.json",
    "discussion.json",
    "score_dimensions.json",
]

OPTIONAL_ARTIFACTS = [
    "prior_artifacts.json",
    "partner_assessment_visionary.json",
    "partner_assessment_operator.json",
    "partner_assessment_analyst.json",
]

PARTNER_ASSESSMENT_FILES = [
    "partner_assessment_visionary.json",
    "partner_assessment_operator.json",
    "partner_assessment_analyst.json",
]

# Expected top-level keys per artifact for SCHEMA_DRIFT detection.
EXPECTED_KEYS: dict[str, set[str]] = {
    "startup_profile.json": {
        "company_name",
        "simulation_date",
        "stage",
        "one_liner",
        "sector",
        "geography",
        "business_model",
        "funding_history",
        "current_raise",
        "key_metrics",
        "materials_provided",
        # Common agent additions
        "founded",
        "team",
        "website",
        "competitors",
        "product_description",
        "team_highlights",
    },
    "fund_profile.json": {
        "fund_name",
        "mode",
        "thesis_areas",
        "check_size_range",
        "stage_focus",
        "archetypes",
        "portfolio",
        "sources",
        "validation",
        "accepted_warnings",
    },
    "conflict_check.json": {
        "portfolio_size",
        "conflicts",
        "summary",
        "validation",
    },
    "discussion.json": {
        "assessment_mode",
        "partner_verdicts",
        "debate_sections",
        "consensus_verdict",
        "key_concerns",
        "diligence_requirements",
        "assessment_mode_intentional",
    },
    "score_dimensions.json": {
        "items",
        "summary",
    },
    "prior_artifacts.json": {
        "imported",
        "skipped",
        "reason",
    },
}

REQUIRED_KEYS: dict[str, set[str]] = {
    "startup_profile.json": {
        "company_name",
        "stage",
        "one_liner",
        "sector",
    },
    "fund_profile.json": {
        "fund_name",
        "mode",
        "thesis_areas",
        "check_size_range",
        "stage_focus",
        "archetypes",
        "portfolio",
    },
    "conflict_check.json": {
        "portfolio_size",
        "conflicts",
    },
    "discussion.json": {
        "assessment_mode",
        "partner_verdicts",
        "consensus_verdict",
    },
    "score_dimensions.json": {
        "items",
        "summary",
    },
}

# Verdict-to-score-range mapping for VERDICT_SCORE_MISMATCH check.
VERDICT_SCORE_RANGES: dict[str, tuple[float, float]] = {
    "invest": (75.0, 100.0),
    "more_diligence": (50.0, 74.9),
    "pass": (0.0, 49.9),
}


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


def _fmt_number(val: Any, fallback: str = "?") -> str:
    """Format a number with commas, or return fallback for non-numeric values."""
    if val is None:
        return fallback
    try:
        return f"{val:,}"
    except (TypeError, ValueError):
        return str(val)


def _normalize_ws(s: str) -> str:
    """Normalize whitespace for comparison: collapse runs and strip."""
    return re.sub(r"\s+", " ", s).strip()


def _normalize_company(name: str) -> str:
    """Normalize company name for matching: strip legal suffixes, lowercase, collapse whitespace."""
    name = name.strip().lower()
    for suffix in (" inc.", " inc", " llc", " ltd.", " ltd", " corp.", " corp"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"\s+", " ", name).strip()


def _normalize_verdict(v: Any) -> str:
    """Normalize a verdict string for comparison. Returns '' for non-string/empty."""
    if not isinstance(v, str) or not v.strip():
        return ""
    return v.strip().lower().replace("-", "_").replace(" ", "_")


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    fund_profile = artifacts.get("fund_profile.json")
    conflict_check = artifacts.get("conflict_check.json")
    discussion = artifacts.get("discussion.json")
    score_dims = artifacts.get("score_dimensions.json")
    prior = artifacts.get("prior_artifacts.json")

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 2. BLOCKING_CONFLICT
    if _usable(conflict_check):
        summary = _as_dict(conflict_check.get("summary"))
        if summary.get("has_blocking_conflict") is True:
            warnings.append(
                _warn("BLOCKING_CONFLICT", "Portfolio has a blocking conflict — cannot proceed with investment")
            )

    # 3. ORPHANED_CONFLICT — conflict company not found in fund_profile portfolio
    if _usable(conflict_check) and _usable(fund_profile):
        portfolio_names = {
            _normalize_company(entry.get("name", ""))
            for entry in _as_list(fund_profile.get("portfolio"))
            if isinstance(entry, dict)
        }
        for conflict in _as_list(conflict_check.get("conflicts")):
            if not isinstance(conflict, dict):
                continue
            company = conflict.get("company", "")
            if _normalize_company(company) not in portfolio_names:
                warnings.append(
                    _warn(
                        "ORPHANED_CONFLICT",
                        f"Conflict company '{company}' not in fund_profile.portfolio"
                        " — cross-artifact identity mismatch",
                    )
                )

    # 3b. INCOMPLETE_PORTFOLIO_REVIEW — conflict check didn't cover all portfolio companies
    if _usable(conflict_check) and _usable(fund_profile):
        portfolio = _as_list(fund_profile.get("portfolio"))
        portfolio_size = conflict_check.get("portfolio_size", 0)
        if isinstance(portfolio_size, int) and portfolio_size < len(portfolio):
            not_assessed = len(portfolio) - portfolio_size
            warnings.append(
                _warn(
                    "INCOMPLETE_PORTFOLIO_REVIEW",
                    f"Conflict check covered {portfolio_size} companies but fund has"
                    f" {len(portfolio)} — {not_assessed} not assessed",
                )
            )

    # 4. VERDICT_SCORE_MISMATCH
    if _usable(score_dims):
        score_summary = _as_dict(score_dims.get("summary"))
        score_warnings = _as_list(score_summary.get("warnings"))
        conviction_score = score_summary.get("conviction_score", 0.0)
        verdict = score_summary.get("verdict", "")

        # Suppress if ZERO_APPLICABLE_DIMENSIONS present
        has_zero_applicable = "ZERO_APPLICABLE_DIMENSIONS" in score_warnings

        if not has_zero_applicable and verdict in VERDICT_SCORE_RANGES:
            low, high = VERDICT_SCORE_RANGES[verdict]
            if not (low <= conviction_score <= high) and verdict != "hard_pass":
                warnings.append(
                    _warn(
                        "VERDICT_SCORE_MISMATCH",
                        f"Verdict '{verdict}' does not match score {conviction_score}% "
                        f"(expected range: {low}%-{high}%)",
                    )
                )

    # 4b. CONSENSUS_SCORE_MISMATCH
    if _usable(discussion) and _usable(score_dims):
        consensus_v = _normalize_verdict(discussion.get("consensus_verdict"))
        score_v = _normalize_verdict(_as_dict(score_dims.get("summary")).get("verdict"))
        if consensus_v and score_v and consensus_v != score_v:
            warnings.append(
                _warn(
                    "CONSENSUS_SCORE_MISMATCH",
                    f"Discussion consensus verdict '{discussion.get('consensus_verdict')}' "
                    f"differs from score verdict '{_as_dict(score_dims.get('summary')).get('verdict')}' "
                    "— review for consistency",
                )
            )

    # 4c. UNANIMOUS_VERDICT_MISMATCH
    # Only fires when ALL partners share one polarity but consensus has
    # the opposite. Individual dissent (1-2 out of 3) is normal and ignored.
    _POSITIVE_VERDICTS = {"invest", "more_diligence"}
    _NEGATIVE_VERDICTS = {"pass", "hard_pass"}
    if _usable(discussion):
        consensus = _normalize_verdict(discussion.get("consensus_verdict"))
        partner_verdicts_list = [
            _normalize_verdict(pv.get("verdict"))
            for pv in _as_list(discussion.get("partner_verdicts"))
            if isinstance(pv, dict) and pv.get("verdict")
        ]
        if partner_verdicts_list:
            all_positive = all(v in _POSITIVE_VERDICTS for v in partner_verdicts_list)
            all_negative = all(v in _NEGATIVE_VERDICTS for v in partner_verdicts_list)
            consensus_positive = consensus in _POSITIVE_VERDICTS
            consensus_negative = consensus in _NEGATIVE_VERDICTS
            # Check opposite polarity (e.g., all positive vs negative consensus)
            opposite_polarity = (all_positive and consensus_negative) or (all_negative and consensus_positive)
            # Also check unanimous same-verdict mismatch (e.g., all "more_diligence" vs consensus "invest")
            unanimous_exact = len(set(partner_verdicts_list)) == 1 and partner_verdicts_list[0] != consensus
            if opposite_polarity or unanimous_exact:
                if opposite_polarity:
                    detail = (
                        f"{'positive' if all_positive else 'negative'} "
                        f"but consensus is '{discussion.get('consensus_verdict')}' "
                        f"({'negative' if consensus_negative else 'positive'})"
                    )
                else:
                    detail = (
                        f"unanimously '{partner_verdicts_list[0]}' "
                        f"but consensus is '{discussion.get('consensus_verdict')}'"
                    )
                warnings.append(
                    _warn(
                        "UNANIMOUS_VERDICT_MISMATCH",
                        (
                            f"All {len(partner_verdicts_list)} partners are {detail}"
                            " — partner_verdicts or consensus_verdict likely not "
                            "updated after debate"
                        ),
                    )
                )

    # 5. PARTNER_UNANIMITY / PARTNER_CONVERGENCE
    if _usable(discussion):
        partner_verdicts = _as_list(discussion.get("partner_verdicts"))
        assessment_mode = discussion.get("assessment_mode", "sequential")

        if len(partner_verdicts) != 3:
            warnings.append(_warn("INVALID_PARTNER_COUNT", f"Expected 3 partner verdicts, got {len(partner_verdicts)}"))

        if len(partner_verdicts) == 3:
            verdicts_list = [pv.get("verdict") for pv in partner_verdicts]
            rationales = [pv.get("rationale", "") for pv in partner_verdicts]

            if len(set(verdicts_list)) == 1:
                # All agree — check for copy-paste rationales
                normalized = [_normalize_ws(r) for r in rationales]
                # Any 2 rationales identical after normalization?
                has_identical = False
                for i in range(len(normalized)):
                    for j in range(i + 1, len(normalized)):
                        if normalized[i] == normalized[j]:
                            has_identical = True
                            break
                    if has_identical:
                        break

                if has_identical:
                    warnings.append(
                        _warn(
                            "PARTNER_UNANIMITY",
                            "All 3 partners agree on verdict AND share identical"
                            " rationales — flags generation collapse",
                        )
                    )
                else:
                    # Convergence: only noteworthy in sub-agent mode
                    if assessment_mode == "sub-agent":
                        warnings.append(
                            _warn(
                                "PARTNER_CONVERGENCE",
                                "All 3 partners independently converged on the same verdict with distinct rationales",
                            )
                        )

    # 6. ZERO_APPLICABLE
    if _usable(score_dims):
        score_warnings = _as_list(_as_dict(score_dims.get("summary")).get("warnings"))
        if "ZERO_APPLICABLE_DIMENSIONS" in score_warnings:
            warnings.append(_warn("ZERO_APPLICABLE", "All dimensions marked not_applicable — score is 0.0"))

    # 7. STALE_IMPORT
    if _usable(prior):
        for imp in _as_list(prior.get("imported")):
            if not isinstance(imp, dict):
                continue
            import_date_str = imp.get("import_date", "")
            if import_date_str:
                try:
                    import_date = datetime.strptime(import_date_str[:10], "%Y-%m-%d")
                    if datetime.now() - import_date > timedelta(days=7):
                        source = imp.get("source_skill", "unknown")
                        warnings.append(
                            _warn(
                                "STALE_IMPORT",
                                f"Imported {source} artifact from {import_date_str} is older than 7 days",
                            )
                        )
                except ValueError:
                    pass

    # 8. LOW_EVIDENCE
    if _usable(score_dims):
        for item in _as_list(score_dims.get("items")):
            if not isinstance(item, dict):
                continue
            if item.get("status") != "not_applicable":
                evidence = item.get("evidence")
                if not evidence or (isinstance(evidence, str) and evidence.strip() == ""):
                    warnings.append(
                        _warn(
                            "LOW_EVIDENCE",
                            f"Dimension '{item.get('id', '?')}' has no evidence field",
                        )
                    )

    # 9. FUND_VALIDATION_ERROR
    if _usable(fund_profile):
        validation = _as_dict(fund_profile.get("validation"))
        if validation.get("status") != "valid":
            errors = _as_list(validation.get("errors"))
            warnings.append(
                _warn(
                    "FUND_VALIDATION_ERROR",
                    f"Fund profile validation failed: {'; '.join(str(e) for e in errors[:3])}",
                )
            )

    # 9b. CONFLICT_CHECK_VALIDATION_ERROR
    if _usable(conflict_check) and "validation" in conflict_check:
        validation = _as_dict(conflict_check.get("validation"))
        if validation.get("status") != "valid":
            errors = _as_list(validation.get("errors"))
            warnings.append(
                _warn(
                    "CONFLICT_CHECK_VALIDATION_ERROR",
                    f"Conflict check validation failed: {'; '.join(str(e) for e in errors[:3])}",
                )
            )

    # 9c. SCORE_DIMENSIONS_VALIDATION_ERROR
    if _usable(score_dims) and "validation" in score_dims:
        validation = _as_dict(score_dims.get("validation"))
        if validation.get("status") != "valid":
            errors = _as_list(validation.get("errors"))
            warnings.append(
                _warn(
                    "SCORE_DIMENSIONS_VALIDATION_ERROR",
                    f"Score dimensions validation failed: {'; '.join(str(e) for e in errors[:3])}",
                )
            )

    # 10. DEGRADED_ASSESSMENT
    if _usable(discussion) and discussion.get("assessment_mode") == "sub-agent":
        for pa_file in PARTNER_ASSESSMENT_FILES:
            if artifacts.get(pa_file) is None:
                warnings.append(
                    _warn(
                        "DEGRADED_ASSESSMENT",
                        f"Sub-agent mode but {pa_file} is missing — indicates sub-agent failure with silent fallback",
                    )
                )

    # 10b. SHALLOW_ASSESSMENT (sub-agent mode only, present files only)
    if _usable(discussion) and discussion.get("assessment_mode") == "sub-agent":
        for pa_file in PARTNER_ASSESSMENT_FILES:
            pa_data = artifacts.get(pa_file)
            if _usable(pa_data):
                issues: list[str] = []
                if len(_as_list(pa_data.get("conviction_points"))) < 2:
                    issues.append("conviction_points < 2")
                if len(_as_list(pa_data.get("key_concerns"))) < 2:
                    issues.append("key_concerns < 2")
                rationale = pa_data.get("rationale", "")
                if not isinstance(rationale, str):
                    rationale = ""
                if len(rationale) < 100:
                    issues.append("rationale < 100 chars")
                if issues:
                    warnings.append(
                        _warn(
                            "SHALLOW_ASSESSMENT",
                            f"{pa_file}: {', '.join(issues)}",
                        )
                    )

    # 10c. HIGH_NA_COUNT
    if _usable(score_dims):
        na_count = sum(
            1
            for item in _as_list(score_dims.get("items"))
            if isinstance(item, dict) and item.get("status") == "not_applicable"
        )
        if na_count > 6:
            warnings.append(
                _warn(
                    "HIGH_NA_COUNT",
                    f"{na_count} of 28 dimensions marked not_applicable — conviction score may be inflated",
                )
            )

    # 11. SCHEMA_DRIFT
    for name, expected in EXPECTED_KEYS.items():
        artifact = artifacts.get(name)
        if _usable(artifact):
            actual_keys = set(artifact.keys())
            extra = actual_keys - expected
            if extra:
                warnings.append(
                    _warn(
                        "SCHEMA_DRIFT",
                        f"{name} has unexpected top-level keys: {sorted(extra)}",
                    )
                )
            required = REQUIRED_KEYS.get(name, set())
            missing = required - actual_keys
            if missing:
                warnings.append(
                    _warn(
                        "SCHEMA_DRIFT",
                        f"{name} missing required top-level keys: {sorted(missing)}",
                    )
                )

    # 12. STAGE_OUT_OF_SCOPE
    startup = artifacts.get("startup_profile.json")
    if _usable(startup):
        stage = (startup.get("stage") or "").lower().replace("-", "_").replace(" ", "_")
        if stage and stage not in KNOWN_STAGES:
            warnings.append(
                _warn(
                    "STAGE_OUT_OF_SCOPE",
                    f"Stage '{stage}' is outside calibrated range "
                    f"(pre_seed, seed, series_a). Results may be less precise.",
                )
            )

    # 13. SEQUENTIAL_FALLBACK
    if (
        _usable(discussion)
        and discussion.get("assessment_mode") == "sequential"
        and not discussion.get("assessment_mode_intentional")
    ):
        warnings.append(
            _warn(
                "SEQUENTIAL_FALLBACK",
                "Assessments generated sequentially (no sub-agents) — not an error, just transparency",
            )
        )

    return warnings


def _section_title(profile: dict[str, Any] | None) -> str:
    """Report title."""
    if profile is None:
        return "# IC Simulation Report\n\n*No startup profile found.*\n"
    company = profile.get("company_name", "Unknown Company")
    date = profile.get("simulation_date", "unknown date")
    stage = (profile.get("stage") or "unknown").replace("_", " ").title()
    return (
        f"# IC Simulation: {company}\n\n"
        f"**Date:** {date} | **Stage:** {stage}  \n"
        "**Generated by:** [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — IC Simulation Agent\n\n"
        "> *This is an AI simulation. Partner verdicts, debate positions, and questions are "
        "generated based on archetype personas and provided materials. They represent plausible "
        "perspectives, not actual VC feedback.*\n"
    )


def _section_executive_summary(
    profile: dict[str, Any] | None,
    score_dims: dict[str, Any] | None,
    discussion: dict[str, Any] | None,
) -> str:
    """Executive summary with verdict, score, and partner split."""
    lines = ["## Executive Summary\n"]

    if profile is not None and not _is_stub(profile):
        lines.append(f"**Company:** {profile.get('company_name', '?')}")
        lines.append(f"**One-liner:** {profile.get('one_liner', '?')}")
        lines.append(f"**Sector:** {profile.get('sector', '?')}")

    if score_dims is not None and not _is_stub(score_dims):
        summary = _as_dict(score_dims.get("summary"))
        score = summary.get("conviction_score", 0)
        verdict = summary.get("verdict", "unknown")
        strong = summary.get("strong_conviction", 0)
        moderate = summary.get("moderate_conviction", 0)
        concern = summary.get("concern", 0)
        db = summary.get("dealbreaker", 0)

        verdict_label = {
            "invest": "Invest — strong enough for a term sheet discussion",
            "more_diligence": "More Diligence — promising but needs more evidence",
            "pass": "Pass — too many concerns to proceed at this time",
            "hard_pass": "Hard Pass — fatal flaw identified",
        }.get(verdict, verdict)

        lines.append(f"**Conviction Score:** {score}% — {verdict_label}")
        lines.append(f"**Breakdown:** {strong} strong, {moderate} moderate, {concern} concern, {db} dealbreaker")

    if discussion is not None and not _is_stub(discussion):
        partner_verdicts = _as_list(discussion.get("partner_verdicts"))
        if partner_verdicts:
            verdict_strs = [
                f"{(pv.get('partner') or '?').title()}: {pv.get('verdict') or '?'}" for pv in partner_verdicts
            ]
            lines.append(f"**Partner Split:** {' | '.join(verdict_strs)}")

    # Consensus/Score verdict mismatch note
    if score_dims is not None and not _is_stub(score_dims) and discussion is not None and not _is_stub(discussion):
        consensus_v = _normalize_verdict(discussion.get("consensus_verdict"))
        score_v = _normalize_verdict(_as_dict(score_dims.get("summary")).get("verdict"))
        if consensus_v and score_v and consensus_v != score_v:
            lines.append("")
            score_verdict = _as_dict(score_dims.get("summary")).get("verdict")
            lines.append(
                f"> **Note:** The IC discussion consensus (*{discussion.get('consensus_verdict')}*) "
                f"differs from the quantitative score verdict (*{score_verdict}*). "
                "This can occur when qualitative debate conclusions override borderline numeric scores."
            )

    return "\n".join(lines) + "\n"


def _section_fund_profile(fund: dict[str, Any] | None) -> str:
    """Fund profile summary."""
    if fund is None or _is_stub(fund):
        return "## Fund Profile\n\n*No fund profile available.*\n"

    lines = ["## Fund Profile\n"]
    lines.append(f"**Fund:** {fund.get('fund_name', '?')}")
    lines.append(f"**Mode:** {fund.get('mode', '?')}")

    thesis = _as_list(fund.get("thesis_areas"))
    if thesis:
        lines.append(f"**Thesis Areas:** {', '.join(str(t) for t in thesis)}")

    check_size = fund.get("check_size_range", {})
    if check_size:
        currency = check_size.get("currency", "USD")
        min_str = _fmt_number(check_size.get("min"))
        max_str = _fmt_number(check_size.get("max"))
        lines.append(f"**Check Size:** {currency} {min_str} - {max_str}")

    archetypes = _as_list(fund.get("archetypes"))
    if archetypes:
        lines.append("\n**Partners:**")
        for arch in archetypes:
            role = arch.get("role", "?").title()
            name = arch.get("name", "?")
            lines.append(f"- **{name}** ({role}): {arch.get('background', '?')}")

    return "\n".join(lines) + "\n"


def _section_conflict_check(conflict: dict[str, Any] | None) -> str:
    """Conflict check results."""
    if conflict is None or _is_stub(conflict):
        return "## Conflict Check\n\n*No conflict check available.*\n"

    summary = _as_dict(conflict.get("summary"))
    lines = ["## Conflict Check\n"]
    lines.append(f"**Portfolio Companies Checked:** {summary.get('total_checked', '?')}")
    lines.append(f"**Conflicts Found:** {summary.get('conflict_count', 0)}")
    lines.append(f"**Overall Severity:** {summary.get('overall_severity', '?')}")

    conflicts = _as_list(conflict.get("conflicts"))
    if conflicts:
        lines.append("")
        for c in conflicts:
            if not isinstance(c, dict):
                continue
            sev = c.get("severity", "?").upper()
            lines.append(f"- **[{sev}]** {c.get('company', '?')} ({c.get('type', '?')}): {c.get('rationale', '?')}")

    return "\n".join(lines) + "\n"


def _section_discussion(discussion: dict[str, Any] | None) -> str:
    """Discussion summary with partner positions and debate."""
    if discussion is None or _is_stub(discussion):
        return "## Discussion Summary\n\n*No discussion available.*\n"

    lines = ["## Discussion Summary\n"]
    lines.append(f"**Assessment Mode:** {discussion.get('assessment_mode', '?')}")
    lines.append(f"**Consensus Verdict:** {discussion.get('consensus_verdict', '?')}")

    # Partner positions
    for pv in _as_list(discussion.get("partner_verdicts")):
        if not isinstance(pv, dict):
            continue
        partner = (pv.get("partner") or "?").title()
        verdict = pv.get("verdict") or "?"
        rationale = pv.get("rationale") or ""
        lines.append(f"\n### {partner}: {verdict}")
        if rationale:
            lines.append(f"\n{rationale}")

    # Debate sections
    debate = _as_list(discussion.get("debate_sections"))
    if debate:
        lines.append("\n### Key Debates\n")
        for section in debate:
            if not isinstance(section, dict):
                continue
            lines.append(f"**{section.get('topic', '?')}**\n")
            for exchange in _as_list(section.get("exchanges")):
                if not isinstance(exchange, dict):
                    continue
                partner = (exchange.get("partner") or "?").title()
                position = exchange.get("position") or ""
                lines.append(f"> **{partner}:** {position}\n")

    return "\n".join(lines) + "\n"


def _section_scorecard(score_dims: dict[str, Any] | None) -> str:
    """Dimension scorecard table."""
    if score_dims is None or _is_stub(score_dims):
        return "## Dimension Scorecard\n\n*No scorecard available.*\n"

    items = _as_list(score_dims.get("items"))
    summary = _as_dict(score_dims.get("summary"))
    by_cat = _as_dict(summary.get("by_category"))

    lines = ["## Dimension Scorecard\n"]
    lines.append(
        "*Dimension scores reflect the agent's assessment calibrated against "
        "stage-appropriate benchmarks. All scores are agent-generated.*\n"
    )

    # Category summary
    lines.append("| Category | Strong | Moderate | Concern | Dealbreaker | N/A |")
    lines.append("|----------|--------|----------|---------|-------------|-----|")
    for cat, counts in by_cat.items():
        lines.append(
            f"| {cat} | {counts.get('strong_conviction', 0)} | {counts.get('moderate_conviction', 0)} "
            f"| {counts.get('concern', 0)} | {counts.get('dealbreaker', 0)} "
            f"| {counts.get('not_applicable', 0)} |"
        )
    lines.append("")

    # Full item table
    status_icons = {
        "strong_conviction": "STRONG",
        "moderate_conviction": "MODERATE",
        "concern": "CONCERN",
        "dealbreaker": "DEALBREAKER",
        "not_applicable": "N/A",
    }

    lines.append("| # | Category | Dimension | Status |")
    lines.append("|---|----------|-----------|--------|")
    for i, item in enumerate(items, 1):
        cat = item.get("category", "?")
        label = item.get("label", item.get("id", "?"))
        status = status_icons.get(item.get("status", "?"), "?")
        lines.append(f"| {i} | {cat} | {label} | {status} |")

    return "\n".join(lines) + "\n"


def _section_concerns(score_dims: dict[str, Any] | None) -> str:
    """Concerns and dealbreakers."""
    if score_dims is None or _is_stub(score_dims):
        return ""

    summary = _as_dict(score_dims.get("summary"))
    dealbreakers = _as_list(summary.get("dealbreakers"))
    concerns = _as_list(summary.get("top_concerns"))

    if not dealbreakers and not concerns:
        return ""

    lines = ["## Concerns and Dealbreakers\n"]

    if dealbreakers:
        lines.append("### Dealbreakers\n")
        for db in dealbreakers:
            lines.append(f"- **{db.get('label', db.get('id', '?'))}** ({db.get('category', '?')})")
            if db.get("notes"):
                lines.append(f"  - {db['notes']}")
        lines.append("")

    if concerns:
        lines.append("### Key Concerns\n")
        for c in concerns:
            lines.append(f"- **{c.get('label', c.get('id', '?'))}** ({c.get('category', '?')})")
            if c.get("notes"):
                lines.append(f"  - {c['notes']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_diligence(discussion: dict[str, Any] | None) -> str:
    """Diligence requirements from the discussion."""
    if discussion is None or _is_stub(discussion):
        return ""

    reqs = _as_list(discussion.get("diligence_requirements"))
    if not reqs:
        return ""

    lines = ["## Diligence Requirements\n"]
    for i, req in enumerate(reqs, 1):
        lines.append(f"{i}. {req}")
    return "\n".join(lines) + "\n"


def _section_coaching(
    discussion: dict[str, Any] | None,
    score_dims: dict[str, Any] | None,
) -> str:
    """Founder coaching based on concerns and partner questions."""
    lines = ["## Founder Coaching\n"]
    lines.append("Prepare for these areas before your next investor meeting:\n")

    coaching_items: list[str] = []

    if score_dims is not None and not _is_stub(score_dims):
        # Build lookup from items for evidence fallback
        items_by_id: dict[str, dict[str, Any]] = {}
        for it in _as_list(score_dims.get("items")):
            if isinstance(it, dict) and it.get("id"):
                items_by_id[it["id"]] = it

        for db in _as_list(_as_dict(score_dims.get("summary")).get("dealbreakers")):
            if not isinstance(db, dict):
                continue
            label = db.get("label", "?")
            evidence = db.get("evidence", "")
            # Fallback: if summary.dealbreakers lacks evidence, pull from items
            if not evidence:
                dim_id = db.get("id", "")
                fallback = items_by_id.get(dim_id, {})
                evidence = fallback.get("evidence", "")
            item = f"CRITICAL — **{label}**"
            if evidence:
                item += f": {evidence}"
            item += " **Prepare:** Gather specific evidence to address this before your next IC."
            coaching_items.append(item)

    if discussion is not None and not _is_stub(discussion):
        concerns = _as_list(discussion.get("key_concerns"))
        for c in concerns:
            coaching_items.append(f"Address this concern proactively: {c}")

    if not coaching_items:
        lines.append("No specific coaching items identified.\n")
    else:
        for i, item in enumerate(coaching_items[:10], 1):
            lines.append(f"{i}. {item}")
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

    # Apply accepted_warnings from fund_profile (medium-severity only)
    fund_art = artifacts.get("fund_profile.json")
    if _usable(fund_art):
        acceptances: list[dict[str, str]] = []
        for aw in _as_list(fund_art.get("accepted_warnings")):
            code = aw.get("code", "") if isinstance(aw, dict) else ""
            match_str = aw.get("match", "") if isinstance(aw, dict) else ""
            if not code or not match_str:
                print("Warning: accepted_warnings entry missing 'code' or 'match' — skipped", file=sys.stderr)
                continue
            reason = aw.get("reason", "") if isinstance(aw, dict) else ""
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

    profile = _render_safe(artifacts.get("startup_profile.json"))
    fund = _render_safe(artifacts.get("fund_profile.json"))
    conflict = _render_safe(artifacts.get("conflict_check.json"))
    discussion = _render_safe(artifacts.get("discussion.json"))
    score_dims = _render_safe(artifacts.get("score_dimensions.json"))

    sections = [
        _section_title(profile),
        _section_executive_summary(profile, score_dims, discussion),
        _section_fund_profile(fund),
        _section_conflict_check(conflict),
        _section_discussion(discussion),
        _section_scorecard(score_dims),
        _section_concerns(score_dims),
        _section_diligence(discussion),
        _section_coaching(discussion, score_dims),
        _section_warnings(warnings),
    ]

    report_markdown = "\n".join(s for s in sections if s)
    report_markdown += (
        "\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — IC Simulation Agent*\n"
    )

    # Stderr summary
    print(f"Artifacts found: {len(artifacts_found)}/{len(all_names)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        low = [w for w in warnings if w["severity"] == "low"]
        info = [w for w in warnings if w["severity"] == "info"]
        print(
            f"Warnings: {len(high)} high, {len(medium)} medium, {len(low)} low, {len(info)} info",
            file=sys.stderr,
        )
        for w in warnings:
            print(f"  [{w['severity'].upper()}] {w['code']}: {w['message']}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)

    return {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose IC simulation report from artifacts")
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
