#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Compute cap_state.json from inputs.json + instruments.json.

cap_state.py is the foundational aggregation step. It reads `inputs.json`
(founder/preferred/option-pool declarations) plus `instruments.json` (SAFEs,
notes, warrants, option grants) and produces `cap_state.json` — the
authoritative current cap-table state every math producer consumes.

Per design doc §11 + Gotcha #1, `as_converted_totals.*` is the
**pre-financing** snapshot. It does NOT include new-money financing shares
or new pool top-ups. The YC Company Capitalization denominator
(`safe.company_capitalization_yc_post_money`) binds to this field
precisely because of the no-new-money-in-the-denominator invariant.

Usage:
    python3 cap_state.py --inputs inputs.json --instruments instruments.json \\
        --run-id 20260519T020000Z -o cap_state.json --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)


def _compute_as_converted_totals(
    founders: list[dict[str, Any]],
    canonical_preferred_series: list[dict[str, Any]],
    canonical_option_pool: dict[str, Any],
    common_batches: list[dict[str, Any]],
) -> dict[str, int]:
    """Compute pre-financing as-converted totals.

    Per Gotcha #1: this snapshot is what `safe.company_capitalization_yc_post_money`
    binds to. It MUST NOT include new-money financing shares or new
    post-financing pool top-ups. Pre-existing pool (issued + available) IS
    included.

    All inputs must be in the **canonical cap_state shape** (post-mapping),
    not the raw inputs.json shape.
    """
    founder_shares = sum(int(f.get("common_shares", 0)) for f in founders)
    batch_shares = sum(int(b.get("shares", 0)) for b in common_batches)
    common_shares = founder_shares + batch_shares

    # As-converted preferred: each series's shares × (OCP / current_conversion_price)
    # When AD hasn't triggered, current = original, so the ratio is 1.0.
    preferred_as_converted = 0
    for s in canonical_preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", 1.0))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp == 0:
            preferred_as_converted += shares
        else:
            preferred_as_converted += int(round(shares * (ocp / ccp)))

    options_outstanding = int(canonical_option_pool.get("issued_and_outstanding", 0))
    options_available = int(canonical_option_pool.get("available_for_grant", 0))

    fd = common_shares + preferred_as_converted + options_outstanding + options_available
    return {
        "common_shares": common_shares,
        "preferred_shares_as_converted": preferred_as_converted,
        "options_outstanding": options_outstanding,
        "options_available": options_available,
        "fully_diluted_shares": fd,
    }


def _build_outstanding_options(
    grants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build outstanding_options[] from instruments.option_grants[].

    Per Gotcha #6 + design rev16: grant_date / strike / plan_type are NOT
    re-declared here. cap_state.outstanding_options[] carries grant_id +
    as-converted-math fields (vested / exercised / unvested) only.
    """
    out = []
    for g in grants:
        granted = int(g.get("shares_granted", 0))
        vested = int(g.get("shares_vested_to_date", 0))
        exercised = int(g.get("shares_exercised", 0))
        unvested = max(0, granted - vested)
        out.append(
            {
                "grant_id": g["id"],
                "holder_id": g.get("holder_id", ""),
                "shares_vested_to_date": vested,
                "shares_exercised": exercised,
                "shares_outstanding_unvested": unvested,
            }
        )
    return out


def _build_outstanding_safes(safes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "safe_id": s["id"],
            "purchase_amount": s["purchase_amount"],
            "issuance_date": s["issuance_date"],
        }
        for s in safes
    ]


def _build_outstanding_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "note_id": n["id"],
            "principal": n["principal"],
            "issuance_date": n["issuance_date"],
        }
        for n in notes
    ]


def build_cap_state(
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    *,
    currency: str = "USD",
) -> dict[str, Any]:
    """Build cap_state.json content (no metadata.run_id; writer injects)."""
    founders = inputs.get("founders", []) or []
    preferred_series = inputs.get("preferred_series", []) or []
    option_pool = inputs.get("option_pool", {}) or {}
    common_batches = inputs.get("common_batches", []) or []

    canonical_founders = [
        {
            "name": f["name"],
            "founder_id": f.get("founder_id", f"founder_{i:03d}"),
            "common_shares": int(f.get("common_shares", 0)),
            "vesting": f.get("vesting"),
        }
        for i, f in enumerate(founders, start=1)
    ]
    canonical_preferred = [
        {
            "series_id": s.get("series_id", s["series_name"].lower().replace(" ", "_")),
            "series_name": s["series_name"],
            "shares": int(s["shares"]),
            "original_issue_price": float(s.get("original_issue_price", s.get("oip", 0))),
            "original_conversion_price": float(s.get("original_conversion_price", s.get("ocp", 0))),
            "current_conversion_price": float(s.get("current_conversion_price", s.get("ocp", 0))),
            "issuance_date": s["issuance_date"],
            "liquidation_preference_multiple": float(s.get("liquidation_preference_multiple", 1.0)),
            "liquidation_preference_type": s.get("liquidation_preference_type", "non_participating"),
            "participation_cap_multiple": s.get("participation_cap_multiple"),
            "anti_dilution_protection": s.get("anti_dilution_protection", "none"),
            # v0.4.8: per-series AD knobs. Default to NVCA-default semantics so
            # downstream priced_round.py sees the right contract; the input
            # may omit these fields and they'll be filled in here.
            "ad_trigger_basis": s.get("ad_trigger_basis", "original_issue_price"),
            "ad_a_denominator_basis": s.get(
                "ad_a_denominator_basis",
                "nvca_broad" if s.get("anti_dilution_protection") == "broad_based_weighted_average" else "nvca_narrow",
            ),
            "ad_cp2_floor": s.get("ad_cp2_floor"),
            "ad_carve_outs": s.get("ad_carve_outs", "nvca_default"),
            "dividend_rate_percent": s.get("dividend_rate_percent"),
            "dividend_cumulative": bool(s.get("dividend_cumulative", False)),
            "pro_rata_rights": bool(s.get("pro_rata_rights", False)),
        }
        for s in preferred_series
    ]
    canonical_option_pool = {
        "plan_type": option_pool.get("plan_type", "nso"),
        "authorized": int(option_pool.get("authorized", 0)),
        "issued_and_outstanding": int(option_pool.get("issued", 0)),
        "exercised_and_outstanding": int(option_pool.get("exercised", 0)),
        "available_for_grant": int(option_pool.get("unallocated", 0)),
        "expired_or_forfeited": int(option_pool.get("expired_or_forfeited", 0)),
    }

    cap_state: dict[str, Any] = {
        "as_of_date": inputs.get("analysis_date", ""),
        "currency": currency,
        "founders": canonical_founders,
        "common_batches": common_batches,
        "preferred_series": canonical_preferred,
        # v0.4.8: cap_table_history carries prior anti_dilution_applied events.
        # Read by priced_round.py's stale-CCP guard. Optional in inputs; defaults
        # to an empty list. cap_state_after_round.py writes new events here.
        **({"cap_table_history": inputs["cap_table_history"]} if "cap_table_history" in inputs else {}),
        "option_pool": canonical_option_pool,
        "outstanding_options": _build_outstanding_options(instruments.get("option_grants", []) or []),
        "outstanding_safes": _build_outstanding_safes(instruments.get("safes", []) or []),
        "outstanding_notes": _build_outstanding_notes(instruments.get("notes", []) or []),
        "outstanding_warrants": instruments.get("warrants", []) or [],
        "as_converted_totals": _compute_as_converted_totals(
            canonical_founders, canonical_preferred, canonical_option_pool, common_batches
        ),
        "metadata": {
            "produced_by": "cap_state.py",
            "source_inputs": ["inputs.json", "instruments.json"],
        },
    }
    return cap_state


def _print_pretty(receipt: dict[str, Any], data: dict[str, Any]) -> None:
    """Human-readable summary to stderr."""
    fd = data["as_converted_totals"]["fully_diluted_shares"]
    sys.stderr.write(f"cap_state written: {receipt['path']} ({receipt['bytes']:,} bytes)\n")
    sys.stderr.write(f"  founders: {len(data['founders'])}\n")
    sys.stderr.write(f"  preferred series: {len(data['preferred_series'])}\n")
    sys.stderr.write(
        f"  outstanding SAFEs: {len(data['outstanding_safes'])} | "
        f"notes: {len(data['outstanding_notes'])} | "
        f"warrants: {len(data['outstanding_warrants'])}\n"
    )
    sys.stderr.write(f"  option grants: {len(data['outstanding_options'])}\n")
    sys.stderr.write(f"  pre-financing fully-diluted shares: {fd:,}\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True, help="Path to inputs.json")
    p.add_argument("--instruments", required=True, help="Path to instruments.json")
    p.add_argument("--run-id", required=True, help="Run identifier for metadata")
    p.add_argument("-o", "--output", required=True, help="Output cap_state.json path")
    p.add_argument("--currency", default="USD", help="Currency code (default USD)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON + stderr summary")
    args = p.parse_args()

    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)

    cap_state = build_cap_state(inputs, instruments, currency=args.currency)
    schema = load_schema(os.path.join(_SCHEMA_DIR, "cap_state.schema.json"))

    try:
        receipt = write_artifact(
            data=cap_state,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"cap_state.py: schema validation failed: {e}\n")
        return 1

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        _print_pretty(receipt, cap_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
