#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Write `coverage_disclosure.json` for the HAND-ROLL route (`covered: false`).

WHY A STANDALONE SCRIPT AND NOT A FLAG ON AN EXISTING WRITER. Two producers already
emit this artifact -- `compose_report.py` for the covered/deterministic path and
`compose_extraction_report.py` for the extraction-only path -- but neither can serve
the hand-roll route:

  * `compose_report.py`'s write is inline in `main()`, between the coaching-payload
    build and the banner prepend; it is not a separable writer. More decisively,
    SKILL.md's covered branch says `compose_report.py` writes the file automatically,
    while the hand-roll branch is precisely the route where `compose_report.py` DOES
    NOT RUN (it requires `cap_state.json`, which a hand-roll may not have).
  * `compose_extraction_report.py` is a different route with a fixed payload.

So the route with the weakest guarantees -- a human-authored disclosure for math the
engine could not cover -- was the only one whose artifact nothing validated. SKILL.md
told the model to write it "by heredoc", and in the 2026-07-05 incident the agent did
exactly that, with an AD-HOC RICHER SCHEMA than the template.

THE EXTRA-KEYS POINT, because it decides what this script must do. That incident's
failure was extra keys, not missing ones. A validator that only checks `required`
accepts it unchanged -- so this script would have been useless without the companion
change to `references/schemas/coverage-disclosure.schema.json`, which is now closed
(`additionalProperties: false`) at the top level AND inside `reconciliation`, the
nested object that a top-level-only closure leaves open.

Reads the disclosure JSON on stdin, validates against the schema, writes to `-o`.
Producer contract: on rejection the diagnostic goes to stdout, the reason to stderr,
`-o` is LEFT UNTOUCHED, exit non-zero.

Usage:
  cat "$STAGING_DIR/disclosure.json" | python3 write_coverage_disclosure.py \
      -o "$REVIEW_DIR/coverage_disclosure.json" --run-id "$RUN_ID" --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, NoReturn

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA = os.path.join(_HERE, "..", "references", "schemas", "coverage-disclosure.schema.json")

# The hand-roll route's own obligations, beyond what the shared schema encodes. SKILL.md
# requires each of these alongside the artifact; a disclosure that omits them is a
# disclosure that discloses nothing.
_MANUAL_METHOD = "manual_outside_pipeline"


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def validate(data: Any, schema: dict[str, Any]) -> list[str]:
    """Validate against the closed schema. Returns a list of human-readable errors.

    Hand-rolled rather than pulling `jsonschema`: no skill script in this repo imports
    it, and the closed schema uses only const/enum/type/required/additionalProperties.
    The extra-keys check is the load-bearing one -- see the module docstring.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"top level must be a JSON object, got {type(data).__name__}"]
    props: dict[str, Any] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in data:
            errors.append(f"missing required key: {key}")
    if schema.get("additionalProperties") is False:
        for key in sorted(set(data) - set(props)):
            errors.append(
                f"unknown key {key!r} — the disclosure form is closed. The 2026-07-05 incident "
                f"hand-authored a richer schema than the template; that is the failure this rejects."
            )
    for key, spec in props.items():
        if key not in data:
            continue
        val = data[key]
        if "const" in spec and val != spec["const"]:
            errors.append(f"{key}: expected {spec['const']!r}, got {val!r}")
        if "enum" in spec and val not in spec["enum"]:
            errors.append(f"{key}: {val!r} is not one of {spec['enum']}")
        want = spec.get("type")
        if want and not _type_ok(val, want):
            errors.append(f"{key}: expected type {want}, got {type(val).__name__}")
        if isinstance(spec.get("properties"), dict) and isinstance(val, dict):
            errors.extend(f"{key}.{e}" for e in validate(val, spec))
        # `items` was declared in the schema and IGNORED here, which made the
        # `uncovered_parts: {items: string}` tightening inert -- a list of objects validated
        # clean. Checked per element so the error names the offending index.
        item_spec = spec.get("items")
        if isinstance(item_spec, dict) and isinstance(val, list):
            want = item_spec.get("type")
            for i, element in enumerate(val):
                if want and not _type_ok(element, want):
                    errors.append(f"{key}[{i}]: expected type {want}, got {type(element).__name__}")
                if isinstance(item_spec.get("properties"), dict) and isinstance(element, dict):
                    errors.extend(f"{key}[{i}].{e}" for e in validate(element, item_spec))
    return errors


def _type_ok(val: Any, want: Any) -> bool:
    """JSON-Schema `type` check, accepting a string or a list of strings.

    `bool` is a subclass of `int` in Python, so a naive isinstance accepts `true`
    for `{"type": "number"}` -- which matters here because `covered` and
    `counsel_review` sit beside `max_divergence_ppm` in the same object.
    """
    names: list[str] = [want] if isinstance(want, str) else [str(n) for n in want]
    table: dict[str, tuple[type, ...]] = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "boolean": (bool,),
        "number": (int, float),
        "null": (type(None),),
    }
    for name in names:
        expected = table.get(name)
        if expected is None:
            return True  # unknown type keyword: do not invent a failure
        if isinstance(val, bool) and name != "boolean":
            continue
        if isinstance(val, expected):
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", help="Destination coverage_disclosure.json")
    ap.add_argument("--run-id", help="Run id stamped into metadata.run_id")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--input", default="-", help="Input JSON file, or '-' for stdin (default)")
    args = ap.parse_args()
    indent = 2 if args.pretty else None

    raw = sys.stdin.read() if args.input == "-" else pathlib.Path(args.input).read_text(encoding="utf-8")
    if not raw.strip():
        _fail_invalid({"validation": {"status": "invalid", "errors": ["empty input"]}}, args.output, indent)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail_invalid(
            {"validation": {"status": "invalid", "errors": [f"input is not valid JSON: {exc}"]}},
            args.output,
            indent,
        )

    schema = json.loads(pathlib.Path(_SCHEMA).read_text(encoding="utf-8"))
    errors = validate(data, schema)

    # Route-specific obligations. This script serves the hand-roll route only; the other
    # two computation_methods have their own producers and must not be redirected here.
    if isinstance(data, dict):
        method = data.get("computation_method")
        if method != _MANUAL_METHOD:
            errors.append(
                f"computation_method must be {_MANUAL_METHOD!r} for the hand-roll route "
                f"(got {method!r}); the covered and extraction-only routes have their own producers"
            )
        if data.get("covered") is not False:
            errors.append("covered must be false — this producer serves the `covered: false` route")
        if not data.get("uncovered_parts"):
            errors.append(
                "uncovered_parts must be a non-empty list — a hand-roll disclosure that names no "
                "uncovered primitive tells the founder nothing about what was not covered"
            )
        if data.get("counsel_review") is not True:
            errors.append("counsel_review must be true — hand-rolled figures always carry the boundary")

    if errors:
        _fail_invalid({"validation": {"status": "invalid", "errors": errors}}, args.output, indent)

    assert isinstance(data, dict)
    if args.run_id:
        meta = data.setdefault("metadata", {})
        if isinstance(meta, dict):
            meta["run_id"] = args.run_id

    payload = json.dumps(data, indent=indent) + "\n"
    if args.output:
        pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.output).write_text(payload, encoding="utf-8")
        print(
            json.dumps({"ok": True, "output_path": os.path.abspath(args.output), "bytes": len(payload)}, indent=indent)
        )
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
