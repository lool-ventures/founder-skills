#!/usr/bin/env python3
"""Extract one release's notes, or its title, from CHANGELOG.md.

ONE COPY, TWO CALLERS, and that is the point. `publish-release` uses this to build the notes it
publishes, and `verify-release-notes` uses it to rehearse that without publishing. If the two paths
had their own copies they would drift, and the rehearsal would stop testing the thing that runs.

It is a file rather than a heredoc so it can also be run locally and covered by the normal test
suite -- `tests/test_release_notes.py` runs it against the real CHANGELOG, so the extractor is
checked on every push instead of first executing at the moment of a release.

Exits NON-ZERO when the section is missing or empty. A Release with empty notes is worse than no
Release, because it looks done.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


def _section(changelog: str, version: str) -> re.Match[str] | None:
    # Runs to the next `## [` heading, or to end-of-file so the oldest entry also matches.
    return re.search(
        rf"^## \[{re.escape(version)}\]([^\n]*)\n(.*?)(?=^## \[|\Z)",
        changelog,
        re.S | re.M,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Extract release notes or title from CHANGELOG.md")
    p.add_argument("tag", help="tag or bare version, e.g. v0.10.0 or 0.10.0")
    p.add_argument("--title", action="store_true", help="print the heading text instead of the body")
    p.add_argument("--changelog", default="CHANGELOG.md")
    args = p.parse_args()

    version = args.tag.lstrip("v")
    try:
        text = pathlib.Path(args.changelog).read_text(encoding="utf-8")
    except OSError as e:
        print(f"::error::cannot read {args.changelog}: {e}", file=sys.stderr)
        return 1

    m = _section(text, version)
    if not m:
        print(f"::error::no CHANGELOG section for {version} — refusing to publish empty notes", file=sys.stderr)
        return 1

    if args.title:
        # MUST MATCH THE EIGHT RELEASES ALREADY PUBLISHED BY HAND: `vX.Y.Z — <title>`.
        # This emitted `[0.10.0] - 2026-08-26 — <title>` — bracketed, no `v`, with the changelog's
        # date pasted into the public "Latest" badge — because it echoed the heading verbatim. The
        # heading tail is ` - <date> — <title>`; keep only the em-dash clause, and fall back to a
        # bare `vX.Y.Z` for an older heading that carries no title at all.
        tail = m.group(1)
        suffix = ""
        if "—" in tail:
            suffix = " — " + tail.split("—", 1)[1].strip()
        sys.stdout.write(f"v{version}{suffix}\n")
        return 0

    body = m.group(2).strip()
    # A `## [` INSIDE the body — a heading quoted in a fenced block — ends the lookahead early and
    # publishes a SILENTLY TRUNCATED note with exit 0. That is worse than the empty note this script
    # exists to prevent, because nothing looks wrong. The precise signature is an UNCLOSED fence:
    # cutting inside one leaves an odd number of ``` markers. Latent today; the guard is one count.
    if body.count("```") % 2:
        print(
            f"::error::CHANGELOG section for {version} ends inside an unclosed ``` fence — it was "
            "probably truncated by a '## [' quoted in the body; refusing to publish a partial note",
            file=sys.stderr,
        )
        return 1
    if not body:
        print(f"::error::CHANGELOG section for {version} is empty — refusing to publish it", file=sys.stderr)
        return 1
    sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
