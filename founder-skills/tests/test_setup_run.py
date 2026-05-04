from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
    "setup_run.py",
)


def _run(args: list[str], cwd: str) -> tuple[int, dict | None, str]:
    res = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=cwd)
    parsed = json.loads(res.stdout) if res.stdout.strip() else None
    return res.returncode, parsed, res.stderr


def test_setup_run_creates_review_dir_under_artifacts_root() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        rc, out, err = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--pretty"],
            cwd=d,
        )
        assert rc == 0, err
        assert out is not None
        assert out["slug"] == "acme-corp"
        assert out["review_dir"] == os.path.join(artifacts_root, "deck-review-acme-corp")
        assert os.path.isdir(out["review_dir"])
        assert out["artifacts_root"] == artifacts_root


def test_setup_run_generates_iso_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        rc, out, _ = _run(
            ["--artifacts-root", os.path.join(d, "artifacts"), "--slug", "x", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert re.match(r"^\d{8}T\d{6}Z$", out["run_id"])


def test_setup_run_cleans_existing_artifacts_with_clean_flag() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        # Plant stale files
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            with open(os.path.join(review_dir, name), "w") as f:
                f.write("stale")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            assert not os.path.exists(os.path.join(review_dir, name))


def test_setup_run_clean_preserves_gate_state() -> None:
    """gate_state.json must survive --clean so re-invocation can find the answer (v3)."""
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        with open(os.path.join(review_dir, "gate_state.json"), "w") as f:
            f.write('{"metadata":{"run_id":"r1"},"answer":"Looks right"}')
        rc, _, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert os.path.exists(os.path.join(review_dir, "gate_state.json"))


def test_setup_run_without_clean_flag_preserves_files() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        with open(os.path.join(review_dir, "deck_inventory.json"), "w") as f:
            f.write("kept")
        _run(["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--pretty"], cwd=d)
        with open(os.path.join(review_dir, "deck_inventory.json")) as f:
            assert f.read() == "kept"


def test_setup_run_takes_override_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        rc, out, _ = _run(
            [
                "--artifacts-root",
                os.path.join(d, "artifacts"),
                "--slug",
                "x",
                "--run-id",
                "20260101T000000Z",
                "--pretty",
            ],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["run_id"] == "20260101T000000Z"
