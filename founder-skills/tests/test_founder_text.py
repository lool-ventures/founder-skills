"""Tests for the fleet's shared founder-facing text policy.

The policy exists because the same defect was found in four skills independently, and because the
naive rule ("no internal tokens") is WRONG for one of the four token types: it would delete
`safe_001` and cost a founder the ability to cross-reference their own SAFE. Each test below pins one
type's behaviour, so a change to the policy must break a test rather than silently re-render every
report in the fleet.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "founder-skills" / "scripts"))

import _founder_text as ft  # noqa: E402

# --- type 1: private enums -> humanize ---------------------------------------


def test_private_enums_are_humanized() -> None:
    assert ft.humanize_token("partially_supported") == "Partially supported"
    assert ft.humanize_token("more_diligence") == "More diligence"


def test_enums_whose_plain_form_reads_wrong_have_overrides() -> None:
    """`pass` is the trap 0.6.0 already fixed semantically: a bare 'Pass' reads as approval and means
    the opposite."""
    assert ft.humanize_token("pass") == "Decline"
    assert ft.humanize_token("hard_pass") == "Decline — hard pass"
    assert ft.humanize_token("purpose_traction") == "Purpose / traction"


# --- type 2: field names -> humanize ----------------------------------------


def test_field_names_are_humanized() -> None:
    assert ft.humanize_token("evidence_source") == "Evidence source"
    assert ft.humanize_token("switching_costs") == "Switching costs"


def test_acronyms_keep_their_casing() -> None:
    assert ft.humanize_token("safe_price") == "SAFE price"
    assert ft.humanize_token("target_arpu") == "Target ARPU"


# --- type 3: stable public identifiers -> KEEP ------------------------------


def test_identifiers_are_never_rewritten() -> None:
    """This is the case the naive 'no internal tokens' rule gets wrong. `safe_001` is traceability:
    the founder matches it against their own instrument. Humanizing it harms them."""
    for ident in ("safe_001", "note_002", "holder_014"):
        assert ft.is_verbatim_token(ident), ident
        assert ft.humanize_token(ident) == ident


def test_identifiers_survive_substitution_in_prose() -> None:
    line = "- safe_001: 5.0% cap-implied (safe_price $0.4545)"
    out = ft.substitute(line)
    assert "safe_001" in out, "the identifier must survive"
    assert "SAFE price" in out, "the field name beside it must still be humanized"


# --- type 4: diagnostic codes -> KEEP ---------------------------------------


def test_declared_diagnostic_codes_are_kept() -> None:
    assert ft.is_verbatim_token("ai_claimed_unverified")
    assert ft.substitute("shows no AI-core evidence (ai_claimed_unverified)").endswith("(ai_claimed_unverified)")


def test_an_undeclared_code_is_treated_as_an_enum() -> None:
    """The safe default: a humanized diagnostic is merely less greppable, while an unrendered enum is
    unreadable. So an unlisted code is humanized rather than passed through."""
    assert not ft.is_verbatim_token("some_undeclared_code")
    assert ft.humanize_token("some_undeclared_code") == "Some undeclared code"


# --- the detector ------------------------------------------------------------


def test_scan_finds_tokens_regardless_of_markdown_shape() -> None:
    """The reason this matches TOKENS, not markdown: an earlier regex matched `**Label:** value` and
    missed `**Label**: value`; the corrected one missed the first. Two regexes, two different single
    hits, neither catching both."""
    for line in (
        "**Consensus Verdict:** more_diligence",
        "- **Serviceable %**: partially_supported (1 source)",
        "| SOM | $141.8M | Bottom-up | agent_estimate |",
    ):
        assert ft.scan(line)["enums"], f"missed: {line}"


def test_scan_separates_filenames_from_enums() -> None:
    """A filename is a different fix: drop the reference, do not rename it."""
    found = ft.scan("Optional artifact missing: model_data.json")
    assert found["filenames"] == ["model_data.json"]
    assert "model_data" not in found["enums"], "a filename must not double-report as an enum"


def test_scan_is_clean_on_already_humanized_text() -> None:
    assert ft.scan("- **Verdict:** Partially holds") == {"enums": [], "filenames": []}


def test_substitute_does_not_rewrite_filenames() -> None:
    out = ft.substitute("see model_data.json")
    assert "model_data.json" in out


def test_substitute_handles_a_token_that_prefixes_another() -> None:
    """Longest-first ordering: `evidence_source` must not be half-replaced by `evidence`."""
    out = ft.substitute("evidence_source and evidence_source_detail differ")
    assert out == "evidence source and evidence source detail differ"


# ---------------------------------------------------------------------------
# Dot-namespaced identifiers (cap-table's rule ids)
# ---------------------------------------------------------------------------


def test_scan_ignores_dot_namespaced_rule_ids() -> None:
    """cap-table's 85 rule ids are dotted and deliberately verbatim — counsel cites them.

    Without the namespacing guard the scanner reports every one as a violation, which is how a
    detector becomes noise nobody reads.
    """
    found = ft.scan("Per `safe.post_money_cap_conversion` the cap binds.")
    assert found["enums"] == []


def test_substitute_leaves_dot_namespaced_rule_ids_intact() -> None:
    text = "see safe.post_money_cap_conversion and convertible_notes.accrued_interest"
    assert ft.substitute(text) == text


def test_scan_still_catches_a_sentence_final_token() -> None:
    """The namespacing guard must not swallow a token that merely ends a sentence.

    A blunter `(?![\\w.])` trailing guard excludes both, silently losing this case.
    """
    assert ft.scan("the field is switching_costs.")["enums"] == ["switching_costs"]


def test_substitute_rewrites_a_sentence_final_token() -> None:
    assert ft.substitute("the field is switching_costs.") == "the field is switching costs."


# ---------------------------------------------------------------------------
# Capitalization is decided by TYPE, not position
# ---------------------------------------------------------------------------


def test_enum_values_capitalize_but_field_names_do_not() -> None:
    """`**X**: partially_supported` and `supports: customer_count` are the same markdown shape.

    Position cannot tell them apart; type can. Getting this wrong put lowercase verdicts in
    ic-sim's headline lines (`### Operator: more diligence`).
    """
    assert ft.substitute("- **Serviceable %**: partially_supported") == "- **Serviceable %**: Partially supported"
    assert ft.substitute("— supports: customer_count") == "— supports: customer count"


def test_known_verdict_enums_capitalize_in_headings() -> None:
    assert ft.substitute("### Operator: more_diligence") == "### Operator: More diligence"
    assert ft.substitute("**Consensus Verdict:** more_diligence") == "**Consensus Verdict:** More diligence"


def test_enum_value_list_failure_is_cosmetic_not_a_detection_hole() -> None:
    """An unlisted enum must still be SUBSTITUTED (lowercase) and still be SCANNED."""
    assert "made up state" in ft.substitute("status is made_up_state")
    assert ft.scan("status is made_up_state")["enums"] == ["made_up_state"]


# ---------------------------------------------------------------------------
# extra_keep parity between scan and substitute
# ---------------------------------------------------------------------------


def test_scan_honours_extra_keep_so_a_kept_token_is_not_warned_about() -> None:
    """cap-table keeps its own glossed vocabulary; warning about it trains readers to ignore warnings."""
    keep = frozenset({"structural_only"})
    text = "**Stage:** Structure only — no priced round yet (`structural_only`)"
    assert ft.substitute(text, extra_keep=keep) == text
    assert ft.scan(text, extra_keep=keep)["enums"] == []
    # ...and without the keep-set it IS reported, so the test is not vacuous.
    assert ft.scan(text)["enums"] == ["structural_only"]


# ---------------------------------------------------------------------------
# identifier_values is cap-table-only
# ---------------------------------------------------------------------------


def test_identifier_values_does_not_harvest_map_keys_by_default() -> None:
    """A metrics map is keyed by FIELD NAME, not by id; keeping those leaves our vocabulary in place."""
    doc = {"metrics": {"gross_margin": {"value": 0.75}, "cac_payback": {"value": 9}}}
    assert ft.identifier_values(doc) == frozenset()
    assert "gross_margin" in ft.identifier_values(doc, include_map_keys=True)


def test_an_id_field_holding_a_field_name_is_still_harvested_which_is_why_callers_must_opt_in() -> None:
    """Documents the hazard rather than pretending the helper can tell the difference.

    financial-model-review names a metric with `id`. The helper cannot distinguish that from a
    traceability handle, so the decision belongs to the caller: only cap-table uses it.
    """
    fmr_shaped = {"metrics": [{"id": "gross_margin", "value": 0.75}]}
    assert "gross_margin" in ft.identifier_values(fmr_shaped)


def test_keeping_a_token_also_silences_the_scan() -> None:
    """Why over-keeping is not the safe direction: the warning disappears with the substitution."""
    keep = frozenset({"gross_margin"})
    text = "ARPU $500 x gross_margin 0.75"
    assert ft.substitute(text, extra_keep=keep) == text
    assert ft.scan(text, extra_keep=keep)["enums"] == []
    assert ft.scan(text)["enums"] == ["gross_margin"]


# ---------------------------------------------------------------------------
# Internal vs founder-supplied filenames
# ---------------------------------------------------------------------------


def test_a_founder_supplied_filename_is_not_reported() -> None:
    """The founder's own upload is legitimately nameable; flagging it trains readers to ignore warnings."""
    text = "Source file is named 'sample_model.xlsx' — a generic filename that suggests a template."
    assert ft.scan(text)["filenames"] == []


def test_our_own_artifact_filenames_are_still_reported() -> None:
    assert ft.scan("inputs.json reports actuals separated: false")["filenames"] == ["inputs.json"]
    assert ft.scan("run explore.py first")["filenames"] == ["explore.py"]
