#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Compose cap-table report.md + report.json from canonical artifacts.

Reads all canonical artifacts from a directory, validates cross-artifact
consistency (matching run_id; required artifacts present), assembles
report.md (with Coaching Commentary uuid marker per design §3.1) and
report.json (with embedded coaching_payload block per rev15 §11 schema).

Per the cross-skill invariant tested in tests/test_compose_invariants.py:
report.json must contain `report_markdown` AND `coaching_payload` as
top-level keys.

Schema version: `v0.5.0-cap-table`. Includes the per-instrument
verification-output fields (evidence_verification, backward_verification,
invariant_checks).

math_provenance uses source_type + (rule_id + rule_pack_version |
source_ref) — see scenarios.json schema.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _labels  # noqa: E402
import _rules  # noqa: E402

SCHEMA_VERSION = "v0.5.0-cap-table"


def _rule_md(
    rule_id: str,
    *,
    item_title: str | None = None,
    item_source_ids: list[str] | None = None,
    bold: bool = False,
) -> str:
    """Readable rule reference for Markdown: title linked to its primary source,
    extra publishers as 'also' links, raw rule_id as small-print code."""
    ref = _rules.rule_ref(rule_id, item_title=item_title, item_source_ids=item_source_ids)
    title = str(ref["title"])
    links = ref["links"]
    title_part = f"[{title}]({links[0][1]})" if links else title
    if bold:
        title_part = f"**{title_part}**"
    out = title_part
    if links and links[1:]:
        out += " · " + " · ".join(f"[{p}]({u})" for p, u in links[1:])
    out += f" (`{rule_id}`)"
    return out


# Required canonical artifacts per design §3.6
REQUIRED_ARTIFACTS = [
    "inputs.json",
    "instruments.json",
    "cap_state.json",
    "scenarios.json",
    "rule_audit.json",
    "counsel_packet.json",
]


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _percent(p: float) -> str:
    return f"{p * 100:.1f}%"


def _money(m: float, currency: str = "USD") -> str:
    sign = "-" if m < 0 else ""
    abs_m = abs(m)
    if abs_m >= 1_000_000_000:
        return f"{sign}${abs_m / 1_000_000_000:.2f}B"
    if abs_m >= 1_000_000:
        return f"{sign}${abs_m / 1_000_000:.2f}M"
    if abs_m >= 1_000:
        return f"{sign}${abs_m / 1_000:,.0f}K"
    return f"{sign}${abs_m:,.0f}"


def validate_run_id_parity(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per design §11 + Gotcha-equivalent: all artifacts must share metadata.run_id.

    Returns structured warnings: [{code, severity, message, details}, ...].
    The structured shape matches the cross-skill test_compose_invariants
    contract (warnings have a `code` field).
    """
    warnings: list[dict[str, Any]] = []
    run_ids = {}
    for name, content in artifacts.items():
        rid = (content.get("metadata") or {}).get("run_id")
        if rid is None:
            warnings.append(
                {
                    "code": "MISSING_METADATA",
                    "severity": "high",
                    "message": f"{name} has no metadata.run_id",
                    "artifact": name,
                }
            )
        else:
            run_ids[name] = rid
    unique = set(run_ids.values())
    if len(unique) > 1:
        details = "; ".join(f"{n}={rid}" for n, rid in run_ids.items())
        warnings.append(
            {
                "code": "STALE_ARTIFACT",
                "severity": "high",
                "message": f"run_id mismatch across artifacts: {details}",
                "run_ids_seen": run_ids,
            }
        )
    return warnings


def build_scenario_digest(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per rev15 coaching_payload schema."""
    digest = []
    for s in scenarios:
        co = s.get("computed_outputs", {}) or {}
        completeness = co.get("completeness", "structural_only")
        blockers = co.get("blockers", [])
        founder_impact = co.get("founder_impact")  # nullable per rev15
        params = s.get("parameters", {})
        headline_inputs = {
            "pre_money": params.get("pre_money"),
            "new_money": params.get("new_money"),
            "target_pool_percent": params.get("target_pool_percent"),
        }
        # Branch summary
        per_note = co.get("per_note", {}) or {}
        per_safe = co.get("per_safe", {}) or {}
        share_branches = {
            "cap_conversion",
            "discount_only",
            "maturity_convert_at_cap",
            "cap_branch",
            "cap_and_discount_branch",
            "discount_branch",
            "conversion_price_override",
        }
        cash_branches = {"maturity_repay"}
        struct_branches = {"maturity_extend", "maturity_counsel_review", "threshold_not_met"}
        branches_seen = [
            *(p.get("branch") for p in per_note.values()),
            *(p.get("branch") for p in per_safe.values()),
        ]
        branch_summary = {
            "share_producing_count": sum(1 for b in branches_seen if b in share_branches),
            "cash_producing_count": sum(1 for b in branches_seen if b in cash_branches),
            "structural_only_count": sum(1 for b in branches_seen if b in struct_branches),
        }
        # Scenario drivers — simple narrative hooks
        drivers = []
        if params.get("pre_money"):
            drivers.append(f"{s['type'].replace('_', ' ').title()} at {_money(params['pre_money'])} pre-money")
        if params.get("target_pool_percent"):
            drivers.append(
                f"Pool top-up to {params['target_pool_percent']:.0%} {params.get('target_basis', 'pre-money').replace('_', ' ')}"
            )
        if branch_summary["structural_only_count"] > 0:
            drivers.append(f"{branch_summary['structural_only_count']} note(s) / SAFE(s) pending")
        digest.append(
            {
                "scenario_id": s["scenario_id"],
                "label": s.get("label", s["scenario_id"]),
                "type": s["type"],
                "completeness": completeness,
                "blockers": blockers,
                "headline_inputs": headline_inputs,
                "founder_impact": founder_impact,
                "branch_summary": branch_summary,
                "scenario_drivers": drivers,
            }
        )
    return digest


def build_ownership_range(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Per rev15: computed only across scenarios with completeness ∈ {full, mixed}."""
    eligible = []
    for s in scenarios:
        co = s.get("computed_outputs", {}) or {}
        if co.get("completeness") not in {"full", "mixed"}:
            continue
        agg = co.get("aggregate_ownership_by_class")
        if agg:
            eligible.append(agg)

    if not eligible:
        return {
            "_note": "No scenarios produced resolved ownership; range is null.",
            "scenarios_considered": 0,
            "founders_min_pct": None,
            "founders_max_pct": None,
            "option_pool_min_pct": None,
            "option_pool_max_pct": None,
            "preferred_min_pct": None,
            "preferred_max_pct": None,
        }

    def _range(key: str) -> tuple[float | None, float | None]:
        vals = [a.get(key, 0.0) for a in eligible]
        return min(vals), max(vals)

    fmin, fmax = _range("founders_pct")
    pmin, pmax = _range("option_pool_pct")
    prmin, prmax = _range("preferred_pct")
    return {
        "scenarios_considered": len(eligible),
        "founders_min_pct": fmin,
        "founders_max_pct": fmax,
        "option_pool_min_pct": pmin,
        "option_pool_max_pct": pmax,
        "preferred_min_pct": prmin,
        "preferred_max_pct": prmax,
    }


def build_top_dilution_drivers(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Surface the biggest dilution sources across scenarios."""
    drivers = []
    for s in scenarios:
        co = s.get("computed_outputs", {}) or {}
        agg = co.get("aggregate_ownership_by_class") or {}
        breakdown = co.get("shares_breakdown") or {}
        post_fd = co.get("post_round_fully_diluted_shares") or 0
        scenario_id = s["scenario_id"]
        new_money_pct = agg.get("new_money_pct", 0.0)
        safe_pct = agg.get("safe_pct", 0.0)
        note_pct = agg.get("note_pct", 0.0)
        pool_topup = breakdown.get("pool_topup") or 0
        if new_money_pct > 0.01:
            drivers.append(
                {
                    "driver": f"New money ({_money(s['parameters'].get('new_money', 0))})",
                    "scenarios": [scenario_id],
                    "founder_impact_pp": round(new_money_pct * 100, 1),
                }
            )
        if safe_pct > 0.01:
            drivers.append(
                {
                    "driver": "SAFE conversion",
                    "scenarios": [scenario_id],
                    "founder_impact_pp": round(safe_pct * 100, 1),
                }
            )
        if note_pct > 0.01:
            drivers.append(
                {
                    "driver": "Note conversion",
                    "scenarios": [scenario_id],
                    "founder_impact_pp": round(note_pct * 100, 1),
                }
            )
        if pool_topup > 0 and post_fd > 0:
            pool_topup_pct = pool_topup / post_fd
            if pool_topup_pct > 0.01:
                drivers.append(
                    {
                        "driver": "Option pool top-up",
                        "scenarios": [scenario_id],
                        "founder_impact_pp": round(pool_topup_pct * 100, 1),
                    }
                )
    # Sort by impact desc, top 5
    drivers.sort(key=lambda d: d["founder_impact_pp"], reverse=True)
    return drivers[:5]


def build_counsel_review_summary(
    counsel_packet: dict[str, Any],
) -> list[dict[str, Any]]:
    by_domain: dict[str, dict[str, Any]] = {}
    for item in counsel_packet.get("items", []):
        d = item.get("domain", "other")
        by_domain.setdefault(d, {"domain": d, "item_count": 0, "rule_ids": []})
        by_domain[d]["item_count"] += 1
        by_domain[d]["rule_ids"].append(item["rule_id"])
    return list(by_domain.values())


def build_date_sensitive_summary(rule_audit: dict[str, Any]) -> dict[str, int]:
    counts = {
        "in_window_count": 0,
        "near_end_count": 0,
        "near_start_count": 0,
        "pre_effective_count": 0,
        "expired_count": 0,
        "date_tracking_only_count": 0,
        "missing_event_date_count": 0,
    }
    for w in rule_audit.get("date_sensitive_watchlist", []):
        if w.get("scope") != "legal_tax_applicability":
            continue
        status = w.get("current_status")
        if status == "in_window":
            counts["in_window_count"] += 1
        elif status == "pre_effective":
            counts["pre_effective_count"] += 1
        elif status == "expired":
            counts["expired_count"] += 1
        elif status == "date_tracking_only":
            counts["date_tracking_only_count"] += 1
        elif status == "missing_event_date":
            counts["missing_event_date_count"] += 1
        if w.get("near_end_flag"):
            counts["near_end_count"] += 1
        if w.get("near_start_flag"):
            counts["near_start_count"] += 1
    return counts


def build_extraction_confidence(instruments: dict[str, Any]) -> dict[str, int]:
    counts = {
        "instruments_extracted": 0,
        "high_confidence": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
        "user_confirmations_outstanding": 0,
    }
    for category in ("safes", "convertible_notes", "warrants", "option_grants"):
        for item in instruments.get(category, []) or []:
            counts["instruments_extracted"] += 1
            conf = item.get("extraction_confidence", "high")
            if conf == "high":
                counts["high_confidence"] += 1
            elif conf == "medium":
                counts["medium_confidence"] += 1
                counts["user_confirmations_outstanding"] += 1
            elif conf == "low":
                counts["low_confidence"] += 1
                counts["user_confirmations_outstanding"] += 1
    return counts


def build_coaching_payload(
    *,
    artifacts: dict[str, dict[str, Any]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
) -> dict[str, Any]:
    """Build the per-rev15 coaching_payload block."""
    inputs = artifacts["inputs.json"]
    instruments = artifacts["instruments.json"]
    scenarios_doc = artifacts["scenarios.json"]
    rule_audit = artifacts["rule_audit.json"]
    counsel_packet = artifacts["counsel_packet.json"]

    scenarios = scenarios_doc.get("scenarios", [])
    # R4 LOW.b: defensive get — a scenario lacking computed_outputs would
    # otherwise KeyError here. Existing convention elsewhere in this file uses
    # `.get("computed_outputs", {}) or {}` (see line 464+); align this call.
    failed_items = [b for s in scenarios for b in ((s.get("computed_outputs", {}) or {}).get("blockers") or [])]
    high_severity = [
        {"warning_id": b["code"], "severity": "high", "title": b["code"], "detail": b["remedy"]} for b in failed_items
    ]

    # summary.passed / summary.failed are SCENARIO counts, not blocker counts. A
    # single scenario can carry several blockers, so counting blockers here would
    # let passed go negative (e.g. one scenario with 3 blockers in a 2-scenario
    # run). A scenario is "failed" iff it carries at least one blocker.
    failed_scenarios = sum(1 for s in scenarios if ((s.get("computed_outputs", {}) or {}).get("blockers") or []))
    passed_scenarios = len(scenarios) - failed_scenarios

    digest = build_scenario_digest(scenarios)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "passed": passed_scenarios,
            "failed": failed_scenarios,
            "warned": 0,
            "score_percent": None,
        },
        "failed_items": [{"code": b["code"], "detail": b["remedy"]} for b in failed_items],
        "warned_items": [],
        "high_severity_warnings": high_severity,
        "company_name": inputs.get("company_name", ""),
        "mode": inputs.get("mode", "standard"),
        "scenarios_modeled": len(scenarios),
        "counsel_review_count": len(counsel_packet.get("items", [])),
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
        "scenario_digest": digest,
        "ownership_range_across_scenarios": build_ownership_range(scenarios),
        "top_dilution_drivers": build_top_dilution_drivers(scenarios),
        "extraction_confidence": build_extraction_confidence(instruments),
        "counsel_review_summary": build_counsel_review_summary(counsel_packet),
        "date_sensitive_summary": build_date_sensitive_summary(rule_audit),
    }

    # flip_specifics only when applicable
    if inputs.get("mode") == "flip_focused" or any(s.get("type") == "flip" for s in scenarios):
        # Read from cap_state.outstanding_options[*].plan_type — the canonical
        # location per the v0.5.0 contract. compose_report is a pure consumer
        # of cap_state, not instruments.option_grants[].
        cs = artifacts["cap_state.json"]
        section_102 = sum(
            1 for o in cs.get("outstanding_options", []) or [] if (o.get("plan_type") or "").startswith("section_102")
        )
        iia = inputs.get("jurisdiction", {}).get("iia_grants_history", {}).get("has_grants", False)
        founders_count = len(cs.get("founders", []) or [])
        preferred_count = len(cs.get("preferred_series", []) or [])
        warrants_count = len(cs.get("outstanding_warrants", []) or [])
        founders = cs.get("founders", []) or []
        dual_class = any((f.get("common_class") or "class_a") != "class_a" for f in founders) or any(
            float(f.get("voting_rights_multiple") or 1.0) != 1.0 for f in founders
        )
        payload["flip_specifics"] = {
            "_note": "Present when mode=flip_focused or a flip scenario is modeled",
            "iia_grants_in_history": iia,
            "section_102_grants_outstanding": section_102,
            "estimated_holders_to_remap": founders_count + preferred_count,
            "warrants_outstanding_count": warrants_count,
            "preferred_class_count": preferred_count,
            "dual_class_present": dual_class,
        }
    else:
        payload["flip_specifics"] = None

    _assert_coaching_payload_privacy_clean(payload, instruments=instruments, inputs=inputs)
    return payload


def _assert_coaching_payload_privacy_clean(
    payload: dict[str, Any],
    *,
    instruments: dict[str, Any],
    inputs: dict[str, Any] | None = None,
) -> None:
    """Defense-in-depth privacy assertion.

    The Context B coaching dispatch contract requires `coaching_payload` to
    refer to investors and founders abstractly (no concrete names). Per
    `agents/cap-table.md` "Privacy boundary" (narrowed from "investor
    names AND founder names AND document text" to just "investor names AND
    founder names" — document text isn't structurally in the payload).

    This assertion walks every string in `payload` and rejects matches against:

    1. **Investor names** from `instruments.safes[].investor_name` and
       `instruments.convertible_notes[].investor_name` — the primary leak surface
       (extracted from source documents; must not surface in coaching).
    2. **Founder names** from `inputs.founders[].name` — included so the
       contract matches the agent body's
       privacy promise.

    Carve-outs (matches that are NOT leaks):

    - **Company-name overlap.** `inputs.company_name` is intentionally in the
      payload (it's the engagement identity). If a founder's name happens to
      equal or substring the company name (e.g., founder "Acme" at "Acme Corp"),
      the assertion would falsely fire. Skip founder names that case-insensitively
      overlap with `company_name`.
    - **Founder-becomes-investor.** Common in Israeli market: a founder later
      participates as an investor in their own company's SAFE / note round. The
      name then legitimately appears in BOTH `inputs.founders[]` AND
      `instruments.safes[].investor_name`. Skip names that appear in both
      lists — they're investors per the contract, but the assertion fires only
      on the investor side (which still gets refer-abstractly treatment).
    - **Length threshold (>8 chars)** filters short / common substrings
      ("SAFE", "Inc", "Capital", "LLC", "Corp") that frequently appear inside
      legitimate generic text.

    Match uses word-boundary regex (`\\b{name}\\b`) so substring collisions
    inside legitimate template prose ("capitalization", "Cap Capital") don't
    false-fire. `re.escape` protects against names with regex metacharacters.
    """
    import re as _re

    raw_investor_names = {
        s.get("investor_name", "")
        for s in instruments.get("safes", []) + instruments.get("convertible_notes", [])
        if s.get("investor_name")
    }
    raw_founder_names: set[str] = set()
    company_name = ""
    if inputs:
        company_name = inputs.get("company_name", "")
        raw_founder_names = {f.get("name", "") for f in inputs.get("founders", []) if f.get("name")}

    # Founder-becomes-investor carve-out: a name in BOTH founders and investors
    # is treated as an investor for the purpose of this check (subject to the
    # investor-side checks below). It's not a separate "founder name leak".
    founder_names = raw_founder_names - raw_investor_names

    # Company-name carve-out: a founder name that overlaps with the company
    # name is intentional (e.g., "Acme" founder at "Acme Corp"). Skip those.
    if company_name:
        cn_lower = company_name.lower()
        founder_names = {n for n in founder_names if n.lower() not in cn_lower and cn_lower not in n.lower()}

    # Length threshold filters short/common substrings.
    investor_names = {n for n in raw_investor_names if n and len(n) > 8}
    founder_names = {n for n in founder_names if n and len(n) > 8}

    if not investor_names and not founder_names:
        return

    def _walk(obj: Any) -> list[str]:
        out: list[str] = []
        if isinstance(obj, str):
            out.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                out.extend(_walk(v))
        elif isinstance(obj, list):
            for item in obj:
                out.extend(_walk(item))
        return out

    all_strings = _walk(payload)
    leaks: list[tuple[str, str, str]] = []  # (name_kind, name, sample)
    for kind, names in (("investor", investor_names), ("founder", founder_names)):
        for name in names:
            pat = _re.compile(r"\b" + _re.escape(name) + r"\b")
            for s in all_strings:
                if pat.search(s):
                    leaks.append((kind, name, s[:120]))
    if leaks:
        kind, name, sample = leaks[0]
        raise AssertionError(
            f"coaching_payload privacy-scrub violation: {len(leaks)} {kind} name leak(s). "
            f"First leak: {kind}_name={name!r} found in payload string: {sample!r}. "
            f"Context B dispatch contract requires investor + founder names to be scrubbed; "
            f"see agents/cap-table.md 'Privacy boundary'."
        )


def render_report_markdown(
    *,
    artifacts: dict[str, dict[str, Any]],
    validation_warnings: list[dict[str, Any]],
    insertion_marker: str,
) -> str:
    inputs = artifacts["inputs.json"]
    cap_state = artifacts["cap_state.json"]
    scenarios_doc = artifacts["scenarios.json"]
    rule_audit = artifacts["rule_audit.json"]
    counsel_packet = artifacts["counsel_packet.json"]
    scenarios = scenarios_doc.get("scenarios", [])
    counsel_count = len(counsel_packet.get("items", []))
    watchlist_count = len(rule_audit.get("date_sensitive_watchlist", []))

    lines = []
    lines.append(f"# Cap Table — {inputs.get('company_name', 'Company')}")
    lines.append("")

    # 1. Executive Summary (rule-driven template, NOT LLM narrative)
    lines.append("## Executive Summary")
    lines.append("")
    n = len(scenarios)
    completes = [s["computed_outputs"].get("completeness") for s in scenarios]
    full = sum(1 for c in completes if c == "full")
    structural = sum(1 for c in completes if c == "structural_only")
    repay = sum(1 for c in completes if c == "repay_only")
    mixed = sum(1 for c in completes if c == "mixed")
    lines.append(
        f"Modeled {n} scenario(s) for {inputs.get('company_name', 'this company')}: "
        f"{full} full, {mixed} mixed, {repay} repay-only, {structural} pending input."
    )
    lines.append(
        f"{counsel_count} counsel-review item(s) surfaced. {watchlist_count} date-sensitive item(s) in watchlist."
    )

    # Founder ownership range (only if any scenarios resolved)
    eligible = [
        s["computed_outputs"].get("aggregate_ownership_by_class", {})
        for s in scenarios
        if s["computed_outputs"].get("completeness") in {"full", "mixed"}
        and s["computed_outputs"].get("aggregate_ownership_by_class")
    ]
    if eligible:
        founder_pcts = [a.get("founders_pct", 0.0) for a in eligible]
        lines.append(
            f"Founder ownership ranges {_percent(min(founder_pcts))} "
            f"to {_percent(max(founder_pcts))} across resolved scenarios."
        )
    lines.append("")

    # W_AOA_ONLY_NO_INSTRUMENTS banner — surfaces when the engagement has no
    # instruments + has AoA findings. The cap_state.py warnings array carries
    # the warning code; render it as a preamble above Current Cap State so the
    # founder sees the engagement scope first.
    cap_state_warnings = cap_state.get("warnings") or []
    if any(w == "W_AOA_ONLY_NO_INSTRUMENTS" for w in cap_state_warnings):
        lines.append("> **AoA-only engagement detected.** No instruments to convert; this report renders the")
        lines.append("> Articles-of-Association findings and the current pre-financing cap state. To model")
        lines.append("> dilution scenarios, add SAFEs, convertible notes, option grants, or warrants to")
        lines.append("> `instruments.json`.")
        lines.append("")
    if any(w == "W_CAP_BASE_ASSUMED" for w in cap_state_warnings):
        lines.append("> ⚠ **Cap base ASSUMED, not founder-confirmed.** Founder share counts / option pool were")
        lines.append("> not confirmed (generic placeholder names or an explicit assumed flag) — ownership")
        lines.append("> figures below are DIRECTIONAL. Confirm the cap base before relying on these numbers.")
        lines.append("")
    if any(w == "W_FOUNDER_LOOKS_LIKE_INVESTOR" for w in cap_state_warnings):
        lines.append("> ⚠ **A listed founder resembles an investment entity** (name contains")
        lines.append("> Ventures/Capital/Fund). Confirm it is a founder, not an investor — mis-classifying an")
        lines.append("> investor as a founder distorts the ownership table.")
        lines.append("")

    # 2. Current Cap State
    lines.append("## Current Cap State")
    lines.append("")
    lines.append(f"As of: {cap_state.get('as_of_date', 'N/A')}")
    lines.append("")

    # Dual-class voting_pct rendering (§6.5): when any holder has
    # voting_rights_multiple != 1.0, switch from the aggregate FD table to a
    # per-holder breakdown with a voting_pct column. Detect across both
    # founders AND common_batches.
    founders_list = cap_state.get("founders") or []
    common_batches_list = cap_state.get("common_batches") or []
    has_dual_class = any(float(f.get("voting_rights_multiple") or 1.0) != 1.0 for f in founders_list) or any(
        float(b.get("voting_rights_multiple") or 1.0) != 1.0 for b in common_batches_list
    )

    fd = cap_state["as_converted_totals"]["fully_diluted_shares"]

    if has_dual_class:
        # Per-holder table with voting_pct column. Preferred is treated as
        # voting_rights_multiple=1.0 per the v0.5.0 §6.5 simplification (the
        # math doesn't model non-unity preferred voting; warn separately if
        # the input declares it).
        lines.append("| Holder | Class | Shares | Voting units | Voting % | FD % |")
        lines.append("|---|---|---:|---:|---:|---:|")
        rows: list[tuple[str, str, int, float, float]] = []
        for f in founders_list:
            cls = f.get("common_class") or "class_a"
            vrm = float(f.get("voting_rights_multiple") or 1.0)
            shares = int(f.get("common_shares") or 0)
            rows.append((f.get("name", "Founder"), cls, shares, vrm, shares * vrm))
        for b in common_batches_list:
            cls = b.get("common_class") or "class_a"
            vrm = float(b.get("voting_rights_multiple") or 1.0)
            shares = int(b.get("shares") or 0)
            rows.append((f"Batch {b.get('batch_id') or b.get('holder_id', '?')}", cls, shares, vrm, shares * vrm))
        # Preferred aggregated (v0.5.0 treats preferred VRM as 1.0)
        preferred_as_converted = int(cap_state["as_converted_totals"]["preferred_shares_as_converted"])
        if preferred_as_converted > 0:
            rows.append(
                ("Preferred (as-converted)", "preferred", preferred_as_converted, 1.0, float(preferred_as_converted))
            )
        options_outstanding = int(cap_state["as_converted_totals"]["options_outstanding"])
        if options_outstanding > 0:
            rows.append(("Options outstanding", "—", options_outstanding, 0.0, 0.0))  # options don't vote
        options_available = int(cap_state["as_converted_totals"]["options_available"])
        if options_available > 0:
            rows.append(("Options available", "—", options_available, 0.0, 0.0))
        warrants_underlying = int(cap_state["as_converted_totals"].get("warrants_underlying_total", 0))
        if warrants_underlying > 0:
            rows.append(("Warrants outstanding (vested)", "—", warrants_underlying, 0.0, 0.0))

        total_voting_units = sum(r[4] for r in rows)
        for name, cls, shares, vrm, voting_units in rows:
            voting_pct = voting_units / total_voting_units if total_voting_units else 0.0
            fd_pct = shares / fd if fd else 0.0
            vrm_label = f"{vrm:g}×" if vrm > 0 else "—"
            lines.append(
                f"| {name} | {cls} | {shares:,} | {vrm_label} → {int(voting_units):,} | "
                f"{_percent(voting_pct)} | {_percent(fd_pct)} |"
            )
        lines.append(
            f"| **Total fully-diluted** | | **{fd:,}** | **{int(total_voting_units):,}** | **100.0%** | **100.0%** |"
        )
        lines.append("")
        lines.append(
            "_Dual-class structure detected. Voting % reflects current voting power "
            "(shares × voting_rights_multiple); see `dual_class.founder_super_voting` "
            "counsel item for investor-objection considerations at later rounds._"
        )
    else:
        # Single-class engagement: aggregate FD table + per-founder rows.
        # Per-founder rows so founders see their own share counts by name.
        lines.append("| Holder | Shares (as-converted) | % of FD |")
        lines.append("|---|---:|---:|")
        # Per-founder rows (name, shares)
        for f in founders_list:
            fname = f.get("name") or "Founder"
            fshares = int(f.get("common_shares") or 0)
            fpct = fshares / fd if fd else 0.0
            lines.append(f"| {fname} | {fshares:,} | {_percent(fpct)} |")
        # Common batches (other common holders besides named founders)
        for b in common_batches_list:
            blabel = f"Batch {b.get('batch_id') or b.get('holder_id', '?')}"
            bshares = int(b.get("shares") or 0)
            bpct = bshares / fd if fd else 0.0
            lines.append(f"| {blabel} | {bshares:,} | {_percent(bpct)} |")
        # Aggregate remaining classes
        aggregate_classes = {
            "Preferred (as-converted)": cap_state["as_converted_totals"]["preferred_shares_as_converted"],
            "Options outstanding": cap_state["as_converted_totals"]["options_outstanding"],
            "Options available": cap_state["as_converted_totals"]["options_available"],
            "Warrants outstanding (vested)": cap_state["as_converted_totals"].get("warrants_underlying_total", 0),
        }
        for label, shares in aggregate_classes.items():
            if shares:
                pct = shares / fd if fd else 0.0
                lines.append(f"| {label} | {shares:,} | {_percent(pct)} |")
        lines.append(f"| **Total fully-diluted** | **{fd:,}** | **100.0%** |")
    lines.append("")
    safes = cap_state.get("outstanding_safes", [])
    notes = cap_state.get("outstanding_notes", [])
    warrants = cap_state.get("outstanding_warrants", [])
    if safes:
        lines.append(f"Outstanding SAFEs: {len(safes)}")
    if notes:
        lines.append(f"Outstanding convertible notes: {len(notes)}")
    if warrants:
        unvested = sum(1 for w in warrants if not w.get("vested_flag", False))
        vested = len(warrants) - unvested
        warrant_note = f"Outstanding warrants: {len(warrants)} ({vested} vested, {unvested} unvested)"
        lines.append(warrant_note)
    if safes or notes or warrants:
        lines.append("")

    # Dedicated AoA Findings section when cap_state.aoa_findings has any
    # non-default value (i.e., the AoA was actually extracted). For AoA-only
    # engagements this is the primary deliverable; for others it surfaces the
    # findings the rules are gating on.
    aoa = cap_state.get("aoa_findings") or {}
    aoa_has_data = any(v is not None and v is not False for v in aoa.values())
    if aoa_has_data:
        lines.append("## Articles of Association — Extracted Findings")
        lines.append("")
        lines.append("| Finding | Value |")
        lines.append("|---|---|")
        _aoa_render_map: list[tuple[str, str, Any]] = [
            ("Pay-to-play detected", "pay_to_play_detected", "bool"),
            ("Drag-along threshold", "drag_along_threshold_pct", "pct"),
            ("§102 plan reference present", "section_102_plan_reference", "bool"),
            ("Ratchet anti-dilution detected", "ratchet_anti_dilution_detected", "bool"),
            ("Liquidation preference > 1x", "liquidation_preference_above_1x", "bool"),
            ("Participation present", "participation_present", "bool"),
            ("Dividend provisions present", "dividend_provisions_present", "bool"),
            ("Protective provisions below 75%", "protective_provisions_below_75_pct", "bool"),
            ("Bring-along threshold", "bring_along_threshold_pct", "pct"),
        ]
        for label, key, fmt in _aoa_render_map:
            val = aoa.get(key)
            if val is None:
                rendered = "_Not extracted_"
            elif fmt == "bool":
                rendered = "Yes" if val else "No"
            elif fmt == "pct":
                rendered = f"{val}%"
            else:
                rendered = str(val)
            lines.append(f"| {label} | {rendered} |")
        lines.append("")

    # 3. Scenarios Modeled
    lines.append("## Scenarios Modeled")
    lines.append("")
    if not scenarios:
        # Sentinel when no scenarios runnable (AoA-only, empty-instruments
        # engagements). Narrate the absence rather than leaving the founder
        # with an unexplained empty section.
        lines.append(
            "_No scenarios runnable for this engagement. This is expected when only Articles of "
            "Association have been extracted (no SAFEs, notes, option grants, or warrants present). "
            "Add instruments to `instruments.json` to model conversion and dilution scenarios._"
        )
        lines.append("")
    for s in scenarios:
        lines.append(f"### {s.get('label', s['scenario_id'])} ({_labels.humanize('scenario_type', s['type'])})")
        lines.append("")
        co = s["computed_outputs"]
        completeness = co.get("completeness", "structural_only")
        lines.append(f"**Stage:** {_labels.md_term('completeness', completeness)}")
        if co.get("cap_implied_only"):
            lines.append(f"_{_labels.CAP_IMPLIED_GLOSS}_")
        lines.append("")
        # Inputs
        params = s.get("parameters", {})
        if params:
            lines.append("**Inputs:**")
            for k, v in params.items():
                if v is not None and v != "":
                    lines.append(f"- `{k}`: {v}")
            lines.append("")
        # Blockers
        blockers = co.get("blockers", [])
        if blockers:
            lines.append("**Blockers (must resolve to upgrade to full):**")
            for b in blockers:
                lines.append(
                    f"- `{b['code']}`{(' on ' + b['instance_id']) if b.get('instance_id') else ''}: {b['remedy']}"
                )
            lines.append("")
        # Math outputs (when full/mixed)
        if completeness in {"full", "mixed"} and co.get("aggregate_ownership_by_class"):
            agg = co["aggregate_ownership_by_class"]
            # When AD fires, show three-way headline (pre-AD baseline /
            # coupled with-AD / delta) so founders understand the AD impact.
            ad_breakdown = co.get("anti_dilution_breakdown") or []
            if ad_breakdown:
                pre_ad_founder = agg.get("founders_pct_pre_anti_dilution")
                post_ad_founder = agg.get("founders_pct")
                ad_delta = agg.get("anti_dilution_delta_pct_points")
                if pre_ad_founder is not None and post_ad_founder is not None:
                    lines.append("**Founder ownership (anti-dilution-aware):**")
                    lines.append(
                        f"- Pre-AD baseline: {_percent(pre_ad_founder)} (what your % would be if AD had not triggered)"
                    )
                    lines.append(f"- Post-AD (coupled equilibrium): **{_percent(post_ad_founder)}** ← headline")
                    if ad_delta is not None:
                        sign = "-" if ad_delta < 0 else "+"
                        lines.append(
                            f"- AD impact: **{sign}{abs(ad_delta):.2f} pp** of additional dilution from anti-dilution adjustment"
                        )
                    lines.append("")
            lines.append("**Post-round ownership:**")
            # Skip the AD comparison fields here — they're rendered in
            # the three-way headline block above, and the delta field is in
            # percentage points (not a fraction), so _percent() would
            # double-encode it as "−256.6%" instead of "-2.57 pp".
            _ad_meta_fields = {
                "founders_pct_pre_anti_dilution",
                "preferred_pct_pre_anti_dilution",
                "anti_dilution_delta_pct_points",
            }
            # founders_by_class is a map, not a scalar pct; render it
            # separately as a sub-list when dual-class is present.
            _structured_fields = {"founders_by_class"}
            for k, v in agg.items():
                if k in _ad_meta_fields or k in _structured_fields:
                    continue
                lines.append(f"- {k.replace('_', ' ')}: {_percent(v)}")
            fbc = agg.get("founders_by_class") or {}
            if len(fbc) > 1 or (fbc and "class_a" not in fbc):
                # Render only when meaningful: more than one class, or a single
                # non-class_a (unusual). Single-class_a-only engagements get
                # the aggregate founders_pct line above.
                lines.append("- founders by class:")
                for cls, pct in sorted(fbc.items()):
                    lines.append(f"  - {cls}: {_percent(pct)}")
            lines.append("")
            # Per-series AD breakdown
            if ad_breakdown:
                lines.append("**Anti-dilution adjustments (per series):**")
                for bd in ad_breakdown:
                    sid = bd.get("series_id", "?")
                    ptype = bd.get("protection_type", "?")
                    ccp_before = bd.get("ccp_before", 0)
                    ccp_after = bd.get("ccp_after", 0)
                    floor_note = " (floor clamped)" if bd.get("floor_applied") else ""
                    lines.append(
                        f"- {sid} ({ptype.replace('_', ' ')}): CCP ${ccp_before:.4f} → ${ccp_after:.4f}{floor_note} "
                        f"(rule: `{bd.get('rule_id')}`)"
                    )
                lines.append("")
            if co.get("equity_financing_price"):
                lines.append(f"**Equity financing price:** ${co['equity_financing_price']:.4f}/share")
                lines.append("")
            fi = co.get("founder_impact")
            if fi:
                lines.append(f"**Founder Impact Lens:** {fi['plain_language']}")
                lines.append("")
        if completeness == "structural_only" and co.get("cap_implied_only"):
            ps = co.get("per_safe", {})
            if ps:
                lines.append("**Cap-implied ownership (pre-financing):**")
                for sid, r in ps.items():
                    if "cap_implied_ownership" in r:
                        lines.append(
                            f"- {sid}: {_percent(r['cap_implied_ownership'])} cap-implied "
                            f"(safe_price ${r['safe_price']:.4f}, {int(r['cap_implied_shares']):,} shares)"
                        )
                lines.append("")
        if completeness == "repay_only" and co.get("aggregate_cash_repayment"):
            lines.append(f"**Cash repayment:** {_money(co['aggregate_cash_repayment'])}")
            lines.append("")

        # Shares breakdown (post-round composition table): pre-round FD → + converted
        # SAFEs → + pool top-up → + new money → = post-FD. Rendered when available.
        shares_breakdown = co.get("shares_breakdown") or {}
        if shares_breakdown and isinstance(shares_breakdown, dict):
            pre_fd = shares_breakdown.get("pre_round_fd")
            safe_shares = shares_breakdown.get("safe_converted_shares") or shares_breakdown.get("safe_shares")
            note_shares = shares_breakdown.get("note_converted_shares") or shares_breakdown.get("note_shares")
            pool_shares = shares_breakdown.get("pool_topup_shares") or shares_breakdown.get("option_pool_shares")
            new_money_shares = shares_breakdown.get("new_money_shares") or shares_breakdown.get("investor_shares")
            post_fd = shares_breakdown.get("post_round_fd") or shares_breakdown.get("post_fd")
            if pre_fd is not None or post_fd is not None:
                lines.append("**Post-round share composition:**")
                lines.append("")
                lines.append("| Component | Shares | Post-round % |")
                lines.append("|-----------|-------:|-------------:|")
                _total_denom = post_fd if post_fd else None

                def _pct(n: int | float | None, denom: int | float | None) -> str:
                    if n is None or denom is None or denom == 0:
                        return "—"
                    return f"{n / denom * 100:.1f}%"

                if pre_fd is not None:
                    lines.append(f"| Pre-round FD | {int(pre_fd):,} | {_pct(pre_fd, _total_denom)} |")
                if safe_shares:
                    lines.append(f"| + SAFE converted | {int(safe_shares):,} | {_pct(safe_shares, _total_denom)} |")
                if note_shares:
                    lines.append(f"| + Notes converted | {int(note_shares):,} | {_pct(note_shares, _total_denom)} |")
                if pool_shares:
                    lines.append(f"| + Pool top-up | {int(pool_shares):,} | {_pct(pool_shares, _total_denom)} |")
                if new_money_shares:
                    lines.append(
                        f"| + New money (investors) | {int(new_money_shares):,} | {_pct(new_money_shares, _total_denom)} |"
                    )
                if post_fd is not None:
                    lines.append(f"| **= Post-round FD** | **{int(post_fd):,}** | **100.0%** |")
                lines.append("")

        # Per-instrument narrative — keyed on non-empty per_note/per_safe rather
        # than scenario type so priced_round scenarios that populate these fields
        # (fully-coupled solver produces per_safe/per_note for every instrument
        # that participates in the round) also get the conversion-math tables.
        per_note = co.get("per_note") or {}
        if per_note:
            lines.append("**Per-note conversion math:**")
            lines.append("")
            lines.append("| Note | Branch | Accrued interest | Conversion price | Conversion shares |")
            lines.append("|---|---|---:|---:|---:|")
            for nid, r in per_note.items():
                branch = r.get("branch", "—")
                ai = r.get("accrued_interest")
                cp = r.get("conversion_price")
                shares = r.get("conversion_shares")
                lines.append(
                    f"| `{nid}` | `{branch}` | "
                    f"{_money(ai) if ai is not None else '—'} | "
                    f"{('$' + format(cp, '.4f')) if cp is not None else '—'} | "
                    f"{(f'{int(shares):,}') if shares is not None else '—'} |"
                )
            lines.append("")
        per_safe = co.get("per_safe") or {}
        # Render only when there are rows that are NOT the cap_implied_only snapshot
        per_safe_rows = {sid: r for sid, r in per_safe.items() if "cap_implied_ownership" not in r}
        if per_safe_rows:
            lines.append("**Per-SAFE conversion math:**")
            lines.append("")
            lines.append("| SAFE | Branch | Purchase ÷ Cap | Conversion price | Conversion shares |")
            lines.append("|---|---|---|---:|---:|")
            for sid, r in per_safe_rows.items():
                branch = r.get("branch", "—")
                cp = r.get("conversion_price")
                shares = r.get("conversion_shares")
                # Derivation sentence: purchase ÷ cap = % → shares
                purchase = r.get("purchase_amount")
                cap = r.get("post_money_cap") or r.get("valuation_cap")
                deriv = "—"
                if purchase is not None and cap is not None and cap > 0:
                    pct_of_cap = purchase / cap
                    deriv = f"{_money(purchase)} ÷ {_money(cap)} = {pct_of_cap * 100:.2f}%"
                lines.append(
                    f"| `{sid}` | `{branch}` | {deriv} | "
                    f"{('$' + format(cp, '.4f')) if cp is not None else '—'} | "
                    f"{(f'{int(shares):,}') if shares is not None else '—'} |"
                )
            lines.append("")

        # Pre-round warrant pump events table. When the pump fires (warrant
        # exercise_event_date < scenario transaction_event_date), founders see
        # exactly which warrants exercised, at what FMV, and how many shares
        # entered the pre-financing FD.
        warrant_events = co.get("warrant_exercise_events") or []
        if warrant_events:
            lines.append("**Pre-round warrant pump events:**")
            lines.append("")
            lines.append("| Warrant | Settlement | Exercised at | Shares added | FMV approximated? |")
            lines.append("|---|---|---:|---:|---|")
            for evt in warrant_events:
                wid = evt.get("warrant_id", "?")
                stype = evt.get("settlement_type", "?")
                pps = evt.get("exercised_at_pps")
                shares = evt.get("shares_added")
                approx = "Yes" if evt.get("fmv_approximation_used") else "No"
                lines.append(
                    f"| `{wid}` | `{stype}` | "
                    f"{('$' + format(pps, '.4f')) if pps is not None else '—'} | "
                    f"{(f'{int(shares):,}') if shares is not None else '—'} | "
                    f"{approx} |"
                )
            lines.append("")
            if any(e.get("fmv_approximation_used") for e in warrant_events):
                lines.append(
                    "_FMV approximation: when no prior priced round exists, the pump used "
                    "`pre_money / pre_pump_FD` as FMV. See `warrant.net_share_pre_round_fmv_approximation` "
                    "counsel item — sub-percent divergence from the converged PPS for typical warrants; "
                    "material for warrants that are a large fraction of FD._"
                )
                lines.append("")

        # Math provenance footer
        prov = co.get("math_provenance", [])
        if prov:
            unique_rules = sorted({p["rule_id"] for p in prov if p.get("rule_id")})
            override_count = sum(1 for p in prov if p.get("source_type") == "counsel_supplied_override")
            footer_parts = []
            if unique_rules:
                footer_parts.append("rules: " + ", ".join(f"`{r}`" for r in unique_rules))
            if override_count:
                footer_parts.append(f"{override_count} counsel-supplied override(s)")
            lines.append(f"_Provenance: {'; '.join(footer_parts)}_")
            lines.append("")

    # 4. Scenario Comparison (when ≥2 scenarios)
    if len(scenarios) >= 2:
        lines.append("## Scenario Comparison")
        lines.append("")
        lines.append("| Scenario | Stage | Founder %  | Equity Price |")
        lines.append("|---|---|---:|---:|")
        for s in scenarios:
            co = s["computed_outputs"]
            agg = co.get("aggregate_ownership_by_class", {})
            fp = _percent(agg.get("founders_pct", 0.0)) if agg else "—"
            ep = f"${co.get('equity_financing_price', 0):.4f}" if co.get("equity_financing_price") else "—"
            stage = _labels.humanize("completeness", co.get("completeness"))
            lines.append(f"| {s.get('label', s['scenario_id'])} | {stage} | {fp} | {ep} |")
        lines.append("")

    # 5. Counsel Review Required
    if counsel_packet.get("items"):
        lines.append("## Counsel Review Required")
        lines.append("")
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for it in counsel_packet["items"]:
            by_domain.setdefault(it.get("domain", "other"), []).append(it)
        for domain in sorted(by_domain.keys()):
            lines.append(f"### {domain.replace('_', ' ').title()}")
            for it in by_domain[domain]:
                lines.append(
                    f"- {_rule_md(it['rule_id'], item_title=it.get('title'), item_source_ids=it.get('source_ids'), bold=True)}"
                )
                if it.get("counsel_question"):
                    lines.append(f"  - {it['counsel_question']}")
            lines.append("")

    # 5b. Source Notes (behavior_target=source_note rules)
    source_notes = rule_audit.get("source_notes") or []
    if source_notes:
        lines.append("## Source Notes")
        lines.append("")
        lines.append(
            "_Informational citations for cap-table conventions applied above. Each note is "
            "tied to a rule in the rule pack with its primary-source citations._"
        )
        lines.append("")
        by_domain_sn: dict[str, list[dict[str, Any]]] = {}
        for sn in source_notes:
            by_domain_sn.setdefault(sn.get("domain", "other"), []).append(sn)
        for domain in sorted(by_domain_sn.keys()):
            lines.append(f"### {domain.replace('_', ' ').title()}")
            for sn in by_domain_sn[domain]:
                lines.append(
                    f"- {_rule_md(sn['rule_id'], item_title=sn.get('title'), item_source_ids=sn.get('source_ids'), bold=True)}"
                )
                if sn.get("summary"):
                    lines.append(f"  - {sn['summary']}")
            lines.append("")

    # 6. Date-Sensitive Watchlist (split into active vs for-reference)
    if rule_audit.get("date_sensitive_watchlist"):
        active_items: list[dict[str, Any]] = []
        annotation_items: list[dict[str, Any]] = []
        for w in rule_audit["date_sensitive_watchlist"]:
            # `applies_when_matched=true` means the rule's own predicate said
            # it applies to this engagement (e.g., Israeli rules in an
            # Israel-context engagement, IIA rules when grants are present).
            # `false` means the rule is structurally inapplicable here —
            # surface as a for-reference annotation, not an action item, so
            # founders don't panic over 50 items that don't apply.
            if w.get("applies_when_matched", True):
                active_items.append(w)
            else:
                annotation_items.append(w)

        if active_items:
            lines.append("## Date-Sensitive Watchlist")
            lines.append("")
            lines.append(f"_{len(active_items)} active item(s) — rules whose predicates match this engagement._")
            lines.append("")
            lines.append("| Rule | Scope | Status | Date | Action |")
            lines.append("|---|---|---|---|---|")
            for w in active_items:
                status_or_fresh = w.get("current_status") or w.get("freshness_status")
                date_val = w.get("event_date_value") or "—"
                lines.append(
                    f"| {_rule_md(w['rule_id'], item_title=w.get('title'))} | {_labels.humanize('scope', w.get('scope'))} | "
                    f"{_labels.humanize('status', status_or_fresh)} | {date_val} | "
                    f"{w.get('action_required', '')[:60]} |"
                )
            lines.append("")
        if annotation_items:
            lines.append("### For-Reference Annotations")
            lines.append("")
            lines.append(
                f"_{len(annotation_items)} item(s) — rules that don't apply to this engagement "
                f"in its current state (different jurisdiction, no grants, etc.) but are tracked "
                f"in case the engagement evolves. No action needed today._"
            )
            lines.append("")

    # 7. Sources Cited (dedup across counsel + scenarios)
    sources_used = set()
    for it in counsel_packet.get("items", []):
        sources_used.update(it.get("source_ids", []))
    if sources_used:
        lines.append("## Sources Cited")
        lines.append("")
        for src in sorted(sources_used):
            lines.append(f"- `{src}`")
        lines.append("")

    # Validation warnings (always emitted, even when empty for visibility)
    if validation_warnings:
        lines.append("## Validation Warnings")
        lines.append("")
        for w in validation_warnings:
            code = w.get("code", "WARNING")
            msg = w.get("message", "")
            lines.append(f"- **{code}**: {msg}")
        lines.append("")

    # 8. Coaching Commentary insertion marker
    lines.append("---")
    lines.append("")
    lines.append(insertion_marker)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc) — Cap Table Agent"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*"
    )

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", required=True, help="Directory containing canonical artifacts")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True, help="report.json output path")
    p.add_argument("--write-md", required=True, help="report.md output path")
    p.add_argument("--strict", action="store_true", help="Exit 1 on high-severity validation warnings")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    # Load all required artifacts
    artifacts: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_ARTIFACTS:
        path = os.path.join(args.dir, name)
        if not os.path.exists(path):
            sys.stderr.write(f"compose_report.py: missing required artifact: {path}\n")
            return 1
        artifacts[name] = _load(path)

    # Validate run_id parity
    validation_warnings = validate_run_id_parity(artifacts)

    # Generate per-run uuid for the insertion marker
    run_uuid = uuid.uuid4().hex[:8]
    insertion_marker = f"<!-- COACHING_INSERTION_POINT_{run_uuid} -->"

    # Build report.md
    report_md = render_report_markdown(
        artifacts=artifacts,
        validation_warnings=validation_warnings,
        insertion_marker=insertion_marker,
    )

    # Write report.md
    md_path = os.path.abspath(args.write_md)
    os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    # Build coaching_payload
    review_dir = os.path.abspath(args.dir)
    coaching_payload = build_coaching_payload(
        artifacts=artifacts,
        review_dir=review_dir,
        report_path=md_path,
        insertion_marker=insertion_marker,
    )

    # Assemble report.json (pre-coaching markdown + coaching_payload)
    report_json: dict[str, Any] = {
        "report_markdown": report_md,
        "validation": {"warnings": validation_warnings},
        "coaching_payload": coaching_payload,
        "metadata": {"run_id": args.run_id, "produced_by": "compose_report.py"},
    }

    # Write report.json
    json_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    if args.pretty:
        text = json.dumps(report_json, indent=2, sort_keys=False) + "\n"
    else:
        text = json.dumps(report_json, sort_keys=False) + "\n"
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Post-write verification — non-zero exit if files are missing/empty
    if not os.path.exists(md_path) or os.path.getsize(md_path) == 0:
        sys.stderr.write(f"compose_report.py: report.md missing or empty at {md_path}\n")
        return 2
    if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
        sys.stderr.write(f"compose_report.py: report.json missing or empty at {json_path}\n")
        return 2

    receipt = {
        "ok": True,
        "report_json": json_path,
        "report_md": md_path,
        "insertion_marker": insertion_marker,
        "validation_warnings": len(validation_warnings),
    }
    print(json.dumps(receipt, indent=2 if args.pretty else None))

    # Print warnings to stderr for visibility
    for w in validation_warnings:
        sys.stderr.write(f"  WARNING [{w.get('code')}]: {w.get('message')}\n")
    if args.pretty:
        sys.stderr.write(
            f"  scenarios: {len(artifacts['scenarios.json']['scenarios'])} | "
            f"counsel items: {len(artifacts['counsel_packet.json']['items'])} | "
            f"watchlist: {len(artifacts['rule_audit.json']['date_sensitive_watchlist'])}\n"
        )

    # --strict exits 1 on any high-severity warning (currently MISSING_METADATA + STALE_ARTIFACT)
    high_severity_codes = {"MISSING_METADATA", "STALE_ARTIFACT"}
    if args.strict and any(w.get("code") in high_severity_codes for w in validation_warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
