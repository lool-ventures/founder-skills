#!/usr/bin/env python3
"""Answer a cowork-harness in-band gate by INDEX, using the exact question text.

Why this exists: `cowork-harness answer --answer "<q>=<label>"` requires the question
key to match EXACTLY. A truncated or prefix key is accepted by the CLI, echoed back,
and reports success — then the run dies with `unanswered question` and the spend is
gone. That happened once and cost a full cap-table run.

This reads the pending request, so the keys are always exact, and lets you pick
answers positionally.

    python3 tools/landing-capture/answer_gate.py <decider-dir>              # show pending
    python3 tools/landing-capture/answer_gate.py <decider-dir> 1 2 1        # answer by option index
    python3 tools/landing-capture/answer_gate.py <decider-dir> --labels A B # answer by label
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys


def latest_request(decider_dir: str) -> tuple[str, dict]:
    reqs = sorted(glob.glob(os.path.join(decider_dir, "req-*.json")))
    if not reqs:
        sys.exit(f"no pending request in {decider_dir}")
    path = reqs[-1]
    if os.path.exists(path.replace("req-", "resp-")):
        print(f"note: {os.path.basename(path)} already has a response", file=sys.stderr)
    return path, json.load(open(path))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    decider_dir = sys.argv[1]
    rest = sys.argv[2:]
    path, req = latest_request(decider_dir)
    gate_n = int(os.path.basename(path).split("-")[1].split(".")[0])
    questions = req.get("questions", [])

    if not rest:
        print(f"gate {gate_n}: {len(questions)} question(s)")
        for qi, q in enumerate(questions, 1):
            print(f"\n[{qi}] {q.get('question')}")
            for oi, o in enumerate(q.get("options", []), 1):
                print(f"    {oi}. {o.get('label')}")
        return

    by_label = rest[0] == "--labels"
    picks = rest[1:] if by_label else rest
    if len(picks) != len(questions):
        sys.exit(f"expected {len(questions)} answers, got {len(picks)}")

    args = ["cowork-harness", "answer", decider_dir, "--gate", str(gate_n)]
    for q, pick in zip(questions, picks, strict=True):
        if by_label:
            label = pick
        else:
            opts = q.get("options", [])
            idx = int(pick)
            if not 1 <= idx <= len(opts):
                sys.exit(f"index {idx} out of range for: {q.get('question')[:60]}")
            label = opts[idx - 1]["label"]
        # exact question text, straight from the request — never hand-typed
        args += ["--answer", f"{q['question']}={label}"]

    print(subprocess.run(args, capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
