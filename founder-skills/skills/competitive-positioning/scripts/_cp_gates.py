"""competitive-positioning's gate checks, shared by its producers, its prompt generator, compose and the closer.

Every function here acts only when the run dir carries this run's `handoff/<RUN_ID>/run_ref.json`
(`_run_ref.has_ledger`); with none it returns at once and loads nothing, so a run without a ledger behaves
exactly as before. The shared modules are loaded by path through `_run_ref`, never imported. Skill scripts
cannot import across skills, so the parts that are market-sizing's too (`require_or_exit`,
`refuse_without_run_id`, `refuse_open_gates`, `coaching_pending`) are copies of `_ms_gates.py`'s, held to them
by a test.

A delivered analysis is composed again in two places the skill documents (the delivery check's fix, and a
coordinate the founder disputes): compose then starts a new revision (`reopen_if_complete`) instead of
refusing. Only the first writes of a whole new analysis (the product profile, the competitor draft) refuse a
finished run.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

GATE1 = "cp_gate1_landscape"
BASIS_GATE = "cp_scoring_basis"
AVAILABILITY_GATE = "cp_product_availability"
PRODUCT_GATES = (
    "cp_product_profile.product",
    "cp_product_profile.customers",
    "cp_product_profile.differentiation",
    AVAILABILITY_GATE,
)
# Step 4's questions, after Gate 1 and before the set is final.
STEP4_GATES = ("cp_research_additions", "cp_research_pick", "cp_merge_pick")
# What the scoring prompts rest on.
SCORING_GATES = (GATE1, *STEP4_GATES, "cp_gate2_axes", BASIS_GATE)
# Everything compose requires. Never `cp_upload_path` or a merger pair: their owed rule is the model's, so a
# `require` would open them on every run; an open one is caught by `refuse_open_gates` instead.
ALL_KEYS = (*PRODUCT_GATES, *SCORING_GATES, "cp_gate3_position")
# Questions a printed prompt waits for while they are open.
OPEN_FOLLOW_UPS = ("cp_consolidation_merge",)
# The artifacts this run's id is read from, as compose and the pages read it.
REQUIRED_ARTIFACTS = (
    "landscape.json",
    "positioning.json",
    "moat_scores.json",
    "positioning_scores.json",
    "checklist.json",
)
# The first writes of a whole new analysis: refused on a delivered run.
FIRST_WRITES = ("product_profile.json", "landscape_draft.json")
DEFAULT_BASIS = "shipped"

FINISHED_MESSAGE = (
    "this analysis was delivered and an answer it rests on has changed since; new materials or a changed "
    "competitor set start a new analysis (run Step 0 again)"
)


def run_id_of(run_dir: str) -> str | None:
    """This run's id, from the required artifacts as compose and the pages read it (the id most of them carry)."""
    import _cp_redteam_copy

    loaded: dict[str, Any] = {}
    for name in REQUIRED_ARTIFACTS:
        try:
            with open(os.path.join(run_dir, name), encoding="utf-8") as f:
                loaded[name] = json.load(f)
        except (OSError, ValueError):
            loaded[name] = None
    rid = _cp_redteam_copy.primary_run_id_in(run_dir, loaded, REQUIRED_ARTIFACTS)
    return rid if isinstance(rid, str) and rid else None


def open_ledger_or_exit(run_dir: str, run_id: str | None) -> Any:
    """(the shared `_gates`, the run's paths), or None with no ledger. A ref whose ledger cannot be reached
    exits 2 here, before anything is written."""
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


def require_or_exit(
    run_dir: str, run_id: str | None, keys: list[str], *, open_follow_ups: tuple[str, ...] = (), by: str
) -> None:
    """Exit 10 (stdout JSON naming the gate, with `needs_input`; nothing written) when one of `keys` has no
    terminal record for this run, its record no longer matches what it confirmed, or a gate in
    `open_follow_ups` is still open; exit 1 on a finished run whose confirmed input changed. Returns with
    nothing to do when the run has no ledger, or the gates do not apply to its mode."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        for key in keys:
            if gates.require_terminal(ctx, led, key, by=by) == "waiting":
                return {"key": key, "exit": gates.waiting_exit(ctx, led, key)}
        for key, entry in sorted((led.get("gates") or {}).items()):
            if isinstance(entry, dict) and entry.get("state") == "open" and entry.get("gate") in open_follow_ups:
                return {"key": key, "exit": gates.waiting_exit(ctx, led, key)}
        return {}

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001 -- RUN_FINISHED, unreachable registry: printed, nothing written
        exit_on_rejection(gates, e)
    if out.get("key"):
        entry = (gates.load_ledger(paths).get("gates") or {}).get(out["key"])
        gates.print_waiting_and_exit(
            out["exit"],
            f"Waiting: {out['key']} {_why(entry)}; ask it, record the answer, then run this again. Nothing was "
            "written.",
        )


def refuse_without_run_id(output: str | None, run_id: str | None) -> None:
    """A call into a run dir that carries any run's ref must name its run: exit 1 `RUN_ID_REQUIRED`."""
    if output is None or run_id:
        return
    run_dir = os.path.dirname(os.path.abspath(output))
    if glob.glob(os.path.join(glob.escape(run_dir), "handoff", "*", _run_ref.RUN_REF_NAME)):
        message = "this analysis dir belongs to a run; pass its --run-id so the run's checks apply"
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_REQUIRED", "message": message}) + "\n")
        print(f"Error: {message}; nothing was written", file=sys.stderr)
        sys.exit(1)


def availability_mismatch(run_dir: str, run_id: str | None, profile: dict[str, Any]) -> str | None:
    """Why the profile's `product_availability` disagrees with the recorded answer, or None. An answer is the
    founder's (or the request's) word, so the profile must carry it, and `not_sure` none; a not-applicable
    record means the materials say it, and the profile's own value stands. Read only; no ledger: None."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    entry = (gates.load_ledger(paths).get("gates") or {}).get(AVAILABILITY_GATE) or {}
    current = entry.get("current") if entry.get("state") == "answered" else None
    answer = current.get("answer_id") if isinstance(current, dict) else None
    if answer is None:
        return None
    want = None if answer == "not_sure" else answer
    got = profile.get("product_availability")
    if got == want:
        return None
    return (
        f"product_availability is {got!r} but {AVAILABILITY_GATE} was answered {answer!r}; write "
        + (f"{want!r}" if want else "no product_availability")
        + " (the recorded answer stands)"
    )


def refuse_if_finished(run_dir: str, run_id: str | None) -> None:
    """The first write of a whole new analysis into a delivered run: exit 1 `RUN_FINISHED`, nothing written."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    rs = sys.modules["_run_status"]
    if (rs.load_status(ledger[1]) or {}).get("status") in rs.FINAL_STATUSES:
        _finished()


def reopen_if_complete(run_dir: str, run_id: str | None, *, step: str) -> None:
    """Compose on a delivered run: a new revision (`running`, `revision` + 1, deliverables cleared) before any
    gate is checked, so the report it writes is not listed as final, and a question the new report owes is
    asked, never refused."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger
    try:
        if gates.reopen_for_recompose(paths, step):
            revision = (sys.modules["_run_status"].load_status(paths) or {}).get("revision")
            # The coaching about the earlier map is not this revision's: SKILL.md names its fresh hand-off file by
            # this number, so a stale file can never pass the gate.
            print(f"note: the delivered analysis is composed again as revision {revision}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        exit_on_rejection(gates, e)


def recorded_basis(run_dir: str, run_id: str | None) -> str | None:
    """The scoring basis this run recorded (`cp_scoring_basis`), `shipped` when none was asked; None with no
    ledger. Read only."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    entry = (gates.load_ledger(paths).get("gates") or {}).get(BASIS_GATE) or {}
    cur = entry.get("current") or {}
    if entry.get("state") == "answered" and isinstance(cur.get("answer_id"), str):
        return str(cur["answer_id"])
    return DEFAULT_BASIS


def basis_mismatch(recorded: str, used: Any, where: str) -> NoReturn:
    message = (
        f"{where} uses the scoring basis {used!r}, but this run recorded {recorded!r}; score on the recorded basis "
        "(run the prompt generator again and dispatch what it prints)"
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


def close_upload_question(run_dir: str, run_id: str | None, reason: str) -> None:
    """The review will not run: the documents question it opened no longer applies (`not_applicable`), so the
    run is not held open asking for a path nobody will read. With no ledger, or no open question: nothing."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return
    gates, paths = ledger

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> None:
        entry = (led.get("gates") or {}).get("cp_upload_path")
        if isinstance(entry, dict) and entry.get("state") == "open":
            gates.record(
                ctx,
                led,
                "cp_upload_path",
                note=f"the outside review did not run: {reason}",
                resolution="not_applicable",
                basis="script",
                by="record_red_team_skip.py",
            )

    try:
        gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001
        exit_on_rejection(gates, e)
