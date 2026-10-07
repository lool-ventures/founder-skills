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
from collections.abc import Sequence
from datetime import date
from typing import Any, TypeGuard

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import _cp_gates  # noqa: E402
import _cp_redteam_copy  # noqa: E402
import _cp_view as _view  # noqa: E402

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
    # A direct competitor research found was left out at the cap while a competitor judged
    # not_a_competitor kept a slot. Medium: a disclosure the founder can act on (swap them).
    "CAP_DISPLACED_DIRECT": "medium",
    # Low
    "FOUNDER_OVERRIDE_COUNT": "low",
    # v0.4.2 Mitigation 2 — informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
    # Info
    "SEQUENTIAL_FALLBACK": "info",
    "CHECKLIST_ALL_PASS": "info",
    # A step whose output reached its producer without passing the hand-off gate (see
    # `_handoff_bypassed`). Medium: the results are valid and must not block. In
    # _UNACCEPTABLE_MEDIUM: a disclosure about the run that model-written accepted_warnings cannot clear.
    "HANDOFF_BYPASSED": "medium",
    # The outside review (`_cp_redteam_copy`, rules in the shared `_redteam_core`). Step 7's second pass
    # runs --strict, so a disclosure whose only remedy is "deliver as it is" cannot be high: it would
    # stop a run nothing can fix, or invite editing the review to clear it. Those three are medium and
    # in _UNACCEPTABLE_MEDIUM, the HANDOFF_BYPASSED posture. REVIEW_COPY_MISSING is fixed by re-running
    # the producer, so it stays high.
    "REDTEAM_ALTERED": "medium",
    "RED_TEAM_SKIP_CONTRADICTED": "medium",
    "ANALYSIS_CHANGED_AFTER_REVIEW": "medium",
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": "medium",
    "REVIEW_COPY_MISSING": "high",
    "EARLIER_REVIEW_THIS_ANALYSIS": "medium",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}
_UNACCEPTABLE_MEDIUM = {
    "HANDOFF_BYPASSED",
    "REDTEAM_ALTERED",
    "RED_TEAM_SKIP_CONTRADICTED",
    "ANALYSIS_CHANGED_AFTER_REVIEW",
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS",
}

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
    "CAP_DISPLACED_DIRECT": "Direct Competitor Left Out",
    "FOUNDER_OVERRIDE_COUNT": "Founder Override Count",
    "MARKER_COLLISION": "Marker Collision",
    "SEQUENTIAL_FALLBACK": "Sequential Fallback",
    "CHECKLIST_ALL_PASS": "Checklist All Pass",
    "HANDOFF_BYPASSED": "Some Steps Were Not Checked",
    "REDTEAM_ALTERED": "The Outside Review Was Changed After It Was Written",
    "RED_TEAM_SKIP_CONTRADICTED": "A Review Ran That Was Recorded As Skipped",
    "ANALYSIS_CHANGED_AFTER_REVIEW": "The Analysis Changed After The Outside Review",
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": "The Analysis Changed Between Reviews",
    "REVIEW_COPY_MISSING": "The Outside Review Cannot Be Shown Unchanged",
    "EARLIER_REVIEW_THIS_ANALYSIS": "An Earlier Run Also Reviewed This Analysis",
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
    # Loaded so its UNVALIDATED_ARTIFACT provenance row below is not a silent no-op:
    # the provenance loop does `artifacts.get(name)` and skips absent artifacts, so an
    # EXPECTED_PRODUCERS entry for a file nothing loads asserts nothing. Optional rather
    # than required because it is superseded by `landscape.json` once LANDSCAPE_RESEARCH
    # returns -- a run that got that far legitimately no longer needs the draft.
    "landscape_draft.json",
    # The adversarial competitor-set verdicts. Optional because a run may legitimately skip the
    # verification dispatch, but when present it MUST reach the deliverable: a competitor the
    # verification judged `not_a_competitor` was previously scored, ranked and tabled
    # indistinguishably from a genuine one, so the challenge survived only in chat.
    "competitor_verification.json",
    # What public records show about the startup itself (STARTUP_RESEARCH). Optional: a run that
    # predates the step has none, and the section then says nothing rather than implying a search.
    "startup_research.json",
    # The outside review (RED_TEAM), or the record of why none ran. Optional here; which of the two a
    # run must carry is decided where the review is resolved (`_cp_redteam_copy`).
    "redteam.json",
    "red_team_skip.json",
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


def _handoff_audit() -> Any:
    """The fleet's shared gate-record check from `founder-skills/scripts/` (same loading as
    `_founder_text_policy`). None if unavailable: a missing module must never block a report."""
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _handoff_audit  # type: ignore[import-not-found]

        return _handoff_audit
    except ImportError:
        return None


_ENRICHMENT_HANDOFF = "landscape_research_enrichment_output.json"


_REVIEW_FOUNDER_MESSAGES = {
    "REDTEAM_ALTERED": "The outside review was changed after it was written. This report shows it as it was written.",
    "RED_TEAM_SKIP_CONTRADICTED": (
        "The analysis recorded that no outside review ran, but one did; this report shows it."
    ),
    "ANALYSIS_CHANGED_AFTER_REVIEW": (
        "The analysis changed after the outside review was written, so the review in this report was "
        "taken against an earlier version of it."
    ),
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": (
        "The analysis changed between two outside reviews. The one shown is of the analysis as delivered; "
        "the earlier one, of the version before the change, is listed with it."
    ),
    "REVIEW_COPY_MISSING": (
        "The outside review carries no record of how it was written, so nothing can show it is unchanged."
    ),
    "EARLIER_REVIEW_THIS_ANALYSIS": (
        "An earlier run today also had this analysis reviewed; this report shows only this run's review."
    ),
}


def _rt_refuse(run_id: str | None, all_run_ids: set[str], reviews: Sequence[Any], skip_record: Any) -> None:
    """THE OUTSIDE-REVIEW GATE: a run's report is composed only when its review ran or the decision not to
    run one was recorded. Silence is not a third option.

    A refusal, not a warning: Step 7's first pass runs without --strict, so even a high warning stops
    nothing, and a step whose only consumer is a warning gets skipped in silence (market-sizing's review
    was, on a live paid run). Only a non-zero exit reaches SKILL.md's stop-and-report branch.

    Keyed on `run_id`, the run the report is resolved for -- the id most usable required artifacts carry
    (`_redteam_core.primary_run_id`, ties to the newest), the same id `_cp_redteam_copy.resolve` and
    `skip_reason` use, so one leftover from an earlier run cannot decide it -- never on the run's hand-off dir: a
    missing dir once read as "not a run that can be judged", so deleting it silenced the gate. A stub
    carries no analysis, so its id is not a run's (the caller drops stubs). Accepting a review of ANY id
    the artifacts carry let an earlier run's review pass a set with one artifact left from that run,
    while the report showed no review; `all_run_ids` only names that mixed set in the refusal. A run with
    no sub-agents records `no_subagent_dispatch`. RESIDUAL, stated: deleting the review and the skip
    record trips this refusal rather than passing it; hand-writing a skip record is a named fabrication.
    """
    if not run_id:
        return
    if any(_as_dict(_as_dict(r).get("metadata")).get("run_id") == run_id for r in reviews):
        return
    rec = _as_dict(skip_record)
    recorded = rec.get("reason")
    if _as_dict(rec.get("metadata")).get("run_id") == run_id:
        if recorded in _cp_redteam_copy.SKIP_REASONS:
            return
        detail = f"red_team_skip.json records {recorded!r}, which is not a recognised reason"
    else:
        others = sorted(
            {
                rid
                for r in reviews
                if isinstance(rid := _as_dict(_as_dict(r).get("metadata")).get("run_id"), str) and rid
            }
        )
        if others:
            # A review exists, for another run. Recording a skip would hide the review this analysis has;
            # the remedy is a review of this run, under this run's id.
            detail = (
                f"a review exists for run {', '.join(others)}, not this run {run_id}. Re-run Step 6.5 with "
                f"RUN_ID {run_id} (the prompt generator and cp_red_team.py both take it); do not record a "
                "skip to get past this"
            )
            sys.stdout.write(
                json.dumps({"validation": {"status": "invalid", "errors": [detail + "."]}}, indent=2) + "\n"
            )
            print(f"Error: report not composed: {detail}.", file=sys.stderr)
            sys.exit(1)
        detail = "no outside review ran for this run and no decision to skip one was recorded"
        if len(all_run_ids) > 1:
            detail += (
                f" (STALE_ARTIFACT: the analysis files carry more than one run id, "
                f"{', '.join(sorted(all_run_ids))}; this run is {run_id}, and a review or skip of another "
                "run does not count)"
            )
    known = ", ".join(_cp_redteam_copy.SKIP_REASONS)
    errors = [
        f"{detail}. Run Step 6.5, or record why it did not run with record_red_team_skip.py --reason <one of: {known}>."
    ]
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": errors}}, indent=2) + "\n")
    print(f"Error: report not composed: {errors[0]}", file=sys.stderr)
    sys.exit(1)


# A review's quote is the source's words. The founder-text pass rewrites internal tokens in the assembled
# report and would run over quotes too, showing the founder a "quotation" the source never contained. The
# review section fences each quote with these private-use sentinels; compose lifts them out before any
# rewriting and restores them after.
_QUOTE_OPEN = "\ue000"
_QUOTE_CLOSE = "\ue001"
_QUOTE_RE = re.compile("\ue000(.*?)\ue001", re.DOTALL)
_QUOTE_SLOT_RE = re.compile("\ue002(\\d+)\ue003")


def _section_outside_review(
    review: dict[str, Any] | None, skip: str | None, others: list[tuple[int, dict[str, Any]]]
) -> str:
    """What an outside review of this analysis turned up.

    Three states that must read differently: it never ran, it ran and found nothing, it found
    something. "No findings" and "nobody looked" are opposite facts about a report. Every field is the
    reviewer's text, already worded by the producer, and is made inert for markdown here; quotes are
    fenced so no later pass rewords them.
    """
    outcome = _view.review_outcome(review, skip)
    if outcome is None:
        return ""
    lines = ["## What an Outside Review Found\n", f"*{_view.md_inline(outcome)}*\n"]

    def _finding(f: dict[str, Any]) -> list[str]:
        sev = _view.SEVERITY_WORDS.get(str(f.get("severity")), "")
        claim = _md_escape(_view.md_inline(str(f.get("claim_attacked") or "").strip()))
        out = [f"\n**{sev}: {claim}**\n", _md_escape(_view.md_inline(str(f.get("what_is_true") or "").strip())) + "\n"]
        quote = str(f.get("evidence_quote") or "").strip()
        if quote:
            out.append(f"> {_QUOTE_OPEN}{_view.md_inline(quote)}{_QUOTE_CLOSE}\n")
        src = _view.review_source(f)
        if src["kind"] == "link" and src["url"].lower().startswith(("http://", "https://")):
            label = _md_escape(_view.md_inline(src["text"])).replace("]", "\\]")
            out.append(f"— [{label}](<{src['url'].replace('>', '%3E')}>)\n")
        else:
            out.append(f"— {_md_escape(_view.md_inline(src['text']))}\n")
        return out

    if review is not None:
        for f in _view.review_findings(review):
            lines.extend(_finding(f))
        unchecked = [str(c) for c in _as_list(review.get("could_not_check")) if str(c).strip()]
        if unchecked:
            lines.append("\n**What the review could not check:**\n")
            lines.extend(f"- {_md_escape(_view.md_inline(c))}" for c in unchecked)
            lines.append("")
        unread = [str(n) for n in _as_list(review.get("sources_unread")) if str(n).strip()]
        if unread:
            lines.append(
                "\n**Your documents the review did not open:** " + ", ".join(_view.md_inline(n) for n in unread) + "\n"
            )
    # Every other review of this run, in full (`_cp_redteam_copy.other_rounds`).
    for n, doc in others:
        lines.append(f"\n### Another review of this analysis (review {n})\n")
        extra = _view.review_findings(doc)
        if not extra:
            lines.append("It raised no challenges it could evidence.\n")
        for f in extra:
            lines.extend(_finding(f))
    return "\n".join(lines) + "\n"


def _handoff_bypassed(dir_path: str, artifacts: dict[str, Any]) -> list[str]:
    """Which sub-agent steps this report's artifacts came from have no gated hand-off in this run.

    Built from the artifacts present, never from what SKILL.md says should run: each artifact a
    sub-agent's hand-off is piped into means that step ran. The blind recall is optional -- required
    only when the verification recorded a non-empty blind set -- and the landscape enrichment
    re-dispatch only when its hand-off is on disk.

    A missing `handoff/<run_id>/` is NOT silence: with no dir there are no gate records, so every step
    the artifacts show ran is reported unchecked. RESIDUAL: the enrichment re-dispatch is required
    only when its hand-off is on disk, so deleting the dir removes that one step's warning (the others
    still fire). A run that dispatched no sub-agent has none of these artifacts, so nothing is required
    of it.

    RESIDUAL: a pass proves a gated hand-off exists and still matches its record -- not that the
    producer consumed it. See `_handoff_audit.py`.
    """
    audit = _handoff_audit()
    if audit is None:
        return []
    run_id = next(
        (
            rid
            for name in REQUIRED_ARTIFACTS
            if isinstance(artifacts.get(name), dict)
            and isinstance(rid := _as_dict(artifacts[name].get("metadata")).get("run_id"), str)
            and rid
        ),
        None,
    )
    if not run_id:
        return []
    run_dir = os.path.join(dir_path, "handoff", run_id)
    requirements: list[tuple[str, list[str]]] = []
    verification = artifacts.get("competitor_verification.json")
    if isinstance(verification, dict):
        requirements.append(("the challenge to the competitor list", ["competitor_verification_output.json"]))
        blind = _as_dict(verification.get("recall_gaps")).get("blind_set_size")
        if isinstance(blind, int) and blind > 0:
            requirements.append(("the independent recall of competitors", ["competitor_recall_output.json"]))
    if isinstance(artifacts.get("landscape.json"), dict):
        requirements.append(("the competitor research", ["landscape_research_output.json"]))
    if os.path.isfile(os.path.join(run_dir, _ENRICHMENT_HANDOFF)):
        requirements.append(("the research on the competitors you added", [_ENRICHMENT_HANDOFF]))
    if isinstance(artifacts.get("startup_research.json"), dict):
        requirements.append(("the research on your company's public record", ["startup_research_output.json"]))
    if isinstance(artifacts.get("moat_scores.json"), dict):
        requirements.append(("the moat scoring", ["moat_scoring_output.json"]))
    if isinstance(artifacts.get("positioning_scores.json"), dict):
        requirements.append(("the positioning scoring", ["positioning_scoring_output.json"]))
    if isinstance(artifacts.get("checklist.json"), dict):
        requirements.append(("the quality checklist", ["checklist_output.json"]))
    if isinstance(artifacts.get("redteam.json"), dict):
        requirements.append(("the outside review", ["redteam_output.json"]))
    labels: list[str] = audit.bypassed(run_dir, requirements)
    return labels


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


def _competitor_names(
    landscape: dict[str, Any] | None, landscape_draft: dict[str, Any] | None = None
) -> dict[str, str]:
    """Map competitor slug -> display name for report.md, made inert for markdown.

    The one choke point for names in this file: every table, sentence, warning and coaching line
    compose writes takes its names from here (see `_view.md_inline`).
    """
    return _view.md_names(_view.competitor_names(landscape, landscape_draft))


def _display_name(slug: str, name_by_slug: dict[str, str] | None) -> str:
    """Render a competitor's display name; fall back to the slug when unknown."""
    return _view.display_name(slug, name_by_slug)


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
        "unproven": "Unproven",
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
    """Truncate long evidence strings for table cells, at a word boundary.

    A plain character cut ended cells mid-token ("…$500K-$1.4M+ (newer G2 600 model ~$1.4M) plus"
    was fine; "…but th…" was not), which reads as a rendering bug.
    """
    if not text or len(text) <= max_len:
        return text
    cut = text[:max_len]
    if " " in cut and not text[max_len].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:—-") + "…"


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


def _confirmed_override_count(artifacts: dict[str, dict[str, Any] | None]) -> int:
    """Founder overrides that changed a scored value: coordinates plus moat ratings.

    The `founder_override` stamp alone is model-written, and was measured on a first-pass rating
    the founder never saw. An override counts only where the value differs from the scorer's first
    copy of this run (`_cp_view.confirmed_*_overrides`). positioning.json's draft moat block is
    not read: it is superseded by moat_scores.json and has no first copy to compare against.
    """

    def _safe(name: str) -> dict[str, Any] | None:
        data = artifacts.get(name)
        return data if _usable(data) else None

    positioning = _safe("positioning.json")
    coords = _view.confirmed_coordinate_overrides(positioning, _safe(_view.FIRST_POSITIONING_SCORES))
    moats = _view.confirmed_moat_overrides(_safe("moat_scores.json"), _safe(_view.FIRST_MOAT_SCORES))
    return len(coords) + len(moats)


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
        "startup_research.json": "validate_startup_research",
        "redteam.json": "cp_red_team",
        "red_team_skip.json": "record_red_team_skip",
        # The three artifacts the MAIN THREAD authors. Until `persist_agent_artifact.py`
        # existed they had no producer to stamp them, so they were the exact complement of
        # this map -- the enforcement was built, high-severity, and structurally blind to
        # the artifacts most in need of it. What this buys is presence-of-keys and
        # provenance, NOT shape: `_produced_by` is a self-reported string in a file the
        # model writes, and a required-keys check cannot see the extra-keys failure mode.
        "product_profile.json": "persist_agent_artifact",
        "landscape_draft.json": "persist_agent_artifact",
        "positioning.json": "persist_agent_artifact",
    }
    for name, expected in EXPECTED_PRODUCERS.items():
        data = artifacts.get(name)
        if _usable(data) and data.get("_produced_by") != expected:
            warnings.append(
                _warn(
                    "UNVALIDATED_ARTIFACT",
                    f"Artifact '{name}' exists but was not produced by {expected}.py — "
                    f"run the script instead of writing the file directly",
                    # The agent-facing `message` NAMES A SCRIPT AND AN ARTIFACT FILE, and
                    # report.md renders `message` when no founder_message is supplied -- so
                    # every firing of this warning previously put two internal tokens into a
                    # founder-visible report. `test_composed_report_carries_no_internal_tokens`
                    # could not see it: fixtures are stamped, so the warning never fires there,
                    # and a warning that only leaks when it fires is invisible to a zero ratchet
                    # driven by clean fixtures. Found by running compose against a deliberately
                    # unstamped artifact.
                    founder_message=(
                        "Part of this analysis was assembled outside the checked pipeline, so it "
                        "hasn't been through the same validation as the rest. Re-run the analysis "
                        "step that produces it before relying on this section."
                    ),
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
                    "the quality checklist was graded against a different positioning map than "
                    "the current positioning scores (fingerprint mismatch) — re-run "
                    "checklist.py against the current scores before composing",
                    founder_message=(
                        "The quality score was calculated from an earlier version of the "
                        "positioning map, so it does not describe the analysis in this report."
                    ),
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
        current = artifacts.get("competitor_verification.json")
        # A PRIOR GOOD ARTIFACT MUST NOT SILENCE THIS. Keying only on "the artifact is absent"
        # left a second way for a refusal to disappear: re-run verification in a REVIEW_DIR that
        # still holds an earlier run's file, have it refused, and the report composes on the STALE
        # verification with nothing saying so. That collapses "refused" into "stale but present"
        # the same way the original defect collapsed "refused" into "skipped". Run-id parity is
        # what tells them apart, and STALE_ARTIFACT is not a substitute -- it is medium and names
        # a symptom.
        stale_or_absent = not _usable(current)
        if not stale_or_absent:
            rid = _as_dict(_as_dict(current).get("metadata")).get("run_id")
            try:
                with open(rejected, encoding="utf-8") as f:
                    rejected_rid = _as_dict(_as_dict(json.load(f)).get("metadata")).get("run_id")
            except (OSError, json.JSONDecodeError, ValueError):
                rejected_rid = None
            stale_or_absent = bool(rejected_rid) and rejected_rid != rid
        if os.path.exists(rejected) and stale_or_absent:
            warnings.append(
                _warn(
                    "VERIFICATION_REJECTED",
                    "The competitor-set verification was run and REJECTED — the competitor set in "
                    "this report has not been independently checked. Re-dispatch the verification "
                    "and re-run the producer before treating the set as verified.",
                )
            )

    # 2. STALE_ARTIFACT — run_id consistency
    #
    # Not the review or its skip record: a run writes one of the two, so the other is routinely an
    # earlier run's, left in place because we never delete under outputs (our rule). Flagged here it would be high
    # with a remedy ("re-run") that never rewrites it, stopping Step 7's --strict pass on a file the
    # run had no reason to touch. Their parity is decided where the review is resolved: an earlier
    # run's review or skip is simply not this run's (`_cp_redteam_copy.resolve` / `skip_reason`).
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        if name in _cp_redteam_copy.RUN_SCOPED:
            continue
        data = artifacts.get(name)
        if _usable(data):
            rid = _as_dict(data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_ids[name] = rid
    if run_ids:
        # "Expected" is the id the review gate resolves for (`_redteam_core.primary_run_id`), so the
        # leftover is what gets named. Taking the first artifact's id named the fresh files as stale
        # whenever the leftover was listed first, and re-running them could never clear it.
        primary_rid = (
            _cp_redteam_copy.primary_run_id_in(artifacts_dir, artifacts, REQUIRED_ARTIFACTS)
            if artifacts_dir
            else _cp_redteam_copy.primary_run_id(artifacts.get(n) for n in REQUIRED_ARTIFACTS)
        ) or next(iter(run_ids.values()))
        for name, rid in run_ids.items():
            if rid != primary_rid:
                warnings.append(
                    _warn(
                        "STALE_ARTIFACT",
                        f"{name} has run_id '{rid}' but expected '{primary_rid}'",
                        # Same class as UNVALIDATED_ARTIFACT above: the agent-facing `message`
                        # names an artifact FILE and two internal run ids, and report.md renders
                        # `message` when no founder_message is given. Found by running compose
                        # with deliberately mismatched run_ids -- the fleet zero-token ratchet
                        # cannot see it, because its fixtures share one run_id so this warning
                        # never fires there.
                        founder_message=(
                            "Part of this analysis is left over from an earlier run and does not "
                            "match the rest, so the sections below may not be consistent with each "
                            "other. Re-run the analysis from the start before relying on it."
                        ),
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
                            f"Orphan competitor '{slug}' in the moat scoring — not in landscape",
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
                                f"Orphan competitor '{p_slug}' in the positioning analysis views — not in landscape",
                            )
                        )
            for slug in _as_dict(positioning.get("moat_assessments")):
                if slug == "_startup":
                    continue
                if slug not in landscape_slugs:
                    warnings.append(
                        _warn(
                            "CORRUPT_ARTIFACT",
                            f"Orphan competitor '{slug}' in the positioning analysis "
                            "moat_assessments — not in landscape",
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
                        f"View '{vid}': the positioning analysis coordinates for {mismatched} differ from "
                        "the positioning scores — the scored merge back into the positioning analysis was "
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
    # 11. CAP_DISPLACED_DIRECT
    verification = artifacts.get("competitor_verification.json")
    verdict_pairs = [
        (str(_as_dict(v).get("slug") or ""), str(_as_dict(v).get("verdict") or ""))
        for v in (_as_list(verification.get("verdicts")) if _usable(verification) else [])
    ]
    first_landscape = artifacts.get(_view.FIRST_LANDSCAPE)
    left_out, kept_non = _view.displaced_direct(
        artifacts.get("landscape.json") if _usable(artifacts.get("landscape.json")) else None,
        first_landscape if _usable(first_landscape) else None,
        verdict_pairs,
    )
    if left_out:
        names = _competitor_names(artifacts.get("landscape.json") if _usable(artifacts.get("landscape.json")) else None)
        out_names = ", ".join(_view.md_inline(name) for _, name in left_out)
        kept_names = ", ".join(_view.display_name(slug, names) for slug in kept_non)
        warnings.append(
            _warn(
                "CAP_DISPLACED_DIRECT",
                f"set at {_view.MAX_COMPETITORS}: direct suggestion(s) {[s for s, _ in left_out]} left out while "
                f"not_a_competitor entries {kept_non} kept a slot",
                founder_message=(
                    f"Research found {out_names}, a direct competitor, but the set was full at "
                    f"{_view.MAX_COMPETITORS} and it was left out, while {kept_names}, judged not to be a "
                    f"competitor, kept its place. Swapping them would compare you against the right company."
                ),
            )
        )

    override_count = _confirmed_override_count(artifacts)
    if override_count > 0:
        warnings.append(
            _warn(
                "FOUNDER_OVERRIDE_COUNT",
                f"{override_count} positioning coordinates or moat ratings were changed at the founder's "
                f"correction after they were first scored",
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
    name_by_slug: dict[str, str] | None = None,
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
    if positioning_scores is not None and not _is_stub(positioning_scores):
        # Where the startup stands, in words, per map. No differentiation number: it read as a
        # percentage and mislabelled a startup that led on both axes (see `_cp_view.view_sentence`).
        # No label prefix: each sentence already names its two axes.
        stand = [_view.view_sentence(_as_dict(v), name_by_slug) for v in _as_list(positioning_scores.get("views"))]
        stand = [st for st in stand if st]
        if stand:
            lines.append("**Where you stand:**")
            lines.extend(f"- {st}" for st in stand)
            lines.append("")

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

    return "\n".join(lines) + "\n"


def _section_startup_record(first: dict[str, Any] | None, current: dict[str, Any] | None) -> str:
    """What public records show about the startup: its legal name and its patent publications.

    Rendered from the run's FIRST record (the producer's frozen copy), with each publication's
    computed status and its source; a later record that disagrees is listed, never substituted.
    Empty when the research step did not run, so no search is implied.
    """
    record = first if first is not None else current
    if record is None:
        return ""
    lines = ["## What Public Records Show\n"]
    legal = _as_dict(record.get("legal_name"))
    if legal.get("value"):
        lines.append(
            f"**Registered legal name:** {_view.md_inline(str(legal['value']))} "
            f"(source: {_view.md_inline(str(legal.get('source') or ''))})"
        )
    family = _view.FAMILY_WORDS.get(str(record.get("family_status")))
    if family:
        lines.append(f"**Patents:** {family}.")
    lines.append("")
    rows = _view.publication_rows(record)
    if rows:
        lines.append("| Publication | Office | Status | What was read | Source |")
        lines.append("|-------------|--------|--------|---------------|--------|")
        for r in rows:
            cells = [r["number"], r["office"], r["status"], r["read"], r["source"]]
            lines.append("| " + " | ".join(_md_escape(_view.md_inline(c)) for c in cells) + " |")
        lines.append("")
        lines.append(
            "_Each record above was found by the analysis's web research; check it at its source before relying on it._"
        )
        lines.append("")
    nothing = [str(q) for q in _as_list(record.get("searched_none")) if q]
    if nothing:
        lines.append("**Searched, nothing found:** " + "; ".join(_view.md_inline(q) for q in nothing))
        lines.append("")
    if first is not None and current is not None:
        disagreements = _view.record_disagreements(first, current)
        if disagreements:
            lines.append("**A later record disagreed:** " + "; ".join(_view.md_inline(d) for d in disagreements))
            lines.append("")
    return "\n".join(lines) + "\n"


def _section_proof_gap(positioning_scores: dict[str, Any] | None) -> str:
    """What is shown and what is claimed, for a map that scores the startup's plan."""
    gap = _view.proof_gap(positioning_scores)
    if gap is None:
        return ""
    lines = ["## What Is Shown and What Is Claimed\n"]
    lines.append(_view.ASYMMETRY)
    lines.append("")
    if gap["availability"]:
        quote = f' ("{_view.md_inline(gap["availability_quote"])}")' if gap["availability_quote"] else ""
        lines.append(f"**How far the product has got:** {gap['availability']}{quote}")
        lines.append("")
    lines.append("| Map | Axis | Planned position | What backs it |")
    lines.append("|-----|------|------------------|---------------|")
    for r in gap["rows"]:
        cells = [r["map"], r["axis"], r["proof"], r["quote"] or "—"]
        lines.append("| " + " | ".join(_md_escape(_view.md_inline(c)) for c in cells) + " |")
    lines.append("")
    if gap["open_claims"]:
        lines.append("**Claims not yet settled:**")
        lines.extend(f"- {_view.md_inline(c)}" for c in gap["open_claims"])
        lines.append("")
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
        name = _view.md_inline(str(c.get("name", "?")))
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
        name = _view.md_inline(str(c.get("name") or c.get("slug") or "?"))
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
        retained, removed = _view.challenge_outcome(
            ((str(v.get("slug") or ""), str(v.get("verdict") or "")) for v in verdicts), landscape
        )
        if retained:
            names = ", ".join(_display_name(slug, name_by_slug) for slug in retained)
            lines.append(
                f"**Retained despite the challenge:** {names}. This entry is scored and ranked "
                f"alongside the rest, so read its position with the verdict above in mind."
            )
            lines.append("")
        if removed:
            names = ", ".join(_display_name(slug, name_by_slug) for slug in removed)
            lines.append(
                f"**Removed after the challenge:** {names}. "
                f"{'It is' if len(removed) == 1 else 'They are'} not part of the scored set."
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
                _display_name(str(c.get("slug", "?")), name_by_slug) or _view.md_inline(str(c.get("name", "?")))
                for c in unverified
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
            label = _view.md_inline(str(u.get("name", u.get("slug", "?"))))
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
    name_by_slug: dict[str, str] | None = None,
    startup_name: str | None = None,
) -> str:
    """Positioning analysis with per-view details and evidence points table."""
    if positioning_scores is None or _is_stub(positioning_scores):
        return "## Positioning Analysis\n\n*No positioning scores available.*\n"

    lines = ["## Positioning Analysis\n"]
    basis_label = _scoring_basis_label(_resolve_scoring_basis(positioning_scores, positioning))
    lines.append(f"**Scoring Basis:** {basis_label}\n")

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
        # A label, else "<X axis> vs <Y axis>": title-casing a slug id leaked it into the heading.
        vid = _view.view_label(view)
        lines.append(f"### {vid}\n")
        lines.append(f"- **X-Axis:** {view.get('x_axis_name', '?')}")
        lines.append(f"  - Rationale: {view.get('x_axis_rationale', '?')}")
        vanity_x = "Yes — axis may not reveal meaningful differentiation" if view.get("x_axis_vanity_flag") else "No"
        lines.append(f"  - Vanity axis: {vanity_x}")
        lines.append(f"- **Y-Axis:** {view.get('y_axis_name', '?')}")
        lines.append(f"  - Rationale: {view.get('y_axis_rationale', '?')}")
        vanity_y = "Yes — axis may not reveal meaningful differentiation" if view.get("y_axis_vanity_flag") else "No"
        lines.append(f"  - Vanity axis: {vanity_y}")
        stand = _view.view_sentence(view, name_by_slug)
        if stand:
            lines.append(f"- **Where you stand:** {stand}")
        # `_compute_rank` counts competitors strictly ahead, +1 — so rank `competitor_count + 1`
        # is reachable and means "behind every competitor". Rendering that against
        # `competitor_count` produced the literal nonsense "Y=11 (of 10 competitors)". Report the
        # denominator as the number of entities actually ranked, startup included, which is also
        # the convention the moat section uses.
        _ccount = view.get("competitor_count")
        _ranked = f"{_ccount + 1}" if isinstance(_ccount, int) else "?"
        x_place = _view.axis_place(view.get("startup_x_rank"), view.get("startup_x_tied_with"), name_by_slug)
        y_place = _view.axis_place(view.get("startup_y_rank"), view.get("startup_y_tied_with"), name_by_slug)
        lines.append(f"- **Startup Rank:** X={x_place}, Y={y_place} (of {_ranked} ranked)")
        lines.append("")

        # Points evidence table (from positioning.json views[].points[])
        points = pos_views_by_id.get(vid_key, [])
        if points:
            x_name = _view.short_axis_name(view.get("x_axis_name")) or "X"
            y_name = _view.short_axis_name(view.get("y_axis_name")) or "Y"
            lines.append(
                f"| Company | {_md_escape(x_name)} | {_md_escape(y_name)} "
                f"| {_md_escape(x_name)} evidence | {_md_escape(y_name)} evidence |"
            )
            lines.append("|---------|------|------|------------|------------|")
            estimated = 0
            for pt in points:
                pt = _as_dict(pt)
                slug = pt.get("competitor", "?")
                # "~" marks a position the analysis estimated rather than sourced -- a disclosure of
                # what the scoring pass itself recorded, so a guess never reads as a measurement.
                x_est = pt.get("x_evidence_source") == "agent_estimate"
                y_est = pt.get("y_evidence_source") == "agent_estimate"
                estimated += int(x_est) + int(y_est)
                x_val = f"~{pt.get('x', '?')}" if x_est else pt.get("x", "?")
                y_val = f"~{pt.get('y', '?')}" if y_est else pt.get("y", "?")
                x_ev = _md_escape(_truncate_evidence(str(pt.get("x_evidence", ""))))
                y_ev = _md_escape(_truncate_evidence(str(pt.get("y_evidence", ""))))
                company = _md_escape(_view.row_name(str(slug), name_by_slug, startup_name))
                lines.append(f"| {company} | {x_val} | {y_val} | {x_ev} | {y_ev} |")
                if slug == "_startup" and pt.get("planned_x") is not None and pt.get("planned_y") is not None:
                    px_ev = _md_escape(_truncate_evidence(str(pt.get("planned_x_evidence", ""))))
                    py_ev = _md_escape(_truncate_evidence(str(pt.get("planned_y_evidence", ""))))
                    lines.append(
                        f"| {company} (if delivered) | {pt.get('planned_x')} | {pt.get('planned_y')} "
                        f"| {px_ev} | {py_ev} |"
                    )
            lines.append("")
            if estimated:
                lines.append(
                    f"_~ marks the analysis's own estimate ({estimated} of {2 * len(points)} positions on this map); "
                    f"unmarked positions cite research or the founder._"
                )
                lines.append("")

    return "\n".join(lines) + "\n"


def _section_moat_assessment(
    moat_scores: dict[str, Any] | None,
    name_by_slug: dict[str, str] | None = None,
    first_moat_scores: dict[str, Any] | None = None,
    startup_name: str | None = None,
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

        confirmed = _view.confirmed_moat_overrides(moat_scores, first_moat_scores)
        # Moat table for _startup — with evidence text as a bullet under each row
        lines.append("| Moat | Status | Trajectory | Evidence Source |")
        lines.append("|------|--------|------------|----------------|")
        moat_evidence_pairs: list[tuple[str, str]] = []
        for moat in _as_list(startup.get("moats")):
            moat = _as_dict(moat)
            mid = _humanize(str(moat.get("id", "?")))
            status = _humanize(str(moat.get("status", "?")))
            traj = _humanize(str(moat.get("trajectory", "?")))
            source = str(moat.get("evidence_source", "?"))
            if source == "founder_override" and ("_startup", str(moat.get("id"))) not in confirmed:
                # A stamp with no change behind it: say nothing about who set this rating.
                src = "—"
            else:
                src = _humanize(source)
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
            # The producer's `{"rank": -1, "total": 0}` sentinel means the startup is `not_applicable`
            # here; rendered verbatim it produced `Rank -1 of 0 ranked`.
            if ri.get("rank") == _NOT_RANKABLE_RANK or ri.get("total") == 0:
                lines.append(f"- **{_humanize(dim)}:** Not applicable to this business model")
                continue
            # Standing, ties and leaders are computed from the scored statuses by `_cp_view`: the
            # producer's rank gives a tie the better place, so an absent moat read "Rank 1 of 8".
            standing = _view.moat_standing(_as_dict(by_dimension.get(dim)), competitor_slugs, name_by_slug, _humanize)
            if standing is None:
                continue
            lines.append(f"- **{_humanize(dim)}:** {standing}")
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
        # Full names: a 12-character cut printed "Network Effe" and "Regulatory B" as headers.
        header_dims = " | ".join(_humanize(d) for d in canonical_dims)
        lines.append(f"| Company | {header_dims} |")
        lines.append("|---------|" + "|".join(["-------"] * len(canonical_dims)) + "|")
        for slug in all_slugs:
            row_data = []
            for dim in canonical_dims:
                dim_map = _as_dict(by_dimension.get(dim))
                val = dim_map.get(slug, "—")
                row_data.append(_status_short.get(val, val[:3] if isinstance(val, str) else "—"))
            display = _md_escape(_view.row_name(slug, name_by_slug, startup_name))
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
    name_by_slug: dict[str, str] | None = None,
) -> str:
    """Script-generated key findings from scoring data."""
    lines = ["## Key Findings\n"]
    findings: list[str] = []

    # From positioning scores
    if positioning_scores is not None and not _is_stub(positioning_scores):
        # Per map, who is ahead on both axes and who is nearest -- computed, no score (see
        # `_cp_view.view_verdict`). The banded "Weak differentiation (35%)" line called a startup
        # that ranked 1st on an axis of every map "close to competitors".
        for view in _as_list(positioning_scores.get("views")):
            view = _as_dict(view)
            verdict = _view.view_verdict(view, name_by_slug)
            if verdict:
                findings.append(f"{_view.view_label(view)}: {verdict}")

        # Vanity axis findings
        for view in _as_list(positioning_scores.get("views")):
            view = _as_dict(view)
            if view.get("x_axis_vanity_flag") or view.get("y_axis_vanity_flag"):
                findings.append(
                    f"Vanity axis detected in the {_view.view_label(view)} map — "
                    "axis may not reveal meaningful differentiation."
                )

        # Stress-test findings
        # From the scorer's tally (`_cp_view.claims_tally`), so the parts sum to the total. An
        # artifact that predates the tally gets the same tally computed here.
        scored = dict(positioning_scores)
        if "verdict_counts" not in scored:
            counts = {v: 0 for v in ("holds", "partially_holds", "does_not_hold", "unproven", "unrecognised")}
            claims = _as_list(positioning_scores.get("differentiation_claims"))
            for c in claims:
                v = _as_dict(c).get("verdict")
                counts[v if v in counts and v != "unrecognised" else "unrecognised"] += 1
            scored["verdict_counts"] = {**counts, "total": len(claims)}
        tally = _view.claims_tally(scored)
        if tally:
            findings.append(tally)

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
    positioning_scores: dict[str, Any] | None = None,
    name_by_slug: dict[str, str] | None = None,
    startup_research: dict[str, Any] | None = None,
    outside_review: list[str] | None = None,
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

    `positioning` and `claim_verdicts` are the same computed sentences the report shows, for the
    same reason: the coach is asked how to answer "why won't X crush you", and with no map and no
    stress-test it never mentioned that the pitch's headline claim failed (both baseline runs; one
    told the founder nothing had raised a serious red flag). Sentences, not numbers, so there is
    nothing to convert.
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
        "positioning": _view.map_sentences(positioning_scores, name_by_slug),
        "claim_verdicts": _view.claim_sentences(positioning_scores),
        # What public records show about the startup, from the run's first record: the coach quotes
        # the computed patent status instead of restating the pitch's ("patent-pending" for a
        # granted family was the measured failure).
        "startup_record": _view.startup_record_sentences(startup_research),
        # What the outside review found, in the report's own words: its outcome, then one sentence per
        # finding, most serious first. The coach otherwise has no way to know a serious challenge was
        # raised, and would reassure the founder beside it.
        "outside_review": list(outside_review or []),
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
    # The scorers' first copies of this run, the comparand for a founder override (`_cp_first_copy`).
    for name in (
        _view.FIRST_MOAT_SCORES,
        _view.FIRST_POSITIONING_SCORES,
        _view.FIRST_LANDSCAPE,
        _view.FIRST_STARTUP_RESEARCH,
    ):
        artifacts[name] = _load_artifact(dir_path, name)

    # The review every reader below sees is its append-only copy, never `redteam.json` as it now stands
    # (`_cp_redteam_copy`, rules in the shared `_redteam_core`).
    # This run's id, from the usable required artifacts only (a stub is no analysis), as visualize.py
    # reads it -- ONE id for the resolver, the gate and the skip reason, so they agree on whose review it is.
    # The id most of them carry, not the first one's: landscape.json is listed first, and a leftover there
    # once made an earlier run's review count as this run's.
    _rt_required = [a for a in (artifacts.get(n) for n in REQUIRED_ARTIFACTS) if _usable(a)]
    _rt_run_id = _cp_redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)
    _rt_shown, _rt_codes, _rt_facts = _cp_redteam_copy.resolve(
        dir_path,
        _rt_run_id,
        artifacts.get("redteam.json"),
        artifacts.get("red_team_skip.json"),
    )
    # Unconditionally, not only when this run has copies: `resolve` returns None for an earlier run's
    # review, and every check below (the hand-off audit, provenance) must key on THIS run's review. The
    # analysis dir is per company, so a re-run that recorded a skip otherwise inherited the last run's
    # review and was told the review had bypassed a hand-off it never made.
    _rt_refuse(
        _rt_run_id,
        {rid for a in _rt_required if isinstance(rid := _as_dict(a.get("metadata")).get("run_id"), str) and rid},
        # The review as it stands, and the one shown (from its append-only copy, which outlives an edit
        # or a delete of redteam.json).
        (artifacts.get("redteam.json"), _rt_shown),
        artifacts.get("red_team_skip.json"),
    )
    artifacts["redteam.json"] = _rt_shown
    _rt_skip = _cp_redteam_copy.skip_reason(artifacts.get("red_team_skip.json"), _rt_run_id)
    _rt_review = _rt_shown if isinstance(_rt_shown, dict) and _rt_shown is not _CORRUPT else None

    # Normalize positioning.json before validation (best-effort)
    positioning_raw = artifacts.get("positioning.json")
    if _usable(positioning_raw):
        _normalize_positioning(positioning_raw)

    artifacts_loaded = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]

    # Run validation
    warnings = validate_artifacts(artifacts, dir_path)
    _bypassed_steps = _handoff_bypassed(dir_path, artifacts)
    if _bypassed_steps:
        _msg = _handoff_audit().founder_message(_bypassed_steps)
        warnings.append(_warn("HANDOFF_BYPASSED", _msg, _msg))
    # `message` carries the remedy for the run; the founder reads what happened.
    warnings.extend(_warn(code, message, _REVIEW_FOUNDER_MESSAGES.get(code)) for code, message in _rt_codes)

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
            if code in _UNACCEPTABLE_MEDIUM:
                print(
                    f"Warning: cannot accept '{code}' -- it discloses how this run was carried out and "
                    "stays in the report; ignored",
                    file=sys.stderr,
                )
            elif code in WARNING_SEVERITY and WARNING_SEVERITY[code] in ACCEPTIBLE_SEVERITIES:
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
    name_by_slug = _competitor_names(landscape, _render_safe(artifacts.get("landscape_draft.json")))
    startup_name = _view.md_inline(str(_as_dict(product_profile).get("company_name") or "").strip()) or None
    # The verdict: the report's first paragraph, and what the pages and cp_closing_message.py carry, word
    # for word. Built once, here, by `_cp_view.verdict`; the pages read it from report.json.
    research_record = next(
        (
            a
            for a in (artifacts.get(_view.FIRST_STARTUP_RESEARCH), artifacts.get("startup_research.json"))
            if _usable(a)
        ),
        None,
    )
    verdict_text = _view.verdict(
        _as_dict(positioning_scores) if _usable(positioning_scores) else None,
        _as_dict(moat_scores) if _usable(moat_scores) else None,
        research_record,
        name_by_slug,
        _rt_review,
        _rt_skip,
    )
    sections = [
        _section_title(product_profile, landscape),
        verdict_text + "\n" if verdict_text else "",
        _section_executive_summary(product_profile, positioning_scores, moat_scores, checklist, name_by_slug),
        _section_outside_review(
            _rt_review, _rt_skip, _cp_redteam_copy.other_rounds(dir_path, _rt_run_id, _rt_facts.get("round_shown"))
        ),
        _section_startup_record(
            _render_safe(artifacts.get(_view.FIRST_STARTUP_RESEARCH)),
            _render_safe(artifacts.get("startup_research.json")),
        ),
        _section_competitor_landscape(landscape),
        _section_recent_developments(landscape),
        _section_competitor_verification(competitor_verification, name_by_slug, landscape),
        _section_positioning(positioning_scores, positioning_safe, name_by_slug, startup_name),
        _section_proof_gap(positioning_scores),
        _section_moat_assessment(
            moat_scores, name_by_slug, _render_safe(artifacts.get(_view.FIRST_MOAT_SCORES)), startup_name
        ),
        _section_stress_test(positioning_scores),
        _section_key_findings(positioning_scores, moat_scores, checklist, name_by_slug),
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
    _quotes: list[str] = []

    def _lift(m: re.Match[str]) -> str:
        _quotes.append(m.group(1))
        return f"\ue002{len(_quotes) - 1}\ue003"

    report_markdown = _QUOTE_RE.sub(_lift, report_markdown)
    _ft = _founder_text_policy()
    if _ft is not None:
        report_markdown = _ft.substitute(report_markdown)
        # Our own warning codes are kept: compose renders them in small print beside a humanized
        # label (the md_term convention), which is deliberate. A code leaking anywhere else is
        # caught by the skill's own gate, not by widening this scan into a false positive.
        # The same pass over the verdict alone, so the pages and the hand-over match report.md.
        verdict_text = _ft.substitute(verdict_text) if verdict_text else verdict_text
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

    # The review's quotes go back exactly as the source wrote them (see _QUOTE_OPEN).
    report_markdown = _QUOTE_SLOT_RE.sub(lambda m: _quotes[int(m.group(1))].replace("\n", "\n> "), report_markdown)

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

    founder_override_count = _confirmed_override_count(artifacts)

    # The report carries the run id the review was resolved for (`_rt_run_id`), so report.json, the gate
    # and STALE_ARTIFACT name one run. Only a set whose required artifacts carry no id falls back to the
    # first optional artifact that does.
    run_id = _rt_run_id or ""
    for name in [] if run_id else OPTIONAL_ARTIFACTS:
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
        positioning_scores=_as_dict(positioning_scores) if _usable(positioning_scores) else None,
        name_by_slug=name_by_slug,
        startup_research=next(
            (
                a
                for a in (artifacts.get(_view.FIRST_STARTUP_RESEARCH), artifacts.get("startup_research.json"))
                if _usable(a)
            ),
            None,
        ),
        outside_review=_view.review_sentences(_rt_review, _rt_skip),
    )

    return {
        "report_markdown": report_markdown,
        "verdict": verdict_text,
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


def _gate_check(dir_path: str) -> Any:
    """With the run's gate ledger, before anything is written: a delivered report composed again starts a new
    revision; every question the analysis rests on must be recorded (exit 10 names one), nothing asked may be
    left open (`GATE_UNRESOLVED`), and the map must be scored on the basis the run recorded. Returns the ledger,
    or None for a run without one (today's path, unchanged)."""
    run_id = _cp_gates.run_id_of(dir_path)
    _cp_gates.refuse_without_run_id(os.path.join(dir_path, "report.json"), run_id)
    ledger = _cp_gates.open_ledger_or_exit(dir_path, run_id)
    if ledger is None:
        return None
    _cp_gates.reopen_if_complete(dir_path, run_id, step="7")
    _cp_gates.require_or_exit(dir_path, run_id, list(_cp_gates.ALL_KEYS), by="compose_report.py")
    _cp_gates.refuse_open_gates(ledger)
    recorded = _cp_gates.recorded_basis(dir_path, run_id)
    for name in ("positioning.json", "positioning_scores.json"):
        doc = _load_artifact(dir_path, name)
        used = doc.get("scoring_basis") if isinstance(doc, dict) else None
        if recorded is not None and isinstance(used, str) and used != recorded:
            _cp_gates.basis_mismatch(recorded, used, name)
    return ledger


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    ledger = _gate_check(args.dir)
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

    if ledger is not None:
        _cp_gates.coaching_pending(ledger)

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
