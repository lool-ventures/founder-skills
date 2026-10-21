#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Which figures, and which pages, Step 3.95's machine read checks. One helper, so the OCR producer, the
check and Step 4's gate cannot disagree about it.

A figure is in scope when it is an operand or the expected figure of a relation `reconciliation.json` kept
(the only figures the founder-facing numbers section uses), it is not a date, and it sits on a slide whose
deck text came from the inventory (`pages_source` is `inventory`): a page the ledger read from how the slide
looks rather than from its own text. Relation ids are merge heads, which are original ledger rows, so the
rows are read by id from `ledger.json` with no reconcile import.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DATE = "date"  # reconcile's DATE unit kind; held equal by a test
MAX_PAGES = 40


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def relation_ids(reconciliation: Mapping[str, Any] | None) -> list[str]:
    """The unique figure ids the kept relations use, in first-seen order: every operand, then the expected id."""
    seen: dict[str, None] = {}
    for relation in _as_list(_as_dict(reconciliation).get("relations")):
        relation = _as_dict(relation)
        for operand in _as_list(relation.get("operands")):
            if isinstance(operand, str) and operand:
                seen.setdefault(operand, None)
        expected = relation.get("expected_id")
        if isinstance(expected, str) and expected:
            seen.setdefault(expected, None)
    return list(seen)


def in_scope(
    ledger: Mapping[str, Any] | None,
    reconciliation: Mapping[str, Any] | None,
    pages_source: Mapping[int, str] | None,
) -> list[dict[str, Any]]:
    """The in-scope ledger rows (id, slide, raw, unit_kind), in the relations' order."""
    rows = {
        str(f.get("id")): f
        for f in (_as_dict(x) for x in _as_list(_as_dict(ledger).get("figures")))
        if isinstance(f.get("id"), str)
    }
    sources = dict(pages_source or {})
    out: list[dict[str, Any]] = []
    for fid in relation_ids(reconciliation):
        row = rows.get(fid)
        if row is None or row.get("unit_kind") == DATE:
            continue
        slide = row.get("slide")
        if isinstance(slide, bool) or not isinstance(slide, int):
            continue
        if sources.get(slide) != "inventory":
            continue
        out.append({"id": fid, "slide": slide, "raw": str(row.get("raw") or ""), "unit_kind": row.get("unit_kind")})
    return out


def pages(figures: list[dict[str, Any]], max_pages: int = MAX_PAGES) -> tuple[list[int], list[int]]:
    """(the pages to read, ascending and capped; the in-scope pages past the cap)."""
    wanted = sorted({int(f["slide"]) for f in figures})
    return wanted[:max_pages], wanted[max_pages:]
