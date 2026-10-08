"""compose_result.json: what this compose run did, written beside the report when it exits.

A caller that needs compose's exit code, codes and output after the fact reads this file rather than
saving compose's streams to a file of its own. It is written only into a run dir that carries a run's
`handoff/<run_id>/run_ref.json`; a dir with none is left byte for byte as before.

The record is never stale: on entry, before compose runs, any earlier record in the dir is removed, so an
exit that writes none (a kill, a failed write) leaves no record rather than an earlier run's. It never
changes compose's arguments, stdout, stderr or exit code: both streams pass through unchanged, the flags it
needs are read with any parse error swallowed (compose then reports its own usage), and a failure to write
is one stderr line. It is a diagnostic, not a deliverable and not a checkpoint: its run id is top level,
never `metadata.run_id`, so nothing that reuses a run's stamped artifacts picks it up.

A second interrupt that arrives while the record is being written replaces the exit that was pending.

Every skill's scripts dir carries an identical copy (skill scripts cannot import across skills); a test
holds the copies equal.
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TextIO

NAME = "compose_result.json"
SCHEMA = "founder-skills/compose_result"
SCHEMA_VERSION = 1
RUN_REF_NAME = "run_ref.json"
# Each stream is kept up to this many characters, from its end: what a caller needs is the last lines, and
# the whole record must stay well under the 64 KiB a recording captures of a file.
STREAM_CAP = 16 * 1024
# The exit code of a process ended by Ctrl-C.
INTERRUPTED = 130


class _Tee:
    """A text stream that writes through to `inner` unchanged and keeps the end of what was written."""

    def __init__(self, inner: TextIO) -> None:
        self.inner = inner
        self.parts: list[str] = []
        self.size = 0
        self.total = 0

    def write(self, s: str) -> int:
        n = self.inner.write(s)
        self.parts.append(s)
        self.size += len(s)
        self.total += len(s)
        while self.size > 4 * STREAM_CAP and len(self.parts) > 1:
            self.size -= len(self.parts.pop(0))
        return n

    def text(self) -> str:
        return "".join(self.parts)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _paths(argv: list[str]) -> argparse.Namespace | None:
    """The flags the record needs, or None when they cannot be read. Prints nothing and never exits:
    compose parses its own arguments and reports its own errors."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-d", "--dir")
    p.add_argument("-o", "--output")
    p.add_argument("--write-md")
    p.add_argument("--run-id")  # read only where it is the skill's own derivation (`run_id_flag`)
    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        ns, _ = p.parse_known_args(argv)
    except SystemExit:
        return None
    finally:
        sys.stderr = saved
    return ns


def _dir_by_hand(argv: list[str]) -> str | None:
    """`--dir` read token by token, for an argv the parser refused (a flag missing its value): the record
    must still be replaced, or the previous call's would read as this one's."""
    for i, a in enumerate(argv):
        if a in ("-d", "--dir") and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--dir="):
            return a[len("--dir=") :]
        if a.startswith("-d") and len(a) > 2 and not a.startswith("--"):
            return a[2:]
    return None


def has_any_ref(run_dir: str) -> bool:
    """Whether the dir carries any run's ref: the test for writing a record at all."""
    return bool(glob.glob(os.path.join(glob.escape(run_dir), "handoff", "*", RUN_REF_NAME)))


def _rel(path: str, run_dir: str) -> str:
    full = os.path.abspath(path)
    rel = os.path.relpath(full, run_dir)
    return full if rel.startswith("..") else rel


def _stat(path: str | None) -> tuple[int, int, int] | None:
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _last_json(text: str) -> Any:
    """The JSON compose printed: the whole stream, else its last line that parses."""
    with contextlib.suppress(ValueError):
        return json.loads(text)
    for line in reversed(text.strip().splitlines()):
        with contextlib.suppress(ValueError):
            return json.loads(line)
    return None


def _exit_code(exc: BaseException | None) -> int:
    if exc is None:
        return 0
    if isinstance(exc, SystemExit):
        c = exc.code
        return 0 if c is None else c if isinstance(c, int) else 1
    if isinstance(exc, KeyboardInterrupt):
        return INTERRUPTED
    return 1


def _write(path: str, body: dict[str, Any]) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class recording:
    """`with recording(skill=..., run_id_of=...): main()`. A context manager, not a wrapper function: nothing
    is caught, so every exit (a SystemExit with its own code, an error with its own traceback) passes through
    unchanged. `run_id_of(run_dir)` is the skill's own run-id derivation, asked after compose has run;
    `run_id_flag` is for the skill whose derivation is its own required `--run-id`."""

    def __init__(
        self, *, skill: str, run_id_of: Callable[[str], str | None] | None = None, run_id_flag: bool = False
    ) -> None:
        self.skill, self.run_id_of, self.run_id_flag = skill, run_id_of, run_id_flag

    def __enter__(self) -> recording:
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.started_ns = time.time_ns()
        self.args = _paths(sys.argv[1:])
        self.run_dir: str | None = None
        given = self.args.dir if self.args is not None else _dir_by_hand(sys.argv[1:])
        if given and os.path.isdir(given):
            run_dir = os.path.abspath(given)
            if has_any_ref(run_dir):
                self.run_dir = run_dir
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(os.path.join(run_dir, NAME))
        self.before = {k: _stat(getattr(self.args, k, None)) for k in ("output", "write_md")}
        self.out, self.err = _Tee(sys.stdout), _Tee(sys.stderr)
        sys.stdout, sys.stderr = self.out, self.err  # type: ignore[assignment]
        return self

    def __exit__(self, et: Any, exc: BaseException | None, tb: Any) -> None:
        sys.stdout, sys.stderr = self.out.inner, self.err.inner
        if self.run_dir is None:
            return
        try:
            _write(os.path.join(self.run_dir, NAME), self._body(exc))
        except Exception as e:  # noqa: BLE001 -- the diagnostic never changes compose's outcome
            # The earlier record was removed on entry, so a failed write leaves none.
            print(f"warning: {NAME} was not written: {e}", file=sys.stderr)

    def _run_id(self) -> str | None:
        if self.run_id_flag:
            rid = getattr(self.args, "run_id", None)
        elif self.run_id_of is not None and self.run_dir is not None:
            try:
                rid = self.run_id_of(self.run_dir)
            except Exception:  # noqa: BLE001 -- an underivable id is recorded as null
                rid = None
        else:
            rid = None
        return rid if isinstance(rid, str) and rid else None

    def _output(self, key: str, code: int) -> dict[str, Any] | None:
        path = getattr(self.args, key, None)
        if not path or self.run_dir is None:
            return None
        now = _stat(path)
        if now is None:
            return {"path": _rel(path, self.run_dir), "exists": False, "written": False}
        # Changed on disk, or a clean exit after which it exists: a rewrite with the same size inside one
        # timestamp tick leaves the stat unchanged.
        written = now[1] > 0 and (now != self.before[key] or code == 0)
        return {"path": _rel(path, self.run_dir), "exists": True, "written": written}

    def _body(self, exc: BaseException | None) -> dict[str, Any]:
        code = _exit_code(exc)
        stdout, stderr = self.out.text(), self.err.text()
        if isinstance(exc, SystemExit) and isinstance(exc.code, str):
            stderr += exc.code + "\n"  # the interpreter prints it after this context exits
        elif exc is not None and not isinstance(exc, SystemExit):
            stderr += f"{type(exc).__name__}: {exc}\n"
        report_json = self._output("output", code)
        report_md = self._output("write_md", code)
        # What compose printed, parsed (a receipt, a refusal or a question); never a whole report printed
        # to stdout.
        printed = _last_json(stdout) if self.out.total <= STREAM_CAP else None
        printed = printed if isinstance(printed, dict) else None
        status, warnings = None, None
        if report_json is not None and report_json["written"]:
            try:
                with open(self.args.output, encoding="utf-8") as f:  # type: ignore[union-attr]
                    report = json.load(f) or {}
                # Five composes keep their warnings under `validation`; competitive-positioning's are top level.
                nested = report.get("validation")
                v: dict[str, Any] = nested if isinstance(nested, dict) else report
                status = v.get("status") if isinstance(nested, dict) else None
                warnings = [
                    {"code": w.get("code"), "severity": w.get("severity")}
                    for w in (v.get("warnings") or [])
                    if isinstance(w, dict)
                ]
            except (OSError, ValueError, AttributeError):
                status, warnings = None, None
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "skill": self.skill,
            "run_id": self._run_id(),
            "exit_code": code,
            "status": (printed or {}).get("status"),
            "code": (printed or {}).get("code"),
            "blocked_by_gate": (printed or {}).get("blocked_by_gate"),
            "validation_status": status,
            "warnings": warnings,
            "outputs": {"report_json": report_json, "report_md": report_md},
            "printed": printed,
            "stdout": stdout[-STREAM_CAP:],
            "stdout_truncated": self.out.total > STREAM_CAP,
            "stderr": stderr[-STREAM_CAP:],
            "stderr_truncated": max(len(stderr), self.err.total) > STREAM_CAP,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
