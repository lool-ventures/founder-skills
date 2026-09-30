"""Where a founder's figure came from is said only when it can be checked.

A live run credited two deck figures to the founder's chat ("you gave it in chat") and called a
TAM the founder typed a "Deck Claim" -- on the table, in the warnings, in the narrative heading and,
through the coaching instructions, in the coaching. Every one was a label the renderer asserted
without looking: a model-written `source`, or one flag for the whole run ("a document was
uploaded, so every claim is the deck's"). A figure is now the founder's figure, which is true
wherever it came from, and a page is named only when the figure's own words are found on it.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
from test_market_sizing import (  # noqa: E402
    _CRUN,
    _VALID_CHECKLIST,
    _VALID_INPUTS,
    _VALID_METHODOLOGY,
    _VALID_SENSITIVITY,
    _VALID_SIZING,
    _VALID_VALIDATION,
    _compose_dir,
    _gated_dir,
    _make_artifact_dir,
    _pipe_review,
    _set_inputs,
    run_script_raw,
)

_SCRIPTS = _TESTS.parent / "skills" / "market-sizing" / "scripts"
_AGENT = _TESTS.parent / "agents" / "market-sizing.md"

# What the deck's page 2 says, as its OCR sidecar would carry it.
_PAGE_2 = (
    "UNIT ECONOMICS\n"
    "ONBOARDING (months 1-2) $317 per customer per month\n"
    "RENEWAL (month 3 on) n=13 customer-months -- $157 per customer per month\n"
    "Blended average rate across onboarding and renewal: $261 per customer per month\n"
)
_DECK_PHRASES = ("Deck Claim", "deck claim", "the deck's claim", "The deck stated", "Deck Claims")


def _both_pages(d: Path) -> tuple[str, str]:
    md = _compose_dir(d)["report_markdown"]
    rc, html_page, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0, err
    return md, html_page


def _with_sidecar(d: Path) -> None:
    ocr = d / "handoff" / _CRUN / "ocr"
    ocr.mkdir(parents=True)
    (ocr / "deck.pdf.p2.txt").write_text(_PAGE_2)
    (d / "handoff" / _CRUN / "docs").mkdir()


def _alternative(label: str, source: str = "document:deck.pdf#page=2") -> dict[str, Any]:
    return {"arpu": [{"value": 261, "period": "month", "source": source, "label": label}]}


def _set_stated(d: Path, alternatives: dict[str, Any], source: str = "chat") -> None:
    _set_inputs(
        d,
        founder_stated_inputs={"arpu": 157},
        founder_stated_inputs_period={"arpu": "month"},
        founder_stated_inputs_source={"arpu": source},
        founder_stated_alternatives=alternatives,
    )
    _pipe_review(d, "Something.")


# --- a founder's figure is theirs; a deck is named only where a page is ---------------------------


def test_a_stated_claim_is_never_credited_to_the_deck_on_either_page() -> None:
    """The measured shape: a TAM typed in chat, a deck uploaded, and every surface said "deck"."""
    inputs: dict[str, Any] = {**_VALID_INPUTS, "materials_provided": ["pitch deck"]}
    inputs["existing_claims"] = {"tam": 10_000_000_000, "sam": None, "som": 200_000_000}
    inputs["existing_claims_detail"] = {"note": "stated in conversation"}
    d = Path(
        _make_artifact_dir(
            {
                "inputs.json": inputs,
                "methodology.json": _VALID_METHODOLOGY,
                "validation.json": _VALID_VALIDATION,
                "sizing.json": _VALID_SIZING,
                "checklist.json": _VALID_CHECKLIST,
                "sensitivity.json": _VALID_SENSITIVITY,
            }
        )
    )
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        for phrase in _DECK_PHRASES:
            assert phrase not in page, phrase
        assert "Your Figure" in page
    assert "differs from the figure you stated" in md  # the >50% warning, reworded, still fires


def test_the_warning_label_the_coach_receives_does_not_say_deck() -> None:
    # _humanize_warning is inside the coaching payload's call graph, so this label reaches the coach.
    # Loaded by path: every skill has a compose_report.py, and a bare import gets whichever is cached.
    import importlib.util

    sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("ms_compose_report", _SCRIPTS / "compose_report.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "deck" not in module._humanize_warning("DECK_CLAIM_MISMATCH").lower()


def test_the_coaching_instructions_do_not_attribute_stated_figures_to_the_deck() -> None:
    """`deck_coverage.stated` lists the founder's stated TAM/SAM/SOM wherever they came from, and
    the coach was told to write "your deck stated {stated}" -- which is how a TAM typed in chat
    became "your own $12B TAM claim in the deck" in the commentary."""
    body = _AGENT.read_text(encoding="utf-8")
    assert "your deck stated" not in body.lower()


# --- a chat figure: nothing is claimed about where it was said ------------------------------------


def test_a_figure_labelled_chat_is_never_said_to_have_been_given_in_chat() -> None:
    """Nothing a script can read shows what the founder typed; the label is the model's word."""
    d = _gated_dir()
    _set_stated(d, _alternative("onboarding-period rate", source="chat"))
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        assert "in chat" not in page
        assert "You also gave ARPU $261.00 per month" in page


# --- a document figure: named only when its words are on that page -------------------------------


def test_a_document_figure_whose_words_are_on_the_page_names_the_page() -> None:
    d = _gated_dir()
    _with_sidecar(d)
    _set_stated(d, _alternative("Blended average rate across onboarding and renewal"))
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        assert "(from deck.pdf, page 2: Blended average rate across onboarding and renewal)" in page


def test_a_document_figure_whose_words_are_not_on_the_page_does_not_name_it() -> None:
    d = _gated_dir()
    _with_sidecar(d)
    _set_stated(d, _alternative("steady state recurring rate after the second month"))
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        assert "deck.pdf, page 2" not in page
        assert "in your materials" in page


def test_a_label_too_short_to_be_a_quote_does_not_name_the_page() -> None:
    # A three-word "quote" matches almost any page; the red team refuses under six words too.
    d = _gated_dir()
    _with_sidecar(d)
    _set_stated(d, _alternative("Blended average rate"))
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        assert "deck.pdf, page 2" not in page


def test_a_document_figure_with_no_page_text_on_disk_does_not_name_the_page() -> None:
    d = _gated_dir()
    _set_stated(d, _alternative("Blended average rate across onboarding and renewal"))
    md, _ = _both_pages(d)
    assert "deck.pdf, page 2" not in md


# --- a model-written list is rendered only in the shape the schema names -------------------------


def test_a_gate_default_that_is_not_a_phrase_is_counted_not_printed() -> None:
    """`gate_defaults` is string[]; a live run wrote objects, and both pages printed the Python repr
    -- `{'gate': 'step_2_3_confirm_methodology', 'reason': ...}` -- to the founder."""
    from test_market_sizing import _set_methodology

    d = _gated_dir()
    _set_methodology(
        d,
        gate_defaults=[
            "the revision question",
            {"gate": "step_2_3_confirm_methodology", "reason": "founder said no questions"},
            {"gate": "two_figures_for_arpu", "reason": "founder said no questions"},
        ],
    )
    _pipe_review(d, "Something.")
    md, html_page = _both_pages(d)
    for page in (md, html_page):
        assert "the revision question" in page
        assert "2 other questions" in page
        for leaked in ("step_2_3", "two_figures_for_arpu", "{'gate'", "&#x27;gate&#x27;"):
            assert leaked not in page, leaked


# --- one page reader, two copies that must not drift ----------------------------------------------


def _function_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.unparse(node)


def test_the_page_reader_matches_the_red_teams() -> None:
    """The report checks a founder's quote against a page the way the red team checks a finding's.
    red_team.py cannot import _view (its lone-scripts refusal), so the body is copied and pinned."""
    assert _function_source(_SCRIPTS / "_view.py", "_page_text") == _function_source(
        _SCRIPTS / "red_team.py", "_page_text"
    )


def test_the_payload_still_names_no_file_it_should_not() -> None:
    d = _gated_dir()
    _with_sidecar(d)
    _set_stated(d, _alternative("Blended average rate across onboarding and renewal"))
    payload = json.dumps(_compose_dir(d)["coaching_payload"])
    assert "Deck Claim" not in payload


# --- a change's reason has a home the founder, and the reviewer, never see ----------------------


def test_a_change_reason_reaches_neither_page_nor_the_payload() -> None:
    """After a revision a live run wrote its reason into the label -- "(set independently of the
    top-down segment %, to avoid mechanical convergence)" -- and the report printed it. Step 6d now
    gives the reason its own key on the approved change; this pins that no renderer prints it."""
    from test_market_sizing import _set_methodology

    d = _gated_dir()
    _pipe_review(d, "Something.")
    _set_methodology(
        d,
        red_team_revision={
            "approved_by_founder": True,
            "founder_words": "use independent estimates",
            "changes": [
                {
                    "field": "target_pct",
                    "from": 3,
                    "to": 5,
                    "reason": "set independently to avoid mechanical convergence",
                }
            ],
        },
    )
    _pipe_review(d, "The revised analysis.")
    data = _compose_dir(d)
    md, html_page = _both_pages(d)
    for text in (md, html_page, json.dumps(data["coaching_payload"])):
        assert "mechanical convergence" not in text


def test_the_reason_for_a_change_is_kept_where_the_reviewer_never_reads() -> None:
    """The reason lives on the approved change in methodology.json, not on the assumption: the red
    team's required reading includes validation.json, and a reason there would hand the constructor's
    account of its own revision to the review meant to escape it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ms_dispatch_prompt", _SCRIPTS / "dispatch_prompt.py")
    assert spec is not None and spec.loader is not None
    dispatch_prompt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatch_prompt)
    assert "methodology.json" not in dispatch_prompt.REQUIRED_ARTIFACTS
    skill = (_SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    step = skill[skill.index("### Step 6d") : skill.index("### Step 7")]
    assert '"reason"' in step and "change_reason" not in skill
    schemas = (_SCRIPTS.parent / "references" / "artifact-schemas.md").read_text(encoding="utf-8")
    row = next(line for line in schemas.splitlines() if line.startswith("| `red_team_revision` |"))
    assert '"reason"' in row and "change_reason" not in schemas


# --- a count the sizing derives is shown whole on the delivered pages -----------------------------


def test_a_derived_customer_count_is_whole_on_both_pages() -> None:
    """`6f18c77` made format_value show a COUNT whole, and its test called format_value with "count"
    directly. The live run after it still printed a fractional "Target Customers" count: target_customers is
    an output the sizing derives, it had no unit, and it fell through to the generic number format.
    So this goes through the report, not the helper."""
    sizing = json.loads(json.dumps(_VALID_SIZING))
    som = sizing["bottom_up"]["som"]
    som["inputs"]["target_customers"] = 1437.58
    sizing["bottom_up"]["sam"]["inputs"]["serviceable_customers"] = 14375.8
    d = Path(
        _make_artifact_dir(
            {
                "inputs.json": _VALID_INPUTS,
                "methodology.json": _VALID_METHODOLOGY,
                "validation.json": _VALID_VALIDATION,
                "sizing.json": sizing,
                "checklist.json": _VALID_CHECKLIST,
                "sensitivity.json": _VALID_SENSITIVITY,
            }
        )
    )
    md, html_page = _both_pages(d)
    assert "Target Customers: 1,438" in md
    for page in (md, html_page):
        assert "1,437.58" not in page and "14,375.8" not in page


# --- the verdict's strongest challenge is a whole sentence ----------------------------------------


def test_the_strongest_challenge_is_not_cut_at_an_abbreviation() -> None:
    """A live verdict read "...than <a count> -- i.e (from deck.pdf, page 2)": the
    first sentence was taken by splitting on ". ", and "i.e. the" is not a sentence end."""
    sys.path.insert(0, str(_SCRIPTS))
    import importlib.util

    spec = importlib.util.spec_from_file_location("ms_view", _SCRIPTS / "_view.py")
    assert spec is not None and spec.loader is not None
    view = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(view)
    finding = {
        "severity": "high",
        "claim_attacked": "The ARPU",
        "what_is_true": "The blend has 24 onboarding and 13 renewal months -- i.e. it is onboarding-heavy, "
        "e.g. twice the M0 share. A second sentence follows.",
        "source_url": "document:deck.pdf#page=2",
    }
    line = view._top_challenge({"findings": [finding], "metadata": {"run_id": "r"}})
    assert "i.e. it is onboarding-heavy, e.g. twice the M0 share (from" in line
    assert "A second sentence" not in line


def test_the_strongest_challenge_keeps_a_quote_the_sentence_closes() -> None:
    """A live hand-over read "...labeled explicitly as the 'blended average rate (from deck.pdf, page
    2)": the closing quote after the full stop was taken as part of the sentence break and dropped."""
    sys.path.insert(0, str(_SCRIPTS))
    import importlib.util

    spec = importlib.util.spec_from_file_location("ms_view_q", _SCRIPTS / "_view.py")
    assert spec is not None and spec.loader is not None
    view = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(view)
    for close in ("'", "\u2019", '"', "\u201d", ")"):
        opener = {"'": "'", "\u2019": "\u2018", '"': '"', "\u201d": "\u201c", ")": "("}[close]
        finding = {
            "severity": "high",
            "claim_attacked": "The ARPU",
            "what_is_true": f"The slide labels $261 as the {opener}blended average rate.{close} "
            "The analysis used $157.",
            "source_url": "document:deck.pdf#page=2",
        }
        line = view._top_challenge({"findings": [finding], "metadata": {"run_id": "r"}})
        assert f"the {opener}blended average rate{close} (from" in line, line
        assert "The analysis used" not in line, line


def test_the_shared_narrowing_note_never_presumes_the_builds_agree() -> None:
    """The ‡ note said "their agreement on it is not a cross-check" beside SOM $2.1M and $228.7M, 196%
    apart. A shared narrowing figure means the builds are not independent on that figure, whether
    they agree or not."""
    for name in ("compose_report.py", "visualize.py", "closing_message.py"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert "their agreement" not in text, name
        assert "not independent" in text, name


# --- "your materials" read as "your documents" (critique 2026-09-27) ------------------------------


def test_a_stated_market_figure_is_what_you_stated_not_what_your_materials_state() -> None:
    """The founder typed $12B and $60M in chat; the verdict said "Your materials state TAM $12.0B" and
    the evaluator read that as the deck. "You stated" is true wherever the figure came from."""
    from test_market_sizing import (
        _REDTEAM_ARTIFACT,
        _VALID_INPUTS,
        _closing,
        _compose_md_text,
        _compose_with_sizing,
        _verdict_sizing,
    )

    inputs = {**_VALID_INPUTS, "existing_claims": {"tam": None, "sam": None, "som": 100_000_000}}
    rc, data, d = _compose_with_sizing(_verdict_sizing(), inputs=inputs, redteam=_REDTEAM_ARTIFACT)
    assert rc == 0 and data is not None
    md = _compose_md_text(Path(d))
    assert "You stated SOM $100.0M; this analysis finds" in md, md[:3000]
    rc, html_page, err = run_script_raw("visualize.py", ["--dir", str(d)])
    assert rc == 0, err
    rc, handover, err = _closing(str(Path(d) / "report.json"))
    assert rc == 0, err
    for page in (md, html_page, handover):
        assert "your materials" not in page.lower(), page[:2000]


def test_a_review_finding_names_the_figure_you_stated() -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "skills" / "market-sizing" / "scripts" / "_redteam_text.py"
    spec = importlib.util.spec_from_file_location("ms_redteam_text_attr", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.humanize_claim("existing_claims.tam") == "the TAM you stated"
    assert "you stated" in mod.humanize_review_text("It contradicts existing_claims.som.value.")[0]
