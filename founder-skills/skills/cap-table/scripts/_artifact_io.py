"""Shared predicates over cap-table artifacts -- the ONE definition of each question.

Every function here answers a question several scripts ask about the same artifact shape, so
that the answer cannot drift between copies: is this id missing, which series carry a stale
conversion price, does this fully-diluted total agree with its own components. Scripts import
this module by path and call the predicates at their own point of use; the module reads no
file and raises nothing.

This module used to also carry a typed LOADER (`load_cap_state` and siblings) that validated
schema version, mirror drift and semantic invariants on read. It had zero production callers --
every consumer reads the artifacts with a bare `json.load` -- so every check it enforced ran
only in one test file, and two of them (`E_FD_SUM_MISMATCH`, `E_FOUNDER_SHARES_REQUIRED`) sat
in the mutation corpus as known survivors for exactly that reason. The loader is gone. The
checks that had teeth were moved to the site where the artifact is actually read: the FD-sum
invariant is now `run_scenario`'s precondition (`fd_sum_mismatch`), the deprecated-key
rejection is `build_cap_state`'s (`deprecated_instrument_key`), and the founder-shares
invariant was already live in `build_cap_state` and merely duplicated here.
"""

from __future__ import annotations

from typing import Any


def row_by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any] | None:
    """Look one row out of a per-instrument LIST by its id.

    The per-instrument outputs (`per_safe`, `per_note`) are lists of rows, each carrying its own
    `id`, rather than dicts keyed by id. That is deliberate and it is the structural half of the
    id-collapse fix: a dict keyed by an id read out of a founder's PDF silently drops a row when two
    ids collide, and no amount of downstream checking can recover the dropped one. A list cannot
    lose a row.

    THIS FUNCTION IS NOT A WAY BACK TO THE DICT. It answers "which row is this id" for the handful
    of callers that genuinely need a single lookup; it does NOT build an index, so re-collapsing the
    list by id is not something a caller can do by accident. Duplicate ids are refused upstream
    (`instrument_id_blockers`, `cap_state._check_unique_ids`), so a match here is unambiguous — but
    if one ever slipped through, this returns the FIRST match and the other row still exists in the
    list, visible to every renderer. Wrong label, not vanished money.
    """
    for row in rows:
        if isinstance(row, dict) and row.get("id") == row_id:
            return row
    return None


def id_missing(value: Any) -> bool:
    """THE definition of "this instrument has no id", for the whole skill.

    Three states must stay distinct and they have three different remedies:
      * MISSING (this function) -- "give it an id";
      * DUPLICATE -- "make the ids distinct";
      * present-and-unique -- fine.
    Collapsing missing into duplicate produces a diagnostic naming an id the founder never wrote
    (`None` or `""`), which is why they are separate codes downstream.

    WHY THIS EXISTS AS ONE FUNCTION. The same decision was made independently in five places and
    disagreed with itself: `cap_state`'s required-field checks test `"id" not in row`, so a blank
    string PASSES them; `_check_unique_ids` skipped blanks; `safe_conversion` and `priced_round`
    treated `in (None, "")` as missing, which is the correct call. The gap between the first two
    and the last two is exactly the width of the empty string, and a founder-facing wrong number
    lived in it: two convertible notes with `id: ""` reported 720,000 shares against a true
    1,120,000, `completeness: "full"`, zero blockers. One predicate, imported everywhere, is what
    stops that gap reopening at the next site.

    Blank-after-strip counts as missing: `" "` is not an identifier anyone typed on purpose, and
    it collides in a dict exactly as `""` does.

    NON-STR COUNTS AS MISSING, and that is defense rather than policy: `instruments.schema.json`
    types every instrument `id` as `{"type": "string"}` (verified), so a non-str id is an upstream
    schema failure. Treating it as missing yields a typed, founder-legible refusal instead of a
    `TypeError` from a dict lookup or an `AttributeError` from `.strip()`.
    """
    if value is None or not isinstance(value, str):
        return True
    return not value.strip()


def instrument_id_blockers(
    items: list[dict[str, Any]],
    label: str,
    *,
    id_field: str = "id",
) -> list[dict[str, Any]]:
    """Blockers for an instrument list whose ids would collapse the per-item output.

    Generalizes `priced_round._duplicate_id_blockers` so every consumer states the same rule.
    Returns the scenario-route refusal shape (`code` / `instance_id` / `remedy`); producers that
    exit rather than return blockers should raise on a non-empty result.

    Ids key the per-item outputs across this skill (`per_safe`, `per_note`, `results_by_id`, the
    CP1 snapshots, the founder breakdown), so a repeat reports one row for two instruments while
    both still count toward the totals -- the summary and the detail disagree, with no warning.
    """
    missing = sum(1 for i in items if not isinstance(i, dict) or id_missing(i.get(id_field)))
    out: list[dict[str, Any]] = []
    if missing:
        out.append(
            {
                "code": "E_INSTRUMENT_ID_MISSING",
                "instance_id": None,
                "remedy": (
                    f"{missing} of {len(items)} {label} carry no id. Ids key the per-item output, so "
                    "an instrument without one cannot be reported separately from the others. Give "
                    "each one a distinct id."
                ),
            }
        )
    ids = [i.get(id_field) for i in items if isinstance(i, dict) and not id_missing(i.get(id_field))]
    dupes = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dupes:
        out.append(
            {
                "code": "E_INSTRUMENT_DUPLICATE_ID",
                "instance_id": ",".join(dupes),
                "remedy": (
                    f"{len(items)} {label} carry {len(dupes)} duplicated id(s): {', '.join(dupes)}. "
                    "Ids key the per-item output, so a repeat would show one row for two instruments "
                    "while both count toward the totals -- the summary and the detail would disagree. "
                    "Give each one a distinct id."
                ),
            }
        )
    return out


def series_has_prior_ad_event(series_id: str, cap_table_history: list[dict[str, Any]]) -> bool:
    """Does the recorded history contain an anti-dilution adjustment for this series?"""
    return any(
        h.get("event_type") == "anti_dilution_applied" and h.get("series_id") == series_id
        for h in (cap_table_history or [])
    )


def stale_ccp_series_ids(preferred_series: list[dict[str, Any]], cap_table_history: list[dict[str, Any]]) -> list[str]:
    """Series whose history records an adjustment while their price says none happened.

    THE ONE definition of "stale conversion price", shared by every consumer rather than copied.
    Two places ask this question -- the cap-state builder and the priced-round solver -- and
    until they shared a function there were two divergent copies. This repo has already
    paid for a third copy of one derivation drifting from the other two.

    Works on either `inputs.json` or `cap_state.json`: both carry `preferred_series` and
    `cap_table_history` in the same shape.
    """
    out = []
    for s in preferred_series or []:
        ccp, ocp = s.get("current_conversion_price"), s.get("original_conversion_price")
        if ccp is None or ocp is None or abs(float(ccp) - float(ocp)) > 1e-9:
            continue
        sid = s.get("series_id")
        if sid and series_has_prior_ad_event(str(sid), cap_table_history):
            out.append(str(sid))
    return out


def stale_ccp_warning(series_id: str, ccp: Any, ocp: Any) -> str:
    """The founder-facing warning string, so the wording cannot drift between emitters."""
    return (
        f"W_STALE_CCP_SUSPECTED: series {series_id} records a prior anti-dilution adjustment, but its "
        f"current conversion price ({ccp}) still equals its original ({ocp}). If that earlier "
        "adjustment was applied, this price is out of date and every ownership figure derived from it "
        "understates the preferred holders' position."
    )


def fd_sum_mismatch(cap_state: dict[str, Any]) -> dict[str, int] | None:
    """Does `as_converted_totals.fully_diluted_shares` disagree with the sum of its own components?

    `build_cap_state` computes the total AS that sum, so checking it at write time is a
    tautology. It has teeth only where the artifact is read back -- a hand-edited
    `cap_state.json` fed to the math would otherwise carry a fully-diluted denominator that
    contradicts the rows it is supposedly derived from, and every percentage downstream is
    measured against it. Returns the two figures on disagreement so the caller can say
    which, or None.
    """
    totals = cap_state.get("as_converted_totals") or {}
    if not totals:
        return None
    expected = (
        int(totals.get("common_shares", 0))
        + int(totals.get("preferred_shares_as_converted", 0))
        + int(totals.get("options_outstanding", 0))
        + int(totals.get("options_available", 0))
        + int(totals.get("warrants_underlying_total", 0))
    )
    actual = int(totals.get("fully_diluted_shares", 0))
    if expected != actual:
        return {"expected": expected, "actual": actual}
    return None


def deprecated_instrument_key(instruments: dict[str, Any]) -> str | None:
    """The v0.4.x top-level key an instruments.json still uses, if any.

    `notes` was renamed to `convertible_notes` in v0.5.0. A file carrying the old key with no new
    one is not a file with no notes: it is a file whose notes every downstream number will silently
    omit, since nothing reads the old key. Refusing at the first read is the only place that
    consequence can be named.
    """
    if "notes" in instruments and "convertible_notes" not in instruments:
        return "notes"
    return None
