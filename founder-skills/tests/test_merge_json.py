#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tests for the shared merge_json.py hand-off merger."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "merge_json.py")


def run_merge(args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def write_json(path: Path, obj: object) -> str:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def test_merges_left_to_right(tmp_path: Path) -> None:
    a = write_json(tmp_path / "a.json", {"x": 1, "shared": "from_a"})
    b = write_json(tmp_path / "b.json", {"y": 2, "shared": "from_b"})
    code, out, _ = run_merge([a, b])
    assert code == 0
    assert json.loads(out) == {"x": 1, "y": 2, "shared": "from_b"}


def test_set_override_applies_after_merge(tmp_path: Path) -> None:
    a = write_json(tmp_path / "a.json", {"approach": "top_down", "industry_total": 5e10})
    b = write_json(tmp_path / "b.json", {"approach": "bottom_up", "arpu": 1200})
    code, out, _ = run_merge([a, b, "--set", "approach=both"])
    assert code == 0
    merged = json.loads(out)
    assert merged["approach"] == "both"
    assert merged["industry_total"] == 5e10
    assert merged["arpu"] == 1200


def test_single_file_passthrough(tmp_path: Path) -> None:
    a = write_json(tmp_path / "a.json", {"k": [1, 2, 3]})
    code, out, _ = run_merge([a])
    assert code == 0
    assert json.loads(out) == {"k": [1, 2, 3]}


def test_bom_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ok": True}).encode("utf-8"))
    code, out, _ = run_merge([str(path)])
    assert code == 0
    assert json.loads(out) == {"ok": True}


def test_missing_file_fails_with_diagnostic(tmp_path: Path) -> None:
    code, _out, err = run_merge([str(tmp_path / "nope.json")])
    assert code == 1
    assert "cannot read" in err


def test_non_object_fails(tmp_path: Path) -> None:
    a = write_json(tmp_path / "list.json", [1, 2])
    code, _out, err = run_merge([a])
    assert code == 1
    assert "not a JSON object" in err


def test_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{truncated", encoding="utf-8")
    code, _out, err = run_merge([str(path)])
    assert code == 1
    assert "cannot read" in err


def test_malformed_set_fails(tmp_path: Path) -> None:
    a = write_json(tmp_path / "a.json", {})
    code, _out, err = run_merge([a, "--set", "no_equals_sign"])
    assert code == 1
    assert "KEY=VALUE" in err
