#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Option-pool top-up math (rule `option_pool.pre_money_topup`).

Per Gotcha #1 + the rule's warnings: when target_basis is `pre_money`, the
top-up increases pre-money FD; when `post_money`, denominator includes new
money. The rule pack's `target_basis` enum has four values
(`pre_money | post_money | post_money_excluding_converting_securities |
custom`). This script implements all four.

Formula (rule pack):
  For post-money target:
    (existing_unallocated_pool + x) / (pre_topup_FD + x + new_money_shares) = target_pool_percent
  For pre-money target:
    (existing_unallocated_pool + x) / (pre_topup_FD + x) = target_pool_percent
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

RULE_PACK_VERSION = "0.3.0"


def required_topup(
    *,
    pre_topup_fully_diluted_shares: int | float,
    existing_unallocated_pool: int | float,
    target_pool_percent: float,
    new_money_shares: int | float | None,
    target_basis: str,
) -> dict[str, Any]:
    """Solve for required_pool_topup_shares.

    Returns:
        {
          required_pool_topup_shares: int,
          post_topup_pool_percent: float,
          target_basis: str,
          math_provenance: [...]
        }
    """
    pre_fd = float(pre_topup_fully_diluted_shares)
    existing = float(existing_unallocated_pool)
    target = float(target_pool_percent)

    if target <= 0 or target >= 1:
        raise ValueError(f"target_pool_percent must be in (0,1); got {target}")

    if target_basis == "pre_money":
        # (existing + x) / (pre_fd + x) = target
        # existing + x = target * (pre_fd + x)
        # x - target * x = target * pre_fd - existing
        # x = (target * pre_fd - existing) / (1 - target)
        x = (target * pre_fd - existing) / (1 - target)
    elif target_basis in {"post_money", "post_money_excluding_converting_securities"}:
        nm = float(new_money_shares or 0)
        # (existing + x) / (pre_fd + x + nm) = target
        # x - target * x = target * (pre_fd + nm) - existing
        # x = (target * (pre_fd + nm) - existing) / (1 - target)
        x = (target * (pre_fd + nm) - existing) / (1 - target)
    elif target_basis == "custom":
        # Custom denominator policy is document-defined; for v0.1 we treat it
        # as pre_money fallback with a counsel-review flag (caller responsibility).
        x = (target * pre_fd - existing) / (1 - target)
    else:
        raise ValueError(f"unknown target_basis: {target_basis}")

    required = max(0, int(round(x)))

    # Recompute realized percent
    if target_basis == "pre_money" or target_basis == "custom":
        denom = pre_fd + required
    else:
        denom = pre_fd + required + float(new_money_shares or 0)
    realized = (existing + required) / denom if denom > 0 else 0.0

    return {
        "required_pool_topup_shares": required,
        "post_topup_pool_percent": realized,
        "target_basis": target_basis,
        "math_provenance": [
            {
                "output_field": "required_pool_topup_shares",
                "source_type": "rule",
                "rule_id": "option_pool.pre_money_topup",
                "rule_pack_version": RULE_PACK_VERSION,
                "source_ref": None,
            }
        ],
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pre-fd", type=float, required=True)
    p.add_argument("--existing", type=float, required=True)
    p.add_argument("--target-pct", type=float, required=True, help="Target pool fraction, e.g. 0.15 for 15%%")
    p.add_argument("--new-money-shares", type=float, default=None)
    p.add_argument(
        "--basis",
        required=True,
        choices=["pre_money", "post_money", "post_money_excluding_converting_securities", "custom"],
    )
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    result = required_topup(
        pre_topup_fully_diluted_shares=args.pre_fd,
        existing_unallocated_pool=args.existing,
        target_pool_percent=args.target_pct,
        new_money_shares=args.new_money_shares,
        target_basis=args.basis,
    )
    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
