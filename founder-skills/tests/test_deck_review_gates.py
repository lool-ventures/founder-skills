"""deck-review with a gate ledger: every stage-question path settles, refusals carry codes, and the run
status says what a host needs.

Driven through the real scripts (`run_status.py start` and `bind`, `gate_state.py`, `setup_run.py`,
`compose_report.py`, `record_gate_answer.py`, `founder_context.py`) on the synthetic fixture artifacts.
Ids and names are synthetic; figures come from the committed fixtures only.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402

SCRIPTS = h.SKILLS / "deck-review" / "scripts"
GATE_STATE = SCRIPTS / "gate_state.py"
SETUP_RUN = SCRIPTS / "setup_run.py"
COMPOSE = SCRIPTS / "compose_report.py"
STAGE_PROFILE = SCRIPTS / "stage_profile.py"
FOUNDER_CONTEXT = h.SHARED / "founder_context.py"
FIXTURES = h.REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "deck-review"
RID = "fixture-deck-review-001"  # the fixture artifacts' own run id, so they compose as this run's

sys.path.insert(0, str(SCRIPTS))
import gate_state  # type: ignore[import-not-found]  # noqa: E402

LABELS = {"pre_seed": "Pre-seed", "seed": "Seed", "series_a": "Series A", "series_b": "Series B", "growth": "Growth"}
CANON = {
    "stage_confirmation": ["Looks right", "Different stage", "Not sure — proceed anyway"],
    "out_of_scope_choice": ["Stop review", "Different stage", "Proceed anyway (best-effort)"],
}
QUESTIONS = {
    "stage_confirmation": "Does this stage detection look right?",
    "out_of_scope_choice": "This looks out of scope. What should I do?",
    "stage_choice": "Which stage is this deck?",
}


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _run(tmp: Path, lines: str = "", *, claimed: str | None = "seed", stage: str = "seed") -> tuple[Path, Path]:
    """(artifacts root, run dir): a started and bound run whose dir holds the fixture artifacts."""
    run_dir = tmp / "artifacts" / "deck-review-example-co"
    run_dir.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        if f.is_file():
            shutil.copy(f, run_dir / f.name)
    inv = json.loads((run_dir / "deck_inventory.json").read_text(encoding="utf-8"))
    inv["claimed_stage"] = claimed
    (run_dir / "deck_inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    root, run_id, bound = h.start_bound(tmp, "deck-review", lines=f"FS_HOST_RUN_ID={RID}\n{lines}")
    assert (run_id, bound) == (RID, run_dir)
    if stage != "seed":
        _rebuild(run_dir, stage, "high")
    return root, run_dir


def _rebuild(run_dir: Path, stage: str, confidence: str) -> None:
    current = (run_dir / "stage_profile.json").read_text(encoding="utf-8")
    proc = h.run(
        STAGE_PROFILE,
        "--rebuild-stage",
        stage,
        "--confidence",
        confidence,
        "--run-id",
        RID,
        "-o",
        str(run_dir / "stage_profile.json"),
        stdin=current,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _emit(run_dir: Path, gate_id: str, stage: str) -> subprocess.CompletedProcess[str]:
    options = [lab for tok, lab in LABELS.items() if tok != stage] if gate_id == "stage_choice" else CANON[gate_id]
    body = {
        "gate_id": gate_id,
        "question": QUESTIONS[gate_id],
        "options": options,
        "context_summary": "Detected from the deck's slides and its stated raise.",
    }
    return h.run(
        GATE_STATE,
        "emit",
        "--run-id",
        RID,
        "--stage",
        stage,
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(body),
    )


def _answer(run_dir: Path, label: str, source: str = "founder") -> subprocess.CompletedProcess[str]:
    return h.run(
        GATE_STATE, "answer", "--file", str(run_dir / "gate_state.json"), "--answer", label, "--source", source
    )


def _asked(run_dir: Path, gate_id: str, stage: str) -> dict[str, Any]:
    proc = _emit(run_dir, gate_id, stage)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = _out(proc)
    assert "needs_input" in out and "answered" not in out, out
    return out


def _settle(run_dir: Path, gate_id: str, stage: str, label: str) -> None:
    _asked(run_dir, gate_id, stage)
    proc = _answer(run_dir, label)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _compose(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return h.run(
        COMPOSE,
        "--dir",
        str(run_dir),
        "-o",
        str(run_dir / "report.json"),
        "--write-md",
        str(run_dir / "report.md"),
        "--gate-state",
        str(run_dir / "gate_state.json"),
        *extra,
    )


def _open_ids(root: Path) -> list[str]:
    return sorted(k for k, e in h.ledger(root, RID)["gates"].items() if e["state"] == "open")


def _setup(root: Path) -> dict[str, Any]:
    proc = h.run(SETUP_RUN, "--artifacts-root", str(root), "--slug", "example-co", "--run-id", RID, "--clean")
    assert proc.returncode == 0, proc.stderr
    return _out(proc)


# --- every path through the stage question settles every gate it opened ---------------------------------

# (steps, final profile): each step is (gate, the stage it asks about, the answer), and a step's profile
# rebuild, when the answer calls for one, follows it as SKILL.md's branch table says.
PATHS: dict[str, tuple[list[tuple[str, str, str]], tuple[str, str]]] = {
    "looks_right": ([("stage_confirmation", "seed", "Looks right")], ("seed", "high")),
    "not_sure": ([("stage_confirmation", "seed", "Not sure — proceed anyway")], ("seed", "low")),
    "different_then_in_scope_then_looks_right": (
        [
            ("stage_confirmation", "seed", "Different stage"),
            ("stage_choice", "seed", "Series A"),
            ("stage_confirmation", "series_a", "Looks right"),
        ],
        ("series_a", "high"),
    ),
    "different_then_in_scope_then_not_sure": (
        [
            ("stage_confirmation", "seed", "Different stage"),
            ("stage_choice", "seed", "Series A"),
            ("stage_confirmation", "series_a", "Not sure — proceed anyway"),
        ],
        ("series_a", "low"),
    ),
    # The blocker: `Different stage` stayed open on stage_confirmation once the out-of-scope answer settled.
    "different_then_out_of_scope_then_proceed": (
        [
            ("stage_confirmation", "seed", "Different stage"),
            ("stage_choice", "seed", "Growth"),
            ("out_of_scope_choice", "growth", "Proceed anyway (best-effort)"),
        ],
        ("series_a", "low"),
    ),
    "out_of_scope_then_proceed": (
        [("out_of_scope_choice", "growth", "Proceed anyway (best-effort)")],
        ("series_a", "low"),
    ),
    "out_of_scope_then_different_then_in_scope": (
        [
            ("out_of_scope_choice", "growth", "Different stage"),
            ("stage_choice", "growth", "Seed"),
            ("stage_confirmation", "seed", "Looks right"),
        ],
        ("seed", "high"),
    ),
    "out_of_scope_then_different_then_out_of_scope_again": (
        [
            ("out_of_scope_choice", "growth", "Different stage"),
            ("stage_choice", "growth", "Series B"),
            ("out_of_scope_choice", "series_b", "Proceed anyway (best-effort)"),
        ],
        ("series_a", "low"),
    ),
}


@pytest.mark.parametrize("name", list(PATHS))
def test_every_path_through_the_stage_question_ends_with_no_open_gate(tmp_path: Path, name: str) -> None:
    steps, (final_stage, final_conf) = PATHS[name]
    first_stage = steps[0][1]
    root, run_dir = _run(tmp_path, stage=first_stage)
    for gate_id, stage, label in steps:
        _settle(run_dir, gate_id, stage, label)
        if gate_id == "stage_choice":
            _rebuild(run_dir, [t for t, lab in LABELS.items() if lab == label][0], "high")
    _rebuild(run_dir, final_stage, final_conf)
    assert _open_ids(root) == [], h.ledger(root, RID)["gates"]
    st = h.status(root, RID)
    assert st["status"] == "running", (st["status"], st["code"], st["waiting_on"])
    assert _setup(root)["gate_action"] in ("continue", "continue_if_rebuilt")
    proc = _compose(run_dir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.status(root, RID)["coaching"] == "pending"


def test_the_out_of_scope_answer_closes_the_whole_stage_question() -> None:
    """The registry lever the path test above depends on, held directly."""
    sys.path.insert(0, str(h.SHARED))
    import _gates  # type: ignore[import-not-found]  # noqa: PLC0415

    opts = {o["id"]: o for o in _gates.GATES["out_of_scope_choice"]["options"]}
    for oid in ("proceed_anyway", "stop_review"):
        assert set(opts[oid]["effects"]["closes"]) == {"stage_choice", "stage_confirmation"}


# --- refusal codes, one per site -----------------------------------------------------------------------


def _gate(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "metadata": {"run_id": "r1"},
        "gate_id": "stage_confirmation",
        "question": "?",
        "options": CANON["stage_confirmation"],
        "context_summary": "x",
        "confirmed_stage": "seed",
        "answer": "Looks right",
        "answer_source": "founder",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _profile(**over: Any) -> dict[str, Any]:
    return {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "high", **over}


_OOS_UNANSWERED_HISTORY = [{"gate_id": "out_of_scope_choice", "run_id": "r1", "confirmed_stage": "growth"}]

CODE_SITES: dict[str, tuple[Any, dict[str, Any], str]] = {
    "not_an_object": ("x", _profile(), "GATE_INVALID"),
    "gate_from_another_run": (_gate(metadata={"run_id": "r0"}), _profile(), "GATE_OTHER_RUN"),
    "profile_from_another_run": (_gate(), _profile(metadata={"run_id": "r0"}), "GATE_OTHER_RUN"),
    "declined": (
        _gate(gate_id="out_of_scope_choice", options=CANON["out_of_scope_choice"], confirmed_stage="growth")
        | {"answer": "Stop review"},
        _profile(),
        "FOUNDER_DECLINED",
    ),
    "never_answered": (_gate(answer=None, answer_source=None), _profile(), "GATE_UNANSWERED"),
    "intermediate": (_gate(answer="Different stage"), _profile(), "GATE_INTERMEDIATE"),
    "no_confirmed_stage": (_gate(confirmed_stage=None), _profile(), "GATE_INVALID"),
    "unknown_stage": (_gate(confirmed_stage="series_z"), _profile(), "GATE_INVALID"),
    "no_transition": (_gate(confirmed_stage="growth"), _profile(), "GATE_INVALID"),
    "profile_moved": (_gate(), _profile(detected_stage="series_a"), "PROFILE_MISMATCH"),
    "out_of_scope_never_answered": (
        _gate(history=_OOS_UNANSWERED_HISTORY),
        _profile(),
        "OUT_OF_SCOPE_UNANSWERED",
    ),
    "not_rebuilt_low": (_gate(answer="Not sure — proceed anyway"), _profile(), "PROFILE_MISMATCH"),
    "auto_satisfied_low": (
        _gate(answer_source="auto_satisfied"),
        _profile(confidence="low"),
        "AUTO_SATISFY_NOT_ALLOWED",
    ),
}


@pytest.mark.parametrize("site", list(CODE_SITES))
def test_each_refusal_carries_its_code(site: str) -> None:
    gate, profile, code = CODE_SITES[site]
    verdict = gate_state.authorize(gate, profile, "r1")
    assert (verdict.permitted, verdict.code) == (False, code), verdict.reason


def test_the_two_backstop_refusals_carry_their_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unrecognised-action and out-of-scope-result refusals are unreachable through the tables; each
    is reached here by changing the table it guards."""
    monkeypatch.setattr(gate_state, "gate_action", lambda g: "weird")
    assert gate_state.authorize(_gate(), _profile(), "r1").code == "GATE_INVALID"
    monkeypatch.undo()
    rows = dict(gate_state.TRANSITIONS)
    rows[("in_scope", "stage_confirmation", "Looks right")] = {"resulting_stage": "growth", "confidence": None}
    monkeypatch.setattr(gate_state, "TRANSITIONS", rows)
    verdict = gate_state.authorize(_gate(), _profile(detected_stage="growth"), "r1")
    assert (verdict.permitted, verdict.code) == (False, "PROFILE_MISMATCH")


def test_a_permit_carries_no_code() -> None:
    verdict = gate_state.authorize(_gate(), _profile(), "r1")
    assert (verdict.permitted, verdict.code) == (True, "")


# --- the host's answer reaches the stage question --------------------------------------------------------


def test_a_request_answer_is_applied_when_the_gate_is_emitted(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=looks_right\n")
    proc = _emit(run_dir, "stage_confirmation", "seed")
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert "needs_input" not in out
    applied = out["answered"]
    assert (applied["answer_source"], applied["gate_id"]) == ("host", "stage_confirmation")
    assert applied["answer"] == "Looks right"
    mirror = json.loads((run_dir / "gate_state.json").read_text(encoding="utf-8"))
    assert (mirror["answer"], mirror["answer_source"]) == ("Looks right", "host")
    led = h.ledger(root, RID)
    entry = led["gates"]["stage_confirmation"]
    assert entry["state"] == "answered"
    assert led["pre_answers"]["stage_confirmation"]["applied_at"] == entry["current"]["answered_at"]
    assert any(ev["event"] == "pre_answer_applied" for ev in entry["history"])
    st = h.status(root, RID)
    assert "PRE_ANSWERED:stage_confirmation" in st["disclosures"]
    after = _setup(root)
    assert (after["resume"], after["gate_action"], after["answer_source"]) == (True, "continue", "host")
    assert _compose(run_dir).returncode == 0
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "the request that started this review answered it" in report


def test_a_request_answer_is_withheld_when_the_deck_names_another_stage(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=looks_right\n", claimed="series_a")
    _asked(run_dir, "stage_confirmation", "seed")
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "PRE_ANSWER_UNLISTED", "stage_confirmation")
    notice = [n for n in h.ledger(root, RID)["notices"] if n["code"] == "PRE_ANSWER_NOT_APPLIED"]
    assert len(notice) == 1 and "deck states Series A" in notice[0]["reason"]
    assert st["notices"] == h.ledger(root, RID)["notices"]


def test_a_request_looks_right_is_withheld_at_low_confidence(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=looks_right\n")
    _rebuild(run_dir, "seed", "low")
    _asked(run_dir, "stage_confirmation", "seed")
    assert h.status(root, RID)["code"] == "PRE_ANSWER_UNLISTED"
    assert "low confidence" in h.ledger(root, RID)["notices"][-1]["reason"]


def test_a_request_not_sure_is_applied_at_low_confidence(tmp_path: Path) -> None:
    """The low-confidence guard is auto-satisfy's, which covers `Looks right` only."""
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=not_sure_proceed\n")
    _rebuild(run_dir, "seed", "low")
    out = _out(_emit(run_dir, "stage_confirmation", "seed"))
    assert out["answered"]["answer"] == "Not sure — proceed anyway"


def test_a_request_stage_pick_the_emit_does_not_offer_is_asked(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_choice=seed\n")
    _settle(run_dir, "stage_confirmation", "seed", "Different stage")
    _asked(run_dir, "stage_choice", "seed")  # Seed is the stage just rejected, so it is not offered
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "PRE_ANSWER_UNLISTED", "stage_choice")


def test_a_request_decline_refuses_the_run(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER out_of_scope_choice=stop_review\n", stage="growth")
    out = _out(_emit(run_dir, "out_of_scope_choice", "growth"))
    assert out["answered"]["answer"] == "Stop review"
    st = h.status(root, RID)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")
    assert _setup(root)["gate_action"] == "stop"


def test_the_cli_cannot_write_the_host_source(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _asked(run_dir, "stage_confirmation", "seed")
    proc = _answer(run_dir, "Looks right", source="host")
    assert proc.returncode == 2 and "invalid choice" in proc.stderr
    assert "host" in gate_state.ANSWER_SOURCES and "host" not in gate_state.CLI_SOURCES


def test_the_schema_admits_exactly_the_sources_the_file_may_carry() -> None:
    schema = json.loads((h.SKILLS / "deck-review/references/schemas/gate_state.schema.json").read_text())
    assert schema["properties"]["answer_source"]["enum"] == list(gate_state.ANSWER_SOURCES)


# --- an answer is bound to the stage it confirmed --------------------------------------------------------


def test_re_emitting_for_another_stage_asks_again(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, claimed=None)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    same = _out(_emit(run_dir, "stage_confirmation", "seed"))
    assert same["answered"]["answer"] == "Looks right", "the same stage is mirrored from the ledger"
    _rebuild(run_dir, "series_a", "high")
    _asked(run_dir, "stage_confirmation", "series_a")
    entry = h.ledger(root, RID)["gates"]["stage_confirmation"]
    assert (entry["state"], entry["supersessions"]) == ("open", 1)
    assert [ev["reason"] for ev in entry["history"] if ev["event"] == "superseded"] == ["binding_changed"]
    assert h.status(root, RID)["waiting_on"] == "stage_confirmation"


def test_a_founder_answer_after_a_superseded_request_answer_is_the_founders(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=looks_right\n", claimed=None)
    assert _out(_emit(run_dir, "stage_confirmation", "seed"))["answered"]["answer_source"] == "host"
    _rebuild(run_dir, "series_a", "high")
    _settle(run_dir, "stage_confirmation", "series_a", "Looks right")
    mirror = json.loads((run_dir / "gate_state.json").read_text(encoding="utf-8"))
    assert mirror["answer_source"] == "founder"
    assert "PRE_ANSWERED:stage_confirmation" not in h.status(root, RID)["disclosures"]
    again = _out(_emit(run_dir, "stage_confirmation", "series_a"))
    assert again["answered"]["answer_source"] == "founder"


# --- compose: each refusal class, and the open-question check ---------------------------------------------


def test_compose_over_an_unanswered_gate_waits_on_it(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _asked(run_dir, "stage_confirmation", "seed")
    proc = _compose(run_dir)
    assert proc.returncode == 10, proc.stderr
    out = _out(proc)
    assert (out["code"], out["blocked_by_gate"]) == ("GATE_UNANSWERED", "stage_confirmation")
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "GATE_UNANSWERED", "stage_confirmation")
    assert not (run_dir / "report.json").exists() and not (run_dir / "report.md").exists()


def test_compose_on_an_intermediate_pick_keeps_the_pick(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Different stage")
    _settle(run_dir, "stage_choice", "seed", "Series A")
    before = h.ledger(root, RID)["gates"]["stage_choice"]
    proc = _compose(run_dir)
    assert proc.returncode == 10
    out = _out(proc)
    assert (out["code"], out["blocked_by_gate"]) == ("GATE_INTERMEDIATE", "stage_confirmation")
    after = h.ledger(root, RID)["gates"]["stage_choice"]
    assert after == before, "the founder's pick was thrown away"
    assert after["current"]["answer_id"] == "series_a"
    mirror = json.loads((run_dir / "gate_state.json").read_text(encoding="utf-8"))
    assert (mirror["gate_id"], mirror["answer"]) == ("stage_choice", after["current"]["answer"])
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "GATE_INTERMEDIATE", "stage_confirmation")


def test_compose_supersedes_an_auto_satisfied_answer_the_profile_does_not_support(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _asked(run_dir, "stage_confirmation", "seed")
    assert _answer(run_dir, "Looks right", source="auto_satisfied").returncode == 0
    _rebuild(run_dir, "seed", "low")
    proc = _compose(run_dir)
    assert proc.returncode == 10
    assert _out(proc)["code"] == "AUTO_SATISFY_NOT_ALLOWED"
    entry = h.ledger(root, RID)["gates"]["stage_confirmation"]
    assert (entry["state"], entry["supersessions"]) == ("open", 1)
    st = h.status(root, RID)
    assert (st["status"], st["code"]) == ("waiting", "AUTO_SATISFY_NOT_ALLOWED")
    _asked(run_dir, "stage_confirmation", "seed")  # the next emit asks rather than mirroring the default


def test_compose_reopens_an_out_of_scope_question_a_later_answer_closed(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, stage="growth")
    _asked(run_dir, "out_of_scope_choice", "growth")
    _rebuild(run_dir, "series_a", "low")
    _settle(run_dir, "stage_confirmation", "series_a", "Looks right")
    assert h.ledger(root, RID)["gates"]["out_of_scope_choice"]["state"] == "not_owed"
    proc = _compose(run_dir)
    assert proc.returncode == 10
    out = _out(proc)
    assert (out["code"], out["blocked_by_gate"]) == ("OUT_OF_SCOPE_UNANSWERED", "out_of_scope_choice")
    assert h.ledger(root, RID)["gates"]["out_of_scope_choice"]["state"] == "open"
    st = h.status(root, RID)
    assert (st["status"], st["code"], st["waiting_on"]) == (
        "waiting",
        "OUT_OF_SCOPE_UNANSWERED",
        "out_of_scope_choice",
    )
    _asked(run_dir, "out_of_scope_choice", "growth")


def test_compose_after_a_decline_leaves_the_run_refused(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, stage="growth")
    _settle(run_dir, "out_of_scope_choice", "growth", "Stop review")
    proc = _compose(run_dir)
    assert proc.returncode == 1
    assert (h.status(root, RID)["status"], h.status(root, RID)["code"]) == ("refused", "FOUNDER_DECLINED")


@pytest.mark.parametrize(
    ("breakage", "code"),
    [("gate_from_another_run", "GATE_OTHER_RUN"), ("profile_moved", "PROFILE_MISMATCH")],
)
def test_compose_refusals_the_run_must_repair_stay_running(tmp_path: Path, breakage: str, code: str) -> None:
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    if breakage == "gate_from_another_run":
        mirror = json.loads((run_dir / "gate_state.json").read_text(encoding="utf-8"))
        mirror["metadata"]["run_id"] = "another-run-001"
        (run_dir / "gate_state.json").write_text(json.dumps(mirror), encoding="utf-8")
    else:
        _rebuild(run_dir, "series_a", "high")
    proc = _compose(run_dir)
    assert proc.returncode == 1
    st = h.status(root, RID)
    assert (st["status"], st["last_error_code"]) == ("running", code)


def test_compose_refuses_while_a_question_it_opened_is_unrecorded(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    opened = h.record(root, RID, "open", "--gate", "dr_input_request.copy_failed")
    assert opened.returncode == 0, opened.stderr
    (run_dir / "report.json").write_text("sentinel", encoding="utf-8")
    proc = _compose(run_dir)
    assert proc.returncode == 10
    out = _out(proc)
    assert (out["status"], out["code"], out["blocked_by_gate"]) == (
        "running",
        "GATE_UNRESOLVED",
        "dr_input_request.copy_failed",
    )
    assert out["needs_input"][0]["answer_command"]
    assert "not-applicable" in proc.stderr
    assert (run_dir / "report.json").read_text(encoding="utf-8") == "sentinel"
    assert not (run_dir / "report.md").exists()
    st = h.status(root, RID)
    assert (st["status"], st["last_error_code"]) == ("running", "GATE_UNRESOLVED")


def test_a_status_write_that_fails_changes_neither_stdout_nor_the_exit(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    runs = root / "runs" / RID
    mode = runs.stat().st_mode
    os.chmod(runs, stat.S_IRUSR | stat.S_IXUSR)
    try:
        proc = _compose(run_dir)
    finally:
        os.chmod(runs, mode)
    assert proc.returncode == 0, proc.stderr
    assert _out(proc)["ok"] is True
    assert "warning: the run status was not updated" in proc.stderr
    assert (run_dir / "report.md").exists()


def test_compose_exits_2_when_the_ref_names_a_ledger_that_is_gone(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    (root / "runs" / RID / "gates.json").unlink()
    proc = _compose(run_dir)
    assert proc.returncode == 2
    assert _out(proc)["code"] == "LEDGER_MISSING"
    assert not (run_dir / "report.json").exists()


def test_compose_refuses_ungated_once_the_run_has_a_ledger(tmp_path: Path) -> None:
    _root, run_dir = _run(tmp_path)
    proc = h.run(COMPOSE, "--dir", str(run_dir), "-o", str(run_dir / "report.json"), "--ungated")
    assert proc.returncode == 1 and "--ungated" in proc.stderr
    assert not (run_dir / "report.json").exists()


# --- an input request asked twice --------------------------------------------------------------------


def test_a_repeated_input_request_can_be_answered_again_and_declined(tmp_path: Path) -> None:
    root, _run_dir = _run(tmp_path)
    key = "dr_input_request.copy_failed"
    first = h.record(root, RID, "open", "--gate", key)
    command = _out(first)["needs_input"][0]["answer_command"]
    assert command.endswith('--answer-id <option_id> --value "<text>"')
    assert h.record(root, RID, "answer", "--gate", key, "--answer-id", "provide", "--value", "deck.pdf").returncode == 0
    again = _out(h.record(root, RID, "open", "--gate", key))
    assert again["opened"] == [key] and again["needs_input"][0]["gate"] == key
    assert h.ledger(root, RID)["gates"][key]["supersessions"] == 1
    assert h.status(root, RID)["waiting_on"] == key
    twice = _out(h.record(root, RID, "open", "--gate", key))
    assert twice["opened"] == [] and h.ledger(root, RID)["gates"][key]["supersessions"] == 1
    assert (
        h.record(root, RID, "answer", "--gate", key, "--answer-id", "provide", "--value", "deck2.pdf").returncode == 0
    )
    assert h.record(root, RID, "open", "--gate", key).returncode == 0
    stop = h.record(root, RID, "answer", "--gate", key, "--answer-id", "stop")
    assert stop.returncode == 0, stop.stdout
    st = h.status(root, RID)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")


def test_other_recorded_answers_still_stand_on_a_second_open(tmp_path: Path) -> None:
    root, _run_dir = _run(tmp_path)
    assert h.record(root, RID, "open", "--gate", "dr_primary_deck").returncode == 0
    ok = h.record(root, RID, "answer", "--gate", "dr_primary_deck", "--answer-id", "named", "--value", "v2.pdf")
    assert ok.returncode == 0, ok.stdout
    again = _out(h.record(root, RID, "open", "--gate", "dr_primary_deck"))
    assert again["answered"] == ["dr_primary_deck"] and again["needs_input"] == []


def test_the_printed_value_slot_copied_as_it_stands_is_no_value(tmp_path: Path) -> None:
    root, _run_dir = _run(tmp_path)
    key = "dr_input_request.wrong_file_type"
    assert h.record(root, RID, "open", "--gate", key).returncode == 0
    proc = h.record(root, RID, "answer", "--gate", key, "--answer-id", "provide", "--value", "<text>")
    assert proc.returncode == 1 and _out(proc)["code"] == "VALUE_REQUIRED"
    stage = _out(h.record(root, RID, "open", "--gate", "ctx_basics.stage"))
    assert "--value" not in stage["needs_input"][0]["answer_command"]


# --- founder_context read with a ledger ----------------------------------------------------------------


def _context(root: Path, name: str, slug: str) -> None:
    proc = h.run(
        FOUNDER_CONTEXT,
        "init",
        "--company-name",
        name,
        "--slug",
        slug,
        "--stage",
        "seed",
        "--sector",
        "fintech",
        "--geography",
        "US",
        "--artifacts-root",
        str(root),
    )
    assert proc.returncode == 0, proc.stderr


def _started(tmp: Path, lines: str = "") -> tuple[Path, str]:
    root = tmp / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root, h.start_ok(root, "deck-review", lines)


def _read(root: Path, run_id: str | None, *extra: str, skill: str | None = "deck-review") -> Any:
    argv = ["read", "--artifacts-root", str(root), *extra]
    if run_id:
        argv += ["--run-id", run_id]
    if skill and run_id:
        argv += ["--skill", skill]
    return h.run(FOUNDER_CONTEXT, *argv)


def test_read_with_several_contexts_asks_which(tmp_path: Path) -> None:
    root, rid = _started(tmp_path)
    _context(root, "Example Co", "example-co")
    _context(root, "Sample Labs", "sample-labs")
    proc = _read(root, rid)
    assert proc.returncode == 10, proc.stderr
    needs = _out(proc)["needs_input"][0]
    assert needs["gate"] == "ctx_select_company"
    assert {o["id"] for o in needs["options"]} == {"example-co", "sample-labs", "different_company"}
    st = h.status(root, rid)
    assert (st["status"], st["waiting_on"]) == ("waiting", "ctx_select_company")


def test_read_follows_the_recorded_company(tmp_path: Path) -> None:
    root, rid = _started(tmp_path)
    _context(root, "Example Co", "example-co")
    _context(root, "Sample Labs", "sample-labs")
    assert _read(root, rid).returncode == 10
    ans = h.record(root, rid, "answer", "--gate", "ctx_select_company", "--answer-id", "sample-labs")
    assert ans.returncode == 0, ans.stdout
    for extra in ((), ("--slug", "sample-labs")):
        proc = _read(root, rid, *extra)
        assert proc.returncode == 0, proc.stderr
        assert _out(proc)["slug"] == "sample-labs"
    wrong = _read(root, rid, "--slug", "example-co")
    assert wrong.returncode == 1 and _out(wrong)["code"] == "GATE_RECORD_MISMATCH"
    gates = h.ledger(root, rid)["gates"]
    assert all(
        gates[f"ctx_basics.{f}"]["state"] == "not_owed" for f in ("company_name", "stage", "sector", "geography")
    )


def test_read_after_a_different_company_is_not_found(tmp_path: Path) -> None:
    root, rid = _started(tmp_path)
    _context(root, "Example Co", "example-co")
    _context(root, "Sample Labs", "sample-labs")
    assert _read(root, rid).returncode == 10
    h.record(root, rid, "answer", "--gate", "ctx_select_company", "--answer-id", "different_company")
    proc = _read(root, rid)
    assert proc.returncode == 1 and "No founder context" in proc.stderr
    assert _out(proc)["code"] == "CONTEXT_NOT_FOUND", "not found must be told apart from a refusal"


def test_read_of_one_context_records_the_basics_and_prints_what_a_plain_read_prints(tmp_path: Path) -> None:
    root, rid = _started(tmp_path, "FS_HOST_ANSWER ctx_basics.stage=seed\n")
    _context(root, "Example Co", "example-co")
    plain = _read(root, None, "--pretty")
    proc = _read(root, rid, "--pretty")
    assert (proc.returncode, proc.stdout) == (0, plain.stdout)
    gates = h.ledger(root, rid)["gates"]
    for key in ("ctx_basics.company_name", "ctx_basics.stage", "ctx_basics.sector", "ctx_basics.geography"):
        assert gates[key]["state"] == "not_owed"
        assert gates[key]["current"]["resolution"] == "not_applicable"
    assert gates["ctx_stage_detail"]["state"] == "not_owed"
    notices = h.status(root, rid)["notices"]
    assert [n["gate"] for n in notices if n["code"] == "PRE_ANSWER_IGNORED"] == ["ctx_basics.stage"]
    before = h.snapshot(root, rid)
    assert _read(root, rid).returncode == 0
    assert h.snapshot(root, rid) == before, "a second read changed the record"


def test_read_of_no_context_is_not_found_and_a_read_with_no_ledger_is_unchanged(tmp_path: Path) -> None:
    root, rid = _started(tmp_path)
    missing = _read(root, rid)
    assert missing.returncode == 1 and _out(missing)["code"] == "CONTEXT_NOT_FOUND"
    other = tmp_path / "other"
    other.mkdir()
    _context(other, "Example Co", "example-co")
    with_id = _read(other, "20261007T090000Z-0f0f0f")
    plain = _read(other, None)
    assert (with_id.returncode, with_id.stdout, with_id.stderr) == (plain.returncode, plain.stdout, plain.stderr)


def test_read_with_a_ledger_needs_the_skill_and_refuses_another_skills_run(tmp_path: Path) -> None:
    root, rid = _started(tmp_path)
    _context(root, "Example Co", "example-co")
    assert _read(root, rid, skill=None).returncode == 2
    before = h.snapshot(root, rid)
    proc = _read(root, rid, skill="market-sizing")
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert h.snapshot(root, rid) == before


def test_a_bound_run_reads_its_own_company(tmp_path: Path) -> None:
    """A resume never re-asks which company, even after `A different company` sent it to `init`."""
    root, rid = _started(tmp_path)
    _context(root, "Example Co", "example-co")
    _context(root, "Sample Labs", "sample-labs")
    assert _read(root, rid).returncode == 10
    h.record(root, rid, "answer", "--gate", "ctx_select_company", "--answer-id", "different_company")
    _context(root, "Third Corp", "third-corp")
    assert h.bind(root, rid, root / "deck-review-third-corp", "third-corp").returncode == 0
    proc = _read(root, rid)
    assert proc.returncode == 0, proc.stderr
    assert _out(proc)["slug"] == "third-corp"


# --- setup_run on a bound run -------------------------------------------------------------------------


def test_a_bound_run_keeps_its_checkpoints_at_an_unanswered_gate(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path)
    _asked(run_dir, "stage_confirmation", "seed")
    before = (run_dir / "deck_inventory.json").read_bytes()
    out = _setup(root)
    assert (out["cleaned"], out["reuse_checkpoints"], out["resume"]) == (False, True, False)
    assert (run_dir / "deck_inventory.json").read_bytes() == before
    assert (run_dir / "gate_state.json").exists()


# --- after compose's exit 10, setup_run names the question, and following it converges -----------------------


def _intermediate(root: Path, run_dir: Path) -> None:
    _settle(run_dir, "stage_confirmation", "seed", "Different stage")
    _settle(run_dir, "stage_choice", "seed", "Series A")


def _auto_low(root: Path, run_dir: Path) -> None:
    _asked(run_dir, "stage_confirmation", "seed")
    assert _answer(run_dir, "Looks right", source="auto_satisfied").returncode == 0
    _rebuild(run_dir, "seed", "low")


def _oos_closed(root: Path, run_dir: Path) -> None:
    _asked(run_dir, "out_of_scope_choice", "growth")
    _rebuild(run_dir, "series_a", "low")
    _settle(run_dir, "stage_confirmation", "series_a", "Looks right")


def _unanswered(root: Path, run_dir: Path) -> None:
    _asked(run_dir, "stage_confirmation", "seed")


RECOVERIES: dict[str, tuple[Any, str, str]] = {
    # code: (how the run gets there, the stage the run starts at, what setup_run must then say)
    "GATE_UNANSWERED": (_unanswered, "seed", "reask"),
    "GATE_INTERMEDIATE": (_intermediate, "seed", "rebuild"),
    "OUT_OF_SCOPE_UNANSWERED": (_oos_closed, "growth", "reask"),
    "AUTO_SATISFY_NOT_ALLOWED": (_auto_low, "seed", "reask"),
}


@pytest.mark.parametrize("code", list(RECOVERIES))
def test_compose_exit_10_then_setup_run_then_the_next_emit_converges(tmp_path: Path, code: str) -> None:
    """The loop the skill text prescribes: compose exits 10, `setup_run` says what to do, the model does it,
    compose again. It must finish in one round, never print `continue` while the ledger waits."""
    reach, first_stage, action = RECOVERIES[code]
    root, run_dir = _run(tmp_path, stage=first_stage)
    reach(root, run_dir)
    refused = _compose(run_dir)
    assert refused.returncode == 10 and _out(refused)["code"] == code
    told = _setup(root)
    assert told["gate_action"] == action, told
    if action == "reask":
        assert told["resume"] is False, "a waiting question is not a resume past the gate"
        assert told["gate_id"] == _out(refused)["blocked_by_gate"]
        stage = told.get("gate_stage") or first_stage
        if code == "OUT_OF_SCOPE_UNANSWERED":
            assert told["gate_stage"] == "growth"
            _settle(run_dir, "out_of_scope_choice", "growth", "Proceed anyway (best-effort)")
        else:
            assert stage == "seed"
            _settle(run_dir, told["gate_id"], "seed", "Looks right")
    else:
        # `rebuild` on the pick: rebuild to it, then emit the confirmation for that stage.
        assert told["gate_id"] == "stage_choice"
        _rebuild(run_dir, "series_a", "high")
        _settle(run_dir, "stage_confirmation", "series_a", "Looks right")
    assert _setup(root)["gate_action"] in ("continue", "continue_if_rebuilt")
    again = _compose(run_dir)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _open_ids(root) == []


# --- a request that proceeds with an out-of-scope deck is disclosed as that ---------------------------------

VISUALIZE = SCRIPTS / "visualize.py"


def _page(run_dir: Path) -> str:
    out = run_dir / "report.html"
    proc = h.run(
        VISUALIZE,
        "--dir",
        str(run_dir),
        "-o",
        str(out),
        "--gate-state",
        str(run_dir / "gate_state.json"),
        "--run-id",
        RID,
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text(encoding="utf-8")


def test_a_request_that_proceeds_out_of_scope_says_so_on_every_surface(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER out_of_scope_choice=proceed_anyway\n", stage="growth")
    out = _out(_emit(run_dir, "out_of_scope_choice", "growth"))
    assert out["answered"]["answer_source"] == "host"
    _rebuild(run_dir, "series_a", "low")
    assert _compose(run_dir).returncode == 0
    page = _page(run_dir)
    for surface in ((run_dir / "report.md").read_text(encoding="utf-8"), page):
        assert "outside the stages this review covers" in surface
        assert "the request that started this review chose to proceed anyway" in surface
        assert "taken as confirmed" not in surface
    assert "PRE_ANSWERED:out_of_scope_choice" in h.status(root, RID)["disclosures"]


def test_the_page_says_when_the_request_answered_the_stage_and_only_then(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, "FS_HOST_ANSWER stage_confirmation=looks_right\n")
    _emit(run_dir, "stage_confirmation", "seed")
    assert _compose(run_dir).returncode == 0
    assert "the request that started this review answered it" in _page(run_dir)
    founder = tmp_path / "founder"
    _root2, run_dir2 = _run(founder)
    _settle(run_dir2, "stage_confirmation", "seed", "Looks right")
    assert _compose(run_dir2).returncode == 0
    assert "the request that started this review" not in _page(run_dir2)


# --- the five fixes the first review found unpinned --------------------------------------------------------


def test_a_request_answer_the_mirror_would_refuse_is_never_recorded(tmp_path: Path) -> None:
    """The would-be mirror is validated BEFORE the ledger takes the answer: a copy of the plugin whose schema
    does not admit `host` refuses the emit and leaves the question open, the line unapplied."""
    plugin = tmp_path / "plugin"
    shutil.copytree(h.SHARED, plugin / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        h.SKILLS / "deck-review", plugin / "skills" / "deck-review", ignore=shutil.ignore_patterns("__pycache__")
    )
    schema_path = plugin / "skills/deck-review/references/schemas/gate_state.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["answer_source"]["enum"] = ["founder", "auto_satisfied"]
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    root, run_dir = _run(tmp_path / "run", "FS_HOST_ANSWER stage_confirmation=looks_right\n")
    body = {
        "gate_id": "stage_confirmation",
        "question": QUESTIONS["stage_confirmation"],
        "options": CANON["stage_confirmation"],
        "context_summary": "Detected from the deck's slides and its stated raise.",
    }
    proc = h.run(
        plugin / "skills/deck-review/scripts/gate_state.py",
        "emit",
        "--run-id",
        RID,
        "--stage",
        "seed",
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(body),
    )
    assert proc.returncode == 1 and "validation failed" in proc.stderr
    led = h.ledger(root, RID)
    assert led["gates"]["stage_confirmation"]["state"] == "open"
    assert led["pre_answers"]["stage_confirmation"]["applied_at"] is None


def test_compose_never_supersedes_a_founders_recorded_answer(tmp_path: Path) -> None:
    """A mirror that lost the answer the ledger holds (hand-edited, or a write that did not land): compose
    waits on the question, and the founder's recorded answer stands."""
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    mirror = json.loads((run_dir / "gate_state.json").read_text(encoding="utf-8"))
    for key in ("answer", "answer_source"):
        mirror.pop(key)
    (run_dir / "gate_state.json").write_text(json.dumps(mirror), encoding="utf-8")
    proc = _compose(run_dir)
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNANSWERED"
    entry = h.ledger(root, RID)["gates"]["stage_confirmation"]
    assert (entry["state"], entry["supersessions"], entry["current"]["answer_id"]) == ("answered", 0, "looks_right")
    re_emitted = _out(_emit(run_dir, "stage_confirmation", "seed"))
    assert re_emitted["answered"]["answer_source"] == "founder", "the re-emit restores the mirror from the ledger"


def test_emitting_a_question_another_answer_closed_asks_it_again(tmp_path: Path) -> None:
    """`proceed_anyway` closes `stage_confirmation`; emitting it afterwards (no compose in between) is the
    question put afresh, so it is asked, never mirrored from the closure."""
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Different stage")
    _settle(run_dir, "stage_choice", "seed", "Growth")
    _rebuild(run_dir, "growth", "high")
    _settle(run_dir, "out_of_scope_choice", "growth", "Proceed anyway (best-effort)")
    assert h.ledger(root, RID)["gates"]["stage_confirmation"]["state"] == "not_owed"
    _rebuild(run_dir, "series_a", "high")
    _asked(run_dir, "stage_confirmation", "series_a")
    entry = h.ledger(root, RID)["gates"]["stage_confirmation"]
    assert (entry["state"], entry["supersessions"]) == ("open", 1)
    assert [ev["reason"] for ev in entry["history"] if ev["event"] == "superseded"] == ["emitted_again"]


def test_compose_over_a_declining_mirror_refuses_the_run(tmp_path: Path) -> None:
    """The backstop: the mirror records a decline the ledger does not (a diverged mirror). Compose refuses
    and the run is `refused`, never left `running`."""
    root, run_dir = _run(tmp_path)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    assert h.status(root, RID)["status"] == "running"
    declined = {
        "metadata": {"run_id": RID},
        "gate_id": "out_of_scope_choice",
        "question": QUESTIONS["out_of_scope_choice"],
        "options": CANON["out_of_scope_choice"],
        "context_summary": "x",
        "confirmed_stage": "growth",
        "answer": "Stop review",
        "answer_source": "founder",
    }
    (run_dir / "gate_state.json").write_text(json.dumps(declined), encoding="utf-8")
    proc = _compose(run_dir)
    assert proc.returncode == 1
    st = h.status(root, RID)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")


# --- minors: the decline's re-bind, the placeholder ------------------------------------------------------


def test_the_slug_block_after_a_decline_binds_quietly(tmp_path: Path) -> None:
    root, run_dir = _run(tmp_path, stage="growth")
    _settle(run_dir, "out_of_scope_choice", "growth", "Stop review")
    assert _setup(root)["gate_action"] == "stop"
    before = h.snapshot(root, RID)
    proc = h.bind(root, RID, run_dir, "example-co")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _out(proc)["code"] == "RUN_REFUSED"
    assert h.snapshot(root, RID) == before
    assert not (root / "runs" / RID / "start_refusals.jsonl").exists()
    other = h.bind(root, RID, root / "deck-review-other-co", "other-co")
    assert other.returncode == 1, "only the run's own dir and slug bind quietly"


def test_a_value_shaped_like_a_placeholder_is_still_a_value(tmp_path: Path) -> None:
    root, _run_dir = _run(tmp_path)
    assert h.record(root, RID, "open", "--gate", "dr_primary_deck").returncode == 0
    ok = h.record(root, RID, "answer", "--gate", "dr_primary_deck", "--answer-id", "named", "--value", "<n/a>")
    assert ok.returncode == 0, ok.stdout
    assert h.ledger(root, RID)["gates"]["dr_primary_deck"]["current"]["value"] == "<n/a>"


def test_a_re_emitted_question_is_asked_about_the_stage_it_was_re_emitted_for(tmp_path: Path) -> None:
    """Answered about seed, the profile rebuilt to series_a and the gate re-emitted about series_a: before the
    reply, setup_run names series_a, never the stage the superseded answer confirmed."""
    root, run_dir = _run(tmp_path, claimed=None)
    _settle(run_dir, "stage_confirmation", "seed", "Looks right")
    _rebuild(run_dir, "series_a", "high")
    _asked(run_dir, "stage_confirmation", "series_a")
    told = _setup(root)
    assert (told["gate_action"], told["gate_id"], told["gate_stage"]) == ("reask", "stage_confirmation", "series_a")
    _settle(run_dir, "stage_confirmation", told["gate_stage"], "Looks right")
    assert _compose(run_dir).returncode == 0
