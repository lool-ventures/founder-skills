"""ic-sim's recorded gates, through the real scripts.

The mode and fund are asked in Step 1 and recorded before `fund_profile.py` builds the profile, which must be
the fund the founder chose. The decline question (Step 8.5) is owed only while this run's scores make a
Decline; compose refuses to write a Decline up until it is recorded, and a delivered simulation is never
built again. A held decline the scores no longer make is closed, and asked again if they make it again.
Every company name and figure here is invented.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402


def _load(name: str, path: Path | None = None) -> ModuleType:
    if path is None and name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, path or h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    if path is None:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load("_run_status")
fp = _load("_ic_fund_profile_gates", h.SKILLS / "ic-sim" / "scripts" / "fund_profile.py")
g = _load("_gates")

IC = h.SKILLS / "ic-sim" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ic-sim"
SKILL_MD = h.SKILLS / "ic-sim" / "SKILL.md"
DECLINE = "ic_decline_confirmation"


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "{}"
    data: dict[str, Any] = json.loads(line)
    return data


def _ok(proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _stamp(run_dir: Path, run_id: str) -> None:
    """Steps 2-8's files, each carrying this run's id."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for f in FIXTURES.iterdir():
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": run_id}
        _write(run_dir / f.name, data)


def _verdict(run_dir: Path, verdict: str, run_id: str | None = None) -> None:
    scores = json.loads((run_dir / "score_dimensions.json").read_text(encoding="utf-8"))
    scores["summary"]["verdict"] = verdict
    if run_id is not None:
        scores["metadata"]["run_id"] = run_id
    _write(run_dir / "score_dimensions.json", scores)


def _sim(tmp_path: Path, verdict: str | None = "pass", lines: str = "") -> tuple[Path, str, Path]:
    """A started, bound run whose mode and fund are recorded and whose Steps 2-8 files are written."""
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim", lines=lines)
    _stamp(run_dir, run_id)
    if verdict is not None:
        _verdict(run_dir, verdict)
    return root, run_id, run_dir


def _answer(root: Path, run_id: str, gate: str, option: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return h.record(root, run_id, "answer", "--gate", gate, "--answer-id", option, *extra)


def _open(root: Path, run_id: str, *gates: str) -> subprocess.CompletedProcess[str]:
    return h.record(root, run_id, "open", *[a for gate in gates for a in ("--gate", gate)])


def _entry(root: Path, run_id: str, key: str) -> dict[str, Any]:
    entry: dict[str, Any] = h.ledger(root, run_id)["gates"][key]
    return entry


def _compose(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return h.run(
        IC / "compose_report.py",
        "--dir",
        str(run_dir),
        "-o",
        str(run_dir / "report.json"),
        "--write-md",
        str(run_dir / "report.md"),
        *extra,
    )


def _profile(mode: str = "generic") -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / "fund_profile.json").read_text(encoding="utf-8"))
    for key in ("validation", "metadata"):
        body.pop(key, None)
    body["mode"] = mode
    if mode == "fund_specific":
        body["portfolio"] = [{"name": "Example Portfolio Co"}]
        body["sources"] = [{"title": "Example Fund site"}]
    return body


def _fund_profile(run_dir: Path, run_id: str, mode: str = "generic") -> subprocess.CompletedProcess[str]:
    return h.run(
        IC / "fund_profile.py",
        "--run-id",
        run_id,
        "-o",
        str(run_dir / "fund_profile.json"),
        stdin=json.dumps(_profile(mode)),
    )


def _complete(root: Path, run_id: str) -> None:
    rs.update(rs.run_paths(str(root), run_id), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))


# --- the decline question: owed by the scores ------------------------------------------------------------


def test_the_decline_is_asked_only_on_a_decline(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "more_diligence")
    assert _open(root, run_id, DECLINE).returncode == 11
    _verdict(run_dir, "hard_pass")
    out = _out(_ok(_open(root, run_id, DECLINE)))
    labels = [o["label"] for o in out["needs_input"][0]["options"]]
    assert labels == ["Yes, finish the write-up", "Hold off — let me add more context first"]


def test_no_scores_yet_means_not_owed(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    (run_dir / "score_dimensions.json").unlink()
    assert _open(root, run_id, DECLINE).returncode == 11


@pytest.mark.parametrize("broken", ["another_run", "unreadable"])
def test_scores_that_cannot_decide_it_are_refused_loudly_and_never_read_as_not_owed(
    tmp_path: Path, broken: str
) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    if broken == "another_run":
        _verdict(run_dir, "more_diligence", run_id="20260101T000000Z-aaaaaa")
    else:
        (run_dir / "score_dimensions.json").write_text("{not json", encoding="utf-8")
    before = h.snapshot(root, run_id)
    proc = _open(root, run_id, DECLINE)
    assert proc.returncode == 2 and _out(proc)["code"] == "GATE_UNDECIDABLE", proc.stdout + proc.stderr
    assert h.snapshot(root, run_id) == before


def test_a_held_decline_is_kept_open_while_the_scores_cannot_be_read(tmp_path: Path) -> None:
    """The settle pass skips a predicate that cannot decide: a hold-off is never closed on another run's file."""
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "hold_off"))
    _verdict(run_dir, "more_diligence", run_id="20260101T000000Z-aaaaaa")
    h.run(h.RUN_STATUS, "show", "--run-id", run_id, "--artifacts-root", str(root))
    _ok(_answer(root, run_id, "ic_mode", "auto_pilot"))  # any write: the pass runs around it
    assert _entry(root, run_id, DECLINE)["state"] == "open"


def test_a_hold_off_the_new_scores_no_longer_owe_is_closed_and_compose_writes(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "hold_off"))
    assert h.status(root, run_id)["code"] == "GATE_INTERMEDIATE"
    _verdict(run_dir, "more_diligence")  # new context, Steps 5-8 again
    assert _open(root, run_id, DECLINE).returncode == 11
    assert _entry(root, run_id, DECLINE)["state"] == "not_owed"
    assert h.status(root, run_id)["status"] == "running"
    _ok(_compose(run_dir))
    # A later re-score that is a Decline again asks again: the closure is never read as an answer.
    _verdict(run_dir, "pass")
    assert len(_out(_ok(_open(root, run_id, DECLINE)))["needs_input"]) == 1
    assert h.status(root, run_id)["waiting_on"] == DECLINE


def test_a_request_finish_is_applied_on_a_decline_and_never_on_another_verdict(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "invest", lines="FS_HOST_ANSWER ic_decline_confirmation=finish")
    assert _open(root, run_id, DECLINE).returncode == 11
    _ok(_compose(run_dir))
    root2, run_id2, run_dir2 = _sim(tmp_path / "b", "pass", lines="FS_HOST_ANSWER ic_decline_confirmation=finish")
    assert _out(_ok(_open(root2, run_id2, DECLINE))).get("applied") == "pre_answer"
    assert _entry(root2, run_id2, DECLINE)["current"]["asked_evidence"] == "host_line"


def test_hold_off_cannot_be_sent_ahead(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    proc = h.start(root, "ic-sim", "FS_HOST_ANSWER ic_decline_confirmation=hold_off")
    assert proc.returncode == 1 and _out(proc)["code"] == "PRE_ANSWER_INVALID"


def test_a_host_resume_after_hold_off_finishes(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "hold_off"))
    lines = f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ic_decline_confirmation=finish\n"
    resumed = json.loads(_ok(h.start(root, "ic-sim", lines)).stdout)
    assert (resumed["resume"], resumed["resume_step"]) == (1, "8.5")
    _ok(h.bind(root, run_id, run_dir, "example-co"))
    assert _out(_ok(_open(root, run_id, DECLINE))).get("applied") == "pre_answer"
    assert _entry(root, run_id, DECLINE)["current"]["answer_id"] == "finish"
    _ok(_compose(run_dir))


def test_a_held_answer_recorded_before_the_question_can_be_replaced_once(tmp_path: Path) -> None:
    """The coaching dispatch held because `finish` was recorded unasked; the founder says hold off."""
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "finish"))
    plain = _answer(root, run_id, DECLINE, "hold_off")
    assert plain.returncode == 1 and "--after-hold" in plain.stderr
    _ok(_answer(root, run_id, DECLINE, "hold_off", "--after-hold"))
    assert h.status(root, run_id)["code"] == "GATE_INTERMEDIATE"
    _ok(_answer(root, run_id, DECLINE, "finish"))
    assert h.status(root, run_id)["status"] == "running"


# --- compose ---------------------------------------------------------------------------------------------


def test_compose_waits_for_the_decline_and_writes_nothing(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == DECLINE
    assert not (run_dir / "report.md").exists() and not (run_dir / "report.json").exists()


def test_compose_refuses_a_profile_naming_people_and_records_the_code(tmp_path: Path) -> None:
    """A profile written before partners became role names: compose refuses before writing, and the run's
    compose_result.json carries the code the skill routes on. The invented person is in no stream."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    profile = json.loads((run_dir / "fund_profile.json").read_text(encoding="utf-8"))
    profile["mode"] = "fund_specific"
    profile["archetypes"][0].update(name="Dana Whitlock", background="Invented partner bio")
    _write(run_dir / "fund_profile.json", profile)
    proc = _compose(run_dir)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not (run_dir / "report.md").exists() and not (run_dir / "report.json").exists()
    record = json.loads((run_dir / "compose_result.json").read_text(encoding="utf-8"))
    assert record["code"] == "FUND_PROFILE_NAMES_PEOPLE"
    for text in (proc.stdout, proc.stderr, json.dumps(record)):
        assert "Dana Whitlock" not in text and "Invented partner bio" not in text


def _old_profile(run_dir: Path) -> None:
    profile = json.loads((run_dir / "fund_profile.json").read_text(encoding="utf-8"))
    profile["mode"] = "fund_specific"
    profile["archetypes"][0].update(name="Dana Whitlock", background="Invented partner bio")
    _write(run_dir / "fund_profile.json", profile)


def test_the_profile_refusal_comes_after_the_run_gates(tmp_path: Path) -> None:
    """A finished run reports RUN_FINISHED (it cannot rebuild a profile), and an open decline question is
    asked first: the profile refusal is placed after both."""
    root, run_id, run_dir = _sim(tmp_path, "pass")
    _old_profile(run_dir)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and "FUND_PROFILE_NAMES_PEOPLE" not in proc.stdout
    root2, run_id2, run_dir2 = _sim(tmp_path / "b", "invest")
    rs.update(rs.run_paths(str(root2), run_id2), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    _old_profile(run_dir2)
    proc = _compose(run_dir2)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
    assert "FUND_PROFILE_NAMES_PEOPLE" not in proc.stdout + proc.stderr


def _record_specific_fund(root: Path, run_id: str) -> None:
    _ok(_answer(root, run_id, "ic_mode", "interactive"))
    _ok(_answer(root, run_id, "ic_fund_mode", "specific", "--value", "Northwind Ventures"))


PARTNERS = [
    (kind, archetype) for kind in ("assessment", "rebuttal") for archetype in ("visionary", "operator", "analyst")
]


def _handoff(run_dir: Path, name: str, tag: str) -> str:
    """A sub-agent's hand-off for this round: the file's content without what the scripts stamp, with one
    invented diligence item naming the round, so each dispatch round is new content (as a real re-dispatch
    is)."""
    body = json.loads((run_dir / name).read_text(encoding="utf-8"))
    body = {k: v for k, v in body.items() if k not in ("metadata", "graded_against")}
    body["diligence_requirements"] = [*body.get("diligence_requirements", []), f"Invented check for round {tag}."]
    return json.dumps(body)


def _persist(run_dir: Path, run_id: str, kind: str, archetype: str, text: str) -> subprocess.CompletedProcess[str]:
    out = run_dir / f"partner_{kind}_{archetype}.json"
    return h.run(
        IC / "persist_partner.py",
        "--kind",
        kind,
        "--archetype",
        archetype,
        "--run-id",
        run_id,
        "-o",
        str(out),
        stdin=text,
    )


def _persist_partners(run_dir: Path, run_id: str, tag: str = "redo") -> dict[str, str]:
    """Steps 6 and 6b again: a new hand-off per archetype and kind, persisted; returns the hand-offs sent."""
    sent: dict[str, str] = {}
    for kind, archetype in PARTNERS:
        text = _handoff(run_dir, f"partner_{kind}_{archetype}.json", tag)
        _ok(_persist(run_dir, run_id, kind, archetype, text))
        sent[f"{kind}:{archetype}"] = text
    return sent


def _score_handoff(run_dir: Path, tag: str) -> str:
    scores = json.loads((run_dir / "score_dimensions.json").read_text(encoding="utf-8"))
    items = [dict(i) for i in scores["items"]]
    items[0]["evidence"] = f"{items[0].get('evidence') or 'Invented evidence'} (round {tag})"
    return json.dumps({"items": items})


def _score(run_dir: Path, run_id: str, mode: str, text: str) -> subprocess.CompletedProcess[str]:
    return h.run(
        IC / "score_dimensions.py",
        "--run-id",
        run_id,
        "--fund-mode",
        mode,
        "-o",
        str(run_dir / "score_dimensions.json"),
        stdin=text,
    )


def _redo_steps_7_to_8(run_dir: Path, run_id: str, mode: str, tag: str = "redo") -> subprocess.CompletedProcess[str]:
    """Step 7 then Step 8 (a new scoring hand-off); returns compose_discussion's result (Step 8 runs only if it
    passed)."""
    proc = h.run(
        IC / "compose_discussion.py", "--dir", str(run_dir), "--run-id", run_id, "-o", str(run_dir / "discussion.json")
    )
    if proc.returncode != 0:
        return proc
    _ok(_score(run_dir, run_id, mode, _score_handoff(run_dir, tag)))
    return proc


def _redo_steps_5_to_8(run_dir: Path, run_id: str, mode: str) -> None:
    """Steps 5-8 again under the same run id, over the content already in the dir (the Step 6/6b sub-agents'
    output is the fixture's; a real redo re-dispatches them and persists their hand-offs)."""
    conflict = json.loads((run_dir / "conflict_check.json").read_text(encoding="utf-8"))
    _ok(
        h.run(
            IC / "detect_conflicts.py",
            "--run-id",
            run_id,
            "-o",
            str(run_dir / "conflict_check.json"),
            stdin=json.dumps({"portfolio_size": conflict["portfolio_size"], "conflicts": conflict["conflicts"]}),
        )
    )
    _persist_partners(run_dir, run_id)
    _ok(_redo_steps_7_to_8(run_dir, run_id, mode))


def test_rebuilding_only_the_profile_does_not_compose_and_a_full_redo_does(tmp_path: Path) -> None:
    """A waiting run resumed with a profile that names people: compose refuses it; rebuilding Step 4 alone
    is refused as stale (every artifact keeps the run's id, so only the stamps can tell); Steps 5-8 again
    under the same run id compose."""
    root, run_id, run_dir = _sim(tmp_path, "hard_pass")
    _record_specific_fund(root, run_id)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "hold_off"))
    _old_profile(run_dir)
    _ok(_answer(root, run_id, DECLINE, "finish"))
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "FUND_PROFILE_NAMES_PEOPLE"
    record_after = json.loads((run_dir / "compose_result.json").read_text(encoding="utf-8"))
    assert record_after["code"] == "FUND_PROFILE_NAMES_PEOPLE"
    # Step 4 only.
    proc = _fund_profile(run_dir, run_id, "fund_specific")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _compose(run_dir)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc)["code"] == "PARTNER_ARTIFACTS_STALE"
    for name in ("conflict_check.json", "discussion.json", "score_dimensions.json"):
        assert name in _out(proc)["message"]
    assert not (run_dir / "report.md").exists() and not (run_dir / "report.json").exists()
    record = json.loads((run_dir / "compose_result.json").read_text(encoding="utf-8"))
    assert record["code"] == "PARTNER_ARTIFACTS_STALE"
    assert "partner_assessment_visionary.json" in _out(proc)["message"]
    # Steps 7-8 only: the partner files were written against the old profile.
    proc = _redo_steps_7_to_8(run_dir, run_id, "fund_specific")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc)["code"] == "PARTNER_ARTIFACTS_STALE" and "PARTNER_ARTIFACTS_STALE" in proc.stderr
    assert "partner_rebuttal_analyst.json" in _out(proc)["message"]
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "PARTNER_ARTIFACTS_STALE"
    # Steps 5-8 again.
    _redo_steps_5_to_8(run_dir, run_id, "fund_specific")
    proc = _compose(run_dir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "- **The Visionary**" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_each_producer_stamps_the_profile_it_was_built_from(tmp_path: Path) -> None:
    """Redoing all but one step leaves that step's artifact stale: each producer's stamp is load-bearing."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    _record_specific_fund(root, run_id)
    _ok(_fund_profile(run_dir, run_id, "fund_specific"))
    _redo_steps_5_to_8(run_dir, run_id, "fund_specific")
    _ok(_compose(run_dir))
    for name in fp.PROFILE_DEPENDENTS:
        data = json.loads((run_dir / name).read_text(encoding="utf-8"))
        assert len(data["graded_against"]["fund_profile"]) == 64, name


def test_re_piping_the_old_handoffs_after_a_rebuild_is_refused(tmp_path: Path) -> None:
    """The partner work and scores were persisted from these hand-offs under one profile; the profile is rebuilt;
    piping the SAME hand-offs through again would re-stamp prose written against the old profile, so it is
    refused (nothing written) until the step is dispatched again, and a new hand-off is accepted."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    _record_specific_fund(root, run_id)
    _ok(_fund_profile(run_dir, run_id, "fund_specific"))
    old = _persist_partners(run_dir, run_id, "old")
    old_score = _score_handoff(run_dir, "old")
    _ok(
        h.run(
            IC / "compose_discussion.py",
            "--dir",
            str(run_dir),
            "--run-id",
            run_id,
            "-o",
            str(run_dir / "discussion.json"),
        )
    )
    _ok(_score(run_dir, run_id, "fund_specific", old_score))
    # Rebuild Step 4 with different content.
    body = _profile("fund_specific")
    body["thesis_areas"] = ["Climate software"]
    _ok(
        h.run(
            IC / "fund_profile.py", "--run-id", run_id, "-o", str(run_dir / "fund_profile.json"), stdin=json.dumps(body)
        )
    )
    # Re-pipe the old hand-offs: refused, file untouched.
    target = run_dir / "partner_assessment_visionary.json"
    before = target.read_bytes()
    proc = _persist(run_dir, run_id, "assessment", "visionary", old["assessment:visionary"])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc)["code"] == "HANDOFF_NOT_REDISPATCHED" and "HANDOFF_NOT_REDISPATCHED" in proc.stderr
    assert target.read_bytes() == before
    scores_before = (run_dir / "score_dimensions.json").read_bytes()
    proc = _score(run_dir, run_id, "fund_specific", old_score)
    assert proc.returncode == 1 and _out(proc)["code"] == "HANDOFF_NOT_REDISPATCHED"
    assert (run_dir / "score_dimensions.json").read_bytes() == scores_before
    # A new round: accepted, and the run composes.
    conflict = json.loads((run_dir / "conflict_check.json").read_text(encoding="utf-8"))
    _ok(
        h.run(
            IC / "detect_conflicts.py",
            "--run-id",
            run_id,
            "-o",
            str(run_dir / "conflict_check.json"),
            stdin=json.dumps({"portfolio_size": conflict["portfolio_size"], "conflicts": conflict["conflicts"]}),
        )
    )
    _persist_partners(run_dir, run_id, "new")
    _ok(_redo_steps_7_to_8(run_dir, run_id, "fund_specific", "new"))
    _ok(_compose(run_dir))


def test_a_repair_under_the_same_profile_is_never_refused(tmp_path: Path) -> None:
    """The same hand-off persisted twice with the profile unchanged (a repeated command) is accepted."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    text = _handoff(run_dir, "partner_assessment_operator.json", "same")
    _ok(_persist(run_dir, run_id, "assessment", "operator", text))
    _ok(_persist(run_dir, run_id, "assessment", "operator", text))


def test_the_generic_path_is_held_to_the_same_stamps(tmp_path: Path) -> None:
    """Generic mode: the conflict check is the stub, and a rebuilt profile still needs Steps 5-8 again."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    profile = json.loads((run_dir / "fund_profile.json").read_text(encoding="utf-8"))
    profile["thesis_areas"] = ["Climate software"]
    _write(run_dir / "fund_profile.json", profile)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "PARTNER_ARTIFACTS_STALE"
    _ok(
        h.run(
            IC / "detect_conflicts.py", "--generic-stub", "--run-id", run_id, "-o", str(run_dir / "conflict_check.json")
        )
    )
    _persist_partners(run_dir, run_id)
    _ok(_redo_steps_7_to_8(run_dir, run_id, "generic"))
    _ok(_compose(run_dir))


def test_accepting_a_warning_stales_nothing(tmp_path: Path) -> None:
    """accepted_warnings live in the fund profile and are added after compose warns; they are not what any
    earlier step was built from."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    profile = json.loads((run_dir / "fund_profile.json").read_text(encoding="utf-8"))
    profile["accepted_warnings"] = [{"code": "SEQUENTIAL_FALLBACK", "match": "x", "reason": "invented"}]
    _write(run_dir / "fund_profile.json", profile)
    _ok(_compose(run_dir))


def test_compose_after_hold_off_says_to_wait_not_to_ask(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "hold_off"))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and "wait for the founder" in proc.stderr
    assert not (run_dir / "report.md").exists()


def test_compose_writes_after_finish_and_marks_coaching_pending(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    _ok(_open(root, run_id, DECLINE))
    _ok(_answer(root, run_id, DECLINE, "finish"))
    _ok(_compose(run_dir))
    assert h.status(root, run_id)["coaching"] == "pending"
    # A re-score after the answer: asked again (the scores it confirmed changed).
    scores = json.loads((run_dir / "score_dimensions.json").read_text(encoding="utf-8"))
    scores["items"][0]["evidence"] = "A different reading of the same materials."
    _write(run_dir / "score_dimensions.json", scores)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and "changed since" in proc.stderr


def test_compose_writes_a_non_decline_without_asking(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "invest")
    _ok(_compose(run_dir))
    assert (run_dir / "report.md").exists()


@pytest.mark.parametrize("verdict", ["pass", "invest"])
def test_a_delivered_simulation_is_never_built_again(tmp_path: Path, verdict: str) -> None:
    root, run_id, run_dir = _sim(tmp_path, verdict)
    if verdict == "pass":
        _ok(_open(root, run_id, DECLINE))
        _ok(_answer(root, run_id, DECLINE, "finish"))
    _ok(_compose(run_dir))
    _complete(root, run_id)
    before = h.snapshot(root, run_id)
    report = (run_dir / "report.md").read_bytes()
    profile = (run_dir / "fund_profile.json").read_bytes()
    for proc in (_fund_profile(run_dir, run_id), _compose(run_dir)):
        assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED", proc.stdout + proc.stderr
        assert "new simulation" in _out(proc)["message"]
        assert h.snapshot(root, run_id) == before
    assert (run_dir / "report.md").read_bytes() == report
    assert (run_dir / "fund_profile.json").read_bytes() == profile
    opened = _open(root, run_id, DECLINE)
    assert opened.returncode == 1 and _out(opened)["code"] == "RUN_FINISHED"


def test_compose_refuses_a_question_opened_and_never_recorded(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "invest")
    _ok(_open(root, run_id, "ctx_stage_detail"))
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNRESOLVED"
    assert not (run_dir / "report.md").exists()


def test_an_unfilled_profile_id_does_not_take_compose_off_the_ledger(tmp_path: Path) -> None:
    """A placeholder id is not this run's: in a folder that belongs to a run it is refused by name (it no longer
    reaches the gates at all), and the report is never composed from it."""
    root, run_id, run_dir = _sim(tmp_path)
    profile = json.loads((run_dir / "startup_profile.json").read_text(encoding="utf-8"))
    profile["metadata"]["run_id"] = "<RUN_ID>"
    _write(run_dir / "startup_profile.json", profile)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "ARTIFACT_OTHER_RUN"
    assert _out(proc)["files"] == [{"file": "startup_profile.json", "run_id": "<RUN_ID>"}]
    assert not (run_dir / "report.md").exists()


def test_files_that_do_not_agree_on_a_run_are_refused_in_a_runs_dir(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "invest")
    for i, name in enumerate(("startup_profile.json", "fund_profile.json", "conflict_check.json", "discussion.json")):
        data = json.loads((run_dir / name).read_text(encoding="utf-8"))
        data["metadata"]["run_id"] = f"20260101T00000{i}Z-aaaaaa"
        _write(run_dir / name, data)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "ARTIFACT_OTHER_RUN"
    named = {f["file"] for f in _out(proc)["files"]}
    assert named == {"startup_profile.json", "fund_profile.json", "conflict_check.json", "discussion.json"}
    assert not (run_dir / "report.md").exists()


def test_the_page_and_compose_read_one_run_id(tmp_path: Path) -> None:
    """visualize.py stamps the page with the id compose's checks read, not the profile's alone."""
    root, run_id, run_dir = _sim(tmp_path, "invest")
    _ok(_compose(run_dir))
    profile = json.loads((run_dir / "startup_profile.json").read_text(encoding="utf-8"))
    profile["metadata"]["run_id"] = "<RUN_ID>"
    _write(run_dir / "startup_profile.json", profile)
    page = run_dir / "report.html"
    _ok(h.run(IC / "visualize.py", "--dir", str(run_dir), "--run-id", run_id, "-o", str(page)))
    assert f'content="{run_id}"' in page.read_text(encoding="utf-8")
    viz = _load("ic_viz_pin", IC / "visualize.py")
    gates = _load("_ic_gates_pin", IC / "_ic_gates.py")
    assert viz._own_run_id(str(run_dir)) == gates.run_id_of(str(run_dir)) == run_id


# --- fund_profile.py -------------------------------------------------------------------------------------


def test_the_profile_waits_for_the_mode_and_the_fund(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    (run_dir / "fund_profile.json").unlink()
    proc = _fund_profile(run_dir, run_id)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ic_mode"
    assert not (run_dir / "fund_profile.json").exists()
    _ok(_answer(root, run_id, "ic_mode", "auto_pilot"))
    assert _out(_fund_profile(run_dir, run_id))["blocked_by_gate"] == "ic_fund_mode"
    _ok(_answer(root, run_id, "ic_fund_mode", "generic"))
    _ok(_fund_profile(run_dir, run_id))
    assert json.loads((run_dir / "fund_profile.json").read_text(encoding="utf-8"))["mode"] == "generic"


@pytest.mark.parametrize(
    ("answer", "value", "wrong"), [("generic", None, "fund_specific"), ("specific", "Example Partners", "generic")]
)
def test_the_profile_must_be_the_fund_the_founder_chose(
    tmp_path: Path, answer: str, value: str | None, wrong: str
) -> None:
    root, run_id, run_dir = _sim(tmp_path)
    (run_dir / "fund_profile.json").unlink()
    _ok(_answer(root, run_id, "ic_mode", "interactive"))
    _ok(_answer(root, run_id, "ic_fund_mode", answer, *(("--value", value) if value else ())))
    proc = _fund_profile(run_dir, run_id, wrong)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert "new simulation" in _out(proc)["message"]
    assert not (run_dir / "fund_profile.json").exists()
    _ok(_fund_profile(run_dir, run_id, "generic" if answer == "generic" else "fund_specific"))


def test_a_profile_written_outside_a_run_is_unchanged(tmp_path: Path) -> None:
    d = tmp_path / "plain"
    d.mkdir()
    _ok(_fund_profile(d, "20261007T090000Z-5e7f91"))
    assert json.loads((d / "fund_profile.json").read_text(encoding="utf-8"))["mode"] == "generic"


# --- the skill-local copies ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["refuse_open_gates", "coaching_pending"])
def test_the_compose_helpers_are_market_sizings_word_for_word(name: str) -> None:
    ic = _load("_ic_gates_pin2", IC / "_ic_gates.py")
    ms = _load("_ms_gates_pin2", h.SKILLS / "market-sizing" / "scripts" / "_ms_gates.py")
    assert inspect.getsource(getattr(ic, name)) == inspect.getsource(getattr(ms, name))


def test_the_registry_decides_the_decline_as_the_hook_does() -> None:
    hook = _load("agc_pin", h.SHARED / "asked_gate_check.py")
    assert tuple(g.IC_DECLINES) == tuple(hook.DECLINES)


# --- SKILL.md --------------------------------------------------------------------------------------------


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    text = _text()
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def test_the_catalog_sections_are_out_and_their_notes_head_the_references() -> None:
    text = _text()
    for heading in ("## Skill Metadata", "## Available Scripts", "## Available References"):
        assert heading not in text
    refs = h.SKILLS / "ic-sim" / "references"
    for name, phrase in (
        ("partner-archetypes.md", "no workflow step reads this file"),
        ("evaluation-criteria.md", "no workflow step reads this file"),
        ("ic-dynamics.md", "a normal run does not read it"),
    ):
        head = (refs / name).read_text(encoding="utf-8").split("\n## ", 1)[0]
        assert phrase in head, name


def test_step_1_opens_its_questions_before_it_asks_and_asks_a_stage_it_cannot_derive() -> None:
    step1 = _section("### Step 1:", "#### Execution checkpoint")
    for case in (
        "**Exit 0 (found):** Open the questions (the block below) first",
        "Open the questions (the block below) first. Do NOT mention this check",
    ):
        assert case in step1
    assert "--gate ic_mode --gate ic_fund_mode" in step1
    assert '--run-id "$RUN_ID" --skill ic-sim' in step1
    assert "the mode and fund first" in step1
    # A stage has no "not sure" option: under Auto-pilot too, a stage with no signal is asked.
    assert "a stage with no signal is asked, under Auto-pilot too" in step1
    assert "mark any field but the stage that still has no signal" in step1
    assert "**Exit 10 (which company):**" in step1 and "Exit 2" not in step1
    assert not any("not_sure" in s and "stage" in s.split("not_sure")[0][-40:] for s in step1.split(". "))


def test_the_mode_selection_asks_the_registrys_questions() -> None:
    mode = _section("### Mode Selection", "### Steps 2-3")
    assert g.GATES["ic_mode"]["question"] in mode and g.GATES["ic_fund_mode"]["question"] in mode
    assert "Pause between partner positions" not in _text()
    assert "neither pauses between partners or skips Step 8.5" in mode


def test_step_8_5_opens_the_question_and_names_every_exit() -> None:
    gate = _section("### Step 8.5:", "### Step 9:")
    assert gate.index("--gate ic_decline_confirmation") < gate.index("**Step A")
    assert "python3 -c" not in gate
    for phrase in (
        "Exit 11 (not owed",
        '`"applied": "pre_answer"`',
        "`RUN_FINISHED`: this simulation was already delivered",
        "Record the reply with the printed `answer_command`",
        "do not send or name the report",
        "record `finish`, then Step 9",
        "New context while it waits",
    ):
        assert phrase in gate, phrase


def test_the_later_steps_carry_the_run() -> None:
    text = _text()
    step9 = _section("### Step 9:", "### Step 10:")
    assert "Exit 10 is a question" in step9 and "never re-run compose without the answer" in step9
    assert "`RUN_FINISHED`" in step9
    assert 'visualize.py" --dir "$SIM_DIR" --run-id "$RUN_ID"' in text
    step12 = _section("### Step 12:", "## Main-Thread Return")
    assert step12.index('deliverables --run-id "$RUN_ID"') < step12.index("**Send the finished work")
    assert "--final || :" in step12
    assert "`-o` under `$STAGING_DIR`" in _section("## What-If Recomputation Rule", "## Cross-Agent Integration")
    resume = _section("**A resumed run**", "Pass `RUN_ID`")
    assert "`8.5`" in resume and "unless the founder brings new context at 8.5" in resume


def test_the_hold_off_turn_asks_for_no_delivery() -> None:
    """Stop hook: a turn that built the report, was held at the coaching dispatch and recorded the founder's
    hold-off asks for no attachment unless the model names the report; and a turn whose first plain answer was
    refused (a failed shell call after the build) is never asked."""
    dc = _load("dc_pin", h.SHARED / "_delivery_check.py")

    def use(i: str, cmd: str) -> dict[str, Any]:
        return {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}]},
        }

    def res(i: str, err: bool = False) -> dict[str, Any]:
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "is_error": err}]}}

    def say(text: str) -> dict[str, Any]:
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    tools = {
        "type": "attachment",
        "attachment": {"type": "deferred_tools_delta", "addedNames": ["mcp__cowork__present_files"]},
    }
    built = [tools, use("c", 'python3 "$SCRIPTS/compose_report.py" --dir d'), res("c")]
    after = [
        use(
            "a",
            'python3 "$SHARED/record_gate_answer.py" answer --gate ic_decline_confirmation '
            "--answer-id hold_off --after-hold",
        ),
        res("a"),
    ]
    quiet = say("Pausing here until you are ready.")
    named = say("Pausing here; the draft is at /work/outputs/report.md")
    assert dc.missing_delivery([*built, *after, quiet], 0) is None
    assert dc.missing_delivery([*built, *after, named], 0) is not None, "control: naming the report is asked about"
    refused = [
        use("p", "python3 record_gate_answer.py answer --gate ic_decline_confirmation --answer-id hold_off"),
        res("p", True),
    ]
    assert dc.missing_delivery([*built, *refused, *after, named], 0) is None
