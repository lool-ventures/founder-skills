"""`_handover_check.contained`: the one containment rule the e2e lane and the Stop hook share."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_handover_check.py"
_spec = importlib.util.spec_from_file_location("_handover_check", _PATH)
assert _spec is not None and _spec.loader is not None
hc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hc)

PRINTED = (
    "Here's your finished market sizing: [the written report](computer:///a/b/X.md) — it opens with the verdict.\n"
    "\n"
    "Your materials state TAM $80.0B; this analysis finds $7.0B (top-down) and $99.9B § (bottom-up). "
    "Self-check: 100% (22/22 pass, 0 fail, 0 N/A)\n"
    "(§ built on a figure you stated that a cited source contradicts.)\n"
    "\n"
    "If you want to keep the working data behind this — say so and I'll send it as a single archive.\n"
)


def test_verbatim_passes() -> None:
    assert hc.contained(PRINTED, PRINTED) == (True, "")


def test_greeting_and_relinking_pass() -> None:
    """A digit-free greeting before it, and the other runtime's link for the same file, are fine."""
    final = "Done!\n\n" + PRINTED.replace("computer:///a/b/X.md", "/Users/x/outputs/X.md") + "\nAnything else?"
    assert hc.contained(PRINTED, final) == (True, "")


def test_reindented_passes() -> None:
    assert hc.contained(PRINTED, "  " + PRINTED.replace("\n", "\n   "))[0]


def test_added_figure_fails_and_names_it() -> None:
    ok, why = hc.contained(PRINTED, PRINTED + "\nThat is about 2% of the illustrative $100M.")
    assert not ok and "figure" in why and "2%" in why


def test_added_verdict_before_it_fails() -> None:
    final = "1. TAM: your $80B vs our $7B.\n2. Recommendation: revisit.\n\n" + PRINTED
    ok, why = hc.contained(PRINTED, final)
    assert not ok and "figure" in why


def test_dropped_line_fails() -> None:
    """Deletion is what a digit check cannot see; the hostloop run dropped a digit-free sentence."""
    final = PRINTED.replace("(§ built on a figure you stated that a cited source contradicts.)\n", "")
    assert hc.contained(PRINTED, final) == (False, "the printed hand-over was not sent whole")


def test_reworded_sentence_fails() -> None:
    final = PRINTED.replace("this analysis finds", "our analysis found")
    assert not hc.contained(PRINTED, final)[0]


def test_reordered_fails() -> None:
    paras = PRINTED.strip().split("\n\n")
    assert not hc.contained(PRINTED, "\n\n".join([paras[1], paras[0], paras[2]]))[0]


@pytest.mark.parametrize("final", ["", "Here's your finished market sizing."])
def test_missing_fails(final: str) -> None:
    assert not hc.contained(PRINTED, final)[0]


def test_empty_printed_never_passes() -> None:
    assert hc.contained("", "anything") == (False, "the printed hand-over is empty")
