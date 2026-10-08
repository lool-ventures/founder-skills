"""A later run of the same skill for the same company takes over the folder an earlier run delivered into.

The earlier run's status must stop promising files that a fresh run's clean pass removed (deck review) or that
its compose is about to overwrite (every other skill): it is marked `superseded`, by the later run's id, with
each listed entry's `present` measured when it was marked. Its `status` and `code` do not change.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import gate_run_helpers as h
import no_ledger_goldens as goldens
import pytest

SETUP_RUN = h.SKILLS / "deck-review" / "scripts" / "setup_run.py"
EARLIER = "20261008T080000Z-aa0001"
LATER = "20261008T090000Z-bb0002"


def _rs() -> ModuleType:
    mod = sys.modules.get("_run_status")
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location("_run_status", h.SHARED / "_run_status.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_run_status"] = mod
    spec.loader.exec_module(mod)
    return mod


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _delivered(root: Path, skill: str, slug: str = "example-co") -> Path:
    """The earlier run, started, bound, coached by the real inserter, its page listed: complete and final."""
    rid = h.start_ok(root, skill, f"FS_HOST_RUN_ID={EARLIER}\n")
    run_dir = root / f"{h.RUN_DIR_PREFIX[skill]}-{slug}"
    if skill == "deck-review":
        proc = h.run(SETUP_RUN, "--artifacts-root", str(root), "--slug", slug, "--run-id", rid, "--clean")
        assert proc.returncode == 0, proc.stderr
    assert h.bind(root, rid, run_dir, slug).returncode == 0
    report, rj, art = goldens.coaching_dir(run_dir, EARLIER)
    ins = subprocess.run(
        [sys.executable, *goldens.coaching_argv(report, rj, art)],
        input=goldens.COACH_STDIN,
        capture_output=True,
        text=True,
    )
    assert ins.returncode == 0, ins.stderr
    page = run_dir / "report.html"
    page.write_text("<html><head></head><body>earlier</body></html>", encoding="utf-8")
    rs = _rs()
    rs.add_deliverable(rs.run_paths(str(root), EARLIER), "report_html", str(page), _sha(page), "visualize.py")
    proc = h.run(h.RUN_STATUS, "deliverables", "--run-id", EARLIER, "--artifacts-root", str(root), "--final")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, EARLIER)
    assert (st["status"], st["deliverables_status"], st.get("superseded_by")) == ("complete", "final", None)
    return run_dir


def _later_starts(root: Path, skill: str, run_dir: Path, slug: str = "example-co") -> subprocess.CompletedProcess[str]:
    h.start_ok(root, skill, f"FS_HOST_RUN_ID={LATER}\n")
    if skill == "deck-review":
        proc = h.run(SETUP_RUN, "--artifacts-root", str(root), "--slug", slug, "--run-id", LATER, "--clean")
        assert proc.returncode == 0, proc.stderr
    return h.bind(root, LATER, run_dir, slug)


def _no_dangling_promise(st: dict[str, Any]) -> None:
    """The fact the bug broke, stated without the new fields: a `final` status lists only files that are there."""
    if st.get("deliverables_status") == "final":
        for key, entry in (st.get("deliverables") or {}).items():
            path = Path(entry["path_shell"])
            assert path.is_file() and _sha(path) == entry["sha256"], f"{key} is listed final but gone or changed"


NOW = {"FOUNDER_SKILLS_SUPERSEDE_RETRY_S": "0"}
# A call that may wait on a lock another process holds is killed past this, so a lost bound fails the test (in
# about this long) instead of hanging the suite; every holder below also lets go on its own after 25 s.
CALL_TIMEOUT_S = 20


def _open_now(root: Path, run_id: str, gate: str) -> subprocess.CompletedProcess[str]:
    """`record_gate_answer.py open`, a plain transaction of the run, with the retry interval at zero."""
    return h.run(
        h.RECORD, "open", "--run-id", run_id, "--artifacts-root", str(root), "--gate", gate,
        env=NOW, timeout=CALL_TIMEOUT_S,
    )  # fmt: skip


def _assert_superseded(st: dict[str, Any]) -> None:
    _no_dangling_promise(st)
    assert (st["status"], st["code"]) == ("complete", "COMPLETE")
    assert (st["deliverables_status"], st["superseded_by"]) == ("superseded", LATER)
    assert isinstance(st["superseded_at"], str)
    assert set(st["deliverables"]) == {"report_md", "report_json", "report_html"}
    assert all("present" not in v for v in st["deliverables"].values())


def test_deck_review_clean_marks_the_earlier_run_whose_reports_it_removed(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "deck-review")
    h.start_ok(root, "deck-review", f"FS_HOST_RUN_ID={LATER}\n")
    proc = h.run(SETUP_RUN, "--artifacts-root", str(root), "--slug", "example-co", "--run-id", LATER, "--clean")
    assert proc.returncode == 0, proc.stderr
    assert not (run_dir / "report.md").exists()
    # The clean pass alone marks it: a bind that then fails cannot leave the promise dangling.
    _assert_superseded(h.status(root, EARLIER))
    assert h.bind(root, LATER, run_dir, "example-co").returncode == 0
    _assert_superseded(h.status(root, EARLIER))


@pytest.mark.parametrize(
    "skill", ["market-sizing", "ic-sim", "competitive-positioning", "financial-model-review", "cap-table"]
)
def test_bind_marks_the_earlier_run_before_its_reports_are_overwritten(tmp_path: Path, skill: str) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, skill)
    proc = _later_starts(root, skill, run_dir)
    assert proc.returncode == 0, proc.stderr
    marked = h.snapshot(root, EARLIER)
    (run_dir / "report.md").write_text("# the later run's report\n", encoding="utf-8")
    _no_dangling_promise(h.status(root, EARLIER))
    assert h.snapshot(root, EARLIER) == marked
    assert json.loads(proc.stdout).get("superseded_runs") == [EARLIER]
    st = h.status(root, EARLIER)
    assert (st["deliverables_status"], st["superseded_by"]) == ("superseded", LATER)
    assert h.status(root, LATER)["superseded_by"] is None


def test_a_second_bind_of_the_later_run_changes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    assert _later_starts(root, "market-sizing", run_dir).returncode == 0
    before = h.snapshot(root, EARLIER)
    again = h.bind(root, LATER, run_dir, "example-co")
    assert again.returncode == 0
    assert "superseded_runs" not in json.loads(again.stdout)
    assert h.snapshot(root, EARLIER) == before


def test_superseded_stays_through_the_earlier_runs_own_writers(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    assert _later_starts(root, "market-sizing", run_dir).returncode == 0
    rs = _rs()
    page = run_dir / "report.html"
    rs.add_deliverable(rs.run_paths(str(root), EARLIER), "report_html", str(page), _sha(page), "visualize.py")
    proc = h.run(h.RUN_STATUS, "deliverables", "--run-id", EARLIER, "--artifacts-root", str(root), "--final")
    assert json.loads(proc.stdout)["deliverables_status"] == "superseded"
    assert h.status(root, EARLIER)["deliverables_status"] == "superseded"


def test_another_folder_and_a_finished_run_with_nothing_there_are_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _delivered(root, "market-sizing")
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    assert h.bind(root, LATER, root / "market-sizing-example-co-quickcheck", "example-co").returncode == 0
    assert h.status(root, EARLIER).get("superseded_by") is None
    # A finished run bound to a folder in which it lists nothing keeps its status when that folder is taken.
    failed, fdir = "20261008T093000Z-cc0003", root / "market-sizing-other-co"
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={failed}\n")
    assert h.bind(root, failed, fdir, "other-co").returncode == 0
    proc = h.run(
        h.RUN_STATUS,
        "fail",
        "--run-id",
        failed,
        "--artifacts-root",
        str(root),
        "--code",
        "PRODUCER_FAILED",
        "--reason",
        "x",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    before = h.snapshot(root, failed)
    taker = "20261008T094000Z-dd0004"
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={taker}\n")
    assert h.bind(root, taker, fdir, "other-co").returncode == 0
    assert h.snapshot(root, failed) == before


def test_a_waiting_run_in_the_folder_is_marked_and_stays_waiting(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    rid = h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={EARLIER}\n")
    run_dir = root / "market-sizing-example-co"
    assert h.bind(root, rid, run_dir, "example-co").returncode == 0
    assert h.record(root, EARLIER, "open", "--gate", "ms_methodology").returncode == 0
    before = h.status(root, EARLIER)
    assert (before["status"], before["waiting_on"]) == ("waiting", "ms_methodology")
    assert _later_starts(root, "market-sizing", run_dir).returncode == 0
    st = h.status(root, EARLIER)
    for key in ("status", "code", "waiting_on", "resumable"):
        assert st[key] == before[key], key
    assert (st["deliverables_status"], st["superseded_by"]) == ("superseded", LATER)


def test_a_resumed_run_that_binds_again_takes_the_folder_back(tmp_path: Path) -> None:
    """A waits, B takes the folder and delivers, A resumes and binds again: A is current, B is superseded by A."""
    root = tmp_path / "artifacts"
    run_dir = root / "market-sizing-example-co"
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={EARLIER}\n")
    assert h.bind(root, EARLIER, run_dir, "example-co").returncode == 0
    assert h.record(root, EARLIER, "open", "--gate", "ms_methodology").returncode == 0
    assert _later_starts(root, "market-sizing", run_dir).returncode == 0
    rs = _rs()
    report, rj, _art = goldens.coaching_dir(run_dir, LATER)
    rs.complete_after_coaching(rs.run_paths(str(root), LATER), str(report), str(rj))
    page = run_dir / "report.html"
    page.write_text("<html><head></head><body>later</body></html>", encoding="utf-8")
    rs.add_deliverable(rs.run_paths(str(root), LATER), "report_html", str(page), _sha(page), "visualize.py")
    assert h.status(root, LATER)["deliverables_status"] == "final"
    assert h.status(root, EARLIER)["superseded_by"] == LATER
    resumed = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={EARLIER}\n")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    rebound = h.bind(root, EARLIER, run_dir, "example-co")
    assert rebound.returncode == 0, rebound.stderr
    assert json.loads(rebound.stdout)["superseded_runs"] == [LATER]
    a, b = h.status(root, EARLIER), h.status(root, LATER)
    assert (a["superseded_by"], a["superseded_at"], a["deliverables_status"]) == (None, None, None)
    assert (b["status"], b["deliverables_status"], b["superseded_by"]) == ("complete", "superseded", EARLIER)
    # A answers and completes: it reads as its own state says, never superseded (B, complete, cannot bind again).
    ans = h.record(root, EARLIER, "answer", "--gate", "ms_methodology", "--answer-id", "looks_good")
    assert ans.returncode == 0, ans.stdout + ans.stderr
    rs.complete_after_coaching(rs.run_paths(str(root), EARLIER), str(report), str(rj))
    a = h.status(root, EARLIER)
    assert (a["status"], a["deliverables_status"], a["superseded_by"]) == ("complete", "pending", None)


@pytest.mark.parametrize("skill", ["competitive-positioning", "cap-table"])
def test_a_reopened_complete_run_takes_the_folder_back(tmp_path: Path, skill: str) -> None:
    """A delivered, B takes the folder and delivers, A's compose reopens it (the skill's own reopen entry point)."""
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, skill)
    assert _later_starts(root, skill, run_dir).returncode == 0
    rs = _rs()
    rs.complete_after_coaching(rs.run_paths(str(root), LATER), str(run_dir / "report.md"), None)
    assert h.status(root, LATER)["deliverables_status"] in ("final", "pending")
    module = "_cp_gates" if skill == "competitive-positioning" else "_ct_gates"
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(h.SKILLS / skill / "scripts")!r})
        import {module} as m
        m.reopen_if_complete({str(run_dir)!r}, {EARLIER!r}, step="7")
        """
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    a, b = h.status(root, EARLIER), h.status(root, LATER)
    assert (a["status"], a["revision"], a["superseded_by"], a["deliverables_status"]) == ("running", 1, None, None)
    assert (b["deliverables_status"], b["superseded_by"]) == ("superseded", EARLIER)


def test_the_cash_reply_reopen_takes_the_folder_back(tmp_path: Path) -> None:
    import test_fmr_gates as fm

    root, run_id, run_dir = fm._run(tmp_path)
    inputs = json.loads((run_dir / "inputs.json").read_text())
    for k in ("current_balance", "balance_date"):
        inputs["cash"].pop(k)
    (run_dir / "inputs.json").write_text(json.dumps(inputs))
    gates = [a for k in ("current_balance", "balance_date", "monthly_burn") for a in ("--gate", f"fmr_cash_basics.{k}")]
    fm._ok(fm._rec(root, run_id, "open", *gates))
    fm._ok(
        fm._rec(
            root, run_id, "answer",
            "--gate", "fmr_cash_basics.current_balance", "--answer-id", "not_stated",
            "--gate", "fmr_cash_basics.balance_date", "--answer-id", "not_stated",
            "--gate", "fmr_cash_basics.monthly_burn", "--answer-id", "stated", "--value", "120000",
        )
    )  # fmt: skip
    fm._opened(root, run_id)
    fm._corrections(run_dir, run_id, "chat", "revenue.mrr=45000")
    fm._ok(fm._rec(root, run_id, "answer", "--gate", "fmr_extracted_values", "--answer-id", "corrections_applied"))
    fm._ok(fm._producer("unit_economics.py", run_dir, run_id))
    fm._ok(fm._producer("runway.py", run_dir, run_id))
    fm._ok(fm._compose(run_dir))
    assert fm._complete(root, run_id, run_dir)["status"] == "complete"
    later = "20261008T095000Z-ee0005"
    h.start_ok(root, "financial-model-review", f"FS_HOST_RUN_ID={later}\n")
    assert h.bind(root, later, run_dir, "example-co").returncode == 0
    assert h.status(root, run_id)["superseded_by"] == later
    rs = _rs()
    rs.complete_after_coaching(rs.run_paths(str(root), later), str(run_dir / "report.md"), None)
    time.sleep(0.002)
    fm._corrections(run_dir, run_id, "chat", "cash.current_balance=900000", "cash.balance_date=2026-09")
    fm._ok(
        fm._rec(
            root, run_id, "answer",
            "--gate", "fmr_cash_followup", "--answer-id", "provided",
            "--gate", "fmr_cash_basics.current_balance", "--answer-id", "stated", "--value", "900000",
            "--gate", "fmr_cash_basics.balance_date", "--answer-id", "stated", "--value", "2026-09",
        )
    )  # fmt: skip
    a, b = h.status(root, run_id), h.status(root, later)
    assert (a["status"], a["revision"], a["superseded_by"]) == ("running", 1, None)
    assert (b["deliverables_status"], b["superseded_by"]) == ("superseded", run_id)


def test_a_status_written_under_another_absolute_path_is_still_matched(tmp_path: Path) -> None:
    """The same folder seen by an earlier session under another prefix: compared relative to each run's root."""
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    path = h.status_path(root, EARLIER)
    st = json.loads(path.read_text(encoding="utf-8"))
    old, dead = str(root), "/sessions/old-session/mnt/outputs/artifacts"
    st["artifacts_root_shell"] = dead
    st["run_dir_shell"] = st["run_dir_shell"].replace(old, dead)
    for entry in st["deliverables"].values():
        entry["path_shell"] = entry["path_shell"].replace(old, dead)
    path.write_text(json.dumps(st, indent=2), encoding="utf-8")
    assert _later_starts(root, "market-sizing", run_dir).returncode == 0
    assert h.status(root, EARLIER)["superseded_by"] == LATER


def test_a_refused_bind_marks_nothing(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    before = h.snapshot(root, EARLIER)
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    assert h.bind(root, LATER, root / "market-sizing-other-co", "other-co").returncode == 0
    assert h.bind(root, LATER, run_dir, "other-co").returncode == 1  # RUN_ALREADY_BOUND
    assert h.bind(root, LATER, root / "market-sizing-example-co-x", "example-co").returncode == 1  # RUN_ID_IN_USE
    assert h.snapshot(root, EARLIER) == before


def test_bind_waits_for_the_earlier_runs_lock_and_loses_neither_write(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    holder = textwrap.dedent(
        f"""
        import importlib.util, select, sys, time
        HOLD_S = 25
        spec = importlib.util.spec_from_file_location("_run_status", {str(h.SHARED / "_run_status.py")!r})
        rs = importlib.util.module_from_spec(spec)
        sys.modules["_run_status"] = rs
        spec.loader.exec_module(rs)
        p = rs.run_paths({str(root)!r}, {EARLIER!r})
        with rs.run_lock(p):
            st = rs.load_status(p)
            print("held", flush=True)
            time.sleep(1.5)
            note = {{"code": "PRE_ANSWER_IGNORED", "gate": "x", "lines": [], "reason": "not_reached"}}
            st["notices"] = [*st["notices"], note]
            rs.write_status(p, st)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
    t0 = time.monotonic()
    bound = h.bind(root, LATER, run_dir, "example-co")
    assert proc.wait(timeout=30) == 0
    assert bound.returncode == 0, bound.stderr
    assert time.monotonic() - t0 >= 1.0
    st = h.status(root, EARLIER)
    assert st["superseded_by"] == LATER
    assert any(n.get("gate") == "x" for n in st["notices"])


def test_the_helper_refuses_to_run_under_a_held_lock(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    rs = _rs()
    with rs.run_lock(rs.run_paths(str(root), EARLIER)), pytest.raises(RuntimeError):
        rs.supersede_runs_in(str(root), str(run_dir), LATER)


def test_an_unreadable_status_is_a_warning_and_no_notice(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    h.status_path(root, EARLIER).write_text("{not json", encoding="utf-8")
    proc = _later_starts(root, "market-sizing", run_dir)
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert h.status(root, LATER)["notices"] == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_run_that_cannot_be_written_is_a_notice_and_the_bind_still_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    run_root = h.status_path(root, EARLIER).parent
    before = h.snapshot(root, EARLIER)
    run_root.chmod(0o555)
    try:
        proc = _later_starts(root, "market-sizing", run_dir)
    finally:
        run_root.chmod(0o755)
    assert proc.returncode == 0, proc.stderr
    assert EARLIER in proc.stderr
    assert {"code": "SUPERSEDE_NOT_RECORDED", "run_id": EARLIER} in h.status(root, LATER)["notices"]
    assert h.snapshot(root, EARLIER) == before
    # The run's next transaction retries: the earlier run is marked and the notice dropped.
    assert _open_now(root, LATER, "ms_methodology").returncode == 0
    assert h.status(root, EARLIER)["superseded_by"] == LATER
    assert {"code": "SUPERSEDE_NOT_RECORDED", "run_id": EARLIER} not in h.status(root, LATER)["notices"]


def test_a_held_lock_is_waited_for_a_bounded_time_then_retried(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    holder = textwrap.dedent(
        f"""
        import importlib.util, select, sys, time
        HOLD_S = 25
        spec = importlib.util.spec_from_file_location("_run_status", {str(h.SHARED / "_run_status.py")!r})
        rs = importlib.util.module_from_spec(spec)
        sys.modules["_run_status"] = rs
        spec.loader.exec_module(rs)
        with rs.run_lock(rs.run_paths({str(root)!r}, {EARLIER!r})):
            print("held", flush=True)
            select.select([sys.stdin], [], [], HOLD_S)  # released by the test, or on its own
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdin is not None and proc.stdout.readline().strip() == "held"
    before = h.snapshot(root, EARLIER)
    try:
        t0 = time.monotonic()
        bound = h.run(
            h.RUN_STATUS, "bind", "--run-id", LATER, "--artifacts-root", str(root),
            "--run-dir", str(run_dir), "--slug", "example-co",
            env={"FOUNDER_SKILLS_SUPERSEDE_WAIT_S": "0.3"}, timeout=CALL_TIMEOUT_S,
        )  # fmt: skip
        assert time.monotonic() - t0 < 5
    finally:
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    assert bound.returncode == 0, bound.stderr
    assert {"code": "SUPERSEDE_NOT_RECORDED", "run_id": EARLIER} in h.status(root, LATER)["notices"]
    assert h.snapshot(root, EARLIER) == before
    # The run's next transaction retries: the earlier run is marked and the notice dropped.
    assert _open_now(root, LATER, "ms_methodology").returncode == 0
    assert h.status(root, EARLIER)["superseded_by"] == LATER
    assert {"code": "SUPERSEDE_NOT_RECORDED", "run_id": EARLIER} not in h.status(root, LATER)["notices"]
    again = h.bind(root, LATER, run_dir, "example-co")
    assert again.returncode == 0
    assert h.status(root, EARLIER)["superseded_by"] == LATER
    assert not any(n.get("code") == "SUPERSEDE_NOT_RECORDED" for n in h.status(root, LATER)["notices"])


def test_a_reopen_whose_marking_times_out_is_noted_and_retried_at_the_next_transaction(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "competitive-positioning")
    assert _later_starts(root, "competitive-positioning", run_dir).returncode == 0
    rs = _rs()
    rs.complete_after_coaching(rs.run_paths(str(root), LATER), str(run_dir / "report.md"), None)
    holder = textwrap.dedent(
        f"""
        import importlib.util, select, sys
        HOLD_S = 25
        spec = importlib.util.spec_from_file_location("_run_status", {str(h.SHARED / "_run_status.py")!r})
        rs = importlib.util.module_from_spec(spec)
        sys.modules["_run_status"] = rs
        spec.loader.exec_module(rs)
        with rs.run_lock(rs.run_paths({str(root)!r}, {LATER!r})):
            print("held", flush=True)
            select.select([sys.stdin], [], [], HOLD_S)  # released by the test, or on its own
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdin is not None and proc.stdout.readline().strip() == "held"
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(h.SKILLS / "competitive-positioning" / "scripts")!r})
        import _cp_gates as m
        m.reopen_if_complete({str(run_dir)!r}, {EARLIER!r}, step="7")
        """
    )
    try:
        env = {**os.environ, "FOUNDER_SKILLS_SUPERSEDE_WAIT_S": "0.3"}
        reopened = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=CALL_TIMEOUT_S
        )
    finally:
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    assert reopened.returncode == 0, reopened.stderr
    assert LATER in reopened.stderr
    notice = {"code": "SUPERSEDE_NOT_RECORDED", "run_id": LATER}
    assert notice in h.status(root, EARLIER)["notices"]
    assert h.status(root, LATER)["superseded_by"] is None
    # The reopened run's next transaction retries, marks the later run and drops the notice.
    assert _open_now(root, EARLIER, "cp_gate1_landscape").returncode == 0
    assert h.status(root, LATER)["superseded_by"] == EARLIER
    assert notice not in h.status(root, EARLIER)["notices"]


def _hold(root: Path, run_id: str) -> subprocess.Popen[str]:
    """A subprocess holding `run_id`'s lock until a line arrives on its stdin."""
    holder = textwrap.dedent(
        f"""
        import importlib.util, select, sys
        HOLD_S = 25
        spec = importlib.util.spec_from_file_location("_run_status", {str(h.SHARED / "_run_status.py")!r})
        rs = importlib.util.module_from_spec(spec)
        sys.modules["_run_status"] = rs
        spec.loader.exec_module(rs)
        with rs.run_lock(rs.run_paths({str(root)!r}, {run_id!r})):
            print("held", flush=True)
            select.select([sys.stdin], [], [], HOLD_S)  # released by the test, or on its own
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
    return proc


def _release(proc: subprocess.Popen[str]) -> None:
    assert proc.stdin is not None
    proc.stdin.write("\n")
    proc.stdin.flush()
    proc.wait(timeout=10)


def _bind_fast(root: Path, run_id: str, run_dir: Path) -> subprocess.CompletedProcess[str]:
    return h.run(
        h.RUN_STATUS, "bind", "--run-id", run_id, "--artifacts-root", str(root),
        "--run-dir", str(run_dir), "--slug", "example-co",
        env={"FOUNDER_SKILLS_SUPERSEDE_WAIT_S": "0.3"}, timeout=CALL_TIMEOUT_S,
    )  # fmt: skip


def test_a_retry_marks_only_and_never_takes_the_folder_back_from_a_later_run(tmp_path: Path) -> None:
    """N4 binds while N1's lock is held (a notice); run C then takes the folder from both. N4's next transaction
    must not take it back: N4 stays superseded by C, C stays current, and N4's notice is dropped."""
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    holder = _hold(root, EARLIER)
    try:
        assert _bind_fast(root, LATER, run_dir).returncode == 0
    finally:
        _release(holder)
    assert {"code": "SUPERSEDE_NOT_RECORDED", "run_id": EARLIER} in h.status(root, LATER)["notices"]
    third = "20261008T100000Z-ff0006"
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={third}\n")
    assert h.bind(root, third, run_dir, "example-co").returncode == 0
    assert h.status(root, LATER)["superseded_by"] == third
    assert _open_now(root, LATER, "ms_methodology").returncode == 0
    later, current = h.status(root, LATER), h.status(root, third)
    assert (later["superseded_by"], current["superseded_by"]) == (third, None)
    assert not any(n.get("code") == "SUPERSEDE_NOT_RECORDED" for n in later["notices"])


def test_a_failed_marking_is_retried_at_most_once_per_interval(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    run_dir = _delivered(root, "market-sizing")
    h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={LATER}\n")
    holder = _hold(root, EARLIER)
    try:
        assert _bind_fast(root, LATER, run_dir).returncode == 0
        # Within the interval (the default), a transaction does not wait on the held lock again.
        t0 = time.monotonic()
        within = h.run(
            h.RECORD, "open", "--run-id", LATER, "--artifacts-root", str(root), "--gate", "ms_methodology",
            timeout=CALL_TIMEOUT_S,
        )  # fmt: skip
        assert within.returncode == 0, within.stderr
        assert time.monotonic() - t0 < 4
    finally:
        _release(holder)
    assert h.status(root, EARLIER)["superseded_by"] is None
    attempts = h.ledger(root, LATER)["supersede_retry"]["attempts"]
    assert attempts == 1
    # Past the interval the next transaction retries, marks and clears both the notice and the retry record.
    assert _open_now(root, LATER, "ms_methodology").returncode == 0
    assert h.status(root, EARLIER)["superseded_by"] == LATER
    assert "supersede_retry" not in h.ledger(root, LATER)
    assert not any(n.get("code") == "SUPERSEDE_NOT_RECORDED" for n in h.status(root, LATER)["notices"])
