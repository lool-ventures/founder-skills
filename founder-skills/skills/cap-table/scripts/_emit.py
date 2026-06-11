"""Shared CLI output helper for cap-table math producers.

Implements the repo-wide script convention: ``--pretty`` for human-readable
output and ``-o <file>`` to write the JSON payload to a file and emit a JSON
receipt to stdout confirming the write.

Use ``add_output_args(parser)`` to register the flags, then ``emit(result,
args)`` to dispatch output.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any


def add_output_args(parser: argparse.ArgumentParser) -> None:
    """Register ``--pretty`` and ``-o/--output`` on a parser."""
    parser.add_argument("--pretty", action="store_true", help="Human-readable (indented) JSON output")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Write JSON payload to this file; emit a receipt to stdout",
    )


def emit(result: Any, args: argparse.Namespace, *, default: Any = None) -> None:
    """Print ``result`` to stdout, or write it to ``args.output`` and print a receipt.

    Honors ``args.pretty`` for indentation on both the payload and the receipt.
    ``default`` is forwarded to ``json.dump``/``json.dumps`` (e.g. ``str`` for
    payloads carrying ``date`` objects).
    """
    indent = 2 if getattr(args, "pretty", False) else None
    output = getattr(args, "output", None)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=indent, default=default)
        receipt = {"ok": True, "output": os.path.abspath(output)}
        print(json.dumps(receipt, indent=indent))
    else:
        print(json.dumps(result, indent=indent, default=default))
