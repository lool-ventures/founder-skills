"""The release-note extractor, checked on every push instead of first at a release.

`publish-release` builds a GitHub Release's body from a CHANGELOG section. Before this existed
that code path first executed at the moment of a tag push — the worst time to find out it is
wrong, because the failure lands on a release rather than before one. These run the real script
against the real CHANGELOG.

The property that matters most is the NEGATIVE one: a missing or empty section must exit non-zero
rather than produce nothing. A Release with empty notes is worse than no Release, because it looks
done.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "changelog-notes.py"
CHANGELOG = REPO / "CHANGELOG.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO)


def _released_versions() -> list[str]:
    """Every version heading in the changelog, newest first. Excludes an Unreleased section."""
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), re.M)


def test_the_script_exists_where_the_workflow_calls_it() -> None:
    """The workflow invokes it by path; a rename would break the release and nothing else."""
    assert SCRIPT.is_file(), f"{SCRIPT} is missing — publish-release calls it by path"
    wf = (REPO / ".github" / "workflows" / "skill-quality.yml").read_text(encoding="utf-8")
    assert ".github/scripts/changelog-notes.py" in wf


def test_every_released_version_yields_non_empty_notes() -> None:
    """Run against every section actually in the file, not a fixture.

    A fixture would only prove the regex works on a shape someone invented; the real changelog is
    the input the release path gets.
    """
    versions = _released_versions()
    assert versions, "no version headings found — the regex or the changelog format changed"
    for v in versions:
        p = _run(v)
        assert p.returncode == 0, f"{v}: exit {p.returncode}, stderr={p.stderr.strip()}"
        assert p.stdout.strip(), f"{v}: produced empty notes"
        t = _run(v, "--title")
        assert t.returncode == 0 and v in t.stdout, f"{v}: title extraction failed"


def test_a_leading_v_is_accepted() -> None:
    """The workflow passes `$GITHUB_REF_NAME`, which is `v0.10.0`, not `0.10.0`."""
    newest = _released_versions()[0]
    assert _run(f"v{newest}").stdout == _run(newest).stdout


def test_a_missing_version_exits_non_zero() -> None:
    """The load-bearing negative: refuse rather than publish nothing."""
    p = _run("v99.99.99")
    assert p.returncode != 0
    assert "no CHANGELOG section" in p.stderr


def test_an_empty_section_exits_non_zero(tmp_path: pathlib.Path) -> None:
    """A heading with no body must refuse too — the case a mid-edit changelog produces."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# Changelog\n\n## [9.9.9] - 2026-01-01 — Title\n\n## [9.9.8] - 2025-01-01\n\nreal\n")
    p = _run("v9.9.9", "--changelog", str(cl))
    assert p.returncode != 0, "an empty section must not publish"
    assert "is empty" in p.stderr


def test_the_oldest_section_is_extractable(tmp_path: pathlib.Path) -> None:
    """The last section has no following `## [` to stop at — it must match to end-of-file."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# Changelog\n\n## [9.9.9] - 2026-01-01 — T\n\nbody of the last one\n")
    p = _run("v9.9.9", "--changelog", str(cl))
    assert p.returncode == 0 and "body of the last one" in p.stdout
