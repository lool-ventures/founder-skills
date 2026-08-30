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
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"

# Dict keys whose values are rendered to a founder verbatim by some producer.
_FOUNDER_TEXT_KEYS = frozenset({"remedy", "reason", "detail", "message", "guidance", "recommendation"})

# MEASURED 2026-08-30 on HEAD 410cf88 + the keep-parity fix, against THIS file's key set. SHRINK ONLY.
#
# Do not inherit this number from anywhere else. An adversarial review of the plan that produced this
# test reported 55 for a WIDER key set; adopting it here would have left 26 slots of silent headroom
# for exactly the defect the ratchet exists to catch. Re-measure when you change `_FOUNDER_TEXT_KEYS`.
_BASELINE = 29


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
                if (
                    isinstance(k, ast.Constant)
                    and k.value in _FOUNDER_TEXT_KEYS
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                    and v.value.strip()
                ):
                    out.append((getattr(v, "lineno", 0), v.value))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if (
                    kw.arg in _FOUNDER_TEXT_KEYS
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                    and kw.value.value.strip()
                ):
                    out.append((getattr(kw.value, "lineno", 0), kw.value.value))
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
        + "\n".join(offenders[_BASELINE:] or offenders[-5:])
    )
    assert len(offenders) >= 0


def test_ratchet_is_not_vacuous() -> None:
    """A detector that finds nothing proves nothing. This class is real and currently populated."""
    assert _offenders(), "the round-trip detector found nothing at all — it has stopped working"


# ------------------------------------------------------------------------------------------------
# The DELIVERED half. The producer ratchet above catches a string whose author and renderer
# disagree; this catches the same defect where it actually reaches a founder, including text no
# producer literal contains (composed at runtime, or assembled from a rule pack).
# ------------------------------------------------------------------------------------------------

_DELIVERED_BASELINE = 1  # MEASURED 2026-08-30: ic-sim's verdict legend. SHRINK ONLY.


def _looks_substituted(span: str) -> bool:
    """True when a backticked span looks like a snake_case token that has been de-snaked.

    A code span the author wrote is a literal: `pre_money`, `report.json`, `--flag`. A span reading
    `pre money` is one substitute got to. The test is round-trip: re-snake it, humanize it, and see
    if you land back on what is rendered.
    """
    ft = _founder_text()
    if " " not in span.strip() or "`" in span:
        return False
    candidate = span.strip().replace(" ", "_").lower()
    return bool(str(ft.humanize_token(candidate)).lower() == span.strip().lower())


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
        for span in code_span.findall(md.read_text(encoding="utf-8")):
            if _looks_substituted(span):
                hits.append(f"{skill}/report.md: `{span}`")

    assert len(hits) <= _DELIVERED_BASELINE, (
        f"{len(hits)} delivered code span(s) look de-snaked (baseline {_DELIVERED_BASELINE}). The "
        f"founder is reading a token that does not exist:\n" + "\n".join(hits)
    )
