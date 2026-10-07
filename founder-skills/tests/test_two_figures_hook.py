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
    payload = _payload(tmp_path, rows, prompt, tool, transcript, cwd)
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _payload(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    prompt: str = "CONTEXT: BOTTOM_UP_METHODOLOGY\nOUTPUT_PATH: x",
    tool: str = "Agent",
    transcript: bool = True,
    cwd: str | None = "",
) -> dict[str, Any]:
    path = tmp_path / "t.jsonl"
    if prompt.lstrip().startswith(_SIZING):
        if not prompt.rstrip().endswith(_END):
            prompt = prompt.rstrip("\n") + "\n" + _END + "\n"
        rows = [*rows, *_chain(prompt)]
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
    return payload


# The rest of the PreToolUse chain, as a market-sizing run leaves it before a sizing dispatch: the Gate's
# question asked with the registry's labels (the asked-gate check holds the sizing otherwise), and the
# prompt printed by the generator (the dispatch-prompt check holds any other prompt). Every sizing dispatch
# below is sent exactly as printed, so neither check decides anything and the figures check is measured
# alone, in the real chain.
_END = "Do NOT write any file other than OUTPUT_PATH."
_METHODOLOGY_LABELS = ["Looks good", "Change methodology", "Correct or add data"]
_SIZING = ("CONTEXT: TOP_DOWN_METHODOLOGY", "CONTEXT: BOTTOM_UP_METHODOLOGY")


def _chain(prompt: str) -> list[dict[str, Any]]:
    sub = "top_down_methodology" if "TOP_DOWN" in prompt.split("\n", 1)[0] else "bottom_up_methodology"
    command = f'python3 "$SCRIPTS/dispatch_prompt.py" {sub} --run-id "$RUN_ID" --analysis-dir "$ANALYSIS_DIR"'
    asked = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_gate",
                    "name": "AskUserQuestion",
                    "input": {
                        "questions": [
                            {
                                "question": (
                                    "I'll size this both top-down and bottom-up — does this approach look right?"
                                ),
                                "options": [{"label": x} for x in _METHODOLOGY_LABELS],
                            }
                        ]
                    },
                }
            ],
        },
    }
    answered = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_gate", "content": "ok"}]},
    }
    gen = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"toolu_gen_{sub}", "name": "Bash", "input": {"command": command}}],
        },
    }
    printed = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"toolu_gen_{sub}", "content": prompt}],
        },
    }
    return [asked, answered, gen, printed]


def _alone(tmp_path: Path, rows: list[dict[str, Any]], prompt: str) -> dict[str, Any] | None:
    """The figures check by itself, for a dispatch the rest of the chain cannot pair with a printed prompt
    (no OUTPUT_PATH, or a context line that is not a line of its own): those checks would hold it first."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("two_figures_alone", SCRIPTS / "two_figures_check.py")
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "session_id": "s",
        "transcript_path": str(path),
        "cwd": str(tmp_path / "outputs"),
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": {"prompt": prompt, "subagent_type": "founder-skills:market-sizing"},
    }
    out: dict[str, Any] | None = mod.decide(payload)
    return out


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
    rows = [_user("Size my market."), held_top_down]
    held = _alone(tmp_path, rows, "CONTEXT: BOTTOM_UP_METHODOLOGY\nx")
    assert held is not None and held["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _alone(tmp_path, rows, "CONTEXT: TOP_DOWN_METHODOLOGY\nx") is None


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


# --- Desktop's question form (2026-10-06) ------------------------------------------------------------
# On Desktop the first question is steered to a `show_widget` elicit form, not `AskUserQuestion`, and
# its answer arrives as a plain user message: "<header> — Label: value · …". The hook counted only
# `AskUserQuestion`, and the answer started a new request, so a founder who had chosen from all the
# figures saw both sizing dispatches held and the question asked again. Synthetic shapes below; the
# figures are invented.

_FORM_ALTERNATIVES = {
    "arpu": [
        {"value": 295, "period": "month", "label": "launch rate"},
        {"value": 233, "period": "month", "label": "averaged rate"},
    ]
}
_HEADER = "Market sizing details"
_DASH = "\u2014"
_ICON = '<svg viewBox="0 0 24 24"><path d="M3 12h18M12 3v18 L140 295 233 18.5"/></svg>'


def _pill(amount: str, note: str, value: str | None = None, attrs: str = "") -> str:
    return (
        f'<button type="button" class="elicit-pill" data-value="{value or amount}"{attrs} style="display:flex">'
        f'<i class="ti ti-tag" aria-hidden="true"></i><span><span>{amount}</span><br>'
        f'<span style="color:var(--text-muted)">{note}</span></span></button>'
    )


def _widget(*pills: str, header: str = f"<span>{_HEADER}</span>", extra: str = "", tool: str = "") -> dict[str, Any]:
    code = (
        '<h2 class="sr-only">Two questions before sizing.</h2>\n<form class="elicit">'
        f'<div class="elicit-header">{_ICON}{header}</div><div class="elicit-body">'
        '<div class="elicit-group"><label class="elicit-question">Which market should I size?</label>'
        '<div class="elicit-pills" data-name="geography" data-multi="false">'
        '<button type="button" class="elicit-pill" data-value="US">US</button>'
        '<button type="button" class="elicit-pill" data-value="Other" data-other>Other</button></div>'
        '<input type="text" class="elicit-other" data-for="geography" placeholder="Which region?" hidden></div>'
        '<div class="elicit-group"><label class="elicit-question">Which price should the sizing use?</label>'
        f'<div class="elicit-pills" data-name="price" data-multi="false">{"".join(pills)}</div></div>{extra}</div>'
        '<div class="elicit-footer"><button type="button" class="elicit-skip">Skip</button>'
        '<button type="button" class="elicit-submit">Continue</button></div></form>'
    )
    return _show(code, tool or "mcp__visualize__show_widget")


def _show(code: str, tool: str = "mcp__visualize__show_widget") -> dict[str, Any]:
    use = {
        "type": "tool_use",
        "id": "toolu_w",
        "name": tool,
        "input": {"title": "market_sizing_details", "loading_messages": ["Building"], "widget_code": code},
    }
    return {"type": "assistant", "message": {"role": "assistant", "content": [use]}}


_SHOWN = {
    "type": "user",
    "message": {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_w",
                "content": [{"type": "text", "text": "Content rendered and shown to the user."}],
            }
        ],
    },
}
_ALL_PILLS = (
    _pill("$140 / month", "Typed in chat", "$140/month typed"),
    _pill("$295 / month", "Launch, months 1-3", "$295/month launch"),
    _pill("$233 / month", "Averaged", "$233/month averaged"),
)


def _answer(text: str = f"{_HEADER} {_DASH} Geography: US · Price: $233/month averaged") -> dict[str, Any]:
    """The answer as Desktop delivers it: a plain string, not a list of blocks."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _form_outputs(tmp_path: Path) -> Path:
    return _outputs(tmp_path, alternatives=_FORM_ALTERNATIVES, stated=140)


def _asked(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    return [_user("Size my market."), *rows]


def test_an_answered_form_offering_every_figure_lets_the_dispatch_through(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, _answer())))
    assert _alone(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, _answer()), "CONTEXT: TOP_DOWN_METHODOLOGY\nx") is None


def test_the_same_form_without_its_answer_is_held(tmp_path: Path) -> None:
    """The widget's result says "rendered and shown" at once; a dispatch in the same turn is before
    anyone chose."""
    _form_outputs(tmp_path)
    assert _decision(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN)))["permissionDecision"] == "deny"


def test_a_form_offering_only_some_figures_is_held_naming_the_missing(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS[:2]), _SHOWN, _answer())
    reason = _decision(_run(tmp_path, rows))["permissionDecisionReason"]
    assert "never offered: $233" in reason and "already offered: $140" in reason


def test_figures_only_in_attributes_or_svg_are_not_offered(tmp_path: Path) -> None:
    """Every figure is in the SVG path data and in a data-value; the visible text names one."""
    _form_outputs(tmp_path)
    pills = [_pill("$140 / month", "Typed"), _pill("The launch rate", "Early months", "$295/month")]
    pills.append(_pill("The averaged rate", "Blended", "$233/month"))
    assert _decision(_run(tmp_path, _asked(_widget(*pills), _SHOWN, _answer())))["permissionDecision"] == "deny"


def test_hidden_pills_and_comments_are_not_offered(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    for pills in (
        _ALL_PILLS[:2] + (_pill("$233 / month", "Averaged", attrs=" hidden"),),
        _ALL_PILLS[:2]
        + (_pill("$233 / month", "Averaged", attrs=' data-x="1"').replace("display:flex", "display: none"),),
        _ALL_PILLS[:2] + (_pill("<!-- $233 / month -->", "Averaged"), _pill("<template>$233</template>", "Blended")),
        _ALL_PILLS[:2] + (_pill("<style>i::after{content:'$233'}</style>Averaged", "Blended"),),
    ):
        rows = _asked(_widget(*pills), _SHOWN, _answer())
        assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny", pills


def test_figures_drawn_as_svg_text_are_not_offered(tmp_path: Path) -> None:
    """SVG text nodes reach the parser as data, unlike path attributes: only the svg rule keeps the
    third figure out."""
    _form_outputs(tmp_path)
    pills = _ALL_PILLS[:2] + (_pill("<svg><text>$233</text></svg>", "Averaged"),)
    assert _decision(_run(tmp_path, _asked(_widget(*pills), _SHOWN, _answer())))["permissionDecision"] == "deny"


def test_text_the_founder_cannot_see_is_not_offered(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    for third in (
        _pill("<details><summary>More</summary>$233 / month</details>", "Averaged", "averaged"),
        _pill("<textarea>$233 / month</textarea>", "Averaged", "averaged"),
        _pill("<noscript>$233 / month</noscript>", "Averaged", "averaged"),
        _pill('<span class="sr-only">$233 / month</span>', "Averaged", "averaged"),
        _pill('<span style="visibility: hidden">$233 / month</span>', "Averaged", "averaged"),
        _pill('<span aria-hidden="true">$233 / month</span>', "Averaged", "averaged"),
        _pill("<div hidden/>$233 / month", "Averaged", "averaged"),
    ):
        rows = _asked(_widget(*(_ALL_PILLS[:2] + (third,))), _SHOWN, _answer())
        assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny", third


def test_a_form_from_an_earlier_request_cannot_be_answered_later(tmp_path: Path) -> None:
    """Form offering every figure, then an unrelated request, then a message that happens to start
    with the form's header: the old form is not in the new request's window."""
    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS), _SHOWN, _user("Actually, start over with the deck."), _answer())
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_the_answer_may_match_an_earlier_form_of_the_same_turn(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    other = _widget(_pill("Yes", "Go"), header="<span>Timing details</span>")
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, other, _SHOWN, _answer())))


def test_an_answer_after_an_attached_file_block_is_still_the_answer(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    text = f"<uploaded_files>\n<file>deck.pdf</file>\n</uploaded_files>\n{_HEADER} {_DASH} Price: $233"
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, _answer(text))))


def test_an_answer_whose_header_differs_is_a_new_request(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS), _SHOWN, _answer(f"Pricing details {_DASH} Price: $233"))
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_an_en_dash_answer_is_a_new_request(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS), _SHOWN, _answer(f"{_HEADER} \u2013 Price: $233"))
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_the_skip_line_answers_the_form(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    skip = f"(Skipped the form {_DASH} proceed with defaults or ask me in plain text)"
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, _answer(skip))))


def test_an_answer_as_a_list_of_blocks_counts(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS), _SHOWN, _user(f"{_HEADER} {_DASH} Price: $233\nmore"))))


def test_a_header_with_an_entity_and_spacing_is_matched_as_rendered(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    header = "<span>\n  Market &amp; pricing\n   details </span>"
    rows = _asked(_widget(*_ALL_PILLS, header=header), _SHOWN, _answer(f"Market & pricing details {_DASH} Price: $233"))
    _silent(_run(tmp_path, rows))


def test_a_later_prompt_after_the_answer_still_starts_a_new_request(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS), _SHOWN, _answer(), _user("Actually, size Europe instead."))
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_the_retry_marker_is_found_across_a_form_answer(tmp_path: Path) -> None:
    """dispatch → hold → form → answer → re-dispatch: the answer does not hide the hold."""
    _form_outputs(tmp_path)
    held = _denied(f"{MARKER}[BOTTOM_UP_METHODOLOGY] Held once: …")
    _silent(_run(tmp_path, _asked(held, _widget(*_ALL_PILLS[:1]), _SHOWN, _answer())))
    _silent(_run(tmp_path, _asked(held, _widget(*_ALL_PILLS), _SHOWN, _answer())))


def test_a_scripted_form_is_not_an_offer(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    for extra in ("<script>void 0</script>", '<div onmouseover="x()"></div>'):
        rows = _asked(_widget(*_ALL_PILLS, extra=extra), _SHOWN, _answer())
        assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny", extra


def test_a_widget_that_is_not_an_elicit_form_is_not_an_offer(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    chart = f'<div class="chart"><span>{_HEADER}</span><p>$140, $295 and $233 per month</p>{_ICON}</div>'
    rows = _asked(_show(chart), _SHOWN, _answer())
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_another_servers_show_widget_counts_only_as_an_elicit_form(tmp_path: Path) -> None:
    _form_outputs(tmp_path)
    _silent(_run(tmp_path, _asked(_widget(*_ALL_PILLS, tool="mcp__other__show_widget"), _SHOWN, _answer())))
    rows = _asked(_widget(*_ALL_PILLS, tool="mcp__other__render"), _SHOWN, _answer())
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


# --- the form read as labels, the run dir, and a host line ---------------------------------------------


def _load_tf(path: Path, name: str = "two_figures_check_under_test") -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _block(row: dict[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = row["message"]["content"][0]
    return block


def test_the_form_parts_group_text_by_pill_and_keep_questions_apart() -> None:
    tf = _load_tf(SCRIPTS / "two_figures_check.py")
    nested = _pill('<span><span class="elicit-pill">$233</span> inner</span>', "Averaged", "averaged")
    header, pills, questions = tf.elicit_form_parts(_block(_widget(*_ALL_PILLS[:2], nested)))
    assert header == _HEADER
    assert questions == ["Which market should I size?", "Which price should the sizing use?"]
    joined = [" ".join(" ".join(p).split()) for p in pills]
    assert joined[:4] == ["US", "Other", "$140 / month Typed in chat", "$295 / month Launch, months 1-3"]
    # A pill inside a pill is its own group; its text is not counted twice.
    assert joined[4:] == ["inner Averaged", "$233"]
    assert tf.elicit_form(_block(_widget(*_ALL_PILLS[:2], nested)))[1] >= {140.0, 295.0, 233.0}


def test_the_form_parts_leave_out_what_the_founder_cannot_see() -> None:
    tf = _load_tf(SCRIPTS / "two_figures_check.py")
    pills = (
        _pill("Looks good", "Go"),
        _pill("Change it", "Hidden", attrs=" hidden"),
        _pill('<span aria-hidden="true">x</span>', "y", "y"),
    )
    _header, groups, _questions = tf.elicit_form_parts(_block(_widget(*pills)))
    assert [" ".join(" ".join(p).split()) for p in groups][2:] == ["Looks good Go", "y"]
    assert tf.elicit_form_parts(_block(_widget(*pills, extra="<script>x</script>"))) is None


_HEAD_CAPTURE = Path(__file__).resolve().parent / "fixtures" / "two_figures_head_capture.json"


def test_the_figures_are_read_as_before_the_label_grouping(tmp_path: Path) -> None:
    """The figures check is unchanged by reading the form as labels too: every recorded form, around each
    construct the parser treats specially, and every OUTPUT_PATH shape gives what the module gave before
    that change (recorded from it, in the fixture)."""
    tf = _load_tf(SCRIPTS / "two_figures_check.py")
    capture = json.loads(_HEAD_CAPTURE.read_text(encoding="utf-8"))
    forms = capture["forms"]
    assert len(forms) > 150 and sum(f["expected"] is None for f in forms) >= 10, "control: both kinds"
    for case in forms:
        got = tf.elicit_form(case["block"])
        assert (None if got is None else [got[0], sorted(got[1])]) == case["expected"], case["block"]
    root = tmp_path / "root"
    (root / "artifacts" / "market-sizing-acme" / "handoff" / "r1" / "r2").mkdir(parents=True)
    (root / "artifacts" / "market-sizing-acme" / "inputs.json").write_text("{}", encoding="utf-8")
    for case in capture["paths"]:
        cwd = None if case["cwd"] is None else str(root)
        got = tf.inputs_from_output_path(case["prompt"].replace("{root}", str(root)), cwd)
        assert (None if got is None else os.path.relpath(got, root)) == case["expected"], case["prompt"]


def test_the_run_dir_and_id_come_from_the_output_path(tmp_path: Path) -> None:
    tf = _load_tf(SCRIPTS / "two_figures_check.py")
    run = tmp_path / "artifacts" / "market-sizing-acme"
    assert tf.run_dir_from_output_path(f"CONTEXT: X\nOUTPUT_PATH: {run}/handoff/r-1/out.json", None) == (
        str(run),
        "r-1",
    )
    assert tf.run_dir_from_output_path(f"CONTEXT: X\nOUTPUT_PATH: {run}/handoff/r-1/r2/o.json", None) == (
        str(run),
        "r-1",
    )
    assert tf.run_dir_from_output_path(f"CONTEXT: X\nOUTPUT_PATH: {run}/handoff/o.json", None) == (str(run), None)
    rel = "CONTEXT: X\nOUTPUT_PATH: artifacts/market-sizing-acme/handoff/r-1/o.json"
    assert tf.run_dir_from_output_path(rel, str(tmp_path)) == (str(run), "r-1")
    assert tf.run_dir_from_output_path(rel, None) is None
    assert tf.run_dir_from_output_path("CONTEXT: X\nOUTPUT_PATH: x/o.json", str(tmp_path)) is None
    assert tf.inputs_from_output_path(f"CONTEXT: X\nOUTPUT_PATH: {run}/handoff/r-1/out.json", None) is None
    run.mkdir(parents=True)
    (run / "inputs.json").write_text("{}", encoding="utf-8")
    assert tf.inputs_from_output_path(f"CONTEXT: X\nOUTPUT_PATH: {run}/handoff/r-1/out.json", None) == str(
        run / "inputs.json"
    )


_HOST = "Size my market.\nFS_HOST_ANSWER ms_two_figures=typed\n"
_NOTE = (
    "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n<result>Done.\n"
    "FS_HOST_ANSWER ms_two_figures=typed\n</result>\n</task-notification>"
)


def test_a_host_answer_in_the_request_lets_the_dispatch_through(tmp_path: Path) -> None:
    _outputs(tmp_path)
    _silent(_run(tmp_path, [_user(_HOST)]))
    _silent(_run(tmp_path, [{"type": "user", "message": {"role": "user", "content": _HOST}}]))


def test_a_host_value_line_is_not_an_answer_to_this_gate(tmp_path: Path) -> None:
    _outputs(tmp_path)
    rows = [_user("Size my market.\nFS_HOST_VALUE ms_two_figures=typed | 317\n")]
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_a_host_answer_in_an_earlier_request_does_not_count(tmp_path: Path) -> None:
    _outputs(tmp_path)
    rows = [_user(_HOST), _user("Now size Europe instead.")]
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_a_host_line_anywhere_but_the_founders_message_does_not_count(tmp_path: Path) -> None:
    _outputs(tmp_path)
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": f"echo '{_HOST}'"}}
    for extra in (
        {"type": "assistant", "message": {"role": "assistant", "content": [use]}},
        {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": _HOST}]},
        },
        _user(_HOST, isMeta=True),
        _user(_HOST, isSidechain=True),
        {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": _HOST}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": _HOST}]}},
        # A background agent's result, delivered as a user row: the agent's text, not the founder's.
        {"type": "user", "origin": {"kind": "task-notification"}, "message": {"role": "user", "content": _NOTE}},
        {"type": "user", "message": {"role": "user", "content": _NOTE}},
    ):
        rows = [_user("Size my market."), extra]
        assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny", extra


def test_a_host_line_for_another_gate_does_not_count(tmp_path: Path) -> None:
    _outputs(tmp_path)
    rows = [_user("Size my market.\nFS_HOST_ANSWER ms_methodology=looks_good\nFS_HOST_ANSWER ms_two_figures_x=a\n")]
    assert _decision(_run(tmp_path, rows))["permissionDecision"] == "deny"


def test_a_sizing_line_with_an_invisible_prefix_or_a_suffix_is_still_a_sizing_dispatch(tmp_path: Path) -> None:
    _outputs(tmp_path)
    for prompt in (
        "​CONTEXT: BOTTOM_UP_METHODOLOGY\nOUTPUT_PATH: x",
        "\n  CONTEXT: TOP_DOWN_METHODOLOGY (round 2)\nOUTPUT_PATH: x",
        "CONTEXT:BOTTOM_UP_METHODOLOGY\nOUTPUT_PATH: x",
    ):
        got = _alone(tmp_path, [_user("Size my market.")], prompt)
        assert got is not None, prompt
        reason = got["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith(f"{MARKER}[") and "METHODOLOGY]" in reason, prompt
    assert _alone(tmp_path, [_user("Size my market.")], "CONTEXT: BOTTOM_UP_METHODOLOGYX\nOUTPUT_PATH: x") is None


def test_the_retry_of_a_suffixed_dispatch_finds_its_marker(tmp_path: Path) -> None:
    _outputs(tmp_path)
    held = _denied(f"{MARKER}[BOTTOM_UP_METHODOLOGY] Held once: …")
    assert (
        _alone(tmp_path, [_user("Size my market."), held], "CONTEXT: BOTTOM_UP_METHODOLOGY (r2)\nOUTPUT_PATH: x")
        is None
    )


def test_a_founders_message_with_an_origin_still_counts(tmp_path: Path) -> None:
    _outputs(tmp_path)
    _silent(_run(tmp_path, [_user(_HOST, origin={"kind": "human"})]))


def test_a_marker_quoted_in_a_skills_expanded_text_does_not_spend_the_retry(tmp_path: Path) -> None:
    _outputs(tmp_path)
    quoted = f"{MARKER}[BOTTOM_UP_METHODOLOGY] Held once: an example."
    for row in (
        _user(quoted, isMeta=True),
        {"type": "user", "origin": {"kind": "task-notification"}, "message": {"role": "user", "content": quoted}},
    ):
        assert _decision(_run(tmp_path, [_user("Size my market."), row]))["permissionDecision"] == "deny", row
