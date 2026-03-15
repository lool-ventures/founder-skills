#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for financial-model-review scripts.

Run:  pytest founder-skills/tests/test_financial_model_review.py -v

All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")
FIXTURES_DIR = os.path.join(SCRIPT_DIR, "fixtures")


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    script_dir: str | None = None,
) -> tuple[int, dict[str, Any], str]:
    """Run a script and return (exit_code, parsed_json, stderr)."""
    base = script_dir or FMR_SCRIPTS_DIR
    cmd = [sys.executable, os.path.join(base, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    return result.returncode, data, result.stderr


def run_script_raw(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    script_dir: str | None = None,
) -> tuple[int, str, str]:
    """Run a script and return (exit_code, raw_stdout, stderr)."""
    base = script_dir or FMR_SCRIPTS_DIR
    cmd = [sys.executable, os.path.join(base, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# --- extract_model.py tests ---


def test_extract_model_csv() -> None:
    """CSV extraction produces structured JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Month,Revenue,Expenses\n2025-01,50000,80000\n2025-02,55000,82000\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert "sheets" in data
    assert len(data["sheets"]) == 1  # CSV = single sheet


def test_extract_model_xlsx() -> None:
    """XLSX extraction produces structured JSON with multiple sheets."""
    import pytest

    fixture = os.path.join(FIXTURES_DIR, "sample_model.xlsx")
    if not os.path.exists(fixture):
        pytest.skip("sample_model.xlsx fixture not yet created")
    rc, data, stderr = run_script("extract_model.py", ["--file", fixture, "--pretty"])
    assert rc == 0
    assert data is not None
    assert "sheets" in data
    assert len(data["sheets"]) >= 2  # sample has multiple sheets


def test_extract_model_stdin_passthrough() -> None:
    """Stdin JSON passes through as model_data."""
    input_data = json.dumps({"sheets": [{"name": "Manual", "headers": ["A"], "rows": [[1]]}]})
    rc, data, stderr = run_script("extract_model.py", ["--stdin"], stdin_data=input_data)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["name"] == "Manual"


def test_extract_model_nonexistent_file() -> None:
    rc, data, stderr = run_script("extract_model.py", ["--file", "/tmp/nonexistent.xlsx"])
    assert rc == 1


def test_extract_model_output_flag() -> None:
    """The -o flag writes to file instead of stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Month,Revenue\n2025-01,50000\n")
        f.flush()
        csv_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as out:
        out_path = out.name
    rc, data, stderr = run_script("extract_model.py", ["--file", csv_path, "-o", out_path])
    os.unlink(csv_path)
    assert rc == 0
    assert data is not None and data["ok"] is True
    with open(out_path) as fh:
        written = json.load(fh)
    os.unlink(out_path)
    assert "sheets" in written


# --- periodicity detection tests ---


def test_extract_periodicity_quarterly_csv() -> None:
    """CSV with Q1/Q2/Q3/Q4 headers detects quarterly periodicity."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,Q1 2024,Q2 2024,Q3 2024,Q4 2024\nRevenue,100,200,300,400\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "quarterly"
    assert data["periodicity_summary"] == "quarterly"


def test_extract_periodicity_monthly_csv() -> None:
    """CSV with month name headers detects monthly periodicity."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,Jan 2024,Feb 2024,Mar 2024\nRevenue,100,200,300\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "monthly"
    assert data["periodicity_summary"] == "monthly"


def test_extract_periodicity_iso_monthly_csv() -> None:
    """CSV with YYYY-MM headers detects monthly periodicity."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,2024-01,2024-02,2024-03\nRevenue,100,200,300\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "monthly"


def test_extract_periodicity_variant_1q24() -> None:
    """CSV with 1Q24-style headers detects quarterly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,1Q24,2Q24,3Q24,4Q24\nRevenue,100,200,300,400\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "quarterly"


def test_extract_periodicity_month_range_quarterly() -> None:
    """CSV with Jan-Mar style headers detects quarterly, not monthly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,Jan-Mar 2024,Apr-Jun 2024,Jul-Sep 2024,Oct-Dec 2024\nRevenue,100,200,300,400\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "quarterly"


def test_extract_periodicity_annual_csv() -> None:
    """CSV with FY headers detects annual periodicity."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Line Item,FY2024,FY2025,FY2026\nRevenue,1000,2000,3000\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "annual"


def test_extract_periodicity_unknown_csv() -> None:
    """CSV with non-time-series headers returns unknown."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Category,Amount,Notes\nSalaries,50000,Monthly\n")
        f.flush()
        rc, data, stderr = run_script("extract_model.py", ["--file", f.name, "--pretty"])
    os.unlink(f.name)
    assert rc == 0
    assert data is not None
    assert data["sheets"][0]["periodicity"] == "unknown"
    assert data["periodicity_summary"] == "unknown"


def test_extract_periodicity_stdin_no_periodicity() -> None:
    """Stdin passthrough does not add periodicity (caller's responsibility)."""
    input_data = json.dumps({"sheets": [{"name": "Manual", "headers": ["A"], "rows": [[1]]}]})
    rc, data, stderr = run_script("extract_model.py", ["--stdin"], stdin_data=input_data)
    assert rc == 0
    assert data is not None
    # Stdin passes through as-is — no periodicity added
    assert "periodicity_summary" not in data


def test_extract_periodicity_mixed_xlsx() -> None:
    """XLSX with quarterly and monthly sheets returns mixed summary."""
    from openpyxl import Workbook

    wb = Workbook()
    # Sheet 1: quarterly headers
    ws1 = wb.active
    assert ws1 is not None
    ws1.title = "P&L"
    ws1.append(["Line Item", "Q1 2024", "Q2 2024", "Q3 2024", "Q4 2024"])
    ws1.append(["Revenue", 100000, 120000, 140000, 160000])
    # Sheet 2: monthly headers
    ws2 = wb.create_sheet("Revenue")
    ws2.append(["Metric", "Jan 2024", "Feb 2024", "Mar 2024"])
    ws2.append(["MRR", 30000, 32000, 34000])

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        wb.save(f.name)
        tmp_path = f.name
    try:
        rc, data, stderr = run_script("extract_model.py", ["--file", tmp_path, "--pretty"])
        assert rc == 0
        assert data is not None
        periodicities = {s["name"]: s["periodicity"] for s in data["sheets"]}
        assert periodicities["P&L"] == "quarterly"
        assert periodicities["Revenue"] == "monthly"
        assert data["periodicity_summary"] == "mixed"
    finally:
        os.unlink(tmp_path)


# --- Checklist IDs and helpers ---

_CHECKLIST_IDS: list[str] = [
    # Structure & Presentation
    "STRUCT_01",
    "STRUCT_02",
    "STRUCT_03",
    "STRUCT_04",
    "STRUCT_05",
    "STRUCT_06",
    "STRUCT_07",
    "STRUCT_08",
    "STRUCT_09",
    # Revenue & Unit Economics
    "UNIT_10",
    "UNIT_11",
    "UNIT_12",
    "UNIT_13",
    "UNIT_14",
    "UNIT_15",
    "UNIT_16",
    "UNIT_17",
    "UNIT_18",
    "UNIT_19",
    # Expenses, Cash & Runway
    "CASH_20",
    "CASH_21",
    "CASH_22",
    "CASH_23",
    "CASH_24",
    "CASH_25",
    "CASH_26",
    "CASH_27",
    "CASH_28",
    "CASH_29",
    "CASH_30",
    "CASH_31",
    "CASH_32",
    # Metrics & Efficiency
    "METRIC_33",
    "METRIC_34",
    "METRIC_35",
    # Fundraising Bridge
    "BRIDGE_36",
    "BRIDGE_37",
    "BRIDGE_38",
    # Sector-Specific
    "SECTOR_39",
    "SECTOR_40",
    "SECTOR_41",
    "SECTOR_42",
    "SECTOR_43",
    "SECTOR_44",
    # Overall
    "OVERALL_45",
    "OVERALL_46",
]


def _make_checklist_items(
    overrides: dict[str, dict[str, str]] | None = None,
    exclude: set[str] | None = None,
) -> list[dict[str, str]]:
    """Build a full 46-item checklist payload. Override specific items by ID."""
    overrides = overrides or {}
    exclude = exclude or set()
    items = []
    for item_id in _CHECKLIST_IDS:
        if item_id in exclude:
            continue
        base = {"id": item_id, "status": "pass", "evidence": f"Evidence for {item_id}"}
        if item_id in overrides:
            base.update(overrides[item_id])
        items.append(base)
    return items


# --- checklist.py tests ---


def test_checklist_all_pass() -> None:
    items = _make_checklist_items()
    payload = json.dumps({"items": items})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["overall_status"] == "strong"
    assert data["summary"]["score_pct"] == 100.0
    assert data["summary"]["total"] == 46


def test_checklist_some_fail() -> None:
    items = _make_checklist_items(
        overrides={
            "STRUCT_01": {"status": "fail", "evidence": "Assumptions buried in formulas"},
            "UNIT_11": {"status": "fail", "evidence": "Zero churn assumed"},
            "CASH_23": {"status": "warn", "evidence": "Runway math unclear"},
        }
    )
    payload = json.dumps({"items": items})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["fail"] == 2
    assert data["summary"]["warn"] == 1
    assert data["summary"]["score_pct"] < 100.0


def test_checklist_gating_unknown_sector_warns() -> None:
    """When sector_type is missing, a warning about sector_type is emitted on stderr."""
    company = {"stage": "seed", "geography": "us", "sector": "fintech", "traits": []}
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert "sector_type" in stderr.lower()


def test_checklist_not_applicable_pre_scored() -> None:
    """Backward compat: without company profile, agent-supplied not_applicable is trusted."""
    items = _make_checklist_items(
        overrides={
            "CASH_28": {"status": "not_applicable", "evidence": "Single-currency company"},
            "CASH_29": {"status": "not_applicable", "evidence": "Single entity"},
            "CASH_30": {"status": "not_applicable", "evidence": "Not Israel-based"},
            "CASH_31": {"status": "not_applicable", "evidence": "No IIA grants"},
            "CASH_32": {"status": "not_applicable", "evidence": "No VAT issues"},
            "SECTOR_39": {"status": "not_applicable", "evidence": "Not a marketplace"},
            "SECTOR_41": {"status": "not_applicable", "evidence": "Not hardware"},
            "SECTOR_42": {"status": "not_applicable", "evidence": "Not usage-based"},
            "SECTOR_43": {"status": "not_applicable", "evidence": "Not consumer"},
            "SECTOR_44": {"status": "not_applicable", "evidence": "No deferred revenue"},
        }
    )
    payload = json.dumps({"items": items})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["not_applicable"] == 10
    assert data["summary"]["score_pct"] == 100.0


def test_checklist_gating_normalizes_geography() -> None:
    """Free-form geography values are normalized; sector gates use sector_type."""
    company = {
        "stage": "seed",
        "geography": "United States",
        "sector": "B2B SaaS",
        "sector_type": "saas",
        "traits": [],
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    cash30 = next(i for i in data["items"] if i["id"] == "CASH_30")
    assert cash30["status"] == "not_applicable"


def test_checklist_missing_sector_type_warns() -> None:
    """When sector_type is missing, a warning is emitted on stderr."""
    company = {"stage": "seed", "geography": "us", "sector": "saas", "traits": []}
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert "sector_type" in stderr.lower()


def test_checklist_gating_us_saas_company() -> None:
    """With company profile, script auto-gates items whose gates don't match."""
    company = {"stage": "seed", "geography": "us", "sector": "saas", "sector_type": "saas", "traits": []}
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    gated_ids = {
        "CASH_28",
        "CASH_29",
        "CASH_30",
        "CASH_31",
        "CASH_32",
        "SECTOR_39",
        "SECTOR_41",
        "SECTOR_42",
        "SECTOR_43",
        "SECTOR_44",
        "OVERALL_46",
    }
    for item in data["items"]:
        if item["id"] in gated_ids:
            assert item["status"] == "not_applicable", f"{item['id']} should be auto-gated but was {item['status']}"
            assert "Auto-gated" in item["evidence"]
    s40 = next(i for i in data["items"] if i["id"] == "SECTOR_40")
    assert s40["status"] == "not_applicable"
    assert data["summary"]["not_applicable"] >= 11


def test_checklist_gating_israel_ai_company() -> None:
    """Israel AI company: Israel items apply, AI items apply, marketplace/hardware don't."""
    company = {
        "stage": "seed",
        "geography": "israel",
        "sector": "ai-native",
        "sector_type": "ai-native",
        "traits": ["multi-currency"],
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for iid in ("CASH_30", "CASH_31", "CASH_32"):
        item = next(i for i in data["items"] if i["id"] == iid)
        assert item["status"] != "not_applicable", f"{iid} should be applicable for Israel"
    cash28 = next(i for i in data["items"] if i["id"] == "CASH_28")
    assert cash28["status"] != "not_applicable"
    s40 = next(i for i in data["items"] if i["id"] == "SECTOR_40")
    assert s40["status"] != "not_applicable"
    for iid in ("SECTOR_39", "SECTOR_41", "SECTOR_43"):
        item = next(i for i in data["items"] if i["id"] == iid)
        assert item["status"] == "not_applicable", f"{iid} should be gated"


def test_checklist_ai_cost_gate_broadened() -> None:
    """SECTOR_40 should be applicable when expenses.cogs has inference_costs, even for non-AI sector."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
    }
    inputs_with_ai_costs = {
        "expenses": {
            "cogs": {"hosting": 5000, "inference_costs": 3000},
        },
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company, "inputs": inputs_with_ai_costs})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s40 = next(it for it in data["items"] if it["id"] == "SECTOR_40")
    assert s40["status"] != "not_applicable", "SECTOR_40 should be applicable when AI costs present"


def test_checklist_ai_cost_gate_no_ai_costs() -> None:
    """SECTOR_40 should remain not_applicable for non-AI sector without AI cost keys."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
    }
    inputs_without_ai_costs = {
        "expenses": {
            "cogs": {"hosting": 5000, "support": 2000},
        },
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company, "inputs": inputs_without_ai_costs})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s40 = next(it for it in data["items"] if it["id"] == "SECTOR_40")
    assert s40["status"] == "not_applicable", "SECTOR_40 should stay gated without AI costs"


def test_checklist_ai_powered_trait_triggers_sector_40() -> None:
    """ai-powered trait triggers SECTOR_40 for SaaS companies."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "Cybersecurity SaaS",
        "revenue_model_type": "saas-sales-led",
        "traits": ["ai-powered"],
        # no sector_type — derives "saas" from revenue_model_type
        # no AI cogs in inputs — trait alone should trigger SECTOR_40
    }
    items = _make_checklist_items(overrides={"SECTOR_40": {"status": "fail", "evidence": "No AI costs shown"}})
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s40 = next(i for i in data["items"] if i["id"] == "SECTOR_40")
    assert s40["status"] == "fail", "SECTOR_40 should not be auto-gated when ai-powered trait present"


def _assert_validation_errors(data: dict | None, *fragments: str) -> None:
    """Assert data has validation.status == 'invalid' and errors contain all fragments."""
    assert data is not None, "expected JSON output with validation errors"
    assert data["validation"]["status"] == "invalid"
    joined = " ".join(data["validation"]["errors"]).lower()
    for frag in fragments:
        assert frag.lower() in joined, f"expected '{frag}' in validation errors: {data['validation']['errors']}"


def test_checklist_missing_items() -> None:
    items = _make_checklist_items(exclude={"STRUCT_01", "UNIT_10"})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "STRUCT_01")


def test_checklist_invalid_status() -> None:
    items = _make_checklist_items(overrides={"STRUCT_01": {"status": "maybe"}})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "invalid")


def test_checklist_by_category() -> None:
    items = _make_checklist_items()
    payload = json.dumps({"items": items})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "by_category" in data["summary"]
    cats = data["summary"]["by_category"]
    assert "Structure & Presentation" in cats
    assert "Revenue & Unit Economics" in cats
    assert cats["Structure & Presentation"]["pass"] == 9


def test_checklist_overall_status_thresholds() -> None:
    """Score >= 85 = strong, >= 70 = solid, >= 50 = needs_work, < 50 = major_revision."""
    fail_ids = {f"UNIT_{i}": {"status": "fail", "evidence": "test"} for i in range(10, 19)}
    items = _make_checklist_items(overrides=fail_ids)
    payload = json.dumps({"items": items})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["summary"]["overall_status"] == "solid"


def test_checklist_deck_format_gates_structural_items() -> None:
    """When model_format is 'deck', structural and expense items auto-gate to not_applicable."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
        "model_format": "deck",
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    # All 9 STRUCT items should be not_applicable
    for i in range(1, 10):
        item = next(it for it in data["items"] if it["id"] == f"STRUCT_0{i}")
        assert item["status"] == "not_applicable", f"STRUCT_0{i} should be gated for deck format"
    # CASH_20-27 (non-geo-gated expense items) should be not_applicable
    for i in range(20, 28):
        item = next(it for it in data["items"] if it["id"] == f"CASH_{i}")
        assert item["status"] == "not_applicable", f"CASH_{i} should be gated for deck format"
    # Revenue/Unit Economics items should still be applicable
    unit10 = next(it for it in data["items"] if it["id"] == "UNIT_10")
    assert unit10["status"] != "not_applicable"


def test_checklist_deck_format_sub_scores() -> None:
    """Deck format produces business_quality_pct and model_maturity_pct in summary."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
        "model_format": "deck",
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    summary = data["summary"]
    assert "business_quality_pct" in summary
    assert "model_maturity_pct" in summary
    # business_quality_pct should be 100% (all remaining items pass)
    assert summary["business_quality_pct"] == 100.0
    # model_maturity_pct should be None (all structural items are N/A)
    assert summary["model_maturity_pct"] is None


def test_checklist_spreadsheet_format_no_extra_gating() -> None:
    """When model_format is 'spreadsheet', no extra gating occurs."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
        "model_format": "spreadsheet",
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    struct01 = next(it for it in data["items"] if it["id"] == "STRUCT_01")
    assert struct01["status"] == "pass"


def test_checklist_no_model_format_backward_compat() -> None:
    """When model_format is absent, no extra gating occurs (backward compat)."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "saas",
        "sector_type": "saas",
        "traits": [],
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    struct01 = next(it for it in data["items"] if it["id"] == "STRUCT_01")
    assert struct01["status"] == "pass"
    # Sub-scores present with same value as score_pct
    summary = data["summary"]
    assert "business_quality_pct" in summary
    assert "model_maturity_pct" in summary


# --- Valid inputs fixture ---

_VALID_INPUTS: dict[str, Any] = {
    "company": {
        "company_name": "TestCo",
        "slug": "testco",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "US",
        "revenue_model_type": "saas-sales-led",
    },
    "revenue": {
        "arr": {"value": 600000, "as_of": "2025-12"},
        "mrr": {"value": 50000, "as_of": "2025-12"},
        "growth_rate_monthly": 0.08,
        "churn_monthly": 0.03,
        "nrr": 1.05,
        "grr": 0.95,
    },
    "expenses": {
        "headcount": [
            {"role": "Engineer", "count": 5, "salary_annual": 150000, "geography": "US", "burden_pct": 0.30},
            {"role": "Sales", "count": 2, "salary_annual": 120000, "geography": "US", "burden_pct": 0.25},
        ],
        "cogs": {"hosting": 5000, "support": 2000},
    },
    "cash": {
        "current_balance": 2000000,
        "debt": 0,
        "balance_date": "2025-12",
        "monthly_net_burn": 80000,
    },
    "unit_economics": {
        "cac": {
            "total": 1500,
            "components": {"ad_spend": 500, "sales_salaries": 800, "tools": 200},
            "fully_loaded": True,
        },
        "ltv": {
            "value": 6000,
            "method": "formula",
            "inputs": {"arpu_monthly": 500, "gross_margin": 0.75, "churn_monthly": 0.03},
            "observed_vs_assumed": "assumed",
        },
        "payback_months": 10,
        "gross_margin": 0.75,
    },
    "bridge": {
        "raise_amount": 5000000,
        "runway_target_months": 24,
    },
}


# --- unit_economics.py tests ---


def test_unit_economics_basic() -> None:
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "metrics" in data
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    assert "cac" in metrics_by_name
    assert "ltv" in metrics_by_name
    assert "gross_margin" in metrics_by_name
    assert "ltv_cac_ratio" in metrics_by_name


def test_unit_economics_burn_multiple() -> None:
    inputs = {**_VALID_INPUTS}
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    if "burn_multiple" in metrics_by_name:
        assert metrics_by_name["burn_multiple"]["value"] is not None


def test_unit_economics_missing_optional_fields() -> None:
    """Should handle missing optional fields gracefully."""
    minimal = {
        "company": {
            "company_name": "MinCo",
            "slug": "minco",
            "stage": "pre-seed",
            "sector": "B2B SaaS",
            "geography": "US",
            "revenue_model_type": "saas-plg",
        },
        "revenue": {"mrr": {"value": 5000, "as_of": "2025-12"}},
    }
    payload = json.dumps(minimal)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    assert "gross_margin" not in metrics_by_name or metrics_by_name["gross_margin"].get("value") is None


def test_unit_economics_ratings() -> None:
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    valid_ratings = {"strong", "acceptable", "warning", "fail", "not_rated", "contextual", "not_applicable"}
    for metric in data["metrics"]:
        if metric.get("value") is not None:
            assert metric["rating"] in valid_ratings


def test_unit_economics_burn_multiple_computed_wins() -> None:
    """When compute inputs are present and values are close, computed burn_multiple is used."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Computed: 80000 / (50000 * 0.08) = 20.0x; provided 18.0 is within 2x ratio → computed wins
    inputs["unit_economics"]["burn_multiple"] = 18.0
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    assert "burn_multiple" in metrics_by_name
    # Computed value (20.0) should be used, not the reported 18.0
    assert metrics_by_name["burn_multiple"]["value"] != 18.0
    # burn_multiple_lifetime should NOT exist
    assert "burn_multiple_lifetime" not in metrics_by_name


def test_unit_economics_burn_multiple_fallback() -> None:
    """When compute inputs are missing, reported burn_multiple is used as fallback."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Remove compute inputs: monthly_burn, mrr, growth_rate
    inputs["cash"].pop("monthly_net_burn", None)
    inputs["revenue"].pop("mrr", None)
    inputs["revenue"].pop("growth_rate_monthly", None)
    # Provide reported burn_multiple
    inputs["unit_economics"]["burn_multiple"] = 0.66
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    assert "burn_multiple" in metrics_by_name
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] == 0.66
    assert bm["rating"] == "not_rated"
    assert "reported" in bm["evidence"].lower()
    # burn_multiple_lifetime should NOT exist
    assert "burn_multiple_lifetime" not in metrics_by_name


def test_unit_economics_rule_of_40_below_1m_arr() -> None:
    """Rule of 40 should be not_applicable when ARR < $1M."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 130000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] == "not_applicable"
    assert "not meaningful" in r40["evidence"].lower() or "$1M" in r40["evidence"]


def test_unit_economics_rule_of_40_above_1m_arr() -> None:
    """Rule of 40 should use operating margin (burn-derived) when ARR >= $5M."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # ARR intentionally inflated above MRR*12 to test R40 $5M+ benchmark path
    inputs["revenue"]["arr"]["value"] = 6000000
    inputs["cash"]["monthly_net_burn"] = 30000  # op_margin = -30K/50K = -60%
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] != "not_applicable"
    assert r40["rating"] != "contextual"  # operating margin → benchmark-rated
    assert r40["value"] is not None
    # growth ≈ 151.8%, op_margin = -60%, R40 ≈ 91.8
    assert 85 < r40["value"] < 100
    assert "operating margin" in r40["evidence"].lower()


def test_unit_economics_rule_of_40_negative() -> None:
    """R40 can be negative when burn far exceeds revenue."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # ARR intentionally inflated above MRR*12 to test R40 $5M+ benchmark path
    inputs["revenue"]["arr"]["value"] = 6000000
    inputs["cash"]["monthly_net_burn"] = 80000  # op_margin = -80K/50K = -160%
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["value"] is not None
    assert r40["value"] < 0  # growth ≈ 151.8% + (-160%) ≈ -8.2
    assert "operating margin" in r40["evidence"].lower()


def test_unit_economics_rule_of_40_gross_margin_fallback() -> None:
    """R40 should fall back to gross margin (contextual) when burn data missing."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 1200000
    del inputs["cash"]["monthly_net_burn"]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["value"] is not None
    assert r40["rating"] == "contextual"
    assert "gross margin" in r40["evidence"].lower()
    assert "overstates" in r40["evidence"].lower()


def test_unit_economics_rule_of_40_operating_margin_preferred() -> None:
    """When both burn+MRR and gross margin are available, operating margin wins."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # ARR intentionally inflated above MRR*12 to test R40 $5M+ benchmark path
    inputs["revenue"]["arr"]["value"] = 6000000
    inputs["cash"]["monthly_net_burn"] = 30000
    inputs["unit_economics"]["gross_margin"] = 0.75  # should be ignored for R40
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert "operating margin" in r40["evidence"].lower()
    assert "gross margin" not in r40["evidence"].lower()


def test_unit_economics_rule_of_40_sign_error_fallback() -> None:
    """Negative monthly_net_burn (wrong sign) should trigger gross margin fallback."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 1200000
    inputs["cash"]["monthly_net_burn"] = -80000  # wrong sign → op_margin > 100%
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] == "contextual"
    assert "gross margin" in r40["evidence"].lower()
    assert "sign error" in stderr.lower() or "exceeds 100%" in stderr.lower()


def test_unit_economics_rule_of_40_sign_error_no_gm() -> None:
    """Sign error + no gross margin → not_rated (can't compute R40 at all)."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 1200000
    inputs["cash"]["monthly_net_burn"] = -80000
    del inputs["unit_economics"]["gross_margin"]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["value"] is None
    assert r40["rating"] == "not_rated"
    assert "implausible" in r40["evidence"].lower()
    assert "exceeds 100%" in stderr.lower()


def test_unit_economics_ltv_zero_churn_capped() -> None:
    """LTV with 0% churn should be capped at 60-month horizon with a label."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["churn_monthly"] = 0.0
    inputs["unit_economics"]["ltv"] = {
        "value": 38235,
        "method": "formula",
        "inputs": {"arpu_monthly": 500, "gross_margin": 0.75, "churn_monthly": 0.0},
        "observed_vs_assumed": "assumed",
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    ltv = metrics_by_name["ltv"]
    assert ltv["value"] is not None
    assert "capped" in ltv["evidence"].lower() or "5-year" in ltv["evidence"].lower()


def test_unit_economics_ltv_zero_churn_missing_arpu() -> None:
    """LTV with 0% churn but missing arpu should be not_rated with warning evidence."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["unit_economics"]["ltv"] = {
        "value": 1840000,
        "method": "formula",
        "inputs": {"churn_monthly": 0.0, "gross_margin": 0.75},
        "observed_vs_assumed": "assumed",
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    ltv = metrics_by_name["ltv"]
    assert ltv["rating"] == "not_rated"
    assert "could not apply 5-year cap" in ltv["evidence"].lower()
    assert "missing arpu" in ltv["evidence"].lower()
    # Structured warning
    warnings = data.get("warnings", [])
    codes = [w["code"] for w in warnings]
    assert "LTV_CAP_MISSING_INPUTS" in codes


def test_unit_economics_ltv_zero_churn_missing_gm() -> None:
    """LTV with 0% churn but missing gross_margin should be not_rated with warning evidence."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["unit_economics"]["ltv"] = {
        "value": 1840000,
        "method": "formula",
        "inputs": {"arpu_monthly": 500, "churn_monthly": 0.0},
        "observed_vs_assumed": "assumed",
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    ltv = metrics_by_name["ltv"]
    assert ltv["rating"] == "not_rated"
    assert "could not apply 5-year cap" in ltv["evidence"].lower()
    # Structured warning
    warnings = data.get("warnings", [])
    codes = [w["code"] for w in warnings]
    assert "LTV_CAP_MISSING_INPUTS" in codes


def test_unit_economics_ltv_zero_churn_with_inputs_no_warning() -> None:
    """LTV with 0% churn and both arpu+gm present should NOT emit LTV_CAP_MISSING_INPUTS."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["unit_economics"]["ltv"]["inputs"]["churn_monthly"] = 0.0
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    warnings = data.get("warnings", [])
    codes = [w["code"] for w in warnings]
    assert "LTV_CAP_MISSING_INPUTS" not in codes


def test_unit_economics_ltv_cac_contextual_when_assumed() -> None:
    """LTV/CAC from assumed inputs should be rated 'contextual', not hard pass/fail."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    if "ltv_cac_ratio" in metrics_by_name:
        assert metrics_by_name["ltv_cac_ratio"]["rating"] == "contextual"


def test_unit_economics_output_flag() -> None:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as out:
        out_path = out.name
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["-o", out_path], stdin_data=payload)
    assert rc == 0
    assert data is not None and data["ok"] is True
    with open(out_path) as f:
        written = json.load(f)
    os.unlink(out_path)
    assert "metrics" in written


def test_unit_economics_confidence_qualifier() -> None:
    """data_confidence: 'estimated' appends qualifier to rated metric evidence."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["data_confidence"] = "estimated"
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    rated_metrics = [m for m in data["metrics"] if m["rating"] not in ("not_rated", "not_applicable")]
    assert len(rated_metrics) > 0, "Expected some rated metrics"
    for m in rated_metrics:
        assert "estimated" in m["evidence"].lower(), (
            f"Metric '{m['name']}' evidence should contain estimated qualifier: {m['evidence']}"
        )
        assert m.get("confidence") == "estimated", f"Metric '{m['name']}' should have confidence='estimated'"


def test_unit_economics_confidence_no_rating_change() -> None:
    """Ratings are identical regardless of data_confidence."""
    payload_exact = json.dumps(_VALID_INPUTS)
    rc1, data_exact, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=payload_exact)
    assert rc1 == 0 and data_exact is not None

    inputs_est = json.loads(json.dumps(_VALID_INPUTS))
    inputs_est["company"]["data_confidence"] = "estimated"
    payload_est = json.dumps(inputs_est)
    rc2, data_est, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=payload_est)
    assert rc2 == 0 and data_est is not None

    ratings_exact = {m["name"]: m["rating"] for m in data_exact["metrics"]}
    ratings_est = {m["name"]: m["rating"] for m in data_est["metrics"]}
    for name in ratings_exact:
        assert ratings_exact[name] == ratings_est.get(name, ratings_exact[name]), (
            f"Rating for '{name}' changed: exact={ratings_exact[name]} vs estimated={ratings_est.get(name)}"
        )


def test_unit_economics_confidence_exact_no_qualifier() -> None:
    """data_confidence: 'exact' (default) adds no qualifier or confidence field."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for m in data["metrics"]:
        assert "estimated" not in m["evidence"].lower()
        assert "confidence" not in m


# --- runway.py tests ---


def test_runway_basic() -> None:
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "scenarios" in data
    assert len(data["scenarios"]) >= 3  # base, slow, crisis


def test_runway_auto_generates_scenarios() -> None:
    """When inputs don't include scenarios, script generates slow and crisis."""
    inputs = {k: v for k, v in _VALID_INPUTS.items() if k != "scenarios"}
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    scenario_names = {s["name"] for s in data["scenarios"]}
    assert "base" in scenario_names
    assert "slow" in scenario_names
    assert "crisis" in scenario_names


def test_runway_decision_points() -> None:
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for scenario in data["scenarios"]:
        assert "runway_months" in scenario
        assert "cash_out_date" in scenario or scenario.get("runway_months") is None
        assert "decision_point" in scenario


def test_runway_default_alive() -> None:
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for scenario in data["scenarios"]:
        assert "default_alive" in scenario
        assert isinstance(scenario["default_alive"], bool)


def test_runway_custom_scenarios() -> None:
    inputs = {
        **_VALID_INPUTS,
        "scenarios": {
            "base": {"growth_rate": 0.08, "burn_change": 0},
            "optimistic": {"growth_rate": 0.12, "burn_change": -0.05},
        },
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    scenario_names = {s["name"] for s in data["scenarios"]}
    assert "optimistic" in scenario_names


def test_runway_iia_grant_disbursement() -> None:
    """IIA grants add cash to projections during disbursement period."""
    inputs_with_grant = {
        **_VALID_INPUTS,
        "cash": {
            **_VALID_INPUTS["cash"],
            "grants": {
                "iia_approved": 120000,
                "iia_disbursement_months": 12,
                "iia_start_month": 1,
            },
        },
    }
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(inputs_with_grant))
    assert rc == 0
    assert data is not None
    base_with = next(s for s in data["scenarios"] if s["name"] == "base")
    # Run without grants to compare
    rc2, data2, _ = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(_VALID_INPUTS))
    assert rc2 == 0
    assert data2 is not None
    base_without = next(s for s in data2["scenarios"] if s["name"] == "base")
    # Grant should extend runway or improve cash at same month
    if base_with["runway_months"] is not None and base_without["runway_months"] is not None:
        assert base_with["runway_months"] >= base_without["runway_months"]
    # Limitations should mention IIA
    assert any("IIA" in lim for lim in data["limitations"])


def test_runway_fx_adjustment() -> None:
    """FX adjustment affects ILS-denominated expenses in scenarios."""
    inputs_with_fx = {
        **_VALID_INPUTS,
        "israel_specific": {
            "fx_rate_ils_usd": 3.65,
            "ils_expense_fraction": 0.6,
        },
    }
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(inputs_with_fx))
    assert rc == 0
    assert data is not None
    # Auto-generated crisis scenario should have fx_adjustment > 0
    crisis = next(s for s in data["scenarios"] if s["name"] == "crisis")
    assert crisis["fx_adjustment"] == 0.10
    # Base should have 0
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    assert base["fx_adjustment"] == 0.0
    # Limitations should mention FX
    assert any("FX" in lim for lim in data["limitations"])


def test_runway_post_raise() -> None:
    """Post-raise computation shows extended runway."""
    inputs_with_raise = {
        **_VALID_INPUTS,
        "cash": {
            **_VALID_INPUTS["cash"],
            "fundraising": {"target_raise": 5000000, "expected_close": "2026-06"},
        },
        "bridge": {"raise_amount": 5000000, "runway_target_months": 24},
    }
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(inputs_with_raise))
    assert rc == 0
    assert data is not None
    assert "post_raise" in data
    assert data["post_raise"] is not None
    assert data["post_raise"]["raise_amount"] == 5000000
    assert data["post_raise"]["new_cash"] > _VALID_INPUTS["cash"]["current_balance"]
    # Post-raise runway should be longer than pre-raise
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    if base["runway_months"] is not None and data["post_raise"]["new_runway_months"] is not None:
        assert data["post_raise"]["new_runway_months"] > base["runway_months"]


def test_runway_no_post_raise_without_fundraising() -> None:
    """post_raise is None when no fundraising data is provided."""
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(_VALID_INPUTS))
    assert rc == 0
    assert data is not None
    assert data["post_raise"] is None


def test_runway_threshold_scenario() -> None:
    """Runway output includes a 'threshold' scenario with minimum viable growth rate."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    scenario_names = {s["name"] for s in data["scenarios"]}
    assert "threshold" in scenario_names
    threshold = next(s for s in data["scenarios"] if s["name"] == "threshold")
    assert "growth_rate" in threshold
    assert threshold["growth_rate"] is not None
    assert threshold["growth_rate"] >= 0
    assert threshold["growth_rate"] <= _VALID_INPUTS["revenue"]["growth_rate_monthly"]


def test_runway_threshold_narrative() -> None:
    """Risk assessment includes minimum viable growth language."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    risk = data["risk_assessment"].lower()
    assert "at least" in risk or "minimum" in risk or "need" in risk


def test_runway_threshold_already_dead() -> None:
    """When even base scenario is not default-alive, threshold still present."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["cash"]["monthly_net_burn"] = 500000
    inputs["cash"]["current_balance"] = 1000000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    threshold = next((s for s in data["scenarios"] if s["name"] == "threshold"), None)
    assert threshold is not None


def test_runway_missing_cash_data() -> None:
    """Should handle missing cash fields gracefully."""
    minimal = {
        "company": {
            "company_name": "MinCo",
            "slug": "minco",
            "stage": "pre-seed",
            "sector": "B2B SaaS",
            "geography": "US",
            "revenue_model_type": "saas-plg",
        },
    }
    payload = json.dumps(minimal)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None


def test_runway_burn_change_one_time_step_up() -> None:
    """burn_change should be a one-time step-up, not monthly compounding."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Use the slow scenario which has burn_change: 0.10
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    slow = next(s for s in data["scenarios"] if s["name"] == "slow")
    projections = slow["monthly_projections"]
    assert len(projections) >= 3
    # After the one-time step-up, expenses should be flat across all months
    month1_expenses = projections[0]["expenses"]
    month2_expenses = projections[1]["expenses"]
    month3_expenses = projections[2]["expenses"]
    # With one-time step-up: month1 == month2 == month3 (no compounding)
    # Allow tiny FP tolerance
    assert abs(month2_expenses - month1_expenses) < 0.01, (
        f"Expenses should be flat after step-up: month1={month1_expenses}, month2={month2_expenses}"
    )
    assert abs(month3_expenses - month1_expenses) < 0.01, (
        f"Expenses should be flat after step-up: month1={month1_expenses}, month3={month3_expenses}"
    )


def test_runway_growth_deceleration() -> None:
    """Effective growth rate should decay over time."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    projections = base["monthly_projections"]
    assert len(projections) >= 6
    # Compute implied growth rates from revenue: g_t = (R_t / R_{t-1}) - 1
    # Month 1 revenue grows from revenue0; subsequent months from prior month
    growth_rates = []
    for i in range(1, min(len(projections), 12)):
        prev_rev = projections[i - 1]["revenue"]
        curr_rev = projections[i]["revenue"]
        if prev_rev > 0:
            growth_rates.append(curr_rev / prev_rev - 1)
    # Growth rates must strictly decrease (not just non-increasing).
    # Math: with MRR=50000, growth=8%, decay=3%, the implied rate drops ~0.24pp per month.
    # Revenue is rounded to 2 decimals, shifting implied rates by at most ~0.001pp.
    # The 0.1% relative tolerance has ~15x headroom over rounding noise.
    assert len(growth_rates) >= 2, "Need at least 2 implied growth rates"
    for i in range(1, len(growth_rates)):
        assert growth_rates[i] < growth_rates[i - 1] * 0.999, (
            f"Growth rate must strictly decay: month {i + 2} rate {growth_rates[i]:.6f} "
            f"not less than month {i + 1} rate {growth_rates[i - 1]:.6f}"
        )


def test_runway_decayed_trajectory_leq_constant() -> None:
    """Decayed revenue trajectory should be <= constant-rate trajectory after month 1."""
    # We compare the actual (decayed) revenue to what constant-rate would produce
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    projections = base["monthly_projections"]
    growth_rate = _VALID_INPUTS["revenue"]["growth_rate_monthly"]
    mrr = _VALID_INPUTS["revenue"]["mrr"]["value"]
    # Compute constant-rate trajectory
    constant_rev = mrr
    for i, p in enumerate(projections):
        constant_rev = constant_rev * (1 + growth_rate)
        # After month 2 (index 1+), decayed must be strictly less than constant.
        # Skip index 1 (month 2) where rounding may compress the small delta;
        # by month 3+ the cumulative gap is well above rounding noise.
        if i > 1:
            assert p["revenue"] < constant_rev - 1.0, (
                f"Month {i + 1}: decayed revenue {p['revenue']:.2f} should be strictly "
                f"less than constant-rate {constant_rev:.2f}"
            )


def test_runway_threshold_solver_with_decay() -> None:
    """Threshold solver should find a viable rate; with decay it must be higher than base rate
    would be without decay for a cash-tight scenario."""
    # Use tight cash so threshold rate is meaningfully above 0
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["cash"]["current_balance"] = 500000  # tight cash
    inputs["cash"]["monthly_net_burn"] = 80000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    threshold = next((s for s in data["scenarios"] if s["name"] == "threshold"), None)
    assert threshold is not None
    assert threshold["growth_rate"] is not None
    # With decay, the solver needs a higher initial rate to compensate.
    # The threshold rate should be > 0 for this cash-tight scenario.
    assert threshold["growth_rate"] > 0.001, (
        f"Threshold rate {threshold['growth_rate']:.4f} should be meaningfully positive "
        f"for a cash-tight scenario with growth decay"
    )


def test_runway_passes_confidence_through() -> None:
    """data_confidence from company appears in runway output."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["data_confidence"] = "estimated"
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("data_confidence") == "estimated"


def test_runway_no_confidence_when_exact() -> None:
    """data_confidence defaults to 'exact' and is omitted from output."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    # 'exact' is the default; field should not be in output
    assert "data_confidence" not in data


# --- compose_report.py helpers ---

_VALID_CHECKLIST: dict[str, Any] = {
    "items": [
        {
            "id": item_id,
            "category": "Test",
            "label": f"Label for {item_id}",
            "status": "pass",
            "evidence": f"Evidence for {item_id}",
            "notes": None,
        }
        for item_id in _CHECKLIST_IDS
    ],
    "summary": {
        "total": 46,
        "pass": 46,
        "fail": 0,
        "warn": 0,
        "not_applicable": 0,
        "score_pct": 100.0,
        "overall_status": "strong",
        "by_category": {},
        "failed_items": [],
        "warned_items": [],
    },
}

_VALID_UNIT_ECONOMICS: dict[str, Any] = {
    "metrics": [
        {
            "name": "cac",
            "value": 1500,
            "rating": "acceptable",
            "evidence": "Fully loaded CAC",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "ltv",
            "value": 6000,
            "rating": "strong",
            "evidence": "Formula-based",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
        {
            "name": "gross_margin",
            "value": 0.75,
            "rating": "strong",
            "evidence": "75% GM",
            "benchmark_source": "test",
            "benchmark_as_of": "2024",
        },
    ],
    "summary": {"computed": 3, "strong": 2, "acceptable": 1, "warning": 0, "fail": 0},
}

_VALID_RUNWAY: dict[str, Any] = {
    "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
    "baseline": {"net_cash": 2000000, "monthly_burn": 80000, "monthly_revenue": 50000},
    "scenarios": [
        {
            "name": "base",
            "runway_months": 25,
            "cash_out_date": "2028-01",
            "decision_point": "2027-01",
            "default_alive": True,
            "monthly_projections": [],
        },
        {
            "name": "slow",
            "runway_months": 18,
            "cash_out_date": "2027-06",
            "decision_point": "2026-06",
            "default_alive": False,
            "monthly_projections": [],
        },
        {
            "name": "crisis",
            "runway_months": 12,
            "cash_out_date": "2026-12",
            "decision_point": "2025-12",
            "default_alive": False,
            "monthly_projections": [],
        },
    ],
    "risk_assessment": "Adequate runway under base case.",
    "limitations": [],
    "warnings": [],
}


def _make_fmr_artifact_dir(artifacts: dict[str, Any]) -> str:
    d = tempfile.mkdtemp(prefix="test-compose-fmr-")
    for name, data in artifacts.items():
        path = os.path.join(d, name)
        with open(path, "w") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)
    return d


def _run_compose(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, dict | None, str]:
    args = ["--dir", artifact_dir, "--pretty"]
    if extra_args:
        args.extend(extra_args)
    return run_script("compose_report.py", args)


# --- compose_report.py tests ---


def test_compose_complete_set() -> None:
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "report_markdown" in data
    assert "validation" in data
    assert data["validation"]["status"] in ("clean", "warnings")


def test_compose_missing_required_artifact() -> None:
    """Missing required artifacts should exit 1."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 1
    assert "required artifacts missing" in stderr


def test_compose_missing_only_optional_artifact() -> None:
    """Missing model_data.json (optional) should succeed without high-severity warnings."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    # No high-severity warnings for missing optional
    missing_artifact_warnings = [w for w in data["validation"].get("warnings", []) if w["code"] == "MISSING_ARTIFACT"]
    assert not missing_artifact_warnings, "model_data.json is optional - should not trigger MISSING_ARTIFACT"


def test_compose_corrupt_artifact() -> None:
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": "not valid json{{{",
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes


def test_compose_strict_mode() -> None:
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": "corrupt",
        }
    )
    rc, data, stderr = _run_compose(d, extra_args=["--strict"])
    assert rc == 1


# --- Pipeline integration: feed realistic data through all scripts ---


def test_pipeline_extract_to_compose() -> None:
    """End-to-end: extract_model → checklist + unit_economics + runway → compose_report.

    This verifies schema compatibility across ALL five data-producing scripts.
    Each script's output must be consumable by downstream scripts without
    transformation.
    """
    # Step 0: Run extract_model on CSV fixture
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Month,Revenue,Expenses,Net\n2025-01,50000,80000,-30000\n2025-02,55000,82000,-27000\n")
        f.flush()
        csv_path = f.name
    rc_ex, extract_data, ex_stderr = run_script("extract_model.py", ["--file", csv_path, "--pretty"])
    os.unlink(csv_path)
    assert rc_ex == 0, f"extract_model.py failed: {ex_stderr}"
    assert extract_data is not None
    assert "sheets" in extract_data

    # Step 1: Build checklist items and run checklist.py
    checklist_input = {"items": _make_checklist_items()}
    rc_ck, checklist_data, _ = run_script("checklist.py", ["--pretty"], stdin_data=json.dumps(checklist_input))
    assert rc_ck == 0 and checklist_data is not None, "checklist.py failed"

    # Step 2: Run unit_economics on inputs
    rc_ue, ue_data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(_VALID_INPUTS))
    assert rc_ue == 0 and ue_data is not None, "unit_economics.py failed"

    # Step 3: Run runway on inputs
    rc_rw, runway_data, _ = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(_VALID_INPUTS))
    assert rc_rw == 0 and runway_data is not None, "runway.py failed"

    # Step 4: Feed all outputs to compose_report
    d = tempfile.mkdtemp(prefix="test-pipeline-")
    for name, data in [
        ("inputs.json", _VALID_INPUTS),
        ("model_data.json", extract_data),
        ("checklist.json", checklist_data),
        ("unit_economics.json", ue_data),
        ("runway.json", runway_data),
    ]:
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)

    rc_cr, report, stderr = _run_compose(d)
    assert rc_cr == 0, f"compose_report failed on pipeline output: {stderr}"
    assert report is not None
    assert "report_markdown" in report
    # No high-severity warnings = schemas are compatible
    if "warnings" in report.get("validation", {}):
        for w in report["validation"]["warnings"]:
            assert w.get("severity") != "high", f"Pipeline produced high-severity warning: {w}"


# --- Agent structural smoke test ---


def test_compose_deck_format_severity_downgrade() -> None:
    """CHECKLIST_FAILURES severity should be 'medium' when model_format is deck."""
    inputs_deck = json.loads(json.dumps(_VALID_INPUTS))
    inputs_deck["company"]["model_format"] = "deck"
    checklist_failing = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist_failing["summary"]["overall_status"] = "major_revision"
    checklist_failing["summary"]["fail"] = 23
    checklist_failing["summary"]["failed_items"] = [{"id": f"STRUCT_0{i}"} for i in range(1, 10)]
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_deck,
            "checklist.json": checklist_failing,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    checklist_warnings = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES"]
    for w in checklist_warnings:
        assert w["severity"] == "medium", "CHECKLIST_FAILURES should be medium for deck format"


def test_compose_model_completeness_section() -> None:
    """Deck format report includes Model Completeness section."""
    inputs_deck = json.loads(json.dumps(_VALID_INPUTS))
    inputs_deck["company"]["model_format"] = "deck"
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_deck,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "Model Completeness" in data["report_markdown"]


def test_compose_no_model_completeness_for_spreadsheet() -> None:
    """Spreadsheet format report should NOT include Model Completeness section."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "Model Completeness" not in data["report_markdown"]


def test_compose_infinite_runway_rendering() -> None:
    """When runway_months is None (default_alive), renders 'Infinite' not 'None months'."""
    runway_infinite = json.loads(json.dumps(_VALID_RUNWAY))
    # Set base scenario to infinite runway (default alive)
    runway_infinite["scenarios"][0]["runway_months"] = None
    runway_infinite["scenarios"][0]["cash_out_date"] = None
    runway_infinite["scenarios"][0]["decision_point"] = None
    runway_infinite["scenarios"][0]["default_alive"] = True
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": runway_infinite,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Should NOT contain "None months" anywhere in the report
    assert "None months" not in md, "Report should not render 'None months'"
    # Should contain the formatted infinite runway text
    assert "Infinite" in md or "profitability" in md.lower(), "Report should indicate infinite runway / profitability"


def test_compose_post_raise_in_report() -> None:
    """Post-raise data appears in runway section when present."""
    runway_with_post = json.loads(json.dumps(_VALID_RUNWAY))
    runway_with_post["post_raise"] = {
        "raise_amount": 5000000,
        "new_cash": 7000000,
        "new_runway_months": 48,
        "new_cash_out_date": "2029-12",
        "meets_target": True,
    }
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": runway_with_post,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Post-Raise" in md or "post_raise" in md.lower() or "$5" in md


# --- compose_report.py data confidence rendering tests ---


def test_compose_report_data_quality_line() -> None:
    """'Data Quality: Estimated' in executive summary when data_confidence != exact."""
    inputs_est = json.loads(json.dumps(_VALID_INPUTS))
    inputs_est["company"]["data_confidence"] = "estimated"
    inputs_est["company"]["model_format"] = "deck"
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_est,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Data Quality" in md
    assert "Estimated" in md


def test_compose_report_estimated_label() -> None:
    """Score label is 'Deck Financial Readiness' when estimated + model_maturity_pct is null."""
    inputs_est = json.loads(json.dumps(_VALID_INPUTS))
    inputs_est["company"]["data_confidence"] = "estimated"
    inputs_est["company"]["model_format"] = "deck"
    checklist_deck = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist_deck["summary"]["model_maturity_pct"] = None
    checklist_deck["summary"]["business_quality_pct"] = 100.0
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_est,
            "checklist.json": checklist_deck,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Deck Financial Readiness" in md or "business quality only" in md.lower()


def test_compose_report_exact_label() -> None:
    """Score label is 'Model Quality' when data_confidence is exact."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Model Quality" in md


def test_compose_report_unit_economics_estimated_header() -> None:
    """Unit economics section notes when metrics are based on estimated inputs."""
    inputs_est = json.loads(json.dumps(_VALID_INPUTS))
    inputs_est["company"]["data_confidence"] = "estimated"
    ue_est = json.loads(json.dumps(_VALID_UNIT_ECONOMICS))
    for m in ue_est["metrics"]:
        m["confidence"] = "estimated"
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_est,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": ue_est,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "estimated" in md.lower()


def test_compose_report_stale_artifact_mismatched_run_ids() -> None:
    """Mismatched run_id across artifacts triggers STALE_ARTIFACT warning."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {"run_id": "run-001"}
    checklist = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist["metadata"] = {"run_id": "run-001"}
    ue = json.loads(json.dumps(_VALID_UNIT_ECONOMICS))
    ue["metadata"] = {"run_id": "run-002"}  # stale!
    runway = json.loads(json.dumps(_VALID_RUNWAY))
    runway["metadata"] = {"run_id": "run-001"}
    d = _make_fmr_artifact_dir(
        {"inputs.json": inputs, "checklist.json": checklist, "unit_economics.json": ue, "runway.json": runway}
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" in codes


def test_compose_report_matching_run_ids_no_stale_warning() -> None:
    """Matching run_id across all artifacts produces no STALE_ARTIFACT warning."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {"run_id": "run-001"}
    checklist = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist["metadata"] = {"run_id": "run-001"}
    ue = json.loads(json.dumps(_VALID_UNIT_ECONOMICS))
    ue["metadata"] = {"run_id": "run-001"}
    runway = json.loads(json.dumps(_VALID_RUNWAY))
    runway["metadata"] = {"run_id": "run-001"}
    d = _make_fmr_artifact_dir(
        {"inputs.json": inputs, "checklist.json": checklist, "unit_economics.json": ue, "runway.json": runway}
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_report_no_run_ids_graceful() -> None:
    """No run_id in any artifact → graceful degradation, no STALE_ARTIFACT."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_report_surfaces_warning_overrides() -> None:
    """Warning overrides from inputs.json metadata appear in the report."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {
        "warning_overrides": [
            {
                "code": "BURN_MULTIPLE_SUSPECT",
                "reason": "Enterprise SaaS with lumpy deal flow; TTM burn multiple is 5.7x",
                "reviewed_by": "agent",
                "timestamp": "2026-03-05T17:30:00Z",
            }
        ]
    }
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "Acknowledged Warnings" in md
    assert "BURN_MULTIPLE_SUSPECT" in md
    assert "Enterprise SaaS with lumpy deal flow" in md
    # Agent overrides appear in "Acknowledged Warnings" without reviewer suffix
    assert "Burn Multiple Suspect" in md


def test_compose_report_no_overrides_no_section() -> None:
    """No warning overrides → no Acknowledged Warnings section."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "Acknowledged Warnings" not in data["report_markdown"]


# --- B1: sector_type derivation from revenue_model_type ---


def test_checklist_sector_type_derived_from_revenue_model_type() -> None:
    """sector_type auto-derived from revenue_model_type when not provided."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "AI infrastructure",
        "revenue_model_type": "ai-native",
        "traits": [],
        # no sector_type — should derive "ai-native" from revenue_model_type
    }
    items = _make_checklist_items(overrides={"SECTOR_40": {"status": "pass", "evidence": "Inference costs modeled"}})
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s40 = next(i for i in data["items"] if i["id"] == "SECTOR_40")
    assert s40["status"] == "pass", "SECTOR_40 should not be auto-gated when ai-native derived"


def test_checklist_sector_type_saas_no_sector_items() -> None:
    """SaaS revenue_model_type derives sector_type='saas', no sector items triggered."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "B2B SaaS",
        "revenue_model_type": "saas-sales-led",
        "traits": [],
        # no sector_type — should derive "saas"
    }
    items = _make_checklist_items()
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for item_id in ("SECTOR_39", "SECTOR_40", "SECTOR_41", "SECTOR_42", "SECTOR_43", "SECTOR_44"):
        item = next(i for i in data["items"] if i["id"] == item_id)
        assert item["status"] == "not_applicable", f"{item_id} should be gated for saas sector_type"


def test_checklist_annual_contracts_sector_gate() -> None:
    """annual-contracts revenue_model_type triggers SECTOR_44 (deferred revenue)."""
    company = {
        "stage": "seed",
        "geography": "us",
        "sector": "Enterprise SaaS",
        "revenue_model_type": "annual-contracts",
        "traits": [],
        # no sector_type — should derive "annual-contracts"
    }
    items = _make_checklist_items(overrides={"SECTOR_44": {"status": "pass", "evidence": "Deferred revenue tracked"}})
    payload = json.dumps({"items": items, "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s44 = next(i for i in data["items"] if i["id"] == "SECTOR_44")
    assert s44["status"] == "pass", "SECTOR_44 should not be auto-gated for annual-contracts"


# --- B2: --strict behavior for deck format ---


def test_compose_strict_mode_deck_format_checklist_failures_not_blocking() -> None:
    """--strict should not exit 1 for deck format CHECKLIST_FAILURES alone."""
    inputs_deck = json.loads(json.dumps(_VALID_INPUTS))
    inputs_deck["company"]["model_format"] = "deck"
    checklist_failing = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist_failing["summary"]["overall_status"] = "major_revision"
    checklist_failing["summary"]["fail"] = 23
    checklist_failing["summary"]["failed_items"] = [{"id": f"STRUCT_0{i}"} for i in range(1, 10)]
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_deck,
            "checklist.json": checklist_failing,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d, extra_args=["--strict"])
    assert rc == 0, f"--strict should not block on CHECKLIST_FAILURES for deck format: {stderr}"
    assert data is not None
    checklist_warnings = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_FAILURES"]
    assert len(checklist_warnings) > 0, "CHECKLIST_FAILURES warning should still be present"
    assert checklist_warnings[0]["severity"] == "medium", "Severity should remain medium"


def test_compose_strict_mode_medium_warnings_do_not_block() -> None:
    """--strict should NOT exit 1 for medium-severity warnings (findings, not data errors)."""
    # Create runway with inconsistent cash to trigger RUNWAY_INCONSISTENCY (medium)
    runway_inconsistent = json.loads(json.dumps(_VALID_RUNWAY))
    runway_inconsistent["baseline"]["net_cash"] = 500000  # differs >10% from inputs cash 2M
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": runway_inconsistent,
        }
    )
    rc, data, stderr = _run_compose(d, extra_args=["--strict"])
    assert rc == 0, "--strict should not block on medium-severity warnings like RUNWAY_INCONSISTENCY"
    assert data is not None
    # But the warning should still be present in the output
    warnings = data["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "RUNWAY_INCONSISTENCY" in codes


def test_compose_validation_includes_model_format() -> None:
    """Validation result includes model_format for --strict context."""
    inputs_deck = json.loads(json.dumps(_VALID_INPUTS))
    inputs_deck["company"]["model_format"] = "deck"
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": inputs_deck,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["validation"]["model_format"] == "deck"


def test_compose_validation_model_format_default_spreadsheet() -> None:
    """Validation result defaults model_format to spreadsheet."""
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert data["validation"]["model_format"] == "spreadsheet"


# --- B3: burn multiple ARR floor ---


def test_unit_economics_burn_multiple_below_500k_arr() -> None:
    """Burn multiple not applicable below $500K ARR."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 130000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["rating"] == "not_applicable"
    assert "$500K" in bm["evidence"] or "not meaningful" in bm["evidence"].lower()


def test_unit_economics_burn_multiple_above_500k_arr() -> None:
    """Burn multiple computed normally above $500K ARR."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 600000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["rating"] != "not_applicable"
    assert bm["value"] is not None


def test_unit_economics_burn_multiple_fallback_below_500k_arr() -> None:
    """Reported burn multiple also gated by ARR floor."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 130000
    # Remove compute inputs so fallback path is used
    inputs["cash"].pop("monthly_net_burn", None)
    inputs["revenue"].pop("mrr", None)
    inputs["revenue"].pop("growth_rate_monthly", None)
    # Provide reported burn_multiple
    inputs["unit_economics"]["burn_multiple"] = 2.5
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["rating"] == "not_applicable", "ARR floor should gate even the fallback path"
    assert "$500K" in bm["evidence"] or "not meaningful" in bm["evidence"].lower()


# --- New tests: FMR postmortem fixes ---


def test_unit_economics_annual_contracts_saas() -> None:
    """annual-contracts model type should be treated as SaaS."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = "annual-contracts"
    inputs["revenue"]["arr"]["value"] = 1200000  # above R40 $1M floor
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    # SaaS-only metrics should be computed, not not_applicable
    assert metrics_by_name["magic_number"]["rating"] != "not_applicable"
    assert metrics_by_name["rule_of_40"]["rating"] != "not_applicable"


def test_unit_economics_rule_of_40_contextual_band_1m_5m() -> None:
    """R40 should be contextual between $1M and $5M ARR with operating margin."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 3000000
    inputs["cash"]["monthly_net_burn"] = 30000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] == "contextual"
    assert "not benchmark-compared below $5M ARR" in r40["evidence"]


def test_unit_economics_rule_of_40_above_5m_benchmarked() -> None:
    """R40 above $5M ARR with operating margin should be benchmark-rated."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 6000000
    inputs["cash"]["monthly_net_burn"] = 30000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] not in ("contextual", "not_applicable", "not_rated")
    assert "benchmark" in r40["evidence"].lower() or "strong" in r40["evidence"].lower()


def test_unit_economics_rule_of_40_hyper_growth_above_5m() -> None:
    """R40 hyper-growth should still be contextual even above $5M ARR."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 6000000
    inputs["revenue"]["growth_rate_monthly"] = 0.15  # annualized ~435%
    inputs["cash"]["monthly_net_burn"] = 30000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] == "contextual"
    assert "hyper" in r40["evidence"].lower()


def test_unit_economics_burn_multiple_hyper_growth_contextual() -> None:
    """Burn multiple should be contextual when annualized growth > 200%."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["growth_rate_monthly"] = 0.15  # annualized ~435%
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["rating"] == "contextual"
    assert "hyper-growth" in bm["evidence"].lower()


def test_unit_economics_burn_multiple_seed_vs_series_a_thresholds() -> None:
    """Seed burn_multiple thresholds (2.0/2.5/3.0) differ from series-a (1.5/2.0/2.5)."""
    # A burn_mult of 1.8 should be strong for seed but acceptable for series-a
    for stage, expected_rating in [("seed", "strong"), ("series-a", "acceptable")]:
        inputs = json.loads(json.dumps(_VALID_INPUTS))
        inputs["company"]["stage"] = stage
        # Engineer BM to ~1.8x: burn=80K, net_new_arr = MRR*growth*12 = 50K*0.08*12 = 48K
        # burn / (net_new_arr/12) = 80K / 4K = 20.0 — too high
        # Set growth higher: 0.20 → net_new_arr/12 = 50K*0.20 = 10K, burn_mult = 80K/10K = 8
        # Set burn = 15000, growth = 0.08 → net_new_arr/12 = 4K, burn_mult = 3.75 — hmm
        # Use: burn=8000, growth=0.08 → 8000/4000 = 2.0
        inputs["cash"]["monthly_net_burn"] = 8000
        inputs["revenue"]["growth_rate_monthly"] = 0.08
        payload = json.dumps(inputs)
        rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
        assert rc == 0
        assert data is not None
        metrics_by_name = {m["name"]: m for m in data["metrics"]}
        bm = metrics_by_name["burn_multiple"]
        assert bm["value"] == 2.0
        assert bm["rating"] == expected_rating, (
            f"Stage {stage}: burn_mult 2.0 expected {expected_rating}, got {bm['rating']}"
        )


def test_unit_economics_burn_multiple_ttm_monthly_arr() -> None:
    """12+ monthly entries with arr field → TTM path used."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Build 12 monthly entries with ARR growing from 400K to 1M
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "total": 33333 + i * 5000, "arr": 400000 + i * 50000}
        for i, m in enumerate(range(1, 13))
    ]
    # net_new_arr = 950000 - 400000 = 550000
    # burn = 80000/mo → annual burn = 960000
    # burn_mult = 960000 / 550000 = 1.75
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] == 1.75, f"Expected TTM burn multiple 1.75, got {bm['value']}"
    assert "TTM actual" in bm["evidence"]


def test_unit_economics_burn_multiple_ttm_monthly_total_only() -> None:
    """12+ monthly entries with only total (no arr) → total*12 approximation."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Build 12 monthly entries with total growing from 30K to 80K (no arr field)
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "total": 30000 + i * (50000 / 11)} for i, m in enumerate(range(1, 13))
    ]
    # latest total ≈ 80000 → arr approx = 960000
    # earliest total = 30000 → arr approx = 360000
    # net_new_arr = 960000 - 360000 = 600000
    # burn = 80000/mo → annual burn = 960000
    # burn_mult = 960000 / 600000 = 1.6
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] is not None
    assert "TTM actual" in bm["evidence"]


def test_unit_economics_burn_multiple_quarterly_yoy() -> None:
    """4+ quarterly entries → YoY quarterly path used."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # No monthly entries — force quarterly path
    inputs["revenue"].pop("monthly", None)
    inputs["revenue"]["quarterly"] = [
        {"quarter": "2025-Q1", "total": 100000, "arr": 400000},
        {"quarter": "2025-Q2", "total": 125000, "arr": 500000},
        {"quarter": "2025-Q3", "total": 150000, "arr": 600000},
        {"quarter": "2025-Q4", "total": 200000, "arr": 800000},
    ]
    # net_new_arr = 800000 - 400000 = 400000
    # burn = 80000/mo → annual burn = 960000
    # burn_mult = 960000 / 400000 = 2.4
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] == 2.4, f"Expected quarterly burn multiple 2.4, got {bm['value']}"
    assert "YoY (quarterly) actual" in bm["evidence"]


def test_unit_economics_burn_multiple_growth_rate_fallback() -> None:
    """<12 monthly + <4 quarterly → growth-rate fallback."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Only 3 monthly entries — not enough for TTM
    inputs["revenue"]["monthly"] = [{"month": f"2025-{m:02d}", "total": 50000} for m in range(10, 13)]
    # Only 2 quarterly entries — not enough for YoY
    inputs["revenue"]["quarterly"] = [
        {"quarter": "2025-Q3", "total": 150000, "arr": 600000},
        {"quarter": "2025-Q4", "total": 200000, "arr": 800000},
    ]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] is not None
    # Growth-rate fallback doesn't say "TTM" or "YoY"
    assert "TTM" not in bm["evidence"]
    assert "YoY" not in bm["evidence"]


def test_unit_economics_burn_multiple_ttm_13_months_full_window() -> None:
    """13 monthly entries → true 12-month lookback (index -13)."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # 13 entries: month 0 (arr=400K) through month 12 (arr=1M)
    # With 13 entries, lookback is -13 → index 0 → arr=400K
    # net_new_arr = 1000000 - 400000 = 600000
    # burn = 80K/mo → annual = 960K → burn_mult = 960K / 600K = 1.6
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}" if m <= 12 else f"2026-{m - 12:02d}", "arr": 400000 + i * 50000}
        for i, m in enumerate(range(0, 13))
    ]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] == 1.6, f"Expected 1.6, got {bm['value']}"
    assert "TTM actual" in bm["evidence"]


def test_unit_economics_burn_multiple_quarterly_5_entries_full_yoy() -> None:
    """5 quarterly entries → true 4-quarter YoY lookback (index -5)."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"].pop("monthly", None)
    # 5 entries: Q1 (arr=300K) through Q5 (arr=900K)
    # With 5 entries, lookback is -5 → index 0 → arr=300K
    # net_new_arr = 900000 - 300000 = 600000
    # burn = 80K/mo → annual = 960K → burn_mult = 960K / 600K = 1.6
    inputs["revenue"]["quarterly"] = [
        {"quarter": f"2024-Q{q}", "arr": 300000 + i * 150000} for i, q in enumerate([1, 2, 3, 4])
    ] + [{"quarter": "2025-Q1", "arr": 900000}]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert bm["value"] == 1.6, f"Expected 1.6, got {bm['value']}"
    assert "YoY (quarterly) actual" in bm["evidence"]


def test_unit_economics_burn_multiple_divergence_warning() -> None:
    """When TTM and growth-rate burn multiples diverge >2x, emit BURN_MULTIPLE_DIVERGENCE warning."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Monthly time-series with flat ARR (net new ARR = 0 from growth, but big jump in ARR)
    # TTM: arr grows from 200K to 800K → net_new_arr = 600K, burn_mult = (80K*12)/600K = 1.6x
    # Growth-rate: MRR=50K, growth=0.02 → net_new_arr = 50K*0.02*12 = 12K, burn_mult = 80K/1K = 80x
    inputs["revenue"]["growth_rate_monthly"] = 0.02  # low stated growth
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "arr": 200000 + i * (600000 / 11)} for i, m in enumerate(range(1, 13))
    ]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    # Should use TTM path
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    bm = metrics_by_name["burn_multiple"]
    assert "TTM actual" in bm["evidence"]
    # Should have divergence warning
    warnings = data.get("warnings", [])
    codes = [w["code"] for w in warnings]
    assert "BURN_MULTIPLE_DIVERGENCE" in codes, f"Expected divergence warning, got: {warnings}"


def test_unit_economics_burn_multiple_no_divergence_warning() -> None:
    """When TTM and growth-rate burn multiples are close, no BURN_MULTIPLE_DIVERGENCE."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    # Linear ARR growth of ~4K/mo over 12 months → net_new_arr ≈ 44K
    # growth_rate=0.08, MRR=50K → growth-rate net_new_arr = 50K*0.08*12 = 48K
    # TTM BM ≈ 21.8x, GR BM ≈ 20.0x → ratio ~1.09 (< 2x threshold)
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "total": 50000 + i * 333, "arr": 600000 + i * 4000}
        for i, m in enumerate(range(1, 13))
    ]
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    warnings = data.get("warnings", [])
    codes = [w["code"] for w in warnings]
    assert "BURN_MULTIPLE_DIVERGENCE" not in codes


def test_unit_economics_ai_gross_margin_seed_vs_series_a() -> None:
    """AI gross margin adjustment: -5pt for seed, -10pt for series-a."""
    for stage, expected_adj in [("seed", 0.05), ("series-a", 0.10)]:
        inputs = json.loads(json.dumps(_VALID_INPUTS))
        inputs["company"]["stage"] = stage
        inputs["company"]["sector"] = "ai-native"
        inputs["unit_economics"]["gross_margin"] = 0.70
        payload = json.dumps(inputs)
        rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
        assert rc == 0
        assert data is not None
        metrics_by_name = {m["name"]: m for m in data["metrics"]}
        gm = metrics_by_name["gross_margin"]
        assert f"{expected_adj:.0%} discount" in gm["evidence"]


def test_unit_economics_benchmark_nested_object() -> None:
    """Benchmark-rated metrics should include a nested benchmark object."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    # Gross margin should have benchmark
    gm = metrics_by_name["gross_margin"]
    assert "benchmark" in gm, f"gross_margin should have benchmark nested object: {gm}"
    assert gm["benchmark"]["target"] is not None
    assert gm["benchmark"]["source"] != ""


def test_runway_arr_12_fallback() -> None:
    """When MRR is missing but ARR present, runway should use ARR/12."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    del inputs["revenue"]["mrr"]
    inputs["revenue"]["arr"]["value"] = 600000  # ARR/12 = 50K
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["baseline"]["monthly_revenue"] == 50000.0
    assert "ARR/12" in stderr or "ARR/12" in str(data.get("warnings", []))


def test_sector_alias_fintech_to_saas() -> None:
    """fintech should resolve to saas sector type."""
    shared_scripts = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")
    sys.path.insert(0, shared_scripts)
    try:
        from founder_context import _derive_sector_type  # type: ignore[import-not-found]

        assert _derive_sector_type("fintech") == "saas"
        assert _derive_sector_type("B2B fintech") == "saas"
        assert _derive_sector_type("cybersecurity") == "saas"
        assert _derive_sector_type("edtech") == "saas"
        assert _derive_sector_type("transactional fintech") == "transactional-fintech"
        assert _derive_sector_type("payment processing") == "transactional-fintech"
        assert _derive_sector_type("payments infrastructure") == "transactional-fintech"
    finally:
        sys.path.remove(shared_scripts)


# --- validate_inputs.py sanity check tests ---


def _make_inputs(
    stage: str = "series-a",
    mrr: float = 100_000,
    burn: float = 200_000,
    growth: float | None = 0.10,
) -> dict[str, Any]:
    """Build a minimal inputs.json for validate_inputs tests."""
    inputs: dict[str, Any] = {
        "company": {
            "company_name": "TestCo",
            "slug": "testco",
            "stage": stage,
            "sector": "SaaS",
            "geography": "US",
            "revenue_model_type": "saas-plg",
        },
        "revenue": {
            "mrr": {"value": mrr, "as_of": "2025-01"},
        },
        "cash": {
            "current_balance": 2_000_000,
            "balance_date": "2025-01",
            "monthly_net_burn": burn,
        },
    }
    if growth is not None:
        inputs["revenue"]["growth_rate_monthly"] = growth
    return inputs


def test_validate_burn_revenue_suspect_series_a() -> None:
    """Series A burn > 5x MRR triggers BURN_REVENUE_SUSPECT with critical flag."""
    inputs = _make_inputs(stage="series-a", mrr=100_000, burn=600_000)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    assert data["valid"] is True
    assert data["has_critical_warnings"] is True
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" in codes
    w = next(w for w in data["warnings"] if w["code"] == "BURN_REVENUE_SUSPECT")
    assert w["critical"] is True


def test_validate_burn_revenue_normal_no_warning() -> None:
    """Series A burn < 5x MRR does not trigger warning."""
    # burn=80K < 5*100K=500K → no BURN_REVENUE_SUSPECT
    # burn_multiple = (80K*12)/(100K*0.1*12) = 8x → no BURN_MULTIPLE_SUSPECT
    inputs = _make_inputs(stage="series-a", mrr=100_000, burn=80_000)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" not in codes
    assert data["has_critical_warnings"] is False


def test_validate_burn_revenue_seed_higher_threshold() -> None:
    """Seed stage uses 10x threshold — 8x burn should not trigger."""
    # burn=40K < 10*50K=500K → no BURN_REVENUE_SUSPECT
    # burn_multiple = (40K*12)/(50K*0.1*12) = 8x → no BURN_MULTIPLE_SUSPECT
    inputs = _make_inputs(stage="seed", mrr=50_000, burn=40_000)  # 0.8x
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" not in codes


def test_validate_burn_revenue_seed_above_threshold() -> None:
    """Seed stage burn > 10x MRR triggers warning."""
    inputs = _make_inputs(stage="seed", mrr=50_000, burn=600_000)  # 12x
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" in codes


def test_validate_burn_revenue_pre_seed_skipped() -> None:
    """Pre-seed stage skips burn-to-revenue check entirely."""
    inputs = _make_inputs(stage="pre-seed", mrr=1_000, burn=200_000)  # 200x
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" not in codes


def test_validate_burn_revenue_zero_mrr_no_trigger() -> None:
    """Zero MRR does not trigger burn-to-revenue check (pre-revenue guard)."""
    inputs = _make_inputs(stage="series-a", mrr=0, burn=500_000)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_REVENUE_SUSPECT" not in codes


def test_validate_burn_multiple_suspect() -> None:
    """Extreme burn multiple (> 10x) triggers BURN_MULTIPLE_SUSPECT."""
    # burn=1.44M, MRR=170K, growth=10% → net_new_ARR = 170K * 0.10 * 12 = 204K
    # burn_multiple = (1.44M * 12) / 204K ≈ 84x
    inputs = _make_inputs(stage="series-a", mrr=170_000, burn=1_440_000, growth=0.10)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_MULTIPLE_SUSPECT" in codes
    assert data["has_critical_warnings"] is True


def test_validate_burn_multiple_suspect_ttm_overrides_growth_rate() -> None:
    """Time-series burn multiple should prevent false positive from growth-rate shortcut."""
    # Growth-rate shortcut: burn=150K, MRR=50K, growth=2% → net_new_arr = 50K*0.02*12 = 12K
    # burn_multiple = (150K*12)/12K = 150x → would trigger BURN_MULTIPLE_SUSPECT
    # But TTM time-series: ARR grew from 400K to 1.4M → net_new_arr = 1M
    # burn_multiple = (150K*12)/1M = 1.8x → should NOT trigger
    inputs = _make_inputs(stage="series-a", mrr=50_000, burn=150_000, growth=0.02)
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "arr": 400000 + i * (1000000 / 11)} for i, m in enumerate(range(1, 13))
    ]
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_MULTIPLE_SUSPECT" not in codes, (
        "TTM time-series should prevent false positive from growth-rate shortcut"
    )


def test_validate_burn_multiple_no_growth_no_trigger() -> None:
    """Missing growth data does not trigger burn multiple check."""
    inputs = _make_inputs(stage="series-a", mrr=170_000, burn=1_440_000, growth=None)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "BURN_MULTIPLE_SUSPECT" not in codes


def test_validate_has_critical_warnings_false_when_clean() -> None:
    """Clean inputs produce has_critical_warnings: false."""
    # burn=80K < 5*100K → no BURN_REVENUE_SUSPECT
    # burn_multiple = (80K*12)/(100K*0.1*12) = 8x → no BURN_MULTIPLE_SUSPECT
    inputs = _make_inputs(stage="series-a", mrr=100_000, burn=80_000, growth=0.10)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    assert data["has_critical_warnings"] is False


def test_validate_warning_overrides_valid() -> None:
    """Valid warning_overrides pass structural validation."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {
        "warning_overrides": [
            {
                "code": "BURN_MULTIPLE_SUSPECT",
                "reason": "Enterprise SaaS with lumpy deal flow",
                "reviewed_by": "agent",
                "timestamp": "2026-03-05T17:30:00Z",
            }
        ]
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    errors = data.get("errors", [])
    override_errors = [e for e in errors if e["code"].startswith("OVERRIDE_")]
    assert override_errors == [], f"Valid overrides should not produce errors: {override_errors}"


def test_validate_warning_overrides_missing_keys() -> None:
    """warning_overrides entry missing required keys produces OVERRIDE_MISSING_KEYS."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {
        "warning_overrides": [{"code": "BURN_MULTIPLE_SUSPECT"}]  # missing reason, reviewed_by, timestamp
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    errors = data.get("errors", [])
    codes = [e["code"] for e in errors]
    assert "OVERRIDE_MISSING_KEYS" in codes


def test_validate_warning_overrides_invalid_reviewer() -> None:
    """warning_overrides entry with bad reviewed_by produces OVERRIDE_INVALID_REVIEWER."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {
        "warning_overrides": [
            {
                "code": "BURN_MULTIPLE_SUSPECT",
                "reason": "test",
                "reviewed_by": "nobody",
                "timestamp": "2026-03-05T17:30:00Z",
            }
        ]
    }
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    errors = data.get("errors", [])
    codes = [e["code"] for e in errors]
    assert "OVERRIDE_INVALID_REVIEWER" in codes


# --- validate_inputs.py override filtering tests (direct import) ---


def _import_validate() -> Any:
    """Import validate() directly from validate_inputs.py."""
    sys.path.insert(0, FMR_SCRIPTS_DIR)
    try:
        import validate_inputs  # type: ignore[import-not-found]

        return validate_inputs.validate
    finally:
        sys.path.remove(FMR_SCRIPTS_DIR)


def test_validate_founder_override_does_not_clear_critical() -> None:
    """Founder override is informational — does NOT clear has_critical_warnings."""
    validate = _import_validate()
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["growth_rate_monthly"] = 0.0
    inputs["revenue"]["mrr"] = {"value": 50000, "as_of": "2026-01"}
    inputs["revenue"]["customers"] = 100

    result = validate(inputs)
    assert result["has_critical_warnings"] is True

    # Founder override: still has_critical_warnings
    warning_field = next(w["field"] for w in result["warnings"] if w["code"] == "GROWTH_RATE_ZERO_SUSPECT")
    inputs.setdefault("metadata", {})["warning_overrides"] = [
        {
            "code": "GROWTH_RATE_ZERO_SUSPECT",
            "field": warning_field,
            "reason": "pivot phase",
            "reviewed_by": "founder",
            "timestamp": "2026-03-09T14:00:00Z",
        }
    ]
    result2 = validate(inputs)
    assert result2["has_critical_warnings"] is True  # founder override does NOT clear


def test_validate_agent_override_clears_critical() -> None:
    """Agent override clears has_critical_warnings."""
    validate = _import_validate()
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["growth_rate_monthly"] = 0.0
    inputs["revenue"]["mrr"] = {"value": 50000, "as_of": "2026-01"}
    inputs["revenue"]["customers"] = 100

    result = validate(inputs)
    assert result["has_critical_warnings"] is True

    warning_field = next(w["field"] for w in result["warnings"] if w["code"] == "GROWTH_RATE_ZERO_SUSPECT")
    inputs.setdefault("metadata", {})["warning_overrides"] = [
        {
            "code": "GROWTH_RATE_ZERO_SUSPECT",
            "field": warning_field,
            "reason": "pivot phase — confirmed by founder",
            "reviewed_by": "agent",
            "timestamp": "2026-03-09T14:00:00Z",
        }
    ]
    result2 = validate(inputs)
    assert result2["has_critical_warnings"] is False
    # Warning still in list, just not blocking
    assert any(w["code"] == "GROWTH_RATE_ZERO_SUSPECT" for w in result2["warnings"])


def test_validate_honors_legacy_overrides_without_field() -> None:
    """Override without field (legacy agent format) suppresses by code only."""
    validate = _import_validate()
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["growth_rate_monthly"] = 0.0
    inputs["revenue"]["mrr"] = {"value": 50000, "as_of": "2026-01"}
    inputs["revenue"]["customers"] = 100

    result = validate(inputs)
    assert result["has_critical_warnings"] is True

    # Legacy override: code only, no field
    inputs.setdefault("metadata", {})["warning_overrides"] = [
        {
            "code": "GROWTH_RATE_ZERO_SUSPECT",
            "reason": "pivot phase",
            "reviewed_by": "agent",
            "timestamp": "2026-03-09T14:00:00Z",
        }
    ]
    result2 = validate(inputs)
    assert result2["has_critical_warnings"] is False


def test_unit_economics_propagates_run_id() -> None:
    """unit_economics.py propagates metadata.run_id from input to output."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {"run_id": "test-run-001"}
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata", {}).get("run_id") == "test-run-001"


def test_unit_economics_no_run_id_no_metadata() -> None:
    """unit_economics.py without run_id in input produces no metadata in output."""
    payload = json.dumps(_VALID_INPUTS)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "metadata" not in data


def test_runway_propagates_run_id() -> None:
    """runway.py propagates metadata.run_id from input to output."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["metadata"] = {"run_id": "test-run-002"}
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata", {}).get("run_id") == "test-run-002"


def test_checklist_propagates_run_id() -> None:
    """checklist.py propagates metadata.run_id from input to output."""
    items = _make_checklist_items()
    payload = json.dumps(
        {
            "items": items,
            "company": {"stage": "seed", "geography": "us", "sector": "B2B SaaS"},
            "metadata": {"run_id": "test-run-003"},
        }
    )
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data.get("metadata", {}).get("run_id") == "test-run-003"


_CO = {
    "company_name": "TestCo",
    "slug": "testco",
    "stage": "seed",
    "sector": "SaaS",
    "geography": "US",
    "revenue_model_type": "saas-plg",
}


def test_validate_date_format_errors() -> None:
    """validate_inputs.py catches malformed YYYY-MM dates."""
    payload = json.dumps(
        {
            "company": _CO,
            "cash": {
                "current_balance": 100000,
                "monthly_net_burn": 10000,
                "balance_date": "not-a-month",
            },
            "revenue": {
                "mrr": {"value": 5000, "as_of": "2026-2"},
            },
        }
    )
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["valid"] is False
    error_fields = {e["field"] for e in data.get("errors", [])}
    assert "cash.balance_date" in error_fields
    assert "revenue.mrr.as_of" in error_fields


def test_validate_enum_errors() -> None:
    """validate_inputs.py catches invalid enum values."""
    payload = json.dumps(
        {
            "company": {**_CO, "stage": "unicorn"},
            "structure": {"formatting_quality": "fair"},
        }
    )
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["valid"] is False
    error_fields = {e["field"] for e in data.get("errors", [])}
    assert "company.stage" in error_fields
    assert "structure.formatting_quality" in error_fields


def test_validate_time_series_date_format() -> None:
    """validate_inputs.py catches malformed dates in time series arrays."""
    payload = json.dumps(
        {
            "company": _CO,
            "revenue": {
                "monthly": [
                    {"month": "2025-01", "actual": True, "total": 1000},
                    {"month": "Jan-2025", "actual": False, "total": 2000},
                ],
            },
        }
    )
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["valid"] is False
    assert any("Jan-2025" in e.get("message", "") for e in data.get("errors", []))


def test_validate_inputs_referenced_by_agent() -> None:
    """validate_inputs.py should exist on disk."""
    scripts_dir = os.path.join(SCRIPT_DIR, "..", "skills", "financial-model-review", "scripts")
    assert os.path.isfile(os.path.join(scripts_dir, "validate_inputs.py"))


# --- Agent structural smoke test ---


def test_agent_definition_references_valid_scripts() -> None:
    """All scripts referenced in agent workflow exist on disk."""
    agent_path = os.path.join(SCRIPT_DIR, "..", "agents", "financial-model-review.md")
    assert os.path.isfile(agent_path), "Agent definition not found"
    scripts_dir = os.path.join(SCRIPT_DIR, "..", "skills", "financial-model-review", "scripts")
    expected_scripts = [
        "extract_model.py",
        "checklist.py",
        "unit_economics.py",
        "runway.py",
        "compose_report.py",
        "visualize.py",
    ]
    for script in expected_scripts:
        assert os.path.isfile(os.path.join(scripts_dir, script)), f"Agent references {script} but it doesn't exist"
    # Verify SKILL.md exists
    skill_md = os.path.join(SCRIPT_DIR, "..", "skills", "financial-model-review", "SKILL.md")
    assert os.path.isfile(skill_md), "SKILL.md not found"


# --- ARPU field-name fallback tests ---


class TestValidateInputsArpuFallback:
    """validate_inputs.py must detect ARPU issues regardless of field name."""

    def _make_inputs_with_arpu(self, field_name: str, arpu_val: float) -> dict:
        """Build minimal inputs with ARPU under the given field name."""
        return {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "customers": 10},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {
                "ltv": {
                    "value": 6000,
                    "inputs": {field_name: arpu_val, "churn_monthly": 0.03, "gross_margin": 0.75},
                },
                "gross_margin": 0.75,
            },
        }

    def test_arpu_monthly_triggers_suspect(self) -> None:
        """ARPU_SUSPECT fires with canonical field name arpu_monthly."""
        inp = self._make_inputs_with_arpu("arpu_monthly", 60000)  # >= MRR
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "ARPU_SUSPECT" in codes

    def test_arpu_old_name_triggers_suspect(self) -> None:
        """ARPU_SUSPECT fires with old schema field name arpu."""
        inp = self._make_inputs_with_arpu("arpu", 60000)  # >= MRR
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "ARPU_SUSPECT" in codes

    def test_arpu_old_name_consistency_check(self) -> None:
        """ARPU_INCONSISTENT fires with old field name when ARPU*customers != MRR."""
        inp = self._make_inputs_with_arpu("arpu", 3000)  # 3000*10=30000 vs MRR 50000 → >20% gap
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "ARPU_INCONSISTENT" in codes

    def test_arpu_monthly_preferred_over_arpu(self) -> None:
        """When both arpu_monthly and arpu exist, arpu_monthly wins."""
        inp = self._make_inputs_with_arpu("arpu_monthly", 5000)
        inp["unit_economics"]["ltv"]["inputs"]["arpu"] = 60000  # old name, wrong value
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "ARPU_SUSPECT" not in codes  # 5000 < 50000 MRR, so no suspect


class TestValidateInputsArpuCritical:
    """ARPU_SUSPECT should be critical; CUSTOMERS_MISSING when LTV present but no customers."""

    def test_arpu_suspect_is_critical(self) -> None:
        """ARPU_SUSPECT should block at the stop-gate."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "customers": 10},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {
                "ltv": {"value": 6000, "inputs": {"arpu_monthly": 60000, "churn_monthly": 0.03, "gross_margin": 0.75}},
                "gross_margin": 0.75,
            },
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        suspect = [w for w in data["warnings"] if w["code"] == "ARPU_SUSPECT"]
        assert len(suspect) == 1
        assert suspect[0].get("critical") is True
        assert data["has_critical_warnings"] is True

    def test_customers_missing_with_ltv_at_seed(self) -> None:
        """CUSTOMERS_MISSING fires when LTV inputs present but revenue.customers absent."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {
                "ltv": {"value": 6000, "inputs": {"arpu_monthly": 5000, "churn_monthly": 0.03, "gross_margin": 0.75}},
                "gross_margin": 0.75,
            },
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CUSTOMERS_MISSING" in codes

    def test_customers_missing_not_at_preseed(self) -> None:
        """CUSTOMERS_MISSING should NOT fire at pre-seed."""
        inp = {
            "company": {"stage": "pre-seed"},
            "revenue": {"mrr": {"value": 5000}},
            "cash": {"monthly_net_burn": 20000},
            "unit_economics": {
                "ltv": {"value": 6000, "inputs": {"arpu_monthly": 5000}},
                "gross_margin": 0.75,
            },
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CUSTOMERS_MISSING" not in codes

    def test_customers_present_no_warning(self) -> None:
        """No CUSTOMERS_MISSING when revenue.customers is populated."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "customers": 10},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {
                "ltv": {"value": 6000, "inputs": {"arpu_monthly": 5000, "churn_monthly": 0.03, "gross_margin": 0.75}},
                "gross_margin": 0.75,
            },
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CUSTOMERS_MISSING" not in codes


class TestValidateInputsCashZero:
    """validate_inputs.py must flag $0 cash balance at seed+ as suspicious."""

    def test_zero_cash_at_series_a(self) -> None:
        """CASH_ZERO_SUSPECT fires as critical at series-a."""
        inp = {
            "company": {"stage": "series-a"},
            "revenue": {"mrr": {"value": 150000}},
            "cash": {"current_balance": 0, "monthly_net_burn": 500000},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        suspect = [w for w in data["warnings"] if w["code"] == "CASH_ZERO_SUSPECT"]
        assert len(suspect) == 1
        assert suspect[0].get("critical") is True
        assert data["has_critical_warnings"] is True

    def test_zero_cash_at_seed(self) -> None:
        """CASH_ZERO_SUSPECT fires at seed."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}},
            "cash": {"current_balance": 0, "monthly_net_burn": 80000},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CASH_ZERO_SUSPECT" in codes

    def test_zero_cash_at_preseed_no_warning(self) -> None:
        """CASH_ZERO_SUSPECT does NOT fire at pre-seed."""
        inp = {
            "company": {"stage": "pre-seed"},
            "revenue": {"mrr": {"value": 5000}},
            "cash": {"current_balance": 0, "monthly_net_burn": 20000},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CASH_ZERO_SUSPECT" not in codes

    def test_nonzero_cash_no_warning(self) -> None:
        """Normal cash balance produces no CASH_ZERO_SUSPECT."""
        inp = {
            "company": {"stage": "series-a"},
            "revenue": {"mrr": {"value": 150000}},
            "cash": {"current_balance": 5000000, "monthly_net_burn": 500000},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CASH_ZERO_SUSPECT" not in codes

    def test_null_cash_no_zero_warning(self) -> None:
        """Null cash triggers MISSING_CASH_BALANCE, not CASH_ZERO_SUSPECT."""
        inp = {
            "company": {"stage": "series-a"},
            "revenue": {"mrr": {"value": 150000}},
            "cash": {"monthly_net_burn": 500000},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "CASH_ZERO_SUSPECT" not in codes
        assert "MISSING_CASH_BALANCE" in codes


# --- ARPU/churn field-name fallback in unit_economics.py ---


class TestUnitEconomicsArpuFallback:
    """unit_economics.py LTV cap must work with both arpu and arpu_monthly."""

    def _make_inputs_zero_churn(self, arpu_field: str, arpu_val: float) -> dict:
        return {
            "company": {"stage": "seed", "sector": "B2B SaaS", "revenue_model_type": "saas-sales-led"},
            "revenue": {"mrr": {"value": 50000}, "arr": {"value": 600000}, "growth_rate_monthly": 0.08},
            "cash": {"current_balance": 2000000, "monthly_net_burn": 80000},
            "unit_economics": {
                "cac": {"total": 1500},
                "ltv": {
                    "value": 999999,
                    "inputs": {arpu_field: arpu_val, "churn_monthly": 0, "gross_margin": 0.75},
                },
                "gross_margin": 0.75,
            },
        }

    def test_zero_churn_cap_with_arpu_monthly(self) -> None:
        """60-month cap applies with canonical arpu_monthly."""
        inp = self._make_inputs_zero_churn("arpu_monthly", 500)
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        assert data is not None
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] == 500 * 0.75 * 60  # 22500

    def test_zero_churn_cap_with_arpu_old_name(self) -> None:
        """60-month cap applies with old schema field name arpu."""
        inp = self._make_inputs_zero_churn("arpu", 500)
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        assert data is not None
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] == 500 * 0.75 * 60  # 22500


# --- DERIVED_METRIC_REDUNDANT informational warning ---


class TestValidateInputsDerivedMetric:
    """validate_inputs.py warns when burn_multiple is provided alongside compute inputs."""

    def test_redundant_with_growth_inputs(self) -> None:
        """Warning fires when burn, mrr, and growth are all present."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "growth_rate_monthly": 0.08},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {"burn_multiple": 3.4, "gross_margin": 0.75},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "DERIVED_METRIC_REDUNDANT" in codes
        redundant = [w for w in data["warnings"] if w["code"] == "DERIVED_METRIC_REDUNDANT"]
        assert redundant[0].get("critical") is not True  # informational only

    def test_redundant_with_time_series(self) -> None:
        """Warning fires when monthly time-series has >= 12 entries."""
        monthly = [{"month": f"2024-{m:02d}", "actual": True, "total": 10000 + m * 1000} for m in range(1, 13)]
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "monthly": monthly},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {"burn_multiple": 3.4, "gross_margin": 0.75},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "DERIVED_METRIC_REDUNDANT" in codes

    def test_no_warning_when_fallback_needed(self) -> None:
        """No warning when compute inputs are missing (fallback is legitimate)."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}},  # no growth, no monthly
            "cash": {},  # no burn
            "unit_economics": {"burn_multiple": 3.4, "gross_margin": 0.75},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "DERIVED_METRIC_REDUNDANT" not in codes

    def test_no_warning_when_no_provided_bm(self) -> None:
        """No warning when burn_multiple is not provided."""
        inp = {
            "company": {"stage": "seed"},
            "revenue": {"mrr": {"value": 50000}, "growth_rate_monthly": 0.08},
            "cash": {"monthly_net_burn": 80000},
            "unit_economics": {"gross_margin": 0.75},
        }
        rc, data, _ = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        codes = [w["code"] for w in data["warnings"]]
        assert "DERIVED_METRIC_REDUNDANT" not in codes


class TestBurnMultipleProvidedPreference:
    """When growth-rate burn multiple diverges >2x from provided, prefer provided."""

    def _make_inputs(self, growth_rate: float, provided_bm: float | None = None) -> dict[str, Any]:
        inp: dict[str, Any] = {
            "company": {"stage": "series-a", "sector": "B2B SaaS", "revenue_model_type": "saas-sales-led"},
            "revenue": {"mrr": {"value": 153603}, "arr": {"value": 1843235}, "growth_rate_monthly": growth_rate},
            "cash": {"current_balance": 1500000, "monthly_net_burn": 561000},
            "unit_economics": {"gross_margin": 0.784},
        }
        if provided_bm is not None:
            inp["unit_economics"]["burn_multiple"] = provided_bm
        return inp

    def test_divergent_prefers_provided(self) -> None:
        """31x growth-rate vs 3.05x provided → use 3.05x, warn about divergence."""
        inp = self._make_inputs(0.118, provided_bm=3.05)
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        bm = next(m for m in data["metrics"] if m["name"] == "burn_multiple")
        assert bm["value"] == 3.05
        # Value goes through normal rating branches (sanity + benchmark)
        # Divergence detail is in the warning
        codes = [w["code"] for w in data.get("warnings", [])]
        assert "BURN_MULTIPLE_REPORTED_DIVERGENCE" in codes

    def test_close_values_uses_computed(self) -> None:
        """When growth-rate and provided are close, use computed."""
        inp = {
            "company": {"stage": "series-a", "sector": "B2B SaaS", "revenue_model_type": "saas-sales-led"},
            "revenue": {"mrr": {"value": 100000}, "arr": {"value": 1200000}, "growth_rate_monthly": 0.05},
            "cash": {"current_balance": 5000000, "monthly_net_burn": 50000},
            "unit_economics": {"gross_margin": 0.75, "burn_multiple": 9.5},
        }
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        bm = next(m for m in data["metrics"] if m["name"] == "burn_multiple")
        # Computed: 50000 / (100000*0.05) = 10x; provided 9.5; ratio 1.05 < 2 → use computed
        assert bm["value"] == 10.0

    def test_no_provided_uses_computed(self) -> None:
        """Without provided burn_multiple, always use computed (existing behavior)."""
        inp = self._make_inputs(0.118, provided_bm=None)
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        bm = next(m for m in data["metrics"] if m["name"] == "burn_multiple")
        # 561000 / (153603 * 0.118) = 30.95
        assert bm["value"] == 30.95

    def test_time_series_path_unaffected_by_divergence_check(self) -> None:
        """Time-series burn multiple path should not be affected by the growth-rate divergence check."""
        inp = self._make_inputs(0.118, provided_bm=3.05)
        # Add TTM revenue data to trigger time-series path
        inp["revenue"]["quarterly"] = [
            {"quarter": "Q1-2025", "arr": 400000},
            {"quarter": "Q2-2025", "arr": 420000},
            {"quarter": "Q3-2025", "arr": 450000},
            {"quarter": "Q4-2025", "arr": 480000},
        ]
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        bm = next(m for m in data["metrics"] if m["name"] == "burn_multiple")
        # Time-series path should be used, not the provided value
        assert bm["value"] != 3.05
        # Should NOT produce BURN_MULTIPLE_REPORTED_DIVERGENCE (that's growth-rate path only)
        codes = [w["code"] for w in data.get("warnings", [])]
        assert "BURN_MULTIPLE_REPORTED_DIVERGENCE" not in codes


class TestUnitEconomicsLtvSynthesis:
    """unit_economics.py synthesizes LTV when ltv.inputs missing but revenue has the data."""

    def _base_inputs(self) -> dict:
        return {
            "company": {"stage": "series-a", "sector": "B2B SaaS", "revenue_model_type": "saas-sales-led"},
            "revenue": {
                "mrr": {"value": 153603},
                "arr": {"value": 1843235},
                "growth_rate_monthly": 0.118,
                "customers": 45,
                "churn_monthly": 0.0067,
            },
            "cash": {"current_balance": 1500000, "monthly_net_burn": 561000},
            "unit_economics": {"gross_margin": 0.784},
        }

    def test_synthesizes_ltv_from_revenue(self) -> None:
        """LTV computed from revenue.customers + revenue.churn_monthly + gross_margin."""
        inp = self._base_inputs()
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        # arpu = 153603/45 = 3413.40, ltv = 3413.40 * 0.784 / 0.0067 ≈ 399,277.01
        expected_ltv = round(153603 / 45 * 0.784 / 0.0067, 2)
        assert ltv["value"] == expected_ltv
        assert "synthesized" in ltv["evidence"].lower() or "computed" in ltv["evidence"].lower()

    def test_no_synthesis_when_ltv_inputs_present(self) -> None:
        """Don't synthesize when ltv.inputs already has data."""
        inp = self._base_inputs()
        inp["unit_economics"]["ltv"] = {
            "value": 50000,
            "inputs": {"arpu_monthly": 3413, "churn_monthly": 0.0067, "gross_margin": 0.784},
        }
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] == 50000  # uses provided, not synthesized

    def test_preserves_existing_ltv_value_when_inputs_missing(self) -> None:
        """When ltv.value is provided but ltv.inputs is missing, synthesis fills inputs but keeps the value."""
        inp = self._base_inputs()
        inp["unit_economics"]["ltv"] = {"value": 75000}  # value present, inputs absent
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] == 75000  # must NOT be overwritten by synthesis
        # Evidence should NOT claim value was synthesized — only inputs were filled
        assert "synthesized from revenue.customers" not in ltv["evidence"].lower()

    def test_no_synthesis_without_customers(self) -> None:
        """Can't compute ARPU without customer count."""
        inp = self._base_inputs()
        del inp["revenue"]["customers"]
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] is None  # no data

    def test_no_synthesis_without_churn(self) -> None:
        """Can't compute LTV without churn."""
        inp = self._base_inputs()
        del inp["revenue"]["churn_monthly"]
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] is None

    def test_no_synthesis_with_zero_customers(self) -> None:
        """Zero customers → can't compute ARPU, no synthesis."""
        inp = self._base_inputs()
        inp["revenue"]["customers"] = 0
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        assert ltv["value"] is None

    def test_zero_churn_applies_60mo_cap(self) -> None:
        """Zero churn → 60-month LTV cap even with synthesized inputs."""
        inp = self._base_inputs()
        inp["revenue"]["churn_monthly"] = 0
        rc, data, _ = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inp))
        assert rc == 0
        ltv = next(m for m in data["metrics"] if m["name"] == "ltv")
        # arpu = 153603/45 = 3413.40, capped ltv = 3413.40 * 0.784 * 60 = 160,564
        expected = round(153603 / 45 * 0.784 * 60, 2)
        assert ltv["value"] == expected


# ---------------------------------------------------------------------------
# ARPU-vs-MRR derived divergence regression tests
# ---------------------------------------------------------------------------


def test_validate_arpu_derived_divergence() -> None:
    """When stated ARPU diverges >20% from MRR/customers, warn."""
    inputs = _make_inputs(stage="series-a", mrr=100_000, burn=80_000, growth=0.10)
    inputs["revenue"]["customers"] = 50
    inputs["unit_economics"] = {
        "ltv": {
            "inputs": {"arpu_monthly": 3400}  # 100K/50 = 2000, 3400 is 70% higher
        }
    }
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "ARPU_INCONSISTENT" in codes


def test_validate_arpu_derived_close_no_warning() -> None:
    """When stated ARPU is within 20% of MRR/customers, no warning."""
    inputs = _make_inputs(stage="series-a", mrr=100_000, burn=80_000, growth=0.10)
    inputs["revenue"]["customers"] = 50
    inputs["unit_economics"] = {
        "ltv": {
            "inputs": {"arpu_monthly": 2100}  # 100K/50 = 2000, 2100 is 5% higher
        }
    }
    rc, data, stderr = run_script("validate_inputs.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "ARPU_INCONSISTENT" not in codes


# ---------------------------------------------------------------------------
# Runway: cash direction warning + profitability regression tests
# ---------------------------------------------------------------------------


def test_runway_no_cash_direction_warning_when_profitable() -> None:
    """Growth-driven profitability should not trigger cash direction warning."""
    # High growth (20% MoM) with moderate burn → revenue overtakes expenses
    inputs = {
        "company": {
            "company_name": "GrowthCo",
            "slug": "growthco",
            "stage": "seed",
            "sector": "SaaS",
            "geography": "US",
        },
        "revenue": {
            "mrr": {"value": 50_000, "as_of": "2025-01"},
            "growth_rate_monthly": 0.20,
        },
        "cash": {
            "current_balance": 500_000,
            "balance_date": "2025-01",
            "monthly_net_burn": 100_000,
        },
    }
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    # With 20% MoM growth, revenue overtakes expenses → became profitable
    assert base["default_alive"] is True
    # Cash direction warning should NOT fire — growth explains cash increase
    assert base.get("cash_direction_warning") is None


def test_runway_cash_direction_warning_with_grant_no_profitability() -> None:
    """Grant-funded cash increase without profitability should still warn.

    IIA grants add cash monthly, making the company never run out of cash
    (default_alive = True), but the company never becomes cash-flow positive
    (revenue < expenses throughout). Cash increases due to grants, not
    operational profitability — the warning should fire.
    """
    inputs = {
        "company": {"company_name": "GrantCo", "slug": "grantco", "stage": "seed", "sector": "SaaS", "geography": "IL"},
        "revenue": {
            "mrr": {"value": 10_000, "as_of": "2025-01"},
            "growth_rate_monthly": 0.0,  # zero growth → never profitable
        },
        "cash": {
            "current_balance": 500_000,
            "balance_date": "2025-01",
            "monthly_net_burn": 20_000,
            "grants": {
                "iia_approved": 3_000_000,  # 50K/mo for 60 months
                "iia_disbursement_months": 60,
                "iia_start_month": 1,
            },
        },
    }
    rc, data, stderr = run_script("runway.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0
    assert data is not None
    base = next(s for s in data["scenarios"] if s["name"] == "base")
    # Revenue (10K) < opex (30K) throughout, never becomes profitable
    # But default_alive is True (never runs out of cash due to grants)
    # Cash increases due to grant inflows — warning SHOULD fire
    assert base["default_alive"] is True
    final_cash = base["monthly_projections"][-1]["cash_balance"]
    assert final_cash > 500_000  # cash increased
    assert base.get("cash_direction_warning") is not None
    # Risk narrative should NOT say "reaches profitability"
    assert "reaches profitability" not in data.get("risk_assessment", "")
