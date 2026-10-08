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
import math
import os
import re
import sys
import uuid
from collections.abc import Callable
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _params  # noqa: E402
import _provenance  # noqa: E402
import _redteam_copy  # noqa: E402
import _revision_answer  # noqa: E402
import _thresholds  # noqa: E402
import _upload_names  # noqa: E402
import _view  # noqa: E402
from _redteam_text import PARAM_LABELS  # noqa: E402
from _redteam_text import humanize_claim as _humanize_claim  # noqa: E402
from _redteam_text import humanize_param as _humanize_param  # noqa: E402
from _view import (  # noqa: E402
    _CORRUPT,
    _INTERNAL_PROVENANCE,
    _RED_TEAM_SKIP_REASONS,
    CLOSE_AGREEMENT_PCT,
    DECK_MISMATCH_PCT,
    QUANTITATIVE_PARAMS,
    _adversarial_outcome,
    _as_dict,
    _as_list,
    _as_number,
    _claim_high,
    _comparable_claim,
    _compute_delta,
    _compute_provenance,
    _contested_rows,
    _document_cite,
    _factor_chain,
    _fmt_param_value,
    _fmt_usd,
    _fx_conversions,
    _horizon_mismatch,
    _is_stub,
    _range_delta,
    _resolve_currency,
    _resolve_sizing_basis,
    _self_check_line,
    _set_currency,
    _shared_input_values,
    _sizing_basis_label,
    _summary_verdict,
    _to_analysis_currency,
    _usable,
    _your_answers_lines,
    claim_disagreements,
    claim_display,
    disagreement_sentence,
)

# Canonical warning severity map — stable API, tested for completeness
WARNING_SEVERITY: dict[str, str] = {
    # "low", not medium: by the time this fires, substitute() has already corrected the text, so the
    # report is clean and what remains is an authoring task. ic-sim / market-sizing / deck-review block
    # strict mode on medium, which would fail a run over an already-fixed issue. The fleet ratchet in
    # test_compose_invariants.py is the gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # High severity — agent must fix before presenting report
    #
    # SIZING_INVALID is high because the failure it catches used to be INVISIBLE. market_sizing.py
    # rejecting its input once meant an exit-0 `{"ok":true}` receipt plus a figure-less stub written
    # over sizing.json; compose then rendered an empty sizing table with no code naming the cause.
    # High keeps it out of ACCEPTIBLE_SEVERITIES, so it cannot be accepted away.
    "SIZING_INVALID": "high",
    # Same class, other producers. `sensitivity.py` / `checklist.py` had the identical
    # exit-0-and-clobber behaviour, and a rejected step surfaced only as a MEDIUM
    # FEW_SENSITIVITY_PARAMS / CHECKLIST_INCOMPLETE — acceptable-away, and naming a
    # symptom rather than the cause.
    "ARTIFACT_INVALID": "high",
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    # The sizing cannot be called solid however the rest is graded — see
    # `_checklist_below_solid` for why that is read off the band and not an item count.
    # A statement about the run rather than about any one item, so it stays unacceptable.
    "CHECKLIST_FAILURES_CRITICAL": "high",
    "OVERCLAIMED_VALIDATION": "high",
    "UNVALIDATED_CLAIMS": "high",
    "IMPLAUSIBLE_PCT_SCALE": "high",
    # Medium severity — include in Warnings section of report
    #
    # MEDIUM IS THE POINT, not a downgrade. `ACCEPTIBLE_SEVERITIES` is exactly {"medium"},
    # so at high this could not be accepted with a stated reason at all, and SKILL.md's
    # advice for a high warning — fix the underlying issue and re-run — was being given for
    # a CONTENT finding. That is an instruction to re-run until a true finding disappears.
    # A founder whose SOM share is deliberately conservative can now say so; a run with more
    # failures than `solid` allows still cannot (see CHECKLIST_FAILURES_CRITICAL above).
    "CHECKLIST_FAILURES": "medium",
    "UNSOURCED_ASSUMPTIONS": "medium",
    # A parameter the sizing math CONSUMED but the sensitivity pass never varied. Medium, so it
    # is acceptable via accepted_warnings ("the source states no range and we accept that" is a
    # legitimate answer) -- what is not legitimate is the founder never being told.
    "SENSITIVITY_OMITS_PARAM": "medium",
    # A parameter that IS in the sensitivity pass but whose tier came from nowhere: no `confidence`
    # on the range, none in `validation_confidence`. sensitivity.py falls back to `sourced`, which
    # widens nothing, so the parameter is listed as stress-tested while carrying whatever band the
    # caller happened to write. Distinct from SENSITIVITY_OMITS_PARAM (not tested at all) because
    # the remedy differs: there, add a range; here, grade the assumption.
    "SENSITIVITY_DEFAULTED_CONFIDENCE": "medium",
    "APPROACH_MISMATCH": "medium",
    "TAM_DISCREPANCY": "medium",
    "SAM_DISCREPANCY": "medium",
    "SOM_DISCREPANCY": "medium",
    "CHECKLIST_INCOMPLETE": "medium",
    "FEW_SENSITIVITY_PARAMS": "medium",
    "NARROW_AGENT_ESTIMATE_RANGE": "medium",
    "LOW_CHECKLIST_COVERAGE": "medium",
    "DEGENERATE_NARROWING": "medium",
    "REFUTED_CLAIMS": "medium",
    "REFUTED_MISSING_REASON": "medium",
    "EXISTING_CLAIMS_SHAPE": "medium",
    "CURRENCY_MISMATCH": "medium",
    # An honest "cannot check" where the alternative is a confident wrong answer. When a money
    # input was FX-converted, a founder-stated figure or deck claim carrying no declared currency
    # cannot be compared against it: the divergence would be exactly the exchange rate, and which
    # side is in which currency is not knowable from the data. Declaring
    # founder_stated_inputs_currency / existing_claims_currency restores the real check.
    "COMPARISON_CURRENCY_UNKNOWN": "medium",
    "FOUNDER_VALUE_OVERRIDDEN": "medium",
    # A `founder_stated_inputs_period` value the normaliser does not know: the check runs on the raw
    # figure and says so, rather than silently comparing a monthly rate against an annual one.
    "FOUNDER_PERIOD_UNKNOWN": "medium",
    # HIGH: the sizing has already consumed the figure as fixed, so this cannot be accepted away
    # into silence -- and the consequence is structural: the bottom-up build replays the deck.
    "FOUNDER_STATED_MARKET_FIGURE": "high",
    # The two builds are ONE computation: the top-down industry total IS the bottom-up
    # customer_count x arpu, so their TAM agreement is arithmetic, not corroboration. Measured 1/1
    # on the run that motivated it and 0/22 on the archived corpus. Medium, not high: the numbers
    # are not wrong, the CLAIM of agreement is, and a founder whose inputs genuinely are one
    # computation can accept it once the report stops making that claim.
    "SHARED_TAM_IDENTITY": "medium",
    # A paired narrowing/capture slot carries the same number on both sides. MEDIUM under the
    # over-warn posture. August measured this class at 5/13 and CUT it, but the cut was for
    # COVERAGE -- it catches 1 of 4 overclaim instances -- not for being WRONG. When it fires the
    # statement is true: the two builds narrow by one number, not two. A true finding with partial
    # coverage is what an over-warn posture keeps loud. Expect it on ~40% of runs; medium is
    # acceptable-away, which is what makes that tolerable.
    "PAIRED_SLOT_SAME_VALUE": "medium",
    # The two narrowing chains are built from overlapping figures. MEDIUM, and the warning is not
    # an accusation: reusing one authoritative published share on both sides is legitimate
    # practice. What it STATES is that the two builds are not independent, which is
    # decision-relevant however legitimate the reuse -- and this is the detector for the defect
    # the whole change set exists to catch, so it does not whisper.
    "SHARED_FACTOR_OVERLAP": "medium",
    # The adversarial review found something and it survived the evidence bar. MEDIUM: the report
    # already carries the findings in their own section, so this is not the only way the founder
    # sees them -- it is what stops the analysis's own summary reading as unchallenged while a
    # sourced contradiction sits ten lines below it.
    "RED_TEAM_FINDINGS": "medium",
    # The assumption's own factor chain does not multiply to its value: the artifact contradicts
    # itself, the same class as deck-review's ledger `raw` disagreeing with `value`. MEDIUM, not
    # high, and the reason is measured: zero true positives on the only run we have (10.047 stated
    # as 10.0 is within tolerance), against a real and UNMEASURED false-positive surface -- a
    # `derived` percentage under a descriptive name is not in _PCT_PARAMS, so fraction factors
    # against a points-valued assumption trip it. An unclearable `high` on that evidence is a
    # promise the check cannot keep; medium is visible, blocks --strict, and is acceptable-away
    # while the field has no population. Revisit once a corpus carries factors[].
    "FACTOR_PRODUCT_MISMATCH": "medium",
    # Low severity — informational; do not block under --strict
    "MISSING_OPTIONAL_ARTIFACT": "low",
    "DECK_CLAIM_MISMATCH": "low",
    # The founder's own materials state more than one figure for the same metric. MEDIUM: the analysis is
    # valid (it compares against the stated figure) and Step 7 composes without --strict, so nothing halts.
    # In _UNACCEPTABLE_MEDIUM: it is a fact about the founder's materials, and `accepted_warnings` is
    # model-written.
    "DECK_CLAIMS_DISAGREE": "medium",
    # The SOM in the founder's materials and ours cover different periods. Not a disagreement
    # about the market -- an incomparable pair, reported as such instead of as a >5x
    # understatement, which is what comparing an 18-month plan case to a 5-year capture produced.
    "HORIZON_MISMATCH": "low",
    # The adversarial review filed something that did not carry a source, so it was set aside.
    # LOW, and it is a DISCLOSURE rather than a finding: without it, a red team that filed five
    # and kept one looks exactly like a red team that found one.
    "RED_TEAM_FINDINGS_DROPPED": "low",
    # HIGH, by the existing rule -- no equivalent reaches the founder from the section itself, and a
    # red team that never opened the deck can only have checked figures against the analysis's
    # reading of it. Measured on a live run: told the artifacts were a faithful transcription, the
    # red team opened three files, none of them a document, and repeated the transcription's misread.
    "RED_TEAM_SOURCES_UNREAD": "high",
    # A `derived` assumption with no factor chain: nothing can check the arithmetic, and nothing
    # can tell whether the two builds share the figure. LOW, and it is the one code the over-warn
    # posture does NOT reach -- every other code fires on a condition in the ANALYSIS, this one on
    # our own schema not yet being adopted. It is a migration signal, not a finding, and at medium
    # it would be the dominant medium on every run in the fleet, drowning the ones that carry
    # actual findings. Raise it once factors[] has real population.
    "UNSTRUCTURED_DERIVATION": "low",
    "PROVENANCE_UNRESOLVED": "low",
    # A conversion ran without a rate date/source. "low", for the same reason FOUNDER_TEXT_TOKEN
    # is: the currency callout already states the gap inline ("Rate as of date not stated"), so
    # the report is honest and what remains is an authoring task. Medium would block --strict,
    # and SKILL.md tells the agent to stop before the coaching step on a non-zero compose — an
    # abort on a condition it usually cannot fix, since the rate comes from the caller. The
    # nearest registered analogue, PROVENANCE_UNRESOLVED, is low for the same reason.
    "FX_UNSOURCED": "low",
    # Marker collision is informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
    # The adversarial review, read from its append-only copy (_redteam_copy). All HIGH: each says
    # the review shown is not simply the file on disk, and none may be accepted away by the thread
    # whose edit or re-run caused it.
    "REDTEAM_ALTERED": "high",
    # Inputs by reference (_view.sizing_integrity). All high: each names a figure the founder reads
    # that is no longer what it claims to be, and none may be accepted away.
    "SIZING_STALE": "high",
    "SIZING_UNRESOLVABLE": "high",
    "SIZING_ALTERED": "high",
    "RECORD_CHANGED_AFTER_REVIEW": "high",
    "UNIT_CHANGED_AFTER_REJECTION": "high",
    "SENSITIVITY_STALE": "high",
    # Medium on purpose: the self-check is judgement, so it can only be re-graded, and a high code
    # here would reward forging the stamp over re-dispatching.
    "CHECKLIST_STALE": "medium",
    "SIZING_NOT_CHECKED": "high",
    # Medium: an honest disclosure of pure calculation, allowed only when every figure is the founder's.
    "INPUTS_USER_PROVIDED": "medium",
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": "medium",
    "REVIEW_COPY_MISSING": "high",
    "RED_TEAM_SKIP_CONTRADICTED": "high",
    # MEDIUM: a review from an earlier run of this same analysis, today. A restart under a new run
    # id is how the round count above would otherwise be escaped; a genuine re-run of the whole
    # analysis is legitimate, so it is disclosed and may be accepted with a reason.
    "EARLIER_REVIEW_THIS_ANALYSIS": "medium",
    # HIGH: a figure the founder stated changed after the review saw it, and the founder did not
    # confirm the change -- measured: a stated figure rewritten to the deck's on a red-team finding's say-so.
    "FOUNDER_INPUT_REWRITTEN": "high",
    # MEDIUM because the results are valid -- the steps ran, their output reached the report -- so it
    # must not block. But it is a disclosure, not a finding the model may reason away, so it is in
    # _UNACCEPTABLE_MEDIUM: `accepted_warnings` is model-written, and a disclosure it could clear
    # is not one.
    "HANDOFF_BYPASSED": "medium",
    # Step 6d's question was owed (a high finding names a parameter) and no answer was recorded for this
    # run's findings. MEDIUM for the HANDOFF_BYPASSED reasons: Step 7 composes without --strict, so no
    # severity halts the run, and the findings themselves are valid and shown. In _UNACCEPTABLE_MEDIUM
    # because `accepted_warnings` is model-written, and the model is the one that skipped the question.
    "REVISION_NOT_OFFERED": "medium",
}

# Medium codes that `accepted_warnings` can never clear: disclosures about the run itself.
_UNACCEPTABLE_MEDIUM = {"HANDOFF_BYPASSED", "REVISION_NOT_OFFERED", "DECK_CLAIMS_DISAGREE"}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}


def _checklist_below_solid(summary: dict[str, Any]) -> bool:
    """Is this checklist unable to be called `solid`, however the rest is graded?

    THE RULE IS THE BAND, NOT A COUNT, and it took a review to see why. This was
    `fail > 6`, derived correctly but on an assumption nobody wrote down: that all 22
    criteria apply. They often do not. With 7 `not_applicable` items the applicable set is
    15, and 5 failures already put the score at 66.7% — below solid — while the absolute
    threshold said "acceptable content finding". Measured, that exact case fired the medium
    warning and contradicted the rule the split is justified by.

    Reading the band back off `score_pct` reproduces the documented 6/7 boundary exactly
    when nothing is N/A (7 of 22 caps the score at 68.2%, under 70; 6 reaches 72.7%), so
    this is the same rule stated in terms that survive N/A rather than a new one.

    `score_pct` is recomputed here rather than trusted: the producer emits it, but this
    decides a severity that cannot be accepted away, and it should not rest on an
    upstream field a hand-built artifact may omit or contradict.
    """
    fail = summary.get("fail")
    passed = summary.get("pass")
    if not isinstance(fail, int) or not isinstance(passed, int) or fail <= 0:
        return False
    applicable = passed + fail
    if applicable <= 0:
        return False
    return _thresholds.band_for(round(passed / applicable * 100, 1)) not in ("strong", "solid")


# Codes a PRODUCER may raise into `sizing.json`'s validation.warnings and have re-emitted into
# the founder-facing Warnings section. Deliberately a subset of WARNING_SEVERITY, not all of it.
#
# Forwarding anything registered would let an artifact assert codes compose OWNS. Measured: a
# `sizing.json` carrying a MISSING_ARTIFACT warning code with all six artifacts present yields
# `[HIGH] MISSING_ARTIFACT`, which is not clearable (ACCEPTIBLE_SEVERITIES is medium-only) and
# drags a FOUNDER_TEXT_TOKEN leak behind it when the message names the file. The containment is
# the point.
#
# It is still a list, so a new producer code is still stranded until added here — but the name
# and this note say so, which the previous `== "IMPLAUSIBLE_PCT_SCALE"` literal did not. That
# literal silently dropped FX_UNSOURCED for the two releases it existed.
_PRODUCER_FORWARDABLE = {"IMPLAUSIBLE_PCT_SCALE", "FX_UNSOURCED"}


REQUIRED_ARTIFACTS = [
    "inputs.json",
    "methodology.json",
    "validation.json",
    "sizing.json",
    "checklist.json",
    "sensitivity.json",
]
OPTIONAL_ARTIFACTS: list[str] = ["redteam.json"]

# What the founder is told when an optional artifact is ABSENT. Keyed by filename, but the VALUE
# must never name it: block 2's old message was f"Optional artifact missing: {name}", which puts
# an internal filename into founder-facing prose and trips the fleet's own token scan. The absence
# of a step is worth disclosing -- that is the whole reason these are warned about rather than
# skipped silently -- but what the founder needs is which check did not happen, not which file.
_OPTIONAL_ARTIFACT_ABSENCE: dict[str, str] = {
    "redteam.json": (
        "No adversarial review ran, so nothing in this report has been challenged from the "
        "outside. The figures below are the analysis's own account of itself. The report says "
        "under Adversarial Findings why the review did not run."
    ),
}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "FOUNDER_STATED_MARKET_FIGURE": "A Market Figure Was Treated As Your Own",
    "FOUNDER_PERIOD_UNKNOWN": "Period Of A Stated Figure Not Recognised",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "IMPLAUSIBLE_PCT_SCALE": "Implausible Percentage Scale",
    "CHECKLIST_FAILURES": "Checklist Failures",
    "CHECKLIST_FAILURES_CRITICAL": "Critical Checklist Failures",
    "OVERCLAIMED_VALIDATION": "Overclaimed Validation",
    "UNVALIDATED_CLAIMS": "Unvalidated Claims",
    "MISSING_OPTIONAL_ARTIFACT": "Missing Optional Artifact",
    "UNSOURCED_ASSUMPTIONS": "Unsourced Assumptions",
    "SENSITIVITY_OMITS_PARAM": "Parameter Not Stress-Tested",
    "SENSITIVITY_DEFAULTED_CONFIDENCE": "Ungraded Sensitivity Parameter",
    "APPROACH_MISMATCH": "Approach Mismatch",
    "TAM_DISCREPANCY": "TAM Discrepancy",
    "SAM_DISCREPANCY": "SAM Discrepancy",
    "SOM_DISCREPANCY": "SOM Discrepancy",
    "CHECKLIST_INCOMPLETE": "Checklist Incomplete",
    "FEW_SENSITIVITY_PARAMS": "Few Sensitivity Parameters",
    "NARROW_AGENT_ESTIMATE_RANGE": "Narrow Agent-Estimate Range",
    "LOW_CHECKLIST_COVERAGE": "Low Checklist Coverage",
    "REFUTED_CLAIMS": "Refuted Claims",
    "REFUTED_MISSING_REASON": "Refuted Claim Missing Reason",
    "DECK_CLAIM_MISMATCH": "Differs From Your Figure",
    "DECK_CLAIMS_DISAGREE": "Your Materials State Two Figures",
    "HORIZON_MISMATCH": "Different Period Than Your Materials",
    "SHARED_TAM_IDENTITY": "Both Approaches Share One Total",
    "PAIRED_SLOT_SAME_VALUE": "Same Value On Both Sides",
    "SHARED_FACTOR_OVERLAP": "Both Approaches Use The Same Figures",
    "RED_TEAM_FINDINGS": "Outside Evidence Contradicts This Analysis",
    "RED_TEAM_FINDINGS_DROPPED": "Some Challenges Were Set Aside",
    "RED_TEAM_SOURCES_UNREAD": "Documents The Review Did Not Open",
    "FACTOR_PRODUCT_MISMATCH": "Derivation Does Not Reproduce Its Value",
    "UNSTRUCTURED_DERIVATION": "Derivation Not Itemized",
    "PROVENANCE_UNRESOLVED": "Provenance Unresolved",
    "FX_UNSOURCED": "Exchange Rate Not Sourced",
    "EXISTING_CLAIMS_SHAPE": "Existing Claims Shape",
    "MARKER_COLLISION": "Marker Collision",
    "REDTEAM_ALTERED": "The Outside Review Was Changed After It Was Written",
    "SIZING_STALE": "The Sizing Was Calculated From Earlier Research",
    "SIZING_UNRESOLVABLE": "A Source Figure Is No Longer In The Research",
    "SIZING_ALTERED": "The Saved Calculation Was Changed After It Was Calculated",
    "RECORD_CHANGED_AFTER_REVIEW": "Research Changed After The Outside Review",
    "UNIT_CHANGED_AFTER_REJECTION": "A Figure Was Relabelled After It Was Refused",
    "SENSITIVITY_STALE": "The Sensitivity Table Is From A Different Sizing",
    "CHECKLIST_STALE": "The Self-Check Is From A Different Sizing",
    "SIZING_NOT_CHECKED": "The Figures Were Not Taken From The Research",
    "INPUTS_USER_PROVIDED": "These Are Your Figures, Unchecked",
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": "The Analysis Changed Between Reviews",
    "REVIEW_COPY_MISSING": "The Outside Review Cannot Be Shown Unchanged",
    "RED_TEAM_SKIP_CONTRADICTED": "A Review Ran That Was Recorded As Skipped",
    "EARLIER_REVIEW_THIS_ANALYSIS": "An Earlier Run Also Reviewed This Analysis",
    "FOUNDER_INPUT_REWRITTEN": "A Figure You Gave Was Changed Without Your Confirmation",
    "HANDOFF_BYPASSED": "Some Steps Were Not Checked",
    "REVISION_NOT_OFFERED": "You Were Not Offered A Revision",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


def _fmt_number(value: Any) -> str:
    """Format a numeric value for display. One owner: `_params.fmt_number`."""
    return _params.fmt_number(value)


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


def _fail_compose(result: dict[str, Any], report_path: str | None) -> NoReturn:
    """Refuse to compose: diagnostic to stdout, a line to stderr, nothing written, exit non-zero.

    The fleet's producer contract, applied to the one script that previously had no refusal path.
    All three properties matter and each has been got wrong somewhere before: the diagnostic goes
    to STDOUT so a caller can read it; `report.md` and `-o` are left UNTOUCHED, because a stub
    over a canonical artifact is worse than writing nothing and destroys the prior good copy; and
    the non-zero exit is what makes SKILL.md's documented "stop and report, do not proceed to
    Step 8" branch reachable at all.
    """
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified refusal"]
    print(f"Error: report not composed: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if report_path:
        print(f"Error: {os.path.abspath(report_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


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


def _stated_as(field: str, stated: dict[str, Any]) -> str:
    """A founder figure as they stated it: "$157 per month", or "not stated"."""
    value = stated.get("founder_stated_inputs")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "not stated"
    currency = stated.get("founder_stated_inputs_currency")
    amount = f"{value:,.2f}".rstrip("0").rstrip(".")
    shown = f"${amount}" if currency in (None, "USD") else f"{currency} {amount}"
    period = stated.get("founder_stated_inputs_period")
    return shown + (f" per {period}" if isinstance(period, str) and period.strip() else "")


def _input_shown(name: str, *where: dict[str, Any]) -> str:
    """A sizing input as the first of `where` holding it records it, printed by its unit, or "?"."""
    for inputs in where:
        if name in inputs:
            return _params.format_value(_params.unit_of(name), inputs[name], _view._CURRENCY)
    return "?"


def _md_safe(text: str) -> str:
    """Escape text for safe markdown table cell interpolation."""
    return text.replace("|", "\\|").replace("\n", " ")


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


def _revision_not_offered(dir_path: str, run_id: str | None, redteam: Any, *, rounds: int) -> list[str]:
    """The parameters whose high findings asked Step 6d's question when no answer was recorded; [] when
    nothing is owed.

    A second review round is the answer "revise" by construction: that round exists only because the
    founder chose it. A missing `handoff/<run_id>/` is not silence: the answer record lives there, so
    deleting the dir can only add this warning, never remove it.

    RESIDUAL (pinned in tests): the record is written by a script the model runs, so a pass proves the
    question step ran the recorder, not that the question was put to the founder.
    """
    if not run_id or rounds >= 2:
        return []
    parameters = _revision_answer.qualifying_parameters(redteam)
    if not parameters or _revision_answer.recorded(dir_path, run_id, parameters):
        return []
    return parameters


def _handoff_bypassed(dir_path: str, run_id: str | None, artifacts: dict[str, Any]) -> list[str]:
    """Which sub-agent steps this report's artifacts came from have no gated hand-off in this run.

    No record means the step's output reached its producer without the gate: through the
    message-channel fallback, or with the gate skipped. The founder text says only that it was not
    checked, which is true of both.

    Built from the artifacts actually present, never from what SKILL.md says should run: a sizing block
    means its sizing dispatch ran; a sensitivity, checklist or review artifact means that step ran.

    REVISION ROUNDS. Step 6d re-runs the sensitivity test, the checklist and the review into
    `handoff/<run_id>/r2/`. When that dir exists those three must be gated THERE -- round 1's record
    would otherwise vouch for a round-2 step that degraded. A sizing is re-run with `--replay` (no
    dispatch) or re-dispatched into r2, so either round's record satisfies it.

    A missing `handoff/<run_id>/` is NOT silence: with no dir there are no gate records, so every step
    the artifacts show ran is reported unchecked. Deleting the dir can only add this warning. A run
    that dispatched no sub-agent has none of these artifacts, so nothing is required of it.

    RESIDUAL (pinned in tests): a pass proves a gated hand-off exists and still matches its record --
    not that the producer consumed it. A step gated once and then degraded on a re-dispatch within the
    same round passes. See `_handoff_audit.py`.
    """
    audit = _handoff_audit()
    if audit is None or not run_id:
        return []
    run_dir = os.path.join(dir_path, "handoff", run_id)
    revised = os.path.isdir(os.path.join(run_dir, "r2"))

    def rerun(stem: str) -> list[str]:
        return [f"r2/{stem}"] if revised else [stem]

    def either(stem: str) -> list[str]:
        return [f"r2/{stem}", stem]

    requirements: list[tuple[str, list[str]]] = []
    sizing = artifacts.get("sizing.json")
    if isinstance(sizing, dict):
        if isinstance(sizing.get("top_down"), dict):
            requirements.append(("the top-down sizing", either("top_down_output.json")))
        if isinstance(sizing.get("bottom_up"), dict):
            requirements.append(("the bottom-up sizing", either("bottom_up_output.json")))
    if isinstance(artifacts.get("sensitivity.json"), dict):
        requirements.append(("the sensitivity test", rerun("sensitivity_output.json")))
    if isinstance(artifacts.get("checklist.json"), dict):
        requirements.append(("the quality checklist", rerun("checklist_output.json")))
    if isinstance(artifacts.get("redteam.json"), dict):
        requirements.append(("the outside review", rerun("redteam_output.json")))
    labels: list[str] = audit.bypassed(run_dir, requirements)
    return labels


def _warn(code: str, message: str) -> dict[str, str]:
    """Create a warning dict with code, message, and severity from canonical map."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


def _collect_sizing_inputs(sizing: dict[str, Any] | None) -> dict[str, float]:
    """Flatten every quantitative parameter the sizing math actually consumed.

    Walks both approaches x tam/sam/som and keeps only QUANTITATIVE_PARAMS keys,
    so derived intermediates (``serviceable_customers``, ``target_customers``) are
    ignored. A parameter appearing under several figures carries the same value,
    so last-write-wins is harmless.
    """
    used: dict[str, float] = {}
    if not isinstance(sizing, dict):
        return used
    for approach_key in ("top_down", "bottom_up"):
        approach = _as_dict(sizing.get(approach_key))
        for figure_key in ("tam", "sam", "som"):
            figure_inputs = _as_dict(_as_dict(approach.get(figure_key)).get("inputs"))
            for name, value in figure_inputs.items():
                if name in QUANTITATIVE_PARAMS and isinstance(value, (int, float)) and not isinstance(value, bool):
                    used[name] = float(value)
    return used


# The one sizing parameter that is a fact about the founder's OWN business: what they charge or
# collect per customer. Every other parameter -- a population, an industry total, a share, a
# capture rate -- is a figure about the MARKET, and a deck that states one is making a claim.
_FOUNDER_FACT_PARAMS: frozenset[str] = frozenset({"arpu"})


def _check_founder_stated_are_facts(inputs: dict[str, Any] | None) -> list[dict[str, str]]:
    """A market figure recorded as founder-stated is a claim protected from the test it needs.

    Measured on a live investor run (the analyst's own words in the critique): the deck's
    population and capture figures went into `founder_stated_inputs`, the value-fidelity rule then
    forbade the bottom-up build from departing from them, and the "independent" build replayed the
    deck's math until a re-dispatch. `founder_stated_inputs` exists so a researched figure cannot
    silently replace what the founder KNOWS; a figure about the market is not something they know,
    it is something they claim, and it belongs in `existing_claims` where it is compared, not fixed.
    """
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    market = sorted(k for k in stated if k in PARAM_LABELS and k not in _FOUNDER_FACT_PARAMS)
    if not market:
        return []
    names = ", ".join(_humanize_param(k) for k in market)
    noun = "figure" if len(market) == 1 else "figures"
    return [
        _warn(
            "FOUNDER_STATED_MARKET_FIGURE",
            f"{names}: {noun} about the market from your materials, recorded as if it were a fact about "
            f"your own business. The sizing used it unchanged, so any build that consumes it restates "
            f"your claim rather than testing it. A market figure is a claim; it belongs beside the "
            f"deck's other claims, where the analysis compares against it.",
        )
    ]


# The period a founder-stated money figure is quoted per, to the analysis's annual basis. One table,
# owned by _params: the resolver normalises with it too, and two copies would drift.
_PERIOD_TO_YEAR: dict[str, float] = _params.PERIOD_TO_YEAR


def _check_founder_value_fidelity(
    inputs: dict[str, Any] | None,
    sizing: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Warn when a founder-stated input is NOT what the math was computed from.

    A researched figure may be offered as a cross-check; it must never be silently
    substituted for a value the founder supplied. The founder recognises their own
    numbers, and a headline figure derived from a number they never gave reads as
    an arithmetic error — discrediting the parts of the analysis that are right.

    Detection is opt-in on ``inputs.founder_stated_inputs`` being populated: when the
    founder stated nothing quantitative there is nothing to preserve. Tolerance is
    0.5% relative, so a unit normalization ("18k" -> 18000) does not trip it while a
    genuine substitution (18,000 -> 16,601) does.
    """
    warnings: list[dict[str, str]] = []
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    if not stated:
        return warnings
    stamped = _view.stamped_provenance(sizing)
    if stamped is not None and all(_as_dict(v).get("kind") != "not_checked" for v in stamped.values()):
        # A stamped sizing says exactly which figures it used, so this is not a numeric comparison: the
        # founder's figure was used if the input's references reach it, including through a derivation.
        for name in sorted(stated):
            entry = _as_dict(stamped.get(name))
            if name not in _provenance.FOUNDER_FACT_PARAMS or not entry:
                continue
            if f"founder:{name}" in _as_list(entry.get("entries")):
                continue
            warnings.append(
                _warn(
                    "FOUNDER_VALUE_OVERRIDDEN",
                    f"You stated your {_humanize_param(name)}, but the sizing used a different figure "
                    f"({_params.format_value(_params.PARAM_UNITS[name], entry.get('value_consumed'), _view._CURRENCY)} "
                    f"per year). A researched figure may be shown as a cross-check; it must not replace yours "
                    f"without your say. Before the outside review, re-run the sizing on your figure or ask you "
                    f"which to use; after it, that is the one revision you approve at Step 6d.",
                )
            )
        return warnings
    used = _collect_sizing_inputs(sizing)
    all_conversions = list(_fx_conversions(sizing).values())
    target_ccy = _as_dict(sizing).get("currency")
    declared_ccy = _as_dict(inputs).get("founder_stated_inputs_currency")
    periods = _as_dict(_as_dict(inputs).get("founder_stated_inputs_period"))
    for name, stated_value in sorted(stated.items()):
        if name not in QUANTITATIVE_PARAMS:
            continue
        if not isinstance(stated_value, (int, float)) or isinstance(stated_value, bool):
            continue
        if name not in used:
            continue
        # Bring the founder's figure onto the analysis's PERIOD before comparing. MEASURED on a live
        # run: the founder stated a price per MONTH, the sizing consumed the annual figure (x12), this
        # check called the correct x12 an override at 0.5% tolerance, and its remedy text told the
        # constructor to "update inputs.founder_stated_inputs" -- which it did, rewriting the
        # founder's stated figure to match the model's, with no founder in the loop. A stated period
        # is normalised here; an unknown one is named rather than guessed.
        per_period = float(stated_value)
        period = periods.get(name)
        if period is not None:
            factor = _PERIOD_TO_YEAR.get(str(period).strip().lower())
            if factor is None:
                warnings.append(
                    _warn(
                        "FOUNDER_PERIOD_UNKNOWN",
                        f"founder_stated_inputs_period.{name} is {period!r}; expected one of "
                        f"{', '.join(sorted(_PERIOD_TO_YEAR))}. The figure was compared as annual.",
                    )
                )
            else:
                per_period = per_period * factor
        # Bring the founder's figure into the analysis currency before comparing. Without this a
        # converted money input diverges from the founder's own number by exactly the FX rate, so
        # FOUNDER_VALUE_OVERRIDDEN would fire on every correctly-converted run.
        comparable, blocked = _to_analysis_currency(per_period, declared_ccy, target_ccy, all_conversions)
        if blocked is not None:
            warnings.append(
                _warn(
                    "COMPARISON_CURRENCY_UNKNOWN",
                    f"Could not verify the figure you gave for {name} against the one the "
                    f"calculation used: {blocked}. State which currency your figure is in and "
                    f"this check can run.",
                )
            )
            continue
        assert comparable is not None  # _to_analysis_currency returns exactly one of the two
        stated_f = float(comparable)
        used_f = used[name]
        denom = abs(stated_f) if stated_f else 1.0
        if abs(used_f - stated_f) / denom <= 0.005:
            continue
        # Report what the founder actually said, not the normalized comparand — the founder has to
        # recognise their own number in this sentence for it to mean anything.
        said_f = float(stated_value)
        said = f"{said_f:,.10g}" + (f" per {period}" if period is not None else "")
        warnings.append(
            _warn(
                "FOUNDER_VALUE_OVERRIDDEN",
                (
                    f"The founder stated {name} = {said}, but the sizing was computed from "
                    f"{used_f:,.10g}. A researched figure may be presented as a cross-check; it must not "
                    f"replace a founder-stated input. Before the outside review (Step 6c), recompute from "
                    f"the founder's figure or put the discrepancy to the founder as a question; after it, "
                    f"ask at Step 6d, because changing an input the review has seen is the one revision "
                    f"the founder approves. Do not edit founder_stated_inputs to "
                    f"match the sizing: a figure the founder did not confirm is not founder-stated. "
                    f"If the founder's figure is per month or per quarter, say so in "
                    f"founder_stated_inputs_period and this check normalises it."
                ),
            )
        )
    return warnings


def validate_artifacts(
    artifacts: dict[str, dict[str, Any] | None], dir_path: str | None = None
) -> list[dict[str, str]]:
    """Run all 17 validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    inputs = artifacts.get("inputs.json")
    methodology = artifacts.get("methodology.json")
    validation = artifacts.get("validation.json")
    sizing = artifacts.get("sizing.json")
    sensitivity = artifacts.get("sensitivity.json")
    checklist = artifacts.get("checklist.json")

    # SIZING_INVALID — sizing.json exists but carries no figures, because market_sizing.py
    # rejected its input. Historically this was the quietest failure in the skill: the producer
    # exited 0 with an `{"ok":true}` receipt and wrote a `{"validation": {"status": "invalid"}}`
    # stub over the canonical artifact, so the only downstream signal was a MEDIUM
    # APPROACH_MISMATCH whose wording ("methodology says top_down but sizing.json is missing
    # top_down") pointed at the wrong cause. market_sizing.py now exits non-zero and refuses to
    # write, so a stub here means an OLD artifact or a hand-edited one — either way the report
    # must not be presented.
    if _usable(sizing):
        _sz_status = _as_dict(sizing.get("validation")).get("status")
        _has_figures = any(sizing.get(k) is not None for k in ("top_down", "bottom_up"))
        if _sz_status == "invalid" or not _has_figures:
            _errs = "; ".join(str(e) for e in _as_list(_as_dict(sizing.get("validation")).get("errors")))
            warnings.append(
                _warn(
                    "SIZING_INVALID",
                    "The market-size calculation did not complete, so this report has no "
                    "TAM/SAM/SOM figures"
                    + (f" ({_errs})" if _errs else "")
                    + ". Do not present it: correct the inputs and run the sizing step again.",
                )
            )

    # ARTIFACT_INVALID — the same check for the other two producer artifacts. Their producers now
    # refuse and preserve, so reaching here means a stale or hand-edited file.
    for _name, _art, _label in (
        ("sensitivity.json", artifacts.get("sensitivity.json"), "the sensitivity analysis"),
        ("checklist.json", artifacts.get("checklist.json"), "the quality checklist"),
    ):
        if not _usable(_art):
            continue
        if _as_dict(_art.get("validation")).get("status") != "invalid":
            continue
        _errs = "; ".join(str(e) for e in _as_list(_as_dict(_art.get("validation")).get("errors")))
        warnings.append(
            _warn(
                "ARTIFACT_INVALID",
                f"{_label.capitalize()} did not complete, so this report is missing part of its "
                f"analysis" + (f" ({_errs})" if _errs else "") + ". Do not present it: correct the "
                "inputs and run that step again.",
            )
        )

    # CURRENCY_MISMATCH — inputs.json records the founder's currency at intake;
    # sizing.json records what the producer was actually told. If they disagree,
    # one of the two figures on the page is mislabelled and we cannot know which,
    # so say so instead of silently picking a winner.
    if _usable(inputs) and _usable(sizing):
        in_cur = inputs.get("currency")
        sz_cur = sizing.get("currency")
        if (
            isinstance(in_cur, str)
            and in_cur.strip()
            and isinstance(sz_cur, str)
            and sz_cur.strip()
            and in_cur.strip().upper() != sz_cur.strip().upper()
        ):
            warnings.append(
                _warn(
                    "CURRENCY_MISMATCH",
                    (
                        f"The recorded inputs state currency {in_cur.strip().upper()} but the sizing was computed "
                        f"as {sz_cur.strip().upper()}. Money figures in this report are labelled "
                        f"{in_cur.strip().upper()}; if the sizing inputs were actually in "
                        f"{sz_cur.strip().upper()}, every TAM/SAM/SOM figure carries the wrong unit. "
                        "Setting the currency does not convert anything — re-run the sizing step with the correct "
                        "--currency rather than converting the output by hand."
                    ),
                )
            )

    warnings.extend(_check_founder_value_fidelity(inputs, sizing))
    warnings.extend(_check_founder_stated_are_facts(inputs))

    # 0. IMPLAUSIBLE_PCT_SCALE — surface sizing.json's input-plausibility warnings (WB-1:
    # the fractional-% guard, e.g. 0.4 entered where 40 was meant → silent ~100x error).
    # These are recorded in sizing.json's validation.warnings; re-emit so the founder sees
    # them in the report's Warnings section rather than only on the script's stderr.
    if _usable(sizing):
        for w in _as_list((sizing.get("validation") or {}).get("warnings")):
            if isinstance(w, dict) and w.get("code") in _PRODUCER_FORWARDABLE:
                code = str(w["code"])
                fallback = f"{_humanize_warning(code)} reported by the sizing step"
                warnings.append(_warn(code, str(w.get("message") or fallback)))

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
            warnings.append(
                _warn(
                    "MISSING_OPTIONAL_ARTIFACT",
                    _OPTIONAL_ARTIFACT_ABSENCE.get(name, "An optional step of this analysis did not run."),
                )
            )

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
        # "Expected" is the id the review gate resolves for (`_redteam_core.primary_run_id`), so the
        # leftover is what gets named. Taking the first artifact's id named the fresh files as stale
        # whenever the leftover was listed first, and re-running them could never clear it.
        primary_rid = (
            _redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)
            if dir_path
            else _redteam_copy.primary_run_id(artifacts.get(n) for n in REQUIRED_ARTIFACTS)
        ) or next(iter(run_ids.values()))
        for name, rid in run_ids.items():
            if rid != primary_rid:
                warnings.append(
                    _warn(
                        "STALE_ARTIFACT",
                        f"{name} has run_id '{rid}' but expected '{primary_rid}'",
                    )
                )

    # 3. UNSOURCED_ASSUMPTIONS — agent_estimate assumptions not in sensitivity
    if _usable(sizing):
        # The inputs the calculator stamped as estimates. A research entry that merely shares an
        # input's name says nothing about what the sizing used.
        agent_estimate_names: set[str] = {
            p for p, g in _view.input_grades(sizing, validation).items() if g["category"] == "agent_estimate"
        }

        sensitivity_params: set[str] = set()
        if _usable(sensitivity):
            for scenario in _as_list(sensitivity.get("scenarios")):
                if isinstance(scenario, dict) and scenario.get("confidence") == "agent_estimate":
                    sensitivity_params.add(scenario.get("parameter", ""))

        unsourced = agent_estimate_names - sensitivity_params
        if unsourced:
            warnings.append(
                _warn(
                    "UNSOURCED_ASSUMPTIONS",
                    "Agent-estimate assumptions not stress-tested in sensitivity: "
                    # Joined, not interpolated: an f-string around the list comprehension printed a
                    # Python list repr -- quotes and brackets -- into a sentence a founder reads.
                    + ", ".join(_humanize_param(p) for p in sorted(unsourced)),
                )
            )

    # 3b. SENSITIVITY_OMITS_PARAM — a consumed parameter the sensitivity pass never varied.
    #
    # NOTHING could see this before. UNSOURCED_ASSUMPTIONS (above) checks only assumptions whose
    # category is `agent_estimate`; FEW_SENSITIVITY_PARAMS fires below 3 scenarios. So a `sourced`
    # parameter dropped from `ranges` entirely was invisible in every output -- measured on a real
    # run, `arpu` (the single most commercially uncertain input in that model, and the only one
    # the analyst had flagged as unconfirmable against any published price list) was omitted, and
    # the delivered report carried ten warnings, none about it.
    #
    # The dispatch contract permits omission for a `sourced` figure whose source states no range.
    # That exemption is honoured ONLY at `confidence: high`: the measured case was `sourced` with
    # `confidence: medium`, i.e. corroborated-but-imprecise, which is exactly the input a buyer
    # pushes hardest on. Note the tier system reads `category` and never `confidence`, which is
    # how a medium-confidence assumption reached zero stress-testing in the first place.
    #
    # Ground truth for "consumed" is sizing.json's per-figure `inputs` — the values the math
    # actually used — not inputs.json, which may carry figures no approach consumed.
    # SCOPED TO THE APPROACH THE SENSITIVITY PASS ACTUALLY RAN. A `both` sizing paired with a
    # single-approach sensitivity run is legitimate -- `sensitivity.py` itself drops the other
    # approach's parameters as irrelevant -- so comparing against every consumed parameter would
    # flag three untestable ones on every such run. Only the blocks the sensitivity pass covered
    # are eligible.
    if _usable(sizing) and _usable(sensitivity):
        sens_approach = str(sensitivity.get("approach") or "both")
        eligible_blocks = ("top_down", "bottom_up") if sens_approach == "both" else (sens_approach,)
        consumed: set[str] = set()
        for approach_key in eligible_blocks:
            block = sizing.get(approach_key)
            if not isinstance(block, dict):
                continue
            for figure in block.values():
                if isinstance(figure, dict) and isinstance(figure.get("inputs"), dict):
                    consumed |= {k for k in figure["inputs"] if k in QUANTITATIVE_PARAMS}

        varied = {
            s.get("parameter")
            for s in _as_list(sensitivity.get("scenarios"))
            if isinstance(s, dict) and s.get("parameter")
        }

        grades: dict[str, dict[str, Any]] = _view.input_grades(sizing, validation)

        for param in sorted(consumed - varied):
            grade = grades.get(param, {})
            category = grade.get("category")
            confidence = grade.get("confidence")
            if category == "sourced" and confidence == "high":
                continue  # a high-confidence sourced figure whose source states no range
            # The founder's own figure grades as sourced for the table, but it was never checked
            # against research; saying "graded sourced" told the founder it had been.
            stamped_category = _as_dict(_as_dict(_view.stamped_provenance(sizing)).get(param)).get("category")
            detail = "your own figure" if stamped_category == "founder_stated" else f"graded {category or 'ungraded'}"
            if confidence:
                detail += f"/{confidence} confidence"
            warnings.append(
                _warn(
                    "SENSITIVITY_OMITS_PARAM",
                    f"{_humanize_param(param)} is used by the sizing math but was never "
                    f"stress-tested ({detail}) — it carries no range in the sensitivity analysis",
                )
            )

    # 3c. SENSITIVITY_DEFAULTED_CONFIDENCE — a scenario whose tier came from neither source.
    #
    # `sensitivity.py` stamps `confidence_source` precisely so this is visible: "no widening
    # happened" and "no widening was called for" were the same artifact before. A `default` source
    # means nothing graded the parameter and the fallback tier (`sourced`) widens nothing, so the
    # founder sees it listed among the stress-tested parameters at a band the caller chose freely.
    # Reported, never silently corrected: the fix is to grade the assumption, which only the
    # validation step can do.
    if _usable(sensitivity):
        ungraded = sorted(
            {
                str(s.get("parameter"))
                for s in _as_list(sensitivity.get("scenarios"))
                if isinstance(s, dict) and s.get("confidence_source") == "default" and s.get("parameter")
            }
        )
        if ungraded:
            warnings.append(
                _warn(
                    "SENSITIVITY_DEFAULTED_CONFIDENCE",
                    f"{', '.join(_humanize_param(p) for p in ungraded)} carries no confidence grade in "
                    "either the range or validation — the fallback tier widens nothing, so the range "
                    "shown is whatever was supplied rather than one the grade justifies",
                )
            )

    # 4. UNVALIDATED_CLAIMS
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if isinstance(fig, dict) and fig.get("status") == "unsupported":
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
            if isinstance(fig, dict) and fig.get("status") == "refuted":
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
                        "Methodology says 'both' but the sizing is missing the top-down or the bottom-up build",
                    )
                )
        elif approach in ("top_down", "bottom_up") and approach not in sizing:
            warnings.append(
                _warn(
                    "APPROACH_MISMATCH",
                    f"Methodology says '{approach}' but the sizing has no {approach.replace('_', '-')} build",
                )
            )

    # 8. TAM_DISCREPANCY / SAM_DISCREPANCY / SOM_DISCREPANCY — same >30% gate extended
    # to SAM/SOM (previously only TAM was checked; an order-of-magnitude SAM/SOM gap
    # between top-down and bottom-up could be presented as equally defensible).
    if _usable(sizing):
        comparison = _as_dict(sizing.get("comparison"))
    # DEGENERATE_NARROWING — SAM that does not narrow TAM.
    #
    # Deliberately deterministic rather than agent-judged. The 22-item self-check has an item for
    # exactly this ("TAM > SAM > SOM"), but it is scored by the sub-agent and there is NO code check
    # anywhere; measured, a run returned `pass` while its own evidence text read "SAM equals TAM
    # exactly ... the bottom-up SAM isn't doing independent work as a constraint".
    #
    # Only the sam == tam limb is implemented. `som == sam` has zero confirmed instances across the
    # corpus, and building a symmetric guess for an unobserved case is how a previous plan shipped a
    # detector for a class that never occurs.
    if _usable(sizing):
        for _approach in ("top_down", "bottom_up"):
            _block = _as_dict(sizing.get(_approach))
            _tam = _as_dict(_block.get("tam")).get("value")
            _sam = _as_dict(_block.get("sam")).get("value")
            if not isinstance(_tam, (int, float)) or not isinstance(_sam, (int, float)):
                continue
            if _tam and math.isclose(float(_tam), float(_sam), rel_tol=1e-9):
                _label = "Top-down" if _approach == "top_down" else "Bottom-up"
                warnings.append(
                    _warn(
                        "DEGENERATE_NARROWING",
                        f"{_label} SAM equals TAM ({_fmt_usd(float(_sam))}) — the serviceable "
                        "market applies no narrowing, so it carries no filtering work. State which "
                        "customers are excluded and why, or drop the distinction.",
                    )
                )

        if comparison.get("tam_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "TAM_DISCREPANCY",
                    _gap_message(comparison, "tam"),
                )
            )
        if comparison.get("sam_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "SAM_DISCREPANCY",
                    _gap_message(comparison, "sam"),
                )
            )
        if comparison.get("som_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "SOM_DISCREPANCY",
                    _gap_message(comparison, "som"),
                )
            )

        # 8b. SHARED_TAM_IDENTITY / PAIRED_SLOT_SAME_VALUE — the discrepancy checks above fire on
        # the two builds DISAGREEING. These fire on the opposite and more dangerous case: they
        # agree because they are not independent. Each item names its own code.
        for shared in _shared_input_values(sizing, validation):
            warnings.append(_warn(str(shared["code"]), str(shared["detail"])))

    # 9. CHECKLIST_FAILURES / CHECKLIST_FAILURES_CRITICAL
    #
    # THE TRIGGER READS THE COUNT, NOT THE BAND. It used to test
    # `overall_status == "fail"`, a value the 4-band vocabulary no longer contains — left
    # alone this became dead code and the warning stopped firing with nothing to say so.
    # The count is what the warning is about anyway; the band was only ever a proxy for it.
    #
    # MUTUALLY EXCLUSIVE. Both firing would show a founder the same failures twice under two
    # severities, and the acceptance rules for the two are opposite.
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        failed = _as_list(summary.get("failed_items"))
        fail_count = summary.get("fail")
        if not isinstance(fail_count, int):
            fail_count = len(failed)
        # Joined as prose, never interpolated as a list. `{failed_ids}` renders a Python repr --
        # brackets and single quotes -- on the line that tells a founder what failed, and the
        # founder-text scan cannot see it because the ids themselves are already humanized.
        # Found by reading a replayed report by eye; no assertion about this warning had ever
        # matched on its SHAPE.
        failed_names = ", ".join(str(f.get("id", "?")) for f in failed)
        if _checklist_below_solid(summary):
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES_CRITICAL",
                    f"Checklist has {fail_count} failures: {failed_names} — that cannot score as "
                    f"solid however the rest is graded",
                )
            )
        elif fail_count > 0:
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES",
                    f"Checklist has {fail_count} failures: {failed_names}",
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
            if isinstance(scenario, dict) and scenario.get("confidence") == "agent_estimate":
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
            if isinstance(fig, dict) and fig.get("status") == "validated" and fig.get("source_count", 0) < 2:
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                warnings.append(
                    _warn(
                        "OVERCLAIMED_VALIDATION",
                        f"Figure '{fig_display}' marked validated but source_count={fig.get('source_count')}",
                    )
                )

    # 15. DECK_CLAIM_MISMATCH — deck claim differs from calculated by >50%
    #
    # FX-aware: every tam/sam/som is derived from the money inputs, so if ANY of them was
    # converted the calculated figures are in the analysis currency while the deck's claim is in
    # whatever the deck used. Comparing across that gap yields a delta of the exchange rate's
    # magnitude (~+272% at USD:ILS=3.72) on a perfectly correct analysis — so gate on a declared
    # claim currency and say "cannot compare" when there isn't one.
    inputs_art = artifacts.get("inputs.json")
    if _usable(sizing) and _usable(inputs_art):
        existing_claims = _as_dict(inputs_art.get("existing_claims"))
        _claim_convs = list(_fx_conversions(sizing).values())
        _claim_ccy = inputs_art.get("existing_claims_currency")
        _horizon_reported: set[str] = set()
        for approach_key in ("top_down", "bottom_up"):
            approach_data = sizing.get(approach_key)
            if approach_data is None:
                continue
            for metric in ("tam", "sam", "som"):
                m = _as_dict(approach_data.get(metric))
                val = m.get("value", 0)
                claim = existing_claims.get(metric)
                if claim is not None and isinstance(claim, (int, float)) and not isinstance(claim, bool):
                    # Different periods are not comparable, so say that instead of computing a
                    # delta between them. Deduplicated on (code, metric): this loop runs once per
                    # APPROACH, and the message names no approach, so a second copy would put the
                    # identical sentence twice under `## Warnings`.
                    _hm = _horizon_mismatch(inputs_art, metric)
                    if _hm is not None:
                        if metric not in _horizon_reported:
                            _horizon_reported.add(metric)
                            warnings.append(
                                _warn(
                                    "HORIZON_MISMATCH",
                                    f"The {metric.upper()} you gave covers {_hm[0]} months "
                                    f"and ours covers {_hm[1]}, so the two are not compared. Put "
                                    f"both on the same period and this cross-check can run.",
                                )
                            )
                        continue
                    comparable, blocked = _to_analysis_currency(
                        float(claim), _claim_ccy, sizing.get("currency"), _claim_convs
                    )
                    if blocked is not None:
                        warnings.append(
                            _warn(
                                "COMPARISON_CURRENCY_UNKNOWN",
                                f"Could not cross-check the {metric.upper()} you stated against the "
                                f"calculated one: {blocked}. State which currency your figure is in "
                                f"and this check can run.",
                            )
                        )
                        continue
                    claim = comparable
                # A stated RANGE: inside it is not a disagreement, outside it is measured to the
                # nearest bound, and the message quotes the range the founder gave.
                claim_high: float | None = None
                if claim is not None:
                    _raw_high = _claim_high(inputs_art, metric)
                    if _raw_high is not None:
                        claim_high, _hb = _to_analysis_currency(
                            float(_raw_high), _claim_ccy, sizing.get("currency"), _claim_convs
                        )
                delta = (
                    _range_delta(float(val), float(claim), claim_high)[0]
                    if isinstance(claim, (int, float)) and not isinstance(claim, bool)
                    else _compute_delta(float(val), claim)
                )
                if delta is not None and abs(delta) > DECK_MISMATCH_PCT and claim is not None:
                    # Code stays DECK_CLAIM_MISMATCH (stable API, asserted elsewhere). The wording
                    # does not say where the claim came from: nothing records that per figure, and
                    # "deck claim" on a TAM the founder typed in chat is a false statement to them.
                    _src = "the figure you stated"
                    _lbl = "you stated"
                    # Pass the currency EXPLICITLY. Validation runs ~60 lines before
                    # `_set_currency()`, so the module default ("USD") is still in force here and
                    # both figures rendered with a bare "$" on an ILS analysis -- in the same
                    # report whose table correctly said ILS. Passing the code beats reordering
                    # compose(), which would mean hoisting three artifact extractions.
                    _ccy = _as_dict(sizing).get("currency")
                    warnings.append(
                        _warn(
                            "DECK_CLAIM_MISMATCH",
                            f"{metric.upper()} differs from {_src} by {_params.fmt_delta(delta, signed=True)} "
                            f"({_lbl}: {claim_display(float(claim), claim_high, _ccy)}, "
                            f"calculated: {_fmt_usd(val, _ccy)})",
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
                    "Quantitative inputs without a matching assumption in the source validation: " + ", ".join(parts),
                )
            )

    # 17. EXISTING_CLAIMS_SHAPE — non-canonical keys silently bypass reconciliation
    # at compose_report.py:282 (_compute_provenance) and the DECK_CLAIM_MISMATCH check above.
    inputs_art = artifacts.get("inputs.json")
    if _usable(inputs_art):
        raw = inputs_art.get("existing_claims")
        if isinstance(raw, dict):
            canonical = {"tam", "sam", "som"}
            unexpected = sorted(k for k in raw if k not in canonical)
            if unexpected:
                warnings.append(
                    _warn(
                        "EXISTING_CLAIMS_SHAPE",
                        f"inputs.existing_claims contains non-canonical keys: "
                        f"{', '.join(unexpected)}. Expected only lowercase "
                        f"'tam', 'sam', 'som' (flat). Non-canonical keys are "
                        f"silently ignored by reconciliation. For deck claims "
                        f"that don't fit the flat shape (regional sub-SAMs, "
                        f"time-anchored figures, alternative TAM frames), use "
                        f"the adjacent 'existing_claims_detail' field — it is "
                        f"rendered narratively in the report.",
                    )
                )
        elif raw is not None and raw != {}:
            warnings.append(
                _warn(
                    "EXISTING_CLAIMS_SHAPE",
                    f"inputs.existing_claims must be a dict of {{tam, sam, som}}; got {type(raw).__name__}.",
                )
            )
        # The upper bound of a stated range. One that cannot form a range with its low end is
        # ignored by every comparison (_claim_high), and said so here rather than dropped in silence.
        raw_high = inputs_art.get("existing_claims_high")
        if isinstance(raw_high, dict):
            for metric, high in sorted(raw_high.items()):
                if metric not in ("tam", "sam", "som"):
                    problem = "is not one of 'tam', 'sam', 'som'"
                elif _claim_high(inputs_art, metric) is not None:
                    continue
                elif _as_dict(raw).get(metric) is None:
                    problem = "has no lower bound in existing_claims"
                else:
                    problem = "is not a number above its lower bound"
                warnings.append(
                    _warn(
                        "EXISTING_CLAIMS_SHAPE",
                        f"inputs.existing_claims_high.{metric} ({high!r}) {problem}, so this upper bound "
                        f"was ignored and the figure is compared as a single value.",
                    )
                )
        raw_alts = inputs_art.get("existing_claims_alternatives")
        if isinstance(raw_alts, dict):
            for metric in sorted(raw_alts):
                if metric not in ("tam", "sam", "som") or _as_dict(raw).get(metric) is None:
                    warnings.append(
                        _warn(
                            "EXISTING_CLAIMS_SHAPE",
                            f"inputs.existing_claims_alternatives.{metric} has no stated figure in "
                            f"existing_claims to disagree with, so it was ignored.",
                        )
                    )
        for item in claim_disagreements(inputs_art):
            warnings.append(_warn("DECK_CLAIMS_DISAGREE", disagreement_sentence(item)))
        if raw_high is not None and not isinstance(raw_high, dict) and raw_high != {}:
            warnings.append(
                _warn(
                    "EXISTING_CLAIMS_SHAPE",
                    f"inputs.existing_claims_high must be a dict of {{tam, sam, som}}; got {type(raw_high).__name__}.",
                )
            )

    # 18. FACTOR_PRODUCT_MISMATCH / UNSTRUCTURED_DERIVATION -- a derivation is checkable only when
    # it is itemized. On the run that motivated this, four narrowing factors lived inside an
    # English label, three of them shared with the other build, and nothing could see either fact.
    if _usable(validation):
        unstructured: list[str] = []
        # Factors listed by name but not in a checkable form (a live run's lacked `source_id`). The
        # warning used to say they were "not recorded separately", which was false; it names the gap.
        factors_unsourced: list[str] = []
        for a in _as_list(validation.get("assumptions")):
            if not isinstance(a, dict) or a.get("category") != "derived":
                continue
            derived_name = a.get("name")
            if not isinstance(derived_name, str):
                continue
            chain = _factor_chain(a)
            if chain is None:
                listed = [f for f in _as_list(a.get("factors")) if isinstance(f, dict) and f.get("factor_id")]
                (factors_unsourced if len(listed) >= 2 else unstructured).append(_humanize_param(derived_name))
                continue
            value = _as_number(a.get("value"))
            if value is None:
                continue
            expected = _factor_product(derived_name, chain, a.get("unit"))
            if expected and not math.isclose(value, expected, rel_tol=FACTOR_PRODUCT_TOL):
                shown = _render_factor_chain(chain, _fmt_factor)
                warnings.append(
                    _warn(
                        "FACTOR_PRODUCT_MISMATCH",
                        f"{_humanize_param(derived_name)} is stated as {_fmt_number(value)} but the figures "
                        f"it is built from ({shown}) come to {_fmt_number(expected)}. One of the two is "
                        f"wrong, and the sizing used the stated value.",
                    )
                )
        # ONE warning per run naming every affected figure, not one per assumption. Both forms
        # report the same figures by name, so aggregating loses no signal, and four near-identical
        # paragraphs would crowd out the mediums beside them. CHECKLIST_FAILURES is the precedent.
        if unstructured or factors_unsourced:
            parts = []
            if unstructured:
                one = len(unstructured) == 1
                parts.append(
                    f"{len(unstructured)} {'figure is' if one else 'figures are'} derived from other numbers "
                    f"that are not recorded separately ({', '.join(unstructured)})"
                )
            if factors_unsourced:
                one = len(factors_unsourced) == 1
                parts.append(
                    f"{len(factors_unsourced)} {'figure lists' if one else 'figures list'} the numbers "
                    f"{'it is' if one else 'they are'} built from without a source for each "
                    f"({', '.join(factors_unsourced)})"
                )
            warnings.append(
                _warn(
                    "UNSTRUCTURED_DERIVATION",
                    "; ".join(parts) + " — so nothing can check the arithmetic behind them, or tell whether "
                    "both approaches lean on the same figure.",
                )
            )

    # 19. RED_TEAM_FINDINGS / RED_TEAM_FINDINGS_DROPPED. The section renders both, but the
    # summary a founder reads first is built from the analysis's own artifacts, so without a
    # warning it states a confident figure with a sourced contradiction ten lines below it.
    redteam_art = artifacts.get("redteam.json")
    if _usable(redteam_art):
        rt_findings = [f for f in _as_list(redteam_art.get("findings")) if isinstance(f, dict)]
        if rt_findings:
            warnings.append(
                _warn(
                    "RED_TEAM_FINDINGS",
                    _adversarial_outcome(redteam_art, None)
                    + " Each quotes the sentence it relies on; they are listed under Adversarial Findings."
                    + " Re-running or editing cannot fix a finding that is true; deliver them as they"
                    + " are, and the founder decides what to do about them.",
                )
            )
        rt_unread = [str(x) for x in _as_list(redteam_art.get("sources_unread")) if str(x).strip()]
        if rt_unread:
            noun = "document" if len(rt_unread) == 1 else "documents"
            warnings.append(
                _warn(
                    "RED_TEAM_SOURCES_UNREAD",
                    f"The adversarial review did not open {len(rt_unread)} of your {noun}: "
                    f"{', '.join(rt_unread)}. Any figure taken from those pages was checked against "
                    f"the analysis's reading of them, not against the page.",
                )
            )
        rt_dropped = int(_as_dict(redteam_art.get("summary")).get("rejected") or 0)
        if rt_dropped:
            one = rt_dropped == 1
            noun, verb, them = ("challenge", "was", "It") if one else ("challenges", "were", "They")
            shown = "it is" if one else "they are"
            warnings.append(
                _warn(
                    "RED_TEAM_FINDINGS_DROPPED",
                    f"{rt_dropped} further {noun} {verb} raised against this analysis but gave no "
                    f"source, so {shown} not shown. {them} {verb} not assessed and may or may not "
                    f"be right.",
                )
            )

    return warnings


def _section_deck_claims_narrative(inputs: dict[str, Any] | None) -> str:
    """Render existing_claims_detail as a narrative sub-section.

    Captures deck claims that don't fit the canonical {tam, sam, som} flat shape
    (regional sub-SAMs, time-anchored figures, alternative TAM frames). Rendered
    as-is; does NOT participate in deck-vs-computed reconciliation.
    """
    if inputs is None or _is_stub(inputs):
        return ""
    detail = inputs.get("existing_claims_detail")
    if not detail:  # None, empty dict, empty list, empty string, etc.
        return ""
    # Not attributed to "the deck": nothing records where each figure came from, and one uploaded
    # document used to make every claim the deck's, including figures the founder typed in chat.
    heading = "Your Stated Figures"
    source = "You stated"
    lines = [f"## {heading} (Narrative)\n"]
    lines.append(
        f"*{source} additional figures that don't fit the canonical "
        "TAM/SAM/SOM shape. These are captured for context but are not "
        "reconciled against the computed sizing.*\n"
    )
    lines.extend(_claim_lines(detail))
    return "\n".join(lines) + "\n"


def _claim_key(key: str) -> str:
    """A founder-authored data key as words, acronyms kept.

    `humanize_token` is the right call even for a key carrying a numeric segment. The shared policy's
    numeric-segment blind spot is in DETECTION -- `_CANDIDATE_RE` has to find a token inside free prose
    -- not in the transformation, and a key is already known here, so detection is not involved:
    `active_accounts_april_2028` comes back as words, and `regional_sam_north_america` keeps SAM as an
    acronym where a plain underscore-to-space would flatten it to "sam".

    Falls back to plain spacing when the policy is unavailable, since a missing policy module must never
    block a report.
    """
    ft = _founder_text_policy()
    if ft is not None:
        humanized = str(ft.humanize_token(key)).strip()
        if humanized:
            return humanized
    words = key.replace("_", " ").strip()
    return (words[:1].upper() + words[1:]) if words else key


def _claim_figure(val: dict[str, Any]) -> str | None:
    """A figure leaf printed by its own unit, or None when this mapping is not a figure.

    The unit DECIDES the format and is never itself printed -- a unit is a dimension, not a label.
    """
    if "value" not in val:
        return None
    unit = val.get("unit")
    unit_s = unit if isinstance(unit, str) else None
    shown = _params.format_value(unit_s, val.get("value"), str(val.get("currency") or "USD"))
    period = val.get("period")
    if unit_s == _params.MONEY_PER_CUSTOMER and isinstance(period, str) and period.strip():
        # The convention the Assumptions rows already use, so one figure reads one way on every page.
        shown += f" per {period}"
    label = val.get("label")
    if isinstance(label, str) and label.strip():
        shown += f" — {_md_safe(label.strip())}"
    return shown


def _claim_scalar(val: Any) -> str:
    """A plain value beside the figures: grouped if it is a number, never given a currency.

    A bare scalar declares no unit, so nothing here may decide it is money; `format_value` with no unit
    groups the digits and does exactly that ("an unknown unit prints the bare number, never money").
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return _md_safe(str(val))
    return _params.format_value(None, val)


def _claim_lines(detail: Any, depth: int = 0) -> list[str]:
    """`existing_claims_detail` as labelled lines, nested maps indented under their key.

    `str()` on this structure put a Python repr in front of founders -- quoted keys, nested braces and
    unit enums -- because the shape is nested more than one level: a figure leaf, a plain scalar and a
    sub-map of figures all appear side by side. So it is walked rather than stringified.
    """
    indent = "  " * depth
    out: list[str] = []
    if isinstance(detail, dict):
        # A bare `label` describes the mapping it sits in, not a figure of its own.
        note = detail.get("label")
        described = depth > 0 and isinstance(note, str) and bool(note.strip())
        if described:
            out.append(f"{indent}- {_md_safe(str(note).strip())}")
        for key, val in detail.items():
            if key == "label" and described:
                continue
            shown = _claim_figure(val) if isinstance(val, dict) else None
            if shown is not None:
                out.append(f"{indent}- **{_claim_key(str(key))}:** {shown}")
            elif isinstance(val, (dict, list)):
                out.append(f"{indent}- **{_claim_key(str(key))}:**")
                out.extend(_claim_lines(val, depth + 1))
            else:
                out.append(f"{indent}- **{_claim_key(str(key))}:** {_claim_scalar(val)}")
    elif isinstance(detail, list):
        for item in detail:
            if isinstance(item, (dict, list)):
                out.extend(_claim_lines(item, depth))
            else:
                out.append(f"{indent}- {_claim_scalar(item)}")
    else:
        out.append(f"{indent}- {_claim_scalar(detail)}")
    return out


def _section_title_provenance(
    inputs: dict[str, Any] | None,
    sizing: dict[str, Any] | None = None,
) -> str:
    """Section 1: Title and provenance."""
    if inputs is None:
        return "# Market Sizing Report\n\n*No inputs artifact found.*\n"
    company = inputs.get("company_name", "Unknown Company")
    date = inputs.get("analysis_date", "unknown date")
    materials = _as_list(inputs.get("materials_provided"))
    mat_str = ", ".join(str(m) for m in materials) if materials else "none"
    basis_label = _sizing_basis_label(_resolve_sizing_basis(sizing, inputs))
    lines = [
        f"# Market Sizing: {company}\n",
        f"**Date:** {date}  ",
        f"**Materials:** {mat_str}  ",
        f"**Sizing basis:** {basis_label}  ",
        "**Generated by:** [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent\n",
    ]
    return "\n".join(lines)


def _widest_stressed(sensitivity: dict[str, Any] | None) -> list[str]:
    """Every parameter tied at the top of sensitivity_ranking.

    `most_sensitive` is `sensitivity_ranking[0]`, and the ranking sorts by `som_swing_pct` -- which,
    for these pure-product models, is just the stress band width. So the "ranking" reflects how wide
    a band each parameter was given, not how much the answer depends on it, and ties are common:
    measured across 14 real runs, the top swing was a TIE on 11, broken by whatever order the
    sub-agent listed parameters.

    CORRECTED 2026-08-15 -- an earlier version of this note said ranges are "assigned by CONFIDENCE
    CLASS, so a well-sourced parameter can never top the ranking". That is false as a mechanism:
    `range_widened` is False on 83/83 scenarios across the corpus, i.e. CONFIDENCE_MIN_RANGE
    (sensitivity.py) has never once fired. The bands arrive from the sub-agent already at those
    widths; the producer floor only ever widens a NARROWER band and never had to. Sourced parameters
    do top the ranking on real runs. The tie is real; the causal story was not.

    Derived from the artifact rather than stored as a new field: both render sites already read
    `sensitivity_ranking`, so a stored field would buy a schema row and a ceiling bump for nothing.
    """
    ranking = _as_list((sensitivity or {}).get("sensitivity_ranking"))
    if not ranking:
        return []
    top = ranking[0].get("som_swing_pct")
    if top is None:
        return [str(ranking[0].get("parameter", "?"))]
    return [str(r.get("parameter", "?")) for r in ranking if r.get("som_swing_pct") == top]


def _verdict_marks(
    sizing: dict[str, Any],
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
    redteam: dict[str, Any] | None,
) -> dict[tuple[str, str], str]:
    """The †/‡/§ mark each summary-table row carries; the verdict quotes figures with these marks."""
    shared = _shared_input_values(sizing, validation)
    identity_metrics = {s["metric"] for s in shared if s["kind"] == "identity"}
    shared_metrics = {s["metric"] for s in shared if s["kind"] in ("equal_value", "shared_factor")}
    contested_rows = _contested_rows(sizing, inputs, redteam)
    marks: dict[tuple[str, str], str] = {}
    for approach_key in ("top_down", "bottom_up"):
        for metric in ("tam", "sam", "som"):
            marks[(approach_key, metric)] = (
                (" †" if metric in identity_metrics else "")
                + (" ‡" if metric in shared_metrics else "")
                + (" §" if (approach_key, metric) in contested_rows else "")
            )
    return marks


def _verdict_paragraph(
    sizing: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None,
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
    redteam: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    skip_reason: str | None,
    bypassed: bool = False,
) -> str:
    """The report's first paragraph, as one string. Never empty: with no sizing it says so.

    Stored in report.json as top-level `verdict` so closing_message.py can print the same words in
    chat. The message used to point at this paragraph and carry no figure; measured 0/2 at hostloop,
    the model wrote its own verdict with its own rounding in front of the pointer. A message that
    already answers leaves nothing to add.
    """
    _ha = _handoff_audit() if bypassed else None
    tail = (" " + _ha.VERDICT_SENTENCE) if _ha is not None else ""
    if sizing is None or _is_stub(sizing):
        return "No sizing was produced; see Warnings. " + _adversarial_outcome(redteam, skip_reason) + tail
    marks = _verdict_marks(sizing, validation, inputs, redteam)
    text, _stated = _summary_verdict(sizing, provenance, checklist, redteam, skip_reason, marks, inputs)
    return text + tail


def _section_executive_summary(
    sizing: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    redteam: dict[str, Any] | None = None,
    checklist: dict[str, Any] | None = None,
    skip_reason: str | None = None,
    bypassed: bool = False,
) -> str:
    """Executive summary: the verdict paragraph, then the marked table, then the deck-claim notes."""
    verdict = _verdict_paragraph(sizing, provenance, validation, inputs, redteam, checklist, skip_reason, bypassed)
    if sizing is None or _is_stub(sizing):
        # Never silence: the first thing a reader sees says what happened.
        return "## Executive Summary\n\n" + verdict + "\n"

    lines = ["## Executive Summary\n"]

    # Rows whose two approaches are ONE computation get a dagger, so the caveat sits on the table
    # a founder reads rather than only in an appendix. A DAGGER, not a star: the deck-claims table
    # already owns `*` for close agreement, and two meanings for one glyph in one report is a
    # defect of its own.
    # Both marks come from the DETECTOR, not the warning list. `accepted_warnings` can demote the
    # warning to acknowledged, and on a live run the constructor did exactly that -- with a reason
    # conceding the two builds were "not fully independent corroboration ... which the report should
    # say plainly" -- while this table said nothing, because only the identity kind was marked.
    # Acceptance explains; it must not hide.
    shared = _shared_input_values(sizing, validation)
    shared_metrics = {s["metric"] for s in shared if s["kind"] in ("equal_value", "shared_factor")}
    contested_rows = _contested_rows(sizing, inputs, redteam)
    marks = _verdict_marks(sizing, validation, inputs, redteam)
    lines.append(verdict + "\n")
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
            lines.append(f"| {metric.upper()} | {_fmt_usd(val)} | {method}{marks[(approach_key, metric)]} |")

    if sensitivity is not None and not _is_stub(sensitivity):
        tied = _widest_stressed(sensitivity)
        most = sensitivity.get("most_sensitive")
        if len(tied) > 1:
            names = ", ".join(_humanize_param(t) for t in tied)
            lines.append(f"| Widest-Stressed Parameters (tied) | {names} | — |")
        elif most:
            lines.append(f"| Widest-Stressed Parameter | {_humanize_param(most)} | — |")

    identity = [s for s in shared if s["kind"] == "identity"]
    if identity:
        # The detail sentence already ends "one computation, shown two ways" -- prefixing the
        # footnote with the same phrase printed it twice in one line. Let the detail carry it.
        lines.append(
            "\n† "
            + " ".join(str(s["detail"]) for s in identity)
            + " Agreement on these rows is arithmetic, not corroboration."
        )
    if shared_metrics:
        lines.append(
            "\n‡ Both builds narrow this figure by the same number(s), so on it they are not independent "
            "checks of each other: "
            + " ".join(str(s["detail"]) for s in shared if s["kind"] in ("equal_value", "shared_factor"))
        )
    if contested_rows:
        lines.append("\n§ Built on a figure you stated that a cited source contradicts; see Adversarial Findings.")

    # Flag significant deck claim deltas
    if provenance:
        both_mode = "top_down" in provenance and "bottom_up" in provenance
        for metric in ("tam", "sam", "som"):
            # Collect mismatches across approaches for this metric
            mismatches: list[tuple[str, float, float]] = []  # (label, val, deck_claim)
            claim_high_shown: float | None = None
            for approach_key in ("top_down", "bottom_up"):
                if approach_key not in provenance:
                    continue
                prov = provenance[approach_key].get(metric, {})
                delta = prov.get("delta_vs_deck_pct")
                deck_claim = prov.get("deck_claim")
                if delta is not None and abs(delta) > DECK_MISMATCH_PCT and deck_claim is not None:
                    approach_data = _as_dict(sizing.get(approach_key)) if sizing else {}
                    m_data = _as_dict(approach_data.get(metric))
                    val = m_data.get("value", 0)
                    label = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    # The CONVERTED claim, matching the table and the warning. Printing the raw
                    # one here put two different figures for the same field in one document,
                    # 24 lines apart.
                    _cmp = prov.get("deck_claim_comparable")
                    mismatches.append((label, float(val), float(deck_claim if _cmp is None else _cmp)))
                    claim_high_shown = _as_number(prov.get("deck_claim_high_comparable"))
            if mismatches:
                claim_str = claim_display(mismatches[0][2], claim_high_shown)
                if both_mode and len(mismatches) > 1:
                    parts = ", ".join(f"{lbl}: {_fmt_usd(v)}" for lbl, v, _ in mismatches)
                    lines.append(
                        f"\n**Note:** Both {metric.upper()} estimates differ significantly "
                        f"from the figure you stated, {claim_str} ({parts})."
                    )
                elif both_mode:
                    lbl, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {lbl.lower()} {metric.upper()} estimate differs significantly "
                        f"from the figure you stated ({_fmt_usd(val)} vs {claim_str})."
                    )
                else:
                    _, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {metric.upper()} estimate differs significantly "
                        f"from the figure you stated ({_fmt_usd(val)} vs {claim_str})."
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
        # NOT "cross-validation". That word asserts the comparison validates something, and the
        # pipeline does not track where each input came from, so it cannot tell whether the two
        # builds are independent -- the same reason the word is refused at the comparison note and
        # in visualize.py. This was the last site left after the closeness-as-strength pass, and it
        # sits on the Methodology line a founder quotes into a deck footnote.
        "both": "Both (top-down and bottom-up, compared)",
        "top_down": "Top-down",
        "bottom_up": "Bottom-up",
    }.get(approach, approach)

    lines = ["## Methodology\n"]
    lines.append(f"**Approach:** {approach_label}")
    if rationale:
        lines.append(f"**Rationale:** {rationale}")
    return "\n".join(lines) + "\n"


def _section_analysis_checklist(checklist: dict[str, Any] | None, artifacts_found: list[str]) -> str:
    """Analysis checklist with compact 22-row appendix."""
    lines = ["## Analysis Checklist\n"]
    # A count, not the filenames. The founder cannot act on "inputs.json, methodology.json, …" — the
    # signal the line actually carries is "how much of the analysis completed", and that survives.
    # Which specific artifact is missing is an operator question, and the missing-artifact warnings
    # already answer it.
    lines.append(f"- Analysis steps completed: {len(artifacts_found)}")
    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        lines.append(f"- {_self_check_line(checklist)}")

        # Failed items detail
        failed_items = _as_list(summary.get("failed_items"))
        if failed_items:
            lines.append("\n**Items that failed:**")
            for raw_f in failed_items:
                f = _as_dict(raw_f)
                label = f.get("label", f.get("id", "?"))
                notes = f.get("notes", "")
                lines.append(f"- **{label}**: {notes}" if notes else f"- **{label}**")

        # Compact 22-row appendix table
        items = _as_list(checklist.get("items"))
        if items:
            lines.append("\n### Appendix: Full Self-Check\n")
            lines.append("| # | Criterion | Status | Notes |")
            lines.append("|---|-----------|--------|-------|")
            status_icons = {"pass": "PASS", "fail": "FAIL", "not_applicable": "N/A"}
            for i, raw_item in enumerate(items, 1):
                item = _as_dict(raw_item)
                label = _md_safe(item.get("label", item.get("id", "?")))
                status = status_icons.get(item.get("status", "?"), "?")
                notes = _md_safe(item.get("notes", "") or "")
                lines.append(f"| {i} | {label} | {status} | {notes} |")

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


# The four narrowing/capture parameters whose `value` is stored in PERCENTAGE POINTS while their
# factors are fractions, so the product needs x100 to reconcile. Keyed on the name because that is
# what the schema contracts; a `derived` percentage under a descriptive name outside this set is
# the known false-positive surface for FACTOR_PRODUCT_MISMATCH, recorded at its severity.
_PCT_PARAMS: frozenset[str] = frozenset({"segment_pct", "share_pct", "serviceable_pct", "target_pct"})

# Relative tolerance for the product check. 2% absorbs the rounding a real run does -- 10.047
# stated as 10.0 -- which is the whole reason this check measures zero true positives today.
FACTOR_PRODUCT_TOL = 0.02


def _factor_product(name: str, chain: list[dict[str, Any]], unit: Any = None) -> float:
    """What the chain says the value should be. A percentage is stored x100.

    A figure that records its unit is a percentage when the unit says so, whatever its name. Only a
    figure with no recorded unit falls back to the name, because a percentage recorded under a
    descriptive name would otherwise miss the x100 and read as a false mismatch.

    A `divisor`-role factor divides instead of multiplying, so a chain can itemize a RATIO
    (multiplicands ÷ divisors) rather than only a product of narrowing multiplicands. A zero
    divisor makes the ratio undefined; this returns 0.0 in that case, which reuses the caller's
    existing `if expected` falsy-check -- the same path a legitimately all-zero multiplicand
    product already takes -- so a bad divisor is skipped rather than raising ZeroDivisionError or
    manufacturing a bogus FACTOR_PRODUCT_MISMATCH.
    """
    numerator = 1.0
    denominator = 1.0
    for f in chain:
        if f.get("role") == "divisor":
            denominator *= float(f["value"])
        else:
            numerator *= float(f["value"])
    if denominator == 0.0:
        return 0.0
    prod = numerator / denominator
    is_pct = _params.is_percent(unit) if unit in _params.UNITS else name in _PCT_PARAMS
    return prod * 100.0 if is_pct else prod


def _fmt_factor(value: Any) -> str:
    """A factor as the founder can check it: 15,000,000 not 1.5e+07, and 0.3732 not a rounded 0.37.

    `:g` put a ratio's numerator into scientific notation in the one line meant to let a founder
    redo the arithmetic, and the report's money-style formatter rounds a share to two places, which
    changes the product being checked.
    """
    v = float(value)
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:.6g}" if abs(v) < 1e6 else f"{v:,.2f}"


def _render_factor_chain(chain: list[dict[str, Any]], fmt: Callable[[Any], str]) -> str:
    """Render a factor chain in the order given: a `divisor`-role factor is preceded by ÷
    instead of ×, so a ratio ("a ÷ b") reads as one relationship, not as a product of
    two unrelated numbers. `fmt` formats each factor's own value; callers use two different
    formatters (see `_section_assumptions` and the FACTOR_PRODUCT_MISMATCH message).
    """
    parts: list[str] = []
    for i, f in enumerate(chain):
        sep = " ÷ " if f.get("role") == "divisor" else (" × " if i else "")
        parts.append(sep + fmt(f["value"]))
    return "".join(parts)


# The producer's closing caveat, verbatim (market_sizing.py emits it on every sub-30% note). It is
# TRUE only while nothing is itemized. Once `_shared_input_values` has found a shared figure, "the
# pipeline cannot tell" is contradicted by the sentence printed right after it -- measured on the
# run that motivated the shared-figure check, where the paragraph read "cannot tell whether the two
# builds rest on the same underlying figures. Check whether they do. Your Industry Total equals ...".
# So when something was seen, the caveat says so and introduces the list; the un-itemized remainder
# is UNSTRUCTURED_DERIVATION's to report, not this sentence's.
_PRODUCER_CAVEAT = (
    "Closeness is not confirmation: the pipeline cannot tell whether the two builds rest on the "
    "same underlying figures. Check whether they do."
)
_SEEN_CAVEAT = (
    "Closeness is not confirmation — and where the inputs are itemized, the pipeline can see what the two builds share:"
)


def _comparison_paragraph(comparison: dict[str, Any], shared: list[dict[str, Any]]) -> str:
    """The comparison sentences plus what the builds share, with the caveat matching what was seen.

    With nothing shared the producer's caveat stands as written. With shared figures found, the
    "cannot tell" form is replaced by one that introduces them; a >30% warning carries no caveat
    to replace, so the details are simply appended, as before.
    """
    text = _comparison_sentences(comparison)
    if not shared:
        return text
    details = " ".join(str(s["detail"]) for s in shared)
    if _PRODUCER_CAVEAT in text:
        return text.replace(_PRODUCER_CAVEAT, _SEEN_CAVEAT) + " " + details
    return text + " " + details


def _comparison_sentences(comparison: dict[str, Any]) -> str:
    """Every compared metric's finding, with each distinct sentence said ONCE.

    Reads `<metric>_warning` when the producer raised one (>30%) and `<metric>_note` otherwise;
    TAM's keys are unprefixed (`note`/`warning`) for historical reasons. A metric ABSENT from the
    comparison block (a single-approach run) is skipped, never invented. A zero pair is NOT absent:
    market_sizing.py sets `<metric>_delta_pct = 0` and a "Both X values are zero." note, and that
    renders -- correctly, since it is a real statement about the run.

    WHY SENTENCE-LEVEL DEDUPLICATION. Each producer note is "<METRIC> estimates differ by X%." plus
    a closing caveat that is BYTE-IDENTICAL across all three (the literal appears four times in
    market_sizing.py). Rendering the notes end to end therefore printed that 24-word caveat three
    times in one paragraph -- correct, and read once and then skipped, which defeats the point of
    surfacing it. So: every metric's leading sentence first, in metric order, then each remaining
    sentence once in first-appearance order.

    No prose is parsed for MEANING and nothing is reworded -- the producer still owns every
    sentence. Splitting is on ". " only, which cannot split a decimal ("9.4%") or a parenthetical
    ("(>30%)."). If the texts happen to share nothing, every sentence survives and the output is
    exactly what concatenating them would have produced, so the degradation is the old behaviour.
    """
    leads: list[str] = []
    rest: list[str] = []
    for delta_key, note_key, warn_key in (
        ("tam_delta_pct", "note", "warning"),
        ("sam_delta_pct", "sam_note", "sam_warning"),
        ("som_delta_pct", "som_note", "som_warning"),
    ):
        if delta_key not in comparison:
            continue
        text = str(comparison.get(warn_key) or comparison.get(note_key) or "").strip()
        if not text:
            continue
        sentences = [s.strip() for s in text.split(". ") if s.strip()]
        for i, sentence in enumerate(sentences):
            # Restore the separator `split` consumed on every sentence but the last.
            sentence = sentence if sentence.endswith(".") else sentence + "."
            target = leads if i == 0 else rest
            if sentence not in leads and sentence not in rest:
                target.append(sentence)
    return " ".join(leads + rest)


def _section_sizing_table(
    sizing: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
) -> str:
    """Section 4: Market sizing table."""
    if sizing is None:
        return "## Market Sizing\n\n*No sizing data available.*\n"
    if _is_stub(sizing):
        return f"## Market Sizing\n\n*Sizing not performed — {sizing.get('reason', 'unknown reason')}*\n"

    lines = ["## Market Sizing\n"]

    # Non-USD disclosure. Labelling the figures correctly is necessary but not
    # sufficient: an externally-sourced industry total is very often quoted in
    # USD, and nothing here converts it. Say so rather than let a mixed-unit
    # TAM pass as a single-unit one.
    # Two mutually exclusive disclosures. The no-FX wording is unchanged for a run where nothing
    # was converted (the overwhelmingly common case); a converted run gets the rate, its date and
    # its source stated in the founder's own report, so the number is auditable rather than
    # asserted. Never print both — the old text claimed "no FX conversion is applied anywhere",
    # which becomes false the moment one is.
    _fx_conv = _fx_conversions(sizing)
    if _fx_conv:
        _fx_meta = _as_dict(_as_dict(sizing).get("fx"))
        _as_of = _fx_meta.get("as_of") or "date not stated"
        _src = _fx_meta.get("source") or "source not stated"
        _each = "; ".join(
            f"{c.get('field')} {_fmt_usd(float(c.get('original_value', 0)), str(c.get('from')))} "
            f"→ {_fmt_usd(float(c.get('converted_value', 0)), str(c.get('to')))} "
            f"at 1 {c.get('from')} = {c.get('rate')} {c.get('to')}"
            for c in _fx_conv.values()
        )
        lines.append(
            f"> **Currency: {_view._CURRENCY}.** Some inputs were supplied in another currency and "
            f"converted into {_view._CURRENCY}: {_each}. Rate as of {_as_of} ({_src}). Every figure below "
            f"is in {_view._CURRENCY}; check the rate if you are comparing against a source in its "
            f"original currency.\n"
        )
    elif _view._CURRENCY != "USD":
        lines.append(
            f"> **Currency: {_view._CURRENCY}.** All figures are stated in {_view._CURRENCY} as supplied — "
            f"**no FX conversion is applied anywhere in this analysis.** If any input came from an "
            f"external source quoted in another currency (industry totals usually are quoted in USD), "
            f"convert it to {_view._CURRENCY} yourself before relying on the combined figure.\n"
        )

    # One-line narrative per approach
    td_data = sizing.get("top_down")
    bu_data = sizing.get("bottom_up")
    if td_data:
        tam_inputs = _as_dict(_as_dict(td_data.get("tam")).get("inputs"))
        td_sam_inputs = _as_dict(_as_dict(td_data.get("sam")).get("inputs"))
        industry = _input_shown("industry_total", tam_inputs)
        seg = _input_shown("segment_pct", td_sam_inputs)
        share_inputs = _as_dict(_as_dict(td_data.get("som")).get("inputs"))
        share = _input_shown("share_pct", share_inputs)
        lines.append(
            f"**Top-down:** Starting from industry total of {industry}, "
            f"targeting {seg} segment with {share} market share.\n"
        )
    if bu_data:
        tam_inputs = _as_dict(_as_dict(bu_data.get("tam")).get("inputs"))
        cust = _input_shown("customer_count", tam_inputs)
        arpu_val = _input_shown("arpu", tam_inputs)
        sam_inputs = _as_dict(_as_dict(bu_data.get("sam")).get("inputs"))
        serv = _input_shown("serviceable_pct", tam_inputs, sam_inputs)
        som_inputs = _as_dict(_as_dict(bu_data.get("som")).get("inputs"))
        tgt = _input_shown("target_pct", tam_inputs, som_inputs)
        bu_line = (
            f"**Bottom-up:** {cust} potential customers x {arpu_val} ARPU, {serv} serviceable, {tgt} target capture.\n"
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
                formatted = _params.format_value(_params.unit_of(k), v, _view._CURRENCY)
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
        # NOT "Cross-validation" -- that label asserts the comparison validates something. The
        # pipeline does not track where each input came from, so it cannot tell whether the two
        # builds are independent, and a small delta is therefore not confirmation. Measured: this
        # label rendered on 13/13 real runs, i.e. wider reach than the note it introduces.
        #
        # ALL THREE metrics, not TAM alone. market_sizing.py has computed sam_note/som_note since
        # the SAM/SOM comparison was added and nothing consumed them -- recorded as "shipped but
        # INERT". On a real run the SAM delta therefore reached the founder solely through two
        # LLM-written prose channels, both of which called a 9.4% gap "corroboration", while the
        # producer's own caveat for it sat unrendered in sizing.json.
        _shared = _shared_input_values(sizing, validation)
        lines.append(f"\n**Top-down vs bottom-up:** {_comparison_paragraph(comparison, _shared)}")

    # Deck Claims comparison table
    if provenance:
        comparison_rows: list[str] = []
        close_agreement = False
        blocked_rows = False
        for approach_key in ("top_down", "bottom_up"):
            if approach_key not in provenance:
                continue
            for metric in ("tam", "sam", "som"):
                prov = provenance[approach_key].get(metric, {})
                deck_claim = prov.get("deck_claim")
                delta_pct = prov.get("delta_vs_deck_pct")
                classification = prov.get("classification", "")
                # Gate the ROW on the claim, not on the delta. Gating on the delta means a blocked
                # comparison drops the row entirely -- and with every row gone, the whole section
                # disappears, taking the founder's own stated figure out of the report. A refused
                # comparison is worth showing: here is what you said, here is what we got, and we
                # could not put them side by side.
                # NUMERIC AND POSITIVE, not merely non-None. `existing_claims: {tam: "big"}` is a
                # legitimate input shape that produces no comparison at all and would send a
                # string into `float()`; a zero or negative claim is one `_compute_delta` refuses
                # (division), so it has no delta either -- and gating the row on "no delta" alone
                # rendered `$0.00` beside an em-dash on runs with no currency conversion anywhere.
                if isinstance(deck_claim, (int, float)) and not isinstance(deck_claim, bool) and deck_claim > 0:
                    approach_data = sizing.get(approach_key, {})
                    m = _as_dict(approach_data.get(metric))
                    val = m.get("value", 0)
                    method = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    classification = _md_safe(classification)
                    marker = ""
                    if (
                        delta_pct is not None
                        and abs(float(delta_pct)) <= CLOSE_AGREEMENT_PCT
                        and not prov.get("comparison_blocked")
                        and not prov.get("within_claim_range")
                    ):
                        marker = " *"
                        close_agreement = True
                    # `is not None`, not `or`: a legitimate comparable of 0.0 is falsy and would
                    # silently fall back to the raw claim.
                    _comparable = prov.get("deck_claim_comparable")
                    _blocked = bool(prov.get("comparison_blocked"))
                    _shown_claim = deck_claim if _comparable is None else _comparable
                    # On the BLOCKED branch the whole point is that we do not know what currency
                    # this figure is in -- and `_fmt_usd` suffixes the ANALYSIS currency, so
                    # printing it here labelled the founder's figure "ILS" one line above the
                    # sentence saying its currency is unknown. Same mislabel this commit fixed on
                    # the converting branch; it must not survive on the branch beside it.
                    _high_shown = _as_number(
                        prov.get("deck_claim_high") if _blocked else prov.get("deck_claim_high_comparable")
                    )
                    _claim_cell = (
                        f"{claim_display(float(_shown_claim), _high_shown, '')} (currency not stated)"
                        if _blocked
                        else claim_display(float(_shown_claim), _high_shown)
                    )
                    # An em-dash reads as missing data. A horizon mismatch is not missing data:
                    # it is two figures for different periods, and saying which periods is what
                    # lets the founder act (put both on one horizon, and the check runs).
                    _hm_prov = _as_dict(prov.get("horizon_mismatch"))
                    if _hm_prov:
                        _delta_cell = (
                            f"different horizon ({_hm_prov.get('claim_months')} vs {_hm_prov.get('ours_months')} mo)"
                        )
                    elif prov.get("within_claim_range"):
                        _delta_cell = "within your range"
                    elif delta_pct is not None:
                        _delta_cell = f"{_params.fmt_delta(delta_pct, signed=True)}{marker}"
                    else:
                        _delta_cell = "—"
                    comparison_rows.append(
                        f"| {metric.upper()} ({method}) | {_claim_cell} "
                        f"| {_fmt_usd(val)} | {_delta_cell} | {classification} |"
                    )
                    # Keyed on the REFUSAL, not on "there is no delta". A delta can be absent for
                    # reasons that have nothing to do with currency, and the note below asserts a
                    # currency problem.
                    if _blocked:
                        blocked_rows = True
        if comparison_rows:
            lines.append("\n### Your Figures vs. Our Estimates\n")
            lines.append("| Metric | Your Figure | Our Estimate | Delta | Classification |")
            lines.append("|--------|-----------|--------------|-------|----------------|")
            lines.extend(comparison_rows)
            if blocked_rows:
                # A dash with no explanation reads as missing data rather than a refused
                # comparison, and the founder cannot act on it without knowing the cause.
                lines.append(
                    # NOT "they are in different currencies" -- we do not know that, and the same
                    # sentence saying no currency was stated cannot also assert which one it is.
                    # If the figure happened to be in the analysis currency the comparison would
                    # have been valid; the honest claim is that we could not tell.
                    "\nA delta of — means we could not compare the two figures: no currency was "
                    "stated for yours, and this calculation converted its own inputs, so we could "
                    "not tell whether the two are on the same footing. Say which currency your "
                    "figure is in and this check runs."
                )
            if close_agreement:
                lines.append(
                    # "the figure you gave", not "in your materials": a TAM/SAM/SOM claim carries no
                    # source, and it may have been typed in chat rather than taken from a document.
                    f"\n\\* Our figure lands within {CLOSE_AGREEMENT_PCT:.0f}% of the figure you "
                    "gave. Agreement on a number is not independent confirmation — it can "
                    "mean both analyses drew on the same source, or that our input came from a "
                    "figure you gave. To get a real check, size it again from an independently chosen "
                    "value."
                )

    return "\n".join(lines) + "\n"


def _section_assumptions(validation: dict[str, Any] | None, sizing: dict[str, Any] | None = None) -> str:
    """Section 5: Assumptions.

    For a sizing whose inputs carry their provenance, a figure prints by the unit it RECORDS, never by
    its name: a head-count recorded under an input's name is a head-count. Research the sizing did
    not use is marked as context, and an estimate the sizing used instead of research says so.
    """
    stamped = _view.stamped_provenance(sizing)
    if validation is None:
        return "## Assumptions\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return f"## Assumptions\n\n*Validation not performed — {validation.get('reason', 'unknown reason')}*\n"

    rows = _view.assumption_rows(validation, sizing)
    if not rows:
        return "## Assumptions\n\n*No assumptions recorded.*\n"

    lines = ["## Assumptions\n"]
    cat_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    for row in rows:
        cat_display = cat_labels[row["grade"]]
        if row["kind"] == "estimate":
            lines.append(f"- **{row['label']}** = {row['shown']} ({cat_display}) — {row['note']}")
            continue
        a = row["entry"]
        name = a.get("name", "unnamed")
        display_name = a.get("label", _humanize_param(name))
        value = a.get("value", "")
        unit = a.get("unit")
        if stamped is not None and unit in _params.UNITS and isinstance(value, (int, float)):
            ccy = str(a.get("currency") or _view._CURRENCY)
            formatted_val = _params.format_value(unit, value, ccy)
            if unit == _params.MONEY_PER_CUSTOMER and a.get("period"):
                formatted_val += f" per {a.get('period')}"
        elif isinstance(value, (int, float)):
            formatted_val = _fmt_number(value)
        else:
            formatted_val = str(value)
        line = f"- **{display_name}** = {formatted_val} ({cat_display})"
        # Per-assumption attribution. "Sourced" without the source is a claim the founder cannot check,
        # and the sub-agent is asked for exactly this pair on each assumption.
        src_title = str(a.get("source_title", "") or "").strip()
        src_url = str(a.get("source_url", "") or "").strip()
        if src_title and src_url:
            line += f" — [{src_title}]({src_url})"
        elif src_title:
            line += f" — {src_title}"
        elif src_url:
            line += f" — {src_url}"
        # The chain the figure is built from -- multiplied or, for a ratio, divided -- so a
        # founder can check the arithmetic themselves rather than take a derived number on trust.
        chain = _factor_chain(a)
        if chain:
            line += " — built from: " + _render_factor_chain(chain, _fmt_factor)
        if row["used"] is False and unit in _params.UNITS:
            line += " — research context; not used in the sizing"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _red_team_state(
    artifacts: dict[str, dict[str, Any] | None],
    methodology: dict[str, Any] | None,
    primary: str | None,
    no_ask: bool = False,
) -> tuple[str, str | None, str | None]:
    """("ran" | "skipped" | "ungated" | "no_ask_declined", <skip reason enum or None>, <refusal detail or None>).

    `no_ask`: the run's request said not to ask (FS_HOST_NO_ASK), so nobody was asked: this run's skip saying
    the founder declined is "no_ask_declined", a refusal like "ungated" that carries the code
    NO_ASK_FOUNDER_DECLINED and offers only the other reasons.

    "ungated" is the refusal case: no review for this run AND no decision of this run's recorded. It
    is not a state the report can render, because the whole point is that nobody decided anything. The
    detail is the sentence the refusal prints, and it carries the remedy that fits the case.
    """
    art = artifacts.get("redteam.json")
    review_rid: str | None = None
    if _usable(art):
        assert art is not None
        # PARITY, not mere presence. A redteam.json left by an earlier analysis of the same
        # company satisfies an existence check while describing different figures entirely --
        # deck-review's reconciliation gate carries the same rule for the same reason.
        # `primary` is this run's id, the one every other reader resolves the review for
        # (`_redteam_copy.primary_run_id`): the id most required artifacts carry, so one leftover from an
        # earlier run cannot make that run's review count as this one's.
        rid = _as_dict(art.get("metadata")).get("run_id")
        if primary is None or (isinstance(rid, str) and rid == primary):
            return ("ran", None, None)
        review_rid = rid if isinstance(rid, str) and rid else None

    meth = _as_dict(methodology) if isinstance(methodology, dict) else {}
    reason = meth.get("red_team_skipped")
    # The skip's run id: its own stamp, else the id of the methodology.json it is recorded in (written with
    # the run's id by Step 1). A skip with neither is not attributable to any run.
    stamp = meth.get("red_team_skipped_run_id")
    if not (isinstance(stamp, str) and stamp):
        stamp = _as_dict(meth.get("metadata")).get("run_id")
    if isinstance(reason, str) and reason in _RED_TEAM_SKIP_REASONS:
        # A skip is a decision of ONE run. Unstamped, or stamped for another run, it is not this run's:
        # a leftover methodology.json carrying an earlier run's skip otherwise passed a later run's gate.
        # Only a set that carries no run id at all has nothing to compare the stamp with.
        if primary is None or stamp == primary:
            if no_ask and reason == "founder_declined":
                others = ", ".join(sorted(r for r in _RED_TEAM_SKIP_REASONS if r != "founder_declined"))
                return (
                    "no_ask_declined",
                    reason,
                    "methodology.red_team_skipped is founder_declined, but the request said not to ask "
                    "(FS_HOST_NO_ASK), so nobody could decline the adversarial review. Run Step 6c, or set "
                    f"methodology.red_team_skipped to why the review did not run, one of: {others}",
                )
            return ("skipped", reason, None)
        if isinstance(stamp, str) and stamp:
            detail = (
                f"methodology.red_team_skipped was recorded for run {stamp}, not this run {primary}. Run "
                f"Step 6c for this run; only if this run decided not to, set red_team_skipped_run_id to {primary}"
            )
        else:
            detail = (
                "methodology.red_team_skipped carries no run id (no red_team_skipped_run_id, and "
                "methodology.json has none), so it cannot be shown to be this run's decision. If this run "
                f"({primary}) decided not to run the review, set red_team_skipped_run_id to {primary}; "
                "otherwise run Step 6c"
            )
        return ("ungated", reason, detail)
    if review_rid is not None:
        # A review exists, for another run. Recording a skip would hide the review this analysis has;
        # the remedy is a review of this run, with this run's id on the generator and the producer.
        return (
            "ungated",
            None,
            f"a review exists for run {review_rid}, not this run {primary}. Re-run Step 6c with RUN_ID "
            f"{primary} (the dispatch-prompt generator and red_team.py both take it); do not record a skip "
            "to get past this",
        )
    if isinstance(reason, str):
        return (
            "ungated",
            reason,
            f"methodology.red_team_skipped is {reason!r}, which is not a recognised reason. A skip must name "
            "one of the recorded reasons",
        )
    return (
        "ungated",
        None,
        "no adversarial review was run and no decision to skip one was recorded. Run Step 6c, or record the "
        "decision as methodology.red_team_skipped with red_team_skipped_run_id set to this run's id",
    )


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _quote_verified_suffix(verified: Any) -> str:
    if verified is True:
        return ""
    if verified is False:
        return " (this sentence was not found on that page)"
    return " (quoted from a page that could not be machine-read)"


# A red-team quote is the source's words. The founder-text pass rewrites internal tokens in the
# assembled report, and ran over quotes too: a quoted `"existing_claims": {...}` came out altered,
# so the founder was shown a "quotation" the source never contained. The adversarial section fences
# each quote with these private-use sentinels; the final pass lifts them out, rewrites and scans the
# rest, scans each quote on its own with a do-not-edit remedy, then puts them back -- every line of
# a multi-line quote prefixed, where the old single `> ` covered only the first.
_QUOTE_OPEN = "\ue000"
_QUOTE_CLOSE = "\ue001"
_QUOTE_RE = re.compile("\ue000(.*?)\ue001", re.DOTALL)
_QUOTE_SLOT_RE = re.compile("\ue002(\\d+)\ue003")


def _section_your_answers(
    methodology: dict[str, Any] | None,
    inputs: dict[str, Any] | None = None,
    analysis_dir: str | None = None,
    gate_view: dict[str, Any] | None = None,
) -> str:
    """What the founder said after the analysis could still change, and which questions were not asked.

    `founder_notes`: an answer given after the one revision round was used, so it could not change
    the analysis -- it is stated here instead of being restated in chat, where the closing message's
    check would block a figure outside the printed hand-over. `gate_defaults`: questions the founder
    asked not to be asked, and whose first option was taken.
    """
    lines = _your_answers_lines(methodology, inputs, analysis_dir, gate_view)
    if not lines:
        return ""
    return "\n".join(["## Your Answers\n"] + [f"- {line}" for line in lines]) + "\n"


def _section_adversarial(
    redteam: dict[str, Any] | None,
    skip_reason: str | None = None,
    review_note: str | None = None,
    review_changes: list[str] | None = None,
    sizing: Any = None,
    inputs: Any = None,
    later: list[tuple[int, dict[str, Any]]] | None = None,
) -> str:
    """Section: what an outside look at this analysis turned up.

    Three states, all of which must read DIFFERENTLY: the step never ran, it ran and found
    nothing, it ran and found something. Collapsing the first two is the failure this section
    exists to prevent -- "no findings" and "nobody looked" are opposite facts about a report, and
    a founder shown a clean report cannot tell them apart unless it says which.
    """
    if redteam is None:
        # The recorded reason, never a generic absence: "you asked us not to" and "we tried and
        # could not" are different disclosures, and collapsing them is what let the step vanish.
        sentence = _RED_TEAM_SKIP_REASONS.get(
            skip_reason or "",
            "No adversarial review ran. Nothing in this report has been checked against an "
            "outside source that was trying to contradict it.",
        )
        return f"## Adversarial Findings\n\n*{sentence}*\n"
    if redteam is _CORRUPT or _is_stub(redteam):
        return "## Adversarial Findings\n\n*The adversarial review did not produce a readable result.*\n"

    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    summary = _as_dict(redteam.get("summary"))
    dropped = int(summary.get("rejected") or 0)
    unchecked = _as_list(redteam.get("could_not_check"))

    lines = ["## Adversarial Findings\n"]
    if review_note:
        lines.append(f"*{review_note}*\n")
        if review_changes:
            lines.append("What changed:\n\n" + "\n".join(f"- {c}" for c in review_changes) + "\n")

    def _finding_lines(f: dict[str, Any]) -> list[str]:
        out: list[str] = []
        claim = str(f.get("claim_attacked") or "").strip()
        out.append(f"\n**{_humanize_claim(claim)}**\n")
        truth = _view.checked_multiples(str(f.get("what_is_true") or "").strip(), sizing, inputs)
        out.append(f"{truth}\n")
        quote = str(f.get("evidence_quote") or "").strip()
        if quote:
            # Fenced by sentinels so the founder-text pass leaves it verbatim (see _QUOTE_OPEN).
            out.append(f"> {_QUOTE_OPEN}{quote}{_QUOTE_CLOSE}\n")
        title = str(f.get("source_title") or "").strip()
        url = str(f.get("source_url") or "").strip()
        # An internal finding is labelled, never linked. Two reasons: there is nothing to
        # click, and the founder must be able to tell the two kinds apart -- an outside
        # source contradicting a figure and the analysis contradicting ITSELF are both worth
        # knowing and are not interchangeable. Rendering the second as a citation would
        # dress an internal inconsistency up as external corroboration.
        if url == _INTERNAL_PROVENANCE:
            out.append("— from this analysis' own output, not an outside source\n")
        elif url.startswith("document:"):
            # The founder's own page: named, never linked. `quote_verified` says whether the
            # quoted sentence was found on that page -- true/false when the page had text (a
            # text layer or an OCR sidecar), null when it did not and the red team read it by
            # eye. Both states are shown; a citation nothing could check is not hidden, it is
            # labelled, so the founder knows which of the two they are looking at.
            out.append(f"— {_document_cite(url)}{_quote_verified_suffix(f.get('quote_verified'))}\n")
        elif title and url:
            out.append(f"— [{title}]({url})\n")
        elif url:
            out.append(f"— {url}\n")
        return out

    if not findings:
        lines.append(_adversarial_outcome(redteam, None) + " That is a result, not an absence of one.\n")
    else:
        lines.append(
            _adversarial_outcome(redteam, None)
            + " Each quotes the sentence it relies on. Read these before the summary above.\n"
        )
        for f in sorted(findings, key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity")), 3)):
            lines.extend(_finding_lines(f))

    # Every later review of the same analysis, in full: the first is shown so that re-running cannot
    # soften it, and the later ones are listed so that re-running cannot hide a harsher one either.
    for n, doc in later or []:
        extra = [f for f in _as_list(_as_dict(doc).get("findings")) if isinstance(f, dict)]
        lines.append(f"\n### A later review of the same analysis (review {n})\n")
        if not extra:
            lines.append("It raised no challenges.\n")
        for f in sorted(extra, key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity")), 3)):
            lines.extend(_finding_lines(f))

    if unchecked:
        lines.append("\n**Not checked**\n")
        for item in unchecked:
            lines.append(f"- {str(item).strip()}")
        lines.append("")

    if dropped:
        # Counted, never silent. A review that filed five and kept one must not read as one.
        noun = "challenge" if dropped == 1 else "challenges"
        lines.append(
            f"\n*{dropped} further {noun} could not be shown here because "
            f"{'it was' if dropped == 1 else 'they were'} incomplete or did not cite "
            f"{'its' if dropped == 1 else 'their'} evidence in a form that can be checked.*\n"
        )

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
        if not isinstance(fig, dict):
            continue
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
        "The table below shows how each market tier changes when each assumption moves between"
        " its low and high estimate. Parameters tagged *Estimate* have wider ranges"
        " because they lack external sourcing — they tend to dominate the sensitivity,"
        " which highlights exactly where better data would most strengthen the analysis.\n",
    ]
    has_approach_used = any(isinstance(s, dict) and s.get("approach_used") for s in scenarios)

    # Check whether TAM/SAM fields are present in any scenario (real sensitivity.py output)
    has_tam_sam = any(
        isinstance(s, dict) and ("tam" in s.get("low", {}) or "tam" in s.get("base", {})) for s in scenarios
    )

    if has_approach_used:
        if has_tam_sam:
            lines.append(
                "| Parameter | Approach | Confidence | Low Value | Base Value | High Value"
                " | Low TAM | Base TAM | High TAM"
                " | Low SAM | Base SAM | High SAM"
                " | Low SOM | Base SOM | High SOM | Range |"
            )
            lines.append(
                "|-----------|----------|------------|-----------|------------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------|-------|"
            )
        else:
            lines.append("| Parameter | Approach | Confidence | Low SOM | Base SOM | High SOM | Range |")
            lines.append("|-----------|----------|------------|---------|----------|----------|-------|")
    else:
        if has_tam_sam:
            lines.append(
                "| Parameter | Confidence | Low Value | Base Value | High Value"
                " | Low TAM | Base TAM | High TAM"
                " | Low SAM | Base SAM | High SAM"
                " | Low SOM | Base SOM | High SOM | Range |"
            )
            lines.append(
                "|-----------|------------|-----------|------------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------|-------|"
            )
        else:
            lines.append("| Parameter | Confidence | Low SOM | Base SOM | High SOM | Range |")
            lines.append("|-----------|------------|---------|----------|----------|-------|")

    conf_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        param = _humanize_param(s.get("parameter", "?"))
        conf = conf_labels.get(s.get("confidence", "sourced"), s.get("confidence", "sourced"))
        low_d = _as_dict(s.get("low"))
        base_d = _as_dict(s.get("base"))
        high_d = _as_dict(s.get("high"))
        low_som = _fmt_usd(low_d.get("som", 0))
        base_som = _fmt_usd(base_d.get("som", 0))
        high_som = _fmt_usd(high_d.get("som", 0))
        eff = _as_dict(s.get("effective_range"))
        range_str = f"[{eff.get('low_pct', 0)}%, +{eff.get('high_pct', 0)}%]"
        widened = " (widened)" if s.get("range_widened") else ""

        # Parameter value columns (low/base/high parameter value, not market size).
        # Format unit-aware (currency / count / percent) so all three cells are consistent.
        raw_param = s.get("parameter", "")
        base_val = s.get("base_value")
        low_val_raw = low_d.get("value")
        high_val_raw = high_d.get("value")
        if base_val is not None and isinstance(base_val, (int, float)):
            low_val_str = _fmt_param_value(raw_param, low_val_raw) if isinstance(low_val_raw, (int, float)) else "—"
            base_val_str = _fmt_param_value(raw_param, base_val)
            high_val_str = _fmt_param_value(raw_param, high_val_raw) if isinstance(high_val_raw, (int, float)) else "—"
        else:
            low_val_str = base_val_str = high_val_str = "—"

        if has_approach_used:
            approach_labels = {"top_down": "Top-down", "bottom_up": "Bottom-up"}
            approach_used = approach_labels.get(s.get("approach_used", "?"), s.get("approach_used", "?"))
            if has_tam_sam:
                low_tam = _fmt_usd(low_d.get("tam", 0))
                base_tam = _fmt_usd(base_d.get("tam", 0))
                high_tam = _fmt_usd(high_d.get("tam", 0))
                low_sam = _fmt_usd(low_d.get("sam", 0))
                base_sam = _fmt_usd(base_d.get("sam", 0))
                high_sam = _fmt_usd(high_d.get("sam", 0))
                lines.append(
                    f"| {param} | {approach_used} | {conf}"
                    f" | {low_val_str} | {base_val_str} | {high_val_str}"
                    f" | {low_tam} | {base_tam} | {high_tam}"
                    f" | {low_sam} | {base_sam} | {high_sam}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
            else:
                lines.append(
                    f"| {param} | {approach_used} | {conf}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
        else:
            if has_tam_sam:
                low_tam = _fmt_usd(low_d.get("tam", 0))
                base_tam = _fmt_usd(base_d.get("tam", 0))
                high_tam = _fmt_usd(high_d.get("tam", 0))
                low_sam = _fmt_usd(low_d.get("sam", 0))
                base_sam = _fmt_usd(base_d.get("sam", 0))
                high_sam = _fmt_usd(high_d.get("sam", 0))
                lines.append(
                    f"| {param} | {conf}"
                    f" | {low_val_str} | {base_val_str} | {high_val_str}"
                    f" | {low_tam} | {base_tam} | {high_tam}"
                    f" | {low_sam} | {base_sam} | {high_sam}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
            else:
                lines.append(f"| {param} | {conf} | {low_som} | {base_som} | {high_som} | {range_str}{widened} |")

    ranking = _as_list(sensitivity.get("sensitivity_ranking"))
    if ranking:
        tied = _widest_stressed(sensitivity)
        if len(tied) > 1:
            names = ", ".join(_humanize_param(t) for t in tied)
            lines.append(
                f"\n**Widest-stressed parameters:** {names} — these are tied at the same stress "
                "width, which follows from how confident we are in each input, not from how much "
                "the answer depends on it."
            )
        else:
            most = _humanize_param(ranking[0].get("parameter", "?"))
            lines.append(f"\n**Widest-stressed parameter:** {most}")

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
        # Source STRENGTH, not just identity. An analyst-firm figure for the exact segment and a blog
        # post about an adjacent one support a number very differently, and the sub-agent is asked to
        # judge both — so withholding them leaves the founder unable to weigh the sizing.
        tier = str(s.get("quality_tier", "") or "").strip()
        if tier:
            parts.append(_humanize_param(tier))
        match = str(s.get("segment_match", "") or "").strip()
        if match:
            parts.append(f"{_humanize_param(match)} segment match")
        line = f"- {parts[0]}"
        meta = [p for p in parts[1:]]
        if meta:
            line += f" ({', '.join(meta)})"
        if supported:
            line += f" — supports: {supported}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _resolve_headline_market_size(
    sizing: dict[str, Any] | None,
) -> tuple[dict[str, float | None], str | None]:
    """Resolve a single headline TAM/SAM/SOM triple from sizing.json for the coaching payload.

    sizing.json never carries a top-level "tam"/"sam"/"som" scalar — each figure is
    nested under an approach key (``top_down`` / ``bottom_up``) as a dict whose
    numeric value lives at ``.value`` (see market_sizing.py's ``top_down()`` /
    ``bottom_up()`` output). The coaching sub-agent is told to reason ONLY from
    coaching_payload and never refetch from disk, so this resolves the nested path
    once here rather than leaving it undone.

    Selection rule for ``approach: "both"`` mode — documented here because nothing
    upstream names a winner between the two independently-computed TAMs: prefer
    ``bottom_up`` when both approaches are present, falling back to ``top_down``
    when bottom_up is absent (top_down-only mode). This matches the skill's own
    stated methodology preference (references/tam-sam-som-methodology.md, §4 Best
    Practices, "Prefer bottom-up for accuracy") rather than inventing a new rule
    such as averaging or taking the larger/smaller figure.

    Cited by SECTION, not by line. The line number this used to carry was correct
    when written and nothing tests it, so every later edit above it would have
    rotted the citation silently.

    Returns (figures, source_approach):
      - figures: {"tam": .., "sam": .., "som": ..}, each a float or None when the
        nested value is missing/non-numeric.
      - source_approach: "bottom_up" | "top_down" | None (neither approach present,
        or sizing.json is absent/corrupt/a stub — callers already coerce those to
        a plain dict or None before reaching here).
    """
    figures: dict[str, float | None] = {"tam": None, "sam": None, "som": None}
    if not isinstance(sizing, dict):
        return figures, None

    bottom_up = _as_dict(sizing.get("bottom_up"))
    top_down = _as_dict(sizing.get("top_down"))
    if bottom_up:
        source, source_approach = bottom_up, "bottom_up"
    elif top_down:
        source, source_approach = top_down, "top_down"
    else:
        return figures, None

    for metric in ("tam", "sam", "som"):
        val = _as_dict(source.get(metric)).get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            figures[metric] = float(val)
    return figures, source_approach


def _blocked_comparisons(inputs: dict[str, Any] | None, sizing: dict[str, Any] | None) -> dict[str, Any]:
    """Which founder-stated figures could NOT be cross-checked, for the coaching sub-agent.

    A refused comparison is invisible in the rest of the payload: the figure is still there,
    `deck_reviewed` is still true, and `COMPARISON_CURRENCY_UNKNOWN` is medium so it never
    reaches `high_severity_warnings`. A coach handed only that writes as though the deck's
    number had been checked against ours.
    """
    blocked: list[str] = []
    claims = _as_dict(_as_dict(inputs).get("existing_claims"))
    for metric in ("tam", "sam", "som"):
        claim = claims.get(metric)
        if claim is None:
            continue
        comparable, is_blocked = _comparable_claim(claim, _as_dict(sizing), inputs)
        if is_blocked and comparable is None:
            blocked.append(metric.upper())
    return {
        "metrics": blocked,
        "any": bool(blocked),
        "reason": (
            "no currency was stated for those figures, so we could not tell whether they are "
            "comparable with the converted analysis"
            if blocked
            else ""
        ),
    }


def _red_team_findings(
    redteam: dict[str, Any] | None,
    sizing: Any = None,
    inputs: Any = None,
    later: list[tuple[int, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """The adversarial findings as the coach should read them, or None if the step did not run.

    None and an empty `findings` list are DIFFERENT and the coach must be able to tell them
    apart: "nobody looked" and "somebody looked and found nothing" support opposite sentences,
    and a coach handed only the empty list would write the confident one.

    Only the fields a founder-facing sentence can be built from. No internal codes.
    """
    if not _usable(redteam):
        return None
    summary = _as_dict(redteam.get("summary"))

    def _coachable(f: dict[str, Any]) -> dict[str, Any]:
        return {
            "claim_attacked": _humanize_claim(str(f.get("claim_attacked") or "").strip()),
            "what_is_true": _view.checked_multiples(str(f.get("what_is_true") or "").strip(), sizing, inputs),
            "evidence_quote": str(f.get("evidence_quote") or "").strip(),
            "source_url": str(f.get("source_url") or "").strip(),
            "source_title": str(f.get("source_title") or "").strip(),
            "severity": f.get("severity"),
        }

    return {
        # Later reviews of the same analysis, in full: the page lists them, so the coach sees them.
        "later_reviews": [
            {
                "review": n,
                "findings": [_coachable(f) for f in _as_list(_as_dict(doc).get("findings")) if isinstance(f, dict)],
            }
            for n, doc in later or []
        ],
        "findings": [
            {
                # HUMANIZED, like the renderer does it. `claim_attacked` is free text and is
                # routinely a bare parameter name -- the agent body invites exactly that ("in the
                # analysis's own words or its parameter name"). The coach echoes this payload into
                # founder-facing prose, so passing it raw is the defect the fleet fixed once in
                # cap-table, reintroduced one field over.
                "claim_attacked": _humanize_claim(str(f.get("claim_attacked") or "").strip()),
                # Checked like every other surface: the coach repeated an unsupported "5x" as a fact
                # about the founder's own build.
                "what_is_true": _view.checked_multiples(str(f.get("what_is_true") or "").strip(), sizing, inputs),
                "evidence_quote": str(f.get("evidence_quote") or "").strip(),
                "source_url": str(f.get("source_url") or "").strip(),
                "source_title": str(f.get("source_title") or "").strip(),
                "severity": f.get("severity"),
            }
            for f in _as_list(redteam.get("findings"))
            if isinstance(f, dict)
        ],
        "dropped": int(summary.get("rejected") or 0),
        "unchecked": len(_as_list(redteam.get("could_not_check"))),
        "could_not_check": [str(c).strip() for c in _as_list(redteam.get("could_not_check"))],
        # Documents the founder supplied that the review never opened, by filename. A coach told
        # only the findings would write as though every page had been checked.
        "unread": [str(x).strip() for x in _as_list(redteam.get("sources_unread")) if str(x).strip()],
    }


def _gap_message(comparison: dict[str, Any], metric: str) -> str:
    """The discrepancy warning: the factor between the two recorded figures, or the producer's
    percentage when the figures are not recorded (an artifact from before they were)."""
    sentence = _params.gap_sentence(metric, comparison.get(f"top_down_{metric}"), comparison.get(f"bottom_up_{metric}"))
    if sentence is not None:
        return sentence.rstrip(".")
    return (
        f"Top-down and bottom-up {metric.upper()} differ by "
        f"{_params.fmt_delta(comparison[f'{metric}_delta_pct'])} (>30%)"
    )


def _payload_gap(comparison: dict[str, Any], metric: str) -> str | None:
    if f"{metric}_delta_pct" not in comparison:
        return None
    return _params.gap_sentence(
        metric, comparison.get(f"top_down_{metric}"), comparison.get(f"bottom_up_{metric}")
    ) or (str(comparison.get("note" if metric == "tam" else f"{metric}_note") or "") or None)  # TAM's is unprefixed


def _approach_comparison(
    sizing: dict[str, Any] | None, validation: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The two-approach comparison as the coach should read it, or None on a single-approach run.

    Carries the three deltas, the pipeline's own caveat, and what the builds demonstrably share --
    each share as a ready-to-quote sentence and nothing else. The caveat is stated once here
    rather than per metric: it is one fact about the run.
    """
    comparison = _as_dict(sizing.get("comparison")) if isinstance(sizing, dict) else {}
    if not comparison or "tam_delta_pct" not in comparison:
        return None
    shared = _shared_input_values(sizing, validation)
    return {
        # The gap as a sentence with its factor, never the percentage: measured against the two
        # figures' average, a gap under 200% was coached as a small multiple on a far wider pair.
        "tam_gap": _payload_gap(comparison, "tam"),
        "sam_gap": _payload_gap(comparison, "sam"),
        "som_gap": _payload_gap(comparison, "som"),
        "shared_inputs": [{"metric": s["metric"], "detail": s["detail"]} for s in shared],
        # The same split the report makes: "cannot tell" is only true while nothing was seen.
        "caveat": (
            "Closeness is not confirmation: where the inputs are itemized the pipeline can see "
            "what the two builds share, and shared_inputs lists it."
            if shared
            else "Closeness is not confirmation: the pipeline cannot tell whether the two builds "
            "rest on the same underlying figures."
        ),
    }


def _emit_coaching_payload(
    inputs: dict[str, Any],
    methodology: dict[str, Any],
    checklist: dict[str, Any],
    validation_warnings: list[dict[str, str]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
    sizing: dict[str, Any] | None = None,
    currency: str = "USD",
    validation: dict[str, Any] | None = None,
    red_team: dict[str, Any] | None = None,
    review_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the coaching_payload for market-sizing (schema_version v0.7.0-market-sizing).

    Read from existing artifacts; do not fabricate fields.
    market-sizing's checklist has only pass/fail/not_applicable (no warn status),
    so warned_items is always an explicit empty list for cross-skill schema consistency.

    tam/sam/som/currency/market_size_approach are resolved via
    _resolve_headline_market_size — see that function for the nested-path
    resolution and the "both"-mode selection rule. currency is never converted
    (a conversion happens only when a money input declares a different source
    currency AND a rate is supplied); otherwise it is only a label on
    the numbers already computed by market_sizing.py.
    """
    market_size, market_size_approach = _resolve_headline_market_size(sizing)
    summary = _as_dict(checklist.get("summary"))

    # Derive a confidence tier from the checklist score_pct so the Context B
    # agent reads it directly from coaching_payload (no fabrication from
    # nonexistent sizing.json/checklist.json fields).
    confidence: str | None = None
    score_pct = summary.get("score_pct")
    if isinstance(score_pct, (int, float)):
        if score_pct >= 85:
            confidence = "high"
        elif score_pct >= 60:
            confidence = "medium"
        else:
            confidence = "low"

    # Compute deck_coverage from inputs.existing_claims (canonical keys only).
    # Non-canonical keys do NOT count here — EXISTING_CLAIMS_SHAPE warning is
    # the dedicated shape signal. Only meaningful when the agent populated at
    # least one canonical figure (proves the deck was reviewed and at least one
    # TAM/SAM/SOM was stated).
    existing_claims = _as_dict(inputs.get("existing_claims"))
    canonical = ("tam", "sam", "som")
    any_stated = any(existing_claims.get(m) is not None for m in canonical)
    deck_coverage: dict[str, Any] | None = None
    if any_stated:
        deck_coverage = {
            "deck_reviewed": True,
            "stated": [m for m in canonical if existing_claims.get(m) is not None],
            "missing": [m for m in canonical if existing_claims.get(m) is None],
        }

    return {
        "schema_version": "v0.7.0-market-sizing",
        "summary": {
            "score_pct": summary.get("score_pct"),
            # The band (how good) and the boolean (is anything outstanding) are two facts,
            # and the coach needs both. `strong` is compatible with an open item — 21 of 22
            # is 95.5% — so a coach given only the band cannot tell the founder there is
            # something left to do, and one given only the boolean reads 21/22 and 1/22 the
            # same way.
            "overall_status": summary.get("overall_status"),
            "all_pass": summary.get("all_pass"),
            "total": summary.get("total"),
            "pass": summary.get("pass"),
            "fail": summary.get("fail"),
            "not_applicable": summary.get("not_applicable"),
        },
        "failed_items": summary.get("failed_items", []),
        "warned_items": [],  # market-sizing has no warn status; explicit empty for schema parity
        # TOP-LEVEL. `COMPARISON_CURRENCY_UNKNOWN` is medium, and `high_severity_warnings` filters
        # to high, so the coach was told `deck_reviewed: true` with nothing saying the cross-check
        # had been refused -- and wrote as though the deck's figure had been checked. Promoting the
        # warning to high would have carried it, but severity drives `accepted_warnings`, so that
        # is a different change wearing this one's clothes.
        "comparison_blocked": _blocked_comparisons(inputs, sizing),
        # The two-approach comparison. Absent from this payload, Context B called a 9.4% SAM gap
        # "two independent chains ... the strongest methodological result" -- one month after the
        # closeness-is-not-confirmation rule landed in that same agent body, which it had in front
        # of it. The same commentary got the TAM identity RIGHT, because a checklist note surfaced
        # it. The rule was present and did not work; the data was absent, and the one thing it did
        # carry was used correctly. So: data, not another prohibition.
        #
        # `kind` and `code` are dropped. The coach echoes this into founder-facing commentary, and
        # a raw internal id in that payload is a defect the fleet has already fixed once.
        "approach_comparison": _approach_comparison(sizing, validation),
        # What an outside look turned up, with its sources. `null` when the step did not run --
        # which the coach must be able to tell apart from "it ran and found nothing", because
        # those are opposite facts about the report it is writing commentary on.
        "red_team_findings": _red_team_findings(red_team, sizing, inputs, _as_dict(review_facts).get("later")),
        # How many times the outside review ran and what the page says about it -- computed from the
        # review copies, never from a model-written approval. The coach had no re-run signal otherwise.
        "review_rounds": {
            "count": int(_as_dict(review_facts).get("rounds") or 0),
            "shown": _as_dict(review_facts).get("round_shown"),
            "note": _view.review_note(_as_dict(review_facts)),
            "changes": _view.review_changes(_as_dict(review_facts), validation, currency),
        },
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
        "company_name": inputs.get("company_name"),
        "methodology": methodology.get("approach_chosen"),
        "confidence": confidence,  # derived from checklist score_pct; null if unavailable
        "deck_coverage": deck_coverage,  # nullable; additive in v0.4.2-market-sizing
        "tam": market_size["tam"],
        "sam": market_size["sam"],
        "som": market_size["som"],
        # The figures AS RENDERED, so the closing message copies a string rather than formatting a
        # number -- a script that formats is a script that can be asked to compute. Null when the
        # figure is.
        "tam_display": _fmt_usd(market_size["tam"]) if market_size["tam"] is not None else None,
        "sam_display": _fmt_usd(market_size["sam"]) if market_size["sam"] is not None else None,
        "som_display": _fmt_usd(market_size["som"]) if market_size["som"] is not None else None,
        "self_check_line": _self_check_line(checklist) if _usable(checklist) else None,
        "currency": currency,
        "market_size_approach": market_size_approach,  # "bottom_up" | "top_down" | null
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
    }


class RevisionOwed(Exception):
    """With a run ledger, Step 6d's unasked question is a question to ask, not a disclosure."""

    def __init__(self, parameters: list[str]) -> None:
        super().__init__(", ".join(parameters))
        self.parameters = parameters


def compose(
    dir_path: str, report_path: str | None = None, gate_view: dict[str, Any] | None = None, no_ask: bool = False
) -> dict[str, Any]:
    """Render inside one currency scope: the default is back to USD when this returns or raises.

    `gate_view` is the run ledger's answers (`_ms_gates.answers_view`), None for a run without one: with it,
    "Your Answers" is read from the ledger, and an unasked revision question raises RevisionOwed. `no_ask`: the
    run's request said not to ask (read from the ledger), so a skip the founder declined is refused."""
    with _view.render_scope():
        return _compose(dir_path, report_path, gate_view, no_ask)


def _compose(
    dir_path: str, report_path: str | None = None, gate_view: dict[str, Any] | None = None, no_ask: bool = False
) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    # Load all artifacts
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    # This run's id, ONE value for the resolver, the sizing check, the gate, the hand-off audit and the
    # revision check, so they agree on whose review it is (rule in `_redteam_core.primary_run_id`).
    _rt_run_id = _redteam_copy.primary_run_id_in(dir_path, artifacts, REQUIRED_ARTIFACTS)

    # The review every reader below sees -- the report, the verdict, the gate, the coaching payload
    # -- is its append-only copy, never `redteam.json` as it now stands (see _redteam_copy).
    _rt_shown, _rt_codes, _rt_facts = _redteam_copy.resolve(
        dir_path,
        _rt_run_id,
        artifacts.get("redteam.json"),
        artifacts.get("methodology.json"),
        same_as_now=_view.review_matcher(
            artifacts.get("sizing.json") if isinstance(artifacts.get("sizing.json"), dict) else {},
            artifacts.get("validation.json"),
            artifacts.get("inputs.json"),
        ),
    )
    if _rt_facts["rounds"]:
        artifacts["redteam.json"] = _rt_shown

    # The sizing every reader below sees has been re-checked: against the research record it was
    # resolved from, and against its own math. An edited sizing is replaced by the recomputation, so no
    # section, verdict or payload can render a figure the inputs do not give.
    _sz_render, _sz_codes = _view.sizing_integrity(
        dir_path,
        _rt_run_id,
        artifacts.get("sizing.json"),
        artifacts.get("validation.json"),
        artifacts.get("inputs.json"),
        reviewed=bool(_rt_facts["rounds"]),
        review_facts=_rt_facts,
        methodology=artifacts.get("methodology.json"),
    )
    if _sz_render is not None:
        artifacts["sizing.json"] = _sz_render

    # REQUIRED only, on both sides. An OPTIONAL artifact that is absent is not missing -- it is
    # optional, and reporting it as missing makes a complete analysis look incomplete. Latent
    # until market-sizing had its first optional artifact; deck-review hit it first and the
    # comment there says the same thing.
    artifacts_found = [n for n in REQUIRED_ARTIFACTS if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in REQUIRED_ARTIFACTS if artifacts[n] is None]

    # THE ADVERSARIAL-REVIEW GATE. Either a fresh findings artifact exists, or the decision not to
    # run one was RECORDED. Silence is not a third option.
    #
    # This is a refusal, not a warning, and the reason is measured rather than argued: the step
    # shipped as "optional" with a low-severity disclosure as its only downstream consumer, and on
    # a live paid run it was skipped outright. This repo had already written that lesson down for
    # deck-review's numeric chain -- a step whose only consumer is a warning gets skipped in
    # silence -- so the gate belongs on the producer of the deliverable, which is here.
    #
    # Severity could not do this job: Step 7 runs compose without --strict, so even `high` halts
    # nothing. Only a non-zero exit reaches SKILL.md's documented stop-and-report branch.
    _rt_state, _rt_reason, _rt_detail = _red_team_state(
        artifacts, artifacts.get("methodology.json"), _rt_run_id, no_ask
    )
    if _rt_state == "no_ask_declined":
        # Its detail names the reasons on offer itself: the closed list carries the very reason refused.
        _fail_compose(
            {
                "code": "NO_ASK_FOUNDER_DECLINED",
                "validation": {"status": "invalid", "code": "NO_ASK_FOUNDER_DECLINED", "errors": [f"{_rt_detail}."]},
                "report_markdown": "",
            },
            report_path,
        )
    if _rt_state == "ungated":
        _detail = _rt_detail or "no adversarial review was run for this run"
        # The closed list of skip reasons is printed only where a skip is a remedy on offer; a review of
        # another run is answered with a review of this one, never with a skip.
        _known = ", ".join(sorted(_RED_TEAM_SKIP_REASONS))
        _suffix = f" (one of: {_known})" if "red_team_skipped" in _detail else ""
        _fail_compose(
            {
                "validation": {
                    "status": "invalid",
                    "errors": [f"{_detail}{_suffix}."],
                },
                "report_markdown": "",
            },
            report_path,
        )

    # Run validation
    warnings = validate_artifacts(artifacts, dir_path)
    _bypassed_steps = _handoff_bypassed(dir_path, _rt_run_id, artifacts)
    if _bypassed_steps:
        warnings.append(_warn("HANDOFF_BYPASSED", _handoff_audit().founder_message(_bypassed_steps)))
    _unoffered = _revision_not_offered(
        dir_path,
        _rt_run_id,
        artifacts.get("redteam.json"),
        rounds=int(_rt_facts.get("rounds") or 0),
    )
    if _unoffered and gate_view is not None:
        raise RevisionOwed(_unoffered)
    if _unoffered:
        _named = ", ".join(_humanize_param(p) for p in _unoffered)
        warnings.append(
            _warn(
                "REVISION_NOT_OFFERED",
                f"The outside review raised a high-severity challenge to {_named}, and there is no record that "
                "you were offered the one revision round: changing the challenged inputs and having the analysis "
                "reviewed once more. The challenges are shown as they stand, and you can still ask for that revision.",
            )
        )
    warnings.extend(_warn(code, message) for code, message in _rt_codes)
    warnings.extend(_warn(code, message) for code, message in _sz_codes)
    warnings.extend(
        _warn(code, message)
        for code, message in _view.unchecked_sizing(
            artifacts.get("sizing.json"),
            artifacts.get("validation.json"),
            artifacts.get("inputs.json"),
            review_facts=_rt_facts,
        )
    )
    warnings.extend(
        _warn(code, message)
        for code, message in _view.downstream_staleness(
            artifacts.get("sizing.json"),
            artifacts.get("sensitivity.json"),
            artifacts.get("checklist.json"),
            artifacts.get("inputs.json"),
        )
    )
    if "inputs_at_review" in _rt_facts:
        # Keyed on the FIRST review only, and stated as a fact: a later review could otherwise clear it
        # by being re-dispatched, and the founder's own figure is the one thing they must be told about.
        for _field, _then, _now in _redteam_copy.rewritten_inputs(
            _rt_facts["inputs_at_review"], artifacts.get("inputs.json")
        ):
            warnings.append(
                _warn(
                    "FOUNDER_INPUT_REWRITTEN",
                    f"Your {_humanize_param(_field)} was {_stated_as(_field, _then)} when the outside review "
                    f"first ran and is {_stated_as(_field, _now)} now. If you chose the new figure, nothing "
                    f"needs to change; if you did not, it should go back to the one you gave.",
                )
            )

    # Apply accepted_warnings from methodology (medium-severity only, instance-scoped)
    methodology_art = artifacts.get("methodology.json")
    if _usable(methodology_art):
        acceptances: list[dict[str, str]] = []
        for aw in _as_list(methodology_art.get("accepted_warnings")):
            if not isinstance(aw, dict):
                print("Warning: accepted_warnings entry is not an object — skipped", file=sys.stderr)
                continue
            code = aw.get("code", "")
            match_str = aw.get("match", "")
            if not code or not match_str:
                print("Warning: accepted_warnings entry missing 'code' or 'match' — skipped", file=sys.stderr)
                continue
            reason = aw.get("reason", "")
            if not isinstance(reason, str) or not reason.strip():
                print(f"Warning: accepted_warnings entry for '{code}' missing 'reason' — skipped", file=sys.stderr)
                continue
            if code in _UNACCEPTABLE_MEDIUM:
                print(
                    f"Warning: cannot accept '{code}' -- it discloses how this run was carried out and "
                    "stays in the report; ignored",
                    file=sys.stderr,
                )
            elif code in WARNING_SEVERITY and WARNING_SEVERITY[code] in ACCEPTIBLE_SEVERITIES:
                acceptances.append(
                    {
                        "code": code,
                        "reason": reason,
                        "match": match_str,
                    }
                )
            elif code in WARNING_SEVERITY:
                # Name the actual severity. This branch is the catch-all for every non-medium
                # code, so it called a low one "high-severity" — reachable now that a producer
                # code (FX_UNSOURCED, low) forwards through here, and actively misleading:
                # only medium is acceptable, and a low warning has nothing to clear.
                _sev = WARNING_SEVERITY[code]
                print(
                    f"Warning: cannot accept {_sev}-severity code '{code}' — "
                    f"only medium-severity warnings can be accepted; ignored",
                    file=sys.stderr,
                )
        for w in warnings:
            for acc in acceptances:
                if w["code"] == acc["code"] and acc["match"].lower() in w.get("message", "").lower():
                    w["severity"] = "acknowledged"
                    w["message"] += f" [Accepted: {acc['reason']}]"
                    break

    # Assemble report — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inputs = _render_safe(artifacts.get("inputs.json"))
    methodology = _render_safe(artifacts.get("methodology.json"))
    validation_data = _render_safe(artifacts.get("validation.json"))
    sizing = _render_safe(artifacts.get("sizing.json"))
    sensitivity = _render_safe(artifacts.get("sensitivity.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))

    # Resolve the analysis currency BEFORE any section renders — every money
    # figure in the report goes through _fmt_usd, which reads this.
    # inputs.json is checked FIRST: it is where the founder's stated currency is
    # recorded at intake, so it outranks whatever the producer defaulted to. A
    # disagreement between the two is separately reported as CURRENCY_MISMATCH.
    _set_currency(_resolve_currency(inputs, sizing, methodology))

    # Compute provenance
    provenance_data: dict[str, dict[str, Any]] | None = None
    if _usable(sizing) and not _is_stub(sizing):
        provenance_data, _ = _compute_provenance(sizing, validation_data, inputs)

    # Render every section EXCEPT Warnings first. The marker pre-scan and the
    # MARKER_COLLISION append must run before the Warnings section is rendered
    # and before status is computed, so that a marker collision is reflected in
    # both validation.status and the report's Warnings section.
    _WARNINGS_PLACEHOLDER = "\x00__WARNINGS_SECTION__\x00"
    sections = [
        _section_title_provenance(inputs, sizing),
        _section_executive_summary(
            sizing,
            sensitivity,
            provenance_data,
            validation_data,
            inputs,
            _render_safe(artifacts.get("redteam.json")),
            checklist,
            _rt_reason,
            bool(_bypassed_steps),
        ),
        _section_analysis_checklist(checklist, artifacts_found),
        _section_methodology(methodology),
        _section_definitions(),
        _section_sizing_table(sizing, provenance_data, validation_data),
        _section_deck_claims_narrative(inputs),
        _section_assumptions(validation_data, sizing),
        _section_adversarial(
            _render_safe(artifacts.get("redteam.json")),
            _rt_reason,
            _view.review_note(_rt_facts),
            _view.review_changes(_rt_facts, validation_data, _view._CURRENCY),
            sizing,
            inputs,
            _rt_facts.get("later"),
        ),
        _section_your_answers(methodology, inputs, dir_path, gate_view),
        _section_validation(validation_data),
        _section_sensitivity(sensitivity),
        _WARNINGS_PLACEHOLDER,
        _section_sources(validation_data),
    ]

    body_without_warnings = "\n".join(s for s in sections if s != _WARNINGS_PLACEHOLDER)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan: check assembled body BEFORE appending the marker (otherwise we
    # always find our own emission). Agent post-Edit verification uses the
    # EXACT uuid (per-run), so substring collisions with body content are
    # informational only — but worth flagging so authors can sanitize.
    if "<!-- COACHING_INSERTION_POINT_" in body_without_warnings:
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

    # Determine status AFTER all warnings (including MARKER_COLLISION) are known.
    status = "clean" if not warnings else "warnings"

    # Splice the Warnings section in now that the warnings list is final.
    report_markdown = "\n".join(_section_warnings(warnings) if s == _WARNINGS_PLACEHOLDER else s for s in sections)

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
    )

    # The founder's filenames as the founder named them: on the cloud lane an attachment carries a
    # platform `<8-hex>-` prefix. One pass over the finished markdown reaches every section (the
    # verdict, citations, "not checked", both warnings that name an unread document) and nothing
    # structured -- the coaching payload below is built from the artifacts and keeps the raw names.
    # Lift the red-team quotes out BEFORE any rewriting pass (see _QUOTE_OPEN).
    _quotes: list[str] = []

    def _lift(m: re.Match[str]) -> str:
        _quotes.append(m.group(1))
        return f"\ue002{len(_quotes) - 1}\ue003"

    report_markdown = _QUOTE_RE.sub(_lift, report_markdown)

    _upload_display = _upload_names.for_redteam(_render_safe(artifacts.get("redteam.json")))
    report_markdown = _upload_names.humanize(report_markdown, _upload_display)

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
                    f"the report names the internal file '{_fn}' — remove it from the label or note you "
                    f"wrote that carries it, and recompose. The outside review is worded when it is "
                    f"produced and is never edited",
                )
            )
        # A token inside a quote is the source's own word. Same code, different remedy: a reworded
        # quote is a false one, so the only thing to do is know it is there.
        _in_quotes = _ft.scan("\n".join(_quotes), extra_keep=frozenset(WARNING_SEVERITY))
        for _tok in [*_in_quotes["enums"], *_in_quotes["filenames"]]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"a quoted source sentence contains '{_tok}'; it is shown verbatim on purpose, "
                    f"because a reworded quote is a false one — do not edit it",
                )
            )

    # Put the quotes back, verbatim, with every line of a multi-line quote inside the blockquote.
    report_markdown = _QUOTE_SLOT_RE.sub(lambda m: _quotes[int(m.group(1))].replace("\n", "\n> "), report_markdown)

    # Stderr summary
    # REQUIRED in the denominator, matching `artifacts_missing`. Counting the optional one made
    # a complete analysis announce itself as 6/7.
    print(f"Artifacts found: {len(artifacts_found)}/{len(REQUIRED_ARTIFACTS)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        print(f"Warnings: {len(high)} high, {len(medium)} medium", file=sys.stderr)
        for w in warnings:
            print(f"  [{w['severity'].upper()}] {w['code']}: {w['message']}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)

    # v0.4.2 Mitigation 2: structured coaching payload for Context B agent.
    # Use the same uuid marker generated above as the single source of truth.
    resolved_report_path = report_path or os.path.join(os.path.abspath(dir_path), "report.md")
    coaching_payload = _emit_coaching_payload(
        inputs=_as_dict(inputs),
        methodology=_as_dict(methodology),
        checklist=_as_dict(checklist),
        validation_warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
        sizing=sizing,
        currency=_view._CURRENCY,
        validation=_as_dict(artifacts.get("validation.json")) or None,
        red_team=_render_safe(artifacts.get("redteam.json")),
        review_facts=_rt_facts,
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
        # The same paragraph the report opens with; closing_message.py prints it in chat.
        "verdict": _upload_names.humanize(
            _verdict_paragraph(
                sizing,
                provenance_data,
                validation_data,
                inputs,
                _render_safe(artifacts.get("redteam.json")),
                checklist,
                _rt_reason,
                bool(_bypassed_steps),
            ),
            _upload_display,
        ),
    }

    if provenance_data:
        result["provenance"] = provenance_data

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose market sizing report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--strict", action="store_true", help="Exit 1 on high/medium-severity warnings (CI mode)")
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
    # THE RUN'S GATE LEDGER, when it has one: the questions the analysis rests on must be recorded, an open
    # question refuses the report, and "Your Answers" is read from the ledger. With no `run_ref.json` none of
    # this runs.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _ms_gates  # noqa: PLC0415

    run_id = _ms_gates.run_id_of(args.dir)
    ledger = _ms_gates.open_ledger_or_exit(args.dir, run_id)
    gate_view = None
    if ledger is not None:
        _ms_gates.require_or_exit(
            args.dir,
            run_id,
            [
                *_ms_gates.two_figure_keys(args.dir),
                _ms_gates.METHODOLOGY_GATE,
                *_ms_gates.pct_scale_keys(args.dir),
            ],
            by="compose_report.py",
        )
        gate_view = _ms_gates.answers_view(args.dir) or {}
    # The request said not to ask: read once from the ledger, for the review gate's founder_declined refusal.
    quiet = ledger is not None and bool(ledger[0].no_ask(ledger[0].load_ledger(ledger[1])))
    try:
        result = compose(args.dir, report_path=report_path, gate_view=gate_view, no_ask=quiet)
    except RevisionOwed as e:
        _ms_gates.revision_owed(args.dir, run_id, e.parameters)
        raise
    if ledger is not None:
        _ms_gates.refuse_open_gates(ledger)
        status = sys.modules["_run_status"].load_status(ledger[1]) or {}
        result["disclosures"] = list(status.get("disclosures") or [])

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

    if ledger is not None:
        _ms_gates.coaching_pending(ledger)

    if args.strict:
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] in ("high", "medium")]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    import _compose_result
    import _ms_gates

    with _compose_result.recording(skill="market-sizing", run_id_of=_ms_gates.run_id_of):
        main()
