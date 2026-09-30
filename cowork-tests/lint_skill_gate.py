#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Gate `cowork-harness lint-skill --json` against a pinned, shrink-only allowlist.

`lint-skill --strict` exits 1 on any WARN and has no per-rule suppression. Some of its warnings are ones this
repo accepts on purpose (see lint-skill-allowlist.json, each with its reason). Dropping `--strict` would stop
gating every WARN rule, including ones the harness adds later; this keeps them all gated and names the accepted
findings by (rule, file, count):

  * any ERROR fails;
  * a WARN whose (rule, file) is not accepted fails, and so does an accepted pair firing MORE times than its
    count (a new site in an accepted file is a new finding);
  * an accepted pair firing FEWER times, or not at all, fails too: lower or remove the entry, so the list only
    shrinks and never goes on excusing a finding that is gone;
  * INFO is ignored; output that is not a JSON list of findings fails (a crashed lint is not a pass).

Usage (CI):
    cowork-harness lint-skill founder-skills/skills/*/ --json > ls.json || true
    python3 cowork-tests/lint_skill_gate.py ls.json
Exit 0 pass, 1 fail. Prints one line per problem.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWLIST = Path(__file__).resolve().parent / "lint-skill-allowlist.json"


def problems(findings: list[dict[str, Any]], accepted: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for f in findings:
        if str(f.get("severity")).upper() == "ERROR":
            out.append(f"ERROR {f.get('rule')} at {f.get('file')}:{f.get('line')} — errors are never accepted")
    warns = Counter(
        (str(f.get("rule")), str(f.get("file"))) for f in findings if str(f.get("severity")).upper() == "WARN"
    )
    allowed = {(str(a["rule"]), str(a["file"])): int(a["count"]) for a in accepted}
    for (rule, file), n in sorted(warns.items()):
        want = allowed.get((rule, file), 0)
        if n > want:
            what = "not accepted" if want == 0 else f"accepted {want}, fired {n}"
            out.append(f"WARN {rule} at {file} ({what}) — fix it, or accept it with a reason in a reviewed change")
    for (rule, file), want in sorted(allowed.items()):
        n = warns.get((rule, file), 0)
        if n < want:
            out.append(f"accepted {rule} at {file} fires {n} of {want} — shrink the allowlist entry to {n}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lint_json", type=Path, help="`lint-skill --json` output")
    ap.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    a = ap.parse_args()
    try:
        findings = json.loads(a.lint_json.read_text(encoding="utf-8"))
        accepted = json.loads(a.allowlist.read_text(encoding="utf-8"))["accepted"]
    except (OSError, ValueError, KeyError) as e:
        print(f"lint_skill_gate: cannot read the lint output or the allowlist: {e}", file=sys.stderr)
        return 1
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        print("lint_skill_gate: the lint output is not a JSON list of findings", file=sys.stderr)
        return 1
    found = problems(findings, accepted)
    for p in found:
        print(p)
    if not found:
        print(f"lint-skill: {len(findings)} finding(s), all accepted or informational")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
