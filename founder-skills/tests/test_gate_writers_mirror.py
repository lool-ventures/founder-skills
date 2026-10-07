"""The scripts that record their own gates write through the ledger when a run has one, and only then.

`gate_state.py` (deck-review), `record_revision_answer.py` (market-sizing) and `extract_cap_table.py`
(cap-table) each keep their own file, which other steps read. With a ledger, the ledger is written first
and the file is its mirror; a refusal on either side leaves both as they were. With no ledger, each
behaves exactly as it did before the ledger existed: held against goldens captured before the change,
and against a copy of the skill with the plugin's shared scripts absent (a flat mount), which must not
change a byte of stdout. `founder_context.py init` is held the same way. Ids and names are synthetic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
import no_ledger_goldens as goldens  # noqa: E402

GATE_STATE = h.SKILLS / "deck-review" / "scripts" / "gate_state.py"
REVISION = h.SKILLS / "market-sizing" / "scripts" / "record_revision_answer.py"
EXTRACT = h.SKILLS / "cap-table" / "scripts" / "extract_cap_table.py"
FOUNDER_CONTEXT = h.SHARED / "founder_context.py"


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


# --- no ledger: today's behaviour ----------------------------------------------------------------


@pytest.mark.parametrize(
    "group",
    [
        "gate_state",
        "record_revision_answer",
        "extract_cap_table",
        "extract_cap_table_flat",
        "founder_context",
        "apply_corrections",
        "html_stdout",
    ],
)
def test_with_no_ledger_each_writer_matches_its_golden(group: str) -> None:
    assert goldens.GROUPS[group]() == goldens.load()[group]


def _flat_copy(tmp: Path, skill: str) -> Path:
    """The skill's scripts as a flat mount has them: no plugin-root `scripts/` beside the skills."""
    dest = tmp / "flat" / "skills" / skill
    shutil.copytree(h.SKILLS / skill, dest, ignore=shutil.ignore_patterns("__pycache__"))
    assert not (tmp / "flat" / "scripts").exists()
    return dest / "scripts"


def _norm(text: str, *roots: Path) -> str:
    for r in roots:
        text = text.replace(str(r), "<ROOT>")
    return re.sub(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", "<TS>", text)


def test_a_flat_mount_runs_the_stage_gate_exactly_as_the_plugin_does(tmp_path: Path) -> None:
    flat = _flat_copy(tmp_path, "deck-review")
    results = []
    for scripts, work in ((GATE_STATE.parent, tmp_path / "a"), (flat, tmp_path / "b")):
        work.mkdir()
        gate = work / "gate_state.json"
        emit = h.run(
            scripts / "gate_state.py",
            "emit",
            "--run-id",
            goldens.GATE_RUN,
            "--stage",
            "seed",
            "-o",
            str(gate),
            stdin=json.dumps(goldens.STAGE_BODY),
        )
        ans = h.run(
            scripts / "gate_state.py", "answer", "--file", str(gate), "--answer", "Looks right", "--source", "founder"
        )
        results.append(
            [(p.returncode, _norm(p.stdout, work), _norm(p.stderr, work)) for p in (emit, ans)]
            + [_norm(gate.read_text(), work)]
        )
    assert results[0] == results[1]


def test_a_flat_mount_records_a_revision_answer_exactly_as_the_plugin_does(tmp_path: Path) -> None:
    flat = _flat_copy(tmp_path, "market-sizing")
    results = []
    for scripts, work in ((REVISION.parent, tmp_path / "a"), (flat, tmp_path / "b")):
        (work / "handoff" / goldens.GATE_RUN).mkdir(parents=True)
        (work / "redteam.json").write_text(json.dumps(goldens.REDTEAM))
        p = h.run(
            scripts / "record_revision_answer.py", "--dir", str(work), "--answer", "deliver", "--source", "founder"
        )
        results.append((p.returncode, _norm(p.stdout, work), p.stderr))
    assert results[0] == results[1]


# --- ledger mode: deck-review's stage gate --------------------------------------------------------


def _emit(run_dir: Path, run_id: str, gate_state: Path = GATE_STATE) -> subprocess.CompletedProcess[str]:
    return h.run(
        gate_state,
        "emit",
        "--run-id",
        run_id,
        "--stage",
        "seed",
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(goldens.STAGE_BODY),
    )


def _answer(run_dir: Path, answer: str, source: str = "founder", gate_state: Path = GATE_STATE) -> Any:
    return h.run(
        gate_state, "answer", "--file", str(run_dir / "gate_state.json"), "--answer", answer, "--source", source
    )


def _mirror_matches(root: Path, run_id: str, run_dir: Path) -> None:
    mirror = json.loads((run_dir / "gate_state.json").read_text())
    entry = h.ledger(root, run_id)["gates"][mirror["gate_id"]]
    if "answer" not in mirror:
        assert entry["state"] == "open" and entry["current"] is None
        return
    assert entry["current"]["answer"] == mirror["answer"]
    expected = "default_taken" if mirror["answer_source"] == "auto_satisfied" else "answered"
    assert entry["current"]["resolution"] == expected


def test_the_stage_gate_writes_the_ledger_first_and_mirrors_it(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert _emit(run_dir, run_id).returncode == 0
    _mirror_matches(root, run_id, run_dir)
    st = h.status(root, run_id)
    assert (st["status"], st["waiting_on"]) == ("waiting", "stage_confirmation")
    proc = _answer(run_dir, "Looks right")
    assert proc.returncode == 0, proc.stderr
    _mirror_matches(root, run_id, run_dir)
    assert h.status(root, run_id)["status"] == "running"
    assert _answer(run_dir, "Looks right").returncode == 0  # an identical re-answer is a no-op on both


def test_an_auto_satisfied_answer_is_recorded_as_its_default(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert _emit(run_dir, run_id).returncode == 0
    assert _answer(run_dir, "Looks right", "auto_satisfied").returncode == 0
    cur = h.ledger(root, run_id)["gates"]["stage_confirmation"]["current"]
    assert (cur["resolution"], cur["default_reason"]) == ("default_taken", "stage_stated_and_detected_agree")
    _mirror_matches(root, run_id, run_dir)


def test_a_body_the_schema_refuses_never_opens_the_gate(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    body = {k: v for k, v in goldens.STAGE_BODY.items() if k != "context_summary"}
    proc = h.run(
        GATE_STATE,
        "emit",
        "--run-id",
        run_id,
        "--stage",
        "seed",
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(body),
    )
    assert proc.returncode == 1 and "validation failed" in proc.stderr
    assert h.snapshot(root, run_id) == before
    assert not (run_dir / "gate_state.json").exists()


def test_a_ledger_refusal_leaves_the_mirror_untouched(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert _emit(run_dir, run_id).returncode == 0
    # The ledger already holds a different answer (written by an earlier call whose mirror write was lost).
    sys.path.append(str(h.SHARED))
    import _gates  # type: ignore[import-not-found]
    import _run_status  # type: ignore[import-not-found]

    _gates.record_from_writer(
        _run_status.run_paths(str(root), run_id), "stage_confirmation", "not_sure_proceed", "gate_state.py"
    )
    mirror_before = (run_dir / "gate_state.json").read_bytes()
    before = h.snapshot(root, run_id)
    proc = _answer(run_dir, "Looks right")
    assert proc.returncode == 1 and _out(proc)["code"] == "ANSWER_STANDS"
    assert (run_dir / "gate_state.json").read_bytes() == mirror_before
    assert h.snapshot(root, run_id) == before
    # The lost mirror write heals by re-running the answer the ledger holds.
    assert _answer(run_dir, "Not sure — proceed anyway").returncode == 0
    _mirror_matches(root, run_id, run_dir)


def test_a_declined_stage_question_refuses_the_run(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    body = {
        "gate_id": "out_of_scope_choice",
        "question": "This deck reads as a later-stage raise. How should I proceed?",
        "options": ["Stop review", "Different stage", "Proceed anyway (best-effort)"],
        "context_summary": "Detected stage: later than this review covers",
    }
    proc = h.run(
        GATE_STATE,
        "emit",
        "--run-id",
        run_id,
        "--stage",
        "growth",
        "-o",
        str(run_dir / "gate_state.json"),
        stdin=json.dumps(body),
    )
    assert proc.returncode == 0, proc.stderr
    assert _answer(run_dir, "Stop review").returncode == 0
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")


def test_two_concurrent_answers_leave_one_answer_in_both(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert _emit(run_dir, run_id).returncode == 0
    env = {k: v for k, v in os.environ.items() if not k.startswith("FS_HOST_")}
    env["FOUNDER_SKILLS_LOCK_PAUSE_S"] = "0.3"
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(GATE_STATE),
                "answer",
                "--file",
                str(run_dir / "gate_state.json"),
                "--answer",
                answer,
                "--source",
                "founder",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for answer in ("Looks right", "Not sure — proceed anyway")
    ]
    codes = sorted(p.wait(timeout=30) for p in procs)
    assert codes == [0, 1]
    _mirror_matches(root, run_id, run_dir)


def test_a_ref_with_no_reachable_registry_or_ledger_exits_2(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    flat = _flat_copy(tmp_path, "deck-review")
    proc = _emit(run_dir, run_id, flat / "gate_state.py")
    assert proc.returncode == 2 and _out(proc)["code"] == "REGISTRY_UNREACHABLE"
    assert not (run_dir / "gate_state.json").exists()
    h.ledger_path(root, run_id).unlink()
    proc = _emit(run_dir, run_id)
    assert proc.returncode == 2 and _out(proc)["code"] == "LEDGER_MISSING"
    assert not (run_dir / "gate_state.json").exists()


# --- ledger mode: market-sizing's revision answer ---------------------------------------------------


def _revision_run(tmp: Path) -> tuple[Path, str, Path]:
    root, run_id, run_dir = h.start_bound(tmp, "market-sizing")
    (run_dir / "redteam.json").write_text(json.dumps({**goldens.REDTEAM, "metadata": {"run_id": run_id}}))
    (run_dir / "handoff" / run_id).mkdir(parents=True, exist_ok=True)
    return root, run_id, run_dir


@pytest.mark.parametrize(
    ("answer", "source", "resolution"),
    [
        ("deliver", "founder", "answered"),
        ("revise", "founder", "answered"),
        ("deliver", "no_questions", "default_taken"),
    ],
)
def test_the_revision_answer_is_recorded_then_mirrored(
    tmp_path: Path, answer: str, source: str, resolution: str
) -> None:
    root, run_id, run_dir = _revision_run(tmp_path)
    proc = h.run(REVISION, "--dir", str(run_dir), "--answer", answer, "--source", source)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    mirror = json.loads((run_dir / "handoff" / run_id / "revision_answer.json").read_text())
    cur = h.ledger(root, run_id)["gates"]["ms_revision"]["current"]
    assert (cur["answer_id"], cur["resolution"]) == (mirror["answer"], resolution)


def test_a_refused_revision_answer_writes_neither(tmp_path: Path) -> None:
    root, run_id, run_dir = _revision_run(tmp_path)
    before = h.snapshot(root, run_id)
    # A founder who asked not to be asked takes the default, which is to deliver.
    proc = h.run(REVISION, "--dir", str(run_dir), "--answer", "revise", "--source", "no_questions")
    assert proc.returncode == 1 and _out(proc)["code"] == "DEFAULT_REASON_INVALID"
    assert not (run_dir / "handoff" / run_id / "revision_answer.json").exists()
    assert h.snapshot(root, run_id) == before


# --- ledger mode: cap-table's freeform blockers ---------------------------------------------------


def _freeform_run(tmp: Path) -> tuple[Path, str, Path, list[str]]:
    root, run_id, run_dir = h.start_bound(tmp, "cap-table")
    xlsx = goldens.ct_workbook(run_dir)
    (run_dir / "inputs.json").write_text(json.dumps({**goldens.CT_INPUTS, "metadata": {"run_id": run_id}}))
    argv = [str(EXTRACT), "--mode=freeform-emit", "--xlsx", str(xlsx), "--dir", str(run_dir), "--run-id", run_id]
    return root, run_id, run_dir, argv


def test_a_remaining_blocker_opens_its_gate_and_the_answer_records_it(tmp_path: Path) -> None:
    root, run_id, run_dir, argv = _freeform_run(tmp_path)
    blocks = json.dumps(goldens.CT_NOTE_BLOCKS)
    proc = subprocess.run([sys.executable, *argv], input=blocks, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert out["ok"] is False and out["gates"] == {"recorded": [], "opened": ["ct_lane3_blocker.0.interest_rate_type"]}
    st = h.status(root, run_id)
    assert (st["status"], st["waiting_on"]) == ("waiting", "ct_lane3_blocker.0.interest_rate_type")
    answered = [*argv, "--answer", "0.interest_rate_type=fixed_numeric_simple"]
    proc = subprocess.run([sys.executable, *answered], input=blocks, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert _out(proc)["gates"]["recorded"] == ["ct_lane3_blocker.0.interest_rate_type"]
    cur = h.ledger(root, run_id)["gates"]["ct_lane3_blocker.0.interest_rate_type"]["current"]
    assert (cur["answer_id"], cur["value"]) == ("stated", "fixed_numeric_simple")
    assert h.status(root, run_id)["status"] == "running"
    assert (run_dir / "instruments.json").is_file()


def test_an_answer_the_mapper_rejects_is_not_recorded(tmp_path: Path) -> None:
    root, run_id, run_dir, argv = _freeform_run(tmp_path)
    bad = [*argv, "--answer", "0.interest_rate_type=weekly_compound"]
    proc = subprocess.run(
        [sys.executable, *bad], input=json.dumps(goldens.CT_NOTE_BLOCKS), capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert _out(proc)["gates"]["recorded"] == []
    entry = h.ledger(root, run_id)["gates"]["ct_lane3_blocker.0.interest_rate_type"]
    assert entry["state"] == "open" and entry["current"] is None


# --- founder_context init -------------------------------------------------------------------------


def _init(
    root: Path, run_id: str, *, name: str = "Example Co", stage: str = "seed", extra: tuple[str, ...] = ()
) -> Any:
    return h.run(
        FOUNDER_CONTEXT,
        "init",
        "--company-name",
        name,
        "--stage",
        stage,
        "--sector",
        "fintech",
        "--geography",
        "US",
        "--artifacts-root",
        str(root),
        "--run-id",
        run_id,
        *extra,
    )


def _init_as(root: Path, run_id: str, skill: str, **kw: Any) -> Any:
    return _init(root, run_id, extra=("--skill", skill), **kw)


def _answer_basics(root: Path, run_id: str, stage: str = "seed") -> None:
    proc = h.record(
        root,
        run_id,
        "answer",
        "--gate",
        "ctx_basics.company_name",
        "--answer-id",
        "different",
        "--value",
        "Example Co",
        "--gate",
        "ctx_basics.stage",
        "--answer-id",
        stage,
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "use_derived",
        "--value",
        "fintech",
        "--gate",
        "ctx_basics.geography",
        "--answer-id",
        "different",
        "--value",
        "US",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_init_with_a_ledger_waits_for_every_field(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "financial-model-review")
    proc = _init_as(root, run_id, "financial-model-review")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    out = _out(proc)
    assert [n["gate"] for n in out["needs_input"]] == [
        f"ctx_basics.{f}" for f in ("company_name", "stage", "sector", "geography")
    ]
    assert not list(root.glob("founder-context-*.json"))
    assert h.status(root, run_id)["status"] == "waiting"


def test_init_refuses_a_typed_value_that_differs_from_the_record(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "financial-model-review")
    _answer_basics(root, run_id)
    proc = _init_as(root, run_id, "financial-model-review", stage="series-a")
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    proc = _init_as(root, run_id, "financial-model-review", name="Other Co")
    assert proc.returncode == 1 and _out(proc)["mismatches"][0]["field"] == "company_name"
    assert not list(root.glob("founder-context-*.json"))
    proc = _init_as(root, run_id, "financial-model-review")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (root / "founder-context-example-co.json").is_file()


def test_init_needs_the_specific_stage_after_series_b_plus(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "deck-review")
    _answer_basics(root, run_id, stage="series_b_plus")
    proc = _init_as(root, run_id, "deck-review", stage="series-c")
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ctx_stage_detail"
    assert h.record(root, run_id, "answer", "--gate", "ctx_stage_detail", "--answer-id", "series_c").returncode == 0
    assert _init_as(root, run_id, "deck-review", stage="series-b").returncode == 1
    assert _init_as(root, run_id, "deck-review", stage="series-c").returncode == 0


def test_init_refuses_a_finished_run_or_another_skills_run(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "deck-review")
    _answer_basics(root, run_id)
    proc = _init(root, run_id, extra=("--skill", "cap-table"))
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    sys.path.append(str(h.SHARED))
    import _run_status  # type: ignore[import-not-found]

    _run_status.update(_run_status.run_paths(str(root), run_id), _run_status.mark_complete)
    proc = _init_as(root, run_id, "deck-review")
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert not list(root.glob("founder-context-*.json"))


def test_init_with_a_ledger_needs_the_skill(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "deck-review")
    _answer_basics(root, run_id)
    proc = _init(root, run_id)
    assert proc.returncode == 2 and _out(proc)["code"] == "USAGE"
    assert not list(root.glob("founder-context-*.json"))


def test_init_with_a_run_id_and_no_ledger_is_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    proc = _init(root, "20261007T090000Z-0c0c0c")
    assert proc.returncode == 0, proc.stderr
    assert not (root / "runs").exists()


def test_re_emitting_an_answered_stage_gate_mirrors_the_ledger(tmp_path: Path) -> None:
    """A second emit of a gate the ledger has answered writes the answered state, and asks nothing."""
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert _emit(run_dir, run_id).returncode == 0
    assert _answer(run_dir, "Looks right").returncode == 0
    proc = _emit(run_dir, run_id)
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert "needs_input" not in out and out["answered"]["answer"] == "Looks right"
    mirror = json.loads((run_dir / "gate_state.json").read_text())
    assert (mirror["answer"], mirror["answer_source"]) == ("Looks right", "founder")
    _mirror_matches(root, run_id, run_dir)
    assert h.status(root, run_id)["status"] == "running"


def test_a_recorded_blocker_answer_is_applied_on_the_next_pass(tmp_path: Path) -> None:
    """The ledger holds the founder's blocker answer: a later pass without `--answer` still writes the files."""
    root, run_id, run_dir, argv = _freeform_run(tmp_path)
    blocks = json.dumps(goldens.CT_NOTE_BLOCKS)
    answered = [*argv, "--answer", "0.interest_rate_type=fixed_numeric_simple"]
    assert subprocess.run([sys.executable, *answered], input=blocks, capture_output=True, text=True).returncode == 0
    (run_dir / "instruments.json").unlink()
    proc = subprocess.run([sys.executable, *argv], input=blocks, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert out["ok"] is True and out["gates"]["opened"] == []
    note = json.loads((run_dir / "instruments.json").read_text())["convertible_notes"][0]
    assert note["interest_rate_type"] == "fixed_numeric_simple"


def _two_note_run(tmp: Path, *, with_type: bool = False) -> tuple[Path, str, Path, list[str]]:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    root, run_id, run_dir = h.start_bound(tmp, "cap-table")
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "N"
    ws.append(["Investor", "Principal", "Interest"])
    ws.append(["Lender One", 4321, "none" if with_type else None])
    ws.append(["Lender Two", 8765, "none" if with_type else None])
    wb.save(run_dir / "n.xlsx")
    (run_dir / "inputs.json").write_text(json.dumps({**goldens.CT_INPUTS, "metadata": {"run_id": run_id}}))
    argv = [str(EXTRACT), "--mode=freeform-emit", "--xlsx", str(run_dir / "n.xlsx"), "--dir", str(run_dir)]
    return root, run_id, run_dir, [*argv, "--run-id", run_id]


def _note_blocks(order: tuple[int, int], *, with_type: bool = False) -> str:
    roles = {"A": "investor_name", "B": "principal", **({"C": "interest_rate_type"} if with_type else {})}
    rows = {0: "A2:C2", 1: "A3:C3"}
    return json.dumps(
        {
            "blocks": [
                {"block_type": "notes_block", "sheet": "N", "cell_range": rows[i], "column_role_map": roles}
                for i in order
            ]
        }
    )


def _emit_freeform(argv: list[str], blocks: str, *answers: str) -> dict[str, Any]:
    extra = [a for pair in (("--answer", x) for x in answers) for a in pair]
    proc = subprocess.run([sys.executable, *argv, *extra], input=blocks, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return _out(proc)


_TWO_ANSWERS = ("0.interest_rate_type=fixed_numeric_simple", "1.interest_rate_type=statutory_ita_section_3j")


def test_an_unchanged_sheet_reuses_each_recorded_answer(tmp_path: Path) -> None:
    root, run_id, run_dir, argv = _two_note_run(tmp_path)
    assert _emit_freeform(argv, _note_blocks((0, 1)), *_TWO_ANSWERS)["ok"] is True
    out = _emit_freeform(argv, _note_blocks((0, 1)))
    assert out["ok"] is True
    notes = json.loads((run_dir / "instruments.json").read_text())["convertible_notes"]
    assert [n["interest_rate_type"] for n in notes] == ["fixed_numeric_simple", "statutory_ita_section_3j"]


def test_a_reordered_sheet_asks_again_rather_than_cross_applying(tmp_path: Path) -> None:
    root, run_id, run_dir, argv = _two_note_run(tmp_path)
    assert _emit_freeform(argv, _note_blocks((0, 1)), *_TWO_ANSWERS)["ok"] is True
    (run_dir / "instruments.json").unlink()
    out = _emit_freeform(argv, _note_blocks((1, 0)))
    assert out["ok"] is False, "an answer for one note was applied to the other"
    assert not (run_dir / "instruments.json").exists()
    entry = h.ledger(root, run_id)["gates"]["ct_lane3_blocker.0.interest_rate_type"]
    assert entry["state"] == "open" and entry["supersessions"] == 1
    assert [e["event"] for e in entry["history"]][-2:] == ["superseded", "reopened"]
    assert h.status(root, run_id)["status"] == "waiting"


def test_a_sheet_that_now_supplies_the_value_wins_over_a_recorded_answer(tmp_path: Path) -> None:
    first = _two_note_run(tmp_path)
    assert _emit_freeform(first[3], _note_blocks((0, 1)), *_TWO_ANSWERS)["ok"] is True
    # The same run, its sheet edited to state the interest type itself.
    root, run_id, run_dir, argv = first
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "N"
    ws.append(["Investor", "Principal", "Interest"])
    ws.append(["Lender One", 4321, "none"])
    ws.append(["Lender Two", 8765, "none"])
    wb.save(run_dir / "n.xlsx")
    out = _emit_freeform(argv, _note_blocks((0, 1), with_type=True))
    assert out["ok"] is True
    notes = json.loads((run_dir / "instruments.json").read_text())["convertible_notes"]
    assert [n["interest_rate_type"] for n in notes] == ["none", "none"]
