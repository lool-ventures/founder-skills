"""Append-only copies of the adversarial review: what the founder is shown, and how many were run.

The analysis's main thread can change the review after it is written -- measured with `python3 -c`
and with a plain write over `redteam.json`, each time with a SKILL.md rule against it in context.
So the founder-facing output does not depend on `redteam.json` staying untouched.

`red_team.py` writes, beside `redteam.json`, a copy per round into this run's hand-off dir,
`handoff/<run_id>/redteam.r<N>.json`, created once and never rewritten by a later round.
Compose and visualize render the review from the copy. An edit to `redteam.json` changes nothing
the founder reads, and it is reported (`REDTEAM_ALTERED`).

The copies also count rounds. A review is final unless the founder approved ONE revision
(`methodology.red_team_revision.approved_by_founder`). Without that approval, a second round is
reported and the FIRST review is the one shown, so re-running the review until it says something
else does not work either.

Detection, not prevention: the main thread owns the filesystem, and a deliberate overwrite of both
the review and its copy defeats this. That is a different act from the two observed, and the
plan names it as a residual.

Rounds are counted by the hand-off each copy was produced from. Re-piping the SAME hand-off (for
instance with a corrected documents dir) replaces that round's copy instead of adding a round.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

COPY_KEY = "_review_copy"
_COPY_RE = re.compile(r"^redteam\.r(\d+)\.json$")
# The founder's stated figures as they stood when the review was written -- the baseline a later
# rewrite of them is compared against.
_INPUT_KEYS = (
    "founder_stated_inputs",
    "founder_stated_inputs_period",
    "founder_stated_inputs_currency",
    "founder_stated_inputs_source",
)


def copies_dir(analysis_dir: str, run_id: str) -> str:
    return os.path.join(analysis_dir, "handoff", run_id)


def strip(doc: dict[str, Any]) -> dict[str, Any]:
    """The review as `redteam.json` holds it: the copy minus its own bookkeeping."""
    return {k: v for k, v in doc.items() if k != COPY_KEY}


def list_copies(analysis_dir: str, run_id: str) -> list[tuple[int, dict[str, Any] | None]]:
    """Every copy for this run, by round. An unreadable copy is kept as None: it still counts."""
    d = copies_dir(analysis_dir, run_id)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out: list[tuple[int, dict[str, Any] | None]] = []
    for name in names:
        m = _COPY_RE.match(name)
        if not m:
            continue
        doc: dict[str, Any] | None
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                loaded = json.load(fh)
            doc = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            doc = None
        out.append((int(m.group(1)), doc))
    return sorted(out, key=lambda x: x[0])


def inputs_at_review(analysis_dir: str) -> dict[str, Any]:
    try:
        with open(os.path.join(analysis_dir, "inputs.json"), encoding="utf-8") as fh:
            inputs = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(inputs, dict):
        return {}
    return {k: inputs[k] for k in _INPUT_KEYS if k in inputs}


def write_copy(analysis_dir: str, run_id: str, result: dict[str, Any], handoff_sha256: str) -> int:
    """Write this round's copy and return its round number. Raises OSError on failure."""
    d = copies_dir(analysis_dir, run_id)
    os.makedirs(d, exist_ok=True)
    existing = list_copies(analysis_dir, run_id)
    block = {"handoff_sha256": handoff_sha256, "inputs_at_review": inputs_at_review(analysis_dir)}
    for n, doc in existing:
        if isinstance(doc, dict) and _as_dict(doc.get(COPY_KEY)).get("handoff_sha256") == handoff_sha256:
            # The same hand-off re-piped: the same round, not a new one. Its content may refresh; its
            # baseline may not. Rebuilding the block here re-read inputs.json, so a figure edited
            # after the review became the round's own baseline and the rewrite went unreported.
            kept = {**_as_dict(doc.get(COPY_KEY)), "round": n}
            with open(os.path.join(d, f"redteam.r{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({**result, COPY_KEY: kept}, fh, indent=2)
            return n
    n = max([0, *(r for r, _ in existing)]) + 1
    while True:
        path = os.path.join(d, f"redteam.r{n}.json")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({**result, COPY_KEY: {**block, "round": n}}, fh, indent=2)
        return n


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def primary_run_id(docs: Iterable[Any]) -> str | None:
    """This run's id, from the required artifacts -- never from the review itself."""
    for doc in docs:
        rid = _as_dict(_as_dict(doc).get("metadata")).get("run_id")
        if isinstance(rid, str) and rid:
            return rid
    return None


def revision_approved(methodology: Any) -> bool:
    return _as_dict(_as_dict(methodology).get("red_team_revision")).get("approved_by_founder") is True


# Each message carries its own remedy. It is printed at the moment of action, which a rule
# further down SKILL.md is not.
_DELIVER = "Re-running or editing cannot fix this; deliver the report as it is."
MESSAGES = {
    "REDTEAM_ALTERED": (
        "The outside review was changed or removed after it was written. This report shows it as it "
        "was written. " + _DELIVER
    ),
    "REVIEW_COPY_MISSING": (
        "The outside review carries no record of how it was written, so nothing can show it is "
        "unchanged. Re-run the review step's producer command exactly as the skill gives it; never "
        "edit the review."
    ),
    "RED_TEAM_SKIP_CONTRADICTED": (
        "The analysis records that no outside review ran, but one did; this report shows it. " + _DELIVER
    ),
}


def rerun_message(rounds: int, approved: bool) -> str:
    if approved:
        why = f"The outside review was run {rounds} times; at most one founder-approved revision counts"
    else:
        why = (
            f"The outside review was run {rounds} times without the founder approving a revision, so "
            "only the first counts"
        )
    return f"{why}, and it is the one shown. {_DELIVER}"


_EARLIER_WINDOW_S = 24 * 3600


def earlier_reviews(analysis_dir: str, run_id: str, now: float | None = None) -> list[str]:
    """Other run ids in this analysis dir with a review copy written in the last 24 hours."""
    import time

    now = time.time() if now is None else now
    root = os.path.join(analysis_dir, "handoff")
    try:
        runs = sorted(os.listdir(root))
    except OSError:
        return []
    found: list[str] = []
    for other in runs:
        if other == run_id:
            continue
        d = os.path.join(root, other)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if _COPY_RE.match(name):
                try:
                    if now - os.path.getmtime(os.path.join(d, name)) <= _EARLIER_WINDOW_S:
                        found.append(other)
                        break
                except OSError:
                    continue
    return found


def resolve(
    analysis_dir: str,
    run_id: str | None,
    redteam: Any,
    methodology: Any,
) -> tuple[dict[str, Any] | None, list[tuple[str, str]], dict[str, Any]]:
    """(the review to show, [(code, message)], facts) for this run.

    With no copies, the review is `redteam` unchanged and nothing is checked -- a run made before
    copies existed, or a fixture. `facts` carries `rounds`, `round_shown`, `approved` and, when
    there is one, `inputs_at_review` of the first copy.
    """
    shown: dict[str, Any] | None = redteam if isinstance(redteam, dict) else None
    facts: dict[str, Any] = {"rounds": 0, "round_shown": None, "approved": revision_approved(methodology)}
    if not run_id:
        return shown, [], facts
    earlier = earlier_reviews(analysis_dir, run_id)
    earlier_codes: list[tuple[str, str]] = []
    if earlier:
        earlier_codes.append(
            (
                "EARLIER_REVIEW_THIS_ANALYSIS",
                f"An earlier run today also had this analysis reviewed ({', '.join(earlier)}); this report "
                "shows only this run's review. If the analysis was restarted to get a different review, "
                "say so to the founder; otherwise accept this with the reason.",
            )
        )
    copies = list_copies(analysis_dir, run_id)
    if not copies:
        codes: list[tuple[str, str]] = []
        rid = _as_dict(_as_dict(shown).get("metadata")).get("run_id")
        if shown is not None and rid == run_id and os.path.isdir(copies_dir(analysis_dir, run_id)):
            codes.append(("REVIEW_COPY_MISSING", MESSAGES["REVIEW_COPY_MISSING"]))
        return shown, earlier_codes + codes, facts

    codes = list(earlier_codes)
    usable = [(n, d) for n, d in copies if isinstance(d, dict)]
    rounds = len(copies)
    approved = facts["approved"]
    facts["rounds"] = rounds
    if usable:
        facts["inputs_at_review"] = _as_dict(_as_dict(usable[0][1].get(COPY_KEY)).get("inputs_at_review"))
    if rounds == 1 or (rounds == 2 and approved):
        pick = usable[-1] if usable else None
    else:
        pick = usable[0] if usable else None
        codes.append(("RED_TEAM_RERUN_UNAPPROVED", rerun_message(rounds, approved)))
    if pick is not None:
        facts["round_shown"] = pick[0]
        chosen: dict[str, Any] | None = strip(pick[1])
    else:
        chosen = shown
    latest = strip(usable[-1][1]) if usable else None
    if latest is None or shown != latest:
        codes.append(("REDTEAM_ALTERED", MESSAGES["REDTEAM_ALTERED"]))
    if _as_dict(methodology).get("red_team_skipped"):
        codes.append(("RED_TEAM_SKIP_CONTRADICTED", MESSAGES["RED_TEAM_SKIP_CONTRADICTED"]))
    return chosen, codes, facts


def approved_changes(methodology: Any) -> set[str]:
    """The inputs the founder confirmed changing, by field name, in the approved revision."""
    rev = _as_dict(_as_dict(methodology).get("red_team_revision"))
    if rev.get("approved_by_founder") is not True:
        return set()
    return {str(c.get("field")) for c in rev.get("changes") or [] if isinstance(c, dict) and c.get("field")}


def rewritten_inputs(before: dict[str, Any], inputs: Any, methodology: Any) -> list[tuple[str, Any, Any]]:
    """Founder-stated fields that differ from what the review saw and were not confirmed.

    Each field is compared across its value and its period, currency and source, because a changed
    period is a changed figure. Returns (field, value before, value now).
    """
    now = _as_dict(inputs)
    fields: set[str] = set()
    for key in _INPUT_KEYS:
        fields |= set(_as_dict(before.get(key))) | set(_as_dict(now.get(key)))
    confirmed = approved_changes(methodology)
    out: list[tuple[str, Any, Any]] = []
    for field in sorted(fields):
        if field in confirmed:
            continue
        was = [_as_dict(before.get(k)).get(field) for k in _INPUT_KEYS]
        is_ = [_as_dict(now.get(k)).get(field) for k in _INPUT_KEYS]
        if was != is_:
            out.append((field, was[0], is_[0]))
    return out


def revision_note(facts: dict[str, Any]) -> str | None:
    """The one line the founder reads about a revision round, or None."""
    if not facts.get("approved"):
        return None
    if facts.get("round_shown") == 2:
        return (
            "This analysis was revised once, with your approval, after an outside review; the review "
            "below is of the revised version."
        )
    if facts.get("rounds") == 1:
        return (
            "A revision was approved, but no new review of it completed; the review below is of the "
            "analysis before that revision."
        )
    return None
