"""Static-analysis tests on SKILL.md: Bash usage must stay in main-thread blocks.

The v0.4.0 Cowork failure was: SKILL.md instructed sub-agents to run Bash. In
Cowork sub-agent contexts, the literal name `Bash` doesn't resolve (Bash is
registered as `mcp__workspace__bash` — see cowork-architecture-and-v0.4.x-
learning.md). So producer scripts never executed. v0.4.1 inverted this:
main thread (where the literal `Bash` name DOES resolve) runs scripts;
sub-agents get JSON-only payloads using names that DO resolve in their
context (Read/Edit/Glob/Grep).

Frontmatter checks parse the YAML directly (not substring match) so they're
robust to whitespace and value-form variations (e.g.,
`disable-model-invocation: true` vs `disable-model-invocation:\\n  true`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

SKILL_MD_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """Return the YAML-parsed frontmatter as a dict, or {} if missing."""
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    parsed = yaml.safe_load(match.group(1))
    return parsed if isinstance(parsed, dict) else {}


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_has_user_invocable_frontmatter(skill_md: Path) -> None:
    """v0.4.3 invariant: every SKILL.md declares user-invocable: true."""
    fm = _parse_frontmatter(skill_md)
    assert fm, f"{skill_md.relative_to(REPO_ROOT)} has no/empty frontmatter"
    assert fm.get("user-invocable") is True, (
        f"{skill_md.relative_to(REPO_ROOT)} missing or non-boolean "
        f"`user-invocable: true` (got {fm.get('user-invocable')!r})"
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_does_not_disable_model_invocation(skill_md: Path) -> None:
    """v0.4.1 invariant: no SKILL.md sets disable-model-invocation: true.

    This was set in v0.3.x, removed in v0.4.1. Setting it again would force
    the skill onto the Cowork sub-agent dispatch path (where the literal
    `Bash` name doesn't resolve in the tool registry), reproducing the
    v0.4.0 failure mode.
    """
    fm = _parse_frontmatter(skill_md)
    assert fm.get("disable-model-invocation") is not True, (
        f"{skill_md.relative_to(REPO_ROOT)} sets disable-model-invocation:"
        " true — this puts the skill on the Cowork sub-agent dispatch path"
        " where the literal `Bash` name doesn't resolve. See"
        " cowork-architecture-and-v0.4.x-learning.md."
    )


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_uses_braced_plugin_root(skill_md: Path) -> None:
    """v0.4.3 invariant: ${CLAUDE_PLUGIN_ROOT} (braced), not bare $CLAUDE_PLUGIN_ROOT.

    Bare form depends on shell-expansion timing that Claude Code doesn't
    document as a guarantee for skill subprocesses.
    """
    text = skill_md.read_text()
    # Find bare $CLAUDE_PLUGIN_ROOT not followed by `}` (i.e., not the ${...} form).
    # Negative lookahead: not preceded by `{` either.
    bare = re.findall(r"(?<!\{)\$CLAUDE_PLUGIN_ROOT(?![}])", text)
    assert not bare, (
        f"{skill_md.relative_to(REPO_ROOT)} uses bare $CLAUDE_PLUGIN_ROOT "
        f"in {len(bare)} place(s); use ${{CLAUDE_PLUGIN_ROOT}} instead."
    )


# Per gist update 2026-05-10: plugin hooks declared in plugin.json never
# fire in Cowork sessions (desktop-side scope restriction excludes plugin
# scope; only ~/.claude/settings.json hooks fire). founder-skills'
# session-setup.sh is OK because ${CLAUDE_PLUGIN_ROOT} is substituted at
# skill-load time by the plugin content expander (v0.4.3 invariant) — the
# hook is defense-in-depth only. This test guards against future SKILL.md
# changes that would re-introduce a dependency on the hook firing.
_HOOK_DEPENDENT_PATTERNS = (
    # Bash idioms that suggest the hook (or some other env-setting thing
    # that doesn't run in Cowork) populated CLAUDE_PLUGIN_ROOT before the
    # SKILL.md ran. The braced ${CLAUDE_PLUGIN_ROOT} form (substituted at
    # load time) is fine; these idioms are not.
    re.compile(r"^\s*source\s+\S*session-setup\.sh", re.MULTILINE),
    re.compile(r"^\s*\.\s+\S*session-setup\.sh", re.MULTILINE),
    re.compile(r"\bCLAUDE_ENV_FILE\b"),  # the file the hook writes to
)


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_does_not_depend_on_session_start_hook(skill_md: Path) -> None:
    """v0.4.3+ invariant: SKILL.md must not depend on session-setup.sh
    actually running (it doesn't fire in Cowork). The braced
    ${CLAUDE_PLUGIN_ROOT} form, substituted at skill-load time by the
    plugin content expander, is the portable mechanism. Sourcing
    session-setup.sh from inside SKILL.md or referencing CLAUDE_ENV_FILE
    indicates a runtime hook dependency.

    Suppression: if a SKILL.md needs to mention these patterns legitimately
    (e.g., a comment explaining why we DON'T depend on the hook), add
    `<!-- skill-quality-ci: hook-mention-ok -->` on the same line or the
    line above. Mirrors Task 4's bash-after-subagent-ok suppression
    convention.
    """
    text = skill_md.read_text()
    suppress_marker = "<!-- skill-quality-ci: hook-mention-ok -->"
    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    for pattern in _HOOK_DEPENDENT_PATTERNS:
        for m in pattern.finditer(text):
            line_num = text.count("\n", 0, m.start()) + 1
            # Suppression: marker on this line or the line above.
            this_line = lines[line_num - 1] if line_num - 1 < len(lines) else ""
            prev_line = lines[line_num - 2] if line_num - 2 >= 0 else ""
            if suppress_marker in this_line or suppress_marker in prev_line:
                continue
            hits.append((line_num, m.group(0)[:80]))
    assert not hits, (
        f"{skill_md.relative_to(REPO_ROOT)} appears to depend on the "
        f"SessionStart hook firing (it doesn't fire in Cowork — see gist "
        f"yaniv-golan/303b6213b7a33167b3f98b076a5f81ad). Use ${{CLAUDE_PLUGIN_ROOT}} "
        f"directly instead, or add `<!-- skill-quality-ci: hook-mention-ok -->` "
        f"if this is an intentional reference.\n" + "\n".join(f"  line {ln}: {txt!r}" for ln, txt in hits)
    )
