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

FAIL OPEN. Any error, any unexpected shape, any other skill's stop: exit 0, no stdout, one stderr
line at most. `stop_hook_active` true: exit 0 -- one rewrite is the budget. The skill does not
depend on this hook (test_skill_orchestration.py forbids that); it is enforcement, not plumbing.
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


def _load_delivery() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_delivery_check.py")
    spec = importlib.util.spec_from_file_location("_delivery_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _current_prompt_start(rows: list[dict[str, Any]]) -> int:
    start = 0
    for i, row in enumerate(rows):
        if _is_real_user_prompt(row):
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


def text_after_closing_call(rows: list[dict[str, Any]]) -> str | None:
    """Every top-level assistant text after the last closing-message call of the current prompt, or
    None when there was none (see `closing_call`)."""
    found = closing_call(rows)
    return found[1] if found is not None else None


def closing_call(rows: list[dict[str, Any]]) -> tuple[str, str, str | None] | None:
    """(skill, every top-level assistant text after the last closing-message call of the current
    prompt, restarting after any Stop-hook feedback turn, the printed hand-over sliced from the
    latest of that skill's closing calls whose result holds one -- else None), or None when the
    current prompt made no such call: this stop is not ours."""
    start = 0
    for i, row in enumerate(rows):
        if _is_real_user_prompt(row):
            start = i
    call_at = None
    call_skill: str | None = None
    calls: list[tuple[str, str]] = []  # (skill, call id) in order
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
                    call_at, call_skill = i, skill
                    if isinstance(b.get("id"), str) and b["id"]:
                        calls.append((skill, b["id"]))
    if call_at is None or call_skill is None:
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
    results = _results_by_id(rows[start:])
    opener = next(o for name, _t, _g, o in SKILLS if name == call_skill)
    printed: str | None = None
    for skill, cid in reversed(calls):
        if skill == call_skill and cid in results:
            printed = printed_from_result(results[cid], opener)
            if printed is not None:
                break
    return call_skill, "\n".join(texts), printed


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


def _handover_problem(payload: dict[str, Any], rows: list[dict[str, Any]] | None) -> tuple[str, str] | None:
    """(why, printed hand-over) when the closing message did not carry the printed hand-over, else None."""
    final: str | None = None
    skill: str | None = None
    from_transcript: str | None = None
    if rows is not None:
        found = closing_call(rows)
        if found is not None:
            skill, final, from_transcript = found
        last = payload.get("last_assistant_message")
        if final is not None and isinstance(last, str) and last.strip() and _ends_on_tool_result(rows):
            # The Stop event can arrive before the final text reaches the transcript file (measured:
            # 65 ms after it was written, not yet there), and a verbatim hand-over read as missing.
            # Added only when the transcript visibly lacks a final text, so the payload's copy never
            # stands in for text the transcript already holds.
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
    return None if ok else (why, printed)


NO_ASK_END_MARKER = "[no-ask-end]"
NO_ASK_END_REASON = (
    f"{NO_ASK_END_MARKER} The run is still marked running. If it stopped on a failure, record it with "
    "run_status.py fail and the code that names it; if it is waiting, its question's open records that; "
    "otherwise continue."
)
_STATUS_PATH = re.compile(r'"status_path"\s*:\s*"([^"]+)"')


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
    if payload.get("hook_event_name") != "Stop" or payload.get("stop_hook_active"):
        return None
    transcript = payload.get("transcript_path")
    rows = read_transcript(transcript) if isinstance(transcript, str) and os.path.isfile(transcript) else None
    handover = _handover_problem(payload, rows)
    tool: str | None = None
    quiet = False
    if rows is not None:
        try:
            quiet = bool(_load_figures().no_ask_in(rows, _current_prompt_start(rows), _is_real_user_prompt))
        except Exception as e:  # noqa: BLE001 - fail open
            _log(f"no-ask check: {type(e).__name__}: {e}")
    if quiet and rows is not None:
        # A request that said not to ask: no delivery or review-page ask (the host reads `deliverables`); only a
        # run left `running` is asked to record why.
        if handover is None:
            try:
                if no_ask_still_running(rows, _current_prompt_start(rows)):
                    return {"decision": "block", "reason": NO_ASK_END_REASON}
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
        why, printed = handover
        lead = (
            f"Your last message did not deliver the printed hand-over as written ({why}). "
            "That message is already in front of the founder, so send a follow-up: "
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
