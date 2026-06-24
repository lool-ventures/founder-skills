#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""B2 — OCR an image-only PDF into a cell grid (binary-only).

Image-only cap-table PDFs (no text layer) are read today by raw model vision, which under-extracts dense
tables silently (the Siteaware P-1 failure). This producer rasterizes the PDF (`pdftoppm`) and OCRs each
page with table structure (`tesseract … tsv`, which gives per-word bounding boxes), then reconstructs a
cell grid by clustering words into rows (by y) and columns (by x). It emits the SAME `--mode=grid` JSON the
Lane-3 freeform pipeline already consumes — so an OCR'd image PDF flows into the (F1-hardened)
SPREADSHEET_STRUCTURE_DETECTION + freeform_mapper machinery instead of being eyeballed.

Binary-only (subprocess `pdftoppm` + `tesseract`) — NO Python OCR deps — so it runs in the full-parity
agent image (`cowork-agent-full:2`) as-is (both binaries ship there). OCR is lossy; the grid is still
strictly better than raw vision because it gives the structure-detection sub-agent addressable cell text.

The grid reconstruction (`tsv_words_to_grid`) is pure + unit-tested; the binary OCR (`ocr_pdf_to_grid`) is
integration-tested only when the binaries are present.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from typing import Any


def _cluster_1d(values: list[int], gap: float) -> list[float]:
    """Cluster sorted 1-D positions into bins; return each bin's mean. A new bin starts when the jump from
    the previous value exceeds `gap`."""
    if not values:
        return []
    vals = sorted(values)
    bins: list[list[int]] = [[vals[0]]]
    for v in vals[1:]:
        if v - bins[-1][-1] > gap:
            bins.append([v])
        else:
            bins[-1].append(v)
    return [sum(b) / len(b) for b in bins]


def tsv_words_to_grid(words: list[dict[str, Any]]) -> list[list[str]]:
    """Reconstruct a row×column grid from OCR word boxes (each: text, left, top, width, height).

    Rows: words whose `top` falls within a y-tolerance (median height) are one row. Columns: word `left`
    positions are clustered into column bins (gap = median width) and each word assigned to the nearest
    bin. Cells with multiple words are space-joined in left order. Pure + deterministic."""
    ws = [w for w in words if str(w.get("text", "")).strip()]
    if not ws:
        return []
    heights = sorted(int(w.get("height", 0)) for w in ws)
    widths = sorted(int(w.get("width", 0)) for w in ws)
    med_h = heights[len(heights) // 2] or 12
    med_w = widths[len(widths) // 2] or 30
    y_tol = max(med_h * 0.7, 6)
    # A column break is a horizontal gap wider than ~1.5 word-widths; intra-cell word spacing is smaller,
    # so adjacent words in one cell (e.g. "Acme Ventures") stay together while real columns split.
    col_gap = max(med_w * 1.5, 24)

    col_centers = _cluster_1d([int(w["left"]) for w in ws], col_gap)

    def col_index(left: int) -> int:
        return min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - left))

    # group into rows by top
    rows: list[list[dict[str, Any]]] = []
    for w in sorted(ws, key=lambda x: int(x["top"])):
        if rows and (int(w["top"]) - int(rows[-1][0]["top"])) <= y_tol:
            rows[-1].append(w)
        else:
            rows.append([w])

    grid: list[list[str]] = []
    for row in rows:
        cells: list[list[str]] = [[] for _ in col_centers]
        for w in sorted(row, key=lambda x: int(x["left"])):
            cells[col_index(int(w["left"]))].append(str(w["text"]).strip())
        grid.append([" ".join(c).strip() for c in cells])
    return grid


def grid_payload(sheets: dict[str, list[list[str]]]) -> dict[str, Any]:
    """Wrap reconstructed per-sheet grids in the `--mode=grid` shape the freeform pipeline consumes."""
    return {
        "ok": True,
        "mode": "grid",
        "source": "ocr_image_pdf",
        "sheets": {name: {"dimensions": "", "rows": rows, "merged_ranges": []} for name, rows in sheets.items()},
    }


def _tesseract_words(png_path: str) -> list[dict[str, Any]]:
    out = subprocess.run(["tesseract", png_path, "stdout", "tsv"], capture_output=True, text=True, check=True).stdout
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t"):
        if str(r.get("text", "")).strip():
            words.append(
                {
                    "text": r["text"],
                    "left": int(r["left"]),
                    "top": int(r["top"]),
                    "width": int(r["width"]),
                    "height": int(r["height"]),
                }
            )
    return words


def ocr_pdf_to_grid(pdf_path: str, dpi: int = 200) -> dict[str, list[list[str]]]:
    """Render the PDF to per-page PNGs (pdftoppm) and OCR each into a grid (tesseract). Binary-only."""
    sheets: dict[str, list[list[str]]] = {}
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "page")
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix], check=True)
        pngs = sorted(f for f in os.listdir(td) if f.endswith(".png"))
        for i, png in enumerate(pngs, start=1):
            sheets[f"page_{i}"] = tsv_words_to_grid(_tesseract_words(os.path.join(td, png)))
    return sheets


def main() -> int:
    p = argparse.ArgumentParser(description="OCR an image-only PDF into a --mode=grid payload (binary-only).")
    p.add_argument("pdf")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    for binary in ("pdftoppm", "tesseract"):
        if subprocess.run(["which", binary], capture_output=True).returncode != 0:
            print(json.dumps({"ok": False, "mode": "ocr-grid", "error": f"{binary} not installed"}))
            return 1
    try:
        sheets = ocr_pdf_to_grid(args.pdf, dpi=args.dpi)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "mode": "ocr-grid", "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps(grid_payload(sheets), indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
