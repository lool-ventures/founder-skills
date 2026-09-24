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
a sub-agent's file tools run host-native with cwd at the outputs mount, where a `/sessions/...` read
is DENIED (cowork-harness 3.7.0 models it: dist/hostloop/canusetool-gate.js:123 refuses any
isVmSessionsPath). So this script CHECKS paths in the caller's namespace and RENDERS them in the
agent's: `--analysis-dir` / `--handoff-dir` are read from disk, `--analysis-dir-agent` /
`--handoff-agent` are what the prompt says. The founder's documents live outside outputs and have no
agent-namespace form, so Step 6c mirrors them into `<handoff-dir>/docs/` first; OCR sidecars sit in
`<handoff-dir>/ocr/`. Omit `--analysis-dir-agent` on a single-namespace host (the CLI) and the real
path is rendered.

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

Prints the prompt. Exit 2 on a missing artifact or an image-only PDF the OCR receipt does not cover.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

REQUIRED_ARTIFACTS = ("inputs.json", "sizing.json", "validation.json")
DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")


def list_documents(uploads_dir: str | None) -> list[str]:
    """Regular files with a document suffix, sorted; dotfiles and AppleDouble `._*` excluded.

    Copied verbatim into red_team.py (skill scripts cannot import each other); keep the two in step.
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


def red_team(
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


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a sub-agent dispatch prompt from identifiers on disk")
    p.add_argument("context", choices=["red_team"])
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
    a = p.parse_args()
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
