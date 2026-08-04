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
import uuid
from datetime import datetime, timedelta
from typing import Any, TypeGuard

# Canonical warning severity map.
# high = must fix before presenting, medium = warn in report,
# low = note in appendix, info = note in report metadata.
_CORRUPT: dict[str, Any] = {"__corrupt__": True}
KNOWN_STAGES = {"pre_seed", "seed", "series_a"}

WARNING_SEVERITY: dict[str, str] = {
    # "low" deliberately, NOT medium: by the time this fires the text has ALREADY been corrected by
    # substitute(), so the report the founder reads is clean. What remains is an AUTHORING task (a
    # producer that should stop emitting the token, or a filename that must be dropped rather than
    # renamed), and ic-sim / market-sizing / deck-review all block strict mode on medium — which would
    # abort a founder's run over a cosmetic issue that was already fixed. The fleet ratchet in
    # test_compose_invariants.py is the real gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # High — structural integrity violations
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    "UNVALIDATED_ARTIFACT": "high",
    "BLOCKING_CONFLICT": "high",
    "ORPHANED_CONFLICT": "high",
    "VERDICT_SCORE_MISMATCH": "high",
    "INVALID_PARTNER_COUNT": "high",
    # Medium — quality concerns worth surfacing
    "PARTNER_UNANIMITY": "medium",
    "ZERO_APPLICABLE": "medium",
    "LOW_CONVICTION_BASIS": "medium",
    "LOW_COVERAGE_VERDICT_CAP": "medium",
    "LOW_COVERAGE_VERDICT_FLOOR": "medium",
    "LOW_COVERAGE_VERDICT_HELD": "medium",
    "STALE_IMPORT": "medium",
    "LOW_EVIDENCE": "medium",
    "FUND_VALIDATION_ERROR": "medium",
    "CONFLICT_CHECK_VALIDATION_ERROR": "medium",
    "SCORE_DIMENSIONS_VALIDATION_ERROR": "medium",
    "DEGRADED_ASSESSMENT": "medium",
    # No id-level debate channel at all, so NO dealbreaker can be attributed.
    # Medium, not low: it means the discussion.json is hand-written or was
    # produced by a compose_discussion.py predating debated_dealbreakers, and
    # every provenance label in the report degrades to "unavailable".
    "DEALBREAKER_PROVENANCE_UNVERIFIABLE": "medium",
    "CONSENSUS_SCORE_MISMATCH": "medium",
    "UNANIMOUS_VERDICT_MISMATCH": "medium",
    "SHALLOW_ASSESSMENT": "medium",
    "HIGH_NA_COUNT": "medium",
    "INCOMPLETE_PORTFOLIO_REVIEW": "medium",
    # Low — minor notes
    "SCHEMA_DRIFT": "low",
    "STAGE_OUT_OF_SCOPE": "low",
    # v0.4.2 Mitigation 2 — informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
    # Uncalibrated by design (see compose_discussion.py) — never gates, just a
    # prompt to read the debate more closely.
    "PARTNER_CAPITULATION": "low",
    # A scored dealbreaker the debate never argued. LOW and deliberately
    # non-gating: scoring covers 28 dimensions and the debate covers whatever
    # three partners chose to argue, so an undebated dealbreaker is an expected,
    # often-correct outcome. This exists to make the difference visible, never to
    # suppress the finding — suppressing it would flip hard_pass and hide a fatal
    # flaw from the founder.
    "UNDEBATED_DEALBREAKER": "low",
    # Info — transparency, no action needed
    "PARTNER_CONVERGENCE": "info",
    "SEQUENTIAL_FALLBACK": "info",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "STALE_ARTIFACT": "Stale Artifact",
    "BLOCKING_CONFLICT": "Blocking Conflict",
    "ORPHANED_CONFLICT": "Orphaned Conflict",
    "VERDICT_SCORE_MISMATCH": "Verdict/Score Mismatch",
    "PARTNER_UNANIMITY": "Partner Unanimity",
    "ZERO_APPLICABLE": "Zero Applicable Dimensions",
    "LOW_CONVICTION_BASIS": "Thin Scoring Base",
    "LOW_COVERAGE_VERDICT_CAP": "Verdict Capped — Low Coverage",
    "LOW_COVERAGE_VERDICT_FLOOR": "Verdict Floored — Low Coverage",
    "LOW_COVERAGE_VERDICT_HELD": "Verdict Held — Low Coverage",
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
    "MARKER_COLLISION": "Marker Collision",
    "UNVALIDATED_ARTIFACT": "Unvalidated Artifact",
    "PARTNER_CAPITULATION": "Partner Capitulation (Unconfirmed)",
    "UNDEBATED_DEALBREAKER": "Undebated Dealbreaker",
    "DEALBREAKER_PROVENANCE_UNVERIFIABLE": "Dealbreaker Provenance Unverifiable",
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
        "competitive_notes",
        "gtm_notes",
        # `to_confirm`: under the Step-1 Auto-pilot carve-out the agent marks a
        # basic it could only infer (not founder-state) as to_confirm and proceeds
        # rather than stalling — a sanctioned note, not schema drift.
        "to_confirm",
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
        "debated_dealbreakers",
        "key_concerns",
        "diligence_requirements",
        "assessment_mode_intentional",
        # compose_discussion.py's uncalibrated capitulation signal (see 4d.
        # PARTNER_CAPITULATION below and that script's module docstring).
        "warnings",
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
        # NOTE: "portfolio" is intentionally NOT in this set. fund_profile.py
        # only requires it for fund_specific mode (a real fund's actual
        # holdings) — it's optional in generic mode, so it can't be an
        # unconditional top-level-shape requirement here.
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


def _founder_text_policy() -> Any:
    """Import the fleet's shared founder-text policy from `founder-skills/scripts/`.

    Parent-relative rather than duplicated: this file lives at
    `skills/<skill>/scripts/compose_report.py`, so `parents[2]/scripts` is the shared dir. Returns
    None if unavailable — a missing policy module must never block a report, since the scan is a
    warning and not a gate.
    """
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _warn(code: str, message: str, founder_message: str | None = None) -> dict[str, str]:
    """Create a warning dict with code, message, and severity.

    `message` is agent-facing and unchanged in report.json. `founder_message`
    is an OPTIONAL additive key stating the founder-visible consequence in
    plain words (no artifact filename, no raw enum token) -- report.md
    renders it instead of `message` when present.
    """
    w = {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }
    if founder_message is not None:
        w["founder_message"] = founder_message
    return w


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

    # 0. UNVALIDATED_ARTIFACT — script provenance check. discussion.json is
    # the artifact a hand-written verdict used to slip into (see
    # compose_discussion.py's module docstring) — every real discussion.json
    # carries the producer's own stamp, so a missing/wrong stamp means
    # something other than compose_discussion.py wrote this file.
    EXPECTED_PRODUCERS = {"discussion.json": "compose_discussion"}
    for name, expected_producer in EXPECTED_PRODUCERS.items():
        data = artifacts.get(name)
        if _usable(data) and data.get("_produced_by") != expected_producer:
            warnings.append(
                _warn(
                    "UNVALIDATED_ARTIFACT",
                    f"Artifact '{name}' exists but was not produced by {expected_producer}.py — "
                    f"run the script instead of writing the file directly",
                )
            )

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 1b. STALE_ARTIFACT — run_id mismatch across artifacts
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifact_data = artifacts.get(name)
        if _usable(artifact_data):
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
            _normalize_company(name)
            for entry in _as_list(fund_profile.get("portfolio"))
            if isinstance(entry, dict)
            for name in [entry.get("name", "")]
            if isinstance(name, str)
        }
        for conflict in _as_list(conflict_check.get("conflicts")):
            if not isinstance(conflict, dict):
                continue
            company = conflict.get("company", "")
            if not isinstance(company, str):
                continue
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

        # Suppress if ZERO_APPLICABLE_DIMENSIONS present, OR if the verdict was intentionally
        # coverage-capped or coverage-floored (IC-11: too many to_confirm -> forced to
        # more_diligence while the conviction sits in the invest band, or in the pass band —
        # both divergences are by design, not errors).
        has_zero_applicable = "ZERO_APPLICABLE_DIMENSIONS" in score_warnings
        coverage_capped = score_summary.get("coverage_capped") is True
        coverage_floored = score_summary.get("coverage_floored") is True
        coverage_held = score_summary.get("coverage_held") is True

        if not has_zero_applicable and not coverage_capped and not coverage_floored and verdict in VERDICT_SCORE_RANGES:
            low, high = VERDICT_SCORE_RANGES[verdict]
            if not (low <= conviction_score <= high) and verdict != "hard_pass":
                warnings.append(
                    _warn(
                        "VERDICT_SCORE_MISMATCH",
                        f"Verdict '{verdict}' does not match score {conviction_score}% "
                        f"(expected range: {low}%-{high}%)",
                    )
                )

        # Surface the coverage cap so the founder knows the verdict was held back by
        # undisclosed data, not by the merits.
        if coverage_capped:
            to_confirm_n = score_summary.get("to_confirm", 0)
            warnings.append(
                _warn(
                    "LOW_COVERAGE_VERDICT_CAP",
                    f"{to_confirm_n} dimensions are undisclosed (to_confirm) — verdict capped at "
                    f"'more_diligence' (conviction {conviction_score}% reflects only the confirmed "
                    "dimensions). Supply the missing data to lift the cap.",
                    founder_message=(
                        f"{to_confirm_n} of the scoring dimensions are still undisclosed, so the "
                        f"verdict is being held at 'More Diligence' — the {conviction_score}% score "
                        "reflects only what could be confirmed so far. Share the missing "
                        "information to get a fuller verdict."
                    ),
                )
            )

        if coverage_held:
            to_confirm_n = score_summary.get("to_confirm", 0)
            basis = _as_dict(score_summary.get("conviction_basis"))
            warnings.append(
                _warn(
                    "LOW_COVERAGE_VERDICT_HELD",
                    f"{to_confirm_n} dimensions are undisclosed and only "
                    f"{basis.get('applicable', '?')} of {basis.get('total', 28)} were scoreable — the "
                    "'More Diligence' verdict reflects how little was disclosed, not a considered "
                    "assessment of the company. It is neither a positive nor a negative signal. Supply "
                    "the missing data for a real verdict.",
                )
            )

        # And the floor. The founder MUST be told the difference between "we looked
        # and this is a pass" and "we could not look" — presenting the latter as a
        # decline is the more damaging error of the two.
        if coverage_floored:
            to_confirm_n = score_summary.get("to_confirm", 0)
            warnings.append(
                _warn(
                    "LOW_COVERAGE_VERDICT_FLOOR",
                    f"{to_confirm_n} dimensions are undisclosed (to_confirm) — the low conviction "
                    f"({conviction_score}%) reflects missing information, not assessed weakness, so the "
                    "verdict is held at 'more_diligence' rather than a decline. This is NOT a negative "
                    "signal about the company; supply the missing data for a real verdict.",
                    founder_message=(
                        f"The {conviction_score}% score is low because {to_confirm_n} scoring "
                        "dimensions are still undisclosed — not because of anything weak in what "
                        "was reviewed. The verdict is being held at 'More Diligence' rather than "
                        "scored as a decline. This is not a negative signal; share the missing "
                        "information for a real verdict."
                    ),
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
    #
    # DORMANT IN NORMAL OPERATION since compose_discussion.py started deriving
    # consensus_verdict as a majority vote over partner_verdicts itself
    # (see that script) — a mismatch between the two is now structurally
    # near-impossible for a real, producer-written discussion.json (majority
    # of 3 either equals a unanimous vote, or there's dissent, which this
    # check ignores by design). It is NOT dead code: a hand-written or
    # otherwise non-derived discussion.json (which UNVALIDATED_ARTIFACT above
    # flags separately) can still violate this, so it stays as a second,
    # independent check on that failure mode. Do not read a quiet run of this
    # warning as evidence the check no longer does anything.
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

    # 4d. PARTNER_CAPITULATION — surfaces compose_discussion.py's uncalibrated
    # POSSIBLE_CAPITULATION signal (>=2 of 3 verdicts changed and converged on
    # the same value) in the report's own Warnings section. Low severity and
    # never gating — see that script's module docstring for why it cannot
    # distinguish genuine persuasion from manufactured agreement.
    if _usable(discussion) and "POSSIBLE_CAPITULATION" in _as_list(discussion.get("warnings")):
        warnings.append(
            _warn(
                "PARTNER_CAPITULATION",
                "2 or more partners changed their verdict in the rebuttal round and converged on the "
                "same value — consistent with genuine persuasion by new evidence, but also with three "
                "partners folding to whoever argued hardest. This signal cannot tell the two apart; "
                "read the debate before treating the convergence as settled.",
            )
        )

    # 4e. Dealbreaker provenance — which scored dealbreakers the debate actually
    # argued. Scoring runs after the debate, over all 28 dimensions, and the only
    # thing tying the two together is a sentence in the SCORE_DIMENSIONS dispatch
    # asking the sub-agent to reflect debated dealbreakers. That is a soft
    # instruction, and on a measured run it produced 4 scored dealbreakers against
    # 3 debated ones, with the report narrating "four independent fatal flaws".
    #
    # This does NOT suppress the undebated one — an undebated dealbreaker can be
    # entirely real (28 dimensions, 3 partners' arguments), and dropping it would
    # flip hard_pass and hide a fatal flaw. It discloses, so a reader can tell a
    # partner-argued dealbreaker from a scoring-pass one.
    if _usable(score_dims):
        scored_ids = [
            db.get("id") for db in _as_list(_as_dict(score_dims.get("summary")).get("dealbreakers")) if db.get("id")
        ]
        if scored_ids:
            debated_raw = discussion.get("debated_dealbreakers") if _usable(discussion) else None
            if isinstance(debated_raw, list):
                debated_ids = {d.get("dimension") for d in debated_raw if isinstance(d, dict)}
                undebated = [i for i in scored_ids if i not in debated_ids]
                if undebated:
                    warnings.append(
                        _warn(
                            "UNDEBATED_DEALBREAKER",
                            f"{len(undebated)} of {len(scored_ids)} scored dealbreaker(s) "
                            f"({', '.join(sorted(undebated))}) were never raised as dealbreakers in the "
                            "partner debate — they come from the scoring pass alone. That does not make "
                            "them wrong, but they carry less evidentiary weight than a dealbreaker two "
                            "partners argued, and the report labels which is which.",
                        )
                    )
            else:
                # No id-level channel in this discussion.json (hand-written, or
                # produced before compose_discussion.py emitted the field). The
                # comparison is impossible — say so rather than let "no warning"
                # read as "every dealbreaker was debated".
                warnings.append(
                    _warn(
                        "DEALBREAKER_PROVENANCE_UNVERIFIABLE",
                        f"discussion.json carries no 'debated_dealbreakers' list, so none of the "
                        f"{len(scored_ids)} scored dealbreaker(s) can be traced to the debate. Treat every "
                        "dealbreaker in this report as unattributed.",
                        founder_message=(
                            f"We can't confirm which of the {len(scored_ids)} dealbreaker(s) below "
                            "were raised and argued in the partner debate versus flagged during "
                            "scoring alone — that link isn't available for this run. That doesn't "
                            "mean they're wrong, just that we can't show their provenance."
                        ),
                    )
                )

    # 5. PARTNER_UNANIMITY / PARTNER_CONVERGENCE
    if _usable(discussion):
        partner_verdicts = _as_list(discussion.get("partner_verdicts"))
        assessment_mode = discussion.get("assessment_mode", "sequential")

        if len(partner_verdicts) != 3:
            warnings.append(_warn("INVALID_PARTNER_COUNT", f"Expected 3 partner verdicts, got {len(partner_verdicts)}"))

        if len(partner_verdicts) == 3 and all(isinstance(pv, dict) for pv in partner_verdicts):
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
            warnings.append(
                _warn(
                    "ZERO_APPLICABLE",
                    "All dimensions marked not_applicable — score is 0.0",
                    founder_message=(
                        "None of the scoring dimensions could be applied to this company, so the "
                        "0% conviction score doesn't reflect an assessment — it means nothing was "
                        "scored, not that everything failed."
                    ),
                )
            )
        if "LOW_CONVICTION_BASIS" in score_warnings:
            # Read the summary locally rather than leaning on the binding from the
            # earlier block — both happen to guard on _usable(score_dims), so it
            # would resolve, but that is an implicit coupling a later edit can break.
            basis = _as_dict(_as_dict(score_dims.get("summary")).get("conviction_basis"))
            warnings.append(
                _warn(
                    "LOW_CONVICTION_BASIS",
                    f"The conviction score rests on only {basis.get('applicable')} of "
                    f"{basis.get('total')} dimensions — the remainder are undisclosed or not "
                    "applicable. The percentage is arithmetically correct but its precision "
                    "overstates the evidence; present it with its denominator and do not treat "
                    "it as comparable to a fully-scored company.",
                )
            )

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
                    founder_message=(
                        f"{na_count} of the 28 scoring dimensions didn't apply to this company, so "
                        "the conviction score is based on a smaller set than usual and may read "
                        "higher than it would with fuller coverage."
                    ),
                )
            )

    # 11. SCHEMA_DRIFT
    # `metadata` (carrying `metadata.run_id`) is stamped on EVERY producer
    # artifact per references/artifact-schemas.md — it is not an unexpected
    # key on any of them, so it's exempted here rather than duplicated into
    # every EXPECTED_KEYS set below. `_produced_by` is the same story for the
    # producer-provenance stamp the UNVALIDATED_ARTIFACT check (above) reads.
    for name, expected in EXPECTED_KEYS.items():
        artifact = artifacts.get(name)
        if _usable(artifact):
            actual_keys = set(artifact.keys()) - {"metadata", "_produced_by"}
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

        # VC "pass"/"hard_pass" mean DECLINE — but a bare "Pass" reads to a
        # founder as "passes the bar." Never render the internal enum value
        # alone; always lead with an unambiguous decision word.
        verdict_label = {
            "invest": "Invest — strong enough for a term sheet discussion",
            "more_diligence": "More Diligence — promising but needs more evidence",
            "pass": "Decline — too many concerns to proceed at this time",
            "hard_pass": "Decline — Hard Pass: fatal flaw identified",
        }.get(verdict, verdict)

        # When the verdict was HELD by coverage rather than earned on the merits, the
        # default wording is wrong in opposite directions: "promising but needs more
        # evidence" flatters a floored verdict (nothing was assessed, so nothing is
        # promising) and undersells a capped one (the conviction was in the invest
        # band). Make the coverage framing the DEFAULT rendering rather than a caveat
        # the narrator has to remember further down the report.
        if verdict == "more_diligence":
            # coverage_held is the case that used to fall through to the merits
            # wording: nothing moved the verdict, but coverage was too thin for
            # "promising" to describe anything that was actually assessed.
            if summary.get("coverage_floored") is True or summary.get("coverage_held") is True:
                verdict_label = (
                    "More Diligence — too little disclosed to reach a verdict (this is NOT a negative signal)"
                )
            elif summary.get("coverage_capped") is True:
                verdict_label = (
                    "More Diligence — the confirmed dimensions score well, but too much is undisclosed to underwrite"
                )

        # The score never appears without its denominator when the base is thin. "50.0%"
        # off two applicable dimensions reads as a considered midpoint across the whole
        # framework; the decimal place implies evidence that does not exist.
        basis = _as_dict(summary.get("conviction_basis"))
        if basis.get("sufficient") is False and basis.get("applicable"):
            lines.append(
                f"**Conviction Score:** {score}% — {verdict_label}  \n"
                f"*Scored on {basis.get('applicable')} of {basis.get('total')} dimensions — "
                f"too thin a base for the percentage to be meaningful. Read the breakdown below, "
                f"not the headline number.*"
            )
        else:
            lines.append(f"**Conviction Score:** {score}% — {verdict_label}")
        to_confirm_ct = summary.get("to_confirm", 0)
        lines.append(
            f"**Breakdown:** {strong} strong, {moderate} moderate, {concern} concern, {db} dealbreaker"
            + (f", {to_confirm_ct} to-confirm" if to_confirm_ct else "")
        )
        lines.append(
            "\n*Conviction score = (strong × 1.0 + moderate × 0.5) ÷ applicable dimensions × 100. "
            "Concerns and N/A earn no credit. A real dealbreaker forces hard_pass regardless of score "
            "(in generic-fund mode a Fund-Fit dealbreaker is non-blocking — see note below if shown).*"
        )
        lines.append(
            "\n*Verdict legend: **Invest** = proceed to term sheet discussion. "
            "**More Diligence** = promising, needs more evidence. **Decline** (internal `pass`) "
            "= would not proceed today. **Decline — Hard Pass** (internal `hard_pass`) = a fatal "
            "flaw makes this a decline regardless of score.*"
        )

        # GENERIC_MODE_DEALBREAKER_NON_BLOCKING: a Fund-Fit dealbreaker (derived from the
        # synthesized fund persona) was recorded but did NOT override the verdict — only the
        # Fund-Fit ones are simulated; startup-side dealbreakers still force hard_pass. Name
        # exactly which dimensions were treated as simulated so the note can't be read as
        # excusing a real fatal flaw.
        simulated_ids = summary.get("simulated_dealbreaker_ids") or []
        if simulated_ids:
            labels = ", ".join(f"`{sid}`" for sid in simulated_ids)
            lines.append(
                f"\n> **Note:** {len(simulated_ids)} Fund-Fit dealbreaker(s) ({labels}) were flagged "
                "during this illustrative/generic-fund simulation and treated as **simulated and "
                "non-blocking** — their evidence derives from the synthesized fund persona (invented "
                "portfolio / check-size / thesis), not a real fund, so they cannot override the "
                "merits-based score. Any startup-side dealbreaker still forces a hard decline."
            )

    if discussion is not None and not _is_stub(discussion):
        partner_verdicts = _as_list(discussion.get("partner_verdicts"))
        if partner_verdicts:
            verdict_strs = [
                f"{(pv.get('partner') or '?').title()}: {pv.get('verdict') or '?'}"
                for pv in partner_verdicts
                if isinstance(pv, dict)
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

    if fund.get("mode") == "generic":
        lines.append(
            "\n> **Illustrative fund profile.** This is a synthesized generic-fund persona "
            "built for this simulation — not a real fund's actual thesis, partners, or "
            "portfolio holdings. Any portfolio companies and conflicts referenced anywhere "
            "in this report are fictional constructs, not real investments."
        )

    thesis = _as_list(fund.get("thesis_areas"))
    if thesis:
        lines.append(f"**Thesis Areas:** {', '.join(str(t) for t in thesis)}")

    check_size = fund.get("check_size_range", {})
    if isinstance(check_size, dict) and check_size:
        currency = check_size.get("currency", "USD")
        min_str = _fmt_number(check_size.get("min"))
        max_str = _fmt_number(check_size.get("max"))
        lines.append(f"**Check Size:** {currency} {min_str} - {max_str}")

    archetypes = _as_list(fund.get("archetypes"))
    if archetypes:
        lines.append("\n**Partners:**")
        for arch in archetypes:
            if not isinstance(arch, dict):
                continue
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

    # Key concerns from discussion (item 14 — collected but previously dropped)
    key_concerns = _as_list(discussion.get("key_concerns"))
    if key_concerns:
        lines.append("\n### Key Concerns\n")
        for concern in key_concerns:
            if isinstance(concern, str) and concern.strip():
                lines.append(f"- {concern}")
            elif isinstance(concern, dict) and concern.get("concern"):
                lines.append(f"- {concern['concern']}")
        lines.append("")

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
    lines.append("| Category | Strong | Moderate | Concern | Dealbreaker | To Confirm | N/A |")
    lines.append("|----------|--------|----------|---------|-------------|------------|-----|")
    for cat, counts in by_cat.items():
        if not isinstance(counts, dict):
            continue
        lines.append(
            f"| {cat} | {counts.get('strong_conviction', 0)} | {counts.get('moderate_conviction', 0)} "
            f"| {counts.get('concern', 0)} | {counts.get('dealbreaker', 0)} "
            f"| {counts.get('to_confirm', 0)} | {counts.get('not_applicable', 0)} |"
        )
    lines.append("")

    lines.append("\n*Dimensions are scored once by the committee as a whole, not per partner.*\n")

    # Full item table
    status_icons = {
        "strong_conviction": "STRONG",
        "moderate_conviction": "MODERATE",
        "concern": "CONCERN",
        "dealbreaker": "DEALBREAKER",
        "to_confirm": "TO CONFIRM",
        "not_applicable": "N/A",
    }

    lines.append("| # | Category | Dimension | Status | Evidence |")
    lines.append("|---|----------|-----------|--------|----------|")
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        cat = item.get("category", "?")
        label = item.get("label", item.get("id", "?"))
        status = status_icons.get(item.get("status", "?"), "?")
        raw_evidence = item.get("evidence") or ""
        evidence = str(raw_evidence)
        if len(evidence) > 120:
            evidence = evidence[:117] + "..."
        evidence = evidence.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {cat} | {label} | {status} | {evidence} |")

    return "\n".join(lines) + "\n"


def _dealbreaker_provenance(discussion: dict[str, Any] | None) -> dict[str, list[str]] | None:
    """Map dimension id -> the archetypes that raised it as a dealbreaker in the
    debate. Returns None when discussion.json carries no id-level channel, which
    is NOT the same as "nothing was debated" and must not be rendered as such."""
    if not _usable(discussion):
        return None
    debated = discussion.get("debated_dealbreakers")
    if not isinstance(debated, list):
        return None
    out: dict[str, list[str]] = {}
    for entry in debated:
        if not isinstance(entry, dict):
            continue
        dimension = entry.get("dimension")
        if isinstance(dimension, str) and dimension:
            out[dimension] = [a for a in _as_list(entry.get("raised_by")) if isinstance(a, str)]
    return out


def _section_concerns(score_dims: dict[str, Any] | None, discussion: dict[str, Any] | None = None) -> str:
    """Concerns and dealbreakers.

    Each dealbreaker is labelled with its provenance — argued by named partners
    in the debate, or produced by the scoring pass alone. The two are not equally
    evidenced and the report should not present them as if they were.
    """
    if score_dims is None or _is_stub(score_dims):
        return ""

    summary = _as_dict(score_dims.get("summary"))
    dealbreakers = _as_list(summary.get("dealbreakers"))
    concerns = _as_list(summary.get("top_concerns"))

    if not dealbreakers and not concerns:
        return ""

    lines = ["## Concerns and Dealbreakers\n"]

    if dealbreakers:
        provenance = _dealbreaker_provenance(discussion)
        lines.append("### Dealbreakers\n")
        for db in dealbreakers:
            lines.append(f"- **{db.get('label', db.get('id', '?'))}** ({db.get('category', '?')})")
            if provenance is None:
                lines.append("  - *Debate provenance: unavailable — could not be traced to the partner debate.*")
            elif db.get("id") in provenance:
                raised_by = provenance[db["id"]] or []
                who = ", ".join(a.title() for a in raised_by) if raised_by else "the debate"
                lines.append(f"  - *Raised as a dealbreaker in the debate by: {who}.*")
            else:
                lines.append(
                    "  - *From the scoring pass — no partner raised this as a dealbreaker in the debate. "
                    "It may still be real; it is simply less corroborated than a partner-argued one.*"
                )
            if db.get("notes"):
                lines.append(f"  - {db['notes']}")
            if db.get("evidence"):
                lines.append(f"  - *Basis: {db['evidence']}*")
        lines.append("")

    if concerns:
        lines.append("### Key Concerns\n")
        for c in concerns:
            lines.append(f"- **{c.get('label', c.get('id', '?'))}** ({c.get('category', '?')})")
            if c.get("notes"):
                lines.append(f"  - {c['notes']}")
            if c.get("evidence"):
                lines.append(f"  - *Basis: {c['evidence']}*")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_partner_questions(partner_assessments: list[dict[str, Any] | None]) -> str:
    """Questions the Partners Would Ask You — rendered from partner_assessment_*.json artifacts."""
    usable = [pa for pa in partner_assessments if _usable(pa)]
    if not usable:
        return ""

    lines = ["## Questions the Partners Would Ask You\n"]
    lines.append(
        "*These questions come from each partner's individual assessment. "
        "They are generated based on archetype personas — use them to stress-test your narrative.*\n"
    )

    for pa in usable:
        partner = (pa.get("partner") or "unknown").title()
        lines.append(f"### {partner}\n")

        conviction_points = _as_list(pa.get("conviction_points"))
        if conviction_points:
            lines.append("**What I like:**")
            for cp in conviction_points:
                lines.append(f"- {cp}")
            lines.append("")

        key_concerns = _as_list(pa.get("key_concerns"))
        if key_concerns:
            lines.append("**What gives me pause:**")
            for kc in key_concerns:
                lines.append(f"- {kc}")
            lines.append("")

        questions = _as_list(pa.get("questions_for_founders"))
        if questions:
            lines.append("**Questions I would ask:**")
            for q in questions:
                lines.append(f"- {q}")
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


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Validation warnings from cross-artifact checks."""
    if not warnings:
        return ""

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i", "info": "~"}
    lines = ["## Warnings\n"]
    for w in warnings:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("founder_message") or w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


def _derive_consensus_strength(discussion: dict[str, Any]) -> str:
    """Derive consensus_strength from discussion.json partner_verdicts.

    "strong" = all 3 partner verdicts match, "mixed" = a 2-1 split,
    "weak" = otherwise (no clear majority, missing/malformed verdicts).
    """
    verdicts = [
        _normalize_verdict(pv.get("verdict"))
        for pv in _as_list(discussion.get("partner_verdicts"))
        if isinstance(pv, dict) and pv.get("verdict")
    ]
    if len(verdicts) != 3:
        return "weak"
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    top = max(counts.values())
    if top == 3:
        return "strong"
    if top == 2:
        return "mixed"
    return "weak"


def _emit_coaching_payload(
    startup_profile: dict[str, Any],
    score_dims: dict[str, Any],
    discussion: dict[str, Any],
    validation_warnings: list[dict[str, str]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
) -> dict[str, Any]:
    """Build the v0.4.2 coaching_payload for ic-sim (schema_version v0.4.2-ic-sim).

    Uses dimension-based schema (no checklist concept).
    Source: score_dimensions.json summary fields + discussion.json partner verdicts.
    """
    summary = _as_dict(score_dims.get("summary"))

    # Dealbreakers from score_dimensions summary.dealbreakers
    # Each entry: {id, category, label, evidence, notes}
    # Payload shape: {dimension, description, severity: "high"}
    raw_dealbreakers = _as_list(summary.get("dealbreakers"))
    dealbreaker_entries: list[dict[str, Any]] = []
    for db in raw_dealbreakers:
        if not isinstance(db, dict):
            continue
        label = db.get("label") or db.get("id") or "?"
        description = db.get("evidence") or db.get("notes") or ""
        dealbreaker_entries.append(
            {
                "dimension": label,
                "description": description,
                "severity": "high",
            }
        )

    # Concerns from score_dimensions summary.top_concerns
    # Each entry: {id, category, label, evidence, notes}
    # Payload shape: {dimension, description} — no severity field
    raw_concerns = _as_list(summary.get("top_concerns"))
    concern_entries: list[dict[str, Any]] = []
    for c in raw_concerns:
        if not isinstance(c, dict):
            continue
        label = c.get("label") or c.get("id") or "?"
        description = c.get("evidence") or c.get("notes") or ""
        concern_entries.append(
            {
                "dimension": label,
                "description": description,
            }
        )

    return {
        "schema_version": "v0.4.2-ic-sim",
        "consensus_strength": _derive_consensus_strength(discussion),
        "summary": {
            "verdict": summary.get("verdict"),
            "conviction_score": summary.get("conviction_score"),
            "strong_conviction_count": summary.get("strong_conviction", 0),
            "moderate_conviction_count": summary.get("moderate_conviction", 0),
            "concern_count": summary.get("concern", 0),
            "dealbreaker_count": summary.get("dealbreaker", 0),
        },
        "dealbreakers": dealbreaker_entries,
        "concerns": concern_entries,
        "high_severity_warnings": [w["code"] for w in validation_warnings if w.get("severity") == "high"],
        "company_name": startup_profile.get("company_name"),
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
    }


def compose(dir_path: str, report_path: str | None = None) -> dict[str, Any]:
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

    # Assemble report sections — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    profile = _render_safe(artifacts.get("startup_profile.json"))
    fund = _render_safe(artifacts.get("fund_profile.json"))
    conflict = _render_safe(artifacts.get("conflict_check.json"))
    discussion = _render_safe(artifacts.get("discussion.json"))
    score_dims = _render_safe(artifacts.get("score_dimensions.json"))

    # Partner assessment artifacts (optional — degrade gracefully when absent)
    partner_assessments: list[dict[str, Any] | None] = [
        _render_safe(artifacts.get(pa_file)) for pa_file in PARTNER_ASSESSMENT_FILES
    ]

    # Render every section EXCEPT Warnings first; the Warnings section, status,
    # validation.warnings, and coaching_payload must all observe the SAME final
    # warnings list — including any MARKER_COLLISION discovered by scanning the body.
    pre_warning_sections = [
        _section_title(profile),
        _section_executive_summary(profile, score_dims, discussion),
        _section_fund_profile(fund),
        _section_conflict_check(conflict),
        _section_discussion(discussion),
        _section_scorecard(score_dims),
        _section_concerns(score_dims, discussion),
        _section_partner_questions(partner_assessments),
        _section_diligence(discussion),
    ]
    body_markdown = "\n".join(s for s in pre_warning_sections if s)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan the body (before appending our own marker, otherwise we always
    # find our own emission). Agent post-Edit verification uses the EXACT uuid
    # (per-run), so substring collisions with body content are informational
    # only — but worth flagging so authors can sanitize. Append BEFORE status is
    # computed and BEFORE the Warnings section is rendered so all consumers agree.
    if "<!-- COACHING_INSERTION_POINT_" in body_markdown:
        warnings.append(
            _warn(
                "MARKER_COLLISION",
                (
                    "Body content contains marker substring; agent post-Edit verification "
                    "uses the EXACT uuid (per-run) so this is informational only — "
                    "body sanitization recommended."
                ),
            )
        )

    status = "clean" if not warnings else "warnings"

    # Render the Warnings section against the final warnings list and splice it in.
    warnings_section = _section_warnings(warnings)
    sections = [body_markdown, warnings_section] if warnings_section else [body_markdown]
    report_markdown = "\n".join(s for s in sections if s)

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — IC Simulation Agent"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
    )

    # --- founder-text policy (shared fleet module) ------------------------------------------------
    # Runs on the FINAL assembled markdown — after the warnings section and footer — because that is
    # the exact string the founder reads, and because producer warning messages are where the
    # internal tokens actually live. Wiring this into competitive-positioning before the warnings
    # splice silently substituted nothing and then reported a clean body while 21 tokens sat in a
    # section appended two lines later.
    _ft = _founder_text_policy()
    if _ft is not None:
        # Identifier keep-set derived from the DATA, not hand-listed: an id present in the artifacts
        # is an id whatever its shape, and rewriting one makes the markdown disagree with the JSON
        # about what a thing is called (cap-table's `safe_conv` is the case that proved this).
        _keep = _ft.identifier_values(artifacts)
        report_markdown = _ft.substitute(report_markdown, extra_keep=_keep)
        _found = _ft.scan(report_markdown, extra_keep=_keep)
        for _tok in _found["enums"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report contains the internal token '{_tok}' — a founder cannot act on it; "
                    f"render it through the shared founder-text policy or stop emitting it",
                )
            )
        for _fn in _found["filenames"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report names the internal file '{_fn}' — drop the reference rather than renaming it",
                )
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

    # v0.4.2 Mitigation 2: structured coaching payload for Context B agent.
    # Use the same uuid marker generated above as the single source of truth.
    resolved_report_path = report_path or os.path.join(os.path.abspath(dir_path), "report.md")
    coaching_payload = _emit_coaching_payload(
        startup_profile=_as_dict(profile),
        score_dims=_as_dict(score_dims),
        discussion=_as_dict(discussion),
        validation_warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
    )

    return {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
        },
        "coaching_payload": coaching_payload,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose IC simulation report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--strict", action="store_true", help="Exit 1 if any warnings (CI mode)")
    p.add_argument(
        "--write-md",
        help="Also write the report markdown to this path (in addition to JSON output via -o)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    report_path = os.path.abspath(args.write_md) if args.write_md else None
    result = compose(args.dir, report_path=report_path)

    if args.write_md:
        report_markdown = result.get("report_markdown", "")
        md_path = os.path.abspath(args.write_md)
        parent = os.path.dirname(md_path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                print(f"Error: cannot create directory for --write-md: {e}", file=sys.stderr)
                sys.exit(2)
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(report_markdown if report_markdown.endswith("\n") else report_markdown + "\n")
        except OSError as e:
            print(f"Error: cannot write --write-md file: {e}", file=sys.stderr)
            sys.exit(2)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    v = result["validation"]
    _write_output(
        out,
        args.output,
        summary={"validation": v["status"], "warnings": len(v["warnings"])},
    )

    # Post-write on-disk verification: confirm declared output files exist and are non-empty.
    if args.output:
        abs_out = os.path.abspath(args.output)
        if not os.path.isfile(abs_out) or os.path.getsize(abs_out) == 0:
            print(
                f"Error: output file missing or empty after write: {abs_out}",
                file=sys.stderr,
            )
            sys.exit(2)
    if args.write_md:
        abs_md = os.path.abspath(args.write_md)
        if not os.path.isfile(abs_md) or os.path.getsize(abs_md) == 0:
            print(
                f"Error: --write-md file missing or empty after write: {abs_md}",
                file=sys.stderr,
            )
            sys.exit(2)

    if args.strict:
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] in ("high", "medium")]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
