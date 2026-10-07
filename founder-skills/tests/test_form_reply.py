"""The Desktop form-reply reader, and the switch that keeps it off.

Every reply shape below is FIXTURE-DERIVED: it follows the synthetic `<header> — Label: value · …`
shape the two-figures hook's tests use, never a reply captured from a live form. That is why the
reader ships switched off and the recorder refuses `--form-reply`; the guard at the bottom fails if the
switch is flipped without a captured reply committed beside these tests.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import gate_run_helpers as h
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CAPTURES = Path(__file__).resolve().parent / "fixtures" / "form_replies"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fr = _load("_form_reply")

HEADER = "Market sizing"
STAGE = fr.Field("ctx_basics.stage", "Stage", [("seed", "Seed", False), ("series_a", "Series A", False)], False)
METHOD = fr.Field(
    "ms_methodology",
    "Methodology",
    [("looks_good", "Looks good", False), ("change_methodology", "Change the methodology", False)],
    False,
)
SECTOR = fr.Field(
    "ctx_basics.sector",
    "Sector",
    [("different", "A different sector — I'll state it", True), ("not_sure", "Not sure", False)],
    False,
)
SCENARIOS = fr.Field(
    "ct_scenario_selection",
    "Scenarios",
    [("priced_round", "Series A priced round", False), ("flip", "Israeli ↔ Delaware flip", False)],
    True,
)
TWO_VALUES = fr.Field(
    "ct_option_pool",
    "Pool",
    [("authorized", "Authorized", True), ("unallocated", "Unallocated", True), ("none", "None", False)],
    False,
)


def _answers(reply: str, *fields: object) -> list[tuple[str, list[str], str | None]]:
    parsed = fr.parse(reply, HEADER, list(fields))
    assert parsed.skipped is False
    return [(k, list(ids), v) for k, ids, v in parsed.answers]


@pytest.mark.parametrize("head", [HEADER, HEADER + " details"])
@pytest.mark.parametrize("dash", ["—", "–", "-"])
def test_header_with_or_without_details_and_any_dash(head: str, dash: str) -> None:
    reply = f"{head} {dash} Stage: Seed · Methodology: Looks good"
    assert _answers(reply, STAGE, METHOD) == [
        ("ctx_basics.stage", ["seed"], None),
        ("ms_methodology", ["looks_good"], None),
    ]


def test_a_value_may_contain_a_separator_or_a_colon() -> None:
    reply = f"{HEADER} — Stage: Seed · Sector: Fintech · payments: B2B"
    out = _answers(reply, STAGE, SECTOR)
    assert out[1] == ("ctx_basics.sector", ["different"], "Fintech · payments: B2B")


@pytest.mark.parametrize("quoted", ['"Seed"', "“Seed”", "'Seed'"])
def test_a_quoted_value_is_unquoted(quoted: str) -> None:
    assert _answers(f"{HEADER} — Stage: {quoted}", STAGE) == [("ctx_basics.stage", ["seed"], None)]


def test_a_folded_value_is_read_from_the_full_content_section() -> None:
    reply = (
        f"{HEADER} — Stage: Seed · Sector: Scheduling tools for…\n"
        "--- Full content ---\n"
        "Stage: Seed\n"
        "Sector: Scheduling tools for independent bike repair shops\n"
    )
    out = _answers(reply, STAGE, SECTOR)
    assert out[1] == ("ctx_basics.sector", ["different"], "Scheduling tools for independent bike repair shops")


def test_multi_select_joins_labels_with_commas() -> None:
    reply = f"{HEADER} — Scenarios: Series A priced round, Israeli ↔ Delaware flip"
    assert _answers(reply, SCENARIOS) == [("ct_scenario_selection", ["priced_round", "flip"], None)]


def test_a_single_value_option_takes_free_text() -> None:
    assert _answers(f"{HEADER} — Sector: Logistics", SECTOR) == [("ctx_basics.sector", ["different"], "Logistics")]


def test_several_value_options_take_label_then_value() -> None:
    reply = f"{HEADER} — Pool: Unallocated: 120000"
    assert _answers(reply, TWO_VALUES) == [("ct_option_pool", ["unallocated"], "120000")]


def test_a_missing_key_is_refused_with_the_allowed_labels() -> None:
    with pytest.raises(fr.FormReplyError) as e:
        fr.parse(f"{HEADER} — Stage: Seed", HEADER, [STAGE, METHOD])
    assert e.value.code == "FORM_REPLY_UNMATCHED"
    assert e.value.allowed["Methodology"] == ["Looks good", "Change the methodology"]


def test_an_unmatched_value_is_refused() -> None:
    with pytest.raises(fr.FormReplyError) as e:
        fr.parse(f"{HEADER} — Stage: Series Z", HEADER, [STAGE])
    assert e.value.code == "FORM_REPLY_UNMATCHED"
    assert e.value.allowed == {"Stage": ["Seed", "Series A"]}


def test_a_label_the_form_did_not_ask_is_refused() -> None:
    with pytest.raises(fr.FormReplyError) as e:
        fr.parse(f"{HEADER} — Stage: Seed · Geography: Lisbon", HEADER, [STAGE])
    assert e.value.code == "FORM_REPLY_UNMATCHED"


def test_a_reply_without_the_header_is_refused() -> None:
    with pytest.raises(fr.FormReplyError):
        fr.parse("Stage: Seed", HEADER, [STAGE])


def test_the_skip_line_records_nothing() -> None:
    parsed = fr.parse(fr.SKIP_LINE, HEADER, [STAGE])
    assert parsed.skipped is True and parsed.answers == []


def test_an_uploaded_files_block_is_dropped_first() -> None:
    reply = f"<uploaded_files>\n<file>deck.pdf</file>\n</uploaded_files>\n{HEADER} — Stage: Series A"
    assert _answers(reply, STAGE) == [("ctx_basics.stage", ["series_a"], None)]


def test_the_skip_line_is_the_two_figures_hooks_own() -> None:
    assert fr.SKIP_LINE == _load("two_figures_check").SKIP_LINE


def test_the_reader_is_switched_off() -> None:
    assert fr.FORM_REPLY_ENABLED is False


def test_the_recorder_refuses_a_form_reply_while_switched_off(tmp_path: Path) -> None:
    root, run_id, _run_dir = h.start_bound(tmp_path, "market-sizing")
    opened = h.record(root, run_id, "open", "--gate", "ctx_basics.stage")
    assert opened.returncode == 0, opened.stderr
    before = h.snapshot(root, run_id)
    proc = h.record(root, run_id, "answer", "--form-reply", stdin=f"{HEADER} — Stage: Seed\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert '"FORM_REPLY_DISABLED"' in proc.stdout
    assert proc.stderr.strip()
    assert h.snapshot(root, run_id) == before


def test_switching_the_reader_on_needs_a_captured_reply() -> None:
    """Flipping the switch without a live capture committed here fails: the shapes above are not evidence."""
    if not fr.FORM_REPLY_ENABLED:
        return
    captures = sorted(CAPTURES.glob("captured-*.txt"))
    assert captures, "the form reader is on, but no captured live reply is committed"
    for path in captures:
        text = path.read_text(encoding="utf-8")
        assert text.strip(), path.name


POOL = fr.Field(
    "ct_option_pool",
    "Option pool",
    [("no_pool", "No option pool", False), ("provide", "Yes — I'll provide authorized / issued / unallocated", True)],
    False,
)


@pytest.mark.parametrize("value", ["No option pol", "no option", "No option pool please"])
def test_free_text_close_to_another_choice_is_refused(value: str) -> None:
    """A garbled choice is not a value: it never goes to the one option that takes free text."""
    with pytest.raises(fr.FormReplyError) as e:
        fr.parse(f"Cap table — Option pool: {value}", "Cap table", [POOL])
    assert e.value.code == "FORM_REPLY_UNMATCHED"


def test_free_text_unlike_any_choice_is_the_value() -> None:
    parsed = fr.parse("Cap table — Option pool: a tenth of the shares, most of it granted", "Cap table", [POOL])
    assert parsed.answers == [("ct_option_pool", ["provide"], "a tenth of the shares, most of it granted")]
    parsed = fr.parse("Cap table — Option pool: No option pool", "Cap table", [POOL])
    assert parsed.answers == [("ct_option_pool", ["no_pool"], None)]
