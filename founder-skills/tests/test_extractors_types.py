"""Unit tests for the extractors/ types module"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"))

from extractors import ExtractionContext, FieldExtraction, SourceSpan  # type: ignore[import-not-found]  # noqa: E402


class TestSourceSpan:
    def test_extract_returns_slice(self) -> None:
        s = SourceSpan(start=5, end=10)
        assert s.extract("0123456789abc") == "56789"

    def test_negative_start_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceSpan(start=-1, end=5)

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceSpan(start=10, end=5)

    def test_out_of_bounds_extract_raises(self) -> None:
        s = SourceSpan(start=5, end=100)
        with pytest.raises(IndexError):
            s.extract("short")

    def test_to_dict(self) -> None:
        s = SourceSpan(start=2, end=7)
        assert s.to_dict() == {"start": 2, "end": 7}


class TestFieldExtraction:
    def test_minimal_construction(self) -> None:
        fe = FieldExtraction(name="purchase_amount", value=500_000)
        assert fe.name == "purchase_amount"
        assert fe.value == 500_000
        assert fe.confidence == "absent"  # default

    def test_to_dict_includes_span_when_set(self) -> None:
        fe = FieldExtraction(
            name="cap",
            value=20_000_000,
            evidence_quote='"Post-Money Valuation Cap" is $20,000,000',
            span=SourceSpan(start=100, end=145),
            confidence="high",
            extractor_id="subagent:safe_v1",
        )
        d = fe.to_dict()
        assert d["span"] == {"start": 100, "end": 145}
        assert d["confidence"] == "high"
        assert d["extractor_id"] == "subagent:safe_v1"

    def test_to_dict_omits_span_when_absent(self) -> None:
        fe = FieldExtraction(name="x", value=1)
        d = fe.to_dict()
        assert "span" not in d

    def test_validate_span_passes_when_quote_matches(self) -> None:
        source = "Investment amount is $500,000 (the Purchase Amount)."
        # span over "$500,000"
        start = source.index("$500,000")
        fe = FieldExtraction(
            name="purchase_amount",
            value=500_000,
            evidence_quote="$500,000",
            span=SourceSpan(start=start, end=start + len("$500,000")),
        )
        assert fe.validate_span(source) is True

    def test_validate_span_fails_when_quote_differs(self) -> None:
        source = "Investment amount is $500,000."
        fe = FieldExtraction(
            name="purchase_amount",
            value=500_000,
            evidence_quote="$600,000",  # wrong!
            span=SourceSpan(start=0, end=10),
        )
        assert fe.validate_span(source) is False

    def test_validate_span_handles_whitespace_differences(self) -> None:
        # PDF may collapse \n\n into spaces. Span should still validate.
        source = "Cap is\n\n$20,000,000."
        # Span over "Cap is\n\n$20,000,000"
        fe = FieldExtraction(
            name="cap",
            value=20_000_000,
            evidence_quote="Cap is $20,000,000",  # single-spaced
            span=SourceSpan(start=0, end=19),
        )
        assert fe.validate_span(source) is True

    def test_validate_span_returns_true_when_no_span(self) -> None:
        fe = FieldExtraction(name="x", value=1, evidence_quote="anything")
        assert fe.validate_span("any source") is True


class TestExtractionContext:
    def test_construction(self) -> None:
        ctx = ExtractionContext(
            instrument_type="safe",
            source_text="...",
            source_path="/path/to/safe.pdf",
        )
        assert ctx.instrument_type == "safe"
        assert ctx.source_path == "/path/to/safe.pdf"
        assert ctx.metadata == {}
