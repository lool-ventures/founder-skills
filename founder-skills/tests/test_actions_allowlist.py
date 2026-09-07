"""Every `uses:` in every workflow must be permitted by the repository's Actions allowlist.

WHY THIS EXISTS. This repository runs with `allowed_actions: "selected"`, so GitHub refuses to
start any workflow referencing an action outside the allowlist. The refusal is not a failing job:
it is a `startup_failure` with **zero jobs, zero seconds and no log**, which reads to everyone as
"CI is broken" rather than "this action is not permitted".

That is exactly how it went wrong. A workflow's `uses:` was bumped across a major while the
allowlist was never widened to cover it. The workflow triggers only on `pull_request`, no pull
request was opened for over a month, and the breakage therefore surfaced on an outside
contributor's first contribution -- as an unexplained red check they had no way to act on, on a
workflow they had not touched.

THE DRIFT IS INVISIBLE BY CONSTRUCTION. The allowlist lives in repository settings and the
`uses:` refs live in git. Nothing compares them, no local run can fail on their disagreement,
and the two are edited by different people at different times for different reasons.

WHAT THIS CAN AND CANNOT SEE. `_ALLOWLIST` below is a COMMITTED MIRROR of the live setting, so
this file catches the high-frequency direction -- a workflow drifting away from the policy -- on
every run, offline, with a readable message. It cannot see the low-frequency direction: someone
narrowing the real setting in the GitHub UI without updating the mirror. Re-derive the mirror
with

    gh api repos/lool-ventures/founder-skills/actions/permissions/selected-actions

whenever the policy is touched. A stale mirror produces a false green here, which is the one
failure mode of this file and the reason the command is written down rather than described.

SCOPE. This asserts PERMISSION, never that an action works, is pinned to a safe ref, or that the
workflow using it passes. Whether `@v3` is the right major is `test_cowork_harness_floors.py`'s
business; whether GitHub will consent to run it at all is this file's.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# MIRROR of the live repository setting. Re-derive with the `gh api` call in the module docstring.
_ALLOWLIST: dict[str, Any] = {
    "github_owned_allowed": True,
    "verified_allowed": True,
    "patterns_allowed": [
        "dcoapp/*",
        "astral-sh/*",
        "yaniv-golan/cowork-harness@*",
    ],
}

# Owners GitHub treats as its own under `github_owned_allowed`.
_GITHUB_OWNED = {"actions", "github"}

# Allowlist patterns that legitimately match no `uses:` in any workflow. `dcoapp` is a GitHub
# APP, not an action -- it reports the DCO status check without ever appearing in a workflow --
# so it can never be exercised here. Every OTHER unused pattern is a suppression that suppresses
# nothing, and this file makes it visible rather than letting it accumulate.
_UNUSED_BY_DESIGN = {"dcoapp/*"}

# Non-vacuity floors. An extraction that silently finds nothing would pass every assertion below
# while checking nothing at all, which is the failure this whole file exists to prevent arriving
# through the tool meant to detect it.
_MIN_WORKFLOWS = 4
_MIN_USES = 20


def _workflow_files() -> list[Path]:
    return sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))


def _uses_refs() -> list[tuple[str, str, str]]:
    """Every (workflow, job, ref) parsed from YAML -- never grepped.

    A regex over the raw text also matches `uses:` inside the long comment blocks these
    workflows carry, which would report a documented historical ref as a live one.
    """
    found: list[tuple[str, str, str]] = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            # A job-level `uses:` is a reusable workflow; it is governed by the same policy.
            if isinstance(job.get("uses"), str):
                found.append((path.name, job_name, job["uses"]))
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("uses"), str):
                    found.append((path.name, job_name, step["uses"]))
    return found


def _permits(ref: str) -> bool:
    """Replicate GitHub's allowlist matching for the forms this repository actually uses."""
    if ref.startswith("./"):
        return True  # an action committed to this repository; not governed by the allowlist
    owner_repo = ref.split("@", 1)[0]
    owner = owner_repo.split("/", 1)[0]
    if _ALLOWLIST["github_owned_allowed"] and owner in _GITHUB_OWNED:
        return True
    return any(fnmatch(ref, pattern) or fnmatch(owner_repo, pattern) for pattern in _ALLOWLIST["patterns_allowed"])


def test_extraction_is_not_vacuous() -> None:
    """Guard the guard: a parser that finds nothing greens every other test in this file."""
    workflows = _workflow_files()
    refs = _uses_refs()
    assert len(workflows) >= _MIN_WORKFLOWS, f"expected >= {_MIN_WORKFLOWS} workflows, found {len(workflows)}"
    assert len(refs) >= _MIN_USES, f"expected >= {_MIN_USES} `uses:` refs, found {len(refs)}"


def test_every_workflow_action_is_permitted_by_the_allowlist() -> None:
    """The check itself. A `uses:` the policy does not cover cannot start, and says nothing."""
    refused = [(wf, job, ref) for wf, job, ref in _uses_refs() if not _permits(ref)]
    assert not refused, (
        "these `uses:` refs are not covered by the Actions allowlist, so GitHub will refuse to "
        "start their workflow (startup_failure, no jobs, no log):\n"
        + "\n".join(f"  {ref}  ({wf} / {job})" for wf, job, ref in refused)
        + "\n\nEither widen the allowlist (Settings > Actions > Allow specified actions) and update "
        "_ALLOWLIST in this file, or change the ref."
    )


def test_no_action_relies_on_the_verified_creator_escape_hatch() -> None:
    """Keep this file decidable offline.

    `verified_allowed` permits actions from GitHub Marketplace verified creators, which cannot be
    determined without a network call. Nothing here relies on it today, and the moment something
    does, every assertion above becomes an approximation. Then the choice is deliberate: add an
    explicit pattern for that action, or accept that this file no longer decides the question.
    """
    hatch = [
        (wf, job, ref)
        for wf, job, ref in _uses_refs()
        if not ref.startswith("./")
        and ref.split("@", 1)[0].split("/", 1)[0] not in _GITHUB_OWNED
        and not any(fnmatch(ref, p) or fnmatch(ref.split("@", 1)[0], p) for p in _ALLOWLIST["patterns_allowed"])
    ]
    assert not hatch, (
        "these refs are permitted only by `verified_allowed`, which this file cannot evaluate "
        "offline: " + ", ".join(ref for _, _, ref in hatch)
    )


@pytest.mark.parametrize("pattern", [p for p in _ALLOWLIST["patterns_allowed"] if p not in _UNUSED_BY_DESIGN])
def test_every_allowlist_pattern_is_exercised(pattern: str) -> None:
    """An allowlist entry matching nothing is a permission granted for no reason.

    It also misleads the next reader, who reasonably assumes each entry is load-bearing. Retire
    the entry, or record it in `_UNUSED_BY_DESIGN` with the reason it cannot be exercised.
    """
    refs = [ref for _, _, ref in _uses_refs()]
    assert any(fnmatch(r, pattern) or fnmatch(r.split("@", 1)[0], pattern) for r in refs), (
        f"allowlist pattern {pattern!r} matches no `uses:` in any workflow. Remove it from the "
        f"repository setting and from _ALLOWLIST, or add it to _UNUSED_BY_DESIGN with a reason."
    )
