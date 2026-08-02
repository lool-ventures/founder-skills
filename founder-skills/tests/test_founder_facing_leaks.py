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
BASELINE = 144


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
