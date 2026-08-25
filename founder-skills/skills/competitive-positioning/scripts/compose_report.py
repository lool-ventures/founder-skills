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
import re
import sys
import uuid
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
    # A checklist graded against a positioning map that has since moved. run_id parity cannot
    # catch this (the run_id is unchanged by a re-score), so the fingerprint comparison is the
    # only detector. High because POS_04's pass condition reads rank data directly, so a
    # mismatch means a graded criterion describes a map that no longer exists.
    "CHECKLIST_STALE_VS_POSITIONING": "high",
    # Medium — show in report
    "SHALLOW_COMPETITOR_PROFILE": "medium",
    "VANITY_AXIS_WARNING": "medium",
    "MOAT_WITHOUT_EVIDENCE": "medium",
    # A verification run that was REJECTED, not skipped. The producer leaves the canonical path
    # untouched on refusal and keeps the rejected artifact in a `.rejected.json` sidecar -- which
    # made an absent competitor_verification.json ambiguous: "the run legitimately skipped
    # verification" and "verification ran and was refused" became the same evidence, and the second
    # is a defect the founder must be told about. HIGH, because the deliverable then presents an
    # unverified competitor set as a verified one and no other signal names the cause.
    "VERIFICATION_REJECTED": "high",
    "MISSING_DO_NOTHING": "medium",
    "RESEARCH_DEPTH_LOW": "medium",
    "MISSING_CANONICAL_MOAT": "medium",
    "INCOMPLETE_SCORING": "medium",
    "RESEARCHED_WITHOUT_SOURCE": "medium",
    "NO_RECENT_DEVELOPMENTS": "medium",
    # "low", not medium: by the time this fires, substitute() has already corrected the text, so the
    # report is clean and what remains is an authoring task. ic-sim / market-sizing / deck-review block
    # strict mode on medium, which would fail a run over an already-fixed issue. The fleet ratchet in
    # test_compose_invariants.py is the gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # A dated competitor move that fell outside the recency window. Dropped from
    # recent_developments and preserved under out_of_window_developments by
    # validate_landscape.py — reported so the exclusion is visible, never silent.
    "STALE_DEVELOPMENT": "medium",
    # A scored view ended up with an empty axis rationale. Emitted by score_positioning.py so a
    # blank rationale can never again pass the checklist's POS_05 unnoticed.
    "RATIONALE_MISSING": "medium",
    # A checklist item's echoed label does not match the item it was recorded under, so the
    # evidence behind that grade may belong to a different criterion. Medium, matching the
    # producer: checklist.py records the signal as new and uncalibrated (two known true
    # positives, no measured false-positive rate) and says to ratchet to an error only after
    # it has run clean on real runs. Raising it here alone would escalate an unmeasured signal
    # into a --strict blocker and split the judgement across two files — change both together.
    "CRITERION_MISMATCH": "medium",
    # Low
    "FOUNDER_OVERRIDE_COUNT": "low",
    # v0.4.2 Mitigation 2 — informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
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
    "CRITERION_MISMATCH": "Quality Check Recorded Against the Wrong Item",
    "SHALLOW_COMPETITOR_PROFILE": "Shallow Competitor Profile",
    "VANITY_AXIS_WARNING": "Vanity Axis Warning",
    "MOAT_WITHOUT_EVIDENCE": "Moat Without Evidence",
    "VERIFICATION_REJECTED": "Competitor Verification Rejected",
    "MISSING_DO_NOTHING": "Missing Do-Nothing Alternative",
    "RESEARCH_DEPTH_LOW": "Research Depth Low",
    "MISSING_CANONICAL_MOAT": "Missing Canonical Moat",
    "INCOMPLETE_SCORING": "Incomplete Scoring",
    "RESEARCHED_WITHOUT_SOURCE": "Researched Without Source",
    "NO_RECENT_DEVELOPMENTS": "No Recent Developments",
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "STALE_DEVELOPMENT": "Stale Development",
    "RATIONALE_MISSING": "Rationale Missing",
    "CHECKLIST_STALE_VS_POSITIONING": "Checklist Stale vs Positioning",
    "FOUNDER_OVERRIDE_COUNT": "Founder Override Count",
    "MARKER_COLLISION": "Marker Collision",
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
    # The adversarial competitor-set verdicts. Optional because a run may legitimately skip the
    # verification dispatch, but when present it MUST reach the deliverable: a competitor the
    # verification judged `not_a_competitor` was previously scored, ranked and tabled
    # indistinguishably from a genuine one, so the challenge survived only in chat.
    "competitor_verification.json",
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


def _founder_text_policy() -> Any:
    """Import the fleet's shared founder-text policy from `founder-skills/scripts/`.

    Parent-relative rather than duplicated: this file lives at
    `skills/<skill>/scripts/compose_report.py`, so `parents[2]/scripts` is the shared dir. Returns
    None if unavailable, because a missing policy module must never block a report — the scan is a
    warning, not a gate.
    """
    try:
        shared = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
        shared = os.path.normpath(shared)
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _competitor_names(landscape: dict[str, Any] | None) -> dict[str, str]:
    """Map competitor slug -> display name from landscape.json.

    Used so a rendered surface never shows a slug. Returns {} when the landscape is absent or
    unusable — callers fall back to the slug, which is worse but never wrong.
    """
    out: dict[str, str] = {}
    if not isinstance(landscape, dict):
        return out
    for comp in _as_list(landscape.get("competitors")):
        comp = _as_dict(comp)
        slug = comp.get("slug")
        name = comp.get("name")
        if isinstance(slug, str) and slug and isinstance(name, str) and name.strip():
            out[slug] = name.strip()
    return out


def _display_name(slug: str, name_by_slug: dict[str, str] | None) -> str:
    """Render a competitor's display name; fall back to the slug when unknown."""
    if slug == "_startup":
        return "This company"
    if name_by_slug:
        return name_by_slug.get(slug, slug)
    return slug


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
        "holds": "Holds",
        "partially_holds": "Partially holds",
        "does_not_hold": "Does not hold",
        "genuine": "Genuine competitor",
        "not_a_competitor": "Not a competitor",
        "keep": "Keep",
        "reclassify_adjacent": "Reclassify as adjacent",
        "challenge_removal": "Consider removing",
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


_SCORING_BASIS_LABELS: dict[str, str] = {
    "shipped": "Shipped / verifiable surface",
    "roadmap_12mo": "12-month roadmap",
    "mixed": "Mixed",
}


def _scoring_basis_label(value: Any) -> str:
    """Human-readable label for scoring_basis.

    Anything outside the three known tokens — including absence — renders as
    "Not declared" rather than defaulting to "shipped". An artifact produced
    before this field existed has a genuinely undefined basis; silently
    stamping "shipped" on it would assert a convention that was not in force
    when the coordinates were scored.
    """
    if isinstance(value, str) and value in _SCORING_BASIS_LABELS:
        return _SCORING_BASIS_LABELS[value]
    return "Not declared"


def _resolve_scoring_basis(
    positioning_scores: dict[str, Any] | None,
    positioning: dict[str, Any] | None,
) -> str | None:
    """Resolve the raw scoring_basis token.

    positioning_scores.json is the scored artifact and is authoritative for
    what convention actually produced the coordinates; positioning.json only
    carries the field on the founder-override re-pipe path, so it is the
    fallback rather than the primary source.
    """
    if _usable(positioning_scores):
        val = positioning_scores.get("scoring_basis")
        if isinstance(val, str) and val:
            return val
    if _usable(positioning):
        val = positioning.get("scoring_basis")
        if isinstance(val, str) and val:
            return val
    return None


def _md_escape(text: str) -> str:
    """Escape text for safe markdown table cell interpolation."""
    return text.replace("|", "\\|").replace("\n", " ")


def _truncate_evidence(text: str, max_len: int = 120) -> str:
    """Truncate long evidence strings for table cells."""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _warn(code: str, message: str, founder_message: str | None = None) -> dict[str, Any]:
    """Create a warning dict with code, message, and severity.

    `message` is agent-facing and unchanged in report.json. `founder_message`
    is an OPTIONAL additive key stating the founder-visible consequence in
    plain words (no artifact filename, no raw enum token) -- report.md
    renders it instead of `message` when present.
    """
    w: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }
    if founder_message is not None:
        w["founder_message"] = founder_message
    return w


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact.

    Returns None if missing, _CORRUPT if unparseable OR if the parsed top-level
    payload is not a JSON object (e.g. a list/string/number). Wrong-shape valid
    JSON degrades to the CORRUPT_ARTIFACT path rather than crashing downstream
    `.get()` access.
    """
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _CORRUPT
    if not isinstance(loaded, dict):
        return _CORRUPT
    return loaded


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
    """Count evidence_source == 'founder_override' across positioning coordinates."""
    count = 0
    for view in _as_list(positioning.get("views")):
        for point in _as_list(_as_dict(view).get("points")):
            p = _as_dict(point)
            if p.get("x_evidence_source") == "founder_override":
                count += 1
            if p.get("y_evidence_source") == "founder_override":
                count += 1
    return count


def _count_moat_founder_overrides(
    moat_scores: dict[str, Any] | None,
    positioning: dict[str, Any] | None,
) -> int:
    """Count evidence_source == 'founder_override' among moat ratings.

    Counts the UNION of two sources, deduplicated by (slug, moat id).

    moat_scores.json is the authoritative moat artifact: a founder moat
    override is re-piped through score_moats.py and lands there.
    positioning.json's moat_assessments block is a superseded draft that is
    never merged back, but an override may still have been recorded only
    there. Preferring one source would silently drop the override recorded
    in the other; counting both without a key would double-count the single
    founder decision that appears in both. The (slug, id) key does neither.
    """
    seen: set[tuple[str, str]] = set()

    def _collect(companies: dict[str, Any]) -> None:
        for slug, company_data in companies.items():
            for idx, moat in enumerate(_as_list(_as_dict(company_data).get("moats"))):
                m = _as_dict(moat)
                if m.get("evidence_source") != "founder_override":
                    continue
                moat_id = m.get("id")
                key = moat_id if isinstance(moat_id, str) and moat_id.strip() else f"#{idx}"
                seen.add((slug, key))

    if _usable(moat_scores):
        _collect(_as_dict(moat_scores.get("companies")))
    if _usable(positioning):
        _collect(_as_dict(_as_dict(positioning).get("moat_assessments")))
    return len(seen)


# score_positioning.py's _score_view() passes each view's input `points` straight
# through into positioning_scores.json (see that file's comment at the `points` key
# in its scored_view dict) — it never recomputes coordinates. That makes
# positioning_scores.json the authoritative post-scoring record of coordinates,
# NOT "aggregates only". positioning.json is supposed to be hand-merged back to
# match it (per SKILL.md's merge step); when that merge is skipped or partial, the
# two artifacts disagree and every downstream renderer (compose_report, visualize,
# explore) silently presents stale/placeholder coordinates while the aggregate
# scores still look valid. This tolerance absorbs float round-trip noise (JSON
# (de)serialization, an LLM re-emitting "60" as "60.0"), not real coordinate drift —
# on the validated 0-100 axis scale, a merge that actually updated the value moves
# it far more than this.
_POINT_MERGE_TOLERANCE = 0.01

# Mirrors the sentinel `score_moats.py` stamps into `comparison.startup_rank[dim]` when the startup is
# `not_applicable` on a dimension: {"rank": -1, "total": 0}. Named here so the renderer's guard says
# what it is guarding rather than testing a bare -1. Both sides are documented in
# references/artifact-schemas.md — a consumer that does not know the convention renders `Rank -1 of 0`.
_NOT_RANKABLE_RANK = -1

# ONE banding contract for `overall_differentiation`, because there were three.
#
# The headline label used these four tiers; Key Findings used three (no 25 boundary); and the summary
# paragraph gated its top tier on defensibility as well, directly beneath a comment asserting that the
# label and the paragraph never disagree. A report could call one score "Strong — clearly
# differentiated" and "moderate differentiation" two lines apart.
#
# The 25 boundary is KEPT rather than dropped: `gate3_triggers._LOW_DIFFERENTIATION_PCT` is 25.0 and
# drives the founder-facing Gate 3 prose, with a test pinning it. Dropping it here would desynchronise
# the delivered report from the gate the founder just answered.
_DIFFERENTIATION_BANDS: tuple[tuple[float, str], ...] = (
    (75.0, "strong"),
    (50.0, "moderate"),
    (25.0, "weak"),
    (float("-inf"), "undifferentiated"),
)


def _differentiation_band(score: Any) -> str | None:
    """The single source of truth for which differentiation tier a score falls in.

    Returns None for a non-numeric score so callers keep their existing "say nothing" behaviour rather
    than inventing a tier.
    """
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    for floor, name in _DIFFERENTIATION_BANDS:
        if score >= floor:
            return name
    return None


def _points_by_slug(points: list[Any]) -> dict[str, tuple[float, float]]:
    """Map competitor slug -> (x, y) from a view's points list.

    Skips malformed entries (non-dict, missing/non-string competitor, non-numeric
    x/y) rather than raising — callers treat absence as "nothing to compare".
    """
    out: dict[str, tuple[float, float]] = {}
    for p in points:
        p = _as_dict(p)
        slug = p.get("competitor")
        x, y = p.get("x"), p.get("y")
        if isinstance(slug, str) and slug and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            out[slug] = (float(x), float(y))
    return out


def validate_artifacts(
    artifacts: dict[str, dict[str, Any] | None],
    artifacts_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Run validation checks across artifacts. Returns list of warnings.

    `artifacts_dir` is optional and used only to look for a producer's rejection sidecar, which is
    evidence that exists on disk rather than inside any artifact. Callers that omit it lose only
    that one check.
    """
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
        # Provenance-checkable now that its stamp is the bare module name like every sibling's.
        # Optional artifact, and the loop below only inspects artifacts that are present, so a run
        # that legitimately skipped verification gains no failure mode.
        "competitor_verification.json": "verify_competitors",
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

    # 0b. CHECKLIST_STALE_VS_POSITIONING — the checklist graded a map that has since moved.
    # checklist.py copies the positioning_scores views_fingerprint it read into
    # graded_against; a mismatch means positioning was re-scored without re-running the
    # checklist. Absent on either side is SILENT — an artifact predating the field has a
    # genuinely unknown provenance and must not be asserted to be either fresh or stale.
    checklist_art = artifacts.get("checklist.json")
    if _usable(positioning_scores) and _usable(checklist_art):
        current_fp = positioning_scores.get("views_fingerprint")
        graded_fp = _as_dict(checklist_art.get("graded_against")).get("views_fingerprint")
        if (
            isinstance(current_fp, str)
            and current_fp
            and isinstance(graded_fp, str)
            and graded_fp
            and current_fp != graded_fp
        ):
            warnings.append(
                _warn(
                    "CHECKLIST_STALE_VS_POSITIONING",
                    "checklist.json was graded against a different positioning map than the "
                    "current positioning_scores.json (fingerprint mismatch) — re-run "
                    "checklist.py against the current scores before composing",
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

    # 1b. VERIFICATION_REJECTED — the sidecar the producer leaves when it refuses its input.
    #
    # `competitor_verification.json` is optional because a run may legitimately skip the
    # verification dispatch, so its absence carries no warning. Once the producer stopped writing
    # the canonical file on rejection (it keeps the audit copy beside it instead), "skipped" and
    # "ran and was refused" became indistinguishable from the artifact list alone -- and the second
    # ships a competitor set the report presents as verified when nothing verified it. The sidecar
    # is the evidence that tells them apart.
    if artifacts_dir:
        rejected = os.path.join(artifacts_dir, "competitor_verification.json.rejected.json")
        if os.path.exists(rejected) and not _usable(artifacts.get("competitor_verification.json")):
            warnings.append(
                _warn(
                    "VERIFICATION_REJECTED",
                    "The competitor-set verification was run and REJECTED — the competitor set in "
                    "this report has not been independently checked. Re-dispatch the verification "
                    "and re-run the producer before treating the set as verified.",
                )
            )

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
                            founder_message=(
                                f"'{ls}' is listed as a competitor but wasn't scored on moat "
                                "strength, so the moat comparison across competitors is "
                                "incomplete and may be skewed."
                            ),
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
                            founder_message=(
                                f"'{ls}' is listed as a competitor but doesn't appear on the "
                                "positioning map, so the map doesn't show where they sit "
                                "relative to everyone else."
                            ),
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

    # 3c. Merge integrity — per-competitor coordinates in positioning.json must
    # match the points carried through positioning_scores.json (see
    # _POINT_MERGE_TOLERANCE above for why positioning_scores.json is authoritative
    # here). Checked per view id, per competitor slug, so a PARTIAL merge — some
    # competitors updated, one left stale — is caught, not just an all-or-nothing
    # miss. A view missing from positioning_scores entirely is already reported by
    # the 3b axis-consistency check above; a positioning_scores view carrying no
    # `points` at all (an older artifact predating the passthrough convention)
    # degrades explicitly here — skipped, not crashed, not false-flagged.
    if _usable(positioning) and _usable(positioning_scores):
        scores_views_by_id: dict[Any, dict[str, Any]] = {
            _as_dict(v).get("view_id"): _as_dict(v) for v in _as_list(positioning_scores.get("views"))
        }
        for view in _as_list(positioning.get("views")):
            view = _as_dict(view)
            vid = view.get("id")
            score_view = scores_views_by_id.get(vid)
            if score_view is None:
                continue

            score_points_raw = score_view.get("points")
            if not isinstance(score_points_raw, list):
                continue  # older artifact with no points passthrough — nothing to cross-check

            pos_points = _points_by_slug(_as_list(view.get("points")))
            score_points = _points_by_slug(score_points_raw)

            mismatched = sorted(
                slug
                for slug, (px, py) in pos_points.items()
                if slug in score_points
                and (
                    abs(px - score_points[slug][0]) > _POINT_MERGE_TOLERANCE
                    or abs(py - score_points[slug][1]) > _POINT_MERGE_TOLERANCE
                )
            )
            if mismatched:
                warnings.append(
                    _warn(
                        "CORRUPT_ARTIFACT",
                        f"View '{vid}': positioning.json coordinates for {mismatched} differ from "
                        "positioning_scores.json — the scored merge back into positioning.json was "
                        "skipped or partial; the report would show stale/placeholder coordinates "
                        "instead of the scored values",
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

    # Forward from checklist. This loop was missing: checklist.py emitted CRITERION_MISMATCH
    # into checklist.json and nothing downstream ever read it, so the newest integrity check in
    # this skill produced a warning no founder or agent saw. Note it forwards `founder_message`
    # explicitly — the agent-facing `message` names a criterion ID, and report.md may not carry
    # one (verify_positioning.py fails the delivery gate on it), so registering the severity
    # without this argument would have traded a silent warning for an unpublishable report.
    if _usable(checklist_art):
        for w in _as_list(checklist_art.get("warnings")):
            w = _as_dict(w)
            code = w.get("code", "")
            if code in WARNING_SEVERITY:
                warnings.append(
                    _warn(
                        code,
                        w.get("message", f"Forwarded from checklist: {code}"),
                        w.get("founder_message"),
                    )
                )

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
                            founder_message=(
                                f"The profile for '{slug}' is based on limited research — only "
                                f"{sfc} verified data points (fewer than the usual minimum of 3). "
                                "Treat any comparison involving them as preliminary until more "
                                "information is gathered."
                            ),
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
    if _usable(checklist):
        # Prefer summary block (post-v0.4.2), fall back to legacy flat fields.
        cl_summary = _as_dict(checklist.get("summary"))
        if cl_summary:
            fail_c = cl_summary.get("fail", 0)
            warn_c = cl_summary.get("warn", 0)
        else:
            fail_c = checklist.get("fail_count", 0)
            warn_c = checklist.get("warn_count", 0)
        if fail_c == 0 and warn_c == 0:
            warnings.append(_warn("CHECKLIST_ALL_PASS", "All checklist items passed — review for self-grading bias"))

    # 10. FOUNDER_OVERRIDE_COUNT
    coordinate_overrides = _count_founder_overrides(positioning) if _usable(positioning) else 0
    moat_overrides = _count_moat_founder_overrides(moat_scores, positioning)
    override_count = coordinate_overrides + moat_overrides
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
            diff_label = {
                "strong": "Strong — clearly differentiated from the competitive set",
                "moderate": "Moderate — differentiated but the lead is narrow",
                "weak": "Weak — positioned close to competitors on key axes",
                "undifferentiated": "Undifferentiated — clustered with competitors",
            }.get(_differentiation_band(diff_score) or "", "Undifferentiated — clustered with competitors")
            lines.append(f"**Overall Differentiation Score:** {diff_score}% ({diff_label})")

    defensibility = None
    if moat_scores is not None and not _is_stub(moat_scores):
        startup_data = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        defensibility = startup_data.get("overall_defensibility")
        if defensibility:
            lines.append(f"**Startup Defensibility:** {defensibility.replace('_', ' ').title()}")

    checklist_score = None
    if checklist is not None and not _is_stub(checklist):
        # Prefer summary block (post-v0.4.2), fall back to legacy flat field.
        cl_summary = _as_dict(checklist.get("summary"))
        checklist_score = cl_summary.get("score_pct") if cl_summary else checklist.get("score_pct")
        if checklist_score is not None:
            lines.append(f"**Analysis Quality Score:** {checklist_score}%")

    # Summary paragraph
    lines.append("")
    if diff_score is not None and defensibility is not None:
        # Banded from `_differentiation_band` so this paragraph cannot disagree with the label above.
        # The previous version added `and defensibility in ("high","moderate")` to its top arm — under a
        # comment claiming the two never disagree — so a 90% score with low defensibility was labelled
        # "Strong" and then described as "moderate differentiation" two lines below. Defensibility is
        # STATED in the sentence rather than used to demote the differentiation tier: they are two
        # different findings, and collapsing one into the other is what produced the contradiction.
        if _differentiation_band(diff_score) == "strong":
            lines.append(
                "The startup shows strong competitive differentiation with "
                f"{defensibility} defensibility. The positioning analysis "
                "suggests a clear value proposition relative to the competitive set."
            )
        elif _differentiation_band(diff_score) == "moderate":
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

    # `pricing_model` is researched per competitor and belongs in the table: how a rival charges is
    # part of the competitive picture a founder is reading this for, and researching it without
    # showing it is work the founder paid for and cannot see.
    # `funding` belongs here for the same reason `pricing_model` does, and more sharply: relative
    # capital is often the competitive fact a founder most needs, it is researched for every
    # competitor, and before this column it reached the delivered report only when the agent happened
    # to mention it in prose — measured at 0, 1, 47 and 25 mentions across four runs of the same
    # pipeline. A field that surfaces by luck is not delivered.
    lines.append("| Name | Category | Pricing | Funding | Research Depth | Sourced Fields |")
    lines.append("|------|----------|---------|---------|---------------|----------------|")
    for c in competitors:
        c = _as_dict(c)
        name = c.get("name", "?")
        cat = _humanize(str(c.get("category", "?")))
        rd = _humanize(str(c.get("research_depth", "?")))
        sfc = c.get("sourced_fields_count", "?")
        pricing = str(c.get("pricing_model", "") or "").strip().replace("|", "\\|") or "—"
        if len(pricing) > 60:
            pricing = pricing[:57].rstrip() + "..."
        # Same coercion as pricing: `or ""` catches a null BEFORE str() turns it into "None", and the
        # trailing `or "—"` catches a value that was present but empty.
        funding = str(c.get("funding", "") or "").strip().replace("|", "\\|") or "—"
        if len(funding) > 60:
            funding = funding[:57].rstrip() + "..."
        lines.append(f"| {name} | {cat} | {pricing} | {funding} | {rd} | {sfc} |")

    return "\n".join(lines) + "\n"


def _section_recent_developments(landscape: dict[str, Any] | None) -> str:
    """Recent competitor developments (funding, launches, leadership moves, etc.),
    grouped by competitor and sorted most-recent-first. Every entry here is
    dated and sourced (validate_landscape.py enforces both) — omit the section
    entirely when no competitor has any, rather than printing an empty heading.
    """
    if landscape is None or _is_stub(landscape):
        return ""

    entries: list[tuple[str, dict[str, Any]]] = []
    for c in _as_list(landscape.get("competitors")):
        c = _as_dict(c)
        name = str(c.get("name") or c.get("slug") or "?")
        for dev in _as_list(c.get("recent_developments")):
            dev = _as_dict(dev)
            if dev:
                entries.append((name, dev))

    if not entries:
        return ""

    entries.sort(key=lambda pair: str(pair[1].get("date", "")), reverse=True)

    lines = ["## What's Changed Recently\n"]
    as_of = landscape.get("landscape_as_of")
    if as_of:
        lines.append(f"**As Of:** {as_of}\n")
    for name, dev in entries:
        date_str = dev.get("date", "?")
        type_label = _humanize(str(dev.get("type", "?")))
        summary = _md_escape(str(dev.get("summary", "?")))
        lines.append(f"- **{date_str}** — {_md_escape(name)} ({type_label}): {summary}")
        relevance = dev.get("relevance")
        if isinstance(relevance, str) and relevance.strip():
            lines.append(f"  - Why it matters: {_md_escape(relevance)}")
        source = dev.get("source")
        if isinstance(source, str) and source.strip():
            lines.append(f"  - Source: {source}")
    lines.append("")

    return "\n".join(lines) + "\n"


def _overlap_summary(overlap: Any) -> str:
    """Render the substitution test's three dimensions as the axes that matched.

    The verdict alone says "adjacent"; this says on what — a competitor sharing the buyer but not the
    job is a different conversation from one sharing the job but not the buyer.
    """
    data = _as_dict(overlap)
    if not data:
        return "—"
    labels = {"buyer": "buyer", "job_to_be_done": "job", "category": "category"}
    matched = [label for key, label in labels.items() if data.get(key) is True]
    if not matched:
        return "none"
    if len(matched) == len(labels):
        return "buyer, job, category"
    return ", ".join(matched)


def _section_competitor_verification(
    competitor_verification: dict[str, Any] | None,
    name_by_slug: dict[str, str] | None = None,
    landscape: dict[str, Any] | None = None,
) -> str:
    """Adversarial competitor-set verification: the per-competitor verdicts and the blind-recall gaps.

    This section exists because the verdicts previously reached the founder only in chat. A
    competitor the verification judged `not_a_competitor` was still scored on every axis, counted in
    every moat denominator, and tabled indistinguishably from a genuine one — so the single most
    valuable check in the run left no trace in the artifact the founder keeps. A founder who
    overrode a flag should see that decision recorded, not silently normalised away.
    """
    if competitor_verification is None or _is_stub(competitor_verification):
        return ""

    verdicts = [_as_dict(v) for v in _as_list(competitor_verification.get("verdicts"))]
    recall = _as_dict(competitor_verification.get("recall_gaps"))
    if not verdicts and not recall:
        return ""

    lines = ["## Competitor Set Verification\n"]
    lines.append(
        "Each competitor below was independently re-researched by a separate pass that did not see "
        "the drafted list, and judged on whether the same buyer would weigh both for the same job."
    )
    lines.append("")

    if verdicts:
        summary = _as_dict(competitor_verification.get("summary"))
        genuine = summary.get("genuine")
        flagged = summary.get("flagged")
        if isinstance(genuine, int) and isinstance(flagged, int):
            lines.append(f"**{genuine} confirmed as genuine competitors; {flagged} came up for a second look.**")
            lines.append("")
        lines.append("| Competitor | Verdict | Overlap | Confidence | Why |")
        lines.append("|------------|---------|---------|------------|-----|")
        for v in verdicts:
            slug = str(v.get("slug", "?"))
            verdict = _humanize(str(v.get("verdict", "?")))
            reasoning = str(v.get("reasoning", "") or "").strip().replace("|", "\\|")
            if len(reasoning) > 300:
                reasoning = reasoning[:297].rstrip() + "..."
            lines.append(
                f"| {_display_name(slug, name_by_slug)} | {verdict} | {_overlap_summary(v.get('overlap'))} "
                f"| {_humanize(str(v.get('confidence', '') or '')) or '—'} | {reasoning or '—'} |"
            )
        lines.append("")
        kept = [v for v in verdicts if str(v.get("verdict")) == "not_a_competitor"]
        if kept:
            names = ", ".join(_display_name(str(v.get("slug", "?")), name_by_slug) for v in kept)
            lines.append(
                f"**Retained despite the challenge:** {names}. This entry is scored and ranked "
                f"alongside the rest, so read its position with the verdict above in mind."
            )
            lines.append("")

        # Competitors in the final set with NO verdict. The verification pass runs BEFORE the founder
        # confirms the competitor set, so anything approved at a gate is never challenged — measured
        # live at 6 verdicts against 9 competitors, the three absent being exactly the three added at a
        # gate. On another run the unverified set included the competitor the skill itself flagged as
        # directly rebutting the deck's central claim. Saying so does not verify them; it stops the
        # section implying they were, which is what a table of verdicts with no mention of the
        # remainder does.
        verified_slugs = {str(v.get("slug")) for v in verdicts}
        unverified = [
            c
            for c in (_as_dict(x) for x in _as_list(_as_dict(landscape).get("competitors")))
            if str(c.get("slug")) and str(c.get("slug")) not in verified_slugs
        ]
        if unverified:
            names = ", ".join(
                _display_name(str(c.get("slug", "?")), name_by_slug) or str(c.get("name", "?")) for c in unverified
            )
            lines.append(
                f"**Not independently challenged:** {names}. "
                f"{'This competitor was' if len(unverified) == 1 else 'These competitors were'} added after "
                f"the verification pass had run, so {'it has' if len(unverified) == 1 else 'they have'} not "
                f"been through it. {'It is' if len(unverified) == 1 else 'They are'} scored and ranked "
                f"alongside the rest."
            )
            lines.append("")

    unmatched = [_as_dict(u) for u in _as_list(recall.get("unmatched"))]
    if unmatched:
        lines.append("### Companies an independent search surfaced\n")
        lines.append(
            "Found by a pass that never saw the drafted list. Not omissions — candidates worth a second thought."
        )
        lines.append("")
        for u in unmatched:
            label = str(u.get("name", u.get("slug", "?")))
            why = str(u.get("why_considered", "") or "").strip()
            if len(why) > 240:
                why = why[:237].rstrip() + "..."
            overlap = u.get("possible_overlap_with")
            note = ""
            if isinstance(overlap, str) and overlap:
                note = f" (may already be covered by {_display_name(overlap, name_by_slug)})"
            lines.append(f"- **{label}**{note} — {why}")
        lines.append("")

    dupes = [_as_dict(d) for d in _as_list(recall.get("probable_duplicates"))]
    if dupes:
        lines.append(
            f"*{len(dupes)} further candidate(s) matched a competitor already in the set and were "
            f"set aside as duplicates.*"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_positioning(
    positioning_scores: dict[str, Any] | None,
    positioning: dict[str, Any] | None = None,
) -> str:
    """Positioning analysis with per-view details and evidence points table."""
    if positioning_scores is None or _is_stub(positioning_scores):
        return "## Positioning Analysis\n\n*No positioning scores available.*\n"

    lines = ["## Positioning Analysis\n"]
    basis_label = _scoring_basis_label(_resolve_scoring_basis(positioning_scores, positioning))
    lines.append(f"**Scoring Basis:** {basis_label}\n")
    overall = positioning_scores.get("overall_differentiation")
    if overall is not None:
        lines.append(f"**Overall Differentiation:** {overall}%\n")

    # Build a lookup: view_id → points list from positioning.json
    pos_views_by_id: dict[str, list[dict[str, Any]]] = {}
    if _usable(positioning):
        for pv in _as_list(positioning.get("views")):
            pv = _as_dict(pv)
            vid_key = str(pv.get("id", ""))
            if vid_key:
                pos_views_by_id[vid_key] = _as_list(pv.get("points"))

    for view in _as_list(positioning_scores.get("views")):
        view = _as_dict(view)
        vid_key = str(view.get("view_id", ""))
        # Prefer an explicit human-readable label; fall back to title-casing the id. Real runs use
        # descriptive slug ids, and title-casing a slug leaks it into a founder-facing heading.
        vid = str(view.get("label") or "").strip() or str(view.get("view_id", "?")).title()
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
        # `_compute_rank` counts competitors strictly ahead, +1 — so rank `competitor_count + 1`
        # is reachable and means "behind every competitor". Rendering that against
        # `competitor_count` produced the literal nonsense "Y=11 (of 10 competitors)". Report the
        # denominator as the number of entities actually ranked, startup included, which is also
        # the convention the moat section uses.
        _ccount = view.get("competitor_count")
        _ranked = f"{_ccount + 1}" if isinstance(_ccount, int) else "?"
        lines.append(
            f"- **Startup Rank:** X={view.get('startup_x_rank', '?')}, "
            f"Y={view.get('startup_y_rank', '?')} "
            f"(of {_ranked} ranked)"
        )
        lines.append("")

        # Points evidence table (from positioning.json views[].points[])
        points = pos_views_by_id.get(vid_key, [])
        if points:
            x_name = view.get("x_axis_name", "X")
            y_name = view.get("y_axis_name", "Y")
            lines.append(
                f"| Company | {_md_escape(x_name)} | {_md_escape(y_name)} "
                f"| {_md_escape(x_name)} evidence | {_md_escape(y_name)} evidence |"
            )
            lines.append("|---------|------|------|------------|------------|")
            for pt in points:
                pt = _as_dict(pt)
                slug = pt.get("competitor", "?")
                x_val = pt.get("x", "?")
                y_val = pt.get("y", "?")
                x_ev = _md_escape(_truncate_evidence(str(pt.get("x_evidence", ""))))
                y_ev = _md_escape(_truncate_evidence(str(pt.get("y_evidence", ""))))
                lines.append(f"| {_md_escape(slug)} | {x_val} | {y_val} | {x_ev} | {y_ev} |")
            lines.append("")

    return "\n".join(lines) + "\n"


def _section_moat_assessment(
    moat_scores: dict[str, Any] | None,
    name_by_slug: dict[str, str] | None = None,
) -> str:
    """Moat assessment section with evidence, leader context, and per-dimension matrix.

    `name_by_slug` maps competitor slug -> display name so rendered leader references show a name
    rather than an internal slug; when omitted the slug is used.
    """
    if moat_scores is None or _is_stub(moat_scores):
        return "## Moat Assessment\n\n*No moat scores available.*\n"

    lines = ["## Moat Assessment\n"]

    companies = _as_dict(moat_scores.get("companies"))
    startup = _as_dict(companies.get("_startup"))
    # Competitor slugs (exclude _startup for leader lookup)
    competitor_slugs = [k for k in companies if k != "_startup"]

    if startup:
        defensibility = _humanize(str(startup.get("overall_defensibility", "?")))
        strongest = _humanize(str(startup.get("strongest_moat", "none")))
        lines.append(f"**Overall Defensibility:** {defensibility}")
        lines.append(f"**Strongest Moat:** {strongest}")
        lines.append("")

        # Moat table for _startup — with evidence text as a bullet under each row
        lines.append("| Moat | Status | Trajectory | Evidence Source |")
        lines.append("|------|--------|------------|----------------|")
        moat_evidence_pairs: list[tuple[str, str]] = []
        for moat in _as_list(startup.get("moats")):
            moat = _as_dict(moat)
            mid = _humanize(str(moat.get("id", "?")))
            status = _humanize(str(moat.get("status", "?")))
            traj = _humanize(str(moat.get("trajectory", "?")))
            src = _humanize(str(moat.get("evidence_source", "?")))
            lines.append(f"| {mid} | {status} | {traj} | {src} |")
            evidence_text = str(moat.get("evidence", "")).strip()
            if evidence_text:
                moat_evidence_pairs.append((mid, evidence_text))
        lines.append("")

        # Evidence bullets under the table
        if moat_evidence_pairs:
            lines.append("**Evidence:**")
            for mid, ev in moat_evidence_pairs:
                lines.append(f"- **{mid}:** {_truncate_evidence(ev, 200)}")
            lines.append("")

    # Comparison highlights — with leader context appended
    comparison = _as_dict(moat_scores.get("comparison"))
    startup_rank = _as_dict(comparison.get("startup_rank"))
    by_dimension = _as_dict(comparison.get("by_dimension"))
    if startup_rank:
        lines.append("### Startup Ranking by Moat Dimension\n")
        for dim, rank_info in startup_rank.items():
            ri = _as_dict(rank_info)
            rank_val = ri.get("rank", "?")
            total_val = ri.get("total", "?")
            # `score_moats.py` stamps {"rank": -1, "total": 0} when the STARTUP is `not_applicable`
            # on this dimension — a producer sentinel meaning "not rankable", correct in the artifact
            # and documented in references/artifact-schemas.md. Rendered verbatim it produced
            # `Rank -1 of 0 ranked` in delivered reports. Say the thing the sentinel means instead of
            # dropping the line: `not_applicable` asserts the moat type does not structurally apply
            # to this business model (references/moat-definitions.md), which is worth telling a
            # founder. No leader is offered, because there is no comparison to lead.
            if rank_val == _NOT_RANKABLE_RANK or total_val == 0:
                lines.append(f"- **{_humanize(dim)}:** Not applicable to this business model")
                continue
            # Identify the leader: competitor with the strongest status in this dimension
            leader_name: str | None = None
            leader_status: str | None = None
            _status_order = {"strong": 0, "moderate": 1, "weak": 2, "absent": 3, "not_applicable": 4}
            dim_scores = _as_dict(by_dimension.get(dim))
            for slug in competitor_slugs:
                s = dim_scores.get(slug, "absent")
                if leader_name is None or _status_order.get(s, 99) < _status_order.get(leader_status or "absent", 99):
                    leader_name = slug
                    leader_status = s
            leader_note = ""
            # `not_applicable` sorts last, so it wins only when EVERY competitor is unassessed on this
            # dimension — "leader: X (N/A)" is not leadership, it is nobody being assessed.
            if leader_name and leader_status and leader_status != "not_applicable" and rank_val != 1:
                # Render the competitor's display name, never its slug — a slug in the
                # deliverable is an internal token the founder has no use for.
                leader_note = f" — leader: {_display_name(leader_name, name_by_slug)} ({_humanize(leader_status)})"
            lines.append(f"- **{_humanize(dim)}:** Rank {rank_val} of {total_val} ranked{leader_note}")
        lines.append("")

    # Per-dimension comparison matrix (rows=companies, cols=6 canonical moat dimensions)
    canonical_dims = [
        "network_effects",
        "data_advantages",
        "switching_costs",
        "regulatory_barriers",
        "cost_structure",
        "brand_reputation",
    ]
    _status_short = {
        "strong": "S",
        "moderate": "M",
        "weak": "W",
        "absent": "—",
        "not_applicable": "N/A",
    }
    # Collect all company slugs including _startup
    all_slugs = ["_startup"] + competitor_slugs
    if all_slugs and by_dimension:
        lines.append("### Moat Dimension Comparison Matrix\n")
        header_dims = " | ".join(_humanize(d)[:12] for d in canonical_dims)
        lines.append(f"| Company | {header_dims} |")
        lines.append("|---------|" + "|".join(["-------"] * len(canonical_dims)) + "|")
        for slug in all_slugs:
            row_data = []
            for dim in canonical_dims:
                dim_map = _as_dict(by_dimension.get(dim))
                val = dim_map.get(slug, "—")
                row_data.append(_status_short.get(val, val[:3] if isinstance(val, str) else "—"))
            display = "_startup_" if slug == "_startup" else slug
            lines.append(f"| {display} | " + " | ".join(row_data) + " |")
        lines.append("")
        lines.append("_Legend: S=Strong, M=Moderate, W=Weak, —=Absent, N/A=Not Applicable_")
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
        lines.append(f"- **Verdict:** {_humanize(str(verdict))}")
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
        band = _differentiation_band(overall)
        if band is not None:
            # Same banding as the headline label. This chain previously had only three tiers — no 25
            # boundary — so a score of 24 and a score of 26 changed the headline and not this line.
            if band == "strong":
                findings.append(
                    f"Strong differentiation ({overall}%) — the startup occupies "
                    "a distinct position in the competitive landscape."
                )
            elif band == "moderate":
                findings.append(
                    f"Moderate differentiation ({overall}%) — some positioning overlap exists with competitors."
                )
            elif band == "weak":
                findings.append(
                    f"Weak differentiation ({overall}%) — the startup sits close to competitors on key axes."
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
        # Prefer summary block (post-v0.4.2), fall back to legacy flat field.
        cl_summary = _as_dict(checklist.get("summary"))
        score = cl_summary.get("score_pct") if cl_summary else checklist.get("score_pct")
        if isinstance(score, (int, float)):
            # READ the status checklist.py already computed; do not re-derive it from the number.
            # This chain used to band at 80/60 while checklist.py bands at 85/70/50 — the canon
            # documented at SKILL.md's Scoring section and shared with deck-review for cross-skill
            # parity. At 82% the checklist called a run "solid" and this line called it "thorough".
            # Two thresholds for one number is a bug that recurs every time both sides are edited;
            # one side owning the banding is the only version that stays fixed.
            status = str(cl_summary.get("overall_status", "") or "").lower()
            phrasing = {
                "strong": "indicates a thorough competitive analysis.",
                "solid": "is solid — a few gaps remain in the competitive analysis.",
                "needs_work": "— some gaps remain in the competitive analysis.",
                "major_revision": "— significant gaps in the competitive analysis need attention.",
            }
            # Absent/unknown status falls back to the most cautious phrasing rather than the most
            # flattering: an unreadable checklist is not evidence of a thorough analysis.
            tail = phrasing.get(status, "— significant gaps in the competitive analysis need attention.")
            findings.append(f"Analysis quality score of {score}% {tail}")

    if not findings:
        lines.append("No key findings generated.\n")
    else:
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. {f}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _substitute_slugs(text: str, name_by_slug: dict[str, str] | None) -> str:
    """Replace competitor slugs with display names in founder-visible prose.

    Producers author their warning `message` strings as prose and legitimately quote the slug of
    the competitor at fault — the slug is what a producer HAS. Rewriting every producer's message
    to carry a name would mean a warnings-schema change across five-plus scripts and would fight
    the code+message pairing tests, so the substitution happens once here, at the render boundary,
    where the landscape's slug -> name map is already in hand.

    Longest slug first, so a slug that is a prefix of another cannot be partially replaced.
    """
    if not name_by_slug:
        return text
    for slug in sorted(name_by_slug, key=len, reverse=True):
        name = name_by_slug[slug]
        text = re.sub(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", name, text)
    return text


def _section_warnings(
    warnings: list[dict[str, Any]],
    name_by_slug: dict[str, str] | None = None,
) -> str:
    """Validation warnings from cross-artifact checks.

    `name_by_slug` substitutes competitor display names into producer-authored message text; a
    slug in the warnings list is as unusable to a founder as one in a heading.
    """
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
        msg = _substitute_slugs(str(w.get("founder_message") or w.get("message", "?")), name_by_slug)
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main composition
# ---------------------------------------------------------------------------


def _emit_coaching_payload(
    product_profile: dict[str, Any],
    checklist: dict[str, Any],
    warnings: list[dict[str, Any]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
    moat_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v0.4.2 coaching_payload for competitive-positioning.

    Read from existing artifacts; do not fabricate fields.
    No stage or is_ai_company fields (no analog in this skill).

    `defensibility` carries the scored moat picture because the coaching agent is
    asked for "the single highest-leverage fix to improve defensibility" and a
    "defensibility roadmap: which moats to invest in, in what order" — while being
    forbidden to read report.md. Without these numbers it can only invent moat
    claims, and its commentary is appended to the same investor-facing report that
    carries the scored table, so an invented claim lands next to the real one.
    """
    summary = _as_dict(checklist.get("summary"))
    startup = _as_dict(_as_dict(_as_dict(moat_scores).get("companies")).get("_startup"))
    defensibility = {
        "moat_count": startup.get("moat_count"),
        "strongest_moat": startup.get("strongest_moat"),
        "overall_defensibility": startup.get("overall_defensibility"),
        # Per-dimension statuses, so "which moats to invest in, in what order"
        # can be answered from the scores rather than guessed.
        "moats": [
            {
                "id": moat.get("id"),
                "status": moat.get("status"),
            }
            for moat in _as_list(startup.get("moats"))
            if isinstance(moat, dict)
        ],
    }
    return {
        "defensibility": defensibility,
        "schema_version": "v0.4.2-competitive-positioning",
        "summary": {
            "score_pct": summary.get("score_pct"),
            "overall_status": summary.get("overall_status"),
            "total": summary.get("total"),
            "pass": summary.get("pass"),
            "fail": summary.get("fail"),
            "warn": summary.get("warn"),
            "not_applicable": summary.get("not_applicable"),
        },
        "failed_items": summary.get("failed_items", []),
        "warned_items": summary.get("warned_items", []),
        # Each entry carries a human LABEL beside the code. A bare code list is a latent nudge:
        # the coaching sub-agent is handed `NARR_03`-shaped tokens with nothing else to call them
        # by, and then asked to write founder-facing prose. `failed_items` already pairs its id
        # with a prose `criterion`; this did not, and it is the same class of pressure.
        "high_severity_warnings": [
            {"code": w["code"], "label": _humanize_warning(w["code"]), "message": w.get("message", "")}
            for w in warnings
            if w.get("severity") == "high"
        ],
        "company_name": product_profile.get("company_name"),
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

    # Normalize positioning.json before validation (best-effort)
    positioning_raw = artifacts.get("positioning.json")
    if _usable(positioning_raw):
        _normalize_positioning(positioning_raw)

    artifacts_loaded = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]

    # Run validation
    warnings = validate_artifacts(artifacts, dir_path)

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
    competitor_verification = _render_safe(artifacts.get("competitor_verification.json"))

    # Assemble report sections — render everything EXCEPT the Warnings section
    # first. The Warnings section must be spliced in only after the marker
    # prescan has had a chance to append MARKER_COLLISION, otherwise that
    # warning would never reach the rendered ## Warnings list.
    name_by_slug = _competitor_names(landscape)
    sections = [
        _section_title(product_profile, landscape),
        _section_executive_summary(product_profile, positioning_scores, moat_scores, checklist),
        _section_competitor_landscape(landscape),
        _section_recent_developments(landscape),
        _section_competitor_verification(competitor_verification, name_by_slug, landscape),
        _section_positioning(positioning_scores, positioning_safe),
        _section_moat_assessment(moat_scores, name_by_slug),
        _section_stress_test(positioning_scores),
        _section_key_findings(positioning_scores, moat_scores, checklist),
    ]

    report_markdown = "\n".join(s for s in sections if s)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan: check the assembled body BEFORE appending the marker (otherwise
    # we always find our own emission) and BEFORE rendering the Warnings section
    # (so the prescan only inspects report body content, not our own warning
    # text). Agent post-Edit verification uses the EXACT uuid (per-run), so
    # substring collisions with body content are informational only — but worth
    # flagging so authors can sanitize.
    if "<!-- COACHING_INSERTION_POINT_" in report_markdown:
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

    # Splice the Warnings section now that MARKER_COLLISION (if any) is in the
    # warnings list. _section_warnings filters to high/medium/acknowledged only,
    # so the low-severity MARKER_COLLISION still won't surface in the report,
    # but the data flow is now correct for any future reportable warning the
    # prescan might add.
    warnings_section = _section_warnings(warnings, name_by_slug)
    if warnings_section:
        report_markdown += "\n" + warnings_section

    # --- founder-text policy: substitute, then scan what remains --------------------------------
    # MUST run after the Warnings section is spliced in. compose assembles the body first and appends
    # warnings last (so the marker prescan sees only body content), and the warnings are exactly where
    # the internal tokens live — producer messages naming a field. Hooking in before the splice
    # substitutes nothing and then reports a clean body.
    #
    # It runs HERE, on the assembled markdown, rather than in CI over fixtures: a fixture is
    # schema-correct by construction, so a fixture-only scan answers "does the renderer behave on good
    # input" — not the question any measured defect lived in. This is the string the founder reads.
    _ft = _founder_text_policy()
    if _ft is not None:
        report_markdown = _ft.substitute(report_markdown)
        # Our own warning codes are kept: compose renders them in small print beside a humanized
        # label (the md_term convention), which is deliberate. A code leaking anywhere else is
        # caught by the skill's own gate, not by widening this scan into a false positive.
        found = _ft.scan(report_markdown, extra_keep=frozenset(WARNING_SEVERITY))
        for token in found["enums"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report contains the internal token '{token}' — a founder cannot act on it; "
                    f"render it through the shared founder-text policy or stop emitting it",
                )
            )
        for name in found["filenames"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report names the internal file '{name}' — drop the reference rather than renaming it",
                )
            )

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Competitive Positioning Coach"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
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
    founder_override_count += _count_moat_founder_overrides(moat_scores, positioning_safe)

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
        # Prefer summary block (post-v0.4.2), fall back to legacy flat field.
        cl_summary = _as_dict(checklist.get("summary"))
        checklist_score_pct = cl_summary.get("score_pct", 0.0) if cl_summary else checklist.get("score_pct", 0.0)

    overall_differentiation = 0.0
    if positioning_scores is not None and not _is_stub(positioning_scores):
        overall_differentiation = positioning_scores.get("overall_differentiation", 0.0)

    startup_defensibility = "unknown"
    if moat_scores is not None and not _is_stub(moat_scores):
        startup_data = _as_dict(_as_dict(moat_scores.get("companies")).get("_startup"))
        startup_defensibility = startup_data.get("overall_defensibility", "unknown")

    scoring_basis_label = _scoring_basis_label(_resolve_scoring_basis(positioning_scores, positioning_safe))

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

    # v0.4.2 Mitigation 2: structured coaching payload for Context B agent.
    # Use the same uuid marker generated above as the single source of truth.
    resolved_report_path = report_path or os.path.join(os.path.abspath(dir_path), "report.md")
    coaching_payload = _emit_coaching_payload(
        product_profile=_as_dict(product_profile),
        checklist=_as_dict(checklist),
        warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
        moat_scores=_as_dict(moat_scores) if _usable(moat_scores) else None,
    )

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
            "scoring_basis": scoring_basis_label,
        },
        "coaching_payload": coaching_payload,
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

    _write_output(
        out,
        args.output,
        summary={
            "warnings": len(result["warnings"]),
            "artifacts_loaded": len(result["artifacts_loaded"]),
        },
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
        blocking = [w for w in result["warnings"] if w["severity"] == "high"]
        if blocking:
            print(
                "STRICT MODE: Exiting with code 1 due to high-severity warnings",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
