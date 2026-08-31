#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Persist a main-thread-authored competitive-positioning artifact, with provenance.

WHY THIS EXISTS. `compose_report.py` raises `UNVALIDATED_ARTIFACT` at HIGH severity
when an artifact's `_produced_by` stamp is missing or wrong -- "run the script instead
of writing the file directly". Its `EXPECTED_PRODUCERS` map covered five artifacts,
and the three this skill has the MODEL write by heredoc (`product_profile.json`,
`landscape_draft.json`, `positioning.json`) were its exact complement: unlisted because
they had no producer to stamp them. The enforcement mechanism was already built, already
high-severity, and structurally could not cover the artifacts most in need of it.

WHAT THIS BUYS, STATED PLAINLY SO NOBODY OVERREADS IT.
  * Presence of required keys, and a provenance stamp. That is all.
  * NOT shape validation. The 2026-07-05 cap-table incident's failure mode was an
    *ad-hoc richer* payload -- EXTRA keys, not missing ones -- which a required-keys
    check cannot see. This skill has no machine-readable JSON schemas (only the prose
    `references/artifact-schemas.md`), and authoring three is a larger project than the
    finding justifies; that gap is tracked, not closed here.
  * NOT proof that a script authored the content. `_produced_by` is a self-reported
    string in a file the model can write. After this script the model still AUTHORS the
    content; only the write path moves. The value is that the write now goes through one
    place that can be given a schema later, and that a direct heredoc becomes detectable.

Reads JSON on stdin, writes the stamped artifact to `-o`. On rejection it follows the
fleet producer contract: diagnostic to stdout, reason to stderr, `-o` LEFT UNTOUCHED,
exit non-zero -- so the prior good artifact survives and SKILL.md's "the pipe fails next"
branch is reachable.

Usage:
  cat draft.json | python3 persist_agent_artifact.py --artifact positioning.json \
      -o "$ANALYSIS_DIR/positioning.json" --run-id "$RUN_ID"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, NoReturn

# Required top-level keys per artifact. Modelled on ic-sim's REQUIRED_KEYS rather than a
# JSON Schema, for the reason in the module docstring. Keys chosen as those a downstream
# consumer dereferences without a guard -- a missing one is an empty report section rather
# than a loud failure, which is exactly the class worth catching at the write.
# Taken from `references/artifact-schemas.md`'s per-artifact "Required: yes" rows in the
# TOP-LEVEL table, NOT invented. Two corrections already, both the same error class:
#   1. A first draft guessed `category` / `target_customer` for product_profile.json. Neither
#      exists -- the field is `target_customers`, and `category` belongs to a competitors[]
#      entry in a DIFFERENT table of the same section.
#   2. A second draft omitted `metadata`, which is Required:yes on all three. Consequence was
#      live: without it an artifact could be persisted carrying no `metadata.run_id`, and
#      `compose_report.py`'s STALE_ARTIFACT parity loop SKIPS artifacts with no run_id -- so
#      the omission disabled a different check entirely.
# `test_required_keys_match_the_documented_top_level_table` now pins the set both ways.
REQUIRED_KEYS: dict[str, set[str]] = {
    "product_profile.json": {
        "company_name",
        "slug",
        "product_description",
        "target_customers",
        "value_propositions",
        "differentiation_claims",
        "stage",
        "sector",
        "business_model",
        "input_mode",
        "source_materials",
        "metadata",
    },
    "landscape_draft.json": {"competitors", "candidate_axes", "metadata"},
    # `moat_assessments` is deliberately NOT required: the schema marks it optional and
    # SKILL.md Step 5 tells the main thread to write `{}` or omit it rather than author a
    # per-slug draft that `moat_scores.json` immediately supersedes.
    "positioning.json": {"views", "differentiation_claims", "metadata"},
}

# The stamp `compose_report.py:EXPECTED_PRODUCERS` compares against. Bare module name,
# matching every sibling producer's convention.
STAMP = "persist_agent_artifact"


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    """Reject loudly without clobbering `-o`. Canonical copy: market-sizing/market_sizing.py."""
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", required=True, choices=sorted(REQUIRED_KEYS), help="Which artifact this is")
    ap.add_argument("-o", "--output", help="Destination path (canonical artifact)")
    ap.add_argument("--run-id", help="Run id stamped into metadata.run_id")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--input", default="-", help="Input JSON file, or '-' for stdin (default)")
    args = ap.parse_args()
    indent = 2 if args.pretty else None

    raw = sys.stdin.read() if args.input == "-" else pathlib.Path(args.input).read_text(encoding="utf-8")
    if not raw.strip():
        _fail_invalid(
            {"artifact": args.artifact, "validation": {"status": "invalid", "errors": ["empty input"]}},
            args.output,
            indent,
        )
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail_invalid(
            {
                "artifact": args.artifact,
                "validation": {"status": "invalid", "errors": [f"input is not valid JSON: {exc}"]},
            },
            args.output,
            indent,
        )

    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append(f"top level must be a JSON object, got {type(data).__name__}")
    else:
        missing = sorted(REQUIRED_KEYS[args.artifact] - set(data))
        if missing:
            errors.append(f"missing required key(s): {', '.join(missing)}")
    if errors:
        _fail_invalid(
            {"artifact": args.artifact, "validation": {"status": "invalid", "errors": errors}},
            args.output,
            indent,
        )

    # `--artifact X -o .../Y.json` would validate X's required keys and then stamp Y with a
    # provenance mark that looks valid to compose_report.py. The two must agree.
    if args.output and os.path.basename(args.output) != args.artifact:
        _fail_invalid(
            {
                "artifact": args.artifact,
                "validation": {
                    "status": "invalid",
                    "errors": [
                        f"--artifact {args.artifact} does not match the output filename "
                        f"{os.path.basename(args.output)!r}; the required-key set and the "
                        f"provenance stamp would be applied to the wrong artifact"
                    ],
                },
            },
            args.output,
            indent,
        )

    assert isinstance(data, dict)
    data["_produced_by"] = STAMP
    if args.run_id:
        meta = data.setdefault("metadata", {})
        if isinstance(meta, dict):
            meta["run_id"] = args.run_id

    payload = json.dumps(data, indent=indent) + "\n"
    if args.output:
        pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.output).write_text(payload, encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "artifact": args.artifact,
                    "output_path": os.path.abspath(args.output),
                    "bytes": len(payload),
                },
                indent=indent,
            )
        )
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
