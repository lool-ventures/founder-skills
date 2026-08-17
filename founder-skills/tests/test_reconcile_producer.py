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
    assert "only a contradiction can be withdrawn" in res.stderr


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
                "raw": "6.2%",
                "unit_kind": "percent",
                "label": "take rate stated on slide four",
                "slide": 1,
                "quote": "a take rate of 6.2%",
            },
        ]
    }
    transcript = "Slide 1: net revenue of $9,000. volume of $493,000. a take rate of 1.9%. a take rate of 6.2%."
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
