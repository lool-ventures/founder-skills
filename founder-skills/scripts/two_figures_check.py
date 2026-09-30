#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
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
import importlib.util
import json
import os
import re
import sys
from typing import Any

MARKER = "[two-figures-check]"
SIZING_CONTEXTS = ("CONTEXT: TOP_DOWN_METHODOLOGY", "CONTEXT: BOTTOM_UP_METHODOLOGY")
DISPATCH_TOOLS = ("Agent", "Task")
INPUTS_GLOBS = ("artifacts/market-sizing-*/inputs.json", "mnt/outputs/artifacts/market-sizing-*/inputs.json")
# A figure is matched whole: "1,261.00" is 1261, never 261.
_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?!\d|,\d)")
_FIELD_NAMES = {"arpu": "ARPU"}
# The whole line, trimmed, as dispatch_prompt_check reads it: local-lane paths contain spaces.
_OUTPUT_RE = re.compile(r"^[ \t]*OUTPUT_PATH:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


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


def _numbers(text: str) -> set[float]:
    return {
        float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else "")) for m in _NUMBER_RE.finditer(text)
    }


def _figure(value: float) -> str:
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


def inputs_from_output_path(prompt: str, cwd: str | None) -> str | None:
    """This run's inputs.json, from the dispatch's own OUTPUT_PATH. It walks up to the last `handoff`
    segment rather than a fixed depth, because a later round writes one level further down. A relative
    path is resolved against cwd."""
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
    candidate = os.path.join(os.sep.join(dirs[:at]) or os.sep, "inputs.json")
    return candidate if os.path.isfile(candidate) else None


def find_inputs(cwd: str) -> str | None:
    found = [p for g in INPUTS_GLOBS for p in glob.glob(os.path.join(cwd, g)) if os.path.isfile(p)]
    return max(found, key=os.path.getmtime) if found else None


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
    start = 0
    for i, row in enumerate(rows):
        if is_prompt(row):
            start = i
    offered: list[set[float]] = []
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


def _marker(context: str) -> str:
    """One hold per sizing dispatch. On the first live firing TOP_DOWN was held and BOTTOM_UP,
    dispatched beside it, went through on TOP_DOWN's marker -- the one retry spent by a sibling."""
    return f"{MARKER}[{context}]"


def _retried(rows: list[dict[str, Any]], is_prompt: Any, context: str) -> bool:
    start = 0
    for i, row in enumerate(rows):
        if is_prompt(row):
            start = i
    mark = _marker(context)
    return any(row.get("type") == "user" and mark in json.dumps(row.get("message")) for row in rows[start:])


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


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not prompt.lstrip().startswith(SIZING_CONTEXTS):
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
    context = prompt.lstrip().split("\n", 1)[0].removeprefix("CONTEXT: ").strip()
    tools = _transcript_tools()
    rows = tools.read_transcript(transcript)
    if _retried(rows, tools._is_real_user_prompt, context):
        return None
    missing = unasked(inputs, rows, tools._is_real_user_prompt)
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
