"""Each deliverable HTML page carries its run's id only when asked, and only the id its artifacts carry.

A host copies a page only when the run's status lists it, and a page left in the folder by an earlier
run looks the same as this run's. So `--run-id` stamps a meta tag and, on a run with a gate ledger,
lists the page among the run's deliverables. Without the flag the page must be byte-for-byte what it was
before the flag existed: that is held against goldens captured before it was added, never against a
second run of the edited code.
"""

from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import gate_run_helpers as h
import no_ledger_goldens as goldens
import pytest
from compose_invocations import drive_compose
from html_writer_invocations import WRITERS, argv

FIXTURES = goldens.FIXTURES
META = re.compile(r'<meta name="founder-skills-run-id" content="([^"]*)">')
HEAD = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)
IDS = [f"{w[0]}/{w[1]}" for w in WRITERS]


def _run_status() -> ModuleType:
    mod = sys.modules.get("_run_status")
    if mod is not None:
        return mod
    path = h.SHARED / "_run_status.py"
    spec = importlib.util.spec_from_file_location("_run_status", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_run_status"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fixture_run_id(skill: str) -> str:
    """The run id the fixtures carry: every fixture of a skill carries the same one."""
    ids: collections.Counter[str] = collections.Counter()
    for f in (FIXTURES / skill).glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        meta = data.get("metadata") if isinstance(data, dict) else None
        rid = meta.get("run_id") if isinstance(meta, dict) else None
        if isinstance(rid, str) and rid:
            ids[rid] += 1
    assert len(ids) == 1, f"{skill} fixtures carry several run ids: {ids}"
    return next(iter(ids))


def _write(
    skill: str, script: str, work: Path, out: Path, run_id: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *argv(skill, script, work, out, run_id)], capture_output=True, text=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(("skill", "script", "out_name", "key", "flags"), WRITERS, ids=IDS)
def test_without_the_flag_the_page_is_what_it_was(skill: str, script: str, out_name: str, key: str, flags: Any) -> None:
    assert goldens.html_scenario(skill, script) == goldens.load()["html"][f"{skill}/{script}"]


@pytest.mark.parametrize(("skill", "script", "out_name", "key", "flags"), WRITERS, ids=IDS)
def test_the_flag_adds_one_tag_right_after_head(
    tmp_path: Path, skill: str, script: str, out_name: str, key: str, flags: Any
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    drive_compose(skill, FIXTURES / skill, work)
    rid = _fixture_run_id(skill)
    plain, stamped = work / "plain.html", work / out_name
    p = _write(skill, script, work, plain)
    assert p.returncode == 0, p.stderr[-400:]
    assert not META.search(plain.read_text(encoding="utf-8"))
    s = _write(skill, script, work, stamped, rid)
    assert s.returncode == 0, s.stderr[-400:]
    page = stamped.read_text(encoding="utf-8")
    tags = META.findall(page)
    assert tags == [rid]
    head = HEAD.search(page)
    assert head is not None
    assert page[head.end() :].startswith(f'<meta name="founder-skills-run-id" content="{rid}">')
    unstamped = META.sub("", page, count=1)
    assert goldens.normalise(unstamped, str(tmp_path)) == goldens.normalise(
        plain.read_text(encoding="utf-8"), str(tmp_path)
    )


@pytest.mark.parametrize(("skill", "script", "out_name", "key", "flags"), WRITERS, ids=IDS)
@pytest.mark.parametrize("bad", ["other-run-7f3a", "../x"])
def test_a_run_id_the_artifacts_do_not_carry_is_refused(
    tmp_path: Path, skill: str, script: str, out_name: str, key: str, flags: Any, bad: str
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    drive_compose(skill, FIXTURES / skill, work)
    out = work / out_name
    out.write_bytes(b"sentinel")
    proc = _write(skill, script, work, out, bad)
    assert proc.returncode == 1, (proc.returncode, proc.stderr[-300:])
    assert json.loads(proc.stdout)["code"] == "RUN_ID_MISMATCH"
    assert proc.stderr.strip()
    assert out.read_bytes() == b"sentinel"


@pytest.mark.parametrize(("skill", "script", "out_name", "key", "flags"), WRITERS, ids=IDS)
def test_with_a_ledger_the_page_is_listed(
    tmp_path: Path, skill: str, script: str, out_name: str, key: str, flags: Any
) -> None:
    rid = _fixture_run_id(skill)
    root, run_id, run_dir = h.start_bound(tmp_path, skill, lines=f"FS_HOST_RUN_ID={rid}\n")
    assert run_id == rid
    drive_compose(skill, FIXTURES / skill, run_dir)
    before = h.status(root, rid)
    out = run_dir / out_name
    proc = _write(skill, script, run_dir, out, rid)
    assert proc.returncode == 0, proc.stderr[-400:]
    after = h.status(root, rid)
    entry = after["deliverables"][key]
    assert entry["sha256"] == _sha(out)
    assert entry["file"] == out_name
    assert entry["writer"] == script
    assert entry["revision"] == 0
    assert after["status"] == "running"
    for k in ("deliverables", "updated_at"):
        before.pop(k)
        after.pop(k)
    assert after == before


@pytest.mark.parametrize(("skill", "script", "out_name", "key", "flags"), WRITERS, ids=IDS)
def test_without_a_ledger_the_flag_writes_no_run_files(
    tmp_path: Path, skill: str, script: str, out_name: str, key: str, flags: Any
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    drive_compose(skill, FIXTURES / skill, work)

    def dirs() -> set[str]:
        return {os.path.relpath(d, tmp_path) for d, _sub, _f in os.walk(tmp_path)}

    before = dirs()
    proc = _write(skill, script, work, work / out_name, _fixture_run_id(skill))
    assert proc.returncode == 0, proc.stderr[-400:]
    added = dirs() - before
    assert added == set(), added
    names = {Path(d).name for d in dirs()}
    assert "runs" not in names
    assert "runs" not in {Path(d).name for d in before}


def test_the_last_expected_page_makes_a_pending_run_final(tmp_path: Path) -> None:
    skill, script = "deck-review", "visualize.py"
    rid = _fixture_run_id(skill)
    root, _rid, run_dir = h.start_bound(tmp_path, skill, lines=f"FS_HOST_RUN_ID={rid}\n")
    drive_compose(skill, FIXTURES / skill, run_dir)
    rs = _run_status()
    paths = rs.run_paths(str(root), rid)
    rs.update(paths, rs.mark_complete)
    assert h.status(root, rid)["deliverables_status"] == "pending"
    proc = _write(skill, script, run_dir, run_dir / "report.html", rid)
    assert proc.returncode == 0, proc.stderr[-400:]
    st = h.status(root, rid)
    assert st["status"] == "complete"
    assert st["deliverables_status"] == "final"
