"""The market-sizing agent body's worked examples must be accepted by the calculator they teach.

A live run spent three of nine sub-agent dispatches on corrective redos, one per class: a top-down
industry_total built with a derived op whose units do not combine, a multi-stage funnel collapsed wrongly
into customer_count / serviceable_pct / target_pct, and sensitivity ranges keyed on an assumption's own
name instead of the calculator's parameter. Each class gets one worked example in the agent body. An
example the calculator would refuse teaches the redo it exists to prevent, so every example is resolved
here by the calculator's own resolver, against recorded figures carrying the units they would have.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "skills" / "market-sizing" / "scripts"
_AGENT = _ROOT / "agents" / "market-sizing.md"


def _load(name: str) -> types.ModuleType:
    sys.path.insert(0, str(_SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(f"ms_worked_{name}", _SCRIPTS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


PROV = _load("_provenance")
PARAMS = _load("_params")

# The recorded figures the examples name, with the units their sources would state.
_RECORDED: list[dict[str, Any]] = [
    {"name": "trades_contractor_count", "value": 250_000, "unit": "count"},
    {"name": "fsm_price_per_account", "value": 300, "unit": "money_per_customer", "currency": "USD", "period": "month"},
    {"name": "share_with_five_plus_techs", "value": 30, "unit": "percent_points"},
    {"name": "share_using_scheduling_software", "value": 40, "unit": "percent_points"},
    {"name": "expected_win_share", "value": 2, "unit": "percent_points"},
    {"name": "us_small_business_count", "value": 30_000_000, "unit": "count"},
]
for _entry in _RECORDED:
    _entry.update({"category": "sourced", "source_title": "Synthetic source"})
_VALIDATION = {"assumptions": _RECORDED, "sources": [{"title": "Synthetic source", "url": "https://example.org"}]}


def _section(heading: str) -> str:
    text = _AGENT.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n#### ", start + len(heading))
    return text[start : end if end != -1 else None]


def _worked_example(section: str) -> dict[str, Any]:
    at = section.index("Worked example")
    fence = section.index("```json", at)
    block = section[fence + len("```json") : section.index("```", fence + len("```json"))]
    parsed: dict[str, Any] = json.loads(block)
    return parsed


def _resolve(refs: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    resolved, errors = PROV.resolve(refs, validation=_VALIDATION, inputs={}, currency="USD")
    return resolved, errors


def test_the_top_down_example_resolves_to_money_per_year() -> None:
    example = _worked_example(_section("#### TOP_DOWN_METHODOLOGY subtype"))
    assert set(example) == {"industry_total"}, example
    resolved, errors = _resolve(example)
    assert errors == [], errors
    q = resolved["industry_total"]
    assert q["unit"] == "money_total_per_year"
    # 250,000 accounts x $300 a month = $900M a year: the monthly price is annualised by the calculator.
    assert q["value_consumed"] == 900_000_000


def test_the_top_down_counter_example_is_refused() -> None:
    """The example's neighbouring sentence says a count times a count does not combine; hold it to that."""
    bad = {
        "industry_total": {
            "derived": {
                "op": "multiply",
                "factors": [{"assumption": "us_small_business_count"}, {"assumption": "trades_contractor_count"}],
            }
        }
    }
    _resolved, errors = _resolve(bad)
    assert errors, "a count times a count must be refused, as the agent body says"


def test_the_funnel_example_resolves_each_stage_to_its_unit() -> None:
    example = _worked_example(_section("#### BOTTOM_UP_METHODOLOGY subtype"))
    assert {"customer_count", "serviceable_pct", "target_pct"} <= set(example), example
    resolved, errors = _resolve(example)
    assert errors == [], errors
    for param, q in resolved.items():
        assert q["unit"] == PARAMS.PARAM_UNITS[param], (param, q["unit"])
    # Two narrowing stages multiply into ONE percentage: 30% of 40% is 12%, not 1,200.
    assert resolved["serviceable_pct"]["value_consumed"] == 12


def test_the_sensitivity_section_names_exactly_the_calculators_parameters() -> None:
    section = _section("#### SENSITIVITY_TEST subtype")
    m = re.search(r"exactly one of: ([a-z_,`\s]+?)\s+—", section)
    assert m, "the SENSITIVITY_TEST section no longer lists the parameter names a range may use"
    named = {n.strip(" `\n") for n in m.group(1).split(",") if n.strip(" `\n")}
    assert named == set(PARAMS.PARAM_UNITS), (named, sorted(PARAMS.PARAM_UNITS))
