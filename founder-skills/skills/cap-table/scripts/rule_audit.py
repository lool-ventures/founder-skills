#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Two-phase rule audit (the gating contract every math producer consumes).

Per design doc §9 Step 4.5 / Step 6:
  * --phase=pre_math: walks the rule pack against inputs + instruments +
    cap_state + each scenario's params; emits the **gating block** for
    every rule. Math producers read this to decide rule applicability.
  * --phase=post_math: re-reads the gating block from the existing
    rule_audit.json at --output; composes watchlist + counsel-review items.
    Math is unchanged by this phase. Only --run-id and --output are required;
    --inputs/--instruments/--cap-state/--scenarios are NOT consumed by
    post_math (the gating block from pre_math contains everything needed).

Per rev17 P1-1 (scope-aware apply contract):
  * scope=not_applicable → apply on applies_when_matched.
  * scope=legal_tax_applicability → apply when status ∈
    {in_window, date_tracking_only} AND applies_when_matched.
  * scope=benchmark_freshness → apply on applies_when_matched regardless
    of status; freshness is annotation only.

Status taxonomy (5 mutually exclusive + 2 boolean overlays):
  in_window | pre_effective | expired | date_tracking_only |
  missing_event_date | not_date_sensitive
  + near_end_flag, near_start_flag (orthogonal)

Per the §6 alias contract: per-instrument fields have NO engagement-level
fallback. Three shapes: per-instrument | per-scenario | engagement-scoped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _artifact_io  # type: ignore[import-not-found]  # noqa: E402
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)
_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cap-table-rules.json",
)

# Per design §6 alias table — three shapes with no cross-shape fallback.
PER_INSTRUMENT_FIELDS = {
    "safe_investment_date": ("instruments.safes", "issuance_date"),
    "grant_date": ("instruments.option_grants", "grant_date"),
    "stock_issue_date": ("cap_state.preferred_series", "issuance_date"),
}
PER_SCENARIO_FIELDS = {
    "transaction_event_date": "transaction_event_date",
}
ENGAGEMENT_FIELDS = {
    "restructuring_effective_date",
    "restructuring_approval_date",
    "filing_date",
    "tax_position_date",
    "flip_closing_date",
    "benchmark_reference_date",
}

# Default near-edge thresholds (overridable per-rule via rule pack)
DEFAULT_NEAR_START_DAYS = 30
DEFAULT_NEAR_END_DAYS = 90


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _classify_scope(rule: dict[str, Any]) -> str:
    """Classify rule into one of {legal_tax_applicability, benchmark_freshness, not_applicable}.

    Per rev17: benchmark_freshness when event_date_field is
    benchmark_reference_date; not_applicable when no date_window;
    otherwise legal_tax_applicability.
    """
    dw = rule.get("date_window")
    if not dw:
        return "not_applicable"
    if dw.get("event_date_field") == "benchmark_reference_date":
        return "benchmark_freshness"
    return "legal_tax_applicability"


def _evaluate_date_status(
    event_date_value: date | None,
    start: date | None,
    end: date | None,
    *,
    near_start_days: int,
    near_end_days: int,
    today: date | None = None,
) -> tuple[str, bool, bool]:
    """Compute status + near-edge overlays.

    Returns (status, near_end_flag, near_start_flag).

    status is one of: in_window | pre_effective | expired | missing_event_date.
    date_tracking_only is handled at the caller (when start AND end are both null).
    """
    if event_date_value is None:
        return "missing_event_date", False, False

    # Near-edge proximity is measured from the audit reference date (`today`,
    # defaulting to the event_date when no override is supplied) — it answers
    # "is this rule's window about to open/close relative to when we're
    # auditing?", which is what the watchlist consumes. The --today CLI override
    # exists so tests can pin the reference date deterministically.
    reference = today if today is not None else event_date_value

    # Window-bounded
    if start is not None and event_date_value < start:
        # pre_effective; check near_start
        delta_start = (start - reference).days
        near_start = 0 <= delta_start <= near_start_days
        return "pre_effective", False, near_start

    if end is not None and event_date_value > end:
        return "expired", False, False

    # in_window — check near_end if end exists
    near_end = False
    if end is not None:
        delta_end = (end - reference).days
        near_end = 0 <= delta_end <= near_end_days

    return "in_window", near_end, False


def _evaluate_freshness(
    benchmark_reference: date | None,
    start: date | None,
    end: date | None,
) -> str:
    """Per rev17: benchmark_freshness rules use freshness_status, not status."""
    if benchmark_reference is None:
        return "unknown"
    if start is not None and benchmark_reference < start:
        return "stale"
    if end is not None and benchmark_reference > end:
        return "stale"
    return "fresh"


def _resolve_event_date(
    rule: dict[str, Any],
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    scenario: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Resolve event date(s) per the shape-aware lookup contract.

    Returns a list of (instance_type, instance_id, instance_json_pointer,
    event_date_value, event_date_field) tuples — one per instance the rule
    applies to. For per-instrument fields, returns one entry per instrument.
    For engagement-scoped fields, returns a single entry.

    QSBS is date-sensitive against the POST-FLIP Delaware C-corp share
    issuance date, not the pre-flip Israeli issuance date. When in flip mode
    (mode=flip_focused or scenario.type=flip or cross-border structure),
    rewrite the QSBS rule's event_date_field from `stock_issue_date` →
    `flip_closing_date` so the rule gates against the correct OBBBA cutoff.
    """
    dw = rule.get("date_window") or {}
    field = dw.get("event_date_field")
    rid = rule.get("rule_id", "")

    # In flip mode, gate QSBS on flip_closing_date instead of stock_issue_date
    if rid == "delaware_cross_border.qsbs_date_sensitive":
        is_flip = (
            inputs.get("mode") == "flip_focused"
            or _is_cross_border(inputs)
            or (scenario is not None and scenario.get("type") == "flip")
        )
        if is_flip:
            field = "flip_closing_date"
    if not field:
        return [
            {
                "instance_type": "global",
                "instance_id": None,
                "instance_json_pointer": None,
                "event_date_value": None,
                "event_date_field": None,
            }
        ]

    if field in PER_INSTRUMENT_FIELDS:
        scope_obj, attr = PER_INSTRUMENT_FIELDS[field]
        # Walk the source collection
        if scope_obj == "instruments.safes":
            items = instruments.get("safes", [])
            it = "safe"
            ptr_prefix = "/instruments/safes"
        elif scope_obj == "instruments.option_grants":
            items = instruments.get("option_grants", [])
            it = "option_grant"
            ptr_prefix = "/instruments/option_grants"
        elif scope_obj == "cap_state.preferred_series":
            items = cap_state.get("preferred_series", [])
            it = "preferred_series"
            ptr_prefix = "/cap_state/preferred_series"
        else:
            items = []
            it = "global"
            ptr_prefix = ""

        if not items:
            return []  # rule has no instances to apply to
        out = []
        for i, item in enumerate(items):
            out.append(
                {
                    "instance_type": it,
                    "instance_id": item.get("id", item.get("series_id", f"{it}_{i}")),
                    "instance_json_pointer": f"{ptr_prefix}/{i}/{attr}",
                    "event_date_value": item.get(attr),
                    "event_date_field": field,
                }
            )
        return out

    if field in PER_SCENARIO_FIELDS:
        if scenario is None:
            return []  # rule does not apply outside scenarios
        params = scenario.get("parameters", {}) or {}
        return [
            {
                "instance_type": "scenario",
                "instance_id": scenario.get("scenario_id"),
                "instance_json_pointer": f"/scenarios/{scenario.get('scenario_id')}/parameters/{field}",
                "event_date_value": params.get(field),
                "event_date_field": field,
            }
        ]

    if field in ENGAGEMENT_FIELDS:
        event_dates = inputs.get("event_dates") or {}
        return [
            {
                "instance_type": "engagement",
                "instance_id": None,
                "instance_json_pointer": f"/inputs/event_dates/{field}",
                "event_date_value": event_dates.get(field),
                "event_date_field": field,
            }
        ]

    # Unknown field — caller should treat as fatal
    return [
        {
            "instance_type": "global",
            "instance_id": None,
            "instance_json_pointer": None,
            "event_date_value": None,
            "event_date_field": field,
            "_unknown_field": True,
        }
    ]


# ---------------------------------------------------------------------------
# Engagement-context predicates — building blocks for per-rule matchers
# ---------------------------------------------------------------------------


def _structure_includes_israel(inputs: dict[str, Any]) -> bool:
    structure = (inputs.get("jurisdiction") or {}).get("structure", "")
    return structure in {"israeli", "delaware_with_israeli_sub", "mid_flip"}


def _structure_includes_delaware(inputs: dict[str, Any]) -> bool:
    structure = (inputs.get("jurisdiction") or {}).get("structure", "")
    return structure in {"delaware", "delaware_with_israeli_sub", "mid_flip"}


#: Stages the early-stage benchmark sets are drawn from. A benchmark labelled for
#: one stage is not evidence about another, so a rule scoped to these must not
#: fire outside them.
_EARLY_STAGES = {"pre-seed", "pre_seed", "preseed", "seed"}


def _declared_stage(inputs: dict[str, Any]) -> str | None:
    """The founder-declared funding stage, or None when it was never recorded.

    Read from `metadata.stage` with a top-level `stage` fallback; both are
    permitted by the open inputs schema. Returns None rather than a default —
    "we were not told" and "they are pre-seed" must stay distinguishable, since
    the whole point of the caller below is to not assert one from the other.
    """
    for candidate in ((inputs.get("metadata") or {}).get("stage"), inputs.get("stage")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return None


def _israel_early_stage_context(inputs: dict[str, Any]) -> bool:
    """Israeli structure AND a declared early stage.

    Geography alone used to carry this, which let a pre-seed/seed benchmark set
    fire for an Israeli company at any stage — a Series B founder shown pre-seed
    ranges as if they applied. Unknown stage does NOT fire: this is benchmark
    context, so withholding it costs a note, while asserting it at the wrong
    stage misinforms.
    """
    return _structure_includes_israel(inputs) and _declared_stage(inputs) in _EARLY_STAGES


def _is_cross_border(inputs: dict[str, Any]) -> bool:
    structure = (inputs.get("jurisdiction") or {}).get("structure", "")
    return structure in {"delaware_with_israeli_sub", "mid_flip"} or inputs.get("mode") == "flip_focused"


def _has_safes(instruments: dict[str, Any]) -> bool:
    return bool(instruments.get("safes"))


def _has_notes(instruments: dict[str, Any]) -> bool:
    return bool(instruments.get("convertible_notes"))


def _has_preferred(cap_state: dict[str, Any]) -> bool:
    return bool(cap_state.get("preferred_series"))


def _has_warrants(cap_state: dict[str, Any]) -> bool:
    return bool(cap_state.get("outstanding_warrants"))


def _has_unvested_warrants(cap_state: dict[str, Any]) -> bool:
    """Gate `warrant.unvested_excluded_from_fd_per_policy` on actual unvested
    warrants existing (not just any warrant)."""
    return any(not w.get("vested_flag", False) for w in cap_state.get("outstanding_warrants") or [])


def _has_warrant_with_ad_clause(cap_state: dict[str, Any]) -> bool:
    """Gate `warrant.repricing_not_modeled` on a warrant actually carrying an
    anti_dilution_clause (mirrored from instruments at canonicalization per
    §3.2). Per §3.5 the matcher reads cap_state, not instruments."""
    return any(w.get("anti_dilution_clause") is not None for w in cap_state.get("outstanding_warrants") or [])


def _has_dual_class_holder(cap_state: dict[str, Any]) -> bool:
    """v0.5.0 §6.5: dual-class detection. Fires when any founder or common_batch
    holder has voting_rights_multiple != 1.0."""
    if any(float(f.get("voting_rights_multiple") or 1.0) != 1.0 for f in cap_state.get("founders") or []):
        return True
    return any(float(b.get("voting_rights_multiple") or 1.0) != 1.0 for b in cap_state.get("common_batches") or [])


def _aoa_has_dividend_provisions(cap_state: dict[str, Any]) -> bool:
    """Gate `cap_table.dividend_provisions_in_aoa_handoff` on the AoA-extracted
    finding."""
    return (cap_state.get("aoa_findings") or {}).get("dividend_provisions_present") is True


def _drag_along_below_75(cap_state: dict[str, Any]) -> bool:
    """Gate `israeli_aoa.drag_along_threshold_below_75_percent` on the actual
    extracted threshold being strictly < 75. Null (AoA not extracted) →
    default-deny."""
    threshold = (cap_state.get("aoa_findings") or {}).get("drag_along_threshold_pct")
    if threshold is None:
        return False
    try:
        return float(threshold) < 75
    except (TypeError, ValueError):
        return False


def _section_102_plan_absent(cap_state: dict[str, Any]) -> bool:
    """Gate `israeli_aoa.section_102_plan_absent` on the AoA-extracted finding
    `section_102_plan_reference is False` (the AoA was extracted AND it
    explicitly does NOT reference a §102 plan). Null (AoA not extracted) →
    default-deny: we don't know if a §102 plan exists, so don't fire the
    "absent" warning."""
    return (cap_state.get("aoa_findings") or {}).get("section_102_plan_reference") is False


def _liquidation_preference_above_1x(cap_state: dict[str, Any]) -> bool:
    """Gate `israeli_aoa.liquidation_preference_above_1x` on the AoA-extracted
    finding being True. Null → default-deny."""
    return (cap_state.get("aoa_findings") or {}).get("liquidation_preference_above_1x") is True


def _full_ratchet_anti_dilution(cap_state: dict[str, Any]) -> bool:
    """Gate `israeli_aoa.full_ratchet_anti_dilution` on the AoA-extracted
    finding being True. Null → default-deny."""
    return (cap_state.get("aoa_findings") or {}).get("ratchet_anti_dilution_detected") is True


def _has_section_102_grants(instruments: dict[str, Any], cap_state: dict[str, Any] | None = None) -> bool:
    """Read from cap_state.outstanding_options[*].plan_type (the canonical
    location) when cap_state is available; fall back to
    instruments.option_grants[*].plan_type for legacy callers. The two are
    mirrored at canonicalization (cap_state.py), so they agree."""
    if cap_state is not None:
        opts = cap_state.get("outstanding_options", []) or []
        if any((o.get("plan_type") or "").startswith("section_102") for o in opts):
            return True
        if opts:
            return False
    grants = instruments.get("option_grants", []) or []
    return any((g.get("plan_type") or "").startswith("section_102") for g in grants)


def _has_iia_grants(inputs: dict[str, Any]) -> bool:
    iia = (inputs.get("jurisdiction") or {}).get("iia_grants_history") or {}
    return bool(iia.get("has_grants"))


# ---------------------------------------------------------------------------
# Per-rule matcher dispatch table
# ---------------------------------------------------------------------------
#
# Each matcher takes (inputs, instruments, cap_state) and returns bool.
# Encodes the rule pack's prose `applies_when` field into a deterministic
# predicate. Rules not listed default to True (always applicable — this
# matches the rule pack's "Use when ..." convention which is permissive
# unless explicitly jurisdiction-gated).
#
# Reading a rule into a matcher:
#   * "Use when modeling Israeli companies" → _structure_includes_israel
#   * "Use when ... Delaware C corporation" → _structure_includes_delaware
#   * "Use when modeling a flip" → _is_cross_border OR mode=flip_focused
#   * "Use when a financing round may trigger automatic note conversion"
#     → has_notes (the trigger is engagement-context, not jurisdiction)
#   * "Use when preferred stock includes ... anti-dilution" → has_preferred
#
# The default (True) is the right v0.1 behaviour: a rule that the engagement
# can't conclusively trigger is still surfaced for counsel/founder visibility
# rather than silently skipped. The matchers below filter ONLY when the
# rule's applies_when explicitly precludes the current engagement.


def _matcher_always(_i: dict[str, Any], _inst: dict[str, Any], _cs: dict[str, Any]) -> bool:
    return True


def _derived_a_basis(series: dict[str, Any]) -> str:
    """The A-basis a series gets when it does not state one.

    Mirrors `cap_state.py`'s canonicalization and `priced_round._default_a_basis`. Kept as a named
    function so the third copy of this derivation is at least visibly a copy.
    """
    return "nvca_narrow" if series.get("anti_dilution_protection") == "narrow_based_weighted_average" else "nvca_broad"


_RULE_MATCHERS: dict[str, Any] = {
    # SAFE rules (US/document-specific — always applicable when SAFEs exist
    # or when modeling SAFEs hypothetically; default True for v0.1 flexibility)
    "safe.post_money_cap_conversion": _matcher_always,
    "safe.company_capitalization_yc_post_money": _matcher_always,
    "safe.discount_rate_semantics": _matcher_always,
    "safe.stacked_post_money_caps": lambda i, inst, cs: len(inst.get("safes", []) or []) > 1,
    "safe.mfn_package_only": lambda i, inst, cs: any(
        (s.get("mfn_provision") or {}).get("present") for s in (inst.get("safes") or [])
    ),
    "safe.pro_rata_rights_side_letter": lambda i, inst, cs: any(
        (s.get("pro_rata_side_letter") or {}).get("present") for s in (inst.get("safes") or [])
    ),
    "safe.liquidity_dissolution_priority": _matcher_always,  # counsel-review; surface always
    "safe.israeli_2025_safe_harbor": lambda i, inst, cs: _structure_includes_israel(i) and _has_safes(inst),
    "safe.israeli_safe_facts_circumstances": lambda i, inst, cs: _structure_includes_israel(i) and _has_safes(inst),
    # Convertible note rules
    "convertible_notes.accrued_interest": lambda i, inst, cs: _has_notes(inst),
    "convertible_notes.cap_discount_conversion": lambda i, inst, cs: _has_notes(inst),
    "convertible_notes.note_denominator_template": lambda i, inst, cs: _has_notes(inst),
    "convertible_notes.qualified_financing_threshold": lambda i, inst, cs: _has_notes(inst),
    "convertible_notes.israeli_cla_deemed_interest": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_notes(inst)
    ),
    # Option-pool rules — apply when there is a pool, or when modeling
    # priced-round mechanics (caller sets via scenario_request)
    "option_pool.pre_money_topup": _matcher_always,
    "option_pool.post_money_topup": _matcher_always,
    "option_pool.target_basis": _matcher_always,
    "option_pool.us_market_benchmarks": _matcher_always,
    # Anti-dilution — applies only when preferred has AD protection
    "anti_dilution.broad_based_weighted_average": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "broad_based_weighted_average" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.narrow_based_denominator": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "narrow_based_weighted_average" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.full_ratchet": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "full_ratchet" for s in (cs.get("preferred_series") or [])
    ),
    # Coupled-solver AD variants — apply only when respective protection is present
    "anti_dilution.broad_based_weighted_average_coupled": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "broad_based_weighted_average" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.narrow_based_weighted_average_coupled": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "narrow_based_weighted_average" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.full_ratchet_coupled": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") == "full_ratchet" for s in (cs.get("preferred_series") or [])
    ),
    # Trigger-basis rules — apply when any AD-protected series uses the respective basis
    "anti_dilution.trigger_basis_original_issue_price": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none"
        and s.get("ad_trigger_basis", "original_issue_price") == "original_issue_price"
        for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.trigger_basis_current_conversion_price": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" and s.get("ad_trigger_basis") == "current_conversion_price"
        for s in (cs.get("preferred_series") or [])
    ),
    # A-denominator-basis rules — apply when respective basis is in use
    # A-denominator basis. The fallback must MATCH the one the math uses -- `cap_state.py` derives it
    # from `anti_dilution_protection` and `priced_round._default_a_basis` agrees, so a hardcoded
    # "nvca_broad" default here made the audit contradict both (and the rule pack, whose own narrow
    # summary states the derivation) for a narrow-based series with the field absent. Latent today,
    # because pre_math reads the canonicalized cap_state where the field is always stamped -- but a
    # third, divergent copy of one derivation is how the first two stop agreeing.
    "anti_dilution.a_denominator_nvca_broad": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") in {"broad_based_weighted_average", "narrow_based_weighted_average"}
        and (s.get("ad_a_denominator_basis") or _derived_a_basis(s)) == "nvca_broad"
        for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.a_denominator_nvca_narrow": lambda i, inst, cs: any(
        s.get("anti_dilution_protection") in {"broad_based_weighted_average", "narrow_based_weighted_average"}
        and (s.get("ad_a_denominator_basis") or _derived_a_basis(s)) == "nvca_narrow"
        for s in (cs.get("preferred_series") or [])
    ),
    # CP2 floor configuration rule — applies when any series has a floor configured
    "anti_dilution.cp2_floor_applicable": lambda i, inst, cs: any(
        s.get("ad_cp2_floor") is not None for s in (cs.get("preferred_series") or [])
    ),
    # Carve-out source notes — apply when any AD-protected series exists
    # (the carve-outs ARE the consideration-set definition, so they're relevant whenever AD runs)
    "anti_dilution.carve_out_preferred_self_conversion": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_outstanding_convertibles": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_pool_grants": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_recapitalization": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_ma_consideration": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_lessor_lender_strategic": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_acquisition_jv": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_public_offering": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_safe_note_conversion": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.carve_out_reflexive_catch_all": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    # Runtime events — default-True via the dispatch table's fallback would surface them
    # always; instead scope to AD presence so they don't pollute no-AD engagements.
    "anti_dilution.cp2_floor_applied": lambda i, inst, cs: any(
        s.get("ad_cp2_floor") is not None for s in (cs.get("preferred_series") or [])
    ),
    # Counsel items are AND-gated: static matcher AND runtime event. Fixing only the runtime half
    # left this rule shut for the very case it exists for -- an unprotected series carrying the
    # contradiction, which is where the check was moved TO. Both halves now ask the same question,
    # via the same predicate, so they cannot disagree again.
    "anti_dilution.stale_ccp_detected": lambda i, inst, cs: bool(
        _artifact_io.stale_ccp_series_ids(cs.get("preferred_series") or [], cs.get("cap_table_history") or [])
    ),
    "anti_dilution.solver_diverged": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.solver_oscillating_damped": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.solver_aitken_acceleration_applied": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    "anti_dilution.solver_aitken_fallback_engaged": lambda i, inst, cs: any(
        s.get("anti_dilution_protection", "none") != "none" for s in (cs.get("preferred_series") or [])
    ),
    # P2P detection — text-pattern flag from extract_aoa; safer to default-True (the
    # rule_audit phase doesn't have access to the AoA text patterns, so applicability is
    # determined upstream by whether the extraction flagged P2P).
    "anti_dilution.pay_to_play_provision_detected": _matcher_always,
    # Israeli equity-tax rules (apply only to Israel-context engagements
    # with option grants — the rule pack is about §102/§3(i) plan-design)
    "israel_equity_tax.section_102_capital_gains": lambda i, inst, cs: _structure_includes_israel(i),
    "israel_equity_tax.section_102_plan_design": lambda i, inst, cs: _structure_includes_israel(i),
    "israel_equity_tax.section_102_double_trigger": lambda i, inst, cs: _structure_includes_israel(i),
    "israel_equity_tax.section_3i_nonemployee": lambda i, inst, cs: _structure_includes_israel(i),
    # Israeli Ltd rules — apply to Israeli entities only
    "israeli_ltd.share_register": lambda i, inst, cs: _structure_includes_israel(i),
    "israeli_ltd.registrar_online_reporting": lambda i, inst, cs: _structure_includes_israel(i),
    "israeli_ltd.iia_royalties_ip": lambda i, inst, cs: _structure_includes_israel(i) and _has_iia_grants(i),
    "israeli_ltd.preferred_governance_checklist": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs)
    ),
    # Israeli AoA rules — apply ONLY when:
    #   (a) jurisdiction structure includes Israel, AND
    #   (b) a preferred series is in cap_state (i.e., AoA terms have actually
    #       been extracted / the engagement is modeling preferred-stock economics).
    # Without (b), the engagement has no AoA-derived terms and these rules
    # would be noise (e.g., firing "drag-along below 75%" when there's no AoA).
    # Real-doc test surfaced this as a false-positive class — see the
    # post-test bugfix commit (May 2026).
    # Gate on the actual extracted threshold value < 75 (strict). Null
    # drag_along_threshold_pct (AoA not extracted) → default-deny.
    "israeli_aoa.drag_along_threshold_below_75_percent": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs) and _drag_along_below_75(cs)
    ),
    # The three sibling israeli_aoa.* rules below each gate on the actual
    # AoA-extracted finding (cap_state.aoa_findings.*) rather than just
    # "Israeli + has_preferred". Null → default-deny: an Israeli engagement
    # with findings that contradict a rule must not fire it as a false positive.
    "israeli_aoa.section_102_plan_absent": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs) and _section_102_plan_absent(cs)
    ),
    "israeli_aoa.liquidation_preference_above_1x": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs) and _liquidation_preference_above_1x(cs)
    ),
    "israeli_aoa.full_ratchet_anti_dilution": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs) and _full_ratchet_anti_dilution(cs)
    ),
    # Delaware cross-border — apply when ANY of: Delaware engagement,
    # cross-border structure, or flip mode
    "delaware_cross_border.structure_note": lambda i, inst, cs: _is_cross_border(i) or _structure_includes_israel(i),
    "delaware_cross_border.section_102_parent_shares": lambda i, inst, cs: (
        _is_cross_border(i) and _has_section_102_grants(inst, cs)
    ),
    "delaware_cross_border.transfer_pricing_ip": lambda i, inst, cs: _is_cross_border(i),
    "delaware_cross_border.delaware_formation_defaults": lambda i, inst, cs: _structure_includes_delaware(i),
    "delaware_cross_border.qsbs_date_sensitive": lambda i, inst, cs: _structure_includes_delaware(i),
    # Delaware flip rules — apply when modeling a flip (mode or cross-border)
    "delaware_flip.share_exchange_mechanics": lambda i, inst, cs: _is_cross_border(i),
    # Narrow to flip-active engagements (cross-border structure OR
    # mode=flip_focused). Bare-Israeli with mode=standard means "not planning
    # a flip" — these flip-doctrine rules don't apply. The general
    # "Israeli founder, consider flipping someday" coverage stays via
    # `delaware_cross_border.structure_note` which keeps the broad OR.
    "delaware_flip.ruling_path": lambda i, inst, cs: _is_cross_border(i) or i.get("mode") == "flip_focused",
    "delaware_flip.part_e2_repeal": lambda i, inst, cs: _is_cross_border(i) or i.get("mode") == "flip_focused",
    "delaware_flip.options_convertibles": lambda i, inst, cs: (
        _is_cross_border(i) and (_has_safes(inst) or _has_notes(inst) or _has_section_102_grants(inst, cs))
    ),
    "delaware_flip.iia_not_automatic_transfer": lambda i, inst, cs: _is_cross_border(i) and _has_iia_grants(i),
    "delaware_flip.timeline_cost": lambda i, inst, cs: _is_cross_border(i),
    # Founder benchmarks — apply by context
    "founder_benchmarks.carta_stage_medians": lambda i, inst, cs: _structure_includes_delaware(i),
    "founder_benchmarks.no_hard_redlines": _matcher_always,
    # Stage-scoped by its own applies_when ("Israeli pre-seed or seed scenarios"),
    # so it needs the stage, not just the geography. The rule_id keeps its name:
    # it is cited in seven committed cassettes, and renaming it would only move
    # the mismatch from the matcher into the identifier.
    "founder_benchmarks.israel_preseed_context": lambda i, inst, cs: _israel_early_stage_context(i),
    "founder_benchmarks.stacked_safe_warning": lambda i, inst, cs: len(inst.get("safes") or []) > 1,
    # Warrants domain: state-readable matchers. The runtime-event subset
    # (net_share_pre_round_fmv_approximation, exercise_event_before_round_pump)
    # lives in _RUNTIME_EVENT_RULE_IDS + _runtime_event_predicate — those gate
    # on actual pump events in scenarios.
    "warrant.included_in_fd_per_policy": lambda i, inst, cs: _has_warrants(cs),
    "warrant.unvested_excluded_from_fd_per_policy": lambda i, inst, cs: _has_unvested_warrants(cs),
    "warrant.repricing_not_modeled": lambda i, inst, cs: _has_warrant_with_ad_clause(cs),
    "warrant.net_share_pre_round_fmv_approximation": lambda i, inst, cs: _has_warrants(cs),
    "warrant.exercise_event_before_round_pump": lambda i, inst, cs: _has_warrants(cs),
    # Dual-class domain (§6.5): fires when any holder has voting_rights_multiple != 1.0
    "dual_class.founder_super_voting": lambda i, inst, cs: _has_dual_class_holder(cs),
    # Cap-table domain: dividend handoff — gates on AoA-extracted finding
    "cap_table.dividend_provisions_in_aoa_handoff": lambda i, inst, cs: _aoa_has_dividend_provisions(cs),
    # P5: pricing-unknown disclosure — gates on the flag actually being present on canonical
    # cap_state.preferred_series (cap_state.py's flag-carry conditional spread). Without this
    # matcher entry the rule defaults to _matcher_always and fires on every engagement.
    "cap_table.pricing_unknown_disclosure": lambda i, inst, cs: any(
        s.get("pricing_unknown") for s in (cs.get("preferred_series") or [])
    ),
    # Acquisition domain — apply only when the engagement models an
    # acquisition (inputs.acquisition is a real top-level key per
    # inputs.schema.json properties.acquisition). Absent block → suppressed.
    "acquisition.consideration_shares": lambda i, inst, cs: bool(i.get("acquisition")),
    "acquisition.pool_consideration_basis": lambda i, inst, cs: bool(i.get("acquisition")),
    "acquisition.timing": lambda i, inst, cs: bool(i.get("acquisition")),
}


def _matches_applies_when(
    rule: dict[str, Any],
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any] | None = None,
    cap_state: dict[str, Any] | None = None,
) -> bool:
    """Per-rule predicate matcher — encodes each rule's `applies_when` prose
    into a deterministic check against engagement context.

    Per design rev17 P3-7 + Phase 1 verification #3: the matcher is per-rule
    dispatch (option b) — rule pack stays stable, matchers live in this script.

    Rules not in _RULE_MATCHERS default to True (always applicable). This
    matches the rule pack's permissive convention.
    """
    rid = rule.get("rule_id", "")
    matcher = _RULE_MATCHERS.get(rid)
    if matcher is None:
        # Unknown rule_id — be permissive (surface for counsel rather than skip)
        return True

    # Build the (inputs, instruments, cap_state) triple expected by matchers.
    # Caller may not pass instruments/cap_state (e.g., in some legacy code
    # paths); default to empty dicts so matchers don't crash.
    return bool(matcher(inputs, instruments or {}, cap_state or {}))


def _build_gating_entry(
    rule: dict[str, Any],
    instance: dict[str, Any],
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any] | None = None,
    cap_state: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Build one gating entry per (rule, instance) tuple."""
    scope = _classify_scope(rule)
    applies = _matches_applies_when(rule, inputs=inputs, instruments=instruments, cap_state=cap_state)

    dw = rule.get("date_window") or {}
    has_window = bool(dw)
    has_bounds = has_window and (dw.get("start") or dw.get("end"))

    near_start_days = dw.get("near_edge_days_before_start", DEFAULT_NEAR_START_DAYS)
    near_end_days = dw.get("near_edge_days_before_end", DEFAULT_NEAR_END_DAYS)

    event_date = _parse_date(instance.get("event_date_value"))
    start = _parse_date(dw.get("start"))
    end = _parse_date(dw.get("end"))

    entry: dict[str, Any] = {
        "scope": scope,
        "applies_when_matched": applies,
        "event_date_field": dw.get("event_date_field"),
        "event_date_value": instance.get("event_date_value"),
        "event_date_path": instance.get("instance_json_pointer"),
        "instance_type": instance.get("instance_type"),
        "instance_id": instance.get("instance_id"),
        "near_end_flag": False,
        "near_start_flag": False,
        "freshness_status": None,
    }

    if scope == "not_applicable":
        entry["status"] = "not_date_sensitive"
        entry["event_date_field"] = None
        entry["event_date_path"] = None
        entry["event_date_value"] = None
        return entry

    if scope == "benchmark_freshness":
        # Freshness gating only; status is not used for math
        entry["status"] = "in_window"  # synthetic — always applicable
        entry["freshness_status"] = _evaluate_freshness(event_date, start, end)
        return entry

    # legal_tax_applicability
    if not has_bounds:
        # date-tracking-only shape
        if event_date is None:
            entry["status"] = "missing_event_date"
        else:
            entry["status"] = "date_tracking_only"
        return entry

    status, near_end, near_start = _evaluate_date_status(
        event_date,
        start,
        end,
        near_start_days=near_start_days,
        near_end_days=near_end_days,
        today=today,
    )
    entry["status"] = status
    entry["near_end_flag"] = near_end
    entry["near_start_flag"] = near_start
    return entry


def build_gating_block(
    rules: dict[str, Any],
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    scenarios: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Build the gating block consumed by math producers.

    Shape: gating[rule_id][instance_key] = entry (per rev15 §11 schema).
    instance_key is `<instance_type>:<instance_id>` (or `global` for
    not_date_sensitive rules).
    """
    gating: dict[str, dict[str, dict[str, Any]]] = {}
    for domain in rules.get("domains", {}).values():
        for rule in domain:
            rid = rule["rule_id"]
            gating[rid] = {}

            # For scenario-scoped rules, iterate scenarios
            field = (rule.get("date_window") or {}).get("event_date_field")
            if field in PER_SCENARIO_FIELDS and scenarios:
                for sc in scenarios:
                    instances = _resolve_event_date(
                        rule,
                        inputs=inputs,
                        instruments=instruments,
                        cap_state=cap_state,
                        scenario=sc,
                    )
                    for inst in instances:
                        entry = _build_gating_entry(
                            rule,
                            inst,
                            inputs=inputs,
                            instruments=instruments,
                            cap_state=cap_state,
                            today=today,
                        )
                        key = f"{inst['instance_type']}:{inst.get('instance_id') or 'global'}"
                        gating[rid][key] = entry
            else:
                instances = _resolve_event_date(
                    rule,
                    inputs=inputs,
                    instruments=instruments,
                    cap_state=cap_state,
                    scenario=None,
                )
                if not instances:
                    # Rule has no applicable instances; still record as not_applicable
                    instances = [
                        {
                            "instance_type": "global",
                            "instance_id": None,
                            "instance_json_pointer": None,
                            "event_date_value": None,
                            "event_date_field": field,
                        }
                    ]
                for inst in instances:
                    entry = _build_gating_entry(
                        rule,
                        inst,
                        inputs=inputs,
                        instruments=instruments,
                        cap_state=cap_state,
                        today=today,
                    )
                    key = f"{inst['instance_type']}:{inst.get('instance_id') or 'global'}"
                    gating[rid][key] = entry

    return gating


def build_watchlist(
    gating: dict[str, dict[str, dict[str, Any]]],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compose date-sensitive watchlist from gating block.

    Per rev16 P1-4: includes legal/tax + benchmark_freshness entries with
    their respective status / freshness_status fields.
    """
    # Build a lookup of rule_id → rule for title + domain
    rule_lookup = {r["rule_id"]: r for domain in rules.get("domains", {}).values() for r in domain}

    watchlist = []
    for rule_id, instances in gating.items():
        rule = rule_lookup.get(rule_id, {})
        for _key, entry in instances.items():
            scope = entry.get("scope")
            if scope == "not_applicable":
                continue  # not date-sensitive; not in watchlist

            wl_entry = {
                "rule_id": rule_id,
                "title": rule.get("title", rule_id),
                "scope": scope,
                # Carry the static gate through. compose_report.py splits the
                # watchlist on this into ACTIVE vs for-reference, and its default
                # for an absent key is True — so dropping it here silently
                # promoted every structurally-inapplicable rule to an action item.
                # Observed: a Delaware-only company with no IIA grants was shown
                # Israeli §102 / Registrar / SAFE-safe-harbour rows as things to
                # watch. The gate itself was always correct; only the plumbing lost it.
                "applies_when_matched": entry.get("applies_when_matched"),
                "event_date_field": entry.get("event_date_field"),
                "instance_type": entry.get("instance_type"),
                "instance_id": entry.get("instance_id"),
                "instance_json_pointer": entry.get("event_date_path"),
                "current_status": entry.get("status") if scope == "legal_tax_applicability" else None,
                "freshness_status": entry.get("freshness_status"),
                "near_end_flag": entry.get("near_end_flag", False),
                "near_start_flag": entry.get("near_start_flag", False),
                "event_date_value": entry.get("event_date_value"),
                "action_required": _action_for_status(entry, rule),
            }
            watchlist.append(wl_entry)
    return watchlist


def _action_for_status(entry: dict[str, Any], rule: dict[str, Any]) -> str:
    scope = entry.get("scope")
    status = entry.get("status")
    if scope == "benchmark_freshness":
        f = entry.get("freshness_status")
        if f == "stale":
            return "Benchmark dataset is stale; refresh annually per rule notes."
        if f == "unknown":
            return "Set a benchmark reference date in your inputs to use current data."
        return "Benchmark fresh; renders as context only."
    if status == "missing_event_date":
        field = (entry.get("event_date_field") or "date").replace("_", " ")
        return f"Provide the {field} for this instance."
    if status == "expired":
        return "Rule's applicability window has passed; counsel review for current regime."
    if status == "pre_effective":
        return "Rule's applicability window has not started yet; flag for activation."
    if status == "date_tracking_only":
        return "Rule applies; date is tracked for downstream prompts."
    if status == "in_window":
        warnings = rule.get("warnings", []) or []
        return warnings[0] if warnings else "Rule applies; review per warnings."
    return "Review status."


_RUNTIME_EVENT_RULE_IDS = frozenset(
    {
        "anti_dilution.stale_ccp_detected",
        "anti_dilution.cp2_floor_applied",
        "anti_dilution.solver_diverged",
        "anti_dilution.solver_oscillating_damped",
        "anti_dilution.solver_aitken_acceleration_applied",
        "anti_dilution.solver_aitken_fallback_engaged",
        "anti_dilution.pay_to_play_provision_detected",
        # Warrant runtime-event rules: gate on actual pump events in
        # scenarios[*].computed_outputs.warrant_exercise_events[*].
        "warrant.net_share_pre_round_fmv_approximation",
        "warrant.exercise_event_before_round_pump",
    }
)


def _runtime_event_predicate(
    rule_id: str,
    scenarios_data: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> bool | None:
    """Gate solver-event counsel rules on the actual runtime event firing.

    Static gating (`applies_when_matched` from `_RULE_MATCHERS`) is intentionally
    permissive — it scopes to "AD-protected series present." But for runtime-event
    rules (solver warning fired, AoA P2P pattern detected, CP2 floor clamped),
    the rule should only surface as a counsel item when the event ACTUALLY
    occurred. Returns:
      * True  → surface the counsel item (event fired)
      * False → suppress (event did not fire — would have been a false positive)
      * None  → not a runtime-event rule; use static gating

    Default-deny semantics: when this is a runtime-event rule AND the caller
    didn't supply scenarios_data / inputs, return False (suppress) rather than
    None (defer). Without this, callers that don't pass --scenarios/--inputs
    end up admitting every runtime-event counsel rule whenever AD-protected
    preferred is present, regardless of whether the event happened. Non-runtime
    rules continue to defer to static gating via the final `return None`.
    """
    if rule_id in _RUNTIME_EVENT_RULE_IDS and scenarios_data is None and inputs is None:
        # Default-deny for runtime-event rules when no context supplied.
        return False
    if rule_id not in _RUNTIME_EVENT_RULE_IDS and scenarios_data is None and inputs is None:
        return None  # not a runtime-event rule, no context; defer to static gating

    scenarios = (scenarios_data or {}).get("scenarios", []) or []

    def _any_warning(code: str) -> bool:
        for s in scenarios:
            co = s.get("computed_outputs", {}) or {}
            for w in co.get("warnings", []) or []:
                if w.get("code") == code:
                    return True
        return False

    def _any_blocker(code: str) -> bool:
        for s in scenarios:
            co = s.get("computed_outputs", {}) or {}
            for b in co.get("blockers", []) or []:
                if b.get("code") == code:
                    return True
        return False

    def _any_diag(flag: str) -> bool:
        for s in scenarios:
            co = s.get("computed_outputs", {}) or {}
            diag = co.get("convergence_diagnostics", {}) or {}
            if diag.get(flag):
                return True
        return False

    if rule_id == "anti_dilution.stale_ccp_detected":
        # TWO channels, because the check moved and this gate did not follow it. `_any_warning` reads
        # SOLVER warnings off scenarios -- the original home, where the check sits behind three
        # unrelated gates and almost never fires. The condition is now also evaluated wherever the cap
        # state is built, which is where it actually catches things. Keying only on the solver channel
        # left this `counsel_review: true` rule inert even once the warning worked: the founder got the
        # prose and their lawyer got nothing.
        if _any_warning("W_STALE_CCP_SUSPECTED"):
            return True
        if inputs:
            return bool(
                _artifact_io.stale_ccp_series_ids(
                    inputs.get("preferred_series") or [], inputs.get("cap_table_history") or []
                )
            )
        return False
    if rule_id == "anti_dilution.cp2_floor_applied":
        return _any_warning("W_CP2_FLOOR_APPLIED")
    if rule_id == "anti_dilution.solver_diverged":
        return _any_blocker("E_SOLVER_DID_NOT_CONVERGE") or _any_blocker("E_SOLVER_LIKELY_DIVERGENT")
    if rule_id == "anti_dilution.solver_oscillating_damped":
        return _any_diag("damping_engaged")
    if rule_id == "anti_dilution.solver_aitken_acceleration_applied":
        return _any_diag("aitken_engaged")
    if rule_id == "anti_dilution.solver_aitken_fallback_engaged":
        return _any_diag("aitken_fallback_engaged")
    if rule_id == "anti_dilution.pay_to_play_provision_detected":
        # P2P is detected by extract_aoa.detect_pay_to_play() and surfaced as a
        # `pay_to_play_present` flag on the AoA-derived input (or as a top-level
        # `aoa_findings.pay_to_play_detected` in inputs.json after merge_into_inputs).
        if not inputs:
            return False
        # Check top-level flag, common-batches metadata, or any preferred-series flag
        if inputs.get("pay_to_play_detected") is True:
            return True
        for s in inputs.get("preferred_series", []) or []:
            if s.get("pay_to_play_present") is True:
                return True
        findings = inputs.get("aoa_findings") or {}
        return findings.get("pay_to_play_detected") is True

    # v0.5.0 warrant runtime events
    def _any_warrant_event_with(field: str, value: Any = True) -> bool:
        for s in scenarios:
            co = s.get("computed_outputs", {}) or {}
            for evt in co.get("warrant_exercise_events", []) or []:
                if evt.get(field) == value:
                    return True
        return False

    if rule_id == "warrant.net_share_pre_round_fmv_approximation":
        # Fires only when a pump event actually used the FMV approximation
        # (settlement_type=net_share AND no prior priced-round PPS).
        return _any_warrant_event_with("fmv_approximation_used", True)
    if rule_id == "warrant.exercise_event_before_round_pump":
        # Informational source note; fires when ANY pump event occurred in a scenario.
        for s in scenarios:
            co = s.get("computed_outputs", {}) or {}
            if co.get("warrant_exercise_events") or []:
                return True
        return False

    return None  # not a runtime-event rule


def build_counsel_review_items(
    gating: dict[str, dict[str, dict[str, Any]]],
    rules: dict[str, Any],
    scenarios_data: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract counsel_review_items from rules where counsel_review=true.

    Runtime-event rules (solver warnings, AoA detections) are gated on the
    actual event having occurred — see _runtime_event_predicate. Without this,
    every AD-domain counsel-review rule fires whenever the engagement has
    AD-protected preferred series, producing false positives like
    `stale_ccp_detected` and `pay_to_play_provision_detected` in scenarios
    where the underlying event never happened.
    """
    rule_lookup = {r["rule_id"]: r for domain in rules.get("domains", {}).values() for r in domain}
    items = []
    seen_rules = set()
    for rule_id, instances in gating.items():
        rule = rule_lookup.get(rule_id)
        if not rule or not rule.get("counsel_review"):
            continue
        # Static gating: rule's _RULE_MATCHERS predicate matched AND status is
        # not definitively out-of-scope.
        any_applicable = any(
            e.get("applies_when_matched") and e.get("status") not in {"pre_effective", "expired"}
            for e in instances.values()
        )
        if not any_applicable:
            continue
        # Runtime gating: for solver-event / AoA-detection rules, also
        # require the underlying event to have actually occurred.
        runtime_gate = _runtime_event_predicate(rule_id, scenarios_data, inputs)
        if runtime_gate is False:
            continue
        if rule_id in seen_rules:
            continue
        seen_rules.add(rule_id)
        # Carry the (instance_type, instance_id) the gating already computed so
        # downstream consumers can show what a counsel item applies to. Exactly
        # one item per rule; the matched instances ride along as a
        # deterministically-sorted list.
        inst_list = _counsel_instances(instances)
        items.append(
            {
                "rule_id": rule_id,
                "domain": rule.get("domain", ""),
                "title": rule.get("title", rule_id),
                "applies_when": rule.get("applies_when", ""),
                "founder_question": (rule.get("warnings") or [""])[0] or "",
                "counsel_question": rule.get("summary", ""),
                "documents_needed": [],  # placeholder; design §17 promises richer field
                "source_ids": rule.get("source_ids", []),
                "instances": inst_list,
                "relevance_tier": _counsel_relevance_tier(inst_list),
                "applies_to": _counsel_applies_to(inst_list),
            }
        )
    # A general-scoped item whose DOMAIN has a specific instrument/scenario match
    # elsewhere in this cap table is "likely relevant": the class is present even
    # though this rule matched no exact instance of its own. Deterministic
    # (depends only on the assembled items).
    specific_domains = {it["domain"] for it in items if it["relevance_tier"] == "applies" and it.get("domain")}
    for it in items:
        if it["relevance_tier"] == "general" and it.get("domain") and it["domain"] in specific_domains:
            it["relevance_tier"] = "likely"
    return items


# Instance types that are not tied to a specific instrument/scenario in this
# cap table — counsel items scoped only to these read as "applies to all".
_GENERAL_INSTANCE_TYPES = {"global", "engagement", None, ""}


def _counsel_instances(instances: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Distinct (instance_type, instance_id) pairs for the gating entries that
    actually matched, sorted None-safely for deterministic output."""
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for e in instances.values():
        if not (e.get("applies_when_matched") and e.get("status") not in {"pre_effective", "expired"}):
            continue
        key = (e.get("instance_type"), e.get("instance_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"instance_type": e.get("instance_type"), "instance_id": e.get("instance_id")})
    out.sort(key=lambda x: (x["instance_type"] or "", x["instance_id"] or ""))
    return out


def _counsel_relevance_tier(inst_list: list[dict[str, Any]]) -> str:
    """ "applies" when the item matched a real instrument/scenario in this cap
    table; "general" when only global/engagement-scoped. We do not invent a
    per-scenario tier the data cannot support."""
    has_specific = any(i.get("instance_type") not in _GENERAL_INSTANCE_TYPES for i in inst_list)
    return "applies" if has_specific else "general"


def _counsel_applies_to(inst_list: list[dict[str, Any]]) -> str:
    """Short founder-facing label of what an item applies to."""
    ids = [
        i["instance_id"]
        for i in inst_list
        if i.get("instance_id") and i.get("instance_type") not in _GENERAL_INSTANCE_TYPES
    ]
    if not ids:
        return "all"
    uniq: list[str] = []
    for x in ids:
        if str(x) not in uniq:
            uniq.append(str(x))
    return ", ".join(uniq[:3]) + ("…" if len(uniq) > 3 else "")


def build_source_notes(
    gating: dict[str, dict[str, dict[str, Any]]],
    rules: dict[str, Any],
    scenarios_data: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Surface `behavior_target=source_note` rules whose matcher predicate
    fires AND (for runtime-event rules) whose underlying event actually
    occurred. counsel_review_items only emits rules with counsel_review=true;
    source notes have counsel_review=false and would otherwise vanish from
    the report.

    Source notes are informational citations — "this number was computed via
    rule X per NVCA §Y." They surface in a dedicated `## Source Notes`
    section of report.md so founders can trace each computation back to a
    primary source.
    """
    rule_lookup = {r["rule_id"]: r for domain in rules.get("domains", {}).values() for r in domain}
    items = []
    seen_rules = set()
    for rule_id, instances in gating.items():
        rule = rule_lookup.get(rule_id)
        if not rule:
            continue
        if rule.get("behavior_target") != "source_note":
            continue
        # Same gating logic as counsel-review items: matcher fired + status applicable.
        any_applicable = any(
            e.get("applies_when_matched") and e.get("status") not in {"pre_effective", "expired"}
            for e in instances.values()
        )
        if not any_applicable:
            continue
        runtime_gate = _runtime_event_predicate(rule_id, scenarios_data, inputs)
        if runtime_gate is False:
            continue
        if rule_id in seen_rules:
            continue
        seen_rules.add(rule_id)
        items.append(
            {
                "rule_id": rule_id,
                "domain": rule.get("domain", ""),
                "title": rule.get("title", rule_id),
                "summary": rule.get("summary", ""),
                "source_ids": rule.get("source_ids", []),
            }
        )
    return items


def build_applied_rules(
    gating: dict[str, dict[str, dict[str, Any]]],
    scenarios_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Composite list of rules math producers applied (or skipped).

    For each rule_id, decide whether the math producers would have applied
    it: applies_when_matched AND status ∈ {in_window, date_tracking_only,
    not_date_sensitive} (scope=legal_tax_applicability or not_applicable),
    OR scope=benchmark_freshness (always applicable).
    """
    out = []
    apply_statuses = {"in_window", "date_tracking_only", "not_date_sensitive"}
    for rule_id, instances in gating.items():
        for _key, entry in instances.items():
            scope = entry.get("scope")
            if (
                scope == "benchmark_freshness"
                or entry.get("applies_when_matched")
                and entry.get("status") in apply_statuses
            ):
                result = "computed"
            else:
                result = "skipped"
            out.append(
                {
                    "rule_id": rule_id,
                    "applied_to": entry.get("instance_id") or "global",
                    "result": result,
                }
            )
    return out


def _load_existing(path: str) -> dict[str, Any]:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    return {}


def _phase_pre_math(args: argparse.Namespace) -> int:
    with open(_RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)
    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)
    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)

    scenarios = None
    if args.scenarios and os.path.exists(args.scenarios):
        with open(args.scenarios, encoding="utf-8") as f:
            scenarios_data = json.load(f)
        scenarios = scenarios_data.get("scenarios", [])

    today = _parse_date(args.today) or date.today()
    gating = build_gating_block(
        rules,
        inputs=inputs,
        instruments=instruments,
        cap_state=cap_state,
        scenarios=scenarios,
        today=today,
    )

    # Pre-math phase writes ONLY the gating block + empty watchlist/items.
    audit_data = {
        "gating": gating,
        "applied_rules": [],
        "counsel_review_items": [],
        "date_sensitive_watchlist": [],
    }
    schema = load_schema(os.path.join(_SCHEMA_DIR, "rule_audit.schema.json"))
    try:
        receipt = write_artifact(
            data=audit_data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"rule_audit.py (pre_math): schema validation failed: {e}\n")
        return 1
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


def _phase_post_math(args: argparse.Namespace) -> int:
    with open(_RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)

    # Read the existing gating block (preserved verbatim)
    existing = _load_existing(args.output)
    gating = existing.get("gating", {})
    if not gating:
        sys.stderr.write(
            f"rule_audit.py (post_math): no existing gating block found at {args.output}; run --phase=pre_math first.\n"
        )
        return 1

    # Optionally load scenarios.json + inputs.json to gate runtime-event
    # counsel rules (stale_ccp_detected, pay_to_play_provision_detected, etc.)
    # on the actual event having fired. Without these reads, every AD-domain
    # counsel-review rule surfaces whenever AD-protected preferred is present.
    scenarios_data: dict[str, Any] | None = None
    if args.scenarios and os.path.exists(args.scenarios):
        with open(args.scenarios, encoding="utf-8") as f:
            scenarios_data = json.load(f)
    inputs_data: dict[str, Any] | None = None
    if args.inputs and os.path.exists(args.inputs):
        with open(args.inputs, encoding="utf-8") as f:
            inputs_data = json.load(f)

    audit_data = {
        "gating": gating,  # preserved verbatim
        "applied_rules": build_applied_rules(gating, scenarios_data),
        "counsel_review_items": build_counsel_review_items(gating, rules, scenarios_data, inputs_data),
        "source_notes": build_source_notes(gating, rules, scenarios_data, inputs_data),
        "date_sensitive_watchlist": build_watchlist(gating, rules),
    }
    schema = load_schema(os.path.join(_SCHEMA_DIR, "rule_audit.schema.json"))
    try:
        receipt = write_artifact(
            data=audit_data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"rule_audit.py (post_math): schema validation failed: {e}\n")
        return 1
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        sys.stderr.write(
            f"  applied: {len(audit_data['applied_rules'])} | "
            f"counsel: {len(audit_data['counsel_review_items'])} | "
            f"date_sensitive_watchlist: {len(audit_data['date_sensitive_watchlist'])}\n"
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["pre_math", "post_math"], required=True)
    p.add_argument("--inputs")
    p.add_argument("--instruments")
    p.add_argument("--cap-state")
    p.add_argument(
        "--scenarios",
        default=None,
        help="Optional scenarios.json for per-scenario rules (post_math + pre_math when scenarios exist)",
    )
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--today", default=None, help="ISO date override for status evaluation (testing)")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    if args.phase == "pre_math":
        for required in ("inputs", "instruments", "cap_state"):
            if not getattr(args, required):
                sys.stderr.write(f"--{required.replace('_', '-')} is required for pre_math\n")
                return 1
        return _phase_pre_math(args)
    return _phase_post_math(args)


if __name__ == "__main__":
    sys.exit(main())
