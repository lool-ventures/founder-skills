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
    # Producers stamp `graded_against` unconditionally, and the verifier now treats an ABSENT stamp as
    # removed-after-the-fact. So a test writing producer outputs without one describes an artifact no
    # run can emit. Stamp here, from the inputs THIS call writes — many tests mutate inputs to exercise
    # an unrelated check, and a stamp frozen at fixture-build time would read as drift. A test that sets
    # `graded_against` itself keeps its value: that is how the drift tests below express staleness.
    artifacts = dict(artifacts)
    inputs_doc = artifacts.get("inputs.json")
    if isinstance(inputs_doc, dict):
        digest = _fingerprint_of(inputs_doc)
        for name in ("checklist.json", "unit_economics.json", "runway.json"):
            art = artifacts.get(name)
            if isinstance(art, dict) and "graded_against" not in art:
                art = dict(art)
                art["graded_against"] = {"inputs.json": digest}
                artifacts[name] = art

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


def _stamped_artifacts() -> dict[str, Any]:
    """`_full_artifacts()` with `graded_against` applied, for tests that stage files themselves
    instead of going through `_run` (which stamps at write time)."""
    arts = _full_artifacts()
    digest = _fingerprint_of(arts["inputs.json"])
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        arts[name]["graded_against"] = {"inputs.json": digest}
    return arts


def _full_artifacts() -> dict[str, Any]:
    """Return a complete set of valid artifacts (quantitative spreadsheet review).

    `graded_against` is applied at WRITE time by `_run`, not here — see the note there.
    """
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
            for name, data in _stamped_artifacts().items():
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
    assert result.returncode == 1, (
        result.stderr
    )  # `items: []` is a deliberately-invalid probe payload; checklist.py now refuses it (exit 1)
    # while still stamping provenance, so the fingerprint stays observable on stdout.
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
    assert result.returncode == 1, (
        result.stderr
    )  # `items: []` is a deliberately-invalid probe payload; checklist.py now refuses it (exit 1)
    # while still stamping provenance, so the fingerprint stays observable on stdout.
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
            body = f.read()
            if "_fingerprint.stamp(" in body or "_fingerprint.stamp_hashes(" in body:
                stampers.add(py)
    assert stampers == {"runway.py", "unit_economics.py", "checklist.py"}, (
        f"the set of fingerprint-stamping producers changed: {sorted(stampers)}. Add the new one to the "
        f"end-to-end tests above."
    )


# ---------------------------------------------------------------------------
# Evidence must not name internal files
#
# Evidence reaches report.md verbatim. A live run produced 10 items citing inputs.json, which the
# founder never saw. Prose guidance alone has measured as inert in this fleet, so the gate checks it.
# ---------------------------------------------------------------------------


def _artifacts_with_evidence(evidence: str) -> dict[str, Any]:
    arts = _full_artifacts()
    arts["checklist.json"]["items"][0]["status"] = "fail"
    arts["checklist.json"]["items"][0]["evidence"] = evidence
    return arts


def _checklist_warnings(out: dict[str, Any]) -> list[str]:
    entry = out.get("artifacts", {}).get("checklist.json", {})
    return [str(i.get("message", "")) for i in entry.get("issues", [])]


def test_evidence_naming_an_internal_artifact_is_flagged() -> None:
    _rc, out, _err = _run(_artifacts_with_evidence("inputs.json reports actuals separated: false"))
    hits = [m for m in _checklist_warnings(out) if "names internal file" in m]
    assert hits, "evidence citing inputs.json was not flagged"
    assert "inputs.json" in hits[0]


def test_evidence_naming_the_founders_own_upload_is_not_flagged() -> None:
    """Naming their upload back to them is useful; flagging it trains readers to ignore the warning."""
    _rc, out, _err = _run(_artifacts_with_evidence("the workbook sample_model.xlsx has no assumptions tab"))
    assert not [m for m in _checklist_warnings(out) if "names internal file" in m]


def test_founder_facing_evidence_passes_clean() -> None:
    _rc, out, _err = _run(_artifacts_with_evidence("the model does not separate actuals from projections"))
    assert not [m for m in _checklist_warnings(out) if "names internal file" in m]


def test_the_flag_is_a_warning_not_a_publish_block() -> None:
    """A wording slip must not cost the founder their review."""
    _rc, out, _err = _run(_artifacts_with_evidence("inputs.json reports actuals separated: false"))
    assert out.get("status") != "fail", "an evidence-wording issue must not fail the gate"


def test_checklist_fingerprint_resolves_when_inputs_are_passed() -> None:
    """--inputs closes the null-fingerprint hole: the payload carries `company`, not the whole doc."""
    inputs = _shared_inputs()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "inputs.json")
        with open(path, "w") as f:
            json.dump(inputs, f)
        result = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS, "checklist.py"), "--inputs", path],
            input=json.dumps({"items": []}),
            capture_output=True,
            text=True,
        )
    assert result.returncode == 1, (
        result.stderr
    )  # `items: []` is a deliberately-invalid probe payload; checklist.py now refuses it (exit 1)
    # while still stamping provenance, so the fingerprint stays observable on stdout.
    graded = json.loads(result.stdout).get("graded_against", {})
    assert graded.get("inputs.json") == _fingerprint_of(inputs)


# ---------------------------------------------------------------------------
# Producer stamp must equal the verifier's hash of the SAME document
#
# A compute step may mutate the document it was handed (`_compute_metrics` adds `unit_economics.ltv`),
# and hashing afterwards fingerprints something that never existed on disk. The verifier hashes the
# file, so the two can never agree — a staleness error on a perfectly current artifact.
# ---------------------------------------------------------------------------


def _inputs_that_trigger_the_mutation() -> dict[str, Any]:
    """The standard fixture already carries `unit_economics.ltv`, so the compute step adds nothing and
    the round-trip passes for the wrong reason. Removing it is what makes this test able to fail."""
    inputs = _shared_inputs()
    inputs["unit_economics"] = {k: v for k, v in inputs.get("unit_economics", {}).items() if k != "ltv"}
    return inputs


@pytest.mark.parametrize("producer", ["unit_economics.py", "runway.py"])
def test_producer_stamp_round_trips_with_the_verifier(producer: str) -> None:
    inputs = _inputs_that_trigger_the_mutation()
    payload = json.dumps(inputs)
    result = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS, producer)],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    stamped = json.loads(result.stdout).get("graded_against", {}).get("inputs.json")
    assert stamped == _fingerprint_of(inputs), (
        f"{producer} stamped a fingerprint the verifier will not reproduce from the same document. "
        f"Hash the inputs AS RECEIVED, before any compute step that may mutate them."
    )


def test_producers_capture_the_fingerprint_before_computing() -> None:
    """Ordering is the invariant, and it is not observable from a passing round-trip.

    `_compute_metrics` mutates the document it is handed (it synthesises `unit_economics.ltv` when the
    drivers allow), so a fingerprint taken afterwards describes something that was never on disk. The
    verifier hashes the file, so the two cannot agree — and the fixture used above does not happen to
    trigger the synthesis, which is exactly why the round-trip alone is not enough.
    """
    for producer, compute in (("unit_economics.py", "_compute_metrics("), ("runway.py", "_compute_runway(")):
        with open(os.path.join(_SCRIPTS, producer), encoding="utf-8") as fh:
            body = fh.read()
        capture = body.find("_fp_inputs = _fingerprint.fingerprint(")
        assert capture != -1, f"{producer} does not capture the inputs fingerprint at parse time"
        first_compute = body.find(f"    result = {compute}")
        if first_compute == -1:
            first_compute = body.find(compute, body.find("def main("))
        assert first_compute != -1, f"{producer}: could not locate its compute call"
        assert capture < first_compute, (
            f"{producer} fingerprints the inputs AFTER {compute} — if that compute mutates its "
            f"argument, the stamp describes a document that never existed on disk"
        )
        assert "_fingerprint.stamp_hashes(" in body, (
            f"{producer} must stamp the precomputed hash, not re-hash a possibly-mutated document"
        )


# ---------------------------------------------------------------------------
# Fabrication resistance
#
# A live run cleared this gate by editing the artifact it protects. These pin the three responses:
# deleting the stamp is an error, the remedy is per-artifact and cascade-aware, and one value-level
# fact survives a forged stamp.
# ---------------------------------------------------------------------------


def test_deleting_the_stamp_is_an_error_not_a_silent_skip() -> None:
    """Removing `graded_against` was the CHEAPEST way to clear this gate — cheaper than forging a
    64-char hash. Measured before this branch existed: wrong hash failed, deleted stamp passed clean."""
    arts = _full_artifacts()
    arts["unit_economics.json"]["graded_against"] = {}  # present but empty: the key was removed
    rc, out, _err = _run(arts)
    text = json.dumps(out)
    assert "carries no record of the inputs" in text
    assert out["status"] == "fail"
    assert rc == 1


@pytest.mark.parametrize(
    ("artifact", "must_contain", "must_not_contain"),
    [
        ("unit_economics.json", "unit_economics.py", "re-dispatch"),
        ("runway.json", "runway.py", "re-dispatch"),
        # Re-piping the old hand-off with new inputs would stamp a CURRENT fingerprint over
        # judgements made from the OLD inputs — manufacturing the false claim this gate prevents.
        ("checklist.json", "re-dispatch the CHECKLIST sub-agent", "cat <dir>/inputs.json"),
    ],
)
def test_the_remedy_is_per_artifact(artifact: str, must_contain: str, must_not_contain: str) -> None:
    arts = _full_artifacts()
    arts[artifact]["graded_against"] = {"inputs.json": "0" * 64}
    _rc, out, _err = _run(arts)
    msg = next(e for e in out["summary"]["errors"] if e.startswith(artifact))
    assert must_contain in msg
    assert must_not_contain not in msg


def test_the_remedy_names_the_downstream_recompose() -> None:
    """This gate runs AFTER compose, so re-running only the producer leaves a stale report shipped."""
    arts = _full_artifacts()
    arts["runway.json"]["graded_against"] = {"inputs.json": "0" * 64}
    _rc, out, _err = _run(arts)
    assert "compose_report.py" in json.dumps(out)


def test_the_remedy_covers_the_survives_a_rerun_case() -> None:
    """The branch the incident actually needed: the agent ran the remedy, watched it fail, and patched."""
    arts = _full_artifacts()
    arts["runway.json"]["graded_against"] = {"inputs.json": "0" * 64}
    _rc, out, _err = _run(arts)
    text = json.dumps(out)
    assert "stop and report the gate as defective" in text
    assert "Never edit graded_against" in text


def test_a_forged_stamp_does_not_hide_a_stale_runway() -> None:
    """The value-level arm is independent of the stamp, so patching the hash leaves it standing.

    PARTIAL by design: unit_economics would need the producer's math re-implemented here, and
    checklist.json is uncoverable — its content is LLM-judged, not derivable from inputs.
    """
    arts = _full_artifacts()
    arts["inputs.json"] = json.loads(json.dumps(arts["inputs.json"]))
    # An 8% correction: inside the 20% tolerance, so only the exact arm can see it.
    arts["inputs.json"]["cash"]["current_balance"] = 1_080_000
    forged = _fingerprint_of(arts["inputs.json"])
    for name in ("checklist.json", "unit_economics.json", "runway.json"):
        arts[name]["graded_against"] = {"inputs.json": forged}
    _rc, out, _err = _run(arts)
    errors = " ".join(out["summary"]["errors"])
    assert "does not equal inputs net cash" in errors, "a forged stamp hid a stale artifact"
    assert "runway.json" not in errors or "different version of the inputs" not in errors


def test_the_exact_arm_does_not_fire_on_the_degenerate_runway_branch() -> None:
    """runway.py's insufficient-data branch reports net_cash WITHOUT subtracting debt (runway.py:675),
    so exact equality legitimately fails there. Gating on monthly_burn keeps it off that path."""
    arts = _full_artifacts()
    arts["inputs.json"] = json.loads(json.dumps(arts["inputs.json"]))
    arts["inputs.json"]["cash"]["debt"] = 50_000
    arts["runway.json"]["baseline"] = {"net_cash": 1_000_000, "monthly_burn": None, "monthly_revenue": None}
    _rc, out, _err = _run(arts)
    assert "does not equal inputs net cash" not in json.dumps(out)


# ---------------------------------------------------------------------------
# Recomputation: ask "would this artifact be different if rebuilt?" not "were the bytes identical?"
# ---------------------------------------------------------------------------


def _producer_output(module_name: str, func_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Build an artifact the way the producer would, for tests about recomputation.

    The hand-authored fixtures carry values no producer emits — deliberately, to exercise the
    verifier's other checks. A test about "would this rebuild identically?" cannot use one.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, os.path.join(_SCRIPTS, f"{module_name}.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(getattr(mod, func_name)(json.loads(json.dumps(inputs))))


def _bump(doc: dict[str, Any], path: tuple[str, ...], factor: float = 1.08) -> dict[str, Any]:
    doc = json.loads(json.dumps(doc))
    node = doc
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = round(node[path[-1]] * factor, 2)
    return doc


def test_an_input_change_that_moves_no_metric_is_not_reported_stale() -> None:
    """The false-alarm class that produced the artifact-patching incident.

    Correcting cash moves no unit-economics metric, so that artifact is current in every way a founder
    can see. Reporting it stale — with no remedy that clears it — is what invites editing the artifact.
    """
    arts = _full_artifacts()
    # Genuine producer output: the suppression asks "would this rebuild identically?", which only has
    # meaning for an artifact the producer actually emitted.
    arts["unit_economics.json"] = _producer_output("unit_economics", "_compute_metrics", arts["inputs.json"])
    stale_stamp = {"inputs.json": _fingerprint_of(arts["inputs.json"])}  # BEFORE the correction
    arts["inputs.json"] = _bump(arts["inputs.json"], ("cash", "current_balance"))
    for name in ("unit_economics.json", "runway.json"):
        arts[name]["graded_against"] = dict(stale_stamp)
    _rc, out, _err = _run(arts)
    flagged = [e for e in out["summary"]["errors"] if e.startswith("unit_economics.json")]
    assert not flagged, f"unit_economics reported stale though no metric changed: {flagged}"
    # Non-vacuity: the hash DID move, so the suppression is what cleared it — runway, which cash does
    # affect, is still reported.
    assert [e for e in out["summary"]["errors"] if e.startswith("runway.json")]


def test_an_input_change_that_does_move_a_metric_is_reported() -> None:
    """Non-vacuity for the test above: the suppression must not be blanket."""
    arts = _full_artifacts()
    arts["unit_economics.json"] = _producer_output("unit_economics", "_compute_metrics", arts["inputs.json"])
    stale_stamp = {"inputs.json": _fingerprint_of(arts["inputs.json"])}
    arts["inputs.json"] = _bump(arts["inputs.json"], ("revenue", "mrr", "value"))
    arts["unit_economics.json"]["graded_against"] = dict(stale_stamp)
    _rc, out, _err = _run(arts)
    assert [e for e in out["summary"]["errors"] if e.startswith("unit_economics.json")]


def test_recomputation_is_not_used_as_a_standalone_fabrication_check() -> None:
    """Scope pin. Comparing content on every run would demand every artifact be byte-identical to a
    fresh producer run — true in production, false of the deliberately artificial fixtures that
    exercise this verifier's other checks. Forged-stamp resistance comes from the net_cash comparison
    instead, which is independent of both the stamp and the producer."""
    arts = _full_artifacts()  # hand-authored values a producer would not emit
    _rc, out, _err = _run(arts)
    assert out["status"] == "pass", "an artificial-but-consistent fixture must not be reported stale"


def test_checklist_is_recorded_as_uncoverable_by_recomputation() -> None:
    """Not an oversight: 46 LLM-judged statuses that nothing in inputs.json determines. If this ever
    becomes recomputable the residual note in the module and plan must change with it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_vr", _SCRIPT)
    assert spec and spec.loader
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    assert "checklist.json" not in vr._RECOMPUTABLE
    assert set(vr._RECOMPUTABLE) == {"unit_economics.json", "runway.json"}


def test_the_recomputed_producers_expose_the_functions_the_verifier_calls() -> None:
    """Contract pin. The verifier imports private producer functions; renaming one would silently
    disable recomputation and leave only the fingerprint, with no test failing."""
    import importlib.util

    for module_name, func_name in (("unit_economics", "_compute_metrics"), ("runway", "_compute_runway")):
        spec = importlib.util.spec_from_file_location(module_name, os.path.join(_SCRIPTS, f"{module_name}.py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, func_name, None)), f"{module_name}.{func_name} is gone"


def test_runway_recompute_is_skipped_without_a_balance_date() -> None:
    """runway.py falls back to datetime.now() for a missing balance_date, so recomputing would make the
    check depend on the calendar. It must fall back to the fingerprint, not invent a verdict."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_vr", _SCRIPT)
    assert spec and spec.loader
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    inputs_no_date = json.loads(json.dumps(_INPUTS))
    inputs_no_date.get("cash", {}).pop("balance_date", None)
    assert vr._recompute("runway.json", inputs_no_date) is None
    assert vr._recompute("unit_economics.json", inputs_no_date) is not None
