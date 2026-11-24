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
    _codes,
    _compose,
    _edit,
    _html,
    _record,
    _replay,
    _reviewed_dir,
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


def _a(name: str) -> dict[str, str]:
    """A reference to a recorded entry."""
    return {"assumption": name}


def _op(op: str, *factors: dict[str, Any]) -> dict[str, Any]:
    """A derivation over references."""
    return {"derived": {"op": op, "factors": list(factors)}}


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


def test_a_share_of_what_another_share_selects_passes_as_a_chain(tmp_path: Path) -> None:
    sub = _sourced("adult_child_pct", 50, "percent_points", of="segment_pct")
    refs = {
        **_REFS,
        "segment_pct": {
            "derived": {"op": "multiply", "factors": [{"assumption": "segment_pct"}, {"assumption": "adult_child_pct"}]}
        },
    }
    d = _run_dir(tmp_path, _record(sub), refs)
    row = _checks(d)["segment_pct"]
    assert row["status"] == "chain" and sorted(row["of"]) == ["eligible_population", "segment_pct"]
    assert row["chained"] == ["adult_child_pct"]


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
    assert row["proxy"] == [
        {"share": "segment_pct", "of": "seniors in the surveyed states", "for": "wider_population", "why": _WHY}
    ]
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


def test_a_proxy_declared_after_the_review_is_a_change_the_review_did_not_see(tmp_path: Path) -> None:
    """`of` is the main thread's word, and only the outside review can attack it: rewriting it, or declaring a
    proxy, after the review is disclosed like any other research change after it."""
    d = _reviewed_dir(tmp_path)
    _edit(
        d,
        "validation.json",
        lambda v: _segment(v, of="seniors in two states", proxy={"for": "eligible_population", "why": _WHY}),
    )
    rc, out = _size(d, _REFS)
    assert rc == 0, out
    _stamp_downstream(d)
    assert "RECORD_CHANGED_AFTER_REVIEW" in _codes(_compose(d))


def test_a_base_cannot_be_built_from_two_populations(tmp_path: Path) -> None:
    """Why matching a share against any one of the base's entries is safe: the calculator's algebra admits no
    count times a count and has no sum, so a base holds at most one population. A wider one arrives as a new
    entry (refused above) or the same entry with a new value (disclosed above)."""
    refs = {
        **_REFS,
        "industry_total": {
            "derived": {
                "op": "multiply",
                "factors": [
                    {"assumption": "eligible_population"},
                    {"assumption": "other_population"},
                    {"assumption": "care_price"},
                ],
            }
        },
    }
    d = _run_dir(tmp_path, _record(_sourced("other_population", 3, "count")))
    rc, out = _size(d, refs)
    assert rc == 1 and "E_ALGEBRA" in out


# --- the post-build review's reproductions -------------------------------------------------------------------


def test_a_widened_base_is_still_disclosed_after_another_replay(tmp_path: Path) -> None:
    """A re-run of the pipe after the revision (a second replay, a downstream rejection) compares with a prior
    that already holds the new value; the disclosure is carried, not lost."""
    d = _run_dir(tmp_path, _record())
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "eligible_population").update(value=52_000_000),
    )
    _replay(d)
    _replay(d)
    assert _checks(d)["segment_pct"]["base_changed"] == [
        {"entry": "eligible_population", "from": 41_000_000, "to": 52_000_000}
    ]


def test_a_share_matched_only_through_another_share_is_stamped_as_a_chain(tmp_path: Path) -> None:
    """The chain rule cannot tell a real "B of what A selects" from a 100% entry inserted to carry B: it is
    stamped `chain`, so the mix of outcomes and the review can see it."""
    head = _sourced("all_members_pct", 100, "percent_points", of="eligible_population")
    refs = {
        **_REFS,
        "segment_pct": {
            "derived": {"op": "multiply", "factors": [{"assumption": "all_members_pct"}, {"assumption": "segment_pct"}]}
        },
    }
    d = _run_dir(tmp_path, _record(head, segment_of="all_members_pct"), refs)
    row = _checks(d)["segment_pct"]
    assert row["status"] == "chain" and row["chained"] == ["segment_pct"]


def test_a_share_recorded_as_a_ratio_is_checked(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", lambda v: v["assumptions"].append(_sourced("segment_ratio", 0.37, "ratio")))
    refs = {**_REFS, "segment_pct": _op("to_percent", _a("segment_ratio"))}
    rc, out = _size(d, refs)
    assert rc == 1 and "E_RATE_BASE_MISSING" in out


_DIVIDED = {**_REFS, "segment_pct": _op("to_percent", _op("divide", _a("local_users"), _a("local_total")))}


def test_a_share_divided_from_counts_must_divide_by_the_base(tmp_path: Path) -> None:
    """A share built as one count over another names its population by its divisor: one of its populations
    must be one the base is built from, or carry a proxy for it."""
    d = _run_dir(tmp_path, _record())
    _edit(
        d,
        "validation.json",
        lambda v: v["assumptions"].extend(
            [_sourced("local_users", 3_000_000, "count"), _sourced("local_total", 9_000_000, "count")]
        ),
    )
    rc, out = _size(d, _DIVIDED)
    assert rc == 1 and "E_RATE_BASE_MISMATCH" in out
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "local_total").update(
            proxy={"for": "eligible_population", "why": _WHY}
        ),
    )
    rc, out = _size(d, _DIVIDED)
    assert rc == 0, out
    assert _checks(d)["segment_pct"]["status"] == "proxy"


def test_a_share_divided_by_the_base_matches(tmp_path: Path) -> None:
    refs = {**_REFS, "segment_pct": _op("to_percent", _op("divide", _a("local_users"), _a("eligible_population")))}
    d = _run_dir(tmp_path, _record(_sourced("local_users", 3_000_000, "count")), refs)
    assert _checks(d)["segment_pct"]["status"] == "match"


def test_the_proxy_sentence_reads_what_the_sizing_checked(tmp_path: Path) -> None:
    """An `of` edited after the sizing does not change what the pages say the share was measured on."""
    d = _wider_dir(tmp_path)
    _edit(
        d,
        "validation.json",
        lambda v: _segment(v, of="seniors in two states", proxy={"for": "wider_population", "why": _WHY}),
    )
    assert _size(d, _WIDER)[0] == 0
    _edit(d, "validation.json", lambda v: _segment(v, of="seniors everywhere"))
    _stamp_downstream(d)
    md = _compose(d)["report_markdown"]
    assert "measured on seniors in two states" in md and "seniors everywhere" not in md


def test_a_base_moved_twice_keeps_the_figure_it_started_from(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    for value in (52_000_000, 60_000_000):
        _edit(
            d,
            "validation.json",
            lambda v, value=value: next(a for a in v["assumptions"] if a["name"] == "eligible_population").update(
                value=value
            ),
        )
        _replay(d)
    assert _checks(d)["segment_pct"]["base_changed"] == [
        {"entry": "eligible_population", "from": 41_000_000, "to": 60_000_000}
    ]


_TWO_STEP = {**_REFS, "segment_pct": _op("multiply", _a("segment_pct"), _a("small_firm_pct"))}


def _two_step_dir(tmp_path: Path, **small: Any) -> Path:
    """A step of two shares: the first of the base, the second of what the first selects."""
    entry = _sourced("small_firm_pct", 40, "percent_points", of="the surveyed sub-market")
    entry.update(small)
    return _run_dir(tmp_path, _record(entry))


def test_a_mismatch_names_the_share_whose_population_it_was_measured_on(tmp_path: Path) -> None:
    """The exit for "B of what A selects" is `of` naming A. A refusal that offered only a proxy or a different
    share sent the model to rewrite `of` to the base and add a proxy for it."""
    d = _two_step_dir(tmp_path)
    rc, out = _size(d, _TWO_STEP)
    assert rc == 1 and "E_RATE_BASE_MISMATCH" in out
    assert "name that share in `of`" in out and "'segment_pct' picks out" in out
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "small_firm_pct").update(of="segment_pct"),
    )
    rc, out = _size(d, _TWO_STEP)
    assert rc == 0, out
    assert _checks(d)["segment_pct"]["status"] == "chain"


def test_a_lone_share_mismatch_offers_no_chain(tmp_path: Path) -> None:
    d = _wider_dir(tmp_path)
    rc, out = _size(d, _WIDER)
    assert rc == 1 and "E_RATE_BASE_MISMATCH" in out and "name that share in `of`" not in out


def test_a_proxy_for_the_population_the_share_was_measured_on_is_refused(tmp_path: Path) -> None:
    """`of` rewritten to the base, plus a proxy for that same entry: the pages would say "measured on X and
    applied to X as a proxy", and the population the source measured is gone. Refused, never asked."""
    d = _two_step_dir(tmp_path)
    before = (d / "sizing.json").read_bytes()
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "small_firm_pct").update(
            of="eligible_population", proxy={"for": "eligible_population", "why": _WHY}
        ),
    )
    rc, out = _size(d, _TWO_STEP)
    assert rc == 1 and "E_RATE_BASE_PROXY_SELF" in out and "remedy: record_research" in out
    assert "'segment_pct' picks out" in out
    assert (d / "sizing.json").read_bytes() == before


def test_a_lone_share_of_the_base_with_a_proxy_for_it_is_refused(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    before = (d / "sizing.json").read_bytes()
    _edit(d, "validation.json", lambda v: _segment(v, proxy={"for": "eligible_population", "why": _WHY}))
    rc, out = _size(d, _REFS)
    assert rc == 1 and "E_RATE_BASE_PROXY_SELF" in out and "name that share" not in out
    assert (d / "sizing.json").read_bytes() == before


def test_a_base_population_with_a_proxy_for_itself_is_refused(tmp_path: Path) -> None:
    refs = {**_REFS, "segment_pct": _op("to_percent", _op("divide", _a("local_users"), _a("eligible_population")))}
    d = _run_dir(tmp_path, _record(_sourced("local_users", 3_000_000, "count")), refs)
    _edit(
        d,
        "validation.json",
        lambda v: next(a for a in v["assumptions"] if a["name"] == "eligible_population").update(
            proxy={"for": "eligible_population", "why": _WHY}
        ),
    )
    before = (d / "sizing.json").read_bytes()
    rc, out = _size(d, refs)
    assert rc == 1 and "E_RATE_BASE_PROXY_SELF" in out
    assert "a population is no proxy for itself" in out and "Remove the `proxy`" in out and "`of`" not in out
    assert (d / "sizing.json").read_bytes() == before


def test_an_of_restating_the_base_in_other_words_is_still_the_base(tmp_path: Path) -> None:
    """Exact names only would let `of` echo the base's name in another case, or its label, and keep the proxy."""
    for i, of in enumerate(("Eligible Population", "eligible-population")):
        (tmp_path / str(i)).mkdir()
        d = _run_dir(tmp_path / str(i), _record())
        before = (d / "sizing.json").read_bytes()
        _edit(
            d, "validation.json", lambda v, of=of: _segment(v, of=of, proxy={"for": "eligible_population", "why": _WHY})
        )
        rc, out = _size(d, _REFS)
        assert rc == 1 and "E_RATE_BASE_PROXY_SELF" in out, of
        assert (d / "sizing.json").read_bytes() == before


def test_an_of_naming_the_base_by_its_label_is_still_the_base(tmp_path: Path) -> None:
    label = "Seniors living at home"

    def edit(v: dict[str, Any]) -> None:
        next(a for a in v["assumptions"] if a["name"] == "eligible_population")["label"] = label
        _segment(v, of=label.upper(), proxy={"for": "eligible_population", "why": _WHY})

    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", edit)
    rc, out = _size(d, _REFS)
    assert rc == 1 and "E_RATE_BASE_PROXY_SELF" in out


def test_a_proxy_on_another_population_in_words_still_passes(tmp_path: Path) -> None:
    """Words that name another population, even one that mentions the base, are a real proxy."""
    d = _wider_dir(tmp_path)
    _edit(
        d,
        "validation.json",
        lambda v: _segment(
            v, of="the surveyed part of the wider population", proxy={"for": "wider_population", "why": _WHY}
        ),
    )
    rc, out = _size(d, _WIDER)
    assert rc == 0, out
