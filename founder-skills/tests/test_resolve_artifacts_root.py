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
# Host-loop: the workspace-shell cwd is somewhere inside /sessions/<id>/mnt/...
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
        "/sessions/abc",  # shell AT the session root — the shape that regressed
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
    """Back-compat: existing callers that never pass --dir-name see the exact same
    {"artifacts_root", "agent_artifacts_root"} shape as before this change."""
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--json"], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc == 0, err
    data = json.loads(out)
    assert set(data.keys()) == {"artifacts_root", "agent_artifacts_root"}


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
