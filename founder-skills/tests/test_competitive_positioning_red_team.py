"""competitive-positioning's outside review: the producer, the skip record, what a review is taken against,
and which review compose resolves. The shared rules are pinned in test_redteam_core.py and by
market-sizing's suites; what is pinned here is this skill's side of them."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "competitive-positioning" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "competitive-positioning"


def _load(name: str) -> Any:
    """A skill script by path, under a name no other skill's module uses: skills share filenames
    (compose_report.py), and the suite imports them into one process."""
    import importlib.util

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # the script's own sibling imports resolve from here
    spec = importlib.util.spec_from_file_location(f"cp_red_team_test__{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cp_redteam_copy = _load("_cp_redteam_copy")
humanize_review_text = _load("_cp_redteam_text").humanize_review_text

RUN = "20260101T000000Z"


def _analysis(tmp_path: Path) -> Path:
    """The fixture analysis, stamped with this run's id, plus the run's hand-off dir."""
    d = tmp_path / "competitive-positioning-acme"
    d.mkdir(parents=True)
    for src in FIXTURES.glob("*.json"):
        if src.name == "red_team_skip.json":  # each test here records (or withholds) its own decision
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("metadata", {})["run_id"] = RUN
        (d / src.name).write_text(json.dumps(data), encoding="utf-8")
    (d / "handoff" / RUN / "docs").mkdir(parents=True)
    return d


def _a_slug_and_name(d: Path) -> tuple[str, str]:
    comp = json.loads((d / "landscape.json").read_text(encoding="utf-8"))["competitors"][0]
    return comp["slug"], comp["name"]


def _finding(**over: Any) -> dict[str, Any]:
    f = {
        "claim_attacked": "a claim",
        "what_is_true": "what is true",
        "evidence_quote": "a sentence long enough to be quoted from the source here",
        "source_url": "https://example.com/page",
        "source_title": "Example",
        "severity": "medium",
    }
    f.update(over)
    return f


def _pipe(d: Path, payload: dict[str, Any], *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cp_red_team.py"),
            "--run-id",
            RUN,
            "--uploads-dir",
            str(d / "handoff" / RUN / "docs"),
            "-o",
            str(d / "redteam.json"),
            *extra,
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _compose(d: Path) -> dict[str, Any]:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "compose_report.py"), "--dir", str(d)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr[-800:]
    out: dict[str, Any] = json.loads(r.stdout)
    return out


def _codes(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {w["code"]: w for w in report["warnings"]}


# --- the wording ------------------------------------------------------------------------------------


def test_the_review_names_competitors_and_files_the_way_the_founder_knows_them() -> None:
    text, n = humanize_review_text(
        "moat_scores.json rates carbon-robotics on switching_costs; _startup has custom_distribution_channel.",
        name_by_slug={"carbon-robotics": "Carbon Robotics"},
        startup_name="Acme",
    )
    assert text == "The moat ratings rates Carbon Robotics on switching costs; Acme has distribution channel."
    assert n == 5


def test_the_founders_own_files_urls_and_ordinary_words_are_left_alone() -> None:
    text, _ = humanize_review_text(
        "See deck_v2.md and https://acme.com/moat_scores.json; the notion is wrong.",
        ["deck_v2.md"],
        name_by_slug={"notion": "Notion"},
    )
    assert text == "See deck_v2.md and https://acme.com/moat_scores.json; the notion is wrong."


def test_a_longer_slug_is_never_partly_replaced_by_a_shorter_one() -> None:
    text, _ = humanize_review_text(
        "acme-pro and acme-x", name_by_slug={"acme-x": "Acme X", "acme-pro": "Acme Pro", "acme": "Acme"}
    )
    assert text == "Acme Pro and Acme X"


# --- the producer -----------------------------------------------------------------------------------


def test_the_review_reaches_the_founder_worded_and_its_quote_untouched(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    slug, name = _a_slug_and_name(d)
    quote = f"The {slug} record in moat_scores.json says what it says, verbatim."
    r = _pipe(
        d,
        {
            "findings": [
                _finding(
                    claim_attacked=f"{slug}'s switching_costs", what_is_true="see landscape.json", evidence_quote=quote
                )
            ],
            "could_not_check": [f"{slug}'s pricing page, behind a login"],
        },
    )
    assert r.returncode == 0, r.stdout + r.stderr
    review = json.loads((d / "redteam.json").read_text(encoding="utf-8"))
    f = review["findings"][0]
    assert f["claim_attacked"] == f"{name}'s switching costs"
    assert f["what_is_true"] == "see the competitor research"
    assert f["evidence_quote"] == quote  # a quotation is never reworded
    assert review["could_not_check"] == [f"{name}'s pricing page, behind a login"]
    assert review["_produced_by"] == "cp_red_team"
    assert review["metadata"] == {"run_id": RUN}
    copy = json.loads((d / "handoff" / RUN / "redteam.r1.json").read_text(encoding="utf-8"))
    assert copy["_review_copy"]["round"] == 1
    assert copy["inputs_reviewed"] == _cp_redteam_copy.reviewed_state(str(d))


def test_a_weak_finding_is_set_aside_and_the_rest_are_kept(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    r = _pipe(d, {"findings": [_finding(), _finding(source_url="somewhere"), _finding(severity="fatal")]})
    assert r.returncode == 0, r.stderr
    review = json.loads((d / "redteam.json").read_text(encoding="utf-8"))
    assert review["summary"]["accepted"] == 1 and review["summary"]["rejected"] == 2


def test_a_citation_to_the_founders_page_is_checked_against_it(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    (d / "handoff" / RUN / "docs" / "notes.md").write_text(
        "We have signed three paying pilot customers in the logistics sector this year.\n", encoding="utf-8"
    )
    found = _finding(
        source_url="document:notes.md",
        evidence_quote="We have signed three paying pilot customers in the logistics sector",
    )
    absent = _finding(
        source_url="document:notes.md", evidence_quote="We have signed forty enterprise contracts this year"
    )
    r = _pipe(d, {"findings": [found, absent], "sources_read": ["notes.md"]})
    assert r.returncode == 0, r.stderr
    verified = [f["quote_verified"] for f in json.loads((d / "redteam.json").read_text(encoding="utf-8"))["findings"]]
    assert verified == [True, False]


def test_a_review_that_cannot_be_worded_is_refused(tmp_path: Path) -> None:
    """No landscape, no names: a review printed with slugs is the leak it exists to prevent."""
    d = _analysis(tmp_path)
    (d / "landscape.json").unlink()
    (d / "redteam.json").write_text('{"sentinel": true}', encoding="utf-8")
    r = _pipe(d, {"findings": []})
    assert r.returncode != 0
    assert json.loads((d / "redteam.json").read_text(encoding="utf-8")) == {"sentinel": True}
    assert "landscape.json" in r.stdout


def test_a_missing_core_is_refused_loudly_even_when_the_text_policy_is_present(tmp_path: Path) -> None:
    """A mixed install: the shared dir carries the founder-text policy but not the red-team core."""
    lone = tmp_path / "plugin" / "skills" / "competitive-positioning" / "scripts"
    lone.mkdir(parents=True)
    for name in ("cp_red_team.py", "_cp_redteam_copy.py", "_cp_redteam_text.py", "_quote_match.py"):
        shutil.copy(SCRIPTS / name, lone / name)
    for name in ("cp_dispatch_prompt.py", "_cp_view.py"):
        shutil.copy(SCRIPTS / name, lone / name)
    shared = tmp_path / "plugin" / "scripts"
    shared.mkdir()
    shutil.copy(ROOT / "scripts" / "_founder_text.py", shared / "_founder_text.py")
    d = _analysis(tmp_path)
    out = d / "redteam.json"
    out.write_text('{"sentinel": true}', encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(lone / "cp_red_team.py"), "--run-id", RUN, "-o", str(out)],
        input=json.dumps({"findings": [_finding()]}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode != 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"sentinel": True}
    assert "shared scripts" in r.stdout and "_redteam_core.py" in r.stdout, r.stdout


# --- what a review is taken against ------------------------------------------------------------------


def test_the_fingerprinted_files_are_the_ones_the_reviewer_was_given() -> None:
    cp_dispatch_prompt = _load("cp_dispatch_prompt")

    state = _cp_redteam_copy.reviewed_state(str(FIXTURES))
    assert list(state) == [*cp_dispatch_prompt.RED_TEAM_ARTIFACTS, *cp_dispatch_prompt.RED_TEAM_OPTIONAL]


def test_an_absent_public_record_fingerprints_as_a_fixed_value(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _cp_redteam_copy.reviewed_state(str(d))["startup_research.json"] == _cp_redteam_copy.ABSENT
    assert _cp_redteam_copy.reviewed_state(str(d)) == _cp_redteam_copy.reviewed_state(str(d))


def test_todays_date_on_a_re_piped_landscape_is_not_a_change(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    before = _cp_redteam_copy.reviewed_state(str(d))
    land = json.loads((d / "landscape.json").read_text(encoding="utf-8"))
    land["landscape_as_of"] = "2099-01-01"
    (d / "landscape.json").write_text(json.dumps(land, indent=4), encoding="utf-8")  # a re-pipe, reformatted
    assert _cp_redteam_copy.reviewed_state(str(d)) == before
    land["competitors"] = land["competitors"][1:]
    (d / "landscape.json").write_text(json.dumps(land), encoding="utf-8")
    assert _cp_redteam_copy.reviewed_state(str(d))["landscape.json"] != before["landscape.json"]


# --- which review compose shows -----------------------------------------------------------------------


def test_compose_shows_the_review_as_written_when_redteam_json_is_edited(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding(severity="high")]}).returncode == 0
    softened = json.loads((d / "redteam.json").read_text(encoding="utf-8"))
    softened["findings"] = []
    (d / "redteam.json").write_text(json.dumps(softened), encoding="utf-8")
    w = _codes(_compose(d))["REDTEAM_ALTERED"]
    assert w["severity"] == "medium"
    assert "redteam" not in w.get("founder_message", "")


def test_a_change_to_the_analysis_after_the_review_is_disclosed_and_names_what_changed(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    scores = json.loads((d / "moat_scores.json").read_text(encoding="utf-8"))
    scores["edited_after_review"] = True
    (d / "moat_scores.json").write_text(json.dumps(scores), encoding="utf-8")
    codes = _codes(_compose(d))
    assert "the moat ratings" in codes["ANALYSIS_CHANGED_AFTER_REVIEW"]["message"]
    assert "REDTEAM_ALTERED" not in codes


def test_an_unchanged_analysis_raises_nothing_about_the_review(tmp_path: Path) -> None:
    """Positive control for the two tests above: the codes fire on a change, not on every review."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding()]}).returncode == 0
    codes = _codes(_compose(d))
    for code in (
        "REDTEAM_ALTERED",
        "ANALYSIS_CHANGED_AFTER_REVIEW",
        "REVIEW_COPY_MISSING",
        "RED_TEAM_SKIP_CONTRADICTED",
    ):
        assert code not in codes, code


def test_a_skip_recorded_beside_a_review_that_ran_is_disclosed(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "record_red_team_skip.py"),
            "--reason",
            "founder_declined",
            "--run-id",
            RUN,
            "-o",
            str(d / "red_team_skip.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "RED_TEAM_SKIP_CONTRADICTED" in _codes(_compose(d))


def test_a_skip_record_from_another_run_is_not_this_runs_decision() -> None:
    record = {"reason": "founder_declined", "metadata": {"run_id": "an-earlier-run"}}
    assert _cp_redteam_copy.skip_reason(record, RUN) is None
    assert _cp_redteam_copy.skip_reason({**record, "metadata": {"run_id": RUN}}, RUN) == "founder_declined"
    assert _cp_redteam_copy.skip_reason({"reason": "not_needed", "metadata": {"run_id": RUN}}, RUN) is None


@pytest.mark.parametrize(
    "code",
    [
        "REDTEAM_ALTERED",
        "RED_TEAM_SKIP_CONTRADICTED",
        "ANALYSIS_CHANGED_AFTER_REVIEW",
        "ANALYSIS_CHANGED_BETWEEN_REVIEWS",
    ],
)
def test_a_deliver_only_disclosure_neither_blocks_strict_nor_can_be_accepted_away(code: str) -> None:
    """Step 7's second pass is --strict: high would stop a run nothing can fix. Medium in the
    unacceptable set: the model-written accepted_warnings cannot clear it."""
    compose_report = _load("compose_report")

    assert compose_report.WARNING_SEVERITY[code] == "medium"
    assert code in compose_report._UNACCEPTABLE_MEDIUM


def test_the_review_is_a_gated_hand_off(tmp_path: Path) -> None:
    """A review piped without its hand-off passing the gate is named, like every other step."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    report = _compose(d)
    bypassed = _codes(report).get("HANDOFF_BYPASSED")
    assert bypassed is not None and "the outside review" in bypassed["message"], report["warnings"]


# --- two runs in one analysis dir ------------------------------------------------------------------------

RUN_2 = "20260102T000000Z"


def _restamp(d: Path, run_id: str) -> None:
    """A second run over the same dir: every artifact but the review's files carries the new run id."""
    for p in d.glob("*.json"):
        if p.name in _cp_redteam_copy.RUN_SCOPED:
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("metadata", {})["run_id"] = run_id
            p.write_text(json.dumps(data), encoding="utf-8")
    (d / "handoff" / run_id / "docs").mkdir(parents=True, exist_ok=True)


def _skip(d: Path, run_id: str) -> None:
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "record_red_team_skip.py"),
            "--reason",
            "dispatch_failed",
            "--run-id",
            run_id,
            "-o",
            str(d / "red_team_skip.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr


def _no_leftover_codes(report: dict[str, Any]) -> None:
    codes = _codes(report)
    stale = [w for w in report["warnings"] if w["code"] == "STALE_ARTIFACT"]
    assert not any(("redteam" in w["message"] or "red_team_skip" in w["message"]) for w in stale), stale
    assert "RED_TEAM_SKIP_CONTRADICTED" not in codes
    assert "REDTEAM_ALTERED" not in codes


def test_an_earlier_runs_review_neither_stops_nor_speaks_for_a_run_that_recorded_a_skip(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding(severity="high")]}).returncode == 0  # run 1 reviewed
    _restamp(d, RUN_2)
    _skip(d, RUN_2)  # run 2 recorded that no review ran
    report = _compose(d)
    _no_leftover_codes(report)
    # Run 1's review never went through run 2's hand-off: naming it as a step that bypassed the check
    # would tell the founder something that did not happen in this run.
    bypassed = _codes(report).get("HANDOFF_BYPASSED")
    assert bypassed is None or "the outside review" not in bypassed["message"], bypassed
    shown, _codes_, _facts = _cp_redteam_copy.resolve(
        str(d), RUN_2, json.loads((d / "redteam.json").read_text(encoding="utf-8")), None
    )
    assert shown is None, "an earlier run's review was returned as this run's"


def test_an_earlier_runs_skip_record_does_not_contradict_a_run_that_reviewed(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    _skip(d, RUN)  # run 1 recorded a skip
    _restamp(d, RUN_2)
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cp_red_team.py"),
            "--run-id",
            RUN_2,
            "-o",
            str(d / "redteam.json"),
        ],
        input=json.dumps({"findings": []}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr  # run 2 reviewed
    _no_leftover_codes(_compose(d))


def test_a_review_of_an_earlier_version_is_disclosed_when_a_later_review_matches(tmp_path: Path) -> None:
    """Round 1 reviews the analysis, the scores are changed, round 2 reviews the change. Round 2 is of
    the analysis as delivered -- and round 1, the review of what was there before, must not vanish."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding(severity="high", claim_attacked="round one")]}).returncode == 0
    scores = json.loads((d / "moat_scores.json").read_text(encoding="utf-8"))
    scores["edited_between_reviews"] = True
    (d / "moat_scores.json").write_text(json.dumps(scores), encoding="utf-8")
    assert _pipe(d, {"findings": [_finding(claim_attacked="round two")]}).returncode == 0
    codes = _codes(_compose(d))
    assert "the moat ratings" in codes["ANALYSIS_CHANGED_BETWEEN_REVIEWS"]["message"]
    assert "ANALYSIS_CHANGED_AFTER_REVIEW" not in codes
    shown, _c, facts = _cp_redteam_copy.resolve(str(d), RUN, None, None)
    assert shown is not None and shown["findings"][0]["claim_attacked"] == "round two"
    assert facts["rounds"] == 2 and facts["round_shown"] == 2


def test_two_reviews_of_the_same_analysis_raise_no_change_code(tmp_path: Path) -> None:
    """Positive control: a second review of an unchanged analysis is a later round, not a change."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding(claim_attacked="round one")]}).returncode == 0
    assert _pipe(d, {"findings": [_finding(claim_attacked="round two")]}).returncode == 0
    codes = _codes(_compose(d))
    assert "ANALYSIS_CHANGED_BETWEEN_REVIEWS" not in codes and "ANALYSIS_CHANGED_AFTER_REVIEW" not in codes


# --- the gate ---------------------------------------------------------------------------------------------


def _compose_run(d: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "compose_report.py"),
            "--dir",
            str(d),
            "-o",
            str(d / "report.json"),
            "--write-md",
            str(d / "report.md"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_run_with_no_review_and_no_recorded_skip_is_refused(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    (d / "report.md").write_text("PRIOR", encoding="utf-8")
    r = _compose_run(d)
    assert r.returncode == 1
    assert "record_red_team_skip.py" in r.stdout and "Step 6.5" in r.stdout
    assert (d / "report.md").read_text(encoding="utf-8") == "PRIOR", "a refusal must leave the report untouched"
    assert not (d / "report.json").exists()


def test_a_run_composes_with_its_review_or_its_recorded_skip(tmp_path: Path) -> None:
    reviewed = _analysis(tmp_path / "a")
    assert _pipe(reviewed, {"findings": []}).returncode == 0
    assert _compose_run(reviewed).returncode == 0
    skipped = _analysis(tmp_path / "b")
    _skip(skipped, RUN)
    assert _compose_run(skipped).returncode == 0


def test_another_runs_review_does_not_satisfy_the_gate(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    _restamp(d, RUN_2)
    r = _compose_run(d)
    assert r.returncode == 1, "a review from an earlier run let this run's report through"


def test_deleting_the_handoff_dir_does_not_silence_the_gate(tmp_path: Path) -> None:
    """The gate keys on the run's id, not on its hand-off dir: deleting the dir once read as "not a run"
    and let a report through with neither a review nor a recorded skip."""
    d = _analysis(tmp_path)
    shutil.rmtree(d / "handoff")
    r = _compose_run(d)
    assert r.returncode == 1 and "record_red_team_skip.py" in r.stdout
    _skip(d, RUN)
    assert _compose_run(d).returncode == 0  # control: a recorded skip still satisfies it


def _refused(d: Path, r: subprocess.CompletedProcess[str], other_review: str | None = None) -> None:
    """Refused, writing nothing. With `other_review`, the refusal names that run's review and offers no skip:
    recording one would hide the review the analysis has."""
    assert r.returncode == 1, f"composed (rc {r.returncode}) with no review or skip of this run: {r.stdout[-400:]}"
    if other_review is None:
        assert "record_red_team_skip.py" in r.stdout
    else:
        assert f"a review exists for run {other_review}, not this run" in r.stdout, r.stdout[-400:]
        assert "record_red_team_skip.py" not in r.stdout and "founder_declined" not in r.stdout
    assert not (d / "report.json").exists(), "a refusal must write nothing"


def _stamp(d: Path, name: str, run_id: str) -> None:
    data = json.loads((d / name).read_text(encoding="utf-8"))
    data.setdefault("metadata", {})["run_id"] = run_id
    (d / name).write_text(json.dumps(data), encoding="utf-8")


def test_a_review_or_skip_of_another_run_in_a_mixed_set_is_refused(tmp_path: Path) -> None:
    """The gate keys on the run id the report is resolved for (the id most required artifacts carry), the
    same id `resolve` and `skip_reason` use. A skip of the id only a leftover carries is not this run's
    decision, and the refusal names the mixed set. The leftover is listed FIRST (landscape.json), where a
    first-artifact rule would have taken its id for the run's and accepted the skip."""
    d = _analysis(tmp_path)
    _stamp(d, "landscape.json", RUN_2)
    _skip(d, RUN_2)
    r = _compose_run(d)
    _refused(d, r)
    assert "more than one run" in r.stdout and RUN in r.stdout and RUN_2 in r.stdout


def test_a_skip_of_this_run_passes_a_set_with_one_leftover_to_stale_artifact(tmp_path: Path) -> None:
    """Control for the case above: the skip IS this run's (the id four of five artifacts carry), so the gate
    passes and STALE_ARTIFACT names the leftover. A first-artifact rule refused this run for its own skip."""
    d = _analysis(tmp_path)
    _stamp(d, "landscape.json", "an-earlier-run")
    _skip(d, RUN)
    r = _compose_run(d)
    assert r.returncode == 0, r.stdout[-600:]
    assert "STALE_ARTIFACT" in (d / "report.json").read_text(encoding="utf-8")


def test_stale_artifact_names_the_leftover_and_agrees_with_the_gate(tmp_path: Path) -> None:
    """The leftover is listed first. STALE_ARTIFACT must name it -- not the four fresh files -- and the
    report must carry the run id the review was resolved for."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    _stamp(d, "landscape.json", "an-earlier-run")
    r = _compose_run(d)
    assert r.returncode == 0, r.stdout[-600:]
    report = json.loads((d / "report.json").read_text(encoding="utf-8"))
    stale = [w["message"] for w in report["warnings"] if w["code"] == "STALE_ARTIFACT"]
    assert stale == [f"landscape.json has run_id 'an-earlier-run' but expected '{RUN}'"], stale
    assert report["metadata"]["run_id"] == RUN


def test_an_earlier_runs_review_does_not_pass_a_set_with_a_leftover_landscape(tmp_path: Path) -> None:
    """Run 1 reviewed; run 2 regenerated every artifact but landscape.json, the first one listed, and recorded
    no review or skip. One leftover file must not make run 1's review stand in for run 2's."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    _restamp(d, RUN_2)
    _stamp(d, "landscape.json", RUN)
    _refused(d, _compose_run(d), other_review=RUN)


def _second_run_with_a_stale_checklist(tmp_path: Path, checklist: dict[str, Any] | None = None) -> Path:
    """Run 1 reviewed; run 2 regenerated every artifact but the checklist and recorded no review or skip."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    _restamp(d, RUN_2)
    ck = checklist if checklist is not None else json.loads((d / "checklist.json").read_text(encoding="utf-8"))
    ck.setdefault("metadata", {})["run_id"] = RUN
    (d / "checklist.json").write_text(json.dumps(ck), encoding="utf-8")
    return d


def test_an_earlier_runs_review_does_not_pass_a_set_with_one_artifact_left_from_it(tmp_path: Path) -> None:
    """One required artifact still carrying run 1's id must not let run 1's review stand in for run 2's,
    while the report shows no review and says none ran."""
    d = _second_run_with_a_stale_checklist(tmp_path)
    _refused(d, _compose_run(d), other_review=RUN)


def test_an_earlier_runs_stub_does_not_pass_the_gate(tmp_path: Path) -> None:
    """A stub (a step deliberately skipped) is no artifact: its run id must not satisfy the gate. Before
    this, a stale stub let an earlier review through with no high warning, so --strict passed too."""
    d = _second_run_with_a_stale_checklist(tmp_path, {"skipped": True, "reason": "not run"})
    r = _compose_run(d)
    _refused(d, r, other_review=RUN)
    assert "more than one run id" not in r.stdout, "a stub's id was counted as a run's"
    strict = subprocess.run(
        [sys.executable, str(SCRIPTS / "compose_report.py"), "--dir", str(d), "--strict"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert strict.returncode == 1


def test_a_mixed_set_reviewed_for_its_own_run_still_reaches_stale_artifact(tmp_path: Path) -> None:
    """Control: when the review IS the run's, the gate passes and STALE_ARTIFACT names the leftover."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    ck = json.loads((d / "checklist.json").read_text(encoding="utf-8"))
    ck["metadata"]["run_id"] = "an-earlier-run"
    (d / "checklist.json").write_text(json.dumps(ck), encoding="utf-8")
    r = _compose_run(d)
    assert r.returncode == 0, r.stdout[-600:]
    assert "STALE_ARTIFACT" in (d / "report.json").read_text(encoding="utf-8")


def test_the_review_shown_from_its_copy_satisfies_the_gate_after_redteam_json_is_deleted(tmp_path: Path) -> None:
    """The review is kept in an append-only copy that outlives a delete of redteam.json; the gate reads
    the shown review, so the run is not refused for a review it has."""
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": []}).returncode == 0
    (d / "redteam.json").unlink()
    r = _compose_run(d)
    assert r.returncode == 0, r.stdout[-600:]


def test_a_skip_record_off_the_closed_list_is_refused(tmp_path: Path) -> None:
    """A recorded reason must be one of the closed list; any other string is not a decision."""
    d = _analysis(tmp_path)
    (d / "red_team_skip.json").write_text(
        json.dumps({"reason": "felt_like_it", "_produced_by": "record_red_team_skip", "metadata": {"run_id": RUN}}),
        encoding="utf-8",
    )
    r = _compose_run(d)
    assert r.returncode == 1
    assert "'felt_like_it', which is not a recognised reason" in r.stdout
    assert not (d / "report.json").exists()


# --- what the founder reads ---------------------------------------------------------------------------------


def _pages(d: Path) -> tuple[str, str, dict[str, Any]]:
    r = _compose_run(d)
    assert r.returncode == 0, r.stderr[-600:]
    html_page = subprocess.run(
        [sys.executable, str(SCRIPTS / "visualize.py"), "--dir", str(d)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert html_page.returncode == 0, html_page.stderr[-600:]
    report = json.loads((d / "report.json").read_text(encoding="utf-8"))
    return (d / "report.md").read_text(encoding="utf-8"), html_page.stdout, report


def test_both_pages_show_the_review_as_written_even_after_redteam_json_is_edited(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert (
        _pipe(d, {"findings": [_finding(severity="high", claim_attacked="The patent covers routing")]}).returncode == 0
    )
    edited = json.loads((d / "redteam.json").read_text(encoding="utf-8"))
    edited["findings"] = [dict(edited["findings"][0], claim_attacked="Nothing to see")]
    (d / "redteam.json").write_text(json.dumps(edited), encoding="utf-8")
    md, page, _ = _pages(d)
    for text in (md, page):
        assert "What an Outside Review Found" in text
        assert "Serious: The patent covers routing" in text
        assert "Nothing to see" not in text


def test_the_three_states_read_differently(tmp_path: Path) -> None:
    """Never ran, ran and found nothing, found something: "no findings" and "nobody looked" are
    opposite facts, and a founder must be able to tell them apart."""
    ran_empty = _analysis(tmp_path / "a")
    assert _pipe(ran_empty, {"findings": []}).returncode == 0
    found = _analysis(tmp_path / "b")
    assert _pipe(found, {"findings": [_finding()]}).returncode == 0
    skipped = _analysis(tmp_path / "c")
    _skip(skipped, RUN)
    texts = [_pages(d)[0] for d in (ran_empty, found, skipped)]
    assert "found nothing it could evidence" in texts[0]
    assert "raised 1 challenge" in texts[1]
    assert "was attempted and did not complete" in texts[2]


def test_the_reviewers_text_is_inert_on_both_pages_and_its_quote_verbatim(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    hostile = _finding(
        claim_attacked="<img src=x onerror=alert(1)> [click](javascript:alert(1))",
        what_is_true="**bold** <script>x</script>",
        evidence_quote="The switching_costs rating quoted as it stands in the source text",
        source_title="Title <b>x</b>",
    )
    assert _pipe(d, {"findings": [hostile]}).returncode == 0
    md, page, _ = _pages(d)
    assert "<img src=x" not in page and "<script>x</script>" not in page and "<b>x</b>" not in page
    assert "&lt;img src=x" in page
    assert "<img src=x" not in md.replace("\\<", "&lt;")  # made inert for a viewer rendering inline HTML
    assert "The switching_costs rating quoted as it stands in the source text" in md  # a quote is never reworded


def test_the_verdict_carries_a_serious_challenge_and_a_skipped_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's sentence ends the verdict -- and so the hand-over -- when it raised a serious
    challenge or did not run; a review of minor points stays in the report. (The map sentence is stubbed:
    what is under test is the review's part of the paragraph.)"""
    view = _load("_cp_view")
    monkeypatch.setattr(view, "map_sentences", lambda *_a, **_k: ["You rank first."])

    def verdict(redteam: Any, skip: str | None) -> str:
        text: str = view.verdict({"views": []}, None, None, None, redteam, skip)
        return text

    serious = {"findings": [_finding(severity="high")], "summary": {"rejected": 0}}
    minor = {"findings": [_finding(severity="low")], "summary": {"rejected": 0}}
    assert verdict(serious, None).endswith("Read them before relying on the positions above.")
    assert verdict(minor, None) == "You rank first."
    assert verdict(None, "dispatch_failed").endswith(view.SKIP_SENTENCES["dispatch_failed"])
    assert verdict(None, None) == "You rank first."


def test_the_coach_is_handed_the_review_in_the_reports_words(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    findings = [
        _finding(severity="low", claim_attacked="minor one"),
        _finding(severity="high", claim_attacked="big one"),
    ]
    assert _pipe(d, {"findings": findings}).returncode == 0
    payload = _pages(d)[2]["coaching_payload"]["outside_review"]
    assert payload[0].startswith("An outside review raised 2 challenges")
    assert payload[1].startswith("Serious: big one") and payload[2].startswith("Minor: minor one")


def test_every_other_review_of_the_run_is_listed_on_both_pages(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    assert _pipe(d, {"findings": [_finding(claim_attacked="first look")]}).returncode == 0
    assert _pipe(d, {"findings": [_finding(claim_attacked="second look")]}).returncode == 0
    md, page, _ = _pages(d)
    for text in (md, page):
        assert "first look" in text and "second look" in text
        assert "Another review of this analysis (review 2)" in text


@pytest.mark.parametrize(
    ("raw", "worded"),
    [
        ("so the positioning_scores.json placement", "so the positioning map placement"),
        ("per the checklist.json grading", "per the quality checklist grading"),
        ("The moat_scores.json rating of Acme", "The moat ratings rating of Acme"),
        ("a landscape.json entry", "a competitor research entry"),
        ("its differentiation_claims list", "its differentiation claims list"),
        ("See moat_scores.json.", "See the moat ratings."),  # no article before it: the phrase keeps its own
        ("moat_scores.json disagrees.", "The moat ratings disagrees."),
    ],
)
def test_a_reviewers_own_article_is_not_doubled(raw: str, worded: str) -> None:
    """A reviewer writes "the <file>"; the replacement brings its own "the". Only one survives."""
    assert humanize_review_text(raw)[0] == worded


# --- our file names never need removing after the review ----------------------------------------------------


def _scored_with_our_file_names(d: Path) -> None:
    """The positioning scorer run for real over evidence naming our files, into the analysis dir."""
    from test_competitive_positioning import _make_valid_positioning_input

    payload = _make_valid_positioning_input(run_id=RUN)
    payload["views"][0]["points"][1]["x_evidence"] = "Per landscape.json and the product_profile.json pricing."
    payload["differentiation_claims"][0]["evidence"] = "As product_profile.json states."
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "score_positioning.py"),
            "--run-id",
            RUN,
            "-o",
            str(d / "positioning_scores.json"),
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def _file_token_warnings(report: dict[str, Any]) -> list[str]:
    return [
        w["message"]
        for w in report["warnings"]
        if w["code"] == "FOUNDER_TEXT_TOKEN"
        and ("landscape.json" in w["message"] or "product_profile.json" in w["message"])
    ]


def test_scored_evidence_naming_our_files_needs_no_edit_after_the_review(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    _scored_with_our_file_names(d)
    assert _pipe(d, {"findings": []}).returncode == 0
    report = _compose(d)
    assert not _file_token_warnings(report), _file_token_warnings(report)
    assert "ANALYSIS_CHANGED_AFTER_REVIEW" not in _codes(report)


def test_the_report_scan_would_see_those_names_if_a_scorer_let_them_through(tmp_path: Path) -> None:
    """Positive control: the same names written into the artifact directly (no scorer) are flagged, so
    the test above passes because the scorer reworded them, not because the scan is blind to them."""
    d = _analysis(tmp_path)
    _scored_with_our_file_names(d)
    scores = json.loads((d / "positioning_scores.json").read_text(encoding="utf-8"))
    scores["differentiation_claims"][0]["evidence"] = "As product_profile.json states."
    (d / "positioning_scores.json").write_text(json.dumps(scores), encoding="utf-8")
    assert _pipe(d, {"findings": []}).returncode == 0
    assert _file_token_warnings(_compose(d))


@pytest.mark.parametrize(
    ("raw", "worded"),
    [
        # A modifier before the name: the phrase loses its article and reads as a noun the modifier describes.
        (
            "does not appear anywhere in the analysis's checked differentiation_claims list",
            "does not appear anywhere in the analysis's checked differentiation claims list",
        ),
        # A possessive after the name: the phrase is a compact noun, never "…record's searches".
        (
            "because the startup_research.json's searches of company registries returned nothing",
            "because the public-record research's searches of company registries returned nothing",
        ),
        # Controls that must not move.
        ("See moat_scores.json.", "See the moat ratings."),
        ("moat_scores.json disagrees.", "The moat ratings disagrees."),
        ("so the positioning_scores.json placement", "so the positioning map placement"),
    ],
)
def test_a_modifier_or_possessive_gets_a_compact_phrase(raw: str, worded: str) -> None:
    assert humanize_review_text(raw)[0] == worded
