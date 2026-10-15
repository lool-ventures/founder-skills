#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Adds the context supplied with the request to the simulation's startup profile.

    host_context.py --run-id R --profile <SIM_DIR>/startup_profile.json [--pretty]

Run right after the model writes `startup_profile.json` (Steps 2-3). The context is a request line
(`FS_HOST_VALUE host_context=supplied | <JSON array of {fact, source, date}>`) that Step 1's `open` applied and
checked; the ledger holds the value and what the check kept and dropped. This script copies the KEPT items into
the profile as `host_context` (the model never types them), so every dispatch that pastes the profile carries
them, and compose can check the profile against the ledger.

- No run ledger (no `run_ref.json` for the run): exit 0, nothing written.
- The question was not answered with the request's context: a profile carrying `host_context` is refused
  (`HOST_CONTEXT_NOT_SUPPLIED`, exit 1, file untouched); otherwise exit 0, nothing written.
- Answered: the ledger's value must still hash to what was checked and filter to the same items, else
  `GATE_RECORD_MISMATCH` (exit 1, file untouched). The profile is rewritten with `host_context` (kept items
  only, characters not escapes); any `host_context` the model wrote is replaced. A re-run writes the same bytes.

The items are supplied with the request: third-party to the analysis, never the founder's own statements.
`host_context_lines` is the one owner of their founder-facing wording (compose and the page render it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import date
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _host_text  # noqa: E402

GATE = "host_context"
OPTION = "supplied"
PROVENANCE = "supplied_with_request"
INTRO = (
    "These facts were supplied with this request. They were not checked in this run and are not the founder's "
    "own statements; each date is the one supplied with the fact."
)
NONE_USED = "None of the facts supplied with this request could be used."


def _refuse(code: str, message: str, profile: str) -> NoReturn:
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message}) + "\n")
    print(f"Error ({code}): {message}; {profile} was left unchanged", file=sys.stderr)
    sys.exit(1)


def _ok(payload: dict[str, Any], pretty: bool) -> NoReturn:
    sys.stdout.write(json.dumps({"status": "ok", **payload}, indent=2 if pretty else None) + "\n")
    sys.exit(0)


def block_from_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    """The `host_context` block for an answered `supplied` entry, re-derived from the ledger's value. Raises
    ValueError naming what no longer agrees with the record."""
    cur = entry.get("current") or {}
    value = cur.get("value")
    evidence = cur.get("evidence") or {}
    if not isinstance(value, str):
        raise ValueError("the recorded context has no value")
    sha = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if sha != evidence.get("sha256"):
        raise ValueError("the recorded context no longer hashes to what was checked")
    try:
        as_of = date.fromisoformat(str(evidence.get("as_of")))
    except ValueError as e:
        raise ValueError("the recorded check has no run start date") from e
    kept, dropped = _host_text.parse_and_filter(value, as_of)
    if [k["index"] for k in kept] != evidence.get("kept") or dropped != evidence.get("dropped"):
        raise ValueError("the recorded context no longer filters to what was checked")
    return {"provenance": PROVENANCE, "sha256": sha, "items": kept, "dropped": dropped}


def host_context_parts(
    profile: dict[str, Any] | None, escape: Callable[[str], str] | None = None
) -> tuple[str, list[str], list[str]] | None:
    """(the provenance sentence, one line per kept fact as `<fact> (<source>, <date>)` passed through `escape`
    when given, the closing sentences: none used, and which facts were not used and why), or None when the
    profile carries no context."""
    block = profile.get("host_context") if isinstance(profile, dict) else None
    if not isinstance(block, dict):
        return None
    items = [i for i in block.get("items") or [] if isinstance(i, dict)]
    dropped = [d for d in block.get("dropped") or [] if isinstance(d, dict)]
    lines = []
    for item in items:
        text = f"{item.get('fact', '')} ({item.get('source', '')}, {item.get('date', '')})"
        lines.append(escape(text) if escape is not None else text)
    closing = [] if items else [NONE_USED]
    sentence = _host_text.dropped_sentence(dropped, len(items) + len(dropped))
    if sentence:
        closing.append(sentence)
    return INTRO, lines, closing


def host_context_lines(profile: dict[str, Any] | None, escape: Callable[[str], str] | None = None) -> list[str]:
    """The founder-facing lines for a profile's `host_context`, in order (`host_context_parts` flattened): what
    the report and the page render, verbatim. Empty when the profile carries none."""
    parts = host_context_parts(profile, escape)
    if parts is None:
        return []
    intro, items, closing = parts
    return [intro, *items, *closing]


def kept_texts(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The kept items of a profile's `host_context` (for the founder-text keep-set)."""
    block = profile.get("host_context") if isinstance(profile, dict) else None
    items = block.get("items") if isinstance(block, dict) else None
    return [i for i in items or [] if isinstance(i, dict)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Add the context supplied with the request to startup_profile.json")
    p.add_argument("--run-id", required=True, help="the run's id")
    p.add_argument("--profile", required=True, help="the simulation's startup_profile.json")
    p.add_argument("--pretty", action="store_true", help="pretty-print the receipt")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    profile_path = os.path.abspath(args.profile)
    import _out_guard

    _out_guard.refuse_output_onto_input([profile_path], script="host_context.py", in_place=[profile_path])
    import _run_ref

    sim_dir = os.path.dirname(profile_path)
    _run_ref.refuse_not_this_runs(os.path.dirname(os.path.abspath(args.profile)), args.run_id, noun="simulation dir")
    try:
        opened = _run_ref.open_ledger(sim_dir, args.run_id)
    except _run_ref.LedgerUnavailable as e:
        sys.exit(_run_ref.report_failure(e))
    if opened is None:
        _ok({"host_context": "no_ledger", "written": False}, args.pretty)
    gates, paths = opened
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
    except (OSError, ValueError) as e:
        _refuse("PROFILE_UNREADABLE", f"startup_profile.json cannot be read ({e})", profile_path)
    if not isinstance(profile, dict):
        _refuse("PROFILE_UNREADABLE", "startup_profile.json is not a JSON object", profile_path)
    entry = (gates.load_ledger(paths).get("gates") or {}).get(GATE) or {}
    cur = entry.get("current") or {}
    if entry.get("state") != "answered" or cur.get("answer_id") != OPTION:
        if GATE in profile:
            _refuse(
                "HOST_CONTEXT_NOT_SUPPLIED",
                "startup_profile.json carries host_context, but no context was supplied with this request for this "
                "run; write the profile again without it, then run this again",
                profile_path,
            )
        _ok({"host_context": "not_supplied", "written": False}, args.pretty)
    try:
        block = block_from_ledger(entry)
    except ValueError as e:
        _refuse("GATE_RECORD_MISMATCH", f"{e}; start a new run with the request's lines", profile_path)
    profile[GATE] = block
    text = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    # Every line-splitting character was dropped with its item: nothing written may split a line.
    assert not any(ch in text for ch in (" ", " ", "\u0085")), "a line separator reached the profile"
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(text)
    _ok(
        {
            "host_context": "written",
            "written": True,
            "path": profile_path,
            "kept": len(block["items"]),
            "dropped": len(block["dropped"]),
        },
        args.pretty,
    )


if __name__ == "__main__":
    main()
