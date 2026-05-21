"""Span-preserving extraction types.

Why spans matter: evidence_verifier currently re-runs substring search over
the full source document to locate the evidence quote. When span offsets are
preserved at extraction time, verification becomes O(1) byte-comparison
against the source's offset range — eliminating the entire fuzzy-match
ladder for fields the extractor was confident enough to span-tag.

This module is type scaffolding. Corpus-specific extraction logic lives in
separate extractor modules (e.g. `extractors/safe/purchase_amount.py`)
that all return FieldExtraction instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceSpan:
    """Inclusive-start, exclusive-end character offsets into the source doc."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid SourceSpan: start={self.start}, end={self.end}")

    def extract(self, source: str) -> str:
        """Return source[start:end]. Raises IndexError if out of bounds."""
        if self.end > len(source):
            raise IndexError(f"span [{self.start}:{self.end}] exceeds source length {len(source)}")
        return source[self.start : self.end]

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass
class FieldExtraction:
    """A single field's extracted value, with span-preserved evidence.

    Attributes:
        name: Field name (e.g. "purchase_amount")
        value: The extracted value (any JSON-serializable scalar/composite)
        evidence_quote: Verbatim source text supporting the extraction
        span: Char-offset range in the source doc where evidence_quote lives.
              If None, the extractor couldn't compute a precise span
              (e.g. multi-line clause, table cell joined across rows).
        confidence: "high" | "medium" | "low" | "absent"
        ambiguity: Free-text human-readable note when confidence < high
        extractor_id: Identifier of the extractor that produced this field
                      (e.g. "regex:purchase_amount", "subagent:safe_form")
    """

    name: str
    value: Any
    evidence_quote: str | None = None
    span: SourceSpan | None = None
    confidence: str = "absent"
    ambiguity: str | None = None
    extractor_id: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "evidence_quote": self.evidence_quote,
            "confidence": self.confidence,
            "extractor_id": self.extractor_id,
        }
        if self.span is not None:
            out["span"] = self.span.to_dict()
        if self.ambiguity is not None:
            out["ambiguity"] = self.ambiguity
        return out

    def validate_span(self, source: str) -> bool:
        """If a span is set AND an evidence_quote is set, check that the source
        text in the span matches the evidence_quote (modulo whitespace
        normalization). Returns True if the span is consistent or absent.
        """
        if self.span is None or self.evidence_quote is None:
            return True
        try:
            sliced = self.span.extract(source)
        except IndexError:
            return False
        # Allow whitespace differences (PDFs may collapse line-end whitespace)
        sliced_norm = " ".join(sliced.split())
        quote_norm = " ".join(self.evidence_quote.split())
        return sliced_norm == quote_norm


@dataclass
class ExtractionContext:
    """Shared context passed to all field extractors for a given document."""

    instrument_type: str  # "safe" | "convertible_note" | "term_sheet" | ...
    source_text: str  # extracted text of the source document
    source_path: str | None = None  # original file path (for diagnostics)
    metadata: dict[str, Any] = field(default_factory=dict)


class ExtractorProtocol(Protocol):
    """Interface every field extractor must implement.

    Extractors live in `extractors/<corpus>/<field_or_form>.py` and expose
    an `extract` function matching this signature. The orchestrator
    dispatches by instrument_type → extractor.

    Returns an iterable of FieldExtractions. An extractor may produce zero
    fields (no match), one field (focused regex/heuristic), or many (a
    schema-wide pass like the sub-agent).
    """

    def extract(self, ctx: ExtractionContext) -> list[FieldExtraction]: ...
