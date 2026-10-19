"""Read a PDF's per-page text, with every tool optional and detected at run time.

The deck-text producer wants one answer from a PDF: does this page carry a text layer, or is
it an image the inventory has to describe? `pdftotext` is the best reader when it is present,
`pdfplumber` is a soft import used when it happens to be installed (not a deck-review
dependency), and `pypdf` is a last resort. None of them is required to import this module, and
a missing binary or a failed extraction never raises: callers get None and fall back.

Nothing here writes a file. `pdftotext` prints to stdout (`-`), so there is no scratch copy
under a shared /tmp name to collide with another run.
"""

from __future__ import annotations

import importlib
import subprocess
from typing import Any

TEXT_LAYER_FLOOR = 100
"""Non-blank characters a page needs before its text layer counts as real.

A cover image with a caption, a scanned chart, and a page whose only text is a footer all sit
far below this. At or above it, the page's own words are what a reader sees and the inventory's
summary is the weaker description.
"""

_TIMEOUT = 30


def _pdfinfo_pages(pdf: str) -> int | None:
    try:
        result = subprocess.run(
            ["pdfinfo", pdf],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (IndexError, ValueError):
                return None
    return None


def _pypdf_reader(pdf: str) -> Any | None:
    try:
        pypdf = importlib.import_module("pypdf")
        return pypdf.PdfReader(pdf)
    except Exception:
        return None


def page_count(pdf: str) -> int | None:
    """The number of pages, from `pdfinfo` then `pypdf`, or None when neither can say."""
    count = _pdfinfo_pages(pdf)
    if count is not None:
        return count
    reader = _pypdf_reader(pdf)
    if reader is None:
        return None
    try:
        return len(reader.pages)
    except Exception:
        return None


def _pdftotext_pages(pdf: str) -> dict[int, str] | None:
    count = page_count(pdf)
    if count is None:
        return None
    out: dict[int, str] = {}
    for number in range(1, count + 1):
        try:
            result = subprocess.run(
                ["pdftotext", "-f", str(number), "-l", str(number), pdf, "-"],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        out[number] = result.stdout
    return out


def _pdfplumber_pages(pdf: str) -> dict[int, str] | None:
    try:
        pdfplumber = importlib.import_module("pdfplumber")
        with pdfplumber.open(pdf) as document:
            return {number: (page.extract_text() or "") for number, page in enumerate(document.pages, 1)}
    except Exception:
        return None


def _pypdf_pages(pdf: str) -> dict[int, str] | None:
    reader = _pypdf_reader(pdf)
    if reader is None:
        return None
    try:
        return {number: (page.extract_text() or "") for number, page in enumerate(reader.pages, 1)}
    except Exception:
        return None


def page_texts(pdf: str) -> dict[int, str] | None:
    """Per 1-based page text, trying `pdftotext`, then `pdfplumber`, then `pypdf`; None if none works."""
    for reader in (_pdftotext_pages, _pdfplumber_pages, _pypdf_pages):
        texts = reader(pdf)
        if texts is not None:
            return texts
    return None


def text_layer_chars(pdf: str) -> dict[int, int] | None:
    """Per 1-based page count of non-blank characters, or None when no reader was available."""
    texts = page_texts(pdf)
    if texts is None:
        return None
    return {number: sum(1 for char in text if not char.isspace()) for number, text in texts.items()}
