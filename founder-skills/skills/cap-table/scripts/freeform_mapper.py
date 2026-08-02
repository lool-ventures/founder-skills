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
# Provenance marker stamped ONLY when this mapper genuinely produced the equity base from the sheet.
# Its ABSENCE on a confirmed base is what cap_state uses to flag a model-reconstructed base — so keep this
# spelling in lock-step with cap_state.py's check (a typo here would silently make every freeform run warn).
_PROVENANCE_DETERMINISTIC = "deterministic_mapped"
_INPUTS_SCHEMA_VERSION = "v0.5.0-inputs"
_INSTRUMENTS_SCHEMA_VERSION = "v0.5.0-instruments"


def _load_role_map(path: str | None = None) -> dict[str, Any]:
    with open(path or _ROLE_MAP_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _f(v: Any) -> float | None:
    # Crash-safe (L1-A): a non-numeric value in a numeric role returns None (→ the caller's
    # required-field blocker fires) instead of an uncaught ValueError. Blank also → None.
    if _is_blank(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    f = _f(v)
    return None if f is None else int(round(f))


def _resolve_prices(
    pricing_unknown: bool, oip_source: Any, ocp_source: Any, ccp_source: Any
) -> tuple[float, float, float] | None:
    """Resolve (original_issue_price, original_conversion_price, current_conversion_price)
    for one preferred-series record. `pricing_unknown` short-circuits to the numeric 1.0
    sentinel for all three (SHARED P5 CONSTANT: OIP=OCP=CCP=1.0), skipping the price gate
    entirely. Otherwise OIP must coerce to a positive number (never fabricated) or this
    returns None so the caller emits the blocker; OCP/CCP default forward (1:1 at fresh
    issuance, then no further adjustment) when absent."""
    if pricing_unknown:
        return 1.0, 1.0, 1.0
    oip = _f(oip_source)
    if oip is None or oip <= 0:
        return None
    ocp = _f(ocp_source)
    ocp = oip if ocp is None else ocp
    ccp = _f(ccp_source)
    ccp = ocp if ccp is None else ccp
    return oip, ocp, ccp


def _b(v: Any) -> bool:
    """Coerce a founder --answer value (arrives as a .strip()ed string, per
    extract_cap_table.py's --answer parsing) to bool. Only the literal 'true'
    (case-insensitive) is truthy; anything else (including None/blank) is False —
    never silently fabricates a True flag from garbage input."""
    if isinstance(v, bool):
        return v
    if _is_blank(v):
        return False
    return str(v).strip().lower() == "true"


# L1-A — orientation/type-coherence guard. A transposed sheet (holders/series as COLUMNS) mis-mapped to a
# normal vertical block produces records where a numeric-role column is text, or the name column is numeric
# / holds field labels. These sets drive the per-role coherence check in _orientation_blocker.
_NUMERIC_ROLES = {
    "shares",
    "common_shares",
    "amount",
    "principal",
    "issue_price",
    "original_conversion_price",
    "current_conversion_price",
    "authorized",
    "issued",
    "unallocated",
    "annual_interest_rate",
    "interest_rate",
    "discount",
    "discount_multiplier",
    "valuation_cap",
}
_NAME_ROLES = {"holder_name", "series_name", "investor_name"}
# Whole-cell, lowercased: unambiguous column-header terms that are never a real holder/series name.
# Also doubles as the P6 row_label discriminator's skip-list (see the row-level stoplist skip in
# map_freeform, scoped to preferred_series_block): a row whose row_label whole-cell-matches one of
# these is a Total/Subtotal row, not a holder. Whole-cell match ONLY — never substring/prefix — so a
# real fund named e.g. "Total Ventures Fund I" is never dropped.
_FIELD_LABEL_STOPLIST = {
    "shares",
    "total",
    "subtotal",
    "grand total",
    "totals",
    "sum",
    "price",
    "issue price",
    "ownership",
    "fully diluted",
    "authorized",
    "issued",
    "unallocated",
    "%",
}


def _looks_numeric(v: Any) -> bool:
    if _is_blank(v):
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _orientation_blocker(rows: list[dict[str, Any]]) -> str | None:
    """Detect a transposed / mis-mapped block by per-role TYPE COHERENCE.

    A numeric role whose column is predominantly non-numeric, or a name role whose column is
    predominantly numeric or holds a whole-cell field-label, signals a transposed/mis-mapped sheet
    (holders/series as COLUMNS). Returns a blocker reason, or None if correctly oriented. WHOLE-CELL
    match only (never substring), so legit entity names ("Class A Holdings", "500 Startups") pass.
    Does NOT catch the section-label all-numeric transpose (name col = arbitrary text, data numeric) —
    that residual is owned by L1-B (correct transpose mapping), per the reliability plan."""
    cols: dict[str, list[Any]] = {}
    for raw in rows:
        for role, val in raw.items():
            if not _is_blank(val):
                cols.setdefault(role, []).append(val)
    for role, vals in cols.items():
        if role in _NUMERIC_ROLES and vals:
            non_numeric = sum(1 for v in vals if not _looks_numeric(v))
            if non_numeric * 2 > len(vals):
                return (
                    f"column mapped to numeric role {role!r} is predominantly non-numeric "
                    f"({non_numeric}/{len(vals)} cells) — likely a transposed/mis-mapped sheet "
                    "(holders/series laid out as COLUMNS). Re-emit cell_range + column_role_map with the "
                    "correct orientation, or fall back to Lane 4."
                )
    for role, vals in cols.items():
        if role in _NAME_ROLES and vals:
            numeric = sum(1 for v in vals if _looks_numeric(v))
            if numeric * 2 > len(vals):
                return (
                    f"column mapped to name role {role!r} is predominantly numeric — likely a "
                    "transposed/mis-mapped sheet. Re-emit with the correct orientation."
                )
            for v in vals:
                if isinstance(v, str) and v.strip().lower() in _FIELD_LABEL_STOPLIST:
                    return (
                        f"name role {role!r} contains the field-label {v!r} as a holder/series name — "
                        "likely a transposed sheet (field labels down the name column). Re-emit correctly."
                    )
    return None


def _block_rows(block: dict[str, Any], grid: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield one {role: value} dict per non-blank row in the block's cell_range.

    column_role_map is keyed by COLUMN LETTER; rows from --mode=grid are sheet-origin
    positional tuples (column A == index 0), so a letter maps via column_index_from_string-1.

    P6 (wide-matrix): an optional block-level `role_constants` ({role: literal}) is stamped
    onto every surviving row — e.g. a matrix column's series_name, which lives in the column
    header rather than a per-row cell. The overlay MUST run AFTER the blank-row skip below,
    judged on COLUMN-SOURCED values only: stamping constants first would turn every blank
    spacer/subtotal row inside the range into a bogus non-blank record. Column value wins
    where a column already supplies a non-blank value for that role.

    P6 root-cause fix: the blank-row skip judges blankness on NON-`row_label` columns only. A
    `row_label` (the holder-name column re-attached to a per-series matrix block so a Total row
    can be recognized — see map_freeform) is populated on EVERY real matrix row, including a
    row where the block's own data column (e.g. `shares`) is blank for that holder. Judging
    blankness across ALL roles (row_label included) would never skip those legitimately-blank
    rows in a matrix, since the holder name alone would always keep the row alive.
    """
    sheet = block.get("sheet")
    cr = str(block.get("cell_range", ""))
    if "!" in cr:  # strip a "Sheet!A1:B2" qualifier
        cr = cr.split("!", 1)[1]
    _mc, min_row, _xc, max_row = range_boundaries(cr)
    rows = grid.get("sheets", {}).get(sheet, {}).get("rows", [])
    role_map = block.get("column_role_map", {})
    role_constants: dict[str, Any] = block.get("role_constants") or {}
    out: list[dict[str, Any]] = []
    for r in range(int(min_row or 1), int(max_row or 1) + 1):
        row = rows[r - 1] if 0 <= r - 1 < len(rows) else []
        raw: dict[str, Any] = {}
        for letter, role in role_map.items():
            ci = column_index_from_string(str(letter)) - 1
            raw[role] = row[ci] if 0 <= ci < len(row) else None
        if all(_is_blank(v) for role, v in raw.items() if role != "row_label"):
            continue  # blank / merged-spacer row — judged on column-sourced, non-row_label values
            # ONLY, i.e. BEFORE the role_constants overlay (see docstring / P6 ordering trap) and
            # ignoring row_label (a holder name alone must not keep an otherwise-blank row alive).
        for role, literal in role_constants.items():
            if _is_blank(raw.get(role)):
                raw[role] = literal
        out.append(raw)
    return out


def map_freeform(
    blocks: list[dict[str, Any]],
    grid: dict[str, Any],
    existing_inputs: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    run_id: str = "",
    role_map: dict[str, Any] | None = None,
    stated_total: int | None = None,
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
    common_batches_acc: list[dict[str, Any]] = []
    existing_cb_count = len((existing_inputs or {}).get("common_batches", []))
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

        # P6 capability 1: optional block-level constants — a role whose value is fixed for the
        # WHOLE block (e.g. a wide-matrix column's series_name, which lives in the column header,
        # not a per-row cell). Each key MUST already be a valid role for this block_type; anything
        # else is off-contract, never silently accepted. _block_rows overlays these onto every row
        # AFTER the blank-row skip (see its docstring) so a spacer/subtotal row inside the range
        # isn't turned into a bogus non-blank record.
        role_constants = block.get("role_constants")
        if role_constants is not None:
            if not isinstance(role_constants, dict):
                block_blocker(
                    i,
                    bt,
                    "role_constants",
                    "role_constants must be an object of role -> literal value (off-contract shape)",
                )
                continue
            bad_roles = [r for r in role_constants if r not in roles]
            if bad_roles:
                for r in bad_roles:
                    block_blocker(i, bt, r, f"unknown role {r!r} in role_constants for {bt} (off-contract)")
                continue

        # P6 capability 2: aggregate is opt-in, preferred_series_block ONLY — founders is
        # per-holder with no constant identity to sum by.
        aggregate = block.get("aggregate")
        if aggregate is not None:
            if bt != "preferred_series_block":
                block_blocker(
                    i,
                    bt,
                    "aggregate",
                    f"'aggregate' is not supported on {bt} (off-contract; preferred_series_block only)",
                )
                continue
            if aggregate != "sum_by_constant":
                block_blocker(
                    i, bt, "aggregate", f"unknown aggregate value {aggregate!r} (off-contract; only 'sum_by_constant')"
                )
                continue

        # P6 root-cause fix (d): stated_block_total is opt-in, validated NEXT TO aggregate — allowed
        # ONLY on an aggregated (sum_by_constant) preferred_series_block, mirroring the aggregate
        # validation shape immediately above. Off-contract placement (non-aggregate block,
        # non-preferred block, or a non-numeric value) is a blocker, never silently ignored.
        stated_block_total: int | None = None
        stated_block_total_raw = block.get("stated_block_total")
        if stated_block_total_raw is not None:
            if bt != "preferred_series_block" or aggregate != "sum_by_constant":
                block_blocker(
                    i,
                    bt,
                    "stated_block_total",
                    "'stated_block_total' is not supported here (off-contract; aggregated "
                    "preferred_series_block with aggregate='sum_by_constant' ONLY)",
                )
                continue
            stated_block_total = _i(stated_block_total_raw)
            if stated_block_total is None or stated_block_total <= 0:
                block_blocker(
                    i,
                    bt,
                    "stated_block_total",
                    f"stated_block_total {stated_block_total_raw!r} must coerce to a positive integer (off-contract)",
                )
                continue

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

        # L1-A: fail loud on a transposed / type-incoherent block instead of crashing or silently
        # emitting garbage records. (Section-label all-numeric transpose remains a residual — L1-B.)
        _orient = _orientation_blocker(rows)
        if _orient:
            block_blocker(i, bt, "orientation", _orient)
            continue

        # P6 root-cause fix (b): row-level stoplist skip. Scoped to preferred_series_block and
        # placed BEFORE both the aggregated (sum_by_constant) and per-row branches below, so a
        # Total/Subtotal/Grand total/Sum row that made it into cell_range never reaches either
        # summation or per-row record creation. Deliberately does NOT add "row_label" to
        # _NAME_ROLES (see that set's comment) — that's what keeps _orientation_blocker above
        # from hard-blocking the whole block on a "Total" row in the label column.
        if bt == "preferred_series_block":
            kept_rows: list[dict[str, Any]] = []
            stoplist_skips: list[tuple[str, Any]] = []
            for raw in rows:
                lbl = raw.get("row_label")
                if isinstance(lbl, str) and lbl.strip().lower() in _FIELD_LABEL_STOPLIST:
                    shares_val = raw.get("shares")
                    if not _is_blank(shares_val):
                        stoplist_skips.append((lbl.strip(), shares_val))
                    continue  # value-less label rows are silently dropped — no warning (pure noise)
                kept_rows.append(raw)
            if stoplist_skips:

                def _fmt_shares(v: Any) -> str:
                    iv = _i(v)
                    return f"{iv:,}" if iv is not None else str(v)

                detail = ", ".join(f"{lbl!r} (shares={_fmt_shares(val)})" for lbl, val in stoplist_skips)
                warnings.append(
                    f"block {i} ({bt}): skipped {len(stoplist_skips)} row(s) whose row_label matched the "
                    f"label stoplist (e.g. 'Total') and excluded their share value(s) from the sum: {detail}"
                )
            rows = kept_rows

        if bt == "founders_block":
            skipped_blank_common: list[str] = []
            for raw in rows:
                name = raw.get("holder_name")
                if _is_blank(name):
                    block_blocker(i, bt, "name", "founder row missing holder_name")
                    continue
                shares_raw = raw.get("shares")
                if _is_blank(shares_raw):
                    # P6: in a wide-matrix sheet a preferred-only holder (e.g. a VC fund with no
                    # Ordinary shares) has a blank common-column cell for this row. SKIP it rather
                    # than hard-blocking the whole founders_block on every non-common holder — but
                    # WARN (below) so a genuine data-entry gap ("this founder's cell was mistakenly
                    # left empty") still surfaces instead of silently shrinking the founder base.
                    # An explicit 0 is NOT blank (_i(0) == 0) and is never skipped here.
                    skipped_blank_common.append(str(name))
                    continue
                shares = _i(shares_raw)
                if shares is None:
                    block_blocker(i, bt, "common_shares", f"founder {name!r} has a non-numeric share count")
                    continue
                rec: dict[str, Any] = {"name": str(name), "common_shares": shares}
                if not _is_blank(raw.get("founder_id")):
                    rec["founder_id"] = str(raw["founder_id"])
                if not _is_blank(raw.get("common_class")):
                    rec["common_class"] = str(raw["common_class"])
                if not _is_blank(raw.get("voting_multiple")):
                    rec["voting_rights_multiple"] = _f(raw["voting_multiple"])
                founders_acc.append(rec)
            if skipped_blank_common:
                warnings.append(
                    f"block {i} ({bt}): skipped {len(skipped_blank_common)} rows with blank common column: "
                    + ", ".join(skipped_blank_common)
                )

        elif bt == "common_holders_block":
            # Non-founder common/ordinary holders (angels, ex-employees, nominee trusts) → their own
            # common_batches records, NOT the founders block. holder_id auto-assigns when not mapped;
            # issuance_date sentinels when the sheet has no date column (mirrors safes_block).
            for raw in rows:
                shares_raw = raw.get("shares")
                if _is_blank(shares_raw):
                    block_blocker(i, bt, "shares", "common holder row missing shares")
                    continue
                cb_shares = _i(shares_raw)
                if cb_shares is None:
                    block_blocker(i, bt, "shares", "common holder row has a non-numeric share count")
                    continue
                cbrec: dict[str, Any] = {"shares": cb_shares}
                hid = raw.get("holder_id")
                if not _is_blank(hid):
                    cbrec["holder_id"] = str(hid)
                else:
                    cbrec["holder_id"] = f"common_{existing_cb_count + len(common_batches_acc) + 1:03d}"
                cb_name = raw.get("holder_name")
                if not _is_blank(cb_name):
                    cbrec["holder_name"] = str(cb_name)
                cb_idate = _to_iso_date(raw.get("issue_date"))
                if cb_idate is None:
                    cb_idate = _DATE_SENTINEL
                    warnings.append(
                        f"common holder {cbrec.get('holder_name', cbrec['holder_id'])}: "
                        f"issuance_date defaulted to {_DATE_SENTINEL} (confirm)"
                    )
                cbrec["issuance_date"] = cb_idate
                if not _is_blank(raw.get("common_class")):
                    cbrec["common_class"] = str(raw["common_class"])
                if not _is_blank(raw.get("voting_multiple")):
                    cbrec["voting_rights_multiple"] = _f(raw["voting_multiple"])
                common_batches_acc.append(cbrec)

        elif bt == "preferred_series_block":
            # P5: --answer <i>.pricing_unknown=true applies uniformly to every row this block
            # emits (same convention as plan_type/interest_rate_type below): a series flagged
            # pricing_unknown gets the numeric 1.0 sentinel for OIP/OCP/CCP + AD forced to "none",
            # and SKIPS the issue-price blocker entirely (SHARED P5 CONSTANT contract).
            pricing_unknown = _b(answers.get(f"{i}.pricing_unknown"))

            if aggregate == "sum_by_constant":
                # P6 root-cause fix (b), missing-label visibility: without a row_label column
                # mapped, the row-level stoplist skip above had nothing to check — a Total row
                # inside cell_range is invisible to this block, same as before the fix. Warn so
                # that gap is surfaced instead of silently relying on cell_range precision alone.
                mapped_roles = set(block.get("column_role_map", {}).values()) | set(
                    (block.get("role_constants") or {}).keys()
                )
                if "row_label" not in mapped_roles:
                    warnings.append(
                        f"block {i} ({bt}): aggregated block has no row_label column mapped — a "
                        "Total/subtotal row inside cell_range cannot be detected; relying on "
                        "cell_range precision."
                    )

                # P6 capability 2: the block's rows are per-holder share counts in ONE matrix
                # column; collapse them into a single series record (dup-guard suppressed WITHIN
                # this block — many rows -> one record by design). OIP/OCP/CCP/series_name/
                # issue_date are read off whatever role_constants stamped (or a per-row column,
                # if one happens to be mapped) — the FIRST non-blank value across rows wins.
                total_shares = 0
                sname: Any = None
                idate: str | None = None
                oip_row: Any = None
                ocp_row: Any = None
                ccp_row: Any = None
                for raw in rows:
                    row_sname = raw.get("series_name")
                    if not _is_blank(row_sname):
                        sname = row_sname
                    s = _i(raw.get("shares"))
                    if s is not None:
                        total_shares += s
                    if oip_row is None and not _is_blank(raw.get("issue_price")):
                        oip_row = raw.get("issue_price")
                    if ocp_row is None and not _is_blank(raw.get("original_conversion_price")):
                        ocp_row = raw.get("original_conversion_price")
                    if ccp_row is None and not _is_blank(raw.get("current_conversion_price")):
                        ccp_row = raw.get("current_conversion_price")
                    if idate is None:
                        row_idate = _to_iso_date(raw.get("issue_date"))
                        if row_idate is not None:
                            idate = row_idate

                if _is_blank(sname):
                    block_blocker(
                        i,
                        bt,
                        "series_name",
                        "aggregated preferred block has no series_name (supply role_constants.series_name "
                        "or a per-row series_name column)",
                    )
                    continue

                # P6 root-cause fix (d): deterministic cross-foot. Catches EXACTLY the residual the
                # row_label discriminator can't see on its own — e.g. an unlabeled total row left
                # inside cell_range — by comparing the (post-row_label-skip) summed shares against
                # the sheet's own printed column total. Exact int compare: shares are integers.
                if stated_block_total is not None and total_shares != stated_block_total:
                    block_blocker(
                        i,
                        bt,
                        "stated_block_total",
                        f"series {sname!r} (aggregated): summed shares {total_shares:,} != "
                        f"column-stated total {stated_block_total:,} — cell_range likely "
                        "includes/omits a row",
                    )
                    continue

                oip_answer = answers.get(f"{i}.original_issue_price", oip_row)
                prices = _resolve_prices(pricing_unknown, oip_answer, ocp_row, ccp_row)
                if prices is None:
                    block_blocker(
                        i,
                        bt,
                        "original_issue_price",
                        f"series {sname!r} (aggregated): no issue price (never fabricated) — supply "
                        "role_constants.issue_price, --answer, or pricing_unknown",
                    )
                    continue
                oip, ocp, ccp = prices

                if idate is None:
                    idate = _DATE_SENTINEL
                    warnings.append(
                        f"preferred {sname!r} (aggregated): issuance_date defaulted to {_DATE_SENTINEL} (confirm)"
                    )
                if sname in existing_pref_names or sname in {p["series_name"] for p in preferred_acc}:
                    block_blocker(
                        i, bt, "series_name", f"conflict: series {sname!r} already in inputs.json — keeping existing"
                    )
                    continue
                agg_rec: dict[str, Any] = {
                    "series_name": str(sname),
                    "shares": total_shares,
                    "original_issue_price": oip,
                    "original_conversion_price": ocp,
                    "current_conversion_price": ccp,
                    "issuance_date": idate,
                }
                if pricing_unknown:
                    agg_rec["anti_dilution_protection"] = "none"
                    agg_rec["pricing_unknown"] = True
                preferred_acc.append(agg_rec)
                continue  # aggregated: one record for the whole block, not per-row

            for raw in rows:
                sname = raw.get("series_name")
                if _is_blank(sname):
                    block_blocker(i, bt, "series_name", "preferred row missing series_name")
                    continue
                # P4: an --answer for this block's index wins over the column value (mirrors the
                # plan_type / interest_rate_type answer pattern below) — coerced numeric, required
                # > 0, else the blocker stands. P5: pricing_unknown short-circuits to the sentinel.
                oip_answer = answers.get(f"{i}.original_issue_price", raw.get("issue_price"))
                prices = _resolve_prices(
                    pricing_unknown,
                    oip_answer,
                    raw.get("original_conversion_price"),
                    raw.get("current_conversion_price"),
                )
                if prices is None:
                    block_blocker(i, bt, "original_issue_price", f"series {sname!r}: no issue price (never fabricated)")
                    continue
                oip, ocp, ccp = prices
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
                series_rec: dict[str, Any] = {
                    "series_name": str(sname),
                    "shares": shares,
                    "original_issue_price": oip,
                    "original_conversion_price": ocp,
                    "current_conversion_price": ccp,
                    "issuance_date": idate,
                }
                if pricing_unknown:
                    series_rec["anti_dilution_protection"] = "none"
                    series_rec["pricing_unknown"] = True
                preferred_acc.append(series_rec)

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
                idate = _to_iso_date(raw.get("issue_date"))
                if idate is None:
                    idate = _DATE_SENTINEL
                    warnings.append(f"SAFE {inv!r}: issuance_date defaulted to {_DATE_SENTINEL} (confirm)")
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
                ndate = _to_iso_date(raw.get("issue_date"))
                if ndate is None:
                    ndate = _DATE_SENTINEL
                    warnings.append(f"note {inv!r}: issuance_date defaulted to {_DATE_SENTINEL} (confirm)")
                rec = {
                    "id": f"note_{note_n:03d}",
                    "investor_name": str(inv),
                    "principal": principal,
                    "annual_interest_rate": _f(raw.get("interest_rate")),
                    "interest_rate_type": str(irt),
                    "valuation_cap": _f(raw.get("valuation_cap")),
                    "discount_multiplier": disc_mult,
                    "issuance_date": ndate,
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
        and not (founders_acc or common_batches_acc or preferred_acc or option_pool_new or safe_n or note_n)
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
    if common_batches_acc:
        # keep-existing + append the sheet's common holders (no id collision: new ids are offset
        # past the existing count).
        inputs["common_batches"] = list((existing_inputs or {}).get("common_batches", [])) + common_batches_acc
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

    # Provenance: stamp deterministic_mapped ONLY when the mapper itself produced equity THIS call
    # (the accumulators) — NOT merely when inputs.get(...) is truthy, which would inherit equity merged
    # from existing_inputs and falsely claim a model-built base was deterministically mapped.
    if founders_acc or common_batches_acc or preferred_acc or option_pool_new or safe_n or note_n:
        inputs["metadata"].setdefault("cap_base_provenance", _PROVENANCE_DETERMINISTIC)

    # The sheet's OWN printed grand fully-diluted total (independent of the rows we rebuild) → cross-foot
    # source. cap_state compares it to the computed FD and emits W_FD_RECONCILE_DELTA on a >0.1% divergence,
    # catching a dropped/mis-mapped class. Only a SOURCE-printed total (non-circular); absent => no key. The
    # caller must pass ONLY a fully-diluted, pool-inclusive printed total (same basis as the computed FD).
    if isinstance(stated_total, int) and not isinstance(stated_total, bool) and stated_total > 0:
        inputs["stated_totals"] = {"fully_diluted": stated_total, "source": "freeform_grid"}
    blockers.sort(key=lambda b: (b["block_index"], b["field"]))
    return {"inputs": inputs, "instruments": instruments, "blockers": blockers, "warnings": warnings}
