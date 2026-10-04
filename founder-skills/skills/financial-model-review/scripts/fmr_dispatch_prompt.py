#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the financial-model-review CHECKLIST dispatch prompt from identifiers.

The main thread runs this and sends the printed text as the sub-agent's prompt, unchanged. It used to
copy the template out of SKILL.md and fill it in by hand, and a hand-filled prompt is where text
nobody chose gets added and rules get dropped: kept runs sent the grader a prompt missing most of the
template's sentences. Printing from identifiers alone -- paths and the run id -- leaves nothing to
write in. The shared PreToolUse hook (founder-skills/scripts/dispatch_prompt_check.py) holds a dispatch
that differs from the printed prompt for its OUTPUT_PATH; SKILL.md does not depend on it.

The template's one condition is decided here, not by the reader: whether this run's model came with a
spreadsheet extraction (inputs.json's model_format is not deck or conversational, and model_data.json
exists) decides what the structural-error criterion rests on, so only the sentence that applies is
printed.

Every prompt ends with the hook's closing line, "Do NOT write any file other than OUTPUT_PATH.",
which is how the hook finds where a printed prompt ends.

THE PLUGIN FOLDER NEVER COMES FROM THE SHELL. Recent Claude Desktop versions rewrite the plugin's folder
inside a shell command to its path inside the VM before the command runs, and a sub-agent's file tools
are refused a VM path. So the reference path comes from where this script runs: off a `/sessions` tree
(the CLI, cloud sessions) the absolute path is printed; on one (a local Desktop session) the prompt
names the reference by how its path ends and sends the sub-agent to the full path its own agent
instructions give. Same rule as market-sizing's dispatch_prompt.py and competitive-positioning's
cp_dispatch_prompt.py. This script is new, so it has no older command line to stay compatible with and
takes no plugin-folder flag at all.

Usage:
    python fmr_dispatch_prompt.py checklist --run-id R --handoff-agent H --review-dir-agent A --review-dir D
                                  [--correction missing-file|receipt-only|producer-rejected [--detail-file F]]

`--review-dir` is the review folder in THIS shell's namespace (read to decide the condition);
`--review-dir-agent` / `--handoff-agent` are what the prompt says. Exit 2 when an argument is missing or
invalid, or when the review folder holds no inputs.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

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

# model_data.json's `structural_errors` tally is the only evidence for the structural-error criterion.
# With no extraction (a conversational or deck-described model) that evidence cannot exist, and a grader
# told "read it when it exists" was left to work out which case it was in.
_MODEL_DATA_PRESENT = (
    "Also read model_data.json at <REVIEW_DIR_AGENT>/model_data.json: its\n"
    "`structural_errors` tally is the only evidence for the structural-error criterion, whose\n"
    "pass/warn/fail bars are defined entirely on broken cells. An empty tally means none were\n"
    "found.\n"
)
_MODEL_DATA_ABSENT = (
    "This review has no model_data.json (a conversational or deck-described model). Its\n"
    "`structural_errors` tally is the only evidence for the structural-error criterion, whose\n"
    "pass/warn/fail bars are defined entirely on broken cells, so that evidence cannot exist:\n"
    "mark that criterion not_applicable rather than guessing a pass.\n"
)

_CHECKLIST_TEMPLATE = (
    _CHECKLIST_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "\n"
    "You are the financial-model-review agent dispatched in Context A (CHECKLIST).\n"
    "Read inputs.json at <REVIEW_DIR_AGENT>/inputs.json.\n"
    "<MODEL_DATA_LINES>"
    + _FALLBACK
    + "Also read <PLUGIN_ROOT_AGENT>/skills/financial-model-review/references/checklist-criteria.md.\n"
    "Also read unit_economics.json and runway.json at <REVIEW_DIR_AGENT> when they exist:\n"
    "this review's computed figures. When an item turns on a burn multiple, runway, CAC\n"
    "payback, LTV/CAC or gross margin, use these figures; do not compute your own. For\n"
    "runway use the planning number: today's-burn runway (static_runway_months) when it is\n"
    "shorter than the base scenario or the base never runs out, else the base scenario's\n"
    "months. A metric rated contextual WITH a benchmark_reference_rating is graded on that\n"
    "reference rating. One rated contextual WITHOUT it was deliberately left ungraded: give\n"
    "that criterion `warn` and say why in plain words -- never pass or fail it on the\n"
    "benchmark bar, and never not_applicable. not_rated means the inputs do not allow the\n"
    'figure, which supports a "not computable" fail. These figures are our computation, not\n'
    "the founder's model: they show a figure is computable from the model's inputs, never that\n"
    "the model itself shows, highlights, summarises or explains it. State figures in your own\n"
    "words; never copy our evidence text, our rating words, or a filename.\n"
    "\n"
    "Assess all 46 checklist items (STRUCT_01..09, UNIT_10..19, CASH_20..32,\n"
    "METRIC_33..35, BRIDGE_36..38, SECTOR_39..44, OVERALL_45..46).\n"
    "Profile-based auto-gating is applied BY THE PRODUCER SCRIPT after you return —\n"
    "assess EVERY item on its merits and never mark an item not_applicable because\n"
    'of a stage/geography/sector/model_format gate ("partial" models are evaluated\n'
    "in full; only the script decides gating).\n"
    "\n"
    "Evidence is MANDATORY for every item, but scale it to the status: every `fail`\n"
    "and `warn` MUST carry full evidence with the specific values from the model\n"
    "(these drive the score and the coaching payload). Every `pass` needs only a\n"
    'brief note of what was checked — keep it to ~12 words (e.g. "checked runway vs\n'
    'burn; consistent"); do not pad passing items with long evidence, it is never a\n'
    "coaching input.\n"
    "\n"
    "Evidence prints VERBATIM in the founder's report: state what is true of the MODEL,\n"
    'never citing our filenames. "the model does not separate actuals from projections",\n'
    'not "inputs.json reports actuals separated: false". The delivery gate flags an\n'
    "internal filename in evidence, so this is checked.\n"
    "\n"
    "Use your Write tool to write to OUTPUT_PATH — company + metadata + items\n"
    "(producer script computes summary):\n"
    "{\n"
    '  "company": {<the company object copied verbatim from inputs.json — enables profile auto-gating>},\n'
    '  "metadata": {"run_id": "<RUN_ID>"},\n'
    '  "items": [{"id": "STRUCT_01", "status": "pass", "evidence": "...", "notes": null}, ...all 46 items...]\n'
    "}\n"
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema\n"
    "validation and run_id stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)

# The hook's closing line (founder-skills/scripts/dispatch_prompt_check.py END); it ends every prompt.
_END = "Do NOT write any file other than OUTPUT_PATH.\n"
assert _CHECKLIST_TEMPLATE.endswith(_END), "the CHECKLIST template must end with the hook's closing line"
assert _CHECKLIST_TEMPLATE.count(_END.strip()) == 1, "the closing line must appear once, last"

# A corrective redo re-sends the same prompt with one line added. The lines are a closed set, printed
# here, so a redo is also a printed prompt and nothing is typed into it. A producer's rejection goes back
# the same way: read from the file its stderr was saved to, never typed, behind a fixed lead, quoted line
# by line so no line of it reads as the prompt's context or closing line, and capped. Same text in
# market-sizing's dispatch_prompt.py and competitive-positioning's cp_dispatch_prompt.py. The added lines
# go before the closing line, which must stay last.
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


# The formats with no spreadsheet extraction (schema-inputs.md `model_format`); a missing value is a
# spreadsheet, as checklist.py and compose_report.py read it.
NO_EXTRACTION_FORMATS = ("deck", "conversational")


def has_extraction(inputs: object, review_dir: str) -> bool:
    """Whether this run's model came with a spreadsheet extraction. The review folder is per company and
    reused, and model_data.json carries no run id, so a file left by an earlier spreadsheet review of the
    same company is still there when it is reviewed again from a deck. inputs.json is this run's: its
    model_format decides first, and the file must also exist."""
    company = inputs.get("company") if isinstance(inputs, dict) else None
    model_format = company.get("model_format") if isinstance(company, dict) else None
    if model_format in NO_EXTRACTION_FORMATS:
        return False
    return os.path.isfile(os.path.join(review_dir, "model_data.json"))


def checklist(
    *,
    run_id: str,
    handoff_agent: str,
    review_dir_agent: str,
    has_model_data: bool,
    correction: str | None = None,
    detail: str | None = None,
    session_tree: bool | None = None,
) -> str:
    """The CHECKLIST prompt, placeholders filled and the model_data.json arm chosen.

    `session_tree` None detects the lane (see `_on_session_lane`); tests pass it to force one."""
    text = _references(_CHECKLIST_TEMPLATE, session_tree)
    arm = _MODEL_DATA_PRESENT if has_model_data else _MODEL_DATA_ABSENT
    text = (
        text.replace("<MODEL_DATA_LINES>", arm)
        .replace("<HANDOFF_AGENT>", handoff_agent.rstrip("/"))
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


def main() -> None:
    p = argparse.ArgumentParser(description="Print a financial-model-review dispatch prompt")
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
    inputs_path = os.path.join(a.review_dir, "inputs.json")
    if not os.path.isfile(inputs_path):
        print(f"Error: no inputs.json in --review-dir {a.review_dir}; the checklist grades it", file=sys.stderr)
        sys.exit(2)
    try:
        with open(inputs_path, encoding="utf-8") as fh:
            inputs = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"Error: cannot read inputs.json in --review-dir {a.review_dir}: {e}", file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(
        checklist(
            run_id=a.run_id,
            handoff_agent=a.handoff_agent,
            review_dir_agent=a.review_dir_agent,
            has_model_data=has_extraction(inputs, a.review_dir),
            correction=a.correction,
            detail=detail,
        )
    )


if __name__ == "__main__":
    main()
