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

import pytest

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


def test_uploads_is_none_on_the_plain_cli_never_a_guessed_path(tmp_path: Path) -> None:
    """None, not './uploads'. A fabricated path would `ls` clean-empty and be reported
    to the founder as 'you attached nothing' — the exact failure this replaced."""
    assert resolve_uploads_dir("/home/dev/project", {"HOME": str(tmp_path)}) is None


_REMOTE_ENV = {
    "CLAUDE_CODE_REMOTE": "true",
    "CLAUDE_CODE_ENTRYPOINT": "remote_cowork",
    "CLAUDE_CODE_SESSION_ID": "117a27ba",
}


def test_uploads_on_the_remote_lane_is_the_per_session_uploads_dir(tmp_path: Path) -> None:
    """Measured in a real cloud session 2026-09-22: no `/sessions` tree, shell cwd /home/claude,
    an attached PDF at `$HOME/.claude/uploads/<CLAUDE_CODE_SESSION_ID>/<8-hex>-<name>.pdf` — and NOT
    at `/mnt/user-data/uploads`, which the lane's own environment text names and which does not
    exist. The live report came from this lane; before this branch its red team was told the
    founder supplied no documents."""
    up = tmp_path / ".claude" / "uploads" / "117a27ba"
    up.mkdir(parents=True)
    (up / "85451e6d-deck.pdf").write_bytes(b"%PDF")
    env = {**_REMOTE_ENV, "HOME": str(tmp_path)}
    assert resolve_uploads_dir("/home/claude", env) == str(up)


def test_uploads_on_the_remote_lane_with_nothing_attached_is_none(tmp_path: Path) -> None:
    """No attachment, no dir (measured): None, never a path that lists clean-empty."""
    env = {**_REMOTE_ENV, "HOME": str(tmp_path)}
    assert resolve_uploads_dir("/home/claude", env) is None


def test_remote_uploads_keys_on_the_directory_not_the_env_markers(tmp_path: Path) -> None:
    """Runtime markers are served per session and have changed across releases; the directory on
    disk is the durable signal. With the session id: that dir. Without it: the single session dir.
    Two session dirs and no id: ambiguous, None."""
    up = tmp_path / ".claude" / "uploads" / "117a27ba"
    up.mkdir(parents=True)
    assert resolve_uploads_dir("/home/claude", {"HOME": str(tmp_path), "CLAUDE_CODE_SESSION_ID": "117a27ba"}) == str(up)
    assert resolve_uploads_dir("/home/claude", {"HOME": str(tmp_path)}) == str(up)  # no markers at all
    (tmp_path / ".claude" / "uploads" / "other").mkdir()
    assert resolve_uploads_dir("/home/claude", {"HOME": str(tmp_path)}) is None
    assert resolve_uploads_dir("/home/claude", {"HOME": str(tmp_path), "CLAUDE_CODE_SESSION_ID": "117a27ba"}) == str(up)
    assert resolve_uploads_dir("/home/claude", {"HOME": str(tmp_path), "CLAUDE_CODE_SESSION_ID": "gone"}) is None


def test_cli_uploads_flag_on_the_remote_lane(tmp_path: Path) -> None:
    up = tmp_path / ".claude" / "uploads" / "117a27ba"
    up.mkdir(parents=True)
    rc, out, err = _run_cli(["--uploads"], {**_REMOTE_ENV, "HOME": str(tmp_path)})
    assert rc == 0, err
    assert out.strip() == str(up)


# The exit-3 note must be true on BOTH hosts that reach it. The cloud lane creates
# `~/.claude/uploads/<session>` only once something is attached, so before that it answers exactly as
# the plain CLI does; the old note ("this is not a Cowork session tree") was false there, and told the
# model the founder was on the wrong host when they had simply attached nothing yet.
_FALSE_ON_CLOUD = ("session tree", "not a cowork", "plain cli")


def _assert_exit_3_note_true_on_both_hosts(err: str) -> None:
    low = err.lower()
    for phrase in _FALSE_ON_CLOUD:
        assert phrase not in low, f"exit-3 note claims a host it cannot know ({phrase!r}): {err!r}"
    assert "nothing has been attached" in low and "somewhere this script does not look" in low, err
    assert "attach" in low and "path" in low, f"the note must say what to ask the user for: {err!r}"
    assert "$COWORK_UPLOADS_DIR" in err, "the declared override is a real escape hatch; keep it named"


def test_cli_uploads_exit_3_note_on_the_remote_lane_with_nothing_attached(tmp_path: Path) -> None:
    env = {**_REMOTE_ENV, "HOME": str(tmp_path), "COWORK_UPLOADS_DIR": ""}
    rc, out, err = _run_cli(["--uploads"], env)
    assert rc == 3, (rc, out, err)
    assert out.strip() == ""
    _assert_exit_3_note_true_on_both_hosts(err)


def test_cli_uploads_exit_3_note_when_several_session_folders_exist_and_no_id_picks_one(tmp_path: Path) -> None:
    """No session id and two session folders: the script cannot tell which is this session's, and says so.
    It does not pick the newest-modified one, which could be another session's."""
    for name in ("aaaa1111", "bbbb2222"):
        (tmp_path / ".claude" / "uploads" / name).mkdir(parents=True)
    env = {"HOME": str(tmp_path), "COWORK_UPLOADS_DIR": "", "CLAUDE_CODE_SESSION_ID": "", "CLAUDE_CODE_REMOTE": "true"}
    rc, out, err = _run_cli(["--uploads"], env)
    assert rc == 3, (rc, out, err)
    assert out.strip() == ""
    low = err.lower()
    assert "could not tell which session's uploads folder is this one's" in low, err
    assert "2 session folders" in low and "path" in low and "$COWORK_UPLOADS_DIR" in err
    assert "session tree" not in low and "nothing has been attached" not in low


def test_cli_uploads_exit_3_note_on_the_plain_cli(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "COWORK_UPLOADS_DIR": "", "CLAUDE_CODE_SESSION_ID": ""}
    rc, out, err = _run_cli(["--uploads"], env)
    assert rc == 3, (rc, out, err)
    _assert_exit_3_note_true_on_both_hosts(err)


_SKILLS_DIR = _SCRIPT.parent.parent / "skills"
_UPLOADS_CALL = 'resolve_artifacts_root.py" --uploads   # prints UPLOADS_DIR, or exits 3'


def _uploads_step(skill: str) -> str:
    """The paragraph before the `--uploads` block, the block, and the paragraph after it.

    Bounded on structure (blank lines and fences), not a character window, so an edit nearby cannot
    push the stated reason out of view while it is still there."""
    text = (_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.count(_UPLOADS_CALL) == 1, f"{skill}: the --uploads call must say it exits 3, once"
    at = text.index(_UPLOADS_CALL)
    fence_open = text.rindex("```bash", 0, at)
    start = text.rindex("\n\n", 0, fence_open - 1)
    fence_close = text.index("```", at)
    after = text.index("\n\n", fence_close + 3)
    end = text.find("\n\n", after + 2)
    return text[start : end if end != -1 else len(text)]


@pytest.mark.parametrize("skill", ["market-sizing", "competitive-positioning", "deck-review"])
def test_each_uploads_caller_states_a_reason_true_on_every_host(skill: str) -> None:
    """Each caller branches on exit 3 and states why it happens in words true on both hosts that reach it:
    the plain CLI, and the cloud lane before anything is attached (where "no session tree" was false)."""
    step = _uploads_step(skill)
    flat = " ".join(step.split()).lower()
    assert "exit 3" in flat, f"{skill}: no exit-3 branch beside the --uploads call"
    assert "session tree" not in flat, f"{skill}: the exit-3 reason still says 'no session tree'"
    assert "nothing was attached" in flat or "nothing has been attached" in flat, skill
    assert "keeps uploads elsewhere" in flat, skill
    assert "path" in flat, f"{skill}: exit 3 must say to ask for a path"
    if skill == "deck-review":
        assert "if the request already names the deck's path, use it" in flat, skill
    else:
        # The review must still see the founder's documents, and an unattended host must not stall on a
        # question it can answer itself: copy what was read earlier, ask only with no path at all.
        assert "copy into `$handoff_dir/docs` the founder documents you read earlier" in flat, skill
        assert "ask for a path only if you never had one" in flat, skill


def test_deck_review_lists_the_uploads_folder_only_when_one_was_printed() -> None:
    """deck-review listed `<printed UPLOADS_DIR>` unconditionally, a path never printed on exit 3."""
    flat = " ".join(_uploads_step("deck-review").split())
    assert "On exit 0, `ls -la <printed UPLOADS_DIR>`" in flat
    assert "On exit 3 nothing was printed" in flat


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


# ---------------------------------------------------------------------------
# Host-loop: the agent process does not run in the outputs dir and a RELATIVE file-tool path is
# refused, so the agent namespace must be the ABSOLUTE file-tool path of the outputs folder. Only the
# model knows it; the main thread supplies it once and a probe written by its file tool PROVES it.
# ---------------------------------------------------------------------------

_REAL_RESOLVE_ROOTS = _mod.resolve_roots
_HOST = "/Users/u/Library/Application Support/Claude/local-agent-mode-sessions/o/u/1a2b3c4d/outputs"


def test_host_outputs_dir_shape_accepts_the_production_path_with_a_space() -> None:
    assert _mod.normalize_host_outputs_dir(_HOST) == (_HOST, None)
    assert _mod.normalize_host_outputs_dir(_HOST + "/") == (_HOST, None)
    # The harness layout ends in mnt/outputs; same rule.
    assert _mod.normalize_host_outputs_dir("/tmp/run/mnt/outputs")[0] == "/tmp/run/mnt/outputs"


def test_host_outputs_dir_shape_rejects_what_the_file_tools_would_refuse_or_misplace() -> None:
    for bad in ("artifacts", "outputs", _HOST + "/artifacts", "/a/outputs\n/b/outputs"):
        normalized, reason = _mod.normalize_host_outputs_dir(bad)
        assert normalized is None and reason, bad


def test_verify_probe_distinguishes_absent_from_wrong(tmp_path: Path) -> None:
    code, detail = _mod.verify_probe(str(tmp_path), _HOST)
    assert code == _mod.EXIT_PROBE_MISSING and _mod.PROBE_NAME in detail
    (tmp_path / _mod.PROBE_NAME).write_text("/elsewhere/outputs\n", encoding="utf-8")
    assert _mod.verify_probe(str(tmp_path), _HOST)[0] == _mod.EXIT_PROBE_MISMATCH
    (tmp_path / _mod.PROBE_NAME).write_text(_HOST + "\n", encoding="utf-8")
    assert _mod.verify_probe(str(tmp_path), _HOST) == (0, "ok")


def test_persisted_value_round_trips_and_a_malformed_file_reads_as_absent(tmp_path: Path) -> None:
    assert _mod.read_persisted(str(tmp_path)) is None
    _mod.write_persisted(str(tmp_path), _HOST)
    assert _mod.read_persisted(str(tmp_path)) == _HOST
    for junk in ("not json", '{"host_outputs_dir": "relative/outputs"}', '["x"]'):
        (tmp_path / _mod.PERSIST_NAME).write_text(junk, encoding="utf-8")
        assert _mod.read_persisted(str(tmp_path)) is None, junk


def test_a_proven_host_path_makes_the_agent_root_absolute_on_every_session_shape() -> None:
    for cwd in ("/sessions/abc", "/sessions/abc/mnt", "/sessions/abc/mnt/outputs"):
        root, agent = resolve_roots(cwd, {}, _HOST)
        assert root == "/sessions/abc/mnt/outputs/artifacts"
        assert agent == _HOST + "/artifacts"


def test_the_declared_override_still_beats_a_proven_host_path() -> None:
    _, agent = resolve_roots("/sessions/abc", {"COWORK_AGENT_ARTIFACTS_ROOT": "/declared"}, _HOST)
    assert agent == "/declared"


def test_off_a_session_tree_the_host_path_is_ignored(tmp_path: Path) -> None:
    root, agent = resolve_roots(str(tmp_path), {}, _HOST)
    assert root == agent == os.path.join(str(tmp_path), "artifacts")


def _session_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], keep_agent_env: bool = False
) -> tuple[int, str, str, list[str]]:
    """Run main() as if the shell sat at /sessions/abc, with that tree's outputs mapped onto tmp_path.

    Literal /sessions/ dirs cannot be created, so the resolver's own resolve_roots is wrapped to relocate
    the ABSOLUTE root. `used` records every relocation: a test that asserts on the result must also see it
    non-empty, or the mapping did not engage and the test proved nothing.
    """
    import contextlib
    import io

    real = _REAL_RESOLVE_ROOTS  # never the wrapper a previous call in the same test installed
    used: list[str] = []

    def mapped(cwd: str, env: dict[str, str], host_outputs_dir: str | None = None) -> tuple[str, str]:
        root, agent = real(cwd, env, host_outputs_dir)
        prefix = "/sessions/abc/mnt/outputs"
        if root.startswith(prefix):
            used.append(root)
            root = str(tmp_path / "outputs") + root[len(prefix) :]
        return root, agent

    monkeypatch.setattr(_mod, "resolve_roots", mapped)
    monkeypatch.setattr(_mod.os, "getcwd", lambda: "/sessions/abc")
    monkeypatch.delenv("COWORK_ARTIFACTS_ROOT", raising=False)
    if not keep_agent_env:
        monkeypatch.delenv("COWORK_AGENT_ARTIFACTS_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", ["resolve_artifacts_root.py", *argv])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = _mod.main()
        except SystemExit as e:  # argparse
            rc = int(e.code or 0)
    return rc, out.getvalue(), err.getvalue(), used


def test_set_host_outputs_dir_proves_persists_and_later_calls_print_absolute_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = tmp_path / "outputs" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / _mod.PROBE_NAME).write_text(_HOST, encoding="utf-8")  # what the file tool wrote

    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--set-host-outputs-dir", _HOST + "/"])
    assert used, "the /sessions -> tmp_path mapping never engaged"
    assert rc == 0, err
    assert out.strip() == _HOST + "/artifacts"
    assert _mod.read_persisted(str(artifacts)) == _HOST

    # A later fresh shell reads the persisted value: absolute paths, and no relative-root warning.
    rc, out, err, used = _session_main(
        monkeypatch, tmp_path, ["--handoff-dir-agent", "--dir-name", "market-sizing-acme", "--run-id", "R1"]
    )
    assert used and rc == 0, err
    assert out.strip() == f"{_HOST}/artifacts/market-sizing-acme/handoff/R1"
    assert "RELATIVE" not in err


def test_set_host_outputs_dir_refuses_without_the_probe_and_persists_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--set-host-outputs-dir", _HOST])
    assert used, "the /sessions -> tmp_path mapping never engaged"
    assert rc == _mod.EXIT_PROBE_MISSING
    diag = json.loads(out)
    assert diag["code"] == "probe_missing"
    assert diag["shell_outputs_dir"] == str(tmp_path / "outputs")
    assert _mod.read_persisted(str(tmp_path / "outputs" / "artifacts")) is None


def test_set_host_outputs_dir_refuses_a_value_that_differs_from_the_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = tmp_path / "outputs" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / _mod.PROBE_NAME).write_text(_HOST, encoding="utf-8")
    typo = _HOST.replace("1a2b3c4d", "1a2b3c4e")
    rc, out, _, used = _session_main(monkeypatch, tmp_path, ["--set-host-outputs-dir", typo])
    assert used and rc == _mod.EXIT_PROBE_MISMATCH
    assert json.loads(out)["code"] == "probe_mismatch"
    assert _mod.read_persisted(str(artifacts)) is None


def test_set_host_outputs_dir_refuses_a_bad_shape_before_touching_the_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, out, _, _ = _session_main(monkeypatch, tmp_path, ["--set-host-outputs-dir", "artifacts"])
    assert rc == _mod.EXIT_BAD_HOST_DIR
    assert json.loads(out)["code"] == "bad_host_outputs_dir"


def test_without_a_proven_path_an_agent_call_refuses_instead_of_printing_a_relative_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for flags in (["--agent"], ["--json"], ["--handoff-dir-agent", "--dir-name", "x", "--run-id", "R"]):
        rc, out, err, used = _session_main(monkeypatch, tmp_path, flags)
        assert used, "the /sessions -> tmp_path mapping never engaged"
        assert rc == _mod.EXIT_NOT_PROVEN, (flags, out, err)
        diag = json.loads(out)
        assert diag["code"] == "host_outputs_dir_not_proven"
        assert diag["shell_outputs_dir"] == str(tmp_path / "outputs")
        assert "artifacts\n" not in out, "a relative root must never be printed"


def test_without_a_proven_path_the_plain_root_still_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only agent-namespace calls need the proof: the absolute root is the shell's own path."""
    rc, out, _, used = _session_main(monkeypatch, tmp_path, [])
    assert used and rc == 0
    assert out.strip() == str(tmp_path / "outputs" / "artifacts")


def test_a_declared_agent_root_needs_no_proof(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--agent"])
    assert rc == _mod.EXIT_NOT_PROVEN  # control: without the declaration it refuses
    monkeypatch.setenv("COWORK_AGENT_ARTIFACTS_ROOT", "/declared/artifacts")
    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--agent"], keep_agent_env=True)
    assert used and rc == 0, err
    assert out.strip() == "/declared/artifacts"


def test_set_host_outputs_dir_is_a_no_op_off_a_session_tree(tmp_path: Path) -> None:
    root = str(tmp_path / "artifacts")
    rc, out, err = _run_cli(["--set-host-outputs-dir", _HOST], {"COWORK_ARTIFACTS_ROOT": root})
    assert rc == 0, err
    payload = json.loads(out)
    assert payload == {"code": "not_needed", "agent_artifacts_root": os.path.abspath(root)}
    assert not (tmp_path / "artifacts" / _mod.PERSIST_NAME).exists()


def test_vm_loop_a_sessions_path_is_proven_by_the_probe_and_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On a VM-loop tier the file tools take the shell's own `/sessions/...` paths and no "Paths in bash
    differ" list exists. The shape rule must not reject that path: the probe is the test. Proven -> the
    agent root is that absolute path; unproven -> the agent call still refuses."""
    vm_outputs = "/sessions/abc/mnt/outputs"
    assert _mod.normalize_host_outputs_dir(vm_outputs) == (vm_outputs, None)

    rc, out, _, used = _session_main(monkeypatch, tmp_path, ["--agent"])
    assert used and rc == _mod.EXIT_NOT_PROVEN  # unproven: refuses

    artifacts = tmp_path / "outputs" / "artifacts"
    (artifacts / _mod.PROBE_NAME).write_text(vm_outputs, encoding="utf-8")  # the VM file tool's write
    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--set-host-outputs-dir", vm_outputs])
    assert used and rc == 0, err
    assert out.strip() == vm_outputs + "/artifacts"
    rc, out, err, used = _session_main(monkeypatch, tmp_path, ["--agent"])
    assert used and rc == 0, err
    assert out.strip() == vm_outputs + "/artifacts"
