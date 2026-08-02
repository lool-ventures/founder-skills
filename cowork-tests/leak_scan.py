#!/usr/bin/env python3
"""Founder-facing "internal plumbing" leak detector.

Scans the founder-visible assistant narration in cowork-harness cassettes (or
any events.jsonl transcript) for developer-facing tokens that should never reach
a founder: code spans, script/flag/var syntax, exit codes, W_/E_ warning codes,
and internal step/route labels ("Lane N", "Context A/B", "the grid", …).

The class-based patterns double as the SKILL.md rule's enforcement instrument:
the rule bans exactly these classes, and this scanner measures whether the skills
actually keep them out of the chat. Run it over the committed cassettes for a
base rate; the ratchet test (`test_founder_facing_leaks.py`) prevents regressions.

Usage:
    python3 cowork-tests/leak_scan.py cowork-tests/cassettes/            # scan a dir
    python3 cowork-tests/leak_scan.py path/to/one.cassette.json --show   # + show text
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Each class is (name, compiled regex). Matched against FOUNDER-FACING assistant
# text only. Kept deliberately class-based (not an enumerated token list) so new
# internal tokens are caught without maintenance — see the adversarial review that
# motivated this (an enumerated blocklist is unwinnable).
LEAK_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    # A founder-facing message should carry no code spans at all — the model wraps
    # filenames / identifiers / warning codes in backticks. Highest-signal class.
    ("code_span", re.compile(r"`[^`\n]+`")),
    ("exit_code", re.compile(r"\bExit\s+\d+\b|\bexit code\b|\bnot found\b", re.I)),
    ("warn_err_code", re.compile(r"\b[WE]_[A-Z][A-Z0-9_]{2,}\b")),
    ("script_name", re.compile(r"\b[\w./-]+\.py\b")),
    ("cli_flag", re.compile(r"(?<!\w)--[a-z][\w-]+")),
    ("shell_var", re.compile(r"\$\{?[A-Z_][A-Z0-9_]+")),
    (
        "route_label",
        re.compile(
            r"\bLane\s+\d|\bContext\s+[AB]\b|\bPhase\s+\d|"
            r"structure detection|the grid\b|freeform-emit|--mode=",
            re.I,
        ),
    ),
    ("allcaps_token", re.compile(r"\b[A-Z][A-Z0-9]{3,}(?:_[A-Z0-9]+)+\b")),  # SPREADSHEET_STRUCTURE_DETECTION
    ("json_ref", re.compile(r"\b\w+\.json\b")),
    # PLUMBING VERBS — the semantic class the other nine cannot see.
    #
    # Added after it recurred across two skills and survived three prose fixes.
    # Measured instance, which scores ZERO against every class above:
    #   "Slide-by-slide analysis complete. Now gating the hand-off and piping it
    #    through the producer."
    # No backticks, no flag, no .py, no ALLCAPS — pure English about machinery.
    #
    # This is NOT an enumerated blocklist of nouns (the file's own design note
    # explains why that is unwinnable). It targets the VERB+OBJECT construction
    # that only appears when narrating internals: you gate a hand-off, pipe
    # through a producer, dispatch a sub-agent. A founder-facing sentence has no
    # occasion to use these together.
    (
        "plumbing_verb",
        re.compile(
            r"\b(?:gat(?:e|ing|ed)|pip(?:e|ing|ed)|dispatch(?:ing|ed)?|stag(?:e|ing|ed))\b"
            r"[^.\n]{0,40}?"
            r"\b(?:hand-?off|producer|sub-?agent|payload|artifact|extraction|marker)\b"
            r"|\b(?:hand-?off|producer|sub-?agent)\b[^.\n]{0,40}?"
            r"\b(?:gat(?:e|ing|ed)|pip(?:e|ing|ed)|dispatch(?:ing|ed)?)\b",
            re.I,
        ),
    ),
]


def founder_text_blocks(cassette: dict) -> list[str]:
    """Extract the founder-visible assistant text blocks from a cassette."""
    out: list[str] = []
    for raw in cassette.get("events", []):
        try:
            e = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        msg = e.get("message") or (e.get("event") or {}).get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    out.append(b["text"])
    return out


def scan_text(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for name, pat in LEAK_CLASSES:
        for m in pat.finditer(text):
            hits.append((name, m.group(0)))
    return hits


def scan_cassette(path: Path) -> list[tuple[str, str, str]]:
    """Return (leak_class, matched_token, snippet) for every leak in a cassette
    (*.json with an ``events`` list) OR a raw run-dir transcript (``events.jsonl``)."""
    if path.suffix == ".jsonl":
        d: dict = {"events": [ln for ln in path.read_text().splitlines() if ln.strip()]}
    else:
        loaded = json.loads(path.read_text())
        d = loaded if isinstance(loaded, dict) else {"events": [json.dumps(x) for x in loaded]}
    results: list[tuple[str, str, str]] = []
    for block in founder_text_blocks(d):
        for cls, tok in scan_text(block):
            snippet = block.strip().replace("\n", " ")[:90]
            results.append((cls, tok, snippet))
    return results


def _iter_cassettes(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(target.glob("*.cassette.json")) or sorted(target.glob("*.json"))
    return [target]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path, help="cassette file or dir of cassettes")
    ap.add_argument("--show", action="store_true", help="print each leak + snippet")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    args = ap.parse_args()

    per_file: dict[str, int] = {}
    total = 0
    for cass in _iter_cassettes(args.target):
        hits = scan_cassette(cass)
        per_file[cass.name] = len(hits)
        total += len(hits)
        if args.show and hits:
            print(f"\n{cass.name} — {len(hits)} leak(s):")
            for cls, tok, snip in hits[:40]:
                print(f"  [{cls}] {tok!r}  in: {snip!r}")

    if args.json:
        print(json.dumps({"total": total, "per_file": per_file}, indent=2))
    else:
        print(f"\n== base rate: {total} founder-facing leaks across {len(per_file)} cassettes ==")
        for name, n in sorted(per_file.items(), key=lambda kv: -kv[1]):
            if n:
                print(f"  {n:4d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
