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
main-thread workspace shell, whose cwd is a DIFFERENT path space from the file tools'. On Cowork
host-loop -- the production topology -- that shell starts at the BARE SESSION ROOT `/sessions/<id>`
(branch 3 below). The agent process, and so the file tools, run host-native, outside the VM, and not in
the outputs dir: they address the outputs folder by its HOST path (see HOST-LOOP below). Branch 2 (a
shell inside `/sessions/<id>/mnt/...`) serves the VM-loop tiers.

**Branches 2 and 3 return IDENTICAL roots, and that convergence is the invariant.** Do not "simplify"
either away, and do not let them diverge: a change that makes them disagree silently relocates every
artifact the moment the shell's cwd moves.

The shell's cwd is NOT necessarily the outputs mount. Probing the filesystem for a sibling `outputs/`
mis-anchors: if a connected folder contains its own `outputs/`, an `isdir(cwd/outputs)` branch would point
artifacts INSIDE the user's real project, while the sub-agents' file tools write to the session's outputs
folder -- write and gate would then address different physical dirs. So we key on the session ROOT
extracted from the cwd shape and anchor unconditionally on `<session>/mnt/outputs`, regardless of where
in the tree the shell cwd sits.

Resolution (first match wins; pure string logic, no FS probe except the CLI mkdir and the persisted
host path in main()):
  1. $COWORK_ARTIFACTS_ROOT (explicit override / tests) -> (abs, abs)
  2. Cowork session tree, shell inside the mount: `^/sessions/<id>/mnt(/...)?`
                                              -> (<session>/mnt/outputs/artifacts, <host outputs>/artifacts)
  3. Cowork session tree, shell AT the session root: `^/sessions/<id>$`
                                              -> (cwd/mnt/outputs/artifacts, <host outputs>/artifacts)
  4. CLI default:                             -> (cwd/artifacts, cwd/artifacts)
  On a session tree with no proven host path, an agent-namespace call refuses (exit 6) rather than print
  a relative root the file tools would refuse.
  $COWORK_AGENT_ARTIFACTS_ROOT overrides ONLY the agent-namespace half (see below).

Prints the absolute artifacts root on stdout (one line). With --json, prints
{"artifacts_root": ..., "agent_artifacts_root": ..., "uploads_dir": ...}. Creates the dir unless
--no-create. `--uploads` prints the uploads mount alone (exit 3 when there is no session tree) --
see `resolve_uploads_dir`.

THREE CONSUMERS READ THE SHELL cwd, NOT ONE. Beyond this module, `find_artifact.py` and
`founder_context.py` both default `--artifacts-root` to `os.path.join(os.getcwd(), "artifacts")`.
Every SKILL.md passes the flag explicitly, so those defaults are latent -- but "the flag is always
passed" is a property of PROSE the agent paraphrases (see WHY THIS EXISTS above), and a dropped flag
lands at `/sessions/<id>/artifacts`, outside `mnt/`, where nothing is ever delivered and nothing
reports it. If you add a fourth consumer, pass the root in -- do not re-derive it from `getcwd()`.

AGENT NAMESPACE (branch C hand-off): the same file has two addresses -- the main thread's absolute VM
path under the outputs root, and the path the file tools use. On the CLI both sides share one
filesystem, so both roots are the same absolute path. Print it with --agent. Dispatch prompts build
OUTPUT_PATH (and under-outputs read paths) from the agent namespace; shell-side gates use the absolute
namespace.

**THE SHELL'S cwd CANNOT TELL YOU WHERE THE FILE TOOLS ARE.** Branches 2 and 3 differ only in how they
LOCATE the session root (from the `/mnt` match, or from the cwd itself) -- which the ABSOLUTE root
depends on. They must NOT differ in the agent-namespace root: inferring the file tools' location from
the shell's cwd shape produces a DOUBLED `<outputs>/mnt/outputs/artifacts/...` prefix, silently, for
every blind-writing sub-agent.

HOST-LOOP: THE AGENT NAMESPACE MUST BE ABSOLUTE, AND ONLY THE MODEL KNOWS IT.
The agent process does not run in the outputs dir, and a RELATIVE `Read`/`Write`/`Edit` is refused
("File is in a directory that is denied by your permission settings."). So the relative `"artifacts"`
root described above is refused, for the main thread and every sub-agent alike. The file
tools need the HOST path of the outputs folder (production: `.../local-agent-mode-sessions/<org>/<user>/
<8hex>/outputs`; it contains a space), and nothing in the VM shell can see it: Desktop names it to the
MODEL only, in a "Paths in bash differ from what file tools (Read/Write/Edit) see:" block mapping it to
`/sessions/<id>/mnt/outputs/`. Sub-agents given a relative OUTPUT_PATH routinely ignore the
platform's own "Pass absolute paths to these tools."

So the main thread supplies the host path ONCE, and a probe PROVES it before anything uses it:
  1. the main thread Writes, with its FILE tool, `<host outputs>/artifacts/.host-outputs-probe`
     containing exactly `<host outputs>`;
  2. `--set-host-outputs-dir "<host outputs>"` checks the shape, then checks that the probe landed at
     THIS shell's `<artifacts root>/.host-outputs-probe` with that exact content -- which can only happen
     if the file tool and this shell address the same directory under those two names;
  3. only then is the value persisted to `<artifacts root>/.host-outputs-dir.json`, and every later
     agent-namespace call (in any fresh shell) reads it and prints ABSOLUTE agent paths.
A mistyped path fails at step 2 (the probe is absent or its content differs), at Step 0, where it can be
retried -- not as an exit 3 on every hand-off later. The proof also serves a VM-loop tier unchanged: there
the file tool takes the `/sessions/...` path itself, so `<host outputs>` IS the shell path and the probe
lands. Without a proven value, agent-namespace calls on a session tree exit 6 (`EXIT_NOT_PROVEN`) with a
JSON diagnostic, unless `$COWORK_AGENT_ARTIFACTS_ROOT` declares the agent root.

REMOTE LANE (Cowork "in the cloud", the default for new sessions):
no `/sessions` tree; shell cwd `/home/claude`; `CLAUDE_CODE_REMOTE=true`. Artifacts fall through to the
CLI branch (`/home/claude/artifacts`, one shared filesystem, so both roots are the same absolute path),
which is correct. Uploads do NOT: see `_remote_uploads_dir`.

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


# The proof and the persisted value live in the canonical artifacts root (shell namespace), so any later
# fresh shell finds them. Dot-files: never artifacts, never read by a producer. We never delete under
# the outputs mount (our rule), so they persist -- harmless, and a later run in the same session re-proves over them.
PROBE_NAME = ".host-outputs-probe"
PERSIST_NAME = ".host-outputs-dir.json"

EXIT_BAD_HOST_DIR = 2
EXIT_PROBE_MISSING = 4
EXIT_PROBE_MISMATCH = 5
# An agent-namespace call on a session tree with no proven host path and no declared override. Answering
# with the relative root would hand every sub-agent a path the file tools refuse, and the refusal would
# surface much later, as a hand-off failure that reads like a fabricated receipt.
EXIT_NOT_PROVEN = 6


def normalize_host_outputs_dir(value: str) -> tuple[str | None, str | None]:
    """Return (normalized, None) or (None, reason). Shape only -- the probe is the proof."""
    v = value.strip()
    if "\n" in v or "\r" in v:
        return None, "the path contains a line break -- pass exactly one path"
    v = v.rstrip("/")
    if not v.startswith("/"):
        return None, "the path is not absolute -- a relative path is what the file tools refuse"
    if os.path.basename(v) != "outputs":
        return None, (
            "the path does not end in an `outputs` folder -- pass the file-tool path your context maps to "
            "this session's outputs directory, not a folder inside it"
        )
    return v, None


def verify_probe(artifacts_dir: str, host_outputs_dir: str) -> tuple[int, str]:
    """Check the probe the main thread's file tool wrote. Returns (exit_code, detail)."""
    probe = os.path.join(artifacts_dir, PROBE_NAME)
    try:
        with open(probe, encoding="utf-8") as f:
            content = f.read().strip()
    except OSError:
        return EXIT_PROBE_MISSING, (
            f"no probe at {probe}: the file tool's Write to `{host_outputs_dir}/artifacts/{PROBE_NAME}` did "
            "not land in this session's outputs folder (it was refused, or went to a different folder), so "
            "that path is not the one the file tools use for it"
        )
    if content != host_outputs_dir:
        return EXIT_PROBE_MISMATCH, (
            f"the probe exists but contains {content!r}, not {host_outputs_dir!r}: write the SAME path you "
            "pass here, character for character"
        )
    return 0, "ok"


def read_persisted(artifacts_dir: str) -> str | None:
    """The proven host outputs dir, or None. A malformed file reads as absent, never as a path."""
    try:
        with open(os.path.join(artifacts_dir, PERSIST_NAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    value = data.get("host_outputs_dir") if isinstance(data, dict) else None
    if not isinstance(value, str):
        return None
    normalized, _ = normalize_host_outputs_dir(value)
    return normalized


def write_persisted(artifacts_dir: str, host_outputs_dir: str) -> None:
    with open(os.path.join(artifacts_dir, PERSIST_NAME), "w", encoding="utf-8") as f:
        json.dump({"host_outputs_dir": host_outputs_dir}, f)
        f.write("\n")


def on_session_tree(cwd: str) -> bool:
    return bool(_SESSION_TREE.match(cwd) or _SESSION_ROOT.match(cwd))


def _session_agent_root(host_outputs_dir: str | None) -> str:
    return f"{host_outputs_dir}/artifacts" if host_outputs_dir else _AGENT_ROOT_COWORK


def resolve_roots(cwd: str, env: dict[str, str], host_outputs_dir: str | None = None) -> tuple[str, str]:
    """Return (artifacts_root, agent_artifacts_root).

    agent_artifacts_root is the artifacts root as a SUB-AGENT's native file tools address it: relative
    to the sub-agent's cwd, which on any Cowork session tree is the session OUTPUTS dir (host-loop, the
    production topology) — never inferred from the main thread's shell cwd, which is a different process
    in a different namespace. Identical to the absolute root on the shared-filesystem CLI. See the module
    docstring's AGENT NAMESPACE section for why this must not branch on the shell's cwd shape, and for
    the `$COWORK_AGENT_ARTIFACTS_ROOT` escape hatch that serves a real VM-loop tier.

    `host_outputs_dir` is the PROVEN file-tool path of the outputs folder (see the module docstring's
    HOST-LOOP section). When given, the session-tree agent root is
    `<host_outputs_dir>/artifacts` -- absolute, which current Desktop requires. The explicit env override
    still wins over it: a declared fact beats a derived one.
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
            _agent_override(env, _session_agent_root(host_outputs_dir)),
        )

    # Cowork session tree, shell AT the session root /sessions/<id>. Only the ABSOLUTE root differs from
    # the branch above (the session root is the cwd itself); the agent-namespace root is the SAME, because
    # the sub-agent's cwd is the outputs dir either way. Returning "mnt/outputs/artifacts" here — inferring
    # the agent's cwd from the shell's — is the defect that produced a doubled `mnt/outputs/` prefix.
    if _SESSION_ROOT.match(cwd):
        return (
            os.path.join(cwd, "mnt", "outputs", "artifacts"),
            _agent_override(env, _session_agent_root(host_outputs_dir)),
        )

    # CLI: ./artifacts (matches find_artifact.py's default artifacts root); both roots identical.
    root = os.path.join(cwd, "artifacts")
    return root, root


def resolve_artifacts_root(cwd: str, env: dict[str, str]) -> str:
    return resolve_roots(cwd, env)[0]


def resolve_uploads_dir(cwd: str, env: dict[str, str]) -> str | None:
    """Return the absolute uploads mount, or None when there is no session tree (plain CLI).

    WHY THIS IS A SCRIPT FLAG AND NOT SHELL IN A SKILL.md: an attached file lands under
    `<session>/mnt/uploads`, and a skill that cannot list that dir tells the founder their upload is
    missing while it sits there. A hand-built path keyed off anything other than the session root --
    `../uploads` from an analysis dir, or `./mnt/uploads` against the workspace shell's cwd -- points at
    the real mount only for one shell cwd, and the shell's cwd is not a stable fact. Hence one opaque
    command, per this module's opening rationale.

    NOT derived from the artifacts root: `$COWORK_ARTIFACTS_ROOT` may point anywhere, and uploads is a
    property of the session tree, not of where artifacts were redirected. Keyed on the cwd shape only,
    with `$COWORK_UPLOADS_DIR` as the explicit override (same escape-hatch posture as the agent root:
    declared, never guessed).
    """
    override = env.get("COWORK_UPLOADS_DIR")
    if override:
        return os.path.abspath(override)

    m = _SESSION_TREE.match(cwd)
    if m:
        return os.path.join(m.group(1), "mnt", "uploads")
    if _SESSION_ROOT.match(cwd):
        return os.path.join(cwd, "mnt", "uploads")
    remote = _remote_uploads_dir(env)
    if remote is not None:
        return remote
    # Plain CLI: no session tree, so no uploads mount. None, never a fabricated path — a guessed
    # `./uploads` would `ls` clean-empty and read as "the founder attached nothing".
    return None


def _remote_uploads_dir(env: dict[str, str]) -> str | None:
    """Cowork's REMOTE (cloud) lane: the agent runs in a Linux VM with no `/sessions` tree at all.

    On this lane (the default for new sessions) the shell cwd is `/home/claude`,
    `CLAUDE_CODE_REMOTE=true`, and an attached file sits at
    `$HOME/.claude/uploads/<session id>/<8-hex>-<original name>` -- NOT at `/mnt/user-data/uploads`,
    which the lane's own environment description names and which does not exist. Answering "no session
    tree" here would make a skill tell the founder they supplied no documents.

    THE DIRECTORY IS THE SIGNAL, NOT THE ENV. Runtime markers are served per session and have been
    added and removed across releases (ccinternals.dev/cowork, "detect.markers-come-and-go"), so this
    keys on what is on disk: `$HOME/.claude/uploads/<CLAUDE_CODE_SESSION_ID>` when the id is known,
    else the single session dir under `$HOME/.claude/uploads/` (one session per remote VM). With
    nothing attached there is no dir, and None is the honest answer, never a fabricated path. Never
    reached on a `/sessions` tree (the branches above answer first) and never on a CLI host unless a
    `~/.claude/uploads/<session>` dir actually exists there, which nothing on the CLI creates.
    """
    home = env.get("HOME") or os.path.expanduser("~")
    base = os.path.join(home, ".claude", "uploads")
    session = env.get("CLAUDE_CODE_SESSION_ID")
    if session:
        candidate = os.path.join(base, session)
        return candidate if os.path.isdir(candidate) else None
    if not os.path.isdir(base):
        return None
    dirs = [d for d in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, d))]
    return os.path.join(base, dirs[0]) if len(dirs) == 1 else None


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
    p.add_argument(
        "--uploads",
        action="store_true",
        help="Print the absolute uploads mount (where attached files land). Exits 3 with a stderr "
        "note when there is no session tree (plain CLI), so an absent mount is distinguishable "
        "from an empty one",
    )
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
    p.add_argument(
        "--set-host-outputs-dir",
        default=None,
        metavar="PATH",
        help="PROVE and persist the file-tool path of this session's outputs folder (Cowork only). "
        "First Write, with a file tool, <PATH>/artifacts/" + PROBE_NAME + " containing exactly <PATH>; "
        "this checks that probe from the shell, persists PATH, and prints the absolute agent root. "
        "Exits 2 (bad shape), 4 (probe absent) or 5 (probe content differs) with a JSON diagnostic",
    )
    args = p.parse_args()
    cwd = os.getcwd()
    env = dict(os.environ)

    # ANSWERED FIRST, BEFORE ANY SIDE EFFECT OR UNRELATED VALIDATION. `--uploads` is a pure query
    # about the SESSION TREE: it needs no artifacts root, no --dir-name mirror, and no filesystem
    # access at all. Answering it after `os.makedirs(root)` meant a question about the uploads mount
    # CREATED the artifacts dir as a side effect (measured: an empty cwd gained `artifacts/` even on
    # the exit-3 "there is no session tree" path), and made the flag die with an uncaught
    # PermissionError in a read-only cwd — a third exit state the callers' prose does not document.
    if args.uploads:
        # A caller who typed `--uploads --json | jq` used to get a bare path and
        # `Expecting value: line 1 column 1` — the exact silent-format-mismatch class CLAUDE.md
        # already records for `critique --out` without `--output-format json`. Refuse instead.
        conflicting = [
            f"--{name.replace('_', '-')}"
            for name in ("json", "agent", "analysis_dir_agent", "handoff_dir_agent")
            if getattr(args, name)
        ]
        if conflicting:
            p.error("--uploads cannot be combined with " + ", ".join(conflicting))
        uploads_dir = resolve_uploads_dir(cwd, env)
        if uploads_dir is None:
            sys.stderr.write(
                "No uploads mount: this is not a Cowork session tree, so nothing was attached "
                "through one. Ask the founder for a path instead of reporting the file missing. "
                "Set $COWORK_UPLOADS_DIR to override.\n"
            )
            return 3
        sys.stdout.write(uploads_dir + "\n")
        return 0

    if args.handoff_dir_agent and not args.run_id:
        p.error("--handoff-dir-agent requires --run-id")
    if (args.analysis_dir_agent or args.handoff_dir_agent) and not args.dir_name:
        p.error("--analysis-dir-agent/--handoff-dir-agent require --dir-name")

    if args.set_host_outputs_dir is not None:
        return _set_host_outputs_dir(args.set_host_outputs_dir, cwd, env, create=not args.no_create)

    root, _ = resolve_roots(cwd, env)
    if not args.no_create:
        os.makedirs(root, exist_ok=True)
    wants_agent = args.agent or args.json or args.analysis_dir_agent or args.handoff_dir_agent
    host_outputs_dir = read_persisted(root) if on_session_tree(cwd) else None
    root, agent_root = resolve_roots(cwd, env, host_outputs_dir)
    if wants_agent and on_session_tree(cwd) and not host_outputs_dir and not env.get("COWORK_AGENT_ARTIFACTS_ROOT"):
        detail = (
            "no proven file-tool path for this session's outputs folder, so there is no agent-namespace "
            "path to give a sub-agent (a relative one is refused). Run the Step 0 proof first: Write "
            f"`<host outputs>/artifacts/{PROBE_NAME}` with a file tool, then --set-host-outputs-dir. On a "
            "tier whose file tools take this shell's paths, declare $COWORK_AGENT_ARTIFACTS_ROOT instead."
        )
        sys.stdout.write(
            json.dumps(
                {
                    "code": "host_outputs_dir_not_proven",
                    "detail": detail,
                    "shell_outputs_dir": os.path.dirname(root),
                    "probe_name": PROBE_NAME,
                }
            )
            + "\n"
        )
        sys.stderr.write(f"resolve_artifacts_root: {detail}\n")
        return EXIT_NOT_PROVEN

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

    uploads = resolve_uploads_dir(cwd, env)

    if args.handoff_dir_agent:
        sys.stdout.write(agent_paths["handoff_dir_agent"] + "\n")
    elif args.analysis_dir_agent:
        sys.stdout.write(agent_paths["analysis_dir_agent"] + "\n")
    elif args.json:
        # `null` rather than an omitted key: a consumer that reads a missing key as "" builds
        # `/uploads` and lists the host root. An explicit null forces the branch.
        payload: dict[str, str | None] = {
            "artifacts_root": root,
            "agent_artifacts_root": agent_root,
            **agent_paths,
            "uploads_dir": uploads,
        }
        sys.stdout.write(json.dumps(payload) + "\n")
    elif args.agent:
        sys.stdout.write(agent_root + "\n")
    else:
        sys.stdout.write(root + "\n")
    return 0


def _set_host_outputs_dir(value: str, cwd: str, env: dict[str, str], *, create: bool) -> int:
    """`--set-host-outputs-dir`: shape check, probe check, persist, print the absolute agent root.

    Diagnostics go to stdout as one JSON object and a line to stderr; nothing is persisted on failure,
    so a rejected value can never become the root later calls read.
    """
    root, _ = resolve_roots(cwd, env)
    shell_outputs = os.path.dirname(root)

    def fail(code: str, exit_code: int, detail: str) -> int:
        sys.stdout.write(
            json.dumps({"code": code, "detail": detail, "shell_outputs_dir": shell_outputs, "probe_name": PROBE_NAME})
            + "\n"
        )
        sys.stderr.write(f"--set-host-outputs-dir: {detail}\n")
        return exit_code

    if not on_session_tree(cwd):
        # CLI, the remote lane, or an explicit override: the file tools and this shell share one
        # filesystem, and the agent root is already absolute. Nothing to prove; say so, change nothing.
        sys.stdout.write(json.dumps({"code": "not_needed", "agent_artifacts_root": resolve_roots(cwd, env)[1]}) + "\n")
        return 0
    normalized, reason = normalize_host_outputs_dir(value)
    if normalized is None:
        return fail("bad_host_outputs_dir", EXIT_BAD_HOST_DIR, reason or "invalid path")
    if create:
        os.makedirs(root, exist_ok=True)
    status, detail = verify_probe(root, normalized)
    if status != 0:
        return fail("probe_missing" if status == EXIT_PROBE_MISSING else "probe_mismatch", status, detail)
    write_persisted(root, normalized)
    sys.stdout.write(resolve_roots(cwd, env, normalized)[1] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
