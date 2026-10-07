"""The gate registry: every question the six analysis skills put to a founder, and the ledger of answers.

One literal (`GATES`) names every gate, its options and who records it. Gate ids, instance keys, option
ids, default reasons and codes are contract: hosts pre-answer and read status by them, so they change
only by addition. Labels are presentation, held to each skill's own text by sync tests.

The ledger is `<ARTIFACTS_ROOT>/runs/<RUN_ID>/gates.json`. Every write takes the run lock, writes the
ledger, then re-derives the run status from it (`_run_status.update`). A rejected write changes neither.
Three gates are recorded by their own scripts (deck-review's `gate_state.py`, market-sizing's
`record_revision_answer.py`, cap-table's `extract_cap_table.py`): those call `open_from_writer` /
`record_from_writer` here and keep their own files as mirrors. The recorder refuses those gates.

WHAT A RECORD PROVES: that a script recorded a listed option for this run, and, for a bound gate, that
what it confirmed has not changed since. Not that a person chose it: the ledger is a plain file and the
lock is advisory. Compare-and-set is an accident guard, not a lock.

Predicates, option sources, binders and `requires` checks are named in the registry; the ones whose
skill is not wired yet raise `Unimplemented`, which every caller turns into exit 2. A contract test
pins the exact unimplemented set.

`python3 _gates.py --dump-contract` writes `data/host-contract.json` from the registry.
"""

from __future__ import annotations

import copy
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    # Appended, never prepended: a skill script that loads this module keeps its own modules first.
    sys.path.append(_HERE)
import _form_reply  # noqa: E402
import _founder_text  # noqa: E402
import _run_status  # noqa: E402

REGISTRY_VERSION = 1
LEDGER_SCHEMA = "founder-skills/gates"
CONTRACT_SCHEMA = "founder-skills/host-contract"
CONTRACT_PATH = os.path.join(os.path.dirname(_HERE), "data", "host-contract.json")
RECORDER = "record_gate_answer.py"

SKILLS = (
    "deck-review",
    "market-sizing",
    "financial-model-review",
    "ic-sim",
    "competitive-positioning",
    "cap-table",
)
SHARED = "shared"

# The title a form for this skill's gates is headed with.
FORM_HEADERS = {
    "deck-review": "Deck review",
    "market-sizing": "Market sizing",
    "financial-model-review": "Financial model review",
    "ic-sim": "IC simulation",
    "competitive-positioning": "Competitive positioning",
    "cap-table": "Cap table",
}

DEFAULT_REASONS = (
    "stated_in_request",
    "derived_from_materials",
    "inferred",
    "asked_not_to_be_asked",
    "stage_stated_and_detected_agree",
    "no_signal_marked_to_confirm",
    "producer_default_disclosed",
    "start_fresh_by_default",
    # The question was put and no answer came back: the gate's `asked_unanswered` default is recorded.
    "asked_unanswered",
)
RESOLUTIONS = ("answered", "default_taken", "not_applicable")
RESOLUTION_BASES = ("script", "model")
GATE_STATES = ("open", "answered", "not_owed")
# How the status lists a registered gate of the run's skill and mode that the run has not reached.
NOT_REACHED = "not_reached"
KINDS = ("fixed", "templated", "script_built")
ASKED_CHECKS = ("none", "since_invocation", "current_prompt")
ASKED_EVIDENCE = ("host_line", "form", "after_hold", "ask_user_question", "plain_chat")
# The values a script records; the others come only from the asked-gate hook's record, folded into the
# status by `_run_status.fold_asked_evidence`.
SCRIPT_ASKED_EVIDENCE = ASKED_EVIDENCE[:3]
WRITERS = (RECORDER, "gate_state.py", "record_revision_answer.py", "extract_cap_table.py")
# The gates a hook holds the next dispatch for; `--after-hold` may replace their answer once per run.
HELD_GATES = ("ms_two_figures", "ms_methodology", "fmr_extracted_values", "ic_decline_confirmation")
# Gates whose site can be asked again in one run: the founder resends a file and it fails the same way.
# `open` on one that already has an answer supersedes that answer (reason `asked_again`), so the new
# reply, `Stop the review` included, can be recorded. Every other recorded answer stands.
REASK_SUPERSEDES = ("dr_input_request", "ms_correct_data")
# Gates whose instances are made at run time and whose bare key a request may answer for every instance at
# once: `FS_HOST_ANSWER ms_two_figures=typed` chooses the typed figure for each input that has two. A line
# naming an instance wins over the bare line for that instance.
BARE_PRE_ANSWER_GATES = ("ms_two_figures",)

# Rejections: exit 1, ledger and status untouched.
REJECTION_CODES = (
    "GATE_UNKNOWN",
    "GATE_FOREIGN",
    "OPTION_UNLISTED",
    "VALUE_REQUIRED",
    "VALUE_NOT_ALLOWED",
    "OPTION_SKILL",
    "ID_MALFORMED",
    "ANSWER_STANDS",
    "AFTER_HOLD_USED",
    "AFTER_HOLD_NOT_HELD",
    "AFTER_HOLD_NO_ANSWER",
    "REQUIRES_UNMET",
    "GATE_NOT_OWED",
    "NOTE_INVALID",
    "CLOSE_SCRIPT_OWED",
    "WRITER_IS_OTHER_SCRIPT",
    "DEFAULT_REASON_INVALID",
    "RUN_FINISHED",
    "FORM_REPLY_DISABLED",
    "FORM_REPLY_UNMATCHED",
    "GATE_RECORD_MISMATCH",
)
# Exit 2: the run or the registry cannot be reached.
UNREACHABLE_CODES = (
    "RUN_NOT_FOUND",
    "LEDGER_MISSING",
    "REGISTRY_UNREACHABLE",
    "GATE_NOT_WIRED",
    "GATE_UNDECIDABLE",
    "LOCK_UNAVAILABLE",
    "RUN_DIR_OUTSIDE_ROOT",
    "SKILL_UNKNOWN",
)
EXIT_CODES = {
    "ok": 0,
    "rejected": 1,
    "usage_or_unreachable": 2,
    "waiting": 10,
    "not_owed": 11,
}

GATE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
OPTION_ID_RE = re.compile(r"^[a-z0-9_+.-]+$")
NOTE_MAX = 2000

REQUEST_TOKENS = {
    "run_id": "FS_HOST_RUN_ID=<run_id>",
    "answer": "FS_HOST_ANSWER <gate>[.<instance>]=<option_id>",
    "value": "FS_HOST_VALUE <gate>[.<instance>]=<option_id> | <value>",
    "note": "FS_HOST_NOTE <gate>[.<instance>]=<text>",
}

# Sentences a host relies on, carried in the contract file.
CONTRACT_NOTES = (
    "`complete` means the markdown and JSON reports are final; HTML pages may appear in `deliverables` after "
    "`complete`, and an HTML file not listed there is not this run's.",
    "`complete` with `deliverables_status: pending` after the skill has returned means no more pages will be listed.",
    "A resume request repeats every FS_HOST_ line of the original request, plus the answer for the waiting gate.",
    "Before `bind`, `gates[]` holds the gates already reached plus those common to every mode of the skill; "
    "`bind` completes the list for the run's mode.",
    "`RUN_ID_IN_USE`, `RUN_ID_FINISHED` and `RUN_ID_MALFORMED` are printed only; they never change a run's "
    "run_status.json.",
    "`current.asked_evidence` may also be `ask_user_question`, `plain_chat`, `host_line` or `form` from the "
    "plugin's transcript check. It stays null when that check did not run (hooks are optional) or when the step "
    "went through on its one retry with no question. It is a measurement of how the question was put, not an "
    "attestation that a person answered it.",
    "`untouched_since_resume` lists the run-dir files no writer rewrote after this invocation began; "
    "`touched_since_resume` lists those a writer did, and how. It records file writes measured by script, not "
    "steps: which files a correct resume rewrites depends on the skill and the gate (reports, coaching and pages "
    "are rewritten every invocation; a corrections resume rewrites inputs.json), and it cannot see work written "
    "outside the run dir or work that wrote nothing. `null` means no manifest could be taken, never that nothing "
    "ran.",
    "Exit 10 means a question is owed and its gate is named in `blocked_by_gate`. The status is then `waiting`, "
    "except for `GATE_UNRESOLVED`: a question that was opened and never recorded leaves the run `running` with "
    "`last_error_code: GATE_UNRESOLVED`. Like every `last_error_code` (`GATE_INVALID`, `GATE_OTHER_RUN`, "
    "`PROFILE_MISMATCH`, `COACHING_BLOCKED`), it records the last error seen and is cleared only when the run "
    "completes.",
    "`disclosures` lists `DEFAULT_TAKEN:<gate>` for an answer recorded as a default and `PRE_ANSWERED:<gate>` for "
    "one applied from a request line instead of being asked. `PRE_ANSWERED:out_of_scope_choice` means the request "
    "chose to review a deck outside the skill's stage scope, best-effort; the report and page tell the founder so.",
    "`disclosures` also lists `EXTRACTION_UNREVIEWED` when financial-model-review's extracted values went on "
    "without being reviewed, and `CORRECTIONS_SOURCE:<origin>` (`external`, `upload` or `chat`) when corrections "
    "to them were applied, naming who supplied them.",
    "A `complete` financial-model-review run returns to `running`, with `revision` + 1 and `handed_over_at` "
    "cleared, when the founder answers the cash follow-up; it completes again at the next coaching insert.",
    "An enforcer never re-opens a finished run's answer: on a `complete` or `refused` run whose confirmed input "
    "changed, it refuses `RUN_FINISHED` and writes nothing; a changed figure after `complete` needs a new run.",
    "`ms_two_figures` has one instance per input the founder stated two figures for "
    "(`FS_HOST_ANSWER ms_two_figures.arpu=typed`). The bare `FS_HOST_ANSWER ms_two_figures=<option>` answers every "
    "instance; a line naming an instance wins for that instance. Its alternatives' ids are keyed on the figure "
    "(`alt_<value>[_<period>]`), so only `typed` is known before the run.",
    "A question the run no longer owes (its parent was answered otherwise, its condition no longer holds, or the "
    "run's mode does not ask it) is closed `not_applicable` by script; if the run owes it again it is re-opened and "
    "asked, never read as answered.",
    "`ic_decline_confirmation` is owed only while this run's scored verdict is a Decline (`pass` or `hard_pass`); "
    "a request line for it applies only then. `hold_off` cannot be sent ahead: recorded, it leaves the run "
    "`waiting` until `finish` is. A scores file that cannot be read or carries another run's id makes the gate "
    "`GATE_UNDECIDABLE` (exit 2) rather than not owed.",
    "ic-sim refuses `RUN_FINISHED` (exit 1, nothing written) when its fund profile or report is built again for a "
    "`complete` run: new materials after delivery are a new simulation, under a new run id.",
)


class GateRejection(Exception):
    """A refused write. Nothing was written."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        assert code in REJECTION_CODES, code
        self.code = code
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        return {"status": "rejected", "code": self.code, "message": str(self), **self.extra}


class Unimplemented(Exception):
    """A predicate, option source, binder or requires check whose skill is not wired yet (`GATE_NOT_WIRED`),
    or one that cannot be decided from what is on disk (`GATE_UNDECIDABLE`). Exit 2. The settle pass leaves a
    gate whose predicate raises it as it is."""

    def __init__(self, message: str, code: str = "GATE_NOT_WIRED") -> None:
        super().__init__(message)
        self.code = code


class RegistryError(Exception):
    """The registry literal is inconsistent. Exit 2: the loader fails closed."""


def _o(
    id: str,
    label: str,
    *,
    terminal: bool = True,
    shown: bool = True,
    pre: bool = True,
    value: bool = False,
    requires: str | None = None,
    discloses: str | None = None,
    declines: bool = False,
    effects: dict[str, tuple[str, ...]] | None = None,
    only_skills: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "terminal": terminal,
        "shown": shown,
        "pre_answerable": pre and terminal,
        "takes_value": value,
        "requires": requires,
        "discloses": discloses,
        "declines": declines,
        "effects": effects,
        "only_skills": only_skills,
    }


_ALL_MODES = ("full", "quick_check", "fast_assess", "concise", "extraction_only")
_FULL = ("full",)
_STATED = (("stated_in_request", None),)


def _no_ask(option_id: str) -> tuple[tuple[str, str | None], ...]:
    return (("stated_in_request", None), ("asked_not_to_be_asked", option_id))


# --- the registry: one entry per gate, grouped by skill ---------------------------------------------

GATES: dict[str, dict[str, Any]] = {
    # --- shared: Step 1 company context -------------------------------------------------------
    "ctx_select_company": {
        "skill": "shared",
        "step": "1",
        "modes": _ALL_MODES,
        "kind": "script_built",
        "question": "Which company is this for?",
        "form_label": "Company",
        "instances": None,
        "multi": False,
        "options": (_o("different_company", "A different company"),),
        "option_source": "ctx_company_slugs",
        "option_variants": None,
        "owed": "ctx_many_contexts",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ctx_basics": {
        "skill": "shared",
        "step": "1",
        "modes": _ALL_MODES,
        "kind": "templated",
        "question": {
            "company_name": "What's the company's name?",
            "stage": "What stage is [Company] at?",
            "sector": "What sector best describes [Company]?",
            "geography": "Where is [Company] based?",
        },
        "form_label": {"company_name": "Company", "stage": "Stage", "sector": "Sector", "geography": "Geography"},
        "instances": {"static": ("company_name", "stage", "sector", "geography")},
        "multi": False,
        "options": {
            "company_name": (
                _o("use_derived", 'Use "<name>" — as it appeared in the conversation / on the deck', value=True),
                _o("different", "A different name — I'll state it", value=True),
                _o("working_title", "No name yet — use a working title I can rename later"),
                _o(
                    "use_model_file",
                    "Use what the model file states",
                    only_skills=("financial-model-review",),
                ),
            ),
            "stage": (
                _o("pre_seed", "Pre-seed"),
                _o("seed", "Seed"),
                _o("series_a", "Series A"),
                _o("series_b_plus", "Series B+", effects={"opens": ("ctx_stage_detail",)}),
            ),
            "sector": (
                _o("use_derived", 'Use "<sector>" — as derived from the materials', value=True),
                _o("different", "A different sector — I'll state it", value=True),
                _o("not_sure", "Not sure"),
            ),
            "geography": (
                _o("use_derived", 'Use "<geography>" — as derived from the materials', value=True),
                _o("different", "A different location — I'll state it", value=True),
                _o("not_sure", "Not sure"),
            ),
        },
        "option_source": None,
        "option_variants": None,
        "owed": "ctx_needs_init",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": (
            ("stated_in_request", None),
            ("derived_from_materials", None),
            ("inferred", None),
            ("no_signal_marked_to_confirm", None),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ctx_stage_detail": {
        "skill": "shared",
        "step": "1",
        "modes": _ALL_MODES,
        "kind": "fixed",
        "question": "Which stage exactly?",
        "form_label": "Stage detail",
        "instances": None,
        "multi": False,
        "options": (
            _o("series_b", "Series B"),
            _o("series_c", "Series C"),
            _o("series_d", "Series D"),
            _o("later", "Later"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ctx_needs_init",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- deck-review ---------------------------------------------------------------------------
    "dr_primary_deck": {
        "skill": "deck-review",
        "step": "2",
        "modes": _FULL,
        "kind": "templated",
        "question": "Which file is the primary deck?",
        "form_label": "Primary deck",
        "instances": None,
        "multi": False,
        "options": (
            _o("named", "This file is the primary deck", value=True),
            _o("none_of_these", "None of these"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "stage_confirmation": {
        "skill": "deck-review",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Does this stage detection look right?",
        "form_label": "Stage",
        "instances": None,
        "multi": False,
        "options": (
            _o("looks_right", "Looks right", effects={"closes": ("out_of_scope_choice", "stage_choice")}),
            _o("different_stage", "Different stage", terminal=False, effects={"reopens": ("stage_choice",)}),
            _o(
                "not_sure_proceed",
                "Not sure — proceed anyway",
                effects={"closes": ("out_of_scope_choice", "stage_choice")},
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "by_writer",
        "asked_check": "none",
        "writer": "gate_state.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": (("stated_in_request", None), ("stage_stated_and_detected_agree", "looks_right")),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "out_of_scope_choice": {
        "skill": "deck-review",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "This looks out of scope. What should I do?",
        "form_label": "Out of scope",
        "instances": None,
        "multi": False,
        "options": (
            # Both terminal answers settle the whole stage question: a `Different stage` reply left on
            # `stage_confirmation` earlier in the chain would otherwise stay open, and a run whose questions
            # were all answered could never complete.
            _o(
                "stop_review",
                "Stop review",
                declines=True,
                effects={"closes": ("stage_choice", "stage_confirmation")},
            ),
            _o("different_stage", "Different stage", terminal=False, effects={"reopens": ("stage_choice",)}),
            _o(
                "proceed_anyway",
                "Proceed anyway (best-effort)",
                effects={"closes": ("stage_choice", "stage_confirmation")},
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "by_writer",
        "asked_check": "none",
        "writer": "gate_state.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "stage_choice": {
        "skill": "deck-review",
        "step": "3",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Which stage is this deck?",
        "form_label": "Stage",
        "instances": None,
        "multi": False,
        "options": (),
        "option_source": "dr_stage_tokens",
        "option_variants": None,
        "owed": "by_writer",
        "asked_check": "none",
        "writer": "gate_state.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "dr_input_request": {
        "skill": "deck-review",
        "step": "2",
        "modes": _FULL,
        "kind": "templated",
        "question": {
            "wrong_file_type": "This file could not be read as a deck. Can you send it again?",
            "gated_link": "That link asks for a login. Can you send a PDF export or the slides as text?",
            "no_uploads_mount": "I can't see an attached deck. Can you attach it or give its path?",
            "pdf_unreadable": "This PDF could not be read. Can you send another export?",
            "copy_failed": "The deck could not be opened here. Can you send it again?",
        },
        "form_label": "Deck",
        "instances": {"static": ("wrong_file_type", "gated_link", "no_uploads_mount", "pdf_unreadable", "copy_failed")},
        "multi": False,
        "options": (
            _o("provide", "I'll provide it", value=True),
            _o("stop", "Stop the review", declines=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- market-sizing -------------------------------------------------------------------------
    "ms_two_figures": {
        "skill": "market-sizing",
        "step": "3",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Your materials state more than one figure for this input. Which one should the sizing use?",
        "form_label": "Figure",
        "instances": {"dynamic": "input"},
        "multi": False,
        "options": (_o("typed", "The figure you typed"),),
        "option_source": "ms_alternatives",
        "option_variants": None,
        "owed": "ms_founder_alternatives",
        "asked_check": "current_prompt",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "typed",
        "defaults": _no_ask("typed"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_methodology": {
        "skill": "market-sizing",
        "step": "3",
        "modes": _FULL,
        "kind": "templated",
        "question": (
            "I'll size this <top-down / bottom-up / both top-down and bottom-up> — does this approach look right?"
        ),
        "form_label": "Methodology",
        "instances": None,
        "multi": False,
        "options": (
            _o("looks_good", "Looks good"),
            # Neither closes the question: it is asked again once the approach or the data has changed.
            _o(
                "change_methodology",
                "Change methodology",
                terminal=False,
                effects={"reopens": ("ms_methodology_change",)},
            ),
            _o("correct_data", "Correct or add data", terminal=False),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ms_full_sizing",
        "asked_check": "since_invocation",
        "writer": "record_gate_answer.py",
        "binds": "ms_methodology_files",
        "no_ask_default": "looks_good",
        "defaults": _no_ask("looks_good"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_methodology_change": {
        "skill": "market-sizing",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Which approach do you prefer?",
        "form_label": "Approach",
        "instances": None,
        "multi": False,
        "options": (
            _o("top_down", "Top-down"),
            _o("bottom_up", "Bottom-up"),
            _o("both", "Both top-down and bottom-up"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ms_methodology_changed",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_correct_data": {
        "skill": "market-sizing",
        "step": "3",
        "modes": _FULL,
        "kind": "templated",
        "question": "Which value is wrong or missing?",
        "form_label": "Correction",
        "instances": {"dynamic": "field_path"},
        "multi": False,
        "options": (
            _o("set", "<input>: <current value>", value=True),
            _o("something_else", "Something else — I'll say which in chat"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ms_correction_requested",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_fx_rate": {
        "skill": "market-sizing",
        "step": "3",
        "modes": _FULL,
        "kind": "templated",
        "question": "What exchange rate should the sizing use, and from what source?",
        "form_label": "Exchange rate",
        "instances": None,
        "multi": False,
        "options": (
            _o("give_rate", "I'll give the rate", value=True),
            _o("size_in_source_currency", "Size it in the source currency"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_input_period": {
        "skill": "market-sizing",
        "step": "5",
        "modes": _FULL,
        "kind": "templated",
        "question": "Is this figure per month, per quarter or per year?",
        "form_label": "Period",
        "instances": {"dynamic": "input"},
        "multi": False,
        "options": (
            _o("per_month", "Per month"),
            _o("per_quarter", "Per quarter"),
            _o("per_year", "Per year"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ms_period_unknown",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_pct_scale": {
        "skill": "market-sizing",
        "step": "5.5",
        "modes": _FULL,
        "kind": "templated",
        "question": "Did you mean this value as given, or as that many percent?",
        "form_label": "Percent",
        "instances": {"dynamic": "input"},
        "multi": False,
        "options": (
            _o("as_given", "As given"),
            _o("percent", "That many percent"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ms_implausible_pct_scale",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "as_given",
        "defaults": _no_ask("as_given"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_revision": {
        "skill": "market-sizing",
        "step": "6d",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Deliver with the challenges shown, or revise?",
        "form_label": "Revision",
        "instances": None,
        "multi": False,
        "options": (
            _o("deliver", "Deliver with the challenges shown"),
            # Not answerable ahead: the changes it opens are named by the review, which no request has seen.
            _o(
                "revise",
                "Revise the challenged inputs and have it reviewed once more (about 10 minutes)",
                pre=False,
                effects={"opens": ("ms_revision_changes",)},
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "by_writer",
        "asked_check": "none",
        "writer": "record_revision_answer.py",
        "binds": None,
        "no_ask_default": "deliver",
        "defaults": _no_ask("deliver"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_revision_changes": {
        "skill": "market-sizing",
        "step": "6d",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Which changes should I make?",
        "form_label": "Changes",
        "instances": None,
        "multi": True,
        "options": (_o("none_of_these", "None of these"),),
        "option_source": "ms_proposed_changes",
        "option_variants": None,
        "owed": "ms_revise_chosen",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ms_upload_path": {
        "skill": "market-sizing",
        "step": "6c",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Where are the documents you shared? The review reads them first.",
        "form_label": "Documents",
        "instances": None,
        "multi": False,
        "options": (
            _o("provide", "I'll give the path", value=True),
            _o("review_without_documents", "Review without the documents"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- financial-model-review ----------------------------------------------------------------
    "fmr_cash_basics": {
        "skill": "financial-model-review",
        "step": "1",
        "modes": _FULL,
        "kind": "templated",
        "question": {
            "current_balance": "What is the current cash balance?",
            "balance_date": "What date is that balance from?",
            "monthly_burn": "What is the monthly burn rate?",
        },
        "form_label": {"current_balance": "Cash", "balance_date": "Cash date", "monthly_burn": "Burn"},
        "instances": {"static": ("current_balance", "balance_date", "monthly_burn")},
        "multi": False,
        "options": (
            _o("stated", "<the stated value>", value=True),
            _o("not_stated", "Not stated — proceed and flag to confirm"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "fmr_full_review",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "not_stated",
        "defaults": _no_ask("not_stated"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "fmr_extracted_values": {
        "skill": "financial-model-review",
        "step": "3.6",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Do the extracted values look right?",
        "form_label": "Extracted values",
        "instances": None,
        "multi": False,
        "options": (
            _o("values_ok", "Looks right, proceed"),
            _o("has_corrections", "I have corrections", value=True, terminal=False),
            _o(
                "proceed_unreviewed",
                "Proceed without reviewing the extracted values",
                discloses="EXTRACTION_UNREVIEWED",
            ),
            _o(
                "corrections_applied",
                "Corrections applied, proceed",
                shown=False,
                requires="fmr_corrections_audit",
                discloses="CORRECTIONS_SOURCE",
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "fmr_full_review",
        "asked_check": "since_invocation",
        "writer": "record_gate_answer.py",
        "binds": "fmr_inputs_minus_cash",
        "no_ask_default": "proceed_unreviewed",
        "defaults": _no_ask("proceed_unreviewed"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "fmr_cash_followup": {
        "skill": "financial-model-review",
        "step": "12",
        "modes": _FULL,
        "kind": "fixed",
        "question": "How much cash is in the bank now, and as of which date?",
        "form_label": "Cash",
        "instances": None,
        "multi": False,
        "options": (
            # The reply re-states the two cash basics it answers, so a `Not stated` from Step 1 does not stand
            # beside the balance the founder has now given.
            _o(
                "provided",
                "Cash balance provided",
                pre=False,
                requires="fmr_cash_audit",
                effects={"reopens": ("fmr_cash_basics.current_balance", "fmr_cash_basics.balance_date")},
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "fmr_no_cash_balance",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": (("stated_in_request", None), ("producer_default_disclosed", None)),
        "reopens_complete": True,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- ic-sim ----------------------------------------------------------------------------------
    "ic_mode": {
        "skill": "ic-sim",
        "step": "1",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Which mode should I run?",
        "form_label": "Mode",
        "instances": None,
        "multi": False,
        "options": (
            _o("interactive", "Interactive"),
            _o("auto_pilot", "Auto-pilot"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "always",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "auto_pilot",
        "defaults": _no_ask("auto_pilot"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ic_fund_mode": {
        "skill": "ic-sim",
        "step": "1",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Should I simulate a generic fund, or research a real one?",
        "form_label": "Fund",
        "instances": None,
        "multi": False,
        "options": (
            _o("generic", "Generic fund"),
            _o("specific", "A specific fund — I'll name it", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "always",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "generic",
        "defaults": _no_ask("generic"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ic_decline_confirmation": {
        "skill": "ic-sim",
        "step": "8.5",
        "modes": _FULL,
        "kind": "fixed",
        "question": "The scored result comes out to a Decline — want me to go ahead and finish the full write-up?",
        "form_label": "Decline",
        "instances": None,
        "multi": False,
        "options": (
            _o("finish", "Yes, finish the write-up"),
            _o("hold_off", "Hold off — let me add more context first", terminal=False),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ic_verdict_decline",
        "asked_check": "since_invocation",
        "writer": "record_gate_answer.py",
        "binds": "ic_score_dimensions",
        "no_ask_default": "finish",
        "defaults": _no_ask("finish"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- competitive-positioning -----------------------------------------------------------------
    "cp_product_profile": {
        "skill": "competitive-positioning",
        "step": "2",
        "modes": _FULL,
        "kind": "templated",
        "question": {
            "product": "What does the product do?",
            "customers": "Who are the target customers?",
            "differentiation": "What do you believe differentiates you?",
        },
        "form_label": {"product": "Product", "customers": "Customers", "differentiation": "Differentiation"},
        "instances": {"static": ("product", "customers", "differentiation")},
        "multi": False,
        "options": (
            _o("use_derived", 'Use "<derived>"', value=True),
            _o("describe_in_chat", "I'll describe it in chat", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_gate1_landscape": {
        "skill": "competitive-positioning",
        "step": "3",
        "modes": _FULL,
        "kind": "templated",
        "question": (
            "Found <N> competitors (I'd challenge: <names>) (stronger than drafted: "
            "<upgraded names>) — does this set look right?"
        ),
        "form_label": "Competitors",
        "instances": None,
        "multi": False,
        "options": (
            _o("no_changes", "No changes — looks good as drafted"),
            _o("missing", "Missing competitors", value=True),
            _o("remove", "Remove some", value=True),
            _o("change_axes", "Change axes", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "cp_full_mode",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": "cp_landscape_draft",
        "no_ask_default": "no_changes",
        "defaults": _no_ask("no_changes"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_research_additions": {
        "skill": "competitive-positioning",
        "step": "4a",
        "modes": _FULL,
        "kind": "templated",
        "question": "Found <N> more competitors during research — include any?",
        "form_label": "Additions",
        "instances": None,
        "multi": False,
        "options": (
            _o("include_all", "Include all"),
            _o("include_top", "Include top <slots>"),
            _o("include_some", "Include some"),
            _o("skip", "No changes — skip these"),
            _o("free_slot_by_merging", "Free a slot by merging"),
        ),
        "option_source": None,
        "option_variants": (
            ("include_all", "include_some", "skip"),
            ("include_top", "include_some", "skip"),
            ("skip", "free_slot_by_merging"),
        ),
        "owed": "cp_research_suggestions",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "skip",
        "defaults": _no_ask("skip"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_research_pick": {
        "skill": "competitive-positioning",
        "step": "4a",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Which ones should I include?",
        "form_label": "Include",
        "instances": None,
        "multi": False,
        "options": (_o("none_of_these", "None of these"),),
        "option_source": "cp_competitor_slugs",
        "option_variants": None,
        "owed": "cp_include_some_chosen",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_gate2_axes": {
        "skill": "competitive-positioning",
        "step": "4c",
        "modes": _FULL,
        "kind": "templated",
        "question": "I'll plot competitors on <axis-X> × <axis-Y> — do these axes look right?",
        "form_label": "Axes",
        "instances": None,
        "multi": False,
        "options": (
            _o("no_changes", "No changes — proceed to scoring"),
            _o("change_axes", "Change axes", value=True),
            _o("adjust_set", "Adjust competitor set", value=True),
            _o(
                "change_scoring_basis",
                "Change scoring basis",
                effects={"opens": ("cp_scoring_basis",)},
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "cp_full_mode",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "no_changes",
        "defaults": _no_ask("no_changes"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_scoring_basis": {
        "skill": "competitive-positioning",
        "step": "4c",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Which basis should the scoring use?",
        "form_label": "Scoring basis",
        "instances": None,
        "multi": False,
        "options": (
            _o("shipped", "Shipped"),
            _o("roadmap_12mo", "12-month roadmap"),
            _o("mixed", "Mixed"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "cp_basis_change_chosen",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_gate3_position": {
        "skill": "competitive-positioning",
        "step": "6",
        "modes": _FULL,
        "kind": "templated",
        "question": (
            "The scored position <plain-language description of the trigger> — keep it, "
            "dig deeper, or reconsider how it's scored?"
        ),
        "form_label": "Position",
        "instances": None,
        "multi": False,
        "options": (
            _o("no_changes", "No changes — keep the scoring"),
            _o("rescore_founder_facts", "Re-score with founder facts", value=True),
            _o(
                "change_scoring_basis",
                "Change scoring basis",
                effects={"opens": ("cp_scoring_basis",)},
            ),
            _o("show_both", "Show both positions"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "cp_gate3_triggered",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "no_changes",
        "defaults": _no_ask("no_changes"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_consolidation_merge": {
        "skill": "competitive-positioning",
        "step": "4a",
        "modes": _FULL,
        "kind": "templated",
        "question": (
            "My research also found that <A> and <B> are now one company as of <date>, per <source> — want me "
            "to combine them?"
        ),
        "form_label": "Merge",
        "instances": None,
        "multi": False,
        "options": (
            _o("combine", "Combine them"),
            _o("keep_separate", "Keep them separate"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_merge_pick": {
        "skill": "competitive-positioning",
        "step": "4a",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Which two should I merge to free a slot?",
        "form_label": "Merge pair",
        "instances": None,
        "multi": False,
        "options": (),
        "option_source": "cp_merge_pairs",
        "option_variants": None,
        "owed": "cp_free_slot_chosen",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "cp_upload_path": {
        "skill": "competitive-positioning",
        "step": "6c",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Where are the documents you shared? The review reads them first.",
        "form_label": "Documents",
        "instances": None,
        "multi": False,
        "options": (
            _o("provide", "I'll give the path", value=True),
            _o("review_without_documents", "Review without the documents"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    # --- cap-table -------------------------------------------------------------------------------
    "ct_scenario_selection": {
        "skill": "cap-table",
        "step": "5",
        "modes": _FULL,
        "kind": "script_built",
        "question": "Which scenarios should I model? (select all that apply)",
        "form_label": "Scenarios",
        "instances": None,
        "multi": True,
        "options": (
            _o("cap_implied_safe", "Cap-implied SAFE snapshot"),
            _o("priced_round", "Series A priced round"),
            _o("note_conversion", "Convertible note conversion at financing"),
            _o("flip", "Israeli ↔ Delaware flip"),
        ),
        "option_source": "ct_applicable_scenarios",
        "option_variants": None,
        "owed": "ct_scenarios_owed",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Scenario selection",
    },
    "ct_option_pool": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Does the company have an employee option pool?",
        "form_label": "Option pool",
        "instances": None,
        "multi": False,
        "options": (
            _o("no_pool", "No option pool"),
            _o("provide", "Yes — I'll provide authorized / issued / unallocated", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_pool_existence_unknown",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Option pool",
    },
    "ct_cap_base_confirmation": {
        "skill": "cap-table",
        "step": "2",
        "modes": _FULL,
        "kind": "templated",
        "question": "Please confirm [Company]'s cap-table base — I'll use exactly these numbers for all the math:",
        "form_label": "Cap base",
        "instances": None,
        "multi": False,
        "options": (
            _o("confirmed", "Confirmed"),
            _o("different", "Different — I'll correct it in chat", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_cap_base_built",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": "ct_cap_base_fields",
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": True,
        "catalog_row": "Cap-base confirmation",
    },
    "ct_no_cap_base_fork": {
        "skill": "cap-table",
        "step": "2",
        "modes": _FULL,
        "kind": "fixed",
        "question": "No cap base found in your document(s). How should I proceed?",
        "form_label": "Cap base",
        "instances": None,
        "multi": False,
        "options": (
            _o("provide_cap_base", "Provide the cap base — full review"),
            _o("terms_only", "Instrument terms only"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_no_cap_base",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": True,
        "catalog_row": "No-cap-base fork",
    },
    "ct_note_cap_denominator": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "What does the note's 'Company Capitalization' clause define as the conversion denominator?",
        "form_label": "Note denominator",
        "instances": None,
        "multi": False,
        "options": (
            _o(
                "fully_diluted_pre",
                "Fully-diluted pre-financing (common + options + as-converted SAFEs/notes, before new money)",
            ),
            _o(
                "issued_outstanding",
                "Issued-and-outstanding only (common + issued options, no unallocated pool)",
            ),
            _o("check_note_text", "I'd need to check the note text"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_note_denominator_unset",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": 'Note "Company Capitalization" denominator',
    },
    "ct_note_maturity_default": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "If the note reaches maturity before a qualified financing, what happens?",
        "form_label": "Note maturity",
        "instances": None,
        "multi": False,
        "options": (
            _o("convert_at_cap", "Convert at cap"),
            _o("repay", "Repay principal"),
            _o("extend", "Extend maturity"),
            _o("counsel", "Counsel review / unclear"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_note_maturity_unset",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "convert_at_cap",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "convert_at_cap"),
            ("producer_default_disclosed", "convert_at_cap"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Note maturity default",
    },
    "ct_note_qualified_threshold": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": (
            "What dollar amount triggers the note's automatic conversion (its 'qualified financing' threshold)?"
        ),
        "form_label": "Note threshold",
        "instances": None,
        "multi": False,
        "options": (
            _o("same_as_round", "Same as this round's total new money"),
            _o("different_amount", "A different specific amount — I'll state it", value=True),
            _o("check_note_text", "I'd need to check the note text"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_note_threshold_unset",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "same_as_round",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "same_as_round"),
            ("producer_default_disclosed", "same_as_round"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Qualified-financing threshold",
    },
    "ct_existing_review": {
        "skill": "cap-table",
        "step": "0",
        "modes": _FULL,
        "kind": "templated",
        "question": "I found an existing cap-table review for [Company]. Use it, or start fresh?",
        "form_label": "Existing review",
        "instances": None,
        "multi": False,
        "options": (
            _o("use_existing", "Use existing review"),
            _o("start_fresh", "Start fresh"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_existing_review_found",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "start_fresh",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "start_fresh"),
            ("start_fresh_by_default", "start_fresh"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Existing-review routing",
    },
    "ct_pool_topup_intent": {
        "skill": "cap-table",
        "step": "5",
        "modes": ("full", "fast_assess"),
        "kind": "fixed",
        "question": "Are you planning to top up your option pool as part of this round?",
        "form_label": "Pool top-up",
        "instances": None,
        "multi": False,
        "options": (
            _o("none", "No top-up planned"),
            _o("top_up_10", "Top up to 10%"),
            _o("top_up_15", "Top up to 15%"),
            _o("not_sure", "Not sure yet"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_priced_round_modelled",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Pool top-up intent",
    },
    "ct_pool_basis": {
        "skill": "cap-table",
        "step": "5",
        "modes": ("full", "fast_assess"),
        "kind": "fixed",
        "question": "What does your pool target percentage measure?",
        "form_label": "Pool basis",
        "instances": None,
        "multi": False,
        "options": (
            _o("post_money", "The pool available for new grants after the round"),
            _o("post_money_increase", "Only the new options added in this round"),
            _o("pre_money", "Measured against the share count before the round"),
            _o("counsel", "Something else / not sure — ask counsel"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_pool_basis_unsettled",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "pre_money",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "pre_money"),
            ("producer_default_disclosed", "pre_money"),
            ("asked_unanswered", "post_money"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Pool basis",
    },
    "ct_pool_basis_remedy": {
        "skill": "cap-table",
        "step": "5",
        "modes": ("full", "fast_assess"),
        "kind": "templated",
        "question": {
            "custom": "Which computed measure does your document's pool basis match?",
            "excluding": "Your pool basis excludes converting securities, which is not modelled. How should I proceed?",
        },
        "form_label": {"custom": "Pool measure", "excluding": "Pool basis"},
        "instances": {"static": ("custom", "excluding")},
        "multi": False,
        "options": {
            "custom": (_o("state_measure", "I'll state the measure", value=True),),
            "excluding": (
                _o("show_post_money", "Show it on the plain post-money basis"),
                _o("keep_refused", "Leave the pool unmodelled"),
            ),
        },
        "option_source": None,
        "option_variants": None,
        "owed": "ct_pool_basis_refused",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_engagement_mode": {
        "skill": "cap-table",
        "step": "2",
        "modes": ("full", "concise"),
        "kind": "fixed",
        "question": (
            "Is this a flip-focused engagement (Israeli → Delaware), or a standard cap-table modeling engagement?"
        ),
        "form_label": "Engagement",
        "instances": None,
        "multi": False,
        "options": (
            _o("standard", "Standard cap-table modeling"),
            _o("flip_focused", "Flip-focused (Israeli → Delaware)"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_engagement_unknown",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Engagement mode",
    },
    "ct_jurisdiction": {
        "skill": "cap-table",
        "step": "2",
        "modes": ("full", "fast_assess", "concise"),
        "kind": "templated",
        "question": "What is [Company]'s jurisdiction structure?",
        "form_label": "Jurisdiction",
        "instances": None,
        "multi": False,
        "options": (
            _o("israeli", "Israeli company"),
            _o("delaware", "Delaware (already flipped)"),
            _o("mid_flip", "Mid-flip"),
            _o("delaware_with_israeli_sub", "Delaware with Israeli subsidiary"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_jurisdiction_unknown",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Jurisdiction structure",
    },
    "ct_iia_grants": {
        "skill": "cap-table",
        "step": "2",
        "modes": ("full", "fast_assess", "concise"),
        "kind": "templated",
        "question": "Has [Company] received any IIA (Israel Innovation Authority / OCS) grants?",
        "form_label": "IIA grants",
        "instances": None,
        "multi": False,
        "options": (
            _o("none", "No IIA grants"),
            _o("yes", "Yes, has IIA grants"),
            _o("not_sure", "Not sure"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_israeli_company",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "IIA / OCS grants",
    },
    "ct_note_interest_type": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "What kind of interest does the note carry?",
        "form_label": "Note interest",
        "instances": None,
        "multi": False,
        "options": (
            _o("fixed_numeric", "Fixed rate (a stated numeric %)"),
            _o("fixed_numeric_simple", "Fixed rate, simple interest only"),
            _o("statutory_ita_section_3j", "Israeli statutory rate (ITA §3(j))"),
            _o("none", "No interest"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_note_interest_type_unset",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "fixed_numeric",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "fixed_numeric"),
            ("producer_default_disclosed", "fixed_numeric"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Interest rate type (note)",
    },
    "ct_note_interest_converts": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": "Does accrued interest on the note convert into shares along with principal?",
        "form_label": "Interest converts",
        "instances": None,
        "multi": False,
        "options": (
            _o("yes", "Yes — interest converts too"),
            _o("no", "No — interest is paid in cash / forgiven"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_note_interest_converts_unset",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "yes",
        "defaults": (
            ("stated_in_request", None),
            ("asked_not_to_be_asked", "yes"),
            ("producer_default_disclosed", "yes"),
        ),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "Interest converts to shares (note)",
    },
    "ct_safe_terms": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "fixed",
        "question": (
            "Do you know the valuation cap and/or discount on the SAFEs? The "
            "spreadsheet shows amounts but not the terms."
        ),
        "form_label": "SAFE terms",
        "instances": None,
        "multi": False,
        "options": (
            _o("share_terms", "Yes — I'll share the terms in chat", value=True),
            _o("uncapped_mfn", "Uncapped MFN SAFEs"),
            _o("dont_have", "Don't have the terms handy"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_safe_terms_missing",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "SAFE terms",
    },
    "ct_s102_grant_route": {
        "skill": "cap-table",
        "step": "5",
        "modes": _FULL,
        "kind": "fixed",
        "question": (
            "I need per-grant tax-route data to model §102 exposure on the flip — do you have plan "
            "type and grant date for each holder's options?"
        ),
        "form_label": "§102 grants",
        "instances": None,
        "multi": False,
        "options": (
            _o("share", "Yes — I'll share plan type + grant date per holder", value=True),
            _o("partial", "Some, not all — I'll share what I have", value=True),
            _o("proceed_without", "Don't have this — proceed without §102 detail"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_flip_grants_missing",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": "proceed_without",
        "defaults": _no_ask("proceed_without"),
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": "§102 per-grant tax route",
    },
    "ct_docx_tracked_changes": {
        "skill": "cap-table",
        "step": "3",
        "modes": ("full", "fast_assess", "concise", "extraction_only"),
        "kind": "fixed",
        "question": (
            "This document has tracked changes — it's a redline / unsigned draft, not a "
            "final executed version. How should I proceed?"
        ),
        "form_label": "Tracked changes",
        "instances": None,
        "multi": False,
        "options": (
            _o("upload_clean", "Upload the clean / final executed version"),
            _o(
                "proceed_accepted",
                "Proceed on the accepted (final-proposed) terms — I understand it's a draft",
            ),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_docx_has_tracked_changes",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_extraction_confirmation": {
        "skill": "cap-table",
        "step": "3",
        "modes": ("full", "extraction_only"),
        "kind": "templated",
        "question": "Do these extracted values look right?",
        "form_label": "Extracted values",
        "instances": {"static": ("flagged_fields", "unverifiable_doc", "ambiguities", "aoa_fields")},
        "multi": False,
        "options": (
            _o("values_ok", "Confirmed as extracted"),
            _o("has_corrections", "I have corrections", value=True),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_extraction_needs_confirmation",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_founder_fact": {
        "skill": "cap-table",
        "step": "3",
        "modes": ("full", "fast_assess", "concise", "extraction_only"),
        "kind": "templated",
        "question": "What is the value of <field>?",
        "form_label": "Fact",
        "instances": {"dynamic": "field_path"},
        "multi": False,
        "options": (_o("stated", "<the stated value>", value=True),),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_producer_reports_null",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_lane1_counsel_review": {
        "skill": "cap-table",
        "step": "3",
        "modes": ("full", "extraction_only"),
        "kind": "templated",
        "question": "This term needs your confirmation before it is used. What does the document say?",
        "form_label": "Counsel item",
        "instances": {"dynamic": "field_path"},
        "multi": False,
        "options": (_o("stated", "<the stated value>", value=True),),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_lane2_column_mapping": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "templated",
        "question": "Which column holds this field in your export?",
        "form_label": "Column",
        "instances": {"dynamic": "field_path"},
        "multi": False,
        "options": (_o("stated", "<the stated column>", value=True),),
        "option_source": None,
        "option_variants": None,
        "owed": "model",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_lane3_blocker": {
        "skill": "cap-table",
        "step": "3",
        "modes": _FULL,
        "kind": "script_built",
        "question": "What is the value of <field> for this block of the spreadsheet?",
        "form_label": "Sheet value",
        "instances": {"dynamic": "BLOCK.FIELD"},
        "multi": False,
        "options": (_o("stated", "<the stated value>", value=True),),
        "option_source": None,
        "option_variants": None,
        "owed": "by_writer",
        "asked_check": "none",
        "writer": "extract_cap_table.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
    "ct_rule_lookup_fact": {
        "skill": "cap-table",
        "step": "5-lookup",
        "modes": ("rule_lookup",),
        "kind": "templated",
        "question": "I need one fact to answer this. Can you provide it?",
        "form_label": "Fact",
        "instances": None,
        "multi": False,
        "options": (
            _o("provide", "I'll provide it", value=True),
            _o("unknown", "I don't know"),
        ),
        "option_source": None,
        "option_variants": None,
        "owed": "ct_lookup_escalated",
        "asked_check": "none",
        "writer": "record_gate_answer.py",
        "binds": None,
        "no_ask_default": None,
        "defaults": _STATED,
        "reopens_complete": False,
        "mandatory": False,
        "catalog_row": None,
    },
}


# --- registry access ---------------------------------------------------------------------------------

# deck-review's stage tokens and the words a founder reads for them (`gate_state.STAGE_LABELS`, held
# equal by a sync test). `stage_choice` offers four of these, built at run time.
DR_STAGE_LABELS = {
    "pre_seed": "Pre-seed",
    "seed": "Seed",
    "series_a": "Series A",
    "series_b": "Series B",
    "growth": "Growth",
}


def gate_def(gate_id: str) -> dict[str, Any]:
    g = GATES.get(gate_id)
    if g is None:
        raise GateRejection("GATE_UNKNOWN", f"{gate_id!r} is not a registered gate")
    return g


def parse_key(key: str) -> tuple[str, str | None]:
    """`gate` or `gate.instance`. A `/` anywhere is a sub-path and refused."""
    if not isinstance(key, str) or "/" in key or not key:
        raise GateRejection("ID_MALFORMED", f"{key!r} is not a gate id")
    gate_id, _, instance = key.partition(".")
    if not GATE_ID_RE.match(gate_id):
        raise GateRejection("ID_MALFORMED", f"{key!r} is not a gate id")
    if _ and not INSTANCE_RE.match(instance):
        raise GateRejection("ID_MALFORMED", f"{key!r} names a malformed instance")
    return gate_id, (instance if _ else None)


def check_key(key: str, skill: str) -> tuple[str, str | None, dict[str, Any]]:
    gate_id, instance = parse_key(key)
    g = gate_def(gate_id)
    if g["skill"] not in (skill, SHARED):
        raise GateRejection("GATE_FOREIGN", f"{gate_id!r} belongs to {g['skill']}, not {skill}")
    inst = g["instances"]
    if inst is None and instance is not None:
        raise GateRejection("ID_MALFORMED", f"{gate_id!r} has no instances; got {key!r}")
    if inst is not None:
        if instance is None:
            raise GateRejection("ID_MALFORMED", f"{gate_id!r} needs an instance: {gate_id}.<instance>")
        static = inst.get("static")
        if static is not None and instance not in static:
            raise GateRejection("ID_MALFORMED", f"{instance!r} is not an instance of {gate_id!r}: {list(static)}")
    return gate_id, instance, g


def _pick(value: Any, instance: str | None) -> Any:
    if isinstance(value, dict):
        return value.get(instance) if instance is not None else None
    return value


def question_for(g: dict[str, Any], instance: str | None) -> str:
    return str(_pick(g["question"], instance) or "")


def form_label_for(g: dict[str, Any], instance: str | None) -> str:
    return str(_pick(g["form_label"], instance) or "")


_SLOT = re.compile(r"<[^<>\n]+>|\[[^\[\]\n]+\]")
# The value slot a printed `answer_command` ends with.
VALUE_SLOT = "<text>"


def render_question(g: dict[str, Any], instance: str | None, ctx: Ctx | None) -> str:
    """The question as a host or founder may read it: `[Company]` filled from the run's founder context,
    and any slot only the asking step can fill (`<N>`, `<axis-X>`, ...) never shown raw. A question that
    still has one reads as a plain request to choose, named by its form label."""
    question = question_for(g, instance)
    if "[Company]" in question:
        question = question.replace("[Company]", (_company_name(ctx) if ctx else None) or "the company")
    if _SLOT.search(question):
        return f"Please choose an answer for: {form_label_for(g, instance) or 'this question'}."
    return question


def render_label(option: dict[str, Any], ctx: Ctx | None) -> str:
    """An option's label as shown: the company's name where the label takes it, and otherwise, for a
    label whose slot only the asking step can fill, the option's own plain name. Never a raw slot."""
    label = str(option["label"])
    name = _company_name(ctx) if ctx else None
    if name:
        label = label.replace("[Company]", name).replace("<name>", name)
    if _SLOT.search(label):
        return str(_founder_text.humanize_token(option["id"]))
    return label


def _company_name(ctx: Ctx) -> str | None:
    slug = ctx.status.get("slug")
    if not isinstance(slug, str) or not slug:
        return None
    try:
        data = _run_status.read_json(os.path.join(ctx.paths.artifacts_root, f"founder-context-{slug}.json"))
    except ValueError:
        return None
    name = data.get("company_name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def fixed_options(g: dict[str, Any], instance: str | None, skill: str) -> list[dict[str, Any]]:
    opts = _pick(g["options"], instance) or ()
    return [o for o in opts if o["only_skills"] is None or skill in o["only_skills"]]


class Ctx:
    """What a predicate, option source or binder may read: the run's paths, status and run dir."""

    def __init__(self, paths: _run_status.RunPaths, status: dict[str, Any] | None, skill: str) -> None:
        self.paths = paths
        self.status = status or {}
        self.skill = skill
        # The ledger as it stands in memory, inside a transaction: a predicate that reads another gate's
        # answer reads it here, never from the status, which is re-derived only after the write.
        self.ledger: dict[str, Any] | None = None

    @property
    def run_dir(self) -> str | None:
        rd = self.status.get("run_dir_shell")
        return rd if isinstance(rd, str) and rd else None

    @property
    def mode(self) -> str | None:
        m = self.status.get("mode")
        return m if isinstance(m, str) else None


def _context_files(root: str) -> list[str]:
    return sorted(glob.glob(os.path.join(glob.escape(root), "founder-context-*.json")))


def _src_dr_stage_tokens(ctx: Ctx, instance: str | None) -> list[dict[str, Any]]:
    return [_o(token, label) for token, label in DR_STAGE_LABELS.items()]


def _src_ctx_company_slugs(ctx: Ctx, instance: str | None) -> list[dict[str, Any]]:
    out = []
    for path in _context_files(ctx.paths.artifacts_root):
        slug = os.path.basename(path)[len("founder-context-") : -len(".json")]
        if not OPTION_ID_RE.match(slug):
            continue
        try:
            name = (_run_status.read_json(path) or {}).get("company_name")
        except (ValueError, AttributeError):
            name = None
        out.append(_o(slug, str(name or slug)))
    return out


OPTION_SOURCES: dict[str, Callable[[Ctx, str | None], list[dict[str, Any]]] | None] = {
    "dr_stage_tokens": _src_dr_stage_tokens,
    "ctx_company_slugs": _src_ctx_company_slugs,
    "ms_alternatives": None,  # set below, after the run-file readers
    "ms_proposed_changes": None,
    "cp_competitor_slugs": None,
    "cp_merge_pairs": None,
    "ct_applicable_scenarios": None,
}


def options_for(g: dict[str, Any], instance: str | None, ctx: Ctx) -> list[dict[str, Any]]:
    """Every option this gate offers in this run: its fixed ones plus, for a script-built gate, the ones
    its source finds on disk. A source not wired yet raises Unimplemented."""
    opts = fixed_options(g, instance, ctx.skill)
    source = g["option_source"]
    if source is None:
        return opts
    fn = OPTION_SOURCES.get(source)
    if fn is None:
        raise Unimplemented(f"option source {source!r} is not implemented yet")
    built = fn(ctx, instance)
    if source == "ms_alternatives":
        # The typed figure stays first (it is the no-ask default), shown with its amount.
        return [*(_ms_typed(ctx, instance, o) for o in opts), *built]
    if source == "ct_applicable_scenarios":
        ids = {o["id"] for o in built}
        return [o for o in opts if o["id"] in ids]
    return [*built, *opts]


def _pred_always(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    return True


def _pred_many_contexts(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    return len(_context_files(ctx.paths.artifacts_root)) >= 2


# `model`: the model decides the gate applies (and may record it not applicable). `by_writer`: the
# dedicated script's own call is the evidence. `ctx_needs_init`: Step 1 reached `init` because no
# context was found. Every other name is a skill predicate wired with that skill.
PREDICATES: dict[str, Callable[[Ctx, dict[str, Any], str | None], bool] | None] = {
    "always": _pred_always,
    "model": _pred_always,
    "by_writer": _pred_always,
    "ctx_needs_init": _pred_always,
    "ctx_many_contexts": _pred_many_contexts,
    # Owed only on a rule lookup that escalated: `run_status.py finish --lookup-status escalate` is the one
    # caller, and the gate's mode list keeps it out of every other run.
    "ct_lookup_escalated": _pred_always,
    # financial-model-review asks its cash questions in Step 1, before `bind` sets the mode; `modes` drops them
    # from a quick check once it is bound.
    "fmr_full_review": _pred_always,
    "fmr_no_cash_balance": lambda ctx, g, instance: _fmr_no_cash_balance(ctx),
}


_FMR_SCRIPTS = os.path.join(os.path.dirname(_HERE), "skills", "financial-model-review", "scripts")


def fmr_runway_has_no_cash(runway: Any) -> bool:
    """financial-model-review's runway.json when runway was not computed only for want of the cash balance:
    compose_report.py's `_runway_status` test, read structurally (held equal to it by a test)."""
    if not isinstance(runway, dict) or runway.get("skipped") or runway.get("insufficient_data") is not True:
        return False
    baseline = runway.get("baseline")
    return isinstance(baseline, dict) and baseline.get("net_cash") is None and baseline.get("monthly_burn") is not None


def _fmr_no_cash_balance(ctx: Ctx) -> bool:
    """Owed while this run's runway.json lacks the balance, and once reached: the founder's reply is then
    recordable whether or not runway was already re-run with it."""
    for view in ctx.status.get("gates") or []:
        if isinstance(view, dict) and view.get("id") == "fmr_cash_followup" and view.get("state") in GATE_STATES:
            return True
    if ctx.run_dir is None:
        return False
    try:
        runway = _run_status.read_json(os.path.join(ctx.run_dir, "runway.json"))
    except ValueError:
        return False
    # Only this run's runway: an earlier run's file left in the same dir says nothing about this one.
    meta = runway.get("metadata") if isinstance(runway, dict) else None
    if not isinstance(meta, dict) or meta.get("run_id") != ctx.paths.run_id:
        return False
    return fmr_runway_has_no_cash(runway)


# --- market-sizing ---------------------------------------------------------------------------------

_MS_SCRIPTS = os.path.join(os.path.dirname(_HERE), "skills", "market-sizing", "scripts")


def _run_json(ctx: Ctx, name: str) -> Any:
    """A JSON file in the run dir, or None."""
    if ctx.run_dir is None:
        return None
    try:
        return _run_status.read_json(os.path.join(ctx.run_dir, name))
    except ValueError:
        return None


def _answer_id(ctx: Ctx, key: str) -> str | None:
    """`key`'s current answer: from the in-memory ledger inside a transaction, else from the status."""
    if ctx.ledger is not None:
        entry = (ctx.ledger.get("gates") or {}).get(key)
        cur = (entry or {}).get("current") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and entry.get("state") in ("answered", "open") and isinstance(cur, dict):
            return cur.get("answer_id")
        return None
    gate_id, instance = parse_key(key)
    for view in ctx.status.get("gates") or []:
        if isinstance(view, dict) and view.get("id") == gate_id and view.get("instance") == instance:
            cur = view.get("current")
            if view.get("state") in ("answered", "open") and isinstance(cur, dict):
                return cur.get("answer_id")
    return None


def _pred_parent_answered(parent: str, option: str) -> Callable[[Ctx, dict[str, Any], str | None], bool]:
    """Owed while the parent's current answer is `option`."""

    def fn(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
        return option in str(_answer_id(ctx, parent) or "").split(",")

    return fn


def _ms_alternatives(ctx: Ctx, instance: str | None) -> list[dict[str, Any]]:
    inputs = _run_json(ctx, "inputs.json")
    alts = inputs.get("founder_stated_alternatives") if isinstance(inputs, dict) else None
    got = alts.get(instance) if isinstance(alts, dict) and instance else None
    return (
        [a for a in got if isinstance(a, dict) and isinstance(a.get("value"), (int, float))]
        if isinstance(got, list)
        else []
    )


def _pred_ms_alternatives(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    return bool(_ms_alternatives(ctx, instance))


def _ms_figure(value: Any, period: Any) -> str:
    """A figure as a question shows it: plain digits (no separator, no dash a reader takes for a number)."""
    number = int(value) if isinstance(value, float) and value.is_integer() else value
    return f"{number} per {period}" if isinstance(period, str) and period else str(number)


def _ms_alt_id(value: Any, period: Any) -> str:
    """An alternative's id, keyed on the figure itself: it survives the list being rewritten after the
    answer (the chosen figure moves into `founder_stated_inputs`, the typed one into the list)."""
    number = int(value) if isinstance(value, float) and value.is_integer() else value
    tail = f"_{period}" if isinstance(period, str) and re.fullmatch(r"[a-z]+", period) else ""
    return f"alt_{number}{tail}".lower()


def _src_ms_alternatives(ctx: Ctx, instance: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for alt in _ms_alternatives(ctx, instance):
        oid = _ms_alt_id(alt["value"], alt.get("period"))
        if not OPTION_ID_RE.match(oid) or any(o["id"] == oid for o in out):
            continue
        said = str(alt.get("label") or "").strip()
        label = _ms_figure(alt["value"], alt.get("period")) + (f" ({said})" if said else "")
        out.append(_o(oid, label))
    # The question tool shows at most four options: the typed figure and three alternatives. The report
    # still names every figure the materials stated.
    return out[:3]


def _ms_typed(ctx: Ctx, instance: str | None, option: dict[str, Any]) -> dict[str, Any]:
    """The `typed` option, labelled with the figure it stands for."""
    if option["id"] != "typed":
        return option
    inputs = _run_json(ctx, "inputs.json")
    stated = inputs.get("founder_stated_inputs") if isinstance(inputs, dict) else None
    periods = inputs.get("founder_stated_inputs_period") if isinstance(inputs, dict) else None
    value = stated.get(instance) if isinstance(stated, dict) and instance else None
    if not isinstance(value, (int, float)):
        return option
    period = periods.get(instance) if isinstance(periods, dict) else None
    return {**option, "label": f"{option['label']}: {_ms_figure(value, period)}"}


def _ms_qualifying_parameters(redteam: Any) -> list[str]:
    """market-sizing's own rule for the findings that ask the revision question (`_revision_answer.py`),
    loaded by path: the writer, compose and this list cannot disagree."""
    path = os.path.join(_MS_SCRIPTS, "_revision_answer.py")
    mod = sys.modules.get("_ms_revision_answer")
    if mod is None:
        if not os.path.isfile(path):
            raise Unimplemented(f"market-sizing's revision rule is not reachable at {path}")
        spec = importlib.util.spec_from_file_location("_ms_revision_answer", path)
        if spec is None or spec.loader is None:
            raise Unimplemented(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["_ms_revision_answer"] = mod
    out: list[str] = mod.qualifying_parameters(redteam)
    return out


def _src_ms_proposed_changes(ctx: Ctx, instance: str | None) -> list[dict[str, Any]]:
    params = _ms_qualifying_parameters(_run_json(ctx, "redteam.json"))
    return [_o(p, str(_founder_text.humanize_token(p))) for p in params if OPTION_ID_RE.match(p)]


def _pred_ms_pct_scale(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    sizing = _run_json(ctx, "sizing.json")
    warnings = ((sizing.get("validation") or {}).get("warnings") if isinstance(sizing, dict) else None) or []
    return any(
        isinstance(w, dict) and w.get("code") == "IMPLAUSIBLE_PCT_SCALE" and w.get("field") == instance
        for w in warnings
    )


OPTION_SOURCES["ms_alternatives"] = _src_ms_alternatives
OPTION_SOURCES["ms_proposed_changes"] = _src_ms_proposed_changes
PREDICATES.update(
    {
        # Only a full analysis sizes from the research; the gate's modes keep it out of a quick check.
        "ms_full_sizing": _pred_always,
        "ms_founder_alternatives": _pred_ms_alternatives,
        "ms_methodology_changed": _pred_parent_answered("ms_methodology", "change_methodology"),
        "ms_correction_requested": _pred_parent_answered("ms_methodology", "correct_data"),
        "ms_implausible_pct_scale": _pred_ms_pct_scale,
        # Opened by market_sizing.py when it needs the period of a founder's figure (or by the model).
        "ms_period_unknown": _pred_always,
        "ms_revise_chosen": _pred_parent_answered("ms_revision", "revise"),
    }
)


# --- ic-sim -----------------------------------------------------------------------------------------

# The scored verdicts ic-sim confirms before writing up (`asked_gate_check.DECLINES`, held equal by a test).
IC_DECLINES = ("pass", "hard_pass")


def _pred_ic_verdict_decline(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    """Owed while this run's `score_dimensions.json` scores a decline. No file yet: not owed. A file that
    cannot be read, or that carries another run's id, cannot decide it: raised, so the settle pass leaves an
    open question open (a held decline is never closed on a file it could not read) and `open` refuses loudly
    rather than answering "not owed"."""
    if ctx.run_dir is None:
        return False
    path = os.path.join(ctx.run_dir, "score_dimensions.json")
    try:
        scores = _run_status.read_json(path)
    except ValueError as e:
        raise Unimplemented(f"this run's scores cannot be read ({e})", code="GATE_UNDECIDABLE") from e
    if scores is None:
        return False
    meta = scores.get("metadata") if isinstance(scores, dict) else None
    rid = meta.get("run_id") if isinstance(meta, dict) else None
    if rid != ctx.paths.run_id:
        raise Unimplemented(
            f"{path} carries run id {rid!r}, not this run's {ctx.paths.run_id!r}; score this run first",
            code="GATE_UNDECIDABLE",
        )
    summary = scores.get("summary")
    return isinstance(summary, dict) and summary.get("verdict") in IC_DECLINES


PREDICATES["ic_verdict_decline"] = _pred_ic_verdict_decline


def owed(ctx: Ctx, g: dict[str, Any], instance: str | None) -> bool:
    if ctx.mode is not None and ctx.mode not in g["modes"]:
        return False
    fn = PREDICATES.get(g["owed"])
    if fn is None:
        raise Unimplemented(f"owed predicate {g['owed']!r} is not implemented yet")
    return fn(ctx, g, instance)


# Declarative binders: the files a bound answer confirmed, fingerprinted as canonical JSON.
BINDERS: dict[str, dict[str, Any]] = {
    # The approach the question names, and nothing else: methodology.json later takes the review's skip
    # record, the revision record, founder notes and accepted warnings, and Step 5 may write a scope note
    # into its rationale. None of those is a different approach.
    "ms_methodology_files": {
        "kind": "json_fingerprint",
        "files": ("methodology.json",),
        "exclude": ("metadata",),
        "include": ("approach_chosen",),
    },
    "ic_score_dimensions": {"kind": "json_fingerprint", "files": ("score_dimensions.json",), "exclude": ("metadata",)},
    "ct_cap_base_fields": {"kind": "json_fingerprint", "files": ("inputs.json",), "exclude": ("metadata",)},
    "cp_landscape_draft": {"kind": "json_fingerprint", "files": ("landscape_draft.json",), "exclude": ("metadata",)},
    # inputs.json as apply_corrections.py normalises it, minus the two cash paths: a cash follow-up changes
    # only those, so it never re-asks the values review.
    "fmr_inputs_minus_cash": {
        "kind": "fmr_normalised_inputs",
        "files": ("inputs.json",),
        "exclude": ("metadata",),
        "drop": ("cash.current_balance", "cash.balance_date"),
    },
}


def binding(ctx: Ctx, name: str | None) -> dict[str, Any] | None:
    if name is None:
        return None
    spec = BINDERS.get(name)
    if spec is not None and spec["kind"] == "fmr_normalised_inputs":
        return _fmr_binding(ctx, name, spec)
    if spec is None or spec["kind"] != "json_fingerprint":
        raise Unimplemented(f"binder {name!r} is not implemented yet")
    run_dir = ctx.run_dir
    if run_dir is None:
        return None
    docs = []
    for rel in spec["files"]:
        try:
            doc = _run_status.read_json(os.path.join(run_dir, rel))
        except ValueError:
            doc = {"unreadable": True}
        if isinstance(doc, dict):
            doc = {k: v for k, v in doc.items() if k not in spec["exclude"]}
            if "include" in spec:
                doc = {k: v for k, v in doc.items() if k in spec["include"]}
        docs.append(doc)
    canon = json.dumps(docs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"binder": name, "fingerprint": hashlib.sha256(canon.encode("utf-8")).hexdigest()}


def _fmr_pipeline() -> Any:
    """apply_corrections.py, loaded by path: the binder normalises with the producer's own steps, never a copy.
    Its import puts its own dir first on `sys.path` and caches its sibling `_run_ref`; both are put back, so a
    same-named module of another skill still resolves to its own."""
    mod = sys.modules.get("_fmr_apply_corrections")
    if mod is not None:
        return mod
    path = os.path.join(_FMR_SCRIPTS, "apply_corrections.py")
    if not os.path.isfile(path):
        raise Unimplemented(f"the financial-model-review normaliser is not reachable at {path}")
    saved_path, saved_ref = list(sys.path), sys.modules.get("_run_ref")
    try:
        spec = importlib.util.spec_from_file_location("_fmr_apply_corrections", path)
        if spec is None or spec.loader is None:
            raise Unimplemented(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved_path
        if saved_ref is None:
            sys.modules.pop("_run_ref", None)
        else:
            sys.modules["_run_ref"] = saved_ref
    sys.modules["_fmr_apply_corrections"] = mod
    return mod


def _fmr_binding(ctx: Ctx, name: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    run_dir = ctx.run_dir
    if run_dir is None:
        return None
    ac = _fmr_pipeline()
    try:
        doc = _run_status.read_json(os.path.join(run_dir, "inputs.json"))
    except ValueError:
        doc = {"unreadable": True}
    if isinstance(doc, dict):
        doc = copy.deepcopy({k: v for k, v in doc.items() if k not in spec["exclude"]})
        # Not `_normalize_to_usd`: it converts only the fields a call names in `ils_fields`, which the
        # document does not record, so the binder cannot repeat it; every --set call passes none.
        ac._coerce_state(doc)
        ac._canonicalize_time_series(doc)
        ac._strip_row_ids(doc)
        for dotted in spec["drop"]:
            head, _, leaf = dotted.rpartition(".")
            parent = ac._deep_get(doc, head) if head else doc
            if isinstance(parent, dict):
                parent.pop(leaf, None)
    canon = json.dumps([doc], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"binder": name, "fingerprint": hashlib.sha256(canon.encode("utf-8")).hexdigest()}


FMR_HISTORY = "extraction_corrections.history.jsonl"
_HISTORY_TS = "%Y-%m-%dT%H:%M:%S.%fZ"


def _fmr_history(ctx: Ctx) -> list[dict[str, Any]]:
    """This run's lines of the corrections history, oldest first. A torn line is skipped, never refused."""
    if ctx.run_dir is None:
        return []
    out = []
    try:
        with open(os.path.join(ctx.run_dir, FMR_HISTORY), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("run_id") == ctx.paths.run_id:
                    out.append(rec)
    except OSError:
        return []
    return out


def _after_open(rec: dict[str, Any], entry: dict[str, Any]) -> bool:
    """The call was made after the question was opened. Times are parsed, never compared as strings."""
    from datetime import datetime  # noqa: PLC0415

    try:
        made = datetime.strptime(str(rec.get("timestamp")), _HISTORY_TS)
        opened = datetime.strptime(str(entry.get("opened_at")), _HISTORY_TS)
    except ValueError:
        return False
    return made > opened


def _req_fmr_corrections(ctx: Ctx, entry: dict[str, Any]) -> dict[str, Any] | None:
    """A corrections call for this run, by the founder or the host (never the inputs-review sub-agent), that
    changed something, made after the question was opened."""
    for rec in reversed(_fmr_history(ctx)):
        if (
            rec.get("origin") in ("external", "upload", "chat")
            and (rec.get("changed_count") or 0) >= 1
            and _after_open(rec, entry)
        ):
            return {"origin": rec["origin"], "history_seq": rec.get("seq")}
    return None


def _req_fmr_cash(ctx: Ctx, entry: dict[str, Any]) -> dict[str, Any] | None:
    """A call for this run, in chat or by the host, that set both cash paths after the follow-up was opened."""
    for rec in reversed(_fmr_history(ctx)):
        paths = {c.get("path") for c in rec.get("corrections") or [] if isinstance(c, dict)}
        if (
            rec.get("origin") in ("chat", "external")
            and {"cash.current_balance", "cash.balance_date"} <= paths
            and _after_open(rec, entry)
        ):
            return {"origin": rec["origin"], "history_seq": rec.get("seq")}
    return None


# `requires` checks on an option. Each reads evidence a script wrote and returns what it found (stored on the
# answer as `current.evidence`), or nothing when the evidence is missing.
REQUIRES: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any] | bool | None] | None] = {
    "fmr_corrections_audit": _req_fmr_corrections,
    "fmr_cash_audit": _req_fmr_cash,
}


def _requires_met(ctx: Ctx, option: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any] | None:
    name = option["requires"]
    if name is None:
        return None
    fn = REQUIRES.get(name)
    if fn is None:
        raise Unimplemented(f"requires check {name!r} is not implemented yet")
    got = fn(ctx, entry)
    if not got:
        raise GateRejection("REQUIRES_UNMET", f"{option['id']!r} needs evidence this run does not have ({name})")
    return got if isinstance(got, dict) else None


def unimplemented() -> dict[str, list[str]]:
    """Every registry name with no implementation yet. Pinned by a test; each skill's wiring shrinks it."""
    preds = sorted({g["owed"] for g in GATES.values()} - {k for k, v in PREDICATES.items() if v})
    sources = sorted({g["option_source"] for g in GATES.values() if g["option_source"]} - _impl(OPTION_SOURCES))
    binders = sorted(
        {g["binds"] for g in GATES.values() if g["binds"]}
        - {k for k, v in BINDERS.items() if v["kind"] != "unimplemented"}
    )
    reqs = sorted({o["requires"] for g in GATES.values() for o in _all_options(g) if o["requires"]} - _impl(REQUIRES))
    return {"predicates": preds, "option_sources": sources, "binders": binders, "requires": reqs}


def _impl(table: dict[str, Any]) -> set[str]:
    return {k for k, v in table.items() if v is not None}


def _all_options(g: dict[str, Any]) -> list[dict[str, Any]]:
    opts = g["options"]
    if isinstance(opts, dict):
        return [o for t in opts.values() for o in t]
    return list(opts)


# --- registry validation (the loader fails closed) ------------------------------------------------------


def validate_registry(gates: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    keys = None
    for gid, g in gates.items():
        if keys is None:
            keys = set(g)
        elif set(g) != keys:
            problems.append(f"{gid}: keys differ from the first entry")
        if not GATE_ID_RE.match(gid):
            problems.append(f"{gid}: malformed gate id")
        if g["skill"] not in (*SKILLS, SHARED):
            problems.append(f"{gid}: unknown skill {g['skill']!r}")
        if g["kind"] not in KINDS:
            problems.append(f"{gid}: unknown kind")
        if g["asked_check"] not in ASKED_CHECKS:
            problems.append(f"{gid}: unknown asked_check")
        if g["writer"] not in WRITERS:
            problems.append(f"{gid}: unknown writer {g['writer']!r}")
        if any(m not in _run_status.MODES for m in g["modes"]):
            problems.append(f"{gid}: unknown mode")
        if g["binds"] is not None and g["binds"] not in BINDERS:
            problems.append(f"{gid}: unknown binder")
        option_sets = g["options"].values() if isinstance(g["options"], dict) else [g["options"]]
        for opts in option_sets:
            ids = [o["id"] for o in opts]
            if len(set(ids)) != len(ids):
                problems.append(f"{gid}: duplicate option ids")
            for o in opts:
                if not OPTION_ID_RE.match(o["id"]):
                    problems.append(f"{gid}: option id {o['id']!r} outside [a-z0-9_+.-]")
                for kind, targets in (o["effects"] or {}).items():
                    if kind not in ("opens", "reopens", "closes"):
                        problems.append(f"{gid}: unknown effect {kind!r}")
                    problems.extend(
                        f"{gid}: effect target {t!r} unknown" for t in targets if not _effect_target_ok(gates, t)
                    )
                    # A gate with instances is opened per instance by its own site; an effect could only
                    # open it bare, as a key nothing can answer. It may name one static instance instead.
                    problems.extend(
                        f"{gid}: effect target {t!r} has instances"
                        for t in targets
                        if t in gates and gates[t]["instances"] is not None
                    )
        all_ids = {o["id"] for o in _all_options(g)}
        if g["no_ask_default"] is not None and g["no_ask_default"] not in all_ids:
            problems.append(f"{gid}: no_ask_default names no option")
        for reason, oid in g["defaults"]:
            if reason not in DEFAULT_REASONS:
                problems.append(f"{gid}: default reason {reason!r} not in the closed list")
            if oid is not None and oid not in all_ids:
                problems.append(f"{gid}: default {reason} names no option")
    return problems


def _effect_target_ok(gates: dict[str, dict[str, Any]], target: str) -> bool:
    """A gate id, or `gate.instance` naming one of that gate's static instances."""
    if target in gates:
        return True
    gid, _, inst = target.partition(".")
    instances = (gates.get(gid) or {}).get("instances") or {}
    return bool(inst) and inst in (instances.get("static") or ())


def _load_checked() -> None:
    problems = validate_registry(GATES)
    if problems:
        raise RegistryError("; ".join(problems[:5]))


# --- the ledger ---------------------------------------------------------------------------------------


def new_ledger(run_id: str, skill: str, surface: str) -> dict[str, Any]:
    return {
        "schema": LEDGER_SCHEMA,
        "schema_version": 1,
        "registry_version": REGISTRY_VERSION,
        "run_id": run_id,
        "skill": skill,
        "surface": surface,
        "seq": 0,
        "pre_answers": {},
        "form_batches": [],
        "notices": [],
        "gates": {},
    }


def load_ledger(paths: _run_status.RunPaths) -> dict[str, Any]:
    try:
        data = _run_status.read_json(paths.ledger)
    except ValueError as e:
        raise _run_status.RunStatusError("LEDGER_MISSING", str(e)) from e
    if not isinstance(data, dict) or data.get("schema") != LEDGER_SCHEMA:
        raise _run_status.RunStatusError("LEDGER_MISSING", f"no gate ledger at {paths.ledger}")
    return data


def _event(ledger: dict[str, Any], entry: dict[str, Any], event: str, by: str, **extra: Any) -> None:
    ledger["seq"] = int(ledger.get("seq") or 0) + 1
    entry["history"].append({"seq": ledger["seq"], "at": _run_status.now_iso(), "event": event, "by": by, **extra})


def _entry(ledger: dict[str, Any], key: str) -> dict[str, Any]:
    gates = ledger.setdefault("gates", {})
    if key not in gates:
        gate_id, instance = parse_key(key)
        gates[key] = {
            "gate": gate_id,
            "instance": instance,
            "state": None,
            "opened_at": None,
            "opened_seq": None,
            "current": None,
            "supersessions": 0,
            "replaced_after_hold": False,
            "flags": [],
            "history": [],
        }
    entry: dict[str, Any] = gates[key]
    return entry


def _open_entry(ledger: dict[str, Any], key: str, by: str, **extra: Any) -> tuple[dict[str, Any], bool]:
    """(entry, newly opened). Opening an open gate is idempotent and never re-stamps `opened_at`; opening an
    answered one does nothing at all. A recorded answer is re-asked only through `_supersede`."""
    entry = _entry(ledger, key)
    if entry["state"] is not None:
        return entry, False
    entry["state"] = "open"
    entry["opened_at"] = _run_status.now_iso()
    _event(ledger, entry, "opened", by, **extra)
    entry["opened_seq"] = ledger["seq"]
    return entry, True


def _supersede(ledger: dict[str, Any], entry: dict[str, Any], by: str, reason: str) -> None:
    """The one route that re-asks an answered gate: the answer is kept in history as `superseded`, and the
    gate re-opens with a fresh `opened_at`. Reached by a changed binding (`binding_changed`), a registered
    `reopens`, a re-asked site (`asked_again`, REASK_SUPERSEDES), a dedicated writer putting a closed question
    again (`emitted_again`), a refused compose re-opening a stage question (`compose_refused:<code>`), and
    market-sizing's compose finding the review now names more than the revision answer covered
    (`review_names_more`); and a gate `settle_owed` had closed as no longer owed that the run owes again
    (`owed_again`)."""
    _event(ledger, entry, "superseded", by, reason=reason, previous=entry["current"])
    entry["current"] = None
    entry["supersessions"] = int(entry.get("supersessions") or 0) + 1
    entry["state"] = "open"
    entry["opened_at"] = _run_status.now_iso()
    _event(ledger, entry, "reopened", by, reason=reason)
    entry["opened_seq"] = ledger["seq"]


def _key(entry: dict[str, Any]) -> str:
    return entry["gate"] if entry["instance"] is None else f"{entry['gate']}.{entry['instance']}"


def _match_option(options: list[dict[str, Any]], answer_id: str | None, label: str | None, key: str) -> dict[str, Any]:
    if answer_id is not None:
        for o in options:
            if o["id"] == answer_id:
                return o
        raise GateRejection(
            "OPTION_UNLISTED",
            f"{answer_id!r} is not an option of {key}",
            allowed=[o["id"] for o in options],
        )
    want = _norm_label(label or "")
    for o in options:
        if _norm_label(o["label"]) == want:
            return o
    raise GateRejection(
        "OPTION_UNLISTED", f"{label!r} is not an option label of {key}", allowed=[o["label"] for o in options]
    )


def _norm_label(text: str) -> str:
    return _form_reply.normalise(text)


def check_note(note: str | None) -> None:
    if note is None:
        return
    if len(note) > NOTE_MAX or "\x00" in note:
        raise GateRejection("NOTE_INVALID", f"a note must be at most {NOTE_MAX} characters with no NUL")


NONE_OF_THESE = "none_of_these"


def _resolve_options(
    ctx: Ctx, g: dict[str, Any], key: str, instance: str | None, answer_ids: list[str] | None, label: str | None
) -> list[dict[str, Any]]:
    options = options_for(g, instance, ctx)
    every = list(_pick(g["options"], instance) or ())
    if answer_ids and len(answer_ids) > 1 and not g["multi"]:
        raise GateRejection("OPTION_UNLISTED", f"{key} takes one option, not {len(answer_ids)}")
    if answer_ids and len(answer_ids) > 1 and NONE_OF_THESE in answer_ids:
        raise GateRejection("OPTION_UNLISTED", f"{key}: {NONE_OF_THESE!r} is answered alone")
    if answer_ids:
        picked = []
        for aid in answer_ids:
            if not OPTION_ID_RE.match(aid):
                raise GateRejection("ID_MALFORMED", f"{aid!r} is not an option id")
            if aid not in {o["id"] for o in options} and aid in {o["id"] for o in every}:
                raise GateRejection("OPTION_SKILL", f"{aid!r} is not offered by {ctx.skill}")
            picked.append(_match_option(options, aid, None, key))
        return picked
    if g["multi"] and label and ", " in label:
        picked = [_match_option(options, None, part, key) for part in label.split(", ")]
        if any(o["id"] == NONE_OF_THESE for o in picked):
            raise GateRejection("OPTION_UNLISTED", f"{key}: {NONE_OF_THESE!r} is answered alone")
        return picked
    return [_match_option(options, None, label, key)]


def _current(
    options: list[dict[str, Any]],
    value: str | None,
    note: str | None,
    *,
    resolution: str,
    default_reason: str | None = None,
    basis: str | None = None,
    bound: dict[str, Any] | None = None,
    asked_evidence: str | None = None,
    held: bool = False,
) -> dict[str, Any]:
    cur = {
        "answer": ", ".join(o["label"] for o in options) if options else None,
        "answer_id": ",".join(o["id"] for o in options) if options else None,
        "value": value,
        "note": note,
        "answered_at": _run_status.now_iso(),
        "resolution": resolution,
        "default_reason": default_reason,
        "resolution_basis": basis,
        "binding": bound,
    }
    if held:
        cur["asked_evidence"] = asked_evidence
    return cur


def _terminal(entry: dict[str, Any]) -> bool:
    return entry["state"] in ("answered", "not_owed")


def _same(entry: dict[str, Any], options: list[dict[str, Any]], value: str | None) -> bool:
    cur = entry["current"] or {}
    return cur.get("answer_id") == ",".join(o["id"] for o in options) and cur.get("value") == value


def _apply_effects(ctx: Ctx, ledger: dict[str, Any], option: dict[str, Any], key: str, by: str) -> None:
    for kind, targets in (option["effects"] or {}).items():
        for target in targets:
            if kind == "opens":
                _open_entry(ledger, target, by, reason=f"opened_by:{key}")
            elif kind == "reopens":
                entry = _entry(ledger, target)
                if entry["state"] == "open":
                    continue
                if entry["state"] is None:
                    _open_entry(ledger, target, by, reason=f"reopened_by:{key}")
                else:
                    _supersede(ledger, entry, by, f"reopened_by:{key}")
            elif kind == "closes":
                entry = ledger.get("gates", {}).get(target)
                if entry is not None and entry["state"] == "open":
                    entry["state"] = "not_owed"
                    entry["current"] = _current(
                        [], None, None, resolution="not_applicable", basis="script", default_reason=None
                    )
                    _event(ledger, entry, "closed", by, reason=f"closed_by:{key}")


def resolve_default(gate_id: str, g: dict[str, Any], reason: str | None, answer_id: str | None) -> str | None:
    """The option a default with this reason records, or DEFAULT_REASON_INVALID.

    `asked_not_to_be_asked` only where the gate has a `no_ask_default`, and always that option.
    `stated_in_request` names the stated option. Any other reason only where the registry lists it.
    """
    listed = dict(g["defaults"])
    if reason not in DEFAULT_REASONS:
        raise GateRejection("DEFAULT_REASON_INVALID", f"{reason!r} is not a default reason")
    if reason == "asked_not_to_be_asked":
        if g["no_ask_default"] is None:
            raise GateRejection("DEFAULT_REASON_INVALID", f"{gate_id} has no default for a founder not to be asked")
        if answer_id not in (None, g["no_ask_default"]):
            raise GateRejection("DEFAULT_REASON_INVALID", f"{gate_id}'s default is {g['no_ask_default']!r}")
        return str(g["no_ask_default"])
    if reason not in listed:
        raise GateRejection("DEFAULT_REASON_INVALID", f"{gate_id} does not take the default reason {reason!r}")
    if listed[reason] is not None:
        if answer_id not in (None, listed[reason]):
            raise GateRejection("DEFAULT_REASON_INVALID", f"{gate_id}'s {reason} default is {listed[reason]!r}")
        return str(listed[reason])
    if answer_id is None and reason != "producer_default_disclosed":
        raise GateRejection("DEFAULT_REASON_INVALID", f"{reason} on {gate_id} needs the option it took")
    return answer_id


def _guard_finished(status: dict[str, Any], g: dict[str, Any]) -> None:
    state = status.get("status")
    if state == "refused" or (state == "complete" and not g["reopens_complete"]):
        raise GateRejection("RUN_FINISHED", f"the run is {state}; its gates can no longer change")


def record(
    ctx: Ctx,
    ledger: dict[str, Any],
    key: str,
    *,
    answer_ids: list[str] | None = None,
    label: str | None = None,
    value: str | None = None,
    note: str | None = None,
    resolution: str = "answered",
    default_reason: str | None = None,
    basis: str | None = None,
    by: str = RECORDER,
    after_hold: bool = False,
    asked_evidence: str | None = None,
    writer: str = RECORDER,
    bound: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and record one answer into `ledger` (in memory). Raises GateRejection with nothing changed
    in the caller's on-disk files; the caller writes only when every segment passed. `bound` is a binding
    the writer computed itself, for a gate whose confirmed content only it can see; otherwise the
    registry's binder is used."""
    if asked_evidence is not None and asked_evidence not in SCRIPT_ASKED_EVIDENCE:
        raise ValueError(f"asked_evidence {asked_evidence!r} is not a value a script records")
    gate_id, instance, g = check_key(key, ctx.skill)
    if g["writer"] != writer:
        raise GateRejection(
            "WRITER_IS_OTHER_SCRIPT", f"{gate_id} is recorded by {g['writer']}; run that script", writer=g["writer"]
        )
    _guard_finished(ctx.status, g)
    check_note(note)
    reopening = ctx.status.get("status") == "complete" and g["reopens_complete"]
    if not owed(ctx, g, instance):
        raise GateRejection("GATE_NOT_OWED", f"{key} does not apply to this run")
    if resolution == "default_taken":
        picked = resolve_default(gate_id, g, default_reason, answer_ids[0] if answer_ids else None)
        answer_ids = [picked] if picked else None
    options = _resolve_options(ctx, g, key, instance, answer_ids, label) if (answer_ids or label) else []
    if resolution == "answered" and not options:
        raise GateRejection("OPTION_UNLISTED", f"{key} needs an option")
    takes_value = any(o["takes_value"] for o in options)
    if value is not None and value.strip() == VALUE_SLOT:
        # The `<text>` slot of a printed `answer_command`, copied as it stands, is no value. Only that exact
        # token: a real value may look like `<5` or `<n/a>`.
        value = None
    if takes_value and (value is None or value == ""):
        raise GateRejection("VALUE_REQUIRED", f"{key}: {options[0]['id']!r} takes a value (--value)")
    if not takes_value and value is not None and options:
        raise GateRejection("VALUE_NOT_ALLOWED", f"{key}: {options[0]['id']!r} takes no value")
    entry = _entry(ledger, key)
    held = gate_id in HELD_GATES
    if after_hold and not held:
        raise GateRejection("AFTER_HOLD_NOT_HELD", f"{gate_id} is not a gate a hook holds; --after-hold does not apply")
    replacing_after_hold = False
    prior = entry["current"]
    if entry["state"] is not None and _terminal(entry):
        cur = entry["current"] or {}
        # Checked first: the same answer to a changed artifact is a new confirmation, not a repeat.
        stale = cur.get("binding") is not None and _binding_now(ctx, g, bound) not in (None, cur.get("binding"))
        same = bool(options) and _same(entry, options, value) and cur.get("resolution") == resolution
        if same and not stale and not after_hold:
            if note is None or note == cur.get("note"):
                return {"key": key, "unchanged": True, "state": entry["state"]}
            cur["note"] = note
            _event(ledger, entry, "note_added", by, note=note)
            return {"key": key, "unchanged": False, "state": entry["state"], "answer_id": cur.get("answer_id")}
        if after_hold:
            if entry.get("replaced_after_hold") and not stale:
                raise GateRejection("AFTER_HOLD_USED", f"{gate_id}'s answer was already replaced after a hold this run")
            replacing_after_hold = not entry.get("replaced_after_hold")
        if stale:
            _supersede(ledger, entry, by, "binding_changed")
        elif replacing_after_hold or (cur.get("resolution") == "default_taken" and resolution == "answered"):
            pass
        else:
            hint = ""
            if gate_id in HELD_GATES and not answered_by_request(ledger, key):
                # The one way a held step's answer is replaced: the founder answered the question the hold
                # put. Never offered over an answer the request carried.
                hint = "; if this step was just held for this question, record the founder's answer with --after-hold"
            raise GateRejection(
                "ANSWER_STANDS",
                f"{key} was already answered {cur.get('answer_id')!r}; a recorded answer stands{hint}",
                current=cur.get("answer_id"),
            )
    elif after_hold:
        raise GateRejection("AFTER_HOLD_NO_ANSWER", f"{key} has no recorded answer for --after-hold to replace")
    evidence = None
    for o in options:
        evidence = _requires_met(ctx, o, entry) or evidence
    if entry["state"] is None:
        _open_entry(ledger, key, by, reason="implicit")
    if replacing_after_hold:
        _event(ledger, entry, "replaced_after_hold", by, previous=prior)
        entry["replaced_after_hold"] = True
        asked_evidence = "after_hold"
    terminal = all(o["terminal"] for o in options) if options else True
    entry["current"] = _current(
        options,
        value,
        note,
        resolution=resolution,
        default_reason=default_reason,
        basis=basis,
        bound=_binding_now(ctx, g, bound) if terminal else None,
        asked_evidence=asked_evidence,
        held=g["asked_check"] == "since_invocation",
    )
    if evidence is not None:
        entry["current"]["evidence"] = evidence
    if resolution == "not_applicable":
        entry["state"] = "not_owed"
        _event(ledger, entry, "not_applicable", by, basis=basis, reason=note)
    else:
        entry["state"] = "answered" if terminal else "open"
        event = "default_taken" if resolution == "default_taken" else "answered"
        _event(ledger, entry, event, by, answer_id=entry["current"]["answer_id"], value=value, note=note)
    for o in options:
        _apply_effects(ctx, ledger, o, key, by)
    if reopening:
        _reopen_complete(ctx.status, key, g)
    declined = any(o["declines"] for o in options)
    return {"key": key, "state": entry["state"], "answer_id": entry["current"]["answer_id"], "declined": declined}


def _binding_now(ctx: Ctx, g: dict[str, Any], given: dict[str, Any] | None) -> dict[str, Any] | None:
    return given if given is not None else binding(ctx, g["binds"])


def _reopen_complete(status: dict[str, Any], key: str, g: dict[str, Any]) -> None:
    """A `reopens_complete` answer on a complete run: a new revision, whose reports are not yet final,
    and a new invocation that starts at the reopening gate."""
    status["revision"] = int(status.get("revision") or 0) + 1
    status["coaching"] = None
    status["deliverables"] = None
    status["deliverables_status"] = None
    # The hand-over belongs to the revision it handed over; the closer stamps the new one.
    status["handed_over_at"] = None
    _run_status.set_state(status, "running", "RUNNING")
    _run_status.open_invocation(status, "reopen", {"gate": key, "step": g["step"], "reason": "reopened"})


# --- pre-answers ------------------------------------------------------------------------------------

_LINE_RE = re.compile(r"^FS_HOST_(?P<kw>[A-Z_]+)(?P<rest>.*)$")


def parse_request(text: str, skill: str) -> tuple[str | None, dict[str, dict[str, Any]], list[dict[str, str]]]:
    """(host run id or None, pre-answers by gate key, invalid lines). Lines not starting `FS_HOST_` are
    ignored. Within one request the last line for a key wins (an answer and a note separately). Checked
    against the registry only: whether a script-built option exists is `open`'s check."""
    run_id: str | None = None
    pre: dict[str, dict[str, Any]] = {}
    notes: dict[str, tuple[str, str]] = {}
    bad: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("FS_HOST_"):
            continue
        m = _LINE_RE.match(line)
        kw, rest = (m.group("kw"), m.group("rest")) if m else ("", "")
        try:
            if kw == "RUN_ID" and rest.startswith("="):
                if run_id is not None and run_id != rest[1:]:
                    raise ValueError("a second, different FS_HOST_RUN_ID line")
                run_id = rest[1:]
                if not _run_status.valid_run_id(run_id):
                    raise ValueError("the run id does not match the run-id grammar")
                continue
            if kw not in ("ANSWER", "VALUE", "NOTE") or not rest.startswith(" ") or "=" not in rest:
                raise ValueError("not a recognised FS_HOST_ line")
            key, _, payload = rest[1:].partition("=")
            key = key.strip()
            if key in BARE_PRE_ANSWER_GATES:
                # The bare key answers every instance of the gate (BARE_PRE_ANSWER_GATES).
                gate_id, instance, g = key, None, gate_def(key)
                if g["skill"] not in (skill, SHARED):
                    raise GateRejection("GATE_FOREIGN", f"{key!r} belongs to {g['skill']}, not {skill}")
            else:
                gate_id, instance, g = check_key(key, skill)
            if kw == "NOTE":
                check_note(payload)
                notes[key] = (payload, line)
                continue
            option_text, value = payload, None
            if kw == "VALUE":
                if " | " not in payload:
                    raise ValueError("FS_HOST_VALUE needs `<option_id> | <value>`")
                option_text, value = payload.split(" | ", 1)
            ids = [p.strip() for p in option_text.split(",")] if g["multi"] else [option_text.strip()]
            for oid in ids:
                if not OPTION_ID_RE.match(oid):
                    raise ValueError(f"{oid!r} is not an option id")
                listed = {o["id"]: o for o in fixed_options(g, instance, skill)}
                if g["option_source"] is None and oid not in listed:
                    raise ValueError(f"{oid!r} is not an option of {key}")
                o = listed.get(oid)
                if o is not None:
                    if not o["pre_answerable"]:
                        raise ValueError(f"{oid!r} cannot be answered ahead")
                    if kw == "VALUE" and not o["takes_value"]:
                        raise ValueError(f"{oid!r} takes no value; use FS_HOST_ANSWER")
                    if kw == "ANSWER" and o["takes_value"]:
                        raise ValueError(f"{oid!r} takes a value; use FS_HOST_VALUE")
            # The last line for a key wins: a resume request carries the original lines first, then the
            # host's new answer.
            pre[key] = {"option_id": ",".join(ids), "value": value, "note": None, "raw": [line]}
        except (ValueError, GateRejection) as e:
            bad.append({"line": line, "reason": str(e)})
    for key, (note, line) in notes.items():
        if key not in pre:
            bad.append({"line": line, "reason": f"a note for {key} needs an answer line for the same gate"})
            continue
        pre[key]["note"] = note
        pre[key]["raw"].append(line)
    return run_id, pre, bad


def store_pre_answers(ledger: dict[str, Any], pre: dict[str, dict[str, Any]], by: str) -> None:
    """Merge validated pre-answers: added, identical no-op, replaced while the gate is open, ignored once
    the gate has an answer (the recorded answer stands; the line is listed in `notices`)."""
    stored = ledger.setdefault("pre_answers", {})
    for key, new in pre.items():
        old = stored.get(key)
        same = old is not None and (old["option_id"], old["value"], old["note"]) == (
            new["option_id"],
            new["value"],
            new["note"],
        )
        if same:
            continue
        if key in BARE_PRE_ANSWER_GATES:
            # No entry of its own: each instance takes it when it is opened (`pending_pre_answer`).
            stored[key] = {**new, "stored_at": _run_status.now_iso(), "applied_at": None}
            continue
        entry = _entry(ledger, key)
        if entry["state"] is not None and _terminal(entry):
            _event(ledger, entry, "pre_answer_ignored", by, raw=new["raw"])
            ledger.setdefault("notices", []).append({"code": "PRE_ANSWER_IGNORED", "gate": key, "lines": new["raw"]})
            continue
        stored[key] = {**new, "stored_at": _run_status.now_iso(), "applied_at": None}
        _event(ledger, entry, "pre_answer_superseded" if old else "pre_answer_stored", by, raw=new["raw"])


def pending_pre_answer(ledger: dict[str, Any], key: str) -> dict[str, Any] | None:
    """A stored, not yet applied pre-answer for `key`. A gate's own writer applies it.

    For an instance of a BARE_PRE_ANSWER_GATES gate with no line of its own, the bare line is copied to
    the instance's key the first time it is asked for, so each instance applies (and records) it once."""
    stored = ledger.get("pre_answers") or {}
    pa = stored.get(key)
    gate_id, _, instance = key.partition(".")
    if pa is None and instance and gate_id in BARE_PRE_ANSWER_GATES:
        bare = stored.get(gate_id)
        if isinstance(bare, dict):
            pa = {**bare, "applied_at": None, "from": gate_id}
            ledger.setdefault("pre_answers", {})[key] = pa
    if isinstance(pa, dict) and pa.get("applied_at") is None:
        return pa
    return None


def _apply_pre_answer(ctx: Ctx, ledger: dict[str, Any], key: str, by: str) -> str | None:
    """Apply a stored pre-answer through the normal record path. Returns "applied", "unlisted" or None."""
    pa = pending_pre_answer(ledger, key)
    if pa is None:
        return None
    gate_id, instance, g = check_key(key, ctx.skill)
    entry = _entry(ledger, key)
    ids = pa["option_id"].split(",")
    listed = {o["id"] for o in options_for(g, instance, ctx)}
    if any(i not in listed for i in ids):
        if "pre_answer_unlisted" not in entry["flags"]:
            entry["flags"].append("pre_answer_unlisted")
            _event(ledger, entry, "pre_answer_unlisted", by, raw=pa["raw"])
        return "unlisted"
    try:
        record(
            ctx,
            ledger,
            key,
            answer_ids=ids,
            value=pa["value"],
            note=pa["note"],
            by=by,
            asked_evidence="host_line",
        )
    except GateRejection as e:
        # The line names an option whose evidence this run does not have (financial-model-review's
        # `corrections_applied` with no corrections call on record): the gate stays open and is asked.
        if e.code != "REQUIRES_UNMET":
            raise
        if "pre_answer_unlisted" not in entry["flags"]:
            entry["flags"].append("pre_answer_unlisted")
            _event(ledger, entry, "pre_answer_unlisted", by, raw=pa["raw"], reason="requires_unmet")
            ledger.setdefault("notices", []).append(
                {"code": "PRE_ANSWER_NOT_APPLIED", "gate": key, "lines": pa["raw"], "reason": str(e)}
            )
        return "unlisted"
    _mark_applied(ledger, entry, pa, by)
    return "applied"


def _mark_applied(ledger: dict[str, Any], entry: dict[str, Any], pa: dict[str, Any], by: str) -> None:
    """Stamp a stored pre-answer as applied, at the very time its record carries: `answered_at` equal to
    `applied_at` is how the ledger shows the current answer came from the request (`answered_by_request`)."""
    pa["applied_at"] = (entry.get("current") or {}).get("answered_at") or _run_status.now_iso()
    _event(ledger, entry, "pre_answer_applied", by, raw=pa["raw"])
    if "pre_answer_unlisted" in entry["flags"]:
        entry["flags"].remove("pre_answer_unlisted")


def answered_by_request(ledger: dict[str, Any], key: str) -> bool:
    """Was this gate's current answer applied from a line the request carried, rather than asked?"""
    entry = (ledger.get("gates") or {}).get(key)
    pa = (ledger.get("pre_answers") or {}).get(key)
    cur = (entry or {}).get("current") or {}
    if not isinstance(pa, dict) or entry is None or entry.get("state") != "answered":
        return False
    return bool(pa.get("applied_at")) and pa.get("applied_at") == cur.get("answered_at")


# --- the status view ------------------------------------------------------------------------------


def _gate_view(ctx: Ctx, gate_id: str, instance: str | None, entry: dict[str, Any] | None) -> dict[str, Any]:
    g = GATES[gate_id]
    try:
        opts = options_for(g, instance, ctx)
    except Unimplemented:
        opts = fixed_options(g, instance, ctx.skill)
    reached = entry is not None and entry.get("state") in GATE_STATES
    return {
        "id": gate_id,
        "instance": instance,
        "step": g["step"],
        "kind": g["kind"],
        "asked_check": g["asked_check"],
        "question": render_question(g, instance, ctx),
        "options": [
            {"id": o["id"], "label": render_label(o, ctx), "terminal": o["terminal"]} for o in opts if o["shown"]
        ],
        "state": entry["state"] if reached and entry else NOT_REACHED,
        "current": entry["current"] if entry else None,
        "supersessions": entry["supersessions"] if entry else 0,
        "history": entry["history"] if entry else [],
    }


def _registered_keys(ctx: Ctx, ledger: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Every gate of this run's skill and mode, as (gate, instance), in registry order. A gate whose
    instances are made at run time is listed once, instance null, until one is reached."""
    touched = ledger.get("gates") or {}
    out: list[tuple[str, str | None]] = []
    mine = [g for g in GATES.values() if g["skill"] in (ctx.skill, SHARED)]
    # Before `bind` the mode is not known: only the gates every mode of the skill has are listed, and
    # `bind` completes the list for the run dir's mode.
    every_mode = {m for g in mine for m in g["modes"]}
    for gid, g in GATES.items():
        if g["skill"] not in (ctx.skill, SHARED):
            continue
        in_mode = ctx.mode in g["modes"] if ctx.mode is not None else every_mode <= set(g["modes"])
        seen = [e["instance"] for k, e in touched.items() if isinstance(e, dict) and e.get("gate") == gid]
        inst = g["instances"]
        if inst is None:
            if in_mode or seen:
                out.append((gid, None))
        elif inst.get("static") is not None:
            out.extend((gid, i) for i in inst["static"] if in_mode or i in seen)
        else:
            reached = sorted(i for i in seen if i is not None)
            out.extend((gid, i) for i in reached)
            if not reached and in_mode:
                out.append((gid, None))
    return out


def derive_status(ctx: Ctx, ledger: dict[str, Any], status: dict[str, Any], *, declined: bool = False) -> None:
    """Re-derive every gate-dependent status field from the ledger. Final states move only by the
    explicit reopen path, never here."""
    entries = [
        (k, e) for k, e in (ledger.get("gates") or {}).items() if isinstance(e, dict) and e.get("state") in GATE_STATES
    ]
    entries.sort(key=lambda ke: (ke[1].get("opened_seq") or 0, ke[0]))
    gates = ledger.get("gates") or {}
    status["gates"] = [
        _gate_view(ctx, gid, inst, gates.get(gid if inst is None else f"{gid}.{inst}"))
        for gid, inst in _registered_keys(ctx, ledger)
    ]
    status["disclosures"] = [
        d for d in (status.get("disclosures") or []) if not str(d).startswith(_DERIVED_DISCLOSURES)
    ]
    status["disclosures"] += [
        f"DEFAULT_TAKEN:{k}" for k, e in entries if (e.get("current") or {}).get("resolution") == "default_taken"
    ]
    status["disclosures"] += [f"PRE_ANSWERED:{k}" for k, _e in entries if answered_by_request(ledger, k)]
    status["disclosures"] += [d for _k, e in entries for d in option_disclosures(e)]
    status["notices"] = list(ledger.get("notices") or [])
    if status.get("status") in _run_status.FINAL_STATUSES:
        return
    if declined:
        _run_status.set_state(status, "refused", "FOUNDER_DECLINED")
        return
    open_entries = [(k, e) for k, e in entries if e["state"] == "open"]
    if open_entries:
        # A fresh question before a follow-up still pending on an earlier answer: it is what to ask next.
        fresh = [ke for ke in open_entries if ke[1]["current"] is None]
        key, entry = (fresh or open_entries)[0]
        g = GATES[entry["gate"]]
        question = render_question(g, entry["instance"], ctx)
        if "pre_answer_unlisted" in entry["flags"]:
            code = "PRE_ANSWER_UNLISTED"
        elif entry["current"] is not None:
            code = "GATE_INTERMEDIATE"
        else:
            code = "GATE_WAITING"
        _run_status.set_state(status, "waiting", code, question=question)
        status["waiting_on"] = key
        status["resumable"] = _run_status.RESUMABLE_BY_SURFACE.get(str(ledger.get("surface")), "same_session")
        status["resume_prompt"] = resume_prompt(ledger)
        return
    if status.get("coaching") == "inserted":
        _run_status.mark_complete(status)
    else:
        _run_status.set_state(status, "running", "RUNNING")


# Every disclosure derived from the ledger, stripped before each re-derivation so none is listed twice.
_DERIVED_DISCLOSURES = ("DEFAULT_TAKEN:", "PRE_ANSWERED:", "EXTRACTION_UNREVIEWED", "CORRECTIONS_SOURCE")


def option_disclosures(entry: dict[str, Any]) -> list[str]:
    """The disclosures the current answer's options carry (`discloses`); `CORRECTIONS_SOURCE` names who
    supplied the corrections, from the evidence its `requires` check found."""
    if entry.get("state") not in ("answered", "open"):
        return []
    cur = entry.get("current") or {}
    ids = str(cur.get("answer_id") or "").split(",")
    out = []
    for o in _all_options(GATES[entry["gate"]]):
        if o["id"] in ids and o["discloses"]:
            origin = (cur.get("evidence") or {}).get("origin")
            out.append(
                f"{o['discloses']}:{origin}" if o["discloses"] == "CORRECTIONS_SOURCE" and origin else o["discloses"]
            )
    return out


def resume_prompt(ledger: dict[str, Any]) -> str:
    lines = [f"Resume the {ledger['skill']} run.", f"FS_HOST_RUN_ID={ledger['run_id']}"]
    for pa in (ledger.get("pre_answers") or {}).values():
        if pa.get("from"):
            continue  # an instance's copy of a bare line, which is listed once, as it was sent
        lines.extend(pa.get("raw") or [])
    return "\n".join(lines) + "\n"


# --- transactions ------------------------------------------------------------------------------------


def transact(
    paths: _run_status.RunPaths, fn: Callable[[Ctx, dict[str, Any], dict[str, Any]], Any], *, skill: str | None = None
) -> Any:
    """Run `fn(ctx, ledger, status)` under the run lock. Ledger first, then status; a rejection writes
    nothing. `fn` may return (result, declined) or a plain result."""
    with _run_status.run_lock(paths):
        status = _run_status.load_status(paths)
        if status is None:
            raise _run_status.RunStatusError("RUN_NOT_FOUND", f"no run status at {paths.status}")
        ledger = load_ledger(paths)
        ctx = Ctx(paths, status, skill or str(ledger.get("skill")))
        ctx.ledger = ledger
        before_ledger = copy.deepcopy(ledger)
        before_status = copy.deepcopy(status)
        # Before and after every transaction, read-only ones included: a gate the run stopped owing since the
        # last write is closed, and one it owes again is re-opened, before anything reads or records it.
        settle_owed(ctx, ledger, "script")
        out = fn(ctx, ledger, status)
        declined = bool(out.get("declined")) if isinstance(out, dict) else False
        settle_owed(ctx, ledger, "script")
        if ledger != before_ledger:
            _run_status.atomic_write_json(paths.ledger, ledger)
            derive_status(ctx, ledger, status, declined=declined)
        if status != before_status:
            _run_status.write_status(paths, status)
        return out


def _shown_option(o: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    out = {"id": o["id"], "label": render_label(o, ctx), "takes_value": o["takes_value"]}
    if out["label"] != o["label"]:
        # The asking step fills the slots from what it has on screen; the template says where they go.
        out["label_template"] = o["label"]
    return out


def needs_input(ctx: Ctx, ledger: dict[str, Any], key: str) -> dict[str, Any]:
    gate_id, instance = parse_key(key)
    g = GATES[gate_id]
    opts = options_for(g, instance, ctx)
    out: dict[str, Any] = {
        "gate": key,
        "step": g["step"],
        "question": render_question(g, instance, ctx),
        "options": [_shown_option(o, ctx) for o in opts if o["shown"]],
        "multi": g["multi"],
        "form_label": form_label_for(g, instance),
        "form_header": FORM_HEADERS.get(ctx.skill, ""),
        "recorded_by": g["writer"],
    }
    template = question_for(g, instance)
    if template != out["question"]:
        # The asking step fills the slots from what it has on screen; the template says where they go.
        out["question_template"] = template
    if g["writer"] == RECORDER:
        locator = f'--run-dir "{ctx.run_dir}"' if ctx.run_dir else f'--artifacts-root "{ctx.paths.artifacts_root}"'
        out["answer_command"] = (
            f'python3 "{_run_status.shared_scripts_dir()}/{RECORDER}" answer --run-id {ctx.paths.run_id} '
            f"{locator} --gate {key} --answer-id <option_id>"
        )
        if any(o["takes_value"] for o in out["options"]):
            # Filled for an option whose `takes_value` is true, dropped for the others (VALUE_NOT_ALLOWED).
            out["answer_command"] += f' --value "{VALUE_SLOT}"'
    else:
        out["answer_command"] = None
    return out


def open_gates(ctx: Ctx, ledger: dict[str, Any], keys: list[str], *, by: str = RECORDER) -> dict[str, Any]:
    """Open each owed gate (idempotent), applying a stored pre-answer where the recorder owns the gate."""
    checked = []
    for key in keys:
        gate_id, instance, g = check_key(key, ctx.skill)
        _guard_finished(ctx.status, g)
        checked.append((key, g, owed(ctx, g, instance)))
    owed_keys = [(k, g) for k, g, is_owed in checked if is_owed]
    if not owed_keys:
        return {"opened": [], "answered": [], "not_owed": [k for k, _g, _o in checked]}
    opened, applied, unlisted, waiting, answered = [], [], [], [], []
    for key, g in owed_keys:
        prior = (ledger.get("gates") or {}).get(key)
        reasked = parse_key(key)[0] in REASK_SUPERSEDES and prior is not None and _terminal(prior)
        if reasked:
            assert prior is not None
            _supersede(ledger, prior, by, "asked_again")
        entry, new = _open_entry(ledger, key, by)
        if new or reasked:
            opened.append(key)
        if entry["state"] != "open":
            answered.append(key)
            continue
        if g["writer"] == RECORDER and entry["state"] == "open":
            got = _apply_pre_answer(ctx, ledger, key, by)
            if got == "applied":
                applied.append(key)
                continue
            if got == "unlisted":
                unlisted.append(key)
        if entry["state"] == "open":
            waiting.append(key)
    header = FORM_HEADERS.get(ctx.skill, "")
    if waiting and (not ledger["form_batches"] or ledger["form_batches"][-1]["gates"] != waiting):
        ledger["form_batches"].append({"header": header, "gates": waiting, "opened_at": _run_status.now_iso()})
    out: dict[str, Any] = {
        "opened": opened,
        "answered": answered,
        "not_owed": [k for k, _g, is_owed in checked if not is_owed],
        "needs_input": [needs_input(ctx, ledger, k) for k in waiting],
    }
    if applied:
        out["applied"] = "pre_answer"
        out["applied_gates"] = applied
    if unlisted:
        out["pre_answer_unlisted"] = unlisted
    pending_other = [k for k, g in owed_keys if g["writer"] != RECORDER and pending_pre_answer(ledger, k)]
    if pending_other:
        out["pre_answer_applied_by"] = {k: GATES[parse_key(k)[0]]["writer"] for k in pending_other}
    return out


CLOSED_NOT_OWED = "not_owed"


def _closed_by_settle(entry: dict[str, Any]) -> bool:
    """The entry's last event is `settle_owed` closing it: it was never answered, only stopped being owed."""
    history = entry.get("history") or []
    last = history[-1] if history else {}
    return entry.get("state") == "not_owed" and last.get("event") == "closed" and last.get("reason") == CLOSED_NOT_OWED


def settle_owed(ctx: Ctx, ledger: dict[str, Any], by: str) -> dict[str, list[str]]:
    """Keep the ledger's open gates the ones this run owes, in memory.

    An open gate the run no longer owes is closed (`not_applicable / script`, reason `not_owed`): a follow-up
    whose parent was answered otherwise, a held decline the scores no longer make, a figure choice once the
    materials state one figure. Left open it could never be answered (refused as not owed) and would hold the
    run open. A gate closed that way that the run owes again is re-opened, so it is asked: it was never
    answered, and an enforcer must never read its closure as an answer. A predicate that cannot be evaluated
    leaves its gate as it is. Writes nothing itself; the caller writes when the ledger changed.

    A finished run (`complete` or `refused`) is left exactly as it is: its answers never move (RUN_FINISHED),
    and a gate re-opened there could never be answered. A run that reopens (financial-model-review's cash
    reply) is `running` again before the next transaction settles it."""
    closed: list[str] = []
    reopened: list[str] = []
    if ctx.status.get("status") in _run_status.FINAL_STATUSES:
        return {"closed": closed, "reopened": reopened}
    for key, entry in (ledger.get("gates") or {}).items():
        if not isinstance(entry, dict) or entry.get("gate") not in GATES:
            continue
        state = entry.get("state")
        if state != "open" and not _closed_by_settle(entry):
            continue
        g = GATES[entry["gate"]]
        if g["skill"] not in (ctx.skill, SHARED):
            continue
        try:
            owes = owed(ctx, g, entry.get("instance"))
        except Unimplemented:
            continue
        if state == "open" and not owes:
            entry["state"] = "not_owed"
            entry["current"] = _current([], None, None, resolution="not_applicable", basis="script")
            _event(ledger, entry, "closed", by, reason=CLOSED_NOT_OWED)
            closed.append(key)
        elif state == "not_owed" and owes:
            _supersede(ledger, entry, by, "owed_again")
            reopened.append(key)
    return {"closed": closed, "reopened": reopened}


def close_unowed_for_mode(ledger: dict[str, Any], mode: str, by: str) -> list[str]:
    """Close every open gate the run's mode does not owe (`not_applicable / script`), in memory. A question
    opened before `bind` set the mode (financial-model-review's cash questions on what became a quick check)
    can then no longer hold the run open. A request line still waiting for such a gate is noted as ignored."""
    closed = []
    for key, entry in (ledger.get("gates") or {}).items():
        if not isinstance(entry, dict) or entry.get("state") != "open":
            continue
        if mode in GATES[entry["gate"]]["modes"]:
            continue
        entry["state"] = "not_owed"
        entry["current"] = _current([], None, None, resolution="not_applicable", basis="script")
        _event(ledger, entry, "closed", by, reason=f"not_owed_in_mode:{mode}")
        pa = pending_pre_answer(ledger, key)
        if pa is not None:
            ledger.setdefault("notices", []).append({"code": "PRE_ANSWER_IGNORED", "gate": key, "lines": pa["raw"]})
        closed.append(key)
    return closed


def require_terminal(ctx: Ctx, ledger: dict[str, Any], key: str, *, by: str = RECORDER) -> str:
    """`ok`, `waiting` (auto-opened, binding re-checked) or `not_owed`. In memory; call inside transact."""
    gate_id, instance, g = check_key(key, ctx.skill)
    if not owed(ctx, g, instance):
        return "not_owed"
    entry = _entry(ledger, key)
    if entry["state"] is not None and _terminal(entry):
        cur = entry["current"] or {}
        if g["binds"] and cur.get("binding") is not None and binding(ctx, g["binds"]) != cur.get("binding"):
            # A finished run's answers never move through an enforcer: RUN_FINISHED, nothing written.
            _guard_finished(ctx.status, g)
            _supersede(ledger, entry, by, "binding_changed")
            return "waiting"
        return "ok"
    _guard_finished(ctx.status, g)
    _open_entry(ledger, key, by)
    if g["writer"] == RECORDER and _apply_pre_answer(ctx, ledger, key, by) == "applied":
        return "ok"
    return "waiting"


# --- the dedicated writers ---------------------------------------------------------------------------


def open_from_writer(paths: _run_status.RunPaths, keys: list[str], writer: str) -> dict[str, Any]:
    """A dedicated writer opened its gate. Stored pre-answers are left for that writer to apply."""

    def fn(ctx: Ctx, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        opened: list[str] = []
        answered: list[str] = []
        for key in keys:
            gate_id, _instance, g = check_key(key, ctx.skill)
            if g["writer"] != writer:
                raise GateRejection("WRITER_IS_OTHER_SCRIPT", f"{gate_id} is recorded by {g['writer']}")
            _guard_finished(status, g)
            entry, _new = _open_entry(ledger, key, writer)
            (opened if entry["state"] == "open" else answered).append(key)
        return {"opened": opened, "answered": answered}

    out: dict[str, Any] = transact(paths, fn)
    return out


def record_from_writer(
    paths: _run_status.RunPaths,
    key: str,
    option_id: str,
    writer: str,
    *,
    resolution: str = "answered",
    default_reason: str | None = None,
    value: str | None = None,
    bound: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def fn(ctx: Ctx, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        return record(
            ctx,
            ledger,
            key,
            answer_ids=[option_id],
            value=value,
            resolution=resolution,
            default_reason=default_reason,
            by=writer,
            writer=writer,
            bound=bound,
        )

    out: dict[str, Any] = transact(paths, fn)
    return out


def apply_writer_pre_answer(
    paths: _run_status.RunPaths,
    key: str,
    writer: str,
    offered: list[str],
    *,
    withheld: str | None = None,
    bound: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """A dedicated writer applies the answer the request carried for its open gate, against the options
    it is about to offer (`offered`, option ids), through the normal record path.

    None when there is no pending pre-answer or the gate is not open. `{"unlisted": raw}` when the line
    names an option not offered, or when the writer withholds it (`withheld`, the reason, added to the
    run's notices): the gate stays open, flagged, and is asked. Else `record()`'s result."""

    def fn(ctx: Ctx, ledger: dict[str, Any], status: dict[str, Any]) -> dict[str, Any] | None:
        gate_id, _instance, g = check_key(key, ctx.skill)
        if g["writer"] != writer:
            raise GateRejection("WRITER_IS_OTHER_SCRIPT", f"{gate_id} is recorded by {g['writer']}")
        entry = (ledger.get("gates") or {}).get(key)
        pa = pending_pre_answer(ledger, key)
        if pa is None or entry is None or entry["state"] != "open":
            return None
        ids = pa["option_id"].split(",")
        if withheld is not None or any(i not in offered for i in ids):
            if "pre_answer_unlisted" not in entry["flags"]:
                entry["flags"].append("pre_answer_unlisted")
                _event(ledger, entry, "pre_answer_unlisted", writer, raw=pa["raw"], reason=withheld)
                if withheld is not None:
                    ledger.setdefault("notices", []).append(
                        {"code": "PRE_ANSWER_NOT_APPLIED", "gate": key, "lines": pa["raw"], "reason": withheld}
                    )
            return {"unlisted": pa["raw"]}
        out = record(
            ctx,
            ledger,
            key,
            answer_ids=ids,
            value=pa["value"],
            note=pa["note"],
            by=writer,
            writer=writer,
            bound=bound,
        )
        _mark_applied(ledger, entry, pa, writer)
        return out

    result: dict[str, Any] | None = transact(paths, fn)
    return result


def supersede_from_writer(paths: _run_status.RunPaths, key: str, writer: str, reason: str) -> bool:
    """A dedicated writer found that what an answer confirmed has changed: the answer is superseded and
    the gate re-opens, so it is asked again. False when there is no recorded answer to supersede."""

    def fn(ctx: Ctx, ledger: dict[str, Any], status: dict[str, Any]) -> bool:
        gate_id, _instance, g = check_key(key, ctx.skill)
        if g["writer"] != writer:
            raise GateRejection("WRITER_IS_OTHER_SCRIPT", f"{gate_id} is recorded by {g['writer']}")
        _guard_finished(status, g)
        entry = (ledger.get("gates") or {}).get(key)
        if entry is None or not _terminal(entry):
            return False
        _supersede(ledger, entry, writer, reason)
        return True

    done: bool = transact(paths, fn)
    return done


# --- the contract ----------------------------------------------------------------------------------------


# What a host may rely on about a gate. Everything else in the registry (who records it, when it is owed,
# where its options come from, what an answer does to other gates) is internal and may change freely.
PUBLIC_GATE_FIELDS = (
    "id",
    "skill",
    "step",
    "kind",
    "instances",
    "question",
    "options",
    "multi",
    "no_ask_default",
    "asked_check",
    "mandatory",
    "modes",
)
PUBLIC_OPTION_FIELDS = ("id", "label", "terminal", "takes_value", "hidden", "pre_answerable", "only_skills")


def _public_gate(gid: str, g: dict[str, Any]) -> dict[str, Any]:
    def opt(o: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": o["id"],
            "label": o["label"],
            "terminal": o["terminal"],
            "takes_value": o["takes_value"],
            "hidden": not o["shown"],
            "pre_answerable": o["pre_answerable"],
            "only_skills": list(o["only_skills"]) if o["only_skills"] else None,
        }

    opts = g["options"]
    inst = g["instances"]
    out = {
        "id": gid,
        "skill": g["skill"],
        "step": g["step"],
        "kind": g["kind"],
        "instances": None
        if inst is None
        else {"static": list(inst["static"])}
        if inst.get("static") is not None
        else {"pattern": INSTANCE_RE.pattern},
        "question": g["question"],
        "options": {i: [opt(o) for o in t] for i, t in opts.items()}
        if isinstance(opts, dict)
        else [opt(o) for o in opts],
        "multi": g["multi"],
        "no_ask_default": g["no_ask_default"],
        "asked_check": g["asked_check"],
        "mandatory": g["mandatory"],
        "modes": list(g["modes"]),
    }
    return out


# Every code a script here can print, by where it appears. A test greps the scripts and holds this whole.
CLI_CODES = {
    "start_payload": [],
    "finish": ["FINISH_REFUSED", "MODE_MISMATCH", "MODE_NOT_OFFERED"],
    "deliverables": ["RUN_NOT_COMPLETE"],
    "bind": ["RUN_ALREADY_BOUND", "RUN_REFUSED"],
    "founder_context": ["CONTEXT_NOT_FOUND"],
    "html_writers": ["RUN_ID_MISMATCH"],
    # financial-model-review's producers: a call into a bound review dir that names no run.
    "fmr_producers": ["RUN_ID_REQUIRED"],
    # market-sizing's producers and prompt generator: a call into a bound analysis dir that names no run.
    # PERIOD_NOT_WRITTEN: the period of a founder's figure was answered but never written into inputs.json.
    "ms_producers": ["RUN_ID_REQUIRED", "PERIOD_NOT_WRITTEN"],
    # ic-sim's compose: a simulation dir that belongs to a run, whose files do not agree on which.
    "ic_producers": ["RUN_ID_REQUIRED"],
    "usage": ["USAGE"],
    "notices": ["PRE_ANSWER_IGNORED", "PRE_ANSWER_INVALID", "PRE_ANSWER_NOT_APPLIED"],
}

SHAPES = {
    "needs_input": {
        "gate": "the gate key, `<gate>` or `<gate>.<instance>`",
        "step": "the skill step that asks it",
        "question": "the question, with every slot filled or replaced by a plain request",
        "question_template": "present only when it differs: the question with the slots the asking step fills",
        "options": "[{id, label, takes_value}] of the shown options",
        "multi": "true when several options may be chosen (comma-joined ids)",
        "form_label": "the short label a question form uses",
        "form_header": "the header a question form for this skill uses",
        "recorded_by": "the script that records the answer",
        "answer_command": "the exact recording command, or null when another script records it; when a shown "
        'option takes a value it ends `--value "<text>"`, filled for that option and dropped for the others',
    },
    "blocked_by_gate": "the gate key a refused step waits on (exit 10); answer it, then run the step again",
    "invocation": "1 at a fresh start; +1 at every resume and every reopen of a complete run; never reset",
    "resumed_from": "{gate, step, reason} of the current invocation: the gate key it started at, that gate's "
    "step, and `resume` or `reopened`; null on invocation 1",
    "invocations": "append-only [{n, kind, started_at, ended_at, resumed_from, reuse, manifest, "
    "manifest_incomplete, untouched_since_resume, touched_since_resume, counts, maps_dropped}]; `kind` is `start`, "
    "`resume` or `reopen`; `manifest` is the snapshot's path relative to the artifacts root, null before `bind`. "
    "An invocation ends at the next start or reopen; at the coaching insert, unless the skill lists pages after "
    "its coaching, in which case when `deliverables_status` turns `final`; and when the run completes with no "
    "page still to come or is refused. Until then, and whenever no complete manifest and walk exist, both "
    "partitions and `counts` are null. At the end every file up to 8 MiB is hashed again: different bytes are "
    "`changed`, the same bytes with another mtime are `rewritten_identical`, and the same bytes with the same "
    "mtime count as untouched, so an identical copy that kept its mtime (`cp -p`, `copy2`, `rsync -t`) or a "
    "permission change is untouched. `counts` is {untouched, changed, rewritten_identical, added, removed}. Only "
    f"the {_run_status.KEEP_MAPS} most recent ended invocations keep their key maps; an older one has both "
    "partitions null, `maps_dropped: true` and its `counts`",
    "evidence_key": "a run-dir-relative path with every `.` and `/` replaced by `_`; paths whose keys collide take "
    "`__2`, `__3`, ... in sorted path order, skipping any key already taken (so `a_b.json`, `a/b.json`, "
    "`a.b/json` and a file named `a_b_json__2` take `a_b_json__3`, `a_b_json__2`, `a_b_json` and "
    "`a_b_json__2__2`)",
    "touched_kinds": list(_run_status.TOUCHED_KINDS),
}


def contract() -> dict[str, Any]:
    return {
        "schema": CONTRACT_SCHEMA,
        "schema_version": 1,
        "registry_version": REGISTRY_VERSION,
        "gates": {gid: _public_gate(gid, g) for gid, g in GATES.items()},
        "statuses": list(_run_status.STATUSES),
        "status_codes": {k: list(v) for k, v in _run_status.STATUS_CODES.items()},
        "last_error_codes": list(_run_status.LAST_ERROR_CODES),
        "print_only_codes": list(_run_status.PRINT_ONLY_CODES),
        "rejection_codes": list(REJECTION_CODES),
        "unreachable_codes": list(UNREACHABLE_CODES),
        "exit_codes": EXIT_CODES,
        "default_reasons": list(DEFAULT_REASONS),
        "resolutions": list(RESOLUTIONS),
        "gate_states": [*GATE_STATES, NOT_REACHED],
        "cli_codes": CLI_CODES,
        "shapes": SHAPES,
        "asked_evidence": list(ASKED_EVIDENCE),
        "request_tokens": REQUEST_TOKENS,
        "run_id_grammar": _run_status.RUN_ID_RE.pattern,
        "run_status_fields": list(_run_status.FIELDS),
        "resumable": _run_status.RESUMABLE_BY_SURFACE,
        "pages_after_coaching": {k: list(v) for k, v in _run_status.PAGES_AFTER_COACHING.items()},
        "form_reply_enabled": _form_reply.FORM_REPLY_ENABLED,
        "notes": list(CONTRACT_NOTES),
    }


def contract_text() -> str:
    return json.dumps(contract(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


_load_checked()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--dump-contract"]:
        sys.stderr.write("usage: _gates.py --dump-contract\n")
        return 2
    os.makedirs(os.path.dirname(CONTRACT_PATH), exist_ok=True)
    with open(CONTRACT_PATH, "w", encoding="utf-8") as f:
        f.write(contract_text())
    sys.stdout.write(json.dumps({"written": CONTRACT_PATH, "gates": len(GATES)}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
