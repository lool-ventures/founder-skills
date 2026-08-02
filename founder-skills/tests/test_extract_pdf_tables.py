"""B2 — OCR an image-only PDF into a grid (binary-only: pdftoppm + tesseract).

The risky part — reconstructing a table grid from OCR word boxes — is a pure function
(`tsv_words_to_grid`) testable without any binary. The end-to-end OCR (`ocr_pdf_to_grid`) is integration-
tested only when the tesseract/pdftoppm binaries are present (they ship in the full-parity agent image).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

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
def test_ocr_pdf_to_grid_end_to_end(tmp_path: Path) -> None:
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


@pytest.mark.skipif(
    not (shutil.which("tesseract") and shutil.which("pdftoppm")),
    reason="needs tesseract + pdftoppm (present in the full-parity agent image)",
)
def test_cov_a_synthetic_scanned_cap_table(tmp_path: Path) -> None:
    """COV-A — a synthetic MULTI-HOLDER cap table rasterized to a TRUE image-only PDF, OCR'd end-to-end.

    Closes the coverage gap: B2's table path had only met a tiny 2-col image + a prose note, never a
    realistic multi-holder cap table. Synthetic names only (no real data). Asserts the image-only
    PRECONDITION first (a text-layer PDF would route to pdftotext and silently defeat the fixture)."""
    import sys

    sys.path.insert(0, SCRIPTS)
    import pdf_probe  # type: ignore[import-not-found]
    from PIL import Image, ImageDraw

    rows = [
        ("Holder", "Common", "Preferred"),
        ("Acmecorp", "4000000", "0"),
        ("Cadence VC", "0", "2000000"),
        ("Foobar Ltd", "1500000", "500000"),
    ]
    img = Image.new("RGB", (640, 260), "white")
    d = ImageDraw.Draw(img)
    for r, (a, b, c) in enumerate(rows):
        y = 24 + r * 50
        d.text((24, y), a, fill="black")
        d.text((320, y), b, fill="black")
        d.text((500, y), c, fill="black")
    pdf = tmp_path / "scanned_captable.pdf"
    img.save(str(pdf), "PDF")

    # PRECONDITION: it must be image-only, else the test isn't exercising OCR.
    probe = pdf_probe.probe_pdf(str(pdf))
    assert probe["image_only"] is True, f"fixture not image-only (would defeat OCR): {probe}"

    grid = ept.ocr_pdf_to_grid(str(pdf))
    flat = " ".join(c for sheet in grid.values() for row in sheet for c in row)
    # Holders recovered (OCR is lossy — assert the distinctive tokens survive)
    assert "Acmecorp" in flat
    assert "Cadence" in flat and "Foobar" in flat
    # at least one share figure recovered
    assert any(n in flat.replace(",", "").replace(" ", "") for n in ("4000000", "2000000", "1500000"))
