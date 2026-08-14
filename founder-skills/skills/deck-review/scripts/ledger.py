#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Validate the numeric ledger a sub-agent extracted from the deck.

The sub-agent does the extraction — reading a chart axis and deciding that "$493K" is
2024 GMV is judgment, and no script can do it. This file does the part that is checkable
against the text the model itself returned, and refuses the ledger when it does not hold.

THE CHECK THAT EARNS ITS PLACE is `raw` against `value`. Every scale-sensitive failure in
this domain looks the same: the model reads "$493K" correctly, writes the quote
correctly, and records `value: 493`. Downstream arithmetic is then flawless and wrong by
a thousand. Because `raw` and `value` are two independent statements about the same
figure, disagreement between them is detectable without ever seeing the deck — which is
what makes it a validation rather than a second opinion.

WHAT THIS IS NOT. It is not the provenance gate. Whether a figure exists in the deck at
all is settled later, in `reconcile.py`, against an INDEPENDENT second reading — checking
a quote against the prompt the model was handed would be checking the model against
itself. Nothing here reads the deck.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _artifact_writer import load_schema, write_artifact  # type: ignore[import-not-found]  # noqa: E402
from reconcile import _NUM_RE, MONEY, _precision, _raw_scale  # type: ignore[import-not-found]  # noqa: E402

UNIT_KINDS = {"money", "count", "percent", "multiple", "duration", "date"}

SCALE_FLOOR = 0.02
"""Minimum relative slack, for a raw string whose own precision claims almost none.

The tolerance is normally derived from `raw`'s significant figures — "$1.2M" claims two
and legitimately covers 1,150,000 to 1,250,000, so a value of 1,238,400 is a correct
extraction of a rounded slide figure and must not be refused. A flat percentage cannot
express that: 2% rejects it, and anything loose enough to accept it stops discriminating.

This floor only catches the case where sig-figs claim implausibly tight precision. It is
never the binding constraint on the failure this check exists for, because a factor of a
thousand does not fit inside any tolerance expressible here.
"""


def _parsed_magnitude(raw: str) -> float | None:
    """What `raw` says the figure is, read independently of `value`."""
    match = _NUM_RE.search(raw or "")
    if not match or not match.group("int"):
        return None
    digits = match.group("int").replace(",", "")
    frac = match.group("frac")
    try:
        magnitude = float(f"{digits}.{frac}") if frac else float(digits)
    except ValueError:
        return None
    return magnitude * _raw_scale(raw)


def validate_ledger(data: dict[str, Any], total_slides: int | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). A non-empty errors list means the ledger is refused."""
    errors: list[str] = []
    warnings: list[str] = []

    figures = data.get("figures")
    if not isinstance(figures, list):
        return ["'figures' must be an array"], warnings

    seen: set[str] = set()
    for index, fig in enumerate(figures):
        where = f"figures[{index}]"
        if not isinstance(fig, dict):
            errors.append(f"{where} must be an object")
            continue

        fig_id = fig.get("id")
        if not isinstance(fig_id, str) or not fig_id.strip():
            errors.append(f"{where} has no id")
        elif fig_id in seen:
            errors.append(f"{where} duplicates id {fig_id!r}; relations address figures by id")
        else:
            seen.add(fig_id)

        value = fig.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{where} value must be a number, got {value!r}")
            value = None

        unit_kind = fig.get("unit_kind")
        if unit_kind not in UNIT_KINDS:
            errors.append(f"{where} unit_kind {unit_kind!r} is not one of {sorted(UNIT_KINDS)}")

        quote = fig.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            errors.append(f"{where} has no quote; the verbatim quote is what the second read checks")

        raw = fig.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"{where} has no raw; without the slide's own string, scale cannot be checked")

        # A money figure with no currency divides fine and compares meaninglessly.
        if unit_kind == MONEY and not fig.get("currency"):
            warnings.append(f"{where} is money with no currency; cross-currency relations will be refused")

        slide = fig.get("slide")
        if slide is None:
            warnings.append(f"{where} names no slide; it will not be covered by the second read")
        elif not isinstance(slide, int) or isinstance(slide, bool):
            errors.append(f"{where} slide must be an integer, got {slide!r}")
        elif slide < 1:
            errors.append(f"{where} slide {slide} is below 1")
        elif total_slides is not None and slide > total_slides:
            errors.append(f"{where} slide {slide} is past the deck's last slide ({total_slides})")

        if value is not None and isinstance(raw, str):
            parsed = _parsed_magnitude(raw)
            if parsed is not None and parsed != 0:
                observed = abs(value)
                # Tolerance from the raw string's OWN significant figures, floored.
                # "$1.2M" claims two figures and covers 1.15M-1.25M; "$1,238,400" claims
                # seven and covers almost nothing. One constant cannot serve both.
                precision = _precision(raw)
                relative = max(precision[0] / precision[1], SCALE_FLOOR) if precision and precision[1] else SCALE_FLOOR
                if observed == 0 or abs(observed - parsed) / parsed > relative:
                    ratio = observed / parsed if parsed else 0
                    errors.append(
                        f"{where} value {value!r} disagrees with raw {raw!r}, which reads as "
                        f"{parsed:,.4g} (ratio {ratio:,.4g}) — record the figure at full scale"
                    )

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a deck's extracted numeric ledger.")
    ap.add_argument("--inventory", help="deck_inventory.json; enables the slide-bounds check")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if sys.stdin.isatty():
        print("Error: pipe the extracted ledger as JSON via stdin", file=sys.stderr)
        return 1
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON input: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        return 1

    total_slides = None
    if args.inventory:
        try:
            with open(args.inventory, encoding="utf-8") as fh:
                inventory = json.load(fh)
            slides = inventory.get("slides")
            if isinstance(slides, list):
                total_slides = len(slides)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error: could not read inventory: {exc}", file=sys.stderr)
            return 1

    errors, warnings = validate_ledger(data, total_slides)

    if errors:
        # Reject loudly and leave `-o` untouched: an invalid-shaped artifact written
        # through `-o` destroys the prior good one and makes SKILL.md's error branch
        # unreachable.
        rejected: dict[str, Any] = {
            "figures": [],
            "validation": {"status": "invalid", "errors": errors, "warnings": warnings},
        }
        print(json.dumps(rejected, indent=2))
        for err in errors:
            print(f"Error: ledger validation failed: {err}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "figures": data["figures"],
        "figures_total": len(data["figures"]),
        "validation": {"status": "valid", "errors": [], "warnings": warnings},
    }

    if args.output:
        schema_path = pathlib.Path(__file__).resolve().parents[1] / "references" / "schemas" / "ledger.schema.json"
        receipt = write_artifact(
            data=result,
            schema=load_schema(str(schema_path)),
            run_id=args.run_id,
            output_path=args.output,
            pretty=True,
        )
        print(json.dumps(receipt, indent=2))
        return 0

    result["metadata"] = {"run_id": args.run_id}
    print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
