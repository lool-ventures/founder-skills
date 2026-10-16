#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
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
the model rewrites the first words. The trigger is a skill's closing-message script (SKILLS below:
market-sizing's `closing_message.py`, competitive-positioning's `cp_closing_message.py`) called after
the last real user prompt -- the same key the e2e lane uses. Each script is matched as a WHOLE name,
so neither name matches inside the other and the table's order does not matter; the last such call
in the prompt decides which skill's hand-over is judged. What is judged is EVERY top-level assistant text
after that call, not `last_assistant_message`: tool calls (present_files, TaskUpdate) sit between
the call and the final text on real runs, and text emitted before them is founder-visible.

THE PRINTED TEXT: handover.txt UNDER cwd, ELSE THE CLOSING CALL'S RESULT. Never from the message:
its links are what the model may have rewritten, and the model's `--report` path is in whichever
namespace its shell had (VM `/sessions/…` at hostloop) while this hook runs host-side.
`handover.txt` is looked for under that skill's `<cwd>/artifacts/<skill>-*/` or
`<cwd>/mnt/outputs/artifacts/<skill>-*/`, newest first -- found that way on the CLI (the working dir)
and the cloud lane (`/home/claude`). Under the host-loop spawn newer Desktop uses, cwd is
`/var/empty`, nothing is under it, and a live run's rewritten hand-over went through unchecked. So
when no file is found, the printed text is read from the transcript's record of the closing call:
its tool result, paired by a non-empty id, which a measured run showed equal to handover.txt byte
for byte. That result can carry other commands' output around the hand-over (a recorded run ran
`cp` and `ls` in the same command; stderr lands after stdout), so it is SLICED from the last opener
line to the closing offer both scripts print last, and a result with no such slice -- cut short by
a pipe, or empty after a redirect -- is not used: judging against part of the text would pass a
message that drops the rest. The file stays first so every lane where it works today is unchanged.

`stop-hook-error` IN THE SDK STREAM IS NOT AN ERROR HERE. A blocking Stop hook surfaces to the SDK
as a `notification` whose key is `stop-hook-error`, whatever the hook's outcome was. MEASURED from
the `market-sizing-remote-lane` cassette (2026-09-24), which records all three frames of a real run:
the block carries `exit_code: 0`, `outcome: "success"`, `stderr: ""` and the decision JSON on
stdout; the second Stop invocation carries `exit_code: 0`, `outcome: "success"` and empty output,
which is `stop_hook_active` spending the one-rewrite budget. So a `stop-hook-error` line in a
transcript is the host's label for "a Stop hook returned a block", not evidence this script failed.
Check `stderr` on the frame before believing otherwise.

A REPLY THE HOST SAYS GOES THROUGH A TOOL. On some hosts the founder reads only what a message tool sends;
the plain text is unseen (often just "Done."), so judging it blocks a run that sent the hand-over whole. The
hook cannot know which tool reaches the founder, and a guess fails in the unsafe direction (a hand-over relayed
to a third party would pass), so the host names it: `FS_HOST_REPLY_TOOL <tool_name> <input_key>`, read from a
founder's own message (any prompt of the session, last valid line wins, a slash command's `<command-args>`
unwrapped) and NEVER from the run's ledger, whose lines the model types into `run_status.py start`: a ledger
route would let the model name any tool as the founder's message and remove the hold by writing it. When the
turn sent through that tool after the closing call (exact name, the named input a non-empty string, a
main-thread call whose result is not `is_error`), the sends alone are the message: plain text and the payload's
`last_assistant_message` are not read, so the hand-over sent, then contradicted in plain text, passes -- right
where the plain text is unseen. With no send, or no line, the text is judged as before. A block then asks for
the follow-up through that tool whenever the line names it (send or not), in the lead sentence and never
beside `CORRECTION_LEAD` (that text is resent to the founder). Residual, accepted: with the line and no send, a
hand-over written only as plain text passes, though on such a host it may never be seen -- blocking it would
block every run on a host whose tool calls do not reach the transcript. The line is looked for only on a stop
whose prompt ran a closing script. The line's shape and refused names are a copy of `_gates.py`'s, held equal
by a test.

FAIL OPEN. Any error, any unexpected shape, any other skill's stop: exit 0, no stdout, one stderr
line at most. `stop_hook_active` true: exit 0 and no stdout -- one rewrite is the budget -- but the
follow-up to a HAND-OVER block (its feedback row carries `CORRECTION_LEAD`) is judged anyway and one
stderr line says whether it passed (`second stop: hand-over passed` / `… failed: <why>`), which
measures the closing-rewrite rate; a second stop after any other block, or that ran no closing script,
writes nothing. The skill does not depend on this hook (test_skill_orchestration.py
forbids that); it is enforcement, not plumbing.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys
from typing import Any

# market-sizing's values, unchanged; the table below adds skills beside it.
TRIGGER = "closing_message.py"
HANDOVER_GLOBS = ("artifacts/market-sizing-*/handover.txt", "mnt/outputs/artifacts/market-sizing-*/handover.txt")


def _script(name: str) -> re.Pattern[str]:
    """A script name as a whole word: not preceded by a name character, so "closing_message.py" does
    not match inside "cp_closing_message.py", whatever order the table is in."""
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"\b")


# (skill, trigger script, handover globs, the opener the no-transcript fallback keys on).
SKILLS: tuple[tuple[str, re.Pattern[str], tuple[str, ...], str], ...] = (
    ("market-sizing", _script(TRIGGER), HANDOVER_GLOBS, "finished market sizing"),
    (
        "competitive-positioning",
        _script("cp_closing_message.py"),
        (
            "artifacts/competitive-positioning-*/handover.txt",
            "mnt/outputs/artifacts/competitive-positioning-*/handover.txt",
        ),
        "finished competitive positioning",
    ),
    (
        "financial-model-review",
        _script("fmr_closing_message.py"),
        (
            "artifacts/financial-model-review-*/handover.txt",
            "mnt/outputs/artifacts/financial-model-review-*/handover.txt",
        ),
        "finished financial model review",
    ),
)
STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
# The first and last lines of every printed hand-over, the ends of the slice taken from a tool result.
# test_stop_handover_hook.py holds both closing scripts' output to them.
OPENER_PREFIX = "Here's your "
OFFER_START = "If you want to keep the working data behind this"
OFFER_END = "as a single archive."
CORRECTION_LEAD = (
    "For the record, this is the summary as the analysis produced it; "
    "if a figure in my message above differs from one here, use the one here, "
    "and check any figure above that is not here against the report before relying on it:"
)


def _log(msg: str) -> None:
    print(f"stop_handover_check: {msg}", file=sys.stderr)


# --- the reply tool a request names (FS_HOST_REPLY_TOOL) --------------------------------------------------------
# A copy of `_gates.py`'s rules (a hook never loads `_gates`), held equal by test_stop_reply_tool.py.
REPLY_TOOL_KEYWORD = "FS_HOST_REPLY_TOOL"
REPLY_TOOL_NAME_MAX = 128
REPLY_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1," + str(REPLY_TOOL_NAME_MAX) + "}")
REPLY_TOOL_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
# Names the hook already reads as something else: the shells, dispatch, the question tool, agent-to-agent
# messages and the file-delivery tool. Any name containing `present_files` is a delivery tool too.
REPLY_TOOL_REFUSED = ("Bash", "mcp__workspace__bash", "Agent", "Task", "AskUserQuestion", "SendMessage", "SendUserFile")


def reply_tool_name_problem(name: str) -> str | None:
    """Why `name` cannot be a reply tool, or None."""
    if not REPLY_TOOL_NAME_RE.fullmatch(name):
        return f"the tool name is not letters, digits, underscores or hyphens, at most {REPLY_TOOL_NAME_MAX} long"
    if name in REPLY_TOOL_REFUSED or "present_files" in name:
        return f"{name} is read as another kind of tool"
    return None


def reply_tool_line_problem(rest: str) -> tuple[tuple[str, str] | None, str]:
    """((name, key), "") for a valid line's text after the keyword, else (None, why)."""
    parts = rest.split()
    if not rest.startswith(" ") or len(parts) != 2:
        return None, f"{REPLY_TOOL_KEYWORD} takes two words: <tool_name> <input_key>"
    name, key = parts
    why = reply_tool_name_problem(name)
    if why is not None:
        return None, why
    if not REPLY_TOOL_KEY_RE.fullmatch(key):
        return None, "the input key is not an identifier"
    return (name, key), ""


def reply_tool_in(rows: list[dict[str, Any]], figures: Any) -> tuple[str, str] | None:
    """(tool name, input key) from the last valid `FS_HOST_REPLY_TOOL` line in any founder's own message of the
    session, or None. The rows `no_ask_in` reads (never a tool's text, `isMeta`, a sub-agent, a compaction summary
    or a delivered agent result); never the ledger. A line that breaks the shape is ignored, with a stderr line."""
    found: tuple[str, str] | None = None
    for row in rows:
        if not figures.founders_message(row, _is_real_user_prompt):
            continue
        for text in figures._founder_texts(row):
            for raw in text.splitlines():
                line = raw.strip()
                if not line.startswith(REPLY_TOOL_KEYWORD):
                    continue
                rest = line[len(REPLY_TOOL_KEYWORD) :]
                if rest and not rest[:1].isspace():
                    continue  # another keyword sharing the prefix
                parsed, why = reply_tool_line_problem(rest)
                if parsed is None:
                    _log(f"reply tool line ignored ({why}): {line[:200]}")
                    continue
                found = parsed
    return found


def _reply_tool_or_none(rows: list[dict[str, Any]], figures: Any) -> tuple[str, str] | None:
    """`reply_tool_in`, failing open to None (today's judgement of the plain text) with one stderr line."""
    try:
        return reply_tool_in(rows, figures if figures is not None else _load_figures())
    except Exception as e:  # noqa: BLE001 - fail open
        _log(f"reply tool check: {type(e).__name__}: {e}")
        return None


def _send_clause(reply_name: str | None) -> str:
    """The follow-up's route, for the lead sentence of a reason that asks for one: whenever the request named the
    tool, whether or not the turn used it (on that host a plain-text follow-up may never be seen)."""
    return f" with {reply_name}, the tool the founder reads replies through, not as plain text" if reply_name else ""


def _load_delivery() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_delivery_check.py")
    spec = importlib.util.spec_from_file_location("_delivery_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_NOTIFICATION = "<task-notification>"


def _starts_a_prompt(row: dict[str, Any]) -> bool:
    """A row that opens the current prompt: a founder's turn. Two user rows the runtime writes itself are not:
    a compaction summary (written mid-turn, after the calls the prompt made) and a background agent's result
    delivered as a user row (`origin.kind` other than human, or, on older CLIs, text opening with the
    notification tag)."""
    if not _is_real_user_prompt(row) or row.get("isCompactSummary"):
        return False
    origin = row.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    body = (row.get("message") or {}).get("content")
    if isinstance(body, list):
        body = next((b.get("text") for b in body if isinstance(b, dict) and b.get("type") == "text"), "")
    return not (isinstance(body, str) and body.lstrip().startswith(_NOTIFICATION))


def _current_prompt_start(rows: list[dict[str, Any]]) -> int:
    start = 0
    for i, row in enumerate(rows):
        if _starts_a_prompt(row):
            start = i
    return start


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


def _skill_of_call(tool_input: Any) -> str | None:
    """The skill whose closing-message script this tool call ran, or None."""
    text = json.dumps(tool_input)
    for skill, trigger, _globs, _opener in SKILLS:
        if trigger.search(text):
            return skill
    return None


def printed_from_result(text: str, opener: str) -> str | None:
    """The printed hand-over inside a closing call's tool result, or None when the result holds no
    whole one: the lines from the last opener line to the first closing offer after it."""
    lines = text.splitlines()
    for start in reversed(range(len(lines))):
        if not (lines[start].startswith(OPENER_PREFIX) and opener in lines[start]):
            continue
        for end in range(start, len(lines)):
            line = lines[end].strip()
            if line.startswith(OFFER_START) and line.endswith(OFFER_END):
                return "\n".join(lines[start : end + 1]) + "\n"
        return None
    return None


def _results_by_id(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Top-level tool results keyed by their non-empty tool_use_id."""
    out: dict[str, str] = {}
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                rid = b.get("tool_use_id")
                if isinstance(rid, str) and rid:
                    out[rid] = _text_of(b.get("content"))
    return out


_EXIT_PREFIX = re.compile(r"\[exit (-?\d+)\]")


def _errored_ids(rows: list[dict[str, Any]]) -> set[str]:
    """Ids of top-level tool results that report a failure: `is_error`, or the host loop's `[exit N]` lead
    with N other than 0."""
    out: set[str] = set()
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            rid = b.get("tool_use_id")
            if not (isinstance(rid, str) and rid):
                continue
            m = _EXIT_PREFIX.match(_text_of(b.get("content")).lstrip())
            if b.get("is_error") is True or (m is not None and m.group(1) != "0"):
                out.add(rid)
    return out


def _latest_closing_call(rows: list[dict[str, Any]]) -> tuple[int, int, str, str | None] | None:
    """(current prompt's first row, the row of its last closing-message call, that call's skill, its id or
    None), or None when the current prompt made no such call."""
    start = _current_prompt_start(rows)
    found: tuple[int, int, str, str | None] | None = None
    for i in range(start, len(rows)):
        row = rows[i]
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                skill = _skill_of_call(b.get("input"))
                if skill is not None:
                    cid = b.get("id")
                    found = (start, i, skill, cid if isinstance(cid, str) and cid else None)
    return found


def refused_closing_call(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    """(skill, the first line of its error) when the current prompt's LAST closing-message call failed and
    printed no hand-over -- a closer that refused a report from another run, say. Any handover.txt on disk
    is then an earlier run's, so nothing is judged against it; an earlier closing call of the same prompt
    is never used either. A failed call that still printed a whole hand-over (a compound command whose
    other part failed) is judged as before."""
    latest = _latest_closing_call(rows)
    if latest is None or latest[3] is None:
        return None
    start, _at, skill, cid = latest
    if cid not in _errored_ids(rows[start:]):
        return None
    text = _results_by_id(rows[start:]).get(cid, "")
    opener = next(o for name, _t, _g, o in SKILLS if name == skill)
    if printed_from_result(text, opener) is not None:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not _EXIT_PREFIX.fullmatch(ln.strip())]
    return skill, (lines[0][:300] if lines else "no output")


# shared_tmp_check's hold, as the runtime records it: "PreToolUse:<tool> hook error: [shared-tmp][<path>]...".
_SHARED_TMP_HELD = re.compile(r"\[shared-tmp\]\[([^\]]+)\]")


def refused_reason(skill: str, error: str, sent_via: str | None = None) -> str:
    """The once-only follow-up for a closing step that refused. It states what the closing step did, never
    that the message above was wrong (the rule cannot tell), and dictates no earlier run's hand-over.

    A closing call the shared-/tmp check held never ran: the report needs nothing, only the command again
    without its redirect into the shared temp folder. The check's marker is not repeated, since that check
    counts every main-thread row carrying it as one of its holds."""
    label = skill.replace("-", " ")
    held = _SHARED_TMP_HELD.findall(error) if "hook error:" in error else []
    if held:
        return (
            f"The {label} closing step's last run never ran: its command would have written {', '.join(held)}, "
            "a fixed name in the shared temp folder, and was held before it started, so it printed nothing. "
            f"Your last message is already in front of the founder, so send a follow-up{_send_clause(sent_via)}: "
            "run the closing step again with no redirect into the shared temp folder, and send what it prints "
            "exactly as printed. If it cannot be run again, say so in one line, and add nothing with a number."
        )
    return (
        f"The {label} closing step's last run stopped with an error and printed no hand-over ({error}). Your "
        f"last message is already in front of the founder, so send a follow-up{_send_clause(sent_via)}: compose "
        "the report again for this run, run the closing step again, and send what it prints exactly as printed. "
        "If it cannot be run again, say so in one line, and add nothing with a number."
    )


def text_after_closing_call(rows: list[dict[str, Any]]) -> str | None:
    """Every top-level assistant text after the last closing-message call of the current prompt, or
    None when there was none (see `closing_call`)."""
    found = closing_call(rows)
    return found[1] if found is not None else None


def closing_call(rows: list[dict[str, Any]]) -> tuple[str, str, str | None] | None:
    """(skill, every top-level assistant text after the last closing-message call of the current
    prompt, restarting after any Stop-hook feedback turn, the printed hand-over sliced from that
    last call's result -- else None), or None when the current prompt made no such call: this stop
    is not ours. Only the last call's result is read: an earlier closing call of the same prompt
    printed for figures the run has since replaced (a what-if, a refused re-run). The judgement with
    no reply tool named, which the cassette checker shares (`closing_window` with None)."""
    found = closing_window(rows, None)
    return None if found is None else (found[0], found[1], found[2])


def _failed_results(rows: list[dict[str, Any]]) -> set[str]:
    """Ids of top-level tool results marked `is_error: true`."""
    out: set[str] = set()
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error") is True:
                rid = b.get("tool_use_id")
                if isinstance(rid, str) and rid:
                    out.add(rid)
    return out


def _sends_of(content: Any, reply_tool: tuple[str, str], failed: set[str]) -> list[str]:
    """The text of each call to the reply tool in one assistant row: exact name, the named input a non-empty
    string, its result not an error. A call with no result yet counts: it went out."""
    name, key = reply_tool
    out: list[str] = []
    for b in content if isinstance(content, list) else []:
        if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == name):
            continue
        tool_input = b.get("input")
        text = tool_input.get(key) if isinstance(tool_input, dict) else None
        if isinstance(text, str) and text.strip() and b.get("id") not in failed:
            out.append(text)
    return out


def closing_window(
    rows: list[dict[str, Any]], reply_tool: tuple[str, str] | None
) -> tuple[str, str, str | None, str | None] | None:
    """(skill, the founder's message after the last closing-message call, the printed hand-over sliced from
    that call's result or None, the reply tool the message went through or None), or None when the current
    prompt made no such call. The message is the text of every send through `reply_tool` after the call when
    there is one (plain text unread: on that host it is unseen), else every top-level assistant text, as
    before. Both restart after a Stop-hook feedback turn."""
    latest = _latest_closing_call(rows)
    if latest is None:
        return None
    start, call_at, call_skill, last_id = latest
    failed = _failed_results(rows[call_at + 1 :]) if reply_tool is not None else set()
    texts: list[str] = []
    sends: list[str] = []
    for row in rows[call_at + 1 :]:
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "user" and row.get("isMeta") and _text_of(content).startswith(STOP_FEEDBACK_PREFIX):
            # A hook already sent the model back once; judge its latest attempt, not the history.
            texts, sends = [], []
            continue
        if row.get("type") != "assistant":
            continue
        if reply_tool is not None:
            sends.extend(_sends_of(content, reply_tool, failed))
        t = _text_of(content)
        if t.strip():
            texts.append(t)
    results = _results_by_id(rows[start:])
    opener = next(o for name, _t, _g, o in SKILLS if name == call_skill)
    printed = printed_from_result(results[last_id], opener) if last_id in results else None
    if sends and reply_tool is not None:
        return call_skill, "\n".join(sends), printed, reply_tool[0]
    return call_skill, "\n".join(texts), printed, None


def _ends_on_tool_result(rows: list[dict[str, Any]]) -> bool:
    """The session's last top-level row is a tool result: a stop cannot follow one, so the final
    assistant text exists and has not reached the file yet."""
    for row in reversed(rows):
        if row.get("isSidechain") or row.get("type") not in ("user", "assistant") or row.get("isMeta"):
            continue
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "assistant":
            return False
        return isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def find_handover(cwd: str, globs: tuple[str, ...] = HANDOVER_GLOBS) -> str | None:
    candidates: list[str] = []
    for pattern in globs:
        candidates.extend(glob.glob(os.path.join(cwd, pattern)))
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _printed(skill: str, cwd: Any, from_transcript: str | None) -> str | None:
    """The skill's printed hand-over: its handover.txt under `cwd`, else the transcript's slice."""
    globs = next(g for name, _t, g, _o in SKILLS if name == skill)
    handover = find_handover(cwd, globs) if isinstance(cwd, str) else None
    if handover is not None:
        with open(handover, encoding="utf-8") as fh:
            return fh.read()
    return from_transcript


def _judgement(
    payload: dict[str, Any], rows: list[dict[str, Any]] | None, reply_tool: tuple[str, str] | None = None
) -> tuple[bool, str, str, str | None] | None:
    """(ok, why, printed hand-over, the reply tool the message went through or None), or None when there is
    nothing to judge: this stop ran no closing script, or no printed hand-over could be found (a stderr line)."""
    final: str | None = None
    skill: str | None = None
    from_transcript: str | None = None
    sent_via: str | None = None
    if rows is not None:
        found = closing_window(rows, reply_tool)
        if found is not None:
            skill, final, from_transcript, sent_via = found
        last = payload.get("last_assistant_message")
        if (
            final is not None
            and sent_via is None
            and isinstance(last, str)
            and last.strip()
            and _ends_on_tool_result(rows)
        ):
            # The Stop event can arrive before the final text reaches the transcript file (measured:
            # 65 ms after it was written, not yet there), and a verbatim hand-over read as missing.
            # Added only when the transcript visibly lacks a final text, so the payload's copy never
            # stands in for text the transcript already holds; never when the message went through the
            # reply tool, where the plain text the payload carries is unseen.
            final = f"{final}\n{last}" if final else last
    else:
        # No transcript to trigger from: the message's own opener is the only key left.
        last = payload.get("last_assistant_message")
        if isinstance(last, str):
            for name, _trigger, _globs, opener in SKILLS:
                if opener in last:
                    skill, final = name, last
                    break
    if final is None or skill is None:
        return None
    cwd = payload.get("cwd")
    printed = _printed(skill, cwd, from_transcript)
    if printed is None:
        _log(
            f"{skill}'s closing message ran but no handover.txt under {cwd}, "
            "and the transcript holds no whole printed hand-over"
        )
        return None
    ok, why = _load_contained()(printed, final)
    return ok, why, printed, sent_via


def _handover_problem(
    payload: dict[str, Any], rows: list[dict[str, Any]] | None, reply_tool: tuple[str, str] | None = None
) -> tuple[str, str, str | None] | None:
    """(why, printed hand-over, the reply tool the message went through or None) when the closing message did
    not carry the printed hand-over, else None."""
    judged = _judgement(payload, rows, reply_tool)
    if judged is None or judged[0]:
        return None
    return judged[1], judged[2], judged[3]


def _last_feedback_asked_for_the_hand_over(rows: list[dict[str, Any]], after: int) -> bool:
    """The latest Stop-hook feedback row after row `after` carries the hand-over block's own lead: the first stop
    sent the model back for the hand-over, not for a delivery or a no-ask end."""
    last: str | None = None
    for row in rows[after + 1 :]:
        if row.get("isSidechain") or row.get("type") != "user" or not row.get("isMeta"):
            continue
        message = row.get("message")
        body = _text_of(message.get("content")) if isinstance(message, dict) else ""
        if body.startswith(STOP_FEEDBACK_PREFIX):
            last = body
    return last is not None and CORRECTION_LEAD in last


def second_stop(payload: dict[str, Any], rows: list[dict[str, Any]] | None, figures: Any) -> None:
    """On `stop_hook_active`: never a second block, but one stderr line saying whether the follow-up carried the
    printed hand-over (the window restarts at the feedback turn). Only after a hand-over block (the feedback row
    carries `CORRECTION_LEAD`): a follow-up to a delivery or no-ask block was never asked to carry it. Silent when
    this stop is not ours, or when the closing step refused (any handover.txt on disk is then an earlier run's)."""
    try:
        latest = _latest_closing_call(rows) if rows is not None else None
        if rows is None or latest is None or refused_closing_call(rows) is not None:
            return
        if not _last_feedback_asked_for_the_hand_over(rows, latest[1]):
            return
        judged = _judgement(payload, rows, _reply_tool_or_none(rows, figures))
        if judged is None:
            return
        _log("second stop: hand-over passed" if judged[0] else f"second stop: hand-over failed: {judged[1]}")
    except Exception as e:  # noqa: BLE001 - a measurement never fails the stop
        _log(f"second stop: {type(e).__name__}: {e}")


NO_ASK_END_MARKER = "[no-ask-end]"
NO_ASK_END_REASON = (
    f"{NO_ASK_END_MARKER} The run is still marked running. If it stopped on a failure, record it with "
    "run_status.py fail and the code that names it; if it is waiting, its question's open records that; "
    "otherwise continue."
)
_STATUS_PATH = re.compile(r'"status_path"\s*:\s*"([^"]+)"')
COMPACTED_SENTENCE = (
    " This conversation was compacted mid-run: Read the skill's SKILL.md from the step after the last one that "
    "ran before your next command."
)


def compacted_since(rows: list[dict[str, Any]], start: int) -> bool:
    """A main-thread compaction since `start` (the runtime's `compact_boundary` row)."""
    return any(
        r.get("type") == "system" and r.get("subtype") == "compact_boundary" and not r.get("isSidechain")
        for r in rows[start:]
    )


def _load_figures() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "two_figures_check.py")
    spec = importlib.util.spec_from_file_location("two_figures_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strings_of(obj: Any) -> Any:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings_of(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings_of(v)


def no_ask_still_running(rows: list[dict[str, Any]], start: int) -> bool:
    """A turn of a run whose request said not to ask that ends with the run still `running`: it neither waits
    on a question nor finished, so a host would see a stall. Read from the status file the run's `start` result
    named in this prompt; where that path cannot be opened (the host loop runs this hook outside the session's
    shell) nothing is asked. Once per prompt: the block's own marker stops a second."""
    found = None
    main_user_rows = [r for r in rows[start:] if r.get("type") == "user" and not r.get("isSidechain")]
    for row in main_user_rows:
        message = row.get("message") or {}
        for piece in _strings_of(message.get("content")):
            if NO_ASK_END_MARKER in piece:
                return False
            m = _STATUS_PATH.search(piece)
            if m:
                found = m.group(1)
    if not found or not os.path.isfile(found):
        return False
    with open(found, encoding="utf-8") as fh:
        status = json.load(fh)
    return isinstance(status, dict) and status.get("status") == "running" and bool(status.get("no_ask"))


def decide(payload: dict[str, Any]) -> dict[str, str] | None:
    """The block to emit, or None to let the stop through. Raises on nothing; callers fail open.

    Two checks, each independent of the other, merged into ONE block because a stop gets one: the
    hand-over (the closing message carries the printed text) and delivery (finished files were
    attached, not only linked -- `_delivery_check.py`). When both fail, the delivery comes first and
    the printed hand-over is the last thing sent, since nothing after the rewrite is checked.

    Only when neither fires: financial-model-review's review page, built and left unsent by a turn that
    ended waiting at its values check (`_delivery_check.missing_review_delivery`). The two cannot both
    apply in one prompt's tail -- a report build after the page ends the page's ask -- and the ask names
    the pending question, never a finished run.
    """
    if payload.get("hook_event_name") != "Stop":
        return None
    transcript = payload.get("transcript_path")
    rows = read_transcript(transcript) if isinstance(transcript, str) and os.path.isfile(transcript) else None
    if payload.get("stop_hook_active"):
        # One rewrite is the budget: no second block, but the follow-up is measured.
        second_stop(payload, rows, None)
        return None
    # The tool the founder reads replies through, named by the host in a founder's own message (never the ledger,
    # whose lines the model types). Looked for only when this prompt ran a closing script: no other stop scans.
    ours = rows is not None and _latest_closing_call(rows) is not None
    reply_tool = _reply_tool_or_none(rows, None) if ours and rows is not None else None
    refused = refused_closing_call(rows) if rows is not None else None
    if refused is not None:
        # Before anything reads a handover.txt: the one on disk is an earlier run's. Once, as every block is.
        return {"decision": "block", "reason": refused_reason(*refused, reply_tool[0] if reply_tool else None)}
    handover = _handover_problem(payload, rows, reply_tool)
    tool: str | None = None
    quiet = False
    if rows is not None:
        try:
            # The request said not to ask: in the founder's own message, or recorded in the run's ledger, which
            # the latest `start` result of this prompt names. That covers a host that passes its request lines as
            # the skill's arguments; the path is the session shell's, so at Cowork local (this hook on the host,
            # the shell in the VM) only the message counts.
            figures = _load_figures()
            start = _current_prompt_start(rows)
            quiet = bool(figures.no_ask_in(rows, start, _is_real_user_prompt)) or bool(
                figures.ledger_no_ask(figures.read_ledger(figures.ledger_path(rows[start:])))
            )
        except Exception as e:  # noqa: BLE001 - fail open
            _log(f"no-ask check: {type(e).__name__}: {e}")
    if quiet and rows is not None:
        # A request that said not to ask: no delivery or review-page ask (the host reads `deliverables`); only a
        # run left `running` is asked to record why.
        if handover is None:
            try:
                start = _current_prompt_start(rows)
                if no_ask_still_running(rows, start):
                    reason = NO_ASK_END_REASON + (COMPACTED_SENTENCE if compacted_since(rows, start) else "")
                    return {"decision": "block", "reason": reason}
            except Exception as e:  # noqa: BLE001 - fail open
                _log(f"no-ask end check: {type(e).__name__}: {e}")
            return None
        rows_for_delivery = None
    else:
        rows_for_delivery = rows
    if rows_for_delivery is not None:
        try:
            found = closing_call(rows_for_delivery)
            printed = _printed(found[0], payload.get("cwd"), found[2]) if found is not None else None
            tool = _load_delivery().missing_delivery(
                rows_for_delivery, _current_prompt_start(rows_for_delivery), printed
            )
        except Exception as e:  # noqa: BLE001 - the delivery check must never cost the hand-over check
            _log(f"delivery check: {type(e).__name__}: {e}")
    if handover is None and tool is None:
        review = None
        if rows is not None and not quiet:
            try:
                review = _load_delivery().missing_review_delivery(rows, _current_prompt_start(rows))
            except Exception as e:  # noqa: BLE001 - fail open, as the report check does
                _log(f"review-page check: {type(e).__name__}: {e}")
        if review is None:
            return None
        review_tool, page = review
        return {
            "decision": "block",
            "reason": (
                f"The review page ({page}) was built so the founder can check the extracted values, but it "
                "was not sent, and the question whether those values look right waits on it. "
                f"Send {page} now with {review_tool}, then ask (or repeat) the question whether those "
                "values look right, in one line. If the page is not ready to show, say so in one line "
                "instead. Add nothing else."
            ),
        }
    attach = (
        f"If the files your message points to are the finished deliverables, attach them now with {tool}; "
        "if they are not finished, say so in one line instead."
    )
    if handover is None:
        reason = (
            # True on both shapes the check fires on: a message that links the files, and a cloud closing
            # message that names each document by its label with no link.
            "Your last message points the founder to the finished files but did not attach them, and a "
            f"link or a name alone does not reach the founder on every host. {attach} Add nothing else."
        )
    else:
        why, printed, _sent_via = handover
        lead = (
            f"Your last message did not deliver the printed hand-over as written ({why}). "
            "That message is already in front of the founder, so send a follow-up"
            f"{_send_clause(reply_tool[0] if reply_tool else None)}: "
        )
        steps = f"first, {attach[0].lower()}{attach[1:]} Then send " if tool is not None else "send "
        reason = (
            f"{lead}{steps}the line below, then the printed hand-over exactly as printed, and nothing with "
            f"a number outside it.\n\n{CORRECTION_LEAD}\n\n{printed.rstrip()}"
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
