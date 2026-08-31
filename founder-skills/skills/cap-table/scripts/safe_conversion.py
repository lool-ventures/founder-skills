#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""SAFE conversion math (YC post-money primer + Cooley/NVCA references).

Implements `safe.post_money_cap_conversion` and `safe.discount_rate_semantics`
from `cap-table-rules.json` (v0.2.8+). The `company_capitalization` denominator
is supplied by the caller (typically `cap_state.as_converted_totals.fully_diluted_shares`
per the §5.1 binding table) and MUST be the pre-financing snapshot.

Per Gotcha #3: `discount_multiplier = 0.80` means 20% discount (multiplier
form, not percent). Per Gotcha #1: never include new-money or post-financing
pool increases in `company_capitalization`.

Two output sets (per §5.1 cap-implied vs post-financing split):

  * Cap-implied set — works standalone with cap + company_capitalization
    only. Produces cap_implied_ownership, safe_price, cap-implied shares.
  * Post-financing set — requires a priced-round price (equity_financing_price)
    OR conversion_price_override. Produces conversion shares + ownership %.

Hard-rejected cases (see Gotcha #4):
  * yc_postmoney_discount with no priced round / override → caller's job
    (E_SAFE_REQUIRES_CONVERSION_EVENT).
  * yc_uncapped_mfn with no priced round / override / MFN trigger → same.

Usage as a library:
    from safe_conversion import convert_safe_cap_implied, convert_safe_priced_round
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _emit import add_output_args, emit  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402

# Typed error codes (mirror design doc §5.1)
E_SAFE_REQUIRES_CONVERSION_EVENT = "E_SAFE_REQUIRES_CONVERSION_EVENT"
E_SAFE_CAP_MISSING_DENOMINATOR = "E_SAFE_CAP_MISSING_DENOMINATOR"
# Stacked post-money SAFEs reserving >= 100% of the company. The rule pack authorises the refusal
# directly: `safe.stacked_post_money_caps` -> "Block or escalate when aggregate SAFE ownership is
# greater than or equal to 100 percent." Distinct from the priced path's E_SOLVER_* codes, which
# describe an iteration that failed to converge; here the infeasibility is closed-form and exact.
E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE = "E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE"
E_SAFE_DUPLICATE_INSTRUMENT_ID = "E_SAFE_DUPLICATE_INSTRUMENT_ID"
E_SAFE_INSTRUMENT_ID_MISSING = "E_SAFE_INSTRUMENT_ID_MISSING"
E_SAFE_CIRCULAR_MFN = "E_SAFE_CIRCULAR_MFN"
E_SAFE_INVALID_PRICE_INPUT = "E_SAFE_INVALID_PRICE_INPUT"
E_UNKNOWN_SAFE_FORM = "E_UNKNOWN_SAFE_FORM"


def safe_has_usable_purchase_amount(safe: dict[str, Any]) -> bool:
    """True iff the SAFE has a real, positive purchase_amount (so its conversion math can run).

    A blank/template SAFE with a missing/zero/non-numeric purchase amount is terms-only (non-convertible).
    """
    amt = safe.get("purchase_amount")
    return isinstance(amt, (int, float)) and not isinstance(amt, bool) and amt > 0


def convert_safes_cap_implied(
    safes: list[dict[str, Any]],
    *,
    pre_financing_fd: int | float,
) -> dict[str, Any]:
    """Cap-implied output for a SET of post-money SAFEs (standalone; no priced round).

    WHY THIS IS SET-LEVEL AND NOT PER-INSTRUMENT — the shape of the bug it fixes.

    The YC post-money SAFE's "Company Capitalization" is SELF-INCLUSIVE: it counts the shares
    issuable on conversion of the SAFEs themselves (rule `safe.company_capitalization_yc_post_money`
    — "including … converting securities"). That is the defining property of the post-money form and
    the reason an investor's percentage is locked against dilution from other SAFEs.

    The previous per-instrument version divided the cap by the PRE-financing FD count, which omits
    the converting SAFEs, and it was called once per SAFE with that same base. Two consequences, both
    shipped to founders:
      * the three outputs disagreed with each other — a $500k SAFE at a $5M post cap against 8,000,000
        shares rendered as "10.0% cap-implied (800,000 shares)", and 800,000 shares is 9.09%;
      * the priced-round path, which solves the fixed point, returned 888,889 shares for the SAME
        instrument, so one report converted one SAFE two ways.

    The denominator is a fixed point, and the rule pack already states its closed form
    (`safe.stacked_post_money_caps`, which no producer implemented until now):

        pct_i  = purchase_i / cap_i
        total  = pre_financing_fd / (1 - Σ pct_i)
        price_i = cap_i / total
        shares_i = purchase_i / price_i          ( = pct_i × total )

    `pre_financing_fd` is the PRE-financing fully-diluted count — the name is deliberate. It already
    includes options outstanding, the available pool and vested warrants (`cap_state.py`), which the
    rule also requires. It is NOT the Company Capitalization; this function derives that (`total`)
    from it. The identically-named parameter on `convert_safe_priced_round` means the post-money CC,
    and conflating the two is how this defect happened.

    ALL-OR-NOTHING BY DESIGN: if any SAFE in the set cannot be priced, the whole set is rejected. A
    dropped member would be missing from `total` while still being a converting security, silently
    inflating every other SAFE's share count.
    """
    if pre_financing_fd is None or pre_financing_fd <= 0:
        return {
            "branch": "rejected",
            "error": E_SAFE_CAP_MISSING_DENOMINATOR,
            "reason": "pre_financing_fd must be > 0 (pre-financing FD share count)",
        }

    # DUPLICATE IDS MUST BE REFUSED, NOT COLLAPSED. `priced` and `per_safe` below are keyed by id,
    # so two SAFEs sharing one silently become one: measured, two SAFEs with id "same" returned a
    # clean `cap_implied_set` whose denominator counted only the second, dropping a $500k instrument
    # from BOTH the denominator and the output with no diagnostic. That is the same class as the
    # all-or-nothing rule above -- a converting security missing from `total` inflates every other
    # SAFE's ownership -- and nothing upstream prevents it: the schemas declare no `uniqueItems`,
    # and `extract_instrument.py` guards ids only on its own lane, so a
    # hand-authored or freeform-mapped instruments.json reaches this function directly.
    #
    # `cap_state.build_cap_state` now refuses this artifact-wide, so on the orchestrated path this
    # is a second line of defence rather than the only one. It stays because this function is also
    # called directly (its own CLI, and callers that build a SAFE list without a cap state), and a
    # guard that only holds when someone remembered to route through another module is not a
    # guarantee.
    # A MISSING id is its own defect, reported separately. Folding it in as a duplicate of `None`
    # names a value that appears nowhere in the founder's documents, and the two need different
    # fixes. It also has to be checked FIRST: `priced[safe["id"]]` below is a subscript, so a single
    # id-less SAFE raised KeyError out of a function whose entire contract is typed rejections --
    # the same objection this file already makes about ZeroDivisionError, three lines away.
    missing = sum(1 for s in safes if s.get("id") in (None, ""))
    if missing:
        return {
            "branch": "rejected",
            "error": E_SAFE_INSTRUMENT_ID_MISSING,
            "reason": (
                f"{missing} of {len(safes)} SAFEs carry no id. Ids key the conversion output, so a "
                "SAFE without one cannot be reported separately from the others. Give each SAFE a "
                "distinct id."
            ),
        }

    ids = [s.get("id") for s in safes]
    duplicates = sorted({str(i) for i in ids if ids.count(i) > 1})
    if duplicates:
        return {
            "branch": "rejected",
            "error": E_SAFE_DUPLICATE_INSTRUMENT_ID,
            "reason": (
                f"{len(safes)} SAFEs carry {len(duplicates)} duplicated id(s): {', '.join(duplicates)}. "
                "Ids key the conversion output, so a repeat would silently drop an instrument from the "
                "denominator and overstate every other SAFE's ownership. Give each SAFE a distinct id."
            ),
        }

    priced: dict[str, float] = {}
    for safe in safes:
        cap = safe.get("post_money_valuation_cap")
        if cap is None or cap <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
                "reason": (
                    f"cap-implied path requires a non-null post_money_valuation_cap; {safe.get('id')!r} "
                    "has none. The whole set is rejected rather than priced without it: an unpriced "
                    "SAFE is still a converting security, so omitting it from the denominator would "
                    "overstate every other SAFE's ownership."
                ),
            }
        priced[safe["id"]] = safe["purchase_amount"] / cap

    aggregate = sum(priced.values())
    if aggregate >= 1.0:
        return {
            "branch": "rejected",
            "error": E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE,
            "reason": (
                f"stacked post-money SAFEs reserve {aggregate:.1%} of the company, which is not "
                "feasible (rule safe.stacked_post_money_caps: block at or above 100%). Confirm each "
                "cap and purchase amount against the signed documents."
            ),
        }

    # NUMERICAL degeneracy, and deliberately ONLY that. The check above blocks `aggregate >= 1.0`; at
    # 1 - 1.1e-16 the division returned a `company_capitalization` of 7.2e22 and handed each SAFE
    # 3.6e22 shares, branch `cap_implied_set`, `error: None`. With a large enough `pre_financing_fd`
    # the same path overflows to `inf` and the per-SAFE price becomes 0.0, raising ZeroDivisionError
    # out of a function whose entire contract is typed rejections.
    #
    # SCOPE, because the threshold invites a fair objection. `1e-9` is where float arithmetic stops
    # producing a meaningful denominator, not where a cap table stops being plausible: an aggregate of
    # 0.99 still prices, and returns a company capitalization 100x the pre-financing base. That is an
    # extreme cap table, not a broken computation, and refusing it would be this function inventing an
    # economic policy the rule pack does not state. Implausible-but-computable belongs to a warning
    # someone writes deliberately; this guard's job is to stop reporting arithmetic that has lost its
    # meaning.
    residual = 1.0 - aggregate
    if residual <= 1e-9:
        return {
            "branch": "rejected",
            "error": E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE,
            "reason": (
                "stacked post-money SAFEs reserve so close to the whole company that the remaining "
                f"share is {residual:.3g} -- below the point where this arithmetic stays meaningful. "
                "(Distinct from the at-or-above-100% case above: this one is a rounding-scale "
                "problem, not an outright impossible one.) Confirm each cap and purchase amount "
                "against the signed documents."
            ),
        }

    total = pre_financing_fd / residual
    if not math.isfinite(total):
        return {
            "branch": "rejected",
            "error": E_SAFE_AGGREGATE_CAP_OWNERSHIP_INFEASIBLE,
            "reason": (
                f"cap-implied denominator overflowed to {total} from a pre-financing base of "
                f"{pre_financing_fd:,} against {aggregate:.9%} reserved. Confirm the inputs."
            ),
        }

    per_safe: dict[str, Any] = {}
    for safe in safes:
        cap = safe["post_money_valuation_cap"]
        safe_price = cap / total
        shares = safe["purchase_amount"] / safe_price
        per_safe[safe["id"]] = {
            "branch": "cap_implied",
            "cap_implied_ownership": priced[safe["id"]],
            "safe_price": safe_price,
            "cap_implied_shares": shares,
            "math_provenance": [
                {
                    "output_field": field,
                    "source_type": "rule",
                    # The stacked rule governs the denominator; the per-SAFE percentage is still the
                    # post-money cap conversion. Citing both is the honest provenance.
                    "rule_id": rule_id,
                    "rule_pack_version": RULE_PACK_VERSION,
                    "source_ref": None,
                }
                for field, rule_id in (
                    ("cap_implied_ownership", "safe.post_money_cap_conversion"),
                    ("safe_price", "safe.stacked_post_money_caps"),
                    ("cap_implied_shares", "safe.stacked_post_money_caps"),
                )
            ],
        }

    # THE INVARIANT THAT HAS CONTENT. Asserting `shares/total == ownership` would be a tautology --
    # `shares` is derived from `total` -- which is the same "checked against the formula that produced
    # it" failure that let the original defect ship. This checks the FIXED POINT actually closed: the
    # denominator must equal the pre-financing base plus the shares it produced.
    closed = pre_financing_fd + sum(v["cap_implied_shares"] for v in per_safe.values())
    if abs(closed - total) > 1e-6 * max(1.0, total):
        return {
            "branch": "rejected",
            "error": E_SAFE_CAP_MISSING_DENOMINATOR,
            "reason": (
                f"cap-implied denominator did not close: total {total:,.4f} but pre-financing base "
                f"plus converting shares is {closed:,.4f}"
            ),
        }

    return {"branch": "cap_implied_set", "company_capitalization": total, "per_safe": per_safe}


def convert_safe_cap_implied(
    *,
    purchase_amount: float,
    post_money_valuation_cap: float | None,
    company_capitalization: int | float,
) -> dict[str, Any]:
    """SINGLE-SAFE cap-implied conversion. Thin wrapper over the set solver.

    Kept for the CLI subcommand and single-instrument callers. `company_capitalization` here is the
    PRE-financing FD count (the parameter name predates the fix and is retained for compatibility;
    `convert_safes_cap_implied` names it `pre_financing_fd`, which is what it is).

    A single SAFE is the special case in which the set coupling is invisible — which is exactly why
    the per-instrument shape hid the defect. Prefer the set solver for anything reading real
    instruments.
    """
    result = convert_safes_cap_implied(
        [{"id": "_single", "purchase_amount": purchase_amount, "post_money_valuation_cap": post_money_valuation_cap}],
        pre_financing_fd=company_capitalization,
    )
    if result["branch"] != "cap_implied_set":
        return result
    single: dict[str, Any] = result["per_safe"]["_single"]
    return single


# Form classification for denominator routing.
# Post-money forms: each SAFE locks `purchase / cap` of Company Capitalization,
# measured immediately prior to the equity financing (= existing shares +
# pre-existing unissued pool + ALL converting securities, but EXCLUDING new-money
# financing shares and in-connection pool top-ups). The operational denominator
# passed via `company_capitalization` must reflect this pre-new-money snapshot,
# resolved self-consistently via the fixed-point loop in the solver.
# See rule `safe.company_capitalization_yc_post_money` and the YC post-money
# SAFE definition.
POST_MONEY_FORMS: set[str] = {
    "yc_postmoney_cap",
    "yc_postmoney_discount",
    "yc_uncapped_mfn",
    "cap_plus_discount",
}
# Pre-money (legacy, pre-Oct-2018) forms: cap_price = cap / pre_money_FD where
# pre_money_FD is the PRE-FINANCING fully-diluted snapshot (constant, NOT the
# iterating post-money FD). These SAFEs dilute alongside founders when new money
# and pool refresh land — they do NOT have the locked-% property of post-money.
PRE_MONEY_FORMS: set[str] = {
    "yc_premoney_cap_only",
    "pre_money_cap_and_discount_legacy",
}


def convert_safe_priced_round(
    *,
    purchase_amount: float,
    form: str,
    post_money_valuation_cap: float | None,
    discount_multiplier: float | None,
    company_capitalization: int | float,
    equity_financing_price: float | None,
    conversion_price_override: float | None = None,
    pre_money_valuation_cap: float | None = None,
    pre_money_fd: float | None = None,
    pre_money_valuation: float | None = None,
) -> dict[str, Any]:
    """Post-financing output set (requires a real conversion event).

    Branches:
        * conversion_price_override → branch = "conversion_price_override"
        * yc_postmoney_cap → cap branch (post-money denominator)
        * cap_plus_discount → min(cap_price, discount_price)
        * yc_postmoney_discount → discount branch only
        * yc_uncapped_mfn → REJECTED (caller must resolve MFN trigger first)
        * yc_premoney_cap_only → Standard-Preferred branch (round price) when
          pre_money_valuation ≤ pre_money_valuation_cap per YC pre-money SAFE
          §(a)(1); cap branch (pre-money denominator) when > cap per §(a)(2).
        * pre_money_cap_and_discount_legacy → same §(a)(1)/§(a)(2) branch
          selection, then min(winning_price, discount_price).

    Denominator routing: post-money forms use `company_capitalization`
    (= Company Capitalization immediately prior to the equity financing:
    adj_pre_fd + converting securities, EXCLUDING new-money shares and
    in-connection pool top-ups); pre-money forms use `pre_money_fd`
    (= pre-financing FD including in-connection pool increase, per the YC
    pre-money SAFE "Company Capitalization" definition). See `POST_MONEY_FORMS`
    / `PRE_MONEY_FORMS`.

    `pre_money_valuation` (the round's pre-money valuation) is required for
    pre-money forms when a priced round is known; without it the §(a)(1) ≤-cap
    branch cannot be selected. When absent the cap-price path is used as a
    conservative fallback and a note is emitted.

    Caller is responsible for resolving MFN cherry-pick BEFORE calling this
    function (yc_uncapped_mfn with a trigger should be re-presented as if
    it were the triggering SAFE's form).
    """
    # Unknown form — emit a structured blocker BEFORE any other logic so the
    # caller sees exactly what value was rejected and what values are valid.
    _all_valid_forms = POST_MONEY_FORMS | PRE_MONEY_FORMS
    if form not in _all_valid_forms:
        _sorted_valid = sorted(_all_valid_forms)
        return {
            "branch": "rejected",
            "error": E_UNKNOWN_SAFE_FORM,
            "reason": (
                f"form={form!r} is not a recognised SAFE form. "
                f"Valid values: {_sorted_valid}. "
                f"Check instruments.json safes[].form and correct the typo or "
                f"map to the nearest canonical form before re-running."
            ),
            "valid_forms": _sorted_valid,
        }

    # Override branch — counsel-supplied price; bypass rule
    if conversion_price_override is not None:
        if conversion_price_override <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
                "reason": "conversion_price_override must be > 0",
            }
        conversion_price = conversion_price_override
        shares = purchase_amount / conversion_price
        return {
            "branch": "conversion_price_override",
            "conversion_price": conversion_price,
            "conversion_shares": shares,
            "math_provenance": [
                {
                    "output_field": "conversion_price",
                    "source_type": "counsel_supplied_override",
                    "rule_id": None,
                    "rule_pack_version": None,
                    "source_ref": "safes[].conversion_price_override",
                },
                {
                    "output_field": "conversion_shares",
                    "source_type": "counsel_supplied_override",
                    "rule_id": None,
                    "rule_pack_version": None,
                    "source_ref": "safes[].conversion_price_override",
                },
            ],
        }

    # yc_uncapped_mfn without override needs MFN trigger resolution upstream
    if form == "yc_uncapped_mfn" and post_money_valuation_cap is None and discount_multiplier is None:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": (
                "yc_uncapped_mfn requires MFN trigger resolution upstream OR "
                "conversion_price_override; caller did not provide either"
            ),
        }

    # Forms requiring a priced-round price
    needs_price = form in {"yc_postmoney_discount", "yc_uncapped_mfn"} or (
        form == "cap_plus_discount" and discount_multiplier is not None
    )
    if needs_price and equity_financing_price is None:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": (
                f"{form} requires equity_financing_price (priced round) or conversion_price_override; neither provided"
            ),
        }

    candidate_prices: list[tuple[str, float]] = []
    notes: list[str] = []

    # Cap candidate — route denominator on form.
    # Post-money forms use the iterating post-money FD as denominator
    # (`company_capitalization`); pre-money forms use `pre_money_fd` which
    # includes the in-connection pool increase per the YC pre-money SAFE
    # "Company Capitalization" definition. This is the load-bearing distinction
    # between the two SAFE families.
    cap_provenance_rule_id: str = "safe.post_money_cap_conversion"

    if form in POST_MONEY_FORMS and post_money_valuation_cap is not None and post_money_valuation_cap > 0:
        if company_capitalization is None or company_capitalization <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_CAP_MISSING_DENOMINATOR,
                "reason": (
                    f"cap branch requires non-zero denominator (company_capitalization); got {company_capitalization!r}"
                ),
            }
        cap_price = post_money_valuation_cap / company_capitalization
        candidate_prices.append(("cap_price", cap_price))
        cap_provenance_rule_id = "safe.post_money_cap_conversion"

    elif form in PRE_MONEY_FORMS and pre_money_valuation_cap is not None and pre_money_valuation_cap > 0:
        # YC pre-money SAFE §(a): branch on whether round pre-money valuation
        # is ≤ cap or > cap.
        #   §(a)(1): pre_money_valuation ≤ cap → Standard Preferred (round price)
        #   §(a)(2): pre_money_valuation > cap → Safe Preferred (cap price)
        # When pre_money_valuation is unknown the cap-price path is used as a
        # conservative fallback (investor gets fewer shares — conservative for
        # the founder-side; counsel should confirm branch when at/below-cap).
        cap_provenance_rule_id = "safe.pre_money_cap_conversion"
        if (
            pre_money_valuation is not None
            and pre_money_valuation <= pre_money_valuation_cap
            and equity_financing_price is not None
            and equity_financing_price > 0
        ):
            # §(a)(1): round price applies; cap price is disregarded.
            # The investor gets purchase / round_price shares.
            # The discount candidate (if any) still competes — investor
            # always gets the more favorable (more shares) price.
            candidate_prices.append(("round_price", equity_financing_price))
        else:
            # §(a)(2): pre_money_valuation > cap, OR round context not available.
            if pre_money_valuation is None and equity_financing_price is not None:
                # No valuation supplied; emit an informational note.
                notes.append(
                    "pre_money_valuation not provided; cap-price path used as conservative "
                    "fallback. If the round pre-money valuation is ≤ the SAFE cap, §(a)(1) "
                    "of the YC pre-money SAFE applies and the investor converts at the round "
                    "price instead (more investor-favorable)."
                )
            elif (
                pre_money_valuation is not None
                and pre_money_valuation <= pre_money_valuation_cap
                and (equity_financing_price is None or equity_financing_price <= 0)
            ):
                # §(a)(1) is KNOWN to apply (valuation ≤ cap) but no round price is
                # available to price it — the cap-branch numbers below are the
                # wrong branch and must not be presented as the document's answer.
                notes.append(
                    "pre_money_valuation ≤ cap, so §(a)(1) of the YC pre-money SAFE applies "
                    "(round-price conversion) — but no round price per share was provided. "
                    "The cap-price figures below are placeholders from the wrong branch; "
                    "re-run with the round price to get the document's answer."
                )
            if pre_money_fd is None or pre_money_fd <= 0:
                return {
                    "branch": "rejected",
                    "error": E_SAFE_CAP_MISSING_DENOMINATOR,
                    "reason": (f"cap branch requires non-zero denominator (pre_money_fd); got {pre_money_fd!r}"),
                }
            cap_price = pre_money_valuation_cap / pre_money_fd
            candidate_prices.append(("cap_price", cap_price))

    # Discount candidate (rule: safe.discount_rate_semantics)
    if discount_multiplier is not None and equity_financing_price is not None:
        if discount_multiplier <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_INVALID_PRICE_INPUT,
                "reason": f"discount_multiplier must be > 0; got {discount_multiplier!r}",
            }
        if equity_financing_price <= 0:
            return {
                "branch": "rejected",
                "error": E_SAFE_INVALID_PRICE_INPUT,
                "reason": f"equity_financing_price must be > 0; got {equity_financing_price!r}",
            }
        discount_price = equity_financing_price * discount_multiplier
        candidate_prices.append(("discount_price", discount_price))

    if not candidate_prices:
        return {
            "branch": "rejected",
            "error": E_SAFE_REQUIRES_CONVERSION_EVENT,
            "reason": f"no usable conversion price for form={form}",
        }

    # min(valid_price_candidates) wins (lower price → more shares for SAFE holder)
    winning_label, conversion_price = min(candidate_prices, key=lambda kv: kv[1])
    shares = purchase_amount / conversion_price

    labels = {label for label, _ in candidate_prices}
    if len(candidate_prices) == 1:
        if winning_label == "cap_price":
            branch = "cap_branch"
        elif winning_label == "round_price":
            branch = "round_price_branch"
        else:
            branch = "discount_branch"
    else:
        # Two candidates: name the combination
        if "cap_price" in labels and "discount_price" in labels:
            branch = "cap_and_discount_branch"
        elif "round_price" in labels and "discount_price" in labels:
            branch = "round_price_and_discount_branch"
        else:
            branch = "cap_and_discount_branch"  # fallback

    provenance = []
    if "cap_price" in labels:
        provenance.append(
            {
                "output_field": "cap_price",
                "source_type": "rule",
                "rule_id": cap_provenance_rule_id,
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )
    if "round_price" in labels:
        provenance.append(
            {
                "output_field": "round_price",
                "source_type": "rule",
                "rule_id": cap_provenance_rule_id,
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )
    if "discount_price" in labels:
        provenance.append(
            {
                "output_field": "discount_price",
                "source_type": "rule",
                "rule_id": "safe.discount_rate_semantics",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        )
    provenance.append(
        {
            "output_field": "conversion_price",
            "source_type": "rule",
            "rule_id": cap_provenance_rule_id,
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )
    provenance.append(
        {
            "output_field": "conversion_shares",
            "source_type": "rule",
            "rule_id": cap_provenance_rule_id,
            "rule_pack_version": RULE_PACK_VERSION,
            "source_ref": None,
        }
    )

    result: dict[str, Any] = {
        "branch": branch,
        "candidates": dict(candidate_prices),
        "conversion_price": conversion_price,
        "conversion_shares": shares,
        "math_provenance": provenance,
    }
    if notes:
        result["notes"] = notes
    return result


def detect_mfn_cycles(safes: list[dict[str, Any]]) -> list[set[str]]:
    """Detect circular MFN-election chains.

    Returns a list of cycles (each cycle is a set of safe IDs). Empty list
    means no cycles. Per Gotcha #4: yc_uncapped_mfn A → B → ... → A with no
    anchor SAFE in the cycle is unresolvable.
    """
    # Build directed graph: A → B iff A.mfn.elected_against_safe_id == B
    graph: dict[str, str | None] = {}
    forms: dict[str, str] = {}
    for s in safes:
        sid = s["id"]
        forms[sid] = s.get("form", "other")
        mfn = s.get("mfn_provision") or {}
        elected = mfn.get("elected_against_safe_id")
        graph[sid] = elected

    cycles = []
    visited = set()
    for sid in list(graph.keys()):
        if sid in visited:
            continue
        path: list[str] = []
        current: str | None = sid
        seen_in_walk: dict[str, int] = {}
        while current is not None and current not in visited:
            if current in seen_in_walk:
                # Found a cycle starting at seen_in_walk[current]
                cycle_start = seen_in_walk[current]
                cycle = set(path[cycle_start:])
                # Only flag as unresolvable if EVERY SAFE in the cycle is
                # yc_uncapped_mfn (no anchor with intrinsic price)
                if all(forms.get(c) == "yc_uncapped_mfn" for c in cycle):
                    cycles.append(cycle)
                break
            seen_in_walk[current] = len(path)
            path.append(current)
            current = graph.get(current)
        visited.update(path)
    return cycles


# ---------------------------------------------------------------------------
# CLI entrypoint (for ad-hoc testing; production callers use the library API)
# ---------------------------------------------------------------------------


def _cli() -> int:
    shared = argparse.ArgumentParser(add_help=False)
    add_output_args(shared)

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("cap-implied", parents=[shared], help="Cap-implied output (standalone)")
    cap.add_argument("--purchase", type=float, required=True)
    cap.add_argument("--cap", type=float, required=True)
    cap.add_argument("--company-cap", type=float, required=True)

    pr = sub.add_parser("priced-round", parents=[shared], help="Post-financing output")
    pr.add_argument("--purchase", type=float, required=True)
    pr.add_argument(
        "--form",
        required=True,
        choices=[
            "yc_postmoney_cap",
            "yc_postmoney_discount",
            "yc_uncapped_mfn",
            "cap_plus_discount",
            "yc_premoney_cap_only",
            "pre_money_cap_and_discount_legacy",
        ],
    )
    pr.add_argument("--cap", type=float, default=None)
    pr.add_argument("--discount", type=float, default=None, help="Multiplier form: 0.80 = 20%% discount")
    pr.add_argument("--company-cap", type=float, required=True)
    pr.add_argument("--equity-price", type=float, default=None)
    pr.add_argument("--override", type=float, default=None, help="Conversion price override (counsel-supplied)")
    pr.add_argument(
        "--pre-money-cap",
        type=float,
        default=None,
        help="Pre-money valuation cap (legacy pre-money forms)",
    )
    pr.add_argument(
        "--pre-money-fd",
        type=float,
        default=None,
        help="Pre-money fully-diluted denominator (legacy pre-money forms)",
    )

    cycles = sub.add_parser("detect-mfn-cycles", parents=[shared], help="Detect circular MFN chains")
    cycles.add_argument("--instruments", required=True)

    args = p.parse_args()

    if args.cmd == "cap-implied":
        result = convert_safe_cap_implied(
            purchase_amount=args.purchase,
            post_money_valuation_cap=args.cap,
            company_capitalization=args.company_cap,
        )
    elif args.cmd == "priced-round":
        result = convert_safe_priced_round(
            purchase_amount=args.purchase,
            form=args.form,
            post_money_valuation_cap=args.cap,
            discount_multiplier=args.discount,
            company_capitalization=args.company_cap,
            equity_financing_price=args.equity_price,
            conversion_price_override=args.override,
            pre_money_valuation_cap=args.pre_money_cap,
            pre_money_fd=args.pre_money_fd,
        )
    else:  # detect-mfn-cycles
        with open(args.instruments, encoding="utf-8") as f:
            inst = json.load(f)
        cycle_list = detect_mfn_cycles(inst.get("safes", []))
        result = {
            "cycles": [sorted(c) for c in cycle_list],
            "error": E_SAFE_CIRCULAR_MFN if cycle_list else None,
        }

    emit(result, args)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
