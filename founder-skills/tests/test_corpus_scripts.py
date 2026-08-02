#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression tests for the repo-root corpus_test_*.py diagnostic scripts.

These exercise the pure classification/heuristic functions whose behavior was
corrected — no external corpus or optional deps (pdfplumber/xlrd) are needed.

Run:  pytest founder-skills/tests/test_corpus_scripts.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType

# repo-root/scripts holds the corpus diagnostic scripts.
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(TESTS_DIR))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")


def _load(module_name: str) -> ModuleType:
    path = os.path.join(SCRIPTS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# --- corpus_test_aoa: anti-dilution classifier ordering (shared-scripts-7) ---


def test_aoa_full_ratchet_beats_generic_broad_based() -> None:
    """A full-ratchet AOA carrying generic adjustment language is full_ratchet."""
    aoa = _load("corpus_test_aoa")
    text = "The Conversion Price shall be adjusted on a full ratchet basis. Adjustment of the Conversion Price applies."
    assert aoa.detect_anti_dilution_type(text) == "full_ratchet"


def test_aoa_lowest_price_classifies_full_ratchet() -> None:
    """Specific full-ratchet phrasing ('lowest price') classifies as full_ratchet."""
    aoa = _load("corpus_test_aoa")
    text = (
        "the Conversion Price shall be reduced to the price per share at which "
        "such shares were issued, being the lowest price."
    )
    assert aoa.detect_anti_dilution_type(text) == "full_ratchet"


def test_aoa_broad_based_still_classified() -> None:
    """Genuine broad-based clauses still resolve to broad_based_weighted_average."""
    aoa = _load("corpus_test_aoa")
    text = "Anti-dilution protection on a broad-based weighted average basis. Adjustment of the Conversion Price."
    assert aoa.detect_anti_dilution_type(text) == "broad_based_weighted_average"


# --- corpus_test_safes: CLA marker word boundary (shared-scripts-11) ---


def test_safes_cla_marker_has_word_boundary() -> None:
    """'clause'/'class'/'claim' must not increment the CLA marker count."""
    safes = _load("corpus_test_safes")
    text = (
        "This clause and that class and a claim and a declaration. "
        "Simple Agreement for Future Equity. the Investor. the Safe."
    )
    doc_type, counts = safes.classify_document(text)
    assert counts["cla"] == 0
    assert doc_type == "safe"


# --- corpus_test_term_sheets: case-insensitive jurisdiction (shared-scripts-13) ---


def test_term_sheets_jurisdiction_is_case_insensitive() -> None:
    """All-caps Israeli markers are detected (parity with sibling scripts)."""
    ts = _load("corpus_test_term_sheets")
    # Two distinct Israeli markers in upper case; siblings match these
    # case-insensitively. Without IGNORECASE the count would be 0 -> 'unknown'.
    upper = "MEITAR LAW OFFICES. HERZOG FOX & NEEMAN."
    mixed = "Meitar Law Offices. Herzog Fox & Neeman."
    assert ts.classify_jurisdiction(upper) == ts.classify_jurisdiction(mixed)
    assert ts.classify_jurisdiction(upper) in {"israeli", "israeli_likely"}
