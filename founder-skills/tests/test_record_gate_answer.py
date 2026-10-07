"""`record_gate_answer.py` and the ledger operations under it.

A recorded answer is what every enforcer checks, so each refusal is held here with the ledger and the
status left byte-identical: a refused write that changed either would let a host read an answer nobody
recorded. Compare-and-set, supersession on a changed binding, defaults, effects between gates and the
reopen of a finished run are driven both through the CLI and in-process, where a gate's skill predicate
is not wired yet (those are patched to "owed" for the test, never in the module). Ids are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load("_run_status")
g = _load("_gates")


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def _tx(root: Path, run_id: str, fn: Callable[[Any, dict[str, Any], dict[str, Any]], Any]) -> Any:
    return g.transact(rs.run_paths(str(root), run_id), fn)


def _rec(root: Path, run_id: str, key: str, **kw: Any) -> Any:
    return _tx(root, run_id, lambda ctx, ledger, st: g.record(ctx, ledger, key, **kw))


def _owed(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.setitem(g.PREDICATES, name, g._pred_always)


def _rejected(root: Path, run_id: str, proc: Any, code: str, before: tuple[bytes, bytes]) -> None:
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc)["code"] == code, proc.stdout
    assert proc.stderr.strip()
    assert h.snapshot(root, run_id) == before, f"{code} changed the ledger or the status"


# --- the refusals --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--gate", "no_such_gate", "--answer-id", "x"], "GATE_UNKNOWN"),
        (["--gate", "ms_methodology", "--answer-id", "looks_good"], "GATE_FOREIGN"),
        (["--gate", "ctx_basics.stage", "--answer-id", "series_q"], "OPTION_UNLISTED"),
        (["--gate", "ctx_basics.stage", "--answer", "Series Q"], "OPTION_UNLISTED"),
        (["--gate", "ctx_basics.sector", "--answer-id", "different"], "VALUE_REQUIRED"),
        (["--gate", "ctx_basics.stage", "--answer-id", "seed", "--value", "x"], "VALUE_NOT_ALLOWED"),
        (["--gate", "ctx_basics.company_name", "--answer-id", "use_model_file"], "OPTION_SKILL"),
        (["--gate", "ctx_basics.stage/r2", "--answer-id", "seed"], "ID_MALFORMED"),
        (["--gate", "Ctx_basics.stage", "--answer-id", "seed"], "ID_MALFORMED"),
        (["--gate", "ctx_basics.rank", "--answer-id", "seed"], "ID_MALFORMED"),
        (["--gate", "ctx_basics", "--answer-id", "seed"], "ID_MALFORMED"),
        (["--gate", "ctx_select_company", "--answer-id", "different_company"], "GATE_NOT_OWED"),
        (["--gate", "ctx_basics.stage", "--answer-id", "seed", "--note", "x" * 2001], "NOTE_INVALID"),
        (["--gate", "stage_confirmation", "--answer-id", "looks_right"], "WRITER_IS_OTHER_SCRIPT"),
        (["--gate", "ctx_basics.stage", "--answer-id", "seed", "--after-hold"], "AFTER_HOLD_NOT_HELD"),
        (["--gate", "dr_primary_deck", "--answer-id", "none_of_these"], "GATE_NOT_OWED"),
    ],
)
def test_answer_refusals_change_nothing(tmp_path: Path, args: list[str], code: str) -> None:
    suffix = "-quickcheck" if "dr_primary_deck" in args else ""
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review", suffix=suffix)
    before = h.snapshot(root, run_id)
    _rejected(root, run_id, h.record(root, run_id, "answer", *args), code, before)


def test_a_malformed_run_id_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    proc = h.record(root, "../x", "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed")
    assert proc.returncode == 1 and _out(proc)["code"] == "ID_MALFORMED"
    assert not root.exists()


def test_a_note_with_a_nul_is_refused(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    with pytest.raises(g.GateRejection) as e:
        _rec(root, run_id, "ctx_basics.stage", answer_ids=["seed"], note="a\x00b")
    assert e.value.code == "NOTE_INVALID"
    assert h.snapshot(root, run_id) == before


def test_not_applicable_is_only_for_a_model_owed_gate(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    proc = h.record(root, run_id, "not-applicable", "--gate", "ctx_basics.stage", "--reason", "known")
    _rejected(root, run_id, proc, "CLOSE_SCRIPT_OWED", before)
    proc = h.record(root, run_id, "not-applicable", "--gate", "dr_primary_deck", "--reason", "one file only")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    entry = h.ledger(root, run_id)["gates"]["dr_primary_deck"]
    assert entry["state"] == "not_owed"
    assert (entry["current"]["resolution"], entry["current"]["resolution_basis"]) == ("not_applicable", "model")


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--gate", "ctx_basics.stage", "--reason", "asked_not_to_be_asked"], "DEFAULT_REASON_INVALID"),
        (["--gate", "ctx_basics.stage", "--reason", "stated_in_request"], "DEFAULT_REASON_INVALID"),
        (["--gate", "ctx_basics.stage", "--reason", "made_up"], "DEFAULT_REASON_INVALID"),
        (["--gate", "ctx_basics.stage", "--reason", "start_fresh_by_default"], "DEFAULT_REASON_INVALID"),
    ],
)
def test_default_refusals(tmp_path: Path, args: list[str], code: str) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    _rejected(root, run_id, h.record(root, run_id, "default", *args), code, before)


def test_a_default_is_disclosed_and_an_answer_may_replace_it(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    proc = h.record(
        root, run_id, "default", "--gate", "ctx_basics.stage", "--reason", "stated_in_request", "--answer-id", "seed"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert "DEFAULT_TAKEN:ctx_basics.stage" in st["disclosures"]
    proc = h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "series_a")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    entry = h.ledger(root, run_id)["gates"]["ctx_basics.stage"]
    assert entry["current"]["answer_id"] == "series_a" and entry["current"]["resolution"] == "answered"
    assert [e["event"] for e in entry["history"]] == ["opened", "default_taken", "answered"]
    assert "DEFAULT_TAKEN:ctx_basics.stage" not in h.status(root, run_id)["disclosures"]


def test_answering_a_finished_run_is_refused(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    rs.update(rs.run_paths(str(root), run_id), rs.mark_complete)
    before = h.snapshot(root, run_id)
    proc = h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed")
    _rejected(root, run_id, proc, "RUN_FINISHED", before)
    proc = h.record(root, run_id, "open", "--gate", "ctx_basics.stage")
    _rejected(root, run_id, proc, "RUN_FINISHED", before)


def test_there_is_no_asked_evidence_flag(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    proc = h.record(
        root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed", "--asked-evidence", "plain_chat"
    )
    assert proc.returncode == 2
    assert h.snapshot(root, run_id) == before


# --- compare-and-set ------------------------------------------------------------------------------


def test_the_same_answer_is_unchanged_and_a_different_one_stands_refused(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    ans = ["--gate", "ctx_basics.stage", "--answer-id", "seed"]
    assert h.record(root, run_id, "answer", *ans).returncode == 0
    before = h.snapshot(root, run_id)
    again = h.record(root, run_id, "answer", *ans)
    assert again.returncode == 0 and _out(again)["unchanged"] is True
    assert h.snapshot(root, run_id) == before
    other = h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "series_a")
    _rejected(root, run_id, other, "ANSWER_STANDS", before)


def test_after_hold_replaces_a_held_answer_once(tmp_path: Path) -> None:
    # A held gate with two terminal options (market-sizing's methodology has one since its other two
    # options ask the question again).
    root, run_id, _rd = h.start_bound(tmp_path, "financial-model-review")
    _rec(root, run_id, "fmr_extracted_values", answer_ids=["values_ok"])
    with pytest.raises(g.GateRejection) as e:
        _rec(root, run_id, "fmr_extracted_values", answer_ids=["proceed_unreviewed"])
    assert e.value.code == "ANSWER_STANDS"
    _rec(root, run_id, "fmr_extracted_values", answer_ids=["proceed_unreviewed"], after_hold=True)
    entry = h.ledger(root, run_id)["gates"]["fmr_extracted_values"]
    assert entry["replaced_after_hold"] is True
    assert entry["current"]["asked_evidence"] == "after_hold"
    assert "replaced_after_hold" in [ev["event"] for ev in entry["history"]]
    before = h.snapshot(root, run_id)
    with pytest.raises(g.GateRejection) as e:
        _rec(root, run_id, "fmr_extracted_values", answer_ids=["values_ok"], after_hold=True)
    assert e.value.code == "AFTER_HOLD_USED"
    assert h.snapshot(root, run_id) == before


def test_a_changed_binding_supersedes_the_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "ic_verdict_decline")
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim")
    dims = run_dir / "score_dimensions.json"
    dims.write_text(json.dumps({"metadata": {"run_id": run_id}, "summary": {"verdict": "pass"}}))
    _rec(root, run_id, "ic_decline_confirmation", answer_ids=["finish"])
    first = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]
    assert first["current"]["binding"]["binder"] == "ic_score_dimensions"
    # The metadata is not part of what was confirmed.
    dims.write_text(json.dumps({"metadata": {"run_id": "other"}, "summary": {"verdict": "pass"}}))
    got = _tx(root, run_id, lambda ctx, ledger, st: g.require_terminal(ctx, ledger, "ic_decline_confirmation"))
    assert got == "ok"
    dims.write_text(json.dumps({"metadata": {"run_id": run_id}, "summary": {"verdict": "pass", "score": 1}}))
    got = _tx(root, run_id, lambda ctx, ledger, st: g.require_terminal(ctx, ledger, "ic_decline_confirmation"))
    assert got == "waiting"
    entry = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]
    assert entry["state"] == "open" and entry["supersessions"] == 1 and entry["current"] is None
    assert entry["opened_at"] > first["opened_at"]
    assert h.status(root, run_id)["status"] == "waiting"
    _rec(root, run_id, "ic_decline_confirmation", answer_ids=["hold_off"])
    assert h.status(root, run_id)["code"] == "GATE_INTERMEDIATE"


def test_a_stale_binding_lets_a_different_answer_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "ic_verdict_decline")
    root, run_id, run_dir = h.start_bound(tmp_path, "ic-sim")
    dims = run_dir / "score_dimensions.json"
    dims.write_text(json.dumps({"summary": {"verdict": "pass"}}))
    _rec(root, run_id, "ic_decline_confirmation", answer_ids=["finish"])
    dims.write_text(json.dumps({"summary": {"verdict": "decline"}}))
    out = _rec(root, run_id, "ic_decline_confirmation", answer_ids=["hold_off"])
    assert out["answer_id"] == "hold_off"
    events = [e["event"] for e in h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]["history"]]
    assert "superseded" in events


def test_requires_unmet_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "fmr_full_review")
    monkeypatch.setitem(g.REQUIRES, "fmr_corrections_audit", lambda ctx, entry: False)
    root, run_id, _rd = h.start_bound(tmp_path, "financial-model-review")
    before = h.snapshot(root, run_id)
    with pytest.raises(g.GateRejection) as e:
        _rec(root, run_id, "fmr_extracted_values", answer_ids=["corrections_applied"])
    assert e.value.code == "REQUIRES_UNMET"
    assert h.snapshot(root, run_id) == before


# --- open, batches, pre-answers ------------------------------------------------------------------


def test_open_is_batched_and_idempotent(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    first = h.record(root, run_id, "open", "--gate", "ctx_basics.stage", "--gate", "ctx_basics.sector")
    assert first.returncode == 0, first.stderr
    out = _out(first)
    assert out["opened"] == ["ctx_basics.stage", "ctx_basics.sector"]
    assert [n["gate"] for n in out["needs_input"]] == ["ctx_basics.stage", "ctx_basics.sector"]
    assert "--answer-id <option_id>" in out["needs_input"][0]["answer_command"]
    stamped = h.ledger(root, run_id)["gates"]["ctx_basics.stage"]["opened_at"]
    again = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.stage"))
    assert again["opened"] == [] and again["needs_input"][0]["gate"] == "ctx_basics.stage"
    assert h.ledger(root, run_id)["gates"]["ctx_basics.stage"]["opened_at"] == stamped
    st = h.status(root, run_id)
    assert (st["status"], st["code"], st["waiting_on"]) == ("waiting", "GATE_WAITING", "ctx_basics.stage")
    assert st["resumable"] == "same_session"
    assert st["resume_prompt"].startswith(f"Resume the deck-review run.\nFS_HOST_RUN_ID={run_id}\n")


def test_answer_is_all_or_nothing_across_segments(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    before = h.snapshot(root, run_id)
    proc = h.record(
        root,
        run_id,
        "answer",
        "--gate",
        "ctx_basics.stage",
        "--answer-id",
        "seed",
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "nope",
    )
    _rejected(root, run_id, proc, "OPTION_UNLISTED", before)
    proc = h.record(
        root,
        run_id,
        "answer",
        "--gate",
        "ctx_basics.stage",
        "--answer-id",
        "seed",
        "--gate",
        "ctx_basics.sector",
        "--answer-id",
        "different",
        "--value",
        "fintech",
        "--note",
        "said in the first message",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gates = h.ledger(root, run_id)["gates"]
    assert gates["ctx_basics.sector"]["current"]["value"] == "fintech"
    assert gates["ctx_basics.sector"]["current"]["note"] == "said in the first message"
    assert "asked_evidence" not in gates["ctx_basics.sector"]["current"]
    assert h.status(root, run_id)["status"] == "running"


def test_open_applies_a_stored_pre_answer(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review", lines="FS_HOST_ANSWER ctx_basics.stage=seed\n")
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.stage"))
    assert out["applied"] == "pre_answer" and out["needs_input"] == []
    entry = h.ledger(root, run_id)["gates"]["ctx_basics.stage"]
    assert entry["state"] == "answered" and entry["current"]["answer_id"] == "seed"
    assert h.ledger(root, run_id)["pre_answers"]["ctx_basics.stage"]["applied_at"]
    assert h.status(root, run_id)["status"] == "running"


def test_a_held_gate_pre_answer_records_host_line_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "ms_full_sizing")
    root, run_id, _rd = h.start_bound(tmp_path, "market-sizing", lines="FS_HOST_ANSWER ms_methodology=looks_good\n")
    out = _tx(root, run_id, lambda ctx, ledger, st: g.open_gates(ctx, ledger, ["ms_methodology"]))
    assert out["applied"] == "pre_answer"
    assert h.ledger(root, run_id)["gates"]["ms_methodology"]["current"]["asked_evidence"] == "host_line"


def test_a_pre_answer_naming_no_option_on_disk_waits_unlisted(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review", lines="FS_HOST_ANSWER ctx_select_company=gone-co\n")
    for slug in ("alpha-co", "beta-co"):
        (root / f"founder-context-{slug}.json").write_text(json.dumps({"company_name": slug.title()}))
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_select_company"))
    assert out["pre_answer_unlisted"] == ["ctx_select_company"]
    assert {o["id"] for o in out["needs_input"][0]["options"]} == {"alpha-co", "beta-co", "different_company"}
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("waiting", "PRE_ANSWER_UNLISTED")
    events = [e["event"] for e in h.ledger(root, run_id)["gates"]["ctx_select_company"]["history"]]
    assert "pre_answer_unlisted" in events
    assert h.record(root, run_id, "answer", "--gate", "ctx_select_company", "--answer-id", "beta-co").returncode == 0
    assert h.status(root, run_id)["code"] == "RUNNING"


def test_a_dedicated_writers_gate_opens_but_its_pre_answer_waits_for_that_writer(tmp_path: Path) -> None:
    lines = "FS_HOST_ANSWER stage_confirmation=looks_right\n"
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review", lines=lines)
    out = _out(h.record(root, run_id, "open", "--gate", "stage_confirmation"))
    assert out["opened"] == ["stage_confirmation"]
    assert out["pre_answer_applied_by"] == {"stage_confirmation": "gate_state.py"}
    assert out["needs_input"][0]["answer_command"] is None
    assert h.ledger(root, run_id)["gates"]["stage_confirmation"]["state"] == "open"
    assert g.pending_pre_answer(h.ledger(root, run_id), "stage_confirmation")["option_id"] == "looks_right"


def test_require_is_ok_waiting_or_not_owed(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    waiting = h.record(root, run_id, "require", "--gate", "ctx_basics.stage")
    assert waiting.returncode == 10 and _out(waiting)["blocked_by_gate"] == "ctx_basics.stage"
    assert h.status(root, run_id)["status"] == "waiting"
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    assert h.record(root, run_id, "require", "--gate", "ctx_basics.stage").returncode == 0
    assert h.record(root, run_id, "require", "--gate", "ctx_select_company").returncode == 11
    assert h.record(root, run_id, "open", "--gate", "ctx_select_company").returncode == 11


def test_an_unwired_gate_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate whose predicate is not written yet refuses to open and writes nothing. Made unwired here, so the
    test does not move each time a skill is wired."""
    root, run_id, _rd = h.start_bound(tmp_path, "competitive-positioning")
    monkeypatch.setitem(g.PREDICATES, "cp_gate3_triggered", None)
    before = h.snapshot(root, run_id)
    with pytest.raises(g.Unimplemented) as exc:
        _tx(root, run_id, lambda ctx, ledger, st: g.open_gates(ctx, ledger, ["cp_gate3_position"]))
    assert exc.value.code == "GATE_NOT_WIRED"
    assert h.snapshot(root, run_id) == before


def test_list_prints_the_contract_and_filters_by_skill(tmp_path: Path) -> None:
    proc = h.run(h.RECORD, "list")
    assert proc.returncode == 0
    assert proc.stdout == (h.REPO_ROOT / "founder-skills" / "data" / "host-contract.json").read_text(encoding="utf-8")
    only = _out(h.run(h.RECORD, "list", "--skill", "ic-sim"))
    assert {v["skill"] for v in only["gates"].values()} == {"ic-sim", "shared"}


def test_the_run_dir_locator_finds_the_ledger(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "deck-review")
    args = ["--run-id", run_id, "--run-dir", str(run_dir), "--gate", "ctx_basics.stage", "--answer-id", "seed"]
    proc = h.run(h.RECORD, "answer", *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    h.ledger_path(root, run_id).unlink()
    proc = h.run(h.RECORD, "show", "--run-id", run_id, "--run-dir", str(run_dir))
    assert proc.returncode == 2 and _out(proc)["code"] == "LEDGER_MISSING"


# --- effects, declines, reopen ---------------------------------------------------------------------


def _dr(root: Path, run_id: str, key: str, option: str, **kw: Any) -> Any:
    return _tx(
        root,
        run_id,
        lambda ctx, ledger, st: g.record(
            ctx, ledger, key, answer_ids=[option], writer="gate_state.py", by="gate_state.py", **kw
        ),
    )


def test_the_stage_gate_asks_the_stage_twice_through_its_registered_reopen(tmp_path: Path) -> None:
    """A second stage pick re-asks `stage_choice` only through `different_stage`'s registered reopen: the
    first pick is kept in history as superseded, and the confirmation ends answered with nothing open."""
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    paths = rs.run_paths(str(root), run_id)
    g.open_from_writer(paths, ["stage_confirmation"], "gate_state.py")
    for pick in ("seed", "series_a"):
        _dr(root, run_id, "stage_confirmation", "different_stage")
        st = h.status(root, run_id)
        assert (st["status"], st["waiting_on"]) == ("waiting", "stage_choice")
        _dr(root, run_id, "stage_choice", pick)
        # The re-emitted confirmation is still open on its intermediate answer: emitting it is a no-op.
        assert g.open_from_writer(paths, ["stage_confirmation"], "gate_state.py")["opened"] == ["stage_confirmation"]
        st = h.status(root, run_id)
        assert (st["waiting_on"], st["code"]) == ("stage_confirmation", "GATE_INTERMEDIATE")
    _dr(root, run_id, "stage_confirmation", "looks_right")
    assert h.status(root, run_id)["status"] == "running"
    choice = h.ledger(root, run_id)["gates"]["stage_choice"]
    assert choice["current"]["answer_id"] == "series_a" and choice["supersessions"] == 1
    events = [e["event"] for e in choice["history"]]
    assert events == ["opened", "answered", "superseded", "reopened", "answered"]
    assert rs.open_gate_ids(paths) == []


def test_opening_an_answered_gate_changes_nothing(tmp_path: Path) -> None:
    """`open` never re-asks a recorded answer: it reports it answered, and a different answer stays refused."""
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    before = h.snapshot(root, run_id)
    out = _out(h.record(root, run_id, "open", "--gate", "ctx_basics.stage"))
    assert out["answered"] == ["ctx_basics.stage"] and out["opened"] == [] and out["needs_input"] == []
    assert h.snapshot(root, run_id) == before
    paths = rs.run_paths(str(root), run_id)
    g.open_from_writer(paths, ["stage_confirmation"], "gate_state.py")
    _dr(root, run_id, "stage_confirmation", "looks_right")
    before = h.snapshot(root, run_id)
    assert g.open_from_writer(paths, ["stage_confirmation"], "gate_state.py")["answered"] == ["stage_confirmation"]
    assert h.snapshot(root, run_id) == before
    with pytest.raises(g.GateRejection) as e:
        _dr(root, run_id, "stage_confirmation", "different_stage")
    assert e.value.code == "ANSWER_STANDS"


def test_a_declining_answer_refuses_the_run(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    proc = h.record(root, run_id, "answer", "--gate", "dr_input_request.gated_link", "--answer-id", "stop")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = h.status(root, run_id)
    assert (st["status"], st["code"]) == ("refused", "FOUNDER_DECLINED")
    before = h.snapshot(root, run_id)
    proc = h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed")
    _rejected(root, run_id, proc, "RUN_FINISHED", before)


def test_a_late_gate_close_completes_a_coached_run(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "financial-model-review")
    assert h.record(root, run_id, "open", "--gate", "ctx_basics.stage").returncode == 0
    rs.update(rs.run_paths(str(root), run_id), lambda st: st.update(coaching="inserted"))
    assert h.status(root, run_id)["status"] == "waiting"
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    st = h.status(root, run_id)
    assert (st["status"], st["deliverables_status"]) == ("complete", "final")


def test_a_reopening_answer_starts_a_new_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "fmr_no_cash_balance")
    monkeypatch.setitem(g.REQUIRES, "fmr_cash_audit", lambda ctx, entry: True)
    root, run_id, _rd = h.start_bound(tmp_path, "financial-model-review")
    _rec(root, run_id, "fmr_cash_followup", resolution="default_taken", default_reason="producer_default_disclosed")
    paths = rs.run_paths(str(root), run_id)
    rs.update(paths, lambda st: (st.update(coaching="inserted", deliverables={"report_md": {}}), rs.mark_complete(st)))
    assert h.status(root, run_id)["status"] == "complete"
    _rec(root, run_id, "fmr_cash_followup", answer_ids=["provided"])
    # `provided` re-opens the two cash basics it answers; the same call records them (SKILL.md Step 12).
    assert h.status(root, run_id)["status"] == "waiting"
    _rec(root, run_id, "fmr_cash_basics.current_balance", answer_ids=["stated"], value="250000")
    _rec(root, run_id, "fmr_cash_basics.balance_date", answer_ids=["stated"], value="2026-09")
    st = h.status(root, run_id)
    assert (st["status"], st["revision"], st["coaching"]) == ("running", 1, None)
    assert st["deliverables"] is None and st["deliverables_status"] is None
    assert "DEFAULT_TAKEN:fmr_cash_followup" not in st["disclosures"]


# --- guards added after review -------------------------------------------------------------------


def test_require_on_a_complete_run_opens_nothing(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    rs.update(rs.run_paths(str(root), run_id), rs.mark_complete)
    before = h.snapshot(root, run_id)
    proc = h.record(root, run_id, "require", "--gate", "ctx_basics.stage")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_FINISHED"
    assert h.snapshot(root, run_id) == before


def test_open_exits_11_only_when_no_listed_gate_is_owed(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    assert h.record(root, run_id, "answer", "--gate", "ctx_basics.stage", "--answer-id", "seed").returncode == 0
    mixed = h.record(root, run_id, "open", "--gate", "ctx_basics.stage", "--gate", "ctx_select_company")
    assert mixed.returncode == 0, mixed.stdout
    assert _out(mixed)["answered"] == ["ctx_basics.stage"] and _out(mixed)["not_owed"] == ["ctx_select_company"]
    assert h.record(root, run_id, "open", "--gate", "ctx_select_company").returncode == 11


def test_after_hold_with_nothing_recorded_has_its_own_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owed(monkeypatch, "ms_full_sizing")
    root, run_id, _rd = h.start_bound(tmp_path, "market-sizing")
    with pytest.raises(g.GateRejection) as e:
        _rec(root, run_id, "ms_methodology", answer_ids=["looks_good"], after_hold=True)
    assert e.value.code == "AFTER_HOLD_NO_ANSWER"


def _bound_ic(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, Path]:
    _owed(monkeypatch, "ic_verdict_decline")
    root, run_id, run_dir = h.start_bound(tmp, "ic-sim")
    (run_dir / "score_dimensions.json").write_text(json.dumps({"summary": {"verdict": "pass"}}))
    _rec(root, run_id, "ic_decline_confirmation", answer_ids=["finish"])
    return root, run_id, run_dir


def test_after_hold_on_a_stale_binding_still_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, run_id, run_dir = _bound_ic(tmp_path, monkeypatch)
    (run_dir / "score_dimensions.json").write_text(json.dumps({"summary": {"verdict": "decline"}}))
    _rec(root, run_id, "ic_decline_confirmation", answer_ids=["hold_off"], after_hold=True)
    entry = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]
    assert entry["replaced_after_hold"] is True
    assert entry["current"]["asked_evidence"] == "after_hold"


def test_the_same_answer_to_a_changed_artifact_refreshes_its_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run_id, run_dir = _bound_ic(tmp_path, monkeypatch)
    old = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]["current"]["binding"]
    (run_dir / "score_dimensions.json").write_text(json.dumps({"summary": {"verdict": "decline"}}))
    out = _rec(root, run_id, "ic_decline_confirmation", answer_ids=["finish"])
    assert not out.get("unchanged")
    entry = h.ledger(root, run_id)["gates"]["ic_decline_confirmation"]
    assert entry["current"]["binding"] != old and entry["supersessions"] == 1
    got = _tx(root, run_id, lambda ctx, ledger, st: g.require_terminal(ctx, ledger, "ic_decline_confirmation"))
    assert got == "ok"


def test_the_same_answer_with_a_new_note_records_the_note(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "deck-review")
    ans = ["--gate", "ctx_basics.stage", "--answer-id", "seed"]
    assert h.record(root, run_id, "answer", *ans).returncode == 0
    proc = h.record(root, run_id, "answer", *ans, "--note", "the deck says so")
    assert proc.returncode == 0 and _out(proc)["unchanged"] is False
    entry = h.ledger(root, run_id)["gates"]["ctx_basics.stage"]
    assert entry["current"]["note"] == "the deck says so"
    assert entry["history"][-1]["event"] == "note_added"


def test_an_unanswered_pool_basis_question_takes_the_first_option(tmp_path: Path) -> None:
    """Asked and not answered: the first option. Never asked: the stated basis, else pre-money."""
    root, run_id, _rd = h.start_bound(tmp_path, "cap-table")
    gate = g.GATES["ct_pool_basis"]
    assert g.resolve_default("ct_pool_basis", gate, "asked_unanswered", None) == "post_money"
    assert g.resolve_default("ct_pool_basis", gate, "producer_default_disclosed", None) == "pre_money"
    assert g.resolve_default("ct_pool_basis", gate, "asked_not_to_be_asked", None) == "pre_money"
    with pytest.raises(g.GateRejection):
        g.resolve_default("ct_pool_basis", gate, "asked_unanswered", "pre_money")
    with pytest.raises(g.GateRejection):
        g.resolve_default("ct_option_pool", g.GATES["ct_option_pool"], "asked_unanswered", None)


# --- settle_owed: an open gate the run no longer owes is closed; owed again, it is asked again --------------


def _pct_warning(run_dir: Path, run_id: str, *, on: bool) -> None:
    warnings = [{"field": "target_pct", "code": "IMPLAUSIBLE_PCT_SCALE", "message": "x"}] if on else []
    body = {"validation": {"status": "valid", "errors": [], "warnings": warnings}, "metadata": {"run_id": run_id}}
    (run_dir / "sizing.json").write_text(json.dumps(body), encoding="utf-8")


def test_a_gate_the_run_stops_owing_is_closed_by_a_read_only_transaction(tmp_path: Path) -> None:
    """The strand: a gate open, then not owed, and every call that could clear it either writes nothing (an
    enforcer's require returns not owed) or is refused as not owed. The pass runs on every transaction."""
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing")
    key = "ms_pct_scale.target_pct"
    _pct_warning(run_dir, run_id, on=True)
    _tx(root, run_id, lambda ctx, ledger, st: g.open_gates(ctx, ledger, [key]))
    assert h.status(root, run_id)["waiting_on"] == key
    _pct_warning(run_dir, run_id, on=False)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    entry = h.ledger(root, run_id)["gates"][key]
    assert entry["state"] == "not_owed" and entry["current"]["resolution_basis"] == "script"
    assert h.status(root, run_id)["status"] == "running"


def test_a_transaction_with_nothing_to_settle_writes_nothing(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "market-sizing")
    before = h.snapshot(root, run_id)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    assert h.snapshot(root, run_id) == before


def test_a_gate_closed_as_not_owed_is_asked_again_once_owed_and_never_read_as_answered(tmp_path: Path) -> None:
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing")
    key = "ms_pct_scale.target_pct"
    _pct_warning(run_dir, run_id, on=True)
    _tx(root, run_id, lambda ctx, ledger, st: g.open_gates(ctx, ledger, [key]))
    _pct_warning(run_dir, run_id, on=False)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    _pct_warning(run_dir, run_id, on=True)
    got = _tx(root, run_id, lambda ctx, ledger, st: g.require_terminal(ctx, ledger, key))
    assert got == "waiting", "an enforcer must not read the closure as an answer"
    entry = h.ledger(root, run_id)["gates"][key]
    assert entry["state"] == "open" and entry["current"] is None
    assert [e["reason"] for e in entry["history"] if e["event"] == "superseded"] == ["owed_again"]
    assert h.status(root, run_id)["waiting_on"] == key


def test_a_gate_answered_and_then_not_owed_keeps_its_answer(tmp_path: Path) -> None:
    """Only an OPEN gate is closed, and only one the pass closed is re-opened: an answer stands."""
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing")
    key = "ms_pct_scale.target_pct"
    _pct_warning(run_dir, run_id, on=True)
    _rec(root, run_id, key, answer_ids=["as_given"])
    _pct_warning(run_dir, run_id, on=False)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    _pct_warning(run_dir, run_id, on=True)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    entry = h.ledger(root, run_id)["gates"][key]
    assert entry["state"] == "answered" and entry["current"]["answer_id"] == "as_given"


def test_a_finished_run_is_never_settled(tmp_path: Path) -> None:
    """A gate the pass closed, owed again only after the run completed: a read-only `require` on the complete
    run changes nothing (no re-open the run could never answer) and the run stays complete."""
    root, run_id, run_dir = h.start_bound(tmp_path, "market-sizing")
    key = "ms_pct_scale.target_pct"
    _pct_warning(run_dir, run_id, on=True)
    _tx(root, run_id, lambda ctx, ledger, st: g.open_gates(ctx, ledger, [key]))
    _pct_warning(run_dir, run_id, on=False)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    assert h.ledger(root, run_id)["gates"][key]["state"] == "not_owed"
    rs.update(rs.run_paths(str(root), run_id), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    _pct_warning(run_dir, run_id, on=True)
    before = h.snapshot(root, run_id)
    _tx(root, run_id, lambda ctx, ledger, st: None)
    # The run's one unanswered question is refused, not asked: nothing loops on a delivered run.
    proc = h.record(root, run_id, "require", "--gate", "ms_methodology")
    assert proc.returncode == 1 and json.loads(proc.stdout)["code"] == "RUN_FINISHED", proc.stdout
    assert h.snapshot(root, run_id) == before
    assert h.status(root, run_id)["status"] == "complete"
    assert h.ledger(root, run_id)["gates"][key]["state"] == "not_owed"


def test_not_applicable_takes_several_gates_all_or_none(tmp_path: Path) -> None:
    root, run_id, _rd = h.start_bound(tmp_path, "competitive-positioning")
    before = h.snapshot(root, run_id)
    args = ("--gate", "cp_product_profile.product", "--gate", "cp_gate1_landscape", "--reason", "stated")
    mixed = h.record(root, run_id, "not-applicable", *args)
    _rejected(root, run_id, mixed, "CLOSE_SCRIPT_OWED", before)
    keys = [f"cp_product_profile.{f}" for f in ("product", "customers", "differentiation")]
    proc = h.record(root, run_id, "not-applicable", *[a for k in keys for a in ("--gate", k)], "--reason", "stated")
    assert proc.returncode == 0 and len(_out(proc)["gates"]) == 3
    assert all(h.ledger(root, run_id)["gates"][k]["state"] == "not_owed" for k in keys)
