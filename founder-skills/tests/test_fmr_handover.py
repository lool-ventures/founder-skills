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
