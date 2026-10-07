"""The run status reads the asked-gate hook's record into a held gate's `asked_evidence`.

The hook (`asked_gate_check.py`) appends one line per decision to `handoff/<run_id>/asked_evidence.jsonl`
in the run's dir. `_run_status.fold_asked_evidence` copies the evidence of a pass into the gate's current
answer when no script recorded a value, bound to that answer by its `answered_at`. Every line here is
written by hand in the record's shape; `test_asked_gate_hook.py` covers the hook writing it.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))
import _gates  # type: ignore[import-not-found]  # noqa: E402
import _run_status as rs  # type: ignore[import-not-found]  # noqa: E402

RUN_ID = "r-acme-1"
AT = "2026-01-02T03:04:05.000006Z"


def _line(**over: Any) -> dict[str, Any]:
    line = {
        "schema": rs.ASKED_EVIDENCE_SCHEMA,
        "schema_version": rs.ASKED_EVIDENCE_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "gate": "ms_methodology",
        "context": "TOP_DOWN_METHODOLOGY",
        "agent": "market-sizing",
        "decision": "pass",
        "passed_on": "evidence",
        "evidence": "plain_chat",
        "kinds": ["plain_chat"],
        "window": "invocation",
        "answered_at": AT,
        "at": "2026-01-02T03:05:00.000000Z",
        "by": "asked_gate_check.py",
    }
    line.update(over)
    return line


def _write(run: Path, *lines: dict[str, Any] | str) -> None:
    folder = run / "handoff" / RUN_ID
    folder.mkdir(parents=True, exist_ok=True)
    text = "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines)
    (folder / rs.ASKED_EVIDENCE_FILE).write_text(text, encoding="utf-8")


def _status(run: Path, **current: Any) -> dict[str, Any]:
    cur: dict[str, Any] = {
        "answer": "Looks good",
        "answer_id": "looks_good",
        "answered_at": AT,
        "resolution": "answered",
    }
    cur["asked_evidence"] = None
    cur.update(current)
    gate = {"id": "ms_methodology", "instance": None, "asked_check": "since_invocation", "current": cur}
    other = {"id": "ms_two_figures", "instance": None, "asked_check": "current_prompt", "current": dict(cur)}
    return {"run_id": RUN_ID, "run_dir_shell": str(run), "gates": [gate, other]}


def _folded(status: dict[str, Any]) -> Any:
    rs.fold_asked_evidence(status)
    return status["gates"][0]["current"]["asked_evidence"]


def test_a_pass_on_evidence_for_this_answer_is_folded(tmp_path: Path) -> None:
    _write(tmp_path, _line())
    status = _status(tmp_path)
    assert _folded(status) == "plain_chat"
    assert status["gates"][1]["current"]["asked_evidence"] is None, "a gate checked in the current prompt only"


@pytest.mark.parametrize(
    "line",
    [
        _line(answered_at="2026-01-02T03:04:05.000007Z"),
        _line(answered_at=None),
        _line(run_id="r-other"),
        _line(decision="hold", passed_on=None, evidence=None),
        _line(passed_on="marker", evidence=None),
        _line(passed_on="marker"),
        _line(evidence="after_hold"),
        _line(evidence="telepathy"),
        _line(gate="fmr_extracted_values"),
        _line(schema="founder-skills/other"),
        _line(schema_version=2),
    ],
    ids=[
        "other-answer",
        "no-answer",
        "other-run",
        "hold",
        "marker",
        "marker-with-kind",
        "script-kind",
        "unknown",
        "other-gate",
        "schema",
        "version",
    ],  # fmt: skip
)
def test_a_line_that_is_not_this_answers_pass_on_evidence_is_ignored(tmp_path: Path, line: dict[str, Any]) -> None:
    _write(tmp_path, line)
    assert _folded(_status(tmp_path)) is None


def test_a_script_value_always_wins(tmp_path: Path) -> None:
    _write(tmp_path, _line(evidence="ask_user_question"))
    assert _folded(_status(tmp_path, asked_evidence="host_line")) == "host_line"


def test_only_an_answer_counts(tmp_path: Path) -> None:
    _write(tmp_path, _line())
    assert _folded(_status(tmp_path, resolution="default_taken")) is None
    status = _status(tmp_path)
    status["gates"][0]["current"] = None
    rs.fold_asked_evidence(status)
    assert status["gates"][0]["current"] is None


def test_the_last_matching_line_wins_and_a_torn_line_is_skipped(tmp_path: Path) -> None:
    _write(tmp_path, _line(evidence="host_line"), '{"schema": "founder-sk', _line(evidence="ask_user_question"), "{")
    assert _folded(_status(tmp_path)) == "ask_user_question"


def test_no_run_dir_yet_folds_nothing(tmp_path: Path) -> None:
    _write(tmp_path, _line())
    status = _status(tmp_path)
    status["run_dir_shell"] = None
    assert _folded(status) is None


def test_no_record_or_an_unreadable_one_folds_nothing(tmp_path: Path) -> None:
    assert _folded(_status(tmp_path)) is None
    (tmp_path / "handoff" / RUN_ID / rs.ASKED_EVIDENCE_FILE).mkdir(parents=True)
    assert _folded(_status(tmp_path)) is None


def test_the_ledgers_own_answer_is_not_changed(tmp_path: Path) -> None:
    """The status view shares the ledger's answer dict: the fold assigns a copy."""
    _write(tmp_path, _line())
    status = _status(tmp_path)
    shared = status["gates"][0]["current"]
    before = copy.deepcopy(shared)
    assert _folded(status) == "plain_chat"
    assert shared == before and status["gates"][0]["current"] is not shared


def test_only_the_tail_of_a_large_record_is_read(tmp_path: Path) -> None:
    filler = json.dumps(_line(evidence="host_line")) + "\n"
    _write(tmp_path, *([filler.strip()] * (rs._ASKED_EVIDENCE_MAX // len(filler) + 50)), _line())
    assert _folded(_status(tmp_path)) == "plain_chat"


# --- through the status writers ----------------------------------------------------------------------


def _run(tmp_path: Path) -> tuple[Path, rs.RunPaths]:
    root = tmp_path / "artifacts"
    run = root / "market-sizing-acme"
    paths = rs.run_paths(str(root), RUN_ID)
    status = rs.blank_status("market-sizing", paths)
    status.update(_status(run))
    status["mode"] = "full"
    rs.create_status_exclusive(paths, status)
    rs.atomic_write_json(paths.ledger, _gates.new_ledger(RUN_ID, "market-sizing", "cli"))
    return run, paths


def test_every_status_write_folds(tmp_path: Path) -> None:
    run, paths = _run(tmp_path)
    _write(run, _line())
    report = run / "report.md"
    report.write_text("# Report\n", encoding="utf-8")
    rs.complete_after_coaching(paths, str(report), None)
    on_disk = json.loads(Path(paths.status).read_text(encoding="utf-8"))
    assert on_disk["gates"][0]["current"]["asked_evidence"] == "plain_chat"


def test_show_folds_on_read_without_writing(tmp_path: Path) -> None:
    run, paths = _run(tmp_path)
    _write(run, _line(evidence="ask_user_question"))
    before = Path(paths.status).read_text(encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "run_status.py"), "show", "--run-id", RUN_ID,
         "--artifacts-root", str(tmp_path / "artifacts")],
        capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["gates"][0]["current"]["asked_evidence"] == "ask_user_question"
    assert Path(paths.status).read_text(encoding="utf-8") == before


# --- who supplies which value ------------------------------------------------------------------------


def test_a_script_records_only_its_own_values() -> None:
    assert set(_gates.SCRIPT_ASKED_EVIDENCE) == {"host_line", "form", "after_hold"}
    assert set(_gates.ASKED_EVIDENCE) == set(_gates.SCRIPT_ASKED_EVIDENCE) | set(rs.HOOK_ASKED_EVIDENCE)
    with pytest.raises(ValueError, match="not a value a script records"):
        _gates.record(None, {}, "ms_methodology", answer_ids=["looks_good"], asked_evidence="plain_chat")  # type: ignore[arg-type]


def test_the_contract_lists_every_value_and_says_what_it_is() -> None:
    contract = json.loads((PLUGIN / "data" / "host-contract.json").read_text(encoding="utf-8"))
    assert contract["asked_evidence"] == list(_gates.ASKED_EVIDENCE)
    note = next(n for n in contract["notes"] if n.startswith("`current.asked_evidence`"))
    assert "measurement" in note and "not an attestation" in note


def test_no_skill_script_reads_the_hooks_record() -> None:
    """Reports and compose never read it: it measures the hold, and no deliverable is built from it."""
    named = [
        str(p.relative_to(PLUGIN))
        for p in (PLUGIN / "skills").rglob("*.py")
        if rs.ASKED_EVIDENCE_FILE in p.read_text(encoding="utf-8")
    ]
    assert named == []


def test_a_gate_with_an_instance_is_not_folded(tmp_path: Path) -> None:
    _write(tmp_path, _line())
    status = _status(tmp_path)
    status["gates"][0]["instance"] = "x"
    assert _folded(status) is None
