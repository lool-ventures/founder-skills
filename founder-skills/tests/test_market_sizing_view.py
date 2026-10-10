"""The report renders what the sizing consumed, and says so when the record or the sizing has moved.

Each run here is real: the producer resolves references against a research record and writes
sizing.json, then compose and visualize render it. The founder-facing defect this exists for was a
head-count recorded under the name `industry_total`, printed in dollars and lending its grade to
the top-down TAM through a join on the name.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from html_text import visible_text  # noqa: E402
from test_market_sizing import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_METHODOLOGY,
    _VALID_SENSITIVITY,
    run_script,
    run_script_raw,
)

_SCRIPTS = _TESTS.parent / "skills" / "market-sizing" / "scripts"
_RUN = "RUN-VIEW"
_SRC = {"title": "Government survey 2025", "url": "https://example.gov/survey"}


def _sourced(name: str, value: float, unit: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "category": "sourced",
        "source_title": _SRC["title"],
        "source_url": _SRC["url"],
        **extra,
    }


def _record(*extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "assumptions": [
            _sourced("eligible_population", 41_000_000, "count"),
            _sourced("care_price", 157, "money_per_customer", currency="USD", period="month"),
            _sourced("segment_pct", 37, "percent_points"),
            *extra,
        ],
        "sources": [_SRC],
        "figure_validations": [{"figure": "TAM", "status": "validated", "source_count": 2}],
    }


_REFS = {
    "approach": "top_down",
    "industry_total": {
        "derived": {"op": "multiply", "factors": [{"assumption": "eligible_population"}, {"assumption": "care_price"}]}
    },
    "segment_pct": {"assumption": "segment_pct"},
    "share_pct": {"estimate": 0.27, "unit": "percent_points", "why": "The deck's own long-run capture target."},
}


def _stamp(doc: dict[str, Any]) -> dict[str, Any]:
    return {**doc, "metadata": {"run_id": _RUN}}


def _run_dir(tmp_path: Path, record: dict[str, Any], refs: dict[str, Any] | None = None, **methodology: Any) -> Path:
    d = tmp_path / "analysis"
    d.mkdir()
    (d / "validation.json").write_text(json.dumps(_stamp(record)))
    (d / "inputs.json").write_text(json.dumps(_stamp({"company_name": "TestCo", "currency": "USD"})))
    (d / "methodology.json").write_text(
        json.dumps(_stamp({**_VALID_METHODOLOGY, "approach_chosen": "top_down", **methodology}))
    )
    (d / "checklist.json").write_text(json.dumps(_stamp(_VALID_CHECKLIST)))
    (d / "sensitivity.json").write_text(json.dumps(_stamp(_VALID_SENSITIVITY)))
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(refs or _REFS),
    )
    assert rc == 0, out + err
    _stamp_downstream(d)
    return d


def _stamp_downstream(d: Path) -> None:
    """What a correct run's sensitivity and checklist producers record: the sizing they were built on."""
    import importlib

    sys.path.insert(0, str(_SCRIPTS))
    fp = importlib.import_module("_provenance").sizing_fingerprint(json.loads((d / "sizing.json").read_text()))
    for name in ("sensitivity.json", "checklist.json"):
        _edit(d, name, lambda doc: doc.update(graded_against={"sizing.json": fp}))


def _compose(d: Path) -> dict[str, Any]:
    rc, data, err = run_script("compose_report.py", ["--dir", str(d)])
    assert rc == 0 and data is not None, err
    return data


def _codes(data: dict[str, Any]) -> list[str]:
    return [w["code"] for w in data["validation"]["warnings"]]


def _html(d: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "visualize.py"), "--dir", str(d)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _edit(d: Path, name: str, fn: Any) -> None:
    doc = json.loads((d / name).read_text())
    fn(doc)
    (d / name).write_text(json.dumps(doc))


# --- the defect ---------------------------------------------------------------------------------


def test_a_head_count_named_like_an_input_is_neither_money_nor_its_provenance(tmp_path: Path) -> None:
    """The record keeps a head-count under the name `industry_total` as research context, while the
    sizing's industry total is derived money. The report must print the head-count as a count, and
    must grade the TAM from what the sizing consumed, not from whatever shares the name."""
    head_count = {
        **_sourced("industry_total", 36_000_000, "count"),
        "category": "agent_estimate",
        "label": "Seniors eligible for care",
    }
    d = _run_dir(tmp_path, _record(head_count))
    data = _compose(d)
    md = data["report_markdown"]
    assert "$36.0M" not in md
    assert "36,000,000" in md
    # Graded from the stamp: population and price are sourced, so the derived total is "derived";
    # the name join would have lent the head-count's "agent_estimate".
    tam = data["provenance"]["top_down"]["tam"]
    assert tam["classification"] == "derived"
    assert tam["input_provenances"] == {"industry_total": "derived"}
    assert "PROVENANCE_UNRESOLVED" not in _codes(data)


def test_an_estimate_is_graded_as_an_estimate_even_beside_research_of_the_same_name(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record(_sourced("share_pct", 2.0, "percent_points")))
    data = _compose(d)
    som = data["provenance"]["top_down"]["som"]
    assert som["classification"] == "agent_estimate"
    md = data["report_markdown"]
    assert "0.27%" in md and "2%" in md  # the estimate and the research it departed from, both shown


# --- the sizing is re-checked, never trusted --------------------------------------------------------


def test_a_record_that_moved_after_the_sizing_ran_is_named_before_the_review(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    data = _compose(d)
    assert "SIZING_STALE" in _codes(data)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "SIZING_STALE")
    assert w["severity"] == "high"


def test_an_edited_sizing_is_not_what_the_founder_reads(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    true_tam = json.loads((d / "sizing.json").read_text())["top_down"]["tam"]["value"]
    _edit(d, "sizing.json", lambda s: s["top_down"]["tam"].update(value=12_345_000_000))
    data = _compose(d)
    assert "SIZING_ALTERED" in _codes(data)
    md = data["report_markdown"]
    assert "$12.3B" not in md
    assert f"${true_tam / 1e9:,.1f}B" in md
    html = _html(d)
    assert "$12.3B" not in html
    assert f"${true_tam / 1e9:,.1f}B" in html


def test_a_referenced_figure_that_vanished_from_the_record_is_named(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(name="segment_share"))
    data = _compose(d)
    assert "SIZING_UNRESOLVABLE" in _codes(data)


def test_after_the_review_a_moved_record_is_not_offered_the_replay(tmp_path: Path) -> None:
    """Once a review exists, re-running the sizing would adopt a change the review never saw."""
    d = _run_dir(tmp_path, _record(), red_team_skipped=None)
    _edit(d, "methodology.json", lambda m: m.pop("red_team_skipped", None))
    finding = {
        "claim_attacked": "The segment share",
        "what_is_true": "The published share is 30%.",
        "evidence_quote": "Thirty percent of seniors have an adult child with access.",
        "source_url": "https://example.gov/survey",
        "source_title": "Government survey 2025",
        "severity": "high",
    }
    rc, out, err = run_script_raw(
        "red_team.py", ["--run-id", _RUN, "-o", str(d / "redteam.json")], stdin_data=json.dumps({"findings": [finding]})
    )
    assert rc == 0, out + err
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    data = _compose(d)
    codes = _codes(data)
    assert "RECORD_CHANGED_AFTER_REVIEW" in codes and "SIZING_STALE" not in codes
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "RECORD_CHANGED_AFTER_REVIEW")
    assert "re-run" not in w["message"].lower()


def test_a_unit_relabelled_after_the_calculator_refused_it_is_disclosed(tmp_path: Path) -> None:
    """The refusal is a recorded fact. Relabelling the head-count as money and referencing it again
    clears the refusal and nothing else; the founder is told."""
    d = _run_dir(tmp_path, _record(_sourced("eligible_total", 36_000_000, "count")))
    refs = {**_REFS, "industry_total": {"assumption": "eligible_total"}}
    rc, out, _ = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(refs),
    )
    assert rc != 0 and "E_UNIT_MISMATCH" in out
    _edit(
        d,
        "validation.json",
        lambda v: v["assumptions"][3].update(unit="money_total_per_year", currency="USD"),
    )
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(refs),
    )
    assert rc == 0, out + err
    data = _compose(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "UNIT_CHANGED_AFTER_REJECTION")
    assert w["severity"] == "high"
    assert "36,000,000" in w["message"]


def test_every_code_this_subsystem_adds_has_a_remedy_that_changes_nothing_it_checks() -> None:
    """Driven by the registry, so a code added later is held to the same rule.

    A remedy may re-run a producer, re-dispatch a sub-agent, ask the founder, restore a baseline, or
    disclose. It may never be to edit the sizing, the review or the record until the comparison
    agrees: a check whose cheapest remedy changes the thing it checks trains the edit.
    """
    import importlib
    import importlib.util

    sys.path.insert(0, str(_SCRIPTS))
    view = importlib.import_module("_view")
    prov = importlib.import_module("_provenance")
    spec = importlib.util.spec_from_file_location("_ms_compose_remedy_test", _SCRIPTS / "compose_report.py")
    assert spec is not None and spec.loader is not None
    compose = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compose)

    legitimate = {"producer_rerun", "redispatch", "founder_question", "restore_to_baseline", "disclose"}
    assert legitimate <= prov.REMEDY_KINDS
    codes = view.INTEGRITY_REMEDY
    assert len(codes) == 10, sorted(codes)  # non-vacuity: every code this subsystem raises is listed
    for code, remedy in codes.items():
        assert remedy in legitimate, (code, remedy)
        assert code in compose.WARNING_SEVERITY, f"{code} has no severity"
        assert code in compose.WARNING_LABELS, f"{code} has no founder-facing label"


# --- after the review: the snapshot the review was taken against ------------------------------------


def _reviewed_dir(tmp_path: Path) -> Path:
    d = _run_dir(tmp_path, _record())
    _edit(d, "methodology.json", lambda m: m.pop("red_team_skipped", None))
    _review(d, "The published share is 30%.")
    return d


def _review(d: Path, what_is_true: str) -> int:
    finding = {
        "claim_attacked": "The segment share",
        "what_is_true": what_is_true,
        "evidence_quote": "Thirty percent of seniors have an adult child with access.",
        "source_url": "https://example.gov/survey",
        "source_title": "Government survey 2025",
        "severity": "high",
    }
    rc, out, err = run_script_raw(
        "red_team.py", ["--run-id", _RUN, "-o", str(d / "redteam.json")], stdin_data=json.dumps({"findings": [finding]})
    )
    assert rc == 0, out + err
    receipt: dict[str, Any] = json.loads(out)
    return int(receipt["round"])


def _replay(d: Path) -> None:
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--replay",
            str(d / "sizing.json"),
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "-o",
            str(d / "sizing.json"),
        ],
    )
    assert rc == 0, out + err


def test_the_review_records_what_it_reviewed_once(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    copy1 = json.loads((d / "handoff" / _RUN / "redteam.r1.json").read_text())
    snap = copy1["inputs_reviewed"]
    assert snap["sizing"]["segment_pct"]["value_consumed"] == 37
    assert snap["record"]["segment_pct"]["value"] == 37
    # A re-pipe of the same hand-off after the record moved keeps the round's baseline.
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    assert _review(d, "The published share is 30%.") == 1
    again = json.loads((d / "handoff" / _RUN / "redteam.r1.json").read_text())
    assert again["inputs_reviewed"] == snap
    assert json.loads((d / "redteam.json").read_text())["inputs_reviewed"] == snap


def test_an_edit_after_the_review_then_a_replay_is_still_reported(tmp_path: Path) -> None:
    """Replaying makes the record and the sizing agree again. Only the review's snapshot can see
    that neither is what the review saw."""
    d = _reviewed_dir(tmp_path)
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    assert "RECORD_CHANGED_AFTER_REVIEW" in _codes(_compose(d))


def test_a_revised_and_re_reviewed_analysis_reports_the_change_as_a_fact(tmp_path: Path) -> None:
    """Was: an approval in methodology.json licensed the change and nothing was reported. The change
    is now disclosed from the two review copies, whatever methodology.json says."""
    d = _reviewed_dir(tmp_path)
    _edit(
        d,
        "methodology.json",
        lambda m: m.update(red_team_revision={"approved_by_founder": True, "founder_words": "Yes, use 30%."}),
    )
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    assert _review(d, "Round two: the revised share is supported.") == 2
    codes = _codes(_compose(d))
    assert "RECORD_CHANGED_AFTER_REVIEW" not in codes and "SIZING_STALE" not in codes, codes
    assert "ANALYSIS_CHANGED_BETWEEN_REVIEWS" in codes, codes


def test_a_second_review_does_not_launder_a_change(tmp_path: Path) -> None:
    """A change followed by a fresh review is shown with that review -- and disclosed as a change, in
    Warnings and in the coaching payload, not only in the note (the adversarial review's finding 5)."""
    d = _reviewed_dir(tmp_path)
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    _review(d, "Round two: the revised share is supported.")
    data = _compose(d)
    assert "ANALYSIS_CHANGED_BETWEEN_REVIEWS" in _codes(data)
    assert data["coaching_payload"]["review_rounds"]["changes"] == ["Segment %: 37% \u2192 30%"]


def test_editing_the_reviewed_snapshot_is_an_edit_of_the_review(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    _edit(d, "redteam.json", lambda r: r["inputs_reviewed"]["sizing"]["segment_pct"].update(value_consumed=30))
    assert "REDTEAM_ALTERED" in _codes(_compose(d))


# --- the steps built on the sizing were built on THIS sizing ----------------------------------------


def test_a_sensitivity_table_built_on_an_earlier_sizing_is_named(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    assert "SENSITIVITY_STALE" not in _codes(_compose(d))
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    data = _compose(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "SENSITIVITY_STALE")
    assert w["severity"] == "high"


def test_a_sensitivity_table_that_does_not_say_what_it_was_built_on_is_not_trusted(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    _edit(d, "sensitivity.json", lambda doc: doc.pop("graded_against", None))
    assert "SENSITIVITY_STALE" in _codes(_compose(d))


def test_a_self_check_graded_on_an_earlier_sizing_is_disclosed_not_blocked(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())
    assert "CHECKLIST_STALE" not in _codes(_compose(d))
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    data = _compose(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "CHECKLIST_STALE")
    assert w["severity"] == "medium"


# --- a sizing that does not say where its figures came from -----------------------------------------


def _numeric_dir(tmp_path: Path, validation: dict[str, Any], inputs: dict[str, Any] | None = None) -> Path:
    d = tmp_path / "analysis"
    d.mkdir()
    (d / "validation.json").write_text(json.dumps(_stamp(validation)))
    (d / "inputs.json").write_text(json.dumps(_stamp({"company_name": "TestCo", "currency": "USD", **(inputs or {})})))
    (d / "methodology.json").write_text(json.dumps(_stamp({**_VALID_METHODOLOGY, "approach_chosen": "top_down"})))
    (d / "checklist.json").write_text(json.dumps(_stamp(_VALID_CHECKLIST)))
    (d / "sensitivity.json").write_text(json.dumps(_stamp(_VALID_SENSITIVITY)))
    rc, out, err = run_script_raw(
        "market_sizing.py",
        ["--stdin", "--run-id", _RUN, "-o", str(d / "sizing.json")],
        stdin_data=json.dumps({"approach": "top_down", "industry_total": 5e9, "segment_pct": 20, "share_pct": 5}),
    )
    assert rc == 0, out + err
    return d


def test_numbers_typed_beside_real_research_are_not_graded_as_that_research(tmp_path: Path) -> None:
    """Skipping the references must not be a way past every check: the sizing is named unchecked, and
    nothing is graded by a name match with the research."""
    d = _numeric_dir(tmp_path, _record(_sourced("industry_total", 5e9, "money_total_per_year", currency="USD")))
    data = _compose(d)
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "SIZING_NOT_CHECKED")
    assert w["severity"] == "high"
    assert data["provenance"]["top_down"]["tam"]["classification"] == "unknown"


def test_pure_calculation_on_the_founders_own_figures_is_disclosed_not_blocked(tmp_path: Path) -> None:
    d = _numeric_dir(
        tmp_path,
        {"skipped": True, "reason": "User-provided inputs"},
        {"existing_claims": {"tam": 5e9}, "existing_claims_detail": {"segment_pct": 20, "share_pct": 5}},
    )
    data = _compose(d)
    codes = _codes(data)
    assert "SIZING_NOT_CHECKED" not in codes
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "INPUTS_USER_PROVIDED")
    assert w["severity"] == "medium"


def test_a_stub_record_with_a_figure_that_is_not_the_founders_is_unchecked(tmp_path: Path) -> None:
    """Writing the stub is not a way to escape the research checks: the calm label is true only when
    every figure really is the founder's."""
    d = _numeric_dir(tmp_path, {"skipped": True, "reason": "User-provided inputs"}, {"existing_claims": {"tam": 5e9}})
    codes = _codes(_compose(d))
    assert "SIZING_NOT_CHECKED" in codes and "INPUTS_USER_PROVIDED" not in codes


def test_a_declared_percentage_is_not_asked_whether_it_meant_a_hundred_times_more(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record())  # share_pct is an estimate of 0.27, unit percent_points
    assert "IMPLAUSIBLE_PCT_SCALE" not in _codes(_compose(d))
    numeric = run_script(
        "market_sizing.py",
        ["--stdin"],
        stdin_data=json.dumps({"approach": "top_down", "industry_total": 5e9, "segment_pct": 20, "share_pct": 0.27}),
    )[1]
    assert numeric is not None
    assert "IMPLAUSIBLE_PCT_SCALE" in [w["code"] for w in numeric["validation"]["warnings"]]


def test_an_estimate_is_found_from_what_the_sizing_used_not_from_a_name(tmp_path: Path) -> None:
    """The research keeps an unsourced entry named like an input the sizing took from sourced
    research: that is not an unstress-tested estimate. The sizing's own estimate is."""
    record = _record({"name": "segment_pct_guess", "value": 40, "unit": "percent_points", "category": "agent_estimate"})
    record["assumptions"].append({"name": "industry_total", "value": 1, "unit": "count", "category": "agent_estimate"})
    d = _run_dir(tmp_path, record)
    w = [w for w in _compose(d)["validation"]["warnings"] if w["code"] == "UNSOURCED_ASSUMPTIONS"]
    assert w and "Market Share" in w[0]["message"] and "Industry Total" not in w[0]["message"]


def test_the_founders_figure_is_found_by_what_the_sizing_references(tmp_path: Path) -> None:
    record = _record(_sourced("addressable", 100_000, "count"), _sourced("svc", 50, "percent_points"))
    inputs_extra = {"founder_stated_inputs": {"arpu": 157}, "founder_stated_inputs_period": {"arpu": "month"}}
    bu = {
        "approach": "bottom_up",
        "customer_count": {"assumption": "addressable"},
        "arpu": {"assumption": "care_price"},
        "serviceable_pct": {"assumption": "svc"},
        "target_pct": {"estimate": 10, "unit": "percent_points", "why": "Channel capacity."},
    }
    d = _run_dir(tmp_path, record, bu)
    _edit(d, "inputs.json", lambda i: i.update(inputs_extra))
    _stamp_downstream(d)
    assert "FOUNDER_VALUE_OVERRIDDEN" in _codes(_compose(d))  # research price used, founder's stated
    uplift = {
        "derived": {
            "op": "multiply",
            "factors": [{"founder_stated": "arpu"}, {"estimate": 1.1, "unit": "ratio", "why": "Onboarding fee."}],
        }
    }
    (d / "sizing.json").unlink()
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps({**bu, "arpu": uplift}),
    )
    assert rc == 0, out + err
    _stamp_downstream(d)
    assert "FOUNDER_VALUE_OVERRIDDEN" not in _codes(_compose(d))  # derived FROM the founder's figure


def test_a_percentage_recorded_under_any_name_multiplies_out_as_a_percentage(tmp_path: Path) -> None:
    share = {
        "name": "regulated_smb_share",
        "value": 16,
        "unit": "percent_points",
        "category": "derived",
        "factors": [
            {"factor_id": "regulated", "value": 0.4, "source_id": "company_stated"},
            {"factor_id": "smb", "value": 0.4, "source_id": "company_stated"},
        ],
    }
    d = _run_dir(tmp_path, _record(share))
    assert "FACTOR_PRODUCT_MISMATCH" not in _codes(_compose(d))


def test_a_figure_with_no_unit_is_never_printed_as_money(tmp_path: Path) -> None:
    d = _numeric_dir(tmp_path, _record({"name": "industry_total", "value": 36_000_000, "category": "sourced"}))
    md = _compose(d)["report_markdown"]
    assert "$36.0M" not in md and "36,000,000" in md


# --- a grade is earned by the record, and every surface shows the same one ---------------------------


def test_sourced_with_no_source_list_to_name_is_an_estimate(tmp_path: Path) -> None:
    """The schema requires `sources[]`, and "sourced" means naming an entry in it. A record that lists
    no sources at all cannot be pointed at, so its "sourced" figures grade as estimates."""
    d = _run_dir(tmp_path, {**_record(), "sources": []})
    assert _compose(d)["provenance"]["top_down"]["tam"]["classification"] == "agent_estimate"


def _unlisted_source_record() -> dict[str, Any]:
    rec = _record()
    rec["assumptions"][2].update(source_title="A blog post", source_url="https://blog.example/post")
    return rec


def test_a_source_the_record_does_not_list_is_an_estimate_in_the_assumptions_list(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _unlisted_source_record())
    line = next(x for x in _compose(d)["report_markdown"].splitlines() if x.startswith("- **Segment"))
    assert "(Estimate)" in line and "(Sourced)" not in line, line


def test_the_html_counts_grades_the_way_the_markdown_lists_them(tmp_path: Path) -> None:
    """Both pages grade from one place. The record claims three sourced figures; one names a source the
    record never listed, and the sizing used one estimate of its own, so two are sourced and two are
    estimates -- on both pages."""
    d = _run_dir(tmp_path, _unlisted_source_record())
    md = _compose(d)["report_markdown"]
    listed = [x for x in md.split("## Assumptions", 1)[1].split("\n## ", 1)[0].splitlines() if x.startswith("- **")]
    assert sum("(Sourced)" in x for x in listed) == 2 and sum("(Estimate)" in x for x in listed) == 2, listed
    html = _html(d)
    assert "Sourced: 2" in html and "Agent Estimate: 2" in html


def test_the_html_says_why_the_sizing_used_an_estimate_over_research(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _record(_sourced("share_pct", 2.0, "percent_points")))
    html = _html(d)
    assert "The deck&#x27;s own long-run capture target." in html or "The deck's own long-run capture target." in html
    assert "The research recorded 2%; the sizing used this estimate instead." in html


def test_the_method_table_prints_each_input_by_what_it_measures(tmp_path: Path) -> None:
    md = _compose(_run_dir(tmp_path, _record()))["report_markdown"]
    sam = next(x for x in md.splitlines() if x.startswith("| SAM |") and "Segment" in x)
    assert "Segment %: 37%" in sam, sam
    som = next(x for x in md.splitlines() if x.startswith("| SOM |") and "Share" in x)
    assert "Market Share %: 0.27%" in som, som


def test_a_second_review_that_is_the_first_one_copied_is_not_a_second_review(tmp_path: Path) -> None:
    """A re-pipe of the same hand-off replaces its round, so a genuine round 2 was built from a different
    hand-off. A round-2 copy carrying round 1's hand-off hash was written by hand: it licenses nothing,
    and the review the founder reads is round 1's."""
    d = _reviewed_dir(tmp_path)
    _edit(
        d,
        "methodology.json",
        lambda m: m.update(
            red_team_revision={
                "approved_by_founder": True,
                "founder_words": "Yes, use 30%.",
                "changes": [{"field": "segment_pct", "from": 37, "to": 30}],
            }
        ),
    )
    _edit(d, "validation.json", lambda v: v["assumptions"][2].update(value=30))
    _replay(d)
    copies = d / "handoff" / _RUN
    r1 = json.loads((copies / "redteam.r1.json").read_text())
    import importlib

    sys.path.insert(0, str(_SCRIPTS))
    state = importlib.import_module("_redteam_copy").reviewed_state(str(d))
    forged = {**r1, "inputs_reviewed": state}
    forged["_review_copy"] = {**r1["_review_copy"], "round": 2}
    (copies / "redteam.r2.json").write_text(json.dumps(forged))
    (d / "redteam.json").write_text(json.dumps({k: v for k, v in forged.items() if k != "_review_copy"}))
    codes = _codes(_compose(d))
    assert "REDTEAM_ALTERED" in codes and "RECORD_CHANGED_AFTER_REVIEW" in codes, codes
    # Rewriting the stored hash too is part of the same edit of the same file; the findings are still
    # round 1's, and that is what is compared.
    forged["_review_copy"]["handoff_sha256"] = "0" * 64
    (copies / "redteam.r2.json").write_text(json.dumps(forged))
    codes = _codes(_compose(d))
    assert "REDTEAM_ALTERED" in codes and "RECORD_CHANGED_AFTER_REVIEW" in codes, codes


def _typed_in_after_review(d: Path) -> None:
    rc, out, err = run_script_raw(
        "market_sizing.py",
        ["--stdin", "--run-id", _RUN, "-o", str(d / "sizing.json")],
        stdin_data=json.dumps({"approach": "top_down", "industry_total": 5e9, "segment_pct": 20, "share_pct": 5}),
    )
    assert rc == 0, out + err


def test_typed_in_numbers_after_a_review_of_references_are_a_change_after_the_review(tmp_path: Path) -> None:
    """The review saw figures taken from the research. Re-running the sizing on typed numbers is a change
    the review never saw; "re-run the sizing step" (the remedy for unchecked numbers) is not the answer."""
    d = _reviewed_dir(tmp_path)
    _typed_in_after_review(d)
    codes = _codes(_compose(d))
    assert "RECORD_CHANGED_AFTER_REVIEW" in codes and "SIZING_NOT_CHECKED" not in codes, codes


def test_a_sizing_stripped_of_its_stamp_after_the_review_is_a_change_after_the_review(tmp_path: Path) -> None:
    d = _reviewed_dir(tmp_path)
    for key in ("provenance_version", "input_refs", "input_provenance"):
        _edit(d, "sizing.json", lambda s, k=key: s.pop(k, None))
    codes = _codes(_compose(d))
    assert "RECORD_CHANGED_AFTER_REVIEW" in codes and "SIZING_NOT_CHECKED" not in codes, codes


# --- structural: the owners stay the only owners -------------------------------------------------------

# Registries whose job is to be CHECKED: the remedy rule's test reads them and nothing in production
# needs to. Each must actually be read by a test (asserted below), so this list cannot hide a constant
# nobody uses.
_READ_BY_CONTRACT_TESTS = {("_view", "INTEGRITY_REMEDY"), ("_provenance", "REMEDY_KINDS")}


def _public_names(module_file: Path) -> list[str]:
    import ast

    names: list[str] = []
    for node in ast.parse(module_file.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names += [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return [n for n in names if not n.startswith("_")]


def _names_used(source: str) -> set[str]:
    """Names CODE refers to: bare names, attribute access and imports. Never comments or strings, so a
    docstring that mentions a name, or a list that spells it, does not count as using it."""
    import ast

    used: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            used |= {a.name for a in node.names}
    return used


def test_every_public_name_of_the_shared_modules_is_used_by_another_script() -> None:
    """A name declared for others and read by none is a promise nothing keeps: two constants on this
    branch declared a unit for figures nothing rendered by it. Private it, use it, or delete it."""
    scripts = {p.name: p.read_text() for p in _SCRIPTS.glob("*.py")}
    tests: set[str] = set()
    for path in _TESTS.glob("test_*.py"):
        tests |= _names_used(path.read_text())
    unused = []
    for module in ("_params", "_view", "_provenance"):
        others: set[str] = set()
        for name, text in scripts.items():
            if name != f"{module}.py":
                others |= _names_used(text)
        for name in _public_names(_SCRIPTS / f"{module}.py"):
            if (module, name) in _READ_BY_CONTRACT_TESTS:
                assert name in tests, f"{module}.{name} is listed as test-read but no test reads it"
            elif name not in others:
                unused.append(f"{module}.{name}")
    assert unused == [], unused


def test_the_html_never_grades_the_research_record_itself() -> None:
    """Every grade the founder sees comes from `_view`; visualize reading the record's own claims is how
    report.html once counted a figure as sourced that report.md called an estimate."""
    source = (_SCRIPTS / "visualize.py").read_text()
    assert '"assumptions"' not in source and "'assumptions'" not in source


def test_the_growth_projection_is_produced_and_no_page_reads_it(tmp_path: Path) -> None:
    """growth_rate and years stay plain numbers in the hand-off: nothing references or grades them. That
    is safe only while no page shows the projection they feed. The first page to read it fails here and
    has to give them references first. The positive half keeps a rename from passing this silently.

    Not covered: the red-team sub-agent is handed the whole sizing file, `projected` included, and its
    findings reach the founder. It attacks what it reads rather than endorsing it, so this is named in
    the plan's known limits instead of guarded here."""
    import re

    d = _run_dir(tmp_path, _record(), {**_REFS, "growth_rate": 12, "years": 5})
    assert "projected" in json.loads((d / "sizing.json").read_text())["top_down"]
    for renderer in ("compose_report.py", "visualize.py", "_view.py", "closing_message.py"):
        assert not re.search(r"\bprojected\b", (_SCRIPTS / renderer).read_text()), renderer


def _list_the_blog(v: dict[str, Any]) -> None:
    v["sources"].append({"title": "A blog post", "url": "https://blog.example/post"})


def test_a_grade_raised_after_the_sizing_ran_is_named_before_the_review(tmp_path: Path) -> None:
    """Listing a source after the sizing ran changes no value, but it raises a grade the sizing stamped
    lower. The pages would then disagree with themselves: the list says sourced, the sizing's own
    provenance says estimate."""
    d = _run_dir(tmp_path, _unlisted_source_record())
    _edit(d, "validation.json", _list_the_blog)
    assert "SIZING_STALE" in _codes(_compose(d))


def test_a_grade_raised_after_the_review_is_a_change_after_the_review(tmp_path: Path) -> None:
    d = _run_dir(tmp_path, _unlisted_source_record())
    _edit(d, "methodology.json", lambda m: m.pop("red_team_skipped", None))
    _review(d, "The published share is 30%.")
    _edit(d, "validation.json", _list_the_blog)
    _replay(d)
    assert "RECORD_CHANGED_AFTER_REVIEW" in _codes(_compose(d))


def test_the_method_narrative_prints_each_input_by_what_it_measures(tmp_path: Path) -> None:
    md = _compose(_run_dir(tmp_path, _record()))["report_markdown"]
    assert "targeting 37% segment with 0.27% market share." in md


# --- a figure the sizing is built from is never "not used" ---------------------------------------

# Run 1's shape: the sizing references a figure the record derived from two others, whose factors
# name them by `factor_id` and carry no `source_id`.
_BUILT_FROM = [
    {**_sourced("utilization_pct", 3.4, "percent_points")},
    {
        "name": "enrolled_population",
        "label": "Members enrolled in the program",
        "value": 1_394_000,
        "unit": "count",
        "category": "derived",
        "factors": [
            {"factor_id": "eligible_population", "value": 41_000_000},
            {"factor_id": "utilization_pct", "value": 3.4},
        ],
    },
    {**_sourced("unrelated_context", 7, "count"), "label": "Unrelated context figure"},
]
_REFS_BUILT_FROM = {
    **_REFS,
    "industry_total": {
        "derived": {"op": "multiply", "factors": [{"assumption": "enrolled_population"}, {"assumption": "care_price"}]}
    },
}


def test_the_figures_a_used_figure_is_built_from_are_not_called_unused(tmp_path: Path) -> None:
    """A live report labelled the 41M-style population and the 3.4% rate "research context; not used
    in the sizing" while their product was the customer count the sizing consumed: `used` held only
    the figures the sizing named directly and never followed a derivation's factors."""
    d = _run_dir(tmp_path, _record(*_BUILT_FROM), _REFS_BUILT_FROM)
    md = _compose(d)["report_markdown"]
    section = md[md.index("## Assumptions") :]
    rows = {line.split("**")[1]: line for line in section.splitlines() if line.startswith("- **")}
    for label in ("Eligible Population", "Utilization Pct", "Members enrolled in the program"):
        row = next(v for k, v in rows.items() if k.startswith(label))
        assert "not used in the sizing" not in row, row
    # Positive control: the walk must not mark everything used.
    assert "not used in the sizing" in next(v for k, v in rows.items() if k.startswith("Unrelated context"))


# --- one text, both delivered pages -------------------------------------------------------------------

# A sub-agent writes an estimate's `why` as free prose and names a record entry by its identifier. All
# segments are alphabetic on purpose, so the shared policy can DETECT it -- the point here is which
# surfaces get the repair, not the policy's own detection limits.
_REFS_LEAKY_WHY: dict[str, Any] = {
    **_REFS,
    "share_pct": {
        "estimate": 0.27,
        "unit": "percent_points",
        "why": "Derived against eligible_population rather than a sourced capture rate.",
    },
}


def test_an_estimates_reason_reads_the_same_on_both_delivered_pages(tmp_path: Path) -> None:
    """report.md and report.html rendered the same sentence differently.

    compose substitutes the whole document through the founder-text policy; visualize never referenced
    it, so an identifier a sub-agent wrote into an estimate's reason was repaired on the markdown and
    shipped raw in the HTML. Both pages read these rows from ONE owner, so the repair belongs there
    rather than as a second policy copy in the renderer.
    """
    d = _run_dir(tmp_path, _record(), _REFS_LEAKY_WHY)
    md = _compose(d)["report_markdown"]
    html_text = _text_nodes(_html(d))
    for surface, text in (("report.md", md), ("report.html", html_text)):
        assert "eligible_population" not in text, f"{surface} carries the raw identifier"
        assert "eligible population" in text, f"{surface} lost the humanized form"


# --- figures that do not fit the canonical shape ------------------------------------------------------

# The shapes the live artifact uses, with invented content: a figure leaf, a plain scalar, a nested map
# of figures, and a `label` describing its parent. The three key shapes the shared humanizer leaves
# alone are all here on purpose -- a digit-leading segment, a trailing year, a trailing number.
_NESTED_CLAIMS: dict[str, Any] = {
    "deck_headline_slide_4": {
        "buyers_total": {"value": 50_000_000, "unit": "count", "label": "Buyers in the category"},
        "target_price": {"value": 40, "unit": "money_per_customer", "currency": "USD", "period": "month"},
        "revenue_framing": {"value": 75_000_000, "unit": "money_total_per_year", "currency": "USD"},
    },
    "18_month_plan_case": {
        "label": "Staged launches at a modelled conversion.",
        "active_buyers_april_2028": {"value": 900, "unit": "count"},
        "horizon_months_from_close": 18,
        "conversion_sensitivity": {
            "low": {"value": 1_000_000, "unit": "money_total_per_year", "currency": "USD"},
            "high": {"value": 4_000_000, "unit": "money_total_per_year", "currency": "USD"},
        },
    },
}


def _claims_dir(tmp_path: Path) -> Path:
    d = _run_dir(tmp_path, _record())
    _edit(d, "inputs.json", lambda i: i.update(existing_claims_detail=_NESTED_CLAIMS))
    return d


def _text_nodes(html: str) -> str:
    """Founder-visible text only: script and style bodies are not prose, and attributes are not read."""
    return visible_text(html)


_LITERAL = re.compile(r"[{\[]\s*['\"]")


def test_no_founder_surface_contains_a_dict_or_list_literal(tmp_path: Path) -> None:
    """A structural guard the humanizer CANNOT satisfy by glossing a token.

    `str()` on a nested mapping put a Python repr in front of founders -- quoted keys, nested braces
    and six unit enums -- and every founder-text detector reported clean, because the humanizer had
    glossed the enums in place and the remaining keys were data, not vocabulary it knows. Asserted on
    the DELIVERED surfaces, so it cannot pass on a renderer whose output never reaches a page.
    """
    d = _claims_dir(tmp_path)
    composed = _compose(d)
    for surface, text in (
        ("report.md", composed["report_markdown"]),
        ("verdict", str(composed.get("verdict") or "")),
        ("report.html", _text_nodes(_html(d))),
    ):
        found = _LITERAL.search(text)
        assert not found, (
            f"{surface} carries a mapping literal at {found.start()}: {text[found.start() - 60 : found.start() + 90]!r}"
        )


def test_stated_figures_that_do_not_fit_the_canonical_shape_render_as_labelled_lines(tmp_path: Path) -> None:
    """Each figure printed by its own unit, each key as words, each nested map indented under its key.

    The keys are the FOUNDER's own, so they are spaced here rather than passed to the shared policy,
    which leaves a token with a numeric segment alone to protect stable ids.
    """
    md = _compose(_claims_dir(tmp_path))["report_markdown"]
    section = md[md.index("## Your Stated Figures (Narrative)") :]
    section = section[: section.index("\n## ")] if "\n## " in section else section

    assert "**Deck headline slide 4:**" in section  # trailing number
    assert "**18 month plan case:**" in section  # digit-leading segment
    assert "**Active buyers april 2028:**" in section  # trailing year
    assert "Staged launches at a modelled conversion." in section  # a parent's own label

    assert "50,000,000" in section and "Buyers in the category" in section  # a count, with its label
    assert "$40.00 per month" in section  # a per-customer price keeps its period
    assert "$75.0M" in section  # a money total by its own unit
    assert "**Horizon months from close:** 18" in section  # a plain scalar
    assert "**Conversion sensitivity:**" in section and "$1.0M" in section  # a nested map, indented

    # No unit enum reaches the prose, humanized or not: the unit decides the format, it is not printed.
    for enum in ("money_total_per_year", "money total per year", "money_per_customer", "money per customer"):
        assert enum not in section, enum


# --- a figure the founder stated, also carried by a record entry -------------------------------------

_STATED_BU: dict[str, Any] = {
    "approach": "bottom_up",
    "customer_count": {"assumption": "addressable"},
    "arpu": {"assumption": "care_price"},
    "serviceable_pct": {"assumption": "svc"},
    "target_pct": {"estimate": 10, "unit": "percent_points", "why": "Channel capacity."},
}


def _stated_arpu_dir(tmp_path: Path, *extra: dict[str, Any], stated: float = 157) -> Path:
    """A bottom-up sizing whose `arpu` is what the FOUNDER stated, not a record entry.

    `_run_dir` sizes before `inputs.json` can carry `founder_stated_inputs`, so the founder-stated
    reference is sized in a second pass, the way the live pipeline reaches it.
    """
    record = _record(_sourced("addressable", 100_000, "count"), _sourced("svc", 50, "percent_points"), *extra)
    d = _run_dir(tmp_path, record, _STATED_BU)
    _edit(
        d,
        "inputs.json",
        lambda i: i.update(
            founder_stated_inputs={"arpu": stated},
            founder_stated_inputs_period={"arpu": "month"},
        ),
    )
    (d / "sizing.json").unlink()
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps({**_STATED_BU, "arpu": {"founder_stated": "arpu"}}),
    )
    assert rc == 0, out + err
    _stamp_downstream(d)
    return d


def _assumption_rows(d: Path) -> dict[str, str]:
    md = _compose(d)["report_markdown"]
    section = md[md.index("## Assumptions") :]
    return {line.split("**")[1]: line for line in section.splitlines() if line.startswith("- **")}


def _row(d: Path, label: str) -> str:
    rows = _assumption_rows(d)
    return next(v for k, v in rows.items() if k.startswith(label))


def test_a_record_entry_holding_the_founders_stated_figure_is_not_called_unused(tmp_path: Path) -> None:
    """A live report labelled the per-customer price "research context; not used in the sizing" while
    that figure WAS the `arpu` the whole bottom-up build rested on: the founder-stated leaf stamps a
    synthetic `founder:<key>` entry, so a record entry carrying the same figure could never be in
    `used`. The derived-factor walk cannot reach it either -- the leaf has no factors."""
    d = _stated_arpu_dir(tmp_path)
    assert "not used in the sizing" not in _row(d, "Care Price"), _row(d, "Care Price")
    # Positive control: a figure this sizing genuinely does not touch still says so.
    assert "not used in the sizing" in _row(d, "Eligible Population")


def test_a_record_entry_named_like_the_param_with_a_different_value_stays_unused(tmp_path: Path) -> None:
    """The match is on the FIGURE, never the name. Joining the record to the sizing by name without
    comparing values is the defect the derived-factor fix was written for, in reverse."""
    d = _stated_arpu_dir(tmp_path, _sourced("arpu", 999, "money_per_customer", currency="USD", period="month"))
    assert "not used in the sizing" in _row(d, "ARPU")


def test_a_record_entry_with_the_founders_value_but_a_different_period_stays_unused(tmp_path: Path) -> None:
    """$157 a month and $157 a year are different figures. Period is part of a per-customer price."""
    d = _stated_arpu_dir(tmp_path, _sourced("yearly_price", 157, "money_per_customer", currency="USD", period="year"))
    assert "not used in the sizing" in _row(d, "Yearly")


def test_a_record_entry_with_the_founders_value_but_a_different_unit_stays_unused(tmp_path: Path) -> None:
    """157 people is not $157 per customer. The unit the slot requires is part of the comparison."""
    d = _stated_arpu_dir(tmp_path, _sourced("people_count", 157, "count"))
    assert "not used in the sizing" in _row(d, "People")


def test_a_record_entry_near_but_not_equal_to_the_founders_value_stays_unused(tmp_path: Path) -> None:
    """Near-miss control: equality is exact, so a figure that merely rounds to the founder's is a
    different figure and keeps saying so."""
    d = _stated_arpu_dir(tmp_path, _sourced("almost", 157.5, "money_per_customer", currency="USD", period="month"))
    assert "not used in the sizing" in _row(d, "Almost")


# --- a recorded figure the sizing typed in as an estimate ------------------------------------------


def _inlined_estimate_dir(tmp_path: Path, *extra: dict[str, Any]) -> Path:
    """A live sizing multiplied a population by a sourced 35% it had recorded, but wrote that 35% into
    the derivation as an estimate (0.35, a fraction) instead of referencing the entry."""
    refs = {
        **_REFS,
        "industry_total": {
            "derived": {
                "op": "multiply",
                "factors": [
                    {
                        "derived": {
                            "op": "multiply",
                            "factors": [
                                {"assumption": "employment"},
                                {"estimate": 0.35, "unit": "fraction", "why": "35% expressed as a fraction."},
                            ],
                        }
                    },
                    {"assumption": "care_price"},
                ],
            }
        },
    }
    record = _record(
        _sourced("employment", 2_000_000, "count"),
        _sourced("access_pct", 35, "percent_points", label="Share of workers with access"),
        *extra,
    )
    return _run_dir(tmp_path, record, refs)


def test_a_recorded_figure_the_sizing_typed_in_as_an_estimate_is_not_called_unused(tmp_path: Path) -> None:
    """A live report labelled a sourced 35% "research context; not used in the sizing" while the
    sizing multiplied by 0.35: the derivation carried the number as an estimate, so no reference
    named the entry. The same-figure comparison the founder-stated path uses reaches it."""
    d = _inlined_estimate_dir(tmp_path)
    assert "not used in the sizing" not in _row(d, "Share of workers"), _row(d, "Share of workers")
    # Positive control: a figure this sizing genuinely does not touch still says so.
    assert "not used in the sizing" in _row(d, "Eligible Population")


def test_a_recorded_figure_near_an_inlined_estimate_stays_unused(tmp_path: Path) -> None:
    """Near-miss control: 36% is not 0.35, so it keeps its label."""
    d = _inlined_estimate_dir(tmp_path, _sourced("other_pct", 36, "percent_points", label="Some other share"))
    assert "not used in the sizing" in _row(d, "Some other share")


def test_a_recorded_count_equal_to_an_inlined_fraction_stays_unused(tmp_path: Path) -> None:
    """Unit control: a count of 0.35 is not a fraction of 0.35."""
    d = _inlined_estimate_dir(tmp_path, _sourced("tiny_count", 0.35, "count", label="A tiny count"))
    assert "not used in the sizing" in _row(d, "A tiny count")


def test_a_record_entry_matching_the_founders_figure_is_not_a_change_to_the_reviewed_analysis(
    tmp_path: Path,
) -> None:
    """The same-figure fact must NOT widen `entries`, which means "the sizing depends on this" and is
    what the review diff compares. A record entry that merely equals the founder's stated figure is not
    an input, so editing it after the review is not a change to the analysis that was reviewed."""
    d = _stated_arpu_dir(tmp_path)
    _edit(d, "methodology.json", lambda m: m.pop("red_team_skipped", None))
    _review(d, "The published share is 30%.")
    assert "RECORD_CHANGED_AFTER_REVIEW" not in _codes(_compose(d))
    _edit(
        d,
        "validation.json",
        lambda v: v["assumptions"].__setitem__(
            next(i for i, a in enumerate(v["assumptions"]) if a["name"] == "care_price"),
            _sourced("care_price", 157, "money_per_customer", currency="USD", period="month", label="Reworded."),
        ),
    )
    assert "RECORD_CHANGED_AFTER_REVIEW" not in _codes(_compose(d))


def test_matching_the_founders_figure_does_not_silence_a_real_override(tmp_path: Path) -> None:
    """FOUNDER_VALUE_OVERRIDDEN decides on `entries` too. A record entry equal to the founder's stated
    figure must not make a sizing that used a DIFFERENT figure look like it used theirs."""
    record = _record(
        _sourced("addressable", 100_000, "count"),
        _sourced("svc", 50, "percent_points"),
        _sourced("other_price", 300, "money_per_customer", currency="USD", period="month"),
    )
    d = _run_dir(tmp_path, record, _STATED_BU)  # arpu references care_price (157), not the founder
    _edit(
        d,
        "inputs.json",
        lambda i: i.update(
            founder_stated_inputs={"arpu": 300},
            founder_stated_inputs_period={"arpu": "month"},
        ),
    )
    _stamp_downstream(d)
    assert "FOUNDER_VALUE_OVERRIDDEN" in _codes(_compose(d))


def test_listed_factors_without_a_source_are_named_as_such(tmp_path: Path) -> None:
    """The same run warned the derivation's factors were "not recorded separately" -- they were, by
    factor_id, and lacked only a source. The warning names what is missing."""
    d = _run_dir(tmp_path, _record(*_BUILT_FROM), _REFS_BUILT_FROM)
    w = next(w for w in _compose(d)["validation"]["warnings"] if w["code"] == "UNSTRUCTURED_DERIVATION")
    assert "not recorded separately" not in w["message"]
    assert "source" in w["message"]


# --- rewording an estimate's reason is not a change to the analysis ----------------------------------

_SHARE: dict[str, Any] = {"estimate": 0.27, "unit": "percent_points", "why": "The deck's own long-run capture target."}
assert _REFS["share_pct"] == _SHARE


def _resize(d: Path, refs: dict[str, Any]) -> None:
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(refs),
    )
    assert rc == 0, out + err
    _stamp_downstream(d)


def test_rewording_an_estimates_reason_after_the_review_is_not_a_change(tmp_path: Path) -> None:
    """A live run's founder chose to deliver; the founder-text check then flagged a file name inside an
    estimate's `why`, and rewording it fired RECORD_CHANGED_AFTER_REVIEW (high), because the review's
    snapshot compared the whole reference, prose included. Its remedies were to put the file name back
    or re-review -- which the founder had declined -- and the model wrote the founder's approval itself.
    A reference is compared on what it computes; its wording is not the analysis."""
    d = _reviewed_dir(tmp_path)
    reworded = {**_REFS, "share_pct": {**_SHARE, "why": "The long-run capture target the deck sets out."}}
    _resize(d, reworded)
    assert "RECORD_CHANGED_AFTER_REVIEW" not in _codes(_compose(d))


def test_rewording_an_estimates_reason_does_not_make_the_downstream_tables_stale(tmp_path: Path) -> None:
    """The same run then re-ran sensitivity and the checklist: the sizing's fingerprint hashed the
    references with their prose, so the tables graded against it read as stale (high)."""
    d = _run_dir(tmp_path, _record())
    reworded = {**_REFS, "share_pct": {**_SHARE, "why": "The long-run capture target the deck sets out."}}
    rc, out, err = run_script_raw(
        "market_sizing.py",
        [
            "--stdin",
            "--validation",
            str(d / "validation.json"),
            "--inputs",
            str(d / "inputs.json"),
            "--run-id",
            _RUN,
            "-o",
            str(d / "sizing.json"),
        ],
        stdin_data=json.dumps(reworded),
    )
    assert rc == 0, out + err
    codes = _codes(_compose(d))
    assert "SENSITIVITY_STALE" not in codes and "CHECKLIST_STALE" not in codes, codes


def test_changing_an_estimates_value_after_the_review_is_still_a_change(tmp_path: Path) -> None:
    """Positive control: the comparison still sees what the estimate computes."""
    d = _reviewed_dir(tmp_path)
    _resize(d, {**_REFS, "share_pct": {**_SHARE, "estimate": 0.5}})
    assert "RECORD_CHANGED_AFTER_REVIEW" in _codes(_compose(d))
