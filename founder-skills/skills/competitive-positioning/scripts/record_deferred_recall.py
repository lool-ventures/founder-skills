#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record recall candidates the founder declined at Gate 1 in landscape_draft.json.

WHY THIS EXISTS. A blind-recall candidate the founder does not approve at the competitor-set gate is
kept, not dropped: it goes into the draft's top-level `deferred_recall_candidates[]` so the later
additions gate can offer it again. Writing that by hand meant editing `landscape_draft.json`, and a
whole-file rewrite drops its `_produced_by` stamp, which `compose_report.py` reports as
`UNVALIDATED_ARTIFACT` at HIGH severity on a run that did everything right. This script appends in
place and leaves every other key, the stamp included, exactly as it was.

Input (stdin): one entry or a JSON array of entries, each
  {"name": str, "slug": str, "category": str | null, "why_considered": str, "sources": [...]}
`sources` is a non-empty list whose items are non-empty strings (URLs, as the recall dispatch returns
them) or objects carrying a non-empty string `url`.

`category` MAY be absent or null. The recall dispatch returns one, but the recall-gap list Gate 1
shows the founder (`competitor_verification.json` `recall_gaps.unmatched`) carries slug, name,
why_considered and sources but no category, so requiring it would refuse an entry copied from the
list the founder actually answered. When present it must be a non-empty string.

De-duplicated by slug, normalized as `verify_competitors.normalize_competitor_slug` normalizes it
(so `Acme, Inc.` and `acme` are one candidate), first kept: an entry already in the draft wins over a
new one, and within the input the earlier entry wins. An entry whose normalized slug is already in the
draft's `competitors[]` is skipped too: it was adopted, so it is not deferred (the same rule
`validate_landscape.py --carry-deferred` applies later). Entries are stored as given; skipped slugs
are named in the receipt.

All-or-nothing, per the fleet producer contract: if any entry, the draft, or its existing
`deferred_recall_candidates` is invalid, nothing is written -- diagnostic JSON on stdout, a line on
stderr, the draft untouched, exit 1. The draft is replaced atomically (temp file + rename).

Usage:
  python3 record_deferred_recall.py --draft "$ANALYSIS_DIR/landscape_draft.json" [--pretty] [-o receipt.json] <<'JSON'
  [{"name": "...", "slug": "...", "category": "adjacent", "why_considered": "...", "sources": ["https://..."]}]
  JSON
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from typing import Any, NoReturn

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from verify_competitors import normalize_competitor_slug  # noqa: E402

FIELD = "deferred_recall_candidates"
REQUIRED_STRINGS = ("name", "slug", "why_considered")


def _fail_invalid(result: dict[str, Any], draft_path: str | None, indent: int | None) -> NoReturn:
    """Reject loudly without touching the draft. Canonical copy: market-sizing/market_sizing.py."""
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if draft_path:
        print(f"Error: {os.path.abspath(draft_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_entry(entry: Any, index: int) -> list[str]:
    """Return the problems with one entry; empty when it is valid."""
    where = f"entry {index}"
    if not isinstance(entry, dict):
        return [f"{where}: must be an object, got {type(entry).__name__}"]
    errors: list[str] = []
    for key in REQUIRED_STRINGS:
        if not _nonempty(entry.get(key)):
            errors.append(f"{where}: '{key}' must be a non-empty string")
    category = entry.get("category")
    if category is not None and not _nonempty(category):
        errors.append(f"{where}: 'category' must be a non-empty string or null")
    sources = entry.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append(f"{where}: 'sources' must be a non-empty list")
    else:
        for j, src in enumerate(sources):
            if _nonempty(src) or (isinstance(src, dict) and _nonempty(src.get("url"))):
                continue
            errors.append(f"{where}: sources[{j}] must be a non-empty string or an object with a non-empty 'url'")
    return errors


def _write_atomic(path: str, payload: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".record_deferred_recall.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft", required=True, help="Path to landscape_draft.json (updated in place)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print the JSON receipt")
    ap.add_argument("-o", "--output", help="Also write the JSON receipt to this file")
    args = ap.parse_args()
    indent = 2 if args.pretty else None
    draft_path: str = args.draft

    def reject(errors: list[str]) -> NoReturn:
        _fail_invalid({"validation": {"status": "invalid", "errors": errors}}, draft_path, indent)

    raw = sys.stdin.read()
    if not raw.strip():
        reject(["empty input: pipe one entry or a JSON array of entries on stdin"])
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        reject([f"input is not valid JSON: {exc}"])
    entries = payload if isinstance(payload, list) else [payload]
    if not entries:
        reject(["input is an empty array: nothing to record"])
    errors = [e for i, entry in enumerate(entries) for e in validate_entry(entry, i)]
    if errors:
        reject(errors)

    try:
        with open(draft_path, encoding="utf-8") as f:
            draft: Any = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        reject([f"cannot read the draft {draft_path}: {exc}"])
    if not isinstance(draft, dict):
        reject([f"the draft must be a JSON object, got {type(draft).__name__}"])
    existing = draft.get(FIELD, [])
    if not isinstance(existing, list):
        reject([f"the draft's '{FIELD}' must be an array, got {type(existing).__name__}"])

    def norm(v: Any) -> str:
        return normalize_competitor_slug(v) if isinstance(v, str) else ""

    competitors = draft.get("competitors")
    adopted = (
        {norm(c.get("slug")) for c in competitors if isinstance(c, dict)} if isinstance(competitors, list) else set()
    )
    adopted.discard("")
    seen = {norm(e.get("slug")) for e in existing if isinstance(e, dict)}
    added: list[str] = []
    skipped: list[str] = []
    skipped_adopted: list[str] = []
    merged = list(existing)
    for entry in entries:
        slug = entry["slug"]
        key = norm(slug) or slug
        if key in adopted:
            skipped_adopted.append(slug)
            continue
        if key in seen:
            skipped.append(slug)
            continue
        seen.add(key)
        merged.append(entry)
        added.append(slug)

    if added:
        draft[FIELD] = merged  # every other key, `_produced_by` included, is left as read
        _write_atomic(draft_path, json.dumps(draft, indent=2) + "\n")

    receipt = {
        "ok": True,
        "draft": os.path.abspath(draft_path),
        "added": added,
        "skipped_duplicate_slugs": skipped,
        "skipped_already_competitors": skipped_adopted,
        "deferred_recall_candidates": len(merged),
    }
    text = json.dumps(receipt, indent=indent) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
