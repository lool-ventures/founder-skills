#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Scenario orchestrator — dispatches to the right math producer per type.

Reads a scenario request (type + parameters), routes to the appropriate
math producer (safe_conversion, note_conversion, priced_round, flip),
collects results into a scenarios.json entry per the rev15 conditional
schema, and writes the combined scenarios.json.

Per design doc §9 Step 5: the solver respects the §6 apply contract by
consuming rule_audit.json.gating (NOT the rule pack directly). For v0.1
the gating is permissive (all applicable rules apply) and the solver
focuses on math correctness; structured `applies_when_match` predicates
are a Phase 2 deliverable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artifact_io import id_missing, instrument_id_blockers  # noqa: E402
from _artifact_writer import ArtifactValidationError, load_schema, write_artifact  # noqa: E402
from _rule_pack import RULE_PACK_VERSION  # noqa: E402
from flip_scenario import flip_share_for_share  # noqa: E402
from note_conversion import (  # noqa: E402
    convert_note,
    derive_scenario_completeness,
    note_has_usable_math_inputs,
)
from priced_round import solve_priced_round  # noqa: E402
from safe_conversion import (  # noqa: E402
    convert_safes_cap_implied,
    detect_mfn_cycles,
    safe_has_usable_purchase_amount,
)

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)


def _resolve_target_basis(params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Resolve the priced-round solver's `target_basis` for one scenario request.

    Mirrors note_conversion.py's `maturity_default_treatment_defaulted` disclosure pattern:
    when the founder's scenario request omits `target_basis`, the solver still needs a definite
    denominator string to run — but pre-money vs post-money vs post-money-excluding-converting-
    securities is a term-sheet-specific negotiation point, not a settled default. Silently
    defaulting to pre_money would present an assumption as a founder-confirmed input.

    Returns `(basis, warning_or_None)`. No target_pool_percent means no pool top-up is being
    modeled, so target_basis has no math effect — defaulting it is a no-op, not an assumption,
    and no warning is emitted.
    """
    if "target_basis" in params:
        return params["target_basis"], None
    if not params.get("target_pool_percent"):
        return "pre_money", None
    warning = {
        "code": "target_basis_defaulted",
        "severity": "medium",
        "message": (
            "target_basis was not specified for this priced-round scenario; the solver "
            "defaulted to 'pre_money'. Option-pool denominator choice (pre-money vs post-money "
            "vs post-money-excluding-converting-securities) is a term-sheet-specific negotiation "
            "point, not a settled default — confirm which basis applies before relying on the "
            "resulting pool top-up shares and post-round ownership figures."
        ),
    }
    return "pre_money", warning


def _compute_founder_impact(
    aggregate: dict[str, float],
    cap_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Compute founder impact (before/after %) — rendered as plain language."""
    founders = cap_state.get("founders", [])
    if not founders:
        return None
    founder_total = sum(int(f.get("common_shares", 0)) for f in founders)
    pre_fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    before_pct = founder_total / pre_fd if pre_fd else 0.0
    after_pct = aggregate.get("founders_pct", 0.0)
    delta_pp = (after_pct - before_pct) * 100  # percentage points
    plain = (
        f"Founders collectively held {before_pct:.1%} of fully-diluted shares before this scenario; "
        f"after, {after_pct:.1%}. That's {delta_pp:+.1f} percentage points."
    )
    return {
        "before_pct": before_pct,
        "after_pct": after_pct,
        "delta_pp": delta_pp,
        "plain_language": plain,
    }


def run_safe_conversion_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    safes_filter = params.get("safe_ids")
    all_safes = [s for s in instruments.get("safes", []) if safe_has_usable_purchase_amount(s)]
    safes = [s for s in all_safes if not safes_filter or s["id"] in safes_filter]

    blockers: list[dict[str, Any]] = []

    # Check for circular MFN
    cycles = detect_mfn_cycles(safes)
    if cycles:
        blockers.append(
            {
                "code": "E_SAFE_CIRCULAR_MFN",
                "instance_id": ",".join(sorted(c for cycle in cycles for c in cycle)),
                "remedy": "Break the circular MFN chain or provide conversion_price_override.",
            }
        )

    pre_fd = cap_state["as_converted_totals"]["fully_diluted_shares"]
    priced_pre = params.get("priced_round_pre_money")
    priced_new = params.get("priced_round_new_money")

    # A convertible note is a CONVERTING SECURITY, so it belongs in the post-money SAFE's Company
    # Capitalization (rule `safe.company_capitalization_yc_post_money`). NEITHER arm of this function
    # counts one: the cap-implied arm cannot price a note without a round, and the priced arm below
    # delegates with a hardcoded `notes=[]`. Refuse on both rather than silently omit, which
    # understates the denominator and overstates every SAFE's ownership.
    #
    # This sits ABOVE the arm split deliberately, and returns rather than appending to `blockers`.
    # It used to live inside the cap-implied arm and name `priced_round_pre_money` /
    # `priced_round_new_money` as the remedy -- which are THIS function's params, so following it
    # crossed to the arm that drops the note, converting a loud refusal into a silent overstatement.
    # Appending to `blockers` here would not help either: the priced arm returns the solver's output
    # directly and never reads that list.
    #
    # `run_priced_round_scenario` is the route that actually counts notes (it passes
    # `instruments["convertible_notes"]` through), and its params are `pre_money` / `new_money`.
    notes = instruments.get("convertible_notes") or []
    if notes:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_CAP_IMPLIED_NOTES_PRESENT",
                    "instance_id": None,
                    "remedy": (
                        f"{len(notes)} convertible note(s) are outstanding. A note converts only "
                        "against a priced round, but it counts in the post-money SAFE denominator, "
                        "so converting the SAFEs without it would overstate their ownership. Author "
                        "a `priced_round` scenario (parameters `pre_money` / `new_money`) — that "
                        "route converts the notes alongside the SAFEs."
                    ),
                }
            ],
            "per_safe": [],
            "math_provenance": [
                {
                    "output_field": "blockers",
                    "source_type": "rule",
                    "rule_id": "safe.company_capitalization_yc_post_money",
                    "rule_pack_version": RULE_PACK_VERSION,
                    "source_ref": None,
                }
            ],
        }

    per_safe: list[dict[str, Any]] = []
    if priced_pre is None or priced_new is None:
        # Cap-implied path only. MFN elections need a priced round to resolve against
        # (the cap-implied path has no election path) — surface a blocker once rather
        # than silently dropping the param.
        if params.get("mfn_elections"):
            blockers.append(
                {
                    "code": "E_SAFE_MFN_ELECTION_REQUIRES_PRICED_ROUND",
                    "instance_id": None,
                    "remedy": "mfn_elections requires a priced round (priced_round_pre_money / "
                    "priced_round_new_money); the cap-implied path cannot resolve an MFN election.",
                }
            )
        company_capitalization: float | None = None
        if not blockers:
            solved = convert_safes_cap_implied(safes, pre_financing_fd=pre_fd)
            if solved["branch"] == "rejected":
                blockers.append(
                    {
                        "code": solved.get("error", "E_UNKNOWN"),
                        "instance_id": None,
                        "remedy": solved.get("reason", "unspecified"),
                    }
                )
            else:
                per_safe = solved["per_safe"]
                company_capitalization = solved["company_capitalization"]

        outputs: dict[str, Any] = {
            "completeness": "structural_only",
            "cap_implied_only": True,
            "blockers": blockers,
            "per_safe": per_safe,
            # The denominator the percentages are measured against. Emitted so a reader (and the e2e
            # lane's self-consistency check) can verify `shares / company_capitalization` equals the
            # stated ownership, rather than re-deriving a base and getting a different answer.
            "company_capitalization": company_capitalization,
            "math_provenance": [
                {
                    "output_field": "cap_implied_outputs",
                    "source_type": "rule",
                    "rule_id": "safe.stacked_post_money_caps",
                    "rule_pack_version": RULE_PACK_VERSION,
                    "source_ref": None,
                }
            ],
        }
        return outputs

    # Has a priced round — delegate to solver
    target_basis, tb_warning = _resolve_target_basis(params)
    priced_outputs = solve_priced_round(
        cap_state=cap_state,
        safes=safes,
        # Unreachable with notes outstanding: the guard above returns before this point. Kept
        # explicit so the empty list reads as an asserted invariant rather than an omission.
        notes=[],
        pre_money=priced_pre,
        new_money=priced_new,
        target_pool_percent=params.get("target_pool_percent"),
        target_basis=target_basis,
        conversion_event_date=params.get("transaction_event_date"),
        mfn_elections=params.get("mfn_elections"),
    )
    if tb_warning:
        priced_outputs.setdefault("warnings", [])
        priced_outputs["warnings"].append(tb_warning)
    return priced_outputs


def run_note_conversion_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    notes_filter = params.get("note_ids")
    all_notes = instruments.get("convertible_notes", [])

    # POINT-OF-USE GUARD, because this route reads RAW `instruments.json` and never the canonical
    # cap_state arrays. `build_cap_state`'s uniqueness check therefore does not protect it: measured,
    # a clean artifact built from good instruments plus a scenario run against dirty ones produced
    # `completeness: "full"`, zero blockers, and 720,000 shares where the truth was 1,120,000,
    # because `per_note[n["id"]]` below keeps one row for two notes while the total counts both.
    #
    # It also fixes the `n["id"]` subscript on the next line, which raised a bare KeyError on a note
    # with no id at all -- an untyped crash out of a route whose refusal channel is typed blockers.
    id_blockers = instrument_id_blockers(all_notes, "convertible_notes")
    if id_blockers:
        return {
            "completeness": "structural_only",
            "blockers": id_blockers,
            "per_note": [],
            "math_provenance": [],
        }

    notes = [n for n in all_notes if not notes_filter or n["id"] in notes_filter]
    # Partial/blank notes (null principal / missing issuance_date) would crash convert_note; exclude
    # them from the math and surface them as terms-only, never silently dropped.
    usable_notes = [n for n in notes if note_has_usable_math_inputs(n)]
    terms_only_notes = [n for n in notes if not note_has_usable_math_inputs(n)]

    conv_date = params.get("transaction_event_date")
    if not conv_date:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_NOTE_NO_CONVERSION_DATE",
                    "instance_id": None,
                    "remedy": "Provide transaction_event_date for note conversion.",
                }
            ],
            "per_note": [],
            "math_provenance": [],
        }

    priced_new = params.get("priced_round_new_money")
    qfp = params.get("qualified_financing_price")
    per_note: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for n in usable_notes:
        r = convert_note(
            n,
            conversion_event_date=conv_date,
            priced_round_new_money=priced_new,
            qualified_financing_price=qfp,
        )
        r["id"] = n["id"]
        per_note.append(r)
        if "error" in r:
            blockers.append(
                {
                    "code": r["error"],
                    "instance_id": n["id"],
                    "remedy": r.get("reason", ""),
                }
            )

    completeness = derive_scenario_completeness(per_note)

    # Surface terms-only notes (excluded from math above) so they never vanish silently.
    for n in terms_only_notes:
        per_note.append(
            {
                "id": n["id"],
                "branch": "terms_only_excluded",
                "reason": "principal or issuance_date absent in the document — terms-only, not converted",
            }
        )
    out: dict[str, Any] = {
        "completeness": completeness,
        "blockers": blockers,
        "per_note": per_note,
        "math_provenance": [],
    }

    # Aggregate cash repayment when at least one note hit repay branch
    cash = sum(p.get("cash_repayment", 0.0) for p in per_note if p.get("branch") == "maturity_repay")
    if cash > 0:
        out["aggregate_cash_repayment"] = cash

    return out


def run_priced_round_scenario(
    scenario: dict[str, Any],
    *,
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    last_priced_round_pps: float | None = None,
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}

    # §6.1.5: pre-round warrant pump. Runs against the pre-pump cap_state for
    # warrants whose exercise_event_date is strictly before the scenario's
    # transaction_event_date. The post-pump cap_state is what the priced-round
    # solver consumes.
    import warrant_exercise

    try:
        cap_state_post_pump, warrant_events = warrant_exercise.run_pre_round_pump(
            cap_state,
            params.get("transaction_event_date"),
            last_priced_round_pps=last_priced_round_pps,
            pre_money=params.get("pre_money"),
        )
    except warrant_exercise.WarrantPumpError as e:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": str(e).split(":", 1)[0],
                    "instance_id": None,
                    "remedy": str(e).split(":", 1)[1].strip() if ":" in str(e) else str(e),
                }
            ],
            "math_provenance": [],
        }

    # The coverage detector (detect_structure.py) emits a priced-round request whose `parameters`
    # it CANNOT populate: pre_money and new_money are the founder's round terms, absent from
    # inputs.json/instruments.json by construction. SKILL.md tells the caller to extend the route's
    # request with those answers -- but a caller that runs it verbatim used to reach the bare
    # subscripts below and die on an uncaught KeyError traceback. A missing round term is a normal
    # not-enough-information state, so report it the way every other such state is reported: a typed
    # blocker on a structural_only result.
    _missing = [k for k in ("pre_money", "new_money") if params.get(k) is None]
    if _missing:
        return {
            "completeness": "structural_only",
            "blockers": [
                {
                    "code": "E_MISSING_PARAMETER",
                    "instance_id": None,
                    "remedy": (
                        "priced_round needs " + " and ".join(_missing) + " in scenario_requests.json. "
                        "The coverage route cannot supply round terms -- add the founder's stated "
                        "pre-money and new-money before running this scenario."
                    ),
                }
            ],
            "math_provenance": [],
        }

    _acq = params.get("acquisition")
    _acq_for_solver = (
        _acq
        if (
            isinstance(_acq, dict)
            and _acq.get("acquisition_timing", "concurrent_with_round") == "concurrent_with_round"
        )
        else None
    )
    target_basis, tb_warning = _resolve_target_basis(params)
    result = solve_priced_round(
        cap_state=cap_state_post_pump,
        safes=instruments.get("safes", []),
        notes=instruments.get("convertible_notes", []),
        pre_money=params["pre_money"],
        new_money=params["new_money"],
        target_pool_percent=params.get("target_pool_percent"),
        target_basis=target_basis,
        conversion_event_date=params.get("transaction_event_date"),
        mfn_elections=params.get("mfn_elections"),
        pre_money_basis=params.get("pre_money_basis", "includes_safe_conversion"),
        acquisition={"consideration_pct": _acq_for_solver["consideration_pct"]} if _acq_for_solver else None,
        pool_consideration_basis=params.get("pool_consideration_basis", "include"),
    )
    if tb_warning:
        result.setdefault("warnings", [])
        result["warnings"].append(tb_warning)

    if warrant_events:
        result["warrant_exercise_events"] = warrant_events
        # Phase F (v0.5.0): embed post-pump cap_state delta so downstream
        # debugging + the §4.5 FD-sum invariant can trip on future regressions.
        # Only the changing parts are embedded (per reviewer Q10 recommendation)
        # — full cap_state would duplicate top-level metadata. Schema-locked in
        # scenarios.schema.json via cap_state_pump_delta sub-schema.
        result["cap_state_after_pump"] = {
            "as_converted_totals": cap_state_post_pump.get("as_converted_totals", {}),
            "outstanding_warrants": cap_state_post_pump.get("outstanding_warrants", []),
            "cap_table_history": cap_state_post_pump.get("cap_table_history", []),
        }

    # Augment with founder_impact when completeness is full/mixed
    if result.get("completeness") in {"full", "mixed"}:
        result["founder_impact"] = _compute_founder_impact(
            result.get("aggregate_ownership_by_class", {}), cap_state_post_pump
        )
    return result


def run_flip_scenario(
    scenario: dict[str, Any],
    *,
    cap_state: dict[str, Any],
    instruments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = scenario.get("parameters", {}) or {}
    return flip_share_for_share(
        cap_state,
        instruments=instruments,
        iia_grants_in_history=params.get("iia_grants_in_history", False),
        section_102_grants_outstanding=params.get("section_102_grants_outstanding", 0),
    )


def run_all_scenarios(
    *,
    inputs: dict[str, Any],
    instruments: dict[str, Any],
    cap_state: dict[str, Any],
    scenario_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dispatch each scenario_request to the right runner and collect outputs.

    SCENARIO IDS MUST BE UNIQUE AND NON-BLANK, checked here because this is where they are first
    consumed as keys. The math itself survives a repeat -- both scenarios are computed and both come
    back -- so the damage is entirely downstream and entirely silent:

      * `rule_audit`'s gating map keys on `f"scenario:{scenario_id or 'global'}"`, so two scenarios
        sharing an id (or both blank, which collapse onto `scenario:global`) keep ONE gating entry.
        Measured: two scenarios in, one `date_sensitive_watchlist` row out. That row is rendered to
        the founder in `report.md`, so a real financing date's sensitivity status -- whether it
        falls inside or outside a legal window -- disappears with no error, no warning, and no
        count anywhere that looks wrong.
      * `flip_outputs[req["scenario_id"]]` below collapses the same way, mis-routing a chained
        scenario's `chained_from_scenario_id` lookup to the wrong parent.

    Unlike the instrument ids, a `scenario_id` is authored here rather than extracted from a
    document, so this is a caller error rather than a document-reading error -- but it is unchecked
    everywhere (no schema `uniqueItems`, no runtime test), and its cost is a founder-visible row
    quietly missing rather than a visibly wrong number.
    """
    _sids = [r.get("scenario_id") for r in scenario_requests]
    _blank = sum(1 for s in _sids if id_missing(s))
    if _blank:
        raise ValueError(
            f"E_SCENARIO_ID_MISSING: {_blank} of {len(_sids)} scenario requests carry no scenario_id. "
            "Scenario ids key the rule-audit gating map and the chained-scenario lookup, so a blank "
            "one silently merges two scenarios' results. Give each scenario request a distinct, "
            "non-blank scenario_id."
        )
    _dupes = sorted({str(s) for s in _sids if _sids.count(s) > 1})
    if _dupes:
        raise ValueError(
            f"E_SCENARIO_ID_DUPLICATE: scenario_id(s) {', '.join(_dupes)} appear more than once. "
            "Scenario ids key the rule-audit gating map and the chained-scenario lookup, so a repeat "
            "drops one scenario's date-sensitivity rows from the report with no warning. Give each "
            "scenario request a distinct scenario_id."
        )

    results = []
    flip_outputs: dict[str, dict[str, Any]] = {}
    for req in scenario_requests:
        stype = req.get("type")
        step_cap_state = cap_state
        step_instruments = instruments
        chained = req.get("chained_from_scenario_id")
        if chained and chained in flip_outputs:
            fo = flip_outputs[chained]
            step_cap_state = fo.get("post_flip_cap_state", cap_state)
            step_instruments = fo.get("post_flip_instruments") or instruments
        if stype == "safe_conversion":
            outputs = run_safe_conversion_scenario(req, instruments=step_instruments, cap_state=step_cap_state)
        elif stype == "note_conversion":
            outputs = run_note_conversion_scenario(req, instruments=step_instruments, cap_state=step_cap_state)
        elif stype == "priced_round":
            outputs = run_priced_round_scenario(req, instruments=step_instruments, cap_state=step_cap_state)
        elif stype == "flip":
            outputs = run_flip_scenario(req, cap_state=step_cap_state, instruments=step_instruments)
            flip_outputs[req["scenario_id"]] = outputs
        else:
            outputs = {
                "completeness": "structural_only",
                "blockers": [
                    {
                        "code": "E_UNKNOWN_SCENARIO_TYPE",
                        "instance_id": req.get("scenario_id"),
                        "remedy": f"Unknown scenario type: {stype}",
                    }
                ],
                "math_provenance": [],
            }
        results.append(
            {
                "scenario_id": req["scenario_id"],
                "label": req.get("label", req["scenario_id"]),
                "type": stype,
                "parameters": req.get("parameters", {}),
                "computed_outputs": outputs,
            }
        )
    return results


def _fail(code: str, message: str, output_path: str) -> None:
    """The four-property loud-failure contract (CLAUDE.md, Script Conventions).

    Machine-readable diagnostic on stdout, a line on stderr, `-o` left untouched, and the caller
    returns non-zero. Split out so every refusal in `main()` states all four rather than three.
    """
    sys.stdout.write(json.dumps({"validation": {"status": "invalid", "errors": [f"{code}: {message}"]}}) + "\n")
    sys.stderr.write(f"run_scenario.py: {code}: {message}\n")
    sys.stderr.write(f"run_scenario.py: {os.path.abspath(output_path)} was left unchanged.\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True)
    p.add_argument("--instruments", required=True)
    p.add_argument("--cap-state", required=True)
    p.add_argument("--scenarios-input", required=True, help="JSON file with list of scenario requests")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    with open(args.instruments, encoding="utf-8") as f:
        instruments = json.load(f)
    with open(args.cap_state, encoding="utf-8") as f:
        cap_state = json.load(f)
    with open(args.scenarios_input, encoding="utf-8") as f:
        scenario_requests = json.load(f)
    if isinstance(scenario_requests, dict):
        scenario_requests = scenario_requests.get("scenarios", [])

    # STALENESS IS CHECKED BEFORE THE MATH, NOT AFTER IT. `compose_report.validate_run_id_parity`
    # already catches a run_id mismatch -- but it runs at the END, so by then the numbers have been
    # computed from mismatched artifacts and the founder is shown a high-severity warning ABOUT a
    # report rather than being spared the report. Nothing stopped a fresh `instruments.json` being
    # run against a stale `cap_state.json`, and the two disagree in exactly the way that matters:
    # `cap_state` carries the share counts every percentage is measured against, while
    # `instruments` carries what converts into them.
    #
    # This refuses instead of warning because a producer that cannot trust its inputs has nothing
    # useful to emit, and because the remedy is mechanical (re-run the earlier step). Deliberately
    # NOT a `run_id` equality check against `--run-id`: the three artifacts must agree with EACH
    # OTHER, and an artifact carrying no run_id at all is its own defect, reported separately so
    # the remedy differs ("re-run the step that wrote it" vs "re-run both steps").
    _rids = {
        "inputs.json": (inputs.get("metadata") or {}).get("run_id"),
        "instruments.json": (instruments.get("metadata") or {}).get("run_id"),
        "cap_state.json": (cap_state.get("metadata") or {}).get("run_id"),
    }
    _absent = sorted(n for n, r in _rids.items() if id_missing(r))
    if _absent:
        _fail(
            "E_ARTIFACT_RUN_ID_MISSING",
            f"{', '.join(_absent)} carries no run identifier, so it cannot be checked against the "
            "other artifacts in this run. Re-run the step that wrote it.",
            args.output,
        )
        return 1
    if len(set(_rids.values())) > 1:
        _seen = "; ".join(f"{n}={r}" for n, r in _rids.items())
        _fail(
            "E_ARTIFACT_RUN_ID_MISMATCH",
            f"these artifacts are from different runs ({_seen}), so the share counts and the "
            "instruments that convert into them do not describe the same cap table. Re-run the "
            "earlier steps so all three come from one run.",
            args.output,
        )
        return 1

    scenarios = run_all_scenarios(
        inputs=inputs,
        instruments=instruments,
        cap_state=cap_state,
        scenario_requests=scenario_requests,
    )

    data = {"scenarios": scenarios}
    schema = load_schema(os.path.join(_SCHEMA_DIR, "scenarios.schema.json"))
    try:
        receipt = write_artifact(
            data=data,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"run_scenario.py: schema validation failed: {e}\n")
        return 1
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    if args.pretty:
        for s in scenarios:
            co = s["computed_outputs"]
            sys.stderr.write(
                f"  {s['scenario_id']} ({s['type']}): "
                f"completeness={co.get('completeness')} | "
                f"blockers={len(co.get('blockers', []))}\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
