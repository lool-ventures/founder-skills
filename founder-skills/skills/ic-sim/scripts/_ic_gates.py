"""ic-sim's gate checks, shared by fund_profile.py, compose and the page.

Every function here acts only when the simulation dir carries this run's `handoff/<RUN_ID>/run_ref.json`
(`_run_ref.has_ledger`); with none it returns at once and loads nothing, so a run without a ledger behaves
exactly as before. The shared modules are loaded by path through `_run_ref`, never imported. Skill scripts
cannot import across skills, so `refuse_open_gates` and `coaching_pending` are copies of market-sizing's
(`_ms_gates.py`), held to them by a test.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

MODE_GATE = "ic_mode"
FUND_GATE = "ic_fund_mode"
DECLINE_GATE = "ic_decline_confirmation"
# The files every simulation writes before compose, each stamped with the run's id (compose's required set).
RUN_ARTIFACTS = (
    "startup_profile.json",
    "fund_profile.json",
    "conflict_check.json",
    "discussion.json",
    "score_dimensions.json",
)
# The fund question's answer, as fund_profile.json's `mode` states it.
FUND_MODES = {"generic": "generic", "specific": "fund_specific"}

# A simulation already delivered is never written into again: new materials start a new one.
FINISHED_MESSAGE = (
    "this simulation is complete; a re-run with new materials or a changed score is a new simulation (run Step 0 "
    "again, without this run's FS_HOST_RUN_ID)"
)


def run_id_of(sim_dir: str) -> str | None:
    """The run id the simulation's files agree on: the one more than half of `RUN_ARTIFACTS` that carry a
    valid id carry. None when none carries one, or when they disagree with no majority: a model-written
    profile with an unfilled id, or an earlier run's file left beside this run's, never decides it alone."""
    ids = []
    for name in RUN_ARTIFACTS:
        rid = _run_ref.json_run_id(os.path.join(sim_dir, name))
        if rid is not None and _run_ref.RUN_ID_RE.match(rid):
            ids.append(rid)
    if not ids:
        return None
    rid, n = Counter(ids).most_common(1)[0]
    return rid if n * 2 > len(ids) else None


def refuse_without_run_id(sim_dir: str, run_id: str | None) -> None:
    """A simulation dir that carries any run's ref must say which run it is: exit 1 `RUN_ID_REQUIRED`."""
    if run_id:
        return
    if glob.glob(os.path.join(glob.escape(os.path.abspath(sim_dir)), "handoff", "*", _run_ref.RUN_REF_NAME)):
        message = (
            "this simulation dir belongs to a run, and its files do not agree on which; stamp each with this run's "
            "id (the producers' --run-id) so the run's checks apply"
        )
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_REQUIRED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def open_ledger_or_exit(sim_dir: str, run_id: str | None) -> Any:
    """(the shared `_gates`, the run's paths), or None with no ledger. A ref whose ledger cannot be reached
    exits 2 here, before anything is written."""
    try:
        return _run_ref.open_ledger(os.path.abspath(sim_dir), run_id)
    except _run_ref.LedgerUnavailable as e:
        sys.exit(_run_ref.report_failure(e))


def _finished() -> NoReturn:
    sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_FINISHED", "message": FINISHED_MESSAGE}) + "\n")
    print(f"Error: {FINISHED_MESSAGE}; nothing was written", file=sys.stderr)
    sys.exit(1)


def exit_on_rejection(gates: Any, e: Exception) -> NoReturn:
    """A refused gate step: RUN_FINISHED as a plain refusal (exit 1), anything else as the shared failure."""
    if isinstance(e, gates.GateRejection) and e.code == "RUN_FINISHED":
        _finished()
    sys.exit(_run_ref.report_failure(e))


def _why(key: str, entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict) or entry.get("state") is None:
        return "has no answer for this run yet; ask it, record the answer, then run this again"
    cur = entry.get("current") or {}
    if key == DECLINE_GATE and cur.get("answer_id") == "hold_off":
        return (
            "was answered `Hold off`: wait for the founder, then record `finish` or fold in what they add "
            "(Step 8.5), then run this again"
        )
    if entry.get("supersessions"):
        return "was answered, but the scores it confirmed have changed since; ask it again, record it, run this again"
    return "has no answer for this run yet; ask it, record the answer, then run this again"


def require_or_exit(sim_dir: str, run_id: str | None, keys: list[str], *, by: str) -> Any:
    """With a ledger: exit 1 `RUN_FINISHED` when the run is already complete (nothing of a delivered
    simulation is written again); exit 10 (stdout JSON naming the gate, with `needs_input`; nothing written)
    when one of `keys` has no terminal record for this run or its record no longer matches what it confirmed.
    Returns the ledger, or None when the run has none."""
    ledger = open_ledger_or_exit(sim_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    rs = sys.modules["_run_status"]
    if (rs.load_status(paths) or {}).get("status") in rs.FINAL_STATUSES:
        _finished()

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        for key in keys:
            if gates.require_terminal(ctx, led, key, by=by) == "waiting":
                return {"key": key, "exit": gates.waiting_exit(ctx, led, key)}
        return {}

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001 -- RUN_FINISHED, an undecidable verdict, unreachable registry
        exit_on_rejection(gates, e)
    if out.get("key"):
        entry = (gates.load_ledger(paths).get("gates") or {}).get(out["key"])
        gates.print_waiting_and_exit(
            out["exit"],
            f"Waiting: {out['key']} {_why(out['key'], entry)}. Nothing was written.",
        )
    return ledger


def fund_choice_or_exit(ledger: Any, profile_mode: Any) -> None:
    """fund_profile.json's `mode` must be the fund the founder chose (`ic_fund_mode`): exit 1
    `GATE_RECORD_MISMATCH`, nothing written, when it is not."""
    gates, paths = ledger
    entry = (gates.load_ledger(paths).get("gates") or {}).get(FUND_GATE) or {}
    answer = (entry.get("current") or {}).get("answer_id")
    expected = FUND_MODES.get(str(answer))
    if expected is None or profile_mode == expected:
        return
    message = (
        f"the fund recorded for this run is {answer!r}, so the profile's mode must be {expected!r}, not "
        f"{profile_mode!r}; rebuild the profile for the recorded choice (a founder who now wants the other kind "
        "of fund starts a new simulation)"
    )
    sys.stdout.write(json.dumps({"status": "rejected", "code": "GATE_RECORD_MISMATCH", "message": message}) + "\n")
    print(f"Error: {message}; nothing was written", file=sys.stderr)
    sys.exit(1)


def refuse_open_gates(ledger: Any) -> None:
    """A question the run opened and never recorded leaves it unable to complete, so compose refuses before
    writing anything and names it (exit 10). The status it reads is settled: compose's own require
    transaction, which runs first, closes any gate the run no longer owes. The run reads `running` with
    `GATE_UNRESOLVED`: never a `waiting` no host answer could clear."""
    gates, paths = ledger
    rs = sys.modules["_run_status"]
    open_now = rs.open_gate_ids(paths)
    if not open_now:
        return
    if gates.no_ask(gates.load_ledger(paths)):
        # The request said not to ask: what it carried is applied; anything still open leaves the run waiting.
        try:
            stop = gates.settle_open_for_no_ask(paths)
        except Exception as e:  # noqa: BLE001 -- a request stop still pending (REQUEST_DECLINED): exit 1, no trace
            sys.exit(_run_ref.report_failure(e))
        if stop is None:
            return
        gates.print_waiting_and_exit(stop)
    key = open_now[0]
    needs = gates.transact(paths, lambda ctx, led, st: gates.needs_input(ctx, led, key))

    def unresolved(st: dict[str, Any]) -> None:
        if st.get("status") in rs.FINAL_STATUSES:
            return
        rs.set_state(st, "running", "RUNNING")
        st["last_error_code"] = "GATE_UNRESOLVED"

    try:
        rs.update(paths, unresolved)
    except Exception as exc:  # noqa: BLE001 -- a status write never changes what compose prints
        print(f"warning: the run status was not updated: {exc}", file=sys.stderr)
    sys.stdout.write(
        json.dumps({"status": "running", "code": "GATE_UNRESOLVED", "blocked_by_gate": key, "needs_input": [needs]})
        + "\n"
    )
    how = (
        "record the reply with its printed answer_command"
        if needs.get("answer_command")
        else f"record it with {needs.get('recorded_by')}"
    )
    print(
        f"Error: {key} was asked and never recorded; {how}, then compose again. Nothing was written.", file=sys.stderr
    )
    sys.exit(gates.EXIT_CODES["waiting"])


def coaching_pending(ledger: Any) -> None:
    _gates, paths = ledger
    rs = sys.modules["_run_status"]

    def pending(st: dict[str, Any]) -> None:
        if st.get("status") not in rs.FINAL_STATUSES:
            st["coaching"] = "pending"

    try:
        rs.update(paths, pending)
    except Exception as exc:  # noqa: BLE001 -- a status write never changes what compose prints
        print(f"warning: the run status was not updated: {exc}", file=sys.stderr)
