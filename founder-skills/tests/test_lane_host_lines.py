"""The paid lanes' request lines, fed to the real run-status scripts on every free run.

Each paid lane answers its gates up front with `FS_HOST_` lines, as an unattended host does. A line the
scripts refuse (`PRE_ANSWER_INVALID`) or never apply would make a $5-15 lane produce nothing, and the lanes
never run in the free suite. So this takes each lane's own constants, builds the request with the harness's
own `host_request`, and runs it through `run_status.py start`, `bind` and `record_gate_answer.py open`: the
line must be accepted, applied as the gate's answer, carry its note, and count as the host's evidence. A
later rename of a gate or an option the lanes send reds here instead of in a paid run.

Not named `test_e2e_*`: the lane count is pinned, and this file runs in the default suite.
"""

from __future__ import annotations

import importlib.util
import json
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

# (lane id, skill, slug, answers, notes)
LANES: list[tuple[str, str, str, Any, Any]] = [
    (MS.LANE, MS.SKILL, "foobar-fleet", MS.HOST_ANSWERS, MS.HOST_NOTES),
    (FMR.LANE, FMR.SKILL, "foobar-systems", FMR.HOST_ANSWERS, FMR.HOST_NOTES),
    (CT.SMOKE_LANE, CT.SKILL, "foobar", CT.SMOKE_ANSWERS, CT.SMOKE_NOTES),
    (CT.POOL_LANE, CT.SKILL, "barbaz", CT.POOL_ANSWERS, ()),
    ("dr", "deck-review", "acmecorp", (), ()),
]


def _out(proc: Any) -> dict[str, Any]:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _started(tmp_path: Path, lane: str, skill: str, slug: str, answers: Any, notes: Any) -> tuple[Path, str, Path]:
    run_id = harness.lane_run_id(lane)
    request = harness.host_request("The founder's request.", run_id, answers=answers, notes=notes)
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
    name, skill, slug, answers, notes = lane
    root, run_id, run_dir = _started(tmp_path, name, skill, slug, answers, notes)
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


def test_the_two_figures_line_answers_every_figure_the_inputs_name(tmp_path: Path) -> None:
    assert ("ms_two_figures", "typed") in MS.HOST_ANSWERS
    root, run_id, run_dir = _started(tmp_path, MS.LANE, MS.SKILL, "foobar-fleet", MS.HOST_ANSWERS, MS.HOST_NOTES)
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
