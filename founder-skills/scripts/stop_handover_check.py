#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Stop hook: after the model's final turn, does the founder's message carry the printed hand-over?

WHY A HOOK. market-sizing prints its closing message from report.json (closing_message.py) so the
model has nothing to compute in chat. Three prose rules and two message shapes were measured not
to land (0/2 at hostloop on the last one): the model kept the links, dropped the pointer, and wrote
its own verdict with its own rounding. The message is the one founder-facing surface with no
script between the model and the reader -- until this one. Claude Code's Stop hook runs after the
final turn; a `{"decision": "block", "reason": …}` reply sends the model back once.

A BLOCK APPENDS, IT DOES NOT RETRACT. The faulted message stays on screen; the model's rewrite lands
under it after a user turn "Stop hook feedback:\\n<reason>". So the reason dictates a follow-up the
founder will read beneath that message, and Half 1 (the printed message already answers the
question) is the prevention; this is the repair. The follow-up's lead states where the text comes
from and which figure wins on a conflict -- never that the message above was wrong: the rule cannot
tell a wrong figure from a correctly paraphrased one, and a block fires on both.

TRIGGER FROM THE TRANSCRIPT, NOT THE MESSAGE. Keying on the message's first words fails exactly when
the model rewrites the first words. The trigger is a `closing_message.py` tool call after the last
real user prompt -- the same key the e2e lane uses. What is judged is EVERY top-level assistant text
after that call, not `last_assistant_message`: tool calls (present_files, TaskUpdate) sit between
the call and the final text on real runs, and text emitted before them is founder-visible.

LOCATE FROM cwd, NOT FROM THE MESSAGE. The model's `--report` path is in whichever namespace its shell
had (VM `/sessions/…` at hostloop) while this hook runs host-side; the links in the message are what
it may have rewritten. stdin's `cwd` is a contract: hostloop = the outputs host dir, Claude Code =
the working dir, VM-loop = `/sessions/<id>`. `handover.txt` is found under
`<cwd>/artifacts/market-sizing-*/` or `<cwd>/mnt/outputs/artifacts/market-sizing-*/`, newest first.

FAIL OPEN. Any error, any unexpected shape, any other skill's stop: exit 0, no stdout, one stderr
line at most. `stop_hook_active` true: exit 0 -- one rewrite is the budget. The skill does not
depend on this hook (test_skill_orchestration.py forbids that); it is enforcement, not plumbing.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import sys
from typing import Any

TRIGGER = "closing_message.py"
HANDOVER_GLOBS = ("artifacts/market-sizing-*/handover.txt", "mnt/outputs/artifacts/market-sizing-*/handover.txt")
STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
CORRECTION_LEAD = (
    "For the record, this is the summary as the analysis produced it; "
    "if a figure in my message above differs from one here, use the one here:"
)


def _log(msg: str) -> None:
    print(f"stop_handover_check: {msg}", file=sys.stderr)


def _load_contained() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_handover_check.py")
    spec = importlib.util.spec_from_file_location("_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.contained


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _is_real_user_prompt(row: dict[str, Any]) -> bool:
    """A founder's turn: type user, not meta (skill attachments, hook feedback), carrying text."""
    if row.get("type") != "user" or row.get("isMeta") or row.get("isSidechain"):
        return False
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def read_transcript(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def text_after_closing_call(rows: list[dict[str, Any]]) -> str | None:
    """Every top-level assistant text after the last closing_message.py call of the current prompt
    (restarting after any Stop-hook feedback turn), or None when the current prompt made no such
    call: this stop is not ours."""
    start = 0
    for i, row in enumerate(rows):
        if _is_real_user_prompt(row):
            start = i
    call_at = None
    for i in range(start, len(rows)):
        row = rows[i]
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and TRIGGER in json.dumps(b.get("input")):
                call_at = i
    if call_at is None:
        return None
    texts: list[str] = []
    for row in rows[call_at + 1 :]:
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "user" and row.get("isMeta") and _text_of(content).startswith(STOP_FEEDBACK_PREFIX):
            # A hook already sent the model back once; judge its latest attempt, not the history.
            texts = []
            continue
        if row.get("type") != "assistant":
            continue
        t = _text_of(content)
        if t.strip():
            texts.append(t)
    return "\n".join(texts)


def find_handover(cwd: str) -> str | None:
    candidates: list[str] = []
    for pattern in HANDOVER_GLOBS:
        candidates.extend(glob.glob(os.path.join(cwd, pattern)))
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def decide(payload: dict[str, Any]) -> dict[str, str] | None:
    """The block to emit, or None to let the stop through. Raises on nothing; callers fail open."""
    if payload.get("hook_event_name") != "Stop" or payload.get("stop_hook_active"):
        return None
    transcript = payload.get("transcript_path")
    final: str | None = None
    if isinstance(transcript, str) and os.path.isfile(transcript):
        final = text_after_closing_call(read_transcript(transcript))
    else:
        # No transcript to trigger from: the message's own opener is the only key left.
        last = payload.get("last_assistant_message")
        if isinstance(last, str) and "finished market sizing" in last:
            final = last
    if final is None:
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        return None
    handover = find_handover(cwd)
    if handover is None:
        _log(f"closing_message.py ran but no handover.txt under {cwd}")
        return None
    with open(handover, encoding="utf-8") as fh:
        printed = fh.read()
    ok, why = _load_contained()(printed, final)
    if ok:
        return None
    reason = (
        f"Your last message did not deliver the printed hand-over as written ({why}). "
        "That message is already in front of the founder, so send a follow-up: the line below, then the "
        "printed hand-over exactly as printed, and nothing with a number outside it.\n\n"
        f"{CORRECTION_LEAD}\n\n{printed.rstrip()}"
    )
    return {"decision": "block", "reason": reason}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        block = decide(payload)
        if block is not None:
            sys.stdout.write(json.dumps(block))
    except Exception as e:  # noqa: BLE001 - a hook that crashes blocks nothing and confuses everyone
        _log(f"{type(e).__name__}: {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
