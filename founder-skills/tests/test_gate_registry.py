"""The gate registry: its shape, its published contract, and its agreement with each skill's own text.

Gate ids, option ids, default reasons and codes are contract for hosts, so the registry is held to the
contract file byte for byte, and its structural rules (index 0 terminal, at most four choices shown,
which gates a hook checks, which are bound) are pinned here. Labels are presentation, but the places a
skill already spells them (deck-review's gate options, market-sizing's revision answers, cap-table's Gate
Catalog and its interest-rate enum) must agree with the registry, so a change on either side is a
deliberate edit of both.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "founder-skills"
SCRIPTS = PLUGIN / "scripts"
SKILLS = PLUGIN / "skills"
CONTRACT = PLUGIN / "data" / "host-contract.json"

sys.path.append(str(SCRIPTS))
import _gates  # type: ignore[import-not-found]  # noqa: E402

GATES = _gates.GATES


def _options(g: dict[str, Any]) -> list[list[dict[str, Any]]]:
    opts = g["options"]
    return [list(t) for t in opts.values()] if isinstance(opts, dict) else [list(opts)]


def _load_skill_module(skill: str, name: str) -> Any:
    scripts = str(SKILLS / skill / "scripts")
    sys.path.insert(0, scripts)
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"{name}_under_registry_test", Path(scripts) / f"{name}.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(scripts)


# --- shape -----------------------------------------------------------------------------------------


def test_there_are_59_gates() -> None:
    assert len(GATES) == 59


def test_the_contract_file_is_the_registry() -> None:
    assert CONTRACT.read_text(encoding="utf-8") == _gates.contract_text(), (
        "data/host-contract.json is out of date: regenerate it with "
        "`python3 founder-skills/scripts/_gates.py --dump-contract`"
    )


def test_the_registry_validates() -> None:
    assert _gates.validate_registry(GATES) == []


def test_option_ids_use_the_contract_charset() -> None:
    bad = [(gid, o["id"]) for gid, g in GATES.items() for t in _options(g) for o in t]
    assert [b for b in bad if not re.fullmatch(r"[a-z0-9_+.-]+", b[1])] == []


def test_at_most_four_choices_are_shown_per_question() -> None:
    for gid, g in GATES.items():
        variants = g["option_variants"]
        for opts in _options(g):
            ids = [o["id"] for o in opts]
            shown = {o["id"] for o in opts if o["shown"]}
            if variants:
                for v in variants:
                    assert set(v) <= set(ids), (gid, v)
                    assert len([i for i in v if i in shown]) <= 4, (gid, v)
            else:
                assert len(shown) <= 4, gid


def test_the_first_option_is_terminal_and_does_not_decline() -> None:
    for gid, g in GATES.items():
        for opts in _options(g):
            if not opts:
                continue
            if gid == "out_of_scope_choice":
                assert opts[0]["declines"], "out_of_scope_choice leads with its decline"
                continue
            assert opts[0]["terminal"] and not opts[0]["declines"], gid


def test_no_ask_defaults_never_decline_and_never_sit_on_a_mandatory_gate() -> None:
    for gid, g in GATES.items():
        default = g["no_ask_default"]
        if g["mandatory"] or gid == "ct_no_cap_base_fork":
            assert default is None, gid
        if default is None:
            continue
        option = next(o for t in _options(g) for o in t if o["id"] == default)
        assert not option["declines"], gid


def test_default_reasons_come_from_the_closed_list() -> None:
    for gid, g in GATES.items():
        for reason, _option in g["defaults"]:
            assert reason in _gates.DEFAULT_REASONS, (gid, reason)


def test_which_gates_a_hook_checks() -> None:
    since = {gid for gid, g in GATES.items() if g["asked_check"] == "since_invocation"}
    current = {gid for gid, g in GATES.items() if g["asked_check"] == "current_prompt"}
    assert since == {"ms_methodology", "fmr_extracted_values", "ic_decline_confirmation"}
    assert current == {"ms_two_figures"}
    assert {g["asked_check"] for g in GATES.values()} <= {"none", "since_invocation", "current_prompt"}


def test_which_gates_are_bound() -> None:
    bound = {gid for gid, g in GATES.items() if g["binds"] is not None}
    assert bound == {
        "ms_methodology",
        "ic_decline_confirmation",
        "ct_cap_base_confirmation",
        "cp_gate1_landscape",
        "fmr_extracted_values",
        "ct_extraction_confirmation",
    }
    assert {g["binds"] for g in GATES.values() if g["binds"]} == set(_gates.BINDERS)
    assert len(_gates.BINDERS) == 6


def test_only_the_cash_follow_up_reopens_a_complete_run() -> None:
    assert {gid for gid, g in GATES.items() if g["reopens_complete"]} == {"fmr_cash_followup"}


def test_every_writer_is_a_real_script() -> None:
    for gid, g in GATES.items():
        writer = g["writer"]
        if writer == "record_gate_answer.py":
            assert (SCRIPTS / writer).is_file()
        else:
            assert (SKILLS / g["skill"] / "scripts" / writer).is_file(), (gid, writer)


def test_effect_targets_exist() -> None:
    for gid, g in GATES.items():
        for opts in _options(g):
            for o in opts:
                for targets in (o["effects"] or {}).values():
                    for t in targets:
                        base, _, inst = t.partition(".")
                        assert base in GATES, (gid, o["id"], t)
                        if inst:
                            assert inst in (GATES[base]["instances"] or {}).get("static", ()), (gid, o["id"], t)


def test_gates_recorded_by_their_own_script() -> None:
    by_writer = {gid: g["writer"] for gid, g in GATES.items() if g["owed"] == "by_writer"}
    assert by_writer == {
        "stage_confirmation": "gate_state.py",
        "out_of_scope_choice": "gate_state.py",
        "stage_choice": "gate_state.py",
        "ms_revision": "record_revision_answer.py",
        "ct_lane3_blocker": "extract_cap_table.py",
    }
    others = {gid for gid, g in GATES.items() if g["writer"] != "record_gate_answer.py"}
    assert others == set(by_writer)


# Every registry name with no implementation yet. Each skill's wiring implements its own and shrinks
# this; growing it means a new gate whose check nobody wrote.
# Empty since cap-table's wiring (the last skill): every predicate, option source, binder and requires check is
# implemented. `GATE_NOT_WIRED` stays reachable for a future gate; its test patches a predicate out.
UNIMPLEMENTED: dict[str, list[str]] = {"predicates": [], "option_sources": [], "binders": [], "requires": []}


def test_the_unimplemented_set_is_pinned() -> None:
    assert _gates.unimplemented() == UNIMPLEMENTED


# --- agreement with each skill's own text ----------------------------------------------------------


def _labels(gid: str) -> list[str]:
    return [o["label"] for o in GATES[gid]["options"]]


def test_deck_review_gate_options_match() -> None:
    gs = _load_skill_module("deck-review", "gate_state")
    assert list(gs.CANONICAL_OPTIONS["stage_confirmation"]) == _labels("stage_confirmation")
    assert list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]) == _labels("out_of_scope_choice")
    assert gs.STAGE_LABELS == _gates.DR_STAGE_LABELS


def test_market_sizing_revision_answers_match() -> None:
    ra = _load_skill_module("market-sizing", "_revision_answer")
    assert list(ra.ANSWERS) == [o["id"] for o in GATES["ms_revision"]["options"]]


def test_cap_table_interest_rate_enum_matches() -> None:
    role_map = json.loads(
        (SKILLS / "cap-table" / "references" / "schemas" / "freeform-role-map.json").read_text(encoding="utf-8")
    )
    enums = [
        b["enum_fields"]["interest_rate_type"]
        for b in role_map["block_types"].values()
        if isinstance(b, dict) and "interest_rate_type" in (b.get("enum_fields") or {})
    ]
    assert enums, "the role map no longer carries the interest-rate enum"
    for enum in enums:
        assert enum == [o["id"] for o in GATES["ct_note_interest_type"]["options"]]


def test_ic_mode_labels_are_verbatim() -> None:
    assert _labels("ic_mode") == ["Interactive", "Auto-pilot"]


_CATALOG_ANCHOR = "**Gate Catalog — canonical phrasing"
_CTX_ROWS = {"company_name": "Company name", "stage": "Company stage", "sector": "Sector", "geography": "Geography"}


def _catalog() -> dict[str, list[str]]:
    lines = (SKILLS / "cap-table" / "SKILL.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_CATALOG_ANCHOR))
    rows: dict[str, list[str]] = {}
    i = start + 1
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    while i < len(lines) and lines[i].strip():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))]
        m = re.fullmatch(r"\*\*(.+)\*\*", cells[0])
        if m:
            rows[m.group(1)] = cells
        i += 1
    assert rows, "the Gate Catalog table was not found"
    return rows


def _row_question(cells: list[str]) -> str:
    q = cells[2]
    return q[q.index('"') + 1 : q.rindex('"')]


def _row_labels(cells: list[str]) -> list[str]:
    # `(→ `enum`)` annotations name the option ids, not labels.
    labels = re.findall(r"`([^`]+)`", re.sub(r"\(→[^)]*\)", "", cells[3]))
    if "RUNTIME-LABELLED" in cells[4]:
        labels = [lab for lab in labels if "<" not in lab]
    return labels


def _fixed(labels: list[str], runtime: bool) -> list[str]:
    return [lab for lab in labels if not (runtime and "<" in lab)]


def test_the_cap_table_catalog_matches_the_registry() -> None:
    rows = _catalog()
    checked = 0
    for gid, g in GATES.items():
        row = g["catalog_row"]
        if row is None:
            continue
        assert row in rows, f"{gid}: no catalog row {row!r}"
        cells = rows[row]
        assert _row_question(cells) == g["question"], gid
        runtime = "RUNTIME-LABELLED" in cells[4]
        assert _row_labels(cells) == _fixed(_labels(gid), runtime), gid
        checked += 1
    assert checked >= 15
    assert "Founder-only fact gates (general shape)" in rows


@pytest.mark.parametrize("instance", sorted(_CTX_ROWS))
def test_the_company_context_rows_match_ctx_basics(instance: str) -> None:
    cells = _catalog()[_CTX_ROWS[instance]]
    g = GATES["ctx_basics"]
    assert _row_question(cells) == g["question"][instance]
    runtime = "RUNTIME-LABELLED" in cells[4]
    shared = [o["label"] for o in g["options"][instance] if o["only_skills"] is None]
    assert _row_labels(cells) == _fixed(shared, runtime)


# --- the loader fails closed -----------------------------------------------------------------------

_COPIED = ("_gates.py", "_run_status.py", "_form_reply.py", "run_status.py", "record_gate_answer.py")


def _copy(tmp: Path) -> Path:
    scripts = tmp / "plugin" / "scripts"
    scripts.mkdir(parents=True)
    for name in _COPIED:
        shutil.copy(SCRIPTS / name, scripts / name)
    return scripts


def _assert_unreachable(scripts: Path, tmp: Path) -> None:
    for argv in (
        [str(scripts / "record_gate_answer.py"), "list"],
        [str(scripts / "run_status.py"), "show", "--run-id", "r1", "--artifacts-root", str(tmp / "artifacts")],
    ):
        proc = subprocess.run([sys.executable, *argv], capture_output=True, text=True)
        assert proc.returncode == 2, (argv[0], proc.stdout, proc.stderr)
        assert json.loads(proc.stdout)["code"] == "REGISTRY_UNREACHABLE", proc.stdout


def test_an_inconsistent_registry_is_unreachable(tmp_path: Path) -> None:
    scripts = _copy(tmp_path)
    path = scripts / "_gates.py"
    text = path.read_text(encoding="utf-8")
    hook = "\n_load_checked()\n"
    assert text.count(hook) == 1
    bad = '\nGATES["zz_bad"] = dict(GATES["ic_mode"], writer="nope.py")\n'
    path.write_text(text.replace(hook, bad + hook), encoding="utf-8")
    _assert_unreachable(scripts, tmp_path)


def test_a_missing_registry_is_unreachable(tmp_path: Path) -> None:
    scripts = _copy(tmp_path)
    (scripts / "_gates.py").unlink()
    _assert_unreachable(scripts, tmp_path)


# --- effects, defaults and the published contract -------------------------------------------------


def test_an_effect_names_a_gate_with_instances_only_by_one_static_instance() -> None:
    """A gate with instances is opened per instance by its own site; an effect could only open it bare, so
    it names one static instance (`gate.instance`) or none of that gate."""
    for gid, g in GATES.items():
        for opts in _options(g):
            for o in opts:
                for targets in (o["effects"] or {}).values():
                    for t in targets:
                        assert t in GATES and GATES[t]["instances"] is None or "." in t, (gid, o["id"], t)
    for target in ("fmr_cash_basics", "fmr_cash_basics.not_an_instance"):
        bad_gates = dict(GATES)
        bad_gates["fmr_cash_followup"] = dict(GATES["fmr_cash_followup"])
        opt = dict(GATES["fmr_cash_followup"]["options"][0], effects={"reopens": (target,)})
        bad_gates["fmr_cash_followup"]["options"] = (opt,)
        assert _gates.validate_registry(bad_gates), target
    bad = dict(GATES)
    bad["ms_methodology"] = dict(GATES["ms_methodology"])
    looks = dict(GATES["ms_methodology"]["options"][0], effects={"opens": ("ms_correct_data",)})
    bad["ms_methodology"]["options"] = (looks, *GATES["ms_methodology"]["options"][1:])
    assert any("has instances" in p for p in _gates.validate_registry(bad))


def test_cap_table_defaults_are_the_producers_own() -> None:
    """A cap-table gate's default is what its producer does with the value absent, disclosed as such."""
    expected = {
        "ct_note_interest_type": "fixed_numeric",
        "ct_note_interest_converts": "yes",
        "ct_note_maturity_default": "convert_at_cap",
        "ct_note_qualified_threshold": "same_as_round",
        "ct_pool_basis": "pre_money",
    }
    for gid, option in expected.items():
        defaults = dict(GATES[gid]["defaults"])
        assert GATES[gid]["no_ask_default"] == option, gid
        assert defaults["producer_default_disclosed"] == option, gid
    # The pool basis: a question asked and left unanswered takes the first option; never asked, pre-money.
    pool = dict(GATES["ct_pool_basis"]["defaults"])
    assert pool["asked_unanswered"] == GATES["ct_pool_basis"]["options"][0]["id"] == "post_money"
    assert {gid for gid, g in GATES.items() if "asked_unanswered" in dict(g["defaults"])} == {"ct_pool_basis"}


def test_the_published_gate_shape_is_host_fields_only() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for gid, g in data["gates"].items():
        assert set(g) == set(_gates.PUBLIC_GATE_FIELDS), gid
        options = g["options"].values() if isinstance(g["options"], dict) else [g["options"]]
        for opts in options:
            for o in opts:
                assert set(o) == set(_gates.PUBLIC_OPTION_FIELDS), (gid, o)
    text = CONTRACT.read_text(encoding="utf-8")
    for internal in ('"owed"', '"writer"', '"option_source"', '"catalog_row"', '"effects"', '"binds"', '"discloses"'):
        assert internal not in text, internal


def test_the_contract_defines_the_waiting_shapes_and_every_state() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert {"needs_input", "blocked_by_gate"} <= set(data["shapes"])
    assert "not_reached" in data["gate_states"]
    for code in ("GATE_UNANSWERED", "OUT_OF_SCOPE_UNANSWERED", "AUTO_SATISFY_NOT_ALLOWED"):
        assert code in data["status_codes"]["waiting"]
    assert "INPUT_MISSING" in data["status_codes"]["refused"]
    for code in ("GATE_INVALID", "GATE_OTHER_RUN", "PROFILE_MISMATCH", "GATE_UNRESOLVED", "COACHING_BLOCKED"):
        assert code in data["last_error_codes"]


_HTML_WRITERS = [
    SKILLS / skill / "scripts" / script
    for skill, script in (
        ("deck-review", "visualize.py"),
        ("market-sizing", "visualize.py"),
        ("ic-sim", "visualize.py"),
        ("financial-model-review", "visualize.py"),
        ("competitive-positioning", "visualize.py"),
        ("cap-table", "visualize.py"),
        ("financial-model-review", "explore.py"),
        ("competitive-positioning", "explore.py"),
        ("cap-table", "explore.py"),
    )
]
# Every file this change made an emitter of run-status or gate codes.
_CODE_SOURCES = [
    SCRIPTS / "_gates.py",
    SCRIPTS / "_run_status.py",
    SCRIPTS / "run_status.py",
    SCRIPTS / "record_gate_answer.py",
    SCRIPTS / "_form_reply.py",
    SKILLS / "deck-review" / "scripts" / "_run_ref.py",
    SCRIPTS / "founder_context.py",
    SCRIPTS / "insert_coaching.py",
    SKILLS / "deck-review" / "scripts" / "gate_state.py",
    SKILLS / "deck-review" / "scripts" / "compose_report.py",
    SKILLS / "financial-model-review" / "scripts" / "_fmr_gates.py",
    SKILLS / "financial-model-review" / "scripts" / "compose_report.py",
    SKILLS / "market-sizing" / "scripts" / "record_revision_answer.py",
    SKILLS / "market-sizing" / "scripts" / "_ms_gates.py",
    SKILLS / "ic-sim" / "scripts" / "_ic_gates.py",
    SKILLS / "ic-sim" / "scripts" / "compose_report.py",
    SKILLS / "ic-sim" / "scripts" / "fund_profile.py",
    SKILLS / "cap-table" / "scripts" / "extract_cap_table.py",
    SKILLS / "competitive-positioning" / "scripts" / "_cp_gates.py",
    SKILLS / "competitive-positioning" / "scripts" / "compose_report.py",
    SKILLS / "competitive-positioning" / "scripts" / "cp_dispatch_prompt.py",
    *_HTML_WRITERS,
]
_Q = r"""['"]"""
# Where a code is emitted: a rejection or error class, a refusal helper, a `code` field, or a status set.
_EMITTERS = [
    re.compile(
        r"\b(?:GateRejection|RunStatusError|LedgerUnavailable|FormReplyError|_unreachable|_print_only|_refuse)"
        r"\(\s*(?:paths,\s*)?" + _Q + r"([A-Z][A-Z0-9_]+)" + _Q
    ),
    re.compile(_Q + r"code" + _Q + r"\s*:\s*" + _Q + r"([A-Z][A-Z0-9_]+)" + _Q),
    re.compile(r"\bset_state\(\s*\w+,\s*" + _Q + r"\w+" + _Q + r",\s*" + _Q + r"([A-Z][A-Z0-9_]+)" + _Q),
    # deck-review's `Authorization(..., code="...")`: the stable code each stage-gate refusal carries.
    re.compile(r"\bcode\s*=\s*" + _Q + r"([A-Z][A-Z0-9_]+)" + _Q),
]


def emitted_codes(text: str) -> set[str]:
    """The run-status and gate codes `text` emits. Producer codes (`E_…`, `W_…`) are another namespace."""
    found = {m for rx in _EMITTERS for m in rx.findall(text)}
    return {c for c in found if not c.startswith(("E_", "W_"))}


def _contract_codes(data: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for key in (
        "status_codes",
        "last_error_codes",
        "print_only_codes",
        "rejection_codes",
        "unreachable_codes",
        "cli_codes",
    ):
        walk(data[key])
    return found


def test_every_code_a_script_can_print_is_in_the_contract() -> None:
    published = _contract_codes(json.loads(CONTRACT.read_text(encoding="utf-8")))
    emitted: set[str] = set()
    for path in _CODE_SOURCES:
        emitted |= emitted_codes(path.read_text(encoding="utf-8"))
    assert "RUN_ID_MISMATCH" in emitted and "GATE_RECORD_MISMATCH" in emitted, "the scan found nothing"
    assert sorted(emitted - published) == []


def test_the_code_scan_sees_either_quote(tmp_path: Path) -> None:
    """Held on a scratch copy: a code added in single quotes, in either emitter shape, is caught."""
    copy = tmp_path / "record_gate_answer.py"
    text = (SCRIPTS / "record_gate_answer.py").read_text(encoding="utf-8")
    text += "\n\ndef _x():\n    raise _gates.GateRejection('FAKE_SINGLE_QUOTED', 'x')\n"
    text += "\n\nY = {'code': 'FAKE_FIELD_CODE'}\n"
    text += "\n\nZ = Authorization(False, 'x', code='FAKE_KEYWORD_CODE')\n"
    copy.write_text(text, encoding="utf-8")
    found = emitted_codes(copy.read_text(encoding="utf-8"))
    assert {"FAKE_SINGLE_QUOTED", "FAKE_FIELD_CODE", "FAKE_KEYWORD_CODE"} <= found
    published = _contract_codes(json.loads(CONTRACT.read_text(encoding="utf-8")))
    assert {"FAKE_SINGLE_QUOTED", "FAKE_FIELD_CODE", "FAKE_KEYWORD_CODE"} & published == set()


def test_every_stage_gate_refusal_code_is_seen_by_the_scan() -> None:
    """Each of `authorize()`'s sixteen refusals carries a code the scan reads, so a new one cannot ship
    outside the contract."""
    text = (SKILLS / "deck-review" / "scripts" / "gate_state.py").read_text(encoding="utf-8")
    sites = re.findall(r"\bcode=\"([A-Z_]+)\"", text)
    assert len(sites) == 16, sites
    assert set(sites) <= emitted_codes(text)


def test_an_option_offered_by_some_skills_says_which() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    name = {o["id"]: o for o in data["gates"]["ctx_basics"]["options"]["company_name"]}
    assert name["use_model_file"]["only_skills"] == ["financial-model-review"]
    assert name["working_title"]["only_skills"] is None


# Wording no skill's own text carries yet: questions the skill asks in prose, and labels marked new. Each
# skill's wiring commit either matches an entry to its SKILL.md or keeps it here deliberately.
# financial-model-review (wired): Step 3.6 asks the registry's question with its three shown labels, so those
# left the list. Kept deliberately: `corrections_applied` (hidden; a host's or the recorder's word), the cash
# questions and `stated` (asked from the printed `needs_input`), and the cash follow-up (the closer's own
# sentence asks for the balance; the reply is recorded as `provided`).
# ic-sim (wired): Mode Selection asks the registry's mode and fund questions with their labels, so those three
# left the list; the decline question and its labels were already in its text.
# deck-review (wired): its text names `A different company` and `Stop the review`, so those two left the
# list. The rest of its entries and the shared ones stay deliberately: the model asks those questions from
# the `needs_input` block a script prints, so SKILL.md need not carry their words.
NEW_WORDING = {
    ("ctx_select_company", "question"),
    ("ctx_stage_detail", "question"),
    ("dr_primary_deck", "question"),
    ("dr_primary_deck", "named"),
    ("stage_choice", "question"),
    ("dr_input_request", "question.wrong_file_type"),
    ("dr_input_request", "question.gated_link"),
    ("dr_input_request", "question.no_uploads_mount"),
    ("dr_input_request", "question.pdf_unreadable"),
    ("dr_input_request", "question.copy_failed"),
    ("dr_input_request", "provide"),
    ("ms_two_figures", "question"),
    ("ms_two_figures", "typed"),
    ("ms_methodology_change", "question"),
    ("ms_correct_data", "question"),
    ("ms_correct_data", "set"),
    ("ms_fx_rate", "question"),
    ("ms_fx_rate", "give_rate"),
    ("ms_fx_rate", "size_in_source_currency"),
    ("ms_input_period", "question"),
    ("ms_pct_scale", "question"),
    ("ms_revision", "question"),
    ("ms_revision_changes", "question"),
    ("ms_upload_path", "question"),
    ("ms_upload_path", "provide"),
    ("ms_upload_path", "review_without_documents"),
    ("fmr_cash_basics", "question.current_balance"),
    ("fmr_cash_basics", "question.balance_date"),
    ("fmr_cash_basics", "question.monthly_burn"),
    ("fmr_cash_basics", "stated"),
    ("fmr_extracted_values", "corrections_applied"),
    ("fmr_cash_followup", "question"),
    ("fmr_cash_followup", "provided"),
    ("cp_product_profile", "question.product"),
    ("cp_product_profile", "question.customers"),
    ("cp_product_profile", "question.differentiation"),
    ("cp_product_profile", "use_derived"),
    ("cp_product_profile", "describe_in_chat"),
    ("cp_research_pick", "question"),
    ("cp_scoring_basis", "question"),
    ("cp_consolidation_merge", "keep_separate"),
    ("cp_merge_pick", "question"),
    ("cp_upload_path", "question"),
    ("cp_upload_path", "provide"),
    ("cp_upload_path", "review_without_documents"),
    ("ct_pool_basis_remedy", "question.custom"),
    ("ct_pool_basis_remedy", "question.excluding"),
    ("ct_pool_basis_remedy", "custom.state_measure"),
    ("ct_pool_basis_remedy", "excluding.show_post_money"),
    ("ct_pool_basis_remedy", "excluding.keep_refused"),
    ("ct_extraction_confirmation", "question"),
    ("ct_extraction_confirmation", "values_ok"),
    ("ct_founder_fact", "question"),
    ("ct_founder_fact", "stated"),
    ("ct_lane1_counsel_review", "question"),
    ("ct_lane1_counsel_review", "stated"),
    ("ct_lane2_column_mapping", "question"),
    ("ct_lane2_column_mapping", "stated"),
    ("ct_lane3_blocker", "question"),
    ("ct_lane3_blocker", "stated"),
    ("ct_rule_lookup_fact", "question"),
    ("ct_rule_lookup_fact", "provide"),
    ("ct_rule_lookup_fact", "unknown"),
}


def _skill_text(skill: str) -> str:
    import _form_reply  # type: ignore[import-not-found]

    names = list(_gates.SKILLS) if skill == _gates.SHARED else [skill]
    parts = []
    for name in names:
        for f in sorted((SKILLS / name).rglob("*")):
            if f.suffix in (".md", ".py") and f.name != "_run_ref.py" and "__pycache__" not in f.parts:
                parts.append(f.read_text(encoding="utf-8"))
        agent = PLUGIN / "agents" / f"{name}.md"
        if agent.exists():
            parts.append(agent.read_text(encoding="utf-8"))
    normalised: str = _form_reply.normalise("\n".join(parts))
    return normalised


def test_wording_not_in_any_skills_text_is_listed() -> None:
    """Every question and label is either in its skill's own text (whitespace, dashes, quotes and case
    aside) or listed in NEW_WORDING; the list cannot grow or shrink silently."""
    import _form_reply  # type: ignore[import-not-found]

    texts: dict[str, str] = {}
    missing = set()
    for gid, g in GATES.items():
        text = texts.setdefault(g["skill"], _skill_text(g["skill"]))
        questions = g["question"].items() if isinstance(g["question"], dict) else [(None, g["question"])]
        for inst, q in questions:
            if _form_reply.normalise(q) not in text:
                missing.add((gid, "question" if inst is None else f"question.{inst}"))
        opts = g["options"].items() if isinstance(g["options"], dict) else [(None, g["options"])]
        for inst, group in opts:
            for o in group:
                if _form_reply.normalise(o["label"]) not in text:
                    missing.add((gid, o["id"] if inst is None else f"{inst}.{o['id']}"))
    assert missing == NEW_WORDING


def test_the_contract_says_what_the_gate_list_holds_before_bind() -> None:
    notes = json.loads(CONTRACT.read_text(encoding="utf-8"))["notes"]
    assert any("Before `bind`" in n and "common to every mode" in n for n in notes)
