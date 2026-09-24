"""The vendored corpus resolver must agree with the harness's own.

`_critique_corpus.py` is a verbatim copy of two functions from cowork-harness's bundled
`scripts/scenario.py`. A copy is the right shape here — importing the installed CLI's copy would
make the corpus ceiling ratchet CLI-conditional, and a ratchet that silently stops running is worse
than no ratchet — but a copy drifts. This is the guard that makes the drift loud.

It compares OUTPUTS, not source text: the resolved agent set and root-reference set for every skill,
against the same functions in the installed CLI's `scenario.py`. Comparing outputs rather than parsed
bodies is deliberate — upstream may reformat or refactor freely, and only a behavioural difference
matters to us.

SKIP POLICY, which is the load-bearing part. The test skips when the CLI is absent or below the
version whose resolver we vendored — a contributor without the CLI must not see a red. But when the
CLI IS at or above that version and the symbols are MISSING, it FAILS rather than skips: that is the
upstream-rename case, and letting it skip would retire this guard silently at the exact moment it
became necessary.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import _critique_corpus
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "founder-skills" / "skills"

# The release whose resolver `_critique_corpus.py` was vendored from. Below this the upstream copy
# has no root-reference resolution at all, so a comparison would be meaningless rather than useful.
VENDORED_FROM = (3, 7, 0)


def _installed_version() -> tuple[int, ...] | None:
    exe = shutil.which("cowork-harness")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (out.stdout or out.stderr).strip().split()
    for token in raw:
        parts = token.lstrip("v").split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return tuple(int(p) for p in parts)
    return None


def _installed_scenario_py() -> Path | None:
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not root:
        return None
    candidate = Path(root) / "cowork-harness" / ".claude" / "skills" / "cowork-harness" / "scripts" / "scenario.py"
    return candidate if candidate.is_file() else None


def _load_upstream(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("_upstream_scenario", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vendored_resolver_matches_the_installed_harness() -> None:
    version = _installed_version()
    if version is None:
        pytest.skip("cowork-harness CLI not installed")
    if version < VENDORED_FROM:
        pytest.skip(f"installed CLI {version} predates the vendored resolver {VENDORED_FROM}")

    path = _installed_scenario_py()
    assert path is not None, (
        "cowork-harness is installed at a version that ships the corpus resolver, but its "
        "scripts/scenario.py was not found under `npm root -g`. Cannot verify the vendored copy."
    )
    upstream = _load_upstream(path)

    # Not a skip: at or above the vendored version these symbols exist, so their absence means
    # upstream renamed them and the vendored copy is now unpinned.
    for name in ("_resolve_corpus_agents", "_resolve_corpus_root_references"):
        assert hasattr(upstream, name), (
            f"installed cowork-harness {version} no longer exports `{name}` — the vendored copy in "
            "_critique_corpus.py is now pinned to nothing. Re-vendor from the current release."
        )

    drift: list[str] = []
    for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
        skill = str(skill_dir)
        ours_agents = sorted(_critique_corpus.resolve_agents(skill))
        theirs_agents = sorted(upstream._resolve_corpus_agents(skill))
        if ours_agents != theirs_agents:
            drift.append(f"{skill_dir.name} agents: ours={ours_agents} theirs={theirs_agents}")
        ours_refs = sorted(_critique_corpus.resolve_root_references(skill, ours_agents))
        theirs_refs = sorted(upstream._resolve_corpus_root_references(skill, theirs_agents))
        if ours_refs != theirs_refs:
            drift.append(f"{skill_dir.name} root refs: ours={ours_refs} theirs={theirs_refs}")

    assert not drift, (
        "the vendored corpus resolver disagrees with the installed harness — re-vendor it:\n"
        + json.dumps(drift, indent=2)
    )
