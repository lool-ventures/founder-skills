"""Percent-type figures read as percents on every page a financial model review produces.

Gross margin, NRR and GRR are stored as fractions (0.75, 1.05, 0.9). Net retention above 100% is
normal for a growing SaaS book, so a formatter that scales only values at or below 1.0 printed an NRR
of 1.05 as "1%" in report.html; report.md printed it as a bare "1.05" and the explorer as "1.1x".
Invented figures.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_financial_model_review import (  # noqa: E402
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_RUNWAY,
    _make_fmr_artifact_dir,
    _run_compose,
    run_script,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "financial-model-review" / "scripts"

# The three figures, and the percent each must read as.
_EXPECTED = {"nrr": "105%", "grr": "90%", "gross_margin": "75%"}


def _inputs() -> dict[str, Any]:
    inputs = copy.deepcopy(_VALID_INPUTS)
    inputs["revenue"]["nrr"] = 1.05
    inputs["revenue"]["grr"] = 0.9
    inputs["unit_economics"]["gross_margin"] = 0.75
    return inputs


def _artifact_dir() -> str:
    inputs = _inputs()
    rc, ue, err = run_script("unit_economics.py", [], stdin_data=json.dumps(inputs))
    assert rc == 0 and ue is not None, err
    values = {m["name"]: m.get("value") for m in ue["metrics"]}
    # The producer stores fractions; the fix is in how the pages print them.
    assert values["nrr"] == 1.05 and values["grr"] == 0.9 and values["gross_margin"] == 0.75, values
    return _make_fmr_artifact_dir(
        {
            "inputs.json": inputs,
            "checklist.json": _VALID_CHECKLIST,
            "unit_economics.json": ue,
            "runway.json": _VALID_RUNWAY,
        }
    )


def _run(script: str, d: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--dir", d], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_report_md_prints_each_retention_and_margin_figure_as_a_percent() -> None:
    rc, data, err = _run_compose(_artifact_dir())
    assert rc == 0 and data is not None, err
    md = data["report_markdown"]
    for name, expected in _EXPECTED.items():
        label = name.upper().replace("_", " ")
        row = re.search(rf"^\| {label} \| ([^|]+) \|", md, re.M)
        assert row is not None, (label, md[:2000])
        assert row.group(1).strip() == expected, (label, row.group(0))


def test_report_html_prints_each_retention_and_margin_figure_as_a_percent() -> None:
    html = _run("visualize.py", _artifact_dir())
    labels = {"nrr": "Net Revenue Retention", "grr": "Gross Revenue Retention", "gross_margin": "Gross Margin"}
    for name, expected in _EXPECTED.items():
        # Each bullet-chart row: the label, the bar, then "<figure> — <rating>".
        row = re.search(rf">{labels[name]}</span>.*?<span[^>]*>([^<]*?) — ", html, re.S)
        assert row is not None, labels[name]
        assert row.group(1) == expected, (name, row.group(1))


def test_the_percent_formatter_scales_every_fraction() -> None:
    """Direct: the same three figures, plus a negative margin and a zero, through report.html's formatter."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fmr_visualize_pct", SCRIPTS / "visualize.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    fmt = mod._format_metric_value
    assert fmt("nrr", 1.05) == "105%"
    assert fmt("grr", 0.9) == "90%"
    assert fmt("gross_margin", 0.75) == "75%"
    assert fmt("gross_margin", -0.2) == "-20%"
    assert fmt("nrr", 2.5) == "250%"
    assert fmt("grr", 0.0) == "0%"


def _grab(source: str, start_token: str) -> str:
    start = source.index(start_token)
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


def test_explorer_prints_each_retention_and_margin_figure_as_a_percent() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    html = _run("explore.py", _artifact_dir())
    parts = [
        "var CURRENCY = 'USD'; var CUR_PREFIX = '$'; var CUR_SUFFIX = '';",
        _grab(html, "function fmtCurrency("),
        _grab(html, "function fmtPct("),
        _grab(html, "function fmtRatio("),
        _grab(html, "function fmtMonths("),
        _grab(html, "var metricFmt = ") + ";",
        "console.log(JSON.stringify({nrr: metricFmt.nrr(1.05), grr: metricFmt.grr(0.9),"
        " gross_margin: metricFmt.gross_margin(0.75)}));",
    ]
    res = subprocess.run([node, "-e", "\n".join(parts)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == _EXPECTED
