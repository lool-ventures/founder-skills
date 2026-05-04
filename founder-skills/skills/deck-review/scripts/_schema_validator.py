"""Minimal JSON-Schema-subset validator (stdlib only).

Supports: type (object|array|string|integer|number|boolean|null), required,
properties, items, enum. Returns a list of human-readable error strings;
empty list means valid. Error messages include a dotted/indexed path so
agents/scripts can pinpoint the offending field.

Unsupported keywords are silently ignored: $ref, oneOf, anyOf, allOf,
additionalProperties, patternProperties, pattern, minLength/maxLength,
minimum/maximum, format. Schema authors must not rely on them.

Type-mismatch errors short-circuit further checks for that subtree to
avoid cascading errors on the wrong shape.

Why a hand-rolled validator: scripts in this repo are invoked via bare
python3, not uv run, so PEP 723 inline deps aren't honored at runtime.
"""

from __future__ import annotations

from typing import Any

_TypeSpec = type | tuple[type, ...]

_TYPE_CHECKS: dict[str, _TypeSpec] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate(data: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    """Validate `data` against `schema`. Returns list of error strings."""
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type:
        py_type = _TYPE_CHECKS.get(expected_type)
        if py_type is None:
            errors.append(f"{path or '<root>'}: schema has unknown type '{expected_type}'")
            return errors
        # bool is a subclass of int in Python — disambiguate
        if expected_type == "integer" and isinstance(data, bool):
            errors.append(f"{path or '<root>'}: expected integer, got boolean")
            return errors
        if not isinstance(data, py_type):
            actual = type(data).__name__
            errors.append(f"{path or '<root>'}: expected {expected_type}, got {actual}")
            return errors

    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path or '<root>'}: value {data!r} not in enum {schema['enum']}")

    if expected_type == "object" and isinstance(data, dict):
        for required_key in schema.get("required", []):
            if required_key not in data:
                errors.append(f"{path or '<root>'}: required field '{required_key}' missing")
        for key, sub_schema in schema.get("properties", {}).items():
            if key in data:
                sub_path = f"{path}.{key}" if path else key
                errors.extend(validate(data[key], sub_schema, sub_path))

    if expected_type == "array" and isinstance(data, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                sub_path = f"{path}[{i}]" if path else f"[{i}]"
                errors.extend(validate(item, item_schema, sub_path))

    return errors
