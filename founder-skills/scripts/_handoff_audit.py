"""Gate records for sub-agent hand-off files, and the check that a run's steps went through the gate.

`check_handoff.py` writes `<hand-off file>.gate.json` beside every hand-off file it passes (exit 0),
recording the file's sha256. A step with no record got to its producer some other way: it took the
message-channel fallback (staged outside the hand-off dir), or the gate was simply skipped and the file
piped straight to the producer. Both leave no record, and the check cannot tell them apart -- so the
founder-facing text states only what is measured: the step was not put through the check.
A compose script asks `bypassed()` which of the steps its artifacts came from have no gated hand-off, and
discloses them to the founder (`HANDOFF_BYPASSED`).

The evidence is the ABSENCE of a record, deliberately. Keying on something the fallback path writes
would depend on the model following the fallback prose; an absent record survives the prose being
skipped. The hand-off dir sits under the outputs mount. Newer hosts allow deletes there (we never delete
by rule), so a record CAN be removed. For a step the artifacts identify, that only adds the warning:
`gate_ok` reads a missing record (or a missing dir) as ungated, and no caller treats a missing dir as
"not a run". A run that dispatched no sub-agent has no artifact that requires a record. RESIDUALS:
deleting a canonical artifact removes its step's requirement; and a step required only because its
hand-off file is in the dir -- cap-table's per-document extractions, competitive-positioning's
enrichment re-dispatch -- is no longer required once the dir is deleted, so deleting it removes that
warning. Closing those needs each producer to record which hand-off it consumed. The only way to
manufacture a record is to hand-write a sub-agent's JSON into the hand-off path and gate it, which is
the main thread re-emitting a payload -- a named fabrication failure, not a paraphrase. The sha also
catches a hand-off file rewritten after it was gated.

WHAT A PASS DOES NOT PROVE: that the producer consumed the gated file. A step that was gated once and
then degraded on a re-dispatch within the same run still has a matching record, and passes. Proving
consumption needs each producer to stamp the sha of its own input and compose to match that against the
records -- the upgrade path, not built.

Standalone: stdlib only, imported by path from `check_handoff.py` (same dir) and from each skill's
`compose_report.py` (`parents[2]/scripts`).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence

GATE_SUFFIX = ".gate.json"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_gate_record(path: str, fmt: str) -> None:
    """Record that `path` passed the gate. Raises OSError if the record cannot be written."""
    with open(path + GATE_SUFFIX, "w", encoding="utf-8") as f:
        json.dump({"sha256": file_sha256(path), "format": fmt}, f)
        f.write("\n")


def gate_ok(path: str) -> bool:
    """True iff `path` exists, has a gate record, and still has the sha the record holds."""
    try:
        with open(path + GATE_SUFFIX, encoding="utf-8") as f:
            record = json.load(f)
        return isinstance(record, dict) and record.get("sha256") == file_sha256(path)
    except (OSError, ValueError):
        return False


def bypassed(run_dir: str, requirements: Sequence[tuple[str, Sequence[str]]]) -> list[str]:
    """Return the labels of the requirements with no gated hand-off.

    `requirements` pairs a founder-neutral label with the candidate hand-off paths, relative to
    `run_dir` (the run's `handoff/<run_id>` dir); any one gated candidate satisfies it. The caller builds
    the list from the artifacts actually present, so a step that never ran is never required.
    """
    return [
        label for label, candidates in requirements if not any(gate_ok(os.path.join(run_dir, c)) for c in candidates)
    ]


# The founder-facing wording, one copy for the fleet. Names steps, never a path or a file.
WARNING_CODE = "HANDOFF_BYPASSED"
WARNING_LABEL = "Some Steps Were Not Checked"
VERDICT_SENTENCE = (
    "Some steps were not put through the check that confirms each step's saved output, so the record "
    "of those steps is incomplete; that alone does not mean the results are wrong."
)


def founder_message(labels: Sequence[str]) -> str:
    """The warning message naming the steps that were not put through the gate."""
    steps = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return (
        f"The results of {steps} were not put through the check that confirms each step's saved "
        "output, so the record of those steps is incomplete. That alone does not mean the results are wrong."
    )
