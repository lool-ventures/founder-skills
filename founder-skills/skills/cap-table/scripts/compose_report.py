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
import _artifact_writer  # noqa: E402
import _labels  # noqa: E402
import _rules  # noqa: E402
import _warning_callouts  # noqa: E402
from compose_extraction_report import (  # noqa: E402
    _load_ambiguity_map,
    _load_amendment_deltas,
    _load_terms_doc,
    _terms_section,
)

SCHEMA_VERSION = "v0.5.0-cap-table"
_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "schemas")
RECONCILIATION_TOLERANCE_PPM = 1000  # 0.1%; matches the W_FD_RECONCILE_DELTA threshold in cap_state.py

# Markers that make a `stated_totals.source` string SELF-REFERENTIAL — i.e. it names one of the
# skill's own artifacts/outputs rather than the founder's source document. Per SKILL.md
# "Non-circularity rule": the whole point of the reconciliation cross-foot is that the stated figure
# comes from a source INDEPENDENT of the skill's own math; a source that names the skill's own output
# cannot back that up, even when it happens to be spelled correctly. Kept short and specific (rather
# than generic tokens like "model") to avoid false-firing on legitimate sources such as
# "carta_summary" / "freeform_grid" / "pro_forma_grid" / "term_sheet".
_SELF_REFERENTIAL_SOURCE_MARKERS = (
    "scenarios.json",
    "scenario.json",
    "report.json",
    "cap_state.json",
    "computed",
    "calculated",
    "derived",
    "this report",
    "this skill",
    "the skill",
    "skill output",
    "skill_output",
    "skill-output",
    "model output",
    "model_output",
    "model-output",
)


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


def _rule_md(
    rule_id: str,
    *,
    item_title: str | None = None,
    item_source_ids: list[str] | None = None,
    bold: bool = False,
    compact: bool = False,
) -> str:
    """Readable rule reference for Markdown: title linked to its primary source.
    Full form adds extra 'also' links + the raw rule_id; `compact=True` (for
    dense tables) keeps just the linked title."""
    ref = _rules.rule_ref(rule_id, item_title=item_title, item_source_ids=item_source_ids)
    title = str(ref["title"])
    links = ref["links"]
    title_part = f"[{title}]({links[0][1]})" if links else title
    if bold:
        title_part = f"**{title_part}**"
    if compact:
        return title_part
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


def _batch_label(b: dict[str, Any]) -> str:
    """Display label for a common batch. common_batches has no name field like founders[].name, so
    prefer an explicit holder_name; otherwise fall back to the 'Batch <id>' form (batch_id, else
    holder_id)."""
    name = b.get("holder_name")
    if isinstance(name, str) and name.strip():
        return name
    return f"Batch {b.get('batch_id') or b.get('holder_id', '?')}"


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
            _tb_assumed = any((w or {}).get("code") == "target_basis_defaulted" for w in (co.get("warnings") or []))
            _basis_label = params.get("target_basis", "pre_money").replace("_", " ")
            _basis_suffix = " (basis assumed — not stated)" if _tb_assumed else ""
            drivers.append(f"Pool top-up to {params['target_pool_percent']:.0%} {_basis_label}{_basis_suffix}")
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
    reconciliation_status: str | None = None,
    reconciliation_max_divergence_ppm: float | None = None,
) -> dict[str, Any]:
    """Build the per-rev15 coaching_payload block.

    `reconciliation_status` / `reconciliation_max_divergence_ppm` mirror the top-level
    `report.json` fields of the same computation (`compute_reconciliation_status`) — passed in
    by the caller rather than recomputed here so the coaching commentary can cite a computed
    price-per-share / fully-diluted figure that disagrees with the founder's own source document.
    Optional so existing callers/tests that don't care about reconciliation keep working; a caller
    that omits them gets `"not_applicable"` / `0.0`, matching `compute_reconciliation_status`'s own
    no-stated-terms result rather than a silent None.
    """
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
        # Same computation as the top-level report.json fields (see compute_reconciliation_status);
        # threaded through so a computed PPS / fully-diluted figure that disagrees with the
        # founder's own source document is reachable from the coaching commentary, not just a
        # field the dispatch structurally never sees.
        "reconciliation": {
            "status": reconciliation_status if reconciliation_status is not None else "not_applicable",
            "max_divergence_ppm": reconciliation_max_divergence_ppm
            if reconciliation_max_divergence_ppm is not None
            else 0.0,
        },
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
            # Distinguishes "0 §102 grants" from "no per-grant data captured" — a flip that left
            # option_grants[] empty reports 0, which the coaching layer must not read as "no §102 exposure".
            "option_grant_detail_available": bool(cs.get("outstanding_options")),
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


def build_disclosure_banner(*, covered: bool, reconciliation_status: str, max_divergence_ppm: float) -> str:
    """Return a markdown blockquote banner for the report header, or '' when covered and passing.

    Non-empty variants:
    - uncovered: provisional/counsel language when the deal was not fully handled by the pipeline.
    - covered+diverged: divergence percentage when computed terms differ from source-stated terms.
    - covered+circular: a stated total exactly matches the computed figure but its provenance is
      missing or self-referential — a false-green cross-foot (see
      `refine_reconciliation_status_for_provenance`).
    - covered+cannot_verify: a stated total has no usable provenance, so the match cannot be
      trusted (degraded, not a confirmed match).
    covered+pass returns an empty string (no banner emitted).
    """
    if not covered:
        return (
            "> ⚠️ **Computed outside the validated cap-table engine.** This deal combines primitives the "
            "deterministic pipeline does not fully cover; figures are provisional — confirm with counsel."
        )
    if reconciliation_status == "diverged":
        pct = max_divergence_ppm / 10_000.0
        return f"> ⚠️ **Computed figures diverge from source-stated terms by ~{pct:.1f}%.** Review before relying."
    if reconciliation_status == "circular":
        return (
            "> ⚠️ **Circular reconciliation detected.** A stated total matches the skill's own computed "
            "figure exactly, but its source is missing or names the skill's own output — not an "
            "independent confirmation. Treat the reconciliation section as unverified."
        )
    if reconciliation_status == "cannot_verify":
        return (
            "> ⚠️ **Reconciliation cannot be verified.** A stated total has no source citing which "
            "document it was read from, so the match against computed figures is unconfirmed."
        )
    return ""


def _render_warning_callouts(cap_state_warnings: list[str]) -> list[str]:
    """Founder-facing callout block for cap_state warnings. Thin wrapper over the shared
    `_warning_callouts.render_warning_callouts` (single source of truth shared with `concise_report`,
    so the full and concise routes cannot diverge). Wrapper name kept for existing call sites/tests."""
    return _warning_callouts.render_warning_callouts(cap_state_warnings)


def build_pool_basis_note(
    *,
    target_pool_percent: float | None,
    pool_consideration_basis: str,
    realized_pool_pct: float,
    acquisition_pct: float | None,
) -> str:
    """Labeled option-pool sizing-basis note. Returns '' unless there is BOTH an acquisition
    (acquisition_pct truthy) AND a pool (target_pool_percent truthy). The negotiated headline is a
    SIZING input, surfaced separately here; the ownership table keeps the true realized % (pool/post_fd)."""
    if not acquisition_pct or not target_pool_percent:
        return ""
    if pool_consideration_basis == "exclude":
        return (
            f"Option pool sizing basis: sized to {target_pool_percent:.1%} of pre-consideration "
            f"fully-diluted, which is {realized_pool_pct:.1%} of post-closing combined "
            f"fully-diluted after the acquisition's consideration shares."
        )
    # "include" (or default)
    return (
        f"Option pool: {realized_pool_pct:.1%} of post-closing combined fully-diluted "
        f"(sized including acquisition consideration)."
    )


def _stated_totals_provenance_ok(stated_totals: dict[str, Any]) -> tuple[bool, str | None]:
    """Whether a `stated_totals` block names a usable, independent source.

    Returns `(ok, reason)`. `reason` is populated (non-None) whenever `ok` is False, giving a
    short diagnostic: `"no source given"` for a missing/blank `source`, or a message naming the
    self-referential match for a `source` that names one of the skill's own artifacts (see
    `_SELF_REFERENTIAL_SOURCE_MARKERS`).

    This is a NECESSARY-but-not-SUFFICIENT check: a `source` that passes here (present, and
    doesn't name our own outputs) is not thereby proven truthful — it just isn't structurally
    circular. Closes the gap SKILL.md's "Non-circularity rule" documents as agent-instruction-only
    with no deterministic guard: nothing previously stopped `stated_totals.source` from being
    absent or from literally being `"computed"` / `"scenarios.json"`.
    """
    source = stated_totals.get("source")
    if not isinstance(source, str) or not source.strip():
        return False, "no source given"
    normalized = source.strip().lower()
    if any(marker in normalized for marker in _SELF_REFERENTIAL_SOURCE_MARKERS):
        return False, f"source names the skill's own output: {source!r}"
    return True, None


def build_reconciliation_lines(
    scenario: dict[str, Any], inputs: dict[str, Any], cap_state: dict[str, Any]
) -> list[str]:
    """Reconcile the skill's COMPUTED round terms (PPS, FD) against the SOURCE doc's stated terms, plus an
    informational pre-money input-consistency row. Returns [] when no source-stated term is present
    (opt-in — no empty section, no false rows). Currency is read from cap_state (no caller arg)."""
    st = inputs.get("stated_totals") or {}
    co = scenario.get("computed_outputs", {}) or {}
    params = scenario.get("parameters", {}) or {}
    currency = cap_state.get("currency", "USD")
    PPM = 1000  # 0.1%, same threshold as cap_state's W_FD_RECONCILE_DELTA
    rows, pps_diverged = [], False
    # Set when a would-be "match" row can't be trusted because stated_totals carries no usable
    # provenance — see _stated_totals_provenance_ok. `circular` (bit-for-bit identical value, bad
    # provenance — the copy-the-computed-value-back-in pattern) is the stronger finding;
    # `cannot_verify` (a near-but-not-exact match, bad provenance) is the softer degradation.
    # Tracked separately from pps_diverged/fd so a genuine divergence still renders as before.
    circular_fields: list[str] = []
    cannot_verify_fields: list[str] = []
    provenance_ok, provenance_reason = _stated_totals_provenance_ok(st) if st else (True, None)

    def _num(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def _flag_suffix(*, diverged: bool, exact: bool, label: str) -> str:
        if diverged:
            return " ⚠"
        if provenance_ok:
            return ""
        if exact:
            circular_fields.append(label)
            return " ⚠ CIRCULAR"
        cannot_verify_fields.append(label)
        return " ⚠ CANNOT VERIFY"

    # Price per share — a genuine computed-vs-stated reconciliation (flagged on divergence > 0.1%).
    # A row that would otherwise read as a clean match is NOT reported as one unless stated_totals
    # carries usable provenance (see _stated_totals_provenance_ok / SKILL.md "Non-circularity rule").
    stated_pps, computed_pps = st.get("price_per_share"), co.get("equity_financing_price")
    if _num(stated_pps) and _num(computed_pps) and stated_pps > 0:  # type: ignore[operator]
        d = (computed_pps - stated_pps) / stated_pps  # type: ignore[operator]
        pps_diverged = abs(d) * 1_000_000 > PPM
        flag = _flag_suffix(diverged=pps_diverged, exact=computed_pps == stated_pps, label="Price per share")
        rows.append(f"| Price per share | ${stated_pps:,.4f} | ${computed_pps:,.4f} | {d:+.1%}{flag} |")

    # Fully diluted — genuine computed-vs-stated (also surfaced as W_FD_RECONCILE_DELTA in warnings).
    stated_fd = st.get("fully_diluted")
    computed_fd = (cap_state.get("as_converted_totals") or {}).get("fully_diluted_shares")
    if _num(stated_fd) and _num(computed_fd) and stated_fd > 0:  # type: ignore[operator]
        d = (computed_fd - stated_fd) / stated_fd  # type: ignore[operator]
        fd_diverged = abs(d) * 1_000_000 > PPM
        flag = _flag_suffix(diverged=fd_diverged, exact=computed_fd == stated_fd, label="Fully diluted")
        rows.append(f"| Fully diluted | {int(stated_fd):,} | {int(computed_fd):,} | {d:+.1%}{flag} |")  # type: ignore[arg-type]

    # Pre-money — INFORMATIONAL only: the doc's stated pre-money vs the value USED as the round input (not a
    # computed quantity, so never ⚠-flagged — a no-op when equal, a useful "did I use your number?" check when
    # not). Read both priced-scenario param shapes (run_priced_round_scenario uses pre_money;
    # run_safe_conversion_scenario's priced delegate uses priced_round_pre_money).
    stated_pre = st.get("pre_money")
    used_pre = params.get("pre_money")
    if used_pre is None:
        used_pre = params.get("priced_round_pre_money")
    if _num(stated_pre) and _num(used_pre) and stated_pre > 0:  # type: ignore[operator]
        rows.append(
            f"| Pre-money (input check) | {_money(stated_pre, currency)} | {_money(used_pre, currency)} | informational |"  # type: ignore[arg-type]
        )

    if not rows:
        return []
    out: list[str] = [
        "",
        "**Reconciliation vs your source documents:**",
        "",
        "| Term | Stated (your doc) | Computed / used | Δ |",
        "|---|---:|---:|---:|",
        *rows,
    ]
    if circular_fields:
        out += [
            "",
            f"> ⚠ **Circular reconciliation detected ({', '.join(circular_fields)}).** The stated figure above "
            f"is bit-for-bit identical to the skill's own computed value, but its `source` "
            f"({provenance_reason or 'no source given'}) doesn't name an independent document. A cross-foot "
            "only means something when the two figures come from INDEPENDENT sources — treat this row as "
            "**unverified**, not as a confirmed match, until `stated_totals` cites a figure the source "
            "document itself prints.",
        ]
    elif cannot_verify_fields:
        out += [
            "",
            f"> ⚠ **Cannot verify ({', '.join(cannot_verify_fields)}) — provenance missing.** "
            f"`stated_totals` has no usable `source` ({provenance_reason or 'no source given'}), so this "
            "reconciliation cannot confirm the figure came from an independent document. Degraded to "
            "unverified rather than reported as a match; add a `source` naming the document/section it was "
            "read from.",
        ]
    elif pps_diverged:
        out += [
            "",
            "> The computed price uses a different basis than your stated figure — commonly a coupled "
            "SAFE-conversion / anti-dilution solve rather than a straight pre-money ÷ fully-diluted, but it "
            "can also be a different pre-money or fully-diluted denominator. Confirm which basis your round uses.",
        ]
    return out


def compute_reconciliation_status(*, computed: dict[str, Any], stated: dict[str, Any] | None) -> tuple[str, float]:
    """Compare computed PPS/FD against source-stated values. Returns (status, max_ppm).

    not_applicable when the source states nothing comparable (stated is falsy or no
    paired numeric value found). Threshold: RECONCILIATION_TOLERANCE_PPM (1000 ppm = 0.1%).

    Mirrors the numeric logic inside build_reconciliation_lines — does NOT consume
    the rendered markdown rows (which are str and would raise AttributeError on .get()).
    """
    if not stated:
        return "not_applicable", 0.0
    max_ppm = 0.0
    compared = False
    for key in ("pps", "fd"):
        c_raw, s_raw = computed.get(key), stated.get(key)
        if c_raw is None or s_raw is None or s_raw == 0:
            continue
        c_f, s_f = float(c_raw), float(s_raw)  # type: ignore[arg-type]
        compared = True
        max_ppm = max(max_ppm, abs(c_f - s_f) / abs(s_f) * 1_000_000.0)
    if not compared:
        return "not_applicable", 0.0
    return ("pass" if max_ppm <= RECONCILIATION_TOLERANCE_PPM else "diverged"), max_ppm


def refine_reconciliation_status_for_provenance(
    *, status: str, max_ppm: float, stated_totals: dict[str, Any] | None
) -> str:
    """Downgrade a `compute_reconciliation_status` verdict when `stated_totals` provenance can't
    back it up. See SKILL.md "Non-circularity rule" — the whole value of the reconciliation
    cross-foot is that computed and stated figures come from INDEPENDENT sources; nothing
    previously enforced that, so a copied-back computed value would trivially "pass".

    Only a `"pass"` verdict (computed and stated agree within tolerance) can be downgraded here:

    - Provenance missing or self-referential (see `_stated_totals_provenance_ok`) AND the stated
      value is bit-for-bit identical to the computed one (`max_ppm == 0.0`) → `"circular"` — the
      classic copy-the-computed-value-back-in pattern this closes.
    - Provenance missing or self-referential but the match is close-not-exact (small nonzero
      `max_ppm`, e.g. independent rounding) → `"cannot_verify"` — can't confirm an independent
      source, but it isn't proven circular either.
    - Provenance present and not self-referential → unchanged (`"pass"`); a legitimate exact match
      IS possible and common (the skill's math SHOULD agree with the document) — exact-match alone
      must never be the trigger.

    `"diverged"` and `"not_applicable"` pass through unchanged: a genuine numeric divergence is a
    real finding regardless of provenance, and `"not_applicable"` already means there was nothing
    to compare.
    """
    if status != "pass" or not stated_totals:
        return status
    provenance_ok, _reason = _stated_totals_provenance_ok(stated_totals)
    if provenance_ok:
        return status
    return "circular" if max_ppm == 0.0 else "cannot_verify"


def build_reconciliation_provenance_warnings(
    *, status: str, stated_totals: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Structured `{code, severity, message}` entries for a provenance-refined reconciliation
    status — same shape as `validate_run_id_parity`'s warnings, so both feed the SAME
    '## Validation Warnings' report.md section, the SAME `report.json` `validation.warnings` list,
    and (for the circular code) the SAME `--strict` high-severity gate in `main()`.

    Returns [] for any status other than "circular" / "cannot_verify" (including "pass" — a
    legitimate, provenance-backed match raises no warning at all).
    """
    if status not in {"circular", "cannot_verify"} or not stated_totals:
        return []
    _ok, reason = _stated_totals_provenance_ok(stated_totals)
    if status == "circular":
        return [
            {
                "code": "E_CIRCULAR_RECONCILIATION",
                "severity": "critical",
                "message": (
                    "stated_totals matches the skill's own computed figure bit-for-bit, but its `source` "
                    f"is unusable ({reason}) — this is the copy-the-computed-value-back-in pattern the "
                    "reconciliation cross-foot exists to catch. Treat as UNVERIFIED, not a confirmed match; "
                    "re-derive stated_totals from a figure the source document itself prints."
                ),
            }
        ]
    return [
        {
            "code": "W_STATED_TOTALS_PROVENANCE_MISSING",
            "severity": "medium",
            "message": (
                f"stated_totals has no usable source ({reason}) — the reconciliation cannot confirm the "
                "figure came from an independent document. Degraded to 'cannot verify' rather than "
                "reported as a match."
            ),
        }
    ]


def render_report_markdown(
    *,
    artifacts: dict[str, dict[str, Any]],
    validation_warnings: list[dict[str, Any]],
    insertion_marker: str,
    extraction_audit_path: str | None = None,
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
    repay = sum(1 for c in completes if c == "repay_only")
    mixed = sum(1 for c in completes if c == "mixed")
    # `structural_only` has EIGHT origins, and only one is working-as-intended: the cap-implied SAFE
    # snapshot (stamped `cap_implied_only` by run_scenario.py). The other seven are genuinely blocked
    # runs (missing note date, warrant-pump error, unknown type, priced-round solve with blockers).
    # Counting them together and calling the total "pending input" labels a by-design result as an
    # unfinished one -- a founder scanning the summary reads it as a defect. Split them on the same
    # signal visualize.py already classifies with, and describe each in founder-facing words.
    by_design = sum(
        1
        for s in scenarios
        if (s["computed_outputs"].get("completeness") == "structural_only")
        and s["computed_outputs"].get("cap_implied_only")
        and s["computed_outputs"].get("per_safe")
    )
    blocked = sum(1 for c in completes if c == "structural_only") - by_design
    parts = [f"{full} full", f"{mixed} mixed", f"{repay} repay-only"]
    if by_design:
        parts.append(f"{by_design} priced-round terms not set yet")
    if blocked:
        parts.append(f"{blocked} needs more from you")
    lines.append(f"Modeled {n} scenario(s) for {inputs.get('company_name', 'this company')}: " + ", ".join(parts) + ".")
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

    # cap_state.py warnings array → founder-facing callouts, rendered above Current Cap State so the
    # founder sees engagement scope / data caveats first.
    lines.extend(_render_warning_callouts(cap_state.get("warnings") or []))

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
            rows.append((_batch_label(b), cls, shares, vrm, shares * vrm))
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
            blabel = _batch_label(b)
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
        # Assumed-basis disclosure: when target_basis was defaulted rather than supplied, it is
        # absent from `params` above, so the Inputs list never mentions it. Render the assumption
        # explicitly so a defaulted pool denominator never reads as a founder-confirmed input.
        if any((w or {}).get("code") == "target_basis_defaulted" for w in (co.get("warnings") or [])):
            lines.append(
                "> ⚠ **Option pool basis ASSUMED, not stated.** No pool-sizing basis was confirmed "
                "for this scenario — pre-money was assumed. Pre-money vs post-money changes the "
                "pool top-up and post-round ownership; confirm which basis your term sheet uses "
                "before relying on these figures."
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
            _structured_fields = {"founders_by_class", "founders_by_holder"}
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
            # Per-founder post-round ownership. Answers "what does this round do to ME", which the
            # aggregate alone cannot -- and which must never be back-computed by splitting the
            # aggregate in chat. Rendered only for more than one founder: a solo founder's number is
            # the aggregate already printed above.
            fbh = agg.get("founders_by_holder") or {}
            if len(fbh) > 1:
                lines.append("- each founder, post-round:")
                for _fid, row in sorted(fbh.items(), key=lambda kv: -(kv[1].get("pct") or 0.0)):
                    nm = row.get("name") or _fid
                    shares = row.get("common_shares")
                    lines.append(f"  - {nm}: {_percent(row.get('pct'))} ({shares:,} shares)")
                # Scope disclosure: cap_state keeps `founders[]` and `common_batches[]` separate, so a
                # shareholder whose stock sits in a batch (Carta rebuild, RSP, exercised employee) is
                # absent here. Without this line they read their absence as "I hold nothing".
                lines.append(
                    "  - *(Founders only. Shares held through employee/other common batches are counted "
                    "in the totals above but are not broken out per person here.)*"
                )
            lines.append("")
            # Option-pool sizing-basis note (acquisition deals only; ownership table unchanged)
            _pool_note = build_pool_basis_note(
                target_pool_percent=params.get("target_pool_percent"),
                pool_consideration_basis=params.get("pool_consideration_basis", "include"),
                realized_pool_pct=agg.get("option_pool_pct") or 0.0,
                acquisition_pct=agg.get("acquisition_pct"),
            )
            if _pool_note:
                lines.append(f"> _{_pool_note}_")
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
                lines.extend(build_reconciliation_lines(s, inputs, cap_state))
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

    # 4b. Additional document terms (optional — extraction_audit.json from a term sheet, option
    # plan, or amendment uploaded alongside this engagement's cap base). Absent for the common
    # case (a pure SAFE/note engagement with no terms-doc/amendment); a no-op then. This is the
    # SAME content the no-cap-base fork's compose_extraction_report.py --audit renders — reused
    # here so it isn't silently dropped just because a real cap base also happened to exist.
    if extraction_audit_path:
        _ambiguity_map = _load_ambiguity_map(extraction_audit_path)
        _terms_doc = _load_terms_doc(extraction_audit_path)
        _amendment_deltas = _load_amendment_deltas(extraction_audit_path)
        if _terms_doc:
            lines.extend(_terms_section(_terms_doc, _ambiguity_map))
        if _amendment_deltas:
            lines.append("## Amendments (terms modified)")
            lines.append("")
            lines.append(
                "_This document amends a pre-existing instrument rather than defining a standalone "
                "one; the clause changes below are surfaced as extracted and are NOT modeled against "
                "the base instrument. Confirm against the original instrument._"
            )
            lines.append("")
            for _delta in _amendment_deltas:
                _field = _delta.get("field") or "clause"
                _description = _delta.get("description") or ""
                lines.append(f"- **{_field}** — {_description}")
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
            # Default FALSE for an absent key: "the producer did not say" must not
            # mean "assume it applies" for a filter whose whole job is suppressing
            # inapplicable rules. An older artifact without the field renders its
            # watchlist as for-reference, which is the safe direction.
            if w.get("applies_when_matched") is True:
                active_items.append(w)
            else:
                annotation_items.append(w)

        if active_items:
            grouped = _rules.group_watchlist(active_items)
            lines.append("## Date-Sensitive Watchlist")
            lines.append("")
            lines.append(f"_{len(grouped)} rule(s) to watch (from {len(active_items)} matched instances)._")
            lines.append("")
            lines.append("| Rule | Status | When | Action |")
            lines.append("|---|---|---|---|")
            for g in grouped:
                status = _labels.humanize("status", g["status"]) + (f" · {g['count']}×" if g["count"] > 1 else "")
                action = (g.get("action") or "").replace("|", "\\|")[:80]
                lines.append(
                    f"| {_rule_md(g['rule_id'], item_title=g['title'], compact=True)} | {status} | "
                    f"{_rules.format_dates(g['dates'])} | {action} |"
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

    # Optional: extraction_audit.json — a term sheet / option plan / amendment extracted
    # alongside this engagement's cap base (Step 3's Lane-1 invocation always writes it via -o;
    # absent for the common pure-SAFE/note case, where it's simply not there).
    _extraction_audit_candidate = os.path.join(args.dir, "extraction_audit.json")
    _extraction_audit_path: str | None = (
        _extraction_audit_candidate if os.path.exists(_extraction_audit_candidate) else None
    )

    # Build reconciliation_status — compare computed PPS/FD against source-stated values.
    # PPS: from the first priced-round scenario that produced equity_financing_price.
    # FD:  PRE-round cap_state.as_converted_totals.fully_diluted_shares (mirrors compose_report.py
    #      build_reconciliation_lines:587 which compares source-stated FD against pre-round FD, NOT
    #      post_round_fully_diluted_shares — using post-round would spuriously flip status to "diverged").
    # Computed BEFORE render_report_markdown / build_coaching_payload (below) so (a) a provenance
    # finding can be folded into validation_warnings and land in the rendered '## Validation
    # Warnings' section, and (b) a computed price-per-share disagreeing with the founder's own term
    # sheet is exactly the kind of thing the Context-B coaching commentary should be able to cite.
    _inputs_data = artifacts["inputs.json"]
    _cap_state_data = artifacts["cap_state.json"]
    _scenarios_data = artifacts["scenarios.json"]
    _stated_raw = _inputs_data.get("stated_totals") or None
    _stated: dict[str, Any] | None = (
        {"pps": _stated_raw.get("price_per_share"), "fd": _stated_raw.get("fully_diluted")} if _stated_raw else None
    )
    _round_outputs: dict[str, Any] = {}
    for _s in _scenarios_data.get("scenarios") or []:
        _co = (_s.get("computed_outputs") or {}) if isinstance(_s, dict) else {}
        if _co.get("equity_financing_price"):
            _round_outputs = _co
            break
    _computed: dict[str, Any] = {
        "pps": _round_outputs.get("equity_financing_price"),
        "fd": _cap_state_data["as_converted_totals"]["fully_diluted_shares"],  # PRE-round
    }
    _recon_status, _max_ppm = compute_reconciliation_status(computed=_computed, stated=_stated)
    # Non-circularity guard (finding 14): a "pass" verdict backed by missing/self-referential
    # provenance is refused — downgraded to "circular" (exact-match copy-back) or "cannot_verify"
    # (near-match, no usable source) — see refine_reconciliation_status_for_provenance.
    _recon_status = refine_reconciliation_status_for_provenance(
        status=_recon_status, max_ppm=_max_ppm, stated_totals=_stated_raw
    )
    validation_warnings = validation_warnings + build_reconciliation_provenance_warnings(
        status=_recon_status, stated_totals=_stated_raw
    )

    # Build report.md
    report_md = render_report_markdown(
        artifacts=artifacts,
        validation_warnings=validation_warnings,
        insertion_marker=insertion_marker,
        extraction_audit_path=_extraction_audit_path,
    )

    # --- founder-text policy (shared fleet module) ------------------------------------------------
    # cap-table is the one skill that does NOT hand its vocabulary to the shared module. `_labels.py`
    # is the authority here and its convention is deliberate: lead with plain language, keep the raw
    # code as a small-print parenthetical, because counsel and power users need the exact term. So its
    # own enum keys are passed as `extra_keep` and survive untouched; what the policy still catches is
    # everything `_labels.py` never mapped (field names like `safe_price`).
    #
    # Rule ids need no keep-list — they are dot-namespaced (`safe.post_money_cap_conversion`) and the
    # detector excludes namespaced identifiers by construction. Scenario and instrument ids DO need
    # one: `safe_conv` looks like vocabulary and is not, and rewriting it would make the markdown
    # disagree with the JSON, the explorer and the counsel packet about what a scenario is called.
    _ft = _founder_text_policy()
    if _ft is not None:
        _keep = frozenset(k for _m in _labels.MAPS.values() for k in _m) | _ft.identifier_values(
            artifacts, include_map_keys=True
        )
        report_md = _ft.substitute(report_md, extra_keep=_keep)
        _found = _ft.scan(report_md, extra_keep=_keep)
        for _tok in _found["enums"]:
            validation_warnings.append(
                {
                    "code": "FOUNDER_TEXT_TOKEN",
                    "severity": "low",
                    "message": (
                        f"the report contains the internal token '{_tok}' — a founder cannot act on "
                        f"it; map it in _labels.py or stop emitting it"
                    ),
                }
            )
        for _fn in _found["filenames"]:
            validation_warnings.append(
                {
                    "code": "FOUNDER_TEXT_TOKEN",
                    "severity": "low",
                    "message": (
                        f"the report names the internal file '{_fn}' — drop the reference rather than renaming it"
                    ),
                }
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
        reconciliation_status=_recon_status,
        reconciliation_max_divergence_ppm=_max_ppm,
    )

    # Build disclosure banner; prepend to report.md when non-empty
    _banner = build_disclosure_banner(
        covered=True,
        reconciliation_status=_recon_status,
        max_divergence_ppm=_max_ppm,
    )
    if _banner:
        report_md = _banner + "\n\n" + report_md
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_md)

    # Write coverage_disclosure.json (deterministic pipeline = covered path)
    _coverage_disclosure: dict[str, Any] = {
        "schema_version": "v0.1-coverage-disclosure",
        "covered": True,
        "computation_method": "deterministic_pipeline",
        "reconciliation": {
            "status": _recon_status,
            "max_divergence_ppm": _max_ppm,
        },
    }
    _disclosure_schema = _artifact_writer.load_schema(os.path.join(_SCHEMA_DIR, "coverage-disclosure.schema.json"))
    _disclosure_path = os.path.join(os.path.abspath(args.dir), "coverage_disclosure.json")
    _artifact_writer.write_artifact(
        data=_coverage_disclosure,
        schema=_disclosure_schema,
        run_id=args.run_id,
        output_path=_disclosure_path,
        pretty=args.pretty,
    )

    # Assemble report.json (pre-coaching markdown + coaching_payload)
    report_json: dict[str, Any] = {
        "report_markdown": report_md,
        "validation": {"warnings": validation_warnings},
        "coaching_payload": coaching_payload,
        "metadata": {"run_id": args.run_id, "produced_by": "compose_report.py"},
        "reconciliation_status": _recon_status,
        "max_divergence_ppm": _max_ppm,
        "disclosure_banner": _banner,
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
        "coverage_disclosure": _disclosure_path,
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

    # --strict exits 1 on any high-severity warning (MISSING_METADATA + STALE_ARTIFACT, plus the
    # circular-reconciliation false-green guard — see build_reconciliation_provenance_warnings).
    high_severity_codes = {"MISSING_METADATA", "STALE_ARTIFACT", "E_CIRCULAR_RECONCILIATION"}
    if args.strict and any(w.get("code") in high_severity_codes for w in validation_warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
