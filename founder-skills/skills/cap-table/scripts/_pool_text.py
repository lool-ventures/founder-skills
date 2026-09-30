#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""The option pool's founder-facing text, in one place: the sizing labels, the comparison and new-options
digests, the report lines built from them, and the pool section each scenario shows.

report.md, report.html and explorer.html render the same section from here, so a figure or a label cannot
read one way on one page and another way on the next. The coaching commentary does not discuss the pool's
sizing: the section is the founder's explanation, computed from the scenario, never written by a model.
"""

from __future__ import annotations

import html
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _warning_callouts  # noqa: E402


def _percent(p: float) -> str:
    return f"{p * 100:.1f}%"


def _founders_pair(a: float, b: float) -> tuple[str, str, str]:
    """Founders' two figures and the change between them, for a pool comparison: at two decimals, and the
    change taken from the two DISPLAYED figures. At one decimal the pair could not be both exact and
    self-consistent -- 63.04 and 64.86 display as 63.0 and 64.9, so the change read either +1.9 (from
    the display) or +1.8 (exact) -- and a coach quoted "+1.7 points" for an exact 1.63."""
    left, right = f"{a * 100:.2f}%", f"{b * 100:.2f}%"
    change = float(right.rstrip("%")) - float(left.rstrip("%"))
    return left, right, f"{change:+.2f} points"


# What each measure counts, named by the share count it is taken against. "Pre-money basis" / "post-money basis"
# are gone from every founder surface: "pre-money pool" is VC shorthand for how EVERY pool's cost falls (created
# before the price, existing holders pay), and a pool labelled "pre-money basis" collided with it.
_AFTER_THE_ROUND = "fully diluted share count after the round"
_BEFORE_THE_ROUND = "fully diluted share count before the round"
_POOL_SIZING_DENOMINATOR = {
    "post_money": _AFTER_THE_ROUND,
    "pre_money": _BEFORE_THE_ROUND,
    # Solved only when no SAFE or note converts, where it is the post-money sizing exactly.
    "post_money_excluding_converting_securities": f"{_AFTER_THE_ROUND}, not counting converting securities",
}
# `target_basis` in words, for report.md's per-scenario Inputs list (which printed the raw enum).
TARGET_BASIS_WORDS = {
    "post_money": f"the {_AFTER_THE_ROUND}",
    "pre_money": f"the {_BEFORE_THE_ROUND}",
    "post_money_increase": f"only the new options, against the {_AFTER_THE_ROUND}",
    "post_money_excluding_converting_securities": f"the {_AFTER_THE_ROUND}, not counting converting securities",
    "custom": "a measure your documents define",
}


def pool_target_pct(target: float) -> str:
    """A pool target as a percentage at the precision it was given: 0.1 -> "10%", 0.125 -> "12.5%". The one
    formatter for every surface that prints the target, so a section can never show two different ones."""
    return f"{float(target) * 100:.2f}".rstrip("0").rstrip(".") + "%"


# The one bridge to a term sheet's own words, for the plain post-money measure only. "Pre-money" is never printed
# beside "pool".
_TERM_SHEET_BRIDGE = 'a term sheet writes this as a "{target} post-money pool"'


# The solver's basis gate: a refusal solves nothing; a substitution solves a different basis than requested.
_POOL_BASIS_BLOCKER_CODES = frozenset({"E_POOL_BASIS_NOT_MODELED", "E_POOL_BASIS_EXCLUDING_NOT_MODELED"})


# The pool-basis disclosures rendered beside their own scenario as well as in the report's callouts: the two
# substitutions, and the reading of a post-money pool taken beside existing unallocated options (either one).
_POOL_BASIS_SUBSTITUTED_CODES = (
    "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY",
    "W_CUSTOM_BASIS_STATED_BY_FOUNDER",
    "W_POOL_BASIS_READING_NOT_CONFIRMED",
    "W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY",
    "W_POOL_INCREASE_READING_UNAVAILABLE",
)


def _solved_pool_basis(params: dict[str, Any], co: dict[str, Any]) -> str | None:
    """The pool basis the solver actually used for this scenario, or None when there was no pool target or the
    basis was refused. Reported instead of the requested value: a refused scenario solved nothing, and a
    substituted one (the founder's choice or stated answer) solved a different basis, so naming the request
    would tell the coach the pool was sized on a basis it never was."""
    if not params.get("target_pool_percent") or co.get("completeness") not in {"full", "mixed"}:
        return None
    if any(str(b.get("code")) in _POOL_BASIS_BLOCKER_CODES for b in co.get("blockers") or [] if isinstance(b, dict)):
        return None
    warnings = [w for w in co.get("warnings") or [] if isinstance(w, dict)]
    if any(w.get("code") == "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY" for w in warnings):
        return "post_money"
    stated = next(
        (w.get("stated_basis") for w in warnings if w.get("code") == "W_CUSTOM_BASIS_STATED_BY_FOUNDER"), None
    )
    if isinstance(stated, str):
        return "post_money" if stated == "post_money_excluding_converting_securities" else stated
    basis = str(params.get("target_basis") or "pre_money")
    # With nothing converting, the gate passes the excluding basis through and it solves as post-money exactly.
    return "post_money" if basis == "post_money_excluding_converting_securities" else basis


_POOL_CF_HOLDERS = {
    "founders_pct": "Founders",
    "safe_pct": "SAFE holders",
    "note_pct": "Noteholders",
    "preferred_pct": "Preferred holders",
    "option_pool_pct": "Option pool, granted and unallocated",
    "new_money_pct": "New investors",
    "acquisition_pct": "Shares issued for the acquisition",
    "other_existing_pct": "Other existing holders",
}


_POOL_CF_STATUS = {
    "computed": "computed",
    "same_on_both_sizings": "same on both sizings",
    "not_computed": "not computed",
    "unavailable": "unavailable",
}


POOL_SIZING_MECHANISM = (
    "Under both sizings the pool is created before the round's price is set, so its cost falls almost "
    "entirely on the holders before the round; the sizing changes how large it is."
)


def _pool_sizing_label(basis: str | None, target: Any, *, topup: Any = None, excludes_acquisition: bool = False) -> str:
    if basis == "custom":
        return "a pool basis defined by your documents"
    if basis == "post_money_increase" and isinstance(target, (int, float)):
        # The percentage sizes the NEW options alone; the existing unallocated options sit on top of it. There is
        # no "already met" case: an increase is added whatever the existing pool holds.
        count = _AFTER_THE_ROUND + (", not counting shares issued for the acquisition" if excludes_acquisition else "")
        return (
            f"new options equal to {pool_target_pct(target)} of the {count}, on top of the existing unallocated options"
        )
    denom = _POOL_SIZING_DENOMINATOR.get(str(basis))
    if denom is None or not isinstance(target, (int, float)):
        return "the pool basis in your documents"
    # Name the NUMERATOR: the target counts only options still available for grant after the round
    # (`option_pool.py`), while the holder rows show the whole pool, granted options included. Real term
    # sheets also size a pool by its increase or by its total, so "10% post-money" alone is ambiguous.
    # Only a post-round count could include the acquisition's shares; a pre-round count never does.
    excluded = excludes_acquisition and denom.startswith(_AFTER_THE_ROUND)
    count = denom + (", not counting shares issued for the acquisition" if excluded else "")
    if isinstance(topup, (int, float)) and topup == 0:
        # The existing pool already covers the target on this side, so "equal to" would be false.
        return (
            f"unallocated options already at or above {pool_target_pct(target)} of the {count}, "
            "so no new options are added"
        )
    return f"unallocated options equal to {pool_target_pct(target)} of the {count}"


def build_pool_sizing_counterfactual_digest(cf: dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any] | None:
    """The payload's `pool_sizing_counterfactual`: founder-readable strings only -- no enum, no code.

    `change` is computed from the DISPLAYED percentages, so the coach can never quote a change that
    disagrees with the two figures beside it.
    """
    if not isinstance(cf, dict) or cf.get("status") not in _POOL_CF_STATUS:
        return None
    target = params.get("target_pool_percent")
    modeled_basis = cf.get("modeled_basis")
    topups = cf.get("pool_topup_shares") or {}
    excl_acq = _consideration_excluded_from_pool_sizing(params)
    if cf.get("modeled_as_approximation"):
        modeled_sizing = (
            f"{_pool_sizing_label('post_money', target, excludes_acquisition=excl_acq)}, used as an approximation "
            "of a pool that excludes converting securities"
        )
    else:
        modeled_sizing = _pool_sizing_label(
            modeled_basis, target, topup=topups.get("modeled"), excludes_acquisition=excl_acq
        )
    out: dict[str, Any] = {
        "status": _POOL_CF_STATUS[cf["status"]],
        "modeled_sizing": modeled_sizing,
        "modeled_basis_assumed": bool(cf.get("modeled_basis_assumed")),
    }
    if cf["status"] in {"not_computed", "unavailable"}:
        out["reason"] = str(cf.get("reason") or "")
        return out
    out["other_sizing"] = _pool_sizing_label(
        cf.get("other_basis"), target, topup=topups.get("other"), excludes_acquisition=excl_acq
    )
    founders = cf.get("founders") or {}
    f_mod, f_oth, change = _founders_pair(founders.get("modeled_value", 0.0), founders.get("other_value", 0.0))
    out["founders"] = {"modeled": f_mod, "other": f_oth, "change": change}
    if cf["status"] == "same_on_both_sizings":
        # Name WHICH choice is immaterial: beside a new-options-only line where founders move by points, a bare
        # "the sizing does not change the figures" would read as "the pool's reading does not matter".
        pair = (
            "measuring against the share count after the round or before it"
            if "pre_money" in {modeled_basis, cf.get("other_basis")}
            else "the two sizings"
        )
        out["note"] = (
            f"The existing pool already meets the target on both sizings, so choosing between {pair} does not "
            "change the figures."
            if not topups.get("modeled") and not topups.get("other")
            else "The two sizings differ by less than a tenth of a point for every holder."
        )
        return out
    classes = cf.get("classes") or {}
    rows = [
        {"holder": label, "modeled": _percent(classes[k]["modeled"]), "other": _percent(classes[k]["other"])}
        for k, label in _POOL_CF_HOLDERS.items()
        if k in classes
    ]
    if "other_existing_pct" not in classes:
        rows.append({"holder": _POOL_CF_HOLDERS["other_existing_pct"], "modeled": "0.0%", "other": "0.0%"})
    out["rows"] = rows
    pps = cf.get("price_per_share") or {}
    if isinstance(pps.get("modeled"), (int, float)) and isinstance(pps.get("other"), (int, float)):
        out["price_per_share"] = {"modeled": f"${pps['modeled']:.4f}", "other": f"${pps['other']:.4f}"}
    out["who_gains_on_the_other_sizing"] = [
        _POOL_CF_HOLDERS[k] for k in _POOL_CF_HOLDERS if k in (cf.get("gains_on_other_sizing") or [])
    ]
    out["mechanism"] = POOL_SIZING_MECHANISM
    out["other_solve_warnings"] = [_warning_callouts.humanize_warning(c) for c in cf.get("other_solve_warnings") or []]
    return out


def pool_sizing_counterfactual_line(digest: dict[str, Any] | None) -> str | None:
    """report.md's one line, from the same digest the coach reads."""
    if not digest:
        return None
    if digest["status"] == "computed":
        f = digest["founders"]
        other = digest["other_sizing"]
        return f"{other[0].upper()}{other[1:]}: founders {f['other']} (vs {f['modeled']} as modeled)."
    if digest["status"] == "same on both sizings":
        other = digest["other_sizing"]
        return f"{other[0].upper()}{other[1:]}: {digest['note'][0].lower()}{digest['note'][1:]}"
    return _not_computed_line(digest)


_POOL_INCREASE_STATUS = {
    "computed": "computed",
    "same_on_both_readings": "same on both readings",
    "not_computed": "not computed",
    "unavailable": "unavailable",
}


# report.md's lead for the new-options-only line; the paid lane's lever check looks for this exact text.
POOL_INCREASE_LINE_LEAD = "**If your term sheet sizes only the new options:**"


def _not_computed_line(digest: dict[str, Any]) -> str | None:
    """A comparison or reading the producer refused or could not solve, with the reason it wrote: the section
    says a figure is missing and why, rather than going silent."""
    reason = str(digest.get("reason") or "").strip()
    if digest.get("status") not in {"not computed", "unavailable"} or not reason:
        return None
    ft = _founder_text()
    if ft is not None:
        reason = ft.substitute(reason)
    return f"{digest['status'][0].upper()}{digest['status'][1:]}: {reason.rstrip('.')}."


def _founder_text() -> Any:
    """The fleet's founder-text policy from the plugin's shared `scripts/`; None if it cannot be imported, since
    a missing policy module must never block a report."""
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _shares(n: Any) -> str:
    return f"{round(float(n or 0)):,}"


def build_pool_increase_reading_digest(
    block: dict[str, Any] | None, params: dict[str, Any], *, modeled_reading: str
) -> dict[str, Any] | None:
    """The payload's `pool_increase_reading`: the figures if the term sheet's post-money percentage sizes only
    the new options. Founder-readable strings only; `change` and `additional` come from the DISPLAYED values,
    so the coach cannot quote a difference that disagrees with the two figures beside it."""
    if not isinstance(block, dict) or block.get("status") not in _POOL_INCREASE_STATUS:
        return None
    out: dict[str, Any] = {
        "status": _POOL_INCREASE_STATUS[block["status"]],
        "reading": _pool_sizing_label(
            "post_money_increase",
            params.get("target_pool_percent"),
            excludes_acquisition=_consideration_excluded_from_pool_sizing(params),
        ),
        "modeled_reading": modeled_reading,
    }
    if block["status"] in {"not_computed", "unavailable"}:
        out["reason"] = str(block.get("reason") or "")
        return out
    founders = block.get("founders") or {}
    f_mod, f_inc, change = _founders_pair(founders.get("modeled_value", 0.0), founders.get("increase_value", 0.0))
    out["founders"] = {"modeled": f_mod, "increase": f_inc, "change": change}
    topups = block.get("pool_topup_shares") or {}
    n_mod, n_inc = round(float(topups.get("modeled") or 0)), round(float(topups.get("increase") or 0))
    out["new_options"] = {"modeled": _shares(n_mod), "increase": _shares(n_inc), "additional": _shares(n_inc - n_mod)}
    pps = block.get("price_per_share") or {}
    if isinstance(pps.get("modeled"), (int, float)) and isinstance(pps.get("increase"), (int, float)):
        out["price_per_share"] = {"modeled": f"${pps['modeled']:.4f}", "increase": f"${pps['increase']:.4f}"}
    if block["status"] == "same_on_both_readings":
        out["note"] = "Sizing only the new options moves no holder by a tenth of a point or more."
    out["other_solve_warnings"] = [
        _warning_callouts.humanize_warning(c) for c in block.get("other_solve_warnings") or []
    ]
    return out


def pool_increase_reading_line(digest: dict[str, Any] | None) -> str | None:
    """report.md's one line under the scenario's disclosure, from the same digest the coach reads."""
    if not digest:
        return None
    if digest["status"] == "computed":
        f, n = digest["founders"], digest["new_options"]
        return (
            f"{POOL_INCREASE_LINE_LEAD} {n['increase']} new options instead of {n['modeled']} "
            f"({digest['reading']}), founders {f['increase']} (vs {f['modeled']} as modeled)."
        )
    if digest["status"] == "same on both readings":
        return f"{POOL_INCREASE_LINE_LEAD} {digest['note']}"
    line = _not_computed_line(digest)
    return f"{POOL_INCREASE_LINE_LEAD} {line}" if line else None


def _pool_digests(co: dict[str, Any], params: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The comparison's digest and the new-options-only reading's, built together: the reading names the
    modeled sizing in the comparison's own words."""
    cf = build_pool_sizing_counterfactual_digest(co.get("pool_sizing_counterfactual"), params)
    modeled = (cf or {}).get("modeled_sizing") or _pool_sizing_label("post_money", params.get("target_pool_percent"))
    return cf, build_pool_increase_reading_digest(co.get("pool_increase_reading"), params, modeled_reading=modeled)


def _unallocated_pool_pct(co: dict[str, Any], cap_state: dict[str, Any]) -> float | None:
    """Unallocated options after the round (existing available + top-up) as a share of post-round FD.

    The scenario's own post-pump state wins over the pre-round artifact: it is what the solver used.
    None when the scenario carries no post-round share count to divide by.
    """
    post_fd = co.get("post_round_fully_diluted_shares")
    if not isinstance(post_fd, (int, float)) or post_fd <= 0:
        return None
    ats = ((co.get("cap_state_after_pump") or {}).get("as_converted_totals")) or (
        cap_state.get("as_converted_totals") or {}
    )
    available = float(ats.get("options_available", 0) or 0)
    topup = float((co.get("shares_breakdown") or {}).get("pool_topup", 0) or 0)
    return (available + topup) / float(post_fd)


def _consideration_excluded_from_pool_sizing(params: dict[str, Any]) -> bool:
    """Whether the solver sized the pool on a base WITHOUT the acquisition's consideration shares.

    `pool_consideration_basis: exclude` takes effect only when the scenario's own acquisition reached the
    solver, which `run_scenario.py` allows only for a concurrent acquisition. An acquisition that closed
    before the round is already in the pre-round cap table, so its shares sit inside the sizing base
    whatever the parameter says.
    """
    acq = params.get("acquisition")
    return (
        params.get("pool_consideration_basis") == "exclude"
        and isinstance(acq, dict)
        and acq.get("acquisition_timing", "concurrent_with_round") == "concurrent_with_round"
    )


def build_pool_basis_note(
    *,
    target_pool_percent: float | None,
    pool_consideration_basis: str,
    realized_pool_pct: float,
    acquisition_pct: float | None,
    target_basis: str | None = None,
    unallocated_pool_pct: float | None = None,
    pool_topup_shares: float | None = None,
    consideration_excluded: bool | None = None,
) -> str:
    """Labeled option-pool sizing-basis note for acquisition deals. Returns '' unless there is BOTH an
    acquisition (acquisition_pct truthy) AND a pool (target_pool_percent truthy).

    Every sentence describes what the solver DID, not what a parameter asked for:
    - `realized_pool_pct` is the WHOLE pool (granted + unallocated + top-up); the target sizes unallocated
      options only, so the sized figure comes from `unallocated_pool_pct` and the whole pool is named as the
      whole pool when granted options make the two differ.
    - `consideration_excluded` says whether the sizing base left out the acquisition's shares (see
      `_consideration_excluded_from_pool_sizing`); None falls back to the parameter.
    - a pre-money sizing is of the pre-round share count, which the consideration never enters.
    - a top-up of zero means nothing was sized: the existing unallocated options already met the target.
    Without `unallocated_pool_pct` the caller has no granted options to separate, and the two are equal.
    """
    if not acquisition_pct or not target_pool_percent:
        return ""
    free_pct = realized_pool_pct if unallocated_pool_pct is None else unallocated_pool_pct
    whole = (
        f"; counting granted options, the whole pool is {realized_pool_pct:.1%}"
        if realized_pool_pct - free_pct > 0.0005
        else ""
    )
    excluded = pool_consideration_basis == "exclude" if consideration_excluded is None else consideration_excluded
    post = "post-closing combined fully-diluted, the acquisition's consideration shares included"
    if target_basis == "pre_money":
        base = f"the {_BEFORE_THE_ROUND} (the acquisition's shares do not enter it)"
    elif excluded:
        base = "pre-consideration fully-diluted"
    else:
        base = "post-closing combined fully-diluted, the acquisition's consideration shares counted"
    target = pool_target_pct(target_pool_percent)
    if pool_topup_shares is not None and pool_topup_shares == 0:
        return (
            f"Option pool sizing basis: no new options were added -- the existing unallocated options already "
            f"meet the {target} target on {base}; they are {free_pct:.1%} of {post}{whole}."
        )
    if target_basis == "post_money_increase":
        # The percentage sizes the new options alone, so it is never stated as the pool's size.
        return (
            f"Option pool sizing basis: new options equal to {target} of {base}, on top of the existing "
            f"unallocated options; unallocated options are {free_pct:.1%} of {post}{whole}."
        )
    if target_basis != "pre_money" and not excluded:
        # Sized on the post-closing count itself, so restating it "as a share of post-closing" says nothing.
        return f"Option pool sizing basis: unallocated options sized to {target} of {base}{whole}."
    return (
        f"Option pool sizing basis: unallocated options sized to {target} of {base}, which is "
        f"{free_pct:.1%} of {post}{whole}."
    )


# --- the pool section each scenario shows -------------------------------------------------------------------

POOL_SECTION_HEADING = "**Option pool**"
# What the coaching commentary may say about the pool: that it is a dilution driver, and where it is explained.
POOL_DRIVER_REFERENCE = "The report's Option pool section explains how this pool was sized."
# The pool-basis disclosures: rendered in the Option pool section, handed to the main thread for the hand-over,
# never to the coach.
POOL_DISCLOSURE_CODES = frozenset(
    {
        "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY",
        "W_CUSTOM_BASIS_STATED_BY_FOUNDER",
        "W_POOL_BASIS_READING_NOT_CONFIRMED",
        "W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY",
        "W_POOL_INCREASE_READING_UNAVAILABLE",
    }
)


def pool_section_codes(scenario: dict[str, Any]) -> frozenset[str]:
    """The disclosures a scenario's Option pool section states. A surface that renders the section leaves them out
    of its global callouts, so each is stated once, beside the scenario it applies to."""
    if not ((scenario or {}).get("parameters") or {}).get("target_pool_percent"):
        return frozenset()
    return frozenset(_POOL_BASIS_SUBSTITUTED_CODES)


POOL_DISCLOSURE_POINTER = "See the Option pool section of the report."
POOL_CF_LINE_LEAD = "**Option pool on the other sizing:**"
# How the modeled pool's cost falls, said of this pool only and only when options are added. Scoping it to the
# modeled pool matters: a coach explaining the pool in its own words called a post-money pool "the standard
# pre-money pool mechanics", the VC name for this mechanism, which both sizings share.
POOL_CREATED_BEFORE_PRICE = (
    "It is created before the round's price is set, so its cost falls almost entirely on the holders before the round."
)
POOL_COUNSEL_ACTION = "Confirm with counsel that your term sheet measures the pool the way this section describes."
POOL_ASSUMED_CALLOUT = (
    "**What the pool target counts was ASSUMED, not stated.** No measure was given for this scenario, so the "
    f"target was taken as a share of the {_BEFORE_THE_ROUND}. Measuring it against the share count after the "
    "round instead changes the pool top-up and post-round ownership; confirm what your term sheet's percentage "
    "counts before relying on these figures."
)


def pool_measure_sentence(scenario: dict[str, Any]) -> str:
    """What the scenario's pool target counts, in one sentence. The plain post-money measure carries the one
    bridge to a term sheet's words; no other measure does."""
    params = scenario.get("parameters") or {}
    co = scenario.get("computed_outputs") or {}
    target = params.get("target_pool_percent")
    basis = _solved_pool_basis(params, co)
    topup = (co.get("shares_breakdown") or {}).get("pool_topup")
    acquisition = _consideration_excluded_from_pool_sizing(params)
    if not isinstance(target, (int, float)):
        return ""
    t = pool_target_pct(target)
    if basis == "post_money_increase":
        count = _AFTER_THE_ROUND + (", not counting shares issued for the acquisition" if acquisition else "")
        return (
            f"The new options added in the round equal {t} of the {count}, on top of the existing unallocated options."
        )
    denom = _POOL_SIZING_DENOMINATOR.get(str(basis))
    if denom is None:
        return "The pool is measured the way your documents define it."
    count = denom + (
        ", not counting shares issued for the acquisition" if acquisition and denom.startswith(_AFTER_THE_ROUND) else ""
    )
    if isinstance(topup, (int, float)) and topup == 0:
        core = (
            f"The unallocated options after the round are already at or above {t} of the {count}, "
            "so no new options are added"
        )
    else:
        core = f"The unallocated options after the round equal {t} of the {count}"
    # The solver's disclosure is the signal, as in run_scenario, so the fast path (which computes no comparison)
    # reads it too. Such a term sheet does not write this pool as a plain "post-money pool", so no bridge.
    approximated = any(
        isinstance(w, dict) and w.get("code") == "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY"
        for w in co.get("warnings") or []
    )
    if basis == "post_money" and not approximated:
        core += f" ({_TERM_SHEET_BRIDGE.format(target=t)})"
    if approximated:
        core += ", used here as an approximation of a pool measured without the converting securities"
    return core + "."


def pool_section(scenario: dict[str, Any], cap_state: dict[str, Any]) -> list[dict[str, str]]:
    """The pool's explanation for one scenario, as items every surface renders the same way; empty when the
    scenario has no pool target.

    Items: `text` (a sentence), `callout` (a disclosure), `note` (the acquisition sizing note), `line` (a lead
    and its text), `action` (what to take to counsel). Figures come from the same digests report.md's lines
    always used, so no surface can round or label them differently.
    """
    params = scenario.get("parameters") or {}
    co = scenario.get("computed_outputs") or {}
    target = params.get("target_pool_percent")
    if not target:
        return []
    items: list[dict[str, str]] = []
    cf_digest, inc_digest = _pool_digests(co, params)
    topup = (co.get("shares_breakdown") or {}).get("pool_topup")
    # The measure the solver used, named by what it counts -- for a document-defined basis, the one the founder
    # said it matches.
    items.append({"kind": "text", "text": pool_measure_sentence(scenario)})
    if isinstance(topup, (int, float)) and topup > 0:
        items.append({"kind": "text", "text": POOL_CREATED_BEFORE_PRICE})
    warnings = [w for w in co.get("warnings") or [] if isinstance(w, dict)]
    if any(w.get("code") == "target_basis_defaulted" for w in warnings):
        items.append({"kind": "callout", "text": POOL_ASSUMED_CALLOUT})
    for w in warnings:
        if w.get("code") in _POOL_BASIS_SUBSTITUTED_CODES:
            items.append({"kind": "callout", "text": _warning_callouts._SOLVER_WARNING_PROSE[w["code"]]})
            if w["code"] == "W_POOL_BASIS_READING_NOT_CONFIRMED":
                # An unavailable reading that the solver also disclosed is stated by that callout; the reason line
                # would say it a second time.
                said = (inc_digest or {}).get("status") == "unavailable" and any(
                    x.get("code") == "W_POOL_INCREASE_READING_UNAVAILABLE" for x in warnings
                )
                inc_line = None if said else pool_increase_reading_line(inc_digest)
                if inc_line:
                    items.append(
                        {
                            "kind": "line",
                            "lead": POOL_INCREASE_LINE_LEAD,
                            "text": inc_line[len(POOL_INCREASE_LINE_LEAD) :].strip(),
                        }
                    )
    agg = co.get("aggregate_ownership_by_class") or {}
    if co.get("completeness") in {"full", "mixed"} and agg:
        note = build_pool_basis_note(
            target_pool_percent=target,
            pool_consideration_basis=params.get("pool_consideration_basis", "include"),
            realized_pool_pct=agg.get("option_pool_pct") or 0.0,
            acquisition_pct=agg.get("acquisition_pct"),
            target_basis=_solved_pool_basis(params, co),
            unallocated_pool_pct=_unallocated_pool_pct(co, cap_state),
            pool_topup_shares=topup,
            consideration_excluded=_consideration_excluded_from_pool_sizing(params),
        )
        if note:
            items.append({"kind": "note", "text": note})
        cf_line = pool_sizing_counterfactual_line(cf_digest)
        if cf_line:
            items.append({"kind": "line", "lead": POOL_CF_LINE_LEAD, "text": cf_line})
    items.append({"kind": "action", "text": POOL_COUNSEL_ACTION})
    return items


def pool_section_markdown(items: list[dict[str, str]]) -> list[str]:
    """report.md's lines for a pool section, each followed by a blank line; empty for no section."""
    if not items:
        return []
    out = [POOL_SECTION_HEADING, ""]
    for it in items:
        kind, text = it["kind"], it["text"]
        if kind == "callout":
            out.append(f"> ⚠ {text}")
        elif kind == "note":
            out.append(f"> _{text}_")
        elif kind == "line":
            out.append(f"{it['lead']} {text}")
        else:
            out.append(text)
        out.append("")
    return out


def _inline_html(text: str) -> str:
    """Escape, then keep the section's one markup: **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text, quote=False))


def pool_section_html(items: list[dict[str, str]]) -> str:
    """The same section for report.html and explorer.html; empty for no section. Every string is escaped."""
    if not items:
        return ""
    parts = ['<div class="pool-section"><h4>Option pool</h4>']
    for it in items:
        kind, text = it["kind"], _inline_html(it["text"])
        if kind == "callout":
            parts.append(f'<p class="pool-callout">⚠ {text}</p>')
        elif kind == "note":
            parts.append(f'<p class="pool-note"><em>{text}</em></p>')
        elif kind == "line":
            parts.append(f"<p>{_inline_html(it['lead'])} {text}</p>")
        elif kind == "action":
            parts.append(f'<p class="pool-action">{text}</p>')
        else:
            parts.append(f"<p>{text}</p>")
    parts.append("</div>")
    return "".join(parts)
