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


def test_title_matches_the_format_of_every_release_published_by_hand() -> None:
    """`vX.Y.Z — <title>`, not the raw changelog heading.

    The extractor echoed the heading verbatim and emitted `[0.10.0] - 2026-08-26 — <title>` —
    bracketed, no `v`, with the changelog's DATE pasted into the public "Latest" badge. All eight
    releases published by hand use `vX.Y.Z — <title>`. The old test asserted only `version in output`,
    a substring check that is structurally blind to the format.
    """
    out = _run("v0.10.0", "--title").stdout.strip()
    assert out.startswith("v0.10.0 — "), out
    assert not out.startswith("["), f"raw changelog heading leaked into the release title: {out}"
    assert " - 20" not in out, f"changelog date leaked into the release title: {out}"


def test_title_falls_back_to_a_bare_version_when_the_heading_has_no_title() -> None:
    """An older heading carries no `— <title>`; emit `vX.Y.Z`, never `[X.Y.Z] - <date>`."""
    out = _run("v0.1.0", "--title").stdout.strip()
    assert out == "v0.1.0", out


def test_a_version_that_is_a_prefix_of_another_extracts_its_own_section(tmp_path: pathlib.Path) -> None:
    """The `\\]` anchor in the heading pattern is what makes this work, and nothing tested it.

    THE FIXTURE IS SYNTHETIC ON PURPOSE. The repo's own near-miss pair (0.1.0 / 0.10.0) does NOT
    collide even with the anchor removed — `\\[0\\.1\\.0` cannot match `[0.10.0]`, because the `.`
    after `1` meets a `0`. Asserting against the real changelog therefore proves nothing, and a first
    draft of this test did exactly that and passed against the mutated extractor.
    0.7.1 / 0.7.10 is a pair that genuinely collides: without the anchor, `\\[0\\.7\\.1` matches the
    `[0.7.10]` heading and `re.search` returns whichever appears first in the file.
    """
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(
        "# Changelog\n\n"
        "## [0.7.10] - 2026-02-02 — Ten\n\nbody of ten\n\n"
        "## [0.7.1] - 2026-01-01 — One\n\nbody of one\n",
        encoding="utf-8",
    )
    one = _run("v0.7.1", "--changelog", str(cl))
    ten = _run("v0.7.10", "--changelog", str(cl))
    assert one.returncode == 0 and ten.returncode == 0, (one.stderr, ten.stderr)
    assert "body of one" in one.stdout and "body of ten" not in one.stdout, one.stdout
    assert "body of ten" in ten.stdout and "body of one" not in ten.stdout, ten.stdout
    assert _run("v0.7.1", "--changelog", str(cl), "--title").stdout.strip() == "v0.7.1 — One"


def test_a_truncated_section_is_refused_rather_than_published(tmp_path: pathlib.Path) -> None:
    """A `## [` quoted inside a fenced block ends the lookahead early.

    That published a SILENTLY TRUNCATED note with exit 0 — worse than the empty note this script
    exists to prevent, because nothing looks wrong. The signature is an unclosed ``` fence.
    """
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(
        "# Changelog\n\n## [1.0.0] - 2026-01-01 — T\n\nintro\n\n```\n"
        "## [0.9.0] quoted in a code block\n```\n\ntail that must survive\n",
        encoding="utf-8",
    )
    r = _run("v1.0.0", "--changelog", str(cl))
    assert r.returncode == 1, f"published a truncated note: rc={r.returncode}, out={r.stdout!r}"
    assert "truncated" in r.stderr or "unclosed" in r.stderr
