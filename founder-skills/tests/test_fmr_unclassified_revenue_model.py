"""`unclassified`: the revenue model the materials do not state, and what the review does with it.

The type list is closed and the field is required, so a model or deck that never says how the
company makes money used to be forced onto the nearest value -- in practice a SaaS type, which
switches on the SaaS metric suite and grades gross margin against the SaaS table. `unclassified`
is the honest answer: the review abstains from every judgement that needs a revenue model and says
why, in founder language, on every surface that shows the judgement.

The founder-facing assertions are POSITIVE ("no revenue model" is present), not only the absence of
the token: a plain English word like "unclassified" is not an internal-token candidate for the leak
scan, so an absence check alone would pass while the founder read nothing about why.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts"

sys.path.insert(0, str(Path(__file__).parent))
from test_explore import _extract_data_payload  # noqa: E402
from test_financial_model_review import (  # noqa: E402
    _PROFILE_SPREADSHEET,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _make_checklist_items,
    _make_fmr_artifact_dir,
    _run_compose,
    run_script,
)

PHRASE = "no revenue model"
SAAS_ONLY = {"nrr", "grr", "magic_number", "rule_of_40", "arr_per_fte"}


def _unclassified_inputs(gm: float = 0.55) -> dict[str, Any]:
    inputs: dict[str, Any] = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = "unclassified"
    inputs["unit_economics"]["gross_margin"] = gm
    return inputs


def _unit_economics(inputs: dict[str, Any]) -> dict[str, Any]:
    rc, data, stderr = run_script("unit_economics.py", ["--pretty"], stdin_data=json.dumps(inputs))
    assert rc == 0, stderr
    assert data is not None
    return data


def _checklist(company: dict[str, Any]) -> tuple[dict[str, Any], str]:
    payload = json.dumps({"items": _make_checklist_items(), "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0, stderr
    assert data is not None
    return data, stderr


def _visible_text(html: str) -> str:
    """HTML minus <script>/<style> bodies and tags: what a founder reads."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


# --- the value is accepted ----------------------------------------------------------------------


def test_validator_accepts_unclassified() -> None:
    rc, data, stderr = run_script("validate_inputs.py", [], stdin_data=json.dumps(_unclassified_inputs()))
    assert data is not None, stderr
    bad = [e for e in data.get("errors", []) if "revenue_model_type" in json.dumps(e)]
    assert bad == [], f"validator rejected unclassified: {bad}"


def test_review_dropdown_offers_unclassified() -> None:
    src = (SCRIPTS / "review_inputs.py").read_text()
    line = next(ln for ln in src.splitlines() if 'createDropdown("company.revenue_model_type"' in ln)
    assert '"unclassified"' in line


# --- unit economics abstains -------------------------------------------------------------------


def test_gross_margin_is_contextual_with_a_founder_reason() -> None:
    data = _unit_economics(_unclassified_inputs(0.55))
    gm = {m["name"]: m for m in data["metrics"]}["gross_margin"]
    assert gm["rating"] == "contextual", gm
    assert PHRASE in gm["evidence"].lower(), gm["evidence"]
    assert "unclassified" not in gm["evidence"], gm["evidence"]
    assert "SaaS benchmark assumed" not in gm["evidence"]


def test_no_saas_only_metric_is_rated() -> None:
    data = _unit_economics(_unclassified_inputs())
    for m in data["metrics"]:
        if m["name"] in SAAS_ONLY:
            assert m["rating"] in ("not_applicable", "not_rated"), m


def test_positive_control_saas_type_is_still_graded() -> None:
    """The lever engaged: the same margin IS graded when a type is stated."""
    inputs = _unclassified_inputs(0.55)
    inputs["company"]["revenue_model_type"] = "saas-sales-led"
    gm = {m["name"]: m for m in _unit_economics(inputs)["metrics"]}["gross_margin"]
    assert gm["rating"] != "contextual"


# --- the checklist records the abstention, in founder language ------------------------------------


def test_checklist_marks_sector_unresolved_and_says_why() -> None:
    data, stderr = _checklist({**_PROFILE_SPREADSHEET, "revenue_model_type": "unclassified"})
    dropped = data["summary"]["unresolved_profile_exclusions"].get("sector", [])
    assert dropped, "sector-keyed criteria must be recorded as not assessed"
    by_id = {i["id"]: i for i in data["items"]}
    for crit in dropped:
        ev = str(by_id[crit].get("evidence", ""))
        assert PHRASE in ev.lower(), ev
        assert "unclassified" not in ev, ev
    assert "could not derive" not in stderr


# --- every founder surface ---------------------------------------------------------------------


def _pipeline_dir() -> str:
    inputs = _unclassified_inputs(0.55)
    checklist, _ = _checklist({**_PROFILE_SPREADSHEET, **inputs["company"], "revenue_model_type": "unclassified"})
    return _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": checklist,
            "unit_economics.json": _unit_economics(inputs),
            "runway.json": _VALID_RUNWAY,
        }
    )


def test_report_md_says_no_revenue_model_stated() -> None:
    d = _pipeline_dir()
    md_path = Path(d) / "report.md"
    rc, _data, stderr = _run_compose(d, ["--write-md", str(md_path)])
    assert rc == 0, stderr
    md = md_path.read_text()
    assert PHRASE in md.lower(), "report.md must say the materials state no revenue model"
    assert "unclassified" not in md
    assert "match your revenue model" not in md, "not-stated is not a matching failure"


def test_report_html_says_no_revenue_model_stated() -> None:
    d = _pipeline_dir()
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    text = _visible_text(out.stdout)
    assert PHRASE in text.lower()
    assert "unclassified" not in text


def test_explorer_says_no_revenue_model_stated() -> None:
    d = _pipeline_dir()
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "explore.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    html = out.stdout
    # The explorer renders metric evidence client-side from its embedded payload.
    payload = _extract_data_payload(html)
    gm = [m for m in payload["metrics"] if m.get("name") == "gross_margin" or m.get("id") == "gross_margin"]
    assert gm, "the explorer must carry the gross-margin verdict"
    assert PHRASE in json.dumps(gm).lower(), f"the explorer's GM evidence must carry the reason: {gm}"
    assert "unclassified" not in _visible_text(html)
    assert "gross_margin" not in payload.get("benchmarks", {}), "no client-side re-rating without a model"


# --- why it is unclassified: not stated, stated-but-none-fits, or not recorded ---------------------
#
# `unclassified` covers two cases a founder must be told apart: the materials never say how the company
# makes money, or they do and no benchmarked type fits (licensing royalties, advertising, ...). Telling
# the second founder to "state how the company makes money" is false. `company.unclassified_reason`
# says which; when it is absent (old inputs, an extraction that skipped it, the corrections UI) the
# wording stays hedged -- true in both cases -- and the remedy is conditional.

import pytest  # noqa: E402

_REMEDY = "state how the company makes money and this can be graded"
_CASE2_GM = "not one we have gross-margin benchmarks for"
_CASE2_CHECKS = "not one our model-specific checks cover"
_NOT_STATED = "no revenue model is stated in your materials"
_HEDGED = "no revenue model we have benchmarks for is stated"


def _reason_inputs(reason: str | None, gm: float = 0.55) -> dict[str, Any]:
    inputs = _unclassified_inputs(gm)
    if reason is not None:
        inputs["company"]["unclassified_reason"] = reason
    return inputs


def _reason_dir(reason: str | None) -> str:
    inputs = _reason_inputs(reason)
    checklist, _ = _checklist({**_PROFILE_SPREADSHEET, **inputs["company"]})
    return _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": checklist,
            "unit_economics.json": _unit_economics(inputs),
            "runway.json": _VALID_RUNWAY,
        }
    )


def _gm(reason: str | None) -> dict[str, Any]:
    gm: dict[str, Any] = {m["name"]: m for m in _unit_economics(_reason_inputs(reason))["metrics"]}["gross_margin"]
    return gm


def test_gm_unknown_reason_is_hedged_with_a_conditional_remedy() -> None:
    ev = _gm(None)["evidence"]
    assert _HEDGED in ev, ev
    assert "if your materials do not say how the company makes money" in ev, ev
    assert _REMEDY not in ev, "an unconditional remedy is false when a model WAS stated"


def test_gm_not_stated_keeps_the_remedy() -> None:
    ev = _gm("not_stated")["evidence"]
    assert _REMEDY in ev, ev


def test_gm_no_fitting_type_drops_the_remedy() -> None:
    gm = _gm("no_fitting_type")
    assert gm["rating"] == "contextual", gm
    assert _CASE2_GM in gm["evidence"], gm["evidence"]
    assert "state how" not in gm["evidence"] and PHRASE not in gm["evidence"].lower(), gm["evidence"]
    assert "is stated" not in gm["benchmark_source"], gm["benchmark_source"]


def test_reason_is_ignored_for_a_stated_benchmarked_type() -> None:
    inputs = _reason_inputs("no_fitting_type")
    inputs["company"]["revenue_model_type"] = "saas-sales-led"
    gm = {m["name"]: m for m in _unit_economics(inputs)["metrics"]}["gross_margin"]
    assert gm["rating"] != "contextual"


@pytest.mark.parametrize(
    ("reason", "want", "absent"),
    [
        (None, _HEDGED, None),
        ("not_stated", _NOT_STATED, _CASE2_CHECKS),
        ("no_fitting_type", _CASE2_CHECKS, PHRASE),
    ],
)
def test_checklist_gated_evidence_names_the_case(reason: str | None, want: str, absent: str | None) -> None:
    inputs = _reason_inputs(reason)
    data, _ = _checklist({**_PROFILE_SPREADSHEET, **inputs["company"]})
    dropped = data["summary"]["unresolved_profile_exclusions"].get("sector", [])
    assert dropped
    by_id = {i["id"]: i for i in data["items"]}
    for crit in dropped:
        ev = str(by_id[crit].get("evidence", ""))
        assert want in ev, ev
        if absent:
            assert absent not in ev.lower(), ev
        assert "unclassified" not in ev and "no_fitting_type" not in ev and "not_stated" not in ev, ev


@pytest.mark.parametrize(
    ("reason", "want", "absent"),
    [
        (None, _HEDGED, _REMEDY),
        ("not_stated", _NOT_STATED, _CASE2_CHECKS),
        ("no_fitting_type", _CASE2_CHECKS, "state how"),
    ],
)
def test_report_md_names_the_case(reason: str | None, want: str, absent: str) -> None:
    d = _reason_dir(reason)
    md_path = Path(d) / "report.md"
    rc, _data, stderr = _run_compose(d, ["--write-md", str(md_path)])
    assert rc == 0, stderr
    md = md_path.read_text()
    assert want in md.lower(), md
    assert absent not in md.lower()
    assert "unclassified" not in md and "no_fitting_type" not in md and "not_stated" not in md


@pytest.mark.parametrize(
    ("reason", "want"),
    [(None, _HEDGED), ("not_stated", _NOT_STATED), ("no_fitting_type", _CASE2_CHECKS)],
)
def test_report_html_names_the_case(reason: str | None, want: str) -> None:
    d = _reason_dir(reason)
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    text = " ".join(_visible_text(out.stdout).split())
    assert want in text.lower(), want
    assert "unclassified" not in text and "no_fitting_type" not in text
    if reason == "no_fitting_type":
        assert "state how" not in text.lower()
        assert "could not tell" not in text.lower(), "a stated model this check is not written for is not unknown"
    else:
        assert _REMEDY not in text.lower() or reason == "not_stated"


def test_explorer_gm_names_case_two() -> None:
    d = _reason_dir("no_fitting_type")
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "explore.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    payload = _extract_data_payload(out.stdout)
    gm = [m for m in payload["metrics"] if m.get("name") == "gross_margin" or m.get("id") == "gross_margin"]
    blob = json.dumps(gm)
    assert _CASE2_GM in blob, blob
    assert "state how" not in blob


def test_coaching_payload_does_not_depend_on_the_reason() -> None:
    """Forward guard, not a proof: the case only changes report wording, never the coach's payload.

    If this starts failing, the reason reached the payload builder's call graph, and CLAUDE.md's
    one-paid-lane-per-changed-payload-builder rule applies.
    """
    masked = ("insertion_marker", "review_dir", "report_path")
    payloads = []
    for reason in (None, "not_stated", "no_fitting_type"):
        rc, data, stderr = _run_compose(_reason_dir(reason))
        assert rc == 0 and data is not None, stderr
        p = dict(data["coaching_payload"])
        for k in masked:
            p.pop(k, None)
        payloads.append(json.dumps(p, sort_keys=True))
    assert payloads[0] == payloads[1] == payloads[2]


@pytest.mark.parametrize("reason", ["not_stated", "no_fitting_type"])
def test_validator_accepts_each_reason(reason: str) -> None:
    rc, data, stderr = run_script("validate_inputs.py", [], stdin_data=json.dumps(_reason_inputs(reason)))
    assert data is not None, stderr
    bad = [e for e in data.get("errors", []) + data.get("warnings", []) if "unclassified_reason" in json.dumps(e)]
    assert bad == [], bad


def test_validator_rejects_an_unknown_reason() -> None:
    rc, data, stderr = run_script("validate_inputs.py", [], stdin_data=json.dumps(_reason_inputs("N/A")))
    assert data is not None, stderr
    assert any(e.get("code") == "ENUM_ERROR" and "unclassified_reason" in e.get("field", "") for e in data["errors"])


def test_schema_doc_names_the_reason_field_not_agent_supplied() -> None:
    doc = (SCRIPTS.parent / "references" / "schema-inputs.md").read_text()
    assert "unclassified_reason" in doc
    assert "describe the model in\n`agent_supplied`" not in doc and "describe the model in `agent_supplied`" not in doc


def test_explorer_unknown_case_keeps_the_remedy_conditional() -> None:
    payload = _extract_data_payload(
        subprocess.run(
            [sys.executable, str(SCRIPTS / "explore.py"), "--dir", _reason_dir(None)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    blob = json.dumps(
        [m for m in payload["metrics"] if m.get("name") == "gross_margin" or m.get("id") == "gross_margin"]
    )
    assert "if your materials do not say how the company makes money" in blob, blob
    assert _REMEDY not in blob


def test_a_chat_correction_can_record_the_reason() -> None:
    """The unknown case is resolved by a founder saying how they make money; the correction must land."""
    import tempfile

    inputs = _reason_inputs(None)
    with tempfile.TemporaryDirectory() as td:
        orig = Path(td) / "inputs.json"
        orig.write_text(json.dumps(inputs))
        out = Path(td) / "out"
        out.mkdir()
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_corrections.py"),
                "--original",
                str(orig),
                "--set",
                "company.unclassified_reason=no_fitting_type",
                "--output-dir",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert (
            json.loads((out / "corrected_inputs.json").read_text())["company"]["unclassified_reason"]
            == "no_fitting_type"
        )


def test_a_typo_path_is_still_refused() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        orig = Path(td) / "inputs.json"
        orig.write_text(json.dumps(_reason_inputs(None)))
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_corrections.py"),
                "--original",
                str(orig),
                "--set",
                "company.unclassified_reasn=no_fitting_type",
                "--output-dir",
                str(td),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode != 0 and "PATH_ERROR" in (r.stdout + r.stderr)


# --- report.html prints why an ungraded metric has no grade -------------------------------------


@pytest.mark.parametrize(
    ("reason", "want", "absent"),
    [
        (None, "if your materials do not say how the company makes money", _REMEDY),
        ("not_stated", _REMEDY, _CASE2_GM),
        ("no_fitting_type", _CASE2_GM, "state how"),
    ],
)
def test_report_html_prints_the_gross_margin_reason(reason: str | None, want: str, absent: str) -> None:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", _reason_dir(reason)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    text = " ".join(_visible_text(out.stdout).split()).lower()
    assert want in text, want
    assert absent not in text
    assert "gross margin of 55%;" not in text, "the row already shows the figure; print only the reason"


def test_stray_spaces_in_the_model_type_are_read_as_unclassified() -> None:
    """unit_economics trims the type as checklist and compose do, so the three readers agree."""
    inputs = _reason_inputs("no_fitting_type")
    inputs["company"]["revenue_model_type"] = " Unclassified "
    gm = {m["name"]: m for m in _unit_economics(inputs)["metrics"]}["gross_margin"]
    assert gm["rating"] == "contextual", gm


@pytest.mark.parametrize(
    ("reason", "suffix"),
    [
        (None, "not assessed because no revenue model we have benchmarks for is stated"),
        ("not_stated", "not assessed because no revenue model is stated"),
        ("no_fitting_type", None),
    ],
)
def test_saas_only_metrics_do_not_imply_the_company_is_not_saas(reason: str | None, suffix: str | None) -> None:
    """'NRR applies to SaaS models only' implies 'you are not SaaS', known only when a stated model fits no type."""
    saas_only = [m for m in _unit_economics(_reason_inputs(reason))["metrics"] if m["name"] in SAAS_ONLY]
    assert saas_only
    for m in saas_only:
        if suffix:
            assert suffix in m["evidence"], m
        else:
            assert "not assessed because" not in m["evidence"], m


# --- an unclassified model with no reason is noted, never blocking -----------------------------------


def _validator(inputs: dict[str, Any]) -> dict[str, Any]:
    rc, data, stderr = run_script("validate_inputs.py", [], stdin_data=json.dumps(inputs))
    assert data is not None, stderr
    return data


def test_validator_notes_an_unclassified_model_with_no_reason_without_blocking() -> None:
    """Leaving the reason out when unsure is what the schema asks, so the note must not stop Step 3.5."""
    data = _validator(_reason_inputs(None))
    notes = [w for w in data["warnings"] if w["code"] == "UNCLASSIFIED_REASON_NOT_RECORDED"]
    assert len(notes) == 1
    assert notes[0]["layer"] == 4 and notes[0]["severity"] == "info" and not notes[0].get("critical")
    assert data["has_critical_warnings"] is False


@pytest.mark.parametrize("reason", ["not_stated", "no_fitting_type"])
def test_validator_has_no_note_when_the_reason_is_recorded(reason: str) -> None:
    codes = [w["code"] for w in _validator(_reason_inputs(reason))["warnings"]]
    assert "UNCLASSIFIED_REASON_NOT_RECORDED" not in codes


def test_validator_has_no_note_for_a_classified_model() -> None:
    inputs = _reason_inputs(None)
    inputs["company"]["revenue_model_type"] = "saas-sales-led"
    assert "UNCLASSIFIED_REASON_NOT_RECORDED" not in [w["code"] for w in _validator(inputs)["warnings"]]
