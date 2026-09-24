"""market-sizing's copy of cap-table's PDF probe must not drift.

Skill scripts are standalone and cannot import across skills, so the image-only-PDF probe exists
twice. Compared as PARSED BODIES rather than as text, so reformatting is allowed and a behaviour
change is not — the pattern `test_quote_match_sync.py` uses for deck-review's copy of cap-table's
matcher, and `test_theme_sync.py` for the six `_theme.py` copies.

A drift here means two skills disagree about whether a founder's document is readable, which is
worse than either answer alone: one skill would warn and the other would silently under-read.
"""

from __future__ import annotations

import ast
import pathlib

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills"
_CAP_TABLE = SCRIPTS / "cap-table" / "scripts" / "pdf_probe.py"
_MARKET_SIZING = SCRIPTS / "market-sizing" / "scripts" / "pdf_probe.py"

# Every top-level function. The module docstrings deliberately DIFFER (the copy says it is one),
# so the comparison is over definitions, never over file text.
_SHARED = ("_hebrew_ratio", "detect_rtl", "classify_pages", "_page_texts", "probe_pdf", "main")


def _defs(path: pathlib.Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_both_probes_exist() -> None:
    assert _CAP_TABLE.is_file(), f"missing: {_CAP_TABLE}"
    assert _MARKET_SIZING.is_file(), f"missing: {_MARKET_SIZING}"


def test_pdf_probe_copies_have_not_drifted() -> None:
    cap, ms = _defs(_CAP_TABLE), _defs(_MARKET_SIZING)
    for name in _SHARED:
        assert name in cap, f"cap-table/pdf_probe.py lost {name}"
        assert name in ms, f"market-sizing/pdf_probe.py lost its copy of {name}"
        assert cap[name] == ms[name], (
            f"{name} has drifted between the two pdf_probe.py copies — two skills would disagree "
            "about whether a founder's document is readable. Edit one, re-copy to the other."
        )
    # Non-vacuity: a typo in a name above would make the loop assert nothing, and the two files
    # must not have grown a function the list does not cover.
    assert len(_SHARED) == 6
    assert set(cap) == set(ms) == set(_SHARED), (set(cap) ^ set(ms)) or set(cap) ^ set(_SHARED)


def test_the_module_constants_agree() -> None:
    """The thresholds ARE the behaviour; an AST diff over functions alone would miss them."""
    for const in ("PER_PAGE_CHAR_FLOOR = 100", "RTL_HEBREW_RATIO_FLOOR = 0.10"):
        assert const in _CAP_TABLE.read_text(encoding="utf-8"), const
        assert const in _MARKET_SIZING.read_text(encoding="utf-8"), const
