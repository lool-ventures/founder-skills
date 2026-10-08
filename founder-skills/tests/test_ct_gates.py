"""cap-table's recorded gates, through the real scripts.

The questions a cap-table review rests on are recorded in the run's ledger, and each producer refuses (exit 10)
until the ones it rests on are recorded: the cap state on the engagement, the structure, IIA and the confirmed
base; the scenario solver on the scenarios chosen, the note questions and the pool questions; the extraction on
the founder's confirmation of the values it flagged, before it saves them. A what-if on a delivered review reopens
it as a new revision and asks a question its request contradicts again. Every name and figure here is invented.
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402
import no_ledger_goldens as goldens  # noqa: E402

CT = "cap-table"
SCRIPTS = h.SKILLS / CT / "scripts"
SKILL_MD = h.SKILLS / CT / "SKILL.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / CT


def _load(name: str, path: Path | None = None) -> ModuleType:
    if path is None and name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, path or h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    if path is None:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


g = _load("_gates")


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    return data


def _ok(proc: Any) -> Any:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def ct(script: str, *args: str, stdin: str | None = None) -> Any:
    return h.run(SCRIPTS / script, *args, stdin=stdin)


def entry(root: Path, rid: str, key: str) -> dict[str, Any]:
    e: dict[str, Any] = (h.ledger(root, rid).get("gates") or {}).get(key) or {}
    return e


def answer(root: Path, rid: str, key: str, option: str, value: str | None = None) -> Any:
    h.record(root, rid, "open", "--gate", key)
    extra = ["--value", value] if value is not None else []
    return _ok(h.record(root, rid, "answer", "--gate", key, "--answer-id", option, *extra))


def write(rd: Path, name: str, doc: Any) -> None:
    rd.mkdir(parents=True, exist_ok=True)
    (rd / name).write_text(json.dumps(doc), encoding="utf-8")


def fixture_dir(rd: Path, rid: str, *, note: bool = False, structure: str = "delaware") -> None:
    """The committed cap-table fixture under this run's id, with a stated structure."""
    for name in ("inputs.json", "instruments.json"):
        doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        doc["metadata"]["run_id"] = rid
        if name == "inputs.json":
            doc["jurisdiction"] = {"structure": structure}
        if name == "instruments.json" and note:
            doc["convertible_notes"] = [{**goldens.CT_NOTE, "interest_converts_to_shares": True}]
        write(rd, name, doc)


def bound(tmp: Path, *, suffix: str = "", **kw: Any) -> tuple[Path, str, Path]:
    root, rid, rd = h.start_bound(tmp, CT, suffix=suffix)
    if not suffix:
        fixture_dir(rd, rid, **kw)
    return root, rid, rd


def step2(root: Path, rid: str, *, structure: str = "delaware") -> None:
    answer(root, rid, "ct_engagement_mode", "standard")
    answer(root, rid, "ct_jurisdiction", structure)


def cap_state(rd: Path, rid: str) -> Any:
    return ct(
        "cap_state.py",
        "--inputs",
        str(rd / "inputs.json"),
        "--instruments",
        str(rd / "instruments.json"),
        "--run-id",
        rid,
        "-o",
        str(rd / "cap_state.json"),
    )


def scenarios(rd: Path, rid: str, requests: list[dict[str, Any]]) -> Any:
    (rd / "scenario_requests.json").write_text(json.dumps(requests), encoding="utf-8")
    return ct(
        "run_scenario.py",
        "--inputs",
        str(rd / "inputs.json"),
        "--instruments",
        str(rd / "instruments.json"),
        "--cap-state",
        str(rd / "cap_state.json"),
        "--scenarios-input",
        str(rd / "scenario_requests.json"),
        "--run-id",
        rid,
        "-o",
        str(rd / "scenarios.json"),
    )


def ready_for_math(tmp: Path, **kw: Any) -> tuple[Path, str, Path]:
    root, rid, rd = bound(tmp, **kw)
    step2(root, rid)
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    _ok(cap_state(rd, rid))
    return root, rid, rd


PRICED: dict[str, Any] = {"scenario_id": "series_a", "label": "Series A", "type": "priced_round",
          "parameters": {"pre_money": 20000000, "new_money": 5000000,
                         "transaction_event_date": "2026-06-01"}}  # fmt: skip


def priced(**params: Any) -> dict[str, Any]:
    return {**PRICED, "parameters": {**PRICED["parameters"], **params}}


# --- registry and the cap base ------------------------------------------------------------------------------


def test_every_cap_table_predicate_and_source_is_wired() -> None:
    assert g.unimplemented() == {"predicates": [], "option_sources": [], "binders": [], "requires": []}


def test_a_non_base_write_keeps_the_confirmation_and_a_base_change_asks_again(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["stated_totals"] = {"price_per_share": 2.5, "source": "term_sheet"}
    inputs["aoa_findings"] = []
    write(rd, "inputs.json", inputs)
    assert h.record(root, rid, "require", "--gate", "ct_cap_base_confirmation").returncode == 0
    inputs["founders"][0]["common_shares"] += 1000
    write(rd, "inputs.json", inputs)
    assert h.record(root, rid, "require", "--gate", "ct_cap_base_confirmation").returncode == 10


def test_different_leaves_the_base_question_open_until_confirmed(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    answer(root, rid, "ct_cap_base_confirmation", "different", "the pool is larger")
    assert h.status(root, rid)["status"] == "waiting"
    _ok(h.record(root, rid, "answer", "--gate", "ct_cap_base_confirmation", "--answer-id", "confirmed"))
    assert entry(root, rid, "ct_cap_base_confirmation")["state"] == "answered"


def test_a_model_written_provenance_stamp_never_clears_the_base_question(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["metadata"]["cap_base_provenance"] = "deterministic_mapped"
    inputs["metadata"]["cap_base_source"] = "confirmed"
    write(rd, "inputs.json", inputs)
    proc = h.record(root, rid, "require", "--gate", "ct_cap_base_confirmation")
    assert proc.returncode == 10, proc.stdout
    closed = h.record(root, rid, "not-applicable", "--gate", "ct_cap_base_confirmation", "--reason", "mapped")
    assert closed.returncode == 1 and _out(closed)["code"] == "CLOSE_SCRIPT_OWED"


def test_another_runs_inputs_cannot_decide_a_question(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["metadata"]["run_id"] = "20200101T000000Z-aaaaaa"
    write(rd, "inputs.json", inputs)
    proc = h.record(root, rid, "open", "--gate", "ct_cap_base_confirmation")
    assert proc.returncode == 2 and "GATE_UNDECIDABLE" in proc.stdout


def test_the_pool_is_asked_before_the_base_and_the_base_is_asked_once(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["option_pool"] = {}
    write(rd, "inputs.json", inputs)
    answer(root, rid, "ct_option_pool", "provide", "900000 authorized, none issued")
    inputs["option_pool"] = {"plan_type": "iso", "authorized": 900000, "issued": 0, "unallocated": 900000}
    write(rd, "inputs.json", inputs)
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    step2(root, rid)
    _ok(cap_state(rd, rid))
    assert entry(root, rid, "ct_cap_base_confirmation").get("supersessions") in (None, 0)


def test_an_empty_pool_counts_as_unknown(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["option_pool"] = {}
    write(rd, "inputs.json", inputs)
    assert "ct_option_pool" in _out(h.record(root, rid, "open", "--gate", "ct_option_pool"))["opened"]


# --- cap_state.py ---------------------------------------------------------------------------------------------


def test_cap_state_waits_for_each_question_and_writes_nothing(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    proc = cap_state(rd, rid)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_engagement_mode"
    assert not (rd / "cap_state.json").exists()
    step2(root, rid)
    proc = cap_state(rd, rid)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_cap_base_confirmation"
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    _ok(cap_state(rd, rid))


@pytest.mark.parametrize(
    "key, option, change",
    [
        ("ct_engagement_mode", "flip_focused", None),
        ("ct_jurisdiction", "mid_flip", None),
    ],
)
def test_cap_state_refuses_inputs_that_disagree_with_a_recorded_answer(
    tmp_path: Path, key: str, option: str, change: Any
) -> None:
    root, rid, rd = bound(tmp_path)
    answer(root, rid, "ct_engagement_mode", "flip_focused" if key == "ct_engagement_mode" else "standard")
    answer(root, rid, "ct_jurisdiction", option if key == "ct_jurisdiction" else "delaware")
    if key == "ct_jurisdiction":
        answer(root, rid, "ct_iia_grants", "none")
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    proc = cap_state(rd, rid)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert not (rd / "cap_state.json").exists()


def test_iia_is_asked_with_the_structure_and_closes_outside_israel(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    opened = _out(h.record(root, rid, "open", "--gate", "ct_jurisdiction", "--gate", "ct_iia_grants"))
    assert len(opened["needs_input"]) == 2
    _ok(h.record(root, rid, "answer", "--gate", "ct_jurisdiction", "--answer-id", "delaware"))
    assert entry(root, rid, "ct_iia_grants")["state"] == "not_owed"


def test_iia_answer_must_be_written_into_inputs(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path, structure="israeli")
    answer(root, rid, "ct_engagement_mode", "standard")
    answer(root, rid, "ct_jurisdiction", "israeli")
    answer(root, rid, "ct_iia_grants", "yes")
    answer(root, rid, "ct_cap_base_confirmation", "confirmed")
    assert _out(cap_state(rd, rid))["code"] == "GATE_RECORD_MISMATCH"
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["jurisdiction"]["iia_grants_history"] = {"has_grants": True}
    write(rd, "inputs.json", inputs)
    _ok(cap_state(rd, rid))


# --- run-id backstop ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("script", ["cap_state.py", "run_scenario.py", "compose_report.py", "rule_audit.py"])
def test_an_empty_run_id_on_a_ledger_run_is_refused(tmp_path: Path, script: str) -> None:
    root, rid, rd = bound(tmp_path)
    args = {
        "cap_state.py": ["--inputs", str(rd / "inputs.json"), "--instruments", str(rd / "instruments.json"), "-o",
                         str(rd / "cap_state.json")],
        "run_scenario.py": ["--inputs", str(rd / "inputs.json"), "--instruments", str(rd / "instruments.json"),
                            "--cap-state", str(rd / "x.json"), "--scenarios-input", str(rd / "x.json"), "-o",
                            str(rd / "scenarios.json")],
        "compose_report.py": ["--dir", str(rd), "-o", str(rd / "report.json"), "--write-md", str(rd / "report.md")],
        "rule_audit.py": ["--phase=pre_math", "--inputs", str(rd / "inputs.json"), "-o", str(rd / "rule_audit.json")],
    }[script]  # fmt: skip
    proc = ct(script, *args, "--run-id", "")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED"
    assert not any((rd / n).exists() for n in ("cap_state.json", "scenarios.json", "report.json", "rule_audit.json"))


# --- extract_instrument.py -------------------------------------------------------------------------------------


def _extract(rd: Path, rid: str, extraction: dict[str, Any], *extra: str, doc: Path | None = None) -> Any:
    if doc is None:
        doc = rd.parent / "safe.txt"
        doc.write_text(goldens.CT_DOC, encoding="utf-8")
    return ct(
        "extract_instrument.py",
        "--instruments",
        str(rd / "instruments.json"),
        "--run-id",
        rid,
        "--source-doc",
        str(doc),
        "-o",
        str(rd / "extraction_audit.json"),
        *extra,
        stdin=json.dumps(extraction),
    )


def test_flagged_values_are_confirmed_before_they_are_saved(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    before = (rd / "instruments.json").read_bytes()
    proc = _extract(rd, rid, goldens.CT_SAFE_EXTRACTION)
    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert _out(proc)["blocked_by_gate"] == "ct_extraction_confirmation.flagged_fields"
    assert (rd / "instruments.json").read_bytes() == before and not (rd / "extraction_audit.json").exists()
    pending = json.loads((rd / "extraction_pending.json").read_text())
    assert pending["metadata"]["run_id"] == rid and "purchase_amount" in pending["receipt"]["attention_needed_fields"]
    _ok(
        h.record(root, rid, "answer", "--gate", "ct_extraction_confirmation.flagged_fields", "--answer-id", "values_ok")
    )
    _ok(_extract(rd, rid, goldens.CT_SAFE_EXTRACTION))
    saved = json.loads((rd / "instruments.json").read_text())
    assert [s["id"] for s in saved["safes"]] == ["safe_001", "safe_002"]
    assert json.loads((rd / "extraction_audit.json").read_text())["run_id"] == rid


def test_corrections_keep_the_question_open_until_the_corrected_values_are_confirmed(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    assert _extract(rd, rid, goldens.CT_SAFE_EXTRACTION).returncode == 10
    _ok(h.record(root, rid, "answer", "--gate", "ct_extraction_confirmation.flagged_fields", "--answer-id",
                 "has_corrections", "--value", "the cap is 12M"))  # fmt: skip
    # The same content piped again still waits: the founder confirms what is saved.
    assert _extract(rd, rid, goldens.CT_SAFE_EXTRACTION).returncode == 10
    _ok(
        h.record(root, rid, "answer", "--gate", "ct_extraction_confirmation.flagged_fields", "--answer-id", "values_ok")
    )
    _ok(_extract(rd, rid, goldens.CT_SAFE_EXTRACTION))


def test_a_founder_answer_written_back_into_the_note_does_not_ask_the_confirmation_again(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    note: dict[str, Any] = {"instrument_type": "convertible_note", "fields": {**goldens.CT_NOTE}, "confidence": {
        "principal": {"level": "medium", "evidence_quote": "x"}}, "ambiguities": []}  # fmt: skip
    proc = _extract(rd, rid, note, "--no-verify", "--no-invariants")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    _ok(
        h.record(root, rid, "answer", "--gate", "ct_extraction_confirmation.flagged_fields", "--answer-id", "values_ok")
    )
    _ok(_extract(rd, rid, note, "--no-verify", "--no-invariants"))
    answer(root, rid, "ct_note_qualified_threshold", "different_amount", "2000000")
    written = {**note, "fields": {**note["fields"], "qualified_financing_threshold": 2000000}}
    _ok(_extract(rd, rid, written, "--no-verify", "--no-invariants", "--replace"))
    assert entry(root, rid, "ct_extraction_confirmation.flagged_fields").get("supersessions") in (None, 0)


def test_aoa_fields_is_never_opened_by_the_extraction(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    clean = {**goldens.CT_SAFE_EXTRACTION, "confidence": {
        k: {**v, "level": "high"} for k, v in goldens.CT_SAFE_EXTRACTION["confidence"].items()}}  # fmt: skip
    _ok(_extract(rd, rid, clean))
    assert "ct_extraction_confirmation.aoa_fields" not in (h.ledger(root, rid).get("gates") or {})


def test_a_vision_transcription_needs_its_source_named_and_is_confirmed(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    text = rd.parent / "vision.txt"
    text.write_text(goldens.CT_DOC, encoding="utf-8")
    clean = {**goldens.CT_SAFE_EXTRACTION, "confidence": {
        k: {**v, "level": "high"} for k, v in goldens.CT_SAFE_EXTRACTION["confidence"].items()}}  # fmt: skip
    assert _extract(rd, rid, clean, "--doc-text", str(text)).returncode == 1
    proc = _extract(rd, rid, clean, "--doc-text", str(text), "--doc-text-source", "model_vision")
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_extraction_confirmation.unverifiable_doc"


def test_with_no_ledger_a_text_layer_doc_text_verifies_as_the_document_does(tmp_path: Path) -> None:
    rd = tmp_path / "rd"
    fixture_dir(rd, goldens.CT_RUN)
    text = tmp_path / "text.txt"
    text.write_text(goldens.CT_DOC, encoding="utf-8")
    a = _extract(rd, goldens.CT_RUN, goldens.CT_SAFE_EXTRACTION)
    b = json.loads((rd / "extraction_audit.json").read_text())
    fixture_dir(rd, goldens.CT_RUN)
    c = _extract(rd, goldens.CT_RUN, goldens.CT_SAFE_EXTRACTION, "--doc-text", str(text), "--doc-text-source",
                 "text_layer")  # fmt: skip
    assert a.returncode == c.returncode == 0
    d = json.loads((rd / "extraction_audit.json").read_text())
    assert b["evidence_verification"]["overall_status"] == d["evidence_verification"]["overall_status"]
    assert "run_id" not in d


def test_an_earlier_reviews_instruments_are_never_appended_to(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inst = json.loads((rd / "instruments.json").read_text())
    inst["metadata"]["run_id"] = "20200101T000000Z-bbbbbb"
    write(rd, "instruments.json", inst)
    before = (rd / "instruments.json").read_bytes()
    proc = _extract(rd, rid, goldens.CT_SAFE_EXTRACTION)
    assert proc.returncode == 1 and json.loads(proc.stdout)["error"] == "E_INSTRUMENTS_FILE_UNUSABLE"
    assert (rd / "instruments.json").read_bytes() == before


def _redline(path: Path) -> Path:
    """A minimal .docx built here, with one tracked insertion (never a committed document)."""
    body = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'
        "<w:r><w:t>" + goldens.CT_DOC + "</w:t></w:r>"
        '<w:ins w:id="1" w:author="a"><w:r><w:t> Added.</w:t></w:r></w:ins></w:p></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)
    path.write_bytes(buf.getvalue())
    return path


def test_a_redline_waits_for_the_tracked_changes_answer(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    doc = _redline(tmp_path / "safe.docx")
    clean = {**goldens.CT_SAFE_EXTRACTION, "confidence": {
        k: {**v, "level": "high"} for k, v in goldens.CT_SAFE_EXTRACTION["confidence"].items()}}  # fmt: skip
    proc = _extract(rd, rid, clean, doc=doc)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_docx_tracked_changes"
    _ok(h.record(root, rid, "answer", "--gate", "ct_docx_tracked_changes", "--answer-id", "upload_clean"))
    proc = _extract(rd, rid, clean, doc=doc)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


# --- the scenario solver ---------------------------------------------------------------------------------------


def test_the_solver_waits_for_the_selection_and_refuses_an_unchosen_type(tmp_path: Path) -> None:
    root, rid, rd = ready_for_math(tmp_path)
    proc = scenarios(rd, rid, [priced()])
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_scenario_selection"
    answer(root, rid, "ct_scenario_selection", "cap_implied_safe")
    proc = scenarios(rd, rid, [priced()])
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert not (rd / "scenarios.json").exists()


def test_a_note_rules_out_the_cap_implied_snapshot(tmp_path: Path) -> None:
    root, rid, rd = ready_for_math(tmp_path, note=True)
    proc = h.record(root, rid, "answer", "--gate", "ct_scenario_selection", "--answer-id", "cap_implied_safe")
    assert proc.returncode == 1 and _out(proc)["code"] == "OPTION_UNLISTED"


def _priced_run(tmp: Path, topup: str, **basis: str) -> tuple[Path, str, Path]:
    root, rid, rd = ready_for_math(tmp)
    answer(root, rid, "ct_scenario_selection", "priced_round")
    answer(root, rid, "ct_pool_topup_intent", topup)
    if basis.get("answer"):
        answer(root, rid, "ct_pool_basis", basis["answer"])
    elif basis.get("default"):
        h.record(root, rid, "open", "--gate", "ct_pool_basis")
        _ok(h.record(root, rid, "default", "--gate", "ct_pool_basis", "--reason", basis["default"]))
    return root, rid, rd


@pytest.mark.parametrize(
    "topup, basis, params, ok",
    [
        ("none", {}, {"target_pool_percent": 0.1}, False),
        ("not_sure", {}, {"target_pool_percent": 0.1, "target_basis": "pre_money"}, False),
        ("top_up_10", {"answer": "post_money"}, {"target_pool_percent": 0.1, "target_basis": "post_money"}, True),
        ("top_up_10", {"answer": "post_money"}, {"target_pool_percent": 0.1, "target_basis": "pre_money"}, False),
        ("top_up_10", {"answer": "post_money"}, {"target_pool_percent": 0.1}, False),
        ("top_up_10", {"answer": "counsel"}, {"target_pool_percent": 0.1}, False),
        ("top_up_10", {"default": "asked_not_to_be_asked"}, {"target_pool_percent": 0.1}, True),
        ("top_up_10", {"default": "asked_not_to_be_asked"}, {"target_pool_percent": 0.1, "target_basis": "pre_money"},
         False),
        ("top_up_10", {"default": "asked_unanswered"}, {"target_pool_percent": 0.1, "target_basis": "post_money"},
         True),
        ("top_up_15", {"answer": "pre_money"}, {"target_pool_percent": 0.12, "target_basis": "pre_money"}, True),
        ("none", {}, {}, True),
    ],
)  # fmt: skip
def test_the_pool_request_agrees_with_the_recorded_answers(
    tmp_path: Path, topup: str, basis: dict[str, str], params: dict[str, Any], ok: bool
) -> None:
    root, rid, rd = _priced_run(tmp_path, topup, **basis)
    proc = scenarios(rd, rid, [priced(**params)])
    if ok:
        _ok(proc)
    else:
        assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH", proc.stdout + proc.stderr
        assert not (rd / "scenarios.json").exists()


def test_a_remedy_flag_needs_the_founders_recorded_answer(tmp_path: Path) -> None:
    root, rid, rd = _priced_run(tmp_path, "top_up_10", answer="post_money")
    proc = scenarios(rd, rid, [priced(target_pool_percent=0.1, target_basis="post_money",
                                      excluding_basis_modeled_as="post_money_by_founder_choice")])  # fmt: skip
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


def test_a_refused_basis_asks_the_remedy_question(tmp_path: Path) -> None:
    root, rid, rd = _priced_run(tmp_path, "top_up_10", answer="post_money")
    req = priced(target_pool_percent=0.1, target_basis="post_money_excluding_converting_securities")
    proc = scenarios(rd, rid, [req])
    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert _out(proc)["blocked_by_gate"] == "ct_pool_basis_remedy.excluding"
    assert not (rd / "scenarios.json").exists()
    answer(root, rid, "ct_pool_basis_remedy.excluding", "keep_refused")
    _ok(scenarios(rd, rid, [req]))


def test_a_recorded_note_answer_must_be_written_into_the_note(tmp_path: Path) -> None:
    root, rid, rd = ready_for_math(tmp_path, note=True)
    answer(root, rid, "ct_scenario_selection", "priced_round")
    answer(root, rid, "ct_pool_topup_intent", "none")
    answer(root, rid, "ct_note_qualified_threshold", "different_amount", "2000000")
    proc = scenarios(rd, rid, [priced()])
    assert proc.returncode == 1 and "write the answer into the note" in proc.stdout


def test_a_note_question_stays_owed_while_open_even_once_the_field_is_written(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path, note=True)
    h.record(root, rid, "open", "--gate", "ct_note_qualified_threshold")
    inst = json.loads((rd / "instruments.json").read_text())
    inst["convertible_notes"][0]["qualified_financing_threshold"] = 2000000
    write(rd, "instruments.json", inst)
    assert h.record(root, rid, "require", "--gate", "ct_note_qualified_threshold").returncode == 10
    # A note no longer there owes nothing, open or not.
    inst["convertible_notes"] = []
    write(rd, "instruments.json", inst)
    assert entry(root, rid, "ct_note_qualified_threshold")["state"] in ("open", "not_owed")
    assert h.record(root, rid, "require", "--gate", "ct_note_qualified_threshold").returncode == 11


# --- the threshold disclosure ---------------------------------------------------------------------------------


def _threshold_codes(rd: Path) -> list[str]:
    scen = json.loads((rd / "scenarios.json").read_text())
    return [
        w.get("code")
        for s in scen["scenarios"]
        for w in (s["computed_outputs"].get("warnings") or [])
        if w.get("code") == "qualified_financing_threshold_defaulted"
    ]


def test_with_no_ledger_the_threshold_disclosure_is_the_only_change(tmp_path: Path) -> None:
    rd = tmp_path / "rd"
    rd.mkdir()
    goldens.ct_dir(rd, note=True)
    _ok(goldens._ct_math(rd, [goldens.CT_NOTE_REQUEST]))
    scen = json.loads((rd / "scenarios.json").read_text())
    _stripped, removed = goldens.strip_threshold_warnings(scen)
    # The lifted copy on the scenario; the note keeps its own row.
    assert removed == 1
    assert _threshold_codes(rd) == ["qualified_financing_threshold_defaulted"]


def test_the_disclosure_reaches_the_report_and_both_pages(tmp_path: Path) -> None:
    rd = tmp_path / "rd"
    rd.mkdir()
    goldens.ct_dir(rd, note=True)
    goldens._ct_math(rd, [goldens.CT_NOTE_REQUEST])
    i, s = str(rd / "inputs.json"), str(rd / "scenarios.json")
    goldens._ct("rule_audit.py", "--phase=post_math", "--inputs", i, "--scenarios", s, "--run-id", goldens.CT_RUN,
                "-o", str(rd / "rule_audit.json"))  # fmt: skip
    goldens._ct("counsel_packet.py", "--rule-audit", str(rd / "rule_audit.json"), "--inputs", i, "--scenarios", s,
                "--run-id", goldens.CT_RUN, "-o", str(rd / "counsel_packet.json"), "--write-md",
                str(rd / "counsel_packet.md"))  # fmt: skip
    _ok(goldens._ct("compose_report.py", "--dir", str(rd), "--run-id", goldens.CT_RUN, "-o", str(rd / "report.json"),
                    "--write-md", str(rd / "report.md")))  # fmt: skip
    _ok(goldens._ct("visualize.py", "--dir", str(rd), "-o", str(rd / "report.html")))
    _ok(goldens._ct("explore.py", "--dir", str(rd), "-o", str(rd / "explorer.html")))
    line = "qualified-financing threshold was not stated; it was treated as met by this round"
    for name in ("report.md", "report.html", "explorer.html"):
        assert line in (rd / name).read_text(encoding="utf-8"), name


def test_a_threshold_confirmed_as_this_rounds_drops_the_disclosure(tmp_path: Path) -> None:
    root, rid, rd = ready_for_math(tmp_path, note=True)
    answer(root, rid, "ct_scenario_selection", "priced_round")
    answer(root, rid, "ct_pool_topup_intent", "none")
    answer(root, rid, "ct_note_qualified_threshold", "same_as_round")
    _ok(scenarios(rd, rid, [priced()]))
    assert _threshold_codes(rd) == []


# --- what-ifs on a delivered review ---------------------------------------------------------------------------


def _fast(root: Path, rid: str, rd: Path, *flags: str) -> Any:
    return ct(
        "quick_assess.py",
        "--inputs",
        str(rd / "inputs.json"),
        "--safes",
        str(rd / "safes.json"),
        "--pre-money",
        "20000000",
        "--new-money",
        "5000000",
        "--review-dir",
        str(rd),
        "--run-id",
        rid,
        *flags,
    )


def test_the_fast_assess_pool_what_if_reopens_the_run_and_asks_the_top_up_again(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, CT, suffix="-fastassess")
    fixture_dir(rd, rid)
    safes = json.loads((rd / "instruments.json").read_text())["safes"]
    write(rd, "safes.json", safes)
    answer(root, rid, "ct_jurisdiction", "delaware")
    answer(root, rid, "ct_pool_topup_intent", "none")
    _ok(_fast(root, rid, rd))
    _ok(h.run(h.RUN_STATUS, "finish", "--mode", "fast_assess", "--run-id", rid, "--artifacts-root", str(root),
              "--output", str(rd / "fast_assess_only.json")))  # fmt: skip
    assert h.status(root, rid)["status"] == "complete"
    # "What if we top up the pool to 10%?"
    proc = _fast(root, rid, rd, "--target-pool-percent", "0.1", "--target-basis", "post_money")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert _out(proc)["blocked_by_gate"] == "ct_pool_topup_intent"
    st = h.status(root, rid)
    assert st["status"] == "waiting" and st["revision"] == 1
    _ok(h.record(root, rid, "answer", "--gate", "ct_pool_topup_intent", "--answer-id", "top_up_10"))
    answer(root, rid, "ct_pool_basis", "post_money")
    _ok(_fast(root, rid, rd, "--target-pool-percent", "0.1", "--target-basis", "post_money"))
    _ok(h.run(h.RUN_STATUS, "finish", "--mode", "fast_assess", "--run-id", rid, "--artifacts-root", str(root),
              "--output", str(rd / "fast_assess_only.json")))  # fmt: skip
    assert h.status(root, rid)["status"] == "complete"
    history = entry(root, rid, "ct_pool_topup_intent")["history"]
    assert any(str(e.get("reason", "")).startswith("what_if:") for e in history)


def test_a_full_review_what_if_asks_the_scenarios_again_never_run_finished(tmp_path: Path) -> None:
    root, rid, rd = ready_for_math(tmp_path)
    answer(root, rid, "ct_scenario_selection", "cap_implied_safe")
    base = [{"scenario_id": "base", "label": "Base", "type": "safe_conversion", "parameters": {}}]
    _ok(scenarios(rd, rid, base))
    h.run(h.RUN_STATUS, "finish", "--mode", "concise", "--run-id", rid, "--artifacts-root", str(root))
    status = json.loads(h.status_path(root, rid).read_text())
    status["status"], status["code"] = "complete", "COMPLETE"
    h.status_path(root, rid).write_text(json.dumps(status))
    proc = scenarios(rd, rid, [*base, priced()])
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_scenario_selection", proc.stdout
    assert h.status(root, rid)["revision"] == 1
    _ok(
        h.record(root, rid, "answer", "--gate", "ct_scenario_selection", "--answer-id", "cap_implied_safe,priced_round")
    )
    answer(root, rid, "ct_pool_topup_intent", "none")
    _ok(scenarios(rd, rid, [*base, priced()]))


def test_a_what_if_hitting_a_refused_basis_asks_the_remedy_not_run_finished(tmp_path: Path) -> None:
    root, rid, rd = _priced_run(tmp_path, "top_up_10", answer="post_money")
    _ok(scenarios(rd, rid, [priced(target_pool_percent=0.1, target_basis="post_money")]))
    status = json.loads(h.status_path(root, rid).read_text())
    status["status"], status["code"] = "complete", "COMPLETE"
    h.status_path(root, rid).write_text(json.dumps(status))
    proc = scenarios(
        rd, rid, [priced(target_pool_percent=0.1, target_basis="post_money_excluding_converting_securities")]
    )
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_pool_basis_remedy.excluding"


# --- compose, the fork, the lightweight routes -----------------------------------------------------------------


def test_compose_opens_no_question_only_a_script_or_the_model_opens(tmp_path: Path) -> None:
    root, rid, rd = _priced_run(tmp_path, "none")
    _ok(scenarios(rd, rid, [priced()]))
    i, s = str(rd / "inputs.json"), str(rd / "scenarios.json")
    _ok(ct("rule_audit.py", "--phase=pre_math", "--inputs", i, "--instruments", str(rd / "instruments.json"),
           "--cap-state", str(rd / "cap_state.json"), "--run-id", rid, "-o", str(rd / "rule_audit.json")))  # fmt: skip
    _ok(ct("rule_audit.py", "--phase=post_math", "--inputs", i, "--scenarios", s, "--run-id", rid, "-o",
           str(rd / "rule_audit.json")))  # fmt: skip
    _ok(ct("counsel_packet.py", "--rule-audit", str(rd / "rule_audit.json"), "--inputs", i, "--scenarios", s,
           "--run-id", rid, "-o", str(rd / "counsel_packet.json"), "--write-md",
           str(rd / "counsel_packet.md")))  # fmt: skip
    write(rd, "report.json", {"metadata": {"run_id": "20200101T000000Z-cccccc"}})  # an earlier review's report
    proc = ct("compose_report.py", "--dir", str(rd), "--run-id", rid, "-o", str(rd / "report.json"), "--write-md",
              str(rd / "report.md"))  # fmt: skip
    _ok(proc)
    keys = set(h.ledger(root, rid).get("gates") or {})
    assert not keys & {"ct_docx_tracked_changes", "ct_existing_review", "ct_pool_basis_remedy.custom",
                       "ct_extraction_confirmation.aoa_fields"}  # fmt: skip
    assert h.status(root, rid)["coaching"] == "pending"


def test_compose_refuses_a_question_left_open(tmp_path: Path) -> None:
    root, rid, rd = _priced_run(tmp_path, "none")
    _ok(scenarios(rd, rid, [priced()]))
    h.record(root, rid, "open", "--gate", "ct_lane1_counsel_review.safes.0.purchase_amount")
    proc = ct("compose_report.py", "--dir", str(rd), "--run-id", rid, "-o", str(rd / "report.json"), "--write-md",
              str(rd / "report.md"))  # fmt: skip
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNRESOLVED"
    assert not (rd / "report.md").exists()


def test_the_terms_only_fork_renders_and_finishes_as_extraction_only(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    for k in ("founders", "option_pool", "preferred_series", "common_batches"):
        inputs.pop(k, None)
    write(rd, "inputs.json", inputs)
    ext = root / "cap-table-example-co-extraction"
    args = ["--inputs", str(rd / "inputs.json"), "--instruments", str(rd / "instruments.json"), "--review-dir",
            str(ext), "--run-id", rid]  # fmt: skip
    proc = ct("compose_extraction_report.py", *args)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "ct_no_cap_base_fork"
    early = h.run(h.RUN_STATUS, "finish", "--mode", "extraction_only", "--run-id", rid, "--artifacts-root", str(root),
                  "--output", str(ext / "extraction_only.json"))  # fmt: skip
    assert early.returncode == 1
    answer(root, rid, "ct_no_cap_base_fork", "terms_only")
    _ok(ct("compose_extraction_report.py", *args))
    _ok(h.run(h.RUN_STATUS, "finish", "--mode", "extraction_only", "--run-id", rid, "--artifacts-root", str(root),
              "--output", str(ext / "extraction_only.json")))  # fmt: skip
    st = h.status(root, rid)
    assert st["status"] == "complete" and st["mode"] == "extraction_only"


def test_provide_cap_base_refuses_the_terms_only_report(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    inputs = json.loads((rd / "inputs.json").read_text())
    for k in ("founders", "option_pool", "preferred_series", "common_batches"):
        inputs.pop(k, None)
    write(rd, "inputs.json", inputs)
    answer(root, rid, "ct_no_cap_base_fork", "provide_cap_base")
    proc = ct("compose_extraction_report.py", "--inputs", str(rd / "inputs.json"), "--instruments",
              str(rd / "instruments.json"), "--review-dir", str(root / "x-extraction"), "--run-id", rid)  # fmt: skip
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


def test_a_rule_lookup_finishes_with_step_ones_basics_unanswered(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    rid = h.start_ok(root, CT)
    h.record(root, rid, "open", "--gate", "ctx_basics.company_name")
    _ok(h.run(h.RUN_STATUS, "finish", "--mode", "rule_lookup", "--run-id", rid, "--artifacts-root", str(root),
              "--lookup-status", "answered"))  # fmt: skip
    assert h.status(root, rid)["status"] == "complete"


def test_an_earlier_review_in_the_dir_is_the_existing_review_and_this_runs_is_not(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    write(rd, "report.json", {"metadata": {"run_id": "20200101T000000Z-dddddd"}})
    assert "ct_existing_review" in _out(h.record(root, rid, "open", "--gate", "ct_existing_review"))["opened"]
    root2, rid2, rd2 = bound(tmp_path / "b")
    write(rd2, "report.json", {"metadata": {"run_id": rid2}})
    assert "ct_existing_review" in _out(h.record(root2, rid2, "open", "--gate", "ct_existing_review"))["not_owed"]


def test_a_founder_fact_takes_a_defer_and_can_be_asked_again(tmp_path: Path) -> None:
    root, rid, rd = bound(tmp_path)
    key = "ct_founder_fact.safes.0.issuance_date"
    answer(root, rid, key, "not_sure")
    answer(root, rid, key, "stated", "2025-01-01")
    assert (entry(root, rid, key)["current"] or {}).get("value") == "2025-01-01"


# --- the freeform emit ---------------------------------------------------------------------------------------


EQUITY_BLOCKS: dict[str, Any] = {
    "blocks": [
        {"block_type": "founders_block", "sheet": "F", "cell_range": "A2:B2",
         "column_role_map": {"A": "holder_name", "B": "shares"}},
    ]
}  # fmt: skip


def _equity_book(path: Path) -> Path:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "F"
    ws.append(["Holder", "Shares"])
    ws.append(["Dana Ray", 7000000])
    wb.save(path)
    return path


def _emit(rd: Path, rid: str, book: Path, blocks: dict[str, Any]) -> Any:
    return ct("extract_cap_table.py", "--mode=freeform-emit", "--xlsx", str(book), "--dir", str(rd), "--run-id", rid,
              stdin=json.dumps(blocks))  # fmt: skip


def test_a_base_mapped_from_the_founders_sheet_is_exempt_and_a_later_change_asks_again(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, CT)
    write(rd, "inputs.json", {**goldens.CT_INPUTS, "metadata": {"run_id": rid, "schema_version": "v0.5.0-inputs"}})
    proc = _emit(rd, rid, _equity_book(tmp_path / "f.xlsx"), EQUITY_BLOCKS)
    _ok(proc)
    assert json.loads((rd / "inputs.json").read_text()).get("founders"), proc.stdout
    assert entry(root, rid, "ct_cap_base_confirmation")["state"] == "not_owed"
    assert h.record(root, rid, "require", "--gate", "ct_cap_base_confirmation").returncode == 0
    inputs = json.loads((rd / "inputs.json").read_text())
    inputs["founders"][0]["common_shares"] += 1
    write(rd, "inputs.json", inputs)
    assert h.record(root, rid, "require", "--gate", "ct_cap_base_confirmation").returncode == 10


def test_a_lane_three_pre_answer_is_recorded_only_when_the_mapper_accepts_it(tmp_path: Path) -> None:
    for value, accepted in (("fixed_numeric_simple", True), ("not-an-enum", False)):
        root = tmp_path / value / "artifacts"
        root.mkdir(parents=True)
        line = f"FS_HOST_VALUE ct_lane3_blocker.0.interest_rate_type=stated | {value}\n"
        rid = h.start_ok(root, CT, line)
        rd = root / "cap-table-example-co"
        _ok(h.bind(root, rid, rd, "example-co"))
        write(rd, "inputs.json", {**goldens.CT_INPUTS, "metadata": {"run_id": rid, "schema_version": "v0.5.0-inputs"}})
        proc = _emit(rd, rid, goldens.ct_workbook(tmp_path / value), goldens.CT_NOTE_BLOCKS)
        _ok(proc)
        e = entry(root, rid, "ct_lane3_blocker.0.interest_rate_type")
        if accepted:
            assert e["state"] == "answered" and (rd / "instruments.json").exists(), proc.stdout
        else:
            assert e["state"] == "open" and "pre_answer_unlisted" in e["flags"], e


# --- the skill's copies and text --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["refuse_open_gates", "coaching_pending"])
def test_the_compose_helpers_are_market_sizings_word_for_word(name: str) -> None:
    ct_mod = _load("_ct_gates_pin", SCRIPTS / "_ct_gates.py")
    ms = _load("_ms_gates_pin3", h.SKILLS / "market-sizing" / "scripts" / "_ms_gates.py")
    assert inspect.getsource(getattr(ct_mod, name)) == inspect.getsource(getattr(ms, name))


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_the_catalog_lists_are_out_and_the_gate_catalog_stays() -> None:
    text = _text()
    for heading in ("## Skill Metadata", "## Available Scripts", "## Available References"):
        assert heading not in text
    assert "**Gate Catalog — canonical phrasing" in text
    fork = text[text.index("**No-cap-base fork (standalone instrument).**") : text.index("**Heredoc guardrail")]
    assert "Never hand-compose `report_extraction_only.md`" in fork
    assert "finish --mode extraction_only" in fork


@pytest.mark.parametrize(
    "first, then",
    [
        ("--gate ct_existing_review", "ask it from its `needs_input`"),
        ("--gate ct_engagement_mode --gate ct_jurisdiction", "then ask the rest via `AskUserQuestion`"),
        ("--gate ct_docx_tracked_changes", "Raise an `AskUserQuestion` BEFORE extraction"),
        ("--gate ct_note_cap_denominator", "Batch ALL such fields into ONE `AskUserQuestion` call"),
        ("--gate ct_option_pool", "--gate ct_cap_base_confirmation"),
        ("--gate ct_no_cap_base_fork", "raise ONE `AskUserQuestion`"),
        ("--gate ct_scenario_selection", "ask the founder via `AskUserQuestion` which to model"),
    ],
)
def test_each_question_is_opened_before_it_is_asked(first: str, then: str) -> None:
    text = _text()
    assert text.index(first) < text.index(then, text.index(first))


def test_the_routes_finish_and_the_pages_take_the_run_id() -> None:
    text = _text()
    for mode in ("fast_assess", "concise", "rule_lookup", "extraction_only"):
        assert f"finish --mode {mode}" in text
    assert '"$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" --run-id "$RUN_ID"' in text
    assert '"$SCRIPTS/explore.py" --dir "$REVIEW_DIR" --run-id "$RUN_ID"' in text
    step12 = text[text.index("### Step 12:") :]
    assert step12.index("deliverables --run-id") < step12.index("**Send the finished work")
    assert "--final || :" in step12
    assert "→ Steps 9–12" in text and "run the finish again" in text


def test_the_lane_four_skeleton_carries_the_run_id() -> None:
    assert '"run_id": "<RUN_ID>"' not in _text()
    assert '"run_id": "<the run_id start printed>"' in _text()


# --- the pool check is bound to the figures it judged ------------------------------------------------------------


def test_a_what_if_cannot_reuse_the_earlier_coaching_or_its_pool_check(tmp_path: Path) -> None:
    run = "20261008T120000Z-e4f5a6"
    rd = tmp_path / "rd"
    rd.mkdir()
    scen = rd / "scenarios.json"
    scen.write_text(json.dumps({"scenarios": [], "metadata": {"run_id": run}}), encoding="utf-8")
    coaching = rd / "coaching.md"
    coaching.write_text("The round leaves the founders with a clear majority.\n", encoding="utf-8")
    checked, released = rd / "coaching.checked.json", rd / "coaching.released.json"
    _ok(ct("pool_claims_check.py", str(coaching), "--scenarios", str(scen), "-o", str(checked)))
    release = ("pool_check_release.py", str(coaching), "--checked", str(checked), "--scenarios", str(scen), "-o",
               str(released))  # fmt: skip
    _ok(ct(*release))
    marker = "<!-- COACHING_INSERTION_POINT_abc123 -->"
    report = rd / "report.md"
    report.write_text(f"# Report\n\n<!-- COACHING_REQUIRES_CHECK_RECORD run_id={run} -->\n{marker}\n", encoding="utf-8")
    # A what-if re-solves the scenarios on the same run.
    scen.write_text(json.dumps({"scenarios": [{"scenario_id": "w"}], "metadata": {"run_id": run}}), encoding="utf-8")
    proc = ct(*release)
    assert proc.returncode == 1 and "scenarios changed" in proc.stdout
    insert = h.run(h.SHARED / "insert_coaching.py", "--commentary-file", str(released), "--report", str(report),
                   "--marker", marker, "--verify-artifact", str(scen))  # fmt: skip
    assert insert.returncode == 1 and "scenarios changed" in insert.stdout, insert.stdout + insert.stderr
    assert marker in report.read_text(encoding="utf-8")
