#!/usr/bin/env python3
"""`second_read.py` stages the second read's hand-off as the canonical `second_read.json`.

Fixtures are invented: the transcript carries $6.83M rather than a round figure, so a test that
accidentally matched a different number would still be distinguishable by eye. The last test
runs the real `reconcile.py` over the written file, because the whole point of the producer is
that the artifact it writes is the one the numeric chain consumes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"
SCRIPT = SCRIPTS / "second_read.py"

_TESTS_DIR = str(TESTS)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

_SCRIPTS_DIR = str(SCRIPTS)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402

_TRANSCRIPT = "Slide 6: gross volume of $6.83M in 2024. Slide 7: an invented take rate of 5.37%."


def _run(*args: object, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(arg) for arg in args]],
        input=stdin,
        capture_output=True,
        text=True,
    )


def _handoff(**over: object) -> str:
    base: dict[str, object] = {"transcript": _TRANSCRIPT, "slides_transcribed": [6, 7]}
    base.update(over)
    return json.dumps(base)


def test_a_valid_handoff_is_written_with_the_run_id_stamped_and_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "second_read.json"

    proc = _run(
        "--run-id",
        "20261019T101500Z-3f3f3f",
        "-o",
        out,
        stdin=_handoff(metadata={"run_id": "carried-from-the-handoff", "note": "kept"}),
    )

    assert proc.returncode == 0, proc.stderr
    text = out.read_text(encoding="utf-8")
    assert text.startswith("{\n  ")
    assert text.endswith("\n")
    written = json.loads(text)
    assert written["metadata"]["run_id"] == "20261019T101500Z-3f3f3f"
    assert written["metadata"]["note"] == "kept"  # unknown keys survive
    assert written["transcript"] == _TRANSCRIPT
    assert written["slides_transcribed"] == [6, 7]
    assert json.loads(proc.stdout) == {
        "ok": True,
        "output_path": str(out),
        "slides_transcribed": 2,
        "deck_text_sha256": None,
    }


def test_deck_text_sha256_hashes_the_files_body(tmp_path: Path) -> None:
    deck_text = tmp_path / "deck_text.md"
    deck_text.write_bytes(
        b"---\nrun_id: RID-A\nsource: extracted\n---\n## Slide 6\n\nGross volume of $6.83M in 2024.\n"
    )
    out = tmp_path / "second_read.json"

    proc = _run("--run-id", "RID-A", "-o", out, "--deck-text", deck_text, stdin=_handoff())

    assert proc.returncode == 0, proc.stderr
    expected = _deck_text_file.body_sha256(deck_text.read_bytes())
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["metadata"]["deck_text_sha256"] == expected
    receipt = json.loads(proc.stdout)
    assert receipt["deck_text_sha256"] == expected


def test_another_runs_deck_text_is_refused_and_leaves_o_untouched(tmp_path: Path) -> None:
    deck_text = tmp_path / "deck_text.md"
    deck_text.write_text("---\nrun_id: RID-A\n---\n## Slide 6\n\nInvented text.\n", encoding="utf-8")
    out = tmp_path / "second_read.json"
    sentinel = b'{"sentinel": true}\n'
    out.write_bytes(sentinel)

    proc = _run("--run-id", "RID-B", "-o", out, "--deck-text", deck_text, stdin=_handoff())

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    diagnostic = json.loads(proc.stdout)
    assert diagnostic["status"] == "rejected"
    assert diagnostic["code"] == "DECK_TEXT_OTHER_RUN"
    assert "RID-A" in diagnostic["message"] and "RID-B" in diagnostic["message"]
    assert proc.stderr.strip()
    assert out.read_bytes() == sentinel


def test_without_deck_text_no_sha_key_is_written(tmp_path: Path) -> None:
    out = tmp_path / "second_read.json"

    assert _run("--run-id", "R", "-o", out, stdin=_handoff()).returncode == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert "deck_text_sha256" not in written["metadata"]


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        "[]",
        '{"slides_transcribed": [6]}',
        '{"transcript": "   ", "slides_transcribed": [6]}',
        '{"transcript": 5, "slides_transcribed": [6]}',
        '{"transcript": "a reading", "slides_transcribed": 6}',
        '{"transcript": "a reading", "slides_transcribed": ["6"]}',
        '{"transcript": "a reading", "slides_transcribed": [true]}',
        '{"transcript": "a reading", "slides_transcribed": [0]}',
        '{"transcript": "a reading", "slides_transcribed": [-3]}',
    ],
)
def test_each_invalid_shape_is_refused_and_leaves_o_byte_identical(payload: str, tmp_path: Path) -> None:
    out = tmp_path / "second_read.json"
    sentinel = b'{"sentinel": true}\n'
    out.write_bytes(sentinel)

    proc = _run("--run-id", "R", "-o", out, stdin=payload)

    assert proc.returncode == 1, (payload, proc.stdout, proc.stderr)
    diagnostic = json.loads(proc.stdout)
    assert diagnostic["status"] == "rejected"
    assert diagnostic["code"] == "SECOND_READ_INVALID"
    assert diagnostic["message"]
    assert proc.stderr.strip()
    assert out.read_bytes() == sentinel


def test_an_unreadable_deck_text_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "second_read.json"
    sentinel = b'{"sentinel": true}\n'
    out.write_bytes(sentinel)

    proc = _run("--run-id", "R", "-o", out, "--deck-text", tmp_path / "absent.md", stdin=_handoff())

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    diagnostic = json.loads(proc.stdout)
    assert diagnostic["status"] == "rejected"
    assert diagnostic["code"] == "DECK_TEXT_UNREADABLE"
    assert diagnostic["message"]
    assert proc.stderr.strip()
    assert out.read_bytes() == sentinel


def test_reconcile_accepts_the_written_file(tmp_path: Path) -> None:
    import test_reconcile_producer as trp

    out = tmp_path / "second_read.json"
    handoff = json.dumps({"transcript": trp._TRANSCRIPT, "slides_transcribed": [6]})
    assert _run("--run-id", "R", "-o", out, stdin=handoff).returncode == 0

    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(trp._LEDGER), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "reconcile.py"),
            "--run-id",
            "R",
            "--ledger",
            str(ledger),
            "--second-read",
            str(out),
        ],
        input=json.dumps({"relations": []}),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_a_hand_off_deck_text_stamp_is_dropped_without_the_flag(tmp_path: Path) -> None:
    """A deck_text_sha256 the hand-off carried is never kept when no deck text was hashed."""
    out = tmp_path / "second_read.json"
    payload = {"slides_transcribed": [2], "transcript": "Slide 2: invented", "metadata": {"deck_text_sha256": "0" * 64}}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "RID", "-o", str(out)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "deck_text_sha256" not in json.loads(out.read_text())["metadata"]
