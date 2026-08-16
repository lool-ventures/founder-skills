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
import _notes  # noqa: E402
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
    # HIGH, not medium, and the difference is load-bearing: `ACCEPTIBLE_SEVERITIES` is
    # exactly {"medium"}, so at medium this warning could be ACCEPTED AWAY -- the one signal
    # that a founder is reading findings nothing reviewed was itself dismissible.
    #
    # Measured skip rate for the review pass: 1 of 3 eligible live runs, and it skipped on
    # the deck with 9 contradictions. Skipping shows MORE findings, not fewer, including the
    # kind a founder would rightly reject. It carries a founder_message rather than the
    # agent-facing text, because the founder's stake is "these are a first pass", not the
    # name of a step.
    "NUMBERS_NOT_REVIEWED": "high",
    # Medium: the figures are not wrong, the evidence that they were re-found is weak, and
    # ~7.5% of a real corpus is this shape — too large a pre-existing population to block on.
    "THIN_QUOTES": "medium",
    "STAGE_MISMATCH": "medium",
    "SLIDE_COUNT_EXTREME": "medium",
    "UNCITED_CRITIQUE": "medium",
    # Medium, not high: the item is suppressed from the fixes list rather than rendered,
    # so nothing wrong reaches the founder -- but a checklist item that produced no
    # usable fix is a sub-agent contract miss worth surfacing.
    "NOTES_NOT_ACTIONABLE": "medium",
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
    # Medium, not high: every deliverable is valid and complete. What is unavailable is the
    # statement of how this run's stage gate was answered, which is a disclosure gap, not a
    # broken pipeline. See the parity check in compose() for why neither disclosing nor
    # staying silent is acceptable on a foreign run's gate record.
    "STALE_GATE_STATE": "medium",
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
    # "high", alongside AI_CRITERIA_MISSING: both mean work the founder paid for was not
    # done and nothing said so. A review missing slides is a materially incomplete
    # deliverable, not a presentation nit.
    "SLIDE_REVIEW_MISSING": "high",
    "SLIDE_REVIEW_DUPLICATE": "medium",
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
    "NOTES_NOT_ACTIONABLE": "Fix Text Not Actionable",
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
    "SLIDE_REVIEW_MISSING": "Slides Not Reviewed",
    "SLIDE_REVIEW_DUPLICATE": "Slide Reviewed More Than Once",
}


def _humanize_importance(value: str) -> str:
    """Founder-facing rendering of the importance enum, via the shared policy where available."""
    try:
        ft = _founder_text_policy()
        if ft is not None:
            return str(ft.humanize_token(value))
    except Exception:
        pass
    return value.replace("_", " ").capitalize()


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


REQUIRED_ARTIFACTS = [
    "deck_inventory.json",
    "stage_profile.json",
    "slide_reviews.json",
    "checklist.json",
    "reconciliation.json",
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

    # 7b. NOTES_NOT_ACTIONABLE — a fail/warn item's `notes` describes what was CHECKED
    # rather than what to change, so the fixes section suppressed it (see _notes.py).
    # Layer 1 (a missing `notes`) is fatal in checklist.py; this is the shape tripwire,
    # which stays advisory because it is a heuristic and can false-positive.
    if _usable(checklist):
        _summary = _as_dict(checklist.get("summary"))
        _unusable = [
            str(_as_dict(raw).get("id", "?"))
            for key in ("failed_items", "warned_items")
            for raw in _as_list(_summary.get(key))
            if _notes.usable_fix(_as_dict(raw).get("notes")) is None
        ]
        if _unusable:
            warnings.append(
                _warn(
                    "NOTES_NOT_ACTIONABLE",
                    f"{len(_unusable)} checklist item(s) describe what was checked instead of what to "
                    f"change, so they were left out of the fixes list: {', '.join(_unusable[:5])}",
                    founder_message=(
                        f"{len(_unusable)} checklist item(s) had no actionable fix text and were left "
                        "out of the fixes list. The full findings are still in the checklist below."
                    ),
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

    # 13. SLIDE_REVIEW_MISSING / SLIDE_REVIEW_DUPLICATE — the inventory and the reviews
    # disagree about which slides were actually reviewed.
    #
    # Nothing checked this before: compose loaded both artifacts and rendered whatever
    # reviews existed, so a deck whose sub-agent returned 12 reviews for 15 slides produced
    # a clean-looking report covering 12. `missing_slides` in the reviews artifact does NOT
    # cover this — that field is the model's own list of slides it thinks the DECK should
    # add, which is a content recommendation, not a coverage record.
    #
    # Duplicates are separate from DUPLICATE_SLIDE_NUMBER above: that one is two inventory
    # rows sharing a number; this one is the same slide reviewed twice, which inflates
    # apparent coverage and double-counts its findings.
    if _usable(inventory) and _usable(reviews):
        inventory_numbers: list[int] = [
            slide["number"]
            for slide in _as_list(inventory.get("slides"))
            if isinstance(slide, dict) and isinstance(slide.get("number"), int)
        ]
        reviewed_numbers: list[int] = [
            review["slide_number"]
            for review in _as_list(reviews.get("reviews"))
            if isinstance(review, dict) and isinstance(review.get("slide_number"), int)
        ]

        # Only meaningful when the inventory actually enumerated slides. A text-format deck
        # can legitimately carry total_slides with no per-slide rows.
        if inventory_numbers:
            unreviewed = sorted(set(inventory_numbers) - set(reviewed_numbers))
            if unreviewed:
                nums_str = ", ".join(str(n) for n in unreviewed)
                warnings.append(
                    _warn(
                        "SLIDE_REVIEW_MISSING",
                        f"{len(unreviewed)} of {len(set(inventory_numbers))} slides were not "
                        f"reviewed: {nums_str}. This review is incomplete — re-run the slide "
                        f"review for those slides before treating the score as final.",
                    )
                )

        repeated = sorted({n for n in reviewed_numbers if reviewed_numbers.count(n) > 1})
        if repeated:
            nums_str = ", ".join(str(n) for n in repeated)
            warnings.append(
                _warn(
                    "SLIDE_REVIEW_DUPLICATE",
                    f"Slide(s) {nums_str} were reviewed more than once — their findings are "
                    f"counted twice and apparent coverage is overstated.",
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
            # Craft language only. These used to promise investability ("investor-ready"),
            # which this same block now disclaims one line below — and half credit for a
            # warn widened that string's reach (25 pass / 10 warn moved Solid -> Strong).
            # A deck can meet every craft criterion and still be uninvestable.
            "strong": "Strong — meets nearly all 35 craft criteria; what is left is polish",
            "solid": "Solid — a well-built deck with a few craft gaps to close",
            "needs_work": "Needs Work — several craft gaps to close before sending",
            "major_revision": "Major Revision — worth reworking before it goes out; see the fixes below",
        }.get(status, status)

        # "Deck-craft score", not "Overall Score": this measures conformance to 35
        # deck-craft criteria and does NOT predict investability. Measured across four
        # decks, it does not even rank with an experienced reader's verdict — the
        # strongest company scored among the weakest decks.
        lines.append(f"**Deck-craft score:** {score}% — {status_label}")
        lines.append(f"**Breakdown:** {pass_c} pass, {fail_c} fail, {warn_c} warn, {na_c} N/A")
        lines.append(
            "\n*Score = (pass + half credit per warn) ÷ applicable. Measures conformance to "
            "35 deck-craft criteria, not investability.*"
        )

    lines.extend(_unreviewed_design_note(checklist))
    lines.extend(_scope_note(checklist))
    return "\n".join(lines) + "\n"


def _scope_note(checklist: dict[str, Any] | None = None) -> list[str]:
    """State what this review does NOT cover, so its silence is not read as a clean bill.

    R8 offered two options: a sector-conditional criteria pack, or an explicit out-of-scope
    statement. The pack is not buildable as specified, and the reason was established while
    debugging an unrelated warning: `sector_type` is a REVENUE MODEL classifier (saas,
    marketplace, usage-based), not an industry taxonomy. There is nothing in the system to
    key sector-conditional criteria off -- a fintech and a healthtech with identical
    subscription economics are the same value. Building the pack would mean first building
    an industry taxonomy and sourcing per-sector diligence content to this repo's citation
    standard, which is a research project, not a gate.

    So: the honest option. A founder who reads 35 criteria and sees no regulatory finding
    should not conclude there is no regulatory problem.
    """
    # "design" is dropped when the design gate fired. Listing it there is an affirmative false
    # statement — on an image-only deck this sentence claimed design was assessed while four
    # design criteria had been excluded for want of a slide anyone could see.
    built_from = (
        "story, evidence, structure, design" if design_gate_reason(checklist) is None else "story, evidence, structure"
    )
    return [
        f"\n> **What this review does not cover.** These 35 criteria assess how the deck is "
        f"built — {built_from}. They do not assess your market, your "
        "technology, or the regulatory, clinical, licensing or compliance questions specific "
        "to your sector. An investor will ask about those separately, and a clean score here "
        "is not evidence they are handled."
    ]


# The evidence string `checklist.py` stamps when it gates a criterion on the input format.
# The prefix `checklist.py` stamps when it gates a design criterion. It stamps ONE of two
# reasons -- `input_format=` or `input_quality=` -- and this used to name only the first, which
# meant an image-only or partially-read PDF lost four criteria in total silence. The two reason
# sets are DISJOINT (`{text, markdown}` vs `{image_only, partial}`), so a PDF gates on quality
# alone and never matched. Match the shared stem and read the reason off the end.
_DESIGN_GATE_EVIDENCE = "Auto-gated: not_applicable — input_"

# One sentence per reason. A single sentence cannot serve all three: widening the old prefix
# would have told a founder who sent an image-only PDF that "this deck reached the review as
# text ... sending the deck as a PDF gets them reviewed" -- both clauses false, and the second
# is advice they already followed.
_DESIGN_GATE_REASONS: dict[str, str] = {
    "format": (
        "This deck reached the review as text — its slides were never rendered, so nothing here "
        "judges how the deck *looks*: layout, typography, whitespace, or how it reads on a phone. "
        "Sending the deck as a PDF gets them reviewed."
    ),
    "quality:image_only": (
        "This deck's slides are images with no readable text layer, so nothing here judges how the "
        "deck *looks*: layout, typography, whitespace, or how it reads on a phone. Exporting the "
        "deck to PDF from the original file — rather than scanning or screenshotting it — gets "
        "them reviewed."
    ),
    "quality:partial": (
        "Not every page of this deck could be read, so nothing here judges how the deck *looks*: "
        "layout, typography, whitespace, or how it reads on a phone. Re-sending the deck as a "
        "complete PDF gets them reviewed."
    ),
}


def design_gate_reason(checklist: dict[str, Any] | None) -> str | None:
    """Which reason the design gate fired on, or None if it did not fire.

    Keyed on what the gate ACTUALLY DID -- the evidence string in the artifact -- rather than
    re-deriving from the inventory, so the disclosure cannot drift out of agreement with the
    gate. Shared with `visualize.py`'s category charts, which must not report a gated category
    as a percentage over its surviving criterion.
    """
    if checklist is None or _is_stub(checklist):
        return None
    for item in _as_list(checklist.get("items")):
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidence", ""))
        if not evidence.startswith(_DESIGN_GATE_EVIDENCE):
            continue
        tail = evidence[len(_DESIGN_GATE_EVIDENCE) :]
        if tail.startswith("format="):
            return "format"
        if tail.startswith("quality="):
            return f"quality:{tail[len('quality=') :].strip()}"
    return None


def _design_gate_payload(checklist: dict[str, Any] | None) -> dict[str, Any]:
    """Whether the design criteria were assessed at all, for the coaching sub-agent.

    `summary.not_applicable` is a bare count and says nothing about WHY, so a coach handed a
    "strong" overall status writes an unqualified headline over a deck whose design nobody
    could see. Reasons are the founder-facing ones, not the gate's enum.
    """
    reason = design_gate_reason(checklist)
    gated = [
        item
        for item in _as_list(_as_dict(checklist).get("items"))
        if isinstance(item, dict) and str(item.get("evidence", "")).startswith(_DESIGN_GATE_EVIDENCE)
    ]
    return {
        "design_reviewed": reason is None,
        "gated_count": len(gated),
        "reason": {
            None: "",
            "format": "the deck reached the review as text rather than as a rendered file",
            "quality:image_only": "the slides are images with no readable text layer",
            "quality:partial": "not every page of the deck could be read",
        }.get(reason, "the slides could not be rendered"),
    }


def _unreviewed_design_note(checklist: dict[str, Any] | None) -> list[str]:
    """Tell the founder, in the summary, when the deck's design was never looked at.

    A live run over a PowerPoint upload gated the Design & Readability criteria correctly and
    then never said so anywhere a founder would read: the report's only disclosure was an
    "Auto-gated" annotation inside a 35-row table, and the closing message reported "10
    not-applicable" without explaining that some of those mean nobody saw the slides. Leaving
    this to the model's prose did not work — hence a structural note emitted from the artifact.

    The distinction matters to a founder in a specific way: an unscored design criterion
    is NOT a passed one, and it is not a criticism either. It is a gap in the review.
    """
    reason = design_gate_reason(checklist)
    if reason is None:
        return []
    gated = [
        item
        for item in _as_list(_as_dict(checklist).get("items"))
        if isinstance(item, dict) and str(item.get("evidence", "")).startswith(_DESIGN_GATE_EVIDENCE)
    ]
    body = _DESIGN_GATE_REASONS.get(reason) or _DESIGN_GATE_REASONS["format"]
    return [
        f"\n> **{len(gated)} design criteria could not be reviewed.** {body} Those criteria are "
        "excluded from the score rather than counted against you."
    ]


AUTO_SATISFY_DISCLOSURE = (
    "*The stage above was not put to you as a question: you named this stage earlier and the deck "
    "agreed, so it was taken as confirmed. If that is wrong, say so — everything below is graded "
    "against it.*"
)


def _section_stage_context(profile: dict[str, Any] | None, gate_auto_satisfied: bool = False) -> str:
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

    if gate_auto_satisfied:
        # The confirmation gate can be answered without the founder being asked — legitimately,
        # when Step 1 already captured a matching stage, since re-asking a question they answered
        # two minutes ago reads as not listening. But the report then presents a *confirmed* stage,
        # and every criterion below is graded against it. A founder who never saw the question is
        # entitled to know that this one was decided on their behalf, and where.
        #
        # Only the exception is disclosed. Telling a founder who answered the gate that they
        # answered it is noise, and noise is what makes a disclosure stop being read.
        lines.append("\n" + AUTO_SATISFY_DISCLOSURE)

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
            # NOT imp.upper(): that MANUFACTURES an ALLCAPS internal token into founder prose
            # ("[NICE_TO_HAVE]"), in a form the founder-text scan is blind to and substitute() cannot
            # reach. Measured in a delivered report. humanize_token gives "Nice to have".
            lines.append(f"- **[{_humanize_importance(imp)}]** {expected}: {rec}")
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
            # Same predicate as the fixes section. Suppression has to hold at EVERY site
            # that renders `notes`, or it is not suppression — it just moves the bad text
            # to a different heading. Evidence still prints, so the item keeps its
            # diagnosis; only the non-actionable "fix" is dropped.
            notes = _notes.usable_fix(f.get("notes")) or ""
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
            notes = _notes.usable_fix(w.get("notes")) or ""
            evidence = w.get("evidence", "")
            lines.append(f"- **{w.get('label', w.get('id', '?'))}** ({w.get('category', '?')})")
            if notes:
                lines.append(f"  - {notes}")
            if evidence:
                lines.append(f"  - *Basis: {evidence}*")
        lines.append("")

    return "\n".join(lines) + "\n"


def _sanitize_items_for_coaching(items: Any) -> list[dict[str, Any]]:
    """Drop unusable `notes` before the coaching sub-agent sees them.

    Copies rather than mutating: `summary` is also rendered by the report sections, and
    an in-place edit here would make the payload and the report silently co-dependent.
    """
    out: list[dict[str, Any]] = []
    for raw in _as_list(items):
        item = dict(_as_dict(raw))
        if "notes" in item and _notes.usable_fix(item.get("notes")) is None:
            item.pop("notes")
        out.append(item)
    return out


def _coverage_line(reconciliation: dict[str, Any]) -> str:
    """How much of the deck this actually looked at, in the founder's terms.

    Without it the section's opening sentence is true and its silence is misleading: it
    describes what was done to the figures SHOWN and says nothing about how many were read,
    how many survived corroboration, or how many comparisons were run. A founder reading a
    short list reasonably infers there was little to find.

    Deliberately counts rather than characterises. "12 could not be confirmed" is a fact
    the founder can act on -- they know which of their slides are hard to read. A
    percentage or a grade would be a judgement this has no basis for.

    THE CLOSING CLAUSE SAYS A CAREFUL READER WOULD FIND MORE, and that is measured, not
    modesty. Across seven real decks this pipeline reproduced 4 of 16 findings an expert
    had graded real on the same decks. So a short list is weak evidence of clean numbers,
    and the section has to say so or its silence does the lying.

    What it deliberately does NOT do is quantify that. The 4-of-16 is measured against a
    REPRODUCIBILITY target -- verdicts on what one frozen bench draw surfaced -- not
    against everything an expert would find, so "roughly a quarter" would state a
    precision the evidence does not support, and it would go stale the moment recall
    moves. Qualitative here is the honest register; the counts above carry what is
    actually known.
    """
    if reconciliation.get("status") != "checked":
        return ""
    total = reconciliation.get("figures_total")
    verified = reconciliation.get("figures_verified")
    computed = reconciliation.get("relations_proposed")
    if not isinstance(total, int) or not isinstance(verified, int):
        return ""
    bits = [f"I read **{total}** figures off your deck"]
    if verified < total:
        bits.append(
            f"**{verified}** of them had their wording checked back against your deck — the other "
            f"**{total - verified}** I could not confirm, so nothing below rests on them"
        )
    else:
        bits.append("all of them had their wording checked back against your deck")
    if isinstance(computed, int) and computed:
        bits.append(f"and I ran **{computed}** comparisons across them")
    return ", ".join(bits) + (
        ". That is what was checked. A short list here means these particular comparisons "
        "held — not that every number in the deck has been verified against every other, and "
        "not that a careful reader would find nothing more. Treat this as a first pass over "
        "your arithmetic, not a clean bill of health.\n"
    )


def _section_numbers(
    reconciliation: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> str:
    """What the deck's own numbers say about each other.

    Renders NOTHING unless there is something to act on. A deck whose figures all agree
    produces no section at all — a list of confirmations is volume, and volume is the
    enemy of the few findings that count.

    This renderer never decides what is shown. `select()` in reconcile.py is the single
    place that decides, and it has already dropped confirmations, restatements, relations
    resting on a figure whose quote the second read could not confirm, and every
    `convention_differs` pair. Reaching past `relations` here — into the suppressed
    counts, or back into the engine — would put a second decider in the pipeline and
    silently widen what a founder sees.
    """
    if not reconciliation:
        return ""
    relations = _as_list(reconciliation.get("relations"))

    # THE COVERAGE LINE RENDERS EVEN WITH NOTHING TO REPORT, and that is the point.
    #
    # This section used to return "" on an empty relation set, so a founder saw no numbers
    # section at all. Measured on a real deck: 113 figures read, 101 corroborated, 20
    # relations computed, 12 figures whose quotes weren't found in the second read -- and
    # the report said nothing whatsoever. The deck the tool worked hardest on is the one it appeared
    # to skip.
    #
    # Silence is the worst available answer here. It reads as "your numbers are fine" when
    # what happened was "these particular comparisons held, and this many figures never got
    # checked". Saying how much was looked at is an ADDITION to the claim, not a retreat
    # from it: the founder can tell a clean bill of health from a thin one.
    counts = _coverage_line(reconciliation)
    if not relations:
        return "## What Your Numbers Say About Each Other\n\n" + counts if counts else ""

    # Split on VERDICT, not `kind`. `kind` is what the model PROPOSED the relation was;
    # `verdict` is what the engine computed it to be, and they routinely differ — the
    # flagship finding is proposed as a `derived_ratio` and comes back a `contradiction`
    # because it disagreed with a figure the deck itself states. Keying the founder-facing
    # split on `kind` filed every contradiction under "readings, not errors", telling a
    # founder their deck disagreeing with itself was a matter of interpretation.
    parsed = [_as_dict(x) for x in relations]
    contradictions = [r for r in parsed if r.get("verdict") == "contradiction"]
    derived = [r for r in parsed if r.get("verdict") == "derived"]
    if not contradictions and not derived:
        return ""

    lines = ["## What Your Numbers Say About Each Other\n"]
    lines.append(
        "Every figure below was read off your deck, had its wording checked back against "
        "the deck's own text, and was then related by arithmetic rather than by eye. "
        "Figures whose wording could not be found again were dropped rather than guessed at.\n"
    )
    if counts:
        lines.append(counts)

    if contradictions:
        lines.append("### Figures that disagree\n")
        for rel in contradictions:
            rendered = str(rel.get("rendered", "")).strip()
            if rendered:
                lines.append(f"- {rendered}")
        lines.append("")

    if derived:
        lines.append("### What the numbers imply\n")
        lines.append(
            "These are readings, not errors — the arithmetic is exact, the interpretation "
            "is a judgement call, and an investor may well make it.\n"
        )
        for rel in derived:
            rendered = str(rel.get("rendered", "")).strip()
            if rendered:
                lines.append(f"- {rendered}")
        lines.append("")

    # The checklist scores internal numeric consistency on the reviewer's reading; this
    # section computes it. When they disagree the report says so rather than quietly
    # preferring one — there is no adjudication rule yet, and inventing one here would
    # bury the more interesting fact that two methods reached different answers.
    if contradictions and checklist is not None and not _is_stub(checklist):
        for raw_item in _as_list(checklist.get("items")):
            item = _as_dict(raw_item)
            if item.get("id") == "numbers_consistent" and item.get("status") == "pass":
                lines.append(
                    "> Note: the criteria review marked your figures internally consistent, "
                    "while the arithmetic above found a disagreement. The two looked at the "
                    "deck differently and reached different answers; both are shown.\n"
                )
                break

    return "\n".join(lines)


def _section_priority_fixes(
    checklist: dict[str, Any] | None,
    reviews: dict[str, Any] | None,
) -> str:
    """Up to five founder-facing fixes, drawn from `notes` (the contracted fix field).

    Two rules that are easy to "simplify" back into the bug this replaced:

    1. NEVER fall back to the criterion label or to `evidence`. A label is a criterion
       name and `evidence` is a diagnosis; neither is a change to make. A candidate with
       no usable `notes` is SKIPPED and the next one backfills its slot, so the list can
       hold fewer than five. That is why the heading says "Up to".
    2. The section is NOT ranked. A critical missing slide is placed first because it
       genuinely outranks a failed criterion, and the preamble discloses exactly that;
       the remaining order is `failed_items` order, i.e. criteria-file order, which is
       arbitrary. Do not present it as a ranking — `checklist.py` deliberately refuses to
       weight criteria, so no severity signal exists to sort by.
    """
    lines = ["## Up to 5 Fixes to Make\n"]
    lines.append(
        "Drawn from the criteria this deck missed and from slides it is missing entirely. "
        "A missing critical slide is listed first; the rest are in no particular order — "
        "for where to start, see the coaching commentary.\n"
    )

    fixes: list[str] = []

    # A critical missing slide outranks a failed criterion, so it leads. `missing_slides`
    # carries no intrinsic order (the schema imposes none), so "first" among several is
    # arbitrary and deliberately so.
    if reviews is not None and not _is_stub(reviews):
        for raw_m in _as_list(reviews.get("missing_slides")):
            m = _as_dict(raw_m)
            if m.get("importance") == "critical":
                rec = str(m.get("recommendation", "")).strip()
                # Raw, like the "Slides to Add" section: substitute() de-tokenizes the whole
                # body before the founder-text scan, turning "why_now" into "why now".
                expected = str(m.get("expected_type", "slide"))
                if rec:
                    fixes.append(f"Add a {expected} slide: {rec}")
                    break

    # Failures, then warnings. Skip any candidate without a usable fix.
    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        for key in ("failed_items", "warned_items"):
            for raw in _as_list(summary.get(key)):
                item = _as_dict(raw)
                fix = _notes.usable_fix(item.get("notes"))
                if fix is None:
                    continue
                label = item.get("label", item.get("id", "?"))
                fixes.append(f"{label}: {fix}")

    if not fixes:
        # Reachable with failures present, once every candidate is suppressed — so it must
        # not claim the deck is clean. The accompanying NOTES_NOT_ACTIONABLE warning says
        # the same thing in the Warnings section.
        lines.append("No specific fixes could be listed here — see the checklist below.\n")
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
        # Sanitised, NOT passed by reference. The coaching sub-agent reads these and echoes
        # them into commentary inserted back into report.md — a fourth path to the founder.
        # Handing it a note the three renderers just suppressed would route around all of them.
        "failed_items": _sanitize_items_for_coaching(summary.get("failed_items", [])),
        "warned_items": _sanitize_items_for_coaching(summary.get("warned_items", [])),
        # {code, label, message}, matching competitive-positioning — NOT a bare code list. The
        # coaching sub-agent reads this payload and echoes it into commentary the founder reads;
        # handing it only `UNVALIDATED_CLAIMS` is how raw warning codes reached delivered reports.
        # The label gives it something founder-facing to write instead.
        "high_severity_warnings": [
            {
                "code": w["code"],
                "label": _humanize_warning(w["code"]),
                "message": w.get("message", ""),
            }
            for w in validation_warnings
            if w.get("severity") == "high"
        ],
        "stage": stage_profile.get("detected_stage") or inventory.get("claimed_stage"),
        "ai_company_status": inventory.get("ai_company_status"),
        # TOP-LEVEL, not folded into `summary`: the contract test asserts top-level names and
        # `summary` is already required, so a nested field would leave the pin green forever.
        # Without this the coach saw `not_applicable: 4` with no reason and wrote "strong" over
        # a category nobody could look at.
        "design_gate": _design_gate_payload(checklist),
        "company_name": inventory.get("company_name"),
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
    }


def read_gate_state(path: str | None) -> dict[str, Any] | None:
    """Load the gate artifact for the disclosure, or fail loudly.

    THREE CONDITIONS, and collapsing any two of them is what makes a disclosure droppable:

      no --gate-state       the caller is not a gated pipeline (the fixture-driven compose
                            invariants, a direct call). Nothing to say.
      path supplied, missing
                            FATAL. The stage gate sits unconditionally between Step 3 and
                            Step 3.5 — no path through the skill skips it — so a caller
                            that names a gate file and has none did not run the gate step.
                            An earlier version of this returned None here, on the argument
                            that "SKILL.md always passes the flag, so absent means the run
                            never gated". That is backwards: it is precisely BECAUSE the
                            flag is always passed that absence means a skipped step, and
                            composing a clean report over one is the work-that-never-
                            happened class this disclosure exists to surface.
      path present, unreadable
                            FATAL. The record of how the gate was answered has been
                            destroyed, and a report that quietly asserts nothing about it
                            is the same failure in a different costume.

    Raises ValueError for the latter two; the caller turns it into a non-zero exit.
    """
    if not path:
        return None
    if not os.path.isfile(path):
        raise ValueError(
            f"gate_state was named as {path} but no file is there — the stage gate is not optional, "
            "so this run did not reach it"
        )
    try:
        with open(path, encoding="utf-8") as f:
            gate = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"gate_state at {path} exists but cannot be read: {e}") from e
    if not isinstance(gate, dict):
        raise ValueError(f"gate_state at {path} is not a JSON object")
    return gate


def compose(
    dir_path: str,
    report_path: str | None = None,
    gate_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    artifacts_found = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in all_names if artifacts[n] is None]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # RUN-ID PARITY ON THE GATE RECORD. A gate_state.json left by a prior run says nothing
    # about this one, and reading its source either way asserts something unfounded: disclose
    # and we claim this run self-answered when it may not have; stay silent and we withhold a
    # disclosure this run may owe. So neither — say that the record does not belong to this run.
    #
    # Medium, not high. Every deliverable is valid and complete; what is missing is our ability
    # to state how one question was answered. `setup_run.py --clean` removes a prior run's gate,
    # so reaching this means something upstream did not run or could not delete.
    gate_auto_satisfied = False
    if gate_state is not None:
        artifact_run_ids = [
            rid
            for name in REQUIRED_ARTIFACTS
            if _usable(artifacts.get(name))
            and isinstance(rid := _as_dict(_as_dict(artifacts[name]).get("metadata")).get("run_id"), str)
            and rid
        ]
        gate_run_id = _as_dict(gate_state.get("metadata")).get("run_id")
        if artifact_run_ids and gate_run_id != artifact_run_ids[0]:
            warnings.append(
                _warn(
                    "STALE_GATE_STATE",
                    f"the gate record is from run '{gate_run_id}' but this report is run "
                    f"'{artifact_run_ids[0]}' — how this run's stage gate was answered is unrecorded",
                )
            )
        else:
            gate_auto_satisfied = gate_state.get("answer_source") == "auto_satisfied"

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
    reconciliation = _render_safe(artifacts.get("reconciliation.json"))

    # Skipping the review pass shows MORE findings, including ones a founder would reject —
    # which is the expensive direction, not the safe one. Nothing else notices, because a
    # complete-looking report is exactly what a skipped judgement pass produces.
    if reconciliation is not None:
        interp = _as_dict(reconciliation.get("interpretation"))
        if interp.get("status") == "not_run" and _as_list(reconciliation.get("relations")):
            warnings.append(
                _warn(
                    "NUMBERS_NOT_REVIEWED",
                    (
                        "reconciliation.interpretation.status is 'not_run' with contradictions "
                        "surfaced: the review of surviving disagreements did not run"
                    ),
                    founder_message=(
                        "The number checks below are a first pass — nobody reviewed them for "
                        "cases where the comparison itself does not hold, so read them as "
                        "questions to check rather than as settled problems."
                    ),
                )
            )

        # A quote carrying no word identifies nothing — the gate matches TEXT, so "$80B" is
        # re-found on any slide that prints $80B. `ledger.py` warns on each one, and that
        # warning went nowhere a human looks: the receipt it prints is {ok, path, bytes},
        # `reconcile.py` never reads the ledger's validation block, and `ledger.json` is
        # not in REQUIRED_ARTIFACTS. This is the surfacing step.
        #
        # Medium, and deliberately not high: ~7.5% of a real corpus is this shape, and the
        # figures are not wrong — what is weak is the evidence that they were re-found. A
        # high warning here would block runs over a known, pre-existing population.
        quality = _as_dict(reconciliation.get("quote_quality"))
        thin = quality.get("thin")
        total = quality.get("total")
        if isinstance(thin, int) and thin > 0:
            warnings.append(
                _warn(
                    "THIN_QUOTES",
                    (
                        f"{thin} of {total} ledger quotes carry no word, so the second read "
                        "confirmed only that the deck prints those figures somewhere — not that "
                        "it prints them where the ledger says"
                    ),
                    founder_message=(
                        f"{thin} of the {total} figures we checked were quoted as bare numbers, so "
                        "the double-check on those was weaker than on the rest: it confirms the "
                        "number appears in your deck, not that it appears where we say it does."
                    ),
                )
            )

    # Render every section EXCEPT Warnings first, so we can pre-scan the body
    # for a marker collision and append MARKER_COLLISION before status and the
    # Warnings section are computed. Otherwise status could read "clean" while
    # a MARKER_COLLISION warning sits in the warnings list (and is missing from
    # the rendered Warnings section).
    # R3: the coaching commentary is the most useful thing in this report -- it is the part
    # written by something that read the deck rather than scored it -- and it used to land
    # BELOW the warnings section and a 35-row appendix, where a founder reaches it last if at
    # all. The marker now sits directly under the executive summary, so the order is:
    # what we think -> why -> the evidence.
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"
    body_sections = [
        _section_title(inventory),
        _section_executive_summary(stage_profile, checklist_data, inventory),
        marker,
        _section_stage_context(stage_profile, gate_auto_satisfied),
        _section_slide_feedback(slide_reviews, inventory),
        _section_numbers(reconciliation, checklist_data),
        _section_checklist(checklist_data),
        _section_priority_fixes(checklist_data, slide_reviews),
    ]
    appendix = _section_full_checklist(checklist_data)
    body_markdown = "\n".join(body_sections)

    # Pre-scan for a marker substring the BODY brought with it. The marker is now spliced
    # into body_sections above, so scan with our own emission removed rather than scanning
    # a string that necessarily contains it.
    if "<!-- COACHING_INSERTION_POINT_" in (body_markdown.replace(marker, "") + appendix):
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
        "\n\n---\n"
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
        # No data-derived keep-set here. `identifier_values` is cap-table-only by design: this skill
        # uses `id` for a metric's NAME (`unit_economics.metrics[].id == "gross_margin"`), which is our
        # vocabulary and must be humanized, not a handle the founder cross-references. Keeping it left
        # "ARPU $500 x gross_margin 0.75" in a delivered report AND suppressed the warning, since the
        # scan honours the same keep-set.
        report_markdown = _ft.substitute(report_markdown)
        # Our own warning codes are kept: compose renders them in small print beside a humanized
        # label (the md_term convention), which is deliberate. A code leaking anywhere else is
        # caught by the skill's own gate, not by widening this scan into a false positive.
        _found = _ft.scan(report_markdown, extra_keep=frozenset(WARNING_SEVERITY))
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
    p.add_argument(
        "--gate-state",
        help="Path to gate_state.json. An absent file is fine (the run never gated); an unreadable "
        "one is fatal, because the record of how the gate was answered is what the report discloses.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    report_path = os.path.abspath(args.write_md) if args.write_md else None
    try:
        gate_state = read_gate_state(args.gate_state)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    result = compose(args.dir, report_path=report_path, gate_state=gate_state)

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
