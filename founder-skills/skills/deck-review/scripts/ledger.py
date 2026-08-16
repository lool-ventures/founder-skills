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

WHAT THIS IS NOT. It is not the provenance gate. Whether a figure's quote can be re-found
in the deck's slides is settled later, in `reconcile.py`, against a second reading that
never saw the ledger — checking a quote against the prompt the model was handed would be
checking the model against itself. Nothing here reads the deck.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _artifact_writer import load_schema, write_artifact  # type: ignore[import-not-found]  # noqa: E402
from reconcile import _NUM_RE, DATE, MONEY, _precision, _raw_scale  # type: ignore[import-not-found]  # noqa: E402

UNIT_KINDS = {"money", "count", "percent", "multiple", "duration", "date"}

SIGFIG_ONLY = True
"""`value` must agree with `raw` to within RAW'S OWN precision. No relative floor.

There used to be a 2% floor here, applied as a `max()` over the significant-figure
tolerance, and it was the reason a real defect shipped. A live deck recorded
`raw: "16661.2"` with `value: 16661` — extraction silently dropped a decimal — and the
0.0012% discrepancy vanished inside a 2% floor. Downstream that truncation moved a sum
0.54 off its stated total against a tolerance of 0.555, and a founder was told their
revenue disagreed with itself by 1 part in 17,772.

Significant figures alone discriminate correctly on every case the floor was meant to
cover, which is why the floor is gone rather than tuned. Measured:

    raw          value      sigfig tol      gap      verdict
    16661.2      16661        0.0003%   0.0012%     reject   <- the precision loss
    $1.2M      1238400        4.1667%   3.2000%     accept   <- a genuinely rounded figure
    $493K            493      0.1014%  99.9000%     reject   <- the 1000x scale slip
    100               97     50.0000%   3.0000%     accept   <- one sig fig, loose by design

The floor was introduced when this check used a FLAT percentage, which genuinely could not
express "$1.2M legitimately covers 1.15M-1.25M". Switching to significant figures solved
that; keeping the floor afterwards was leftover scaffolding that only ever loosened.
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


def _numeric_tokens(raw: str) -> list[float]:
    """Every number the raw string prints, in the order printed, scale suffixes ignored.

    `_parsed_magnitude` reads the FIRST token and applies a scale to it, which is right
    for a magnitude and wrong for a date: "Q4 2025" reads as 4, so a correctly-extracted
    2025 was rejected as a 506x scale error. A date has no scale — it is one of the
    numbers on the slide — so the date check compares against all of them.
    """
    out: list[float] = []
    for match in _NUM_RE.finditer(raw or ""):
        digits = (match.group("int") or "").replace(",", "")
        if not digits:
            continue
        frac = match.group("frac")
        try:
            out.append(float(f"{digits}.{frac}") if frac else float(digits))
        except ValueError:
            continue
    return out


_BARE_SUFFIX = re.compile(r"\d\s*[kKmMbBtT]\s*$")


def _ambiguous_suffix(raw: str, value: float, unit_kind: object, currency: object) -> bool:
    """Is the trailing letter a UNIT (metres, months) rather than a multiplier?

    Undecidable from the numbers alone, which is the whole point. Measured:

        raw          value        value == mantissa   truth
        200-400m       200              True          metres, correct
        $493K          493              True          1000x scale error
        32.5m          32.5             True          scale error

    So this does not try to decide. It narrows to the shape where the question ARISES --
    a bare k/m/b/t at the end of the raw, on a figure that is not money, whose value
    equals the mantissa -- and swaps in a message that tells the model how to resolve it
    instead of telling it to inflate a building.

    Money is excluded because a currency marker settles it: "$493K" is thousands, always.
    """
    if unit_kind == MONEY or currency:
        return False
    if not _BARE_SUFFIX.search(raw):
        return False
    match = _NUM_RE.search(raw)
    if not match or not match.group("int"):
        return False
    mantissa = float(match.group("int").replace(",", ""))
    if match.group("frac"):
        mantissa += float("0." + match.group("frac"))
    return abs(abs(value) - mantissa) <= max(abs(mantissa) * 1e-9, 1e-9)


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

        if value is not None and isinstance(raw, str) and unit_kind == DATE:
            # A DATE IS NOT A MAGNITUDE WITH A SCALE, and the check below assumes it is.
            # It reads the first numeric token and applies a scale rule to it, so "Q4 2025"
            # recorded as 2025 — the correct extraction — was refused as a 506x error, while
            # "2024-2030" recorded as its later endpoint was refused as a 1.003x one.
            #
            # The rule that fits a date is token equality: the value has to be a number the
            # slide actually prints. That still catches the two classes this check exists
            # for — a fabricated year, and the 10x slip ("2024" recorded as 20240) — without
            # a scale rule a date has no use for.
            #
            # BOTH readings of "Q4 2025" are admitted, the quarter and the year, on the
            # strength of the figure's label. That would be an ambiguity if anything
            # computed with dates: `Q4 − Q2` would yield "2 years". Nothing does —
            # `reconcile.py` refuses every relation with a date participant, operands and
            # stated side alike — so the ambiguity is unreachable, and neither restricting
            # dates to four-digit years nor adding a self-attested resolution field buys
            # anything here. If date arithmetic is ever un-refused, this is the second place
            # to revisit.
            tokens = _numeric_tokens(raw)
            if tokens and not any(abs(abs(value) - token) < 1e-9 for token in tokens):
                printed = ", ".join(f"{token:g}" for token in tokens)
                errors.append(
                    f"{where} value {value!r} is not one of the numbers raw {raw!r} prints "
                    f"({printed}) — a date must be a number stated on the slide"
                )
        elif value is not None and isinstance(raw, str):
            parsed = _parsed_magnitude(raw)
            if parsed is not None and parsed != 0:
                observed = abs(value)
                # Tolerance from the raw string's OWN significant figures, floored.
                # "$1.2M" claims two figures and covers 1.15M-1.25M; "$1,238,400" claims
                # seven and covers almost nothing. One constant cannot serve both.
                # `raw`'s own precision, and nothing looser. A figure printed to six
                # significant figures is a claim to six significant figures.
                precision = _precision(raw)
                relative = (precision[0] / precision[1]) if precision and precision[1] else 0.0
                if observed == 0 or abs(observed - parsed) / parsed > relative:
                    ratio = observed / parsed if parsed else 0
                    if _ambiguous_suffix(raw, value, unit_kind, fig.get("currency")):
                        # NOT a scale error, and the usual advice would make it one. A real
                        # deck stated tower heights as "200-400m" and the model recorded 200
                        # with a label saying "(metres)" -- correct, and "record at full
                        # scale" would have pushed it to 200,000,000.
                        #
                        # The code cannot resolve this: "32.5m businesses" recorded as 32.5
                        # (a genuine scale error) is structurally IDENTICAL to "200-400m"
                        # metres recorded as 200. `value == mantissa` holds for both. The
                        # disambiguating fact lives on the slide, so the model has to state
                        # it -- and the existing word-boundary guard already reads the
                        # spelled-out form correctly ("200-400 metres" -> 200). Note a bare
                        # space does NOT help: "200-400 m" still parses as millions.
                        errors.append(
                            f"{where} raw {raw!r} is ambiguous: the trailing suffix reads as a "
                            f"multiplier ({parsed:,.4g}) but value is {value!r}. If the suffix is a "
                            f"UNIT rather than a multiplier, spell it out in raw (e.g. "
                            f"'200-400 metres', '18 months'); if it is a multiplier, record value "
                            f"at full scale"
                        )
                    else:
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
