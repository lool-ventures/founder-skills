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
for user-facing deliverables. In the CLI (no session tree) they live at `./artifacts`.

TOPOLOGY IS DETECTED FROM THE cwd STRING SHAPE, NOT FROM THE FILESYSTEM. This resolver runs in the
main-thread workspace shell. On Cowork host-loop that shell's cwd is somewhere inside the session tree
`/sessions/<id>/mnt/<first-connected-folder-else-outputs>` (Ch35/L122 "first-folder-else-outputs") —
NOT necessarily the outputs mount. Probing the filesystem for a sibling `outputs/` mis-anchors: if a
connected folder contains its own `outputs/`, an `isdir(cwd/outputs)` branch would point artifacts
INSIDE the user's real project while a sub-agent's host-native file tools (whose cwd IS the session
outputs dir) resolve the returned relative root against the outputs mount — write and gate then address
different physical dirs. So we key on the session ROOT extracted from the cwd shape and anchor
unconditionally on `<session>/mnt/outputs` (the bind-mount identity of the sub-agent's host cwd),
regardless of where in the tree the shell cwd sits.

Resolution (first match wins; pure string logic, no FS probe except the CLI mkdir in main()):
  1. $COWORK_ARTIFACTS_ROOT (explicit override / tests) -> (abs, abs)
  2. Cowork session tree, shell inside the mount: `^/sessions/<id>/mnt(/...)?`
                                                           -> (<session>/mnt/outputs/artifacts, "artifacts")
  3. Cowork session tree, shell AT the session root: `^/sessions/<id>$`
                                                           -> (cwd/mnt/outputs/artifacts, "artifacts")
  4. CLI default:                                          -> (cwd/artifacts, cwd/artifacts)
  $COWORK_AGENT_ARTIFACTS_ROOT overrides ONLY the agent-namespace half (see below).

Prints the absolute artifacts root on stdout (one line). With --json, prints
{"artifacts_root": ..., "agent_artifacts_root": ...}. Creates the dir unless --no-create.

AGENT NAMESPACE (branch C hand-off): in Cowork a sub-agent's native file tools are rooted at the
outputs mount itself (its cwd IS the outputs dir), so the same file has two addresses — the main
thread's absolute path under the outputs root, and the agent's path RELATIVE to its cwd. On the CLI both
sides share one filesystem, so both roots are the same absolute path. Print it with --agent. Dispatch
prompts build OUTPUT_PATH (and under-outputs read paths) from the agent namespace; shell-side gates use
the absolute namespace.

**THE SHELL'S cwd CANNOT TELL YOU THE SUB-AGENT'S cwd.** Branches 2 and 3 differ only in how they LOCATE
the session root (from the `/mnt` match, or from the cwd itself) — which the ABSOLUTE root depends on.
They must NOT differ in the agent-namespace root, and a previous version's branch 3 got this wrong: it
returned `"mnt/outputs/artifacts"` on the premise that a shell sitting at `/sessions/<id>` implies the
sub-agent also sits there. Those are independent facts. On Cowork host-loop the sub-agent's file tools run
host-native with cwd = the session outputs dir while the main thread's shell runs in the VM sidecar, and
that shell can sit at the session root — so the premise produced `<outputs>/mnt/outputs/artifacts/...`, a
DOUBLED prefix, silently, for every blind-writing sub-agent. (See `references/skill-execution-model.md`
"a sub-agent's file tools run host-native (cwd IS the session outputs dir)", which this module's own
opening docstring already asserted.) Host-loop is the production topology, so `"artifacts"` is correct for
any real Cowork session tree.

A genuine VM-loop topology (the agent loop itself inside the VM, cwd `/sessions/<id>`) does exist as a
test tier, and there `"artifacts"` would resolve to `/sessions/<id>/artifacts` — sandbox scratch OUTSIDE
outputs. That case is served by the explicit `$COWORK_AGENT_ARTIFACTS_ROOT` override rather than by
guessing from a cwd shape, because nothing in the shell's environment distinguishes the two topologies.
Set it to `mnt/outputs/artifacts` when running a hand-off-bearing scenario at a VM-loop tier.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# A Cowork session tree, anchored at the START of the path so an ordinary CLI project that merely
# CONTAINS a "sessions/<x>/mnt" segment (e.g. /home/u/sessions/y/mnt/z) is NOT mistaken for one.
_SESSION_TREE = re.compile(r"^(/sessions/[^/]+)/mnt(?:/|$)")
_SESSION_ROOT = re.compile(r"^/sessions/[^/]+$")

# The sub-agent-relative artifacts root on any Cowork session tree. The sub-agent's file tools are rooted
# at the session outputs dir, so this is correct whether the main thread's shell sits inside the mount or
# at the session root — the shell's cwd is a different process in a different namespace and says nothing
# about the agent's. See the module docstring's AGENT NAMESPACE section.
_AGENT_ROOT_COWORK = "artifacts"


def _agent_override(env: dict[str, str], default: str) -> str:
    """Honor an explicit agent-namespace override, else return `default`.

    Exists so a genuine VM-loop tier (agent loop inside the VM, cwd `/sessions/<id>`, where a bare
    `artifacts` would land in sandbox scratch outside outputs) can be served by a stated fact instead of
    a guess. Nothing in the shell's environment distinguishes that topology from host-loop, so it must be
    declared, not inferred.
    """
    return env.get("COWORK_AGENT_ARTIFACTS_ROOT") or default


def resolve_roots(cwd: str, env: dict[str, str]) -> tuple[str, str]:
    """Return (artifacts_root, agent_artifacts_root).

    agent_artifacts_root is the artifacts root as a SUB-AGENT's native file tools address it: relative
    to the sub-agent's cwd, which on any Cowork session tree is the session OUTPUTS dir (host-loop, the
    production topology) — never inferred from the main thread's shell cwd, which is a different process
    in a different namespace. Identical to the absolute root on the shared-filesystem CLI. See the module
    docstring's AGENT NAMESPACE section for why this must not branch on the shell's cwd shape, and for
    the `$COWORK_AGENT_ARTIFACTS_ROOT` escape hatch that serves a real VM-loop tier.
    """
    override = env.get("COWORK_ARTIFACTS_ROOT")
    if override:
        root = os.path.abspath(override)
        return root, _agent_override(env, root)

    # Cowork session tree, shell somewhere inside /sessions/<id>/mnt/...; anchor on the session's outputs
    # mount regardless of where in the tree the shell sits (see module docstring).
    m = _SESSION_TREE.match(cwd)
    if m:
        session_root = m.group(1)  # /sessions/<id>
        return (
            os.path.join(session_root, "mnt", "outputs", "artifacts"),
            _agent_override(env, _AGENT_ROOT_COWORK),
        )

    # Cowork session tree, shell AT the session root /sessions/<id>. Only the ABSOLUTE root differs from
    # the branch above (the session root is the cwd itself); the agent-namespace root is the SAME, because
    # the sub-agent's cwd is the outputs dir either way. Returning "mnt/outputs/artifacts" here — inferring
    # the agent's cwd from the shell's — is the defect that produced a doubled `mnt/outputs/` prefix.
    if _SESSION_ROOT.match(cwd):
        return (
            os.path.join(cwd, "mnt", "outputs", "artifacts"),
            _agent_override(env, _AGENT_ROOT_COWORK),
        )

    # CLI: ./artifacts (matches find_artifact.py's default artifacts root); both roots identical.
    root = os.path.join(cwd, "artifacts")
    return root, root


def resolve_artifacts_root(cwd: str, env: dict[str, str]) -> str:
    return resolve_roots(cwd, env)[0]


def build_agent_paths(agent_root: str, dir_name: str, run_id: str | None = None) -> dict[str, str]:
    """Build the FULL agent-namespace paths a Context-A dispatch needs, from the agent-namespace
    artifacts root plus the per-run/per-company directory name (e.g. `competitive-positioning-acme-corp`).

    Every skill's Step 0 currently hand-concatenates `HANDOFF_AGENT` / `ANALYSIS_DIR_AGENT` as
    `<printed AGENT_ARTIFACTS_ROOT>/<skill>-<slug>[/handoff/<run_id>]` in its own SKILL.md bash —
    a free-form string a paraphrasing agent can get wrong. This gives callers the option to get the
    same result from the script instead. Purely additive: `resolve_roots`/`resolve_artifacts_root`
    and the existing `--agent`/`--json` CLI behavior are unchanged when this isn't used.

    Returns {"analysis_dir_agent": ...} plus {"handoff_dir_agent": ...} when `run_id` is given.
    """
    analysis_dir_agent = f"{agent_root}/{dir_name}" if agent_root else dir_name
    result = {"analysis_dir_agent": analysis_dir_agent}
    if run_id:
        result["handoff_dir_agent"] = f"{analysis_dir_agent}/handoff/{run_id}"
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve the canonical artifacts root deterministically.")
    p.add_argument(
        "--json",
        action="store_true",
        help='Emit {"artifacts_root": ..., "agent_artifacts_root": ...} instead of a bare path'
        " (plus analysis_dir_agent/handoff_dir_agent when --dir-name is given)",
    )
    p.add_argument("--agent", action="store_true", help="Print the agent-namespace root instead")
    p.add_argument("--no-create", action="store_true", help="Do not mkdir the resolved root")
    p.add_argument(
        "--dir-name",
        default=None,
        help="Per-run/per-company dir name (e.g. 'competitive-positioning-acme-corp'), "
        "for --analysis-dir-agent / --handoff-dir-agent / the --json extra keys",
    )
    p.add_argument("--run-id", default=None, help="RUN_ID, required by --handoff-dir-agent")
    p.add_argument(
        "--analysis-dir-agent",
        action="store_true",
        help="Print the full agent-namespace ANALYSIS_DIR_AGENT (requires --dir-name)",
    )
    p.add_argument(
        "--handoff-dir-agent",
        action="store_true",
        help="Print the full agent-namespace HANDOFF_AGENT (requires --dir-name and --run-id)",
    )
    args = p.parse_args()

    if args.handoff_dir_agent and not args.run_id:
        p.error("--handoff-dir-agent requires --run-id")
    if (args.analysis_dir_agent or args.handoff_dir_agent) and not args.dir_name:
        p.error("--analysis-dir-agent/--handoff-dir-agent require --dir-name")

    root, agent_root = resolve_roots(os.getcwd(), dict(os.environ))
    if not args.no_create:
        os.makedirs(root, exist_ok=True)

    agent_paths = build_agent_paths(agent_root, args.dir_name, args.run_id) if args.dir_name else {}

    # A MISTYPED --dir-name IS OTHERWISE SILENT, AND ITS SYMPTOM POINTS THE WRONG WAY.
    # `build_agent_paths` is string concatenation with no validation, so any string yields a
    # plausible-looking path. The shell-side HANDOFF_DIR is derived separately from REVIEW_DIR and
    # stays correct, so sub-agents write to one place while `check_handoff.py` reads another: exit
    # 3 on every dispatch, which the state machine reads as fabricated receipts and answers by
    # burning the retry budget on redo-dispatches that cannot succeed. One warning here turns a
    # whole-run failure into a one-line diagnosis at Step 0.
    #
    # WARNING, never an error. An agent-root override can legitimately decouple the two
    # namespaces, and on a first run the canonical directory may not exist yet -- failing closed
    # would break working callers to catch a typo.
    if args.dir_name:
        mirror = os.path.join(root, args.dir_name)
        if not os.path.isdir(mirror):
            sys.stderr.write(
                f"Warning: no directory named {args.dir_name!r} under the canonical artifacts root "
                f"({root}). If that name is a typo, the agent-namespace path below is still well-formed "
                f"and every hand-off will fail check_handoff.py with exit 3 (which reads as a fabricated "
                f"receipt, not a bad path). Expected the basename of the analysis dir, e.g. "
                f"'<skill>-<slug>'.\n"
            )

    if args.handoff_dir_agent:
        sys.stdout.write(agent_paths["handoff_dir_agent"] + "\n")
    elif args.analysis_dir_agent:
        sys.stdout.write(agent_paths["analysis_dir_agent"] + "\n")
    elif args.json:
        payload = {"artifacts_root": root, "agent_artifacts_root": agent_root, **agent_paths}
        sys.stdout.write(json.dumps(payload) + "\n")
    elif args.agent:
        sys.stdout.write(agent_root + "\n")
    else:
        sys.stdout.write(root + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
