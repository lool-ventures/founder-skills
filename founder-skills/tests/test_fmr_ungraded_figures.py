"""What a financial model review says about figures it shows without a grade.

- The headline count is over GRADED figures only. A business no bar fits (a project builder, a
  marketplace) has nothing graded by design, so "0/6" read as a failing score; the card says how many
  figures are shown and that none is graded, and report.md's summary line says the same.
- Wherever the explorer drops a bar for a figure the review did not grade, it prints the review's
  reason in that cell instead of a dash (a SaaS company below $500K ARR, whose burn multiple is not
  assessed at that size, included).
- The benchmark-age note counts only figures graded on a benchmark (or carrying a reference grade).
- Plain words: no raw rating enum, no "0.0" for a figure with no value, no field names.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_explore import _extract_data_payload  # noqa: E402
from test_financial_model_review import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _VALID_UNIT_ECONOMICS,
    _make_fmr_artifact_dir,
    _run_compose,
    run_script,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "financial-model-review" / "scripts"
_GRADED = {"strong", "acceptable", "warning", "fail"}
_TODAY = "2026-10-01"
_FIELD_TOKEN = re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z]+\.[a-z_]+\b")


def _inputs(model_type: str, *, arr: float | None = None, **ue_fields: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = model_type
    if arr is not None:
        inputs["revenue"]["arr"]["value"] = arr
        inputs["revenue"]["mrr"]["value"] = arr / 12
    inputs["unit_economics"].update(ue_fields)
    return inputs


def _ue(inputs: dict[str, Any]) -> dict[str, Any]:
    rc, data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    assert data is not None
    return data


# The four shapes the headline has to read right for. Invented figures.
_CASES: dict[str, dict[str, Any]] = {
    "project-builder": {"model_type": "project-builder"},
    "marketplace": {"model_type": "marketplace"},
    "saas-graded": {"model_type": "saas-sales-led"},
    "saas-small": {"model_type": "saas-sales-led", "arr": 300_000},
}


def _case_dir(case: str) -> str:
    spec = dict(_CASES[case])
    inputs = _inputs(spec.pop("model_type"), **spec)
    return _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": _ue(inputs),
            "runway.json": _VALID_RUNWAY,
        }
    )


def _run(script: str, d: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def _visible_text(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _ue_card(html: str) -> tuple[str, str]:
    """(value, whole visible text) of the Unit Economics headline card."""
    start = html.index('<div class="label">Unit Economics</div>')
    end = html.find('<div class="summary-card"', start)
    card = html[start : end if end != -1 else start + 2000]
    m = re.search(r'class="value"[^>]*>([^<]*)<', card)
    assert m, card
    return m.group(1).strip(), _visible_text(card)


def _summary_line(case: str) -> str:
    d = _case_dir(case)
    md_path = Path(d) / "report.md"
    rc, _data, stderr = _run_compose(d, ["--write-md", str(md_path), "--today", _TODAY])
    assert rc == 0, stderr
    lines = [ln for ln in md_path.read_text().splitlines() if ln.startswith("**Summary:**")]
    assert len(lines) == 1, lines
    return lines[0]


# --- the headline count ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["project-builder", "marketplace"])
def test_the_card_shows_no_ratio_when_nothing_is_graded(case: str) -> None:
    value, text = _ue_card(_run("visualize.py", _case_dir(case)))
    assert not re.match(r"^0/\d", value), (value, text)
    assert value == "—", (value, text)
    assert "6 figures shown; none graded for this business" in text, text


@pytest.mark.parametrize(("case", "ratio", "ungraded"), [("saas-graded", "5/6", 4), ("saas-small", "3/5", 4)])
def test_the_card_counts_graded_figures_only(case: str, ratio: str, ungraded: int) -> None:
    value, text = _ue_card(_run("visualize.py", _case_dir(case)))
    assert value == ratio, (value, text)
    assert f"{ungraded} shown without a grade" in text, text


@pytest.mark.parametrize("case", ["project-builder", "marketplace"])
def test_the_summary_line_says_nothing_is_graded(case: str) -> None:
    line = _summary_line(case)
    assert line == "**Summary:** 6 figures shown; none graded for this business, and each row says why.", line


def test_the_summary_line_counts_graded_figures_and_states_the_rest() -> None:
    line = _summary_line("saas-graded")
    assert line == (
        "**Summary:** 5 strong, 1 acceptable, 0 warning, 0 fail, of 6 graded figures; 4 shown without a grade."
    ), line


# --- the explorer: a dropped bar leaves the review's reason, not a dash ----------------------------


def _explorer(case: str) -> dict[str, Any]:
    return _extract_data_payload(_run("explore.py", _case_dir(case)))


def test_a_small_saas_burn_multiple_shows_why_it_has_no_bar() -> None:
    payload = _explorer("saas-small")
    by_id = {m["id"]: m for m in payload["metrics"]}
    bm = by_id["burn_multiple"]
    assert bm["rating"] == "not_applicable", bm
    assert "burn_multiple" not in payload["benchmarks"], sorted(payload["benchmarks"])
    assert "not meaningful below $500K ARR" in (bm.get("contextual_note") or ""), bm
    assert "not meaningful below $1M ARR" in (by_id["rule_of_40"].get("contextual_note") or ""), by_id["rule_of_40"]


def test_a_saas_only_metric_shows_why_it_has_no_bar() -> None:
    payload = _explorer("marketplace")
    by_id = {m["id"]: m for m in payload["metrics"]}
    for mid in ("nrr", "grr", "magic_number", "rule_of_40"):
        assert mid not in payload["benchmarks"], mid
        assert "applies to SaaS" in (by_id[mid].get("contextual_note") or ""), by_id[mid]


def test_the_explorer_prints_the_note_where_the_bar_would_be() -> None:
    """The cell rule the notes above depend on: no bar → the note, escaped."""
    html = _run("explore.py", _case_dir("saas-small"))
    assert "var benchStr = bench ? fmt(bench.strong) : (m.contextual_note ? escHtml(m.contextual_note) : '-');" in html


def test_a_derived_ltv_note_is_the_reason_alone() -> None:
    """LTV evidence once carried "; " inside its parenthesis, so a split on the first "; " cut the
    reason in half."""
    inputs = _inputs("marketplace", ltv={"value": 75_000})
    explore = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "explore.py"),
            "--dir",
            _make_fmr_artifact_dir(
                {"inputs.json": inputs, "unit_economics.json": _ue(inputs), "runway.json": _VALID_RUNWAY}
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert explore.returncode == 0, explore.stderr
    ltv = next(m for m in _extract_data_payload(explore.stdout)["metrics"] if m["id"] == "ltv")
    assert ltv["contextual_note"] == "LTV benchmarks vary too widely across businesses like yours to grade it", ltv


# --- the benchmark-age note counts graded figures only -------------------------------------------


def _vintage_codes(ue: dict[str, Any]) -> list[dict[str, Any]]:
    d = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": ue,
            "runway.json": _VALID_RUNWAY,
        }
    )
    rc, data, err = _run_compose(d, ["--today", "2026-08-18"])
    assert rc == 0, err
    assert data is not None
    return [w for w in data["validation"]["warnings"] if w["code"] == "BENCHMARK_VINTAGE"]


def test_the_vintage_fixture_is_graded() -> None:
    """The age tests in test_financial_model_review.py stamp every fixture metric; they still test the
    age arithmetic only while those metrics are graded."""
    assert {m["rating"] for m in _VALID_UNIT_ECONOMICS["metrics"]} <= _GRADED


@pytest.mark.parametrize("as_of", ["2024-Q4", "recent"])
def test_an_ungraded_figure_does_not_date_the_review(as_of: str) -> None:
    ue = copy.deepcopy(_VALID_UNIT_ECONOMICS)
    for m in ue["metrics"]:
        m["rating"] = "contextual"
        m["benchmark_as_of"] = as_of
    assert _vintage_codes(ue) == []


def test_a_reference_grade_still_dates_the_review() -> None:
    """The skip condition's other half: a figure with a reference grade was compared to the bar."""
    ue = copy.deepcopy(_VALID_UNIT_ECONOMICS)
    for m in ue["metrics"]:
        m["rating"] = "contextual"
        m["benchmark_reference_rating"] = "strong"
        m["benchmark_as_of"] = "2024-Q4"
    assert len(_vintage_codes(ue)) == 1


# --- plain words -----------------------------------------------------------------------------------


def test_report_html_names_a_not_applicable_rating_in_words_and_shows_no_zero() -> None:
    text = _visible_text(_run("visualize.py", _case_dir("marketplace")))
    assert "Not_Applicable" not in text, text
    assert "Not applicable" in text, text
    assert "0.0 —" not in text, text


def test_report_md_key_metrics_say_not_graded_in_words() -> None:
    d = _case_dir("project-builder")
    md_path = Path(d) / "report.md"
    rc, _data, stderr = _run_compose(d, ["--write-md", str(md_path), "--today", _TODAY])
    assert rc == 0, stderr
    key = next(ln for ln in md_path.read_text().splitlines() if ln.startswith("**Key Metrics:**"))
    assert "(contextual)" not in key, key
    assert "(not graded)" in key, key


def test_a_derived_ltv_names_no_field() -> None:
    inputs = _inputs("saas-sales-led")
    inputs["unit_economics"].pop("ltv")
    inputs["revenue"]["customers"] = 40
    ltv = next(m for m in _ue(inputs)["metrics"] if m["name"] == "ltv")
    assert ltv["value"] is not None, ltv
    assert "computed from your customer count and monthly churn" in ltv["evidence"], ltv
    assert not _FIELD_TOKEN.search(ltv["evidence"]), ltv["evidence"]
