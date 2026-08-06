"""Regression ratchet for founder-facing "internal plumbing" leaks.

The 6 SKILL.md files carry a class-based communication rule ("never surface
file/script names, `*.py`, `--flags`, `$vars`, exit codes, `W_`/`E_` codes, JSON,
or step/route labels — narrate in the founder's own words"). This test measures
whether the recorded cassettes actually keep those tokens out of the founder-
visible assistant narration, using the shared detector (`cowork-tests/leak_scan.py`).

It is a RATCHET, not a pass/fail on zero: the committed cassettes were recorded
against the pre-rule skills and carry a base rate of leaks, and a re-record is
currently held (baseline skew). So the gate is "no NEW leaks beyond the recorded
baseline". When cassettes are re-recorded against the fixed skills the count drops
— lower `BASELINE` to the new total at that time (ratchet down, never up).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CASSETTES = _REPO_ROOT / "cowork-tests" / "cassettes"
sys.path.insert(0, str(_REPO_ROOT / "cowork-tests"))

# Base rate measured 2026-07-16 against the pre-rule cassettes. Ratchet DOWN after
# any re-record against the class-based communication rule; never raise it.
# 144 was measured over nine syntactic classes. A tenth — `plumbing_verb`, the
# semantic class — was added after it recurred in two skills and survived three
# prose fixes; it contributes 13, and the ten-class total is 61, still far under.
# Ratchet DOWN as narration improves; never up.
# Ratcheted 144 -> 64 on 2026-08-04, and NOT because the cassettes improved: `leak_scan.py` gained
# two precision filters. It now excludes sub-agent narration (an event carrying
# `parent_tool_use_id` — no founder ever sees it) and can scope to one turn. Counting sub-agent text
# was measuring a population the founder is not exposed to.
#
# Ratcheting down locks the precision win in, per this file's own rule. If a future re-record raises
# the number, that is a real regression in the recorded narration, not a reason to raise this back.
BASELINE = 55


pytestmark = pytest.mark.skipif(
    not _CASSETTES.exists() or not any(_CASSETTES.glob("*.cassette.json")),
    reason="no committed cassettes to scan",
)


def _total_leaks() -> tuple[int, dict[str, int]]:
    import leak_scan  # type: ignore[import-not-found]  # from cowork-tests/ (added to sys.path above)

    per_file: dict[str, int] = {}
    for cass in sorted(_CASSETTES.glob("*.cassette.json")):
        per_file[cass.name] = len(leak_scan.scan_cassette(cass))
    return sum(per_file.values()), per_file


def test_no_new_founder_facing_leaks() -> None:
    total, per_file = _total_leaks()
    assert total <= BASELINE, (
        f"Founder-facing plumbing leaks rose to {total} (baseline {BASELINE}). "
        f"A skill change surfaced new internal tokens to the founder. Run "
        f"`python3 cowork-tests/leak_scan.py cowork-tests/cassettes/ --show` to see them, "
        f"and fix the SKILL.md narration (class-based rule at each file's ~line 100-166). "
        f"Per-file: { {k: v for k, v in sorted(per_file.items(), key=lambda kv: -kv[1]) if v} }"
    )


def test_detector_finds_the_known_leak_classes() -> None:
    """Guard the detector itself: a crafted plumbing string must trip it."""
    import leak_scan

    sample = "Exit 1 (not found). Running `extract_cap_table.py --mode=grid`; W_CAP_BASE_ASSUMED."
    classes = {c for c, _ in leak_scan.scan_text(sample)}
    for expected in ("exit_code", "code_span", "route_label", "warn_err_code"):
        assert expected in classes, f"detector missed {expected} in: {sample!r}"


# ---------------------------------------------------------------------------
# The detector's own precision. It is now the instrument for a before/after
# narration measurement, so its filters need their own tests: an instrument that
# silently counts the wrong population produces a threshold nobody can trust.
# ---------------------------------------------------------------------------


def _events(*evs: dict) -> dict:
    import json as _json

    return {"events": [_json.dumps(e) for e in evs]}


def _assistant(text: str, *, parent: str | None = None, kind: str = "assistant") -> dict:
    e: dict = {"type": kind, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if parent:
        e["parent_tool_use_id"] = parent
    return e


def test_subagent_text_is_not_founder_visible() -> None:
    """A sub-agent's own narration never reaches the founder, so it must not be counted.

    Measured: counting it inflated one run from 9 leak-bearing top-level blocks to 78 raw hits.
    """
    import leak_scan

    top = leak_scan.founder_text_blocks(_events(_assistant("Gating the hand-off.")))
    sub = leak_scan.founder_text_blocks(_events(_assistant("Gating the hand-off.", parent="toolu_1")))
    assert len(top) == 1
    assert sub == [], "sub-agent text must be excluded from the founder-visible population"


def test_turn_scoping_separates_a_reflection_turn() -> None:
    """A `critique` run's reflection turn is ASKED to discuss internals, so leaks there are correct
    behaviour. Comparing raw totals across a critique run and a scenario run compares different
    things; `turn=1` scopes to the graded task turn."""
    import leak_scan

    init = {"type": "system", "subtype": "init"}
    cassette = _events(
        init,
        _assistant("Now dispatching the sub-agents."),
        init,
        _assistant("The COMPETITOR_RECALL dispatch confused me."),
    )
    turn1 = leak_scan.founder_text_blocks(cassette, turn=1)
    turn2 = leak_scan.founder_text_blocks(cassette, turn=2)
    both = leak_scan.founder_text_blocks(cassette)
    assert len(turn1) == 1 and "dispatching" in turn1[0]
    assert len(turn2) == 1 and "COMPETITOR_RECALL" in turn2[0]
    assert len(both) == 2, "turn=None keeps every turn, which is right for a single-turn cassette"


def test_block_stats_reports_a_ratio_not_just_hits() -> None:
    """The block RATIO is what compares across runs — one verbose block can carry many hits, which
    is exactly how a 78-hit total came from 10 blocks."""
    import json as _json
    import tempfile

    import leak_scan

    cassette = _events(
        _assistant("Gating the hand-off and piping through the producer and dispatching Step 3.5."),
        _assistant("Your competitor set looks solid."),
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump(cassette, f)
        path = Path(f.name)
    leak_blocks, total_blocks = leak_scan.block_stats(path)
    hits = len(leak_scan.scan_cassette(path))
    path.unlink()
    assert (leak_blocks, total_blocks) == (1, 2)
    assert hits > leak_blocks, "one block carried several hits — which is why the ratio is the metric"
