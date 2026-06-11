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


# Sub-agent-affirmative cue patterns (regex). Each pattern matches an
# instruction telling the agent TO dispatch a sub-agent — not negations.
# Match is case-insensitive. The negation check is *prefix-only* (only the
# part of the line BEFORE the cue match) so "Dispatch X. Do not Y." correctly
# treats the dispatch as affirmative (the "Do not" applies to Y, not X).
#
# Design notes (rev 5):
# - The bare `task` alternative was DROPPED from the dispatch cues — it
#   matched "Dispatch the Task tool" (Task as object, not subject) which is
#   not the v0.4.0 pattern.
# - The `via Task tool` cue requires a `dispatch(...)` anchor in the same
#   line BEFORE it — otherwise documentary mentions like "the harness uses
#   Task tool internally" fire false positives.
_SUBAGENT_AFFIRMATIVE_CUES = (
    # "Dispatch a sub-agent", "Dispatch the deck-review sub-agent", etc.
    # Note: `.+?\s+agent` matches "Dispatch the X agent" generically.
    re.compile(r"\bdispatch\s+(a|the)\s+(sub-?agent|.+?\s+agent)\b", re.IGNORECASE),
    re.compile(r"\bspawn\s+(a|the)\s+sub-?agent\b", re.IGNORECASE),
    # "Dispatch X via the Task tool" — require dispatch verb in line prefix.
    re.compile(
        r"\bdispatch(?:ed|ing|es)?\b[^\n]*?\bvia\s+(?:the\s+)?`?Task`?\s+tool\b",
        re.IGNORECASE,
    ),
)

# Negation tokens. Checked only in the line PREFIX before the cue match,
# not anywhere on the line — this distinguishes "Do not dispatch X" (negates
# the dispatch) from "Dispatch X. Do not Y." (does NOT negate the dispatch).
_NEGATION_TOKEN = re.compile(
    r"\b(do\s*not|don't|never|must\s+not|skip(?:\s+the)?|without|instead\s+of)\b",
    re.IGNORECASE,
)

# v0.4.0 footgun pattern: bash inside a sub-agent prompt template that
# the sub-agent is supposed to execute. Heuristic: a bash block that
# appears INSIDE a window suspiciously close to a sub-agent dispatch
# instruction. The legitimate v0.4.1 pattern (main thread runs bash to
# extract a payload, then dispatches) is silenced via suppression marker.
_WINDOW_LINES = 10


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_skill_md_subagent_blocks_have_no_bash(skill_md: Path) -> None:
    """Heuristic: a sub-agent-affirmative cue followed within 10 lines by a
    fenced ```bash block is the v0.4.0 failure pattern.

    Negation handling: a "do NOT" / "skip" / "without" / "instead of" token
    appearing in the line PREFIX before the cue match negates the cue. A
    negation token appearing AFTER the cue is irrelevant ("Dispatch X. Do
    not also do Y." is still an affirmative dispatch).

    Suppression: add `<!-- skill-quality-ci: bash-after-subagent-ok -->`
    ANYWHERE between the cue line (inclusive) and the bash fence
    (exclusive). The full window between cue and bash is scanned.

    Note on adjacent cues: a single marker placed between two cues that
    share a downstream bash block silences findings for BOTH cues.
    """
    lines = skill_md.read_text().splitlines()
    suppress_marker = "<!-- skill-quality-ci: bash-after-subagent-ok -->"
    issues: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        # Find the first cue match anywhere in the line
        cue_match = None
        for pattern in _SUBAGENT_AFFIRMATIVE_CUES:
            m = pattern.search(line)
            if m:
                cue_match = m
                break
        if cue_match is None:
            continue
        # Negation check: only the line prefix BEFORE the cue match counts.
        prefix = line[: cue_match.start()]
        if _NEGATION_TOKEN.search(prefix):
            continue
        # Look ahead _WINDOW_LINES for ```bash
        window = lines[i + 1 : i + 1 + _WINDOW_LINES]
        for j, w in enumerate(window):
            if not w.strip().startswith("```bash"):
                continue
            # Suppression marker may appear ANYWHERE between the cue line
            # (inclusive) and the bash fence (exclusive). Scan that range.
            suppression_range = [lines[i], *window[:j]]
            if any(suppress_marker in s for s in suppression_range):
                break
            issues.append((i + 1, line.strip()[:80]))
            break
    assert not issues, (
        f"{skill_md.relative_to(REPO_ROOT)}: sub-agent dispatch cue followed"
        f" by ```bash within {_WINDOW_LINES} lines (v0.4.0 failure pattern):\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in issues)
        + "\n\nIf this is a legitimate payload-extraction-then-dispatch "
        "pattern (main thread extracts, then dispatches), add "
        "`<!-- skill-quality-ci: bash-after-subagent-ok -->` anywhere "
        "between the cue line and the bash block."
    )


# Producer pipes that write a pipeline artifact (-o <path>.json).
_PIPE_WRITES_JSON = re.compile(r'\.py\b[^\n|]*\s-o\s+"?[^"\n]*\.json')
# Scripts that write JSON but do not mint a run_id, exempt from the stamping
# check: orchestrators / renderers / receipts, plus artifacts that are NOT in
# the Context B run_id-parity set (FMR's model_data / extraction_validation are
# pre-pipeline extraction outputs, not parity artifacts).
_RUN_ID_EXEMPT_SCRIPTS = (
    "compose_report.py",  # consumes run_ids, does not mint them
    "visualize.py",
    "explore.py",
    "find_artifact.py",
    "founder_context.py",
    "extract_model.py",  # model_data.json — not a run_id-parity artifact
    "validate_extraction.py",  # extraction_validation.json — not parity-checked
)
# All six skills now stamp metadata.run_id from --run-id on the producer CLI.
# Two mechanisms exist (both satisfy the Context B run_id-parity check) and the
# pipe must carry --run-id either way:
#   - CLI-stamping: producer sets metadata.run_id from --run-id.
#   - stdin passthrough + CLI override: producer propagates stdin metadata.run_id
#     but --run-id (when passed, as the SKILL.md pipes now do) takes precedence.
# Its ABSENCE deterministically BLOCKED Context B in the ic-sim / market-sizing
# regression, so every artifact-writing producer pipe must pass it.


@pytest.mark.parametrize("skill_md", SKILL_MD_FILES, ids=lambda p: p.parent.name)
def test_producer_pipes_carry_run_id(skill_md: Path) -> None:
    """Every `... script.py ... -o <artifact>.json` invocation in a SKILL.md
    bash block must pass --run-id so the producer stamps metadata.run_id
    (regression guard for the ic-sim / market-sizing Context B blocker)."""
    text = skill_md.read_text(encoding="utf-8")
    offenders: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not _PIPE_WRITES_JSON.search(line):
            continue
        if any(exempt in line for exempt in _RUN_ID_EXEMPT_SCRIPTS):
            continue
        if "--run-id" not in line:
            offenders.append(line[:100])
    assert not offenders, (
        f"{skill_md.relative_to(REPO_ROOT)}: artifact-writing producer pipe(s) "
        f"missing --run-id (Context B run_id-parity will BLOCK):\n" + "\n".join(f"  {o}" for o in offenders)
    )
