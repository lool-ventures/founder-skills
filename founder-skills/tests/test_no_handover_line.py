"""`FS_HOST_NO_HANDOVER`: the request line, its record in the ledger and the status, and its conflict with
`FS_HOST_REPLY_TOOL`. The closers' half is in each skill's gates tests; the Stop hook's in
`test_stop_no_handover.py`. Ids are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import gate_run_helpers as h
import pytest

RID = "20261020T090000Z-1a2b3c"
LINE = "FS_HOST_NO_HANDOVER"
REPLY_LINE = "FS_HOST_REPLY_TOOL mcp__hostchat__reply text"


def _gates() -> Any:
    if str(h.SHARED) not in sys.path:
        sys.path.insert(0, str(h.SHARED))
    spec = importlib.util.spec_from_file_location("_gates_nh_test", h.SHARED / "_gates.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    return root


@pytest.mark.parametrize(
    "text",
    [f"{LINE}\n", f"FS_HOST_RUN_ID={RID}\n{LINE}\n", f"FS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK\n{LINE}\n"],
    ids=["alone", "with-run-id", "with-no-ask"],
)
def test_the_line_is_accepted(text: str) -> None:
    _rid, _pre, bad, flags = _gates().parse_request(text, "market-sizing")
    assert bad == [] and flags["no_handover"] == LINE


@pytest.mark.parametrize(
    "text", [f"{LINE} yes\n", f"{LINE}\n{REPLY_LINE}\n"], ids=["trailing-word", "beside-reply-tool"]
)
def test_the_line_is_refused(text: str) -> None:
    _rid, _pre, bad, _flags = _gates().parse_request(text, "market-sizing")
    assert [b["line"] for b in bad] == [text.splitlines()[0]]


def test_start_records_it_and_the_status_shows_it(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{LINE}\n") == RID
    rec = h.ledger(root, RID)["no_handover"]
    assert (rec["raw"], rec["by"]) == (LINE, "run_status.py") and "not_used_by_skill" not in rec
    st = h.status(root, RID)
    assert st["no_handover"] is True and st["handover"] is None
    assert "no_ask" not in h.ledger(root, RID)


def test_start_records_it_beside_no_ask(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\nFS_HOST_NO_ASK\n{LINE}\n") == RID
    led = h.ledger(root, RID)
    assert isinstance(led["no_handover"], dict) and isinstance(led["no_ask"], dict)


def test_a_run_with_no_line_shows_false(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n") == RID
    st = h.status(root, RID)
    assert st["no_handover"] is False and st["handover"] is None
    assert "no_handover" not in h.ledger(root, RID)


def test_start_refuses_it_beside_the_reply_tool(tmp_path: Path) -> None:
    root = _root(tmp_path)
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{LINE}\n{REPLY_LINE}\n")
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "PRE_ANSWER_INVALID"


def _waiting(root: Path, lines: str) -> None:
    assert h.start_ok(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{lines}") == RID
    opened = h.record(root, RID, "open", "--gate", "ms_methodology")
    assert h.status(root, RID)["status"] == "waiting", opened.stdout + opened.stderr


@pytest.mark.parametrize(("first", "added"), [(REPLY_LINE, LINE), (LINE, REPLY_LINE)])
def test_a_resume_adding_the_other_line_is_refused_and_the_run_unchanged(
    tmp_path: Path, first: str, added: str
) -> None:
    root = _root(tmp_path)
    _waiting(root, f"{first}\n")
    before = h.snapshot(root, RID)
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{added}\n")
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "PRE_ANSWER_INVALID", proc.stdout
    assert h.snapshot(root, RID) == before


def test_it_is_sticky_across_a_resume_and_never_in_the_resume_prompt(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _waiting(root, f"{LINE}\n")
    assert LINE not in h.status(root, RID)["resume_prompt"]
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.status(root, RID)["no_handover"] is True


def test_a_resume_may_add_it(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _waiting(root, "")
    proc = h.start(root, "market-sizing", f"FS_HOST_RUN_ID={RID}\n{LINE}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert h.status(root, RID)["no_handover"] is True


@pytest.mark.parametrize(
    ("skill", "verdict"),
    [
        ("market-sizing", "applies"),
        ("competitive-positioning", "applies"),
        ("financial-model-review", "applies"),
        ("deck-review", "not_used_by_skill"),
        ("ic-sim", "not_used_by_skill"),
        ("cap-table", "not_used_by_skill"),
    ],
)
def test_check_reads_the_line_per_skill(skill: str, verdict: str) -> None:
    proc = h.run(h.RUN_STATUS, "check", "--skill", skill, stdin=f"{LINE}\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [v for v in json.loads(proc.stdout)["values"] if v.get("line") == LINE]
    assert rows == [{"gate": None, "line": LINE, "verdict": verdict}]


@pytest.mark.parametrize(("skill", "listed"), [("deck-review", True), ("ic-sim", True), ("market-sizing", False)])
def test_a_skill_with_no_closer_lists_the_line_not_used(tmp_path: Path, skill: str, listed: bool) -> None:
    root = _root(tmp_path)
    assert h.start_ok(root, skill, f"FS_HOST_RUN_ID={RID}\n{LINE}\n") == RID
    done = h.run(h.RUN_STATUS, "fail", "--run-id", RID, "--artifacts-root", str(root), "--code",
                 "PRODUCER_FAILED", "--reason", "x")  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    notices = [n for n in h.status(root, RID)["notices"] if n.get("lines") == [LINE]]
    want = [{"code": "PRE_ANSWER_IGNORED", "gate": None, "lines": [LINE], "reason": "not_used_by_skill"}]
    assert notices == (want if listed else [])


def test_a_reopen_clears_the_hand_over_mark() -> None:
    g = _gates()
    status: dict[str, Any] = {"revision": 1, "handed_over_at": "2026-10-20T00:00:00Z", "handover": "host"}
    status.update({"status": "complete", "code": "COMPLETE", "invocations": [], "invocation": 1})
    g._reopen_complete(status, None, None, step="Step 7")
    assert status["handed_over_at"] is None and status["handover"] is None and status["status"] == "running"


def test_the_contract_lists_the_line() -> None:
    contract = json.loads((h.REPO_ROOT / "founder-skills" / "data" / "host-contract.json").read_text())
    assert contract["request_tokens"]["no_handover"] == LINE
    assert any("`FS_HOST_NO_HANDOVER`" in n for n in contract["notes"])


@pytest.mark.parametrize(("skill", "shown"), [("deck-review", False), ("cap-table", False), ("market-sizing", True)])
def test_the_status_shows_it_in_effect_only_where_a_closer_reads_it(tmp_path: Path, skill: str, shown: bool) -> None:
    root = _root(tmp_path)
    assert h.start_ok(root, skill, f"FS_HOST_RUN_ID={RID}\n{LINE}\n") == RID
    assert h.status(root, RID)["no_handover"] is shown
    assert isinstance(h.ledger(root, RID)["no_handover"], dict)
