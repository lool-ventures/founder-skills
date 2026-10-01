"""No revenue model is graded on SaaS bars unless it is one; take-rate revenue is graded only net.

Three rules, each a way a founder was graded against a benchmark built for someone else:

1. Every `revenue_model_type` has an explicit gross-margin placement (SaaS table, its own sector table,
   or contextual). A value added without one used to fall through to the SaaS stage table silently, which
   grades worse than abstaining. The drift test reds the day that happens; the code abstains anyway
   (`"unrecognized"`) for an empty or off-enum type that skipped the validator.
2. A business with no benchmarked model (`unclassified`, including a large-system OEM) is not graded on
   the SaaS-calibrated burn multiple or CAC payback either. LTV/CAC is left alone: LTV is gross profit per
   customer, so the revenue basis cancels out, and 3:1 is not a SaaS-only rule.
3. Transactional fintech and marketplaces book revenue gross or net. Gross volume inflates net-new ARR and
   flatters the burn multiple, so it is graded only when the revenue basis is declared net.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_financial_model_review import _VALID_INPUTS, run_script  # noqa: E402

SKILL = Path(__file__).resolve().parents[1] / "skills" / "financial-model-review"
SCRIPTS = SKILL / "scripts"
REFS = SKILL / "references"
_GRADED = {"strong", "acceptable", "warning", "fail"}


def _load(name: str, key: str) -> Any:
    """By path, under a unique key: several skills ship a module of the same name, and a bare import
    in a shared test process can hand back another skill's copy."""
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ue = _load("unit_economics", "_fmr_trap_unit_economics")


def _enum() -> list[str]:
    """The validator's revenue_model_type list, read from source (it lives inside a function)."""
    tree = ast.parse((SCRIPTS / "validate_inputs.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "revenue_model_type" and isinstance(v, ast.Tuple):
                    lst = v.elts[1]
                    assert isinstance(lst, ast.List)
                    return [e.value for e in lst.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("revenue_model_type enum not found in validate_inputs.py")


def _checklist_map() -> dict[str, str]:
    tree = ast.parse((SCRIPTS / "checklist.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_REVENUE_MODEL_TO_SECTOR":
            value = ast.literal_eval(node.value)  # type: ignore[arg-type]
            assert isinstance(value, dict)
            return value
    raise AssertionError("_REVENUE_MODEL_TO_SECTOR not found in checklist.py")


# --- 1. the placement drift test -----------------------------------------------------------------


def test_every_revenue_model_type_has_exactly_one_gross_margin_placement() -> None:
    enum = set(_enum())
    saas, sector, contextual = set(ue._KNOWN_SAAS_LIKE_TYPES), set(ue._GM_SECTOR_TABLE), set(ue._GM_CONTEXTUAL_TYPES)
    assert not (saas & sector) and not (saas & contextual) and not (sector & contextual)
    assert saas | sector | contextual == enum, (
        f"placed but not in the enum: {sorted((saas | sector | contextual) - enum)}; "
        f"in the enum with no gross-margin placement (would abstain as unrecognized): "
        f"{sorted(enum - (saas | sector | contextual))}"
    )
    for t in contextual:
        assert t in ue._GM_CONTEXTUAL_SOURCES and t in ue._GM_CONTEXTUAL_EVIDENCE, t


def test_the_enum_copies_agree() -> None:
    enum = _enum()
    dropdown = re.search(
        r'createDropdown\("company\.revenue_model_type", "Revenue Model Type", \[([^\]]*)\]\)',
        (SCRIPTS / "review_inputs.py").read_text(),
    )
    assert dropdown, "the corrections UI dropdown moved"
    assert sorted(re.findall(r'"([^"]+)"', dropdown.group(1))) == sorted(enum)
    schema = (REFS / "schema-inputs.md").read_text()
    row = next(ln for ln in schema.splitlines() if ln.startswith("| `revenue_model_type` |"))
    assert sorted(re.findall(r'"([a-z-]+)"', row)) == sorted(enum)
    table = schema.split("### Valid `revenue_model_type` Values", 1)[1].split("\n### ", 1)[0]
    assert sorted(re.findall(r"^\| `([a-z-]+)` \|", table, re.M)) == sorted(enum)
    # `unclassified` is left out of the sector map on purpose (no sector gate applies).
    assert set(_checklist_map()) == set(enum) - {"unclassified"}


def test_an_unplaced_type_abstains_instead_of_taking_the_saas_bar() -> None:
    for mt in ("", "saas", "industrial-oem", "  "):
        assert ue.gm_contextual_reason(mt) == "unrecognized", mt
        assert ue.gm_benchmark_for(mt, "seed") is None, mt
    for mt in ue._KNOWN_SAAS_LIKE_TYPES | set(ue._GM_SECTOR_TABLE):
        assert ue.gm_benchmark_for(mt, "seed") is not None, mt


# --- helpers for whole-producer runs -------------------------------------------------------------


def _metrics(model_type: str, **ue_fields: Any) -> dict[str, dict[str, Any]]:
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    company = inputs["company"]
    company["revenue_model_type"] = model_type
    for k in ("unclassified_reason", "currency"):
        if k in ue_fields:
            company[k] = ue_fields.pop(k)
    inputs["unit_economics"].update(ue_fields)
    rc, data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    assert data is not None
    return {m["name"]: m for m in data["metrics"]}


def test_the_fixture_grades_both_ratios_for_saas() -> None:
    """Control: without it every 'not graded' below could pass on a fixture that grades nothing."""
    m = _metrics("saas-sales-led")
    assert m["burn_multiple"]["rating"] in _GRADED and m["cac_payback"]["rating"] in _GRADED


# --- 2. OEM / unclassified ------------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "no_fitting_type", "not_stated"])
def test_a_project_oem_is_not_graded_on_saas_bars(reason: str | None) -> None:
    fields: dict[str, Any] = {"gross_margin": 0.25}
    if reason:
        fields["unclassified_reason"] = reason
    m = _metrics("unclassified", **fields)
    assert m["gross_margin"]["rating"] == "contextual", m["gross_margin"]
    for name in ("burn_multiple", "cac_payback"):
        assert m[name]["rating"] not in _GRADED, (name, m[name])
        assert m[name]["rating"] == "contextual", (name, m[name])
        assert not m[name]["benchmark_source"], (name, m[name])
        assert "unclassified" not in m[name]["evidence"], m[name]["evidence"]
    for name in ("nrr", "grr", "magic_number", "rule_of_40", "arr_per_fte"):
        assert m[name]["rating"] not in _GRADED, name


def test_the_oem_reason_states_the_case_it_knows() -> None:
    bm = _metrics("unclassified", unclassified_reason="no_fitting_type")["burn_multiple"]["evidence"]
    assert "your revenue model is not" in bm, bm
    bm = _metrics("unclassified", unclassified_reason="not_stated")["burn_multiple"]["evidence"]
    assert "no revenue model is stated" in bm, bm


def test_the_schema_routes_project_oem_to_unclassified_not_hardware() -> None:
    text = re.sub(r"\s+", " ", (REFS / "schema-inputs.md").read_text())
    assert "A large-system or project OEM" in text
    assert "is `unclassified` with `unclassified_reason: no_fitting_type`, not `hardware`" in text


# --- 3. take-rate revenue basis --------------------------------------------------------------------


@pytest.mark.parametrize("model_type", ["transactional-fintech", "marketplace"])
@pytest.mark.parametrize(
    ("basis", "graded"), [(None, False), ("gross_revenue", False), ("blended", False), ("net_revenue", True)]
)
def test_take_rate_burn_multiple_is_graded_only_on_net_revenue(
    model_type: str, basis: str | None, graded: bool
) -> None:
    fields = {"gross_margin_basis": basis} if basis else {}
    bm = _metrics(model_type, **fields)["burn_multiple"]
    assert (bm["rating"] in _GRADED) is graded, (basis, bm)
    if not graded:
        assert bm["rating"] == "contextual"
        assert bm["evidence"].startswith("Burn multiple of "), bm["evidence"]
        assert ("stated gross" in bm["evidence"]) is (basis == "gross_revenue"), bm["evidence"]
        assert "benchmark" not in bm and bm.get("benchmark_reference"), bm
        assert model_type not in bm["evidence"], bm["evidence"]


def test_the_method_word_survives_so_the_explorer_still_knows_the_burn_method() -> None:
    """The explorer reads "TTM"/"YoY" from the evidence head to decide whether a slider may move the
    ratio. Replacing the whole evidence would make a time-series multiple slider-adjustable."""
    explore = _load("explore", "_fmr_trap_explore")
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["revenue"]["monthly"] = [{"month": f"2025-{i:02d}", "total": 40_000 + i * 3_000} for i in range(1, 13)]
    inputs["revenue"]["monthly"] += [{"month": "2026-01", "total": 80_000}]
    for mt, graded in (("saas-sales-led", True), ("transactional-fintech", False)):
        inputs["company"]["revenue_model_type"] = mt
        rc, data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
        assert rc == 0, err
        assert data is not None
        bm = {m["name"]: m for m in data["metrics"]}["burn_multiple"]
        assert (bm["rating"] in _GRADED) is graded, (mt, bm)
        assert "TTM" in bm["evidence"].split("; ", 1)[0], (mt, bm["evidence"])
        assert explore._detect_burn_method(bm["evidence"]) == "ttm", mt


def test_a_non_usd_take_rate_burn_multiple_gets_no_reference_grade() -> None:
    """The non-USD caveat keeps a 'reference' grade; on gross revenue that reference is the misleading
    part, so the basis rule runs first and the caveat then leaves the metric alone."""
    bm = _metrics("transactional-fintech", currency="EUR")["burn_multiple"]
    assert bm["rating"] == "contextual"
    assert not bm.get("benchmark_reference_rating"), bm


@pytest.mark.parametrize("model_type", ["transactional-fintech", "marketplace"])
def test_take_rate_cac_payback_and_cac_are_not_graded(model_type: str) -> None:
    m = _metrics(model_type, gross_margin_basis="net_revenue")
    assert m["cac_payback"]["rating"] == "contextual", m["cac_payback"]
    assert m["cac"]["rating"] == "contextual", m["cac"]
    assert model_type not in m["cac"]["evidence"] and model_type not in m["cac_payback"]["evidence"]


def test_saas_is_unaffected() -> None:
    m = _metrics("saas-sales-led", gross_margin_basis="gross_revenue")
    assert m["burn_multiple"]["rating"] in _GRADED and m["cac_payback"]["rating"] in _GRADED


def test_the_references_say_so() -> None:
    schema = re.sub(r"\s+", " ", (REFS / "schema-inputs.md").read_text())
    assert "Transactional fintech and marketplaces: record revenue NET." in schema
    assert 'the burn multiple is graded only when it is `"net_revenue"`' in schema
    suff = (REFS / "data-sufficiency.md").read_text()
    assert "Transactional fintech (by `revenue_model_type`" in suff
    crit = (REFS / "checklist-criteria.md").read_text()
    assert "payments: interchange, network and processor fees, fraud and chargeback losses" in crit
    assert "net revenue and volume (TPV) in place of ARR" in crit
    assert "never pass or fail on the 3x bar" in crit


# --- the explorer -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("model_type", "kept"), [("transactional-fintech", False), ("saas-sales-led", True)])
def test_the_explorer_does_not_regrade_a_withheld_burn_multiple(model_type: str, kept: bool) -> None:
    """Its what-if slider re-rates against DATA.benchmarks[id]; a withheld grade must have no bar there,
    and the table shows the reason where the bar would be."""
    explore = _load("explore", "_fmr_trap_explore")
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = model_type
    rc, ue_data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    payload = explore._build_data_payload(inputs, None, ue_data, None, None, stub_reasons={})
    assert ("burn_multiple" in payload["benchmarks"]) is kept, sorted(payload["benchmarks"])
    bm = next(m for m in payload["metrics"] if m["id"] == "burn_multiple")
    if not kept:
        assert "net revenue" in (bm.get("contextual_note") or ""), bm


# --- an empty or off-enum type --------------------------------------------------------------------


@pytest.mark.parametrize("model_type", ["", "industrial-oem"])
def test_an_unstated_or_unknown_type_keeps_its_growth_grades(model_type: str) -> None:
    """Only `unclassified` withholds the burn multiple and CAC payback. An empty or off-enum type never
    reached the validator's routing, so nothing says the business is not one the stage bars fit; the
    gross margin abstains (its tables differ by model) and the two growth ratios stay graded."""
    m = _metrics(model_type)
    for name in ("burn_multiple", "cac_payback"):
        assert m[name]["rating"] in _GRADED, (model_type, name, m[name])
        assert m[name]["benchmark_source"], (model_type, name, m[name])
    assert m["gross_margin"]["rating"] == "contextual", m["gross_margin"]


def test_a_withheld_grade_keeps_the_estimate_qualifier_once() -> None:
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = "unclassified"
    inputs["company"]["data_confidence"] = "estimated"
    rc, data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    assert data is not None
    m = {x["name"]: x for x in data["metrics"]}
    for name in ("burn_multiple", "cac_payback"):
        ev = m[name]["evidence"]
        assert m[name]["rating"] == "contextual", (name, m[name])
        assert ev.endswith(" (based on estimated inputs)"), (name, ev)
        assert ev.count("(based on estimated inputs)") == 1, (name, ev)


@pytest.mark.parametrize("model_type", sorted(ue._GM_CONTEXTUAL_TYPES - {"unclassified"}))
def test_contextual_gross_margin_evidence_names_no_type_token(model_type: str) -> None:
    gm = _metrics(model_type, gross_margin=0.55)["gross_margin"]
    assert gm["rating"] == "contextual", gm
    assert model_type not in gm["evidence"], gm["evidence"]


def test_an_empty_type_says_why_a_saas_only_metric_was_not_assessed() -> None:
    nrr = _metrics("")["nrr"]
    assert nrr["rating"] == "not_applicable", nrr
    assert nrr["evidence"].endswith(
        "models only; it is not assessed because no revenue model we have benchmarks for is stated in your materials"
    ), nrr["evidence"]


@pytest.mark.parametrize("model_type", ["hardware", "hardware-subscription", "marketplace"])
def test_contextual_ltv_evidence_names_no_type_token(model_type: str) -> None:
    ltv = _metrics(model_type)["ltv"]
    assert ltv["rating"] == "contextual", ltv
    assert model_type not in ltv["evidence"], ltv["evidence"]
    assert "LTV benchmarks vary too widely across businesses like yours to grade it" in ltv["evidence"]


def test_a_padded_type_takes_its_own_gross_margin_bar() -> None:
    assert ue.gm_benchmark_for(" hardware", "seed") == ue.GM_BENCHMARKS_BY_SECTOR["hardware"]
    assert ue.gm_benchmark_for("Hardware ", "seed") == ue.GM_BENCHMARKS_BY_SECTOR["hardware"]


def test_a_declared_basis_is_named_in_plain_words() -> None:
    gm = _metrics("saas-sales-led", gross_margin_basis="net_revenue")["gross_margin"]
    assert gm["rating"] == "contextual", gm
    assert "net revenue basis" in gm["evidence"] and "net_revenue" not in gm["evidence"], gm["evidence"]


def test_the_fintech_gross_margin_reason_agrees_with_its_source() -> None:
    ev = ue._GM_CONTEXTUAL_EVIDENCE["transactional-fintech"]
    assert ue._GM_CONTEXTUAL_SOURCES["transactional-fintech"].startswith("No benchmark")
    assert "comps" not in ev and "40pts" not in ev, ev
    assert "booked net or gross" in ev, ev


def test_the_take_rate_burn_reason_names_its_metric() -> None:
    bm = _metrics("marketplace")["burn_multiple"]
    assert "the burn-multiple benchmark applies only to net revenue" in bm["evidence"], bm["evidence"]


@pytest.mark.parametrize("model_type", ["transactional-fintech", "marketplace"])
def test_the_explorer_shows_why_a_withheld_cac_payback_has_no_bar(model_type: str) -> None:
    explore = _load("explore", "_fmr_trap_explore")
    inputs = json.loads(json.dumps(_VALID_INPUTS))
    inputs["company"]["revenue_model_type"] = model_type
    rc, ue_data, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0, err
    payload = explore._build_data_payload(inputs, None, ue_data, None, None, stub_reasons={})
    pb = next(m for m in payload["metrics"] if m["id"] == "cac_payback")
    assert pb["rating"] == "contextual", pb
    assert "subscription software contract sizes" in (pb.get("contextual_note") or ""), pb


# --- 4. A declared basis gets advice that fits it -------------------------------------------------

_NON_PRODUCT_BASES = ("store_contribution", "net_revenue", "gross_revenue", "blended")


@pytest.mark.parametrize("model_type", ["retail", "saas-sales-led"])
@pytest.mark.parametrize("basis", _NON_PRODUCT_BASES)
def test_a_declared_basis_gets_advice_that_fits_it(basis: str, model_type: str) -> None:
    """Store advice ("store-level contribution, buildout payback, same-store trends") was given for
    every declared basis, including revenue booked net or gross, where there are no stores."""
    gm = _metrics(model_type, gross_margin_basis=basis)["gross_margin"]
    assert gm["rating"] == "contextual", gm
    ev = gm["evidence"]
    assert f"{basis.replace('_', ' ')} basis" in ev, ev
    assert ("store" in ev.lower()) == (basis == "store_contribution"), ev
    # The multi-word values are the tokens; "blended" is its own plain word.
    for raw in (b for b in _NON_PRODUCT_BASES + ("gross_margin_basis",) if "_" in b):
        assert raw not in ev and raw.replace("_", "-") not in ev, ev


def _benchmarks_row(label_start: str) -> str:
    text = (SKILL.parents[1] / "references" / "benchmarks.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith(f"| {label_start}")]
    assert len(rows) == 1, (label_start, rows)
    return rows[0]


def test_the_reference_agrees_that_payments_have_no_gross_margin_benchmark() -> None:
    """The script says payments have no benchmark; the reference grouped them with marketplaces and
    cited the marketplace comps for both."""
    assert ue._GM_CONTEXTUAL_SOURCES["transactional-fintech"].startswith("No benchmark")
    payments = _benchmarks_row("Transactional fintech")
    assert "Marketplace" not in payments, payments
    assert "no published benchmark" in payments.lower(), payments
    assert "booked net or gross" in payments, payments
    assert "Airbnb" not in payments and "DoorDash" not in payments, payments
    marketplace = _benchmarks_row("Marketplace")
    assert "fintech" not in marketplace.lower(), marketplace
    assert "Airbnb" in marketplace and "DoorDash" in marketplace, marketplace
