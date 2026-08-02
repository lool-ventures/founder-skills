#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Single-question cited lookup from the rule pack — the lightweight answer path.

`--rule-lookup <rule_id>` returns the cited constant a rule carries (e.g. the
QSBS OBBBA date-window start), its primary-source citations, and the reliance
boundary — for a bare eligibility/date question that needs a fact, not a solver
run. The model never computes the fact: it comes verbatim from the rule pack.

ALLOWLIST BY DATA, NOT BY HARDCODED LIST: a rule is answerable here ONLY if it
exposes a recognized STRUCTURED constant (currently `date_window.start`). Rules
whose trap fact is not a stored constant — e.g. the Section 102 capital-gains
holding clock, which runs from a plan/trustee-specific deposit date the pack
does not store — return status "escalate": collect the founder's input and treat
as a counsel determination. This guard is what stops the path from echoing a
non-constant field (like `grant_date`) as if it were the answer.

A rule carrying `counsel_review: true` is ALWAYS a flag/handoff, never an
eligibility conclusion (see the skill's Reliance Boundary).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.join(HERE, "..", "data", "cap-table-rules.json")

RELIANCE_BOUNDARY = (
    "State the cited fact (date window / threshold / clock) and stop. Do NOT "
    "conclude that the founder does or will qualify — eligibility is a counsel "
    "determination. Emit a counsel item."
)


def _iter_rules(pack: dict) -> Iterator[dict]:
    """Yield every rule object across the pack's domains."""
    domains = pack.get("domains", {})
    groups = domains.values() if isinstance(domains, dict) else domains
    for group in groups:
        rules = group.get("rules", []) if isinstance(group, dict) else group
        for rule in rules or []:
            if isinstance(rule, dict):
                yield rule


def find_rule(pack: dict, rule_id: str) -> dict | None:
    for rule in _iter_rules(pack):
        if (rule.get("id") or rule.get("rule_id")) == rule_id:
            return rule
    return None


def resolve_citations(pack: dict, rule: dict) -> list[dict]:
    bib = {e.get("source_id"): e for e in pack.get("source_bibliography", []) if isinstance(e, dict)}
    out = []
    for sid in rule.get("source_ids", []) or []:
        entry = bib.get(sid)
        if entry:
            out.append({k: entry.get(k) for k in ("source_id", "title", "publisher", "url")})
        else:
            out.append({"source_id": sid, "title": None, "publisher": None, "url": None})
    return out


def extract_constant(rule: dict) -> dict | None:
    """Return a recognized STRUCTURED constant, or None (→ escalate).

    Recognized: `date_window.start` — a concrete date the rule pins. Extend here
    as more structured constants are added to the pack; never fall back to a
    non-constant field (e.g. `event_date_field`) as "the fact".
    """
    dw = rule.get("date_window")
    if isinstance(dw, dict) and dw.get("start"):
        return {
            "kind": "date_window_start",
            "value": dw["start"],
            "keyed_on": dw.get("event_date_field"),
            "note": dw.get("notes"),
        }
    return None


def lookup(pack: dict, rule_id: str) -> dict:
    rule = find_rule(pack, rule_id)
    if rule is None:
        return {
            "rule_id": rule_id,
            "lookup_status": "not_found",
            "answer": f"No rule with id {rule_id!r} in the rule pack.",
        }

    citations = resolve_citations(pack, rule)
    counsel_review = bool(rule.get("counsel_review"))
    const = extract_constant(rule)

    base = {
        "rule_id": rule_id,
        "counsel_review": counsel_review,
        "citations": citations,
        "reliance_boundary": RELIANCE_BOUNDARY,
    }

    if const is None:
        # No stored constant: do not fabricate one. Escalate for founder input.
        base.update(
            lookup_status="escalate",
            constant=None,
            escalation_reason=(
                "This rule does not carry a fixed constant answerable from the rule "
                "pack alone — the trap fact depends on inputs the pack does not store "
                "(e.g. a plan/trustee-specific date). Do not answer from a default."
            ),
            answer=(
                f"[{rule_id}] cannot be answered from a stored constant. "
                f"{rule.get('summary', '').strip()} "
                "Collect the specific date/fact from the founder and treat as a "
                "counsel-reviewed determination — do not state a default as the answer."
            ).strip(),
        )
        return base

    cite_str = (
        "; ".join(
            f"{c.get('title') or c.get('source_id')}" + (f" — {c['url']}" if c.get("url") else "") for c in citations
        )
        or "(see rule pack source_ids)"
    )
    keyed = f" (keyed on {const['keyed_on']})" if const.get("keyed_on") else ""
    answer = (
        f"Cited fact [{rule_id}]: window start = {const['value']}{keyed}. "
        + (f"{const['note']} " if const.get("note") else "")
        + f"Source: {cite_str}. "
        + (
            "This is counsel-reviewed: the date above is a fact; whether the founder "
            "ultimately qualifies is a counsel determination — flag it, do not conclude it."
            if counsel_review
            else ""
        )
    ).strip()
    base.update(lookup_status="answered", constant=const, escalation_reason=None, answer=answer)
    return base


def main() -> int:
    p = argparse.ArgumentParser(description="Single-question cited rule-pack lookup.")
    p.add_argument(
        "--rule-lookup",
        metavar="RULE_ID",
        required=True,
        help="rule_id to look up (e.g. delaware_cross_border.qsbs_date_sensitive)",
    )
    p.add_argument("--rules", default=DEFAULT_RULES, help="path to cap-table-rules.json")
    p.add_argument("-o", "--output-json", default=None, help="write the result JSON to a file")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    try:
        with open(args.rules, encoding="utf-8") as fh:
            pack = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"could not load rules: {e}"}), file=sys.stderr)
        return 2

    result = lookup(pack, args.rule_lookup)
    indent = 2 if args.pretty else None

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(
            json.dumps({"ok": True, "path": args.output_json, "lookup_status": result["lookup_status"]}, indent=indent)
        )
    else:
        print(json.dumps(result, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
