#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Validate the STARTUP_RESEARCH hand-off and compute each publication's status.

The analysis used to research competitors and never the startup's own public record. A real run
called a granted patent family "pending": nothing looked it up, so the founder's pitch was the only
source. This step records what public records show -- the legal name, and the startup's patent
publications -- and this producer decides the status, so no status the model types reaches the
founder.

STATUS IS COMPUTED, and conservatively:
  * `granted`   -- the publication's own (office, kind) pair is in GRANTED_KINDS.
  * `published` -- its (office, kind) pair is in PUBLISHED_KINDS: an application was published and
                   nothing here shows a grant. Deliberately not "pending", which would assert it is
                   still alive.
  * `unknown`   -- anything else. Kind codes are per office: the same letter can mean a grant in one
                   office and nothing in another, so an unlisted pair is never guessed at.
  A publication also carries `grant_event: true` when a recorded legal event is in GRANT_EVENTS (a
  national-office grant recorded against a WIPO publication). The family is `granted` when any
  member is granted or carries a grant event.

RESIDUAL, stated: the numbers, kind codes and events are recorded by the research sub-agent from
search results. Freezing the first copy (`_cp_first_copy`) stops a later rewrite; it does not verify
the first record. Every rendered publication therefore shows its source, so the founder can check
it.

Rejects loudly: diagnostic JSON to stdout, a line to stderr, `-o` untouched, exit 1.

Usage:
    cat startup_research_output.json | python validate_startup_research.py --run-id R -o startup_research.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

# (office, kind) pairs known to mean a granted patent. Small on purpose: extend only from an
# authoritative kind-code table, one office at a time.
GRANTED_KINDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("US", "B1"),
        ("US", "B2"),
        ("EP", "B1"),
        ("EP", "B2"),
    }
)
# (office, kind) pairs known to mean a published application.
PUBLISHED_KINDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("WO", "A1"),
        ("WO", "A2"),
        ("WO", "A3"),
        ("US", "A1"),
        ("US", "A2"),
        ("EP", "A1"),
        ("EP", "A2"),
    }
)
# Legal-event codes that record a grant. WWG: WIPO's "grant in a national office" event, recorded
# against the WO publication of a family.
GRANT_EVENTS: frozenset[str] = frozenset({"WWG"})

SEARCH_KINDS = frozenset({"registry", "inventor", "applicant", "publication", "status", "other"})
READ_PARTS = frozenset({"none", "abstract", "claims", "full_text"})


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def publication_status(office: str, kind: str) -> str:
    """`granted`, `published` or `unknown` for one (office, kind) pair."""
    pair = (office.strip().upper(), kind.strip().upper())
    if pair in GRANTED_KINDS:
        return "granted"
    if pair in PUBLISHED_KINDS:
        return "published"
    return "unknown"


def validate(data: Any) -> tuple[dict[str, Any], list[str]]:
    """Return (result, errors). Errors mean the input is rejected."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return {}, ["input must be a JSON object"]

    legal = data.get("legal_name")
    if legal is not None and not (
        isinstance(legal, dict)
        and (legal.get("value") is None or _nonempty(legal.get("value")))
        and (legal.get("value") is None or _nonempty(legal.get("source")))
    ):
        errors.append("legal_name must be {value, source}; a value needs a source")

    searches = data.get("searches")
    if not isinstance(searches, list) or not searches:
        errors.append("searches must be a non-empty list: record every search, including those that found nothing")
        searches = []
    for i, s in enumerate(searches):
        if not isinstance(s, dict) or not _nonempty(s.get("query")) or s.get("kind") not in SEARCH_KINDS:
            errors.append(f"searches[{i}] needs a query and a kind in {sorted(SEARCH_KINDS)}")
        elif not isinstance(s.get("found"), bool):
            errors.append(f"searches[{i}].found must be true or false")

    pubs_in = data.get("publications", [])
    if not isinstance(pubs_in, list):
        errors.append("publications must be a list (empty when none were found)")
        pubs_in = []
    publications: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, p in enumerate(pubs_in):
        if not isinstance(p, dict):
            errors.append(f"publications[{i}] must be an object")
            continue
        number, office, kind = p.get("number"), p.get("office"), p.get("kind")
        if not (_nonempty(number) and _nonempty(office) and _nonempty(kind)):
            errors.append(f"publications[{i}] needs number, office and kind")
            continue
        if not _nonempty(p.get("source")):
            errors.append(f"publications[{i}] ({number}) needs a source: the URL or the exact query")
            continue
        if p.get("read", "none") not in READ_PARTS:
            errors.append(f"publications[{i}] ({number}).read must be one of {sorted(READ_PARTS)}")
            continue
        events = p.get("events", [])
        if not isinstance(events, list) or not all(isinstance(e, dict) and _nonempty(e.get("code")) for e in events):
            errors.append(f"publications[{i}] ({number}).events must be a list of {{code, date}}")
            continue
        key = str(number).strip().upper()
        if key in seen:
            errors.append(f"publications[{i}]: duplicate number {number}")
            continue
        seen.add(key)
        status = publication_status(str(office), str(kind))
        grant_event = any(str(e.get("code")).strip().upper() in GRANT_EVENTS for e in events)
        publications.append({**p, "status": status, "grant_event": grant_event})

    if errors:
        return {"validation": {"status": "invalid", "errors": errors}}, errors

    if any(p["status"] == "granted" or p["grant_event"] for p in publications):
        family_status = "granted"
    elif any(p["status"] == "published" for p in publications):
        family_status = "published"
    elif publications:
        family_status = "unknown"
    else:
        family_status = "none_found"

    result = {
        "legal_name": legal,
        "searches": searches,
        "searched_none": [s["query"] for s in searches if s.get("found") is False],
        "publications": publications,
        "family_status": family_status,
        "_produced_by": "validate_startup_research",
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
    }
    return result, []


def _fail_invalid(result: dict[str, Any], output_path: str | None) -> NoReturn:
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Validate STARTUP_RESEARCH and compute publication status")
    p.add_argument("--run-id", default=None, help="Stamp metadata.run_id")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("-o", "--output", help="Write the artifact to this path (a receipt goes to stdout)")
    a = p.parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    result, errors = validate(data)
    if a.run_id:
        result.setdefault("metadata", {})["run_id"] = a.run_id
    if errors:
        _fail_invalid(result, a.output)

    text = json.dumps(result, indent=2 if a.pretty else None) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import _cp_first_copy

        _cp_first_copy.keep_first(a.output, result)
        print(json.dumps({"ok": True, "path": os.path.abspath(a.output), "family_status": result["family_status"]}))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
