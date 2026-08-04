#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Validate and normalize competitor landscape.

Takes landscape_enriched.json (from stdin) and produces a validated,
normalized landscape.json. Validates structure, checks slug uniqueness,
preserves provenance fields, and emits warnings for quality issues.

Usage:
    echo '{"competitors": [...], ...}' | python validate_landscape.py --pretty
    echo '{"competitors": [...], ...}' | python validate_landscape.py -o landscape.json

Output: JSON with validated competitor list, warnings, and metadata.
Exit codes: 0 = success (may include warnings), 1 = validation error.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any


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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"direct", "adjacent", "do_nothing", "emerging", "custom"}
VALID_RESEARCH_DEPTHS = {"full", "partial", "founder_provided"}
REQUIRED_COMPETITOR_FIELDS = {"name", "slug", "category", "description", "key_differentiators"}
PROVENANCE_FIELDS = {"research_depth", "evidence_source", "sourced_fields_count"}
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Hard structural floor. The checklist (COVER_01) sets the investor bar at 5+
# and fails below 4. This validator ensures a minimum viable landscape;
# the checklist evaluates whether it meets investor expectations.
MIN_COMPETITORS = 3
MAX_COMPETITORS = 10
RESERVED_SLUGS = {"_startup"}

VALID_RECENT_DEVELOPMENT_TYPES = {
    "funding",
    "pricing_change",
    "product_launch",
    "market_move",
    "acquisition",
    "leadership",
    "layoff",
}
DEV_DATE_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DEV_DATE_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_PREFIXES = ("http://", "https://")
# PROVISIONAL: how far back a recent_developments entry may date and still be
# considered "recent" relative to the as-of date. This is a judgement call, not
# a validated bound — revisit if founder feedback or investor practice suggests
# a different horizon.
RECENCY_WINDOW_MONTHS = 18
# Founder-facing rendering of the bound above (no bare number-plus-underscore token in prose).
RECENCY_MONTHS_LABEL = f"{RECENCY_WINDOW_MONTHS} months"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _parse_as_of(as_of_str: str) -> _date:
    """Parse a --as-of CLI value (YYYY-MM-DD). Raises ValueError on bad format."""
    if not DEV_DATE_FULL_RE.match(as_of_str):
        raise ValueError(f"--as-of must be YYYY-MM-DD, got '{as_of_str}'")
    y, m, d = (int(x) for x in as_of_str.split("-"))
    return _date(y, m, d)


def _shift_months(d: _date, months: int) -> _date:
    """Return d shifted back by `months` months, clamping day to the target
    month's length (e.g. Aug 31 - 6 months -> Feb 28/29, not an OverflowError)."""
    total = d.year * 12 + (d.month - 1) - months
    y2, m2 = divmod(total, 12)
    m2 += 1
    last_day = calendar.monthrange(y2, m2)[1]
    return _date(y2, m2, min(d.day, last_day))


def _parse_dev_date(date_str: str) -> tuple[_date, bool]:
    """Parse a recent_developments 'date' field. Returns (date, is_month_only).

    Raises ValueError if the format is not YYYY-MM or YYYY-MM-DD. A month-only
    date is normalized to day=1 for storage, but callers must compare it at
    month granularity (see is_month_only) — a day-1 date is a comparison
    artifact, not a claim that the event happened on the 1st.
    """
    if DEV_DATE_FULL_RE.match(date_str):
        y, m, d = (int(x) for x in date_str.split("-"))
        return _date(y, m, d), False
    if DEV_DATE_MONTH_RE.match(date_str):
        y, m = (int(x) for x in date_str.split("-"))
        return _date(y, m, 1), True
    raise ValueError("bad format")


def _check_recent_developments(
    comp: dict[str, Any], as_of: _date, window_start: _date
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the optional recent_developments[] field for one competitor.

    Returns (errors, kept, dropped):
      - errors: fatal error message fragments (caller prefixes with the
        'Competitor N (name):' context, matching the rest of this file's
        error style) — bad format, future dates, bad `type`, empty
        `summary`, or a non-URL `source`. These are integrity guards
        against fabrication and stay fatal regardless of the date.
      - kept: entries that pass every check AND fall within the recency
        window — the new value of `recent_developments`.
      - dropped: entries that pass every OTHER check but fall outside the
        recency window. The 18-month bound is an editorial-freshness rule,
        not an integrity guard, so an out-of-window entry is relocated
        (see caller) rather than rejected — but an out-of-window entry
        with a bad `type`/`summary`/`source` still lands in `errors`, not
        `dropped`: relocation is not an exemption from the other guards.

    Absent or an empty list is valid and produces no errors: ([], [], []).
    A non-list value is a fatal error; kept/dropped are both empty.
    """
    if "recent_developments" not in comp:
        return [], [], []
    rd = comp["recent_developments"]
    if not isinstance(rd, list):
        return ["recent_developments must be an array"], [], []

    errors: list[str] = []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for idx, raw_entry in enumerate(rd):
        if not isinstance(raw_entry, dict):
            errors.append(f"recent_developments[{idx}] must be an object")
            continue
        entry: dict[str, Any] = raw_entry
        entry_errors: list[str] = []
        is_out_of_window = False

        date_str = entry.get("date")
        if not isinstance(date_str, str) or not date_str:
            entry_errors.append(f"recent_developments[{idx}]: 'date' is required and must be a string")
        else:
            try:
                dev_date, month_only = _parse_dev_date(date_str)
            except ValueError:
                entry_errors.append(
                    f"recent_developments[{idx}]: 'date' must be YYYY-MM or YYYY-MM-DD, got '{date_str}'"
                )
            else:
                if month_only:
                    is_future = (dev_date.year, dev_date.month) > (as_of.year, as_of.month)
                    is_too_old = (dev_date.year, dev_date.month) < (window_start.year, window_start.month)
                else:
                    is_future = dev_date > as_of
                    is_too_old = dev_date < window_start
                if is_future:
                    entry_errors.append(
                        f"recent_developments[{idx}]: 'date' {date_str} is in the future "
                        f"relative to as-of {as_of.isoformat()}"
                    )
                elif is_too_old:
                    is_out_of_window = True

        type_val = entry.get("type")
        if type_val not in VALID_RECENT_DEVELOPMENT_TYPES:
            entry_errors.append(
                f"recent_developments[{idx}]: 'type' must be one of "
                f"{sorted(VALID_RECENT_DEVELOPMENT_TYPES)}, got {type_val!r}"
            )

        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            entry_errors.append(f"recent_developments[{idx}]: 'summary' is required and must be non-empty")

        source = entry.get("source")
        if not isinstance(source, str) or not source.strip() or not source.startswith(URL_PREFIXES):
            entry_errors.append(
                f"recent_developments[{idx}]: 'source' must be a non-empty URL "
                "(http:// or https://) — a dated factual claim must be spot-checkable"
            )

        if entry_errors:
            errors.extend(entry_errors)
            continue

        if is_out_of_window:
            dropped.append(entry)
        else:
            kept.append(entry)

    return errors, kept, dropped


def _check_key_differentiators(comp: dict[str, Any]) -> str | None:
    """Validate key_differentiators content, once the required-field presence
    check (REQUIRED_COMPETITOR_FIELDS) has already run.

    Returns an error message, or None if the field is absent (presence is
    the required-field loop's job, not this one) or valid.

    An empty list is valid only when research_depth is 'partial' — the
    promoted-but-not-yet-enriched case: a suggestion that was never
    researched has no differentiators, and inventing one would be content
    authoring. Any other research_depth (notably 'full') claims complete
    research, so an empty list there is an error, not a stub.
    """
    if "key_differentiators" not in comp:
        return None
    kd = comp.get("key_differentiators")
    if not isinstance(kd, list):
        return "key_differentiators must be an array"
    if len(kd) == 0 and comp.get("research_depth") != "partial":
        return (
            "key_differentiators is empty, which is only valid for a competitor with "
            "research_depth 'partial' (a promoted-but-not-yet-enriched suggestion). A "
            "fully-researched competitor must have at least one differentiator — if it "
            "was not enriched, set research_depth: 'partial' rather than leaving this "
            "empty under 'full'."
        )
    return None


def validate_landscape(enriched: dict[str, Any], as_of: str | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate landscape_enriched.json and return (output, errors).

    `as_of` is the reference date (YYYY-MM-DD) for the recent_developments
    recency window; defaults to today (UTC) when omitted. Callers that need a
    deterministic clock (tests, reproducible runs) should always pass it
    explicitly rather than relying on the wall-clock default.

    Returns (output_dict, []) on success, (None, error_list) on failure.
    """
    errors: list[str] = []
    warnings: list[dict[str, Any]] = []

    if as_of is None:
        as_of_date = datetime.now(timezone.utc).date()
    else:
        try:
            as_of_date = _parse_as_of(as_of)
        except ValueError as e:
            return None, [str(e)]
    window_start = _shift_months(as_of_date, RECENCY_WINDOW_MONTHS)

    # Top-level structure
    competitors_raw = enriched.get("competitors")
    if not isinstance(competitors_raw, list):
        return None, ["'competitors' must be an array"]

    if "deferred_recall_candidates" in enriched and not isinstance(enriched["deferred_recall_candidates"], list):
        return None, ["'deferred_recall_candidates' must be an array"]

    # Bounds check
    n = len(competitors_raw)
    if n < MIN_COMPETITORS:
        errors.append(f"Minimum {MIN_COMPETITORS} competitors required, got {n}")
    if n > MAX_COMPETITORS:
        errors.append(f"Maximum {MAX_COMPETITORS} competitors allowed, got {n}")

    # Per-competitor validation
    slugs_seen: set[str] = set()
    validated_competitors: list[dict[str, Any]] = []
    has_do_nothing = False
    has_adjacent = False
    has_recent_developments = False

    for i, comp in enumerate(competitors_raw):
        if not isinstance(comp, dict):
            errors.append(f"Competitor {i}: must be an object")
            continue

        # Auto-fix: an observed sub-agent near-miss stamps 'key_differentiators_per_deck'
        # instead of the canonical 'key_differentiators' (same auto-fix pattern as the
        # underscore-slug conversion below). If the canonical field is absent, promote the
        # alias to it; if BOTH are present, canonical wins and the alias is dropped — but
        # note the drop on stderr rather than discarding it silently (its content may differ
        # from the canonical field, and a silent drop hides that from the operator).
        if "key_differentiators_per_deck" in comp:
            if "key_differentiators" not in comp:
                comp["key_differentiators"] = comp.pop("key_differentiators_per_deck")
                print(
                    f"Note: auto-converted field 'key_differentiators_per_deck' -> "
                    f"'key_differentiators' for competitor {i} ({comp.get('name', '?')})",
                    file=sys.stderr,
                )
            else:
                comp.pop("key_differentiators_per_deck", None)
                print(
                    f"Note: dropped alias 'key_differentiators_per_deck' for competitor {i} "
                    f"({comp.get('name', '?')}) — canonical 'key_differentiators' already present, "
                    f"canonical wins",
                    file=sys.stderr,
                )

        # Required fields
        for field in REQUIRED_COMPETITOR_FIELDS:
            if field not in comp:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): missing required field '{field}'")

        # Slug validation — auto-convert underscores to hyphens for kebab-case
        slug = comp.get("slug", "")
        if not slug:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug must be non-empty")
        else:
            # Auto-fix: convert underscores to hyphens (common agent mistake)
            if "_" in slug and slug not in RESERVED_SLUGS:
                original = slug
                slug = slug.replace("_", "-")
                comp["slug"] = slug  # fix in-place so output gets corrected slug
                print(f"Note: auto-converted slug '{original}' -> '{slug}'", file=sys.stderr)
            if slug in RESERVED_SLUGS:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug '{slug}' is reserved")
            elif not KEBAB_CASE_RE.match(slug):
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): slug '{slug}' must be kebab-case")
        if slug and slug not in RESERVED_SLUGS:
            if slug in slugs_seen:
                errors.append(f"Competitor {i} ({comp.get('name', '?')}): duplicate slug '{slug}'")
            slugs_seen.add(slug)

        # Category validation
        category = comp.get("category", "")
        if not category:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): category must be non-empty")
        elif category not in VALID_CATEGORIES:
            errors.append(
                f"Competitor {i} ({comp.get('name', '?')}): invalid category '{category}'. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )
        if category == "do_nothing":
            has_do_nothing = True
        if category == "adjacent":
            has_adjacent = True

        kd_error = _check_key_differentiators(comp)
        if kd_error:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): {kd_error}")

        # recent_developments[] — optional; absent or [] is valid (a genuinely
        # quiet competitor is a correct answer). When present, each entry is
        # validated against the enum/URL/non-empty rules above — these exist
        # to stop fabrication of a dated, sourced claim. The 18-month recency
        # window is handled separately below: it is editorial freshness, not
        # an integrity guard, so an out-of-window entry is relocated rather
        # than rejected.
        raw_rd = comp.get("recent_developments")
        rd_errors, rd_kept, rd_dropped = _check_recent_developments(comp, as_of_date, window_start)
        for rd_error in rd_errors:
            errors.append(f"Competitor {i} ({comp.get('name', '?')}): {rd_error}")

        # has_recent_developments is evidence-that-research-happened, and must
        # be computed BEFORE the out-of-window drop below: a competitor whose
        # only developments are all out-of-window still proves research
        # occurred, and must not retroactively trip NO_RECENT_DEVELOPMENTS
        # ("shallow research") just because its findings aged out.
        if isinstance(raw_rd, list) and len(raw_rd) > 0:
            has_recent_developments = True

        # Relocate out-of-window entries rather than discard them — nothing
        # researched is silently lost, it just stops being rendered as
        # "recent". One STALE_DEVELOPMENT warning per dropped entry.
        if isinstance(raw_rd, list):
            comp["recent_developments"] = rd_kept
            if rd_dropped:
                existing_oow = comp.get("out_of_window_developments")
                comp["out_of_window_developments"] = (
                    existing_oow + rd_dropped if isinstance(existing_oow, list) else rd_dropped
                )
                for dropped_entry in rd_dropped:
                    dev_date_str = dropped_entry.get("date", "?")
                    summary_text = str(dropped_entry.get("summary", "")).strip()
                    truncated_summary = summary_text if len(summary_text) <= 80 else summary_text[:77] + "..."
                    warnings.append(
                        {
                            "code": "STALE_DEVELOPMENT",
                            "severity": "medium",
                            # Founder-readable by construction: this message is rendered into
                            # report.md's warning list, so it must not name an internal field.
                            # A snake_case key in the deliverable is the same leak class as a
                            # slug in a heading — it means nothing to the reader and reads as
                            # machinery. Name the competitor, the date, and what was set aside.
                            "message": (
                                f"{comp.get('name') or comp.get('slug', '?')}: a dated update from "
                                f"{dev_date_str} is older than the {RECENCY_MONTHS_LABEL} this review "
                                f"treats as current, so it is recorded separately rather than listed "
                                f'as a recent move — "{truncated_summary}"'
                            ),
                        }
                    )

        # A remembered event is not a researched one: reject recent_developments
        # stamped agent_estimate outright rather than merely warning, since this
        # field is the most exposed to confidently recalling something that
        # never happened.
        comp_ev_src = comp.get("evidence_source")
        if isinstance(comp_ev_src, dict) and comp_ev_src.get("recent_developments") == "agent_estimate":
            errors.append(
                f"Competitor {i} ({comp.get('name', '?')}): recent_developments evidence_source "
                "is 'agent_estimate' — a remembered event is not a researched one"
            )

        # Build validated competitor entry — preserve ALL fields from input.
        # Required fields were already validated above; enrichment fields
        # (pricing_model, funding, team_size, strengths, weaknesses, etc.)
        # are passed through so compose_report can use them in the narrative.
        validated_comp: dict[str, Any] = dict(comp)

        # Validate research_depth enum if present
        rd = validated_comp.get("research_depth")
        if rd is not None and rd not in VALID_RESEARCH_DEPTHS:
            errors.append(
                f"Competitor {i} ({comp.get('name', '?')}): research_depth '{rd}' "
                f"must be one of {sorted(VALID_RESEARCH_DEPTHS)}"
            )

        validated_competitors.append(validated_comp)

        # Verifiability check: a per-field "researched" evidence_source with no matching
        # "sources" (URL or search query) citation is indistinguishable from a plausible-
        # sounding fabrication to the main thread, which never sees the sub-agent's WebSearch
        # results — only its artifact. Not a schema requirement (a source may legitimately be
        # a query string, not a URL) — warn, don't fail.
        ev_src = validated_comp.get("evidence_source")
        if isinstance(ev_src, dict):
            sources = validated_comp.get("sources")
            sources = sources if isinstance(sources, dict) else {}
            for field, src_type in ev_src.items():
                if src_type != "researched":
                    continue
                cited = sources.get(field)
                if isinstance(cited, str) and cited.strip():
                    continue
                warnings.append(
                    {
                        "code": "RESEARCHED_WITHOUT_SOURCE",
                        "severity": "medium",
                        "message": (
                            f"{validated_comp.get('slug', '?')}: '{field}' evidence_source is"
                            " 'researched' but no source (URL or search query) was provided"
                            " in 'sources' — this claim can't be spot-checked"
                        ),
                    }
                )

    # Bail on errors
    if errors:
        return None, errors

    # Quality warnings (non-blocking)
    if not has_do_nothing and not has_adjacent:
        warnings.append(
            {
                "code": "MISSING_DO_NOTHING",
                "severity": "medium",
                "message": "No competitor with category 'do_nothing' or 'adjacent' found. "
                "Consider adding a status-quo alternative.",
            }
        )

    # NO_RECENT_DEVELOPMENTS fires only when EVERY competitor has an empty/absent
    # recent_developments — that pattern indicates shallow research. One quiet
    # competitor among several researched ones is a correct answer and must not
    # warn (hence no per-competitor warning above).
    if not has_recent_developments:
        warnings.append(
            {
                "code": "NO_RECENT_DEVELOPMENTS",
                "severity": "medium",
                "message": "No competitor has any recent_developments entries. This may indicate "
                "shallow research rather than a genuinely quiet market — consider researching "
                "recent funding, launches, pricing changes, or leadership moves.",
            }
        )

    # Metadata passthrough
    metadata = enriched.get("metadata", {})
    input_mode = enriched.get("input_mode", "conversation")

    output: dict[str, Any] = {
        "competitors": validated_competitors,
        "input_mode": input_mode,
        "warnings": warnings,
        "_produced_by": "validate_landscape",
        "metadata": metadata,
        "landscape_as_of": as_of_date.isoformat(),
    }

    # Optional passthroughs
    if "research_depth" in enriched:
        output["research_depth"] = enriched["research_depth"]
    if "assessment_mode" in enriched:
        output["assessment_mode"] = enriched["assessment_mode"]
    if "data_confidence" in enriched:
        output["data_confidence"] = enriched["data_confidence"]
    if "suggested_additions" in enriched:
        output["suggested_additions"] = enriched["suggested_additions"]
    if "deferred_recall_candidates" in enriched:
        output["deferred_recall_candidates"] = enriched["deferred_recall_candidates"]

    return output, []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate competitor landscape (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--run-id",
        default=None,
        help="Stamp metadata.run_id (overrides any run_id from stdin metadata)",
    )
    p.add_argument(
        "--derive-deferred",
        default=None,
        metavar="COMPETITOR_VERIFICATION",
        help=(
            "Path to competitor_verification.json. LAST-RESORT source for "
            "deferred_recall_candidates: a blind-recall candidate that is still not in competitors[] "
            "was, by definition, not adopted at the competitor-set gate. Used only when neither "
            "stdin nor --carry-deferred supplied a non-empty list."
        ),
    )
    p.add_argument(
        "--carry-deferred",
        default=None,
        metavar="LANDSCAPE_DRAFT",
        help=(
            "Path to landscape_draft.json. Carries its deferred_recall_candidates into the output "
            "deterministically, instead of relying on the research sub-agent to copy the field "
            "through. Entries whose slug is now in competitors[] are dropped (a promoted candidate "
            "is no longer deferred)."
        ),
    )
    p.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="Reference date for the recent_developments recency window (default: today, UTC)",
    )
    return p.parse_args()


def _derive_deferred_recall_candidates(result: dict[str, Any], verification_path: str) -> None:
    """Derive `deferred_recall_candidates` from the blind-recall diff, as a last resort.

    WHY THIS EXISTS. The field was originally populated by the main thread at the competitor-set gate
    and copied through by the research sub-agent. Measured across two live runs, BOTH hops proved
    unreliable in different ways: one run's sub-agent dropped the field, and the other run's main
    thread created the key but left it empty. `--carry-deferred` fixes the first. This fixes the
    second, and it needs no knowledge of the founder's answer:

        a recall candidate that is STILL not in competitors[] was not adopted.

    That is the definition of deferred, so it is derivable rather than remembered. Adoption is the
    only way a candidate leaves the set, and adoption puts it in `competitors[]`.

    Never raises: an unreadable or malformed artifact leaves the output untouched and notes it on
    stderr — this is a convenience field, not an integrity guard.
    """
    existing = result.get("deferred_recall_candidates")
    if isinstance(existing, list) and existing:
        return
    try:
        with open(verification_path, encoding="utf-8") as f:
            verification = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"Note: --derive-deferred could not read {verification_path} ({e}); leaving "
            "deferred_recall_candidates as-is",
            file=sys.stderr,
        )
        return
    if not isinstance(verification, dict):
        print(f"Note: --derive-deferred file {verification_path} is not a JSON object; ignoring", file=sys.stderr)
        return
    recall = verification.get("recall_gaps")
    unmatched = recall.get("unmatched") if isinstance(recall, dict) else None
    if not isinstance(unmatched, list) or not unmatched:
        return
    adopted = {c.get("slug") for c in result.get("competitors", []) if isinstance(c, dict)}
    derived = [
        {
            "name": c.get("name"),
            "slug": c.get("slug"),
            "category": c.get("category"),
            "why_considered": c.get("why_considered"),
            "sources": c.get("sources"),
        }
        for c in unmatched
        if isinstance(c, dict) and c.get("slug") and c.get("slug") not in adopted
    ]
    if not derived:
        return
    result["deferred_recall_candidates"] = derived
    print(
        f"Note: derived {len(derived)} deferred recall candidate(s) from the blind-recall diff "
        "(not adopted into competitors[])",
        file=sys.stderr,
    )


def _carry_deferred_recall_candidates(result: dict[str, Any], draft_path: str) -> None:
    """Carry `deferred_recall_candidates` from landscape_draft.json into the output.

    WHY THIS IS MECHANICAL RATHER THAN AN INSTRUCTION. The field is written by the main thread at the
    competitor-set gate (the candidates the founder declined) and has to survive into
    `landscape.json` so the later additions gate can offer them again. The research sub-agent was
    originally asked to copy it through verbatim — but it has no other reason to touch the field, and
    measured across two live runs it copied it in one and dropped it in the other. A courier that
    complies half the time is not a mechanism, so the producer reads the draft directly and the
    sub-agent is out of the chain.

    Precedence: a non-empty value already on stdin wins (the sub-agent may legitimately have enriched
    it); otherwise the draft's value is used. Entries whose slug now appears in `competitors[]` are
    dropped — a candidate that made it into the set is no longer deferred, and resurrecting it would
    re-offer something the founder already accepted.

    Never raises: an unreadable or malformed draft leaves the output untouched (the field is an
    optional convenience, not an integrity guard) and notes it on stderr.
    """
    existing = result.get("deferred_recall_candidates")
    if isinstance(existing, list) and existing:
        return
    try:
        with open(draft_path, encoding="utf-8") as f:
            draft = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"Note: --carry-deferred could not read {draft_path} ({e}); leaving deferred_recall_candidates as-is",
            file=sys.stderr,
        )
        return
    if not isinstance(draft, dict):
        print(f"Note: --carry-deferred file {draft_path} is not a JSON object; ignoring", file=sys.stderr)
        return
    carried = draft.get("deferred_recall_candidates")
    if not isinstance(carried, list) or not carried:
        return
    promoted = {c.get("slug") for c in result.get("competitors", []) if isinstance(c, dict)}
    kept = [c for c in carried if not (isinstance(c, dict) and c.get("slug") in promoted)]
    dropped = len(carried) - len(kept)
    result["deferred_recall_candidates"] = kept
    msg = f"Note: carried {len(kept)} deferred recall candidate(s) from the draft"
    if dropped:
        msg += f" ({dropped} dropped — now in competitors[])"
    print(msg, file=sys.stderr)


def _apply_run_id(result: dict, run_id: str | None) -> None:
    """CLI run_id overrides stdin-passthrough metadata.run_id (CLI > stdin)."""
    if not run_id:
        return
    md = result.get("metadata")
    if not isinstance(md, dict):
        md = {}
    md["run_id"] = run_id
    result["metadata"] = md


def main() -> None:
    args = parse_args()

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            "Example: cat landscape_enriched.json | python validate_landscape.py --pretty",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        sys.exit(1)

    result, errors = validate_landscape(data, as_of=args.as_of)

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    assert result is not None
    # Precedence: stdin (the sub-agent may have enriched it) > the draft > derived from the diff.
    if args.carry_deferred:
        _carry_deferred_recall_candidates(result, args.carry_deferred)
    if args.derive_deferred:
        _derive_deferred_recall_candidates(result, args.derive_deferred)
    _apply_run_id(result, args.run_id)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"

    warning_count = len(result.get("warnings", []))
    _write_output(
        out,
        args.output,
        summary={"warning_count": warning_count, "competitor_count": len(result["competitors"])},
    )


if __name__ == "__main__":
    main()
