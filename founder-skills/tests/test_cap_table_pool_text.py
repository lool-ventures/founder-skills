"""The option pool section: one builder (`_pool_text.pool_section`) for every surface that explains the pool.

A coach explaining the pool in its own words named a post-money pool "the standard pre-money pool mechanics",
invented a new-options reading nobody computed, and composed lead-ins without their figures. The pool's
explanation is therefore computed, not written: this section is the founder's account of how the pool was
sized, and report.md shows it inside each scenario that has a pool target.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pool_sizing_claims  # noqa: E402
from test_cap_table import _cf_compose, _cf_run  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts"))
import _pool_text  # type: ignore[import-not-found]  # noqa: E402

_BASE = {"pre_money": 12_000_000, "new_money": 3_000_000, "target_pool_percent": 0.1}


def _scenario(params: dict[str, Any], **setup: int) -> dict[str, Any]:
    return {
        "scenario_id": "s_round",
        "label": "Series A",
        "type": "priced_round",
        "parameters": {**_BASE, **params},
        "computed_outputs": _cf_run(params, counterfactual=True, **setup),
    }


def _section_md(scenario: dict[str, Any]) -> list[str]:
    lines: list[str] = _pool_text.pool_section_markdown(_pool_text.pool_section(scenario, cap_state={}))
    return lines


def test_report_md_carries_the_section_the_builder_renders() -> None:
    """One source: report.md's pool lines are exactly the builder's, in order, once."""
    for params, setup in (
        ({"target_basis": "post_money"}, {}),
        ({"target_basis": "pre_money"}, {}),
        ({"target_basis": "post_money"}, {"available_pool": 3_000_000}),
        ({}, {}),
    ):
        _digest, page = _cf_compose(params, **setup)
        section = [ln for ln in _section_md(_scenario(params, **setup)) if ln]
        assert section[0] == _pool_text.POOL_SECTION_HEADING, section
        start = page.index(_pool_text.POOL_SECTION_HEADING)
        assert page.count(_pool_text.POOL_SECTION_HEADING) == 1
        shown = [ln for ln in page[start:].splitlines() if ln][: len(section)]
        assert shown == section, (params, setup, shown, section)


def test_no_pool_target_no_section() -> None:
    _digest, page = _cf_compose({"target_pool_percent": None})
    assert _pool_text.POOL_SECTION_HEADING not in page
    assert _pool_text.pool_section(_scenario({"target_pool_percent": None}), cap_state={}) == []


def test_the_section_states_the_measure_and_the_comparison_with_its_figures() -> None:
    lines = _section_md(_scenario({"target_basis": "post_money"}))
    text = "\n".join(lines)
    assert "10% of the fully diluted share count after the round" in text
    other = next(ln for ln in lines if ln.startswith(_pool_text.POOL_CF_LINE_LEAD))
    assert "64.80%" in other and "63.00%" in other


def test_how_the_cost_falls_is_said_only_when_options_are_added() -> None:
    added = "\n".join(_section_md(_scenario({"target_basis": "post_money"})))
    assert _pool_text.POOL_CREATED_BEFORE_PRICE in added
    none_added = "\n".join(_section_md(_scenario({"target_basis": "post_money"}, available_pool=3_000_000)))
    assert _pool_text.POOL_CREATED_BEFORE_PRICE not in none_added
    assert "no new options are added" in none_added


def test_the_section_ends_with_the_counsel_action() -> None:
    """The one action a founder takes from this section, stated by the report rather than left to a coach."""
    lines = [ln for ln in _section_md(_scenario({"target_basis": "post_money"})) if ln]
    assert lines[-1] == _pool_text.POOL_COUNSEL_ACTION


def test_the_judge_and_the_lanes_read_the_same_line_leads() -> None:
    """The paid lanes' lever checks look for these leads in report.md; they are the builder's own."""
    assert _pool_sizing_claims.REPORT_LINE_LEAD == _pool_text.POOL_CF_LINE_LEAD
    assert _pool_sizing_claims.INCREASE_LINE_LEAD == _pool_text.POOL_INCREASE_LINE_LEAD


def test_a_defaulted_basis_is_disclosed_inside_the_section() -> None:
    lines = _section_md(_scenario({}))
    assert any("ASSUMED" in ln for ln in lines), lines


# --- the coach is off the topic: the payload carries nothing about the pool's sizing -------------------------

_REMOVED_SCENARIO_KEYS = ("pool_sizing_counterfactual", "pool_basis_reading_unconfirmed", "pool_increase_reading")
_REMOVED_HEADLINE_KEYS = ("pool_basis", "pool_basis_assumed", "pool_basis_confirmed")
_POOL_CODES = (
    "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY",
    "W_CUSTOM_BASIS_STATED_BY_FOUNDER",
    "W_POOL_BASIS_READING_NOT_CONFIRMED",
    "W_POOL_INCREASE_READING_UNAVAILABLE",
)
# A sizing named in words: the other measure's labels, and the phrases a coach used for them.
_SIZING_WORDS = re.compile(
    r"\b(?:pre|post)[- ](?:money|round)\b|\bshare\s+count\b|\bnew\s+options\b|\bbasis\b", re.IGNORECASE
)
# The valuation, not a sizing: "$12.00M pre-money".
_VALUATION = re.compile(r"\$[\d.,]+\s*[KMB]?\s+pre-money\b", re.IGNORECASE)


def _report(params: dict[str, Any], **setup: int) -> dict[str, Any]:
    from test_cap_table import _CF_BASE_PARAMS, _make_cap_compose_dir, _run_cap_compose

    scenario = {
        "scenario_id": "s_round",
        # A model-written label naming the pool's sizing, as real runs write them: it is the model's own text
        # and is exempt below, so the check must not be vacuous about it.
        "label": "Series A — 10% post-money pool",
        "type": "priced_round",
        "parameters": {**_CF_BASE_PARAMS, **params},
        "computed_outputs": _cf_run(params, counterfactual=True, **setup),
    }
    rc, report, err = _run_cap_compose(_make_cap_compose_dir(scenarios=[scenario]))
    assert rc == 0, err
    out: dict[str, Any] = report
    return out


def _payload(params: dict[str, Any], **setup: int) -> dict[str, Any]:
    payload: dict[str, Any] = _report(params, **setup)["coaching_payload"]
    return payload


def _strings(o: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(o, str):
        return [(path, o)]
    if isinstance(o, dict):
        return [x for k, v in o.items() for x in _strings(v, f"{path}.{k}")]
    if isinstance(o, list):
        return [x for v in o for x in _strings(v, f"{path}[]")]
    return []


_CASES: tuple[tuple[dict[str, Any], dict[str, int]], ...] = (
    ({"target_basis": "post_money"}, {}),
    ({"target_basis": "pre_money"}, {}),
    ({}, {}),
    ({"target_basis": "post_money"}, {"available_pool": 400_000}),
    ({"target_basis": "custom", "custom_basis_stated_by_founder": "pre_money"}, {}),
    ({"target_basis": "post_money_increase"}, {}),
)


def test_the_payload_carries_no_pool_sizing_keys() -> None:
    for params, setup in _CASES:
        payload = _payload(params, **setup)
        for entry in payload["scenario_digest"]:
            for k in _REMOVED_SCENARIO_KEYS:
                assert k not in entry, (params, k)
            for k in _REMOVED_HEADLINE_KEYS:
                assert k not in entry["headline_inputs"], (params, k)


def test_no_payload_string_compose_writes_names_a_sizing() -> None:
    seen_label = False
    for params, setup in _CASES:
        payload = _payload(params, **setup)
        for path, text in _strings(payload):
            if path.endswith(".label") and path.startswith(".scenario_digest"):
                seen_label = seen_label or bool(_SIZING_WORDS.search(text))
                continue  # the model's own scenario label
            if path in {".review_dir", ".report_path", ".insertion_marker"}:
                continue
            stripped = _VALUATION.sub(" ", text)
            assert not _SIZING_WORDS.search(stripped), (params, path, text)
    assert seen_label  # positive control: a sizing word was present and exempted, so the walk saw strings


def test_the_pool_driver_points_to_the_report_section() -> None:
    import compose_report  # type: ignore[import-not-found]

    payload = _payload({"target_basis": "post_money"})
    pool = [d for d in payload["top_dilution_drivers"] if d["driver"] == "Option pool top-up"]
    assert pool, payload["top_dilution_drivers"]
    assert pool[0]["reference"] == compose_report.POOL_DRIVER_REFERENCE
    assert isinstance(pool[0]["founder_impact_pp"], float)


def test_pool_disclosures_leave_the_coach_but_not_the_hand_over() -> None:
    """The four pool-basis codes are the report's (callouts in its Option pool section), not the coach's. The
    main thread still names them at hand-over, from report.json's `report_disclosures` -- outside the coaching
    payload, which is staged whole to the coach. One of them is high severity."""
    for params, code in (
        (
            {
                "target_basis": "post_money_excluding_converting_securities",
                "excluding_basis_modeled_as": "post_money_by_founder_choice",
            },
            "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY",
        ),
        ({"target_basis": "custom", "custom_basis_stated_by_founder": "pre_money"}, "W_CUSTOM_BASIS_STATED_BY_FOUNDER"),
        ({"target_basis": "post_money"}, "W_POOL_BASIS_READING_NOT_CONFIRMED"),
    ):
        setup = {"available_pool": 400_000} if code == "W_POOL_BASIS_READING_NOT_CONFIRMED" else {}
        report = _report(params, **setup)
        payload = report["coaching_payload"]
        assert not [w for w in payload["high_severity_warnings"] if w.get("code") in _POOL_CODES]
        assert "report_disclosures" not in payload
        disclosed = [d for d in report["report_disclosures"] if d["code"] == code]
        assert len(disclosed) == 1, (code, report["report_disclosures"])
        assert disclosed[0]["label"] and disclosed[0]["pointer"]
        assert not _SIZING_WORDS.search(disclosed[0]["pointer"]), disclosed[0]


# --- the same section on both HTML pages ---------------------------------------------------------------------


def _pages(params: dict[str, Any], edit: Any = None, **setup: int) -> tuple[dict[str, Any], str, str]:
    """(scenario, report.html, explorer.html) for one priced scenario the real producer solved."""
    import subprocess

    from test_cap_table import _CF_BASE_PARAMS, _make_cap_compose_dir

    scenario = {
        "scenario_id": "s_round",
        "label": "Series A",
        "type": "priced_round",
        "parameters": {**_CF_BASE_PARAMS, **params},
        "computed_outputs": _cf_run(params, counterfactual=True, **setup),
    }
    if edit is not None:
        edit(scenario)
    d = _make_cap_compose_dir(scenarios=[scenario])
    scripts = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
    pages = []
    for script, out in (("visualize.py", "report.html"), ("explore.py", "explorer.html")):
        r = subprocess.run(
            [sys.executable, os.path.join(scripts, script), "--dir", d, "-o", os.path.join(d, out)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, (script, r.stderr)
        with open(os.path.join(d, out), encoding="utf-8") as f:
            pages.append(f.read())
    return scenario, pages[0], pages[1]


def test_both_pages_show_the_section_report_md_shows() -> None:
    import json as _json

    for params, setup in (
        ({"target_basis": "post_money"}, {}),
        ({"target_basis": "post_money"}, {"available_pool": 400_000}),
    ):
        scenario, report_html, explorer_html = _pages(params, **setup)
        items = _pool_text.pool_section(scenario, cap_state={})
        html = _pool_text.pool_section_html(items)
        assert report_html.count(html) == 1, params
        # The explorer embeds it per scenario (in its data payload) and shows it for the selected one.
        data = _json.loads(explorer_html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
        assert [sc["pool_section_html"] for sc in data["scenarios"]] == [html], params
        assert 'getElementById("scenario-pool")' in explorer_html
        for it in items:
            plain = it["text"].replace("**", "")
            assert _html_escape(plain) in _strip_tags(html), (it, html)


def test_the_explorer_hides_the_section_while_the_what_if_slider_is_off_the_scenario() -> None:
    """The slider models a different pre-money with the comparison switched off, so the section's figures
    would belong to the scenario the founder entered, not to the frame on screen."""
    _scenario, _report_html, explorer_html = _pages({"target_basis": "post_money"})
    enter = explorer_html[explorer_html.index("function enterModeled") :]
    enter = enter[: enter.index("\n}")]
    exit_ = explorer_html[explorer_html.index("function exitModeled") :]
    exit_ = exit_[: exit_.index("\n}")]
    assert 'getElementById("scenario-pool")' in enter and ".hidden = true" in enter
    assert 'getElementById("scenario-pool")' in exit_ and ".hidden = false" in exit_


def test_no_pool_no_section_on_either_page() -> None:
    _scenario, report_html, explorer_html = _pages({"target_pool_percent": None})
    assert 'class="pool-section"' not in report_html
    data = json.loads(explorer_html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    assert [sc["pool_section_html"] for sc in data["scenarios"]] == [""]


def _html_escape(text: str) -> str:
    import html as _h

    return _h.escape(text, quote=False)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


# --- facts the report now holds that the coach used to be told ---------------------------------------------


def test_assumed_and_given_stay_distinct_in_the_section() -> None:
    """Assumed: no basis given, disclosed as assumed. Given: either post-money reading beside existing
    unallocated options, disclosed as the reading modelled, with the other reading's figures. There is no third,
    "confirmed" state that clears the disclosure: the model could reach it by writing a field."""
    import _warning_callouts  # type: ignore[import-not-found]

    prose = _warning_callouts._SOLVER_WARNING_PROSE
    whole, new_only = prose["W_POOL_BASIS_READING_NOT_CONFIRMED"], prose["W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY"]
    assumed = "\n".join(_section_md(_scenario({})))
    stated = "\n".join(_section_md(_scenario({"target_basis": "post_money"}, available_pool=400_000)))
    increase = _section_md(_scenario({"target_basis": "post_money_increase"}, available_pool=400_000))
    assert "ASSUMED" in assumed and whole not in assumed and new_only not in assumed
    assert "ASSUMED" not in stated and whole in stated and new_only not in stated
    joined = "\n".join(increase)
    assert "ASSUMED" not in joined and new_only in joined and whole not in joined
    # The mirror cites the whole-pool reading's computed figures: the comparison line is that reading.
    cf = [ln for ln in increase if ln.startswith(_pool_text.POOL_CF_LINE_LEAD)]
    assert len(cf) == 1 and "Unallocated options equal to" in cf[0] and "founders" in cf[0], increase
    assert increase.index(cf[0]) > [i for i, ln in enumerate(increase) if new_only in ln][0]


def test_the_new_options_line_appears_only_when_that_reading_was_computed() -> None:
    computed = _section_md(_scenario({"target_basis": "post_money"}, available_pool=400_000))
    assert any(ln.startswith(_pool_text.POOL_INCREASE_LINE_LEAD) for ln in computed), computed
    for params, setup in (
        ({"target_basis": "post_money_increase"}, {"available_pool": 400_000}),
        ({"target_basis": "post_money"}, {}),
        ({"target_basis": "pre_money"}, {}),
    ):
        lines = _section_md(_scenario(params, **setup))
        assert not any(_pool_text.POOL_INCREASE_LINE_LEAD in ln for ln in lines), (params, lines)


# --- the measure is named by what it counts ------------------------------------------------------------------
# "Pre-money pool" is VC shorthand for how EVERY pool's cost falls (created before the price, existing holders
# pay), so a pool labelled "pre-money basis" collided with it, and coaches named post-money pools by it. The
# founder's surfaces name the measure by the share count it is taken against, and bridge once to the term
# sheet's own words for the post-money case: 'a term sheet writes this as a "10% post-money pool"'.

_OLD_LABELS = re.compile(
    r"\b(?:pre|post)-money basis\b|\b(?:pre|post)-round share count\b|\bplain post-money\b"
    r"|\bpool before the new money\b",
    re.IGNORECASE,
)
_PRE_MONEY_BESIDE_POOL = re.compile(r"\bpre-money\s+(?:option\s+)?pool\b|\bpool\b[^.\n]{0,40}\bpre-money\b", re.I)
_BRIDGE = 'a term sheet writes this as a "10% post-money pool"'
_MEASURE_CASES: tuple[tuple[dict[str, Any], dict[str, int]], ...] = (
    ({"target_basis": "post_money"}, {}),
    ({"target_basis": "post_money"}, {"available_pool": 400_000}),
    ({"target_basis": "post_money"}, {"available_pool": 3_000_000}),
    ({"target_basis": "pre_money"}, {}),
    ({}, {}),
    ({"target_basis": "post_money_increase"}, {}),
    ({"target_basis": "custom", "custom_basis_stated_by_founder": "pre_money"}, {}),
    (
        {
            "target_basis": "post_money_excluding_converting_securities",
            "excluding_basis_modeled_as": "post_money_by_founder_choice",
        },
        {},
    ),
    (
        {
            "target_basis": "post_money",
            "acquisition": {"consideration_pct": 0.1},
            "pool_consideration_basis": "exclude",
        },
        {},
    ),
)


def _surfaces(params: dict[str, Any], **setup: int) -> dict[str, str]:
    _scenario_dict, report_html, explorer_html = _pages(params, **setup)
    _digest, page = _cf_compose(params, **setup)
    section = "\n".join(_section_md(_scenario(params, **setup)))
    return {"report.md": page, "report.html": report_html, "explorer.html": explorer_html, "section": section}


def test_no_founder_surface_uses_the_old_measure_labels() -> None:
    for params, setup in _MEASURE_CASES:
        for name, text in _surfaces(params, **setup).items():
            hit = _OLD_LABELS.search(text)
            assert hit is None, (params, setup, name, text[max(0, hit.start() - 80) : hit.end() + 80])
            hit = _PRE_MONEY_BESIDE_POOL.search(text)
            assert hit is None, (params, setup, name, text[max(0, hit.start() - 80) : hit.end() + 80])


def test_the_post_money_measure_bridges_to_the_term_sheets_words_once() -> None:
    section = "\n".join(_section_md(_scenario({"target_basis": "post_money"})))
    assert section.count(_BRIDGE) == 1, section
    assert (
        "The unallocated options after the round equal 10% of the fully diluted share count after the round "
        f"({_BRIDGE})." in section
    ), section
    pre = "\n".join(_section_md(_scenario({"target_basis": "pre_money"})))
    assert "post-money pool" not in pre
    assert "The unallocated options after the round equal 10% of the fully diluted share count before the round." in pre


def test_the_gate_catalog_names_the_pre_round_measure_by_what_it_counts() -> None:
    with open(os.path.join(_REPO, "founder-skills", "skills", "cap-table", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    row = next(ln for ln in skill.splitlines() if ln.startswith("| **Pool basis**"))
    assert "The pool before the new money" not in row
    # Option order is kept: an unanswered question takes option 1.
    first, third = (
        row.index("`The pool available for new grants after the round`"),
        row.index("`Measured against the share count before the round`"),
    )
    assert first < third, row


def test_the_inputs_list_names_the_measure_in_words() -> None:
    """report.md's per-scenario Inputs list printed the raw `target_basis` value ("post_money")."""
    _digest, page = _cf_compose({"target_basis": "post_money"})
    assert "- `target_basis`: the fully diluted share count after the round" in page
    assert "- `target_basis`: post_money" not in page


# --- the pool target is printed at the precision it was given --------------------------------------------------
# A whole-percent format printed a 12.5% target as "12%", beside an acquisition note that printed it "12.5%". One
# formatter now serves every surface.

_ROUNDED = {0.125: re.compile(r"(?<![\d.])1[23]%"), 0.075: re.compile(r"(?<![\d.])[78]%")}


def _as_given(target: float) -> str:
    return {0.125: "12.5%", 0.075: "7.5%"}[target]


def test_the_pool_target_keeps_its_precision_in_report_md() -> None:
    for target in _ROUNDED:
        for basis in ("post_money", "pre_money", "post_money_increase"):
            params = {"target_basis": basis, "target_pool_percent": target}
            lines = _section_md(_scenario(params, available_pool=400_000))
            text = "\n".join(lines)
            assert _as_given(target) in text, (target, basis, lines)
            assert not _ROUNDED[target].search(text), (target, basis, lines)
            _digest, page = _cf_compose(params, available_pool=400_000)
            assert _as_given(target) in page and not _ROUNDED[target].search(page), (target, basis)


def test_the_pool_target_keeps_its_precision_on_both_pages() -> None:
    for target in _ROUNDED:
        scenario, report_html, explorer_html = _pages(
            {"target_basis": "post_money", "target_pool_percent": target}, available_pool=400_000
        )
        html = _pool_text.pool_section_html(_pool_text.pool_section(scenario, cap_state={}))
        assert _as_given(target) in html and not _ROUNDED[target].search(_strip_tags(html)), (target, html)
        assert report_html.count(html) == 1, target  # the page shows exactly this section
        data = json.loads(explorer_html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
        assert [sc["pool_section_html"] for sc in data["scenarios"]] == [html], target


def test_the_pool_target_keeps_its_precision_in_the_quick_answer() -> None:
    import quick_assess  # type: ignore[import-not-found]

    inputs = {
        "company_name": "Foobar",
        "founders": [{"id": "f", "name": "Founders", "common_shares": 8_000_000, "share_class": "class_a"}],
        "option_pool": {"authorized": 1_000_000, "issued": 800_000, "unallocated": 200_000},
        "metadata": {"run_id": "r"},
    }
    for target in _ROUNDED:
        out = quick_assess.quick_assess(
            company_name="Foobar",
            inputs=inputs,
            safes=[],
            notes=[],
            pre_money=12_000_000,
            new_money=3_000_000,
            target_pool_percent=target,
            target_basis="post_money",
        )
        md = out["_report_md"]
        assert _as_given(target) in md and not _ROUNDED[target].search(md), md
        assert _as_given(target) in out["headline_data"]["branch_summary"], out["headline_data"]


def test_the_acquisition_note_prints_the_target_as_the_section_does() -> None:
    for target in (0.1, 0.125):
        note = _pool_text.build_pool_basis_note(
            target_pool_percent=target,
            pool_consideration_basis="exclude",
            realized_pool_pct=0.15,
            acquisition_pct=0.2,
        )
        assert f"sized to {_pool_text.pool_target_pct(target)} of" in note, note
    assert _pool_text.pool_target_pct(0.1) == "10%" and _pool_text.pool_target_pct(0.125) == "12.5%"


# --- a comparison or reading that was not computed says why, on every surface ---------------------------------
# The producer writes the reason; the coach used to relay it, and when the coach left the topic nothing rendered it,
# so the section went silent exactly where the founder needed to know a figure was missing.

_NOT_COMPUTED_CASES = (
    ({"target_basis": "custom", "custom_basis_stated_by_founder": "post_money"}, ("cf", "inc")),
    (
        {
            "target_basis": "post_money_excluding_converting_securities",
            "excluding_basis_modeled_as": ("post_money_by_founder_choice"),
        },
        ("cf", "inc"),
    ),
)


def _reasons(scenario: dict[str, Any]) -> dict[str, str]:
    co = scenario["computed_outputs"]
    out = {}
    for key, block in (("cf", "pool_sizing_counterfactual"), ("inc", "pool_increase_reading")):
        b = co.get(block) or {}
        if b.get("status") in {"not_computed", "unavailable"}:
            out[key] = str(b["reason"])
    return out


def test_a_comparison_or_reading_not_computed_shows_its_reason_in_report_md() -> None:
    seen: set[str] = set()
    for params, kinds in _NOT_COMPUTED_CASES:
        scenario = _scenario(params, available_pool=400_000)
        reasons = _reasons(scenario)
        assert set(reasons) == set(kinds), (params, reasons)  # positive control: the producer refused both
        text = "\n".join(_section_md(scenario))
        for kind, reason in reasons.items():
            assert reason in text, (params, kind, text)
            seen.add(kind)
        _digest, page = _cf_compose(params, available_pool=400_000)
        for reason in reasons.values():
            assert reason in page, params
    assert seen == {"cf", "inc"}


def test_a_reason_reaches_both_pages() -> None:
    params = _NOT_COMPUTED_CASES[0][0]
    scenario, report_html, explorer_html = _pages(params, available_pool=400_000)
    html = _pool_text.pool_section_html(_pool_text.pool_section(scenario, cap_state={}))
    for reason in _reasons(scenario).values():
        assert _html_escape(reason) in html, reason
    assert report_html.count(html) == 1
    data = json.loads(explorer_html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    assert [sc["pool_section_html"] for sc in data["scenarios"]] == [html]


_UNAVAILABLE_REASON = "the new-options-only reading could not be solved"


def _unavailable(scenario: dict[str, Any], *, with_callout: bool = True) -> None:
    co = scenario["computed_outputs"]
    if with_callout:  # the solve raised: the producer both discloses it and records the reason
        co["warnings"] = [*co["warnings"], {"code": "W_POOL_INCREASE_READING_UNAVAILABLE", "severity": "medium"}]
    co["pool_increase_reading"] = {"status": "unavailable", "reason": _UNAVAILABLE_REASON}


def test_an_unavailable_reading_is_stated_once_on_every_surface() -> None:
    """When the solve raised, the producer both discloses it (a callout) and records a reason; the section states
    it once, by the callout, which every page already renders. When the re-solve returned a blocker instead, there
    is no callout, so the reason line is what says it."""
    import _warning_callouts  # type: ignore[import-not-found]

    callout = _warning_callouts._SOLVER_WARNING_PROSE["W_POOL_INCREASE_READING_UNAVAILABLE"].split("**")[1]
    scenario, report_html, explorer_html = _pages(
        {"target_basis": "post_money"}, edit=_unavailable, available_pool=400_000
    )
    md = "\n".join(_section_md(scenario))
    html = _pool_text.pool_section_html(_pool_text.pool_section(scenario, cap_state={}))
    for surface in (md, report_html, explorer_html):
        assert surface.count(callout) == 1, surface.count(callout)
        assert _UNAVAILABLE_REASON not in surface
    assert report_html.count(html) == 1
    blocked = _scenario({"target_basis": "post_money"}, available_pool=400_000)
    _unavailable(blocked, with_callout=False)
    text = "\n".join(_section_md(blocked))
    assert text.count(_UNAVAILABLE_REASON) == 1 and callout not in text, text


def test_every_reason_the_producer_writes_passes_the_founder_text_scan() -> None:
    import run_scenario  # type: ignore[import-not-found]

    sys.path.insert(0, os.path.join(_REPO, "founder-skills", "scripts"))
    try:
        import _founder_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    reasons = [*run_scenario._POOL_NOT_COMPUTED_REASON.values(), *run_scenario._INCREASE_NOT_COMPUTED_REASON.values()]
    assert len(reasons) == 6
    for r in reasons:
        assert _founder_text.scan(r) == {"enums": [], "filenames": []}, r


def test_the_other_sizing_line_names_itself_once_on_every_surface() -> None:
    """The line's lead already says "Option pool on the other sizing"; its text repeated "On the other sizing"."""
    for setup in ({}, {"available_pool": 3_000_000}):  # computed, and the same on both sizings
        scenario, report_html, explorer_html = _pages({"target_basis": "post_money"}, **setup)
        md = "\n".join(_section_md(scenario))
        html = _pool_text.pool_section_html(_pool_text.pool_section(scenario, cap_state={}))
        assert report_html.count(html) == 1
        data = json.loads(explorer_html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
        assert [sc["pool_section_html"] for sc in data["scenarios"]] == [html]
        for surface in (md, _strip_tags(html)):
            assert len(re.findall(r"on the other sizing", surface, re.I)) == 1, (setup, surface)
