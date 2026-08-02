#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
IC discussion composer — derives discussion.json from a real two-round debate.

Round 1 is the three independent PARTNER_ANALYSIS assessments
(partner_assessment_{visionary,operator,analyst}.json). Round 2 is the three
PARTNER_REBUTTAL rebuttals (partner_rebuttal_{visionary,operator,analyst}.json),
each written after that partner read the other two partners' round-1
assessments and decided whether new evidence changed their position.

This script is the only thing that writes discussion.json. Everything in its
output is copied or mechanically combined from those six input files — nothing
is authored here. That is the point: before this script existed, no artifact
ever compared a partner's opening position to their closing one, so nothing
stopped discussion.json from asserting a "post-debate" verdict that no partner
actually held.

Consensus rule (documented again in references/artifact-schemas.md):
consensus_verdict is the value shared by at least 2 of the 3 partners'
revised_verdict. With exactly three partners, a value with count >= 2 is
unique whenever one exists. If all three revised verdicts are distinct (no
majority), consensus_verdict is "more_diligence" — a genuine three-way split
cannot be presented as a decision one way or the other.

debated_dealbreakers carries every round-2 dealbreaker with its DIMENSION ID
intact, deduped by dimension, listing which archetypes raised it. key_concerns
keeps only the prose "reason", so it cannot answer "was this dimension argued?".
Scoring runs after this script, over all 28 dimensions, and may mark a
dealbreaker no partner raised — the debate is an input to that judgment, not a
constraint on it. This field is the id-level channel compose_report.py compares
against score_dimensions.json to disclose which scored dealbreakers were never
debated. Nothing here suppresses a scored dealbreaker: an undebated one can be
perfectly real, and dropping it would hide a fatal flaw from the founder.

debate_sections are derived from each rebuttal's "responses" array, grouped by
the archetype being addressed (topic = "Responses to <Archetype>"), in
canonical partner order. The exchange text is exactly what the responding
partner wrote in "point" (plus a mechanical "(concedes this point)" suffix
when they marked concedes=true) — never rewritten or summarized here.

Rejects (exit 1, JSON diagnostic {"error": ..., "errors": [...]} on stdout;
nothing is written to -o) when:
  - a rebuttal for one of the three archetypes is missing, or two rebuttal
    files resolve to the same internal "partner" value (missing or duplicate
    archetype coverage — see _load and the archetype-resolution loop below);
  - verdict_changed is true but changed_because is empty;
  - revised_verdict is outside the four-value verdict enum;
  - a dealbreaker has no evidence;
  - a dealbreaker's dimension id is not one of score_dimensions.py's 28
    canonical dimension ids (imported from that script, never hardcoded here).

A non-blocking POSSIBLE_CAPITULATION warning (in the output's "warnings" list)
fires when >= 2 of the 3 verdicts changed AND the changed verdicts converged
on the same value — the shape of three partners folding to whoever argued
hardest. This is UNCALIBRATED: it is detectable purely from vote-change
structure, and that structure looks identical whether the convergence was
earned by genuinely new evidence or manufactured by pressure. It never blocks
and never changes consensus_verdict; it exists only to flag the run for a
closer read.

Usage:
    python compose_discussion.py --dir ./ic-sim-acme/ --run-id "$RUN_ID" --pretty \
        -o discussion.json

Output: discussion.json (JSON) to stdout or -o on success. On rejection, a
JSON diagnostic to stdout and exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_dimensions  # noqa: E402

# Imported, never hardcoded — a renamed/added/removed dimension id in
# score_dimensions.py propagates here automatically.
VALID_DIMENSION_IDS: frozenset[str] = frozenset(score_dimensions.VALID_IDS)

CANONICAL_ARCHETYPES: tuple[str, ...] = ("visionary", "operator", "analyst")
VALID_VERDICTS: frozenset[str] = frozenset({"invest", "more_diligence", "pass", "hard_pass"})


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


def _as_list(value: Any) -> list[Any]:
    """Coerce to list — returns [] if not a list."""
    return value if isinstance(value, list) else []


def _load_artifact(dir_path: str, name: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load a JSON object artifact. Returns (data, None) on success or
    (None, error_message) on failure (missing file, unparseable JSON, or a
    non-object top level)."""
    path = os.path.join(dir_path, name)
    if not os.path.isfile(path):
        return None, f"missing artifact: {name}"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"unreadable artifact {name}: {e}"
    if not isinstance(data, dict):
        return None, f"artifact {name} is not a JSON object"
    return data, None


def compose(dir_path: str) -> dict[str, Any]:
    """Load the six round-1/round-2 artifacts, validate the round-2
    rebuttals, and derive discussion.json.

    Returns either the composed discussion object, or
    {"error": ..., "errors": [...]} — callers MUST check for the "error" key
    before treating the return value as a discussion.json body.
    """
    errors: list[str] = []

    assessments: dict[str, dict[str, Any]] = {}
    for archetype in CANONICAL_ARCHETYPES:
        data, err = _load_artifact(dir_path, f"partner_assessment_{archetype}.json")
        if err:
            errors.append(f"round-1 assessment: {err}")
        else:
            assert data is not None
            assessments[archetype] = data

    # Resolve each rebuttal file to an archetype via its OWN internal "partner"
    # field (never trust the filename alone) — this is what lets us detect a
    # sub-agent that wrote the wrong archetype's identity into its output, the
    # same class of mistake the Step 6 PARTNER_ANALYSIS dedup guard exists for.
    rebuttals: dict[str, dict[str, Any]] = {}
    for archetype in CANONICAL_ARCHETYPES:
        fname = f"partner_rebuttal_{archetype}.json"
        data, err = _load_artifact(dir_path, fname)
        if err:
            errors.append(f"round-2 rebuttal: {err}")
            continue
        assert data is not None
        partner = data.get("partner")
        if partner not in CANONICAL_ARCHETYPES:
            errors.append(f"{fname}: 'partner' field is {partner!r}, must be one of {sorted(CANONICAL_ARCHETYPES)}")
            continue
        if partner in rebuttals:
            errors.append(f"duplicate archetype among rebuttals: '{partner}' (from {fname} and an earlier file)")
            continue
        if partner != archetype:
            errors.append(
                f"{fname}: internal partner '{partner}' does not match the expected archetype "
                f"'{archetype}' for this filename"
            )
        rebuttals[partner] = data

    missing_archetypes = set(CANONICAL_ARCHETYPES) - set(rebuttals)
    for missing in sorted(missing_archetypes):
        errors.append(f"missing rebuttal for archetype: '{missing}'")

    # Per-rebuttal content validation — only over rebuttals that resolved to a
    # real, non-duplicate archetype above.
    for archetype, reb in rebuttals.items():
        revised = reb.get("revised_verdict")
        if revised not in VALID_VERDICTS:
            errors.append(
                f"partner_rebuttal_{archetype}.json: revised_verdict {revised!r} not in {sorted(VALID_VERDICTS)}"
            )

        if reb.get("verdict_changed") is True:
            changed_because = reb.get("changed_because")
            if not isinstance(changed_because, str) or not changed_because.strip():
                errors.append(
                    f"partner_rebuttal_{archetype}.json: verdict_changed is true but changed_because is empty"
                )

        for i, db in enumerate(_as_list(reb.get("dealbreakers"))):
            if not isinstance(db, dict):
                errors.append(f"partner_rebuttal_{archetype}.json: dealbreakers[{i}] must be an object")
                continue
            dimension = db.get("dimension")
            if dimension not in VALID_DIMENSION_IDS:
                errors.append(
                    f"partner_rebuttal_{archetype}.json: dealbreakers[{i}].dimension {dimension!r} "
                    "is not a recognized dimension id"
                )
            evidence = db.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                errors.append(f"partner_rebuttal_{archetype}.json: dealbreakers[{i}] has no evidence")

    if errors:
        return {"error": "invalid_rebuttal_round", "errors": errors}

    return _derive(assessments, rebuttals)


def _derive(assessments: dict[str, dict[str, Any]], rebuttals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build discussion.json from validated round-1 + round-2 artifacts.

    Every field is copied or mechanically combined from partner-authored
    content — nothing is authored in this function.
    """
    partner_verdicts: list[dict[str, Any]] = []
    for archetype in CANONICAL_ARCHETYPES:
        reb = rebuttals[archetype]
        verdict = reb["revised_verdict"]
        if reb.get("verdict_changed") is True:
            rationale = reb.get("changed_because") or ""
        else:
            rationale = assessments.get(archetype, {}).get("rationale") or ""
        partner_verdicts.append({"partner": archetype, "verdict": verdict, "rationale": rationale})

    # Consensus: majority of the three revised verdicts; no majority (all
    # three distinct) -> more_diligence. See module docstring for the rule.
    vote_counts: dict[str, int] = {}
    for pv in partner_verdicts:
        vote_counts[pv["verdict"]] = vote_counts.get(pv["verdict"], 0) + 1
    majority = [v for v, n in vote_counts.items() if n >= 2]
    consensus_verdict = majority[0] if majority else "more_diligence"

    # Debate sections: group each rebuttal's responses by the archetype being
    # addressed. The position text is the responding partner's own "point",
    # verbatim (plus a mechanical concession marker) — never a rewrite.
    by_target: dict[str, list[dict[str, Any]]] = {a: [] for a in CANONICAL_ARCHETYPES}
    dropped_response_reasons: dict[str, int] = {}
    for archetype in CANONICAL_ARCHETYPES:
        for resp in _as_list(rebuttals[archetype].get("responses")):
            if not isinstance(resp, dict):
                dropped_response_reasons["entry_not_object"] = dropped_response_reasons.get("entry_not_object", 0) + 1
                continue
            to = resp.get("to")
            point = resp.get("point")
            if to not in CANONICAL_ARCHETYPES:
                dropped_response_reasons["unrecognized_target"] = (
                    dropped_response_reasons.get("unrecognized_target", 0) + 1
                )
                continue
            if not isinstance(point, str) or not point.strip():
                dropped_response_reasons["empty_point"] = dropped_response_reasons.get("empty_point", 0) + 1
                continue
            position = point.strip()
            if resp.get("concedes") is True:
                position += " (concedes this point)"
            by_target[to].append({"partner": archetype, "position": position})

    debate_sections = [
        {"topic": f"Responses to {target.title()}", "exchanges": by_target[target]}
        for target in CANONICAL_ARCHETYPES
        if by_target[target]
    ]

    # diligence_requirements: union across the 3 rebuttals' (post-debate)
    # lists, order-preserving, first-seen wins.
    diligence_requirements: list[str] = []
    seen_dr: set[str] = set()
    for archetype in CANONICAL_ARCHETYPES:
        for req in _as_list(rebuttals[archetype].get("diligence_requirements")):
            if isinstance(req, str) and req.strip() and req.strip() not in seen_dr:
                seen_dr.add(req.strip())
                diligence_requirements.append(req.strip())

    # debated_dealbreakers: the round-2 dealbreakers with their DIMENSION IDS
    # preserved, deduped by dimension, accumulating who raised each one.
    #
    # This exists because key_concerns (built below) carries only each
    # dealbreaker's prose `reason`, with the dimension id dropped. That makes it
    # impossible for any downstream consumer to answer "was this dimension
    # actually argued in the debate?" — and scoring runs AFTER this file, over
    # all 28 dimensions, free to mark a dealbreaker no partner ever raised. On a
    # measured run it did exactly that (4 scored, 3 debated), and the report
    # narrated all four as though the IC had argued them. compose_report.py
    # compares this list against score_dimensions.json to disclose the
    # difference; without the ids there is no channel for it to compare on.
    debated_dealbreakers: list[dict[str, Any]] = []
    by_dimension: dict[str, dict[str, Any]] = {}
    for archetype in CANONICAL_ARCHETYPES:
        for db in _as_list(rebuttals[archetype].get("dealbreakers")):
            if not isinstance(db, dict):
                continue
            dimension = db.get("dimension")
            if dimension not in VALID_DIMENSION_IDS:
                continue
            entry = by_dimension.get(dimension)
            if entry is None:
                entry = {"dimension": dimension, "raised_by": [], "evidence": []}
                by_dimension[dimension] = entry
                debated_dealbreakers.append(entry)
            if archetype not in entry["raised_by"]:
                entry["raised_by"].append(archetype)
            ev = db.get("evidence")
            if isinstance(ev, str) and ev.strip() and ev.strip() not in entry["evidence"]:
                entry["evidence"].append(ev.strip())

    # key_concerns: union of round-1 key_concerns plus round-2 dealbreaker
    # reasons — everything that survived (or emerged from) the debate.
    key_concerns: list[str] = []
    seen_kc: set[str] = set()
    for archetype in CANONICAL_ARCHETYPES:
        for kc in _as_list(assessments.get(archetype, {}).get("key_concerns")):
            if isinstance(kc, str) and kc.strip() and kc.strip() not in seen_kc:
                seen_kc.add(kc.strip())
                key_concerns.append(kc.strip())
        for db in _as_list(rebuttals[archetype].get("dealbreakers")):
            if isinstance(db, dict):
                reason = db.get("reason")
                if isinstance(reason, str) and reason.strip() and reason.strip() not in seen_kc:
                    seen_kc.add(reason.strip())
                    key_concerns.append(reason.strip())

    # POSSIBLE_CAPITULATION — see module docstring: uncalibrated, never
    # blocking, never changes consensus_verdict.
    changed_verdicts = [
        rebuttals[a]["revised_verdict"] for a in CANONICAL_ARCHETYPES if rebuttals[a].get("verdict_changed") is True
    ]
    warnings: list[str] = []
    if len(changed_verdicts) >= 2 and len(set(changed_verdicts)) == 1:
        warnings.append("POSSIBLE_CAPITULATION")

    # DROPPED_REBUTTAL_RESPONSES — non-blocking disclosure that some round-2
    # response entries were silently excluded from debate_sections (malformed
    # entry, unrecognized target, or empty point — none of these are among the
    # 5 documented hard-reject conditions, see module docstring). Without this,
    # a failed round-two exchange is indistinguishable from a genuinely
    # one-sided debate where nobody had anything to say. Never blocks and
    # never changes consensus_verdict.
    total_dropped = sum(dropped_response_reasons.values())
    if total_dropped:
        reason_summary = ", ".join(f"{reason}={count}" for reason, count in sorted(dropped_response_reasons.items()))
        warnings.append(
            f"DROPPED_REBUTTAL_RESPONSES: {total_dropped} response entr"
            f"{'y' if total_dropped == 1 else 'ies'} dropped from debate_sections ({reason_summary})"
        )

    return {
        "assessment_mode": "sub-agent",
        "partner_verdicts": partner_verdicts,
        "debate_sections": debate_sections,
        "consensus_verdict": consensus_verdict,
        "debated_dealbreakers": debated_dealbreakers,
        "key_concerns": key_concerns,
        "diligence_requirements": diligence_requirements,
        "warnings": warnings,
        "_produced_by": "compose_discussion",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Derive discussion.json from round-1 assessments + round-2 rebuttals")
    p.add_argument("-d", "--dir", required=True, help="Directory containing the 6 canonical partner artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", required=True, help="Run identifier injected into metadata.run_id")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    result = compose(args.dir)

    if "error" in result:
        # Reject: nothing is written to -o. A discussion.json a founder could
        # read as "the IC debated this" must never land on disk unless it was
        # actually derived from six validated partner artifacts.
        sys.stdout.write(json.dumps(result, indent=2 if args.pretty else None) + "\n")
        sys.exit(1)

    # Inject metadata.run_id as the last step before serialization (matches
    # every other ic-sim producer's contract).
    result["metadata"] = {"run_id": args.run_id}

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={
            "consensus_verdict": result.get("consensus_verdict"),
            "warnings": len(result.get("warnings", [])),
        },
    )


if __name__ == "__main__":
    main()
