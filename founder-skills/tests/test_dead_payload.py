"""Unit tests for the dead-payload analyzer.

Two properties matter most and are asserted directly: a computed-name read (`LABELS[cat]`) must not be
reported as dead, and it must not be reported as consumption either.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

import dead_payload as dp


# ---------------------------------------------------------------------------
# Static access
# ---------------------------------------------------------------------------


def test_dotted_access_is_a_read() -> None:
    r = dp.analyze("render(DATA.scenarios);", ["scenarios", "founders"])
    assert r["read"] == ["scenarios"]
    assert r["unread"] == ["founders"]
    assert r["unverifiable"] == []


def test_static_bracket_access_is_a_read() -> None:
    r = dp.analyze('render(DATA["scenarios"]);', ["scenarios"])
    assert r["read"] == ["scenarios"]
    assert r["unread"] == []


def test_single_quoted_static_bracket_is_a_read() -> None:
    assert dp.analyze("render(DATA['scenarios']);", ["scenarios"])["unread"] == []


def test_optional_chaining_is_a_read() -> None:
    assert dp.analyze("render(DATA?.scenarios);", ["scenarios"])["unread"] == []


def test_named_destructuring_is_a_read() -> None:
    r = dp.analyze("const { scenarios, founders } = DATA;", ["scenarios", "founders", "sweep"])
    assert r["read"] == ["founders", "scenarios"]
    assert r["unread"] == ["sweep"]


def test_renaming_destructuring_reads_the_source_key_not_the_alias() -> None:
    r = dp.analyze("const { scenarios: rows } = DATA;", ["scenarios", "rows"])
    assert r["read"] == ["scenarios"]
    assert r["unread"] == ["rows"], "the local alias is not a payload key"


# ---------------------------------------------------------------------------
# Dynamic access -> unverifiable, never clean
# ---------------------------------------------------------------------------


def test_dynamic_bracket_makes_keys_unverifiable_not_read() -> None:
    """Treating computed access as "everything is consumed" would hide a genuinely dead key."""
    r = dp.analyze("function humanize(cat, v) { return LABELS[cat][v]; }", ["completeness", "scope"], var="LABELS")
    assert r["dynamic_access"] is True
    assert r["read"] == []
    assert r["unread"] == [], "must not claim these are dead — they may be reached by computed name"
    assert r["unverifiable"] == ["completeness", "scope"]


def test_dynamic_access_does_not_launder_a_statically_read_key() -> None:
    r = dp.analyze("LABELS[cat]; LABELS.scope;", ["completeness", "scope"], var="LABELS")
    assert r["read"] == ["scope"]
    assert r["unverifiable"] == ["completeness"]


def test_object_keys_iteration_is_dynamic() -> None:
    assert dp.analyze("Object.keys(DATA).forEach(f);", ["a"])["unverifiable"] == ["a"]


def test_for_in_iteration_is_dynamic() -> None:
    assert dp.analyze("for (const k in DATA) use(k);", ["a"])["unverifiable"] == ["a"]


def test_spread_is_dynamic() -> None:
    assert dp.analyze("const copy = {...DATA};", ["a"])["unverifiable"] == ["a"]


def test_iterating_a_member_is_not_whole_object_access() -> None:
    """`for (const s of DATA.scenarios)` iterates a MEMBER, so other keys stay provably dead."""
    script = "for (const s of DATA.scenarios) use(s);"
    r = dp.analyze(script, ["scenarios", "founders"])
    assert r["dynamic_access"] is False
    assert r["read"] == ["scenarios"]
    assert r["unread"] == ["founders"]


def test_stringifying_a_member_is_not_whole_object_access() -> None:
    r = dp.analyze("JSON.stringify(DATA.views);", ["views", "other"])
    assert r["dynamic_access"] is False
    assert r["unread"] == ["other"]


# ---------------------------------------------------------------------------
# Aliasing
# ---------------------------------------------------------------------------


def test_alias_member_access_is_a_read() -> None:
    r = dp.analyze("const d = DATA;\nrender(d.scenarios);", ["scenarios"])
    assert r["aliases"] == ["d"]
    assert r["unread"] == []


def test_member_binding_is_not_an_alias() -> None:
    """A member binding's own member reads say nothing about the payload's other keys."""
    script = "const pre = DATA.pre_financing;\nuse(pre.common);"
    r = dp.analyze(script, ["pre_financing", "common"])
    assert r["aliases"] == []
    assert r["read"] == ["pre_financing"]
    assert r["unread"] == ["common"]


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------


def test_extract_payload_reads_the_embedded_object() -> None:
    html = '<script>const DATA = {"a": 1, "b": [2]};\nmore();</script>'
    assert dp.extract_payload(html) == {"a": 1, "b": [2]}


def test_extract_payload_is_loud_when_absent() -> None:
    try:
        dp.extract_payload("<script>const OTHER = {};</script>")
    except AssertionError as exc:
        assert "could not locate" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a missing payload must raise, not return {} — a silent {} is vacuous")


# ---------------------------------------------------------------------------
# The four embedders
#
# Every generator that embeds a JS payload is covered here. `unread` is a hard failure: the key is
# provably unreachable. `dynamic_access` is reported, not failed — it means this scan cannot see the
# whole picture for that object, and silence about that is what makes a green misleading.
# ---------------------------------------------------------------------------


def _cp_explorer_html() -> str:
    import test_explore_competitive_positioning as t

    with t._make_artifact_dir(t._all_artifacts()) as d:
        rc, html, stderr = t._run_explore(d)
    assert rc == 0, stderr
    return html


def _fmr_explorer_html() -> str:
    import test_explore as t

    d = t._make_artifact_dir()
    rc, html, stderr = t.run_script_raw("explore.py", ["--dir", d])
    assert rc == 0, stderr
    return html


def _fmr_review_inputs_html() -> str:
    import test_review_inputs as t

    rc, html, stderr = t._generate_static(t._FULL_INPUTS)
    assert rc == 0, stderr
    return html


def _cap_table_explorer_html() -> str:
    import os
    import tempfile

    import test_cap_table as t

    d = t._make_cap_compose_dir(scenarios=[t._minimal_scenario("s1")])
    out = os.path.join(tempfile.mkdtemp(), "explorer.html")
    rc, _stdout, stderr = t._run("explore.py", ["--dir", d, "-o", out])
    assert rc == 0, stderr
    with open(out, encoding="utf-8") as f:
        return f.read()


# (label, html factory, payload var, minimum key count for the scan to be non-vacuous)
_EMBEDDERS = [
    ("competitive-positioning/explore.py", _cp_explorer_html, "DATA", 5),
    ("financial-model-review/explore.py", _fmr_explorer_html, "DATA", 5),
    ("financial-model-review/review_inputs.py", _fmr_review_inputs_html, "DATA", 5),
    ("cap-table/explore.py", _cap_table_explorer_html, "DATA", 3),
    ("cap-table/explore.py LABELS", _cap_table_explorer_html, "LABELS", 3),
]


@pytest.mark.parametrize(("label", "factory", "var", "min_keys"), _EMBEDDERS)
def test_no_embedded_payload_key_is_provably_unread(
    label: str, factory: Callable[[], str], var: str, min_keys: int
) -> None:
    html = factory()
    payload = dp.extract_payload(html, var)
    assert len(payload) >= min_keys, (
        f"{label}: {var} parsed as {len(payload)} key(s) — below the non-vacuity floor, so this scan "
        f"would pass for the wrong reason"
    )
    result = dp.analyze(html, list(payload), var=var)
    assert result["unread"] == [], (
        f"{label} embeds {var} key(s) its script never reads: {result['unread']}. Either render them or "
        f"stop embedding them — an unread key is a founder-facing feature that silently does not exist, "
        f"and it still costs payload."
    )


def test_dynamic_access_coverage_is_declared_not_assumed() -> None:
    """Pin which objects the scan can fully verify, so a new dynamic access does not pass unnoticed.

    An object with dynamic access yields `unverifiable` keys — neither read nor provably dead. Listing
    the expected set here means a generator that newly switches to computed access has to come through
    this test rather than quietly reducing coverage.
    """
    expected_dynamic = {"cap-table/explore.py LABELS", "financial-model-review/review_inputs.py"}
    actual_dynamic = set()
    for label, factory, var, _min_keys in _EMBEDDERS:
        html = factory()
        payload = dp.extract_payload(html, var)
        if dp.analyze(html, list(payload), var=var)["dynamic_access"]:
            actual_dynamic.add(label)
    assert actual_dynamic == expected_dynamic, (
        f"dynamic-access coverage changed: {actual_dynamic} vs expected {expected_dynamic}. A newly "
        f"dynamic object means its keys can no longer be shown dead; a newly static one means it can "
        f"and the expectation should shrink."
    )
