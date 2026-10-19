#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Read the small pieces of a canonical deck-text file: its front matter, its body hash, its run id.

A deck-text file opens with front matter between two `---` fences: the file's first line and the
next line that is exactly `---`. Everything after that second fence is the body. A markdown body
may carry `---` lines of its own (a horizontal rule, a slide rule), so only the first two fences
count. Nothing here reads a slide or judges a deck; these are the pure string and byte helpers the
producer and its callers share.
"""

from __future__ import annotations

import hashlib
import os

_FENCE = "---"
_OPENING = b"---\n"
_SECOND = b"\n---"


def _fence_line(lines: list[str]) -> int | None:
    for index in range(1, len(lines)):
        if lines[index] == _FENCE:
            return index
    return None


def split(text: str) -> tuple[dict[str, str] | None, str]:
    """(front matter, body) for a file that opens with a `---` fence, else (None, text).

    The front matter is the `key: value` lines between the file's first line and the next line that
    is exactly `---`; the body is everything after that line. When the file does not open with
    `---`, or carries no second `---` line, both the front matter and the body are absent and the
    whole text comes back as the body. A body with its own `---` lines does not reopen the front
    matter, because only the first two fences count.
    """
    lines = text.split("\n")
    if not lines or lines[0] != _FENCE:
        return None, text
    end = _fence_line(lines)
    if end is None:
        return None, text
    front: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        front[key.strip()] = value.lstrip(" ")
    return front, "\n".join(lines[end + 1 :])


def front_matter(text: str) -> dict[str, str] | None:
    """The front matter's key/value pairs, or None when the file carries none."""
    front, _ = split(text)
    return front


def _body_start(data: bytes) -> int:
    """The offset of the newline that ends the second `---` fence, or 0 with no valid front matter."""
    if not data.startswith(_OPENING):
        return 0
    index = 3
    while True:
        found = data.find(_SECOND, index)
        if found == -1:
            return 0
        after = found + len(_SECOND)
        if after == len(data) or data[after : after + 1] == b"\n":
            return after
        index = found + 1


def body_sha256(data: bytes) -> str:
    """sha256 hex of the bytes after the second `---` fence, including its newline.

    With no valid front matter -- no opening fence, or no second one -- it is the sha256 of all the
    bytes, so a caller can always hash something.
    """
    return hashlib.sha256(data[_body_start(data) :]).hexdigest()


def run_id_of(path: str | os.PathLike[str]) -> str | None:
    """The front matter's `run_id`, or None when the file is unreadable or carries none."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return None
    front, _ = split(text)
    if front is None:
        return None
    return front.get("run_id")


def stamp(path: str | os.PathLike[str], run_id: str) -> tuple[str | None, dict[str, str] | None]:
    """(the body's sha256, None) for this run's deck text, else (None, a refusal).

    The bytes are read once so the hash is over exactly what the front matter was read from. A file
    that cannot be read or decoded, that carries no front matter, or whose front matter names another
    or no run is refused by code rather than raising. Pure: prints nothing.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return None, {"code": "DECK_TEXT_UNREADABLE", "message": f"cannot read deck_text.md: {exc}"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, {"code": "DECK_TEXT_UNREADABLE", "message": f"deck_text.md is not UTF-8: {exc}"}
    front, _ = split(text)
    if front is None:
        return None, {"code": "DECK_TEXT_INVALID", "message": "deck_text.md carries no front matter"}
    found = front.get("run_id")
    if found != run_id:
        return None, {
            "code": "DECK_TEXT_OTHER_RUN",
            "message": (
                f"deck_text.md belongs to run {found!r}, not {run_id!r}; run Step 2's deck_text.py again for this run"
            ),
        }
    return body_sha256(data), None
