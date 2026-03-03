#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for find_artifact.py.

Run:  pytest founder-skills/tests/test_find_artifact.py -v

All tests use subprocess to exercise the script exactly as agents do.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "scripts")


def run_find(args: list[str], artifacts_root: str | None = None) -> tuple[int, str, str]:
    """Run find_artifact.py and return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "find_artifact.py")]
    cmd.extend(args)
    if artifacts_root:
        cmd.extend(["--artifacts-root", artifacts_root])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr


def _make_artifacts(root: str, dirs: dict[str, list[str]]) -> str:
    """Create artifact directory structure. dirs maps dir_name -> list of filenames."""
    for dir_name, files in dirs.items():
        dir_path = os.path.join(root, dir_name)
        os.makedirs(dir_path, exist_ok=True)
        for f in files:
            with open(os.path.join(dir_path, f), "w") as fh:
                fh.write("{}")
    return root


# --- Tests ---


def test_explicit_slug_found() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(root, {"market-sizing-acme-corp": ["sizing.json"]})
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp"],
            artifacts_root=root,
        )
        assert rc == 0
        assert stdout.endswith("market-sizing-acme-corp/sizing.json")


def test_explicit_slug_not_found() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(root, {"market-sizing-acme-corp": ["sizing.json"]})
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "nonexistent"],
            artifacts_root=root,
        )
        assert rc == 1


def test_auto_resolve_single_match() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(root, {"market-sizing-acme-corp": ["sizing.json"]})
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json"],
            artifacts_root=root,
        )
        assert rc == 0
        assert "acme-corp" in stdout


def test_ambiguous_multiple_matches() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-beta-inc": ["sizing.json"],
            },
        )
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json"],
            artifacts_root=root,
        )
        assert rc == 2
        assert "Ambiguous" in stderr


def test_artifact_file_missing_in_dir() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(root, {"market-sizing-acme-corp": ["other.json"]})
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp"],
            artifacts_root=root,
        )
        assert rc == 1


def test_max_age_days_rejects_old() -> None:
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(root, {"market-sizing-acme-corp": ["sizing.json"]})
        # Set mtime to 30 days ago
        path = os.path.join(root, "market-sizing-acme-corp", "sizing.json")
        old_time = os.path.getmtime(path) - (30 * 86400)
        os.utime(path, (old_time, old_time))
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp", "--max-age-days", "7"],
            artifacts_root=root,
        )
        assert rc == 1
        assert "older than" in stderr.lower() or "expired" in stderr.lower()


def test_explicit_slug_filters_exactly() -> None:
    """--slug matches the exact directory suffix, not a prefix."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-acme-corp-v2": ["sizing.json"],
            },
        )
        # --slug acme-corp matches only the exact slug, not acme-corp-v2
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp"],
            artifacts_root=root,
        )
        assert rc == 0
        assert "acme-corp" in stdout and "v2" not in stdout


def test_no_slug_different_dirs_is_ambiguous() -> None:
    """Without --slug, directories with different suffixes are different slugs = ambiguous."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-acme-corp-v2": ["sizing.json"],
            },
        )
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json"],
            artifacts_root=root,
        )
        assert rc == 2  # two different slugs = ambiguous


def test_prefer_newest_cross_slug_still_ambiguous() -> None:
    """--prefer newest must NOT resolve across different company slugs."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-beta-inc": ["sizing.json"],
            },
        )
        # Even with --prefer newest, different slugs = ambiguous
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--prefer", "newest"],
            artifacts_root=root,
        )
        assert rc == 2  # cross-slug ambiguity is never auto-resolved


def test_prefer_newest_resolves_reruns() -> None:
    """--prefer newest picks the most recently modified rerun for the same slug."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-acme-corp--20260101": ["sizing.json"],
                "market-sizing-acme-corp--20260301": ["sizing.json"],
            },
        )
        # Make the --20260301 rerun the newest by mtime
        newest = os.path.join(root, "market-sizing-acme-corp--20260301", "sizing.json")
        import time as _time

        os.utime(newest, (_time.time(), _time.time()))
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp", "--prefer", "newest"],
            artifacts_root=root,
        )
        assert rc == 0
        assert "20260301" in stdout


def test_reruns_without_prefer_newest_is_ambiguous() -> None:
    """Multiple same-slug rerun dirs without --prefer newest = exit 2."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp": ["sizing.json"],
                "market-sizing-acme-corp--20260101": ["sizing.json"],
            },
        )
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp"],
            artifacts_root=root,
        )
        assert rc == 2  # multiple same-slug dirs without --prefer = ambiguous


def test_slug_match_ignores_run_id_suffix() -> None:
    """--slug acme-corp matches 'market-sizing-acme-corp--20260301'."""
    with tempfile.TemporaryDirectory(prefix="test-find-") as root:
        _make_artifacts(
            root,
            {
                "market-sizing-acme-corp--20260301": ["sizing.json"],
            },
        )
        rc, stdout, stderr = run_find(
            ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "acme-corp"],
            artifacts_root=root,
        )
        assert rc == 0
        assert "acme-corp--20260301" in stdout


def test_no_artifacts_root() -> None:
    rc, stdout, stderr = run_find(
        ["--skill", "market-sizing", "--artifact", "sizing.json", "--slug", "nonexistent"],
        artifacts_root="/tmp/nonexistent-dir-xyzzy",
    )
    assert rc == 1
