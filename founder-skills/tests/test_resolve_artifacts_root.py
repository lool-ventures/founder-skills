"""Unit tests for the deterministic artifacts-root resolver.

The resolver exists because SKILL.md bash is paraphrased by the agent (non-deterministic path
choice). These tests lock the canonical resolution rule so it cannot silently drift.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_artifacts_root.py"


def _load():
    spec = importlib.util.spec_from_file_location("resolve_artifacts_root", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
resolve = _mod.resolve_artifacts_root


def test_cli_default_is_cwd_artifacts(tmp_path: Path) -> None:
    assert resolve(str(tmp_path), {}) == os.path.join(str(tmp_path), "artifacts")


def test_cowork_pwd_is_mnt_root(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir()
    assert resolve(str(tmp_path), {}) == os.path.join(str(tmp_path), "outputs", "artifacts")


def test_cowork_pwd_one_level_up(tmp_path: Path) -> None:
    (tmp_path / "mnt" / "outputs").mkdir(parents=True)
    assert resolve(str(tmp_path), {}) == os.path.join(str(tmp_path), "mnt", "outputs", "artifacts")


def test_cowork_pwd_above_session_is_deterministic(tmp_path: Path) -> None:
    # Two sessions present → the resolver must pick a FIXED one (sorted), never a first-subdir guess.
    for s in ("local_zzz", "local_aaa"):
        (tmp_path / "sessions" / s / "mnt" / "outputs").mkdir(parents=True)
    got = resolve(str(tmp_path), {})
    assert got == os.path.join(str(tmp_path), "sessions", "local_aaa", "mnt", "outputs", "artifacts")


def test_env_override_wins(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir()
    assert resolve(str(tmp_path), {"COWORK_ARTIFACTS_ROOT": "/somewhere/else"}) == os.path.abspath("/somewhere/else")


def test_outputs_preferred_over_mnt_outputs(tmp_path: Path) -> None:
    # If both exist, the cwd/outputs branch wins (fixed order), so the result is unambiguous.
    (tmp_path / "outputs").mkdir()
    (tmp_path / "mnt" / "outputs").mkdir(parents=True)
    assert resolve(str(tmp_path), {}) == os.path.join(str(tmp_path), "outputs", "artifacts")
