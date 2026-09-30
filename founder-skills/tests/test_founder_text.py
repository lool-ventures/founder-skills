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

import _founder_text as ft  # type: ignore[import-not-found]  # noqa: E402  # sys.path-injected above

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


def test_scan_is_blind_to_a_dotted_internal_path_and_that_is_the_price() -> None:
    """The INVERSE of the two tests above, recorded because the exemption has a cost nobody had written down.

    A rule id and an internal path are structurally identical to this regex -- `safe.post_money_cap_conversion`
    and `state.aoa_findings.dividend_provisions_present` differ only in meaning. So the guard that keeps
    counsel's citations verbatim ALSO makes every internal path invisible, to the scanner and the
    substituter alike. That is a deliberate trade, not an oversight, and it is the right one: the only
    precise discriminator is cap-table's rule pack, which has no business in a shared fleet module.

    WHAT THIS MEANS FOR YOU, if you are writing a renderer or a validation message: this policy will
    NOT catch `expenses.headcount[0].salary_monthly` or `cap_state.as_converted_totals.fully_diluted_shares`
    in text you send a founder. Two skills shipped exactly that -- financial-model-review's validation
    messages and cap-table's fast-assess remedies -- and no fleet scan saw either. Write the sentence
    for a human; do not rely on a substituter to rescue a JSON path.

    This test asserts the blindness so it cannot be "fixed" by accident. If you widen the regex, this
    test fails and you must first answer what happens to the legal citations.
    """
    path = "state.aoa_findings.dividend_provisions_present"
    assert ft.scan(f"Use when the {path} is true.")["enums"] == [], (
        "the scanner now sees dotted paths -- which also means it sees dotted RULE IDS. Check what "
        "substitute() does to a counsel citation before keeping this change."
    )
    assert ft.substitute(path) == path


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


def test_internal_file_detection_is_by_extension_not_a_name_list() -> None:
    """A name list cannot be kept current: 53 of the fleet's 82 artifact stems were missing from one,
    including `moat_scores.json`, which a live run cited and the scan waved through."""
    for ours in ("moat_scores.json", "landscape_draft.json", "competitor_recall_output.json", "explore.py"):
        assert ft.scan(f"see {ours}")["filenames"] == [ours], ours


def test_founder_document_formats_are_never_reported() -> None:
    for theirs in ("sample_model.xlsx", "my_model.csv", "deck.pdf", "terms.docx"):
        assert ft.scan(f"the file {theirs} looks like a template")["filenames"] == [], theirs


def test_a_url_path_segment_is_not_an_internal_file() -> None:
    """Source citations legitimately end in `.html`. Flagging them blocked a correctly-cited report at
    error severity in a live artifact."""
    text = "See https://www.globenewswire.com/news/housecall-pro-appoints-chief-executive-officer.html"
    assert ft.scan(text)["filenames"] == []


def test_an_internal_file_beside_a_url_is_still_reported() -> None:
    text = "inputs.json reports x; source https://example.com/a/page.html"
    assert ft.scan(text)["filenames"] == ["inputs.json"]


# ---------------------------------------------------------------------------
# ALLCAPS — the class the lowercase rule is blind to by construction
# ---------------------------------------------------------------------------


def test_shouting_internal_tokens_are_detected() -> None:
    """Measured in delivered reports while every detector reported clean."""
    for token in ("NICE_TO_HAVE", "FUND_PROFILE", "CONFLICT_CHECK", "NARR_01", "UNVALIDATED_CLAIMS"):
        assert ft.scan(f"see {token} here")["enums"] == [token], token


def test_founder_known_acronyms_are_not_flagged() -> None:
    """A bare acronym is something the founder knows; TAM_SAM is two of them."""
    for token in ("TAM", "SAM", "SOM", "ARPU", "QSBS", "USD", "TAM_SAM"):
        assert ft.scan(f"the {token} figure")["enums"] == [], token


def test_a_partly_acronym_token_is_still_flagged() -> None:
    assert ft.scan("TAM_DISCREPANCY fired")["enums"] == ["TAM_DISCREPANCY"]


def test_shouting_tokens_are_detect_only_never_rewritten() -> None:
    """Rewriting is wrong for two of the three things an ALLCAPS token can be: an id (`NARR_01` ->
    "NARR 01" helps nobody) and a code shown beside its own humanized label (the md_term convention,
    e.g. `**Burn Multiple Suspect** (`BURN_MULTIPLE_SUSPECT`)`). Leaks are fixed at the source."""
    for token in ("NARR_01", "BURN_MULTIPLE_SUSPECT", "NICE_TO_HAVE"):
        assert ft.substitute(token) == token, token


def test_a_kept_code_is_not_reported() -> None:
    """Each compose passes its own WARNING_SEVERITY keys, which it renders beside a label on purpose."""
    keep = frozenset({"BURN_MULTIPLE_SUSPECT"})
    text = "- **Burn Multiple Suspect** (`BURN_MULTIPLE_SUSPECT`): acknowledged"
    assert ft.scan(text, extra_keep=keep)["enums"] == []
    assert ft.scan(text)["enums"] == ["BURN_MULTIPLE_SUSPECT"]


def test_urls_are_never_rewritten_but_prose_around_them_is() -> None:
    """A citation URL must reach the founder byte-exact.

    `substitute()` used to rewrite tokens wherever they appeared, including inside links:
    "…/press_release/exclusive_partnership" became "…/press release/exclusive partnership"
    and the founder got a dead citation for a claim the report was challenging. It reported
    CLEAN, because every call site runs scan() after substitute(), so the evidence was
    already gone. Fleet-wide — every skill that renders a source URL goes through here.
    """
    import _founder_text as ft

    url = "https://www.reuters.com/tech/press_release/exclusive_partnership-2024?utm_source=deck"
    out = ft.substitute(f"See {url} for the ai_core claim")
    assert url in out, "the URL must survive substitution unchanged"
    assert "ai_core" not in out, "prose outside the URL must still be humanized"
    assert "AI core" in out


def test_scan_does_not_report_url_path_segments_as_internal_tokens() -> None:
    """A slug in somebody else's URL is not a token of ours, and reporting it sends an
    author hunting for a leak that does not exist. The filename pass already stripped URLs;
    the enum pass read the raw text."""
    import _founder_text as ft

    found = ft.scan("Source: https://example.com/reports/model_data/ai_core_summary")
    assert found["enums"] == [] and found["filenames"] == []
    # and a real token in prose is still caught
    assert ft.scan("the ai_core flag was set")["enums"]


# ---------------------------------------------------------------------------
# Code spans — the author marked it literal, so the policy must not rewrite it
# ---------------------------------------------------------------------------
#
# Specimens live INSIDE the tests, both directions. Two earlier attempts at this fix were refuted by
# measurement rather than by review, and each refutation is a case below: a fenced block, a doubled
# span, and a stray backtick that INVERTED protection (leaked an unrelated token AND still corrupted
# the target). A matcher that regresses on any of them reds here rather than in a founder's report.

# The exact string that shipped, from `run_scenario.py`'s E_CAP_IMPLIED_NOTES_PRESENT remedy.
_SHIPPED_CORRUPTION = "Author a `priced_round` scenario (parameters `pre_money` / `new_money`) — that route converts."


def test_the_flag_is_off_by_default_so_no_existing_caller_moves() -> None:
    """Default OFF is load-bearing: `_rules.founder_text` feeds HTML TEXT NODES, where a backtick is a
    literal character rather than markup. Protecting there would hand a founder ``valuation_cap``
    where prose reads better, and `test_html_founder_text.py` scans those nodes with NO keep set."""
    assert ft.substitute(_SHIPPED_CORRUPTION) == (
        "Author a `priced round` scenario (parameters `pre money` / `new money`) — that route converts."
    )


def test_a_backticked_parameter_name_survives_when_protection_is_on() -> None:
    assert ft.substitute(_SHIPPED_CORRUPTION, protect_code_spans=True) == _SHIPPED_CORRUPTION


def test_bare_tokens_beside_a_code_span_are_still_humanized() -> None:
    """Protection is scoped to the span, not to the line. Without this the fix would be a licence to
    leak: one backtick anywhere and the rest of the sentence stops being policed."""
    assert ft.substitute("`pre_money` and bare pre_money", protect_code_spans=True) == (
        "`pre_money` and bare pre money"
    )


def test_a_fenced_block_is_protected_and_prose_after_it_is_not() -> None:
    out = ft.substitute("text\n```\npre_money\n```\nmore new_money here", protect_code_spans=True)
    assert "```\npre_money\n```" in out, "a fenced block was rewritten"
    assert "more new money here" in out, "prose after the fence stopped being humanized"


def test_a_doubled_span_protects_its_inner_backticks() -> None:
    """Equal-length matching: the outer pair is two backticks, so the single inner one cannot close
    it. Measured as a failure of the previous attempt's regex."""
    assert ft.substitute("see ``a `pre_money` b`` now", protect_code_spans=True) == "see ``a `pre_money` b`` now"


def test_a_stray_backtick_does_not_invert_protection() -> None:
    """The previous attempt's worst failure: an unmatched backtick both leaked an unrelated token and
    still corrupted the target. An unmatched run must protect NOTHING."""
    out = ft.substitute("a `pre_money` b ` c switching_costs", protect_code_spans=True)
    assert "`pre_money`" in out, "the matched span stopped being protected"
    assert "switching costs" in out, "a stray backtick silenced the policy for the rest of the line"


def test_an_unclosed_fence_protects_nothing() -> None:
    """Deliberate: protecting to end-of-document would let one stray fence silence the policy over the
    whole rest of a report. Failing toward the pre-flag behaviour is the smaller error."""
    assert ft.substitute("```\npre_money\nstill open", protect_code_spans=True) == "```\npre money\nstill open"


def test_scan_moves_with_substitute_or_the_warning_cannot_be_cleared() -> None:
    """The reason the previous attempt was rejected. Changing `substitute` alone manufactures a
    warning whose only remedy is to un-backtick — undoing the fix. Under the flag, a token the
    substitution deliberately preserved is not reported."""
    kept = ft.substitute(_SHIPPED_CORRUPTION, protect_code_spans=True)
    assert ft.scan(kept, protect_code_spans=True) == {"enums": [], "filenames": []}
    # ... and without the flag the same text IS reported, so the pair is not vacuously silent.
    assert ft.scan(kept)["enums"], "scan reports nothing even with protection off — the test proves nothing"


# --- the coaching insertion marker --------------------------------------------


def test_the_coaching_insertion_marker_is_not_a_leak_whatever_its_hex() -> None:
    """Every compose writes `<!-- COACHING_INSERTION_POINT_<8 hex> -->` for the coaching step to
    replace. The ALLCAPS rule needs every part uppercase, so a suffix with a hex letter never matched,
    and an all-digit one (about one run in forty-three) did: a spurious warning that the founder is
    shown and nobody can clear."""
    for marker in ("<!-- COACHING_INSERTION_POINT_12345678 -->", "<!-- COACHING_INSERTION_POINT_a1b2c3d4 -->"):
        assert ft.scan(f"# Report\n\n{marker}\n\nBody.")["enums"] == [], marker


def test_the_marker_exemption_is_the_marker_not_the_word() -> None:
    """Outside its comment the same token is prose, and prose carrying it IS a leak."""
    assert ft.scan("See COACHING_INSERTION_POINT_12345678 below.")["enums"] == ["COACHING_INSERTION_POINT_12345678"]


def test_the_check_record_declaration_beside_the_marker_is_not_a_leak() -> None:
    """cap-table's compose writes it beside the marker, and the same insert removes it; until then it is an HTML
    comment a founder never sees. Outside its comment the token is still prose."""
    decl = "<!-- COACHING_REQUIRES_CHECK_RECORD run_id=20260930T101500Z -->"
    assert ft.scan(f"# Report\n\n{decl}\n<!-- COACHING_INSERTION_POINT_12345678 -->\n\nBody.")["enums"] == []
    assert ft.scan("See COACHING_REQUIRES_CHECK_RECORD below.")["enums"] == ["COACHING_REQUIRES_CHECK_RECORD"]


# --- a segment that begins with a digit ---------------------------------------
#
# `_CANDIDATE_RE` required every segment after an underscore to begin with a LETTER, so a token with a
# numeric segment was never a candidate and reached founders raw. MEASURED on delivered pages: 49
# occurrences across 37 distinct tokens in one skill, every one inside sub-agent-authored prose (a `why`
# or a label). Widening detection alone would have broken tokens that are safe today, so the verbatim
# guard widened in the same change; these tests pin both halves.
#
# Coverage, stated so a green is not over-read: live-prose evidence exists for market-sizing only
# (41 delivered pages) plus competitive-positioning (6 pages, zero instances). deck-review, ic-sim,
# financial-model-review and cap-table have no kept delivered pages, so their behaviour is inferred from
# shape, not measured. Fixture-rendered pages for all six skills carry zero instances, which measures
# our PRODUCERS (clean fleet-wide) and not sub-agent prose, where the class actually lives.

# Minted ids, from the producers that mint them: `safe_{n:03d}`, `note_{n:03d}`, `warrant_{n:03d}`,
# `founder_{i:03d}`, `common_{n:03d}`, `sweep_{i:02d}`. The digit run is two or three wide, never four --
# which is exactly what separates an id from a year, and why the guard keys on WIDTH rather than on "a
# digit run follows a word". A naive suffixed-id guard would also protect `fy_2025_plan`.
_MUST_STAY_VERBATIM = {
    "stable id": ["safe_001", "note_002", "holder_014", "warrant_007"],
    "stable id with a suffix": ["safe_001_a", "note_002_mfn", "sweep_01_high"],
    "diagnostic code": ["E_NO_EQUITY_BASE", "W_STALE_ARTIFACT", "UNVALIDATED_CLAIMS", "TAM_DISCREPANCY"],
    "filename": ["inputs.json", "deck_v2.pdf", "model_2026.xlsx", "report_2026_09.html"],
    "date": ["2026-09-27", "20260927"],
    "version string": ["v0.13.0", "3.10.0", "v1_2_3"],
    "run id": ["20260927T080504Z"],
    "slide or page ref": ["slide_12", "page_7", "p_21"],
}

# A year inside a name does NOT make it a handle. A handle is recognised by an existing protection -- an
# id form, a code, a filename, a URL, or the caller's `extra_keep` -- never by guessing from a year.
_INTENDED_REPAIRS = [
    "q1_2026_actuals",
    "fy_2025_plan",
    "cohort_2024_retention",
    "total_beneficiaries_implied_2025",
    "deck_headline_slide_12",
    "active_buyers_april_2028",
]


def test_a_token_carrying_a_numeric_segment_is_humanized() -> None:
    """The defect: none of these was a candidate, so each reached the founder raw."""
    for token in _INTENDED_REPAIRS:
        sentence = f"Derived against {token} rather than a sourced rate."
        assert ft.substitute(sentence) != sentence, f"{token} was left raw"
        assert token not in ft.substitute(sentence), token


def test_widening_detection_did_not_break_what_must_stay_verbatim() -> None:
    """Every class the policy promises to leave alone, byte-identical after the widening.

    Each is safe TODAY; a detection-only widening broke the suffixed ids and the underscore version
    string, which is why the guard widened with it.
    """
    for cls, tokens in _MUST_STAY_VERBATIM.items():
        for token in tokens:
            sentence = f"The record lists {token} beside the figure."
            assert ft.substitute(sentence) == sentence, f"[{cls}] {token} was altered"


def test_the_widened_guard_engages_rather_than_the_pattern_simply_missing_them() -> None:
    """Positive control. A guard that protects by NOT MATCHING proves nothing about the guard.

    With the guard disabled, the suffixed ids and the underscore version string must be rewritten --
    i.e. the pattern really does reach them and the guard is what saves them. Without this, deleting the
    guard would leave this file green.
    """
    at_risk = ["safe_001_a", "note_002_mfn", "sweep_01_high", "v1_2_3"]
    original = ft.is_verbatim_token
    try:
        ft.is_verbatim_token = lambda token: token in ft.DIAGNOSTIC_CODES  # type: ignore[assignment]
        for token in at_risk:
            sentence = f"The record lists {token} beside the figure."
            assert ft.substitute(sentence) != sentence, (
                f"{token} is not reached by the pattern at all, so the guard is not what protects it "
                "and this test is vacuous"
            )
    finally:
        ft.is_verbatim_token = original  # type: ignore[assignment]
    # And with the guard restored they are safe again.
    for token in at_risk:
        sentence = f"The record lists {token} beside the figure."
        assert ft.substitute(sentence) == sentence, token
