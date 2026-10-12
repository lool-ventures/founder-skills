#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Persist one partner's round-1 assessment or round-2 rebuttal from its sub-agent hand-off.

Steps 6 and 6b pipe each gated hand-off through this script into the run dir. It stamps the run id and
`graded_against.fund_profile` (the fund profile beside `-o`, `fund_profile.stamp_profile`), so
compose_discussion.py and compose_report.py can tell a partner file written against an earlier fund profile
(PARTNER_ARTIFACTS_STALE). The stamp is the script's, never the model's: any stamp in the input is replaced.

A refused input exits 1 with the diagnostic on stdout and a line on stderr, and `-o` is left untouched.

Usage:
    cat "$HANDOFF_DIR/partner_visionary_output.json" | python persist_partner.py --kind assessment \\
        --archetype visionary --run-id "$RUN_ID" -o "$SIM_DIR/partner_assessment_visionary.json"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

ARCHETYPES = ("visionary", "operator", "analyst")
KINDS = ("assessment", "rebuttal")


def _fund_profile_module() -> Any:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import fund_profile

    return fund_profile


def _refuse(errors: list[str], output_path: str) -> NoReturn:
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": errors}}) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(errors)}", file=sys.stderr)
    print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def validate(data: Any, kind: str, archetype: str, output_path: str) -> list[str]:
    """What makes this hand-off unfit to be this partner's file. The content itself is validated downstream
    (compose_discussion.py); this checks only that it is this archetype's, of this kind, going to its own file."""
    errors: list[str] = []
    expected = f"partner_{kind}_{archetype}.json"
    if os.path.basename(output_path) != expected:
        errors.append(f"OUTPUT_NAME_MISMATCH: the {archetype} {kind} is written to {expected}, not to this -o")
    if not isinstance(data, dict):
        errors.append("the hand-off is not a JSON object")
        return errors
    partner = data.get("partner")
    if partner != archetype:
        errors.append(
            f"PARTNER_MISMATCH: the hand-off's partner field is not {archetype!r}; "
            "re-dispatch this archetype (each archetype's file comes from its own dispatch)"
        )
    return errors


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Persist a partner assessment or rebuttal hand-off (reads JSON on stdin)")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--archetype", required=True, choices=ARCHETYPES)
    p.add_argument("--run-id", required=True, help="Run identifier injected into metadata.run_id")
    p.add_argument("-o", "--output", required=True, help="The partner file in the run dir")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.run_id.strip():
        print("Error: --run-id is empty", file=sys.stderr)
        sys.exit(2)
    if sys.stdin.isatty():
        print("Error: pipe the hand-off JSON via stdin", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        _refuse([f"invalid JSON input: {e}"], args.output)

    errors = validate(data, args.kind, args.archetype, args.output)
    if errors:
        _refuse(errors, args.output)

    fp = _fund_profile_module()
    if fp.profile_fingerprint_in(os.path.dirname(os.path.abspath(args.output))) is None:
        _refuse(
            ["FUND_PROFILE_MISSING: no readable fund_profile.json beside -o; build the fund profile (Step 4) first"],
            args.output,
        )
    result = {k: v for k, v in data.items() if k not in ("metadata", "graded_against")}
    fp.stamp_profile(result, args.output)
    result["metadata"] = {"run_id": args.run_id}

    abs_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    text = json.dumps(result, indent=2 if args.pretty else None) + "\n"
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)
    receipt = {
        "ok": True,
        "path": abs_path,
        "bytes": len(text.encode("utf-8")),
        "fund_profile_stamped": result["graded_against"]["fund_profile"] is not None,
    }
    sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
