"""Every cap-table `substitute` call site must use the SAME keep set.

`compose_report.py` builds one from `_labels.MAPS` — the skill's own glossary — and passes it to
both `substitute` and `scan`. The other three call sites passed NOTHING, so the very vocabulary
cap-table deliberately glosses was destroyed on those routes: `quick_assess` (the fast-assess
report), `counsel_packet` (the lawyer hand-off), and `_rules.founder_text` (the per-string boundary
feeding `report.html` and `explorer.html`).

The asymmetry is invisible by inspection — each call site reads as "we apply the founder-text
policy here" — and it is why the same token is delivered three different ways in one run.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "cap-table" / "scripts"


def _load(name: str) -> types.ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A token cap-table deliberately glosses: it is a key of `_labels.MAPS`, so `compose_report` keeps it
# verbatim in the small-print parenthetical the md_term convention exists for.
_GLOSSED = "structural_only"


def test_the_shared_keep_helper_exists_and_covers_the_glossary() -> None:
    """One construction, or the sites drift again. `compose_report` built it inline, which is why
    three siblings never got it."""
    ft = _load("_founder_text_keep")
    keep = ft.cap_table_keep()
    labels = _load("_labels")
    for m in labels.MAPS.values():
        for k in m:
            assert k in keep, f"{k} is glossed by _labels but missing from the shared keep set"


def test_glossed_vocabulary_survives_at_every_call_site() -> None:
    """The regression this file exists for. Each of the four sites must deliver `structural_only`
    unchanged; three of them used to hand the founder `structural only`, which matches no field,
    no enum, and nothing the founder could look up."""
    import _founder_text as FT  # type: ignore[import-not-found]

    ft = _load("_founder_text_keep")
    keep = ft.cap_table_keep()
    probe = f"The stage is `{_GLOSSED}` for this run."

    assert FT.substitute(probe, extra_keep=keep) == probe, "the shared keep set does not protect the glossary"
    # And without it — the state the three siblings were in.
    assert FT.substitute(probe) != probe, "probe is vacuous: substitute would not have touched it anyway"


def test_rules_boundary_keeps_the_glossary() -> None:
    """`_rules.founder_text` feeds HTML text nodes, where a mangled token is what the founder reads."""
    rules = _load("_rules")
    probe = f"See `{_GLOSSED}` above."
    assert rules.founder_text(probe) == probe, (
        f"_rules.founder_text mangled the glossary: {rules.founder_text(probe)!r}"
    )


class TestQuickAssessGlossesItsEnums:
    """The fast-assess route renders enums into PROSE, where the keep set is not enough.

    The keep set exists so a token the skill glosses survives verbatim -- correct where the renderer
    then glosses it. `quick_assess` interpolated the completeness enum NAKED into a sentence, so
    giving that site the keep set replaced readable prose with a raw internal token, on the route a
    founder asking a quick question actually lands on. Nothing caught it: the producer ratchet walks
    dict/keyword founder-text values and this is an `md_lines.append(f"...")`, and the delivered
    scan reads `report.md` while this writes `report_fast_assess.md`.
    """

    @staticmethod
    def _line() -> str:
        labels = _load("_labels")
        # The exact construction at the call site, so a change to either side is caught here.
        return f"_Solver could not produce a full answer ({labels.humanize('completeness', 'structural_only')})._"

    def test_the_enum_is_glossed_not_raw(self) -> None:
        line = self._line()
        assert "structural_only" not in line, f"raw internal token reached founder prose: {line!r}"
        assert "Structure only" in line, line

    def test_the_gloss_is_not_nested_parentheses(self) -> None:
        """`md_term` emits `Label (`code`)`, and this site already wraps its value in parentheses
        inside an italic run. Nesting them was measured at 60 chars against 15, and read worse than
        the bare enum it replaced."""
        line = self._line()
        assert line.count("(") == 1 and line.count(")") == 1, f"nested parenthetical: {line!r}"

    def test_the_source_still_uses_humanize_not_md_term(self) -> None:
        src = (SCRIPTS / "quick_assess.py").read_text(encoding="utf-8")
        assert '_labels.humanize("completeness", completeness)' in src, "the call site drifted"
        assert "md_term('completeness'" not in src and 'md_term("completeness"' not in src

    def test_the_labels_import_is_guarded(self) -> None:
        """This function's contract is that a fast answer is worth delivering unpolished rather than
        not at all. An unguarded import here deleted the whole report when `_labels.py` was absent --
        measured against both prior commits, which produced it fine."""
        src = (SCRIPTS / "quick_assess.py").read_text(encoding="utf-8")
        i = src.index("import _labels")
        window = src[max(0, i - 400) : i]
        assert "try:" in window, "the _labels import is not inside a try/except"
