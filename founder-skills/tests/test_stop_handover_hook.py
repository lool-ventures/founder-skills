"""`stop_handover_check.py`: the Stop hook that sends the model back once when its closing
message does not carry the printed hand-over. Exercised through the POSIX wrapper as the runtime
invokes it, with stdin payloads shaped like the CLI's (2.1.278) and transcripts shaped like the
session JSONL: real prompts are `type: user` without `isMeta`; skill attachments and hook feedback
are `isMeta: true`; tool results are user turns carrying `tool_result` blocks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WRAPPER = SCRIPTS / "stop-handover-check.sh"

PRINTED = (
    "Here's your finished market sizing: [the written report](computer:///out/X.md) — it opens with the verdict.\n"
    "\n"
    "Your materials state TAM $80.0B; this analysis finds $7.0B (top-down) and $99.9B (bottom-up). "
    "Self-check: 100% (22/22 pass, 0 fail, 0 N/A)\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)
OWN_VERDICT = (
    "Here's your finished market sizing: [the written report](computer:///out/X.md).\n\n"
    "1. Your $80B TAM is about 11x what the top-down build supports.\n"
    "2. Recommendation: revisit the deck's market slide.\n"
)
# The follow-up's lead, pinned as a literal rather than imported: it is the sentence a founder reads,
# so a reword must be a deliberate edit here. It states provenance and precedence, never error --
# the rule cannot tell a wrong figure from a correct paraphrase, and blocks both.
LEAD = (
    "For the record, this is the summary as the analysis produced it; "
    "if a figure in my message above differs from one here, use the one here, "
    "and check any figure above that is not here against the report before relying on it:"
)


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _tool_result() -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": ""}]}}


def _assistant_text(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **extra}


def _assistant_call(name: str, command: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": {"command": command}}],
        },
    }


CLOSING_CMD = (
    'python3 "$SCRIPTS/closing_message.py" --report "/sessions/x/mnt/outputs/artifacts/market-sizing-foo/report.json"'
)


def _run(tmp_path: Path, rows: list[dict[str, Any]] | None, payload_extra: dict[str, Any] | None = None) -> Any:
    transcript = tmp_path / "t.jsonl"
    if rows is not None:
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path / "outputs"),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": rows[-1]["message"]["content"][0].get("text", "") if rows else "",
        **(payload_extra or {}),
    }
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def _handover(tmp_path: Path, text: str = PRINTED, sub: str = "artifacts", run: str = "market-sizing-foo") -> Path:
    d = tmp_path / "outputs" / sub / run
    d.mkdir(parents=True, exist_ok=True)
    p = d / "handover.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _rows_after_call(*after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _user("Use the market-sizing skill on this deck."),
        _user("Base directory for this skill: /x", isMeta=True),
        _assistant_call("Bash", "python3 market_sizing.py --stdin"),
        _tool_result(),
        _assistant_call("mcp__workspace__bash", CLOSING_CMD),
        _tool_result(),
        *after,
    ]


def test_verbatim_message_passes_silently(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text("Done!\n\n" + PRINTED)))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_own_verdict_is_blocked_with_a_correction(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert LEAD in out["reason"]
    assert PRINTED.rstrip() in out["reason"]
    assert "not sent whole" in out["reason"]


def test_text_before_a_trailing_tool_call_is_judged_too(tmp_path: Path) -> None:
    """On real runs present_files and TaskUpdate sit between the closing call and the final text;
    a verdict emitted before them is on screen and invisible to last_assistant_message."""
    _handover(tmp_path)
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        _assistant_call("mcp__cowork__present_files", "x"),
        _tool_result(),
        _assistant_text(PRINTED),
    )
    r = _run(tmp_path, rows, {"last_assistant_message": PRINTED})
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    # PRINTED is there whole, so this is the OTHER failure (a figure added around it) -- and it
    # gets the same lead: an addition can be wrong ("11x") or right, and the rule cannot tell.
    assert "was added around" in out["reason"]
    assert LEAD in out["reason"]


def test_second_stop_is_let_through(tmp_path: Path) -> None:
    """One rewrite is the budget: `stop_hook_active` true means the model already came back."""
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)), {"stop_hook_active": True})
    assert r.stdout == ""


def test_the_correction_the_reason_asks_for_satisfies_the_rule(tmp_path: Path) -> None:
    """After a block, the judged text restarts at the feedback turn: the model's latest attempt is
    what is checked, and the correction the reason dictates must pass it."""
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    reason = json.loads(r.stdout)["reason"]
    correction = reason[reason.index(LEAD) :]
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n" + reason}},
        _assistant_text(correction),
    )
    r2 = _run(tmp_path, rows)  # stop_hook_active deliberately False: the rule itself must pass
    assert r2.stdout == "", r2.stdout


def test_another_skills_stop_is_ignored(tmp_path: Path) -> None:
    _handover(tmp_path)
    rows = [
        _user("Review my deck."),
        _assistant_call("Bash", "python3 checklist.py"),
        _tool_result(),
        _assistant_text("Score: 71%."),
    ]
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_a_closing_call_from_an_earlier_prompt_does_not_trigger(tmp_path: Path) -> None:
    _handover(tmp_path)
    rows = _rows_after_call(_assistant_text(PRINTED)) + [
        _user("Thanks. What is 2+2?"),
        _assistant_text("4."),
    ]
    r = _run(tmp_path, rows)
    assert r.stdout == ""


def test_stop_feedback_turns_are_not_prompts(tmp_path: Path) -> None:
    """A hook's own feedback must not reset 'the current prompt', or the trigger call would fall
    before it and every later stop would read as another skill's."""
    _handover(tmp_path)
    rows = _rows_after_call(
        _assistant_text(OWN_VERDICT),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\nx"}},
        _assistant_text(OWN_VERDICT),
    )
    r = _run(tmp_path, rows)
    assert json.loads(r.stdout)["decision"] == "block"


def test_other_events_are_ignored(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)), {"hook_event_name": "SubagentStop"})
    assert r.stdout == ""


def test_missing_handover_fails_open_with_a_stderr_line(tmp_path: Path) -> None:
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


def test_vm_loop_cwd_layout_is_found(tmp_path: Path) -> None:
    _handover(tmp_path, sub="mnt/outputs/artifacts")
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert json.loads(r.stdout)["decision"] == "block"


def test_newest_handover_wins(tmp_path: Path) -> None:
    old = _handover(tmp_path, text="OLD RUN'S TEXT\n", run="market-sizing-old")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    _handover(tmp_path, run="market-sizing-new")
    r = _run(tmp_path, _rows_after_call(_assistant_text("Done!\n\n" + PRINTED)))
    assert r.stdout == "", r.stdout


def test_unreadable_transcript_falls_back_to_the_message_opener(tmp_path: Path) -> None:
    _handover(tmp_path)
    r = _run(tmp_path, None, {"last_assistant_message": OWN_VERDICT})
    assert json.loads(r.stdout)["decision"] == "block"
    r2 = _run(tmp_path, None, {"last_assistant_message": "Score: 71%."})
    assert r2.stdout == ""


@pytest.mark.parametrize("stdin", ["", "not json", "[1,2]"])
def test_garbage_stdin_exits_zero_silently_on_stdout(tmp_path: Path, stdin: str) -> None:
    r = subprocess.run(["sh", str(WRAPPER)], input=stdin, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""


def test_wrapper_is_posix_sh() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    for bashism in ("[[", "$(<", "<(", "function ", "local "):
        assert bashism not in text, bashism
    assert os.access(WRAPPER, os.X_OK)


# --- the transcript lags the Stop event (e2e 2026-09-27) --------------------------------------------


def test_a_final_text_not_yet_in_the_transcript_is_read_from_the_payload(tmp_path: Path) -> None:
    """The hook ran 65 ms after the final text was written, before it reached the transcript file; it
    judged an empty message and blocked a verbatim hand-over. The runtime also passes that text as
    `last_assistant_message`, so a transcript that does not end with it is completed from it."""
    _handover(tmp_path)
    rows = _rows_after_call(_assistant_call("TodoWrite", "x"), _tool_result())
    r = _run(tmp_path, rows, {"last_assistant_message": PRINTED})
    assert r.returncode == 0 and r.stdout == "", r


def test_a_lagging_transcript_still_blocks_a_rewritten_message(tmp_path: Path) -> None:
    """Positive control: the payload text is judged, not waved through."""
    _handover(tmp_path)
    rows = _rows_after_call(_assistant_call("TodoWrite", "x"), _tool_result())
    out = json.loads(_run(tmp_path, rows, {"last_assistant_message": OWN_VERDICT}).stdout)
    assert out["decision"] == "block"


def test_the_payload_text_is_not_added_when_the_transcript_holds_the_final_text(tmp_path: Path) -> None:
    """The transcript is the record of what the founder saw; the payload only fills the measured lag.
    A payload copy that differs (a truncation marker carries a count) must not be judged beside it."""
    _handover(tmp_path)
    rows = _rows_after_call(_assistant_text(PRINTED))
    r = _run(tmp_path, rows, {"last_assistant_message": "Here's your finished market sizing… [+812 chars]"})
    assert r.returncode == 0 and r.stdout == "", r


# --- competitive-positioning: the same rule, keyed on its own script and its own run directories ---

CP_PRINTED = (
    "Here's your finished competitive positioning analysis: [the written report](computer:///out/R.md)"
    " — where you stand against each competitor, and the evidence behind every placement.\n"
    "\n"
    "Acme sits behind two competitors on both axes of the map.\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)
CP_OWN_VERDICT = (
    "Here's your finished competitive positioning analysis: [the written report](computer:///out/R.md).\n\n"
    "Acme is ahead of the large incumbents on both axes.\n"
)
CP_CLOSING_CMD = (
    'python3 "$SCRIPTS/cp_closing_message.py" --report '
    '"/sessions/x/mnt/outputs/artifacts/competitive-positioning-foo/report.json"'
)


def _cp_rows_after_call(*after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _user("Use the competitive-positioning skill on this deck."),
        _assistant_call("mcp__workspace__bash", CP_CLOSING_CMD),
        _tool_result(),
        *after,
    ]


def test_cp_verbatim_hand_over_passes(tmp_path: Path) -> None:
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    r = _run(tmp_path, _cp_rows_after_call(_assistant_text("Done!\n\n" + CP_PRINTED)))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_cp_own_verdict_is_blocked_with_the_cp_hand_over(tmp_path: Path) -> None:
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    r = _run(tmp_path, _cp_rows_after_call(_assistant_text(CP_OWN_VERDICT)))
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "Acme sits behind two competitors" in out["reason"]


def test_cp_call_reads_only_cp_run_directories(tmp_path: Path) -> None:
    """A market-sizing hand-over on disk is not the one a CP call is judged against: with only it
    present, the CP stop finds no hand-over and fails open."""
    _handover(tmp_path)  # market-sizing-foo
    r = _run(tmp_path, _cp_rows_after_call(_assistant_text(CP_OWN_VERDICT)))
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


def test_market_sizing_call_reads_only_market_sizing_run_directories(tmp_path: Path) -> None:
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    r = _run(tmp_path, _rows_after_call(_assistant_text(OWN_VERDICT)))
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


def test_in_a_mixed_prompt_the_last_closing_call_decides(tmp_path: Path) -> None:
    _handover(tmp_path)
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    rows = _rows_after_call(
        _assistant_text(PRINTED),
        _assistant_call("mcp__workspace__bash", CP_CLOSING_CMD),
        _tool_result(),
        _assistant_text(CP_PRINTED),
    )
    r = _run(tmp_path, rows)
    assert r.stdout == "", r.stdout
    rows[-1] = _assistant_text(CP_OWN_VERDICT)
    r2 = _run(tmp_path, rows)
    assert "Acme sits behind two competitors" in json.loads(r2.stdout)["reason"]


def test_cp_unreadable_transcript_falls_back_to_the_cp_opener(tmp_path: Path) -> None:
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    r = _run(tmp_path, None, {"last_assistant_message": CP_OWN_VERDICT})
    assert json.loads(r.stdout)["decision"] == "block"


def _load_hook() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("stop_handover_check_under_test", SCRIPTS / "stop_handover_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("reverse", [False, True], ids=["table-order", "reversed"])
def test_a_script_name_never_selects_the_other_skill(reverse: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """`closing_message.py` is a substring of `cp_closing_message.py` and `fmr_closing_message.py`:
    matching by substring would route either call to market-sizing whenever market-sizing's row came
    first. Whole-name matching makes the result independent of the table's order."""
    mod = _load_hook()
    assert len(mod.SKILLS) == 3  # the reversal below is only a real reordering with every row present
    if reverse:
        monkeypatch.setattr(mod, "SKILLS", tuple(reversed(mod.SKILLS)))
    cp = mod.closing_call(_cp_rows_after_call(_assistant_text("x")))
    ms = mod.closing_call(_rows_after_call(_assistant_text("x")))
    fmr = mod.closing_call(_fmr_rows_after_call(_assistant_text("x")))
    assert cp is not None and cp[0] == "competitive-positioning"
    assert ms is not None and ms[0] == "market-sizing"
    assert fmr is not None and fmr[0] == "financial-model-review"


# --- the printed text, read from the transcript when no handover.txt is reachable -----------------
# Under the host-loop spawn newer Desktop uses, the hook's cwd is /var/empty: no handover.txt is under
# it, and a live run's rewritten hand-over went through unchecked. The closing call's own result in the
# transcript carries the same text, byte for byte on a measured run.


def _call_with_id(name: str, command: str, call_id: str) -> dict[str, Any]:
    row = _assistant_call(name, command)
    row["message"]["content"][0]["id"] = call_id
    return row


def _result_for(call_id: str, text: str, *, is_error: bool = False, as_string: bool = False) -> dict[str, Any]:
    content: Any = text if as_string else [{"type": "text", "text": text}]
    block = {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _rows_with_result(result: dict[str, Any], *after: dict[str, Any], cmd: str = CLOSING_CMD) -> list[dict[str, Any]]:
    return [
        _user("Use the market-sizing skill on this deck."),
        _call_with_id("mcp__workspace__bash", cmd, "toolu_close"),
        result,
        *after,
    ]


def test_with_no_handover_file_the_transcripts_printed_text_is_the_comparand(tmp_path: Path) -> None:
    rows = _rows_with_result(_result_for("toolu_close", PRINTED), _assistant_text(OWN_VERDICT))
    out = json.loads(_run(tmp_path, rows).stdout)
    assert out["decision"] == "block"
    assert PRINTED.rstrip() in out["reason"]
    rows[-1] = _assistant_text("Done!\n\n" + PRINTED)
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_a_closing_call_compounded_with_other_commands_is_sliced_to_the_hand_over(tmp_path: Path) -> None:
    """A recorded run put `cp`, an echo and `ls` in the same command as the closing script, and stderr
    lands after stdout: the hand-over is the slice from its opener to its closing offer."""
    noisy = "Deliverables copied:\n-rw-r--r-- 1 u u 75K X.md\n" + PRINTED + "Warning: could not write handover.txt\n"
    rows = _rows_with_result(_result_for("toolu_close", noisy), _assistant_text(PRINTED))
    r = _run(tmp_path, rows)
    assert r.stdout == "", r.stdout  # no false block from the noise around it
    rows[-1] = _assistant_text(OWN_VERDICT)
    reason = json.loads(_run(tmp_path, rows).stdout)["reason"]
    assert "Deliverables copied" not in reason and "Warning:" not in reason


def test_an_errored_compound_call_that_printed_the_hand_over_still_counts(tmp_path: Path) -> None:
    rows = _rows_with_result(
        _result_for("toolu_close", "[exit 1]\n" + PRINTED + "ls: x: No such file\n", is_error=True, as_string=True),
        _assistant_text(OWN_VERDICT),
    )
    assert json.loads(_run(tmp_path, rows).stdout)["decision"] == "block"


def test_a_cut_short_result_is_not_a_comparand(tmp_path: Path) -> None:
    """`| head -3` keeps the opener and drops the offer: judging against that would pass a message
    that drops lines. No closing offer, no slice -- fail open, as before."""
    cut = "\n".join(PRINTED.splitlines()[:3]) + "\n"
    rows = _rows_with_result(_result_for("toolu_close", cut), _assistant_text(cut))
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


def test_a_result_is_paired_to_its_call_only_by_a_real_id(tmp_path: Path) -> None:
    """A result with no tool_use_id is never the closing call's, even when the call has no id either."""
    rows = [
        _user("Use the market-sizing skill on this deck."),
        _assistant_call("mcp__workspace__bash", CLOSING_CMD),
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": PRINTED}]}},
        _assistant_text(OWN_VERDICT),
    ]
    r = _run(tmp_path, rows)
    assert r.stdout == "" and "no handover.txt" in r.stderr


def test_a_found_handover_file_is_still_what_is_judged_against(tmp_path: Path) -> None:
    """Where the file is reachable (CLI working dir, the cloud lane), behaviour is unchanged: the file
    is the comparand even when the transcript holds a different printed text."""
    _handover(tmp_path)
    other = PRINTED.replace("$7.0B", "$6.0B")
    rows = _rows_with_result(_result_for("toolu_close", other), _assistant_text(PRINTED))
    assert _run(tmp_path, rows).stdout == ""


def test_cp_with_no_handover_file_reads_the_cp_result(tmp_path: Path) -> None:
    rows = _rows_with_result(
        _result_for("toolu_close", "copied\n" + CP_PRINTED),
        _assistant_text(CP_OWN_VERDICT),
        cmd=CP_CLOSING_CMD,
    )
    assert "Acme sits behind two competitors" in json.loads(_run(tmp_path, rows).stdout)["reason"]


@pytest.mark.parametrize("skill", ["market-sizing", "competitive-positioning", "financial-model-review"])
def test_the_hooks_slice_ends_on_the_offer_both_scripts_print(skill: str) -> None:
    """The slice's end marker is the offer both closing scripts print last; a reword there would make
    every transcript read fail open, silently."""
    import importlib.util

    rel = {
        "market-sizing": "market-sizing/scripts/closing_message.py",
        "competitive-positioning": "competitive-positioning/scripts/cp_closing_message.py",
        "financial-model-review": "financial-model-review/scripts/fmr_closing_message.py",
    }[skill]
    path = Path(__file__).resolve().parents[1] / "skills" / rel
    spec = importlib.util.spec_from_file_location(f"closing_{skill}", path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    text = script.build({"verdict": "The verdict."}, [("the written report", "`/out/R.md`")])
    mod = _load_hook()
    opener = next(o for name, _t, _g, o in mod.SKILLS if name == skill)
    assert mod.printed_from_result(text, opener) == text


FMR_PRINTED = (
    "Here's your finished financial model review: [the written report](computer:///out/R.md)"
    " — every check scored, with the evidence behind it.\n"
    "\n"
    "Model Quality: needs work (62%). Base runway: 14 months (default alive: no).\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)
FMR_OWN_VERDICT = (
    "Here's your finished financial model review: [the written report](computer:///out/R.md).\n\n"
    "You have about 16 months of runway once the raise closes.\n"
)
FMR_CLOSING_CMD = (
    'python3 "$SCRIPTS/fmr_closing_message.py" --report '
    '"/sessions/x/mnt/outputs/artifacts/financial-model-review-foo/report.json"'
)


def _fmr_rows_after_call(*after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _user("Use the financial-model-review skill on this model."),
        _assistant_call("mcp__workspace__bash", FMR_CLOSING_CMD),
        _tool_result(),
        *after,
    ]


def test_fmr_verbatim_hand_over_passes(tmp_path: Path) -> None:
    _handover(tmp_path, text=FMR_PRINTED, run="financial-model-review-foo")
    r = _run(tmp_path, _fmr_rows_after_call(_assistant_text("Done.\n\n" + FMR_PRINTED)))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_fmr_own_runway_figure_is_blocked_with_the_fmr_hand_over(tmp_path: Path) -> None:
    """The defect this row exists for: the hand-over stated a runway the analysis never printed."""
    _handover(tmp_path, text=FMR_PRINTED, run="financial-model-review-foo")
    r = _run(tmp_path, _fmr_rows_after_call(_assistant_text(FMR_OWN_VERDICT)))
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "Base runway: 14 months" in out["reason"]


def test_fmr_call_reads_only_fmr_run_directories(tmp_path: Path) -> None:
    _handover(tmp_path, text=CP_PRINTED, run="competitive-positioning-foo")
    r = _run(tmp_path, _fmr_rows_after_call(_assistant_text(FMR_OWN_VERDICT)))
    assert r.returncode == 0 and r.stdout == "" and "no handover.txt" in r.stderr


# --- delivery: finished files linked but never attached ----------------------------------------------
# Live runs linked their deliverables with computer:// and never called the host's delivery tool; on the
# cloud lane a link is dead text and the file card is the only delivery. The check fires only when the
# host offered a delivery tool, a founder-skills report was built in this prompt, nothing failed after
# it, and the final message points at a deliverable.

COMPOSE_CMD = 'python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.json"'
LINKED = "Here is your review: [the written report](computer:///sessions/x/mnt/outputs/Review.md).\n"


def _snapshot(*tools: str) -> dict[str, Any]:
    return {
        "type": "attachment",
        "entrypoint": "local-agent",
        "attachment": {"type": "prompt_snapshot", "tools": [{"name": t, "description": ""} for t in tools]},
    }


def _delta(*names: str) -> dict[str, Any]:
    return {"type": "attachment", "attachment": {"type": "deferred_tools_delta", "addedNames": list(names)}}


def _deliver(call_id: str, tool: str = "mcp__cowork__present_files", *, is_error: bool = False) -> list[dict[str, Any]]:
    call = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": call_id, "name": tool, "input": {}}]},
    }
    return [call, _result_for(call_id, "ok", is_error=is_error)]


def _delivery_rows(
    *after: dict[str, Any], offered: tuple[str, ...] = ("mcp__cowork__present_files",), compose_error: bool = False
) -> list[dict[str, Any]]:
    return [
        _snapshot("mcp__workspace__bash", *offered),
        _user("Review this deck."),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}", is_error=compose_error),
        *after,
    ]


def test_linked_but_never_delivered_is_sent_back_to_attach(tmp_path: Path) -> None:
    out = json.loads(_run(tmp_path, _delivery_rows(_assistant_text(LINKED))).stdout)
    assert out["decision"] == "block"
    assert "mcp__cowork__present_files" in out["reason"] and "attach" in out["reason"]


def test_a_delivery_call_after_the_report_passes(tmp_path: Path) -> None:
    rows = _delivery_rows(*_deliver("toolu_d"), _assistant_text(LINKED))
    r = _run(tmp_path, rows)
    assert r.stdout == "" and r.stderr == "", r


@pytest.mark.parametrize("tool", ["SendUserFile", "mcp__cowork__present_files", "mcp__other__present_files_v2"])
def test_any_present_files_tool_or_send_user_file_counts(tmp_path: Path, tool: str) -> None:
    rows = _delivery_rows(*_deliver("toolu_d", tool), _assistant_text(LINKED), offered=(tool,))
    assert _run(tmp_path, rows).stdout == ""


def test_a_deferred_delivery_tool_counts_as_offered(tmp_path: Path) -> None:
    rows = _delivery_rows(_assistant_text(LINKED), offered=())
    rows.insert(1, _delta("SendUserFile"))
    assert "SendUserFile" in json.loads(_run(tmp_path, rows).stdout)["reason"]


def test_no_delivery_tool_offered_is_not_blocked(tmp_path: Path) -> None:
    assert _run(tmp_path, _delivery_rows(_assistant_text(LINKED), offered=())).stdout == ""


def test_no_evidence_of_the_tool_list_is_not_blocked(tmp_path: Path) -> None:
    rows = _delivery_rows(_assistant_text(LINKED))[1:]  # no snapshot row
    assert _run(tmp_path, rows).stdout == ""


def test_a_failed_guess_at_a_delivery_tool_is_not_evidence_it_exists(tmp_path: Path) -> None:
    rows = _delivery_rows(
        *_deliver("toolu_g", "mcp__workspace__present_files", is_error=True), _assistant_text(LINKED), offered=()
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_failed_delivery_call_is_not_a_delivery(tmp_path: Path) -> None:
    rows = _delivery_rows(*_deliver("toolu_d", is_error=True), _assistant_text(LINKED))
    assert json.loads(_run(tmp_path, rows).stdout)["decision"] == "block"


def test_a_message_that_links_no_deliverable_is_not_blocked(tmp_path: Path) -> None:
    """The run built its report and then stopped on purpose (a later step failed and the model said so):
    it links nothing, so nothing is asked of it."""
    rows = _delivery_rows(_assistant_text("The coaching step failed, so I stopped before delivering."))
    assert _run(tmp_path, rows).stdout == ""


def test_a_failed_step_after_the_report_is_not_blocked(tmp_path: Path) -> None:
    rows = _delivery_rows(
        _call_with_id("mcp__workspace__bash", 'python3 "$SHARED/insert_coaching.py" --report x', "toolu_ins"),
        _result_for("toolu_ins", "[exit 1]\nblocked", is_error=True),
        _assistant_text(LINKED),
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_failed_report_build_does_not_trigger(tmp_path: Path) -> None:
    assert _run(tmp_path, _delivery_rows(_assistant_text(LINKED), compose_error=True)).stdout == ""


def test_the_script_named_in_a_dispatch_prompt_does_not_trigger(tmp_path: Path) -> None:
    """compose_report.py appears in Agent and TaskCreate inputs; only a shell call runs it."""
    rows = [
        _snapshot("mcp__cowork__present_files"),
        _user("Review this deck."),
        _call_with_id("Agent", "then run compose_report.py", "toolu_a"),
        _result_for("toolu_a", "done"),
        _assistant_text(LINKED),
    ]
    assert _run(tmp_path, rows).stdout == ""


def test_the_plain_cli_is_never_asked_to_attach(tmp_path: Path) -> None:
    rows = _delivery_rows(_assistant_text(LINKED))
    rows[0]["entrypoint"] = "cli"
    rows.insert(1, _delta("SendUserFile"))
    assert _run(tmp_path, rows).stdout == ""


def test_a_delivery_before_the_report_does_not_count(tmp_path: Path) -> None:
    rows = _delivery_rows(_assistant_text(LINKED))
    rows[2:2] = _deliver("toolu_early")  # an inputs viewer presented before compose
    assert json.loads(_run(tmp_path, rows).stdout)["decision"] == "block"


def test_hand_over_and_delivery_failing_together_make_one_block_delivery_first(tmp_path: Path) -> None:
    rows = [
        _snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        *_rows_with_result(_result_for("toolu_close", PRINTED), _assistant_text(OWN_VERDICT)),
    ]
    out = json.loads(_run(tmp_path, rows).stdout)
    reason = out["reason"]
    assert out["decision"] == "block"
    assert reason.index("mcp__cowork__present_files") < reason.index(LEAD) < reason.index(PRINTED.splitlines()[0])


# On a cloud session the three closing scripts name each document by its label alone (the files arrive as
# cards there, and a printed path could not be opened), so the final message links no file. For a closing
# script's build the printed hand-over sent whole is what names the deliverables.
CLOUD_PRINTED = (
    "Here's your finished market sizing: the written report and the interactive page — the report opens "
    "with the verdict.\n"
    "\n"
    "Your materials state TAM $80.0B; this analysis finds $7.0B (top-down) and $99.9B (bottom-up).\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)


def _cloud_closer_rows(*after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        _user("Size this market."),
        _call_with_id("mcp__workspace__bash", CLOSING_CMD, "toolu_close"),
        _result_for("toolu_close", CLOUD_PRINTED),
        *after,
    ]


def test_a_cloud_closing_message_carrying_the_hand_over_is_asked_to_attach(tmp_path: Path) -> None:
    assert not _load_hook()._load_delivery()._DELIVERABLE.search(CLOUD_PRINTED), "control: no link or path in it"
    r = _run(tmp_path, _cloud_closer_rows(_assistant_text(CLOUD_PRINTED)))
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "mcp__cowork__present_files" in out["reason"] and "attach" in out["reason"]
    assert LEAD not in out["reason"], "the hand-over itself was sent whole; only the delivery is asked for"
    # The message names its documents by label and links nothing, so the reason may not say it links them.
    assert "links" not in out["reason"]
    assert "points the founder to the finished files" in out["reason"]


def test_a_cloud_closing_message_after_a_delivery_call_passes(tmp_path: Path) -> None:
    rows = _cloud_closer_rows(*_deliver("toolu_d"), _assistant_text(CLOUD_PRINTED))
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def _compose_deliver_close_rows(*between: dict[str, Any]) -> list[dict[str, Any]]:
    """The order the skills ask for: compose the report, deliver its files, then the closing script last,
    whose printed text is the final message."""
    return [
        _snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        _user("Size this market."),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        *between,
        _call_with_id("mcp__workspace__bash", CLOSING_CMD, "toolu_close"),
        _result_for("toolu_close", CLOUD_PRINTED),
        _assistant_text(CLOUD_PRINTED),
    ]


def test_a_delivery_before_the_closing_script_counts_for_the_report(tmp_path: Path) -> None:
    r = _run(tmp_path, _compose_deliver_close_rows(*_deliver("toolu_d")))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_with_no_delivery_before_or_after_the_closing_script_it_is_asked_to_attach(tmp_path: Path) -> None:
    out = json.loads(_run(tmp_path, _compose_deliver_close_rows()).stdout)
    assert out["decision"] == "block" and "attach" in out["reason"]


def test_a_delivery_before_the_compose_does_not_count(tmp_path: Path) -> None:
    rows = _compose_deliver_close_rows()
    rows[2:2] = _deliver("toolu_early")
    out = json.loads(_run(tmp_path, rows).stdout)
    assert out["decision"] == "block" and "attach" in out["reason"]


def test_a_retried_step_between_compose_and_closing_script_still_asks_to_attach(tmp_path: Path) -> None:
    """The coaching chain between compose and the closer retries by design (a hand-off gate's exit 3,
    a verification re-run); a failure there that the run recovered from does not excuse delivery."""
    failed = [
        _call_with_id("mcp__workspace__bash", 'python3 "$SHARED_SCRIPTS/check_handoff.py" x', "toolu_gate"),
        _result_for("toolu_gate", "exit 3", is_error=True),
    ]
    out = json.loads(_run(tmp_path, _compose_deliver_close_rows(*failed)).stdout)
    assert out["decision"] == "block" and "attach" in out["reason"]


def test_a_failure_after_the_closing_script_stops_the_ask(tmp_path: Path) -> None:
    rows = _compose_deliver_close_rows()
    rows[-1:-1] = [
        _call_with_id("mcp__workspace__bash", "ls /nonexistent", "toolu_late"),
        _result_for("toolu_late", "No such file", is_error=True),
    ]
    assert _run(tmp_path, rows).stdout == ""


def test_a_resumed_run_that_delivers_then_closes_passes(tmp_path: Path) -> None:
    """A prompt that only re-sends a report built earlier runs no compose: its delivery counts from the
    prompt's start."""
    rows = _cloud_closer_rows(_assistant_text(CLOUD_PRINTED))
    rows[2:2] = _deliver("toolu_d")
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_a_report_built_after_the_closing_script_is_judged_on_its_own_links(tmp_path: Path) -> None:
    """The hand-over counts for a closing script's build only: a report composed after it is the build
    the message must point at."""
    rows = _cloud_closer_rows(
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        _assistant_text(CLOUD_PRINTED),
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_closing_message_on_the_plain_cli_is_never_asked_to_attach(tmp_path: Path) -> None:
    rows = _cloud_closer_rows(_assistant_text(CLOUD_PRINTED))
    rows[0]["entrypoint"] = "cli"
    assert _run(tmp_path, rows).stdout == ""


def test_a_cloud_closing_message_is_not_asked_twice(tmp_path: Path) -> None:
    rows = _cloud_closer_rows(_assistant_text(CLOUD_PRINTED))
    assert _run(tmp_path, rows, {"stop_hook_active": True}).stdout == ""


def test_a_cloud_closing_message_without_the_hand_over_is_not_asked_to_attach(tmp_path: Path) -> None:
    """A message that neither links a file nor carries the printed hand-over names no deliverable (the
    hand-over check speaks to it instead)."""
    rows = _cloud_closer_rows(_assistant_text("The coaching step failed, so I stopped before delivering."))
    out = json.loads(_run(tmp_path, rows).stdout)
    assert "attach" not in out["reason"]


# --- the review page: a turn that ended waiting at financial-model-review's values check ---------------
# The question normally goes through AskUserQuestion, which keeps the turn open (the PreToolUse check
# covers that path). This ask covers the turn that ENDS at the gate -- the question asked in chat, or a
# host with no question tool -- with the page unsent. The fixtures key on the static build and on how the
# turn ended, never on the question's wording or options.

REVIEW_CMD = (
    'python3 "$SCRIPTS/review_inputs.py" "$REVIEW_DIR/inputs.json" --static "$REVIEW_DIR/review.html" '
    '--extraction-warnings "$REVIEW_DIR/extraction_validation.json"'
)
GATE_OPEN_CMD = 'python3 "$SCRIPTS/record_gate_answer.py" open --gate values_check --dir "$REVIEW_DIR"'
REVIEW_PAGE = "/sessions/x/mnt/outputs/artifacts/financial-model-review-acme/review.html"
WAITING = "I've built the review page. Please check the values and tell me whether they look right."


def _deliver_files(call_id: str, *paths: str, tool: str = "mcp__cowork__present_files") -> list[dict[str, Any]]:
    call = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": call_id, "name": tool, "input": {"files": [{"file_path": p} for p in paths]}}
            ],
        },
    }
    return [call, _result_for(call_id, "ok")]


def _asked(call_id: str, *, is_error: bool = False, answer: str = "ok") -> list[dict[str, Any]]:
    call = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": "AskUserQuestion", "input": {"questions": []}}],
        },
    }
    return [call, _result_for(call_id, answer, is_error=is_error)]


def _review_rows(
    *after: dict[str, Any], offered: tuple[str, ...] = ("mcp__cowork__present_files",), cmd: str = REVIEW_CMD
) -> list[dict[str, Any]]:
    return [
        _snapshot("mcp__workspace__bash", *offered),
        _user("Review this financial model."),
        _call_with_id("mcp__workspace__bash", cmd, "toolu_review"),
        _result_for("toolu_review", '{"ok": true, "mode": "static"}'),
        *after,
    ]


def _review_ask(tmp_path: Path, rows: list[dict[str, Any]], **extra: Any) -> str | None:
    r = _run(tmp_path, rows, extra or None)
    assert r.returncode == 0, r
    if not r.stdout:
        return None
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    return str(out["reason"]) if "review page" in out["reason"] else None


def test_review_built_gate_opened_turn_ends_waiting_page_unsent_asks_for_the_page_naming_the_question(
    tmp_path: Path,
) -> None:
    rows = _review_rows(
        _call_with_id("mcp__workspace__bash", GATE_OPEN_CMD, "toolu_gate"),
        _result_for("toolu_gate", '{"ok": true}'),
        _assistant_text(WAITING),
    )
    reason = _review_ask(tmp_path, rows)
    assert reason is not None
    assert "review.html" in reason and "mcp__cowork__present_files" in reason
    # The turn may have asked in chat or not asked at all, so the reason covers both.
    assert "then ask (or repeat) the question whether those values look right" in reason
    assert "your question" not in reason, "it may never have been asked"
    for word in ("finished", "complete", "done", "deliverable"):
        assert word not in reason.lower(), word


def test_a_page_built_and_left_unsent_with_no_gate_record_is_asked_for_too(tmp_path: Path) -> None:
    assert _review_ask(tmp_path, _review_rows(_assistant_text(WAITING))) is not None


def test_a_message_that_links_nothing_is_still_asked_for_the_page(tmp_path: Path) -> None:
    """The report's message-shape condition is not part of this ask: the turn waiting at the gate links
    no file and names no deliverable."""
    assert not _load_hook()._load_delivery()._DELIVERABLE.search(WAITING), "control: the message links nothing"
    assert _review_ask(tmp_path, _review_rows(_assistant_text(WAITING))) is not None


def test_a_page_sent_before_the_turn_ended_is_silent(tmp_path: Path) -> None:
    r = _run(tmp_path, _review_rows(*_deliver_files("toolu_d", REVIEW_PAGE), _assistant_text(WAITING)))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_a_delivery_of_another_file_does_not_send_the_page(tmp_path: Path) -> None:
    rows = _review_rows(*_deliver_files("toolu_d", "/sessions/x/mnt/outputs/Acme_Report.md"), _assistant_text(WAITING))
    assert _review_ask(tmp_path, rows) is not None


def test_a_question_put_through_the_question_tool_is_silent(tmp_path: Path) -> None:
    assert _run(tmp_path, _review_rows(*_asked("toolu_q"), _assistant_text("Thanks."))).stdout == ""


def test_a_question_the_question_check_held_is_not_a_question_asked(tmp_path: Path) -> None:
    rows = _review_rows(
        *_asked("toolu_q", is_error=True, answer="PreToolUse:AskUserQuestion hook error: [review-page-check] Held"),
        _assistant_text(WAITING),
    )
    assert _review_ask(tmp_path, rows) is not None


def test_review_built_question_answered_report_delivered_at_end_is_silent(tmp_path: Path) -> None:
    rows = _review_rows(
        *_deliver_files("toolu_d0", REVIEW_PAGE),
        *_asked("toolu_q"),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        *_deliver_files("toolu_d", "/sessions/x/mnt/outputs/Acme_Report.md"),
        _assistant_text(LINKED),
    )
    r = _run(tmp_path, rows)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def test_review_built_question_answered_page_never_sent_report_delivered_at_end_is_silent(tmp_path: Path) -> None:
    """Past the values check the page no longer matters: a report build after it ends this ask."""
    rows = _review_rows(
        *_asked("toolu_q"),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        *_deliver_files("toolu_d", "/sessions/x/mnt/outputs/Acme_Report.md"),
        _assistant_text(LINKED),
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_sent_review_page_does_not_satisfy_the_report_check(tmp_path: Path) -> None:
    rows = _review_rows(
        *_deliver_files("toolu_d0", REVIEW_PAGE),
        *_asked("toolu_q"),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        _assistant_text(LINKED),
    )
    out = json.loads(_run(tmp_path, rows).stdout)
    assert out["decision"] == "block" and "attach" in out["reason"] and "review page" not in out["reason"]


def test_a_sent_report_does_not_send_the_review_page(tmp_path: Path) -> None:
    """A delivery of an earlier report, after the page was built, is not the page's delivery."""
    rows = _review_rows(*_deliver_files("toolu_d", "/sessions/x/mnt/outputs/Acme_Report.md"), _assistant_text(WAITING))
    assert _review_ask(tmp_path, rows) is not None


def test_server_mode_is_never_asked_for_a_page(tmp_path: Path) -> None:
    server = REVIEW_CMD.replace('--static "$REVIEW_DIR/review.html"', '--workspace "$REVIEW_DIR"')
    assert _run(tmp_path, _review_rows(_assistant_text(WAITING), cmd=server)).stdout == ""


def test_no_delivery_tool_offered_is_never_asked_for_a_page(tmp_path: Path) -> None:
    assert _run(tmp_path, _review_rows(_assistant_text(WAITING), offered=())).stdout == ""


def test_the_plain_cli_is_never_asked_for_a_page(tmp_path: Path) -> None:
    rows = _review_rows(_assistant_text(WAITING))
    rows[0]["entrypoint"] = "cli"
    assert _run(tmp_path, rows).stdout == ""


def test_the_page_is_asked_for_once(tmp_path: Path) -> None:
    assert _run(tmp_path, _review_rows(_assistant_text(WAITING)), {"stop_hook_active": True}).stdout == ""


def test_a_gate_record_is_not_a_report_build() -> None:
    delivery = _load_hook()._load_delivery()
    assert delivery._BUILD.search(GATE_OPEN_CMD) is None
    assert delivery._BUILD.search('python3 "$SCRIPTS/record_gate_answer.py" answer --gate values_check') is None


def test_a_gate_record_alone_never_triggers_the_report_check(tmp_path: Path) -> None:
    rows = [
        _snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        _user("Review this financial model."),
        _call_with_id("mcp__workspace__bash", GATE_OPEN_CMD, "toolu_gate"),
        _result_for("toolu_gate", '{"ok": true}'),
        _assistant_text(LINKED),
    ]
    assert _run(tmp_path, rows).stdout == ""


def test_a_report_build_after_the_page_ends_the_ask_even_with_no_question(tmp_path: Path) -> None:
    rows = _review_rows(
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD, "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        *_deliver_files("toolu_d", "/sessions/x/mnt/outputs/Acme_Report.md"),
        _assistant_text(LINKED),
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_page_built_across_lines_and_left_unsent_is_asked_for(tmp_path: Path) -> None:
    continued = REVIEW_CMD.replace(" --static", " \\\n  --static").replace(" --extraction", " \\\n  --extraction")
    assert "\\\n" in continued, "control: the command is written across lines"
    assert _review_ask(tmp_path, _review_rows(_assistant_text(WAITING), cmd=continued)) is not None


def test_a_connected_folder_write_of_the_page_sends_it(tmp_path: Path) -> None:
    rows = _review_rows(
        *_deliver_files("toolu_d", REVIEW_PAGE, tool="mcp__remote-devices__device_commit_files"),
        _assistant_text(WAITING),
    )
    assert _run(tmp_path, rows).stdout == ""


def test_a_report_build_written_across_lines_still_triggers_the_report_check(tmp_path: Path) -> None:
    rows = [
        _snapshot("mcp__workspace__bash", "mcp__cowork__present_files"),
        _user("Review this deck."),
        _call_with_id("mcp__workspace__bash", COMPOSE_CMD.replace(" -o", " \\\n  -o"), "toolu_compose"),
        _result_for("toolu_compose", "{}"),
        _assistant_text(LINKED),
    ]
    assert json.loads(_run(tmp_path, rows).stdout)["decision"] == "block"
