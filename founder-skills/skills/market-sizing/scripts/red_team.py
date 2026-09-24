#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Validator for the RED_TEAM sub-agent's adversarial findings.

The sub-agent attacks a finished sizing analysis and writes a findings file.
This validates that file and produces `redteam.json`. It is a VALIDATOR, not a
detector: it never decides whether a finding is correct, only whether it is
evidenced well enough to put in front of a founder.

Always reads JSON from stdin.

Usage:
    cat findings.json | python red_team.py --run-id 20260101T000000Z -o redteam.json

Output: JSON with accepted findings, rejected findings (each with its reason),
and a summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any, NoReturn

from _quote_match import quote_in_doc
from _redteam_copy import write_copy
from _redteam_text import humanize_review_text

# The review's prose goes to the founder verbatim, so it is worded here, once, before anyone else
# can see it -- see _redteam_text for the two runs that made this necessary. The fleet's shared
# founder-text policy runs last over the same fields. It lives in the plugin's shared scripts, which
# the skill's Step 0 preflight already requires; a missing copy is a broken install and fails loudly
# (main), never a silently unworded review.
_SHARED_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
)
_PROSE_FIELDS = ("claim_attacked", "what_is_true", "source_title")


def _founder_text_policy() -> Any:
    if _SHARED_SCRIPTS not in sys.path:
        sys.path.insert(0, _SHARED_SCRIPTS)
    import _founder_text  # type: ignore[import-not-found]

    return _founder_text


_SEVERITIES = ("high", "medium", "low")

# The ONE non-web provenance a finding may claim: the sentence is from this run's own output.
#
# It exists because a real run produced exactly that shape -- the red team quoted the analysis'
# own comparison note back at it -- and, with only http(s) accepted, hung an unrelated external
# URL on it to get through. A link that does not contain the quote quietly breaks this step's
# whole promise, which is that every finding carries the sentence it relies on.
#
# A CLOSED single value, for the same reason the skip reason is closed: an open one lets a
# finding claim a provenance nobody can check. Exact match, case-sensitive -- "internal",
# "internal:whatever" and "INTERNAL:ANALYSIS" are all refused.
INTERNAL_PROVENANCE = "internal:analysis"

# Every field a finding must carry to reach a founder. `source_url` is the load-bearing one and
# the requirement is POSITIVE on purpose.
#
# An earlier design tried to catch the failure from the other side, with a regex refusing any
# finding that "proposes a number". Measured against real findings it failed BOTH ways: it
# accepted "closer to $66 than $203" and "5.1 billed months rather than 12", and it REFUSED
# "the recurring rate is actually $203 on n=17" -- a correct finding quoting its source to
# correct a misread, which is the single most valuable shape this step produces. A negative
# rule over prose cannot separate those, because the difference is not in the grammar.
#
# What does separate them is whether the claim is anchored: a finding that names where its
# sentence came from can be checked by the founder, and one that cannot is an opinion no matter
# how it is phrased.
_REQUIRED_FIELDS = ("claim_attacked", "what_is_true", "evidence_quote", "source_url", "source_title")

# The THIRD provenance: the founder's own page. `document:<filename>#page=<n>`, where the file
# is one the founder supplied. It exists because, with only a web address and `internal:analysis`
# accepted, a finding whose evidence is the deck itself -- "slide 8 says n=17, the analysis says
# n=47" -- had no legal source and was dropped as unsourced. The step that should catch a misread
# of a page was forbidden from citing the page. Measured on a live run: the misread was repeated.
#
# A document citation is CHECKED where it can be: against the page's text layer, else against the
# OCR sidecar ocr_uploads.py wrote, else it is `quote_verified: null` -- shown, and marked as not
# machine-checked. It is never rejected for being unverifiable; it IS rejected for naming a file
# the founder did not supply, or for quoting a token rather than a sentence (a three-character
# "quote" always matches something).
DOCUMENT_PREFIX = "document:"
# `#page=<n>` is REQUIRED for a paginated file and OPTIONAL otherwise: a live red team cited a
# markdown file -- which has no pages -- and the first rule, which demanded a page on every
# citation, set a real finding aside.
_DOC_RE = re.compile(r"^document:([^#/\\]+)(?:#page=([1-9]\d*))?$")
_PAGINATED_SUFFIXES = (".pdf", ".pptx", ".docx")
_MIN_DOC_QUOTE_WORDS = 6
# The sizing inputs a finding may NAME so the report can mark the rows built on one. An unknown
# name is dropped from the finding, never a reason to reject it -- the most valuable findings are
# about what the analysis omitted, which by construction has no parameter name.
_PARAMETER_NAMES = frozenset(
    {"industry_total", "segment_pct", "share_pct", "customer_count", "arpu", "serviceable_pct", "target_pct"}
)
# Copy of dispatch_prompt.list_documents (skill scripts cannot import each other); keep in step.
DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")
# An `internal:analysis` quote is shown to the founder as a quotation of this analysis. A live red
# team quoted raw JSON (`"existing_claims": {"tam": 12000000000}`) -- a founder cannot read that, and
# the report must not reword a quote to make it readable. So it is set aside, per finding, with its
# reason: the sentence form exists in the analysis for anything worth quoting.
_JSON_QUOTE_RE = re.compile(r'^\s*[\[{]\s*["\[{\d]|"\w+"\s*:\s*(?:[{\["\d-]|true\b|false\b|null\b)')
# The probe's per-page floor: under this, a text layer is treated as absent and the sidecar is used.
_TEXT_LAYER_FLOOR = 100


def list_documents(uploads_dir: str | None) -> list[str]:
    """Regular files with a document suffix, sorted; dotfiles and AppleDouble `._*` excluded."""
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return []
    out: list[str] = []
    for name in sorted(os.listdir(uploads_dir)):
        if name.startswith(".") or not name.lower().endswith(DOCUMENT_SUFFIXES):
            continue
        if os.path.isfile(os.path.join(uploads_dir, name)):
            out.append(name)
    return out


def _page_text(uploads_dir: str | None, ocr_dir: str | None, filename: str, page: int) -> str | None:
    """Text of one page: the text layer if it has one, else the OCR sidecar, else None."""
    if not uploads_dir:
        return None
    path = os.path.join(uploads_dir, filename)
    if filename.lower().endswith((".md", ".txt")):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None
    try:
        import pdfplumber  # optional at runtime; absent means "no text layer here"

        with pdfplumber.open(path) as pdf:
            if 1 <= page <= len(pdf.pages):
                text = pdf.pages[page - 1].extract_text() or ""
                if len(text.strip()) >= _TEXT_LAYER_FLOOR:
                    return text
    except Exception:  # noqa: BLE001 -- any failure here means "no text layer", never a crash
        pass
    if ocr_dir:
        sidecar = os.path.join(ocr_dir, f"{filename}.p{page}.txt")
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return None
    return None


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    """Emit a validation-error result and exit NON-ZERO, without touching `output_path`.

    Same contract as every other producer in this fleet: diagnostic to stdout, a line to stderr,
    `-o` left untouched, exit 1. A stub written through `-o` destroys the prior good artifact
    AND makes SKILL.md's "the pipe fails next" branch unreachable.
    """
    payload = json.dumps(result, indent=indent) + "\n"
    sys.stdout.write(payload)
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def _reject_reason(finding: Any, documents: list[str] | None = None) -> str | None:
    """Why this ONE finding cannot be shown to a founder, or None if it can.

    Per-finding, never whole-payload. An earlier design discarded the entire hand-off when any
    finding named something absent from the artifacts -- measured against a real run, the
    "known" set is exactly the twelve parameter names the sizing math uses, and EVERY finding
    about something the analysis OMITTED is by construction outside it. That gate would have
    thrown away the most valuable findings and raised a high-severity warning while doing it.

    `claim_attacked` is therefore free text and is never checked against a vocabulary.
    """
    if not isinstance(finding, dict):
        return "not an object"
    missing = [f for f in _REQUIRED_FIELDS if not str(finding.get(f) or "").strip()]
    if missing:
        return f"missing or empty: {', '.join(missing)}"
    url = str(finding["source_url"]).strip()
    doc = _DOC_RE.match(url)
    if doc:
        if doc.group(1) not in (documents or []):
            return f"source_url names a document that was not supplied: {doc.group(1)}"
        if doc.group(2) is None and doc.group(1).lower().endswith(_PAGINATED_SUFFIXES):
            return "a citation to a PDF must name the page: document:<filename>#page=<n>"
        if len(str(finding["evidence_quote"]).split()) < _MIN_DOC_QUOTE_WORDS:
            return f"quote the sentence, not a token ({_MIN_DOC_QUOTE_WORDS} words minimum for a document citation)"
    elif url.startswith(DOCUMENT_PREFIX):
        return "source_url for a document must be exactly document:<filename>#page=<n>"
    elif url == INTERNAL_PROVENANCE and _JSON_QUOTE_RE.search(str(finding["evidence_quote"])):
        return "quote this analysis in its own words, as a sentence -- not as JSON from its files"
    elif url != INTERNAL_PROVENANCE and not url.lower().startswith(("http://", "https://")):
        return f"source_url must be a web address, a document citation, or exactly {INTERNAL_PROVENANCE!r}"
    severity = finding.get("severity")
    if severity not in _SEVERITIES:
        return f"severity must be one of {', '.join(_SEVERITIES)}"
    return None


def validate_findings(
    data: dict[str, Any], uploads_dir: str | None = None, ocr_dir: str | None = None
) -> dict[str, Any]:
    """Split the sub-agent's findings into accepted and rejected, keeping both."""
    documents = list_documents(uploads_dir)
    policy = _founder_text_policy()
    humanized = 0
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for finding in data.get("findings") or []:
        reason = _reject_reason(finding, documents)
        if reason is None:
            url = str(finding["source_url"]).strip()
            quote = str(finding["evidence_quote"]).strip()
            # One shape for every provenance: web and internal findings are `null` (nothing on disk
            # to check them against); a document citation is true/false when the page has text.
            quote_verified: bool | None = None
            doc = _DOC_RE.match(url)
            if doc:
                text = _page_text(uploads_dir, ocr_dir, doc.group(1), int(doc.group(2) or 1))
                if text is not None:
                    quote_verified = bool(quote_in_doc(quote, text)[0])
            kept: dict[str, Any] = {
                "claim_attacked": str(finding["claim_attacked"]).strip(),
                "what_is_true": str(finding["what_is_true"]).strip(),
                "evidence_quote": quote,
                "source_url": url,
                "source_title": str(finding["source_title"]).strip(),
                "severity": finding["severity"],
                "quote_verified": quote_verified,
            }
            for field in _PROSE_FIELDS:
                worded, n = humanize_review_text(kept[field], documents)
                humanized += n
                kept[field] = policy.substitute(worded)
            parameter = finding.get("parameter")
            if isinstance(parameter, str) and parameter.strip() in _PARAMETER_NAMES:
                kept["parameter"] = parameter.strip()
            accepted.append(kept)
        else:
            # Keep enough to identify it without echoing a field we just called unusable.
            label = ""
            if isinstance(finding, dict):
                label = str(finding.get("claim_attacked") or "").strip()
            rejected.append({"claim_attacked": label or "(unnamed)", "reason": reason})

    # Printed to the founder under "Not checked", so worded exactly like the three prose fields.
    could_not_check = []
    for c in data.get("could_not_check") or []:
        if str(c).strip():
            worded, n = humanize_review_text(str(c).strip(), documents)
            humanized += n
            could_not_check.append(policy.substitute(worded))

    # What the red team OPENED, against what the founder SUPPLIED. Self-reported -- the only
    # evidence it is honest is the tool stream a harness records, which the e2e lane reads -- but a
    # red team that lists nothing when documents exist is caught here, and that is the live case:
    # told the artifacts were "a faithful transcription", it opened three files, none of them the
    # deck. A file opened but unreadable belongs in BOTH sources_read and could_not_check.
    # The prompt lists documents by agent-namespace PATH and their OCR sidecars beside them; an
    # honest red team echoes those. Normalise to the document's basename: strip directories, and
    # map a `<name>.p<N>.txt` sidecar to `<name>` -- reading the machine-read text of a page IS
    # reading that document. (Measured: an exact-basename match read a correct transcription of
    # the prompt as "unread", which would have put a high warning on the honest behaviour.)
    read_names: set[str] = set()
    for raw in data.get("sources_read") or []:
        base = os.path.basename(str(raw).strip())
        m = re.match(r"^(.+)\.p\d+\.txt$", base)
        read_names.add(m.group(1) if m else base)
    sources_read = [n for n in documents if n in read_names]
    sources_unread = [n for n in documents if n not in read_names]

    by_severity = {s: sum(1 for f in accepted if f["severity"] == s) for s in _SEVERITIES}
    return {
        "findings": accepted,
        "rejected": rejected,
        "could_not_check": could_not_check,
        "sources_read": sources_read,
        "sources_unread": sources_unread,
        "summary": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "unchecked": len(could_not_check),
            "sources_unread": len(sources_unread),
            "by_severity": by_severity,
            "humanized": humanized,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Validate RED_TEAM adversarial findings")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", help="Inject metadata.run_id into output (for stale-artifact detection)")
    p.add_argument("--uploads-dir", help="The founder's documents; a document: citation must name one of them")
    p.add_argument("--ocr-dir", help="ocr_uploads.py sidecars, used to check a citation to a scanned page")
    args = p.parse_args()

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None

    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("JSON must be an object")
    elif "findings" not in data:
        errors.append("Missing required key: 'findings'")
    elif not isinstance(data["findings"], list):
        errors.append("'findings' must be an array")
    elif data.get("could_not_check") is not None and not isinstance(data.get("could_not_check"), list):
        errors.append("'could_not_check' must be an array when present")

    if errors:
        stub: dict[str, Any] = {
            "validation": {"status": "invalid", "errors": errors},
            "findings": [],
            "rejected": [],
            "could_not_check": [],
            "summary": None,
        }
        if args.run_id:
            stub["metadata"] = {"run_id": args.run_id}
        _fail_invalid(stub, args.output, indent)

    assert isinstance(data, dict)
    if args.output and not args.run_id:
        # The review's copy lives under this run's hand-off dir, and compose finds it by run id. A
        # pipe without one would write a review nothing can later show is unchanged.
        _fail_invalid(
            {
                "validation": {"status": "invalid", "errors": ["--run-id is required with -o"]},
                "findings": [],
                "rejected": [],
                "could_not_check": [],
                "summary": None,
            },
            args.output,
            indent,
        )
    try:
        _founder_text_policy()
    except ImportError as exc:
        _fail_invalid(
            {
                "validation": {
                    "status": "invalid",
                    "errors": [f"the plugin's shared scripts are not reachable: {exc}"],
                },
                "findings": [],
                "rejected": [],
                "could_not_check": [],
                "summary": None,
                **({"metadata": {"run_id": args.run_id}} if args.run_id else {}),
            },
            args.output,
            indent,
        )
    result = validate_findings(data, args.uploads_dir, args.ocr_dir)
    # An EMPTY findings list is a valid, meaningful result and must never be an error: a red team
    # that always finds something is a red team nobody believes, and making zero findings a
    # failure is how a step learns to manufacture them.
    result["validation"] = {"status": "valid", "errors": []}

    if args.run_id:
        result["metadata"] = {"run_id": args.run_id}

    summary = dict(result["summary"])
    if args.output:
        # The copy FIRST: a review written without its copy is one compose cannot vouch for, so a
        # failed copy leaves -o untouched and fails loudly.
        assert args.run_id
        analysis_dir = os.path.dirname(os.path.abspath(args.output))
        try:
            summary["round"] = write_copy(
                analysis_dir, args.run_id, result, hashlib.sha256(raw.encode("utf-8")).hexdigest()
            )
        except OSError as exc:
            _fail_invalid(
                {
                    **result,
                    "validation": {"status": "invalid", "errors": [f"could not write the review's copy: {exc}"]},
                },
                args.output,
                indent,
            )

    out = json.dumps(result, indent=indent) + "\n"
    _write_output(out, args.output, summary=summary)


if __name__ == "__main__":
    main()
