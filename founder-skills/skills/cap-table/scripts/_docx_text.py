#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tracked-changes-aware DOCX reader (stdlib only: zipfile + xml.etree).

python-docx `Paragraph.text` drops `<w:ins>` (inserted/final) AND `<w:del>` (struck) runs and
misses table cells — so a redline SAFE/note's FINAL operative terms are invisible to it (e.g. an
inserted maturity clause). This module reads the **accepted-revisions** ("accept all changes") view
straight from the OOXML, and detects whether a `.docx` carries tracked changes at all.

stdlib-only on purpose: it runs in the cowork sandbox, which omits `office_convert`/pandoc. Scope is
deliberately narrow — flat accepted-view text + a detection signal. NON-GOALS (do not grow this into a
half-parser): list/clause numbering (`numbering.xml`), fields (`w:fldChar`), footnotes/endnotes,
faithful table *structure*. For SAFE/note/term-sheet terms (body prose + table cells) this suffices.

Entry points (also a CLI):
  - detect_tracked_changes(path) -> {has_tracked_changes, ins, del, move}
  - extract_text(path, revisions="accept") -> str   # v1: accept-only (the final executed view)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Body + headers + footers carry visible text. (Footnotes/endnotes are a documented non-goal.)
_TEXT_PART_RE = re.compile(r"word/(document|header\d*|footer\d*)\.xml$")

# Revision wrappers whose descendant text is DROPPED from the accepted (final) view: struck text
# (`<w:del>`) and the original location of moved text (`<w:moveFrom>`). Insertions (`<w:ins>`) and
# move destinations (`<w:moveTo>`) hold normal `<w:t>` runs and are KEPT.
_ACCEPT_EXCLUDE = frozenset({f"{_W}del", f"{_W}moveFrom"})


def _text_parts(z: zipfile.ZipFile) -> list[str]:
    # document.xml first (sorts before footer/header), then headers/footers — order is immaterial to
    # a substring search blob, but keep the body primary for readability.
    return sorted(n for n in z.namelist() if _TEXT_PART_RE.match(n))


def detect_tracked_changes(path: str) -> dict[str, Any]:
    """Count revision elements across all text parts.

    The reliable signal is the PRESENCE of `<w:ins>`/`<w:del>`/`<w:moveFrom|To>` elements — NOT
    `settings.xml` `<w:trackChanges/>`, which only enables tracking of FUTURE edits (verified False
    on real redlines that already carry changes)."""
    ins = dele = move = 0
    with zipfile.ZipFile(path) as z:
        for part in _text_parts(z):
            xml = z.read(part).decode("utf-8", "ignore")
            ins += len(re.findall(r"<w:ins\b", xml))
            dele += len(re.findall(r"<w:del\b", xml))
            move += len(re.findall(r"<w:move(?:From|To)\b", xml))
    return {"has_tracked_changes": (ins + dele + move) > 0, "ins": ins, "del": dele, "move": move}


def _walk(el: ET.Element, excluded: bool, out: list[str]) -> None:
    """Ancestor-aware recursive descendant walk collecting the ACCEPTED-view text.

    `excluded` latches True under a `<w:del>`/`<w:moveFrom>` ancestor (struck / moved-away text) so
    that text is dropped. This handles nested revisions correctly (a `<w:del>` inside a `<w:ins>` is
    excluded) and `<w:hyperlink>`-wrapped runs (the `<w:r>` is a grandchild) via plain recursion.
    `xml:space="preserve"` is honored implicitly — run text is concatenated verbatim, never stripped."""
    tag = el.tag
    now_excluded = excluded or tag in _ACCEPT_EXCLUDE
    if not now_excluded:
        if tag == f"{_W}t":
            out.append(el.text or "")
        elif tag == f"{_W}tab":
            out.append("\t")
        elif tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
    for child in el:
        _walk(child, now_excluded, out)
    if tag == f"{_W}p" and not now_excluded:
        out.append("\n")


def extract_text(path: str, revisions: str = "accept") -> str:
    """Flat document text in the ACCEPTED-revisions view (final executed terms).

    v1 is **accept-only** — the sole real use case for a redline SAFE/note. Walks body + headers +
    footers; table cell text is captured (tables live inside `document.xml`)."""
    if revisions != "accept":
        raise ValueError(f"unsupported revisions={revisions!r} (v1 is accept-only)")
    out: list[str] = []
    with zipfile.ZipFile(path) as z:
        for part in _text_parts(z):
            root = ET.fromstring(z.read(part))
            _walk(root, False, out)
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description="Tracked-changes-aware DOCX reader (stdlib).")
    p.add_argument("docx", help="path to the .docx")
    p.add_argument("--detect", action="store_true", help="emit a tracked-changes detection receipt (JSON)")
    p.add_argument("--extract", action="store_true", help="emit the accepted-view document text to stdout")
    p.add_argument("--revisions", choices=["accept"], default="accept")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    if args.extract:
        try:
            sys.stdout.write(extract_text(args.docx, revisions=args.revisions))
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(json.dumps({"ok": False, "mode": "docx-extract", "error": f"{type(e).__name__}: {e}"}))
            return 1
        return 0

    # default mode: detect (the SKILL gate's probe — mirrors the pdf_probe receipt shape)
    try:
        result = detect_tracked_changes(args.docx)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "mode": "docx-probe", "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps({"ok": True, "mode": "docx-probe", **result}, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
