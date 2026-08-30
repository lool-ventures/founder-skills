"""Every founder-facing surface must show the SOLVER's warnings, not just `report.md`.

`priced_round` computes warnings onto `computed_outputs.warnings` -- among them
`W_MFN_NOT_MOST_FAVORABLE`, the counterfactual `agents/cap-table.md` requires the report to LABEL as
such rather than present as the holder's entitlement. Until this file existed, exactly one renderer
read them (`compose_report`), and `render_solver_warning_callouts` itself had no test at all while
already shipping into `report.md`.

The other surfaces each render `cap_state`'s warning STRINGS and stop there. They are a different
channel: strings vs dicts, cap-state vs solver. Rendering one is not rendering the other, which is
why every one of them read as "warnings are handled here".
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "cap-table" / "scripts"


def _load(name: str) -> types.ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WC = _load("_warning_callouts")

# A solver warning as `priced_round` emits it: a DICT with a code and a subject, never a bare string.
MFN_WARNING = {
    "code": "W_MFN_NOT_MOST_FAVORABLE",
    "instance_id": "safe_003_mfn",
    "detail": "elected terms are not the most favorable available",
}
SCENARIOS = [
    {
        "scenario_id": "s1",
        "type": "priced_round",
        "label": "Series A",
        "computed_outputs": {"completeness": "full", "warnings": [MFN_WARNING], "blockers": []},
    }
]

_FIXTURES = REPO / "tests" / "fixtures" / "cap-table"


def _fx(name: str) -> dict:
    import json

    loaded = json.loads((_FIXTURES / name).read_text())
    assert isinstance(loaded, dict)
    return loaded


def _render_visualize() -> str:
    viz = _load("visualize")
    return str(
        viz.render_report_html(
            inputs=_fx("inputs.json"),
            cap_state=_fx("cap_state.json"),
            scenarios_doc={"scenarios": SCENARIOS},
            rule_audit=_fx("rule_audit.json"),
            counsel_packet=_fx("counsel_packet.json"),
        )
    )


def _render_explore() -> str:
    exp = _load("explore")
    return str(
        exp.render_explorer_html(
            inputs=_fx("inputs.json"),
            cap_state=_fx("cap_state.json"),
            scenarios_doc={"scenarios": SCENARIOS},
            counsel_packet=_fx("counsel_packet.json"),
        )
    )


class TestRendererItself:
    """`render_solver_warning_callouts` ships in `report.md` and had zero tests."""

    def test_renders_the_counterfactual_label(self) -> None:
        out = "\n".join(WC.render_solver_warning_callouts([MFN_WARNING]))
        assert "counterfactual" in out.lower()
        assert "safe_003_mfn" in out, "the callout must name the instrument it is about"

    def test_unknown_code_is_not_swallowed(self) -> None:
        out = "\n".join(WC.render_solver_warning_callouts([{"code": "W_SOMETHING_NEW", "detail": "d"}]))
        assert out.strip(), "an unrecognised W_ code must still reach the founder, not vanish"

    def test_non_dict_and_non_warning_entries_are_skipped(self) -> None:
        mixed = ["a bare string", {"code": "E_NOT_A_WARNING"}, MFN_WARNING]
        out = "\n".join(WC.render_solver_warning_callouts(mixed))
        assert "counterfactual" in out.lower()
        assert "E_NOT_A_WARNING" not in out

    def test_same_warning_about_same_subject_renders_once(self) -> None:
        out = WC.render_solver_warning_callouts([MFN_WARNING, dict(MFN_WARNING)])
        assert sum(1 for line in out if "counterfactual" in line.lower()) == 1


class TestCollectionIsShared:
    """The scenarios -> warnings walk must live in ONE place. It was inline in `compose_report`, so
    every other surface would have had to reimplement it to use it."""

    def test_collect_helper_exists_and_walks_scenarios(self) -> None:
        assert hasattr(WC, "collect_solver_warnings"), "collection must be shared, not per-renderer"
        assert WC.collect_solver_warnings(SCENARIOS) == [MFN_WARNING]

    def test_collect_tolerates_missing_and_malformed(self) -> None:
        assert WC.collect_solver_warnings([]) == []
        assert WC.collect_solver_warnings([{"computed_outputs": {}}]) == []
        assert WC.collect_solver_warnings([{}]) == []


class TestHtmlSurfaces:
    """`report.html` and `explorer.html` are delivered artifacts.

    They must NOT be fed through `_strip_md_markers`: it deletes every underscore, so a snake_case
    instrument id arrives at the founder as `safe003mfn` -- a name that matches nothing in their cap
    table.
    """

    def test_visualize_shows_solver_warning_with_id_intact(self) -> None:
        html = _render_visualize()
        assert "counterfactual" in html.lower(), "report.html drops solver warnings"
        assert "safe_003_mfn" in html, "underscores stripped from the instrument id"

    def test_explore_shows_solver_warning_with_id_intact(self) -> None:
        html = _render_explore()
        assert "counterfactual" in html.lower(), "explorer.html drops solver warnings"
        assert "safe_003_mfn" in html, "underscores stripped from the instrument id"


class TestConciseSurface:
    def test_concise_shows_solver_warning(self) -> None:
        cr = _load("concise_report")
        md = cr.render({"company_name": "Acme"}, {"scenarios": SCENARIOS}, rule_audit=None)
        assert "counterfactual" in md.lower(), "the concise route drops solver warnings"


class TestCoachingPayload:
    """The Context-B sub-agent's commentary is inserted into `report.md`, so the payload is a
    founder-facing surface. It sourced `high_severity_warnings` from BLOCKERS only, so a sub-agent
    coaching a founder on a priced round could not see that the MFN line was a counterfactual."""

    def test_payload_carries_solver_warnings(self) -> None:
        cm = _load("compose_report")
        payload = cm.build_coaching_payload(
            artifacts={
                "inputs.json": _fx("inputs.json"),
                "instruments.json": _fx("instruments.json"),
                "scenarios.json": {"scenarios": SCENARIOS},
                "rule_audit.json": _fx("rule_audit.json"),
                "counsel_packet.json": _fx("counsel_packet.json"),
            },
            review_dir="/tmp/x",
            report_path="/tmp/x/report.md",
            insertion_marker="MARKER",
        )
        blob = str(payload)
        assert "W_MFN_NOT_MOST_FAVORABLE" in blob, "coaching payload cannot see solver warnings"
