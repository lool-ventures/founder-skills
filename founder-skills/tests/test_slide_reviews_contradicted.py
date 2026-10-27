"""slide_reviews.py's warn-only check: a strength that praises a figure reconciliation.json shows the deck got wrong.

A hit is a strength on the stated figure's own slide that writes its numerals, where the figure is the
`expected_id` of a kept relation with verdict "contradiction". It never changes the artifact or the exit code.
The figures are synthetic.

Run: uv run pytest founder-skills/tests/test_slide_reviews_contradicted.py -q
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from types import ModuleType
from typing import Any

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "deck-review", "scripts", "slide_reviews.py"
)

_LEDGER = {
    "metadata": {"run_id": "r1"},
    "figures": [
        {"id": "runway", "raw": "22 months", "slide": 10, "label": "Runway"},
        {"id": "cash", "raw": "$1.2M", "slide": 9, "label": "Cash"},
        {"id": "burn", "raw": "$95K", "slide": 9, "label": "Monthly burn"},
        {"id": "customers", "raw": "2", "slide": 4, "label": "Paying customers"},
        {"id": "margin", "raw": "64%", "slide": 7, "label": "Gross margin"},
    ],
}
_CONTRADICTION = {"verdict": "contradiction", "expected_id": "runway", "rendered": "$1.2M ÷ $95K"}
_RECON: dict[str, Any] = {
    "metadata": {"run_id": "r1"},
    "status": "checked",
    "figures_total": 5,
    "figures_verified": 5,
    "relations": [_CONTRADICTION],
    "validation": {"status": "valid", "errors": [], "warnings": []},
}


def _load() -> ModuleType:
    scripts = os.path.dirname(SCRIPT)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("dr_slide_reviews_contradicted_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reviews(slide: int, strengths: list[str], weaknesses: list[str] | None = None) -> dict[str, Any]:
    return {
        "reviews": [
            {
                "slide_number": slide,
                "maps_to": "ask",
                "strengths": strengths,
                "weaknesses": weaknesses or [],
                "recommendations": [],
                "best_practice_refs": [],
            }
        ],
        "missing_slides": [],
        "overall_narrative_assessment": "",
    }


def _recon(*relations: dict[str, Any]) -> dict[str, Any]:
    return dict(_RECON, relations=list(relations))


def test_a_strength_praising_the_contradicted_figure_is_a_hit() -> None:
    mod = _load()
    data = _reviews(10, ["Clear ask.", 'Runway is stated: "22 months" is within the 18-24 month range.'])
    assert mod.contradicted_strengths(data, _RECON, _LEDGER) == ["slide 10 strengths[1]"]


@pytest.mark.parametrize(
    ("data", "recon"),
    [
        # Another slide, though it names the same figure.
        (_reviews(9, ["Runway of 22 months is stated."]), _RECON),
        # A weakness is where the finding belongs.
        (_reviews(10, [], ["Runway of 22 months is not what cash over burn gives."]), _RECON),
        # A figure that only contains the numerals is not the figure.
        (_reviews(10, ["A $22M post-money cap is in range."]), _RECON),
        # Only a contradiction counts.
        (_reviews(10, ["Runway of 22 months is stated."]), _recon(dict(_CONTRADICTION, verdict="derived"))),
        (_reviews(10, ["Runway of 22 months is stated."]), _recon(dict(_CONTRADICTION, verdict="confirmation"))),
        # A relation with no stated figure names none.
        (_reviews(10, ["Runway of 22 months is stated."]), _recon({"verdict": "contradiction"})),
    ],
)
def test_no_hit(data: dict[str, Any], recon: dict[str, Any]) -> None:
    assert _load().contradicted_strengths(data, recon, _LEDGER) == []


def test_a_spelled_small_number_is_not_the_figure() -> None:
    mod = _load()
    recon = _recon(dict(_CONTRADICTION, expected_id="customers"))
    assert mod.contradicted_strengths(_reviews(4, ["Two founders with domain depth."]), recon, _LEDGER) == []
    assert mod.contradicted_strengths(_reviews(4, ["2 paying customers already."]), recon, _LEDGER) == [
        "slide 4 strengths[0]"
    ]


def test_a_percent_figure_is_matched_as_written() -> None:
    mod = _load()
    recon = _recon(dict(_CONTRADICTION, expected_id="margin"))
    assert mod.contradicted_strengths(_reviews(7, ["Gross margin of 64% is strong."]), recon, _LEDGER) == [
        "slide 7 strengths[0]"
    ]
    assert mod.contradicted_strengths(_reviews(7, ["64 enterprise logos."]), recon, _LEDGER) == []


def _write_inputs(d: str) -> list[str]:
    paths = {}
    for name, body in (("reconciliation.json", _RECON), ("ledger.json", _LEDGER)):
        paths[name] = os.path.join(d, name)
        with open(paths[name], "w", encoding="utf-8") as fh:
            json.dump(body, fh)
    deck_text = os.path.join(d, "deck_text.md")
    with open(deck_text, "w", encoding="utf-8") as fh:
        fh.write("---\nrun_id: r1\nsource: pasted\npages_source: {10: pasted}\n---\n## Slide 10\n\nText\n")
    out = os.path.join(d, "slide_reviews.json")
    return [
        "--run-id",
        "r1",
        "-o",
        out,
        "--reconciliation",
        paths["reconciliation.json"],
        "--ledger",
        paths["ledger.json"],
        "--deck-text",
        deck_text,
    ]


def _main(mod: ModuleType, args: list[str], data: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["slide_reviews.py", *args])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    return int(mod.main())


def test_the_pipe_warns_and_writes_the_reviews_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _reviews(10, ['Runway is stated: "22 months".'])
    with tempfile.TemporaryDirectory() as d:
        args = _write_inputs(d)
        assert _main(_load(), args, data, monkeypatch) == 0
        out = capsys.readouterr()
        receipt = json.loads(out.out)
        assert receipt["contradicted_strengths"] == {"hits": 1}
        assert "contradicted_strengths: slide 10 strengths[0]" in out.err
        assert "22 months" not in out.err  # where, never what
        with open(args[3], encoding="utf-8") as fh:
            written = json.load(fh)
        assert {k: v for k, v in written.items() if k != "metadata"} == {
            k: v for k, v in data.items() if k != "metadata"
        }


def test_a_check_that_fails_leaves_the_pipe_green(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load()

    def boom(*_: Any) -> list[str]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(mod, "contradicted_strengths", boom)
    with tempfile.TemporaryDirectory() as d:
        args = _write_inputs(d)
        assert _main(mod, args, _reviews(10, ["Runway of 22 months."]), monkeypatch) == 0
        out = capsys.readouterr()
        assert "contradicted_strengths" not in json.loads(out.out)
        assert "contradicted_strengths: not checked (RuntimeError)" in out.err
        assert os.path.exists(args[3])
