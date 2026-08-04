"""Unit + CLI tests for the deterministic plugin-root selector.

The selector exists because a Cowork session's `find / -type d -path '*/skills/<skill>/scripts'`
can turn up MULTIPLE mounts of the same plugin (stale host cache, test + prod marketplace, even a
symlink into a different session's tree) and `head -1` picks arbitrarily. These tests lock the
selection policy: exact `--expect-version` match wins; a tie among matches is broken
deterministically by sorting candidate paths (never silently); no match / no flag falls back to
the first candidate as given; a higher version is NEVER preferred over an exact-version match.

Candidates are read on STDIN (never argv) because a real host-side Cowork path can contain a
space (`.../Application Support/...`), which argv would word-split.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "select_plugin_root.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("select_plugin_root", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
derive_plugin_root = _mod.derive_plugin_root
read_plugin_version = _mod.read_plugin_version
build_candidates = _mod.build_candidates
select = _mod.select


def _make_plugin(root: Path, version: str | None) -> Path:
    """Create `<root>/skills/some-skill/scripts` plus a `.claude-plugin/plugin.json` at `root`
    (omitted entirely when version is None, to exercise the missing-manifest path). Returns the
    scripts dir path (the shape `find` would emit)."""
    scripts_dir = root / "skills" / "some-skill" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    if version is not None:
        plugin_dir = root / ".claude-plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": version}))
    return scripts_dir


def _run_cli(stdin_text: str, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# derive_plugin_root / read_plugin_version — pure helpers
# ---------------------------------------------------------------------------


def test_derive_plugin_root_strips_skills_skill_scripts() -> None:
    assert derive_plugin_root("/a/b/skills/deck-review/scripts") == "/a/b"


def test_derive_plugin_root_degenerate_path_returns_empty() -> None:
    assert derive_plugin_root("scripts") == ""
    assert derive_plugin_root("") == ""


def test_read_plugin_version_missing_manifest_returns_none(tmp_path: Path) -> None:
    assert read_plugin_version(str(tmp_path)) is None


def test_read_plugin_version_invalid_json_returns_none(tmp_path: Path) -> None:
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("{not valid json")
    assert read_plugin_version(str(tmp_path)) is None


def test_read_plugin_version_missing_version_key_returns_none(tmp_path: Path) -> None:
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": "founder-skills"}))
    assert read_plugin_version(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# select() — the policy itself
# ---------------------------------------------------------------------------


def test_select_single_candidate(tmp_path: Path) -> None:
    scripts = _make_plugin(tmp_path / "root", "0.6.0")
    candidates = build_candidates([str(scripts)])
    selected, rejected, note = select(candidates, None)
    assert selected["root"] == str(tmp_path / "root")
    assert rejected == []


def test_select_expect_version_matches_one_of_two(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    candidates = build_candidates([str(s1), str(s2)])
    selected, rejected, note = select(candidates, "0.6.0")
    assert selected["root"] == str(tmp_path / "a")
    assert [r["root"] for r in rejected] == [str(tmp_path / "b")]
    assert "0.6.0" in note


def test_select_tie_is_deterministic_and_reported(tmp_path: Path) -> None:
    # Two candidates both report the SAME version (a realistic tie: identical plugin.json content
    # mounted at two different marketplace paths).
    s_z = _make_plugin(tmp_path / "zzz", "0.6.0")
    s_a = _make_plugin(tmp_path / "aaa", "0.6.0")
    candidates = build_candidates([str(s_z), str(s_a)])
    selected, rejected, note = select(candidates, "0.6.0")
    # Deterministic: the lexicographically-first PATH wins, regardless of stdin order.
    expected_root = str(tmp_path / "aaa")
    assert selected["root"] == expected_root
    assert "tie" in note
    assert str(s_z) in note and str(s_a) in note

    # Reversed stdin order must select the SAME candidate — the determinism guard.
    candidates_reversed = build_candidates([str(s_a), str(s_z)])
    selected2, _, _ = select(candidates_reversed, "0.6.0")
    assert selected2["root"] == expected_root


def test_select_no_expect_version_falls_back_to_first(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    candidates = build_candidates([str(s1), str(s2)])
    selected, rejected, note = select(candidates, None)
    assert selected["root"] == str(tmp_path / "a")
    assert "no --expect-version" in note


def test_select_expect_version_matches_nothing_falls_back_to_first(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    candidates = build_candidates([str(s1), str(s2)])
    selected, rejected, note = select(candidates, "9.9.9")
    assert selected["root"] == str(tmp_path / "a")
    assert "no candidate matched" in note


def test_select_unknown_version_candidate_not_crash_not_selected_over_match(tmp_path: Path) -> None:
    good = _make_plugin(tmp_path / "good", "0.6.0")
    broken_dir = tmp_path / "broken"
    (broken_dir / "skills" / "some-skill" / "scripts").mkdir(parents=True)
    # No .claude-plugin/plugin.json at all under "broken".
    broken_scripts = broken_dir / "skills" / "some-skill" / "scripts"
    candidates = build_candidates([str(broken_scripts), str(good)])
    assert candidates[0]["version"] is None  # unknown, not a crash
    selected, rejected, note = select(candidates, "0.6.0")
    assert selected["root"] == str(tmp_path / "good")
    assert any(r["version"] is None for r in rejected)


def test_select_higher_version_not_preferred_over_expect_version_match(tmp_path: Path) -> None:
    # Regression guard: a stale host-side cache can carry a HIGHER version than the session
    # actually installed. Selection must never fall back to "highest version wins".
    higher = _make_plugin(tmp_path / "higher", "0.7.0")
    expected = _make_plugin(tmp_path / "expected", "0.6.0")
    candidates = build_candidates([str(higher), str(expected)])
    selected, rejected, note = select(candidates, "0.6.0")
    assert selected["root"] == str(tmp_path / "expected")
    assert selected["version"] == "0.6.0"


def test_select_empty_candidate_list_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        select([], None)


# ---------------------------------------------------------------------------
# CLI (subprocess) — exercises stdin parsing, argparse, exit codes, stdout/stderr shape.
# ---------------------------------------------------------------------------


def test_cli_single_candidate_selected(tmp_path: Path) -> None:
    scripts = _make_plugin(tmp_path / "root", "0.6.0")
    rc, out, err = _run_cli(str(scripts) + "\n", [])
    assert rc == 0
    assert out.strip() == str(tmp_path / "root")


def test_cli_expect_version_matches_one_other_named_on_stderr(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    rc, out, err = _run_cli(f"{s1}\n{s2}\n", ["--expect-version", "0.6.0"])
    assert rc == 0
    assert out.strip() == str(tmp_path / "a")
    assert str(s2) in err
    assert "0.5.922" in err


def test_cli_tie_reported_and_deterministic_across_stdin_order(tmp_path: Path) -> None:
    s_z = _make_plugin(tmp_path / "zzz", "0.6.0")
    s_a = _make_plugin(tmp_path / "aaa", "0.6.0")
    expected_root = str(tmp_path / "aaa")

    rc1, out1, err1 = _run_cli(f"{s_z}\n{s_a}\n", ["--expect-version", "0.6.0"])
    rc2, out2, err2 = _run_cli(f"{s_a}\n{s_z}\n", ["--expect-version", "0.6.0"])

    assert rc1 == 0 and rc2 == 0
    assert out1.strip() == expected_root
    assert out2.strip() == expected_root
    assert "tie" in err1 and "tie" in err2


def test_cli_no_expect_version_uses_first_and_notes_on_stderr(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    rc, out, err = _run_cli(f"{s1}\n{s2}\n", [])
    assert rc == 0
    assert out.strip() == str(tmp_path / "a")
    assert "no --expect-version" in err


def test_cli_expect_version_matches_nothing_falls_back_exit0(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    rc, out, err = _run_cli(f"{s1}\n", ["--expect-version", "9.9.9"])
    assert rc == 0
    assert out.strip() == str(tmp_path / "a")
    assert "no candidate matched" in err


def test_cli_candidate_path_with_space_handled(tmp_path: Path) -> None:
    spacey_root = tmp_path / "Application Support" / "Claude"
    scripts = _make_plugin(spacey_root, "0.6.0")
    rc, out, err = _run_cli(str(scripts) + "\n", [])
    assert rc == 0
    assert out.strip() == str(spacey_root)


def test_cli_empty_stdin_exit1() -> None:
    rc, out, err = _run_cli("", [])
    assert rc == 1
    assert out == ""
    assert err.strip() != ""


def test_cli_blank_lines_ignored(tmp_path: Path) -> None:
    scripts = _make_plugin(tmp_path / "root", "0.6.0")
    rc, out, err = _run_cli(f"\n\n{scripts}\n\n", [])
    assert rc == 0
    assert out.strip() == str(tmp_path / "root")


def test_cli_json_output_shape(tmp_path: Path) -> None:
    s1 = _make_plugin(tmp_path / "a", "0.6.0")
    s2 = _make_plugin(tmp_path / "b", "0.5.922")
    rc, out, err = _run_cli(f"{s1}\n{s2}\n", ["--expect-version", "0.6.0", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["root"] == str(tmp_path / "a")
    assert payload["version"] == "0.6.0"
    assert len(payload["rejected"]) == 1
    assert payload["rejected"][0]["root"] == str(tmp_path / "b")
