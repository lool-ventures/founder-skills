"""`project-builder`: a business that builds large engineered systems to order, and no bar built for SaaS.

A project builder (plants, vessels, buildings, production lines) sells contract by contract, bills by
milestone or percentage of completion, and earns a thin project margin. Every unit-economics bar this
review owns for growth efficiency (burn multiple, CAC payback, LTV/CAC) is SaaS-sourced, and the device
gross-margin table would fail a healthy project margin. So for this type:

- gross margin is reported without a grade, with the public sector spread as the stated reason;
- the burn multiple, CAC payback and an observed LTV/CAC are reported without a grade, each with its
  own reason;
- the checklist reads the hardware milestones-and-capex criterion (sector `hardware`).

The drift tests at the bottom are the "no future type falls onto a SaaS bar" guard: every enum value
must sit in exactly one growth-bar set and one LTV/CAC set, and a producer run for every value must
behave as its set says.
"""

from __future__ import annotations

import ast
import datetime as _dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_explore import _extract_data_payload, _grab_js_function  # noqa: E402
from test_financial_model_review import (  # noqa: E402
    _PROFILE_SPREADSHEET,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _make_checklist_items,
    _make_fmr_artifact_dir,
    _run_compose,
    run_script,
)

SKILL = Path(__file__).resolve().parents[1] / "skills" / "financial-model-review"
SCRIPTS = SKILL / "scripts"
REFS = SKILL / "references"
ROOT_REFS = SKILL.parents[1] / "references"
PB = "project-builder"
_GRADED = {"strong", "acceptable", "warning", "fail"}
_TODAY = "2026-10-01"

_BURN_REASON = (
    "it is not graded because this benchmark measures burn against new recurring revenue, and project "
    "revenue is contracted and billed by milestone rather than recurring"
)
_PAYBACK_REASON = "it is not graded because the payback benchmark is set for subscription software contract sizes"
_LTV_CAC_REASON = (
    "it is not graded because lifetime value assumes recurring revenue from a customer, and project "
    "revenue is won contract by contract"
)


def _load(name: str, key: str) -> Any:
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ue = _load("unit_economics", "_fmr_pb_unit_economics")
compose = _load("compose_report", "_fmr_pb_compose_report")
# A thin project margin, under the device table's lowest tier, so the hardware control grades it fail.
_THIN_GM = ue.GM_BENCHMARKS_BY_SECTOR["hardware"]["warning"] * 0.75


def _enum() -> list[str]:
    tree = ast.parse((SCRIPTS / "validate_inputs.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "revenue_model_type" and isinstance(v, ast.Tuple):
                    lst = v.elts[1]
                    assert isinstance(lst, ast.List)
                    return [e.value for e in lst.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("revenue_model_type enum not found in validate_inputs.py")


_OBSERVED_LTV = {
    "value": 6000,
    "method": "formula",
    "inputs": {"arpu_monthly": 500, "gross_margin": 0.75, "churn_monthly": 0.03},
    "observed_vs_assumed": "observed",
}


def _inputs(model_type: str, **ue_fields: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = model_type
    for k in ("unclassified_reason", "stage"):
        if k in ue_fields:
            inputs["company"][k] = ue_fields.pop(k)
    inputs["unit_economics"].update(ue_fields)
    return inputs


def _ue(inputs: dict[str, Any]) -> dict[str, Any]:
    rc, data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    assert data is not None
    return data


def _metrics(model_type: str, **ue_fields: Any) -> dict[str, dict[str, Any]]:
    return {m["name"]: m for m in _ue(_inputs(model_type, **ue_fields))["metrics"]}


# --- the value is accepted, and only that spelling -------------------------------------------------


def test_validator_accepts_project_builder() -> None:
    rc, data, err = run_script("validate_inputs.py", [], stdin_data=json.dumps(_inputs(PB)))
    assert data is not None
    assert not [e for e in data.get("errors", []) if e.get("code") == "ENUM_ERROR"], data.get("errors")


@pytest.mark.parametrize("spelling", ["project_builder", "industrial-oem", "project-oem"])
def test_validator_rejects_near_spellings(spelling: str) -> None:
    _rc, data, _err = run_script("validate_inputs.py", [], stdin_data=json.dumps(_inputs(spelling)))
    assert data is not None
    assert any(e.get("code") == "ENUM_ERROR" for e in data.get("errors", [])), data


# --- checklist: the hardware milestones-and-capex criterion is assessed -----------------------------


def _checklist(model_type: str) -> tuple[dict[str, Any], str]:
    company = {**_PROFILE_SPREADSHEET, "revenue_model_type": model_type}
    payload = json.dumps({"items": _make_checklist_items({"SECTOR_41": {"status": "warn"}}), "company": company})
    rc, data, stderr = run_script("checklist.py", ["--pretty"], stdin_data=payload)
    assert rc == 0, stderr
    assert data is not None
    return data, stderr


def test_checklist_assesses_the_milestones_and_capex_criterion() -> None:
    data, stderr = _checklist(PB)
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id["SECTOR_41"]["status"] == "warn", by_id["SECTOR_41"]
    for sid in ("SECTOR_39", "SECTOR_40", "SECTOR_42", "SECTOR_43", "SECTOR_44"):
        assert by_id[sid]["status"] == "not_applicable", by_id[sid]
        assert "applies to a different sector" in by_id[sid]["evidence"], by_id[sid]
    assert not data["summary"]["unresolved_profile_exclusions"], data["summary"]
    assert "could not derive" not in stderr, stderr


def test_checklist_control_unclassified_drops_the_criterion() -> None:
    """Control: the fixture's SECTOR_41 is dropped for `unclassified`, so the test above shows the type moved it."""
    data, _ = _checklist("unclassified")
    assert {i["id"]: i for i in data["items"]}["SECTOR_41"]["status"] == "not_applicable"


# --- unit economics ---------------------------------------------------------------------------------


def test_gross_margin_is_reported_without_a_grade_and_says_why() -> None:
    gm = _metrics(PB, gross_margin=_THIN_GM)["gross_margin"]
    assert gm["rating"] == "contextual", gm
    ev = gm["evidence"]
    assert ev.startswith(f"Gross margin of {_THIN_GM:.0%}; "), ev
    assert "no single benchmark applies" in ev, ev
    assert "about 15%" in ev and "about 37%" in ev, ev
    assert "public companies" in ev, ev
    assert gm["benchmark_as_of"] == "2026-01", gm
    assert "Damodaran" in gm["benchmark_source"], gm


def test_gross_margin_control_hardware_grades_the_same_figure() -> None:
    """Control: the same margin on the device table is graded, so the type moved the grade."""
    gm = _metrics("hardware", gross_margin=_THIN_GM)["gross_margin"]
    assert gm["rating"] in _GRADED, gm


def test_burn_multiple_and_payback_each_carry_their_own_reason() -> None:
    m = _metrics(PB)
    bm, pb = m["burn_multiple"], m["cac_payback"]
    for entry in (bm, pb):
        assert entry["rating"] == "contextual", entry
        assert not entry["benchmark_source"] and not entry["benchmark_as_of"], entry
        assert entry.get("benchmark_reference") and "benchmark" not in entry, entry
        assert "stated in your materials" not in entry["evidence"], entry["evidence"]
    assert bm["evidence"].startswith("Burn multiple of "), bm["evidence"]
    assert bm["evidence"].split("; ", 1)[1] == _BURN_REASON, bm["evidence"]
    assert pb["evidence"].startswith("CAC payback of "), pb["evidence"]
    assert pb["evidence"].split("; ", 1)[1] == _PAYBACK_REASON, pb["evidence"]


def test_an_observed_ltv_cac_is_reported_without_a_grade() -> None:
    lc = _metrics(PB, ltv=dict(_OBSERVED_LTV))["ltv_cac_ratio"]
    assert lc["rating"] == "contextual", lc
    assert not lc["benchmark_source"] and not lc["benchmark_as_of"], lc
    assert lc["evidence"].startswith("LTV/CAC of "), lc["evidence"]
    assert lc["evidence"].split("; ", 1)[1] == _LTV_CAC_REASON, lc["evidence"]


@pytest.mark.parametrize("model_type", ["hardware", "unclassified"])
def test_ltv_cac_control_stays_graded(model_type: str) -> None:
    """Control: the fixture grades an observed LTV/CAC for hardware, and for `unclassified` (deliberately
    left graded there: 3:1 on gross profit per customer is not withheld for that type)."""
    lc = _metrics(model_type, ltv=dict(_OBSERVED_LTV))["ltv_cac_ratio"]
    assert lc["rating"] in _GRADED, lc
    assert lc["benchmark_source"], lc


def test_cac_and_ltv_are_contextual_with_plain_reasons() -> None:
    m = _metrics(PB)
    assert m["cac"]["rating"] == "contextual", m["cac"]
    assert "CAC benchmarks vary too widely across businesses like yours" in m["cac"]["evidence"]
    assert m["ltv"]["rating"] == "contextual", m["ltv"]
    assert "LTV benchmarks vary too widely across businesses like yours" in m["ltv"]["evidence"]


def test_saas_only_metrics_stay_not_applicable() -> None:
    m = _metrics(PB)
    for name in ("nrr", "grr", "magic_number", "rule_of_40", "arr_per_fte"):
        assert m[name]["rating"] == "not_applicable", m[name]


def test_no_evidence_names_the_type_token() -> None:
    """The founder-text scan cannot see a hyphenated token, so this is the only guard."""
    m = _metrics(PB, ltv=dict(_OBSERVED_LTV), gross_margin=_THIN_GM)
    for entry in m.values():
        assert PB not in entry["evidence"] and "project_builder" not in entry["evidence"], entry


# --- the as_of a contextual gross margin carries is a date compose can read -------------------------


def test_every_contextual_gross_margin_has_a_readable_as_of() -> None:
    keyed = set(ue._GM_CONTEXTUAL_AS_OF)
    assert keyed == set(ue._GM_CONTEXTUAL_TYPES) - {"unclassified"}, sorted(keyed)
    today = _dt.date(2026, 10, 1)
    for t, as_of in ue._GM_CONTEXTUAL_AS_OF.items():
        assert as_of == "" or compose._vintage_age_months(as_of, today) is not None, (t, as_of)


@pytest.mark.parametrize("model_type", sorted({"marketplace", "usage-based", "hardware-subscription", PB}))
def test_a_contextual_gross_margin_stamps_its_own_as_of(model_type: str) -> None:
    gm = _metrics(model_type, gross_margin=0.4)["gross_margin"]
    assert gm["rating"] == "contextual", gm
    assert gm["benchmark_as_of"] == ue._GM_CONTEXTUAL_AS_OF[model_type], gm
    assert gm["benchmark_as_of"] != "FY2024", gm


# --- compose, report.html, explorer -----------------------------------------------------------------


def _builder_dir(model_type: str = PB, *, checklist: dict[str, Any] | None = None) -> str:
    inputs = _inputs(model_type, gross_margin=_THIN_GM, ltv=dict(_OBSERVED_LTV))
    if checklist is None:
        checklist, _ = _checklist(model_type)
    return _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": checklist,
            "unit_economics.json": _ue(inputs),
            "runway.json": _VALID_RUNWAY,
        }
    )


def _visible_text(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_report_md_assesses_the_sector_and_shows_the_margin_ungraded() -> None:
    d = _builder_dir()
    md_path = Path(d) / "report.md"
    rc, data, stderr = _run_compose(d, ["--write-md", str(md_path), "--today", _TODAY])
    assert rc == 0, stderr
    assert data is not None
    md = md_path.read_text()
    codes = {w["code"] for w in data["validation"]["warnings"]}
    assert "CHECKLIST_PROFILE_UNRESOLVED" not in codes, codes
    assert "BENCHMARK_VINTAGE" not in codes, [w for w in data["validation"]["warnings"]]
    assert f"GROSS MARGIN: {_THIN_GM:.2f} (contextual)" in md, md
    assert "no single benchmark applies" in md
    assert "Not assessed" not in md
    assert PB not in md


def test_report_html_prints_the_margin_reason() -> None:
    d = _builder_dir()
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    text = _visible_text(out.stdout)
    assert "no single benchmark applies" in text, text[:2000]
    assert PB not in text


def test_explorer_carries_no_bar_and_shows_each_reason() -> None:
    d = _builder_dir()
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "explore.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    payload = _extract_data_payload(out.stdout)
    for mid in ("gross_margin", "burn_multiple", "cac_payback", "ltv_cac_ratio"):
        assert mid not in payload["benchmarks"], (mid, sorted(payload["benchmarks"]))
    notes = {m["id"]: m.get("contextual_note") for m in payload["metrics"]}
    assert "no single benchmark applies" in (notes["gross_margin"] or ""), notes
    assert notes["burn_multiple"] == _BURN_REASON, notes
    assert notes["cac_payback"] == _PAYBACK_REASON, notes
    assert notes["ltv_cac_ratio"] == _LTV_CAC_REASON, notes
    assert PB not in _visible_text(out.stdout)


def test_the_coach_payload_does_not_depend_on_the_type() -> None:
    """Forward guard: the type changes the metrics, never the coach's payload (it reads no unit
    economics and no model type). If this reds, the type reached the payload builder's call graph."""
    checklist, _ = _checklist(PB)
    masked = ("insertion_marker", "review_dir", "report_path")
    payloads = []
    for mt in (PB, "hardware"):
        rc, data, stderr = _run_compose(_builder_dir(mt, checklist=checklist), ["--today", _TODAY])
        assert rc == 0 and data is not None, stderr
        p = dict(data["coaching_payload"])
        for k in masked:
            p.pop(k, None)
        payloads.append(json.dumps(p, sort_keys=True))
    assert payloads[0] == payloads[1]


# --- the explorer: a not-applicable metric has no bar and no what-if (every type) --------------------


def _explorer_payload(model_type: str) -> dict[str, Any]:
    explore = _load("explore", "_fmr_pb_explore")
    inputs = _inputs(model_type)
    return dict(explore._build_data_payload(inputs, None, _ue(inputs), None, None, stub_reasons={}))


@pytest.mark.parametrize("model_type", ["hardware", PB, "consumer-subscription"])
def test_a_not_applicable_metric_carries_no_saas_bar(model_type: str) -> None:
    payload = _explorer_payload(model_type)
    na = {m["id"] for m in payload["metrics"] if m.get("rating") == "not_applicable"}
    assert {"nrr", "grr", "magic_number", "rule_of_40"} <= na, na
    leaked = na & set(payload["benchmarks"])
    assert not leaked, f"a not-applicable metric keeps a SaaS bar: {sorted(leaked)}"


def test_a_saas_type_keeps_its_bars_in_the_explorer() -> None:
    """Control: the SaaS stage bars still ride the payload for a SaaS business, for the metrics the review
    graded. (The fixture's Rule of 40 is not applicable below $1M ARR, so its bar goes too.)"""
    payload = _explorer_payload("saas-sales-led")
    graded = {m["id"] for m in payload["metrics"] if m.get("rating") in _GRADED}
    assert {"nrr", "grr", "magic_number"} <= graded, graded
    assert {"nrr", "grr", "magic_number"} <= set(payload["benchmarks"]), sorted(payload["benchmarks"])
    assert "rule_of_40" not in payload["benchmarks"]


def _js_is_explorable(metric: dict[str, Any]) -> bool:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "explore.py"), "--dir", _builder_dir()],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    fn = _grab_js_function(out.stdout, "isExplorable")
    script = (
        "var METRIC_FORMULAS = {rule_of_40: function(){}, burn_multiple: function(){}};\n"
        f"{fn}\nconsole.log(JSON.stringify(isExplorable({json.dumps(metric)})));"
    )
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return bool(json.loads(res.stdout))


def test_the_explorer_offers_no_what_if_for_a_not_applicable_metric() -> None:
    assert _js_is_explorable({"id": "rule_of_40", "rating": "not_applicable"}) is False
    assert _js_is_explorable({"id": "rule_of_40", "rating": "strong"}) is True
    assert _js_is_explorable({"id": "nrr", "rating": "strong"}) is False  # no formula


# --- the corrections page: a withheld burn multiple is not coloured on the >3x bar ------------------


_SANITY_HARNESS = """
function makeCard() {
  return { className: "", _value: { textContent: "" }, _label: { textContent: "" },
    querySelector: function (s) { return s === ".value" ? this._value : (s === ".label" ? this._label : null); } };
}
var __cards = {};
["runway", "burn-multiple", "arpu-check", "expense-coverage"].forEach(function (id) {
  __cards["sanity-" + id] = makeCard();
});
var document = { getElementById: function (id) { return __cards[id] || null; } };
"""


def _review_js(names: list[str]) -> str:
    source = (SCRIPTS / "review_inputs.py").read_text()

    def grab(name: str) -> str:
        start = source.index(f"function {name}(")
        depth, i = 0, source.index("{", start)
        while True:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    return source[start : i + 1]
            i += 1

    return "\n".join(grab(n) for n in names)


def _node(script: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _static_burn_card(model_type: str, basis: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "company": {"revenue_model_type": model_type},
        "revenue": {"mrr": {"value": 10000}, "growth_rate_monthly": 0.02},
        "cash": {"current_balance": 900000, "monthly_net_burn": 40000},
    }
    if basis:
        state["unit_economics"] = {"gross_margin_basis": basis}
    script = (
        _SANITY_HARNESS
        + _review_js(
            ["getByPath", "numOrNull", "computeSanity", "updateMetricCard", "updateMetricLabel", "refreshSanity"]
        )
        + f"\nvar state = {json.dumps(state)};\nrefreshSanity();\n"
        + 'console.log(JSON.stringify({value: __cards["sanity-burn-multiple"]._value.textContent,'
        + ' cls: __cards["sanity-burn-multiple"].className}));'
    )
    return dict(_node(script))


@pytest.mark.parametrize(
    ("model_type", "basis", "graded"),
    [
        (PB, None, False),
        ("unclassified", None, False),
        ("marketplace", None, False),
        ("marketplace", "net_revenue", True),
        ("saas-sales-led", None, True),
        ("hardware", None, True),
    ],
)
def test_the_static_card_grades_the_burn_multiple_only_where_the_review_does(
    model_type: str, basis: str | None, graded: bool
) -> None:
    card = _static_burn_card(model_type, basis)
    assert card["value"].endswith("x"), card  # the figure is still shown
    assert ("warn" in card["cls"] or "pass" in card["cls"]) is graded, card


def test_the_server_card_does_not_grade_a_withheld_burn_multiple() -> None:
    script = (
        _SANITY_HARNESS
        + _review_js(["updateMetricCard", "updateMetricLabel", "updateSanityFromServer"])
        + "\nvar out = {};"
        + "\nupdateSanityFromServer({burn_multiple: 6.5, burn_multiple_graded: false});"
        + '\nout.withheld = __cards["sanity-burn-multiple"].className;'
        + "\nupdateSanityFromServer({burn_multiple: 6.5, burn_multiple_graded: true});"
        + '\nout.graded = __cards["sanity-burn-multiple"].className;'
        + "\nconsole.log(JSON.stringify(out));"
    )
    out = _node(script)
    assert "warn" not in out["withheld"] and "pass" not in out["withheld"], out
    assert "warn" in out["graded"], out


def test_the_server_says_whether_the_burn_multiple_is_graded() -> None:
    ri = _load("review_inputs", "_fmr_pb_review_inputs")
    withheld = ri._sanity_from_metrics(_ue(_inputs(PB))["metrics"])
    assert withheld.get("burn_multiple") is not None and withheld["burn_multiple_graded"] is False, withheld
    graded = ri._sanity_from_metrics(_ue(_inputs("saas-sales-led"))["metrics"])
    assert graded["burn_multiple_graded"] is True, graded


def test_the_corrections_page_withholds_for_the_same_types_as_the_review() -> None:
    """Drift guard: the static page cannot import the producer, so it carries its own lists."""
    js = _review_js(["computeSanity"])
    no_bar = re.search(r"var NO_BURN_BAR_TYPES = \[([^\]]*)\]", js)
    net_only = re.search(r"var NET_ONLY_BURN_BAR_TYPES = \[([^\]]*)\]", js)
    assert no_bar and net_only, "computeSanity no longer declares its withheld-type lists"
    assert sorted(re.findall(r'"([^"]+)"', no_bar.group(1))) == sorted(ue._NO_SAAS_BAR_TYPES)
    assert sorted(re.findall(r'"([^"]+)"', net_only.group(1))) == sorted(ue._TAKE_RATE_TYPES)


# --- the validator does not ask a project builder for retention -------------------------------------


@pytest.mark.parametrize(("model_type", "asked"), [(PB, False), ("saas-sales-led", True)])
def test_retention_is_asked_for_only_where_it_applies(model_type: str, asked: bool) -> None:
    inputs = _inputs(model_type, stage="series-a")
    inputs["revenue"].pop("nrr", None)
    inputs["revenue"].pop("grr", None)
    _rc, data, _err = run_script("validate_inputs.py", [], stdin_data=json.dumps(inputs))
    assert data is not None
    codes = {w.get("code") for w in data.get("warnings", [])}
    assert ("MISSING_RETENTION" in codes) is asked, codes


# --- plain words in what the founder reads ----------------------------------------------------------

_FIELD_TOKEN = re.compile(r"\b[a-z]+_[a-z_]+\b")


def test_the_sector_table_assumption_is_in_plain_words() -> None:
    gm = _metrics("hardware", gross_margin=0.55)["gross_margin"]
    assert gm["rating"] in _GRADED, gm
    assert "gross_margin_basis" not in gm["evidence"], gm["evidence"]
    assert not _FIELD_TOKEN.search(gm["evidence"]), gm["evidence"]
    assert "store-level contribution" in gm["evidence"], gm["evidence"]


def test_a_declared_basis_source_is_in_plain_words() -> None:
    gm = _metrics("saas-sales-led", gross_margin_basis="net_revenue")["gross_margin"]
    assert gm["rating"] == "contextual", gm
    assert not _FIELD_TOKEN.search(gm["benchmark_source"]), gm["benchmark_source"]


# --- the drift guard: no type falls onto a SaaS growth bar without saying so -------------------------


def test_every_type_has_exactly_one_growth_bar_placement() -> None:
    enum = set(_enum())
    graded, net_only, withheld = set(ue._GROWTH_BARS_GRADED), set(ue._TAKE_RATE_TYPES), set(ue._NO_SAAS_BAR_TYPES)
    assert not (graded & net_only) and not (graded & withheld) and not (net_only & withheld)
    assert graded | net_only | withheld == enum, (
        f"placed but not in the enum: {sorted((graded | net_only | withheld) - enum)}; "
        f"in the enum with no burn-multiple / CAC-payback placement: {sorted(enum - (graded | net_only | withheld))}"
    )


def test_every_type_has_exactly_one_ltv_cac_placement() -> None:
    enum = set(_enum())
    graded, withheld = set(ue._LTV_CAC_GRADED), set(ue._LTV_CAC_WITHHELD)
    assert not (graded & withheld)
    assert graded | withheld == enum, sorted(enum ^ (graded | withheld))


@pytest.mark.parametrize("model_type", sorted(_enum()))
def test_each_type_behaves_as_its_placement_says(model_type: str) -> None:
    """The sets above are only a guard if the producer reads them: run it for every enum value."""
    m = _metrics(model_type, ltv=dict(_OBSERVED_LTV))
    bm, pb, lc = m["burn_multiple"], m["cac_payback"], m["ltv_cac_ratio"]
    if model_type in ue._GROWTH_BARS_GRADED:
        assert bm["rating"] in _GRADED and pb["rating"] in _GRADED, (bm, pb)
    elif model_type in ue._TAKE_RATE_TYPES:
        assert bm["rating"] == "contextual" and pb["rating"] == "contextual", (bm, pb)
        net = _metrics(model_type, gross_margin_basis="net_revenue")["burn_multiple"]
        assert net["rating"] in _GRADED, net
    else:
        assert model_type in ue._NO_SAAS_BAR_TYPES
        assert bm["rating"] == "contextual" and pb["rating"] == "contextual", (bm, pb)
        assert not bm["benchmark_source"] and not pb["benchmark_source"], (bm, pb)
    assert (lc["rating"] in _GRADED) is (model_type in ue._LTV_CAC_GRADED), lc


# --- the references say so --------------------------------------------------------------------------


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _section(text: str, heading: str, *, deepest: int = 4) -> str:
    """From *heading* up to the next heading at level 2..*deepest*."""
    start = text.index(heading)
    rest = text[start + len(heading) :]
    m = re.search(r"\n#{2," + str(deepest) + "} ", rest)
    return rest[: m.start()] if m else rest


def test_the_schema_routes_a_project_builder_by_its_billing() -> None:
    text = _flat(REFS / "schema-inputs.md")
    assert "is `project-builder`, not `hardware` and not `unclassified`" in text
    assert "Billing mechanics decide" in text
    assert 'a margin stated "on cost" is a markup' in text
    assert "record the derivation in `metadata.extraction_notes`" in text
    assert "- `SECTOR_41` (hardware): triggers for `hardware`, `hardware-subscription`, `project-builder`" in text
    assert "vehicle fleet" not in text


def test_the_criteria_name_what_a_project_builder_is_judged_on() -> None:
    raw = (REFS / "checklist-criteria.md").read_text(encoding="utf-8")
    assert "Project builder: materials, subcontractors, site labour" in _section(raw, "### `UNIT_14`")
    assert "Material by construction for a project builder" in _section(raw, "### `CASH_22`")
    assert "For a project builder: progress billing, retentions" in _section(raw, "### `SECTOR_41`")
    note = _section(raw, "## Category 6")
    assert "For a project builder" in note and "customer concentration" in note and "backlog" in note
    assert "project" not in _section(raw, "### `METRIC_34`").lower()


def test_data_sufficiency_does_not_count_what_a_project_builder_lacks() -> None:
    text = (REFS / "data-sufficiency.md").read_text(encoding="utf-8")
    row = next(ln for ln in text.splitlines() if ln.startswith("- Project builder (by `revenue_model_type`"))
    for field in ("`mrr`", "`growth_rate_monthly`", "`cac`"):
        assert field in row.split("not expected")[0].rsplit(";", 1)[-1], (field, row)


def test_the_pitfalls_cover_milestones_and_markup() -> None:
    raw = (REFS / "extraction-pitfalls.md").read_text(encoding="utf-8")
    items = {int(m.group(1)): m.group(0) for m in re.finditer(r"^(\d+)\. .*$", raw, re.M)}
    assert "project builder" in items[4] and "milestone" in items[4], items[4]
    assert "project builder" in items[8] and "growth rate" in items[8], items[8]
    markup = next(v for v in items.values() if "Margin on cost is a markup" in v)
    assert "markup ÷ (1 + markup)" in markup, markup
    assert "25%" not in markup


def test_the_shared_references_carry_the_type() -> None:
    bench = (ROOT_REFS / "benchmarks.md").read_text(encoding="utf-8")
    rows = [ln for ln in bench.splitlines() if ln.startswith("| Project builder")]
    assert len(rows) == 1 and "contextual — no threshold" in rows[0], rows
    assert "Vehicle" not in rows[0] and "Auto" not in rows[0], rows[0]
    types = (ROOT_REFS / "revenue-model-types.md").read_text(encoding="utf-8")
    sec = _section(types, "## Project Builder", deepest=2)
    assert "milestone" in sec and "retentions" in sec and "concentration" in sec, sec
