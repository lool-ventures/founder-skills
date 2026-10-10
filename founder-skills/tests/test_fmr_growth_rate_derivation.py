"""The monthly growth rate computed from the monthly revenue series at Step 3.5.

`validate_extraction.py --fix` sets `revenue.growth_rate_monthly` from `revenue.monthly[]` (the rule
lives in `_growth_rate.py`), so the figure the burn multiple and the runway read no longer depends on
how the extraction worked a compound rate out by hand. These tests run the real script on invented
series: what it replaces, what it never replaces, that a re-run leaves the file byte-identical, that a
founder's correction is kept, and that every surface says the figure was computed. Free.
"""

from __future__ import annotations

import copy
import html
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "financial-model-review" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Invented: about 14.6% a month, Mar to Aug 2025, MRR date Aug 2025.
_TOTALS = [30_000, 34_100, 39_500, 45_200, 51_800, 59_300]
_MONTHS = ["2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08"]
_EXPECTED = round((59_300 / 30_000) ** (1 / 5) - 1, 4)

_MODEL_DATA: dict[str, Any] = {
    "sheets": [
        {
            "name": "P&L",
            "headers": ["Line Item", *_MONTHS],
            "rows": [["Revenue", *_TOTALS]],
            "detected_type": "pnl",
            "periodicity": "monthly",
            "row_count": 1,
            "col_count": 7,
            "pre_header_rows": [["Example Co", None]],
            "cell_refs": [],
        }
    ],
    "source_format": "csv",
    "source_file": "model.csv",
    "periodicity_summary": "monthly",
}


def _inputs(growth: Any = 0.083, *, actual: bool = True, **company: Any) -> dict[str, Any]:
    revenue: dict[str, Any] = {
        "customers": 120,
        "monthly": [{"month": m, "actual": actual, "total": t} for m, t in zip(_MONTHS, _TOTALS, strict=True)],
        "mrr": {"value": 59_300, "as_of": "2025-08"},
        "arr": {"value": 711_600, "as_of": "2025-08"},
    }
    if growth != "absent":
        revenue["growth_rate_monthly"] = growth
    return {
        "company": {
            "company_name": "Example Co",
            "slug": "example-co",
            "stage": "seed",
            "sector": "B2B SaaS",
            "geography": "US",
            "model_format": "spreadsheet",
            "revenue_model_type": "saas-sales-led",
            **company,
        },
        "revenue": revenue,
        "cash": {"current_balance": 2_000_000, "monthly_net_burn": 30_000, "balance_date": "2025-08"},
        "metadata": {"run_id": "r1"},
    }


def _fix(review_dir: Path, inputs: dict[str, Any] | None = None, model_data: Any = _MODEL_DATA) -> dict[str, Any]:
    """Run `validate_extraction.py --fix` in `review_dir` (writing `inputs` first when given)."""
    review_dir.mkdir(parents=True, exist_ok=True)
    if inputs is not None:
        (review_dir / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    if model_data is not None:
        (review_dir / "model_data.json").write_text(json.dumps(model_data), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "validate_extraction.py"),
            "--inputs",
            str(review_dir / "inputs.json"),
            "--model-data",
            str(review_dir / "model_data.json"),
            "--fix",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def _read(review_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((review_dir / "inputs.json").read_text(encoding="utf-8"))
    return data


def _growth_row(result: dict[str, Any]) -> dict[str, Any] | None:
    return next((c for c in result.get("checks", []) if c.get("id") == "GROWTH_RATE_DERIVED"), None)


def _burn_multiple(inputs: dict[str, Any]) -> Any:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "unit_economics.py")],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        check=True,
    )
    metrics = json.loads(proc.stdout)["metrics"]
    return next(m["value"] for m in metrics if m["name"] == "burn_multiple")


def _escaped(text: str) -> str:
    return html.escape(text, quote=True)


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"fmr_growth_test_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- one figure, however the extraction worked it out ---------------------------------------------


def test_three_hand_computed_rates_become_one_and_give_one_burn_multiple(tmp_path: Path) -> None:
    """The variants kept runs stored for one series (a slip, a 3-month and a 5-month rate) converge."""
    burn_multiples = set()
    for i, stored in enumerate((0.083, 0.1427, 0.147)):
        _fix(tmp_path / str(i), _inputs(stored))
        fixed = _read(tmp_path / str(i))
        assert fixed["revenue"]["growth_rate_monthly"] == _EXPECTED
        marker = fixed["metadata"]["growth_rate_derivation"]
        assert marker == {
            "method": "compound_monthly_growth",
            "basis": "total",
            "from_month": "2025-03",
            "to_month": "2025-08",
            "intervals": 5,
            "value": _EXPECTED,
            "replaced": stored,
        }
        burn_multiples.add(_burn_multiple(fixed))
    assert len(burn_multiples) == 1 and None not in burn_multiples


def test_an_absent_rate_is_computed(tmp_path: Path) -> None:
    _fix(tmp_path, _inputs("absent"))
    fixed = _read(tmp_path)
    assert fixed["revenue"]["growth_rate_monthly"] == _EXPECTED
    assert fixed["metadata"]["growth_rate_derivation"]["replaced"] is None


def test_months_flagged_as_projections_still_count(tmp_path: Path) -> None:
    """Runs have flagged every historical month `actual: false`; the window is keyed on the MRR date."""
    _fix(tmp_path, _inputs(0.2, actual=False))
    assert _read(tmp_path)["revenue"]["growth_rate_monthly"] == _EXPECTED


def test_the_window_is_the_last_six_months_ending_at_the_mrr_date(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    # Earlier months and a projected month after the MRR date are outside the window.
    inputs["revenue"]["monthly"] = [
        {"month": "2024-12", "actual": True, "total": 10_000},
        {"month": "2025-01", "actual": True, "total": 20_000},
        {"month": "2025-02", "actual": True, "total": 25_000},
        *inputs["revenue"]["monthly"],
        {"month": "2025-09", "actual": False, "total": 90_000},
    ]
    _fix(tmp_path, inputs)
    marker = _read(tmp_path)["metadata"]["growth_rate_derivation"]
    assert (marker["from_month"], marker["to_month"], marker["intervals"]) == ("2025-02", "2025-08", 6)
    assert marker["value"] == round((59_300 / 25_000) ** (1 / 6) - 1, 4)


def test_a_month_without_revenue_does_not_shorten_the_exponent(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"][2]["total"] = 0
    _fix(tmp_path, inputs)
    marker = _read(tmp_path)["metadata"]["growth_rate_derivation"]
    assert marker["intervals"] == 5, "the calendar span, not the count of months with revenue"
    assert marker["value"] == _EXPECTED


def test_a_dip_inside_the_window_is_smoothed_by_the_compound_rate(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"][3]["total"] = 28_000
    _fix(tmp_path, inputs)
    assert _read(tmp_path)["revenue"]["growth_rate_monthly"] == _EXPECTED


def test_the_run_rate_is_used_when_both_ends_carry_one(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"][0]["arr"] = 300_000
    inputs["revenue"]["monthly"][-1]["arr"] = 720_000
    _fix(tmp_path, inputs)
    marker = _read(tmp_path)["metadata"]["growth_rate_derivation"]
    assert marker["basis"] == "arr"
    assert marker["value"] == round((720_000 / 300_000) ** (1 / 5) - 1, 4)


def test_one_end_with_a_run_rate_uses_the_totals_for_both(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"][-1]["arr"] = 720_000
    _fix(tmp_path, inputs)
    marker = _read(tmp_path)["metadata"]["growth_rate_derivation"]
    assert (marker["basis"], marker["value"]) == ("total", _EXPECTED)


# ---- what is never replaced ----------------------------------------------------------------------


def _unchanged(review_dir: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    result = _fix(review_dir, inputs)
    after = _read(review_dir)
    assert after == inputs
    assert _growth_row(result) is None
    return after


@pytest.mark.parametrize("stored", [None, 0.0, 0, -0.02, True])
def test_a_null_zero_or_negative_rate_is_kept(tmp_path: Path, stored: Any) -> None:
    _unchanged(tmp_path, _inputs(stored))


def test_a_project_builder_gets_no_rate(tmp_path: Path) -> None:
    _unchanged(tmp_path, _inputs(0.2, revenue_model_type="project-builder"))
    _unchanged(tmp_path / "absent", _inputs("absent", revenue_model_type="project-builder"))


@pytest.mark.parametrize("months", [3, 1])
def test_too_few_months_up_to_the_mrr_date(tmp_path: Path, months: int) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"] = inputs["revenue"]["monthly"][-months:]
    _unchanged(tmp_path, inputs)


def test_a_projection_only_series_starting_at_the_mrr_date(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"] = [
        {"month": f"2025-{m:02d}", "actual": False, "total": 59_300 + 1_000 * i} for i, m in enumerate(range(8, 13))
    ]
    _unchanged(tmp_path, inputs)


def test_a_series_that_stops_before_the_mrr_date(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["mrr"]["as_of"] = "2025-10"
    _unchanged(tmp_path, inputs)


def test_no_revenue_in_the_mrr_month(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    inputs["revenue"]["monthly"][-1]["total"] = 0
    _unchanged(tmp_path, inputs)


def test_with_no_mrr_date_the_balance_date_ends_the_window(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    del inputs["revenue"]["mrr"]["as_of"]
    _fix(tmp_path, inputs)
    assert _read(tmp_path)["revenue"]["growth_rate_monthly"] == _EXPECTED
    neither = _inputs(0.2)
    del neither["revenue"]["mrr"]["as_of"]
    del neither["cash"]["balance_date"]
    _unchanged(tmp_path / "neither", neither)


def test_a_flat_series_is_not_written_as_zero(tmp_path: Path) -> None:
    """A stored 0.0 with revenue is a critical warning at Step 3.5; a computed zero is not written."""
    inputs = _inputs(0.01)
    for entry in inputs["revenue"]["monthly"]:
        entry["total"] = 59_300
    _unchanged(tmp_path, inputs)


def test_a_conversational_model_is_skipped(tmp_path: Path) -> None:
    _unchanged(tmp_path, _inputs(0.2, model_format="conversational"))


def test_no_extraction_means_no_rate(tmp_path: Path) -> None:
    inputs = _inputs(0.2)
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    _fix(tmp_path, None, model_data=None)
    assert _read(tmp_path) == inputs


# ---- re-runs and the founder's correction ---------------------------------------------------------


def test_a_rerun_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    """The values gate re-asks on any change to inputs.json, so a re-run on the same inputs writes nothing."""
    _fix(tmp_path, _inputs(0.083))
    first = (tmp_path / "inputs.json").read_bytes()
    result = _fix(tmp_path)
    assert (tmp_path / "inputs.json").read_bytes() == first
    row = _growth_row(result)
    assert row is not None and row["action"] == "unchanged"


@pytest.mark.parametrize("corrected", [0.12, None])
def test_a_founder_corrected_rate_is_kept(tmp_path: Path, corrected: Any) -> None:
    _fix(tmp_path, _inputs(0.083))
    after_fix = _read(tmp_path)
    after_fix["revenue"]["growth_rate_monthly"] = corrected
    (tmp_path / "inputs.json").write_text(json.dumps(after_fix, indent=2), encoding="utf-8")
    before = (tmp_path / "inputs.json").read_bytes()
    result = _fix(tmp_path)
    assert (tmp_path / "inputs.json").read_bytes() == before
    row = _growth_row(result)
    assert row is not None and row["action"] == "founder_value_kept"
    assert "corrected figure is kept" in row["message"]


def test_a_founder_edit_to_the_series_recomputes_the_rate(tmp_path: Path) -> None:
    _fix(tmp_path, _inputs(0.083))
    edited = _read(tmp_path)
    edited["revenue"]["monthly"][-1]["total"] = 62_000
    _fix(tmp_path, edited)
    after = _read(tmp_path)
    assert after["revenue"]["growth_rate_monthly"] == round((62_000 / 30_000) ** (1 / 5) - 1, 4)
    assert after["metadata"]["growth_rate_derivation"]["replaced"] == 0.083, "the original estimate is kept"


def test_the_derivation_never_turns_the_result_into_a_warning(tmp_path: Path) -> None:
    result = _fix(tmp_path, _inputs(0.083))
    row = _growth_row(result)
    assert row is not None and row["status"] == "info"
    assert result["status"] == ("warn" if any(c["status"] == "warn" for c in result["checks"]) else "pass")
    assert result["summary"]["total"] == len(result["checks"])
    assert result["summary"]["info"] == 1


# ---- every surface says the figure was computed ---------------------------------------------------


def _computed_inputs(tmp_path: Path) -> dict[str, Any]:
    _fix(tmp_path, _inputs(0.083))
    return _read(tmp_path)


def test_the_disclosure_names_the_rate_the_window_and_the_estimate(tmp_path: Path) -> None:
    sentence = _load("_growth_rate").disclosure(_computed_inputs(tmp_path))
    assert sentence == (
        f"Monthly growth of {_EXPECTED * 100:.1f}% was computed from your monthly revenue, Mar 2025 to Aug 2025, "
        f"in place of an earlier estimate of {0.083 * 100:.1f}%."
    )
    assert "MRR" not in sentence


def test_report_md_html_and_explorer_carry_the_disclosure(tmp_path: Path) -> None:
    inputs = _computed_inputs(tmp_path / "run")
    sentence = _load("_growth_rate").disclosure(inputs)
    assert sentence
    summary = _load("compose_report")._section_executive_summary(inputs, None, None, None)
    assert f"**Monthly Growth:** {sentence}" in summary
    page = _load("visualize").compose_html(str(tmp_path / "run"))
    assert sentence in page
    explore = _load("explore")
    data = explore._build_data_payload(inputs, None, None, None, None, stub_reasons={})
    explorer = explore._generate_html(data)
    assert "<div class='growth-note'" in explorer and _escaped(sentence) in explorer
    assert sentence not in explorer.split("const DATA", 1)[1], "server-rendered, not embedded in the payload"


def test_no_disclosure_once_the_founder_corrected_the_rate(tmp_path: Path) -> None:
    inputs = _computed_inputs(tmp_path)
    inputs["revenue"]["growth_rate_monthly"] = 0.12
    assert _load("_growth_rate").disclosure(inputs) is None
    assert "Monthly Growth" not in _load("compose_report")._section_executive_summary(inputs, None, None, None)
    explore = _load("explore")
    explorer = explore._generate_html(explore._build_data_payload(inputs, None, None, None, None, stub_reasons={}))
    assert "growth-note" not in explorer


def test_the_review_page_shows_the_computed_rate_in_a_neutral_card(tmp_path: Path) -> None:
    """An info row renders on its own (a passing extraction used to render no banner at all), never in red."""
    inputs = _computed_inputs(tmp_path)
    row = _growth_row(_fix(tmp_path))
    assert row is not None
    info_only = {"status": "pass", "checks": [row], "summary": {"total": 1, "info": 1}}
    page = _load("review_inputs")._build_html(copy.deepcopy(inputs), extraction_warnings=info_only, is_static=True)
    info_at = page.index("extraction-info-card")
    card = page[info_at : page.index("</div>", info_at)]
    assert "computed value, not a problem" in card
    assert "lool-danger" not in card
    assert "Extraction Warnings" not in page
    beside_a_warning = dict(info_only, status="warn", checks=[{"id": "X", "status": "warn", "message": "check"}, row])
    page = _load("review_inputs")._build_html(
        copy.deepcopy(inputs), extraction_warnings=beside_a_warning, is_static=True
    )
    assert "Extraction Warnings" in page and "extraction-info-card" in page


def test_the_rule_lives_in_a_registered_scoring_file() -> None:
    """The window and minimum decide a graded figure, so a change to them must be declared at release."""
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "fmr_scoring_check", repo / ".github" / "scripts" / "scoring_changes_check.py"
    )
    assert spec is not None and spec.loader is not None
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    assert (
        "founder-skills/skills/financial-model-review/scripts/_growth_rate.py"
        in check.SCORING_FILES["financial-model-review"]
    )
    rule = _load("_growth_rate")
    assert (rule.K_MAX, rule.N_MIN) == (6, 4)
