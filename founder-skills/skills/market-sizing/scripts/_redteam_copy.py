"""Market-sizing's side of the adversarial review's copies: what a sizing review is taken against.

Which review the founder is shown, and why the answer comes from append-only copies rather than from
`redteam.json`, is decided in the plugin's shared `scripts/_redteam_core.py` -- the same rules serve
every skill with a reviewer, and a rule with two copies drifts. What stays here is what only a sizing
has: the founder's stated figures as the review saw them (`inputs_at_review`), each sizing input and
research record entry as it stood (`reviewed_state`), and the stated figures rewritten since
(`rewritten_inputs`).

The shared module is loaded by path on FIRST USE, never at import: `red_team.py` imports this file at
the top, and a copy of the skill's scripts without the plugin around them must still reach its own
"shared scripts are not reachable" refusal rather than a traceback.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable, Iterable
from typing import Any

_SHARED_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
)
# The founder's stated figures as they stood when the review was written -- the baseline a later
# rewrite of them is compared against.
_INPUT_KEYS = (
    "founder_stated_inputs",
    "founder_stated_inputs_period",
    "founder_stated_inputs_currency",
    "founder_stated_inputs_source",
)


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


def copies_dir(analysis_dir: str, run_id: str) -> str:
    return str(core().copies_dir(analysis_dir, run_id))


def strip(doc: dict[str, Any]) -> dict[str, Any]:
    return dict(core().strip(doc))


def list_copies(analysis_dir: str, run_id: str) -> list[tuple[int, dict[str, Any] | None]]:
    return list(core().list_copies(analysis_dir, run_id))


def inputs_at_review(analysis_dir: str) -> dict[str, Any]:
    try:
        with open(os.path.join(analysis_dir, "inputs.json"), encoding="utf-8") as fh:
            inputs = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(inputs, dict):
        return {}
    return {k: inputs[k] for k in _INPUT_KEYS if k in inputs}


def _load(analysis_dir: str, name: str) -> Any:
    try:
        with open(os.path.join(analysis_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def reviewed_state(analysis_dir: str) -> dict[str, Any]:
    """What a review is taken against: each sizing input's reference and consumed value (with the
    record entries it depends on), and every quantitative research record entry as it stands.

    It is written INTO the review, not into the copy's own bookkeeping, so an edit of it is an edit
    of the review and is reported as one. Empty parts for a sizing from before inputs carried
    their provenance.
    """
    import _provenance

    sizing = _as_dict(_load(analysis_dir, "sizing.json"))
    state: dict[str, Any] = {"sizing": {}, "record": {}}
    if sizing.get("provenance_version") == 1:
        refs = _as_dict(sizing.get("input_refs"))
        for param, entry in _as_dict(sizing.get("input_provenance")).items():
            e = _as_dict(entry)
            state["sizing"][param] = {
                "ref": refs.get(param),
                "value_consumed": e.get("value_consumed"),
                "entries": list(e.get("entries") or []),
            }
    state["record"] = _provenance.record_snapshot(
        _load(analysis_dir, "validation.json"), _load(analysis_dir, "inputs.json")
    )
    return state


def write_copy(analysis_dir: str, run_id: str, result: dict[str, Any], handoff_sha256: str) -> int:
    """Write this round's copy and return its round number. Raises OSError on failure.

    Sets `result["inputs_reviewed"]` in place, so `redteam.json` and the copy carry the same one.
    """
    return int(
        core().write_copy(
            analysis_dir,
            run_id,
            result,
            handoff_sha256,
            reviewed_state=lambda: reviewed_state(analysis_dir),
            block_extra=lambda: {"inputs_at_review": inputs_at_review(analysis_dir)},
        )
    )


def primary_run_id(docs: Iterable[Any]) -> str | None:
    """This run's id, from the required artifacts -- never from the review itself."""
    rid = core().primary_run_id(docs)
    return rid if isinstance(rid, str) else None


def earlier_reviews(analysis_dir: str, run_id: str, now: float | None = None) -> list[str]:
    return list(core().earlier_reviews(analysis_dir, run_id, now))


def resolve(
    analysis_dir: str,
    run_id: str | None,
    redteam: Any,
    methodology: Any,
    *,
    same_as_now: Callable[[Any], bool],
) -> tuple[dict[str, Any] | None, list[tuple[str, str]], dict[str, Any]]:
    """(the review to show, [(code, message)], facts) for this run -- `_redteam_core.resolve`, with a
    sizing's skip record and its copies' `inputs_at_review` / `inputs_at_shown` baselines.

    With no copies, the review is `redteam` unchanged and nothing is checked. When no review is of the
    analysis as delivered, the latest is shown and RECORD_CHANGED_AFTER_REVIEW says what changed after it.
    """
    chosen, codes, facts = core().resolve(
        analysis_dir,
        run_id,
        redteam,
        skipped=bool(_as_dict(methodology).get("red_team_skipped")),
        same_as_now=same_as_now,
    )
    if "first_block" in facts:
        facts["inputs_at_review"] = _as_dict(facts.pop("first_block").get("inputs_at_review"))
    if "shown_block" in facts:
        facts["inputs_at_shown"] = _as_dict(facts.pop("shown_block").get("inputs_at_review"))
    return chosen, codes, facts


def rewritten_inputs(before: dict[str, Any], inputs: Any) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Founder-stated fields that differ from what the FIRST review saw: (field, then, now).

    `then` / `now` hold the field's value, period, currency and source as the founder's figures record
    them, because a changed period is a changed figure. Keyed on the first review only: a check that a
    later review could clear is cleared by re-dispatching the review, and this is the one thing the
    founder has to be told about. Nothing here reads an approval; the change is stated as a fact, and
    it is still true when the founder chose it.
    """
    now = _as_dict(inputs)
    fields: set[str] = set()
    for key in _INPUT_KEYS:
        fields |= set(_as_dict(before.get(key))) | set(_as_dict(now.get(key)))
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for field in sorted(fields):
        was = {k: _as_dict(before.get(k)).get(field) for k in _INPUT_KEYS}
        is_ = {k: _as_dict(now.get(k)).get(field) for k in _INPUT_KEYS}
        if was != is_:
            out.append((field, was, is_))
    return out
