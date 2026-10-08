"""`asked_gate_check.py`: the dispatch that follows a confirmation is held once until the question was asked.

The check ships with an empty table (`ROWS`): a row is enabled when its skill asks the question with the
registry's labels. These tests load the module by path and enable its planned rows on the module object;
one test runs the shipped wrapper to show that the empty table holds nothing. Transcripts are shaped like
the session JSONL the other hook tests use; every name and figure is invented.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
MARKER = "[asked-gate-check]"
RUN_ID = "r-acme-1"

sys.path.insert(0, str(SCRIPTS))
import _founder_text  # type: ignore[import-not-found]  # noqa: E402
import _gates  # type: ignore[import-not-found]  # noqa: E402
import _run_status  # type: ignore[import-not-found]  # noqa: E402


def _load(name: str = "asked_gate_check", *, enabled: bool = True) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if enabled and name == "asked_gate_check":
        mod.ROWS = dict(mod.PLANNED_ROWS)
    return mod


SHIPPED = _load(enabled=False)

# (context, agent, gate) for each planned row; market-sizing's two contexts share one gate.
ROW_CASES = [
    ("BOTTOM_UP_METHODOLOGY", "market-sizing", "ms_methodology"),
    ("CHECKLIST", "financial-model-review", "fmr_extracted_values"),
    ("POST_COMPOSE_COACHING", "ic-sim", "ic_decline_confirmation"),
]
_IDS = [c[1] for c in ROW_CASES]


# --- transcript rows ---------------------------------------------------------------------------------


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _assistant(*blocks: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}, **extra}


def _text(text: str) -> dict[str, Any]:
    return _assistant({"type": "text", "text": text})


def _notification(text: str) -> dict[str, Any]:
    """A background agent's result, delivered as a user row."""
    return {"type": "user", "origin": {"kind": "task-notification"}, "message": {"role": "user", "content": text}}


def _skill(skill: str) -> dict[str, Any]:
    return _assistant(
        {"type": "tool_use", "id": "toolu_s", "name": "Skill", "input": {"skill": f"founder-skills:{skill}"}}
    )


def _result(call_id: str, text: str = "ok", *, is_error: bool = False) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _question(call_id: str, labels: tuple[str, ...] | list[str], question: str = "Anything?") -> dict[str, Any]:
    q = {"question": question, "header": "Check", "options": [{"label": x, "description": ""} for x in labels]}
    return _assistant({"type": "tool_use", "id": call_id, "name": "AskUserQuestion", "input": {"questions": [q]}})


def _asked(labels: tuple[str, ...] | list[str], *, call_id: str = "toolu_q", **kw: Any) -> list[dict[str, Any]]:
    return [_question(call_id, labels, **kw), _result(call_id, "User answered.")]


def _shell(command: str, call_id: str, out: str) -> list[dict[str, Any]]:
    use = {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}
    return [_assistant(use), _result(call_id, out)]


def _labels(gate: str) -> tuple[str, ...]:
    return tuple(SHIPPED.GATES[gate].labels)


# --- the run on disk, and the payload ----------------------------------------------------------------


def _run_dir(tmp_path: Path, skill: str, *, verdict: str | None = "pass") -> Path:
    run = tmp_path / "artifacts" / f"{skill}-acme"
    (run / "handoff" / RUN_ID).mkdir(parents=True, exist_ok=True)
    if skill == "ic-sim" and verdict is not None:
        (run / "score_dimensions.json").write_text(json.dumps({"summary": {"verdict": verdict}}), encoding="utf-8")
    return run


def _prompt(context: str, run: Path | str) -> str:
    return f"CONTEXT: {context}\nOUTPUT_PATH: {run}/handoff/{RUN_ID}/out.json\nRead the files.\n"


def _payload(
    tmp_path: Path, rows: list[dict[str, Any]], context: str, agent: str, *, prompt: str | None = None
) -> dict[str, Any]:
    skill = agent.split(":")[-1]
    run = _run_dir(tmp_path, skill)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": "/var/empty",
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": {
            "prompt": prompt if prompt is not None else _prompt(context, run),
            "subagent_type": f"founder-skills:{agent}",
            "description": "d",
        },
    }


def _decide(tmp_path: Path, rows: list[dict[str, Any]], context: str, agent: str, mod: Any = None, **kw: Any) -> Any:
    return (mod or _load()).decide(_payload(tmp_path, rows, context, agent, **kw))


def _reason(decision: Any) -> str:
    assert decision is not None, "expected a hold"
    out = decision["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return str(out["permissionDecisionReason"])


def _start(skill: str) -> list[dict[str, Any]]:
    return [_user("Please run this for Acme."), _skill(skill)]


# --- the shipped table -------------------------------------------------------------------------------


SHIPPED_ROWS = {
    ("CHECKLIST", "financial-model-review"): "fmr_extracted_values",
    ("TOP_DOWN_METHODOLOGY", "market-sizing"): "ms_methodology",
    ("BOTTOM_UP_METHODOLOGY", "market-sizing"): "ms_methodology",
    ("POST_COMPOSE_COACHING", "ic-sim"): "ic_decline_confirmation",
}


def test_the_shipped_table_is_exactly_the_rows_whose_skills_ask_with_the_registry_labels() -> None:
    """financial-model-review's Step 3.6, market-sizing's Gate and ic-sim's Step 8.5 ask the registry's question
    and labels, so every planned row is enabled."""
    assert SHIPPED.ROWS == SHIPPED_ROWS == SHIPPED.PLANNED_ROWS


def test_the_shipped_hook_holds_an_ic_coaching_dispatch_on_a_decline_once(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _start("ic-sim"), "POST_COMPOSE_COACHING", "ic-sim")
    r = subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and f"{MARKER}[ic-sim:POST_COMPOSE_COACHING]" in r.stdout, r
    reason = _reason(SHIPPED.decide(payload))
    assert "do not send the report" in reason
    retry = [*_start("ic-sim"), _result("toolu_x", reason, is_error=True)]
    assert SHIPPED.decide(_payload(tmp_path, retry, "POST_COMPOSE_COACHING", "ic-sim")) is None, "one retry"


@pytest.mark.parametrize("verdict", ["invest", "more_diligence"])
def test_the_shipped_hook_passes_an_ic_coaching_dispatch_that_is_no_decline(tmp_path: Path, verdict: str) -> None:
    """Paired with its control: the same readable file scoring a decline is held, so the pass is the verdict's,
    not a file the hook failed to read (which also passes, failing open)."""
    payload = _payload(tmp_path, _start("ic-sim"), "POST_COMPOSE_COACHING", "ic-sim")
    scores = tmp_path / "artifacts" / "ic-sim-acme" / "score_dimensions.json"
    scores.write_text(json.dumps({"summary": {"verdict": verdict}}), encoding="utf-8")
    assert SHIPPED.decide(payload) is None
    scores.write_text(json.dumps({"summary": {"verdict": "pass"}}), encoding="utf-8")
    assert SHIPPED.decide(payload) is not None, "control: a decline in the same file is held"


def test_the_shipped_hook_passes_ic_after_hold_off_then_finish_and_on_a_host_resume(tmp_path: Path) -> None:
    labels = _labels("ic_decline_confirmation")
    rows = [*_start("ic-sim"), *_asked(labels), _text("Pausing here."), _user("OK, finish it."), _text("Composing.")]
    assert _decide(tmp_path, rows, "POST_COMPOSE_COACHING", "ic-sim", mod=SHIPPED) is None
    resume = f"Resume the ic-sim run.\nFS_HOST_RUN_ID={RUN_ID}\nFS_HOST_ANSWER ic_decline_confirmation=finish\n"
    assert _decide(tmp_path, [_user(resume), _skill("ic-sim")], "POST_COMPOSE_COACHING", "ic-sim", mod=SHIPPED) is None


def test_the_hooks_declines_are_the_registrys() -> None:
    """The hook cannot load `_gates`, so it carries the decline verdicts itself. It does not check the scores
    file's run id as the registry's predicate does: at worst it holds once more than needed, never less."""
    assert tuple(SHIPPED.DECLINES) == tuple(_gates.IC_DECLINES)


def test_the_shipped_hook_holds_an_fmr_checklist_with_nothing_asked_once(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _start("financial-model-review"), "CHECKLIST", "financial-model-review")
    r = subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and MARKER in r.stdout, r
    assert SHIPPED.decide(payload) is not None


@pytest.mark.parametrize("context", ["TOP_DOWN_METHODOLOGY", "BOTTOM_UP_METHODOLOGY"])
def test_the_shipped_hook_holds_a_sizing_dispatch_with_nothing_asked_once(tmp_path: Path, context: str) -> None:
    payload = _payload(tmp_path, _start("market-sizing"), context, "market-sizing")
    r = subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and f"{MARKER}[market-sizing:{context}]" in r.stdout, r
    reason = _reason(SHIPPED.decide(payload))
    retry = [*_start("market-sizing"), _result("toolu_x", reason, is_error=True)]
    assert SHIPPED.decide(_payload(tmp_path, retry, context, "market-sizing")) is None, "one hold, one retry"


def test_the_shipped_hook_passes_a_sizing_dispatch_the_request_answered(tmp_path: Path) -> None:
    rows = [_user("Please size this.\nFS_HOST_ANSWER ms_methodology=looks_good"), _skill("market-sizing")]
    assert SHIPPED.decide(_payload(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing")) is None


def test_the_shipped_hook_holds_both_market_sizing_questions_in_one_deny(tmp_path: Path) -> None:
    _figures(tmp_path)
    reason = _wrapper(tmp_path, _start("market-sizing"), mod=SHIPPED)
    assert reason is not None
    assert reason.startswith(f"{MARKER}[market-sizing:TOP_DOWN_METHODOLOGY]")
    assert "[two-figures-check][TOP_DOWN_METHODOLOGY]" in reason
    retry = [*_start("market-sizing"), _result("toolu_x", reason, is_error=True)]
    assert _wrapper(tmp_path, retry, mod=SHIPPED) is None


def test_the_shipped_hook_passes_a_question_asked_word_for_word_from_needs_input(tmp_path: Path) -> None:
    """market-sizing asks the Gate with the registry's labels, and the figures from what `open` prints: the
    typed option carries its figure, so a question built verbatim from it offers every figure."""
    _figures(tmp_path)
    figures = ["The figure you typed: 157 per month", "311 per month (list rate)"]
    rows = [
        *_start("market-sizing"),
        *_asked(_labels("ms_methodology")),
        *_asked(figures, call_id="toolu_f", question=_gates.GATES["ms_two_figures"]["question"]),
    ]
    assert _wrapper(tmp_path, rows, mod=SHIPPED) is None


def test_the_labels_and_questions_are_the_registrys() -> None:
    for gid, spec in SHIPPED.GATES.items():
        g = _gates.GATES[gid]
        assert spec.labels == tuple(o["label"] for o in g["options"] if o["shown"]), gid
        assert spec.question == g["question"], gid
        assert spec.skill == g["skill"], gid


def test_the_gates_held_are_the_registrys_since_invocation_gates() -> None:
    since = {gid for gid, g in _gates.GATES.items() if g["asked_check"] == "since_invocation"}
    assert set(SHIPPED.HELD_GATE_IDS) == since
    assert set(SHIPPED.HELD_GATE_IDS) <= set(_gates.HELD_GATES)


def test_every_planned_row_is_its_gates_skill_and_an_allowed_agent() -> None:
    dispatch = _load("dispatch_type_check")
    assert set(SHIPPED.PLANNED_ROWS.values()) == set(SHIPPED.GATES)
    for (context, agent), gate in SHIPPED.PLANNED_ROWS.items():
        assert agent == _gates.GATES[gate]["skill"], (context, agent)
        assert agent in dispatch.CONTEXT_AGENTS[context], (context, agent)
    assert set(SHIPPED.ROWS) <= set(SHIPPED.PLANNED_ROWS)


def test_the_run_id_grammar_and_record_names_are_the_run_status_modules() -> None:
    assert SHIPPED.RUN_ID_RE.pattern == _run_status.RUN_ID_RE.pattern
    assert SHIPPED.EVIDENCE_FILE == _run_status.ASKED_EVIDENCE_FILE
    assert SHIPPED.EVIDENCE_SCHEMA == _run_status.ASKED_EVIDENCE_SCHEMA
    assert SHIPPED.EVIDENCE_SCHEMA_VERSION == _run_status.ASKED_EVIDENCE_SCHEMA_VERSION
    assert set(SHIPPED.EVIDENCE_KINDS) == set(_run_status.HOOK_ASKED_EVIDENCE)
    assert set(_gates.ASKED_EVIDENCE) == set(_gates.SCRIPT_ASKED_EVIDENCE) | set(_run_status.HOOK_ASKED_EVIDENCE)


def test_the_asked_gate_check_runs_second() -> None:
    checks = _load("pretooluse_dispatch").CHECKS
    assert checks.index("asked_gate_check") == 1
    assert checks.index("asked_gate_check") < checks.index("two_figures_check") < checks.index("dispatch_prompt_check")


# --- per row -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_nothing_asked_is_held_once_with_the_question_and_its_options(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    reason = _reason(_decide(tmp_path, _start(agent), context, agent))
    assert reason.startswith(f"{MARKER}[{agent}:{context}] Held once:")
    for label in _labels(gate):
        assert f'"{label}"' in reason
    held = [*_start(agent), _result("toolu_x", reason, is_error=True)]
    assert _decide(tmp_path, held, context, agent) is None, "the retry goes through on the hold's own marker"


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_question_offering_two_labels_lets_it_through(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    labels = _labels(gate)
    assert _decide(tmp_path, [*_start(agent), *_asked(labels[:2])], context, agent) is None
    # The question tool's other labels and order do not matter.
    reordered = [*_start(agent), *_asked(["Something else", labels[1], labels[0]])]
    assert _decide(tmp_path, reordered, context, agent) is None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_one_label_alone_does_not_count(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    rows = [*_start(agent), *_asked([_labels(gate)[0], "Something unrelated"])]
    assert _decide(tmp_path, rows, context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_question_that_was_held_is_not_a_question_asked(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    rows = [
        *_start(agent),
        _question("toolu_q", _labels(gate)),
        _result("toolu_q", "[review-page-check] Held", is_error=True),
    ]
    assert _decide(tmp_path, rows, context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_question_with_no_result_counts_only_once_a_reply_follows(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    asked = [*_start(agent), _question("toolu_q", _labels(gate))]
    assert _decide(tmp_path, asked, context, agent) is not None
    assert _decide(tmp_path, [*asked, _user("The first one.")], context, agent) is None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
@pytest.mark.parametrize("kind", ["ANSWER", "VALUE"])
def test_a_host_line_in_the_founders_message_lets_it_through(
    tmp_path: Path, context: str, agent: str, gate: str, kind: str
) -> None:
    rows = [_user(f"Please run this for Acme.\nFS_HOST_{kind} {gate}=x\n"), _skill(agent)]
    assert _decide(tmp_path, rows, context, agent) is None
    as_string = [{"type": "user", "message": {"role": "user", "content": f"Go.\n  FS_HOST_{kind} {gate} = x"}}]
    assert _decide(tmp_path, as_string, context, agent) is None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_request_that_said_not_to_ask_is_never_held_and_leaves_no_record(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    """Under `FS_HOST_NO_ASK` the gate's default is taken by script and nothing may be asked: no hold (its
    reason would tell the model to ask), and no evidence line, since nobody was asked."""
    run, _paths = _bound(tmp_path, agent)
    rows = [_user("Please run this for Acme.\nFS_HOST_RUN_ID=r-acme-1\nFS_HOST_NO_ASK\n"), _skill(agent)]
    assert _decide(tmp_path, rows, context, agent) is None
    assert _lines(run) == []
    # The same request without the line is held.
    assert _decide(tmp_path, [_user("Please run this for Acme."), _skill(agent)], context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_host_line_anywhere_else_does_not_count(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    line = f"FS_HOST_ANSWER {gate}=x"
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": f"echo '{line}'"}}
    for extra in (
        [_assistant(use)],
        [_assistant(use), _result("t1", line)],
        [_user(line, isMeta=True)],
        [_user(line, isSidechain=True)],
        [{"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": line}}],
        [_text(line)],
        [_notification(f"<task-notification>\n<result>{line}\n</result>\n</task-notification>")],
        [
            {
                "type": "user",
                "message": {"role": "user", "content": f"<task-notification>\n{line}\n</task-notification>"},
            }
        ],
    ):
        assert _decide(tmp_path, [*_start(agent), *extra], context, agent) is not None, extra


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_host_line_for_another_gate_does_not_count(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    rows = [_user(f"Go.\nFS_HOST_ANSWER {gate}_other=x\nFS_HOST_ANSWER ctx_basics.stage=seed\n"), _skill(agent)]
    assert _decide(tmp_path, rows, context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_a_plain_chat_question_counts_once_the_founder_replies(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    labels = _labels(gate)
    said = _text(f"Before I go on: {labels[0]}, or {labels[1]}?")
    assert _decide(tmp_path, [*_start(agent), said], context, agent) is not None
    assert _decide(tmp_path, [*_start(agent), said, _user("The second.")], context, agent) is None
    compacted = {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "Summary."}}
    assert _decide(tmp_path, [*_start(agent), said, compacted], context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_another_contexts_marker_does_not_spend_this_ones_retry(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    other = _result("toolu_x", f"{MARKER}[{agent}:SOMETHING_ELSE] Held once: …", is_error=True)
    assert _decide(tmp_path, [*_start(agent), other], context, agent) is not None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_the_context_line_is_read_as_every_dispatch_check_reads_it(
    tmp_path: Path, context: str, agent: str, gate: str
) -> None:
    run = _run_dir(tmp_path, agent)
    tail = f"\nOUTPUT_PATH: {run}/handoff/{RUN_ID}/out.json\n"
    for prompt in (
        f"\u200bCONTEXT: {context}{tail}",
        f"\n CONTEXT: {context} (round 2){tail}",
        f"CONTEXT:{context}{tail}",
    ):
        assert _decide(tmp_path, _start(agent), context, agent, prompt=prompt) is not None, prompt
    assert _decide(tmp_path, _start(agent), context, agent, prompt=f"CONTEXT: {context}X{tail}") is None


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_another_agent_is_not_this_row(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    assert _decide(tmp_path, _start(agent), context, "deck-review") is None
    assert _decide(tmp_path, _start(agent), context, "other:" + agent) is None


def test_the_labels_are_matched_tolerantly() -> None:
    mod, form = _load(), _load("_form_reply")
    labels = _labels("fmr_extracted_values")
    assert mod.labels_matched(form, ["Looks right — proceed", "I have corrections."], labels) == 2
    assert mod.labels_matched(form, ["LOOKS RIGHT, PROCEED"], labels) == 1
    assert mod.labels_matched(form, ["Looks wrong, stop", "I need to correct something"], labels) == 0
    assert mod.labels_matched(form, ["Looks good"], _labels("ms_methodology")) == 1
    assert mod.labels_matched(form, ["Good"], _labels("ms_methodology")) == 0


def test_the_gates_question_counts_with_labels_in_the_skills_own_words(tmp_path: Path) -> None:
    mod, form = _load(), _load("_form_reply")
    q = _gates.GATES["ms_methodology"]["question"]
    for asked in (
        "I'll size this top-down — does this approach look right?",
        "I'll size this both top-down and bottom-up — does this approach look right?",
    ):
        assert mod.question_matches(form, asked, q), asked
    assert not mod.question_matches(form, "Which market should I size?", q)
    fmr_q = _gates.GATES["fmr_extracted_values"]["question"]
    assert mod.question_matches(form, "Do the extracted values look right?", fmr_q)
    # The gate's question with one of its labels passes; the question alone, with generic options, does not.
    one = [*_start("financial-model-review"), *_asked(["Looks right, proceed", "No"], question=fmr_q)]
    assert _decide(tmp_path, one, "CHECKLIST", "financial-model-review", mod) is None
    bare = [*_start("financial-model-review"), *_asked(["Yes", "No"], question=fmr_q)]
    assert _decide(tmp_path, bare, "CHECKLIST", "financial-model-review", mod) is not None


@pytest.mark.parametrize(
    "question",
    [
        "Do the extracted values look wrong?",
        "Are these the expected values?",
        "Do the extracted values look right?",
        "Do the extracted value look right to you?",
    ],
)
def test_a_question_that_reads_like_the_gates_never_passes_alone(tmp_path: Path, question: str) -> None:
    rows = [*_start("financial-model-review"), *_asked(["Yes", "No", "Not sure"], question=question)]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review") is not None


def test_a_paraphrased_label_matches_and_a_near_miss_does_not(tmp_path: Path) -> None:
    mod, form = _load(), _load("_form_reply")
    labels = _labels("fmr_extracted_values")
    assert mod.labels_matched(form, ["Values look right, proceed", "I have a correction"], labels) == 2
    rows = [*_start("financial-model-review"), *_asked(["Values look right, proceed", "I have a correction"])]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review", mod) is None
    assert mod.labels_matched(form, ["Values look wrong, stop", "I have questions"], labels) == 0
    near = [*_start("financial-model-review"), *_asked(["Values look wrong, stop", "I have questions"])]
    assert _decide(tmp_path, near, "CHECKLIST", "financial-model-review", mod) is not None


def test_an_ic_run_that_is_not_a_decline_is_not_held(tmp_path: Path) -> None:
    for verdict in ("invest", "more_diligence"):
        _run_dir(tmp_path, "ic-sim", verdict=verdict)
        (tmp_path / "artifacts" / "ic-sim-acme" / "score_dimensions.json").write_text(
            json.dumps({"summary": {"verdict": verdict}}), encoding="utf-8"
        )
        mod = _load()
        payload = _payload(tmp_path, _start("ic-sim"), "POST_COMPOSE_COACHING", "ic-sim")
        (tmp_path / "artifacts" / "ic-sim-acme" / "score_dimensions.json").write_text(
            json.dumps({"summary": {"verdict": verdict}}), encoding="utf-8"
        )
        assert mod.decide(payload) is None, verdict


def test_an_ic_verdict_that_cannot_be_read_fails_open_with_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _payload(tmp_path, _start("ic-sim"), "POST_COMPOSE_COACHING", "ic-sim")
    (tmp_path / "artifacts" / "ic-sim-acme" / "score_dimensions.json").unlink()
    assert _load().decide(payload) is None
    assert capsys.readouterr().err.count("\n") == 1


def test_no_transcript_fails_open(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing")
    payload["transcript_path"] = str(tmp_path / "absent.jsonl")
    assert _load().decide(payload) is None


def test_a_question_and_a_garbage_stdin_return_at_once(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing")
    payload["tool_name"] = "AskUserQuestion"
    assert _load().decide(payload) is None
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "asked_gate_check.py")], input="not json", capture_output=True, text=True
    )
    assert r.returncode == 0 and r.stdout == "" and len(r.stderr.strip().splitlines()) == 1


# --- the form ----------------------------------------------------------------------------------------


def _form(labels: tuple[str, ...] | list[str], header: str = "Review") -> dict[str, Any]:
    pills = "".join(f'<button type="button" class="elicit-pill" data-value="v">{x}</button>' for x in labels)
    code = (
        f'<form class="elicit"><div class="elicit-header"><span>{header}</span></div>'
        f'<label class="elicit-question">Anything?</label><div class="elicit-pills">{pills}</div></form>'
    )
    use = {"type": "tool_use", "id": "toolu_w", "name": "mcp__visualize__show_widget", "input": {"widget_code": code}}
    return _assistant(use)


_SHOWN = _result("toolu_w", "Content rendered and shown to the user.")


def _form_on(monkeypatch: pytest.MonkeyPatch, mod: Any) -> None:
    reader = _load("_form_reply")
    reader.FORM_REPLY_ENABLED = True
    monkeypatch.setattr(mod, "_form_reply", lambda: reader)


def test_an_answered_form_does_not_count_while_the_form_reader_is_off(tmp_path: Path) -> None:
    rows = [
        *_start("financial-model-review"),
        _form(_labels("fmr_extracted_values")),
        _SHOWN,
        _user("Review — Values: ok"),
    ]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review") is not None


@pytest.mark.parametrize(
    "reply",
    [
        "Review — Extracted values: The values look right, proceed",
        "Review details \u2013 Extracted values: The values look right, proceed",
        "(Skipped the form — proceed with defaults or ask me in plain text)",
    ],
)
def test_an_answered_form_counts_once_the_form_reader_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    mod = _load()
    _form_on(monkeypatch, mod)
    rows = [*_start("financial-model-review"), _form(_labels("fmr_extracted_values")), _SHOWN]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review", mod) is not None, "unanswered: held"
    assert _decide(tmp_path, [*rows, _user(reply)], "CHECKLIST", "financial-model-review", mod) is None


def test_a_form_reply_to_another_header_is_not_its_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    _form_on(monkeypatch, mod)
    rows = [*_start("financial-model-review"), _form(_labels("fmr_extracted_values")), _SHOWN, _user("Other — x")]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review", mod) is not None


# --- the window --------------------------------------------------------------------------------------


def test_a_question_before_the_skill_was_started_does_not_count(tmp_path: Path) -> None:
    rows = [_user("Earlier."), *_asked(_labels("ms_methodology")), *_start("market-sizing")]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None


def test_a_new_invocation_starts_a_new_window_and_budget(tmp_path: Path) -> None:
    first = [*_start("market-sizing"), *_asked(_labels("ms_methodology"))]
    assert _decide(tmp_path, first, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    again = [*first, _user("Now size Europe."), _skill("market-sizing")]
    reason = _reason(_decide(tmp_path, again, "TOP_DOWN_METHODOLOGY", "market-sizing"))
    held = [*first, _result("toolu_x", reason, is_error=True), _user("Now size Europe."), _skill("market-sizing")]
    assert _decide(tmp_path, held, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None, "an earlier hold is spent"


def test_a_question_in_an_earlier_message_of_the_same_invocation_counts(tmp_path: Path) -> None:
    rows = [*_start("market-sizing"), *_asked(_labels("ms_methodology")), _user("Use the US only."), _text("Sizing.")]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None


def test_no_invocation_found_reads_the_whole_transcript(tmp_path: Path) -> None:
    rows = [_user("Run it.\nFS_HOST_ANSWER ms_methodology=looks_good\n"), _user("Continue."), _text("Going on.")]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    assert (
        _decide(tmp_path, [_user("Run it."), _text("Going on.")], "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
    )


def test_a_slash_command_starts_the_window(tmp_path: Path) -> None:
    command = {
        "type": "user",
        "message": {"role": "user", "content": "<command-name>/founder-skills:market-sizing</command-name>"},
    }
    rows = [_user("Earlier."), *_asked(_labels("ms_methodology")), command]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
    rows = [command, *_asked(_labels("ms_methodology"))]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None


def test_a_command_name_a_tool_returned_is_not_an_invocation(tmp_path: Path) -> None:
    mod = _load("dispatch_type_check")
    returned = _result("toolu_r", "<command-name>/founder-skills:market-sizing</command-name>")
    assert mod.invocations([returned]) == []
    assert mod.started_skills([returned]) == {"market-sizing"}, "the agent check keeps its wider reading"
    rows = [*_start("market-sizing"), *_asked(_labels("ms_methodology")), returned]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None


def test_the_runs_id_anchors_the_window_before_a_later_invocation(tmp_path: Path) -> None:
    """The first message naming the run starts the window, so a question asked before the model started
    the skill again in a later message of the same run still counts."""
    for opener in (
        [_user(f"Size Acme.\nFS_HOST_RUN_ID={RUN_ID}\n"), _skill("market-sizing")],
        [
            _user("Size Acme."),
            _skill("market-sizing"),
            *_shell(
                'python3 "$SHARED/run_status.py" start --skill market-sizing --artifacts-root A',
                "toolu_st",
                json.dumps({"run_id": RUN_ID, "status": "running"}),
            ),  # fmt: skip
        ],
    ):
        rows = [*opener, *_asked(_labels("ms_methodology")), _user("Also Europe."), _skill("market-sizing")]
        assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    other = [
        _user("Size Acme.\nFS_HOST_RUN_ID=r-other\n"),
        *_asked(_labels("ms_methodology")),
        _user("x"),
        _skill("market-sizing"),
    ]
    assert _decide(tmp_path, other, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None


def test_a_compaction_summary_is_never_the_windows_start(tmp_path: Path) -> None:
    summary = {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "Summary of earlier."}}
    rows = [*_start("market-sizing"), *_asked(_labels("ms_methodology")), summary, _skill("market-sizing")]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None


# --- flows that must not be stranded -----------------------------------------------------------------


def test_corrections_typed_in_a_later_message_pass(tmp_path: Path) -> None:
    labels = _labels("fmr_extracted_values")
    rows = [
        *_start("financial-model-review"),
        *_asked(labels),
        _text("Send me the corrections."),
        _user("MRR is 45000, cash 1.2M."),
        *_shell('python3 "$SCRIPTS/apply_corrections.py" --set revenue.mrr=45000', "toolu_c", "{}"),
    ]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review") is None


def test_an_ic_write_up_finished_after_holding_off_passes(tmp_path: Path) -> None:
    labels = _labels("ic_decline_confirmation")
    rows = [*_start("ic-sim"), *_asked(labels), _text("Pausing here."), _user("OK, finish it."), _text("Composing.")]
    assert _decide(tmp_path, rows, "POST_COMPOSE_COACHING", "ic-sim") is None


def test_a_host_corrections_resume_passes(tmp_path: Path) -> None:
    resume = (
        f"Resume the financial-model-review run.\nFS_HOST_RUN_ID={RUN_ID}\n"
        "FS_HOST_ANSWER fmr_extracted_values=corrections_applied\n"
    )
    rows = [*_start("financial-model-review"), _text("Waiting."), _user(resume), _skill("financial-model-review")]
    assert _decide(tmp_path, rows, "CHECKLIST", "financial-model-review") is None


def test_a_pre_answered_unattended_run_is_not_held(tmp_path: Path) -> None:
    rows = [
        _user(f"Size Acme.\nFS_HOST_RUN_ID={RUN_ID}\nFS_HOST_ANSWER ms_methodology=looks_good\n"),
        _skill("market-sizing"),
    ]
    assert _decide(tmp_path, rows, "BOTTOM_UP_METHODOLOGY", "market-sizing") is None


def test_a_resume_in_a_new_session_with_the_lines_repeated_passes(tmp_path: Path) -> None:
    resume = f"Resume the ic-sim run.\nFS_HOST_RUN_ID={RUN_ID}\nFS_HOST_ANSWER ic_decline_confirmation=finish\n"
    assert _decide(tmp_path, [_user(resume), _skill("ic-sim")], "POST_COMPOSE_COACHING", "ic-sim") is None


# --- market-sizing: one hold for both questions ------------------------------------------------------

_ALTERNATIVES = {"arpu": [{"value": 311, "period": "month", "label": "list rate"}]}


def _figures(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, "market-sizing")
    inputs = {"founder_stated_inputs": {"arpu": 157}, "founder_stated_alternatives": _ALTERNATIVES}
    (run / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")


def _figures_asked() -> list[dict[str, Any]]:
    return _asked(["$157 per month", "$311 per month"], call_id="toolu_f", question="Which ARPU should I use?")


def _wrapper(tmp_path: Path, rows: list[dict[str, Any]], mod: Any = None) -> str | None:
    """Both checks as the runner runs them: the asked-gate check (every row enabled, or `mod`), then the
    figures check, first hold wins."""
    payload = _payload(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing")
    asked = mod or _load()
    decision = asked.decide(payload)
    if decision is None:
        decision = _load("two_figures_check").decide(payload)
    return None if decision is None else _reason(decision)


def test_methodology_asked_and_figures_offered_passes(tmp_path: Path) -> None:
    _figures(tmp_path)
    assert _wrapper(tmp_path, [*_start("market-sizing"), *_asked(_labels("ms_methodology")), *_figures_asked()]) is None


def test_methodology_asked_and_figures_not_offered_is_the_figures_hold_alone(tmp_path: Path) -> None:
    _figures(tmp_path)
    reason = _wrapper(tmp_path, [*_start("market-sizing"), *_asked(_labels("ms_methodology"))])
    assert (
        reason is not None and reason.startswith("[two-figures-check][TOP_DOWN_METHODOLOGY]") and MARKER not in reason
    )


def test_neither_asked_is_one_hold_with_both_questions_and_both_markers(tmp_path: Path) -> None:
    _figures(tmp_path)
    reason = _wrapper(tmp_path, _start("market-sizing"))
    assert reason is not None
    assert reason.startswith(f"{MARKER}[market-sizing:TOP_DOWN_METHODOLOGY]")
    assert "[two-figures-check][TOP_DOWN_METHODOLOGY]" in reason and "$311" in reason
    retry = [*_start("market-sizing"), _result("toolu_x", reason, is_error=True)]
    assert _wrapper(tmp_path, retry) is None, "each check finds its own marker"


def test_methodology_not_asked_figures_offered_holds_without_the_figures_marker(tmp_path: Path) -> None:
    """The figures check did not hold, so its marker is not carried: a bare marker would spend its retry."""
    _figures(tmp_path)
    reason = _wrapper(tmp_path, [*_start("market-sizing"), *_figures_asked()])
    assert reason is not None and reason.startswith(MARKER) and "two-figures-check" not in reason
    retry = [*_start("market-sizing"), *_figures_asked(), _result("toolu_x", reason, is_error=True)]
    assert _wrapper(tmp_path, retry) is None


def test_methodology_not_asked_and_no_inputs_holds_the_methodology_alone(tmp_path: Path) -> None:
    reason = _wrapper(tmp_path, _start("market-sizing"))
    assert reason is not None and reason.startswith(MARKER) and "two-figures-check" not in reason


def test_a_retry_after_a_merged_hold_whose_figures_were_offered_since_passes(tmp_path: Path) -> None:
    _figures(tmp_path)
    reason = _wrapper(tmp_path, _start("market-sizing"))
    assert reason is not None
    retry = [*_start("market-sizing"), _result("toolu_x", reason, is_error=True), *_figures_asked()]
    assert _wrapper(tmp_path, retry) is None


# --- the reason --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("context", "agent", "gate"), ROW_CASES, ids=_IDS)
def test_the_reason_reads_as_plain_words(tmp_path: Path, context: str, agent: str, gate: str) -> None:
    reason = _reason(_decide(tmp_path, _start(agent), context, agent))
    text = re.sub(r"\[[a-z-]+-check\]\[[^\]]*\]", " ", reason)
    assert _founder_text.scan(text) == {"enums": [], "filenames": []}, text
    for token in (".py", ".json", "FS_HOST", "--", gate, "asked_evidence", "hook"):
        assert token not in text, token
    if gate == "ic_decline_confirmation":
        assert "do not dispatch and do not send the report; pause until they are ready" in text


# --- the record --------------------------------------------------------------------------------------


def _bound(tmp_path: Path, skill: str) -> tuple[Path, _run_status.RunPaths]:
    """A run with a ledger and a run dir bound to it, as `run_status.py start` + `bind` leave it."""
    root = tmp_path / "artifacts"
    run = _run_dir(tmp_path, skill)
    paths = _run_status.run_paths(str(root), RUN_ID)
    os.makedirs(paths.run_root, exist_ok=True)
    ledger = _gates.new_ledger(RUN_ID, skill, "cli")
    ledger["gates"] = {"x": 1}
    _run_status.atomic_write_json(paths.ledger, ledger)
    _run_status.write_run_ref(str(run), paths, skill)
    return run, paths


def _lines(run: Path) -> list[dict[str, Any]]:
    path = run / "handoff" / RUN_ID / "asked_evidence.jsonl"
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_every_decision_is_recorded_beside_the_runs_ref(tmp_path: Path) -> None:
    run, _paths = _bound(tmp_path, "market-sizing")
    reason = _reason(_decide(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing"))
    held = [*_start("market-sizing"), _result("toolu_x", reason, is_error=True)]
    assert _decide(tmp_path, held, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    asked = [*_start("market-sizing"), *_asked(_labels("ms_methodology"))]
    assert _decide(tmp_path, asked, "BOTTOM_UP_METHODOLOGY", "market-sizing") is None
    lines = _lines(run)
    assert [(x["decision"], x["passed_on"], x["evidence"]) for x in lines] == [
        ("hold", None, None),
        ("pass", "marker", None),
        ("pass", "evidence", "ask_user_question"),
    ]
    for x in lines:
        assert x["schema"] == "founder-skills/asked_evidence" and x["schema_version"] == 1
        assert x["run_id"] == RUN_ID and x["gate"] == "ms_methodology" and x["agent"] == "market-sizing"
        assert x["window"] == "invocation" and x["by"] == "asked_gate_check.py"
        assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$", x["at"])
    assert lines[2]["kinds"] == ["ask_user_question"] and lines[2]["context"] == "BOTTOM_UP_METHODOLOGY"


def test_every_kind_found_is_listed_strongest_first(tmp_path: Path) -> None:
    run, _paths = _bound(tmp_path, "market-sizing")
    labels = _labels("ms_methodology")
    rows = [
        _user("Size Acme.\nFS_HOST_ANSWER ms_methodology=looks_good\n"),
        _skill("market-sizing"),
        _text(f"{labels[0]} or {labels[1]}?"),
        *_asked(labels),
        _user("Go ahead."),
    ]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    (line,) = _lines(run)
    assert line["evidence"] == "ask_user_question"
    assert line["kinds"] == ["ask_user_question", "host_line", "plain_chat"]


def test_no_record_without_the_runs_ref_and_no_directory_is_made(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, "market-sizing")
    assert _decide(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
    assert _lines(run) == []
    payload = _payload(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing")
    payload["tool_input"]["prompt"] = _prompt("TOP_DOWN_METHODOLOGY", tmp_path / "nowhere")
    assert _load().decide(payload) is not None
    assert not (tmp_path / "nowhere").exists()


def test_an_unwritable_record_changes_no_decision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run, _paths = _bound(tmp_path, "market-sizing")
    folder = run / "handoff" / RUN_ID
    (folder / "asked_evidence.jsonl").mkdir()  # a directory where the file goes: the open fails
    assert _decide(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
    assert "evidence not recorded" in capsys.readouterr().err


def test_the_record_switch_writes_nothing(tmp_path: Path) -> None:
    run, _paths = _bound(tmp_path, "market-sizing")
    mod = _load()
    mod.RECORD = False
    assert _decide(tmp_path, _start("market-sizing"), "TOP_DOWN_METHODOLOGY", "market-sizing", mod) is not None
    assert _lines(run) == []


def _answer(paths: _run_status.RunPaths, skill: str, gate: str, answer_id: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Record an answer through the registry, as the recorder does; returns its `answered_at`. The held
    gates' predicates and binders belong to their skills' own steps, so here the gate is owed and binds
    nothing."""
    monkeypatch.setattr(_gates, "owed", lambda ctx, g, instance: True)
    monkeypatch.setattr(_gates, "_binding_now", lambda ctx, g, given, instance=None: None)
    status = _run_status.blank_status(skill, paths)
    status["run_dir_shell"] = str(Path(paths.artifacts_root) / f"{skill}-acme")
    status["mode"] = "full"
    _run_status.write_status(paths, status)
    _run_status.atomic_write_json(paths.ledger, _gates.new_ledger(paths.run_id, skill, "cli"))

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> Any:
        _gates.open_gates(ctx, ledger, [gate])
        return _gates.record(ctx, ledger, gate, answer_ids=[answer_id])

    _gates.transact(paths, fn, skill=skill)
    answered_at: str = _gates.load_ledger(paths)["gates"][gate]["current"]["answered_at"]
    return answered_at


def test_the_record_carries_the_answer_it_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, paths = _bound(tmp_path, "market-sizing")
    answered_at = _answer(paths, "market-sizing", "ms_methodology", "looks_good", monkeypatch)
    rows = [*_start("market-sizing"), *_asked(_labels("ms_methodology"))]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is None
    (line,) = _lines(run)
    assert line["answered_at"] == answered_at


def test_the_ledger_is_found_as_the_run_status_finds_it(tmp_path: Path) -> None:
    run, paths = _bound(tmp_path, "market-sizing")
    assert _run_status.locate_from_run_dir(str(run), RUN_ID) == paths
    ledger = _gates.new_ledger(RUN_ID, "market-sizing", "cli")
    ledger["gates"] = {"ms_methodology": {"current": {"answered_at": "2026-01-02T03:04:05.000000Z"}}}
    _run_status.atomic_write_json(paths.ledger, ledger)
    assert _load()._ledger_answered_at(str(run), RUN_ID, "ms_methodology") == "2026-01-02T03:04:05.000000Z"
    (run / "handoff" / RUN_ID / "run_ref.json").write_text('{"run_id": "r-acme-1", "ledger_rel": "../x"}')
    assert _load()._ledger_answered_at(str(run), RUN_ID, "ms_methodology") is None


def test_a_marker_quoted_in_expanded_text_or_a_notification_does_not_spend_the_retry(tmp_path: Path) -> None:
    quoted = f"{MARKER}[market-sizing:TOP_DOWN_METHODOLOGY] Held once: an example."
    for row in (_user(quoted, isMeta=True), _notification(quoted)):
        assert _decide(tmp_path, [*_start("market-sizing"), row], "TOP_DOWN_METHODOLOGY", "market-sizing") is not None


def test_a_reply_or_run_id_line_in_a_notification_is_not_the_founders(tmp_path: Path) -> None:
    labels = _labels("ms_methodology")
    said = _text(f"Before I go on: {labels[0]}, or {labels[1]}?")
    rows = [*_start("market-sizing"), said, _notification("<task-notification>done</task-notification>")]
    assert _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
    anchored = [
        _user("Size Acme."),
        *_asked(labels),
        _notification(f"FS_HOST_RUN_ID={RUN_ID}"),
        _user("Also Europe."),
        _skill("market-sizing"),
    ]
    assert _decide(tmp_path, anchored, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None


def test_a_failed_start_call_does_not_anchor_the_run(tmp_path: Path) -> None:
    start = 'python3 "$SHARED/run_status.py" start --skill market-sizing --artifacts-root A'
    use = {"type": "tool_use", "id": "toolu_st", "name": "Bash", "input": {"command": start}}
    for is_error in (False, True):
        rows = [
            _user("Size Acme."),
            _skill("market-sizing"),
            _assistant(use),
            _result("toolu_st", json.dumps({"run_id": RUN_ID}), is_error=is_error),
            *_asked(_labels("ms_methodology")),
            _user("Also Europe."),
            _skill("market-sizing"),
        ]
        held = _decide(tmp_path, rows, "TOP_DOWN_METHODOLOGY", "market-sizing") is not None
        assert held is is_error


def test_deck_review_has_no_held_step() -> None:
    """Every deck-review gate is recorded by a script the skill runs (`gate_state.py`, `record_gate_answer.py`
    and `founder_context.py`), so no deck-review dispatch is held on the transcript."""
    rows = {**SHIPPED.PLANNED_ROWS, **SHIPPED.ROWS}
    assert all(_gates.GATES[gate]["skill"] != "deck-review" for gate in rows.values())
    assert all(agent != "deck-review" for (_context, agent) in rows)


# --- the question's last sentence ------------------------------------------------------------------------

_PREAMBLE = "I pulled the figures from your model into a page, and assumed the amounts are in dollars."


@pytest.mark.parametrize(
    ("asked", "labels", "passes"),
    [
        # A lead before the question no longer hides it; one of the gate's labels is still required.
        (f"{_PREAMBLE} Do the extracted values look right?", ["Looks right — proceed", "I'll fix it in chat"], True),
        (f"{_PREAMBLE} Do the values look right?", ["Looks right, proceed", "I'll upload a file"], True),
        (f"{_PREAMBLE}\nDo the extracted values look right?", ["Looks right, proceed", "Other"], True),
        # The question alone, with none of the labels, still never passes.
        (f"{_PREAMBLE} Do the extracted values look right?", ["Yes", "No"], False),
        # A last sentence that is not the gate's question does not count.
        (f"{_PREAMBLE} Should I go ahead?", ["Looks right, proceed", "No"], False),
    ],
)
def test_the_question_is_also_read_from_its_last_sentence(
    tmp_path: Path, asked: str, labels: list[str], passes: bool
) -> None:
    rows = [*_start("financial-model-review"), *_asked(labels, question=asked)]
    held = _decide(tmp_path, rows, "CHECKLIST", "financial-model-review")
    assert (held is None) is passes


def test_a_slotted_question_is_matched_as_before() -> None:
    """market-sizing's question has a slot; its match is the words around the slot, not the last sentence."""
    mod, form = _load(), _load("_form_reply")
    q = _gates.GATES["ms_methodology"]["question"]
    assert not mod.question_matches(form, f"{_PREAMBLE} Does this approach look right?", q)
