#!/usr/bin/env python3
"""Tag-time check: the newest CHANGELOG section says what changed in scoring.

A downstream consumer reads every `### Scoring changes` section between two versions to explain why
a score moved between its reports. That heading is therefore a CONTRACT: it must be in every release
section from 0.16.1 on, spelled exactly so, and it must not say "None." when a file that decides a
grade changed in the release.

What it checks, for the newest `## [X.Y.Z]` section only:

  1. The section has a `### Scoring changes` heading (sections at or before 0.16.0 are exempt; the
     contract starts after them and they are not backfilled).
  2. The range is `v<previous section>` .. `v<newest section>`, or .. HEAD when the newest tag does
     not exist yet: committed changes only, so the local pre-tag run judges exactly what CI will once
     the tag is on HEAD. This tree is dirty by design; a scoring file with uncommitted edits gets a
     warning on stderr, never a failure. A missing previous tag FAILS: a range that cannot be computed
     is not a range with no changes.
  3. If any file in `SCORING_FILES` changed in that range, the body under the heading must not be
     just "None." / "No changes." and must name each affected skill by its user-facing name. A shared
     file is listed under each skill that reads it, and only those.

`--tag vX.Y.Z` (CI passes `$GITHUB_REF_NAME`, pre-tag.sh its tag argument) also requires the newest
section to BE that version. Without it, tagging 0.16.1 before writing its section would pass as
"newest is 0.16.0, exempt".

The registry is PINNED, not a glob: a glob over `checklist*` silently stops covering a scorer that is
renamed, and silently starts covering one that is not a scorer. `tests/test_scoring_changes_check.py`
asserts every path exists.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence

HEADING = "### Scoring changes"

# The last version whose section predates the contract. Not backfilled, never required.
EXEMPT_THROUGH = (0, 16, 0)

# Same heading pattern as `changelog-notes.py`, so the two never disagree about which section is newest.
_SECTION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\][^\n]*\n(.*?)(?=^## \[|\Z)", re.S | re.M)

# User-facing names, as the CHANGELOG writes them. The first is the canonical one printed in errors;
# the rest are accepted spellings. Matching is case-insensitive with hyphens read as spaces.
SKILL_NAMES: dict[str, tuple[str, ...]] = {
    "deck-review": ("deck review",),
    "market-sizing": ("market sizing",),
    "ic-sim": ("IC simulation", "ic sim"),
    "financial-model-review": ("financial model review",),
    "competitive-positioning": ("competitive positioning",),
    "cap-table": ("cap table",),
}

# The plugin's folder in this repository; every registry path is under it.
PLUGIN = "founder-skills"

# skill -> repo paths whose change can move that skill's grade, score or verdict.
SCORING_FILES: dict[str, list[str]] = {
    "deck-review": [
        # The scorer: the 35 criteria ids, the pass/warn/fail arithmetic and the deterministic gating.
        f"{PLUGIN}/skills/deck-review/scripts/checklist.py",
        # The band cutoffs checklist.py selects the overall status from.
        f"{PLUGIN}/skills/deck-review/scripts/_thresholds.py",
        # The arithmetic numbers_consistent is scored from: its verdicts decide that criterion's status.
        f"{PLUGIN}/skills/deck-review/scripts/reconcile.py",
        # The criteria definitions with their pass/fail/warn thresholds; the CHECKLIST dispatch grades from it.
        f"{PLUGIN}/skills/deck-review/references/checklist-criteria.md",
        # The stage table written into stage_profile.json, which the CHECKLIST dispatch grades the
        # stage-fit criteria against.
        f"{PLUGIN}/skills/deck-review/scripts/stage_profile.py",
        # The stage frameworks the slide reviews compare against; the checklist reads those reviews,
        # and stage_profile.py's table mirrors this file.
        f"{PLUGIN}/skills/deck-review/references/deck-best-practices.md",
        # The CHECKLIST sub-agent's own grading instructions (its "For `CHECKLIST`" section).
        f"{PLUGIN}/agents/deck-review.md",
    ],
    "market-sizing": [
        # The 22-item self-check scorer.
        f"{PLUGIN}/skills/market-sizing/scripts/checklist.py",
        # The band cutoffs checklist.py selects the overall grade from.
        f"{PLUGIN}/skills/market-sizing/scripts/_thresholds.py",
        # The low/base/high ranges and confidence-based widening; moves the stress-tested figures.
        f"{PLUGIN}/skills/market-sizing/scripts/sensitivity.py",
        # The checklist's item definitions, which the CHECKLIST dispatch grades from.
        f"{PLUGIN}/skills/market-sizing/references/pitfalls-checklist.md",
        # The CHECKLIST prompt generator: the grader's instructions come from here.
        f"{PLUGIN}/skills/market-sizing/scripts/dispatch_prompt.py",
        # The agent body's CHECKLIST subtype section: the grader's standing instructions.
        f"{PLUGIN}/agents/market-sizing.md",
    ],
    "ic-sim": [
        # The 28-dimension conviction scorer and the verdict (a dealbreaker forces hard_pass).
        f"{PLUGIN}/skills/ic-sim/scripts/score_dimensions.py",
        # The OPERATIVE rubric: ic-sim's SKILL.md states the 28-dimension rubric is inlined into the
        # SCORE_DIMENSIONS sub-agent's prompt here, and that references/evaluation-criteria.md is
        # documentation whose edits do not reach scoring. So this file is listed and that one is not;
        # listing the reference would flag doc edits and miss real rubric edits.
        f"{PLUGIN}/agents/ic-sim.md",
    ],
    "financial-model-review": [
        # The 46-criterion scorer with stage/geography/sector gating.
        f"{PLUGIN}/skills/financial-model-review/scripts/checklist.py",
        # The 11 unit-economics metrics and their ratings against stage targets.
        f"{PLUGIN}/skills/financial-model-review/scripts/unit_economics.py",
        # The criteria definitions the CHECKLIST dispatch grades from.
        f"{PLUGIN}/skills/financial-model-review/references/checklist-criteria.md",
        # Prints the CHECKLIST dispatch, including which structural-error sentence the grader gets.
        f"{PLUGIN}/skills/financial-model-review/scripts/fmr_dispatch_prompt.py",
        # The agent body's CHECKLIST subtype section.
        f"{PLUGIN}/agents/financial-model-review.md",
        # Plugin-root, but read by this skill only (SKILL.md's shared-reference list): the per-model
        # "checks by stage" tables that say which checks apply to a revenue model.
        f"{PLUGIN}/references/revenue-model-types.md",
        # Shared stage benchmarks and expectations. Read by this skill (SKILL.md's shared-reference
        # list; unit_economics.py cites benchmarks.md for its R40 tiers) and by competitive
        # positioning, so they are listed under both and under no other.
        f"{PLUGIN}/references/benchmarks.md",
        f"{PLUGIN}/references/stage-expectations.md",
        # runway.py is deliberately absent: it computes months of runway and grades nothing (its own
        # comment contrasts it with unit_economics.py, "which grades against a stage").
    ],
    "competitive-positioning": [
        # The ~25-criterion quality checklist scorer.
        f"{PLUGIN}/skills/competitive-positioning/scripts/checklist.py",
        # Moat dimension scoring.
        f"{PLUGIN}/skills/competitive-positioning/scripts/score_moats.py",
        # Positioning ranks and the claim verdict counts.
        f"{PLUGIN}/skills/competitive-positioning/scripts/score_positioning.py",
        # The moat scoring rubrics the MOAT_SCORING dispatch scores from.
        f"{PLUGIN}/skills/competitive-positioning/references/moat-definitions.md",
        # The checklist criteria; checklist.py's ids must match it exactly.
        f"{PLUGIN}/skills/competitive-positioning/references/checklist-criteria.md",
        # Prints the MOAT_SCORING, POSITIONING_SCORING and CHECKLIST dispatches.
        f"{PLUGIN}/skills/competitive-positioning/scripts/cp_dispatch_prompt.py",
        # The agent body's MOAT_SCORING, POSITIONING_SCORING and CHECKLIST subtype sections.
        f"{PLUGIN}/agents/competitive-positioning.md",
        # Shared benchmarks, read per SKILL.md's shared-reference list (see financial-model-review).
        f"{PLUGIN}/references/benchmarks.md",
        f"{PLUGIN}/references/stage-expectations.md",
    ],
    "cap-table": [
        # cap-table has no numeric score. The rule pack is listed as its VERDICT source, not a grade:
        # it decides each rule's status (in window, expired, not applicable) and the counsel-review
        # reliance boundary, which is what a reader needs to explain a changed cap-table output.
        f"{PLUGIN}/skills/cap-table/data/cap-table-rules.json",
    ],
}


class CheckError(Exception):
    """A failure to report; the message is printed as a GitHub `::error::` line."""


def _vtuple(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return (a, b, c)


def sections(changelog: str) -> list[tuple[str, str]]:
    """Every `(version, body)` in file order, newest first."""
    return [(m.group(1), m.group(2)) for m in _SECTION_RE.finditer(changelog)]


def scoring_body(section_body: str) -> str | None:
    """The text under `### Scoring changes`, up to the next `##`/`###` heading; None when absent."""
    m = re.search(rf"^{re.escape(HEADING)}[ \t]*\n(.*?)(?=^#{{2,3}}[ \t]|\Z)", section_body, re.S | re.M)
    return None if m is None else m.group(1).strip()


# Bodies that mean "nothing changed", compared case-insensitively with any trailing full stop dropped.
_EMPTY = ("", "none", "no changes")


def _norm(text: str) -> str:
    return " ".join(text.replace("-", " ").casefold().split())


def names_skill(body: str, skill: str) -> bool:
    nb = _norm(body)
    return any(re.search(rf"\b{re.escape(_norm(n))}\b", nb) for n in SKILL_NAMES[skill])


def affected_skills(changed: Iterable[str], registry: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """skill -> registry paths of that skill that changed."""
    changed_set = set(changed)
    out: dict[str, list[str]] = {}
    for skill, paths in registry.items():
        hit = sorted(p for p in paths if p in changed_set)
        if hit:
            out[skill] = hit
    return out


def check_section(
    version: str,
    body: str,
    changed: Iterable[str],
    registry: Mapping[str, Sequence[str]] = SCORING_FILES,
) -> list[str]:
    """Problems with one section, given the files changed in its range. Empty list = pass."""
    text = scoring_body(body)
    if text is None:
        return [f"CHANGELOG section {version} has no `{HEADING}` heading (write 'None.' when nothing changed)"]
    affected = affected_skills(changed, registry)
    if not affected:
        return []
    files = sorted({p for ps in affected.values() for p in ps})
    if _norm(text).rstrip(".").strip() in _EMPTY:
        return [
            f"`{HEADING}` in {version} says 'None.' (or 'No changes.') but scoring files changed: " + ", ".join(files)
        ]
    problems: list[str] = []
    for skill, paths in sorted(affected.items()):
        if not names_skill(text, skill):
            problems.append(
                f"`{HEADING}` in {version} does not name {SKILL_NAMES[skill][0]!r}, whose scoring files changed: "
                + ", ".join(paths)
            )
    return problems


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _tag_exists(repo: pathlib.Path, tag: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0


def changed_files(repo: pathlib.Path, prev_tag: str, new_tag: str) -> list[str]:
    """Files committed between `prev_tag` and `new_tag`, or HEAD when `new_tag` is absent."""
    if not _tag_exists(repo, prev_tag):
        raise CheckError(
            f"previous release tag {prev_tag} not found, so the release's range cannot be computed. "
            "Fetch tags (CI: `fetch-depth: 0`) — this check fails rather than skipping."
        )
    end = new_tag if _tag_exists(repo, new_tag) else "HEAD"
    p = _git(repo, "diff", "--name-only", f"{prev_tag}..{end}")
    if p.returncode != 0:
        raise CheckError(f"git diff {prev_tag}..{end} failed: {p.stderr.strip()}")
    return sorted(set(p.stdout.splitlines()))


def uncommitted_scoring_files(repo: pathlib.Path, registry: Mapping[str, Sequence[str]]) -> list[str]:
    """Registry files with uncommitted edits (staged or not). Reported, never judged: the tag is cut
    from a commit, so only committed changes are in the release."""
    p = _git(repo, "diff", "--name-only", "HEAD")
    dirty = set(p.stdout.splitlines()) if p.returncode == 0 else set()
    return sorted({f for paths in registry.values() for f in paths} & dirty)


def run(
    repo: pathlib.Path,
    changelog: str,
    tag: str | None = None,
    registry: Mapping[str, Sequence[str]] = SCORING_FILES,
) -> str:
    """Return a one-line pass message, or raise CheckError."""
    secs = sections(changelog)
    if not secs:
        raise CheckError("no `## [X.Y.Z]` section found in the CHANGELOG")
    newest, body = secs[0]
    if tag is not None and newest != tag.lstrip("v"):
        raise CheckError(f"tagging {tag} but the newest CHANGELOG section is {newest}; write {tag.lstrip('v')}'s first")
    if _vtuple(newest) <= EXEMPT_THROUGH:
        return f"{newest} predates the `{HEADING}` contract; exempt"
    if len(secs) < 2:
        raise CheckError(f"{newest} has no previous section to diff from")
    prev = secs[1][0]
    changed = changed_files(repo, f"v{prev}", f"v{newest}")
    dirty = uncommitted_scoring_files(repo, registry)
    if dirty:
        print(
            "::warning::scoring files have uncommitted edits, not judged (only committed changes are in "
            "the release): " + ", ".join(dirty),
            file=sys.stderr,
        )
    problems = check_section(newest, body, changed, registry)
    if problems:
        raise CheckError("; ".join(problems))
    hit = affected_skills(changed, registry)
    return f"{newest}: `{HEADING}` present; scoring files changed since v{prev}: {sum(map(len, hit.values()))}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    p.add_argument("--changelog", default="CHANGELOG.md")
    p.add_argument("--repo", default=".")
    p.add_argument("--tag", help="the tag being cut, e.g. v0.16.1; the newest section must be this version")
    args = p.parse_args(argv)
    try:
        text = pathlib.Path(args.changelog).read_text(encoding="utf-8")
        print(run(pathlib.Path(args.repo), text, args.tag or None))
    except (CheckError, OSError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
