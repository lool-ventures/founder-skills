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
    "data",
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


def _keep() -> frozenset[str]:
    """The shared keep set, resolved defensively.

    `_policy()` below catches its own import precisely so "a rule summary is worth rendering
    unpolished rather than not at all". An unguarded import here defeated that: with the helper
    missing, `visualize` and `explore` both died and neither report.html nor explorer.html was
    written at all. Degrade to the empty set, never to no deliverable.
    """
    try:
        import os
        import sys

        d = os.path.dirname(os.path.abspath(__file__))
        if d not in sys.path:
            sys.path.insert(0, d)
        from _founder_text_keep import cap_table_keep

        return frozenset(cap_table_keep())
    except Exception:
        return frozenset()


def founder_text(s: str) -> str:
    """Unsnake internal vocabulary in a string bound for a founder-visible surface.

    The single entry point for the HTML generators, which apply the shared policy nowhere else --
    `compose_report` substitutes its markdown, and `visualize` / `explore` did neither, so a rule's
    counsel question reached `report.html` as raw text in a `<div class="ci-q">`. Not a tooltip: a
    visible block, carrying names like `current_conversion_price` on seven counsel-review rules.

    Deliberately NOT applied to a whole HTML document. Substitution over markup would rewrite class
    names, JS identifiers and URLs; it is applied per founder-visible STRING at the render boundary.
    """
    pol = _policy()
    if pol is None or not s:
        return s
    return str(pol.substitute(s, extra_keep=_keep()))


def rule_title(rule_id: str) -> str:
    """A rule's title, policied for the same reason as `rule_summary`.

    `c3e9483` policied the summary and left this sibling, so two titles kept leaking through the
    same text nodes (anchor text in `visualize.rule_ref`, and `<div class="ci-title">`).
    """
    return founder_text((_rules_by_id().get(rule_id) or {}).get("title") or rule_id)


@functools.lru_cache(maxsize=1)
def _policy() -> Any:
    """The shared founder-text policy, or None when it cannot be imported.

    Best-effort by design: these scripts are standalone, and a rule summary is worth rendering
    unpolished rather than not at all.
    """
    import sys

    try:
        sys.path.insert(
            0,
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts"
            ),
        )
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except Exception:
        return None


def rule_summary(rule_id: str) -> str:
    """A rule's summary, with internal vocabulary unsnaked.

    Applied HERE rather than at each call site because this one function feeds every founder-visible
    surface that shows a rule: `visualize.rule_ref`'s `title=` tooltip in report.html and
    `explore.py`'s JS payload in explorer.html. Neither applies the policy itself -- only
    `compose_report` did, and only to report.md -- so every rule summary in the pack was reaching
    both HTML surfaces raw, in a form no fleet test could see (the HTML scan reads text nodes, not
    attribute values or script bodies).

    Unsnaking only. Our knob names and plumbing are fixed in the pack itself, because `substitute`
    is detect-only for ALLCAPS and never rewrites filenames.
    """
    raw = (_rules_by_id().get(rule_id) or {}).get("summary") or ""
    pol = _policy()
    # FIFTH call site. It was left on a bare substitute when the other four were unified, which
    # recreated inside this one file the exact "invisible by inspection" asymmetry being removed.
    return str(pol.substitute(raw, extra_keep=_keep())) if pol is not None and raw else raw


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
