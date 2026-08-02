"""B0 — image-only PDF detection (per-page, not whole-doc).

The classification logic is pure (`classify_pages` over per-page char counts) so it's testable without
PDF fixtures. The load-bearing requirement: a multi-page doc with ONE text page but
image-only TABLE pages must classify as image-only — a whole-doc char total would
miss it.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import pdf_probe  # type: ignore[import-not-found]  # noqa: E402


def test_all_pages_low_is_image_only() -> None:
    r = pdf_probe.classify_pages([5, 5, 5])
    assert r["image_only"] is True
    assert r["kind"] == "image_only"


def test_all_pages_text_is_not_image_only() -> None:
    r = pdf_probe.classify_pages([500, 600, 700])
    assert r["image_only"] is False
    assert r["kind"] == "text"


def test_one_text_page_many_image_pages_is_image_only() -> None:
    # A text cover page + 16 image-only table pages. A WHOLE-DOC char total would
    # clear the floor and mislabel this "text" → route to vision → the bug survives. Per-page must catch it.
    r = pdf_probe.classify_pages([800] + [5] * 16)
    assert r["image_only"] is True
    assert r["pages_below_floor"] == 16
    assert r["total_pages"] == 17


def test_mostly_text_one_image_page_is_not_image_only() -> None:
    r = pdf_probe.classify_pages([800, 900, 5])
    assert r["image_only"] is False  # 1/3 below floor < majority


def test_no_pages_is_image_only() -> None:
    # nothing extractable at all → strongest image-only signal (don't trust vision)
    assert pdf_probe.classify_pages([])["image_only"] is True


def test_custom_floor() -> None:
    assert pdf_probe.classify_pages([50, 50], floor=10)["image_only"] is False
    assert pdf_probe.classify_pages([50, 50], floor=100)["image_only"] is True


# --- RTL / reversed-Hebrew text-layer detection (warning-only; never affects image_only) ---

_HEB = "מניות הון רגיל בכורה"  # shares / capital / ordinary / preferred


def test_hebrew_pages_flag_rtl_suspect() -> None:
    r = pdf_probe.detect_rtl([_HEB, _HEB])
    assert r["rtl_suspect"] is True
    assert r["hebrew_char_ratio"] > 0.10


def test_english_pages_do_not_flag_rtl() -> None:
    r = pdf_probe.detect_rtl(["Shares Capital Ordinary", "Total Preferred Options"])
    assert r["rtl_suspect"] is False
    assert r["reversed_word_hits"] == 0
    assert r["forward_word_hits"] == 0


def test_numbers_only_pages_do_not_flag_rtl() -> None:
    # A numbers-only grid (no alphabetic chars) must NOT flag — guards the false positive.
    r = pdf_probe.detect_rtl(["1,000,000 500,000", "12.5% 3,450,000"])
    assert r["hebrew_char_ratio"] == 0.0
    assert r["rtl_suspect"] is False


def test_single_hebrew_page_in_long_english_doc_flags() -> None:
    pages = ["English cap table text here " * 20 for _ in range(30)] + [_HEB * 20]
    r = pdf_probe.detect_rtl(pages)
    assert r["hebrew_char_ratio"] < 0.10  # aggregate diluted well below the floor
    assert r["max_page_hebrew_ratio"] >= 0.10  # but one page is majority-Hebrew
    assert r["rtl_suspect"] is True  # per-page arm catches it


def test_reversed_lexicon_words_flag_reversed_likely() -> None:
    reversed_text = pdf_probe._RTL_LEXICON[0][::-1] + " " + pdf_probe._RTL_LEXICON[1][::-1]
    r = pdf_probe.detect_rtl([reversed_text])
    assert r["rtl_reversed_likely"] is True


def test_forward_hebrew_not_flagged_reversed() -> None:
    forward_text = pdf_probe._RTL_LEXICON[0] + " " + pdf_probe._RTL_LEXICON[1]
    r = pdf_probe.detect_rtl([forward_text])
    assert r["rtl_suspect"] is True
    assert r["rtl_reversed_likely"] is False


def test_rtl_never_affects_image_only_classification() -> None:
    r = pdf_probe.detect_rtl([])  # no crash on empty
    assert r["rtl_suspect"] is False
    assert r["max_page_hebrew_ratio"] == 0.0
    # classify_pages is independent of RTL
    assert pdf_probe.classify_pages([500, 600])["kind"] == "text"
