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

    def test_null_mrr_fails(self) -> None:
        """Null MRR value in inputs.json is an error."""
        arts = _full_artifacts()
        arts["inputs.json"] = json.loads(json.dumps(_INPUTS))
        arts["inputs.json"]["revenue"]["mrr"]["value"] = None
        rc, out, stderr = _run(arts)
        assert rc == 1
        inputs_issues = out["artifacts"]["inputs.json"]["issues"]
        assert any("mrr" in i["message"].lower() for i in inputs_issues)

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
        """The -o flag writes output to a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, data in _full_artifacts().items():
                with open(os.path.join(tmpdir, name), "w") as f:
                    json.dump(data, f)
            out_path = os.path.join(tmpdir, "verification.json")
            subprocess.run(
                [sys.executable, _SCRIPT, "--dir", tmpdir, "-o", out_path],
                capture_output=True,
                text=True,
            )
            assert os.path.exists(out_path)
            with open(out_path) as f:
                data = json.load(f)
            assert data["status"] == "pass"

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
