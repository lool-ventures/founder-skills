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
