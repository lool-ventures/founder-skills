#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""PreToolUse on AskUserQuestion: hold financial-model-review's values check once when the review page
it asks about was built and never sent.

WHY. At its values check, financial-model-review builds a static review page (`review_inputs.py …
--static`) for the founder to inspect the extracted numbers, sends it, then asks whether the values
look right. Runs built the page and asked without sending it, so the founder was asked to confirm a
page they could not open. The question keeps the turn open while the founder answers, so the Stop
hook cannot see this gate in time; the question itself is the last moment the page can still go first.

WHEN IT HOLDS -- all of these, read from the transcript since the current prompt:
1. A static review build succeeded through a shell tool (server mode writes no page, and is silent).
2. No successful delivery call whose input names that page followed it, and no report build did (past
   the values check the page no longer matters). Other shell calls in between -- a gate record before
   the question, say -- change nothing.
3. The host offered a delivery tool (`_delivery_check.offered_tool`), and this is not the plain CLI.
4. This check has not held a question in the current prompt yet: its marker is looked for in the
   decoded text of every user row, so one hold is the budget and the next question goes through.

Nothing here reads the question's wording or its options: the build, not a label, says which gate this
is. Any other question, in this skill or any other, with no unsent page behind it, is let through.

FAIL OPEN. Any error, any unexpected shape: exit 0, no stdout, one stderr line at most (the runner in
pretooluse_dispatch.py). SKILL.md does not depend on this hook.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

MARKER = "[review-page-check]"
QUESTION_TOOL = "AskUserQuestion"


def _transcript_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stop_handover_check.py")
    spec = importlib.util.spec_from_file_location("stop_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def held_before(rows: list[dict[str, Any]], start: int, strings: Any) -> bool:
    return any(
        row.get("type") == "user" and any(MARKER in s for s in strings(row.get("message"))) for row in rows[start:]
    )


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != QUESTION_TOOL:
        return None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    tools = _transcript_tools()
    delivery = tools._load_delivery()
    rows = tools.read_transcript(transcript)
    if any(r.get("entrypoint") == "cli" for r in rows):
        return None
    start = tools._current_prompt_start(rows)
    pending = delivery.unsent_review_page(rows, start)
    if pending is None:
        return None
    seen, tool = delivery.offered_tool(rows)
    if not seen or tool is None:
        return None
    if held_before(rows, start, delivery._strings):
        return None
    page = pending[1]
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{MARKER} Held once: the review page ({page}) was built for the founder to check the "
                f"extracted values, and it has not been sent. Send {page} with {tool} first, then ask this "
                "question again."
            ),
        }
    }
