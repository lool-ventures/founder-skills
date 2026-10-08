#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record the answer to a registered gate, in the run's gate ledger.

    open            --run-id R (--run-dir D | --artifacts-root A) --gate G[.I] [--gate ...]
    answer          --run-id R (--run-dir D | --artifacts-root A)
                    --gate G[.I] (--answer-id X | --answer "LABEL") [--value V] [--note N] [--after-hold]
                    [--gate ...]                                   (one segment per gate)
    answer          --run-id R (--run-dir D | --artifacts-root A) --form-reply   (reply on stdin)
    default         --run-id R (...) --gate G[.I] --reason REASON [--answer-id X] [--value V] [--note N]
    not-applicable  --run-id R (...) --gate G[.I] [--gate ...] --reason TEXT   (all or none)
    require         --run-id R (...) --gate G[.I]
    derive          --run-id R (...) --gate G[.I] --answer-id X --value V --source S   (FS_HOST_DERIVE keys only)
    list            [--skill S]
    show            --run-id R (...)

The ledger is found through `<run_dir>/handoff/<R>/run_ref.json` (`--run-dir`), or under the artifacts
root before the run dir exists. `open` writes `waiting` and prints the question to ask (`needs_input`)
BEFORE it is asked; a stored pre-answer from the request is applied instead (`"applied": "pre_answer"`).
`answer` validates every segment before writing any. A recorded answer stands: a different one is
refused, except a default replaced by an answer, a bound answer whose binding changed, and `--after-hold`
once per run on a gate a hook holds.

Exit codes: 0 ok; 1 rejected (JSON with `code` on stdout, one line on stderr, ledger and status
untouched); 2 usage, IO, an unreachable registry, or a gate whose skill is not wired yet; 10 waiting
(`require`: the gate was opened, `needs_input` printed); 11 not owed; 12 waiting, and the request said not to
ask (FS_HOST_NO_ASK): nothing is asked and nothing is recorded by hand; the run waits for a request line.

Under FS_HOST_NO_ASK `answer` is refused (NO_ASK_ANSWER) and `default` only marks a company's name, sector or
geography as unknown or takes a producer's disclosed default (NO_ASK_DEFAULT otherwise). `open` that applies a
request's declining answer exits 1 (REQUEST_DECLINED): the run is `refused`.
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
except Exception as _e:  # the registry fails closed: every command exits 2
    _GATES_ERROR = f"{type(_e).__name__}: {_e}"

BY = "record_gate_answer.py"


def _emit(payload: dict[str, Any], pretty: bool) -> None:
    sys.stdout.write(json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False) + "\n")


def _exit(code: int, payload: dict[str, Any], line: str, pretty: bool) -> NoReturn:
    _emit(payload, pretty)
    print(line, file=sys.stderr)
    sys.exit(code)


def _unreachable(code: str, message: str, pretty: bool) -> NoReturn:
    _exit(2, {"status": "error", "code": code, "message": message}, f"Error: {message}", pretty)


def _gates_or_exit(pretty: bool) -> Any:
    if _gates is None:
        _unreachable("REGISTRY_UNREACHABLE", f"the plugin's gate registry is not reachable: {_GATES_ERROR}", pretty)
    return _gates


def _locate(args: argparse.Namespace) -> rs.RunPaths:
    if not rs.valid_run_id(args.run_id):
        g = _gates_or_exit(args.pretty)
        raise g.GateRejection("ID_MALFORMED", f"run id {args.run_id!r} does not match {rs.RUN_ID_RE.pattern}")
    if args.run_dir:
        paths = rs.locate_from_run_dir(args.run_dir, args.run_id)
        if paths is None:
            raise rs.RunStatusError("RUN_NOT_FOUND", f"{args.run_dir} has no run_ref.json for {args.run_id}")
        return paths
    if not args.artifacts_root:
        _unreachable("RUN_NOT_FOUND", "give --run-dir or --artifacts-root", args.pretty)
    return rs.run_paths(args.artifacts_root, args.run_id)


def _skill(paths: rs.RunPaths) -> str:
    status = rs.load_status(paths)
    if status is None:
        raise rs.RunStatusError("RUN_NOT_FOUND", f"no run status at {paths.status}")
    return str(status.get("skill"))


def cmd_open(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)
    out = g.transact(paths, lambda ctx, ledger, status: g.open_gates(ctx, ledger, args.gate, by=BY))
    if len(out["not_owed"]) == len(args.gate):
        _exit(11, {"status": "not_owed", **out}, "Not owed: none of the listed gates applies to this run", args.pretty)
    if out.get("no_ask") and out.get("waiting"):
        keys = ", ".join(w["gate"] for w in out["waiting"])
        _exit(
            g.NO_ASK_EXIT,
            {"ok": True, **out},
            f"Waiting (the request said not to ask): {keys}. {g.NO_ASK_STOP}",
            args.pretty,
        )
    _emit({"ok": True, **out}, args.pretty)
    return 0


def _refuse_no_ask_answer(g: Any, paths: rs.RunPaths) -> None:
    """Under FS_HOST_NO_ASK only a request line answers: nothing the model types is recorded."""
    try:
        ledger = g.load_ledger(paths)
    except rs.RunStatusError:
        return
    if g.no_ask(ledger):
        raise g.GateRejection(
            "NO_ASK_ANSWER",
            "the request said not to ask; an answer can only come from a request line (FS_HOST_ANSWER / "
            "FS_HOST_VALUE)" + g.NO_ASK_LEAVE,
        )


def _segments(rest: list[str]) -> list[list[str]]:
    segs: list[list[str]] = []
    for tok in rest:
        if tok == "--gate" or tok.startswith("--gate="):
            segs.append([tok])
        elif segs:
            segs[-1].append(tok)
        else:
            raise SystemExit(f"answer: {tok!r} before the first --gate")
    return segs


def _segment_parser() -> argparse.ArgumentParser:
    sp = argparse.ArgumentParser(prog="record_gate_answer.py answer --gate", add_help=False)
    sp.add_argument("--gate", required=True)
    sp.add_argument("--answer-id", dest="answer_id", default=None)
    sp.add_argument("--answer", dest="label", default=None)
    sp.add_argument("--value", default=None)
    sp.add_argument("--note", default=None)
    sp.add_argument("--after-hold", dest="after_hold", action="store_true")
    return sp


def cmd_answer(args: argparse.Namespace, rest: list[str]) -> int:
    g = _gates_or_exit(args.pretty)
    if args.form_reply:
        if rest:
            _unreachable("USAGE", "--form-reply takes no --gate segments", args.pretty)
        return _form_reply(g, args)
    if not rest:
        _unreachable("USAGE", "answer needs at least one --gate segment", args.pretty)
    parsed = []
    sp = _segment_parser()
    for seg in _segments(rest):
        a = sp.parse_args(seg)
        if (a.answer_id is None) == (a.label is None):
            _unreachable("USAGE", f"{a.gate}: give exactly one of --answer-id and --answer", args.pretty)
        parsed.append(a)
    paths = _locate(args)
    _refuse_no_ask_answer(g, paths)

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        results = []
        for a in parsed:
            results.append(
                g.record(
                    ctx,
                    ledger,
                    a.gate,
                    answer_ids=a.answer_id.split(",") if a.answer_id is not None else None,
                    label=a.label,
                    value=a.value,
                    note=a.note,
                    by=BY,
                    after_hold=a.after_hold,
                )
            )
        return {"answers": results, "declined": any(r.get("declined") for r in results)}

    out = g.transact(paths, fn)
    _emit({"ok": True, **out, "unchanged": all(r.get("unchanged") for r in out["answers"])}, args.pretty)
    return 0


def _form_reply(g: Any, args: argparse.Namespace) -> int:
    import _form_reply as fr

    if not fr.FORM_REPLY_ENABLED:
        raise g.GateRejection(
            "FORM_REPLY_DISABLED", "reading a form reply is switched off; ask with AskUserQuestion and record by id"
        )
    reply = sys.stdin.read()
    paths = _locate(args)
    _refuse_no_ask_answer(g, paths)

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        batches = ledger.get("form_batches") or []
        if not batches:
            raise g.GateRejection("FORM_REPLY_UNMATCHED", "no question form was opened for this run")
        batch = batches[-1]
        fields = []
        for key in batch["gates"]:
            gid, inst = g.parse_key(key)
            gdef = g.GATES[gid]
            opts = [(o["id"], o["label"], o["takes_value"]) for o in g.options_for(gdef, inst, ctx) if o["shown"]]
            fields.append(fr.Field(key, g.form_label_for(gdef, inst), opts, gdef["multi"]))
        try:
            parsed = fr.parse(reply, batch["header"], fields)
        except fr.FormReplyError as e:
            raise g.GateRejection(e.code, str(e), allowed=e.allowed) from e
        if parsed.skipped:
            return {"skipped": True, "answers": []}
        results = [
            g.record(ctx, ledger, key, answer_ids=ids, value=value, by=BY, asked_evidence="form")
            for key, ids, value in parsed.answers
        ]
        return {"skipped": False, "answers": results, "declined": any(r.get("declined") for r in results)}

    out = g.transact(paths, fn)
    _emit({"ok": True, **out}, args.pretty)
    return 0


def cmd_default(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> Any:
        basis = g.check_model_default(ledger, args.gate, args.reason, args.answer_id, args.value)
        return g.record(
            ctx,
            ledger,
            args.gate,
            answer_ids=[args.answer_id] if args.answer_id else None,
            value=args.value,
            note=args.note,
            resolution="default_taken",
            default_reason=args.reason,
            basis=basis,
            by=BY,
        )

    out = g.transact(paths, fn)
    _emit({"ok": True, **out}, args.pretty)
    return 0


def cmd_not_applicable(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> list[dict[str, Any]]:
        # Every gate is checked before any is recorded: one refusal writes nothing for the others either.
        for key in args.gate:
            gid, _inst, gdef = g.check_key(key, ctx.skill)
            if gdef["writer"] != g.RECORDER:
                raise g.GateRejection("WRITER_IS_OTHER_SCRIPT", f"{gid} is recorded by {gdef['writer']}")
            if gdef["owed"] != "model":
                raise g.GateRejection(
                    "CLOSE_SCRIPT_OWED", f"{gid} is decided by a script, so only that script can find it does not apply"
                )
        return [
            g.record(ctx, ledger, key, note=args.reason, resolution="not_applicable", basis="model", by=BY)
            for key in args.gate
        ]

    outs = g.transact(paths, fn)
    _emit({"ok": True, **outs[0]} if len(outs) == 1 else {"ok": True, "gates": outs}, args.pretty)
    return 0


def cmd_require(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)
    holder: dict[str, Any] = {}

    def fn(ctx: Any, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        got = g.require_terminal(ctx, ledger, args.gate, by=BY)
        holder["exit"] = g.waiting_exit(ctx, ledger, args.gate) if got == "waiting" else None
        return {"result": got}

    out = g.transact(paths, fn)
    if out["result"] == "not_owed":
        _exit(11, {"status": "not_owed", "gate": args.gate}, f"Not owed: {args.gate} does not apply", args.pretty)
    if out["result"] == "waiting":
        code, payload, line = holder["exit"]
        _exit(code, payload, line, args.pretty)
    _emit({"ok": True, "gate": args.gate, "result": "ok"}, args.pretty)
    return 0


def cmd_derive(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)
    out = g.transact(
        paths,
        lambda ctx, ledger, status: g.record_derived(
            ctx, ledger, args.gate, args.answer_id, args.value, args.source, by=BY
        ),
    )
    _emit({"ok": True, **out}, args.pretty)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    try:
        with open(g.CONTRACT_PATH, encoding="utf-8") as f:
            text = f.read()
        data = json.loads(text)
    except (OSError, ValueError) as e:
        _unreachable("REGISTRY_UNREACHABLE", f"the contract file is not readable: {e}", args.pretty)
    if args.skill is None:
        sys.stdout.write(text)
        return 0
    data["gates"] = {k: v for k, v in data["gates"].items() if v.get("skill") in (args.skill, g.SHARED)}
    _emit(data, args.pretty)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    g = _gates_or_exit(args.pretty)
    paths = _locate(args)
    ledger = g.load_ledger(paths)
    _emit(ledger, args.pretty)
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Record the answer to a registered gate")
    sub = p.add_subparsers(dest="command", required=True)

    def locator(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--run-id", required=True)
        where = sp.add_mutually_exclusive_group(required=True)
        where.add_argument("--run-dir", default=None)
        where.add_argument("--artifacts-root", default=None)
        sp.add_argument("--pretty", action="store_true")

    sp = sub.add_parser("open", help="open gates before asking (batched)")
    locator(sp)
    sp.add_argument("--gate", action="append", required=True)
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("answer", help="record answers; one --gate segment per gate")
    locator(sp)
    sp.add_argument("--form-reply", dest="form_reply", action="store_true")

    sp = sub.add_parser("default", help="record a default taken, with its reason")
    locator(sp)
    sp.add_argument("--gate", required=True)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--answer-id", dest="answer_id", default=None)
    sp.add_argument("--value", default=None)
    sp.add_argument("--note", default=None)
    sp.set_defaults(func=cmd_default)

    sp = sub.add_parser("not-applicable", help="record that model-owed gates do not apply (one reason, all or none)")
    locator(sp)
    sp.add_argument("--gate", action="append", required=True)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_not_applicable)

    sp = sub.add_parser("require", help="exit 0 when answered, 10 (opened) when not, 11 when not owed")
    locator(sp)
    sp.add_argument("--gate", required=True)
    sp.set_defaults(func=cmd_require)

    sp = sub.add_parser("derive", help="record an answer the request let the run take from the materials")
    locator(sp)
    sp.add_argument("--gate", required=True)
    sp.add_argument("--answer-id", dest="answer_id", required=True)
    sp.add_argument("--value", required=True)
    sp.add_argument("--source", required=True)
    sp.set_defaults(func=cmd_derive)

    sp = sub.add_parser("list", help="print the host contract")
    sp.add_argument("--skill", default=None)
    sp.add_argument("--pretty", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="print the run's gate ledger")
    locator(sp)
    sp.set_defaults(func=cmd_show)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = _parser()
    rest: list[str] = []
    if argv and argv[0] == "answer":
        first_gate = next((i for i, t in enumerate(argv) if t == "--gate" or t.startswith("--gate=")), len(argv))
        argv, rest = argv[:first_gate], argv[first_gate:]
    args = p.parse_args(argv)
    pretty = getattr(args, "pretty", False)
    try:
        if args.command == "answer":
            return cmd_answer(args, rest)
        return int(args.func(args))
    except rs.RunStatusError as e:
        _unreachable(e.code, str(e), pretty)
    except Exception as e:
        g = _gates
        if g is not None and isinstance(e, g.Declined):
            _exit(1, e.payload(), f"Refused ({e.code}): {e}; stop here and produce nothing", pretty)
        if g is not None and isinstance(e, g.GateRejection):
            _exit(1, e.payload(), f"Rejected ({e.code}): {e}; nothing was written", pretty)
        if g is not None and isinstance(e, g.Unimplemented):
            if getattr(e, "code", None) == "GATE_UNDECIDABLE":
                _unreachable("GATE_UNDECIDABLE", f"{e}; nothing was written", pretty)
            _unreachable("GATE_NOT_WIRED", f"{e}; this gate's skill does not record it yet", pretty)
        raise


if __name__ == "__main__":
    sys.exit(main())
