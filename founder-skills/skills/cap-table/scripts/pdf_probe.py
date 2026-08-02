#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber"]
# ///
"""B0 — image-only PDF probe (per-page).

A cap-table PDF whose tables are images (no text layer) is read today by raw model vision, which
under-extracts dense tables silently. This probe lets the skill DETECT that
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

# A text layer that is majority-Hebrew (or stores lines in visual / reversed order, a common
# locale-export artifact) garbles a naive vision/line read of tables — silent numeric transcription
# errors. This is a WARNING signal only: it never changes image_only / kind / the exit code.
RTL_HEBREW_RATIO_FLOOR = 0.10
# Hebrew Unicode block (incl. presentation forms would need U+FB1D–FB4F; the base block suffices here).
_HEBREW_LO, _HEBREW_HI = "֐", "׿"
# Common Hebrew cap-table words, for the visual-order (reversed) heuristic. Hebrew string : English gloss.
_RTL_LEXICON = [
    "מניות",  # shares
    "הון",  # capital
    "סהכ",  # total (sach-hakol)
    "רגיל",  # ordinary
    "בכורה",  # preferred
    "אופציות",  # options
]


def _hebrew_ratio(text: str) -> float:
    """Hebrew-block letters / all letters (0.0 when there are no letters — a numbers-only grid)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    hebrew = sum(1 for c in letters if _HEBREW_LO <= c <= _HEBREW_HI)
    return hebrew / len(letters)


def detect_rtl(page_texts: list[str]) -> dict[str, Any]:
    """Warning-only RTL signal. Hebrew-locale exports frequently store the text layer in visual
    (reversed) order, which garbles naive line reads. Pure; never affects image_only / kind / exit."""
    joined = "\n".join(page_texts)
    agg_ratio = _hebrew_ratio(joined)
    max_page_ratio = max((_hebrew_ratio(t) for t in page_texts), default=0.0)
    # Aggregate OR any single page — one fully-Hebrew page in a long English doc sits far below the
    # aggregate floor but must still flag (the same whole-doc-aggregation failure classify_pages avoids).
    rtl_suspect = agg_ratio >= RTL_HEBREW_RATIO_FLOOR or max_page_ratio >= RTL_HEBREW_RATIO_FLOOR
    reversed_hits = sum(joined.count(w[::-1]) for w in _RTL_LEXICON)
    forward_hits = sum(joined.count(w) for w in _RTL_LEXICON)
    return {
        "hebrew_char_ratio": agg_ratio,
        "max_page_hebrew_ratio": max_page_ratio,
        "rtl_suspect": rtl_suspect,
        "reversed_word_hits": reversed_hits,
        "forward_word_hits": forward_hits,
        "rtl_reversed_likely": rtl_suspect and reversed_hits > forward_hits,
    }


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


def _page_texts(pdf_path: str) -> list[str]:
    """Per-page stripped text via pdfplumber (raises on a missing parser — fail loud, never
    silently treat a parse failure as text)."""
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(pdf_path) as pdf:
        return [(p.extract_text() or "").strip() for p in pdf.pages]


def probe_pdf(pdf_path: str, floor: int = PER_PAGE_CHAR_FLOOR) -> dict[str, Any]:
    texts = _page_texts(pdf_path)
    result = classify_pages([len(t) for t in texts], floor=floor)
    rtl = detect_rtl(texts)
    result["rtl"] = rtl
    if rtl["rtl_suspect"]:
        warnings = ["W_PDF_RTL_TEXT_SUSPECT"]
        if rtl["rtl_reversed_likely"]:
            warnings.append("W_PDF_RTL_REVERSED_LIKELY")
        result["warnings"] = warnings
    return result


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
