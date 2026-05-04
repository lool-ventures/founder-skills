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
    # NOTE: gate_state.json is NOT cleanable. Re-invocation after a gate
    # answer depends on the file persisting across the second Step-0 call.
    # Stale-state risk is handled by the agent comparing
    # gate_state.json's metadata.run_id against the current RUN_ID before
    # treating it as a resume signal — see SKILL.md Gate section.
}


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

    if args.clean:
        for name in _CLEANABLE_NAMES:
            path = os.path.join(review_dir, name)
            if os.path.isfile(path):
                os.remove(path)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    out = {
        "review_dir": review_dir,
        "run_id": run_id,
        "slug": args.slug,
        "artifacts_root": artifacts_root,
    }
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(out, indent=indent) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
