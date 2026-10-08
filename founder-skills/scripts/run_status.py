#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Start, bind, finish and show a run's status file.

    start         --skill S --artifacts-root A   (host request lines on stdin)
    bind          --run-id R --artifacts-root A --run-dir D --slug G
    finish        --mode M --run-id R --artifacts-root A [--output P] [--lookup-status S]
    show          --run-id R --artifacts-root A
    deliverables  --run-id R --artifacts-root A --final
    fail          --run-id R --artifacts-root A --code C --reason TEXT

`start` takes a run id from an `FS_HOST_RUN_ID=` line or mints one, validates every `FS_HOST_` line
against the gate registry before writing anything, and creates `runs/<id>/run_status.json` and the gate
ledger beside it, or resumes a `waiting` run of the same skill. It never writes another run's status:
an id in use or finished is refused PRINT-ONLY (JSON on stdout, one stderr line, one line appended to
`runs/<id>/start_refusals.jsonl`), and a malformed id writes nothing at all.

`bind` records the run dir and slug once they exist, and writes `<run_dir>/handoff/<id>/run_ref.json`,
which is what tells the skill's own scripts that this run has a ledger.

Exit codes: 0 ok; 1 refused (JSON on stdout, a line on stderr, nothing written beyond what the refusal
says); 2 usage, IO, an unreachable registry or no status for the id (stdout carries `code`); 10 a gate
is still open (`blocked_by_gate`); 12 the same, on a request that said not to ask (FS_HOST_NO_ASK).

`fail` ends a run that stopped on a failure it cannot recover from (`refused`, with a code from a closed list);
it is named only by the rule for a request that says not to ask (FS_HOST_NO_ASK).
It is refused (`RUN_WAITING`) while a question is open: a run waiting for an answer is never ended by it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_status as rs  # noqa: E402

_gates: Any = None
_GATES_ERROR = ""
try:
    import _gates as _gates_module  # noqa: E402

    _gates = _gates_module
except Exception as _e:  # the registry fails closed: every command that needs it exits 2
    _GATES_ERROR = f"{type(_e).__name__}: {_e}"

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out(payload: dict[str, Any], pretty: bool, output: str | None = None) -> None:
    text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False) + "\n"
    if output:
        path = os.path.abspath(output)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        sys.stdout.write(json.dumps({"ok": True, "path": path, "bytes": len(text.encode("utf-8"))}) + "\n")
    else:
        sys.stdout.write(text)


def _exit(code: int, payload: dict[str, Any], line: str, pretty: bool) -> NoReturn:
    sys.stdout.write(json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False) + "\n")
    print(line, file=sys.stderr)
    sys.exit(code)


def _unreachable(code: str, message: str, pretty: bool) -> NoReturn:
    _exit(2, {"status": "error", "code": code, "message": message}, f"Error: {message}", pretty)


def _require_gates(pretty: bool) -> Any:
    if _gates is None:
        _unreachable("REGISTRY_UNREACHABLE", f"the plugin's gate registry is not reachable: {_GATES_ERROR}", pretty)
    return _gates


def _paths(artifacts_root: str, run_id: str, pretty: bool) -> rs.RunPaths:
    if not rs.valid_run_id(run_id):
        _exit(
            1,
            {"status": "refused", "code": "RUN_ID_MALFORMED", "run_id": run_id, "message": "the run id is malformed"},
            f"Refused: run id {run_id!r} does not match {rs.RUN_ID_RE.pattern}; nothing was written",
            pretty,
        )
    return rs.run_paths(artifacts_root, run_id)


def _print_only(paths: rs.RunPaths, code: str, message: str, pretty: bool, **extra: Any) -> NoReturn:
    """Refuse without touching run_status.json: one line in start_refusals.jsonl, JSON out, exit 1."""
    record = {"at": rs.now_iso(), "code": code, "message": message, **extra}
    try:
        rs.append_jsonl(paths.refusals, record)
    except OSError as e:
        print(f"warning: could not append to {paths.refusals}: {e}", file=sys.stderr)
    _exit(
        1,
        {"status": "refused", "code": code, "run_id": paths.run_id, "message": message, **extra},
        f"Refused ({code}): {message}",
        pretty,
    )


def _host_status_path(paths: rs.RunPaths) -> str | None:
    try:
        import resolve_artifacts_root as rar
    except ImportError:
        return None
    host = rar.read_persisted(paths.artifacts_root)
    if not host:
        return None
    rel = os.path.relpath(paths.status, paths.artifacts_root)
    return f"{host}/artifacts/{rel}"


def _host_run_id(text: str) -> str | None:
    lines = _gates.request_lines(text) if _gates is not None else [raw.strip() for raw in text.splitlines()]
    for line in lines:
        if line.startswith("FS_HOST_RUN_ID="):
            return line[len("FS_HOST_RUN_ID=") :]
    return None


def cmd_start(args: argparse.Namespace) -> int:
    gates = _require_gates(args.pretty)
    if args.skill not in gates.SKILLS:
        _unreachable("SKILL_UNKNOWN", f"--skill must be one of {', '.join(gates.SKILLS)}", args.pretty)
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    host_id = _host_run_id(text)
    run_id = host_id if host_id is not None else rs.mint_run_id()
    paths = _paths(args.artifacts_root, run_id, args.pretty)
    _rid, pre, bad, flags = gates.parse_request(text, args.skill)
    surface = rs.surface(os.getcwd(), dict(os.environ))

    with rs.run_lock(paths, create=True):
        rs.pause_for_tests()
        status = rs.load_status(paths)
        if status is not None and status.get("status") == "refused" and status.get("code") == "PRE_ANSWER_INVALID":
            n = 1
            while os.path.exists(f"{paths.status}.replaced-{n}"):
                n += 1
            os.replace(paths.status, f"{paths.status}.replaced-{n}")
            status = None
        if status is None:
            return _start_fresh(gates, args, paths, pre, bad, surface, flags)
        state, skill = status.get("status"), status.get("skill")
        if state == "waiting" and skill == args.skill:
            return _resume(gates, args, paths, status, pre, bad, flags)
        if state in rs.FINAL_STATUSES:
            _print_only(paths, "RUN_ID_FINISHED", f"run {run_id} is already {state}; start a new run", args.pretty)
        _print_only(
            paths,
            "RUN_ID_IN_USE",
            f"run {run_id} is {state} for {skill}; only a waiting run of the same skill can be resumed",
            args.pretty,
        )


def _start_fresh(
    gates: Any,
    args: argparse.Namespace,
    paths: rs.RunPaths,
    pre: dict[str, Any],
    bad: list[dict[str, str]],
    surface: str,
    flags: dict[str, Any],
) -> int:
    status = rs.blank_status(args.skill, paths)
    status["artifacts_root_shell"] = paths.artifacts_root
    status["run_status_path_host"] = _host_status_path(paths)
    if bad:
        rs.set_state(status, "refused", "PRE_ANSWER_INVALID")
        status["notices"] = [{"code": "PRE_ANSWER_INVALID", **b} for b in bad]
        if not rs.create_status_exclusive(paths, status):
            _print_only(paths, "RUN_ID_IN_USE", f"run {paths.run_id} was created concurrently", args.pretty)
        _exit(
            1,
            {"status": "refused", "code": "PRE_ANSWER_INVALID", "run_id": paths.run_id, "invalid": bad},
            f"Refused (PRE_ANSWER_INVALID): {bad[0]['line']!r}: {bad[0]['reason']}",
            args.pretty,
        )
    ledger = gates.new_ledger(paths.run_id, args.skill, surface)
    gates.store_request_flags(ledger, flags, "run_status.py")
    gates.store_pre_answers(ledger, pre, "run_status.py")
    gates.derive_status(gates.Ctx(paths, status, args.skill), ledger, status)
    if not rs.create_status_exclusive(paths, status):
        _print_only(paths, "RUN_ID_IN_USE", f"run {paths.run_id} was created concurrently", args.pretty)
    rs.atomic_write_json(paths.ledger, ledger)
    _out(
        _start_payload(paths, status, resume=False, resume_step=None, reuse=[], ledger=ledger), args.pretty, args.output
    )
    return 0


def _resume(
    gates: Any,
    args: argparse.Namespace,
    paths: rs.RunPaths,
    status: dict[str, Any],
    pre: dict[str, Any],
    bad: list[dict[str, str]],
    flags: dict[str, Any],
) -> int:
    if bad:
        _print_only(
            paths,
            "PRE_ANSWER_INVALID",
            f"{bad[0]['line']!r}: {bad[0]['reason']}; the waiting run is unchanged",
            args.pretty,
            invalid=bad,
        )
    ledger = gates.load_ledger(paths)
    waiting_on = status.get("waiting_on")
    resume_step = None
    if isinstance(waiting_on, str):
        try:
            resume_step = gates.GATES[gates.parse_key(waiting_on)[0]]["step"]
        except (KeyError, gates.GateRejection):
            resume_step = None
    gates.store_request_flags(ledger, flags, "run_status.py")
    gates.store_pre_answers(ledger, pre, "run_status.py")
    rs.atomic_write_json(paths.ledger, ledger)
    resumed_from = {
        "gate": waiting_on if isinstance(waiting_on, str) else None,
        "step": resume_step,
        "reason": "resume",
    }
    entry = rs.open_invocation(status, "resume", resumed_from)
    ctx = gates.Ctx(paths, status, args.skill)
    gates.derive_status(ctx, ledger, status)
    # The run is `running` again only when this request carried something the open question can take: an answer
    # line for it, or (under FS_HOST_NO_ASK) a derive line. Otherwise it stays `waiting`, so a resume that brought
    # nothing new (a retried prompt, a line for another question, a crash after this call) can be sent again.
    if _resume_can_progress(gates, ledger):
        rs.set_state(status, "running", "RUNNING")
    rs.write_status(paths, status)
    payload = _start_payload(paths, status, resume=True, resume_step=resume_step, reuse=entry["reuse"], ledger=ledger)
    _out(payload, args.pretty, args.output)
    return 0


def _resume_can_progress(gates: Any, ledger: dict[str, Any]) -> bool:
    open_keys = [k for k, e in (ledger.get("gates") or {}).items() if isinstance(e, dict) and e.get("state") == "open"]
    if not open_keys:
        return True
    for key in open_keys:
        if gates.pending_pre_answer(ledger, key) is not None or gates.derive_authorized(ledger, key):
            return True
    return False


def _start_payload(
    paths: rs.RunPaths,
    status: dict[str, Any],
    *,
    resume: bool,
    resume_step: str | None,
    reuse: list[str],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    quiet = _gates is not None and _gates.no_ask(ledger)
    extra: dict[str, Any] = {"no_ask": 1, "rule": _gates.NO_ASK_RULE} if quiet else {"no_ask": 0}
    return {
        **extra,
        "run_id": paths.run_id,
        "resume": 1 if resume else 0,
        "resume_step": resume_step,
        "reuse": reuse,
        "invocation": status.get("invocation"),
        "ledger_path_shell": paths.ledger,
        "status": status.get("status"),
        "status_path": paths.status,
    }


def _load_or_unreachable(paths: rs.RunPaths, pretty: bool) -> dict[str, Any]:
    try:
        status = rs.load_status(paths)
    except ValueError as e:
        _unreachable("RUN_NOT_FOUND", f"the run status is unreadable: {e}", pretty)
    if status is None:
        _unreachable("RUN_NOT_FOUND", f"no run status for {paths.run_id} at {paths.status}", pretty)
    return status


def cmd_bind(args: argparse.Namespace) -> int:
    _require_gates(args.pretty)
    paths = _paths(args.artifacts_root, args.run_id, args.pretty)
    run_dir = os.path.abspath(args.run_dir)
    root = paths.artifacts_root
    if os.path.commonpath([run_dir, root]) != root or run_dir == root:
        _unreachable(
            "RUN_DIR_OUTSIDE_ROOT", f"--run-dir {run_dir} is not inside the artifacts root {root}", args.pretty
        )
    with rs.run_lock(paths):
        status = _load_or_unreachable(paths, args.pretty)
        if (
            status.get("status") == "refused"
            and status.get("run_dir_shell") == run_dir
            and status.get("slug") == args.slug
        ):
            # A run the founder declined, re-bound by the skill's own slug block on its way to the stop: nothing
            # to do and nothing failed, so it is not an exit that reads as "the run could not start".
            _out(
                {
                    "ok": True,
                    "run_id": paths.run_id,
                    "status": "refused",
                    "code": "RUN_REFUSED",
                    "message": "the run was declined; it stays bound and nothing was written",
                },
                args.pretty,
            )
            return 0
        if status.get("status") in rs.FINAL_STATUSES:
            _print_only(paths, "RUN_ID_FINISHED", f"run {paths.run_id} is already {status.get('status')}", args.pretty)
        bound = status.get("slug")
        bound_dir = status.get("run_dir_shell")
        if bound_dir is not None and bound_dir != run_dir and (bound is None or bound == args.slug):
            _print_only(
                paths,
                "RUN_ALREADY_BOUND",
                f"run {paths.run_id} is already bound to {bound_dir}; a run has one run dir",
                args.pretty,
            )
        if bound is not None and bound != args.slug:
            _print_only(
                paths,
                "RUN_ID_IN_USE",
                f"run {paths.run_id} is bound to {bound!r}, not {args.slug!r}; start a new run for another company",
                args.pretty,
            )
        os.makedirs(run_dir, exist_ok=True)
        ref = rs.write_run_ref(run_dir, paths, str(status.get("skill")))
        status["slug"] = args.slug
        status["mode"] = rs.mode_for_run_dir(run_dir)
        status["run_dir_shell"] = run_dir
        status["scripts_dir_shell"] = os.path.join(_PLUGIN_ROOT, "skills", str(status.get("skill")), "scripts")
        status["run_status_path_host"] = _host_status_path(paths)
        try:
            ledger = _require_gates(args.pretty).load_ledger(paths)
        except rs.RunStatusError as e:
            _unreachable(e.code, str(e), args.pretty)
        # A gate opened before the mode was known that this mode does not owe could never be answered (it
        # is refused as not owed) and would hold the run open: it is closed as not applicable, by script.
        if _gates.close_unowed_for_mode(ledger, status["mode"], "run_status.py"):
            rs.atomic_write_json(paths.ledger, ledger)
        # The mode decides which gates the run lists, so the list is re-derived with it.
        _gates.derive_status(_gates.Ctx(paths, status, str(status.get("skill"))), ledger, status)
        rs.write_status(paths, status)
    _out({"ok": True, "run_id": paths.run_id, "slug": args.slug, "mode": status["mode"], "run_ref": ref}, args.pretty)
    return 0


def _output_run_id(path: str) -> str | None:
    try:
        data = rs.read_json(path)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("metadata")
    rid = meta.get("run_id") if isinstance(meta, dict) else None
    rid = rid if rid is not None else data.get("run_id")
    return rid if isinstance(rid, str) else None


def cmd_finish(args: argparse.Namespace) -> int:
    gates = _require_gates(args.pretty)
    paths = _paths(args.artifacts_root, args.run_id, args.pretty)

    def refuse(message: str, **extra: Any) -> NoReturn:
        _exit(
            1,
            {"status": "rejected", "code": "FINISH_REFUSED", "message": message, **extra},
            f"Refused: {message}",
            args.pretty,
        )

    if args.mode == "rule_lookup":
        if args.output:
            refuse("--mode rule_lookup takes no --output: the lookup writes no artifact")
        if args.lookup_status is None:
            refuse("--mode rule_lookup needs --lookup-status")
    else:
        if args.lookup_status is not None:
            refuse("--lookup-status applies only to --mode rule_lookup")
        if not args.output:
            refuse(f"--mode {args.mode} needs --output, the JSON artifact this run wrote")
        if not os.path.isfile(args.output):
            refuse(f"--output {args.output} does not exist")
        if _output_run_id(args.output) != paths.run_id:
            refuse(f"--output {args.output} does not carry run id {paths.run_id}")

    with rs.run_lock(paths):
        status = _load_or_unreachable(paths, args.pretty)
        if status.get("status") in rs.FINAL_STATUSES:
            refuse(f"run {paths.run_id} is already {status.get('status')}")
        if args.mode == "rule_lookup" and status.get("skill") != "cap-table":
            _exit(
                1,
                {"status": "rejected", "code": "MODE_NOT_OFFERED", "message": "only cap-table has a rule lookup"},
                f"Refused: {status.get('skill')} has no rule-lookup mode; nothing was written",
                args.pretty,
            )
        # The mode is the run dir's, set at bind; finish never changes it. A rule lookup writes no run dir,
        # so it is the one mode that finishes an unbound run.
        bound_mode = status.get("mode")
        unbound_ok = bound_mode is None and args.mode == "rule_lookup"
        # cap-table's no-cap-base fork: a full run whose founder chose instrument terms only finishes as an
        # extraction-only run (its report is written beside the run dir, in the `-extraction` sibling).
        if args.mode == "extraction_only" and bound_mode == "full":
            fork = (gates.load_ledger(paths).get("gates") or {}).get("ct_no_cap_base_fork") or {}
            unbound_ok = (
                fork.get("state") == "answered" and (fork.get("current") or {}).get("answer_id") == "terms_only"
            )
        if bound_mode != args.mode and not unbound_ok:
            _exit(
                1,
                {"status": "rejected", "code": "MODE_MISMATCH", "mode": bound_mode, "message": "not this run's mode"},
                f"Refused: run {paths.run_id} is a {bound_mode} run, not {args.mode}; nothing was written",
                args.pretty,
            )
        try:
            ledger = gates.load_ledger(paths)
        except rs.RunStatusError as e:
            _unreachable(e.code, str(e), args.pretty)
        if unbound_ok:
            status["mode"] = args.mode
            # Questions opened before the mode was known that this mode does not ask (Step 1's on a lookup; the
            # full review's on a terms-only fork) are closed, so they cannot hold the run open.
            if gates.close_unowed_for_mode(ledger, args.mode, "run_status.py"):
                rs.atomic_write_json(paths.ledger, ledger)
                gates.derive_status(gates.Ctx(paths, status, str(status.get("skill"))), ledger, status)
                rs.write_status(paths, status)
        ctx = gates.Ctx(paths, status, str(status.get("skill")))
        if args.mode == "rule_lookup" and args.lookup_status == "escalate":
            before = json.dumps(ledger, sort_keys=True)
            try:
                got = gates.require_terminal(ctx, ledger, "ct_rule_lookup_fact", by="run_status.py")
            except gates.Unimplemented as e:
                _unreachable("REGISTRY_UNREACHABLE", str(e), args.pretty)
            if got == "waiting":
                return _blocked(gates, ctx, ledger, status, paths, "ct_rule_lookup_fact", before, args.pretty)
        open_now = rs.open_gate_ids(paths)
        if open_now:
            before = json.dumps(ledger, sort_keys=True)
            return _blocked(gates, ctx, ledger, status, paths, open_now[0], before, args.pretty)
        rs.mark_complete(status)
        rs.write_status(paths, status)
    _out({"ok": True, "run_id": paths.run_id, "status": "complete", "deliverables_status": "final"}, args.pretty)
    return 0


def _blocked(
    gates: Any,
    ctx: Any,
    ledger: dict[str, Any],
    status: dict[str, Any],
    paths: rs.RunPaths,
    key: str,
    before: str,
    pretty: bool,
) -> int:
    if json.dumps(ledger, sort_keys=True) != before:
        rs.atomic_write_json(paths.ledger, ledger)
        gates.derive_status(ctx, ledger, status)
        rs.write_status(paths, status)
    try:
        code, payload, line = gates.waiting_exit(ctx, ledger, key)
    except gates.Unimplemented:
        code, payload, line = (
            gates.EXIT_CODES["waiting"],
            {"status": "waiting", "blocked_by_gate": key, "needs_input": [{"gate": key}]},
            f"Waiting: {key} has no answer yet; ask it, record the answer, then run this again",
        )
    _exit(code, payload, line, pretty)


def cmd_show(args: argparse.Namespace) -> int:
    _require_gates(args.pretty)
    paths = _paths(args.artifacts_root, args.run_id, args.pretty)
    status = _load_or_unreachable(paths, args.pretty)
    # The hook's record may have a line newer than the last status write: folded for printing only.
    rs.fold_asked_evidence(status)
    _out(status, args.pretty, args.output)
    return 0


def cmd_deliverables(args: argparse.Namespace) -> int:
    _require_gates(args.pretty)
    paths = _paths(args.artifacts_root, args.run_id, args.pretty)
    with rs.run_lock(paths):
        status = _load_or_unreachable(paths, args.pretty)
        if status.get("status") != "complete":
            _exit(
                1,
                {"status": "rejected", "code": "RUN_NOT_COMPLETE", "message": "only a complete run's pages are final"},
                f"Refused: run {paths.run_id} is {status.get('status')}, not complete; nothing was written",
                args.pretty,
            )
        if status.get("deliverables_status") != "final":
            status["deliverables_status"] = "final"
            rs.write_status(paths, status)
    _out({"ok": True, "run_id": paths.run_id, "deliverables_status": "final"}, args.pretty)
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    gates = _require_gates(args.pretty)
    paths = _paths(args.artifacts_root, args.run_id, args.pretty)
    if args.code not in rs.FAIL_CODES:
        _unreachable("USAGE", f"--code must be one of {', '.join(rs.FAIL_CODES)}", args.pretty)
    with rs.run_lock(paths):
        status = _load_or_unreachable(paths, args.pretty)
        if status.get("status") in rs.FINAL_STATUSES:
            _print_only(paths, "RUN_ID_FINISHED", f"run {paths.run_id} is already {status.get('status')}", args.pretty)
        try:
            ledger = gates.load_ledger(paths)
        except rs.RunStatusError as e:
            _unreachable(e.code, str(e), args.pretty)
        open_now = [
            k for k, e in (ledger.get("gates") or {}).items() if isinstance(e, dict) and e.get("state") == "open"
        ]
        if open_now:
            _exit(
                1,
                {
                    "status": "rejected",
                    "code": "RUN_WAITING",
                    "waiting_on": open_now[0],
                    "message": "the run is waiting for an answer, not stopped by a failure",
                },
                f"Refused (RUN_WAITING): {open_now[0]} is open; the run waits for an answer. Nothing was written",
                args.pretty,
            )
        rs.set_state(status, "refused", args.code)
        status["last_error_code"] = None
        status["failure"] = {"code": args.code, "reason": args.reason[:2000], "at": rs.now_iso()}
        rs.write_status(paths, status)
    _out({"ok": True, "run_id": paths.run_id, "status": "refused", "code": args.code}, args.pretty)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="A run's status file: start, bind, finish, show, deliverables, fail")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser, *, run_id: bool = True) -> None:
        if run_id:
            sp.add_argument("--run-id", required=True)
        sp.add_argument("--artifacts-root", required=True)
        sp.add_argument("--pretty", action="store_true")
        sp.add_argument("-o", "--output-file", dest="output", default=None, help="write the JSON here")

    sp = sub.add_parser("start", help="create or resume a run; FS_HOST_ lines on stdin")
    sp.add_argument("--skill", required=True)
    common(sp, run_id=False)
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("bind", help="record the run dir and slug; writes run_ref.json")
    common(sp)
    sp.add_argument("--run-dir", required=True)
    sp.add_argument("--slug", required=True)
    sp.set_defaults(func=cmd_bind)

    sp = sub.add_parser("finish", help="complete a run whose mode has no coaching")
    sp.add_argument(
        "--mode", required=True, choices=("quick_check", "fast_assess", "concise", "rule_lookup", "extraction_only")
    )
    sp.add_argument("--run-id", required=True)
    sp.add_argument("--artifacts-root", required=True)
    sp.add_argument("--output", default=None, help="the JSON artifact this run wrote")
    sp.add_argument("--lookup-status", choices=("answered", "escalate", "not_found"), default=None)
    sp.add_argument("--pretty", action="store_true")
    sp.set_defaults(func=cmd_finish)

    sp = sub.add_parser("show", help="print the run status")
    common(sp)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("deliverables", help="close a complete run's page list")
    common(sp)
    sp.add_argument("--final", action="store_true", required=True)
    sp.set_defaults(func=cmd_deliverables)

    sp = sub.add_parser("fail", help="end a run that stopped on a failure it cannot recover from")
    common(sp)
    sp.add_argument("--code", required=True)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_fail)

    args = p.parse_args()
    pretty = getattr(args, "pretty", False)
    try:
        return int(args.func(args))
    except rs.RunStatusError as e:
        _unreachable(e.code, str(e), pretty)
    except Exception as e:
        if _gates is not None and isinstance(e, _gates.Declined):
            _exit(1, e.payload(), f"Refused ({e.code}): {e}; stop here and produce nothing", pretty)
        if _gates is not None and isinstance(e, _gates.GateRejection):
            _exit(1, e.payload(), f"Rejected ({e.code}): {e}; nothing was written", pretty)
        if _gates is not None and isinstance(e, _gates.Unimplemented):
            if getattr(e, "code", None) == "GATE_UNDECIDABLE":
                _unreachable("GATE_UNDECIDABLE", f"{e}; nothing was written", pretty)
            _unreachable("GATE_NOT_WIRED", f"{e}; this gate's skill does not record it yet", pretty)
        raise


if __name__ == "__main__":
    sys.exit(main())
