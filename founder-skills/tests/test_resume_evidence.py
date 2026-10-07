"""Resume evidence in `run_status.json`: which invocation this is, where it started, and what it rewrote.

A host (and a cowork-harness `artifact_json` assert) proves that a resumed invocation started at its gate
and redid nothing by reading `invocation`, `resumed_from` and `invocations[]`. Each invocation snapshots
the run dir into `runs/<id>/manifest-<n>.json`; when it ends, the run dir is compared with the snapshot by
stat and sha256 equality into `untouched_since_resume` / `touched_since_resume`. Driven through the real
`run_status.py`, `record_gate_answer.py` and a real producer. Ids and names are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
g = _load("_gates")

CONTRACT = h.REPO_ROOT / "founder-skills" / "data" / "host-contract.json"
DECK_INVENTORY = h.SKILLS / "deck-review" / "scripts" / "deck_inventory.py"
INVENTORY_INPUT = json.dumps(
    {
        "company_name": "Example Co",
        "review_date": "2026-10-07",
        "input_format": "pdf",
        "input_quality": "good",
        "total_slides": 1,
        "ai_company_status": "not_ai",
        "slides": [{"number": 1, "headline": "A headline", "content_summary": "A summary"}],
    }
)


def _out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _produce_inventory(run_dir: Path, run_id: str) -> Path:
    out = run_dir / "deck_inventory.json"
    proc = h.run(DECK_INVENTORY, "--run-id", run_id, "-o", str(out), "--pretty", stdin=INVENTORY_INPUT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


def _age(path: Path, seconds: int = 30) -> None:
    """Move a file's mtime into the past, so a rewrite in this test cannot share its timestamp."""
    past = time.time_ns() - seconds * 1_000_000_000
    os.utime(path, ns=(past, past))


def _wait(root: Path, run_id: str, gate: str) -> None:
    proc = h.record(root, run_id, "open", "--gate", gate)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert (st["status"], st["waiting_on"]) == ("waiting", gate)


def _resume(root: Path, skill: str, run_id: str) -> dict[str, Any]:
    proc = h.start(root, skill, f"FS_HOST_RUN_ID={run_id}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = _out(proc)
    assert out["resume"] == 1
    return out


def _complete(root: Path, run_id: str) -> dict[str, Any]:
    """Complete the run and close its page list, which ends the current invocation."""
    rs.update(rs.run_paths(str(root), run_id), rs.mark_complete)
    proc = h.run(h.RUN_STATUS, "deliverables", "--run-id", run_id, "--artifacts-root", str(root), "--final")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return h.status(root, run_id)


def _manifest(root: Path, run_id: str, n: int) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / "runs" / run_id / f"manifest-{n}.json").read_text(encoding="utf-8"))
    return data


# --- the redo -------------------------------------------------------------------------------------------


def test_a_resume_that_reruns_a_producer_on_the_same_input_shows_an_identical_rewrite(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    inventory = _produce_inventory(run_dir, run_id)
    (run_dir / "brief.md").write_text("synthetic brief\n", encoding="utf-8")
    _age(inventory)
    _age(run_dir / "brief.md")
    _wait(root, run_id, "ctx_basics.stage")

    out = _resume(root, "deck-review", run_id)
    assert out["invocation"] == 2
    manifest_rel = f"runs/{run_id}/manifest-2.json"
    assert (root / manifest_rel).exists(), "the resume took no snapshot of the run dir"
    st = h.status(root, run_id)
    assert st["invocations"][1]["manifest"] == manifest_rel and st["invocations"][1]["manifest_incomplete"] is False
    assert st["invocations"][1]["untouched_since_resume"] is None, "a running invocation has no partitions yet"
    assert st["invocations"][1]["reuse"] == ["deck_inventory.json"]
    files = _manifest(root, run_id, 2)["files"]
    assert set(files) == {"deck_inventory.json", "brief.md"}, "the run's own bookkeeping is not in the manifest"

    before = inventory.read_bytes()
    _produce_inventory(run_dir, run_id)
    assert inventory.read_bytes() == before, "the producer is not deterministic; this test needs it to be"
    st = _complete(root, run_id)

    entry = st["invocations"][1]
    assert entry["ended_at"] is not None
    assert entry["touched_since_resume"] == {"deck_inventory_json": {"kind": "rewritten_identical"}}
    assert "deck_inventory_json" not in entry["untouched_since_resume"]
    assert entry["untouched_since_resume"] == {"brief_md": True}


def test_known_gap_a_redo_written_outside_the_run_dir_is_not_seen(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "brief.md").write_text("synthetic brief\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    elsewhere = root / "another-place"
    elsewhere.mkdir()
    _produce_inventory(elsewhere, run_id)
    entry = _complete(root, run_id)["invocations"][1]
    assert entry["touched_since_resume"] == {}
    assert entry["untouched_since_resume"] == {"brief_md": True}


# --- the counter ----------------------------------------------------------------------------------------


def test_the_counter_counts_each_resume_and_names_the_gate_it_started_at(tmp_path: Path) -> None:
    root, run_id, _run_dir = h.start_bound(tmp_path, "deck-review")
    st = h.status(root, run_id)
    assert (st["invocation"], st["resumed_from"]) == (1, None)
    assert [e["kind"] for e in st["invocations"]] == ["start"]
    assert st["invocations"][0]["manifest"] is None, "invocation 1 starts before bind"

    for n, gate in ((2, "ctx_basics.stage"), (3, "ctx_basics.sector")):
        _wait(root, run_id, gate)
        out = _resume(root, "deck-review", run_id)
        st = h.status(root, run_id)
        assert out["invocation"] == st["invocation"] == n
        step = g.GATES[g.parse_key(gate)[0]]["step"]
        assert st["resumed_from"] == {"gate": gate, "step": step, "reason": "resume"}
        assert st["invocations"][-1]["resumed_from"] == st["resumed_from"]
        assert st["invocations"][-2]["ended_at"] is not None, "the prior invocation was not closed"
        assert (root / "runs" / run_id / f"manifest-{n}.json").exists()
        if n == 2:
            answered = h.record(root, run_id, "answer", "--gate", gate, "--answer-id", "seed")
            assert answered.returncode == 0, answered.stdout + answered.stderr

    assert [e["n"] for e in h.status(root, run_id)["invocations"]] == [1, 2, 3]
    before = h.status_path(root, run_id).read_bytes()
    proc = h.start(root, "deck-review", f"FS_HOST_RUN_ID={run_id}\n")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_IN_USE"
    assert h.status_path(root, run_id).read_bytes() == before
    assert h.status(root, run_id)["invocation"] == 3


def test_a_reopen_of_a_complete_run_is_a_new_invocation_with_a_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(g.PREDICATES, "fmr_no_cash_balance", g._pred_always)
    monkeypatch.setitem(g.REQUIRES, "fmr_cash_audit", lambda ctx, entry: True)
    root, run_id, run_dir = h.start_bound(tmp_path, "financial-model-review")
    (run_dir / "inputs.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    paths = rs.run_paths(str(root), run_id)

    def rec(**kw: Any) -> Any:
        return g.transact(paths, lambda ctx, ledger, st: g.record(ctx, ledger, "fmr_cash_followup", **kw))

    rec(resolution="default_taken", default_reason="producer_default_disclosed")
    st = rs.update(paths, lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    assert st["status"] == "complete" and st["invocations"][0]["ended_at"] is not None
    rec(answer_ids=["provided"])
    for basic, value in (("current_balance", "250000"), ("balance_date", "2026-09")):
        g.transact(
            paths,
            lambda ctx, ledger, st, b=basic, v=value: g.record(
                ctx, ledger, f"fmr_cash_basics.{b}", answer_ids=["stated"], value=v
            ),
        )
    st = h.status(root, run_id)
    assert (st["status"], st["invocation"]) == ("running", 2)
    step = g.GATES["fmr_cash_followup"]["step"]
    assert st["resumed_from"] == {"gate": "fmr_cash_followup", "step": step, "reason": "reopened"}
    entry = st["invocations"][1]
    assert (entry["kind"], entry["manifest"]) == ("reopen", f"runs/{run_id}/manifest-2.json")
    assert set(_manifest(root, run_id, 2)["files"]) == {"inputs.json"}
    assert entry["ended_at"] is None


# --- null means no manifest -------------------------------------------------------------------------------


def test_a_resume_before_bind_has_no_manifest_and_no_partitions(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "cap-table")
    finish = ("finish", "--run-id", run_id, "--artifacts-root", str(root), "--mode", "rule_lookup")
    proc = h.run(h.RUN_STATUS, *finish, "--lookup-status", "escalate")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert _resume(root, "cap-table", run_id)["invocation"] == 2
    entry = h.status(root, run_id)["invocations"][1]
    assert entry["manifest"] is None and entry["manifest_incomplete"] is None
    assert not (root / "runs" / run_id / "manifest-2.json").exists()
    answered = h.record(root, run_id, "answer", "--gate", "ct_rule_lookup_fact", "--answer-id", "unknown")
    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert h.run(h.RUN_STATUS, *finish, "--lookup-status", "escalate").returncode == 0
    entry = h.status(root, run_id)["invocations"][1]
    assert entry["ended_at"] is not None
    assert entry["untouched_since_resume"] is None and entry["touched_since_resume"] is None


@pytest.fixture
def locked_dir(tmp_path: Path) -> Iterator[Path]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("permissions do not bind the superuser")
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    locked = run_dir / "locked"
    locked.mkdir()
    (locked / "inner.json").write_text("{}\n", encoding="utf-8")
    locked.chmod(0)
    try:
        yield root
    finally:
        locked.chmod(0o755)


def test_an_unreadable_subtree_makes_the_manifest_incomplete_and_the_partitions_null(locked_dir: Path) -> None:
    root = locked_dir
    run_id = os.listdir(root / "runs")[0]
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    entry = h.status(root, run_id)["invocations"][1]
    assert entry["manifest"] is not None and entry["manifest_incomplete"] is True
    entry = _complete(root, run_id)["invocations"][1]
    assert entry["untouched_since_resume"] is None and entry["touched_since_resume"] is None


# --- comparison by content, not by clock -------------------------------------------------------------------


def test_a_changed_file_whose_mtime_was_set_back_is_changed(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    target = run_dir / "a.json"
    target.write_text('{"v": 1}\n', encoding="utf-8")
    _age(target)
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    recorded = _manifest(root, run_id, 2)["files"]["a.json"]
    target.write_text('{"v": 2}\n', encoding="utf-8")
    os.utime(target, ns=(recorded["mtime_ns"], recorded["mtime_ns"]))
    now = os.stat(target)
    assert (now.st_size, now.st_mtime_ns) == (recorded["size"], recorded["mtime_ns"])
    entry = _complete(root, run_id)["invocations"][1]
    assert entry["touched_since_resume"] == {"a_json": {"kind": "changed"}}
    assert entry["untouched_since_resume"] == {}


def test_added_and_removed_files_are_named(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "old.json").write_text("{}\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    (run_dir / "old.json").unlink()
    (run_dir / "sub").mkdir()
    (run_dir / "sub" / "new.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "sub" / "x.json.tmp-123").write_text("{}\n", encoding="utf-8")
    touched = _complete(root, run_id)["invocations"][1]["touched_since_resume"]
    assert touched == {"old_json": {"kind": "removed"}, "sub_new_json": {"kind": "added"}}


# --- keys ---------------------------------------------------------------------------------------------------


def test_the_key_transform_and_its_collisions_are_deterministic() -> None:
    paths = ["x.json", "a_b.json", "a/b.json", "a.b/json", "a_b_json__2"]
    assert rs.evidence_keys(paths) == {
        "a.b/json": "a_b_json",
        "a/b.json": "a_b_json__2",
        "a_b.json": "a_b_json__3",
        "a_b_json__2": "a_b_json__2__2",
        "x.json": "x_json",
    }
    assert rs.evidence_keys(reversed(paths)) == rs.evidence_keys(paths)


def test_colliding_files_in_a_run_dir_get_distinct_keys(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "a.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "a_json").write_text("{}\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    entry = _complete(root, run_id)["invocations"][1]
    assert entry["untouched_since_resume"] == {"a_json": True, "a_json__2": True}


# --- the contract ---------------------------------------------------------------------------------------------


def test_the_contract_publishes_the_fields_the_note_and_the_key_transform() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["run_status_fields"][-3:] == ["invocation", "resumed_from", "invocations"]
    assert any(n.startswith("`untouched_since_resume` lists the run-dir files") for n in data["notes"])
    assert any("`null` means no manifest could be taken, never that nothing ran." in n for n in data["notes"])
    assert "every `.` and `/` replaced by `_`" in data["shapes"]["evidence_key"]
    assert "skipping any key already taken" in data["shapes"]["evidence_key"]
    assert "`a_b_json__2__2`" in data["shapes"]["evidence_key"]
    assert "(`cp -p`, `copy2`, `rsync -t`) or a permission change is untouched" in data["shapes"]["invocations"]
    assert "`maps_dropped: true`" in data["shapes"]["invocations"]
    assert "when `deliverables_status` turns `final`" in data["shapes"]["invocations"]
    assert data["shapes"]["touched_kinds"] == ["changed", "rewritten_identical", "added", "removed"]


# --- when an invocation ends ----------------------------------------------------------------------------------


def test_pages_written_after_coaching_belong_to_the_invocation_that_wrote_them(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    report_md, report_html = run_dir / "report.md", run_dir / "report.html"
    report_md.write_text("draft\n", encoding="utf-8")
    report_html.write_text("old page\n", encoding="utf-8")
    _age(report_md)
    _age(report_html)
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    paths = rs.run_paths(str(root), run_id)
    report_md.write_text("draft with coaching\n", encoding="utf-8")
    st = rs.complete_after_coaching(paths, str(report_md), None)
    assert (st["status"], st["deliverables_status"]) == ("complete", "pending")
    assert st["invocations"][1]["ended_at"] is None, "the page still to come belongs to this invocation"
    report_html.write_text("the new page\n", encoding="utf-8")
    st = rs.add_deliverable(paths, "report_html", str(report_html), rs.file_sha256(str(report_html)), "visualize.py")
    entry = st["invocations"][1]
    assert st["deliverables_status"] == "final" and entry["ended_at"] is not None
    assert entry["touched_since_resume"] == {"report_html": {"kind": "changed"}, "report_md": {"kind": "changed"}}


def test_a_skill_with_no_pages_after_coaching_ends_the_invocation_at_the_insert(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "financial-model-review")
    report_md = run_dir / "report.md"
    report_md.write_text("draft\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "financial-model-review", run_id)
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    st = rs.complete_after_coaching(rs.run_paths(str(root), run_id), str(report_md), None)
    assert st["status"] == "complete" and st["invocations"][1]["ended_at"] is not None
    assert st["invocations"][1]["untouched_since_resume"] == {"report_md": True}


def test_a_declined_run_ends_its_invocation(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "brief.md").write_text("synthetic brief\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    proc = h.record(root, run_id, "answer", "--gate", "dr_input_request.gated_link", "--answer-id", "stop")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")
    entry = st["invocations"][1]
    assert entry["ended_at"] is not None and entry["untouched_since_resume"] == {"brief_md": True}
    assert entry["counts"] == {"untouched": 1, "changed": 0, "rewritten_identical": 0, "added": 0, "removed": 0}


def test_closing_twice_changes_nothing(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "brief.md").write_text("synthetic brief\n", encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    st = _complete(root, run_id)
    once = json.dumps(st["invocations"], sort_keys=True)
    (run_dir / "late.json").write_text("{}\n", encoding="utf-8")
    assert rs.close_invocation(st) is None
    assert json.dumps(st["invocations"], sort_keys=True) == once


def test_only_the_two_latest_ended_invocations_keep_their_key_maps(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    (run_dir / "brief.md").write_text("synthetic brief\n", encoding="utf-8")
    for gate, answer in (("ctx_basics.stage", "seed"), ("ctx_basics.sector", "not_sure"), ("ctx_basics.geography", "")):
        _wait(root, run_id, gate)
        _resume(root, "deck-review", run_id)
        if answer:
            assert h.record(root, run_id, "answer", "--gate", gate, "--answer-id", answer).returncode == 0
    entries = _complete(root, run_id)["invocations"]
    assert [e["n"] for e in entries] == [1, 2, 3, 4]
    assert [e["maps_dropped"] for e in entries] == [False, True, False, False]
    assert entries[1]["untouched_since_resume"] is None and entries[1]["touched_since_resume"] is None
    assert entries[1]["counts"]["untouched"] == 1
    for e in entries[2:]:
        assert e["untouched_since_resume"] == {"brief_md": True}


def test_a_status_from_before_invocations_were_recorded_opens_invocation_1_as_a_start(tmp_path: Path) -> None:
    root, run_id, _run_dir = h.start_bound(tmp_path, "deck-review")
    st = h.status(root, run_id)
    for key in ("invocation", "resumed_from", "invocations"):
        del st[key]
    entry = rs.open_invocation(st, "resume", {"gate": "ctx_basics.stage", "step": "0", "reason": "resume"})
    assert (st["invocation"], st["resumed_from"]) == (1, None)
    assert (entry["n"], entry["kind"], entry["resumed_from"]) == (1, "start", None)


# --- the comparison at the end hashes again -------------------------------------------------------------------


def _complete_in_process(root: Path, run_id: str) -> dict[str, Any]:
    def fn(st: dict[str, Any]) -> None:
        rs.mark_complete(st)
        st["deliverables_status"] = "final"

    status: dict[str, Any] = rs.update(rs.run_paths(str(root), run_id), fn)
    return status


def test_a_rewrite_that_keeps_every_stat_field_is_still_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    target = run_dir / "a.json"
    target.write_text('{"v": 1}\n', encoding="utf-8")
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    recorded = _manifest(root, run_id, 2)["files"]["a.json"]
    target.write_text('{"v": 2}\n', encoding="utf-8")
    real_lstat = os.lstat

    def frozen(path: Any, *args: Any, **kwargs: Any) -> Any:
        st = real_lstat(path, *args, **kwargs)
        if os.path.abspath(path) != str(target):
            return st
        # The stat a coarse clock gives a same-size rewrite inside one tick, in place.
        return SimpleNamespace(
            st_mode=st.st_mode,
            st_size=recorded["size"],
            st_mtime_ns=recorded["mtime_ns"],
            st_ctime_ns=recorded["ctime_ns"],
            st_ino=recorded["ino"],
        )

    monkeypatch.setattr(os, "lstat", frozen)
    entry = _complete_in_process(root, run_id)["invocations"][1]
    assert entry["touched_since_resume"] == {"a_json": {"kind": "changed"}}


def test_an_atomic_replace_changes_the_inode_in_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{}\n", encoding="utf-8")
    before, _ = rs.snapshot_run_dir(str(tmp_path))
    (tmp_path / "b.tmp").write_text("{}\n", encoding="utf-8")
    os.replace(tmp_path / "b.tmp", tmp_path / "a.json")
    after, _ = rs.snapshot_run_dir(str(tmp_path), prior=before)
    assert before["a.json"]["ino"] != after["a.json"]["ino"]


def test_an_identical_copy_that_kept_its_mtime_or_a_permission_change_is_untouched(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    a, b = run_dir / "a.json", run_dir / "b.json"
    for p in (a, b):
        p.write_text('{"v": 1}\n', encoding="utf-8")
        _age(p)
    _wait(root, run_id, "ctx_basics.stage")
    _resume(root, "deck-review", run_id)
    a.chmod(0o600)
    kept = os.stat(b)
    b.write_text('{"v": 1}\n', encoding="utf-8")
    os.utime(b, ns=(kept.st_atime_ns, kept.st_mtime_ns))
    entry = _complete(root, run_id)["invocations"][1]
    assert entry["untouched_since_resume"] == {"a_json": True, "b_json": True}
    assert entry["touched_since_resume"] == {}


def test_a_rejected_reopen_writes_no_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(g.PREDICATES, "fmr_no_cash_balance", g._pred_always)
    monkeypatch.setitem(g.REQUIRES, "fmr_cash_audit", lambda ctx, entry: True)
    root, run_id, run_dir = h.start_bound(tmp_path, "financial-model-review")
    (run_dir / "inputs.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    paths = rs.run_paths(str(root), run_id)
    key = "fmr_cash_followup"
    g.transact(
        paths,
        lambda c, led, s: g.record(
            c, led, key, resolution="default_taken", default_reason="producer_default_disclosed"
        ),
    )
    rs.update(paths, lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    before = h.snapshot(root, run_id)

    def reopen_then_reject(c: Any, led: dict[str, Any], s: dict[str, Any]) -> Any:
        g.record(c, led, key, answer_ids=["provided"])
        raise g.GateRejection("ANSWER_STANDS", "a later segment was refused")

    with pytest.raises(g.GateRejection):
        g.transact(paths, reopen_then_reject)
    assert h.snapshot(root, run_id) == before
    assert not (root / "runs" / run_id / "manifest-2.json").exists()


# --- the walk's limits --------------------------------------------------------------------------------------------


def test_the_walk_stops_at_its_file_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a.json", "b.json", "c.json"):
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(rs, "MANIFEST_MAX_FILES", 2)
    files, complete = rs.snapshot_run_dir(str(tmp_path))
    assert (sorted(files), complete) == (["a.json", "b.json"], False)


def test_the_hash_budget_records_by_stat_in_a_manifest_and_makes_a_comparison_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text("12345678", encoding="utf-8")
    monkeypatch.setattr(rs, "MANIFEST_SHA_BUDGET", 10)
    files, complete = rs.snapshot_run_dir(str(tmp_path))
    assert complete and files["a.json"]["sha256"] is not None and files["b.json"]["sha256"] is None
    _files, complete = rs.snapshot_run_dir(str(tmp_path), prior=files, rehash=True)
    assert complete is False


def test_symlinks_are_neither_followed_nor_recorded(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "real").mkdir(parents=True)
    (run_dir / "real" / "a.json").write_text("{}\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "link.json").symlink_to(run_dir / "real" / "a.json")
    (run_dir / "linked_dir").symlink_to(outside, target_is_directory=True)
    files, complete = rs.snapshot_run_dir(str(run_dir))
    assert (sorted(files), complete) == (["real/a.json"], True)


def test_a_comparison_out_of_budget_does_not_leave_the_next_invocation_without_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    for name in ("a.json", "b.json"):
        (run_dir / name).write_text("12345678", encoding="utf-8")
    paths = rs.run_paths(str(root), run_id)
    resumed = {"gate": "ctx_basics.stage", "step": "0", "reason": "resume"}
    monkeypatch.setattr(rs, "MANIFEST_SHA_BUDGET", 10)
    rs.update(paths, lambda st: rs.open_invocation(st, "resume", resumed))
    st = rs.update(paths, lambda st: rs.open_invocation(st, "resume", resumed))
    closed, current = st["invocations"][1], st["invocations"][2]
    assert closed["ended_at"] is not None and closed["untouched_since_resume"] is None, "the comparison ran out"
    assert current["manifest"] is not None and current["manifest_incomplete"] is False
    monkeypatch.setattr(rs, "MANIFEST_SHA_BUDGET", 1 << 20)
    entry = _complete_in_process(root, run_id)["invocations"][2]
    assert entry["untouched_since_resume"] == {"a_json": True, "b_json": True}
    assert entry["touched_since_resume"] == {}


# --- deck-review: a resume at the stage question -----------------------------------------------------------

DR_SCRIPTS = h.SKILLS / "deck-review" / "scripts"
DR_PROFILE_BODY = {
    k: v
    for k, v in json.loads(
        (h.REPO_ROOT / "founder-skills/tests/fixtures/deck-review/stage_profile.json").read_text(encoding="utf-8")
    ).items()
    if k != "metadata"
}
DR_STAGE_BODY = {
    "gate_id": "stage_confirmation",
    "question": "Does this stage detection look right?",
    "options": ["Looks right", "Different stage", "Not sure — proceed anyway"],
    "context_summary": "Detected from the deck's slides and its stated raise.",
}
# The files a resume at deck-review's stage question must leave as they were: Steps 2-3's checkpoints. The
# gate file is rewritten by design (the emit that applies the answer), and the report is new.
DR_KEPT_ON_RESUME = frozenset(("stage_profile_json", "deck_inventory_json"))


def _dr(script: str, *args: str, stdin: str | None = None) -> dict[str, Any]:
    proc = h.run(DR_SCRIPTS / script, *args, stdin=stdin)
    assert proc.returncode == 0, (script, proc.stdout, proc.stderr)
    return _out(proc)


def _dr_setup(root: Path, run_id: str) -> dict[str, Any]:
    return _dr("setup_run.py", "--artifacts-root", str(root), "--slug", "example-co", "--run-id", run_id, "--clean")


def _dr_emit(run_dir: Path, run_id: str, stage: str, body: dict[str, Any] = DR_STAGE_BODY) -> dict[str, Any]:
    out = run_dir / "gate_state.json"
    return _dr("gate_state.py", "emit", "--run-id", run_id, "--stage", stage, "-o", str(out), stdin=json.dumps(body))


def _dr_first_invocation(tmp: Path) -> tuple[Path, str, Path]:
    """Step 0 to the stage question, in the skill's order: start, Step 1's questions and `init`,
    `setup_run --clean`, `bind`, Steps 2-3's producers, then the emit that waits."""
    root = tmp / "artifacts"
    root.mkdir()
    run_id = h.start_ok(root, "deck-review")
    keys = ["ctx_basics.company_name", "ctx_basics.stage", "ctx_basics.sector", "ctx_basics.geography"]
    assert h.record(root, run_id, "open", *[a for k in keys for a in ("--gate", k)]).returncode == 0
    answers = [
        ("ctx_basics.company_name", "use_derived", "Example Co"),
        ("ctx_basics.stage", "seed", None),
        ("ctx_basics.sector", "use_derived", "fintech"),
        ("ctx_basics.geography", "use_derived", "US"),
    ]
    segs: list[str] = []
    for key, oid, value in answers:
        segs += ["--gate", key, "--answer-id", oid] + (["--value", value] if value else [])
    assert h.record(root, run_id, "answer", *segs).returncode == 0
    init = h.run(
        h.SHARED / "founder_context.py",
        "init",
        "--company-name",
        "Example Co",
        "--stage",
        "seed",
        "--sector",
        "fintech",
        "--geography",
        "US",
        "--artifacts-root",
        str(root),
        "--run-id",
        run_id,
        "--skill",
        "deck-review",
    )
    assert init.returncode == 0, init.stdout + init.stderr
    assert _dr_setup(root, run_id)["cleaned"] is True
    run_dir = root / "deck-review-example-co"
    assert h.bind(root, run_id, run_dir, "example-co").returncode == 0
    inventory = _produce_inventory(run_dir, run_id)
    profile = run_dir / "stage_profile.json"
    _dr("stage_profile.py", "--run-id", run_id, "-o", str(profile), stdin=json.dumps(DR_PROFILE_BODY))
    _age(inventory)
    _age(profile)
    assert "needs_input" in _dr_emit(run_dir, run_id, "seed")
    st = h.status(root, run_id)
    assert (st["status"], st["waiting_on"]) == ("waiting", "stage_confirmation")
    return root, run_id, run_dir


def _dr_resume(root: Path, run_id: str, answer: str) -> dict[str, Any]:
    proc = h.start(root, "deck-review", f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER {answer}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = _out(proc)
    assert (out["resume"], out["resume_step"]) == (1, "3")
    read = h.run(
        h.SHARED / "founder_context.py",
        "read",
        "--artifacts-root",
        str(root),
        "--run-id",
        run_id,
        "--skill",
        "deck-review",
    )
    assert read.returncode == 0, read.stderr
    return out


def test_a_deck_review_resume_at_the_stage_gate_rewrites_only_the_gate(tmp_path: Path) -> None:
    root, run_id, run_dir = _dr_first_invocation(tmp_path)
    kept = {n: (run_dir / n).read_bytes() for n in ("deck_inventory.json", "stage_profile.json")}

    _dr_resume(root, run_id, "stage_confirmation=looks_right")
    setup = _dr_setup(root, run_id)
    assert (setup["cleaned"], setup["reuse_checkpoints"], setup["gate_action"]) == (False, True, "reask")
    assert {n: (run_dir / n).read_bytes() for n in kept} == kept
    assert h.bind(root, run_id, run_dir, "example-co").returncode == 0
    emitted = _dr_emit(run_dir, run_id, "seed")
    assert "needs_input" not in emitted and emitted["answered"]["answer_source"] == "host"
    after = _dr_setup(root, run_id)
    assert (after["resume"], after["gate_action"]) == (True, "continue")
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    st = _complete(root, run_id)

    entry = st["invocations"][1]
    assert set(entry["untouched_since_resume"]) == DR_KEPT_ON_RESUME
    assert all(entry["untouched_since_resume"].values())
    assert entry["touched_since_resume"] == {"gate_state_json": {"kind": "changed"}, "report_md": {"kind": "added"}}


def test_a_deck_review_resume_at_the_stage_pick_keeps_the_pick_and_settles_every_gate(tmp_path: Path) -> None:
    root, run_id, run_dir = _dr_first_invocation(tmp_path)
    ans = h.run(
        DR_SCRIPTS / "gate_state.py",
        "answer",
        "--file",
        str(run_dir / "gate_state.json"),
        "--answer",
        "Different stage",
        "--source",
        "founder",
    )
    assert ans.returncode == 0, ans.stderr
    pick_body = {
        "gate_id": "stage_choice",
        "question": "Which stage is this deck?",
        "options": ["Pre-seed", "Series A", "Series B", "Growth"],
        "context_summary": "Detected from the deck's slides and its stated raise.",
    }
    assert "needs_input" in _dr_emit(run_dir, run_id, "seed", pick_body)
    assert h.status(root, run_id)["waiting_on"] == "stage_choice"

    _dr_resume(root, run_id, "stage_choice=series_a")
    assert _dr_setup(root, run_id)["reuse_checkpoints"] is True
    picked = _dr_emit(run_dir, run_id, "seed", pick_body)
    assert picked["answered"] == {"gate_id": "stage_choice", "answer": "Series A", "answer_source": "host"}
    assert _dr_setup(root, run_id)["gate_action"] == "rebuild"
    current = (run_dir / "stage_profile.json").read_text(encoding="utf-8")
    _dr(
        "stage_profile.py",
        "--rebuild-stage",
        "series_a",
        "--confidence",
        "high",
        "--run-id",
        run_id,
        "-o",
        str(run_dir / "stage_profile.json"),
        stdin=current,
    )
    assert "needs_input" in _dr_emit(run_dir, run_id, "series_a")
    ans = h.run(
        DR_SCRIPTS / "gate_state.py",
        "answer",
        "--file",
        str(run_dir / "gate_state.json"),
        "--answer",
        "Looks right",
        "--source",
        "founder",
    )
    assert ans.returncode == 0, ans.stderr
    led = h.ledger(root, run_id)["gates"]
    assert (led["stage_choice"]["current"]["answer_id"], led["stage_choice"]["supersessions"]) == ("series_a", 0)
    assert sorted(k for k, e in led.items() if e["state"] == "open") == []
    assert h.status(root, run_id)["status"] == "running"
    assert _dr_setup(root, run_id)["gate_action"] == "continue"


def test_a_fresh_deck_review_run_still_cleans_a_prior_runs_files(tmp_path: Path) -> None:
    root, old_id, run_dir = h.start_bound(tmp_path, "deck-review")
    _produce_inventory(run_dir, old_id)
    new_id = h.start_ok(root, "deck-review")
    out = _dr_setup(root, new_id)
    assert (out["cleaned"], out["reuse_checkpoints"]) == (True, False)
    assert not (run_dir / "deck_inventory.json").exists()


# --- financial-model-review: a host's corrections resume at the values check -------------------------------

FMR_SCRIPTS = h.SKILLS / "financial-model-review" / "scripts"
FMR_FIXTURE = h.REPO_ROOT / "founder-skills" / "tests" / "fixtures" / "financial-model-review" / "inputs.json"
# What the waiting run already holds and the resumed invocation must not rewrite: the extraction, the inputs
# review's hand-off, and the host's corrections call (made while the run waited, before the resume began).
FMR_KEPT_ON_RESUME = frozenset(
    (
        "model_data_json",
        "corrected_inputs_json",
        "extraction_corrections_json",
        "extraction_corrections_history_jsonl",
    )
)


def _fmr_ok(proc: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _fmr_first_invocation(tmp: Path) -> tuple[Path, str, Path]:
    root, run_id, run_dir = h.start_bound(tmp, "financial-model-review")
    rec = lambda *a: _fmr_ok(h.record(root, run_id, *a))  # noqa: E731
    rec(
        "open",
        "--gate",
        "ctx_basics.company_name",
        "--gate",
        "ctx_basics.stage",
        "--gate",
        "ctx_basics.sector",
        "--gate",
        "ctx_basics.geography",
        "--gate",
        "fmr_cash_basics.current_balance",
        "--gate",
        "fmr_cash_basics.balance_date",
        "--gate",
        "fmr_cash_basics.monthly_burn",
    )
    rec(
        "answer",
        "--gate",
        "ctx_basics.company_name",
        "--answer-id",
        "use_derived",
        "--value",
        "Example Co",
        "--gate",
        "ctx_basics.stage",
        "--answer-id",
        "seed",
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "use_derived",
        "--value",
        "B2B SaaS",
        "--gate",
        "ctx_basics.geography",
        "--answer-id",
        "use_derived",
        "--value",
        "US",
        "--gate",
        "fmr_cash_basics.current_balance",
        "--answer-id",
        "stated",
        "--value",
        "1500000",
        "--gate",
        "fmr_cash_basics.balance_date",
        "--answer-id",
        "stated",
        "--value",
        "2026-05",
        "--gate",
        "fmr_cash_basics.monthly_burn",
        "--answer-id",
        "stated",
        "--value",
        "120000",
    )
    _fmr_ok(
        h.run(
            h.SHARED / "founder_context.py",
            "init",
            "--company-name",
            "Example Co",
            "--stage",
            "seed",
            "--sector",
            "B2B SaaS",
            "--geography",
            "US",
            "--artifacts-root",
            str(root),
            "--run-id",
            run_id,
            "--skill",
            "financial-model-review",
        )
    )
    (run_dir / "model_data.json").write_text('{"sheets": []}\n', encoding="utf-8")
    inputs = json.loads(FMR_FIXTURE.read_text(encoding="utf-8"))
    inputs["metadata"]["run_id"] = run_id
    handoff = run_dir / "handoff" / run_id / "inputs_review_output.json"
    handoff.write_text(json.dumps({"corrected": inputs, "corrections": []}), encoding="utf-8")
    (run_dir / "inputs.json").write_text("{}\n", encoding="utf-8")
    _fmr_ok(
        h.run(
            FMR_SCRIPTS / "apply_corrections.py",
            str(handoff),
            "--original",
            str(run_dir / "inputs.json"),
            "--output-dir",
            str(run_dir),
            "--run-id",
            run_id,
            "--origin",
            "inputs_review",
        )
    )
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    (run_dir / "extraction_validation.json").write_text('{"status": "pass"}\n', encoding="utf-8")
    _wait(root, run_id, "fmr_extracted_values")
    time.sleep(0.002)
    # The host corrects the values itself while the run waits.
    _fmr_ok(
        h.run(
            FMR_SCRIPTS / "apply_corrections.py",
            "--set",
            "cash.monthly_net_burn=110000",
            "--original",
            str(run_dir / "inputs.json"),
            "--output-dir",
            str(run_dir),
            "--run-id",
            run_id,
            "--origin",
            "external",
        )
    )
    for f in run_dir.rglob("*"):
        if f.is_file():
            _age(f)
    return root, run_id, run_dir


def test_a_financial_model_review_resume_with_host_corrections_rewrites_only_what_the_values_check_owns(
    tmp_path: Path,
) -> None:
    root, run_id, run_dir = _fmr_first_invocation(tmp_path)
    proc = h.start(
        root,
        "financial-model-review",
        f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER fmr_extracted_values=corrections_applied\n",
    )
    out = _out(_fmr_ok(proc))
    assert (out["resume"], out["resume_step"]) == (1, "3.6")
    _fmr_ok(
        h.run(
            h.SHARED / "founder_context.py",
            "read",
            "--artifacts-root",
            str(root),
            "--run-id",
            run_id,
            "--skill",
            "financial-model-review",
        )
    )
    _fmr_ok(h.bind(root, run_id, run_dir, "example-co"))
    # SKILL.md: promote and re-run Step 3.5 before Step 3.6's open.
    shutil.copy(run_dir / "corrected_inputs.json", run_dir / "inputs.json")
    _fmr_ok(
        h.run(
            FMR_SCRIPTS / "validate_inputs.py",
            "--fix",
            "-o",
            str(run_dir / "inputs.json"),
            stdin=(run_dir / "inputs.json").read_text(encoding="utf-8"),
        )
    )
    (run_dir / "extraction_validation.json").write_text('{"status": "pass", "rerun": true}\n', encoding="utf-8")
    opened = _out(_fmr_ok(h.record(root, run_id, "open", "--gate", "fmr_extracted_values")))
    assert opened["applied"] == "pre_answer"
    cur = h.ledger(root, run_id)["gates"]["fmr_extracted_values"]["current"]
    assert (cur["answer_id"], cur["evidence"]["origin"]) == ("corrections_applied", "external")
    for script in ("unit_economics.py", "runway.py"):
        _fmr_ok(
            h.run(
                FMR_SCRIPTS / script,
                "--run-id",
                run_id,
                "-o",
                str(run_dir / script.replace(".py", ".json")),
                stdin=(run_dir / "inputs.json").read_text(encoding="utf-8"),
            )
        )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    st = _complete(root, run_id)

    entry = st["invocations"][1]
    untouched = {k for k in entry["untouched_since_resume"] if not k.startswith("handoff_")}
    assert untouched == FMR_KEPT_ON_RESUME
    assert all(entry["untouched_since_resume"].values())
    touched = entry["touched_since_resume"]
    assert touched["inputs_json"]["kind"] in ("changed", "rewritten_identical")
    assert touched["extraction_validation_json"]["kind"] == "changed"
    assert {"unit_economics_json", "runway_json", "report_md"} <= set(touched)


def test_a_financial_model_review_resume_whose_host_skipped_the_run_id_asks_the_founder(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "financial-model-review")
    inputs = json.loads(FMR_FIXTURE.read_text(encoding="utf-8"))
    inputs["metadata"]["run_id"] = run_id
    (run_dir / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    _wait(root, run_id, "fmr_extracted_values")
    time.sleep(0.002)
    _fmr_ok(
        h.run(
            FMR_SCRIPTS / "apply_corrections.py",
            "--set",
            "cash.monthly_net_burn=110000",
            "--original",
            str(run_dir / "inputs.json"),
            "--output-dir",
            str(run_dir),
        )
    )
    _fmr_ok(
        h.start(
            root,
            "financial-model-review",
            f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER fmr_extracted_values=corrections_applied\n",
        )
    )
    opened = _out(_fmr_ok(h.record(root, run_id, "open", "--gate", "fmr_extracted_values")))
    assert "applied" not in opened and opened["needs_input"]
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("waiting", "PRE_ANSWER_UNLISTED")
    assert any(n["code"] == "PRE_ANSWER_NOT_APPLIED" for n in st["notices"])


# --- market-sizing: a resume at the approach question ------------------------------------------------------

MS_SCRIPTS = h.SKILLS / "market-sizing" / "scripts"
# What Steps 2-3 wrote before the approach question: a resume at the Gate never rewrites them.
MS_KEPT_ON_RESUME = frozenset(("inputs_json", "methodology_json"))


def _ms_first_invocation(tmp: Path) -> tuple[Path, str, Path]:
    root, run_id, run_dir = h.start_bound(tmp, "market-sizing")
    rec = lambda *a: _fmr_ok(h.record(root, run_id, *a))  # noqa: E731
    keys = ("ctx_basics.company_name", "ctx_basics.stage", "ctx_basics.sector", "ctx_basics.geography")
    rec("open", *[a for k in keys for a in ("--gate", k)])
    rec(
        "answer",
        "--gate",
        "ctx_basics.company_name",
        "--answer-id",
        "use_derived",
        "--value",
        "Example Co",
        "--gate",
        "ctx_basics.stage",
        "--answer-id",
        "seed",
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "use_derived",
        "--value",
        "B2B SaaS",
        "--gate",
        "ctx_basics.geography",
        "--answer-id",
        "use_derived",
        "--value",
        "US",
    )
    _fmr_ok(
        h.run(
            h.SHARED / "founder_context.py",
            "init",
            "--company-name",
            "Example Co",
            "--stage",
            "seed",
            "--sector",
            "B2B SaaS",
            "--geography",
            "US",
            "--artifacts-root",
            str(root),
            "--run-id",
            run_id,
            "--skill",
            "market-sizing",
        )
    )
    inputs = {
        "company_name": "Example Co",
        "currency": "USD",
        "founder_stated_inputs": {"arpu": 90},
        "founder_stated_inputs_period": {"arpu": "month"},
        "founder_stated_alternatives": {"arpu": [{"value": 110, "period": "month", "source": "chat"}]},
        "metadata": {"run_id": run_id},
    }
    (run_dir / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    methodology = {"approach_chosen": "bottom_up", "rationale": "x", "metadata": {"run_id": run_id}}
    (run_dir / "methodology.json").write_text(json.dumps(methodology), encoding="utf-8")
    rec("open", "--gate", "ms_two_figures.arpu")
    rec("answer", "--gate", "ms_two_figures.arpu", "--answer-id", "typed")
    _wait(root, run_id, "ms_methodology")
    return root, run_id, run_dir


def test_a_market_sizing_resume_at_the_approach_question_rewrites_only_what_follows_it(tmp_path: Path) -> None:
    root, run_id, run_dir = _ms_first_invocation(tmp_path)
    for f in run_dir.glob("*.json"):
        _age(f)
    out = _out(
        _fmr_ok(h.start(root, "market-sizing", f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ms_methodology=looks_good\n"))
    )
    assert (out["resume"], out["resume_step"]) == (1, "3")
    _fmr_ok(
        h.run(
            h.SHARED / "founder_context.py",
            "read",
            "--artifacts-root",
            str(root),
            "--run-id",
            run_id,
            "--skill",
            "market-sizing",
        )
    )
    _fmr_ok(h.bind(root, run_id, run_dir, "example-co"))
    opened = json.loads(_fmr_ok(h.record(root, run_id, "open", "--gate", "ms_methodology")).stdout)
    assert opened["applied"] == "pre_answer"
    # Step 4, then the sizing: the real generator prints, the real calculator sizes by reference.
    validation = {
        "sources": [{"title": "Example Report", "url": "https://example.org/r"}],
        "assumptions": [
            {
                "name": "accounts",
                "value": 42000,
                "unit": "count",
                "category": "sourced",
                "source_title": "Example Report",
                "source_url": "https://example.org/r",
            },
            {"name": "reachable", "value": 30, "unit": "percent_points", "category": "derived"},
            {"name": "capture", "value": 4, "unit": "percent_points", "category": "agent_estimate"},
        ],
        "metadata": {"run_id": run_id},
    }
    (run_dir / "validation.json").write_text(json.dumps(validation), encoding="utf-8")
    hand = run_dir / "handoff" / run_id
    _fmr_ok(
        h.run(
            MS_SCRIPTS / "dispatch_prompt.py",
            "bottom_up_methodology",
            "--run-id",
            run_id,
            "--analysis-dir",
            str(run_dir),
            "--handoff-dir",
            str(hand),
            "--handoff-agent",
            str(hand),
        )
    )
    refs = {
        "approach": "bottom_up",
        "customer_count": {"assumption": "accounts"},
        "serviceable_pct": {"assumption": "reachable"},
        "arpu": {"founder_stated": "arpu"},
        "target_pct": {"assumption": "capture"},
    }
    _fmr_ok(
        h.run(
            MS_SCRIPTS / "market_sizing.py",
            "--stdin",
            "--run-id",
            run_id,
            "--validation",
            str(run_dir / "validation.json"),
            "--inputs",
            str(run_dir / "inputs.json"),
            "-o",
            str(run_dir / "sizing.json"),
            stdin=json.dumps(refs),
        )
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    st = _complete(root, run_id)

    entry = st["invocations"][1]
    untouched = {k for k in entry["untouched_since_resume"] if not k.startswith("handoff_")}
    assert untouched == MS_KEPT_ON_RESUME
    touched = entry["touched_since_resume"]
    assert {"validation_json", "sizing_json", "report_md"} <= set(touched)


# --- ic-sim: a resume at the decline question --------------------------------------------------------------

IC_SCRIPTS = h.SKILLS / "ic-sim" / "scripts"
IC_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ic-sim"
# Steps 2-8's files: a resume at 8.5 writes none of them again.
IC_KEPT_ON_RESUME = frozenset(
    (
        "startup_profile_json",
        "prior_artifacts_json",
        "fund_profile_json",
        "conflict_check_json",
        "partner_assessment_visionary_json",
        "partner_assessment_operator_json",
        "partner_assessment_analyst_json",
        "partner_rebuttal_visionary_json",
        "partner_rebuttal_operator_json",
        "partner_rebuttal_analyst_json",
        "discussion_json",
        "score_dimensions_json",
    )
)


def _ic_fixture(name: str, run_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((IC_FIXTURES / name).read_text(encoding="utf-8"))
    data["metadata"] = {"run_id": run_id}
    return data


def _ic_first_invocation(tmp: Path) -> tuple[Path, str, Path]:
    """Steps 1-8 of a simulation that scores a Decline, ending with the founder's hold-off."""
    root, run_id, run_dir = h.start_bound(tmp, "ic-sim")
    rec = lambda *a: _fmr_ok(h.record(root, run_id, *a))  # noqa: E731
    keys = ("ctx_basics.company_name", "ctx_basics.stage", "ctx_basics.sector", "ctx_basics.geography")
    rec("open", *[a for k in (*keys, "ic_mode", "ic_fund_mode") for a in ("--gate", k)])
    rec(
        "answer",
        *("--gate", "ctx_basics.company_name", "--answer-id", "use_derived", "--value", "Example Co"),
        *("--gate", "ctx_basics.stage", "--answer-id", "seed"),
        *("--gate", "ctx_basics.sector", "--answer-id", "use_derived", "--value", "B2B SaaS"),
        *("--gate", "ctx_basics.geography", "--answer-id", "use_derived", "--value", "US"),
        *("--gate", "ic_mode", "--answer-id", "interactive"),
        *("--gate", "ic_fund_mode", "--answer-id", "generic"),
    )
    init = ("init", "--company-name", "Example Co", "--stage", "seed", "--sector", "B2B SaaS", "--geography", "US")
    _fmr_ok(
        h.run(
            h.SHARED / "founder_context.py",
            *init,
            "--artifacts-root",
            str(root),
            "--run-id",
            run_id,
            "--skill",
            "ic-sim",
        )
    )
    for name in ("startup_profile.json",):
        (run_dir / name).write_text(json.dumps(_ic_fixture(name, run_id)), encoding="utf-8")
    prior = {"imported": [], "skipped": True, "reason": "none", "metadata": {"run_id": run_id}}
    (run_dir / "prior_artifacts.json").write_text(json.dumps(prior), encoding="utf-8")
    fund = {k: v for k, v in _ic_fixture("fund_profile.json", run_id).items() if k not in ("validation", "metadata")}
    out = str(run_dir / "fund_profile.json")
    _fmr_ok(h.run(IC_SCRIPTS / "fund_profile.py", "--run-id", run_id, "-o", out, stdin=json.dumps(fund)))
    stub = ("--generic-stub", "--run-id", run_id, "-o", str(run_dir / "conflict_check.json"))
    _fmr_ok(h.run(IC_SCRIPTS / "detect_conflicts.py", *stub))
    for role in ("visionary", "operator", "analyst"):
        for kind in ("assessment", "rebuttal"):
            name = f"partner_{kind}_{role}.json"
            (run_dir / name).write_text(json.dumps(_ic_fixture(name, run_id)), encoding="utf-8")
    disc = ("--dir", str(run_dir), "--run-id", run_id, "-o", str(run_dir / "discussion.json"))
    _fmr_ok(h.run(IC_SCRIPTS / "compose_discussion.py", *disc))
    items = _ic_fixture("score_dimensions.json", run_id)["items"]
    for item in items:
        if item.get("status") in ("strong_conviction", "moderate_conviction"):
            item["status"] = "concern"
    scored = ("--run-id", run_id, "--fund-mode", "generic", "-o", str(run_dir / "score_dimensions.json"))
    _fmr_ok(h.run(IC_SCRIPTS / "score_dimensions.py", *scored, stdin=json.dumps({"items": items})))
    verdict = json.loads((run_dir / "score_dimensions.json").read_text(encoding="utf-8"))["summary"]["verdict"]
    assert verdict in ("pass", "hard_pass"), f"the lever: the scores must make a Decline, got {verdict!r}"
    _wait(root, run_id, "ic_decline_confirmation")
    rec("answer", "--gate", "ic_decline_confirmation", "--answer-id", "hold_off")
    assert h.status(root, run_id)["code"] == "GATE_INTERMEDIATE"
    return root, run_id, run_dir


def test_an_ic_sim_resume_at_the_decline_question_rewrites_only_what_follows_it(tmp_path: Path) -> None:
    root, run_id, run_dir = _ic_first_invocation(tmp_path)
    for f in run_dir.glob("*.json"):
        _age(f)
    lines = f"FS_HOST_RUN_ID={run_id}\nFS_HOST_ANSWER ic_decline_confirmation=finish\n"
    out = _out(_fmr_ok(h.start(root, "ic-sim", lines)))
    assert (out["resume"], out["resume_step"]) == (1, "8.5")
    read = ("read", "--artifacts-root", str(root), "--run-id", run_id, "--skill", "ic-sim")
    _fmr_ok(h.run(h.SHARED / "founder_context.py", *read))
    _fmr_ok(h.bind(root, run_id, run_dir, "example-co"))
    opened = json.loads(_fmr_ok(h.record(root, run_id, "open", "--gate", "ic_decline_confirmation")).stdout)
    assert opened["applied"] == "pre_answer"
    entry = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]
    assert (entry["current"]["answer_id"], entry["current"]["asked_evidence"]) == ("finish", "host_line")
    compose = ("--dir", str(run_dir), "-o", str(run_dir / "report.json"), "--write-md", str(run_dir / "report.md"))
    _fmr_ok(h.run(IC_SCRIPTS / "compose_report.py", *compose))
    page = ("--dir", str(run_dir), "--run-id", run_id, "-o", str(run_dir / "report.html"))
    _fmr_ok(h.run(IC_SCRIPTS / "visualize.py", *page))
    st = _complete(root, run_id)

    entry = st["invocations"][1]
    untouched = {k for k in entry["untouched_since_resume"] if not k.startswith("handoff_")}
    assert untouched == IC_KEPT_ON_RESUME
    assert {"report_json", "report_md", "report_html"} <= set(entry["touched_since_resume"])


def test_an_ic_sim_resume_without_the_answer_asks_again(tmp_path: Path) -> None:
    root, run_id, run_dir = _ic_first_invocation(tmp_path)
    _resume(root, "ic-sim", run_id)
    _fmr_ok(h.bind(root, run_id, run_dir, "example-co"))
    opened = json.loads(_fmr_ok(h.record(root, run_id, "open", "--gate", "ic_decline_confirmation")).stdout)
    assert opened.get("applied") is None and len(opened["needs_input"]) == 1
    assert h.status(root, run_id)["status"] == "waiting"
