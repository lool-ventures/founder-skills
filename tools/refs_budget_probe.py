#!/usr/bin/env python3
"""Reference-budget acceptance harness for cowork-harness `critique`.

Two modes, both free:

  baseline   read archived critique-evidence-package.txt files and report, per
             reference file, how many bytes actually SURVIVED into the evidence
             the evaluator graded (not merely which files were omitted).

  model      report whether a skill's content is cut at all, and — only if it
             breaches the ceiling — how the allocator would slice it.

AS OF cowork-harness 1.13.0 the allocation problem is largely GONE. Skill-authored
content — SKILL.md + every references/** file + agents/<skill>.md — ships WHOLE,
bounded only by a 512 KiB sanity ceiling across all three COMBINED. Allocation only
engages above that ceiling; below it nothing is cut.

So `model` now reports "ships whole" for any skill under the ceiling, and only
falls through to the slicing model above it. Reporting predicted cuts for a skill
that will not be cut is worse than reporting nothing.

The historical note stands for the above-ceiling path: under any fair allocation the
omission count goes to zero while every file can still be a useless sliver, so the
omission count is gamed by construction and must not be the acceptance metric alone.
`baseline` mode is unchanged and still reads archived packages.

Usage:
  python3 tools/refs_budget_probe.py baseline [--runs <glob>]
  python3 tools/refs_budget_probe.py model --skills-dir founder-skills/skills --cap 8192 --cap 32768
"""

from __future__ import annotations

import argparse
import glob as globmod
import pathlib
import re
import sys

PKG_GLOB = "~/.cowork-harness/runs/*/sess-crit-*/critique-evidence-package.txt"
SECTION = "references/ content"
OMIT = "(omitted — references/ content budget exhausted)"
# A truncated slice below this is treated as too small to be worth packaging.
THIN_BYTES = 2048

# FORMAT COUPLINGS — this tool reads an artifact it does not own. Three things
# must hold, and all three are the harness's to change:
#   0a. references/ ships EVERY file type, not just *.md — no extension filter.
#   0. the 512 KiB COMBINED ceiling and the fact that content ships whole below it
#      (`--ceiling` overrides). If that number moves, `model` is wrong until updated.
#   1. the OMIT marker text above, verbatim;
#   2. the "### <name>.md" per-file header shape inside the references section;
#   3. the section terminator: parse_package ends the references block at the
#      next "\n### [E-" armor head-tag. If the armor tag shape changes, the
#      section is read to EOF and byte counts inflate silently.
# If the allocator stops being classic surplus-redistribution water-filling,
# `water_fill` must be updated with it or `model` predictions stop matching.


def water_fill(sizes: dict[str, int], budget: int) -> dict[str, int]:
    """Equal share with surplus redistribution: small files complete, rest split the remainder."""
    remaining = dict(sizes)
    alloc = dict.fromkeys(sizes, 0)
    left = budget
    while left > 0 and remaining:
        share = left // len(remaining)
        if share == 0:
            break
        finished = []
        for name, need in list(remaining.items()):
            take = min(need, share)
            alloc[name] += take
            left -= take
            if take == need:
                finished.append(name)
            else:
                remaining[name] = need - take
        for name in finished:
            remaining.pop(name)
        if not finished:
            break
    return alloc


def parse_package(path: pathlib.Path) -> dict[str, int] | None:
    """Per-reference SURVIVING bytes from one evidence package."""
    text = path.read_text(errors="replace")
    start = text.find(SECTION)
    if start < 0:
        return None
    end = text.find("\n### [E-", start + len(SECTION))
    section = text[start : end if end > 0 else len(text)]
    out: dict[str, int] = {}
    parts = re.split(r"^### ([\w.-]+\.md)$", section, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        name, body = parts[i], parts[i + 1]
        out[name] = 0 if OMIT in body else len(body.strip().encode())
    return out


def cmd_baseline(args: argparse.Namespace) -> int:
    pkgs = sorted(globmod.glob(str(pathlib.Path(args.runs).expanduser())))
    if not pkgs:
        print(f"no evidence packages matched {args.runs}", file=sys.stderr)
        return 1
    agg: dict[str, list[int]] = {}
    for p in pkgs:
        got = parse_package(pathlib.Path(p))
        if not got:
            continue
        for name, survived in got.items():
            agg.setdefault(name, []).append(survived)
    print(f"{'reference file':40} {'runs':>4} {'min B':>7} {'max B':>7}  verdict")
    total = starved = 0
    for name, vals in sorted(agg.items()):
        total += 1
        lo, hi = min(vals), max(vals)
        verdict = "NEVER SEEN" if hi == 0 else ("thin (<2 KiB)" if hi < 2048 else "delivered")
        if hi == 0:
            starved += 1
        print(f"{name:40} {len(vals):4} {lo:7,} {hi:7,}  {verdict}")
    print(f"\n{starved}/{total} distinct reference files never reached the evaluator in any run.")
    return 0


def cmd_model(args: argparse.Namespace) -> int:
    """Report whether a skill's corpus is cut at all; slice only above the ceiling.

    The `thin` guard below (`v < sizes[k]`) matters: a file smaller than the
    threshold that arrives COMPLETE is delivered, not thin. Without it a 500 B
    reference counts as a failure — reported by the cowork-harness maintainer.
    """
    root = pathlib.Path(args.skills_dir)
    ceiling = args.ceiling
    agents_dir = root.parent / "agents"
    for skill_dir in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        # EVERY file under references/, not just *.md. The packager walks the tree
        # with no extension filter (listSkillFilesRecursive), so JSON schemas and
        # rule packs are packaged too. Filtering to .md here undercounted cap-table
        # by 224 KB and put it at 52% of the ceiling when it is actually at 96%.
        sizes = {
            str(f.relative_to(skill_dir / "references")): len(f.read_bytes())
            for f in sorted((skill_dir / "references").glob("**/*"))
            if f.is_file()
        }
        skill_md = len((skill_dir / "SKILL.md").read_bytes())
        agent_path = agents_dir / f"{skill_dir.name}.md"
        agent_md = len(agent_path.read_bytes()) if agent_path.is_file() else 0
        corpus = skill_md + agent_md + sum(sizes.values())
        print(f"\n{skill_dir.name}  corpus {corpus:,} B = {100 * corpus / ceiling:.0f}% of {ceiling:,} B")
        print(f"  SKILL.md {skill_md:,} + references {sum(sizes.values()):,} ({len(sizes)} files) + agent {agent_md:,}")
        if corpus <= ceiling:
            print("  -> SHIPS WHOLE. No allocation, no cuts. Nothing to model.")
            continue
        print(f"  -> BREACHES by {corpus - ceiling:,} B; allocator engages:")
        alloc = water_fill(sizes, max(ceiling - skill_md - agent_md, 0))
        whole = sum(1 for k, v in alloc.items() if v == sizes[k])
        thin = sum(1 for k, v in alloc.items() if v < sizes[k] and v < THIN_BYTES)
        omitted = sum(1 for v in alloc.values() if v == 0)
        print(f"     whole={whole}/{len(sizes)}  thin={thin}  omitted={omitted}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline", help="surviving bytes per reference, from archived packages")
    b.add_argument("--runs", default=PKG_GLOB)
    b.set_defaults(func=cmd_baseline)
    m = sub.add_parser("model", help="water-fill a skills tree against candidate budgets")
    m.add_argument("--skills-dir", default="founder-skills/skills")
    m.add_argument("--ceiling", type=int, default=512 * 1024, help="combined corpus ceiling (default 512 KiB)")
    m.set_defaults(func=cmd_model)
    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
