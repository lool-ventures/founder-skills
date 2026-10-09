#!/usr/bin/env python3
"""Tag-time check: the paid gate already passed, on a dispatched run, at exactly this commit.

The paid checks (`deck-review-e2e-smoke`, the three real-LLM lanes, and `mutation-corpus`) run ONCE
per release: dispatched by hand on the release branch, before `main` moves. The tag push does not
run them again. Instead `verify-branch-gate` in `skill-quality.yml` runs this script, and
`publish-release` needs that job, so a Release exists only when GitHub holds a run record that says
the paid checks passed at the tagged commit.

WHAT COUNTS AS EVIDENCE. A run of `skill-quality.yml` that:

  - was started by `workflow_dispatch` (a `pull_request` run at the same commit skips the paid
    jobs, and a tag push no longer runs them);
  - is at `head_sha` == the tagged commit, the full 40-hex SHA;
  - has `status == completed`;
  - in the LATEST attempt of each job (`jobs?filter=latest`), has every display name in
    `REQUIRED_JOBS` present with `conclusion == success`.

The run's own `conclusion` is NOT read. A release-notes rehearsal dispatch (`-f
verify_release_notes_for=...`) concludes `success` with both paid jobs skipped; only the per-job
check rejects it. A required name that is absent from the jobs list is a rejection ("job not
found"), never a skip.

The branch the run was dispatched on is NOT checked. The commit identifies what was tested; a
branch name adds no security (anyone who can dispatch can also name a branch or push a tag), and
requiring `release/` would reject a legitimate green run made on `main` or on the tag ref itself
(the override below).

POLICY: ANY ONE qualifying run passes. Several dispatches at the same commit ran the same tree, so
a later red one is variance; but each rejected sibling is still printed as a warning on the success
path, so a maintainer who dispatched again sees that not every run was green.

`filter=latest` takes the newest attempt of each job. A run that failed and was then re-run green
passes; a run that was green and then re-run red is rejected. A job carried over from an earlier
attempt is reported in the latest attempt with its original conclusion.

MATCHING IS ON DISPLAY NAMES (the jobs API returns `name:`, not the YAML id). The workflow file at
the tagged commit is the one the branch run executed, so the names agree by construction;
`test_release_gating.py` pins `REQUIRED_JOBS` to the workflow, so a rename reds for free. A matrix
job would render as `name (value)`; none of the required jobs is a matrix job.

RENAMING A REQUIRED JOB: change its `name:` and `REQUIRED_JOBS` together, in one release. That
release's branch run reports the new name, so its tag passes. Older runs keep the old name, so after
that release point `branch-gate-selftest`'s SHA and tag at it.

FAILS CLOSED. Every `gh` call is `check=True`; output is parsed once; nothing is caught broadly. An
API error, a rate limit or an unexpected shape ends the script non-zero, which skips the Release.

OVERRIDE (no branch run, or a hotfix shipped without one): `gh workflow run skill-quality.yml --ref
vX.Y.Z` runs the paid checks at the tag's commit (a dispatch never publishes), then, once green,
`gh run rerun <tag-push-run-id> --failed` re-runs this check, and `publish-release` with it. A run
can be re-run only within 30 days of its first attempt, and a re-run executes the workflow file at
that run's own commit; past either limit the only path is a hand-run `gh release create`.

Usage (CI passes the checkout's HEAD and `$GITHUB_REF_NAME`; `GH_REPO` names the repository):

    python3 .github/scripts/branch_gate_check.py --sha "$(git rev-parse HEAD)" --tag vX.Y.Z

Plain stdlib Python: the tag job runs it before any dependency is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

WORKFLOW_FILE = "skill-quality.yml"

# YAML job id -> display `name:`. The jobs API reports the display name, so that is what must match.
REQUIRED_JOBS: dict[str, str] = {
    "deck-review-e2e-smoke": "end-to-end smoke, 3 skills (real LLM)",
    "mutation-corpus": "Curated mutant corpus (cap-table)",
}

_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def judge(
    runs: Sequence[Mapping[str, Any]],
    jobs_by_run: Mapping[Any, Sequence[Mapping[str, Any]]],
    sha: str,
) -> tuple[Mapping[str, Any] | None, list[tuple[Mapping[str, Any], str]]]:
    """Pure decision. Returns (the first qualifying run or None, [(rejected run, reason), ...]).

    `jobs_by_run` maps a run id to the LATEST attempt's jobs. A run missing from it is rejected, never
    passed: no jobs list is no evidence.
    """
    accepted: Mapping[str, Any] | None = None
    rejected: list[tuple[Mapping[str, Any], str]] = []
    for run in runs:
        reason = _reject_reason(run, jobs_by_run.get(run.get("id")), sha)
        if reason is None and accepted is None:
            accepted = run
        elif reason is not None:
            rejected.append((run, reason))
    return accepted, rejected


def _reject_reason(run: Mapping[str, Any], jobs: Sequence[Mapping[str, Any]] | None, sha: str) -> str | None:
    if run.get("event") != "workflow_dispatch":
        return f"event is {run.get('event')!r}, not a dispatch"
    if run.get("head_sha") != sha:
        return f"at {run.get('head_sha')!r}, not this commit"
    path = run.get("path")
    if path is not None and not str(path).endswith(WORKFLOW_FILE):
        return f"a run of {path!r}, not {WORKFLOW_FILE}"
    if run.get("status") != "completed":
        return f"still {run.get('status')!r}; when it finishes, re-run this job (free)"
    if not jobs:
        return "no jobs listed for its latest attempt"
    problems = []
    for job_id, name in REQUIRED_JOBS.items():
        matching = [j for j in jobs if j.get("name") == name]
        if not matching:
            problems.append(f"{job_id} ({name!r}) not found")
            continue
        bad = [j.get("conclusion") for j in matching if j.get("conclusion") != "success"]
        if bad:
            problems.append(f"{job_id} concluded {bad[0]!r}")
    return "; ".join(problems) if problems else None


def _describe(run: Mapping[str, Any]) -> str:
    return (
        f"run {run.get('id')} on {run.get('head_branch')!r} (attempt {run.get('run_attempt')}, {run.get('html_url')})"
    )


def _override(tag: str) -> str:
    return (
        f"To publish {tag} without a branch run: `gh workflow run {WORKFLOW_FILE} --ref {tag}`, wait for "
        "it to go green, then `gh run rerun <this run's id> --failed` (within 30 days of this run's first "
        "attempt). Past that, publish by hand with `gh release create` (CLAUDE.md, Release Process)."
    )


# --- I/O --------------------------------------------------------------------------------------------


def _gh_json(args: Sequence[str]) -> Any:
    """One `gh api` call. check=True: any failure ends the script, which skips the Release."""
    # stderr is not captured, so gh's own error (HTTP status, rate limit) reaches the job log.
    proc = subprocess.run(["gh", "api", *args], check=True, stdout=subprocess.PIPE, text=True)
    return json.loads(proc.stdout)


def fetch(repo: str, sha: str) -> tuple[list[dict[str, Any]], dict[Any, list[dict[str, Any]]]]:
    pages = _gh_json(
        [
            "--paginate",
            "--slurp",
            f"repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?event=workflow_dispatch&head_sha={sha}&per_page=100",
        ]
    )
    if not isinstance(pages, list):
        raise SystemExit(f"::error::unexpected runs response (not a list of pages): {type(pages).__name__}")
    runs: list[dict[str, Any]] = []
    for page in pages:
        runs.extend(page["workflow_runs"])
    jobs_by_run: dict[Any, list[dict[str, Any]]] = {}
    for run in runs:
        # One page: a run of this workflow has a handful of jobs, far under 100.
        data = _gh_json([f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100"])
        jobs_by_run[run["id"]] = list(data["jobs"])
    return runs, jobs_by_run


def _full_sha(sha: str) -> str:
    """The API's `head_sha` filter matches only the full SHA (an abbreviated one returns zero runs, which
    would read as "no branch run"). Expand through git when a repository is present; otherwise refuse."""
    if _FULL_SHA.fullmatch(sha):
        return sha
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], capture_output=True, text=True
    )
    full = proc.stdout.strip()
    if proc.returncode != 0 or not _FULL_SHA.fullmatch(full):
        raise SystemExit(f"::error::--sha {sha!r} is not a full 40-hex commit SHA and git cannot expand it")
    return full


def _summary(lines: Sequence[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--sha", required=True, help="the tagged commit (CI passes `git rev-parse HEAD`)")
    ap.add_argument("--tag", required=True, help="the tag, for messages only (CI passes $GITHUB_REF_NAME)")
    ap.add_argument("--repo", default=os.environ.get("GH_REPO", ""), help="owner/name (default: $GH_REPO)")
    args = ap.parse_args(argv)
    if not args.repo:
        print("::error::no repository: pass --repo or set GH_REPO", file=sys.stderr)
        return 2
    sha = _full_sha(args.sha)

    runs, jobs_by_run = fetch(args.repo, sha)
    accepted, rejected = judge(runs, jobs_by_run, sha)

    if accepted is not None:
        print(f"paid gate passed for {args.tag} at {sha}: {_describe(accepted)}")
        for run, why in rejected:
            print(f"::warning::another dispatch at this commit was not green: {_describe(run)}: {why}")
        _summary(
            [
                f"### Paid gate for `{args.tag}`",
                "",
                f"Passed at `{sha}` by [run {accepted.get('id')}]({accepted.get('html_url')}) "
                f"on `{accepted.get('head_branch')}`.",
                f"{len(runs) - len(rejected)} of {len(runs)} dispatched run(s) at this commit qualified.",
            ]
        )
        return 0

    print(f"::error::no green paid-gate run at {sha} for {args.tag}", file=sys.stderr)
    if not runs:
        print(f"no `{WORKFLOW_FILE}` dispatch exists at this commit.", file=sys.stderr)
    for run, why in rejected:
        print(f"  rejected {_describe(run)}: {why}", file=sys.stderr)
    print(_override(args.tag), file=sys.stderr)
    _summary(
        [f"### Paid gate for `{args.tag}`: NOT FOUND", "", f"No qualifying run at `{sha}`.", "", _override(args.tag)]
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
