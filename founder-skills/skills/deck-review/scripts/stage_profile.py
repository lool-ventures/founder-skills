#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Producer for stage_profile.json.

Validates against stage_profile.schema.json. Supports --rebuild-stage to
rebuild expected_framework / stage_benchmarks for a corrected stage
(closes #14 — manual mutation when founder picks a different stage).

Stage table below mirrors references/deck-best-practices.md. Update both
together — there is no automated cross-check yet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TypedDict

from _artifact_writer import ArtifactValidationError, load_schema, write_artifact


class _StageBenchmarks(TypedDict):
    round_size_range: str
    expected_traction: str
    runway_expectation: str


class _StageEntry(TypedDict):
    expected_framework: list[str]
    stage_benchmarks: _StageBenchmarks


_STAGE_TABLE: dict[str, _StageEntry] = {
    "pre_seed": {
        "expected_framework": [
            "purpose",
            "problem",
            "solution_product",
            "why_now",
            "market",
            "early_signals",
            "team",
            "ask_milestones",
        ],
        "stage_benchmarks": {
            "round_size_range": "$500K-$2.5M",
            "expected_traction": "Prototype, LOIs, waitlist signals",
            "runway_expectation": "12-18 months",
        },
    },
    "seed": {
        "expected_framework": [
            "purpose_traction",
            "problem",
            "solution_product",
            "traction_kpis",
            "market",
            "competition",
            "business_model_pricing",
            "gtm",
            "unit_economics",
            "team",
            "financials",
            "ask_milestones",
        ],
        "stage_benchmarks": {
            "round_size_range": "$2M-$6M",
            "expected_traction": "$300K-$500K ARR signals",
            "runway_expectation": "18-24 months",
        },
    },
    "series_a": {
        "expected_framework": [
            "purpose_traction",
            "problem",
            "solution_product",
            "traction_kpis",
            "cohort_data",
            "ltv_cac",
            "market",
            "competition",
            "business_model_pricing",
            "gtm",
            "unit_economics",
            "team",
            "financials",
            "ask_milestones",
        ],
        "stage_benchmarks": {
            "round_size_range": "$8M-$15M",
            "expected_traction": "$1M+ ARR with cohort retention data",
            "runway_expectation": "18-24 months",
        },
    },
    # Out-of-scope stages get stub benchmarks so the schema validates;
    # compose_report.py will emit STAGE_OUT_OF_SCOPE.
    "series_b": {
        "expected_framework": [],
        "stage_benchmarks": {
            "round_size_range": "out of calibrated scope",
            "expected_traction": "out of calibrated scope",
            "runway_expectation": "out of calibrated scope",
        },
    },
    "growth": {
        "expected_framework": [],
        "stage_benchmarks": {
            "round_size_range": "out of calibrated scope",
            "expected_traction": "out of calibrated scope",
            "runway_expectation": "out of calibrated scope",
        },
    },
}


def _normalize_stage_arg(value: str) -> str:
    """Coerce a stage CLI arg to this skill's canonical underscore form.

    The shared founder context stores the hyphenated spelling, and sibling skills
    mix separators for the same token. argparse applies type= BEFORE choices=, so
    this accepts either spelling without widening the valid set. Without it, a
    stage read from founder context reaches this flag in the wrong dialect and
    argparse exits 2 — a break that only prose currently prevents.
    """
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def main() -> int:
    p = argparse.ArgumentParser(description="Producer for stage_profile.json")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    p.add_argument(
        "--rebuild-stage",
        type=_normalize_stage_arg,
        choices=sorted(_STAGE_TABLE.keys()),
        help="Rebuild for a founder-corrected stage; framework/benchmarks come from internal table",
    )
    p.add_argument(
        "--confidence",
        choices=["high", "low"],
        default="high",
        help="Confidence to record on a --rebuild-stage (high when founder picked a different "
        "stage; low when they were unsure / proceeding best-effort)",
    )
    args = p.parse_args()

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("Error: stdin must be a JSON object", file=sys.stderr)
        return 1

    if args.rebuild_stage:
        original_stage = data.get("detected_stage", "unknown")
        data["detected_stage"] = args.rebuild_stage
        data["confidence"] = args.confidence
        evidence = list(data.get("evidence", []))
        if args.confidence == "low" and args.rebuild_stage == original_stage:
            evidence.append("Founder unsure; proceeding with detected stage at low confidence")
        else:
            evidence.append(f"Founder corrected stage from {original_stage} to {args.rebuild_stage}")
        data["evidence"] = evidence
        data["expected_framework"] = list(_STAGE_TABLE[args.rebuild_stage]["expected_framework"])
        data["stage_benchmarks"] = dict(_STAGE_TABLE[args.rebuild_stage]["stage_benchmarks"])

    schema = load_schema(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "references",
            "schemas",
            "stage_profile.schema.json",
        )
    )

    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        print(f"Error: stage_profile validation failed: {e}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
