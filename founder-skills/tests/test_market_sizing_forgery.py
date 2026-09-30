"""Can an instructed edit clear an integrity warning? One forgery per lever, per code.

The threat measured on real runs is not an adversary rewriting everything. It is the model, told by a
warning or a remedy to fix something, editing the one file the warning pointed at until the warning goes
away. So each test below edits ONLY files the model is instructed to write or amend, and runs only the
producers a remedy names. It then asserts the warning is still LIVE for the founder (present and not
accepted away), or that the edit is disclosed to the founder rather than laundered.

Accepting a warning is one of those edits, and only a medium warning can be accepted. Every code tried
below is high, which a test asserts; a positive control shows the same lever does clear a medium one,
so "it resisted acceptance" is a claim that could have failed.

MODEL-EDITED (the forger may write these): `_MODEL_EDITED` below, plus a new sizing hand-off, since
re-dispatching a step is itself a remedy and the sub-agent writes the hand-off.

PRODUCER-OWNED (the forger never writes these directly): the append-only review copies and the unit
rejections under `handoff/<run>/`, and `sizing.json` / `sensitivity.json` / `checklist.json`, which only
their producers write. A test may tamper with one of them only to CREATE the defect a code detects.

SCOPE, stated as what holds: a forger who also rewrites the producer-owned copies is out of scope. These
defences raise the cost of an edit and make it visible; they do not stop full write access to the
analysis directory, which the model has in Cowork. Before the outside review, a changed research record
is indistinguishable from research under any design, so pre-review record edits are held to "visible",
not "refused".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from test_market_sizing import run_script_raw  # noqa: E402
from test_market_sizing_view import (  # noqa: E402
    _REFS,
    _RUN,
    _compose,
    _numeric_dir,
    _record,
    _replay,
    _review,
    _reviewed_dir,
    _run_dir,
    _sourced,
    _unlisted_source_record,
)

_SCRIPTS = _TESTS.parent / "skills" / "market-sizing" / "scripts"
_MODEL_EDITED = frozenset({"redteam.json", "validation.json", "inputs.json", "methodology.json"})


def _forge(d: Path, name: str, fn: Any) -> None:
    """The only way a test below changes a file after its setup: one the model is told to write."""
    assert name in _MODEL_EDITED, f"{name} is producer-owned; forging it is out of this suite's scope"
    doc = json.loads((d / name).read_text())
    fn(doc)
    (d / name).write_text(json.dumps(doc))


def _accept(d: Path, code: str) -> None:
    """The cheapest lever: record the warning as accepted, matched on its own live text so the entry is
    well-formed. Only a medium warning can be accepted (see the positive control below); this tries it
    anyway, because the model is told to accept what it cannot fix."""
    live = [w for w in _warnings(d) if w["code"] == code]
    assert live, f"{code} is not firing, so there is nothing to accept"
    match = live[0]["message"][:40]
    _forge(
        d,
        "methodology.json",
        lambda m: m.setdefault("accepted_warnings", []).append(
            {"code": code, "match": match, "reason": "Reviewed; the figure is fine."}
        ),
    )


def _approve(d: Path, field: str, was: Any, now: Any) -> None:
    """The founder's approval, as the model would write it: nothing checks the words are the founder's."""
    _forge(
        d,
        "methodology.json",
        lambda m: m.update(
            red_team_revision={
                "approved_by_founder": True,
                "founder_words": "Yes, go ahead.",
                "changes": [{"field": field, "from": was, "to": now}],
            }
        ),
    )


def _size_from(d: Path, refs: dict[str, Any]) -> tuple[int, str]:
    """Re-run the sizing step from a (new) hand-off: the re-dispatch remedy."""
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


def _warnings(d: Path) -> list[dict[str, Any]]:
    return list(_compose(d)["validation"]["warnings"])


def _fires(d: Path, *codes: str) -> list[str]:
    """At least one of `codes` is LIVE for the founder: present and not accepted away. An accepted
    warning stays in the list, marked "acknowledged", so presence alone would not show it.

    Inert today, deliberately kept: while ACCEPTIBLE_SEVERITIES excludes every code tried here, nothing
    reaches "acknowledged", so a mutation pass reports the filter as surviving. It becomes the primary
    guard the moment any of them is made acceptable (measured: 8 of the 9 tests that then fail fail
    through this filter). Do not delete it for being inert."""
    warnings = _warnings(d)
    live = [w["code"] for w in warnings if w.get("severity") != "acknowledged"]
    assert any(c in live for c in codes), (codes, [(w["code"], w.get("severity")) for w in warnings])
    return live


def _move_share(v: dict[str, Any]) -> None:
    v["assumptions"][2]["value"] = 30


# --- the acceptance lever --------------------------------------------------------------------------------

# Every code the tests below try to accept. Each is high, which is WHY accepting it cannot clear it.
_ACCEPTANCE_TRIED = (
    "SIZING_STALE",
    "SIZING_UNRESOLVABLE",
    "SIZING_ALTERED",
    "UNIT_CHANGED_AFTER_REJECTION",
    "SIZING_NOT_CHECKED",
    "RECORD_CHANGED_AFTER_REVIEW",
    "REDTEAM_ALTERED",
)


def test_acceptance_is_a_real_lever_on_a_medium_warning(tmp_path: Path) -> None:
    """Positive control. Without it, "the high warning resisted acceptance" could mean the lever never
    engaged at all -- which it once did not, with an empty match."""
    d = _run_dir(tmp_path, _record())
    _accept(d, "UNSOURCED_ASSUMPTIONS")
    got = [w for w in _warnings(d) if w["code"] == "UNSOURCED_ASSUMPTIONS"]
    assert got and all(w["severity"] == "acknowledged" for w in got), got


def test_every_warning_the_suite_tries_to_accept_is_one_acceptance_cannot_clear() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ms_compose_forgery", _SCRIPTS / "compose_report.py")
    assert spec is not None and spec.loader is not None
    compose = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_SCRIPTS))
    spec.loader.exec_module(compose)
    for code in _ACCEPTANCE_TRIED:
        assert compose.WARNING_SEVERITY[code] not in compose.ACCEPTIBLE_SEVERITIES, code
    # The list is the codes this file actually tries to accept, so a new attempt cannot skip the claim.
    import re

    source = Path(__file__).read_text()
    literal = re.findall(r'_accept\s*\(d, "([A-Z_]+)"\)', source)
    # Every call names its code as a literal, or the derivation below could not see it. The case only
    # this count catches: an EXTRA attempt built from a variable beside an existing literal one -- the
    # set comparison still matches then (measured: without this line that mutation passes all 16).
    assert len(literal) == len(re.findall(r"(?<!def )_accept\s*\(", source)), "write each _accept code as a literal"
    assert set(literal) - {"UNSOURCED_ASSUMPTIONS"} == set(_ACCEPTANCE_TRIED), literal


# --- before the review: visible, never laundered --------------------------------------------------------


def test_sizing_stale_survives_acceptance_and_renaming(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _forge(d, "validation.json", _move_share)
    _accept(d, "SIZING_STALE")
    _fires(d, "SIZING_STALE")
    # Renaming the moved entry away from the reference does not make the sizing current.
    _forge(d, "validation.json", lambda v: v["assumptions"][2].update(name="segment_share"))
    _fires(d, "SIZING_UNRESOLVABLE")


def test_a_raised_grade_is_visible_before_the_review(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _unlisted_source_record())
    _forge(
        d,
        "validation.json",
        lambda v: v["sources"].append({"title": "A blog post", "url": "https://blog.example/post"}),
    )
    _accept(d, "SIZING_STALE")
    _fires(d, "SIZING_STALE")


def test_sizing_unresolvable_is_not_cleared_by_a_same_named_figure_of_another_kind(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _forge(d, "validation.json", lambda v: v["assumptions"][2].update(name="segment_share"))
    _accept(d, "SIZING_UNRESOLVABLE")
    _fires(d, "SIZING_UNRESOLVABLE")
    _forge(d, "validation.json", lambda v: v["assumptions"].append(_sourced("segment_pct", 37, "count")))
    _fires(d, "SIZING_UNRESOLVABLE")


def test_sizing_altered_is_not_reachable_from_any_model_edited_file(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    # The defect: the saved figures edited (producer-owned; this is what the code exists to see).
    doc = json.loads((d / "sizing.json").read_text())
    doc["top_down"]["tam"]["value"] = 12_345_000_000
    (d / "sizing.json").write_text(json.dumps(doc))
    # This attempt rests on the severity assertion alone: SIZING_STALE is also live here, so this test's
    # green does not show the acceptance lever was exercised against SIZING_ALTERED.
    _accept(d, "SIZING_ALTERED")
    _forge(d, "validation.json", lambda v: v["assumptions"][0].update(value=60_807_881))
    got = _fires(d, "SIZING_ALTERED", "SIZING_STALE")
    assert "$12.3B" not in _compose(d)["report_markdown"], got


def test_a_relabelled_unit_is_caught_under_a_new_name_too(tmp_path: Path) -> None:
    """The refused figure, renamed as well as relabelled, is still the refused figure."""
    d = _run_dir(tmp_path, _record(_sourced("eligible_total", 36_000_000, "count")))
    refs = {**_REFS, "industry_total": {"assumption": "eligible_total"}}
    rc, out = _size_from(d, refs)
    assert rc != 0 and "E_UNIT_MISMATCH" in out
    _forge(
        d,
        "validation.json",
        lambda v: v["assumptions"][3].update(name="market_spend", unit="money_total_per_year", currency="USD"),
    )
    rc, out = _size_from(d, {**_REFS, "industry_total": {"assumption": "market_spend"}})
    assert rc == 0, out
    _accept(d, "UNIT_CHANGED_AFTER_REJECTION")
    _fires(d, "UNIT_CHANGED_AFTER_REJECTION")


def test_numbers_typed_over_real_research_are_disclosed_even_after_the_research_is_emptied(tmp_path: Path) -> None:
    """Emptying the record and recording the typed figures as the founder's is a pre-review record edit:
    not refusable, but the report must then tell the founder no research was done."""
    d = _numeric_dir(tmp_path, _record())
    _accept(d, "SIZING_NOT_CHECKED")
    _fires(d, "SIZING_NOT_CHECKED")
    _forge(d, "validation.json", lambda v: v.update(skipped=True, reason="Not needed."))
    _forge(d, "inputs.json", lambda i: i.update(existing_claims={"industry_total": 5e9, "segment": 20, "share": 5}))
    got = _fires(d, "SIZING_NOT_CHECKED", "INPUTS_USER_PROVIDED")
    if "INPUTS_USER_PROVIDED" in got:
        assert "no outside research was done" in _compose(d)["report_markdown"]


# --- after the review: refused ------------------------------------------------------------------------------


def _moved_after_review(tmp_path: Path) -> Path:
    d = _reviewed_dir(tmp_path)
    _forge(d, "validation.json", _move_share)
    _replay(d)
    return d


def test_a_change_after_the_review_survives_acceptance(tmp_path: Path) -> None:
    d = _moved_after_review(tmp_path)
    _accept(d, "RECORD_CHANGED_AFTER_REVIEW")
    _fires(d, "RECORD_CHANGED_AFTER_REVIEW")


def test_an_approval_with_no_second_review_licenses_nothing(tmp_path: Path) -> None:
    d = _moved_after_review(tmp_path)
    _approve(d, "segment_pct", 37, 30)
    _fires(d, "RECORD_CHANGED_AFTER_REVIEW")


def test_an_approval_and_the_first_review_re_piped_is_not_a_second_review(tmp_path: Path) -> None:
    """Round 1's hand-off, re-piped: the same bytes replace round 1, and different bytes carrying the
    same findings make a round 2 that reviewed nothing new. Neither licenses the change."""
    d = _moved_after_review(tmp_path)
    _approve(d, "segment_pct", 37, 30)
    assert _review(d, "The published share is 30%.") == 1
    _fires(d, "RECORD_CHANGED_AFTER_REVIEW")
    finding = json.loads((d / "redteam.json").read_text())["findings"][0]
    rc, out, err = run_script_raw(
        "red_team.py",
        ["--run-id", _RUN, "-o", str(d / "redteam.json")],
        stdin_data=json.dumps({"findings": [finding]}, indent=1),
    )
    assert rc == 0, out + err
    assert json.loads(out)["round"] == 2
    _fires(d, "RECORD_CHANGED_AFTER_REVIEW")


def test_rewriting_what_the_review_saw_is_an_edit_of_the_review(tmp_path: Path) -> None:
    d = _moved_after_review(tmp_path)
    _forge(d, "redteam.json", lambda r: r["inputs_reviewed"]["sizing"]["segment_pct"].update(value_consumed=30))
    _forge(d, "redteam.json", lambda r: r["inputs_reviewed"]["record"]["segment_pct"].update(value=30))
    _fires(d, "REDTEAM_ALTERED", "RECORD_CHANGED_AFTER_REVIEW")


def test_a_grade_raised_after_the_review_survives_acceptance(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _unlisted_source_record())
    _forge(d, "methodology.json", lambda m: m.pop("red_team_skipped", None))
    _review(d, "The published share is 30%.")
    _forge(
        d,
        "validation.json",
        lambda v: v["sources"].append({"title": "A blog post", "url": "https://blog.example/post"}),
    )
    _replay(d)
    _accept(d, "RECORD_CHANGED_AFTER_REVIEW")
    _fires(d, "RECORD_CHANGED_AFTER_REVIEW")


def test_an_edited_review_survives_acceptance(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    _forge(d, "redteam.json", lambda r: r["findings"][0].update(severity="low"))
    _accept(d, "REDTEAM_ALTERED")
    _fires(d, "REDTEAM_ALTERED")


def test_a_founder_figure_rewritten_after_the_review_needs_more_than_the_flag(tmp_path: Path) -> None:
    """The founder's own figure, changed after the review with an approval the model wrote itself and
    no second review, is not the founder's decision on the record: nothing a script can check says so."""
    d = _reviewed_dir(tmp_path)
    _forge(d, "inputs.json", lambda i: i.update(founder_stated_inputs={"arpu": 150}))
    _fires(d, "FOUNDER_INPUT_REWRITTEN")
    _approve(d, "arpu", None, 150)
    _fires(d, "FOUNDER_INPUT_REWRITTEN", "RECORD_CHANGED_AFTER_REVIEW")


def test_a_founder_figure_changed_and_re_reviewed_is_still_reported(tmp_path: Path) -> None:
    """Was: the second review licensed the value it saw. Re-dispatching the review is itself a lever,
    so the founder-figure check is keyed on the first review, and an approval licenses nothing."""
    d = _reviewed_dir(tmp_path)
    _forge(d, "inputs.json", lambda i: i.update(founder_stated_inputs={"arpu": 150}))
    _approve(d, "arpu", None, 150)
    assert _review(d, "Round two: the revised price is supported.") == 2
    _fires(d, "FOUNDER_INPUT_REWRITTEN")
