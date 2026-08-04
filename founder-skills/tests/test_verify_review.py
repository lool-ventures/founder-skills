# founder-skills/tests/test_verify_review.py
"""Tests for verify_review.py — review completeness gate."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

import pytest

_SCRIPTS = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "financial-model-review",
    "scripts",
)
_SCRIPT = os.path.join(_SCRIPTS, "verify_review.py")


def _run(artifacts: dict[str, Any], extra_args: list[str] | None = None) -> tuple[int, dict[str, Any], str]:
    """Write artifacts to temp dir, run verify, return (exit_code, output_dict, stderr).

    Values can be dicts (written as JSON) or strings (written raw, for corrupt JSON tests).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, data in artifacts.items():
            path = os.path.join(tmpdir, name)
            with open(path, "w") as f:
                if isinstance(data, str):
                    f.write(data)
                else:
                    json.dump(data, f)
        cmd = [sys.executable, _SCRIPT, "--dir", tmpdir, "--pretty"]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = {}
        if result.stdout.strip():
            with contextlib.suppress(json.JSONDecodeError):
                output = json.loads(result.stdout)
        return result.returncode, output, result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RUN_ID = "20260314T120000Z"

_INPUTS = {
    "company": {
        "company_name": "TestCo",
        "stage": "seed",
        "sector": "B2B SaaS",
        "geography": "US",
        "model_format": "spreadsheet",
    },
    "revenue": {
        "mrr": {"value": 50000, "as_of": "2026-01"},
        "arr": {"value": 600000, "as_of": "2026-01"},
        "customers": 100,
        "growth_rate_monthly": 0.1,
        "monthly": [
            {"month": "2026-01", "total": 50000, "actual": True},
        ],
    },
    "cash": {
        "current_balance": 1000000,
        "monthly_net_burn": 80000,
        "balance_date": "2026-01",
    },
    "metadata": {"run_id": _RUN_ID},
}


def _make_checklist(items: list[dict[str, Any]] | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Build a valid checklist.json with 46 items."""
    if items is None:
        items = []
        for i in range(46):
            items.append(
                {
                    "id": f"ITEM_{i:02d}",
                    "category": "structure",
                    "label": f"Item {i}",
                    "status": "pass",
                    "evidence": f"Checked item {i}",
                    "notes": None,
                }
            )
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "pass": sum(1 for i in items if i["status"] == "pass"),
            "fail": sum(1 for i in items if i["status"] == "fail"),
            "warn": sum(1 for i in items if i["status"] == "warn"),
            "not_applicable": sum(1 for i in items if i["status"] == "not_applicable"),
            "not_rated": 0,
            "warning": 0,
            "contextual": 0,
            "score_pct": 80.0,
            "overall_status": "solid",
            "failed_items": [i for i in items if i["status"] == "fail"],
            "warned_items": [i for i in items if i["status"] == "warn"],
        },
        "metadata": {"run_id": run_id or _RUN_ID},
    }


def _make_ue(run_id: str | None = None) -> dict[str, Any]:
    """Build a valid unit_economics.json."""
    return {
        "metrics": [
            {
                "name": "cac",
                "value": 5000,
                "rating": "acceptable",
                "evidence": "",
                "benchmark_source": "OpenView 2025",
                "benchmark_as_of": "2025-Q4",
            },
            {
                "name": "ltv",
                "value": 25000,
                "rating": "strong",
                "evidence": "",
                "benchmark_source": "OpenView 2025",
                "benchmark_as_of": "2025-Q4",
            },
            {
                "name": "burn_multiple",
                "value": 1.5,
                "rating": "acceptable",
                "evidence": "",
                "benchmark_source": "Bessemer 2025",
                "benchmark_as_of": "2025-Q4",
            },
        ],
        "summary": {
            "computed": 3,
            "strong": 1,
            "acceptable": 2,
            "warning": 0,
            "fail": 0,
            "not_rated": 0,
            "not_applicable": 0,
            "contextual": 0,
        },
        "metadata": {"run_id": run_id or _RUN_ID},
    }


def _make_runway(net_cash: int | None = 1000000, run_id: str | None = None) -> dict[str, Any]:
    """Build a valid runway.json."""
    return {
        "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
        "baseline": {
            "net_cash": net_cash,
            "monthly_burn": 80000,
            "monthly_revenue": 50000,
        },
        "scenarios": [
            {
                "name": "base",
                "growth_rate": 0.1,
                "runway_months": 12,
                "default_alive": False,
                "cash_out_date": "2027-01",
                "decision_point": "2026-09",
                "became_profitable": False,
                "monthly_projections": [],
            },
        ],
        "risk_assessment": "Moderate burn with 12 months runway",
        "limitations": [],
        "warnings": [],
        "post_raise": None,
        "metadata": {"run_id": run_id or _RUN_ID},
    }


def _make_report(run_id: str | None = None) -> dict[str, Any]:
    """Build a valid report.json."""
    return {
        "report_markdown": "# Financial Model Review\n\nSummary here.",
        "validation": {"status": "clean", "warnings": []},
        "metadata": {"run_id": run_id or _RUN_ID},
    }


def _make_commentary() -> dict[str, Any]:
    """Build a valid commentary.json."""
    return {
        "headline": "TestCo has 12 months of runway with solid unit economics.",
        "lenses": {
            "runway": {
                "callout": "12 months runway",
                "highlight": "Default alive in base case",
            },
        },
        "metadata": {"run_id": _RUN_ID},
    }


def _full_artifacts() -> dict[str, Any]:
    """Return a complete set of valid artifacts (quantitative spreadsheet review)."""
    return {
        "inputs.json": _INPUTS,
        "checklist.json": _make_checklist(),
        "unit_economics.json": _make_ue(),
        "runway.json": _make_runway(),
        "report.json": _make_report(),
        "commentary.json": _make_commentary(),
    }


def _gate1_artifacts() -> dict[str, Any]:
    """Return artifacts expected at Gate 1 (after compose, before commentary)."""
    arts = _full_artifacts()
    del arts["commentary.json"]
    return arts


# ---------------------------------------------------------------------------
# Tests: Full Pass
# ---------------------------------------------------------------------------


class TestStrayFiles:
    """The Gate-2 stray-file allowlist must recognise the skill's own mandated
    workflow artifacts (Steps 3.5/3.6) and still flag genuinely-unknown files."""

    def test_review_html_not_flagged_stray(self) -> None:
        arts = {**_full_artifacts(), "review.html": "<html></html>"}
        rc, out, _ = _run(arts)
        assert not any("review.html" in cc["message"] for cc in out["cross_checks"])

    def test_extraction_validation_json_not_flagged_stray(self) -> None:
        arts = {**_full_artifacts(), "extraction_validation.json": {"status": "pass", "checks": []}}
        rc, out, _ = _run(arts)
        assert not any("extraction_validation.json" in cc["message"] for cc in out["cross_checks"])

    def test_unknown_file_still_flagged_stray(self) -> None:
        arts = {**_full_artifacts(), "scratch_notes.txt": "tmp"}
        rc, out, _ = _run(arts)
        assert rc == 0
        assert any("scratch_notes.txt" in cc["message"] and cc["severity"] == "warning" for cc in out["cross_checks"])


class TestFullPass:
    def test_complete_review_passes(self) -> None:
        """A complete review with all valid artifacts passes."""
        rc, out, stderr = _run(_full_artifacts())
        assert rc == 0
        assert out["status"] == "pass"

    def test_output_has_required_keys(self) -> None:
        """Output has artifacts, cross_checks, summary keys."""
        rc, out, stderr = _run(_full_artifacts())
        assert "artifacts" in out
        assert "cross_checks" in out
        assert "summary" in out

    def test_gate1_passes_without_commentary(self) -> None:
        """Gate 1 (after compose) passes without commentary.json."""
        rc, out, stderr = _run(_gate1_artifacts(), ["--gate", "1"])
        assert rc == 0
        assert out["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: Missing Artifacts
# ---------------------------------------------------------------------------


class TestMissingArtifacts:
    def test_missing_inputs_fails(self) -> None:
        """Missing inputs.json is an error."""
        arts = _full_artifacts()
        del arts["inputs.json"]
        rc, out, stderr = _run(arts)
        assert rc == 1
        assert out["status"] == "fail"
        assert not out["artifacts"]["inputs.json"]["exists"]

    def test_missing_checklist_fails(self) -> None:
        """Missing checklist.json is an error."""
        arts = _full_artifacts()
        del arts["checklist.json"]
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_missing_commentary_fails_at_gate2_for_spreadsheet(self) -> None:
        """Missing commentary.json is an error at Gate 2 when model_format is spreadsheet."""
        arts = _full_artifacts()
        del arts["commentary.json"]
        rc, out, stderr = _run(arts)  # default is gate 2
        assert rc == 1
        assert any("commentary" in e for e in out["summary"]["errors"])

    def test_missing_commentary_ok_at_gate1(self) -> None:
        """Missing commentary.json is OK at Gate 1 (not yet created)."""
        arts = _gate1_artifacts()
        rc, out, stderr = _run(arts, ["--gate", "1"])
        assert rc == 0

    def test_missing_commentary_ok_for_qualitative_conversational(self) -> None:
        """Missing commentary.json is OK for qualitative (skipped) conversational reviews."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["model_format"] = "conversational"
        del arts["commentary.json"]
        # Make it a qualitative review — skip unit_economics and runway
        arts["unit_economics.json"] = {"skipped": True, "reason": "qualitative path"}
        arts["runway.json"] = {"skipped": True, "reason": "qualitative path"}
        rc, out, stderr = _run(arts)
        assert rc == 0

    def test_missing_commentary_ok_for_qualitative_deck(self) -> None:
        """Missing commentary.json is OK for qualitative (skipped) deck reviews."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["model_format"] = "deck"
        del arts["commentary.json"]
        # Make it a qualitative review — skip unit_economics and runway
        arts["unit_economics.json"] = {"skipped": True, "reason": "qualitative path"}
        arts["runway.json"] = {"skipped": True, "reason": "qualitative path"}
        rc, out, stderr = _run(arts)
        assert rc == 0

    def test_missing_commentary_fails_for_quantitative_deck(self) -> None:
        """Missing commentary.json fails for quantitative deck reviews."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["model_format"] = "deck"
        del arts["commentary.json"]
        # unit_economics.json and runway.json are NOT skipped -> quantitative path
        rc, out, stderr = _run(arts)
        assert rc == 1


# ---------------------------------------------------------------------------
# Tests: Skipped Stubs (qualitative path)
# ---------------------------------------------------------------------------


class TestSkippedStubs:
    def test_skipped_ue_passes(self) -> None:
        """Skipped unit_economics.json stub passes (qualitative path)."""
        arts = _full_artifacts()
        arts["unit_economics.json"] = {"skipped": True, "reason": "qualitative path"}
        rc, out, stderr = _run(arts)
        assert rc == 0

    def test_skipped_runway_passes(self) -> None:
        """Skipped runway.json stub passes (qualitative path)."""
        arts = _full_artifacts()
        arts["runway.json"] = {"skipped": True, "reason": "qualitative path"}
        rc, out, stderr = _run(arts)
        assert rc == 0

    def test_skipped_commentary_passes_for_deck(self) -> None:
        """Skipped commentary.json with deck model_format passes."""
        arts = _full_artifacts()
        arts["commentary.json"] = {"skipped": True, "reason": "deck model_format"}
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["model_format"] = "deck"
        rc, out, stderr = _run(arts)
        assert rc == 0

    def test_skipped_ue_and_runway_qualitative(self) -> None:
        """Full qualitative review: skipped UE + runway + commentary for conversational."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["model_format"] = "conversational"
        arts["unit_economics.json"] = {"skipped": True, "reason": "qualitative path"}
        arts["runway.json"] = {"skipped": True, "reason": "qualitative path"}
        del arts["commentary.json"]
        rc, out, stderr = _run(arts)
        assert rc == 0


# ---------------------------------------------------------------------------
# Tests: Content Quality
# ---------------------------------------------------------------------------


class TestContentQuality:
    def test_checklist_fail_missing_evidence(self) -> None:
        """Checklist fail item with empty evidence is an error."""
        items = [
            {
                "id": f"ITEM_{i:02d}",
                "category": "structure",
                "label": f"Item {i}",
                "status": "pass",
                "evidence": f"Checked item {i}",
                "notes": None,
            }
            for i in range(45)
        ]
        items.append(
            {
                "id": "ITEM_45",
                "category": "structure",
                "label": "Bad item",
                "status": "fail",
                "evidence": "",
                "notes": None,
            }
        )
        arts = _full_artifacts()
        arts["checklist.json"] = _make_checklist(items)
        rc, out, stderr = _run(arts)
        assert rc == 1
        checklist_issues = out["artifacts"]["checklist.json"]["issues"]
        assert any("evidence" in i["message"].lower() for i in checklist_issues)

    def test_checklist_warn_missing_evidence(self) -> None:
        """Checklist warn item with empty evidence is an error."""
        items = [
            {
                "id": f"ITEM_{i:02d}",
                "category": "structure",
                "label": f"Item {i}",
                "status": "pass",
                "evidence": f"Checked item {i}",
                "notes": None,
            }
            for i in range(45)
        ]
        items.append(
            {
                "id": "ITEM_45",
                "category": "structure",
                "label": "Warn no ev",
                "status": "warn",
                "evidence": "",
                "notes": None,
            }
        )
        arts = _full_artifacts()
        arts["checklist.json"] = _make_checklist(items)
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_checklist_pass_missing_evidence(self) -> None:
        """Checklist pass item with empty evidence is an error."""
        items = [
            {
                "id": f"ITEM_{i:02d}",
                "category": "structure",
                "label": f"Item {i}",
                "status": "pass",
                "evidence": f"Checked item {i}",
                "notes": None,
            }
            for i in range(45)
        ]
        items.append(
            {
                "id": "ITEM_45",
                "category": "structure",
                "label": "Pass no ev",
                "status": "pass",
                "evidence": "",
                "notes": None,
            }
        )
        arts = _full_artifacts()
        arts["checklist.json"] = _make_checklist(items)
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_checklist_wrong_count_fails(self) -> None:
        """Checklist with != 46 items is an error."""
        items = [
            {
                "id": f"ITEM_{i}",
                "category": "structure",
                "label": f"I{i}",
                "status": "pass",
                "evidence": f"E{i}",
                "notes": None,
            }
            for i in range(10)
        ]
        arts = _full_artifacts()
        arts["checklist.json"] = _make_checklist(items)
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_null_critical_inputs_fails(self) -> None:
        """Null truly critical fields (company_name, stage) in inputs.json are errors."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["company_name"] = None
        rc, out, stderr = _run(arts)
        assert rc == 1
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("company_name" in i["message"] for i in inputs_issues)

    def test_null_stage_fails(self) -> None:
        """Null stage in inputs.json is an error."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["stage"] = None
        rc, out, stderr = _run(arts)
        assert rc == 1
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("stage" in i["message"] for i in inputs_issues)

    def test_null_mrr_with_series_warns(self) -> None:
        """Null MRR scalar but a populated monthly revenue series is honest
        degradation — a warning, not a blocking error (the series is real evidence)."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))  # _INPUTS retains revenue.monthly
        arts["inputs.json"]["revenue"]["mrr"]["value"] = None
        rc, out, stderr = _run(arts)
        assert rc == 0, stderr
        assert out["status"] == "pass"
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("revenue" in i["message"].lower() and i["severity"] == "warning" for i in inputs_issues)

    def _inputs_missing_revenue(self) -> dict[str, Any]:
        inp: dict[str, Any] = json.loads(json.dumps(_INPUTS))
        inp["revenue"]["mrr"]["value"] = None
        inp["revenue"].pop("arr", None)
        inp["revenue"].pop("monthly", None)
        return inp

    def test_missing_revenue_warns_with_estimated_confidence(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["company"]["data_confidence"] = "estimated"
        arts["inputs.json"] = inp
        rc, out, stderr = _run(arts)
        assert rc == 0, stderr
        assert out["status"] == "pass"
        issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("revenue" in i["message"].lower() and i["severity"] == "warning" for i in issues)

    def test_missing_revenue_warns_with_mixed_confidence(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["company"]["data_confidence"] = "mixed"
        arts["inputs.json"] = inp
        rc, out, _ = _run(arts)
        assert rc == 0
        issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("revenue" in i["message"].lower() and i["severity"] == "warning" for i in issues)

    def test_missing_revenue_warns_with_monthly_series(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["revenue"]["monthly"] = [{"month": "2026-01", "total": 50000, "actual": True}]
        arts["inputs.json"] = inp
        rc, out, _ = _run(arts)
        assert rc == 0
        assert any(i["severity"] == "warning" for i in out["artifacts"]["inputs.json"]["issues"])

    def test_missing_revenue_warns_with_quarterly_series(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["revenue"]["quarterly"] = [{"quarter": "2026-Q1", "total": 150000, "actual": True}]
        arts["inputs.json"] = inp
        rc, out, _ = _run(arts)
        assert rc == 0
        assert any(i["severity"] == "warning" for i in out["artifacts"]["inputs.json"]["issues"])

    def test_missing_revenue_still_fails_without_honest_signal(self) -> None:
        """Fabricated-empty backstop: no series, no estimated/mixed confidence -> hard error."""
        arts = _full_artifacts()
        arts["inputs.json"] = self._inputs_missing_revenue()
        rc, out, _ = _run(arts)
        assert rc == 1
        assert any(
            "revenue" in i["message"].lower() and i["severity"] == "error"
            for i in out["artifacts"]["inputs.json"]["issues"]
        )

    def test_empty_monthly_series_does_not_downgrade(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["revenue"]["monthly"] = []
        arts["inputs.json"] = inp
        rc, _out, _ = _run(arts)
        assert rc == 1

    def test_monthly_series_without_totals_does_not_downgrade(self) -> None:
        arts = _full_artifacts()
        inp = self._inputs_missing_revenue()
        inp["revenue"]["monthly"] = [{"month": "2026-01"}]
        arts["inputs.json"] = inp
        rc, _out, _ = _run(arts)
        assert rc == 1

    def test_ue_insufficient_data_flag_warns(self) -> None:
        arts = _full_artifacts()
        arts["unit_economics.json"] = {
            "metrics": [
                {
                    "name": "cac",
                    "value": None,
                    "rating": "not_rated",
                    "evidence": "",
                    "benchmark_source": "",
                    "benchmark_as_of": "",
                }
            ],
            "summary": {
                "computed": 0,
                "strong": 0,
                "acceptable": 0,
                "warning": 0,
                "fail": 0,
                "not_rated": 1,
                "not_applicable": 0,
                "contextual": 0,
            },
            "insufficient_data": True,
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, _ = _run(arts)
        assert rc == 0
        assert any(i["severity"] == "warning" for i in out["artifacts"]["unit_economics.json"]["issues"])

    def test_ue_partial_analysis_flag_warns(self) -> None:
        arts = _full_artifacts()
        ue = _make_ue()
        ue["metrics"] = [
            {
                "name": "cac",
                "value": None,
                "rating": "not_rated",
                "evidence": "",
                "benchmark_source": "",
                "benchmark_as_of": "",
            }
        ]
        ue["summary"]["computed"] = 0
        ue["partial_analysis"] = True
        arts["unit_economics.json"] = ue
        rc, out, _ = _run(arts)
        assert rc == 0
        assert any(i["severity"] == "warning" for i in out["artifacts"]["unit_economics.json"]["issues"])

    def test_null_cash_balance_warns(self) -> None:
        """Null cash.current_balance produces a warning but still passes (exit 0)."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["cash"]["current_balance"] = None
        rc, out, stderr = _run(arts)
        assert rc == 0
        assert out["status"] == "pass"
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("current_balance" in i["message"] and i["severity"] == "warning" for i in inputs_issues)

    def test_null_monthly_net_burn_warns(self) -> None:
        """Null cash.monthly_net_burn produces a warning but still passes (exit 0)."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["cash"]["monthly_net_burn"] = None
        rc, out, stderr = _run(arts)
        assert rc == 0
        assert out["status"] == "pass"
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("monthly_net_burn" in i["message"] and i["severity"] == "warning" for i in inputs_issues)

    def test_null_company_name_fails(self) -> None:
        """Null company name in inputs.json is an error."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["company"]["company_name"] = None
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_commentary_missing_headline_fails(self) -> None:
        """Commentary without headline is an error."""
        arts = _full_artifacts()
        arts["commentary.json"] = {
            "lenses": {"runway": {}},
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_commentary_missing_lenses_fails(self) -> None:
        """Commentary without any lens is an error."""
        arts = _full_artifacts()
        arts["commentary.json"] = {
            "headline": "Good.",
            "lenses": {},
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_runway_null_baseline_warns(self) -> None:
        """Runway with null baseline.net_cash is a warning (not error)."""
        arts = _full_artifacts()
        arts["runway.json"] = _make_runway(net_cash=None)
        rc, out, stderr = _run(arts)
        assert out["status"] == "pass"
        assert len(out["summary"]["warnings"]) > 0

    def test_runway_partial_analysis_passes(self) -> None:
        """Runway with scenarios: [] and partial_analysis: true is valid."""
        arts = _full_artifacts()
        arts["runway.json"] = {
            "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
            "baseline": {
                "net_cash": None,
                "monthly_burn": 80000,
                "monthly_revenue": None,
            },
            "scenarios": [],
            "partial_analysis": True,
            "insufficient_data": True,
            "risk_assessment": "Cash balance unknown",
            "limitations": [],
            "warnings": ["Missing cash"],
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, stderr = _run(arts)
        assert rc == 0
        assert out["status"] == "pass"

    def test_empty_report_markdown_fails(self) -> None:
        """Empty report_markdown is an error."""
        arts = _full_artifacts()
        arts["report.json"]["report_markdown"] = ""
        rc, out, stderr = _run(arts)
        assert rc == 1

    def test_ue_insufficient_metrics_fails(self) -> None:
        """Unit economics with < 2 computed metrics is an error."""
        arts = _full_artifacts()
        arts["unit_economics.json"] = {
            "metrics": [{"name": "cac", "value": None, "rating": "not_rated"}],
            "summary": {
                "computed": 0,
                "strong": 0,
                "acceptable": 0,
                "warning": 0,
                "fail": 0,
                "not_rated": 1,
                "not_applicable": 0,
                "contextual": 0,
            },
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, stderr = _run(arts)
        assert rc == 1


# ---------------------------------------------------------------------------
# Tests: Cross-Artifact Consistency
# ---------------------------------------------------------------------------


class TestCrossChecks:
    def test_stale_run_id_fails(self) -> None:
        """Mismatched run_id across artifacts is an error."""
        arts = _full_artifacts()
        arts["checklist.json"] = _make_checklist(run_id="STALE_ID")
        rc, out, stderr = _run(arts)
        assert rc == 1
        assert any("run_id" in c["message"].lower() for c in out["cross_checks"])

    def test_runway_cash_mismatch_warns(self) -> None:
        """runway baseline.net_cash != inputs cash.current_balance is a warning."""
        arts = _full_artifacts()
        arts["runway.json"] = _make_runway(net_cash=500000)
        rc, out, stderr = _run(arts)
        assert out["status"] == "pass"
        assert any("net_cash" in c["message"] for c in out["cross_checks"])

    def test_timeseries_mrr_mismatch_warns(self) -> None:
        """Latest monthly revenue total diverging >20% from MRR is a warning."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["revenue"]["monthly"] = [
            {"month": "2026-01", "total": 80000, "actual": True},  # 60% > MRR 50k
        ]
        rc, out, stderr = _run(arts)
        assert out["status"] == "pass"  # warning, not error
        assert any(
            "timeseries" in c["message"].lower() or "monthly" in c["message"].lower() for c in out["cross_checks"]
        )

    def test_arr_mrr_mismatch_warns(self) -> None:
        """ARR/12 diverging >20% from MRR is a warning."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["revenue"]["arr"]["value"] = 1200000  # 100k/mo vs 50k MRR
        rc, out, stderr = _run(arts)
        assert out["status"] == "pass"
        assert any("arr" in c["message"].lower() for c in out["cross_checks"])


# ---------------------------------------------------------------------------
# Tests: Corrupt Artifacts
# ---------------------------------------------------------------------------


class TestCorruptArtifacts:
    def test_corrupt_json_fails(self) -> None:
        """Invalid JSON in an artifact is an error."""
        arts = _full_artifacts()
        arts["checklist.json"] = "{invalid json"  # raw string, not dict
        rc, out, stderr = _run(arts)
        assert rc == 1
        assert not out["artifacts"]["checklist.json"]["valid"]


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dir_fails(self) -> None:
        """Empty directory fails with all artifacts missing."""
        rc, out, stderr = _run({})
        assert rc == 1
        assert out["summary"]["failed"] > 0

    def test_pretty_flag(self) -> None:
        """--pretty produces indented JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, data in _full_artifacts().items():
                with open(os.path.join(tmpdir, name), "w") as f:
                    json.dump(data, f)
            result = subprocess.run(
                [sys.executable, _SCRIPT, "--dir", tmpdir, "--pretty"],
                capture_output=True,
                text=True,
            )
            assert "\n  " in result.stdout

    def test_output_to_file(self) -> None:
        """The -o flag writes output to a file and emits a JSON receipt on
        stdout (per the shared script convention)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, data in _full_artifacts().items():
                with open(os.path.join(tmpdir, name), "w") as f:
                    json.dump(data, f)
            out_path = os.path.join(tmpdir, "verification.json")
            result = subprocess.run(
                [sys.executable, _SCRIPT, "--dir", tmpdir, "-o", out_path],
                capture_output=True,
                text=True,
            )
            assert os.path.exists(out_path)
            with open(out_path) as f:
                data = json.load(f)
            assert data["status"] == "pass"
            # stdout carries the receipt, not the raw result JSON.
            receipt = json.loads(result.stdout)
            assert receipt["ok"] is True
            assert receipt["path"] == os.path.abspath(out_path)
            assert receipt["bytes"] > 0

    def test_gate1_flag(self) -> None:
        """--gate 1 skips commentary check."""
        arts = _gate1_artifacts()
        rc, out, stderr = _run(arts, ["--gate", "1"])
        assert rc == 0

    def test_default_is_gate2(self) -> None:
        """Without --gate flag, runs full Gate 2 checks."""
        arts = _gate1_artifacts()  # no commentary
        rc, out, stderr = _run(arts)  # no --gate flag
        assert rc == 1  # fails because commentary missing for spreadsheet

    def test_runway_quality_accepts_default_alive_company(self) -> None:
        """A profitable company legitimately has runway_months: null in every
        scenario (cash never runs out). The gate must not error on that
        (regression: it demanded a non-null runway_months unconditionally)."""
        arts = _full_artifacts()
        arts["runway.json"] = {
            "company": {"name": "TestCo", "slug": "testco", "stage": "seed"},
            "baseline": {
                "net_cash": 1000000,
                "monthly_burn": 0,
                "monthly_revenue": 150000,
            },
            "scenarios": [
                {
                    "name": "base",
                    "runway_months": None,
                    "default_alive": True,
                    "cash_out_date": None,
                    "growth_rate": 0.1,
                    "decision_point": None,
                    "became_profitable": True,
                    "monthly_projections": [],
                },
                {
                    "name": "downside",
                    "runway_months": None,
                    "default_alive": True,
                    "cash_out_date": None,
                    "growth_rate": 0.05,
                    "decision_point": None,
                    "became_profitable": True,
                    "monthly_projections": [],
                },
            ],
            "risk_assessment": "Company is default-alive",
            "limitations": [],
            "warnings": [],
            "post_raise": None,
            "metadata": {"run_id": _RUN_ID},
        }
        rc, out, stderr = _run(arts, ["--gate", "1"])
        runway_issues = out["artifacts"]["runway.json"]["issues"]
        runway_errors = [i for i in runway_issues if i["severity"] == "error"]
        assert not runway_errors, f"Unexpected runway errors for default-alive company: {runway_errors}"


# ---------------------------------------------------------------------------
# Inputs-drift fingerprints
#
# run_id parity cannot see this class: apply_corrections.py rewrites inputs.json inside a single run,
# so an output computed before the corrections carries the same run_id as one computed after.
# ---------------------------------------------------------------------------


def _fingerprint_of(doc: dict[str, Any]) -> str:
    import importlib.util

    path = os.path.join(_SCRIPTS, "_fingerprint.py")
    spec = importlib.util.spec_from_file_location("_fingerprint", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.fingerprint(doc))


def test_matching_inputs_fingerprint_raises_no_drift_issue() -> None:
    arts = _full_artifacts()
    fp = _fingerprint_of(arts["inputs.json"])
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        arts[name]["graded_against"] = {"inputs.json": fp}
    _rc, out, _err = _run(arts)
    text = json.dumps(out)
    assert "different version of the inputs" not in text


def test_stale_output_is_flagged_when_inputs_changed_after_it_ran() -> None:
    """The whole point: outputs can agree with each other while all are stale."""
    arts = _full_artifacts()
    stale = _fingerprint_of({"cash": {"current_balance": 1}})
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        arts[name]["graded_against"] = {"inputs.json": stale}
    _rc, out, _err = _run(arts)
    text = json.dumps(out)
    assert "different version of the inputs" in text, "drift against current inputs was not detected"
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        assert name in text


def test_a_recorded_null_fingerprint_is_reported_not_passed_over() -> None:
    """ "No fingerprint" and "matching fingerprint" are different claims."""
    arts = _full_artifacts()
    arts["runway.json"]["graded_against"] = {"inputs.json": None}
    _rc, out, _err = _run(arts)
    assert "records no fingerprint" in json.dumps(out)


def test_absent_graded_against_is_not_an_error() -> None:
    """An artifact produced before fingerprints existed has nothing to compare, not a failure."""
    arts = _full_artifacts()
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        arts[name].pop("graded_against", None)
    _rc, out, _err = _run(arts)
    text = json.dumps(out)
    assert "different version of the inputs" not in text
    assert "records no fingerprint" not in text


def test_run_id_parity_alone_would_miss_this() -> None:
    """Every artifact shares one run_id and the drift is still detected."""
    arts = _full_artifacts()
    stale = _fingerprint_of({"cash": {"current_balance": 1}})
    arts["runway.json"]["graded_against"] = {"inputs.json": stale}
    run_ids = {
        json.dumps(a.get("metadata", {}).get("run_id"))
        for a in arts.values()
        if isinstance(a, dict) and a.get("metadata")
    }
    assert len(run_ids) == 1, f"fixture must share one run_id for this test to mean anything: {run_ids}"
    assert "different version of the inputs" in json.dumps(_run(arts)[1])


def test_metadata_is_excluded_from_the_fingerprint() -> None:
    """Stamping a run_id must not read as an inputs change."""
    base = {"cash": {"current_balance": 100}}
    with_meta = {"cash": {"current_balance": 100}, "metadata": {"run_id": "abc"}}
    assert _fingerprint_of(base) == _fingerprint_of(with_meta)


def _shared_inputs() -> dict[str, Any]:
    import test_financial_model_review as t

    assert hasattr(t, "_VALID_INPUTS"), "shared inputs fixture went missing"
    return dict(t._VALID_INPUTS)


@pytest.mark.parametrize("producer", ["runway.py", "unit_economics.py"])
def test_direct_pipe_producers_record_the_fingerprint_end_to_end(producer: str) -> None:
    """The stamp must survive a real producer run, not just the helper's unit behaviour.

    Both of these consume inputs.json verbatim, so the payload IS the document to fingerprint.
    """
    inputs = _shared_inputs()
    result = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS, producer)],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    produced = json.loads(result.stdout)
    assert produced.get("graded_against", {}).get("inputs.json") == _fingerprint_of(inputs), (
        f"{producer} did not record the fingerprint of the inputs it computed from"
    )


def test_checklist_records_the_fingerprint_of_its_embedded_inputs() -> None:
    """checklist.py receives the inputs under an `inputs` key rather than as the whole payload."""
    inputs = _shared_inputs()
    payload = {"items": [], "inputs": inputs}
    result = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS, "checklist.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    produced = json.loads(result.stdout)
    assert produced.get("graded_against", {}).get("inputs.json") == _fingerprint_of(inputs)


def test_checklist_records_null_when_it_cannot_see_the_inputs() -> None:
    """`inputs` is optional in that payload; a null must be recorded rather than the key omitted.

    Omitting it is indistinguishable from a producer that predates fingerprints, which the verifier
    passes over silently.
    """
    result = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS, "checklist.py")],
        input=json.dumps({"items": []}),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    graded = json.loads(result.stdout).get("graded_against", {})
    assert "inputs.json" in graded
    assert graded["inputs.json"] is None


def test_every_fingerprinting_producer_is_covered_by_this_module() -> None:
    """A new producer that stamps must gain a test here, or its coverage is silently absent."""
    stampers = set()
    for py in os.listdir(_SCRIPTS):
        if not py.endswith(".py") or py.startswith("_"):
            continue
        with open(os.path.join(_SCRIPTS, py), encoding="utf-8") as f:
            if "_fingerprint.stamp(" in f.read():
                stampers.add(py)
    assert stampers == {"runway.py", "unit_economics.py", "checklist.py"}, (
        f"the set of fingerprint-stamping producers changed: {sorted(stampers)}. Add the new one to the "
        f"end-to-end tests above."
    )
