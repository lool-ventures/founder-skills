"""Unit tests for concise_report.py — the lightweight math-answer renderer.

Asserts it renders the deterministic solver's numbers (the same fields the full
pipeline reads) without requiring the heavy-tail artifacts, and that it does not
fabricate a post-financing table for cap-implied-only / blocked scenarios.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "cap-table" / "scripts" / "concise_report.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("concise_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CR = _load()

INPUTS = {"company_name": "BenchCo"}

FULL_SCENARIO = {
    "scenarios": [
        {
            "label": "Series A",
            "computed_outputs": {
                "completeness": "full",
                "equity_financing_price": 0.875,
                "per_safe": [{"id": "safe_disc", "conversion_price": 0.70, "conversion_shares": 1428571}],
                "aggregate_ownership_by_class": {
                    "founders_pct": 0.625,
                    "safe_pct": 0.0893,
                    "new_money_pct": 0.2857,
                    "preferred_pct": 0.0,
                },
                "post_round_fully_diluted_shares": 16000000,
            },
        }
    ]
}


def test_renders_solver_numbers_without_tail_artifacts() -> None:
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None)
    # the deterministic numbers come through verbatim-in-spirit
    assert "$0.8750" in md
    assert "$0.7000" in md
    assert "1,428,571 shares" in md
    assert "62.5%" in md  # founders
    assert "28.6%" in md  # new money
    assert "16,000,000 shares" in md  # FD total
    # it advertises itself as concise and offers the full review
    assert "concise" in md.lower()
    assert "full review" in md.lower()


def test_no_rule_audit_is_fine() -> None:
    # counsel_packet / rule_audit are NOT required for a concise answer
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None)
    assert "## Flags" not in md


def test_rule_audit_flags_and_boundary_render() -> None:
    ra = {
        "counsel_review_items": [{"rule_id": "delaware_cross_border.qsbs_date_sensitive", "title": "QSBS date"}],
        "date_sensitive_watchlist": [{"rule_id": "safe.israeli_2025_safe_harbor"}],
    }
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=ra)
    assert "qsbs_date_sensitive" in md
    assert "israeli_2025_safe_harbor" in md
    # reliance boundary appears when counsel items are present
    assert "defer eligibility" in md.lower()


def test_cap_implied_only_does_not_fabricate_post_financing() -> None:
    """Driven from the REAL producer, not a hand-built dict.

    The previous version of this test asserted a `completeness: "cap_implied_only"` that is not in
    `scenarios.schema.json`'s enum, and a TOP-LEVEL `cap_implied_ownership` no producer emits -- so it
    greened a shape that cannot occur while the real one rendered nothing at all.
    """
    doc = {"scenarios": [{"label": "Standalone SAFE", "computed_outputs": _cap_implied_outputs()}]}
    md = CR.render(INPUTS, doc, rule_audit=None)
    assert "Cap-implied ownership (pre-financing)" in md
    # must NOT invent a founders/new-investor post-financing table
    assert "New investors" not in md
    assert "not a post-financing table" in md


def test_blocked_scenario_surfaces_blocker() -> None:
    doc = {
        "scenarios": [
            {
                "label": "Circular MFN",
                "computed_outputs": {"completeness": "structural_only", "blockers": [{"code": "E_SAFE_CIRCULAR_MFN"}]},
            }
        ]
    }
    md = CR.render(INPUTS, doc, rule_audit=None)
    assert "E_SAFE_CIRCULAR_MFN" in md
    assert "Blocked" in md


def test_concise_render_surfaces_anti_dilution_warning() -> None:
    """Part A: the standalone-anti-dilution scenario routes to concise mode (SKILL.md:187), but
    concise_report never loaded cap_state — so the AD recovery warning was dropped on the dominant
    route. render() must accept cap_state and surface the W_ANTI_DILUTION_* family (interpolated
    sentences) as a founder-facing callout."""
    cap_state = {
        "warnings": [
            "W_ANTI_DILUTION_NONCANONICAL: preferred series 'Series Seed' specified anti-dilution under "
            "the wrong key `anti_dilution`='bbwa' — recovered as 'broad_based_weighted_average'."
        ]
    }
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None, cap_state=cap_state)
    assert "anti-dilution" in md.lower()
    assert "broad_based_weighted_average" in md  # the recovery detail reaches the founder


def test_concise_render_no_cap_state_is_fine() -> None:
    """cap_state is optional — omitting it (or passing None) renders no warning block, no crash."""
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None, cap_state=None)
    assert "anti-dilution" not in md.lower()


def test_concise_render_surfaces_cap_base_assumed() -> None:
    """Issue C: concise mode rendered ONLY the W_ANTI_DILUTION family, silently dropping the other three
    warning families. A standalone quick question routes to concise — so a founder querying on an
    ASSUMED/unconfirmed cap base saw no 'DIRECTIONAL, not founder-confirmed' caveat. render() must surface
    W_CAP_BASE_ASSUMED via the shared renderer (the same wording compose uses)."""
    cap_state = {"warnings": ["W_CAP_BASE_ASSUMED"]}
    md = CR.render(INPUTS, FULL_SCENARIO, rule_audit=None, cap_state=cap_state)
    assert "Cap base ASSUMED" in md
    assert "DIRECTIONAL" in md


# --------------------------------------------------------------------------------------------
# Real producer output. Every assertion about what concise mode renders is driven from
# `run_scenario`, never from a hand-authored `computed_outputs` dict: the defect these tests
# exist for was invisible for exactly as long as the fixtures were invented.
# --------------------------------------------------------------------------------------------

import json  # noqa: E402
import sys  # noqa: E402

_SCRIPTS = REPO / "skills" / "cap-table" / "scripts"
_FIXTURES = REPO / "tests" / "fixtures" / "cap-table"


def _run_scenario_mod() -> types.ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_scenario", _SCRIPTS / "run_scenario.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _main_with_argv(argv: list[str]) -> int:
    """`main()` reads `sys.argv` directly (argparse, no argv parameter)."""
    saved = sys.argv
    sys.argv = ["concise_report.py", *argv]
    try:
        return int(CR.main())
    finally:
        sys.argv = saved


def _fixture(name: str) -> dict:
    loaded = json.loads((_FIXTURES / name).read_text())
    assert isinstance(loaded, dict)
    return loaded


def _cap_implied_outputs(instruments: dict | None = None) -> dict:
    """A real cap-implied SAFE snapshot: no priced params, so `run_safe_conversion_scenario`
    takes the cap-implied arm."""
    rs = _run_scenario_mod()
    out = rs.run_safe_conversion_scenario(
        {"scenario_id": "snap", "label": "Snapshot", "type": "safe_conversion", "parameters": {}},
        instruments=instruments or _fixture("instruments.json"),
        cap_state=_fixture("cap_state.json"),
    )
    assert isinstance(out, dict)
    return out


def test_cap_implied_snapshot_renders_its_numbers() -> None:
    """THE DEFECT: a complete cap-implied answer rendered as a header and a completeness note --
    zero numbers -- because concise had no cap-implied block at all. The producer emits
    `safe_price` / `cap_implied_shares` / `cap_implied_ownership` PER SAFE; concise's only per-SAFE
    loop reads the PRICED keys (`conversion_price` / `conversion_shares`), which the cap-implied arm
    never emits. `compose_report.py` and `visualize.py` both carry a separate cap-implied block; this
    is the third renderer catching up, not a rename of the priced one.
    """
    co = _cap_implied_outputs()
    md = CR.render(INPUTS, {"scenarios": [{"label": "Snapshot", "computed_outputs": co}]}, rule_audit=None)
    fact_lines = [ln for ln in md.splitlines() if ln.startswith("- ") and "completeness" not in ln]
    assert fact_lines, f"cap-implied snapshot rendered no facts:\n{md}"
    assert "Cap-implied ownership (pre-financing)" in md
    sid = co["per_safe"][0]["id"]
    assert sid in md, "the per-SAFE cap-implied row must name its instrument"


def test_priced_arm_still_renders_after_cap_implied_block_added() -> None:
    """Guards the regression the fix could most easily cause. The priced arm's per-SAFE keys
    (`conversion_price` / `conversion_shares`) render correctly today; adding the cap-implied block
    must not disturb that loop."""
    rs = _run_scenario_mod()
    co = rs.run_safe_conversion_scenario(
        {
            "scenario_id": "priced",
            "label": "Priced",
            "type": "safe_conversion",
            "parameters": {"priced_round_pre_money": 12_000_000, "priced_round_new_money": 3_000_000},
        },
        instruments=_fixture("instruments.json"),
        cap_state=_fixture("cap_state.json"),
    )
    md = CR.render(INPUTS, {"scenarios": [{"label": "Priced", "computed_outputs": co}]}, rule_audit=None)
    assert "Price per share" in md
    assert "converts at $" in md
    assert "Founders:" in md


def test_blocked_cap_implied_run_renders_no_ownership_number() -> None:
    """A run blocked INSIDE the cap-implied arm carries `cap_implied_only: True` with an EMPTY
    `per_safe`. Gating the block on the flag alone would print an ownership heading with nothing
    under it on every such refusal.

    An MFN election with no priced round is used because it blocks inside that arm, so the flag is
    still stamped. A notes-present refusal returns BEFORE the arm split and carries no flag at all --
    it cannot exercise this gate, which is why it is not the fixture here.
    """
    rs = _run_scenario_mod()
    co = rs.run_safe_conversion_scenario(
        {
            "scenario_id": "snap",
            "label": "Blocked",
            "type": "safe_conversion",
            "parameters": {"mfn_elections": {"safe_001": "x"}},
        },
        instruments=_fixture("instruments.json"),
        cap_state=_fixture("cap_state.json"),
    )
    assert co.get("cap_implied_only") is True and not co.get("per_safe"), "precondition drifted"
    md = CR.render(INPUTS, {"scenarios": [{"label": "Blocked", "computed_outputs": co}]}, rule_audit=None)
    assert "Cap-implied ownership (pre-financing)" not in md
    assert "Blocked" in md


def test_main_writes_the_cap_implied_answer(tmp_path: Path) -> None:
    """The pre-write gate has never been executed by a test -- every existing test calls `render()`.
    A complete cap-implied answer must be WRITTEN, not refused as empty."""
    co = _cap_implied_outputs()
    scen = tmp_path / "scenarios.json"
    scen.write_text(json.dumps({"scenarios": [{"label": "Snapshot", "computed_outputs": co}]}))
    inp = tmp_path / "inputs.json"
    inp.write_text(json.dumps(INPUTS))
    out = tmp_path / "report_concise.md"
    rc = _main_with_argv(["--scenarios", str(scen), "--inputs", str(inp), "-o", str(out), "--run-id", "r1"])
    assert rc == 0, "a complete cap-implied answer was refused as empty"
    assert out.exists() and "Cap-implied ownership" in out.read_text()


def test_main_refuses_and_leaves_output_untouched_when_truly_empty(tmp_path: Path) -> None:
    """The property the gate exists for, and the one a naive fix would drop: nothing to say means
    exit 2 with `-o` byte-unchanged (not merely absent)."""
    scen = tmp_path / "scenarios.json"
    scen.write_text(json.dumps({"scenarios": []}))
    inp = tmp_path / "inputs.json"
    inp.write_text(json.dumps(INPUTS))
    out = tmp_path / "report_concise.md"
    out.write_text("PRIOR GOOD CONTENT")
    rc = _main_with_argv(["--scenarios", str(scen), "--inputs", str(inp), "-o", str(out), "--run-id", "r1"])
    assert rc == 2
    assert out.read_text() == "PRIOR GOOD CONTENT", "-o was clobbered by a rejected run"
