#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Extract counsel-review items from rule_audit.json into a standalone packet.

Per design doc §3.4: counsel_packet.md / counsel_packet.json is a
standalone deliverable the founder can send to counsel WITHOUT sharing
the full cap-table report.
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


def _domain_label(domain: str) -> str:
    """Founder/counsel-facing name for a rule domain.

    Shared by the summary sentence and the section heading so the two cannot drift: the heading
    humanized and the summary did not, which put the raw `delaware_cross_border` into a delivered
    packet. Rule IDs and source IDs are NOT routed through this — they stay verbatim because counsel
    cites them.
    """
    return domain.replace("_", " ").title()


def build_packet(
    *,
    company_name: str,
    rule_audit: dict[str, Any],
    flip_counsel_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose packet from rule_audit + any flip-scenario counsel items."""
    items = list(rule_audit.get("counsel_review_items", []))
    if flip_counsel_items:
        # Dedupe by rule_id
        seen = {i["rule_id"] for i in items}
        for f in flip_counsel_items:
            if f.get("rule_id") not in seen:
                items.append(f)
                seen.add(f["rule_id"])

    summary_parts = []
    domain_counts: dict[str, int] = {}
    for it in items:
        d = it.get("domain", "other")
        domain_counts[d] = domain_counts.get(d, 0) + 1
    for d, c in sorted(domain_counts.items()):
        summary_parts.append(f"{c} {_domain_label(d)}")

    noun = "item" if len(items) == 1 else "items"
    engagement_summary = (
        f"Counsel-handoff packet for {company_name}. "
        f"{len(items)} {noun} flagged across: {', '.join(summary_parts) or 'no domains'}."
    )

    return {
        "company_name": company_name,
        "engagement_summary": engagement_summary,
        "items": items,
        "metadata": {},
    }


def _apply_founder_text_policy(md: str) -> str:
    """Unsnake internal vocabulary in the delivered packet.

    This packet is read by a founder's lawyer and had NO founder-text pass of any kind, while
    `rule_audit` maps a rule's `summary` straight to the counsel question and renders `applies_when`
    verbatim above it. Both arrived raw.

    Scope is deliberately just unsnaking, and that is a division of labour with the rule pack rather
    than laziness. Domain vocabulary is what `substitute` handles WELL -- "current_conversion_price"
    becomes "current conversion price", which is the term counsel maps onto a charter clause, so
    paraphrasing it would destroy the precision they need. What substitute cannot fix -- our own knob
    names, script filenames, internal warning codes -- is fixed in the pack itself, because it is
    detect-only for ALLCAPS and deliberately never rewrites a filename ("renaming a file in prose
    would be a lie").

    Best-effort: the shared policy module lives outside this skill, and a packet is worth delivering
    unpolished rather than not at all.
    """
    try:
        sys.path.insert(
            0,
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts"
            ),
        )
        import _founder_text  # type: ignore[import-not-found]
    except Exception:
        return md
    # Keep set, not bare substitute: counsel needs the exact term, and this route was mangling the
    # skill's own glossed vocabulary while `report.md` preserved it. Guarded separately -- the
    # try/except above exists so "a packet is worth delivering unpolished rather than not at all",
    # and an unguarded import here defeated that: a missing helper meant NO counsel_packet.md.
    try:
        from _founder_text_keep import cap_table_keep

        keep = cap_table_keep()
    except Exception:
        keep = frozenset()
    return str(_founder_text.substitute(md, extra_keep=keep))


def render_markdown(packet: dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Counsel Packet — {packet['company_name']}")
    lines.append("")
    lines.append(packet["engagement_summary"])
    lines.append("")
    lines.append("> This packet was prepared by the cap-table skill from a structured rule pack.")
    lines.append("> Every item links to a primary source. The skill makes no legal or tax conclusions —")
    lines.append("> it flags questions for counsel to determine.")
    lines.append("")

    # Group by domain
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for it in packet["items"]:
        by_domain.setdefault(it.get("domain", "other"), []).append(it)

    for domain in sorted(by_domain.keys()):
        lines.append(f"## {_domain_label(domain)}")
        lines.append("")
        for it in by_domain[domain]:
            lines.append(f"### {it['title']}")
            lines.append(f"**Rule:** `{it['rule_id']}`")
            lines.append("")
            if it.get("applies_when"):
                lines.append(f"**Applies when:** {it['applies_when']}")
                lines.append("")
            if it.get("founder_question"):
                lines.append(f"**For founder:** {it['founder_question']}")
                lines.append("")
            if it.get("counsel_question"):
                lines.append(f"**For counsel:** {it['counsel_question']}")
                lines.append("")
            docs = it.get("documents_needed", [])
            if docs:
                lines.append("**Documents needed:**")
                for d in docs:
                    lines.append(f"- {d}")
                lines.append("")
            sources = it.get("source_ids", [])
            if sources:
                lines.append(f"**Sources:** {', '.join(f'`{s}`' for s in sources)}")
                lines.append("")
    return _apply_founder_text_policy("\n".join(lines))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rule-audit", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--scenarios", default=None)
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output-json", required=True)
    p.add_argument("--write-md", default=None, help="Path to write counsel_packet.md")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()

    with open(args.rule_audit, encoding="utf-8") as f:
        rule_audit = json.load(f)
    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)
    company_name = inputs.get("company_name", "Company")

    flip_items = []
    if args.scenarios and os.path.exists(args.scenarios):
        with open(args.scenarios, encoding="utf-8") as f:
            scenarios_doc = json.load(f)
        for s in scenarios_doc.get("scenarios", []):
            if s.get("type") == "flip":
                flip_items.extend(s["computed_outputs"].get("counsel_review_items", []))

    packet = build_packet(
        company_name=company_name,
        rule_audit=rule_audit,
        flip_counsel_items=flip_items,
    )

    schema = load_schema(os.path.join(_SCHEMA_DIR, "counsel_packet.schema.json"))
    try:
        receipt = write_artifact(
            data=packet,
            schema=schema,
            run_id=args.run_id,
            output_path=args.output_json,
            pretty=args.pretty,
        )
    except ArtifactValidationError as e:
        sys.stderr.write(f"counsel_packet.py: schema validation failed: {e}\n")
        return 1

    if args.write_md:
        md = render_markdown(packet)
        os.makedirs(os.path.dirname(os.path.abspath(args.write_md)) or ".", exist_ok=True)
        with open(args.write_md, "w", encoding="utf-8") as f:
            f.write(md)
        receipt["markdown_path"] = os.path.abspath(args.write_md)

    print(json.dumps(receipt, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
