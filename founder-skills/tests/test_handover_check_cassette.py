"""cowork-tests/handover_check_cassette.py: a recorded run's final message carried the printed hand-over.

`hook_event_fired: Stop` passed on a recording whose final message was the model's own rewrite, made while
the Stop hook failed open with "no handover.txt" on its stderr. No harness assertion can see either fact,
so this checker reads the cassette with the hook's own logic (one owner) and fails on both.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "handover_check_cassette", _ROOT / "cowork-tests" / "handover_check_cassette.py"
)
assert _SPEC is not None and _SPEC.loader is not None
hcc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = hcc  # a dataclass needs its module registered while it is built
_SPEC.loader.exec_module(hcc)

_CASSETTES = _ROOT / "cowork-tests" / "cassettes"

OFFER = "If you want to keep the working data behind this — say so and I'll send it as a single archive."
PRINTED = {
    "market-sizing": (
        "closing_message.py",
        "Here's your finished market sizing: [the written report](computer:///o/R.md).\n\nTAM is $4.2B.\n\n"
        + OFFER
        + "\n",
    ),
    "competitive-positioning": (
        "cp_closing_message.py",
        "Here's your finished competitive positioning analysis: [the written report](computer:///o/R.md).\n\n"
        "Acme sits behind two competitors.\n\n" + OFFER + "\n",
    ),
    "financial-model-review": (
        "fmr_closing_message.py",
        "Here's your finished financial model review: [the written report](computer:///o/R.md).\n\n"
        "Model Quality: needs work (62%). Base runway: 14 months (default alive: no).\n\n" + OFFER + "\n",
    ),
}


def _ev(obj: dict[str, Any]) -> str:
    return json.dumps(obj)


def _call(script: str, cid: str = "toolu_close") -> str:
    return _ev(
        {
            "type": "assistant",
            "parent_tool_use_id": None,
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": cid,
                        "name": "mcp__workspace__bash",
                        "input": {"command": f'python3 "$SCRIPTS/{script}" --report "/o/report.json"'},
                    }
                ]
            },
        }
    )


def _result(text: str, cid: str = "toolu_close") -> str:
    return _ev(
        {
            "type": "user",
            "parent_tool_use_id": None,
            "message": {"content": [{"type": "tool_result", "tool_use_id": cid, "content": text}]},
        }
    )


def _say(text: str, *, sub: bool = False) -> str:
    return _ev(
        {
            "type": "assistant",
            "parent_tool_use_id": "toolu_task" if sub else None,
            "message": {"content": [{"type": "text", "text": text}]},
        }
    )


def _stop(stderr: str = "", exit_code: int = 0) -> str:
    return _ev(
        {
            "type": "system",
            "subtype": "hook_response",
            "hook_name": "Stop",
            "hook_event": "Stop",
            "stderr": stderr,
            "exit_code": exit_code,
        }
    )


def _feedback(text: str) -> str:
    return _ev({"type": "user", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": text}]}})


def _check(events: list[str]) -> Any:
    return hcc.check_events(events)


@pytest.mark.parametrize("skill", sorted(PRINTED))
def test_a_verbatim_hand_over_passes_for_every_skill_the_hook_knows(skill: str) -> None:
    script, printed = PRINTED[skill]
    r = _check([_call(script), _result(printed), _say("Done.\n\n" + printed), _stop()])
    assert r.outcome == "PASS" and r.skill == skill, r


def test_a_rewritten_hand_over_fails() -> None:
    script, printed = PRINTED["market-sizing"]
    rewrite = printed.replace("TAM is $4.2B.", "Your TAM comes to roughly $4B, a strong result.")
    r = _check([_call(script), _result(printed), _say(rewrite), _stop()])
    assert r.outcome == "FAIL" and any("not sent whole" in p for p in r.problems), r


def test_the_re_send_after_a_hook_block_is_what_is_judged() -> None:
    script, printed = PRINTED["market-sizing"]
    rewrite = printed.replace("TAM is $4.2B.", "Your TAM is about $4B.")
    events = [
        _call(script),
        _result(printed),
        _say(rewrite),
        _stop(exit_code=2),
        _feedback("Stop hook feedback: Your last message did not deliver the printed hand-over as written."),
        _say("For the record, this is the summary as the analysis produced it:\n\n" + printed),
        _stop(),
    ]
    assert _check(events).outcome == "PASS"


def test_a_stop_hook_that_found_no_hand_over_fails_even_when_the_message_is_verbatim() -> None:
    """The hook failing open is itself the defect: it checked nothing."""
    script, printed = PRINTED["market-sizing"]
    stderr = "stop_handover_check: market-sizing's closing message ran but no handover.txt under /x\n"
    r = _check([_call(script), _result(printed), _say(printed), _stop(stderr=stderr)])
    assert r.outcome == "FAIL" and any("no handover.txt" in p for p in r.problems), r


def test_sub_agent_text_is_not_the_founders_message() -> None:
    script, printed = PRINTED["financial-model-review"]
    r = _check([_call(script), _result(printed), _say(printed, sub=True), _say("All done."), _stop()])
    assert r.outcome == "FAIL", r


def test_a_run_with_no_closing_call_is_not_exercised() -> None:
    r = _check([_say("Here is your deck review."), _stop()])
    assert r.outcome == "NOT-EXERCISED", r


def test_a_closing_call_whose_result_holds_no_whole_hand_over_fails() -> None:
    script, printed = PRINTED["market-sizing"]
    r = _check([_call(script), _result("Error: cannot build the hand-over"), _say(printed), _stop()])
    assert r.outcome == "FAIL", r


def test_the_re_recorded_closing_lanes_deliver_their_hand_over() -> None:
    """The recording this checker was built on (market-sizing-remote-lane at 3.10.0) failed it for both
    reasons: the final message was the model's rewrite, and the Stop hook had failed open with "no
    handover.txt". Re-recorded at harness 4.0.0 under the fixed hook, it passes; so does
    financial-model-review-smoke, the first recording of its printed hand-over. The rewrite and fail-open
    cases stay covered by the synthetic tests above."""
    for lane, skill in (
        ("market-sizing-remote-lane", "market-sizing"),
        ("financial-model-review-smoke", "financial-model-review"),
    ):
        events = json.loads((_CASSETTES / f"{lane}.cassette.json").read_text(encoding="utf-8"))["events"]
        r = hcc.check_events(events)
        assert (r.outcome, r.skill) == ("PASS", skill), (lane, r)


def test_the_cli_exit_codes(tmp_path: Path) -> None:
    import subprocess

    script, printed = PRINTED["market-sizing"]
    cases = {
        0: [_call(script), _result(printed), _say(printed), _stop()],
        1: [_call(script), _result(printed), _say("rewritten"), _stop()],
        2: [_say("no closing call"), _stop()],
    }
    for want, events in cases.items():
        cassette = tmp_path / f"c{want}.cassette.json"
        cassette.write_text(json.dumps({"events": events}), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(_ROOT / "cowork-tests" / "handover_check_cassette.py"), str(cassette)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == want, (want, r.stdout, r.stderr)
        assert json.loads(r.stdout)["outcome"] in {"PASS", "FAIL", "NOT-EXERCISED"}


# SHRINK-ONLY. Emptied at the 4.0.0 re-record: market-sizing-remote-lane, recorded while the Stop hook failed
# open, now passes. A lane added here must say why, and leaves at its next re-record.
_KNOWN_FAILING: set[str] = set()


def test_every_committed_cassette_with_a_closing_call_carries_its_hand_over() -> None:
    failing: dict[str, list[str]] = {}
    exercised: set[str] = set()
    for path in sorted(_CASSETTES.glob("*.cassette.json")):
        name = path.name.removesuffix(".cassette.json")
        r = hcc.check_events(json.loads(path.read_text(encoding="utf-8"))["events"])
        if r.outcome == "NOT-EXERCISED":
            continue
        exercised.add(name)
        if r.outcome == "FAIL":
            failing[name] = r.problems
    assert exercised, "no committed cassette has a closing call -- the check covers nothing"
    assert set(failing) <= _KNOWN_FAILING, {k: v for k, v in failing.items() if k not in _KNOWN_FAILING}
    stale = _KNOWN_FAILING - set(failing)
    assert not stale, f"now passing -- remove from _KNOWN_FAILING: {sorted(stale)}"


def test_ci_runs_the_hand_over_check_on_every_cassette() -> None:
    wf = (_ROOT / ".github" / "workflows" / "cowork-replay.yml").read_text(encoding="utf-8")
    at = wf.index("python3 cowork-tests/handover_check_cassette.py")
    step = wf[wf.rindex("- name:", 0, at) : at]
    assert "continue-on-error" not in step, "the hand-over check is a hard gate"
    assert "for f in cowork-tests/cassettes/*.cassette.json" in step
