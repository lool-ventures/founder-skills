#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfplumber", "python-docx", "openpyxl"]
# ///
"""Anti-hallucination validator for Lane-1 instrument extraction.

The Context A sub-agent does the actual extraction from PDF/DOCX. This
script validates the returned JSON, enforces form-dependent required-field
gates (per SKILL.md §5.1), surfaces ambiguities for AskUserQuestion, and
appends the validated instrument into instruments.json.

Per Gotcha #3: this script also normalizes discount values to the canonical
multiplier form. A value >= 50 is read as a percent-multiplier (80 → 0.80 =
20% discount); a value in (1, 50) is read as a discount-rate percent (20 →
0.80 multiplier); a value in (0, 1] passes through as an already-canonical
multiplier; <= 0 is rejected. See normalize_discount_multiplier.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402
from cross_checker import cross_check as _cross_check  # noqa: E402
from evidence_verifier import (  # noqa: E402
    MissingDependencyError,  # noqa: E402
    report_to_dict,
    verify_extraction,
)
from evidence_verifier import _load_doc_text as _ev_load_doc_text  # noqa: E402
from extractors import ExtractionContext as _ExtractionContext  # noqa: E402
from invariant_checker import check_instrument as _invariant_check  # noqa: E402
from invariant_checker import report_to_dict as _invariant_report_to_dict  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)


# Per SKILL.md §5.1: form-dependent required-field gates.
#
# Pre-money forms (yc_premoney_cap_only, pre_money_cap_and_discount_legacy)
# cover legacy YC SAFEs that pre-date the 2018 post-money template revision.
# Eval-set labeling found multiple real SAFEs across 2017–2025 vintages still
# using the legacy pre-money form (header reads bare "Valuation Cap" without
# "Post-Money" prefix; Company Capitalization formula INCLUDES future option
# pool grants). `pre_money_cap_and_discount_legacy` is the cap-plus-discount
# variant; `yc_premoney_cap_only` is its peer for cap-only.
SAFE_FORM_GATES: dict[str, dict[str, Any]] = {
    "yc_postmoney_cap": {
        "required_non_null": ["post_money_valuation_cap"],
        "must_be_null": ["discount_multiplier", "pre_money_valuation_cap"],
    },
    "yc_postmoney_discount": {
        "required_non_null": ["discount_multiplier"],
        "must_be_null": ["post_money_valuation_cap", "pre_money_valuation_cap"],
    },
    "yc_uncapped_mfn": {
        "required_non_null": [],
        "must_be_null": ["post_money_valuation_cap", "pre_money_valuation_cap", "discount_multiplier"],
        "must_have_mfn": True,
    },
    "cap_plus_discount": {
        "required_non_null": ["post_money_valuation_cap", "discount_multiplier"],
        "must_be_null": ["pre_money_valuation_cap"],
    },
    "yc_premoney_cap_only": {
        # Legacy YC pre-money SAFE with cap only (no discount).
        # Discriminator: header says "VALUATION CAP" (not "POST-MONEY"), uses
        # "Safe Capital Stock" terminology, Company Capitalization formula
        # INCLUDES the future option pool grants.
        "required_non_null": ["pre_money_valuation_cap"],
        "must_be_null": ["post_money_valuation_cap", "discount_multiplier"],
    },
    "pre_money_cap_and_discount_legacy": {
        # Legacy YC pre-money SAFE with both cap and discount. Same discriminator
        # as yc_premoney_cap_only plus a Discount Rate clause.
        "required_non_null": ["pre_money_valuation_cap", "discount_multiplier"],
        "must_be_null": ["post_money_valuation_cap"],
    },
    "other": {
        "required_non_null": [],
        "must_be_null": [],
    },
}

# Valid values for convertible note interest_rate_type. Determines whether
# annual_interest_rate is required.
# - fixed_numeric / fixed_numeric_simple: numeric rate required
# - statutory_ita_section_3j: Israeli ITA Section 3(j) statutory rate; numeric value
#   is null because rate is set annually by Israeli Tax Authority
# - none: SAFE-equivalent convertible securities — no interest at all
INTEREST_RATE_TYPES_REQUIRING_NUMERIC = {"fixed_numeric", "fixed_numeric_simple"}
INTEREST_RATE_TYPES_ALLOWING_NULL = {"statutory_ita_section_3j", "none"}
INTEREST_RATE_TYPES_ALL = INTEREST_RATE_TYPES_REQUIRING_NUMERIC | INTEREST_RATE_TYPES_ALLOWING_NULL

# Non-extractable doc types: classified + surfaced, never forced through the SAFE/note gate and
# (for non_instrument / amendment) never persisted to a math array. `warrant` is persisted to
# warrants[] separately. An `amendment` restates one clause of an existing instrument and leaves
# every other term legitimately absent, so it must not land as an all-null note in convertible_notes.
# Single source of truth so the routing / classified / verify-skip / invariants-skip sets can't drift.
NON_EXTRACTABLE_ITYPES = {"warrant", "non_instrument", "amendment"}
# Terms docs (term_sheet / option_plan): no strict field schema and no math-consumable shape. Their
# content is persisted to the RECEIPT (never a math array) and display-rendered by the extraction-only
# renderer via --audit. Verifier / invariant FINDINGS surface as per-field markers + attention_needed
# entries, never a block; input-integrity errors (missing source doc, bad JSON, schema-write) still
# fail loud.
TERMS_DOC_ITYPES = frozenset({"term_sheet", "option_plan"})

# Relaxable-absence sets: a required field that is missing WITH confidence.level == "absent" is a
# warning (the instrument persists as a partial), not a hard error — but ONLY for these fields, per
# instrument type. Everything else stays strict: the per-form required_non_null cap gate, must_be_null,
# the interest_rate_type enum, must_have_mfn, the Gotcha-#5 branch check, and day_count_basis /
# annual_interest_rate (the note math filter / day_count coalesce handle those nulls, so they are not
# relaxed at the validation gate). Every relaxable MATH-CONSUMED field here must be covered by a math
# usable-predicate (test_relaxable_note_fields_covered_by_usable_predicate enforces this).
SAFE_RELAXABLE_ABSENT_FIELDS = frozenset({"purchase_amount", "issuance_date", "investor_name"})
NOTE_RELAXABLE_ABSENT_FIELDS = frozenset(
    {"principal", "issuance_date", "investor_name", "maturity_date", "maturity_default_treatment"}
)
# A warrant whose share count is confirmed but whose strike is genuinely not stated persists as a
# partial (exercise_price documented-absent) instead of being dropped from fully-diluted math. The
# math usable-predicate (warrant_exercise.warrant_has_usable_exercise_price) must cover every
# math-consumed field here (test_relaxable_warrant_fields_covered_by_usable_predicate enforces this).
WARRANT_RELAXABLE_ABSENT_FIELDS = frozenset({"exercise_price"})


def normalize_discount_multiplier(d: float | None) -> tuple[float | None, str | None]:
    """Normalize a discount input to the canonical multiplier form (Gotcha #3).

    The canonical field stores the MULTIPLIER (0.80 = a 20% discount). YC SAFEs
    phrase the "Discount Rate" as the multiplier itself (e.g. "Discount Rate is
    80%"), so a raw value >= 50 is interpreted as a percent-multiplier
    (80 -> 0.80); a value in (1, 50) is interpreted as a discount-rate percent
    (20 -> 0.80 multiplier); a value in (0, 1] is already a multiplier and passes
    through (with a warning below 0.5, since that is an unusually deep discount).
    Matches extractors/safe/discount_multiplier.py and the backward_verifier
    prompt template so the three never disagree.

    Returns (multiplier_or_None, warning_or_error_message).
    """
    if d is None:
        return None, None
    if d <= 0:
        return None, (
            f"discount value {d} <= 0 is invalid. The canonical field is the multiplier "
            f"(0.80 = 20% discount); ask founder for clarification."
        )
    if d <= 1.0:
        # Already a multiplier (0.80 = 20% discount). Pass through.
        if d < 0.5:
            return d, (
                f"discount multiplier {d:.4f} implies a discount deeper than 50% — unusual; "
                f"confirm with founder (the field is the multiplier, not the discount rate)."
            )
        return d, None
    if d < 50.0:
        # Discount-RATE percent (e.g. 20 means a 20% discount → 0.80 multiplier).
        multiplier = 1.0 - (d / 100.0)
        return multiplier, (
            f"discount value {d} interpreted as a discount-rate percent and converted to "
            f"multiplier form {multiplier:.4f}. Per Gotcha #3 the canonical field is the "
            f"multiplier (0.80 = 20% discount); confirm with founder."
        )
    if d <= 100.0:
        # Percent-MULTIPLIER (e.g. 80 means the multiplier is 0.80, a 20% discount).
        multiplier = d / 100.0
        return multiplier, (
            f"discount value {d} interpreted as a percent-multiplier and converted to "
            f"multiplier form {multiplier:.4f}. Per Gotcha #3 the canonical field is the "
            f"multiplier (0.80 = 20% discount); confirm with founder."
        )
    return None, (
        f"discount value {d} > 100 — uninterpretable. The field is the multiplier "
        f"(0.80 = 20% discount); ask founder for clarification."
    )


def validate_safe(fields: dict[str, Any], confidence: dict[str, Any] | None = None) -> list[str]:
    errors = []
    # Relaxable fields the extractor affirmatively documented as absent (level == "absent") become
    # warnings at the call site rather than errors — a blank/template SAFE persists as a partial.
    absent = documented_absent_fields(fields, confidence or {}) & SAFE_RELAXABLE_ABSENT_FIELDS
    form = fields.get("form", "other")
    if form not in SAFE_FORM_GATES:
        errors.append(f"unknown SAFE form: {form}")
        return errors
    gate = SAFE_FORM_GATES[form]
    for fld in gate["required_non_null"]:
        if fields.get(fld) is None:
            errors.append(f"form={form} requires non-null {fld}")
    for fld in gate["must_be_null"]:
        if fields.get(fld) is not None:
            errors.append(f"form={form} requires {fld} to be null/absent")
    if gate.get("must_have_mfn"):
        mfn = fields.get("mfn_provision") or {}
        if not mfn.get("present"):
            errors.append(f"form={form} requires mfn_provision.present == true")
    if not fields.get("purchase_amount") and "purchase_amount" not in absent:
        errors.append("purchase_amount is required")
    if not fields.get("issuance_date") and "issuance_date" not in absent:
        errors.append("issuance_date is required")
    return errors


# Per-subtype required-field gates for the convertible_note family.
# Routing is done in _cli via the instrument_type enum; the subtype value is
# stored on the canonical convertible_note shape and surfaced as provenance
# to downstream consumers. Reflects real-world convertible eval data (CLA,
# convertible_security, and bridge-note shapes; anonymized).
CONVERTIBLE_SUBTYPE_GATES: dict[str, dict[str, Any]] = {
    # Standard YC / NVCA convertible note (Series Seed Note, US promissory).
    # All canonical fields apply. This is the default when no subtype is set.
    "convertible_note": {
        "always_required": [
            "principal",
            "day_count_basis",
            "issuance_date",
            "maturity_date",
            "maturity_default_treatment",
        ],
        "may_be_null": [],
    },
    # Israeli convertible loan agreement (CLA / CIA). Mathematically identical
    # to the canonical convertible_note: principal + interest + maturity + QF
    # conversion. The naming differs (GKH templates: "Investment Amount" /
    # "Investors" instead of "Principal Amount" / "Lenders") but the math is
    # the same. Israeli CLAs commonly carry ITA Section 3(j) statutory interest
    # (interest_rate_type="statutory_ita_section_3j"; annual_interest_rate=null).
    "convertible_loan_agreement": {
        "always_required": [
            "principal",
            "day_count_basis",
            "issuance_date",
            "maturity_date",
            "maturity_default_treatment",
        ],
        "may_be_null": [],
    },
    # YC convertible_security (pre-SAFE form, used by GS-Cap Table etc.) is
    # SAFE-equivalent: no interest, no maturity date, conversion-on-QF only.
    # The doc has: principal (Purchase Amount), valuation_cap or discount,
    # qualified_financing_threshold (QF definition). Maturity-related fields
    # may be null.
    "convertible_security": {
        "always_required": ["principal", "issuance_date"],
        "may_be_null": ["maturity_date", "maturity_default_treatment", "day_count_basis", "annual_interest_rate"],
    },
}


def validate_note(
    fields: dict[str, Any], *, subtype: str | None = None, confidence: dict[str, Any] | None = None
) -> list[str]:
    errors = []
    # Relaxable fields the extractor affirmatively documented as absent (level == "absent") become
    # warnings at the call site rather than errors — a partial/blank note persists as a partial.
    absent = documented_absent_fields(fields, confidence or {}) & NOTE_RELAXABLE_ABSENT_FIELDS
    # interest_rate_type drives whether annual_interest_rate must be numeric.
    # Default to fixed_numeric for backward compatibility with extractions that
    # don't return the type explicitly.
    rate_type = fields.get("interest_rate_type", "fixed_numeric")
    if rate_type not in INTEREST_RATE_TYPES_ALL:
        errors.append(f"interest_rate_type must be one of {sorted(INTEREST_RATE_TYPES_ALL)}; got {rate_type!r}")
    # Required-field gate routed by subtype (post-J audit commit #6).
    # convertible_security (SAFE-equivalent) waives maturity-related fields.
    gate_key = subtype if subtype in CONVERTIBLE_SUBTYPE_GATES else "convertible_note"
    gate = CONVERTIBLE_SUBTYPE_GATES[gate_key]
    for r in gate["always_required"]:
        if fields.get(r) is None and r not in absent:
            errors.append(f"required field {r} is missing (subtype={gate_key!r})")
    # annual_interest_rate is conditionally required, also routed by subtype:
    #   - fixed_numeric / fixed_numeric_simple: numeric rate required
    #     (EXCEPT when subtype waives it, e.g., convertible_security with rate_type=none)
    #   - statutory_ita_section_3j: rate is null (Israeli ITA sets annually)
    #   - none: SAFE-equivalent — no interest provision
    annual_interest_rate_waived = "annual_interest_rate" in gate.get("may_be_null", [])
    if rate_type in INTEREST_RATE_TYPES_REQUIRING_NUMERIC:
        if fields.get("annual_interest_rate") is None and not annual_interest_rate_waived:
            errors.append(f"annual_interest_rate is required when interest_rate_type={rate_type!r}")
    elif rate_type in INTEREST_RATE_TYPES_ALLOWING_NULL and fields.get("annual_interest_rate") is not None:
        # Statutory or none — value MUST be null; if numeric was extracted, drop it
        # and require the agent to re-surface as ambiguity instead.
        errors.append(
            f"annual_interest_rate must be null when interest_rate_type={rate_type!r}; "
            f"got {fields.get('annual_interest_rate')!r}. For statutory_ita_section_3j the "
            f"rate is set annually by the Israeli Tax Authority — do not fabricate a value."
        )
    # Branch consistency: maturity_conversion_price_override only with convert_at_cap
    has_override = fields.get("maturity_conversion_price_override") is not None
    is_convert_at_cap = fields.get("maturity_default_treatment") == "convert_at_cap"
    if has_override and not is_convert_at_cap:
        errors.append(
            "maturity_conversion_price_override is non-null but "
            "maturity_default_treatment != 'convert_at_cap'; per Gotcha #5 the "
            "override only applies to convert_at_cap (E_NOTE_OVERRIDE_BRANCH_MISMATCH)"
        )
    return errors


def validate_non_extractable(fields: dict[str, Any]) -> list[str]:
    """Validator for doc_types that are not standard SAFE/note instruments
    (warrants, non-instrument misfiles). Accepts empty fields block."""
    return []  # no required fields; the doc_type itself is the classification


def build_verifier_input(fields: dict[str, Any], confidence: dict[str, Any]) -> dict[str, Any]:
    """Adapt production extraction shape ({fields, confidence}) to the
    evidence_verifier input shape ({fields: {name: {value, evidence_quote}}})
    so verify_extraction can run unchanged on production output.

    fields:       {"purchase_amount": 500000, "post_money_valuation_cap": 20000000, ...}
    confidence:   {"purchase_amount": {"level": "high", "evidence_quote": "...", "document_location": "..."}, ...}
    """
    verifier_fields: dict[str, Any] = {}
    for fname, fvalue in fields.items():
        conf = confidence.get(fname) if isinstance(confidence, dict) else None
        evidence_quote = None
        if isinstance(conf, dict):
            evidence_quote = conf.get("evidence_quote")
        verifier_fields[fname] = {
            "value": fvalue,
            "evidence_quote": evidence_quote,
        }
    return {"fields": verifier_fields}


def documented_absent_fields(fields: dict[str, Any], confidence: dict[str, Any]) -> set[str]:
    """Field names the extractor deliberately reported as absent from the
    document: a falsy value (None/False/"") paired with confidence level
    "absent". There is no evidence quote for the absence of something, so
    these are not hallucination candidates — the verifier's "value present
    but no evidence_quote" fail path should not apply to them.

    Only matches on the explicit "absent" level, not merely a falsy value —
    a real `False`/`None` the model is otherwise confident about (e.g.
    level "high" with a quote, or a falsy value with no absence signal at
    all) still goes through normal verification.
    """
    out: set[str] = set()
    for fname, fvalue in fields.items():
        if not (fvalue is None or fvalue is False or fvalue == ""):
            continue
        conf = confidence.get(fname) if isinstance(confidence, dict) else None
        level = conf.get("level") if isinstance(conf, dict) else conf
        if level == "absent":
            out.add(fname)
    return out


# Synthesized fields that don't have verbatim source quotes. Tuned against
# the eval set — these are fields where the model produces a classification
# (enum) or derived count, not a verbatim extraction. The forward verifier
# would always flag them as not-in-doc.
SYNTHESIZED_FIELDS_SKIP_VERIFICATION = {
    # Enum classifications
    "form",
    "instrument_subtype",
    "interest_rate_type",
    "jurisdiction",
    "doc_type",
    "format",  # carta | pulley | freeform
    "anti_dilution_provision",
    "anti_dilution_type",
    "liquidation_participation",
    "liq_pref_type",
    "option_pool_basis",
    "conversion_trigger",
    "maturity_default_treatment",
    # Composite types verifier can't introspect
    "mfn_provision",  # {present: bool}
    # Derived counts (model counted rows in source, not verbatim)
    "options_granted_count",
    "convertibles_active_count",
    "total_authorized_shares",
    "total_issued_shares",
    # List fields (verifier can't introspect each element)
    "share_classes",
    "preferred_series",
    "authorized_share_classes",
    "expected_absent",
    # Partial-instrument state, stamped by the script after validation (never sub-agent-extracted,
    # so they carry no evidence_quote by design — verifying them would flip a clean partial to 'fail').
    "completeness",
    "missing_required_fields",
    "to_confirm",
    # Metadata / non-extraction fields
    "extraction_confidence",
    "id",
    "label_source",
    "corpus",
    "label_schema_version",
    "label_compat_min",
    "label_compat_max",
}


def filter_verifier_report(
    report_dict: dict[str, Any], absent_fields: set[str] | None = None, no_quote_soft: bool = False
) -> dict[str, Any]:
    """Demote failures on synthesized fields to 'skipped', and failures on
    documented-absent fields (see documented_absent_fields) to
    'skipped_documented_absence'. Prevents the two most common
    false-positive classes from cluttering verification reports.

    `no_quote_soft` (terms docs): a `fail` whose ONLY reason is the missing-quote
    reason demotes to `unverified_no_quote` — a schema-less terms doc paraphrases
    narrative fields, so a missing verbatim quote is not a hallucination signal.
    A genuine `value_in_doc failed` is never softened."""
    absent_fields = absent_fields or set()
    filtered_per_field = []
    n_skipped_synth = 0
    n_skipped_absence = 0
    for r in report_dict.get("per_field", []):
        _reasons_txt = " ".join(r.get("reasons", []))
        if r["field"] in SYNTHESIZED_FIELDS_SKIP_VERIFICATION:
            r = {
                **r,
                "status": "skipped_synthesized",
                "reasons": r.get("reasons", []) + ["field is synthesized; skipping evidence check"],
            }
            n_skipped_synth += 1
        elif (
            no_quote_soft
            and r["status"] == "fail"
            and "evidence_quote is null/empty" in _reasons_txt
            and "value_in_doc failed" not in _reasons_txt
        ):
            r = {
                **r,
                "status": "unverified_no_quote",
                "reasons": r.get("reasons", [])
                + ["terms doc: no evidence quote — surfaced to-confirm, not a hard fail"],
            }
        elif r["status"] == "fail" and r["field"] in absent_fields:
            r = {
                **r,
                "status": "skipped_documented_absence",
                "reasons": r.get("reasons", [])
                + ["extractor reported field absent from document; no evidence to quote for an absence"],
            }
            n_skipped_absence += 1
        filtered_per_field.append(r)
    out = {**report_dict, "per_field": filtered_per_field}
    out["n_skipped_synthesized"] = n_skipped_synth
    out["n_skipped_absence"] = n_skipped_absence
    # Recompute overall_status excluding synthesized and documented-absence fields
    real = [r for r in filtered_per_field if r["status"] not in ("skipped_synthesized", "skipped_documented_absence")]
    n_fail = sum(1 for r in real if r["status"] == "fail")
    n_pass = sum(1 for r in real if r["status"] == "pass")
    n_unver = sum(1 for r in real if r["status"] == "unverifiable")
    out["filtered_summary"] = {
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_unverifiable": n_unver,
        "n_skipped_synthesized": n_skipped_synth,
        "n_skipped_absence": n_skipped_absence,
    }
    if out.get("overall_status") == "unverifiable_doc":
        pass  # leave as-is
    elif n_fail == 0:
        out["overall_status"] = "pass" if n_pass > 0 else "no_verifiable_fields"
    else:
        out["overall_status"] = "fail"
    return out


def confirm_required(confidence: dict[str, Any]) -> list[str]:
    """Return field names with low confidence that need user confirmation.

    Sub-agents occasionally return `confidence` as a bare string (e.g.,
    `"confidence": "medium"`) instead of the per-field map. Surface this with a
    clear error message rather than crashing on `.items()`.
    """
    if not isinstance(confidence, dict):
        raise ValueError(
            f"`confidence` must be a per-field map like "
            f"{{'purchase_amount': {{'level': 'high', 'evidence_quote': '...'}} , ...}}; "
            f"got {type(confidence).__name__}. See lane-1 reference 'Sub-agent response shape' section."
        )
    low = []
    for fname, ent in confidence.items():
        level = ent.get("level") if isinstance(ent, dict) else ent
        if level in {"low", "medium"}:
            low.append(fname)
    return low


def _instruments_refusal(path: str, detail: str) -> int:
    """`--instruments` points at something this script cannot safely append to.

    Same four properties as `_gate_refusal` and the fleet contract behind it -- diagnostic to
    stdout, a line to stderr, the canonical path untouched, exit non-zero -- but a different
    cause, so a different function and a different code. This is a PRECONDITION on a file the
    operator named, not a rejection of the extraction on stdin.

    Refusing rather than repairing is the whole point. This script APPENDS: the file may hold
    instruments extracted from earlier documents in the same engagement, so overwriting it on a
    guess is unrecoverable. The most valuable case is the one that looks most innocent -- a path
    that is simply the wrong file. `inputs.json` passed here is a JSON object with none of the
    instrument arrays; filling them in and writing would rewrite its `schema_version` to
    `v0.5.0-instruments` and leave a hybrid that no consumer can read, on a ZERO exit. The schema
    cannot catch that: the validator ignores `additionalProperties`, so every foreign key from the
    wrong file passes, and schema-validity only ever certifies "has the five keys", never "is the
    right file".
    """
    diagnostic = {"ok": False, "error": "E_INSTRUMENTS_FILE_UNUSABLE", "path": path, "detail": detail}
    print(json.dumps(diagnostic, indent=2))
    print(f"Error: E_INSTRUMENTS_FILE_UNUSABLE - {detail}", file=sys.stderr)
    print(f"Error: {os.path.abspath(path)} was left unchanged.", file=sys.stderr)
    return 1


_INSTRUMENT_ARRAYS = ("safes", "convertible_notes", "warrants", "option_grants")


def _gate_refusal(gates: dict[str, Any], args: argparse.Namespace, code: str) -> int:
    """A BLOCKING anti-hallucination gate refused. Emit loudly; write no canonical artifact.

    Matches the fleet's producer-refusal contract (diagnostic to stdout, a line to stderr,
    the canonical path left untouched, exit non-zero) -- the same shape as `_fail_invalid`
    in market-sizing's `market_sizing.py`.

    The gates that call this are default-ON and they used to run AFTER `write_artifact`, so a
    refusal exited 1 with a hallucinated `instruments.json` already on disk. Downstream math
    producers read that file; the gate exists precisely to stop them. Refusing before the
    write is what makes the gate mean anything.

    Returns the diagnostic on stdout rather than a receipt: there is no receipt, because
    nothing was written. `--output` (the receipt path) is likewise left untouched.
    """
    # FLAT, not nested under a "gates" key: SKILL.md:416 documents a `retry_hint` re-dispatch
    # lane that reads `evidence_verification.rejection.retry_hint` off this payload, and
    # `test_cap_table.py::test_verify_blocking_exits_nonzero_on_hallucination` pins it. The
    # refusal markers are added alongside, so a reader can tell a refusal from a receipt
    # (`ok: false` + `error`) without the gate findings moving.
    diagnostic: dict[str, Any] = {"ok": False, "error": code, **gates}
    print(json.dumps(diagnostic, indent=2 if args.pretty else None))
    print(
        f"Error: {code} - extraction rejected by a blocking gate; no instruments.json written.",
        file=sys.stderr,
    )
    print(f"Error: {os.path.abspath(args.instruments)} was left unchanged.", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instruments", required=True, help="Path to existing instruments.json (will be updated)")
    p.add_argument("--run-id", required=True)
    p.add_argument(
        "--require-confirm",
        action="store_true",
        help="Exit 1 if any field has confidence < high (force user confirmation)",
    )
    p.add_argument(
        "--source-doc",
        help="Path to the source document (PDF/DOCX/XLSX). Required when --verify is on (default).",
    )
    p.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Evidence verification against --source-doc. Default: ON. "
        "Use --no-verify to disable (e.g. for tests with no source doc).",
    )
    p.add_argument(
        "--verify-blocking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit 1 on evidence verification failure. Default: ON. Use --no-verify-blocking for informational mode.",
    )
    p.add_argument(
        "--invariants",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run invariant_checker: per-field bounds + cross-field math invariants. "
        "Default: ON. Hard math violations exit 1; soft bounds violations warn-only.",
    )
    p.add_argument(
        "--cross-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run deterministic backstop extractors and cross-check against the "
        "sub-agent's values (demote confidence on disagreement). Default: ON for "
        "instrument types that have backstop extractors (currently SAFE only). "
        "Always informational — never blocks.",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="If the target array already contains an entry with the same id, overwrite it "
        "in place (upsert). Without this flag, a duplicate id is a hard error "
        "(E_DUPLICATE_INSTRUMENT_ID) and the file is left unchanged.",
    )
    p.add_argument("--pretty", action="store_true")
    p.add_argument("-o", "--output", default=None, help="Write the receipt to this file; emit a receipt to stdout")
    args = p.parse_args()

    # Fail loud if a --source-doc path was given but does not exist: a missing file is an agent
    # plumbing error (e.g. a host/VM path mismatch), NOT an image-only doc. Silently degrading to
    # unverifiable_doc / ok:true hides the failure. Checked at argument-validation
    # time, before write_artifact, so nothing is persisted on a bad path.
    if args.source_doc and not os.path.isfile(args.source_doc):
        sys.stderr.write(
            f"extract_instrument.py: E_SOURCE_DOC_NOT_FOUND: --source-doc file not found: {args.source_doc}\n"
        )
        return 1

    extraction = json.load(sys.stdin)
    if not isinstance(extraction, dict):
        sys.stderr.write("extract_instrument.py: stdin must contain a JSON object\n")
        return 1

    itype = extraction.get("instrument_type")
    fields = extraction.get("fields", {})
    confidence = extraction.get("confidence", {})
    ambiguities = extraction.get("ambiguities", [])

    valid_itypes = {
        "safe",
        "convertible_note",
        # Convertible-note family (commit #6 post-J audit): real-world docs
        # come in three flavors that share the same math but differ in document
        # naming convention + which fields may be null.
        "convertible_loan_agreement",  # Israeli CLA / CIA — GKH/Herzog/Meitar templates
        "convertible_security",  # YC pre-SAFE convertible security — SAFE-equivalent
        "term_sheet",
        "option_plan",
        # warrant + non_instrument + amendment let misfiled or clause-only docs (a warrant that
        # ended up in the safes/ folder, a financing-notice letter mistaken for a SAFE, or an
        # amendment that only restates one clause of an existing instrument) return cleanly
        # classified rather than forcing an invalid SAFE/note classification. These are exactly
        # NON_EXTRACTABLE_ITYPES (kept as literals here so the enum is greppable).
        "warrant",
        "non_instrument",
        "amendment",
    }
    assert valid_itypes.issuperset(NON_EXTRACTABLE_ITYPES)  # keep the two in sync
    if itype not in valid_itypes:
        sys.stderr.write(f"extract_instrument.py: unknown instrument_type: {itype}\n")
        return 1

    # Normalize the instrument_type → canonical `convertible_note` for
    # downstream artifact storage, preserving the original as `subtype` for
    # provenance. instruments.json schema accepts {safe, convertible_note,
    # term_sheet, option_plan, warrant, non_instrument} — the new subtype
    # field is a parallel provenance marker. Math producers
    # (note_conversion.py) consume the canonical convertible_note shape
    # regardless of subtype.
    convertible_family = {"convertible_loan_agreement", "convertible_security"}
    subtype: str | None = None
    if itype in convertible_family:
        subtype = itype
        itype = "convertible_note"
        # For convertible_security (SAFE-equivalent): set sensible defaults
        # if extraction left fields null/unset.
        if subtype == "convertible_security":
            if fields.get("interest_rate_type") is None:
                fields["interest_rate_type"] = "none"
            if fields.get("annual_interest_rate") is None:
                fields["annual_interest_rate"] = None  # explicit null

    # Normalize discount if needed (Gotcha #3)
    warnings: list[str] = []
    if "discount_multiplier" in fields and itype in {"safe", "convertible_note"}:
        norm, msg = normalize_discount_multiplier(fields["discount_multiplier"])
        fields["discount_multiplier"] = norm
        if msg:
            warnings.append(msg)

    # Validate by type
    if itype == "safe":
        errors = validate_safe(fields, confidence=confidence)
    elif itype == "convertible_note":
        errors = validate_note(fields, subtype=subtype, confidence=confidence)
    elif itype in NON_EXTRACTABLE_ITYPES:
        errors = validate_non_extractable(fields)
    else:
        errors = []  # term_sheet / option_plan: caller routes elsewhere

    if errors:
        sys.stderr.write("extract_instrument.py: validation errors:\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1

    low_confidence = confirm_required(confidence)
    if args.require_confirm and low_confidence:
        sys.stderr.write(
            "extract_instrument.py: --require-confirm set and these fields have low/medium "
            "confidence (need user confirmation): " + ", ".join(low_confidence) + "\n"
        )
        return 1

    # Load existing instruments.json and append.
    #
    # Every branch below that refuses used to raise instead: a malformed file tracebacked out of
    # `json.load`, and a JSON object of the wrong shape reached `len(instruments["safes"])` and
    # died on a KeyError. Neither clobbered anything, so this is not the write-before-validate
    # class -- it is the other half of the same contract, failing loudly AND cleanly. The
    # `metadata` branch is the exception and the reason this is worth doing: a non-dict `metadata`
    # is silently discarded by `write_artifact`, so today that path exits 0 having overwritten
    # whatever was there.
    if os.path.exists(args.instruments):
        try:
            with open(args.instruments, encoding="utf-8") as f:
                instruments = json.load(f)
        except json.JSONDecodeError as e:
            return _instruments_refusal(args.instruments, f"file is not valid JSON: {e}")
        except OSError as e:
            return _instruments_refusal(args.instruments, f"file could not be read: {e}")
        if not isinstance(instruments, dict):
            return _instruments_refusal(
                args.instruments, f"file holds a JSON {type(instruments).__name__}, not an object"
            )
        present = [k for k in _INSTRUMENT_ARRAYS if k in instruments]
        if not present:
            # NOT the forgiving case, and treating it as one was the first design here. A JSON
            # object carrying none of the four arrays is evidence the path is wrong, not evidence
            # of an incomplete file -- and every writer of a real one emits all four
            # (`freeform_mapper`, and the hand-authoring skeleton SKILL.md documents).
            return _instruments_refusal(
                args.instruments,
                "file is a JSON object but carries none of "
                f"{', '.join(_INSTRUMENT_ARRAYS)} — it does not look like an instruments.json",
            )
        bad = [k for k in present if not isinstance(instruments[k], list)]
        if bad:
            return _instruments_refusal(
                args.instruments, f"expected a list for {', '.join(bad)} — appending is not possible"
            )
        if "metadata" in instruments and not isinstance(instruments["metadata"], dict):
            # write_artifact replaces a non-dict `metadata` wholesale, so continuing here means
            # discarding it silently on a successful exit.
            return _instruments_refusal(
                args.instruments,
                f"metadata is a {type(instruments['metadata']).__name__}, not an object — continuing would discard it",
            )
        # Forgiving only now: at least one array proves the file's identity, so the rest being
        # absent is an incomplete instruments.json rather than the wrong one. `write_artifact`
        # requires all four, and without this the operator got a schema error naming a field they
        # never supplied.
        for key in _INSTRUMENT_ARRAYS:
            instruments.setdefault(key, [])
    else:
        instruments = {
            "safes": [],
            "convertible_notes": [],
            "warrants": [],
            "option_grants": [],
            "metadata": {},
        }

    # Set default extraction_confidence based on the most cautious of the fields
    field_level = "high"
    for ent in confidence.values():
        lvl = ent.get("level") if isinstance(ent, dict) else ent
        if lvl == "low":
            field_level = "low"
            break
        if lvl == "medium" and field_level == "high":
            field_level = "medium"
    fields.setdefault("extraction_confidence", field_level)

    # Partial instrument: relaxable required fields the extractor documented as absent were relaxed to
    # warnings (not errors) above. Stamp the partiality INSIDE the artifact (so it travels with the
    # data, not just the receipt), demote extraction_confidence, and emit a per-field warning. The
    # value stays null — never fabricated; the founder confirms via the downstream CONFIRM-GATE.
    relaxable = (
        SAFE_RELAXABLE_ABSENT_FIELDS
        if itype == "safe"
        else NOTE_RELAXABLE_ABSENT_FIELDS
        if itype == "convertible_note"
        else WARRANT_RELAXABLE_ABSENT_FIELDS
        if itype == "warrant"
        else frozenset()
    )
    absent_relaxed = sorted(documented_absent_fields(fields, confidence) & relaxable)
    if absent_relaxed:
        amb_map = {a.get("field"): a.get("reason") for a in ambiguities if isinstance(a, dict) and a.get("field")}
        fields["completeness"] = "partial"
        fields["missing_required_fields"] = absent_relaxed
        fields["to_confirm"] = {fld: amb_map.get(fld) or "not stated in document; confirm" for fld in absent_relaxed}
        fields["extraction_confidence"] = "low"  # a documented-absent partial is not high-confidence
        for fld in absent_relaxed:
            warnings.append(f"W_FIELD_ABSENT_IN_DOC:{fld}")

    def _upsert_or_error(
        array: list[Any],
        entry: dict[str, Any],
        *,
        array_name: str,
    ) -> str | None:
        """Check for a duplicate id in array.

        When args.replace is set, replace the existing entry in place and
        return None. When args.replace is not set and a duplicate is found,
        return the structured error code string (do not raise — caller exits 1).
        When no duplicate exists, append and return None.

        Requires entry to have an 'id' key already set.
        """
        eid = entry.get("id")
        for i, existing in enumerate(array):
            if existing.get("id") == eid:
                if args.replace:
                    array[i] = entry
                    return None
                return (
                    f"E_DUPLICATE_INSTRUMENT_ID: entry '{eid}' already exists in "
                    f"instruments.json {array_name}[] — pass --replace to overwrite it, "
                    f"or use a new id"
                )
        array.append(entry)
        return None

    def _looks_like_content_duplicate(
        array: list[dict[str, Any]], entry: dict[str, Any], keys: tuple[str, ...]
    ) -> bool:
        """A prior entry with a DIFFERENT id but identical content — the signature of
        a re-piped correction that got a fresh sequential id instead of overwriting.
        Different-id only, so a deliberate same-id `--replace` upsert never trips it."""
        eid = entry.get("id")
        for existing in array:
            if existing.get("id") == eid:
                continue
            if all(existing.get(k) is not None and existing.get(k) == entry.get(k) for k in keys):
                return True
        return False

    if itype == "safe":
        # Allocate next id
        fields.setdefault("id", f"safe_{len(instruments['safes']) + 1:03d}")
        if _looks_like_content_duplicate(
            instruments["safes"], fields, ("investor_name", "purchase_amount", "issuance_date")
        ):
            warnings.append(
                "W_POSSIBLE_DUPLICATE_INSTRUMENT: a safes[] entry with the same "
                "investor_name / purchase_amount / issuance_date already exists — this looks like a "
                "re-piped correction that was appended under a new id; reset the array or reuse the "
                "same id with --replace to avoid a duplicate."
            )
        dup_err = _upsert_or_error(instruments["safes"], fields, array_name="safes")
        if dup_err:
            sys.stderr.write(f"extract_instrument.py: {dup_err}\n")
            print(json.dumps({"error": "E_DUPLICATE_INSTRUMENT_ID", "detail": dup_err}))
            return 1
    elif itype == "convertible_note":
        fields.setdefault("id", f"note_{len(instruments['convertible_notes']) + 1:03d}")
        # Record subtype for provenance. Math producers consume the canonical
        # convertible_note shape; subtype is informational for counsel-review
        # framing (Israeli CLA / YC convertible_security / standard note).
        if subtype:
            fields["subtype"] = subtype
        if _looks_like_content_duplicate(
            instruments["convertible_notes"], fields, ("investor_name", "principal", "issuance_date")
        ):
            warnings.append(
                "W_POSSIBLE_DUPLICATE_INSTRUMENT: a convertible_notes[] entry with the same "
                "investor_name / principal / issuance_date already exists — this looks like a "
                "re-piped correction that was appended under a new id; reset the array or reuse the "
                "same id with --replace to avoid a duplicate."
            )
        dup_err = _upsert_or_error(instruments["convertible_notes"], fields, array_name="convertible_notes")
        if dup_err:
            sys.stderr.write(f"extract_instrument.py: {dup_err}\n")
            print(json.dumps({"error": "E_DUPLICATE_INSTRUMENT_ID", "detail": dup_err}))
            return 1
    elif itype == "warrant":
        # v0.5.0: warrants require a full item shape (shares_underlying,
        # exercise_price, warrant_type, issuance_date, settlement_type,
        # vested_flag). The Lane-1 warrant misfile escape hatch produces an
        # empty fields-block; only persist the warrant when minimum required
        # fields are present. Otherwise, surface as a non-instrument
        # classification and let the founder re-extract via the Lane-2 Carta
        # warrant ledger path.
        # A present-but-null exercise_price is only legitimate when its absence is DOCUMENTED
        # (confidence.level == "absent" + ambiguities entry) — that path stamped the warrant partial
        # above (absent_relaxed). An undocumented null is a fabrication-inviting gap: fail loud. Guard on
        # key-PRESENT-and-null, never key-absent: a missing key is the empty-fields misfile escape hatch
        # below, which must keep its rc-0 "NOT persisted" behavior.
        if "exercise_price" in fields and fields["exercise_price"] is None and "exercise_price" not in absent_relaxed:
            _werr = (
                "E_WARRANT_EXERCISE_PRICE_UNDOCUMENTED_NULL: warrant exercise_price is null but its "
                "absence is not documented. To capture a warrant whose strike is genuinely not stated, "
                "mark exercise_price with confidence.level='absent' and add an ambiguities entry; "
                "otherwise supply the strike. Never fabricate."
            )
            sys.stderr.write(f"extract_instrument.py: {_werr}\n")
            print(json.dumps({"error": "E_WARRANT_EXERCISE_PRICE_UNDOCUMENTED_NULL", "detail": _werr}))
            return 1
        required_warrant_keys = (
            "shares_underlying",
            "exercise_price",
            "warrant_type",
            "issuance_date",
            "settlement_type",
            "vested_flag",
        )
        if all(k in fields for k in required_warrant_keys):
            fields.setdefault("id", f"warrant_{len(instruments['warrants']) + 1:03d}")
            dup_err = _upsert_or_error(instruments["warrants"], fields, array_name="warrants")
            if dup_err:
                sys.stderr.write(f"extract_instrument.py: {dup_err}\n")
                print(json.dumps({"error": "E_DUPLICATE_INSTRUMENT_ID", "detail": dup_err}))
                return 1
        else:
            warnings.append(
                "extract_instrument.py: warrant classification accepted but the extraction did not provide a "
                "full warrant item shape (missing one of: " + ", ".join(required_warrant_keys) + "); "
                "the warrant was NOT persisted. Re-extract via the Lane-2 Carta warrant ledger path or "
                "supply a full warrant heredoc."
            )
    # itype == "non_instrument": classified-as-non-extractable; do not append to
    # any instrument array. The receipt below surfaces the classification.

    # ---- ANTI-HALLUCINATION GATES RUN BEFORE THE ARTIFACT IS WRITTEN ----
    # These gates are default-ON and BLOCKING, and they used to run AFTER write_artifact: a
    # blocking refusal exited 1 with a hallucinated instruments.json already on disk for the
    # math producers to consume, which inverts the point of an anti-hallucination gate. They
    # now populate `gates` (a plain dict merged into the receipt after a successful write) and
    # never touch the canonical path, so a refusal leaves --instruments untouched.
    gates: dict[str, Any] = {}
    # Evidence verification. --verify-blocking exits non-zero on failure (default ON).
    if args.verify:
        if not args.source_doc:
            sys.stderr.write("extract_instrument.py: --verify requires --source-doc\n")
            return 1
        if itype in NON_EXTRACTABLE_ITYPES:
            # Non-extractable classifications have no fields to verify.
            gates["evidence_verification"] = {
                "overall_status": "skipped_non_instrument",
                "reason": f"doc classified as {itype}; no fields to verify",
            }
        else:
            from pathlib import Path as _Path

            try:
                doc_text = _ev_load_doc_text(_Path(args.source_doc))
            except MissingDependencyError as _e:
                # Blocking gate must fail loudly on a missing parser, not
                # silently degrade to 'unverifiable_doc' (which would pass).
                gates["evidence_verification"] = {
                    "overall_status": "error",
                    "error": "E_MISSING_DEPENDENCY",
                    "dependency": _e.dependency,
                    "detail": str(_e),
                }
                sys.stderr.write(str(_e) + "\n")
                return _gate_refusal(gates, args, "E_MISSING_DEPENDENCY")
            verifier_input = build_verifier_input(fields, confidence)
            verification_report = verify_extraction(verifier_input, doc_text)
            raw_report = report_to_dict(verification_report)
            absent_fields = documented_absent_fields(fields, confidence)
            filtered = filter_verifier_report(raw_report, absent_fields, no_quote_soft=itype in TERMS_DOC_ITYPES)
            gates["evidence_verification"] = filtered

            # Structured rejection contract: when there are real value_in_doc
            # failures, surface a re-prompt hint that the dispatching agent
            # can use to ask the sub-agent to recheck specific fields.
            real_failures = [
                r
                for r in filtered["per_field"]
                if r["status"] == "fail" and "value_in_doc failed" in " ".join(r.get("reasons", []))
            ]
            if real_failures:
                # Terms docs never block on a finding: the gate record keeps the rejection (so a
                # dispatcher may still repair) and the renderer marks the rows; only exit 1 otherwise.
                _blocks = args.verify_blocking and itype not in TERMS_DOC_ITYPES
                gates["evidence_verification"]["rejection"] = {
                    "rejected": _blocks,
                    "reason": "value_in_doc_failures",
                    "failed_fields": [r["field"] for r in real_failures],
                    "retry_hint": (
                        "These field values were not found in the source document; the sub-agent "
                        "may have fabricated them. For each: either correct to a value verifiable "
                        "in the source, or set to null with ambiguity describing why the field is absent. "
                        "Fields: " + ", ".join(r["field"] for r in real_failures)
                    ),
                }
                if _blocks:
                    sys.stderr.write(
                        "extract_instrument.py: evidence verification failed (blocking mode). "
                        "Fields with value_in_doc failures: " + ", ".join(r["field"] for r in real_failures) + "\n"
                    )
                    return _gate_refusal(gates, args, "E_EVIDENCE_VERIFICATION_FAILED")

    # Invariant checking. Default ON via --invariants. Hard math invariants
    # block (e.g. options_granted > total_authorized); soft bounds violations
    # warn-only.
    if args.invariants and itype not in NON_EXTRACTABLE_ITYPES:
        # invariant_checker takes the flat {name: value} form; build_verifier_input
        # only adapts to the evidence-verifier shape.
        invariant_input = {"instrument_type": itype, "fields": fields}
        inv_report = _invariant_check(invariant_input)
        gates["invariant_check"] = _invariant_report_to_dict(inv_report)
        # Terms docs never block on an invariant FINDING: it is recorded + surfaced in
        # attention_needed_fields + marked by the renderer (a false-positive-prone cross-field check on
        # display-only content must not empty the deliverable). Other itypes still block.
        if inv_report.n_hard_violations > 0 and itype not in TERMS_DOC_ITYPES:
            sys.stderr.write(
                "extract_instrument.py: invariant_checker found hard violations: "
                + "; ".join(v.reason for v in inv_report.violations if v.stake == "hard")
                + "\n"
            )
            return _gate_refusal(gates, args, "E_INVARIANT_VIOLATION")

    # Cross-check: run deterministic backstop extractors against the source doc
    # and demote sub-agent confidence on disagreement. Default ON for SAFEs.
    # Always informational — never blocks. Backstop extractors only exist for
    # SAFE currently; extend to other instrument types as they're built.
    if args.cross_check and args.source_doc and itype == "safe":
        from pathlib import Path as _Path

        try:
            from extractors.safe import SAFE_EXTRACTORS as _backstop_extractors
        except ImportError:
            _backstop_extractors = []
        if _backstop_extractors:
            # Reuse doc_text from the verify block if available; otherwise reload.
            # Using locals() avoids ruff F823 on the unbound-name path. Cross-check
            # is informational; a missing parser here downgrades to no-op rather
            # than crashing (the blocking gate already covers the loud path).
            try:
                _doc_text = locals().get("doc_text") or _ev_load_doc_text(_Path(args.source_doc))
            except MissingDependencyError:
                _doc_text = ""
            ctx = _ExtractionContext(instrument_type=itype, source_text=_doc_text, source_path=args.source_doc)
            per_field_cross: list[dict[str, Any]] = []
            n_demotions = 0
            for ext_mod in _backstop_extractors:
                try:
                    backstop_results = ext_mod.extract(ctx)
                except Exception:
                    continue
                for br in backstop_results:
                    sub_value = fields.get(br.name)
                    sub_conf_slot = confidence.get(br.name) if isinstance(confidence, dict) else None
                    sub_conf = (sub_conf_slot.get("level") if isinstance(sub_conf_slot, dict) else "high") or "high"
                    # Skip ambiguity-tagged backstop results — cross_checker treats
                    # them as non-disagreement (don't demote sub-agent's read).
                    if br.value is None and br.confidence == "low":
                        per_field_cross.append(
                            {
                                "field": br.name,
                                "skipped_reason": "backstop_ambiguity",
                                "ambiguity": br.ambiguity,
                            }
                        )
                        continue
                    cc_result = _cross_check(
                        br.name,
                        [
                            {"value": sub_value, "confidence": sub_conf, "extractor_id": "subagent"},
                            {"value": br.value, "confidence": br.confidence, "extractor_id": br.extractor_id},
                        ],
                    )
                    per_field_cross.append(cc_result)
                    if cc_result["disagreement"]:
                        n_demotions += 1
            gates["cross_check"] = {
                "n_demotions": n_demotions,
                "per_field": per_field_cross,
            }

    # attention_needed_fields surfaces the union of fields the dispatching
    # agent should escalate (backward verification, founder review).
    # Includes low/medium-confidence fields + any soft invariant warnings
    # + unverifiable evidence fields.
    attention_fields = set(low_confidence)
    _is_terms_doc = itype in TERMS_DOC_ITYPES
    if "invariant_check" in gates:
        for v in gates["invariant_check"]["violations"]:
            # soft always; for terms docs the hard violations no longer block, so surface them here.
            if v["stake"] == "soft" or (_is_terms_doc and v["stake"] == "hard"):
                attention_fields.add(v["field"])
    if "evidence_verification" in gates:
        per_field = gates["evidence_verification"].get("per_field", [])
        for r in per_field:
            # unverifiable always; for terms docs the non-blocking value_in_doc fails surface here too.
            if r.get("status") == "unverifiable" or (_is_terms_doc and r.get("status") == "fail"):
                attention_fields.add(r["field"])
    if "cross_check" in gates:
        for r in gates["cross_check"]["per_field"]:
            if r.get("disagreement"):
                attention_fields.add(r["field_name"])
    gates["attention_needed_fields"] = sorted(attention_fields)

    schema = load_schema(os.path.join(_SCHEMA_DIR, "instruments.schema.json"))
    try:
        receipt = write_artifact(
            data=instruments,
            schema=schema,
            run_id=args.run_id,
            output_path=args.instruments,
            pretty=args.pretty,
            schema_version="v0.5.0-instruments",
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"extract_instrument.py: instruments.json schema validation failed: {e}\n")
        return 1
    receipt["warnings"] = warnings
    receipt["ambiguities"] = ambiguities
    receipt["low_confidence_fields"] = low_confidence
    receipt["classified_doc_type"] = itype
    if itype in NON_EXTRACTABLE_ITYPES:
        # Surface so downstream consumers know to skip math producers for this doc
        receipt["classified_as_non_extractable"] = True
    elif itype in TERMS_DOC_ITYPES:
        # Content lives in the receipt (never a math array). Strip synthesized stamps so the renderer's
        # flat table shows only real extracted fields (M1: extraction_confidence is stamped at ~:637).
        _synth = {"extraction_confidence", "completeness", "missing_required_fields", "to_confirm"}
        receipt["classified_as_terms_doc"] = True
        receipt["terms_doc"] = {
            "fields": {k: v for k, v in fields.items() if k not in _synth},
            "confidence": confidence,
        }

    # Gate findings computed BEFORE the write (see the banner above) are merged in here.
    receipt.update(gates)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as _fh:
            json.dump(receipt, _fh, indent=2 if args.pretty else None)
        print(json.dumps({"ok": True, "output": os.path.abspath(args.output)}, indent=2 if args.pretty else None))
    else:
        print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
