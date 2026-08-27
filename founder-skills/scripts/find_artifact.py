#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Resolve artifact paths by skill name, artifact filename, and optional company slug.

Usage:
    python find_artifact.py --skill market-sizing --artifact sizing.json --slug acme-corp
    python find_artifact.py --skill market-sizing --artifact sizing.json
    python find_artifact.py --skill market-sizing --artifact sizing.json --max-age-days 7

On success a JSON object {"path": "<resolved path>"} is written to stdout (or to
the file given by -o, with a receipt object emitted to stdout confirming the
write). Use --pretty for indented JSON.

Exit codes:
    0 = found (JSON {"path": ...} on stdout)
    1 = not found
    2 = ambiguous (multiple matches, need --slug)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def find_artifact(
    artifacts_root: str,
    skill: str,
    artifact: str,
    slug: str | None = None,
    max_age_days: int | None = None,
    prefer_newest: bool = False,
) -> tuple[int, str]:
    """Find an artifact. Returns (exit_code, path_or_message)."""
    if not os.path.isdir(artifacts_root):
        return 1, f"Artifacts root does not exist: {artifacts_root}"

    prefix = f"{skill}-"
    candidates: list[str] = []

    for entry in os.listdir(artifacts_root):
        if not entry.startswith(prefix):
            continue
        dir_path = os.path.join(artifacts_root, entry)
        if not os.path.isdir(dir_path):
            continue
        # Parse slug from dir name. Rerun convention: {skill}-{slug}--{run_id}
        # where run_id is a timestamp or sequence number. Double-dash separates
        # slug from run_id; slugs themselves use single-dashes only.
        remainder = entry[len(prefix) :]
        entry_slug = remainder.split("--", 1)[0] if "--" in remainder else remainder
        if slug and entry_slug != slug:
            continue
        artifact_path = os.path.join(dir_path, artifact)
        if not os.path.isfile(artifact_path):
            continue
        if max_age_days is not None:
            age_days = (time.time() - os.path.getmtime(artifact_path)) / 86400
            if age_days > max_age_days:
                print(
                    f"Artifact expired: {artifact_path} is {age_days:.0f} days old "
                    f"(older than {max_age_days} day limit)",
                    file=sys.stderr,
                )
                continue
        candidates.append(artifact_path)

    if not candidates:
        if slug:
            return 1, f"Not found: {skill}/{artifact} with slug '{slug}'"
        return 1, f"Not found: {skill}/{artifact}"

    if len(candidates) == 1:
        return 0, candidates[0]

    # Group candidates by slug to detect cross-slug ambiguity.
    # Same rerun parsing as above: {skill}-{slug}--{run_id}
    slugs_seen: set[str] = set()
    for c in candidates:
        dir_name = os.path.basename(os.path.dirname(c))
        remainder = dir_name[len(prefix) :]
        c_slug = remainder.split("--", 1)[0] if "--" in remainder else remainder
        slugs_seen.add(c_slug)

    if len(slugs_seen) > 1:
        # Multiple different slugs — always ambiguous, even with --prefer newest.
        # Cross-company resolution is never automatic (safety invariant).
        msg_lines = [
            f"Ambiguous: found {len(candidates)} matches across {len(slugs_seen)} companies. "
            f"Use --slug to disambiguate:"
        ]
        for c in sorted(candidates):
            msg_lines.append(f"  {c}")
        return 2, "\n".join(msg_lines)

    # Same slug, multiple directories (re-runs of the same skill)
    if prefer_newest:
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return 0, candidates[0]

    # Same slug, multiple dirs, no --prefer newest
    msg_lines = [f"Ambiguous: found {len(candidates)} matches. Use --prefer newest to pick latest:"]
    for c in sorted(candidates):
        msg_lines.append(f"  {c}")
    return 2, "\n".join(msg_lines)


def _default_artifacts_root() -> str:
    """The artifacts root to use when --artifacts-root is not passed.

    NOT `os.getcwd()/artifacts`. On a Cowork session tree the workspace shell's cwd is the BARE
    SESSION ROOT (cowork-harness >=2.4.0, measured against production 2026-08-27), so that guess
    resolves to `/sessions/<id>/artifacts` -- OUTSIDE `mnt/`, where a write is never delivered and
    nothing reports it. Every SKILL.md passes the flag explicitly, but "the flag is always passed"
    is a property of PROSE the agent paraphrases, which is the whole reason the resolver exists.

    Falls back to the old guess if the sibling import fails, so this stays a standalone script:
    a wrong default is strictly better than an unrunnable one, and on the plain CLI the two agree.
    """
    try:
        shared = os.path.dirname(os.path.abspath(__file__))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import resolve_artifacts_root  # type: ignore[import-not-found]

        return str(resolve_artifacts_root.resolve_artifacts_root(os.getcwd(), dict(os.environ)))
    except Exception:
        return os.path.join(os.getcwd(), "artifacts")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resolve artifact paths")
    p.add_argument("--skill", required=True, help="Skill name (e.g., market-sizing)")
    p.add_argument("--artifact", required=True, help="Artifact filename (e.g., sizing.json)")
    p.add_argument("--slug", help="Company slug (optional; auto-detects if single match)")
    p.add_argument("--max-age-days", type=int, help="Reject artifacts older than N days")
    p.add_argument("--prefer", choices=["newest"], help="When multiple matches, prefer newest")
    p.add_argument(
        "--artifacts-root",
        default=_default_artifacts_root(),
        help="Override artifacts directory (default: the resolved canonical root)",
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    p.add_argument("-o", "--output", help="Write output to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    exit_code, result = find_artifact(
        artifacts_root=args.artifacts_root,
        skill=args.skill,
        artifact=args.artifact,
        slug=args.slug,
        max_age_days=args.max_age_days,
        prefer_newest=(args.prefer == "newest"),
    )
    if exit_code != 0:
        # Not-found / ambiguous messages stay on stderr (human-readable).
        print(result, file=sys.stderr)
        sys.exit(exit_code)

    payload = {"path": result}
    indent = 2 if args.pretty else None
    out = json.dumps(payload, indent=indent) + "\n"

    if args.output:
        abs_path = os.path.abspath(args.output)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(out)
        receipt = {"written": abs_path, "bytes": len(out.encode("utf-8"))}
        sys.stdout.write(json.dumps(receipt) + "\n")
    else:
        sys.stdout.write(out)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
