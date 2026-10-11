"""The comparison redo's record: one sanctioned second build of one sizing approach, once per run.

WHY. On a "both" run `market_sizing.py` flags a gap of more than 30% between the two builds' TAM, SAM or
SOM (`comparison.warning` / `sam_warning` / `som_warning`). The only way the main thread's reading of
that gap could reach a sizing sub-agent was a changed prompt, and the dispatch hook rewrites any prompt
that is not the generator's output back to the printed one: the repair's reason was dropped and the build
was redone from identical instructions, with nothing recording that it happened. So the generator prints
the redo (`dispatch_prompt.py <context> --redo comparison [--suspect <input>]...`), writes every word of
it, and records it here; `market_sizing.py` fills in what the redo produced; compose discloses it.

THE RECORD. `<analysis-dir>/sizing_redo.json`, written by the generator at the first redo print for the
run, never by the model. With a gate ledger the same record is also written into the ledger under
`sizing_redo`, inside a ledger transaction (under the run lock), and every reader takes the ledger's copy
first: deleting the file neither erases the disclosure nor reopens the budget. It holds the build, the
levels the producer flagged, the inputs named as suspect, the gap before the redo (`before`), the
hand-off the redo writes (its shell path and the agent's OUTPUT_PATH), the first hand-off's sha and
references, the research names recorded when the first builds were printed and when the redo was, and
`after`, which `market_sizing.py` writes ONCE: on its first successful run over a consumed redo whose
references it actually used. Compose prints the gap after the redo only from there, so Step 6d's later
replay or round-2 re-dispatch cannot move it.

CONSUMED, one predicate (`consumed`), called by the generator (SPENT) and compose (NOT_RUN): the gate
record beside the redo's hand-off carries `gated_at` later than the print, the hand-off file's mtime is
later than the print, and the gate record's sha256 is the file's. All three, no fallback: check_handoff.py
rewrites the gate record on every pass, so a re-gate of the untouched first file after the print has a
late `gated_at` and an early mtime; and "the same references again" is an allowed outcome, so the sha
alone says nothing. A gate record written before `gated_at` existed reads as not consumed. Settled from
round 1's hand-off only: Step 6d's round 2 writes under `r2/`, which the record does not name.

RESIDUALS, stated:
- The budget limits PRINTS, not dispatches. The identical redo prompt can be dispatched again and again;
  the hook passes each one, since each is the printed prompt. The e2e lane counts dispatches; a run has no
  such check.
- With no ledger the file is the only copy: deleting `sizing_redo.json` removes the disclosure and
  reopens the budget, and a fresh run id starts a fresh budget (the record is per run).
- The first hand-off is not moved aside. A redo sub-agent that writes nothing leaves the first file in
  place and check_handoff.py passes it; the mtime conjunct reads that as not consumed (SIZING_REDO_NOT_RUN).
- The redo sub-agent may open its own OUTPUT_PATH (the file tool reads an existing file before it
  overwrites it); that file is this build's own first references, never the other build's figures.
- Research recorded after the first builds were printed is disclosed when the redo uses it; a snapshot
  that is missing (deleted, or a run printed before this existed) discloses nothing.
- A re-read, after the redo print, of an earlier redirected plain print is not detected here.

Standalone: stdlib, plus the shared ledger modules through `_run_ref` when the run has a ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _run_ref  # noqa: E402

RECORD_NAME = "sizing_redo.json"
LEDGER_KEY = "sizing_redo"
# What the research held when the first sizing prompts were printed (in the run's hand-off dir).
SNAPSHOT_NAME = "sizing_research_at_print.json"
GATE_SUFFIX = ".gate.json"  # _handoff_audit.GATE_SUFFIX

# context -> (build, hand-off file, the build's own input names)
BUILDS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "top_down_methodology": ("top_down", "top_down_output.json", ("industry_total", "segment_pct", "share_pct")),
    "bottom_up_methodology": (
        "bottom_up",
        "bottom_up_output.json",
        ("customer_count", "arpu", "serviceable_pct", "target_pct"),
    ),
}
LEVELS = (("tam", "warning"), ("sam", "sam_warning"), ("som", "som_warning"))


def _read(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path: str, data: Any) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def now() -> tuple[str, float]:
    """(ISO-8601 UTC with microseconds, the same instant as epoch seconds)."""
    t = time.time()
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), t


def _epoch(iso: Any) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def run_id_of(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("metadata")
    rid = meta.get("run_id") if isinstance(meta, dict) else None
    rid = rid if isinstance(rid, str) and rid else data.get("run_id")
    return rid if isinstance(rid, str) and rid else None


def research_names(validation: Any) -> list[str]:
    """The names of the figures the research record holds."""
    items = validation.get("assumptions") if isinstance(validation, dict) else None
    return sorted({str(a["name"]) for a in items or [] if isinstance(a, dict) and isinstance(a.get("name"), str)})


def referenced_names(refs: Any) -> set[str]:
    """Every research figure a set of references names, derived factors included."""
    out: set[str] = set()
    if isinstance(refs, dict):
        name = refs.get("assumption")
        if isinstance(name, str):
            out.add(name)
        for value in refs.values():
            out |= referenced_names(value)
    elif isinstance(refs, list):
        for value in refs:
            out |= referenced_names(value)
    return out


def handoff_refs(path: str, names: tuple[str, ...]) -> dict[str, Any] | None:
    data = _read(path)
    if not isinstance(data, dict):
        return None
    return {n: data[n] for n in names if n in data}


def file_sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def gaps(comparison: Any) -> dict[str, dict[str, Any]]:
    """Per compared level: the delta the producer computed and the two builds' figures."""
    comparison = comparison if isinstance(comparison, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for level, _warn in LEVELS:
        if f"{level}_delta_pct" in comparison:
            out[level] = {
                "delta_pct": comparison.get(f"{level}_delta_pct"),
                "top_down": comparison.get(f"top_down_{level}"),
                "bottom_up": comparison.get(f"bottom_up_{level}"),
            }
    return out


def flagged_levels(comparison: Any) -> list[str]:
    """The levels the producer itself flagged. Its verdict is read; the threshold is never recomputed."""
    comparison = comparison if isinstance(comparison, dict) else {}
    return [level for level, key in LEVELS if comparison.get(key)]


# --- the record, file and ledger ------------------------------------------------------------------------


def _ledger(analysis_dir: str, run_id: str) -> Any:
    """(gates, paths) or None with no ledger; raises `_run_ref.LedgerUnavailable` on a ref it cannot reach."""
    return _run_ref.open_ledger(os.path.abspath(analysis_dir), run_id)


def load(analysis_dir: str, run_id: str | None) -> dict[str, Any] | None:
    """This run's record: the ledger's copy first, the file second; another run's is never returned."""
    if not run_id:
        return None
    try:
        ledger = _ledger(analysis_dir, run_id)
    except Exception:  # noqa: BLE001 -- an unreachable ledger: the file is what is left to read
        ledger = None
    if ledger is not None:
        gates, paths = ledger
        try:
            held = gates.load_ledger(paths).get(LEDGER_KEY)
        except Exception:  # noqa: BLE001
            held = None
        if isinstance(held, dict) and held.get("run_id") == run_id:
            return held
    data = _read(os.path.join(analysis_dir, RECORD_NAME))
    if isinstance(data, dict) and data.get("run_id") == run_id:
        return data
    return None


def save(analysis_dir: str, run_id: str, record: dict[str, Any]) -> None:
    """Write the record: into the ledger first (one transaction, under the run lock), then the file."""
    ledger = _ledger(analysis_dir, run_id)
    if ledger is not None:
        gates, paths = ledger

        def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
            led[LEDGER_KEY] = record
            return {}

        gates.transact(paths, fn)
    _write(os.path.join(analysis_dir, RECORD_NAME), record)


def run_finished(analysis_dir: str, run_id: str) -> bool:
    """With a ledger, whether the run's status reads `complete`."""
    if not _run_ref.has_ledger(os.path.abspath(analysis_dir), run_id):
        return False
    try:
        rs = _run_ref.load_shared("_run_status")
        paths = rs.locate_from_run_dir(os.path.abspath(analysis_dir), run_id)
        status = rs.load_status(paths) or {}
    except Exception:  # noqa: BLE001 -- the generator's own gate check reports an unreachable ledger
        return False
    return status.get("status") == "complete"


def write_snapshot(handoff_dir: str, run_id: str, validation_path: str) -> None:
    """At the first plain print of a sizing prompt: the research the first builds could use. Kept once per
    run; never written into a hand-off dir that does not exist yet."""
    if not os.path.isdir(handoff_dir):
        return
    path = os.path.join(handoff_dir, SNAPSHOT_NAME)
    if _read(path) is not None and run_id_of(_read(path)) == run_id:
        return
    try:
        _write(path, {"run_id": run_id, "names": research_names(_read(validation_path))})
    except OSError as exc:
        print(f"warning: the research snapshot was not written: {exc}", file=sys.stderr)


def read_snapshot(handoff_dir: str, run_id: str) -> list[str] | None:
    data = _read(os.path.join(handoff_dir, SNAPSHOT_NAME))
    if run_id_of(data) != run_id or not isinstance(data.get("names"), list):
        return None
    return [str(n) for n in data["names"]]


# --- the one predicate ----------------------------------------------------------------------------------


def consumed(record: dict[str, Any]) -> bool:
    """The redo's hand-off was written and gated after the print, and is still what was gated."""
    path = record.get("handoff_file")
    printed = _epoch(record.get("printed_at"))
    if not isinstance(path, str) or printed is None:
        return False
    gate = _read(path + GATE_SUFFIX)
    if not isinstance(gate, dict):
        return False
    gated = _epoch(gate.get("gated_at"))
    if gated is None or not gated > printed:
        return False
    try:
        if not os.path.getmtime(path) > printed:
            return False
    except OSError:
        return False
    sha = gate.get("sha256")
    return isinstance(sha, str) and sha == file_sha256(path)


def build_names(record: dict[str, Any]) -> tuple[str, ...]:
    for build, _file, names in BUILDS.values():
        if build == record.get("build"):
            return names
    return ()


def outcome(record: dict[str, Any]) -> str:
    """`changed` / `same_inputs` when the redo was consumed and the sizing used it, else `not_run`."""
    after = record.get("after")
    if not consumed(record) or not isinstance(after, dict):
        return "not_run"
    names = build_names(record)
    now_refs = handoff_refs(str(record.get("handoff_file")), names)
    if now_refs is None or after.get("input_refs") != now_refs:
        return "not_run"
    return "same_inputs" if after.get("input_refs") == record.get("first_input_refs") else "changed"


def new_research(record: dict[str, Any]) -> list[str]:
    """Figures the redo used that the research did not hold when the first builds were printed."""
    snapshot = record.get("research_at_first_print")
    after = record.get("after")
    if not isinstance(snapshot, list) or not isinstance(after, dict):
        return []
    return sorted(referenced_names(after.get("input_refs")) - set(snapshot))


def fill_after(analysis_dir: str, run_id: str | None, result: dict[str, Any]) -> None:
    """market_sizing.py, after a successful run: the first sizing over a consumed redo whose references it
    used records the gap it produced. Written once; a failure is one stderr line and never stops the sizing."""
    try:
        record = load(analysis_dir, run_id)
        if record is None or record.get("after") is not None or not run_id:
            return
        comparison = result.get("comparison")
        refs = result.get("input_refs")
        if not isinstance(comparison, dict) or not isinstance(refs, dict) or not consumed(record):
            return
        names = build_names(record)
        used = {n: refs[n] for n in names if n in refs}
        if used != handoff_refs(str(record.get("handoff_file")), names):
            return
        at, _ = now()
        save(analysis_dir, run_id, {**record, "after": {"gaps": gaps(comparison), "input_refs": used, "at": at}})
    except Exception as exc:  # noqa: BLE001 -- the sizing is written whatever happens here
        print(f"warning: the comparison redo's result was not recorded: {exc}", file=sys.stderr)
