"""cap-table's coaching payload must never hand the sub-agent a raw warning code under a
founder-facing name.

The defect this pins: `high_severity_warnings` was built as
`{"warning_id": code, "severity": ..., "title": code, "detail": remedy}` -- two of four fields
were the same internal string, and one of them was called `title`. A coach told to write "the
title" writes `E_ACQUISITION_DOUBLE_SPECIFIED`. Measured across kept run dirs, when the payload
carried a `label` the coach used it (0 leaks in 28 warnings); when it carried a bare code the
code reached the founder's report (2 leaks in 16).

Two tests, deliberately:

1. `test_humanize_warning_never_returns_an_internal_code` runs the humanizer over EVERY `E_`/`W_`
   code literal in the skill's scripts. A per-code COVERAGE test ("every code has a dict entry")
   would red on the many codes that never reach a founder and would be deleted or suppressed --
   measured, financial-model-review carries 11 labels against 39 emitted codes. An OUTPUT-SHAPE
   test cannot rot: adding a code without an entry is fine, because the burden sits on the
   fallback, which is the thing that has to be right.

2. `test_payload_warnings_carry_a_label_not_a_code` drives the real producer. It seeds a blocker
   AND a solver warning, because the committed fixture
   (`tests/fixtures/cap-table/scenarios.json`) has exactly ONE scenario carrying zero blockers
   and zero warnings -- so a fixture-driven assertion here passes over an empty list and stays
   green with the defect restored. That is the `counsel_packet.md` trap: the scan that found
   nothing because there was nothing to find.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"

# An internal code as a founder would see it: ALLCAPS run with at least one underscore.
INTERNAL_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
CODE_LITERAL = re.compile(r"[\"']([EW]_[A-Z0-9_]{3,})[\"']")


def _load(name: str) -> Any:
    """Import a cap-table script standalone, the way the skill runs it."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _every_code_literal() -> set[str]:
    codes: set[str] = set()
    for p in SCRIPTS.glob("*.py"):
        codes.update(CODE_LITERAL.findall(p.read_text(encoding="utf-8")))
    return codes


def test_the_corpus_of_codes_is_not_empty() -> None:
    """Guard the guard: a broken regex would make the next test vacuous."""
    codes = _every_code_literal()
    assert len(codes) >= 40, f"only {len(codes)} code literals found -- the scraper is broken"


def test_humanize_warning_never_returns_an_internal_code() -> None:
    wc = _load("_warning_callouts")
    offenders = []
    for code in sorted(_every_code_literal()):
        label = wc.humanize_warning(code)
        if INTERNAL_CODE.search(label):
            offenders.append((code, label))
    assert not offenders, (
        "humanize_warning returned an internal-code-shaped label -- a founder reads this:\n"
        + "\n".join(f"  {c} -> {label}" for c, label in offenders[:10])
    )


def test_payload_warnings_carry_a_label_not_a_code() -> None:
    """The producer's own output, over SEEDED blockers and solver warnings."""
    compose = _load("compose_report")
    scenarios_doc = {
        "scenarios": [
            {
                "scenario_id": "s1",
                "label": "Priced round",
                "type": "priced_round",
                "computed_outputs": {
                    "completeness": "structural_only",
                    "blockers": [
                        {
                            "code": "E_CAP_IMPLIED_NOTES_PRESENT",
                            "instance_id": None,
                            "remedy": "Model the priced round so the notes convert.",
                        }
                    ],
                    "warnings": [
                        {
                            "code": "W_MFN_NOT_MOST_FAVORABLE",
                            "detail": "The election was modelled against the terms it named.",
                        }
                    ],
                },
            }
        ]
    }
    payload = compose.build_coaching_payload(
        artifacts={
            "inputs.json": {"company_name": "Test Co", "mode": "standard"},
            "instruments.json": {},
            "scenarios.json": scenarios_doc,
            "rule_audit.json": {},
            "counsel_packet.json": {"items": []},
        },
        review_dir="/tmp/review",
        report_path="/tmp/review/report.md",
        insertion_marker="<!-- COACHING_INSERTION_POINT_test -->",
    )

    warnings = payload["high_severity_warnings"]
    assert warnings, "seeded a blocker and a solver warning but the payload carries neither"

    for w in warnings:
        assert "title" not in w, "`title` is gone -- it held the raw code under a prose-sounding name"
        assert "warning_id" not in w, "`warning_id` is gone -- it had no readers"
        assert not INTERNAL_CODE.search(w["label"]), f"label is an internal code: {w['label']!r}"

    for item in payload["failed_items"]:
        assert not INTERNAL_CODE.search(item["label"]), f"failed_items label is a code: {item['label']!r}"


@pytest.mark.parametrize("code", ["E_CAP_IMPLIED_NOTES_PRESENT", "W_MFN_NOT_MOST_FAVORABLE"])
def test_the_prefix_is_stripped(code: str) -> None:
    """`E_`/`W_` is our severity vocabulary, not a word. It must not survive into a label."""
    wc = _load("_warning_callouts")
    assert not wc.humanize_warning(code).startswith(("E ", "W ", "E_", "W_"))
