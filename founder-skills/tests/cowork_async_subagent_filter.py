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

  2. Bash has an MCP replacement: `mcp__workspace__bash` (deferred-tier
     MCP). Sub-agents that need shell can declare this name explicitly
     in `tools:` AND use `ToolSearch` (immediate-tier) to load its
     schema on demand. Inline skills (no fork) use it transparently via
     the model's `ToolSearch` integration — no explicit declaration
     required.

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
"filter strips Bash" framing — the mechanism is name-registration mismatch,
not filtering).
Update the constant if the platform's sub-agent native-tool registry changes.
"""

from __future__ import annotations

# Tool NAMES that resolve natively in Cowork sub-agent dispatch contexts.
#
# Notable absences (the desktop-side scope exclusion removes 5 tools BEFORE
# the CLI's runtime tool registry is built — these names don't exist in the
# Cowork sub-agent registry at all):
#   - Bash         (replaced by mcp__workspace__bash, deferred MCP tier;
#                   reachable via explicit declaration + ToolSearch)
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
    }
)


def apply_filter(declared_tools: list[str]) -> list[str]:
    """Return the subset of `declared_tools` whose names resolve natively in
    Cowork's sub-agent tool registry.

    Mirrors the runtime name-resolution: names in `declared_tools` that are
    NOT in `COWORK_ASYNC_SUBAGENT_ALLOWLIST` don't bind to anything, so the
    agent effectively has the filtered subset. (No error from the platform,
    no warning — the agent just can't see the unbound name.)

    The function name retains "filter" terminology because that's what the
    operation does (set intersection); the underlying mechanism is
    name-registration, not post-binding stripping. See module docstring.
    """
    return [t for t in declared_tools if t in COWORK_ASYNC_SUBAGENT_ALLOWLIST]
