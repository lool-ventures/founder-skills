#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Competitor-set verification validator for competitive-positioning.

Role: VALIDATOR, not detector. A fresh Context-A sub-agent independently
re-characterizes each competitor and judges genuine overlap against the
startup; THIS script validates that JSON's structure, enforces the
"show-your-work" gate (a non-genuine verdict must carry reasoning + an
independent characterization with buyer + job_to_be_done), cross-checks that
every landscape slug has exactly one verdict, computes the summary, and stamps
run_id. It never authors or overrides a verdict.

Optionally also diffs a BLIND recall set (`--blind-set`): a second sub-agent
that read only the product profile — never the drafted competitor list — and
independently named who it thinks competes. This is a deterministic diff
against the draft slugs, never an agent judgment, and surfaces under
`recall_gaps` in the output which competitors the blind agent found that the
draft missed.

Reads verdict JSON from stdin. Output: validated JSON + computed summary +
validation.status/errors (+ recall_gaps when --blind-set is given). Exit 0
valid, exit 1 on any violation (including an unreadable/malformed
--blind-set file), exit 2 if --blind-set is given without --landscape.

Usage:
    cat verdicts.json | python verify_competitors.py --run-id R1 \
        --landscape landscape_draft.json -o competitor_verification.json --pretty

    cat verdicts.json | python verify_competitors.py --run-id R1 \
        --landscape landscape_draft.json --blind-set blind_recall.json \
        -o competitor_verification.json --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

VERDICTS = {"genuine", "adjacent", "not_a_competitor"}
ACTIONS = {"keep", "reclassify_adjacent", "reclassify_direct", "challenge_removal"}
SOURCES = {"researched", "agent_estimate", "founder_provided"}

# verdict -> draft category pairs that unambiguously mean the draft undersold
# ("upgrade") or oversold ("downgrade") the overlap. do_nothing/emerging are
# deliberately excluded: those two categories encode market ROLE (status-quo
# alternative, convergence risk), not DEGREE of overlap, so a genuine/adjacent
# verdict landing on either one is not evidence the draft mischaracterized
# anything. custom is excluded too — its semantics are caller-defined, so no
# fixed verdict is "expected" for it.
_DISAGREEMENT_DIRECTIONS = {
    ("genuine", "adjacent"): "upgrade",
    ("adjacent", "direct"): "downgrade",
}


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


# ---------------------------------------------------------------------------
# Blind-recall diff (--blind-set)
# ---------------------------------------------------------------------------

# A trailing corporate-suffix token, matched only when it is preceded by a
# comma/period (with optional following space) or by whitespace — i.e. only
# when it is a separate token, never when it's glued onto the preceding word
# (so "PayCorp" is untouched) and never when it IS the whole name (so a
# company literally called "Corp" stays "corp", not "").
_CORP_SUFFIX_RE = re.compile(r"(?:[,.]\s*|\s+)(?:inc|llc|ltd|corp|co|gmbh|plc)\.?$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_competitor_slug(text: str) -> str:
    """Normalize a company name or slug for cross-set slug comparison.

    Lowercases, strips a trailing corporate-suffix token (inc/llc/ltd/corp/
    co/gmbh/plc) together with its preceding comma/period or whitespace
    separator, then collapses any run of non-alphanumeric characters to a
    single hyphen and trims leading/trailing hyphens. Idempotent on an
    already-normalized slug, so it is safe to run on both sides of a diff
    regardless of whether a string started life as a free-text name or an
    existing kebab-case slug.

    "ServiceTitan, Inc." -> "servicetitan"; "Housecall Pro" -> "housecall-pro";
    "Jobber" -> "jobber"; "Corp" -> "corp" (guarded — see _CORP_SUFFIX_RE).
    """
    s = (text or "").strip().lower()
    m = _CORP_SUFFIX_RE.search(s)
    if m:
        s = s[: m.start()]
    return _NON_ALNUM_RE.sub("-", s).strip("-")


_RECALL_GAP_NOTE = (
    "draft_only lists competitors present in the draft but not returned by "
    "the blind agent. This is diagnostic only, NOT evidence that a "
    "competitor is fake — the precision verdicts already cover genuineness; "
    "a blind agent simply failing to independently recall something is weak "
    "evidence on its own and must not be treated as a verdict. unmatched "
    "entries that are actually the SAME competitor as something already in "
    "the draft (a slug spelling variant, or a named member of a cohort "
    "entry's `constituents`) are moved into probable_duplicates instead — "
    "see _slugs_are_variants()/constituent lookup below; that demotion is "
    "the only thing ever removed from unmatched. A surviving unmatched "
    "entry may additionally carry `possible_overlap_with` when its "
    "normalized name/slug turns up as a word in a draft entry's prose — "
    "that is an ANNOTATION ONLY, never a demotion, because a text-substring "
    "heuristic was measured to falsely disappear real gaps."
)

# ---------------------------------------------------------------------------
# Slug-variant demotion (Task 1): maximum bipartite token matching
# ---------------------------------------------------------------------------

# A proper-prefix token pair (one token strictly shorter and a prefix of the
# other) only counts as a match once the shared prefix is at least this long.
# Equal tokens always match regardless of length (see _token_match_kind) —
# that clause is load-bearing, because short tokens like "quo" (3 chars)
# would otherwise never clear this floor and the rule would demote nothing.
_TOKEN_MIN_PREFIX_COMMON = 5

# Cohort-suspicion text annotation (Task 3): a candidate token must be at
# least this long, and not a generic category word, before it is allowed to
# annotate (never demote) an unmatched entry with `possible_overlap_with`.
_ANNOTATE_TOKEN_MIN_LEN = 4
_GENERIC_TEXT_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "status",
    "quo",
    "system",
    "systems",
    "solution",
    "solutions",
    "platform",
    "service",
    "services",
    "technology",
    "technologies",
    "company",
    "companies",
    "energy",
    "storage",
    "thermal",
}


def _slug_tokens(slug: str) -> list[str]:
    return [t for t in slug.split("-") if t]


def _token_match_kind(a: str, b: str) -> str | None:
    """ "exact" | "prefix" | None for a single token pair.

    Equal tokens always match ("exact"), with no length floor. A "prefix"
    match requires one token be a *proper* prefix of the other (they must
    differ) with at least `_TOKEN_MIN_PREFIX_COMMON` shared characters —
    this is what lets "oversized" match "oversize" and "chiller" match
    "chillers", while refusing to let a bare brand prefix like "square"
    match "squarespace" on its own (that pair IS a valid "prefix" edge here;
    the brand-prefix guard against it lives in `_slugs_are_variants`, which
    additionally requires at least one "exact" pair in the chosen matching).
    """
    if a == b:
        return "exact"
    if not a or not b:
        return None
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if longer.startswith(shorter) and len(shorter) >= _TOKEN_MIN_PREFIX_COMMON:
        return "prefix"
    return None


def _slugs_are_variants(norm_a: str, norm_b: str) -> bool:
    """Slug-variant test: do two ALREADY-NORMALIZED slugs' token lists match
    under maximum bipartite matching?

    Token counts must be equal. This is deliberately NOT greedy left-to-right
    pairing — greedy is order-dependent (e.g. tokens [chille, chilled] vs
    [chilled, chiller] pair up under one ordering and fail under another).
    Instead this runs a standard augmenting-path (Kuhn's) maximum-matching
    search: the maximum matching's SIZE is a property of the bipartite graph
    alone and is provably independent of the order vertices are processed
    in, so token order on either side of the comparison cannot change
    whether a full match is found.

    Brand-prefix guard: even a full match is only accepted if at least one
    of its token pairs is an EXACT pair. Without this, single-token slugs
    like "square"/"squarespace" or "chart"/"chartio" would match on a bare
    prefix relation alone — measured false positives. Adjacency lists are
    ordered exact-edges-first specifically so that, among possibly several
    maximum matchings, the search preferentially lands on one containing an
    exact pair whenever one exists.
    """
    a_tokens = _slug_tokens(norm_a)
    b_tokens = _slug_tokens(norm_b)
    n = len(a_tokens)
    if n == 0 or n != len(b_tokens):
        return False

    kind: list[list[str | None]] = [[_token_match_kind(a_tokens[i], b_tokens[j]) for j in range(n)] for i in range(n)]
    adj = [
        [j for j in range(n) if kind[i][j] == "exact"] + [j for j in range(n) if kind[i][j] == "prefix"]
        for i in range(n)
    ]
    match_to_left = [-1] * n  # right index j -> left index i, or -1 if unmatched

    def try_augment(i: int, visited: list[bool]) -> bool:
        for j in adj[i]:
            if visited[j]:
                continue
            visited[j] = True
            if match_to_left[j] == -1 or try_augment(match_to_left[j], visited):
                match_to_left[j] = i
                return True
        return False

    matched = 0
    for i in range(n):
        if try_augment(i, [False] * n):
            matched += 1
    if matched != n:
        return False
    return any(kind[match_to_left[j]][j] == "exact" for j in range(n))


def _draft_text_blob(comp: dict[str, Any]) -> str:
    parts = [str(comp.get("name") or ""), str(comp.get("description") or "")]
    kd = comp.get("key_differentiators")
    if isinstance(kd, list):
        parts.append(" ".join(str(x) for x in kd if _nonempty(x)))
    return " ".join(parts).lower()


def _find_possible_overlap(candidate_norm_slug: str, text_blobs: list[tuple[str, str]]) -> str | None:
    """Task 3: cohort-membership hint, ANNOTATION ONLY (never a demotion — see the
    docstring on `diff_recall_gaps`). Returns the first matching draft's raw slug, or None.

    Requires the candidate's WHOLE normalized name to appear as a word-boundary phrase in
    the draft entry's text — not any single token of it. Measured on a real run, a
    single-token rule annotated 5 of 7 gaps and most were misleading: `johnson-controls`
    matched a Trane entry on the word "controls", `cold-utes` matched a PCM entry on "cold",
    `bess-peak-shaving` matched on "peak". Those are industry vocabulary, not evidence that a
    competitor is already represented — and a stoplist cannot enumerate them (the same
    argument that governs the leak scanner's class-based design). Whole-phrase matching keeps
    exactly the true cohort members, which are named verbatim inside the cohort's prose.

    The annotation never hides a gap, so a miss costs only a hint. A false hint, by contrast,
    tells the founder a real gap is already covered — so this is deliberately biased toward
    silence.
    """
    phrase = " ".join(t for t in _slug_tokens(candidate_norm_slug) if t)
    if not phrase or len(phrase) < _ANNOTATE_TOKEN_MIN_LEN or phrase in _GENERIC_TEXT_WORDS:
        return None
    for raw_slug, blob in text_blobs:
        if not blob.strip():
            continue
        # The blob is lowercased raw prose; the candidate phrase is hyphen-normalized, so
        # allow any non-alphanumeric run between its words ("chilled-water" ~ "chilled water").
        pattern = r"\b" + r"[^a-z0-9]+".join(re.escape(t) for t in phrase.split(" ")) + r"\b"
        if re.search(pattern, blob):
            return raw_slug
    return None


def diff_recall_gaps(blind_payload: Any, draft_competitors: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministically diff a blind-recall candidate set against the
    drafted landscape. Returns the `recall_gaps` block.

    Validation happens here (not upstream) because unsourced claims must
    never reach the founder: a candidate missing name/why_considered/sources
    is DROPPED (recorded, not fatal) before it can be laundered into a
    "the draft missed this" gap. A missing/empty/non-list `candidates` is
    likewise not an error — a blind agent legitimately finding nothing must
    not red the run.

    Beyond the original exact-slug diff, a surviving `unmatched` candidate
    is run through two ADDITIONAL demotion passes (in order) before falling
    through to an annotation-only pass:

      1. slug_variant — `_slugs_are_variants` against every draft slug.
      2. constituent — the candidate's normalized name/slug against every
         draft entry's `constituents` list (exact lookup only).
      3. (never a demotion) cohort-suspicion text annotation via
         `_find_possible_overlap` — sets `possible_overlap_with` on an
         entry that stays in `unmatched`.

    This is demote-only: `unmatched` can only shrink relative to what a
    pure exact-slug diff would have produced, never grow.
    """
    candidates = blind_payload.get("candidates") if isinstance(blind_payload, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return {
            "blind_set_size": 0,
            "matched": [],
            "unmatched": [],
            "probable_duplicates": [],
            "draft_only": [],
            "dropped": [],
            "note": (
                "No blind-set candidates were provided (missing, not a list, or "
                "empty); recall_gaps is empty. A blind agent that legitimately "
                "finds no additional competitors must not fail the run."
            ),
        }

    draft_entries = [c for c in draft_competitors if isinstance(c, dict)]
    draft_slugs = [str(c.get("slug")) for c in draft_entries if _nonempty(c.get("slug"))]
    draft_norm = {normalize_competitor_slug(s) for s in draft_slugs}

    # normalized draft slug -> raw (as-authored) slug, first wins
    draft_norm_to_raw: dict[str, str] = {}
    for s in draft_slugs:
        n = normalize_competitor_slug(s)
        if n and n not in draft_norm_to_raw:
            draft_norm_to_raw[n] = s

    # normalized constituent name/slug -> raw draft slug, first wins
    constituent_to_raw: dict[str, str] = {}
    for c in draft_entries:
        raw_slug_val = c.get("slug")
        if not _nonempty(raw_slug_val):
            continue
        raw_slug = str(raw_slug_val)
        constituents = c.get("constituents")
        if not isinstance(constituents, list):
            continue
        for member in constituents:
            if not _nonempty(member):
                continue
            n = normalize_competitor_slug(str(member))
            if n and n not in constituent_to_raw:
                constituent_to_raw[n] = raw_slug

    # (raw draft slug, lowercased name+description+key_differentiators blob)
    text_blobs = [(str(c.get("slug")), _draft_text_blob(c)) for c in draft_entries if _nonempty(c.get("slug"))]

    dropped: list[dict[str, str]] = []
    by_slug: dict[str, dict[str, Any]] = {}  # normalized slug -> full entry, first wins
    for c in candidates:
        if not isinstance(c, dict):
            dropped.append({"name": "?", "reason": "candidate is not an object"})
            continue
        name = c.get("name")
        why = c.get("why_considered")
        sources = c.get("sources")
        reasons: list[str] = []
        if not _nonempty(name):
            reasons.append("name missing/empty")
        if not _nonempty(why):
            reasons.append("why_considered missing/empty")
        clean_sources = [s for s in sources if _nonempty(s)] if isinstance(sources, list) else []
        if not clean_sources:
            reasons.append("sources missing/empty (needs at least one non-empty source)")
        if reasons:
            dropped.append({"name": str(name) if _nonempty(name) else "?", "reason": "; ".join(reasons)})
            continue
        cand_raw_slug = c.get("slug") if _nonempty(c.get("slug")) else name
        norm = normalize_competitor_slug(str(cand_raw_slug))
        if norm and norm not in by_slug:
            by_slug[norm] = {"slug": norm, "name": name, "why_considered": why, "sources": clean_sources}

    matched = sorted(n for n in by_slug if n in draft_norm)

    # Everything not already an exact match starts as a demotion candidate.
    remaining: dict[str, dict[str, Any]] = {n: e for n, e in by_slug.items() if n not in draft_norm}

    probable_duplicates: list[dict[str, str]] = []

    # --- Task 1: slug-variant demotion ---
    still_remaining: dict[str, dict[str, Any]] = {}
    for n, entry in remaining.items():
        hit_raw: str | None = None
        for draft_n, draft_raw in draft_norm_to_raw.items():
            if _slugs_are_variants(n, draft_n):
                hit_raw = draft_raw
                break
        if hit_raw is not None:
            probable_duplicates.append(
                {"slug": entry["slug"], "name": entry["name"], "matched_draft_slug": hit_raw, "rule": "slug_variant"}
            )
        else:
            still_remaining[n] = entry
    remaining = still_remaining

    # --- Task 2: constituent membership (exact normalized lookup only) ---
    still_remaining = {}
    for n, entry in remaining.items():
        name_norm = normalize_competitor_slug(str(entry["name"])) if _nonempty(entry["name"]) else ""
        hit_raw = constituent_to_raw.get(n) or (constituent_to_raw.get(name_norm) if name_norm else None)
        if hit_raw is not None:
            probable_duplicates.append(
                {"slug": entry["slug"], "name": entry["name"], "matched_draft_slug": hit_raw, "rule": "constituent"}
            )
        else:
            still_remaining[n] = entry
    remaining = still_remaining

    # --- Task 3: cohort-suspicion text annotation (never demotes) ---
    unmatched: list[dict[str, Any]] = []
    for n in sorted(remaining):
        entry = dict(remaining[n])
        overlap = _find_possible_overlap(entry["slug"], text_blobs)
        if overlap is not None:
            entry["possible_overlap_with"] = overlap
        unmatched.append(entry)

    draft_only = sorted(n for n in draft_norm if n not in by_slug)

    return {
        "blind_set_size": len(candidates),
        "matched": matched,
        "unmatched": unmatched,
        "probable_duplicates": probable_duplicates,
        "draft_only": draft_only,
        "dropped": dropped,
        "note": _RECALL_GAP_NOTE,
    }


def validate(
    payload: dict[str, Any],
    run_id: str | None,
    landscape_slugs: list[str] | None,
    landscape_categories: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    verdicts = payload.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        errors.append("verdicts: must be a non-empty array")
        verdicts = []

    sc = payload.get("startup_characterization")
    if not isinstance(sc, dict) or not _nonempty(sc.get("buyer")) or not _nonempty(sc.get("job_to_be_done")):
        errors.append("startup_characterization: buyer and job_to_be_done required")

    seen: list[str] = []
    counts = {"genuine": 0, "adjacent": 0, "not_a_competitor": 0}
    flagged_slugs: list[str] = []
    syw_violations: list[str] = []
    category_disagreements: list[dict[str, str]] = []

    for i, v in enumerate(verdicts):
        slug = v.get("slug")
        if not _nonempty(slug):
            errors.append(f"verdicts[{i}]: slug required")
            continue
        seen.append(slug)
        verdict = v.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{slug}: verdict must be one of {sorted(VERDICTS)}")
            continue
        counts[verdict] += 1
        draft_category = (landscape_categories or {}).get(slug)
        if draft_category is not None:
            direction = _DISAGREEMENT_DIRECTIONS.get((verdict, draft_category))
            if direction is not None:
                category_disagreements.append(
                    {
                        "slug": slug,
                        "draft_category": draft_category,
                        "verdict": verdict,
                        "direction": direction,
                    }
                )
        if v.get("recommended_action") not in ACTIONS:
            errors.append(f"{slug}: recommended_action must be one of {sorted(ACTIONS)}")
        ic = v.get("independent_characterization")
        if not isinstance(ic, dict):
            errors.append(f"{slug}: independent_characterization required")
            ic = {}
        if ic.get("evidence_source") not in SOURCES:
            errors.append(f"{slug}: independent_characterization.evidence_source invalid")
        # --- show-your-work gate: a flag must prove it understood the company ---
        if verdict != "genuine":
            flagged_slugs.append(slug)
            if not _nonempty(v.get("reasoning")):
                syw_violations.append(slug)
                errors.append(f"{slug}: flagged verdict requires non-empty reasoning")
            if not _nonempty(ic.get("buyer")):
                syw_violations.append(slug)
                errors.append(f"{slug}: flagged verdict requires independent_characterization.buyer")
            if not _nonempty(ic.get("job_to_be_done")):
                syw_violations.append(slug)
                errors.append(f"{slug}: flagged verdict requires independent_characterization.job_to_be_done")

    dups = sorted({s for s in seen if seen.count(s) > 1})
    if dups:
        errors.append(f"duplicate verdict slugs: {dups}")

    if landscape_slugs is not None:
        missing = [s for s in landscape_slugs if s not in seen]
        extra = [s for s in seen if s not in landscape_slugs]
        if missing:
            errors.append(f"landscape slugs missing a verdict: {missing}")
        if extra:
            errors.append(f"verdicts for slugs not in landscape: {extra}")

    md_run = (payload.get("metadata") or {}).get("run_id")
    if run_id is not None and md_run != run_id:
        errors.append(f"metadata.run_id ({md_run!r}) != --run-id ({run_id!r})")

    payload["summary"] = {
        "total": len(seen),
        "genuine": counts["genuine"],
        "adjacent": counts["adjacent"],
        "not_a_competitor": counts["not_a_competitor"],
        "flagged": len(flagged_slugs),
        "flagged_slugs": flagged_slugs,
        "show_your_work_violations": sorted(set(syw_violations)),
        "category_disagreements": category_disagreements,
    }
    if run_id is not None:
        payload.setdefault("metadata", {})["run_id"] = run_id
    payload["_produced_by"] = "verify_competitors.py"
    payload["validation"] = {"status": "error" if errors else "ok", "errors": errors}
    return payload, errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id")
    ap.add_argument("--landscape", help="landscape*.json — cross-check every slug has a verdict")
    ap.add_argument(
        "--blind-set",
        help=(
            "blind-recall candidates JSON (e.g. blind_recall.json) — deterministically diffed "
            "against --landscape's slugs to surface recall_gaps. Requires --landscape."
        ),
    )
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    if args.blind_set and not args.landscape:
        print("Error: --blind-set requires --landscape (nothing to diff the blind set against)", file=sys.stderr)
        return 2

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1

    landscape_slugs = None
    landscape_categories: dict[str, str] | None = None
    landscape_competitors: list[dict[str, Any]] = []
    if args.landscape:
        with open(args.landscape, encoding="utf-8") as f:
            land = json.load(f)
        landscape_competitors = [c for c in land.get("competitors", []) if isinstance(c, dict)]
        landscape_slugs = [str(c.get("slug")) for c in landscape_competitors if c.get("slug")]
        landscape_categories = {
            str(c.get("slug")): str(c.get("category"))
            for c in landscape_competitors
            if c.get("slug") and c.get("category")
        }

    blind_recall_gaps: dict[str, Any] | None = None
    if args.blind_set:
        try:
            with open(args.blind_set, encoding="utf-8") as f:
                blind_payload = json.load(f)
        except OSError as e:
            print(f"Error: cannot read --blind-set file {args.blind_set!r}: {e}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"Error: --blind-set file {args.blind_set!r} is not valid JSON: {e}", file=sys.stderr)
            return 1
        blind_recall_gaps = diff_recall_gaps(blind_payload, landscape_competitors)

    validated, errors = validate(payload, args.run_id, landscape_slugs, landscape_categories)
    if blind_recall_gaps is not None:
        validated["recall_gaps"] = blind_recall_gaps
    text = json.dumps(validated, indent=2) if args.pretty else json.dumps(validated, separators=(",", ":"))

    if args.output:
        abs_path = os.path.abspath(args.output)
        parent = os.path.dirname(abs_path)
        if parent in ("", "/"):
            print(f"Error: refusing to write to {args.output!r}", file=sys.stderr)
            return 1
        os.makedirs(parent, exist_ok=True)
        # Always write the artifact (audit trail) even on validation error; the
        # nonzero exit below halts the producer pipe.
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(text)
        receipt = {
            "ok": not errors,
            "path": abs_path,
            "flagged": validated["summary"]["flagged"],
            "status": validated["validation"]["status"],
        }
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(text + "\n")

    if errors:
        print(f"validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
