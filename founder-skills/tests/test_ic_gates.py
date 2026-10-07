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
    root, run_id, run_dir = _sim(tmp_path)
    profile = json.loads((run_dir / "startup_profile.json").read_text(encoding="utf-8"))
    profile["metadata"]["run_id"] = "<RUN_ID>"
    _write(run_dir / "startup_profile.json", profile)
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == DECLINE


def test_files_that_do_not_agree_on_a_run_are_refused_in_a_runs_dir(tmp_path: Path) -> None:
    root, run_id, run_dir = _sim(tmp_path, "invest")
    for i, name in enumerate(("startup_profile.json", "fund_profile.json", "conflict_check.json", "discussion.json")):
        data = json.loads((run_dir / name).read_text(encoding="utf-8"))
        data["metadata"]["run_id"] = f"20260101T00000{i}Z-aaaaaa"
        _write(run_dir / name, data)
    proc = _compose(run_dir)
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED"
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
        ("partner-archetypes.md", "fund-specific mode only"),
        ("evaluation-criteria.md", "no workflow step reads this file"),
        ("ic-dynamics.md", "a normal run does not read it"),
    ):
        head = (refs / name).read_text(encoding="utf-8").split("\n## ", 1)[0]
        assert phrase in head, name


def test_step_1_opens_its_questions_before_it_asks_and_asks_a_stage_it_cannot_derive() -> None:
    step1 = _section("### Step 1:", "#### Execution checkpoint")
    for case in (
        "**Exit 0 (found):** Open the questions (the block below) first",
        "Open the questions (the block below) first. Expected",
    ):
        assert case in step1
    assert "--gate ic_mode --gate ic_fund_mode" in step1
    assert '--run-id "$RUN_ID" --skill ic-sim' in step1
    assert "the mode and fund first" in step1
    # A stage has no "not sure" option: under Auto-pilot too, a stage with no signal is asked.
    assert "a stage with no signal is asked, under Auto-pilot too" in step1
    assert "mark any field but the stage that still has no signal" in step1
    assert "**Exit 10 (several companies):**" in step1 and "Exit 2" not in step1
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
