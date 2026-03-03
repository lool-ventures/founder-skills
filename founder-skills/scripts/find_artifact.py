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

Exit codes:
    0 = found (path on stdout)
    1 = not found
    2 = ambiguous (multiple matches, need --slug)
"""

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resolve artifact paths")
    p.add_argument("--skill", required=True, help="Skill name (e.g., market-sizing)")
    p.add_argument("--artifact", required=True, help="Artifact filename (e.g., sizing.json)")
    p.add_argument("--slug", help="Company slug (optional; auto-detects if single match)")
    p.add_argument("--max-age-days", type=int, help="Reject artifacts older than N days")
    p.add_argument("--prefer", choices=["newest"], help="When multiple matches, prefer newest")
    p.add_argument(
        "--artifacts-root",
        default=os.path.join(os.getcwd(), "artifacts"),
        help="Override artifacts directory (default: ./artifacts)",
    )
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
    if exit_code == 0:
        sys.stdout.write(result + "\n")
    else:
        print(result, file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
