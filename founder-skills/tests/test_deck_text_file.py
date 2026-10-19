"""`_deck_text_file.py`: the front matter, the body hash and the run id, without reading a slide.

The helper only splits a deck-text file on its first two `---` fences. A markdown body may carry
`---` lines of its own, so the tests pin that only the first two fences count, and that a file with
no valid front matter is hashed whole rather than treated as empty.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"

sys.path.insert(0, str(SCRIPTS))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402


def test_split_reads_the_front_matter_and_leaves_the_body_whole() -> None:
    text = "---\nrun_id: RID-47\nsource: extracted\n---\nSLIDE 1: TITLE\nInvented text\n"
    front, body = _deck_text_file.split(text)
    assert front == {"run_id": "RID-47", "source": "extracted"}
    assert body == "SLIDE 1: TITLE\nInvented text\n"


def test_a_fence_inside_the_body_does_not_end_the_front_matter() -> None:
    text = "---\nrun_id: RID-47\n---\nSLIDE 1\nAbove the rule\n---\nBelow the rule\n"
    front, body = _deck_text_file.split(text)
    assert front == {"run_id": "RID-47"}
    assert body == "SLIDE 1\nAbove the rule\n---\nBelow the rule\n"


def test_no_opening_fence_means_no_front_matter_and_the_whole_text_is_the_body() -> None:
    text = "SLIDE 1: TITLE\nA line\n---\nAnother line\n"
    assert _deck_text_file.split(text) == (None, text)
    assert _deck_text_file.front_matter(text) is None


def test_no_second_fence_means_no_front_matter() -> None:
    text = "---\nrun_id: RID-47\nSLIDE 1: TITLE\n"
    assert _deck_text_file.split(text) == (None, text)


def test_body_sha256_hashes_the_bytes_after_the_second_fence() -> None:
    data = b"---\nrun_id: RID-47\n---\nSLIDE 1: TITLE\nInvented text\n"
    expected = hashlib.sha256(b"\nSLIDE 1: TITLE\nInvented text\n").hexdigest()
    assert _deck_text_file.body_sha256(data) == expected


def test_body_sha256_with_no_front_matter_hashes_every_byte() -> None:
    data = b"SLIDE 1: TITLE\nInvented text\n"
    assert _deck_text_file.body_sha256(data) == hashlib.sha256(data).hexdigest()


def test_body_sha256_ignores_a_fence_inside_the_body() -> None:
    data = b"---\nrun_id: RID-47\n---\nSLIDE 1\n---\nTail\n"
    expected = hashlib.sha256(b"\nSLIDE 1\n---\nTail\n").hexdigest()
    assert _deck_text_file.body_sha256(data) == expected


def test_run_id_of_reads_the_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "deck_text.md"
    path.write_text("---\nrun_id: RID-47\nsource: pasted\n---\nSLIDE 1\n", encoding="utf-8")
    assert _deck_text_file.run_id_of(path) == "RID-47"


def test_run_id_of_is_none_without_front_matter_or_a_file(tmp_path: Path) -> None:
    path = tmp_path / "deck_text.md"
    path.write_text("SLIDE 1\n", encoding="utf-8")
    assert _deck_text_file.run_id_of(path) is None
    assert _deck_text_file.run_id_of(tmp_path / "absent.md") is None
