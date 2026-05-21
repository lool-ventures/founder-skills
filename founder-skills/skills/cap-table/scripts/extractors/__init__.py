"""Extractors module — span-preserving extraction primitives.

This module provides the data types and shared helpers for span-preserving
extraction. The Lane-1 sub-agent + `extract_instrument.py` validator
(in the parent scripts/ directory) handles the main extraction flow;
deterministic per-field extractors under `safe/` (and future
`convertible_note/`, `term_sheet/` subpackages) serve as regex-based
backstops to the sub-agent.

Public types:
    FieldExtraction         — value + evidence_quote + source span + confidence
    SourceSpan              — (start, end) char offsets into the source document
    ExtractionContext       — instrument_type, source_doc_text, source_path
    ExtractorProtocol       — interface a field extractor must satisfy
"""

from __future__ import annotations

from .types import (
    ExtractionContext,
    ExtractorProtocol,
    FieldExtraction,
    SourceSpan,
)

__all__ = [
    "ExtractionContext",
    "ExtractorProtocol",
    "FieldExtraction",
    "SourceSpan",
]
