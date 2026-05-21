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
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)
_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
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

    # Window-bounded
    if start is not None and event_date_value < start:
        # pre_effective; check near_start
        delta_start = (start - event_date_value).days
        near_start = delta_start <= near_start_days
        return "pre_effective", False, near_start

    if end is not None and event_date_value > end:
        return "expired", False, False

    # in_window — check near_end if end exists
    near_end = False
    if end is not None:
        delta_end = (end - event_date_value).days
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
    """
    dw = rule.get("date_window") or {}
    field = dw.get("event_date_field")
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


def _is_cross_border(inputs: dict[str, Any]) -> bool:
    structure = (inputs.get("jurisdiction") or {}).get("structure", "")
    return structure in {"delaware_with_israeli_sub", "mid_flip"} or inputs.get("mode") == "flip_focused"


def _has_safes(instruments: dict[str, Any]) -> bool:
    return bool(instruments.get("safes"))


def _has_notes(instruments: dict[str, Any]) -> bool:
    return bool(instruments.get("notes"))


def _has_preferred(cap_state: dict[str, Any]) -> bool:
    return bool(cap_state.get("preferred_series"))


def _has_section_102_grants(instruments: dict[str, Any]) -> bool:
    grants = instruments.get("option_grants", []) or []
    return any(g.get("plan_type", "").startswith("section_102") for g in grants)


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
    # Israeli AoA rules (commit #7 post-J audit) — apply ONLY when:
    #   (a) jurisdiction structure includes Israel, AND
    #   (b) a preferred series is in cap_state (i.e., AoA terms have actually
    #       been extracted / the engagement is modeling preferred-stock economics).
    # Without (b), the engagement has no AoA-derived terms and these rules
    # would be noise (e.g., firing "drag-along below 75%" when there's no AoA).
    # Real-doc test surfaced this as a false-positive class — see the
    # post-test bugfix commit (May 2026).
    "israeli_aoa.drag_along_threshold_below_75_percent": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs)
    ),
    "israeli_aoa.section_102_plan_absent": lambda i, inst, cs: _structure_includes_israel(i) and _has_preferred(cs),
    "israeli_aoa.liquidation_preference_above_1x": lambda i, inst, cs: (
        _structure_includes_israel(i) and _has_preferred(cs)
    ),
    "israeli_aoa.full_ratchet_anti_dilution": lambda i, inst, cs: _structure_includes_israel(i) and _has_preferred(cs),
    # Delaware cross-border — apply when ANY of: Delaware engagement,
    # cross-border structure, or flip mode
    "delaware_cross_border.structure_note": lambda i, inst, cs: _is_cross_border(i) or _structure_includes_israel(i),
    "delaware_cross_border.section_102_parent_shares": lambda i, inst, cs: (
        _is_cross_border(i) and _has_section_102_grants(inst)
    ),
    "delaware_cross_border.transfer_pricing_ip": lambda i, inst, cs: _is_cross_border(i),
    "delaware_cross_border.delaware_formation_defaults": lambda i, inst, cs: _structure_includes_delaware(i),
    "delaware_cross_border.qsbs_date_sensitive": lambda i, inst, cs: _structure_includes_delaware(i),
    # Delaware flip rules — apply when modeling a flip (mode or cross-border)
    "delaware_flip.share_exchange_mechanics": lambda i, inst, cs: _is_cross_border(i),
    "delaware_flip.ruling_path": lambda i, inst, cs: _is_cross_border(i) or _structure_includes_israel(i),
    "delaware_flip.part_e2_repeal": lambda i, inst, cs: _is_cross_border(i) or _structure_includes_israel(i),
    "delaware_flip.options_convertibles": lambda i, inst, cs: (
        _is_cross_border(i) and (_has_safes(inst) or _has_notes(inst) or _has_section_102_grants(inst))
    ),
    "delaware_flip.iia_not_automatic_transfer": lambda i, inst, cs: _is_cross_border(i) and _has_iia_grants(i),
    "delaware_flip.timeline_cost": lambda i, inst, cs: _is_cross_border(i),
    # Founder benchmarks — apply by context
    "founder_benchmarks.carta_stage_medians": lambda i, inst, cs: _structure_includes_delaware(i),
    "founder_benchmarks.no_hard_redlines": _matcher_always,
    "founder_benchmarks.israel_preseed_context": lambda i, inst, cs: _structure_includes_israel(i),
    "founder_benchmarks.stacked_safe_warning": lambda i, inst, cs: len(inst.get("safes") or []) > 1,
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
            return "Set benchmark_reference_date in inputs.event_dates to use current data."
        return "Benchmark fresh; renders as context only."
    if status == "missing_event_date":
        return f"Provide {entry.get('event_date_field')} on the relevant instance."
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


def build_counsel_review_items(
    gating: dict[str, dict[str, dict[str, Any]]],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract counsel_review_items from rules where counsel_review=true."""
    rule_lookup = {r["rule_id"]: r for domain in rules.get("domains", {}).values() for r in domain}
    items = []
    seen_rules = set()
    for rule_id, instances in gating.items():
        rule = rule_lookup.get(rule_id)
        if not rule or not rule.get("counsel_review"):
            continue
        # Counsel-review surfaces whenever the rule applies to the engagement
        # AND status is not definitively out-of-scope (pre_effective / expired).
        # missing_event_date IS surfaced — the founder needs to be prompted to
        # provide the date. in_window / date_tracking_only / not_date_sensitive
        # all surface as well.
        any_applicable = any(
            e.get("applies_when_matched") and e.get("status") not in {"pre_effective", "expired"}
            for e in instances.values()
        )
        if not any_applicable:
            continue
        if rule_id in seen_rules:
            continue
        seen_rules.add(rule_id)
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

    audit_data = {
        "gating": gating,  # preserved verbatim
        "applied_rules": build_applied_rules(gating),
        "counsel_review_items": build_counsel_review_items(gating, rules),
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
            f"watchlist: {len(audit_data['date_sensitive_watchlist'])}\n"
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
