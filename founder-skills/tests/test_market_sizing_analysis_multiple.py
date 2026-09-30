"""A red-team multiple attributed to the analysis is checked against the analysis's own figures.

A live round-2 review wrote that "the analysis's own bottom-up build separately estimates … at roughly
5x this figure", and the coaching repeated it to the founder as a fact about their own build. The
analysis's bottom-up TAM was 0.51x the top-down; no figure it computed stood in a 5x ratio. The
reviewer's `what_is_true` is free prose, checked nowhere, rendered on four surfaces.

Calibrated before it was written: across the 15 kept red-team outputs (52 findings, 7 multiples) the
rule -- a multiple in a sentence that attributes it to the analysis's own build, with no ratio among
the analysis's figures, the founder's stated figures or the figures the sentence quotes within 25% --
fires on exactly one: the defect. Six correct multiples (deck vs research, stale vs current, external
benchmarks) make no such attribution and stay silent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from test_market_sizing import (  # noqa: E402
    _CRUN,
    _GOOD_FINDING,
    _compose_dir,
    _gated_dir,
    run_script_raw,
)

_SCRIPTS = _TESTS.parent / "skills" / "market-sizing" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("ms_view_multiple", _SCRIPTS / "_view.py")
assert _spec is not None and _spec.loader is not None
_view = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_view)

# Run 1's figures: top-down TAM $6.3B, bottom-up $3.2B.
_SIZING = {
    "top_down": {"tam": {"value": 6_300_000_000}, "sam": {"value": 756_000_000}, "som": {"value": 22_700_000}},
    "bottom_up": {"tam": {"value": 3_225_166_560}, "sam": {"value": 645_000_000}, "som": {"value": 32_300_000}},
}
_INPUTS = {"existing_claims": {"tam": 12_000_000_000, "sam": None, "som": 60_000_000}}
_DEFECT = (
    "The $6.3B figure is not the market the sizing narrows down from -- the actual pool (which the "
    "analysis's own bottom-up build separately estimates, using per-code monthly reimbursement rates, at "
    "roughly 5x this figure before any discount) is not the same market."
)


def _flag(text: str, sizing: dict[str, Any] = _SIZING) -> str:
    out: str = _view.checked_multiples(text, sizing, _INPUTS)
    return out


def test_the_measured_defect_is_flagged() -> None:
    assert _view._MULTIPLE_CAVEAT in _flag(_DEFECT)


def test_a_multiple_the_analysis_does_stand_in_is_not_flagged() -> None:
    """Round 1 of the same run: bottom-up $94.9B against top-down $6.3B, "~15x" -- true."""
    sizing = json.loads(json.dumps(_SIZING))
    sizing["bottom_up"]["tam"]["value"] = 94_900_000_000
    text = _DEFECT.replace("roughly 5x", "roughly 15x")
    assert _flag(text, sizing) == text


def test_a_multiple_not_attributed_to_the_analysis_is_not_checked() -> None:
    """The six correct multiples in the corpus compare the deck, published figures or old runs."""
    for text in (
        "Published estimates put the market at $2.6B, so the figure used is at least ~2.4x larger than the US portion.",
        "A serviceable share of 20% is roughly 6-18x the historical uptake rate this program has shown.",
        "The corrected SOM figures are $6.78M and $208.0M -- both about 1.37x the stale figures.",
    ):
        assert _flag(text) == text


def test_a_multiple_against_the_founders_own_claim_is_supported() -> None:
    text = "The analysis's own top-down build comes to about 2x less than the $12B you stated, at $6.3B."
    assert _flag(text) == text


def test_the_caveat_says_only_what_the_check_knows() -> None:
    # It must stay true when the check fires wrongly: it names only what was compared.
    assert "none of this analysis's figures" in _view._MULTIPLE_CAVEAT
    assert "wrong" not in _view._MULTIPLE_CAVEAT.lower()


# --- every surface the red team's words reach --------------------------------------------------------


def test_every_surface_carries_the_caveat(tmp_path: Path) -> None:
    d = _gated_dir()
    sizing = json.loads((d / "sizing.json").read_text())
    td = sizing["top_down"]["tam"]["value"]
    finding = {
        **_GOOD_FINDING,
        "severity": "high",
        "what_is_true": (
            f"The analysis's own bottom-up build estimates roughly 40x the ${td / 1e9:.1f}B top-down figure."
        ),
    }
    rc, out, _ = run_script_raw(
        "red_team.py",
        ["--run-id", _CRUN, "-o", str(d / "redteam.json")],
        stdin_data=json.dumps({"findings": [finding]}),
    )
    assert rc == 0, out
    data = _compose_dir(d)
    rc, html_page, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0, err
    payload = json.dumps(data["coaching_payload"]["red_team_findings"])
    assert _view._MULTIPLE_CAVEAT in data["report_markdown"]
    # The findings section itself, not only the verdict above it (which carries the caveat too, and
    # hid an unchecked section from a looser assertion).
    assert "none of this analysis" in html_page[html_page.index("<h2>Adversarial Findings</h2>") :]
    assert "none of this analysis" in payload
    # The verdict, which the hand-over message prints: its strongest challenge carries it too.
    verdict = next(line for line in data["report_markdown"].splitlines() if "The most serious" in line)
    assert _view._MULTIPLE_CAVEAT in verdict


def test_nothing_changes_without_a_sizing_to_check_against() -> None:
    assert _view.checked_multiples(_DEFECT, None, _INPUTS) == _DEFECT
