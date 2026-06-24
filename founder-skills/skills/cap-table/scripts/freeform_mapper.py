#!/usr/bin/env python3
"""Lane-3 freeform deterministic mapper (the "Phase 1 follow-up" the freeform stub named).

Pure function: maps a SPREADSHEET_STRUCTURE_DETECTION block set + a `--mode=grid` cell
grid into schema-valid inputs/instruments *proposals* plus an explicit blocker list. No
LLM, no network — a fixed (blocks, grid) maps deterministically. The agent<->producer
contract is the single source of truth in references/schemas/freeform-role-map.json:
the agent emits only roles listed there; this maps role -> schema field. Off-contract
roles and required-but-unsupplied fields become BLOCKERS (never silent skips / fabrication).
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

# Reuse the deterministic helpers (no behavior change; _to_iso_date is module-scope now).
from extract_cap_table import (  # type: ignore[import-not-found]
    _infer_safe_form,
    _normalize_discount,
    _to_iso_date,
)
from openpyxl.utils import column_index_from_string, range_boundaries  # type: ignore[import-untyped]

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROLE_MAP_PATH = os.path.join(_HERE, "..", "references", "schemas", "freeform-role-map.json")
_DATE_SENTINEL = "1900-01-01"
_INPUTS_SCHEMA_VERSION = "v0.5.0-inputs"
_INSTRUMENTS_SCHEMA_VERSION = "v0.5.0-instruments"


def _load_role_map(path: str | None = None) -> dict[str, Any]:
    with open(path or _ROLE_MAP_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _f(v: Any) -> float | None:
    return None if _is_blank(v) else float(v)


def _i(v: Any) -> int | None:
    return None if _is_blank(v) else int(round(float(v)))


def _block_rows(block: dict[str, Any], grid: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield one {role: value} dict per non-blank row in the block's cell_range.

    column_role_map is keyed by COLUMN LETTER; rows from --mode=grid are sheet-origin
    positional tuples (column A == index 0), so a letter maps via column_index_from_string-1.
    """
    sheet = block.get("sheet")
    cr = str(block.get("cell_range", ""))
    if "!" in cr:  # strip a "Sheet!A1:B2" qualifier
        cr = cr.split("!", 1)[1]
    _mc, min_row, _xc, max_row = range_boundaries(cr)
    rows = grid.get("sheets", {}).get(sheet, {}).get("rows", [])
    role_map = block.get("column_role_map", {})
    out: list[dict[str, Any]] = []
    for r in range(int(min_row or 1), int(max_row or 1) + 1):
        row = rows[r - 1] if 0 <= r - 1 < len(rows) else []
        raw: dict[str, Any] = {}
        for letter, role in role_map.items():
            ci = column_index_from_string(str(letter)) - 1
            raw[role] = row[ci] if 0 <= ci < len(row) else None
        if all(_is_blank(v) for v in raw.values()):
            continue  # blank / merged-spacer row
        out.append(raw)
    return out


def map_freeform(
    blocks: list[dict[str, Any]],
    grid: dict[str, Any],
    existing_inputs: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    run_id: str = "",
    role_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map detected blocks -> {inputs, instruments, blockers, warnings}. Deterministic."""
    rm = role_map or _load_role_map()
    bt_defs = rm["block_types"]
    hard = rm["hard_block_block_types"]
    ignore = set(rm["ignore_block_types"])
    answers = answers or {}

    inputs: dict[str, Any] = copy.deepcopy(existing_inputs) if existing_inputs else {}
    inputs.setdefault("metadata", {})
    inputs["metadata"]["run_id"] = run_id
    inputs["metadata"].setdefault("schema_version", _INPUTS_SCHEMA_VERSION)
    # (cap_base_source is stamped AFTER mapping — only when an equity base was actually produced; see end.)

    instruments: dict[str, Any] = {
        "safes": [],
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": run_id, "schema_version": _INSTRUMENTS_SCHEMA_VERSION},
    }
    blockers: list[dict[str, Any]] = []
    warnings: list[str] = []

    founders_acc: list[dict[str, Any]] = []
    preferred_acc: list[dict[str, Any]] = []
    option_pool_new: dict[str, Any] | None = None

    existing_pref_names = {
        p.get("series_name") for p in (existing_inputs or {}).get("preferred_series", []) if isinstance(p, dict)
    }

    def block_blocker(i: int, bt: str, field: str, reason: str) -> None:
        blockers.append({"block_index": i, "block_type": bt, "field": field, "reason": reason})

    safe_n = 0
    note_n = 0

    for i, block in enumerate(blocks):
        bt = block.get("block_type", "")
        if bt in ignore:
            continue
        if bt in hard:
            block_blocker(i, bt, "block", hard[bt])
            continue
        if bt not in bt_defs:
            block_blocker(i, bt, "block_type", f"unknown block_type {bt!r} (off-contract)")
            continue

        # (1a) Required block-field schema. An equity block MUST carry a non-empty cell_range AND a
        # non-empty column_role_map. The structure sub-agent sometimes drifts to row_range/columns; an
        # empty column_role_map then skips every row, silently mapping nothing — so fail loud and name
        # the correct field names instead of writing an empty cap base.
        cell_range = block.get("cell_range")
        role_map = block.get("column_role_map")
        if not (isinstance(cell_range, str) and cell_range.strip()):
            block_blocker(
                i,
                bt,
                "cell_range",
                "required field 'cell_range' (data rows, e.g. 'A5:F12') missing or empty; got keys "
                f"{sorted(block.keys())}. Emit cell_range + column_role_map, not row_range/columns.",
            )
            continue
        if not (isinstance(role_map, dict) and role_map):
            block_blocker(
                i,
                bt,
                "column_role_map",
                "required field 'column_role_map' (column-letter -> role) missing or empty; got keys "
                f"{sorted(block.keys())}. Emit cell_range + column_role_map, not row_range/columns.",
            )
            continue

        defn = bt_defs[bt]
        roles = defn["roles"]
        # Contract: every column_role_map value must be a known role for this block.
        unknown = [role for role in block.get("column_role_map", {}).values() if role not in roles]
        if unknown:
            for role in unknown:
                block_blocker(i, bt, role, f"unknown role {role!r} for {bt} (off-contract role-map value)")
            continue  # don't trust a contract-violating block

        rows = _block_rows(block, grid)
        cr_bare = str(block.get("cell_range", "")).split("!", 1)[-1]
        src = f"freeform:{block.get('sheet')}!{cr_bare}"
        if not rows:
            # MR-2: an equity block whose cell_range maps to zero data rows is a silent drop in the
            # MIXED case (the global 0-records backstop only fires when EVERY equity block is empty).
            # Surface it so a partially-dropped sheet is never reported as a clean success.
            warnings.append(
                f"block {i} ({bt}): cell_range {cr_bare!r} yielded 0 data rows — verify it points at the "
                "data rows (not headers/blank rows); this block contributed nothing."
            )

        if bt == "founders_block":
            for raw in rows:
                name = raw.get("holder_name")
                shares = _i(raw.get("shares"))
                if _is_blank(name):
                    block_blocker(i, bt, "name", "founder row missing holder_name")
                    continue
                if shares is None:
                    block_blocker(i, bt, "common_shares", f"founder {name!r} missing share count")
                    continue
                rec = {"name": str(name), "common_shares": shares}
                if not _is_blank(raw.get("founder_id")):
                    rec["founder_id"] = str(raw["founder_id"])
                if not _is_blank(raw.get("common_class")):
                    rec["common_class"] = str(raw["common_class"])
                if not _is_blank(raw.get("voting_multiple")):
                    rec["voting_rights_multiple"] = _f(raw["voting_multiple"])
                founders_acc.append(rec)

        elif bt == "preferred_series_block":
            for raw in rows:
                sname = raw.get("series_name")
                if _is_blank(sname):
                    block_blocker(i, bt, "series_name", "preferred row missing series_name")
                    continue
                oip = _f(raw.get("issue_price"))
                if oip is None:
                    block_blocker(i, bt, "original_issue_price", f"series {sname!r}: no issue price (never fabricated)")
                    continue
                ocp = _f(raw.get("original_conversion_price"))
                ocp = oip if ocp is None else ocp  # default 1:1 at fresh issuance
                ccp = _f(raw.get("current_conversion_price"))
                ccp = ocp if ccp is None else ccp
                idate = _to_iso_date(raw.get("issue_date"))
                if idate is None:
                    idate = _DATE_SENTINEL
                    warnings.append(f"preferred {sname!r}: issuance_date defaulted to {_DATE_SENTINEL} (confirm)")
                if sname in existing_pref_names or sname in {p["series_name"] for p in preferred_acc}:
                    block_blocker(
                        i, bt, "series_name", f"conflict: series {sname!r} already in inputs.json — keeping existing"
                    )
                    continue
                shares = _i(raw.get("shares")) or 0
                preferred_acc.append(
                    {
                        "series_name": str(sname),
                        "shares": shares,
                        "original_issue_price": oip,
                        "original_conversion_price": ocp,
                        "current_conversion_price": ccp,
                        "issuance_date": idate,
                    }
                )

        elif bt == "option_pool_block":
            if not rows:
                continue
            raw = rows[0]
            plan_type = answers.get(f"{i}.plan_type", raw.get("plan_type"))
            valid = defn["enum_fields"]["plan_type"]
            if _is_blank(plan_type) or plan_type not in valid:
                block_blocker(i, bt, "plan_type", f"plan_type {plan_type!r} absent or not in {valid}")
                continue
            authorized = _i(raw.get("authorized"))
            issued = _i(raw.get("issued")) or 0
            if authorized is None:
                block_blocker(i, bt, "authorized", "option_pool missing authorized share count")
                continue
            unalloc = _i(raw.get("unallocated"))
            if unalloc is None:
                unalloc = authorized - issued
            option_pool_new = {
                "plan_type": str(plan_type),
                "authorized": authorized,
                "issued": issued,
                "unallocated": unalloc,
            }

        elif bt == "safes_block":
            for raw in rows:
                inv = raw.get("investor_name")
                amt = _f(raw.get("amount"))
                if _is_blank(inv):
                    block_blocker(i, bt, "investor_name", "SAFE row missing investor_name")
                    continue
                if amt is None:
                    block_blocker(i, bt, "purchase_amount", f"SAFE {inv!r} missing purchase amount")
                    continue
                disc_raw = raw.get("discount")
                disc_mult, disc_warn = _normalize_discount(disc_raw)
                if disc_warn and not _is_blank(disc_raw):
                    warnings.append(f"SAFE {inv!r}: {disc_warn}")
                post_cap = _f(raw.get("post_money_cap"))
                pre_cap = _f(raw.get("pre_money_cap"))
                idate = _to_iso_date(raw.get("issue_date")) or _DATE_SENTINEL
                rec = {
                    "id": f"safe_{safe_n:03d}",
                    "investor_name": str(inv),
                    "purchase_amount": amt,
                    "post_money_valuation_cap": post_cap,
                    "pre_money_valuation_cap": pre_cap,
                    "discount_multiplier": disc_mult,
                    "issuance_date": idate,
                    "form": _infer_safe_form(post_cap if post_cap else pre_cap, disc_raw),
                    "source_document": src,
                    "extraction_confidence": "medium",
                }
                if post_cap and rec["form"] == "yc_postmoney_cap":
                    warnings.append(
                        f"SAFE {inv!r}: cap mapped post-money (freeform cannot distinguish "
                        "pre/post — confirm vintage, Gotcha #1)"
                    )
                safe_n += 1
                instruments["safes"].append(rec)

        elif bt == "notes_block":
            for raw in rows:
                inv = raw.get("investor_name")
                principal = _f(raw.get("principal"))
                if _is_blank(inv):
                    block_blocker(i, bt, "investor_name", "note row missing investor_name")
                    continue
                if principal is None:
                    block_blocker(i, bt, "principal", f"note {inv!r} missing principal")
                    continue
                irt = answers.get(f"{i}.interest_rate_type", raw.get("interest_rate_type"))
                valid = defn["enum_fields"]["interest_rate_type"]
                if _is_blank(irt) or irt not in valid:
                    block_blocker(
                        i,
                        bt,
                        "interest_rate_type",
                        f"interest_rate_type {irt!r} absent or not in {valid} (founder must confirm)",
                    )
                    continue
                disc_raw = raw.get("discount")
                disc_mult, disc_warn = _normalize_discount(disc_raw)
                if disc_warn and not _is_blank(disc_raw):
                    warnings.append(f"note {inv!r}: {disc_warn}")
                rec = {
                    "id": f"note_{note_n:03d}",
                    "investor_name": str(inv),
                    "principal": principal,
                    "annual_interest_rate": _f(raw.get("interest_rate")),
                    "interest_rate_type": str(irt),
                    "valuation_cap": _f(raw.get("valuation_cap")),
                    "discount_multiplier": disc_mult,
                    "issuance_date": _to_iso_date(raw.get("issue_date")) or _DATE_SENTINEL,
                    "maturity_date": _to_iso_date(raw.get("maturity_date")),
                    "source_document": src,
                    "extraction_confidence": "medium",
                }
                note_n += 1
                instruments["convertible_notes"].append(rec)

    # (1b) Global silent-empty backstop. ≥1 equity block was declared but produced ZERO records this
    # call (accumulators are pre-merge, so keep-existing duplicates still count as mapped) and no
    # per-block blocker already explains it → fail loud instead of writing an empty cap base. Catches a
    # well-formed block whose cell_range points at blank rows, which (1a)'s field-presence check cannot
    # see.
    if (
        any(b.get("block_type") in bt_defs for b in blocks)
        and not (founders_acc or preferred_acc or option_pool_new or safe_n or note_n)
        and not blockers
    ):
        block_blocker(
            -1,
            "*",
            "emit",
            "equity block(s) were declared but 0 records mapped — verify each cell_range points at the "
            "data rows and column_role_map names the columns; no rows were extracted.",
        )

    # --- merge equity into inputs (keep-existing-on-conflict + warn) ---
    if founders_acc:
        if (existing_inputs or {}).get("founders"):
            warnings.append("founders already present in inputs.json — keeping existing, ignoring sheet founders")
        else:
            inputs["founders"] = founders_acc
    if preferred_acc or existing_pref_names:
        inputs["preferred_series"] = list((existing_inputs or {}).get("preferred_series", [])) + preferred_acc
    if option_pool_new is not None:
        if (existing_inputs or {}).get("option_pool"):
            warnings.append("option_pool already present in inputs.json — keeping existing, ignoring sheet pool")
        else:
            inputs["option_pool"] = option_pool_new

    # Lane-3 carve-out for the cap_state default-to-assumed warn: the founder's sheet IS the cap-base
    # source of truth, so a freeform-mapped base is confirmed — but ONLY when the emit actually produced
    # or merged an equity base, never on an empty/partial result (so a downstream consumer can't read
    # "confirmed" off an empty cap base). setdefault keeps an explicit pre-existing value (e.g. "assumed").
    if (
        inputs.get("founders")
        or inputs.get("common_batches")
        or inputs.get("preferred_series")
        or inputs.get("option_pool")
    ):
        inputs["metadata"].setdefault("cap_base_source", "confirmed")

    blockers.sort(key=lambda b: (b["block_index"], b["field"]))
    return {"inputs": inputs, "instruments": instruments, "blockers": blockers, "warnings": warnings}
