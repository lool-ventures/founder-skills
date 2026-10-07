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
