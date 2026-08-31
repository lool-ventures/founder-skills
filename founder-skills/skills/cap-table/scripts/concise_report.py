#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Concise answer from the deterministic engine — the lightweight math path.

Renders the headline numbers a founder asked for straight from `scenarios.json`
(the solver's `computed_outputs`), plus any counsel / date-sensitive flags from
`rule_audit.json`, into a short cited markdown answer — WITHOUT the heavy tail
(no HTML, no interactive explorer, no counsel packet, no coaching sub-agent).

Use for a single quick MATH question that is neither a pure eligibility/date
lookup (use `verify_one.py`) nor a priced-round gut-check (use `quick_assess.py`)
— e.g. a fully-diluted warrant count, an as-converted snapshot, a standalone
anti-dilution adjustment. The NUMBERS are identical to the full pipeline's: this
reads the same `run_scenario.py` output, it does not recompute. The only thing
dropped is production weight, never correctness.

Pipeline: cap_state -> rule_audit --phase=pre_math -> run_scenario
          -> rule_audit --phase=post_math (optional, cheap) -> concise_report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _warning_callouts  # noqa: E402

# aggregate_ownership_by_class keys -> founder-facing labels (same data the full
# report renders; only the presentation is lighter).
CLASS_LABELS = [
    ("founders_pct", "Founders"),
    ("preferred_pct", "Preferred"),
    ("safe_pct", "SAFEs"),
    ("note_pct", "Notes"),
    ("option_pool_pct", "Option pool"),
    ("new_money_pct", "New investors"),
]

RELIANCE_BOUNDARY = (
    "Counsel-review items below are flags, not conclusions: state the cited fact "
    "and defer eligibility/qualification to counsel."
)


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def _ownership_lines(co: dict) -> list[str]:
    agg = co.get("aggregate_ownership_by_class") or {}
    rows = [f"- **{label}:** {_pct(agg[key])}" for key, label in CLASS_LABELS if agg.get(key) not in (None,)]
    return rows


def _scenario_facts(co: dict) -> list[str]:
    """Every founder-facing FACT line for one scenario, and nothing else.

    Separated from `_scenario_block` so the pre-write gate can ask "did this render anything?"
    by COUNTING what the renderer produced, rather than pattern-matching the rendered prose.
    The header, the completeness note and the trailing blank are deliberately not facts: a block
    consisting only of those is the empty answer the gate must refuse.
    """
    out: list[str] = []

    price = co.get("equity_financing_price")
    if price is not None:
        out.append(f"- **Price per share:** ${float(price):,.4f}")

    per_safe = co.get("per_safe") or []

    # PRICED conversion. The cap-implied arm emits a different key set entirely (below), so this
    # loop must stay keyed on the priced fields -- widening it to cover both is what would break
    # the priced path.
    for s in per_safe:
        sid = s["id"]
        cp = s.get("conversion_price")
        shares = s.get("conversion_shares")
        if cp is not None:
            bits = f"converts at ${float(cp):,.4f}"
            if shares is not None:
                bits += f" → {round(float(shares)):,} shares"
            out.append(f"- **SAFE {sid}:** {bits}")

    own = _ownership_lines(co)
    if own:
        out.extend(own)
        fd = co.get("post_round_fully_diluted_shares")
        if fd:
            out.append(f"- **Fully-diluted total:** {round(float(fd)):,} shares")
    elif co.get("cap_implied_only") and per_safe:
        # CAP-IMPLIED snapshot -- a separate block, mirroring `compose_report._render_scenarios`
        # and `visualize`. Gated on `per_safe` as well as the flag: a BLOCKED cap-implied run
        # carries `cap_implied_only: True` with an empty `per_safe`, and heading a refusal with an
        # ownership label prints a promise with nothing under it.
        rows = [r for r in per_safe if "cap_implied_ownership" in r]
        if rows:
            out.append("- **Cap-implied ownership (pre-financing):**")
            for r in rows:
                sid = r["id"]
                bits = _pct(r["cap_implied_ownership"])
                price_i = r.get("safe_price")
                shares_i = r.get("cap_implied_shares")
                if price_i is not None:
                    bits += f" (SAFE price ${float(price_i):,.4f}"
                    if shares_i is not None:
                        bits += f", {round(float(shares_i)):,} shares"
                    bits += ")"
                out.append(f"  - **{sid}:** {bits}")

    # A blocked run's answer IS the blocker. Carry the remedy, not the bare code: the code alone is
    # internal vocabulary, and `compose_report` already renders both to the founder.
    for b in co.get("blockers") or []:
        if isinstance(b, dict):
            code = b.get("code")
            remedy = (b.get("remedy") or "").strip()
            where = f" on {b['instance_id']}" if b.get("instance_id") else ""
            out.append(f"- ⚠️ **Blocked** (`{code}`{where}){f': {remedy}' if remedy else ''}")
        else:
            out.append(f"- ⚠️ **Blocked** (`{b}`)")

    return out


def _scenario_block(scenario: dict) -> list[str]:
    co = scenario.get("computed_outputs", {}) or {}
    label = scenario.get("label") or scenario.get("scenario_id") or "Scenario"
    completeness = co.get("completeness", "structural_only")

    out = [f"### {label}"]
    out.extend(_scenario_facts(co))
    if completeness not in {"full", "mixed"}:
        out.append(f"- _(completeness: {completeness} — not a post-financing table)_")
    out.append("")
    return out


def _flag_lines(rule_audit: dict | None) -> list[str]:
    if not rule_audit:
        return []
    out: list[str] = []
    counsel = rule_audit.get("counsel_review_items") or rule_audit.get("counsel_items") or []
    watch = rule_audit.get("date_sensitive_watchlist") or []
    if counsel:
        out.append("**Counsel review:**")
        for item in counsel:
            rid = item.get("rule_id") or item.get("id") if isinstance(item, dict) else item
            title = item.get("title") if isinstance(item, dict) else None
            out.append(f"- {rid}" + (f" — {title}" if title else ""))
    if watch:
        out.append("**Date-sensitive:**")
        for w in watch:
            rid = w.get("rule_id") or w.get("id") if isinstance(w, dict) else w
            out.append(f"- {rid}")
    if counsel:
        out.append("")
        out.append(f"> {RELIANCE_BOUNDARY}")
    return out


def render(inputs: dict, scenarios_doc: dict, rule_audit: dict | None, cap_state: dict | None = None) -> str:
    company = inputs.get("company_name", "Your company")
    scenarios = scenarios_doc.get("scenarios", []) or []
    lines = [f"# {company} — concise cap-table answer", ""]
    # cap_state warnings → founder-facing callouts via the SHARED renderer (single source of truth with
    # compose_report). A standalone quick question routes to concise mode (SKILL.md Step-5-concise), so
    # this is the only path it takes — surfacing the full family set here (not just W_ANTI_DILUTION) keeps
    # W_CAP_BASE_ASSUMED / W_AOA_ONLY_NO_INSTRUMENTS / W_FOUNDER_LOOKS_LIKE_INVESTOR from being silently
    # dropped on that route.
    lines.extend(_warning_callouts.render_warning_callouts((cap_state or {}).get("warnings") or []))
    # SOLVER warnings are a second channel -- dicts on `computed_outputs.warnings`, not cap_state
    # strings. Rendering one is not rendering the other, and the concise route is where a founder
    # asks a single question and gets a single answer, so an unlabelled MFN counterfactual here is
    # the whole answer being wrong.
    lines.extend(_warning_callouts.render_solver_warning_callouts(_warning_callouts.collect_solver_warnings(scenarios)))
    for sc in scenarios:
        lines.extend(_scenario_block(sc))
    flags = _flag_lines(rule_audit)
    if flags:
        lines.append("## Flags")
        lines.extend(flags)
        lines.append("")
    lines.append(
        "_Concise answer (deterministic engine, artifacts skipped). "
        "Want the full report + interactive explorer + counsel packet? Ask for the full review._"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Concise cap-table answer from solver output.")
    p.add_argument("--inputs", required=True, help="inputs.json")
    p.add_argument("--scenarios", required=True, help="scenarios.json (run_scenario output)")
    p.add_argument("--rule-audit", default=None, help="rule_audit.json (optional — adds counsel/date flags)")
    p.add_argument(
        "--cap-state",
        default=None,
        help="cap_state.json (optional — surfaces anti-dilution recovery warnings on the concise route)",
    )
    p.add_argument("--run-id", default=None)
    p.add_argument("-o", "--output-md", required=True, help="path to write the concise markdown")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    try:
        inputs = _load(args.inputs)
        scenarios_doc = _load(args.scenarios)
        rule_audit = _load(args.rule_audit) if args.rule_audit else None
        cap_state = _load(args.cap_state) if args.cap_state else None
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"could not load inputs: {e}"}), file=sys.stderr)
        return 2

    md = render(inputs, scenarios_doc, rule_audit, cap_state=cap_state)

    # DECIDE BEFORE WRITING. This used to write the markdown, then evaluate it, then return 2 --
    # leaving a file the producer itself had just called empty sitting at the founder-facing path.
    # That is the defect `_fail_invalid` exists to prevent (CLAUDE.md, Script Conventions: "-o left
    # untouched"), in its milder form: the original six producers wrote a stub through `-o` and
    # returned 0; this wrote a stub through `-o` and returned 2. The exit code was honest and the
    # artifact was not, and a founder is pointed at the artifact.
    #
    # DECIDE FROM THE DATA, NOT FROM THE PROSE. The previous predicate was
    # `not md.strip() or ("—" in md and "Founders" not in md)`, described in a comment here as an
    # intended truth table. It was not: the title is always `# {company} — concise cap-table
    # answer`, so `"—" in md` is a tautology and the whole thing collapsed to `"Founders" not in
    # md` -- and "Founders" renders only when `aggregate_ownership_by_class.founders_pct` is
    # present. Measured, EVERY documented concise route was refused (cap-implied snapshot, blocked
    # run, priced round with no founders row); only a priced round carrying founders_pct survived.
    # A complete answer was discarded and the founder told it "looks empty".
    #
    # The gate now counts what the renderers actually produced. Any of three kinds of content is a
    # real answer: a scenario fact, a cap_state warning callout, or a rule_audit flag -- a run whose
    # only content is "your cap base is ASSUMED" is still an answer, and refusing it would be the
    # same defect in a new place.
    has_content = (
        any(_scenario_facts(s.get("computed_outputs", {}) or {}) for s in (scenarios_doc.get("scenarios") or []))
        or bool(_warning_callouts.render_warning_callouts((cap_state or {}).get("warnings") or []))
        or bool(_flag_lines(rule_audit))
    )
    rejected = not md.strip() or not has_content
    if rejected:
        payload = {
            "ok": False,
            "path": args.output_md,
            "run_id": args.run_id,
            "warning": "rendered answer looks empty — check scenarios.json computed_outputs",
        }
        print(json.dumps(payload, indent=2 if args.pretty else None))
        print(
            "Error: concise answer rendered empty, no output written: check scenarios.json computed_outputs",
            file=sys.stderr,
        )
        print(f"Error: {os.path.abspath(args.output_md)} was left unchanged.", file=sys.stderr)
        return 2

    with open(args.output_md, "w", encoding="utf-8") as fh:
        fh.write(md)

    receipt = {
        "ok": True,
        "path": args.output_md,
        "scenarios": len(scenarios_doc.get("scenarios", []) or []),
        "bytes": len(md),
        "run_id": args.run_id,
    }
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
