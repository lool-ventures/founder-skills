"""Which outside review the founder is shown, and what the page says about the others -- from records
the model does not write.

A live run's founder chose to deliver without revising. A later question, asked after a second review
had already run, was answered "Use the corrected, second review", and the model recorded it as
`red_team_revision.approved_by_founder`. Both pages then said "This analysis was revised once, with your
approval", when nothing had changed (2.5% -> 2.5%). The flag was model-written, and it chose the round
shown, licensed changes between rounds, excused a rewritten founder figure and wrote that sentence.

Now: the review shown is the EARLIEST one of the analysis as delivered, so re-running cannot make it
softer; every later review of the same analysis is listed in full beneath it, so re-running cannot hide
a harsher one either; a change between reviews is a computed disclosure; and nothing is read from
`red_team_revision`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from test_market_sizing import (  # noqa: E402
    _CRUN,
    _compose_dir,
    _gated_dir,
    _pipe_review,
    _set_methodology,
    _warning_codes,
    run_script_raw,
)
from test_market_sizing_view import (  # noqa: E402
    _codes,
    _compose,
    _edit,
    _html,
    _replay,
    _review,
    _reviewed_dir,
)

_FIRST = "The first review found the share is 6.1%."
_SECOND = "A second review found the price is unsupported."
_THIRD = "A third review found nothing new."
_FORGED = {
    "approved_by_founder": True,
    "founder_words": "Use the corrected, second review",
    "changes": [{"field": "target_pct", "from": 2.5, "to": 2.5}],
}


def _pages(d: Path) -> tuple[dict[str, Any], str, str]:
    data = _compose_dir(d)
    rc, html_page, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0, err
    return data, data["report_markdown"], html_page


def _section(md: str) -> str:
    start = md.index("## Adversarial Findings")
    end = md.find("\n## ", start + 1)
    return md[start : end if end > 0 else len(md)]


# --- the same analysis reviewed more than once ------------------------------------------------------


def test_the_first_review_is_shown_and_a_later_one_of_the_same_analysis_is_listed_beneath_it() -> None:
    d = _gated_dir()
    _pipe_review(d, _FIRST)
    _pipe_review(d, _SECOND)
    data, md, html_page = _pages(d)
    section = _section(md)
    assert section.index(_FIRST) < section.index("A later review of the same analysis") < section.index(_SECOND)
    assert "The outside review ran 2 times on the analysis as delivered" in section
    later = html_page[html_page.index("A later review of the same analysis") :]
    assert _SECOND in later
    payload = data["coaching_payload"]
    assert payload["review_rounds"]["count"] == 2
    assert _SECOND in json.dumps(payload["red_team_findings"])


def test_nothing_on_the_page_claims_the_founder_approved_anything() -> None:
    d = _gated_dir({"red_team_revision": _FORGED})
    _pipe_review(d, _FIRST)
    _pipe_review(d, _SECOND)
    _, md, html_page = _pages(d)
    for page in (md, html_page):
        assert "approval" not in page.lower()
        assert "2.5% → 2.5%" not in page


def test_a_written_approval_changes_nothing_the_founder_reads() -> None:
    """The positive statement of the fix: the model-written flag steers nothing."""
    plain, forged = _gated_dir(), _gated_dir({"red_team_revision": _FORGED})
    for d in (plain, forged):
        _pipe_review(d, _FIRST)
        _pipe_review(d, _SECOND)
    p_data, f_data = _compose_dir(plain), _compose_dir(forged)
    assert _section(p_data["report_markdown"]) == _section(f_data["report_markdown"])
    assert p_data["coaching_payload"]["red_team_findings"] == f_data["coaching_payload"]["red_team_findings"]
    assert sorted(_warning_codes(p_data)) == sorted(_warning_codes(f_data))


def test_three_reviews_of_the_same_analysis_show_the_first_and_list_the_other_two() -> None:
    d = _gated_dir()
    for text in (_FIRST, _SECOND, _THIRD):
        _pipe_review(d, text)
    section = _section(_compose_dir(d)["report_markdown"])
    assert section.index(_FIRST) < section.index(_SECOND) < section.index(_THIRD)
    assert "ran 3 times" in section


# --- a review of a changed analysis ------------------------------------------------------------------


def test_a_review_of_the_changed_analysis_is_shown_and_the_change_is_computed(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    assert _review(d, "Round two: the revised share is supported.") == 2
    data = _compose(d)
    codes = _codes(data)
    assert "RECORD_CHANGED_AFTER_REVIEW" not in codes, codes
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "ANALYSIS_CHANGED_BETWEEN_REVIEWS")
    assert "Segment %" in w["message"] and "37%" in w["message"] and "30%" in w["message"], w
    section = _section(data["report_markdown"])
    assert "Round two: the revised share is supported." in section
    assert "The analysis changed after the first review" in section
    assert "Segment %: 37% → 30%" in section
    assert "Segment %: 37% → 30%" in _html(d)


def test_no_review_of_the_analysis_as_delivered_is_stated_as_such(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    data = _compose(d)
    assert "RECORD_CHANGED_AFTER_REVIEW" in _codes(data)


# --- a round removed ---------------------------------------------------------------------------------


def test_a_deleted_first_round_is_reported_not_silently_skipped() -> None:
    """Rounds were counted by how many copies exist, so deleting round 1 made round 2 the only one."""
    d = _gated_dir()
    _pipe_review(d, _FIRST)
    _pipe_review(d, _SECOND)
    (d / "handoff" / _CRUN / "redteam.r1.json").unlink()
    data = _compose_dir(d)
    assert "REDTEAM_ALTERED" in _warning_codes(data)
    assert "ran 2 times" in _section(data["report_markdown"])


def test_the_two_pages_show_the_same_review() -> None:
    d = _gated_dir()
    _pipe_review(d, _FIRST)
    _pipe_review(d, _SECOND)
    _set_methodology(d, red_team_revision=_FORGED)
    _, md, html_page = _pages(d)
    first_md = _section(md).index(_FIRST) < _section(md).index(_SECOND)
    first_html = html_page.index(_FIRST) < html_page.index(_SECOND)
    assert first_md and first_html
