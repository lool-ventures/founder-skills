"""`run_status.py`: a run's status file is created, resumed and finished only on the run's own terms.

What a host reads is `runs/<id>/run_status.json`, so the properties held here are the ones a host relies
on: `start` never writes another run's status (an id in use or finished is refused print-only, a
malformed id writes nothing), host request lines are validated before anything is written, a waiting run
resumes once under concurrent starts, and `deliverables_status` says whether more pages are coming.
Ids and names are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load("_run_status")

RID = "20261007T090000Z-aa11bb"


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _root(tmp: Path) -> Path:
    root = tmp / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _set_state(root: Path, run_id: str, state: str, code: str) -> None:
    paths = rs.run_paths(str(root), run_id)
    rs.update(paths, lambda st: rs.set_state(st, state, code))


# --- start -----------------------------------------------------------------------------------------


def test_a_fresh_start_writes_every_field_and_a_ledger(tmp_path: Path) -> None:
    root = _root(tmp_path)
    proc = h.start(root, "market-sizing")
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert out["resume"] == 0 and out["status"] == "running" and rs.valid_run_id(out["run_id"])
    st = h.status(root, out["run_id"])
    assert list(st) == list(rs.FIELDS)
    assert st["status"] == "running" and st["code"] == "RUNNING" and st["revision"] == 0
    assert st["deliverables_status"] is None and st["coaching"] is None and st["deliverables"] is None
    assert st["plugin_version"] and st["shared_scripts_dir_shell"] == str(h.SHARED)
    led = h.ledger(root, out["run_id"])
    assert led["schema"] == "founder-skills/gates" and led["skill"] == "market-sizing"


def test_the_host_run_id_is_used_and_the_environment_one_is_not(tmp_path: Path) -> None:
    root = _root(tmp_path)
    proc = h.run(
        h.RUN_STATUS,
        "start",
        "--skill",
        "ic-sim",
        "--artifacts-root",
        str(root),
        stdin=f"FS_HOST_RUN_ID={RID}\n",
        env={"RUN_ID": "20261007T000000Z-ffffff"},
    )
    assert proc.returncode == 0, proc.stderr
    assert _out(proc)["run_id"] == RID
    assert sorted(os.listdir(root / "runs")) == [RID]


@pytest.mark.parametrize("bad", ["../x", "a/r2", ".hidden", "x" * 65])
def test_a_malformed_run_id_writes_nothing(tmp_path: Path, bad: str) -> None:
    root = _root(tmp_path)
    proc = h.start(root, "deck-review", f"FS_HOST_RUN_ID={bad}\n")
    assert proc.returncode == 1
    assert _out(proc)["code"] == "RUN_ID_MALFORMED"
    assert proc.stderr.strip()
    assert not (root / "runs").exists()
    assert list(tmp_path.rglob("*.json")) == []


def _refused_print_only(root: Path, run_id: str, skill: str, code: str) -> None:
    before = h.status_path(root, run_id).read_bytes()
    refusals = root / "runs" / run_id / "start_refusals.jsonl"
    lines_before = refusals.read_text().count("\n") if refusals.exists() else 0
    proc = h.start(root, skill, f"FS_HOST_RUN_ID={run_id}\n")
    assert proc.returncode == 1, proc.stdout
    assert _out(proc)["code"] == code
    assert proc.stderr.strip()
    assert h.status_path(root, run_id).read_bytes() == before, "a refusal changed the run's status"
    assert refusals.read_text().count("\n") == lines_before + 1


def test_a_running_id_is_in_use(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n")
    _refused_print_only(root, run_id, "market-sizing", "RUN_ID_IN_USE")


def test_a_waiting_id_of_another_skill_is_in_use(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "market-sizing", lines=f"FS_HOST_RUN_ID={RID}\n")
    assert h.record(root, run_id, "open", "--gate", "ctx_basics.stage").returncode == 0
    assert h.status(root, run_id)["status"] == "waiting"
    _refused_print_only(root, run_id, "ic-sim", "RUN_ID_IN_USE")


@pytest.mark.parametrize(("state", "code"), [("complete", "COMPLETE"), ("refused", "FOUNDER_DECLINED")])
def test_a_finished_id_is_refused_and_its_status_stays_byte_identical(tmp_path: Path, state: str, code: str) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "deck-review", f"FS_HOST_RUN_ID={RID}\n")
    _set_state(root, run_id, state, code)
    _refused_print_only(root, run_id, "deck-review", "RUN_ID_FINISHED")
    _refused_print_only(root, run_id, "deck-review", "RUN_ID_FINISHED")


@pytest.mark.parametrize(
    "line",
    [
        "FS_HOST_ANSWER no_such_gate=x",
        "FS_HOST_ANSWER ms_methodology=looks_good",  # another skill's gate
        "FS_HOST_ANSWER ctx_basics.stage=series_q",  # not an option
        "FS_HOST_ANSWER ctx_basics.rank=seed",  # not an instance
        "FS_HOST_ANSWER fmr_extracted_values=has_corrections",  # not answerable ahead
        "FS_HOST_VALUE ctx_basics.stage=seed | Seed",  # a value on an option that takes none
        "FS_HOST_ANSWER ctx_basics.sector=different",  # a value option needs FS_HOST_VALUE
        "FS_HOST_VALUE ctx_basics.sector=different",  # no ` | value`
        "FS_HOST_FROBNICATE ctx_basics.stage=seed",  # unknown keyword
        "FS_HOST_NOTE ctx_basics.stage=a note with no answer",
        "FS_HOST_ANSWER ctx_basics.stage/x=seed",
    ],
)
def test_a_bad_line_refuses_a_fresh_run_and_a_retry_succeeds(tmp_path: Path, line: str) -> None:
    root = _root(tmp_path)
    proc = h.start(root, "deck-review", f"FS_HOST_RUN_ID={RID}\n{line}\n")
    assert proc.returncode == 1, proc.stdout
    out = _out(proc)
    assert out["code"] == "PRE_ANSWER_INVALID" and out["invalid"][0]["line"] == line
    st = h.status(root, RID)
    assert st["status"] == "refused" and st["code"] == "PRE_ANSWER_INVALID"
    assert not h.ledger_path(root, RID).exists()
    retry = h.start(root, "deck-review", f"FS_HOST_RUN_ID={RID}\nFS_HOST_ANSWER ctx_basics.stage=seed\n")
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert h.status(root, RID)["status"] == "running"
    assert (root / "runs" / RID / "run_status.json.replaced-1").is_file()


def test_lines_that_are_not_host_lines_are_ignored_and_an_empty_request_is_fine(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert h.start(root, "cap-table", "").returncode == 0
    proc = h.start(root, "cap-table", "Please review this.\n  FS_HOST_ANSWER  \nRUN_ID=whatever\n")
    assert proc.returncode == 1  # "  FS_HOST_ANSWER  " is a malformed host line, never silently dropped
    proc = h.start(root, "cap-table", "Please review this.\nRUN_ID=whatever\n")
    assert proc.returncode == 0, proc.stdout


def test_a_note_with_an_apostrophe_survives(tmp_path: Path) -> None:
    root = _root(tmp_path)
    note = "the founder's own figure, it's right"
    lines = f"FS_HOST_RUN_ID={RID}\nFS_HOST_ANSWER ctx_basics.stage=seed\nFS_HOST_NOTE ctx_basics.stage={note}\n"
    assert h.start(root, "deck-review", lines).returncode == 0
    assert h.ledger(root, RID)["pre_answers"]["ctx_basics.stage"]["note"] == note


def _waiting_run(tmp: Path, lines: str = "") -> tuple[Path, str]:
    root, run_id, _rd = h.start_bound(tmp, "market-sizing", lines=f"FS_HOST_RUN_ID={RID}\n{lines}")
    opened = h.record(root, run_id, "open", "--gate", "ctx_basics.sector", "--gate", "ctx_basics.geography")
    assert opened.returncode == 0, opened.stderr
    assert h.status(root, run_id)["status"] == "waiting"
    return root, run_id


def test_a_waiting_run_of_the_same_skill_resumes(tmp_path: Path) -> None:
    root, run_id = _waiting_run(tmp_path)
    proc = h.start(
        root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\nFS_HOST_VALUE ctx_basics.sector=different | fintech\n"
    )
    assert proc.returncode == 0, proc.stderr
    out = _out(proc)
    assert out["resume"] == 1 and out["resume_step"] == "1"
    assert h.status(root, run_id)["status"] == "running"


def test_a_resume_that_brings_no_answer_stays_waiting_and_can_be_sent_again(tmp_path: Path) -> None:
    """A retried resume, a line for another question or a crash after `start` must never lock the id: the run
    stays `waiting`, opening its question again keeps it so, and the same resume is accepted again."""
    root, run_id = _waiting_run(tmp_path)
    for n in (1, 2):
        proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\n")
        assert proc.returncode == 0 and _out(proc)["resume"] == 1, proc.stdout + proc.stderr
        assert h.status(root, run_id)["status"] == "waiting", n
        opened = h.record(root, run_id, "open", "--gate", "ctx_basics.sector")
        assert opened.returncode == 0, opened.stderr
        assert h.status(root, run_id)["status"] == "waiting", n
    proc = h.start(
        root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\nFS_HOST_VALUE ctx_basics.sector=different | fintech\n"
    )
    assert proc.returncode == 0 and h.status(root, run_id)["status"] == "running"
    opened = h.record(root, run_id, "open", "--gate", "ctx_basics.sector")
    assert opened.returncode == 0 and _out(opened)["applied"] == "pre_answer"


def test_a_running_status_with_an_open_question_is_derived_waiting_on_the_next_transaction(tmp_path: Path) -> None:
    """The status a crash or an older resume left `running` beside an open question is corrected by the next
    script that reads the ledger, so the run can be resumed."""
    root, run_id = _waiting_run(tmp_path)
    _set_state(root, run_id, "running", "RUNNING")
    before = h.ledger_path(root, run_id).read_bytes()
    # The same questions as before: the ledger does not change, so only the status re-derivation can fix it.
    opened = h.record(root, run_id, "open", "--gate", "ctx_basics.sector", "--gate", "ctx_basics.geography")
    assert h.ledger_path(root, run_id).read_bytes() == before
    assert opened.returncode == 0, opened.stderr
    assert h.status(root, run_id)["status"] == "waiting"
    assert h.start(root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\n").returncode == 0


def test_a_bad_line_on_resume_is_print_only(tmp_path: Path) -> None:
    root, run_id = _waiting_run(tmp_path)
    before = h.snapshot(root, run_id)
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ctx_basics.stage=nope\n")
    assert proc.returncode == 1 and _out(proc)["code"] == "PRE_ANSWER_INVALID"
    assert h.snapshot(root, run_id) == before


def test_resume_merges_pre_answers_per_gate(tmp_path: Path) -> None:
    first = "FS_HOST_ANSWER ctx_basics.stage=seed\nFS_HOST_VALUE ctx_basics.sector=different | fintech\n"
    root, run_id = _waiting_run(tmp_path, first)
    # The sector pre-answer was applied when `open` ran; the stage one is stored, its gate not opened.
    led = h.ledger(root, run_id)
    assert led["gates"]["ctx_basics.sector"]["state"] == "answered"
    again = (
        f"FS_HOST_RUN_ID={run_id}\n"
        "FS_HOST_ANSWER ctx_basics.stage=series_a\n"  # different, gate not answered -> replaced
        "FS_HOST_VALUE ctx_basics.sector=different | health\n"  # different, gate answered -> ignored
        "FS_HOST_VALUE ctx_basics.geography=different | EU\n"  # new -> added
    )
    assert h.start(root, "market-sizing", again).returncode == 0
    led = h.ledger(root, run_id)
    assert led["pre_answers"]["ctx_basics.stage"]["option_id"] == "series_a"
    assert led["pre_answers"]["ctx_basics.sector"]["value"] == "fintech"
    assert led["pre_answers"]["ctx_basics.geography"]["value"] == "EU"
    # The stage question was never opened: its lines' events are on the line's own record, and no gate entry
    # (never a `state: null` one) exists for it.
    assert "ctx_basics.stage" not in led["gates"]
    events = [e["event"] for e in led["pre_answers"]["ctx_basics.stage"]["events"]]
    assert events == ["pre_answer_stored", "pre_answer_superseded"]
    notices = h.status(root, run_id)["notices"]
    assert [n["gate"] for n in notices] == ["ctx_basics.sector"]
    # An identical line is a no-op.
    before = h.ledger_path(root, run_id).read_bytes()
    _set_state(root, run_id, "waiting", "GATE_WAITING")
    same = f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ctx_basics.stage=series_a\n"
    assert h.start(root, "market-sizing", same).returncode == 0
    assert h.ledger_path(root, run_id).read_bytes() == before


def _concurrent_starts(root: Path, lines: str, skill: str) -> list[subprocess.CompletedProcess[str]]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FS_HOST_")}
    env["FOUNDER_SKILLS_LOCK_PAUSE_S"] = "0.4"
    cmd = [sys.executable, str(h.RUN_STATUS), "start", "--skill", skill, "--artifacts-root", str(root)]
    procs = [
        subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for _ in range(2)
    ]
    outs = []
    for p in procs:
        out, err = p.communicate(lines, timeout=30)
        outs.append(subprocess.CompletedProcess(cmd, p.returncode, out, err))
    return outs


def test_two_starts_on_a_fresh_id_create_it_once(tmp_path: Path) -> None:
    root = _root(tmp_path)
    results = _concurrent_starts(root, f"FS_HOST_RUN_ID={RID}\n", "deck-review")
    assert sorted(r.returncode for r in results) == [0, 1]
    refused = next(r for r in results if r.returncode == 1)
    assert _out(refused)["code"] == "RUN_ID_IN_USE"


def test_two_starts_on_a_waiting_id_resume_it_once(tmp_path: Path) -> None:
    root, run_id = _waiting_run(tmp_path)
    results = _concurrent_starts(
        root, f"FS_HOST_RUN_ID={run_id}\nFS_HOST_VALUE ctx_basics.sector=different | fintech\n", "market-sizing"
    )
    assert sorted(r.returncode for r in results) == [0, 1]
    assert _out(next(r for r in results if r.returncode == 0))["resume"] == 1
    assert _out(next(r for r in results if r.returncode == 1))["code"] == "RUN_ID_IN_USE"


@pytest.mark.skipif(shutil.which("dash") is None and not Path("/bin/sh").exists(), reason="no POSIX sh")
def test_start_runs_from_a_posix_shell_heredoc_under_the_c_locale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sh = shutil.which("dash") or "/bin/sh"
    script = (
        f'"{sys.executable}" "{h.RUN_STATUS}" start --skill deck-review --artifacts-root "{root}" <<\'FS_HOST_EOF\'\n'
        f"FS_HOST_RUN_ID={RID}\n"
        "FS_HOST_ANSWER ctx_basics.stage=seed\n"
        "FS_HOST_NOTE ctx_basics.stage=the deck's title slide says so\n"
        "FS_HOST_EOF\n"
    )
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "HOME": str(tmp_path)}
    proc = subprocess.run([sh, "-c", script], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.ledger(root, RID)["pre_answers"]["ctx_basics.stage"]["note"] == "the deck's title slide says so"


# --- bind ------------------------------------------------------------------------------------------


def test_bind_is_idempotent_for_the_same_slug_and_writes_the_run_ref(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim")
    ref = json.loads((run_dir / "handoff" / run_id / "run_ref.json").read_text())
    assert ref == {
        "schema": "founder-skills/run_ref",
        "schema_version": 1,
        "run_id": run_id,
        "skill": "ic-sim",
        "ledger_rel": f"runs/{run_id}/gates.json",
    }
    assert h.bind(root, run_id, run_dir, "example-co").returncode == 0
    st = h.status(root, run_id)
    assert st["slug"] == "example-co" and st["mode"] == "full" and st["run_dir_shell"] == str(run_dir)
    assert st["scripts_dir_shell"] == str(h.SKILLS / "ic-sim" / "scripts")


def test_bind_with_another_slug_is_print_only(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim")
    before = h.status_path(root, run_id).read_bytes()
    proc = h.bind(root, run_id, run_dir.parent / "ic-sim-other-co", "other-co")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_IN_USE"
    assert h.status_path(root, run_id).read_bytes() == before


def test_bind_without_a_status_is_run_not_found(tmp_path: Path) -> None:
    root = _root(tmp_path)
    proc = h.bind(root, RID, root / "ic-sim-example-co", "example-co")
    assert proc.returncode == 2 and _out(proc)["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize(
    ("suffix", "mode"),
    [("-quickcheck", "quick_check"), ("-fastassess", "fast_assess"), ("-concise", "concise"), ("", "full")],
)
def test_bind_reads_the_mode_from_the_run_dir_suffix(tmp_path: Path, suffix: str, mode: str) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "cap-table", suffix=suffix)
    assert h.status(root, run_id)["mode"] == mode


def test_show_distinguishes_no_run_from_an_unreachable_registry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    proc = h.run(h.RUN_STATUS, "show", "--run-id", RID, "--artifacts-root", str(root))
    assert proc.returncode == 2 and _out(proc)["code"] == "RUN_NOT_FOUND"


# --- finish ----------------------------------------------------------------------------------------


def _artifact(run_dir: Path, run_id: str, name: str = "fast_assess_only.json") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / name
    path.write_text(json.dumps({"metadata": {"run_id": run_id}}), encoding="utf-8")
    return path


def _finish(root: Path, run_id: str, *args: str) -> subprocess.CompletedProcess[str]:
    return h.run(h.RUN_STATUS, "finish", "--run-id", run_id, "--artifacts-root", str(root), *args)


@pytest.mark.parametrize("mode", ["quick_check", "fast_assess", "concise"])
def test_finish_completes_with_its_output_and_the_pages_are_final(tmp_path: Path, mode: str) -> None:
    suffix = {"quick_check": "-quickcheck", "fast_assess": "-fastassess", "concise": "-concise"}[mode]
    root, run_id, run_dir = h.start_bound(tmp_path, "cap-table", suffix=suffix)
    out = _artifact(run_dir, run_id)
    proc = _finish(root, run_id, "--mode", mode, "--output", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert (st["status"], st["code"], st["deliverables_status"], st["mode"]) == ("complete", "COMPLETE", "final", mode)


def test_finish_refuses_another_runs_output(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "financial-model-review", suffix="-quickcheck")
    out = _artifact(run_dir, "20260101T000000Z-000000")
    before = h.status_path(root, run_id).read_bytes()
    proc = _finish(root, run_id, "--mode", "quick_check", "--output", str(out))
    assert proc.returncode == 1 and proc.stderr.strip()
    assert h.status_path(root, run_id).read_bytes() == before


def test_finish_with_an_open_gate_waits_on_it(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "cap-table", suffix="-fastassess")
    assert h.record(root, run_id, "open", "--gate", "ctx_basics.stage").returncode == 0
    proc = _finish(root, run_id, "--mode", "fast_assess", "--output", str(_artifact(run_dir, run_id)))
    assert proc.returncode == 10, proc.stdout
    assert _out(proc)["blocked_by_gate"] == "ctx_basics.stage"
    assert h.status(root, run_id)["status"] == "waiting"


def test_rule_lookup_finishes_with_no_output(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "cap-table")
    assert _finish(root, run_id, "--mode", "rule_lookup", "--output", "x.json").returncode == 1
    proc = _finish(root, run_id, "--mode", "rule_lookup", "--lookup-status", "answered")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.status(root, run_id)["deliverables_status"] == "final"


def test_an_escalated_lookup_waits_on_the_fact(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "cap-table")
    proc = _finish(root, run_id, "--mode", "rule_lookup", "--lookup-status", "escalate")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    out = _out(proc)
    assert out["blocked_by_gate"] == "ct_rule_lookup_fact"
    assert out["needs_input"][0]["gate"] == "ct_rule_lookup_fact"
    st = h.status(root, run_id)
    assert st["status"] == "waiting" and st["waiting_on"] == "ct_rule_lookup_fact"
    answered = h.record(root, run_id, "answer", "--gate", "ct_rule_lookup_fact", "--answer-id", "unknown")
    assert answered.returncode == 0, answered.stdout + answered.stderr
    proc = _finish(root, run_id, "--mode", "rule_lookup", "--lookup-status", "escalate")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.status(root, run_id)["status"] == "complete"


# --- deliverables_status ---------------------------------------------------------------------------


def test_deliverables_final_needs_a_complete_run_and_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "deck-review")
    cmd = ["deliverables", "--run-id", run_id, "--artifacts-root", str(root), "--final"]
    refused = h.run(h.RUN_STATUS, *cmd)
    assert refused.returncode == 1 and _out(refused)["code"] == "RUN_NOT_COMPLETE"
    paths = rs.run_paths(str(root), run_id)
    rs.update(paths, rs.mark_complete)
    assert h.status(root, run_id)["deliverables_status"] == "pending"
    for _ in range(2):
        assert h.run(h.RUN_STATUS, *cmd).returncode == 0
        assert h.status(root, run_id)["deliverables_status"] == "final"


@pytest.mark.parametrize(
    ("skill", "pages", "expected"),
    [
        ("deck-review", (), "pending"),
        ("deck-review", ("report_html",), "final"),
        ("competitive-positioning", ("report_html",), "pending"),
        ("competitive-positioning", ("report_html", "explorer_html"), "final"),
        ("financial-model-review", (), "final"),
        ("cap-table", (), "final"),
    ],
)
def test_completion_names_whether_pages_are_still_coming(
    tmp_path: Path, skill: str, pages: tuple[str, ...], expected: str
) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, skill)
    paths = rs.run_paths(str(root), run_id)
    page = run_dir / "page.html"
    page.write_text("<html><head></head></html>", encoding="utf-8")
    rs.update(paths, rs.mark_complete)
    for key in pages:
        rs.add_deliverable(paths, key, str(page), rs.file_sha256(str(page)), "visualize.py")
    assert h.status(root, run_id)["deliverables_status"] == expected
    if expected == "final" and pages:
        rs.add_deliverable(paths, pages[0], str(page), rs.file_sha256(str(page)), "visualize.py")
        assert h.status(root, run_id)["deliverables_status"] == "final"


def test_a_page_from_an_earlier_revision_does_not_count(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    paths = rs.run_paths(str(root), run_id)
    page = run_dir / "report.html"
    page.write_text("<html><head></head></html>", encoding="utf-8")
    rs.add_deliverable(paths, "report_html", str(page), rs.file_sha256(str(page)), "visualize.py")

    def bump(st: dict[str, Any]) -> None:
        st["revision"] = 1
        rs.mark_complete(st)

    rs.update(paths, bump)
    assert h.status(root, run_id)["deliverables_status"] == "pending"


# --- fixed tables and the write path -----------------------------------------------------------------


def test_resumable_is_true_only_where_a_separate_process_resumed() -> None:
    # Only `cli_artifacts_root` was shown to resume from a new process over the same root; every other
    # surface stays conservative until it is measured.
    assert rs.RESUMABLE_BY_SURFACE == {
        "cli": "same_session",
        "cli_artifacts_root": True,
        "cowork_local": "same_session",
        "cowork_cloud": "same_session",
    }
    assert [k for k, v in rs.RESUMABLE_BY_SURFACE.items() if v is True] == ["cli_artifacts_root"]


@pytest.mark.parametrize(
    ("env", "surface", "expected"),
    [
        ({}, "cli", "same_session"),
        ({"COWORK_ARTIFACTS_ROOT": "<root>"}, "cli_artifacts_root", True),
        ({"CLAUDE_CODE_REMOTE": "true"}, "cowork_cloud", "same_session"),
    ],
)
def test_waiting_status_says_resumable_per_surface(
    tmp_path: Path, env: dict[str, str], surface: str, expected: bool | str
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    env = {k: (str(root) if v == "<root>" else v) for k, v in env.items()}
    proc = h.run(h.RUN_STATUS, "start", "--skill", "deck-review", "--artifacts-root", str(root), env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    run_id = json.loads(proc.stdout)["run_id"]
    assert h.ledger(root, run_id)["surface"] == surface
    assert h.bind(root, run_id, root / "deck-review-example-co", "example-co").returncode == 0
    assert h.record(root, run_id, "open", "--gate", "ctx_basics.stage").returncode == 0
    st = h.status(root, run_id)
    assert st["status"] == "waiting"
    assert st["resumable"] == expected


@pytest.mark.parametrize(
    ("cwd", "env", "surface"),
    [
        ("/home/claude", {"CLAUDE_CODE_REMOTE": "true"}, "cowork_cloud"),
        ("/sessions/abc/mnt/outputs", {}, "cowork_local"),
        ("/sessions/abc", {}, "cowork_local"),
        ("/tmp/x", {"COWORK_ARTIFACTS_ROOT": "/tmp/x/artifacts"}, "cli_artifacts_root"),
        ("/tmp/x", {}, "cli"),
    ],
)
def test_surface_detection(cwd: str, env: dict[str, str], surface: str) -> None:
    assert rs.surface(cwd, env) == surface


def _instances(g: dict[str, Any]) -> list[str | None]:
    inst = g["instances"]
    if inst is None:
        return [None]
    return list(inst["static"]) if inst.get("static") is not None else ["0.example_field"]


def test_every_gate_question_reaches_the_status_founder_clean(tmp_path: Path) -> None:
    """Each registered question, rendered the way the status message and `needs_input` render it, with
    and without a known company name: no slot like `[Company]` or `<N>` survives, and nothing internal."""
    gates = _load("_gates")
    ft = _load("_founder_text")
    root = _root(tmp_path)
    (root / "founder-context-example-co.json").write_text(json.dumps({"company_name": "Example Co"}))
    paths = rs.run_paths(str(root), RID)
    slot = re.compile(r"<[^<>]+>|\[[^\[\]]+\]")
    for slug in (None, "example-co"):
        for gid, g in gates.GATES.items():
            skill = g["skill"] if g["skill"] != "shared" else "deck-review"
            ctx = gates.Ctx(paths, {"slug": slug, "skill": skill}, skill)
            for inst in _instances(g):
                labels = [gates.render_label(o, ctx) for o in gates.fixed_options(g, inst, skill)]
                for label in labels:
                    assert not slot.search(label), (gid, inst, label)
                    found = ft.scan(label)
                    assert found["enums"] == [] and found["filenames"] == [], (gid, inst, label, found)
                question = gates.render_question(g, inst, ctx)
                status: dict[str, Any] = {}
                rs.set_state(status, "waiting", "GATE_WAITING", question=question)
                for text in (question, status["message"]):
                    assert not slot.search(text), (gid, inst, text)
                    found = ft.scan(text)
                    assert found["enums"] == [] and found["filenames"] == [], (gid, inst, text, found)
    for code, template in rs.MESSAGES.items():
        found = ft.scan(template.replace("{question}", "Does this look right?"))
        assert found["enums"] == [] and found["filenames"] == [], (code, found)


def test_a_label_slot_is_filled_or_named_plainly(tmp_path: Path) -> None:
    gates = _load("_gates")
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.company_name"))
    option = out["needs_input"][0]["options"][0]
    assert option["id"] == "use_derived" and option["label"] == "Use derived"
    assert option["label_template"].startswith('Use "<name>"')
    labels = [o["label"] for g in h.status(root, run_id)["gates"] for o in g["options"]]
    assert not [x for x in labels if "<" in x or "[" in x]
    (root / "founder-context-example-co.json").write_text(json.dumps({"company_name": "Example Co"}))
    ctx = gates.Ctx(rs.run_paths(str(root), run_id), {"slug": "example-co"}, "deck-review")
    first = gates.fixed_options(gates.GATES["ctx_basics"], "company_name", "deck-review")[0]
    assert gates.render_label(first, ctx) == 'Use "Example Co" — as it appeared in the conversation / on the deck'


def test_before_bind_only_the_gates_every_mode_has_are_listed(tmp_path: Path) -> None:
    """Before `bind` the mode is unknown, so the list holds the gates common to every mode of the skill;
    `bind` completes it for the run dir's mode."""
    gates = _load("_gates")
    root = _root(tmp_path)
    run_id = h.start_ok(root, "financial-model-review")
    listed = {g["id"] for g in h.status(root, run_id)["gates"]}
    mine = [g for g in gates.GATES.values() if g["skill"] in ("financial-model-review", "shared")]
    every = {m for g in mine for m in g["modes"]}
    assert listed == {gid for gid, g in gates.GATES.items() if g in mine and every <= set(g["modes"])}
    assert "fmr_extracted_values" not in listed and "ctx_basics" in listed
    run_dir = root / "financial-model-review-example-co"
    assert h.bind(root, run_id, run_dir, "example-co").returncode == 0
    assert "fmr_extracted_values" in {g["id"] for g in h.status(root, run_id)["gates"]}
    root2 = _root(tmp_path / "ct")
    run_id2 = h.start_ok(root2, "cap-table")
    assert "ct_rule_lookup_fact" not in {g["id"] for g in h.status(root2, run_id2)["gates"]}


def test_the_company_name_fills_its_slot(tmp_path: Path) -> None:
    gates = _load("_gates")
    root = _root(tmp_path)
    (root / "founder-context-example-co.json").write_text(json.dumps({"company_name": "Example Co"}))
    ctx = gates.Ctx(rs.run_paths(str(root), RID), {"slug": "example-co"}, "cap-table")
    g = gates.GATES["ct_jurisdiction"]
    assert gates.render_question(g, None, ctx) == "What is Example Co's jurisdiction structure?"
    ctx = gates.Ctx(rs.run_paths(str(root), RID), {}, "cap-table")
    assert gates.render_question(g, None, ctx) == "What is the company's jurisdiction structure?"


def test_a_failed_replace_leaves_the_prior_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "run_status.json"
    rs.atomic_write_json(str(target), {"v": 1})
    before = target.read_bytes()

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        rs.atomic_write_json(str(target), {"v": 2})
    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["run_status.json"], "a temp file was left behind"


def test_the_lock_falls_back_to_a_lockfile_when_flock_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = rs.run_paths(str(tmp_path), RID)
    monkeypatch.setattr(rs, "_flock", lambda fd: False)
    with rs.run_lock(paths, create=True):
        assert Path(paths.lock + ".excl").exists()
        with rs.run_lock(paths):  # re-entrant within one process
            pass
    assert not Path(paths.lock + ".excl").exists()


def test_a_stale_fallback_lockfile_is_taken_over_and_a_live_one_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = rs.run_paths(str(tmp_path), RID)
    monkeypatch.setattr(rs, "_flock", lambda fd: False)
    os.makedirs(paths.run_root)
    marker = Path(paths.lock + ".excl")
    marker.write_text("1")
    os.utime(marker, (1, 1))
    with rs.run_lock(paths):
        pass
    marker.write_text("1")
    monkeypatch.setattr(rs, "LOCK_WAIT_S", 0.2)
    with pytest.raises(rs.RunStatusError) as e, rs.run_lock(paths):
        pass
    assert e.value.code == "LOCK_UNAVAILABLE"


def test_a_run_ref_whose_ledger_is_gone_is_ledger_missing(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    assert rs.locate_from_run_dir(str(run_dir), run_id).ledger == str(h.ledger_path(root, run_id))
    h.ledger_path(root, run_id).unlink()
    with pytest.raises(rs.RunStatusError) as e:
        rs.locate_from_run_dir(str(run_dir), run_id)
    assert e.value.code == "LEDGER_MISSING"
    assert rs.locate_from_run_dir(str(run_dir), "20260101T000000Z-000000") is None


# --- resume recipe, the full gate list, bind and finish guards -------------------------------------


def test_the_resume_recipe_is_the_resume_prompt_plus_the_new_answer(tmp_path: Path) -> None:
    """A host resumes with `resume_prompt` as the status printed it, then its answer for the waiting
    gate. The original lines come back first, so the last line for a key wins."""
    root, run_id, _rd = h.start_bound(
        tmp_path, "market-sizing", lines=f"FS_HOST_RUN_ID={RID}\nFS_HOST_ANSWER ctx_basics.stage=seed\n"
    )
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.stage", "--gate", "ctx_basics.sector"))
    assert out["applied_gates"] == ["ctx_basics.stage"]
    st = h.status(root, run_id)
    assert st["status"] == "waiting" and st["waiting_on"] == "ctx_basics.sector"
    first = st["resume_prompt"]
    request = first + "FS_HOST_VALUE ctx_basics.sector=different | fintech\n"
    proc = h.start(root, "market-sizing", request)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _out(proc)["resume"] == 1
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.sector"))
    assert out["applied_gates"] == ["ctx_basics.sector"]
    assert h.status(root, run_id)["status"] == "running"
    # A line repeating a different answer for the gate already answered stands refused, as a notice.
    _set_state(root, run_id, "waiting", "GATE_WAITING")
    proc = h.start(root, "market-sizing", first + "FS_HOST_ANSWER ctx_basics.stage=series_a\n")
    assert proc.returncode == 0, proc.stdout
    assert h.ledger(root, run_id)["gates"]["ctx_basics.stage"]["current"]["answer_id"] == "seed"
    assert [n["gate"] for n in h.status(root, run_id)["notices"]] == ["ctx_basics.stage"]


def test_within_one_request_the_last_line_for_a_key_wins(tmp_path: Path) -> None:
    root = _root(tmp_path)
    lines = f"FS_HOST_RUN_ID={RID}\nFS_HOST_ANSWER ctx_basics.stage=seed\nFS_HOST_ANSWER ctx_basics.stage=series_a\n"
    assert h.start(root, "deck-review", lines).returncode == 0
    assert h.ledger(root, RID)["pre_answers"]["ctx_basics.stage"]["option_id"] == "series_a"


def test_the_status_lists_every_gate_of_the_skill_and_mode(tmp_path: Path) -> None:
    gates = _load("_gates")
    root, run_id, _rd = h.start_bound(tmp_path, "ic-sim")
    st = h.status(root, run_id)
    listed = {(g["id"], g["instance"]) for g in st["gates"]}
    expected = {
        (gid, inst)
        for gid, g in gates.GATES.items()
        if g["skill"] in ("ic-sim", "shared") and "full" in g["modes"]
        for inst in _instances(g)
    }
    expected = {(gid, None if inst == "0.example_field" else inst) for gid, inst in expected}
    assert listed == expected
    assert {g["state"] for g in st["gates"]} == {"not_reached"}
    assert h.record(root, run_id, "open", "--gate", "ctx_basics.stage").returncode == 0
    states = {(g["id"], g["instance"]): g["state"] for g in h.status(root, run_id)["gates"]}
    assert states[("ctx_basics", "stage")] == "open" and states[("ic_mode", None)] == "not_reached"


def test_start_names_the_ledger_as_a_shell_path(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = _out(h.start(root, "deck-review", f"FS_HOST_RUN_ID={RID}\n"))
    assert "ledger" not in out and out["ledger_path_shell"] == str(h.ledger_path(root, RID))


def test_nothing_is_created_for_a_run_that_does_not_exist(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for proc in (
        h.run(h.RUN_STATUS, "show", "--run-id", RID, "--artifacts-root", str(root)),
        h.bind(root, RID, root / "ic-sim-example-co", "example-co"),
        h.record(root, RID, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed"),
        h.run(h.RUN_STATUS, "deliverables", "--run-id", RID, "--artifacts-root", str(root), "--final"),
    ):
        assert proc.returncode == 2 and _out(proc)["code"] == "RUN_NOT_FOUND", proc.stdout
    assert not (root / "runs").exists()


def test_bind_refuses_a_finished_run_and_a_second_run_dir(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim")
    before = h.status_path(root, run_id).read_bytes()
    proc = h.bind(root, run_id, run_dir.parent / "ic-sim-example-co-2", "example-co")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ALREADY_BOUND"
    assert h.status_path(root, run_id).read_bytes() == before
    assert h.bind(root, run_id, run_dir, "example-co").returncode == 0
    _set_state(root, run_id, "complete", "COMPLETE")
    before = h.status_path(root, run_id).read_bytes()
    proc = h.bind(root, run_id, run_dir, "example-co")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_FINISHED"
    assert h.status_path(root, run_id).read_bytes() == before


def test_finish_never_changes_the_runs_mode(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "cap-table", suffix="-concise")
    before = h.status_path(root, run_id).read_bytes()
    proc = _finish(root, run_id, "--mode", "quick_check", "--output", str(_artifact(run_dir, run_id)))
    assert proc.returncode == 1 and _out(proc)["code"] == "MODE_MISMATCH"
    assert h.status_path(root, run_id).read_bytes() == before
    root2, run_id2, _rd = h.start_bound(tmp_path / "b", "cap-table")
    proc = _finish(root2, run_id2, "--mode", "rule_lookup", "--lookup-status", "answered")
    assert proc.returncode == 1 and _out(proc)["code"] == "MODE_MISMATCH"


def test_a_rule_lookup_on_another_skill_is_refused_without_a_traceback(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run_id = h.start_ok(root, "deck-review")
    before = h.snapshot(root, run_id)
    proc = _finish(root, run_id, "--mode", "rule_lookup", "--lookup-status", "escalate")
    assert proc.returncode == 1 and _out(proc)["code"] == "MODE_NOT_OFFERED"
    assert "Traceback" not in proc.stderr
    assert h.snapshot(root, run_id) == before


def test_a_writer_that_outlived_its_lock_does_not_remove_the_next_holders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = rs.run_paths(str(tmp_path), RID)
    monkeypatch.setattr(rs, "_flock", lambda fd: False)
    marker = Path(paths.lock + ".excl")
    with rs.run_lock(paths, create=True):
        # Another writer took the lock over as stale while this one was still inside.
        marker.write_text("another-writer-token")
    assert marker.read_text() == "another-writer-token"


def test_a_request_line_ignored_on_two_invocations_is_one_notice(tmp_path: Path) -> None:
    """A basics line the company's existing context made moot, sent again with the resume: one notice at the end."""
    root = _root(tmp_path)
    (root / "founder-context-example-co.json").write_text(
        json.dumps({"company_name": "Example Co", "slug": "example-co", "stage": "seed", "sector": "saas"}),
        encoding="utf-8",
    )
    lines = "FS_HOST_RUN_ID=dup-notice-1\nFS_HOST_ANSWER ctx_basics.stage=seed\n"
    read = ("read", "--artifacts-root", str(root), "--run-id", "dup-notice-1", "--skill", "market-sizing")
    assert h.start(root, "market-sizing", lines).returncode == 0
    assert h.run(h.SHARED / "founder_context.py", *read).returncode == 0
    assert h.bind(root, "dup-notice-1", root / "market-sizing-example-co", "example-co").returncode == 0
    assert h.record(root, "dup-notice-1", "open", "--gate", "ms_methodology").returncode == 0
    assert h.start(root, "market-sizing", lines).returncode == 0
    assert h.run(h.SHARED / "founder_context.py", *read).returncode == 0
    assert (
        h.record(root, "dup-notice-1", "answer", "--gate", "ms_methodology", "--answer-id", "looks_good").returncode
        == 0
    )
    done = h.run(h.RUN_STATUS, "fail", "--run-id", "dup-notice-1", "--artifacts-root", str(root), "--code",
                 "PRODUCER_FAILED", "--reason", "x")  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    notices = [n for n in h.status(root, "dup-notice-1")["notices"] if n.get("gate") == "ctx_basics.stage"]
    assert len(notices) == 1, notices


def test_a_different_line_for_the_same_question_is_still_its_own_notice(tmp_path: Path) -> None:
    """De-duplication keys on the lines too: a resume that sends a NEW line for a question already passed over
    lists that line as well."""
    root = _root(tmp_path)
    (root / "founder-context-example-co.json").write_text(
        json.dumps({"company_name": "Example Co", "slug": "example-co", "stage": "seed", "sector": "saas"}),
        encoding="utf-8",
    )
    rid = "dup-notice-2"
    read = ("read", "--artifacts-root", str(root), "--run-id", rid, "--skill", "market-sizing")
    assert (
        h.start(root, "market-sizing", f"FS_HOST_RUN_ID={rid}\nFS_HOST_ANSWER ctx_basics.stage=seed\n").returncode == 0
    )
    assert h.run(h.SHARED / "founder_context.py", *read).returncode == 0
    assert h.bind(root, rid, root / "market-sizing-example-co", "example-co").returncode == 0
    assert h.record(root, rid, "open", "--gate", "ms_methodology").returncode == 0
    resume = f"FS_HOST_RUN_ID={rid}\nFS_HOST_ANSWER ctx_basics.stage=series_a\n"
    assert h.start(root, "market-sizing", resume).returncode == 0
    assert h.run(h.SHARED / "founder_context.py", *read).returncode == 0
    lines = [n["lines"] for n in h.status(root, rid)["notices"] if n.get("gate") == "ctx_basics.stage"]
    assert sorted(lines) == [
        ["FS_HOST_ANSWER ctx_basics.stage=seed"],
        ["FS_HOST_ANSWER ctx_basics.stage=series_a"],
    ], lines
