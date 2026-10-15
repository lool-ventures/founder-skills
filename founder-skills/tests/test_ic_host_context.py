"""ic-sim's use of context supplied with the request, through the real scripts: `host_context.py` copies the kept
items into the startup profile, compose checks the profile against the run's record and renders the items
verbatim (marked unchecked, not the founder's own), and founder context never carries them. Every company,
label, address and figure here is invented.
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

IC_SCRIPTS = h.SKILLS / "ic-sim" / "scripts"
IC_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ic-sim"
HC = IC_SCRIPTS / "host_context.py"
RUN_ID = "ic-hc-run-1"
GOOD = {"fact": "Raising a seed round; lead not set", "source": "source A", "date": "2026-01-05"}
MARK = "QZWMARKQZW"


def _fp() -> ModuleType:
    if str(IC_SCRIPTS) not in sys.path:
        sys.path.append(str(IC_SCRIPTS))
    spec = importlib.util.spec_from_file_location("_ichc_fund_profile", IC_SCRIPTS / "fund_profile.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _fp()


def _value(items: Any) -> str:
    return json.dumps(items, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lines(value: str) -> str:
    return (
        f"FS_HOST_RUN_ID={RUN_ID}\nFS_HOST_NO_ASK\nFS_HOST_ANSWER ctx_basics.stage=seed\n"
        f"FS_HOST_VALUE host_context=supplied | {value}\n"
    )


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[0])
    return data


def _open(root: Path, rid: str, *gates: str) -> Any:
    return h.record(root, rid, "open", *[a for gate in gates for a in ("--gate", gate)])


def _write_steps(rd: Path, rid: str, startup_extra: dict[str, Any] | None = None) -> None:
    rd.mkdir(parents=True, exist_ok=True)
    for f in sorted(IC_FIXTURES.iterdir(), key=lambda p: p.name != "fund_profile.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        data["metadata"] = {**(data.get("metadata") or {}), "run_id": rid}
        if f.name == "startup_profile.json" and startup_extra:
            data.update(startup_extra)
        if f.name in fp.PROFILE_DEPENDENTS:
            fp.stamp_profile(data, str(rd / f.name))
        (rd / f.name).write_text(json.dumps(data), encoding="utf-8")


def _sim(tmp_path: Path, value: str) -> tuple[Path, str, Path]:
    """A no-ask simulation whose Step 1 applied the context and the generic fund, with Steps 2-8 written."""
    root, rid, rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    assert _open(root, rid, "ic_mode", "ic_fund_mode", "host_context").returncode == 0
    _write_steps(rd, rid)
    return root, rid, rd


def _hc(rd: Path, rid: str) -> Any:
    return h.run(HC, "--run-id", rid, "--profile", str(rd / "startup_profile.json"))


def _compose(rd: Path) -> Any:
    return h.run(
        IC_SCRIPTS / "compose_report.py",
        "--dir",
        str(rd),
        "-o",
        str(rd / "report.json"),
        "--write-md",
        str(rd / "report.md"),
    )


_REPORT_ITEMS = [
    {**GOOD, "fact": "Stage is pre_seed per the data room"},
    {**GOOD, "fact": "**bold** claim about revenue"},
    {**GOOD, "fact": "# a heading-like line"},
    {**GOOD, "fact": "Prix fixe: café pricing in €"},
]


def test_host_context_py_adds_the_kept_items_deterministically(tmp_path: Path) -> None:
    value = _value([*_REPORT_ITEMS, {**GOOD, "fact": MARK + " someone@example.com"}])
    _root, rid, rd = _sim(tmp_path, value)
    proc = _hc(rd, rid)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (rd / "startup_profile.json").read_text(encoding="utf-8")
    block = json.loads(text)["host_context"]
    assert block["provenance"] == "supplied_with_request" and block["sha256"] == _sha(value)
    assert [i["index"] for i in block["items"]] == [1, 2, 3, 4]
    assert block["dropped"] == [{"index": 5, "cause": "person_detail"}]
    assert MARK not in text and "café" in text  # characters, not escapes
    assert _hc(rd, rid).returncode == 0
    assert (rd / "startup_profile.json").read_text(encoding="utf-8") == text


def test_host_context_py_without_a_ledger_does_nothing(tmp_path: Path) -> None:
    rd = tmp_path / "sim"
    rd.mkdir()
    (rd / "startup_profile.json").write_text('{"company_name": "Example Co"}', encoding="utf-8")
    before = (rd / "startup_profile.json").read_bytes()
    assert _hc(rd, RUN_ID).returncode == 0
    assert (rd / "startup_profile.json").read_bytes() == before


def test_host_context_py_refuses_a_model_written_block(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim")
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "startup_profile.json").write_text(json.dumps({"host_context": {"items": []}}), encoding="utf-8")
    before = (rd / "startup_profile.json").read_bytes()
    proc = _hc(rd, rid)
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_CONTEXT_NOT_SUPPLIED"
    assert (rd / "startup_profile.json").read_bytes() == before


@pytest.mark.parametrize("edit", ["value", "evidence"])
def test_host_context_py_refuses_an_edited_record(tmp_path: Path, edit: str) -> None:
    root, rid, rd = _sim(tmp_path, _value([GOOD]))
    path = h.ledger_path(root, rid)
    led = json.loads(path.read_text(encoding="utf-8"))
    cur = led["gates"]["host_context"]["current"]
    if edit == "value":
        cur["value"] = _value([{**GOOD, "fact": "Edited"}])
    else:
        cur["evidence"]["kept"] = []
    path.write_text(json.dumps(led), encoding="utf-8")
    proc = _hc(rd, rid)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


def test_compose_renders_the_context_verbatim_and_keeps_its_tokens(tmp_path: Path) -> None:
    value = _value([*_REPORT_ITEMS, {**GOOD, "fact": MARK, "date": "2026-02-30"}])
    _root, rid, rd = _sim(tmp_path, value)
    assert _hc(rd, rid).returncode == 0
    proc = _compose(rd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    md = (rd / "report.md").read_text(encoding="utf-8")
    report = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    assert "## Context Supplied With This Request" in md
    assert "not the founder's own statements" in md
    unescaped = md.replace("\\", "")
    for item in _REPORT_ITEMS:
        assert f"{item['fact']} ({item['source']}, {item['date']})" in unescaped
    assert "\n- \\# a heading" in md and "\\*\\*bold\\*\\*" in md
    assert "1 of 5 facts supplied with this request was not used: fact 5 (its date was not a real date)." in md
    assert not [w for w in report["validation"]["warnings"] if w["code"] == "FOUNDER_TEXT_TOKEN"]
    hc = report["host_context"]
    assert hc["sha256"] == _sha(value) and "pre_seed" in hc["keep_tokens"]
    assert report["disclosures"] == ["HOST_CONTEXT_SUPPLIED", "HOST_CONTEXT_ITEMS_DROPPED"]
    for name in ("report.md", "report.json", "startup_profile.json", "compose_result.json"):
        if (rd / name).exists():
            assert MARK not in (rd / name).read_text(encoding="utf-8"), name
    # The coaching payload reads the profile's company name only: nothing supplied reaches it.
    assert "Stage is pre" not in json.dumps(report["coaching_payload"])


def test_compose_refuses_a_profile_without_the_supplied_context(tmp_path: Path) -> None:
    _root, _rid, rd = _sim(tmp_path, _value([GOOD]))
    proc = _compose(rd)
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_CONTEXT_MISSING"
    assert str(rd / "startup_profile.json") in _out(proc)["message"]
    assert not (rd / "report.md").exists()


def test_compose_refuses_context_the_request_did_not_supply(tmp_path: Path) -> None:
    root, rid, rd = h.start_bound(tmp_path, "ic-sim")
    h.record(root, rid, "answer", "--gate", "ic_mode", "--answer-id", "auto_pilot")
    h.record(root, rid, "answer", "--gate", "ic_fund_mode", "--answer-id", "generic")
    _write_steps(rd, rid, {"host_context": {"provenance": "supplied_with_request", "items": [], "dropped": []}})
    proc = _compose(rd)
    assert proc.returncode == 1 and _out(proc)["code"] == "HOST_CONTEXT_NOT_SUPPLIED"
    assert not (rd / "report.md").exists()


def test_the_page_hand_off_renders_the_same_lines() -> None:
    sys.path.append(str(IC_SCRIPTS))
    import host_context  # type: ignore[import-not-found]

    profile = {
        "host_context": {
            "items": [{"index": 1, **GOOD}],
            "dropped": [{"index": 2, "cause": "date_after_run_start"}],
        }
    }
    assert host_context.host_context_lines(profile) == [
        host_context.INTRO,
        "Raising a seed round; lead not set (source A, 2026-01-05)",
        "1 of 2 facts supplied with this request was not used: fact 2 (it was dated after this run started).",
    ]
    assert host_context.host_context_lines({}) == []


# --- founder context never carries it ---------------------------------------------------------------------


def test_founder_context_never_carries_the_context(tmp_path: Path) -> None:
    value = _value([{**GOOD, "fact": MARK + " revenue grew"}])
    root, rid, _rd = h.start_bound(tmp_path, "ic-sim", lines=_lines(value))
    _open(root, rid, "ctx_basics.company_name", "ctx_basics.stage", "ctx_basics.sector", "ctx_basics.geography")
    _open(root, rid, "ic_mode", "ic_fund_mode", "host_context")
    fc = h.SHARED / "founder_context.py"
    for gate, option in (
        ("ctx_basics.company_name", "working_title"),
        ("ctx_basics.sector", "not_sure"),
        ("ctx_basics.geography", "not_sure"),
    ):
        h.record(root, rid, "default", "--gate", gate, "--reason", "no_signal_marked_to_confirm", "--answer-id", option)
    init = h.run(
        fc,
        "init",
        "--company-name",
        "Example Co",
        "--stage",
        "seed",
        "--sector",
        "",
        "--geography",
        "",
        "--artifacts-root",
        str(root),
        "--run-id",
        rid,
        "--skill",
        "ic-sim",
    )
    stored = list(root.glob("founder-context-*.json"))
    assert stored, init.stdout + init.stderr
    for f in stored:
        text = f.read_text(encoding="utf-8")
        assert MARK not in text and "host_context" not in text
    read = h.run(fc, "read", "--artifacts-root", str(root))
    assert MARK not in read.stdout
    slug = stored[0].name[len("founder-context-") : -len(".json")]
    before = stored[0].read_bytes()
    merge = h.run(
        fc,
        "merge",
        "--slug",
        slug,
        "--source",
        "user",
        "--data",
        json.dumps({"host_context": [GOOD]}),
        "--artifacts-root",
        str(root),
    )
    assert merge.returncode == 1 and _out(merge)["code"] == "HOST_CONTEXT_NOT_FOUNDER_CONTEXT"
    assert stored[0].read_bytes() == before
