"""The body stamp: producers hash a deck text's body and refuse another run's file.

The front matter's `run_id` decides whose file it is, while the hash covers only the body, so a
re-stamped or re-written front matter (a new source line, a new deck hash) does not stale a
transcript taken against the same slides. Every fixture is invented.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"

sys.path.insert(0, str(SCRIPTS))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402
from slide_review_inputs import slide_review_inputs  # noqa: E402

DECK_TEXT = SCRIPTS / "deck_text.py"
SLIDE_REVIEWS = SCRIPTS / "slide_reviews.py"
SETUP_RUN = SCRIPTS / "setup_run.py"

RUN_A = "RID-A"
RUN_B = "RID-B"


def _write_deck_text(
    path: Path, run_id: str = RUN_A, body: str = "## Slide 1\n\nInvented text.\n", source: str = "extracted"
) -> Path:
    path.write_text(f"---\nrun_id: {run_id}\nsource: {source}\n---\n{body}", encoding="utf-8")
    return path


def _run(script: Path, *args: object, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *[str(arg) for arg in args]],
        input=stdin,
        capture_output=True,
        text=True,
    )


# --- stamp -----------------------------------------------------------------------------------


def test_stamp_returns_the_same_sha_as_body_sha256(tmp_path: Path) -> None:
    path = _write_deck_text(tmp_path / "deck_text.md")

    sha, refusal = _deck_text_file.stamp(path, RUN_A)

    assert refusal is None
    assert sha == _deck_text_file.body_sha256(path.read_bytes())


def test_stamp_matches_deck_texts_receipt_for_a_file_it_wrote(tmp_path: Path) -> None:
    deck = tmp_path / "deck.md"
    deck.write_text("## Slide 1\nInvented pasted text\n", encoding="utf-8")
    inventory = tmp_path / "deck_inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "number": 1,
                        "headline": "Invented headline",
                        "content_summary": "Invented summary",
                        "visuals": "Invented visual",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "deck_text.md"

    proc = _run(DECK_TEXT, "--deck", deck, "--inventory", inventory, "--run-id", RUN_A, "--staged", "-o", out)

    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    sha, refusal = _deck_text_file.stamp(out, RUN_A)
    assert refusal is None
    assert sha == receipt["deck_text_sha256"]


def test_a_fence_inside_the_body_stamps_and_the_front_matter_does_not_move_the_sha(tmp_path: Path) -> None:
    path = tmp_path / "deck_text.md"
    body = "## Slide 1\n\nAbove the rule\n\n---\n\nBelow the rule\n"
    _write_deck_text(path, body=body)
    first, refusal = _deck_text_file.stamp(path, RUN_A)
    assert refusal is None
    assert first == _deck_text_file.body_sha256(path.read_bytes())

    _write_deck_text(path, body=body, source="pasted")
    restamped, refusal = _deck_text_file.stamp(path, RUN_A)
    assert refusal is None
    assert restamped == first

    _write_deck_text(path, body=body.replace("Below", "Below!"))
    changed, refusal = _deck_text_file.stamp(path, RUN_A)
    assert refusal is None
    assert changed != first


def test_a_missing_file_is_unreadable(tmp_path: Path) -> None:
    sha, refusal = _deck_text_file.stamp(tmp_path / "absent.md", RUN_A)

    assert sha is None
    assert refusal is not None and refusal["code"] == "DECK_TEXT_UNREADABLE"


def test_a_file_with_no_front_matter_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "deck_text.md"
    path.write_text("## Slide 1\n\nInvented text.\n", encoding="utf-8")

    sha, refusal = _deck_text_file.stamp(path, RUN_A)

    assert sha is None
    assert refusal is not None and refusal["code"] == "DECK_TEXT_INVALID"


def test_another_runs_id_names_both_runs(tmp_path: Path) -> None:
    path = _write_deck_text(tmp_path / "deck_text.md", run_id=RUN_A)

    sha, refusal = _deck_text_file.stamp(path, RUN_B)

    assert sha is None
    assert refusal is not None
    assert refusal["code"] == "DECK_TEXT_OTHER_RUN"
    assert RUN_A in refusal["message"] and RUN_B in refusal["message"]


def test_a_missing_run_id_is_another_runs_file(tmp_path: Path) -> None:
    path = tmp_path / "deck_text.md"
    path.write_text("---\nsource: extracted\n---\n## Slide 1\n", encoding="utf-8")

    sha, refusal = _deck_text_file.stamp(path, RUN_A)

    assert sha is None
    assert refusal is not None and refusal["code"] == "DECK_TEXT_OTHER_RUN"


# --- slide_reviews.py ------------------------------------------------------------------------


_RECONCILIATION: dict[str, Any] = {
    "metadata": {"run_id": RUN_B},
    "status": "checked",
    "figures_total": 0,
    "figures_verified": 0,
    "relations": [],
    "validation": {"status": "valid", "errors": [], "warnings": []},
}

_VALID: dict[str, Any] = {
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["No ICP specificity"],
            "recommendations": ["Add ICP"],
            "best_practice_refs": ["Sequoia: declarative sentence"],
        }
    ],
    "missing_slides": [{"expected_type": "why_now", "importance": "important", "recommendation": "Add why-now"}],
    "overall_narrative_assessment": "Strong opening, weak middle.",
}


def _reconciliation(tmp_path: Path, run_id: str) -> Path:
    body = json.loads(json.dumps(_RECONCILIATION))
    body["metadata"]["run_id"] = run_id
    path = tmp_path / "reconciliation.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _slide_reviews(
    tmp_path: Path, run_id: str, out: Path, *extra: object, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    argv: list[object] = [
        "--run-id",
        run_id,
        "-o",
        out,
        "--reconciliation",
        _reconciliation(tmp_path, run_id),
        *slide_review_inputs(tmp_path, run_id),  # a later --deck-text in `extra` replaces this one
        *extra,
    ]
    return _run(SLIDE_REVIEWS, *argv, stdin=stdin)


def _slide_reviews_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dr_slide_reviews_stamp", SLIDE_REVIEWS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slide_reviews_stamps_the_body_hash_and_keeps_the_read_token(tmp_path: Path) -> None:
    deck_text = _write_deck_text(tmp_path / "deck_text.md", run_id=RUN_B)
    other = _write_deck_text(tmp_path / "other_deck_text.md", run_id=RUN_B, body="## Slide 1\n\nOther words\n")
    payload = dict(_VALID, metadata={"deck_text_sha256": "0" * 64})

    first = _slide_reviews(tmp_path, RUN_B, tmp_path / "a.json", "--deck-text", other, stdin=json.dumps(payload))
    stamped = _slide_reviews(
        tmp_path, RUN_B, tmp_path / "stamped.json", "--deck-text", deck_text, stdin=json.dumps(payload)
    )

    assert first.returncode == 0, first.stderr
    assert stamped.returncode == 0, stamped.stderr
    first_written = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    stamped_written = json.loads((tmp_path / "stamped.json").read_text(encoding="utf-8"))
    # Each carries its own deck text's body hash, never the hand-off's; the read token ignores the deck text.
    assert first_written["metadata"]["deck_text_sha256"] == _deck_text_file.body_sha256(other.read_bytes())
    assert stamped_written["metadata"]["deck_text_sha256"] == _deck_text_file.body_sha256(deck_text.read_bytes())
    assert stamped_written["metadata"]["read_token"] == first_written["metadata"]["read_token"]


def test_read_token_hashes_the_body_without_metadata() -> None:
    module = _slide_reviews_module()
    with_metadata = dict(_VALID, metadata={"read_token": "0" * 12, "deck_text_sha256": "1" * 64})
    assert module.read_token(RUN_B, with_metadata) == module.read_token(RUN_B, _VALID)


def test_slide_reviews_refuses_another_runs_deck_text_before_reading_stdin(tmp_path: Path) -> None:
    deck_text = _write_deck_text(tmp_path / "deck_text.md", run_id=RUN_A)
    out = tmp_path / "slide_reviews.json"
    sentinel = b'{"sentinel": true}\n'
    out.write_bytes(sentinel)

    proc = _slide_reviews(tmp_path, RUN_B, out, "--deck-text", deck_text, stdin="{ not valid json")

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    diagnostic = json.loads(proc.stdout)
    assert diagnostic["status"] == "rejected"
    assert diagnostic["code"] == "DECK_TEXT_OTHER_RUN"
    assert RUN_A in diagnostic["message"] and RUN_B in diagnostic["message"]
    assert "nothing was written" in proc.stderr
    assert out.read_bytes() == sentinel


# --- setup_run.py ----------------------------------------------------------------------------


def _setup(tmp_path: Path, run_id: str) -> dict[str, Any]:
    root = tmp_path / "artifacts"
    proc = _run(
        SETUP_RUN,
        "--artifacts-root",
        root,
        "--slug",
        "courier-co",
        "--run-id",
        run_id,
        "--clean",
    )
    assert proc.returncode == 0, proc.stderr
    parsed: dict[str, Any] = json.loads(proc.stdout)
    return parsed


def test_a_fresh_clean_keeps_this_runs_deck_text(tmp_path: Path) -> None:
    review_dir = tmp_path / "artifacts" / "deck-review-courier-co"
    os.makedirs(review_dir)
    deck_text = _write_deck_text(review_dir / "deck_text.md", run_id=RUN_A)

    out = _setup(tmp_path, RUN_A)

    assert deck_text.is_file()
    assert out["reuse_checkpoints"] is True


def test_a_fresh_clean_removes_another_runs_deck_text(tmp_path: Path) -> None:
    review_dir = tmp_path / "artifacts" / "deck-review-courier-co"
    os.makedirs(review_dir)
    deck_text = _write_deck_text(review_dir / "deck_text.md", run_id=RUN_A)

    out = _setup(tmp_path, RUN_B)

    assert not deck_text.exists()
    assert out["reuse_checkpoints"] is False
