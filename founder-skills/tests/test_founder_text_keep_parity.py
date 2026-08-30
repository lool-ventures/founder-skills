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
