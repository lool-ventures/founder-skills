#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the deck-review CHECKLIST dispatch prompt from identifiers.

The main thread runs this and sends the printed text as the sub-agent's prompt, unchanged. It used to copy
the template out of SKILL.md and fill it in by hand. Two things went wrong with that: the grader was
dispatched in the same message as the slide reviews, before the file it must read existed, and graded blind;
and a hand-written repair could tell the grader to copy the slide reviews' read token onto an old grade.
Printing from identifiers alone -- paths and the run id -- leaves nothing to write in, and this script prints
nothing until Step 4's pipe has written this run's slide reviews. The shared PreToolUse hook
(founder-skills/scripts/dispatch_prompt_check.py) holds or rewrites a dispatch that differs from the printed
prompt for its OUTPUT_PATH; SKILL.md does not depend on it, and checklist.py refuses a grade that does not
echo the slide reviews' read token whatever the hook did.

THE TOKEN IS NEVER READ HERE. checklist.py's proof that the grader read slide_reviews.json is that only a
reader of the file has its `metadata.read_token`. This script asks `_slide_reviews_file.usable` whether the
file is this run's and carries a token, and nothing else: it never reads the token, prints it, or prints
anything derived from it.

Every prompt ends with the hook's closing line, "Do NOT write any file other than OUTPUT_PATH.", which is how
the hook finds where a printed prompt ends.

EVERY OPTION TAKES A VALUE. The hook reads a generator call's context as the first positional argument after
the script and steps over every option as taking one; a store-true flag (`--pretty`, `--session-tree`) would
make it read the next word as the subcommand, and the print would count for no context. Never add one.

THE PLUGIN FOLDER NEVER COMES FROM THE SHELL. Recent Claude Desktop versions rewrite the plugin's folder
inside a shell command to its path inside the VM before the command runs, and a sub-agent's file tools are
refused a VM path. So the reference path comes from where this script runs: off a `/sessions` tree (the CLI,
cloud sessions) the absolute path is printed; on one (a local Desktop session) the prompt names the reference
by how its path ends and sends the sub-agent to the full path its own agent instructions give. Same rule as
the other skills' generators.

Usage:
    python dr_dispatch_prompt.py checklist --run-id R --handoff-agent H --review-dir-agent A --review-dir D
                                 [--correction missing-file|receipt-only|producer-rejected [--detail-file F]]

`--review-dir` is the review folder in THIS shell's namespace (read for the slide reviews); `--review-dir-agent`
/ `--handoff-agent` are what the prompt says. Exit 2 when an argument is missing or invalid. Exit 1 when the
folder belongs to another run, a file the grader reads is another run's, or this run's slide reviews are not
written yet (`SLIDE_REVIEWS_MISSING`, no context line on either stream).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _slide_reviews_file  # noqa: E402

# --- where the reference files are --------------------------------------------------------------------
#
# The cwd half is a copy of the session-tree detection in scripts/resolve_artifacts_root.py (a generator runs
# without the plugin's shared scripts on its path); tests/test_plugin_root_not_through_bash.py pins the copy.
# The folder half is a plain prefix: a plugin mounted anywhere under /sessions is on a local session.
_SESSION_TREE = re.compile(r"^(/sessions/[^/]+)/mnt(?:/|$)")
_SESSION_ROOT = re.compile(r"^/sessions/[^/]+$")


def on_session_tree(cwd: str) -> bool:
    return bool(_SESSION_TREE.match(cwd) or _SESSION_ROOT.match(cwd))


def _plugin_root() -> str:
    """The plugin folder this script runs from (four levels up from this file)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _on_session_lane() -> bool:
    """A local Desktop session: this script or the shell sits on a `/sessions` tree, where the folder above
    is a VM path a sub-agent's file tools are refused."""
    return on_session_tree(os.getcwd()) or _plugin_root().startswith("/sessions/")


_FALLBACK = (
    "If a reference path below cannot be read (refused or not found), read the same file under the plugin folder "
    "your own instructions name.\n"
)
_POINTER = (
    "Each reference file below is in your plugin folder: open it at the full path your own instructions give "
    "for it (below, each is named by how that path ends).\n"
)
_REFERENCE = re.compile(r"<PLUGIN_ROOT_AGENT>/(skills/[a-z-]+/references/[\w./-]+?\.md)")


def _references(text: str, session_tree: bool | None) -> str:
    """Absolute reference paths off a `/sessions` tree; on one, a pointer to the agent body's full path."""
    if not (_on_session_lane() if session_tree is None else session_tree):
        return text.replace("<PLUGIN_ROOT_AGENT>", _plugin_root().rstrip("/"))
    out = _REFERENCE.sub(r"the file ending \1", text.replace(_FALLBACK, _POINTER))
    if "<PLUGIN_ROOT_AGENT>" in out:
        raise ValueError("a plugin-root placeholder that names no reference file")
    return out


# --- the CHECKLIST prompt -----------------------------------------------------------------------------

# The first line of the prompt, as its own literal: the hook and the dispatch-contract test read it.
_CHECKLIST_CONTEXT = "CONTEXT: CHECKLIST"

# Moved from SKILL.md's Step 5 template. Two mechanical changes: the reference path is filled per lane, and
# the closing sentence is reordered so the prompt ends with the hook's closing line exactly once.
_CHECKLIST_TEMPLATE = (
    _CHECKLIST_CONTEXT
    + r"""
OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json
RUN_ID: <RUN_ID>

You are the deck-review agent dispatched in Context A (CHECKLIST).
If a reference path below cannot be read (refused or not found), read the same file under the plugin folder your own instructions name.
Evaluate all
35 criteria from <PLUGIN_ROOT_AGENT>/skills/deck-review/references/checklist-criteria.md
using the slide reviews at <REVIEW_DIR_AGENT>/slide_reviews.json (a required
read), the stage profile at <REVIEW_DIR_AGENT>/stage_profile.json, and the
deck inventory at <REVIEW_DIR_AGENT>/deck_inventory.json.

Assess ALL 35 criteria including the 4 AI criteria and the 5 Design & Readability
criteria — do NOT self-gate. `checklist.py` applies deterministic AI-criteria
gating from `deck_inventory.json`'s `ai_company_status` AND deterministic
Design-criteria gating from its `input_format` (forcing Design & Readability to
`not_applicable` when the deck was described in text rather than uploaded as a
file) after you return — assess every criterion regardless of format.

Evidence quality rules:
- Every fail and warn `evidence` MUST include BOTH what this deck actually does (quote or describe the specific slide content) AND the best-practice principle or benchmark it falls short of — the deck observation is not optional.
- Every pass MUST record in `evidence` what was checked.
- not_applicable items MUST include a reason.
- `notes` is the specific change the founder should make — imperative, concrete, particular to this deck, never a restatement of the criterion or a record of what you checked. Required on fail and warn; omit it entirely on pass and not_applicable.
- Before asserting a visual or design element is absent (photos, charts,
  diagrams, logos), check the `visuals` field of every relevant slide in
  `deck_inventory.json` and cite the slide number(s) you checked in the evidence.
- `deck_inventory.json`'s `observations`, when present, are the extraction's own
  notes on what the slides show that their text does not. Use them as you use
  `visuals`, but never quote one as the deck's words: say it is a note on the slide.

Evaluate every one of these 35 criteria — one item per id, no omissions, no
invented ids. Grouped by category:

Narrative Flow:
  - purpose_clear
  - headlines_carry_story
  - narrative_arc_present
  - strongest_proof_early
  - story_stands_alone
Slide Content:
  - problem_quantified
  - solution_shows_workflow
  - why_now_has_catalyst
  - market_bottom_up
  - competition_honest
  - business_model_clear
  - gtm_has_proof
  - team_has_depth
Stage Fit:
  - stage_appropriate_structure
  - stage_appropriate_traction
  - stage_appropriate_financials
  - ask_ties_to_milestones
  - round_size_realistic
Design & Readability:
  - one_idea_per_slide
  - minimal_text
  - slide_count_appropriate
  - consistent_design
  - mobile_readable
Common Mistakes:
  - no_vague_purpose
  - no_nice_to_have_problem
  - no_hype_without_proof
  - no_features_over_outcomes
  - no_dodged_competition
AI Company (score all 4; the producer script gates them after you return):
  - ai_retention_rebased
  - ai_cost_to_serve_shown
  - ai_defensibility_beyond_model
  - ai_responsible_controls
Diligence Readiness:
  - numbers_consistent
  - data_room_ready
  - contact_info_present

When you cite deck figures in evidence, quote them verbatim from the deck
content — do not paraphrase or round numbers, percentages, dates, or named
metrics.

Evidence prints VERBATIM in the founder's report, so name the source the way the
founder knows it — never by our filename or a dispatch label. They saw their deck,
not `deck_inventory.json` or `deck-best-practices.md`.
  Instead of: "slide_reviews.json shows no competition slide"
  Write:      "the deck has no competition slide"
State what is true of the DECK.


Use your Write tool to write to OUTPUT_PATH the items array without a summary
(the producer script computes the summary):
{"slide_reviews_read_token": "the metadata.read_token value you read", "items": [{"id": "purpose_clear", "status": "pass", "evidence": "...", "notes": "..."}, ...all 35 items...]}
The main thread leaves `slide_reviews_read_token` to you; copy it from the `metadata.read_token` field at the end of the `slide_reviews.json` you Read (12 hex characters).
On the four visual Design & Readability criteria add `"verified_by"`: `"measured"` only
when you directly observed the property with a tool that can observe it, `"inferred"` when
you reasoned it from other evidence, `"not_possible"` when you had no way to observe it.
Leaving it off means unstated, which is not the same as measured.
All string values must be JSON-escaped (`\n` for line breaks, `\"` for embedded
quotes); the file must parse with a strict JSON parser.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
You never write a canonical artifact; anything else you write bypasses schema
validation and run_id stamping.
Do NOT write any file other than OUTPUT_PATH.
"""  # noqa: E501
)

# The hook's closing line (founder-skills/scripts/dispatch_prompt_check.py END); it ends every prompt.
_END = "Do NOT write any file other than OUTPUT_PATH.\n"
assert _CHECKLIST_TEMPLATE.endswith(_END), "the CHECKLIST template must end with the hook's closing line"
assert _CHECKLIST_TEMPLATE.count(_END.strip()) == 1, "the closing line must appear once, last"

# A corrective redo re-sends the same prompt with one line added. The lines are a closed set, printed
# here, so a redo is also a printed prompt and nothing is typed into it. A producer's rejection goes back
# the same way (SLIDE_REVIEWS_NOT_READ included: the redo is a full grading prompt with a required read):
# read from the file its stderr was saved to, never typed, behind a fixed lead, quoted line by line so no
# line of it reads as the prompt's context or closing line, and capped. Same text in the other skills'
# generators. The added lines go before the closing line, which must stay last.
CORRECTIONS = {
    "missing-file": (
        "Your previous receipt claimed a file at OUTPUT_PATH but none exists; use Write to create exactly that path."
    ),
    "receipt-only": "Return ONLY the receipt JSON -- no fences, no prose.",
}
PRODUCER_REJECTED = "producer-rejected"
REJECTION_LEAD = "The producer rejected your previous file. Its message, quoted:"
REJECTION_TAIL = "Write a corrected file to OUTPUT_PATH."
DETAIL_CAP = 2000


def rejection_text(detail: str) -> str:
    """The lines a producer-rejected redo adds. ValueError on an empty message."""
    body = detail.strip()
    if not body:
        raise ValueError("the producer's message is empty")
    if len(body) > DETAIL_CAP:
        body = body[:DETAIL_CAP].rstrip() + " [cut at 2,000 characters]"
    body = body.replace(_END.rstrip("\n"), "[closing line removed]")
    quoted = "\n".join(f"> {line}".rstrip() for line in body.splitlines())
    return f"{REJECTION_LEAD}\n{quoted}\n{REJECTION_TAIL}"


def _correction_line(correction: str, detail: str | None) -> str:
    if correction == PRODUCER_REJECTED:
        if detail is None:
            raise ValueError("producer-rejected needs the producer's message")
        return rejection_text(detail)
    return CORRECTIONS[correction]


def checklist(
    *,
    run_id: str,
    handoff_agent: str,
    review_dir_agent: str,
    correction: str | None = None,
    detail: str | None = None,
    session_tree: bool | None = None,
) -> str:
    """The CHECKLIST prompt, placeholders filled.

    `session_tree` None detects the lane (see `_on_session_lane`); tests pass it to force one."""
    text = _references(_CHECKLIST_TEMPLATE, session_tree)
    text = (
        text.replace("<HANDOFF_AGENT>", handoff_agent.rstrip("/"))
        .replace("<REVIEW_DIR_AGENT>", review_dir_agent.rstrip("/"))
        .replace("<RUN_ID>", run_id)
    )
    # Added last: text in the message is quoted as written, never filled in.
    if correction is not None:
        text = text.replace(_END, f"{_correction_line(correction, detail)}\n{_END}")
    return text


def _detail(correction: str | None, path: str | None) -> str | None:
    """The producer's message for a producer-rejected redo, read from its file; exits 2 when it is
    missing, unreadable or empty, or when a file is given for any other correction."""
    if correction != PRODUCER_REJECTED:
        if path is not None:
            print("Error: --detail-file is read only with --correction producer-rejected", file=sys.stderr)
            sys.exit(2)
        return None
    if path is None:
        print(
            "Error: --correction producer-rejected needs --detail-file <the producer's saved stderr>", file=sys.stderr
        )
        sys.exit(2)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(DETAIL_CAP + 1)  # the message is capped anyway; never read more than that
    except OSError as e:
        print(f"Error: cannot read --detail-file {path}: {e}", file=sys.stderr)
        sys.exit(2)
    if not text.strip():
        print(f"Error: --detail-file {path} is empty; save the producer's stderr to it first", file=sys.stderr)
        sys.exit(2)
    return text


def _refuse_empty(args: argparse.Namespace, flags: tuple[str, ...]) -> None:
    """Exit 2 when a flag below was given an empty value. A shell that did not re-assign the variable a
    flag is built from passes "", and the prompt then named a path such as `/checklist_output.json`."""
    for flag in flags:
        value = getattr(args, flag.lstrip("-").replace("-", "_"))
        if value is not None and not value.strip():
            print(
                f"Error: {flag} is empty. Each shell starts fresh: set the variable it is built from in this "
                "block, then run again.",
                file=sys.stderr,
            )
            sys.exit(2)


# The precondition's refusal. Same code as checklist.py's (same cause, already in the host contract), with a
# fix of its own: this script is what prints the prompt, so its remedy is to run it again, never to dispatch.
SLIDE_REVIEWS_MISSING_FIX = (
    "Step 4's pipe has not written this run's slide reviews yet: run it, then run this generator again; do not "
    "dispatch the CHECKLIST before this generator prints its prompt."
)


def _refuse_missing(path: str, problem: str | None) -> None:
    """Exit 1 with the rejection on stdout and one stderr line, neither carrying a context line: a refusal
    must never become a comparand."""
    rejection = {
        "status": "rejected",
        "code": "SLIDE_REVIEWS_MISSING",
        "message": f"the slide reviews at {path} {problem}, so the checklist prompt is not printed",
        "fix": SLIDE_REVIEWS_MISSING_FIX,
    }
    sys.stdout.write(json.dumps(rejection) + "\n")
    print(
        "Error (SLIDE_REVIEWS_MISSING): this run's slide reviews are not written yet; nothing printed", file=sys.stderr
    )
    sys.exit(1)


# The files the grader reads, each checked for another run's id in a folder that belongs to a run.
GRADER_READS = ("slide_reviews.json", "stage_profile.json", "deck_inventory.json", "reconciliation.json")


def main() -> None:
    p = argparse.ArgumentParser(description="Print a deck-review dispatch prompt")
    p.add_argument("context", choices=["checklist"])
    p.add_argument("--run-id", required=True)
    p.add_argument("--handoff-agent", required=True, help="the hand-off dir as the sub-agent addresses it")
    p.add_argument("--review-dir-agent", required=True, help="the review dir as the sub-agent addresses it")
    p.add_argument("--review-dir", required=True, help="the review dir in THIS shell's namespace")
    p.add_argument(
        "--correction", choices=sorted([*CORRECTIONS, PRODUCER_REJECTED]), help="a corrective redo's added line"
    )
    p.add_argument("--detail-file", help="producer-rejected: the file the producer's stderr was saved to")
    a = p.parse_args()
    _refuse_empty(a, ("--run-id", "--handoff-agent", "--review-dir-agent", "--review-dir"))
    detail = _detail(a.correction, a.detail_file)
    # In a folder that belongs to a run: only that folder's current run, and the grader is never briefed on
    # another run's files.
    import _run_ref

    _run_ref.refuse_not_this_runs(
        a.review_dir, a.run_id, [os.path.join(a.review_dir, name) for name in GRADER_READS], noun="review dir"
    )
    slide_reviews = os.path.join(a.review_dir, "slide_reviews.json")
    ok, problem = _slide_reviews_file.usable(slide_reviews, a.run_id)
    if not ok:
        _refuse_missing(slide_reviews, problem)
    sys.stdout.write(
        checklist(
            run_id=a.run_id,
            handoff_agent=a.handoff_agent,
            review_dir_agent=a.review_dir_agent,
            correction=a.correction,
            detail=detail,
        )
    )


if __name__ == "__main__":
    main()
