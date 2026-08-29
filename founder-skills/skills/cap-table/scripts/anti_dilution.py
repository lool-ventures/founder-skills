#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Anti-dilution math: BBWA + narrow-based weighted-average + full ratchet.

Per Gotcha #2: the BBWA divisor uses CP1 (current conversion price), NOT
original_issue_price. Formula:

  CP2 = CP1 × (A + B) / (A + C)

where:
  A = pre-deemed-issuance share count (broad-based: all common + preferred
      as-converted + options outstanding + options reserved;
      narrow-based: common + preferred as-converted only)
  B = consideration_received / CP1   ← critical: divisor is CP1, not OIP
  C = shares actually issued in the down round

Full ratchet: CP2 = new_issue_price (the lowest price paid).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _emit import add_output_args, emit  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402


def bbwa_new_conversion_price(
    *,
    current_conversion_price: float,
    pre_issuance_share_count_A: float,
    consideration_received: float,
    new_issue_price: float,
) -> dict[str, Any]:
    """Broad-based weighted-average anti-dilution.

    B = consideration / CP1 (NOT consideration / OIP — Gotcha #2)
    C = consideration / new_issue_price, always DERIVED and never supplied.

    C was formerly an optional override. Nothing passed a value that disagreed with the derivation,
    so the parameter bought no expressiveness -- but it made the identity `B/C == new_price/CP1`
    breakable by a caller, and that identity is what makes CP2 <= CP1 an arithmetic guarantee rather
    than a hope. Deriving it unconditionally means the only way to reach a ratchet-up is a floor, and
    the floor is validated at the solver entry point.

    Returns CP2 (new conversion price) plus the intermediate B and C values
    for transparency in math provenance.
    """
    if current_conversion_price <= 0:
        raise ValueError("current_conversion_price must be > 0")
    if new_issue_price <= 0:
        # Reachable only for a non-positive price, which still satisfies `< current_conversion_price`
        # and would divide by zero deriving C. A free or negative-priced issuance is not a
        # weighted-average input; the caller must decide what it means.
        raise ValueError("new_issue_price must be > 0")
    if new_issue_price >= current_conversion_price:
        # No down-round trigger; AD does not adjust
        return {
            "triggered": False,
            "new_conversion_price": current_conversion_price,
            "reason": "new_issue_price >= current_conversion_price; no adjustment",
            "math_provenance": [],
        }

    B = consideration_received / current_conversion_price  # noqa: N806
    C = consideration_received / new_issue_price  # noqa: N806
    A = pre_issuance_share_count_A  # noqa: N806
    cp2 = current_conversion_price * (A + B) / (A + C)
    return {
        "triggered": True,
        "new_conversion_price": cp2,
        "intermediate": {"A": A, "B": B, "C": C, "CP1": current_conversion_price},
        "math_provenance": [
            {
                "output_field": "new_conversion_price",
                "source_type": "rule",
                "rule_id": "anti_dilution.broad_based_weighted_average",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        ],
    }


# NVCA §4.4.4 proviso: a without-consideration issuance is deemed to have
# received $.001 aggregate consideration.  Full-ratchet sets CP2 = new_issue_price,
# so a zero (or sub-floor) price would produce CP2=0, an invalid conversion price.
# FULL_RATCHET_DEEMED_MIN_PRICE is a pragmatic per-share epsilon consistent with the NVCA
# $.001 deemed aggregate consideration.  It prevents CP2 from reaching zero.
FULL_RATCHET_DEEMED_MIN_PRICE: float = 0.001


def full_ratchet_new_conversion_price(
    *,
    current_conversion_price: float,
    new_issue_price: float,
) -> dict[str, Any]:
    """Full-ratchet: CP2 = new_issue_price if new < current; else no change.

    NVCA §4.4.4 proviso: a without-consideration (zero-price) issuance is
    deemed to have received $.001 of aggregate consideration.  Any
    new_issue_price below FULL_RATCHET_DEEMED_MIN_PRICE (0.001) is floored
    to that value and deemed_consideration_floor_applied=True is set in the
    result so callers can surface the NVCA proviso to founders/counsel.
    """
    if new_issue_price >= current_conversion_price:
        return {
            "triggered": False,
            "new_conversion_price": current_conversion_price,
            "reason": "new_issue_price >= current_conversion_price; no adjustment",
            "math_provenance": [],
        }

    floor_applied = new_issue_price < FULL_RATCHET_DEEMED_MIN_PRICE
    cp2 = max(new_issue_price, FULL_RATCHET_DEEMED_MIN_PRICE)

    result: dict[str, Any] = {
        "triggered": True,
        "new_conversion_price": cp2,
        "math_provenance": [
            {
                "output_field": "new_conversion_price",
                "source_type": "rule",
                "rule_id": "anti_dilution.full_ratchet",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        ],
    }
    if floor_applied:
        result["deemed_consideration_floor_applied"] = True
        result["deemed_consideration_floor"] = FULL_RATCHET_DEEMED_MIN_PRICE
        result["raw_new_issue_price"] = new_issue_price
    return result


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    add_output_args(shared)

    bb = sub.add_parser("bbwa", parents=[shared])
    bb.add_argument("--cp1", type=float, required=True)
    bb.add_argument("--A", type=float, required=True)
    bb.add_argument("--consideration", type=float, required=True)
    bb.add_argument("--new-price", type=float, required=True)

    fr = sub.add_parser("full-ratchet", parents=[shared])
    fr.add_argument("--cp1", type=float, required=True)
    fr.add_argument("--new-price", type=float, required=True)

    args = p.parse_args()

    if args.cmd == "bbwa":
        result = bbwa_new_conversion_price(
            current_conversion_price=args.cp1,
            pre_issuance_share_count_A=args.A,
            consideration_received=args.consideration,
            new_issue_price=args.new_price,
        )
    else:
        result = full_ratchet_new_conversion_price(
            current_conversion_price=args.cp1,
            new_issue_price=args.new_price,
        )

    emit(result, args)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
