"""competitive-positioning's side of the adversarial review's copies: what a review is taken against.

Which review the founder is shown, and why the answer comes from append-only copies rather than from
`redteam.json`, is decided in the plugin's shared `scripts/_redteam_core.py`; the same rules serve every
skill with a reviewer. What stays here is what only this skill has:

- `reviewed_state`: a fingerprint of each file the reviewer was given, so a review of a map that has
  since changed is told apart from a review of the map as delivered. The file list is the prompt
  generator's own (`cp_dispatch_prompt.RED_TEAM_ARTIFACTS`), so what the review read and what it is
  compared against cannot drift apart;
- the reasons a run may record for not running a review (`SKIP_REASONS`), and reading that record.

The shared module is loaded by path on FIRST USE, never at import: a copy of the skill's scripts without
the plugin around them must still reach the producer's "shared scripts are not reachable" refusal
rather than a traceback.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Callable, Iterable
from typing import Any

from cp_dispatch_prompt import RED_TEAM_ARTIFACTS, RED_TEAM_OPTIONAL

_SHARED_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
)
SKIP_FILE = "red_team_skip.json"
# The review and its skip record: a run writes one of the two, so the other is often an earlier run's.
# Each is this run's only when its run_id says so -- decided here, and nowhere by a generic check.
RUN_SCOPED = frozenset({"redteam.json", SKIP_FILE})
# Closed on purpose: each value is a different sentence the founder reads, and there is deliberately
# no value meaning "it did not seem necessary".
SKIP_REASONS = ("founder_declined", "dispatch_failed", "no_network_available", "no_subagent_dispatch")
# Fields a producer rewrites on a re-pipe that changed nothing: the landscape's as-of date is today's
# date. Left in, a re-pipe on a later day would read as a changed map.
_VOLATILE_KEYS = frozenset({"landscape_as_of"})
# What an absent optional file fingerprints as. A fixed value, so a run without the public-record step
# compares equal to itself rather than flipping between the review and compose.
ABSENT = "absent"


def core() -> Any:
    """The shared `_redteam_core` module. Raises ImportError when the plugin's shared scripts are absent."""
    mod = sys.modules.get("_redteam_core")
    if mod is not None:
        return mod
    path = os.path.join(_SHARED_SCRIPTS, "_redteam_core.py")
    spec = importlib.util.spec_from_file_location("_redteam_core", path)
    if spec is None or spec.loader is None or not os.path.isfile(path):
        raise ImportError(f"no _redteam_core.py at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_redteam_core"] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop("_redteam_core", None)
        raise
    return mod


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fingerprint(analysis_dir: str, name: str) -> str:
    """sha256 of the file's JSON in canonical form, volatile keys dropped; ABSENT when it is not there."""
    path = os.path.join(analysis_dir, name)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return ABSENT
    except (OSError, ValueError):
        return "unreadable"
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in _VOLATILE_KEYS}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reviewed_state(analysis_dir: str) -> dict[str, str]:
    """Each file the reviewer was given, fingerprinted as it stands."""
    return {name: _fingerprint(analysis_dir, name) for name in (*RED_TEAM_ARTIFACTS, *RED_TEAM_OPTIONAL)}


def review_matcher(analysis_dir: str) -> Callable[[Any], bool]:
    """`same_as_now` for `resolve`: was a copy taken of the files as they now stand?"""
    now = reviewed_state(analysis_dir)
    return lambda reviewed: isinstance(reviewed, dict) and reviewed == now


def changed_since(reviewed: Any, analysis_dir: str) -> list[str]:
    """The files that differ from what a review saw, in the generator's order."""
    if not isinstance(reviewed, dict):
        return []
    now = reviewed_state(analysis_dir)
    return [name for name in now if reviewed.get(name) != now[name]]


def write_copy(analysis_dir: str, run_id: str, result: dict[str, Any], handoff_sha256: str) -> int:
    """Write this round's copy and return its round number. Raises OSError on failure."""
    return int(
        core().write_copy(
            analysis_dir,
            run_id,
            result,
            handoff_sha256,
            reviewed_state=lambda: reviewed_state(analysis_dir),
            block_extra=lambda: {},
        )
    )


def primary_run_id(docs: Iterable[Any]) -> str | None:
    """This run's id, from the required artifacts -- never from the review itself."""
    rid = core().primary_run_id(docs)
    return rid if isinstance(rid, str) else None


def primary_run_id_in(dir_path: str, artifacts: Any, names: Iterable[str]) -> str | None:
    """This run's id from the named artifacts as loaded, ties to the one produced last (rule in the core)."""
    rid = core().primary_run_id_in(dir_path, artifacts, names)
    return rid if isinstance(rid, str) else None


def skip_reason(skip_record: Any, run_id: str | None) -> str | None:
    """This run's recorded reason for not running a review, or None. A record from another run, or a
    reason off the closed list, is not this run's decision."""
    rec = _as_dict(skip_record)
    reason = rec.get("reason")
    rid = _as_dict(rec.get("metadata")).get("run_id")
    if run_id and rid != run_id:
        return None
    return reason if isinstance(reason, str) and reason in SKIP_REASONS else None


def resolve(
    analysis_dir: str,
    run_id: str | None,
    redteam: Any,
    skip_record: Any,
) -> tuple[dict[str, Any] | None, list[tuple[str, str]], dict[str, Any]]:
    """(the review to show, [(code, message)], facts) for this run -- `_redteam_core.resolve`, with this
    skill's skip record and fingerprints.

    When no review is of the files as delivered, the latest is shown and ANALYSIS_CHANGED_AFTER_REVIEW
    names the files that changed after it.
    """
    # An earlier run's review is not this run's: never returned, never rendered. (Its copies live under
    # that run's own hand-off dir, so nothing here can pick one up either.)
    if run_id and _as_dict(_as_dict(redteam).get("metadata")).get("run_id") != run_id:
        redteam = None
    chosen, codes, facts = core().resolve(
        analysis_dir,
        run_id,
        redteam,
        skipped=skip_reason(skip_record, run_id) is not None,
        same_as_now=review_matcher(analysis_dir),
    )
    altered = any(c == "REDTEAM_ALTERED" for c, _ in codes)
    if facts.get("rounds") and not facts.get("matched") and not altered:
        changed = changed_since(facts.get("reviewed_shown"), analysis_dir)
        if changed:
            codes.append(("ANALYSIS_CHANGED_AFTER_REVIEW", changed_message(changed)))
    elif facts.get("matched") and not facts.get("all_match") and not altered:
        # A later round matches the analysis as delivered and an earlier one does not: the analysis was
        # changed between reviews. This skill has no revision round, so the earlier review -- possibly
        # the harsher one -- is exactly what the founder must hear about; the renderer lists it.
        changed = changed_since(facts.get("reviewed_first"), analysis_dir)
        codes.append(("ANALYSIS_CHANGED_BETWEEN_REVIEWS", between_message(changed)))
    return chosen, codes, facts


_PLAIN_FILES = {
    "product_profile.json": "the profile of your company",
    "landscape.json": "the competitor research",
    "positioning_scores.json": "the positioning map",
    "moat_scores.json": "the moat ratings",
    "startup_research.json": "the research on your company's public record",
}


def between_message(changed: list[str]) -> str:
    what = ", ".join(_PLAIN_FILES.get(n, n) for n in changed) or "the analysis"
    return (
        f"The analysis changed between two outside reviews ({what}). The review shown is of the analysis "
        "as delivered, and the earlier one is listed with it. Re-running or editing cannot fix this; "
        "deliver the report as it is."
    )


def changed_message(changed: list[str]) -> str:
    what = ", ".join(_PLAIN_FILES.get(n, n) for n in changed)
    # One remedy only. "Review it again" would change what this compares: a second review of the changed
    # analysis would then be the one shown, and the first -- taken before the change -- would drop from
    # view. This skill has no revision round; a change after the review is disclosed, never re-reviewed.
    return (
        f"The analysis changed after the outside review was written ({what}), so the review shown was "
        "taken against an earlier version. Re-running or editing cannot fix this; deliver the report as "
        "it is."
    )


def other_rounds(analysis_dir: str, run_id: str | None, round_shown: Any) -> list[tuple[int, dict[str, Any]]]:
    """Every other readable review round of this run, in order, as `redteam.json` would hold it.

    This skill has no revision round, so every other review of this run is listed beside the one shown:
    a later review of the same analysis so that re-running cannot hide a harsher one, and an earlier
    review of a version since changed so that changing the analysis cannot hide one either.
    """
    if not run_id:
        return []
    c = core()
    return [
        (n, dict(c.strip(doc)))
        for n, doc in c.list_copies(analysis_dir, run_id)
        if isinstance(doc, dict) and n != round_shown
    ]
