"""B2 — OCR an image-only PDF into a grid (binary-only: pdftoppm + tesseract).

The risky part — reconstructing a table grid from OCR word boxes — is a pure function
(`tsv_words_to_grid`) testable without any binary. The end-to-end OCR (`ocr_pdf_to_grid`) is integration-
tested only when the tesseract/pdftoppm binaries are present (they ship in the full-parity agent image).
"""

from __future__ import annotations

import os
import shutil
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import extract_pdf_tables as ept  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402


def _w(text: str, left: int, top: int, width: int = 60, height: int = 20) -> dict:
    return {"text": text, "left": left, "top": top, "width": width, "height": height}


def test_grid_from_words_two_columns_three_rows() -> None:
    # Coords mirror the real tesseract smoke: col0 ~left 20, col1 ~left 300; rows ~40px apart.
    words = [
        _w("Holder", 21, 20),
        _w("Shares", 301, 20),
        _w("Alice", 20, 60),
        _w("5000000", 300, 60),
        _w("Bob", 17, 100),
        _w("4000000", 301, 100),
    ]
    grid = ept.tsv_words_to_grid(words)
    assert grid == [["Holder", "Shares"], ["Alice", "5000000"], ["Bob", "4000000"]]


def test_multi_word_cell_joined() -> None:
    words = [_w("Acme", 20, 20), _w("Ventures", 70, 20), _w("500000", 300, 20)]
    grid = ept.tsv_words_to_grid(words)
    assert grid == [["Acme Ventures", "500000"]]


def test_empty_words_empty_grid() -> None:
    assert ept.tsv_words_to_grid([]) == []


def test_grid_payload_shape_matches_freeform_grid() -> None:
    # The emitted payload must match the --mode=grid shape the freeform pipeline already consumes.
    payload = ept.grid_payload({"page_1": [["Holder", "Shares"], ["Alice", "5000000"]]})
    assert payload["ok"] is True and payload["mode"] == "grid"
    sheet = payload["sheets"]["page_1"]
    assert sheet["rows"] == [["Holder", "Shares"], ["Alice", "5000000"]]
    assert "merged_ranges" in sheet


@pytest.mark.skipif(
    not (shutil.which("tesseract") and shutil.which("pdftoppm")),
    reason="needs tesseract + pdftoppm binaries (present in the full-parity agent image)",
)
def test_ocr_pdf_to_grid_end_to_end(tmp_path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (520, 180), "white")
    d = ImageDraw.Draw(img)
    for r, (a, b) in enumerate([("Holder", "Shares"), ("Alice", "5000000"), ("Bob", "4000000")]):
        d.text((20, 20 + r * 45), a, fill="black")
        d.text((300, 20 + r * 45), b, fill="black")
    pdf = tmp_path / "imgonly.pdf"
    img.save(str(pdf), "PDF")
    grid = ept.ocr_pdf_to_grid(str(pdf))
    flat = " ".join(c for sheet in grid.values() for row in sheet for c in row)
    assert "Alice" in flat and "Bob" in flat
    assert "5000000" in flat.replace("'", "").replace(" ", "") or "5000000" in flat
