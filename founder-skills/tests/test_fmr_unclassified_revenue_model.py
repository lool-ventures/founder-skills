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
