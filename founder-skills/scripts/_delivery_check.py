"""Did a finished founder-skills run hand its files to the founder, or only link them?

Loaded by path from stop_handover_check.py (plugin-root `scripts/` is not a package), which merges
what this returns with the hand-over check into one Stop-hook block.

WHY. Live runs wrote and copied their deliverables, then ended with `computer://` links and never
called the host's delivery tool. On Cowork's cloud lane a link is dead text and the file card is the
only delivery, so the founder there gets nothing openable. SKILL.md says "Present each file to the
user" and names no tool on purpose (each lane serves a different one); this is the enforcement.

WHEN IT ASKS -- all of these, read from the session transcript:
1. The current prompt ran a founder-skills report build (a compose or closing script) through a
   SHELL tool, and it succeeded. The script name inside an Agent or TaskCreate input is not a run.
2. No shell call after it failed. A run that hit an error after building the report and stopped
   is not asked to deliver what it chose to withhold.
3. The final message points at a deliverable (a `computer://` link, or an absolute path or link
   target ending .md/.html/.pdf/.xlsx). A model that withheld delivery does not link the files.
   For a closing script's build (`closing_message` / `cp_closing_message` / `fmr_closing_message`),
   carrying the printed hand-over whole also counts (`_handover_check.carries`): on a cloud session
   those scripts name each document by its label alone, so the message links nothing. RESIDUAL: a
   cloud closing message rewritten without the hand-over and without a path is not asked to attach.
4. No delivery call after the build succeeded. When the prompt ran a compose script, the build is the
   last compose, so a delivery between it and a closing script that follows counts. A delivery before
   the build does not count: financial-model-review's review page, sent at its values check, is not
   the report's delivery (and the report's is not the page's -- see REVIEW PAGE below). Each is
   judged on deliveries after its own build.
5. The host OFFERED a delivery tool: a name containing `present_files`, or `SendUserFile`, in the
   tool list the transcript records (a `prompt_snapshot` attachment's `tools`, or
   `deferred_tools_delta.addedNames`). A failed call to a guessed name is not evidence the tool
   exists. No such record, or no delivery tool in it: no block -- a host without one delivers some
   other way. The cloud lane's transcript shape is unmeasured, so there this may never fire.
6. Not the plain Claude Code CLI (`entrypoint == "cli"`), where a path on disk is a delivery.

REVIEW PAGE (`missing_review_delivery`), a separate ask with its own conditions -- not a branch of the
report's, whose message-shape condition (3) has no part in it: financial-model-review's values check
built its static review page (`review_inputs.py … --static`) in the current prompt, no successful
delivery naming the page followed, no report build followed (past the gate the page no longer
matters), no question was put through AskUserQuestion after it (the PreToolUse check,
review_page_check.py, owns that path; a question it held does not count as asked), and conditions 5
and 6 hold. That is a turn that ended WAITING at the gate -- the question asked in chat, or on a host
with no question tool -- with the page unsent. The ask names the pending question and never calls the
run finished. A shell call between the build and the end (a gate record) changes nothing. A build
written across lines (shell line continuations) is read as one line, and a connected-folder write carrying
the page counts as sending it.
"""

from __future__ import annotations

import importlib.util
import os
import re
from typing import Any

SHELL_TOOLS = ("Bash", "mcp__workspace__bash")
_BUILD = re.compile(r"(?<![\w-])(?:compose_report|closing_message|cp_closing_message|fmr_closing_message)\.py\b")
_CLOSER = re.compile(r"(?<![\w-])(?:closing_message|cp_closing_message|fmr_closing_message)\.py\b")
_COMPOSE = re.compile(r"(?<![\w-])compose_report\.py\b")
_DELIVERABLE = re.compile(
    r"computer://\S+|(?:^|[\s(`\"'])/[^\s)`\"']+\.(?:md|html|pdf|xlsx)\b|\]\([^)]+\.(?:md|html|pdf|xlsx)\)",
    re.IGNORECASE | re.MULTILINE,
)
STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
# financial-model-review's values-check page, built for the founder to look at before the review goes
# on. Only that skill ships `review_inputs.py`; its server mode (no --static) serves a local address
# and writes no page to send.
_REVIEW_BUILD = re.compile(r"(?<![\w-])review_inputs\.py\b(?P<args>[^\n;&|]*)")
_STATIC_ARG = re.compile(r"(?:^|\s)--static(?:=|\s+|$)(?P<path>\"[^\"]*\"|'[^']*'|[^\s\"']*)")
REVIEW_PAGE = "review.html"
# A shell line continuation: many runs write the build across lines. `_BUILD` and `_CLOSER` search the
# whole command and need no joining; the page's arguments are read up to the end of the line.
_CONTINUATION = re.compile(r"\\\r?\n")
# A connected-folder write (served on cloud as `mcp__remote-devices__device_commit_files`) that carries
# the page puts it in front of the founder too. It counts for the page only: it is not a tool the host
# offers for delivery, so it never stands in for `offered_tool`, and the report check is unchanged.
_FOLDER_WRITE = "device_commit_files"


def is_delivery_tool(name: Any) -> bool:
    return isinstance(name, str) and ("present_files" in name or name == "SendUserFile")


def _content(row: dict[str, Any]) -> list[Any]:
    c = (row.get("message") or {}).get("content")
    return c if isinstance(c, list) else []


def _text(row: dict[str, Any]) -> str:
    c = (row.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in _content(row) if isinstance(b, dict) and b.get("type") == "text")


def offered_tool(rows: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """(the transcript records the tool list at all, the delivery tool it offered or None)."""
    seen = False
    found: str | None = None
    for row in rows:
        att = row.get("attachment")
        if not isinstance(att, dict):
            continue
        names: list[Any] = []
        if att.get("type") == "prompt_snapshot" and isinstance(att.get("tools"), list):
            names = [t.get("name") for t in att["tools"] if isinstance(t, dict)]
        elif att.get("type") == "deferred_tools_delta" and isinstance(att.get("addedNames"), list):
            names = list(att["addedNames"])
        else:
            continue
        seen = True
        for n in names:
            if is_delivery_tool(n) and found is None:
                found = n
    return seen, found


def _carries(printed: str, final: str) -> bool:
    """`_handover_check.carries`, loaded by path: one owner of the containment rule."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_handover_check.py")
    spec = importlib.util.spec_from_file_location("_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return bool(mod.carries(printed, final))


def missing_delivery(rows: list[dict[str, Any]], start: int, printed: str | None = None) -> str | None:
    """The delivery tool to ask for, or None when nothing should be asked (see the module docstring).
    `printed` is the closing script's printed hand-over, when the caller found one."""
    if any(r.get("entrypoint") == "cli" for r in rows):
        return None
    results: dict[str, bool] = {}
    for row in rows[start:]:
        if row.get("isSidechain"):
            continue
        for b in _content(row):
            if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                results[b["tool_use_id"]] = bool(b.get("is_error"))
    build_at: int | None = None
    compose_at: int | None = None
    closer_at: int | None = None
    for i in range(start, len(rows)):
        row = rows[i]
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        for b in _content(row):
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in SHELL_TOOLS):
                continue
            cid = b.get("id")
            command = str((b.get("input") or {}).get("command", ""))
            if isinstance(cid, str) and cid and _BUILD.search(command) and results.get(cid) is False:
                build_at = i
                if _CLOSER.search(command):
                    closer_at = i
                if _COMPOSE.search(command):
                    compose_at = i
    if build_at is None:
        return None
    # The report is built by its compose script; a closing script only prints the hand-over, and the
    # skills deliver first and run the closer last, so its printed text is the final message. Three
    # windows follow from that. Deliveries count from the prompt's last compose (from the prompt's
    # start when it ran no compose: a resumed run re-sends files it built earlier). A failed shell call
    # stops the ask only after the closer that follows that compose: the coaching chain between them
    # retries by design. The final message is read after the last build.
    text_from = build_at
    closer = closer_at is not None and (compose_at is None or closer_at > compose_at)
    if compose_at is not None:
        deliver_from = compose_at
        fail_from = closer_at if closer else compose_at
    else:
        deliver_from = start - 1
        fail_from = build_at
    texts: list[str] = []
    for i in range(min(deliver_from, fail_from, text_from) + 1, len(rows)):
        row = rows[i]
        if row.get("isSidechain"):
            continue
        if (
            i > text_from
            and row.get("type") == "user"
            and row.get("isMeta")
            and _text(row).startswith(STOP_FEEDBACK_PREFIX)
        ):
            texts = []  # judge the latest attempt's words; deliveries still accumulate
            continue
        if row.get("type") != "assistant":
            continue
        for b in _content(row):
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            cid = b.get("id")
            outcome = results.get(cid) if isinstance(cid, str) else None
            if i > fail_from and b.get("name") in SHELL_TOOLS and outcome is True:
                return None
            if i > deliver_from and is_delivery_tool(b.get("name")) and outcome is False:
                return None
        t = _text(row) if i > text_from else ""
        if t.strip():
            texts.append(t)
    final = "\n".join(texts)
    if not _DELIVERABLE.search(final) and not (closer and printed and _carries(printed, final)):
        return None
    seen, tool = offered_tool(rows)
    if not seen or tool is None:
        return None
    return tool


def _strings(obj: Any) -> Any:
    """Every string inside a decoded JSON value."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def static_review_page(command: str) -> str | None:
    """The file name of the page a `review_inputs.py … --static <page>` command writes, or None when the
    command is not a static review build. A name the shell has yet to expand falls back to the page
    SKILL.md names."""
    m = _REVIEW_BUILD.search(_CONTINUATION.sub(" ", command))
    if m is None:
        return None
    arg = _STATIC_ARG.search(m.group("args"))
    if arg is None:
        return None
    name = arg.group("path").strip("\"'").rstrip("/").rsplit("/", 1)[-1]
    return name if name and "$" not in name and "." in name else REVIEW_PAGE


def _sends_page(name: Any) -> bool:
    return is_delivery_tool(name) or (
        isinstance(name, str) and (name == _FOLDER_WRITE or name.endswith("__" + _FOLDER_WRITE))
    )


def tool_outcomes(rows: list[dict[str, Any]], start: int) -> dict[str, bool]:
    """Each top-level tool result since `start`, keyed by its id: True when it is an error."""
    results: dict[str, bool] = {}
    for row in rows[start:]:
        if row.get("isSidechain"):
            continue
        for b in _content(row):
            if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                results[b["tool_use_id"]] = bool(b.get("is_error"))
    return results


def unsent_review_page(rows: list[dict[str, Any]], start: int) -> tuple[int, str] | None:
    """(row index, page name) of the current prompt's latest successful static review build, when no
    successful delivery naming that page and no report build has followed it; else None.

    A delivery counts for the page only when its input names the page's file: a report's delivery is
    not the page's, and the page's is not the report's (`missing_delivery` judges deliveries only after
    its own build). A report build after the page means the run is past the values check, where the page
    no longer matters. Any other shell call (a gate record, a validation) is neither."""
    results = tool_outcomes(rows, start)
    found: tuple[int, str] | None = None
    for i in range(start, len(rows)):
        row = rows[i]
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        for b in _content(row):
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            cid = b.get("id")
            outcome = results.get(cid) if isinstance(cid, str) and cid else None
            name = b.get("name")
            if name in SHELL_TOOLS:
                command = str((b.get("input") or {}).get("command", ""))
                page = static_review_page(command)
                if page is not None and outcome is False:
                    found = (i, page)
                elif found is not None and _BUILD.search(command):
                    found = None
            elif found is not None and _sends_page(name) and outcome is False:
                page = found[1]
                if any(s.strip() == page or s.strip().endswith("/" + page) for s in _strings(b.get("input"))):
                    found = None
    return found


def missing_review_delivery(rows: list[dict[str, Any]], start: int) -> tuple[str, str] | None:
    """(delivery tool, page name) when a turn ended waiting at the values check with its review page
    unsent, else None (see REVIEW PAGE in the module docstring)."""
    if any(r.get("entrypoint") == "cli" for r in rows):
        return None
    pending = unsent_review_page(rows, start)
    if pending is None:
        return None
    at, page = pending
    results = tool_outcomes(rows, start)
    for row in rows[at + 1 :]:
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        for b in _content(row):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
                cid = b.get("id")
                if not (isinstance(cid, str) and results.get(cid) is True):
                    return None
    seen, tool = offered_tool(rows)
    if not seen or tool is None:
        return None
    return tool, page
