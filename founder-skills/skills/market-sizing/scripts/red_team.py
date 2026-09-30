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
import sys
from typing import Any, NoReturn

import _redteam_copy
from _quote_match import quote_in_doc
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


# Which findings may reach a founder, and which review is shown, are decided in the plugin's shared
# `scripts/_redteam_core.py` (loaded through `_redteam_copy.core()`), because every skill with a
# reviewer follows the same rules and a rule with two copies drifts. What is a sizing's own is below.

# The sizing inputs a finding may NAME so the report can mark the rows built on one. An unknown
# name is dropped from the finding, never a reason to reject it -- the most valuable findings are
# about what the analysis omitted, which by construction has no parameter name.
_PARAMETER_NAMES = frozenset(
    {"industry_total", "segment_pct", "share_pct", "customer_count", "arpu", "serviceable_pct", "target_pct"}
)


# The probe's per-page floor: under this, a text layer is treated as absent and the sidecar is used.
_TEXT_LAYER_FLOOR = 100


# The page reader this review checks a document citation with. It stays here, and is handed to the
# shared validation, because the report checks a founder's quote with a copy of it (`_view._page_text`)
# and the two are pinned identical: a quote the review verified must verify on the page the same way.
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


def validate_findings(
    data: dict[str, Any], uploads_dir: str | None = None, ocr_dir: str | None = None
) -> dict[str, Any]:
    """Split the sub-agent's findings into accepted and rejected, keeping both."""
    policy = _founder_text_policy()
    result: dict[str, Any] = _redteam_copy.core().validate_findings(
        data,
        uploads_dir,
        ocr_dir,
        page_text=_page_text,
        quote_in_doc=quote_in_doc,
        humanize=humanize_review_text,
        substitute=policy.substitute,
        prose_fields=_PROSE_FIELDS,
        parameter_names=_PARAMETER_NAMES,
    )
    return result


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
        _redteam_copy.core()
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
            summary["round"] = _redteam_copy.write_copy(
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
