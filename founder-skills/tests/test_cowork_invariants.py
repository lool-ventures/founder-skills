"""Tests that each agent's declared tool names resolve sensibly in Cowork's
sub-agent tool registry. See cowork_async_subagent_filter.py for the scoping
caveat (this is NOT a full Cowork environment simulator) and for the
mechanism details (name-resolution, not filter)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from cowork_async_subagent_filter import apply_filter

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "founder-skills" / "agents"

# Underscore-prefixed agents are probes/experiments and intentionally
# exempt from the no-dangerous-tools invariant — they may declare tools
# precisely to test the platform's behavior on those tools.
AGENT_FILES = sorted(p for p in AGENTS_DIR.glob("*.md") if not p.stem.startswith("_"))


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    parsed = yaml.safe_load(match.group(1))
    return parsed if isinstance(parsed, dict) else {}


@pytest.mark.parametrize("agent_path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_has_persistence_in_cowork_subagent_registry(agent_path: Path) -> None:
    """Every agent must declare a tool name that resolves to a persistence
    tool (Write or Edit) in Cowork's sub-agent tool registry.

    Without a resolving persistence name, the sub-agent can't produce
    artifacts. This is the v0.3.1 invariant — see
    archived/fmr-cowork-postmortem.md.
    """
    fm = _parse_frontmatter(agent_path)
    declared = fm.get("tools", [])
    assert declared, f"{agent_path.name} has no `tools:` declaration"
    surviving = apply_filter(declared)
    assert "Write" in surviving or "Edit" in surviving, (
        f"{agent_path.name} sub-agent declares no persistence tool name resolving in Cowork sub-agent registry"
    )


# Tool NAMES that don't resolve in Cowork sub-agent dispatch contexts AND
# either have caused real regressions (Bash, AskUserQuestion in v0.4.0) or
# would silently no-op if a future agent declared them. Declaring any of
# these is the v0.4.0 failure pattern: the agent thinks the name binds to a
# tool, the platform doesn't have that name registered for sub-agents, the
# agent improvises with whatever names DID bind (typically Write) and
# produces fabricated results.
#
# Mechanism notes:
#   - The 5 desktop-side scope-excluded names (Bash/NotebookEdit/REPL/
#     JavaScript/WebFetch) are removed from the registry BEFORE the CLI's
#     filter runs. They're not in any sub-agent's tool surface regardless of
#     declaration. Bash is replaced by `mcp__workspace__bash` (deferred MCP),
#     reachable only via explicit declaration + ToolSearch — not from the
#     literal `Bash` name.
#   - Task / AskUserQuestion / SendMessage aren't scope-excluded; they're
#     parent-only or non-sub-agent tools (Task is canonicalized to Agent at
#     parse time but is a filter no-op for nested dispatch).
_DANGEROUS_IF_DECLARED: frozenset[str] = frozenset(
    {
        # Desktop-side scope-excluded (not in Cowork registry at any tier):
        "Bash",  # v0.4.0 — replaced by mcp__workspace__bash
        "NotebookEdit",  # scope-excluded; no native replacement
        "REPL",  # scope-excluded
        "JavaScript",  # scope-excluded
        "WebFetch",  # scope-excluded; WebSearch IS available
        # Parent-only / non-sub-agent:
        "Task",  # recursive sub-agent dispatch isn't exposed
        "AskUserQuestion",  # parent-only tool; v0.4.0 stage gate failure
        "SendMessage",  # parent-only
    }
)


@pytest.mark.parametrize("agent_path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_declares_no_dangerous_tools(agent_path: Path) -> None:
    """v0.4.0 regression detector: an agent must NOT declare tool names that
    don't resolve in Cowork sub-agent contexts AND have caused real failures.

    This is structural. The agent body might honestly never invoke the tool,
    but the declaration itself is a footgun: the next time the agent body is
    edited, the declaration suggests the name binds to a tool and the new
    instructions may rely on it. v0.4.1's design is "if the platform doesn't
    register the name, don't declare it." See
    cowork-architecture-and-v0.4.x-learning.md.

    Through v0.4.6 all 5 agents declared exactly Read/Edit/Glob/Grep — none
    of these are in the dangerous set. v0.4.7 added WebSearch to the
    competitive-positioning agent's allowlist (WebSearch resolves in
    Cowork's sub-agent registry; see probe results in v0.4.7 release notes).
    Other additions to non-dangerous declared tool sets are OK; additions of
    names in _DANGEROUS_IF_DECLARED are what this test catches.
    """
    fm = _parse_frontmatter(agent_path)
    declared = set(fm.get("tools", []))
    dangerous_declared = declared & _DANGEROUS_IF_DECLARED
    assert not dangerous_declared, (
        f"{agent_path.name} declares {sorted(dangerous_declared)} which "
        f"don't resolve in Cowork's sub-agent tool registry (Bash is "
        f"registered as mcp__workspace__bash; Task/AskUserQuestion/SendMessage "
        f"aren't exposed to sub-agents). Either remove from `tools:` "
        f"or document why the agent will never run as a Cowork sub-agent. "
        f"See cowork-architecture-and-v0.4.x-learning.md."
    )


# Agents whose SKILL.md dispatch prompts instruct them to research
# competitors, markets, etc. via WebSearch. These MUST declare WebSearch in
# their tools allowlist — Cowork's named-sub-agent dispatch is strict
# allowlist mode (empirically verified v0.4.7: a sub-agent declared with
# tools: [Read, Edit, Glob, Grep] receives EXACTLY those four names, no MCP
# leakage, no default-toolset injection). Undeclared = unavailable.
#
# Adding/removing an agent here is intentional — call it out in CHANGELOG.
_AGENTS_REQUIRING_WEBSEARCH: frozenset[str] = frozenset(
    {
        "competitive-positioning",
    }
)


@pytest.mark.parametrize("agent_stem", sorted(_AGENTS_REQUIRING_WEBSEARCH), ids=lambda s: s)
def test_research_agents_declare_websearch(agent_stem: str) -> None:
    """v0.4.7 regression detector: agents whose dispatch prompts reference
    WebSearch must declare it. Without the declaration, the sub-agent's
    Phase-A enrichment / moat trajectory / positioning evidence steps
    silently degrade to training-cutoff guesses stamped as `researched`.
    See v0.4.7 release notes and the named-agent probe in
    /tmp/cowork-tool-probe/.
    """
    agent_path = AGENTS_DIR / f"{agent_stem}.md"
    assert agent_path.exists(), (
        f"agent {agent_stem} not found at {agent_path} — update _AGENTS_REQUIRING_WEBSEARCH or rename the agent file"
    )
    fm = _parse_frontmatter(agent_path)
    declared = set(fm.get("tools", []))
    assert "WebSearch" in declared, (
        f"{agent_stem}.md SKILL.md dispatch prompts reference WebSearch "
        f"for competitor/market research, but the agent's `tools:` "
        f"declaration is {sorted(declared)} — WebSearch missing. Cowork's "
        f"named-sub-agent dispatch is strict allowlist mode; undeclared "
        f"tools don't bind. Add 'WebSearch' to the tools list or remove "
        f"the WebSearch references from the dispatch prompts."
    )
