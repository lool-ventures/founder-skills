"""The market-sizing lane's sizing-dispatch check, driven by hand-built captures. Free: no model is called.

The paid lane (`test_e2e_market_sizing.py`) accepts each sizing build dispatched once, or one build dispatched
a second time as the run's one comparison redo. Whether a run takes the redo is the model's call, so the lane
cannot force either branch; each branch is settled here instead, on captures shaped like the SDK stream,
through the same `dispatch_report` and the dispatch hook's own comparand the lane uses.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
GEN = TESTS.parent / "skills" / "market-sizing" / "scripts" / "dispatch_prompt.py"
RUN = "lane-redo-run"
HAND = "/agent/market-sizing-quillfern/handoff/lane-redo-run"


def _module(name: str, path: Path) -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lane() -> Any:
    return _module("_redo_lane_test_e2e_market_sizing", TESTS / "test_e2e_market_sizing.py")


@pytest.fixture(scope="module")
def gen() -> Any:
    return _module("_redo_lane_dispatch_prompt", GEN)


def _prompt(gen: Any, context: str, redo: bool = False) -> str:
    with tempfile.TemporaryDirectory() as d:
        for name in ("inputs.json", "validation.json", "methodology.json"):
            Path(d, name).write_text("{}")
        text: str = gen.sizing(
            context,
            RUN,
            d,
            HAND,
            "/agent/market-sizing-quillfern",
            redo={"flagged": ["tam"], "suspect": []} if redo else None,
        )
    return text


class _Capture:
    """A RunCapture-shaped recording: transcript rows, structured calls, and their results."""

    def __init__(self, harness: Any) -> None:
        self.cap = harness.RunCapture()
        self.ids = itertools.count()

    def _id(self) -> str:
        return f"toolu_{next(self.ids)}"

    def call(
        self, name: str, tool_input: dict[str, Any], result: str, parent: str | None = None, **extra: Any
    ) -> dict[str, Any]:
        uid = self._id()
        use = {"id": uid, "name": name, "input": tool_input, "parent_tool_use_id": parent}
        self.cap.tool_uses.append(use)
        if parent is None:
            self.cap.rows.append(
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", **use}]}}
            )
            self.cap.rows.append(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": uid, "content": result}],
                    },
                }
            )
        self.cap.tool_results[uid] = {"is_error": False, "content": result, **extra}
        return use

    def printed(self, text: str, context: str, *flags: str) -> None:
        cmd = (
            f'python3 "$SCRIPTS/dispatch_prompt.py" {context} --run-id "$RUN_ID" --analysis-dir "$ANALYSIS_DIR" '
            f'--handoff-dir "$HANDOFF_DIR" --handoff-agent "$HANDOFF_AGENT" {" ".join(flags)}'
        ).rstrip()
        self.call("Bash", {"command": cmd}, text)

    def dispatch(self, prompt: str, received: str | None = None) -> dict[str, Any]:
        return self.call(
            "Agent",
            {"prompt": prompt, "subagent_type": "founder-skills:market-sizing", "description": "sizing"},
            "done",
            tool_use_result={"prompt": received if received is not None else prompt},
        )


TD, BU = "top_down_methodology", "bottom_up_methodology"


def _both_once(c: _Capture, gen: Any) -> list[dict[str, Any]]:
    out = []
    for ctx in (TD, BU):
        text = _prompt(gen, ctx)
        c.printed(text, ctx)
        out.append(c.dispatch(text))
    return out


def _problems(lane: Any, c: _Capture, sizing: list[dict[str, Any]], tmp_path: Path, **kw: Any) -> list[str]:
    from _e2e_harness import dispatch_report

    report = kw.pop("report", {"sizing_redo": {"build": "top_down", "flagged": ["tam"], "outcome": "changed"}})
    ledger = kw.pop("ledger", {"sizing_redo": {"run_id": RUN, "build": "top_down"}})
    problems: list[str] = lane.sizing_redo_problems(
        c.cap, sizing, dispatch_report(c.cap, sizing), tmp_path, RUN, report, ledger
    )
    return problems


def test_the_lane_and_the_generator_agree_on_the_lead(lane: Any, gen: Any) -> None:
    assert lane.REDO_LEAD == gen.REDO_LEAD


def test_one_dispatch_each_passes(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    assert _problems(lane, c, _both_once(c, gen), tmp_path, report={}, ledger={}) == []


def _with_redo(c: _Capture, gen: Any, context: str = TD) -> dict[str, Any]:
    text = _prompt(gen, context, redo=True)
    c.printed(text, context, "--redo comparison")
    return c.dispatch(text)


def test_a_sanctioned_redo_passes(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    redo = _with_redo(c, gen)
    c.call("Read", {"file_path": f"{HAND}/../validation.json"}, "x", parent=redo["id"])
    c.call("Read", {"file_path": f"{HAND}/top_down_output.json"}, "x", parent=redo["id"])
    assert _problems(lane, c, [*sizing, redo], tmp_path) == []


def test_a_plain_re_dispatch_fails(lane: Any, gen: Any, tmp_path: Path) -> None:
    """The observed failure: a hand-written repair, rewritten by the hook to the plain prompt."""
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    plain = _prompt(gen, TD)
    again = c.dispatch(plain.replace("do not swap them.", "do not swap them. Use the regional total."), received=plain)
    problems = _problems(lane, c, [*sizing, again], tmp_path)
    assert any("not the comparison redo" in p for p in problems), problems


def test_two_redos_fail(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    redos = [_with_redo(c, gen, TD), _with_redo(c, gen, BU)]
    problems = _problems(lane, c, [*sizing, *redos], tmp_path)
    assert any("2 comparison redos" in p for p in problems), problems


def test_a_third_dispatch_of_a_build_fails(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    redo = _with_redo(c, gen)
    again = c.dispatch(_prompt(gen, TD, redo=True))
    problems = _problems(lane, c, [*sizing, redo, again], tmp_path)
    assert any("3 dispatches went through" in p for p in problems), problems


@pytest.mark.parametrize(
    ("tool", "target"),
    [
        ("Read", "/agent/market-sizing-quillfern/sizing.json"),
        ("Read", f"{HAND}/bottom_up_output.json"),
        ("Read", "/agent/market-sizing-quillfern/sizing_redo.json"),
        ("Grep", "/agent/market-sizing-quillfern"),
    ],
)
def test_a_redo_sub_agent_that_opened_what_its_prompt_rules_out_fails(
    lane: Any, gen: Any, tmp_path: Path, tool: str, target: str
) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    redo = _with_redo(c, gen)
    key = "file_path" if tool == "Read" else "path"
    c.call(tool, {key: target}, "x", parent=redo["id"])
    assert _problems(lane, c, [*sizing, redo], tmp_path), (tool, target)


def test_a_redo_with_no_record_or_one_the_sizing_never_used_fails(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    redo = _with_redo(c, gen)
    no_record = _problems(lane, c, [*sizing, redo], tmp_path, ledger={})
    assert any("no record" in p for p in no_record), no_record
    unused = _problems(lane, c, [*sizing, redo], tmp_path, report={"sizing_redo": {"outcome": "not_run"}})
    assert any("the report says" in p for p in unused), unused


def test_a_redo_the_sub_agent_did_not_receive_fails(lane: Any, gen: Any, tmp_path: Path) -> None:
    import _e2e_harness

    c = _Capture(_e2e_harness)
    sizing = _both_once(c, gen)
    text = _prompt(gen, TD, redo=True)
    c.printed(text, TD, "--redo comparison")
    redo = c.dispatch(text, received=_prompt(gen, TD))
    problems = _problems(lane, c, [*sizing, redo], tmp_path)
    assert any("did not receive" in p for p in problems), problems
