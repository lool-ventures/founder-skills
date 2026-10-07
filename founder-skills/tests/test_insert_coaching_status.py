"""Inserting the coaching completes a run that has a gate ledger, and changes nothing for one that has not.

`complete` is written when the coaching lands, with the reports' hashes as they are after insertion.
The status write is a side effect: it never changes what the inserter prints or how it exits, so a run
with no ledger is held against goldens captured before the write existed, and a run whose status cannot
be written behaves exactly like one whose status can.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import gate_run_helpers as h
import no_ledger_goldens as goldens
import pytest

RUN = goldens.COACH_RUN


def _run_status() -> ModuleType:
    mod = sys.modules.get("_run_status")
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location("_run_status", h.SHARED / "_run_status.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_run_status"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ledgered(tmp: Path, skill: str = "market-sizing") -> tuple[Path, Path, Path, Path, Path]:
    """(artifacts root, run dir, report.md, report.json, verified artifact) for a bound run."""
    root, rid, run_dir = h.start_bound(tmp, skill, lines=f"FS_HOST_RUN_ID={RUN}\n")
    assert rid == RUN
    report, rj, art = goldens.coaching_dir(run_dir)
    return root, run_dir, report, rj, art


def _insert(
    report: Path, rj: Path, art: Path, stdin: str = goldens.COACH_STDIN, **kw: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *goldens.coaching_argv(report, rj, art, **kw)], input=stdin, capture_output=True, text=True
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _page(root: Path, run_dir: Path, key: str, name: str) -> None:
    rs = _run_status()
    page = run_dir / name
    page.write_text("<html><head></head><body>page</body></html>", encoding="utf-8")
    rs.add_deliverable(rs.run_paths(str(root), RUN), key, str(page), rs.file_sha256(str(page)), "visualize.py")


def test_without_a_ledger_nothing_changes() -> None:
    assert goldens.coaching_scenarios() == goldens.load()["insert_coaching"]


def test_inserted_completes_the_run_with_post_insert_hashes(tmp_path: Path) -> None:
    root, _run_dir, report, rj, art = _ledgered(tmp_path)
    proc = _insert(report, rj, art)
    assert proc.returncode == 0, proc.stderr
    st = h.status(root, RUN)
    assert (st["status"], st["code"], st["coaching"]) == ("complete", "COMPLETE", "inserted")
    assert st["deliverables"]["report_md"]["sha256"] == _sha(report)
    assert st["deliverables"]["report_json"]["sha256"] == _sha(rj)
    assert "## Coaching Commentary" in report.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        plain_report, plain_rj, plain_art = goldens.coaching_dir(Path(td))
        plain = _insert(plain_report, plain_rj, plain_art)
    assert set(json.loads(proc.stdout)) == set(json.loads(plain.stdout))
    again = _insert(report, rj, art)
    assert again.returncode == 0
    assert json.loads(again.stdout)["status"] == "already_inserted"
    assert h.status(root, RUN)["status"] == "complete"


@pytest.mark.parametrize(
    ("skill", "expected"),
    [
        ("financial-model-review", "final"),
        ("cap-table", "final"),
        ("deck-review", "pending"),
        ("market-sizing", "pending"),
        ("ic-sim", "pending"),
        ("competitive-positioning", "pending"),
    ],
)
def test_deliverables_status_at_complete(tmp_path: Path, skill: str, expected: str) -> None:
    root, run_dir, report, rj, art = _ledgered(tmp_path, skill)
    if skill in ("financial-model-review", "cap-table"):
        _page(root, run_dir, "report_html", "report.html")
    proc = _insert(report, rj, art)
    assert proc.returncode == 0, proc.stderr
    st = h.status(root, RUN)
    assert st["status"] == "complete"
    assert st["deliverables_status"] == expected
    if skill in ("financial-model-review", "cap-table"):
        assert "report_html" in st["deliverables"], "a page written before coaching was dropped"
    if skill == "competitive-positioning":
        _page(root, run_dir, "report_html", "report.html")
        assert h.status(root, RUN)["deliverables_status"] == "pending"
        _page(root, run_dir, "explorer_html", "explore.html")
        assert h.status(root, RUN)["deliverables_status"] == "final"


def test_an_open_gate_holds_complete_until_it_is_answered(tmp_path: Path) -> None:
    root, _run_dir, report, rj, art = _ledgered(tmp_path)
    opened = h.record(root, RUN, "open", "--gate", "ctx_basics.stage")
    assert opened.returncode == 0, opened.stderr
    proc = _insert(report, rj, art)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.strip() and len(proc.stderr.strip().splitlines()) == 1
    st = h.status(root, RUN)
    assert (st["status"], st["coaching"]) == ("waiting", "inserted")
    ans = h.record(root, RUN, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed")
    assert ans.returncode == 0, ans.stdout + ans.stderr
    st = h.status(root, RUN)
    assert st["status"] == "complete"
    assert st["deliverables_status"] == "pending"


def test_blocked_after_parity_is_recorded(tmp_path: Path) -> None:
    root, _run_dir, report, rj, art = _ledgered(tmp_path)
    proc = _insert(report, rj, art, stdin=json.dumps({"commentary_markdown": ""}))
    assert proc.returncode == 1
    golden = goldens.load()["insert_coaching"]["blocked_after_parity"]
    assert goldens._sha(goldens.normalise(proc.stdout, str(tmp_path))) == golden["stdout"]
    st = h.status(root, RUN)
    assert (st["status"], st["last_error_code"], st["coaching"]) == ("running", "COACHING_BLOCKED", "blocked")


def test_blocked_before_parity_writes_nothing(tmp_path: Path) -> None:
    root, _run_dir, report, rj, art = _ledgered(tmp_path)
    before = h.status_path(root, RUN).read_bytes()
    proc = _insert(report, rj, art, marker="<!-- COACHING_INSERTION_POINT_00000000 -->")
    assert proc.returncode == 1
    assert h.status_path(root, RUN).read_bytes() == before


def _normalised(proc: subprocess.CompletedProcess[str], tmp: Path) -> tuple[int, str]:
    return proc.returncode, goldens.normalise(proc.stdout, str(tmp))


def test_a_status_that_cannot_be_written_changes_nothing_printed(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    _root, _d, report, rj, art = _ledgered(good)
    writable = _insert(report, rj, art)
    root, _d2, report2, rj2, art2 = _ledgered(bad)
    status_file = h.status_path(root, RUN)
    run_root = status_file.parent
    status_file.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    run_root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        locked = _insert(report2, rj2, art2)
    finally:
        run_root.chmod(stat.S_IRWXU)
        status_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert _normalised(locked, bad) == _normalised(writable, good)
    lines = locked.stderr.strip().splitlines()
    assert len(lines) == 1 and "warning" in lines[0], locked.stderr


def test_a_ref_whose_ledger_is_gone_changes_nothing_printed(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    _root, _d, report, rj, art = _ledgered(good)
    writable = _insert(report, rj, art)
    root, _d2, report2, rj2, art2 = _ledgered(bad)
    os.unlink(h.ledger_path(root, RUN))
    gone = _insert(report2, rj2, art2)
    assert _normalised(gone, bad) == _normalised(writable, good)
    lines = gone.stderr.strip().splitlines()
    assert len(lines) == 1 and "warning" in lines[0], gone.stderr
