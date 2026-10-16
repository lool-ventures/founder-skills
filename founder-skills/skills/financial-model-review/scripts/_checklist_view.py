"""The review checklist as both FMR pages show it: grouped by category, every criterion listed.

One owner for report.html and explore.html, so the two pages cannot disagree about which criteria
exist, what each one is called, which tone it gets, or what evidence sits under it. The assessor's
evidence goes through the fleet's founder-text policy (`_founder_text.substitute`, when reachable) and
then `_evidence_multiple.caveat`, the same caveat report.md carries. The label fallback for an item with
no `label` lives here too, so both pages fall back to the same name.

Shapes are the ones `_ui.checklist` and `_ui.score_ring` take; this module decides only what the FMR
pages already decided (the 80 / 60 score bands, the "pass/applicable (pct)" group count).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _evidence_multiple  # noqa: E402
import _ui  # noqa: E402

# The criterion names for an artifact item that carries no `label` of its own. Hand-kept and not
# held in step with `checklist.py`, so an item's own label always wins.
FALLBACK_LABELS: dict[str, str] = {
    "STRUCT_01": "Assumptions on dedicated tab",
    "STRUCT_02": "Tab structure is navigable",
    "STRUCT_03": "Actuals vs. projections separated",
    "STRUCT_04": "Scenario toggles (base/up/down)",
    "STRUCT_05": "Model matches pitch deck",
    "STRUCT_06": "Version/date included",
    "STRUCT_07": "Monthly granularity appropriate",
    "STRUCT_08": "No structural errors",
    "STRUCT_09": "Professional formatting",
    "UNIT_10": "Revenue is bottom-up",
    "UNIT_11": "Churn modeled explicitly",
    "UNIT_12": "Pricing logic explicit",
    "UNIT_13": "Expansion revenue modeled",
    "UNIT_14": "COGS/margin matches model type",
    "UNIT_15": "CAC fully loaded",
    "UNIT_16": "CAC payback computed",
    "UNIT_17": "LTV/CAC shown",
    "UNIT_18": "Sales capacity constrains revenue",
    "UNIT_19": "Conversion rates grounded",
    "CASH_20": "Headcount plan drives expenses",
    "CASH_21": "Benefits/tax burden included",
    "CASH_22": "Working capital modeled",
    "CASH_23": "Cash runway computed correctly",
    "CASH_24": "Runway length adequate",
    "CASH_25": "Cash-out date explicit",
    "CASH_26": "Step costs captured",
    "CASH_27": "OpEx scales with revenue",
    "CASH_28": "FX sensitivity modeled",
    "CASH_29": "Entity-level cash solvent",
    "CASH_30": "Israel statutory costs itemized",
    "CASH_31": "Government grants modeled",
    "CASH_32": "VAT/indirect tax cash timing",
    "METRIC_33": "KPI summary visible",
    "METRIC_34": "Burn multiple tracked",
    "METRIC_35": "Benchmark awareness",
    "BRIDGE_36": "Raise-runway-milestones linked",
    "BRIDGE_37": "Next-round milestones identified",
    "BRIDGE_38": "Dilution/ownership shown",
    "SECTOR_39": "Marketplace: two-sided mechanics",
    "SECTOR_40": "AI: inference costs modeled",
    "SECTOR_41": "Hardware: milestones + capex",
    "SECTOR_42": "Usage-based: margin at scale",
    "SECTOR_43": "Consumer: retention curves",
    "SECTOR_44": "Deferred revenue handled",
    "OVERALL_45": "5-minute audit possible",
    "OVERALL_46": "Country-level metrics tracked",
}


def founder_text(text: str) -> str:
    """`text` with internal tokens rewritten by the founder-text policy, when the policy is reachable.

    The CHECKLIST sub-agent writes each item's evidence and notes, and report.md never carries them, so
    the two pages are the only place they reach a founder: this is that text's one policy pass. The
    policy is loaded by path (`_ui.founder_text`), never through `sys.path`; a surface that mounts the
    skill without the plugin root (the claude.ai flat mount) gets the assessor's text as written.
    """
    return _ui.founder_text(text)


# checklist.json's statuses onto the page's four tones. Anything else reads as not applicable,
# which is how both pages drew an unknown status before (a grey dash).
_TONE = {"pass": "pass", "fail": "fail", "warn": "warn", "not_applicable": "na"}


def tone(status: Any) -> str:
    return _TONE.get(str(status), "na")


def score_tone(score_pct: float) -> str:
    """The score's band, the thresholds both pages have always used."""
    if score_pct >= 80:
        return "pass"
    if score_pct >= 60:
        return "warn"
    return "fail"


def groups(items: list[Any], fallback_labels: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Items grouped by category in first-seen order, ready for `_ui.checklist`."""
    order: list[str] = []
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category", "Other"))
        if cat not in by_cat:
            order.append(cat)
            by_cat[cat] = []
        by_cat[cat].append(item)

    out: list[dict[str, Any]] = []
    for cat in order:
        rows: list[dict[str, Any]] = []
        passed = applicable = 0
        for item in by_cat[cat]:
            item_id = str(item.get("id") or "").strip()
            t = tone(item.get("status"))
            if t != "na":
                applicable += 1
            if t == "pass":
                passed += 1
            # Never fall back to the id: it would put `CASH_23` in front of a founder. The item's own
            # label first; the hand-kept map only for an artifact that carries none.
            title = (
                str(item.get("label") or item.get("criterion") or "").strip()
                or (FALLBACK_LABELS if fallback_labels is None else fallback_labels).get(item_id)
                or "Checklist item"
            )
            raw = founder_text(str(item.get("evidence") or item.get("notes") or "").strip())
            evidence = _evidence_multiple.caveat(raw)
            rows.append({"tone": t, "title": title, "criterion": item_id, "evidence": evidence})
        pct = f"{passed / applicable * 100:.0f}%" if applicable > 0 else "N/A"
        out.append({"name": cat, "count_text": f"{passed}/{applicable} ({pct})", "items": rows})
    return out
