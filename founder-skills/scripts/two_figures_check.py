#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""PreToolUse hook: hold market-sizing's sizing dispatch once when the founder was never asked which
of two stated figures to use.

WHY A HOOK. When the founder's materials state more than one figure for one input (a rate typed in
chat, two more on a slide), SKILL.md says to ask which one the sizing uses before sizing. On two live
runs the figures were recorded as alternatives, the question was never asked, and the sizing went
ahead. The report now says "you were not asked", which is honest, but the founder still never chose.

WHY THE TRANSCRIPT, AND NOT THE ARTIFACTS. `founder_stated_choice` and `gate_defaults` are written by
the model; a check they satisfy is satisfied by writing them, which is the defect this repo keeps
finding in checks whose remedy can change their own comparand. The transcript is written by the
runtime: an `AskUserQuestion` whose question or options name every figure is the evidence, read
there.

THE ONE ARTIFACT READ: THE RUN'S LEDGER, FOR WHAT THE REQUEST CARRIED. A host that passes its request
lines as the skill's arguments leaves them in the skill's expanded text, which no check here counts.
So the run's ledger is read too (shared with `asked_gate_check.py`, `no_ask_check.py` and the Stop
hook): a ledger with `no_ask` set is not held, and an input the ledger shows answered from the request
(`answered_by_request`: the stored line's `applied_at` equal to the answer's `answered_at`, as
`_gates.answered_by_request` tests it) is left out of the hold. An answer recorded through the recorder
never counts; that is the case this hook exists for. What the ledger shows is that the run's ledger
records that the request carried a line, not that a person sent it. Exactly what that trusts:
(1) a line reaches the ledger through the run status script's `start`, at a fresh start or a resume
of a `waiting` run; a model that opens the held gate (the run then waits), resumes under the same run id
with an answer line or `FS_HOST_NO_ASK`, and opens again holds an applied pre-answer (or a no-ask
ledger) with nothing asked. That is the host's own resume flow, so it is not refused; points (3) to (5)
are what make it acceptable (a test pins it as a known residual); (2) a shell can hand-edit
`gates.json` and nothing detects it, the same residual as a hand-written gate record; (3) a forge buys
one skipped hold, and the hold already lets the second dispatch through; (4) a forged `no_ask` makes the
recorder refuse every answer the model types, so it costs the model more than it saves; (5) a forged
pre-answer is disclosed, since the status and the reports say the request answered it rather than the
founder. The asymmetry is new and named: `inputs.json` is model-writable too, but it can only ADD a
hold; the ledger is the first model-writable input that REMOVES one. Under a host that passes the lines
as arguments nothing in the transcript is runtime-written either (the Skill call's arguments and its
expanded text are the model's), so any fix there trusts a model-transcribed line, and the ledger is the
one the recorder and the report are already bound to. Which ledger: the one the dispatch's OUTPUT_PATH
names (`run_ref.json` beside `handoff/<run id>/`, its run id and the ledger's both equal to the
OUTPUT_PATH's), read live, so a stale OUTPUT_PATH reads that older run's ledger. It reaches the ledger
wherever the hook can open OUTPUT_PATH; at the Cowork host loop OUTPUT_PATH is the host path of the
outputs folder, as for `inputs.json` below, so the ledger should be reached there too (code-read from
the same path; not yet observed on a Cowork-local run). Only a regular file is opened: every path here
is model-written, and a FIFO or a device would block the hook.

THE DESKTOP QUESTION FORM. Desktop steers a first question to a form instead: a `show_widget` call
whose HTML is a `<form class="elicit">`, answered by the founder's next message on one line, the
form's header, a space, an em dash, a space, then the choices (or a fixed Skip line). Two things
follow. A form counts only once ANSWERED: the widget's tool result says "rendered and shown" at once,
so a model could show the form and dispatch in the same turn before anyone chose. And the answer,
being a plain user message, would otherwise start a new request and drop the form out of the
window; here, and only here, the answer to the latest form shown in the window is not a boundary
(the Stop, dispatch-prompt and review-page checks keep their windows). The figures are read from the
form's rendered text only, the option buttons and question labels; never attributes, SVG path data,
comments, `<template>`/`<style>`/`<script>`, or hidden elements. A form with a script or an inline
event handler is not an offer. The risk accepted: the answer is recognised by its text, so a founder
who types the header followed by an em dash extends the window over an unanswered form.

WHY THE DISPATCH. A hook on the question tool cannot make a question happen, and on both runs none
did. The thing that must not happen before the question is the sizing, so the hook sits on the
TOP_DOWN / BOTTOM_UP dispatch. Every other dispatch, and every other session, returns at the prefix
check before any disk or transcript read.

A NUDGE WITH ONE RETRY, NOT PROOF. The deny's reason is the question itself, built from the recorded
figures, plus the way out for a founder who asked not to be asked. The second dispatch after a hold
goes through: the hook recognises its own marker in the transcript, so it never has to trust a
model-written "the founder said no questions". What that costs is one refused dispatch (nothing was
spawned). What it cannot see: a model that records no alternatives at all.

ONE MECHANISM NO TEST REACHES. The retry depends on the denial's tool result being in the transcript
file when the next PreToolUse runs. The Stop hook reads the transcript mid-session and works, so this
is expected, not measured; the synthetic critique runs are where it is measured.

WHERE THE INPUTS ARE. The dispatch names its own directory: OUTPUT_PATH is
`<analysis dir>/handoff/<run id>/<file>`, so `inputs.json` beside `handoff/` is this run's file. The
hook's cwd cannot be relied on for this: on current local Cowork it is `/private/var/empty`, and a glob
under it found nothing, so the hold silently never ran. The cwd glob remains the fallback for a prompt
with no usable OUTPUT_PATH. Only the path comes from the model-written prompt; the figures come from
the file the sizing reads.

FAIL OPEN. Any error, any unexpected shape, no transcript, no inputs: exit 0, no stdout, one stderr
line at most. A sizing dispatch whose inputs cannot be found says so on stderr, so a hold that could
not run is visible rather than indistinguishable from one that had nothing to hold. SKILL.md does
not depend on this hook (test_skill_orchestration.py).
"""

from __future__ import annotations

import glob
import html.parser
import importlib.util
import json
import os
import re
import sys
from typing import Any

MARKER = "[two-figures-check]"
SIZING_CONTEXTS = ("CONTEXT: TOP_DOWN_METHODOLOGY", "CONTEXT: BOTTOM_UP_METHODOLOGY")
SIZING_NAMES = ("TOP_DOWN_METHODOLOGY", "BOTTOM_UP_METHODOLOGY")
GATE = "ms_two_figures"
DISPATCH_TOOLS = ("Agent", "Task")
INPUTS_GLOBS = ("artifacts/market-sizing-*/inputs.json", "mnt/outputs/artifacts/market-sizing-*/inputs.json")
# A figure is matched whole: "1,261.00" is 1261, never 261.
_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?!\d|,\d)")
_FIELD_NAMES = {"arpu": "ARPU"}
# The whole line, trimmed, as dispatch_prompt_check reads it: local-lane paths contain spaces.
_OUTPUT_RE = re.compile(r"^[ \t]*OUTPUT_PATH:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
# Desktop's question form, as its elicitation module describes it to the model.
FORM_TOOL = "mcp__visualize__show_widget"
SKIP_LINE = "(Skipped the form \u2014 proceed with defaults or ask me in plain text)"
_ANSWER_DASH = " \u2014 "
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Elements whose text the founder does not see as an option: drawn, inert, collapsed, or read only by
# a screen reader. A model that puts a figure there has not offered it.
_UNSEEN = {"svg", "template", "style", "script", "details", "textarea", "noscript"}


def _log(msg: str) -> None:
    print(f"two_figures_check: {msg}", file=sys.stderr)


def _transcript_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stop_handover_check.py")
    spec = importlib.util.spec_from_file_location("stop_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dispatch_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch_type_check.py")
    spec = importlib.util.spec_from_file_location("dispatch_type_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sizing_context(prompt: str) -> str | None:
    """The sizing context this prompt is a dispatch of, read as every dispatch check reads a first line
    (`dispatch_type_check.context_of`: invisible characters removed, a suffix allowed), or None. The
    name is also the key of this check's marker, so the hold and its retry agree on it."""
    if "METHODOLOGY" not in prompt:
        return None
    context = _dispatch_tools().context_of(prompt)
    return context if context in SIZING_NAMES else None


def _numbers(text: str) -> set[float]:
    return {
        float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else "")) for m in _NUMBER_RE.finditer(text)
    }


def _figure(value: float) -> str:
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


def run_dir_from_output_path(prompt: str, cwd: str | None) -> tuple[str, str | None] | None:
    """(this run's analysis dir, the segment after `handoff` or None), from the dispatch's own
    OUTPUT_PATH. It walks up to the last `handoff` segment rather than a fixed depth, because a later
    round writes one level further down. A relative path is resolved against cwd."""
    m = _OUTPUT_RE.search(prompt)
    if m is None:
        return None
    path = m.group(1)
    if not os.path.isabs(path):
        if cwd is None:
            return None
        path = os.path.join(cwd, path)
    dirs = os.path.normpath(path).split(os.sep)[:-1]
    if "handoff" not in dirs:
        return None
    at = len(dirs) - 1 - dirs[::-1].index("handoff")
    run_id = dirs[at + 1] if at + 1 < len(dirs) else None
    return os.sep.join(dirs[:at]) or os.sep, run_id


def inputs_from_output_path(prompt: str, cwd: str | None) -> str | None:
    """This run's inputs.json, beside the `handoff` dir its OUTPUT_PATH names."""
    found = run_dir_from_output_path(prompt, cwd)
    if found is None:
        return None
    candidate = os.path.join(found[0], "inputs.json")
    return candidate if os.path.isfile(candidate) else None


def find_inputs(cwd: str) -> str | None:
    found = [p for g in INPUTS_GLOBS for p in glob.glob(os.path.join(cwd, g)) if os.path.isfile(p)]
    return max(found, key=os.path.getmtime) if found else None


def _squash(text: str) -> str:
    return " ".join(text.split())


class _FormText(html.parser.HTMLParser):
    """The text a founder sees in an elicit form: the header's span, and each option button's and
    question label's text. Character references are unescaped by the parser (convert_charrefs).

    `options` is every visible chunk of either, in order, as the figures are read from it. `pills` and
    `questions` hold the same chunks grouped by the element they sit in (the innermost pill or question
    label), for a check that compares whole option labels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str, list[str] | None]] = []  # (tag, role, the group its text joins)
        self.scripted = False
        self.forms = 0
        self.header: list[str] = []
        self.options: list[str] = []
        self.pills: list[list[str]] = []
        self.questions: list[list[str]] = []

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], push: bool) -> None:
        names = {k for k, _ in attrs}
        values = {k: v or "" for k, v in attrs}
        if tag == "script" or any(k.startswith("on") for k in names):
            self.scripted = True
        classes = set(values.get("class", "").split())
        roles = {r for _, r, _g in self.stack}
        style = "".join(values.get("style", "").lower().split())
        if (
            tag in _UNSEEN
            or "hidden" in names
            or "sr-only" in classes
            or values.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            role = "unseen"
        elif tag == "form" and "elicit" in classes:
            role = "form"
            self.forms += 1
        elif "elicit-header" in classes:
            role = "header"
        elif tag == "span" and "header" in roles:
            role = "title"
        elif "elicit-pill" in classes:
            role = "pill"
        elif "elicit-question" in classes:
            role = "question"
        else:
            role = ""
        if push and tag not in _VOID:
            group: list[str] | None = None
            if role in ("pill", "question"):
                group = []
                (self.pills if role == "pill" else self.questions).append(group)
            self.stack.append((tag, role, group))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, push=True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # HTML ignores a self-closing slash on a non-void element: `<div hidden/>` stays open in a
        # browser, so it stays open here.
        self._open(tag, attrs, push=True)

    def handle_endtag(self, tag: str) -> None:
        if any(t == tag for t, _r, _g in self.stack):
            while self.stack and self.stack.pop()[0] != tag:
                pass

    def handle_data(self, data: str) -> None:
        roles = {r for _, r, _g in self.stack}
        if "unseen" in roles or "form" not in roles:
            return
        if "title" in roles:
            self.header.append(data)
        elif "pill" in roles or "question" in roles:
            self.options.append(data)
            group = next(g for _t, _r, g in reversed(self.stack) if g is not None)
            group.append(data)


def _parsed_form(block: Any) -> tuple[str, _FormText] | None:
    """(header, parsed text) for a `show_widget` call that shows an elicit form, else None. A scripted
    form, an empty header, or anything that does not parse is not an offer."""
    if not isinstance(block, dict) or block.get("type") != "tool_use":
        return None
    name = block.get("name")
    if not isinstance(name, str) or not (name == FORM_TOOL or name.endswith("__show_widget")):
        return None
    code = (block.get("input") or {}).get("widget_code") if isinstance(block.get("input"), dict) else None
    if not isinstance(code, str) or "<script" in code.lower():
        return None
    try:
        parser = _FormText()
        parser.feed(code)
        parser.close()
    except Exception:  # noqa: BLE001 - a form that does not parse offered nothing
        return None
    header = _squash(" ".join(parser.header))
    if parser.scripted or not parser.forms or not header:
        return None
    return header, parser


def elicit_form(block: Any) -> tuple[str, set[float]] | None:
    """(header, figures offered) for a `show_widget` call that shows an elicit form, else None."""
    parsed = _parsed_form(block)
    if parsed is None:
        return None
    header, parser = parsed
    return header, _numbers(" ".join(parser.options))


def elicit_form_parts(block: Any) -> tuple[str, list[tuple[str, ...]], list[str]] | None:
    """(header, each option button's visible text chunks, each question label's text) for an elicit
    form, else None: the same form, read as labels rather than figures."""
    parsed = _parsed_form(block)
    if parsed is None:
        return None
    header, parser = parsed
    return header, [tuple(p) for p in parser.pills], [_squash(" ".join(q)) for q in parser.questions]


def _forms_in(row: dict[str, Any]) -> list[tuple[str, set[float]]]:
    if row.get("type") != "assistant" or row.get("isSidechain"):
        return []
    content = (row.get("message") or {}).get("content")
    found = [elicit_form(b) for b in (content if isinstance(content, list) else [])]
    return [f for f in found if f is not None]


_UPLOADS_RE = re.compile(r"\A\s*<uploaded_files>.*?</uploaded_files>\s*", re.DOTALL)


def _first_line(row: dict[str, Any]) -> str:
    """The message's first line, after any leading `<uploaded_files>` block the host adds when the
    founder attaches a file."""
    message = row.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = next((b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
    if not isinstance(content, str):
        return ""
    return _squash(_UPLOADS_RE.sub("", content, count=1).split("\n", 1)[0])


def _answers(row: dict[str, Any], header: str) -> bool:
    """The founder's reply to the form: its header, a spaced em dash, the choices; or the Skip line."""
    line = _first_line(row)
    return line.startswith(header + _ANSWER_DASH) or line == SKIP_LINE


def _scan(rows: list[dict[str, Any]], is_prompt: Any) -> tuple[int, dict[int, set[float]]]:
    """Where the current request starts, and the figures of each form answered after a prompt: {row
    of the answer: figures}. A real prompt that answers a form shown since the previous prompt is
    that form's answer, not a new request; when several forms share the header, the latest one is
    the one answered. Any prompt clears the forms shown before it, so an old form cannot be answered
    from a later request."""
    start = 0
    pending: list[tuple[str, set[float]]] = []
    answered: dict[int, set[float]] = {}
    for i, row in enumerate(rows):
        if is_prompt(row):
            match = next((f for f in reversed(pending) if _answers(row, f[0])), None)
            if match is not None:
                answered[i] = match[1]
            else:
                start = i
            pending = []
            continue
        pending.extend(_forms_in(row))
    return start, answered


def _window_start(rows: list[dict[str, Any]], is_prompt: Any) -> int:
    return _scan(rows, is_prompt)[0]


def unasked(
    inputs: dict[str, Any], rows: list[dict[str, Any]], is_prompt: Any
) -> list[tuple[str, list[tuple[float, str, bool]]]]:
    """Each input whose figures were not all offered in one question since the current request:
    (field, [(value, how to describe it, offered in some question), ...]), the recorded figure first."""
    stated_raw, periods_raw = inputs.get("founder_stated_inputs"), inputs.get("founder_stated_inputs_period")
    stated: dict[str, Any] = stated_raw if isinstance(stated_raw, dict) else {}
    periods: dict[str, Any] = periods_raw if isinstance(periods_raw, dict) else {}
    alternatives = inputs.get("founder_stated_alternatives")
    if not isinstance(alternatives, dict):
        return []
    start, answered = _scan(rows, is_prompt)
    offered: list[set[float]] = [nums for at, nums in answered.items() if at > start]
    for row in rows[start:]:
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
                offered.append(_numbers(json.dumps(b.get("input"))))
    out = []
    for field, alts in alternatives.items():
        figures: list[tuple[float, str]] = []
        typed = stated.get(field)
        if isinstance(typed, (int, float)) and not isinstance(typed, bool):
            per = f" per {periods[field]}" if isinstance(periods.get(field), str) else ""
            figures.append((float(typed), f"{_figure(typed)}{per} (the figure recorded now)"))
        for alt in alts if isinstance(alts, list) else []:
            if (
                isinstance(alt, dict)
                and isinstance(alt.get("value"), (int, float))
                and not isinstance(alt.get("value"), bool)
            ):
                per = f" per {alt['period']}" if isinstance(alt.get("period"), str) else ""
                label = alt.get("label") if isinstance(alt.get("label"), str) and alt["label"].strip() else ""
                figures.append(
                    (float(alt["value"]), f"{_figure(alt['value'])}{per}" + (f" ({label.strip()})" if label else ""))
                )
        if len(figures) < 2:
            continue
        needed = {v for v, _ in figures}
        if not any(needed <= nums for nums in offered):
            anywhere = set().union(*offered) if offered else set()
            out.append((field, [(v, desc, v in anywhere) for v, desc in figures]))
    return out


_HOST_KINDS = ("ANSWER", "VALUE")
_NOTIFICATION = "<task-notification>"


def from_founder(row: dict[str, Any]) -> bool:
    """Whether a user row is the founder's own text rather than one the runtime delivers in a user row: a
    background agent's result (`origin.kind` other than human; on older CLIs, text opening with the
    notification tag) is that agent's words, which the model can steer."""
    origin = row.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return False
    body = (row.get("message") or {}).get("content")
    if isinstance(body, list):
        body = next((b.get("text") for b in body if isinstance(b, dict) and b.get("type") == "text"), "")
    return not (isinstance(body, str) and body.lstrip().startswith(_NOTIFICATION))


def founders_message(row: dict[str, Any], is_prompt: Any) -> bool:
    """A real prompt the founder wrote: not a compaction summary, not a delivered notification."""
    return not row.get("isCompactSummary") and bool(is_prompt(row)) and from_founder(row)


_COMMAND_ARGS = re.compile(r"</?command-args>")
NO_ASK_LINE = re.compile(r"(?m)^[ \t]*FS_HOST_NO_ASK[ \t]*$")


def _founder_texts(row: dict[str, Any]) -> list[str]:
    """A founder message's text blocks, with a slash command's `<command-args>` wrapper removed so a request
    line first or last in the arguments still stands on a line of its own."""
    content = (row.get("message") or {}).get("content")
    texts = [content] if isinstance(content, str) else []
    if isinstance(content, list):
        texts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
    return [_COMMAND_ARGS.sub("\n", t.replace("\r", "")) for t in texts]


def no_ask_in(rows: list[dict[str, Any]], start: int, is_prompt: Any = None) -> bool:
    """Whether a founder's own message since `start` carries an `FS_HOST_NO_ASK` line: the request said not to
    ask. Same exclusions as `host_line_in` (never a tool's text, a skill's expanded text, a sub-agent or a
    compaction summary)."""
    if is_prompt is None:
        is_prompt = _transcript_tools()._is_real_user_prompt
    for row in rows[start:]:
        if founders_message(row, is_prompt) and any(NO_ASK_LINE.search(t) for t in _founder_texts(row)):
            return True
    return False


def host_line_in(
    rows: list[dict[str, Any]], start: int, gate: str, kinds: tuple[str, ...], is_prompt: Any = None
) -> bool:
    """Whether a founder's own message since `start` carries an `FS_HOST_<kind> <gate>=` line. Only a
    real prompt's text counts: never a tool call's input or result, a skill's expanded text (isMeta), a
    sub-agent's rows or its delivered result, or a compaction summary, which restates earlier messages in
    the model's words."""
    if is_prompt is None:
        is_prompt = _transcript_tools()._is_real_user_prompt
    names = "|".join(k for k in kinds if k in _HOST_KINDS)
    if not names:
        return False
    line = re.compile(
        r"(?m)^[ \t]*FS_HOST_(?:" + names + r")[ \t]+" + re.escape(gate) + r"(?:\.[A-Za-z0-9][A-Za-z0-9_.+-]*)?[ \t]*="
    )
    for row in rows[start:]:
        if not founders_message(row, is_prompt):
            continue
        if any(line.search(t) for t in _founder_texts(row)):
            return True
    return False


# --- the run's ledger -------------------------------------------------------------------------------
# Shared with `asked_gate_check.py`, `no_ask_check.py` and the Stop hook. Read only, never `_gates.py`
# (a hook never loads it); every failure is None or False, so an unreadable ledger is today's behaviour.

# The run id grammar (`_run_status.RUN_ID_RE`, held equal by a test).
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LEDGER_PATH = re.compile(r'"ledger_path_shell"\s*:\s*"([^"]+)"')


def ledger_path(rows: list[dict[str, Any]]) -> str | None:
    """The ledger the latest `start` result on the main thread named, if any: the route for a check with no
    OUTPUT_PATH (the question tool, the Stop hook). The path is the session shell's, so it opens only where
    the hook shares that filesystem."""
    strings = _dispatch_tools().strings
    found = None
    for row in rows:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        for text in strings((row.get("message") or {}).get("content")):
            m = _LEDGER_PATH.search(text)
            if m:
                found = m.group(1)
    return found


def read_ledger(path: str | None, run_id: str | None = None) -> dict[str, Any] | None:
    """The ledger at `path`, or None when it cannot be read or is not an object; with `run_id`, also None
    when the ledger is another run's."""
    # A regular file only: the path is model-written, and opening a FIFO or a device would block the hook.
    if not isinstance(path, str) or not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(ledger, dict):
        return None
    if run_id is not None and ledger.get("run_id") != run_id:
        return None
    return ledger


def run_ledger(run_dir: str | None, run_id: str | None) -> dict[str, Any] | None:
    """The ledger this run's `run_ref.json` names, found as the run status finds it
    (`_run_status.locate_from_run_dir`): the ref's run id must be this one, its `ledger_rel` relative with
    no `..`, and the nearest ancestor of the run dir holding it wins. None wherever that fails."""
    if not run_dir or not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        return None
    ref_path = os.path.join(run_dir, "handoff", run_id, "run_ref.json")
    if not os.path.isfile(ref_path):  # a regular file only, as in `read_ledger`
        return None
    try:
        with open(ref_path, encoding="utf-8") as fh:
            ref = json.load(fh)
        rel = ref.get("ledger_rel") if isinstance(ref, dict) else None
        if not isinstance(rel, str) or not rel or ref.get("run_id") != run_id:
            return None
        if os.path.isabs(rel) or ".." in rel.split("/"):
            return None
        probe = os.path.dirname(os.path.abspath(run_dir))
        while not os.path.isfile(os.path.join(probe, rel)):
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent
    except (OSError, ValueError):
        return None
    return read_ledger(os.path.join(probe, rel), run_id)


def ledger_no_ask(ledger: Any) -> bool:
    """The run's ledger records that the request said not to ask (`_gates.no_ask`)."""
    return isinstance(ledger, dict) and isinstance(ledger.get("no_ask"), dict)


def answered_by_request(ledger: Any, key: str) -> bool:
    """The run's ledger records that this gate's current answer was applied from a line the request carried,
    rather than recorded by hand: a copy of `_gates.answered_by_request`, held equal to it by a test."""
    if not isinstance(ledger, dict):
        return False
    gates, pre = ledger.get("gates"), ledger.get("pre_answers")
    entry = gates.get(key) if isinstance(gates, dict) else None
    pa = pre.get(key) if isinstance(pre, dict) else None
    if not isinstance(entry, dict) or not isinstance(pa, dict) or entry.get("state") != "answered":
        return False
    cur = entry.get("current")
    answered_at = cur.get("answered_at") if isinstance(cur, dict) else None
    return bool(pa.get("applied_at")) and pa.get("applied_at") == answered_at


def _marker(context: str) -> str:
    """One hold per sizing dispatch. On the first live firing TOP_DOWN was held and BOTTOM_UP,
    dispatched beside it, went through on TOP_DOWN's marker -- the one retry spent by a sibling."""
    return f"{MARKER}[{context}]"


def _retried(rows: list[dict[str, Any]], is_prompt: Any, context: str) -> bool:
    start = _window_start(rows, is_prompt)
    mark = _marker(context)
    # Only a tool result can carry this check's hold: a skill's expanded text or a delivered notification
    # that quotes the marker does not spend the retry.
    return any(
        row.get("type") == "user"
        and not row.get("isMeta")
        and from_founder(row)
        and mark in json.dumps(row.get("message"))
        for row in rows[start:]
    )


def reason_for(context: str, missing: list[tuple[str, list[tuple[float, str, bool]]]]) -> str:
    """The question, built from what is recorded. It names what was never offered rather than saying
    the founder was not asked: on the first live firing they had been asked about two of three
    figures, and "not asked" read to the model as its recorded choice not taking effect."""
    parts = []
    for field, figures in missing:
        name = _FIELD_NAMES.get(field, field.replace("_", " "))
        left_out = "; ".join(desc for _, desc, offered in figures if not offered)
        already = "; ".join(desc for _, desc, offered in figures if offered)
        part = f"{name}: never offered: {left_out}"
        if already:
            part += f" (already offered: {already})"
        parts.append(part)
    return (
        f"{_marker(context)} Held once: the founder's materials state more than one figure for the same "
        f"input, and no question has offered all of them. {' | '.join(parts)}. "
        "Ask them now with one option per figure, each option naming its amount, then record their "
        "answer and dispatch again. If the founder asked not to be asked questions, record that, keep "
        "the figure recorded now, and dispatch again."
    )


def decide(payload: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The hold, or None. `rows` is the transcript already read by a caller that has it."""
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str):
        return None
    context = sizing_context(prompt)
    if context is None:
        return None
    transcript, raw_cwd = payload.get("transcript_path"), payload.get("cwd")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None
    path = inputs_from_output_path(prompt, cwd) or (find_inputs(cwd) if cwd else None)
    if path is None:
        _log(f"sizing dispatch, but no inputs found from its OUTPUT_PATH or under cwd {cwd!r}; not checked")
        return None
    with open(path, encoding="utf-8") as fh:
        inputs = json.load(fh)
    if not isinstance(inputs, dict):
        return None
    tools = _transcript_tools()
    if rows is None:
        rows = tools.read_transcript(transcript)
    if _retried(rows, tools._is_real_user_prompt, context):
        return None
    # The request said not to ask: nothing is put, and the figure's no-ask default is taken by the scripts.
    if no_ask_in(rows, _window_start(rows, tools._is_real_user_prompt), tools._is_real_user_prompt):
        return None
    # The founder's own request answered it: a host line in a real prompt of this request.
    if host_line_in(
        rows, _window_start(rows, tools._is_real_user_prompt), GATE, ("ANSWER",), tools._is_real_user_prompt
    ):
        return None
    # The run's ledger records that the request said not to ask, or answered an input from its own lines
    # (bare or per input: the bare line is applied to each input's key). See THE ONE ARTIFACT READ.
    found = run_dir_from_output_path(prompt, cwd)
    ledger = run_ledger(*found) if found is not None else None
    if ledger_no_ask(ledger):
        return None
    unanswered = unasked(inputs, rows, tools._is_real_user_prompt)
    missing = [m for m in unanswered if not answered_by_request(ledger, f"{GATE}.{m[0]}")]
    if not missing:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason_for(context, missing),
        }
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            decision = decide(payload)
            if decision is not None:
                sys.stdout.write(json.dumps(decision))
    except Exception as e:  # noqa: BLE001 - a hook that crashes holds nothing and confuses everyone
        _log(f"{type(e).__name__}: {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
