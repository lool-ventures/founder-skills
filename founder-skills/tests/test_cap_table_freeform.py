"""Lane-3 freeform deterministic-mapping tests (Phase 2).

Drives `freeform_mapper.map_freeform` — the pure function that maps a
SPREADSHEET_STRUCTURE_DETECTION block set + cell grid into schema-valid
inputs/instruments proposals plus an explicit blocker list. No live agent, no
LLM: a fixed (blocks, grid) input must map deterministically.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402
import freeform_mapper as fm  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402

RUN = "testrun01"


def _grid(sheets: dict[str, list[list]]) -> dict:
    """Build a --mode=grid-shaped payload from {sheet_name: rows}."""
    return {
        "ok": True,
        "mode": "grid",
        "sheets": {name: {"dimensions": "", "rows": rows, "merged_ranges": []} for name, rows in sheets.items()},
    }


def _meta_inputs() -> dict:
    """A Step-2 inputs.json carrying company meta only (no equity)."""
    return {
        "company_name": "Cadence",
        "analysis_date": "2026-06-19",
        "mode": "standard",
        "metadata": {"run_id": RUN, "schema_version": "v0.5.0-inputs"},
    }


def _blockers_for(result: dict, field: str) -> list[dict]:
    return [b for b in result["blockers"] if b["field"] == field]


# --- founders ---------------------------------------------------------------


def test_founders_block_happy() -> None:
    blocks = [
        {
            "block_type": "founders_block",
            "sheet": "Cap",
            "cell_range": "A2:B3",
            "column_role_map": {"A": "holder_name", "B": "shares"},
        }
    ]
    grid = _grid({"Cap": [["Name", "Shares"], ["Alice", 5000000], ["Bob", 5000000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert r["blockers"] == []
    founders = r["inputs"]["founders"]
    assert [(f["name"], f["common_shares"]) for f in founders] == [("Alice", 5000000), ("Bob", 5000000)]
    # company meta carried forward untouched
    assert r["inputs"]["company_name"] == "Cadence"
    assert r["inputs"]["metadata"]["schema_version"] == "v0.5.0-inputs"


def test_blank_rows_in_range_skipped() -> None:
    blocks = [
        {
            "block_type": "founders_block",
            "sheet": "Cap",
            "cell_range": "A2:B4",
            "column_role_map": {"A": "holder_name", "B": "shares"},
        }
    ]
    # row 3 (index 2) fully blank (merged-cell / spacer) -> skipped, not a record
    grid = _grid({"Cap": [["Name", "Shares"], ["Alice", 5000000], [None, None], ["Bob", 5000000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert [f["name"] for f in r["inputs"]["founders"]] == ["Alice", "Bob"]


# --- safes ------------------------------------------------------------------


def test_safes_block_happy_form_discount_id_sentinel() -> None:
    blocks = [
        {
            "block_type": "safes_block",
            "sheet": "SAFEs",
            "cell_range": "A2:D2",
            "column_role_map": {"A": "investor_name", "B": "amount", "C": "post_money_cap", "D": "discount"},
        }
    ]
    grid = _grid({"SAFEs": [["Investor", "Amount", "Cap", "Disc"], ["Acme Ventures", 500000, 20000000, 0.20]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert r["blockers"] == []
    s = r["instruments"]["safes"][0]
    assert s["id"] == "safe_000"
    assert s["investor_name"] == "Acme Ventures"
    assert s["purchase_amount"] == 500000.0
    assert s["post_money_valuation_cap"] == 20000000.0
    assert s["discount_multiplier"] == 0.8  # 0.20 rate -> 0.80 multiplier
    assert s["form"] == "cap_plus_discount"
    assert s["issuance_date"] == "1900-01-01"  # sentinel: no issue_date column
    assert s["extraction_confidence"] == "medium"
    assert s["source_document"].startswith("freeform:")


def test_two_safes_blocks_no_id_collision() -> None:
    blocks = [
        {
            "block_type": "safes_block",
            "sheet": "S",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "amount"},
        },
        {
            "block_type": "safes_block",
            "sheet": "S",
            "cell_range": "A5:B5",
            "column_role_map": {"A": "investor_name", "B": "amount"},
        },
    ]
    grid = _grid(
        {
            "S": [
                ["I", "A"],
                ["First", 100000],
                [None, None],
                [None, None],
                ["Second", 200000],
            ]
        }
    )
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    ids = [s["id"] for s in r["instruments"]["safes"]]
    assert ids == ["safe_000", "safe_001"]  # per-array, not per-block -> no collision


def test_discount_rate_forms_both_normalize() -> None:
    for raw, expect in [(20, 0.8), (0.20, 0.8)]:
        blocks = [
            {
                "block_type": "safes_block",
                "sheet": "S",
                "cell_range": "A2:C2",
                "column_role_map": {"A": "investor_name", "B": "amount", "C": "discount"},
            }
        ]
        grid = _grid({"S": [["I", "A", "D"], ["X", 100000, raw]]})
        r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
        assert r["instruments"]["safes"][0]["discount_multiplier"] == expect


# --- notes (interest_rate_type blocker + answer) ----------------------------


def test_notes_missing_interest_rate_type_blocks() -> None:
    blocks = [
        {
            "block_type": "notes_block",
            "sheet": "N",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "principal"},
        }
    ]
    grid = _grid({"N": [["I", "P"], ["Lender", 250000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert _blockers_for(r, "interest_rate_type"), "missing required enum must block"
    assert r["instruments"]["convertible_notes"] == []  # not emitted while blocked


def test_notes_answer_completes_block() -> None:
    blocks = [
        {
            "block_type": "notes_block",
            "sheet": "N",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "principal"},
        }
    ]
    grid = _grid({"N": [["I", "P"], ["Lender", 250000]]})
    r = fm.map_freeform(
        blocks,
        grid,
        existing_inputs=_meta_inputs(),
        answers={"0.interest_rate_type": "fixed_numeric_simple"},
        run_id=RUN,
    )
    assert r["blockers"] == []
    n = r["instruments"]["convertible_notes"][0]
    assert n["id"] == "note_000"
    assert n["interest_rate_type"] == "fixed_numeric_simple"
    assert n["principal"] == 250000.0


def test_notes_answer_rejects_non_enum() -> None:
    blocks = [
        {
            "block_type": "notes_block",
            "sheet": "N",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "principal"},
        }
    ]
    grid = _grid({"N": [["I", "P"], ["Lender", 250000]]})
    r = fm.map_freeform(
        blocks, grid, existing_inputs=_meta_inputs(), answers={"0.interest_rate_type": "weekly_compound"}, run_id=RUN
    )
    assert _blockers_for(r, "interest_rate_type"), "a non-enum answer must still block"


# --- preferred --------------------------------------------------------------


def test_preferred_missing_oip_blocks() -> None:
    blocks = [
        {
            "block_type": "preferred_series_block",
            "sheet": "P",
            "cell_range": "A2:C2",
            "column_role_map": {"A": "series_name", "B": "shares", "C": "issue_date"},
        }
    ]
    grid = _grid({"P": [["S", "Sh", "D"], ["Series A", 2000000, "2025-01-01"]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert _blockers_for(r, "original_issue_price"), "no price column -> blocker, never fabricated"


def test_preferred_cp_defaults_to_oip() -> None:
    blocks = [
        {
            "block_type": "preferred_series_block",
            "sheet": "P",
            "cell_range": "A2:D2",
            "column_role_map": {"A": "series_name", "B": "shares", "C": "issue_price", "D": "issue_date"},
        }
    ]
    grid = _grid({"P": [["S", "Sh", "Px", "D"], ["Series A", 2000000, 1.25, "2025-01-01"]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert r["blockers"] == []
    ps = r["inputs"]["preferred_series"][0]
    assert ps["original_issue_price"] == 1.25
    assert ps["original_conversion_price"] == 1.25  # default 1:1 at fresh issuance
    assert ps["current_conversion_price"] == 1.25


def test_preferred_dup_series_name_conflict_keeps_existing() -> None:
    existing = _meta_inputs()
    existing["preferred_series"] = [
        {
            "series_name": "Series A",
            "shares": 1,
            "original_issue_price": 9.99,
            "original_conversion_price": 9.99,
            "current_conversion_price": 9.99,
            "issuance_date": "2020-01-01",
        }
    ]
    blocks = [
        {
            "block_type": "preferred_series_block",
            "sheet": "P",
            "cell_range": "A2:D2",
            "column_role_map": {"A": "series_name", "B": "shares", "C": "issue_price", "D": "issue_date"},
        }
    ]
    grid = _grid({"P": [["S", "Sh", "Px", "D"], ["Series A", 2000000, 1.25, "2025-01-01"]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=existing, run_id=RUN)
    # conflict -> existing kept (no clobber), surfaced as a blocker
    assert any(b["block_type"] == "preferred_series_block" and "conflict" in b["reason"].lower() for b in r["blockers"])
    kept = [p for p in r["inputs"]["preferred_series"] if p["series_name"] == "Series A"]
    assert len(kept) == 1 and kept[0]["original_issue_price"] == 9.99


# --- option_pool ------------------------------------------------------------


def test_option_pool_unallocated_computed() -> None:
    blocks = [
        {
            "block_type": "option_pool_block",
            "sheet": "O",
            "cell_range": "A2:C2",
            "column_role_map": {"A": "plan_type", "B": "authorized", "C": "issued"},
        }
    ]
    grid = _grid({"O": [["Plan", "Auth", "Iss"], ["iso", 1000000, 250000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert r["blockers"] == []
    pool = r["inputs"]["option_pool"]
    assert pool["plan_type"] == "iso"
    assert pool["authorized"] == 1000000
    assert pool["issued"] == 250000
    assert pool["unallocated"] == 750000  # computed authorized - issued


def test_option_pool_non_enum_plan_type_blocks() -> None:
    blocks = [
        {
            "block_type": "option_pool_block",
            "sheet": "O",
            "cell_range": "A2:C2",
            "column_role_map": {"A": "plan_type", "B": "authorized", "C": "issued"},
        }
    ]
    grid = _grid({"O": [["Plan", "Auth", "Iss"], ["ESOP", 1000000, 250000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert _blockers_for(r, "plan_type"), "non-enum plan_type must block"


# --- contract violations ----------------------------------------------------


def test_unknown_role_blocks() -> None:
    blocks = [
        {
            "block_type": "founders_block",
            "sheet": "Cap",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "holder_name", "B": "magic_unknown_role"},
        }
    ]
    grid = _grid({"Cap": [["N", "X"], ["Alice", 5000000]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert _blockers_for(r, "magic_unknown_role"), "an off-contract role must block, never silently skip"


def test_warrants_and_grants_hard_block() -> None:
    for bt in ("warrants_block", "options_grants_block"):
        blocks = [{"block_type": bt, "sheet": "W", "cell_range": "A2:B2", "column_role_map": {"A": "x"}}]
        grid = _grid({"W": [["a", "b"], ["c", "d"]]})
        r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
        assert any(b["block_type"] == bt for b in r["blockers"]), f"{bt} must hard-block, not silently drop"


def test_ignore_block_types_no_op() -> None:
    blocks = [{"block_type": "noise", "sheet": "X", "cell_range": "A1:A1", "column_role_map": {}}]
    grid = _grid({"X": [[None]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert r["blockers"] == []
    assert r["instruments"]["safes"] == []


# --- cell_range forms + determinism ----------------------------------------


def test_sheet_qualified_range_equivalent_to_bare() -> None:
    grid = _grid({"Cap": [["N", "S"], ["Alice", 5000000]]})
    rm = {"A": "holder_name", "B": "shares"}
    bare = fm.map_freeform(
        [{"block_type": "founders_block", "sheet": "Cap", "cell_range": "A2:B2", "column_role_map": rm}],
        grid,
        existing_inputs=_meta_inputs(),
        run_id=RUN,
    )
    qual = fm.map_freeform(
        [{"block_type": "founders_block", "sheet": "Cap", "cell_range": "Cap!A2:B2", "column_role_map": rm}],
        grid,
        existing_inputs=_meta_inputs(),
        run_id=RUN,
    )
    assert bare["inputs"]["founders"] == qual["inputs"]["founders"]


def test_run_twice_byte_identical() -> None:
    blocks = [
        {
            "block_type": "safes_block",
            "sheet": "S",
            "cell_range": "A2:D2",
            "column_role_map": {"A": "investor_name", "B": "amount", "C": "post_money_cap", "D": "discount"},
        }
    ]
    grid = _grid({"S": [["I", "A", "C", "D"], ["Acme", 500000, 20000000, 0.20]]})
    a = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    b = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)


def test_blockers_sorted_deterministically() -> None:
    # two blocked blocks; blockers must be a stable sorted list (not set ordering)
    blocks = [
        {
            "block_type": "notes_block",
            "sheet": "N",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "investor_name", "B": "principal"},
        },
        {
            "block_type": "option_pool_block",
            "sheet": "O",
            "cell_range": "A2:B2",
            "column_role_map": {"A": "authorized", "B": "issued"},
        },
    ]
    grid = _grid({"N": [["I", "P"], ["L", 1000]], "O": [["A", "Iss"], [100, 10]]})
    r = fm.map_freeform(blocks, grid, existing_inputs=_meta_inputs(), run_id=RUN)
    keys = [(b["block_index"], b["field"]) for b in r["blockers"]]
    assert keys == sorted(keys)


# --- Phase 0d: cap_state no-equity-base guard --------------------------------

_A_SAFE = {
    "id": "safe_000",
    "investor_name": "Acme",
    "purchase_amount": 500000.0,
    "issuance_date": "2025-01-01",
    "form": "yc_postmoney_cap",
    "post_money_valuation_cap": 20000000.0,
    "extraction_confidence": "medium",
}


def _instruments(safes: list[dict]) -> dict:
    return {
        "safes": safes,
        "convertible_notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": RUN, "schema_version": "v0.5.0-instruments"},
    }


def test_cap_state_blocks_no_equity_base_with_instruments() -> None:
    """Absent founders AND absent option_pool + instruments → loud error, not silent zeros."""
    inputs = _meta_inputs()  # company meta only — no founders, no option_pool
    with pytest.raises(cap_state_mod.CapStateInvariantError, match="E_NO_EQUITY_BASE"):
        cap_state_mod.build_cap_state(inputs, _instruments([_A_SAFE]))


def test_cap_state_present_but_zero_pool_does_not_trip_guard() -> None:
    """A present-but-zero option_pool (founders []) must NOT trip the guard (regression)."""
    inputs = _meta_inputs()
    inputs["founders"] = []
    inputs["option_pool"] = {"plan_type": "nso", "authorized": 0, "issued": 0, "unallocated": 0}
    cs = cap_state_mod.build_cap_state(inputs, _instruments([_A_SAFE]))  # must not raise
    assert cs is not None


# --- Phase 3: --mode=freeform-emit CLI wrapper (end-to-end) -----------------


def test_freeform_emit_cli_writes_schema_valid_artifacts(tmp_path) -> None:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    ws.title = "Cap Table"
    for row in [
        ["Name", "Shares"],
        ["Alice", 5000000],
        ["Bob", 5000000],
        [None, None],
        ["Investor", "Amt", "Cap"],
        ["Acme", 500000, 20000000],
    ]:
        ws.append(row)
    xlsx = tmp_path / "cap.xlsx"
    wb.save(xlsx)
    (tmp_path / "inputs.json").write_text(
        json.dumps(
            {
                "company_name": "Cadence",
                "analysis_date": "2026-06-19",
                "mode": "standard",
                "metadata": {"run_id": "R1", "schema_version": "v0.5.0-inputs"},
            }
        )
    )
    blocks = json.dumps(
        {
            "blocks": [
                {
                    "block_type": "founders_block",
                    "sheet": "Cap Table",
                    "cell_range": "A2:B3",
                    "column_role_map": {"A": "holder_name", "B": "shares"},
                },
                {
                    "block_type": "safes_block",
                    "sheet": "Cap Table",
                    "cell_range": "A6:C6",
                    "column_role_map": {"A": "investor_name", "B": "amount", "C": "post_money_cap"},
                },
            ]
        }
    )
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(SCRIPTS, "extract_cap_table.py"),
            "--mode=freeform-emit",
            "--xlsx",
            str(xlsx),
            "--dir",
            str(tmp_path),
            "--run-id",
            "R1",
        ],
        input=blocks,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["ok"] is True
    inputs = json.loads((tmp_path / "inputs.json").read_text())
    instruments = json.loads((tmp_path / "instruments.json").read_text())
    assert [f["name"] for f in inputs["founders"]] == ["Alice", "Bob"]
    assert inputs["company_name"] == "Cadence"  # meta preserved
    assert instruments["safes"][0]["id"] == "safe_000"
    assert instruments["safes"][0]["post_money_valuation_cap"] == 20000000.0


def test_freeform_emit_cli_blocker_is_a_gate_not_error(tmp_path) -> None:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    ws.title = "N"
    ws.append(["Investor", "Principal"])
    ws.append(["Lender", 250000])
    wb.save(tmp_path / "n.xlsx")
    (tmp_path / "inputs.json").write_text(
        json.dumps(
            {
                "company_name": "Cadence",
                "analysis_date": "2026-06-19",
                "mode": "standard",
                "metadata": {"run_id": "R1", "schema_version": "v0.5.0-inputs"},
            }
        )
    )
    blocks = json.dumps(
        {
            "blocks": [
                {
                    "block_type": "notes_block",
                    "sheet": "N",
                    "cell_range": "A2:B2",
                    "column_role_map": {"A": "investor_name", "B": "principal"},
                }
            ]
        }
    )
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(SCRIPTS, "extract_cap_table.py"),
            "--mode=freeform-emit",
            "--xlsx",
            str(tmp_path / "n.xlsx"),
            "--dir",
            str(tmp_path),
            "--run-id",
            "R1",
        ],
        input=blocks,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0  # a gate, not an error
    receipt = json.loads(proc.stdout)
    assert receipt["ok"] is False
    assert any(b["field"] == "interest_rate_type" for b in receipt["blockers"])
    assert not (tmp_path / "instruments.json").exists()  # nothing written while blocked


# --- Part 2: next_action branches on blocker kind ---------------------------
# An off-contract block_type/role is NOT founder-answerable — telling the agent to
# "ask the founder / re-run with --answer" is wrong advice. The producer must steer
# an off-contract blocker to a re-dispatch instead.


def _emit_cli(tmp_path, sheet_rows: list, blocks: dict) -> dict:
    """Run --mode=freeform-emit over a one-sheet xlsx + blocks; return the receipt."""
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    for row in sheet_rows:
        ws.append(row)
    wb.save(tmp_path / "s.xlsx")
    (tmp_path / "inputs.json").write_text(
        json.dumps(
            {
                "company_name": "Cadence",
                "analysis_date": "2026-06-19",
                "mode": "standard",
                "metadata": {"run_id": "R1", "schema_version": "v0.5.0-inputs"},
            }
        )
    )
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(SCRIPTS, "extract_cap_table.py"),
            "--mode=freeform-emit",
            "--xlsx",
            str(tmp_path / "s.xlsx"),
            "--dir",
            str(tmp_path),
            "--run-id",
            "R1",
        ],
        input=json.dumps(blocks),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_offcontract_blocktype_next_action_says_redispatch(tmp_path) -> None:
    receipt = _emit_cli(
        tmp_path,
        [["Exit", "Proceeds"], [1_000_000, 500_000]],
        {
            "blocks": [
                {
                    "block_type": "waterfall_scenarios",  # off-contract: not in the closed vocabulary
                    "sheet": "S",
                    "cell_range": "A2:B2",
                    "column_role_map": {"A": "exit", "B": "proceeds"},
                }
            ]
        },
    )
    assert receipt["ok"] is False
    na = receipt["next_action"].lower()
    # off-contract → steer to re-dispatch, not to the founder/--answer path
    assert "re-dispatch" in na
    assert "spreadsheet_structure_detection" in na


def test_answerable_blocker_keeps_founder_next_action(tmp_path) -> None:
    receipt = _emit_cli(
        tmp_path,
        [["Investor", "Principal"], ["Lender", 250_000]],
        {
            "blocks": [
                {
                    "block_type": "notes_block",  # on-contract; missing interest_rate_type is founder-answerable
                    "sheet": "S",
                    "cell_range": "A2:B2",
                    "column_role_map": {"A": "investor_name", "B": "principal"},
                }
            ]
        },
    )
    assert receipt["ok"] is False
    na = receipt["next_action"].lower()
    # purely founder-answerable → keep the --answer guidance, do NOT tell it to re-dispatch
    assert "--answer" in na
    assert "re-dispatch" not in na


def test_offcontract_role_next_action_says_redispatch(tmp_path) -> None:
    # Off-contract ROLE (not block_type): the block_type is valid (founders_block) but a
    # column-role value is off-contract. This must hit the "off-contract" reason discriminator,
    # NOT the field=="block_type" one — so it isolates that branch.
    receipt = _emit_cli(
        tmp_path,
        [["Name", "Shares"], ["Alice", 1_000_000]],
        {
            "blocks": [
                {
                    "block_type": "founders_block",
                    "sheet": "S",
                    "cell_range": "A2:B2",
                    "column_role_map": {"A": "holder_name", "B": "bogus_role"},
                }
            ]
        },
    )
    assert receipt["ok"] is False
    # no block_type-field blocker here → only the reason clause can trigger re-dispatch
    assert all(b["field"] != "block_type" for b in receipt["blockers"])
    assert any("off-contract" in str(b.get("reason", "")) for b in receipt["blockers"])
    na = receipt["next_action"].lower()
    assert "re-dispatch" in na and "spreadsheet_structure_detection" in na


def test_mixed_offcontract_and_answerable_next_action(tmp_path) -> None:
    # An off-contract block AND a founder-answerable blocker in the same run: steer to
    # re-dispatch (off-contract wins) but still surface the --answer path for the rest.
    receipt = _emit_cli(
        tmp_path,
        [["Exit", "Proceeds"], [1_000_000, 500_000], ["Investor", "Principal"], ["Lender", 250_000]],
        {
            "blocks": [
                {  # off-contract block_type
                    "block_type": "waterfall_scenarios",
                    "sheet": "S",
                    "cell_range": "A2:B2",
                    "column_role_map": {"A": "exit", "B": "proceeds"},
                },
                {  # on-contract but missing required interest_rate_type → founder-answerable
                    "block_type": "notes_block",
                    "sheet": "S",
                    "cell_range": "A4:B4",
                    "column_role_map": {"A": "investor_name", "B": "principal"},
                },
            ]
        },
    )
    assert receipt["ok"] is False
    fields = {b["field"] for b in receipt["blockers"]}
    assert "block_type" in fields  # the off-contract block
    assert "interest_rate_type" in fields  # the founder-answerable one
    na = receipt["next_action"].lower()
    assert "re-dispatch" in na  # off-contract steers the whole message to re-dispatch
    assert "--answer" in na  # ...while still pointing at the answerable path for the rest


# --- Part 3: drift guard — the contract vocabulary must stay surfaced in the
# sub-agent system prompt (the hand-maintained copy the sub-agent actually reads).


def test_role_map_vocab_present_in_agent_prompt() -> None:
    """Every closed-contract term — block_type KEYS, role KEYS (what the sub-agent emits,
    NOT role values or enum values), ignore types, hard-block keys — must appear word-bounded
    in agents/cap-table.md. Guards against adding a term to freeform-role-map.json without
    surfacing it in the SPREADSHEET_STRUCTURE_DETECTION prompt."""
    rm = fm._load_role_map()
    terms: set[str] = set(rm["block_types"].keys())
    for bt in rm["block_types"].values():
        terms |= set(bt["roles"].keys())  # role KEYS only
    terms |= set(rm["ignore_block_types"])
    terms |= set(rm["hard_block_block_types"].keys())

    agent_md = os.path.join(_REPO, "founder-skills", "agents", "cap-table.md")
    with open(agent_md, encoding="utf-8") as f:
        text = f.read()
    missing = [t for t in sorted(terms) if not re.search(r"\b" + re.escape(t) + r"\b", text)]
    assert not missing, f"closed-contract terms absent from agents/cap-table.md: {missing}"
