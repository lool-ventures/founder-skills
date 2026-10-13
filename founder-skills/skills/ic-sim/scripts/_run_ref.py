"""Does this run have a gate ledger? Answered from the run dir alone, with nothing from the plugin root.

A run that has one carries `<run_dir>/handoff/<RUN_ID>/run_ref.json`. Skill scripts ask here before
touching any shared code, because the plugin's shared `scripts/` directory is absent on a flat mount:
with no ref, a writer takes today's path and never loads anything else. With a ref, it loads the shared
modules through `load_shared`, which raises ImportError when they are not reachable.

Every skill's scripts dir carries an identical copy (skill scripts are standalone and cannot import
across skills); a test holds the copies equal, and `RUN_ID_RE` equal to the shared `_run_status.py`.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys
from collections.abc import Iterable
from types import ModuleType
from typing import Any, NoReturn

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUN_REF_NAME = "run_ref.json"
META_NAME = "founder-skills-run-id"

_HEAD = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)
_SHARED_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))


def run_ref_path(run_dir: str, run_id: str) -> str:
    return os.path.join(run_dir, "handoff", run_id, RUN_REF_NAME)


def folder_current_run(run_dir: str) -> str | None:
    """The run this folder belongs to now: the run whose `run_ref.json` here was bound last.

    Read from the folder alone (no status, no ledger, no lock): every `bind` stamps its ref with `bound_seq`
    (one more than the highest already in the folder) and `bound_at`, so the newest bind wins, a re-bind of
    an earlier run (a host resume) takes the folder back, and an implicit reopen (which does not bind) does
    not. Refs with no stamp (bound before the stamp existed) sort below every stamped one and among
    themselves by the ref file's mtime. A tie on all of that (two binds in the same instant computing the
    same `bound_seq`) is broken by the run id: a host error, named here as a residual. A ref that cannot be
    read is skipped. None when the folder carries no ref.

    `_run_status.folder_current_run` is canonical; each skill's `_run_ref.py` carries the same function
    (held equal by a test), so a skill script answers this without loading the plugin's shared code.
    """
    best: tuple[int, str, float, str] | None = None
    pattern = os.path.join(glob.escape(os.path.abspath(run_dir)), "handoff", "*", RUN_REF_NAME)
    for ref in glob.glob(pattern):
        run_id = os.path.basename(os.path.dirname(ref))
        if not RUN_ID_RE.match(run_id):
            continue
        try:
            with open(ref, encoding="utf-8") as f:
                data = json.load(f)
            mtime = os.path.getmtime(ref)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        seq = data.get("bound_seq")
        at = data.get("bound_at")
        key = (
            seq if isinstance(seq, int) and not isinstance(seq, bool) else 0,
            at if isinstance(at, str) else "",
            mtime,
            run_id,
        )
        if best is None or key > best:
            best = key
    return best[3] if best is not None else None


def has_ledger(run_dir: str, run_id: object) -> bool:
    """True when the run dir carries this run's `run_ref.json`. A ref whose ledger is then missing is
    still ledger mode: the shared code refuses it, and it never falls back to the no-ledger path."""
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        return False
    return os.path.isfile(run_ref_path(run_dir, run_id))


def _artifact_run_id(path: str) -> tuple[bool, object]:
    """(carries an id, the id) for a JSON object file: `metadata.run_id`, or a top-level `run_id` when it has no
    `metadata` (cap-table's receipts). A file that is not a JSON object, or carries no id, is (False, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, None
    if not isinstance(data, dict):
        return False, None
    meta = data.get("metadata")
    if isinstance(meta, dict):
        return ("run_id" in meta and meta["run_id"] is not None), meta.get("run_id")
    return ("run_id" in data and data["run_id"] is not None), data.get("run_id")


def foreign_artifacts(run_dir: str, run_id: str, paths: Iterable[str | None]) -> list[tuple[str, str]]:
    """(file name, the id it carries) for each path that is a regular file inside the run dir (not under
    `handoff/`, whose files are namespaced per run), parses as a JSON object, and carries another run's id (or a
    malformed one). Files outside the run dir (the founder's uploads, another skill's folder), non-JSON files and
    id-less JSON are not compared."""
    base = os.path.realpath(run_dir)
    handoff = os.path.join(base, "handoff")
    out: list[tuple[str, str]] = []
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        real = os.path.realpath(p)
        if not real.startswith(base + os.sep) or real.startswith(handoff + os.sep):
            continue
        has, rid = _artifact_run_id(p)
        if has and rid != run_id:
            out.append((os.path.relpath(real, base), str(rid)))
    return out


def _reject(code: str, message: str, written: str, **extra: object) -> NoReturn:
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message, **extra}) + "\n")
    print(f"Error ({code}): {message}; {written}", file=sys.stderr)
    sys.exit(1)


def refuse_not_this_runs(
    run_dir: str | None,
    run_id: str | None,
    inputs: Iterable[str | None] = (),
    *,
    noun: str,
    written: str = "nothing was written",
) -> None:
    """In a folder that belongs to a run (it carries any `run_ref.json`), a step runs only as that folder's
    current run and reads only that run's files. Exit 1, nothing written, on the first of:
    1. no id: `RUN_ID_REQUIRED`;
    2. no ref for the id here: `RUN_NOT_BOUND`;
    3. the id is not the folder's current run (`folder_current_run`, the newest bind): `RUN_SUPERSEDED`,
       naming the run that holds the folder;
    4. an input carrying another run's id (`foreign_artifacts`): `ARTIFACT_OTHER_RUN`, naming each file.
    A folder with no ref returns at once and reads nothing (the no-ledger path, byte-identical). Loads nothing
    from the plugin root. `written` ends the stderr line (cap-table's compose still records its own exit)."""
    if not run_dir:
        return
    run_dir = os.path.abspath(run_dir)
    if not glob.glob(os.path.join(glob.escape(run_dir), "handoff", "*", RUN_REF_NAME)):
        return
    if not run_id:
        _reject(
            "RUN_ID_REQUIRED", f"this {noun} belongs to a run; pass its --run-id so the run's checks apply", written
        )
    current = folder_current_run(run_dir)
    if not has_ledger(run_dir, run_id):
        _reject(
            "RUN_NOT_BOUND",
            f"--run-id {run_id!r} is not a run bound to this {noun}, which belongs to {current}; pass that run's id "
            "(the run_id Step 0 printed), or start a new run for a new review",
            written,
        )
    if current is not None and current != run_id:
        _reject(
            "RUN_SUPERSEDED",
            f"run {run_id} no longer holds this {noun}: run {current} was bound here after it. Pass {current}'s id "
            "to continue the review this folder holds now, or start a new run in another folder to revisit the "
            "earlier one",
            written,
            current_run=current,
        )
    foreign = foreign_artifacts(run_dir, str(run_id), inputs)
    if foreign:
        names = ", ".join(f"{name} (run {rid})" for name, rid in foreign)
        bound_here = [rid for _n, rid in foreign if has_ledger(run_dir, rid)]
        why = "which another run bound to this folder wrote" if bound_here else "left by an earlier review"
        _reject(
            "ARTIFACT_OTHER_RUN",
            f"this step reads {names}, {why}, not this run's",
            written,
            files=[{"file": name, "run_id": rid} for name, rid in foreign],
            fix=(
                "run the step that writes each named file again for this run, even on a resume: the resume rule "
                "keeps only this run's own files"
            ),
        )


def stamp_html(html: str, run_id: str) -> str | None:
    """The page with this run's id in a meta tag right after its first `<head>`; None if it has none."""
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"run id {run_id!r} is not a valid run id")
    m = _HEAD.search(html)
    if m is None:
        return None
    tag = f'<meta name="{META_NAME}" content="{run_id}">'
    return html[: m.end()] + tag + html[m.end() :]


def _load(name: str) -> ModuleType:
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    path = os.path.join(_SHARED_DIR, f"{name}.py")
    if not os.path.isfile(path):
        raise ImportError(f"the plugin's shared {name}.py is not reachable at {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def load_shared(name: str) -> ModuleType:
    """A shared module by path from the plugin's `scripts/`. Raises ImportError when it is not there."""
    _load("_run_status")
    return _load(name)


class LedgerUnavailable(Exception):
    """The run has a `run_ref.json`, but its ledger or the shared code cannot be reached. Exit 2."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def open_ledger(run_dir: str, run_id: object) -> tuple[ModuleType, Any] | None:
    """(the shared `_gates` module, the run's paths), or None when this run has no ledger.

    With a ref, nothing falls back to the no-ledger path: an unreachable registry or a missing ledger
    raises LedgerUnavailable.
    """
    if not has_ledger(run_dir, run_id):
        return None
    try:
        gates = load_shared("_gates")
    except Exception as e:
        raise LedgerUnavailable("REGISTRY_UNREACHABLE", f"the plugin's gate registry is not reachable: {e}") from e
    status = sys.modules["_run_status"]
    try:
        paths = status.locate_from_run_dir(run_dir, run_id)
    except status.RunStatusError as e:
        raise LedgerUnavailable(e.code, str(e)) from e
    return gates, paths


def report_failure(exc: BaseException) -> int:
    """Print a ledger failure the way every gate script does (JSON on stdout, one stderr line) and return
    its exit code: 1 for a rejected answer, 2 for anything unreachable. Re-raises anything else."""
    payload = getattr(exc, "payload", None)
    if callable(payload):
        body = payload()
        code = 1
    elif isinstance(exc, LedgerUnavailable) or type(exc).__name__ in ("RunStatusError", "Unimplemented"):
        body = {"status": "error", "code": getattr(exc, "code", "GATE_NOT_WIRED"), "message": str(exc)}
        code = 2
    else:
        raise exc
    sys.stdout.write(json.dumps(body) + "\n")
    if type(exc).__name__ == "Declined":
        # The run was stopped for good (recorded `refused`): no later step may run.
        print(f"Refused ({body['code']}): {exc}; stop here and produce nothing", file=sys.stderr)
        return code
    print(f"Error ({body['code']}): {exc}; nothing was written", file=sys.stderr)
    return code


def json_run_id(path: str) -> str | None:
    """`metadata.run_id` of a JSON artifact, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    meta = data.get("metadata") if isinstance(data, dict) else None
    rid = meta.get("run_id") if isinstance(meta, dict) else None
    return rid if isinstance(rid, str) and rid else None


def page_for_run(html: str, run_id: str, own_run_id: str | None) -> str:
    """The page stamped with `run_id`, or a loud refusal (exit 1, nothing written).

    A page is stamped only with the run id its own artifacts carry: a stamp is what lets a host tell
    this run's page from an earlier run's file left in the same folder.
    """
    problem = None
    if not RUN_ID_RE.match(run_id):
        problem = f"--run-id {run_id!r} is not a valid run id"
    elif own_run_id != run_id:
        problem = f"--run-id {run_id!r} is not the run id this page's artifacts carry ({own_run_id!r})"
    stamped = None if problem else stamp_html(html, run_id)
    if stamped is None:
        problem = problem or "the page has no <head> to carry the run id"
        sys.stdout.write(json.dumps({"status": "rejected", "code": "RUN_ID_MISMATCH", "message": problem}) + "\n")
        print(f"Error: {problem}; no page was written", file=sys.stderr)
        sys.exit(1)
    return stamped


def list_page(run_dir: str, run_id: str, key: str, path: str, writer: str) -> None:
    """List a page this run wrote among the run's deliverables. Never changes the writer's stdout or exit:
    a failure is one stderr line, and the page stays unlisted (a host copies only listed files)."""
    if not has_ledger(run_dir, run_id):
        return
    try:
        status = load_shared("_run_status")
        paths = status.locate_from_run_dir(run_dir, run_id)
        status.add_deliverable(paths, key, os.path.abspath(path), status.file_sha256(path), writer)
    except Exception as e:
        print(f"warning: the page was written but not listed in the run status: {e}", file=sys.stderr)
