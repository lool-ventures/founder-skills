"""A folder belongs to the run bound into it last, read from the folder's refs alone.

`bind` stamps each `run_ref.json` with `bound_seq` (one more than the highest in the folder) and `bound_at`;
`folder_current_run` picks the newest. The canonical function is `_run_status.folder_current_run`; each
skill's `_run_ref.py` carries the same source, so a skill script answers without loading shared code.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402

SKILL_NAMES = (
    "deck-review",
    "market-sizing",
    "ic-sim",
    "financial-model-review",
    "competitive-positioning",
    "cap-table",
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass resolves its module through sys.modules
    spec.loader.exec_module(mod)
    return mod


STATUS = _load(h.SHARED / "_run_status.py", "_run_status_folder_under_test")
REF = _load(h.SKILLS / "market-sizing" / "scripts" / "_run_ref.py", "_run_ref_folder_under_test")
IMPLS = {"_run_status": STATUS.folder_current_run, "_run_ref": REF.folder_current_run}


def _ref(run_dir: Path, run_id: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((run_dir / "handoff" / run_id / "run_ref.json").read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_each_skill_copy_has_the_canonical_source(skill: str) -> None:
    copy = _load(h.SKILLS / skill / "scripts" / "_run_ref.py", f"_run_ref_src_{skill.replace('-', '_')}")
    assert inspect.getsource(copy.folder_current_run) == inspect.getsource(STATUS.folder_current_run)


def test_bind_stamps_a_rising_sequence_and_the_newest_bind_holds_the_folder(tmp_path: Path) -> None:
    root, old, run_dir = h.start_bound(tmp_path, "market-sizing")
    new = h.start_ok(root, "market-sizing")
    assert h.bind(root, new, run_dir, "example-co").returncode == 0
    assert _ref(run_dir, old)["bound_seq"] == 1 and _ref(run_dir, new)["bound_seq"] == 2
    assert isinstance(_ref(run_dir, new)["bound_at"], str)
    assert _ref(run_dir, new)["schema_version"] == 1
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == new, name


def test_a_rebind_of_the_earlier_run_takes_the_folder_back(tmp_path: Path) -> None:
    """A host resume runs the slug block again, which binds: the earlier, unfinished run is current again.
    So does a model re-running the slug block after a compaction (a bind with no `start`)."""
    root, old, run_dir = h.start_bound(tmp_path, "market-sizing")
    new = h.start_ok(root, "market-sizing")
    assert h.bind(root, new, run_dir, "example-co").returncode == 0
    assert h.bind(root, old, run_dir, "example-co").returncode == 0
    assert _ref(run_dir, old)["bound_seq"] == 3
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == old, name


def test_legacy_refs_with_no_stamp_are_ordered_by_mtime_and_below_a_stamped_one(tmp_path: Path) -> None:
    run_dir = tmp_path / "f"
    for rid, mtime in (("20260101T000000Z-aaaaaa", 1_000), ("20260101T000000Z-bbbbbb", 2_000)):
        ref = run_dir / "handoff" / rid / "run_ref.json"
        ref.parent.mkdir(parents=True)
        ref.write_text(json.dumps({"run_id": rid, "ledger_rel": f"runs/{rid}/gates.json"}), encoding="utf-8")
        os.utime(ref, (mtime, mtime))
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == "20260101T000000Z-bbbbbb", name
    os.utime(run_dir / "handoff" / "20260101T000000Z-aaaaaa" / "run_ref.json", (3_000, 3_000))
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == "20260101T000000Z-aaaaaa", name
    stamped = run_dir / "handoff" / "20260101T000000Z-cccccc" / "run_ref.json"
    stamped.parent.mkdir(parents=True)
    stamped.write_text(json.dumps({"bound_seq": 1, "bound_at": "2026-01-01T00:00:00.000000Z"}), encoding="utf-8")
    os.utime(stamped, (10, 10))  # older file, but stamped: a stamp outranks every legacy ref
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == "20260101T000000Z-cccccc", name


def test_an_unbound_folder_has_no_current_run(tmp_path: Path) -> None:
    for name, fn in IMPLS.items():
        assert fn(str(tmp_path)) is None, name


def test_another_runs_pruned_status_does_not_matter(tmp_path: Path) -> None:
    root, old, run_dir = h.start_bound(tmp_path, "market-sizing")
    new = h.start_ok(root, "market-sizing")
    assert h.bind(root, new, run_dir, "example-co").returncode == 0
    shutil.rmtree(root / "runs" / old)
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == new, name


def test_an_unreadable_ref_is_skipped(tmp_path: Path) -> None:
    root, old, run_dir = h.start_bound(tmp_path, "market-sizing")
    bad = run_dir / "handoff" / "20991231T000000Z-ffffff" / "run_ref.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json", encoding="utf-8")
    for name, fn in IMPLS.items():
        assert fn(str(run_dir)) == old, name


def test_the_skill_copy_answers_without_loading_shared_code(tmp_path: Path) -> None:
    """A flat mount has no plugin-root scripts: the skill's own copy must not need them."""
    root, old, run_dir = h.start_bound(tmp_path, "market-sizing")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import _run_ref; "
        "print(_run_ref.folder_current_run(sys.argv[2])); print('_run_status' in sys.modules)"
    )
    proc = h.run("-c", code, str(h.SKILLS / "market-sizing" / "scripts"), str(run_dir))  # type: ignore[arg-type]
    assert proc.stdout.split() == [old, "False"], proc.stderr
