"""Shared helper for producer scripts: validate input, inject metadata, write."""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any

from _schema_validator import validate  # type: ignore[import-not-found]


class ArtifactValidationError(ValueError):
    """Raised when input data fails schema validation."""


def write_artifact(
    *,
    data: dict[str, Any],
    schema: dict[str, Any],
    run_id: str,
    output_path: str,
    pretty: bool = True,
) -> dict[str, Any]:
    """Validate, inject metadata.run_id, write to disk. Return receipt dict."""
    merged: dict[str, Any] = dict(data)
    existing_meta = merged.get("metadata")
    merged_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    merged_meta["run_id"] = run_id
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
    # ATOMIC. `open(..., "w")` truncates first, so an interrupted write leaves a partial
    # file — and for gate_state.json a partial file is an ERASURE: the record holds a
    # founder's decision plus the history that carries it forward, and a reader that finds
    # unparseable JSON has no way to distinguish "never asked" from "asked and truncated".
    # Write beside the target and rename, which is atomic within a directory.
    tmp_path = f"{abs_path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, abs_path)
    finally:
        if os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.remove(tmp_path)

    return {"ok": True, "path": abs_path, "bytes": len(text.encode("utf-8"))}


def load_schema(schema_path: str) -> dict[str, Any]:
    """Load a JSON schema file."""
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]
