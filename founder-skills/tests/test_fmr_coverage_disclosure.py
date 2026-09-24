"""The self-gated-coverage contract, pinned on the FREE lane.

WHY A SEPARATE FILE. These are the unit counterparts of the financial-model-review e2e lane's new
assertions (see `docs/internal/2026-09-19-e2e-gate-root-cause-plan.md` §2). That lane used to assert
`score_coverage["complete"] is True` -- i.e. that the scoring sub-agent never judges a criterion
not applicable -- which is a model judgement on a fixed fixture and failed 2 of 3 independent CI
runs, blocking a release. The pipeline is BUILT for that judgement to happen and to be disclosed
(`checklist.py` records rather than overrides it; `compose_report.py` renders it on every founder
surface), so the gate now asserts the DISCLOSURE. Every surface it asserts is rendered by code we
own, and therefore belongs in a free test rather than a $5-15 paid run.

Two of these were asserted NOWHERE before this file existed: the `**Not assessed:**` line that
report.md puts under the score, and that an id an assessor writes into its own evidence reaches the
founder as a label.
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


def _checklist_module() -> Any:
    spec = importlib.util.spec_from_file_location("fmr_checklist", SCRIPTS / "checklist.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compose_with_self_gated(ids: list[str]) -> tuple[dict[str, Any], str]:
    """Compose a report whose checklist recorded `ids` as set aside. Returns (report.json, report.md)."""
    checklist = json.loads(json.dumps(_VALID_CHECKLIST))
    checklist["summary"]["self_gated_items"] = ids
    directory = _make_fmr_artifact_dir(
        {
            "inputs.json": _VALID_INPUTS,
            "checklist.json": checklist,
            "unit_economics.json": _VALID_UNIT_ECONOMICS,
            "runway.json": _VALID_RUNWAY,
        }
    )
    md_path = Path(directory) / "report.md"
    rc, data, stderr = _run_compose(directory, ["--write-md", str(md_path)])
    assert rc == 0, stderr
    assert data is not None
    return data, md_path.read_text(encoding="utf-8")


def test_self_gated_drop_reaches_report_md_under_the_score() -> None:
    """report.md must carry the `**Not assessed:**` line, not only the warning.

    `compose_report.py` renders it directly beneath the percentage, which is the founder's only
    in-context signal that the score was computed over fewer criteria than their company warrants.
    Nothing asserted it: the existing self-gated test reads report.json only, and the one test that
    does read report.md covers the UNRESOLVED branch (`Not matched:`), a different cause.
    """
    _data, md = _compose_with_self_gated(["UNIT_10", "METRIC_33"])
    assert "**Not assessed:**" in md, "the score's own section does not disclose the shrunken denominator"
    assert "2 checks" in md
    # Named by LABEL, which is what `_checklist_labels` is for. (The id-absence check lives in the
    # HTML ratchet and the e2e lane; this fixture's own labels literally read "Label for UNIT_10",
    # so asserting the id is absent here would test the fixture rather than the product.)
    module = _checklist_module()
    for item_id in ("UNIT_10", "METRIC_33"):
        assert f"Label for {item_id}" in md or module.ITEM_LOOKUP[item_id]["label"] in md


def test_self_gated_founder_message_is_rendered_verbatim() -> None:
    """The warning's `founder_message` is what the e2e lane matches against report.md."""
    data, md = _compose_with_self_gated(["UNIT_10"])
    hits = [w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_SELF_GATED"]
    assert len(hits) == 1
    founder_message = hits[0]["founder_message"]
    assert founder_message and founder_message in md, (
        "founder_message is not in report.md verbatim; the e2e assertion keyed on it would be vacuous"
    )
    # Ids stay on the machine surface so the paid lane can name the criterion.
    assert "UNIT_10" in hits[0]["message"]


def test_self_gated_ids_parses_the_warning_the_paid_lane_keys_on() -> None:
    """`self_gated_ids` is the parser BOTH identity assertions in the paid lane depend on.

    It lived only in that lane, exercised only by a $5-15 run — the same unexercised-helper shape
    as the diagnostic that read the wrong key for a month and was found by a release tag. One line
    here costs nothing and fails loudly instead.
    """
    from test_e2e_financial_model_review import self_gated_ids

    data, _md = _compose_with_self_gated(["UNIT_10", "CASH_23"])
    assert self_gated_ids(data) == ["CASH_23", "UNIT_10"]
    clean, _md2 = _compose_with_self_gated([])
    assert self_gated_ids(clean) == []


def test_clean_run_discloses_nothing() -> None:
    """The green branch asserts something too, so a spurious disclosure cannot pass."""
    _data, md = _compose_with_self_gated([])
    assert "**Not assessed:**" not in md


def test_assessor_written_criterion_id_reaches_the_founder_as_a_label() -> None:
    """An id in assessor-authored evidence is rewritten to the criterion's label by the PRODUCER.

    POSITIVE assertion, deliberately. Rewriting also silences the only detector that existed --
    `_founder_text.scan` reports this shape as `FOUNDER_TEXT_TOKEN` (severity low, and it lands in
    report.json only) -- so a test asserting the id is ABSENT would pass just as well if the
    evidence had been dropped on the floor. The label has to be there.

    It belongs in the producer and not in `compose_report.py`, because `visualize.py` and
    `explore.py` render the same evidence into HTML and never see compose's output.
    """
    module = _checklist_module()
    label_23 = module.ITEM_LOOKUP["CASH_23"]["label"]
    out = module._ids_to_labels("Cross-checked against CASH_23; see also UNIT_10.")
    assert label_23 in out, "the criterion's label is missing — the evidence was not rewritten"
    assert module.ITEM_LOOKUP["UNIT_10"]["label"] in out
    assert "CASH_23" not in out and "UNIT_10" not in out
    # Non-strings and empties pass through untouched (evidence is Optional in the schema).
    assert module._ids_to_labels(None) is None
    assert module._ids_to_labels("") == ""


def test_notes_are_rewritten_too_not_only_evidence() -> None:
    """`visualize.py` falls back to `notes` in two places, so it is the same founder surface."""
    module = _checklist_module()
    items = [{"id": item["id"], "status": "pass", "evidence": "ok", "notes": None} for item in module.CHECKLIST_ITEMS]
    items[0] = {**items[0], "evidence": "matches CASH_23", "notes": "cross-ref UNIT_10"}
    first_id = items[0]["id"]
    result, errors = module.validate_checklist(items, company=None, inputs=None)
    assert not errors, errors
    scored = next(i for i in result["items"] if i["id"] == first_id)
    assert scored["notes"] == f"cross-ref {module.ITEM_LOOKUP['UNIT_10']['label']}", (
        "notes was not rewritten; visualize.py falls back to it when evidence is empty"
    )
    # BOTH fields, through the producer. Testing `_ids_to_labels` directly proves the helper and
    # not the call site: deleting either call leaves a helper-only test green.
    assert scored["evidence"] == f"matches {module.ITEM_LOOKUP['CASH_23']['label']}", (
        "evidence was not rewritten at the call site"
    )
