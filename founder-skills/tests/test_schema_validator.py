# founder-skills/tests/test_schema_validator.py
from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "skills",
        "deck-review",
        "scripts",
    ),
)

from _schema_validator import validate  # type: ignore[import-not-found]  # noqa: E402


def test_validate_passes_minimal_object() -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    errors = validate({"name": "Acme"}, schema)
    assert errors == []


def test_validate_reports_missing_required_field() -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    errors = validate({}, schema)
    assert len(errors) == 1
    assert "name" in errors[0]
    assert "required" in errors[0].lower()


def test_validate_reports_wrong_type() -> None:
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    errors = validate({"count": "twelve"}, schema)
    assert any("count" in e and "integer" in e for e in errors)


def test_validate_enforces_enum() -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["pass", "fail"]}},
    }
    errors = validate({"status": "maybe"}, schema)
    assert any("enum" in e.lower() and "status" in e for e in errors)


def test_validate_recurses_into_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "slides": {
                "type": "array",
                "items": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer"}}},
            }
        },
    }
    errors = validate({"slides": [{"number": 1}, {"number": "two"}, {}]}, schema)
    assert len(errors) == 2  # one for "two" (wrong type), one for missing "number"


def test_validate_path_in_error_message() -> None:
    schema = {
        "type": "object",
        "properties": {"slides": {"type": "array", "items": {"type": "object", "required": ["number"]}}},
    }
    errors = validate({"slides": [{}, {}]}, schema)
    # Error messages should reference the path so the agent knows where to fix
    assert any("slides[0]" in e or "slides.0" in e for e in errors)


def test_validate_rejects_bool_as_integer() -> None:
    """Python's bool is an int subclass; the validator must reject it for type=integer."""
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    errors = validate({"count": True}, schema)
    assert any("count" in e and "integer" in e and "boolean" in e for e in errors)


def test_validate_reports_unknown_schema_type() -> None:
    """A typo'd type (e.g., 'Object' capitalized) should produce a clear error."""
    schema = {"type": "Object"}
    errors = validate({}, schema)
    assert any("unknown type" in e for e in errors)
