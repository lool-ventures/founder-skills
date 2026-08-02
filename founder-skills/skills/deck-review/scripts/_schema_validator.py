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
        # type may be a string (e.g. "boolean") or a list of strings
        # (e.g. ["boolean", "null"]) per JSON Schema draft-07+.
        type_names: list[str] = expected_type if isinstance(expected_type, list) else [expected_type]
        unknown = [t for t in type_names if t not in _TYPE_CHECKS]
        if unknown:
            errors.append(f"{path or '<root>'}: schema has unknown type(s) {unknown!r}")
            return errors
        # bool is a subclass of int — disambiguate so True/False don't satisfy
        # "integer" or "number" fields unless "boolean" is also an allowed type.
        numeric_types = {"integer", "number"}
        if any(t in numeric_types for t in type_names) and "boolean" not in type_names and isinstance(data, bool):
            errors.append(f"{path or '<root>'}: expected {type_names}, got boolean")
            return errors
        allowed_py_types = tuple(_TYPE_CHECKS[t] for t in type_names)
        if not isinstance(data, allowed_py_types):
            actual = type(data).__name__
            errors.append(f"{path or '<root>'}: expected {type_names}, got {actual}")
            return errors
        # For single-type schemas keep backward-compatible behaviour: use the
        # original single string for subtype dispatch below.
        expected_type = type_names[0] if len(type_names) == 1 else None

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
