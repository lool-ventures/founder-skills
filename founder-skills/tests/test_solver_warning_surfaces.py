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


class TestTermsOnlyNoteDisclosure:
    """A note the math cannot convert is DROPPED and the founder is warned. Two things were wrong
    with that warning, and the first one is a factual error.

    `cap_state` raised the single code `W_NOTE_PRINCIPAL_MISSING` for two different causes — a
    missing principal AND a missing issuance date. So a founder holding a $1,000,000 note with no
    date was told the note "has no principal" and asked to "provide the principal". They already
    had; the field actually missing was the date, and nothing said so, which leaves no way to act.

    Second, both texts described the MECHANISM ("contributes NO shares") without the CONSEQUENCE.
    Dropping a note removes shares from the denominator, so every remaining stake — the founder's
    included — displays HIGHER than it will really be. The error flatters the reader, which is the
    direction that most needs saying out loud.
    """

    @staticmethod
    def _warnings_for(note: dict) -> list[str]:
        cs = _load("cap_state")
        inst = dict(_fx("instruments.json"))
        inst["convertible_notes"] = [note]
        built = cs.build_cap_state(_fx("inputs.json"), inst)
        return [w for w in built.get("warnings") or [] if "NOTE" in w]

    _BASE = {
        "id": "n1",
        "investor_name": "X",
        "interest_rate_type": "none",
        "extraction_confidence": "high",
        "valuation_cap": 10_000_000,
    }

    def test_missing_date_is_not_reported_as_a_missing_principal(self) -> None:
        got = self._warnings_for({**self._BASE, "principal": 1_000_000, "issuance_date": None})
        assert "W_NOTE_PRINCIPAL_MISSING" not in got, (
            "a $1M note with no issuance date was reported as having no principal — the founder is "
            "asked to supply a field they already supplied"
        )
        assert "W_NOTE_ISSUANCE_DATE_MISSING" in got, got

    def test_missing_principal_still_reports_a_missing_principal(self) -> None:
        got = self._warnings_for({**self._BASE, "principal": None, "issuance_date": "2024-01-01"})
        assert "W_NOTE_PRINCIPAL_MISSING" in got, got
        assert "W_NOTE_ISSUANCE_DATE_MISSING" not in got, got

    def test_both_causes_are_named_when_both_are_missing(self) -> None:
        got = self._warnings_for({**self._BASE, "principal": None, "issuance_date": None})
        assert set(got) >= {"W_NOTE_PRINCIPAL_MISSING", "W_NOTE_ISSUANCE_DATE_MISSING"}, got

    def test_each_text_names_its_own_field_and_the_direction_of_the_error(self) -> None:
        for code, must_name in [
            ("W_NOTE_PRINCIPAL_MISSING", "principal"),
            ("W_NOTE_ISSUANCE_DATE_MISSING", "issuance date"),
        ]:
            text = " ".join(WC.render_warning_callouts([code])).lower()
            assert text.strip(), f"{code} has no founder-facing prose"
            assert must_name in text, f"{code} does not name the field that is actually missing: {text}"
            assert "higher" in text, (
                f"{code} does not tell the founder their ownership is shown HIGHER than it will be — "
                "'contributes no shares' is the mechanism, not the consequence"
            )
