"""`review_page_check.py`: the PreToolUse check that holds financial-model-review's values-check question
once when the review page it asks about was built and never sent.

Exercised through the POSIX wrapper the manifest names, with transcripts shaped like the session JSONL
(the same shapes `test_stop_handover_hook.py` uses). The fixtures key on the static build and on a
question being asked, never on the question's wording or its options: the gate's labels are
presentation and may change without these tests changing."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
TOOL = "mcp__cowork__present_files"
STATIC_CMD = (
    'python3 "$SCRIPTS/review_inputs.py" "$REVIEW_DIR/inputs.json" --static "$REVIEW_DIR/review.html" '
    '--extraction-warnings "$REVIEW_DIR/extraction_validation.json"'
)
SERVER_CMD = (
    'python3 "$SCRIPTS/review_inputs.py" "$REVIEW_DIR/inputs.json" --workspace "$REVIEW_DIR" '
    '--extraction-warnings "$REVIEW_DIR/extraction_validation.json" &'
)
GATE_OPEN_CMD = 'python3 "$SCRIPTS/record_gate_answer.py" open --gate values_check --dir "$REVIEW_DIR"'
COMPOSE_CMD = 'python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.json"'
PAGE = "/sessions/x/mnt/outputs/artifacts/financial-model-review-acme/review.html"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _snapshot(*tools: str, entrypoint: str = "local-agent") -> dict[str, Any]:
    return {
        "type": "attachment",
        "entrypoint": entrypoint,
        "attachment": {"type": "prompt_snapshot", "tools": [{"name": t, "description": ""} for t in tools]},
    }


def _call(name: str, tool_input: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}],
        },
    }


def _result(call_id: str, text: str, *, is_error: bool = False) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _shell(command: str, call_id: str, *, is_error: bool = False, out: str = "{}") -> list[dict[str, Any]]:
    return [_call("mcp__workspace__bash", {"command": command}, call_id), _result(call_id, out, is_error=is_error)]


def _deliver(call_id: str, *paths: str, tool: str = TOOL, is_error: bool = False) -> list[dict[str, Any]]:
    return [
        _call(tool, {"files": [{"file_path": p} for p in paths]}, call_id),
        _result(call_id, "ok", is_error=is_error),
    ]


def _question(labels: tuple[str, ...] = ("Yes", "No")) -> dict[str, Any]:
    return {
        "questions": [
            {
                "question": "Anything to check?",
                "header": "Check",
                "options": [{"label": lab, "description": ""} for lab in labels],
            }
        ]
    }


def _built(
    *after: dict[str, Any], offered: tuple[str, ...] = (TOOL,), build_error: bool = False
) -> list[dict[str, Any]]:
    return [
        _snapshot("mcp__workspace__bash", *offered),
        _user("Review this financial model."),
        _user("Base directory for this skill: /x", isMeta=True),
        *_shell(STATIC_CMD, "toolu_build", is_error=build_error),
        *after,
    ]


def _payload(tmp_path: Path, rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": "/var/empty",
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUserQuestion",
        "tool_input": _question(),
        "tool_use_id": "toolu_q",
        **extra,
    }


def _run(tmp_path: Path, rows: list[dict[str, Any]], **extra: Any) -> subprocess.CompletedProcess[str]:
    payload = _payload(tmp_path, rows, **extra)
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _held(r: subprocess.CompletedProcess[str]) -> str | None:
    assert r.returncode == 0, r
    if not r.stdout:
        return None
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return str(out["permissionDecisionReason"])


# --- holds -------------------------------------------------------------------------------------------


def test_a_question_after_an_unsent_review_page_is_held_once_naming_the_page_and_the_tool(tmp_path: Path) -> None:
    reason = _held(_run(tmp_path, _built()))
    assert reason is not None
    assert reason.startswith("[review-page-check]")
    assert "review.html" in reason and TOOL in reason
    assert "ask this question again" in reason


def test_a_gate_record_between_the_build_and_the_question_does_not_clear_the_hold(tmp_path: Path) -> None:
    """The values check's planned sequence opens a gate record after the build and before asking: that
    shell call is neither a delivery nor a later build, so the question is held exactly as without it."""
    rows = _built(*_shell(GATE_OPEN_CMD, "toolu_gate", out='{"ok": true}'))
    assert _held(_run(tmp_path, rows)) == _held(_run(tmp_path, _built()))
    assert _held(_run(tmp_path, rows)) is not None


def test_a_gate_record_call_is_never_held_itself(tmp_path: Path) -> None:
    """The check answers only the question tool; a shell call recording the gate goes through."""
    payload = _payload(tmp_path, _built(), tool_name="Bash", tool_input={"command": GATE_OPEN_CMD})
    assert _load("review_page_check").decide(payload) is None


@pytest.mark.parametrize(
    "labels",
    [
        ("I reviewed the page and the values look right", "I will upload corrections", "I will say in chat"),
        ("A", "B"),
        (),
    ],
)
def test_the_decision_does_not_depend_on_the_question_or_its_options(tmp_path: Path, labels: tuple[str, ...]) -> None:
    assert _held(_run(tmp_path, _built(), tool_input=_question(labels))) is not None
    rows = _built(*_deliver("toolu_d", PAGE))
    assert _held(_run(tmp_path, rows, tool_input=_question(labels))) is None


@pytest.mark.parametrize("tool", ["SendUserFile", "mcp__other__present_files_v2"])
def test_any_offered_delivery_tool_is_named(tmp_path: Path, tool: str) -> None:
    reason = _held(_run(tmp_path, _built(offered=(tool,))))
    assert reason is not None and tool in reason


def test_a_delivery_of_another_file_does_not_send_the_page(tmp_path: Path) -> None:
    rows = _built(*_deliver("toolu_d", "/sessions/x/mnt/outputs/Acme_Inputs.md"))
    assert _held(_run(tmp_path, rows)) is not None


def test_a_failed_delivery_does_not_send_the_page(tmp_path: Path) -> None:
    rows = _built(*_deliver("toolu_d", PAGE, is_error=True))
    assert _held(_run(tmp_path, rows)) is not None


def test_a_delivery_before_the_latest_build_does_not_send_the_rebuilt_page(tmp_path: Path) -> None:
    rows = _built(*_deliver("toolu_d", PAGE), *_shell(STATIC_CMD, "toolu_build2"))
    assert _held(_run(tmp_path, rows)) is not None


# --- silent ------------------------------------------------------------------------------------------


def test_a_page_sent_before_the_question_is_let_through(tmp_path: Path) -> None:
    r = _run(tmp_path, _built(*_deliver("toolu_d", PAGE)))
    assert _held(r) is None and r.stderr == "", r


def test_a_page_sent_under_another_name_is_matched_by_the_name_the_build_wrote(tmp_path: Path) -> None:
    rows = _built()
    rows[3] = _call(
        "mcp__workspace__bash", {"command": STATIC_CMD.replace("review.html", "values.html")}, "toolu_build"
    )
    assert "values.html" in str(_held(_run(tmp_path, rows)))
    rows += _deliver("toolu_d", "/out/values.html")
    assert _held(_run(tmp_path, rows)) is None


def test_the_second_question_after_a_hold_goes_through(tmp_path: Path) -> None:
    first = _held(_run(tmp_path, _built()))
    assert first is not None
    # The runtime records the denial as the question's error result, prefixed by its own label.
    rows = _built(
        _call("AskUserQuestion", _question(), "toolu_q1"),
        _result("toolu_q1", f"PreToolUse:AskUserQuestion hook error: {first}", is_error=True),
    )
    assert _held(_run(tmp_path, rows)) is None


def test_a_hold_in_an_earlier_prompt_does_not_spend_this_prompts_budget(tmp_path: Path) -> None:
    earlier = [
        _user("Review this financial model."),
        _call("AskUserQuestion", _question(), "toolu_q0"),
        _result("toolu_q0", "PreToolUse:AskUserQuestion hook error: [review-page-check] Held once", is_error=True),
    ]
    rows = _built()
    rows[1:1] = earlier
    assert _held(_run(tmp_path, rows)) is not None


def test_server_mode_writes_no_page_and_is_let_through(tmp_path: Path) -> None:
    rows = _built()
    rows[3] = _call("mcp__workspace__bash", {"command": SERVER_CMD}, "toolu_build")
    assert _held(_run(tmp_path, rows)) is None


def test_a_failed_build_is_let_through(tmp_path: Path) -> None:
    assert _held(_run(tmp_path, _built(build_error=True))) is None


def test_no_delivery_tool_offered_is_let_through(tmp_path: Path) -> None:
    assert _held(_run(tmp_path, _built(offered=()))) is None


def test_no_record_of_the_tool_list_is_let_through(tmp_path: Path) -> None:
    assert _held(_run(tmp_path, _built()[1:])) is None


def test_the_plain_cli_is_let_through(tmp_path: Path) -> None:
    rows = _built()
    rows[0] = _snapshot("Bash", TOOL, entrypoint="cli")
    assert _held(_run(tmp_path, rows)) is None


def test_another_skills_question_with_no_review_page_is_let_through(tmp_path: Path) -> None:
    rows = [
        _snapshot("mcp__workspace__bash", TOOL),
        _user("Size this market."),
        *_shell('python3 "$SCRIPTS/market_sizing.py" --stdin', "toolu_ms"),
    ]
    assert _held(_run(tmp_path, rows)) is None


def test_a_page_built_in_an_earlier_prompt_is_let_through(tmp_path: Path) -> None:
    rows = [*_built(), _user("Thanks. Now size the market for the same company.")]
    assert _held(_run(tmp_path, rows)) is None


def test_a_question_after_the_report_build_is_let_through(tmp_path: Path) -> None:
    """Past the values check the page no longer matters."""
    assert _held(_run(tmp_path, _built(*_shell(COMPOSE_CMD, "toolu_compose")))) is None


def test_the_build_named_inside_a_dispatch_prompt_is_not_a_build(tmp_path: Path) -> None:
    rows = _built()
    rows[3] = _call("Agent", {"prompt": STATIC_CMD, "subagent_type": "general-purpose"}, "toolu_build")
    assert _held(_run(tmp_path, rows)) is None


def test_a_missing_transcript_is_let_through_silently(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _built(), transcript_path=str(tmp_path / "absent.jsonl"))
    r = subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


# --- one process, two kinds of tool -------------------------------------------------------------------


def test_the_manifest_sends_dispatches_and_questions_to_the_hook() -> None:
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    entries = manifest["hooks"]["PreToolUse"]
    assert [e["matcher"] for e in entries] == ["Agent|Task|AskUserQuestion"]
    assert entries[0]["hooks"][0]["command"] == "${CLAUDE_PLUGIN_ROOT}/scripts/pretooluse-dispatch.sh"


@pytest.mark.parametrize("name", ["dispatch_type_check", "two_figures_check", "dispatch_prompt_check"])
def test_each_dispatch_check_returns_at_once_on_a_question(tmp_path: Path, name: str) -> None:
    """A question whose text looks exactly like a dispatch prompt is still not a dispatch."""
    prompt = "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/r2/redteam_output.json\nRead docs.\n"
    payload = _payload(tmp_path, _built(), tool_input={"prompt": prompt, "subagent_type": "general-purpose"})
    assert _load(name).decide(payload) is None


def test_the_question_check_returns_at_once_on_a_dispatch(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _built(), tool_name="Agent", tool_input={"prompt": "x", "subagent_type": "claude"})
    assert _load("review_page_check").decide(payload) is None
    payload["tool_name"] = "AskUserQuestion"
    assert _load("review_page_check").decide(payload) is not None, "control: the same transcript holds a question"


def test_the_runner_lists_the_question_check() -> None:
    assert "review_page_check" in _load("pretooluse_dispatch").CHECKS


# --- the page a command writes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "page"),
    [
        (STATIC_CMD, "review.html"),
        ('python3 review_inputs.py in.json --static "/a b/out/page.html"', "page.html"),
        ("python3 review_inputs.py in.json --static=/out/p.html", "p.html"),
        ('python3 review_inputs.py in.json --static "$OUT"', "review.html"),
        (SERVER_CMD, None),
        ('python3 review_inputs.py in.json --workspace d ; echo --static "x.html"', None),
        ('python3 "$SCRIPTS/record_gate_answer.py" open --static x.html', None),
        ("python3 my_review_inputs.py in.json --static x.html", None),
    ],
)
def test_the_page_a_command_writes(command: str, page: str | None) -> None:
    assert _load("_delivery_check").static_review_page(command) == page
