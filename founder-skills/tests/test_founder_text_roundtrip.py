"""Producer strings must survive the policy that renders them.

THE CLASS. `_founder_text.substitute` rewrites snake_case tokens anywhere in the text -- including
inside the backticks an author used to mark a token as literal. So a producer writes an actionable
instruction and the founder is handed a mangled one:

    producer:  Author a `priced_round` scenario (parameters `pre_money` / `new_money`)
    delivered: Author a `priced_round` scenario (parameters `pre money` / `new money`)

`pre money` is not a parameter. Nothing detects this, and the module's own comment says why: `scan()`
runs AFTER `substitute()` at every call site, so by the time anything looks, the token is already a
plain-English phrase and reports clean. A delivered-artifact scan structurally cannot see it.

This catches it at the SOURCE instead: a founder-facing string that changes when substituted is a
string whose author and whose renderer disagree. That is either a leak the author should not have
written, or a literal the policy should not have touched -- both worth a human decision.

RATCHET, SHRINK-ONLY. The baseline is what was measured on the day this landed, not a target. Lower
it when you fix one; never raise it to make a new one pass.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"

# Dict keys whose values are rendered to a founder verbatim by some producer.
_FOUNDER_TEXT_KEYS = frozenset({"remedy", "reason", "detail", "message", "guidance", "recommendation"})

# MEASURED against THIS file's key set AND its literal walk. SHRINK ONLY; fails in BOTH directions.
#
# It was 29 when the walk saw only `ast.Constant`. That number was not a smaller problem, it was a
# blinder: f-strings outnumber constants ~2:1 in founder-text values (110 vs 61 measured), so the
# ratchet could not see the very remedy it was written about. Widening the walk to f-string and
# concatenation segments took the true count to 68. Re-measure whenever `_FOUNDER_TEXT_KEYS` or
# `_literal_parts` changes; never inherit a count from a review or a sibling file.
_BASELINE = 68


def _founder_text() -> types.ModuleType:
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("_founder_text", REPO / "scripts" / "_founder_text.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cap_table_keep() -> frozenset[str]:
    d = SKILLS / "cap-table" / "scripts"
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    spec = importlib.util.spec_from_file_location("_founder_text_keep", d / "_founder_text_keep.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(mod.cap_table_keep())


def _literal_parts(node: ast.AST) -> list[str]:
    """The literal text of a founder-facing value, including inside an f-string.

    F-STRINGS ARE THE DOMINANT SHAPE, and a Constant-only walk could not see them: measured across
    the fleet, 105 founder-text values are f-strings against 59 plain constants. The remedy that
    motivated this whole detector -- `f"{len(notes)} convertible note(s) are outstanding ... "` --
    was itself invisible to the first version of this function, so the ratchet could not see the
    defect it was written about.

    Interpolations are skipped and their surrounding literal segments checked individually: a
    computed value cannot be audited statically, but the prose around it can.
    """
    out: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip():
        out.append(node.value)
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str) and part.value.strip():
                out.append(part.value)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        out.extend(_literal_parts(node.left))
        out.extend(_literal_parts(node.right))
    return out


def _founder_strings(path: Path) -> list[tuple[int, str]]:
    """Every literal string a producer assigns to a founder-facing key.

    Dict literals and keyword arguments both, because producers use both shapes. Docstrings and
    comments are excluded by construction: this walks the AST, not the text.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=False):
                if isinstance(k, ast.Constant) and k.value in _FOUNDER_TEXT_KEYS:
                    for text in _literal_parts(v):
                        out.append((getattr(v, "lineno", 0), text))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in _FOUNDER_TEXT_KEYS:
                    for text in _literal_parts(kw.value):
                        out.append((getattr(kw.value, "lineno", 0), text))
    return out


def _offenders() -> list[str]:
    ft = _founder_text()
    keep = _cap_table_keep()
    found: list[str] = []
    for script in sorted(SKILLS.glob("*/scripts/*.py")):
        # The static keep can only carry cap-table's glossary; other skills pass none at their call
        # sites, so scanning them with an empty keep matches what they actually do.
        k = keep if script.parts[-3] == "cap-table" else frozenset()
        for lineno, s in _founder_strings(script):
            if ft.substitute(s, extra_keep=k) != s:
                found.append(f"{script.relative_to(REPO)}:{lineno}")
    return found


def test_founder_text_roundtrip_ratchet() -> None:
    offenders = _offenders()
    assert len(offenders) <= _BASELINE, (
        f"{len(offenders)} founder-facing producer strings are rewritten by substitute (baseline "
        f"{_BASELINE}). A NEW one shipped: the founder will read a mangled version of what you "
        f"wrote. Either drop the internal token from the prose, or gloss it in _labels.py.\n"
        # Sorted for a stable, readable report: `_offenders()` returns ast.walk order, so slicing it
        # printed an arbitrary element rather than anything related to what changed.
        + "\n".join(sorted(offenders))
    )
    if len(offenders) < _BASELINE:
        pytest.fail(
            f"only {len(offenders)} offenders remain (baseline {_BASELINE}) -- good. Lower "
            f"_BASELINE to {len(offenders)} to lock the win in. This ratchet fails in BOTH "
            f"directions, like the rest of this repo's: an un-lowered baseline is headroom for the "
            f"next regression to hide in."
        )


def test_ratchet_is_not_vacuous() -> None:
    """A detector that finds nothing proves nothing. This class is real and currently populated."""
    assert _offenders(), "the round-trip detector found nothing at all — it has stopped working"


# ------------------------------------------------------------------------------------------------
# The DELIVERED half. The producer ratchet above catches a string whose author and renderer
# disagree; this catches the same defect where it actually reaches a founder, including text no
# producer literal contains (composed at runtime, or assembled from a rule pack).
# ------------------------------------------------------------------------------------------------

# An ALLOWLIST, not a count. A count was the wrong mechanism twice over:
#
#   - The predicate cannot distinguish a mangled token from domain English that happens to share its
#     shape. `option pool`, `term sheet`, `common stock`, `pro rata`, `fully diluted` and
#     `accrued interest` are all substituted forms of real tokens AND ordinary things a report might
#     legitimately backtick. Under a count, the first innocent one reds CI.
#   - Failing in both directions made that worse: fixing the one known hit forces the baseline to 0,
#     at which point the test asserts nothing, and a partial fixture failure prints "lower it" --
#     instructing the maintainer to disarm the detector.
#
# So: every accepted span is named, with the reason. A new span reds, and the fix is either to stop
# mangling it or to add a line here saying why it is fine. Both are a human decision.
_ALLOWED_DELIVERED: dict[str, str] = {
    # ic-sim's verdict legend renders `**Decline — Hard Pass** (internal `hard_pass`)`; substitute
    # de-snakes the parenthetical, destroying the legend's purpose (it exists to show the raw token
    # beside the label). A REAL defect, allowlisted because fixing it belongs to the `substitute`
    # code-span work. Remove this line when that lands.
    "ic-sim/report.md: `Decline — hard pass`": "known: verdict legend, pending code-span protection",
}


def _looks_substituted(span: str) -> bool:
    """True when a backticked span looks like a snake_case token that has been de-snaked.

    A code span the author wrote is a literal: `pre_money`, `report.json`, `--flag`. A span reading
    `pre money` is one substitute got to. The test is round-trip: re-snake it, humanize it, and see
    if you land back on what is rendered.
    """
    span = span.strip()
    if " " not in span:
        return False
    # The naive round-trip (re-snake, humanize, compare) is the IDENTITY for any span whose only
    # structure is spaces -- measured, it returned True for `npm install`, `uv run pytest` and
    # `SELECT * FROM t`. It collapsed to "contains a space", so the baseline of 1 was luck: the
    # committed fixtures happen to render only one multi-word span.
    #
    # A de-snaked token is narrower than that. Every part must be a plausible identifier fragment
    # (lowercase alphanumeric, no punctuation, no shell/SQL shape), and the whole must re-snake into
    # a token some producer or schema in this repo actually uses -- otherwise it is just prose.
    # Ask the POLICY what each known token becomes, and look for that. This catches both shapes a
    # de-snaked token actually takes: the plain humanize (`pre_money` -> `pre money`) and the
    # _labels-mapped form (`hard_pass` -> `Decline — hard pass`), which carries an em dash and a
    # capital and so is invisible to any rule about identifier-looking parts.
    return span.lower() in _substituted_forms()


def _substituted_forms() -> frozenset[str]:
    """What `substitute` turns each real snake_case token in this repo into.

    Grounded in actual vocabulary, not shape. Shape alone cannot distinguish `npm install` from
    `pre money` -- the first predicate here tried and was measured to return True for `npm install`,
    `uv run pytest` and `SELECT * FROM t`, i.e. it had collapsed to "contains a space".
    """
    global _FORMS
    if _FORMS is None:
        ft = _founder_text()
        pat = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
        forms: set[str] = set()
        for f in list(SKILLS.glob("*/scripts/*.py")) + list(SKILLS.glob("*/references/schemas/*.json")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover
                continue
            for tok in pat.findall(text):
                sub = str(ft.substitute(tok))
                if sub != tok and " " in sub:
                    forms.add(sub.lower())
        _FORMS = frozenset(forms)
    return _FORMS


_FORMS: frozenset[str] | None = None


def test_delivered_scan_actually_examines_code_spans() -> None:
    """Companion to the producer half's non-vacuity test, which this side was missing.

    The delivered scan can only find a mangled span if the fixtures render code spans at all. Four
    of the six skills render none, so this asserts the corpus it examines is non-empty -- otherwise
    a fixture change could quietly reduce the whole detector to `assert True`.
    """
    import re
    import tempfile

    sys.path.insert(0, str(Path(__file__).parent))
    from test_compose_invariants import drive_compose

    spans = 0
    for skill_dir in sorted(SKILLS.iterdir()):
        fixture = REPO / "tests" / "fixtures" / skill_dir.name
        if not fixture.exists():
            continue
        work = Path(tempfile.mkdtemp()) / skill_dir.name
        work.mkdir(parents=True)
        try:
            drive_compose(skill_dir.name, fixture, work)
        except Exception:  # pragma: no cover
            continue
        md = work / "report.md"
        if md.exists():
            spans += len(re.findall(r"`([^`\n]+)`", md.read_text(encoding="utf-8")))
    assert spans, "the delivered scan sees no code spans at all -- it can no longer detect anything"


def test_delivered_artifacts_carry_no_de_snaked_code_span() -> None:
    """Fleet scan over every composed report.md.

    Non-vacuous on the committed fixtures with no seeding: ic-sim's verdict legend renders
    `**Decline — Hard Pass** (internal \\`hard_pass\\`)` as `(internal \\`Decline — hard pass\\`)`,
    which destroys the legend's whole purpose — it exists to show the raw token beside the label.
    """
    import re
    import tempfile

    sys.path.insert(0, str(Path(__file__).parent))
    from test_compose_invariants import drive_compose

    code_span = re.compile(r"`([^`\n]+)`")
    hits: list[str] = []
    scanned = 0
    for skill_dir in sorted(SKILLS.iterdir()):
        skill = skill_dir.name
        fixture = REPO / "tests" / "fixtures" / skill
        if not fixture.exists():
            continue
        work = Path(tempfile.mkdtemp()) / skill
        work.mkdir(parents=True)
        try:
            drive_compose(skill, fixture, work)
        except Exception:  # pragma: no cover - a skill that cannot compose is another test's problem
            continue
        md = work / "report.md"
        if not md.exists():
            continue
        # Counted HERE, not after drive_compose: a skill that composes but writes no report.md
        # contributes no evidence, and counting it there let the vacuity guard pass on nothing.
        scanned += 1
        for span in code_span.findall(md.read_text(encoding="utf-8")):
            if _looks_substituted(span):
                hits.append(f"{skill}/report.md: `{span}`")

    # Vacuity FIRST. A partial fixture failure used to surface as "lower the baseline", which reads
    # as an instruction to disarm the detector rather than as evidence the scan saw nothing.
    assert scanned, (
        "no skill composed a report.md, so this scan proved nothing. A skill whose fixture stops "
        "composing drops out of the loop silently; that is a false green, not a pass."
    )
    unexpected = sorted(h for h in hits if h not in _ALLOWED_DELIVERED)
    assert not unexpected, (
        "delivered code span(s) look de-snaked -- the founder is reading a token that does not "
        "exist:\n" + "\n".join(unexpected) + "\n\nEither stop mangling it, or add it to "
        "_ALLOWED_DELIVERED with the reason it is acceptable."
    )
    stale = sorted(k for k in _ALLOWED_DELIVERED if k not in hits)
    assert not stale, (
        "these allowlisted spans no longer occur -- delete them, or the allowlist becomes headroom "
        "nobody is watching:\n" + "\n".join(stale)
    )
