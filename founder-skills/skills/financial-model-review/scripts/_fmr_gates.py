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
    "this review is complete and a figure it confirmed has changed since; only a first newer cash balance or "
    "its date, given in the conversation that delivered it, updates it in place: any other changed figure "
    "starts a new review (run Step 0 again)"
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


CASH_PATHS = frozenset(("cash.current_balance", "cash.balance_date"))
UNCHANGED_MESSAGE = "this review is complete and already uses these values; there is nothing to apply and no rerun"


def refuse_finished_corrections(run_dir: str, run_id: str | None, paths_set: set[str], changed: int) -> None:
    """Corrections into a finished run: exit 1 `RUN_FINISHED` before anything is written, so the corrected
    inputs never move under a delivered review. The one exception is the cash update: a call that sets both
    cash paths and nothing else (the follow-up's answer needs both), changes one of them, on a review that
    is `complete` (a full review: the follow-up is that mode's) and whose follow-up was never answered with
    the founder's reply (it asked for the balance, or the review had one and this is a newer balance or date).
    Once per review: an answered follow-up means a new review. Not on a run whose request said not to ask (its
    follow-up cannot be answered), and not from a folder other than the run's own (an archived copy). A run
    with no ledger, or one still running, returns at once."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger
    rs = sys.modules["_run_status"]

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        state = st.get("status")
        if state not in rs.FINAL_STATUSES:
            return {}
        if state == "complete" and paths_set == CASH_PATHS and changed >= 1 and not gates.no_ask(led):
            entry = (led.get("gates") or {}).get(CASH_FOLLOWUP) or {}
            replied = (entry.get("current") or {}).get("resolution") == "answered"
            own = isinstance(ctx.run_dir, str) and os.path.realpath(ctx.run_dir) == os.path.realpath(run_dir)
            if not replied and own and st.get("mode") in (None, "full"):
                return {}
        return {"finished": state}

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001 -- unreachable registry, unwired predicate: exit 2, nothing written
        sys.exit(_run_ref.report_failure(e))
    if out.get("finished"):
        message = UNCHANGED_MESSAGE if changed == 0 else FINISHED_MESSAGE
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_FINISHED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def refuse_without_run_id(output: str | None, run_id: str | None) -> None:
    """A call into a run dir that carries any run's ref must name its run: exit 1 `RUN_ID_REQUIRED`. A named run
    must be bound there (`RUN_NOT_BOUND`) and be the folder's current run (`RUN_SUPERSEDED`):
    `_run_ref.refuse_not_this_runs`."""
    if output is None:
        return
    run_dir = os.path.dirname(os.path.abspath(output))
    if run_id:
        _run_ref.refuse_not_this_runs(run_dir, run_id, noun="review dir")
        return
    if glob.glob(os.path.join(glob.escape(run_dir), "handoff", "*", _run_ref.RUN_REF_NAME)):
        message = "this review dir belongs to a run; pass its --run-id so the run's checks apply"
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_REQUIRED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def values_record(run_dir: str) -> dict[str, Any] | None:
    """What the run's ledger holds for the values check, for the report: `{run_id, answer_id, resolution,
    by_request, origin, cash_reply_seq, revision}` (`answer_id` None when it is not answered;
    `cash_reply_seq` the history line the cash follow-up's recorded reply came from, or None; `revision` the
    run status's); None with no ledger. Read only."""
    run_id = run_id_of(run_dir)
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    led = gates.load_ledger(paths)
    entry = (led.get("gates") or {}).get(VALUES_GATE)
    answered = isinstance(entry, dict) and entry.get("state") == "answered"
    cur = (entry.get("current") or {}) if answered and isinstance(entry, dict) else {}
    cash = ((led.get("gates") or {}).get(CASH_FOLLOWUP) or {}).get("current") or {}
    status = sys.modules["_run_status"].load_status(paths) or {}
    return {
        "run_id": run_id,
        "answer_id": cur.get("answer_id"),
        "resolution": cur.get("resolution"),
        "by_request": gates.answered_by_request(led, VALUES_GATE),
        "origin": (cur.get("evidence") or {}).get("origin"),
        "cash_reply_seq": (cash.get("evidence") or {}).get("history_seq")
        if cash.get("resolution") == "answered"
        else None,
        "revision": int(status.get("revision") or 0),
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
    the follow-up a default, or a newer balance or date was given after delivery and the follow-up holds no
    reply: the founder's reply was used but never recorded, so compose refuses (exit 10, nothing written) and
    names the record to make -- the reply IS the answer; it is not asked again. Residual: the producers can
    still rewrite runway.json on the complete run before the record; compose is where the founder's report is
    held."""
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
    if status.get("status") != "complete" or resolution == "answered":
        return
    # A newer balance or date given after delivery and never recorded: rebuilding the delivered review in place
    # would replace it at the same revision with no reopen, so the record comes first.
    try:
        unrecorded = resolution == "default_taken" or (
            gates.transact(paths, lambda ctx, led, st: gates.fmr_post_delivery_cash_call(ctx)) is not None
        )
    except Exception as e:  # noqa: BLE001 -- an undecidable delivery time: exit 2, nothing written
        sys.exit(_run_ref.report_failure(e))
    if unrecorded:
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
