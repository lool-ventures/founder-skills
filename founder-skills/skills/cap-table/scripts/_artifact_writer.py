"""Shared helper for producer scripts: validate input, inject metadata, write."""

from __future__ import annotations

import json
import os
from typing import Any

from _cap_table_schema_validator import validate  # type: ignore[import-not-found]


class ArtifactValidationError(ValueError):
    """Raised when input data fails schema validation."""


def write_artifact(
    *,
    data: dict[str, Any],
    schema: dict[str, Any],
    run_id: str,
    output_path: str,
    pretty: bool = True,
    schema_version: str | None = None,
) -> dict[str, Any]:
    """Validate, inject metadata.run_id (+ optional schema_version), write to disk.

    `schema_version`, when provided, is injected into `metadata.schema_version`.
    Producers MUST pass this for v0.5.0+ artifacts (cap_state -> "v0.5.0-cap-state",
    instruments -> "v0.5.0-instruments", inputs -> "v0.5.0-inputs"). The schema
    validator catches a wrong literal via the `const` constraint.
    """
    merged: dict[str, Any] = dict(data)
    existing_meta = merged.get("metadata")
    merged_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    merged_meta["run_id"] = run_id
    if schema_version is not None:
        merged_meta["schema_version"] = schema_version
    merged["metadata"] = merged_meta

    errors = validate(merged, schema)
    if errors:
        raise ArtifactValidationError("; ".join(errors))

    abs_path = os.path.abspath(output_path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if pretty:
        text = json.dumps(merged, indent=2, sort_keys=False) + "\n"
    else:
        text = json.dumps(merged, sort_keys=False) + "\n"
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)

    return {"ok": True, "path": abs_path, "bytes": len(text.encode("utf-8"))}


def load_schema(schema_path: str) -> dict[str, Any]:
    """Load a JSON schema file."""
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]
