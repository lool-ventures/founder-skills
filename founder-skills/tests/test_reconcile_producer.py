#!/usr/bin/env python3
"""`reconcile.py`'s producer layer — the gate, the statuses, and what escapes to a founder.

`test_reconcile.py` covers the engine: tolerances, unit algebra, the convention classes.
This file covers what the engine is wrapped in — which figures are trusted, which of the
three statuses is reported, and above all the rule that only `select()` decides what a
founder sees.
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
SCRIPT = os.path.join(SCRIPTS, "reconcile.py")

_LEDGER = {
    "figures": [
        {
            "id": "gross_volume",
            "value": 493000,
            "raw": "$493K",
            "unit_kind": "money",
            "label": "GMV 2024",
            "slide": 6,
            "quote": "GMV of $493K in 2024",
            "currency": "USD",
            "period": "year",
        },
        {
            "id": "net_revenue",
            "value": 9000,
            "raw": "$9K",
            "unit_kind": "money",
            "label": "net revenue 2024",
            "slide": 6,
            "quote": "net revenue of $9K",
            "currency": "USD",
            "period": "year",
        },
        {
            "id": "stated_take_rate",
            "value": 6.2,
            "raw": "6.2%",
            "unit_kind": "percent",
            "label": "take rate",
            "slide": 6,
            "quote": "our take rate is 6.2%",
        },
    ]
}

_TRANSCRIPT = "Slide 6: GMV of $493K in 2024. We report net revenue of $9K, and our take rate is 6.2%."

_TAKE_RATE_RELATION = {
    "kind": "derived_ratio",
    "operator": "ratio",
    "operands": ["net_revenue", "gross_volume"],
    "expected_id": "stated_take_rate",
}


def _run(
    relations: list[dict],
    *,
    ledger: dict | None = None,
    transcript: str | None = None,
    slides: list | None = None,
    inventory: dict | None = None,
) -> tuple[int, dict, str]:
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "ledger.json")
        sp = os.path.join(d, "second.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_LEDGER if ledger is None else ledger, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "transcript": _TRANSCRIPT if transcript is None else transcript,
                    "slides_transcribed": [6] if slides is None else slides,
                },
                f,
            )
        args = [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"]
        if inventory is not None:
            ip = os.path.join(d, "deck_inventory.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inventory, f)
            args += ["--inventory", ip]
        res = subprocess.run(args, input=json.dumps({"relations": relations}), capture_output=True, text=True)
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr


# ---------------------------------------------------------------------------
# The flagship shape: a computed figure disagreeing with one the deck itself states.
# That is what makes a contradiction ESTABLISHED rather than judged.
# ---------------------------------------------------------------------------


def test_a_computed_figure_disagreeing_with_a_stated_one_is_a_contradiction() -> None:
    rc, out, err = _run([_TAKE_RATE_RELATION])
    assert rc == 0, err
    assert out["status"] == "checked"
    kinds = [r["verdict"] for r in out["relations"]]
    assert "contradiction" in kinds
    rendered = out["relations"][0]["rendered"]
    assert "6.2%" in rendered and "1.8%" in rendered


def test_both_sides_of_a_finding_render_in_the_same_number_space() -> None:
    """A founder must never be shown two numbers that look 1000x apart and are not.

    A cashflow table denominated in thousands otherwise renders as
    "= -19,393,000 — but the deck states (19,391)".
    """
    rc, out, err = _run([_TAKE_RATE_RELATION])
    assert rc == 0, err
    rendered = out["relations"][0]["rendered"]
    assert "493" in rendered


# ---------------------------------------------------------------------------
# The gate. A figure the independent read cannot corroborate is not merely low
# confidence — it is dropped, and so is anything resting on it.
# ---------------------------------------------------------------------------


def test_a_figure_absent_from_the_second_read_takes_its_relation_with_it() -> None:
    rc, out, err = _run([_TAKE_RATE_RELATION], transcript="Slide 6: some words that quote nothing at all.")
    assert rc == 0, err
    assert out["figures_verified"] == 0
    assert out["status"] == "gate_failed"
    assert out["relations"] == []


def test_coverage_records_a_slide_the_second_read_never_looked_at() -> None:
    """A figure can fail the gate because it was invented, or because nobody looked.

    Only one of those is the deck's problem, and the gate alone cannot tell them apart.
    """
    rc, out, err = _run([_TAKE_RATE_RELATION], slides=[6, 7])
    assert rc == 0, err
    ledger_with_slide_9 = json.loads(json.dumps(_LEDGER))
    ledger_with_slide_9["figures"][0]["slide"] = 9
    rc, out, err = _run([_TAKE_RATE_RELATION], ledger=ledger_with_slide_9, slides=[6])
    assert rc == 0, err
    assert out["second_read_coverage"]["slides_missing"] == [9]


# ---------------------------------------------------------------------------
# Status. Absence of the artifact means the chain did not run; these three all mean
# it ran, and the distinction is the whole reason the field exists.
# ---------------------------------------------------------------------------


def test_a_deck_with_nothing_to_relate_reports_no_figures() -> None:
    rc, out, err = _run([], ledger={"figures": []})
    assert rc == 0, err
    assert out["status"] == "no_figures"


def test_no_figures_is_refused_on_a_deck_plainly_full_of_numbers() -> None:
    """The cheapest way to skip this whole chain is to return an empty ledger.

    An empty ledger is indistinguishable from a genuinely wordless deck unless something
    else has looked at the deck — which is what `--inventory` is for.
    """
    numeral_rich = {
        "slides": [
            {"summary": "ARR 1200000 growth 340 percent 2024 2025 45 customers 89 NPS 12 months"} for _ in range(8)
        ]
    }
    rc, out, err = _run([], ledger={"figures": []}, inventory=numeral_rich)
    assert rc != 0
    assert "numerals" in err


def test_no_figures_is_accepted_on_a_deck_that_really_has_none() -> None:
    wordless = {"slides": [{"summary": "We believe in a better way to work."} for _ in range(8)]}
    rc, out, err = _run([], ledger={"figures": []}, inventory=wordless)
    assert rc == 0, err
    assert out["status"] == "no_figures"


# ---------------------------------------------------------------------------
# select() is the only thing entitled to decide what a founder sees. These two tests
# are what stop a later renderer from reaching past it.
# ---------------------------------------------------------------------------


def test_suppressed_relations_are_reported_as_counts_and_never_as_content() -> None:
    confirming = {
        "kind": "derived_ratio",
        "operator": "ratio",
        "operands": ["net_revenue", "gross_volume"],
    }
    rc, out, err = _run([confirming, _TAKE_RATE_RELATION])
    assert rc == 0, err
    assert isinstance(out["suppressed"], dict)
    for value in out["suppressed"].values():
        assert isinstance(value, int)
    serialized = json.dumps(out["suppressed"])
    assert "rendered" not in serialized


def test_no_convention_differs_relation_ever_reaches_the_relations_array() -> None:
    """A convention difference is an interpretation difference, and the scope rule is
    "material, and not open to interpretations". It is suppressed, not relabelled."""
    rc, out, err = _run([_TAKE_RATE_RELATION])
    assert rc == 0, err
    assert all(r["verdict"] != "convention_differs" for r in out["relations"])


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


def test_a_rate_never_names_its_unit_with_an_internal_enum() -> None:
    """ "per count" is a token from our own vocabulary in front of a founder.

    All three cases here are real corpus lines. The middle one is why the label is used
    unaltered rather than singularised: a trailing-"s" rule turned "businesses in the
    United States" into "businesses in the United State".
    """
    sys.path.insert(0, SCRIPTS)
    from reconcile import (  # type: ignore[import-not-found]  # noqa: PLC0415
        COUNT,
        DURATION,
        Figure,
        _denominator_noun,
    )

    def fig(unit_kind: str, label: str, raw: str) -> Figure:
        return Figure(id="d", value=1, raw=raw, unit_kind=unit_kind, label=label, slide=1, quote="q")

    assert _denominator_noun(fig(COUNT, "Standard customers", "52")) == "Standard customers"
    assert _denominator_noun(fig(COUNT, "businesses in the United States", "32.5 million")) == (
        "businesses in the United States"
    )
    # A duration is named by its time unit, not its label: "$4M over 3 years" is per
    # YEAR, and "per payback period high end" is both unreadable and wrong.
    assert _denominator_noun(fig(DURATION, "payback period high end", "3 years")) == "year"
    # Fallback for a figure with no label is a word, never the enum.
    assert _denominator_noun(fig(COUNT, "", "52")) == "unit"


def test_rejects_a_relations_payload_that_is_not_an_array() -> None:
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "ledger.json")
        sp = os.path.join(d, "second.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_LEDGER, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _TRANSCRIPT, "slides_transcribed": [6]}, f)
        res = subprocess.run(
            [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"],
            input='{"relations": "ratio"}',
            capture_output=True,
            text=True,
        )
    assert res.returncode != 0
    assert "must be an array" in res.stderr
