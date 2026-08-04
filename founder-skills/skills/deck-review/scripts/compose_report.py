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
import re
import sys
import uuid
from difflib import SequenceMatcher
from typing import Any, TypeGuard


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _edge_affix_only(a: str, b: str) -> bool:
    """True when a and b differ only by characters added or dropped at the
    word's edges. Such a pair is morphology (singular/plural, a shared root
    with a leading or trailing affix), not a misspelling — misspellings of a
    name alter its interior."""
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            return False
        at_start = i1 == 0 and j1 == 0
        at_end = i2 == len(a) and j2 == len(b)
        if not (at_start or at_end):
            return False
    return True


# Emails, URLs, and dotted domains — spans a brand may legitimately appear
# inside without it being name drift. Stripped before the NAME_DRIFT scan.
_URL_EMAIL_RE = re.compile(r"\S+@\S+|https?://\S+|www\.\S+|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import load_schema  # noqa: E402
from _schema_validator import validate as _schema_validate  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

_ARTIFACT_TO_SCHEMA = {
    "deck_inventory.json": "deck_inventory.schema.json",
    "stage_profile.json": "stage_profile.schema.json",
    "slide_reviews.json": "slide_reviews.schema.json",
    "checklist.json": "checklist.schema.json",
}

# Canonical warning severity map.
# High severity = agent must fix before presenting report.
# Medium severity = include in report's Warnings section.
_CORRUPT: dict[str, Any] = {"__corrupt__": True}
KNOWN_STAGES = {"pre_seed", "seed", "series_a"}

# Every stage the shared founder context admits (founder_context.VALID_STAGES),
# underscore dialect to match this file's tokens. Mirrored rather than
# imported — skill scripts are standalone and don't cross-import.
_STAGE_LADDER = ("pre_seed", "seed", "series_a", "series_b", "series_c", "series_d", "later")

# Stage tokens the cross-checks recognise as an actual stage assertion: every
# ladder stage, DERIVED rather than hand-picked — a hand-written subset omits
# whatever stage nobody thought of, and it fails silent: a token missing from
# this set is treated as "not a stage assertion" and neither STAGE_MISMATCH
# nor STAGE_OUT_OF_SCOPE ever fires for it, so a genuine late-stage claim goes
# through with no founder-visible signal at all. Plus "growth", so a deck's
# own "growth stage" language is recognized even though it isn't a
# founder-context stage. Anything else in claimed_stage (descriptive text, a
# "not stated" note, an omitted/null value) is not a stage assertion and is
# skipped by the stage cross-checks.
RECOGNIZED_STAGE_TOKENS = frozenset(_STAGE_LADDER) | {"growth"}


def _stage_slug(value: Any) -> str:
    """Normalize a stage value to its comparison token.

    str() coercion keeps a non-string value from raising before the schema
    check can report it; absence (None/"") normalizes to the empty string.
    """
    return str(value or "").lower().replace("-", "_").replace(" ", "_")


WARNING_SEVERITY: dict[str, str] = {
    # "low", not medium: by the time this fires, substitute() has already corrected the text, so the
    # report is clean and what remains is an authoring task. ic-sim / market-sizing / deck-review block
    # strict mode on medium, which would fail a run over an already-fixed issue. The fleet ratchet in
    # test_compose_invariants.py is the gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # High — structural integrity violations
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    "SCHEMA_VIOLATION": "high",
    "MISSING_METADATA": "high",
    "CHECKLIST_FAILURES_CRITICAL": "high",
    # Medium — quality concerns worth surfacing
    "STAGE_MISMATCH": "medium",
    "SLIDE_COUNT_EXTREME": "medium",
    "UNCITED_CRITIQUE": "medium",
    "AI_CRITERIA_MISSING": "high",
    "AI_CRITERIA_SKIPPED": "medium",
    "AI_CRITERIA_ON_NON_AI": "medium",
    # Low — minor notes
    "STAGE_OUT_OF_SCOPE": "low",
    "UNSUPPORTED_CHECKLIST_CRITIQUE": "high",
    "CHECKLIST_VALIDATION_FAILED": "high",
    "NAME_DRIFT": "medium",
    # v0.4.2 Mitigation 2 — informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
    # AI classification quality
    "UNSUBSTANTIATED_AI_CLAIM": "medium",
    # Content-accuracy: two inventory slides share a number, so the per-slide
    # heading's quoted headline is ambiguous (the report picks one). Not
    # artifact corruption — the artifact is schema-valid and deck_inventory.py
    # already emitted its own non-fatal producer-side note — and the blast
    # radius is confined to the heading text (strengths/weaknesses/
    # recommendations are keyed off the review, never mis-keyed). That puts it
    # with NAME_DRIFT / STAGE_MISMATCH (medium: a founder-visible
    # content-accuracy issue), not high (structural integrity) or low
    # (MARKER_COLLISION-style, provably harmless).
    "DUPLICATE_SLIDE_NUMBER": "medium",
}

ACCEPTIBLE_SEVERITIES = {"medium"}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "STALE_ARTIFACT": "Stale Artifact",
    "SCHEMA_VIOLATION": "Schema Violation",
    "MISSING_METADATA": "Missing Metadata",
    "CHECKLIST_FAILURES_CRITICAL": "Checklist Failures (Critical)",
    "STAGE_MISMATCH": "Stage Mismatch",
    "SLIDE_COUNT_EXTREME": "Slide Count",
    "UNCITED_CRITIQUE": "Uncited Critique",
    "AI_CRITERIA_MISSING": "AI Criteria Missing",
    "AI_CRITERIA_SKIPPED": "AI Criteria Skipped",
    "AI_CRITERIA_ON_NON_AI": "AI Criteria Applied to Non-AI Company",
    "STAGE_OUT_OF_SCOPE": "Stage Out of Scope",
    "UNSUPPORTED_CHECKLIST_CRITIQUE": "Unsupported Checklist Critique",
    "CHECKLIST_VALIDATION_FAILED": "Checklist Validation Failed",
    "NAME_DRIFT": "Company Name Drift",
    "MARKER_COLLISION": "Marker Collision",
    "UNSUBSTANTIATED_AI_CLAIM": "Unsubstantiated AI Claim",
    "DUPLICATE_SLIDE_NUMBER": "Duplicate Slide Number",
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


def _md_safe(text: Any) -> str:
    """Escape text for safe markdown table cell interpolation."""
    return str(text).replace("|", "\\|").replace("\n", " ")


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

    # 1b. SCHEMA_VIOLATION — required artifact violates JSON schema
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if not _usable(data):
            continue
        schema_file = _ARTIFACT_TO_SCHEMA.get(name)
        if not schema_file:
            continue
        try:
            schema = load_schema(os.path.join(_SCHEMA_DIR, schema_file))
        except (OSError, json.JSONDecodeError) as e:
            warnings.append(_warn("SCHEMA_VIOLATION", f"Could not load schema for {name}: {e}"))
            continue
        errs = _schema_validate(data, schema)
        if errs:
            warnings.append(_warn("SCHEMA_VIOLATION", f"{name}: {'; '.join(errs[:3])}"))

    # 1c. MISSING_METADATA — required artifact lacks metadata.run_id
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if not _usable(data):
            continue
        meta = _as_dict(data.get("metadata"))
        if not isinstance(meta.get("run_id"), str) or not meta.get("run_id"):
            warnings.append(_warn("MISSING_METADATA", f"{name} has no metadata.run_id"))

    # 2. STALE_ARTIFACT — run_id mismatch across artifacts
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
        claimed = _stage_slug(inventory.get("claimed_stage"))
        detected = _stage_slug(profile.get("detected_stage"))
        # Only flag when the deck makes a recognised stage assertion that differs.
        # A descriptive / absent claimed_stage is not a stage assertion.
        if claimed in RECOGNIZED_STAGE_TOKENS and detected and claimed != detected:
            warnings.append(
                _warn(
                    "STAGE_MISMATCH",
                    f"Deck claims '{claimed}' but analysis detected '{detected}'",
                )
            )

    # 5. STAGE_OUT_OF_SCOPE — check both detected and claimed stage
    out_of_scope_stages: list[str] = []
    if _usable(profile):
        detected = _stage_slug(profile.get("detected_stage"))
        if detected and detected not in KNOWN_STAGES:
            out_of_scope_stages.append(detected)
    if _usable(inventory):
        claimed = _stage_slug(inventory.get("claimed_stage"))
        # Only a recognised stage assertion can be out of scope — a descriptive
        # or absent claimed_stage is neither mismatched nor out of scope.
        if claimed in RECOGNIZED_STAGE_TOKENS and claimed not in KNOWN_STAGES and claimed not in out_of_scope_stages:
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
    # Read ai_company_status from deck_inventory.json (the authoritative source).
    # Falls back to profile's is_ai_company for backward compatibility when inventory is absent.
    _ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    _ai_status = None
    if _usable(inventory):
        _ai_status = inventory.get("ai_company_status")
    if _ai_status is None and _usable(profile):
        # Backward-compat: if inventory has no ai_company_status, use profile boolean.
        _profile_is_ai = profile.get("is_ai_company", False)
        _ai_status = "ai_core" if _profile_is_ai else "not_ai"

    if _usable(checklist) and _ai_status is not None:
        is_ai_for_check = _ai_status in ("ai_core", "ai_claimed_unverified")
        items = _as_list(checklist.get("items"))
        ai_items = [i for i in items if i.get("id") in _ai_ids]
        if is_ai_for_check:
            if len(ai_items) < 4:
                warnings.append(
                    _warn(
                        "AI_CRITERIA_MISSING",
                        f"AI company checklist missing {4 - len(ai_items)} of 4 AI criteria items",
                    )
                )
            if ai_items and all(i.get("status") == "not_applicable" for i in ai_items):
                warnings.append(
                    _warn(
                        "AI_CRITERIA_SKIPPED",
                        "Company detected as AI-first but all AI criteria marked not_applicable",
                        founder_message=(
                            "This deck was flagged as AI-first, but none of the AI-specific "
                            "criteria could be evaluated — so the AI-related scoring doesn't "
                            "reflect a real assessment. Treat it as unscored, not as a pass or "
                            "a fail."
                        ),
                    )
                )
        else:
            # 8b. AI_CRITERIA_ON_NON_AI — not_ai company penalized on AI criteria
            penalized = [i.get("id", "?") for i in ai_items if i.get("status") in ("fail", "warn")]
            if penalized:
                ids_str = ", ".join(penalized)
                warnings.append(
                    _warn(
                        "AI_CRITERIA_ON_NON_AI",
                        f"Non-AI company penalized on AI-specific criteria: {ids_str}",
                        founder_message=(
                            "This deck was scored against a few AI-specific criteria even "
                            "though the company isn't AI-first. Any deductions from those "
                            "criteria shouldn't count against the overall score and can be "
                            "disregarded."
                        ),
                    )
                )

    # 9. UNSUPPORTED_CHECKLIST_CRITIQUE — fail/warn items without evidence
    if _usable(checklist):
        unsupported_ids: list[str] = []
        for item in _as_list(checklist.get("items")):
            if item.get("status") in ("fail", "warn"):
                evidence = item.get("evidence", "")
                if not evidence or not str(evidence).strip():
                    unsupported_ids.append(item.get("id", "?"))
        if unsupported_ids:
            ids_str = ", ".join(unsupported_ids)
            warnings.append(
                _warn(
                    "UNSUPPORTED_CHECKLIST_CRITIQUE",
                    f"Checklist items lack evidence for fail/warn status: {ids_str}",
                )
            )

    # 10. CHECKLIST_VALIDATION_FAILED — checklist present but validation.status != "valid"
    if _usable(checklist):
        validation = _as_dict(checklist.get("validation"))
        if validation and validation.get("status") != "valid":
            val_status = validation.get("status", "unknown")
            warnings.append(
                _warn(
                    "CHECKLIST_VALIDATION_FAILED",
                    f"Checklist validation status is '{val_status}' — checklist data may be unreliable",
                )
            )

    # 11b. UNSUBSTANTIATED_AI_CLAIM — deck claims AI but shows no AI-core evidence
    if _usable(inventory):
        ai_status = inventory.get("ai_company_status", "")
        if ai_status == "ai_claimed_unverified":
            warnings.append(
                _warn(
                    "UNSUBSTANTIATED_AI_CLAIM",
                    (
                        "Deck positions as AI but shows no AI-core evidence (ai_claimed_unverified) "
                        "— substantiate the AI claim or reframe; investors will probe it."
                    ),
                )
            )

    # 11. NAME_DRIFT — variants of company_name appear in slide content
    if _usable(inventory):
        canonical = (inventory.get("company_name") or "").strip()
        if canonical and len(canonical) >= 3:
            canonical_lower = canonical.lower()
            seen_variants: set[str] = set()
            for slide in _as_list(inventory.get("slides")):
                for field in ("headline", "content_summary"):
                    text = str(slide.get(field, ""))
                    # Emails, URLs, and dotted domains are conventionally
                    # lowercase — a brand appearing inside them is not name
                    # drift, so strip those spans before tokenizing.
                    text = _URL_EMAIL_RE.sub(" ", text)
                    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]{2,}\b", text):
                        if token == canonical:
                            continue
                        # Lowercase is the conventional register for domains,
                        # handles, and ordinary prose words; genuine drifted
                        # variants of a brand are cased (ALL-CAPS or mixed).
                        if token.islower():
                            continue
                        tl = token.lower()
                        if tl == canonical_lower:
                            # Same letters, different case — flag
                            seen_variants.add(token)
                            continue
                        # Edit-distance check: same length ±1, ratio ≥ 0.80.
                        # Exempt pairs that differ only by an edge affix
                        # (singular/plural, shared root) — morphology, not drift.
                        if (
                            abs(len(token) - len(canonical)) <= 1
                            and _ratio(tl, canonical_lower) >= 0.80
                            and not _edge_affix_only(tl, canonical_lower)
                        ):
                            seen_variants.add(token)
            if seen_variants:
                variants_str = ", ".join(sorted(seen_variants))
                warnings.append(
                    _warn(
                        "NAME_DRIFT",
                        f"Company name '{canonical}' appears as variants in deck content: {variants_str}",
                    )
                )

    # 12. DUPLICATE_SLIDE_NUMBER — two inventory slides share a number. The
    # per-slide heading below (_section_slide_feedback) quotes whichever
    # headline wins the first-occurrence tie-break, so a founder can see a
    # heading whose quoted headline came from a different slide than the one
    # whose analysis follows it. deck_inventory.py already logs a producer-side
    # note for this; this is the compose-side, founder-facing surface of it.
    if _usable(inventory):
        seen_numbers: set[int] = set()
        dup_numbers: list[int] = []
        for slide in _as_list(inventory.get("slides")):
            if isinstance(slide, dict):
                n = slide.get("number")
                if isinstance(n, int):
                    if n in seen_numbers and n not in dup_numbers:
                        dup_numbers.append(n)
                    seen_numbers.add(n)
        if dup_numbers:
            nums_str = ", ".join(str(n) for n in sorted(dup_numbers))
            warnings.append(
                _warn(
                    "DUPLICATE_SLIDE_NUMBER",
                    f"Inventory has duplicate slide number(s): {nums_str} — the quoted "
                    f"headline for that slide reflects only the first occurrence.",
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
        lines.append(f"**Stage:** {stage} (confidence: {confidence})")

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

        # Scoring footnote: formula + score-if-all-fixed
        applicable = summary.get("total", 0) - na_c
        if applicable > 0:
            score_if_fixed = round((pass_c + fail_c + warn_c) / applicable * 100, 1)
            lines.append(
                f"\n*Score = pass ÷ applicable (warn and fail earn no credit). "
                f"If all fixable items were resolved: {score_if_fixed}%.*"
            )

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


def _section_slide_feedback(reviews: dict[str, Any] | None, inventory: dict[str, Any] | None = None) -> str:
    """Per-slide feedback with strengths, areas to improve, and recommendations."""
    if reviews is None or _is_stub(reviews):
        return "## Slide-by-Slide Feedback\n\n*No slide reviews available.*\n"

    # Build slide-number → headline lookup from inventory. Keep the FIRST
    # occurrence on a duplicate slide number (last-write-wins previously let a
    # later duplicate silently overwrite the heading's quoted headline) — this
    # matches visualize.py's `_chart_slide_map`, which also keeps first
    # occurrence, so the two surfaces agree on which headline a duplicated
    # slide number shows. See the DUPLICATE_SLIDE_NUMBER warning above for the
    # founder-visible signal that a tie-break happened at all.
    headline_by_num: dict[int, str] = {}
    if inventory is not None and not _is_stub(inventory):
        for slide in _as_list(inventory.get("slides")):
            if isinstance(slide, dict):
                n = slide.get("number")
                h = slide.get("headline", "")
                if isinstance(n, int) and h and n not in headline_by_num:
                    headline_by_num[n] = str(h)

    lines = ["## Slide-by-Slide Feedback\n"]
    lines.append(
        "*Each slide assessment is the agent's evaluation against best-practice frameworks. "
        "Strengths and weaknesses are the agent's analysis, not investor quotes.*\n"
    )

    for raw_review in _as_list(reviews.get("reviews")):
        review = _as_dict(raw_review)
        num = review.get("slide_number", "?")
        maps_to = review.get("maps_to", "unknown")
        headline = headline_by_num.get(num) if isinstance(num, int) else None
        if headline:
            lines.append(f'### Slide {num}: "{headline}" ({maps_to})\n')
        else:
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
            refs = _as_list(review.get("best_practice_refs"))
            if refs:
                lines.append(f"  *Principles: {', '.join(str(r) for r in refs)}*")

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
        for raw_m in missing:
            m = _as_dict(raw_m)
            imp = str(m.get("importance", "important"))
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
    for cat, raw_counts in by_cat.items():
        counts = _as_dict(raw_counts)
        lines.append(
            f"| {cat} | {counts.get('pass', 0)} | {counts.get('fail', 0)} "
            f"| {counts.get('warn', 0)} | {counts.get('not_applicable', 0)} |"
        )
    lines.append("")

    # Failed items detail
    failed = _as_list(summary.get("failed_items"))
    if failed:
        lines.append("### Areas That Need Attention\n")
        for raw_f in failed:
            f = _as_dict(raw_f)
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
        for raw_w in warned:
            w = _as_dict(raw_w)
            notes = w.get("notes", "")
            evidence = w.get("evidence", "")
            lines.append(f"- **{w.get('label', w.get('id', '?'))}** ({w.get('category', '?')})")
            if notes:
                lines.append(f"  - {notes}")
            if evidence:
                lines.append(f"  - *Basis: {evidence}*")
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
        for raw_f in _as_list(_as_dict(checklist.get("summary")).get("failed_items")):
            f = _as_dict(raw_f)
            label = f.get("label", f.get("id", "?"))
            notes = f.get("notes", "")
            fix = f"{label}: {notes}" if notes else label
            fixes.append(fix)

    # Draw from missing slides
    if reviews is not None and not _is_stub(reviews):
        for raw_m in _as_list(reviews.get("missing_slides")):
            m = _as_dict(raw_m)
            if m.get("importance") == "critical":
                fixes.append(f"Add missing {m.get('expected_type', 'slide')}: {m.get('recommendation', '')}")

    # Draw from warned items
    if checklist is not None and not _is_stub(checklist):
        for raw_w in _as_list(_as_dict(checklist.get("summary")).get("warned_items")):
            w = _as_dict(raw_w)
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

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i"}
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


def _section_full_checklist(checklist: dict[str, Any] | None) -> str:
    """Appendix: full checklist table."""
    if checklist is None or _is_stub(checklist):
        return ""

    items = _as_list(checklist.get("items"))
    if not items:
        return ""

    lines = ["## Appendix: Full Checklist\n"]
    lines.append("| # | Category | Criterion | Status | Evidence |")
    lines.append("|---|----------|-----------|--------|----------|")

    status_icons = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "not_applicable": "N/A"}

    for i, raw_item in enumerate(items, 1):
        item = _as_dict(raw_item)
        cat = item.get("category", "?")
        label = item.get("label", item.get("id", "?"))
        status = status_icons.get(item.get("status", "?"), "?")
        evidence = _md_safe(item.get("evidence", "") or "")
        lines.append(f"| {i} | {cat} | {label} | {status} | {evidence} |")

    return "\n".join(lines) + "\n"


def _emit_coaching_payload(
    inventory: dict[str, Any],
    stage_profile: dict[str, Any],
    checklist: dict[str, Any],
    validation_warnings: list[dict[str, str]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
) -> dict[str, Any]:
    """Build the v0.4.2 coaching_payload for deck-review (schema_version v0.4.2-deck-review).

    Read from existing artifacts; do not fabricate fields.
    """
    summary = _as_dict(checklist.get("summary"))
    return {
        "schema_version": "v0.4.2-deck-review",
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
        "high_severity_warnings": [w["code"] for w in validation_warnings if w.get("severity") == "high"],
        "stage": stage_profile.get("detected_stage") or inventory.get("claimed_stage"),
        "ai_company_status": inventory.get("ai_company_status"),
        "company_name": inventory.get("company_name"),
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

    # Assemble report sections — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inventory = _render_safe(artifacts.get("deck_inventory.json"))
    stage_profile = _render_safe(artifacts.get("stage_profile.json"))
    slide_reviews = _render_safe(artifacts.get("slide_reviews.json"))
    checklist_data = _render_safe(artifacts.get("checklist.json"))

    # Render every section EXCEPT Warnings first, so we can pre-scan the body
    # for a marker collision and append MARKER_COLLISION before status and the
    # Warnings section are computed. Otherwise status could read "clean" while
    # a MARKER_COLLISION warning sits in the warnings list (and is missing from
    # the rendered Warnings section).
    body_sections = [
        _section_title(inventory),
        _section_executive_summary(stage_profile, checklist_data, inventory),
        _section_stage_context(stage_profile),
        _section_slide_feedback(slide_reviews, inventory),
        _section_checklist(checklist_data),
        _section_priority_fixes(checklist_data, slide_reviews),
    ]
    appendix = _section_full_checklist(checklist_data)
    body_markdown = "\n".join(body_sections)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan: check the assembled body BEFORE appending the marker (otherwise
    # we always find our own emission). The appendix is rendered below the
    # marker but is part of the body content, so include it in the scan.
    if "<!-- COACHING_INSERTION_POINT_" in (body_markdown + appendix):
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

    # Compute status AFTER MARKER_COLLISION can be appended, then splice the
    # Warnings section (which now reflects the final warnings list) into place.
    status = "clean" if not warnings else "warnings"
    report_markdown = "\n".join([body_markdown, _section_warnings(warnings), appendix])

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Deck Review Agent"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
    )

    # --- founder-text policy (shared fleet module) ------------------------------------------------
    # MUST run on the FINAL assembled markdown, after the warnings section and the footer: that is the
    # exact string the founder reads, and producer warning messages are where the internal tokens
    # live. Hooking in before the warnings splice substitutes nothing and reports a clean body.
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
        # accepted_warnings re-marks medium warnings as 'acknowledged' — count
        # them so the summary line totals match the per-warning lines below.
        # There is no 'info' severity, so no info bucket.
        acknowledged = [w for w in warnings if w["severity"] == "acknowledged"]
        print(
            f"Warnings: {len(high)} high, {len(medium)} medium, {len(low)} low, {len(acknowledged)} acknowledged",
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
        inventory=_as_dict(inventory),
        stage_profile=_as_dict(stage_profile),
        checklist=_as_dict(checklist_data),
        validation_warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
    )

    result = {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
        },
        "coaching_payload": coaching_payload,
    }

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose deck review report from artifacts")
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
