#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Anti-hallucination validator for Lane-1 instrument extraction.

The Context A sub-agent does the actual extraction from PDF/DOCX. This
script validates the returned JSON, enforces form-dependent required-field
gates (per SKILL.md §5.1), surfaces ambiguities for AskUserQuestion, and
appends the validated instrument into instruments.json.

Per Gotcha #3: this script also normalizes discount values: if a value > 1
is given for discount_multiplier, treat it as percent and convert to
multiplier form (90 → 0.90 = 10% discount; 80 → 0.80 = 20% discount; etc.)
with a warning.
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
from evidence_verifier import _load_doc_text as _ev_load_doc_text  # noqa: E402
from evidence_verifier import report_to_dict, verify_extraction  # noqa: E402
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


def normalize_discount_multiplier(d: float | None) -> tuple[float | None, str | None]:
    """If discount looks like percent (>1), convert to multiplier and warn."""
    if d is None:
        return None, None
    if d > 1.0 and d <= 100.0:
        # Treat as percent — e.g., 20 → 0.80 (20% discount)
        multiplier = 1.0 - (d / 100.0)
        return multiplier, (
            f"discount value {d} > 1 — interpreted as a percent and converted to "
            f"multiplier form {multiplier:.4f}. Per Gotcha #3, the canonical field "
            f"is the multiplier (0.80 = 20% discount); confirm with founder."
        )
    if d > 100.0:
        return None, (
            f"discount value {d} > 100 — uninterpretable. Field is the multiplier "
            f"(0.80 = 20% discount); ask founder for clarification."
        )
    return d, None


def validate_safe(fields: dict[str, Any]) -> list[str]:
    errors = []
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
    if not fields.get("purchase_amount"):
        errors.append("purchase_amount is required")
    if not fields.get("issuance_date"):
        errors.append("issuance_date is required")
    return errors


# Per-subtype required-field gates for the convertible_note family.
# Routing is done in _cli via the instrument_type enum; the subtype value is
# stored on the canonical convertible_note shape (added in commit #6 post-J
# audit) and surfaced as provenance to downstream consumers. Reflects real
# convertible eval data at ~/private-corpus/convertible/ (Acmecorp CLA, Foxtrotcorp
# convertible_security, Golfcorp bridge).
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


def validate_note(fields: dict[str, Any], *, subtype: str | None = None) -> list[str]:
    errors = []
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
        if fields.get(r) is None:
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
    # Metadata / non-extraction fields
    "extraction_confidence",
    "id",
    "label_source",
    "corpus",
    "label_schema_version",
    "label_compat_min",
    "label_compat_max",
}


def filter_verifier_report(report_dict: dict[str, Any]) -> dict[str, Any]:
    """Demote failures on synthesized fields to 'skipped'. Prevents the most
    common false-positive class from cluttering verification reports."""
    filtered_per_field = []
    n_skipped_synth = 0
    for r in report_dict.get("per_field", []):
        if r["field"] in SYNTHESIZED_FIELDS_SKIP_VERIFICATION:
            r = {
                **r,
                "status": "skipped_synthesized",
                "reasons": r.get("reasons", []) + ["field is synthesized; skipping evidence check"],
            }
            n_skipped_synth += 1
        filtered_per_field.append(r)
    out = {**report_dict, "per_field": filtered_per_field}
    out["n_skipped_synthesized"] = n_skipped_synth
    # Recompute overall_status excluding synthesized fields
    real = [r for r in filtered_per_field if r["status"] != "skipped_synthesized"]
    n_fail = sum(1 for r in real if r["status"] == "fail")
    n_pass = sum(1 for r in real if r["status"] == "pass")
    n_unver = sum(1 for r in real if r["status"] == "unverifiable")
    out["filtered_summary"] = {
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_unverifiable": n_unver,
        "n_skipped_synthesized": n_skipped_synth,
    }
    if out.get("overall_status") == "unverifiable_doc":
        pass  # leave as-is
    elif n_fail == 0:
        out["overall_status"] = "pass" if n_pass > 0 else "no_verifiable_fields"
    else:
        out["overall_status"] = "fail"
    return out


def confirm_required(confidence: dict[str, Any]) -> list[str]:
    """Return field names with low confidence that need user confirmation."""
    low = []
    for fname, ent in confidence.items():
        level = ent.get("level") if isinstance(ent, dict) else ent
        if level in {"low", "medium"}:
            low.append(fname)
    return low


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
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

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
        # warrant + non_instrument let misfiled docs (e.g., a warrant that
        # ended up in the safes/ folder, or a financing-notice letter mistaken
        # for a SAFE) return cleanly classified rather than forcing an
        # invalid SAFE/note classification.
        "warrant",
        "non_instrument",
    }
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
        errors = validate_safe(fields)
    elif itype == "convertible_note":
        errors = validate_note(fields, subtype=subtype)
    elif itype in {"warrant", "non_instrument"}:
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

    # Load existing instruments.json and append
    if os.path.exists(args.instruments):
        with open(args.instruments, encoding="utf-8") as f:
            instruments = json.load(f)
    else:
        instruments = {
            "safes": [],
            "notes": [],
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

    if itype == "safe":
        # Allocate next id
        fields.setdefault("id", f"safe_{len(instruments['safes']) + 1:03d}")
        instruments["safes"].append(fields)
    elif itype == "convertible_note":
        fields.setdefault("id", f"note_{len(instruments['notes']) + 1:03d}")
        # Record subtype for provenance (commit #6 post-J audit). Math producers
        # consume the canonical convertible_note shape; subtype is informational
        # for counsel-review framing ("Israeli CLA terms..." vs "convertible
        # security (SAFE-equivalent)...").
        if subtype:
            fields["subtype"] = subtype
        instruments["notes"].append(fields)
    elif itype == "warrant":
        fields.setdefault("id", f"warrant_{len(instruments['warrants']) + 1:03d}")
        instruments["warrants"].append(fields)
    # itype == "non_instrument": classified-as-non-extractable; do not append to
    # any instrument array. The receipt below surfaces the classification.

    schema = load_schema(os.path.join(_SCHEMA_DIR, "instruments.schema.json"))
    try:
        receipt = write_artifact(
            data=instruments,
            schema=schema,
            run_id=args.run_id,
            output_path=args.instruments,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"extract_instrument.py: instruments.json schema validation failed: {e}\n")
        return 1
    receipt["warnings"] = warnings
    receipt["ambiguities"] = ambiguities
    receipt["low_confidence_fields"] = low_confidence
    receipt["classified_doc_type"] = itype
    if itype in {"warrant", "non_instrument"}:
        # Surface so downstream consumers know to skip math producers for this doc
        receipt["classified_as_non_extractable"] = True

    # Evidence verification. --verify-blocking exits non-zero on failure (default ON).
    if args.verify:
        if not args.source_doc:
            sys.stderr.write("extract_instrument.py: --verify requires --source-doc\n")
            return 1
        if itype in {"warrant", "non_instrument"}:
            # Non-extractable classifications have no fields to verify.
            receipt["evidence_verification"] = {
                "overall_status": "skipped_non_instrument",
                "reason": f"doc classified as {itype}; no fields to verify",
            }
        else:
            from pathlib import Path as _Path

            doc_text = _ev_load_doc_text(_Path(args.source_doc))
            verifier_input = build_verifier_input(fields, confidence)
            verification_report = verify_extraction(verifier_input, doc_text)
            raw_report = report_to_dict(verification_report)
            filtered = filter_verifier_report(raw_report)
            receipt["evidence_verification"] = filtered

            # Structured rejection contract: when there are real value_in_doc
            # failures, surface a re-prompt hint that the dispatching agent
            # can use to ask the sub-agent to recheck specific fields.
            real_failures = [
                r
                for r in filtered["per_field"]
                if r["status"] == "fail" and "value_in_doc failed" in " ".join(r.get("reasons", []))
            ]
            if real_failures:
                receipt["evidence_verification"]["rejection"] = {
                    "rejected": args.verify_blocking,
                    "reason": "value_in_doc_failures",
                    "failed_fields": [r["field"] for r in real_failures],
                    "retry_hint": (
                        "These field values were not found in the source document; the sub-agent "
                        "may have fabricated them. For each: either correct to a value verifiable "
                        "in the source, or set to null with ambiguity describing why the field is absent. "
                        "Fields: " + ", ".join(r["field"] for r in real_failures)
                    ),
                }
                if args.verify_blocking:
                    sys.stderr.write(
                        "extract_instrument.py: evidence verification failed (blocking mode). "
                        "Fields with value_in_doc failures: " + ", ".join(r["field"] for r in real_failures) + "\n"
                    )
                    print(json.dumps(receipt, indent=2 if args.pretty else None))
                    return 1

    # Invariant checking. Default ON via --invariants. Hard math invariants
    # block (e.g. options_granted > total_authorized); soft bounds violations
    # warn-only.
    if args.invariants and itype not in {"warrant", "non_instrument"}:
        # invariant_checker takes the flat {name: value} form; build_verifier_input
        # only adapts to the evidence-verifier shape.
        invariant_input = {"instrument_type": itype, "fields": fields}
        inv_report = _invariant_check(invariant_input)
        receipt["invariant_check"] = _invariant_report_to_dict(inv_report)
        if inv_report.n_hard_violations > 0:
            sys.stderr.write(
                "extract_instrument.py: invariant_checker found hard violations: "
                + "; ".join(v.reason for v in inv_report.violations if v.stake == "hard")
                + "\n"
            )
            print(json.dumps(receipt, indent=2 if args.pretty else None))
            return 1

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
            # Using locals() avoids ruff F823 on the unbound-name path.
            _doc_text = locals().get("doc_text") or _ev_load_doc_text(_Path(args.source_doc))
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
            receipt["cross_check"] = {
                "n_demotions": n_demotions,
                "per_field": per_field_cross,
            }

    # attention_needed_fields surfaces the union of fields the dispatching
    # agent should escalate (backward verification, founder review).
    # Includes low/medium-confidence fields + any soft invariant warnings
    # + unverifiable evidence fields.
    attention_fields = set(low_confidence)
    if "invariant_check" in receipt:
        for v in receipt["invariant_check"]["violations"]:
            if v["stake"] == "soft":
                attention_fields.add(v["field"])
    if "evidence_verification" in receipt:
        per_field = receipt["evidence_verification"].get("per_field", [])
        for r in per_field:
            if r.get("status") == "unverifiable":
                attention_fields.add(r["field"])
    if "cross_check" in receipt:
        for r in receipt["cross_check"]["per_field"]:
            if r.get("disagreement"):
                attention_fields.add(r["field_name"])
    receipt["attention_needed_fields"] = sorted(attention_fields)

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
