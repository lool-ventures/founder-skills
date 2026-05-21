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

Schema version: `v0.5.0-cap-table`. v0.5.0 adds the evidence-verification
+ invariant-check fields to the per-instrument shape. Backward-compatible
read: consumers reading v0.4.2 inputs MUST treat the new fields
(evidence_verification, backward_verification, invariant_checks) as
optional and fall back to v0.4.2 semantics when absent. The compat window
accepts both versions on input; emits v0.5.0 on output.

Per Codex rev17 P2-8: math_provenance uses source_type + (rule_id +
rule_pack_version | source_ref) — see scenarios.json schema.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

SCHEMA_VERSION = "v0.5.0-cap-table"
SCHEMA_VERSION_COMPAT_FLOOR = "v0.4.2-cap-table"  # accepts inputs at this version too
COMPAT_VERSIONS = (SCHEMA_VERSION_COMPAT_FLOOR, SCHEMA_VERSION)

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
        scenario_id = s["scenario_id"]
        new_money_pct = agg.get("new_money_pct", 0.0)
        safe_pct = agg.get("safe_pct", 0.0)
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
    for category in ("safes", "notes", "warrants", "option_grants"):
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
    failed_items = [b for s in scenarios for b in (s["computed_outputs"].get("blockers") or [])]
    high_severity = [
        {"warning_id": b["code"], "severity": "high", "title": b["code"], "detail": b["remedy"]} for b in failed_items
    ]

    digest = build_scenario_digest(scenarios)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "passed": len(scenarios) - len(failed_items),
            "failed": len(failed_items),
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
        section_102 = sum(
            1 for g in instruments.get("option_grants", []) if g.get("plan_type", "").startswith("section_102")
        )
        iia = inputs.get("jurisdiction", {}).get("iia_grants_history", {}).get("has_grants", False)
        founders_count = len(artifacts["cap_state.json"].get("founders", []))
        preferred_count = len(artifacts["cap_state.json"].get("preferred_series", []))
        payload["flip_specifics"] = {
            "_note": "Present when mode=flip_focused or a flip scenario is modeled",
            "iia_grants_in_history": iia,
            "section_102_grants_outstanding": section_102,
            "estimated_holders_to_remap": founders_count + preferred_count,
        }
    else:
        payload["flip_specifics"] = None

    return payload


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

    # 2. Current Cap State
    lines.append("## Current Cap State")
    lines.append("")
    lines.append(f"As of: {cap_state.get('as_of_date', 'N/A')}")
    lines.append("")
    lines.append("| Holder class | Shares (as-converted) | % of FD |")
    lines.append("|---|---:|---:|")
    fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    pcts = {
        "Founders (common)": cap_state["as_converted_totals"]["common_shares"],
        "Preferred (as-converted)": cap_state["as_converted_totals"]["preferred_shares_as_converted"],
        "Options outstanding": cap_state["as_converted_totals"]["options_outstanding"],
        "Options available": cap_state["as_converted_totals"]["options_available"],
    }
    for label, shares in pcts.items():
        pct = shares / fd if fd else 0.0
        lines.append(f"| {label} | {shares:,} | {_percent(pct)} |")
    lines.append(f"| **Total fully-diluted** | **{fd:,}** | **100.0%** |")
    lines.append("")
    safes = cap_state.get("outstanding_safes", [])
    notes = cap_state.get("outstanding_notes", [])
    if safes:
        lines.append(f"Outstanding SAFEs: {len(safes)}")
    if notes:
        lines.append(f"Outstanding convertible notes: {len(notes)}")
    if safes or notes:
        lines.append("")

    # 3. Scenarios Modeled
    lines.append("## Scenarios Modeled")
    lines.append("")
    for s in scenarios:
        lines.append(f"### {s.get('label', s['scenario_id'])} ({s['type']})")
        lines.append("")
        co = s["computed_outputs"]
        completeness = co.get("completeness", "structural_only")
        lines.append(f"**Completeness:** `{completeness}`")
        if co.get("cap_implied_only"):
            lines.append("**Sub-flag:** `cap_implied_only` — pre-financing snapshot only")
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
            lines.append("**Post-round ownership:**")
            for k, v in agg.items():
                lines.append(f"- {k.replace('_', ' ')}: {_percent(v)}")
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
        lines.append("| Scenario | Completeness | Founder %  | Equity Price |")
        lines.append("|---|---|---:|---:|")
        for s in scenarios:
            co = s["computed_outputs"]
            agg = co.get("aggregate_ownership_by_class", {})
            fp = _percent(agg.get("founders_pct", 0.0)) if agg else "—"
            ep = f"${co.get('equity_financing_price', 0):.4f}" if co.get("equity_financing_price") else "—"
            lines.append(f"| {s.get('label', s['scenario_id'])} | {co.get('completeness')} | {fp} | {ep} |")
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
                lines.append(f"- **{it['title']}** (`{it['rule_id']}`)")
                if it.get("counsel_question"):
                    lines.append(f"  - {it['counsel_question']}")
            lines.append("")

    # 6. Date-Sensitive Watchlist
    if rule_audit.get("date_sensitive_watchlist"):
        lines.append("## Date-Sensitive Watchlist")
        lines.append("")
        lines.append("| Rule | Scope | Status | Date | Action |")
        lines.append("|---|---|---|---|---|")
        for w in rule_audit["date_sensitive_watchlist"]:
            status_or_fresh = w.get("current_status") or w.get("freshness_status") or "—"
            date_val = w.get("event_date_value") or "—"
            lines.append(
                f"| `{w['rule_id']}` | {w['scope']} | {status_or_fresh} | {date_val} | "
                f"{w.get('action_required', '')[:60]} |"
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
    lines.append("*Report generated by cap-table skill. Rule pack v0.2.8.*")

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
