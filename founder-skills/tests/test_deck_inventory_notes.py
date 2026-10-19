"""Optional reviewer notes on deck_inventory.json, and the hard caps the producer enforces.

Fixtures use invented text only. Every refusal must leave `-o` untouched, and because these
notes are the reviewer's, not deck text, `deck_text.py` must never copy them into deck_text.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"
INVENTORY_SCRIPT = SCRIPTS / "deck_inventory.py"
DECK_TEXT_SCRIPT = SCRIPTS / "deck_text.py"

_UNSET = object()


def _inventory(observations: Any = _UNSET, printed_label: Any = _UNSET) -> dict[str, Any]:
    slide: dict[str, Any] = {
        "number": 1,
        "headline": "Invented headline",
        "content_summary": "Invented summary",
    }
    if printed_label is not _UNSET:
        slide["printed_label"] = printed_label
    data: dict[str, Any] = {
        "company_name": "Invented Co",
        "review_date": "2026-01-01",
        "input_format": "text",
        "total_slides": 1,
        "ai_company_status": "not_ai",
        "input_quality": "good",
        "slides": [slide],
    }
    if observations is not _UNSET:
        data["observations"] = observations
    return data


def _run_inventory(payload: dict[str, Any], output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INVENTORY_SCRIPT), "--run-id", "RID", "-o", str(output)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_twelve_observations_of_300_chars_and_a_16_char_label_are_written(tmp_path: Path) -> None:
    observations = [f"{index:02d}" + "x" * 298 for index in range(12)]
    label = "0123456789abcdef"
    assert all(len(note) == 300 for note in observations)
    assert len(label) == 16
    out = tmp_path / "deck_inventory.json"

    proc = _run_inventory(_inventory(observations, label), out)

    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["observations"] == observations
    assert written["slides"][0]["printed_label"] == label


def test_thirteen_observations_is_refused_and_leaves_output_untouched(tmp_path: Path) -> None:
    payload = _inventory(["an invented note"] * 13)
    absent = tmp_path / "absent.json"

    proc = _run_inventory(payload, absent)

    assert proc.returncode == 1
    assert "observations:" in proc.stderr
    assert not absent.exists()

    existing = tmp_path / "existing.json"
    sentinel = b"prior good inventory\n"
    existing.write_bytes(sentinel)

    proc = _run_inventory(payload, existing)

    assert proc.returncode == 1
    assert existing.read_bytes() == sentinel


def test_a_301_char_observation_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "deck_inventory.json"

    proc = _run_inventory(_inventory(["x" * 301]), out)

    assert proc.returncode == 1
    assert "observations[" in proc.stderr
    assert not out.exists()


def test_a_17_char_printed_label_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "deck_inventory.json"

    proc = _run_inventory(_inventory(printed_label="x" * 17), out)

    assert proc.returncode == 1
    assert "printed_label" in proc.stderr
    assert not out.exists()


def test_null_and_empty_reviewer_notes_are_dropped(tmp_path: Path) -> None:
    null_out = tmp_path / "null.json"

    proc = _run_inventory(_inventory(None, None), null_out)

    assert proc.returncode == 0, proc.stderr
    written = json.loads(null_out.read_text(encoding="utf-8"))
    assert "observations" not in written
    assert "printed_label" not in written["slides"][0]

    empty_out = tmp_path / "empty.json"

    proc = _run_inventory(_inventory([], _UNSET), empty_out)

    assert proc.returncode == 0, proc.stderr
    written = json.loads(empty_out.read_text(encoding="utf-8"))
    assert "observations" not in written


def test_reviewer_notes_never_reach_deck_text(tmp_path: Path) -> None:
    inventory = tmp_path / "deck_inventory.json"
    payload = _inventory(["INVENTED-NOTE-MARKER saw a chart"], "p.9-LABEL")

    assert _run_inventory(payload, inventory).returncode == 0

    deck = tmp_path / "deck.txt"
    # No marker, so slide 1 falls back to its inventory record: the path where a note could leak.
    deck.write_text("Invented words with no slide marker\n", encoding="utf-8")
    out = tmp_path / "deck_text.md"

    proc = subprocess.run(
        [
            sys.executable,
            str(DECK_TEXT_SCRIPT),
            "--deck",
            str(deck),
            "--inventory",
            str(inventory),
            "--run-id",
            "RID",
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "pages_source: {1: inventory}" in body
    assert "Invented headline" in body
    assert "INVENTED-NOTE-MARKER" not in body
    assert "p.9-LABEL" not in body
