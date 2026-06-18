#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
r"""Deterministically resolve the canonical artifacts root.

WHY THIS EXISTS: a SKILL.md ```bash``` block is guidance the agent paraphrases into its own Bash
calls — it is not executed verbatim. A computed path like
`ARTIFACTS_ROOT="$(ls -d "$(pwd)"/mnt/*/ | head -1)artifacts"` is exactly the kind of clever shell the
model shortcuts: it keeps the intent ("under outputs/") but drops the detection, landing `outputs/` in
one run and `outputs/artifacts/` in another. That non-determinism breaks cross-skill `find_artifact.py`
resolution and any path-based test assertion. Putting the logic in a script the agent invokes as one
opaque command removes the surface to paraphrase: the agent runs this and uses the printed value.

CANONICAL RULE: artifacts live under the **promoted outputs dir** in Cowork (so they're user-visible
AND resolvable by find_artifact.py), nested in an `artifacts/` subdir so the outputs/ root stays clean
for user-facing deliverables. In the CLI (no outputs/ dir) they live at `./artifacts`.

Resolution order (first existing wins — a FIXED order, never a first-subdir guess):
  1. $COWORK_ARTIFACTS_ROOT (explicit override / tests)
  2. <cwd>/outputs/artifacts            (Cowork: pwd is the session mnt root)
  3. <cwd>/mnt/outputs/artifacts        (Cowork: pwd is one level up)
  4. first <cwd>/sessions/*/mnt/outputs/artifacts   (Cowork: pwd above the session)
  5. <cwd>/artifacts                    (CLI default; matches find_artifact.py's default)

Prints the absolute artifacts root on stdout (one line). With --json, prints
{"artifacts_root": ...}. Creates the dir unless --no-create.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def resolve_artifacts_root(cwd: str, env: dict[str, str]) -> str:
    override = env.get("COWORK_ARTIFACTS_ROOT")
    if override:
        return os.path.abspath(override)

    # Cowork: pin under the promoted outputs/ dir, nested in artifacts/.
    if os.path.isdir(os.path.join(cwd, "outputs")):
        return os.path.join(cwd, "outputs", "artifacts")
    if os.path.isdir(os.path.join(cwd, "mnt", "outputs")):
        return os.path.join(cwd, "mnt", "outputs", "artifacts")
    # pwd sits above the session dir: take the first session deterministically (sorted).
    sessions = sorted(glob.glob(os.path.join(cwd, "sessions", "*", "mnt", "outputs")))
    if sessions:
        return os.path.join(sessions[0], "artifacts")

    # CLI: ./artifacts (matches find_artifact.py's default artifacts root).
    return os.path.join(cwd, "artifacts")


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve the canonical artifacts root deterministically.")
    p.add_argument("--json", action="store_true", help='Emit {"artifacts_root": ...} instead of a bare path')
    p.add_argument("--no-create", action="store_true", help="Do not mkdir the resolved root")
    args = p.parse_args()

    root = resolve_artifacts_root(os.getcwd(), dict(os.environ))
    if not args.no_create:
        os.makedirs(root, exist_ok=True)

    if args.json:
        sys.stdout.write(json.dumps({"artifacts_root": root}) + "\n")
    else:
        sys.stdout.write(root + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
