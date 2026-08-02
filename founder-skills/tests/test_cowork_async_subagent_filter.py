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
    """Dispatch + interactive tool names don't resolve in Cowork async
    sub-agent contexts (parent-only; not registered for the dispatch
    context)."""
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


@pytest.mark.parametrize(
    "mcp_name",
    ["mcp__workspace__bash", "mcp__foo__bar", "mcp__claude_ai_Slack__send"],
)
def test_mcp_tools_pass_through(mcp_name: str) -> None:
    """`mcp__*` names take the runtime's MCP fast-path: they resolve against
    the MCP server registry, not the native-tool allowlist, so the helper
    passes them through unconditionally. (Repo POLICY still forbids agents
    declaring any `mcp__*` name — that's enforced in
    test_cowork_invariants.py, not here.)"""
    assert apply_filter([mcp_name]) == [mcp_name]


def test_workspace_bash_survives_but_literal_bash_does_not() -> None:
    """The v0.4.7 probe finding in one assertion pair: Cowork registers shell
    as `mcp__workspace__bash` (resolvable if declared), while the literal
    `Bash` name doesn't exist in the sub-agent registry."""
    assert apply_filter(["mcp__workspace__bash", "Bash"]) == ["mcp__workspace__bash"]


def test_toolsearch_survives() -> None:
    """ToolSearch is immediate-tier and available to sub-agents — it's what
    loads a deferred MCP tool's schema on demand."""
    assert "ToolSearch" in COWORK_ASYNC_SUBAGENT_ALLOWLIST
    assert apply_filter(["ToolSearch"]) == ["ToolSearch"]


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
