#!/usr/bin/env python3
"""deck-review's copy of the quote matcher must not drift from cap-table's original.

WHY A COPY EXISTS AT ALL: skill scripts are standalone, run by path with no package
context, so deck-review cannot import cap-table's `evidence_verifier`. `_theme.py` is
copied across all six skills for the same reason and `test_theme_sync.py` is the
precedent for this test.

WHAT THIS GUARDS, and why it is not the obvious thing. An earlier design note said to
copy `_normalize.py`. That is the half that will NOT drift; the matching logic —
the five-step fallback, both fuzzy passes, the calibrated threshold — lives in
`evidence_verifier.py`, and a sync test over `_normalize.py` alone would have locked the
stable half and left the volatile half free to diverge silently. So this compares the
functions that actually decide whether a figure passes the gate.

Comparison is on the PARSED function body, not the file: the two files legitimately
differ in imports, module docstring and what else they contain.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DECK_COPY = REPO / "founder-skills" / "skills" / "deck-review" / "scripts" / "_quote_match.py"
CAP_NORMALIZE = REPO / "founder-skills" / "skills" / "cap-table" / "scripts" / "_normalize.py"
CAP_VERIFIER = REPO / "founder-skills" / "skills" / "cap-table" / "scripts" / "evidence_verifier.py"


def _function_source(path: pathlib.Path, name: str) -> str:
    """Return a function's normalized source, with its docstring stripped.

    Docstrings are excluded deliberately: the copy's docstring may explain the copy, and
    a comment divergence is not a behaviour divergence. Everything else must match.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            stripped = ast.Module(body=body, type_ignores=[])
            return ast.dump(ast.parse(ast.unparse(stripped)), annotate_fields=False)
    raise AssertionError(f"{name} not found in {path}")


@pytest.mark.parametrize(
    ("func", "origin"),
    [
        ("normalize_text", CAP_NORMALIZE),
        ("compact_form", CAP_NORMALIZE),
        ("quote_in_doc", CAP_VERIFIER),
    ],
)
def test_copied_function_matches_origin(func: str, origin: pathlib.Path) -> None:
    assert _function_source(DECK_COPY, func) == _function_source(origin, func), (
        f"{func} has drifted from {origin.name}. These are copies by necessity — edit one, "
        "re-copy to the other. Do not 'fix' this by deleting the assertion."
    )


def test_fuzzy_threshold_matches_origin() -> None:
    """The threshold is calibrated against a private evaluation set held by cap-table.

    Retuning it from deck data alone would silently move a constant two skills share.
    """
    origin = CAP_VERIFIER.read_text(encoding="utf-8")
    copy = DECK_COPY.read_text(encoding="utf-8")
    assert "DEFAULT_FUZZY_THRESHOLD = 0.85" in origin
    assert "DEFAULT_FUZZY_THRESHOLD = 0.85" in copy


def test_value_matching_is_deliberately_absent() -> None:
    """`value_in_doc` must NOT be copied into deck-review.

    Measured on decks: `value_in_doc` false-passes 5.7% cross-deck and 37% on plausible
    round numbers, because a slide deck is dense with round integers, page numbers and
    axis labels. `quote_in_doc` false-passes 0.8%. The gate was deliberately inverted
    relative to cap-table's precedent, and re-adding a value check here would undo that
    without anyone noticing.
    """
    tree = ast.parse(DECK_COPY.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # Names in the module docstring are the file EXPLAINING the absence, which is the
    # opposite of the thing being tested — so this reads definitions, not text.
    assert defined == {"normalize_text", "compact_form", "quote_in_doc"}, (
        f"unexpected functions in the deck-review copy: {sorted(defined)}"
    )
