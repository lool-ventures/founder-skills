"""Edges of the values a request supplies, through the real scripts: a context line Step 1 never opened, values that
are not finite numbers, e-mail addresses in any script, control characters that reorder text, a question only a
request line can answer on an attended run, and the fund profile's own output guard. Every company, address and
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
IC_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ic-sim"
REQUEST_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ic-sim-request" / "fund_profile_request.json"
RUN_ID = "edge-run-1"
GOOD = {"fact": "Raising a seed round; lead not set", "source": "source A", "date": "2026-01-05"}


def _module(name: str, path: Path) -> ModuleType:
    for d in (h.SHARED, IC):
        if str(d) not in sys.path:
            sys.path.append(str(d))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _module("_edge_fund_profile", IC / "fund_profile.py")
ht = _module("_edge_host_text", h.SHARED / "_host_text.py")


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[0])
    return data


def _value(items: Any) -> str:
    return json.dumps(items, separators=(",", ":"))


def _lines(*extra: str, no_ask: bool = True) -> str:
    head = [f"FS_HOST_RUN_ID={RUN_ID}", *(["FS_HOST_NO_ASK"] if no_ask else []), "FS_HOST_ANSWER ctx_basics.stage=seed"]
    return "\n".join([*head, *extra]) + "\n"


def _ctx_line(value: str) -> str:
    return f"FS_HOST_VALUE host_context=supplied | {value}"


def _open(root: Path, rid: str, *gates: str) -> Any:
    return h.record(root, rid, "open", *[a for gate in gates for a in ("--gate", gate)])


def _write_steps(rd: Path, rid: str, extra: dict[str, Any] | None = None) -> None:
    rd.mkdir(parents=True, exist_ok=True)
    for f in sorted(IC_FIXTURES.iterdir(), key=lambda p: p.name != "fund_profile.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": rid}
        if f.name == "startup_profile.json" and extra:
            data.update(extra)
        if f.name in fp.PROFILE_DEPENDENTS:
            fp.stamp_profile(data, str(rd / f.name))
        (rd / f.name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _hc(rd: Path, rid: str) -> Any:
    return h.run(IC / "host_context.py", "--run-id", rid, "--profile", str(rd / "startup_profile.json"))


def _compose(rd: Path) -> Any:
    return h.run(
        IC / "compose_report.py", "--dir", str(rd), "-o", str(rd / "report.json"), "--write-md", str(rd / "report.md")
    )


# --- a context line Step 1 never opened ------------------------------------------------------------------


def test_host_context_py_applies_a_line_step_one_did_not_open(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_ctx_line(_value([GOOD]))))
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 0  # no `--gate host_context`
    _write_steps(rd, rid)
    proc = _hc(rd, rid)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads((rd / "startup_profile.json").read_text(encoding="utf-8"))["host_context"]["items"]
    assert h.ledger(root, rid)["gates"]["host_context"]["state"] == "answered"


@pytest.mark.parametrize("no_ask,code", [(True, 12), (False, 10)])
def test_host_context_py_waits_on_a_line_that_cannot_be_read(tmp_path: Path, no_ask: bool, code: int) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_ctx_line("not json"), no_ask=no_ask))
    _write_steps(rd, rid)
    before = (rd / "startup_profile.json").read_bytes()
    proc = _hc(rd, rid)
    assert proc.returncode == code, proc.stdout + proc.stderr
    assert "needs_input" not in _out(proc)  # nothing to ask a person
    assert (rd / "startup_profile.json").read_bytes() == before
    assert h.status(root, rid)["code"] == "PRE_ANSWER_MALFORMED"


def test_compose_refuses_a_context_line_no_step_applied(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_ctx_line(_value([GOOD])), no_ask=False))
    h.record(root, rid, "answer", "--gate", "ic_mode", "--answer-id", "auto_pilot")
    h.record(root, rid, "answer", "--gate", "ic_fund_mode", "--answer-id", "generic")
    _write_steps(rd, rid)
    proc = _compose(rd)
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_CONTEXT_MISSING", proc.stdout + proc.stderr
    assert not (rd / "report.md").exists()


# --- an attended run: a question only the request can answer is never put ---------------------------------


def test_an_attended_open_never_asks_a_request_only_question(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_ctx_line("not json"), no_ask=False))
    proc = _open(root, rid, "ic_mode", "host_context")
    assert proc.returncode == 10, proc.stdout + proc.stderr
    out = _out(proc)
    assert [n["gate"] for n in out["needs_input"]] == ["ic_mode"]
    assert [w["gate"] for w in out["request_waiting"]] == ["host_context"]
    assert "not valid JSON" in out["request_waiting"][0]["reason"]
    assert all("host_context" not in b["gates"] for b in h.ledger(root, rid)["form_batches"])


# --- numbers that are not finite --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_a_non_finite_number_waits_at_step_one(tmp_path: Path, raw: str) -> None:
    ctx = '[{"fact":"x","source":"s","date":"2026-01-05","n":' + raw + "}]"
    fund = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    fund_value = _value(fund).replace('"min":1000000', '"min":' + raw)
    lines = _lines(_ctx_line(ctx), f"FS_HOST_VALUE ic_fund_mode=host_profile | {fund_value}")
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=lines)
    proc = _open(root, rid, "ic_mode", "ic_fund_mode", "host_context")
    assert proc.returncode == 12 and "Traceback" not in proc.stderr, proc.stdout + proc.stderr
    flags = h.ledger(root, rid)["gates"]
    assert "pre_answer_malformed" in flags["host_context"]["flags"]
    assert "pre_answer_malformed" in flags["ic_fund_mode"]["flags"]
    chk = h.run(h.RUN_STATUS, "check", "--skill", "ic-sim", stdin=lines.replace(RUN_ID, "edge-run-2"))
    assert chk.returncode == 4 and "Traceback" not in chk.stderr


def test_an_overwide_integer_is_refused_at_step_four_not_a_traceback(tmp_path: Path) -> None:
    fund = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    value = _value(fund).replace('"max":5000000', '"max":' + "9" * 4000)
    root, rid, rd = h.start_bound(
        tmp_path, "ic-sim", lines=_lines(f"FS_HOST_VALUE ic_fund_mode=host_profile | {value}")
    )
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 0
    rd.mkdir(parents=True, exist_ok=True)
    proc = h.run(IC / "fund_profile.py", "--from-request", "--run-id", rid, "-o", str(rd / "fund_profile.json"))
    assert proc.returncode == 1 and "Traceback" not in proc.stderr, proc.stderr
    assert "check_size_range.min and max must be numbers" in proc.stdout
    assert not (rd / "fund_profile.json").exists()


def test_a_stdin_profile_with_a_non_finite_check_size_is_refused() -> None:
    body = json.loads((IC_FIXTURES / "fund_profile.json").read_text(encoding="utf-8"))
    body["check_size_range"] = {"min": float("nan"), "max": float("inf")}
    proc = h.run(IC / "fund_profile.py", "--run-id", RUN_ID, stdin=json.dumps(body))
    assert proc.returncode == 1 and "must be numbers" in proc.stdout


# --- the per-item rules -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Write to josé@example.com",
        "Write to someone＠example.com",
        "Write to пример@example.com",
    ],
)
def test_an_e_mail_address_in_any_script_is_person_detail(text: str) -> None:
    assert ht.has_person_detail(text)


@pytest.mark.parametrize("ch", ["‮", "⁦", "​", "﻿"])
def test_a_bidirectional_or_zero_width_character_is_dropped(ch: str) -> None:
    kept, dropped = ht.filter_items([{**GOOD, "fact": f"Revenue {ch}grew"}], __import__("datetime").date(2026, 2, 1))
    assert kept == [] and dropped == [{"index": 1, "cause": "control_characters"}]


def test_a_numbered_line_marker_is_escaped() -> None:
    compose = _module("_edge_compose", IC / "compose_report.py")
    assert compose._md_escape("1) first") == "1\\) first"
    assert compose._md_escape("12. twelfth") == "12\\. twelfth"


# --- host_context.py and a model-written profile ---------------------------------------------------------


def test_a_line_separator_in_the_model_written_profile_does_not_crash(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(_ctx_line(_value([GOOD]))))
    assert _open(root, rid, "ic_mode", "ic_fund_mode", "host_context").returncode == 0
    _write_steps(rd, rid, {"one_liner": "Line one line two"})
    proc = _hc(rd, rid)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- compose: a supplied fund with no fund profile -------------------------------------------------------


def test_compose_refuses_a_supplied_fund_with_no_fund_profile(tmp_path: Path) -> None:
    value = REQUEST_FIXTURE.read_text(encoding="utf-8").strip()
    root, rid, rd = h.start_bound(
        tmp_path, "ic-sim", lines=_lines(f"FS_HOST_VALUE ic_fund_mode=host_profile | {value}")
    )
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 0
    _write_steps(rd, rid)
    (rd / "fund_profile.json").unlink()
    proc = _compose(rd)
    assert proc.returncode == 1 and _out(proc)["code"] == "FUND_PROFILE_SOURCE_MISMATCH", proc.stdout + proc.stderr


# --- fund_profile.py --from-request: its output guard and its usage ---------------------------------------


def test_from_request_refuses_an_output_that_is_the_run_ledger(tmp_path: Path) -> None:
    value = REQUEST_FIXTURE.read_text(encoding="utf-8").strip()
    root, rid, rd = h.start_bound(
        tmp_path, "ic-sim", lines=_lines(f"FS_HOST_VALUE ic_fund_mode=host_profile | {value}")
    )
    assert _open(root, rid, "ic_mode", "ic_fund_mode").returncode == 0
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "fund_profile.json").symlink_to(h.ledger_path(root, rid))
    before = h.ledger_path(root, rid).read_bytes()
    proc = h.run(IC / "fund_profile.py", "--from-request", "--run-id", rid, "-o", str(rd / "fund_profile.json"))
    assert proc.returncode == 1 and _out(proc)["code"] == "OUTPUT_IS_INPUT", proc.stdout + proc.stderr
    assert h.ledger_path(root, rid).read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == hashlib.sha256(h.ledger_path(root, rid).read_bytes()).hexdigest()


def test_from_request_without_an_output_is_a_usage_error() -> None:
    proc = h.run(IC / "fund_profile.py", "--from-request", "--run-id", RUN_ID)
    assert proc.returncode == 2 and _out(proc)["code"] == "USAGE"
