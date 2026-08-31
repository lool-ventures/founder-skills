#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Extraction-only entry mode for the cap-table skill.

Renders a founder-facing instrument-terms report directly from `inputs.json` +
`instruments.json` — no equity base required. This covers the case where a
founder uploads a single financing instrument (a SAFE, note, or warrant) with
no surrounding cap table: there is no founder/pool/preferred equity base, so
`cap_state.py` / `rule_audit.py` / `compose_report.py` (all of which require a
`cap_state.json` built from a real equity base) cannot run.

Workflow contract:

  - Reads ONLY `inputs.json` + `instruments.json`. NEVER reads or requires
    `cap_state.json` / `scenarios.json` / any full-pipeline artifact.
  - No math is performed: no ownership percentages, no dilution, no
    fully-diluted totals, no per-holder cap table. Only the instrument terms
    as extracted are rendered.
  - Output: `report_extraction_only.md` (founder-facing) + a sentinel
    `extraction_only.json` future consumers can detect, plus a
    `coverage_disclosure.json` explaining why full coverage was not
    attempted, plus copies of the two source files so the extraction
    directory is self-contained.

Directory convention: extraction-only writes to `cap-table-{slug}-extraction/`
(single-dash suffix — same naming pin as `-fastassess`; see
`references/sentinel-schema.md`).

Sentinel contract: see `references/sentinel-schema.md` and
`references/schemas/extraction_only.schema.json`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import shutil
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rule_pack import RULE_PACK_VERSION  # noqa: E402

SCHEMA_VERSION = "v0.1.0-cap-table-extraction-only"

# A null field must never read as an affirmative claim of absence — it may only
# mean "not present in this document." This is the single rendering for that
# case; only the SAFE `form` enum values that genuinely encode no-cap-by-design
# get an affirmative "uncapped" string instead (see `_safe_cap_str`).
NEUTRAL_MARKER = "— (not stated in document; confirm)"

# SAFE forms whose null cap fields still IMPLY a cap should have existed
# (extraction gap, not a real no-cap instrument) — these get the neutral
# marker, never "uncapped". The two forms that affirmatively encode "no cap
# by design" (yc_uncapped_mfn, yc_postmoney_discount) are handled separately
# in `_safe_cap_str`, so any form not in either set (including "other" and
# anything off-enum) also falls through to the neutral marker.
_SAFE_CAP_IMPLYING_FORMS = frozenset(
    {
        "yc_postmoney_cap",
        "cap_plus_discount",
        "yc_premoney_cap_only",
        "pre_money_cap_and_discount_legacy",
    }
)
_SAFE_AFFIRMATIVE_UNCAPPED_FORMS = frozenset({"yc_uncapped_mfn", "yc_postmoney_discount"})
assert not (_SAFE_CAP_IMPLYING_FORMS & _SAFE_AFFIRMATIVE_UNCAPPED_FORMS), (
    "a SAFE form cannot both imply a cap and affirmatively encode no-cap"
)


def _money(m: Any) -> str:
    if not isinstance(m, (int, float)) or isinstance(m, bool):
        return "n/a"
    if m >= 1_000_000:
        return f"${m / 1_000_000:.2f}M"
    if m >= 1_000:
        return f"${m / 1_000:,.0f}K"
    return f"${m:,.0f}"


def _annotate(base: str, field: str, ambiguity_map: dict[str, str]) -> str:
    """Append an audit-sourced to-confirm reason next to a null-field render.

    No-op unless `field` is present in `ambiguity_map` (see `--audit`).
    """
    reason = ambiguity_map.get(field)
    if not reason:
        return base
    return f"{base} — {reason}"


def _copy_if_different(src: str, dst: str) -> None:
    """Copy ``src`` -> ``dst`` unless they resolve to the same file — the author may stage
    inputs/instruments inside ``--review-dir`` (the natural location), which would otherwise raise
    ``shutil.SameFileError``. Uses abspath, not ``os.path.samefile`` (which raises when ``dst`` is
    absent)."""
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copyfile(src, dst)


def _str_field(value: Any, field: str, ambiguity_map: dict[str, str]) -> str:
    """Render a string field. A present-with-null value (a partial/blank instrument's field, e.g.
    investor_name/issuance_date) renders the neutral to-confirm marker — never the literal 'None'
    (`.get(k, "n/a")` returns None, not the default, when the key exists with a null value)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return _annotate(NEUTRAL_MARKER, field, ambiguity_map)
    return str(value)


def _discount_str(discount_multiplier: Any, ambiguity_map: dict[str, str] | None = None) -> str:
    """Render a canonical discount_multiplier (0.80 == 20% discount per Gotcha #3).

    A null discount_multiplier is rendered with the neutral marker, not "none"
    — the discount may simply be defined in a document not included here.
    """
    if not isinstance(discount_multiplier, (int, float)) or isinstance(discount_multiplier, bool):
        return _annotate(NEUTRAL_MARKER, "discount_multiplier", ambiguity_map or {})
    pct = (1 - discount_multiplier) * 100
    return f"{pct:.0f}% ({discount_multiplier:.2f}x)"


def _safe_cap_str(post_cap: Any, pre_cap: Any, form: Any, ambiguity_map: dict[str, str]) -> str:
    """Render a SAFE's cap, form-aware for the null case.

    Only `yc_uncapped_mfn` (genuinely uncapped by design) and
    `yc_postmoney_discount` (no cap by design, discount-only) get an
    affirmative "uncapped" string when the cap is null. Every other form
    (cap-implying, `other`, or unknown) renders the neutral marker — a null
    cap there is an extraction gap, not a real absence of a cap.
    """
    if post_cap is not None:
        return f"{_money(post_cap)} (post-money)"
    if pre_cap is not None:
        return f"{_money(pre_cap)} (pre-money)"
    if form in _SAFE_AFFIRMATIVE_UNCAPPED_FORMS:
        return "uncapped (per form)" if form == "yc_uncapped_mfn" else "uncapped — discount-only (per form)"
    # form in _SAFE_CAP_IMPLYING_FORMS, "other", or off-enum/unknown — null cap
    # here is an extraction gap, never affirmed.
    return _annotate(NEUTRAL_MARKER, "valuation_cap", ambiguity_map)


def _load_ambiguity_map(audit_path: str | None) -> dict[str, str]:
    """Best-effort load of `{field: reason}` from an optional `extraction_audit.json`.

    Never raises: a missing path, missing file, unreadable file, invalid JSON,
    or a payload with no usable `ambiguities` list all resolve to `{}`, which
    makes `_annotate` a no-op — F2a's neutral-marker rendering stands
    unchanged. `extraction_audit.json` is produced by `extract_cap_table.py`,
    not the Lane-1 path this renderer usually sits behind, so absence is the
    common case, not an error.
    """
    if not audit_path:
        return {}
    try:
        with open(audit_path) as f:
            data = json.load(f)
    except Exception:
        return {}
    ambiguities = data.get("ambiguities") if isinstance(data, dict) else None
    if not isinstance(ambiguities, list):
        return {}
    result: dict[str, str] = {}
    for item in ambiguities:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        reason = item.get("reason")
        if isinstance(field, str) and isinstance(reason, str) and field not in result:
            result[field] = reason
    return result


def _load_amendment_deltas(audit_path: str | None) -> list[dict[str, str]]:
    """Load an amendment's clause deltas from the extract_instrument receipt / audit file.

    An amendment classifies non-extractable (no math instrument is persisted), so its
    clause-delta content lives only in the receipt's `ambiguities`. When the audit payload
    declares `classified_doc_type == "amendment"`, return each ambiguity's `{field, description}`
    so the renderer can surface an 'Amendments (terms modified)' section instead of an empty
    deliverable. Non-amendment payloads (or a missing/unreadable file) resolve to `[]`.

    Display-only: the deltas are rendered verbatim, not modeled against a base instrument.
    """
    if not audit_path:
        return []
    try:
        with open(audit_path) as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("classified_doc_type") != "amendment":
        return []
    ambiguities = data.get("ambiguities")
    if not isinstance(ambiguities, list):
        return []
    deltas: list[dict[str, str]] = []
    for item in ambiguities:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        # Amendment ambiguities carry the clause delta in `description`; tolerate `reason` too.
        description = item.get("description") or item.get("reason")
        if isinstance(field, str) and isinstance(description, str):
            deltas.append({"field": field, "description": description})
    return deltas


_TERMS_DOC_ITYPES = frozenset({"term_sheet", "option_plan"})

# Per-field verifier status → the Confidence-cell wording. A finding is a to-confirm marker, never a
# block; `fail` (value_in_doc) is stated as fact, not "fabricated" (the 1-2-fail band is dominated by
# correct paraphrases), but it still overrides the sub-agent's self-claimed level. Statuses not listed
# (pass / skipped_synthesized / absent) fall back to the extracted confidence level.
_TERMS_STATUS_CELL = {
    "unverified_no_quote": "no evidence quote — confirm against the document",
    "fail": "value not found in source text — confirm against the document",
    "unverifiable": "not machine-checkable — confirm against the source",
    "skipped_documented_absence": "documented absent — to confirm",
}


def _load_terms_doc(audit_path: str | None) -> dict[str, Any] | None:
    """Load a term_sheet / option_plan extraction from the extract_instrument receipt (or an improvised
    raw hand-off) so the renderer can show a 'Term sheet terms' section instead of an empty deliverable.

    Accepts two shapes: (1) the receipt — `classified_doc_type ∈ TERMS_DOC` + a `terms_doc` payload +
    (optionally) `evidence_verification`/`invariant_check`; (2) the raw hand-off —
    `instrument_type ∈ TERMS_DOC` + top-level `fields`/`confidence` (no verification). Non-terms /
    missing / unreadable → None. Display-only; nothing is modeled.
    """
    if not audit_path:
        return None
    try:
        with open(audit_path) as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    itype: str | None = None
    fields: Any = None
    confidence: Any = {}
    if data.get("classified_doc_type") in _TERMS_DOC_ITYPES and isinstance(data.get("terms_doc"), dict):
        itype = data["classified_doc_type"]
        fields = data["terms_doc"].get("fields")
        confidence = data["terms_doc"].get("confidence") or {}
    elif data.get("instrument_type") in _TERMS_DOC_ITYPES and isinstance(data.get("fields"), dict):
        itype = data["instrument_type"]
        fields = data.get("fields")
        confidence = data.get("confidence") or {}
    if itype is None or not isinstance(fields, dict):
        return None
    status_by_field: dict[str, Any] = {}
    ev = data.get("evidence_verification")
    if isinstance(ev, dict):
        for r in ev.get("per_field", []) or []:
            if isinstance(r, dict) and isinstance(r.get("field"), str):
                status_by_field[r["field"]] = r.get("status")
    invariant_fields: set[str] = set()
    inv = data.get("invariant_check")
    if isinstance(inv, dict):
        for v in inv.get("violations", []) or []:
            if isinstance(v, dict) and isinstance(v.get("field"), str):
                invariant_fields.add(v["field"])
    ambiguities = data.get("ambiguities") if isinstance(data.get("ambiguities"), list) else []
    return {
        "itype": itype,
        "fields": fields,
        "confidence": confidence if isinstance(confidence, dict) else {},
        "status_by_field": status_by_field,
        "invariant_fields": invariant_fields,
        "ambiguities": ambiguities,
    }


def _terms_cell(value: Any, field: str, ambiguity_map: dict[str, str]) -> str:
    """Render one terms-doc value into a markdown table cell (pipe/newline-safe)."""
    if value is None:
        return _annotate(NEUTRAL_MARKER, field, ambiguity_map)
    if isinstance(value, list):
        s = "; ".join(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in value)
    elif isinstance(value, dict):
        # A flat dict (board_composition: {total_directors: 3, ...}) renders as humanized "Key: v"
        # pairs — far more founder-readable than a raw JSON dump. Deeply-nested → compact JSON.
        if value and all(not isinstance(v, (dict, list)) for v in value.values()):
            s = "; ".join(f"{str(k).replace('_', ' ').title()}: {v}" for k, v in value.items())
        else:
            s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _terms_section(terms_doc: dict[str, Any], ambiguity_map: dict[str, str]) -> list[str]:
    label = "Option plan" if terms_doc["itype"] == "option_plan" else "Term sheet"
    lines: list[str] = [f"## {label} terms (as extracted)", ""]
    lines.append(
        "_This document defines prospective / non-binding terms rather than an executed instrument; "
        "nothing here is modeled against a cap base. Terms are rendered exactly as extracted — confirm "
        "any row marked to-confirm against the source document._"
    )
    lines.append("")
    lines.append("| Term | Value | Confidence |")
    lines.append("|---|---|---|")
    confidence = terms_doc["confidence"]
    status_by_field = terms_doc["status_by_field"]
    invariant_fields = terms_doc["invariant_fields"]
    for key, value in terms_doc["fields"].items():
        term = str(key).replace("_", " ").title()
        val_cell = _terms_cell(value, str(key), ambiguity_map)
        status = status_by_field.get(key)
        slot = confidence.get(key)
        level = slot.get("level") if isinstance(slot, dict) else None
        conf_cell = _TERMS_STATUS_CELL.get(status, level or "—") if status in _TERMS_STATUS_CELL else (level or "—")
        if key in invariant_fields:
            conf_cell = f"{conf_cell}; ⚠ fails a cross-field check — confirm"
        lines.append(f"| {term} | {val_cell} | {conf_cell} |")
    lines.append("")
    ambs = [a for a in (terms_doc.get("ambiguities") or []) if isinstance(a, dict)]
    if ambs:
        lines.append("**To confirm:**")
        lines.append("")
        for a in ambs:
            fld = a.get("field") or "term"
            desc = a.get("description") or a.get("reason") or ""
            lines.append(f"- **{fld}** — {desc}")
        lines.append("")
    return lines


def _yes_no(v: Any) -> str:
    return "Yes" if v else "No"


def _safes_table(safes: list[dict[str, Any]], ambiguity_map: dict[str, str]) -> list[str]:
    lines: list[str] = []
    lines.append("| Investor | Purchase Amount | Cap | Discount | Form | MFN | Pro-Rata | Issuance Date |")
    lines.append("|---|---:|---:|---:|---|---|---|---|")
    for s in safes:
        investor = _str_field(s.get("investor_name"), "investor_name", ambiguity_map)
        amt = _money(s.get("purchase_amount"))
        post_cap = s.get("post_money_valuation_cap")
        pre_cap = s.get("pre_money_valuation_cap")
        raw_form = s.get("form")
        cap_str = _safe_cap_str(post_cap, pre_cap, raw_form, ambiguity_map)
        discount = _discount_str(s.get("discount_multiplier"), ambiguity_map)
        form = str(raw_form or "n/a").replace("_", " ")
        mfn = s.get("mfn_provision") or {}
        mfn_str = _yes_no(mfn.get("present")) if isinstance(mfn, dict) else "No"
        pro_rata = s.get("pro_rata_side_letter") or {}
        pro_rata_str = _yes_no(pro_rata.get("present")) if isinstance(pro_rata, dict) else "No"
        issuance_date = _str_field(s.get("issuance_date"), "issuance_date", ambiguity_map)
        lines.append(
            f"| {investor} | {amt} | {cap_str} | {discount} | {form} | {mfn_str} | {pro_rata_str} | {issuance_date} |"
        )
    return lines


def _notes_table(notes: list[dict[str, Any]], ambiguity_map: dict[str, str]) -> list[str]:
    lines: list[str] = []
    lines.append(
        "| Investor | Principal | Cap | Discount | Interest Rate | Maturity Date | Governing Law | Issuance Date |"
    )
    lines.append("|---|---:|---:|---:|---:|---|---|---|")
    for n in notes:
        investor = _str_field(n.get("investor_name"), "investor_name", ambiguity_map)
        principal = _money(n.get("principal"))
        cap = n.get("valuation_cap")
        # Notes have no affirmative no-cap enum (unlike SAFE's `form`) — a null
        # cap is always the neutral marker, never "uncapped".
        cap_str = _money(cap) if cap is not None else _annotate(NEUTRAL_MARKER, "valuation_cap", ambiguity_map)
        discount = _discount_str(n.get("discount_multiplier"), ambiguity_map)
        rate = n.get("annual_interest_rate")
        rate_str = f"{rate * 100:.2f}%" if isinstance(rate, (int, float)) and not isinstance(rate, bool) else "n/a"
        maturity_raw = n.get("maturity_date")
        maturity = (
            maturity_raw if maturity_raw is not None else _annotate(NEUTRAL_MARKER, "maturity_date", ambiguity_map)
        )
        governing_law = n.get("governing_law") or "n/a"
        issuance_date = _str_field(n.get("issuance_date"), "issuance_date", ambiguity_map)
        lines.append(
            f"| {investor} | {principal} | {cap_str} | {discount} | {rate_str} | "
            f"{maturity} | {governing_law} | {issuance_date} |"
        )
    return lines


def _warrants_table(warrants: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("| Investor | Shares Underlying | Exercise Price | Warrant Type | Settlement Type | Issuance Date |")
    lines.append("|---|---:|---:|---|---|---|")
    for w in warrants:
        investor = w.get("investor_name") or "n/a"
        shares = w.get("shares_underlying")
        shares_str = f"{int(shares):,}" if isinstance(shares, (int, float)) and not isinstance(shares, bool) else "n/a"
        exercise_price = w.get("exercise_price")
        exercise_str = (
            f"${exercise_price:,.4f}"
            if isinstance(exercise_price, (int, float)) and not isinstance(exercise_price, bool)
            else "n/a"
        )
        warrant_type = str(w.get("warrant_type", "n/a")).replace("_", " ")
        settlement_type = str(w.get("settlement_type", "n/a")).replace("_", " ")
        issuance_date = w.get("issuance_date", "n/a")
        lines.append(
            f"| {investor} | {shares_str} | {exercise_str} | {warrant_type} | {settlement_type} | {issuance_date} |"
        )
    return lines


def compose_extraction_report(
    *,
    company_name: str,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    run_id_override: str | None = None,
    ambiguity_map: dict[str, str] | None = None,
    amendments: list[dict[str, Any]] | None = None,
    terms_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the extraction-only sentinel + founder-facing markdown.

    `ambiguity_map` is the optional `{field: reason}` enrichment loaded from
    `--audit` (see `_load_ambiguity_map`); omit or pass `{}` for the default
    F2a-only rendering.

    Returns the sentinel payload (matching `extraction_only.schema.json`) with
    two transient keys the CLI extracts before writing the sentinel to disk:
    `_report_md` (the founder-facing markdown) and `_coverage_disclosure`
    (the `coverage_disclosure.json` payload).
    """
    ambiguity_map = ambiguity_map or {}
    amendments = amendments or []
    safes = instruments.get("safes") or []
    notes = instruments.get("convertible_notes") or []
    warrants = instruments.get("warrants") or []

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = run_id_override if run_id_override else now.replace(":", "").replace("-", "")
    slug = company_name.lower().replace(" ", "-").replace("_", "-")

    instruments_summary = {
        "safes": len(safes),
        "convertible_notes": len(notes),
        "warrants": len(warrants),
    }

    required_primitives: list[str] = []
    if safes:
        required_primitives.append("safe_conversion")
    if notes:
        required_primitives.append("note_conversion")
    if warrants:
        required_primitives.append("warrant_exercise")

    sentinel: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "extraction_only",
        "run_id": run_id,
        "company_name": company_name,
        "company_slug": slug,
        "created_at": now,
        "rule_pack_version": RULE_PACK_VERSION,
        "produces_canonical_artifacts": False,
        "note": (
            "Extraction-only mode renders instrument terms as extracted. No equity base "
            "(founders / pool / preferred) was supplied, so no cap_state.json / scenarios.json / "
            "report.json was produced."
        ),
        "instruments_summary": instruments_summary,
        "rerun_hint": (
            "For ownership percentages, dilution, and a full cap table, supply the founder + "
            "pool (and any preferred) equity base and re-run the full cap-table pipeline."
        ),
    }

    # ── Founder-facing markdown ──────────────────────────────────────────────
    md_lines: list[str] = []
    md_lines.append(
        "> ⚠ **Instrument terms only — no cap base modeled.** No ownership %, dilution, or "
        "fully-diluted math was computed; provide the founder/pool cap base for a full "
        "cap-table review."
    )
    md_lines.append("")
    md_lines.append(f"# {company_name} — Instrument Terms")
    md_lines.append("")
    md_lines.append(
        "_Extraction-only mode: instrument terms rendered exactly as extracted, with no "
        "equity base to compute against. Ask for the full review once the founder / pool "
        "cap base is available._"
    )
    md_lines.append("")

    jurisdiction = (inputs.get("jurisdiction") or {}).get("structure")
    analysis_date = inputs.get("analysis_date")
    md_lines.append("## Company")
    md_lines.append("")
    md_lines.append(f"- Jurisdiction: {jurisdiction or 'not specified'}")
    md_lines.append(f"- Analysis date: {analysis_date or 'not specified'}")
    md_lines.append("")

    md_lines.append("## Instrument terms")
    md_lines.append("")

    if safes:
        md_lines.append(f"### SAFEs ({len(safes)})")
        md_lines.append("")
        md_lines.extend(_safes_table(safes, ambiguity_map))
        md_lines.append("")
    if notes:
        md_lines.append(f"### Convertible notes ({len(notes)})")
        md_lines.append("")
        md_lines.extend(_notes_table(notes, ambiguity_map))
        md_lines.append("")
    if warrants:
        md_lines.append(f"### Warrants ({len(warrants)})")
        md_lines.append("")
        md_lines.extend(_warrants_table(warrants))
        md_lines.append("")
    if not safes and not notes and not warrants:
        if amendments:
            md_lines.append("_(no standalone SAFEs, convertible notes, or warrants — see Amendments below)_")
        elif terms_doc:
            md_lines.append("_(no standalone SAFEs, convertible notes, or warrants — see Term sheet terms below)_")
        else:
            md_lines.append("_(no SAFEs, convertible notes, or warrants supplied)_")
            # M-R2-1 backstop: for a terms-doc/amendment upload the receipt IS the content; a silently
            # empty report almost always means the extraction receipt was not passed as --audit.
            md_lines.append("")
            md_lines.append(
                "> ⚠ No instrument content found. If this was a term sheet, option plan, or amendment, "
                "re-run `compose_extraction_report.py` with the `extract_instrument.py` receipt as `--audit`."
            )
        md_lines.append("")

    if terms_doc:
        md_lines.extend(_terms_section(terms_doc, ambiguity_map))

    if amendments:
        md_lines.append("## Amendments (terms modified)")
        md_lines.append("")
        md_lines.append(
            "_This document amends a pre-existing instrument rather than defining a standalone one; "
            "the clause changes below are surfaced as extracted and are NOT modeled against the base "
            "instrument. Supply the original instrument for a full review._"
        )
        md_lines.append("")
        for delta in amendments:
            field = delta.get("field") or "clause"
            description = delta.get("description") or ""
            md_lines.append(f"- **{field}** — {description}")
        md_lines.append("")

    md_lines.append("## What this extraction does NOT cover")
    md_lines.append("")
    md_lines.append("- Ownership percentages, dilution, or fully diluted share totals (no cap base supplied)")
    md_lines.append("- A per-holder capitalization table")
    md_lines.append("- Anti-dilution, MFN cross-instrument resolution, or the rule-audit watchlist")
    md_lines.append("- The counsel-handoff packet")
    md_lines.append("")
    md_lines.append("_Ask for the full review (with the founder + pool cap base supplied) to get all of the above._")
    md_lines.append("")

    sentinel["_report_md"] = "\n".join(md_lines)

    # ── coverage_disclosure.json payload ─────────────────────────────────────
    sentinel["_coverage_disclosure"] = {
        "schema_version": "v0.1-coverage-disclosure",
        "covered": False,
        "computation_method": "extraction_only",
        "counsel_review": True,
        "required_primitives": required_primitives,
        "uncovered_parts": ["equity_base"],
    }

    return sentinel


def _validate_coverage_disclosure(payload: dict[str, Any]) -> list[str]:
    """Check the extraction-only disclosure against the shared closed schema.

    Reuses `write_coverage_disclosure.validate` rather than copying the logic: a fourth copy
    of the rules is exactly the drift surface this consolidation exists to remove.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(here, "..", "references", "schemas", "coverage-disclosure.schema.json")
    spec = importlib.util.spec_from_file_location("_wcd", os.path.join(here, "write_coverage_disclosure.py"))
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    return list(mod.validate(payload, schema))


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True, help="Path to inputs.json (per the inputs schema)")
    p.add_argument("--instruments", required=True, help="Path to instruments.json (per the instruments schema)")
    p.add_argument("--review-dir", required=True, help="Output directory (e.g. cap-table-{slug}-extraction/)")
    p.add_argument("--run-id", default=None, help="Override the run_id in the sentinel (optional)")
    p.add_argument(
        "--audit",
        default=None,
        help=(
            "Optional path to extraction_audit.json (from extract_cap_table.py) or an extract_instrument "
            "receipt. If it parses with an 'ambiguities' list, null fields it names get a to-confirm "
            "annotation; if it declares classified_doc_type=='amendment', the ambiguities are rendered as "
            "an 'Amendments (terms modified)' section. Missing/unreadable/malformed is not an error."
        ),
    )
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.inputs) as f:
        inputs = json.load(f)
    with open(args.instruments) as f:
        instruments = json.load(f)

    company_name_raw = inputs.get("company_name") or inputs.get("company", {}).get("company_name")
    if not company_name_raw:
        print(
            "Warning: company_name not found at top-level or under 'company.company_name'; using 'Unknown'.",
            file=sys.stderr,
        )
        company_name_raw = "Unknown"

    ambiguity_map = _load_ambiguity_map(args.audit)
    amendments = _load_amendment_deltas(args.audit)
    terms_doc = _load_terms_doc(args.audit)

    sentinel = compose_extraction_report(
        company_name=company_name_raw,
        inputs=inputs,
        instruments=instruments,
        run_id_override=args.run_id,
        ambiguity_map=ambiguity_map,
        amendments=amendments,
        terms_doc=terms_doc,
    )

    os.makedirs(args.review_dir, exist_ok=True)

    md_path = os.path.join(args.review_dir, "report_extraction_only.md")
    # Validate BEFORE writing anything. Validating just before the disclosure write left
    # Validate the disclosure payload BEFORE writing anything. This is the third writer of
    # coverage_disclosure.json and was the only one validating nothing -- compose_report.py
    # loads the schema, and the hand-roll route goes through write_coverage_disclosure.py.
    # It runs ahead of the first write on purpose: validating just before the disclosure write
    # left report_extraction_only.md already on disk when the payload was rejected, i.e. a
    # partial output dir, which is what the fleet's reject-without-clobbering contract forbids.
    _disclosure_errors = _validate_coverage_disclosure(sentinel["_coverage_disclosure"])
    if _disclosure_errors:
        print(
            "Error: coverage_disclosure payload does not match its schema: " + "; ".join(_disclosure_errors),
            file=sys.stderr,
        )
        return 1

    with open(md_path, "w") as f:
        f.write(sentinel.pop("_report_md"))
    sentinel["extraction_report_path"] = os.path.abspath(md_path)

    coverage_disclosure = sentinel.pop("_coverage_disclosure")
    coverage_path = os.path.join(args.review_dir, "coverage_disclosure.json")
    with open(coverage_path, "w") as f:
        if args.pretty:
            json.dump(coverage_disclosure, f, indent=2)
        else:
            json.dump(coverage_disclosure, f)

    sentinel_path = os.path.join(args.review_dir, "extraction_only.json")
    with open(sentinel_path, "w") as f:
        if args.pretty:
            json.dump(sentinel, f, indent=2)
        else:
            json.dump(sentinel, f)

    inputs_copy_path = os.path.join(args.review_dir, "inputs.json")
    instruments_copy_path = os.path.join(args.review_dir, "instruments.json")
    _copy_if_different(args.inputs, inputs_copy_path)
    _copy_if_different(args.instruments, instruments_copy_path)

    receipt = {
        "wrote": {
            "extraction_report_md": os.path.abspath(md_path),
            "sentinel_json": os.path.abspath(sentinel_path),
            "coverage_disclosure_json": os.path.abspath(coverage_path),
            "inputs_json": os.path.abspath(inputs_copy_path),
            "instruments_json": os.path.abspath(instruments_copy_path),
        },
        "schema_version": SCHEMA_VERSION,
        "run_id": sentinel["run_id"],
        "company_name": sentinel["company_name"],
        "mode": "extraction_only",
    }
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
