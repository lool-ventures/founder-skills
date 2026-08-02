from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
    "deck_inventory.py",
)


def _run(args: list[str], stdin_data: str) -> tuple[int, str, str]:
    res = subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


_VALID_INPUT = {
    "company_name": "Acme",
    "review_date": "2026-05-03",
    "input_format": "pdf",
    "total_slides": 1,
    "ai_company_status": "not_ai",
    "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
}


def test_deck_inventory_writes_validated_artifact() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck_inventory.json")
        rc, stdout, stderr = _run(
            ["--run-id", "r1", "-o", out, "--pretty"],
            json.dumps(_VALID_INPUT),
        )
        assert rc == 0, stderr
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert written["company_name"] == "Acme"
        assert written["total_slides"] == 1
        # stdout receipt
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        assert receipt["path"] == os.path.abspath(out)


def test_deck_inventory_rejects_missing_required_field() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck_inventory.json")
        bad = {**_VALID_INPUT}
        del bad["company_name"]
        rc, _, stderr = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "company_name" in stderr
        assert not os.path.exists(out)


def test_deck_inventory_rejects_wrong_enum_value() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck_inventory.json")
        bad = {**_VALID_INPUT, "input_format": "powerpoint"}
        rc, _, stderr = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "input_format" in stderr or "enum" in stderr.lower()


def test_deck_inventory_rejects_wrong_slide_field_type() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck_inventory.json")
        bad = {
            **_VALID_INPUT,
            "slides": [{"number": "one", "headline": "h", "content_summary": "s"}],
        }
        rc, _, stderr = _run(["--run-id", "r1", "-o", out], json.dumps(bad))
        assert rc != 0
        assert "slides" in stderr and "integer" in stderr
