"""Registry of per-skill compose-script invocations.

Each skill's compose has slightly different CLI flags. Rather than `if skill ==
"x": ...` chains, this registry maps skill name → callable. Add a new entry
when wiring a new skill's compose into the test suite. The registry is the
authoritative list of which skills' composes the test harness knows about.

Two entry points:
  - drive_compose(skill, fixture_dir, work_dir) -> Path (raises on non-zero)
  - run_compose_capturing(skill, fixture_dir, work_dir) -> CompletedProcess
    (does NOT raise; lets caller branch on returncode + stderr)

The two-entry-point design is required by Task 6 (run_id parity test), which
needs to inspect compose's stderr to distinguish "STALE_ARTIFACT under --strict
exits non-zero" from "compose crashed for an unrelated reason."

`fixture_dir` and `work_dir` MUST be different paths. The helpers stage
fixtures from the former into the latter; passing the same path is a
caller bug (caught immediately by an explicit assertion).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _stage_fixtures(fixture_dir: Path, work_dir: Path) -> None:
    """Copy fixture files into work_dir, preserving names. Idempotent."""
    assert fixture_dir.resolve() != work_dir.resolve(), (
        f"fixture_dir and work_dir must be different paths (both were {fixture_dir!s})"
    )
    for f in fixture_dir.iterdir():
        if f.is_file():
            shutil.copy(f, work_dir / f.name)


def _run_compose_subprocess(skill: str, work_dir: Path, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run compose; return CompletedProcess. Does NOT raise on non-zero exit.

    `REPORT_JSON_OUT` placeholders in extra_args are replaced with
    `<work_dir>/report.json`. `REPORT_MD_OUT` is replaced with
    `<work_dir>/report.md` for skills (like cap-table) whose compose
    requires both.
    """
    scripts = REPO_ROOT / "founder-skills" / "skills" / skill / "scripts"
    compose = scripts / "compose_report.py"
    report_out = str(work_dir / "report.json")
    report_md_out = str(work_dir / "report.md")
    resolved_args = []
    for a in extra_args:
        if a == "REPORT_JSON_OUT":
            resolved_args.append(report_out)
        elif a == "REPORT_MD_OUT":
            resolved_args.append(report_md_out)
        else:
            resolved_args.append(a)
    cmd = [sys.executable, str(compose), "--dir", str(work_dir), *resolved_args]
    return subprocess.run(cmd, capture_output=True, text=True)


# Per-skill compose flag sets. Add a row when a new skill's compose is wired.
# Flags are appended after `--dir <work_dir>` — must include `-o` pointing at
# the work_dir so report.json lands where drive_compose() can find it.
# (deck-review compose writes to stdout by default; -o redirects.)
_COMPOSE_FLAGS: dict[str, list[str]] = {
    # Every row must pass --write-md. A row that omits it produces no report.md, and a fixture-driven
    # fleet scan then reports that skill CLEAN without having looked at it.
    # `--ungated`: these fixtures exercise composition, not the stage gate, and deck-review
    # now requires an explicit choice rather than letting a missing flag skip its
    # authorization boundary silently. Saying "ungated" out loud is the point of the flag.
    "deck-review": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT", "--ungated"],
    # cap-table also requires --write-md; the harness substitutes REPORT_JSON_OUT
    # but also needs a markdown sibling path. We pass an explicit md path.
    "cap-table": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT", "--run-id", "test-run"],
    "market-sizing": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT"],
    "ic-sim": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT"],
    "financial-model-review": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT"],
    "competitive-positioning": ["-o", "REPORT_JSON_OUT", "--write-md", "REPORT_MD_OUT"],
}

# Per-skill artifact name to mutate when testing run_id-parity behavior.
# This MUST be an INPUT artifact (something compose reads), not a compose-
# produced output (`report.json` etc.) — compose overwrites those, making
# the mutation a no-op.
#
# Note on what STALE_ARTIFACT actually flags: deck-review's compose picks
# the FIRST artifact's run_id as the "primary" and flags every other artifact
# whose run_id differs. So mutating any one input artifact triggers
# STALE_ARTIFACT on the OTHERS — the test asserts the warning code appears
# at all, not which artifact name it cites. Choosing `deck_inventory.json`
# is arbitrary among the inputs; any non-output works.
_RUN_ID_MUTATION_TARGET: dict[str, str] = {
    "deck-review": "deck_inventory.json",
    "cap-table": "inputs.json",
    "market-sizing": "inputs.json",
    "ic-sim": "startup_profile.json",
    "financial-model-review": "inputs.json",
    "competitive-positioning": "landscape.json",
}


def get_mutation_target(skill: str) -> str:
    """Return the name of the input artifact whose run_id should be mutated
    when testing run_id-parity. Raises KeyError if not registered."""
    target = _RUN_ID_MUTATION_TARGET.get(skill)
    if target is None:
        raise KeyError(
            f"No run_id mutation target registered for skill {skill!r}. "
            f"Add an entry to _RUN_ID_MUTATION_TARGET in compose_invocations.py "
            f"naming an INPUT artifact (not a compose output)."
        )
    return target


def _ensure_registered(skill: str) -> list[str]:
    flags = _COMPOSE_FLAGS.get(skill)
    if flags is None:
        raise KeyError(
            f"No compose flags registered for skill {skill!r}. "
            f"Add an entry to _COMPOSE_FLAGS in compose_invocations.py "
            f"after verifying the skill's compose CLI."
        )
    return flags


def drive_compose(skill: str, fixture_dir: Path, work_dir: Path) -> Path:
    """Stage fixtures, run compose; raise on non-zero exit; return report.json path."""
    flags = _ensure_registered(skill)
    _stage_fixtures(fixture_dir, work_dir)
    result = _run_compose_subprocess(skill, work_dir, flags)
    if result.returncode != 0:
        raise RuntimeError(
            f"compose failed for {skill} (rc={result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    report = work_dir / "report.json"
    assert report.exists(), "compose succeeded but report.json missing"
    return report


def run_compose_capturing(skill: str, fixture_dir: Path, work_dir: Path) -> subprocess.CompletedProcess[str]:
    """Stage fixtures, run compose; return the CompletedProcess unchanged.

    For tests that need to inspect stderr / returncode (e.g., asserting that
    a specific warning surfaces under --strict). Caller is responsible for
    inspecting `result.returncode` and `result.stdout`/`stderr`.
    """
    flags = _ensure_registered(skill)
    _stage_fixtures(fixture_dir, work_dir)
    return _run_compose_subprocess(skill, work_dir, flags)
