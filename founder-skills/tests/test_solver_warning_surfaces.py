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


# The option pool's basis disclosures, on every surface a founder reads. One registry, so a new code cannot
# render in report.md and vanish from the HTML pages, the concise answer or the coach's payload.
_POOL_BASIS_DISCLOSURES = (
    "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY",
    "W_CUSTOM_BASIS_STATED_BY_FOUNDER",
    "W_POOL_BASIS_READING_NOT_CONFIRMED",
    "W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY",
)


def _pool_scenarios(code: str) -> list[dict]:
    return [
        {
            "scenario_id": "s1",
            "type": "priced_round",
            "label": "Series A",
            "computed_outputs": {"completeness": "full", "warnings": [{"code": code, "message": "m"}], "blockers": []},
        }
    ]


class TestPoolBasisDisclosuresReachEverySurface:
    @staticmethod
    def _label(code: str) -> str:
        label = WC._SOLVER_WARNING_LABELS[code]
        assert isinstance(label, str) and label
        return label

    def test_each_has_prose_and_a_label(self) -> None:
        for code in _POOL_BASIS_DISCLOSURES:
            assert WC._SOLVER_WARNING_PROSE.get(code), code
            assert self._label(code)

    def test_report_md_callouts(self) -> None:
        for code in _POOL_BASIS_DISCLOSURES:
            out = "\n".join(WC.render_solver_warning_callouts([{"code": code}]))
            assert WC._SOLVER_WARNING_PROSE[code].split("**")[1] in out, code

    def test_html_pages(self) -> None:
        viz, exp = _load("visualize"), _load("explore")
        for code in _POOL_BASIS_DISCLOSURES:
            kw = {
                "inputs": _fx("inputs.json"),
                "cap_state": _fx("cap_state.json"),
                "scenarios_doc": {"scenarios": _pool_scenarios(code)},
                "rule_audit": _fx("rule_audit.json"),
                "counsel_packet": _fx("counsel_packet.json"),
            }
            report = str(viz.render_report_html(**kw))
            explorer = str(exp.render_explorer_html(**{k: v for k, v in kw.items() if k != "rule_audit"}))
            needle = WC._SOLVER_WARNING_PROSE[code].split("**")[1]
            assert needle in report or self._label(code) in report, ("report.html", code)
            assert needle in explorer or self._label(code) in explorer, ("explorer.html", code)

    def test_concise(self) -> None:
        cr = _load("concise_report")
        for code in _POOL_BASIS_DISCLOSURES:
            md = cr.render({"company_name": "Acme"}, {"scenarios": _pool_scenarios(code)}, rule_audit=None)
            needle = WC._SOLVER_WARNING_PROSE[code].split("**")[1]
            assert needle in md or self._label(code) in md, code

    def test_the_hand_over_list_and_not_the_coaching_payload(self) -> None:
        """The pool-basis disclosures are the report's (its Option pool section) and the main thread's hand-over
        list (report.json `report_disclosures`); the coach, which does not discuss the pool's sizing, is not
        handed them."""
        cm = _load("compose_report")
        for code in _POOL_BASIS_DISCLOSURES:
            payload = cm.build_coaching_payload(
                artifacts={
                    "inputs.json": _fx("inputs.json"),
                    "instruments.json": _fx("instruments.json"),
                    "scenarios.json": {"scenarios": _pool_scenarios(code)},
                    "rule_audit.json": _fx("rule_audit.json"),
                    "counsel_packet.json": _fx("counsel_packet.json"),
                },
                review_dir="/tmp/x",
                report_path="/tmp/x/report.md",
                insertion_marker="MARKER",
            )
            assert not [w for w in payload["high_severity_warnings"] if w.get("code") == code], code
            listed = [d for d in cm.build_report_disclosures(_pool_scenarios(code)) if d["code"] == code]
            assert len(listed) == 1 and listed[0]["label"], (code, listed)

    def test_the_text_passes_the_founder_text_scan(self) -> None:
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import _founder_text  # type: ignore[import-not-found]
        finally:
            sys.path.pop(0)
        for code in _POOL_BASIS_DISCLOSURES:
            for text in (WC._SOLVER_WARNING_PROSE[code], self._label(code)):
                assert _founder_text.scan(text) == {"enums": [], "filenames": []}, (code, text)


def test_the_two_reading_disclosures_are_judged_alike() -> None:
    """The new-options-only callout mirrors the whole-pool one, so the coaching judge takes both the same way:
    clean when both readings' figures were computed, and (report text being exempt from the backstop) flagged the
    same way when a coach repeats one with no second reading computed."""
    judge = _load("_pool_sizing_claims")
    whole = WC._SOLVER_WARNING_PROSE["W_POOL_BASIS_READING_NOT_CONFIRMED"]
    mirror = WC._SOLVER_WARNING_PROSE["W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY"]
    for other, increase in (([60.0], [58.0]), (None, None), ([60.0], None)):

        def reasons(text: str, other: list[float] | None = other, increase: list[float] | None = increase) -> list:
            found = judge.pool_sizing_findings(
                text,
                modeled_basis="post_money",
                other_founders_pct=other,
                increase_founders_pct=increase,
                target_pct=10.0,
            )
            return [f["reason"] for f in found]

        assert reasons(mirror) == reasons(whole), (other, increase)
    assert not judge.pool_sizing_findings(
        mirror, modeled_basis="post_money", other_founders_pct=[60.0], increase_founders_pct=[58.0], target_pct=10.0
    )


def test_a_non_w_code_is_not_dropped_unless_another_renderer_owns_it() -> None:
    """The callout filter kept only `W_` codes while its own fallback promised "say the honest generic
    thing rather than dropping it". The one non-`W_` code the orchestrator writes into a scenario's
    warnings today, `target_basis_defaulted`, has its own callout in the report and its own payload flag,
    so it is named as the exception; any other code, a future one included, reaches the founder."""
    unknown = [{"code": "pool_target_already_met_check_intent", "severity": "high", "message": "x"}]
    lines = WC.render_solver_warning_callouts(unknown)
    assert lines and "round math flagged" in " ".join(lines), lines
    assert "pool_target" not in " ".join(lines)  # the code itself is withheld
    assert WC.render_solver_warning_callouts([{"code": "target_basis_defaulted", "severity": "medium"}]) == []
    # Positive control: a W_ code still renders.
    assert WC.render_solver_warning_callouts([{"code": "W_SOLVER_AITKEN_FALLBACK"}])


def test_the_coach_sees_the_same_warnings_the_callouts_render() -> None:
    """One predicate for both surfaces: the payload's `high_severity_warnings` used to repeat the `W_`
    prefix test, so a code the report showed could still be missing from what the coach reads."""
    assert WC.is_solver_callout("W_SOLVER_AITKEN_FALLBACK")
    assert WC.is_solver_callout("pool_target_already_met_check_intent")
    assert not WC.is_solver_callout("target_basis_defaulted")
    assert not WC.is_solver_callout("")
    compose = (SCRIPTS / "compose_report.py").read_text(encoding="utf-8")
    assert "_warning_callouts.is_solver_callout(" in compose
    assert 'str(w.get("code") or "").startswith("W_")\n    )' not in compose


# --- the flip's Section 102 line ------------------------------------------------------------------------------
# A flip with issued options and no per-grant data said nothing to the founder about Section 102: the counsel
# item fired only for a §102 or mixed pool, and the flip's outputs carried no warnings at all. The line is now a
# flip disclosure: on every surface, in the hand-over list, and NOT in the coaching payload.

S102 = "W_SECTION_102_NOT_MODELED"


def _flip_inputs(*, issued: float, structure: str | None = "israeli", plan_type: str = "iso") -> dict:
    inputs = _fx("inputs.json")
    inputs["option_pool"] = dict(inputs["option_pool"], issued=issued, plan_type=plan_type)
    if structure is not None:
        inputs["jurisdiction"] = {"structure": structure}
    return inputs


def _grant() -> dict:
    return {
        "grant_id": "g1",
        "holder": "Employee One",
        "shares": 1_000,
        "strike_price": 0.1,
        "plan_type": "section_102_cg",
        "grant_date": "2024-01-01",
    }


def _run_flip(inputs: dict, grants: list[dict] | None = None) -> list[dict]:
    rs = _load("run_scenario")
    instruments = _fx("instruments.json")
    instruments["option_grants"] = list(grants or [])
    scenarios: list[dict] = rs.run_all_scenarios(
        inputs=inputs,
        instruments=instruments,
        cap_state=_fx("cap_state.json"),
        scenario_requests=[{"scenario_id": "s_flip", "label": "Flip", "type": "flip", "parameters": {}}],
    )
    return scenarios


def _s102_codes(scenarios: list[dict]) -> list[str]:
    return [w.get("code") for w in WC.collect_solver_warnings(scenarios) if w.get("code") == S102]


class TestFlipSection102Line:
    def test_issued_options_with_no_grant_data_are_disclosed_whatever_the_plan(self) -> None:
        for plan_type in ("iso", "nso", "section_3i", "section_102_cg", "mixed"):
            scenarios = _run_flip(_flip_inputs(issued=50_000, plan_type=plan_type))
            assert _s102_codes(scenarios) == [S102], plan_type

    def test_grant_data_present_states_nothing(self) -> None:
        """Also the recorded 'share' / 'partial' answer followed through: the grants reached the instruments, so
        the line is not stated, and no ledger drop is needed to remove it."""
        assert _s102_codes(_run_flip(_flip_inputs(issued=50_000, plan_type="section_102_cg"), [_grant()])) == []

    def test_no_issued_options_states_nothing(self) -> None:
        assert _s102_codes(_run_flip(_flip_inputs(issued=0))) == []

    def test_a_delaware_only_structure_states_nothing(self) -> None:
        assert _s102_codes(_run_flip(_flip_inputs(issued=50_000, structure="delaware"))) == []

    def test_the_line_keys_on_the_documents_the_grants_question_reads(self) -> None:
        """One source for the line and the question: `_pred_ct_flip_grants` reads `inputs.option_pool.issued`
        and `instruments.option_grants`. A fractional issued count is owed the question (> 0) though the cap
        state truncates it to 0; the line follows the question."""
        flip = _load("flip_scenario")
        assert flip.section_102_not_modeled(_flip_inputs(issued=0.5), {"option_grants": []}) is not None
        assert flip.section_102_not_modeled(_flip_inputs(issued=10), {"option_grants": ["not-a-grant"]}) is not None
        assert flip.section_102_not_modeled(_flip_inputs(issued=10), {"option_grants": [_grant()]}) is None
        gates = (REPO / "scripts" / "_gates.py").read_text(encoding="utf-8")
        assert 'issued = pool.get("issued") if isinstance(pool, dict) else None' in gates
        assert 'not _ct_items(ctx, "option_grants")' in gates

    def test_prose_and_label(self) -> None:
        assert WC._SOLVER_WARNING_PROSE[S102].startswith("**Section 102 tax exposure was not modelled")
        assert WC._SOLVER_WARNING_LABELS[S102]
        assert S102 in WC.FLIP_DISCLOSURE_CODES
        assert WC.is_solver_callout(S102)

    def test_the_text_passes_the_founder_text_scan(self) -> None:
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import _founder_text  # type: ignore[import-not-found]
        finally:
            sys.path.pop(0)
        for text in (WC._SOLVER_WARNING_PROSE[S102], WC._SOLVER_WARNING_LABELS[S102], WC.humanize_warning(S102)):
            assert _founder_text.scan(text) == {"enums": [], "filenames": []}, text
        assert S102 not in WC.humanize_warning(S102)

    def test_every_surface_states_it(self) -> None:
        scenarios = _run_flip(_flip_inputs(issued=50_000))
        needle = WC._SOLVER_WARNING_PROSE[S102].split("**")[1]
        cm = _load("compose_report")
        artifacts = {
            "inputs.json": _flip_inputs(issued=50_000),
            "instruments.json": _fx("instruments.json"),
            "cap_state.json": _fx("cap_state.json"),
            "scenarios.json": {"scenarios": scenarios},
            "rule_audit.json": _fx("rule_audit.json"),
            "counsel_packet.json": _fx("counsel_packet.json"),
        }
        md = cm.render_report_markdown(artifacts=artifacts, validation_warnings=[], insertion_marker="MARKER")
        assert md.count(needle) == 1
        cr = _load("concise_report")
        assert needle in cr.render({"company_name": "Acme"}, {"scenarios": scenarios}, rule_audit=None)
        viz, exp = _load("visualize"), _load("explore")
        kw = {
            "inputs": artifacts["inputs.json"],
            "cap_state": artifacts["cap_state.json"],
            "scenarios_doc": {"scenarios": scenarios},
            "counsel_packet": artifacts["counsel_packet.json"],
        }
        assert needle in str(viz.render_report_html(rule_audit=artifacts["rule_audit.json"], **kw))
        assert needle in str(exp.render_explorer_html(**kw))

    def test_the_hand_over_list_and_not_the_coaching_payload(self) -> None:
        """Routed like the pool-basis disclosures: the coaching payload of a flip run is the payload it was before
        the line existed, and the main thread's hand-over list names it with a pointer to where the report says it."""
        cm = _load("compose_report")
        with_line = _run_flip(_flip_inputs(issued=50_000))
        assert _s102_codes(with_line) == [S102]
        without_line = [
            dict(s, computed_outputs={k: v for k, v in s["computed_outputs"].items() if k != "warnings"})
            for s in with_line
        ]

        def payload(scenarios: list[dict]) -> dict:
            result: dict = cm.build_coaching_payload(
                artifacts={
                    "inputs.json": _flip_inputs(issued=50_000),
                    "instruments.json": _fx("instruments.json"),
                    "cap_state.json": _fx("cap_state.json"),
                    "scenarios.json": {"scenarios": scenarios},
                    "rule_audit.json": _fx("rule_audit.json"),
                    "counsel_packet.json": _fx("counsel_packet.json"),
                },
                review_dir="/tmp/x",
                report_path="/tmp/x/report.md",
                insertion_marker="MARKER",
            )
            return result

        assert payload(with_line) == payload(without_line)
        assert S102 not in str(payload(with_line))
        listed = [d for d in cm.build_report_disclosures(with_line) if d["code"] == S102]
        assert len(listed) == 1, listed
        assert listed[0]["label"] == WC._SOLVER_WARNING_LABELS[S102]
        assert listed[0]["pointer"] == WC.FLIP_DISCLOSURE_POINTER
        assert listed[0]["severity"] == "medium"
