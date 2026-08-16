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
    """The quote is what the second read is checked against."""
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


def test_rejects_a_value_that_drops_precision_the_raw_string_carries() -> None:
    """The deck-H defect: `raw: "16661.2"` recorded as `value: 16661`.

    A 0.0012% discrepancy, invisible to any relative floor — and it does real damage
    downstream. That lost 0.2 moved a sum 0.54 off its stated total against a tolerance of
    0.555, and a founder was told their revenue disagreed with itself by 1 part in 17,772.

    A figure printed to six significant figures is a claim to six significant figures, so
    `value` must match `raw` to `raw`'s own precision and no looser.
    """
    rc, _, err = _run(
        {"figures": [_fig(id="rev_mix", value=16661, raw="16661.2", quote="Subscription revenue 16661.2")]}
    )
    assert rc != 0
    assert "disagrees with raw" in err


def test_an_exact_match_on_a_precise_raw_is_accepted() -> None:
    """The counter-test: the rule must be satisfiable, not merely strict."""
    rc, _, err = _run(
        {"figures": [_fig(id="rev_mix", value=16661.2, raw="16661.2", quote="Subscription revenue 16661.2")]}
    )
    assert rc == 0, err


def test_a_coarse_raw_still_tolerates_the_rounding_it_implies() -> None:
    """Removing the floor must not make a genuinely rounded slide figure a failure.

    "$1.2M" claims two significant figures and legitimately covers 1.15M-1.25M — the
    significant-figure band already expresses that, which is why no floor is needed.
    """
    rc, _, err = _run({"figures": [_fig(value=1_238_400, raw="$1.2M", quote="$1.2M in bookings")]})
    assert rc == 0, err
    rc, _, err = _run({"figures": [_fig(id="c", value=97, raw="100", unit_kind="count", quote="about 100 users")]})
    assert rc == 0, err


def test_a_unit_suffix_is_not_reported_as_a_scale_error() -> None:
    """ "200-400m" of building height, recorded as 200, is CORRECT extraction.

    The old message told the model to "record the figure at full scale", which for a
    200-metre tower means 200,000,000. The code cannot decide this — "32.5m businesses"
    recorded as 32.5 (a genuine scale error) is structurally identical — so it stops
    pretending to and tells the model how to disambiguate instead.
    """
    fig = _fig(
        id="h",
        value=200,
        raw="200-400m",
        unit_kind="count",
        label="tower height range (metres)",
        quote="towers of 200-400m",
    )
    del fig["currency"]  # a height is not money; the default helper supplies one
    rc, _, err = _run({"figures": [fig]})
    assert rc != 0
    assert "ambiguous" in err and "spell it out" in err
    assert "record the figure at full scale" not in err.split("ambiguous")[1]


def test_spelling_the_unit_out_resolves_it() -> None:
    """The escape hatch has to work, or the message sends the model in a circle."""
    fig = _fig(
        id="h",
        value=200,
        raw="200-400 metres",
        unit_kind="count",
        label="tower height range",
        quote="towers of 200-400 metres",
    )
    del fig["currency"]
    rc, _, err = _run({"figures": [fig]})
    assert rc == 0, err


def test_a_currency_marker_still_means_the_suffix_is_a_multiplier() -> None:
    """Money is never ambiguous: "$493K" is thousands, so 493 stays a scale error."""
    rc, _, err = _run({"figures": [_fig(value=493, raw="$493K")]})
    assert rc != 0
    assert "full scale" in err
    assert "ambiguous" not in err
