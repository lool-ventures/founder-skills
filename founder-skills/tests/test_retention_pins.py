#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Data a skill promises to retain must reach a rendered deliverable.

Several skills compute or capture something specifically so a founder can see
it later -- a defaulted field the agent had to fill in, a term sheet's terms,
an amendment's clause changes -- and it is not enough for that content to
exist in an intermediate artifact; it has to reach the report the founder
actually reads. Both cases pinned here were live defects (the data was
extracted/computed and then never rendered); both are now fixed. This file
locks the fix in and gives a future retention promise a place to land.

This is a REGRESSION PIN over a hand-seeded registry, not a class-level gate:
it can only check retention promises listed below. It cannot discover a
promise nobody registered here.

Registry (skill / promise / how populated / what must appear):
  - financial-model-review / agent-supplied defaults: computation-feeding
    fields the agent defaulted rather than the founder stating are disclosed
    under "## Agent-Supplied Values". Populated via inputs.json's top-level
    `agent_supplied` list of field paths. Driven directly through
    compose_report.compose().
  - cap-table / term-sheet extraction: a term_sheet or option_plan document
    extracted alongside a cap-table engagement (extraction_audit.json) has
    its field values rendered under "## Term sheet terms (as extracted)".
    Driven through the real cap_state.py + compose_report.py CLI pipeline.
  - cap-table / amendment extraction: an amendment document's clause deltas
    are rendered under "## Amendments (terms modified)". Same pipeline,
    a different extraction_audit.json shape (classified_doc_type ==
    "amendment").

Each entry asserts on the planted VALUE reaching the output, not on a section
heading string -- matching a heading alone would pass a renderer that always
prints an empty section, and would break on a harmless reword. The negative
case (nothing promised) is the exception: with no value to check for, the
correct assertion IS that the section never appears, which is what actually
distinguishes a gated renderer from one that always prints something.

Run: pytest founder-skills/tests/test_retention_pins.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FMR_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "financial-model-review", "scripts")
CAP_TABLE_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "cap-table", "scripts")


def _load_module(path: str, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_fmr_compose_module() -> Any:
    return _load_module(
        os.path.join(FMR_SCRIPTS_DIR, "compose_report.py"),
        "retention_pin_fmr_compose_report_module",
    )


def _run_cap_table_script(name: str, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, os.path.join(CAP_TABLE_SCRIPTS_DIR, name), *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# financial-model-review: inputs.json's `agent_supplied` -> "## Agent-Supplied
# Values" in the composed report (compose_report.py's _section_agent_supplied).
# ---------------------------------------------------------------------------


def test_agent_supplied_field_path_reaches_the_report() -> None:
    """A field the agent defaulted (declared in inputs.json's `agent_supplied`)
    must show up in the composed report, not just sit in the intermediate
    inputs.json artifact."""
    mod = _load_fmr_compose_module()
    marker = "revenue.growth_rate_monthly.AGENT_SUPPLIED_MARKER_7f3a"
    with tempfile.TemporaryDirectory(prefix="test-retention-fmr-") as d:
        inputs = {"company": {"company_name": "TestCo"}, "agent_supplied": [marker]}
        with open(os.path.join(d, "inputs.json"), "w", encoding="utf-8") as f:
            json.dump(inputs, f)
        result = mod.compose(d)
    md = result["report_markdown"]
    assert marker in md, f"agent_supplied field path did not reach the composed report:\n{md}"


def test_absent_agent_supplied_renders_no_section() -> None:
    """The common case (nothing defaulted) must not print an empty or spurious
    'Agent-Supplied Values' section -- otherwise a working renderer and one
    that always prints a section look identical from the positive case alone."""
    mod = _load_fmr_compose_module()
    with tempfile.TemporaryDirectory(prefix="test-retention-fmr-") as d:
        inputs = {"company": {"company_name": "TestCo"}}
        with open(os.path.join(d, "inputs.json"), "w", encoding="utf-8") as f:
            json.dump(inputs, f)
        result = mod.compose(d)
    md = result["report_markdown"]
    assert "Agent-Supplied Values" not in md


# ---------------------------------------------------------------------------
# cap-table: extraction_audit.json (term_sheet / option_plan / amendment) ->
# "## Term sheet terms (as extracted)" / "## Amendments (terms modified)" in
# the full-pipeline report (compose_report.py's render_report_markdown).
# ---------------------------------------------------------------------------

_RUN_ID = "retention-pin-test"

_CAP_TABLE_INPUTS: dict[str, Any] = {
    "company_name": "Acmecorp",
    "analysis_date": "2026-05-19",
    "mode": "standard",
    "jurisdiction": {
        "structure": "delaware",
        "incorporated_date": "2024-01-01",
        "iia_grants_history": {"has_grants": False, "grant_details": []},
    },
    "founders": [
        {"name": "Alice", "founder_id": "founder_alice", "common_shares": 5_000_000},
        {"name": "Bob", "founder_id": "founder_bob", "common_shares": 5_000_000},
    ],
    "preferred_series": [],
    "option_pool": {"plan_type": "nso", "authorized": 1_500_000, "issued": 500_000, "unallocated": 1_000_000},
    "common_batches": [],
    "metadata": {"run_id": _RUN_ID},
}

_CAP_TABLE_INSTRUMENTS: dict[str, Any] = {
    "safes": [],
    "convertible_notes": [],
    "warrants": [],
    "option_grants": [],
    "metadata": {"run_id": _RUN_ID},
}


def _build_cap_table_compose_dir(extraction_audit: dict[str, Any] | None) -> str:
    """A minimal cap-table engagement directory. inputs.json/instruments.json are
    driven through the real cap_state.py producer (not hand-assembled); the other
    required-but-irrelevant-to-this-test artifacts are stubbed directly, matching
    the shape the skill's own compose fixtures use."""
    d = tempfile.mkdtemp(prefix="test-retention-captable-")
    inputs = json.loads(json.dumps(_CAP_TABLE_INPUTS))
    instruments = json.loads(json.dumps(_CAP_TABLE_INSTRUMENTS))
    inputs_path = os.path.join(d, "inputs.json")
    instruments_path = os.path.join(d, "instruments.json")
    with open(inputs_path, "w", encoding="utf-8") as f:
        json.dump(inputs, f)
    with open(instruments_path, "w", encoding="utf-8") as f:
        json.dump(instruments, f)

    cap_state_path = os.path.join(d, "cap_state.json")
    rc, _, stderr = _run_cap_table_script(
        "cap_state.py",
        ["--inputs", inputs_path, "--instruments", instruments_path, "--run-id", _RUN_ID, "-o", cap_state_path],
    )
    assert rc == 0, f"cap_state.py failed to build the fixture cap state: {stderr}"

    for name, data in [
        (
            "rule_audit.json",
            {
                "gating": {},
                "applied_rules": [],
                "counsel_review_items": [],
                "date_sensitive_watchlist": [],
                "metadata": {"run_id": _RUN_ID},
            },
        ),
        ("scenarios.json", {"scenarios": [], "metadata": {"run_id": _RUN_ID}}),
        (
            "counsel_packet.json",
            {"company_name": "Acmecorp", "engagement_summary": "", "items": [], "metadata": {"run_id": _RUN_ID}},
        ),
    ]:
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    if extraction_audit is not None:
        with open(os.path.join(d, "extraction_audit.json"), "w", encoding="utf-8") as f:
            json.dump(extraction_audit, f)

    return d


def _run_cap_table_compose(d: str) -> dict[str, Any]:
    report_path = os.path.join(d, "report.json")
    md_path = os.path.join(d, "report.md")
    rc, _, stderr = _run_cap_table_script(
        "compose_report.py",
        ["--dir", d, "--run-id", _RUN_ID, "-o", report_path, "--write-md", md_path],
    )
    assert rc == 0, f"compose_report.py failed: {stderr}"
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def test_term_sheet_extraction_value_reaches_the_report() -> None:
    """A term_sheet field value extracted alongside a real cap-table engagement
    must reach the full-pipeline report, not just extraction_audit.json."""
    marker = "TERM_SHEET_LEAD_INVESTOR_MARKER_9c2e"
    extraction_audit = {
        "instrument_type": "term_sheet",
        "fields": {"lead_investor_name": marker},
        "confidence": {},
    }
    d = _build_cap_table_compose_dir(extraction_audit)
    report = _run_cap_table_compose(d)
    md = report["report_markdown"]
    assert marker in md, f"term-sheet extraction value did not reach the composed report:\n{md}"


def test_amendment_extraction_value_reaches_the_report() -> None:
    """An amendment's clause-delta description must reach the full-pipeline
    report, not just extraction_audit.json."""
    marker = "AMENDMENT_CLAUSE_DELTA_MARKER_4b1d"
    extraction_audit = {
        "classified_doc_type": "amendment",
        "ambiguities": [{"field": "valuation_cap", "description": marker}],
    }
    d = _build_cap_table_compose_dir(extraction_audit)
    report = _run_cap_table_compose(d)
    md = report["report_markdown"]
    assert marker in md, f"amendment clause delta did not reach the composed report:\n{md}"


def test_absent_extraction_audit_renders_neither_section() -> None:
    """The common pure-SAFE/note engagement (no term sheet, no amendment) must
    not print either section -- otherwise a working renderer and one that
    always prints a section look identical from the positive cases alone."""
    d = _build_cap_table_compose_dir(None)
    report = _run_cap_table_compose(d)
    md = report["report_markdown"]
    assert "Term sheet terms (as extracted)" not in md
    assert "Amendments (terms modified)" not in md


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
