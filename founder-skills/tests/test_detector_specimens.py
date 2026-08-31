"""The five detectors that carry specimens must keep carrying them.

A detector that scans live repo data and asserts "no offenders" proves nothing once the data is
clean -- and clean is the goal. Five of them were measured blind-vacuous in one session: blind the
matcher and the suite stays green. Each was fixed by putting specimens INSIDE the detector, both
directions -- strings that actually shipped must be flagged, live look-alikes must not.

Deleting those specimens is invisible. Nothing else reds: the detector still scans, still passes,
and has silently returned to proving nothing. This is the guard for that.

WHY THIS IS A FIXED LIST AND NOT A SCAN, which is a reversal of the plan that asked for it. That
plan proposed enumerating the detector class by AST and asserting each member names a specimen set,
controlled by a fixed list of the four known members. Every formalisation of that predicate was
measured and none is usable:

  * "reads repo files and asserts a collection empty" -> 108 members
  * "applies a module-level compiled regex to repo text" -> 41 members, of which the heuristic
    reports 38 as lacking specimens INCLUDING three that demonstrably have them, because they reach
    their matcher through a helper function rather than naming it directly

An exemption list covering 38 false gaps is not a guard; it is the same "calibrated on the wrong
thing" failure the class is about, wearing the costume of a fix. So this keeps the half of the
design that works -- the plan's own words for it were "a control that does not itself need a
control, because it compares against a constant rather than searching."

ADDING A DETECTOR TO THIS LIST IS MANUAL, and that is the honest cost of not having a scan.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

# (module, the specimen constants it must keep, the test that must consume them).
# Every entry was verified by breaking it: blinding the matcher reds the named test.
_SPECIMEN_BEARING_DETECTORS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "test_html_founder_text.py",
        ("_TOOLTIP_SPECIMENS_BAD", "_TOOLTIP_SPECIMENS_OK"),
        "test_the_tooltip_signature_catches_what_shipped_and_spares_what_did_not",
    ),
    (
        "test_founder_facing_leaks.py",
        ("_PATH_SPECIMENS_BAD", "_PATH_SPECIMENS_OK"),
        "test_validation_messages_carry_no_json_paths",
    ),
    (
        "test_cap_table_guards.py",
        ("_PROSE_BAD", "_PROSE_OK"),
        "test_the_prose_matchers_catch_what_shipped_and_spare_what_must_survive",
    ),
    (
        "test_skill_contract.py",
        ("_BASHISM_SPECIMENS", "_POSIX_SPECIMENS"),
        "test_the_bashism_patterns_catch_bashisms_and_spare_posix",
    ),
    (
        "test_skill_orchestration.py",
        ("_TASK_SPECIMENS_BAD", "_TASK_SPECIMENS_OK"),
        "test_the_task_pin_detector_catches_an_unpinned_dispatch",
    ),
)


def _module(name: str) -> ast.Module:
    return ast.parse((TESTS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(("module", "constants", "consumer"), _SPECIMEN_BEARING_DETECTORS)
def test_specimen_sets_still_exist_and_are_still_consumed(
    module: str, constants: tuple[str, ...], consumer: str
) -> None:
    """Both halves matter. A specimen set nothing reads is decoration; a test reading a set that has
    been emptied asserts over zero items and passes."""
    tree = _module(module)

    defined: dict[str, int] = {}
    for node in tree.body:
        # The five detectors do not agree on a container type -- tuple, list and dict-of-labelled-
        # specimens are all in use. Requiring one shape would fail a detector that is working, which
        # is how this test's own first draft failed two live rows.
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
            size = len(node.value.keys) if isinstance(node.value, ast.Dict) else len(node.value.elts)
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in constants:
                    defined[target.id] = size

    for name in constants:
        assert name in defined, (
            f"{module} no longer defines {name} at module level. Its detector scans live repo data "
            "and asserts no offenders, which passes trivially once the data is clean -- the "
            "specimens are the only thing that can fail when the matcher rots."
        )
        assert defined[name] > 0, (
            f"{module}::{name} is empty. A loop over an empty specimen set asserts nothing and "
            "reports the same green as a working detector."
        )

    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert consumer in names, (
        f"{module} no longer defines {consumer}, the test that exercises {list(constants)}. The "
        "specimens may still be present and now prove nothing."
    )

    consuming = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == consumer)
    referenced = {n.id for n in ast.walk(consuming) if isinstance(n, ast.Name)}
    missing = [c for c in constants if c not in referenced]
    assert not missing, f"{consumer} no longer reads {missing} -- the specimens are decoration now."


def test_the_registry_has_not_quietly_shrunk() -> None:
    """Shrink-only in the wrong direction is the failure mode: dropping a row silences a detector's
    only control, and nothing else notices. Five is the measured size of the class as of the session
    that closed it. Raise it when a detector gains specimens; never lower it to accommodate one that
    lost them."""
    assert len(_SPECIMEN_BEARING_DETECTORS) >= 5, (
        f"only {len(_SPECIMEN_BEARING_DETECTORS)} specimen-bearing detectors registered (floor 5)"
    )
