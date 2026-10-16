"""One owner per skill of the score string and the verdict, and one fleet format.

Each skill's report.md and its pages print the checklist score (and, in deck-review and
financial-model-review, the verdict beside it) from one module of the skill's own:

  * deck-review: `_dr_score_view.py` (score, band, the band's verdict sentence, the criteria count);
  * financial-model-review: `_fmr_score_view.py` (score, and which score the review headlines under which
    name, the one choice report.md, the report page and the explorer make);
  * ic-sim: `_ic_view.py`; competitive-positioning: `_cp_view.py`.

The format is the fleet's: one decimal at most and no trailing zero ("63%", "97.7%", "20.6%"), which is
`_ui.score_text`'s default. No owner imports `_ui`: compose loads these modules, and the report builder's
process must not start loading the page module. So each owner carries the one-line format, and the first
test holds every copy equal to `_ui.score_text`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _dom import Element, parse
from compose_invocations import drive_compose
from no_ledger_goldens import FIXTURES, html_argv

_ROOT = Path(__file__).resolve().parents[1]
_SKILLS = _ROOT / "skills"

# (skill, owner module, how its `score_text` takes a score)
_OWNERS: tuple[tuple[str, str, str], ...] = (
    ("deck-review", "_dr_score_view", "pct"),
    ("financial-model-review", "_fmr_score_view", "pct"),
    ("ic-sim", "_ic_view", "summary"),
    ("competitive-positioning", "_cp_view", "pct"),
)
_VALUES = (0, 0.0, 20.6, 21.0, 37.84, 63.0, 63.7, 97.7, 100.0, 100)


def _load(skill: str, module: str) -> ModuleType:
    """The owner, loaded by path under a name of its own, so two skills' modules never share `sys.modules`."""
    path = _SKILLS / skill / "scripts" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"_score_owner_{skill.replace('-', '_')}_{module}", path)
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ui() -> ModuleType:
    return _load("deck-review", "_ui")


@pytest.mark.parametrize(("skill", "module", "takes"), _OWNERS, ids=[o[0] for o in _OWNERS])
def test_every_owner_prints_the_fleet_format(skill: str, module: str, takes: str) -> None:
    owner, ui = _load(skill, module), _ui()
    for value in _VALUES:
        got = owner.score_text({"conviction_score": value} if takes == "summary" else value)
        assert got == ui.score_text(value), (skill, value, got)
    # The format, stated once more without `_ui`, so a change there cannot carry every owner with it.
    assert ui.score_text(63.0) == "63" and ui.score_text(97.7) == "97.7" and ui.score_text(100.0) == "100"


@pytest.mark.parametrize(("skill", "module", "takes"), _OWNERS, ids=[o[0] for o in _OWNERS])
def test_no_owner_loads_the_page_module(skill: str, module: str, takes: str) -> None:
    """Imported in a fresh interpreter the way compose imports it (its folder on `sys.path`), the owner
    leaves neither `_ui` nor a page helper that loads it in `sys.modules`."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module(sys.argv[2]); "
        "print(sorted(m for m in ('_ui', '_checklist_view') if m in sys.modules))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(_SKILLS / skill / "scripts"), module],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", (skill, proc.stdout)


# ---------------------------------------------------------------------------------------------------------
# deck-review: an unknown band reads the same in the report and on the page
# ---------------------------------------------------------------------------------------------------------


def _page(skill: str, script: str, work: Path) -> Element:
    out = work / f"{script}.html"
    proc = subprocess.run([sys.executable, *html_argv(skill, script, work, out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return parse(out.read_text(encoding="utf-8"))


def _staged(skill: str, td: str) -> tuple[Path, Path]:
    fix, work = Path(td) / "fix", Path(td) / "work"
    shutil.copytree(FIXTURES / skill, fix)
    work.mkdir()
    return fix, work


def _edit(path: Path, change: Any) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


def test_deck_review_report_and_page_band_an_unknown_status_alike() -> None:
    """A checklist whose band the scripts do not know is banded from its score, by `_thresholds.band_for`,
    on both surfaces: the report used to print the raw token where the page printed the band's sentence."""
    with tempfile.TemporaryDirectory() as td:
        fix, work = _staged("deck-review", td)

        def change(ck: dict[str, Any]) -> None:
            ck["summary"]["score_pct"] = 63.0
            ck["summary"]["overall_status"] = "not_a_band"

        _edit(fix / "checklist.json", change)
        md = json.loads(drive_compose("deck-review", fix, work).read_text())["report_markdown"]
        doc = _page("deck-review", "visualize.py", work)
    m = re.search(r"\*\*Deck-craft score:\*\* ([\d.]+)% — ([^\n]+)", md)
    assert m, "no score line in the report"
    (verdict,) = [e for e in doc.iter() if e.has("data-verdict")]
    assert m.group(2).strip() == verdict.text().strip(), (m.group(2), verdict.text())
    assert m.group(2).startswith("Needs Work"), m.group(2)
    assert "not_a_band" not in md and "Not A Band" not in md


# ---------------------------------------------------------------------------------------------------------
# financial-model-review: one choice of which score and which name, on all three surfaces
# ---------------------------------------------------------------------------------------------------------

_DECK = "Deck Financial Readiness"
# Whole scores, so the format (held by test_page_structure) agrees at every base and only the choice can red.
_SCORE, _BQ = 64.0, 71.0


def _ring(doc: Element) -> tuple[str, str]:
    """(the figure the ring speaks, the ring's own label)."""
    (ring,) = [e for e in doc.iter() if e.get("role") == "img" and " percent" in (e.get("aria-label") or "")]
    spoken = re.search(r"([\d.]+) percent", ring.get("aria-label") or "")
    assert spoken
    (label,) = [e for e in ring.iter() if e.tag == "strong"]
    return spoken.group(1), label.text().strip()


# (model_maturity_pct, data_confidence, model_format, headlined on business quality?)
_FMR_CASES = (
    (58.8, "exact", "spreadsheet", False),
    (58.8, "estimated", "spreadsheet", False),
    (None, "exact", "spreadsheet", False),
    (None, "estimated", "spreadsheet", True),
    # A deck or a conversation is headlined on business quality whatever its figures' confidence: the
    # structural criteria are gated off for those formats (`references/schema-inputs.md`).
    (None, "exact", "deck", True),
    (None, "exact", "conversational", True),
)


@pytest.mark.parametrize(("maturity", "confidence", "model_format", "deck_only"), _FMR_CASES)
def test_fmr_report_page_and_explorer_headline_one_score_under_one_name(
    maturity: float | None, confidence: str, model_format: str, deck_only: bool
) -> None:
    """One score under one name on report.md (its verdict), the report page and the explorer. The deck-only
    headline (business quality, "Deck Financial Readiness") is the review's when no structural criterion
    applied and either the figures are not exact or the review is of a deck or a conversation; every other
    review is headlined on the checklist score as "Model Quality". The report page used to switch on maturity
    alone, the explorer never switched, and neither page used the report's name for the checklist score."""
    with tempfile.TemporaryDirectory() as td:
        fix, work = _staged("financial-model-review", td)

        def checklist(ck: dict[str, Any]) -> None:
            ck["summary"]["score_pct"] = _SCORE
            ck["summary"]["business_quality_pct"] = _BQ
            ck["summary"]["model_maturity_pct"] = maturity

        def inputs(doc: dict[str, Any]) -> None:
            doc["company"]["data_confidence"] = confidence
            doc["company"]["model_format"] = model_format

        _edit(fix / "checklist.json", checklist)
        _edit(fix / "inputs.json", inputs)
        verdict = json.loads(drive_compose("financial-model-review", fix, work).read_text())["verdict"]
        pages = {
            script: _ring(_page("financial-model-review", script, work)) for script in ("visualize.py", "explore.py")
        }
    m = re.match(r"(Model Quality|Deck Financial Readiness): [^(\n]*\(([\d.]+)%\)", verdict)
    assert m, verdict
    want = f"{_BQ:g}" if deck_only else f"{_SCORE:g}"
    assert (m.group(1) == _DECK) is deck_only and m.group(2) == want, verdict
    wrong = [
        (script, spoken, label) for script, (spoken, label) in pages.items() if (spoken, label) != (want, m.group(1))
    ]
    assert not wrong, (want, m.group(1), wrong)


# ---------------------------------------------------------------------------------------------------------
# A score that is not a number prints as no score, never as "0%"
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["95.5", float("nan"), None, True])
def test_deck_review_prints_no_figure_for_a_score_that_is_not_a_number(bad: Any) -> None:
    """compose renders a checklist the schema flags (a medium warning, not a refusal). A `score_pct` that is
    not a finite number is no score: the report says so beside the band's verdict, and the page draws no ring,
    where both used to print "0%"."""
    with tempfile.TemporaryDirectory() as td:
        fix, work = _staged("deck-review", td)

        def change(ck: dict[str, Any]) -> None:
            ck["summary"]["score_pct"] = bad
            ck["summary"]["overall_status"] = "solid"

        _edit(fix / "checklist.json", change)
        md = json.loads(drive_compose("deck-review", fix, work).read_text())["report_markdown"]
        doc = _page("deck-review", "visualize.py", work)
    (line,) = [ln for ln in md.splitlines() if ln.startswith("**Deck-craft score:**")]
    assert "0%" not in line and "nan" not in line.lower(), line
    assert line == "**Deck-craft score:** not recorded — Solid — a well-built deck with a few craft gaps to close", line
    rings = [e for e in doc.iter() if e.get("role") == "img" and " percent" in (e.get("aria-label") or "")]
    assert rings == [], "a page ring for a score that is not a number"
    (verdict,) = [e for e in doc.iter() if e.has("data-verdict")]
    assert verdict.text().strip() == line.split(" — ", 1)[1]


# ---------------------------------------------------------------------------------------------------------
# ic-sim: every score string in the report, the high mismatch warning's included
# ---------------------------------------------------------------------------------------------------------


def test_ic_verdict_score_mismatch_prints_the_score_as_the_report_does() -> None:
    """The one warning that kept the raw float (`VERDICT_SCORE_MISMATCH`) prints the fleet format, so one
    report never says "80%" and "80.0%" of one score."""
    with tempfile.TemporaryDirectory() as td:
        fix, work = _staged("ic-sim", td)

        def change(sd: dict[str, Any]) -> None:
            sd["summary"]["conviction_score"] = 80.0
            sd["summary"]["verdict"] = "more_diligence"
            for key in ("coverage_capped", "coverage_floored", "coverage_held"):
                sd["summary"].pop(key, None)

        _edit(fix / "score_dimensions.json", change)
        report = json.loads(drive_compose("ic-sim", fix, work).read_text())
    (w,) = [w for w in report["validation"]["warnings"] if w.get("code") == "VERDICT_SCORE_MISMATCH"]
    text = json.dumps(w)
    assert "80%" in text and "80.0%" not in text, w
    assert "80.0%" not in report["report_markdown"]
