"""The deck lanes' deck-text dispatch checks, against hand-built captures.

Free: nothing here calls the model. All three deck lanes run `deck_text_dispatch_problems` from
`test_e2e_deck_review.py` and fail on what it returns, so the cases a live run rarely shows (a hold or a
failed attempt followed by a good retry, a blind capture) are settled here instead of on a paid re-run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
SLIDE_ONE = "Synthetic slide one line"


@pytest.fixture(scope="module")
def lane() -> Any:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    spec = importlib.util.spec_from_file_location("_deck_text_test_e2e_deck_review", TESTS / "test_e2e_deck_review.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Capture:
    """Builds a RunCapture with main-thread dispatches, their results and their child calls."""

    def __init__(self, lane: Any) -> None:
        self.cap = lane.RunCapture()
        self._n = 0

    def dispatch(
        self,
        context: str,
        *,
        result: str = "ok",
        names_file: bool = True,
        inline: bool = False,
        reads: bool = True,
        child: bool = True,
    ) -> None:
        self._n += 1
        tid = f"t{self._n}"
        prompt = f"CONTEXT: {context}\nOUTPUT_PATH: /x/{context}.json\n"
        if names_file:
            prompt += "Read /x/deck_text.md first.\n"
        if inline:
            prompt += SLIDE_ONE + "\n"
        self.cap.tool_uses.append({"id": tid, "name": "Agent", "input": {"prompt": prompt}, "parent_tool_use_id": None})
        if result == "ok":
            self.cap.tool_results[tid] = {"is_error": False, "content": "receipt"}
        elif result == "hold":
            self.cap.tool_results[tid] = {"is_error": True, "content": "[dispatch-check][/x] hold"}
        elif result == "error":
            self.cap.tool_results[tid] = {"is_error": True, "content": "sub-agent failed"}
        if not child:
            return
        path = "/x/deck_text.md" if reads else "/x/deck_inventory.json"
        self.cap.tool_uses.append(
            {"id": f"{tid}c", "name": "Read", "input": {"file_path": path}, "parent_tool_use_id": tid}
        )


def _all_good(lane: Any) -> _Capture:
    c = _Capture(lane)
    for context in lane.DECK_TEXT_CONTEXTS:
        c.dispatch(context)
    return c


def test_all_good_has_no_failure(lane: Any) -> None:
    failures, notes, calls = lane.deck_text_dispatch_problems(_all_good(lane).cap, SLIDE_ONE)
    assert (failures, notes, calls) == ([], [], 3)


@pytest.mark.parametrize("first", ["hold", "error"])
def test_a_held_or_failed_attempt_then_a_good_retry_passes(lane: Any, first: str) -> None:
    c = _Capture(lane)
    c.dispatch("SLIDE_REVIEWS", result=first, names_file=False, reads=False)
    for context in lane.DECK_TEXT_CONTEXTS:
        c.dispatch(context)
    failures, _notes, _calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == []


def test_a_succeeded_dispatch_that_never_read_the_file_fails(lane: Any) -> None:
    c = _Capture(lane)
    c.dispatch("LEDGER_EXTRACTION")
    c.dispatch("SECOND_READ", reads=False)
    c.dispatch("SLIDE_REVIEWS")
    failures, _notes, _calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == ["a SECOND_READ dispatch never Read deck_text.md"]


def test_a_prompt_that_inlines_the_deck_fails(lane: Any) -> None:
    c = _Capture(lane)
    c.dispatch("LEDGER_EXTRACTION", inline=True)
    c.dispatch("SECOND_READ")
    c.dispatch("SLIDE_REVIEWS")
    failures, _notes, _calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == [f"a LEDGER_EXTRACTION dispatch inlines the deck's text ({SLIDE_ONE!r})"]


def test_a_prompt_that_does_not_name_the_file_fails(lane: Any) -> None:
    c = _Capture(lane)
    c.dispatch("LEDGER_EXTRACTION")
    c.dispatch("SECOND_READ")
    c.dispatch("SLIDE_REVIEWS", names_file=False)
    failures, _notes, _calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == ["a SLIDE_REVIEWS dispatch does not name deck_text.md"]


def test_a_blind_capture_is_a_note_not_a_failure(lane: Any) -> None:
    c = _Capture(lane)
    for context in lane.DECK_TEXT_CONTEXTS:
        c.dispatch(context, child=False)
    failures, notes, calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == []
    assert calls == 0
    assert notes and notes[0].startswith("child calls not captured")


@pytest.mark.parametrize("only", ["hold", "error", "missing"])
def test_a_context_with_no_succeeded_dispatch_fails(lane: Any, only: str) -> None:
    c = _Capture(lane)
    c.dispatch("LEDGER_EXTRACTION")
    c.dispatch("SECOND_READ", result=only)
    c.dispatch("SLIDE_REVIEWS")
    failures, _notes, _calls = lane.deck_text_dispatch_problems(c.cap, SLIDE_ONE)
    assert failures == ["no SECOND_READ dispatch succeeded"]


def test_the_lane_gates_on_the_function(lane: Any) -> None:
    """The driver adds the function's failures to its own, never only to `observed`."""
    import inspect

    src = inspect.getsource(lane._drive_deck_review_lane)
    assert "deck_text_dispatch_problems(cap, slide_one)" in src
    assert "failures.extend(text_failures)" in src
