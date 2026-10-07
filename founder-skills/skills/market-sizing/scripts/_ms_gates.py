"""market-sizing's gate checks, shared by its prompt generator, its producers, compose and the closer.

Every function here acts only when the run dir carries this run's `handoff/<RUN_ID>/run_ref.json`
(`_run_ref.has_ledger`); with none it returns at once and loads nothing, so a run without a ledger behaves
exactly as before. The shared modules are loaded by path through `_run_ref`, never imported. Skill scripts
cannot import across skills, so the parts that are financial-model-review's too (`refuse_without_run_id`,
the finished-run refusal) are copies of `_fmr_gates.py`'s, held to them by a test.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

METHODOLOGY_GATE = "ms_methodology"
TWO_FIGURES_GATE = "ms_two_figures"
REVISION_GATE = "ms_revision"
PCT_SCALE_GATE = "ms_pct_scale"
PERIOD_GATE = "ms_input_period"
# Questions the sizing rests on: while one is open, the sizing prompts are not printed.
SIZING_FOLLOW_UPS = ("ms_methodology_change", "ms_correct_data", "ms_fx_rate", TWO_FIGURES_GATE)

# A changed answer after the analysis was delivered: the enforcer will not re-open a finished run's answer.
FINISHED_MESSAGE = (
    "this analysis is complete and an answer it rests on has changed since; a changed approach or figure starts "
    "a new analysis (run Step 0 again)"
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


def two_figure_keys(run_dir: str) -> list[str]:
    """`ms_two_figures.<input>` for each input the founder's materials state more than one figure for."""
    try:
        with open(os.path.join(run_dir, "inputs.json"), encoding="utf-8") as f:
            inputs = json.load(f)
    except (OSError, ValueError):
        return []
    alts = inputs.get("founder_stated_alternatives") if isinstance(inputs, dict) else None
    if not isinstance(alts, dict):
        return []
    return [f"{TWO_FIGURES_GATE}.{k}" for k in sorted(alts) if isinstance(alts[k], list) and alts[k]]


def pct_scale_keys(run_dir: str) -> list[str]:
    """`ms_pct_scale.<input>` for each input the sizing flagged as a share that may be a percent. The flag is
    raised only on the numeric path: a figure recorded by reference carries its unit."""
    try:
        with open(os.path.join(run_dir, "sizing.json"), encoding="utf-8") as f:
            sizing = json.load(f)
    except (OSError, ValueError):
        return []
    warnings = ((sizing.get("validation") or {}).get("warnings") if isinstance(sizing, dict) else None) or []
    fields = {
        w["field"]
        for w in warnings
        if isinstance(w, dict) and w.get("code") == "IMPLAUSIBLE_PCT_SCALE" and isinstance(w.get("field"), str)
    }
    return [f"{PCT_SCALE_GATE}.{f}" for f in sorted(fields)]


def exit_on_rejection(gates: Any, e: Exception) -> NoReturn:
    """A refused gate write: RUN_FINISHED as a plain refusal (exit 1), anything else as the shared failure."""
    if isinstance(e, gates.GateRejection) and e.code == "RUN_FINISHED":
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_FINISHED", "message": FINISHED_MESSAGE}) + "\n")
        print(f"Error: {FINISHED_MESSAGE}; nothing was written", file=sys.stderr)
        sys.exit(1)
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
                return {"key": key, "needs": gates.needs_input(ctx, led, key)}
        for key, entry in sorted((led.get("gates") or {}).items()):
            if isinstance(entry, dict) and entry.get("state") == "open" and entry.get("gate") in open_follow_ups:
                return {"key": key, "needs": gates.needs_input(ctx, led, key)}
        return {}

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001 -- RUN_FINISHED, unreachable registry: printed, nothing written
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


def period_question(run_dir: str, run_id: str | None, params: list[str]) -> None:
    """market_sizing.py could not tell a founder's figure's period. Unanswered: the question is opened and
    the run waits (exit 10). Answered: the answer was recorded but never written where the sizing reads it,
    so asking again would loop; exit 1 naming the field to write. With no ledger: returns."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None or not params:
        return
    gates, paths = ledger
    keys = [f"{PERIOD_GATE}.{p}" for p in params]
    led = gates.load_ledger(paths)
    for key, param in zip(keys, params, strict=True):
        entry = (led.get("gates") or {}).get(key) or {}
        cur = entry.get("current") or {}
        if entry.get("state") == "answered" and cur.get("answer_id"):
            period = str(cur["answer_id"]).removeprefix("per_")
            message = (
                f"the founder answered that their {param} is per {period}; write "
                f'founder_stated_inputs_period.{param} = "{period}" into inputs.json and run this again'
            )
            sys.stdout.write(
                json.dumps({"status": "rejected", "code": "PERIOD_NOT_WRITTEN", "message": message}) + "\n"
            )
            print(f"Error: {message}; nothing was written", file=sys.stderr)
            sys.exit(1)

    def fn(ctx: Any, led_: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        opened: dict[str, Any] = gates.open_gates(ctx, led_, keys, by="market_sizing.py")
        return opened

    try:
        out = gates.transact(paths, fn)
    except Exception as e:  # noqa: BLE001
        exit_on_rejection(gates, e)
    sys.stdout.write(
        json.dumps({"status": "waiting", "blocked_by_gate": keys[0], "needs_input": out.get("needs_input") or []})
        + "\n"
    )
    print(
        f"Waiting: the period of the founder's {', '.join(params)} is not known; ask it, record the answer, write it "
        "into inputs.json (founder_stated_inputs_period), then run this again. Nothing was written.",
        file=sys.stderr,
    )
    sys.exit(10)


def revision_owed(run_dir: str, run_id: str | None, unoffered: list[str]) -> None:
    """Compose: the review raised a high challenge naming `unoffered` parameters and no answer to Step 6d's
    question covers them (`_revision_answer.recorded`, the rule compose uses without a ledger). With a ledger
    that is a question, not a disclosure: exit 10 naming it, nothing written. An answer recorded for fewer
    parameters than the review now names is superseded, so the founder's new answer can be recorded."""
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None or not unoffered:
        return
    gates, paths = ledger
    entry = (gates.load_ledger(paths).get("gates") or {}).get(REVISION_GATE) or {}
    try:
        if entry.get("state") == "answered":
            gates.supersede_from_writer(paths, REVISION_GATE, "record_revision_answer.py", "review_names_more")
        else:
            gates.open_from_writer(paths, [REVISION_GATE], "record_revision_answer.py")
    except Exception as e:  # noqa: BLE001
        exit_on_rejection(gates, e)
    message = (
        "the outside review raised a high-severity challenge and the founder's answer to Step 6d's question "
        "(deliver, or revise once) is not recorded for it; ask it and record it with record_revision_answer.py, "
        "then compose again"
    )
    sys.stdout.write(
        json.dumps({"status": "waiting", "code": "GATE_WAITING", "blocked_by_gate": REVISION_GATE, "message": message})
        + "\n"
    )
    print(f"Waiting: {message}. Nothing was written.", file=sys.stderr)
    sys.exit(10)


def answers_view(run_dir: str) -> dict[str, Any] | None:
    """What the run's ledger holds for the report's "Your Answers" lines, by gate key: `{answer_id,
    resolution, default_reason, by_request, form_label}`; None with no ledger. Read only."""
    run_id = run_id_of(run_dir)
    ledger = open_ledger_or_exit(run_dir, run_id)
    if ledger is None:
        return None
    gates, paths = ledger
    led = gates.load_ledger(paths)
    out: dict[str, Any] = {}
    for key, entry in (led.get("gates") or {}).items():
        if not isinstance(entry, dict) or entry.get("state") != "answered":
            continue
        cur = entry.get("current") or {}
        g = gates.GATES.get(entry.get("gate"))
        if g is None or g["skill"] != "market-sizing":
            continue
        out[key] = {
            "answer_id": cur.get("answer_id"),
            "resolution": cur.get("resolution"),
            "default_reason": cur.get("default_reason"),
            "by_request": gates.answered_by_request(led, key),
            "form_label": gates.form_label_for(g, entry.get("instance")),
        }
    return out


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
