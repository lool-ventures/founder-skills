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
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _artifact_io  # type: ignore[import-not-found]  # noqa: E402
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

CAP_STATE_SCHEMA_VERSION = "v0.5.0-cap-state"

# Phase-3 readiness inventory (DEFERRED — see `_cap_table_schema_validator.py` and the cap-table
# hardening notes). Keys that producers legitimately READ off inputs/instruments objects but that are
# NOT declared schema properties. Today the schemas leave `additionalProperties` unset (and the
# hand-rolled validator can't enforce it anyway), so unknown keys pass silently. WHEN
# `additionalProperties: false` is eventually enforced (Phase 3), every key below must first become a
# declared schema property (or a documented exception) — otherwise reject-mode would fail valid inputs.
# Recording it here (git-tracked + test-locked, see test_intentional_non_schema_keys_*) is the
# down-payment that makes Phase 3 a mechanical follow-through. NOT exhaustive: a full producer-wide
# sweep (safe_conversion/note_conversion/warrant_exercise/priced_round/freeform_mapper/extractors) is a
# Phase-3 prerequisite. Underscore-prefixed in-memory shadow keys (priced_round `_mfn_*`) are never
# persisted to a validated file, so they are intentionally excluded.
_INTENTIONAL_NON_SCHEMA_KEYS: dict[str, frozenset[str]] = {
    "preferred_series": frozenset({"oip", "ocp", "anti_dilution", "voting_rights_multiple"}),
    "founders": frozenset({"vesting"}),
    "option_pool": frozenset({"exercised", "expired_or_forfeited"}),
    "warrants": frozenset({"exercised_flag"}),
}


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
    for i, g in enumerate(grants):
        # TYPED, like every sibling builder. `"grant_id": g["id"]` below is a subscript, so a grant
        # with no id raised a bare KeyError out of a function whose peers (_build_outstanding_safes /
        # _notes / _warrants) all raise E_*_MISSING_FIELD with a remedy. The caller cannot tell a
        # missing field from a crash, and the founder gets a traceback instead of a sentence.
        if "id" not in g:
            holder = g.get("holder_id") or f"index {i}"
            raise CapStateInvariantError(
                f"E_OPTION_GRANT_MISSING_FIELD: option_grants[{i}] (holder '{holder}') is missing "
                "required field 'id'. Remedy: add 'id' (a unique string key for this grant, e.g. "
                "'grant_001')."
            )
        # Null-tolerant: an explicit null share numeric is schema-equivalent to an absent key for these
        # not-required ["integer","null"] fields; degrade unknown vesting to fully-unvested (conservative).
        granted = int(g.get("shares_granted") or 0)
        vested = int(g.get("shares_vested_to_date") or 0)
        exercised = int(g.get("shares_exercised") or 0)
        unvested = max(0, granted - vested)
        # Proceed-degraded strike: a grant whose strike is genuinely not stated is kept with a null
        # strike (share counts are unaffected — the pool aggregate drives FD; only strike-dependent
        # analysis is deferred). >= 0 (not > 0): a zero/nominal strike is legitimate. bool is not a strike.
        sp = g.get("strike_price")
        if isinstance(sp, (int, float)) and not isinstance(sp, bool) and sp >= 0:
            sp_value: float | None = float(sp)
        else:
            sp_value = None
        out.append(
            {
                "grant_id": g["id"],
                "holder_id": g.get("holder_id", ""),
                "shares_vested_to_date": vested,
                "shares_exercised": exercised,
                "shares_outstanding_unvested": unvested,
                "plan_type": g.get("plan_type", "nso"),
                "section_102_trustee_deposit_date": g.get("section_102_trustee_deposit_date"),
                "strike_price": sp_value,
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
            ("issuance_date", "add 'issuance_date' (ISO date the SAFE was signed, e.g. '2024-01-15')"),
        ]:
            if field not in s:
                raise CapStateInvariantError(
                    f"E_SAFE_MISSING_FIELD: safes[{i}] (investor '{investor}') is missing required field "
                    f"'{field}'. Remedy: {hint}."
                )
        amt = s.get("purchase_amount")
        usable = isinstance(amt, (int, float)) and not isinstance(amt, bool) and amt > 0
        out.append(
            {
                "safe_id": s["id"],
                "investor_name": s.get("investor_name"),
                # Proceed-degraded: a blank/template SAFE with no usable purchase amount is kept as a
                # terms-only, non-convertible entry (the conversion path skips it; the caller warns).
                "purchase_amount": amt if usable else None,
                "convertible": bool(usable),
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
        # principal is NOT required-present (mirror _build_outstanding_safes' purchase_amount): a
        # blank/template note whose amount lives in a Schedule of Lenders is kept terms-only.
        for field, hint in [
            ("id", "add 'id' (a unique string key for this note, e.g. 'note_seed_1')"),
            ("issuance_date", "add 'issuance_date' (ISO date the note was issued, e.g. '2024-03-01')"),
        ]:
            if field not in n:
                raise CapStateInvariantError(
                    f"E_NOTE_MISSING_FIELD: notes[{i}] (investor '{investor}') is missing required field "
                    f"'{field}'. Remedy: {hint}."
                )
        principal = n.get("principal")
        p_usable = isinstance(principal, (int, float)) and not isinstance(principal, bool) and principal > 0
        issuance = n.get("issuance_date")
        i_usable = isinstance(issuance, str) and bool(issuance.strip())
        out.append(
            {
                "note_id": n["id"],
                "investor_name": n.get("investor_name"),
                # Proceed-degraded: a note with no usable principal (blank/template) is kept as a
                # terms-only, non-convertible entry (the conversion path skips it; the caller warns).
                "principal": principal if p_usable else None,
                "convertible": bool(p_usable and i_usable),
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
            ("warrant_type", "add 'warrant_type' (e.g. 'common_stock' or 'preferred_stock_series')"),
            ("issuance_date", "add 'issuance_date' (ISO date the warrant was issued)"),
            ("settlement_type", "add 'settlement_type' (e.g. 'physical', 'net_share', 'holder_election')"),
        ]:
            if field not in w:
                raise CapStateInvariantError(
                    f"E_WARRANT_MISSING_FIELD: warrants[{i}] (id '{w.get('id', f'index {i}')}') is missing "
                    f"required field '{field}'. Remedy: {hint}."
                )
        # Proceed-degraded: a warrant whose strike is genuinely not stated is kept as a partial. Its
        # shares_underlying STILL count in fully-diluted (that is the whole point); only exercise/pump
        # math is unavailable. >= 0 (not > 0): a zero/nominal strike is legitimate for a warrant.
        ep = w.get("exercise_price")
        if isinstance(ep, (int, float)) and not isinstance(ep, bool) and ep >= 0:
            ep_value: float | None = float(ep)
            ep_usable = True
        else:
            ep_value = None
            ep_usable = False
        out.append(
            {
                "warrant_id": w["id"],
                "investor_name": w.get("investor_name"),
                "shares_underlying": int(w["shares_underlying"]),
                "exercise_price": ep_value,
                "exercisable": ep_usable,
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


# S3: investor-entity-as-founder detection. NARROW, high-precision suffix/token matcher —
# `Ventures`/`Capital`/`Fund` only. NOT `Holdings`/`Ltd`/`LLC`/`Partners`/`LP`/`VC` (too common for
# personal/Israeli founder vehicles; e.g. "Acme Holdings Founder Trust", "LP Morgan" must NOT match).
_INVESTOR_ENTITY_RE = re.compile(r"\b(?:Ventures|Capital|Fund)\b", re.IGNORECASE)

# S2: generic placeholder founder-name tell (the model uses these when it's assuming the cap base
# rather than confirming it). Anchored full-match, case-sensitive. Bare "Founder" does NOT match.
_PLACEHOLDER_FOUNDER_RE = re.compile(r"^(?:Co-?)?Founder ?[A-Z0-9]$|^Founder \d+$")


def looks_like_investor_entity(name: str) -> bool:
    """True if a holder name resembles an investment entity (S3 founder-mislabel guard).

    Conservative by design: false-negatives are acceptable (the warning is advisory), but it must
    not false-positive on real/personal founder names or common founder holding vehicles.
    """
    return bool(name) and bool(_INVESTOR_ENTITY_RE.search(name))


def _is_placeholder_founder_name(name: str) -> bool:
    """True if a founder name is a generic placeholder (e.g. 'Founder A') — the S2 assumed-base tell."""
    return bool(name) and bool(_PLACEHOLDER_FOUNDER_RE.match(name.strip()))


# Anti-dilution protection: the canonical inputs field is `anti_dilution_protection` with the
# inputs.schema enum below. The model sometimes writes the intent under the WRONG key
# (`anti_dilution`) or as an abbreviation (`bbwa`); since the schema permits extra keys, that
# silently defaulted AD to "none" and SKIPPED the down-round adjustment a founder explicitly asked
# for. We recover the intent (and flag it) so it is never silently dropped.
_AD_CANON: dict[str, str] = {
    "none": "none",
    "broad_based_weighted_average": "broad_based_weighted_average",
    "narrow_based_weighted_average": "narrow_based_weighted_average",
    "full_ratchet": "full_ratchet",
    # common abbreviations / variants the model writes
    "bbwa": "broad_based_weighted_average",
    "broad_based": "broad_based_weighted_average",
    "broadbased": "broad_based_weighted_average",
    "nbwa": "narrow_based_weighted_average",
    "narrow_based": "narrow_based_weighted_average",
    "narrowbased": "narrow_based_weighted_average",
    "ratchet": "full_ratchet",
    "fullratchet": "full_ratchet",
}


def _ad_token(v: Any) -> str:
    return str(v).strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_anti_dilution(s: dict[str, Any]) -> tuple[str, str | None]:
    """Resolve a preferred series' anti-dilution protection to the canonical enum, tolerating the
    common model slips so a founder's explicit AD intent is NEVER silently dropped to 'none'.
    Returns (canonical_value, warning_or_None). An unrecognized AD value is left 'none' but flagged."""
    name = s.get("series_name", "?")
    canon_field = s.get("anti_dilution_protection")
    if canon_field not in (None, "", "none"):  # canonical field already set to a real value
        mapped = _AD_CANON.get(_ad_token(canon_field))
        if mapped and mapped != canon_field:
            return mapped, (
                f"W_ANTI_DILUTION_NONCANONICAL: preferred series {name!r} anti_dilution_protection="
                f"{canon_field!r} is non-canonical — normalized to {mapped!r}; confirm with counsel."
            )
        return str(canon_field), None
    # canonical absent/none → recover the founder's intent from the wrong key `anti_dilution`
    stray = s.get("anti_dilution")
    if stray in (None, "", "none"):
        return "none", None
    mapped = _AD_CANON.get(_ad_token(stray))
    if mapped and mapped != "none":
        return mapped, (
            f"W_ANTI_DILUTION_NONCANONICAL: preferred series {name!r} specified anti-dilution under the "
            f"wrong key `anti_dilution`={stray!r} (the canonical field is `anti_dilution_protection`) — "
            f"recovered as {mapped!r} so the down-round adjustment is not silently skipped; confirm with counsel."
        )
    return "none", (
        f"W_ANTI_DILUTION_UNRECOGNIZED: preferred series {name!r} has `anti_dilution`={stray!r}, which is not "
        f"a recognized anti-dilution form and is absent from the canonical `anti_dilution_protection` field — "
        f"treated as NONE; confirm whether anti-dilution applies."
    )


# Accepted raw forms for preferred_series[].ad_carve_outs (inputs.schema.json ~:89): the
# canonical scalar plus the two list shapes the plural key name invites a model to write.
_AD_CARVE_OUTS_ACCEPTED: tuple[Any, ...] = ("nvca_default", [], ["nvca_default"])


def _normalize_ad_carve_outs(s: dict[str, Any]) -> str:
    """Normalize preferred_series[].ad_carve_outs to the canonical scalar `"nvca_default"`.

    The schema key is plural (`ad_carve_outs`) but the value space is a single scalar policy
    marker — only one carve-out bundle is modeled today. inputs.schema.json accepts the
    ergonomic list forms `[]` / `["nvca_default"]` alongside the scalar for exactly that reason;
    this collapses all three to the same scalar so every downstream consumer (rule_audit
    matchers, disclosure, `test_ad_carve_outs_survives_canonicalization`) keeps seeing a plain
    string. Anything else is a genuinely invalid value and is hard-rejected here rather than
    silently coerced.
    """
    raw = s.get("ad_carve_outs", "nvca_default")
    if raw in _AD_CARVE_OUTS_ACCEPTED:
        return "nvca_default"
    raise CapStateInvariantError(
        f"E_INVALID_AD_CARVE_OUTS: preferred_series[{s.get('series_name', '?')}].ad_carve_outs="
        f"{raw!r} is not a recognized value. Accepted forms: the scalar 'nvca_default', or the "
        "list forms [] / ['nvca_default'] (both normalize to 'nvca_default')."
    )


# A1: relative-ppm threshold for the FD reconciliation residual. 1000 ppm = 0.1% — comfortably above
# legitimate multi-series conversion-ratio rounding (a real Carta export's delta was ~3 ppm) and well below
# a genuine dropped-holder divergence (~%). RELATIVE so it scales with cap-table size.
_FD_RECONCILE_PPM_THRESHOLD = 1000


def _check_unique_ids(arrays: list[tuple[str, str, list[dict[str, Any]]]]) -> None:
    """Every id-bearing array must have distinct ids. Checked ONCE, here, for all of them.

    WHY HERE AND NOT AT EACH CONSUMER. Ids key the per-instrument outputs across this skill --
    `per_safe`, `per_note`, `results_by_id`, `cp1_snapshots`, the founder breakdown, rule_audit's
    gating map. Every one of those is `map[thing["id"]] = row`, so a repeated id silently drops a row
    while the totals keep counting it. Guarding them one at a time was tried and does not work: two
    consumers were fixed in separate commits and SIX more were still collapsing, because the
    invariant belongs to the ARTIFACT, not to whichever function happens to read it next. This is the
    one place every array is canonicalized, so it is the one place the invariant can be stated once
    and hold for consumers nobody has written yet.

    Measured, with no duplicate typed by anyone: two preferred series named "Series A" and "series a"
    both DERIVE `series_id` "series_a" (see the canonicalization below), and the anti-dilution
    snapshot then runs both series against one CP1 -- a ~5 percentage-point swing in founder
    ownership with `completeness: "full"` and zero blockers. Two notes sharing an id reported
    720,000 shares where the truth was 1,120,000.

    A schema `uniqueItems` cannot stand in for this: `_cap_table_schema_validator.py` implements only
    type/enum/items/properties/required, so the keyword would be inert, and the derived-id case is
    not expressible in the schema at all -- the collision is created here, after validation.
    """
    for array_name, id_field, rows in arrays:
        seen: dict[Any, int] = {}
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = row.get(id_field)
            if rid is None or rid == "":
                continue
            if rid in seen:
                raise CapStateInvariantError(
                    f"E_DUPLICATE_ID_IN_CAP_TABLE: {array_name}[{i}] and {array_name}[{seen[rid]}] "
                    f"share {id_field} {rid!r}. Ids key the per-item outputs, so a repeat reports one "
                    f"row for two items while both still count toward the totals -- the summary and "
                    f"the detail would disagree with no warning. Remedy: give each entry in "
                    f"{array_name} a distinct {id_field}."
                    + (
                        " (Note this id may have been DERIVED from the series name, so two series "
                        "whose names differ only in case or spacing collide here without anyone "
                        "typing a duplicate.)"
                        if array_name == "preferred_series"
                        else ""
                    )
                )
            seen[rid] = i


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

    # No-equity-base invariant: an absent equity base used to sail through silently
    # (the E_FOUNDER_SHARES check above only fires when founders are present-but-zero),
    # yielding an all-zero pre-financing snapshot — into which SAFE/note conversions
    # divide (silent corruption). Fire only when ALL FOUR equity-base sources
    # (founders / option_pool / preferred_series / common_batches) are absent AND
    # there are instruments to convert (a present-but-zero pool is fine, and a
    # preferred-only or common-batches-only base is a valid non-zero equity base).
    _has_instruments = bool(
        instruments.get("safes") or instruments.get("convertible_notes") or instruments.get("warrants")
    )
    if not (founders or option_pool or preferred_series or common_batches) and _has_instruments:
        raise CapStateInvariantError(
            "E_NO_EQUITY_BASE: instruments are present but inputs.json has none of founders, "
            "option_pool, preferred_series, or common_batches — the pre-financing snapshot would be "
            "all-zero and conversions would divide into an empty base. Populate at least one equity-base "
            "source before computing cap state (Lane 3: run the freeform producer to fill them from the "
            "sheet)."
        )

    canonical_batches = [_canonicalize_common_class(b) for b in common_batches]

    # Recover anti-dilution intent the model may have written under the wrong key/abbreviation, so a
    # founder's explicit AD request is never silently dropped to 'none' (which would skip the down-round
    # adjustment). Mutate in place so the comprehension + the ad_a_denominator default below read it.
    _ad_warnings: list[str] = []
    for _s in preferred_series:
        _resolved, _note = _resolve_anti_dilution(_s)
        if _note:
            _s["anti_dilution_protection"] = _resolved
            _ad_warnings.append(_note)

    # P5: pricing_unknown AD-none invariant. MUST run AFTER the anti-dilution resolution loop above,
    # not inside `_check_invariants_preferred_series` (which is called before that loop mutates
    # anti_dilution_protection in place). A pricing_unknown series carries a numeric $1.00 sentinel for
    # OIP/OCP/CCP; applying AD math against that sentinel would produce nonsensical (and often
    # spuriously dilutive) results. Checking here — after resolution — means a stray mis-keyed
    # `anti_dilution: "ratchet"` on a pricing_unknown series cannot sneak past this guard by reading the
    # pre-resolution "none" default and then getting flipped to full_ratchet by the loop above. Read
    # `anti_dilution_protection` with the "none" default: the resolution loop only writes the key back
    # when a recovery note fired, so a plain pricing_unknown series may carry no AD key at all.
    for _s in preferred_series:
        if _s.get("pricing_unknown") and _s.get("anti_dilution_protection", "none") != "none":
            raise CapStateInvariantError(
                f"E_PRICING_UNKNOWN_AD_NOT_NONE: preferred_series[{_s.get('series_name', '?')}] has "
                "pricing_unknown=true but anti_dilution_protection resolves to "
                f"{_s.get('anti_dilution_protection', 'none')!r} (must be 'none' — a $1.00 sentinel price "
                "cannot feed anti-dilution math)."
            )

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
            # `or` not `.get(k, default)`: an explicitly-null value must mean "not specified",
            # exactly like an absent key. The authoring skeleton writes `null` for every optional
            # field a founder has not filled in, so a present null is the COMMON case, and treating
            # it as a supplied value shipped a schema-invalid cap state from the documented template.
            "ad_a_denominator_basis": s.get("ad_a_denominator_basis")
            or (
                "nvca_narrow" if s.get("anti_dilution_protection") == "narrow_based_weighted_average" else "nvca_broad"
            ),
            "ad_cp2_floor": s.get("ad_cp2_floor"),
            "ad_carve_outs": _normalize_ad_carve_outs(s),
            "pro_rata_rights": bool(s.get("pro_rata_rights", False)),
            **({"extraction_provenance": s["extraction_provenance"]} if "extraction_provenance" in s else {}),
            # P5: carry the pricing_unknown flag into canonical cap_state.preferred_series. Without this
            # the fixed-key comprehension silently drops it, killing both the rule_audit matcher (task 5)
            # and the founder-facing disclosure banner (task 6) — mirrors the extraction_provenance
            # conditional-spread pattern immediately above.
            **({"pricing_unknown": True} if s.get("pricing_unknown") else {}),
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

    # Checked on the CANONICAL rows, deliberately -- `preferred_series` ids are derived here when the
    # document does not state one, so checking the raw input would miss exactly the case a founder
    # cannot see coming.
    #
    # NOTE THE PER-ARRAY KEY NAMES. The canonical row RENAMES the input's `id` to `safe_id` /
    # `note_id` / `warrant_id` / `grant_id`, so a check written against `"id"` silently matches
    # nothing and passes. Measured while writing this: the notes row read `"id"` and the duplicate
    # sailed through while the other five were caught. `test_cap_state_rejects_duplicate_ids`
    # exercises every array for exactly that reason -- a uniqueness check that inspects a field name
    # nothing carries is the vacuous-guard failure this repo keeps finding.
    _check_unique_ids(
        [
            ("founders", "founder_id", canonical_founders),
            ("preferred_series", "series_id", canonical_preferred),
            ("option_grants", "grant_id", outstanding_options),
            ("safes", "safe_id", outstanding_safes),
            ("convertible_notes", "note_id", outstanding_notes),
            ("warrants", "warrant_id", outstanding_warrants),
        ]
    )

    # W_AOA_ONLY_NO_INSTRUMENTS — AoA-only engagement detection (§6.0). When all
    # instruments arrays are empty AND aoa_findings has actual data, downstream
    # consumers (compose_report, rule_audit) surface this as a banner + a
    # "no scenarios runnable" sentinel.
    no_instruments = not (outstanding_options or outstanding_safes or outstanding_notes or outstanding_warrants)
    aoa_has_data = any(v is not None and v is not False for v in aoa_findings_mirror.values())
    warnings_list: list[str] = []
    warnings_list.extend(_ad_warnings)  # anti-dilution recovery notes (never silently dropped)
    if no_instruments and aoa_has_data:
        warnings_list.append("W_AOA_ONLY_NO_INSTRUMENTS")

    # P5: at least one preferred series has unconfirmed pricing (numeric $1.00 sentinel,
    # AD forced to 'none' by the invariant above). Surface so the report/counsel-packet
    # disclose the assumed 1:1 conversion ratio + un-modeled AD/liquidation preference.
    if any(s.get("pricing_unknown") for s in preferred_series):
        warnings_list.append("W_PRICING_UNKNOWN")

    # A SAFE whose purchase_amount is absent or non-positive (e.g. a blank/template) is kept as a
    # terms-only, non-convertible entry by _build_outstanding_safes. Warn here so the report and
    # downstream consumers know conversion math was skipped for that instrument.
    if any(s.get("convertible") is False for s in outstanding_safes):
        warnings_list.append("W_SAFE_PURCHASE_AMOUNT_MISSING")

    # STALE CONVERSION PRICE. A series whose history records a prior anti-dilution adjustment, while
    # its current conversion price still equals its ORIGINAL, is contradictory: the adjustment either
    # did not happen or was never written back. Emitted here, at cap-state build, because it is a
    # property of the cap state alone.
    #
    # The solver has carried this check for a long time and it could not fire in practice: it sits
    # behind three unrelated gates -- the round must have anti-dilution protection, the series must be
    # protected, and the new price must be below the trigger -- so a founder was told only if they
    # happened to be closing a down round with protected preferred. Checking it where the state is
    # built removes all three gates. The PREDICATE is SHARED (`_artifact_io`), never copied: the
    # build-time, load-time and solver-time answers must not be free to diverge.
    for _sid in _artifact_io.stale_ccp_series_ids(canonical_preferred, inputs.get("cap_table_history") or []):
        _s = next((x for x in canonical_preferred if x.get("series_id") == _sid), {})
        warnings_list.append(
            _artifact_io.stale_ccp_warning(
                _sid, _s.get("current_conversion_price"), _s.get("original_conversion_price")
            )
        )

    # Mirror for notes: a note with no usable principal/issuance is kept terms-only, non-convertible
    # by _build_outstanding_notes. Warn so the report + downstream know its conversion math was skipped.
    if any(n.get("convertible") is False for n in outstanding_notes):
        warnings_list.append("W_NOTE_PRINCIPAL_MISSING")

    # A warrant whose strike is genuinely not stated is kept non-exercisable by _build_outstanding_warrants
    # (its shares STILL count in fully-diluted; only exercise/pump math is unavailable). Warn so the report
    # and downstream know the strike must be confirmed before any exercise math.
    if any(w.get("exercisable") is False for w in outstanding_warrants):
        warnings_list.append("W_WARRANT_EXERCISE_PRICE_MISSING")

    # An option grant whose strike is genuinely not stated is kept with a null strike (share counts are
    # unaffected — the pool aggregate drives FD). Warn so the report + downstream know strike-dependent
    # analysis is pending confirmation.
    if any(o.get("strike_price") is None for o in outstanding_options):
        warnings_list.append("W_OPTION_GRANT_STRIKE_MISSING")

    # v0.5.0 Q7: warn on non-1.0 preferred VRM. The math doesn't model non-1.0
    # preferred voting (§6.5 simplification); surface a warning so counsel
    # knows preferred voting was passed through as data-only, not as math.
    for s in preferred_series:
        vrm = s.get("voting_rights_multiple")
        if vrm is not None and float(vrm) != 1.0:
            warnings_list.append("W_PREFERRED_VOTING_NON_UNITY_NOT_MODELED")
            break

    # S3: a founder whose name resembles an investment entity is likely mis-classified (advisory).
    # The suffix match is the sole trigger; founder co-investment (founder name also an investor_name)
    # is a normal Israeli pattern and must NOT fire this on its own.
    if any(looks_like_investor_entity(f.get("name", "")) for f in founders):
        warnings_list.append("W_FOUNDER_LOOKS_LIKE_INVESTOR")

    # S2 / Issue B: the cap base is treated as ASSUMED unless the model affirmatively confirms it.
    # DEFAULT-TO-ASSUMED: any engagement with an equity base (founders / common / preferred / option
    # pool) warns unless metadata.cap_base_source == "confirmed". This flips the compliance burden to
    # the SAFE side — a model that skips the cap-base gate, uses the founder's real inline names, and
    # never sets a flag now still surfaces the "DIRECTIONAL, not founder-confirmed" caveat, instead of
    # the prior behavior where only generic placeholder names (the model's assume-tell) tripped it.
    # Lane 3 stamps cap_base_source="confirmed" in the freeform emit (the sheet is the source of truth),
    # so it is exempt by construction. No equity base → nothing to assume → silent.
    cap_base_source = (inputs.get("metadata") or {}).get("cap_base_source")
    _has_equity_base = bool(founders or common_batches or preferred_series or option_pool)
    if cap_base_source != "confirmed" and (cap_base_source == "assumed" or _has_equity_base):
        warnings_list.append("W_CAP_BASE_ASSUMED")

    # A confirmed base whose provenance is NOT the deterministic mapper's marker was model-built (Lane-1/2/4
    # hand-build / vision) — flag it so a hand-built base can't masquerade as verified. The marker is set
    # only by freeform_mapper (machine-set), so its ABSENCE is the trustworthy signal (no model self-report
    # needed). Mutually exclusive with W_CAP_BASE_ASSUMED, which requires cap_base_source != "confirmed".
    cap_base_provenance = (inputs.get("metadata") or {}).get("cap_base_provenance")
    if cap_base_source == "confirmed" and _has_equity_base and cap_base_provenance != "deterministic_mapped":
        warnings_list.append("W_CAP_BASE_RECONSTRUCTED")

    # B3: an image-only PDF (no text layer) read by raw model vision under-extracts dense tables silently.
    # The pdf-probe sets metadata.extraction_mode="vision_image_pdf"; surface a low-confidence warning so
    # the structured artifacts carry the same caveat the narrative does (the run still proceeds — degraded
    # but honest, per the project's proceed-with-warning posture).
    if (inputs.get("metadata") or {}).get("extraction_mode") == "vision_image_pdf":
        warnings_list.append("W_VISION_EXTRACTION_LOW_CONFIDENCE")

    # B2: a tracked-changes/redline .docx is an UNSIGNED draft under negotiation. When the founder chose to
    # proceed on the accepted (final-proposed) view, the SKILL stamps metadata.source_markup; surface a
    # warning so the report persists the draft caveat. (The gate's AskUserQuestion is the PRIMARY caveat — it
    # reaches the founder even when there's no cap base and cap_state never runs; this is the report-
    # persistence backstop for full-pipeline runs that DO supply a cap base.)
    # A tracked-changes/redline draft caveat persists from EITHER the inputs.metadata stamp OR the
    # per-instrument source_markup the extractor writes deterministically (belt-and-suspenders: the manual
    # stamp can be skipped, the per-instrument signal cannot).
    _redline = (inputs.get("metadata") or {}).get("source_markup") == "tracked_changes_accepted"
    if not _redline:
        _instr = (instruments.get("safes") or []) + (instruments.get("convertible_notes") or [])
        _redline = any((i or {}).get("source_markup") == "tracked_changes_accepted" for i in _instr)
    if _redline:
        warnings_list.append("W_REDLINE_DRAFT")

    # A1: cross-foot the computed FD against an INDEPENDENT source-stated grand total (e.g. Carta's printed
    # "Totals" row), captured in inputs.stated_totals. A divergence beyond the relative-ppm threshold means
    # a holder/class was likely dropped or mis-entered during a manual rebuild. Suppressible warning.
    _act: dict[str, Any] = _compute_as_converted_totals(
        canonical_founders, canonical_preferred, canonical_option_pool, canonical_batches, outstanding_warrants
    )
    _stated = (inputs.get("stated_totals") or {}).get("fully_diluted")
    if isinstance(_stated, (int, float)) and not isinstance(_stated, bool) and _stated > 0:
        _computed = _act["fully_diluted_shares"]
        _resid = _computed - int(_stated)
        _ppm = round(1_000_000 * _resid / _stated)
        _act["reconciliation"] = {
            "stated_fully_diluted": int(_stated),
            "residual_abs": _resid,
            "residual_ppm": _ppm,
            "source": (inputs.get("stated_totals") or {}).get("source"),
        }
        if abs(_ppm) > _FD_RECONCILE_PPM_THRESHOLD:
            warnings_list.append(
                f"W_FD_RECONCILE_DELTA: computed fully-diluted {_computed:,} vs source-stated "
                f"{int(_stated):,} (Δ {_resid:+,}, {_ppm:+} ppm) exceeds {_FD_RECONCILE_PPM_THRESHOLD} ppm "
                "— a holder/class may be dropped or mis-entered."
            )

    acq = inputs.get("acquisition")
    if isinstance(acq, dict) and acq.get("acquisition_timing") == "pre_round_closed":
        t = float(acq["consideration_pct"])
        pre_fd_excl = int(_act["fully_diluted_shares"])
        c_shares = int(round(t / (1.0 - t) * pre_fd_excl)) if 0.0 < t < 1.0 else 0
        _act["acquisition_consideration_shares"] = c_shares
        _act["fully_diluted_shares"] = pre_fd_excl + c_shares

    # R-5: a base with NO equity holders (0 common AND 0 preferred) but a positive fully-diluted total —
    # i.e. the FD is entirely an option pool — is a confidently-misleading deliverable (the donut, FD, and
    # ownership %s describe an empty company). Flag it INDEPENDENT of cap_base_source: a CONFIRMED empty
    # base is still vacuous. (The real holder base wasn't captured — e.g. a Carta export with 0 issued.)
    if (
        _act.get("common_shares", 0) == 0
        and _act.get("preferred_shares_as_converted", 0) == 0
        and _act.get("fully_diluted_shares", 0) > 0
    ):
        warnings_list.append("W_BASE_VACUOUS")

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
        "as_converted_totals": _act,
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
        # The loud-failure contract (CLAUDE.md, Script Conventions) is FOUR properties, and this
        # producer met three: exit non-zero, a line on stderr, `-o` left untouched. The missing one
        # was the machine-readable diagnostic on STDOUT. Emitting it costs nothing and makes the
        # rejection legible to a caller that reads stdout rather than the terminal.
        #
        # Deliberately NOT registered in test_skill_contract.py::_REJECTING_PAYLOADS: that harness
        # pipes its payload on stdin and this producer takes argv, so every encoding of it exits on
        # argparse or a missing file and satisfies all three of the registry's assertions WITHOUT
        # running the producer -- a false green. Reaching argv-driven producers needs a harness
        # change (seed inputs, assert a stdout marker), which is its own work.
        sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": [str(e)]}}) + "\n")
        sys.stderr.write(f"cap_state.py: invariant violation: {e}\n")
        if args.output:
            sys.stderr.write(f"cap_state.py: {os.path.abspath(args.output)} was left unchanged.\n")
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
        sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": [str(e)]}}) + "\n")
        sys.stderr.write(f"cap_state.py: schema validation failed: {e}\n")
        if args.output:
            sys.stderr.write(f"cap_state.py: {os.path.abspath(args.output)} was left unchanged.\n")
        return 1

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        _print_pretty(receipt, cap_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
