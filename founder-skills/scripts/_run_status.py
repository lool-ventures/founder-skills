"""A run's status file, its lock, and the run-level facts every writer shares.

`<ARTIFACTS_ROOT>/runs/<RUN_ID>/run_status.json` is what a host reads to learn where a run stands:
running, waiting on a question, complete, or refused. The gate ledger (`gates.json`) sits beside it and
is owned by `_gates.py`; this module never imports that one. `_gates.py` pushes its view of the gates
into the status through `update()`, and the writers that know nothing about gates (the coaching
inserter, the HTML pages) call the narrow helpers at the bottom.

Every run dir that has a ledger carries `handoff/<RUN_ID>/run_ref.json`, naming the ledger by a path
RELATIVE to the artifacts root. Skill scripts find it through their sibling `_run_ref.py`, which needs
nothing from this directory.

One lock per run (`runs/<id>/gates.json.lock`), held across read-check-write. `flock` where the
filesystem has it; otherwise an exclusive lockfile with a stale timeout. A writer never proceeds
unlocked: a run whose lock cannot be taken fails, and the caller reports it.

Standalone: stdlib only. Imported by path from the shared scripts beside it and, through
`_run_ref.load_shared`, from skill scripts once they know a ledger exists.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# The one RUN_ID grammar. A run id names a directory, so a sub-path (`<id>/r2`), a leading dot or
# anything shell-hostile is refused. Each skill's `_run_ref.py` carries a copy, held equal by a test.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SCHEMA = "founder-skills/run_status"
SCHEMA_VERSION = 1
RUN_REF_SCHEMA = "founder-skills/run_ref"
RUN_REF_NAME = "run_ref.json"

STATUSES = ("running", "waiting", "complete", "refused")
FINAL_STATUSES = ("complete", "refused")

# Codes change only by addition: hosts key on them.
# Some are written by the skills' own scripts as each is wired; all are accepted here from the start.
STATUS_CODES: dict[str, tuple[str, ...]] = {
    "running": ("RUNNING",),
    "waiting": (
        "GATE_WAITING",
        "GATE_UNANSWERED",
        "GATE_INTERMEDIATE",
        "OUT_OF_SCOPE_UNANSWERED",
        "AUTO_SATISFY_NOT_ALLOWED",
        "PRE_ANSWER_UNLISTED",
    ),
    "complete": ("COMPLETE",),
    "refused": ("FOUNDER_DECLINED", "INPUT_MISSING", "PRE_ANSWER_INVALID"),
}
LAST_ERROR_CODES = ("GATE_INVALID", "GATE_OTHER_RUN", "PROFILE_MISMATCH", "GATE_UNRESOLVED", "COACHING_BLOCKED")
PRINT_ONLY_CODES = ("RUN_ID_IN_USE", "RUN_ID_FINISHED", "RUN_ID_MALFORMED")

# What a host reads in `message`. Plain sentences, no internal tokens: a test scans each one.
MESSAGES: dict[str, str] = {
    "RUNNING": "The review is in progress.",
    "GATE_WAITING": "Waiting for an answer: {question}",
    "GATE_INTERMEDIATE": "Waiting for a follow-up answer: {question}",
    "GATE_UNANSWERED": "Waiting for an answer that was asked for and not given: {question}",
    "OUT_OF_SCOPE_UNANSWERED": "Waiting for an answer on whether to continue a review outside its stage range.",
    "AUTO_SATISFY_NOT_ALLOWED": "Waiting for an answer this question must get from the founder: {question}",
    "INPUT_MISSING": "The review could not start: a file it needs was not provided.",
    "GATE_INVALID": "The review is in progress; a recorded answer could not be used and has to be asked again.",
    "GATE_OTHER_RUN": "The review is in progress; a recorded answer belongs to an earlier review.",
    "PROFILE_MISMATCH": "The review is in progress; a recorded answer no longer matches the review's inputs.",
    "GATE_UNRESOLVED": "The review is in progress; a question it needed was not settled.",
    "PRE_ANSWER_UNLISTED": "Waiting for an answer, because an answer sent with the request is not one of the choices: "
    "{question}",
    "COMPLETE": "The review is complete.",
    "FOUNDER_DECLINED": "The founder chose not to continue.",
    "PRE_ANSWER_INVALID": "An answer sent with the request could not be used, so the review did not start.",
    "COACHING_BLOCKED": "The review is in progress; the coaching commentary could not be added yet.",
}

# Whether a `waiting` run can be resumed, per surface. Conservative: until a new session has been shown
# to see an earlier session's outputs on a surface, a waiting run there resumes only in the session
# that started it. An entry moves to `true` only by a deliberate edit.
RESUMABLE_BY_SURFACE: dict[str, bool | str] = {
    "cli": "same_session",
    "cli_artifacts_root": "same_session",
    "cowork_local": "same_session",
    "cowork_cloud": "same_session",
}

# The HTML pages each skill builds AFTER its coaching is inserted. At `complete` a run whose pages are
# not all listed for the current revision reads `deliverables_status: pending`; the last page write
# makes it `final`. A skill whose pages are built before coaching has none here.
PAGES_AFTER_COACHING: dict[str, tuple[str, ...]] = {
    "deck-review": ("report_html",),
    "market-sizing": ("report_html",),
    "ic-sim": ("report_html",),
    "competitive-positioning": ("report_html", "explorer_html"),
    "financial-model-review": (),
    "cap-table": (),
}

DELIVERABLE_KEYS = ("report_md", "report_json", "report_html", "explorer_html")

# Every key of run_status.json, in order. Every one is always present; null when unset.
FIELDS: tuple[str, ...] = (
    "schema",
    "schema_version",
    "skill",
    "run_id",
    "slug",
    "mode",
    "revision",
    "status",
    "code",
    "last_error_code",
    "message",
    "updated_at",
    "plugin_version",
    "scripts_dir_shell",
    "shared_scripts_dir_shell",
    "artifacts_root_shell",
    "run_dir_shell",
    "run_status_path_host",
    "waiting_on",
    "resumable",
    "resume_prompt",
    "gates",
    "coaching",
    "deliverables",
    "deliverables_status",
    "handed_over_at",
    "disclosures",
    "notices",
)

# Mode from the run dir's suffix. The suffix is chosen by the skill's own routing, never typed here.
MODE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("-quickcheck", "quick_check"),
    ("-fastassess", "fast_assess"),
    ("-concise", "concise"),
    ("-extraction", "extraction_only"),
)
MODES = ("full", "quick_check", "fast_assess", "concise", "extraction_only", "rule_lookup")

_SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SHARED_DIR)
_STALE_TMP = re.compile(r"^(gates|run_status)\.json\.tmp-\d+$")

# The fallback lockfile is treated as abandoned after this long; a writer waits at most LOCK_WAIT_S.
LOCK_STALE_S = 60.0
LOCK_WAIT_S = 30.0


class RunStatusError(Exception):
    """A run-level failure a CLI reports with a stable `code` and exit 2."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def valid_run_id(value: object) -> bool:
    return isinstance(value, str) and RUN_ID_RE.match(value) is not None


def mint_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def mode_for_run_dir(run_dir: str) -> str:
    base = os.path.basename(os.path.normpath(run_dir))
    for suffix, mode in MODE_SUFFIXES:
        if base.endswith(suffix):
            return mode
    return "full"


def plugin_version() -> str | None:
    try:
        with open(os.path.join(_PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            version = json.load(f).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


def shared_scripts_dir() -> str:
    return _SHARED_DIR


def surface(cwd: str, env: dict[str, str]) -> str:
    """Which host this run is on, as far as the shell can tell."""
    if env.get("COWORK_ARTIFACTS_ROOT"):
        return "cli_artifacts_root"
    if env.get("CLAUDE_CODE_REMOTE") == "true":
        return "cowork_cloud"
    if re.match(r"^/sessions/[^/]+(?:/|$)", cwd):
        return "cowork_local"
    return "cli"


# --- paths ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunPaths:
    artifacts_root: str
    run_id: str

    @property
    def run_root(self) -> str:
        return os.path.join(self.artifacts_root, "runs", self.run_id)

    @property
    def status(self) -> str:
        return os.path.join(self.run_root, "run_status.json")

    @property
    def ledger(self) -> str:
        return os.path.join(self.run_root, "gates.json")

    @property
    def lock(self) -> str:
        return os.path.join(self.run_root, "gates.json.lock")

    @property
    def refusals(self) -> str:
        return os.path.join(self.run_root, "start_refusals.jsonl")

    @property
    def ledger_rel(self) -> str:
        return f"runs/{self.run_id}/gates.json"


def run_paths(artifacts_root: str, run_id: str) -> RunPaths:
    if not valid_run_id(run_id):
        raise RunStatusError("RUN_ID_MALFORMED", f"run id {run_id!r} does not match {RUN_ID_RE.pattern}")
    return RunPaths(os.path.abspath(artifacts_root), run_id)


def run_ref_path(run_dir: str, run_id: str) -> str:
    return os.path.join(run_dir, "handoff", run_id, RUN_REF_NAME)


def write_run_ref(run_dir: str, paths: RunPaths, skill: str) -> str:
    path = run_ref_path(run_dir, paths.run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "schema": RUN_REF_SCHEMA,
        "schema_version": 1,
        "run_id": paths.run_id,
        "skill": skill,
        "ledger_rel": paths.ledger_rel,
    }
    atomic_write_json(path, data)
    return path


def locate_from_run_dir(run_dir: str, run_id: str) -> RunPaths | None:
    """The run's paths from its run dir's `run_ref.json`; None when the run dir names no ledger.

    The ledger path in the ref is relative to the artifacts root, which is an ancestor of the run dir:
    the nearest ancestor holding that path is the root. A ref whose ledger is nowhere is an error, never
    a quiet fall back to "no ledger": `LEDGER_MISSING`.
    """
    if not valid_run_id(run_id):
        raise RunStatusError("RUN_ID_MALFORMED", f"run id {run_id!r} does not match {RUN_ID_RE.pattern}")
    ref_path = run_ref_path(run_dir, run_id)
    if not os.path.isfile(ref_path):
        return None
    try:
        ref = read_json(ref_path)
    except ValueError as e:
        raise RunStatusError("LEDGER_MISSING", f"{ref_path} is not readable: {e}") from e
    rel = ref.get("ledger_rel") if isinstance(ref, dict) else None
    if not isinstance(ref, dict) or ref.get("run_id") != run_id or not isinstance(rel, str):
        raise RunStatusError("LEDGER_MISSING", f"{ref_path} does not name this run's ledger")
    if os.path.isabs(rel) or ".." in rel.split("/"):
        raise RunStatusError("LEDGER_MISSING", f"{ref_path} names a ledger outside the artifacts root")
    probe = os.path.dirname(os.path.abspath(run_dir))
    while True:
        if os.path.isfile(os.path.join(probe, rel)):
            return run_paths(probe, run_id)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    raise RunStatusError("LEDGER_MISSING", f"{ref_path} names {rel}, which is not under any parent of the run dir")


# --- file IO ---------------------------------------------------------------------------------------


def read_json(path: str) -> Any:
    """The parsed file, or None when absent. Unparseable raises ValueError: unreadable is not absent."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}") from e


def atomic_write_json(path: str, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def sweep_stale_tmp(run_root: str) -> None:
    with contextlib.suppress(OSError):
        for name in os.listdir(run_root):
            if _STALE_TMP.match(name):
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(run_root, name))


def append_jsonl(path: str, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


# --- the lock --------------------------------------------------------------------------------------

_HELD: dict[str, int] = {}


def _flock(fd: int) -> bool:
    try:
        import fcntl
    except ImportError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def _excl_lockfile(path: str) -> Iterator[None]:
    """An O_EXCL lockfile, for filesystems without flock. A lockfile older than LOCK_STALE_S is a writer
    that died holding it, and is taken over."""
    marker = f"{path}.excl"
    token = f"{os.getpid()}-{secrets.token_hex(8)}"
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, token.encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(marker)
            except OSError:
                continue
            if age > LOCK_STALE_S:
                with contextlib.suppress(OSError):
                    os.unlink(marker)
                continue
            if time.monotonic() > deadline:
                raise RunStatusError("LOCK_UNAVAILABLE", f"the run lock {marker} is held by another writer") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        # Only our own marker: if this writer stalled past LOCK_STALE_S, another may hold the lock now.
        with contextlib.suppress(OSError):
            with open(marker, encoding="utf-8") as f:
                mine = f.read() == token
            if mine:
                os.unlink(marker)


@contextlib.contextmanager
def run_lock(paths: RunPaths, *, create: bool = False) -> Iterator[None]:
    """Exclusive, re-entrant within one process. Only `start` creates the run dir (`create=True`); for any
    other writer a missing run is RUN_NOT_FOUND, with nothing created."""
    key = paths.lock
    if _HELD.get(key):
        _HELD[key] += 1
        try:
            yield
        finally:
            _HELD[key] -= 1
        return
    if create:
        os.makedirs(paths.run_root, exist_ok=True)
    elif not os.path.isdir(paths.run_root):
        raise RunStatusError("RUN_NOT_FOUND", f"no run at {paths.run_root}")
    with open(key, "a+", encoding="utf-8") as fh:
        if _flock(fh.fileno()):
            _HELD[key] = 1
            try:
                sweep_stale_tmp(paths.run_root)
                yield
            finally:
                _HELD.pop(key, None)
            return
        with _excl_lockfile(key):
            _HELD[key] = 1
            try:
                sweep_stale_tmp(paths.run_root)
                yield
            finally:
                _HELD.pop(key, None)


def pause_for_tests() -> None:
    """Hold the lock a moment when `FOUNDER_SKILLS_LOCK_PAUSE_S` is set, so a test can make two writers
    overlap inside the critical section. Unset in every real run."""
    raw = os.environ.get("FOUNDER_SKILLS_LOCK_PAUSE_S")
    if raw:
        with contextlib.suppress(ValueError):
            time.sleep(min(float(raw), 5.0))


# --- the status document -----------------------------------------------------------------------------


def blank_status(skill: str, paths: RunPaths) -> dict[str, Any]:
    status: dict[str, Any] = dict.fromkeys(FIELDS)
    status.update(
        {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "skill": skill,
            "run_id": paths.run_id,
            "revision": 0,
            "plugin_version": plugin_version(),
            "shared_scripts_dir_shell": _SHARED_DIR,
            "artifacts_root_shell": paths.artifacts_root,
            "gates": [],
            "disclosures": [],
            "notices": [],
        }
    )
    set_state(status, "running", "RUNNING")
    return status


def set_state(status: dict[str, Any], state: str, code: str, **fill: str) -> None:
    """The one place a status/code/message triple is written."""
    if state not in STATUSES or code not in STATUS_CODES[state]:
        raise ValueError(f"{code} is not a {state} code")
    status["status"] = state
    status["code"] = code
    status["message"] = _message(code, fill)
    if state != "waiting":
        status["waiting_on"] = None
        status["resumable"] = None
        status["resume_prompt"] = None
    if state == "complete":
        status["last_error_code"] = None


def _message(code: str, fill: dict[str, str]) -> str:
    template = MESSAGES[code]
    try:
        return template.format(**fill)
    except (KeyError, IndexError):
        return template.split("{", 1)[0].rstrip(": ")


def normalise(status: dict[str, Any]) -> dict[str, Any]:
    """Every field present, in FIELDS order; unknown keys kept after them."""
    out = {k: status.get(k) for k in FIELDS}
    for k, v in status.items():
        if k not in out:
            out[k] = v
    return out


def load_status(paths: RunPaths) -> dict[str, Any] | None:
    data = read_json(paths.status)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"{paths.status} is not a JSON object")
    return data


def write_status(paths: RunPaths, status: dict[str, Any]) -> None:
    status["updated_at"] = now_iso()
    atomic_write_json(paths.status, normalise(status))


def create_status_exclusive(paths: RunPaths, status: dict[str, Any]) -> bool:
    """Create run_status.json only if absent (O_EXCL), so two fresh starts cannot both create it."""
    os.makedirs(paths.run_root, exist_ok=True)
    try:
        fd = os.open(paths.status, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    status["updated_at"] = now_iso()
    text = json.dumps(normalise(status), indent=2, ensure_ascii=False) + "\n"
    try:
        os.write(fd, text.encode("utf-8"))
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)
    return True


def update(paths: RunPaths, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Read-modify-write the status under the run lock. No status → RUN_NOT_FOUND."""
    with run_lock(paths):
        status = load_status(paths)
        if status is None:
            raise RunStatusError("RUN_NOT_FOUND", f"no run status at {paths.status}")
        fn(status)
        write_status(paths, status)
        return status


def open_gate_ids(paths: RunPaths) -> list[str]:
    """Gate keys the ledger holds open. Read-only: the ledger is written only by `_gates.py`."""
    ledger = read_json(paths.ledger)
    if not isinstance(ledger, dict):
        return []
    gates = ledger.get("gates")
    if not isinstance(gates, dict):
        return []
    return sorted(k for k, g in gates.items() if isinstance(g, dict) and g.get("state") == "open")


# --- completion and deliverables ---------------------------------------------------------------------


def _listed_pages(status: dict[str, Any]) -> set[str]:
    deliverables = status.get("deliverables") or {}
    revision = status.get("revision") or 0
    return {
        k
        for k, v in deliverables.items()
        if k in ("report_html", "explorer_html") and isinstance(v, dict) and v.get("revision") == revision
    }


def deliverables_status_for(status: dict[str, Any]) -> str:
    expected = set(PAGES_AFTER_COACHING.get(str(status.get("skill")), ()))
    return "final" if expected <= _listed_pages(status) else "pending"


def mark_complete(status: dict[str, Any]) -> None:
    """`complete`, with the deliverables status that goes with it."""
    set_state(status, "complete", "COMPLETE")
    if status.get("mode") in (None, "full"):
        status["deliverables_status"] = deliverables_status_for(status)
    else:
        status["deliverables_status"] = "final"


def deliverable_entry(path: str, sha256: str, writer: str, revision: int) -> dict[str, Any]:
    return {
        "file": os.path.basename(path),
        "path_shell": os.path.abspath(path),
        "sha256": sha256,
        "written_at": now_iso(),
        "writer": writer,
        "revision": revision,
    }


def add_deliverable(paths: RunPaths, key: str, path: str, sha256: str, writer: str) -> dict[str, Any]:
    """List a page this run wrote. A page completing the expected set of a `pending` run makes it final."""
    if key not in DELIVERABLE_KEYS:
        raise ValueError(f"unknown deliverable {key!r}")

    def fn(status: dict[str, Any]) -> None:
        deliverables = dict(status.get("deliverables") or {})
        deliverables[key] = deliverable_entry(path, sha256, writer, int(status.get("revision") or 0))
        status["deliverables"] = deliverables
        if status.get("status") == "complete" and status.get("deliverables_status") == "pending":
            status["deliverables_status"] = deliverables_status_for(status)

    return update(paths, fn)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def complete_after_coaching(paths: RunPaths, report_md: str, report_json: str | None) -> dict[str, Any]:
    """Coaching landed: list the reports with their post-insert hashes, and complete unless a gate is open.

    A read-modify-write, so pages a skill wrote before its coaching stay listed.
    """

    def fn(status: dict[str, Any]) -> None:
        open_now = open_gate_ids(paths)
        revision = int(status.get("revision") or 0)
        deliverables = dict(status.get("deliverables") or {})
        deliverables["report_md"] = deliverable_entry(report_md, file_sha256(report_md), "insert_coaching.py", revision)
        if report_json and os.path.isfile(report_json):
            deliverables["report_json"] = deliverable_entry(
                report_json, file_sha256(report_json), "insert_coaching.py", revision
            )
        status["deliverables"] = deliverables
        status["coaching"] = "inserted"
        if status.get("status") in FINAL_STATUSES or open_now:
            return
        mark_complete(status)

    return update(paths, fn)


def coaching_blocked(paths: RunPaths) -> dict[str, Any]:
    def fn(status: dict[str, Any]) -> None:
        if status.get("status") in FINAL_STATUSES:
            return
        status["coaching"] = "blocked"
        status["last_error_code"] = "COACHING_BLOCKED"
        if status.get("status") == "running":
            status["message"] = MESSAGES["COACHING_BLOCKED"]

    return update(paths, fn)
