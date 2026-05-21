#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Israeli ↔ Delaware flip mechanics (v0.1 scope: share-for-share 1:1 only).

Per Gotcha #7: v0.1 supports only 1:1 share-for-share exchange. Other
ratios, partial roll-forward of SAFEs/CLAs, and option-plan continuity
adjustments are deferred to v0.2 with counsel-review.

SAFE/CLA conversion + pricing run as a SEPARATE priced-round scenario
before or after the flip — they're NOT collapsed into flip math.

Output:
  pre_flip_cap_state: input cap_state (for record)
  post_flip_cap_state: same shape, share-for-share copied
  per_holder_mapping: explicit list of (pre_entity, post_entity) for audit
  counsel_review_items: §102 continuity, IIA approval, §104H/§103K
                        route choice flags (counsel-review gated)
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from typing import Any


def flip_share_for_share(
    cap_state: dict[str, Any],
    *,
    iia_grants_in_history: bool = False,
    section_102_grants_outstanding: int = 0,
) -> dict[str, Any]:
    """Model a 1:1 share-for-share flip.

    Every holder of Israeli-entity shares receives the same number of
    Delaware-parent shares. Pre/post cap state is structurally identical
    on share counts; counsel-review items are surfaced for IP, IIA, §102,
    and tax-deferral route choices.
    """
    post = deepcopy(cap_state)
    # The flip itself doesn't change share counts; it changes the issuer.
    # We mark the as_of_date as "post-flip" (caller may overwrite).
    post["_flip_metadata"] = {
        "exchange_ratio": "1:1",
        "model": "share_for_share",
        "v0_1_scope_limitation": (
            "v0.1 supports only 1:1 share-for-share. Other ratios, partial "
            "roll-forward of SAFEs/CLAs, and option-plan continuity require "
            "v0.2 + counsel review."
        ),
    }

    # Build per-holder mapping (every founder + preferred-series holder)
    mapping = []
    for f in cap_state.get("founders", []):
        mapping.append(
            {
                "pre_entity": "israeli_subsidiary",
                "post_entity": "delaware_parent",
                "holder_id": f["founder_id"],
                "holder_name": f["name"],
                "shares_pre": f["common_shares"],
                "shares_post": f["common_shares"],
            }
        )
    for s in cap_state.get("preferred_series", []):
        mapping.append(
            {
                "pre_entity": "israeli_subsidiary",
                "post_entity": "delaware_parent",
                "series_id": s["series_id"],
                "shares_pre": s["shares"],
                "shares_post": s["shares"],
            }
        )

    # Counsel-review items (always emitted in a flip)
    counsel_items: list[dict[str, Any]] = [
        {
            "rule_id": "delaware_flip.share_exchange_mechanics",
            "domain": "delaware_flip",
            "title": "Flip mechanics require holder-by-holder mapping",
            "founder_question": "Have all current shareholders agreed to the exchange?",
            "counsel_question": "What share-exchange / contribution structure preserves economic rights and minimizes tax friction?",
            "documents_needed": [
                "Articles of association",
                "Shareholder agreement",
                "All SAFEs / convertibles outstanding",
            ],
            "source_ids": ["ARNONTL-RESTRUCTURING-2025", "ICNL-ISRAEL-ORDINANCE"],
        },
        {
            "rule_id": "delaware_flip.tax_route_decision",
            "domain": "delaware_flip",
            "title": "§104H / §103K / §85A tax-deferral route choice",
            "founder_question": "Do you have an Israeli tax advisor for the flip transaction?",
            "counsel_question": "Which tax route applies to this flip (104H reorganization, 103K asset transfer, 85A IP migration)?",
            "documents_needed": [
                "Current IP ownership records",
                "Israeli tax filings",
                "Founder tax-residency declarations",
            ],
            "source_ids": ["KPMG-RD-CENTER-2025", "TAXADVISER-QSBS-OBBBA"],
        },
        {
            "rule_id": "delaware_cross_border.ip_transfer_pricing",
            "domain": "delaware_cross_border",
            "title": "Cross-border IP ownership and transfer pricing",
            "founder_question": "Where is your IP currently owned?",
            "counsel_question": "Does flip require IP migration, and what's the §85A / OECD transfer-pricing exposure?",
            "documents_needed": ["IP register", "Cost-plus arrangements", "Related-party agreements"],
            "source_ids": ["KPMG-RD-CENTER-2025"],
        },
    ]

    if section_102_grants_outstanding > 0:
        counsel_items.append(
            {
                "rule_id": "delaware_cross_border.section_102_parent_shares",
                "domain": "delaware_cross_border",
                "title": f"§102 continuity for {section_102_grants_outstanding} outstanding grants",
                "founder_question": "How many §102 option grants do you currently have outstanding?",
                "counsel_question": "What sub-plan and trustee arrangements continue §102 treatment under foreign-parent shares?",
                "documents_needed": ["§102 plan document", "Trustee agreement", "Per-grant deposit confirmations"],
                "source_ids": ["ICNL-ISRAEL-ORDINANCE", "PEARLCOHEN-102-PITFALLS"],
            }
        )

    if iia_grants_in_history:
        counsel_items.append(
            {
                "rule_id": "israeli_ltd.iia_royalty_obligations",
                "domain": "israeli_ltd",
                "title": "IIA-funded technology cannot be assumed transferable in a flip",
                "founder_question": "Has the company ever received IIA (formerly OCS) grants?",
                "counsel_question": "What IIA approvals + buy-out fees apply to the flip? Has the 6× / 3× transfer-cap rule been triggered?",
                "documents_needed": [
                    "All IIA grant agreements",
                    "IIA approval correspondence",
                    "Royalty payment records",
                ],
                "source_ids": ["IIA-ROYALTIES-IP"],
            }
        )

    return {
        "completeness": "structural_only",
        "pre_flip_cap_state": cap_state,
        "post_flip_cap_state": post,
        "per_holder_mapping": mapping,
        "counsel_review_items": counsel_items,
        "math_provenance": [
            {
                "output_field": "flip_exchange_ratio",
                "source_type": "rule",
                "rule_id": "delaware_flip.share_exchange_mechanics",
                "rule_pack_version": "0.3.1",
                "source_ref": None,
            },
        ],
        "blockers": [],
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cap-state", required=True)
    p.add_argument("--iia-grants", action="store_true")
    p.add_argument("--section-102-grants", type=int, default=0)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    result = flip_share_for_share(
        cap_state,
        iia_grants_in_history=args.iia_grants,
        section_102_grants_outstanding=args.section_102_grants,
    )
    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
