#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber"]
# ///
"""B0 — image-only PDF probe (per-page).

A cap-table PDF whose tables are images (no text layer) is read today by raw model vision, which
under-extracts dense tables silently (the Siteaware P-1 failure). This probe lets the skill DETECT that
case before reading, so it can warn + mark the result low-confidence (B3) instead of silently trusting a
hollow vision extraction.

Detection is PER-PAGE, not whole-doc: a multi-page doc with one text cover page but image-only table pages
must classify as image-only — a whole-doc char total would clear the floor and miss exactly that shape.

Output: a JSON receipt to stdout, e.g.
  {"ok": true, "mode": "pdf-probe", "kind": "image_only", "image_only": true,
   "total_pages": 17, "pages_below_floor": 16, "per_page_char_floor": 100}
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Per-page text-character floor below which a page is "image-only" (no usable text layer). 100 chars/page
# matches the heuristic already documented for the agent (agents/cap-table.md).
PER_PAGE_CHAR_FLOOR = 100


def classify_pages(page_char_counts: list[int], floor: int = PER_PAGE_CHAR_FLOOR) -> dict[str, Any]:
    """Classify a PDF as image-only from per-page stripped-text character counts.

    image-only iff there are no readable pages at all, OR a MAJORITY of pages fall below the per-page
    floor (so a single text cover page can't mask image-only table pages). Pure + side-effect free."""
    total = len(page_char_counts)
    below = sum(1 for c in page_char_counts if c < floor)
    image_only = total == 0 or (below / total) >= 0.5
    return {
        "total_pages": total,
        "pages_below_floor": below,
        "per_page_char_floor": floor,
        "image_only": image_only,
        "kind": "image_only" if image_only else "text",
    }


def _page_char_counts(pdf_path: str) -> list[int]:
    """Per-page stripped-text length via pdfplumber (raises on a missing parser — fail loud, never
    silently treat a parse failure as text)."""
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(pdf_path) as pdf:
        return [len((p.extract_text() or "").strip()) for p in pdf.pages]


def probe_pdf(pdf_path: str, floor: int = PER_PAGE_CHAR_FLOOR) -> dict[str, Any]:
    return classify_pages(_page_char_counts(pdf_path), floor=floor)


def main() -> int:
    p = argparse.ArgumentParser(description="Probe whether a PDF is image-only (no text layer), per-page.")
    p.add_argument("pdf", help="path to the PDF")
    p.add_argument("--floor", type=int, default=PER_PAGE_CHAR_FLOOR, help="per-page char floor")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    try:
        result = probe_pdf(args.pdf, floor=args.floor)
    except ImportError:
        print(json.dumps({"ok": False, "mode": "pdf-probe", "error": "pdfplumber not installed"}))
        return 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "mode": "pdf-probe", "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps({"ok": True, "mode": "pdf-probe", **result}, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
