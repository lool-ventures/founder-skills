"""Market-sizing quoted passages: the matcher, the producer's stamp, and the one sentence both pages print.

A research entry may carry a `quote`, the passage of its source that states the figure. `_quote_value.py`
decides whether the recorded figure is written in it, `market_sizing.py` stamps the answer per entry
(`quote_checks`), and `_view.quote_sentence` says for how many of the sourced market figures the sizing uses a
passage containing the figure was recorded. All figures here are synthetic.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "market-sizing" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

_quote_value = importlib.import_module("_quote_value")
_view = importlib.import_module("_view")
_sizing_redo = importlib.import_module("_sizing_redo")


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_compose = _load("ms_compose_quotes", "compose_report.py")
_visualize = _load("ms_visualize_quotes", "visualize.py")

_SRC = {"title": "Synthetic Industry Survey", "url": "https://example.org/survey", "quality_tier": "analyst_firm"}


def _q(value: Any, unit: str, quote: Any) -> bool:
    return bool(_quote_value.quote_matches({"value": value, "unit": unit, "quote": quote}))


# --- the matcher -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "quote", "expected"),
    [
        pytest.param(7_834_000_000, "money_total_per_year", "It reached $7.83 billion.", True, id="sigfig-window"),
        pytest.param(6_400_000_000, "money_total_per_year", "about 6,400 million dollars", True, id="million-form"),
        pytest.param(6_400_000_000, "money_total_per_year", "USD 6.4bn in sales", True, id="bn-suffix"),
        pytest.param(6_400_000_000, "money_total_per_year", "$6.4B", True, id="b-suffix"),
        pytest.param(3_100_000_000_000, "money_total_per_year", "a 3.1 trillion market", True, id="trillion"),
        pytest.param(1_020_000_000, "money_total_per_year", "roughly 1 billion", True, id="round-within-cap"),
        pytest.param(1_400_000_000, "money_total_per_year", "roughly 1 billion", False, id="round-capped-at-5pct"),
        pytest.param(12_000, "count", "12,000 clinics", True, id="count-grouped"),
        pytest.param(12_000, "count", "12 thousand clinics", True, id="count-scale-word"),
        pytest.param(35, "percent_points", "35% of firms", True, id="percent-with-sign"),
        pytest.param(35, "percent_points", "35 percent of firms", True, id="percent-word"),
        pytest.param(35, "percent_points", "35 firms", False, id="percent-needs-sign"),
        pytest.param(0.07, "fraction", "7% adopt it", True, id="fraction-times-100-rounded"),
        pytest.param(0.4, "fraction", "40 companies", False, id="fraction-needs-sign"),
        pytest.param(-5, "percent_change", "declined 5% last year", True, id="change-magnitude"),
        pytest.param(2.5, "ratio", "2.5 seats per account", True, id="ratio"),
        pytest.param(5, "years", "within 5 years", True, id="years"),
        pytest.param(3.72, "fx_rate", "3.72", False, id="fx-never"),
        pytest.param(10, "an_unlisted_unit", "10", False, id="unlisted-unit"),
        pytest.param(42, "count", None, False, id="no-quote"),
        pytest.param(42, "count", "42 " + "x" * 1000, False, id="over-the-cap"),
        pytest.param(True, "count", "1 clinic", False, id="bool-value"),
    ],
)
def test_the_matcher(value: Any, unit: str, quote: Any, expected: bool) -> None:
    assert _q(value, unit, quote) is expected


def test_known_false_matches_are_pinned() -> None:
    """Accepted residuals, named in the module docstring: the sign of a change, and a round number by chance."""
    assert _q(-5, "percent_change", "grew 5% last year")
    assert _q(50, "percent_points", "50% of an unrelated group")


def test_a_repeated_name_writes_no_stamp() -> None:
    record = {"assumptions": [{"name": "a", "value": 1, "unit": "count"}, {"name": "a", "value": 2, "unit": "count"}]}
    assert _quote_value.quote_checks(record) is None


# --- the redo record ignores a quote ---------------------------------------------------------------


def test_a_quote_is_not_a_change_to_the_research() -> None:
    entry = {"name": "accounts", "value": 42_000, "unit": "count", "category": "sourced"}
    before = _sizing_redo.research_digest({"assumptions": [entry]})
    after = _sizing_redo.research_digest({"assumptions": [{**entry, "quote": "42,000 accounts"}]})
    assert before == after
    assert before != _sizing_redo.research_digest({"assumptions": [{**entry, "value": 43_000}]})


# --- the producer's stamp, from a real by-reference run --------------------------------------------


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


def _validation(*, accounts_quote: str | None, reachable_quote: str | None) -> dict[str, Any]:
    accounts = _sourced("accounts", 42_000, "count", **({"quote": accounts_quote} if accounts_quote else {}))
    reachable = _sourced("reachable", 30, "percent_points", **({"quote": reachable_quote} if reachable_quote else {}))
    return {
        "sources": [_SRC],
        "assumptions": [
            accounts,
            reachable,
            {"name": "capture", "value": 4, "unit": "percent_points", "category": "agent_estimate"},
            _sourced("context_only", 9_000, "count", quote="9,000 firms"),
        ],
        "figure_validations": [],
        "metadata": {"run_id": "run-quotes"},
    }


def _size(tmp_path: Path, validation: dict[str, Any]) -> dict[str, Any]:
    inputs = json.loads((Path(__file__).parent / "fixtures" / "market-sizing" / "inputs.json").read_text())
    inputs["founder_stated_inputs"] = {"arpu": 90}
    inputs["founder_stated_inputs_period"] = {"arpu": "month"}
    (tmp_path / "inputs.json").write_text(json.dumps(inputs))
    (tmp_path / "validation.json").write_text(json.dumps(validation))
    refs = {
        "approach": "bottom_up",
        "customer_count": {"assumption": "accounts"},
        "serviceable_pct": {"assumption": "reachable"},
        "arpu": {"founder_stated": "arpu"},
        "target_pct": {"assumption": "capture"},
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "market_sizing.py"),
            "--stdin",
            "--run-id",
            "run-quotes",
            "--validation",
            str(tmp_path / "validation.json"),
            "--inputs",
            str(tmp_path / "inputs.json"),
            "-o",
            str(tmp_path / "sizing.json"),
        ],
        input=json.dumps(refs),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sizing: dict[str, Any] = json.loads((tmp_path / "sizing.json").read_text())
    return sizing


def test_the_stamp_covers_every_entry_and_the_sentence_counts_the_used_sourced_ones(tmp_path: Path) -> None:
    validation = _validation(accounts_quote="the survey counts 42,000 accounts", reachable_quote="about a third")
    sizing = _size(tmp_path, validation)
    assert sizing["quote_checks"] == {"accounts": True, "reachable": False, "capture": False, "context_only": True}
    # M: accounts and reachable (used, sourced). Not capture (an estimate), not context_only (unused).
    sentence = _view.quote_sentence(validation, sizing)
    assert sentence == (
        "Of the 2 sourced market figures this sizing uses (exchange rates not counted), 1 has a recorded passage "
        "containing the figure."
    )


def test_m_equals_the_unmarked_sourced_rows_report_md_lists(tmp_path: Path) -> None:
    validation = _validation(accounts_quote="42,000 accounts", reachable_quote="30% are reachable")
    sizing = _size(tmp_path, validation)
    listed = _compose._section_assumptions(validation, sizing)
    used_sourced = [
        line for line in listed.splitlines() if "(Sourced)" in line and "not used in the sizing" not in line
    ]
    assert len(used_sourced) == 2, listed
    assert "Of the 2 sourced market figures" in str(_view.quote_sentence(validation, sizing))


def test_the_sentence_reads_the_stamp_not_a_later_edit(tmp_path: Path) -> None:
    validation = _validation(accounts_quote=None, reachable_quote=None)
    sizing = _size(tmp_path, validation)
    edited = _validation(accounts_quote="42,000 accounts", reachable_quote="30% are reachable")
    assert "0 have" in str(_view.quote_sentence(edited, sizing))


def test_no_stamp_or_a_missing_entry_means_no_sentence(tmp_path: Path) -> None:
    validation = _validation(accounts_quote="42,000 accounts", reachable_quote=None)
    sizing = _size(tmp_path, validation)
    old = {k: v for k, v in sizing.items() if k != "quote_checks"}
    assert _view.quote_sentence(validation, old) is None
    partial = {**sizing, "quote_checks": {"accounts": True}}
    assert _view.quote_sentence(validation, partial) is None


def test_a_rate_entry_and_a_unit_outside_the_registry_are_not_counted() -> None:
    validation = {
        "sources": [_SRC],
        "assumptions": [
            _sourced("market", 1_000_000_000, "money_total_per_year", currency="USD", quote="$1.0 billion"),
            _sourced("fx_usd_eur", 0.92, "fx_rate", **{"from": "USD", "to": "EUR", "as_of": "2026-01-01"}),
            _sourced("odd", 7, "widgets"),
        ],
    }
    sizing = {
        "provenance_version": 1,
        "input_provenance": {
            "industry_total": {
                "entries": ["odd", "market", "fx_usd_eur"],
                "kind": "assumption",
            }
        },
        "quote_checks": {"market": True, "fx_usd_eur": False, "odd": False},
    }
    assert _view.quote_sentence(validation, sizing) == (
        "The one sourced market figure this sizing uses (exchange rates not counted) has a recorded passage "
        "containing the figure."
    )


def test_a_same_figure_entry_counts() -> None:
    validation = {"sources": [_SRC], "assumptions": [_sourced("price", 90, "money_per_customer", period="month")]}
    sizing = {
        "provenance_version": 1,
        "input_provenance": {"arpu": {"kind": "founder_stated", "entries": [], "same_figure_entries": ["price"]}},
        "quote_checks": {"price": False},
    }
    assert "does not have" in str(_view.quote_sentence(validation, sizing))


# --- both pages print it --------------------------------------------------------------------------


def test_both_pages_print_the_sentence_including_when_every_figure_is_quoted(tmp_path: Path) -> None:
    validation = _validation(accounts_quote="42,000 accounts", reachable_quote="30% are reachable")
    sizing = _size(tmp_path, validation)
    sentence = _view.quote_sentence(validation, sizing)
    assert sentence and "2 have" in sentence
    assert sentence in _compose._section_sources(validation, sizing)
    assert sentence in _visualize._chart_confidence_donut(validation, sizing)
    assert sentence not in _compose._section_sources(validation, None)
