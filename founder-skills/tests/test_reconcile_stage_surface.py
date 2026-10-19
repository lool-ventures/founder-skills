#!/usr/bin/env python3
"""Pin the names an offline comparison of reconcile.py runs it by, stage by stage.

`build()` is the engine's one entry point for the skill, but a before-and-after comparison of an
engine change runs its stages one at a time (load, merge range twins, verify, compute, supersede,
downgrade, select) and reads fields off each figure and relation. Renaming one of them breaks that
comparison where nothing in the skill notices. This file names them, so a rename is a deliberate
edit here too.

Run: uv run pytest founder-skills/tests/test_reconcile_stage_surface.py -q
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).parent
SCRIPTS = HERE.parent / "skills" / "deck-review" / "scripts"
sys.path[:0] = [str(SCRIPTS)]

import reconcile as R  # type: ignore[import-not-found]  # noqa: E402

STAGES = {
    "load_figures": ["ledger"],
    "merge_range_twins": ["figures"],
    "verify": ["figures", "transcript", "quote_in_doc"],
    "compute": ["rel_spec", "by_id"],
    "supersede": ["relations"],
    "apply_downgrades": ["relations", "downgrades"],
    "select": ["relations", "max_derived", "max_rounding_gaps"],
    "build": ["ledger", "transcript", "rel_specs", "inventory", "slides_transcribed", "downgrades"],
    "figure_tolerance": ["fig"],
    "duration_tolerance": ["fig"],
    "numeral_form": ["raw"],
    "bps_factor": ["raw"],
}

FIGURE_FIELDS = {"id", "value", "raw", "unit_kind", "lo", "hi", "verified", "attribution", "bound", "drop_reason"}

RELATION_FIELDS = {
    "operator",
    "operands",
    "expected_id",
    "verdict",
    "dropped",
    "computed",
    "span_lo",
    "span_hi",
    "confidence",
    "gap_basis",
    "untested_claim",
    "reasons",
    "rendered",
}


@pytest.mark.parametrize("name", sorted(STAGES))
def test_each_stage_keeps_its_name_and_parameters(name: str) -> None:
    fn = getattr(R, name, None)
    assert callable(fn), f"reconcile.{name} is gone or renamed"
    params = list(inspect.signature(fn).parameters)
    assert params[: len(STAGES[name])] == STAGES[name], f"reconcile.{name}{inspect.signature(fn)}"


def test_quote_in_doc_is_reachable_from_the_engine() -> None:
    assert callable(R.quote_in_doc)


def test_reviewable_verdicts_are_the_two_the_interpretation_pass_reads() -> None:
    assert tuple(R.REVIEWABLE_VERDICTS) == ("contradiction", "rounding_gap")


def test_a_figure_keeps_the_fields_a_comparison_reads() -> None:
    names = {f.name for f in dataclasses.fields(R.Figure)}
    assert names >= FIGURE_FIELDS, sorted(FIGURE_FIELDS - names)


def test_a_relation_keeps_the_fields_a_comparison_reads() -> None:
    names = {f.name for f in dataclasses.fields(R.Relation)}
    assert names >= RELATION_FIELDS, sorted(RELATION_FIELDS - names)


def test_merge_range_twins_returns_figures_and_an_alias_map() -> None:
    figures, alias = R.merge_range_twins([])
    assert list(figures) == [] and dict(alias) == {}
