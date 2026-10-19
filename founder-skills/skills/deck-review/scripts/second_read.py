#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Stage the second read's hand-off as the canonical `second_read.json`.

Step 3.6 dispatches a sub-agent to re-transcribe the figure-bearing slides, and that sub-agent
writes a hand-off shaped `{"slides_transcribed": [...], "transcript": "..."}`. This is the
producer that turns that hand-off into the artifact the rest of the chain reads. It replaces the
inline `python3 -c` the SKILL.md used to pipe the hand-off through, which validated nothing:
a hand-off with a missing `transcript`, a numeric `slides_transcribed`, or a JSON array instead of
an object became a `second_read.json` that `reconcile.py` consumed unconditionally.

WHAT THIS IS NOT. It does not read the deck and does not judge the transcription. The sub-agent
receives the main thread's own extracted deck text, so the transcript descends from the same act
of reading the ledger's quotes came from; all this file does is refuse a hand-off whose shape
would break `reconcile.py`, stamp the run id, and record which deck text the transcript sits
against.

TWO STAMPS, BOTH ABOUT PROVENANCE. `metadata.run_id` binds the artifact to the run that staged it,
overwriting whatever the hand-off carried. `metadata.deck_text_sha256` (written only when
`--deck-text` is given) records the hash of the deck text's BODY -- everything after its front
matter -- so a transcript left beside a later-edited deck text is detectable downstream. A deck
text stamped with another run's id is refused.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402
import _out_guard  # type: ignore[import-not-found]  # noqa: E402
import _run_ref  # type: ignore[import-not-found]  # noqa: E402


def _reject(code: str, message: str) -> int:
    """A loud refusal: one JSON diagnostic on stdout, one line on stderr, `-o` untouched."""
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message}) + "\n")
    print(f"Error ({code}): {message}; nothing was written", file=sys.stderr)
    return 1


def _validate(data: Any) -> str | None:
    """The shape `reconcile.py` needs, or a one-line reason it is not.

    `transcript` is a non-empty string because it is the haystack every ledger quote is matched
    against; an empty one verifies nothing while looking like a reading that ran. `slides_transcribed`
    is a list of positive slide numbers so coverage can tell "no figures on this slide" from "nobody
    looked here". Bools are refused explicitly: `True` is an `int` in Python and would pass as slide 1.
    Unknown keys are kept, so a hand-off may carry whatever else the sub-agent recorded.
    """
    if not isinstance(data, dict):
        return "the hand-off must be a JSON object"
    transcript = data.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return "'transcript' must be a non-empty string"
    slides = data.get("slides_transcribed")
    if not isinstance(slides, list):
        return "'slides_transcribed' must be a list of positive integers"
    for index, slide in enumerate(slides):
        if isinstance(slide, bool) or not isinstance(slide, int) or slide < 1:
            return f"'slides_transcribed[{index}]' must be a positive integer, got {slide!r}"
    return None


def _write_atomic(path: str, text: str) -> None:
    """Write beside the destination, then replace it, so an interrupted write cannot truncate it."""
    parent = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix=".second_read.", suffix=".tmp", dir=parent)
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
    ap = argparse.ArgumentParser(description="Stage the second read's hand-off as second_read.json.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output", required=True, help="The second_read.json to write")
    ap.add_argument("--deck-text", help="deck_text.md; its bytes are hashed into metadata")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    # FIRST: an output naming one of this step's own input files is refused before anything is written.
    _out_guard.refuse_output_onto_input([args.output], script="second_read.py")
    # In a folder that belongs to a run: only that folder's current run, reading only its own files.
    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)) if args.output else None,
        args.run_id,
        [args.deck_text],
        noun="review dir",
    )

    if sys.stdin.isatty():
        print("Error: pipe the second read's hand-off as JSON via stdin", file=sys.stderr)
        return 1
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        return _reject("SECOND_READ_INVALID", f"invalid JSON on stdin: {exc}")

    problem = _validate(data)
    if problem is not None:
        return _reject("SECOND_READ_INVALID", problem)

    deck_text_sha256: str | None = None
    if args.deck_text:
        deck_text_sha256, refusal = _deck_text_file.stamp(args.deck_text, args.run_id)
        if refusal is not None:
            return _reject(refusal["code"], refusal["message"])

    metadata: Any = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["run_id"] = args.run_id
    # The stamp is this producer's, never the hand-off's: a value the sub-agent wrote, or one left
    # from an earlier staging, must not survive a run that was given no deck text to hash.
    metadata.pop("deck_text_sha256", None)
    if deck_text_sha256 is not None:
        metadata["deck_text_sha256"] = deck_text_sha256
    data["metadata"] = metadata

    body = json.dumps(data, indent=2) + "\n"
    try:
        _write_atomic(args.output, body)
    except OSError as exc:
        return _reject("WRITE_FAILED", f"cannot write {args.output!r}: {exc}")

    receipt = {
        "ok": True,
        "output_path": str(args.output),
        "slides_transcribed": len(data["slides_transcribed"]),
        "deck_text_sha256": deck_text_sha256,
    }
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
