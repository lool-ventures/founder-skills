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
    """Every agent must declare `Write` (resolving in Cowork's sub-agent
    tool registry).

    Originally the v0.3.1 invariant (Write-or-Edit so the sub-agent can
    persist at all — see archived/fmr-cowork-postmortem.md). Since the
    Context A file hand-off, `Write` specifically is load-bearing: the
    agent must create its OUTPUT_PATH hand-off file (Edit can't create
    files), so Write-only is now a hard requirement, not one of two
    options.
    """
    fm = _parse_frontmatter(agent_path)
    declared = fm.get("tools", [])
    assert declared, f"{agent_path.name} has no `tools:` declaration"
    surviving = apply_filter(declared)
    assert "Write" in surviving, (
        f"{agent_path.name} sub-agent doesn't declare Write (required to create its "
        f"Context A OUTPUT_PATH hand-off file) or the name doesn't survive the Cowork registry filter"
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
#     declaration. Bash is replaced by `mcp__workspace__bash` (in the default
#     sub-agent toolset's MCP tier per the v0.4.7 probe), reachable via
#     explicit declaration + ToolSearch — not from the literal `Bash` name.
#     Declaring it would WORK; repo policy forbids it (see
#     test_agent_declares_no_mcp_tools below).
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


@pytest.mark.parametrize("agent_path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_declares_no_mcp_tools(agent_path: Path) -> None:
    """Repo POLICY (not a resolution question): no agent declares any
    `mcp__*` tool name.

    `mcp__workspace__bash` / `mcp__workspace__web_fetch` WOULD resolve for a
    Cowork sub-agent that declared them (v0.4.7 probe), but they are
    Cowork-only names — they don't exist in the standalone CLI or other
    hosts — and a sub-agent shell would blur the producer-script-only
    boundary for canonical artifacts (anti-fabrication). The portable
    sub-agent surface is Read/Write/Edit/Glob/Grep (+ WebSearch where
    declared). See references/skill-execution-model.md "Why Inline" and the
    2026-07-04 plan in docs/internal.
    """
    fm = _parse_frontmatter(agent_path)
    declared = fm.get("tools", [])
    mcp_declared = [t for t in declared if isinstance(t, str) and t.startswith("mcp__")]
    assert not mcp_declared, (
        f"{agent_path.name} declares MCP tool names {mcp_declared}. These are "
        f"host-specific (Cowork-only) and grant capabilities repo policy "
        f"reserves for the main thread. Remove them from `tools:`."
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


# Agents whose SKILL.md dispatch prompts hand off a Context A/B artifact via
# an `OUTPUT_PATH:` line — the sub-agent writes its output JSON (or coaching
# markdown) to that path with its Write tool and returns a receipt echoing
# it (see check_handoff.py). These MUST declare Write in their tools
# allowlist — same strict-allowlist reasoning as
# test_research_agents_declare_websearch above, but for the transport every
# Context A/B dispatch depends on rather than one research capability. A
# sub-agent whose declared tools omit Write cannot create OUTPUT_PATH at
# all, and the resulting missing file is indistinguishable at the gate from
# a fabricated receipt (check_handoff.py exit 3) — the redo-dispatch it
# triggers fails identically, burning retry budget before anything points
# at the real cause.
#
# Adding/removing an agent here is intentional — call it out in CHANGELOG.
_AGENTS_REQUIRING_WRITE: frozenset[str] = frozenset(
    {
        "cap-table",
        "competitive-positioning",
        "deck-review",
        "financial-model-review",
        "ic-sim",
        "market-sizing",
    }
)


@pytest.mark.parametrize("agent_stem", sorted(_AGENTS_REQUIRING_WRITE), ids=lambda s: s)
def test_handoff_agents_declare_write(agent_stem: str) -> None:
    """Regression detector: agents whose dispatch prompts hand off via
    OUTPUT_PATH must declare Write. Without the declaration the tool
    doesn't bind at runtime and the hand-off silently fails as a phantom
    missing file — check_handoff.py's exit 3 reads identically to a
    fabricated receipt, so the SKILL.md state machine spends a
    redo-dispatch on a sub-agent that was never able to comply.
    """
    agent_path = AGENTS_DIR / f"{agent_stem}.md"
    assert agent_path.exists(), (
        f"agent {agent_stem} not found at {agent_path} — update _AGENTS_REQUIRING_WRITE or rename the agent file"
    )
    fm = _parse_frontmatter(agent_path)
    declared = set(fm.get("tools", []))
    assert "Write" in declared, (
        f"{agent_stem}.md SKILL.md dispatch prompts carry an OUTPUT_PATH: "
        f"line instructing the sub-agent to hand off via Write, but the "
        f"agent's `tools:` declaration is {sorted(declared)} — Write "
        f"missing. Cowork's named-sub-agent dispatch is strict allowlist "
        f"mode; undeclared tools don't bind. Add 'Write' to the tools list "
        f"or remove the OUTPUT_PATH/Write references from the dispatch "
        f"prompts."
    )
