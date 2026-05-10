"""Tests for the Cowork async sub-agent tool-allowlist intersection helper."""

from __future__ import annotations

import pytest
from cowork_async_subagent_filter import (
    COWORK_ASYNC_SUBAGENT_ALLOWLIST,
    apply_filter,
)


def test_allowlist_excludes_bash() -> None:
    assert "Bash" not in COWORK_ASYNC_SUBAGENT_ALLOWLIST


def test_allowlist_excludes_task_and_askuserquestion() -> None:
    """Cowork strips dispatch + interactive tools from async sub-agents."""
    assert "Task" not in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert "AskUserQuestion" not in COWORK_ASYNC_SUBAGENT_ALLOWLIST


def test_allowlist_includes_persistence_tools() -> None:
    """Write/Edit must survive the filter (this is the v0.3.1 fix)."""
    assert "Write" in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert "Edit" in COWORK_ASYNC_SUBAGENT_ALLOWLIST


def test_taskstop_in_but_task_out() -> None:
    """TaskStop lets a sub-agent terminate itself; Task would let it dispatch
    further sub-agents recursively, which the platform forbids."""
    assert "TaskStop" in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert "Task" not in COWORK_ASYNC_SUBAGENT_ALLOWLIST


def test_apply_filter_intersects_to_allowlist() -> None:
    declared = ["Read", "Write", "Edit", "Bash", "Task", "Glob"]
    filtered = apply_filter(declared)
    assert "Bash" not in filtered
    assert "Task" not in filtered
    assert set(filtered) == {"Read", "Write", "Edit", "Glob"}


# Documentation tripwires: assert behavior on tool-name classes the founder-skills
# suite doesn't currently use, so future contributors don't assume them.


@pytest.mark.parametrize("mcp_name", ["mcp__foo__bar", "mcp__claude_ai_Slack__send"])
def test_mcp_tools_are_filtered_out(mcp_name: str) -> None:
    """MCP-tool names go through the same allowlist intersection. Since none
    of them are in the frozenset, all are filtered. Documenting current
    behavior — if Cowork ever passes MCP tools through, update the allowlist."""
    assert apply_filter([mcp_name]) == []


@pytest.mark.parametrize("bg_tool", ["BashOutput", "KillShell"])
def test_background_process_tools_filtered(bg_tool: str) -> None:
    """Background-process management tools are pointless without Bash and
    are not in the allowlist. Test asserts current behavior."""
    assert apply_filter([bg_tool]) == []


# The 5 desktop-side scope-excluded names — none should be in the allowlist.
# This is the source of the v0.4.0 failure pattern (declarations naming
# scope-excluded tools silently no-op).
@pytest.mark.parametrize("scope_excluded", ["Bash", "NotebookEdit", "REPL", "JavaScript", "WebFetch"])
def test_desktop_scope_excluded_not_in_allowlist(scope_excluded: str) -> None:
    """Desktop-side scope exclusion removes 5 tool names BEFORE the CLI's
    runtime tool registry is built. None should be in the allowlist."""
    assert scope_excluded not in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert apply_filter([scope_excluded]) == []


def test_websearch_in_but_webfetch_out() -> None:
    """WebSearch IS in the registry; WebFetch is scope-excluded. Easy to
    confuse the pair, so assert both directions explicitly."""
    assert "WebSearch" in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert "WebFetch" not in COWORK_ASYNC_SUBAGENT_ALLOWLIST
