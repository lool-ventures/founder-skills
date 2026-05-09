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

AGENT_FILES = sorted(AGENTS_DIR.glob("*.md"))


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

    All 5 v0.4.4 agents declare exactly Read/Edit/Glob/Grep — none of these
    are in the dangerous set. This test exists to keep that property.
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
