#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
r"""Resolve REVIEW_DIR for a deck review run.

Replaces the bash path heuristic in SKILL.md Step 0. Output is a JSON
object the agent can source into shell variables:

    eval "$(python setup_run.py --slug acme-corp --artifacts-root ./artifacts \
        | jq -r '@sh "REVIEW_DIR=\(.review_dir) RUN_ID=\(.run_id)"')"

Or simply parsed by a sub-agent that calls this once and uses the values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_CLEANABLE_NAMES = {
    "deck_inventory.json",
    "stage_profile.json",
    "slide_reviews.json",
    "checklist.json",
    "report.json",
    "report.md",
    "report.html",
    # gate_state.json is handled separately: it must persist across a gate
    # round-trip (same run_id) but be deleted when --clean runs for a fresh
    # run (resume is false). See _read_gate_state / the --clean block below.
}
_GATE_STATE_NAME = "gate_state.json"


def _read_gate_state(review_dir: str) -> tuple[str, str]:
    """Return (answer, run_id) from gate_state.json, ("", "") if absent/unreadable."""
    path = os.path.join(review_dir, _GATE_STATE_NAME)
    if not os.path.isfile(path):
        return "", ""
    try:
        with open(path, encoding="utf-8") as f:
            gate = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "", ""
    if not isinstance(gate, dict):
        return "", ""
    answer = gate.get("answer") or ""
    run_id = ""
    meta = gate.get("metadata")
    if isinstance(meta, dict):
        run_id = meta.get("run_id") or ""
    return str(answer), str(run_id)


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve REVIEW_DIR and run_id.")
    p.add_argument("--artifacts-root", required=True, help="Path to artifacts root directory")
    p.add_argument("--slug", required=True, help="Company slug")
    p.add_argument("--run-id", help="Override run_id (default: ISO timestamp)")
    p.add_argument("--clean", action="store_true", help="Remove stale review artifacts before starting")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    artifacts_root = os.path.abspath(args.artifacts_root)
    review_dir = os.path.join(artifacts_root, f"deck-review-{args.slug}")
    os.makedirs(review_dir, exist_ok=True)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Resume detection lives here (not in SKILL.md bash) so it cannot drift.
    # A resume is ONLY valid when gate_state.json carries an answer AND its
    # run_id matches the current run_id. An answered gate from a *prior*
    # completed run (different run_id) is stale and must NOT trigger a resume —
    # otherwise a fresh review of the same company reuses the old run's
    # artifacts.
    #
    # Preservation contract: when resume is true, artifacts from _CLEANABLE_NAMES
    # are same-run checkpoints (Steps 2-3 already ran for this run_id).  --clean
    # must NOT delete them — skipping re-runs avoids redundant LLM calls on gate
    # round-trips.  compose_report.py's run_id parity check is the safety net
    # against stale content from a different run.  On a fresh (non-resume) run
    # _CLEANABLE_NAMES are deleted unconditionally so no prior run's artifacts
    # pollute the new run.
    gate_answer, gate_run_id = _read_gate_state(review_dir)
    resume = bool(gate_answer) and gate_run_id == run_id

    if args.clean and not resume:
        # Fresh run: remove all cleanable pipeline artifacts so no stale
        # content from a prior run contaminates this invocation.
        for name in _CLEANABLE_NAMES:
            path = os.path.join(review_dir, name)
            if os.path.isfile(path):
                os.remove(path)
        # Also remove a stale answered gate_state.json so it cannot be
        # misread as a resume signal on a later invocation.
        gate_path = os.path.join(review_dir, _GATE_STATE_NAME)
        if os.path.isfile(gate_path):
            os.remove(gate_path)
            gate_answer, gate_run_id, resume = "", "", False
    # resume is true: _CLEANABLE_NAMES artifacts are same-run checkpoints —
    # leave them intact.  gate_state.json is also preserved (it holds the
    # founder's answer that enabled resume detection).

    out = {
        "review_dir": review_dir,
        "run_id": run_id,
        "slug": args.slug,
        "artifacts_root": artifacts_root,
        "gate_answer": gate_answer,
        "gate_run_id": gate_run_id,
        "resume": resume,
    }
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(out, indent=indent) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
