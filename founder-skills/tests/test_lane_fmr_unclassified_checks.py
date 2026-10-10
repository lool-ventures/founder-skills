"""The financial-model-review unclassified lane's assertion code, against hand-built artifacts.

Free: nothing here calls the model. The paid lane (`test_e2e_financial_model_review.py::
test_financial_model_review_unclassified_lane`, opt-in) asks whether a real run writes
`company.revenue_model_type: "unclassified"` with a `company.unclassified_reason` for a licensing and
royalty model that names no revenue model type. Its checks are settled here before anyone pays: each passes
on artifacts where the finding holds and names the failure where it does not. Also pins the fixture and the
opt-in, which no paid run would otherwise show to be wired.

Not named `test_e2e_*`: the lane count is pinned, and this file runs in the default suite.
"""

from __future__ import annotations

import csv
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def lane() -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location("_uncl_test_e2e_fmr", TESTS / "test_e2e_financial_model_review.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _inputs(model: Any = "unclassified", reason: Any = "no_fitting_type") -> dict[str, Any]:
    company: dict[str, Any] = {"revenue_model_type": model}
    if reason is not None:
        company["unclassified_reason"] = reason
    return {"company": company}


@pytest.mark.parametrize("reason", ["not_stated", "no_fitting_type"])
def test_the_measurement_passes_on_either_reason(lane: Any, reason: str) -> None:
    assert lane.unclassified_measurement_problems(_inputs(reason=reason)) == []


@pytest.mark.parametrize(
    "inputs, needle",
    [
        (_inputs(model="saas-sales-led", reason=None), "'saas-sales-led'"),
        (_inputs(model=None, reason=None), "None"),
        (_inputs(reason=None), "unclassified_reason is None"),
        (_inputs(reason="made_up"), "'made_up'"),
        ({}, "None"),
        ({"company": "not a dict"}, "None"),
    ],
)
def test_the_measurement_names_what_the_run_wrote(lane: Any, inputs: dict[str, Any], needle: str) -> None:
    problems = lane.unclassified_measurement_problems(inputs)
    assert len(problems) == 1 and needle in problems[0], problems


_CLEAN_CHECKLIST = {"summary": {"unresolved_profile_exclusions": {"sector": ["SECTOR_39"]}}}


def _ue(**ratings: str) -> dict[str, Any]:
    return {"metrics": [{"id": k, "rating": v} for k, v in ratings.items()]}


def test_saas_grading_passes_when_saas_only_metrics_are_ungraded(lane: Any) -> None:
    ue = _ue(nrr="not_rated", magic_number="contextual", burn_multiple="strong")  # burn multiple is not SaaS-only
    assert lane.saas_grading_problems(ue, _CLEAN_CHECKLIST) == []


def test_saas_grading_names_a_graded_saas_only_metric(lane: Any) -> None:
    problems = lane.saas_grading_problems(_ue(rule_of_40="warning", grr="not_rated"), _CLEAN_CHECKLIST)
    assert len(problems) == 1 and "'rule_of_40'" in problems[0], problems


@pytest.mark.parametrize(
    "checklist", [{}, {"summary": {}}, {"summary": {"unresolved_profile_exclusions": {}}}, {"summary": []}]
)
def test_saas_grading_requires_the_sector_criteria_recorded_as_unassessed(lane: Any, checklist: Any) -> None:
    problems = lane.saas_grading_problems(_ue(), checklist)
    assert len(problems) == 1 and "unassessed" in problems[0], problems


def test_every_graded_rating_is_one_unit_economics_grades(lane: Any) -> None:
    """The lane's list of grades is the producer's own (`_graded` in unit_economics.py), read from its source."""
    src = (TESTS.parent / "skills" / "financial-model-review" / "scripts" / "unit_economics.py").read_text()
    assert '_graded = ("strong", "acceptable", "warning", "fail")' in src
    assert {"strong", "acceptable", "warning", "fail"} == lane._GRADED_RATINGS
    for metric in lane._SAAS_ONLY_METRIC_IDS:
        assert f'"{metric}"' in src.split("_SAAS_ONLY_METRICS = ", 1)[1].split("\n", 1)[0], metric


def test_the_fixture_is_a_licensing_model_naming_no_revenue_model_type() -> None:
    path = TESTS / "fixtures" / "models" / "synthetic-licensing-model.csv"
    text = path.read_text(encoding="utf-8")
    assert "synthetic; not a real company" in text.splitlines()[0]
    rows = list(csv.reader(text.splitlines()[1:]))
    header, body = rows[0], rows[1:]
    assert all(len(r) == len(header) for r in body), "ragged rows"
    items = {r[1] for r in body}
    assert {"Royalty income from licensees", "Total revenue", "Monthly net burn", "Starting cash"} <= items
    lowered = text.lower()
    # A model that names a type is not the measurement: no SaaS vocabulary, no revenue-model row.
    for banned in ("mrr", "arr", "saas", "subscription", "revenue model", "churn", "marketplace"):
        assert banned not in lowered.replace("headcount", "").replace("harbourlight", ""), banned


def test_the_prompt_states_each_value_line_and_names_no_revenue_model(lane: Any) -> None:
    prompt = lane.UNCLASSIFIED_PROMPT_TEMPLATE.format(model_path="/workspace/model.csv")
    for _gate, _option, value in lane.UNCLASSIFIED_HOST_VALUES:
        assert value in prompt, value
    assert "saas" not in prompt.lower() and "subscription" not in prompt.lower()


def test_the_lane_is_opt_in_on_its_own_variable(lane: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert lane.UNCLASSIFIED_OPT_IN_ENV == "RUN_PAID_E2E_FMR_UNCLASSIFIED"
    monkeypatch.delenv(lane.UNCLASSIFIED_OPT_IN_ENV, raising=False)
    assert lane._unclassified_lane_authorized() is False
    for off in ("", "0", "false", "no"):
        monkeypatch.setenv(lane.UNCLASSIFIED_OPT_IN_ENV, off)
        assert lane._unclassified_lane_authorized() is False, off
    for on in ("1", "true", "YES"):
        monkeypatch.setenv(lane.UNCLASSIFIED_OPT_IN_ENV, on)
        assert lane._unclassified_lane_authorized() is True, on
    # The skip condition also needs the shared paid opt-in: the lane variable alone must not authorize a run.
    monkeypatch.delenv("RUN_PAID_E2E", raising=False)
    monkeypatch.setenv(lane.UNCLASSIFIED_OPT_IN_ENV, "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-probe-not-a-real-key")
    assert lane.has_claude_auth() is False
    assert os.environ.get("RUN_PAID_E2E") is None
