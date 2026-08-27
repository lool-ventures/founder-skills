"""Unit tests for the deterministic artifacts-root resolver.

The resolver exists because SKILL.md bash is paraphrased by the agent (non-deterministic path
choice). These tests lock the canonical resolution rule so it cannot silently drift.

Topology is detected from the cwd STRING SHAPE (not the filesystem), so these tests pass literal
`/sessions/...` cwds and never touch disk — which is also what makes the host-loop / VM-loop branches
unit-testable at all (real dirs can't be created under literal `/sessions/`).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_artifacts_root.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("resolve_artifacts_root", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
resolve = _mod.resolve_artifacts_root
resolve_roots = _mod.resolve_roots


# ---------------------------------------------------------------------------
# Host-loop (PRODUCTION): the workspace-shell cwd is the BARE SESSION ROOT
# /sessions/<id> — measured upstream 2026-08-27, pinned in cowork-harness >=2.4.0
# (`hostLoopCwds`). The `/sessions/<id>/mnt/...` shapes below are the VM-loop tiers
# and any pre-2.4.0 recording; both are still exercised on purpose.
# The resolver anchors UNCONDITIONALLY on <session>/mnt/outputs, and the agent
# namespace is the mount-relative "artifacts" (the sub-agent's cwd IS that mount).
# ---------------------------------------------------------------------------


def test_hostloop_cwd_is_outputs_mount() -> None:
    root, agent = resolve_roots("/sessions/abc/mnt/outputs", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"
    assert agent == "artifacts"


def test_hostloop_cwd_connected_folder_anchors_on_outputs() -> None:
    # A connected folder shifts the shell cwd off the outputs mount (first-folder-else-outputs);
    # the resolver must STILL anchor on the session outputs mount, not on <folder>.
    root, agent = resolve_roots("/sessions/abc/mnt/myproject", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"
    assert agent == "artifacts"


def test_hostloop_connected_folder_named_like_it_has_outputs() -> None:
    # Regression for the divergence bug: even a folder whose own subtree looks like `outputs/` must
    # NOT re-anchor artifacts inside the user's project (detection is pure-string, never FS-probed).
    root, agent = resolve_roots("/sessions/abc/mnt/myproject/outputs", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"
    assert agent == "artifacts"


def test_hostloop_cwd_below_mount_root() -> None:
    # Model cd'd into a subdir of a connected folder — still anchors on the session outputs mount.
    root, agent = resolve_roots("/sessions/abc/mnt/myproject/src/deep", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"
    assert agent == "artifacts"


def test_hostloop_cwd_is_mnt_exactly() -> None:
    root, agent = resolve_roots("/sessions/abc/mnt", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"
    assert agent == "artifacts"


# ---------------------------------------------------------------------------
# Shell AT the session root /sessions/<id>: the ABSOLUTE root descends into the
# outputs mount (the session root is the cwd itself), but the AGENT-namespace
# root is the same as every other Cowork branch.
#
# These assert the INVARIANT, not a literal string. The previous version of this
# test asserted `agent == "mnt/outputs/artifacts"` — the exact value that made a
# sub-agent's relative path resolve to a DOUBLED `<outputs>/mnt/outputs/...`
# under real Cowork. It was written from the same premise as the code (that the
# shell's cwd reveals the sub-agent's cwd), so it could never falsify it and
# stayed green while the defect shipped. Assert the property that has to hold.
# ---------------------------------------------------------------------------


def _agent_path_resolves_under_outputs(cwd: str, env: dict[str, str]) -> bool:
    """The invariant: joining a sub-agent's cwd with the agent root must land on
    the same physical dir the main thread addresses absolutely.

    A sub-agent's cwd on any Cowork session tree IS the session outputs dir —
    that is the fact the resolver must encode, and it does not vary with where
    the main thread's shell happens to sit.
    """
    abs_root, agent_root = resolve_roots(cwd, env)
    subagent_cwd = abs_root.split("/artifacts")[0]  # <session>/mnt/outputs
    return bool(os.path.normpath(os.path.join(subagent_cwd, agent_root)) == os.path.normpath(abs_root))


def test_shell_at_session_root_absolute_root_descends_into_outputs() -> None:
    root, _ = resolve_roots("/sessions/abc", {})
    assert root == "/sessions/abc/mnt/outputs/artifacts"


def test_agent_root_resolves_under_outputs_wherever_the_shell_sits() -> None:
    """Regression: the doubled-prefix defect. Every Cowork cwd shape must yield an
    agent root that resolves to the SAME dir as the absolute root."""
    for cwd in (
        "/sessions/abc",  # shell AT the session root — PRODUCTION host-loop as of harness
        #                   2.4.0, and separately the shape whose agent root once regressed
        "/sessions/abc/mnt",
        "/sessions/abc/mnt/outputs",
        "/sessions/abc/mnt/SomeConnectedFolder",
    ):
        assert _agent_path_resolves_under_outputs(cwd, {}), f"agent root misresolves for cwd={cwd}"


def test_agent_root_is_identical_across_cowork_cwd_shapes() -> None:
    """The shell's cwd is a different process in a different namespace; it must not
    change the agent-namespace answer at all."""
    roots = {resolve_roots(cwd, {})[1] for cwd in ("/sessions/abc", "/sessions/abc/mnt", "/sessions/abc/mnt/outputs")}
    assert roots == {"artifacts"}, f"agent root varies with shell cwd: {roots}"


def test_vmloop_agent_root_comes_from_an_explicit_declaration() -> None:
    """A genuine VM-loop tier (agent cwd == session root) is served by a stated fact,
    never inferred from the shell's cwd shape."""
    _, agent = resolve_roots("/sessions/abc", {"COWORK_AGENT_ARTIFACTS_ROOT": "mnt/outputs/artifacts"})
    assert agent == "mnt/outputs/artifacts"
    # ...and the override does not disturb the absolute root.
    root, _ = resolve_roots("/sessions/abc", {"COWORK_AGENT_ARTIFACTS_ROOT": "mnt/outputs/artifacts"})
    assert root == "/sessions/abc/mnt/outputs/artifacts"


# ---------------------------------------------------------------------------
# CLI default + the negative cases: an ordinary path that merely resembles a
# session tree must NOT be hijacked (start-anchored regex), and both roots are
# the same absolute path (shared filesystem, no path gate).
# ---------------------------------------------------------------------------


def test_cli_default_is_cwd_artifacts(tmp_path: Path) -> None:
    root, agent = resolve_roots(str(tmp_path), {})
    assert root == os.path.join(str(tmp_path), "artifacts")
    assert agent == root  # CLI: both namespaces identical


def test_cli_project_with_outputs_sibling_not_hijacked(tmp_path: Path) -> None:
    # A plain CLI project that happens to contain ./outputs/ must fall through to ./artifacts,
    # never re-anchor into the sibling (the deleted bare-sibling branch used to do exactly that).
    (tmp_path / "outputs").mkdir()
    root, agent = resolve_roots(str(tmp_path), {})
    assert root == os.path.join(str(tmp_path), "artifacts")
    assert agent == root


def test_cli_path_containing_sessions_mnt_substring_not_hijacked() -> None:
    # /home/x/sessions/y/mnt/z is NOT a Cowork session tree (doesn't START with /sessions) → CLI default.
    root, agent = resolve_roots("/home/x/sessions/y/mnt/z", {})
    assert root == "/home/x/sessions/y/mnt/z/artifacts"
    assert agent == root


def test_cli_parent_named_mnt_not_hijacked() -> None:
    root, agent = resolve_roots("/home/x/mnt/project", {})
    assert root == "/home/x/mnt/project/artifacts"
    assert agent == root


def test_env_override_wins() -> None:
    # The override wins even inside a session tree, and both roots are the same absolute path.
    root, agent = resolve_roots("/sessions/abc/mnt/outputs", {"COWORK_ARTIFACTS_ROOT": "/somewhere/else"})
    assert root == os.path.abspath("/somewhere/else")
    assert agent == root


def test_resolve_artifacts_root_returns_first_element() -> None:
    assert resolve("/sessions/abc/mnt/outputs", {}) == "/sessions/abc/mnt/outputs/artifacts"
    assert resolve("/home/user/proj", {}) == os.path.join("/home/user/proj", "artifacts")


# ---------------------------------------------------------------------------
# Agent-namespace full-path builder: competitive-positioning's Step 0 hand-
# concatenates HANDOFF_AGENT / ANALYSIS_DIR_AGENT from the printed
# AGENT_ARTIFACTS_ROOT (`<root>/<skill>-<slug>[/handoff/<run_id>]`) — additive
# helper so callers can get the full path from the script instead of splicing
# strings themselves. Purely additive: existing --agent / --json / bare-root
# behavior (tested above) is unchanged when the new flags are absent.
# ---------------------------------------------------------------------------


def test_build_agent_paths_analysis_dir_only() -> None:
    build_agent_paths = _mod.build_agent_paths
    result = build_agent_paths("artifacts", "competitive-positioning-acme-corp")
    assert result == {"analysis_dir_agent": "artifacts/competitive-positioning-acme-corp"}


def test_build_agent_paths_includes_handoff_when_run_id_given() -> None:
    build_agent_paths = _mod.build_agent_paths
    result = build_agent_paths("artifacts", "competitive-positioning-acme-corp", run_id="20260319T143045Z")
    assert result == {
        "analysis_dir_agent": "artifacts/competitive-positioning-acme-corp",
        "handoff_dir_agent": "artifacts/competitive-positioning-acme-corp/handoff/20260319T143045Z",
    }


def test_build_agent_paths_vmloop_agent_root() -> None:
    build_agent_paths = _mod.build_agent_paths
    result = build_agent_paths("mnt/outputs/artifacts", "market-sizing-acme", run_id="R1")
    assert result["analysis_dir_agent"] == "mnt/outputs/artifacts/market-sizing-acme"
    assert result["handoff_dir_agent"] == "mnt/outputs/artifacts/market-sizing-acme/handoff/R1"


def test_build_agent_paths_cli_absolute_root() -> None:
    build_agent_paths = _mod.build_agent_paths
    result = build_agent_paths("/home/user/proj/artifacts", "ic-sim-acme", run_id="R1")
    assert result["analysis_dir_agent"] == "/home/user/proj/artifacts/ic-sim-acme"
    assert result["handoff_dir_agent"] == "/home/user/proj/artifacts/ic-sim-acme/handoff/R1"


# ---------------------------------------------------------------------------
# CLI wiring for the new flags (subprocess — exercises argparse + main()
# exactly as SKILL.md's Step 0 bash block invokes it).
# ---------------------------------------------------------------------------


def _run_cli(args: list[str], env_extra: dict[str, str]) -> tuple[int, str, str]:
    env = dict(os.environ)
    env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def test_cli_analysis_dir_agent_flag(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(
        ["--analysis-dir-agent", "--dir-name", "competitive-positioning-acme-corp"],
        {"COWORK_ARTIFACTS_ROOT": root},
    )
    assert rc == 0, err
    assert out.strip() == os.path.join(root, "competitive-positioning-acme-corp")


def test_cli_handoff_dir_agent_flag(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(
        [
            "--handoff-dir-agent",
            "--dir-name",
            "competitive-positioning-acme-corp",
            "--run-id",
            "20260319T143045Z",
        ],
        {"COWORK_ARTIFACTS_ROOT": root},
    )
    assert rc == 0, err
    assert out.strip() == os.path.join(root, "competitive-positioning-acme-corp", "handoff", "20260319T143045Z")


def test_cli_handoff_dir_agent_without_run_id_errors(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(
        ["--handoff-dir-agent", "--dir-name", "competitive-positioning-acme-corp"],
        {"COWORK_ARTIFACTS_ROOT": root},
    )
    assert rc != 0
    assert "run-id" in err.lower() or "run_id" in err.lower()


def test_cli_analysis_dir_agent_without_dir_name_errors(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--analysis-dir-agent"], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc != 0
    assert "dir-name" in err.lower() or "dir_name" in err.lower()


def test_cli_json_includes_agent_paths_when_dir_name_given(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(
        [
            "--json",
            "--dir-name",
            "competitive-positioning-acme-corp",
            "--run-id",
            "20260319T143045Z",
        ],
        {"COWORK_ARTIFACTS_ROOT": root},
    )
    assert rc == 0, err
    data = json.loads(out)
    expected_dir = os.path.join(root, "competitive-positioning-acme-corp")
    assert data["analysis_dir_agent"] == expected_dir
    assert data["handoff_dir_agent"] == os.path.join(expected_dir, "handoff", "20260319T143045Z")
    # Pre-existing keys are unaffected (back-compat).
    assert data["artifacts_root"] == root
    assert data["agent_artifacts_root"] == root


def test_cli_json_omits_agent_paths_when_dir_name_absent(tmp_path: Path) -> None:
    """Without --dir-name the agent-PATH keys are absent, and the base payload is pinned.

    `uploads_dir` joined the base set on 2026-08-27. It is additive — no consumer reads
    this payload by exact key set (verified: nothing in the fleet parses `--json` at all;
    SKILL.mds use the bare/--agent/--handoff-dir-agent forms) — but the set stays pinned
    so a future key cannot arrive unnoticed.
    """
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--json"], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc == 0, err
    data = json.loads(out)
    assert set(data.keys()) == {"artifacts_root", "agent_artifacts_root", "uploads_dir"}
    assert "analysis_dir_agent" not in data and "handoff_dir_agent" not in data


def test_cli_json_uploads_is_null_not_absent_off_a_session_tree(tmp_path: Path) -> None:
    """An omitted key read as "" builds `/uploads` and lists the host root. Force the branch."""
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--json"], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc == 0, err
    data = json.loads(out)
    assert "uploads_dir" in data and data["uploads_dir"] is None


def test_cli_uploads_flag_exits_3_off_a_session_tree(tmp_path: Path) -> None:
    """Exit 3, not 0-with-empty-stdout: "no uploads mount" must be distinguishable from
    "the mount is empty", or a skill tells the founder their attachment is missing."""
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--uploads"], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc == 3, (rc, out, err)
    assert out.strip() == ""
    assert "uploads mount" in err


def test_cli_uploads_flag_prints_the_declared_override(tmp_path: Path) -> None:
    up = str(tmp_path / "up")
    rc, out, err = _run_cli(["--uploads"], {"COWORK_UPLOADS_DIR": up})
    assert rc == 0, err
    assert out.strip() == up


def test_cli_warns_when_dir_name_has_no_canonical_mirror(tmp_path: Path) -> None:
    """A mistyped --dir-name is otherwise silent, and its symptom points the wrong way.

    `build_agent_paths` is string concatenation with no validation, so any string yields a
    plausible path. Measured cause of a near-miss: deck-review's SKILL.md said
    `--dir-name "<basename of REVIEW_DIR>"` where every sibling skill states a literal, the slug
    was passed instead, and the resulting path was well-formed and wrong. The shell-side
    HANDOFF_DIR stays correct, so sub-agents write one place and `check_handoff.py` reads another:
    exit 3 on every dispatch, which the state machine reads as a fabricated receipt rather than a
    bad path, and answers by spending the retry budget on redo-dispatches that cannot succeed.
    """
    root = tmp_path / "artifacts"
    (root / "deck-review-acme").mkdir(parents=True)
    rc, out, err = _run_cli(
        ["--analysis-dir-agent", "--dir-name", "acme"],  # the slug, not the dir basename
        {"COWORK_ARTIFACTS_ROOT": str(root)},
    )
    assert rc == 0, "a warning, never an error — an agent-root override legitimately decouples the two"
    assert out.strip() == os.path.join(str(root), "acme"), "the path is still emitted"
    assert "Warning:" in err and "acme" in err
    assert "check_handoff" in err, "the warning must name the symptom, which points the wrong way"


def test_cli_is_silent_when_the_mirror_exists(tmp_path: Path) -> None:
    """The counter-test: a correct --dir-name must not produce noise on every run."""
    root = tmp_path / "artifacts"
    (root / "deck-review-acme").mkdir(parents=True)
    rc, out, err = _run_cli(
        ["--analysis-dir-agent", "--dir-name", "deck-review-acme"],
        {"COWORK_ARTIFACTS_ROOT": str(root)},
    )
    assert rc == 0
    assert "Warning:" not in err, err


# ---------------------------------------------------------------------------
# Uploads mount (`--uploads` / resolve_uploads_dir).
#
# WHY THESE EXIST: deck-review located attached files with
#   ls -la "$(dirname "$REVIEW_DIR")"/../uploads 2>/dev/null || ls -la ./mnt/uploads
# Both arms were wrong, and the SECOND one's meaning MOVED when cowork-harness 2.4.0
# corrected the workspace-shell cwd. That is the whole point of resolving it here:
# a path that is correct only on one harness version is not a path.
# ---------------------------------------------------------------------------

resolve_uploads_dir = _mod.resolve_uploads_dir


def test_uploads_is_identical_across_every_cowork_cwd_shape() -> None:
    """The uploads mount is a property of the SESSION TREE, not of where the shell
    happens to stand. If this ever varies by cwd, the 2.4.0 class of bug is back."""
    seen = {
        resolve_uploads_dir(cwd, {})
        for cwd in (
            "/sessions/abc",  # production host-loop (harness >=2.4.0)
            "/sessions/abc/mnt",
            "/sessions/abc/mnt/outputs",  # what host-loop looked like pre-2.4.0
            "/sessions/abc/mnt/SomeConnectedFolder",
        )
    }
    assert seen == {"/sessions/abc/mnt/uploads"}, f"uploads varies with shell cwd: {seen}"


def test_uploads_is_none_on_the_plain_cli_never_a_guessed_path() -> None:
    """None, not './uploads'. A fabricated path would `ls` clean-empty and be reported
    to the founder as 'you attached nothing' — the exact failure this replaced."""
    assert resolve_uploads_dir("/home/dev/project", {}) is None


def test_uploads_is_not_derived_from_the_artifacts_root_override() -> None:
    """$COWORK_ARTIFACTS_ROOT may point anywhere; uploads must not follow it."""
    env = {"COWORK_ARTIFACTS_ROOT": "/tmp/elsewhere/artifacts"}
    assert resolve_uploads_dir("/sessions/abc", env) == "/sessions/abc/mnt/uploads"


def test_uploads_honors_an_explicit_declaration() -> None:
    env = {"COWORK_UPLOADS_DIR": "/tmp/up"}
    assert resolve_uploads_dir("/sessions/abc", env) == "/tmp/up"
    assert resolve_uploads_dir("/home/dev/project", env) == "/tmp/up"


def test_the_replaced_relative_path_would_have_moved_between_harness_versions() -> None:
    """Pins the defect itself, so nobody reintroduces a cwd-relative uploads path.

    `./mnt/uploads` resolved against the workspace shell's cwd. Under the pre-2.4.0
    cwd it pointed at a directory that never existed; under the corrected cwd it
    happens to be right. Same string, two meanings — which is why it is gone.
    """
    old_cwd, new_cwd = "/sessions/abc/mnt/outputs", "/sessions/abc"
    relative = os.path.normpath(os.path.join(old_cwd, "mnt/uploads"))
    assert relative == "/sessions/abc/mnt/outputs/mnt/uploads"
    assert relative != resolve_uploads_dir(old_cwd, {})
    assert os.path.normpath(os.path.join(new_cwd, "mnt/uploads")) == resolve_uploads_dir(new_cwd, {})


# ---------------------------------------------------------------------------
# `_default_artifacts_root` — the duplicated helper, and the fallback it hides
#
# It exists in find_artifact.py AND founder_context.py because skill/shared scripts are standalone
# and cannot be packaged. The fleet's precedent for a duplicated helper is a SYNC TEST
# (test_theme_sync.py for _theme.py, test_quote_match_sync.py for _quote_match.py); this had none,
# and no test exercised the default at all — mutating either copy to return a constant left the
# whole suite green.
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = _SCRIPT.parent
_HELPER_HOSTS = ("find_artifact.py", "founder_context.py")


def _load_host(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name[:-3], _SCRIPTS_DIR / name)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _helper_body(name: str) -> str:
    text = (_SCRIPTS_DIR / name).read_text(encoding="utf-8")
    start = text.index("def _default_artifacts_root")
    return text[start : text.index("\n\n\n", start)]


def test_default_artifacts_root_copies_do_not_drift() -> None:
    """Edit one, re-copy to the other — the same contract as _theme.py."""
    bodies = {name: _helper_body(name) for name in _HELPER_HOSTS}
    assert len(set(bodies.values())) == 1, (
        "_default_artifacts_root has drifted between "
        + " and ".join(_HELPER_HOSTS)
        + ". These are copies of one helper; edit one and re-copy to the other."
    )


def _root_at(host: str, cwd: str) -> str:
    mod = _load_host(host)
    real = mod.os.getcwd
    mod.os.getcwd = lambda: cwd
    try:
        return str(mod._default_artifacts_root())
    finally:
        mod.os.getcwd = real


def test_default_artifacts_root_resolves_the_session_tree() -> None:
    """The point of the helper: on a session tree it must NOT return $PWD/artifacts.

    Without this, mutating either copy to `os.path.join(os.getcwd(), "artifacts")` — i.e. reverting
    the fix — left all 5,001 tests in the repo green.
    """
    for host in _HELPER_HOSTS:
        got = _root_at(host, "/sessions/abc123")
        assert got == "/sessions/abc123/mnt/outputs/artifacts", f"{host}: {got}"


def test_default_artifacts_root_matches_the_cli_case() -> None:
    """Off a session tree it must agree with the old behaviour, or the change was a regression."""
    for host in _HELPER_HOSTS:
        got = _root_at(host, "/home/dev/project")
        assert got == "/home/dev/project/artifacts", f"{host}: {got}"
