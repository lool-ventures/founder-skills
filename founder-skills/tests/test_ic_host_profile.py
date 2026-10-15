"""ic-sim: a fund profile supplied with the request (`FS_HOST_VALUE ic_fund_mode=host_profile | <JSON>`), through
the real scripts.

Only a request line can choose it; its value is checked at Step 1 (a value that cannot be read waits, never
falls back to a generic fund); Step 4 builds the profile from the ledger's value with `--from-request`, stamped
`profile_source`; compose refuses a profile whose source and the recorded fund disagree. Every fund, company and
figure here is invented.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402

IC = h.SKILLS / "ic-sim" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ic-sim"
REQUEST_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ic-sim-request" / "fund_profile_request.json"
RUN_ID = "hp-run-1"


def _load(name: str, path: Path) -> ModuleType:
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    if str(IC) not in sys.path:
        sys.path.append(str(IC))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _load("_hp_fund_profile", IC / "fund_profile.py")
icg = _load("_hp_ic_gates", IC / "_ic_gates.py")
if "_gates" not in sys.modules:
    sys.modules["_gates"] = _load("_gates", h.SHARED / "_gates.py")
g = sys.modules["_gates"]


def _value(data: Any = None) -> str:
    if data is None:
        data = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    return json.dumps(data, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lines(value: str, *, run_id: str = RUN_ID, no_ask: bool = True, note: str | None = None) -> str:
    out = [f"FS_HOST_RUN_ID={run_id}"]
    if no_ask:
        out.append("FS_HOST_NO_ASK")
    out += ["FS_HOST_ANSWER ctx_basics.stage=seed", f"FS_HOST_VALUE ic_fund_mode=host_profile | {value}"]
    if note is not None:
        out.append(f"FS_HOST_NOTE ic_fund_mode={note}")
    return "\n".join(out) + "\n"


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[0])
    return data


def _open(root: Path, rid: str, *gates: str) -> Any:
    return h.record(root, rid, "open", *[a for gate in gates for a in ("--gate", gate)])


def _from_request(run_dir: Path, rid: str, *extra: str) -> Any:
    return h.run(
        IC / "fund_profile.py", "--from-request", "--run-id", rid, "-o", str(run_dir / "fund_profile.json"), *extra
    )


def _started(tmp_path: Path, value: str | None = None, **kw: Any) -> tuple[Path, str, Path]:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value or _value(), **kw))
    rd.mkdir(parents=True, exist_ok=True)
    return root, rid, rd


# --- Step 1 -----------------------------------------------------------------------------------------------


def test_the_line_is_applied_at_step_one(tmp_path: Path) -> None:
    value = _value()
    root, rid, _rd = _started(tmp_path, value)
    out = _out(_open(root, rid, "ic_mode", "ic_fund_mode"))
    assert out["applied"] == "pre_answer" and out["applied_by"]["ic_fund_mode"] == "request"
    led = h.ledger(root, rid)
    assert g.answered_by_request(led, "ic_fund_mode")
    cur = led["gates"]["ic_fund_mode"]["current"]
    assert cur["answer_id"] == "host_profile" and cur["value"] == value
    assert cur["evidence"] == {"sha256": _sha(value), "bytes": len(value.encode("utf-8"))}
    _open(root, rid, "ic_mode")  # a second status write
    st = h.status(root, rid)
    assert st["disclosures"].count("FUND_PROFILE_SUPPLIED") == 1 and "PRE_ANSWERED:ic_fund_mode" in st["disclosures"]
    row = next(x for x in st["gates"] if x["id"] == "ic_fund_mode")
    assert row["current"]["evidence"]["sha256"] == _sha(value)


@pytest.mark.parametrize("note,applies", [("ok", True), ("altered", False), ("not hex", False)])
def test_the_checksum_note(tmp_path: Path, note: str, applies: bool) -> None:
    value = _value()
    sent = {"ok": _sha(value), "altered": _sha(value.replace("Robotics", "Robotic")), "not hex": "xyz"}[note]
    root, rid, _rd = _started(tmp_path, value, note=sent)
    proc = _open(root, rid, "ic_fund_mode")
    assert proc.returncode == (0 if applies else 12)
    if not applies:
        reason = [n for n in h.status(root, rid)["notices"] if n["code"] == "PRE_ANSWER_NOT_APPLIED"][-1]["reason"]
        assert ("did not arrive intact" if note == "altered" else "not a SHA-256") in reason


def test_an_attended_question_never_offers_it(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim")
    out = _out(_open(root, rid, "ic_fund_mode"))
    assert [o["id"] for o in out["needs_input"][0]["options"]] == ["generic", "specific"]


@pytest.mark.parametrize(
    "args",
    [
        ("answer", "--gate", "ic_fund_mode", "--answer-id", "host_profile", "--value", "{}"),
        (
            "default",
            "--gate",
            "ic_fund_mode",
            "--reason",
            "stated_in_request",
            "--answer-id",
            "host_profile",
            "--value",
            "{}",
        ),
    ],
)
@pytest.mark.parametrize("with_line", [False, True])
def test_only_a_request_line_records_it(tmp_path: Path, args: tuple[str, ...], with_line: bool) -> None:
    lines = _lines(_value(), no_ask=False) if with_line else ""
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=lines)
    before = h.snapshot(root, rid)
    proc = h.record(root, rid, *args)
    assert proc.returncode == 1 and _out(proc)["code"] == "REQUEST_ONLY_OPTION"
    assert h.snapshot(root, rid) == before


def test_derive_cannot_name_it(tmp_path: Path) -> None:
    lines = f"FS_HOST_RUN_ID={RUN_ID}\nFS_HOST_NO_ASK\nFS_HOST_DERIVE ic_fund_mode\n"
    assert h.start(tmp_path, "ic-sim", lines).returncode == 1


_BAD = [
    ("not json", "not valid JSON"),
    ("[1,2]", "not a JSON object"),
    (_value({**json.loads(_value()), "team": []}), 'field "team" is not allowed'),
    (_value({**json.loads(_value()), "accepted_warnings": []}), 'field "accepted_warnings" is not allowed'),
    (_value({**json.loads(_value()), "profile_source": {"kind": "request"}}), 'field "profile_source"'),
    (
        _value({**json.loads(_value()), "thesis_areas": ["a", "b", "c", "x" * 201]}),
        "thesis_areas[3] is longer than 200",
    ),
    (_value({**json.loads(_value()), "sources": [{"url": "https://example.com/" + "a" * 600}]}), "sources[0].url"),
    (_value({**json.loads(_value()), "fund_name": "Example\nPartners"}), "fund_name contains a control character"),
    (_value({**json.loads(_value()), "portfolio": [{"name": "Co"}] * 201}), "portfolio has more than 200 items"),
]


@pytest.mark.parametrize("value,cause", _BAD)
def test_a_profile_that_cannot_be_read_waits_never_generic(tmp_path: Path, value: str, cause: str) -> None:
    root, rid, _rd = _started(tmp_path, value)
    proc = _open(root, rid, "ic_mode", "ic_fund_mode")
    assert proc.returncode == 12, proc.stdout + proc.stderr
    st = h.status(root, rid)
    assert st["status"] == "waiting" and st["code"] == "PRE_ANSWER_MALFORMED"
    entry = h.ledger(root, rid)["gates"]["ic_fund_mode"]
    assert entry["state"] == "open" and entry["current"] is None  # never the generic default
    reason = [n for n in st["notices"] if n["code"] == "PRE_ANSWER_NOT_APPLIED"][-1]["reason"]
    assert cause in reason and "Example Partners" not in reason
    chk = h.run(h.RUN_STATUS, "check", "--skill", "ic-sim", stdin=_lines(value, run_id="hp-run-2"))
    assert chk.returncode == 4
    assert [v["cause"] for v in json.loads(chk.stdout)["values"] if v["gate"] == "ic_fund_mode"] == [reason]


def test_attended_a_profile_that_cannot_be_read_asks_the_fund_question(tmp_path: Path) -> None:
    root, rid, _rd = _started(tmp_path, "not json", no_ask=False)
    out = _out(_open(root, rid, "ic_fund_mode"))
    assert out["pre_answer_unlisted"] == ["ic_fund_mode"] and out["needs_input"][0]["gate"] == "ic_fund_mode"
    assert h.status(root, rid)["code"] == "PRE_ANSWER_MALFORMED"


def test_a_second_bad_line_then_a_good_one(tmp_path: Path) -> None:
    root, rid, rd = _started(tmp_path, "not json")
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 12
    assert h.start(root, "ic-sim", _lines("[1]")).returncode == 0
    assert _open(root, rid, "ic_fund_mode").returncode == 12
    notices = [n for n in h.status(root, rid)["notices"] if n["code"] == "PRE_ANSWER_NOT_APPLIED"]
    assert "not a JSON object" in notices[-1]["reason"] and "not valid JSON" in notices[0]["reason"]
    assert h.start(root, "ic-sim", _lines(_value())).returncode == 0
    assert _open(root, rid, "ic_fund_mode").returncode == 0
    assert h.ledger(root, rid)["gates"]["ic_fund_mode"]["flags"] == []
    assert _from_request(rd, rid).returncode == 0


def test_a_waiting_run_lists_neither_disclosure(tmp_path: Path) -> None:
    root, rid, _rd = _started(tmp_path, "not json")
    _open(root, rid, "ic_mode", "ic_fund_mode")
    disclosures = h.status(root, rid)["disclosures"]
    assert "FUND_PROFILE_SUPPLIED" not in disclosures and "PRE_ANSWERED:ic_fund_mode" not in disclosures


def test_a_different_value_on_a_resume_is_ignored_once_answered(tmp_path: Path) -> None:
    root, rid, _rd = _started(tmp_path)
    _open(root, rid, "ic_mode", "ic_fund_mode")
    # Leave the run waiting on another question so a resume is allowed.
    h.record(root, rid, "open", "--gate", "ctx_basics.sector")
    assert h.status(root, rid)["status"] == "waiting"
    other = _value({**json.loads(_value()), "fund_name": "Other Example Fund"})
    assert h.start(root, "ic-sim", _lines(other)).returncode == 0
    ignored = [n for n in h.status(root, rid)["notices"] if n["code"] == "PRE_ANSWER_IGNORED"]
    assert [(n["gate"], n["reason"]) for n in ignored] == [("ic_fund_mode", "already_answered")]


def test_a_running_run_is_not_resumed(tmp_path: Path) -> None:
    root, rid, _rd = _started(tmp_path)
    _open(root, rid, "ic_mode", "ic_fund_mode")
    assert h.status(root, rid)["status"] == "running"
    before = h.snapshot(root, rid)
    proc = h.start(root, "ic-sim", _lines(_value({**json.loads(_value()), "fund_name": "Other"})))
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_IN_USE"
    assert h.snapshot(root, rid) == before


def test_the_recorder_caps_a_value(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim")
    proc = h.record(root, rid, "answer", "--gate", "ic_fund_mode", "--answer-id", "specific", "--value", "x" * 32769)
    assert proc.returncode == 1 and _out(proc)["code"] == "VALUE_TOO_LONG"


def test_an_over_cap_line_on_a_resume_leaves_the_run(tmp_path: Path) -> None:
    root, rid, _rd = _started(tmp_path, "not json")
    _open(root, rid, "ic_mode", "ic_fund_mode")
    before = h.snapshot(root, rid)
    proc = h.start(root, "ic-sim", _lines("x" * 32769))
    assert proc.returncode == 1 and _out(proc)["code"] == "PRE_ANSWER_INVALID"
    assert h.snapshot(root, rid) == before


# --- Step 4: --from-request -------------------------------------------------------------------------------


def _answered(tmp_path: Path, value: str | None = None) -> tuple[Path, str, Path]:
    root, rid, rd = _started(tmp_path, value)
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 0
    return root, rid, rd


def test_from_request_builds_the_stamped_profile_deterministically(tmp_path: Path) -> None:
    value = _value()
    root, rid, rd = _answered(tmp_path, value)
    proc = _from_request(rd, rid, "--pretty")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (rd / "fund_profile.json").read_text(encoding="utf-8")
    assert "\n" not in text.rstrip("\n")  # compact: no indent
    prof = json.loads(text)
    assert prof["profile_source"] == {"kind": "request", "sha256": _sha(value)}
    assert prof["mode"] == "fund_specific" and prof["validation"]["status"] == "valid"
    assert [a["role"] for a in prof["archetypes"]] == ["visionary", "operator", "analyst"]
    assert prof["metadata"] == {"run_id": rid} and fp.people_problems(prof) == []
    assert _from_request(rd, rid).returncode == 0
    assert (rd / "fund_profile.json").read_text(encoding="utf-8") == text
    assert fp.founder_lines(prof) == [
        "Fund: a specific fund, profile supplied with this request",
        "The fund's thesis, stage focus, check size and portfolio were supplied with this request and were not "
        "researched in this run. The three partners are role-played.",
        "No sources were listed for this fund profile.",
    ]


def test_a_large_profile_stays_under_a_shell_result(tmp_path: Path) -> None:
    rows = [{"name": f"Example Holding {i:03d} Co", "sector": "Industrial", "status": "active"} for i in range(200)]
    data = {**json.loads(_value()), "portfolio": rows, "thesis_areas": ["Industrial hardware " + "x" * 150] * 20}
    value = _value(data)
    while len(value) < 28_000:
        data["stage_focus"] = [*data.get("stage_focus", []), "seed " + "y" * 150][:20]
        data["sources"] = [*data.get("sources", []), {"title": "Example source " + "z" * 150}][:20]
        value = _value(data)
        if len(data["sources"]) == 20 and len(data["stage_focus"]) == 20:
            break
    root, rid, rd = _answered(tmp_path, value)
    assert _from_request(rd, rid).returncode == 0
    size = len((rd / "fund_profile.json").read_text(encoding="utf-8"))
    print(f"value {len(value)} characters -> fund_profile.json {size} characters")
    assert size - len(value) < 2_000 and size < 32_000


def test_a_hand_edited_ledger_value_is_refused(tmp_path: Path) -> None:
    root, rid, rd = _answered(tmp_path)
    path = h.ledger_path(root, rid)
    led = json.loads(path.read_text(encoding="utf-8"))
    led["gates"]["ic_fund_mode"]["current"]["value"] = _value({**json.loads(_value()), "fund_name": "Edited"})
    path.write_text(json.dumps(led), encoding="utf-8")
    proc = _from_request(rd, rid)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"
    assert not (rd / "fund_profile.json").exists()


def test_step_four_rules(tmp_path: Path) -> None:
    base = json.loads(_value())
    cases = [
        (
            {**base, "archetypes": [{"role": "visionary", "name": "The Visionary", "focus_areas": ["x"]}]},
            "PARTNER_NAME_NOT_ROLE",
        ),
        ({**base, "portfolio": [{"name": "Co", "founder": "x"}]}, "PORTFOLIO_FIELD_NOT_ALLOWED"),
        ({**base, "sources": [{"url": "https://www.linkedin.com/in/example-person"}]}, "SOURCE_IS_A_PERSON"),
        ({**base, "check_size_range": {"min": 5, "max": 1}}, "must be <= max"),
        ({k: v for k, v in base.items() if k != "portfolio"}, "Missing required field: portfolio"),
        ({**base, "mode": "generic"}, "mode must be 'fund_specific'"),
    ]
    for i, (data, code) in enumerate(cases):
        root, rid, rd = _answered(tmp_path / str(i), _value(data))
        proc = _from_request(rd, rid)
        assert proc.returncode == 1, (code, proc.stdout)
        assert code in proc.stdout, (code, proc.stdout)
        assert not (rd / "fund_profile.json").exists()
        if code in ("PARTNER_NAME_NOT_ROLE", "PORTFOLIO_FIELD_NOT_ALLOWED", "SOURCE_IS_A_PERSON"):
            assert "linkedin.com/in" not in proc.stdout and 'founder": "x' not in proc.stdout
        fail = h.run(
            h.RUN_STATUS,
            "fail",
            "--run-id",
            rid,
            "--artifacts-root",
            str(root),
            "--code",
            "INPUT_REJECTED",
            "--reason",
            code,
        )
        assert fail.returncode == 0, fail.stdout + fail.stderr
        st = h.status(root, rid)
        assert st["status"] == "refused" and st["code"] == "INPUT_REJECTED"
        assert st["message"] == "An input supplied with the request was refused, so the run stopped."


def test_metadata_and_validation_are_restamped_and_sources_optional(tmp_path: Path) -> None:
    data = {**json.loads(_value()), "metadata": {"run_id": "x"}, "validation": {"status": "valid"}}
    root, rid, rd = _answered(tmp_path, _value(data))
    assert _from_request(rd, rid).returncode == 0
    prof = json.loads((rd / "fund_profile.json").read_text(encoding="utf-8"))
    assert prof["metadata"] == {"run_id": rid} and prof["validation"] == {"status": "valid", "errors": []}


def test_from_request_needs_a_run_and_the_supplied_answer(tmp_path: Path) -> None:
    rd = tmp_path / "no-ledger"
    rd.mkdir()
    proc = _from_request(rd, RUN_ID)
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_PROFILE_NEEDS_RUN"
    root, rid, rd2 = h.start_bound(tmp_path / "generic", "ic-sim")
    h.record(root, rid, "answer", "--gate", "ic_mode", "--answer-id", "auto_pilot")
    h.record(root, rid, "answer", "--gate", "ic_fund_mode", "--answer-id", "generic")
    rd2.mkdir(parents=True, exist_ok=True)
    proc = _from_request(rd2, rid)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


def test_stdin_under_a_supplied_profile_is_refused(tmp_path: Path) -> None:
    root, rid, rd = _answered(tmp_path)
    body = {**json.loads(_value()), "mode": "fund_specific", "sources": [{"title": "x"}]}
    body["archetypes"] = [dict(a) for a in fp.DEFAULT_ARCHETYPES]
    proc = h.run(IC / "fund_profile.py", "--run-id", rid, "-o", str(rd / "fund_profile.json"), stdin=json.dumps(body))
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_PROFILE_REQUIRED"


def test_stdin_may_not_carry_the_stamp(tmp_path: Path) -> None:
    body = json.loads((FIXTURES / "fund_profile.json").read_text(encoding="utf-8"))
    body["profile_source"] = {"kind": "request", "sha256": "0" * 64}
    proc = h.run(IC / "fund_profile.py", "--run-id", RUN_ID, stdin=json.dumps(body))
    assert proc.returncode == 1 and "written only when the profile is supplied" in proc.stdout
    body.pop("profile_source")
    body["team"] = []
    proc = h.run(IC / "fund_profile.py", "--run-id", RUN_ID, stdin=json.dumps(body))
    assert proc.returncode == 1 and "profile_source" not in proc.stdout.split("it carries only", 1)[1]


def test_fund_modes_are_the_option_ids_both_ways() -> None:
    assert set(icg.FUND_MODES) == {o["id"] for o in g.GATES["ic_fund_mode"]["options"]}


def test_the_request_key_set_is_the_producers() -> None:
    assert set(g.FUND_REQUEST_KEYS) == set(fp.FUND_KEYS) - {"accepted_warnings", "profile_source"}


def test_a_supplied_answer_with_a_generic_profile_is_a_mismatch(tmp_path: Path) -> None:
    root, rid, rd = _answered(tmp_path)
    with pytest.raises(SystemExit) as e:
        icg.fund_choice_or_exit(icg.open_ledger_or_exit(str(rd), rid), "generic")
    assert e.value.code == 1


def test_founder_lines_for_each_kind() -> None:
    assert fp.founder_lines({"mode": "generic"}) == ["Fund: an illustrative generic fund"]
    assert fp.founder_lines({"mode": "fund_specific", "sources": [{"title": "x"}]}) == [
        "Fund: a specific fund, profile researched for this simulation"
    ]
    supplied = {"mode": "fund_specific", "sources": [{"title": "x"}], "profile_source": {"kind": "request"}}
    assert len(fp.founder_lines(supplied)) == 2


def test_the_stamp_is_closed() -> None:
    assert fp.people_problems({"profile_source": {"kind": "request", "sha256": "0", "by": "x"}}) == [
        'field "profile_source"'
    ]


# --- compose ----------------------------------------------------------------------------------------------


def _stage_rest(rd: Path, rid: str) -> None:
    """Steps 2-3 and 5-8, stamped for this run and built from the fund profile now in `rd`."""
    for f in FIXTURES.iterdir():
        if f.name == "fund_profile.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": rid}
        if f.name in fp.PROFILE_DEPENDENTS:
            fp.stamp_profile(data, str(rd / f.name))
        (rd / f.name).write_text(json.dumps(data), encoding="utf-8")


def _compose(rd: Path) -> Any:
    return h.run(
        IC / "compose_report.py", "--dir", str(rd), "-o", str(rd / "report.json"), "--write-md", str(rd / "report.md")
    )


def _ready(tmp_path: Path) -> tuple[Path, str, Path]:
    root, rid, rd = _answered(tmp_path)
    assert _from_request(rd, rid).returncode == 0
    _stage_rest(rd, rid)
    return root, rid, rd


def test_compose_renders_the_supplied_fund_and_no_raw_mode(tmp_path: Path) -> None:
    root, rid, rd = _ready(tmp_path)
    proc = _compose(rd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    md = (rd / "report.md").read_text(encoding="utf-8")
    for line in fp.founder_lines(json.loads((rd / "fund_profile.json").read_text(encoding="utf-8"))):
        assert line in md
    assert "fund_specific" not in md and "**Mode:**" not in md
    warnings = json.loads((rd / "report.json").read_text(encoding="utf-8"))["validation"]["warnings"]
    assert not [w for w in warnings if w["code"] == "FOUNDER_TEXT_TOKEN"]


def test_stamped_steps_stay_current_after_step_four_runs_again(tmp_path: Path) -> None:
    root, rid, rd = _ready(tmp_path)
    assert _from_request(rd, rid).returncode == 0
    assert fp.stale_dependents(str(rd)) == []


@pytest.mark.parametrize("direction", ["stamp_removed", "stamp_on_a_research_run", "stamp_altered"])
def test_compose_refuses_a_source_that_disagrees_with_the_record(tmp_path: Path, direction: str) -> None:
    if direction == "stamp_on_a_research_run":
        root, rid, rd = h.start_bound(tmp_path, "ic-sim")
        rd.mkdir(parents=True, exist_ok=True)
        h.record(root, rid, "answer", "--gate", "ic_mode", "--answer-id", "auto_pilot")
        h.record(root, rid, "answer", "--gate", "ic_fund_mode", "--answer-id", "generic")
        body = json.loads((FIXTURES / "fund_profile.json").read_text(encoding="utf-8"))
        body["metadata"] = {"run_id": rid}
        body["profile_source"] = {"kind": "request", "sha256": "0" * 64}
        (rd / "fund_profile.json").write_text(json.dumps(body), encoding="utf-8")
        _stage_rest(rd, rid)
    else:
        root, rid, rd = _ready(tmp_path)
        prof = json.loads((rd / "fund_profile.json").read_text(encoding="utf-8"))
        if direction == "stamp_removed":
            prof.pop("profile_source")
            prof["sources"] = [{"title": "Example research"}]
        else:
            prof["profile_source"]["sha256"] = "1" * 64
        (rd / "fund_profile.json").write_text(json.dumps(prof), encoding="utf-8")
        _stage_rest(rd, rid)
    proc = _compose(rd)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _out(proc)["code"] == "FUND_PROFILE_SOURCE_MISMATCH"
    assert not (rd / "report.md").exists()


def test_the_request_fixture_is_outside_the_shared_fixture_dir() -> None:
    assert REQUEST_FIXTURE.parent.name == "ic-sim-request" and not (FIXTURES / REQUEST_FIXTURE.name).exists()
