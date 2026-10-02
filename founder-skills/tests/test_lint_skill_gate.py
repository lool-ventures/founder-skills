"""cowork-tests/lint_skill_gate.py: `lint-skill` gated against a pinned, shrink-only allowlist.

`lint-skill --strict` has no per-rule suppression, and from 4.0.0 it fires size-cap warnings that the repo's
measured decision not to shrink SKILL.md bodies contradicts. Dropping `--strict` would lose every WARN rule;
this keeps them all and names the accepted ones by (rule, file, count). A new rule, a new file, or one more
site reds; an accepted entry that no longer fires reds too, so the list only shrinks.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "cowork-tests" / "lint_skill_gate.py"
_ALLOW = _ROOT / "cowork-tests" / "lint-skill-allowlist.json"
_WORKFLOW = _ROOT / ".github" / "workflows" / "cowork-replay.yml"
_SPEC = importlib.util.spec_from_file_location("lint_skill_gate", _GATE)
assert _SPEC is not None and _SPEC.loader is not None
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)

_ALLOWED = [{"rule": "plugin-root-in-vm-bash", "file": "skills/x/SKILL.md", "count": 2, "reason": "r"}]


def _f(rule: str, file: str, severity: str = "WARN", line: int = 1) -> dict[str, Any]:
    return {"severity": severity, "rule": rule, "file": file, "line": line, "message": "m"}


def _warn2() -> list[dict[str, Any]]:
    return [
        _f("plugin-root-in-vm-bash", "skills/x/SKILL.md", line=1),
        _f("plugin-root-in-vm-bash", "skills/x/SKILL.md", line=9),
    ]


def test_exactly_the_accepted_findings_pass() -> None:
    problems = gate.problems(_warn2() + [_f("plugin-root-guarded", "skills/y/SKILL.md", "INFO")], _ALLOWED)
    assert problems == []


@pytest.mark.parametrize(
    "extra",
    [
        _f("skill-body-over-reattach-cap", "skills/x/SKILL.md"),  # a new rule
        _f("plugin-root-in-vm-bash", "skills/z/SKILL.md"),  # the same rule, a new file
        _f("plugin-root-in-vm-bash", "skills/x/SKILL.md", line=40),  # one more site in an accepted file
    ],
    ids=["new-rule", "new-file", "new-site"],
)
def test_anything_new_reds(extra: dict[str, Any]) -> None:
    assert gate.problems(_warn2() + [extra], _ALLOWED)


def test_an_accepted_entry_that_fires_less_or_not_at_all_reds_so_the_list_only_shrinks() -> None:
    assert any("shrink" in p for p in gate.problems(_warn2()[:1], _ALLOWED))
    assert any("shrink" in p for p in gate.problems([], _ALLOWED))


def test_an_error_is_never_accepted() -> None:
    allowed = [{"rule": "some-error", "file": "skills/x/SKILL.md", "count": 1, "reason": "r"}]
    assert gate.problems([_f("some-error", "skills/x/SKILL.md", "ERROR")], allowed)


def test_the_cli_fails_closed_on_output_it_cannot_read(tmp_path: Path) -> None:
    for content in ("", "not json", '{"findings": []}'):
        out = tmp_path / "ls.json"
        out.write_text(content, encoding="utf-8")
        r = subprocess.run([sys.executable, str(_GATE), str(out)], capture_output=True, text=True)
        assert r.returncode == 1, (content, r.stdout, r.stderr)


def test_the_committed_allowlist_is_well_formed() -> None:
    entries = json.loads(_ALLOW.read_text(encoding="utf-8"))["accepted"]
    assert entries, "an empty allowlist should be removed, with the plain --strict step restored"
    keys = [(e["rule"], e["file"]) for e in entries]
    assert len(keys) == len(set(keys)), "one entry per (rule, file)"
    for e in entries:
        assert isinstance(e["count"], int) and e["count"] >= 1, e
        assert str(e.get("reason") or "").strip(), f"every accepted finding says why: {e}"


def test_ci_runs_lint_skill_through_the_gate() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "cowork-tests/lint_skill_gate.py" in text
    assert "lint-skill founder-skills/skills/*/ --strict || fail=1" not in text


@pytest.mark.cowork
def test_the_pinned_cli_passes_the_gate_on_this_tree() -> None:
    """Live: every accepted entry still fires under the installed CLI, and nothing else does."""
    cli = shutil.which("cowork-harness")
    if cli is None:
        pytest.skip("cowork-harness not installed")
    # Repo-relative, from the repo root, as CI passes them: findings carry the path as given.
    skills = sorted(
        f"founder-skills/skills/{p.name}/" for p in (_ROOT / "founder-skills" / "skills").iterdir() if p.is_dir()
    )
    r = subprocess.run([cli, "lint-skill", *skills, "--json"], capture_output=True, text=True, cwd=_ROOT)
    findings = json.loads(r.stdout)
    allowed = json.loads(_ALLOW.read_text(encoding="utf-8"))["accepted"]
    assert gate.problems(findings, allowed) == []
