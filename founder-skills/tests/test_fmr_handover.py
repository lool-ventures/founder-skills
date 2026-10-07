"""financial-model-review's hand-over is printed, not written.

The model used to write the closing message itself from the coaching payload's headline fields, so the
rating and the runway reached the founder restated or recomputed in chat. compose now writes a `verdict`
paragraph into report.json -- the report's own first paragraph, built from the same values and helpers
report.md prints -- and `fmr_closing_message.py` prints the links, that verdict and the offer, which the
shared Stop hook holds the final message to.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_financial_model_review import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _VALID_UNIT_ECONOMICS,
    _make_fmr_artifact_dir,
    _run_compose,
)

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "founder-skills" / "skills" / "financial-model-review" / "scripts"
_CLOSER = _SCRIPTS / "fmr_closing_message.py"


def _compose(**overrides: Any) -> dict[str, Any]:
    arts: dict[str, Any] = {
        "inputs.json": _VALID_INPUTS,
        "checklist.json": _VALID_CHECKLIST,
        "unit_economics.json": _VALID_UNIT_ECONOMICS,
        "runway.json": _VALID_RUNWAY,
    }
    arts.update(overrides)
    rc, data, err = _run_compose(_make_fmr_artifact_dir({k: v for k, v in arts.items() if v is not None}))
    assert rc == 0 and data is not None, err
    return data


def _founder_text() -> Any:
    sys.path.insert(0, str(_REPO / "founder-skills" / "scripts"))
    try:
        import _founder_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return _founder_text


def _figures(text: str) -> list[str]:
    return re.findall(r"\d[\d,.]*\s*(?:%|months?)", text)


def test_the_verdict_is_the_reports_own_first_paragraph() -> None:
    data = _compose()
    verdict = data["verdict"]
    assert isinstance(verdict, str) and verdict.strip()
    md = data["report_markdown"]
    assert verdict in md, (verdict, md[:600])
    assert md.index(verdict) < md.index("## Executive Summary")  # first, before the sections
    figures = _figures(verdict)
    assert figures, verdict  # positive control: the verdict carries figures
    body = md.replace(verdict, "")
    for fig in figures:
        assert fig in body, (fig, "must be the figure the report itself prints, not a second rounding")


def test_a_default_alive_model_states_runway_at_todays_burn_too() -> None:
    runway = copy.deepcopy(_VALID_RUNWAY)
    base = runway["scenarios"][0]
    base.update({"runway_months": None, "default_alive": True, "static_runway_months": 14})
    data = _compose(**{"runway.json": runway})
    verdict = data["verdict"]
    assert "Infinite" in verdict and "14 months" in verdict, verdict
    body = data["report_markdown"].replace(verdict, "")
    for fig in _figures(verdict):
        assert fig in body, fig


def test_a_shorter_runway_at_todays_burn_travels_with_the_projected_one() -> None:
    """Projected runway assumes burn held flat while revenue grows; when today's-burn runway is shorter, the
    projected figure alone overstates the cash. Both are stated, the second in the runway table's format."""
    runway = copy.deepcopy(_VALID_RUNWAY)
    runway["scenarios"][0].update({"runway_months": 25, "static_runway_months": 18})
    data = _compose(**{"runway.json": runway})
    verdict = data["verdict"]
    assert "25 months" in verdict and "18 months" in verdict, verdict
    body = data["report_markdown"].replace(verdict, "")
    for fig in _figures(verdict):
        assert fig in body, fig
    # Not when it is longer: then the projected figure is the cautious one.
    runway["scenarios"][0]["static_runway_months"] = 30
    assert "30 months" not in _compose(**{"runway.json": runway})["verdict"]


def test_no_internal_token_reaches_the_verdict() -> None:
    ft = _founder_text()
    for status, pct in (("strong", 90.0), ("solid", 75.0), ("needs_work", 55.0), ("major_revision", 30.0)):
        checklist = copy.deepcopy(_VALID_CHECKLIST)
        checklist["summary"].update({"overall_status": status, "score_pct": pct})
        verdict = _compose(**{"checklist.json": checklist})["verdict"]
        assert ft.scan(verdict) == {"enums": [], "filenames": []}, verdict
        assert "_" not in verdict, verdict


def test_nothing_to_say_is_no_verdict() -> None:
    """Without a checklist or a base runway there is no verdict, and the closer then refuses (below)
    rather than printing links with nothing to say. compose itself refuses a run missing required
    artifacts, so this is the function it calls."""
    sys.path.insert(0, str(_SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("fmr_compose_verdict_t", _SCRIPTS / "compose_report.py")
        assert spec is not None and spec.loader is not None
        compose = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compose)
    finally:
        sys.path.pop(0)
    assert compose._verdict(_VALID_INPUTS, None, None) == ""
    assert compose._verdict(_VALID_INPUTS, _VALID_CHECKLIST, None)  # positive control


def _load_closer() -> Any:
    spec = importlib.util.spec_from_file_location("fmr_closing_message_t", _CLOSER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_closer_prints_links_the_verdict_and_the_offer_last(tmp_path: Path) -> None:
    report = tmp_path / "financial-model-review-acme" / "report.json"
    report.parent.mkdir()
    report.write_text(json.dumps({"verdict": "The verdict paragraph."}), encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(_CLOSER),
            "--report",
            str(report),
            "--deliverable",
            f"the written report={tmp_path}/R.md",
            "--link",
            "path",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.rstrip("\n").splitlines()
    assert lines[0].startswith("Here's your finished financial model review:"), lines[0]
    assert "The verdict paragraph." in r.stdout
    assert lines[-1].startswith("If you want to keep the working data behind this")
    assert lines[-1].endswith("as a single archive.")
    assert (report.parent / "handover.txt").read_text(encoding="utf-8") == r.stdout


def test_the_closer_refuses_a_report_without_a_verdict(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"report_markdown": "x"}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(_CLOSER), "--report", str(report)], capture_output=True, text=True)
    assert r.returncode == 2 and "no verdict" in r.stderr and r.stdout == ""
    assert not (tmp_path / "handover.txt").exists()


def test_link_forms_per_surface() -> None:
    closer = _load_closer()
    assert closer.detect_link_form("/sessions/abc/mnt", {}) == "computer"
    assert closer.detect_link_form("/home/claude", {"CLAUDE_CODE_REMOTE": "true"}) == "none"
    assert closer.detect_link_form("/Users/x/work", {}) == "path"
    text = closer.build({"verdict": "V."}, closer._deliverables(["the written report=/o/R.md"], "computer"))
    assert "[the written report](computer:///o/R.md)" in text
    # Cloud (`none`): the label alone, no dead path beside the file card. Terminal (`path`): the path.
    first = closer.build({"verdict": "V."}, closer._deliverables(["the written report=/o/R.md"], "none")).split("\n")[0]
    assert "the written report" in first and "/o/" not in first and "`" not in first and "](" not in first
    text = closer.build({"verdict": "V."}, closer._deliverables(["the written report=/o/R.md"], "path"))
    assert "[the written report](/o/R.md)" in text


# --- Step 12: the hand-over is the closer's, and each HTML page is named for what it is ------------

_SKILL_MD = _REPO / "founder-skills" / "skills" / "financial-model-review" / "SKILL.md"


def _step12() -> str:
    text = _SKILL_MD.read_text(encoding="utf-8")
    start = text.index("### Step 12: Deliver Artifacts")
    return text[start : text.index("\n## ", start)]


def test_step_12_gives_no_hand_over_to_write_in_the_models_own_words() -> None:
    """The message is printed. An example sentence beside the command is a second template the model
    can follow instead, with its own wording and its own labels."""
    assert "Here's your finished" not in _step12()


def test_step_12_names_each_html_page_with_its_own_label() -> None:
    """Two HTML pages ship: the charts (report.html) and the what-if explorer (explore.html). One
    `the interactive version=<the .html>` line could not say which, so a founder got one of the two."""
    block = re.search(r"fmr_closing_message\.py.*?\n```", _step12(), re.S)
    assert block is not None
    pairs = re.findall(r'--deliverable "([^"=]+)=([^"]+)"', block.group(0))
    labels = {label for label, _ in pairs}
    assert len(pairs) == 3 and len(labels) == 3, pairs
    assert [p for _, p in pairs if "report.html" in p] and [p for _, p in pairs if "explore.html" in p], pairs


def test_the_closer_lists_three_deliverables_under_their_own_labels(tmp_path: Path) -> None:
    closer = _load_closer()
    specs = ["the written report=/o/R.md", "the charts=/o/report.html", "the what-if explorer=/o/explore.html"]
    first = closer.build({"verdict": "V."}, closer._deliverables(specs, "computer")).splitlines()[0]
    for label, path in (s.split("=", 1) for s in specs):
        assert f"[{label}](computer://{path})" in first
    assert first.count("has the charts") == 0, "the label says what the page is; no tail guesses it"


# --- the paid lane checks the hand-over the founder saw ------------------------------------------
# Contract tests pin that the closer prints the verdict and that the Stop hook holds the final message
# to it; only a paid lane shows what a real run put on screen. Each lane for a skill whose hand-over is
# printed regenerates it from the model's own closer call and checks it with the hook's own rule.

_LANES = {
    "closing_message.py": "test_e2e_market_sizing.py",
    "fmr_closing_message.py": "test_e2e_financial_model_review.py",
}


def test_each_paid_lane_holds_the_founders_message_to_the_printed_hand_over() -> None:
    for closer, lane in _LANES.items():
        source = (Path(__file__).resolve().parent / lane).read_text(encoding="utf-8")
        assert "run_skill_capture(" in source, f"{lane} cannot see the closer call without the structured capture"
        assert f'"{closer}" in str(' in source, f"{lane} does not find the model's own {closer} call"
        assert "_handover.contained(" in source, f"{lane} does not apply the Stop hook's containment rule"
        assert "stop_hook_blocks()" in source, f"{lane} does not report whether the Stop hook had to block"


# --- runway not computed for want of the cash balance: the hand-over asks for it --------------------


def _runway_from(inputs: dict[str, Any]) -> dict[str, Any]:
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "runway.py")], input=json.dumps(inputs), capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert isinstance(out, dict)
    return out


def _no_cash_inputs() -> dict[str, Any]:
    """A model that states its burn but not its cash balance (the sample_model.xlsx fixture's shape)."""
    inputs = copy.deepcopy(_VALID_INPUTS)
    inputs["cash"].pop("current_balance", None)
    assert inputs["cash"].get("monthly_net_burn") is not None  # burn known: the balance alone recomputes it
    return inputs


def _closer_output(tmp_path: Path, data: dict[str, Any], *extra: str) -> str:
    report = tmp_path / "financial-model-review-testco" / "report.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(data), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_CLOSER), "--report", str(report), "--deliverable", "the written report=/o/R.md"]
        + ["--link", "path", *extra],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def _load_by_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_missing_cash_balance_is_a_structured_field_in_report_json() -> None:
    inputs = _no_cash_inputs()
    runway = _runway_from(inputs)
    assert runway.get("insufficient_data") is True  # the case under test, as runway.py writes it
    data = _compose(**{"inputs.json": inputs, "runway.json": runway})
    assert data.get("runway_status") == "no_cash_balance"
    # A computed runway carries no field at all.
    computed = _runway_from(copy.deepcopy(_VALID_INPUTS))
    assert not computed.get("insufficient_data")  # positive control: this one is computed
    full = _compose(**{"runway.json": computed})
    assert "runway_status" not in full
    # Cash and burn both missing: the balance alone would not recompute it, so no request is keyed.
    neither = copy.deepcopy(inputs)
    neither["cash"].pop("monthly_net_burn", None)
    assert "runway_status" not in _compose(**{"inputs.json": neither, "runway.json": _runway_from(neither)})


def test_the_hand_over_asks_for_the_cash_balance_before_the_offer(tmp_path: Path) -> None:
    inputs = _no_cash_inputs()
    data = _compose(**{"inputs.json": inputs, "runway.json": _runway_from(inputs)})
    printed = _closer_output(tmp_path, data)
    closer = _load_closer()
    ask = closer.ASK_FOR_CASH_BALANCE
    lines = printed.rstrip("\n").splitlines()
    assert ask in lines, printed
    assert lines[-1].startswith("If you want to keep the working data behind this"), lines[-1]
    assert lines.index(ask) < len(lines) - 1
    assert ask not in data["verdict"] and ask not in data["report_markdown"]  # the chat's, not the report's
    # Founder-facing: no field name, no code, no internal token.
    ft = _founder_text()
    assert ft.scan(ask) == {"enums": [], "filenames": []}, ask
    assert "_" not in ask and not re.search(r"\d", ask), ask
    leak_scan = _load_by_path("fmr_leak_scan_t", _REPO / "cowork-tests" / "leak_scan.py")
    assert leak_scan.scan_text(printed) == [], printed
    # The Stop hook accepts a final message equal to the printed text, both from handover.txt and from
    # the transcript slice it falls back to (opener line to the offer's end).
    hook_dir = _REPO / "founder-skills" / "scripts"
    contained = _load_by_path("fmr_handover_contained_t", hook_dir / "_handover_check.py").contained
    assert contained(printed, printed)[0]
    hook = _load_by_path("fmr_stop_hook_t", hook_dir / "stop_handover_check.py")
    sliced = hook.printed_from_result("noise before\n" + printed + "noise after\n", "finished financial model review")
    assert sliced is not None and ask in sliced
    assert contained(sliced, printed)[0]
    # A final message that drops the request is not the printed hand-over.
    assert not contained(printed, printed.replace(ask + "\n\n", ""))[0]


def test_with_a_cash_balance_the_hand_over_asks_for_nothing(tmp_path: Path) -> None:
    data = _compose(**{"runway.json": _runway_from(copy.deepcopy(_VALID_INPUTS))})
    printed = _closer_output(tmp_path, data)
    assert _load_closer().ASK_FOR_CASH_BALANCE not in printed
    assert "cash balance" not in printed


@pytest.mark.parametrize("model_format", ["spreadsheet", "deck", "conversational"])
def test_the_request_for_the_balance_is_true_for_every_input_kind(model_format: str, tmp_path: Path) -> None:
    """A deck is the input most likely to lack the balance, so the request fires there too, in words
    that do not call the input a model."""
    inputs = _no_cash_inputs()
    inputs["company"]["model_format"] = model_format
    data = _compose(**{"inputs.json": inputs, "runway.json": _runway_from(inputs)})
    assert data.get("runway_status") == "no_cash_balance"
    ask = _load_closer().ASK_FOR_CASH_BALANCE
    assert ask in _closer_output(tmp_path, data)
    assert "model" not in ask.lower()


def test_the_founders_reply_recomputes_runway_by_the_skill_md_commands(tmp_path: Path) -> None:
    """Step 12's follow-up: --set adds the balance and its date even when the extraction left both keys
    out, and runway re-run on the promoted inputs is computed, so the request is not printed again."""
    inputs = _no_cash_inputs()
    inputs["cash"].pop("balance_date", None)
    assert "current_balance" not in inputs["cash"] and "balance_date" not in inputs["cash"]
    (tmp_path / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "apply_corrections.py")]
        + ["--set", "cash.current_balance=1500000", "--set", "cash.balance_date=2026-09"]
        + ["--original", str(tmp_path / "inputs.json"), "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    corrected = json.loads((tmp_path / "corrected_inputs.json").read_text(encoding="utf-8"))
    assert corrected["cash"]["current_balance"] == 1500000 and corrected["cash"]["balance_date"] == "2026-09"
    runway = _runway_from(corrected)
    assert not runway.get("insufficient_data"), runway.get("warnings")
    assert "runway_status" not in _compose(**{"inputs.json": corrected, "runway.json": runway})


def test_the_re_run_after_the_cash_reply_prints_its_own_update_line(tmp_path: Path) -> None:
    """On the re-run turn the model announced the update in its own words around the hand-over, and the
    Stop hook then added a second message. The closer prints that sentence itself, after the opener and
    before the verdict, so the printed text is still the whole final message and the hook still finds it."""
    data = _compose(**{"runway.json": _runway_from(copy.deepcopy(_VALID_INPUTS))})
    update = _load_closer().CASH_UPDATE
    plain = _closer_output(tmp_path, data)
    printed = _closer_output(tmp_path, data, "--cash-update")
    assert update not in plain
    lines = printed.rstrip("\n").splitlines()
    assert lines[0].startswith("Here's your finished financial model review:")
    assert lines.index(update) < lines.index(data["verdict"].strip().splitlines()[0])
    assert lines[-1].startswith("If you want to keep the working data behind this")
    assert (tmp_path / "financial-model-review-testco" / "handover.txt").read_text(encoding="utf-8") == printed
    assert _founder_text().scan(update) == {"enums": [], "filenames": []}
    assert not re.search(r"\d", update)
    hook_dir = _REPO / "founder-skills" / "scripts"
    hook = _load_by_path("fmr_stop_hook_u", hook_dir / "stop_handover_check.py")
    sliced = hook.printed_from_result("noise\n" + printed + "noise\n", "finished financial model review")
    assert sliced is not None and update in sliced


def test_step_12_closes_the_cash_re_run_with_the_update_flag() -> None:
    skill = (_REPO / "founder-skills" / "skills" / "financial-model-review" / "SKILL.md").read_text(encoding="utf-8")
    follow_up = skill[skill.index("**When the hand-over asked for the cash balance") :]
    follow_up = follow_up[: follow_up.index("\n## ")]
    assert "--cash-update" in follow_up


def test_a_misspelt_cash_path_is_still_refused(tmp_path: Path) -> None:
    """Only the two named cash paths may be added; a typo beside them is refused as before."""
    (tmp_path / "inputs.json").write_text(json.dumps(_no_cash_inputs()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "apply_corrections.py"), "--set", "cash.current_balanse=1"]
        + ["--original", str(tmp_path / "inputs.json"), "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "PATH_ERROR" in r.stdout
    assert not (tmp_path / "corrected_inputs.json").exists()
