"""The `### Scoring changes` contract, checked at tag time by `.github/scripts/scoring_changes_check.py`.

A downstream consumer reads every such section between two versions to explain score changes, so a
missing heading, a "None." over a changed scorer, or an unnamed skill all reach it as a wrong
explanation. The negatives below run the real checker against real git repos built in `tmp_path`.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "scoring_changes_check.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("scoring_changes_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk: Any = _load()

SCORER = "founder-skills/skills/deck-review/scripts/checklist.py"
OTHER = "founder-skills/skills/deck-review/scripts/visualize.py"
SHARED = "founder-skills/references/benchmarks.md"


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _changelog(body: str, newest: str = "0.16.1", prev: str = "0.16.0") -> str:
    return f"# Changelog\n\n## [{newest}] - 2026-10-06 — T\n\n{body}\n\n## [{prev}] - 2026-10-05 — P\n\nold\n"


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A repo tagged v0.16.0 holding the registry's files, so a later edit is a real diff."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    for rel in (SCORER, OTHER, SHARED):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("v1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "tag", "v0.16.0")
    return tmp_path


def _edit_and_commit(repo: pathlib.Path, rel: str) -> None:
    (repo / rel).write_text("v2\n")
    _git(repo, "commit", "-q", "-am", "edit")


def _run(repo: pathlib.Path, changelog: str, tag: str | None = None) -> str:
    return str(chk.run(repo, changelog, tag))


# ---- registry ---------------------------------------------------------------------------------------


def test_every_registry_path_exists() -> None:
    """A renamed scorer would otherwise drop out of the registry with nothing noticing."""
    missing = [p for paths in chk.SCORING_FILES.values() for p in paths if not (REPO / p).is_file()]
    assert not missing, f"scoring registry names files that do not exist: {missing}"


def test_registry_covers_every_analysis_skill() -> None:
    skills = {p.name for p in (REPO / "founder-skills" / "skills").iterdir() if p.is_dir()} - {"feedback"}
    assert set(chk.SCORING_FILES) == skills
    assert set(chk.SKILL_NAMES) == skills


# ---- the real CHANGELOG -----------------------------------------------------------------------------


def test_the_real_newest_section_carries_the_heading_once_the_contract_applies() -> None:
    """Structural only, deliberately WITHOUT git. This file runs in per-PR CI on a shallow checkout with
    no tags, where the range check would correctly fail -- so the range is checked only at tag time
    (pre-tag.sh and the tag job). Today the newest section is 0.16.0, exempt; from 0.16.1 on, the
    newest section must at least carry the heading."""
    newest, body = chk.sections((REPO / "CHANGELOG.md").read_text(encoding="utf-8"))[0]
    if chk._vtuple(newest) <= chk.EXEMPT_THROUGH:
        return
    assert chk.scoring_body(body) is not None, f"CHANGELOG {newest} has no `{chk.HEADING}` heading"


# ---- positives --------------------------------------------------------------------------------------


def test_none_is_fine_when_no_scoring_file_changed(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, OTHER)
    assert "present" in _run(repo, _changelog("### Scoring changes\n\nNone."))


def test_a_named_skill_passes_when_its_scorer_changed(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, SCORER)
    out = _run(repo, _changelog("### Scoring changes\n\n- **Deck review:** the market criterion now warns."))
    assert "changed since v0.16.0: 1" in out, out


def test_sections_at_or_before_0_16_0_are_exempt(repo: pathlib.Path) -> None:
    cl = "# Changelog\n\n## [0.16.0] - 2026-10-05 — P\n\nno heading here\n\n## [0.15.2] - x\n\nold\n"
    assert "exempt" in _run(repo, cl)


def test_an_existing_new_tag_bounds_the_range(repo: pathlib.Path) -> None:
    """With v<new> tagged, a later edit to a scorer is outside the release and does not count."""
    _edit_and_commit(repo, OTHER)
    _git(repo, "tag", "v0.16.1")
    _edit_and_commit(repo, SCORER)
    assert "present" in _run(repo, _changelog("### Scoring changes\n\nNone."))


# ---- seeded negatives -------------------------------------------------------------------------------


def test_missing_heading_fails(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, OTHER)
    with pytest.raises(chk.CheckError, match="no `### Scoring changes` heading"):
        _run(repo, _changelog("### Fixed\n\n- something"))


def test_a_renamed_heading_fails(repo: pathlib.Path) -> None:
    with pytest.raises(chk.CheckError, match="no `### Scoring changes` heading"):
        _run(repo, _changelog("### Scoring Changes\n\nNone."))


def test_none_fails_when_a_scorer_changed(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, SCORER)
    with pytest.raises(chk.CheckError, match="says 'None.'.* but scoring files changed"):
        _run(repo, _changelog("### Scoring changes\n\nNone.\n\n### Fixed\n\n- deck review fix"))


def test_an_uncommitted_scorer_edit_warns_but_is_not_judged(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before the tag exists the range ends at HEAD: committed changes only, exactly what CI will see
    once the tag is on HEAD. A dirty scorer (this tree is dirty by design) is reported, never failed."""
    (repo / SCORER).write_text("dirty\n")
    (repo / "founder-skills/skills/deck-review/scripts/new_scorer.py").write_text("x\n")
    assert "present" in _run(repo, _changelog("### Scoring changes\n\nNone."))
    err = capsys.readouterr().err
    assert "::warning::" in err and SCORER in err, err


def test_a_committed_scorer_change_is_judged_before_the_tag_exists(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, SCORER)
    with pytest.raises(chk.CheckError, match="says 'None.'"):
        _run(repo, _changelog("### Scoring changes\n\nNone."))


def test_an_unnamed_skill_fails(repo: pathlib.Path) -> None:
    _edit_and_commit(repo, SCORER)
    with pytest.raises(chk.CheckError, match="does not name 'deck review'"):
        _run(repo, _changelog("### Scoring changes\n\n- Market sizing: a criterion moved."))


def test_a_shared_file_names_exactly_the_skills_that_read_it(repo: pathlib.Path) -> None:
    """benchmarks.md is read by financial model review and competitive positioning, and only by them;
    an entry must name both, and naming them is enough (no "all skills", which would be false)."""
    _edit_and_commit(repo, SHARED)
    with pytest.raises(chk.CheckError, match="does not name 'competitive positioning'"):
        _run(repo, _changelog("### Scoring changes\n\n- Financial model review: seed benchmarks updated."))
    ok = "### Scoring changes\n\n- Financial model review and competitive positioning: seed benchmarks updated."
    assert "present" in _run(repo, _changelog(ok))
    readers = sorted(k for k, v in chk.SCORING_FILES.items() if SHARED in v)
    assert readers == ["competitive-positioning", "financial-model-review"], readers


def test_a_sub_heading_inside_the_section_is_part_of_its_body(repo: pathlib.Path) -> None:
    """`####` per-skill sub-headings must not end the body (it would read as empty, i.e. "None.")."""
    _edit_and_commit(repo, SCORER)
    body = "### Scoring changes\n\n#### Deck review\n\nThe market criterion now warns.\n\n### Fixed\n\n- x"
    assert "present" in _run(repo, _changelog(body))
    got = chk.scoring_body("### Scoring changes\n\n#### Deck review\n\ntext\n\n### Fixed\n\n- x")
    assert got == "#### Deck review\n\ntext", got


@pytest.mark.parametrize("empty", ["None.", "None", "none.", "No changes.", "no changes", "NO CHANGES"])
def test_every_spelling_of_nothing_changed_is_refused_over_a_changed_scorer(repo: pathlib.Path, empty: str) -> None:
    _edit_and_commit(repo, SCORER)
    with pytest.raises(chk.CheckError, match="says 'None.'"):
        _run(repo, _changelog(f"### Scoring changes\n\n{empty}"))


@pytest.mark.parametrize("empty", ["None", "No changes."])
def test_every_spelling_of_nothing_changed_is_accepted_when_nothing_did(repo: pathlib.Path, empty: str) -> None:
    _edit_and_commit(repo, OTHER)
    assert "present" in _run(repo, _changelog(f"### Scoring changes\n\n{empty}"))


def test_a_missing_previous_tag_fails_rather_than_skipping(repo: pathlib.Path) -> None:
    _git(repo, "tag", "-d", "v0.16.0")
    with pytest.raises(chk.CheckError, match="previous release tag v0.16.0 not found"):
        _run(repo, _changelog("### Scoring changes\n\nNone."))


def test_tagging_a_version_whose_section_is_not_written_fails(repo: pathlib.Path) -> None:
    """Else `pre-tag.sh v0.16.1` passes as "newest is 0.16.0, exempt" before 0.16.1 is written."""
    cl = "# Changelog\n\n## [0.16.0] - 2026-10-05 — P\n\nold\n"
    with pytest.raises(chk.CheckError, match="newest CHANGELOG section is 0.16.0"):
        _run(repo, cl, "v0.16.1")


def test_the_cli_exits_non_zero_with_an_error_line(repo: pathlib.Path) -> None:
    cl = repo / "CHANGELOG.md"
    cl.write_text(_changelog("### Fixed\n\n- x"))
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--changelog", str(cl)],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1 and p.stderr.startswith("::error::"), (p.returncode, p.stderr)


# ---- wiring -----------------------------------------------------------------------------------------


def test_the_check_is_wired_into_pre_tag_and_the_tag_job() -> None:
    pre_tag = (REPO / "scripts" / "pre-tag.sh").read_text(encoding="utf-8")
    assert ".github/scripts/scoring_changes_check.py" in pre_tag
    wf = (REPO / ".github" / "workflows" / "skill-quality.yml").read_text(encoding="utf-8")
    assert ".github/scripts/scoring_changes_check.py" in wf
    jobs = yaml.safe_load(wf)["jobs"]
    # The tag no longer runs the paid jobs; the check lives in the job that verifies the branch run.
    job = jobs["verify-branch-gate"]
    assert "verify-branch-gate" in jobs["publish-release"]["needs"], "the check must gate the Release"
    steps = job["steps"]
    assert any("scoring_changes_check.py" in str(s.get("run", "")) for s in steps)
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert (checkout.get("with") or {}).get("fetch-depth") == 0, "tags and history are needed for the range"
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scoring_changes_check" not in ci, "a tag-time check, deliberately not per-PR"
