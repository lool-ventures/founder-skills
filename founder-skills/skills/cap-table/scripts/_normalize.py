"""Shared text-normalization primitives for cap-table extraction + verification.

Extracted from evidence_verifier.py so that future extractor modules can
reuse the same normalization without depending on evidence_verifier
directly.

Public API:
    normalize_text(s)       — smart quotes, dashes, CID strip, hyphenation, whitespace
    compact_form(s)         — strip non-alphanumeric (last-resort matcher)
    numeric_tokens(value)   — plausible representations of a number ($20M, "20 million", etc.)
    date_tokens(yyyy_mm_dd) — plausible representations of an ISO date
"""

from __future__ import annotations

import re
from typing import Any


def normalize_text(s: str) -> str:
    """Aggressive normalization for fuzzy text match.

    Handles pdfplumber/DocuSign-specific extraction artifacts:
      - Smart quotes → ASCII
      - Em/en dashes → hyphen
      - CID-encoded font tokens stripped
      - Hyphenation across line breaks (`foo-\\nbar` → `foobar`)
      - Whitespace collapsed
    """
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\(cid:\d+\)", "", s)
    s = re.sub(r"([a-zA-Z])-\s*\n\s*([a-zA-Z])", r"\1\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compact_form(s: str) -> str:
    """Strip everything except letters and digits.

    Last-resort matcher for pdfplumber's stuck-together-words extraction
    (e.g. `is80%` instead of `is 80%`).
    """
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


_MONTH_NAMES = {
    1: ("january", "jan"),
    2: ("february", "feb"),
    3: ("march", "mar"),
    4: ("april", "apr"),
    5: ("may", "may"),
    6: ("june", "jun"),
    7: ("july", "jul"),
    8: ("august", "aug"),
    9: ("september", "sep", "sept"),
    10: ("october", "oct"),
    11: ("november", "nov"),
    12: ("december", "dec"),
}


def numeric_tokens(value: Any) -> list[str]:
    """Plausible representations of a numeric value that might appear in a doc.

    For 20000000 → ['20000000', '20,000,000', '20M', '20 million', '$20M', ...]
    For 0.80     → ['0.80', '80%', '80']
    For dates    → [] (use date_tokens)
    """
    if value is None:
        return []
    if isinstance(value, bool):
        return [str(value).lower(), str(value)]
    if isinstance(value, int):
        s = str(value)
        out = [s]
        if abs(value) >= 1000:
            out.append(f"{value:,}")

        def _fmt_compact(n: float) -> list[str]:
            out2 = []
            for spec in (".3f", ".2f", ".1f"):
                s2 = f"{n:{spec}}".rstrip("0").rstrip(".")
                if s2 and s2 not in out2:
                    out2.append(s2)
            return out2

        if abs(value) >= 1_000_000_000:
            n = value / 1_000_000_000
            for n_str in _fmt_compact(n):
                out.extend([f"{n_str}B", f"{n_str} billion", f"${n_str} billion", f"${n_str}B", f"${n_str}bn"])
        elif abs(value) >= 1_000_000:
            n = value / 1_000_000
            for n_str in _fmt_compact(n):
                out.extend([f"{n_str}M", f"{n_str} million", f"${n_str} million", f"${n_str}M", f"${n_str}mm"])
        elif abs(value) >= 1_000:
            n = value / 1_000
            for n_str in _fmt_compact(n):
                out.extend([f"{n_str}K", f"${n_str}K", f"${n_str}k"])
        return list(dict.fromkeys(filter(None, out)))
    if isinstance(value, float):
        out = [f"{value:.4f}".rstrip("0").rstrip("."), f"{value:.2f}".rstrip("0").rstrip(".")]
        # An integer-valued float (e.g. 20000000.0 from JSON) must generate the
        # same comma / $XM / "X million" variants as the int branch, otherwise a
        # value_in_doc check against a doc printing "$20,000,000" fails purely on
        # JSON number formatting (the compact-form fallback is disabled for
        # numerics in evidence_verifier).
        if value.is_integer() and abs(value) >= 1000:
            out.extend(numeric_tokens(int(value)))
        if 0 < value < 1:
            pct = value * 100
            pct_str = f"{pct:.4f}".rstrip("0").rstrip(".")
            out.append(f"{pct_str}%")
            out.append(pct_str)
        return list(dict.fromkeys(filter(None, out)))
    return [str(value)]


def date_tokens(date_str: str) -> list[str]:
    """For YYYY-MM-DD date strings, generate likely representations: ISO, US,
    EU, written-out month, and Month-only-year forms."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if not m:
        return []
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    day_stripped = str(day)
    year_str = str(year)
    tokens = [
        date_str,
        f"{month:02d}/{day:02d}/{year}",
        f"{month}/{day}/{year}",
        f"{day:02d}/{month:02d}/{year}",
        f"{day}/{month}/{year}",
    ]
    for name in _MONTH_NAMES[month]:
        tokens.extend(
            [
                f"{name} {day_stripped}, {year}",
                f"{name} {day:02d}, {year}",
                f"{name} {day_stripped} {year_str}",
                f"{day_stripped} {name} {year}",
                f"{day:02d} {name} {year}",
                f"{name} {year}",
                f"{name}-{year}",
            ]
        )
    tokens.append(f"{year}-{month:02d}")
    return tokens
