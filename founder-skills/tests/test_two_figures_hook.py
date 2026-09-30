"""`two_figures_check.py`: the PreToolUse hook that holds market-sizing's sizing dispatch once when
the founder's materials state two figures for one input and nobody asked which to use.

Measured on two live runs: `founder_stated_alternatives` was recorded, the question was never asked,
and the sizing went ahead. `founder_stated_choice` and `gate_defaults` cannot show that the question
was asked -- the model writes both. The transcript is written by the runtime, so the hook reads the
questions there. Exercised through the POSIX wrapper, with payloads shaped like the CLI's PreToolUse
input and transcripts shaped like the session JSONL (run 1 of the 2026-09-26 critique asked at T L78
and dispatched the sizing at L122-123).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
MARKER = "[two-figures-check]"

_ALTERNATIVES = {
    "arpu": [
        {"value": 317, "period": "month", "source": "document:deck.pdf#page=2", "label": "onboarding rate"},
        {"value": 261, "period": "month", "source": "document:deck.pdf#page=2", "label": "blended rate"},
    ]
}


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _question(*option_labels: str, question: str = "Which ARPU should the sizing use?") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "AskUserQuestion",
                    "input": {"questions": [{"question": question, "options": [{"label": x} for x in option_labels]}]},
                }
            ],
        },
    }


def _denied(reason: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "is_error": True, "content": reason}]},
    }


def _outputs(tmp_path: Path, alternatives: dict[str, Any] | None = _ALTERNATIVES, stated: Any = 157) -> Path:
    d = tmp_path / "outputs" / "artifacts" / "market-sizing-foo"
    d.mkdir(parents=True, exist_ok=True)
    inputs: dict[str, Any] = {"founder_stated_inputs": {"arpu": stated} if stated is not None else {}}
    if alternatives is not None:
        inputs["founder_stated_alternatives"] = alternatives
    (d / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    return d


def _run(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    prompt: str = "CONTEXT: BOTTOM_UP_METHODOLOGY\nOUTPUT_PATH: x",
    tool: str = "Agent",
    transcript: bool = True,
    cwd: str | None = "",
) -> subprocess.CompletedProcess[str]:
    """`cwd` defaults to the outputs dir; None leaves it out of the payload."""
    path = tmp_path / "t.jsonl"
    if transcript:
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload: dict[str, Any] = {
        "session_id": "s",
        "transcript_path": str(path),
        "cwd": str(tmp_path / "outputs") if cwd == "" else cwd,
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"prompt": prompt, "subagent_type": "founder-skills:market-sizing"},
    }
    if cwd is None:
        del payload["cwd"]
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _decision(r: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert r.returncode == 0, r.stderr
    out: dict[str, Any] = json.loads(r.stdout)["hookSpecificOutput"]
    return out


def _silent(r: subprocess.CompletedProcess[str]) -> None:
    assert r.returncode == 0 and r.stdout == "", r


# --- the measured failure: the question was never asked -------------------------------------------


def test_a_sizing_dispatch_with_unasked_alternatives_is_held_once(tmp_path: Path) -> None:
    _outputs(tmp_path)
    out = _decision(_run(tmp_path, [_user("Size my market.")]))
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert MARKER in reason
    # The reason is the question: every figure, the typed one first, and the way out.
    assert reason.index("$157") < reason.index("$317") < reason.index("$261")
    assert "onboarding rate" in reason and "blended rate" in reason
    assert "asked not to be asked" in reason
    # No file names or field names: the model narrates tool errors to the founder.
    for internal in ("inputs.json", "founder_stated", "gate_defaults", ".py"):
        assert internal not in reason, internal


def test_the_top_down_dispatch_is_held_too(tmp_path: Path) -> None:
    _outputs(tmp_path)
    r = _run(tmp_path, [_user("Size my market.")], prompt="CONTEXT: TOP_DOWN_METHODOLOGY\nOUTPUT_PATH: x")
    assert _decision(r)["permissionDecision"] == "deny"


def test_a_self_written_choice_does_not_count_as_asking(tmp_path: Path) -> None:
    """The model writes founder_stated_choice; on a live run it wrote one without asking."""
    d = _outputs(tmp_path)
    inputs = json.loads((d / "inputs.json").read_text())
    inputs["founder_stated_choice"] = {"arpu": "the $157 they gave"}
    (d / "inputs.json").write_text(json.dumps(inputs))
    assert _decision(_run(tmp_path, [_user("Size my market.")]))["permissionDecision"] == "deny"


def test_a_question_that_offers_only_the_typed_figure_does_not_count(tmp_path: Path) -> None:
    """Run 1's question, in shape: "$X/month … does this approach look right?" with no alternatives."""
    _outputs(tmp_path)
    rows = [_user("Size my market."), _question("Looks good", "Change methodology", question="Use $157/month?")]
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


# --- positive controls: without these the deny tests are vacuous ----------------------------------


def test_a_question_offering_every_figure_lets_the_dispatch_through(tmp_path: Path) -> None:
    _outputs(tmp_path)
    rows = [_user("Size my market."), _question("$157 per month (chat)", "$317/month (deck)", "$261 per month (deck)")]
    _silent(_run(tmp_path, rows))


def test_figures_in_the_question_text_count_as_offered(tmp_path: Path) -> None:
    _outputs(tmp_path)
    rows = [
        _user("Size my market."),
        _question("The one I typed", "The onboarding rate", "The blended rate", question="$157, $317 or $1,261.00?"),
    ]
    # 1,261 is not 261: a figure is matched whole, not as a digit run inside another number.
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"
    rows[-1] = _question("The one I typed", "The onboarding rate", "The blended rate", question="$157, $317 or $261?")
    _silent(_run(tmp_path, rows))


def test_the_second_dispatch_after_a_hold_goes_through(tmp_path: Path) -> None:
    """One retry: the founder may have asked not to be asked. The hook recognises its own reason in
    the transcript rather than trusting anything the model records."""
    _outputs(tmp_path)
    rows = [
        _user("Size my market, and don't ask me questions."),
        _denied(f"{MARKER}[BOTTOM_UP_METHODOLOGY] Before sizing, ask…"),
    ]
    _silent(_run(tmp_path, rows))


# --- nothing to enforce, or not ours: silent -----------------------------------------------------


def test_no_alternatives_is_silent(tmp_path: Path) -> None:
    _outputs(tmp_path, alternatives=None)
    _silent(_run(tmp_path, [_user("Size my market.")]))


def test_another_dispatch_is_silent(tmp_path: Path) -> None:
    _outputs(tmp_path)
    for prompt in ("CONTEXT: SENSITIVITY_TEST\nOUTPUT_PATH: x", "CONTEXT: POST_COMPOSE_COACHING\n", "summarise this"):
        _silent(_run(tmp_path, [_user("Size my market.")], prompt=prompt))


def test_another_tool_is_silent(tmp_path: Path) -> None:
    _outputs(tmp_path)
    _silent(_run(tmp_path, [_user("x")], tool="Bash"))


def test_missing_or_broken_inputs_fail_open(tmp_path: Path) -> None:
    _silent(_run(tmp_path, [_user("x")]))  # no inputs.json at all
    d = _outputs(tmp_path)
    (d / "inputs.json").write_text("{not json")
    _silent(_run(tmp_path, [_user("x")]))


def test_no_transcript_fails_open(tmp_path: Path) -> None:
    """Without the runtime's record the hook cannot tell asked from unasked, so it enforces nothing."""
    _outputs(tmp_path)
    _silent(_run(tmp_path, [], transcript=False))


def test_garbage_stdin_fails_open() -> None:
    r = subprocess.run(["sh", str(WRAPPER)], input="not json", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""


# --- from the first live firing (2026-09-26, fixed1 L145-153) -------------------------------------


def test_one_dispatchs_hold_does_not_spend_the_others_retry(tmp_path: Path) -> None:
    """TOP_DOWN was held; BOTTOM_UP, dispatched in parallel, then passed on TOP_DOWN's marker and the
    model re-sent TOP_DOWN without asking. Each sizing dispatch has its own retry."""
    _outputs(tmp_path)
    held_top_down = _denied(f"{MARKER}[TOP_DOWN_METHODOLOGY] Held once: …")
    r = _run(tmp_path, [_user("Size my market."), held_top_down], prompt="CONTEXT: BOTTOM_UP_METHODOLOGY\nx")
    assert _decision(r)["permissionDecision"] == "deny"
    _silent(_run(tmp_path, [_user("Size my market."), held_top_down], prompt="CONTEXT: TOP_DOWN_METHODOLOGY\nx"))


def test_the_reason_names_only_the_figures_not_yet_offered(tmp_path: Path) -> None:
    """The founder had been asked $157 vs $261; the reason said they had "not been asked", and the
    model read it as its recorded choice not taking effect. Name what was left out."""
    _outputs(tmp_path)
    rows = [_user("Size my market."), _question("$157 per month", "$261 per month")]
    reason = _decision(_run(tmp_path, rows))["permissionDecisionReason"]
    assert "not been asked" not in reason
    assert "$317" in reason and "onboarding rate" in reason
    assert reason.index("$317") < reason.index("Ask")
    # The figures already offered are named as offered, so the question can include them again.
    assert "$157" in reason and "$261" in reason


# --- finding this run's inputs when the hook's cwd is not the outputs dir ---------------------------
# On current local Cowork the hook's cwd is `/private/var/empty` (every kept recording since the
# absolute-path resolver), so a glob under cwd finds nothing and the hold never fired. The dispatch
# being judged names its own directory: OUTPUT_PATH is `<analysis dir>/handoff/<run id>/<file>`.

_SYNTH_ALTERNATIVES = {"arpu": [{"value": 150, "period": "month", "label": "list price"}]}
_EMPTY_CWD = "/private/var/empty"


def _analysis(root: Path, name: str = "market-sizing-acme", alternatives: Any = _SYNTH_ALTERNATIVES) -> Path:
    d = root / "outputs" / "artifacts" / name
    d.mkdir(parents=True, exist_ok=True)
    inputs: dict[str, Any] = {"founder_stated_inputs": {"arpu": 120}}
    if alternatives is not None:
        inputs["founder_stated_alternatives"] = alternatives
    (d / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    return d


def _sizing(output_path: str, context: str = "BOTTOM_UP_METHODOLOGY") -> str:
    return f"CONTEXT: {context}\nOUTPUT_PATH: {output_path}\nRUN_ID: 20260101T000000Z\n"


def test_an_absolute_output_path_finds_inputs_when_cwd_is_elsewhere(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    prompt = _sizing(str(d / "handoff" / "20260101T000000Z" / "bottom_up_output.json"))
    out = _decision(_run(tmp_path, [_user("Size my market.")], prompt=prompt, cwd=_EMPTY_CWD))
    assert out["permissionDecision"] == "deny"
    assert "$120" in out["permissionDecisionReason"] and "$150" in out["permissionDecisionReason"]


def test_a_later_round_under_the_handoff_dir_is_found_too(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    prompt = _sizing(str(d / "handoff" / "20260101T000000Z" / "r2" / "top_down_output.json"), "TOP_DOWN_METHODOLOGY")
    assert _decision(_run(tmp_path, [_user("x")], prompt=prompt, cwd=_EMPTY_CWD))["permissionDecision"] == "deny"


def test_a_relative_output_path_is_resolved_against_cwd(tmp_path: Path) -> None:
    _analysis(tmp_path)
    prompt = _sizing("artifacts/market-sizing-acme/handoff/20260101T000000Z/bottom_up_output.json")
    r = _run(tmp_path, [_user("x")], prompt=prompt, cwd=str(tmp_path / "outputs"))
    assert _decision(r)["permissionDecision"] == "deny"


def test_no_cwd_with_an_absolute_output_path_still_holds(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    prompt = _sizing(str(d / "handoff" / "20260101T000000Z" / "bottom_up_output.json"))
    assert _decision(_run(tmp_path, [_user("x")], prompt=prompt, cwd=None))["permissionDecision"] == "deny"


def test_this_runs_inputs_decide_not_a_newer_neighbour(tmp_path: Path) -> None:
    """Another market-sizing dir under the same outputs root, newer and with unasked figures, is not
    this run's: the path the dispatch names wins over the newest-by-mtime glob."""
    d = _analysis(tmp_path, alternatives=None)
    decoy = _analysis(tmp_path, name="market-sizing-other")
    later = (d / "inputs.json").stat().st_mtime + 60
    os.utime(decoy / "inputs.json", (later, later))
    prompt = _sizing(str(d / "handoff" / "20260101T000000Z" / "bottom_up_output.json"))
    _silent(_run(tmp_path, [_user("x")], prompt=prompt, cwd=str(tmp_path / "outputs")))


def test_the_hold_is_still_once_under_the_new_locator(tmp_path: Path) -> None:
    d = _analysis(tmp_path)
    prompt = _sizing(str(d / "handoff" / "20260101T000000Z" / "bottom_up_output.json"))
    first = _decision(_run(tmp_path, [_user("x")], prompt=prompt, cwd=_EMPTY_CWD))
    held = _denied(first["permissionDecisionReason"])
    _silent(_run(tmp_path, [_user("x"), held], prompt=prompt, cwd=_EMPTY_CWD))


def test_a_sizing_dispatch_with_no_inputs_anywhere_says_so_on_stderr(tmp_path: Path) -> None:
    """Still fails open, but no longer in silence: a hold that cannot run is visible in the hook log."""
    prompt = _sizing(str(tmp_path / "nowhere" / "handoff" / "20260101T000000Z" / "bottom_up_output.json"))
    r = _run(tmp_path, [_user("x")], prompt=prompt, cwd=_EMPTY_CWD)
    _silent(r)
    assert "two_figures_check" in r.stderr and "no inputs" in r.stderr


def test_a_non_sizing_dispatch_writes_nothing_to_stderr(tmp_path: Path) -> None:
    r = _run(tmp_path, [_user("x")], prompt="CONTEXT: SENSITIVITY_TEST\nOUTPUT_PATH: x", cwd=_EMPTY_CWD)
    _silent(r)
    assert r.stderr == ""
