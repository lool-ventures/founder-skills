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
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

import pytest

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
            "raw": "5.4%",
            "unit_kind": "percent",
            "label": "take rate",
            "slide": 6,
            "quote": "our take rate is 5.4%",
        },
    ]
}

_TRANSCRIPT = "Slide 6: GMV of $493K in 2024. We report net revenue of $9K, and our take rate is 5.4%."

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
    assert "5.4%" in rendered and "1.8%" in rendered


def test_both_sides_of_a_finding_render_in_the_same_number_space() -> None:
    """A founder must never be shown two numbers that look 1000x apart and are not.

    A cashflow table denominated in thousands otherwise renders as
    "= -19,341,000 — but the deck states (19,339)".
    """
    rc, out, err = _run([_TAKE_RATE_RELATION])
    assert rc == 0, err
    rendered = out["relations"][0]["rendered"]
    assert "493" in rendered


# ---------------------------------------------------------------------------
# The gate. A figure the second read cannot corroborate is not merely low
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
    # `content_summary`, which is what the schema requires and what production writes. This
    # fixture said `summary` — a key no inventory has — so it exercised a branch that never
    # runs and the fuse was inert on every real deck while this test stayed green.
    numeral_rich = {
        "slides": [
            {
                "slide_number": n,
                "content_summary": "ARR 1200000 growth 340 percent 2024 2025 45 customers 89 NPS 12 months",
            }
            for n in range(1, 9)
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


# ---------------------------------------------------------------------------
# The interpretation pass (Phase 3). Demote-only, closed class set, and every
# withdrawal recorded — because a suppression with no stated ground cannot be
# audited after the fact.
# ---------------------------------------------------------------------------


def _downgrade(**over: object) -> dict:
    base: dict[str, object] = {
        "operator": "ratio",
        "operands": ["net_revenue", "gross_volume"],
        "expected_id": "stated_take_rate",
        "class": "partial_enumeration",
        "reason": "the deck never claimed the listed components were the whole of it",
    }
    base.update(over)
    return base


def _run_with(downgrades: list[dict]) -> tuple[int, dict, str]:
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "ledger.json")
        sp = os.path.join(d, "second.json")
        dp = os.path.join(d, "downgrades.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_LEDGER, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _TRANSCRIPT, "slides_transcribed": [6]}, f)
        with open(dp, "w", encoding="utf-8") as f:
            json.dump({"downgrades": downgrades}, f)
        res = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--ledger",
                lp,
                "--second-read",
                sp,
                "--downgrades",
                dp,
                "--run-id",
                "r1",
            ],
            input=json.dumps({"relations": [_TAKE_RATE_RELATION]}),
            capture_output=True,
            text=True,
        )
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr


def test_a_withdrawn_contradiction_leaves_the_founder_view() -> None:
    rc, out, err = _run_with([_downgrade()])
    assert rc == 0, err
    assert out["relations"] == []
    assert out["interpretation"]["status"] == "applied"
    assert out["interpretation"]["contradictions_before"] == 1


def test_every_withdrawal_records_its_class_and_reason() -> None:
    rc, out, err = _run_with([_downgrade()])
    assert rc == 0, err
    (record,) = out["interpretation"]["downgraded"]
    assert record["class"] == "partial_enumeration"
    assert record["reason"]
    assert record["rendered"], "the withdrawn line must survive in the record, not just its id"


def test_an_unrecognised_class_is_refused() -> None:
    """The class set is closed. Free-text grounds are not auditable and not allowed."""
    rc, _, err = _run_with([_downgrade(**{"class": "seems_fine_to_me"})])
    assert rc != 0
    assert "is not one of" in err


def test_relation_mis_specified_is_not_an_available_class() -> None:
    """The original spec's motivating class, deliberately absent.

    Its example — `$26B increased by 400% = 130B` against a stated `$104B`, where the sibling
    operator gives 26 x 4 = 104 EXACTLY — was graded **real** by the expert two days after the
    spec was written. A deck writing "400%" where it means 4x has made exactly the imprecision
    this skill exists to catch. The corpus holds zero positive evidence for the class and one
    strong counterexample, so admitting it would invite withdrawing the findings the expert kept.
    """
    rc, _, err = _run_with([_downgrade(**{"class": "relation_mis_specified"})])
    assert rc != 0
    assert "is not one of" in err


def test_a_withdrawal_with_no_reason_is_refused() -> None:
    rc, _, err = _run_with([_downgrade(reason="   ")])
    assert rc != 0
    assert "no reason" in err


def test_a_downgrade_matching_nothing_is_an_error_not_a_no_op() -> None:
    """Silently matching nothing is indistinguishable from working.

    The pass would report success while changing nothing, and nobody would find out.
    """
    rc, _, err = _run_with([_downgrade(operands=["net_revenue", "no_such_figure"])])
    assert rc != 0
    assert "names no relation" in err


def test_only_a_contradiction_can_be_withdrawn() -> None:
    """Demote-only: the pass cannot reach a derived reading, a confirmation, or anything else.

    Targets a bare ratio with no stated counterpart — a `derived` relation, which is a reading
    the report labels as judgement rather than a finding. Withdrawing one is out of scope, and
    the refusal must say so rather than silently accepting.
    """
    with tempfile.TemporaryDirectory() as d:
        lp, sp, dp = (os.path.join(d, n) for n in ("ledger.json", "second.json", "dg.json"))
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_LEDGER, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _TRANSCRIPT, "slides_transcribed": [6]}, f)
        with open(dp, "w", encoding="utf-8") as f:
            json.dump({"downgrades": [_downgrade(expected_id=None)]}, f)
        bare_ratio = {"kind": "derived_ratio", "operator": "ratio", "operands": ["net_revenue", "gross_volume"]}
        res = subprocess.run(
            [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--downgrades", dp, "--run-id", "r1"],
            input=json.dumps({"relations": [_TAKE_RATE_RELATION, bare_ratio]}),
            capture_output=True,
            text=True,
        )
    assert res.returncode != 0
    assert "only a contradiction or a rounding gap can be withdrawn" in res.stderr


def test_status_distinguishes_not_run_from_not_needed() -> None:
    """A deck with contradictions and no pass is NOT the same as a deck with nothing to review.

    The first means the founder is seeing an un-reviewed set; the second means there was
    nothing to review. Collapsing them would hide a skipped step.
    """
    rc, out, err = _run([_TAKE_RATE_RELATION])
    assert rc == 0, err
    assert out["interpretation"]["status"] == "not_run"
    assert out["interpretation"]["contradictions_before"] == 1

    rc, out, err = _run([], ledger={"figures": _LEDGER["figures"][:2]})
    assert rc == 0, err
    assert out["interpretation"]["status"] == "not_needed"


# ---------------------------------------------------------------------------
# Endpoint twins must be fused into one interval BEFORE anything compares them.
# ---------------------------------------------------------------------------

_SPLIT_RANGE_LEDGER = {
    "figures": [
        {
            "id": "contracts_before",
            "value": 6,
            "raw": "6",
            "unit_kind": "count",
            "label": "contracts per analyst per day, before",
            "slide": 3,
            "quote": "Contracts per Analyst / Day 6-10 300-500 40-60x throughput",
        },
        {
            "id": "contracts_after",
            "value": 300,
            "raw": "300",
            "unit_kind": "count",
            "label": "contracts per analyst per day, after",
            "slide": 3,
            "quote": "Contracts per Analyst / Day 6-10 300-500 40-60x throughput",
        },
        # THE SHAPE THAT MATTERS: point raws, not "40-60x" on both rows. A live extraction
        # emits these; the committed corpus happens to carry the full range in `raw`, so a
        # corpus-shaped fixture gets its interval from `_range_kwargs` and would pass here
        # with the fuse REMOVED — testing nothing.
        {
            "id": "throughput_low",
            "value": 40,
            "raw": "40x",
            "unit_kind": "multiple",
            "label": "throughput improvement — low end",
            "slide": 3,
            "quote": "Contracts per Analyst / Day 6-10 300-500 40-60x throughput",
        },
        {
            "id": "throughput_high",
            "value": 60,
            "raw": "60x",
            "unit_kind": "multiple",
            "label": "throughput improvement — high end",
            "slide": 3,
            "quote": "Contracts per Analyst / Day 6-10 300-500 40-60x throughput",
        },
    ]
}
_SPLIT_RANGE_TRANSCRIPT = "Slide 3: Contracts per Analyst / Day 6-10 300-500 40-60x throughput"


def _run_split_range(expected_id: str) -> tuple[int, dict, str]:
    with tempfile.TemporaryDirectory() as d:
        lp, sp = os.path.join(d, "l.json"), os.path.join(d, "s.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_SPLIT_RANGE_LEDGER, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _SPLIT_RANGE_TRANSCRIPT, "slides_transcribed": [3]}, f)
        rel = {
            "kind": "derived_ratio",
            "operator": "ratio",
            "operands": ["contracts_after", "contracts_before"],
            "expected_id": expected_id,
        }
        res = subprocess.run(
            [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"],
            input=json.dumps({"relations": [rel]}),
            capture_output=True,
            text=True,
        )
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr


def test_a_value_inside_a_split_stated_range_is_not_a_contradiction() -> None:
    """300 ÷ 6 = 50x against a deck stating "40-60x". 50 is INSIDE the deck's own claim.

    Measured on a live deck before this was fixed: 9 contradictions reached the founder and
    7 were this artifact — each endpoint of a split range compared as a point value. The
    fuse existed in the prototype and was dropped in the port, because the call lived in the
    eval driver rather than in the engine file.
    """
    rc, out, err = _run_split_range("throughput_low")
    assert rc == 0, err
    verdicts = [r["verdict"] for r in out["relations"]]
    assert "contradiction" not in verdicts, (
        f"a computed 50x contradicted an endpoint of the stated 40-60x range: {out['relations']}"
    )


def test_the_fuse_addresses_either_endpoint_identically() -> None:
    """Whichever twin the model names, it resolves to the same fused interval."""
    for endpoint in ("throughput_low", "throughput_high"):
        rc, out, err = _run_split_range(endpoint)
        assert rc == 0, err
        assert "contradiction" not in [r["verdict"] for r in out["relations"]], endpoint


def test_a_value_outside_the_fused_range_still_contradicts() -> None:
    """The counter-test: fusing must not blunt the engine.

    A ratio landing well outside the deck's stated range is still a finding — otherwise the
    fuse would be suppressing rather than correcting.
    """
    ledger = json.loads(json.dumps(_SPLIT_RANGE_LEDGER))
    ledger["figures"][1]["value"] = 3000  # 3000 / 6 = 500x, far outside 40-60x
    ledger["figures"][1]["raw"] = "3,000"
    with tempfile.TemporaryDirectory() as d:
        lp, sp = os.path.join(d, "l.json"), os.path.join(d, "s.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(ledger, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _SPLIT_RANGE_TRANSCRIPT + " 3,000", "slides_transcribed": [3]}, f)
        rel = {
            "kind": "derived_ratio",
            "operator": "ratio",
            "operands": ["contracts_after", "contracts_before"],
            "expected_id": "throughput_low",
        }
        res = subprocess.run(
            [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"],
            input=json.dumps({"relations": [rel]}),
            capture_output=True,
            text=True,
        )
    out = json.loads(res.stdout)
    assert "contradiction" in [r["verdict"] for r in out["relations"]], (
        "a 500x against a stated 40-60x was suppressed — the fuse is blunting real findings"
    )


def test_contradictions_are_ordered_most_wrong_first() -> None:
    """A wildly-off figure should reach the founder before a marginally-off one.

    Until now the order was whatever the model happened to propose, so the most material
    disagreement could sit last. Ordering is a strict improvement and loses nothing —
    unlike a volume cap, which on the current engine would fire on no deck in the corpus
    (4/2/0/1 contradictions across the four scored) and so would ship untested.
    """
    ledger = {
        "figures": [
            {
                "id": "revenue",
                "value": 9000,
                "raw": "$9,000",
                "unit_kind": "money",
                "currency": "USD",
                "label": "net revenue",
                "slide": 1,
                "quote": "net revenue of $9,000",
            },
            {
                "id": "volume",
                "value": 493000,
                "raw": "$493,000",
                "unit_kind": "money",
                "currency": "USD",
                "label": "volume",
                "slide": 1,
                "quote": "volume of $493,000",
            },
            {
                "id": "near",
                "value": 1.9,
                "raw": "1.9%",
                "unit_kind": "percent",
                "label": "take rate stated on slide one",
                "slide": 1,
                "quote": "a take rate of 1.9%",
            },
            {
                "id": "far",
                "value": 6.2,
                "raw": "5.4%",
                "unit_kind": "percent",
                "label": "take rate stated on slide four",
                "slide": 1,
                "quote": "a take rate of 5.4%",
            },
        ]
    }
    transcript = "Slide 1: net revenue of $9,000. volume of $493,000. a take rate of 1.9%. a take rate of 5.4%."
    with tempfile.TemporaryDirectory() as d:
        lp, sp = os.path.join(d, "l.json"), os.path.join(d, "s.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(ledger, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": transcript, "slides_transcribed": [1]}, f)
        rels = [
            {"kind": "derived_ratio", "operator": "ratio", "operands": ["revenue", "volume"], "expected_id": "near"},
            {"kind": "derived_ratio", "operator": "ratio", "operands": ["revenue", "volume"], "expected_id": "far"},
        ]
        res = subprocess.run(
            [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"],
            input=json.dumps({"relations": rels}),
            capture_output=True,
            text=True,
        )
    out = json.loads(res.stdout)
    cons = [r for r in out["relations"] if r["verdict"] == "contradiction"]
    assert len(cons) == 2, f"fixture produced no comparison to order: {out['relations']}"
    gaps = [abs(r["computed"] - r["expected_value"]) / abs(r["expected_value"]) for r in cons]
    assert gaps == sorted(gaps, reverse=True), f"not ordered most-wrong-first: {gaps}"


def test_thin_quotes_are_counted_where_something_downstream_can_see_them() -> None:
    """The quote-shape warning was written into `ledger.json` and read by nothing.

    Measured: `ledger.py` records it under `validation.warnings`, but the receipt printed
    to stdout is `{ok, path, bytes}`, SKILL.md branches on the exit code alone,
    `reconcile.py` never reads the ledger's validation block, and `ledger.json` is not in
    compose's REQUIRED_ARTIFACTS. So a quote of `$80B` still verified globally and the
    warning reached no human — computed, not delivered, which is the delivery-defect class
    this fleet has shipped before.

    Reconciliation is the first artifact downstream that compose does read, so the count
    goes there.
    """
    ledger = {
        "figures": [
            {
                "id": "a",
                "value": 80e9,
                "raw": "$80B",
                "unit_kind": "money",
                "label": "TAM",
                "slide": 6,
                "quote": "$80B",
                "currency": "USD",
            },
            {
                "id": "b",
                "value": 2e6,
                "raw": "$2M",
                "unit_kind": "money",
                "label": "ARR",
                "slide": 6,
                "quote": "ARR of $2M in 2024",
                "currency": "USD",
            },
        ]
    }
    rc, out, err = _run([], ledger=ledger, transcript="Slide 6: $80B. ARR of $2M in 2024.")
    assert rc == 0, err
    quality = out.get("quote_quality")
    assert isinstance(quality, dict), f"reconciliation.json carries no quote_quality block: {sorted(out)}"
    assert quality["thin"] == 1, quality
    assert quality["total"] == 2, quality


def test_a_ledger_of_real_quotes_reports_none_thin() -> None:
    ledger = {
        "figures": [
            {
                "id": "b",
                "value": 2e6,
                "raw": "$2M",
                "unit_kind": "money",
                "label": "ARR",
                "slide": 6,
                "quote": "ARR of $2M in 2024",
                "currency": "USD",
            },
        ]
    }
    rc, out, err = _run([], ledger=ledger, transcript="Slide 6: ARR of $2M in 2024.")
    assert rc == 0, err
    assert out["quote_quality"] == {"thin": 0, "total": 1}


def test_date_rows_do_not_count_toward_the_numeric_gate() -> None:
    """A DATE row is refused by every operator, so it can never support a finding — but it
    still counted toward `figures_total`, `figures_verified` and the minimum-figures gate.

    Measured: one genuine figure alone yields `no_figures`; add a date and the run reports
    `checked` with `figures_total=2, figures_verified=2`. The date contributed nothing and
    moved the gate, which is the only place a bogus date can still do damage now that the
    arithmetic refuses it. Counting participants of no relation as evidence of a numeric
    check is the same "computed, not delivered" inversion in reverse.
    """
    ledger = {
        "figures": [
            {
                "id": "a",
                "value": 2e6,
                "raw": "$2M",
                "unit_kind": "money",
                "label": "ARR",
                "slide": 6,
                "quote": "ARR of $2M in 2024",
                "currency": "USD",
            },
            {
                "id": "d",
                "value": 2025,
                "raw": "Founded 2025",
                "unit_kind": "date",
                "label": "founded",
                "slide": 6,
                "quote": "Founded 2025",
            },
        ]
    }
    rc, out, err = _run([], ledger=ledger, transcript="Slide 6: ARR of $2M in 2024. Founded 2025")
    assert rc == 0, err
    assert out["figures_total"] == 1, f"the date row was counted as a checkable figure: {out}"
    assert out["figures_verified"] == 1, out
    assert out["status"] == "no_figures", (
        "one real figure plus a date passed the minimum-figures gate on the date's back"
    )


def test_dates_are_still_reported_so_the_exclusion_is_visible() -> None:
    """Excluded from the gate is not the same as unrecorded — a count nobody can see is how
    a silent exclusion becomes a silent loss."""
    ledger = {
        "figures": [
            {
                "id": "d",
                "value": 2025,
                "raw": "Founded 2025",
                "unit_kind": "date",
                "label": "founded",
                "slide": 6,
                "quote": "Founded 2025",
            },
        ]
    }
    rc, out, err = _run([], ledger=ledger, transcript="Slide 6: Founded 2025")
    assert rc == 0, err
    assert out["dates_excluded"] == 1, out


def test_the_no_figures_fuse_reads_the_field_production_writes() -> None:
    """The fuse read `summary`/`content`/`text`; the schema requires `content_summary`.

    So on every real inventory it counted ZERO numerals and the safeguard was inert — and
    the test that was supposed to prove otherwise fabricated a `summary` key, which is how
    the mismatch survived. A fixture that does not validate against the schema is not
    evidence about production.
    """
    import pathlib

    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import reconcile as rec  # noqa: PLC0415

    schema_path = pathlib.Path(SCRIPTS).parent / "references" / "schemas" / "deck_inventory.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    slide_props = schema["properties"]["slides"]["items"]["properties"]
    assert "content_summary" in slide_props, "the schema field this fuse depends on has been renamed"

    number_rich = {
        "slides": [
            {"slide_number": n, "content_summary": f"Slide {n}: ARR $2.4M, 120 customers, 38% growth"}
            for n in range(1, 9)
        ]
    }
    assert rec._inventory_numerals(number_rich) > 40, (
        "a number-rich, schema-valid inventory produced too few numerals to arm the fuse"
    )

    empty = {"slides": [{"slide_number": n, "content_summary": "Team photo and a logo"} for n in range(1, 9)]}
    assert rec._inventory_numerals(empty) == 0


def _write(tmp_path: pathlib.Path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


_STANZA_LEDGER = {
    "figures": [
        {"id": "f37", "raw": "10", "value": 10.0, "slide": 19, "quote": "10 signed"},
        {"id": "f38", "raw": "23", "value": 23.0, "slide": 19, "quote": "23 in talks"},
        {"id": "f39", "raw": "67", "value": 67.0, "slide": 19, "quote": "7 to 67 active"},
    ],
    "metadata": {"run_id": "T3"},
}


def test_the_downgrade_stanza_is_printed_ready_to_copy(tmp_path: pathlib.Path) -> None:
    """The interpretation step must not depend on hand-transcribed operand ids.

    apply_downgrades matches a withdrawal on its exact (operator, operands, expected_id)
    and rejects anything else outright, so a transcription slip costs a full re-dispatch.
    """
    recon = {
        "status": "checked",
        "figures_total": 2,
        "figures_verified": 2,
        "relations": [
            {
                "kind": "derived_ratio",
                "operator": "sum",
                "operands": ["f37", "f38"],
                "expected_id": "f39",
                "computed": 33.0,
                "rendered": "10 + 23 = 33",
                "confidence": "high",
                "verdict": "contradiction",
            }
        ],
        "suppressed": {},
        "untested_claims": [],
        "relations_proposed": 1,
        "metadata": {"run_id": "T3"},
    }
    out = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--print-downgrade-stanza",
            _write(tmp_path, "reconciliation.json", recon),
            "--ledger",
            _write(tmp_path, "ledger.json", _STANZA_LEDGER),
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    stanza = json.loads(out.stdout)
    assert len(stanza) == 1
    assert stanza[0]["operator"] == "sum"
    assert stanza[0]["operands"] == ["f37", "f38"]
    assert stanza[0]["expected_id"] == "f39"
    assert stanza[0]["class"] == "REPLACE_ME"
    assert stanza[0]["reason"] == "REPLACE_ME"
    assert stanza[0]["rendered"] == "10 + 23 = 33"
    assert "10 signed" in json.dumps(stanza[0]["evidence"]), "the judge needs the quotes"


def test_the_stanza_omits_relations_that_cannot_be_withdrawn(tmp_path: pathlib.Path) -> None:
    """select() returns contradictions PLUS derived readings, and apply_downgrades rejects
    a withdrawal targeting anything but a contradiction -- which fails the whole step."""
    recon = {
        "status": "checked",
        "figures_total": 2,
        "figures_verified": 2,
        "relations": [
            {
                "kind": "derived_ratio",
                "operator": "ratio",
                "operands": ["f37", "f38"],
                "computed": 0.43,
                "rendered": "10 / 23 = 0.43",
                "confidence": "high",
                "verdict": "derived",
            }
        ],
        "suppressed": {},
        "untested_claims": [],
        "relations_proposed": 1,
        "metadata": {"run_id": "T3"},
    }
    out = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--print-downgrade-stanza",
            _write(tmp_path, "reconciliation.json", recon),
            "--ledger",
            _write(tmp_path, "ledger.json", _STANZA_LEDGER),
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [], "a derived reading is not withdrawable"


# ---------------------------------------------------------------------------
# A rounding gap reaches the founder, so it can be reviewed and withdrawn like a contradiction.
# ---------------------------------------------------------------------------

_GAP_LEDGER = {
    "figures": [
        {
            "id": "seg_a",
            "value": 1000000,
            "raw": "$1.0M",
            "unit_kind": "money",
            "label": "segment A bookings",
            "slide": 4,
            "quote": "segment A bookings $1.0M",
            "currency": "USD",
        },
        {
            "id": "seg_b",
            "value": 4200000,
            "raw": "$4.2M",
            "unit_kind": "money",
            "label": "segment B bookings",
            "slide": 4,
            "quote": "segment B bookings $4.2M",
            "currency": "USD",
        },
        {
            "id": "seg_c",
            "value": 4100000,
            "raw": "$4.1M",
            "unit_kind": "money",
            "label": "segment C bookings",
            "slide": 4,
            "quote": "segment C bookings $4.1M",
            "currency": "USD",
        },
        {
            "id": "seg_d",
            "value": 3800000,
            "raw": "$3.8M",
            "unit_kind": "money",
            "label": "segment D bookings",
            "slide": 4,
            "quote": "segment D bookings $3.8M",
            "currency": "USD",
        },
        {
            "id": "bookings_total",
            "value": 13300000,
            "raw": "$13.3M",
            "unit_kind": "money",
            "label": "total bookings",
            "slide": 4,
            "quote": "total bookings $13.3M",
            "currency": "USD",
        },
    ]
}
_GAP_TRANSCRIPT = (
    "Slide 4: segment A bookings $1.0M, segment B bookings $4.2M, segment C bookings $4.1M, "
    "segment D bookings $3.8M; total bookings $13.3M."
)
_GAP_RELATION = {
    "kind": "derived_ratio",
    "operator": "sum",
    "operands": ["seg_a", "seg_b", "seg_c", "seg_d"],
    "expected_id": "bookings_total",
}


def _run_gap(downgrades: list[dict] | None) -> tuple[int, dict, str]:
    with tempfile.TemporaryDirectory() as d:
        lp, sp, dp = (os.path.join(d, n) for n in ("ledger.json", "second.json", "dg.json"))
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(_GAP_LEDGER, f)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"transcript": _GAP_TRANSCRIPT, "slides_transcribed": [4]}, f)
        args = [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"]
        if downgrades is not None:
            with open(dp, "w", encoding="utf-8") as f:
                json.dump({"downgrades": downgrades}, f)
            args += ["--downgrades", dp]
        res = subprocess.run(args, input=json.dumps({"relations": [_GAP_RELATION]}), capture_output=True, text=True)
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr


def test_a_rounding_gap_reaches_the_founder_and_owes_a_review() -> None:
    rc, out, err = _run_gap(None)
    assert rc == 0, err
    assert [r["verdict"] for r in out["relations"]] == ["rounding_gap"]
    # Nothing contradicts, but a founder-visible verdict was not reviewed: the pass is owed.
    assert out["interpretation"]["status"] == "not_run"
    assert out["interpretation"]["contradictions_before"] == 0


def test_a_rounding_gap_names_the_allowance_that_covers_it() -> None:
    rc, out, err = _run_gap(None)
    assert rc == 0, err
    assert out["relations"][0]["gap_basis"] == "parts_rounding"


def test_a_rounding_gap_can_be_withdrawn_as_a_partial_enumeration() -> None:
    withdrawal = {
        "operator": "sum",
        "operands": ["seg_a", "seg_b", "seg_c", "seg_d"],
        "expected_id": "bookings_total",
        "class": "partial_enumeration",
        "reason": "the slide lists its four largest segments and never says they are all of them",
    }
    rc, out, err = _run_gap([withdrawal])
    assert rc == 0, err
    assert out["relations"] == []
    assert out["interpretation"]["status"] == "applied"
    assert out["suppressed"] == {"downgraded": 1}


def test_the_stanza_prints_a_rounding_gap_with_its_verdict(tmp_path: pathlib.Path) -> None:
    rc, out, err = _run_gap(None)
    assert rc == 0, err
    printed = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--print-downgrade-stanza",
            _write(tmp_path, "reconciliation.json", out),
            "--ledger",
            _write(tmp_path, "ledger.json", _GAP_LEDGER),
        ],
        capture_output=True,
        text=True,
    )
    assert printed.returncode == 0, printed.stderr
    stanza = json.loads(printed.stdout)
    assert [s["verdict"] for s in stanza] == ["rounding_gap"]
    assert stanza[0]["operands"] == ["seg_a", "seg_b", "seg_c", "seg_d"]


# ---------------------------------------------------------------------------
# A computed runway over the deck's own burn plan replaces a flat division of the same claim.
# ---------------------------------------------------------------------------


def _fig(fid: str, value: float, raw: str, unit: str, label: str, quote: str, period: str | None = None) -> dict:
    out = {"id": fid, "value": value, "raw": raw, "unit_kind": unit, "label": label, "slide": 9, "quote": quote}
    if unit == "money":
        out["currency"] = "USD"
    if period:
        out["period"] = period
    return out


_PLAN_LEDGER = {
    "figures": [
        _fig("cash", 4_200_000, "$4.2M", "money", "cash in bank", "cash in bank of $4.2M"),
        _fig("raised", 4_800_000, "$4.8M", "money", "seed raised", "seed raised of $4.8M"),
        _fig("burn_now", 150_000, "$150K/month", "money", "burn this year", "burn this year $150K/month", "month"),
        _fig("burn_next", 2_160_000, "$2.16M", "money", "burn next year", "burn next year $2.16M", "year"),
        _fig("runway", 25, "25 months", "duration", "runway", "runway of 25 months"),
        _fig("runway_goal", 30, "30 months", "duration", "runway target", "runway target of 30 months"),
        _fig("burn_ads", 163_000, "$163K/month", "money", "ads spend", "ads spend $163K/month", "month"),
    ]
}
_PLAN_TRANSCRIPT = (
    "Slide 9: cash in bank of $4.2M after a seed raised of $4.8M; burn this year $150K/month, "
    "burn next year $2.16M; runway of 25 months; runway target of 30 months; ads spend $163K/month."
)
_PLAN_SCHEDULE = [{"id": "burn_now", "from": "2026-04", "to": "2027-03"}, {"id": "burn_next", "from": "2027-04"}]


def _flat(numerator: str = "cash", expected: str = "runway") -> dict:
    return {"kind": "derived_ratio", "operator": "ratio", "operands": [numerator, "burn_next"], "expected_id": expected}


def _plan_runway(expected: str = "runway", **over: object) -> dict:
    return {
        "kind": "derived_ratio",
        "operator": "runway",
        "operands": ["cash", "burn_now", "burn_next"],
        "expected_id": expected,
        "schedule": _PLAN_SCHEDULE,
        **over,
    }


def _plan_run(relations: list[dict]) -> dict:
    rc, out, err = _run(relations, ledger=_PLAN_LEDGER, transcript=_PLAN_TRANSCRIPT, slides=[9])
    assert rc == 0, err
    return out


def test_a_flat_division_alone_is_compared_as_before() -> None:
    """$4.2M over a year's $2.16M is under two years -- short of the stated 25 months."""
    out = _plan_run([_flat()])
    assert [r["verdict"] for r in out["relations"]] == ["contradiction"]


def test_a_runway_over_the_burn_plan_supersedes_the_flat_division() -> None:
    out = _plan_run([_flat(), _plan_runway()])
    assert out["relations"] == [], "the flat contradiction must not stand beside the plan's runway"
    assert out["suppressed"] == {"superseded": 1, "confirmation": 1}
    # Decided before the count: nothing is left for the interpretation pass to review.
    assert out["interpretation"] == {"status": "not_needed", "contradictions_before": 0, "downgraded": []}


def test_a_runway_against_a_different_stated_figure_supersedes_nothing() -> None:
    out = _plan_run([_flat(), _plan_runway(expected="runway_goal")])
    verdicts = sorted(r["verdict"] for r in out["relations"])
    assert verdicts == ["contradiction", "contradiction"], out["relations"]
    assert "superseded" not in out["suppressed"]


def test_a_flat_division_of_other_cash_is_not_superseded() -> None:
    """The runway counted the bank balance; a division of the amount raised is another claim."""
    out = _plan_run([_flat(numerator="raised"), _plan_runway()])
    assert "superseded" not in out["suppressed"]


@pytest.mark.parametrize(
    "broken",
    [
        {"relation": "at_most"},  # refused as a ceiling: incomparable, no comparison ran
        {"schedule": [{"id": "burn_now", "from": "2026-04", "to": "2027-01"}, {"id": "burn_next", "from": "2027-04"}]},
    ],
)
def test_a_runway_that_did_not_compare_supersedes_nothing(broken: dict) -> None:
    out = _plan_run([_flat(), _plan_runway(**broken)])
    assert [r["verdict"] for r in out["relations"]] == ["contradiction"]
    assert "superseded" not in out["suppressed"]


def test_a_sum_that_starts_with_the_cash_is_not_superseded() -> None:
    """Only a flat ratio is the runway's duplicate; a sum is another claim."""
    total = {"expected_id": "runway", "operands": ["cash", "burn_next"], "kind": "derived_ratio"}
    total["operator"] = "sum"
    out = _plan_run([total, _plan_runway()])
    assert out["suppressed"].get("superseded") is None, out["suppressed"]


def test_a_runway_over_another_burn_does_not_retire_the_flat_division() -> None:
    """One cost line scheduled as the whole plan confirms the stated runway by accident; the
    division by the deck's real burn must still be shown."""
    misbuilt = {
        "kind": "derived_ratio",
        "operator": "runway",
        "operands": ["cash", "burn_ads"],
        "expected_id": "runway",
    }
    out = _plan_run([_flat(), misbuilt])
    assert [r["verdict"] for r in out["relations"]] == ["contradiction"], out["relations"]
    assert "superseded" not in out["suppressed"]


def test_a_longer_runway_keeps_its_finding_when_both_operators_are_proposed() -> None:
    """The measured regression: a ratio and a runway over the same figures, against a stated
    runway the figures exceed several times over. The runway's own contradiction must show, and
    the review pass must still be owed."""
    ledger = {
        "figures": [
            _fig("pool", 1_350_000, "$1.35M", "money", "pre-seed pool", "pre-seed pool of $1.35M"),
            _fig("burn", 17_300, "$17.3K", "money", "monthly burn", "monthly burn of $17.3K", "month"),
            _fig("secured", 11, "10-12", "duration", "runway secured (months)", "runway secured 10-12 months"),
        ]
    }
    transcript = "Slide 9: pre-seed pool of $1.35M; monthly burn of $17.3K; runway secured 10-12 months."
    flat = {"kind": "derived_ratio", "operator": "ratio", "operands": ["pool", "burn"], "expected_id": "secured"}
    runway = {**flat, "operator": "runway"}
    rc, out, err = _run([flat, runway], ledger=ledger, transcript=transcript, slides=[9])
    assert rc == 0, err
    assert [(r["operator"], r["verdict"]) for r in out["relations"]] == [("runway", "contradiction")]
    assert out["suppressed"].get("superseded") == 1
    assert out["interpretation"]["status"] == "not_run"


# ---------------------------------------------------------------------------
# Range figures. The ledger accepts a range at either of its two numbers, so reconcile reads
# every range from its LOW end, and sums, differences and products of a range use the whole
# range, as ratios and growth figures already did. The recorded end then reaches no
# arithmetic: two ledgers that differ only in which end they recorded give the same result.
# ---------------------------------------------------------------------------


def _reconcile() -> object:
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import reconcile as rec  # noqa: PLC0415

    return rec


def test_a_range_is_read_from_its_low_end() -> None:
    rec: Any = _reconcile()
    (f,) = rec.load_figures(
        {"figures": [_fig("eng", 463_000, "$417-463K", "money", "engineering budget", "engineering $417-463K")]}
    )
    assert (f.value, f.lo, f.hi) == (417_000, 417_000, 463_000)


def test_a_descending_range_is_read_from_its_low_end() -> None:
    rec: Any = _reconcile()
    (f,) = rec.load_figures({"figures": [_fig("pilots", 41, "41-37", "count", "paid pilots", "41-37 paid pilots")]})
    assert (f.value, f.lo, f.hi) == (37, 37, 41)


@pytest.mark.parametrize(
    ("raw", "value", "unit"),
    [
        ("$129K", 129_000, "money"),
        # A currency sign on both ends is not a range to parse_range, so it stays a point.
        ("$150K-$250K", 250_000, "money"),
        # A date is the year the ledger accepted, never a range's low end.
        ("2024-2026", 2026, "date"),
    ],
)
def test_a_point_and_a_date_keep_their_recorded_value(raw: str, value: float, unit: str) -> None:
    rec: Any = _reconcile()
    (f,) = rec.load_figures({"figures": [_fig("x", value, raw, unit, "a figure", f"a figure {raw}")]})
    assert f.value == value


_RANGE_CASES = {
    # operator: (range row id, its raw, low and high values, the other operand, the stated figure)
    "sum": ("eng", "$417-463K", 417_000, 463_000, ("sales", 129_000, "$129K"), ("total", 546_000, "$546K")),
    "difference": ("eng", "$417-463K", 417_000, 463_000, ("sales", 129_000, "$129K"), ("net", 288_000, "$288K")),
    "product": ("share", "17-19%", 17, 19, ("base", 650_000, "$650K"), ("cut", 110_500, "$110.5K")),
}


def _range_ledger(operator: str, recorded: float) -> tuple[dict, str, dict]:
    rid, raw, _lo, _hi, (oid, oval, oraw), (sid, sval, sraw) = _RANGE_CASES[operator]
    unit = "percent" if raw.endswith("%") else "money"
    figures = [
        _fig(rid, recorded, raw, unit, f"{rid} figure", f"{rid} figure {raw}"),
        _fig(oid, oval, oraw, "money", f"{oid} figure", f"{oid} figure {oraw}"),
        _fig(sid, sval, sraw, "money", f"{sid} figure", f"{sid} figure {sraw}"),
    ]
    transcript = "Slide 9: " + "; ".join(f["quote"] for f in figures) + "."
    relation = {"kind": "derived_ratio", "operator": operator, "operands": [rid, oid], "expected_id": sid}
    return {"figures": figures}, transcript, relation


@pytest.mark.parametrize("operator", sorted(_RANGE_CASES))
def test_which_end_of_a_range_was_recorded_changes_nothing(operator: str) -> None:
    """The high copy used to compute from its high end and report a contradiction the low copy did not."""
    _rid, _raw, lo, hi, *_ = _RANGE_CASES[operator]
    outs = []
    for recorded in (lo, hi):
        ledger, transcript, relation = _range_ledger(operator, recorded)
        rc, out, err = _run([relation], ledger=ledger, transcript=transcript, slides=[9])
        assert rc == 0, err
        outs.append(out)
    low, high = outs
    assert high["relations"] == low["relations"]
    assert high["suppressed"] == low["suppressed"]
    assert not [r for r in high["relations"] if r["verdict"] == "contradiction"], high["relations"]


def _computed(ledger_figures: list[dict], operator: str, operands: list[str], expected: str) -> Any:
    rec: Any = _reconcile()
    figures = rec.load_figures({"figures": ledger_figures})
    for f in figures:
        f.verified = True
    by_id = {f.id: f for f in figures}
    return rec.compute(
        {"kind": "derived_ratio", "operator": operator, "operands": operands, "expected_id": expected}, by_id
    )


def test_a_sum_of_a_range_is_a_range() -> None:
    """ "3-5" engineers plus 2 sales is 5 to 7 hires, so a stated exact 7 agrees. From the low end alone it
    computed 5 against 7 at a count's zero tolerance and reported a contradiction."""
    r = _computed(
        [
            _fig("eng", 3, "3-5", "count", "engineers to hire", "3-5 engineers"),
            _fig("sales", 2, "2", "count", "sales hires", "2 sales hires"),
            _fig("hires", 7, "7", "count", "hires this year", "7 hires this year"),
        ],
        "sum",
        ["eng", "sales"],
        "hires",
    )
    assert r.verdict != "contradiction", (r.verdict, r.rendered, r.reasons)
    assert (r.span_lo, r.span_hi) == (5, 7)
    assert "5.00–7.00" in r.rendered, r.rendered


def test_a_difference_of_a_range_runs_from_low_minus_high_to_high_minus_low() -> None:
    r = _computed(
        [
            _fig("rev", 417_000, "$417-463K", "money", "revenue", "revenue $417-463K"),
            _fig("cost", 129_000, "$129-141K", "money", "cost", "cost $129-141K"),
            _fig("margin", 300_000, "$300K", "money", "margin", "margin $300K"),
        ],
        "difference",
        ["rev", "cost"],
        "margin",
    )
    assert (r.span_lo, r.span_hi) == (417_000 - 141_000, 463_000 - 129_000)
    assert r.verdict != "contradiction", (r.verdict, r.rendered)


def test_a_product_of_a_range_is_an_agreement_when_the_stated_figure_is_inside_it() -> None:
    """17-19% of $650K is $110.5K to $123.5K. A stated $117K is inside it; the low-end product alone
    (110,500) contradicted it."""
    r = _computed(
        [
            _fig("share", 17, "17-19%", "percent", "share of base", "17-19% share"),
            _fig("base", 650_000, "$650K", "money", "base", "base of $650K"),
            _fig("cut", 117_000, "$117K", "money", "our cut", "our cut of $117K"),
        ],
        "product",
        ["share", "base"],
        "cut",
    )
    assert r.verdict != "contradiction", (r.verdict, r.rendered)
    assert r.span_lo == pytest.approx(110_500) and r.span_hi == pytest.approx(123_500)


def test_a_product_with_a_negative_operand_takes_the_min_and_max_corner() -> None:
    r = _computed(
        [
            _fig("change", -4, "-4", "count", "net change", "net change -4"),
            _fig("units", 3, "3-5", "count", "units", "3-5 units"),
            _fig("total", -17, "-17", "count", "total", "total -17"),
        ],
        "product",
        ["change", "units"],
        "total",
    )
    assert (r.span_lo, r.span_hi) == (-20, -12)


@pytest.mark.parametrize(
    ("operator", "rows", "shown"),
    [
        (
            "product",
            [("share", 17, "17-19%", "percent"), ("base", 650_000, "$650K", "money")],
            "= 110,500–123,500",
        ),
        ("sum", [("eng", 3, "3-5", "count"), ("sales", 2, "2", "count")], "= 5–7"),
        (
            "difference",
            [("rev", 417_000, "$417-463K", "money"), ("cost", 129_000, "$129K", "money")],
            "= 288,000–334,000",
        ),
    ],
)
def test_a_derived_reading_of_a_range_shows_the_whole_range(operator: str, rows: list, shown: str) -> None:
    """With no stated figure to compare against, the reading is printed as computed: a range, never its low end
    alone, which would read as if the deck had stated that one number."""
    rec: Any = _reconcile()
    figures = rec.load_figures(
        {
            "figures": [
                _fig(fid, value, raw, unit, f"{fid} figure", f"{fid} figure {raw}") for fid, value, raw, unit in rows
            ]
        }
    )
    for f in figures:
        f.verified = True
    r = rec.compute(
        {"kind": "derived_ratio", "operator": operator, "operands": [f.id for f in figures]}, {f.id: f for f in figures}
    )
    assert shown in r.rendered, r.rendered


# ---------------------------------------------------------------------------
# Every proposal is accounted for: shown in `relations`, or counted in `suppressed`.
# `Relation` is a dataclass, so membership by VALUE conflated a deduped twin with the
# object `select()` kept — the twin landed in neither list and undercounted the
# comparison count. Membership is by identity, so the twin is counted.
# ---------------------------------------------------------------------------


def test_a_deduped_twin_is_counted_as_suppressed_not_lost() -> None:
    """Two proposals of the SAME relation are one comparison kept and one counted suppressed.

    `select()` dedupes on (operator, operands, expected_id) and keeps the first. The twin is a
    `Relation` dataclass that compares EQUAL to the kept one, so a value-membership test
    (`rel in selected`) matched the twin to the kept object and counted it in neither
    `relations` nor `suppressed` — undercounting the checklist's comparison count. The twin was
    computed and not shown, so `suppressed` is where it belongs.
    """
    rc, out, err = _run([_TAKE_RATE_RELATION, _TAKE_RATE_RELATION])
    assert rc == 0, err
    assert out["status"] == "checked"
    assert out["relations_proposed"] == 2
    assert [r["verdict"] for r in out["relations"]] == ["contradiction"], out["relations"]
    assert sum(out["suppressed"].values()) == 1, out["suppressed"]
    assert len(out["relations"]) + sum(out["suppressed"].values()) == out["relations_proposed"]


_MIXED_LEDGER = {
    "figures": [
        _fig("gross_volume", 388_000, "$388K", "money", "GMV 2024", "GMV of $388K in 2024"),
        _fig("net_revenue", 6_200, "$6.2K", "money", "net revenue 2024", "net revenue of $6.2K"),
        _fig("reconciled_rate", 1.6, "1.6%", "percent", "take rate, reconciled", "our take rate is 1.6%"),
        _fig("stated_rate", 5.4, "5.4%", "percent", "take rate as stated", "our take rate is 5.4%"),
    ]
}
_MIXED_TRANSCRIPT = "Slide 9: GMV of $388K in 2024; net revenue of $6.2K; our take rate is 1.6%; our take rate is 5.4%."


def test_the_proposed_count_is_accounted_for_across_relations_and_suppressed() -> None:
    """A small fixture with mixed verdicts: every proposal is shown or counted, once.

    The deduped twin is deliberately included so the invariant fails under a value-membership
    test — it is the shape this file's fix exists for. No proposal is dropped at the gate, so
    `relations_proposed` equals what was computed and the two buckets must exhaust it.
    """
    confirmation = {
        "kind": "derived_ratio",
        "operator": "ratio",
        "operands": ["net_revenue", "gross_volume"],
        "expected_id": "reconciled_rate",
    }
    contradiction = {**confirmation, "expected_id": "stated_rate"}
    derived = {"kind": "derived_ratio", "operator": "ratio", "operands": ["net_revenue", "gross_volume"]}
    relations = [confirmation, contradiction, derived, dict(confirmation)]
    rc, out, err = _run(relations, ledger=_MIXED_LEDGER, transcript=_MIXED_TRANSCRIPT, slides=[9])
    assert rc == 0, err
    assert out["status"] == "checked"
    assert out["relations"], "fixture selected nothing"
    assert out["suppressed"], "fixture suppressed nothing"
    assert len(out["relations"]) + sum(out["suppressed"].values()) == out["relations_proposed"], (
        f"proposals are accounted for twice or not at all: {out['relations']} {out['suppressed']} "
        f"of {out['relations_proposed']}"
    )
    verdicts = {r["verdict"] for r in out["relations"]} | set(out["suppressed"])
    assert len(verdicts) >= 2, f"fixture did not produce mixed verdicts: {out['relations']} {out['suppressed']}"


# ---------------------------------------------------------------------------
# The deck-text stamp. Both artifacts record which deck text they were staged against, so a
# ledger and a second read that disagree about it must not be reconciled silently.
# ---------------------------------------------------------------------------

_PRIOR_ARTIFACT = b"a pre-existing reconciliation\n"


def _run_metadata(
    *,
    ledger_metadata: dict | None = None,
    second_metadata: dict | None = None,
    with_output: bool = False,
) -> tuple[int, dict, str, bytes | None]:
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "ledger.json")
        sp = os.path.join(d, "second.json")
        ledger = json.loads(json.dumps(_LEDGER))
        if ledger_metadata is not None:
            ledger["metadata"] = ledger_metadata
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(ledger, f)
        second: dict[str, Any] = {"transcript": _TRANSCRIPT, "slides_transcribed": [6]}
        if second_metadata is not None:
            second["metadata"] = second_metadata
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(second, f)
        args = [sys.executable, SCRIPT, "--ledger", lp, "--second-read", sp, "--run-id", "r1"]
        out_path = os.path.join(d, "reconciliation.json")
        if with_output:
            with open(out_path, "wb") as f:
                f.write(_PRIOR_ARTIFACT)
            args += ["-o", out_path]
        res = subprocess.run(
            args, input=json.dumps({"relations": [_TAKE_RATE_RELATION]}), capture_output=True, text=True
        )
        after = None
        if with_output:
            with open(out_path, "rb") as f:
                after = f.read()
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr, after


def test_differing_deck_text_shas_are_refused_and_leave_the_output_untouched() -> None:
    rc, out, err, after = _run_metadata(
        ledger_metadata={"deck_text_sha256": "a" * 64},
        second_metadata={"deck_text_sha256": "b" * 64},
        with_output=True,
    )
    assert rc == 1
    assert "DECK_TEXT_MISMATCH" in json.dumps(out)
    assert "DECK_TEXT_MISMATCH" in err
    assert after == _PRIOR_ARTIFACT


def test_equal_deck_text_shas_reconcile_as_before() -> None:
    rc, out, err, _ = _run_metadata(
        ledger_metadata={"deck_text_sha256": "a" * 64},
        second_metadata={"deck_text_sha256": "a" * 64},
    )
    assert rc == 0, err
    assert out["status"] == "checked"


def test_a_missing_sha_on_the_ledger_side_is_refused() -> None:
    rc, out, err, after = _run_metadata(second_metadata={"deck_text_sha256": "b" * 64}, with_output=True)
    assert rc == 1
    assert "DECK_TEXT_STAMP_MISSING" in json.dumps(out)
    assert "DECK_TEXT_STAMP_MISSING" in err
    assert "redo the ledger step" in err
    assert after == _PRIOR_ARTIFACT


def test_a_missing_sha_on_the_second_read_side_is_refused() -> None:
    rc, out, err, after = _run_metadata(ledger_metadata={"deck_text_sha256": "a" * 64}, with_output=True)
    assert rc == 1
    assert "DECK_TEXT_STAMP_MISSING" in json.dumps(out)
    assert "DECK_TEXT_STAMP_MISSING" in err
    assert "redo the second read step" in err
    assert after == _PRIOR_ARTIFACT


def test_no_sha_on_either_side_reconciles_as_before() -> None:
    rc, out, err, _ = _run_metadata()
    assert rc == 0, err
    assert out["status"] == "checked"


# ---------------------------------------------------------------------------
# `--explain`: a maintainer flag that prints every computed relation with its working,
# selected or not, and writes nothing. It never changes what `build()` returns.
# ---------------------------------------------------------------------------


def _run_explain(
    relations: list[dict],
    *,
    ledger: dict | None = None,
    transcript: str | None = None,
    slides: list | None = None,
    extra: list[str] | None = None,
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
        args += ["--explain"] if extra is None else extra
        res = subprocess.run(args, input=json.dumps({"relations": relations}), capture_output=True, text=True)
    try:
        parsed = json.loads(res.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return res.returncode, parsed, res.stderr


_UNKNOWN_OPERAND = {"kind": "derived_ratio", "operator": "ratio", "operands": ["net_revenue", "no_such_figure"]}


def _mixed_relations() -> list[dict]:
    confirmation = {
        "kind": "derived_ratio",
        "operator": "ratio",
        "operands": ["net_revenue", "gross_volume"],
        "expected_id": "reconciled_rate",
    }
    contradiction = {**confirmation, "expected_id": "stated_rate"}
    derived = {"kind": "derived_ratio", "operator": "ratio", "operands": ["net_revenue", "gross_volume"]}
    return [confirmation, contradiction, derived, dict(confirmation), _UNKNOWN_OPERAND]


def test_explain_prints_one_row_per_proposal_and_marks_what_select_kept() -> None:
    relations = _mixed_relations()
    rc, explained, err = _run_explain(relations, ledger=_MIXED_LEDGER, transcript=_MIXED_TRANSCRIPT, slides=[9])
    assert rc == 0, err
    assert explained["status"] == "checked"
    rows = explained["relations"]
    assert len(rows) == explained["relations_proposed"] == len(relations)
    assert [row["index"] for row in rows] == list(range(len(relations)))
    assert rows[-1]["dropped"] is True, rows[-1]
    rc, out, err = _run(relations, ledger=_MIXED_LEDGER, transcript=_MIXED_TRANSCRIPT, slides=[9])
    assert rc == 0, err
    assert sum(1 for row in rows if row["selected"]) == len(out["relations"])


def test_explain_with_an_output_is_refused_and_leaves_the_file_as_it_was(tmp_path: pathlib.Path) -> None:
    existing = tmp_path / "reconciliation.json"
    existing.write_bytes(_PRIOR_ARTIFACT)
    rc, _out, err = _run_explain([_TAKE_RATE_RELATION], extra=["--explain", "-o", str(existing)])
    assert rc == 1
    assert "drop -o" in err
    assert existing.read_bytes() == _PRIOR_ARTIFACT

    absent = tmp_path / "never.json"
    rc, _out, err = _run_explain([_TAKE_RATE_RELATION], extra=["--explain", "--output", str(absent)])
    assert rc == 1
    assert "drop -o" in err
    assert not absent.exists()


def test_explain_cannot_be_combined_with_the_downgrade_stanza(tmp_path: pathlib.Path) -> None:
    recon = _write(tmp_path, "reconciliation.json", {"relations": []})
    ledger = _write(tmp_path, "ledger.json", _LEDGER)
    res = subprocess.run(
        [sys.executable, SCRIPT, "--explain", "--print-downgrade-stanza", recon, "--ledger", ledger],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "--print-downgrade-stanza" in res.stderr
    assert json.loads(res.stdout)["validation"]["status"] == "invalid"


def test_an_abbreviated_explain_is_not_accepted() -> None:
    rc, _out, err = _run_explain([_TAKE_RATE_RELATION], extra=["--expl"])
    assert rc == 2
    assert "unrecognized arguments: --expl" in err


def test_build_returns_what_the_artifact_path_prints() -> None:
    rec: Any = _reconcile()
    relations = _mixed_relations()
    result, error = rec.build(json.loads(json.dumps(_MIXED_LEDGER)), _MIXED_TRANSCRIPT, relations, None, [9], None)
    assert error is None
    rc, out, err = _run(relations, ledger=_MIXED_LEDGER, transcript=_MIXED_TRANSCRIPT, slides=[9])
    assert rc == 0, err
    printed = {k: v for k, v in out.items() if k not in ("validation", "metadata")}
    assert json.loads(json.dumps(result)) == printed
    assert not any(key in rel for rel in printed["relations"] for key in ("tolerance", "gap"))


def test_an_operand_that_is_a_merged_range_twin_shows_the_merged_raw() -> None:
    relations = [
        {"kind": "derived_ratio", "operator": "ratio", "operands": ["throughput_high", "contracts_before"]},
        {
            "kind": "derived_ratio",
            "operator": "ratio",
            "operands": ["contracts_after", "contracts_before"],
            "expected_id": "throughput_high",
        },
    ]
    rc, explained, err = _run_explain(
        relations, ledger=_SPLIT_RANGE_LEDGER, transcript=_SPLIT_RANGE_TRANSCRIPT, slides=[3]
    )
    assert rc == 0, err
    first, second = explained["relations"]
    assert first["operands"][0]["id"] == "throughput_low"
    assert first["operands"][0]["raw"] == "40x-60x"
    assert second["expected_id"] == "throughput_low"
    assert second["expected_raw"] == "40x-60x"


def test_tolerance_and_gap_are_set_only_where_a_comparison_was_made() -> None:
    incomparable = {
        "kind": "derived_ratio",
        "operator": "ratio",
        "operands": ["net_revenue", "gross_volume"],
        "expected_id": "gross_volume",
    }
    confirmation = _mixed_relations()[0]
    rc, explained, err = _run_explain(
        [incomparable, confirmation], ledger=_MIXED_LEDGER, transcript=_MIXED_TRANSCRIPT, slides=[9]
    )
    assert rc == 0, err
    bad, good = explained["relations"]
    assert bad["verdict"] == "incomparable", bad
    assert bad["tolerance"] is None and bad["gap"] is None
    assert good["verdict"] == "confirmation", good
    assert good["tolerance"] is not None and good["gap"] is not None
    assert 0 <= good["gap"] <= good["tolerance"]


def test_explain_on_a_deck_with_no_figures_prints_its_status_and_no_rows() -> None:
    rc, explained, err = _run_explain([], ledger={"figures": []})
    assert rc == 0, err
    assert explained == {"status": "no_figures", "relations_proposed": 0, "relations": []}
