#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber"]
# ///
"""Corpus test: Articles of Association PDF extraction simulation.

AOAs are the legal-document source of truth for share class terms (Original
Issue Price, Original Conversion Price, liquidation preferences, anti-
dilution protection, conversion rights, voting rights, drag/tag rights,
pro rata, right of first refusal). Currently the cap-table skill assumes
the founder enters these manually; an AOA parser closes that gap.

For each PDF:
  * Loadability via pdfplumber
  * Detect Israeli vs Delaware AOA conventions
  * Identify which key sections are present (Share Capital, Liquidation
    Preference, Anti-Dilution, Conversion, Voting, Drag-Along, Tag-Along,
    Pro Rata, ROFR)
  * Extract per-share-class fields heuristically (OIP, OCP, liquidation
    preference multiple + type, AD protection type, conversion ratio)
  * Output aggregate stats + per-file machine report

Usage:
    python3 scripts/corpus_test_aoa.py <CORPUS_DIR> [-o report.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

# AOA-specific document markers
AOA_MARKERS = [
    r"Articles of Association",
    r"Amended and Restated Articles",
    r"Certificate of Incorporation",
    r"Memorandum of Association",
    r"Amended Articles",
]

# Section discriminators (which sections does the AOA cover?)
SECTION_MARKERS = {
    "share_capital": [
        r"Share Capital",
        r"Authorized Share Capital",
        r"Authorized Capital",
        r"Registered Capital",
    ],
    "liquidation_preference": [
        r"Liquidation Preference",
        r"Liquidation Event",
        r"Preference Amount",
        r"Distribution on Liquidation",
    ],
    "anti_dilution": [
        r"Anti-?[Dd]ilution",
        r"Weighted Average",
        r"Full Ratchet",
        r"Broad[- ]?[Bb]ased",
        r"Narrow[- ]?[Bb]ased",
        r"Adjustment of Conversion Price",
    ],
    "conversion": [
        r"Conversion Rights?",
        r"Conversion of Preferred",
        r"Conversion Price",
        r"Conversion Ratio",
        r"Mandatory Conversion",
        r"Optional Conversion",
    ],
    "voting": [
        r"Voting Rights?",
        r"Voting Power",
        r"Protective Provisions",
        r"Class Vote",
        r"Special Majority",
    ],
    "drag_along": [
        r"Drag[- ]?[Aa]long",
        r"Bring[- ]?[Aa]long",
        r"Compulsory Sale",
    ],
    "tag_along": [
        r"Tag[- ]?[Aa]long",
        r"Co[- ]?[Ss]ale",
    ],
    "pro_rata": [
        r"Pro[- ]?[Rr]ata",
        r"Preemptive Rights?",
        r"Preferred Allocation Rights?",
    ],
    "rofr": [
        r"Right of First Refusal",
        r"ROFR",
        r"First Refusal",
    ],
    "registration_rights": [
        r"Registration Rights?",
        r"Demand Registration",
        r"Piggyback",
    ],
}

# Liquidation preference patterns
LIQ_PREF_MULTIPLE_RE = re.compile(
    r"(?:liquidation\s+preference[^.]{0,80}?)([0-9](?:\.[0-9]+)?)\s*[Xx×]",
    re.IGNORECASE,
)
LIQ_PREF_PARTICIPATION_RE = re.compile(
    r"(non[- ]?participating|fully\s+participating|participating(?:\s+capped)?)",
    re.IGNORECASE,
)

# (AD_TYPE_MARKERS and OIP patterns moved above ISRAELI_MARKERS)

# Share-class naming patterns (common conventions across US + Israel)
SHARE_CLASS_PATTERNS = [
    r"Series\s+(?:Seed|A|B|C|D|E|F|Pre[- ]?[Ss]eed)(?:[- ]?[0-9])?(?:\s+Preferred)?",
    r"Preferred\s+(?:Series\s+)?(?:Seed|A|B|C|D|E|F)",
    r"(?:Series\s+)?(?:Seed|A|B|C|D|E|F)\s+Preferred",
    r"Ordinary\s+Shares?",
    r"Common\s+Stock",
]

# OIP patterns for Israeli AOAs:
# Pattern 1: "US$ X.XXX" — literal dollar sign with space, used in definitions section
# Pattern 2: "NIS X.XX" — shekel-denominated OIP
# NOTE: NIS 0.01 = par value (nominal value per Israeli Companies Law), not OIP
# Filter out values <= 0.01 NIS to avoid par value noise
OIP_DEFN_RE = re.compile(
    r"(?:US\$|USD)\s+([0-9]+\.[0-9]+)"
    r"|"
    r"NIS\s+([0-9]+\.[0-9]+)"
)
PAR_VALUE_THRESHOLD = 0.02  # NIS 0.01 is par value; anything <= this is not OIP

# AD patterns — extend with Israeli phrasing variants.
#
# Order matters: detect_anti_dilution_type returns on the first matching type,
# so full_ratchet must be checked BEFORE broad_based_weighted_average. The
# broad-based bucket carries generic conversion-price-adjustment phrasings
# (r"Adjustment of...Conversion Price") that appear in essentially every AOA
# with any anti-dilution clause — including full-ratchet ones — so checking
# broad-based first would misclassify full-ratchet AOAs as broad-based.
# Full-ratchet therefore leads with specific markers ("lowest price",
# "reduced to the price") that do not appear in weighted-average clauses.
AD_TYPE_MARKERS = {
    "full_ratchet": [
        r"full\s+ratchet",
        r"lowest\s+price",
        r"reduced\s+to\s+the\s+price",
    ],
    "narrow_based_weighted_average": [
        r"narrow[- ]?based\s+weighted\s+average",
        r"narrow[- ]?based",
    ],
    "broad_based_weighted_average": [
        r"broad[- ]?based\s+weighted\s+average",
        r"broad[- ]?based",
        r"Adjustment of.{0,20}Conversion Price",
        r"Conversion Price.{0,30}shall be adjusted",
        r"adjustment.{0,30}weighted\s+average",
    ],
}

# Israeli-context discriminators — current and historical big-law hi-tech firms
# Sources: Legal 500 Tier 1, Chambers Band 1-4, Dun's 100 Leaders/Prominent (2024)
ISRAELI_MARKERS = [
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
    r"Israel.*?Companies Law",
    r"Tel Aviv",
    r"Section 102",
    r"§102",
    r"NIS\b",
    r"New Israeli Shek",
]

# Delaware-context discriminators
DELAWARE_MARKERS = [
    r"Delaware General Corporation Law",
    r"DGCL",
    r"State of Delaware",
    r"Delaware corporation",
    r"Certificate of Incorporation",
]


def classify_jurisdiction(text: str) -> str:
    """Identify whether the AOA is governed by Israeli or Delaware law."""
    israeli = sum(1 for m in ISRAELI_MARKERS if re.search(m, text, re.IGNORECASE))
    delaware = sum(1 for m in DELAWARE_MARKERS if re.search(m, text, re.IGNORECASE))
    if israeli >= 2 and israeli > delaware:
        return "israeli"
    if delaware >= 2 and delaware > israeli:
        return "delaware"
    if israeli > 0 and delaware == 0:
        return "israeli_likely"
    if delaware > 0 and israeli == 0:
        return "delaware_likely"
    return "unknown"


def detect_sections(text: str) -> dict[str, bool]:
    """Detect which key AOA sections are present in the document."""
    sections = {}
    for label, patterns in SECTION_MARKERS.items():
        sections[label] = any(re.search(p, text, re.IGNORECASE) for p in patterns)
    return sections


def detect_share_classes(text: str) -> list[str]:
    """Identify mentioned share classes.

    Filters out noise:
    - Single-char prefix fragments ("a Preferred", "e Preferred" come from
      mid-sentence lowercase references like "the Series A Preferred Shares")
    - Duplicate case variants
    """
    classes_found = set()
    for pat in SHARE_CLASS_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            cls = re.sub(r"\s+", " ", m.group(0).strip())
            # Drop single-letter-prefix fragments: "a Preferred", "b Preferred"
            if re.match(r"^[a-z]\s+Preferred", cls):
                continue
            classes_found.add(cls)
    # Case-insensitive dedup: keep the most-capitalized variant
    deduped: dict[str, str] = {}
    for c in classes_found:
        key = c.lower()
        if key not in deduped or c[0].isupper():
            deduped[key] = c
    return sorted(deduped.values())


def extract_liquidation_preferences(text: str) -> dict[str, Any]:
    """Extract liquidation preference structure."""
    result: dict[str, Any] = {}

    # Find liquidation preference multiples
    multiples = []
    for m in LIQ_PREF_MULTIPLE_RE.finditer(text):
        try:
            mult = float(m.group(1))
            if 0 < mult <= 10:  # sanity bound
                multiples.append(mult)
        except ValueError:
            pass
    if multiples:
        result["multiples_found"] = sorted(set(multiples))

    # Find participation type
    participation_matches = LIQ_PREF_PARTICIPATION_RE.findall(text)
    if participation_matches:
        # Normalize
        normalized = []
        for p in participation_matches:
            p_lower = p.lower()
            if "non" in p_lower:
                normalized.append("non_participating")
            elif "capped" in p_lower:
                normalized.append("participating_capped")
            elif "participating" in p_lower:
                normalized.append("participating")
        result["participation_types_found"] = sorted(set(normalized))

    return result


def detect_anti_dilution_type(text: str) -> str | None:
    """Identify which AD protection type the AOA specifies."""
    for ad_type, patterns in AD_TYPE_MARKERS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return ad_type
    return None


def extract_oip(text: str) -> list[dict[str, Any]]:
    """Extract Original Issue Price values from the text.

    Israeli AOA pattern: "US$ X.XXX" in the Definitions section.
    NIS 0.01 = par value (nominal value under Israeli Companies Law) — filtered out.
    Returns list of {currency, value} dicts.
    """
    seen: set[tuple[str, float]] = set()
    results: list[dict[str, Any]] = []
    for usd_val, nis_val in OIP_DEFN_RE.findall(text):
        if usd_val:
            v = float(usd_val)
            if 0 < v <= 1000 and ("USD", v) not in seen:
                seen.add(("USD", v))
                results.append({"currency": "USD", "value": v})
        if nis_val:
            v = float(nis_val)
            # Filter par value (NIS 0.01 is the statutory minimum nominal value)
            if v > PAR_VALUE_THRESHOLD and ("NIS", v) not in seen:
                seen.add(("NIS", v))
                results.append({"currency": "NIS", "value": v})
    return results


def analyze_pdf(path: Path) -> dict[str, Any]:
    """Full analysis pipeline for one AOA PDF."""
    try:
        import pdfplumber

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pdfplumber.open(path) as pdf:
                n_pages = len(pdf.pages)
                full_text = ""
                for page in pdf.pages:
                    txt = page.extract_text() or ""
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
            }

        # Verify this is actually an AOA
        is_aoa = any(re.search(m, full_text, re.IGNORECASE) for m in AOA_MARKERS)

        result: dict[str, Any] = {
            "loadable": True,
            "n_pages": n_pages,
            "text_density_per_page": round(text_density, 1),
            "is_image_only": False,
            "is_aoa": is_aoa,
            "jurisdiction": classify_jurisdiction(full_text),
            "sections_present": detect_sections(full_text),
            "share_classes_found": detect_share_classes(full_text),
            "anti_dilution_type": detect_anti_dilution_type(full_text),
            "liquidation_preferences": extract_liquidation_preferences(full_text),
            "oips_found": extract_oip(full_text),
            "liquidation_multiple_note": (
                "Israeli AOAs express liq pref as OIP+X%/yr (implicit 1x); numeric multiples not parsed"
            ),
        }

        # Count how many key sections are present (signal of AOA completeness)
        sections_present_count = sum(result["sections_present"].values())
        result["section_completeness"] = f"{sections_present_count}/{len(SECTION_MARKERS)}"
        return result
    except Exception as e:
        return {
            "loadable": False,
            "error": f"{type(e).__name__}: {e}"[:300],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_dir", help="Directory of AOA PDFs")
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
            jur = result.get("jurisdiction", "?")
            sects = result.get("section_completeness", "?")
            classes = len(result.get("share_classes_found", []))
            print(
                f"  [{jur:15s}] sections={sects} classes={classes} {f.name[:55]}",
                file=sys.stderr,
            )

    # Aggregate findings
    jurisdictions = Counter(r.get("jurisdiction", "error") for r in results)
    section_coverage: dict[str, int] = {label: 0 for label in SECTION_MARKERS}
    for r in results:
        for sect, present in r.get("sections_present", {}).items():
            if present:
                section_coverage[sect] += 1

    ad_types = Counter(r.get("anti_dilution_type") for r in results if r.get("anti_dilution_type"))

    # Unique share classes across the corpus
    all_classes: set[str] = set()
    for r in results:
        all_classes.update(r.get("share_classes_found", []))

    report = {
        "corpus_dir": str(corpus),
        "total_files": len(pdfs),
        "loadable_count": sum(1 for r in results if r.get("loadable")),
        "image_only_count": sum(1 for r in results if r.get("is_image_only")),
        "jurisdiction_distribution": dict(jurisdictions),
        "section_coverage": section_coverage,
        "anti_dilution_types_found": dict(ad_types),
        "unique_share_class_names": sorted(all_classes)[:30],
        "per_file": results,
    }

    if args.output:
        out_path = os.path.abspath(args.output)
        with open(out_path, "w") as out_f:
            json.dump(report, out_f, indent=2, default=str)
        print(f"\nReport written to {out_path}", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("AOA CORPUS TEST SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Total PDFs: {len(pdfs)}", file=sys.stderr)
    print(f"Loadable: {report['loadable_count']}/{len(pdfs)}", file=sys.stderr)
    print(f"Image-only: {report['image_only_count']}/{len(pdfs)}", file=sys.stderr)
    print("\nJurisdiction distribution:", file=sys.stderr)
    for j, c in jurisdictions.most_common():
        print(f"  {c:3d} × {j}", file=sys.stderr)
    print(f"\nSection coverage (out of {len(results)} loadable AOAs):", file=sys.stderr)
    loadable = [r for r in results if not r.get("is_image_only")]
    for sect, count in sorted(section_coverage.items(), key=lambda x: -x[1]):
        pct = 100 * count / max(len(loadable), 1)
        print(f"  {count:3d}/{len(loadable)} ({pct:5.1f}%) {sect}", file=sys.stderr)
    print("\nAnti-dilution types found:", file=sys.stderr)
    for t, c in ad_types.most_common():
        print(f"  {c:3d} × {t}", file=sys.stderr)
    print(f"\nUnique share class names ({len(all_classes)}):", file=sys.stderr)
    for c in sorted(all_classes)[:15]:
        print(f"  {c}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
