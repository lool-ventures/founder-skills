"""financial-model-review's gate checks, shared by its producers, compose and the closer.

Every function here acts only when the run dir carries this run's `handoff/<RUN_ID>/run_ref.json`
(`_run_ref.has_ledger`); with none it returns at once and loads nothing, so a run without a ledger behaves
exactly as before. The shared modules are loaded by path through `_run_ref`, never imported.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

VALUES_GATE = "fmr_extracted_values"
CASH_GATES = ("fmr_cash_basics.current_balance", "fmr_cash_basics.balance_date", "fmr_cash_basics.monthly_burn")
CASH_FOLLOWUP = "fmr_cash_followup"

# A changed figure after the review was delivered: the enforcer will not re-open a finished run's answer.
FINISHED_MESSAGE = (
    "this review is complete and a figure it confirmed has changed since; a changed figure starts a new review "
    "(run Step 0 again)"
)


def run_id_of(run_dir: str) -> str | None:
    """The run id this run dir's inputs carry."""
    return _run_ref.json_run_id(os.path.join(run_dir, "inputs.json"))


def open_ledger_or_exit(run_dir: str, run_id: str | None) -> Any:
    """(the shared `_gates`, the run's paths), or None with no ledger. A ref whose ledger cannot be reached
    exits 2 here, before anything is written."""
    try:
        return _run_ref.open_ledger(os.path.abspath(run_dir), run_id)
    except _run_ref.LedgerUnavailable as e:
        sys.exit(_run_ref.report_failure(e))


def require_or_exit(run_dir: str, run_id: str | None, keys: tuple[str, ...]) -> None:
    """Exit 10 (stdout JSON naming the gate, with `needs_input`; nothing written) when one of `keys` has no
    record for this run, or its record no longer matches what it confirmed; exit 1 on a finished run whose
    confirmed input changed. Returns with nothing to do when the run has no ledger, or the gates do not
    apply to this run's mode."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        for key in keys:
            if gates.require_terminal(ctx, led, key, by="financial-model-review") == "waiting":
                return {"key": key, "exit": gates.waiting_exit(ctx, led, key)}
        return {}

    try:
        out = gates.transact(paths, fn)
    except gates.GateRejection as e:
        if e.code == "RUN_FINISHED":
            sys.stdout.write(
                json.dumps({"status": "rejected", "code": "RUN_FINISHED", "message": FINISHED_MESSAGE}) + "\n"
            )
            print(f"Error: {FINISHED_MESSAGE}; nothing was written", file=sys.stderr)
            sys.exit(1)
        sys.exit(_run_ref.report_failure(e))
    except Exception as e:  # noqa: BLE001 -- unreachable registry, unwired predicate: exit 2, nothing written
        sys.exit(_run_ref.report_failure(e))
    if out.get("key"):
        gates.print_waiting_and_exit(
            out["exit"],
            f"Waiting: {out['key']} has no answer for this run yet; ask it, record the answer, then run this "
            "again. Nothing was written.",
        )


def refuse_without_run_id(output: str | None, run_id: str | None) -> None:
    """A call into a run dir that carries any run's ref must name its run: exit 1 `RUN_ID_REQUIRED`."""
    if output is None or run_id:
        return
    run_dir = os.path.dirname(os.path.abspath(output))
    if glob.glob(os.path.join(glob.escape(run_dir), "handoff", "*", _run_ref.RUN_REF_NAME)):
        message = "this review dir belongs to a run; pass its --run-id so the run's checks apply"
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_REQUIRED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def values_record(run_dir: str) -> dict[str, Any] | None:
    """What the run's ledger holds for the values check, for the report: `{run_id, answer_id, resolution,
    by_request, origin}` (`answer_id` None when it is not answered); None with no ledger. Read only."""
    run_id = run_id_of(run_dir)
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    led = gates.load_ledger(paths)
    entry = (led.get("gates") or {}).get(VALUES_GATE)
    answered = isinstance(entry, dict) and entry.get("state") == "answered"
    cur = (entry.get("current") or {}) if answered and isinstance(entry, dict) else {}
    return {
        "run_id": run_id,
        "answer_id": cur.get("answer_id"),
        "resolution": cur.get("resolution"),
        "by_request": gates.answered_by_request(led, VALUES_GATE),
        "origin": (cur.get("evidence") or {}).get("origin"),
    }


def refuse_open_gates(ledger: Any) -> None:
    """A question the run opened and never recorded leaves it unable to complete, so compose refuses before
    writing anything and names it (exit 10). The run reads `running` with `GATE_UNRESOLVED`: never a `waiting`
    no host answer could clear."""
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
    print(
        f"Error: {key} was asked and never recorded; record the reply with its printed answer_command, then "
        "compose again. Nothing was written.",
        file=sys.stderr,
    )
    sys.exit(gates.EXIT_CODES["waiting"])


def settle_cash_followup(ledger: Any, no_cash_balance: bool) -> None:
    """The cash follow-up, after a successful compose and before any write.

    Runway still lacks the balance: the follow-up is recorded at once as the producer's disclosed default, so
    it never sits open (nobody may ever answer it). Runway now has it, on a run that is still `complete` with
    the follow-up a default: the founder's reply was used but never recorded, so compose refuses (exit 10,
    nothing written) and names the record to make -- the reply IS the answer; it is not asked again."""
    gates, paths = ledger
    led = gates.load_ledger(paths)
    entry = (led.get("gates") or {}).get(CASH_FOLLOWUP) or {}
    resolution = (entry.get("current") or {}).get("resolution")
    if no_cash_balance:
        if entry.get("state") in ("answered", "not_owed"):
            return

        def record(ctx: Any, ledger_: dict[str, Any], st: dict[str, Any]) -> Any:
            return gates.record(
                ctx,
                ledger_,
                CASH_FOLLOWUP,
                resolution="default_taken",
                default_reason="producer_default_disclosed",
                by="compose_report.py",
            )

        gates.transact(paths, record)
        return
    status = sys.modules["_run_status"].load_status(paths) or {}
    if status.get("status") == "complete" and resolution == "default_taken":
        message = (
            "the founder's cash balance reached this report but its answer was never recorded; record `provided` "
            "with Step 12's three-part answer command (the founder's reply is the answer: do not ask again), then "
            "compose again"
        )
        sys.stdout.write(
            json.dumps(
                {"status": "waiting", "code": "GATE_WAITING", "blocked_by_gate": CASH_FOLLOWUP, "message": message}
            )
            + "\n"
        )
        print(f"Error: {message}. Nothing was written.", file=sys.stderr)
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


def stamp_handed_over(report_path: str) -> None:
    """The closer printed the hand-over: `handed_over_at`. A failure is one stderr line; stdout is unchanged."""
    run_dir = os.path.dirname(os.path.abspath(report_path))
    run_id = run_id_of(run_dir)
    if not _run_ref.has_ledger(run_dir, run_id):
        return
    try:
        rs = _run_ref.load_shared("_run_status")
        paths = rs.locate_from_run_dir(run_dir, run_id)
        rs.update(paths, lambda st: st.update(handed_over_at=rs.now_iso()))
    except Exception as exc:  # noqa: BLE001 -- the hand-over is printed whatever happens here
        print(f"warning: the hand-over time was not recorded in the run status: {exc}", file=sys.stderr)
