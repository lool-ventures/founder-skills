#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Fast-assess entry mode for the cap-table skill.

Produces a 1-page directional founder-facing markdown report in <60 seconds,
plus a `fast_assess_only.json` sentinel that future cross-skill consumers can
detect to distinguish "cap-table never ran" from "cap-table ran in fast-assess
mode — no structured artifacts available".

Workflow contract (Phase O):

  - Founder describes their cap-table conversationally or via a small JSON
    paste; no document extraction (Lane-1/2/3 extractors are NOT invoked).
  - Inputs are normalized into a minimal in-memory cap-state via the standard
    `cap_state.build_cap_state` helper.
  - The standard priced-round solver runs (so the same correct post-money
    math from `priced_round.py` produces the headline numbers).
  - Output: `fast_assess_only.json` (the sentinel) + a single founder-facing
    `report_fast_assess.md`. NO `inputs.json`, NO `instruments.json`, NO
    `cap_state.json`, NO `scenarios.json`, NO `rule_audit.json`, NO
    `counsel_packet.json`. Downstream skills that need those must request the
    full pipeline.

Directory convention: fast-assess writes to `cap-table-{slug}-fastassess/`
(distinct from the full-pipeline `cap-table-{slug}/`). This eliminates cross-
mode state mutation — both modes can coexist for the same slug and consumers
pick the directory that matches what they need.

Sentinel contract: see `references/sentinel-schema.md` and
`references/schemas/fast_assess_only.schema.json`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from typing import Any

# Import sibling math producers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rule_pack import RULE_PACK_VERSION  # noqa: E402
from cap_state import build_cap_state  # noqa: E402
from priced_round import solve_priced_round  # noqa: E402

SCHEMA_VERSION = "v0.1.0-cap-table-fast-assess"


def _fingerprint(prompt: str, attached_docs: list[str]) -> dict[str, Any]:
    """Stable fingerprint over founder-supplied inputs.

    Lets future consumers detect 'inputs changed since fast-assess ran' and
    decide whether to trust the cached sentinel or trigger a re-run.
    """
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    for d in attached_docs:
        h.update(b"\0")
        h.update(d.encode("utf-8"))
    return {
        "sha256": h.hexdigest(),
        "components": ["founder_prompt_text", *[f"attached_doc:{d}" for d in attached_docs]],
    }


def _percent(p: float) -> str:
    return f"{p * 100:.2f}%"


def _money(m: float) -> str:
    if m >= 1_000_000:
        return f"${m / 1_000_000:.2f}M"
    if m >= 1_000:
        return f"${m / 1_000:,.0f}K"
    return f"${m:,.0f}"


def quick_assess(
    *,
    company_name: str,
    inputs: dict[str, Any],
    safes: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None,
    pre_money: float,
    new_money: float,
    target_pool_percent: float | None,
    target_basis: str,
    event_date: str | None = None,
    founder_prompt: str = "",
    attached_docs: list[str] | None = None,
    run_id_override: str | None = None,
) -> dict[str, Any]:
    """Run a fast-assess directional review.

    Returns the sentinel payload (matching `fast_assess_only.schema.json`)
    AND the founder-facing markdown report as a string under the
    `_report_md` key for the CLI to extract.
    """
    instruments: dict[str, Any] = {
        "safes": safes,
        "convertible_notes": notes or [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": inputs.get("metadata", {}).get("run_id", "fast-assess")},
    }
    cs = build_cap_state(inputs, instruments)

    # When notes are present but no conversion date was supplied, fast-assess
    # defaults to today's date AND discloses the assumption (the math producer
    # solve_priced_round NEVER defaults — it returns a structural blocker). This
    # keeps the directional answer flowing while flagging the assumption.
    assumptions: list[str] = []
    resolved_event_date = event_date
    if (notes or []) and not resolved_event_date:
        resolved_event_date = _dt.date.today().isoformat()
        assumptions.append(
            f"No note conversion date supplied; assumed today ({resolved_event_date}) "
            f"for convertible-note conversion math."
        )

    # Scope note: fast-assess does NOT honor scenario-level mfn_elections overrides — it has
    # no scenario parameters. Baked instrument elections (mfn_provision) still resolve inside
    # the solver. For counterfactual MFN elections, use the full pipeline (run_scenario).
    solver_result = solve_priced_round(
        cap_state=cs,
        safes=safes,
        notes=notes or [],
        pre_money=pre_money,
        new_money=new_money,
        target_pool_percent=target_pool_percent,
        target_basis=target_basis,
        conversion_event_date=resolved_event_date,
    )

    completeness = solver_result.get("completeness", "structural_only")
    drivers: list[dict[str, Any]] = []
    headline: dict[str, Any] = {}

    if completeness == "full":
        agg = solver_result["aggregate_ownership_by_class"]
        headline = {
            "scenarios_summarized": ["priced_round"],
            "founder_impact": {
                "ownership_post_financing_pct": agg["founders_pct"],
                "pps_priced_round": solver_result["equity_financing_price"],
            },
            "branch_summary": (
                f"priced_round: SAFE conversion + "
                f"{int(target_pool_percent * 100) if target_pool_percent else 0}% pool "
                f"+ new money"
            ),
            # R4 LOW.c: drivers expose dilution magnitudes as POSITIVE
            # percentages (the founder's loss attributable to each source).
            # Previously emitted as negative impact_pct which the markdown
            # renderer un-negated, leaving negative values in the sentinel JSON
            # — confusing for external consumers. Now both internal and external
            # representations agree: impact_pct is the dilution magnitude.
            "drivers": [
                {"type": "safe_conversion", "impact_pct": agg["safe_pct"]},
                {"type": "pool_refresh", "impact_pct": agg["option_pool_pct"]},
                {"type": "new_money", "impact_pct": agg["new_money_pct"]},
            ],
        }
        drivers = headline["drivers"]

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = run_id_override if run_id_override else now.replace(":", "").replace("-", "")
    slug = company_name.lower().replace(" ", "-").replace("_", "-")

    sentinel: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "fast_assess",
        "run_id": run_id,
        "company_name": company_name,
        "company_slug": slug,
        "created_at": now,
        "rule_pack_version": RULE_PACK_VERSION,
        "inputs_fingerprint": _fingerprint(founder_prompt, attached_docs or []),
        "produces_canonical_artifacts": False,
        "note": (
            "Fast-assess mode produces a directional 1-page answer only. "
            "No JSON artifacts. See fast_assess_report_path for the markdown deliverable."
        ),
        "headline_data": headline,
        "rerun_hint": (
            "For full structured artifacts (scenarios, counsel packet, anti-dilution, "
            "rule_audit), re-run cap-table without fast-assess mode."
        ),
        "assumptions": assumptions,
    }
    # Surface cap_state warnings (S2 W_CAP_BASE_ASSUMED, S3 W_FOUNDER_LOOKS_LIKE_INVESTOR) into the
    # sentinel too — only when non-empty (the schema declares `warnings` optional; an empty array
    # would still validate but adds noise). This carries the same backstops the full pipeline shows.
    _cs_warnings = list(cs.get("warnings") or [])
    if _cs_warnings:
        sentinel["warnings"] = _cs_warnings

    # Founder-facing markdown
    md_lines: list[str] = []
    md_lines.append(f"# {company_name} — Fast-Assess Cap Table")
    md_lines.append("")
    if "W_CAP_BASE_ASSUMED" in _cs_warnings:
        md_lines.append(
            "> ⚠ **Cap base assumed, not confirmed** — these ownership figures are directional; "
            "confirm founder share counts / pool before relying on them."
        )
        md_lines.append("")
    if "W_FOUNDER_LOOKS_LIKE_INVESTOR" in _cs_warnings:
        md_lines.append(
            "> ⚠ **A listed founder resembles an investment entity** (Ventures/Capital/Fund) — "
            "confirm it is a founder, not an investor."
        )
        md_lines.append("")
    md_lines.append(
        "_Fast-assess mode: a 1-page directional answer. For the full review "
        "(counsel packet, rule audit, anti-dilution, interactive explorer), "
        "ask for the deep dive._"
    )
    md_lines.append("")
    md_lines.append("## Scenario")
    md_lines.append("")
    md_lines.append(f"- Pre-money: {_money(pre_money)}")
    md_lines.append(f"- New money: {_money(new_money)}")
    md_lines.append(f"- Post-money valuation: {_money(pre_money + new_money)}")
    if target_pool_percent:
        md_lines.append(f"- Pool target: {target_pool_percent:.0%} ({target_basis.replace('_', ' ')})")
    else:
        md_lines.append(
            "_No pool top-up modeled — seed investors typically require a 10–15% post-money "
            "unallocated pool; re-run with a pool target to see that dilution._"
        )
    md_lines.append("")
    md_lines.append("## Outstanding instruments")
    md_lines.append("")
    if safes:
        md_lines.append(f"- **{len(safes)} SAFE(s):**")
        for s in safes:
            cap = s.get("post_money_valuation_cap")
            cap_str = f"@ {_money(cap)} cap" if cap else "(uncapped)"
            md_lines.append(f"  - {_money(s['purchase_amount'])} {cap_str}")
    if notes:
        md_lines.append(f"- **{len(notes)} convertible note(s)** (see full review for branch enumeration)")
    if not safes and not notes:
        md_lines.append("- (no outstanding SAFEs or notes)")
    md_lines.append("")
    md_lines.append("## Founder ownership outcome")
    md_lines.append("")
    if completeness == "full" and headline:
        fi = headline["founder_impact"]
        md_lines.append(f"**Post-financing founder ownership: {_percent(fi['ownership_post_financing_pct'])}**")
        md_lines.append(f"**Price per share: ${fi['pps_priced_round']:.4f}**")
        md_lines.append("")
        shares_bd = solver_result.get("shares_breakdown", {})
        existing_unallocated = int(cs.get("option_pool", {}).get("available_for_grant", 0))
        md_lines.append("Dilution by source (post-money percentage):")
        for d in drivers:
            dtype = d["type"]
            line = f"- {dtype.replace('_', ' ').title()}: {_percent(d['impact_pct'])}"
            if dtype == "pool_refresh":
                topup_shares = int(shares_bd.get("pool_topup", 0))
                if topup_shares > 0:
                    total_pool = existing_unallocated + topup_shares
                    line = (
                        f"- Pool Top-Up: +{topup_shares:,} shares"
                        f" (unallocated pool grows to {total_pool:,}"
                        f" = {_percent(d['impact_pct'])} post-money)"
                    )
                else:
                    line = f"- Existing option pool (no top-up): {_percent(d['impact_pct'])} post-money"
            elif dtype == "safe_conversion":
                safe_shares = int(shares_bd.get("safe_converted", 0))
                if safe_shares > 0:
                    line = (
                        f"- Safe Conversion: {_percent(d['impact_pct'])}"
                        f" of pre-round company capitalization"
                        f" → {safe_shares:,} shares"
                    )
            md_lines.append(line)
    else:
        md_lines.append(f"_Solver could not produce a full answer ({completeness})._")
        for b in solver_result.get("blockers", []):
            md_lines.append(f"- `{b['code']}`: {b['remedy']}")
    if completeness == "full" and headline:
        # ── Per-holder cap table ─────────────────────────────────────────────
        shares_bd = solver_result.get("shares_breakdown", {})
        agg = solver_result["aggregate_ownership_by_class"]
        post_fd = solver_result["post_round_fully_diluted_shares"]

        md_lines.append("")
        md_lines.append("## Post-Financing Cap Table")
        md_lines.append("")
        md_lines.append("| Holder | Shares | Ownership |")
        md_lines.append("|---|---:|---:|")

        # Founders row — shares directly from cap_state
        founder_shares = sum(int(f["common_shares"]) for f in cs.get("founders", []))
        md_lines.append(f"| Founders | {founder_shares:,} | {_percent(agg['founders_pct'])} |")

        # Preferred series (existing, pre-financing) — if any
        preferred_pct = agg.get("preferred_pct", 0.0)
        if preferred_pct > 0:
            final_ats = cs["as_converted_totals"]
            pref_shares = final_ats.get("preferred_shares_as_converted", 0)
            md_lines.append(f"| Existing preferred (as-converted) | {int(pref_shares):,} | {_percent(preferred_pct)} |")

        # Option pool row (total: outstanding + unallocated + topup)
        option_pool_pct = agg.get("option_pool_pct", 0.0)
        if option_pool_pct > 0:
            pool_total_shares = int(round(option_pool_pct * post_fd))
            md_lines.append(f"| Option pool (unallocated) | {pool_total_shares:,} | {_percent(option_pool_pct)} |")

        # SAFE rows — per-holder when ≤ 3 SAFEs, aggregate otherwise
        per_safe_results = solver_result.get("per_safe", {})
        safe_investors = {s["id"]: s for s in safes}
        active_safes = [
            (sid, safe_investors[sid], per_safe_results[sid])
            for sid in per_safe_results
            if sid in safe_investors and per_safe_results[sid].get("branch") != "rejected"
        ]
        if len(active_safes) <= 3:
            for sid, sinst, sres in active_safes:
                s_shares = int(round(sres.get("conversion_shares", 0)))
                s_pct = s_shares / post_fd if post_fd else 0.0
                cap = sinst.get("post_money_valuation_cap")
                cap_str = f" @ {_money(cap)} cap" if cap else ""
                label = f"SAFE — {sinst.get('investor_name', sid)} ({_money(sinst['purchase_amount'])}{cap_str})"
                md_lines.append(f"| {label} | {s_shares:,} | {_percent(s_pct)} |")
        else:
            safe_total_shares = int(shares_bd.get("safe_converted", 0))
            safe_total_pct = agg.get("safe_pct", 0.0)
            md_lines.append(
                f"| SAFEs (aggregate, {len(active_safes)}) | {safe_total_shares:,} | {_percent(safe_total_pct)} |"
            )

        # Convertible notes row (aggregate)
        note_pct = agg.get("note_pct", 0.0)
        if note_pct > 0:
            note_shares = int(shares_bd.get("note_converted", 0))
            md_lines.append(f"| Convertible notes (aggregate) | {note_shares:,} | {_percent(note_pct)} |")

        # New investors row
        new_money_pct = agg.get("new_money_pct", 0.0)
        new_money_shares = int(shares_bd.get("new_money", 0))
        md_lines.append(f"| New investors | {new_money_shares:,} | {_percent(new_money_pct)} |")

        # Total row
        md_lines.append(f"| **Total (fully diluted)** | **{post_fd:,}** | **100%** |")
        md_lines.append("")

        # ── SAFE derivation line(s) ───────────────────────────────────────────
        if len(active_safes) <= 3:
            for _sid, sinst, sres in active_safes:
                cap = sinst.get("post_money_valuation_cap")
                if cap and sinst.get("form", "").startswith("yc_postmoney"):
                    purchase = sinst["purchase_amount"]
                    s_shares = int(round(sres.get("conversion_shares", 0)))
                    ownership_pct = purchase / cap
                    md_lines.append(
                        f"_Each post-money SAFE owns purchase ÷ cap of the post-conversion, "
                        f"pre-new-money capitalization (YC convention): "
                        f"{_money(purchase)} ÷ {_money(cap)} = {_percent(ownership_pct)} "
                        f"→ {s_shares:,} shares._"
                    )
                    md_lines.append("")
        elif len(active_safes) > 0:
            # Aggregate sentence for many SAFEs
            total_safe_pct = agg.get("safe_pct", 0.0)
            md_lines.append(
                f"_Each post-money SAFE owns purchase ÷ cap of the post-conversion, "
                f"pre-new-money capitalization (YC convention). "
                f"Aggregate SAFE ownership: {_percent(total_safe_pct)}._"
            )
            md_lines.append("")

    md_lines.append("")
    md_lines.append("## What this fast-assess does NOT cover")
    md_lines.append("")
    md_lines.append("- Counsel-review items (anti-dilution triggers, §102/IIA / Israeli tax flags, QSBS windows)")
    md_lines.append("- Rule audit + watchlist of date-sensitive rules")
    md_lines.append("- Anti-dilution math under hypothetical down rounds")
    md_lines.append("- Scenario completeness analysis across multiple scenarios")
    md_lines.append("- Interactive scenario explorer + HTML deliverables")
    md_lines.append("")
    md_lines.append("_Ask for the full review to get all of the above plus the counsel-handoff packet._")
    md_lines.append("")

    if assumptions:
        md_lines.append("## Assumptions")
        md_lines.append("")
        for a in assumptions:
            md_lines.append(f"- {a}")
        md_lines.append("")

    sentinel["_report_md"] = "\n".join(md_lines)
    return sentinel


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True, help="Path to inputs.json (per the inputs schema)")
    p.add_argument(
        "--safes",
        required=True,
        help="Path to a JSON list of SAFE instruments (matches instruments.json safes[] shape)",
    )
    p.add_argument(
        "--notes",
        help="Path to a JSON list of convertible-note instruments (optional)",
    )
    p.add_argument("--pre-money", type=float, required=True)
    p.add_argument("--new-money", type=float, required=True)
    p.add_argument("--target-pool-percent", type=float, default=None)
    p.add_argument("--target-basis", default="post_money")
    p.add_argument(
        "--event-date",
        default=None,
        help="ISO conversion event date for convertible notes. If notes are present and "
        "this is omitted, fast-assess defaults to today and discloses the assumption.",
    )
    p.add_argument("--review-dir", required=True, help="Output directory (e.g. cap-table-{slug}-fastassess/)")
    p.add_argument("--founder-prompt", default="")
    p.add_argument("--attached-doc", action="append", default=[])
    p.add_argument("--run-id", default=None, help="Override the run_id in the sentinel (optional)")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.inputs) as f:
        inputs = json.load(f)
    with open(args.safes) as f:
        safes = json.load(f)
    notes: list[dict[str, Any]] = []
    if args.notes:
        with open(args.notes) as f:
            notes = json.load(f)

    # Accept both top-level and nested company_name; top-level wins.
    company_name_raw = inputs.get("company_name") or inputs.get("company", {}).get("company_name")
    if not company_name_raw:
        print(
            "Warning: company_name not found at top-level or under 'company.company_name'; using 'Unknown'.",
            file=sys.stderr,
        )
        company_name_raw = "Unknown"

    sentinel = quick_assess(
        company_name=company_name_raw,
        inputs=inputs,
        safes=safes,
        notes=notes,
        pre_money=args.pre_money,
        new_money=args.new_money,
        target_pool_percent=args.target_pool_percent,
        target_basis=args.target_basis,
        event_date=args.event_date,
        founder_prompt=args.founder_prompt,
        attached_docs=args.attached_doc,
        run_id_override=args.run_id,
    )

    os.makedirs(args.review_dir, exist_ok=True)
    md_path = os.path.join(args.review_dir, "report_fast_assess.md")
    with open(md_path, "w") as f:
        f.write(sentinel.pop("_report_md"))
    sentinel["fast_assess_report_path"] = os.path.abspath(md_path)

    sentinel_path = os.path.join(args.review_dir, "fast_assess_only.json")
    with open(sentinel_path, "w") as f:
        if args.pretty:
            json.dump(sentinel, f, indent=2)
        else:
            json.dump(sentinel, f)

    receipt = {
        "wrote": {
            "fast_assess_report_md": os.path.abspath(md_path),
            "sentinel_json": os.path.abspath(sentinel_path),
        },
        "schema_version": SCHEMA_VERSION,
        "run_id": sentinel["run_id"],
        "company_name": sentinel["company_name"],
        "mode": "fast_assess",
    }
    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
