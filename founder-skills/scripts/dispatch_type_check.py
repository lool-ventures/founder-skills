#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""A known dispatch goes to its own agent: a `CONTEXT:` prompt sent with no `subagent_type`, or the
wrong one, is held and told which agent to name.

WHY. A dispatch with no `subagent_type` falls back to the wildcard `general-purpose` agent, and
`claude` is another built-in catch-all: both carry a shell and every tool, and none of the agent body
the prompt was written for -- its scoped tools, its output contract, its rules. The prompt-equality
check (`dispatch_prompt_check.py`) only looks at a registered (context, agent) pair, so a reviewer
prompt sent to the wrong agent was never compared at all.

THE TABLE. Every context line a skill's dispatch templates open with (SKILL.md and its references/),
and every one a prompt generator prints, mapped to the agents its own skill sends it to.
`test_dispatch_type_check.py` derives the same table from those files and asserts equality, so a new
context line cannot be missing from it. A context line not in the table passes unchecked.

WHICH AGENT. Where the transcript shows which founder-skills skills this session has started (a
`Skill` call, or a `<command-name>`), the dispatch must name one of those skills' agents; otherwise any
agent the table lists for the context. Every skill started counts, not only the latest: one session
can run several (a deck review and a market sizing, side by side), and narrowing to the latest one
held the earlier skill's own dispatches in kept runs. The first line is matched by prefix with a word boundary, so
`CONTEXT: CHECKLIST (repair)` still needs the right agent.

NOT OURS. An agent named with another plugin's prefix (`other:market-sizing`) is not ours. A dispatch
in a session that started no founder-skills skill, whose prompt has no OUTPUT_PATH line, is taken to be
another plugin's and passes.

THE BUDGET. Its own: the `[dispatch-type][<OUTPUT_PATH>]` marker, at most two holds per OUTPUT_PATH,
then let through with one stderr line. Separate from the prompt check's, so holds for the wrong agent
never spend the holds a steered prompt to the right agent gets. With no
transcript the holds cannot be counted, so the dispatch passes rather than risk a hold that never
ends.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from typing import Any

MARKER = "[dispatch-type]"
MAX_HOLDS = 2
DISPATCH_TOOLS = ("Agent", "Task")
PLUGIN = "founder-skills"
SKILLS = (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
)
_COACH = SKILLS
# context name -> the agents (name after the plugin prefix) its skills send it to.
CONTEXT_AGENTS: dict[str, tuple[str, ...]] = {
    "ARTICLES_OF_ASSOCIATION_EXTRACTION": ("cap-table",),
    "INSTRUMENT_EXTRACTION": ("cap-table",),
    "SPREADSHEET_STRUCTURE_DETECTION": ("cap-table",),
    "COMPETITOR_RECALL": ("competitive-positioning",),
    "COMPETITOR_VERIFICATION": ("competitive-positioning",),
    "LANDSCAPE_RESEARCH": ("competitive-positioning",),
    "MOAT_SCORING": ("competitive-positioning",),
    "POSITIONING_SCORING": ("competitive-positioning",),
    "STARTUP_RESEARCH": ("competitive-positioning",),
    "INTERPRETATION": ("deck-review",),
    "LEDGER_EXTRACTION": ("deck-review",),
    "RELATION_PROPOSAL": ("deck-review",),
    "SECOND_READ": ("deck-review",),
    "SLIDE_REVIEWS": ("deck-review",),
    "INPUTS_REVIEW": ("financial-model-review",),
    "DETECT_CONFLICTS": ("ic-sim",),
    "PARTNER_ANALYSIS": ("ic-sim",),
    "PARTNER_REBUTTAL": ("ic-sim",),
    "SCORE_DIMENSIONS": ("ic-sim",),
    "BOTTOM_UP_METHODOLOGY": ("market-sizing",),
    "SENSITIVITY_TEST": ("market-sizing",),
    "TOP_DOWN_METHODOLOGY": ("market-sizing",),
    "CHECKLIST": ("competitive-positioning", "deck-review", "financial-model-review", "market-sizing"),
    "RED_TEAM": ("competitive-positioning-redteam", "market-sizing-redteam"),
    "POST_COMPOSE_COACHING": _COACH,
}
# Characters that render as nothing, removed before the first line is read.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
_CONTEXT_RE = re.compile(r"^CONTEXT:[ \t]*([A-Z][A-Z0-9_]*)(?![A-Za-z0-9_])")
_OUTPUT_RE = re.compile(r"^[ \t]*OUTPUT_PATH:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_COMMAND_RE = re.compile(r"<command-name>/?([^<]*)</command-name>")


def _transcript_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stop_handover_check.py")
    spec = importlib.util.spec_from_file_location("stop_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def context_of(prompt: str) -> str | None:
    """The context name on the prompt's first non-blank line, or None."""
    first = next((s for s in (line.translate(_INVISIBLE).strip() for line in prompt.splitlines()) if s), "")
    m = _CONTEXT_RE.match(first)
    return m.group(1) if m else None


def _bare(name: str) -> str:
    """The name after our plugin's prefix, or the bare name; another plugin's `x:<name>` is not ours."""
    name = name.strip()
    if name.startswith(f"{PLUGIN}:"):
        return name[len(PLUGIN) + 1 :]
    return "" if ":" in name else name


def _has_tool_result(content: Any) -> bool:
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _invocations(rows: list[dict[str, Any]], *, in_results: bool) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        if row.get("isSidechain"):
            continue
        message = row.get("message") or {}
        content = message.get("content")
        if row.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                    skill = (b.get("input") or {}).get("skill")
                    if isinstance(skill, str) and _bare(skill) in SKILLS:
                        found.append((i, _bare(skill)))
        elif row.get("type") == "user" and (in_results or not _has_tool_result(content)):
            for name in (n for t in strings(message) for n in _COMMAND_RE.findall(t)):
                if _bare(name) in SKILLS:
                    found.append((i, _bare(name)))
    return found


def invocations(rows: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """(row index, skill) for each time the main thread started a founder-skills skill, in order: a
    `Skill` call, or a slash command's `<command-name>` in a user row. A `<command-name>` inside a tool
    result is text a tool returned, not a command the founder ran."""
    return _invocations(rows, in_results=False)


def started_skills(rows: list[dict[str, Any]]) -> set[str]:
    """The founder-skills skills started on the main thread so far (empty when none shows). Wider than
    `invocations`: a `<command-name>` a tool returned counts here, which only widens the agents a
    dispatch may name."""
    return {skill for _i, skill in _invocations(rows, in_results=True)}


def expected_agents(context: str, skills: set[str]) -> tuple[str, ...]:
    """The table's agents for `context`, narrowed to the started skills' own when that leaves any."""
    allowed = CONTEXT_AGENTS[context]
    own = tuple(a for a in allowed if a in skills or a.removesuffix("-redteam") in skills)
    return own or allowed


def strings(obj: Any) -> Any:
    """Every string inside a decoded JSON value, so a marker is found in the text the runtime wrote and
    not in an encoding that escapes non-ASCII characters, quotes and backslashes."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)


def _holds(rows: list[dict[str, Any]], output_path: str) -> int:
    mark = f"{MARKER}[{output_path}]"
    return sum(1 for row in rows if row.get("type") == "user" and any(mark in t for t in strings(row.get("message"))))


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not isinstance(tool_input, dict):
        return None
    context = context_of(prompt)
    if context is None or context not in CONTEXT_AGENTS:
        return None
    agent = tool_input.get("subagent_type")
    sent = (_bare(agent) or "another plugin's agent") if isinstance(agent, str) and agent.strip() else None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        if sent not in CONTEXT_AGENTS[context]:
            print(f"dispatch_type_check: {context} sent to {agent!r}; no transcript, not held", file=sys.stderr)
        return None
    rows = _transcript_tools().read_transcript(transcript)
    started = started_skills(rows)
    if not started and not _OUTPUT_RE.search(prompt):
        return None  # no founder-skills skill started and no hand-off path: another plugin's dispatch
    want = expected_agents(context, started)
    if sent in want:
        return None
    m = _OUTPUT_RE.search(prompt)
    output_path = m.group(1) if m else "?"
    if _holds(rows, output_path) >= MAX_HOLDS:
        print(f"dispatch_type_check: {output_path} sent to {agent!r} after {MAX_HOLDS} holds", file=sys.stderr)
        return None
    names = " or ".join(f'"{PLUGIN}:{a}"' for a in want)
    got = f'"{agent}"' if sent is not None else "no subagent_type, which falls back to a general-purpose agent"
    reason = (
        f"{MARKER}[{output_path}] Held: a CONTEXT: {context} dispatch goes to its own agent, and this one "
        f"named {got}. Send the same prompt again with subagent_type {names}."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
