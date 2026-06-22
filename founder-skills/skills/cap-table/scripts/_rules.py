"""Rule metadata + source links for founder-facing output.

Resolves a ``rule_id`` to its plain-English title, summary, and primary-source
URL(s) from the cap-table rule pack and its bibliography, so the report and
explorer can show a readable, linked rule reference ("Post-money SAFE cap
conversion ↗") instead of a bare code. Shared by visualize.py / explore.py /
compose_report.py.
"""

from __future__ import annotations

import functools
import json
import os
from typing import Any

_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "cap-table-rules.json",
)


@functools.lru_cache(maxsize=1)
def _pack() -> dict[str, Any]:
    with open(_RULES_PATH, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


@functools.lru_cache(maxsize=1)
def _rules_by_id() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for domain in _pack().get("domains", {}).values():
        for r in domain:
            rid = r.get("rule_id")
            if rid:
                out[rid] = r
    return out


@functools.lru_cache(maxsize=1)
def _sources() -> dict[str, dict[str, Any]]:
    return {s["source_id"]: s for s in _pack().get("source_bibliography", []) if s.get("source_id")}


def rule_title(rule_id: str) -> str:
    return (_rules_by_id().get(rule_id) or {}).get("title") or rule_id


def rule_summary(rule_id: str) -> str:
    return (_rules_by_id().get(rule_id) or {}).get("summary") or ""


def _rule_source_ids(rule_id: str) -> list[str]:
    return (_rules_by_id().get(rule_id) or {}).get("source_ids") or []


def source_links(source_ids: list[str] | None) -> list[list[str]]:
    """``[[publisher, url], ...]`` for source_ids with a URL, deduped by
    publisher (a rule citing two docs from the same publisher → one link)."""
    out: list[list[str]] = []
    seen: set[str] = set()
    for sid in source_ids or []:
        s = _sources().get(sid) or {}
        pub, url = s.get("publisher") or sid, s.get("url")
        if url and pub not in seen:
            seen.add(pub)
            out.append([pub, url])
    return out


# Watchlist status urgency — lower sorts first (most actionable).
_STATUS_RANK = {
    "in_window": 0,  # Active now
    "missing_event_date": 1,  # Needs a date from you
    "pre_effective": 2,  # Not yet in effect
    "date_tracking_only": 3,
    "expired": 4,
    "not_date_sensitive": 5,
}


def _wl_status(w: dict[str, Any]) -> str | None:
    return w.get("current_status") or w.get("freshness_status")


def group_watchlist(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse per-instance watchlist rows into one row per rule.

    Each group reports the most-urgent status across its instances, the unique
    event dates, the instance count, and the action. Sorted by urgency.
    """
    groups: dict[str, dict[str, Any]] = {}
    for w in items:
        rid = w.get("rule_id", "")
        groups.setdefault(rid, {"rule_id": rid, "title": w.get("title"), "items": []})["items"].append(w)

    out: list[dict[str, Any]] = []
    for rid, g in groups.items():
        rows = g["items"]
        urgent = min(rows, key=lambda w: _STATUS_RANK.get(_wl_status(w) or "", 6))
        dates = sorted({w.get("event_date_value") for w in rows if w.get("event_date_value")})
        # Action from the same instance whose status we surface, so they agree.
        action = urgent.get("action_required") or next(
            (w.get("action_required") for w in rows if w.get("action_required")), ""
        )
        out.append(
            {
                "rule_id": rid,
                "title": g["title"] or rule_title(rid),
                "count": len(rows),
                "status": _wl_status(urgent),
                "dates": dates,
                "action": action,
            }
        )
    out.sort(key=lambda r: (_STATUS_RANK.get(r["status"] or "", 6), str(r["title"])))
    return out


def format_dates(dates: list[str]) -> str:
    """Compact 'When' rendering: one date, a short list, or earliest…latest."""
    if not dates:
        return "—"
    if len(dates) == 1:
        return dates[0]
    if len(dates) <= 3:
        return ", ".join(dates)
    return f"{dates[0]} … {dates[-1]} ({len(dates)})"


def rule_ref(
    rule_id: str,
    *,
    item_title: str | None = None,
    item_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolved display reference: title, summary, rule_id, and source links.

    Prefers the item's own title / source_ids (counsel items carry both); falls
    back to the rule pack (watchlist items carry only the rule_id).
    """
    sids = item_source_ids if item_source_ids else _rule_source_ids(rule_id)
    return {
        "title": item_title or rule_title(rule_id),
        "summary": rule_summary(rule_id),
        "rule_id": rule_id,
        "links": source_links(sids),
    }
