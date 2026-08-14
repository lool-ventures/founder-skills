#!/usr/bin/env python3
"""`ledger.py` — the extraction-side validation of the deck's numeric ledger.

The checks worth testing are the ones that catch a plausible-looking ledger, not the ones
that catch garbage. A missing key is obvious; a figure recorded as 493 when the slide says
"$493K" looks completely normal and makes every downstream calculation wrong by a factor
of a thousand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
)
SCRIPT = os.path.join(SCRIPTS, "ledger.py")


def _fig(**over: object) -> dict:
    base = {
        "id": "gmv_2024",
        "value": 493000,
        "raw": "$493K",
        "unit_kind": "money",
        "label": "GMV 2024",
        "slide": 6,
        "quote": "GMV of $493K in 2024",
        "currency": "USD",
        "period": "year",
    }
    base.update(over)
    return base


def _run(payload: dict, extra: list[str] | None = None) -> tuple[int, str, str]:
    res = subprocess.run(
        [sys.executable, SCRIPT, "--run-id", "r1", *(extra or [])],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


def test_accepts_a_well_formed_ledger() -> None:
    rc, out, err = _run({"figures": [_fig(), _fig(id="rev", value=9000, raw="$9K", quote="net revenue of $9K")]})
    assert rc == 0, err
    assert json.loads(out)["validation"]["status"] == "valid"


# ---------------------------------------------------------------------------
# The scale check. `raw` and `value` are two independent statements about the same
# number, so their disagreement is detectable without ever seeing the deck — which is
# what makes this a validation rather than a second opinion.
# ---------------------------------------------------------------------------


def test_rejects_value_a_thousand_times_too_small() -> None:
    rc, _, err = _run({"figures": [_fig(value=493)]})
    assert rc != 0
    assert "full scale" in err


def test_rejects_value_a_thousand_times_too_large() -> None:
    rc, _, err = _run({"figures": [_fig(value=493_000_000)]})
    assert rc != 0
    assert "disagrees with raw" in err


def test_tolerates_the_rounding_a_slide_actually_does() -> None:
    """ "$1.2M" for 1,238,400 is a correct extraction of a rounded slide figure.

    An exact-match rule would reject it, which is why the check has a tolerance at all —
    but the tolerance is far tighter than the error class it guards against.
    """
    rc, _, err = _run({"figures": [_fig(value=1_238_400, raw="$1.2M", quote="$1.2M in bookings")]})
    assert rc == 0, err


def test_scale_check_survives_a_raw_string_with_no_scale_suffix() -> None:
    rc, _, err = _run({"figures": [_fig(id="seats", value=120, raw="120", unit_kind="count", quote="120 seats")]})
    assert rc == 0, err


# ---------------------------------------------------------------------------
# Structural refusals
# ---------------------------------------------------------------------------


def test_rejects_duplicate_ids() -> None:
    """Relations address figures by id, so a duplicate silently redirects an operand."""
    rc, _, err = _run({"figures": [_fig(), _fig(value=9000, raw="$9K", quote="net revenue of $9K")]})
    assert rc != 0
    assert "duplicates id" in err


def test_rejects_a_figure_with_no_quote() -> None:
    """The quote is what the independent second read is checked against."""
    rc, _, err = _run({"figures": [_fig(quote="")]})
    assert rc != 0
    assert "quote" in err


def test_rejects_an_unknown_unit_kind() -> None:
    rc, _, err = _run({"figures": [_fig(unit_kind="dollars")]})
    assert rc != 0
    assert "unit_kind" in err


def test_rejects_a_slide_past_the_end_of_the_deck() -> None:
    with tempfile.TemporaryDirectory() as d:
        inv = os.path.join(d, "deck_inventory.json")
        with open(inv, "w", encoding="utf-8") as f:
            json.dump({"slides": [{"slide_number": n} for n in range(1, 9)]}, f)
        rc, _, err = _run({"figures": [_fig(slide=42)]}, ["--inventory", inv])
    assert rc != 0
    assert "past the deck's last slide" in err


def test_warns_but_accepts_money_with_no_currency() -> None:
    """A warning, not a refusal: the relation that needs it is refused later, by name."""
    fig = _fig()
    del fig["currency"]
    rc, out, err = _run({"figures": [fig]})
    assert rc == 0, err
    assert any("currency" in w for w in json.loads(out)["validation"]["warnings"])
