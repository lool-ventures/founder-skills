#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Compute cap_state.json from inputs.json + instruments.json.

cap_state.py is the foundational aggregation step (the canonicalizer). It
reads `inputs.json` and `instruments.json` and produces `cap_state.json` —
the authoritative current cap-table state every math producer consumes.

Per design doc §11 + Gotcha #1, `as_converted_totals.*` is the
**pre-financing** snapshot. It does NOT include new-money financing shares
or new pool top-ups. The YC Company Capitalization denominator
(`safe.company_capitalization_yc_post_money`) binds to this field
precisely because of the no-new-money-in-the-denominator invariant.

v0.5.0 contract additions (cap-table-data-contract §2-§6):
- Warrants land in cap_state.outstanding_warrants[] with the full item shape
  (warrant_id, exercise_price, warrant_type, vested_flag, settlement_type,
  holder_election_choice, anti_dilution_clause, exercise_event_date,
  exercised_flag). Vested warrants pump `warrants_underlying_total` into
  `as_converted_totals.fully_diluted_shares` (per contract §6.1).
- aoa_findings mirrors from inputs to cap_state (read-only).
- outstanding_safes carries mfn_status derived from instruments.safes[].mfn_provision.
- outstanding_options carries plan_type + section_102_trustee_deposit_date
  (matchers + compose_report.flip_specifics read from cap_state, not instruments).
- outstanding_notes carries subtype + governing_law mirrors.
- Founders + common_batches carry common_class + voting_rights_multiple
  (dual-class voting_pct support).
- inputs.preferred_series with dividend_rate_percent or dividend_cumulative
  is hard-rejected with E_DIVIDEND_FIELDS_REMOVED (dividend math out of scope).

Usage:
    python3 cap_state.py --inputs inputs.json --instruments instruments.json \\
        --run-id 20260519T020000Z -o cap_state.json --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

CAP_STATE_SCHEMA_VERSION = "v0.5.0-cap-state"


class CapStateInvariantError(ValueError):
    """Raised when a semantic invariant fails at canonicalization."""


def _check_invariants_preferred_series(preferred: list[dict[str, Any]]) -> None:
    """§4.5 semantic invariants for preferred series + dividend rejection (§6.2).

    Dividend-field violations are aggregated into a single error so a founder
    doesn't have to migrate field-by-field across multiple runs. Other
    invariants (OIP/OCP > 0, CCP <= OCP) remain fail-fast — they're not
    migration-related so aggregation doesn't help.
    """
    # Pass 1: collect ALL dividend-field violations across the entire preferred
    # series list, then raise once with the aggregate.
    dividend_violations: list[str] = []
    for s in preferred:
        sname = s.get("series_name", "?")
        if "dividend_rate_percent" in s and s.get("dividend_rate_percent") is not None:
            dividend_violations.append(f"preferred_series[{sname}].dividend_rate_percent")
        if "dividend_cumulative" in s and s.get("dividend_cumulative") is True:
            dividend_violations.append(f"preferred_series[{sname}].dividend_cumulative=true")
    if dividend_violations:
        err = CapStateInvariantError(
            "E_DIVIDEND_FIELDS_REMOVED: the following removed-in-v0.5.0 fields are present: "
            + "; ".join(dividend_violations)
            + ". Cumulative-preferred dividend math is not modeled in v0.5.0 (waterfall + cumulative dividends "
            "are out of scope). Remove ALL of these fields in one pass; the AoA-extraction handoff surfaces "
            "dividend provisions via inputs.aoa_findings.dividend_provisions_present for counsel review. "
            "See contract §6.2 / §10.1."
        )
        err.violations = dividend_violations  # type: ignore[attr-defined]
        raise err

    for s in preferred:
        # OIP > 0 / OCP > 0 divide-by-zero guard
        if float(s.get("original_issue_price", 0)) <= 0:
            raise CapStateInvariantError(
                f"E_PREFERRED_SERIES_INVALID_PRICE: preferred_series[{s.get('series_name', '?')}].original_issue_price "
                f"must be > 0 (divide-by-zero guard in AD math)."
            )
        if float(s.get("original_conversion_price", 0)) <= 0:
            sname = s.get("series_name", "?")
            raise CapStateInvariantError(
                f"E_PREFERRED_SERIES_INVALID_PRICE: preferred_series[{sname}].original_conversion_price must be > 0."
            )
        # Resolved current_conversion_price must be > 0 (same fallback chain the
        # canonicalizer uses: current -> original -> ocp). A resolved CCP <= 0
        # would silently corrupt the as-converted ratio and blow up AD math.
        ccp = float(
            s.get(
                "current_conversion_price",
                s.get("original_conversion_price", s.get("ocp", 0)),
            )
        )
        if ccp <= 0:
            sname = s.get("series_name", "?")
            raise CapStateInvariantError(
                f"E_PREFERRED_SERIES_INVALID_PRICE: preferred_series[{sname}].current_conversion_price "
                f"resolves to {ccp} (must be > 0). Provide current_conversion_price or original_conversion_price."
            )
        # CCP <= OCP (ratchet only ratchets down)
        ocp = float(s.get("original_conversion_price", 0))
        if ccp > ocp + 1e-9:
            sname = s.get("series_name", "?")
            raise CapStateInvariantError(
                f"E_PREFERRED_SERIES_CCP_ABOVE_OCP: preferred_series[{sname}].current_conversion_price "
                f"({ccp}) > original_conversion_price ({ocp}); AD only ratchets down."
            )


def _check_invariants_warrants(warrants: list[dict[str, Any]]) -> None:
    """§4.5 warrant semantic invariants."""
    for w in warrants:
        wid = w.get("id", "?")
        # Unvested implies no exercise_event_date
        if not w.get("vested_flag", False) and w.get("exercise_event_date") is not None:
            raise CapStateInvariantError(
                f"E_WARRANT_UNVESTED_EXERCISE_DATE: warrants[{wid}] has exercise_event_date set "
                f"but vested_flag=false. Unvested warrants cannot have a pre-round exercise date."
            )
        # Expiration vs exercise
        eed = w.get("exercise_event_date")
        exp = w.get("expiration_date")
        if eed and exp and eed > exp:
            raise CapStateInvariantError(
                f"E_WARRANT_EXERCISE_AFTER_EXPIRATION: warrants[{wid}].exercise_event_date ({eed}) "
                f"is after expiration_date ({exp})."
            )
        # Holder-election declaration
        if w.get("settlement_type") == "holder_election":
            choice = w.get("holder_election_choice")
            if choice not in ("cash", "net_share"):
                raise CapStateInvariantError(
                    f"E_WARRANT_HOLDER_ELECTION_UNSPECIFIED: warrants[{wid}].settlement_type=holder_election "
                    f"but holder_election_choice is not 'cash' or 'net_share' (got {choice!r})."
                )
        # Forbidden settlement variants (§5.1)
        forbidden = {
            "debt_cancellation": "E_WARRANT_DEBT_CANCELLATION_NOT_MODELED",
            "share_for_share_exchange": "E_WARRANT_EXCHANGE_NOT_MODELED",
        }
        st = w.get("settlement_type")
        if st in forbidden:
            raise CapStateInvariantError(
                f"{forbidden[st]}: warrants[{wid}].settlement_type={st!r} is not modeled in v0.5.0."
            )
        # Preferred-stock-series warrant must declare which series it maps to
        # so the pump can route shares + as-converted ratio correctly.
        if w.get("warrant_type") == "preferred_stock_series" and not w.get("preferred_series_id"):
            raise CapStateInvariantError(
                f"E_WARRANT_PREFERRED_SERIES_ID_REQUIRED: warrants[{wid}].warrant_type=preferred_stock_series "
                f"but preferred_series_id is null. Specify which series this warrant exercises into."
            )


def _compute_as_converted_totals(
    founders: list[dict[str, Any]],
    canonical_preferred_series: list[dict[str, Any]],
    canonical_option_pool: dict[str, Any],
    common_batches: list[dict[str, Any]],
    outstanding_warrants: list[dict[str, Any]],
) -> dict[str, int]:
    """Compute pre-financing as-converted totals.

    Per Gotcha #1: this snapshot is what `safe.company_capitalization_yc_post_money`
    binds to. It MUST NOT include new-money financing shares or new
    post-financing pool top-ups. Pre-existing pool (issued + available) IS
    included. Per contract §6.1, vested outstanding warrants are also included.

    All inputs must be in the **canonical cap_state shape** (post-mapping).
    """
    founder_shares = sum(int(f.get("common_shares", 0)) for f in founders)
    batch_shares = sum(int(b.get("shares", 0)) for b in common_batches)
    common_shares = founder_shares + batch_shares

    preferred_as_converted = 0
    for s in canonical_preferred_series:
        shares = int(s.get("shares", 0))
        ocp = float(s.get("original_conversion_price", 1.0))
        ccp = float(s.get("current_conversion_price", ocp))
        if ccp <= 0:
            # Must never reach here: the §4.5 invariant rejects resolved CCP <= 0
            # upstream. Raise rather than silently masking as 1:1.
            raise CapStateInvariantError(
                f"E_PREFERRED_SERIES_INVALID_PRICE: preferred_series[{s.get('series_id', '?')}]"
                f".current_conversion_price resolves to {ccp} (must be > 0)."
            )
        preferred_as_converted += int(round(shares * (ocp / ccp)))

    options_outstanding = int(canonical_option_pool.get("issued_and_outstanding", 0))
    options_available = int(canonical_option_pool.get("available_for_grant", 0))

    # Include vested outstanding warrants in FD per contract §6.1. Unvested
    # warrants are surfaced in cap_state.outstanding_warrants[] but excluded
    # from FD math (matches YC primer narrow company_capitalization per Gotcha #1).
    warrants_underlying_total = sum(
        int(w.get("shares_underlying", 0))
        for w in outstanding_warrants
        if w.get("vested_flag", False) and not w.get("exercised_flag", False)
    )

    fd = common_shares + preferred_as_converted + options_outstanding + options_available + warrants_underlying_total
    return {
        "common_shares": common_shares,
        "preferred_shares_as_converted": preferred_as_converted,
        "options_outstanding": options_outstanding,
        "options_available": options_available,
        "warrants_underlying_total": warrants_underlying_total,
        "fully_diluted_shares": fd,
    }


def _derive_mfn_status(safe: dict[str, Any]) -> str:
    """Derive mfn_status enum from instruments.safes[i].mfn_provision (§5.2).

    Returns: 'absent' | 'present_unelected' | 'elected' | 'cherry_pick_pending'.
    """
    mfn = safe.get("mfn_provision") or {}
    if not mfn or not mfn.get("present", False):
        return "absent"
    if mfn.get("cherry_pick_attempted"):
        return "cherry_pick_pending"
    if mfn.get("elected"):
        return "elected"
    return "present_unelected"


def _build_outstanding_options(
    grants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build outstanding_options[] from instruments.option_grants[].

    Carries plan_type + section_102_trustee_deposit_date + strike_price +
    grant_date through to cap_state, so rule_audit matchers +
    compose_report.flip_specifics + counsel_packet all read from a single
    canonical location (cap_state.outstanding_options[*]).
    """
    out = []
    for g in grants:
        granted = int(g.get("shares_granted", 0))
        vested = int(g.get("shares_vested_to_date", 0))
        exercised = int(g.get("shares_exercised", 0))
        unvested = max(0, granted - vested)
        out.append(
            {
                "grant_id": g["id"],
                "holder_id": g.get("holder_id", ""),
                "shares_vested_to_date": vested,
                "shares_exercised": exercised,
                "shares_outstanding_unvested": unvested,
                "plan_type": g.get("plan_type", "nso"),
                "section_102_trustee_deposit_date": g.get("section_102_trustee_deposit_date"),
                "strike_price": g.get("strike_price"),
                "grant_date": g.get("grant_date"),
                "vesting": g.get("vesting"),
                "source_doc": g.get("source_document"),
                "extraction_confidence": g.get("extraction_confidence"),
            }
        )
    return out


def _build_outstanding_safes(safes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(safes):
        investor = s.get("investor_name") or f"index {i}"
        for field, hint in [
            ("id", "add 'id' (a unique string key for this SAFE, e.g. 'safe_seed_1')"),
            ("purchase_amount", "add 'purchase_amount' (the dollar amount invested, e.g. 500000)"),
            ("issuance_date", "add 'issuance_date' (ISO date the SAFE was signed, e.g. '2024-01-15')"),
        ]:
            if field not in s:
                raise CapStateInvariantError(
                    f"E_SAFE_MISSING_FIELD: safes[{i}] (investor '{investor}') is missing required field "
                    f"'{field}'. Remedy: {hint}."
                )
        out.append(
            {
                "safe_id": s["id"],
                "investor_name": s.get("investor_name"),
                "purchase_amount": s["purchase_amount"],
                "issuance_date": s["issuance_date"],
                "mfn_status": _derive_mfn_status(s),
                "source_doc": s.get("source_document"),
                "extraction_confidence": s.get("extraction_confidence"),
            }
        )
    return out


def _build_outstanding_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, n in enumerate(notes):
        investor = n.get("investor_name") or f"index {i}"
        for field, hint in [
            ("id", "add 'id' (a unique string key for this note, e.g. 'note_seed_1')"),
            ("principal", "add 'principal' (the principal amount of the note, e.g. 250000)"),
            ("issuance_date", "add 'issuance_date' (ISO date the note was issued, e.g. '2024-03-01')"),
        ]:
            if field not in n:
                raise CapStateInvariantError(
                    f"E_NOTE_MISSING_FIELD: notes[{i}] (investor '{investor}') is missing required field "
                    f"'{field}'. Remedy: {hint}."
                )
        out.append(
            {
                "note_id": n["id"],
                "investor_name": n.get("investor_name"),
                "principal": n["principal"],
                "issuance_date": n["issuance_date"],
                "subtype": n.get("subtype", "convertible_note"),
                "governing_law": n.get("governing_law"),
                "source_doc": n.get("source_document"),
                "extraction_confidence": n.get("extraction_confidence"),
            }
        )
    return out


def _build_outstanding_warrants(warrants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build outstanding_warrants[] from instruments.warrants[].

    Maps `id` -> `warrant_id` for cap_state convention. Carries the full
    item shape so rule_audit matchers, compose_report, visualize/explore,
    and the run_scenario.py pre-round pump can all read from cap_state.
    """
    out = []
    for i, w in enumerate(warrants):
        for field, hint in [
            ("id", "add 'id' (a unique string key for this warrant, e.g. 'warrant_1')"),
            ("shares_underlying", "add 'shares_underlying' (shares the warrant exercises into)"),
            ("exercise_price", "add 'exercise_price' (per-share exercise/strike price)"),
            ("warrant_type", "add 'warrant_type' (e.g. 'common_stock' or 'preferred_stock_series')"),
            ("issuance_date", "add 'issuance_date' (ISO date the warrant was issued)"),
            ("settlement_type", "add 'settlement_type' (e.g. 'physical', 'net_share', 'holder_election')"),
        ]:
            if field not in w:
                raise CapStateInvariantError(
                    f"E_WARRANT_MISSING_FIELD: warrants[{i}] (id '{w.get('id', f'index {i}')}') is missing "
                    f"required field '{field}'. Remedy: {hint}."
                )
        out.append(
            {
                "warrant_id": w["id"],
                "investor_name": w.get("investor_name"),
                "shares_underlying": int(w["shares_underlying"]),
                "exercise_price": float(w["exercise_price"]),
                "warrant_type": w["warrant_type"],
                "preferred_series_id": w.get("preferred_series_id"),
                "vested_flag": bool(w.get("vested_flag", False)),
                "vesting": w.get("vesting"),
                "issuance_date": w["issuance_date"],
                "expiration_date": w.get("expiration_date"),
                "origin": w.get("origin"),
                "settlement_type": w["settlement_type"],
                "holder_election_choice": w.get("holder_election_choice"),
                "anti_dilution_clause": w.get("anti_dilution_clause"),
                "exercise_event_date": w.get("exercise_event_date"),
                "exercised_flag": bool(w.get("exercised_flag", False)),
                "source_doc": w.get("source_document"),
                "extraction_confidence": w.get("extraction_confidence"),
            }
        )
    return out


def _build_aoa_findings_mirror(inputs: dict[str, Any]) -> dict[str, Any]:
    """Mirror inputs.aoa_findings to cap_state.aoa_findings (§2.1 / §3.4).

    Reads from inputs.aoa_findings (the canonical source). Soft-default to
    empty findings when absent. Never mutated downstream; cap_state.py is
    the only writer.
    """
    src = inputs.get("aoa_findings") or {}
    return {
        "pay_to_play_detected": bool(src.get("pay_to_play_detected", False)),
        "drag_along_threshold_pct": src.get("drag_along_threshold_pct"),
        "section_102_plan_reference": src.get("section_102_plan_reference"),
        "ratchet_anti_dilution_detected": bool(src.get("ratchet_anti_dilution_detected", False)),
        "liquidation_preference_above_1x": src.get("liquidation_preference_above_1x"),
        "participation_present": src.get("participation_present"),
        "dividend_provisions_present": src.get("dividend_provisions_present"),
        "protective_provisions_below_75_pct": src.get("protective_provisions_below_75_pct"),
        "bring_along_threshold_pct": src.get("bring_along_threshold_pct"),
    }


def _canonicalize_common_class(holder: dict[str, Any]) -> dict[str, Any]:
    """Apply dual-class soft defaults (§10.2.5)."""
    cls = holder.get("common_class") or "class_a"
    vrm_raw = holder.get("voting_rights_multiple")
    vrm = float(vrm_raw) if vrm_raw is not None else 1.0
    return {
        **holder,
        "common_class": cls,
        "voting_rights_multiple": vrm,
    }


def build_cap_state(
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    *,
    currency: str = "USD",
) -> dict[str, Any]:
    """Build cap_state.json content (no metadata.run_id; writer injects).

    Hard-rejects v0.4.x dividend fields. Runs §4.5 semantic invariants on
    preferred_series + warrants before assembling the canonical state.
    """
    founders = inputs.get("founders", []) or []
    preferred_series = inputs.get("preferred_series", []) or []
    option_pool = inputs.get("option_pool", {}) or {}
    common_batches = inputs.get("common_batches", []) or []
    warrants_raw = instruments.get("warrants", []) or []

    # Invariants (§4.5)
    _check_invariants_preferred_series(preferred_series)
    _check_invariants_warrants(warrants_raw)

    canonical_founders = [
        _canonicalize_common_class(
            {
                "name": f["name"],
                "founder_id": f.get("founder_id", f"founder_{i:03d}"),
                "common_shares": int(f.get("common_shares", 0)),
                "vesting": f.get("vesting"),
                "common_class": f.get("common_class"),
                "voting_rights_multiple": f.get("voting_rights_multiple"),
            }
        )
        for i, f in enumerate(founders, start=1)
    ]
    # Founder-shares invariant (§4.5)
    if founders and sum(f["common_shares"] for f in canonical_founders) <= 0:
        raise CapStateInvariantError(
            "E_FOUNDER_SHARES_REQUIRED: at least one founder is declared but total common_shares across founders is 0."
        )

    canonical_batches = [_canonicalize_common_class(b) for b in common_batches]

    canonical_preferred = [
        {
            "series_id": s.get("series_id", s["series_name"].lower().replace(" ", "_")),
            "series_name": s["series_name"],
            "shares": int(s["shares"]),
            "original_issue_price": float(s.get("original_issue_price", s.get("oip", 0))),
            "original_conversion_price": float(s.get("original_conversion_price", s.get("ocp", 0))),
            "current_conversion_price": float(
                s.get(
                    "current_conversion_price",
                    # Third slot (ocp alias) is unreachable: OCP > 0 is
                    # validated above before this dict is built.
                    s.get("original_conversion_price", s.get("ocp", 0)),
                )
            ),
            "issuance_date": s["issuance_date"],
            "liquidation_preference_multiple": float(s.get("liquidation_preference_multiple", 1.0)),
            "liquidation_preference_type": s.get("liquidation_preference_type", "non_participating"),
            "participation_cap_multiple": s.get("participation_cap_multiple"),
            "anti_dilution_protection": s.get("anti_dilution_protection", "none"),
            "ad_trigger_basis": s.get("ad_trigger_basis", "original_issue_price"),
            "ad_a_denominator_basis": s.get(
                "ad_a_denominator_basis",
                "nvca_broad" if s.get("anti_dilution_protection") == "broad_based_weighted_average" else "nvca_narrow",
            ),
            "ad_cp2_floor": s.get("ad_cp2_floor"),
            "ad_carve_outs": s.get("ad_carve_outs", "nvca_default"),
            "pro_rata_rights": bool(s.get("pro_rata_rights", False)),
            **({"extraction_provenance": s["extraction_provenance"]} if "extraction_provenance" in s else {}),
        }
        for s in preferred_series
    ]
    canonical_option_pool = {
        "plan_type": option_pool.get("plan_type", "nso"),
        "authorized": int(option_pool.get("authorized", 0)),
        "issued_and_outstanding": int(option_pool.get("issued", 0)),
        "exercised_and_outstanding": int(option_pool.get("exercised", 0)),
        "available_for_grant": int(option_pool.get("unallocated", 0)),
        "expired_or_forfeited": int(option_pool.get("expired_or_forfeited", 0)),
    }

    outstanding_warrants = _build_outstanding_warrants(warrants_raw)

    outstanding_options = _build_outstanding_options(instruments.get("option_grants", []) or [])
    outstanding_safes = _build_outstanding_safes(instruments.get("safes", []) or [])
    outstanding_notes = _build_outstanding_notes(instruments.get("convertible_notes", []) or [])
    aoa_findings_mirror = _build_aoa_findings_mirror(inputs)

    # W_AOA_ONLY_NO_INSTRUMENTS — AoA-only engagement detection (§6.0). When all
    # instruments arrays are empty AND aoa_findings has actual data, downstream
    # consumers (compose_report, rule_audit) surface this as a banner + a
    # "no scenarios runnable" sentinel.
    no_instruments = not (outstanding_options or outstanding_safes or outstanding_notes or outstanding_warrants)
    aoa_has_data = any(v is not None and v is not False for v in aoa_findings_mirror.values())
    warnings_list: list[str] = []
    if no_instruments and aoa_has_data:
        warnings_list.append("W_AOA_ONLY_NO_INSTRUMENTS")

    # v0.5.0 Q7: warn on non-1.0 preferred VRM. The math doesn't model non-1.0
    # preferred voting (§6.5 simplification); surface a warning so counsel
    # knows preferred voting was passed through as data-only, not as math.
    for s in preferred_series:
        vrm = s.get("voting_rights_multiple")
        if vrm is not None and float(vrm) != 1.0:
            warnings_list.append("W_PREFERRED_VOTING_NON_UNITY_NOT_MODELED")
            break

    cap_state: dict[str, Any] = {
        "as_of_date": inputs.get("analysis_date", ""),
        "currency": currency,
        "founders": canonical_founders,
        "common_batches": canonical_batches,
        "preferred_series": canonical_preferred,
        **({"cap_table_history": inputs["cap_table_history"]} if "cap_table_history" in inputs else {}),
        "option_pool": canonical_option_pool,
        "outstanding_options": outstanding_options,
        "outstanding_safes": outstanding_safes,
        "outstanding_notes": outstanding_notes,
        "outstanding_warrants": outstanding_warrants,
        "aoa_findings": aoa_findings_mirror,
        "as_converted_totals": _compute_as_converted_totals(
            canonical_founders, canonical_preferred, canonical_option_pool, canonical_batches, outstanding_warrants
        ),
        "metadata": {
            "produced_by": "cap_state.py",
            "source_inputs": ["inputs.json", "instruments.json"],
            "company_name": inputs.get("company_name"),
        },
        **({"warnings": warnings_list} if warnings_list else {}),
    }
    return cap_state


def _print_pretty(receipt: dict[str, Any], data: dict[str, Any]) -> None:
    """Human-readable summary to stderr."""
    fd = data["as_converted_totals"]["fully_diluted_shares"]
    sys.stderr.write(f"cap_state written: {receipt['path']} ({receipt['bytes']:,} bytes)\n")
    sys.stderr.write(f"  founders: {len(data['founders'])}\n")
    sys.stderr.write(f"  preferred series: {len(data['preferred_series'])}\n")
    sys.stderr.write(
        f"  outstanding SAFEs: {len(data['outstanding_safes'])} | "
        f"notes: {len(data['outstanding_notes'])} | "
        f"warrants: {len(data['outstanding_warrants'])}\n"
    )
    sys.stderr.write(f"  option grants: {len(data['outstanding_options'])}\n")
    sys.stderr.write(f"  pre-financing fully-diluted shares: {fd:,}\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True, help="Path to inputs.json")
    p.add_argument("--instruments", required=True, help="Path to instruments.json")
    p.add_argument("--run-id", required=True, help="Run identifier for metadata")
    p.add_argument("-o", "--output", required=True, help="Output cap_state.json path")
    p.add_argument("--currency", default="USD", help="Currency code (default USD)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON + stderr summary")
    args = p.parse_args()

    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)

    try:
        cap_state = build_cap_state(inputs, instruments, currency=args.currency)
    except CapStateInvariantError as e:
        sys.stderr.write(f"cap_state.py: invariant violation: {e}\n")
        return 1

    schema = load_schema(os.path.join(_SCHEMA_DIR, "cap_state.schema.json"))

    try:
        receipt = write_artifact(
            data=cap_state,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
            schema_version=CAP_STATE_SCHEMA_VERSION,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"cap_state.py: schema validation failed: {e}\n")
        return 1

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        _print_pretty(receipt, cap_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
