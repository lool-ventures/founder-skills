#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Release the pool-checked coaching commentary to `insert_coaching.py`, only if this run's check passed it.

    pool_check_release.py coaching.md --checked coaching.checked.json --scenarios scenarios.json -o released.json
    insert_coaching.py --commentary-file released.json --report ...

`pool_claims_check.py` writes a file insert_coaching does not accept, and a record beside the commentary. This
reads the record and refuses -- exit 1, `{"status": "refused", "reason": ...}` on stdout, one line on stderr, `-o`
left untouched -- unless every one of these holds:

- the record exists (`<coaching.md>.pool-check.json`): the check ran on this commentary;
- its `sha256` is the commentary's as it is now: nothing edited it after the check;
- its `output_sha256` is the checked file's: nothing replaced that file after the check;
- its `action` passed the commentary (clean, stripped, not judged, no pool target, or could not run), not
  `findings`, which is still open;
- its `run_id` is this run's (`scenarios.json` metadata). Always: the check reads the run before it can fail
  open, and refuses (exit 2, no checked file) when it cannot.

On success it writes `{"commentary_markdown": ..., "check_record": <the record's path>}` to `-o`, the envelope
insert_coaching reads: cap-table's report declares that it needs a passing record, and this names it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any

CHECKED_KEY = "checked_commentary_markdown"
_PASSED = frozenset({"clean", "stripped", "not_judged", "no_pool_target", "error"})


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _refuse(reason: str) -> int:
    print(json.dumps({"status": "refused", "reason": reason}))
    print(f"pool_check_release: refused: {reason}", file=sys.stderr)
    return 1


def release(coaching_md: str, checked: str, scenarios: str) -> tuple[dict[str, Any] | None, str]:
    """(the envelope, "") or (None, why it is refused)."""
    record_path = f"{coaching_md}.pool-check.json"
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None, "no pool-check record for this commentary: run pool_claims_check.py on it first"
    if record.get("action") not in _PASSED:
        return None, f"the pool check did not pass this commentary (action: {record.get('action')})"
    try:
        if record.get("sha256") != _sha256(coaching_md):
            return None, "the commentary changed after the pool check: run pool_claims_check.py on it again"
        if record.get("output_sha256") != _sha256(checked):
            return None, "the checked file is not the one the pool check wrote: run pool_claims_check.py again"
        with open(checked, encoding="utf-8") as f:
            text = json.load(f).get(CHECKED_KEY)
    except (OSError, ValueError, AttributeError):
        return None, "the checked file is missing or unreadable: run pool_claims_check.py again"
    if not isinstance(text, str) or not text.strip():
        return None, "the checked file carries no commentary"
    try:
        with open(scenarios, encoding="utf-8") as f:
            run_id = (json.load(f).get("metadata") or {}).get("run_id")
    except (OSError, ValueError, AttributeError):
        return None, "cannot read this run's scenarios.json to match the record's run"
    if not run_id or record.get("run_id") != run_id:
        return None, "the pool-check record is from another run: run pool_claims_check.py again"
    return {"commentary_markdown": text, "check_record": os.path.abspath(record_path)}, ""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("coaching_md")
    p.add_argument("--checked", required=True, help="the file pool_claims_check.py wrote with -o")
    p.add_argument("--scenarios", required=True)
    p.add_argument("-o", "--output", required=True, help="the envelope insert_coaching.py --commentary-file reads")
    a = p.parse_args()
    envelope, why = release(a.coaching_md, a.checked, a.scenarios)
    if envelope is None:
        return _refuse(why)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(envelope, f)
    print(json.dumps({"status": "released", "output_path": os.path.abspath(a.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
