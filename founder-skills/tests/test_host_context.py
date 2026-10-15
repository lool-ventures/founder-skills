"""Context about the company supplied with the request (`FS_HOST_VALUE host_context=supplied | <JSON>`), through the
real scripts.

Every skill accepts the line; only ic-sim reads it (the gate's `reads_in`), and the others list it ignored as
`not_used_by_skill`. A value that cannot be read waits at Step 1 (`PRE_ANSWER_MALFORMED`); an item that breaks a
rule is dropped by index and cause and the rest are used. `run_status.py check` gives the same verdicts before a
run exists. Every company, label, address and figure here is invented.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


g = _load("_gates")
ht = _load("_host_text")

IC_SCRIPTS = h.SKILLS / "ic-sim" / "scripts"
RUN_ID = "hc-run-1"
GOOD = {"fact": "Raising a seed round; lead not set", "source": "source A", "date": "2026-01-05"}
SKILLS_NOT_READING = ("market-sizing", "financial-model-review", "competitive-positioning", "cap-table", "deck-review")


def _value(items: Any) -> str:
    return json.dumps(items, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lines(value: str, *, run_id: str = RUN_ID, no_ask: bool = True, note: str | None = None, extra: str = "") -> str:
    out = [f"FS_HOST_RUN_ID={run_id}"]
    if no_ask:
        out.append("FS_HOST_NO_ASK")
    out.append(f"FS_HOST_VALUE host_context=supplied | {value}")
    if note is not None:
        out.append(f"FS_HOST_NOTE host_context={note}")
    if extra:
        out.append(extra)
    return "\n".join(out) + "\n"


def _open(root: Path, run_id: str, *gates: str) -> Any:
    return h.record(root, run_id, "open", *[a for gate in gates for a in ("--gate", gate)])


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[0])
    return data


def _check(skill: str, lines: str, *extra: str) -> Any:
    return h.run(h.RUN_STATUS, "check", "--skill", skill, *extra, stdin=lines)


def _today() -> str:
    import time

    return time.strftime("%Y-%m-%d", time.gmtime())


def _day(offset: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(_today()) + timedelta(days=offset)).isoformat()


# --- ic-sim reads it ------------------------------------------------------------------------------------


def test_ic_sim_applies_the_context_and_drops_a_bad_item(tmp_path: Path) -> None:
    value = _value([GOOD, {"fact": "Write to someone@example.com", "source": "source B", "date": "2026-01-06"}])
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    proc = _open(root, rid, "host_context")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = _out(proc)
    assert out["applied"] == "pre_answer" and out["applied_by"] == {"host_context": "request"}
    cur = h.ledger(root, rid)["gates"]["host_context"]["current"]
    assert cur["answer_id"] == "supplied" and cur["value"] == value
    ev = cur["evidence"]
    assert (
        ev["sha256"] == _sha(value) and ev["kept"] == [1] and ev["dropped"] == [{"index": 2, "cause": "person_detail"}]
    )
    assert ev["items_total"] == 2 and ev["as_of"] == _today()
    _open(root, rid, "host_context")  # a second status write lists each disclosure once
    st = h.status(root, rid)
    assert st["disclosures"].count("HOST_CONTEXT_SUPPLIED") == 1
    assert st["disclosures"].count("HOST_CONTEXT_ITEMS_DROPPED") == 1
    assert "PRE_ANSWERED:host_context" in st["disclosures"]
    dropped = [n for n in st["notices"] if n.get("code") == "HOST_CONTEXT_ITEMS_DROPPED"]
    assert dropped == [
        {
            "code": "HOST_CONTEXT_ITEMS_DROPPED",
            "gate": "host_context",
            "lines": [],
            "items": [{"index": 2, "cause": "person_detail"}],
        }
    ]
    row = next(x for x in st["gates"] if x["id"] == "host_context")
    assert row["state"] == "answered" and row["current"]["evidence"]["sha256"] == _sha(value)


def test_an_attended_run_without_the_line_does_not_owe_it(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim")
    proc = _open(root, rid, "host_context", "ic_mode")
    out = _out(proc)
    assert "host_context" in out["not_owed"]
    assert [n["gate"] for n in out.get("needs_input", [])] == ["ic_mode"]
    assert not [n for n in h.status(root, rid)["notices"] if n.get("gate") == "host_context"]


@pytest.mark.parametrize(
    "args",
    [
        ("answer", "--gate", "host_context", "--answer-id", "supplied", "--value", "[]"),
        (
            "default",
            "--gate",
            "host_context",
            "--reason",
            "stated_in_request",
            "--answer-id",
            "supplied",
            "--value",
            "[]",
        ),
    ],
)
@pytest.mark.parametrize("with_line", [False, True])
def test_only_a_request_line_records_it(tmp_path: Path, args: tuple[str, ...], with_line: bool) -> None:
    """Even while a request line is pending (attended, so it is not applied by any no-ask path), the model cannot
    record the option under the host's evidence."""
    lines = _lines(_value([GOOD]), no_ask=False) if with_line else ""
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=lines)
    before = h.snapshot(root, rid)
    proc = h.record(root, rid, *args)
    assert proc.returncode == 1 and _out(proc)["code"] == ("REQUEST_ONLY_OPTION" if with_line else "GATE_NOT_OWED")
    assert h.snapshot(root, rid) == before


def test_a_form_reply_cannot_record_it(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_value([GOOD]), no_ask=False))
    rs = sys.modules["_run_status"]
    paths = rs.run_paths(str(root), rid)

    def fn(ctx: Any, led: dict[str, Any], st: dict[str, Any]) -> Any:
        return g.record(ctx, led, "host_context", answer_ids=["supplied"], value="[]", asked_evidence="form")

    with pytest.raises(g.GateRejection) as e:
        g.transact(paths, fn)
    assert e.value.code == "REQUEST_ONLY_OPTION"


_MALFORMED = [
    ("not json", "not valid JSON"),
    ('{"fact":"x"}', "not a JSON array"),
    (_value([GOOD, "a string"]), "item 2 of the context is not a JSON object"),
    (_value([GOOD] * 61), "more than 60 items"),
    (_value([{**GOOD, "fact": "x" * 300}] * 14), "facts total more than 4,096"),
    (_value([{**GOOD, "source": "y" * 2000}] * 9), "longer than 16,384"),
]


@pytest.mark.parametrize("value,cause", _MALFORMED)
def test_a_value_that_cannot_be_read_waits_at_step_one(tmp_path: Path, value: str, cause: str) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    proc = _open(root, rid, "host_context")
    assert proc.returncode == 12, proc.stdout + proc.stderr
    st = h.status(root, rid)
    assert st["status"] == "waiting" and st["code"] == "PRE_ANSWER_MALFORMED"
    flags = h.ledger(root, rid)["gates"]["host_context"]["flags"]
    assert set(flags) == {"pre_answer_unlisted", "pre_answer_malformed"}
    notice = [n for n in st["notices"] if n.get("code") == "PRE_ANSWER_NOT_APPLIED"][-1]
    assert cause in notice["reason"] and value[:40] not in notice["reason"]
    # The same cause `check` gives before any run exists.
    chk = _check("ic-sim", _lines(value, run_id="hc-run-2"))
    assert chk.returncode == 4
    assert json.loads(chk.stdout)["values"][0]["cause"] == notice["reason"]


@pytest.mark.parametrize("note,cause", [("0" * 64, "did not arrive intact"), ("not-a-sha", "not a SHA-256")])
def test_the_checksum_note_is_checked(tmp_path: Path, note: str, cause: str) -> None:
    value = _value([GOOD])
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value, note=note))
    assert _open(root, rid, "host_context").returncode == 12
    notice = [n for n in h.status(root, rid)["notices"] if n.get("code") == "PRE_ANSWER_NOT_APPLIED"][-1]
    assert cause in notice["reason"]


def test_a_matching_checksum_note_applies(tmp_path: Path) -> None:
    value = _value([GOOD])
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value, note=_sha(value)))
    assert _open(root, rid, "host_context").returncode == 0
    assert h.ledger(root, rid)["gates"]["host_context"]["state"] == "answered"


def test_a_second_bad_line_gets_its_own_diagnosis_and_a_corrected_one_applies(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines("not json"))
    assert _open(root, rid, "host_context").returncode == 12
    resumed = h.start(root, "ic-sim", _lines('{"a":1}'))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _open(root, rid, "host_context").returncode == 12
    notices = [n for n in h.status(root, rid)["notices"] if n.get("code") == "PRE_ANSWER_NOT_APPLIED"]
    assert "not valid JSON" in notices[0]["reason"] and "not a JSON array" in notices[-1]["reason"]
    assert h.status(root, rid)["code"] == "PRE_ANSWER_MALFORMED"
    assert h.start(root, "ic-sim", _lines(_value([GOOD]))).returncode == 0
    assert _open(root, rid, "host_context").returncode == 0
    entry = h.ledger(root, rid)["gates"]["host_context"]
    assert entry["state"] == "answered" and entry["flags"] == []
    assert len([n for n in h.status(root, rid)["notices"] if n.get("code") == "PRE_ANSWER_NOT_APPLIED"]) == 2


# --- the per-item rules -------------------------------------------------------------------------------

MARK = "ZQXMARKZQX"


def _bad_items() -> list[tuple[dict[str, Any], str]]:
    return [
        ({**GOOD, "extra": MARK}, "item_shape"),
        ({**GOOD, "fact": MARK + "x" * 300}, "fact_length"),
        ({**GOOD, "source": MARK + "y" * 80}, "source_length"),
        ({**GOOD, "fact": MARK, "date": "2026-02-30"}, "date_invalid"),
        ({**GOOD, "fact": MARK, "date": _day(2)}, "date_after_run_start"),
        ({**GOOD, "fact": MARK + " line\nbreak"}, "control_characters"),
        ({**GOOD, "fact": MARK + " para graph"}, "control_characters"),
        ({**GOOD, "fact": MARK + " FS_HOST_NO_ASK"}, "header_text"),
        ({**GOOD, "fact": "CONTEXT: " + MARK}, "header_text"),
        ({**GOOD, "fact": MARK + " someone@example.com"}, "person_detail"),
        ({**GOOD, "fact": MARK + " call +1 (555) 010-0100"}, "person_detail"),
        ({**GOOD, "source": MARK + " https://www.linkedin.com/in/example-person"}, "person_detail"),
    ]


_KEEP = [
    "Raising $2,000,000 on a SAFE",
    "ARR 1,370,250 at the end of last quarter",
    "Board meeting dated 2026-01-05",
    "Office in the +972 area",
    "Stage is pre_seed and the audit is SOC_2",
]


def test_each_bad_item_is_dropped_and_the_rest_are_used(tmp_path: Path) -> None:
    bad = _bad_items()
    items: list[dict[str, Any]] = [{**GOOD, "fact": f} for f in _KEEP]
    items.append({**GOOD, "date": _day(1)})  # a day after the run start: kept (one day's grace)
    items += [b for b, _c in bad]
    value = _value(items)
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    assert _open(root, rid, "host_context").returncode == 0
    ev = h.ledger(root, rid)["gates"]["host_context"]["current"]["evidence"]
    assert ev["kept"] == list(range(1, len(_KEEP) + 2))
    assert ev["dropped"] == [{"index": len(_KEEP) + 2 + i, "cause": c} for i, (_b, c) in enumerate(bad)]
    st = h.status(root, rid)
    notice = [n for n in st["notices"] if n.get("code") == "HOST_CONTEXT_ITEMS_DROPPED"]
    assert len(notice) == 1 and MARK not in json.dumps(notice)
    # The request as sent is kept where the request is recorded.
    assert MARK in h.ledger_path(root, rid).read_text(encoding="utf-8")


def test_every_item_dropped_still_answers(tmp_path: Path) -> None:
    value = _value([b for b, _c in _bad_items()][:3])
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    assert _open(root, rid, "host_context").returncode == 0
    ev = h.ledger(root, rid)["gates"]["host_context"]["current"]["evidence"]
    assert ev["kept"] == [] and len(ev["dropped"]) == 3


def test_the_phone_rule_spares_money_and_dates() -> None:
    for text in _KEEP:
        assert not ht.has_person_detail(text), text
    assert ht.has_person_detail("tel:+15550100100")


# --- the other skills accept it and never judge it ---------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS_NOT_READING)
@pytest.mark.parametrize("value", [_value([{**GOOD, "fact": MARK}]), "not json " + MARK])
def test_other_skills_accept_the_line_and_list_it_unused(tmp_path: Path, skill: str, value: str) -> None:
    root, rid, _rd = h.start_bound(tmp_path, skill, lines=_lines(value))
    row = next(x for x in h.status(root, rid)["gates"] if x["id"] == "host_context")
    assert row["state"] == "not_reached"
    fail = h.run(
        h.RUN_STATUS,
        "fail",
        "--run-id",
        rid,
        "--artifacts-root",
        str(root),
        "--code",
        "PRODUCER_FAILED",
        "--reason",
        "test",
    )
    assert fail.returncode == 0, fail.stdout + fail.stderr
    ignored = [n for n in h.status(root, rid)["notices"] if n.get("gate") == "host_context"]
    assert [(n["code"], n["reason"]) for n in ignored] == [("PRE_ANSWER_IGNORED", "not_used_by_skill")]
    # The request as sent: this notice code carries the line, by design.
    assert MARK in ignored[0]["lines"][0]
    chk = _check(skill, _lines(value, run_id="hc-run-9"))
    assert chk.returncode == 0
    assert json.loads(chk.stdout)["values"] == [{"gate": "host_context", "verdict": "not_used_by_skill"}]


# --- `run_status.py check` ----------------------------------------------------------------------------


def _tree(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


@pytest.mark.parametrize(
    "value",
    [_value([GOOD]), _value([GOOD, *[b for b, _c in _bad_items()]]), *[v for v, _c in _MALFORMED]],
)
def test_check_agrees_with_start_and_open(tmp_path: Path, value: str) -> None:
    before = _tree(tmp_path)
    chk = _check("ic-sim", _lines(value))
    assert _tree(tmp_path) == before
    verdict = json.loads(chk.stdout)["values"][0]
    root, rid, _rd = h.start_bound(tmp_path / "real", "ic-sim", lines=_lines(value))
    opened = _open(root, rid, "host_context")
    entry = h.ledger(root, rid)["gates"]["host_context"]
    if entry["state"] == "answered":
        assert chk.returncode == 0 and opened.returncode == 0
        ev = entry["current"]["evidence"]
        assert verdict == {"gate": "host_context", "verdict": "applies", "kept": ev["kept"], "dropped": ev["dropped"]}
    else:
        assert chk.returncode == 4 and opened.returncode == 12
        reason = [n for n in h.status(root, rid)["notices"] if n.get("code") == "PRE_ANSWER_NOT_APPLIED"][-1]
        assert verdict == {"gate": "host_context", "verdict": "would_wait", "cause": reason["reason"]}


def test_check_exit_codes(tmp_path: Path) -> None:
    unknown = _check("ic-sim", "FS_HOST_RUN_ID=hc-run-3\nFS_HOST_ANSWER no_such_gate=x\n")
    assert unknown.returncode == 1 and json.loads(unknown.stdout)["would_start"] is False
    assert h.start(tmp_path, "ic-sim", "FS_HOST_RUN_ID=hc-run-3\nFS_HOST_ANSWER no_such_gate=x\n").returncode == 1
    assert _check("ic-sim", "", "--as-of", "2026-13-01").returncode == 2
    assert _check("no-such-skill", "").returncode == 2
    empty = _check("ic-sim", "")
    assert empty.returncode == 0 and json.loads(empty.stdout)["values"] == []


def test_check_judges_dates_against_as_of() -> None:
    value = _value([{**GOOD, "date": "2026-03-10"}])
    early = json.loads(_check("ic-sim", _lines(value), "--as-of", "2026-03-01").stdout)["values"][0]
    late = json.loads(_check("ic-sim", _lines(value), "--as-of", "2026-03-10").stdout)["values"][0]
    assert early["dropped"] == [{"index": 1, "cause": "date_after_run_start"}] and late["kept"] == [1]


def test_check_leaves_a_check_that_needs_the_run_unjudged() -> None:
    lines = "FS_HOST_RUN_ID=hc-run-4\nFS_HOST_ANSWER fmr_extracted_values=corrections_applied\n"
    chk = _check("financial-model-review", lines)
    assert chk.returncode == 0, chk.stdout
    assert json.loads(chk.stdout)["values"] == [{"gate": "fmr_extracted_values", "verdict": "not_checked_here"}]


def test_check_runs_only_the_checks_that_read_the_request() -> None:
    """The dry table is exactly the two request-only checks, and a request-only option whose check needs the run
    is refused by the registry."""
    assert {"host_context_parses", "ic_fund_profile_parses"} == g.DRY_REQUIRES
    gates = {k: dict(v) for k, v in g.GATES.items()}
    opt = dict(gates["host_context"]["options"][0])
    opt["requires"] = "fmr_corrections_audit"
    gates["host_context"] = {**gates["host_context"], "options": (opt,)}
    assert any("reads only the request" in p for p in g.validate_registry(gates))


# --- the registry ------------------------------------------------------------------------------------


def test_reads_in_is_validated_and_published() -> None:
    gates = {k: dict(v) for k, v in g.GATES.items()}
    gates["ic_mode"] = {**gates["ic_mode"], "reads_in": ("ic-sim",)}
    assert any("only a shared gate" in p for p in g.validate_registry(gates))
    gates = {k: dict(v) for k, v in g.GATES.items()}
    gates["host_context"] = {**gates["host_context"], "reads_in": ("no-such-skill",)}
    assert any("must name skills" in p for p in g.validate_registry(gates))
    contract = json.loads((h.REPO_ROOT / "founder-skills" / "data" / "host-contract.json").read_text("utf-8"))
    assert contract["gates"]["host_context"]["reads_in"] == ["ic-sim"]
    assert contract["exit_codes"]["check_would_wait"] == 4
    assert contract["request_values"]["host_context"]["drop_causes"] == list(ht.CAUSES)


@pytest.mark.parametrize("change", ["shown", "writer"])
def test_a_request_only_option_must_be_hidden_and_recorder_owned(change: str) -> None:
    gates = {k: dict(v) for k, v in g.GATES.items()}
    if change == "shown":
        opt = {**gates["host_context"]["options"][0], "shown": True}
        gates["host_context"] = {**gates["host_context"], "options": (opt,)}
    else:
        gates["host_context"] = {**gates["host_context"], "writer": "gate_state.py"}
    assert any("request-only option" in p for p in g.validate_registry(gates))


def test_the_malformed_branch_comes_before_the_unlisted_one(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines("not json"))
    _open(root, rid, "host_context")
    assert h.status(root, rid)["code"] == "PRE_ANSWER_MALFORMED"
    # An unlisted line that is not malformed keeps its own code.
    root2, rid2, _rd2 = h.start_bound(
        tmp_path / "b",
        "financial-model-review",
        lines="FS_HOST_RUN_ID=hc-run-5\nFS_HOST_ANSWER fmr_extracted_values=corrections_applied\n",
    )
    out = _open(root2, rid2, "fmr_extracted_values")
    assert out.returncode == 0 and _out(out)["pre_answer_unlisted"] == ["fmr_extracted_values"]
    assert h.status(root2, rid2)["code"] == "PRE_ANSWER_UNLISTED"


def test_the_host_text_copies_are_identical() -> None:
    shared = (h.SHARED / "_host_text.py").read_bytes()
    assert (h.SKILLS / "ic-sim" / "scripts" / "_host_text.py").read_bytes() == shared


def test_the_person_page_rule_is_fund_profiles() -> None:
    import runpy

    person_page = runpy.run_path(str(IC_SCRIPTS / "fund_profile.py"))["_is_person_page"]
    for url in (
        "https://www.linkedin.com/in/example-person",
        "linkedin.com/pub/example",
        "https://example.com/team",
        "https:/www.crunchbase.com/person/x",
        "https://m.linkedin.com/mwlite/in/x",
    ):
        assert ht._is_person_page(url) == person_page(url), url


def test_a_cap_size_value_line_is_accepted(tmp_path: Path) -> None:
    value = "x" * g.VALUE_MAX
    lines = f"FS_HOST_RUN_ID={RUN_ID}\nFS_HOST_VALUE host_context=supplied | {value}\n"
    assert h.start(tmp_path, "market-sizing", lines).returncode == 0
    over = lines.replace(value, value + "x").replace(RUN_ID, "hc-run-6")
    proc = h.start(tmp_path, "market-sizing", over)
    assert proc.returncode == 1 and "longer than 32,768" in proc.stdout
    assert os.path.exists(tmp_path / "runs" / RUN_ID / "run_status.json")
