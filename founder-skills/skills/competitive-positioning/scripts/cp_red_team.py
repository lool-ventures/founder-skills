#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Validator for the RED_TEAM sub-agent's adversarial findings on a competitive-positioning analysis.

The reviewer attacks the finished analysis and writes a findings file. This validates that file and
produces `redteam.json`. It is a VALIDATOR, not a detector: it never decides whether a finding is
correct, only whether it is evidenced well enough to put in front of a founder. The rules are the
fleet's (`scripts/_redteam_core.py`); what is this skill's is the wording of the review's prose -- a
competitor's slug becomes its name, a file or field name becomes plain words (`_cp_redteam_text`) --
and what a review is taken against (`_cp_redteam_copy.reviewed_state`).

Named apart from market-sizing's `red_team.py`: the test suite imports skill scripts into one process.

Always reads JSON from stdin. The analysis dir is `-o`'s directory unless `--analysis-dir` says
otherwise; its `landscape.json` supplies the competitors' names, and a review cannot be worded without
them, so an unreadable landscape is refused rather than letting a slug through.

Usage:
    cat redteam_output.json | python cp_red_team.py --run-id R --uploads-dir H/docs -o A/redteam.json

Output: JSON with accepted findings, rejected findings (each with its reason), and a summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, NoReturn

import _cp_redteam_copy
import _cp_view
from _cp_redteam_text import humanize_review_text
from _quote_match import quote_in_doc

_SHARED_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
)
_PROSE_FIELDS = ("claim_attacked", "what_is_true", "source_title")


def _founder_text_policy() -> Any:
    if _SHARED_SCRIPTS not in sys.path:
        sys.path.insert(0, _SHARED_SCRIPTS)
    import _founder_text  # type: ignore[import-not-found]

    return _founder_text


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def names_from(analysis_dir: str) -> tuple[dict[str, str], str | None]:
    """(slug -> name, the startup's name), the way the report names them (`_cp_view.competitor_names`).
    Raises ValueError when the landscape cannot be read."""
    try:
        landscape = _load(os.path.join(analysis_dir, "landscape.json"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read landscape.json for the competitors' names: {exc}") from exc
    if not isinstance(landscape, dict):
        raise ValueError("landscape.json is not an object")
    try:
        draft = _load(os.path.join(analysis_dir, "landscape_draft.json"))
    except (OSError, ValueError):
        draft = None
    names = _cp_view.competitor_names(landscape, draft if isinstance(draft, dict) else None)
    startup: str | None = None
    try:
        profile = _load(os.path.join(analysis_dir, "product_profile.json"))
        value = profile.get("company_name") if isinstance(profile, dict) else None
        startup = value.strip() if isinstance(value, str) and value.strip() else None
    except (OSError, ValueError):
        startup = None
    return names, startup


def validate_findings(
    data: dict[str, Any],
    uploads_dir: str | None,
    *,
    name_by_slug: dict[str, str],
    startup_name: str | None,
) -> dict[str, Any]:
    """Split the sub-agent's findings into accepted and rejected, keeping both."""
    policy = _founder_text_policy()
    core = _cp_redteam_copy.core()

    def humanize(text: str, documents: list[str]) -> tuple[str, int]:
        return humanize_review_text(text, documents, name_by_slug=name_by_slug, startup_name=startup_name)

    result: dict[str, Any] = core.validate_findings(
        data,
        uploads_dir,
        None,  # no machine-read copies for this skill: a scanned page stays "not machine-checked"
        page_text=core.page_text,
        quote_in_doc=quote_in_doc,
        humanize=humanize,
        substitute=policy.substitute,
        prose_fields=_PROSE_FIELDS,
        parameter_names=frozenset(),
    )
    return result


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    if output_path:
        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def _fail_invalid(errors: list[str], output_path: str | None, indent: int | None, run_id: str | None) -> NoReturn:
    """Diagnostic to stdout, a line to stderr, `-o` untouched, exit 1 -- the fleet's producer contract."""
    result: dict[str, Any] = {
        "validation": {"status": "invalid", "errors": errors},
        "findings": [],
        "rejected": [],
        "could_not_check": [],
        "summary": None,
    }
    if run_id:
        result["metadata"] = {"run_id": run_id}
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Validate the RED_TEAM review of a competitive-positioning analysis")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", help="Inject metadata.run_id into output (required with -o)")
    p.add_argument("--uploads-dir", help="The founder's documents; a document: citation must name one of them")
    p.add_argument("--analysis-dir", help="The analysis dir (default: -o's directory)")
    args = p.parse_args()
    indent = 2 if args.pretty else None

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        _fail_invalid(["JSON must be an object"], args.output, indent, args.run_id)
    if "findings" not in data:
        _fail_invalid(["Missing required key: 'findings'"], args.output, indent, args.run_id)
    if not isinstance(data["findings"], list):
        _fail_invalid(["'findings' must be an array"], args.output, indent, args.run_id)
    for key in ("could_not_check", "sources_read"):
        if data.get(key) is not None and not isinstance(data.get(key), list):
            _fail_invalid([f"'{key}' must be an array when present"], args.output, indent, args.run_id)
    if args.output and not args.run_id:
        # The review's copy lives under this run's hand-off dir, and compose finds it by run id.
        _fail_invalid(["--run-id is required with -o"], args.output, indent, args.run_id)
    analysis_dir = args.analysis_dir or (os.path.dirname(os.path.abspath(args.output)) if args.output else None)
    if analysis_dir is None:
        _fail_invalid(["--analysis-dir is required without -o"], args.output, indent, args.run_id)
    try:
        _founder_text_policy()
        _cp_redteam_copy.core()
    except ImportError as exc:
        _fail_invalid([f"the plugin's shared scripts are not reachable: {exc}"], args.output, indent, args.run_id)
    try:
        name_by_slug, startup_name = names_from(analysis_dir)
    except ValueError as exc:
        _fail_invalid([str(exc)], args.output, indent, args.run_id)

    result = validate_findings(data, args.uploads_dir, name_by_slug=name_by_slug, startup_name=startup_name)
    # An EMPTY findings list is a valid, meaningful result and must never be an error: a red team that
    # always finds something is a red team nobody believes.
    result["validation"] = {"status": "valid", "errors": []}
    result["_produced_by"] = "cp_red_team"
    if args.run_id:
        result["metadata"] = {"run_id": args.run_id}

    summary = dict(result["summary"])
    if args.output:
        # The copy FIRST: a review written without its copy is one compose cannot vouch for, so a failed
        # copy leaves -o untouched and fails loudly.
        assert args.run_id
        try:
            summary["round"] = _cp_redteam_copy.write_copy(
                analysis_dir, args.run_id, result, hashlib.sha256(raw.encode("utf-8")).hexdigest()
            )
        except OSError as exc:
            _fail_invalid([f"could not write the review's copy: {exc}"], args.output, indent, args.run_id)

    _write_output(json.dumps(result, indent=indent) + "\n", args.output, summary=summary)


if __name__ == "__main__":
    main()
