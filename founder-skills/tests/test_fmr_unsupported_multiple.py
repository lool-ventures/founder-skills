"""A checklist finding may not state a 'times' comparison its own cited figures contradict.

THE DEFECT THIS EXISTS FOR. A CHECKLIST sub-agent, reviewing a real 12-sheet model, asserted the
projections were "roughly 2,000x" the actuals while citing, in the same sentence, the two figures
whose ratio is 6.8x -- wrong by ~293x. It was rendered verbatim into report.md, report.json, the
coaching payload and the coaching commentary's headline, and two criteria were scored FAIL on it.
Nothing reconciled a stated figure against the figures beside it.

WHY THE CHECK IS THIS NARROW, measured rather than argued. Across 2,854 real CHECKLIST evidence and
notes strings harvested from every kept run dir -- 289 financial-model-review, 1,563 deck-review,
694 competitive-positioning, 308 market-sizing -- only 39 state a multiple at all, and exactly ONE
fires: the defect. Silent on the other 38. A broader formulation ("does SOME pair in the sentence support the
multiple") was measured at 36% precision on hand-written probe sentences, which is below the bar
`_check_metric_self_contradiction`'s own docstring sets when it explains why it dropped whole metric
classes: "a check that fires on normal, well-written evidence prose trains the reader to ignore it".

The design record, including two earlier revisions that did not survive review, is in
`docs/internal/2026-09-19-fmr-critique-corpus-findings.md`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts"

sys.path.insert(0, str(Path(__file__).parent))
from test_financial_model_review import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _VALID_UNIT_ECONOMICS,
    _make_fmr_artifact_dir,
    _run_compose,
)


def _detector() -> Any:
    """The shared detector. Imported by all three renderers, so there is one implementation."""
    spec = importlib.util.spec_from_file_location("fmr_em", SCRIPTS / "_evidence_multiple.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The defect's own shape, rebuilt with invented figures: a stated multiple ~293x away from the
# ratio of the two figures the same sentence cites.
DEFECT = (
    "Projected FY27 revenue is roughly 2,000x the FY23 actual of $123,485,311 against $843,000,000, "
    "with no bridge between them."
)


def test_the_defect_fires() -> None:
    module = _detector()
    divergence = module.unsupported_multiple(DEFECT)
    assert divergence is not None, "the motivating defect is not detected"
    assert divergence > 100


def test_the_same_sentence_with_a_correct_multiple_is_silent() -> None:
    """The check must key on the arithmetic, not on the shape of the sentence."""
    module = _detector()
    correct = DEFECT.replace("2,000x", "6.8x")
    assert module.unsupported_multiple(correct) is None


def test_real_evidence_prose_does_not_fire() -> None:
    """Legitimate findings that state a multiple about figures they do not both cite stay silent.

    This is the class that sinks a broader rule: the multiple is about one pair and the marked
    figures are another, so "does some pair support it" answers no on perfectly good prose.
    """
    module = _detector()
    legitimate = [
        "Revenue of $8.2M with CAC of $1,200 implies a 40x revenue-per-head gain.",
        "Burn of $450,000 a month against $12,000 of new ARR; the team is 3x oversized.",
        "Gross margin holds at 76% on $2.4M revenue, a 2x improvement in unit contribution.",
        "The model shows $18,000 CAC and $54,000 LTV, a healthy 3x ratio.",
        "ARR grew from $1.2M to $4.1M, roughly 3x, with sales spend of $600,000.",
    ]
    fired = [s for s in legitimate if module.unsupported_multiple(s) is not None]
    assert not fired, f"fired on legitimate evidence prose: {fired}"


def test_degenerate_inputs_do_not_raise() -> None:
    """Every one of these crashed or would have crashed an earlier revision.

    `$0` is currency-marked and therefore a legal operand -- a pre-revenue model states one -- and
    `max/min` over it raises. A space-grouped "2 000x" parses as the token `000x`, i.e. a multiple
    of zero, which divides by zero at normalization. Both land inside `compose_report.py`, where an
    unhandled exception takes down report assembly for the whole review.
    """
    module = _detector()
    # These three DO reach the division and raise without the `a == 0 or b == 0` guard -- verified
    # by deleting it. The probe this test used to carry ("Cash of $0 against $1.2M of burn gives a
    # 3x gap") yielded only one operand under the shipped grammar, so it returned early and the
    # test passed with the guard removed: it was named for a guard it never exercised.
    for text in (
        "$0 of cash against $1,200,000 of burn is 300x the plan",
        "Revenue is 300x the 0,000 base against 1,200,000 of plan",
        "Cash of $0 against $1.2M of burn gives a 3x gap",
        "grew 2 000x the base of $1.2M against $900,000",
        "revenue is 5x the base of $1.2M",
        "revenue is 5x the prior year",
        "5x the $1.2M against $1.2M",
        "",
        None,
    ):
        assert module.unsupported_multiple(text) is None


def test_multiple_token_grammar() -> None:
    """The multiple token uses a SPACE-FREE mantissa, unlike the operand grammar.

    `reconcile.py`'s `_MANTISSA` carries an internal space group, so copying it reads
    "Revenue in 2024 100x" as 2,024,100x -- a spurious multiple that large beside two real figures
    fires with certainty, which inverts the whole safety argument. Pinned so a later "unify the
    grammars" refactor cannot silently undo it.
    """
    module = _detector()
    assert module.MULTIPLE_RE.search("Revenue in 2024 100x the base").group(1) == "100"
    assert module.MULTIPLE_RE.search("Quarter 1 200x improvement").group(1) == "200"
    # An infix multiplication sign between a currency figure and a percentage is not a multiple.
    assert module.MULTIPLE_RE.search("ARPU $500 × gross margin 75%") is None
    assert module.MULTIPLE_RE.search("costs $500x") is None
    assert module.MULTIPLE_RE.search("a 2x2 matrix") is None


# The shared fixture's labels read "Label for STRUCT_01" -- they CONTAIN the id, so a message
# built from either one looks the same and the label-not-id property is untestable against them.
# This is a realistic label with no id in it, which is what makes the assertion below real.
_LABEL = "Assumptions isolated on a dedicated tab"


def _checklist_with(evidence: str) -> dict[str, Any]:
    checklist: dict[str, Any] = json.loads(json.dumps(_VALID_CHECKLIST))
    first = checklist["items"][0]
    first["status"] = "fail"
    first["label"] = _LABEL
    first["evidence"] = evidence
    checklist["summary"]["fail"] = 1
    checklist["summary"]["failed_items"] = [
        {
            "id": first["id"],
            "category": first["category"],
            "label": _LABEL,
            "evidence": evidence,
            "notes": None,
            "severity": "high",
        }
    ]
    return checklist


def _compose(evidence: str) -> tuple[dict[str, Any], str]:
    directory = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _checklist_with(evidence),
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    md_path = Path(directory) / "report.md"
    rc, data, stderr = _run_compose(directory, ["--write-md", str(md_path)])
    assert rc == 0, stderr
    assert data is not None
    return data, md_path.read_text(encoding="utf-8")


def test_warning_reaches_report_md_naming_the_label_not_the_id() -> None:
    """`_harvest` keys on `id` and would ship `UNIT_10` to a founder; read `label` off the item."""
    data, md = _compose(DEFECT)
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "UNSUPPORTED_MULTIPLE"]
    assert len(hits) == 1, "expected exactly one UNSUPPORTED_MULTIPLE warning"
    assert hits[0]["severity"] == "medium"
    assert _LABEL in hits[0]["founder_message"]
    assert hits[0]["founder_message"] in md
    # The id belongs on the machine surface only.
    assert _VALID_CHECKLIST["items"][0]["id"] not in hits[0]["founder_message"]


def test_the_coach_is_caveated_in_the_same_run_as_the_warning() -> None:
    """The prerequisite, not a follow-up.

    The warnings section is spliced last and the coaching marker after it, so the warning renders
    immediately above the commentary — and on the run that produced this finding, the unsupported
    multiple became that commentary's headline. A warning the coach cannot see, one line above a
    coach repeating the number, is a report contradicting itself.
    """
    data, _md = _compose(DEFECT)
    payload_evidence = data["coaching_payload"]["failed_items"][0]["evidence"]
    assert "do not repeat it" in payload_evidence, (
        "the coaching payload carries the unsupported multiple with no caveat"
    )


def test_clean_evidence_leaves_both_surfaces_untouched() -> None:
    data, md = _compose("Opex is a flat monthly number with no headcount plan behind it.")
    assert [w for w in data["validation"]["warnings"] if w["code"] == "UNSUPPORTED_MULTIPLE"] == []
    assert "do not repeat it" not in json.dumps(data["coaching_payload"])
    assert "not supported by the figures" not in md


def test_the_measurement_tool_uses_the_production_detector() -> None:
    """The calibration tool must not carry its own copy of the grammar.

    An earlier revision of this work measured a prototype, wrote a spec describing something else,
    and shipped a regex that matched nothing — the check fired zero times where the prototype fired
    once. A tool with an independent copy reproduces exactly that, and would report a healthy
    false-positive rate for a detector that had stopped working.
    """
    import evidence_multiple_corpus as tool

    detector = tool.load_detector()
    assert detector.unsupported_multiple(DEFECT) is not None
    assert detector.unsupported_multiple(DEFECT.replace("2,000x", "6.8x")) is None
    # Same object the renderers import, not a re-implementation.
    assert tool.DETECTOR.name == "_evidence_multiple.py"
    assert tool.DETECTOR.exists()

    # Exercise `measure()` itself. Asserting only on `load_detector()` left the hazard live: a
    # `measure()` carrying its own always-None detector passed the whole suite, which is precisely
    # "reports a healthy false-positive rate for a detector that has stopped working".
    rows = tool.measure({"probe": {DEFECT, DEFECT.replace("2,000x", "6.8x")}})
    assert rows == [("probe", 2, 2, 1)], rows


def test_every_renderer_caveats_a_flagged_finding() -> None:
    """One surface warning while two ship the number plain is the defect this repo keeps hitting.

    `visualize.py` and `explore.py` read checklist.json directly and never see compose's warnings
    section, so the caveat has to travel with the evidence text itself. The first cut of this change
    caveated only the coaching payload and left both HTML pages unqualified.
    """
    import subprocess
    import sys as _sys

    data, md = _compose(DEFECT)
    assert "do not repeat it" in md, "report.md renders the finding without the caveat"
    assert "do not repeat it" in json.dumps(data["coaching_payload"]), "the coach is uncaveated"

    # Both HTML generators, driven over the same artifact dir the markdown came from.
    work = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": _checklist_with(DEFECT),
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    for generator in ("visualize.py", "explore.py"):
        out = Path(work) / generator.replace(".py", ".html")
        subprocess.run(
            [_sys.executable, str(SCRIPTS / generator), "--dir", work, "-o", str(out)],
            check=True,
            capture_output=True,
        )
        html = out.read_text(encoding="utf-8")
        # PER PANEL, not per file. `visualize.py` renders the evidence twice from different item
        # sets with different field preferences -- the heatmap walks every item preferring
        # `evidence`, "What needs attention" walks fail/warn items preferring `notes` -- so a
        # whole-file assertion stays green while one of the two panels ships the comparison
        # unqualified. Measured: reverting either site alone did not red this test before.
        # visualize.py renders this fixture's flagged item TWICE -- once in the heatmap, once in
        # "What needs attention" -- from different item sets with different field preferences. Both
        # must carry it; measured, reverting either site alone drops the count to 1.
        expected = 2 if generator == "visualize.py" else 1
        assert html.count("do not repeat it") >= expected, (
            f"{generator} carries {html.count('do not repeat it')} caveat(s), expected >= "
            f"{expected} — one of its render paths is unqualified"
        )
