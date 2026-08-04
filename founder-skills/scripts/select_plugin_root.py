#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
r"""Deterministically select ONE plugin root out of several candidate mounts.

WHY THIS EXISTS: in Cowork, `${CLAUDE_PLUGIN_ROOT}` resolves to a host-side path that does not
exist inside the session VM shell, so every skill's Step 0 self-heals by running
`find / -type d -path '*/skills/<skill>/scripts' | head -1`. That `find` can turn up MULTIPLE
mounts of the same plugin at once — a stale host-side cache, a test marketplace, a prod
marketplace, even (measured) a symlink into a different session's plugin tree entirely — and
`head -1` picks whichever one the filesystem happens to walk to first. Nothing about that pick is
stable: the same session, re-running `find` in a fresh shell, can land on a different candidate
next time. A run can silently mix scripts across plugin versions mid-pipeline.

This script replaces "pick the first `find` result" with a small, deterministic, LOUD selection
policy: prefer an exact version match when the caller knows what version it expects; if more than
one candidate matches, break the tie by sorting candidate paths and always report the tie by name;
if nothing matches (or no expectation was given), fall back to the first candidate as given,
and say so. It never guesses "highest version wins" — a higher version turning up in a stale
host-side cache is a tree the session never installed, so picking it would be confidently wrong
rather than merely arbitrary.

INVOCATION CONTRACT
--------------------
Input:  candidate SCRIPT DIRECTORIES (i.e. `find`'s own output, one path per line) on **stdin**.
        Reading from stdin, not argv, is deliberate: a host-side Cowork path can contain a space
        (e.g. `.../Application Support/...`), and argv would word-split it. Blank lines are
        ignored. Each candidate is expected to look like `<plugin-root>/skills/<skill>/scripts`;
        the plugin root is derived by stripping the trailing `skills/<skill>/scripts` segment.

Flags:
    --expect-version X   Prefer the candidate whose `<root>/.claude-plugin/plugin.json#version`
                          equals X. Optional.
    --json                Emit a structured JSON object on stdout instead of the bare path
                          (selected root/path/version, plus the rejected candidates and the
                          reason for the pick). Optional; default stdout stays a bare path so a
                          shell can `ROOT="$(select_plugin_root.py < candidates.txt)"` verbatim.

Output:
    stdout: the selected plugin ROOT (not the scripts dir), one line, nothing else — unless
            --json was given, in which case a single JSON object.
    stderr: one line per REJECTED candidate (`rejected: <path> (version: <version-or-unknown>)`),
            plus exactly one summary line naming why the winner won (exact match / tie / no
            match / no --expect-version given). Concise and always emitted, even on a clean
            single-candidate run, so a duplicate mount is visible instead of silently absorbed.

Exit codes:
    0   a candidate was selected; its root is on stdout.
    1   stdin was empty (no candidate lines), or no candidate had a derivable/readable plugin
        root at all. A clear message goes to stderr; nothing is printed on stdout.

Selection policy (in order):
    1. `--expect-version X` given and EXACTLY ONE candidate's `plugin.json#version == X`
       -> select it.
    2. `--expect-version X` given and MORE THAN ONE candidate matches
       -> sort the matching candidates by their path STRING and take the first; report every
          tied candidate by name on stderr. Deterministic, never silent.
    3. `--expect-version` absent, or given but no candidate matches
       -> select the first candidate as given on stdin; report on stderr that no version match
          was found (or that none was requested).

A candidate whose plugin root can't be derived, whose `plugin.json` is missing, unreadable, or
unparseable, or that has no `version` field is treated as version `"unknown"` and kept in the
pool for the fallback rules above — never a crash, never silently dropped from view.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TypedDict


class Candidate(TypedDict):
    path: str  # the candidate scripts-dir line exactly as given on stdin
    root: str  # derived plugin root, "" if it could not be derived at all
    version: str | None  # plugin.json#version, or None ("unknown") if unreadable/missing


def derive_plugin_root(scripts_dir: str) -> str:
    """`<root>/skills/<skill>/scripts` -> `<root>`.

    Pure string manipulation (three levels up), matching the documented mount shape. Degenerate
    inputs (too shallow to have three path segments) collapse to "" rather than raising, so the
    caller can treat them as "no readable root" instead of crashing.
    """
    norm = os.path.normpath(scripts_dir)
    parent = os.path.dirname(norm)
    grandparent = os.path.dirname(parent)
    root = os.path.dirname(grandparent)
    if not root or root == norm:
        return ""
    return root


def read_plugin_version(root: str) -> str | None:
    """Read `<root>/.claude-plugin/plugin.json#version`. Never raises: any failure (missing dir,
    missing file, unreadable, broken symlink, invalid JSON, non-dict content, missing/non-string
    version) is reported as None, the caller's "unknown" sentinel."""
    if not root:
        return None
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    try:
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    return version if isinstance(version, str) and version else None


def _fmt(c: Candidate) -> str:
    return f"{c['path']} (version: {c['version'] or 'unknown'})"


def build_candidates(lines: list[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for line in lines:
        root = derive_plugin_root(line)
        out.append({"path": line, "root": root, "version": read_plugin_version(root)})
    return out


def select(candidates: list[Candidate], expect_version: str | None) -> tuple[Candidate, list[Candidate], str]:
    """Returns (selected, rejected, summary_note). Raises ValueError if no candidate has a
    readable (derivable) root at all — the caller maps that to exit 1."""
    usable = [c for c in candidates if c["root"]]
    if not usable:
        raise ValueError("no candidate had a readable plugin root")

    if expect_version:
        matches = [c for c in usable if c["version"] == expect_version]
        if len(matches) == 1:
            selected = matches[0]
            note = f"exact match for --expect-version {expect_version}: {_fmt(selected)}"
        elif len(matches) > 1:
            tied_sorted = sorted(matches, key=lambda c: c["path"])
            selected = tied_sorted[0]
            tied_list = ", ".join(_fmt(c) for c in tied_sorted)
            note = (
                f"tie: {len(tied_sorted)} candidates match --expect-version "
                f"{expect_version}: [{tied_list}]; selected {selected['path']} by path sort"
            )
        else:
            selected = usable[0]
            note = (
                f"no candidate matched --expect-version {expect_version}; "
                f"using first candidate on stdin: {_fmt(selected)}"
            )
    else:
        selected = usable[0]
        note = f"no --expect-version given; using first candidate on stdin: {_fmt(selected)}"

    rejected = [c for c in candidates if c is not selected]
    return selected, rejected, note


def main() -> int:
    p = argparse.ArgumentParser(
        description="Deterministically select one plugin root from candidate script-dir mounts "
        "read on stdin (one per line)."
    )
    p.add_argument(
        "--expect-version",
        default=None,
        help="Prefer the candidate whose plugin.json#version equals this value.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a structured JSON object on stdout instead of the bare selected root.",
    )
    args = p.parse_args()

    lines = [line.rstrip("\n").rstrip("\r") for line in sys.stdin]
    lines = [line for line in lines if line.strip()]

    if not lines:
        sys.stderr.write("select_plugin_root: no candidate paths provided on stdin\n")
        return 1

    candidates = build_candidates(lines)

    try:
        selected, rejected, note = select(candidates, args.expect_version)
    except ValueError as exc:
        sys.stderr.write(f"select_plugin_root: {exc}\n")
        return 1

    for c in rejected:
        sys.stderr.write(f"rejected: {_fmt(c)}\n")
    sys.stderr.write(f"select_plugin_root: {note}\n")

    if args.json:
        payload = {
            "root": selected["root"],
            "path": selected["path"],
            "version": selected["version"],
            "rejected": [{"path": c["path"], "root": c["root"], "version": c["version"]} for c in rejected],
            "note": note,
        }
        sys.stdout.write(json.dumps(payload) + "\n")
    else:
        sys.stdout.write(selected["root"] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
