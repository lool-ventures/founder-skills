#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Wrap a raw coaching-commentary markdown file in the transport envelope.

The sub-agent writes the coaching commentary as plain markdown (native
Write tool, no escaping). This adapter reads that file verbatim (arg or
stdin) and prints `{"commentary_markdown": "<text>"}` to stdout --
json.dumps performs the escaping, so the envelope is correct by
construction. Pipe the output into the UNCHANGED insert_coaching.py:

    python3 md_to_commentary.py coaching.md | python3 insert_coaching.py ...

Run check_handoff.py --format=markdown on coaching.md BEFORE this script;
this adapter does no validation of its own.
"""

from __future__ import annotations

import argparse
import json
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wrap a raw markdown file as a commentary_markdown envelope")
    p.add_argument(
        "path",
        nargs="?",
        help="Path to the raw markdown file (omit to read stdin)",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Indent the output (default is compact single-line -- this is a machine pipe stage)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.path:
        with open(args.path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps({"commentary_markdown": text}, indent=indent) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
