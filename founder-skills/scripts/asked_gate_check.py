#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""PreToolUse hook: the dispatch that follows a confirmation is held once until the question was asked.

WHY. Three steps go ahead only after the founder confirms something: market-sizing's approach before
the sizing, financial-model-review's extracted values before the checklist, and ic-sim's decline before
the write-up's coaching. The answer is recorded by a script, but a script cannot tell whether anyone was
asked: the model can record an answer it made up. What the model cannot write is the transcript, so the
evidence that the question was asked is read there, and the step that must not run first is the
dispatch, as `two_figures_check.py` does for market-sizing's figures.

WHICH DISPATCH. `ROWS` maps (context, agent) to the gate it follows. It ships empty: a row is enabled
when its skill asks the question with the labels below, so that an older wording is never held. With
`ROWS` empty every call returns before anything is loaded or read. The context is read as every dispatch
check reads a first line (`dispatch_type_check.context_of`), the agent after our plugin's prefix.

THE WINDOW. From the founder's message that started this run to the dispatch, across later messages:
a question asked in an earlier message of the same run counts (corrections typed in a new message, a
decline held and finished later). The run is found by its id, which every dispatch names in its
OUTPUT_PATH: the first message carrying `FS_HOST_RUN_ID=<id>`, or the run status script's `start` call
whose output names it. Without either, the latest `Skill` call or slash command of the row's skill;
without that, the whole transcript, never nothing. A compaction summary is never a window start, and a
background agent's result the runtime delivers as a user row is never a founder's message.

THE EVIDENCE, any one of, strongest first:
1. `ask_user_question`: a question tool call on the main thread offering at least two of the gate's
   labels (both, for a gate with two), or asking the gate's question with at least one of them; a question
   that only reads like the gate's never passes alone. Labels and question are compared tolerantly
   (`MATCH_RATIO` on their letters and digits), because a skill words its options in its own voice; a
   generic label alone never passes. Its result must not be an error (a question another check
   held was not asked); a call with no result counts once a founder's message follows it.
2. `form`: Desktop's question form offering the labels the same way, answered by a later message
   starting with its header and a dash, or the Skip line. Counted only while the form reader is on
   (`_form_reply.FORM_REPLY_ENABLED`).
3. `host_line`: an `FS_HOST_ANSWER <gate>=` or `FS_HOST_VALUE <gate>=` line in a founder's own message:
   never a tool's input or output, a skill's expanded text, a sub-agent, or a compaction summary.
4. `plain_chat`: assistant text naming at least two labels, followed by a founder's message. The
   weakest: any reply passes it. Kept, and measured through the record below.

ONE HOLD, ONE RETRY. The hold's reason is the question and its options, and the way out for a founder
who asked not to be asked. The second dispatch goes through on the hold's own marker,
`[asked-gate-check][<agent>:<CONTEXT>]`, found in the window: no model-written field is trusted to say
"the founder asked for no questions". A new run is a new window and a new budget.

MARKET-SIZING'S TWO QUESTIONS. The sizing dispatch is also held by `two_figures_check.py`. When this
check holds a sizing dispatch it asks that check too, with the transcript already read, and one hold
carries both questions; the figures check's marker rides along only when that check itself held, so
its own retry is never spent by this one.

THE RECORD. Every decision on an enabled row appends one line to `handoff/<run_id>/asked_evidence.jsonl`
in the run's dir, when that dir already holds the run's `run_ref.json`; nothing else writes the file and
the hook never makes a directory. The run status folds a pass on evidence into the gate's
`asked_evidence`, bound to the answer it followed by that answer's `answered_at`, read from the ledger.
It is a measurement of which evidence carried each step, not an attestation: the file is a plain file.

FAIL OPEN. Any error, any unexpected shape: exit 0, no stdout, one stderr line at most (the runner in
`pretooluse_dispatch.py`). No transcript: no hold. An ic-sim verdict that cannot be read: no hold, one
stderr line. SKILL.md does not depend on this hook. Python 3.9: it runs host-native at the host loop.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, NamedTuple

MARKER = "[asked-gate-check]"
DISPATCH_TOOLS = ("Agent", "Task")
QUESTION_TOOL = "AskUserQuestion"
EVIDENCE_FILE = "asked_evidence.jsonl"
EVIDENCE_SCHEMA = "founder-skills/asked_evidence"
EVIDENCE_SCHEMA_VERSION = 1
# Strongest first.
EVIDENCE_KINDS = ("ask_user_question", "form", "host_line", "plain_chat")
RECORD = True
# Two option texts agree when their letters and digits, case folded, are this close.
MATCH_RATIO = 0.8
# The verdicts ic-sim confirms before finishing the write-up.
DECLINES = ("pass", "hard_pass")
# The run id grammar (`_run_status.RUN_ID_RE`, held equal by a test).
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RECORD_MAX = 4000


class GateSpec(NamedTuple):
    skill: str
    # The registry's question and shown labels, held equal to it by a test.
    question: str
    labels: tuple[str, ...]
    # How the hold's reason names what is confirmed, and asks it.
    topic: str
    ask: str
    # "always", or "ic_decline": only when the scored verdict is a decline.
    owed: str
    extra: str = ""


GATES: dict[str, GateSpec] = {
    "ms_methodology": GateSpec(
        skill="market-sizing",
        question="I'll size this <top-down / bottom-up / both top-down and bottom-up> — does this approach look right?",
        labels=("Looks good", "Change methodology", "Correct or add data"),
        topic="the sizing approach",
        ask="I'll size this <the approach you chose> — does this approach look right?",
        owed="always",
    ),
    "fmr_extracted_values": GateSpec(
        skill="financial-model-review",
        question="Do the extracted values look right?",
        labels=(
            "The values look right, proceed",
            "I have corrections",
            "Proceed without reviewing the extracted values",
        ),
        topic="the extracted values",
        ask="Do the extracted values look right?",
        owed="always",
    ),
    "ic_decline_confirmation": GateSpec(
        skill="ic-sim",
        question="The scored result comes out to a Decline — want me to go ahead and finish the full write-up?",
        labels=("Yes, finish the write-up", "Hold off — let me add more context first"),
        topic="finishing the write-up after a Decline",
        ask="The scored result comes out to a Decline — want me to go ahead and finish the full write-up?",
        owed="ic_decline",
        extra=" If they choose to hold off, do not dispatch; pause until they are ready.",
    ),
}
HELD_GATE_IDS = tuple(GATES)
# (context, agent) -> gate: every row this check is built for. `ROWS` holds the ones enabled.
PLANNED_ROWS: dict[tuple[str, str], str] = {
    ("TOP_DOWN_METHODOLOGY", "market-sizing"): "ms_methodology",
    ("BOTTOM_UP_METHODOLOGY", "market-sizing"): "ms_methodology",
    ("CHECKLIST", "financial-model-review"): "fmr_extracted_values",
    ("POST_COMPOSE_COACHING", "ic-sim"): "ic_decline_confirmation",
}
ROWS: dict[tuple[str, str], str] = {}

_SLOT_RE = re.compile(r"<[^<>]*>")
_START_RE = re.compile(r"(?<![\w-])run_status\.py\b[^\n]*\sstart\b")


def _log(msg: str) -> None:
    print(f"asked_gate_check: {msg}", file=sys.stderr)


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


def _two_figures() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "two_figures_check.py")
    spec = importlib.util.spec_from_file_location("two_figures_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _form_reply() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_form_reply.py")
    spec = importlib.util.spec_from_file_location("_form_reply", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Ctx(NamedTuple):
    """What every evidence rule needs, loaded once per dispatch."""

    rows: list[dict[str, Any]]
    is_prompt: Any
    form: Any
    figures: Any


def _prompt(ctx: _Ctx, row: dict[str, Any]) -> bool:
    """A founder's message: a real prompt, not a compaction summary standing in for earlier ones, and not
    a background agent's result the runtime delivers as a user row."""
    return bool(ctx.figures.founders_message(row, ctx.is_prompt))


def _main_assistant(row: dict[str, Any]) -> list[Any]:
    if row.get("type") != "assistant" or row.get("isSidechain"):
        return []
    content = (row.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


# --- matching ---------------------------------------------------------------------------------------


def _letters(form: Any, text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", form.normalise(text)))


def _close(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or difflib.SequenceMatcher(None, a, b).ratio() >= MATCH_RATIO)


def labels_matched(form: Any, texts: list[str], labels: tuple[str, ...]) -> int:
    """How many of the gate's labels some offered text names."""
    offered = [_letters(form, t) for t in texts]
    return sum(1 for label in labels if any(_close(_letters(form, label), o) for o in offered))


def question_matches(form: Any, text: str, question: str) -> bool:
    """The gate's question, as asked. A registry question with a `<…>` slot matches on the words around
    the slot, whatever fills it."""
    asked = _letters(form, text)
    parts = _SLOT_RE.split(question)
    if len(parts) == 1:
        return _close(asked, _letters(form, question))
    head, tail = _letters(form, parts[0]), _letters(form, parts[-1])
    if len(asked) < len(head) + len(tail):
        return False
    return (not head or _close(asked[: len(head)], head)) and (not tail or _close(asked[-len(tail) :], tail))


def _need(spec: GateSpec) -> int:
    return min(2, len(spec.labels))


def _offered(ctx: _Ctx, options: list[str], questions: list[str], spec: GateSpec) -> bool:
    """The gate's question was put: two of its labels offered, or its question asked with at least one of
    them. A question that only reads like the gate's ("do the values look wrong?") never passes alone."""
    matched = labels_matched(ctx.form, options, spec.labels)
    if matched >= _need(spec):
        return True
    return matched >= 1 and any(question_matches(ctx.form, q, spec.question) for q in questions)


# --- the window -------------------------------------------------------------------------------------


def _run_anchor(ctx: _Ctx, run_id: str | None) -> int | None:
    """The first main-thread row naming this run: a founder's `FS_HOST_RUN_ID=<id>` line, or the result
    of the run status `start` call that printed the id."""
    if run_id is None:
        return None
    id_line = re.compile(r"(?m)^[ \t]*FS_HOST_RUN_ID=" + re.escape(run_id) + r"[ \t]*$")
    starts: set[str] = set()
    for i, row in enumerate(ctx.rows):
        if row.get("isSidechain"):
            continue
        for b in _main_assistant(row):
            command = (b.get("input") or {}).get("command") if isinstance(b.get("input"), dict) else None
            started = isinstance(command, str) and _START_RE.search(command) is not None
            if b.get("type") == "tool_use" and started and isinstance(b.get("id"), str):
                starts.add(b["id"])
        if row.get("type") != "user":
            continue
        content = (row.get("message") or {}).get("content")
        if _prompt(ctx, row):
            texts = [content] if isinstance(content, str) else []
            if isinstance(content, list):
                texts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
            if any(id_line.search(t) for t in texts):
                return i
        for b in content if isinstance(content, list) else []:
            if (
                isinstance(b, dict)
                and b.get("type") == "tool_result"
                and b.get("tool_use_id") in starts
                and not b.get("is_error")
                and re.search(r"(?<![A-Za-z0-9._-])" + re.escape(run_id) + r"(?![A-Za-z0-9._-])", json.dumps(b))
            ):
                return i
    return None


def window_start(ctx: _Ctx, skill: str, run_id: str | None, dispatch: Any) -> tuple[int, str]:
    """(the row the window starts at, "invocation" or "whole_transcript")."""
    anchor = _run_anchor(ctx, run_id)
    if anchor is None:
        mine = [i for i, s in dispatch.invocations(ctx.rows) if s == skill]
        anchor = mine[-1] if mine else None
    if anchor is None:
        return 0, "whole_transcript"
    start = next((i for i in range(anchor, -1, -1) if _prompt(ctx, ctx.rows[i])), 0)
    return start, "invocation"


# --- the evidence -----------------------------------------------------------------------------------


def _results(rows: list[dict[str, Any]], start: int) -> dict[str, bool]:
    """{tool_use_id: whether its result is an error} for the main thread since `start`."""
    out: dict[str, bool] = {}
    for row in rows[start:]:
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                out[b["tool_use_id"]] = bool(b.get("is_error"))
    return out


def _replied_after(ctx: _Ctx, at: int) -> bool:
    return any(_prompt(ctx, row) for row in ctx.rows[at + 1 :])


def asked_by_question(ctx: _Ctx, start: int, spec: GateSpec) -> bool:
    results = _results(ctx.rows, start)
    for i in range(start, len(ctx.rows)):
        for b in _main_assistant(ctx.rows[i]):
            if b.get("type") != "tool_use" or b.get("name") != QUESTION_TOOL or not isinstance(b.get("input"), dict):
                continue
            questions = b["input"].get("questions")
            offered = False
            for q in questions if isinstance(questions, list) else []:
                if not isinstance(q, dict):
                    continue
                options = q.get("options")
                labels = [
                    o["label"]
                    for o in (options if isinstance(options, list) else [])
                    if isinstance(o, dict) and isinstance(o.get("label"), str)
                ]
                raw = q.get("question")
                text = raw if isinstance(raw, str) else ""
                if _offered(ctx, labels, [text], spec):
                    offered = True
            if not offered:
                continue
            call_id = b.get("id")
            if isinstance(call_id, str) and call_id in results:
                if not results[call_id]:
                    return True
            elif _replied_after(ctx, i):
                return True
    return False


def asked_by_form(ctx: _Ctx, start: int, spec: GateSpec) -> bool:
    if not ctx.form.FORM_REPLY_ENABLED:
        return False
    for i in range(start, len(ctx.rows)):
        for b in _main_assistant(ctx.rows[i]):
            parts = ctx.figures.elicit_form_parts(b)
            if parts is None:
                continue
            header, pills, questions = parts
            if not _offered(ctx, [" ".join(p) for p in pills], questions, spec):
                continue
            for row in ctx.rows[i + 1 :]:
                if not _prompt(ctx, row):
                    continue
                line = ctx.figures._first_line(row)
                if line == ctx.form.SKIP_LINE or ctx.form.strip_header(line, header) is not None:
                    return True
    return False


def answered_by_host_line(ctx: _Ctx, start: int, gate: str) -> bool:
    return bool(ctx.figures.host_line_in(ctx.rows, start, gate, ("ANSWER", "VALUE"), ctx.is_prompt))


def asked_in_chat(ctx: _Ctx, start: int, spec: GateSpec) -> bool:
    wanted = [ctx.form.normalise(label) for label in spec.labels]
    for i in range(start, len(ctx.rows)):
        texts = [
            b["text"]
            for b in _main_assistant(ctx.rows[i])
            if b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        if not texts:
            continue
        said = ctx.form.normalise(" ".join(texts))
        named = sum(1 for w in wanted if w and re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", said))
        if named >= _need(spec) and _replied_after(ctx, i):
            return True
    return False


def evidence(ctx: _Ctx, start: int, gate: str, spec: GateSpec) -> tuple[str | None, list[str]]:
    """(the strongest evidence found, every kind found), strongest first."""
    found = {
        "ask_user_question": asked_by_question(ctx, start, spec),
        "form": asked_by_form(ctx, start, spec),
        "host_line": answered_by_host_line(ctx, start, gate),
        "plain_chat": asked_in_chat(ctx, start, spec),
    }
    kinds = [k for k in EVIDENCE_KINDS if found[k]]
    return (kinds[0] if kinds else None), kinds


def marker(agent: str, context: str) -> str:
    return f"{MARKER}[{agent}:{context}]"


def held_before(rows: list[dict[str, Any]], start: int, mark: str, strings: Any, figures: Any) -> bool:
    """This check's hold in the window: a skill's expanded text or a delivered notification that quotes the
    marker does not spend the retry."""
    return any(
        row.get("type") == "user"
        and not row.get("isMeta")
        and figures.from_founder(row)
        and any(mark in s for s in strings(row.get("message")))
        for row in rows[start:]
    )


# --- owed, and the reason ---------------------------------------------------------------------------


def owed(spec: GateSpec, run_dir: str | None) -> bool:
    if spec.owed == "always":
        return True
    path = os.path.join(run_dir, "score_dimensions.json") if run_dir else None
    try:
        if path is None:
            raise OSError("no run dir in the dispatch's OUTPUT_PATH")
        with open(path, encoding="utf-8") as fh:
            verdict = json.load(fh)["summary"]["verdict"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log(f"{spec.skill} verdict not readable ({type(e).__name__}: {e}); not checked")
        return False
    return verdict in DECLINES


def reason_for(mark: str, spec: GateSpec) -> str:
    options = " / ".join(f'"{label}"' for label in spec.labels)
    return (
        f"{mark} Held once: before this step the founder confirms {spec.topic}, and no question about it "
        f'shows since this request began. Ask it now: "{spec.ask}" Options: {options}. Record their answer, '
        "replacing the one recorded before if it differs, then dispatch again. If no one is present to answer, "
        f"or the founder asked not to be asked, record that and dispatch again.{spec.extra}"
    )


# --- the record -------------------------------------------------------------------------------------


def _ledger_answered_at(run_dir: str, run_id: str, gate: str) -> str | None:
    """The recorded answer's `answered_at`, read from the ledger the run's `run_ref.json` names (the
    nearest ancestor of the run dir holding it, as the run status finds it). None when unreadable."""
    try:
        with open(os.path.join(run_dir, "handoff", run_id, "run_ref.json"), encoding="utf-8") as fh:
            ref = json.load(fh)
        rel = ref.get("ledger_rel") if isinstance(ref, dict) else None
        if not isinstance(rel, str) or ref.get("run_id") != run_id or os.path.isabs(rel) or ".." in rel.split("/"):
            return None
        probe = os.path.dirname(os.path.abspath(run_dir))
        while not os.path.isfile(os.path.join(probe, rel)):
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent
        with open(os.path.join(probe, rel), encoding="utf-8") as fh:
            ledger = json.load(fh)
        value = ((ledger.get("gates") or {}).get(gate) or {}).get("current") or {}
        at = value.get("answered_at") if isinstance(value, dict) else None
        return at if isinstance(at, str) else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def _record(run_dir: str | None, run_id: str | None, line: dict[str, Any]) -> None:
    if not RECORD or run_dir is None or run_id is None:
        return
    folder = os.path.join(run_dir, "handoff", run_id)
    if not os.path.isfile(os.path.join(folder, "run_ref.json")):
        return
    line = {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        **line,
        "answered_at": _ledger_answered_at(run_dir, run_id, str(line.get("gate"))),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "by": "asked_gate_check.py",
    }
    text = json.dumps(line, ensure_ascii=False)
    if len(text.encode("utf-8")) > _RECORD_MAX:
        return
    try:
        fd = os.open(os.path.join(folder, EVIDENCE_FILE), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (text + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        _log(f"evidence not recorded ({type(e).__name__}: {e})")


# --- the decision -----------------------------------------------------------------------------------


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not ROWS:
        return None
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not isinstance(tool_input, dict):
        return None
    if not any(context in prompt for context, _agent in ROWS):
        return None
    dispatch = _dispatch_tools()
    context = dispatch.context_of(prompt)
    sent = tool_input.get("subagent_type")
    agent = dispatch._bare(sent) if isinstance(sent, str) else ""
    gate = ROWS.get((context, agent)) if context else None
    if gate is None:
        return None
    spec = GATES[gate]
    transcript, raw_cwd = payload.get("transcript_path"), payload.get("cwd")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    figures = _two_figures()
    cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None
    found = figures.run_dir_from_output_path(prompt, cwd)
    run_dir, run_id = found if found is not None else (None, None)
    if run_id is not None and not RUN_ID_RE.match(run_id):
        run_id = None
    if not owed(spec, run_dir):
        return None
    tools = _transcript_tools()
    ctx = _Ctx(tools.read_transcript(transcript), tools._is_real_user_prompt, _form_reply(), figures)
    start, window = window_start(ctx, spec.skill, run_id, dispatch)
    strongest, kinds = evidence(ctx, start, gate, spec)
    mark = marker(agent, str(context))

    def note(decision: str, passed_on: str | None, kinds: list[str]) -> None:
        line = {"gate": gate, "context": context, "agent": agent, "decision": decision, "passed_on": passed_on}
        line.update({"evidence": kinds[0] if kinds else None, "kinds": kinds, "window": window})
        _record(run_dir, run_id, line)

    if strongest is not None:
        note("pass", "evidence", kinds)
        return None
    if held_before(ctx.rows, start, mark, dispatch.strings, figures):
        note("pass", "marker", [])
        return None
    reason = reason_for(mark, spec)
    if spec.skill == "market-sizing":
        try:
            also = figures.decide(payload, rows=ctx.rows)
        except Exception as e:  # noqa: BLE001 - the figures check failing open must not stop this hold
            _log(f"two_figures_check: {type(e).__name__}: {e}")
            also = None
        if also is not None:
            reason += " " + also["hookSpecificOutput"]["permissionDecisionReason"]
    note("hold", None, [])
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
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
