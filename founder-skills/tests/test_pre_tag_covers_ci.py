"""Drift guard: `scripts/pre-tag.sh` must run every gate `ci.yml` runs.

The release preflight restates CI's gate list, which is the volatile-facts-in-prose defect
in executable form: add a job to `ci.yml`, forget the preflight, and the preflight silently
stops being CI-equivalent — exactly how a "green locally" release can still fail in CI.

Physically unifying them was considered and rejected: `ci.yml` splits these across five jobs
with a Python matrix, so collapsing them into one script would serialize the matrix and lose
per-job reporting. This test buys the same no-silent-drift property while leaving CI's job
topology alone.

Scope: it compares the *commands*, not their outcomes. A gate present in both but broken is
the gate's own tests' problem, not this one's.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRE_TAG = REPO_ROOT / "scripts" / "pre-tag.sh"

# `ci.yml` steps that are environment setup, not gates — nothing for a local preflight to do.
_NOT_A_GATE = re.compile(r"^uv (python install|sync)\b")


def _ci_gate_commands() -> list[str]:
    """Every `- run:` command in ci.yml that is a gate rather than setup."""
    text = CI.read_text(encoding="utf-8")
    runs = re.findall(r"^\s*- run:\s*(.+)$", text, re.MULTILINE)
    return [r.strip() for r in runs if not _NOT_A_GATE.match(r.strip())]


def _normalize(cmd: str) -> str:
    """Reduce a command to the tokens that identify WHICH gate it is.

    Drops flags that differ legitimately between CI and a local run (`-v` vs `-q`) and
    GitHub expression syntax, keeping the tool and its target.
    """
    cmd = re.sub(r"\$\{\{.*?\}\}", "", cmd)
    cmd = re.sub(r"\s-(?:v|q)\b", " ", cmd)
    return " ".join(cmd.split())


def test_every_ci_gate_appears_in_the_preflight() -> None:
    """A gate added to ci.yml and not to pre-tag.sh fails here, not at tag time."""
    script = PRE_TAG.read_text(encoding="utf-8")
    missing: list[str] = []

    for cmd in _ci_gate_commands():
        norm = _normalize(cmd)
        # The identifying tokens: the tool, and the path/target it acts on.
        tokens = [t for t in norm.split() if not t.startswith("-")]
        # `uv run mypy <dir>` → look for the dir; `uv run pytest <dir>` → the dir; etc.
        target = tokens[-1] if tokens else norm
        tool = "mypy" if "mypy" in norm else "pytest" if "pytest" in norm else tokens[2] if len(tokens) > 2 else norm
        if tool not in script or (target.startswith(("founder-skills", "evals", "scripts")) and target not in script):
            missing.append(cmd)

    assert not missing, (
        "scripts/pre-tag.sh does not cover these ci.yml gates — add them, or the preflight "
        "is not CI-equivalent and a release can pass locally and fail in CI:\n  " + "\n  ".join(missing)
    )


def test_preflight_checks_version_parity() -> None:
    """The one gate CI cannot usefully provide: parity BEFORE the tag exists.

    skill-quality.yml runs it on tag push, by which point the tag must be deleted and
    re-pushed to fix. Losing this check would make the preflight strictly weaker than the
    prose it replaced — which is how it was lost once already, when a review replaced a
    hand-listed gate set with "call the shared runner".
    """
    script = PRE_TAG.read_text(encoding="utf-8")
    assert "version parity" in script
    for manifest in ("plugin.json", "pyproject.toml"):
        assert manifest in script, f"version parity must compare {manifest}"


def test_preflight_reports_all_failures_rather_than_stopping_at_the_first() -> None:
    """CI's steps run under `-e`; v0.7.0 burned two tags because the first failure hid the rest.

    The preflight's value is telling you everything to fix in one run, so it must NOT use
    `set -e` and must accumulate failures.
    """
    script = PRE_TAG.read_text(encoding="utf-8")
    assert "set -euo pipefail" not in script, "set -e makes the preflight stop at the first gate"
    assert "FAILED+=(" in script, "failures must accumulate, not abort"
