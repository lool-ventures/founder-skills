from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "skills",
        "deck-review",
        "scripts",
    ),
)

from _artifact_writer import ArtifactValidationError, write_artifact  # type: ignore[import-not-found]  # noqa: E402

_MINIMAL_SCHEMA = {
    "type": "object",
    "required": ["metadata", "name"],
    "properties": {
        "metadata": {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}}},
        "name": {"type": "string"},
    },
}


def test_write_artifact_injects_metadata_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "thing.json")
        write_artifact(
            data={"name": "Acme"},
            schema=_MINIMAL_SCHEMA,
            run_id="20260503T120000Z",
            output_path=out,
        )
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "20260503T120000Z"
        assert written["name"] == "Acme"


def test_write_artifact_validates_against_schema() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "thing.json")
        try:
            write_artifact(
                data={"wrong_field": "Acme"},
                schema=_MINIMAL_SCHEMA,
                run_id="r1",
                output_path=out,
            )
            raise AssertionError("expected ArtifactValidationError")
        except ArtifactValidationError as e:
            assert "name" in str(e)


def test_write_artifact_preserves_user_metadata_fields() -> None:
    """If caller already provided metadata fields beyond run_id, keep them."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "thing.json")
        write_artifact(
            data={"name": "Acme", "metadata": {"review_date": "2026-05-03"}},
            schema=_MINIMAL_SCHEMA,
            run_id="r1",
            output_path=out,
        )
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert written["metadata"]["review_date"] == "2026-05-03"


def test_write_artifact_emits_receipt_when_capture_stdout() -> None:
    """The function returns a receipt dict callers can serialize to stdout."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "thing.json")
        receipt = write_artifact(
            data={"name": "Acme"},
            schema=_MINIMAL_SCHEMA,
            run_id="r1",
            output_path=out,
        )
        assert receipt["ok"] is True
        assert receipt["path"] == os.path.abspath(out)
        assert receipt["bytes"] > 0
