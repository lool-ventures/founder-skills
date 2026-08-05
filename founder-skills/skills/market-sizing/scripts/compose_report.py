#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose market sizing report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./market-sizing-acme-corp/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any, TypeGuard

# Sentinel for corrupt (unparseable) artifact files
_CORRUPT: dict[str, Any] = {"__corrupt__": True}

# Canonical warning severity map — stable API, tested for completeness
WARNING_SEVERITY: dict[str, str] = {
    # "low", not medium: by the time this fires, substitute() has already corrected the text, so the
    # report is clean and what remains is an authoring task. ic-sim / market-sizing / deck-review block
    # strict mode on medium, which would fail a run over an already-fixed issue. The fleet ratchet in
    # test_compose_invariants.py is the gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # High severity — agent must fix before presenting report
    #
    # SIZING_INVALID is high because the failure it catches used to be INVISIBLE. market_sizing.py
    # rejecting its input once meant an exit-0 `{"ok":true}` receipt plus a figure-less stub written
    # over sizing.json; compose then rendered an empty sizing table with no code naming the cause.
    # High keeps it out of ACCEPTIBLE_SEVERITIES, so it cannot be accepted away.
    "SIZING_INVALID": "high",
    # Same class, other producers. `sensitivity.py` / `checklist.py` had the identical
    # exit-0-and-clobber behaviour, and a rejected step surfaced only as a MEDIUM
    # FEW_SENSITIVITY_PARAMS / CHECKLIST_INCOMPLETE — acceptable-away, and naming a
    # symptom rather than the cause.
    "ARTIFACT_INVALID": "high",
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    "CHECKLIST_FAILURES": "high",
    "OVERCLAIMED_VALIDATION": "high",
    "UNVALIDATED_CLAIMS": "high",
    "IMPLAUSIBLE_PCT_SCALE": "high",
    # Medium severity — include in Warnings section of report
    "UNSOURCED_ASSUMPTIONS": "medium",
    "APPROACH_MISMATCH": "medium",
    "TAM_DISCREPANCY": "medium",
    "SAM_DISCREPANCY": "medium",
    "SOM_DISCREPANCY": "medium",
    "CHECKLIST_INCOMPLETE": "medium",
    "FEW_SENSITIVITY_PARAMS": "medium",
    "NARROW_AGENT_ESTIMATE_RANGE": "medium",
    "LOW_CHECKLIST_COVERAGE": "medium",
    "REFUTED_CLAIMS": "medium",
    "REFUTED_MISSING_REASON": "medium",
    "EXISTING_CLAIMS_SHAPE": "medium",
    "CURRENCY_MISMATCH": "medium",
    # An honest "cannot check" where the alternative is a confident wrong answer. When a money
    # input was FX-converted, a founder-stated figure or deck claim carrying no declared currency
    # cannot be compared against it: the divergence would be exactly the exchange rate, and which
    # side is in which currency is not knowable from the data. Declaring
    # founder_stated_inputs_currency / existing_claims_currency restores the real check.
    "COMPARISON_CURRENCY_UNKNOWN": "medium",
    "FOUNDER_VALUE_OVERRIDDEN": "medium",
    # Low severity — informational; do not block under --strict
    "MISSING_OPTIONAL_ARTIFACT": "low",
    "DECK_CLAIM_MISMATCH": "low",
    "PROVENANCE_UNRESOLVED": "low",
    # Marker collision is informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
}

# Only medium-severity codes can be accepted. High-severity = integrity violations.
ACCEPTIBLE_SEVERITIES = {"medium"}

# Quantitative params that should appear in sensitivity analysis if agent_estimate
QUANTITATIVE_PARAMS = {
    "customer_count",
    "arpu",
    "serviceable_pct",
    "target_pct",
    "industry_total",
    "segment_pct",
    "share_pct",
}

REQUIRED_ARTIFACTS = [
    "inputs.json",
    "methodology.json",
    "validation.json",
    "sizing.json",
    "checklist.json",
    "sensitivity.json",
]
OPTIONAL_ARTIFACTS: list[str] = []

# Human-readable parameter names for report presentation
PARAM_LABELS: dict[str, str] = {
    "customer_count": "Customer Count",
    "arpu": "ARPU",
    "serviceable_pct": "Serviceable %",
    "target_pct": "Target Capture %",
    "industry_total": "Industry Total",
    "segment_pct": "Segment %",
    "share_pct": "Market Share %",
    "tam": "TAM",
    "sam": "SAM",
}

# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "IMPLAUSIBLE_PCT_SCALE": "Implausible Percentage Scale",
    "CHECKLIST_FAILURES": "Checklist Failures",
    "OVERCLAIMED_VALIDATION": "Overclaimed Validation",
    "UNVALIDATED_CLAIMS": "Unvalidated Claims",
    "MISSING_OPTIONAL_ARTIFACT": "Missing Optional Artifact",
    "UNSOURCED_ASSUMPTIONS": "Unsourced Assumptions",
    "APPROACH_MISMATCH": "Approach Mismatch",
    "TAM_DISCREPANCY": "TAM Discrepancy",
    "SAM_DISCREPANCY": "SAM Discrepancy",
    "SOM_DISCREPANCY": "SOM Discrepancy",
    "CHECKLIST_INCOMPLETE": "Checklist Incomplete",
    "FEW_SENSITIVITY_PARAMS": "Few Sensitivity Parameters",
    "NARROW_AGENT_ESTIMATE_RANGE": "Narrow Agent-Estimate Range",
    "LOW_CHECKLIST_COVERAGE": "Low Checklist Coverage",
    "REFUTED_CLAIMS": "Refuted Claims",
    "REFUTED_MISSING_REASON": "Refuted Claim Missing Reason",
    "DECK_CLAIM_MISMATCH": "Deck Claim Mismatch",
    "PROVENANCE_UNRESOLVED": "Provenance Unresolved",
    "EXISTING_CLAIMS_SHAPE": "Existing Claims Shape",
    "MARKER_COLLISION": "Marker Collision",
}


def _humanize_param(name: str) -> str:
    """Convert a parameter name to human-readable label."""
    return PARAM_LABELS.get(name, name.replace("_", " ").title())


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


def _fmt_number(value: Any) -> str:
    """Format a numeric value for display (with commas, no unnecessary decimals)."""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
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


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact. Returns None if missing, _CORRUPT if unparseable."""
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return _CORRUPT


def _is_stub(data: dict[str, Any] | None) -> bool:
    """Check if artifact is a stub (intentionally skipped)."""
    return isinstance(data, dict) and data.get("skipped") is True


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list — returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict — returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


def _has_document_materials(inputs: dict[str, Any] | None) -> bool:
    """True when the founder actually supplied a document (deck, model, etc.).

    `materials_provided` is required (artifact-schemas.md). A conversational-only
    run — the founder describing their market in chat, with no upload — sets it
    to `["text"]` per SKILL.md's "Founder provided text, not a file" edge case, or
    leaves it empty. Anything else ("pitch deck", "financial model", "cap table", ...)
    means a real document existed, so deck-attributed language ("the deck stated...")
    is accurate. Used to keep claims-reconciliation copy from crediting a deck that
    was never provided.
    """
    if not isinstance(inputs, dict):
        return False
    materials = _as_list(inputs.get("materials_provided"))
    return any(isinstance(m, str) and m.strip().lower() != "text" for m in materials)


# Process-wide currency label for money formatting, set once per run from the
# artifacts by _set_currency(). A bare "$" on a non-USD analysis is a wrong UNIT
# on the headline number, and a wrong unit in a TAM travels into a deck. Callers
# may still pass currency_code explicitly; the global is only the default, so
# threading a code through every one of the ~30 _fmt_usd call sites (each inside
# a section renderer that has no business knowing about currency) isn't needed.
# Safe as process state because these scripts are single-shot CLIs.
_CURRENCY: str = "USD"


def _resolve_currency(*artifacts: dict[str, Any] | None) -> str:
    """Return the analysis currency code from the first artifact carrying one.

    Checked in the order passed by the caller; falls back to "USD" (the
    back-compat default) when none carry a currency field.
    """
    for artifact in artifacts:
        if isinstance(artifact, dict):
            currency = artifact.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _set_currency(code: str) -> None:
    """Set the process-wide default currency label for _fmt_usd."""
    global _CURRENCY
    _CURRENCY = code.strip().upper() if isinstance(code, str) and code.strip() else "USD"


# Human-readable labels for the declared sizing_basis convention — see
# references/tam-sam-som-methodology.md §5.
_SIZING_BASIS_LABELS: dict[str, str] = {
    "current_year": "Current-year market size",
    "forecast_year": "Forecast-year market size",
    "mixed": "Mixed (current- and forecast-year figures)",
}


def _sizing_basis_label(value: Any) -> str:
    """Human-readable label for sizing_basis.

    Anything outside the three known tokens — including absence — renders as
    "Not declared" rather than defaulting to "current_year". An artifact
    produced before this field existed (or a run that never set it) has a
    genuinely undeclared basis; silently stamping "current_year" on it would
    assert a convention that was not actually in force when the figures were
    sourced.
    """
    if isinstance(value, str) and value in _SIZING_BASIS_LABELS:
        return _SIZING_BASIS_LABELS[value]
    return "Not declared"


def _resolve_sizing_basis(
    sizing: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> str | None:
    """Resolve the raw sizing_basis token.

    sizing.json is the artifact the figures actually came out of and is
    authoritative for which convention was used; inputs.json only carries the
    field at intake (Steps 2-3), so it is the fallback rather than the
    primary source.
    """
    if _usable(sizing):
        val = sizing.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    if _usable(inputs):
        val = inputs.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    return None


def _fmt_usd(value: float | int, currency_code: str | None = None) -> str:
    """Format a number as a compact currency string, scaled with K/M/B suffixes.

    Defaults to the process-wide currency (``_set_currency``), itself defaulting
    to "USD" and rendering a bare "$" prefix. Any other ISO code is tagged as a
    suffix instead (e.g. "1.5M ILS") — a bare "$" would misrepresent a
    non-USD-denominated analysis.
    """
    code = _CURRENCY if currency_code is None else (currency_code or "USD")
    if value < 0:
        return "-" + _fmt_usd(-value, code)
    prefix = "$" if code == "USD" else ""
    suffix = "" if code == "USD" else f" {code}"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.1f}B{suffix}"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}M{suffix}"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:,.1f}K{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def _fmt_param_value(name: str, value: Any) -> str:
    """Unit-aware formatting for a sensitivity parameter's input value.

    The Value column holds the parameter itself, not a market-size figure, so its unit varies:
    percentages (``*_pct``), counts (``*_count``), and currency (everything else, e.g. ``arpu``,
    ``industry_total``). Formatting all three the same way (the old behavior — USD for low/high,
    raw number for base) renders percents and counts as dollars and leaves base inconsistent.
    """
    if not isinstance(value, (int, float)):
        return "—"
    lname = name.lower()
    if lname.endswith("_pct") or "pct" in lname or "percent" in lname or "share" in lname or "rate" in lname:
        return f"{float(value):.2f}".rstrip("0").rstrip(".") + "%"
    if (
        "count" in lname
        or "customers" in lname
        or "users" in lname
        or "establishments" in lname
        or lname.startswith("num_")
        or lname.endswith("_num")
    ):
        return _fmt_number(int(value) if float(value).is_integer() else value)
    return _fmt_usd(float(value))


def _md_safe(text: str) -> str:
    """Escape text for safe markdown table cell interpolation."""
    return text.replace("|", "\\|").replace("\n", " ")


def _fx_conversions(sizing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map money-field name -> its conversion record from `sizing.fx`. Empty when no FX ran."""
    fx = _as_dict(_as_dict(sizing).get("fx"))
    out: dict[str, dict[str, Any]] = {}
    for entry in _as_list(fx.get("conversions")):
        rec = _as_dict(entry)
        field = rec.get("field")
        if isinstance(field, str):
            out[field] = rec
    return out


def _to_analysis_currency(
    stated: float,
    declared: Any,
    target: Any,
    conversions: list[dict[str, Any]],
) -> tuple[float | None, str | None]:
    """Express a founder-stated / deck-claimed figure in the analysis currency.

    Returns (value, reason_it_cannot_be_compared). Exactly one is non-None.

    Only meaningful once FX exists: before it, every figure on the page was in one currency by
    construction and this returned the input unchanged. The undeclared-currency case is
    genuinely undecidable — the founder of an ILS company may state ILS while the researched
    source was USD, so guessing either way manufactures a false positive of the FX rate's
    magnitude. Say so instead.
    """
    # A declared currency is honoured FIRST, before the was-this-field-converted question. The
    # declaration is object-level (one code for all of founder_stated_inputs), so a run that
    # converted `industry_total` but sourced `arpu` domestically has no conversion record for
    # `arpu` — and short-circuiting on `conversion is None` here would compare a declared-USD
    # figure against an ILS one and report the founder's own number as overridden.
    dec = str(declared).upper() if _valid_ccy(declared) else None
    tgt = str(target).upper() if _valid_ccy(target) else None

    if dec is not None and tgt is not None and dec == tgt:
        return stated, None  # already in the analysis currency, converted field or not

    if not conversions:
        # Nothing was converted anywhere: every figure is in one currency by construction, which
        # is the pre-FX world and the overwhelmingly common case.
        return stated, None

    if dec is None:
        _froms = sorted({str(c.get("from")) for c in conversions if c.get("from")})
        return None, (
            f"the calculation converted its input from {' and '.join(_froms) or 'another currency'} "
            f"to {tgt or 'the analysis currency'}, and no currency was stated for the figure being "
            f"compared"
        )

    # Match by CURRENCY PAIR, not by field. A run can convert two fields from two different
    # source currencies, and the deck-claim check has no single field to key on — picking the
    # first record would refuse a comparison that is fully computable from the second. Rates come
    # from one pair-keyed map upstream, so every record sharing a pair shares its rate.
    for rec in conversions:
        if str(rec.get("from", "")).upper() == dec and (tgt is None or str(rec.get("to", "")).upper() == tgt):
            try:
                return float(stated) * float(rec["rate"]), None
            except (TypeError, ValueError, KeyError):
                return None, "the recorded conversion rate is unusable"

    return None, (
        f"the figure is in {dec}, and this run supplied no rate from {dec} to {tgt or 'the analysis currency'}"
    )


def _valid_ccy(value: Any) -> bool:
    """ISO-4217 shape check, mirrored from market_sizing.py."""
    return isinstance(value, str) and len(value) == 3 and value.isalpha()


def _compute_delta(calculated: float, deck_claim: Any) -> float | None:
    """Returns signed percentage delta, or None if claim is invalid."""
    try:
        claim = float(deck_claim)
    except (TypeError, ValueError):
        return None
    if claim <= 0:
        return None
    return round((calculated - claim) / claim * 100, 1)


def _compute_provenance(
    sizing: dict[str, Any],
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Compute provenance classification for each TAM/SAM/SOM figure.

    Cross-references validation.json assumptions with sizing.json inputs
    and inputs.json existing_claims.
    """
    # Build assumption name -> category map from validation
    assumption_map: dict[str, str] = {}
    if validation is not None and not _is_stub(validation):
        for assumption in _as_list(validation.get("assumptions")):
            if isinstance(assumption, dict):
                name = assumption.get("name", "")
                cat = assumption.get("category", "")
                if name and cat:
                    assumption_map[name] = cat

    # Get deck claims from inputs
    existing_claims: dict[str, Any] = {}
    if inputs is not None and not _is_stub(inputs):
        existing_claims = _as_dict(inputs.get("existing_claims"))

    provenance: dict[str, dict[str, Any]] = {}
    unresolved: list[tuple[str, str]] = []  # (param, metric) pairs

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        approach_prov: dict[str, Any] = {}
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            figure_inputs = _as_dict(m.get("inputs"))
            # Filter to quantitative params only (skip intermediates like tam, sam, etc.)
            relevant_inputs = {k: v for k, v in figure_inputs.items() if k in QUANTITATIVE_PARAMS}

            # Look up each input's category
            input_provenances: dict[str, str] = {}
            for param_name in relevant_inputs:
                if param_name in assumption_map:
                    input_provenances[param_name] = assumption_map[param_name]
                else:
                    unresolved.append((param_name, metric.upper()))

            # Classify the figure
            if not input_provenances:
                classification = "unknown"
            else:
                categories = set(input_provenances.values())
                if "agent_estimate" in categories:
                    classification = "agent_estimate"
                elif categories == {"sourced"}:
                    classification = "sourced"
                else:
                    classification = "derived"

            # Confidence breakdown
            breakdown: dict[str, int] = {"sourced": 0, "derived": 0, "agent_estimate": 0}
            for cat in input_provenances.values():
                if cat in breakdown:
                    breakdown[cat] += 1

            # Deck claim and delta
            deck_claim = existing_claims.get(metric)
            value = m.get("value", 0)
            delta = _compute_delta(float(value), deck_claim) if deck_claim is not None else None

            approach_prov[metric] = {
                "classification": classification,
                "confidence_breakdown": breakdown,
                "deck_claim": deck_claim,
                "delta_vs_deck_pct": delta,
                "input_provenances": input_provenances,
            }
        provenance[approach_key] = approach_prov

    return provenance, unresolved


def _founder_text_policy() -> Any:
    """Import the fleet's shared founder-text policy from `founder-skills/scripts/`.

    Parent-relative rather than duplicated: this file lives at
    `skills/<skill>/scripts/compose_report.py`, so `parents[2]/scripts` is the shared dir. Returns
    None if unavailable — a missing policy module must never block a report, since the scan is a
    warning and not a gate.
    """
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _warn(code: str, message: str) -> dict[str, str]:
    """Create a warning dict with code, message, and severity from canonical map."""
    return {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }


def _collect_sizing_inputs(sizing: dict[str, Any] | None) -> dict[str, float]:
    """Flatten every quantitative parameter the sizing math actually consumed.

    Walks both approaches x tam/sam/som and keeps only QUANTITATIVE_PARAMS keys,
    so derived intermediates (``serviceable_customers``, ``target_customers``) are
    ignored. A parameter appearing under several figures carries the same value,
    so last-write-wins is harmless.
    """
    used: dict[str, float] = {}
    if not isinstance(sizing, dict):
        return used
    for approach_key in ("top_down", "bottom_up"):
        approach = _as_dict(sizing.get(approach_key))
        for figure_key in ("tam", "sam", "som"):
            figure_inputs = _as_dict(_as_dict(approach.get(figure_key)).get("inputs"))
            for name, value in figure_inputs.items():
                if name in QUANTITATIVE_PARAMS and isinstance(value, (int, float)) and not isinstance(value, bool):
                    used[name] = float(value)
    return used


def _check_founder_value_fidelity(
    inputs: dict[str, Any] | None,
    sizing: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Warn when a founder-stated input is NOT what the math was computed from.

    A researched figure may be offered as a cross-check; it must never be silently
    substituted for a value the founder supplied. The founder recognises their own
    numbers, and a headline figure derived from a number they never gave reads as
    an arithmetic error — discrediting the parts of the analysis that are right.

    Detection is opt-in on ``inputs.founder_stated_inputs`` being populated: when the
    founder stated nothing quantitative there is nothing to preserve. Tolerance is
    0.5% relative, so a unit normalization ("18k" -> 18000) does not trip it while a
    genuine substitution (18,000 -> 16,601) does.
    """
    warnings: list[dict[str, str]] = []
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    if not stated:
        return warnings
    used = _collect_sizing_inputs(sizing)
    all_conversions = list(_fx_conversions(sizing).values())
    target_ccy = _as_dict(sizing).get("currency")
    declared_ccy = _as_dict(inputs).get("founder_stated_inputs_currency")
    for name, stated_value in sorted(stated.items()):
        if name not in QUANTITATIVE_PARAMS:
            continue
        if not isinstance(stated_value, (int, float)) or isinstance(stated_value, bool):
            continue
        if name not in used:
            continue
        # Bring the founder's figure into the analysis currency before comparing. Without this a
        # converted money input diverges from the founder's own number by exactly the FX rate, so
        # FOUNDER_VALUE_OVERRIDDEN would fire on every correctly-converted run.
        comparable, blocked = _to_analysis_currency(float(stated_value), declared_ccy, target_ccy, all_conversions)
        if blocked is not None:
            warnings.append(
                _warn(
                    "COMPARISON_CURRENCY_UNKNOWN",
                    f"Could not verify the figure you gave for {name} against the one the "
                    f"calculation used: {blocked}. State which currency your figure is in and "
                    f"this check can run.",
                )
            )
            continue
        assert comparable is not None  # _to_analysis_currency returns exactly one of the two
        stated_f = float(comparable)
        used_f = used[name]
        denom = abs(stated_f) if stated_f else 1.0
        if abs(used_f - stated_f) / denom <= 0.005:
            continue
        # Report what the founder actually said, not the currency-normalized comparand — the
        # founder has to recognise their own number in this sentence for it to mean anything.
        said_f = float(stated_value)
        warnings.append(
            _warn(
                "FOUNDER_VALUE_OVERRIDDEN",
                (
                    f"The founder stated {name} = {said_f:,.10g}, but the sizing was computed from "
                    f"{used_f:,.10g}. A researched figure may be presented as a cross-check; it must not "
                    f"replace a founder-stated input. Either recompute from {said_f:,.10g}, or — if the "
                    f"founder agreed to the revised figure — update inputs.founder_stated_inputs and record "
                    "the reason via accepted_warnings so the swap is disclosed rather than silent."
                ),
            )
        )
    return warnings


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run all 17 validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    inputs = artifacts.get("inputs.json")
    methodology = artifacts.get("methodology.json")
    validation = artifacts.get("validation.json")
    sizing = artifacts.get("sizing.json")
    sensitivity = artifacts.get("sensitivity.json")
    checklist = artifacts.get("checklist.json")

    # SIZING_INVALID — sizing.json exists but carries no figures, because market_sizing.py
    # rejected its input. Historically this was the quietest failure in the skill: the producer
    # exited 0 with an `{"ok":true}` receipt and wrote a `{"validation": {"status": "invalid"}}`
    # stub over the canonical artifact, so the only downstream signal was a MEDIUM
    # APPROACH_MISMATCH whose wording ("methodology says top_down but sizing.json is missing
    # top_down") pointed at the wrong cause. market_sizing.py now exits non-zero and refuses to
    # write, so a stub here means an OLD artifact or a hand-edited one — either way the report
    # must not be presented.
    if _usable(sizing):
        _sz_status = _as_dict(sizing.get("validation")).get("status")
        _has_figures = any(sizing.get(k) is not None for k in ("top_down", "bottom_up"))
        if _sz_status == "invalid" or not _has_figures:
            _errs = "; ".join(str(e) for e in _as_list(_as_dict(sizing.get("validation")).get("errors")))
            warnings.append(
                _warn(
                    "SIZING_INVALID",
                    "The market-size calculation did not complete, so this report has no "
                    "TAM/SAM/SOM figures"
                    + (f" ({_errs})" if _errs else "")
                    + ". Do not present it: correct the inputs and run the sizing step again.",
                )
            )

    # ARTIFACT_INVALID — the same check for the other two producer artifacts. Their producers now
    # refuse and preserve, so reaching here means a stale or hand-edited file.
    for _name, _art, _label in (
        ("sensitivity.json", artifacts.get("sensitivity.json"), "the sensitivity analysis"),
        ("checklist.json", artifacts.get("checklist.json"), "the quality checklist"),
    ):
        if not _usable(_art):
            continue
        if _as_dict(_art.get("validation")).get("status") != "invalid":
            continue
        _errs = "; ".join(str(e) for e in _as_list(_as_dict(_art.get("validation")).get("errors")))
        warnings.append(
            _warn(
                "ARTIFACT_INVALID",
                f"{_label.capitalize()} did not complete, so this report is missing part of its "
                f"analysis" + (f" ({_errs})" if _errs else "") + ". Do not present it: correct the "
                "inputs and run that step again.",
            )
        )

    # CURRENCY_MISMATCH — inputs.json records the founder's currency at intake;
    # sizing.json records what the producer was actually told. If they disagree,
    # one of the two figures on the page is mislabelled and we cannot know which,
    # so say so instead of silently picking a winner.
    if _usable(inputs) and _usable(sizing):
        in_cur = inputs.get("currency")
        sz_cur = sizing.get("currency")
        if (
            isinstance(in_cur, str)
            and in_cur.strip()
            and isinstance(sz_cur, str)
            and sz_cur.strip()
            and in_cur.strip().upper() != sz_cur.strip().upper()
        ):
            warnings.append(
                _warn(
                    "CURRENCY_MISMATCH",
                    (
                        f"inputs.json states currency {in_cur.strip().upper()} but sizing.json was computed "
                        f"as {sz_cur.strip().upper()}. Money figures in this report are labelled "
                        f"{in_cur.strip().upper()}; if the sizing inputs were actually in "
                        f"{sz_cur.strip().upper()}, every TAM/SAM/SOM figure carries the wrong unit. "
                        "Setting the currency does not convert anything — re-run the sizing step with the correct "
                        "--currency rather than converting the output by hand."
                    ),
                )
            )

    warnings.extend(_check_founder_value_fidelity(inputs, sizing))

    # 0. IMPLAUSIBLE_PCT_SCALE — surface sizing.json's input-plausibility warnings (WB-1:
    # the fractional-% guard, e.g. 0.4 entered where 40 was meant → silent ~100x error).
    # These are recorded in sizing.json's validation.warnings; re-emit so the founder sees
    # them in the report's Warnings section rather than only on the script's stderr.
    if _usable(sizing):
        for w in _as_list((sizing.get("validation") or {}).get("warnings")):
            if isinstance(w, dict) and w.get("code") == "IMPLAUSIBLE_PCT_SCALE":
                warnings.append(_warn("IMPLAUSIBLE_PCT_SCALE", str(w.get("message") or "Implausible percentage input")))

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT — required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 2. CORRUPT_ARTIFACT / MISSING_OPTIONAL_ARTIFACT — optional artifacts
    for name in OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_OPTIONAL_ARTIFACT", f"Optional artifact missing: {name}"))

    # 2b. STALE_ARTIFACT — run_id mismatch across artifacts
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        artifact_data = artifacts.get(name)
        if _usable(artifact_data):
            assert artifact_data is not None
            rid = _as_dict(artifact_data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_ids[name] = rid
    if run_ids:
        primary_rid = next(iter(run_ids.values()))
        for name, rid in run_ids.items():
            if rid != primary_rid:
                warnings.append(
                    _warn(
                        "STALE_ARTIFACT",
                        f"{name} has run_id '{rid}' but expected '{primary_rid}'",
                    )
                )

    # 3. UNSOURCED_ASSUMPTIONS — agent_estimate assumptions not in sensitivity
    if _usable(validation):
        agent_estimate_names: set[str] = set()
        for assumption in _as_list(validation.get("assumptions")):
            if isinstance(assumption, dict) and assumption.get("category") == "agent_estimate":
                name = assumption.get("name", "")
                if name in QUANTITATIVE_PARAMS:
                    agent_estimate_names.add(name)

        sensitivity_params: set[str] = set()
        if _usable(sensitivity):
            for scenario in _as_list(sensitivity.get("scenarios")):
                if isinstance(scenario, dict) and scenario.get("confidence") == "agent_estimate":
                    sensitivity_params.add(scenario.get("parameter", ""))

        unsourced = agent_estimate_names - sensitivity_params
        if unsourced:
            warnings.append(
                _warn(
                    "UNSOURCED_ASSUMPTIONS",
                    "Agent-estimate assumptions not stress-tested in sensitivity: "
                    f"{[_humanize_param(p) for p in sorted(unsourced)]}",
                )
            )

    # 4. UNVALIDATED_CLAIMS
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if isinstance(fig, dict) and fig.get("status") == "unsupported":
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                warnings.append(
                    _warn(
                        "UNVALIDATED_CLAIMS",
                        f"Unsupported figure: {fig_display}",
                    )
                )

    # 5. REFUTED_CLAIMS — surfaces refuted figures in warnings section
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if isinstance(fig, dict) and fig.get("status") == "refuted":
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                refutation = fig.get("refutation")
                if not refutation:
                    # 6. REFUTED_MISSING_REASON — refuted claim without explanation
                    warnings.append(
                        _warn(
                            "REFUTED_MISSING_REASON",
                            f"Refuted figure '{fig_display}' has no refutation explanation",
                        )
                    )
                warnings.append(
                    _warn(
                        "REFUTED_CLAIMS",
                        f"Refuted figure: {fig_display} — {refutation or 'no explanation provided'}",
                    )
                )

    # 7. APPROACH_MISMATCH
    if _usable(methodology) and _usable(sizing):
        approach = methodology.get("approach_chosen", "")
        if approach == "both":
            if "top_down" not in sizing or "bottom_up" not in sizing:
                warnings.append(
                    _warn(
                        "APPROACH_MISMATCH",
                        "Methodology says 'both' but sizing.json missing top_down or bottom_up",
                    )
                )
        elif approach in ("top_down", "bottom_up") and approach not in sizing:
            warnings.append(
                _warn(
                    "APPROACH_MISMATCH",
                    f"Methodology says '{approach}' but sizing.json missing {approach} key",
                )
            )

    # 8. TAM_DISCREPANCY / SAM_DISCREPANCY / SOM_DISCREPANCY — same >30% gate extended
    # to SAM/SOM (previously only TAM was checked; an order-of-magnitude SAM/SOM gap
    # between top-down and bottom-up could be presented as equally defensible).
    if _usable(sizing):
        comparison = _as_dict(sizing.get("comparison"))
        if comparison.get("tam_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "TAM_DISCREPANCY",
                    f"Top-down and bottom-up TAM differ by {comparison['tam_delta_pct']}% (>30%)",
                )
            )
        if comparison.get("sam_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "SAM_DISCREPANCY",
                    f"Top-down and bottom-up SAM differ by {comparison['sam_delta_pct']}% (>30%)",
                )
            )
        if comparison.get("som_delta_pct", 0) > 30:
            warnings.append(
                _warn(
                    "SOM_DISCREPANCY",
                    f"Top-down and bottom-up SOM differ by {comparison['som_delta_pct']}% (>30%)",
                )
            )

    # 9. CHECKLIST_FAILURES
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        if summary.get("overall_status") == "fail":
            failed = _as_list(summary.get("failed_items"))
            failed_ids = [f.get("id", "?") for f in failed]
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES",
                    f"Checklist has {len(failed)} failures: {failed_ids}",
                )
            )

    # 10. CHECKLIST_INCOMPLETE
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        if len(items) != 22:
            warnings.append(
                _warn(
                    "CHECKLIST_INCOMPLETE",
                    f"Checklist has {len(items)} items (expected 22)",
                )
            )

    # 11. LOW_CHECKLIST_COVERAGE
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        na_count = summary.get("not_applicable", 0)
        if na_count > 7:
            warnings.append(
                _warn(
                    "LOW_CHECKLIST_COVERAGE",
                    f"Checklist has {na_count} not_applicable items (>7 of 22)",
                )
            )

    # 12. FEW_SENSITIVITY_PARAMS
    if _usable(sensitivity):
        scenarios = _as_list(sensitivity.get("scenarios"))
        if len(scenarios) < 3:
            warnings.append(
                _warn(
                    "FEW_SENSITIVITY_PARAMS",
                    f"Sensitivity analysis has {len(scenarios)} parameters (recommend 3+)",
                )
            )

    # 13. NARROW_AGENT_ESTIMATE_RANGE
    if _usable(sensitivity):
        for scenario in _as_list(sensitivity.get("scenarios")):
            if isinstance(scenario, dict) and scenario.get("confidence") == "agent_estimate":
                eff = _as_dict(scenario.get("effective_range"))
                low = abs(eff.get("low_pct", 0))
                high = abs(eff.get("high_pct", 0))
                if low < 50 or high < 50:
                    warnings.append(
                        _warn(
                            "NARROW_AGENT_ESTIMATE_RANGE",
                            f"Agent-estimate parameter '{scenario.get('parameter')}' has effective range "
                            f"[{eff.get('low_pct')}%, +{eff.get('high_pct')}%] — should be at least +/-50%",
                        )
                    )

    # 14. OVERCLAIMED_VALIDATION
    if _usable(validation):
        for fig in _as_list(validation.get("figure_validations")):
            if isinstance(fig, dict) and fig.get("status") == "validated" and fig.get("source_count", 0) < 2:
                fig_display = fig.get("label", fig.get("figure", "unknown"))
                warnings.append(
                    _warn(
                        "OVERCLAIMED_VALIDATION",
                        f"Figure '{fig_display}' marked validated but source_count={fig.get('source_count')}",
                    )
                )

    # 15. DECK_CLAIM_MISMATCH — deck claim differs from calculated by >50%
    #
    # FX-aware: every tam/sam/som is derived from the money inputs, so if ANY of them was
    # converted the calculated figures are in the analysis currency while the deck's claim is in
    # whatever the deck used. Comparing across that gap yields a delta of the exchange rate's
    # magnitude (~+272% at USD:ILS=3.72) on a perfectly correct analysis — so gate on a declared
    # claim currency and say "cannot compare" when there isn't one.
    inputs_art = artifacts.get("inputs.json")
    if _usable(sizing) and _usable(inputs_art):
        existing_claims = _as_dict(inputs_art.get("existing_claims"))
        _claim_convs = list(_fx_conversions(sizing).values())
        _claim_ccy = inputs_art.get("existing_claims_currency")
        for approach_key in ("top_down", "bottom_up"):
            approach_data = sizing.get(approach_key)
            if approach_data is None:
                continue
            for metric in ("tam", "sam", "som"):
                m = _as_dict(approach_data.get(metric))
                val = m.get("value", 0)
                claim = existing_claims.get(metric)
                if claim is not None and isinstance(claim, (int, float)) and not isinstance(claim, bool):
                    comparable, blocked = _to_analysis_currency(
                        float(claim), _claim_ccy, sizing.get("currency"), _claim_convs
                    )
                    if blocked is not None:
                        warnings.append(
                            _warn(
                                "COMPARISON_CURRENCY_UNKNOWN",
                                f"Could not cross-check the {metric.upper()} you stated against the "
                                f"calculated one: {blocked}. State which currency your figure is in "
                                f"and this check can run.",
                            )
                        )
                        continue
                    claim = comparable
                delta = _compute_delta(float(val), claim)
                if delta is not None and abs(delta) > 50 and claim is not None:
                    # Code stays DECK_CLAIM_MISMATCH (stable API, asserted elsewhere);
                    # only the human-readable wording follows where the claim came from.
                    _src = (
                        "deck claim"
                        if _has_document_materials(artifacts.get("inputs.json"))
                        else "the figure you stated"
                    )
                    _lbl = "deck" if _has_document_materials(artifacts.get("inputs.json")) else "you said"
                    warnings.append(
                        _warn(
                            "DECK_CLAIM_MISMATCH",
                            f"{metric.upper()} differs from {_src} by {delta:+.1f}% "
                            f"({_lbl}: {_fmt_usd(float(claim))}, calculated: {_fmt_usd(val)})",
                        )
                    )

    # 16. PROVENANCE_UNRESOLVED — quantitative param in sizing inputs without matching assumption
    if _usable(sizing) and _usable(validation):
        provenance_result, unresolved = _compute_provenance(sizing, validation, artifacts.get("inputs.json"))
        if unresolved:
            # Aggregate: param -> list of metrics
            param_metrics: dict[str, list[str]] = {}
            for param, metric_name in unresolved:
                param_metrics.setdefault(param, []).append(metric_name)
            parts = [f"{p} (used in {', '.join(ms)})" for p, ms in sorted(param_metrics.items())]
            warnings.append(
                _warn(
                    "PROVENANCE_UNRESOLVED",
                    "Quantitative inputs without matching assumptions in validation.json: " + ", ".join(parts),
                )
            )

    # 17. EXISTING_CLAIMS_SHAPE — non-canonical keys silently bypass reconciliation
    # at compose_report.py:282 (_compute_provenance) and the DECK_CLAIM_MISMATCH check above.
    inputs_art = artifacts.get("inputs.json")
    if _usable(inputs_art):
        raw = inputs_art.get("existing_claims")
        if isinstance(raw, dict):
            canonical = {"tam", "sam", "som"}
            unexpected = sorted(k for k in raw if k not in canonical)
            if unexpected:
                warnings.append(
                    _warn(
                        "EXISTING_CLAIMS_SHAPE",
                        f"inputs.existing_claims contains non-canonical keys: "
                        f"{', '.join(unexpected)}. Expected only lowercase "
                        f"'tam', 'sam', 'som' (flat). Non-canonical keys are "
                        f"silently ignored by reconciliation. For deck claims "
                        f"that don't fit the flat shape (regional sub-SAMs, "
                        f"time-anchored figures, alternative TAM frames), use "
                        f"the adjacent 'existing_claims_detail' field — it is "
                        f"rendered narratively in the report.",
                    )
                )
        elif raw is not None and raw != {}:
            warnings.append(
                _warn(
                    "EXISTING_CLAIMS_SHAPE",
                    f"inputs.existing_claims must be a dict of {{tam, sam, som}}; got {type(raw).__name__}.",
                )
            )

    return warnings


def _section_deck_claims_narrative(inputs: dict[str, Any] | None) -> str:
    """Render existing_claims_detail as a narrative sub-section.

    Captures deck claims that don't fit the canonical {tam, sam, som} flat shape
    (regional sub-SAMs, time-anchored figures, alternative TAM frames). Rendered
    as-is; does NOT participate in deck-vs-computed reconciliation.
    """
    if inputs is None or _is_stub(inputs):
        return ""
    detail = inputs.get("existing_claims_detail")
    if not detail:  # None, empty dict, empty list, empty string, etc.
        return ""
    # Attribute the claim to where it actually came from. This skill supports
    # conversational runs (no upload at all), and crediting a founder's spoken
    # figures to "the deck" is a wrong provenance statement about their own input.
    from_doc = _has_document_materials(inputs)
    heading = "Deck Claims" if from_doc else "Your Stated Figures"
    source = "The deck stated" if from_doc else "You stated"
    lines = [f"## {heading} (Narrative)\n"]
    lines.append(
        f"*{source} additional figures that don't fit the canonical "
        "TAM/SAM/SOM shape. These are captured for context but are not "
        "reconciled against the computed sizing.*\n"
    )
    if isinstance(detail, dict):
        for key, val in detail.items():
            lines.append(f"- **{_md_safe(str(key))}:** {_md_safe(str(val))}")
    else:
        lines.append("```")
        lines.append(_md_safe(str(detail)))
        lines.append("```")
    return "\n".join(lines) + "\n"


def _section_title_provenance(
    inputs: dict[str, Any] | None,
    sizing: dict[str, Any] | None = None,
) -> str:
    """Section 1: Title and provenance."""
    if inputs is None:
        return "# Market Sizing Report\n\n*No inputs artifact found.*\n"
    company = inputs.get("company_name", "Unknown Company")
    date = inputs.get("analysis_date", "unknown date")
    materials = _as_list(inputs.get("materials_provided"))
    mat_str = ", ".join(str(m) for m in materials) if materials else "none"
    basis_label = _sizing_basis_label(_resolve_sizing_basis(sizing, inputs))
    lines = [
        f"# Market Sizing: {company}\n",
        f"**Date:** {date}  ",
        f"**Materials:** {mat_str}  ",
        f"**Sizing basis:** {basis_label}  ",
        "**Generated by:** [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent\n",
    ]
    return "\n".join(lines)


def _section_executive_summary(
    sizing: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Executive summary with key metrics from sizing and sensitivity."""
    if sizing is None or _is_stub(sizing):
        return "## Executive Summary\n\n*No sizing data available for summary.*\n"

    lines = ["## Executive Summary\n"]
    lines.append("| Metric | Value | Method |")
    lines.append("|--------|-------|--------|")

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            val = m.get("value", 0)
            lines.append(f"| {metric.upper()} | {_fmt_usd(val)} | {method} |")

    if sensitivity is not None and not _is_stub(sensitivity):
        most = sensitivity.get("most_sensitive")
        if most:
            lines.append(f"| Most Sensitive Parameter | {_humanize_param(most)} | — |")

    # Flag significant deck claim deltas
    if provenance:
        both_mode = "top_down" in provenance and "bottom_up" in provenance
        for metric in ("tam", "sam", "som"):
            # Collect mismatches across approaches for this metric
            mismatches: list[tuple[str, float, float]] = []  # (label, val, deck_claim)
            for approach_key in ("top_down", "bottom_up"):
                if approach_key not in provenance:
                    continue
                prov = provenance[approach_key].get(metric, {})
                delta = prov.get("delta_vs_deck_pct")
                deck_claim = prov.get("deck_claim")
                if delta is not None and abs(delta) > 50 and deck_claim is not None:
                    approach_data = _as_dict(sizing.get(approach_key)) if sizing else {}
                    m_data = _as_dict(approach_data.get(metric))
                    val = m_data.get("value", 0)
                    label = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    mismatches.append((label, float(val), float(deck_claim)))
            if mismatches:
                claim_str = _fmt_usd(mismatches[0][2])
                if both_mode and len(mismatches) > 1:
                    parts = ", ".join(f"{lbl}: {_fmt_usd(v)}" for lbl, v, _ in mismatches)
                    lines.append(
                        f"\n**Note:** Both {metric.upper()} estimates differ significantly "
                        f"from the deck's claim of {claim_str} ({parts})."
                    )
                elif both_mode:
                    lbl, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {lbl.lower()} {metric.upper()} estimate differs significantly "
                        f"from the deck's claim ({_fmt_usd(val)} vs {claim_str})."
                    )
                else:
                    _, val, _ = mismatches[0]
                    lines.append(
                        f"\n**Note:** Our {metric.upper()} estimate differs significantly "
                        f"from the deck's claim ({_fmt_usd(val)} vs {claim_str})."
                    )

    return "\n".join(lines) + "\n"


def _section_methodology(methodology: dict[str, Any] | None) -> str:
    """Methodology section showing approach and rationale."""
    if methodology is None:
        return "## Methodology\n\n*No methodology artifact found.*\n"
    if _is_stub(methodology):
        return f"## Methodology\n\n*Methodology not recorded — {methodology.get('reason', 'unknown reason')}*\n"

    approach = methodology.get("approach_chosen", "unknown")
    rationale = methodology.get("rationale", "")
    approach_label = {
        "both": "Both (top-down and bottom-up cross-validation)",
        "top_down": "Top-down",
        "bottom_up": "Bottom-up",
    }.get(approach, approach)

    lines = ["## Methodology\n"]
    lines.append(f"**Approach:** {approach_label}")
    if rationale:
        lines.append(f"**Rationale:** {rationale}")
    return "\n".join(lines) + "\n"


def _section_analysis_checklist(checklist: dict[str, Any] | None, artifacts_found: list[str]) -> str:
    """Analysis checklist with compact 22-row appendix."""
    lines = ["## Analysis Checklist\n"]
    # A count, not the filenames. The founder cannot act on "inputs.json, methodology.json, …" — the
    # signal the line actually carries is "how much of the analysis completed", and that survives.
    # Which specific artifact is missing is an operator question, and the missing-artifact warnings
    # already answer it.
    lines.append(f"- Analysis steps completed: {len(artifacts_found)}")
    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        pass_ct = summary.get("pass", 0)
        fail_ct = summary.get("fail", 0)
        na_ct = summary.get("not_applicable", 0)
        total_ct = summary.get("total", pass_ct + fail_ct + na_ct)
        applicable_ct = total_ct - na_ct
        score_pct = summary.get("score_pct")
        if isinstance(score_pct, (int, float)):
            # Render as "<score>% (<pass>/<applicable> pass, ...)" — NOT a bare "pass/total"
            # fraction (e.g. "100/22"), which reads as a malformed ratio rather than 100% across
            # 22 items.
            score_str = f"{int(score_pct)}" if float(score_pct) == int(score_pct) else f"{score_pct:.1f}"
            lines.append(f"- Self-check: {score_str}% ({pass_ct}/{applicable_ct} pass, {fail_ct} fail, {na_ct} N/A)")
        else:
            lines.append(f"- Self-check: {pass_ct} pass, {fail_ct} fail, {na_ct} N/A")

        # Failed items detail
        failed_items = _as_list(summary.get("failed_items"))
        if failed_items:
            lines.append("\n**Items that failed:**")
            for raw_f in failed_items:
                f = _as_dict(raw_f)
                label = f.get("label", f.get("id", "?"))
                notes = f.get("notes", "")
                lines.append(f"- **{label}**: {notes}" if notes else f"- **{label}**")

        # Compact 22-row appendix table
        items = _as_list(checklist.get("items"))
        if items:
            lines.append("\n### Appendix: Full Self-Check\n")
            lines.append("| # | Criterion | Status | Notes |")
            lines.append("|---|-----------|--------|-------|")
            status_icons = {"pass": "PASS", "fail": "FAIL", "not_applicable": "N/A"}
            for i, raw_item in enumerate(items, 1):
                item = _as_dict(raw_item)
                label = _md_safe(item.get("label", item.get("id", "?")))
                status = status_icons.get(item.get("status", "?"), "?")
                notes = _md_safe(item.get("notes", "") or "")
                lines.append(f"| {i} | {label} | {status} | {notes} |")

    return "\n".join(lines) + "\n"


def _section_definitions() -> str:
    """Section 3: Brief TAM/SAM/SOM definitions."""
    return (
        "## Definitions\n\n"
        "- **TAM** (Total Addressable Market): Total market demand for the "
        "product/service if 100% market share were achieved.\n"
        "- **SAM** (Serviceable Available Market): The segment of TAM targeted "
        "by your products and services that is within your geographical reach.\n"
        "- **SOM** (Serviceable Obtainable Market): The portion of SAM that you "
        "can realistically capture in the near term.\n"
    )


def _section_sizing_table(
    sizing: dict[str, Any] | None,
    provenance: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Section 4: Market sizing table."""
    if sizing is None:
        return "## Market Sizing\n\n*No sizing data available.*\n"
    if _is_stub(sizing):
        return f"## Market Sizing\n\n*Sizing not performed — {sizing.get('reason', 'unknown reason')}*\n"

    lines = ["## Market Sizing\n"]

    # Non-USD disclosure. Labelling the figures correctly is necessary but not
    # sufficient: an externally-sourced industry total is very often quoted in
    # USD, and nothing here converts it. Say so rather than let a mixed-unit
    # TAM pass as a single-unit one.
    # Two mutually exclusive disclosures. The no-FX wording is unchanged for a run where nothing
    # was converted (the overwhelmingly common case); a converted run gets the rate, its date and
    # its source stated in the founder's own report, so the number is auditable rather than
    # asserted. Never print both — the old text claimed "no FX conversion is applied anywhere",
    # which becomes false the moment one is.
    _fx_conv = _fx_conversions(sizing)
    if _fx_conv:
        _fx_meta = _as_dict(_as_dict(sizing).get("fx"))
        _as_of = _fx_meta.get("as_of") or "date not stated"
        _src = _fx_meta.get("source") or "source not stated"
        _each = "; ".join(
            f"{c.get('field')} {_fmt_usd(float(c.get('original_value', 0)), str(c.get('from')))} "
            f"→ {_fmt_usd(float(c.get('converted_value', 0)), str(c.get('to')))} "
            f"at 1 {c.get('from')} = {c.get('rate')} {c.get('to')}"
            for c in _fx_conv.values()
        )
        lines.append(
            f"> **Currency: {_CURRENCY}.** Some inputs were supplied in another currency and "
            f"converted into {_CURRENCY}: {_each}. Rate as of {_as_of} ({_src}). Every figure below "
            f"is in {_CURRENCY}; check the rate if you are comparing against a source in its "
            f"original currency.\n"
        )
    elif _CURRENCY != "USD":
        lines.append(
            f"> **Currency: {_CURRENCY}.** All figures are stated in {_CURRENCY} as supplied — "
            f"**no FX conversion is applied anywhere in this analysis.** If any input came from an "
            f"external source quoted in another currency (industry totals usually are quoted in USD), "
            f"convert it to {_CURRENCY} yourself before relying on the combined figure.\n"
        )

    # One-line narrative per approach
    td_data = sizing.get("top_down")
    bu_data = sizing.get("bottom_up")
    if td_data:
        tam_inputs = _as_dict(_as_dict(td_data.get("tam")).get("inputs"))
        td_sam_inputs = _as_dict(_as_dict(td_data.get("sam")).get("inputs"))
        industry = _fmt_usd(tam_inputs.get("industry_total", 0)) if "industry_total" in tam_inputs else "?"
        seg = td_sam_inputs.get("segment_pct", "?") if "segment_pct" in td_sam_inputs else "?"
        share_inputs = _as_dict(_as_dict(td_data.get("som")).get("inputs"))
        share = share_inputs.get("share_pct", "?") if "share_pct" in share_inputs else "?"
        lines.append(
            f"**Top-down:** Starting from industry total of {industry}, "
            f"targeting {seg}% segment with {share}% market share.\n"
        )
    if bu_data:
        tam_inputs = _as_dict(_as_dict(bu_data.get("tam")).get("inputs"))
        cust = tam_inputs.get("customer_count", "?")
        arpu_val = _fmt_usd(tam_inputs.get("arpu", 0)) if "arpu" in tam_inputs else "?"
        sam_inputs = _as_dict(_as_dict(bu_data.get("sam")).get("inputs"))
        serv = tam_inputs.get("serviceable_pct", sam_inputs.get("serviceable_pct", "?"))
        som_inputs = _as_dict(_as_dict(bu_data.get("som")).get("inputs"))
        tgt = tam_inputs.get("target_pct", som_inputs.get("target_pct", "?"))
        if isinstance(cust, (int, float)):
            bu_line = (
                f"**Bottom-up:** {cust:,} potential customers x "
                f"{arpu_val} ARPU, {serv}% serviceable, {tgt}% target capture.\n"
            )
        else:
            bu_line = (
                f"**Bottom-up:** {cust} potential customers x "
                f"{arpu_val} ARPU, {serv}% serviceable, {tgt}% target capture.\n"
            )
        lines.append(bu_line)

    lines.append("| Metric | Value | Method | Provenance | Key Assumptions |")
    lines.append("|--------|-------|--------|------------|-----------------|")

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        method = "Top-down" if approach_key == "top_down" else "Bottom-up"
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            val = m.get("value", 0)
            inputs_data = _as_dict(m.get("inputs"))
            assumption_parts = []
            for k, v in inputs_data.items():
                label = _humanize_param(k)
                formatted = _fmt_usd(v) if k in ("industry_total", "arpu", "tam", "sam") else _fmt_number(v)
                assumption_parts.append(f"{label}: {formatted}")
            assumptions = ", ".join(assumption_parts)
            # Look up provenance classification
            prov_label = ""
            if provenance and approach_key in provenance:
                prov = provenance[approach_key].get(metric, {})
                prov_label = _md_safe(prov.get("classification", ""))
            lines.append(f"| {metric.upper()} | {_fmt_usd(val)} | {method} | {prov_label} | {assumptions} |")

    comparison = sizing.get("comparison")
    if comparison:
        delta = comparison.get("tam_delta_pct", 0)
        note = comparison.get("warning") or comparison.get("note", "")
        lines.append(f"\n**Cross-validation:** TAM delta = {delta}%. {note}")

    # Deck Claims comparison table
    if provenance:
        comparison_rows: list[str] = []
        for approach_key in ("top_down", "bottom_up"):
            if approach_key not in provenance:
                continue
            for metric in ("tam", "sam", "som"):
                prov = provenance[approach_key].get(metric, {})
                deck_claim = prov.get("deck_claim")
                delta_pct = prov.get("delta_vs_deck_pct")
                classification = prov.get("classification", "")
                if deck_claim is not None and delta_pct is not None:
                    approach_data = sizing.get(approach_key, {})
                    m = _as_dict(approach_data.get(metric))
                    val = m.get("value", 0)
                    method = "Top-down" if approach_key == "top_down" else "Bottom-up"
                    comparison_rows.append(
                        f"| {metric.upper()} ({method}) | {_fmt_usd(float(deck_claim))} "
                        f"| {_fmt_usd(val)} | {delta_pct:+.1f}% | {_md_safe(classification)} |"
                    )
        if comparison_rows:
            lines.append("\n### Deck Claims vs. Our Estimates\n")
            lines.append("| Metric | Deck Claim | Our Estimate | Delta | Classification |")
            lines.append("|--------|-----------|--------------|-------|----------------|")
            lines.extend(comparison_rows)

    return "\n".join(lines) + "\n"


def _section_assumptions(validation: dict[str, Any] | None) -> str:
    """Section 5: Assumptions."""
    if validation is None:
        return "## Assumptions\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return f"## Assumptions\n\n*Validation not performed — {validation.get('reason', 'unknown reason')}*\n"

    assumptions = _as_list(validation.get("assumptions"))
    if not assumptions:
        return "## Assumptions\n\n*No assumptions recorded.*\n"

    lines = ["## Assumptions\n"]
    cat_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    # Params whose values are monetary
    monetary_params = {"industry_total", "arpu"}
    for a in assumptions:
        if not isinstance(a, dict):
            continue
        cat = a.get("category", "unknown")
        cat_display = cat_labels.get(cat, cat)
        name = a.get("name", "unnamed")
        display_name = a.get("label", _humanize_param(name))
        value = a.get("value", "")
        if isinstance(value, (int, float)) and name in monetary_params:
            formatted_val = _fmt_usd(value)
        elif isinstance(value, (int, float)):
            formatted_val = _fmt_number(value)
        else:
            formatted_val = str(value)
        line = f"- **{display_name}** = {formatted_val} ({cat_display})"
        # Per-assumption attribution. "Sourced" without the source is a claim the founder cannot check,
        # and the sub-agent is asked for exactly this pair on each assumption.
        src_title = str(a.get("source_title", "") or "").strip()
        src_url = str(a.get("source_url", "") or "").strip()
        if src_title and src_url:
            line += f" — [{src_title}]({src_url})"
        elif src_title:
            line += f" — {src_title}"
        elif src_url:
            line += f" — {src_url}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _section_validation(validation: dict[str, Any] | None) -> str:
    """Section 6: Figure validation."""
    if validation is None:
        return "## Validation\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return f"## Validation\n\n*Validation not performed — {validation.get('reason', 'unknown reason')}*\n"

    figs = _as_list(validation.get("figure_validations"))
    if not figs:
        return "## Validation\n\n*No figures validated.*\n"

    lines = ["## Validation\n"]
    for fig in figs:
        if not isinstance(fig, dict):
            continue
        figure = fig.get("label") or fig.get("figure", "unknown")
        status = fig.get("status", "unknown")
        source_count = fig.get("source_count", 0)
        lines.append(f"- **{figure}**: {status} ({source_count} source{'s' if source_count != 1 else ''})")
    return "\n".join(lines) + "\n"


def _section_sensitivity(sensitivity: dict[str, Any] | None) -> str:
    """Section 7: Sensitivity analysis."""
    if sensitivity is None:
        return "## Sensitivity Analysis\n\n*No sensitivity analysis available.*\n"
    if _is_stub(sensitivity):
        reason = sensitivity.get("reason", "unknown reason")
        return f"## Sensitivity Analysis\n\n*Sensitivity analysis not performed — {reason}*\n"

    scenarios = _as_list(sensitivity.get("scenarios"))
    if not scenarios:
        return "## Sensitivity Analysis\n\n*No scenarios analyzed.*\n"

    lines = [
        "## Sensitivity Analysis\n",
        "The table below shows how each market tier changes when each assumption moves between"
        " its low and high estimate. Parameters tagged *Estimate* have wider ranges"
        " because they lack external sourcing — they tend to dominate the sensitivity,"
        " which highlights exactly where better data would most strengthen the analysis.\n",
    ]
    has_approach_used = any(isinstance(s, dict) and s.get("approach_used") for s in scenarios)

    # Check whether TAM/SAM fields are present in any scenario (real sensitivity.py output)
    has_tam_sam = any(
        isinstance(s, dict) and ("tam" in s.get("low", {}) or "tam" in s.get("base", {})) for s in scenarios
    )

    if has_approach_used:
        if has_tam_sam:
            lines.append(
                "| Parameter | Approach | Confidence | Low Value | Base Value | High Value"
                " | Low TAM | Base TAM | High TAM"
                " | Low SAM | Base SAM | High SAM"
                " | Low SOM | Base SOM | High SOM | Range |"
            )
            lines.append(
                "|-----------|----------|------------|-----------|------------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------|-------|"
            )
        else:
            lines.append("| Parameter | Approach | Confidence | Low SOM | Base SOM | High SOM | Range |")
            lines.append("|-----------|----------|------------|---------|----------|----------|-------|")
    else:
        if has_tam_sam:
            lines.append(
                "| Parameter | Confidence | Low Value | Base Value | High Value"
                " | Low TAM | Base TAM | High TAM"
                " | Low SAM | Base SAM | High SAM"
                " | Low SOM | Base SOM | High SOM | Range |"
            )
            lines.append(
                "|-----------|------------|-----------|------------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------"
                "|---------|----------|----------|-------|"
            )
        else:
            lines.append("| Parameter | Confidence | Low SOM | Base SOM | High SOM | Range |")
            lines.append("|-----------|------------|---------|----------|----------|-------|")

    conf_labels = {"sourced": "Sourced", "derived": "Derived", "agent_estimate": "Estimate"}
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        param = _humanize_param(s.get("parameter", "?"))
        conf = conf_labels.get(s.get("confidence", "sourced"), s.get("confidence", "sourced"))
        low_d = _as_dict(s.get("low"))
        base_d = _as_dict(s.get("base"))
        high_d = _as_dict(s.get("high"))
        low_som = _fmt_usd(low_d.get("som", 0))
        base_som = _fmt_usd(base_d.get("som", 0))
        high_som = _fmt_usd(high_d.get("som", 0))
        eff = _as_dict(s.get("effective_range"))
        range_str = f"[{eff.get('low_pct', 0)}%, +{eff.get('high_pct', 0)}%]"
        widened = " (widened)" if s.get("range_widened") else ""

        # Parameter value columns (low/base/high parameter value, not market size).
        # Format unit-aware (currency / count / percent) so all three cells are consistent.
        raw_param = s.get("parameter", "")
        base_val = s.get("base_value")
        low_val_raw = low_d.get("value")
        high_val_raw = high_d.get("value")
        if base_val is not None and isinstance(base_val, (int, float)):
            low_val_str = _fmt_param_value(raw_param, low_val_raw) if isinstance(low_val_raw, (int, float)) else "—"
            base_val_str = _fmt_param_value(raw_param, base_val)
            high_val_str = _fmt_param_value(raw_param, high_val_raw) if isinstance(high_val_raw, (int, float)) else "—"
        else:
            low_val_str = base_val_str = high_val_str = "—"

        if has_approach_used:
            approach_labels = {"top_down": "Top-down", "bottom_up": "Bottom-up"}
            approach_used = approach_labels.get(s.get("approach_used", "?"), s.get("approach_used", "?"))
            if has_tam_sam:
                low_tam = _fmt_usd(low_d.get("tam", 0))
                base_tam = _fmt_usd(base_d.get("tam", 0))
                high_tam = _fmt_usd(high_d.get("tam", 0))
                low_sam = _fmt_usd(low_d.get("sam", 0))
                base_sam = _fmt_usd(base_d.get("sam", 0))
                high_sam = _fmt_usd(high_d.get("sam", 0))
                lines.append(
                    f"| {param} | {approach_used} | {conf}"
                    f" | {low_val_str} | {base_val_str} | {high_val_str}"
                    f" | {low_tam} | {base_tam} | {high_tam}"
                    f" | {low_sam} | {base_sam} | {high_sam}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
            else:
                lines.append(
                    f"| {param} | {approach_used} | {conf}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
        else:
            if has_tam_sam:
                low_tam = _fmt_usd(low_d.get("tam", 0))
                base_tam = _fmt_usd(base_d.get("tam", 0))
                high_tam = _fmt_usd(high_d.get("tam", 0))
                low_sam = _fmt_usd(low_d.get("sam", 0))
                base_sam = _fmt_usd(base_d.get("sam", 0))
                high_sam = _fmt_usd(high_d.get("sam", 0))
                lines.append(
                    f"| {param} | {conf}"
                    f" | {low_val_str} | {base_val_str} | {high_val_str}"
                    f" | {low_tam} | {base_tam} | {high_tam}"
                    f" | {low_sam} | {base_sam} | {high_sam}"
                    f" | {low_som} | {base_som} | {high_som} | {range_str}{widened} |"
                )
            else:
                lines.append(f"| {param} | {conf} | {low_som} | {base_som} | {high_som} | {range_str}{widened} |")

    ranking = _as_list(sensitivity.get("sensitivity_ranking"))
    if ranking:
        most = _humanize_param(ranking[0].get("parameter", "?"))
        lines.append(f"\n**Most sensitive parameter:** {most}")

    return "\n".join(lines) + "\n"


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Section 8: Warnings/errors."""
    if not warnings:
        return ""

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i", "info": "~"}
    lines = ["## Warnings\n"]
    for w in warnings:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


def _section_sources(validation: dict[str, Any] | None) -> str:
    """Section 9: Sources used."""
    if validation is None:
        return "## Sources Used\n\n*No validation data available.*\n"
    if _is_stub(validation):
        return "## Sources Used\n\n*No sources — validation not performed.*\n"

    sources = _as_list(validation.get("sources"))
    if not sources:
        return (
            "## Sources Used\n\nSources Used: none — pure calculation from "
            "user-provided inputs (no market size claims to validate)\n"
        )

    # Deduplicate by URL or title
    seen: set[str] = set()
    lines = ["## Sources Used\n"]
    for i, s in enumerate(sources):
        key = s.get("url") or s.get("title", "") or f"__unnamed_{i}"
        if key in seen:
            continue
        seen.add(key)
        title = s.get("title", "Untitled")
        publisher = s.get("publisher", "")
        url = s.get("url", "")
        date = s.get("date_accessed", "")
        supported = s.get("supported", "")
        # Title as clickable link if URL available, otherwise bold
        title_part = f"[{title}]({url})" if url else f"**{title}**"
        parts = [title_part]
        if publisher:
            parts.append(publisher)
        if date:
            parts.append(f"accessed {date}")
        # Source STRENGTH, not just identity. An analyst-firm figure for the exact segment and a blog
        # post about an adjacent one support a number very differently, and the sub-agent is asked to
        # judge both — so withholding them leaves the founder unable to weigh the sizing.
        tier = str(s.get("quality_tier", "") or "").strip()
        if tier:
            parts.append(_humanize_param(tier))
        match = str(s.get("segment_match", "") or "").strip()
        if match:
            parts.append(f"{_humanize_param(match)} segment match")
        line = f"- {parts[0]}"
        meta = [p for p in parts[1:]]
        if meta:
            line += f" ({', '.join(meta)})"
        if supported:
            line += f" — supports: {supported}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _resolve_headline_market_size(
    sizing: dict[str, Any] | None,
) -> tuple[dict[str, float | None], str | None]:
    """Resolve a single headline TAM/SAM/SOM triple from sizing.json for the coaching payload.

    sizing.json never carries a top-level "tam"/"sam"/"som" scalar — each figure is
    nested under an approach key (``top_down`` / ``bottom_up``) as a dict whose
    numeric value lives at ``.value`` (see market_sizing.py's ``top_down()`` /
    ``bottom_up()`` output). The coaching sub-agent is told to reason ONLY from
    coaching_payload and never refetch from disk, so this resolves the nested path
    once here rather than leaving it undone.

    Selection rule for ``approach: "both"`` mode — documented here because nothing
    upstream names a winner between the two independently-computed TAMs: prefer
    ``bottom_up`` when both approaches are present, falling back to ``top_down``
    when bottom_up is absent (top_down-only mode). This matches the skill's own
    stated methodology preference (references/tam-sam-som-methodology.md:84 —
    "Prefer bottom-up for accuracy: Anchor TAM/SAM/SOM with bottom-up grounded in
    how your business works. Cross-check against top-down.") rather than inventing
    a new rule such as averaging or taking the larger/smaller figure.

    Returns (figures, source_approach):
      - figures: {"tam": .., "sam": .., "som": ..}, each a float or None when the
        nested value is missing/non-numeric.
      - source_approach: "bottom_up" | "top_down" | None (neither approach present,
        or sizing.json is absent/corrupt/a stub — callers already coerce those to
        a plain dict or None before reaching here).
    """
    figures: dict[str, float | None] = {"tam": None, "sam": None, "som": None}
    if not isinstance(sizing, dict):
        return figures, None

    bottom_up = _as_dict(sizing.get("bottom_up"))
    top_down = _as_dict(sizing.get("top_down"))
    if bottom_up:
        source, source_approach = bottom_up, "bottom_up"
    elif top_down:
        source, source_approach = top_down, "top_down"
    else:
        return figures, None

    for metric in ("tam", "sam", "som"):
        val = _as_dict(source.get(metric)).get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            figures[metric] = float(val)
    return figures, source_approach


def _emit_coaching_payload(
    inputs: dict[str, Any],
    methodology: dict[str, Any],
    checklist: dict[str, Any],
    validation_warnings: list[dict[str, str]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
    sizing: dict[str, Any] | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """Build the v0.4.2 coaching_payload for market-sizing (schema_version v0.4.2-market-sizing).

    Read from existing artifacts; do not fabricate fields.
    market-sizing's checklist has only pass/fail/not_applicable (no warn status),
    so warned_items is always an explicit empty list for cross-skill schema consistency.

    tam/sam/som/currency/market_size_approach are resolved via
    _resolve_headline_market_size — see that function for the nested-path
    resolution and the "both"-mode selection rule. currency is never converted
    (a conversion happens only when a money input declares a different source
    currency AND a rate is supplied); otherwise it is only a label on
    the numbers already computed by market_sizing.py.
    """
    market_size, market_size_approach = _resolve_headline_market_size(sizing)
    summary = _as_dict(checklist.get("summary"))

    # Derive a confidence tier from the checklist score_pct so the Context B
    # agent reads it directly from coaching_payload (no fabrication from
    # nonexistent sizing.json/checklist.json fields).
    confidence: str | None = None
    score_pct = summary.get("score_pct")
    if isinstance(score_pct, (int, float)):
        if score_pct >= 85:
            confidence = "high"
        elif score_pct >= 60:
            confidence = "medium"
        else:
            confidence = "low"

    # Compute deck_coverage from inputs.existing_claims (canonical keys only).
    # Non-canonical keys do NOT count here — EXISTING_CLAIMS_SHAPE warning is
    # the dedicated shape signal. Only meaningful when the agent populated at
    # least one canonical figure (proves the deck was reviewed and at least one
    # TAM/SAM/SOM was stated).
    existing_claims = _as_dict(inputs.get("existing_claims"))
    canonical = ("tam", "sam", "som")
    any_stated = any(existing_claims.get(m) is not None for m in canonical)
    deck_coverage: dict[str, Any] | None = None
    if any_stated:
        deck_coverage = {
            "deck_reviewed": True,
            "stated": [m for m in canonical if existing_claims.get(m) is not None],
            "missing": [m for m in canonical if existing_claims.get(m) is None],
        }

    return {
        "schema_version": "v0.4.2-market-sizing",
        "summary": {
            "score_pct": summary.get("score_pct"),
            "overall_status": summary.get("overall_status"),
            "total": summary.get("total"),
            "pass": summary.get("pass"),
            "fail": summary.get("fail"),
            "not_applicable": summary.get("not_applicable"),
        },
        "failed_items": summary.get("failed_items", []),
        "warned_items": [],  # market-sizing has no warn status; explicit empty for schema parity
        # {code, label, message}, matching competitive-positioning — NOT a bare code list. The
        # coaching sub-agent reads this payload and echoes it into commentary the founder reads;
        # handing it only `UNVALIDATED_CLAIMS` is how raw warning codes reached delivered reports.
        # The label gives it something founder-facing to write instead.
        "high_severity_warnings": [
            {
                "code": w["code"],
                "label": _humanize_warning(w["code"]),
                "message": w.get("message", ""),
            }
            for w in validation_warnings
            if w.get("severity") == "high"
        ],
        "company_name": inputs.get("company_name"),
        "methodology": methodology.get("approach_chosen"),
        "confidence": confidence,  # derived from checklist score_pct; null if unavailable
        "deck_coverage": deck_coverage,  # nullable; additive in v0.4.2-market-sizing
        "tam": market_size["tam"],
        "sam": market_size["sam"],
        "som": market_size["som"],
        "currency": currency,
        "market_size_approach": market_size_approach,  # "bottom_up" | "top_down" | null
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
    }


def compose(dir_path: str, report_path: str | None = None) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    # Load all artifacts
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    artifacts_found = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in all_names if artifacts[n] is None]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # Apply accepted_warnings from methodology (medium-severity only, instance-scoped)
    methodology_art = artifacts.get("methodology.json")
    if _usable(methodology_art):
        acceptances: list[dict[str, str]] = []
        for aw in _as_list(methodology_art.get("accepted_warnings")):
            if not isinstance(aw, dict):
                print("Warning: accepted_warnings entry is not an object — skipped", file=sys.stderr)
                continue
            code = aw.get("code", "")
            match_str = aw.get("match", "")
            if not code or not match_str:
                print("Warning: accepted_warnings entry missing 'code' or 'match' — skipped", file=sys.stderr)
                continue
            reason = aw.get("reason", "")
            if not isinstance(reason, str) or not reason.strip():
                print(f"Warning: accepted_warnings entry for '{code}' missing 'reason' — skipped", file=sys.stderr)
                continue
            if code in WARNING_SEVERITY and WARNING_SEVERITY[code] in ACCEPTIBLE_SEVERITIES:
                acceptances.append(
                    {
                        "code": code,
                        "reason": reason,
                        "match": match_str,
                    }
                )
            elif code in WARNING_SEVERITY:
                print(f"Warning: cannot accept high-severity code '{code}' — ignored", file=sys.stderr)
        for w in warnings:
            for acc in acceptances:
                if w["code"] == acc["code"] and acc["match"].lower() in w.get("message", "").lower():
                    w["severity"] = "acknowledged"
                    w["message"] += f" [Accepted: {acc['reason']}]"
                    break

    # Assemble report — treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inputs = _render_safe(artifacts.get("inputs.json"))
    methodology = _render_safe(artifacts.get("methodology.json"))
    validation_data = _render_safe(artifacts.get("validation.json"))
    sizing = _render_safe(artifacts.get("sizing.json"))
    sensitivity = _render_safe(artifacts.get("sensitivity.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))

    # Resolve the analysis currency BEFORE any section renders — every money
    # figure in the report goes through _fmt_usd, which reads this.
    # inputs.json is checked FIRST: it is where the founder's stated currency is
    # recorded at intake, so it outranks whatever the producer defaulted to. A
    # disagreement between the two is separately reported as CURRENCY_MISMATCH.
    _set_currency(_resolve_currency(inputs, sizing, methodology))

    # Compute provenance
    provenance_data: dict[str, dict[str, Any]] | None = None
    if _usable(sizing) and not _is_stub(sizing):
        provenance_data, _ = _compute_provenance(sizing, validation_data, inputs)

    # Render every section EXCEPT Warnings first. The marker pre-scan and the
    # MARKER_COLLISION append must run before the Warnings section is rendered
    # and before status is computed, so that a marker collision is reflected in
    # both validation.status and the report's Warnings section.
    _WARNINGS_PLACEHOLDER = "\x00__WARNINGS_SECTION__\x00"
    sections = [
        _section_title_provenance(inputs, sizing),
        _section_executive_summary(sizing, sensitivity, provenance_data),
        _section_analysis_checklist(checklist, artifacts_found),
        _section_methodology(methodology),
        _section_definitions(),
        _section_sizing_table(sizing, provenance_data),
        _section_deck_claims_narrative(inputs),
        _section_assumptions(validation_data),
        _section_validation(validation_data),
        _section_sensitivity(sensitivity),
        _WARNINGS_PLACEHOLDER,
        _section_sources(validation_data),
    ]

    body_without_warnings = "\n".join(s for s in sections if s != _WARNINGS_PLACEHOLDER)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan: check assembled body BEFORE appending the marker (otherwise we
    # always find our own emission). Agent post-Edit verification uses the
    # EXACT uuid (per-run), so substring collisions with body content are
    # informational only — but worth flagging so authors can sanitize.
    if "<!-- COACHING_INSERTION_POINT_" in body_without_warnings:
        warnings.append(
            _warn(
                "MARKER_COLLISION",
                (
                    "Body content contains marker substring; agent post-Edit verification "
                    "uses the EXACT uuid (per-run) so this is informational only — "
                    "body sanitization recommended."
                ),
            )
        )

    # Determine status AFTER all warnings (including MARKER_COLLISION) are known.
    status = "clean" if not warnings else "warnings"

    # Splice the Warnings section in now that the warnings list is final.
    report_markdown = "\n".join(_section_warnings(warnings) if s == _WARNINGS_PLACEHOLDER else s for s in sections)

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Market Sizing Agent"
        " · [Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
    )

    # --- founder-text policy (shared fleet module) ------------------------------------------------
    # MUST run on the FINAL assembled markdown, after the warnings section and the footer: that is the
    # exact string the founder reads, and producer warning messages are where the internal tokens
    # live. Hooking in before the warnings splice substitutes nothing and reports a clean body.
    _ft = _founder_text_policy()
    if _ft is not None:
        # No data-derived keep-set here. `identifier_values` is cap-table-only by design: this skill
        # uses `id` for a metric's NAME (`unit_economics.metrics[].id == "gross_margin"`), which is our
        # vocabulary and must be humanized, not a handle the founder cross-references. Keeping it left
        # "ARPU $500 x gross_margin 0.75" in a delivered report AND suppressed the warning, since the
        # scan honours the same keep-set.
        report_markdown = _ft.substitute(report_markdown)
        # Our own warning codes are kept: compose renders them in small print beside a humanized
        # label (the md_term convention), which is deliberate. A code leaking anywhere else is
        # caught by the skill's own gate, not by widening this scan into a false positive.
        _found = _ft.scan(report_markdown, extra_keep=frozenset(WARNING_SEVERITY))
        for _tok in _found["enums"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report contains the internal token '{_tok}' — a founder cannot act on it; "
                    f"render it through the shared founder-text policy or stop emitting it",
                )
            )
        for _fn in _found["filenames"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report names the internal file '{_fn}' — drop the reference rather than renaming it",
                )
            )

    # Stderr summary
    print(f"Artifacts found: {len(artifacts_found)}/{len(all_names)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        print(f"Warnings: {len(high)} high, {len(medium)} medium", file=sys.stderr)
        for w in warnings:
            print(f"  [{w['severity'].upper()}] {w['code']}: {w['message']}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)

    # v0.4.2 Mitigation 2: structured coaching payload for Context B agent.
    # Use the same uuid marker generated above as the single source of truth.
    resolved_report_path = report_path or os.path.join(os.path.abspath(dir_path), "report.md")
    coaching_payload = _emit_coaching_payload(
        inputs=_as_dict(inputs),
        methodology=_as_dict(methodology),
        checklist=_as_dict(checklist),
        validation_warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
        sizing=sizing,
        currency=_CURRENCY,
    )

    result = {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
        },
        "coaching_payload": coaching_payload,
    }

    if provenance_data:
        result["provenance"] = provenance_data

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose market sizing report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--strict", action="store_true", help="Exit 1 on high/medium-severity warnings (CI mode)")
    p.add_argument(
        "--write-md",
        help="Also write the report markdown to this path (in addition to JSON output via -o)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    report_path = os.path.abspath(args.write_md) if args.write_md else None
    result = compose(args.dir, report_path=report_path)

    if args.write_md:
        report_markdown = result.get("report_markdown", "")
        md_path = os.path.abspath(args.write_md)
        parent = os.path.dirname(md_path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                print(f"Error: cannot create directory for --write-md: {e}", file=sys.stderr)
                sys.exit(2)
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(report_markdown if report_markdown.endswith("\n") else report_markdown + "\n")
        except OSError as e:
            print(f"Error: cannot write --write-md file: {e}", file=sys.stderr)
            sys.exit(2)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    v = result["validation"]
    _write_output(
        out,
        args.output,
        summary={"validation": v["status"], "warnings": len(v["warnings"])},
    )

    # Post-write on-disk verification: confirm declared output files exist and are non-empty.
    if args.output:
        abs_out = os.path.abspath(args.output)
        if not os.path.isfile(abs_out) or os.path.getsize(abs_out) == 0:
            print(
                f"Error: output file missing or empty after write: {abs_out}",
                file=sys.stderr,
            )
            sys.exit(2)
    if args.write_md:
        abs_md = os.path.abspath(args.write_md)
        if not os.path.isfile(abs_md) or os.path.getsize(abs_md) == 0:
            print(
                f"Error: --write-md file missing or empty after write: {abs_md}",
                file=sys.stderr,
            )
            sys.exit(2)

    if args.strict:
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] in ("high", "medium")]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
