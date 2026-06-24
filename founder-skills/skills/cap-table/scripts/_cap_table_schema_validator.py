"""Minimal JSON-Schema-subset validator (stdlib only).

Supports: type (single value OR list of values, e.g. ["string", "null"]),
required, properties, items, enum. Returns a list of human-readable error
strings; empty list means valid. Error messages include a dotted/indexed
path so agents/scripts can pinpoint the offending field.

Unsupported keywords are silently ignored: $ref, oneOf, anyOf, allOf,
additionalProperties, patternProperties, pattern, minLength/maxLength,
minimum/maximum, format. Schema authors must not rely on them.

DEFERRED (Phase 3): enforcing `additionalProperties: false` end-to-end is the
generic catch-all for mis-keyed input fields (today an unknown key passes
silently and is ignored by the consumer). Prereqs before flipping it on:
(1) this validator gains real `additionalProperties` support; (2) the
producer-wide intentional-extras inventory is complete — see
`cap_state._INTENTIONAL_NON_SCHEMA_KEYS` (currently cap_state-only); (3) every
inventory key becomes a declared schema property or a documented exception.
Otherwise reject-mode would fail VALID inputs. Phase 1 instead handles the one
observed mis-key (anti_dilution) via a targeted recovery in cap_state.py.

Type-mismatch errors short-circuit further checks for that subtree to
avoid cascading errors on the wrong shape.

Why a hand-rolled validator: scripts in this repo are invoked via bare
python3, not uv run, so PEP 723 inline deps aren't honored at runtime.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from typing import Any

_TypeSpec = type | tuple[type, ...]


def _did_you_mean(missing: str, present_keys: Iterable[str]) -> str | None:
    """If a present sibling key resembles a missing REQUIRED field (a wrong-key typo the model writes,
    e.g. `authorized_shares` for `authorized`), return it so the rejection can hint the founder rather
    than dead-end. Conservative: a prefix relationship (after stripping a common suffix) or high string
    similarity (SequenceMatcher ratio ≥ 0.7) only — an unrelated sibling returns None."""
    best: str | None = None
    best_ratio = 0.0
    for k in present_keys:
        if k == missing:
            continue
        stripped = k
        for suf in ("_shares", "_count", "_amount", "_total", "_value"):
            if stripped.endswith(suf):
                stripped = stripped[: -len(suf)]
                break
        if stripped == missing or k.startswith(missing) or missing.startswith(k):
            return k
        ratio = difflib.SequenceMatcher(None, k, missing).ratio()
        if ratio > best_ratio:
            best, best_ratio = k, ratio
    return best if best_ratio >= 0.7 else None


_TYPE_CHECKS: dict[str, _TypeSpec] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _check_type(data: Any, type_spec: str | list[str], path: str) -> list[str]:
    """Check `data` against a single type or a union (list) of types."""
    if isinstance(type_spec, list):
        # JSON-Schema union: pass if any type matches.
        for t in type_spec:
            if not _check_type(data, t, path):  # empty errors == valid
                return []
        # None matched
        actual = type(data).__name__
        return [f"{path or '<root>'}: expected one of {type_spec}, got {actual}"]

    py_type = _TYPE_CHECKS.get(type_spec)
    if py_type is None:
        return [f"{path or '<root>'}: schema has unknown type '{type_spec}'"]
    # bool is a subclass of int in Python — disambiguate
    if type_spec == "integer" and isinstance(data, bool):
        return [f"{path or '<root>'}: expected integer, got boolean"]
    if type_spec == "number" and isinstance(data, bool):
        return [f"{path or '<root>'}: expected number, got boolean"]
    if not isinstance(data, py_type):
        actual = type(data).__name__
        return [f"{path or '<root>'}: expected {type_spec}, got {actual}"]
    return []


def validate(data: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    """Validate `data` against `schema`. Returns list of error strings."""
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type:
        type_errors = _check_type(data, expected_type, path)
        if type_errors:
            errors.extend(type_errors)
            return errors

    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path or '<root>'}: value {data!r} not in enum {schema['enum']}")

    # For union types, only recurse on the matching shape (best-effort).
    effective_type = expected_type
    if isinstance(effective_type, list):
        if isinstance(data, dict) and "object" in effective_type:
            effective_type = "object"
        elif isinstance(data, list) and "array" in effective_type:
            effective_type = "array"
        else:
            effective_type = None

    if effective_type == "object" and isinstance(data, dict):
        for required_key in schema.get("required", []):
            if required_key not in data:
                msg = f"{path or '<root>'}: required field '{required_key}' missing"
                hint = _did_you_mean(required_key, data.keys())
                if hint:
                    msg += f" — did you write '{hint}'?"
                errors.append(msg)
        for key, sub_schema in schema.get("properties", {}).items():
            if key in data:
                sub_path = f"{path}.{key}" if path else key
                errors.extend(validate(data[key], sub_schema, sub_path))

    if effective_type == "array" and isinstance(data, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                sub_path = f"{path}[{i}]" if path else f"[{i}]"
                errors.extend(validate(item, item_schema, sub_path))

    return errors
