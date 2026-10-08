"""cap-table's gate checks, shared by its producers, compose and the extraction-only renderer.

Every function here acts only when the review dir carries this run's `handoff/<RUN_ID>/run_ref.json`
(`_run_ref.has_ledger`); with none it returns at once and loads nothing, so a run without a ledger behaves exactly
as before. The shared modules are loaded by path through `_run_ref`, never imported. Skill scripts cannot import
across skills, so `refuse_open_gates` and `coaching_pending` are copies of market-sizing's (`_ms_gates.py`), held
to them by a test.

A what-if on a delivered review (a new scenario, another pool) re-runs the scenario solver and compose on the same
run: the step re-opens the run as a new revision first (`reopen_if_complete`), and a request that asks for
something a recorded answer rules out re-opens that question (`what_if_or_mismatch`), to be asked again.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

ENGAGEMENT = "ct_engagement_mode"
JURISDICTION = "ct_jurisdiction"
IIA = "ct_iia_grants"
POOL_EXISTS = "ct_option_pool"
CAP_BASE = "ct_cap_base_confirmation"
SELECTION = "ct_scenario_selection"
TOPUP = "ct_pool_topup_intent"
BASIS = "ct_pool_basis"
REMEDY = "ct_pool_basis_remedy"
SAFE_TERMS = "ct_safe_terms"
S102 = "ct_s102_grant_route"
FORK = "ct_no_cap_base_fork"
TRACKED = "ct_docx_tracked_changes"
CONFIRM = "ct_extraction_confirmation"
# The confirmation instances extract_instrument.py decides from the extraction it is about to save. Never
# `aoa_fields`: the model opens that one for an AoA's batch, so requiring it would open it on every extraction.
CONFIRM_KEYS = (f"{CONFIRM}.flagged_fields", f"{CONFIRM}.unverifiable_doc", f"{CONFIRM}.ambiguities")
NOTE_GATES = (
    "ct_note_cap_denominator",
    "ct_note_maturity_default",
    "ct_note_qualified_threshold",
    "ct_note_interest_type",
    "ct_note_interest_converts",
)
# What cap_state.py rests on (each gate's modes decide which apply).
BASE_KEYS = (ENGAGEMENT, JURISDICTION, IIA, POOL_EXISTS, CAP_BASE)
# What the scenario solver rests on.
SCENARIO_KEYS = (SELECTION, *NOTE_GATES, SAFE_TERMS, TOPUP, BASIS, S102)
# Everything compose requires. Never a question only a script or the model opens (tracked changes, the pool-basis
# remedy, the extraction confirmations, founder facts, counsel items, column mappings) and never the Step-0
# routing question: a `require` would open them on every run. An open one is caught by `refuse_open_gates`.
COMPOSE_KEYS = (*BASE_KEYS, *SCENARIO_KEYS)
# The scenario type each selection option allows. A note converts inside the priced round (one request).
SELECTION_TYPES = {
    "cap_implied_safe": ("safe_conversion",),
    "priced_round": ("priced_round",),
    "note_conversion": ("note_conversion", "priced_round"),
    "flip": ("flip",),
}
# The pool bases a recorded `ct_pool_basis` names; the other two are the solver's refusals (the remedy).
RECORDED_BASES = ("post_money", "post_money_increase", "pre_money")
REMEDY_PARAMS = {"custom_basis_stated_by_founder": "custom", "excluding_basis_modeled_as": "excluding"}
REMEDY_OPTIONS = {"custom": "state_measure", "excluding": "show_post_money"}
REMEDY_CODES = {"E_POOL_BASIS_NOT_MODELED": "custom", "E_POOL_BASIS_EXCLUDING_NOT_MODELED": "excluding"}

FINISHED_MESSAGE = (
    "this review is complete and the cap base it rests on has changed since; a changed base is a new review "
    "(run Step 0 again)"
)


def run_dir_of(path: str) -> str:
    return os.path.dirname(os.path.abspath(path))


def refuse_without_run_id(run_dir: str, run_id: str | None) -> None:
    """A review dir that carries any run's ref must be called with its run's id: exit 1 `RUN_ID_REQUIRED`. An
    empty `--run-id` (a fresh shell after a compaction) is refused, never read as "no ledger"."""
    if run_id:
        return
    if glob.glob(os.path.join(glob.escape(os.path.abspath(run_dir)), "handoff", "*", _run_ref.RUN_REF_NAME)):
        message = (
            "this review dir belongs to a run; pass its --run-id (the run_id Step 0 printed) so the run's checks "
            "apply. After a context reset, re-read the skill from its base directory first"
        )
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_REQUIRED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def open_ledger_or_exit(run_dir: str, run_id: str | None) -> Any:
    """(the shared `_gates`, the run's paths), or None with no ledger. A ref whose ledger cannot be reached exits
    2 here, before anything is written."""
    try:
        return _run_ref.open_ledger(os.path.abspath(run_dir), run_id)
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


def _why(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict) or entry.get("state") is None:
        return "has no answer for this run yet"
    if entry.get("current") is not None:
        return "was answered with a reply that asks it again once the change is made"
    if entry.get("supersessions"):
        return "was answered, but what it confirmed has changed since"
    return "has no answer for this run yet"


def require_or_exit(run_dir: str, run_id: str | None, keys: list[str] | tuple[str, ...], *, by: str) -> Any:
    """Exit 10 (stdout JSON naming the gate, with `needs_input`; nothing written) when one of `keys` has no
    terminal record for this run or its record no longer matches what it confirmed; exit 1 on a finished run
    whose confirmed input changed. Returns the ledger, or None when the run has none."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        for key in keys:
            if gates.require_terminal(ctx, led, key, by=by) == "waiting":
                return {"key": key, "needs": gates.needs_input(ctx, led, key)}
        return {}

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001 -- RUN_FINISHED, undecidable, unreachable registry: printed, nothing written
        exit_on_rejection(gates, e)
    if out.get("key"):
        entry = (gates.load_ledger(paths).get("gates") or {}).get(out["key"])
        sys.stdout.write(
            json.dumps({"status": "waiting", "blocked_by_gate": out["key"], "needs_input": [out["needs"]]}) + "\n"
        )
        print(
            f"Waiting: {out['key']} {_why(entry)}; ask it, record the answer, then run this again. Nothing was "
            "written.",
            file=sys.stderr,
        )
        sys.exit(10)
    return ledger


def reopen_if_complete(run_dir: str, run_id: str | None, *, step: str) -> None:
    """A what-if on a delivered review: a new revision (`running`, `revision` + 1, deliverables cleared) before
    any gate is checked, so a question the what-if owes is asked, never refused as a finished run's."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger
    try:
        if gates.reopen_for_recompose(paths, step):
            revision = (sys.modules["_run_status"].load_status(paths) or {}).get("revision")
            print(f"note: the delivered review is reopened as revision {revision} for this what-if", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        exit_on_rejection(gates, e)


def answers(ledger: Any) -> dict[str, dict[str, Any]]:
    """Each gate key's state and current record (read only)."""
    if ledger is None:
        return {}
    gates, paths = ledger
    out: dict[str, dict[str, Any]] = {}
    for key, entry in (gates.load_ledger(paths).get("gates") or {}).items():
        if isinstance(entry, dict):
            out[key] = {"state": entry.get("state"), **(entry.get("current") or {})}
    return out


def mismatch(message: str) -> NoReturn:
    sys.stdout.write(json.dumps({"status": "rejected", "code": "GATE_RECORD_MISMATCH", "message": message}) + "\n")
    print(f"Error: {message}; nothing was written", file=sys.stderr)
    sys.exit(1)


def what_if_or_mismatch(run_dir: str, run_id: str | None, key: str, message: str, *, reason: str, by: str) -> NoReturn:
    """A request that asks for something `key`'s recorded answer rules out. On a reopened revision (a what-if on
    a delivered review) the answer is superseded and the question asked again (exit 10). On the first revision
    it is a mismatch (exit 1): the request is fixed, never the record."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is not None:
        gates, paths = ledger
        try:
            reopened = gates.supersede_for_what_if(paths, key, by, reason)
        except Exception as e:  # noqa: BLE001
            exit_on_rejection(gates, e)
        if reopened:
            require_or_exit(run_dir, run_id, [key], by=by)
    mismatch(message)


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
    sys.exit(10)


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


def write_json(path: str, doc: Any) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
