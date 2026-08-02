"""Tool-name compatibility check for Cowork sub-agent dispatch.

This is NOT a Cowork environment simulator. It models exactly one mechanism:
the runtime tool-name lookup that happens when a Cowork sub-agent declares
`tools: [...]`. Names registered natively in Cowork's sub-agent registry
resolve; names that aren't silently don't bind anything.

The actual mechanism (per gist update 2026-05-10):

  1. Desktop-side scope exclusion: 5 tool names are removed from the
     registry BEFORE the CLI's filter runs:
       Bash, NotebookEdit, REPL, JavaScript, WebFetch
     These names don't exist in any sub-agent's tool surface.

  2. Bash has an MCP replacement: `mcp__workspace__bash`. Per the
     v0.4.7 probe it is present in the default sub-agent toolset's MCP
     tier: sub-agents that need shell can declare the name explicitly
     in `tools:` (plus `ToolSearch` to load its deferred schema) and it
     resolves. Declaring it is POSSIBLE but DISALLOWED by repo policy —
     no founder-skills agent gets a shell (anti-fabrication +
     portability; see references/skill-execution-model.md "Why
     Inline"). This helper models resolution, not policy; the policy
     lives in test_cowork_invariants.py. Inline skills (no fork) use
     `mcp__workspace__bash` transparently via the model's ToolSearch
     integration — no explicit declaration required.

  3. Other parent-only / non-sub-agent tool names (`Task`,
     `AskUserQuestion`, `SendMessage`) aren't scope-excluded but also
     don't resolve in sub-agent contexts.

This helper's purpose: catch agent declarations that name tools the platform
won't expose under that name. The function still INTERSECTS the declared
list against a known-good set — the file name retains "filter" for
historical reasons, but the underlying mechanism is name-resolution against
Cowork's sub-agent tool registry, not post-processing of an already-bound
tool surface.

Things this helper deliberately does NOT model:
  - PTY recording / stdin-stdout flow (`--bg-pty-host` mode, CLAUDE_PTY_RECORD)
  - Bridge transcript persistence and CLAUDE_BRIDGE_REATTACH_SESSION/SEQ tokens
  - Worktree-isolation runtime prompt mutation (CLAUDE_BG_ISOLATION='worktree')
  - The 5-var BG-context env strip (CLAUDE_CODE_SESSION_KIND, etc.)
  - Permission-mode + hook PreToolUse layering (a name can resolve and still
    be blocked by a hook)
  - Classifier-summary status pipeline (tengu_classifier_disabled_surfaces,
    tengu_cobalt_wren)
  - The main-loop tool registry (where literal `Bash` DOES resolve — that's
    why scripts run fine from the main thread, regardless of this helper)

Add a separate, focused helper if you need to model another mechanism — do
NOT extend this one.

Reference: docs/internal/cowork-architecture-and-v0.4.x-learning.md, plus
gist yaniv-golan/303b6213b7a33167b3f98b076a5f81ad (which corrects the earlier
framing of a runtime filter removing Bash — the mechanism is
name-registration mismatch, not filtering).
Update the constant if the platform's sub-agent native-tool registry changes.
"""

from __future__ import annotations

# Tool NAMES that resolve natively in Cowork sub-agent dispatch contexts.
#
# Notable absences (the desktop-side scope exclusion removes 5 tools BEFORE
# the CLI's runtime tool registry is built — these names don't exist in the
# Cowork sub-agent registry at all):
#   - Bash         (the literal name; its MCP replacement
#                   mcp__workspace__bash IS in the default sub-agent
#                   toolset per the v0.4.7 probe, and mcp__* names take
#                   the MCP fast-path in apply_filter below)
#   - NotebookEdit (scope-excluded; no native replacement)
#   - REPL         (scope-excluded)
#   - JavaScript   (scope-excluded)
#   - WebFetch     (scope-excluded; WebSearch IS available)
# Plus parent-only / non-sub-agent tools:
#   - Task            (recursive dispatch; doesn't grant nested sub-agent
#                      dispatch under default settings — canonicalized to
#                      Agent at parse time but is a filter no-op)
#   - AskUserQuestion (parent-only)
#   - SendMessage     (parent-only)
#
# An agent's `tools:` declaration is looked up name-by-name in the runtime
# tool registry; declared names that aren't registered for the dispatch
# context simply don't bind anything (no error, no warning — the agent
# just can't see the tool).
COWORK_ASYNC_SUBAGENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebSearch",  # WebSearch is registered; WebFetch is scope-excluded
        "TodoWrite",
        "Skill",  # founder-skills doesn't currently invoke Skill recursively;
        # whether the name actually resolves in Cowork sub-agent
        # contexts is empirically verified in Task 4.5.
        "TaskStop",  # Lets a sub-agent terminate itself.
        "ToolSearch",  # Immediate-tier; loads deferred MCP tool schemas.
    }
)


def apply_filter(declared_tools: list[str]) -> list[str]:
    """Return the subset of `declared_tools` whose names resolve in
    Cowork's sub-agent tool registry.

    Mirrors the runtime name-resolution: names in `declared_tools` that are
    NOT in `COWORK_ASYNC_SUBAGENT_ALLOWLIST` don't bind to anything, so the
    agent effectively has the filtered subset. (No error from the platform,
    no warning — the agent just can't see the unbound name.)

    `mcp__*` names pass through unconditionally, matching the runtime's MCP
    fast-path: MCP tool names resolve against the MCP server registry, not
    the native-tool registry this allowlist models. (Whether a given MCP
    server/tool actually exists in the session is a separate question this
    helper doesn't answer — and repo policy forbids agents declaring any
    `mcp__*` name regardless; see module docstring.)

    The function name retains "filter" terminology because that's what the
    operation does (set intersection); the underlying mechanism is
    name-registration, not post-binding stripping. See module docstring.
    """
    return [t for t in declared_tools if t.startswith("mcp__") or t in COWORK_ASYNC_SUBAGENT_ALLOWLIST]
