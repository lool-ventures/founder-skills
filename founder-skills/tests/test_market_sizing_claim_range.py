"""A deck that states a market figure as a RANGE is compared, and quoted, as that range.

`existing_claims` holds one number per metric, so a deck stating "$8-12B" was recorded as its low
end and every surface then quoted the founder as having said "$8.0B" -- and a calculated figure
inside the stated range but above 1.5x its low end raised a mismatch the founder's own range does
not support. `existing_claims_high` carries the upper bound: inside the range there is no
disagreement, outside it the delta is taken to the NEAREST bound, and every surface prints the
range through one formatter.

Orphan rule (decided, not incidental): an upper bound with no lower bound for the same metric, or
one not above it, is IGNORED for comparison and reported under EXISTING_CLAIMS_SHAPE -- a range
needs both ends, and guessing the missing end would invent a figure the founder did not state.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from test_market_sizing import (  # noqa: E402
    _make_artifact_dir,
    _make_basic_arts,
    run_script,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts"
# Fixture SAM: top-down $6.0B, bottom-up $23.6B.
IN_RANGE = {"existing_claims": {"sam": 4_000_000_000}, "existing_claims_high": {"sam": 24_000_000_000}}
BELOW_RANGE = {"existing_claims": {"sam": 1_000_000_000}, "existing_claims_high": {"sam": 2_000_000_000}}


def _compose(overrides: dict[str, Any]) -> tuple[dict[str, Any], str]:
    d = _make_artifact_dir(_make_basic_arts(overrides))
    rc, data, stderr = run_script("compose_report.py", ["--dir", d])
    assert rc == 0, stderr
    assert data is not None
    return data, d


def _sam_mismatches(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        w
        for w in data["validation"]["warnings"]
        if w["code"] == "DECK_CLAIM_MISMATCH" and w["message"].startswith("SAM")
    ]


def _shape_warnings(data: dict[str, Any]) -> list[str]:
    return [w["message"] for w in data["validation"]["warnings"] if w["code"] == "EXISTING_CLAIMS_SHAPE"]


def _visible_html(d: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", out.stdout, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# --- comparison --------------------------------------------------------------------------------


def test_positive_control_low_end_alone_raises_the_mismatch() -> None:
    """The lever: without the upper bound, the same low end DOES raise a SAM mismatch."""
    data, _ = _compose({"existing_claims": {"sam": 4_000_000_000}})
    assert _sam_mismatches(data), "control: a $4B low end vs a $23.6B build must mismatch"


def test_inside_the_stated_range_is_not_a_mismatch() -> None:
    data, _ = _compose(IN_RANGE)
    assert _sam_mismatches(data) == []


def test_outside_the_range_is_measured_to_the_nearest_bound_and_quotes_the_range() -> None:
    data, _ = _compose(BELOW_RANGE)
    hits = _sam_mismatches(data)
    assert hits, "a $1-2B range against $6.0B and $23.6B builds must mismatch"
    msg = " ".join(h["message"] for h in hits)
    assert "$1.0B–$2.0B" in msg, msg
    assert "+200.0%" in msg, f"top-down $6.0B vs the $2.0B upper bound is +200%: {msg}"


# --- every surface quotes the range ------------------------------------------------------------


def test_report_md_table_and_answer_quote_the_range() -> None:
    data, _ = _compose(IN_RANGE)
    md = data["report_markdown"]
    assert "$4.0B–$24.0B" in md
    assert "within your range" in md
    assert "You stated SAM $4.0B–$24.0B" in md


def test_report_html_quotes_the_range() -> None:
    _, d = _compose(IN_RANGE)
    text = _visible_html(d)
    assert "$4.0B–$24.0B" in text
    assert "within your range" in text


# --- neutral element and orphans ---------------------------------------------------------------


def test_empty_upper_bounds_change_nothing() -> None:
    base, _ = _compose({"existing_claims": {"sam": 4_000_000_000}})
    empty, _ = _compose({"existing_claims": {"sam": 4_000_000_000}, "existing_claims_high": {}})
    marker = re.compile(r"INSERTION_POINT_[0-9a-f]+")  # per-run uuid, differs by construction
    assert marker.sub("X", base["report_markdown"]) == marker.sub("X", empty["report_markdown"])
    assert base["validation"]["warnings"] == empty["validation"]["warnings"]


def test_an_upper_bound_with_no_lower_bound_is_ignored_and_reported() -> None:
    data, _ = _compose({"existing_claims": {"sam": 4_000_000_000}, "existing_claims_high": {"tam": 90_000_000_000}})
    assert any("tam" in m.lower() and "upper" in m.lower() for m in _shape_warnings(data)), _shape_warnings(data)
    assert "$90.0B" not in data["report_markdown"]


def test_an_upper_bound_not_above_the_lower_is_ignored_and_reported() -> None:
    data, _ = _compose({"existing_claims": {"sam": 4_000_000_000}, "existing_claims_high": {"sam": 3_000_000_000}})
    assert any("sam" in m.lower() and "upper" in m.lower() for m in _shape_warnings(data)), _shape_warnings(data)
    assert _sam_mismatches(data), "ignored upper bound: behaves as the single low figure"
    assert "–$3.0B" not in data["report_markdown"]


def test_an_in_range_figure_is_not_marked_as_close_agreement_on_either_surface() -> None:
    """Inside the range is not "within 25% of your figure": no asterisk, no close-agreement footnote."""
    data, d = _compose(IN_RANGE)
    md = data["report_markdown"]
    assert "within your range *" not in md
    text = _visible_html(d)
    assert "within your range *" not in text
    assert "of the figure in your materials" not in text
