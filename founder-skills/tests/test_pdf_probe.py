"""B0 — image-only PDF detection (per-page, not whole-doc).

The classification logic is pure (`classify_pages` over per-page char counts) so it's testable without
PDF fixtures. The pre-build review's load-bearing requirement: a multi-page doc with ONE text page but
image-only TABLE pages must classify as image-only (the Siteaware shape) — a whole-doc char total would
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
    # The Siteaware shape: a text cover page + 16 image-only table pages. A WHOLE-DOC char total would
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
