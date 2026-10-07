"""Each skill's `_run_ref.py` is one file in six places, and its grammar is the shared one.

Skill scripts decide "is there a gate ledger?" without loading anything from the plugin root, which a
flat mount does not have. So the decision lives in a sibling module each skill carries. Six copies drift
unless something holds them equal, and a run-id grammar that differs between a skill and the shared
status writer would let one accept an id the other refuses.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / "founder-skills" / "skills"
SHARED = REPO_ROOT / "founder-skills" / "scripts"
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
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_ref() -> ModuleType:
    return _load(SKILLS / "deck-review" / "scripts" / "_run_ref.py", "_run_ref_under_test")


def test_every_skill_carries_the_same_copy() -> None:
    copies = {s: (SKILLS / s / "scripts" / "_run_ref.py").read_bytes() for s in SKILL_NAMES}
    first = copies["deck-review"]
    assert all(body == first for body in copies.values()), sorted(s for s, b in copies.items() if b != first)


def test_the_grammar_is_the_shared_one() -> None:
    shared = _load(SHARED / "_run_status.py", "_run_status_under_test")
    assert _run_ref().RUN_ID_RE.pattern == shared.RUN_ID_RE.pattern


def test_apply_corrections_takes_the_grammar_from_its_sibling() -> None:
    src = (SKILLS / "financial-model-review" / "scripts" / "apply_corrections.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "_run_ref"]
    assert imports and any(a.name == "RUN_ID_RE" for n in imports for a in n.names)
    pattern = _run_ref().RUN_ID_RE.pattern
    assert pattern not in src, "apply_corrections.py carries its own copy of the run-id pattern"


@pytest.mark.parametrize(
    ("run_id", "ok"),
    [
        ("20261007T090000Z-1a2b3c", True),
        ("r1", True),
        ("a.b_c-d", True),
        ("../x", False),
        ("a/r2", False),
        (".hidden", False),
        ("", False),
        ("x" * 65, False),
        (None, False),
    ],
)
def test_has_ledger_needs_a_valid_id_and_the_ref(tmp_path: Path, run_id: object, ok: bool) -> None:
    rr = _run_ref()
    assert rr.has_ledger(str(tmp_path), run_id) is False
    if not ok:
        return
    assert isinstance(run_id, str)
    ref = tmp_path / "handoff" / run_id / "run_ref.json"
    ref.parent.mkdir(parents=True)
    ref.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    # The ref alone is ledger mode, whether or not its ledger exists: a ref whose ledger is gone is
    # refused by the shared code, never quietly treated as "no ledger".
    assert rr.has_ledger(str(tmp_path), run_id) is True


def test_has_ledger_ignores_another_runs_ref(tmp_path: Path) -> None:
    rr = _run_ref()
    ref = tmp_path / "handoff" / "other-run" / "run_ref.json"
    ref.parent.mkdir(parents=True)
    ref.write_text("{}", encoding="utf-8")
    assert rr.has_ledger(str(tmp_path), "this-run") is False


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<html><head><title>x</title></head></html>", '<html><head><meta name="founder-skills-run-id"'),
        ('<HTML><HEAD lang="en"><title>x', '<HTML><HEAD lang="en"><meta name="founder-skills-run-id"'),
        ("<html>\n<head>\n", "<html>\n<head><meta"),
    ],
)
def test_stamp_html_inserts_right_after_the_first_head(html: str, expected: str) -> None:
    out = _run_ref().stamp_html(html, "r1")
    assert out is not None and out.startswith(expected)
    assert out.count('name="founder-skills-run-id"') == 1
    assert 'content="r1"' in out


def test_stamp_html_never_matches_a_header_element() -> None:
    rr = _run_ref()
    assert rr.stamp_html("<html><header>x</header></html>", "r1") is None
    out = rr.stamp_html("<html><header>x</header><head></head>", "r1")
    assert out == '<html><header>x</header><head><meta name="founder-skills-run-id" content="r1"></head>'


def test_stamp_html_refuses_a_malformed_id() -> None:
    with pytest.raises(ValueError):
        _run_ref().stamp_html("<head>", "../x")


def test_load_shared_raises_when_the_shared_dir_is_absent(tmp_path: Path) -> None:
    flat = tmp_path / "skill" / "scripts"
    flat.mkdir(parents=True)
    copy = flat / "_run_ref.py"
    copy.write_bytes((SKILLS / "deck-review" / "scripts" / "_run_ref.py").read_bytes())
    mod = _load(copy, "_run_ref_flat")
    saved: dict[str, ModuleType] = {k: sys.modules.pop(k) for k in ("_run_status", "_gates") if k in sys.modules}
    try:
        with pytest.raises(ImportError):
            mod.load_shared("_gates")
    finally:
        sys.modules.update(saved)
