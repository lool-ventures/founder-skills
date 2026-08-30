"""Assertions over the curated mutant corpus. The registry and harness live in `mutation_corpus.py`.

That module is deliberately NOT a `test_*.py` file -- read its docstring before moving anything back
here: its mutants quote error-code literals verbatim, and inside a scanned test file those payloads
make `test_cap_table_guards.py`'s ratchets count a diagnostic as guarded that this corpus is
simultaneously recording as unguarded.

Everything here carries the `mutation` marker and is deselected from the default suite by `addopts`.
A command-line `-m` OVERRIDES `addopts`, so an explicit `-m "not e2e"` re-selects this lane; the CI
gates and `scripts/pre-tag.sh` say `-m "not e2e and not mutation"` for that reason.
"""

from __future__ import annotations

import shutil

import pytest
from mutation_corpus import (
    _ALL,
    _COPY_DIRS,
    _COPY_FILES,
    _IGNORE,
    KNOWN_SURVIVORS,
    MUST_KILL,
    NO_OP,
    REPO_ROOT,
    Mutant,
    _Harness,
)

pytestmark = pytest.mark.mutation


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> _Harness:
    """Build the sandbox and PROVE it works before any verdict is read from it."""
    tree = tmp_path_factory.mktemp("mutation-corpus")
    for name in _COPY_DIRS:
        shutil.copytree(REPO_ROOT / name, tree / name, ignore=_IGNORE)
    for name in _COPY_FILES:
        shutil.copy2(REPO_ROOT / name, tree / name)

    h = _Harness(tree)
    control = h.verdict(NO_OP)
    if control.killed:
        pytest.fail(
            "THE NO-OP CONTROL FAILED, so every verdict in this file is void: a comment-only change "
            "left the selection failing.\n"
            f"  first failure: {control.first_failure or '(see tail)'}\n"
            "THREE CAUSES, DIFFERENT RESPONSES -- check the named test before assuming any of them. "
            "(1) The harness is broken: a bad copy, an unresolvable path, a pytest invocation "
            "erroring for its own reasons. (2) The selection is ALREADY RED on the working tree, in "
            "which case nothing here is wrong and the corpus simply cannot issue a verdict against a "
            "baseline that is not green. (3) A file was added to `_SELECTION` that needs a repo root "
            "`_COPY_DIRS`/`_COPY_FILES` does not copy -- that reads as (1) and is not; the fix is to "
            "add the root, not to debug the harness.\n"
            f"{control.tail}"
        )
    return h


def test_noop_control_leaves_the_selection_passing(harness: _Harness) -> None:
    """The instrument check, stated as its own test so a broken harness is legible in the report.

    The fixture already enforces it -- this exists so the corpus never reports a bare green with no
    evidence that the thing producing it can distinguish success from failure at all.
    """
    verdict = harness.verdict(NO_OP)
    assert not verdict.killed, verdict.tail


@pytest.mark.parametrize("mutant", MUST_KILL, ids=lambda m: m.id)
def test_must_kill_mutant_is_caught(harness: _Harness, mutant: Mutant) -> None:
    verdict = harness.verdict(mutant)
    assert verdict.killed, (
        f"MUTANT SURVIVES: {mutant.id}\n"
        f"  {mutant.file}\n"
        f"  {mutant.rationale}\n"
        "This defect was caught by the suite when the corpus was written and is not caught now. "
        "Either a test that guarded it was weakened, or the guard itself moved. Restore the "
        "assertion -- do not move the entry to KNOWN_SURVIVORS, which is shrink-only.\n"
        f"{verdict.tail}"
    )
    if mutant.killed_by:
        assert mutant.killed_by in verdict.first_failure, (
            f"{mutant.id} was killed, but not by the test it names.\n"
            f"  expected: {mutant.killed_by}\n"
            f"  actual:   {verdict.first_failure or '(no FAILED line)'}\n"
            "A kill by something else is not evidence that the guard works -- it is the false-kill "
            "class this corpus has already hit twice. Either the guard stopped noticing and an "
            "unrelated test is now failing, or the expectation is stale."
        )


@pytest.mark.parametrize("mutant", KNOWN_SURVIVORS, ids=lambda m: m.id)
def test_known_survivor_is_still_unguarded(harness: _Harness, mutant: Mutant) -> None:
    """The recorded-debt half. Failing here is GOOD NEWS and says so."""
    verdict = harness.verdict(mutant)
    if verdict.killed:
        pytest.fail(
            f"GOOD NEWS -- a recorded survivor is now killed: {mutant.id}\n"
            f"  {mutant.file}\n"
            f"  caught by: {verdict.first_failure or '(see tail)'}\n"
            "Move it from KNOWN_SURVIVORS to MUST_KILL to lock the win in. The survivor list is "
            "shrink-only: leaving it here would claim the defect is unguarded when it is.\n"
            f"{verdict.tail}"
        )


def test_every_entry_is_uniquely_named() -> None:
    """Ids are the review surface: two entries sharing one make a parametrized report ambiguous."""
    ids = [m.id for m in (NO_OP, *_ALL)]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def test_every_entry_anchors_on_text_that_exists_exactly_once() -> None:
    """Cheap and token-free: catches a rotted anchor without running a single child pytest.

    The expensive tests assert this too, but only after paying for a run each. This one fails in
    milliseconds and names every rotted entry at once instead of stopping at the first.
    """
    rotted: list[str] = []
    for mutant in (NO_OP, *_ALL):
        path = REPO_ROOT / mutant.file
        if not path.exists():
            rotted.append(f"{mutant.id}: {mutant.file} does not exist")
            continue
        count = path.read_text(encoding="utf-8").count(mutant.find)
        if count != 1:
            rotted.append(f"{mutant.id}: anchor occurs {count}x in {mutant.file}")
    assert not rotted, "mutant anchors no longer match the source:\n  " + "\n  ".join(rotted)


def test_a_mutant_actually_changes_the_source() -> None:
    """A find identical to its replace would be a second no-op masquerading as a mutant.

    It would pass in KNOWN_SURVIVORS forever and never test anything, which is the exact vacuity the
    no-op control exists to expose in the harness -- worth blocking in the registry too.
    """
    inert = [m.id for m in _ALL if m.find == m.replace]
    assert not inert, f"these entries mutate nothing: {inert}"


def test_no_mutant_payload_lives_in_this_scanned_test_file() -> None:
    """The split from `mutation_corpus.py` must stay split.

    `test_cap_table_guards.py`'s two ratchets scan `tests/test_*.py` by bare substring to answer
    "does any test name this diagnostic / rule_id". A mutant payload has to quote the source text it
    patches verbatim, so moving one back into this file would make the ratchet count a code as
    guarded that this corpus records as UNGUARDED -- the two guards then contradict each other and
    the corpus's claim is the one silently overruled.

    Measured, not theorised: the first draft of this corpus lived in one file and dropped
    `test_error_code_assertion_ratchet` below its baseline on exactly one code.
    """
    # SCANS EVERY `test_*.py`, not just this one. Keying the guard on a single filename would let
    # the registry be moved to `test_mutation_registry.py` with the guard still green -- the
    # property is "no payload sits in the namespace the ratchets glob", and the ratchets glob all
    # of them. The only signal would otherwise be the ratchet's own "good news, lower the baseline"
    # message, and following that instruction produces exactly the contradiction described above.
    leaked: list[str] = []
    for path in sorted((REPO_ROOT / "founder-skills" / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for mutant in (NO_OP, *_ALL):
            # An empty `replace` (a deletion mutant) is a substring of everything; it carries no
            # vocabulary and cannot pollute anything.
            for payload in (mutant.find, mutant.replace):
                if payload and payload in text:
                    leaked.append(f"{mutant.id} -> {path.name}")
    assert not leaked, (
        "these mutant payloads are inside a file the guards ratchets scan, which makes them read as "
        f"assertions: {sorted(set(leaked))}. Keep the registry in mutation_corpus.py."
    )


def test_noop_control_still_passes_after_every_mutant(harness: _Harness) -> None:
    """Re-establish the instrument AFTER the verdicts, not only before them.

    The module-scoped fixture proves the harness worked when it was built. Nothing proved it still
    worked when the last verdict was read, and every mechanism that could degrade it mid-run --
    a revert that silently no-ops, state the child leaves in the sandbox, a file handle -- degrades
    it in the direction that makes `MUST_KILL` entries pass and survivors look guarded.

    Definition order is load-bearing: this must run last, which holds because pytest collects a
    module in definition order and no shuffling plugin is installed (`pytest-randomly` is absent --
    if one is ever added, this needs an explicit ordering).
    """
    verdict = harness.verdict(NO_OP)
    assert not verdict.killed, (
        "the no-op control passed before the corpus ran and fails after it. Every verdict above was "
        "read from an instrument that stopped working at some point during the run, so none of them "
        f"can be trusted.\n{verdict.tail}"
    )
