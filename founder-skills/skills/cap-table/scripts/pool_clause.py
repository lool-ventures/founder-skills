#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber"]
# ///
"""Check that a pool sentence quoted from a founder's document is really in it — evidence, never a verdict.

Before the Pool basis question, the model may quote the document's own pool sentence inside the question so
the founder answers against the words they signed. This script decides only whether that quote may be shown:
it is verified when the sentence appears in the document EXACTLY, or after the whitespace / dash / quote-mark
normalization the extractors already apply. It never decides the basis — the founder's answer does.

Deliberately narrower than `evidence_verifier.quote_in_doc`, which is right for extraction and wrong here:
  * no fuzzy match: a sentence with its meaning flipped ("such additional shares constituting 10%" rewritten to
    "such that the total pool constitutes 10%") passes a fuzzy ratio, and on this question the flip IS the
    whole difference;
  * no compact match: stripping everything but letters and digits makes "10.5%" and "105%" the same string;
  * a glyph the PDF reader could not recover, a `(cid:N)` token, is a barrier, not deleted: deleting it
    can remove a "not" and turn the sentence into its opposite;
  * the match must be a whole sentence or clause, bounded by sentence punctuation or the text's start and
    end: a quote cut off before ", excluding ..." or begun after "It is not agreed that" says something
    the document does not.
A document with too little text to search (image-only, or a fragment) is reported as such, and the question
is then asked plainly.

Usage:
  pool_clause.py --doc <path> --quote "<the pool sentence, verbatim>" [--pretty] [-o <file>]

Output: {"verified": bool, "match": "exact" | "normalized" | null, "reason": ...}. Exit 0 whatever the verdict;
exit 1 when the document cannot be read (a missing parser is reported, never treated as "not found").
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _emit import add_output_args, emit  # noqa: E402
from _normalize import normalize_text  # noqa: E402

# A fragment short enough to occur by accident verifies nothing.
MIN_QUOTE_CHARS = 20
# What may sit just outside a matched sentence: the text's own start or end, or clause punctuation.
_LEFT_BOUNDARY = ".;:!?)"
_RIGHT_BOUNDARY = ".;!?"
# An unrecovered glyph survives normalization as this character, which appears in no quote.
_CID_BARRIER = "\x00"


def _verdict(verified: bool, match: str | None, reason: str) -> dict[str, Any]:
    return {"verified": verified, "match": match, "reason": reason}


def check_pool_clause(quote: str, doc_text: str) -> dict[str, Any]:
    """Whether `quote` appears in `doc_text` exactly or after normalization. Never fuzzy, never compact."""
    import evidence_verifier  # noqa: PLC0415

    quote = (quote or "").strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return _verdict(False, None, "quote_too_short")
    if evidence_verifier.is_doc_image_only(doc_text or ""):
        return _verdict(False, None, "too_little_text")
    doc = normalize_text(re.sub(r"\(cid:\d+\)", _CID_BARRIER, doc_text))
    q = normalize_text(quote)
    start = doc.find(q)
    while start != -1:
        if _bounded(doc, start, start + len(q), q):
            return _verdict(True, "exact" if quote in doc_text else "normalized", "found")
        start = doc.find(q, start + 1)
    return _verdict(False, None, "not_found")


def _bounded(doc: str, start: int, end: int, q: str) -> bool:
    """The match is a whole sentence or clause: nothing but clause punctuation, or the text's own edge, lies
    immediately outside it (whitespace aside)."""
    before = doc[:start].rstrip()
    after = doc[end:].lstrip()
    left = not before or before[-1] in _LEFT_BOUNDARY
    right = q[-1] in _RIGHT_BOUNDARY or not after or after[0] in _RIGHT_BOUNDARY
    return left and right


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--doc", required=True, help="The uploaded document (PDF, DOCX or text).")
    p.add_argument("--quote", required=True, help="The pool sentence, copied verbatim from the document.")
    add_output_args(p)
    args = p.parse_args()

    import evidence_verifier  # noqa: PLC0415

    path = Path(args.doc)
    if not path.is_file():
        # A failure never writes through -o: the diagnostic goes to stdout, a line to stderr.
        print(f"pool_clause: no such document: {args.doc}", file=sys.stderr)
        print(json.dumps(_verdict(False, None, "document_not_found")))
        return 1
    try:
        text = evidence_verifier._load_doc_text(path)
    except evidence_verifier.MissingDependencyError as e:
        print(f"pool_clause: {e}", file=sys.stderr)
        print(json.dumps(_verdict(False, None, "missing_dependency")))
        return 1
    emit(check_pool_clause(args.quote, text), args)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
