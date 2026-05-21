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

RULE_PACK_VERSION = "0.3.1"


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

    # Phase M+S: when the founder-supplied target_basis would silently no-op
    # (existing pool already meets target under literal pre_money basis math)
    # but industry norm for "X% pool refresh" usually means post-close
    # unallocated (post_money basis), surface this as a clarifying question
    # the dispatching agent escalates via AskUserQuestion. Otherwise founders
    # see "0 top-up needed" and think the refresh has no cost — incorrect.
    warnings: list[dict[str, Any]] = []
    clarifying_question: dict[str, Any] | None = None
    if target_basis in {"pre_money", "custom"} and required == 0 and target > 0:
        # Compute what the post_money interpretation would give for comparison
        nm = float(new_money_shares or 0)
        post_money_x = (target * (pre_fd + nm) - existing) / (1 - target)
        post_money_required = max(0, int(round(post_money_x)))
    else:
        post_money_required = 0
    # M8 gate: only fire the warning + clarifying_question when post-money
    # interpretation produces a NONZERO top-up. If both interpretations yield 0
    # top-up, the pool is legitimately oversized and there's no real ambiguity.
    # M7 guard: pre_fd may be 0 for library callers; protect the warning message.
    if target_basis in {"pre_money", "custom"} and required == 0 and target > 0 and post_money_required > 0:
        existing_pct_of_pre_fd = (existing / pre_fd) if pre_fd > 0 else 0.0
        warnings.append(
            {
                "code": "pool_target_already_met_check_intent",
                "severity": "high",
                "message": (
                    f"Under literal target_basis={target_basis!r}, the existing pool "
                    f"({existing:,.0f} shares = {existing_pct_of_pre_fd:.1%} of pre-FD) already "
                    f"meets or exceeds the target of {target:.1%}, so the script computed 0 top-up. "
                    f"Series A term-sheet practice for 'X% pool refresh' usually means "
                    f"X% post-close unallocated (post_money basis). Under that reading, "
                    f"top-up would be {post_money_required:,d} shares. Confirm founder intent."
                ),
            }
        )
        clarifying_question = {
            "question": (
                "You asked for a 10% pool refresh on a pre-money basis. Under the literal "
                "reading, the existing pool already meets that target so the refresh is "
                'a no-op. Series A term sheets usually mean "10% post-close unallocated" — '
                "which would require a real top-up. Which interpretation matches your term sheet?"
            ),
            "options": [
                "Literal pre-money basis (no top-up needed — keep existing pool)",
                f"Industry norm: post-close unallocated ({post_money_required:,d} share top-up)",
            ],
            "context": {
                "target_pool_percent": target,
                "literal_pre_money_top_up": 0,
                "industry_norm_post_money_top_up": post_money_required,
                "existing_unallocated_pool": int(existing),
                "pre_topup_fully_diluted_shares": int(pre_fd),
            },
        }

    result: dict[str, Any] = {
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
    if warnings:
        result["warnings"] = warnings
    if clarifying_question:
        result["clarifying_question"] = clarifying_question
    return result


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
