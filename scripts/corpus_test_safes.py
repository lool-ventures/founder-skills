#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber"]
# ///
"""Corpus test: SAFE / convertible-instrument PDF extraction simulation.

Designed to run against a folder of individual signed SAFE / note / warrant
PDFs (the Lane-1 input type per SKILL.md). For each PDF:

  * Loadability via pdfplumber
  * Page count + text-extractability (image-only flag)
  * Document type classification (SAFE / note / warrant / SPA / unknown)
  * SAFE form heuristic (yc_postmoney_cap / cap_plus_discount /
    yc_postmoney_discount / yc_uncapped_mfn / pre_money_legacy / other)
  * Field extraction simulation: regex+heuristic for Purchase Amount,
    Valuation Cap, Discount Rate, MFN, Pro Rata, Investor Name,
    Issuance Date — proxy for what the Lane-1 INSTRUMENT_EXTRACTION
    sub-agent should find
  * Israeli-context markers (Pearl Cohen / Herzog / Meitar / ITA safe harbor)

This is NOT a replacement for the sub-agent's actual extraction — it's a
proxy that shows what fields the agent SHOULD find and how reliably the
patterns surface in real documents. Findings feed back into the
INSTRUMENT_EXTRACTION dispatch prompt in agents/cap-table.md.

Usage:
    python3 scripts/corpus_test_safes.py <CORPUS_DIR> [-o report.json]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

# Document-type discriminators (text patterns)
SAFE_MARKERS = [
    r"\bSAFE\b",
    r"Simple Agreement for Future Equity",
    r"Safe Preferred Stock",
    r"the Investor",
    r"the Safe",
]
NOTE_MARKERS = [
    r"Convertible Note",
    r"Convertible Promissory Note",
    r"Principal Amount",
    r"Interest Rate",
    r"Maturity Date",
]
WARRANT_MARKERS = [
    r"WARRANT TO PURCHASE",
    r"Warrant to Purchase",
    r"Warrant Shares",
    r"Exercise Price",
]
SPA_MARKERS = [
    r"Stock Purchase Agreement",
    r"Share Purchase Agreement",
    r"SHARE PURCHASE AGREEMENT",
]
CLA_MARKERS = [
    r"Convertible Loan Agreement",
    r"\bCLA\b",
    r"convertible loan",
]

# SAFE-form discriminators (key clauses)
SAFE_FORM_MARKERS = {
    "post_money_cap": [
        r"Post-Money Valuation Cap",
        r"post-?money valuation cap",
    ],
    "pre_money_cap": [
        r"Pre-Money Valuation Cap",
        r"pre-?money valuation cap",
    ],
    "discount_rate": [
        r"Discount Rate",
        r"discount rate",
    ],
    "mfn": [
        r"Most Favored Nation",
        r"MFN",
        r"most favored nation",
    ],
    "pro_rata": [
        r"Pro Rata Rights",
        r"pro rata rights",
        r"Pro Rata Side Letter",
        r"Pro-rata",
    ],
}

# Israeli-context discriminators — current and historical big-law hi-tech firms
# Sources: Legal 500 Tier 1, Chambers Band 1-4, Dun's 100 Leaders/Prominent (2024)
ISRAELI_MARKERS = [
    # ── Current top-tier / big-law (Chambers Band 1) ──────────────────────────
    r"Meitar",  # Meitar Law Offices (also Meitar Liquornik Geva Leshem legacy)
    r"Herzog",  # Herzog Fox & Neeman / HFN / Herzog
    r"Goldfarb",  # Goldfarb Gross Seligman (post-2023 GKH+Goldfarb Seligman merger)
    r"Arnon.{0,10}Tadmor",  # Arnon, Tadmor-Levy (post-2022 Yigal Arnon + Tadmor Levy)
    r"FISCHER",  # FISCHER / FBC & Co. (formerly Fischer Behar Chen Well Orion)
    r"Naschitz",  # Naschitz Brandes Amir
    r"Shibolet",
    r"Amit.{0,10}Pollak",  # Amit Pollak Matalon / APM
    r"\bAPM\b",  # APM shorthand
    r"Erdinast",  # Erdinast, Ben Nathan, Toledano / EBN
    r"\bEBN\b",  # EBN shorthand
    r"Gornitzky",
    r"Barnea",  # Barnea Jaffa Lande
    r"Pearl Cohen",
    r"H-F\s*&\s*Co",  # H-F & Co.
    r"\bFWMK\b",
    r"Horn\s*&\s*Co",  # Horn & Co.
    r"Raz Dlugin",
    r"Agmon",  # Agmon with Tulchinsky
    r"\bAYR\b",  # AYR law firm
    r"\bERM\b",  # ERM law firm
    r"Firon",
    r"Katzenell",  # Katzenell Dimant
    r"S\.\s*Horowitz",  # S. Horowitz & Co.
    r"Zemah Schneider",
    r"LIPA\s*&\s*CO",  # LIPA&CO
    # ── Historical / legacy names (may appear in older documents) ─────────────
    r"GKH",  # Gross, Kleinhendler, Hodak, Halevy, Greenberg (→ Goldfarb Gross Seligman)
    r"Gross\s*Kleinhendler",
    r"Yigal Arnon",  # legacy name before 2022 merger
    r"Tadmor\s*Levy",  # legacy name before 2022 merger
    r"Meitar Liquornik",  # historical Meitar brand
    r"Fischer Behar",  # legacy FBC name
    r"\bFBC\b",  # FBC shorthand (Fischer Behar Chen)
    # ── Statutory / tax / context markers ────────────────────────────────────
    r"Israeli law",
    r"Israeli\s+Companies\s+Law",
    r"Companies Law\s*[\-—–]?\s*1999",
    r"Tel Aviv",
    r"Israel Tax Authority",
    r"Section 102",
    r"§102",
    r"NIS\b",
    r"New Israeli Shek",
    r"ITA safe harbor",
    r"2025 Tax Circular",
]

# YC standard form watermark / boilerplate
YC_STANDARD_MARKERS = [
    r"YC SAFE",
    r"Y Combinator",
    r"ycombinator\.com",
    r"this Safe is one of the forms available",
    r"YC.*?Post-Money.*?Safe",
]

# Field extraction patterns. Improved from corpus testing — real SAFEs put
# the Purchase Amount in prose as "$X (the "Purchase Amount") on or about
# <Date>", NOT as a labeled header.

# Purchase Amount in prose: "$X (the "Purchase Amount")"
# Smart quotes (" "), regular quotes ('), or none — all observed in corpus
PURCHASE_AMOUNT_PROSE_RE = re.compile(
    r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*\([^)]*Purchase\s+Amount[^)]*\)",
    re.IGNORECASE,
)
# Purchase Amount labeled: "Purchase Amount: $X" or "Purchase Amount is $X"
PURCHASE_AMOUNT_LABELED_RE = re.compile(
    r"Purchase\s+Amount[^\$\n]{0,30}(?:is|:)?\s*\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

# Valuation Cap — handles smart quotes, "Post-Money"/"Pre-Money" prefix optional
CAP_RE = re.compile(
    r"[\"'“]?(?:Post-?Money|Pre-?Money)?\s*Valuation\s+Cap[\"'”]?"
    r"[^\$\n]{0,80}(?:US)?\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

# Discount Rate / Discount — multiple phrasings, smart-quote-tolerant
DISCOUNT_RE = re.compile(
    r"[\"'“]?Discount(?:\s+Rate)?[\"'”]?"
    r"[^\d\n]{0,30}(?:is\s+|of\s+|:\s*)?([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE,
)

# Issuance/Effective date — corpus shows "on or about <Date>" + "dated as of" + "made and entered into as of"
DATE_PATTERNS = [
    # Headers (rare in real SAFEs)
    r"(?:Effective Date|Date of Issuance|Issue Date|Dated)[:\s]+([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
    r"(?:Effective Date|Date of Issuance|Issue Date|Dated)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
    # In-prose (common in real SAFEs)
    r"(?:on or about|as of|dated as of|made and entered into as of)\s+([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
    r"(?:on or about|as of|dated as of)\s+(\d{1,2}/\d{1,2}/\d{4})",
]

# CID-encoded font detection — DocuSign-signed PDFs frequently have CID
# tokens where font subsetting prevented text recovery. Flag these for
# the sub-agent to either: (a) re-OCR via Claude's PDF reader, or
# (b) prompt the founder for the affected fields.
CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def classify_document(text: str) -> tuple[str, dict[str, int]]:
    """Return (doc_type, marker_counts) based on text pattern matching."""
    counts = {
        "safe": sum(len(re.findall(m, text, re.IGNORECASE)) for m in SAFE_MARKERS),
        "note": sum(len(re.findall(m, text, re.IGNORECASE)) for m in NOTE_MARKERS),
        "warrant": sum(len(re.findall(m, text, re.IGNORECASE)) for m in WARRANT_MARKERS),
        "spa": sum(len(re.findall(m, text, re.IGNORECASE)) for m in SPA_MARKERS),
        "cla": sum(len(re.findall(m, text, re.IGNORECASE)) for m in CLA_MARKERS),
    }
    # Doc type: highest count wins; "safe" is a weak signal so require it to
    # dominate by a margin
    if counts["warrant"] >= 3:
        return "warrant", counts
    if counts["spa"] >= 1 and counts["safe"] < counts["spa"] * 2:
        return "spa", counts
    if counts["note"] >= 5 and counts["safe"] < counts["note"]:
        return "note", counts
    if counts["cla"] >= 3 and counts["safe"] < counts["cla"]:
        return "cla", counts
    if counts["safe"] >= 3:
        return "safe", counts
    return "unknown", counts


def infer_safe_form(text: str) -> tuple[str, dict[str, bool]]:
    """Infer SAFE form by which key clauses are present.

    Improvement (corpus-driven): real SAFEs often say "Valuation Cap"
    without the "Post-Money" prefix when the document is from 2018+ (when
    post-money became the YC default). Detection logic:
      * pre_money_cap explicit → pre-2018 legacy form
      * post_money_cap explicit → modern post-money
      * "Valuation Cap" alone (no Post-/Pre- prefix) → assume post-money
        (modern default since 2018-10)
    """
    markers: dict[str, bool] = {}
    for label, patterns in SAFE_FORM_MARKERS.items():
        markers[label] = any(re.search(p, text, re.IGNORECASE) for p in patterns)

    # "Plain" valuation cap without Post-/Pre- prefix
    has_plain_cap = bool(re.search(r"(?<!Post-)(?<!Pre-)\bValuation Cap\b", text, re.IGNORECASE))
    markers["plain_cap_only"] = has_plain_cap and not markers["post_money_cap"] and not markers["pre_money_cap"]

    if markers["pre_money_cap"]:
        # Pre-money SAFE — pre-2018 YC form (legacy)
        if markers["discount_rate"]:
            return "pre_money_cap_and_discount_legacy", markers
        return "pre_money_cap_only_legacy", markers

    has_cap_modern = markers["post_money_cap"] or markers["plain_cap_only"]

    if has_cap_modern and markers["discount_rate"]:
        return "cap_plus_discount", markers
    if has_cap_modern and not markers["discount_rate"]:
        return "yc_postmoney_cap", markers
    if not has_cap_modern and markers["discount_rate"]:
        return "yc_postmoney_discount", markers
    if markers["mfn"] and not has_cap_modern and not markers["discount_rate"]:
        return "yc_uncapped_mfn", markers
    return "other", markers


def extract_fields(text: str) -> dict[str, Any]:
    """Heuristic field extraction — proxies what the sub-agent should find.

    Improved from corpus testing: real SAFEs put fields in prose, not
    headers. The agent prompt is updated with corpus-derived guidance.
    """
    result: dict[str, Any] = {}

    # Detect CID-encoded font tokens (DocuSign artifact)
    cid_count = len(CID_TOKEN_RE.findall(text))
    if cid_count > 5:
        result["_cid_token_count"] = cid_count
        result["_warning"] = (
            f"{cid_count} CID-encoded font tokens present — some fields "
            f"(investor name, purchase amount, date) likely unreadable. "
            f"Sub-agent should flag for OCR fallback or founder confirmation."
        )

    # Purchase amount — try prose form first ("$X (the 'Purchase Amount')"),
    # then labeled form ("Purchase Amount: $X")
    for re_obj in (PURCHASE_AMOUNT_PROSE_RE, PURCHASE_AMOUNT_LABELED_RE):
        m = re_obj.search(text)
        if m:
            amt = m.group(1).replace(",", "")
            try:
                result["purchase_amount"] = float(amt)
                break
            except ValueError:
                pass

    # Valuation cap — handles smart quotes and Post/Pre-Money prefix variations
    m = CAP_RE.search(text)
    if m:
        cap = m.group(1).replace(",", "")
        with contextlib.suppress(ValueError):
            result["valuation_cap"] = float(cap)

    # Discount rate (percent — needs Gotcha #3 normalization)
    m = DISCOUNT_RE.search(text)
    if m:
        try:
            pct = float(m.group(1))
            # Heuristic: SAFE docs typically state "Discount Rate is 80%"
            # meaning multiplier = 0.80 (an 80%-of-priced-round price).
            # If "20% discount" they mean multiplier = 0.80 as well.
            # The disambiguation: when value > 50, it's the multiplier-percent
            # (e.g. "80%"); when ≤ 50, it's the discount-percent (e.g. "20%").
            if pct > 50:
                result["discount_multiplier"] = pct / 100.0
                result["_discount_interpretation"] = f"{pct}% = multiplier {pct / 100:.2f}"
            else:
                result["discount_multiplier"] = 1.0 - (pct / 100.0)
                result["_discount_interpretation"] = f"{pct}% discount = multiplier {1.0 - pct / 100:.2f}"
        except ValueError:
            pass

    # Effective / issuance date — try header patterns then prose patterns
    for pat in DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["issuance_date_raw"] = m.group(1).strip()
            break

    # Investor name — record only DETECTABILITY, never the real party name.
    # The corpus is real signed SAFEs; storing the captured name would leak a
    # real counterparty into the (anonymized) report. A boolean is enough to
    # measure how reliably the pattern surfaces.
    inv_m = re.search(
        r"(?:Investor\s*Name|Name of Investor)[:\s]+([A-Z][\w\s.,&-]{2,80})",
        text,
    )
    if inv_m:
        result["investor_name_detected"] = True
    else:
        # Try prose form: "exchange for the payment by <NAME> (the 'Investor')"
        inv_m = re.search(
            r"payment\s+by\s+([\w\s.,&-]{3,60}?)\s*\([^)]*Investor[^)]*\)",
            text,
            re.IGNORECASE,
        )
        if inv_m and "(cid:" not in inv_m.group(1):
            result["investor_name_detected"] = True

    return result


def has_israeli_context(text: str) -> tuple[bool, list[str]]:
    """Detect Israeli-law markers in the document."""
    matches = []
    for m in ISRAELI_MARKERS:
        if re.search(m, text, re.IGNORECASE):
            matches.append(m)
    return len(matches) > 0, matches


def has_yc_template(text: str) -> bool:
    """Detect standard YC SAFE template markers."""
    return any(re.search(m, text, re.IGNORECASE) for m in YC_STANDARD_MARKERS)


def analyze_pdf(path: Path) -> dict[str, Any]:
    """Full analysis pipeline for one PDF."""
    try:
        import pdfplumber

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pdfplumber.open(path) as pdf:
                n_pages = len(pdf.pages)
                full_text = ""
                page_texts = []
                for page in pdf.pages:
                    txt = page.extract_text() or ""
                    page_texts.append(len(txt.strip()))
                    full_text += txt + "\n"
        text_density = len(full_text.strip()) / max(n_pages, 1)
        is_image_only = text_density < 100

        if is_image_only:
            return {
                "loadable": True,
                "n_pages": n_pages,
                "text_density_per_page": round(text_density, 1),
                "is_image_only": True,
                "doc_type": "image_only",
                "note": "Insufficient text extracted; would require OCR / Claude PDF reader",
            }

        doc_type, type_counts = classify_document(full_text)
        israeli, israeli_matches = has_israeli_context(full_text)
        yc_template = has_yc_template(full_text)

        result: dict[str, Any] = {
            "loadable": True,
            "n_pages": n_pages,
            "text_density_per_page": round(text_density, 1),
            "is_image_only": False,
            "doc_type": doc_type,
            "type_marker_counts": type_counts,
            "is_israeli_context": israeli,
            "israeli_markers_found": israeli_matches,
            "is_yc_template": yc_template,
        }

        if doc_type == "safe":
            form, markers = infer_safe_form(full_text)
            fields = extract_fields(full_text)
            result["safe_form"] = form
            result["form_clause_markers"] = markers
            result["extracted_fields"] = fields
        elif doc_type == "note" or doc_type == "cla":
            fields = extract_fields(full_text)
            result["extracted_fields"] = fields

        return result
    except Exception as e:
        return {
            "loadable": False,
            "error": f"{type(e).__name__}: {e}"[:300],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_dir", help="Directory of SAFE/convertible PDFs")
    parser.add_argument("-o", "--output", default=None, help="JSON report path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    corpus = Path(args.corpus_dir)
    if not corpus.is_dir():
        print(f"ERROR: {corpus} is not a directory", file=sys.stderr)
        return 1

    pdfs = sorted([f for f in corpus.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"])
    print(f"Analyzing {len(pdfs)} PDFs in {corpus}", file=sys.stderr)

    results: list[dict[str, Any]] = []
    for f in pdfs:
        result = analyze_pdf(f)
        result["anon_name"] = f"file_{len(results):03d}"
        result["file_size_bytes"] = f.stat().st_size
        results.append(result)
        if args.verbose:
            status = result.get("doc_type", "error")
            extra = ""
            if result.get("safe_form"):
                extra = f" form={result['safe_form']}"
            if result.get("is_israeli_context"):
                extra += " [Israeli]"
            print(f"  [{status:10s}]{extra:35s} {f.name[:60]}", file=sys.stderr)

    # Aggregates
    doc_types = Counter(r.get("doc_type", "error") for r in results)
    safe_forms = Counter(r.get("safe_form", "n/a") for r in results if r.get("doc_type") == "safe")
    israeli_count = sum(1 for r in results if r.get("is_israeli_context"))
    yc_template_count = sum(1 for r in results if r.get("is_yc_template"))
    image_only_count = sum(1 for r in results if r.get("is_image_only"))
    loadable_count = sum(1 for r in results if r.get("loadable"))

    # Field-extraction success rates (SAFEs only)
    safe_results = [r for r in results if r.get("doc_type") == "safe"]
    field_success = {
        "purchase_amount": sum(1 for r in safe_results if "purchase_amount" in r.get("extracted_fields", {})),
        "valuation_cap": sum(1 for r in safe_results if "valuation_cap" in r.get("extracted_fields", {})),
        "discount_multiplier": sum(1 for r in safe_results if "discount_multiplier" in r.get("extracted_fields", {})),
        "issuance_date_raw": sum(1 for r in safe_results if "issuance_date_raw" in r.get("extracted_fields", {})),
    }

    report = {
        "corpus_dir": str(corpus),
        "total_files": len(pdfs),
        "loadability": {
            "loadable": loadable_count,
            "image_only": image_only_count,
            "text_extractable": loadable_count - image_only_count,
        },
        "doc_type_distribution": dict(doc_types),
        "safe_form_distribution": dict(safe_forms),
        "israeli_context_count": israeli_count,
        "yc_template_count": yc_template_count,
        "field_extraction_success_rate_on_safes": {
            k: f"{v}/{len(safe_results)} ({100 * v / max(len(safe_results), 1):.0f}%)" for k, v in field_success.items()
        },
        "per_file": results,
    }

    if args.output:
        out_path = os.path.abspath(args.output)
        with open(out_path, "w") as out_f:
            json.dump(report, out_f, indent=2, default=str)
        print(f"\nReport written to {out_path}", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("SAFE CORPUS TEST SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Total PDFs: {len(pdfs)}", file=sys.stderr)
    print(f"Loadable: {loadable_count}/{len(pdfs)}", file=sys.stderr)
    print(f"Text-extractable: {loadable_count - image_only_count}/{len(pdfs)}", file=sys.stderr)
    print(f"Image-only (would need OCR): {image_only_count}/{len(pdfs)}", file=sys.stderr)
    print("\nDocument type breakdown:", file=sys.stderr)
    for t, c in doc_types.most_common():
        print(f"  {c:3d} × {t}", file=sys.stderr)
    print(f"\nSAFE form breakdown ({len(safe_results)} SAFEs):", file=sys.stderr)
    for t, c in safe_forms.most_common():
        print(f"  {c:3d} × {t}", file=sys.stderr)
    print(f"\nIsraeli-context: {israeli_count}/{len(pdfs)}", file=sys.stderr)
    print(f"YC standard template: {yc_template_count}/{len(pdfs)}", file=sys.stderr)
    print("\nField extraction success (on SAFEs, heuristic — sub-agent does real extraction):", file=sys.stderr)
    for k, v in field_success.items():
        print(f"  {k:25s} {v}/{len(safe_results)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
