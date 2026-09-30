"""Market-sizing inputs by reference: the unit registry and the resolver.

A sizing input names WHERE its value comes from, and the resolver produces the value. That leaves
one copy of every figure, in the record, and a unit on every one. The defect this exists for was a
head-count recorded as the top-down industry total and printed as money, with a borrowed
"derived" label.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "market-sizing" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

_params = importlib.import_module("_params")
_provenance = importlib.import_module("_provenance")


def _record(*entries: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"assumptions": list(entries), "sources": sources or []}


_SRC = {"title": "Government survey 2025", "url": "https://example.gov/survey"}


def _sourced(name: str, value: float, unit: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "category": "sourced",
        "source_title": _SRC["title"],
        "source_url": _SRC["url"],
        **extra,
    }


def _resolve(refs: dict[str, Any], record: dict[str, Any], inputs: dict[str, Any] | None = None) -> Any:
    return _provenance.resolve(refs, validation=record, inputs=inputs or {}, currency="USD")


def _codes(errors: list[dict[str, Any]]) -> list[str]:
    return [e["code"] for e in errors]


# --- the defect ---------------------------------------------------------------------------------


def test_a_head_count_cannot_be_the_industry_total() -> None:
    record = _record(_sourced("eligible_population", 36_000_000, "count"), sources=[_SRC])
    resolved, errors = _resolve({"industry_total": {"assumption": "eligible_population"}}, record)
    assert "industry_total" not in resolved
    assert _codes(errors) == ["E_UNIT_MISMATCH"]
    # The remedy names the legitimate route, never an edit of the recorded unit.
    msg = errors[0]["message"].lower()
    assert "derived" in msg
    for route in ("edit", "relabel", "change its unit", "change the unit"):
        assert route not in msg, msg
    assert errors[0]["remedy_kind"] == "redispatch"


def test_head_count_times_a_monthly_price_is_money_per_year() -> None:
    record = _record(
        _sourced("eligible_population", 41_000_000, "count"),
        _sourced("care_price", 157, "money_per_customer", currency="USD", period="month"),
        sources=[_SRC],
    )
    ref = {
        "derived": {"op": "multiply", "factors": [{"assumption": "eligible_population"}, {"assumption": "care_price"}]}
    }
    resolved, errors = _resolve({"industry_total": ref}, record)
    assert errors == []
    it = resolved["industry_total"]
    assert it["unit"] == "money_total_per_year"
    assert it["value_consumed"] == pytest.approx(41_000_000 * 157 * 12)
    assert it["kind"] == "derived"
    assert set(it["entries"]) == {"eligible_population", "care_price"}


def test_a_per_customer_price_without_a_period_is_refused_not_assumed_annual() -> None:
    record = _record(_sourced("arpu_benchmark", 157, "money_per_customer", currency="USD"), sources=[_SRC])
    resolved, errors = _resolve({"arpu": {"assumption": "arpu_benchmark"}}, record)
    assert resolved == {}
    assert _codes(errors) == ["E_PERIOD_MISSING"]


def test_a_monthly_arpu_is_consumed_per_year_and_the_conversion_recorded() -> None:
    record = _record(
        _sourced("arpu_benchmark", 157, "money_per_customer", currency="USD", period="month"), sources=[_SRC]
    )
    resolved, errors = _resolve({"arpu": {"assumption": "arpu_benchmark"}}, record)
    assert errors == []
    arpu = resolved["arpu"]
    assert arpu["value_as_recorded"] == 157
    assert arpu["value_consumed"] == pytest.approx(1884)
    assert {"step": "period", "from": "month", "factor": 12.0} in arpu["normalisation"]


def test_the_period_table_has_one_owner() -> None:
    # By path: six skills each have a compose_report.py, and a bare import returns whichever one an
    # earlier test loaded first.
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ms_compose_for_period_test", _SCRIPTS / "compose_report.py")
    assert spec is not None and spec.loader is not None
    compose = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compose)
    assert compose._PERIOD_TO_YEAR is _params.PERIOD_TO_YEAR


# --- the four reference kinds -------------------------------------------------------------------


def test_a_ratio_of_two_counts_becomes_percent_points_only_through_an_explicit_conversion() -> None:
    record = _record(
        _sourced("reachable", 15_000_000, "count"),
        _sourced("eligible", 41_000_000, "count"),
        sources=[_SRC],
    )
    ratio = {"derived": {"op": "divide", "factors": [{"assumption": "reachable"}, {"assumption": "eligible"}]}}
    bare, errors = _resolve({"segment_pct": ratio}, record)
    assert bare == {} and _codes(errors) == ["E_UNIT_MISMATCH"]
    as_pct = {"derived": {"op": "to_percent", "factors": [ratio]}}
    resolved, errors = _resolve({"segment_pct": as_pct}, record)
    assert errors == []
    assert resolved["segment_pct"]["value_consumed"] == pytest.approx(15 / 41 * 100)


def test_accounts_times_seats_times_a_seat_price_resolves() -> None:
    record = _record(
        _sourced("accounts", 12_000, "count"),
        _sourced("seats_per_account", 40, "ratio"),
        _sourced("seat_price", 30, "money_per_customer", currency="USD", period="month"),
        sources=[_SRC],
    )
    seats = {
        "derived": {"op": "multiply", "factors": [{"assumption": "accounts"}, {"assumption": "seats_per_account"}]}
    }
    total = {"derived": {"op": "multiply", "factors": [seats, {"assumption": "seat_price"}]}}
    resolved, errors = _resolve({"industry_total": total, "customer_count": seats}, record)
    assert errors == []
    assert resolved["industry_total"]["value_consumed"] == pytest.approx(12_000 * 40 * 30 * 12)
    assert resolved["customer_count"]["value_consumed"] == 480_000


def test_arpu_can_be_derived_from_revenue_over_customers() -> None:
    record = _record(
        _sourced("category_revenue", 9_000_000, "money_total_per_year", currency="USD"),
        _sourced("category_customers", 3_000, "count"),
        sources=[_SRC],
    )
    ref = {
        "derived": {
            "op": "divide",
            "factors": [{"assumption": "category_revenue"}, {"assumption": "category_customers"}],
        }
    }
    resolved, errors = _resolve({"arpu": ref}, record)
    assert errors == []
    assert resolved["arpu"]["value_consumed"] == pytest.approx(3_000)


def test_a_derived_count_is_rounded_and_the_rounding_recorded() -> None:
    record = _record(
        _sourced("population", 3_100_000, "count"),
        _sourced("prevalence", 0.07, "fraction"),
        sources=[_SRC],
    )
    ref = {"derived": {"op": "multiply", "factors": [{"assumption": "population"}, {"assumption": "prevalence"}]}}
    resolved, errors = _resolve({"customer_count": ref}, record)
    assert errors == []
    cc = resolved["customer_count"]
    assert cc["value_consumed"] == 217_000 and isinstance(cc["value_consumed"], int)
    assert any(step["step"] == "round" for step in cc["normalisation"])


def test_an_unsupported_combination_is_refused_with_the_rules() -> None:
    record = _record(_sourced("a", 10, "count"), _sourced("b", 20, "count"), sources=[_SRC])
    ref = {"derived": {"op": "multiply", "factors": [{"assumption": "a"}, {"assumption": "b"}]}}
    resolved, errors = _resolve({"customer_count": ref}, record)
    assert resolved == {} and _codes(errors) == ["E_ALGEBRA"]


def test_an_estimate_carries_its_reason_and_is_graded_as_an_estimate() -> None:
    resolved, errors = _resolve(
        {"share_pct": {"estimate": 0.5, "unit": "percent_points", "why": "No source gives it."}}, _record()
    )
    assert errors == []
    sp = resolved["share_pct"]
    assert sp["kind"] == "estimate" and sp["category"] == "agent_estimate" and sp["why"] == "No source gives it."


def test_an_estimate_needs_a_reason() -> None:
    _, errors = _resolve({"share_pct": {"estimate": 0.5, "unit": "percent_points"}}, _record())
    assert _codes(errors) == ["E_REF_SHAPE"]


def test_an_estimate_beside_research_shows_both() -> None:
    record = _record(_sourced("share_pct", 2.0, "percent_points"), sources=[_SRC])
    resolved, errors = _resolve(
        {"share_pct": {"estimate": 0.5, "unit": "percent_points", "why": "Channel-bound."}}, record
    )
    assert errors == []
    assert resolved["share_pct"]["research_value"] == 2.0


def test_the_founders_own_figure_resolves_with_its_period() -> None:
    inputs = {"founder_stated_inputs": {"arpu": 157}, "founder_stated_inputs_period": {"arpu": "month"}}
    resolved, errors = _resolve({"arpu": {"founder_stated": "arpu"}}, _record(), inputs)
    assert errors == []
    assert resolved["arpu"]["kind"] == "founder_stated"
    assert resolved["arpu"]["value_consumed"] == pytest.approx(1884)


def test_a_founder_figure_without_a_period_is_a_question_for_the_founder() -> None:
    inputs = {"founder_stated_inputs": {"arpu": 157}}
    _, errors = _resolve({"arpu": {"founder_stated": "arpu"}}, _record(), inputs)
    assert _codes(errors) == ["E_PERIOD_MISSING"]
    assert errors[0]["remedy_kind"] == "founder_question"


def test_only_a_fact_about_the_founders_business_can_be_founder_stated() -> None:
    inputs = {"founder_stated_inputs": {"customer_count": 900}}
    _, errors = _resolve({"customer_count": {"founder_stated": "customer_count"}}, _record(), inputs)
    assert _codes(errors) == ["E_FOUNDER_NOT_FACT"]


# --- record integrity ----------------------------------------------------------------------------


def test_a_sourced_entry_with_no_source_is_graded_as_an_estimate() -> None:
    entry = {
        "name": "industry_total",
        "value": 5e9,
        "unit": "money_total_per_year",
        "currency": "USD",
        "category": "sourced",
    }
    resolved, errors = _resolve({"industry_total": {"assumption": "industry_total"}}, _record(entry))
    assert errors == []
    it = resolved["industry_total"]
    assert it["category"] == "agent_estimate" and it["category_declared"] == "sourced"


def test_a_sourced_entry_citing_no_listed_source_is_graded_as_an_estimate() -> None:
    entry = _sourced("industry_total", 5e9, "money_total_per_year", currency="USD")
    record = _record(entry, sources=[{"title": "Something else", "url": "https://other.example"}])
    resolved, _ = _resolve({"industry_total": {"assumption": "industry_total"}}, record)
    assert resolved["industry_total"]["category"] == "agent_estimate"


def test_two_entries_with_one_name_are_ambiguous() -> None:
    record = _record(_sourced("x", 1, "count"), _sourced("x", 2, "count"), sources=[_SRC])
    _, errors = _resolve({"customer_count": {"assumption": "x"}}, record)
    assert _codes(errors) == ["E_REF_AMBIGUOUS"]


def test_an_unknown_name_is_refused() -> None:
    _, errors = _resolve({"customer_count": {"assumption": "nope"}}, _record())
    assert _codes(errors) == ["E_REF_UNKNOWN"]


def test_a_bare_number_is_not_a_reference() -> None:
    _, errors = _resolve({"customer_count": 4_500_000}, _record())
    assert _codes(errors) == ["E_REF_SHAPE"]


# --- currency --------------------------------------------------------------------------------------


def test_a_foreign_money_entry_converts_through_a_recorded_rate() -> None:
    record = _record(
        _sourced("market", 1e9, "money_total_per_year", currency="USD"),
        _sourced("usd_ils", 3.7, "fx_rate", **{"from": "USD", "to": "ILS", "as_of": "2026-09-01"}),
        sources=[_SRC],
    )
    resolved, errors = _provenance.resolve(
        {"industry_total": {"assumption": "market"}}, validation=record, inputs={}, currency="ILS"
    )
    assert errors == []
    it = resolved["industry_total"]
    assert it["value_consumed"] == pytest.approx(3.7e9)
    assert set(it["entries"]) == {"market", "usd_ils"}


def test_a_missing_rate_is_refused_and_never_inverted() -> None:
    record = _record(
        _sourced("market", 1e9, "money_total_per_year", currency="USD"),
        _sourced("ils_usd", 0.27, "fx_rate", **{"from": "ILS", "to": "USD", "as_of": "2026-09-01"}),
        sources=[_SRC],
    )
    _, errors = _provenance.resolve(
        {"industry_total": {"assumption": "market"}}, validation=record, inputs={}, currency="ILS"
    )
    assert _codes(errors) == ["E_FX_RATE_MISSING"]


def test_a_rate_cannot_be_an_estimate() -> None:
    _, errors = _resolve({"industry_total": {"estimate": 3.7, "unit": "fx_rate", "why": "memory"}}, _record())
    assert "E_FX_NOT_RESEARCHED" in _codes(errors)


# --- formatting has one owner ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        ("money_total_per_year", 36_000_000, "$36.0M"),
        ("count", 36_000_000, "36,000,000"),
        ("percent_points", 0.27, "0.27%"),
        ("fraction", 0.0002, "0.0002"),
        ("money_per_customer", 1884, "$1.9K"),
    ],
)
def test_a_value_is_formatted_by_its_unit(unit: str, value: float, expected: str) -> None:
    assert _params.format_value(unit, value, "USD") == expected


def test_a_derived_count_prints_as_a_whole_number() -> None:
    # 1,323,960 x 20% x 5% = 13,239.6 customers reached a report as "13,239.60". The math keeps the
    # fraction; a count is shown whole.
    assert _params.format_value("count", 13_239.6, "USD") == "13,240"


@pytest.mark.parametrize(
    ("value", "signed", "expected"),
    [
        (179.0, False, "179.0%"),  # fmt_percent and :g both print "179%", which drops the decimal
        (64.63, False, "64.6%"),
        (0, False, "0.0%"),
        (-47.5, True, "-47.5%"),
        (12.0, True, "+12.0%"),
    ],
)
def test_a_delta_keeps_one_decimal(value: float, signed: bool, expected: str) -> None:
    assert _params.fmt_delta(value, signed=signed) == expected


_FOUNDER_SURFACES = ("_view.py", "compose_report.py", "visualize.py", "closing_message.py", "market_sizing.py")


def test_every_delta_is_printed_by_its_one_owner() -> None:
    # A delta interpolated straight into prose is formatted by whoever wrote that line: `:g` in the
    # verdict printed 179.0 as "179%" while the table beside it printed "179.0%". Derived by scan,
    # not by list, so a new site cannot opt out by being unlisted.
    import re

    pattern = re.compile(r"\{[^{}]*delta[^{}]*\}%")
    offenders = [
        f"{name}:{n}: {line.strip()}"
        for name in _FOUNDER_SURFACES
        for n, line in enumerate((_SCRIPTS / name).read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


# --- market_sizing.py: the producer resolves references ---------------------------------------------

import json  # noqa: E402
import subprocess  # noqa: E402

_SHARED = Path(__file__).resolve().parent.parent / "scripts"


def _run_sizing(tmp_path: Path, stdin: dict[str, Any], *extra: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "market_sizing.py"), "--stdin", *extra],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _full_record() -> dict[str, Any]:
    return _record(
        _sourced("eligible_population", 41_000_000, "count"),
        _sourced("care_price", 157, "money_per_customer", currency="USD", period="month"),
        _sourced("segment_pct", 37, "percent_points"),
        _sourced("addressable_accounts", 232_800, "count"),
        _sourced("serviceable_pct", 50, "percent_points"),
        _sourced("target_pct", 15, "percent_points"),
        sources=[_SRC],
    )


_TD_REFS = {
    "approach": "top_down",
    "industry_total": {
        "derived": {"op": "multiply", "factors": [{"assumption": "eligible_population"}, {"assumption": "care_price"}]}
    },
    "segment_pct": {"assumption": "segment_pct"},
    "share_pct": {"estimate": 0.27, "unit": "percent_points", "why": "The deck's own long-run capture target."},
}
_BU_REFS = {
    "approach": "bottom_up",
    "customer_count": {"assumption": "addressable_accounts"},
    "arpu": {"assumption": "care_price"},
    "serviceable_pct": {"assumption": "serviceable_pct"},
    "target_pct": {"assumption": "target_pct"},
}


def _write(tmp_path: Path, name: str, doc: dict[str, Any]) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def _merged(tmp_path: Path) -> dict[str, Any]:
    td = _write(tmp_path, "td.json", _TD_REFS)
    bu = _write(tmp_path, "bu.json", _BU_REFS)
    proc = subprocess.run(
        [sys.executable, str(_SHARED / "merge_json.py"), str(td), str(bu), "--set", "approach=both"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    merged: dict[str, Any] = json.loads(proc.stdout)
    return merged


def test_a_both_run_resolves_every_input_through_the_merge(tmp_path: Path) -> None:
    v = _write(tmp_path, "validation.json", _full_record())
    i = _write(tmp_path, "inputs.json", {"currency": "USD"})
    out = tmp_path / "sizing.json"
    rc, stdout, stderr = _run_sizing(
        tmp_path, _merged(tmp_path), "--validation", str(v), "--inputs", str(i), "-o", str(out), "--run-id", "R1"
    )
    assert rc == 0, stdout + stderr
    sizing = json.loads(out.read_text())
    prov = sizing["input_provenance"]
    assert set(prov) == set(_params.PARAM_UNITS)
    assert sizing["provenance_version"] == 1
    assert sizing["top_down"]["tam"]["value"] == pytest.approx(41_000_000 * 157 * 12)
    assert sizing["bottom_up"]["tam"]["value"] == pytest.approx(232_800 * 1884)
    assert prov["share_pct"]["kind"] == "estimate"
    assert sizing["input_refs"]["segment_pct"] == {"assumption": "segment_pct"}


def test_a_head_count_as_the_industry_total_is_refused_and_the_rejection_kept(tmp_path: Path) -> None:
    record = _full_record()
    record["assumptions"].append(_sourced("industry_total", 36_000_000, "count"))
    v = _write(tmp_path, "validation.json", record)
    i = _write(tmp_path, "inputs.json", {"currency": "USD"})
    out = tmp_path / "sizing.json"
    out.write_text('{"sentinel": true}')
    refs = {**_TD_REFS, "industry_total": {"assumption": "industry_total"}}
    rc, stdout, stderr = _run_sizing(
        tmp_path, refs, "--validation", str(v), "--inputs", str(i), "-o", str(out), "--run-id", "R1"
    )
    assert rc != 0 and stderr
    assert "E_UNIT_MISMATCH" in stdout
    assert json.loads(out.read_text()) == {"sentinel": True}
    kept = json.loads((tmp_path / "handoff" / "R1" / "unit_rejections.json").read_text())
    assert kept == [{"param": "industry_total", "name": "industry_total", "value": 36_000_000, "unit": "count"}]


def test_references_without_the_record_are_refused(tmp_path: Path) -> None:
    rc, stdout, _ = _run_sizing(tmp_path, _TD_REFS)
    assert rc != 0 and "E_REF_CONTEXT_MISSING" in stdout


def test_a_caller_rate_is_refused_on_the_reference_path(tmp_path: Path) -> None:
    v = _write(tmp_path, "validation.json", _full_record())
    i = _write(tmp_path, "inputs.json", {"currency": "USD"})
    rc, stdout, _ = _run_sizing(
        tmp_path, _TD_REFS, "--validation", str(v), "--inputs", str(i), "--fx-rate", "USD:ILS=3.7"
    )
    assert rc != 0 and "E_FX_ON_REFERENCE_PATH" in stdout


def test_a_recorded_rate_converts_and_the_conversion_is_disclosed(tmp_path: Path) -> None:
    record = _full_record()
    record["assumptions"].append(
        _sourced("usd_ils", 3.7, "fx_rate", **{"from": "USD", "to": "ILS", "as_of": "2026-09-01"})
    )
    v = _write(tmp_path, "validation.json", record)
    i = _write(tmp_path, "inputs.json", {"currency": "ILS"})
    out = tmp_path / "sizing.json"
    rc, stdout, stderr = _run_sizing(
        tmp_path, _BU_REFS, "--validation", str(v), "--inputs", str(i), "--currency", "ILS", "-o", str(out)
    )
    assert rc == 0, stdout + stderr
    sizing = json.loads(out.read_text())
    conv = sizing["fx"]["conversions"]
    assert conv == [
        {
            "field": "arpu",
            "from": "USD",
            "to": "ILS",
            "rate": 3.7,
            "original_value": pytest.approx(1884),
            "converted_value": pytest.approx(1884 * 3.7),
        }
    ]
    assert sizing["fx"]["as_of"] == "2026-09-01" and sizing["fx"]["source"] == _SRC["url"]


def test_replay_re_resolves_the_sizing_against_the_current_record(tmp_path: Path) -> None:
    record = _full_record()
    v = _write(tmp_path, "validation.json", record)
    i = _write(tmp_path, "inputs.json", {"currency": "USD"})
    out = tmp_path / "sizing.json"
    assert _run_sizing(tmp_path, _BU_REFS, "--validation", str(v), "--inputs", str(i), "-o", str(out))[0] == 0
    for a in record["assumptions"]:
        if a["name"] == "addressable_accounts":
            a["value"] = 100_000
    v.write_text(json.dumps(record))
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "market_sizing.py"),
            "--replay",
            str(out),
            "--validation",
            str(v),
            "--inputs",
            str(i),
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sizing = json.loads(out.read_text())
    assert sizing["input_provenance"]["customer_count"]["value_consumed"] == 100_000
    assert sizing["bottom_up"]["tam"]["value"] == pytest.approx(100_000 * 1884)


def test_the_numeric_path_is_stamped_as_not_checked(tmp_path: Path) -> None:
    out = tmp_path / "sizing.json"
    rc, stdout, stderr = _run_sizing(
        tmp_path, {"approach": "top_down", "industry_total": 1e9, "segment_pct": 10, "share_pct": 5}, "-o", str(out)
    )
    assert rc == 0, stdout + stderr
    prov = json.loads(out.read_text())["input_provenance"]
    assert {p["kind"] for p in prov.values()} == {"not_checked"}


# --- the render currency does not outlive the render ------------------------------------------------


def _load_by_path(stem: str, alias: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(alias, _SCRIPTS / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ils_dir(tmp_path: Path) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_market_sizing import _all_artifacts, _make_artifact_dir

    arts = _all_artifacts()
    arts["inputs.json"] = {**arts["inputs.json"], "currency": "ILS"}
    return _make_artifact_dir(arts)


@pytest.mark.parametrize("renderer", ["compose_report", "visualize"])
def test_a_render_in_one_currency_does_not_change_how_the_next_one_formats(tmp_path: Path, renderer: str) -> None:
    """Both renderers share `_view`'s currency. In a CLI that is one render per process; in a test
    session it is every render, so a render must leave the default as it found it."""
    view = importlib.import_module("_view")
    mod = _load_by_path(renderer, f"_ms_{renderer}_currency_scope")
    entry = mod.compose if renderer == "compose_report" else mod.compose_html
    entry(_ils_dir(tmp_path))
    assert view._fmt_usd(1_500_000) == "$1.5M"


def test_a_render_that_fails_partway_still_leaves_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    view = importlib.import_module("_view")
    mod = _load_by_path("compose_report", "_ms_compose_currency_raise")

    def boom(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("a section failed after the currency was set")

    monkeypatch.setattr(mod, "_section_sizing_table", boom)
    with pytest.raises(RuntimeError):
        mod.compose(_ils_dir(tmp_path))
    assert view._fmt_usd(1_500_000) == "$1.5M"
