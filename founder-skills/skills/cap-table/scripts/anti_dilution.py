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
import json
import sys
from typing import Any

RULE_PACK_VERSION = "0.3.1"


def bbwa_new_conversion_price(
    *,
    current_conversion_price: float,
    pre_issuance_share_count_A: float,
    consideration_received: float,
    new_issue_price: float,
    new_shares_issued_C: float | None = None,
) -> dict[str, Any]:
    """Broad-based weighted-average anti-dilution.

    B = consideration / CP1 (NOT consideration / OIP — Gotcha #2)
    C = either supplied directly OR derived as consideration / new_issue_price.

    Returns CP2 (new conversion price) plus the intermediate B and C values
    for transparency in math provenance.
    """
    if current_conversion_price <= 0:
        raise ValueError("current_conversion_price must be > 0")
    if new_issue_price >= current_conversion_price:
        # No down-round trigger; AD does not adjust
        return {
            "triggered": False,
            "new_conversion_price": current_conversion_price,
            "reason": "new_issue_price >= current_conversion_price; no adjustment",
            "math_provenance": [],
        }

    B = consideration_received / current_conversion_price  # noqa: N806
    C = (
        new_shares_issued_C  # noqa: N806
        if new_shares_issued_C is not None
        else consideration_received / new_issue_price
    )
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


def full_ratchet_new_conversion_price(
    *,
    current_conversion_price: float,
    new_issue_price: float,
) -> dict[str, Any]:
    """Full-ratchet: CP2 = new_issue_price if new < current; else no change."""
    if new_issue_price >= current_conversion_price:
        return {
            "triggered": False,
            "new_conversion_price": current_conversion_price,
            "reason": "new_issue_price >= current_conversion_price; no adjustment",
            "math_provenance": [],
        }
    return {
        "triggered": True,
        "new_conversion_price": new_issue_price,
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


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--pretty", action="store_true")

    bb = sub.add_parser("bbwa", parents=[shared])
    bb.add_argument("--cp1", type=float, required=True)
    bb.add_argument("--A", type=float, required=True)
    bb.add_argument("--consideration", type=float, required=True)
    bb.add_argument("--new-price", type=float, required=True)
    bb.add_argument("--shares-C", type=float, default=None)

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
            new_shares_issued_C=args.shares_C,
        )
    else:
        result = full_ratchet_new_conversion_price(
            current_conversion_price=args.cp1,
            new_issue_price=args.new_price,
        )

    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
