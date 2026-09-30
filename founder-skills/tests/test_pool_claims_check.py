"""The pool-sizing judge as a backstop inside the cap-table pipeline (`pool_claims_check.py`).

The coaching commentary no longer discusses the option pool's sizing; the report's Option pool section does.
The backstop checks the coach's text before it is inserted, with the same judge the paid lanes use (held
byte-identical here), and is the step that writes the file `insert_coaching.py --commentary-file` reads: a run
that skips it has nothing to insert. On findings the main thread gets ONE corrective dispatch; if the text is
still flagged, `--strip` removes the flagged claims, keeps the original file, and says so to the founder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pool_sizing_claims  # noqa: E402
from test_cap_table import _CF_BASE_PARAMS, _cf_run  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "founder-skills" / "skills" / "cap-table" / "scripts"
_CHECK = _SCRIPTS / "pool_claims_check.py"
_SKILL = _REPO / "founder-skills" / "skills" / "cap-table" / "SKILL.md"


# --- one instrument ---------------------------------------------------------------------------------------------


def test_the_shipped_judge_is_the_tested_one() -> None:
    shipped = (_SCRIPTS / "_pool_sizing_claims.py").read_bytes()
    tested = (Path(__file__).resolve().parent / "_pool_sizing_claims.py").read_bytes()
    assert shipped == tested, "copy founder-skills/tests/_pool_sizing_claims.py over the skill's copy (or back)"


def test_each_finding_carries_its_span_over_the_original_text() -> None:
    text = "Intro line.\n\n- Founders and SAFE holders gain on the pre-money sizing.\n\nClose."
    findings = _pool_sizing_claims.pool_sizing_findings(text, modeled_basis="post_money", other_founders_pct=64.8)
    assert findings, text
    f = findings[0]
    assert text[f["start"] : f["end"]] == "- Founders and SAFE holders gain on the pre-money sizing."
    assert f["segment"] == "Founders and SAFE holders gain on the pre-money sizing."


def test_the_judge_arguments_come_from_the_run() -> None:
    co = _cf_run({"target_basis": "post_money"}, counterfactual=True, available_pool=400_000)
    doc = {"scenarios": [{"parameters": {**_CF_BASE_PARAMS, "target_basis": "post_money"}, "computed_outputs": co}]}
    args = _pool_sizing_claims.judge_arguments(doc)
    assert args["other_founders_pct"] == [round(co["pool_sizing_counterfactual"]["founders"]["other_value"] * 100, 1)]
    assert args["increase_founders_pct"] == [round(co["pool_increase_reading"]["founders"]["increase_value"] * 100, 1)]
    assert args["target_pct"] == 10.0


# --- the CLI ------------------------------------------------------------------------------------------------------


def _run_dir(tmp_path: Path, commentary: str, params: dict[str, Any] | None = None, **setup: int) -> Path:
    params = {"target_basis": "post_money"} if params is None else params
    co = _cf_run(params, counterfactual=True, **setup)
    scenarios = {
        "scenarios": [{"scenario_id": "s_round", "parameters": {**_CF_BASE_PARAMS, **params}, "computed_outputs": co}],
        "metadata": {"run_id": "run-1"},
    }
    (tmp_path / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
    (tmp_path / "report.md").write_text(
        "# Report\n\n**Option pool**\n\nConfirm with counsel that your term sheet measures the pool the way this "
        "section describes.\n",
        encoding="utf-8",
    )
    (tmp_path / "coaching.md").write_text(commentary, encoding="utf-8")
    return tmp_path


def _check(d: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_CHECK),
            str(d / "coaching.md"),
            "--scenarios",
            str(d / "scenarios.json"),
            "-o",
            str(d / "coaching.checked.json"),
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def _checked_text(d: Path) -> str:
    text: str = json.loads((d / "coaching.checked.json").read_text(encoding="utf-8"))["checked_commentary_markdown"]
    return text


_RELEASE = _SCRIPTS / "pool_check_release.py"


def _release(d: Path, coaching: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_RELEASE),
            str(coaching or d / "coaching.md"),
            "--checked",
            str(d / "coaching.checked.json"),
            "--scenarios",
            str(d / "scenarios.json"),
            "-o",
            str(d / "released.json"),
        ],
        capture_output=True,
        text=True,
    )


def _released(d: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((d / "released.json").read_text(encoding="utf-8"))
    return out


def _record(d: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((d / "coaching.md.pool-check.json").read_text(encoding="utf-8"))
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


_CLEAN = (
    "The largest driver is the new money.\n\n"
    "The option pool top-up takes about 10 points. The report's Option pool section explains how this pool was sized.\n"
)
_FLAGGED = (
    "The largest driver is the new money.\n\n"
    "Here is what changes if the term sheet measures the pool before the round:\n\n"
    "- Founders and SAFE holders gain on the pre-money sizing.\n\n"
    "Before signing, confirm your counsel review items.\n"
)


def test_clean_commentary_is_written_for_insertion_and_recorded(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _CLEAN)
    r = _check(d)
    assert r.returncode == 0, r.stderr
    envelope = json.loads((d / "coaching.checked.json").read_text(encoding="utf-8"))
    assert envelope == {"checked_commentary_markdown": _CLEAN}
    rec = _record(d)
    assert rec["action"] == "clean" and rec["findings"] == []
    assert rec["sha256"] == _sha(d / "coaching.md") and rec["run_id"] == "run-1"


def test_flagged_commentary_is_not_written_and_the_segments_are_named(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _FLAGGED)
    r = _check(d)
    assert r.returncode == 9, (r.returncode, r.stdout, r.stderr)
    assert not (d / "coaching.checked.json").exists()
    out = json.loads(r.stdout)
    assert any("pre-money sizing" in f["segment"] for f in out["findings"]), out
    assert _record(d)["action"] == "findings"


def test_strip_removes_the_flagged_claims_and_their_lead_in_and_says_so(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _FLAGGED)
    before = _sha(d / "coaching.md")
    r = _check(d, "--strip")
    assert r.returncode == 0, r.stderr
    text = _checked_text(d)
    assert "pre-money" not in text and "Here is what changes" not in text, text
    assert "The largest driver is the new money." in text and "confirm your counsel review items" in text
    assert text.rstrip().endswith(_pool_sizing_claims_strip_note())
    assert _sha(d / "coaching.md") == before, "the pre-strip file is kept as written"
    rec = _record(d)
    assert rec["action"] == "stripped" and rec["sha256"] == before and rec["findings"]


_FLAG = "Founders and SAFE holders gain on the pre-money sizing."


def _strip_text(tmp_path: Path, commentary: str) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    d = _run_dir(tmp_path, commentary)
    r = _check(d, "--strip")
    assert r.returncode == 0, r.stderr
    assert _record(d)["action"] == "stripped", _record(d)  # positive control: the judge flagged it
    text: str = _checked_text(d)
    return text


def test_strip_keeps_a_heading_whose_section_keeps_a_paragraph(tmp_path: Path) -> None:
    text = _strip_text(tmp_path, f"## What moves founders\n\n{_FLAG}\n\nThe new money is the largest driver.\n")
    assert _FLAG not in text
    assert "## What moves founders" in text and "The new money is the largest driver." in text, text
    # A heading whose only content was the flagged paragraph goes with it.
    text = _strip_text(tmp_path / "b", f"## What moves founders\n\n{_FLAG}\n\n## Next\n\nAsk counsel.\n")
    assert "## What moves founders" not in text and "## Next" in text and "Ask counsel." in text, text


def test_strip_keeps_a_heading_written_in_the_same_block_as_the_flagged_paragraph(tmp_path: Path) -> None:
    """No blank line between a heading and its flagged paragraph: the heading is split off before the block goes,
    so the clean paragraph after it stays under its own heading, not the previous one."""
    text = _strip_text(tmp_path, f"## Earlier\n\nIntro.\n\n## Pool\n{_FLAG}\n\nThe new money is the largest driver.\n")
    assert _FLAG not in text
    assert text.index("## Pool") < text.index("The new money is the largest driver."), text


def test_strip_treats_a_bold_line_as_a_heading(tmp_path: Path) -> None:
    """A line that is entirely bold reads as a heading; left with nothing under it, it goes too."""
    text = _strip_text(tmp_path, f"Intro.\n\n**Pool sizing**\n\n{_FLAG}\n\n**Next**\n\nAsk counsel.\n")
    assert "**Pool sizing**" not in text and "**Next**" in text and "Ask counsel." in text, text
    kept = _strip_text(tmp_path / "b", f"**Pool sizing**\n\n{_FLAG}\n\nThe new money is the largest driver.\n")
    assert "**Pool sizing**" in kept and "The new money is the largest driver." in kept, kept


def test_strip_keeps_a_bold_sentence_beside_a_removed_claim(tmp_path: Path) -> None:
    """A bolded takeaway is content, not a heading: a bold line ending in sentence punctuation stays when the
    flagged paragraph after it goes."""
    takeaway = "**The new money drives most of your dilution this round.**"
    text = _strip_text(tmp_path, f"{takeaway}\n\n{_FLAG}\n\n## Next\n\nAsk counsel.\n")
    assert _FLAG not in text and takeaway in text, text
    advice = "**Raise the question of the pool with counsel before signing.**"
    text = _strip_text(tmp_path / "b", f"Intro.\n\n{advice}\n\n{_FLAG}\n")
    assert _FLAG not in text and advice in text, text


def test_strip_keeps_a_bold_sentence_that_ends_in_a_parenthesis(tmp_path: Path) -> None:
    for i, line in enumerate(
        (
            "**Raise the question of the pool with counsel (before signing.)**",
            "**Raise the question of the pool with counsel (before signing).**",
        )
    ):
        text = _strip_text(tmp_path / str(i), f"Intro.\n\n{line}\n\n{_FLAG}\n")
        assert _FLAG not in text and line in text, text


def test_strip_removes_only_the_flagged_bullets_of_a_lead_in_block(tmp_path: Path) -> None:
    block = f"Here is what to raise:\n- {_FLAG}\n- The new money is the largest driver.\n"
    text = _strip_text(tmp_path, block)
    assert _FLAG not in text
    assert "Here is what to raise:" in text and "- The new money is the largest driver." in text, text
    # Every bullet flagged: the lead-in has nothing left to introduce, so it goes too.
    text = _strip_text(tmp_path / "b", f"Intro.\n\nHere is what to raise:\n- {_FLAG}\n")
    assert "Here is what to raise:" not in text and "Intro." in text, text


def test_the_strip_note_reads_right_for_one_or_several_removals(tmp_path: Path) -> None:
    note = _note("STRIP_NOTE")
    assert " here" not in note, "the note sits at the end of the commentary, not where the removal was"
    two = f"{_FLAG}\n\nA line.\n\n- {_FLAG.replace('Founders', 'Founders and employees')}\n"
    text = _strip_text(tmp_path, two)
    assert text.count(note) == 1 and text.rstrip().endswith(note), text


def _pool_sizing_claims_strip_note() -> str:
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import pool_claims_check  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    note: str = pool_claims_check.STRIP_NOTE
    return note


def test_a_basis_the_judge_cannot_take_says_so_to_the_founder(tmp_path: Path) -> None:
    """The judge takes one run-wide basis, post-money or pre-money; an increase-modeled run would have true
    sentences flagged and then stripped, so it is not judged -- and, like a check that could not run, it must not
    read like one it passed: the founder is told, and the record carries the code."""
    d = _run_dir(tmp_path, _FLAGGED, {"target_basis": "post_money_increase"})
    r = _check(d)
    assert r.returncode == 0, r.stderr
    text = _checked_text(d)
    assert text.startswith(_FLAGGED.rstrip()) and text.rstrip().endswith(_note("ERROR_NOTE")), text
    rec = _record(d)
    assert rec["action"] == "not_judged" and rec["reason"]
    assert (rec["code"], rec["severity"]) == ("POOL_CHECK_NOT_RUN", "medium")


def test_a_run_with_no_pool_target_has_nothing_to_check_and_no_note(tmp_path: Path) -> None:
    """No pool target means no pool sizing to get wrong; a note saying the pool statements were not checked would
    be about a pool the report does not model."""
    d = _run_dir(tmp_path, _CLEAN, {"target_pool_percent": None})
    r = _check(d)
    assert r.returncode == 0, r.stderr
    text = _checked_text(d)
    assert text == _CLEAN
    rec = _record(d)
    assert rec["action"] == "no_pool_target" and "code" not in rec


def test_the_reports_own_sentences_are_not_findings(tmp_path: Path) -> None:
    quoted = "Confirm with counsel that your term sheet measures the pool the way this section describes.\n"
    d = _run_dir(tmp_path, quoted)
    assert _check(d).returncode == 0


def test_nothing_the_report_holds_exempts_a_claim(tmp_path: Path) -> None:
    """The exempt text is rebuilt from the run's scenarios with the section builder, never parsed out of a report.
    Passing the commentary itself as the report, or a report already carrying the commentary -- plain, or opening
    with the section's own heading (a resume) -- exempted every segment and came out clean. The check takes no
    report at all now."""
    d = _run_dir(tmp_path, _FLAGGED)
    refused = _check(d, "--report-md", str(d / "coaching.md"))
    assert refused.returncode == 2 and "unrecognized arguments" in refused.stderr, refused.stderr
    for commentary in (_FLAGGED, "**Option pool**\n\n" + _FLAGGED):
        (d / "coaching.md").write_text(commentary, encoding="utf-8")
        inserted = "# Report\n\n**Option pool**\n\n## Coaching Commentary\n\n" + commentary
        (d / "report.md").write_text(inserted, encoding="utf-8")
        assert _check(d).returncode == 9, commentary


def test_the_sections_own_sentences_are_exempt_even_when_the_report_is_not_passed_them(tmp_path: Path) -> None:
    """What the builder renders for this run is exempt, with no report in sight."""
    from test_cap_table import _CF_BASE_PARAMS as base

    sys.path.insert(0, str(_SCRIPTS))
    try:
        import _pool_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    d = _run_dir(tmp_path, "x")
    doc = json.loads((d / "scenarios.json").read_text(encoding="utf-8"))
    scenario = {**doc["scenarios"][0], "parameters": {**base, "target_basis": "post_money"}}
    section = "\n".join(_pool_text.pool_section_markdown(_pool_text.pool_section(scenario, cap_state={})))
    (d / "coaching.md").write_text(section, encoding="utf-8")
    r = _check(d)
    assert r.returncode == 0, r.stdout
    assert _record(d)["action"] == "clean"


def test_the_check_fails_open_when_it_cannot_run_and_says_so_to_the_founder(tmp_path: Path) -> None:
    """Never blocks delivery once it has this run's figures -- but a run it could not check must not read like one
    it passed: the founder is told, in the commentary itself (compose ran before it, so no report warning can carry
    this), and the record carries a medium code and this run's id."""
    d = _run_dir(tmp_path, _FLAGGED)
    (d / "cap_state.json").write_text("{not json", encoding="utf-8")
    r = _check(d)
    assert r.returncode == 0, r.stderr
    text = _checked_text(d)
    assert text.startswith(_FLAGGED.rstrip()) and text.rstrip().endswith(_note("ERROR_NOTE")), text
    rec = _record(d)
    assert rec["action"] == "error" and rec["run_id"] == "run-1", rec
    assert (rec["code"], rec["severity"]) == ("POOL_CHECK_NOT_RUN", "medium")
    assert _release(d).returncode == 0


@pytest.mark.parametrize(
    "scenarios",
    [None, "{not json", "[]", json.dumps({"scenarios": [], "metadata": {}})],
    ids=["missing", "not-json", "not-an-object", "no-run-id"],
)
def test_the_check_refuses_when_it_cannot_read_this_runs_figures(tmp_path: Path, scenarios: str | None) -> None:
    """A mistyped or unreadable scenarios.json is not a check that could not run: failing open there would let a
    wrong path skip the judge. It refuses loudly, leaves -o unwritten, and nothing downstream releases it."""
    d = _run_dir(tmp_path, _FLAGGED)
    if scenarios is None:
        (d / "scenarios.json").unlink()
    else:
        (d / "scenarios.json").write_text(scenarios, encoding="utf-8")
    r = _check(d)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert json.loads(r.stdout)["status"] == "refused" and "pool_claims_check" in r.stderr
    assert not (d / "coaching.checked.json").exists()
    assert _record(d)["action"] == "refused"
    assert _release(d).returncode == 1


def test_the_release_refuses_a_could_not_run_record_with_no_run(tmp_path: Path) -> None:
    """The check now always knows the run before it can fail open, so a could-not-run record without one was not
    written by it."""
    d = _run_dir(tmp_path, _CLEAN)
    assert _check(d).returncode == 0
    rec = _record(d)
    rec.update(action="error", run_id=None)
    (d / "coaching.md.pool-check.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _release(d)
    assert r.returncode == 1 and "another run" in r.stderr, r.stderr


def test_a_run_it_could_check_carries_no_such_line(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _CLEAN)
    assert _check(d).returncode == 0
    text = _checked_text(d)
    assert _note("ERROR_NOTE") not in text
    assert "code" not in _record(d)


def _note(name: str) -> str:
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import pool_claims_check  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    note: str = getattr(pool_claims_check, name)
    return note


# --- the runtime enforces the check: only a matching record releases the commentary -----------------------------


def test_the_checked_file_is_not_what_insert_coaching_reads(tmp_path: Path) -> None:
    """Fed to insert_coaching directly, the check's output is refused: only the release step makes the envelope."""
    d = _run_dir(tmp_path, _CLEAN)
    assert _check(d).returncode == 0
    assert "commentary_markdown" not in json.loads((d / "coaching.checked.json").read_text(encoding="utf-8"))


def test_a_matching_record_releases_the_checked_commentary(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _CLEAN)
    assert _check(d).returncode == 0
    r = _release(d)
    assert r.returncode == 0, r.stderr
    assert _released(d) == {
        "commentary_markdown": _CLEAN,
        "check_record": str((d / "coaching.md.pool-check.json").resolve()),
    }


def test_the_release_refuses_whatever_the_check_did_not_pass(tmp_path: Path) -> None:
    # No check ran: no record.
    (tmp_path / "none").mkdir()
    d = _run_dir(tmp_path / "none", _CLEAN)
    (d / "coaching.checked.json").write_text(json.dumps({"checked_commentary_markdown": _CLEAN}), encoding="utf-8")
    cases = {"no record": _release(d)}
    # The commentary changed after the check.
    (tmp_path / "edited").mkdir()
    e = _run_dir(tmp_path / "edited", _CLEAN)
    assert _check(e).returncode == 0
    (e / "coaching.md").write_text(_FLAGGED, encoding="utf-8")
    cases["commentary edited"] = _release(e)
    # The checked file was replaced after the check.
    (tmp_path / "swapped").mkdir()
    w = _run_dir(tmp_path / "swapped", _FLAGGED)
    assert _check(w, "--strip").returncode == 0
    (w / "coaching.checked.json").write_text(json.dumps({"checked_commentary_markdown": _FLAGGED}), encoding="utf-8")
    cases["checked file swapped"] = _release(w)
    # Findings still open (exit 9 writes no checked file; a stale one from an earlier check must not pass).
    (tmp_path / "open").mkdir()
    o = _run_dir(tmp_path / "open", _CLEAN)
    assert _check(o).returncode == 0
    (o / "coaching.md").write_text(_FLAGGED, encoding="utf-8")
    assert _check(o).returncode == 9
    cases["findings open"] = _release(o)
    # A record from another run.
    (tmp_path / "stale").mkdir()
    t = _run_dir(tmp_path / "stale", _CLEAN)
    assert _check(t).returncode == 0
    doc = json.loads((t / "scenarios.json").read_text(encoding="utf-8"))
    doc["metadata"]["run_id"] = "run-2"
    (t / "scenarios.json").write_text(json.dumps(doc), encoding="utf-8")
    cases["another run"] = _release(t)
    for name, r in cases.items():
        assert r.returncode == 1, (name, r.returncode, r.stdout)
        assert r.stderr.strip() and "commentary_markdown" not in r.stdout, (name, r.stdout)
        assert json.loads(r.stdout)["status"] == "refused", name
    for sub in ("none", "edited", "swapped", "open", "stale"):
        assert not (tmp_path / sub / "released.json").exists(), sub  # a refusal writes nothing


# --- the pipeline runs it -----------------------------------------------------------------------------------------


def _step11() -> str:
    text = _SKILL.read_text(encoding="utf-8")
    start = text.index("### Step 11:")
    return text[start : text.index("\n### ", start + 10)]


def test_step_11_inserts_only_what_the_release_wrote() -> None:
    step = _step11()
    assert '--commentary-file "$HANDOFF_DIR/coaching.released.json"' in step
    assert "md_to_commentary.py" not in step, "cap-table's commentary reaches insert_coaching only through the check"
    at = [step.index(x) for x in ("check_handoff.py", "pool_claims_check.py", "pool_check_release.py")]
    assert at == sorted(at) and at[-1] < step.index('"$SHARED_SCRIPTS/insert_coaching.py"')
    # Two commands, not a pipe: the release's refusal must not surface as insert_coaching's "missing" reason, which
    # routes to a repair-dispatch. dash has no pipefail, so the split is the only way to branch on each.
    assert not re.search(r"pool_check_release\.py[^`]*?\|\s*\\?\s*python3", step), "release piped into insert"


def test_step_11_states_the_one_redo_then_the_strip() -> None:
    step = " ".join(_step11().split())
    assert "**`pool_claims_check.py` exit 9**" in step
    assert "--strip" in step
    assert "If the budget is already spent, or it exits 9 again, re-run it with `--strip`" in step
    assert "the dispatch counts against the budget" in step
    # The redo on the two paths without a normal file dispatch.
    assert "on the degrade path it also asks for the commentary inline" in step
    assert "on the inline path there is no dispatch" in step


def test_a_refused_release_and_a_malformed_hand_off_take_different_branches() -> None:
    step = " ".join(_step11().split())
    release = step[step.index("**`pool_check_release.py` exit 1**") :]
    release = release[: release.index("- **")]
    assert "re-run `pool_claims_check.py`" in release and "never a repair-dispatch" in release, release
    insert = step[step.index("**`insert_coaching.py` exit 1**") :]
    insert = insert[: insert.index("- **")]
    record = insert[insert.index("passing check record") :]
    assert "re-run the check and the release" in record.split(". ")[0] and "never a repair-dispatch" in record
    assert "`commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch" in insert


def test_every_insertion_path_goes_through_the_check() -> None:
    """The graceful-degrade path and the inline path used to feed insert_coaching directly. The inline path's
    scratch files go to the hand-off dir, never the delivered review dir."""
    step = " ".join(_step11().split())
    degrade = step[step.index("**Graceful degrade:**") :]
    assert "the check, the release and `insert_coaching.py`" in degrade[:2000] and "$STAGING_DIR" in degrade[:2000]
    inline = step[step.index("**Inline alternative") :]
    assert '"$HANDOFF_DIR/coaching.md"' in inline and '"$REVIEW_DIR/coaching.md"' not in inline
    assert "the check, the release and the script are the single insertion path" in inline


def test_both_paid_lanes_assert_the_backstop_engaged() -> None:
    source = (Path(__file__).resolve().parent / "test_e2e_cap_table.py").read_text(encoding="utf-8")
    assert source.count("assert_pool_backstop_engaged(review_dir)") == 2
    assert "coaching.md.pool-check.json" in source and "coaching.checked.json" in source


# --- the founder sees what the check did, on the surfaces the commentary reaches -----------------------------


def _deliver(tmp_path: Path, commentary: str, *, break_check: bool = False) -> dict[str, str]:
    """compose -> both pages (Steps 9-10, before coaching, as in the pipeline) -> the check -> insert_coaching."""
    from test_cap_table import _make_cap_compose_dir, _run_cap_compose

    params = {"target_basis": "post_money"}
    scenario = {
        "scenario_id": "s_round",
        "label": "Series A",
        "type": "priced_round",
        "parameters": {**_CF_BASE_PARAMS, **params},
        "computed_outputs": _cf_run(params, counterfactual=True),
    }
    d = Path(_make_cap_compose_dir(scenarios=[scenario]))
    rc, report, err = _run_cap_compose(str(d))
    assert rc == 0, err
    for script, out in (("visualize.py", "report.html"), ("explore.py", "explorer.html")):
        r = subprocess.run(
            [sys.executable, str(_SCRIPTS / script), "--dir", str(d), "-o", str(d / out)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
    (d / "coaching.md").write_text(commentary, encoding="utf-8")
    scenarios = str(d / "scenarios.json")
    if break_check:  # the figures load, then the check fails: it fails open
        (d / "cap_state.json").write_text("{not json", encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(_CHECK),
            str(d / "coaching.md"),
            "--scenarios",
            scenarios,
            "-o",
            str(d / "coaching.checked.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    released = _release(d)
    assert released.returncode == 0, released.stderr
    insert = _REPO / "founder-skills" / "scripts" / "insert_coaching.py"
    r = subprocess.run(
        [
            sys.executable,
            str(insert),
            "--report",
            str(d / "report.md"),
            "--report-json",
            str(d / "report.json"),
            "--marker",
            report["coaching_payload"]["insertion_marker"],
            "--commentary-file",
            str(d / "released.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    return {
        "report.md": (d / "report.md").read_text(encoding="utf-8"),
        "report.json": json.loads((d / "report.json").read_text(encoding="utf-8"))["report_markdown"],
        "report.html": (d / "report.html").read_text(encoding="utf-8"),
        "explorer.html": (d / "explorer.html").read_text(encoding="utf-8"),
    }


def test_an_unchecked_commentary_says_so_where_the_commentary_is_delivered(tmp_path: Path) -> None:
    surfaces = _deliver(tmp_path, _CLEAN, break_check=True)
    note = _note("ERROR_NOTE")
    assert note in surfaces["report.md"] and note in surfaces["report.json"]
    # The two pages are built before the commentary exists (Steps 9-10) and carry none of it -- this line or any
    # other -- so the founder who opens only a page never sees an unchecked pool statement either.
    for page in ("report.html", "explorer.html"):
        assert note not in surfaces[page] and "The largest driver is the new money." not in surfaces[page]


def test_a_checked_commentary_carries_neither_note(tmp_path: Path) -> None:
    surfaces = _deliver(tmp_path, _CLEAN)
    assert "The largest driver is the new money." in surfaces["report.md"]
    for text in surfaces.values():
        assert _note("ERROR_NOTE") not in text and _note("STRIP_NOTE") not in text


def test_commentary_that_skipped_the_check_is_refused_by_the_report(tmp_path: Path) -> None:
    """The bypass: the gated markdown wrapped by the generic envelope script and piped straight into
    insert_coaching. cap-table's report declares that it needs a passing check record, so it refuses."""
    from test_cap_table import _make_cap_compose_dir, _run_cap_compose

    params = {"target_basis": "post_money"}
    scenario = {
        "scenario_id": "s_round",
        "label": "Series A",
        "type": "priced_round",
        "parameters": {**_CF_BASE_PARAMS, **params},
        "computed_outputs": _cf_run(params, counterfactual=True),
    }
    d = Path(_make_cap_compose_dir(scenarios=[scenario]))
    rc, report, err = _run_cap_compose(str(d))
    assert rc == 0, err
    before = (d / "report.md").read_text(encoding="utf-8")
    assert "COACHING_REQUIRES_CHECK_RECORD" in before  # positive control: the declaration is there
    (d / "coaching.md").write_text(_CLEAN, encoding="utf-8")
    shared = _REPO / "founder-skills" / "scripts"
    wrapped = subprocess.run(
        [sys.executable, str(shared / "md_to_commentary.py"), str(d / "coaching.md")], capture_output=True, text=True
    )
    assert wrapped.returncode == 0, wrapped.stderr
    r = subprocess.run(
        [
            sys.executable,
            str(shared / "insert_coaching.py"),
            "--report",
            str(d / "report.md"),
            "--marker",
            report["coaching_payload"]["insertion_marker"],
        ],
        input=wrapped.stdout,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1 and json.loads(r.stdout)["status"] == "blocked", (r.returncode, r.stdout)
    assert (d / "report.md").read_text(encoding="utf-8") == before


def test_the_declaration_never_reaches_a_delivered_surface(tmp_path: Path) -> None:
    surfaces = _deliver(tmp_path, _CLEAN)
    for name, text in surfaces.items():
        assert "COACHING_REQUIRES_CHECK_RECORD" not in text, name


def test_the_founder_notes_pass_the_founder_text_scan_and_the_judge() -> None:
    import re

    sys.path.insert(0, str(_REPO / "founder-skills" / "scripts"))
    try:
        import _founder_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    for name in ("ERROR_NOTE", "STRIP_NOTE"):
        note = _note(name)
        assert _founder_text.scan(note) == {"enums": [], "filenames": []}, note
        assert not re.search(r"\d|\b(?:pre|post)[- ](?:money|round)\b|\bshare count\b|\bbasis\b", note, re.I), note
        for basis in ("post_money", "pre_money"):
            assert not _pool_sizing_claims.pool_sizing_problems(note, modeled_basis=basis, other_founders_pct=None), (
                note
            )
