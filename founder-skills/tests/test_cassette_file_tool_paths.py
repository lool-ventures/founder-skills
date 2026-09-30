"""No recorded host-loop run may hand a file tool a relative or a `/sessions/...` path.

On Cowork host-loop the file tools run outside the VM and outside the outputs dir: a relative
Read/Write/Edit is refused, and a `/sessions/...` path is the VM shell's name for a file the file tools
cannot open. Every SKILL.md proves the file-tool path of outputs at Step 0 so that no dispatch hands a
sub-agent either form. This walks every committed cassette's events -- main thread and sub-agents, whose
tool calls ride inside JSON-encoded event strings -- and counts the file-tool calls that did.

A RATCHET until the next re-record. The cassettes recorded before the Step 0 proof existed carry the
calls listed in `_KNOWN_BEFORE_RERECORD`; the count per cassette may only go DOWN. After a re-record it
must be zero, and the dict is emptied. A cassette recorded at a VM-loop tier (`container`) is exempt:
there the file tools take the shell's own `/sessions/...` paths.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

_CASSETTES = Path(__file__).resolve().parents[2] / "cowork-tests" / "cassettes"
_FILE_TOOLS = {"Read": "file_path", "Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path"}
_FILE_TOOLS["NotebookEdit"] = "notebook_path"
_VM_LOOP_TIERS = {"container", "microvm"}

# Calls recorded before the Step 0 proof, per cassette. May only shrink; empty after the re-record.
# Every committed host-loop cassette is now recorded with the proof in place and is at 0.
_KNOWN_BEFORE_RERECORD: dict[str, int] = {}


def _offending(path: Any) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("[REDACTED:"):
        # A redacted host path: the redaction replaced an absolute /Users|/home|/root|/private... prefix.
        return False
    return not path.startswith("/") or path.startswith("/sessions/")


def offending_calls(events: Any) -> set[tuple[str, str]]:
    """(tool, path) for every file-tool call whose path is relative or a /sessions/ path. A set, because
    the stream carries each tool_use twice (the streamed block and the assistant message)."""
    found: set[tuple[str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node[:1] in "{[":
                with contextlib.suppress(ValueError):
                    walk(json.loads(node))
            return
        if isinstance(node, dict):
            if node.get("type") == "tool_use" and node.get("name") in _FILE_TOOLS:
                path = (node.get("input") or {}).get(_FILE_TOOLS[node["name"]])
                if isinstance(path, str) and _offending(path):
                    found.add((str(node["name"]), path))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(events)
    return found


def _host_loop_cassettes() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted(_CASSETTES.glob("*.cassette.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("scenario") or {}).get("fidelity") in _VM_LOOP_TIERS:
            continue
        out[path.name.removesuffix(".cassette.json")] = data
    return out


def test_the_walker_finds_what_it_is_for() -> None:
    """Positive control: nested JSON-encoded events, both offending forms, and the forms that are fine."""
    tool_uses = [
        {"type": "tool_use", "name": "Write", "input": {"file_path": "artifacts/x/handoff/r/a_output.json"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/sessions/abc/mnt/outputs/x.json"}},
        {"type": "tool_use", "name": "NotebookEdit", "input": {"notebook_path": "nb.ipynb"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/Users/u/s/outputs/x.json"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "[REDACTED:local-path:abc]/mnt/outputs/y"}},
        {"type": "tool_use", "name": "Grep", "input": {"path": "relative/is/fine/for/grep"}},
    ]
    events = [json.dumps({"message": {"content": tool_uses}})]
    assert offending_calls(events) == {
        ("Write", "artifacts/x/handoff/r/a_output.json"),
        ("Read", "/sessions/abc/mnt/outputs/x.json"),
        ("NotebookEdit", "nb.ipynb"),
    }


def test_the_corpus_is_there_and_the_walk_engaged() -> None:
    cassettes = _host_loop_cassettes()
    assert len(cassettes) >= 5, sorted(cassettes)
    # The walk reaches sub-agent tool calls: the known offenders are all sub-agent hand-offs.
    assert sum(len(offending_calls(c.get("events", []))) for c in cassettes.values()) > 0 or not _KNOWN_BEFORE_RERECORD


def test_no_host_loop_recording_hands_a_file_tool_a_relative_or_vm_path() -> None:
    counts = {name: len(offending_calls(data.get("events", []))) for name, data in _host_loop_cassettes().items()}
    grew = {name: n for name, n in counts.items() if n > _KNOWN_BEFORE_RERECORD.get(name, 0)}
    assert not grew, (
        f"file-tool calls with a relative or /sessions/ path, beyond the pre-proof baseline: {grew}. "
        "The file tools refuse these at host-loop; the Step 0 proof exists so no dispatch hands one out."
    )
    stale = {name: n for name, n in _KNOWN_BEFORE_RERECORD.items() if counts.get(name, 0) < n}
    assert not stale, f"ratchet _KNOWN_BEFORE_RERECORD down to the current counts: {stale} -> {counts}"
