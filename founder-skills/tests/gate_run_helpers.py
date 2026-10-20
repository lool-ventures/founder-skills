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


HOST_DELIVERS_LINE = "The analysis is complete. The host delivers its output."


def set_no_handover(root: Path, run_id: str) -> None:
    """Record FS_HOST_NO_HANDOVER in the run's ledger, as `start` would have."""
    path = ledger_path(root, run_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["no_handover"] = {"raw": "FS_HOST_NO_HANDOVER", "set_at": "2026-10-20T00:00:00Z", "by": "test"}
    path.write_text(json.dumps(data), encoding="utf-8")


def check_host_closer(closer: Path, root: Path, run_id: str, run_dir: Path) -> None:
    """Under FS_HOST_NO_HANDOVER a closer prints the host line alone, overwrites handover.txt with it, and stamps
    `handover: "host"` beside `handed_over_at`; an unreadable ledger, a report with no verdict, another run's
    report and a failed handover.txt write each exit 2 and print nothing."""
    report_path = run_dir / "report.json"
    argv: list[str] = [
        str(closer), "--report", str(report_path), "--link", "path", "--deliverable", f"the report={run_dir}/report.md"
    ]  # fmt: skip
    handover = run_dir / "handover.txt"
    handover.write_text("Here's your finished analysis: an earlier hand-over.\n", encoding="utf-8")
    set_no_handover(root, run_id)

    good = report_path.read_text(encoding="utf-8")
    report = json.loads(good)
    report.pop("verdict", None)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    no_verdict = run(*argv)
    assert no_verdict.returncode == 2 and no_verdict.stdout == "", no_verdict
    report = json.loads(good)
    report["run_id"] = "20261001T090000Z-0f0f0f"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    other = run(*argv)
    assert other.returncode == 2 and other.stdout == "", other
    report_path.write_text(good, encoding="utf-8")
    assert status(root, run_id)["handed_over_at"] is None

    # handover.txt cannot be written but can be removed: the older one goes, and the line is still printed.
    handover.chmod(0o444)
    try:
        unwritable = run(*argv)
    finally:
        if handover.exists():
            handover.chmod(0o644)
    assert unwritable.returncode == 0 and unwritable.stdout == HOST_DELIVERS_LINE + "\n", unwritable
    assert not handover.exists()
    # Neither written nor removed: exit 2, nothing printed.
    handover.write_text("Here's your finished analysis: an earlier hand-over.\n", encoding="utf-8")
    handover.chmod(0o444)
    run_dir.chmod(0o555)
    try:
        stuck = run(*argv)
    finally:
        run_dir.chmod(0o755)
        handover.chmod(0o644)
    assert stuck.returncode == 2 and stuck.stdout == "", stuck

    _set_status(root, run_id, handed_over_at=None, handover=None)
    proc = run(*argv)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == HOST_DELIVERS_LINE + "\n"
    assert handover.read_text(encoding="utf-8") == HOST_DELIVERS_LINE + "\n"
    st = status(root, run_id)
    assert st["handed_over_at"] and st["handover"] == "host"

    lp = ledger_path(root, run_id)
    saved = lp.read_bytes()
    lp.write_text("{not json", encoding="utf-8")
    try:
        broken = run(*argv)
    finally:
        lp.write_bytes(saved)
    assert broken.returncode == 2, broken
    assert HOST_DELIVERS_LINE not in broken.stdout and "Here's your" not in broken.stdout
    assert json.loads(broken.stdout.strip().splitlines()[-1])["code"] == "LEDGER_MISSING"

    # A bound folder whose only ref names no usable run: exit 2, never the founder hand-over.
    refs = list(run_dir.glob("handoff/*/run_ref.json"))
    saved_refs = {r: r.read_bytes() for r in refs}
    for r in refs:
        r.write_text("{not json", encoding="utf-8")
    try:
        unbound = run(*argv)
    finally:
        for r, b in saved_refs.items():
            r.write_bytes(b)
    assert unbound.returncode == 2 and "Here's your" not in unbound.stdout and HOST_DELIVERS_LINE not in unbound.stdout
    assert json.loads(unbound.stdout.strip().splitlines()[-1])["code"] == "LEDGER_MISSING"


def _set_status(root: Path, run_id: str, **fields: Any) -> None:
    path = status_path(root, run_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")
