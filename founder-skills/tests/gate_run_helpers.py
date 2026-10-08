"""Build a run with a gate ledger, the way a skill's Step 0 and slug block would, for tests.

`start_bound` runs the real `run_status.py start` and `bind`, so every test that uses it exercises the
same path a host request takes. Ids and names are synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "founder-skills" / "scripts"
SKILLS = REPO_ROOT / "founder-skills" / "skills"
RUN_STATUS = SHARED / "run_status.py"
RECORD = SHARED / "record_gate_answer.py"

RUN_DIR_PREFIX = {
    "deck-review": "deck-review",
    "market-sizing": "market-sizing",
    "financial-model-review": "financial-model-review",
    "ic-sim": "ic-sim",
    "competitive-positioning": "competitive-positioning",
    "cap-table": "cap-table",
}


def run(
    script: Path | str,
    *args: str,
    stdin: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """`timeout` (seconds) for a call that could block on a lock another process holds: past it the call is
    killed and `subprocess.TimeoutExpired` fails the test instead of hanging the suite."""
    base = {k: v for k, v in os.environ.items() if not k.startswith(("FS_HOST_", "COWORK_", "CLAUDE_CODE_REMOTE"))}
    if env:
        base.update(env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base,
        timeout=timeout,
    )


def start(root: Path, skill: str, lines: str = "") -> subprocess.CompletedProcess[str]:
    return run(RUN_STATUS, "start", "--skill", skill, "--artifacts-root", str(root), stdin=lines)


def start_ok(root: Path, skill: str, lines: str = "") -> str:
    proc = start(root, skill, lines)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rid: str = json.loads(proc.stdout)["run_id"]
    return rid


def bind(root: Path, run_id: str, run_dir: Path, slug: str) -> subprocess.CompletedProcess[str]:
    return run(
        RUN_STATUS,
        "bind",
        "--run-id",
        run_id,
        "--artifacts-root",
        str(root),
        "--run-dir",
        str(run_dir),
        "--slug",
        slug,
    )


def start_bound(
    tmp: Path, skill: str, *, slug: str = "example-co", lines: str = "", suffix: str = ""
) -> tuple[Path, str, Path]:
    """(artifacts root, run id, run dir) for a started and bound run."""
    root = tmp / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    run_id = start_ok(root, skill, lines)
    run_dir = root / f"{RUN_DIR_PREFIX[skill]}-{slug}{suffix}"
    proc = bind(root, run_id, run_dir, slug)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return root, run_id, run_dir


def status_path(root: Path, run_id: str) -> Path:
    return root / "runs" / run_id / "run_status.json"


def ledger_path(root: Path, run_id: str) -> Path:
    return root / "runs" / run_id / "gates.json"


def status(root: Path, run_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(status_path(root, run_id).read_text(encoding="utf-8"))
    return data


def ledger(root: Path, run_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ledger_path(root, run_id).read_text(encoding="utf-8"))
    return data


def snapshot(root: Path, run_id: str) -> tuple[bytes, bytes]:
    return status_path(root, run_id).read_bytes(), ledger_path(root, run_id).read_bytes()


def record(root: Path, run_id: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return run(RECORD, args[0], "--run-id", run_id, "--artifacts-root", str(root), *args[1:], stdin=stdin)
