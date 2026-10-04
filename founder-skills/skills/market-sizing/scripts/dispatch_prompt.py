#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate a sub-agent dispatch prompt from identifiers on disk.

WHY A SCRIPT. On a live run the main thread hand-filled the RED_TEAM template and added, from its own
head, a numbered list of "things worth attacking" and an instruction not to re-read the founder's
documents. The red team's four findings mapped one-to-one onto that list, and it never opened the deck.
The step that exists to escape the constructor's framing was framed by the constructor, in prose no
test can see. Here the model supplies paths and ids; every sentence comes from this file; the e2e lane
regenerates the prompt and asserts the dispatched one is byte-identical.

WHY DOCUMENTS FIRST. The same four hypotheses were also in the artifacts (`gtm_evidence_notes`,
`competitive_landscape_notes`, `existing_claims_detail`), which the old template listed first. A reader
who opens the analysis's reading of the deck before the deck inherits its frame. So the founder's
documents come first, with an instruction to record what they say before opening any artifact.

TWO PATH NAMESPACES. In Cowork the main thread's shell runs in the VM (`/sessions/<id>/mnt/...`) and
a sub-agent's file tools run host-native, where a `/sessions/...` read is DENIED (cowork-harness 3.7.0
models it: dist/hostloop/canusetool-gate.js:123 refuses any isVmSessionsPath) and a RELATIVE path is
refused too. The agent-namespace values the caller passes are therefore the absolute file-tool paths
`resolve_artifacts_root.py` prints after the Step 0 proof; this script renders them as given. So it
CHECKS paths in the caller's namespace and RENDERS them in the agent's: `--analysis-dir` /
`--handoff-dir` are read from disk, `--analysis-dir-agent` / `--handoff-agent` are what the prompt
says. The founder's documents live outside outputs and have no agent-namespace form, so Step 6c mirrors
them into `<handoff-dir>/docs/` first; OCR sidecars sit in `<handoff-dir>/ocr/`. Omit
`--analysis-dir-agent` on a single-namespace host (the CLI) and the real path is rendered.

THE PLUGIN FOLDER NEVER COMES FROM THE SHELL. Recent Claude Desktop versions rewrite the plugin's folder
(and a skill's folder) inside a shell command to its path inside the VM before the command runs; other
paths are not rewritten. A plugin folder handed to this script as an argument therefore arrives as a VM
path, which a sub-agent's file tools are refused. So the CHECKLIST prompt's reference paths come from
where this script runs. Off a `/sessions` tree (the CLI, cloud sessions) that folder is the one a
sub-agent reads, and the absolute paths are printed. On a `/sessions` tree (a local Desktop session) it
is a VM path, so the prompt names each reference by how its path ends and sends the sub-agent to the
full path its own agent instructions give, which the loader fills in for that sub-agent. That is right on
a VM-loop session too, where the filled path is the VM one and the file tools run in the VM.
`--plugin-root-agent` is still accepted and ignored, so an older command line prints the same prompt.

OCR MUST HAVE FINISHED. This script lists whatever sidecars exist when it runs, and on a live run
that was a half-finished OCR: the shell tool timed out at 120 s, tesseract kept going orphaned, the
prompt was generated twice before the last two documents' pages existed, and the red team was told
those documents had "no machine-read copy". `ocr_uploads.py` now writes `<ocr-dir>/receipt.json`
per document; an image-only PDF the receipt does not cover is a refusal here (exit 2, naming it),
never a prompt that silently offers less.

Only `red_team` today; the generic shape is for the other dispatches once this one has proven itself
live. Output is deterministic for fixed inputs: sorted listings, no timestamps.

Usage:
    dispatch_prompt.py red_team --run-id R --analysis-dir A --handoff-dir D --handoff-agent H
                      [--analysis-dir-agent A_AGENT]
    dispatch_prompt.py checklist --run-id R --analysis-dir A --handoff-dir D --handoff-agent H
                      [--analysis-dir-agent A_AGENT]

Prints the prompt. Exit 2 on a missing artifact or an image-only PDF the OCR receipt does not cover.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

REQUIRED_ARTIFACTS = ("inputs.json", "sizing.json", "validation.json")
DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")


def list_documents(uploads_dir: str | None) -> list[str]:
    """Regular files with a document suffix, sorted; dotfiles and AppleDouble `._*` excluded.

    Copied verbatim into the shared scripts/_redteam_core.py, which red_team.py uses; keep the two in step.
    """
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return []
    out: list[str] = []
    for name in sorted(os.listdir(uploads_dir)):
        if name.startswith(".") or not name.lower().endswith(DOCUMENT_SUFFIXES):
            continue
        if os.path.isfile(os.path.join(uploads_dir, name)):
            out.append(name)
    return out


def _probe(path: str) -> dict[str, Any]:
    """Run the sibling pdf_probe.py; a failed probe is reported as such, never guessed."""
    probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_probe.py")
    try:
        r = subprocess.run([sys.executable, probe, path], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return {"ok": False}
        parsed = json.loads(r.stdout)
        return parsed if isinstance(parsed, dict) else {"ok": False}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ok": False}


class OcrIncomplete(Exception):
    """Image-only PDFs the OCR receipt does not cover (never ran, or was killed before reaching them)."""


def _ocr_receipt(ocr_dir: str) -> dict[str, Any] | None:
    try:
        with open(os.path.join(ocr_dir, "receipt.json"), encoding="utf-8") as fh:
            r = json.load(fh)
        return r if isinstance(r, dict) else None
    except (OSError, ValueError):
        return None


def _ocr_covers(receipt: dict[str, Any] | None, name: str) -> bool:
    """Did ocr_uploads.py get as far as this document? Unavailable binaries count as covered: the
    receipt then says so and the prompt's NO TEXT LAYER note is the honest offer."""
    if receipt is None:
        return False
    if not receipt.get("ocr_available", False):
        return True
    docs = receipt.get("documents")
    skipped = receipt.get("skipped")
    return (isinstance(docs, dict) and name in docs) or (isinstance(skipped, list) and name in skipped)


def _sidecars(ocr_dir: str | None, name: str) -> list[str]:
    """OCR text sidecars for one document: `<ocr_dir>/<name>.p<N>.txt`, sorted by page number."""
    if not ocr_dir or not os.path.isdir(ocr_dir):
        return []
    prefix = name + ".p"
    found = [f for f in os.listdir(ocr_dir) if f.startswith(prefix) and f.endswith(".txt")]

    def page_no(f: str) -> int:
        try:
            return int(f[len(prefix) : -len(".txt")])
        except ValueError:
            return 0

    return [os.path.join(ocr_dir, f) for f in sorted(found, key=page_no)]


class ReviewDocsElsewhere(Exception):
    """A revision round's hand-off dir has no docs/, but the first round's does."""


# A corrective redo (check_handoff.py exit 3 or 6) is a printed prompt too: the dispatch hook holds any
# prompt that is not the generator's output, so a line typed onto the prompt is held and its correction
# lost. The line goes before the closing line, which the hook requires to stay last.
CORRECTIONS = {
    "missing-file": (
        "Your previous receipt claimed a file at OUTPUT_PATH but none exists; use Write to create exactly that path."
    ),
    "receipt-only": "Return ONLY the receipt JSON -- no fences, no prose.",
}
_END = "Do NOT write any file other than OUTPUT_PATH.\n"
# A producer's rejection (the pipe after the hand-off exits non-zero) goes back the same way: read from
# the file its stderr was saved to, never typed, behind a fixed lead, quoted line by line so no line of
# it reads as the prompt's context or closing line, and capped. Same text in cp_dispatch_prompt.py.
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


def _corrected(text: str, correction: str | None, detail: str | None = None) -> str:
    if correction is None:
        return text
    if not text.endswith(_END):
        raise ValueError("a prompt must end with the closing line")
    if correction == PRODUCER_REJECTED:
        if detail is None:
            raise ValueError("producer-rejected needs the producer's message")
        line = rejection_text(detail)
    else:
        line = CORRECTIONS[correction]
    return text[: -len(_END)] + line + "\n" + _END


def red_team(
    run_id: str,
    analysis_dir: str,
    handoff_dir: str,
    handoff_agent: str,
    analysis_dir_agent: str | None = None,
    review_docs_dir: str | None = None,
    review_docs_agent: str | None = None,
    correction: str | None = None,
    detail: str | None = None,
) -> str:
    return _corrected(
        _red_team(
            run_id,
            analysis_dir,
            handoff_dir,
            handoff_agent,
            analysis_dir_agent,
            review_docs_agent=review_docs_agent,
            review_docs_dir=review_docs_dir,
        ),
        correction,
        detail,
    )


def _red_team(
    run_id: str,
    analysis_dir: str,
    handoff_dir: str,
    handoff_agent: str,
    analysis_dir_agent: str | None = None,
    review_docs_dir: str | None = None,
    review_docs_agent: str | None = None,
) -> str:
    missing = [f for f in REQUIRED_ARTIFACTS if not os.path.isfile(os.path.join(analysis_dir, f))]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    analysis_agent = (analysis_dir_agent or analysis_dir).rstrip("/")
    handoff_agent = handoff_agent.rstrip("/")
    # The founder's documents and their OCR live under the FIRST round's hand-off dir; a revision
    # round (handoff/<run>/r2) reads them from there. Without the flag, round 2's own docs/ does not
    # exist and the prompt would silently say the founder supplied nothing -- refused instead.
    docs_root = review_docs_dir or handoff_dir
    docs_agent = (review_docs_agent or handoff_agent).rstrip("/")
    docs_dir = os.path.join(docs_root, "docs")
    ocr_dir = os.path.join(docs_root, "ocr")
    if not os.path.isdir(docs_dir) and os.path.isdir(os.path.join(os.path.dirname(handoff_dir.rstrip("/")), "docs")):
        raise ReviewDocsElsewhere(os.path.join(os.path.dirname(handoff_dir.rstrip("/")), "docs"))
    lines = [
        "CONTEXT: RED_TEAM",
        f"OUTPUT_PATH: {handoff_agent}/redteam_output.json",
        f"RUN_ID: {run_id}",
        "",
    ]
    docs = list_documents(docs_dir)
    if docs:
        lines += [
            "The founder's documents. Open every one of them, and for each figure the analysis relies",
            "on write down what the page actually says, before you open any of the analysis's artifacts:",
        ]
        receipt = _ocr_receipt(ocr_dir)
        uncovered: list[str] = []
        for name in docs:
            full = os.path.join(docs_dir, name)
            note = ""
            if name.lower().endswith(".pdf"):
                p = _probe(full)
                if not p.get("ok"):
                    note = "  (could not probe for a text layer)"
                elif p.get("image_only"):
                    note = (
                        f"  (NO TEXT LAYER, {p.get('total_pages')} pages: a vision read drops dense content silently)"
                    )
                    if not _ocr_covers(receipt, name):
                        uncovered.append(name)
            lines.append(f"  {docs_agent}/docs/{name}{note}")
            for sc in _sidecars(ocr_dir, name):
                lines.append(f"      text of one page, machine-read: {docs_agent}/ocr/{os.path.basename(sc)}")
        if uncovered:
            raise OcrIncomplete(", ".join(uncovered))
        lines += [
            "",
            "Record every file you opened in sources_read. A page you could not read reliably goes in",
            "could_not_check by file and page, never reported as 'nothing found'. A figure the analysis",
            "took from a page that the page does not say is a finding whose source is that page:",
            'source_url "document:<filename>#page=<n>".',
            "",
        ]
    else:
        lines += [
            "The founder supplied no documents. Say so in could_not_check and work from the artifacts",
            "and the web.",
            "",
        ]
    lines += ["Then read the analysis's artifacts and attack the analysis they describe:"]
    lines += [f"  {analysis_agent}/{f}" for f in REQUIRED_ARTIFACTS]
    lines += [
        "",
        "You are not told what to attack. The analysis is not a reliable guide to its own weaknesses,",
        "and its notes fields are its reading of the documents, not the documents.",
        "",
        "Write your findings to OUTPUT_PATH in the shape your agent body specifies, then return ONLY",
        "the receipt JSON in your final assistant message:",
        '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>", "findings": <count>}',
        "Do NOT write any file other than OUTPUT_PATH.",
    ]
    return "\n".join(lines) + "\n"


# --- CHECKLIST ----------------------------------------------------------------------------------------
#
# In round 2 of a live run the main thread told the grader "round 2 after a revision … down from a
# mechanically-forced N% in round 1", and the grader wrote it to the founder ("the two builds now
# diverge … after being set independently"). Round 1's prompt was not the template either: paragraphs
# dropped, a verdict inserted ("score approaches_reconciled accordingly"). So the prompt is printed from
# identifiers alone -- no round, no free text -- and the grader reads a copy of methodology.json holding
# only what an item grades; its revision record, notes and skipped questions are history.

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


_CHECKLIST_METHODOLOGY_KEYS = ("approach_chosen", "rationale", "metadata")
_CHECKLIST_CONTEXT = "CONTEXT: CHECKLIST"
_CHECKLIST_TEMPLATE = (
    _CHECKLIST_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "\n"
    "You are the market-sizing agent dispatched in Context A (CHECKLIST).\n" + _FALLBACK + "Read:\n"
    "- <PLUGIN_ROOT_AGENT>/skills/market-sizing/references/pitfalls-checklist.md\n"
    "- <PLUGIN_ROOT_AGENT>/skills/market-sizing/references/artifact-schemas.md\n"
    '  (read the "Canonical 22 checklist IDs" section)\n'
    "- <ANALYSIS_DIR_AGENT>/inputs.json\n"
    "- <HANDOFF_AGENT>/checklist_view/methodology.json\n"
    "- <ANALYSIS_DIR_AGENT>/validation.json\n"
    "- <ANALYSIS_DIR_AGENT>/sizing.json\n"
    "\n"
    "**Materials-dependent items on a run with no materials.** If `inputs.materials_provided` is empty —\n"
    "a conversational run, no deck, no model — then an item that can only be evidenced BY a deck or\n"
    "financial model (competitive content, GTM evidence, hiring/burn alignment) scores `not_applicable`,\n"
    "not `fail`. There was nothing to acknowledge competition, GTM, or projections alignment *in*. Scoring\n"
    "it `fail` penalises the founder for a document they were never asked for and moves the headline\n"
    "percentage, which is the number they quote. `not_applicable` is excluded from the denominator, so the\n"
    "score reflects what was actually assessable. Say in the item's notes that it was skipped for want of\n"
    "materials.\n"
    "\n"
    "You do NOT see the original deck — score `competitive_landscape_acknowledged` from\n"
    "`inputs.json`'s `competitive_landscape_notes` field only (present or `null`), not from\n"
    'inference about what the deck "probably" said. Score `som_backed_by_gtm` from\n'
    "`inputs.json`'s `gtm_evidence_notes` field only, and `som_consistent_with_projections` from\n"
    "`inputs.json`'s `projections_alignment_notes` field only — same rule, two different fields, because\n"
    "GTM/customer-acquisition evidence and hiring-plan/burn-rate evidence are different things and one\n"
    "field cannot stand in for both.\n"
    "\n"
    "Assess all 22 items with status (pass/fail/not_applicable) and notes.\n"
    "\n"
    "`notes` prints VERBATIM in the founder's report, so name the source the way the\n"
    "founder knows it — never by our filename. They never saw `inputs.json` or\n"
    "`sizing.json`; they saw their deck and the figures they gave you.\n"
    '  Instead of: "sizing.json records formula strings for every figure"\n'
    '  Write:      "every figure shows the formula behind it"\n'
    '  Instead of: "inputs.json gtm_evidence_notes is null"\n'
    '  Write:      "the deck states no go-to-market plan"\n'
    "State what is true of the MARKET or the founder's own materials.\n"
    "\n"
    "Use your Write tool to write to OUTPUT_PATH the items array without a summary\n"
    "(the producer script computes the summary). Each item has this shape:\n"
    "{\n"
    '  "items": [\n'
    '    {"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null}\n'
    "  ]\n"
    "}\n"
    "status is one of: pass, fail, not_applicable.\n"
    "\n"
    "Assess every one of these 22 items — one item per id, no omissions, no invented\n"
    "ids. The 22 ids, grouped by category:\n"
    "Structural Checks:\n"
    '    {"id": "structural_tam_gt_sam_gt_som"}\n'
    '    {"id": "structural_definitions_correct"}\n'
    "TAM Scoping:\n"
    '    {"id": "tam_matches_product_scope"}\n'
    '    {"id": "source_segments_match"}\n'
    "SOM Realism:\n"
    '    {"id": "som_share_defensible"}\n'
    '    {"id": "som_backed_by_gtm"}\n'
    '    {"id": "som_consistent_with_projections"}\n'
    "Data Quality:\n"
    '    {"id": "data_current"}\n'
    '    {"id": "sources_reputable"}\n'
    '    {"id": "figures_triangulated"}\n'
    '    {"id": "unsupported_figures_flagged"}\n'
    '    {"id": "validated_used_precisely"}\n'
    '    {"id": "assumptions_categorized"}\n'
    "Methodology:\n"
    '    {"id": "both_approaches_used"}\n'
    '    {"id": "approaches_reconciled"}\n'
    '    {"id": "growth_dynamics_considered"}\n'
    "Market Understanding:\n"
    '    {"id": "market_properly_segmented"}\n'
    '    {"id": "competitive_landscape_acknowledged"}\n'
    '    {"id": "sam_expansion_path_noted"}\n'
    "Presentation:\n"
    '    {"id": "assumptions_explicit"}\n'
    '    {"id": "formulas_shown"}\n'
    '    {"id": "sources_cited"}\n'
    "\n"
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema validation and run_id\n"
    "stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def checklist(
    run_id: str,
    analysis_dir: str,
    handoff_dir: str,
    handoff_agent: str,
    analysis_dir_agent: str,
    *,
    session_tree: bool | None = None,
    correction: str | None = None,
    detail: str | None = None,
) -> str:
    """The CHECKLIST prompt, after writing `<handoff_dir>/checklist_view/methodology.json`.

    `session_tree` None detects the lane (see `_on_session_lane`); tests pass it to force one."""
    needed = ("inputs.json", "methodology.json", "validation.json", "sizing.json")
    missing = [f for f in needed if not os.path.isfile(os.path.join(analysis_dir, f))]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    with open(os.path.join(analysis_dir, "methodology.json"), encoding="utf-8") as fh:
        methodology = json.load(fh)
    view = {
        k: methodology[k] for k in _CHECKLIST_METHODOLOGY_KEYS if isinstance(methodology, dict) and k in methodology
    }
    os.makedirs(os.path.join(handoff_dir, "checklist_view"), exist_ok=True)
    with open(os.path.join(handoff_dir, "checklist_view", "methodology.json"), "w", encoding="utf-8") as fh:
        json.dump(view, fh, indent=2)
    return _corrected(
        _references(_CHECKLIST_TEMPLATE, session_tree)
        .replace("<HANDOFF_AGENT>", handoff_agent.rstrip("/"))
        .replace("<ANALYSIS_DIR_AGENT>", analysis_dir_agent.rstrip("/"))
        .replace("<RUN_ID>", run_id),
        correction,
        detail,
    )


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


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a sub-agent dispatch prompt from identifiers on disk")
    p.add_argument("context", choices=["red_team", "checklist"])
    p.add_argument("--run-id", required=True)
    p.add_argument("--analysis-dir", required=True, help="the artifacts dir in THIS shell's namespace")
    p.add_argument(
        "--handoff-dir", required=True, help="the hand-off dir in THIS shell's namespace (docs/, ocr/ under it)"
    )
    p.add_argument("--handoff-agent", required=True, help="the same hand-off dir as the sub-agent addresses it")
    p.add_argument(
        "--analysis-dir-agent", help="the artifacts dir as the sub-agent addresses it (default: --analysis-dir)"
    )
    p.add_argument("--review-docs-dir", help="revision round: the FIRST round's hand-off dir (docs/, ocr/ under it)")
    p.add_argument("--review-docs-agent", help="revision round: the same dir as the sub-agent addresses it")
    # Accepted and ignored for one release, so an older command line still prints the same prompt; the
    # folder a prompt names comes from where this script runs (module docstring).
    p.add_argument("--plugin-root-agent", help=argparse.SUPPRESS)
    p.add_argument(
        "--correction", choices=sorted([*CORRECTIONS, PRODUCER_REJECTED]), help="a corrective redo's added line"
    )
    p.add_argument("--detail-file", help="producer-rejected: the file the producer's stderr was saved to")
    a = p.parse_args()
    detail = _detail(a.correction, a.detail_file)
    if a.context == "checklist":
        try:
            sys.stdout.write(
                checklist(
                    a.run_id,
                    a.analysis_dir,
                    a.handoff_dir,
                    a.handoff_agent,
                    a.analysis_dir_agent or a.analysis_dir,
                    correction=a.correction,
                    detail=detail,
                )
            )
        except FileNotFoundError as e:
            print(f"Error: required artifact missing under {a.analysis_dir}: {e}", file=sys.stderr)
            sys.exit(2)
        return
    try:
        sys.stdout.write(
            red_team(
                a.run_id,
                a.analysis_dir,
                a.handoff_dir,
                a.handoff_agent,
                a.analysis_dir_agent,
                a.review_docs_dir,
                a.review_docs_agent,
                correction=a.correction,
                detail=detail,
            )
        )
    except FileNotFoundError as e:
        print(f"Error: required artifact missing under {a.analysis_dir}: {e}", file=sys.stderr)
        sys.exit(2)
    except ReviewDocsElsewhere as e:
        print(
            f"Error: the founder's documents are at {e}, not under this round's hand-off dir. A revision "
            "round passes --review-docs-dir / --review-docs-agent for the FIRST round's hand-off dir.",
            file=sys.stderr,
        )
        sys.exit(2)
    except OcrIncomplete as e:
        print(
            f"Error: OCR has not finished for {e} (no entry in {a.handoff_dir}/ocr/receipt.json). "
            "Re-run ocr_uploads.py -- it resumes where it stopped -- then generate the prompt.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
