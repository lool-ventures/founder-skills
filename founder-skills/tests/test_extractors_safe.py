"""Unit tests for deterministic SAFE backstop extractors."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts"))

from extractors import ExtractionContext  # noqa: E402
from extractors.safe import (  # noqa: E402
    SAFE_EXTRACTORS,
    discount_multiplier,
    investor_name,
    issuance_date,
    purchase_amount,
    valuation_cap,
)


def _ctx(text: str) -> ExtractionContext:
    return ExtractionContext(instrument_type="safe", source_text=text)


# ---------------------------------------------------------------------------
# purchase_amount
# ---------------------------------------------------------------------------


class TestPurchaseAmount:
    def test_canonical_form(self):
        text = 'in exchange for the payment of $500,000 (the "Purchase Amount")'
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 500_000
        assert out[0].confidence == "medium"

    def test_no_thousands_separator(self):
        text = 'payment of $500000 (the "Purchase Amount")'
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 500_000

    def test_smart_quotes(self):
        text = "payment of $1,000,000 (the “Purchase Amount”) on or about"
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 1_000_000

    def test_investment_amount_alias(self):
        text = '$100,000 (the "Investment Amount") was paid'
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 100_000

    def test_no_match_returns_empty(self):
        out = purchase_amount.extract(_ctx("just text, no purchase amount here"))
        assert out == []

    def test_multiple_candidates_flagged(self):
        text = '$500,000 (the "Purchase Amount") and later $750,000 (the "Purchase Amount")'
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 2
        assert all(r.confidence == "low" for r in out)
        assert all("multiple" in (r.ambiguity or "") for r in out)

    def test_span_preserved(self):
        text = 'XXX $500,000 (the "Purchase Amount") YYY'
        out = purchase_amount.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].span is not None
        sliced = text[out[0].span.start : out[0].span.end]
        assert "$500,000" in sliced


# ---------------------------------------------------------------------------
# discount_multiplier
# ---------------------------------------------------------------------------


class TestDiscountMultiplier:
    def test_multiplier_form_X_geq_50(self):
        text = 'The "Discount Rate" is 80%.'
        out = discount_multiplier.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 0.80
        assert out[0].confidence == "medium"
        assert "multiplier-form" in (out[0].ambiguity or "")

    def test_rate_form_X_lt_50(self):
        text = "discount equal to 25%"
        out = discount_multiplier.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == 0.75
        assert "rate-form" in (out[0].ambiguity or "")

    def test_tiered_emits_low_confidence_no_value(self):
        # Multiple distinct percentages → ambiguity
        text = "Discount Rate is 95% after 3 months, 90% after 6 months, and 85% thereafter."
        out = discount_multiplier.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value is None
        assert out[0].confidence == "low"
        amb = out[0].ambiguity or ""
        assert "multi_value" in amb or "conditional" in amb

    def test_conditional_lower_of(self):
        # Realistic legal phrasing — "discount" keyword anchors the regex.
        text = "the discount equal to the lower of 20% or the rate offered to subsequent investors"
        out = discount_multiplier.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value is None  # extractor refuses to decide
        assert "conditional" in (out[0].ambiguity or "").lower()

    def test_no_match_returns_empty(self):
        out = discount_multiplier.extract(_ctx("no discount terms here"))
        assert out == []


# ---------------------------------------------------------------------------
# valuation_cap
# ---------------------------------------------------------------------------


class TestValuationCap:
    def test_post_money_only(self):
        text = 'The "Post-Money Valuation Cap" is US$20,000,000.'
        out = valuation_cap.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].name == "post_money_valuation_cap"
        assert out[0].value == 20_000_000

    def test_pre_money_bare_only(self):
        text = 'The "Valuation Cap" is US$10,000,000. No post-money references anywhere.'
        out = valuation_cap.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].name == "pre_money_valuation_cap"
        assert out[0].value == 10_000_000

    def test_hybrid_terminology_prefers_post_money(self):
        # The OVLP pattern: bare "Valuation Cap" in defined term + Post-Money
        # references in price formulas.
        text = (
            'The "Valuation Cap" is US$15,000,000. The Safe Price means the '
            "price per share equal to the Post-Money Valuation Cap divided by "
            "the Company Capitalization."
        )
        out = valuation_cap.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].name == "post_money_valuation_cap"
        assert "hybrid_terminology" in (out[0].ambiguity or "")

    def test_no_match(self):
        out = valuation_cap.extract(_ctx("unrelated text"))
        assert out == []


# ---------------------------------------------------------------------------
# issuance_date
# ---------------------------------------------------------------------------


class TestIssuanceDate:
    def test_on_or_about_pattern(self):
        text = "on or about January 15, 2024, the Company issues"
        out = issuance_date.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == "2024-01-15"
        assert out[0].confidence == "medium"

    def test_as_of_pattern(self):
        text = "this Agreement is entered into as of March 5, 2023"
        out = issuance_date.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == "2023-03-05"

    def test_template_blank_returns_null(self):
        text = "this Agreement is entered into as of __________, 2024 between"
        out = issuance_date.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value is None
        assert out[0].confidence == "absent"
        assert "template_blank" in (out[0].ambiguity or "")

    def test_multiple_dates_uses_first(self):
        text = "on or about May 1, 2024 ... later amended as of December 31, 2024"
        out = issuance_date.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == "2024-05-01"
        assert "multiple_dates" in (out[0].ambiguity or "")

    def test_no_match(self):
        out = issuance_date.extract(_ctx("just other content"))
        assert out == []


# ---------------------------------------------------------------------------
# investor_name
# ---------------------------------------------------------------------------


class TestInvestorName:
    def test_canonical_form(self):
        text = 'in exchange for the payment by Foobar Capital LLC (the "Investor")'
        out = investor_name.extract(_ctx(text))
        assert len(out) == 1
        assert out[0].value == "Foobar Capital LLC"

    def test_long_legal_name(self):
        text = 'in exchange for the payment by Acmecorp Ventures III, L.P. (the "Investor")'
        out = investor_name.extract(_ctx(text))
        assert len(out) == 1
        assert "Acmecorp Ventures" in out[0].value

    def test_no_match(self):
        out = investor_name.extract(_ctx("no investor pattern here"))
        assert out == []


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_safe_extractors_listed(self):
        assert len(SAFE_EXTRACTORS) == 5
        # Each module exposes extract(ctx)
        for mod in SAFE_EXTRACTORS:
            assert callable(getattr(mod, "extract", None))
