#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cross-extraction confidence modulator (demote-only) for cap-table Lane-1.

When multiple extractors produce values for the same field (e.g. a sub-agent
extracts purchase_amount via prose-reading AND a regex extractor matches
"$X (the Purchase Amount)"), this script cross-checks them and modulates the
per-field confidence DOWNWARDS when they disagree.

Demote-only is a deliberate constraint:
  - Agreement does NOT bump confidence higher than the highest-confidence
    extractor said it was. (Confidence is set by the source extractor's
    rules, not boosted by quorum.)
  - Disagreement DEMOTES confidence to the lower of the two extractors,
    then DEMOTES one more level (high→medium, medium→low, low→absent).
  - The forward verifier's value_in_doc check and the invariant bounds
    checker remain the actual gates; cross_check is informational
    confidence-signal only.

Why demote-only: bumping on quorum is fragile — both extractors might share
a confused assumption about the document. Demoting on disagreement is
asymmetric in the right direction (toward humility).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "absent": 0}
DEMOTE_NEXT = {"high": "medium", "medium": "low", "low": "absent", "absent": "absent"}


def _values_compatible(a: Any, b: Any) -> bool:
    """Lightweight value-equality check.
    - Numeric: 1% relative tolerance (or 1e-6 absolute for tiny values)
    - String: case-insensitive bidirectional substring match
    - None: only matches None
    - Dict/list: deep equality
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if a == 0 and b == 0:
            return True
        if abs(a) < 1e-6 or abs(b) < 1e-6:
            return abs(float(a) - float(b)) < 1e-6
        return abs(float(a) - float(b)) / max(abs(float(a)), abs(float(b))) < 0.01
    if isinstance(a, str) and isinstance(b, str):
        an, bn = a.strip().lower(), b.strip().lower()
        if an == bn:
            return True
        return (an in bn) or (bn in an)
    return bool(a == b)


def cross_check(field_name: str, extractions: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-check ≥2 extractions of the same field. Returns a dict with:
    - "agreed_value": the value all sources agree on (or None if disagreement)
    - "confidence_modulated": demoted confidence if disagreement
    - "n_sources": count of extractions
    - "disagreement": True if any pair disagrees
    - "source_values": list of (extractor_id, value, original_confidence) tuples
    """
    if not extractions:
        return {
            "field_name": field_name,
            "n_sources": 0,
            "disagreement": False,
            "agreed_value": None,
            "confidence_modulated": "absent",
            "source_values": [],
        }

    source_values = [
        {
            "extractor_id": e.get("extractor_id", "unknown"),
            "value": e.get("value"),
            "confidence": e.get("confidence", "absent"),
        }
        for e in extractions
    ]

    if len(extractions) == 1:
        return {
            "field_name": field_name,
            "n_sources": 1,
            "disagreement": False,
            "agreed_value": extractions[0].get("value"),
            "confidence_modulated": extractions[0].get("confidence", "absent"),
            "source_values": source_values,
        }

    # Pairwise check
    disagreement = False
    base_value = extractions[0].get("value")
    for e in extractions[1:]:
        if not _values_compatible(base_value, e.get("value")):
            disagreement = True
            break

    # Confidence: start with the MINIMUM (most cautious) of all sources
    confs = [e.get("confidence", "absent") for e in extractions]
    min_conf = min(confs, key=lambda c: CONFIDENCE_RANK.get(c, 0))

    modulated = DEMOTE_NEXT.get(min_conf, "absent") if disagreement else min_conf

    return {
        "field_name": field_name,
        "n_sources": len(extractions),
        "disagreement": disagreement,
        "agreed_value": base_value if not disagreement else None,
        "confidence_modulated": modulated,
        "source_values": source_values,
    }


def cross_check_all(extractions_by_field: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Cross-check every field across all extraction sources.

    extractions_by_field: {"purchase_amount": [{value, confidence, extractor_id}, ...], ...}
    """
    out = {}
    n_disagreements = 0
    for field_name, sources in extractions_by_field.items():
        result = cross_check(field_name, sources)
        out[field_name] = result
        if result["disagreement"]:
            n_disagreements += 1
    return {
        "n_fields": len(extractions_by_field),
        "n_disagreements": n_disagreements,
        "per_field": out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extractions",
        required=True,
        help="JSON file containing {field_name: [{value, confidence, extractor_id}, ...]}",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()

    with open(args.extractions) as f:
        data = json.load(f)

    report = cross_check_all(data)

    payload = json.dumps(report, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w") as f:
            f.write(payload)
        print(json.dumps({"ok": True, "output": os.path.abspath(args.output)}, indent=2 if args.pretty else None))
    else:
        print(payload)
    # Informational mode: cross-checker never blocks. Disagreements surface in
    # the report payload; downstream consumers decide what to do.
    return 0


if __name__ == "__main__":
    sys.exit(main())
