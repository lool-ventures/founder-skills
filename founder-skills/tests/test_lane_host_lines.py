"""The paid lanes' request lines, fed to the real run-status scripts on every free run.

Each paid lane answers its gates up front with `FS_HOST_` lines, as an unattended host does. A line the
scripts refuse (`PRE_ANSWER_INVALID`) or never apply would make a $5-15 lane produce nothing, and the lanes
never run in the free suite. So this takes each lane's own constants, builds the request with the harness's
own `host_request`, and runs it through `run_status.py start`, `bind` and `record_gate_answer.py open`: the
line must be accepted, applied as the gate's answer, carry its note (or its value), and count as the host's
evidence. A later rename of a gate or an option the lanes send reds here instead of in a paid run.

A VALUE line must also be stated verbatim in the lane's own prompt. The skill types the company basics
again from the prose (`founder_context.py init`), and a typed value that differs from the recorded one is
refused (`GATE_RECORD_MISMATCH`) -- a stop the lane would meet only in a paid run.

Not named `test_e2e_*`: the lane count is pinned, and this file runs in the default suite.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import gate_run_helpers as h  # noqa: E402


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_hostlines_{name}", TESTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


harness = _module("_e2e_harness")
MS = _module("test_e2e_market_sizing")
FMR = _module("test_e2e_financial_model_review")
CT = _module("test_e2e_cap_table")
DR = _module("test_e2e_deck_review")  # the SDK is imported only inside its test functions

# (lane id, skill, slug, answers, values, notes)
LANES: list[tuple[str, str, str, Any, Any, Any]] = [
    (MS.LANE, MS.SKILL, "foobar-fleet", MS.HOST_ANSWERS, MS.HOST_VALUES, MS.HOST_NOTES),
    (FMR.LANE, FMR.SKILL, "foobar-systems", FMR.HOST_ANSWERS, FMR.HOST_VALUES, FMR.HOST_NOTES),
    (CT.SMOKE_LANE, CT.SKILL, "foobar", CT.SMOKE_ANSWERS, (), CT.SMOKE_NOTES),
    (CT.POOL_LANE, CT.SKILL, "barbaz", CT.POOL_ANSWERS, (), ()),
    ("dr", "deck-review", "acmecorp", (), DR.host_values(DR.SMOKE_COMPANY), ()),
    ("dr-contra", "deck-review", "foobar", (), DR.host_values(DR.CONTRADICTION_COMPANY), ()),
    ("dr-numeric", "deck-review", "kestrelline", (), DR.host_values(DR.NUMERIC_COMPANY), ()),
]

# Each lane's prompt as sent, before the host's lines. The paths are placeholders; only the words matter.
PROMPTS: dict[str, str] = {
    MS.LANE: MS.PROMPT,
    FMR.LANE: FMR.PROMPT_TEMPLATE.format(model_path="/workspace/model.csv"),
    CT.SMOKE_LANE: CT.SMOKE_PROMPT,
    CT.POOL_LANE: CT.POOL_PROMPT,
    "dr": DR.lane_prompt("/workspace/deck.txt", DR.SMOKE_COMPANY, "acmecorp"),
    "dr-contra": DR.lane_prompt("/workspace/deck.txt", DR.CONTRADICTION_COMPANY, "foobar"),
    "dr-numeric": DR.lane_prompt("/workspace/deck.txt", DR.NUMERIC_COMPANY, "kestrelline"),
}


def _out(proc: Any) -> dict[str, Any]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _started(
    tmp_path: Path, lane: str, skill: str, slug: str, answers: Any, notes: Any, values: Any = ()
) -> tuple[Path, str, Path]:
    run_id = harness.lane_run_id(lane)
    request = harness.host_request("The founder's request.", run_id, answers=answers, values=values, notes=notes)
    lines = "".join(line + "\n" for line in request.splitlines() if line.startswith("FS_HOST_"))
    root = tmp_path / "artifacts"
    out = _out(h.start(root, skill, lines))
    assert out["run_id"] == run_id and out["status"] == "running", out
    status = h.status(root, run_id)
    assert status["notices"] == [], status["notices"]
    run_dir = root / f"{skill}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _out(h.bind(root, run_id, run_dir, slug))
    return root, run_id, run_dir


@pytest.mark.parametrize("lane", LANES, ids=[lane[0] for lane in LANES])
def test_each_lane_s_lines_are_accepted_and_each_answer_applies(lane: Any, tmp_path: Path) -> None:
    name, skill, slug, answers, values, notes = lane
    root, run_id, run_dir = _started(tmp_path, name, skill, slug, answers, notes, values)
    if skill == "cap-table":
        # The run as each CT prompt states it: a cap base (so its confirmation is owed), an existing option plan
        # only in the pool lane (so the smoke's pool line is the one owed), and one SAFE with no note (the
        # scenarios offered are built from the instruments, and a SAFE alone offers the cap-implied snapshot).
        inputs: dict[str, Any] = {"metadata": {"run_id": run_id}, "founders": [{"name": "Founder", "shares": 8000000}]}
        if name == CT.POOL_LANE:
            inputs["option_pool"] = {"authorized": 1000000, "issued": 800000, "unallocated": 200000}
        (run_dir / "inputs.json").write_text(json.dumps(inputs))
        (run_dir / "instruments.json").write_text(
            json.dumps({"metadata": {"run_id": run_id}, "safes": [{"id": "safe-1"}], "convertible_notes": []})
        )
    noted = dict(notes)
    for gate, option in answers:
        if gate == "ms_two_figures":
            continue  # a bare line for every instance the inputs name; checked below
        opened = _out(h.record(root, run_id, "open", "--gate", gate))
        assert opened.get("applied") == "pre_answer" and gate in opened.get("applied_gates", []), (gate, opened)
        ledger = h.ledger(root, run_id)
        cur = ledger["gates"][gate]["current"]
        assert set(cur["answer_id"].split(",")) == set(option.split(",")), (gate, cur)
        assert cur["resolution"] == "answered" and cur["note"] == noted.get(gate), (gate, cur)
        assert ledger["pre_answers"][gate]["applied_at"] == cur["answered_at"], gate
        problems = harness.pre_answer_problems(ledger, gate, cur["answer_id"], noted.get(gate))
        assert problems == [], problems
        if gate in ("ms_methodology", "fmr_extracted_values"):  # the two `since_invocation` gates a lane answers
            assert cur["asked_evidence"] == "host_line", (gate, cur)
    for gate, option, value in values:
        opened = _out(h.record(root, run_id, "open", "--gate", gate))
        assert opened.get("applied") == "pre_answer" and gate in opened.get("applied_gates", []), (gate, opened)
        ledger = h.ledger(root, run_id)
        cur = ledger["gates"][gate]["current"]
        assert (cur["answer_id"], cur["resolution"], cur["value"]) == (option, "answered", value), (gate, cur)
        assert ledger["pre_answers"][gate]["value"] == value, (gate, ledger["pre_answers"][gate])
        assert harness.pre_answer_problems(ledger, gate, option) == [], gate


def test_every_lane_has_a_prompt_and_every_value_line_is_stated_in_it() -> None:
    """The skill types each basic again from the prose and refuses a typed value that differs from the
    recorded one, so a value the prompt does not state word for word is a stop only a paid run would meet."""
    assert set(PROMPTS) == {lane[0] for lane in LANES}
    sent = 0
    for name, _skill, _slug, _answers, values, _notes in LANES:
        for gate, _option, value in values:
            # Whole words: "US" must not pass on the strength of "USD".
            stated = re.search(rf"(?<!\w){re.escape(value)}(?!\w)", PROMPTS[name])
            assert stated, f"{name}: {gate} sends {value!r}, which its prompt does not state verbatim"
            sent += 1
    assert sent >= 8, f"expected the MS and FMR basics and both DR names, found {sent} value lines"


def test_the_deck_review_lanes_do_not_pre_answer_the_stage() -> None:
    """The DR prompt states the stage as the founder's answer, worded for the stage gate's auto-satisfy branch;
    a host stage line is deliberately not sent there."""
    for name, skill, _slug, answers, values, _notes in LANES:
        if skill == "deck-review":
            assert answers == () and [g for g, _o, _v in values] == ["ctx_basics.company_name"], name


def test_the_two_figures_line_answers_every_figure_the_inputs_name(tmp_path: Path) -> None:
    assert ("ms_two_figures", "typed") in MS.HOST_ANSWERS
    root, run_id, run_dir = _started(
        tmp_path, MS.LANE, MS.SKILL, "foobar-fleet", MS.HOST_ANSWERS, MS.HOST_NOTES, MS.HOST_VALUES
    )
    (run_dir / "inputs.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": run_id},
                "founder_stated_alternatives": {
                    "arpu": [{"value": 261, "period": "month"}, {"value": 317, "period": "month"}]
                },
            }
        )
    )
    opened = _out(h.record(root, run_id, "open", "--gate", "ms_two_figures.arpu"))
    assert opened.get("applied") == "pre_answer", opened
    assert h.ledger(root, run_id)["gates"]["ms_two_figures.arpu"]["current"]["answer_id"] == "typed"


@pytest.mark.parametrize("jurisdiction, owed", [("delaware", False), ("israeli", True)])
def test_the_cap_table_lanes_never_owe_the_israeli_grants_question(
    jurisdiction: str, owed: bool, tmp_path: Path
) -> None:
    """Both CT prompts state a Delaware company; with that recorded, the IIA question is not owed, so the lanes
    need no line for it. The Israeli case is the control: the same call opens it."""
    root, run_id, _ = _started(tmp_path, CT.SMOKE_LANE, CT.SKILL, "foobar", CT.SMOKE_ANSWERS, CT.SMOKE_NOTES)
    _out(h.record(root, run_id, "open", "--gate", "ct_jurisdiction"))
    _out(h.record(root, run_id, "answer", "--gate", "ct_jurisdiction", "--answer-id", jurisdiction))
    proc = h.record(root, run_id, "open", "--gate", "ct_iia_grants")
    out = json.loads(proc.stdout)
    assert (proc.returncode, out["opened"], out["not_owed"]) == (
        (0, ["ct_iia_grants"], []) if owed else (11, [], ["ct_iia_grants"])
    ), proc.stdout


def test_the_lanes_name_a_fresh_run_each_time() -> None:
    assert harness.lane_run_id("ms") != harness.lane_run_id("ms")


SCHEMAS = TESTS.parent / "skills" / "cap-table" / "references" / "schemas"
# Required fields the pipeline fills itself, never the founder: an instrument's id and the extractor's confidence.
SYNTHESIZED = {"safes.id", "safes.extraction_confidence"}


def _required(schema: str, prop: str) -> set[str]:
    node = json.loads((SCHEMAS / schema).read_text(encoding="utf-8"))["properties"][prop]
    node = node.get("items", node)
    return {f"{prop}.{f}" for f in node["required"]}


@pytest.mark.parametrize("lane, prompt", [("smoke", CT.SMOKE_PROMPT), ("pool", CT.POOL_PROMPT)])
def test_each_cap_table_prompt_states_every_field_the_schemas_require(lane: str, prompt: str) -> None:
    """An unstated required field becomes a founder-fact question with no default, which an unattended lane
    cannot answer: the run would wait and produce nothing. So every required founder-supplied field of the
    founders, the SAFE and (where the prompt describes one) the option plan is stated, in the prompt's words."""
    required = _required("inputs.schema.json", "founders") | _required("instruments.schema.json", "safes")
    if "option plan" in prompt:
        required |= _required("inputs.schema.json", "option_pool")
    stated = CT.STATED[lane]
    assert required - SYNTHESIZED == set(stated), sorted((required - SYNTHESIZED) ^ set(stated))
    for field, words in stated.items():
        for w in words:
            assert w in prompt, f"{lane}: {field} is said to be stated as {w!r}, which the prompt does not say"
