#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Anti-hallucination validator + ingest helper for AoA extraction.

Lane-1 AoA documents (Articles of Association — Israeli Ltd or Delaware C-corp
foundational governance docs) use the dedicated Context A sub-context
`ARTICLES_OF_ASSOCIATION_EXTRACTION` rather than `INSTRUMENT_EXTRACTION`. The
sub-agent reads the AoA and returns a structured JSON shape describing the
per-preferred-series terms (OIP, liquidation preference, anti-dilution, etc.)
plus AoA-level metadata (drag-along threshold, §102 plan reference).

This script:
  1. Validates the extraction JSON against the schema-canonical
     `preferred_series` item shape (matches cap_state.schema.json).
  2. Optionally merges the validated preferred_series block into an existing
     `inputs.json` (founder context already populated with company_name +
     jurisdiction + founders). `shares` is left null in the extraction —
     populated by founder input at merge time.
  3. Surfaces AoA-specific counsel-review items (drag-along < 75% in Israeli
     jurisdiction, §102 references absent when expected, etc.) for downstream
     rule_audit consumption.

Usage:
    cat aoa_extraction.json | python3 extract_aoa.py \\
        --run-id 20260521T120000Z \\
        --inputs $REVIEW_DIR/inputs.json \\  # for merge mode (writes new
                                              # preferred_series back to inputs.json)
        --source-doc /path/to/aoa.pdf \\
        --pretty

The dispatching agent then calls AskUserQuestion to fill in `shares` per
series + any low-confidence fields the validator flagged.

Schema: `extraction_type: "articles_of_association"` (NOT `instrument_type`).
Output goes to `inputs.json.preferred_series[]`, NOT
`instruments.json.notes[]`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

RULE_PACK_VERSION = "0.3.2"

VALID_LIQ_PREF_TYPES = {"non_participating", "participating", "participating_capped"}
VALID_ANTI_DILUTION = {
    "none",
    "broad_based_weighted_average",
    "narrow_based_weighted_average",
    "full_ratchet",
}
VALID_JURISDICTIONS = {"israeli", "delaware"}


def validate_aoa_extraction(extraction: dict[str, Any]) -> list[str]:
    """Validate the ARTICLES_OF_ASSOCIATION_EXTRACTION return shape.

    Checks structural validity + per-series field requirements + enum values.
    Does NOT do evidence verification (that's a separate step the dispatching
    agent runs by piping through `evidence_verifier.py` if `--source-doc` was
    provided).
    """
    errors: list[str] = []
    if extraction.get("extraction_type") != "articles_of_association":
        errors.append(f"extraction_type must be 'articles_of_association'; got {extraction.get('extraction_type')!r}")
    fields = extraction.get("fields", {})
    if not isinstance(fields, dict):
        errors.append("fields must be an object")
        return errors

    # Top-level AoA fields
    if "jurisdiction_structure" in fields and fields["jurisdiction_structure"] not in VALID_JURISDICTIONS:
        errors.append(
            f"jurisdiction_structure must be one of {sorted(VALID_JURISDICTIONS)}; "
            f"got {fields['jurisdiction_structure']!r}"
        )

    if "drag_along_threshold_pct" in fields and fields["drag_along_threshold_pct"] is not None:
        dt = fields["drag_along_threshold_pct"]
        if not isinstance(dt, (int, float)) or not (0.0 < dt <= 1.0):
            errors.append(f"drag_along_threshold_pct must be in (0, 1]; got {dt!r}")

    preferred_series = fields.get("preferred_series", [])
    if not isinstance(preferred_series, list):
        errors.append("preferred_series must be an array")
        return errors

    for i, series in enumerate(preferred_series):
        ctx = f"preferred_series[{i}]"
        if not isinstance(series, dict):
            errors.append(f"{ctx} must be an object")
            continue
        # Per-series required fields (AoA-extractable subset).
        # Intentionally NOT in required_at_extract:
        #   - `shares` and `series_id`: assigned at ingest (cap table / Carta)
        #   - `issuance_date`: per the real-doc calibration of 5 Israeli AoAs,
        #     restatement AoAs commonly amend prior series WITHOUT reciting
        #     the original SPA issuance date. Forcing the extractor to assert
        #     a date it cannot find produces low-confidence placeholders.
        #     Treat `issuance_date` as a downstream-merged field (from the
        #     SPA / Carta cap-table data), not an AoA-derivable field.
        required_at_extract = [
            "series_name",
            "original_issue_price",
            "original_conversion_price",
            "current_conversion_price",
        ]
        for r in required_at_extract:
            if series.get(r) is None:
                errors.append(f"{ctx} requires non-null {r}")

        # Liquidation preference enum
        lpt = series.get("liquidation_preference_type")
        if lpt is not None and lpt not in VALID_LIQ_PREF_TYPES:
            errors.append(
                f"{ctx}.liquidation_preference_type must be one of {sorted(VALID_LIQ_PREF_TYPES)}; got {lpt!r}"
            )
        if lpt == "participating_capped" and series.get("participation_cap_multiple") is None:
            errors.append(
                f"{ctx}.participation_cap_multiple is required when "
                f"liquidation_preference_type is 'participating_capped'"
            )

        # Anti-dilution enum
        ad = series.get("anti_dilution_protection")
        if ad is not None and ad not in VALID_ANTI_DILUTION:
            errors.append(f"{ctx}.anti_dilution_protection must be one of {sorted(VALID_ANTI_DILUTION)}; got {ad!r}")

        # Liquidation preference multiple ≥ 1
        lpm = series.get("liquidation_preference_multiple")
        if lpm is not None and (not isinstance(lpm, (int, float)) or lpm < 1.0):
            errors.append(f"{ctx}.liquidation_preference_multiple must be ≥ 1.0; got {lpm!r}")

        # OIP > 0
        oip = series.get("original_issue_price")
        if oip is not None and (not isinstance(oip, (int, float)) or oip <= 0):
            errors.append(f"{ctx}.original_issue_price must be > 0; got {oip!r}")

    return errors


def detect_counsel_review_items(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-AoA counsel-review flags (Israeli AoA gotchas).

    Each item has a `rule_id` matching `cap-table-rules.json` Israeli AoA
    domain entries (added in commit #7 post-J audit). Downstream
    `rule_audit.py` post-math phase consumes these.
    """
    items: list[dict[str, Any]] = []
    jurisdiction = fields.get("jurisdiction_structure")
    drag_along = fields.get("drag_along_threshold_pct")
    section_102 = fields.get("section_102_plan_reference")

    if jurisdiction == "israeli" and drag_along is not None and drag_along < 0.75:
        items.append(
            {
                "rule_id": "israeli_aoa.drag_along_threshold_below_75_percent",
                "severity": "high",
                "summary": (
                    f"Drag-along threshold of {drag_along:.0%} is below Israeli "
                    f"market standard of 75%. Israeli courts have flagged sub-75% "
                    f"thresholds in fiduciary disputes. Counsel review required "
                    f"before relying on the drag-along right."
                ),
            }
        )

    if jurisdiction == "israeli" and section_102 is False:
        items.append(
            {
                "rule_id": "israeli_aoa.section_102_plan_absent",
                "severity": "medium",
                "summary": (
                    "Israeli AoA does not reference a §102 option plan. If the "
                    "company plans to grant equity to Israeli employees, the §102 "
                    "trustee-track plan must be in place AND filed with the ITA "
                    "30 days before the first grant. Counsel review recommended."
                ),
            }
        )

    # Per-series counsel items
    for series in fields.get("preferred_series", []):
        lpm = series.get("liquidation_preference_multiple")
        if lpm is not None and lpm > 1.0:
            items.append(
                {
                    "rule_id": "israeli_aoa.liquidation_preference_above_1x",
                    "severity": "medium",
                    "summary": (
                        f"Series {series.get('series_name', '?')!r} has liquidation "
                        f"preference of {lpm}x — above market standard 1.0x. "
                        f"Often signals later-stage / bridge financing terms; "
                        f"verify with counsel + founder context."
                    ),
                }
            )
        if series.get("anti_dilution_protection") == "full_ratchet":
            items.append(
                {
                    "rule_id": "israeli_aoa.full_ratchet_anti_dilution",
                    "severity": "high",
                    "summary": (
                        f"Series {series.get('series_name', '?')!r} has full-ratchet "
                        f"anti-dilution — rare and aggressive. Most market AoAs use "
                        f"broad-based weighted average. Full ratchet substantially "
                        f"penalizes founders in any down round. Confirm intent."
                    ),
                }
            )

    return items


def merge_into_inputs(
    inputs_path: str,
    preferred_series: list[dict[str, Any]],
    source_doc: str | None,
    extraction_confidence_per_series: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge validated AoA preferred_series block into existing inputs.json.

    Behavior:
    - Reads existing inputs.json (must exist)
    - For each series in `preferred_series`: if a series with the same
      `series_name` already exists, error out (caller must resolve manually).
      Otherwise append to inputs.preferred_series[].
    - Stamps `extraction_provenance` on each new entry so downstream tooling
      can trace back to the AoA.
    - Writes inputs.json back.

    Returns a structured receipt (counts, paths, any conflicts).
    """
    if not os.path.exists(inputs_path):
        return {"status": "error", "reason": f"inputs.json not found at {inputs_path}"}

    with open(inputs_path, encoding="utf-8") as f:
        inputs = json.load(f)

    existing_series = inputs.setdefault("preferred_series", [])
    existing_names = {s.get("series_name") for s in existing_series}

    added: list[str] = []
    conflicts: list[str] = []
    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    for series in preferred_series:
        name = series.get("series_name")
        if name in existing_names:
            conflicts.append(name)
            continue
        new_entry = dict(series)
        # Provenance stamp
        confidence_level = (extraction_confidence_per_series or {}).get(name, "medium")
        new_entry["extraction_provenance"] = {
            "source_doc": source_doc or "",
            "extraction_confidence": confidence_level,
            "extracted_at": now,
        }
        existing_series.append(new_entry)
        added.append(name)

    if conflicts:
        return {
            "status": "conflict",
            "added": added,
            "conflicts": conflicts,
            "reason": (
                f"{len(conflicts)} series already present in inputs.preferred_series[]: "
                f"{conflicts}. Caller must resolve (replace vs skip vs rename) before "
                f"writing AoA extraction. Use --replace-existing to force overwrite."
            ),
        }

    # Write back
    with open(inputs_path, "w", encoding="utf-8") as f:
        json.dump(inputs, f, indent=2)

    return {
        "status": "merged",
        "added": added,
        "added_count": len(added),
        "total_preferred_series_after_merge": len(existing_series),
        "inputs_path": os.path.abspath(inputs_path),
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True, help="Per-engagement run identifier")
    p.add_argument(
        "--inputs",
        help="Path to inputs.json — if provided, validated preferred_series is merged here",
    )
    p.add_argument("--source-doc", help="Path to source AoA document (for provenance stamp)")
    p.add_argument(
        "--replace-existing",
        action="store_true",
        help="When a series with the same name already exists in inputs.preferred_series, replace it (default: error)",
    )
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    extraction = json.load(sys.stdin)

    errors = validate_aoa_extraction(extraction)
    if errors:
        receipt = {
            "status": "validation_failed",
            "errors": errors,
            "extraction_type": extraction.get("extraction_type"),
        }
        print(json.dumps(receipt, indent=2 if args.pretty else None))
        sys.stderr.write(f"extract_aoa.py: {len(errors)} validation error(s)\n")
        return 1

    fields = extraction.get("fields", {})
    preferred_series = fields.get("preferred_series", [])
    counsel_items = detect_counsel_review_items(fields)

    # Build per-series confidence map for provenance stamping
    series_conf: dict[str, str] = {}
    confidence_block = extraction.get("confidence", {})
    for series in preferred_series:
        name = series.get("series_name", "")
        per_series_key = f"preferred_series[{name}].original_issue_price"
        if per_series_key in confidence_block:
            series_conf[name] = confidence_block[per_series_key].get("level", "medium")

    receipt: dict[str, Any] = {
        "status": "validated",
        "extraction_type": "articles_of_association",
        "preferred_series_count": len(preferred_series),
        "counsel_review_items": counsel_items,
        "counsel_review_count": len(counsel_items),
        "rule_pack_version": RULE_PACK_VERSION,
    }

    if args.inputs:
        merge_result = merge_into_inputs(
            args.inputs,
            preferred_series,
            source_doc=args.source_doc,
            extraction_confidence_per_series=series_conf,
        )
        receipt["merge"] = merge_result
        if merge_result.get("status") == "conflict" and not args.replace_existing:
            sys.stderr.write(
                f"extract_aoa.py: merge conflict — {len(merge_result['conflicts'])} "
                f"series already present. Use --replace-existing to force.\n"
            )
            print(json.dumps(receipt, indent=2 if args.pretty else None))
            return 2

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
