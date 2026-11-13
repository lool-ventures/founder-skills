"""market-sizing: a narrowing share must have been measured on the population it is applied to.

`_provenance.check_bases`, called by `market_sizing.py` on a by-reference sizing: each share entry the segment
share (top-down) or the serviceable share (bottom-up) is built from records `of`, the population its source
measured it on. One that names neither the base's own entries nor another share of the same rate is refused,
unless it is declared a `proxy` for that base with a reason; the reason then reaches both delivered pages.
Every figure here is invented.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from html_text import visible_text  # noqa: E402
from test_market_sizing import run_script_raw  # noqa: E402
from test_market_sizing_view import (  # noqa: E402
    _REFS,
    _RUN,
    _compose,
    _edit,
    _html,
    _record,
    _replay,
    _run_dir,
    _sourced,
    _stamp_downstream,
)

_WIDER = {
    **_REFS,
    "industry_total": {
        "derived": {"op": "multiply", "factors": [{"assumption": "wider_population"}, {"assumption": "care_price"}]}
    },
}
_WHY = "No published survey splits the wider population"


def _size(d: Path, refs: dict[str, Any]) -> tuple[int, str]:
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(refs),
    )
    return rc, out + err


def _checks(d: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((d / "sizing.json").read_text())["base_checks"]
    return out


def _segment(v: dict[str, Any], **fields: Any) -> None:
    next(a for a in v["assumptions"] if a["name"] == "segment_pct").update(fields)


def _wider_dir(tmp_path: Path) -> Path:
    return _run_dir(tmp_path, _record(_sourced("wider_population", 52_000_000, "count")))


def test_a_share_measured_on_its_base_matches(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    row = _checks(d)["segment_pct"]
    assert row["status"] == "match" and row["of"] == ["eligible_population"]
    assert row["base_entries"] == ["eligible_population"], "a price is not a population"


def test_a_share_of_what_another_share_selects_matches(tmp_path: Path) -> None:
    sub = _sourced("adult_child_pct", 50, "percent_points", of="segment_pct")
    refs = {
        **_REFS,
        "segment_pct": {
            "derived": {"op": "multiply", "factors": [{"assumption": "segment_pct"}, {"assumption": "adult_child_pct"}]}
        },
    }
    d = _run_dir(tmp_path, _record(sub), refs)
    row = _checks(d)["segment_pct"]
    assert row["status"] == "match" and sorted(row["of"]) == ["eligible_population", "segment_pct"]


def test_a_share_with_no_of_is_refused_and_the_sizing_is_left_alone(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    before = (d / "sizing.json").read_bytes()
    _edit(d, "validation.json", lambda v: _segment(v, of=""))
    rc, out = _size(d, _REFS)
    assert rc == 1 and "E_RATE_BASE_MISSING" in out
    assert (d / "sizing.json").read_bytes() == before


def test_a_share_measured_elsewhere_is_refused_and_the_sizing_is_left_alone(tmp_path: Path) -> None:
    """The producer contract, all three parts: a diagnostic on stdout, a line on stderr, `-o` untouched.
    (`test_skill_contract`'s registry entry for market_sizing.py covers the same `_fail_invalid` path with a
    payload refusal; this one needs a record on disk, which that registry cannot carry.)"""
    d = _wider_dir(tmp_path)
    before = (d / "sizing.json").read_bytes()
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(_WIDER),
    )
    assert rc == 1
    assert json.loads(out)["validation"]["status"] == "invalid"
    assert "E_RATE_BASE_MISMATCH" in out and "do not change it to match" in out
    assert "E_RATE_BASE_MISMATCH" in err
    assert (d / "sizing.json").read_bytes() == before


def test_plain_words_never_match(tmp_path: Path) -> None:
    """`of` in words records what the source said; only a recorded entry can be compared with the base."""
    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", lambda v: _segment(v, of="seniors in the surveyed states"))
    rc, out = _size(d, _REFS)
    assert rc == 1 and "E_RATE_BASE_MISMATCH" in out


def test_a_declared_proxy_passes_and_both_pages_say_why(tmp_path: Path) -> None:
    d = _wider_dir(tmp_path)
    _edit(
        d,
        "validation.json",
        lambda v: _segment(v, of="seniors in the surveyed states", proxy={"for": "wider_population", "why": _WHY}),
    )
    rc, out = _size(d, _WIDER)
    assert rc == 0, out
    row = _checks(d)["segment_pct"]
    assert row["status"] == "proxy"
    assert row["proxy"] == [{"share": "segment_pct", "for": "wider_population", "why": _WHY}]
    _stamp_downstream(d)
    md = _compose(d)["report_markdown"]
    html = visible_text(_html(d))
    for page in (md, html):
        assert "measured on seniors in the surveyed states" in page
        assert f"as a proxy: {_WHY}." in page


def test_a_proxy_is_bound_to_the_base_it_was_declared_for(tmp_path: Path) -> None:
    """Widening the base again needs a new reason: the old one was written for another population."""
    d = _wider_dir(tmp_path)
    _edit(d, "validation.json", lambda v: _segment(v, proxy={"for": "eligible_population", "why": _WHY}))
    rc, out = _size(d, _WIDER)
    assert rc == 1 and "E_RATE_BASE_MISMATCH" in out


def test_an_estimated_share_is_not_checked(tmp_path: Path) -> None:
    refs = {**_REFS, "segment_pct": {"estimate": 30, "unit": "percent_points", "why": "No survey covers it."}}
    d = _run_dir(tmp_path, _record(), refs)
    row = _checks(d)["segment_pct"]
    assert row["status"] == "not_checked" and row["reason"] == "estimate"


def test_a_sizing_from_before_the_check_replays_unchecked(tmp_path: Path) -> None:
    """Analyses sized before the check carry no stamp; replaying one neither refuses nor stamps."""
    d = _run_dir(tmp_path, _record())
    _edit(d, "sizing.json", lambda s: s.pop("base_checks"))
    _edit(d, "validation.json", lambda v: _segment(v, of=""))
    _replay(d)
    assert "base_checks" not in json.loads((d / "sizing.json").read_text())


def test_a_stamped_sizing_replays_checked(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", lambda v: _segment(v, of=""))
    rc, out, _ = run_script_raw(
        "market_sizing.py",
        [
            "--replay",
            str(d / "sizing.json"),
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "-o",
            str(d / "sizing.json"),
        ],
    )
    assert rc == 1 and "E_RATE_BASE_MISSING" in out


def test_a_base_widened_in_place_is_disclosed(tmp_path: Path) -> None:
    """The same entry name with a new value, under a share left as it was: legitimate (a newer count), so
    disclosed on both pages rather than refused."""
    d = _run_dir(tmp_path, _record())
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "eligible_population").update(value=52_000_000),
    )
    _replay(d)
    row = _checks(d)["segment_pct"]
    assert row["base_changed"] == [{"entry": "eligible_population", "from": 41_000_000, "to": 52_000_000}]
    _stamp_downstream(d)
    md = _compose(d)["report_markdown"]
    html = visible_text(_html(d))
    for page in (md, html):
        assert "since the earlier sizing" in page and "was kept as it was" in page


def test_nothing_is_said_when_every_share_matches(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _stamp_downstream(d)
    md = _compose(d)["report_markdown"]
    assert "as a proxy" not in md and "since the earlier sizing" not in md
