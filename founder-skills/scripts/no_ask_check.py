#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""PreToolUse hook: no question is put in a run whose request said not to ask.

WHY. A host that runs a skill with nobody to answer sends `FS_HOST_NO_ASK`. The skills' scripts then take each
question's default or stop the run `waiting` (exit 12), and the recorder refuses an answer typed by the model.
What a script cannot stop is the question tool itself, so this check holds it: every `AskUserQuestion` in such a
run is denied, with no retry budget (there is nobody to answer a retry either).

WHICH RUN. The request is the current prompt: a founder's own message (never a tool's text, a skill's expanded
text, a sub-agent or a compaction summary) carrying an `FS_HOST_NO_ASK` line. Otherwise, the run's ledger: the
latest run status `start` result in the current prompt names it, and a ledger with the flag set keeps the run
no-ask (the flag is sticky). That covers a resume that left the line out, and a host that passes its request
lines as the skill's arguments (they reach the transcript only in the skill's expanded text, which never
counts). What it trusts is what the run's ledger records that the request carried (`two_figures_check.py`,
THE ONE ARTIFACT READ). The path is the session shell's, so it opens only where the hook shares that
filesystem (the plain CLI, a host running the CLI in one container, Cowork in the cloud); at Cowork local
the hook runs on the host outside the session's shell, and only the request's own message counts. The
helpers are `two_figures_check.py`'s, shared with the dispatch checks and the Stop hook.

Plain-chat questions are out of any hook's reach; the scripts' stop text and the skill's Step 0 rule cover them.

FAIL OPEN. Any error, any unexpected shape: no decision, one stderr line at most (the runner in
`pretooluse_dispatch.py`). Python 3.9: it runs host-native at the host loop.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

QUESTION_TOOL = "AskUserQuestion"
MARKER = "[no-ask-check]"
REASON = (
    f"{MARKER} The request said not to ask, so no question can be put in this run, in this tool or in chat. Run "
    "this question's open (it exits 12) and end the turn, saying in one sentence what the run is waiting for."
)


def _load(name: str) -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def is_no_ask(rows: list[dict[str, Any]], tools: Any, figures: Any) -> bool:
    start = tools._current_prompt_start(rows)
    if figures.no_ask_in(rows, start, tools._is_real_user_prompt):
        return True
    return bool(figures.ledger_no_ask(figures.read_ledger(figures.ledger_path(rows[start:]))))


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != QUESTION_TOOL:
        return None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    tools = _load("stop_handover_check")
    figures = _load("two_figures_check")
    rows = tools.read_transcript(transcript)
    if not is_no_ask(rows, tools, figures):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
