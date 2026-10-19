#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Write one canonical deck-text file that every later review step reads.

Each sub-agent used to re-transcribe the same deck, so the same slide could be described two
different ways in two places. This producer transcribes once, page by page, and records where
each page's words came from: the PDF's own text layer (`extracted`) or the inventory's
description of an image-only page (`inventory`).

A `.pptx` given directly is read with `zipfile` and `xml.etree` -- no python-pptx, no new
dependency. Speaker notes are read from `--notes-from` (the original PowerPoint a PDF was
converted from) or from the deck itself when it is already a `.pptx`, through each slide's
notes relationship, so a slide-number placeholder never reaches the notes block.

A `.txt`, `.md` or `.markdown` deck is read as UTF-8 and split into slides on `SLIDE N` marker
lines (optionally under a `#` heading). A `--staged` deck is one the main thread wrote from the
founder's own message rather than extracted from a file, so its marker sections are recorded as
`pasted`; `--staged` on a binary deck is refused. When a deck's markers and the inventory do not
agree, no text is dropped: a marked slide the inventory does not know is still written, and an
inventory slide with no marker falls back to its inventory record.

Every warning goes to stderr, into the receipt's `warnings` list, and onto the front matter as a
`warnings: [CODE, ...]` line of codes only.

The output is markdown with YAML front matter. Nothing here renders a slide or judges it; this
is a faithful, deterministic transcription and nothing else.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402
import _out_guard  # type: ignore[import-not-found]  # noqa: E402
import _pdf_pages  # type: ignore[import-not-found]  # noqa: E402
import _run_ref  # type: ignore[import-not-found]  # noqa: E402

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = f"{{{_A_NS}}}"
_P = f"{{{_P_NS}}}"
_R_ID = f"{{{_R_NS}}}id"

_SLIDE_REL_SUFFIX = "/slide"
_NOTES_REL_SUFFIX = "/notesSlide"

_PDF_SUFFIX = ".pdf"
_PPTX_SUFFIX = ".pptx"
_TEXT_SUFFIXES = (".txt", ".md", ".markdown")

_SLIDE_MARKER_RE = re.compile(
    r"^(?:#{1,6}\s*)?slide\s+(\d+)\s*(?:[:.\-\u2013\u2014]|$)",
    re.IGNORECASE,
)


def _reject(code: str, message: str) -> int:
    """A loud refusal: one JSON diagnostic on stdout, one line on stderr, `-o` untouched."""
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message}) + "\n")
    print(f"Error ({code}): {message}; nothing was written", file=sys.stderr)
    return 1


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _nonblank(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _paragraph_lines(element: ET.Element) -> list[str]:
    """One line per `a:p` paragraph, its `a:t` runs joined in document order."""
    lines: list[str] = []
    for paragraph in element.iter(f"{_A}p"):
        text = "".join(run.text or "" for run in paragraph.iter(f"{_A}t")).strip()
        if text:
            lines.append(text)
    return lines


def _slide_number(name: str) -> int | None:
    if not (name.startswith("ppt/slides/slide") and name.endswith(".xml")):
        return None
    stem = name[len("ppt/slides/slide") : -len(".xml")]
    return int(stem) if stem.isdigit() else None


def _resolve_target(base_dir: str, target: str) -> str:
    """A Target starting with '/' is package-absolute; otherwise it resolves beside its part."""
    if target.startswith("/"):
        return posixpath.normpath(target[1:])
    return posixpath.normpath(posixpath.join(base_dir, target))


def _relationships(root: ET.Element, base_dir: str, rel_type_suffix: str) -> dict[str, str]:
    """Relationship Id -> resolved part name, for relationships whose Type ends with the suffix."""
    out: dict[str, str] = {}
    for relationship in root.iter():
        if not relationship.tag.endswith("Relationship"):
            continue
        if not (relationship.get("Type") or "").endswith(rel_type_suffix):
            continue
        rel_id = relationship.get("Id")
        target = relationship.get("Target")
        if rel_id and target:
            out[rel_id] = _resolve_target(base_dir, target)
    return out


def _slide_names_by_file_number(archive: zipfile.ZipFile) -> list[str]:
    """Slide part names ordered by the number in their file name, the fallback order."""
    numbered = [(number, name) for name in archive.namelist() if (number := _slide_number(name)) is not None]
    return [name for _, name in sorted(numbered)]


def _slide_order(archive: zipfile.ZipFile) -> list[str]:
    """Slide part names in the order the presentation shows them.

    The order comes from `ppt/presentation.xml`'s `p:sldIdLst`, each `p:sldId`'s `r:id` resolved
    through `ppt/_rels/presentation.xml.rels`. PowerPoint reorders slides without renaming their
    parts, so a file named `slideN.xml` is not necessarily the N-th slide. Only when
    `presentation.xml` (or its relationships) is missing does the file-name number order stand in.
    """
    try:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
    except KeyError:
        return _slide_names_by_file_number(archive)
    try:
        rels_root = ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    except KeyError:
        return _slide_names_by_file_number(archive)
    targets = _relationships(rels_root, "ppt", _SLIDE_REL_SUFFIX)
    order: list[str] = []
    for sld_id in presentation.iter(f"{_P}sldId"):
        rel_id = sld_id.get(_R_ID)
        part = targets.get(rel_id) if rel_id is not None else None
        if part is not None:
            order.append(part)
    return order


def _pptx_slide_texts(deck: str) -> dict[int, str]:
    """Slide text keyed by presentation position, read straight from the package's XML parts."""
    out: dict[int, str] = {}
    with zipfile.ZipFile(deck) as archive:
        for number, name in enumerate(_slide_order(archive), 1):
            root = ET.fromstring(archive.read(name))
            out[number] = "\n".join(_paragraph_lines(root))
    return out


def _notes_part(archive: zipfile.ZipFile, slide_part: str) -> str | None:
    """The notes part linked from a slide's relationships, or None when it has none."""
    rels_name = posixpath.join(posixpath.dirname(slide_part), "_rels", posixpath.basename(slide_part) + ".rels")
    try:
        root = ET.fromstring(archive.read(rels_name))
    except KeyError:
        return None
    base_dir = posixpath.dirname(slide_part)
    for relationship in root.iter():
        if not relationship.tag.endswith("Relationship"):
            continue
        if not (relationship.get("Type") or "").endswith(_NOTES_REL_SUFFIX):
            continue
        target = relationship.get("Target")
        if not target:
            continue
        return _resolve_target(base_dir, target)
    return None


def _notes_lines(root: ET.Element) -> list[str]:
    """Text from every placeholder except the slide-number one."""
    lines: list[str] = []
    for shape in root.iter(f"{_P}sp"):
        placeholder = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
        if placeholder is not None and placeholder.get("type") == "sldNum":
            continue
        lines.extend(_paragraph_lines(shape))
    return lines


def _pptx_notes(deck: str) -> dict[int, str]:
    """Speaker notes keyed by presentation position, through each slide's own notes relationship."""
    out: dict[int, str] = {}
    with zipfile.ZipFile(deck) as archive:
        names = set(archive.namelist())
        for number, name in enumerate(_slide_order(archive), 1):
            part = _notes_part(archive, name)
            if part is None or part not in names:
                continue
            root = ET.fromstring(archive.read(part))
            lines = _notes_lines(root)
            if lines:
                out[number] = "\n".join(lines)
    return out


def _slide_key(slide: Any, fallback: int) -> int:
    """A slide's own integer `number`; its list position only when that is missing or unusable."""
    if isinstance(slide, dict):
        number = slide.get("number")
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            return number
    return fallback


def _inventory_text(slide: Any) -> str:
    """The inventory's record of a slide: headline, summary, then labelled visuals."""
    if not isinstance(slide, dict):
        return ""
    parts: list[str] = []
    headline = slide.get("headline")
    if isinstance(headline, str) and headline.strip():
        parts.append(headline.strip())
    summary = slide.get("content_summary")
    if isinstance(summary, str) and summary.strip():
        parts.append(summary.strip())
    visuals = slide.get("visuals")
    if isinstance(visuals, str) and visuals.strip():
        parts.append(f"Visuals: {visuals.strip()}")
    return "\n".join(parts)


def _source(pages_source: dict[int, str]) -> str:
    values = set(pages_source.values())
    if not values:
        return "inventory"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _warn(warnings: list[str], message: str) -> None:
    warnings.append(message)
    print(f"Warning: {message}", file=sys.stderr)


def _warning_codes(warnings: list[str]) -> list[str]:
    return [message.split(":", 1)[0].strip() for message in warnings]


def _distinct(numbers: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for number in numbers:
        if number not in seen:
            seen.add(number)
            out.append(number)
    return out


def _parse_text_deck(text: str) -> tuple[dict[int, str], list[int], list[int]]:
    """(per-slide text, marker numbers in file order, duplicated marker numbers).

    A marker is a line beginning `slide N`, optionally under a `#`..`######` heading, separated
    from the rest of the line by a colon, a period, a dash or nothing. Text from a marker to the
    next marker is that slide's; a marker repeated later in the file joins its sections in file
    order. Text before the first marker joins slide 1. A line such as "Slide 4 shows our traction"
    is not a marker, because a word follows the number rather than a separator.
    """
    sections: dict[int, list[str]] = {}
    markers: list[int] = []
    duplicates: list[int] = []
    preamble: list[str] = []
    current: int | None = None
    for line in text.split("\n"):
        match = _SLIDE_MARKER_RE.match(line)
        if match is None:
            (preamble if current is None else sections[current]).append(line)
            continue
        number = int(match.group(1))
        if number not in sections:
            sections[number] = []
            markers.append(number)
        else:
            duplicates.append(number)
        current = number
        sections[number].append(line)
    if preamble and "\n".join(preamble).strip():
        sections[1] = preamble + sections.get(1, [])
    return {number: "\n".join(lines).strip() for number, lines in sections.items()}, markers, duplicates


def _flow_mapping(mapping: dict[int, str]) -> str:
    if not mapping:
        return "{}"
    return "{" + ", ".join(f"{number}: {value}" for number, value in sorted(mapping.items())) + "}"


def _write_atomic(path: str, text: str) -> None:
    """Write beside the destination, then replace it, so an interrupted write cannot truncate it."""
    parent = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix=".deck_text.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Write one canonical deck-text file.")
    ap.add_argument("--deck", required=True, help="The deck: a .pdf, .pptx, .txt, .md or .markdown")
    ap.add_argument("--inventory", required=True, help="deck_inventory.json")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output", required=True, help="The deck_text.md to write")
    ap.add_argument("--notes-from", help="The original .pptx, when --deck is its PDF conversion")
    ap.add_argument("--staged", action="store_true", help="A text deck the main thread wrote from the message")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    _out_guard.refuse_output_onto_input([args.output], script="deck_text.py")
    # In a folder that belongs to a run: only that folder's current run, reading only its own files.
    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)) if args.output else None,
        args.run_id,
        [args.inventory],
        noun="review dir",
    )

    deck_bytes = _read_bytes(args.deck)
    if deck_bytes is None:
        return _reject("DECK_UNREADABLE", f"cannot read --deck {args.deck!r}")

    suffix = os.path.splitext(args.deck)[1].lower()
    is_text = suffix in _TEXT_SUFFIXES
    if suffix not in (_PDF_SUFFIX, _PPTX_SUFFIX, *_TEXT_SUFFIXES):
        return _reject("DECK_FORMAT", f"--deck must be a .pdf, .pptx, .txt, .md or .markdown, got {args.deck!r}")
    if args.staged and not is_text:
        return _reject("STAGED_FORMAT", f"--staged is for a text deck, got {args.deck!r}")

    deck_text: str | None = None
    if is_text:
        try:
            deck_text = deck_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return _reject("DECK_UNREADABLE", f"cannot decode --deck {args.deck!r} as UTF-8")

    try:
        with open(args.inventory, encoding="utf-8") as handle:
            inventory = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return _reject("INVENTORY_UNREADABLE", f"cannot read --inventory {args.inventory!r}: {exc}")
    slides = inventory.get("slides") if isinstance(inventory, dict) else None
    if not isinstance(slides, list):
        return _reject("INVENTORY_NO_SLIDES", f"--inventory {args.inventory!r} has no 'slides' list")

    notes_deck: str | None = None
    if args.notes_from:
        if not os.path.isfile(args.notes_from):
            return _reject("NOTES_UNREADABLE", f"cannot read --notes-from {args.notes_from!r}")
        if os.path.splitext(args.notes_from)[1].lower() != _PPTX_SUFFIX:
            return _reject("NOTES_FORMAT", f"--notes-from must be a .pptx, got {args.notes_from!r}")
        notes_deck = args.notes_from
    elif suffix == _PPTX_SUFFIX:
        notes_deck = args.deck

    pages_source: dict[int, str] = {}
    slide_texts: dict[int, str] = {}
    warnings: list[str] = []

    if is_text:
        assert deck_text is not None
        text_sections, markers, duplicates = _parse_text_deck(deck_text)
        marker_source = "pasted" if args.staged else "extracted"
        if not markers:
            text_sections = {}
            _warn(warnings, "NO_SLIDE_MARKERS")
        for number in _distinct(duplicates):
            _warn(warnings, f"DUPLICATE_SLIDE_MARKER: {number}")
        if markers and len(markers) != len(slides):
            _warn(
                warnings,
                f"PAGE_COUNT_MISMATCH: deck has {len(markers)} slides, inventory has {len(slides)} slides",
            )
        for index, slide in enumerate(slides):
            number = _slide_key(slide, index + 1)
            if number in text_sections:
                slide_texts[number] = text_sections[number]
                pages_source[number] = marker_source
            else:
                slide_texts[number] = _inventory_text(slide)
                pages_source[number] = "inventory"
        for number, section in text_sections.items():
            if number not in slide_texts:
                slide_texts[number] = section
                pages_source[number] = marker_source
    else:
        try:
            extracted = _pptx_slide_texts(args.deck) if suffix == _PPTX_SUFFIX else _pdf_pages.page_texts(args.deck)
        except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            return _reject("DECK_UNREADABLE", f"cannot read --deck {args.deck!r}: {exc}")
        for index, slide in enumerate(slides):
            number = _slide_key(slide, index + 1)
            page = extracted.get(number) if extracted is not None else None
            if suffix == _PDF_SUFFIX:
                if page is not None and _nonblank(page) >= _pdf_pages.TEXT_LAYER_FLOOR:
                    slide_texts[number] = page.rstrip()
                    pages_source[number] = "extracted"
                else:
                    slide_texts[number] = _inventory_text(slide)
                    pages_source[number] = "inventory"
            elif number in (extracted or {}):
                slide_texts[number] = (extracted or {})[number].rstrip()
                pages_source[number] = "extracted"
            else:
                slide_texts[number] = _inventory_text(slide)
                pages_source[number] = "inventory"
        if suffix == _PDF_SUFFIX:
            count = _pdf_pages.page_count(args.deck)
            if count is not None and count != len(slides):
                _warn(
                    warnings,
                    f"PAGE_COUNT_MISMATCH: deck has {count} pages, inventory has {len(slides)} slides",
                )

    slide_notes: dict[int, str] = {}
    if notes_deck is not None:
        try:
            slide_notes = _pptx_notes(notes_deck)
        except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            return _reject("NOTES_UNREADABLE", f"cannot read --notes-from {notes_deck!r}: {exc}")

    source = _source(pages_source)
    deck_sha256 = hashlib.sha256(deck_bytes).hexdigest()

    sections: list[str] = []
    for number in sorted(slide_texts):
        section = f"## Slide {number}\n\n{slide_texts[number]}"
        notes = slide_notes.get(number, "").rstrip()
        if notes:
            section += f"\n\nSpeaker notes:\n{notes}"
        sections.append(section)

    front_lines = [
        "---",
        f"run_id: {args.run_id}",
        f"source: {source}",
        f"pages_source: {_flow_mapping(pages_source)}",
        f"deck_sha256: {deck_sha256}",
    ]
    if warnings:
        front_lines.append(f"warnings: [{', '.join(_warning_codes(warnings))}]")
    front_lines.append("---")
    front_matter = "\n".join(front_lines)
    body = front_matter + "\n\n" + "\n\n".join(sections) + "\n" if sections else front_matter + "\n"

    try:
        _write_atomic(args.output, body)
    except OSError as exc:
        return _reject("WRITE_FAILED", f"cannot write {args.output!r}: {exc}")

    receipt: dict[str, Any] = {
        "ok": True,
        "output_path": str(args.output),
        "source": source,
        "slides": len(slides),
        "pages_source": pages_source,
        "deck_text_sha256": _deck_text_file.body_sha256(body.encode("utf-8")),
    }
    if warnings:
        receipt["warnings"] = warnings
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
