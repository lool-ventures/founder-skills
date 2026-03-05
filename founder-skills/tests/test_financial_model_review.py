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
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    base = script_dir or FMR_SCRIPTS_DIR
    cmd = [sys.executable, os.path.join(base, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
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
    """When compute inputs are present, computed burn_multiple is used, not reported."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["unit_economics"]["burn_multiple"] = 0.66
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    assert "burn_multiple" in metrics_by_name
    # Computed value should be used, not the reported 0.66
    assert metrics_by_name["burn_multiple"]["value"] != 0.66
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
    """Rule of 40 should be rated normally when ARR >= $1M."""
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["arr"]["value"] = 1200000
    payload = json.dumps(inputs)
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    metrics_by_name = {m["name"]: m for m in data["metrics"]}
    r40 = metrics_by_name["rule_of_40"]
    assert r40["rating"] != "not_applicable"
    assert r40["value"] is not None


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
