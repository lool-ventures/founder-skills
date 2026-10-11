"""market-sizing's comparison redo: `dispatch_prompt.py <sizing context> --redo comparison`.

A paid gate run's "both" sizing flagged a TAM gap; the model re-sent the top-down dispatch with a repair it
wrote itself, the dispatch hook rewrote it back to the printed prompt (by design), and the build was redone
from identical instructions with nothing recording it. The redo is now printed by the generator, recorded,
used by the sizing, and disclosed. These tests drive the real scripts on disk.
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "skills" / "market-sizing" / "scripts"
GEN = SCRIPTS / "dispatch_prompt.py"
MS = SCRIPTS / "market_sizing.py"
CHECK = PLUGIN / "scripts" / "check_handoff.py"
RUN = "redo-run-7"
AGENT = "/agent/ms-quillfern"


def _load(name: str, path: Path) -> Any:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("ms_gen_redo", GEN)
sr = _load("_sizing_redo", SCRIPTS / "_sizing_redo.py")

# Invented research: an orchard-sensor market, two builds that disagree by far more than 30%.
_VALIDATION: dict[str, Any] = {
    "assumptions": [
        {
            "name": "orchard_sensor_total",
            "value": 9_400_000_000,
            "unit": "money_total_per_year",
            "currency": "USD",
            "category": "sourced",
            "label": "Orchard sensor spend, all regions",
        },
        {
            "name": "pear_belt_share",
            "value": 12,
            "category": "sourced",
            "unit": "percent_points",
            "label": "Pear-belt share",
        },
        {
            "name": "reachable_share",
            "value": 5,
            "category": "agent_estimate",
            "unit": "percent_points",
            "label": "Reachable share",
        },
        {"name": "pear_growers", "value": 4100, "unit": "count", "category": "sourced", "label": "Pear growers"},
        {
            "name": "sensor_price",
            "value": 2600,
            "unit": "money_per_customer",
            "currency": "USD",
            "period": "year",
            "category": "sourced",
            "label": "Sensor plan price",
        },
        {"name": "served_share", "value": 60, "category": "sourced", "unit": "percent_points", "label": "Served share"},
        {
            "name": "target_share",
            "value": 8,
            "category": "agent_estimate",
            "unit": "percent_points",
            "label": "Target share",
        },
    ],
    "metadata": {"run_id": RUN},
}
_TD = {
    "industry_total": {"assumption": "orchard_sensor_total"},
    "approach": "top_down",
    "segment_pct": {"assumption": "pear_belt_share"},
    "share_pct": {"assumption": "reachable_share"},
}
_BU = {
    "approach": "bottom_up",
    "customer_count": {"assumption": "pear_growers"},
    "arpu": {"assumption": "sensor_price"},
    "serviceable_pct": {"assumption": "served_share"},
    "target_pct": {"assumption": "target_share"},
}
_COMPARISON = {
    "top_down_tam": 9_400_000_000,
    "bottom_up_tam": 10_660_000,
    "tam_delta_pct": 199.5,
    "warning": "Top-down and bottom-up TAM differ by a factor of 881.8 (top-down is higher). Review assumptions.",
    "top_down_sam": 1_128_000_000,
    "bottom_up_sam": 6_396_000,
    "sam_delta_pct": 197.7,
    "sam_warning": "Top-down and bottom-up SAM differ by a factor of 176.4 (top-down is higher).",
    "top_down_som": 56_400_000,
    "bottom_up_som": 511_680,
    "som_delta_pct": 196.4,
    "som_warning": "SOM: the top-down build is 110.2 times the bottom-up one.",
}


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _gate(path: Path) -> None:
    r = subprocess.run([sys.executable, str(CHECK), str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _run_dir(tmp_path: Path, *, comparison: dict[str, Any] | None = None) -> tuple[Path, Path]:
    a = tmp_path / "market-sizing-quillfern"
    h = a / "handoff" / RUN
    _write(a / "inputs.json", {"company_name": "Quillfern", "metadata": {"run_id": RUN}})
    _write(a / "methodology.json", {"approach_chosen": "both", "metadata": {"run_id": RUN}})
    _write(a / "validation.json", _VALIDATION)
    _write(
        a / "sizing.json",
        {
            "approach": "both",
            "top_down": {"tam": {"value": 1}},
            "bottom_up": {"tam": {"value": 1}},
            "comparison": _COMPARISON if comparison is None else comparison,
            "metadata": {"run_id": RUN},
        },
    )
    _write(h / "top_down_output.json", _TD)
    _write(h / "bottom_up_output.json", _BU)
    _gate(h / "top_down_output.json")
    _gate(h / "bottom_up_output.json")
    return a, h


def _gen(a: Path, h: Path, context: str = "top_down_methodology", *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GEN),
            context,
            "--run-id",
            RUN,
            "--analysis-dir",
            str(a),
            "--handoff-dir",
            str(h),
            "--handoff-agent",
            f"{AGENT}/handoff/{RUN}",
            "--analysis-dir-agent",
            AGENT,
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def _redo(a: Path, h: Path, context: str = "top_down_methodology", *extra: str) -> subprocess.CompletedProcess[str]:
    return _gen(a, h, context, "--redo", "comparison", *extra)


def _refused(r: subprocess.CompletedProcess[str], code: str) -> dict[str, Any]:
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "CONTEXT:" not in r.stdout, "a refusal printed a context line, which the hook would take as a prompt"
    out: dict[str, Any] = json.loads(r.stdout)
    assert out["code"] == code and out["status"] == "refused", out
    assert code in r.stderr
    return out


def _rewrite_handoff(h: Path, data: dict[str, Any], name: str = "top_down_output.json") -> None:
    """The redo sub-agent writes its file after the print; then the main thread gates it."""
    time.sleep(0.01)
    _write(h / name, data)
    _gate(h / name)


# --- T1: each refusal, with nothing written and no context line ------------------------------------------


def test_a_run_with_no_sizing_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    (a / "sizing.json").unlink()
    _refused(_redo(a, h), "SIZING_REDO_NO_SIZING")
    assert not (a / sr.RECORD_NAME).exists()


def test_another_runs_sizing_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    data = json.loads((a / "sizing.json").read_text())
    data["metadata"]["run_id"] = "an-older-run"
    _write(a / "sizing.json", data)
    _refused(_redo(a, h), "SIZING_REDO_NO_SIZING")


def test_an_unflagged_sizing_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path, comparison={"tam_delta_pct": 4.0, "note": "TAM estimates differ by 4.0%."})
    _refused(_redo(a, h), "SIZING_REDO_NOT_FLAGGED")
    assert not (a / sr.RECORD_NAME).exists()


def test_the_producers_flag_is_read_not_the_number(tmp_path: Path) -> None:
    """T2: a SAM gap of 31% whose warning was deleted by hand is not a flag."""
    a, h = _run_dir(tmp_path, comparison={"tam_delta_pct": 9.0, "note": "x", "sam_delta_pct": 31.0, "sam_note": "y"})
    _refused(_redo(a, h), "SIZING_REDO_NOT_FLAGGED")


def test_a_single_approach_sizing_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    data = json.loads((a / "sizing.json").read_text())
    del data["bottom_up"]
    _write(a / "sizing.json", data)
    _refused(_redo(a, h), "SIZING_REDO_NOT_FLAGGED")


@pytest.mark.parametrize("artifact", ["sensitivity.json", "checklist.json", "redteam.json"])
def test_past_the_sizing_it_is_too_late(tmp_path: Path, artifact: str) -> None:
    a, h = _run_dir(tmp_path)
    _write(a / artifact, {"metadata": {"run_id": RUN}})
    _refused(_redo(a, h), "SIZING_REDO_TOO_LATE")


def test_another_runs_sensitivity_is_not_too_late(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    _write(a / "sensitivity.json", {"metadata": {"run_id": "an-older-run"}})
    assert _redo(a, h).returncode == 0


def test_an_ungated_first_build_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    (h / "top_down_output.json.gate.json").unlink()
    _refused(_redo(a, h), "SIZING_REDO_NO_FIRST_BUILD")


def test_a_missing_first_build_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    (h / "top_down_output.json").unlink()
    _refused(_redo(a, h), "SIZING_REDO_NO_FIRST_BUILD")


@pytest.mark.parametrize(
    "extra",
    [
        ("--suspect", "arpu"),  # the other build's input
        ("--suspect", "industry_total", "--suspect", "industry_total"),
        ("--suspect", "market_total"),
    ],
)
def test_a_suspect_outside_the_builds_own_inputs_is_a_usage_error(tmp_path: Path, extra: tuple[str, ...]) -> None:
    a, h = _run_dir(tmp_path)
    r = _redo(a, h, "top_down_methodology", *extra)
    assert r.returncode == 2 and r.stdout == "", r
    assert not (a / sr.RECORD_NAME).exists()


def test_redo_and_suspect_are_refused_where_they_mean_nothing(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _gen(a, h, "checklist", "--redo", "comparison").returncode == 2
    assert _gen(a, h, "top_down_methodology", "--suspect", "share_pct").returncode == 2


def test_the_suspect_lists_are_each_builds_own_output_shape() -> None:
    for context, names in gen.SUSPECTS.items():
        shape = re.findall(r'^\s+"([a-z_]+)": <reference>', "\n".join(gen._SIZING_LINES[context]), re.M)
        assert tuple(shape) == names == sr.BUILDS[context][2]


def test_the_host_contract_lists_every_code_the_redo_prints() -> None:
    raised = set(re.findall(r'RedoRefused\(\s*"([A-Z_]+)"', GEN.read_text(encoding="utf-8")))
    contract = json.loads((PLUGIN / "data" / "host-contract.json").read_text(encoding="utf-8"))
    assert len(raised) >= 7 and raised == set(contract["cli_codes"]["ms_sizing_redo"])


def test_step_5_names_the_redo_the_generator_accepts() -> None:
    """Prose and script cannot drift: Step 5 names the option, and the generator parses exactly that."""
    text = (PLUGIN / "skills" / "market-sizing" / "SKILL.md").read_text(encoding="utf-8")
    step5 = text[text.index("### Step 5: Calculate TAM/SAM/SOM") : text.index("### Step 5.5")]
    assert "`--redo comparison`" in step5 and "`--suspect <input>`" in step5
    assert "Never print that build's plain\nprompt again" in step5
    usage = subprocess.run([sys.executable, str(GEN), "--help"], capture_output=True, text=True).stdout
    assert "--redo {comparison}" in usage and "--suspect" in usage
    for line in ("- **Exit 3**", "- **Producer schema rejection**"):
        row = next(ln for ln in text.splitlines() if ln.startswith(line))
        assert "a sizing build: a redo keeps `--redo comparison`" in row


# --- T3: the printed redo -----------------------------------------------------------------------------


def test_a_flagged_run_prints_the_prompt_plus_the_redo_block(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    plain = _gen(a, h).stdout
    r = _redo(a, h, "top_down_methodology", "--suspect", "segment_pct", "--suspect", "industry_total")
    assert r.returncode == 0, r.stderr
    text = r.stdout
    assert text.endswith(gen._END)
    head, _, rest = text.partition(gen.REDO_LEAD)
    assert head == plain[: -len(gen._END)], "the redo must be the plain prompt with one block added"
    block = gen.REDO_LEAD + rest[: -len(gen._END)]
    assert "TAM, SAM and SOM differ by more than 30%" in block
    assert "Check these inputs first: industry_total, segment_pct." in block
    assert "Open only inputs.json and validation.json" in block
    for line in block.splitlines():
        assert not line.startswith("CONTEXT:") and line.strip() != gen._END.strip()
    figures = {str(v) for k, v in _COMPARISON.items() if isinstance(v, (int, float))}
    for v in list(figures):
        n = float(v)
        figures |= {f"{n:,.0f}", f"{n:.1f}", f"{n / 1e9:.1f}", f"{n / 1e6:.1f}", f"{n / 1e6:.0f}"}
    numbers = set(re.findall(r"\d[\d,.]*", block)) - {"30"}
    assert not numbers & figures, numbers & figures
    # No direction: which build is higher is an anchor. "more than 30%" is the threshold, not a direction.
    for word in ("higher", "lower", "larger", "smaller", "above", "below", "exceed", "too big", "too small", "shrink"):
        assert word not in block.lower(), word


def test_the_block_names_only_the_levels_flagged(tmp_path: Path) -> None:
    comparison = {**_COMPARISON}
    del comparison["sam_warning"], comparison["warning"]
    a, h = _run_dir(tmp_path, comparison=comparison)
    r = _redo(a, h, "bottom_up_methodology")
    assert r.returncode == 0, r.stderr
    assert "two builds' SOM differ by more than 30%" in r.stdout
    assert "Check these inputs first" not in r.stdout


# --- T4: the record ------------------------------------------------------------------------------------


def test_the_record_is_written_once_and_a_reprint_is_byte_identical(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    first = _redo(a, h, "top_down_methodology", "--suspect", "industry_total")
    record = json.loads((a / sr.RECORD_NAME).read_text())
    assert record["run_id"] == RUN and record["build"] == "top_down"
    assert record["flagged"] == ["tam", "sam", "som"] and record["suspect"] == ["industry_total"]
    assert record["first_input_refs"] == {k: v for k, v in _TD.items() if k != "approach"}
    assert record["before"]["tam"]["delta_pct"] == 199.5
    assert record["output_path"] == f"{AGENT}/handoff/{RUN}/top_down_output.json"
    assert sorted(record["research_at_redo_print"]) == sorted(x["name"] for x in _VALIDATION["assumptions"])
    # The research changes; the reprint is rebuilt from the record, not from the sizing.
    _write(a / "sizing.json", {**json.loads((a / "sizing.json").read_text()), "comparison": {"tam_delta_pct": 1}})
    again = _redo(a, h, "top_down_methodology", "--suspect", "industry_total")
    assert again.returncode == 0 and again.stdout == first.stdout
    assert json.loads((a / sr.RECORD_NAME).read_text()) == record


def test_a_reprint_with_another_suspect_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h, "top_down_methodology", "--suspect", "industry_total").returncode == 0
    _refused(_redo(a, h, "top_down_methodology", "--suspect", "share_pct"), "SIZING_REDO_SUSPECT_CHANGED")


def test_once_its_hand_off_is_gated_after_the_print_the_redo_is_spent(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, {**_TD, "segment_pct": {"assumption": "reachable_share"}})
    _refused(_redo(a, h), "SIZING_REDO_SPENT")


def test_a_transport_correction_of_a_consumed_redo_is_still_printed(tmp_path: Path) -> None:
    """T5 shape: the producer rejected the redo's hand-off, which was gated, so the redo is consumed; the
    corrective print carries both blocks, the redo's first, and the closing line stays last."""
    a, h = _run_dir(tmp_path)
    redo = _redo(a, h).stdout
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    detail = tmp_path / "producer_rejected.txt"
    detail.write_text("E_UNIT_MISMATCH: share_pct: the figure measures something else\n", encoding="utf-8")
    r = _redo(a, h, "top_down_methodology", "--correction", "producer-rejected", "--detail-file", str(detail))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith(redo[: -len(gen._END)])
    assert r.stdout.index(gen.REDO_LEAD) < r.stdout.index(gen.REJECTION_LEAD)
    assert r.stdout.endswith(gen._END)


def test_the_other_build_is_spent_once_one_redo_is_printed(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h, "top_down_methodology").returncode == 0
    _refused(_redo(a, h, "bottom_up_methodology"), "SIZING_REDO_SPENT")


def test_a_redo_the_sizing_used_is_spent_even_with_a_correction(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h).returncode == 0
    record = json.loads((a / sr.RECORD_NAME).read_text())
    _write(a / sr.RECORD_NAME, {**record, "after": {"gaps": {}, "input_refs": {}, "at": "x"}})
    _refused(_redo(a, h, "top_down_methodology", "--correction", "missing-file"), "SIZING_REDO_SPENT")


def test_another_runs_record_is_not_this_runs(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    _write(a / sr.RECORD_NAME, {"run_id": "an-older-run", "build": "bottom_up", "after": None})
    assert _redo(a, h).returncode == 0
    assert json.loads((a / sr.RECORD_NAME).read_text())["run_id"] == RUN


# --- T6: the plain prompt is refused while the redo is pending ------------------------------------------


def test_a_plain_print_while_the_redo_is_pending_is_refused(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _gen(a, h).returncode == 0
    assert _redo(a, h).returncode == 0
    _refused(_gen(a, h), "SIZING_REDO_PENDING")
    _refused(_gen(a, h, "top_down_methodology", "--correction", "missing-file"), "SIZING_REDO_PENDING")
    # The other build's plain prompt, and a later round's hand-off dir, are not this redo's.
    assert _gen(a, h, "bottom_up_methodology").returncode == 0
    r2 = h / "r2"
    r2.mkdir()
    assert _gen(a, r2).returncode == 0


def test_once_the_sizing_used_the_redo_the_plain_prompt_prints_again(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h).returncode == 0
    record = json.loads((a / sr.RECORD_NAME).read_text())
    _write(a / sr.RECORD_NAME, {**record, "after": {"gaps": {}, "input_refs": {}, "at": "x"}})
    assert _gen(a, h).returncode == 0


# --- the one predicate -------------------------------------------------------------------------------


def _record_after_print(a: Path, h: Path) -> dict[str, Any]:
    assert _redo(a, h).returncode == 0
    rec: dict[str, Any] = json.loads((a / sr.RECORD_NAME).read_text())
    return rec


def test_consumed_needs_the_gate_after_the_print(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    rec = _record_after_print(a, h)
    assert not sr.consumed(rec), "the first build's gate predates the print"
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    assert sr.consumed(rec)


def test_the_same_references_written_again_but_not_gated_is_not_consumed(tmp_path: Path) -> None:
    """Writing "the same references again" is an allowed outcome: the rewritten file has the first one's sha, so the
    sha says nothing, and its mtime is after the print. Only the gate's own time shows it was not checked."""
    a, h = _run_dir(tmp_path)
    rec = _record_after_print(a, h)
    time.sleep(0.01)
    _write(h / "top_down_output.json", _TD)  # rewritten, byte-identical, never gated
    assert not sr.consumed(rec)
    _gate(h / "top_down_output.json")
    assert sr.consumed(rec)


def test_a_re_gate_of_the_untouched_first_file_is_not_consumed(tmp_path: Path) -> None:
    """check_handoff.py rewrites the gate record on every pass: the mtime conjunct is what sees this."""
    a, h = _run_dir(tmp_path)
    old = time.time() - 3600
    os.utime(h / "top_down_output.json", (old, old))
    rec = _record_after_print(a, h)
    time.sleep(0.01)
    _gate(h / "top_down_output.json")
    assert not sr.consumed(rec)


def test_a_file_changed_after_its_gate_is_not_consumed(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    rec = _record_after_print(a, h)
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    (h / "top_down_output.json").write_text(json.dumps(_TD), encoding="utf-8")
    assert not sr.consumed(rec)


def test_a_gate_record_with_no_time_is_not_consumed(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    rec = _record_after_print(a, h)
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    gate = h / "top_down_output.json.gate.json"
    _write(gate, {k: v for k, v in json.loads(gate.read_text()).items() if k != "gated_at"})
    assert not sr.consumed(rec)


def test_check_handoff_records_when_it_gated(tmp_path: Path) -> None:
    f = tmp_path / "x_output.json"
    f.write_text("{}", encoding="utf-8")
    before = time.time()
    _gate(f)
    gated = json.loads((tmp_path / "x_output.json.gate.json").read_text())["gated_at"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", gated)
    assert sr._epoch(gated) >= before - 0.001


# --- market_sizing.py fills `after` once ---------------------------------------------------------------


def _pipe(a: Path, h: Path, *, replay: bool = False) -> subprocess.CompletedProcess[str]:
    base = [
        sys.executable,
        str(MS),
        "--pretty",
        "--run-id",
        RUN,
        "--validation",
        str(a / "validation.json"),
        "--inputs",
        str(a / "inputs.json"),
        "-o",
        str(a / "sizing.json"),
    ]
    if replay:
        return subprocess.run([*base, "--replay", str(a / "sizing.json")], capture_output=True, text=True)
    merged = {
        **json.loads((h / "top_down_output.json").read_text()),
        **json.loads((h / "bottom_up_output.json").read_text()),
        "approach": "both",
    }
    return subprocess.run([*base, "--stdin"], input=json.dumps(merged), capture_output=True, text=True)


def _real_run(tmp_path: Path) -> tuple[Path, Path]:
    a, h = _run_dir(tmp_path)
    _write(a / "inputs.json", {"company_name": "Quillfern", "metadata": {"run_id": RUN}})
    r = _pipe(a, h)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sr.flagged_levels(json.loads((a / "sizing.json").read_text())["comparison"])
    return a, h


def test_the_sizing_over_a_consumed_redo_records_after_once(tmp_path: Path) -> None:
    a, h = _real_run(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(
        h,
        {
            **_TD,
            "industry_total": {
                "derived": {
                    "op": "multiply",
                    "factors": [{"assumption": "pear_growers"}, {"assumption": "sensor_price"}],
                }
            },
        },
    )
    assert _pipe(a, h).returncode == 0
    rec = json.loads((a / sr.RECORD_NAME).read_text())
    after = rec["after"]
    redone_total = after["input_refs"]["industry_total"]
    assert redone_total["derived"]["op"] == "multiply"
    assert (
        after["gaps"]["tam"]["delta_pct"] == json.loads((a / "sizing.json").read_text())["comparison"]["tam_delta_pct"]
    )
    assert sr.outcome(rec) == "changed"
    # A later replay (Step 6d) cannot move it.
    _write(
        a / "validation.json",
        {
            **_VALIDATION,
            "assumptions": [
                {**x, "value": 9000} if x["name"] == "pear_growers" else x for x in _VALIDATION["assumptions"]
            ],
        },
    )
    assert _pipe(a, h, replay=True).returncode == 0
    assert json.loads((a / sr.RECORD_NAME).read_text())["after"] == after


def test_a_sizing_before_the_redo_hand_off_is_gated_records_nothing(tmp_path: Path) -> None:
    a, h = _real_run(tmp_path)
    assert _redo(a, h).returncode == 0
    assert _pipe(a, h).returncode == 0
    rec = json.loads((a / sr.RECORD_NAME).read_text())
    assert rec["after"] is None and sr.outcome(rec) == "not_run"


def test_a_sizing_that_did_not_use_the_redo_records_nothing(tmp_path: Path) -> None:
    a, h = _real_run(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    # The pipe is fed the FIRST build's references, not the gated redo's.
    first = dict(_TD)
    merged = {**first, **_BU, "approach": "both"}
    base = [
        sys.executable,
        str(MS),
        "--stdin",
        "--run-id",
        RUN,
        "--validation",
        str(a / "validation.json"),
        "--inputs",
        str(a / "inputs.json"),
        "-o",
        str(a / "sizing.json"),
    ]
    assert subprocess.run(base, input=json.dumps(merged), capture_output=True, text=True).returncode == 0
    assert json.loads((a / sr.RECORD_NAME).read_text())["after"] is None


def test_the_same_references_again_is_its_own_outcome(tmp_path: Path) -> None:
    a, h = _real_run(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, dict(_TD))
    assert _pipe(a, h).returncode == 0
    assert sr.outcome(json.loads((a / sr.RECORD_NAME).read_text())) == "same_inputs"


def test_research_recorded_after_the_first_print_is_named(tmp_path: Path) -> None:
    a, h = _run_dir(tmp_path)
    assert _gen(a, h).returncode == 0  # the first plain print notes the research
    snap = json.loads((h / sr.SNAPSHOT_NAME).read_text())
    assert snap["run_id"] == RUN and "pear_growers" in snap["entries"]
    r = _pipe(a, h)
    assert r.returncode == 0, r.stdout + r.stderr
    extra = {
        "name": "pear_belt_total",
        "value": 410_000_000,
        "unit": "money_total_per_year",
        "currency": "USD",
        "category": "sourced",
        "label": "Pear-belt sensor spend",
    }
    _write(a / "validation.json", {**_VALIDATION, "assumptions": [*_VALIDATION["assumptions"], extra]})
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, {**_TD, "industry_total": {"assumption": "pear_belt_total"}})
    assert _pipe(a, h).returncode == 0
    rec = json.loads((a / sr.RECORD_NAME).read_text())
    assert sr.research_since(rec) == (["pear_belt_total"], [])
    assert json.loads((h / sr.SNAPSHOT_NAME).read_text()) == snap, "the first snapshot is kept"


def test_research_edited_after_the_first_print_is_named_even_with_the_same_inputs(tmp_path: Path) -> None:
    """An entry's value edited after both builds were seen moves the gap with the references unchanged: the
    record says the research changed, and the founder's sentence says so beside "the same inputs again"."""
    a, h = _run_dir(tmp_path)
    assert _gen(a, h).returncode == 0
    assert _pipe(a, h).returncode == 0
    edited = [
        {**x, "value": 2_100_000_000} if x["name"] == "orchard_sensor_total" else x for x in _VALIDATION["assumptions"]
    ]
    relabelled = [{**x, "label": "Spend on orchard sensors"} if x["name"] == "pear_belt_share" else x for x in edited]
    _write(a / "validation.json", {**_VALIDATION, "assumptions": relabelled})
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, dict(_TD))
    assert _pipe(a, h).returncode == 0
    rec = json.loads((a / sr.RECORD_NAME).read_text())
    assert sr.outcome(rec) == "same_inputs"
    assert sr.research_since(rec) == ([], ["orchard_sensor_total"]), "a label is how an entry is shown, not data"
    view = _load("_view_redo_t", SCRIPTS / "_view.py")
    sentence = view.redo_sentence(rec, {**_VALIDATION, "assumptions": relabelled})
    assert "it chose the same inputs again" in sentence
    assert "Research the sizing uses was changed after the two builds were first made: Orchard sensor spend" in sentence


def test_the_outcome_is_settled_once_the_sizing_used_the_redo(tmp_path: Path) -> None:
    """Step 6d's sizing re-dispatch runs before HANDOFF_DIR points at r2/, so it rewrites round 1's hand-off.
    That must not turn a redo that ran into "not run"."""
    a, h = _real_run(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    assert _pipe(a, h).returncode == 0
    rec = json.loads((a / sr.RECORD_NAME).read_text())
    assert sr.outcome(rec) == "changed"
    _rewrite_handoff(h, {**_TD, "segment_pct": {"assumption": "served_share"}})  # the 6d re-dispatch, gated
    assert sr.outcome(rec) == "changed"
    (h / "top_down_output.json").write_text(json.dumps(_TD), encoding="utf-8")  # and not gated
    assert sr.outcome(rec) == "changed"


@pytest.mark.parametrize("correction", ["missing-file", "receipt-only"])
def test_only_a_producers_rejection_reprints_a_consumed_redo(tmp_path: Path, correction: str) -> None:
    a, h = _run_dir(tmp_path)
    assert _redo(a, h).returncode == 0
    _rewrite_handoff(h, {**_TD, "share_pct": {"assumption": "pear_belt_share"}})
    _refused(_redo(a, h, "top_down_methodology", "--correction", correction), "SIZING_REDO_SPENT")


def test_past_the_sizing_an_unused_redo_no_longer_blocks_the_plain_prompt(tmp_path: Path) -> None:
    """Step 6d: a new redo is TOO_LATE, so the plain prompt must print, or the run could not re-dispatch."""
    a, h = _run_dir(tmp_path)
    assert _redo(a, h).returncode == 0
    _refused(_gen(a, h), "SIZING_REDO_PENDING")
    _write(a / "redteam.json", {"metadata": {"run_id": RUN}})
    assert _gen(a, h).returncode == 0
    _refused(_redo(a, h), "SIZING_REDO_TOO_LATE")


# --- compose and the page: the sentence, the warning, report.json ----------------------------------------

FIXTURE = PLUGIN / "tests" / "fixtures" / "market-sizing"
FIXTURE_RUN = "fixture-market-sizing-001"
COMPOSE = SCRIPTS / "compose_report.py"
VISUALIZE = SCRIPTS / "visualize.py"


def _compose_dir(tmp_path: Path) -> Path:
    """The compose fixture as a "both" run with a flagged comparison."""
    d = tmp_path / "market-sizing-quillfern"
    d.mkdir(parents=True)
    for f in FIXTURE.glob("*.json"):
        (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    sizing = json.loads((d / "sizing.json").read_text())
    sizing["approach"] = "both"
    sizing["top_down"] = json.loads(json.dumps(sizing["bottom_up"]))
    for level in ("tam", "sam", "som"):
        sizing["top_down"][level]["value"] = sizing["top_down"][level]["raw_value"] = (
            sizing["bottom_up"][level]["value"] * 5
        )
    sizing["comparison"] = {
        "top_down_tam": sizing["top_down"]["tam"]["value"],
        "bottom_up_tam": sizing["bottom_up"]["tam"]["value"],
        "tam_delta_pct": 133.3,
        "warning": "Top-down and bottom-up TAM differ by a factor of 5.0 (top-down is higher). Review assumptions.",
    }
    _write(d / "sizing.json", sizing)
    return d


def _seed_record(d: Path, *, consumed: bool, after: bool, run_id: str = FIXTURE_RUN) -> dict[str, Any]:
    hand = d / "handoff" / run_id
    first = dict(_TD)
    redo = {**_TD, "industry_total": {"assumption": "pear_belt_total"}}
    _write(hand / "top_down_output.json", first)
    printed_at, printed = sr.now()
    if consumed:
        time.sleep(0.01)
        _write(hand / "top_down_output.json", redo)
        _gate(hand / "top_down_output.json")
    else:
        old = printed - 60
        os.utime(hand / "top_down_output.json", (old, old))
        _gate(hand / "top_down_output.json")  # a re-gate of the untouched first file
    names = sr.BUILDS["top_down_methodology"][2]
    record: dict[str, Any] = {
        "run_id": run_id,
        "build": "top_down",
        "context": "top_down_methodology",
        "printed_at": printed_at,
        "flagged": ["tam"],
        "suspect": ["industry_total"],
        "before": {"tam": {"delta_pct": 133.3, "top_down": 40_500_000_000, "bottom_up": 8_100_000_000}},
        "handoff_dir": str(hand),
        "handoff_file": str(hand / "top_down_output.json"),
        "output_path": "/agent/x/top_down_output.json",
        "first_handoff_sha256": None,
        "first_input_refs": {n: first[n] for n in names},
        "research_at_first_print": {"orchard_sensor_total": "1", "pear_belt_share": "2", "reachable_share": "3"},
        "research_at_redo_print": {"orchard_sensor_total": "1", "pear_belt_total": "4"},
        "text_sha256": "x",
        "after": None,
    }
    if after:
        record["after"] = {
            "gaps": {"tam": {"delta_pct": 21.0, "top_down": 9_500_000_000, "bottom_up": 8_100_000_000}},
            "input_refs": {n: redo[n] for n in names},
            "at": printed_at,
            "research_added": ["pear_belt_total"],
            "research_changed": [],
        }
    _write(d / sr.RECORD_NAME, record)
    return record


def _compose(d: Path) -> dict[str, Any]:
    r = subprocess.run(
        [
            sys.executable,
            str(COMPOSE),
            "--dir",
            str(d),
            "-o",
            str(d / "report.json"),
            "--write-md",
            str(d / "report.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    out: dict[str, Any] = json.loads((d / "report.json").read_text())
    return out


def _html(d: Path) -> str:
    r = subprocess.run([sys.executable, str(VISUALIZE), "--dir", str(d)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _codes(report: dict[str, Any]) -> dict[str, str]:
    return {w["code"]: w["severity"] for w in report["validation"]["warnings"]}


def test_a_redo_the_sizing_used_is_told_in_both_surfaces(tmp_path: Path) -> None:
    """C1: consumed, changed references: the sentence, with the gap before and after and the input named the
    way the founder reads it, in report.md and report.html; no warning; report.json says `changed`."""
    d = _compose_dir(tmp_path)
    _seed_record(d, consumed=True, after=True)
    report = _compose(d)
    md = (d / "report.md").read_text()
    sentence = "The top-down build was done a second time because the two builds' TAM differed by more than 30%"
    assert sentence in md
    assert "it changed its Industry Total" in md and "industry_total" not in md
    assert "differed by a factor of 5.0 before the redo and by a factor of 1.2 after it" in md
    assert "The sizing now uses research recorded after the two builds were first made: Pear Belt Total." in md
    assert "SIZING_REDO_NOT_RUN" not in _codes(report)
    assert report["sizing_redo"] == {"build": "top_down", "flagged": ["tam"], "outcome": "changed"}
    page = html.unescape(_html(d))
    assert sentence in page
    # The sentence through the fleet's founder-text scan, as each surface renders it (the HTML ratchet's
    # fixture has no redo, so it would pass with a leak here).
    ft = _load("_founder_text_redo", PLUGIN / "scripts" / "_founder_text.py")
    for text in (md, page):
        start = text.index(sentence)
        end = text.index("\n", start) if "\n" in text[start:] else len(text)
        found = ft.scan(re.sub(r"<[^>]+>", " ", text[start:end]))
        assert found["enums"] == [] and found["filenames"] == [], found


def test_a_redo_never_used_is_disclosed_and_cannot_be_accepted(tmp_path: Path) -> None:
    """C2: printed, its first file re-gated but never rewritten: SIZING_REDO_NOT_RUN, medium, not acceptable."""
    d = _compose_dir(tmp_path)
    _seed_record(d, consumed=False, after=False)
    meth = json.loads((d / "methodology.json").read_text())
    meth["accepted_warnings"] = [{"code": "SIZING_REDO_NOT_RUN", "match": "second", "reason": "fine"}]
    _write(d / "methodology.json", meth)
    report = _compose(d)
    assert _codes(report)["SIZING_REDO_NOT_RUN"] == "medium"
    assert report["sizing_redo"]["outcome"] == "not_run"
    assert "The top-down build was done a second time" not in (d / "report.md").read_text()
    assert "A Build Ordered Redone Was Not Redone" in (d / "report.md").read_text()


def test_another_runs_record_is_ignored_by_compose(tmp_path: Path) -> None:
    """C3."""
    d = _compose_dir(tmp_path)
    _seed_record(d, consumed=False, after=False, run_id="an-older-run")
    report = _compose(d)
    assert "sizing_redo" not in report and "SIZING_REDO_NOT_RUN" not in _codes(report)


def _payload(d: Path) -> dict[str, Any]:
    payload: dict[str, Any] = _compose(d)["coaching_payload"]
    payload.pop("insertion_marker")
    return payload


@pytest.mark.parametrize(("consumed", "after"), [(True, True), (False, False)])
def test_the_coaching_payload_is_the_same_with_or_without_a_redo(tmp_path: Path, consumed: bool, after: bool) -> None:
    """C4: the redo reaches the founder through the report only. The payload's warning list is filtered to
    high, and a high warning is present here, so the filter is shown engaged, not vacuous."""
    plain = _compose_dir(tmp_path / "a")
    redone = _compose_dir(tmp_path / "b")
    _seed_record(redone, consumed=consumed, after=after)
    without, with_ = _payload(plain), _payload(redone)
    assert with_["high_severity_warnings"], "no high warning: the filter this test relies on is not engaged"
    for p in (without, with_):
        p["review_dir"] = p["report_path"] = None
    assert with_ == without
    if not consumed:
        assert "SIZING_REDO_NOT_RUN" in _codes(json.loads((redone / "report.json").read_text()))


# --- with a gate ledger: the record survives the file (M5) ---------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as grh  # noqa: E402


def _ledger_run(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    root, run_id, run_dir = grh.start_bound(tmp_path, "market-sizing", slug="quillfern")
    hand = run_dir / "handoff" / run_id
    _write(run_dir / "inputs.json", {"company_name": "Quillfern", "metadata": {"run_id": run_id}})
    _write(run_dir / "methodology.json", {"approach_chosen": "both", "metadata": {"run_id": run_id}})
    _write(run_dir / "validation.json", {**_VALIDATION, "metadata": {"run_id": run_id}})
    sizing = {"approach": "both", "top_down": {}, "bottom_up": {}, "comparison": _COMPARISON}
    _write(run_dir / "sizing.json", {**sizing, "metadata": {"run_id": run_id}})
    _write(hand / "top_down_output.json", _TD)
    _gate(hand / "top_down_output.json")
    for args in (
        ("open", "--gate", "ms_methodology"),
        ("answer", "--gate", "ms_methodology", "--answer-id", "looks_good"),
    ):
        r = grh.record(root, run_id, *args)
        assert r.returncode == 0, r.stdout + r.stderr
    return root, run_id, run_dir, hand


def _lgen(run_dir: Path, run_id: str, hand: Path, context: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return grh.run(
        GEN,
        context,
        "--run-id",
        run_id,
        "--analysis-dir",
        str(run_dir),
        "--handoff-dir",
        str(hand),
        "--handoff-agent",
        str(hand),
        *extra,
    )


def test_with_a_ledger_the_record_is_in_the_ledger_and_survives_the_files_deletion(tmp_path: Path) -> None:
    root, run_id, run_dir, hand = _ledger_run(tmp_path)
    first = _lgen(run_dir, run_id, hand, "top_down_methodology", "--redo", "comparison")
    assert first.returncode == 0, first.stdout + first.stderr
    held = grh.ledger(root, run_id)[sr.LEDGER_KEY]
    assert held == json.loads((run_dir / sr.RECORD_NAME).read_text())
    (run_dir / sr.RECORD_NAME).unlink()
    # The budget is not reopened, the reprint is still the same text, and the plain prompt still waits.
    _refused(_lgen(run_dir, run_id, hand, "bottom_up_methodology", "--redo", "comparison"), "SIZING_REDO_SPENT")
    _refused(_lgen(run_dir, run_id, hand, "top_down_methodology"), "SIZING_REDO_PENDING")
    again = _lgen(run_dir, run_id, hand, "top_down_methodology", "--redo", "comparison")
    assert again.stdout == first.stdout
    assert sr.load(str(run_dir), run_id) == held


def test_an_unreachable_ledger_is_refused_never_read_around(tmp_path: Path) -> None:
    """With a ref and a ledger it cannot reach, the record is not read from the file: the reader refuses with
    the shared failure JSON, exit 2, and no traceback."""
    root, run_id, run_dir, hand = _ledger_run(tmp_path)
    assert _lgen(run_dir, run_id, hand, "top_down_methodology", "--redo", "comparison").returncode == 0
    grh.ledger_path(root, run_id).unlink()
    with pytest.raises(sr._run_ref.LedgerUnavailable):
        sr.load(str(run_dir), run_id)
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import _view; print(_view.redo_record(sys.argv[2], sys.argv[3]))"
    )
    r = subprocess.run(
        [sys.executable, "-c", probe, str(SCRIPTS), str(run_dir), run_id], capture_output=True, text=True
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["status"] == "error"


def test_a_finished_run_refuses_a_redo(tmp_path: Path) -> None:
    root, run_id, run_dir, hand = _ledger_run(tmp_path)
    st = grh.status(root, run_id)
    grh.status_path(root, run_id).write_text(json.dumps({**st, "status": "complete"}), encoding="utf-8")
    r = _lgen(run_dir, run_id, hand, "top_down_methodology", "--redo", "comparison")
    assert r.returncode == 1 and "CONTEXT:" not in r.stdout
    assert json.loads(r.stdout)["code"] == "RUN_FINISHED"
    assert sr.LEDGER_KEY not in grh.ledger(root, run_id)
