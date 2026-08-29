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
`instruments.json.convertible_notes[]`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rule_pack import RULE_PACK_VERSION  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

VALID_LIQ_PREF_TYPES = {"non_participating", "participating", "participating_capped"}
VALID_ANTI_DILUTION = {
    "none",
    "broad_based_weighted_average",
    "narrow_based_weighted_average",
    "full_ratchet",
}
VALID_JURISDICTIONS = {"israeli", "delaware"}
# Only the two shapes `_compute_a_denominator` implements. A charter defining a third broad-based
# variant (e.g. one excluding the unallocated reserve) has no representation here -- returning null
# and letting counsel resolve it is correct; picking the nearer value would be a silent misread.
VALID_AD_A_DENOMINATOR_BASES = {"nvca_broad", "nvca_narrow"}


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

        # Anti-dilution conversion-price FLOOR, > 0 when present.
        #
        # Optional: many charters have no floor, and absence must stay a legal reading of the
        # document rather than an extraction failure. But when the charter HAS one, failing to
        # extract it is not a cosmetic omission -- the floor limits how far the conversion price
        # falls, so ignoring it drives the adjusted price too low, inflates preferred-as-converted,
        # and UNDERSTATES founder ownership. Measured on the golden-10 cap table: 11.11% founder
        # ownership with a $0.50 charter floor honoured, 5.95% with it missed.
        #
        # Only positivity is checked here. A floor ABOVE the current conversion price is a
        # contradictory term, but that judgement already lives in the solver
        # (`E_AD_CP2_FLOOR_ABOVE_CURRENT_PRICE`, rule `anti_dilution.ratchet_down_only`) where it can
        # be stated against the round's own numbers. Duplicating it here would be two copies of one
        # domain rule, free to drift.
        floor = series.get("ad_cp2_floor")
        if floor is not None and (not isinstance(floor, (int, float)) or floor <= 0):
            errors.append(f"{ctx}.ad_cp2_floor must be > 0 when present; got {floor!r}")

        # Weighted-average DENOMINATOR basis. Broad-based counts the option pool and other
        # convertibles in the "A" term; narrow-based counts only outstanding preferred, which makes
        # the adjustment more favourable to the holder and costs the founder more. Measured on a
        # representative round, the two differ by 0.24-0.47 percentage points of founder ownership.
        #
        # `cap_state.py` stamps a default derived from `anti_dilution_protection`, which is right for
        # the ordinary charter that labels its protection consistently. Extraction is the only route
        # by which a charter that does NOT can reach the math -- and the derived default gives no
        # signal that it was a guess.
        basis = series.get("ad_a_denominator_basis")
        if basis is not None and basis not in VALID_AD_A_DENOMINATOR_BASES:
            errors.append(
                f"{ctx}.ad_a_denominator_basis must be one of {sorted(VALID_AD_A_DENOMINATOR_BASES)}; got {basis!r}"
            )

    return errors


def detect_counsel_review_items(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-AoA counsel-review flags (Israeli AoA gotchas).

    Each item has a `rule_id` matching `cap-table-rules.json` Israeli AoA
    domain entries. Downstream
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

    # Pay-to-play provision detection (rule pack:
    # anti_dilution.pay_to_play_provision_detected). P2P math is NOT modeled
    # currently; this is a detection-only counsel flag.
    if detect_pay_to_play(fields):
        items.append(
            {
                "rule_id": "anti_dilution.pay_to_play_provision_detected",
                "severity": "high",
                "summary": (
                    "AoA contains a pay-to-play provision: AD-protected holders who "
                    "do not participate pro-rata in a down round forfeit AD protection "
                    "and/or convert to common. The current solver does NOT model P2P "
                    "math; dilution figures may over-protect non-participating "
                    "holders. Counsel verifies whether each AD-protected holder will "
                    "participate at full pro-rata."
                ),
            }
        )

    return items


# Pay-to-play text patterns. Matches common drafting language across NVCA-form
# COIs, Israeli AoAs, and Cooley templates. Each pattern is OR-combined; one
# match is enough to flag.
_P2P_PATTERNS = [
    r"\bpay\s*[- ]?\s*to\s*[- ]?\s*play\b",
    r"\bpay\b.{0,40}\bplay\b",  # within-sentence variant
    r"failure\s+to\s+(participate|invest|purchase).{0,80}(forfeit|lose|convert)",
    r"(forfeit|lose).{0,40}anti[\s-]*dilution",
    r"mandatory\s+conversion.{0,80}(non[\s-]*participating|fail|did\s+not\s+participate)",
    r"(participate|invest|purchase)\s+(pro\s*-?\s*rata|its\s+pro\s*rata\s+share).{0,120}(or|otherwise).{0,40}(forfeit|lose|convert|automatically\s+convert)",
    r"(shadow|junior)\s+series.{0,80}(non[\s-]*participat|failure)",
    r"(non[\s-]*participat|failure).{0,120}(shadow|junior)\s+series",
]


def detect_pay_to_play(fields: dict[str, Any]) -> bool:
    """True if any pay-to-play text pattern matches the AoA source text.

    Reads `fields["source_text"]` if present (caller may attach the full
    AoA text from extract_aoa's input). Falls back to scanning any free-text
    fields the extractor surfaced (`pay_to_play_clause_text`, `notes`).

    Detection-only — the rule fires as a counsel-review flag.
    A future extension will implement P2P math (forced conversion, AD-protection
    forfeiture, shadow-series mechanics).
    """
    import re

    haystacks: list[str] = []
    src = fields.get("source_text")
    if isinstance(src, str):
        haystacks.append(src.lower())
    for k in ("pay_to_play_clause_text", "notes", "free_text_notes"):
        v = fields.get(k)
        if isinstance(v, str):
            haystacks.append(v.lower())
    # Explicit boolean override — if the extractor identified P2P upstream
    if fields.get("pay_to_play_present") is True:
        return True

    if not haystacks:
        return False

    return any(any(re.search(pattern, h, re.IGNORECASE | re.DOTALL) for h in haystacks) for pattern in _P2P_PATTERNS)


def merge_into_inputs(
    inputs_path: str,
    preferred_series: list[dict[str, Any]],
    source_doc: str | None,
    extraction_confidence_per_series: dict[str, str] | None = None,
    aoa_findings: dict[str, Any] | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Merge validated AoA preferred_series block into existing inputs.json.

    Behavior:
    - Reads existing inputs.json (must exist; missing → status 'merge_failed').
    - For each series in `preferred_series`: if a series with the same
      `series_name` already exists and `replace_existing` is False, this is a
      CONFLICT — nothing is written (atomic), status 'conflict'. With
      `replace_existing=True`, the existing entry is replaced in place with
      fresh provenance.
    - Otherwise append to inputs.preferred_series[].
    - Stamps `extraction_provenance` on each new/replaced entry.
    - Writes inputs.json back only when there are no unresolved conflicts.

    Returns a structured receipt (counts, paths, any conflicts).
    """
    if not os.path.exists(inputs_path):
        return {"status": "merge_failed", "reason": f"inputs.json not found at {inputs_path}"}

    with open(inputs_path, encoding="utf-8") as f:
        inputs = json.load(f)

    existing_series = inputs.setdefault("preferred_series", [])
    existing_index = {s.get("series_name"): i for i, s in enumerate(existing_series) if isinstance(s, dict)}

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # First pass: detect conflicts WITHOUT mutating, so a no-flag conflict is an
    # atomic no-write (nothing partially merged).
    conflicts = [
        series.get("series_name")
        for series in preferred_series
        if isinstance(series.get("series_name"), str) and series.get("series_name") in existing_index
    ]
    if conflicts and not replace_existing:
        return {
            "status": "conflict",
            "added": [],
            "conflicts": conflicts,
            "reason": (
                f"{len(conflicts)} series already present in inputs.preferred_series[]: "
                f"{conflicts}. Nothing was written. Re-run with --replace-existing to "
                f"overwrite in place."
            ),
        }

    added: list[str] = []
    replaced: list[str] = []
    for series in preferred_series:
        name = series.get("series_name")
        if not isinstance(name, str):
            # Series without a string series_name is invalid — skip silently
            continue
        new_entry = dict(series)
        confidence_level = (extraction_confidence_per_series or {}).get(name, "medium")
        new_entry["extraction_provenance"] = {
            "source_doc": source_doc or "",
            "extraction_confidence": confidence_level,
            "extracted_at": now,
        }
        if name in existing_index:
            # replace_existing path: overwrite in place with fresh provenance.
            existing_series[existing_index[name]] = new_entry
            replaced.append(name)
        else:
            existing_index[name] = len(existing_series)
            existing_series.append(new_entry)
            added.append(name)

    # Persist AoA-level findings (pay_to_play_detected, etc.) so
    # rule_audit.py --phase=post_math's _runtime_event_predicate can suppress
    # P2P false negatives + surface P2P true positives. Without this, P2P
    # detection in detect_pay_to_play() fires at extraction time but the flag
    # is never persisted, so the downstream counsel item silently drops when
    # runtime gating is engaged.
    if aoa_findings:
        existing_findings = inputs.get("aoa_findings", {}) or {}
        existing_findings.update(aoa_findings)
        inputs["aoa_findings"] = existing_findings
        # v0.4.10 → v0.5.0: pay_to_play_detected lives under aoa_findings;
        # the top-level alias is still emitted for v0.4.10-cache compatibility
        # NOTE: nothing rewrites this in production. An earlier comment here said the loaders
        # do, via a soft carve-out in _artifact_io.load_inputs -- but no producer imports that
        # module, so the rewrite never runs. rule_audit.py reads BOTH shapes, which is why this
        # has never surfaced as a bug.
        if aoa_findings.get("pay_to_play_detected") is True:
            inputs["pay_to_play_detected"] = True

    # v0.5.0: stamp schema_version on inputs.json so the typed loader catches
    # stale AoA-merged inputs against a newer skill version (§10.4).
    inputs.setdefault("metadata", {})
    inputs["metadata"]["schema_version"] = "v0.5.0-inputs"

    # Write back
    with open(inputs_path, "w", encoding="utf-8") as f:
        json.dump(inputs, f, indent=2)

    return {
        "status": "merged",
        "added": added,
        "added_count": len(added),
        "replaced": replaced,
        "replaced_count": len(replaced),
        "total_preferred_series_after_merge": len(existing_series),
        "inputs_path": os.path.abspath(inputs_path),
        "aoa_findings_persisted": bool(aoa_findings),
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
        err_receipt = {
            "status": "validation_failed",
            "errors": errors,
            "extraction_type": extraction.get("extraction_type"),
        }
        print(json.dumps(err_receipt, indent=2 if args.pretty else None))
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
        # Also persist AoA-level findings (P2P detection, etc.) so
        # rule_audit.py's _runtime_event_predicate can read them from inputs.json.
        # Without this, P2P detection at extract time would silently drop
        # downstream when runtime gating is engaged in rule_audit post_math.
        aoa_findings_to_persist = {
            "pay_to_play_detected": detect_pay_to_play(fields),
        }
        merge_result = merge_into_inputs(
            args.inputs,
            preferred_series,
            source_doc=args.source_doc,
            extraction_confidence_per_series=series_conf,
            aoa_findings=aoa_findings_to_persist,
            replace_existing=args.replace_existing,
        )
        receipt["merge"] = merge_result
        merge_status = merge_result.get("status")
        if merge_status == "conflict":
            # No-write atomic conflict (no --replace-existing).
            receipt["status"] = "conflict"
            sys.stderr.write(
                f"extract_aoa.py: merge conflict — {len(merge_result['conflicts'])} "
                f"series already present. Nothing written. Re-run with --replace-existing.\n"
            )
            print(json.dumps(receipt, indent=2 if args.pretty else None))
            return 2
        if merge_status == "merge_failed":
            receipt["status"] = "merge_failed"
            sys.stderr.write(f"extract_aoa.py: merge failed — {merge_result.get('reason')}\n")
            print(json.dumps(receipt, indent=2 if args.pretty else None))
            return 1
        # merged
        receipt["status"] = "merged"

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
