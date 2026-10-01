"""A deck that states more than one figure for the same market is told so, on both surfaces.

`existing_claims` holds the one figure the analysis compares against. When the materials ALSO state a
different figure for the same metric -- a second TAM on another slide, a larger "total market" later in
the deck -- that disagreement used to be narrative at best (`existing_claims_detail`, not reconciled).
`existing_claims_alternatives` records each other figure with the slide it came from, and
DECK_CLAIMS_DISAGREE names every figure and its slide. It is MEDIUM (the run is valid and must not
halt) and cannot be accepted away: `accepted_warnings` is model-written, and this is a fact about the
founder's own materials. The canonical comparison is untouched.

All figures here are synthetic.
"""

from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from test_market_sizing import (  # noqa: E402
    _VALID_METHODOLOGY,
    _make_artifact_dir,
    _make_basic_arts,
    run_script,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts"
TWO_TAMS: dict[str, Any] = {
    "existing_claims": {"tam": 42_000_000_000},
    "existing_claims_alternatives": {"tam": [{"value": 97_000_000_000, "slide": 7, "label": "total market"}]},
}


def _compose(overrides: dict[str, Any], methodology: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    arts = _make_basic_arts(overrides)
    if methodology is not None:
        arts["methodology.json"] = methodology
    d = _make_artifact_dir(arts)
    rc, data, stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0, stderr
    assert data is not None
    return data, d


def _disagree(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in data["validation"]["warnings"] if w["code"] == "DECK_CLAIMS_DISAGREE"]


def _visible_html(d: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", out.stdout, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_a_second_figure_for_the_same_market_raises_a_medium_disclosure_naming_both() -> None:
    data, _ = _compose(TWO_TAMS)
    hits = _disagree(data)
    assert len(hits) == 1, hits
    assert hits[0]["severity"] == "medium"
    msg = hits[0]["message"]
    for part in ("TAM", "$42.0B", "$97.0B", "slide 7"):
        assert part in msg, (part, msg)


def test_the_disclosure_reaches_report_md_and_report_html() -> None:
    data, d = _compose(TWO_TAMS)
    md = data["report_markdown"]
    assert "$97.0B" in md and "slide 7" in md
    text = _visible_html(d)
    assert "$97.0B" in text and "slide 7" in text


def test_it_cannot_be_accepted_away() -> None:
    meth = copy.deepcopy(_VALID_METHODOLOGY)
    meth["accepted_warnings"] = [{"code": "DECK_CLAIMS_DISAGREE", "match": "TAM", "reason": "known"}]
    data, _ = _compose(TWO_TAMS, meth)
    assert [w["severity"] for w in _disagree(data)] == ["medium"]


def test_the_canonical_comparison_is_untouched() -> None:
    plain, _ = _compose({"existing_claims": {"tam": 42_000_000_000}})
    both, _ = _compose(TWO_TAMS)
    strip = [w for w in both["validation"]["warnings"] if w["code"] != "DECK_CLAIMS_DISAGREE"]
    assert strip == plain["validation"]["warnings"]


def test_the_same_figure_restated_is_not_a_disagreement() -> None:
    same = copy.deepcopy(TWO_TAMS)
    same["existing_claims_alternatives"]["tam"][0]["value"] = 42_200_000_000  # within 1%
    data, _ = _compose(same)
    assert _disagree(data) == []


def test_a_figure_inside_the_stated_range_is_not_a_disagreement() -> None:
    ranged = copy.deepcopy(TWO_TAMS)
    ranged["existing_claims_high"] = {"tam": 110_000_000_000}
    data, _ = _compose(ranged)
    assert _disagree(data) == []


def test_empty_alternatives_change_nothing() -> None:
    base, _ = _compose({"existing_claims": {"tam": 42_000_000_000}})
    empty, _ = _compose({"existing_claims": {"tam": 42_000_000_000}, "existing_claims_alternatives": {}})
    marker = re.compile(r"INSERTION_POINT_[0-9a-f]+")
    assert marker.sub("X", base["report_markdown"]) == marker.sub("X", empty["report_markdown"])
    assert base["validation"]["warnings"] == empty["validation"]["warnings"]


def test_an_alternative_with_no_stated_figure_is_ignored_and_reported() -> None:
    orphan = {
        "existing_claims": {"tam": 42_000_000_000},
        "existing_claims_alternatives": {"sam": [{"value": 9_000_000_000, "slide": 4, "label": "x"}]},
    }
    data, _ = _compose(orphan)
    assert _disagree(data) == []
    shape = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]
    assert any("existing_claims_alternatives" in m and "sam" in m for m in shape), shape
