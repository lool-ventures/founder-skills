#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""A generated dispatch prompt is sent as the generator printed it: the red team's, and the checklist's.

THE DEFECT. In round 2 of both live runs that reached it, the main thread ran market-sizing's
`dispatch_prompt.py`, then sent the red team a different prompt: lines naming the revision and what
to look for ("Note: this is a round-2 review after a revision. In round 1, the ARPU input was changed
from $X/month…"). The reviewer repeated it to the founder ("the revised $Y…"). Round 1 matched
both times. SKILL.md says to paste the printed text unchanged; that held 0/2 in round 2. The review
exists to look at the analysis without the constructor's framing, and this is the framing.

THE COMPARAND. The generator's output as the transcript recorded it (a tool result), against the
prompt the Agent call carries. The runtime writes both, so nothing the model writes -- no file, no
hand-off, no field -- can make them agree. Compared with whitespace squashed, as the e2e lane does.

THE BUDGET. A round is held at most twice, then let through with one stderr line: a hook that holds
forever can wedge a run on its own bug. Counted per OUTPUT_PATH, i.e. per round -- the only real user
prompts in a run are its first and its last, so a count per prompt would let round 1's holds spend
round 2's. No disclosure code is written from here: compose reading a marker the hook wrote would
make the report depend on the hook, and a missing marker would read as clean.

NO PRINTED PROMPT. Held, with "run the prompt generator": the only way to satisfy it puts the
comparand in the transcript.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from typing import Any

MARKER = "[dispatch-check]"
# The dispatches whose prompt a generator prints (market-sizing's dispatch_prompt.py, competitive-
# positioning's cp_dispatch_prompt.py). Every such prompt ends with END.
# CHECKLIST: in round 2 the grader was told "round 2 after a revision … down from N% in round 1"
# and wrote it to the founder; round 1's prompt had a verdict inserted.
# (context line, agent name after the plugin prefix) -> the reason a held dispatch is given. A dispatch
# is checked only when BOTH match: deck-review's and financial-model-review's CHECKLIST templates open
# with the same context line and have no generator; matched on the prefix alone, they were held for a
# prompt that cannot exist, or handed market-sizing's. One context line can belong to two skills' pairs.
_REVIEW_REASON = (
    "the review's instructions go out exactly as the prompt generator printed them, with nothing "
    "added, removed or reworded -- the review looks at the analysis without its constructor's framing"
)
# competitive-positioning's scoring and checklist prompts (cp_dispatch_prompt.py). A hand-applied review
# once wrote new scoring rules into these; anything a scorer should know belongs in the files it reads.
_SCORING_REASON = (
    "the scoring instructions go out exactly as the prompt generator printed them, with nothing added, "
    "removed or reworded -- anything the scorer should know belongs in the files it reads, not the prompt"
)
PAIRS: dict[tuple[str, str], str] = {
    ("CONTEXT: RED_TEAM", "market-sizing-redteam"): _REVIEW_REASON,
    ("CONTEXT: CHECKLIST", "market-sizing"): _REVIEW_REASON,
    ("CONTEXT: MOAT_SCORING", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: POSITIONING_SCORING", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: CHECKLIST", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: STARTUP_RESEARCH", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: RED_TEAM", "competitive-positioning-redteam"): _REVIEW_REASON,
}
CONTEXTS = tuple(dict.fromkeys(context for context, _ in PAIRS))
END = "Do NOT write any file other than OUTPUT_PATH."
DISPATCH_TOOLS = ("Agent", "Task")
MAX_HOLDS = 2
# The rest of the line, trimmed: local-lane paths contain spaces ("…/Library/Application Support/…"),
# and a `\S+` capture stopped at the first one, so every round and context shared one key.
# Leading whitespace allowed: a model that re-indents the prompt is still sending the same prompt.
_OUTPUT_RE = re.compile(r"^[ \t]*OUTPUT_PATH:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _transcript_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stop_handover_check.py")
    spec = importlib.util.spec_from_file_location("stop_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content if isinstance(x, dict))
    return ""


_READ_LINE_RE = re.compile(r"^\s*\d+\t", re.MULTILINE)


def _unnumbered(text: str) -> str:
    """The Read tool numbers every line ("1\tCONTEXT: RED_TEAM"); a prompt written with -o and read back
    arrives that way. Strip the numbers only when every non-blank line carries one."""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and all(_READ_LINE_RE.match(line) for line in lines):
        return _READ_LINE_RE.sub("", text)
    return text


def _output_path(text: str) -> str | None:
    m = _OUTPUT_RE.search(text)
    return m.group(1) if m else None


def latest_printed(rows: list[dict[str, Any]], context: str, output_path: str | None = None) -> str | None:
    """The last generator output for `context` in the transcript, through its closing line.

    Scoped to the dispatch's own OUTPUT_PATH when given. The path is what separates one skill's
    prompt from another's (their hand-off dirs differ) and one round from the next (each round gets
    its own path); a Read of a SKILL.md template carries a "<…>" placeholder there, which no real
    path equals. A stale round sent verbatim to its own path therefore passes: it carries no added
    framing, and the missing hand-off for the newer round fails check_handoff loudly downstream.
    """
    found = None
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_result" or b.get("is_error"):
                continue
            text = _unnumbered(_result_text(b))
            start = text.rfind(context)
            if start < 0:
                continue
            end = text.find(END, start)
            if end >= 0:
                candidate = text[start : end + len(END)]
                if output_path is None or _output_path(candidate) == output_path:
                    found = candidate
    return found


def _holds(rows: list[dict[str, Any]], output_path: str) -> int:
    mark = f"{MARKER}[{output_path}]"
    return sum(1 for row in rows if row.get("type") == "user" and mark in json.dumps(row.get("message")))


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    context = next((c for c in CONTEXTS if isinstance(prompt, str) and prompt.lstrip().startswith(c)), None)
    if context is None or not isinstance(prompt, str):
        return None
    agent = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
    reason_text = PAIRS.get((context, agent.rsplit(":", 1)[-1])) if isinstance(agent, str) else None
    if reason_text is None:
        return None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    output_path = _output_path(prompt) or "?"
    rows = _transcript_tools().read_transcript(transcript)
    printed = latest_printed(rows, context, output_path)
    if printed is not None and _squash(printed) == _squash(prompt):
        return None
    if _holds(rows, output_path) >= MAX_HOLDS:
        print(
            f"dispatch_prompt_check: {output_path} sent unlike the printed prompt after {MAX_HOLDS} holds",
            file=sys.stderr,
        )
        return None
    if printed is None:
        reason = (
            f"{MARKER}[{output_path}] Held: this review round has no printed prompt yet. Run the prompt "
            "generator for this round and send its output as the prompt, unchanged."
        )
    else:
        reason = f"{MARKER}[{output_path}] Held: {reason_text}. Send this as the prompt, unchanged:\n\n{printed}"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
