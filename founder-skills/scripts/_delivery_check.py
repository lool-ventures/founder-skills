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
4. No delivery call after the build succeeded. A delivery before it (an inputs viewer) does not count.
5. The host OFFERED a delivery tool: a name containing `present_files`, or `SendUserFile`, in the
   tool list the transcript records (a `prompt_snapshot` attachment's `tools`, or
   `deferred_tools_delta.addedNames`). A failed call to a guessed name is not evidence the tool
   exists. No such record, or no delivery tool in it: no block -- a host without one delivers some
   other way. The cloud lane's transcript shape is unmeasured, so there this may never fire.
6. Not the plain Claude Code CLI (`entrypoint == "cli"`), where a path on disk is a delivery.
"""

from __future__ import annotations

import importlib.util
import os
import re
from typing import Any

SHELL_TOOLS = ("Bash", "mcp__workspace__bash")
_BUILD = re.compile(r"(?<![\w-])(?:compose_report|closing_message|cp_closing_message|fmr_closing_message)\.py\b")
_CLOSER = re.compile(r"(?<![\w-])(?:closing_message|cp_closing_message|fmr_closing_message)\.py\b")
_DELIVERABLE = re.compile(
    r"computer://\S+|(?:^|[\s(`\"'])/[^\s)`\"']+\.(?:md|html|pdf|xlsx)\b|\]\([^)]+\.(?:md|html|pdf|xlsx)\)",
    re.IGNORECASE | re.MULTILINE,
)
STOP_FEEDBACK_PREFIX = "Stop hook feedback:"


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
    closer = False
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
                closer = bool(_CLOSER.search(command))
    if build_at is None:
        return None
    texts: list[str] = []
    for row in rows[build_at + 1 :]:
        if row.get("isSidechain"):
            continue
        if row.get("type") == "user" and row.get("isMeta") and _text(row).startswith(STOP_FEEDBACK_PREFIX):
            texts = []  # judge the latest attempt's words; deliveries still accumulate
            continue
        if row.get("type") != "assistant":
            continue
        for b in _content(row):
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            cid = b.get("id")
            outcome = results.get(cid) if isinstance(cid, str) else None
            if b.get("name") in SHELL_TOOLS and outcome is True:
                return None
            if is_delivery_tool(b.get("name")) and outcome is False:
                return None
        t = _text(row)
        if t.strip():
            texts.append(t)
    final = "\n".join(texts)
    if not _DELIVERABLE.search(final) and not (closer and printed and _carries(printed, final)):
        return None
    seen, tool = offered_tool(rows)
    if not seen or tool is None:
        return None
    return tool
