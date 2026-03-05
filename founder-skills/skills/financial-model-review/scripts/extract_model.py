#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl"]
# ///
"""Extract structured data from Excel (.xlsx) or CSV files.

Usage:
    python extract_model.py --file model.xlsx --pretty
    python extract_model.py --file data.csv -o model_data.json
    echo '{"sheets": [...]}' | python extract_model.py --stdin

Output: JSON with structure:
    {"sheets": [{"name": str, "headers": [str], "rows": [[value]], "detected_type": str|null}]}
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from typing import Any


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {abs_path}", file=sys.stderr)
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


# Tab name heuristics for detecting sheet purpose
_TAB_PATTERNS: dict[str, list[str]] = {
    "assumptions": ["assumption", "input", "driver", "parameter"],
    "revenue": ["revenue", "sales", "arr", "mrr", "income"],
    "expenses": ["expense", "opex", "cost", "headcount", "hiring", "payroll"],
    "cash": ["cash", "runway", "burn", "balance"],
    "pnl": ["p&l", "pnl", "profit", "loss", "income statement"],
    "summary": ["summary", "dashboard", "overview", "kpi"],
    "scenarios": ["scenario", "sensitivity", "case"],
}


def _detect_tab_type(name: str) -> str | None:
    lower = name.lower().strip()
    for tab_type, patterns in _TAB_PATTERNS.items():
        for pat in patterns:
            if pat in lower:
                return tab_type
    return None


def _safe_value(val: Any) -> Any:
    """Convert cell value to JSON-serializable type."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool)):
        return val
    return str(val)


# ---------------------------------------------------------------------------
# Periodicity detection
# ---------------------------------------------------------------------------

# Month-range patterns MUST be checked before single-month to avoid
# misclassifying "Jan-Mar" as monthly.
_MONTH_NAMES = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_QUARTERLY_PATTERNS: list[re.Pattern[str]] = [
    # Q1 2024, Q1-24, Q1 - 24, Q1'24
    re.compile(r"\bQ[1-4]\b", re.IGNORECASE),
    # 1Q24, 1Q2024
    re.compile(r"\b[1-4]Q\d{2,4}\b", re.IGNORECASE),
    # Jan-Mar 2024, January-March, Jan-Mar
    re.compile(
        rf"\b({_MONTH_NAMES})\s*[-–]\s*({_MONTH_NAMES})\b",
        re.IGNORECASE,
    ),
]

_ANNUAL_PATTERNS: list[re.Pattern[str]] = [
    # FY2024, FY24, FY 2024
    re.compile(r"\bFY\s*\d{2,4}\b", re.IGNORECASE),
    # H1 2024, H2, 1H24, 2H24
    re.compile(r"\b[12]H\d{2,4}\b|\bH[12]\b", re.IGNORECASE),
]

_MONTHLY_PATTERNS: list[re.Pattern[str]] = [
    # Jan 2024, January 24, Jan-24, Jan '24
    re.compile(
        rf"\b({_MONTH_NAMES})\s*[-–'/]?\s*\d{{2,4}}\b",
        re.IGNORECASE,
    ),
    # 2024-01, 2024-01-01
    re.compile(r"\b20\d{2}-(?:0[1-9]|1[0-2])\b"),
]


def _classify_header(header: str) -> str | None:
    """Classify a single column header as monthly/quarterly/annual or None."""
    # Check quarterly first (month-range before single-month)
    for pat in _QUARTERLY_PATTERNS:
        if pat.search(header):
            return "quarterly"
    for pat in _ANNUAL_PATTERNS:
        if pat.search(header):
            return "annual"
    for pat in _MONTHLY_PATTERNS:
        if pat.search(header):
            return "monthly"
    return None


def detect_periodicity(headers: list[str]) -> str:
    """Detect periodicity from column headers via majority vote.

    Skips the first column (typically row labels). Returns one of:
    monthly, quarterly, annual, unknown.
    """
    classifications: list[str] = []
    for h in headers[1:]:  # skip first column (row labels)
        c = _classify_header(h)
        if c is not None:
            classifications.append(c)

    if not classifications:
        return "unknown"

    # Majority vote
    from collections import Counter

    counts = Counter(classifications)
    winner, _ = counts.most_common(1)[0]
    return winner


def _periodicity_summary(sheets: list[dict[str, Any]]) -> str:
    """Compute top-level periodicity summary from per-sheet values."""
    values: set[str] = {s["periodicity"] for s in sheets if s.get("periodicity") != "unknown"}
    if not values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def extract_xlsx(file_path: str) -> dict[str, Any]:
    """Extract data from an Excel file."""
    try:
        from openpyxl import load_workbook  # type: ignore[import-untyped]
    except ImportError:
        print(
            "Error: openpyxl is required for .xlsx files. Install with: pip install openpyxl",
            file=sys.stderr,
        )
        sys.exit(1)

    wb = load_workbook(file_path, data_only=True, read_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows_data: list[list[Any]] = []
        headers: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            row_vals = [_safe_value(c) for c in row]
            if i == 0:
                headers = [str(v) if v is not None else f"col_{j}" for j, v in enumerate(row)]
            else:
                rows_data.append(row_vals)
        sheets.append(
            {
                "name": ws.title,
                "headers": headers,
                "rows": rows_data,
                "detected_type": _detect_tab_type(ws.title),
                "periodicity": detect_periodicity(headers),
                "row_count": len(rows_data),
                "col_count": len(headers),
            }
        )
    wb.close()
    return {
        "sheets": sheets,
        "source_format": "xlsx",
        "source_file": os.path.basename(file_path),
        "periodicity_summary": _periodicity_summary(sheets),
    }


def extract_csv(file_path: str) -> dict[str, Any]:
    """Extract data from a CSV file."""
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows_raw = list(reader)

    if not rows_raw:
        empty_sheets: list[dict[str, Any]] = [
            {
                "name": "Sheet1",
                "headers": [],
                "rows": [],
                "detected_type": None,
                "periodicity": "unknown",
                "row_count": 0,
                "col_count": 0,
            }
        ]
        return {
            "sheets": empty_sheets,
            "source_format": "csv",
            "source_file": os.path.basename(file_path),
            "periodicity_summary": "unknown",
        }

    headers = rows_raw[0]
    rows_data = []
    for row in rows_raw[1:]:
        row_vals: list[Any] = []
        for v in row:
            # Try to coerce to number
            try:
                row_vals.append(int(v))
            except ValueError:
                try:
                    row_vals.append(float(v))
                except ValueError:
                    row_vals.append(v if v else None)
        rows_data.append(row_vals)

    name = os.path.splitext(os.path.basename(file_path))[0]
    csv_sheets = [
        {
            "name": name,
            "headers": headers,
            "rows": rows_data,
            "detected_type": _detect_tab_type(name),
            "periodicity": detect_periodicity(headers),
            "row_count": len(rows_data),
            "col_count": len(headers),
        }
    ]
    return {
        "sheets": csv_sheets,
        "source_format": "csv",
        "source_file": os.path.basename(file_path),
        "periodicity_summary": _periodicity_summary(csv_sheets),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract structured data from financial model files")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Path to .xlsx or .csv file")
    group.add_argument("--stdin", action="store_true", help="Read pre-structured JSON from stdin")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    p.add_argument("-o", "--output", help="Write output to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.stdin:
        if sys.stdin.isatty():
            print("Error: --stdin requires piped input", file=sys.stderr)
            sys.exit(1)
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON on stdin: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        file_path = args.file
        if not os.path.isfile(file_path):
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            sys.exit(1)

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".xlsx":
            data = extract_xlsx(file_path)
        elif ext == ".csv":
            data = extract_csv(file_path)
        else:
            print(f"Error: unsupported file type '{ext}' (expected .xlsx or .csv)", file=sys.stderr)
            sys.exit(1)

    indent = 2 if args.pretty else None
    out = json.dumps(data, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"sheets": len(data.get("sheets", []))},
    )


if __name__ == "__main__":
    main()
