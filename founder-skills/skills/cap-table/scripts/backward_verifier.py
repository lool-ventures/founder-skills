#!/usr/bin/env python3
"""Backward verification for cap-table Lane-1 extraction.

Forward verification (`evidence_verifier.py`) catches the
HALLUCINATION class: model invents a value not present in source.

Backward verification (this script) catches a DIFFERENT class:
SEMANTIC CONFUSION. The model read the source and pulled a real value,
but pulled the wrong one — e.g., extracted the cap from a referenced
prior SAFE instead of the current SAFE, or confused 'Purchase Amount'
with 'Aggregate Purchase Amount of all Safes'. Forward verification
passes (the value IS in the source) but the value is semantically wrong.

Mechanism:
  1. After forward verification passes, this script emits a structured
     RE-EXTRACTION PROMPT for each high-stakes field — a prompt that asks
     a FRESH sub-agent (no priors from the original extraction) to extract
     that ONE field from the source.
  2. The dispatching agent runs the prompts via Task tool.
  3. This script then SCORES the responses: does the re-extraction agree
     with the original? Numeric tolerance + date format variance applied.
  4. Disagreements are surfaced via a structured report. WARN-mode default
     (informational) — calibration found disagreement rates noisy enough
     that auto-rejection would over-reject.

Two-phase CLI:
  --phase=prompt    Emit re-extraction prompts to stdout (one JSON per line)
  --phase=score     Read responses from stdin; score; emit verification report

Field-conditional gating: only high-stakes scalar fields get re-extracted
(numeric, date, name). Synthesized enums (form, jurisdiction) and composite
fields (mfn_provision) are skipped — they're not meaningful to re-extract.

Stage-conditional gating: caller decides when to invoke. Recommended pattern
is "after forward verification passes" (the rejection retry-hint contract
in extract_instrument.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evidence_verifier import (  # noqa: E402
    _date_tokens,
    compact_form,
)

# Field-conditional gating: only re-extract these high-stakes scalar fields.
# Skips synthesized enums (form, jurisdiction, doc_type), composite types
# (mfn_provision), derived counts (options_granted_count), and list fields
# (share_classes, preferred_series) — those aren't meaningful to re-extract
# field-by-field.
SAFE_BACKWARD_FIELDS = [
    "purchase_amount",
    "post_money_valuation_cap",
    "pre_money_valuation_cap",
    "discount_multiplier",
    "issuance_date",
    "investor_name",
]
NOTE_BACKWARD_FIELDS = [
    "principal",
    "annual_interest_rate",
    "valuation_cap",
    "discount_multiplier",
    "qualified_financing_threshold",
    "issuance_date",
    "maturity_date",
    "investor_name",
]
TERM_SHEET_BACKWARD_FIELDS = [
    "pre_money_valuation",
    "post_money_valuation",
    "investment_amount",
    "discount_multiplier",
    "company_name",
    "lead_investor_name",
]

FIELDS_BY_INSTRUMENT_TYPE = {
    "safe": SAFE_BACKWARD_FIELDS,
    "convertible_note": NOTE_BACKWARD_FIELDS,
    "term_sheet": TERM_SHEET_BACKWARD_FIELDS,
}


# Field-specific re-extraction prompt templates. Each is a focused, single-
# field question — no schema context, no Gotcha rules — to keep the sub-agent
# minimally primed. We're asking "what is this value in this document?" not
# "extract everything." Keeps the re-extraction independent of the prompt
# that produced the original.
FIELD_PROMPT_TEMPLATES = {
    "purchase_amount": (
        "What is the EXACT 'Purchase Amount' (also called 'Investment Amount' "
        "or the principal dollar amount being invested under THIS specific "
        'SAFE)? Return ONLY a JSON object: {"value": <number_in_USD or null>, '
        '"evidence_quote": "<verbatim_phrase>"}. If the document refers to '
        "an 'Aggregate Purchase Amount of all Safes' or similar, return the "
        "amount FOR THIS SAFE only, not the aggregate."
    ),
    "post_money_valuation_cap": (
        "What is the EXACT 'Post-Money Valuation Cap' in this SAFE? Return "
        'ONLY {"value": <number_in_USD or null>, "evidence_quote": '
        '"<verbatim>"}. Only return a value if the document explicitly uses '
        "POST-MONEY terminology. If the document only says 'Valuation Cap' "
        "without the 'Post-Money' prefix, return null."
    ),
    "pre_money_valuation_cap": (
        "What is the EXACT 'Valuation Cap' in this PRE-MONEY SAFE? Return "
        'ONLY {"value": <number_in_USD or null>, "evidence_quote": '
        '"<verbatim>"}. Only return a value if the SAFE is the legacy YC '
        "pre-money form (header says 'Valuation Cap' not 'Post-Money "
        "Valuation Cap', or vocab uses 'Safe Capital Stock')."
    ),
    "discount_multiplier": (
        "What is the discount multiplier in this document? Return ONLY "
        '{"value": <decimal_0_to_1 or null>, "evidence_quote": "<verbatim>"}. '
        "CRITICAL — Gotcha #3 trap: if doc says 'Discount Rate is X%' or "
        "'Discounted Price Percentage is X%' where X >= 50, X is the "
        "MULTIPLIER (investor pays X%, so discount = 100-X%) — return X/100. "
        "If doc says 'discount of X%' where X < 50, X is the RATE — return "
        "1 - X/100. When doc says '(i.e., Y% discount)', use that."
    ),
    "annual_interest_rate": (
        "What is the annual interest rate in this convertible? Return ONLY "
        '{"value": <decimal_0_to_1 or null>, "evidence_quote": "<verbatim>"}. '
        "Return null IF the rate is set by Section 3(j) of the Israeli Income "
        "Tax Regulations (ITA statutory rate — non-numeric) OR if the "
        "instrument has no interest at all (SAFE-like convertible securities)."
    ),
    "valuation_cap": (
        "What is the 'Valuation Cap' or 'Conversion Cap' in this convertible? "
        'Return ONLY {"value": <number_in_USD or null>, "evidence_quote": '
        '"<verbatim>"}. If the doc has no cap, return null.'
    ),
    "principal": (
        "What is the principal amount of this convertible note / CLA / "
        'convertible security? Return ONLY {"value": <number_in_USD or null>, '
        '"evidence_quote": "<verbatim>"}. Return the principal for THIS note '
        "only, not aggregate amounts across multiple notes."
    ),
    "qualified_financing_threshold": (
        "What is the minimum equity-financing size that triggers conversion "
        "of this note (often called 'Qualified Financing' or 'Equity "
        'Financing threshold")? Return ONLY {"value": <number_in_USD or null>, '
        '"evidence_quote": "<verbatim>"}.'
    ),
    "issuance_date": (
        "What is the issuance / effective / 'as of' date of this instrument? "
        'Return ONLY {"value": "YYYY-MM-DD" or null, "evidence_quote": '
        '"<verbatim>"}. If the date is left as a template blank (e.g. '
        "'_______, 20___' or '____, 2024'), return null."
    ),
    "maturity_date": (
        "What is the maturity date of this convertible note / CLA? Return "
        'ONLY {"value": "YYYY-MM-DD" or null, "evidence_quote": "<verbatim>"}. '
        "If only a duration is stated (e.g. '24 months from issuance'), "
        "compute the date if issuance date is known; otherwise return null."
    ),
    "investor_name": (
        "Who is the investor / lender / purchaser in this instrument? Return "
        'ONLY {"value": "<exact_legal_name or null>", "evidence_quote": '
        '"<verbatim>"}. If multiple investors via Exhibit A or schedule, '
        "return 'multiple per Exhibit A'."
    ),
    "lead_investor_name": (
        'Who is the lead investor in this term sheet? Return ONLY {"value": "<name>", "evidence_quote": "<verbatim>"}.'
    ),
    "company_name": (
        "What is the exact legal name of the company in this document? Return "
        'ONLY {"value": "<exact_legal_name>", "evidence_quote": "<verbatim>"}.'
    ),
    "pre_money_valuation": (
        "What is the PRE-MONEY VALUATION (not the cap) in this term sheet? "
        'Return ONLY {"value": <number_in_USD or null>, "evidence_quote": '
        '"<verbatim>"}.'
    ),
    "post_money_valuation": (
        "What is the POST-MONEY VALUATION in this term sheet? Return ONLY "
        '{"value": <number_in_USD or null>, "evidence_quote": "<verbatim>"}.'
    ),
    "investment_amount": (
        "What is the total INVESTMENT AMOUNT in this term sheet? Return ONLY "
        '{"value": <number_in_USD or null>, "evidence_quote": "<verbatim>"}.'
    ),
}


@dataclass
class FieldBackwardResult:
    field_name: str
    original_value: Any
    reextracted_value: Any
    agreement: str  # "match" | "mismatch" | "skipped" | "both_null"
    reason: str = ""
    fuzzy_match: bool = False


@dataclass
class BackwardReport:
    overall_status: str  # "pass" | "fail" | "skipped" | "unverifiable"
    n_fields: int
    n_matched: int
    n_mismatched: int
    n_skipped: int
    per_field: list[FieldBackwardResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _select_fields(instrument_type: str, fields: dict[str, Any]) -> list[str]:
    """Field-conditional gating: pick fields that are (a) high-stakes for the
    instrument type, (b) populated in the original extraction, (c) have a
    re-extraction prompt template defined."""
    candidate = FIELDS_BY_INSTRUMENT_TYPE.get(instrument_type, [])
    selected = []
    for fname in candidate:
        if fname not in FIELD_PROMPT_TEMPLATES:
            continue
        # Only re-extract if the original has a non-null value worth checking
        v = fields.get(fname)
        if v is None:
            continue
        selected.append(fname)
    return selected


def emit_prompts(extraction: dict[str, Any], source_doc_path: str) -> list[dict[str, Any]]:
    """Build re-extraction prompts. Returns a list of {field, prompt} dicts.

    The caller (cap-table SKILL.md / dispatch) is expected to:
      1. Read this stdout
      2. For each prompt, spawn a fresh Task sub-agent with the prompt body
      3. Collect responses
      4. Pipe them back to this script in --phase=score mode
    """
    instrument_type = extraction.get("instrument_type", "")
    fields = extraction.get("fields") or {}
    selected = _select_fields(instrument_type, fields)

    prompts = []
    for fname in selected:
        original = fields.get(fname)
        template = FIELD_PROMPT_TEMPLATES[fname]
        prompt_body = (
            f"# Backward verification — re-extract field `{fname}`\n\n"
            f"You are doing INDEPENDENT re-extraction of one field from a legal\n"
            f"document. DO NOT base your answer on any prior extraction — read\n"
            f"the document fresh and pull the value yourself.\n\n"
            f"## Source document\n\n"
            f"Path: `{source_doc_path}` — use the Read tool to read it.\n\n"
            f"## Field to extract\n\n"
            f"{template}\n\n"
            f"## Output\n\n"
            f"Return EXACTLY ONE JSON object on a single line — no prose, no\n"
            f"code fences, no commentary:\n"
            f'  {{"field": "{fname}", "value": <value or null>, "evidence_quote": "<verbatim>"}}\n'
        )
        prompts.append(
            {
                "field": fname,
                "original_value": original,
                "prompt": prompt_body,
            }
        )
    return prompts


def _values_agree(field_name: str, a: Any, b: Any) -> tuple[bool, str]:
    """Compare an original extraction value with a re-extracted value, with
    tolerance for date format variance and numeric representation differences.
    """
    if a is None and b is None:
        return True, "both_null"
    if a is None or b is None:
        return False, f"null_mismatch (orig={a!r}, reex={b!r})"

    # Numeric: int/float
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # Allow small float epsilon (precision drift)
        if isinstance(a, float) or isinstance(b, float):
            if abs(float(a) - float(b)) <= 1e-6:
                return True, "float_match"
            # 1% relative tolerance for amounts
            if abs(a) > 0 and abs(float(a) - float(b)) / abs(a) < 0.01:
                return True, "float_relative_match"
            return False, f"numeric_mismatch ({a} vs {b})"
        # int-int strict equality
        if a == b:
            return True, "int_match"
        return False, f"numeric_mismatch ({a} vs {b})"

    # Strings (including dates as YYYY-MM-DD strings)
    if isinstance(a, str) and isinstance(b, str):
        an, bn = a.strip().lower(), b.strip().lower()
        if an == bn:
            return True, "string_match"
        # Date — try date_tokens overlap (any common representation)
        if a[:4].isdigit() and "-" in a:
            a_tokens = {t.lower() for t in _date_tokens(a)}
            b_tokens = {t.lower() for t in _date_tokens(b)}
            if a_tokens & b_tokens:
                return True, "date_format_match"
        # Compact form (strip punctuation)
        if compact_form(a) == compact_form(b):
            return True, "compact_match"
        # Bidirectional substring (one is a prefix/suffix/contained in the other)
        if an in bn or bn in an:
            return True, "substring_match"
        return False, f"string_mismatch ({a!r} vs {b!r})"

    # Mixed type — try string conversion
    if str(a).lower() == str(b).lower():
        return True, "stringified_match"
    return False, f"type_mismatch ({type(a).__name__} vs {type(b).__name__})"


def score_responses(extraction: dict[str, Any], responses: list[dict[str, Any]]) -> BackwardReport:
    """Score re-extraction responses against the original extraction.

    responses: list of {field, value, evidence_quote} from sub-agents.
    """
    fields = extraction.get("fields") or {}
    response_by_field = {r["field"]: r for r in responses if "field" in r}

    instrument_type = extraction.get("instrument_type", "")
    expected = _select_fields(instrument_type, fields)

    report = BackwardReport(overall_status="pending", n_fields=0, n_matched=0, n_mismatched=0, n_skipped=0)

    for fname in expected:
        original = fields.get(fname)
        resp = response_by_field.get(fname)
        if resp is None:
            report.per_field.append(
                FieldBackwardResult(
                    field_name=fname,
                    original_value=original,
                    reextracted_value=None,
                    agreement="skipped",
                    reason="no_response_received",
                )
            )
            report.n_skipped += 1
            report.n_fields += 1
            continue

        reextracted = resp.get("value")
        ok, why = _values_agree(fname, original, reextracted)
        report.per_field.append(
            FieldBackwardResult(
                field_name=fname,
                original_value=original,
                reextracted_value=reextracted,
                agreement="match" if ok else "mismatch",
                reason=why,
            )
        )
        report.n_fields += 1
        if ok:
            report.n_matched += 1
        else:
            report.n_mismatched += 1

    if report.n_fields == 0:
        report.overall_status = "skipped"
    elif report.n_mismatched == 0:
        report.overall_status = "pass"
    else:
        report.overall_status = "fail"

    return report


def report_to_dict(report: BackwardReport) -> dict[str, Any]:
    return {
        "overall_status": report.overall_status,
        "n_fields": report.n_fields,
        "n_matched": report.n_matched,
        "n_mismatched": report.n_mismatched,
        "n_skipped": report.n_skipped,
        "metadata": report.metadata,
        "per_field": [
            {
                "field": r.field_name,
                "original_value": r.original_value,
                "reextracted_value": r.reextracted_value,
                "agreement": r.agreement,
                "reason": r.reason,
            }
            for r in report.per_field
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prompt", "score"), required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--source-doc", type=str, help="Path to source doc; used in prompt body")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    extraction = json.loads(args.extraction.read_text())

    if args.phase == "prompt":
        if not args.source_doc:
            sys.stderr.write("backward_verifier.py: --phase=prompt requires --source-doc\n")
            return 2
        prompts = emit_prompts(extraction, args.source_doc)
        out = {"n_prompts": len(prompts), "prompts": prompts}
        if args.output:
            args.output.write_text(json.dumps(out, indent=2 if args.pretty else None))
        else:
            print(json.dumps(out, indent=2 if args.pretty else None))
        return 0

    # phase == "score"
    raw = sys.stdin.read().strip()
    if not raw:
        sys.stderr.write("backward_verifier.py: --phase=score expects responses JSON on stdin\n")
        return 2
    payload = json.loads(raw)
    # Accept either a list of responses or {responses: [...]}
    responses = payload.get("responses", []) if isinstance(payload, dict) else payload

    report = score_responses(extraction, responses)
    out = report_to_dict(report)
    if args.output:
        args.output.write_text(json.dumps(out, indent=2 if args.pretty else None))
    else:
        print(json.dumps(out, indent=2 if args.pretty else None))

    # Exit code mirrors verifier semantics
    if report.overall_status == "pass":
        return 0
    if report.overall_status == "fail":
        return 1
    return 2  # skipped / unverifiable


if __name__ == "__main__":
    sys.exit(main())
