"""Regression tests enforcing the skill frontmatter and env-var contract.

Grounded in the v2.1.120-verified gist: only ``${CLAUDE_PLUGIN_ROOT}``
(braced) is template-substituted by the plugin content expander before
shell substitution. Bare ``$CLAUDE_PLUGIN_ROOT`` resolves only at Bash
execution time and depends on ``CLAUDE_ENV_FILE`` being sourced — which
the gist flags as unconfirmed for skill shell subprocesses.

Frontmatter keys outside the documented set are silently dropped by the
parser, so we keep frontmatter minimal and move human documentation into
the body.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "founder-skills" / "skills"

# Documented frontmatter keys per gist 1 (v2.1.120 SKILL.md table).
# `version` is explicitly tagged "[Undocumented] Informational only" in the
# gist — we exclude it from the documented set so future authors don't
# treat it as a contract.
ALLOWED_FRONTMATTER_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "allowed-tools",
        "argument-hint",
        "arguments",
        "context",
        "agent",
        "model",
        "effort",
        "user-invocable",
        "disable-model-invocation",
        "paths",
        "hooks",
        "shell",
        "created_by",
    }
)


def _skill_md_files() -> list[Path]:
    return sorted(SKILLS_ROOT.glob("*/SKILL.md"))


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Raises on missing frontmatter."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md is missing YAML frontmatter")
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_no_bare_plugin_root_in_body(skill_md: Path) -> None:
    """Bare $CLAUDE_PLUGIN_ROOT (no braces) is fragile — must use ${...}."""
    text = skill_md.read_text()
    _, body = _split_frontmatter(text)
    # Match $CLAUDE_PLUGIN_ROOT NOT preceded by '{' (i.e. bare form).
    bare = re.findall(r"(?<!\{)\$CLAUDE_PLUGIN_ROOT\b", body)
    assert not bare, (
        f"{skill_md.relative_to(REPO_ROOT)} has {len(bare)} bare "
        "$CLAUDE_PLUGIN_ROOT references. Use ${CLAUDE_PLUGIN_ROOT} so the "
        "plugin content expander substitutes it at load time, instead of "
        "depending on CLAUDE_ENV_FILE being sourced into the Bash subprocess."
    )


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_only_documented_keys(skill_md: Path) -> None:
    """Custom keys are silently dropped by the parser — keep them out."""
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    unknown = set(fm.keys()) - ALLOWED_FRONTMATTER_KEYS
    assert not unknown, (
        f"{skill_md.relative_to(REPO_ROOT)} has frontmatter keys "
        f"{sorted(unknown)} that are not in the documented set "
        "(silently dropped by the parser per gist). Move them to a "
        "documentation section in the body."
    )


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_has_when_to_use(skill_md: Path) -> None:
    """Regression lock: every skill must declare when_to_use.

    All 5 skills already have when_to_use on main (added in v0.4.1). This
    test prevents future authors from accidentally dropping the field in
    a refactor. when_to_use is half the model's pitch in the skill listing
    (combined with description, capped at 1,536 chars per gist 1).

    Note: Desktop's regex-based skill scanner ignores when_to_use entirely
    (per gist 2 §"Skill discovery logic" — only `name`, `description`,
    `argument-hint`, `user-invocable` are read). So when_to_use matters
    for CLI-runtime model invocation, not for Settings UI display. Trigger
    phrasing should also live in description for Desktop discoverability.
    """
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    assert fm.get("when_to_use"), (
        f"{skill_md.relative_to(REPO_ROOT)} is missing 'when_to_use'. "
        "This was added in v0.4.1 — re-add it before merging."
    )


@pytest.mark.parametrize("skill_md", _skill_md_files(), ids=lambda p: p.parent.name)
def test_frontmatter_listing_budget(skill_md: Path) -> None:
    """description + when_to_use is capped at 1,536 chars per skill."""
    text = skill_md.read_text()
    fm, _ = _split_frontmatter(text)
    desc = fm.get("description", "") or ""
    wtu = fm.get("when_to_use", "") or ""
    total = len(desc) + len(wtu)
    assert total <= 1536, (
        f"{skill_md.relative_to(REPO_ROOT)}: description+when_to_use is "
        f"{total} chars, exceeds the 1,536-char per-skill listing cap."
    )


def test_total_listing_budget_under_default_floor() -> None:
    """Sum of all skills' description+when_to_use must stay under the 8,000-char fallback.

    Two independent caps apply:
      - per-skill: 1,536 chars (gist authority, enforced above)
      - total: 1% of context window (dynamic) or 8,000 chars (fallback floor)

    These are independent ceilings, not additive. With 5 skills × per-skill
    1,536 = 7,680 chars worst case (still under the 8,000 floor by 320), but
    that leaves no headroom for bundled/built-in skills that share the same
    budget. We hold ourselves to a 6,000-char soft cap on the total to leave
    headroom and stay well above the 20-char-per-skill collapse threshold.

    If the total ever creeps near 6,000, trim description/when_to_use; do
    not raise the cap.
    """
    soft_cap = 6000
    total = 0
    breakdown: list[str] = []
    for skill_md in _skill_md_files():
        fm, _ = _split_frontmatter(skill_md.read_text())
        desc = fm.get("description", "") or ""
        wtu = fm.get("when_to_use", "") or ""
        n = len(desc) + len(wtu)
        total += n
        breakdown.append(f"  {skill_md.parent.name}: {n}")
    assert total <= soft_cap, (
        f"Total listing budget across {len(_skill_md_files())} skills is "
        f"{total} chars, exceeds {soft_cap}-char soft cap "
        f"(8,000 absolute fallback). Trim description/when_to_use:\n" + "\n".join(breakdown)
    )


_INTERNAL_VERSION_REF = re.compile(r"\bv0\.\d+\.\d+")


def test_no_internal_version_refs_in_user_facing_files() -> None:
    """Internal plugin version numbers belong in CHANGELOG / commits /
    docs/internal — never in SKILL.md, skill references, or agent bodies
    (they go stale immediately and leak release internals to users).
    Exempt: lines mentioning schema_version (contractual artifact
    identifiers) and cap-table-rules.json refs (rule-pack DATA-file version
    pin, not a plugin release ref — confirmed contractual semantics)."""
    repo = Path(__file__).resolve().parents[2] / "founder-skills"
    files = (
        list(repo.glob("skills/*/SKILL.md"))
        + list(repo.glob("skills/*/references/*.md"))
        + list(repo.glob("agents/*.md"))
    )
    assert files, "glob found no user-facing files — path layout changed?"
    offenders = []
    for path in files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "schema_version" in line or "cap-table-rules" in line:
                continue
            if _INTERNAL_VERSION_REF.search(line):
                offenders.append(f"{path.relative_to(repo)}:{i}: {line.strip()}")
    assert not offenders, "internal version refs in user-facing files:\n" + "\n".join(offenders)


# Matches `uv run mypy founder-skills/skills/<skill>/scripts/` invocations in
# either CLAUDE.md's Type Checking section or ci.yml's typecheck job.
_MYPY_SKILL_DIR = re.compile(r"uv run mypy (founder-skills/skills/[\w-]+/scripts/)")


def _mypy_skill_dirs(text: str) -> set[str]:
    return set(_MYPY_SKILL_DIR.findall(text))


def test_ci_mypy_matrix_matches_claude_md() -> None:
    """Every skill scripts dir mypy-checked per CLAUDE.md's Type Checking
    section must also be type-checked in ci.yml's typecheck job. Guards against
    a new skill being added to the docs but silently omitted from CI (the
    v0.4.3 bug class, where competitive-positioning was missing from the
    matrix, and the later recurrence with cap-table)."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    documented = _mypy_skill_dirs(claude_md)
    in_ci = _mypy_skill_dirs(ci_yml)
    assert documented, "no `uv run mypy founder-skills/skills/.../scripts/` lines found in CLAUDE.md"

    missing = sorted(documented - in_ci)
    assert not missing, (
        "CLAUDE.md's Type Checking section lists skill scripts dirs that ci.yml's "
        "typecheck job does not run mypy on (untypechecked in CI):\n" + "\n".join(missing)
    )
