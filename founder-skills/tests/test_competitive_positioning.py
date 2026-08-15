#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for competitive positioning scripts.

Run: pytest founder-skills/tests/test_competitive_positioning.py -v
All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FOUNDER_SKILLS_DIR = os.path.dirname(SCRIPT_DIR)
CP_SCRIPTS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts")
CP_SKILL_MD = os.path.join(FOUNDER_SKILLS_DIR, "skills", "competitive-positioning", "SKILL.md")
CP_AGENT_MD = os.path.join(FOUNDER_SKILLS_DIR, "agents", "competitive-positioning.md")
CP_ARTIFACT_SCHEMAS_MD = os.path.join(
    FOUNDER_SKILLS_DIR, "skills", "competitive-positioning", "references", "artifact-schemas.md"
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_script(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(CP_SCRIPTS_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def run_script_raw(
    name: str,
    args: list[str] | None = None,
    stdin_data: str | None = None,
) -> tuple[int, str, str]:
    """Like run_script but returns (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(CP_SCRIPTS_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Factory: valid landscape_enriched.json input
# ---------------------------------------------------------------------------


def _make_competitor(
    name: str,
    slug: str,
    category: str = "direct",
    *,
    research_depth: str = "full",
    sourced_fields_count: int = 5,
    evidence_source: dict[str, str] | None = None,
    recent_developments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a single enriched competitor entry."""
    comp: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "category": category,
        "description": f"{name} is a competitor in the market.",
        "key_differentiators": ["Feature A", "Feature B"],
        "pricing_model": "SaaS, $99/mo",
        "funding": "Series A, $10M",
        "strengths": ["Good product"],
        "weaknesses": ["Small team"],
        "evidence_source": evidence_source or {"description": "researched", "pricing_model": "researched"},
        "research_depth": research_depth,
        "sourced_fields_count": sourced_fields_count,
    }
    if recent_developments is not None:
        comp["recent_developments"] = recent_developments
    return comp


def _make_recent_development(
    *,
    date: str = "2026-03",
    dev_type: str = "funding",
    summary: str = "Raised a $20M Series B.",
    source: str = "https://example.com/news/series-b",
    relevance: str | None = "Signals aggressive expansion into our segment.",
) -> dict[str, Any]:
    """Build a single recent_developments[] entry."""
    entry: dict[str, Any] = {
        "date": date,
        "type": dev_type,
        "summary": summary,
        "source": source,
    }
    if relevance is not None:
        entry["relevance"] = relevance
    return entry


def _make_valid_landscape(
    *,
    competitors: list[dict[str, Any]] | None = None,
    input_mode: str = "conversation",
    research_depth: str = "full",
    run_id: str = "20260319T143045Z",
    data_confidence: float | None = None,
) -> dict[str, Any]:
    """Build a valid landscape_enriched.json payload with 5 competitors."""
    if competitors is None:
        competitors = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Manual Process", "manual-process", "do_nothing"),
        ]
    result: dict[str, Any] = {
        "competitors": competitors,
        "assessment_mode": "sub-agent",
        "research_depth": research_depth,
        "input_mode": input_mode,
        "metadata": {"run_id": run_id},
    }
    if data_confidence is not None:
        result["data_confidence"] = data_confidence
    return result


# ===========================================================================
# validate_landscape.py tests
# ===========================================================================


class TestValidateLandscape:
    """Tests for validate_landscape.py."""

    # 1. Well-formed input passes
    def test_valid_landscape_passes(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "competitors" in data
        assert len(data["competitors"]) == 5
        assert "warnings" in data
        assert isinstance(data["warnings"], list)
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        assert data["input_mode"] == "conversation"

    # 2. Missing required field fails
    def test_missing_required_field_fails(self) -> None:
        payload = _make_valid_landscape()
        del payload["competitors"][0]["slug"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 3. Duplicate slugs fails
    def test_duplicate_slugs_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][1]["slug"] = payload["competitors"][0]["slug"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 4. Missing do_nothing warns
    def test_missing_do_nothing_warns(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "direct"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Epsilon SA", "epsilon-sa", "direct"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_DO_NOTHING" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MISSING_DO_NOTHING")
        assert warn["severity"] == "medium"

    # 5. Adjacent only suppresses warning
    def test_adjacent_only_suppresses_warning(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Epsilon SA", "epsilon-sa", "direct"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_DO_NOTHING" not in codes

    # 6. Invalid category fails
    def test_invalid_category_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["category"] = "bogus"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 7. Bounds min fails (2 competitors)
    def test_bounds_min_fails(self) -> None:
        comps = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "do_nothing"),
        ]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 8. Bounds max fails (11 competitors)
    def test_bounds_max_fails(self) -> None:
        comps = [_make_competitor(f"Comp {i}", f"comp-{i}", "direct") for i in range(11)]
        payload = _make_valid_landscape(competitors=comps)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 9. Preserves provenance fields
    def test_preserves_provenance(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        for comp in data["competitors"]:
            assert "research_depth" in comp, f"Missing research_depth in {comp['slug']}"
            assert "evidence_source" in comp, f"Missing evidence_source in {comp['slug']}"
            assert "sourced_fields_count" in comp, f"Missing sourced_fields_count in {comp['slug']}"
        # Check specific values
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["research_depth"] == "full"
        assert alpha["sourced_fields_count"] == 5
        assert alpha["evidence_source"]["description"] == "researched"

    # 10. _startup slug rejected
    def test_startup_slug_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["slug"] = "_startup"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 10b. Invalid research_depth enum value fails
    def test_invalid_research_depth_fails(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["research_depth"] = "high"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "research_depth" in stderr
        assert "high" in stderr

    # 10c. underscore slugs auto-converted to kebab-case
    def test_underscore_slug_auto_converted(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["slug"] = "manual_campaigns"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0 (auto-convert), got {rc}. stderr: {stderr}"
        assert data is not None
        slugs = [c["slug"] for c in data["competitors"]]
        assert "manual-campaigns" in slugs, f"Expected auto-converted slug, got: {slugs}"
        assert "manual_campaigns" not in slugs
        assert "auto-converted" in stderr.lower()

    # 10d. empty slug rejected
    def test_empty_slug_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["slug"] = ""
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "non-empty" in stderr.lower()

    # 10e. Known near-miss field alias 'key_differentiators_per_deck' is auto-normalized to
    # 'key_differentiators' (same auto-fix pattern as the underscore-slug conversion above) —
    # an observed sub-agent near-miss, rather than a hard failure forcing a repair round-trip.
    def test_key_differentiators_per_deck_alias_auto_normalized(self) -> None:
        payload = _make_valid_landscape()
        comp = payload["competitors"][0]
        comp["key_differentiators_per_deck"] = comp.pop("key_differentiators")
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0 (auto-normalize), got {rc}. stderr: {stderr}"
        assert data is not None
        fixed = data["competitors"][0]
        assert "key_differentiators" in fixed
        assert "key_differentiators_per_deck" not in fixed
        assert "auto-converted" in stderr.lower() or "normalized" in stderr.lower()

    # 10f. When BOTH the canonical field and the alias are present, canonical wins and no
    # silent data loss occurs — the alias is simply dropped (not merged/overwritten).
    def test_key_differentiators_per_deck_alias_ignored_when_canonical_present(self) -> None:
        payload = _make_valid_landscape()
        comp = payload["competitors"][0]
        comp["key_differentiators_per_deck"] = ["Alias value"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        fixed = data["competitors"][0]
        assert fixed["key_differentiators"] == comp["key_differentiators"]

    # 10f-2. When both keys are present the alias is dropped, but NOT silently — a stderr
    # note must record the drop (gap-detection knowledge shouldn't vanish without a trace).
    def test_key_differentiators_per_deck_both_present_notes_drop(self) -> None:
        payload = _make_valid_landscape()
        comp = payload["competitors"][0]
        comp["key_differentiators_per_deck"] = ["Alias value"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert "key_differentiators_per_deck" in stderr, (
            f"dropping the alias when canonical is present must emit a stderr note: {stderr!r}"
        )

    # 10g. A "researched" per-field evidence_source with no matching "sources" citation
    # warns (verifiability gap) — mirrors score_moats.py's RESEARCHED_WITHOUT_SOURCE.
    def test_researched_field_without_source_warns(self) -> None:
        payload = _make_valid_landscape()
        # _make_competitor's default evidence_source has "description" and "pricing_model"
        # both "researched", with no "sources" dict at all.
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0 (warn, not fail), got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "RESEARCHED_WITHOUT_SOURCE")
        assert warn["severity"] == "medium"
        assert "alpha-corp" in warn["message"]

    # 10h. A "researched" field WITH a matching "sources" entry does not warn for that field,
    # and "sources" is passed through into the output competitor.
    def test_researched_field_with_source_no_warning_and_passthrough(self) -> None:
        payload = _make_valid_landscape()
        for comp in payload["competitors"]:
            comp["sources"] = {k: "https://example.com/q" for k in comp["evidence_source"]}
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" not in codes
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["sources"]["description"] == "https://example.com/q"

    # 10i. agent_estimate fields are exempt — no source expected.
    def test_agent_estimate_field_without_source_does_not_warn(self) -> None:
        payload = _make_valid_landscape()
        for comp in payload["competitors"]:
            comp["evidence_source"] = {k: "agent_estimate" for k in comp["evidence_source"]}
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" not in codes

    # 11. data_confidence passthrough
    def test_data_confidence_passthrough(self) -> None:
        payload = _make_valid_landscape(data_confidence=0.85)
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("data_confidence") == 0.85

    # 12. --pretty flag produces indented JSON
    def test_pretty_flag(self) -> None:
        payload = _make_valid_landscape()
        rc, raw_stdout, stderr = run_script_raw(
            "validate_landscape.py",
            args=["--pretty"],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        # Pretty-printed JSON contains newlines and indentation
        assert "\n " in raw_stdout
        # Should still be valid JSON
        data = json.loads(raw_stdout)
        assert "competitors" in data

    # 13. -o writes to file, receipt JSON to stdout
    def test_output_file(self) -> None:
        payload = _make_valid_landscape()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            rc, data, stderr = run_script(
                "validate_landscape.py",
                args=["-o", tmp_path],
                stdin_data=json.dumps(payload),
            )
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            # stdout should be a receipt
            assert data is not None
            assert data["ok"] is True
            assert data["path"] == os.path.abspath(tmp_path)
            assert "bytes" in data
            # File should contain the full landscape JSON
            with open(tmp_path, encoding="utf-8") as f:
                file_data = json.load(f)
            assert "competitors" in file_data
            assert len(file_data["competitors"]) == 5
        finally:
            os.unlink(tmp_path)


class TestValidateLandscapeKeyDifferentiators:
    """key_differentiators emptiness is only valid for a competitor with
    research_depth 'partial' (the promoted-but-not-yet-enriched case). Any other
    research_depth claims complete research, so an empty list there is an error."""

    def test_empty_key_differentiators_valid_when_research_depth_partial(self) -> None:
        payload = _make_valid_landscape()
        comp = payload["competitors"][0]
        comp["key_differentiators"] = []
        comp["research_depth"] = "partial"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0 for empty key_differentiators + partial, got {rc}. stderr: {stderr}"
        assert data is not None
        fixed = next(c for c in data["competitors"] if c["slug"] == comp["slug"])
        assert fixed["key_differentiators"] == []

    def test_empty_key_differentiators_invalid_when_research_depth_full(self) -> None:
        payload = _make_valid_landscape()
        comp = payload["competitors"][0]
        comp["key_differentiators"] = []
        comp["research_depth"] = "full"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for empty key_differentiators + full, got {rc}. stderr: {stderr}"
        assert "partial" in stderr.lower()

    def test_key_differentiators_absent_still_fails(self) -> None:
        payload = _make_valid_landscape()
        del payload["competitors"][0]["key_differentiators"]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 when key_differentiators is absent entirely, got {rc}. stderr: {stderr}"

    def test_non_empty_key_differentiators_valid_at_any_research_depth(self) -> None:
        for depth in ("full", "partial", "founder_provided"):
            payload = _make_valid_landscape()
            comp = payload["competitors"][0]
            comp["key_differentiators"] = ["A real, sourced differentiator"]
            comp["research_depth"] = depth
            rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
            assert rc == 0, (
                f"depth={depth}: expected exit 0 for non-empty key_differentiators, got {rc}. stderr: {stderr}"
            )


class TestValidateLandscapeSuggestedAdditions:
    """A declined suggested_addition (merged: false) must survive into
    landscape.json — otherwise the coaching commentary can never cite a
    declined suggestion, because it was never persisted."""

    def test_declined_suggested_addition_survives_with_merged_false(self) -> None:
        payload = _make_valid_landscape()
        payload["suggested_additions"] = [
            {
                "name": "Omega Analytics",
                "slug": "omega-analytics",
                "category": "adjacent",
                "rationale": "Found via research; founder declined to add it to the formal set.",
                "merged": False,
            }
        ]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "suggested_additions" in data, "declined suggested_additions must survive into landscape.json"
        assert data["suggested_additions"] == payload["suggested_additions"]
        assert data["suggested_additions"][0]["merged"] is False

    def test_suggested_additions_absent_when_not_in_input(self) -> None:
        payload = _make_valid_landscape()
        assert "suggested_additions" not in payload
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "suggested_additions" not in data, (
            "suggested_additions must not be fabricated in the output when the input never had it"
        )


class TestValidateLandscapeDeferredRecallCandidates:
    """deferred_recall_candidates is an optional top-level passthrough. The
    output dict is an explicit allowlist, so this must be added by name or it
    silently vanishes; it must never be fabricated when absent."""

    def test_deferred_recall_candidates_round_trips_when_present(self) -> None:
        payload = _make_valid_landscape()
        payload["deferred_recall_candidates"] = [
            {
                "name": "Nomad Thermal",
                "slug": "nomad-thermal",
                "category": "adjacent",
                "why_considered": "Recalled from prior research but not re-verified this run.",
                "sources": ["https://example.com/nomad-thermal"],
            }
        ]
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "deferred_recall_candidates" in data
        assert data["deferred_recall_candidates"] == payload["deferred_recall_candidates"]

    def test_deferred_recall_candidates_absent_when_not_in_input(self) -> None:
        payload = _make_valid_landscape()
        assert "deferred_recall_candidates" not in payload
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # The key is ALWAYS written, `[]` when the input had none — that is what makes absence
        # discriminating for the delivery gate (no key = an artifact predating this producer;
        # empty key = this producer ran and found none). What must never happen is a FABRICATED
        # entry, which is what this test now guards.
        assert data["deferred_recall_candidates"] == [], (
            "an input with no deferred candidates must yield an empty list, never invented entries"
        )

    def test_deferred_recall_candidates_non_list_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["deferred_recall_candidates"] = "Nomad Thermal"
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "deferred_recall_candidates" in stderr.lower()
        assert "array" in stderr.lower()


# ---------------------------------------------------------------------------
# recent_developments[] + --as-of / landscape_as_of tests
#
# All tests pin the clock via --as-of / the `as_of` factory kwarg so the
# recency window doesn't drift with wall-clock time and age fixtures out.
# Fixed reference date: 2026-06-15. Recency window is 18 months, so
# window_start = 2024-12-15 (month-granularity floor: 2024-12).
# ---------------------------------------------------------------------------

AS_OF = "2026-06-15"


def _make_landscape_with_dev(
    recent_developments: list[dict[str, Any]] | None,
    *,
    other_competitors_dev: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a valid landscape_enriched.json where competitor[0] carries the
    given recent_developments (None means the key is entirely absent) and the
    rest carry `other_competitors_dev` (default: none)."""
    comps = [
        _make_competitor("Alpha Corp", "alpha-corp", "direct", recent_developments=recent_developments),
        _make_competitor("Beta Inc", "beta-inc", "direct", recent_developments=other_competitors_dev),
        _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent", recent_developments=other_competitors_dev),
        _make_competitor("Delta Co", "delta-co", "emerging", recent_developments=other_competitors_dev),
        _make_competitor("Manual Process", "manual-process", "do_nothing", recent_developments=other_competitors_dev),
    ]
    return _make_valid_landscape(competitors=comps)


class TestValidateLandscapeRecentDevelopments:
    """recent_developments[] is optional per-competitor structured data for
    dated, sourced signals (funding, launches, leadership moves, etc.). The
    validation rules exist to stop fabrication of a temporal claim."""

    # --- date format acceptance ---------------------------------------

    def test_date_format_yyyy_mm_accepted(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="2026-03")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["recent_developments"][0]["date"] == "2026-03"

    def test_date_format_yyyy_mm_dd_accepted(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="2026-03-15")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None

    # --- date format rejection ------------------------------------------

    def test_date_format_quarter_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="Q1 2026")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "date" in stderr.lower()

    def test_date_format_free_text_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="last spring")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    def test_date_format_year_only_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="2026")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # --- future / out-of-window ------------------------------------------

    def test_future_date_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="2026-07")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "future" in stderr.lower()

    def test_future_full_date_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(date="2026-06-16")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "future" in stderr.lower()

    def test_out_of_window_date_dropped_with_warning(self) -> None:
        """The 18-month recency window is editorial freshness, not an
        integrity guard: an out-of-window entry must not fail the whole
        payload. It is relocated to out_of_window_developments and raises a
        medium STALE_DEVELOPMENT warning instead — nothing is silently lost."""
        # window_start (month granularity) = 2024-12; 2024-11 is one month too old.
        payload = _make_landscape_with_dev([_make_recent_development(date="2024-11", summary="Raised a Series B.")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["recent_developments"] == [], "the out-of-window entry must be gone from recent_developments"
        assert "out_of_window_developments" in alpha
        assert len(alpha["out_of_window_developments"]) == 1
        moved = alpha["out_of_window_developments"][0]
        assert moved["date"] == "2024-11"
        assert moved["summary"] == "Raised a Series B."
        codes = [w["code"] for w in data["warnings"]]
        assert "STALE_DEVELOPMENT" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "STALE_DEVELOPMENT")
        assert warn["severity"] == "medium"
        # The message is rendered into report.md's warning list, so it must read as prose to a
        # founder: the competitor's DISPLAY NAME, not its slug, and no internal field names. A
        # snake_case key in the deliverable is the same leak class as a slug in a heading.
        assert "Alpha Corp" in warn["message"], "the warning must name the competitor, not its slug"
        assert "alpha-corp" not in warn["message"]
        for internal in ("recent_developments", "out_of_window_developments"):
            assert internal not in warn["message"], (
                f"the founder-facing warning message leaks the internal field name {internal!r}"
            )
        assert "2024-11" in warn["message"]
        assert "Raised a Series B." in warn["message"]

    def test_out_of_window_entry_with_non_url_source_still_rejected(self) -> None:
        """Relocation is not an exemption from the other guards: an
        out-of-window entry with a non-URL source must still fail the whole
        payload, not be silently relocated with unverifiable content."""
        payload = _make_landscape_with_dev(
            [_make_recent_development(date="2024-11", source="saw it on their blog, no link")]
        )
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "source" in stderr.lower()
        assert "url" in stderr.lower()

    def test_out_of_window_entry_with_bad_type_still_rejected(self) -> None:
        """Same guard-still-applies property as the non-URL-source case, for
        the 'type' enum."""
        payload = _make_landscape_with_dev([_make_recent_development(date="2024-11", dev_type="rumor")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "type" in stderr.lower()

    def test_multiple_out_of_window_entries_each_get_own_warning(self) -> None:
        payload = _make_landscape_with_dev(
            [
                _make_recent_development(date="2024-11", summary="First stale event."),
                _make_recent_development(date="2024-10", summary="Second stale event."),
            ]
        )
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["recent_developments"] == []
        assert len(alpha["out_of_window_developments"]) == 2
        stale_warnings = [w for w in data["warnings"] if w["code"] == "STALE_DEVELOPMENT"]
        assert len(stale_warnings) == 2

    def test_competitor_with_only_out_of_window_developments_does_not_trip_no_recent_developments(self) -> None:
        """A landscape whose only development for EVERY competitor is
        out-of-window must not newly trip NO_RECENT_DEVELOPMENTS: the research
        happened, it just aged out of the render window. has_recent_developments
        must be computed BEFORE the drop, not after."""
        stale_dev = [_make_recent_development(date="2024-11")]
        payload = _make_landscape_with_dev(stale_dev, other_competitors_dev=stale_dev)
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "NO_RECENT_DEVELOPMENTS" not in codes, (
            "an all-out-of-window landscape still proves research happened; must not be mistaken for shallow research"
        )
        # And the drop itself did still happen for every competitor.
        for comp in data["competitors"]:
            assert comp["recent_developments"] == []
            assert len(comp.get("out_of_window_developments", [])) == 1

    def test_within_window_boundary_accepted(self) -> None:
        # Exactly at the 18-month floor should be accepted (not strictly less-than).
        payload = _make_landscape_with_dev([_make_recent_development(date="2024-12")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"

    # --- source URL requirement -------------------------------------------

    def test_non_url_source_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(source="saw it on their blog, no link")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "source" in stderr.lower()
        assert "url" in stderr.lower()

    def test_empty_source_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(source="")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    def test_search_query_source_rejected_unlike_moat_source(self) -> None:
        """Unlike moat 'source' (which may be a search query), a dated factual
        claim about a named company must be spot-checkable — URL required."""
        payload = _make_landscape_with_dev([_make_recent_development(source="competitor pricing changes 2026")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # --- type enum ----------------------------------------------------------

    def test_bad_type_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(dev_type="rumor")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "type" in stderr.lower()

    def test_all_seven_types_accepted(self) -> None:
        for t in (
            "funding",
            "pricing_change",
            "product_launch",
            "market_move",
            "acquisition",
            "leadership",
            "layoff",
        ):
            payload = _make_landscape_with_dev([_make_recent_development(dev_type=t)])
            rc, data, stderr = run_script(
                "validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload)
            )
            assert rc == 0, f"type={t}: expected exit 0, got {rc}. stderr: {stderr}"

    # --- summary required ----------------------------------------------------

    def test_empty_summary_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development(summary="")])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # --- agent_estimate rejection ---------------------------------------------

    def test_agent_estimate_evidence_source_rejected(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development()])
        payload["competitors"][0]["evidence_source"]["recent_developments"] = "agent_estimate"
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "agent_estimate" in stderr.lower()

    def test_researched_evidence_source_does_not_reject(self) -> None:
        payload = _make_landscape_with_dev([_make_recent_development()])
        payload["competitors"][0]["evidence_source"]["recent_developments"] = "researched"
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"

    # --- absent / empty are both valid, silently -----------------------------

    def test_field_absent_is_valid_no_per_competitor_warning(self) -> None:
        payload = _make_landscape_with_dev(None, other_competitors_dev=[_make_recent_development()])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert "recent_developments" not in alpha
        # Other competitors have entries, so the whole-set NO_RECENT_DEVELOPMENTS
        # warning must not fire, and there must be no per-competitor warning
        # about alpha-corp's recent_developments specifically (a mention of
        # "recent_developments" naming alpha-corp) for having none.
        codes = [w["code"] for w in data["warnings"]]
        assert "NO_RECENT_DEVELOPMENTS" not in codes
        assert not any(
            "alpha-corp" in w.get("message", "") and "recent_developments" in w.get("message", "")
            for w in data["warnings"]
        )

    def test_field_empty_list_is_valid(self) -> None:
        payload = _make_landscape_with_dev([], other_competitors_dev=[_make_recent_development()])
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        alpha = next(c for c in data["competitors"] if c["slug"] == "alpha-corp")
        assert alpha["recent_developments"] == []

    def test_not_a_list_rejected(self) -> None:
        payload = _make_valid_landscape()
        payload["competitors"][0]["recent_developments"] = "funding round in March"
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "array" in stderr.lower()

    # --- NO_RECENT_DEVELOPMENTS whole-set warning ------------------------------

    def test_no_recent_developments_warns_when_all_empty(self) -> None:
        payload = _make_valid_landscape()  # none of _make_valid_landscape's competitors set it
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "NO_RECENT_DEVELOPMENTS" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "NO_RECENT_DEVELOPMENTS")
        assert warn["severity"] == "medium"

    def test_no_recent_developments_does_not_warn_when_one_has_entries(self) -> None:
        """One quiet competitor among several researched ones is a correct
        answer and must NOT trigger the whole-set warning."""
        payload = _make_landscape_with_dev([_make_recent_development()], other_competitors_dev=None)
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "NO_RECENT_DEVELOPMENTS" not in codes

    # --- landscape_as_of stamp + --as-of --------------------------------------

    def test_landscape_as_of_present_and_honors_as_of_flag(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", args=["--as-of", AS_OF], stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["landscape_as_of"] == AS_OF

    def test_landscape_as_of_defaults_to_today_when_omitted(self) -> None:
        import datetime as _dt

        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["landscape_as_of"] == _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    def test_bad_as_of_flag_rejected(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script(
            "validate_landscape.py", args=["--as-of", "not-a-date"], stdin_data=json.dumps(payload)
        )
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"


# ---------------------------------------------------------------------------
# Factory: verdicts input for verify_competitors.py
# ---------------------------------------------------------------------------


def _make_verdict_entry(
    slug: str,
    verdict: str,
    recommended_action: str,
    *,
    buyer: str = "Head of Platform Engineering",
    job_to_be_done: str = "Secure production APIs against abuse",
    evidence_source: str = "researched",
) -> dict[str, Any]:
    """Build one verify_competitors.py verdict entry, including the
    show-your-work fields a non-genuine verdict requires."""
    return {
        "slug": slug,
        "verdict": verdict,
        "recommended_action": recommended_action,
        "reasoning": (
            "Independent re-characterization found a materially different overlap "
            "profile than the draft category assumed."
        ),
        "independent_characterization": {
            "buyer": buyer,
            "job_to_be_done": job_to_be_done,
            "evidence_source": evidence_source,
        },
    }


def _run_verify_competitors(
    verdicts: list[dict[str, Any]],
    landscape_categories: dict[str, str],
    *,
    run_id: str = "20260319T143045Z",
) -> tuple[int, dict[str, Any] | None, str]:
    """Run verify_competitors.py with a --landscape file built from
    {slug: category} so category_disagreements has a draft category to
    compare each verdict against."""
    payload = {
        "verdicts": verdicts,
        "startup_characterization": {
            "buyer": "Head of Platform Engineering",
            "job_to_be_done": "Secure production APIs against abuse",
        },
        "metadata": {"run_id": run_id},
    }
    landscape_competitors = [{"slug": slug, "category": category} for slug, category in landscape_categories.items()]
    with tempfile.TemporaryDirectory() as d:
        land_path = os.path.join(d, "landscape_draft.json")
        with open(land_path, "w") as f:
            json.dump({"competitors": landscape_competitors}, f)
        return run_script(
            "verify_competitors.py",
            args=["--landscape", land_path],
            stdin_data=json.dumps(payload),
        )


# ===========================================================================
# verify_competitors.py tests — category_disagreements (upgrade/downgrade)
# ===========================================================================


class TestVerifyCompetitorsCategoryDisagreements:
    """summary.category_disagreements must surface BOTH directions: a verdict
    stronger than the draft category (upgrade — cuts against the startup) and
    a verdict weaker than the draft category (downgrade). do_nothing/emerging
    encode market role, not degree of overlap, so they must never produce a
    disagreement; custom is caller-defined and must be excluded too."""

    def test_genuine_verdict_on_adjacent_draft_flags_upgrade(self) -> None:
        verdicts = [_make_verdict_entry("acme", "genuine", "reclassify_direct")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "adjacent"})
        assert rc == 0, stderr
        assert data is not None
        assert data["summary"]["category_disagreements"] == [
            {"slug": "acme", "draft_category": "adjacent", "verdict": "genuine", "direction": "upgrade"}
        ]

    def test_adjacent_verdict_on_direct_draft_flags_downgrade(self) -> None:
        verdicts = [_make_verdict_entry("acme", "adjacent", "reclassify_adjacent")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "direct"})
        assert rc == 0, stderr
        assert data is not None
        assert data["summary"]["category_disagreements"] == [
            {"slug": "acme", "draft_category": "direct", "verdict": "adjacent", "direction": "downgrade"}
        ]

    def test_genuine_verdict_on_do_nothing_draft_produces_no_disagreement(self) -> None:
        """do_nothing encodes market role, not overlap degree — a correct genuine
        verdict on a draft-do_nothing entry must not be flagged as a mischaracterization."""
        verdicts = [_make_verdict_entry("acme", "genuine", "keep")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "do_nothing"})
        assert rc == 0, stderr
        assert data is not None
        assert data["summary"]["category_disagreements"] == []

    def test_adjacent_verdict_on_emerging_draft_produces_no_disagreement(self) -> None:
        """emerging encodes convergence risk, not overlap degree — a correct adjacent
        verdict on a draft-emerging entry must not be flagged."""
        verdicts = [_make_verdict_entry("acme", "adjacent", "reclassify_adjacent")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "emerging"})
        assert rc == 0, stderr
        assert data is not None
        assert data["summary"]["category_disagreements"] == []

    def test_custom_draft_category_never_produces_a_disagreement(self) -> None:
        """custom's semantics are caller-defined — no fixed verdict is 'expected'."""
        verdicts = [_make_verdict_entry("acme", "genuine", "reclassify_direct")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "custom"})
        assert rc == 0, stderr
        assert data is not None
        assert data["summary"]["category_disagreements"] == []

    def test_flagged_slugs_semantics_unchanged_by_category_disagreements(self) -> None:
        """flagged / flagged_slugs stay keyed on verdict != genuine only — an
        upgrade (verdict genuine) must never appear there even though it's a
        disagreement, and a downgrade (verdict != genuine) must still appear."""
        verdicts = [
            _make_verdict_entry("acme", "genuine", "reclassify_direct"),  # upgrade, verdict==genuine
            _make_verdict_entry("beta", "adjacent", "reclassify_adjacent"),  # downgrade, verdict!=genuine
        ]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "adjacent", "beta": "direct"})
        assert rc == 0, stderr
        assert data is not None
        summary = data["summary"]
        assert "acme" not in summary["flagged_slugs"], "an upgrade (verdict genuine) must not be flagged"
        assert "beta" in summary["flagged_slugs"], "a downgrade (verdict != genuine) must still be flagged"
        assert summary["flagged"] == 1
        assert len(summary["category_disagreements"]) == 2

    def test_reclassify_direct_is_an_accepted_recommended_action(self) -> None:
        """reclassify_direct is the natural action for an upgrade — the producer
        must accept it, not just the pre-existing reclassify_adjacent."""
        verdicts = [_make_verdict_entry("acme", "genuine", "reclassify_direct")]
        rc, data, stderr = _run_verify_competitors(verdicts, {"acme": "adjacent"})
        assert rc == 0, f"reclassify_direct must be an accepted recommended_action: {stderr}"
        assert data is not None
        assert data["validation"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Factory: valid moat_assessments input for score_moats.py
# ---------------------------------------------------------------------------

CANONICAL_MOAT_IDS = [
    "network_effects",
    "data_advantages",
    "switching_costs",
    "regulatory_barriers",
    "cost_structure",
    "brand_reputation",
]


def _make_moat_entry(
    moat_id: str,
    *,
    status: str = "moderate",
    evidence: str = "Sufficient evidence for this moat dimension assessment.",
    evidence_source: str = "researched",
    trajectory: str = "stable",
) -> dict[str, Any]:
    """Build a single moat entry."""
    return {
        "id": moat_id,
        "status": status,
        "evidence": evidence,
        "evidence_source": evidence_source,
        "trajectory": trajectory,
    }


def _make_company_moats(
    *,
    statuses: dict[str, str] | None = None,
    extra_moats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a moats object for one company."""
    statuses = statuses or {}
    moats = []
    for mid in CANONICAL_MOAT_IDS:
        moats.append(_make_moat_entry(mid, status=statuses.get(mid, "moderate")))
    if extra_moats:
        moats.extend(extra_moats)
    return {"moats": moats}


def _make_valid_moat_input(
    *,
    startup_statuses: dict[str, str] | None = None,
    competitor_statuses: dict[str, str] | None = None,
    extra_startup_moats: list[dict[str, Any]] | None = None,
    data_confidence: str | None = None,
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a valid score_moats.py input with _startup + 1 competitor."""
    result: dict[str, Any] = {
        "moat_assessments": {
            "_startup": _make_company_moats(statuses=startup_statuses, extra_moats=extra_startup_moats),
            "acme-corp": _make_company_moats(statuses=competitor_statuses),
        },
        "metadata": {"run_id": run_id},
    }
    if data_confidence is not None:
        result["data_confidence"] = data_confidence
    return result


# ===========================================================================
# score_moats.py tests
# ===========================================================================


class TestScoreMoats:
    """Tests for score_moats.py."""

    # 1. Well-formed input passes
    def test_score_moats_valid_passes(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "companies" in data
        assert "_startup" in data["companies"]
        assert "acme-corp" in data["companies"]
        assert "comparison" in data
        assert "warnings" in data
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        # Each company should have moats + aggregates
        for slug in ("_startup", "acme-corp"):
            co = data["companies"][slug]
            assert "moats" in co
            assert "moat_count" in co
            assert "strongest_moat" in co
            assert "overall_defensibility" in co

    # 2. Custom moat accepted
    def test_score_moats_custom_moat_accepted(self) -> None:
        custom = _make_moat_entry("custom_ip_patents", status="strong")
        payload = _make_valid_moat_input(extra_startup_moats=[custom])
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        startup_ids = [m["id"] for m in data["companies"]["_startup"]["moats"]]
        assert "custom_ip_patents" in startup_ids

    # 2b. founder_provided evidence_source accepted (CP-1)
    def test_score_moats_accepts_founder_provided_evidence(self) -> None:
        """CP-1: 'founder_provided' — the provenance vocabulary the methodology reference and
        startup_characterization use — must be accepted by the moat producer, not rejected as
        invalid. It is distinct from 'founder_override' (a coordinate/rating override counted
        separately in compose). The observed Gen-2 failure was a wasted repair dispatch when the
        sub-agent stamped a founder-stated moat 'founder_provided' and the producer rejected it."""
        entry = _make_moat_entry("custom_founder_stated", status="moderate", evidence_source="founder_provided")
        payload = _make_valid_moat_input(extra_startup_moats=[entry])
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"founder_provided must be accepted. stderr: {stderr}"
        assert data is not None
        ids = [m["id"] for m in data["companies"]["_startup"]["moats"]]
        assert "custom_founder_stated" in ids

    # 3. Missing canonical moat produces warning
    def test_score_moats_missing_canonical_warns(self) -> None:
        payload = _make_valid_moat_input()
        # Remove one canonical moat from _startup
        payload["moat_assessments"]["_startup"]["moats"] = [
            m for m in payload["moat_assessments"]["_startup"]["moats"] if m["id"] != "brand_reputation"
        ]
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MISSING_CANONICAL_MOAT" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MISSING_CANONICAL_MOAT")
        assert "_startup" in warn["message"]
        assert "brand_reputation" in warn["message"]

    # 4. Strong without evidence warns
    def test_score_moats_strong_without_evidence_warns(self) -> None:
        payload = _make_valid_moat_input(startup_statuses={"network_effects": "strong"})
        # Shorten the evidence for the strong moat
        for m in payload["moat_assessments"]["_startup"]["moats"]:
            if m["id"] == "network_effects":
                m["evidence"] = "Short."
                break
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "MOAT_WITHOUT_EVIDENCE" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "MOAT_WITHOUT_EVIDENCE")
        assert warn["severity"] == "medium"
        assert "_startup" in warn.get("company", "")

    # 4b. "researched" evidence_source with no source citation warns (unverifiable claim gap) —
    # a dated real-world claim (funding round, M&A, exec change) stamped "researched" needs a
    # URL or search query beside it so the main thread can spot-check it later.
    def test_score_moats_researched_without_source_warns(self) -> None:
        payload = _make_valid_moat_input()
        for m in payload["moat_assessments"]["_startup"]["moats"]:
            if m["id"] == "network_effects":
                m["evidence_source"] = "researched"
                m.pop("source", None)
                break
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0 (warn, not fail), got {rc}. stderr: {stderr}"
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" in codes
        warn = next(w for w in data["warnings"] if w["code"] == "RESEARCHED_WITHOUT_SOURCE")
        assert warn["severity"] == "medium"
        assert warn.get("company") == "_startup"
        assert warn.get("moat_id") == "network_effects"

    # 4c. Empty-string source is treated the same as missing (still warns).
    def test_score_moats_researched_with_blank_source_warns(self) -> None:
        payload = _make_valid_moat_input()
        for m in payload["moat_assessments"]["_startup"]["moats"]:
            if m["id"] == "network_effects":
                m["evidence_source"] = "researched"
                m["source"] = "   "
                break
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" in codes

    # 4d. A "researched" moat WITH a source citation does not warn, and the source is
    # passed through into the output artifact.
    def test_score_moats_researched_with_source_no_warning_and_passthrough(self) -> None:
        payload = _make_valid_moat_input()
        # Every moat across both companies defaults to evidence_source="researched" (see
        # _make_moat_entry) — give them all a source, then check the one under test passes
        # through, and confirm no RESEARCHED_WITHOUT_SOURCE leaks from the rest of the fixture.
        for company in payload["moat_assessments"].values():
            for m in company["moats"]:
                m["source"] = "https://example.com/generic-source"
        for m in payload["moat_assessments"]["_startup"]["moats"]:
            if m["id"] == "network_effects":
                m["evidence_source"] = "researched"
                m["source"] = "https://example.com/press-release"
                break
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" not in codes
        out_moat = next(m for m in data["companies"]["_startup"]["moats"] if m["id"] == "network_effects")
        assert out_moat["source"] == "https://example.com/press-release"

    # 4e. agent_estimate / founder_override moats are exempt — no source expected.
    def test_score_moats_non_researched_no_source_does_not_warn(self) -> None:
        payload = _make_valid_moat_input()
        for company in payload["moat_assessments"].values():
            for m in company["moats"]:
                m["evidence_source"] = "agent_estimate"
                m.pop("source", None)
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RESEARCHED_WITHOUT_SOURCE" not in codes

    # 5. Per-company aggregates
    def test_score_moats_per_company_aggregates(self) -> None:
        payload = _make_valid_moat_input(
            startup_statuses={
                "network_effects": "strong",
                "data_advantages": "strong",
                "switching_costs": "moderate",
                "regulatory_barriers": "absent",
                "cost_structure": "not_applicable",
                "brand_reputation": "weak",
            }
        )
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        startup = data["companies"]["_startup"]
        # moat_count: non-absent, non-na => strong(2) + moderate(1) + weak(1) = 4
        assert startup["moat_count"] == 4
        assert startup["strongest_moat"] == "network_effects"
        assert startup["overall_defensibility"] == "high"  # 2+ strong

    # 6. Comparison section present
    def test_score_moats_comparison_section(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        comp = data["comparison"]
        assert "by_dimension" in comp
        assert "startup_rank" in comp
        # Each canonical moat should be in by_dimension
        for mid in CANONICAL_MOAT_IDS:
            assert mid in comp["by_dimension"], f"Missing {mid} in by_dimension"
            assert "_startup" in comp["by_dimension"][mid]
            assert "acme-corp" in comp["by_dimension"][mid]
        # startup_rank should have entries for canonical moats
        for mid in CANONICAL_MOAT_IDS:
            assert mid in comp["startup_rank"], f"Missing {mid} in startup_rank"
            rank_info = comp["startup_rank"][mid]
            assert "rank" in rank_info
            assert "total" in rank_info

    # 7. _startup key processed correctly
    def test_score_moats_startup_included(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "_startup" in data["companies"]
        startup = data["companies"]["_startup"]
        assert len(startup["moats"]) == 6

    # 8. Data confidence qualifier
    def test_score_moats_data_confidence_qualifier(self) -> None:
        payload = _make_valid_moat_input(data_confidence="estimated")
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # Evidence strings should be qualified
        for m in data["companies"]["_startup"]["moats"]:
            assert "(based on estimated inputs)" in m["evidence"]

    # 9. Invalid trajectory fails
    def test_score_moats_invalid_trajectory_fails(self) -> None:
        payload = _make_valid_moat_input()
        payload["moat_assessments"]["_startup"]["moats"][0]["trajectory"] = "declining"
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 9b. Invalid trajectory error message lists the allowed values — a real observed near-miss
    # was a sub-agent stamping trajectory:"absent" (a moat *status* value, not a trajectory).
    # The repair-dispatch loop feeds this stderr back to the sub-agent verbatim, so the allowed
    # set needs to be IN the message, not just in a resolver step the model has to search for.
    def test_score_moats_invalid_trajectory_error_lists_allowed_values(self) -> None:
        payload = _make_valid_moat_input()
        payload["moat_assessments"]["_startup"]["moats"][0]["trajectory"] = "absent"
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        for allowed in ("building", "stable", "eroding"):
            assert allowed in stderr, f"allowed trajectory value '{allowed}' not in error message: {stderr}"

    # 9b-2. The trajectory error must not MISLABEL the trajectory enum as a "moat status" set
    # (it lists building/stable/eroding — those are trajectories, not statuses). The message
    # should identify it as the trajectory enum and point 'absent'-type values to the status field.
    def test_score_moats_invalid_trajectory_error_not_mislabeled(self) -> None:
        payload = _make_valid_moat_input()
        payload["moat_assessments"]["_startup"]["moats"][0]["trajectory"] = "absent"
        rc, _data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, stderr
        low = stderr.lower()
        assert "trajectory enum" in low or "not the moat status" in low or "not a moat status" in low, (
            f"trajectory error must not mislabel the enum as a moat status set: {stderr!r}"
        )

    # 9c. Invalid status error message likewise lists the allowed values.
    def test_score_moats_invalid_status_error_lists_allowed_values(self) -> None:
        payload = _make_valid_moat_input()
        payload["moat_assessments"]["_startup"]["moats"][0]["status"] = "nonexistent"
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        for allowed in ("strong", "moderate", "weak", "absent", "not_applicable"):
            assert allowed in stderr, f"allowed status value '{allowed}' not in error message: {stderr}"

    # 10. Array-of-objects moat_assessments is normalized to dict-keyed format
    def test_score_moats_array_format_normalized(self) -> None:
        """Array-of-objects moat_assessments is normalized to dict-keyed format."""
        payload = _make_valid_moat_input()
        dict_assessments = payload["moat_assessments"]
        expected_slugs = set(dict_assessments.keys())
        array_assessments = []
        for slug, company_data in dict_assessments.items():
            entry = {"slug": slug}
            entry.update(company_data)
            array_assessments.append(entry)
        payload["moat_assessments"] = array_assessments

        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert set(data["companies"].keys()) == expected_slugs
        assert "normalized" in stderr.lower()

    # 11. Array entry without 'slug' key produces an error, not silent drop
    def test_score_moats_array_missing_slug_errors(self) -> None:
        """Array entry without 'slug' key produces an error, not silent drop."""
        payload = _make_valid_moat_input()
        dict_assessments = payload["moat_assessments"]
        array_assessments = []
        for slug, company_data in dict_assessments.items():
            entry = {"slug": slug}
            entry.update(company_data)
            array_assessments.append(entry)
        array_assessments.append({"moats": []})
        payload["moat_assessments"] = array_assessments

        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for malformed entry, got {rc}. stderr: {stderr}"
        assert "slug" in stderr.lower()

    # 12. Non-string slug values in array format produce an error
    def test_score_moats_array_non_string_slug_errors(self) -> None:
        """Non-string slug values in array format produce an error."""
        payload = _make_valid_moat_input()
        dict_assessments = payload["moat_assessments"]
        array_assessments = []
        for slug, company_data in dict_assessments.items():
            entry = {"slug": slug}
            entry.update(company_data)
            array_assessments.append(entry)
        array_assessments[0]["slug"] = 123
        payload["moat_assessments"] = array_assessments

        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for non-string slug, got {rc}. stderr: {stderr}"
        assert "non-empty string" in stderr.lower() or "int" in stderr.lower()

    # 13. Duplicate slugs in array format produce an error
    def test_score_moats_array_duplicate_slug_errors(self) -> None:
        """Duplicate slugs in array format produce an error."""
        payload = _make_valid_moat_input()
        dict_assessments = payload["moat_assessments"]
        array_assessments = []
        for slug, company_data in dict_assessments.items():
            entry = {"slug": slug}
            entry.update(company_data)
            array_assessments.append(entry)
        array_assessments.append(array_assessments[0].copy())
        payload["moat_assessments"] = array_assessments

        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for duplicate slug, got {rc}. stderr: {stderr}"
        assert "duplicate" in stderr.lower()

    # 14. Error message for invalid moat_assessments hints at expected format
    def test_score_moats_error_shows_expected_shape(self) -> None:
        """Error message for invalid moat_assessments hints at expected format."""
        payload = {"moat_assessments": "not_valid", "metadata": {"run_id": "test"}}
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1
        assert "object or array" in stderr.lower()

    # 15. Error for empty dict moat_assessments includes keyed-by-slug hint
    def test_score_moats_empty_dict_error_shows_expected_shape(self) -> None:
        """Error for empty dict moat_assessments includes keyed-by-slug hint."""
        payload = {"moat_assessments": {}, "metadata": {"run_id": "test"}}
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1
        assert "keyed by" in stderr.lower() or '{"_startup"' in stderr

    # 16. Error for company missing 'moats' array hints at expected entry format
    def test_score_moats_missing_moats_array_error_shows_shape(self) -> None:
        """Error for company missing 'moats' array hints at expected entry format."""
        payload = _make_valid_moat_input()
        del payload["moat_assessments"]["_startup"]["moats"]
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1
        assert "expected format" in stderr.lower() or '"id"' in stderr


# ---------------------------------------------------------------------------
# Factory: valid positioning input for score_positioning.py
# ---------------------------------------------------------------------------


def _make_positioning_point(
    competitor: str,
    x: int | float,
    y: int | float,
) -> dict[str, Any]:
    """Build a single positioning point entry."""
    return {
        "competitor": competitor,
        "x": x,
        "y": y,
        "x_evidence": f"Evidence for {competitor} on x-axis",
        "y_evidence": f"Evidence for {competitor} on y-axis",
        "x_evidence_source": "researched",
        "y_evidence_source": "researched",
    }


def _make_valid_positioning_input(
    *,
    views: list[dict[str, Any]] | None = None,
    differentiation_claims: list[dict[str, Any]] | None = None,
    data_confidence: str = "exact",
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a valid score_positioning.py input with primary view + 5 competitors + _startup."""
    if views is None:
        views = [
            {
                "id": "primary",
                "x_axis": {
                    "name": "Deployment Speed",
                    "description": "How fast the solution can be deployed",
                    "rationale": "Speed-to-value is a key differentiator for SMB buyers",
                },
                "y_axis": {
                    "name": "Data Privacy Level",
                    "description": "Degree of data privacy guarantees",
                    "rationale": "Privacy is a growing concern in the target market",
                },
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                    _make_positioning_point("delta-co", 20, 60),
                    _make_positioning_point("epsilon-sa", 70, 30),
                ],
            }
        ]
    if differentiation_claims is None:
        differentiation_claims = [
            {
                "claim": "Sub-5ms latency vs. competitors' 50-200ms",
                "verifiable": True,
                "evidence": "SDK-based approach avoids network hop",
                "challenge": "No independent benchmark found",
                "verdict": "holds",
            }
        ]
    return {
        "views": views,
        "differentiation_claims": differentiation_claims,
        "metadata": {"run_id": run_id},
        "data_confidence": data_confidence,
    }


# ===========================================================================
# score_positioning.py tests
# ===========================================================================


class TestScorePositioning:
    """Tests for score_positioning.py."""

    # 1. Well-formed input passes
    def test_score_positioning_valid_passes(self) -> None:
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "views" in data
        assert len(data["views"]) == 1
        assert "overall_differentiation" in data
        assert "differentiation_claims" in data
        assert "warnings" in data
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"
        view = data["views"][0]
        assert view["view_id"] == "primary"
        assert view["competitor_count"] == 5
        assert "differentiation_score" in view
        assert "startup_x_rank" in view
        assert "startup_y_rank" in view
        assert "x_axis_vanity_flag" in view
        assert "y_axis_vanity_flag" in view

    # 1b. Rank must respect axis polarity — a cheap price is a GOOD rank, not a bad one
    def test_score_positioning_rank_respects_lower_is_better_axis(self) -> None:
        """`_compute_rank` counted competitors with a HIGHER value and called that the rank, which is
        only correct when higher is better.

        Measured on a live run: the axis was `Price (total cost of ownership, low to high)`, the startup
        sat at x=22 — second cheapest of nine — and the delivered report told the founder it "ranks last
        of eight companies on both price and analytical depth. That is the headline finding to address."
        The same inverted rank feeds `differentiation_score` at 50% weight, so on a price axis the
        formula REWARDED being expensive.

        Nothing in the schema or the dispatch expressed which direction was good, so the producer could
        not have known. This asserts the field is honoured once present.
        """
        payload = _make_valid_positioning_input()
        view = payload["views"][0]
        view["x_axis"] = {
            "name": "Price (total cost of ownership)",
            "description": "First-year total cost to the buyer",
            "rationale": "The deck claims a price advantage; this axis tests it",
            "polarity": "lower_is_better",
        }
        # startup at 22; competitors at 60/30/50/20/70 -> exactly one competitor is cheaper.
        view["points"] = [
            _make_positioning_point("_startup", 22, 85),
            _make_positioning_point("acme-corp", 60, 40),
            _make_positioning_point("beta-inc", 30, 70),
            _make_positioning_point("gamma-ltd", 50, 50),
            _make_positioning_point("delta-co", 20, 60),
            _make_positioning_point("epsilon-sa", 70, 30),
        ]
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        v = data["views"][0]
        assert v["startup_x_rank"] == 2, (
            f"cheapest-but-one on a lower-is-better axis must rank 2, got {v['startup_x_rank']} — the "
            f"rank is being computed as though a high price were good"
        )
        # Y is untouched and higher-is-better: startup at 85 beats every competitor.
        assert v["startup_y_rank"] == 1, f"Y-axis rank changed unexpectedly: {v['startup_y_rank']}"

    def test_score_positioning_polarity_defaults_to_higher_is_better(self) -> None:
        """An artifact written before `polarity` existed must score exactly as it did before.

        The field is optional and absent from every artifact produced to date, so the default is not a
        style choice — it is what keeps already-written artifacts scoring the same.
        """
        payload = _make_valid_positioning_input()
        assert "polarity" not in payload["views"][0]["x_axis"], "factory should not set polarity here"
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # startup x=90 is the highest of 90/60/30/50/20/70 -> rank 1 under higher-is-better.
        assert data["views"][0]["startup_x_rank"] == 1

    # 2. Vanity axis detected when >80% of competitors cluster within 20% range
    def test_score_positioning_vanity_axis_detected(self) -> None:
        # 5 competitors all with x in [40, 60] (within 20% range), _startup at 90
        points = [
            _make_positioning_point("_startup", 90, 85),
            _make_positioning_point("acme-corp", 42, 40),
            _make_positioning_point("beta-inc", 45, 70),
            _make_positioning_point("gamma-ltd", 50, 50),
            _make_positioning_point("delta-co", 48, 60),
            _make_positioning_point("epsilon-sa", 55, 30),
        ]
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points,
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        view = data["views"][0]
        # All 5 competitors (100% > 80%) are within [42, 55] — range of 13 < 20
        assert view["x_axis_vanity_flag"] is True
        # y-axis has spread [30, 70] — range 40 > 20, not vanity
        assert view["y_axis_vanity_flag"] is False
        # Should have VANITY_AXIS_WARNING
        codes = [w["code"] for w in data["warnings"]]
        assert "VANITY_AXIS_WARNING" in codes

    # 3. Non-vanity axis — spread competitors don't trigger vanity
    def test_score_positioning_non_vanity_axis(self) -> None:
        points = [
            _make_positioning_point("_startup", 90, 85),
            _make_positioning_point("acme-corp", 10, 20),
            _make_positioning_point("beta-inc", 30, 80),
            _make_positioning_point("gamma-ltd", 50, 50),
            _make_positioning_point("delta-co", 70, 40),
            _make_positioning_point("epsilon-sa", 90, 10),
        ]
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points,
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        view = data["views"][0]
        assert view["x_axis_vanity_flag"] is False
        assert view["y_axis_vanity_flag"] is False

    # 4. Rank-based differentiation — startup ranked 1st scores high; middle scores low
    #    Uses distance-weighted formula: rank 50% + gap 50%
    def test_score_positioning_rank_based_differentiation(self) -> None:
        # Startup at top of both axes (rank 1 on both) with moderate gap
        points_top = [
            _make_positioning_point("_startup", 95, 95),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
            _make_positioning_point("delta-co", 20, 20),
        ]
        views_top = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_top,
            }
        ]
        payload_top = _make_valid_positioning_input(views=views_top)
        rc, data_top, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload_top))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data_top is not None

        # Startup in middle of both axes
        points_mid = [
            _make_positioning_point("_startup", 50, 50),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
            _make_positioning_point("delta-co", 20, 20),
        ]
        views_mid = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_mid,
            }
        ]
        payload_mid = _make_valid_positioning_input(views=views_mid)
        rc2, data_mid, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload_mid))
        assert rc2 == 0, f"Expected exit 0, got {rc2}. stderr: {stderr2}"
        assert data_mid is not None

        top_score = data_top["views"][0]["differentiation_score"]
        mid_score = data_mid["views"][0]["differentiation_score"]
        assert top_score > mid_score, f"Top score {top_score} should exceed mid score {mid_score}"
        # Distance-weighted: rank 1 of 4 => rank_score = 50, gap (95-80)/100 = 0.15 => gap_score = 7.5
        # Per axis: 57.5, average of two axes: 57.5
        assert top_score == 57.5
        # Mid: rank 3 of 4 => rank_score = 25, gap = 0 (behind top competitor)
        # Per axis: 25.0, average: 25.0
        assert mid_score == 25.0

    # 4b. Distance-weighted scoring: larger gap produces higher score at same rank
    def test_score_positioning_gap_distinguishes_barely_vs_dramatically_ahead(self) -> None:
        # Scenario A: startup barely ahead (rank 1, gap 2%)
        points_barely = [
            _make_positioning_point("_startup", 82, 82),
            _make_positioning_point("acme-corp", 80, 80),
            _make_positioning_point("beta-inc", 60, 60),
            _make_positioning_point("gamma-ltd", 40, 40),
        ]
        views_barely = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_barely,
            }
        ]
        payload_barely = _make_valid_positioning_input(views=views_barely)
        rc1, data_barely, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(payload_barely))
        assert rc1 == 0, f"stderr: {stderr1}"
        assert data_barely is not None

        # Scenario B: startup dramatically ahead (rank 1, gap 40%)
        points_dramatic = [
            _make_positioning_point("_startup", 95, 95),
            _make_positioning_point("acme-corp", 55, 55),
            _make_positioning_point("beta-inc", 40, 40),
            _make_positioning_point("gamma-ltd", 20, 20),
        ]
        views_dramatic = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": points_dramatic,
            }
        ]
        payload_dramatic = _make_valid_positioning_input(views=views_dramatic)
        rc2, data_dramatic, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload_dramatic))
        assert rc2 == 0, f"stderr: {stderr2}"
        assert data_dramatic is not None

        barely_score = data_barely["views"][0]["differentiation_score"]
        dramatic_score = data_dramatic["views"][0]["differentiation_score"]
        # Both are rank 1, but dramatic gap should score meaningfully higher
        assert dramatic_score > barely_score, (
            f"Dramatic gap score {dramatic_score} should exceed barely-ahead score {barely_score}"
        )

    # 5. Secondary view gets its own scores
    def test_score_positioning_secondary_view_scored(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X1", "description": "...", "rationale": "x1 rationale"},
                "y_axis": {"name": "Y1", "description": "...", "rationale": "y1 rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 80),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            },
            {
                "id": "secondary",
                "x_axis": {"name": "X2", "description": "...", "rationale": "x2 rationale"},
                "y_axis": {"name": "Y2", "description": "...", "rationale": "y2 rationale"},
                "points": [
                    _make_positioning_point("_startup", 20, 30),
                    _make_positioning_point("acme-corp", 80, 90),
                    _make_positioning_point("beta-inc", 50, 60),
                ],
            },
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert len(data["views"]) == 2
        ids = [v["view_id"] for v in data["views"]]
        assert "primary" in ids
        assert "secondary" in ids
        # Each view has its own scores
        for v in data["views"]:
            assert "differentiation_score" in v
            assert "startup_x_rank" in v
            assert "startup_y_rank" in v

    # 6. Aggregate differentiation computed across views
    def test_score_positioning_aggregate_differentiation(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X1", "description": "...", "rationale": "x1 rationale"},
                "y_axis": {"name": "Y1", "description": "...", "rationale": "y1 rationale"},
                "points": [
                    _make_positioning_point("_startup", 95, 95),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            },
            {
                "id": "secondary",
                "x_axis": {"name": "X2", "description": "...", "rationale": "x2 rationale"},
                "y_axis": {"name": "Y2", "description": "...", "rationale": "y2 rationale"},
                "points": [
                    _make_positioning_point("_startup", 20, 30),
                    _make_positioning_point("acme-corp", 80, 90),
                    _make_positioning_point("beta-inc", 50, 60),
                ],
            },
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # overall_differentiation should be average of per-view scores
        scores = [v["differentiation_score"] for v in data["views"]]
        expected = round(sum(scores) / len(scores), 1)
        assert data["overall_differentiation"] == expected

    # 7. Missing _startup fails
    def test_score_positioning_missing_startup_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 8. Stress-test passthrough — differentiation_claims passed through
    def test_score_positioning_stress_test_passthrough(self) -> None:
        claims = [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data shows <5ms",
                "challenge": "No third-party validation",
                "verdict": "holds",
            },
            {
                "claim": "Only GraphQL support",
                "verifiable": True,
                "evidence": "Competitor analysis confirms",
                "challenge": "Others may add it soon",
                "verdict": "partially_holds",
            },
        ]
        payload = _make_valid_positioning_input(differentiation_claims=claims)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert len(data["differentiation_claims"]) == 2
        assert data["differentiation_claims"][0]["claim"] == "Best latency in market"
        assert data["differentiation_claims"][1]["verdict"] == "partially_holds"

    # 9. Data confidence passthrough
    def test_score_positioning_data_confidence_passthrough(self) -> None:
        payload = _make_valid_positioning_input(data_confidence="estimated")
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("data_confidence") == "estimated"

    # 10. String axis values are normalized to {name: <string>} objects
    def test_score_positioning_string_axes_normalized(self) -> None:
        """String axis values are normalized to {name: <string>} objects."""
        payload = _make_valid_positioning_input()
        payload["views"][0]["x_axis"] = "Compute Efficiency"
        payload["views"][0]["y_axis"] = "Market Reach"
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["views"][0]["x_axis_name"] == "Compute Efficiency"
        assert data["views"][0]["y_axis_name"] == "Market Reach"
        assert "normalized" in stderr.lower()

    # 11. Points with 'slug' key instead of 'competitor' are normalized and scored identically
    def test_score_positioning_slug_key_accepted(self) -> None:
        """Points with 'slug' key instead of 'competitor' are normalized and scored identically."""
        payload_baseline = _make_valid_positioning_input()
        rc_base, data_base, _ = run_script("score_positioning.py", stdin_data=json.dumps(payload_baseline))
        assert rc_base == 0
        assert data_base is not None
        payload = _make_valid_positioning_input()
        for point in payload["views"][0]["points"]:
            point["slug"] = point.pop("competitor")
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "normalized" in stderr.lower()
        assert data["views"][0]["competitor_count"] == data_base["views"][0]["competitor_count"]
        assert data["views"][0]["differentiation_score"] == data_base["views"][0]["differentiation_score"]

    # 12. Points with empty 'slug' key are rejected
    def test_score_positioning_empty_slug_rejected(self) -> None:
        """Points with empty 'slug' key are rejected."""
        payload = _make_valid_positioning_input()
        for point in payload["views"][0]["points"]:
            point["slug"] = point.pop("competitor")
        payload["views"][0]["points"][0]["slug"] = ""
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for empty slug, got {rc}. stderr: {stderr}"
        assert "empty" in stderr.lower() or "blank" in stderr.lower()

    # 13. Points with both 'slug' and 'competitor' that disagree are rejected
    def test_score_positioning_conflicting_slug_competitor_rejected(self) -> None:
        """Points with both 'slug' and 'competitor' that disagree are rejected."""
        payload = _make_valid_positioning_input()
        payload["views"][0]["points"][0]["slug"] = "wrong-slug"
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for conflicting slug/competitor, got {rc}. stderr: {stderr}"
        assert "conflicting" in stderr.lower()

    # 14. Blank string axis is rejected
    def test_score_positioning_blank_axis_string_rejected(self) -> None:
        """Blank string axis is rejected, not normalized to {'name': ''}."""
        payload = _make_valid_positioning_input()
        payload["views"][0]["x_axis"] = ""
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for blank axis, got {rc}. stderr: {stderr}"
        assert "blank" in stderr.lower()

    # 15. Points without 'competitor' key are rejected by validation
    def test_score_positioning_missing_competitor_rejected(self) -> None:
        """Points without 'competitor' key are rejected by validation."""
        payload = _make_valid_positioning_input()
        del payload["views"][0]["points"][0]["competitor"]
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for missing competitor, got {rc}. stderr: {stderr}"
        assert "competitor" in stderr.lower()

    # 16. Error for invalid axis hints at expected shape with required 'name' field
    def test_score_positioning_axis_error_shows_expected_shape(self) -> None:
        """Error for invalid axis hints at expected shape with required 'name' field."""
        payload = _make_valid_positioning_input()
        payload["views"][0]["x_axis"] = 42  # Not string (would normalize) or object
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1
        assert "name" in stderr.lower()

    # 17. Error for axis object missing 'name' includes recommended shape
    def test_score_positioning_missing_name_error_shows_shape(self) -> None:
        """Error for axis object missing 'name' includes recommended shape."""
        payload = _make_valid_positioning_input()
        payload["views"][0]["x_axis"] = {"description": "test"}
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1
        assert "recommended" in stderr.lower() or '"name"' in stderr

    # 18. scored_view carries points[] through — the main thread must not have to
    # separately keep the sub-agent's raw x/y coordinates alive elsewhere to
    # rebuild the map; positioning_scores.json is a self-contained record of them.
    def test_score_positioning_scored_view_includes_points(self) -> None:
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        view = data["views"][0]
        assert "points" in view, "scored_view must pass through the input view's points[]"
        input_points = payload["views"][0]["points"]
        assert len(view["points"]) == len(input_points)
        by_competitor = {p["competitor"]: p for p in view["points"]}
        for ip in input_points:
            out_p = by_competitor[ip["competitor"]]
            assert out_p["x"] == ip["x"]
            assert out_p["y"] == ip["y"]
            assert out_p["x_evidence"] == ip["x_evidence"]
            assert out_p["y_evidence"] == ip["y_evidence"]
            assert out_p["x_evidence_source"] == ip["x_evidence_source"]
            assert out_p["y_evidence_source"] == ip["y_evidence_source"]


# ---------------------------------------------------------------------------
# Factory: valid checklist input for checklist.py
# ---------------------------------------------------------------------------

# Canonical 25 checklist item IDs — must match checklist-criteria.md exactly.
CHECKLIST_IDS: list[str] = [
    # Competitor Coverage (5)
    "COVER_01",
    "COVER_02",
    "COVER_03",
    "COVER_04",
    "COVER_05",
    # Positioning Quality (5)
    "POS_01",
    "POS_02",
    "POS_03",
    "POS_04",
    "POS_05",
    # Moat Assessment (4)
    "MOAT_01",
    "MOAT_02",
    "MOAT_03",
    "MOAT_04",
    # Evidence Quality (4)
    "EVID_01",
    "EVID_02",
    "EVID_03",
    "EVID_04",
    # Narrative Readiness (4)
    "NARR_01",
    "NARR_02",
    "NARR_03",
    "NARR_04",
    # Common Mistakes (3)
    "MISS_01",
    "MISS_02",
    "MISS_03",
]


def _make_checklist_item(
    item_id: str,
    *,
    status: str = "pass",
    evidence: str = "Sufficient evidence for this checklist item.",
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a single checklist item entry."""
    result: dict[str, Any] = {
        "id": item_id,
        "status": status,
        "evidence": evidence,
    }
    if notes is not None:
        result["notes"] = notes
    return result


def _make_valid_checklist_input(
    *,
    input_mode: str = "conversation",
    data_confidence: str = "exact",
    run_id: str = "20260319T143045Z",
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a valid checklist.py input with all 25 items.

    ``overrides`` maps item ID to status, e.g. {"COVER_01": "fail"}.
    """
    overrides = overrides or {}
    items = []
    for item_id in CHECKLIST_IDS:
        status = overrides.get(item_id, "pass")
        evidence = (
            f"Evidence for {item_id} (status={status})" if status != "not_applicable" else f"Auto-gated: {item_id}"
        )
        items.append(_make_checklist_item(item_id, status=status, evidence=evidence))
    return {
        "items": items,
        "input_mode": input_mode,
        "data_confidence": data_confidence,
        "metadata": {"run_id": run_id},
    }


# ===========================================================================
# score_positioning.py tests — scoring_basis
# ===========================================================================


class TestScorePositioningScoringBasis:
    """scoring_basis must round-trip from stdin to output verbatim, reject an
    unlisted value, and stay ABSENT from the output when the input never
    supplied it — never silently defaulted to 'shipped'. An artifact produced
    before this field existed has a genuinely undefined basis; stamping a
    default on it would assert a convention that was never in force."""

    def test_scoring_basis_round_trips_from_stdin(self) -> None:
        for basis in ("shipped", "roadmap_12mo", "mixed"):
            payload = _make_valid_positioning_input()
            payload["scoring_basis"] = basis
            rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
            assert rc == 0, f"basis={basis}: expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            assert data.get("scoring_basis") == basis

    def test_invalid_scoring_basis_exits_1(self) -> None:
        payload = _make_valid_positioning_input()
        payload["scoring_basis"] = "bogus_basis"
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1 for an unlisted scoring_basis, got {rc}. stderr: {stderr}"
        assert "scoring_basis" in stderr

    def test_scoring_basis_absent_from_input_stays_absent_from_output(self) -> None:
        payload = _make_valid_positioning_input()
        assert "scoring_basis" not in payload
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "scoring_basis" not in data, (
            f"scoring_basis must be ABSENT (not defaulted) when the input never supplied it. "
            f"Got: {data.get('scoring_basis')!r}"
        )

    def test_founder_override_repipe_round_trip_preserves_scoring_basis(self) -> None:
        """The founder coordinate-override flow re-pipes `positioning.json` itself
        (not the original sub-agent hand-off) through score_positioning.py to
        refresh positioning_scores.json. This must carry scoring_basis end to end:
        a positioning.json on disk that carries scoring_basis, piped through the
        script and written back out with -o, must still carry scoring_basis in
        the resulting positioning_scores.json file. If the SKILL.md merge step
        stops copying scoring_basis into positioning.json, this is the test that
        catches the regression before every renderer falls back to "Not declared".
        """
        for basis in ("shipped", "roadmap_12mo", "mixed"):
            # Simulate positioning.json on disk after a founder override: real
            # points, a scoring_basis carried over from the original merge, and
            # one coordinate stamped founder_override.
            positioning_on_disk = _make_valid_positioning_input()
            positioning_on_disk["scoring_basis"] = basis
            positioning_on_disk["views"][0]["points"][1]["x_evidence_source"] = "founder_override"

            with tempfile.TemporaryDirectory() as tmp:
                positioning_path = os.path.join(tmp, "positioning.json")
                scores_path = os.path.join(tmp, "positioning_scores.json")
                with open(positioning_path, "w", encoding="utf-8") as f:
                    json.dump(positioning_on_disk, f)

                with open(positioning_path, encoding="utf-8") as f:
                    stdin_data = f.read()
                rc, _receipt, stderr = run_script(
                    "score_positioning.py",
                    args=["-o", scores_path],
                    stdin_data=stdin_data,
                )
                assert rc == 0, f"basis={basis}: expected exit 0, got {rc}. stderr: {stderr}"

                with open(scores_path, encoding="utf-8") as f:
                    refreshed = json.load(f)
                assert refreshed.get("scoring_basis") == basis, (
                    f"basis={basis}: refreshed positioning_scores.json lost scoring_basis on the "
                    f"founder-override re-pipe. Got: {refreshed.get('scoring_basis')!r}"
                )


# ===========================================================================
# checklist.py tests
# ===========================================================================


class TestChecklist:
    """Tests for checklist.py."""

    # 1. All items assessed with valid statuses, exits 0
    def test_checklist_valid_passes(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "items" in data
        assert len(data["items"]) == 25
        assert "score_pct" in data
        assert "pass_count" in data
        assert "fail_count" in data
        assert "warn_count" in data
        assert "na_count" in data
        assert "total" in data
        assert data["total"] == 25
        assert "input_mode" in data
        assert data["input_mode"] == "conversation"
        assert "metadata" in data
        assert data["metadata"]["run_id"] == "20260319T143045Z"

    # 2. Score computation: (pass_count + 0.5 * warn_count) / (total - na) * 100
    def test_checklist_score_computation(self) -> None:
        # Use document mode which only gates NARR_03 (1 auto-gated).
        # Override 3 items to fail and 1 to warn.
        # Result: 20 pass, 3 fail, 1 warn, 1 na (NARR_03 gated)
        # score = (20 + 0.5 * 1) / (25 - 1) * 100 = 85.4
        overrides = {
            "COVER_01": "fail",
            "COVER_02": "fail",
            "COVER_03": "fail",
            "POS_01": "warn",
        }
        payload = _make_valid_checklist_input(input_mode="document", overrides=overrides)
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["pass_count"] == 20
        assert data["fail_count"] == 3
        assert data["warn_count"] == 1
        assert data["na_count"] == 1
        assert data["total"] == 25
        # warn counts as 0.5 points (matches deck-review pattern)
        expected_score = round((20 + 0.5 * 1) / (25 - 1) * 100, 1)
        assert data["score_pct"] == expected_score

    # 3. Deck mode auto-gates EVID_02 and EVID_04
    def test_checklist_mode_gating_deck(self) -> None:
        payload = _make_valid_checklist_input(input_mode="deck")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        items_by_id = {item["id"]: item for item in data["items"]}
        # EVID_04 should be auto-gated to not_applicable in deck mode
        assert items_by_id["EVID_04"]["status"] == "not_applicable"
        # EVID_02 is NOT gated in deck mode (research always happens)
        assert items_by_id["EVID_02"]["status"] != "not_applicable"
        # NARR_03 should remain active in deck mode
        assert items_by_id["NARR_03"]["status"] != "not_applicable"
        assert data["na_count"] >= 1

    # 4. Conversation mode gates NARR_03 and EVID_04
    def test_checklist_mode_gating_conversation(self) -> None:
        payload = _make_valid_checklist_input(input_mode="conversation")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        items_by_id = {item["id"]: item for item in data["items"]}
        # NARR_03 and EVID_04 should be auto-gated
        assert items_by_id["NARR_03"]["status"] == "not_applicable"
        assert items_by_id["EVID_04"]["status"] == "not_applicable"
        # EVID_02 should remain active in conversation mode
        assert items_by_id["EVID_02"]["status"] != "not_applicable"

    # 5. Missing required item ID exits 1
    def test_checklist_missing_item_fails(self) -> None:
        payload = _make_valid_checklist_input()
        # Remove one item
        payload["items"] = [i for i in payload["items"] if i["id"] != "COVER_01"]
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 6. Invalid status exits 1
    def test_checklist_invalid_status_fails(self) -> None:
        payload = _make_valid_checklist_input()
        payload["items"][0]["status"] = "maybe"
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 7. Data confidence qualifier appended when estimated
    def test_checklist_data_confidence_qualifier(self) -> None:
        payload = _make_valid_checklist_input(data_confidence="estimated")
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # Non-gated items should have the qualifier appended
        for item in data["items"]:
            if item["status"] != "not_applicable":
                assert "(based on estimated inputs)" in item["evidence"], (
                    f"Item {item['id']} missing confidence qualifier in evidence"
                )

    # ---- v0.4.2 Phase 1 Task 1: summary block parity ----

    # 8. Output includes a `summary` block with the unified shape.
    def test_checklist_emits_summary_block(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "summary" in data, "checklist output must include a top-level 'summary' block"
        summary = data["summary"]
        for key in (
            "score_pct",
            "overall_status",
            "total",
            "pass",
            "fail",
            "warn",
            "not_applicable",
            "failed_items",
            "warned_items",
        ):
            assert key in summary, f"summary missing required key '{key}'"
        # overall_status must be one of the four documented tiers
        assert summary["overall_status"] in {"strong", "solid", "needs_work", "major_revision"}

    # 9. failed_items array length matches summary.fail count and item shape is correct.
    def test_checklist_summary_failed_items_array(self) -> None:
        overrides = {"COVER_01": "fail", "COVER_02": "fail"}
        payload = _make_valid_checklist_input(input_mode="document", overrides=overrides)
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        summary = data["summary"]
        failed = summary["failed_items"]
        assert isinstance(failed, list)
        assert len(failed) == summary["fail"], "failed_items length must equal summary.fail"
        assert len(failed) == 2
        for entry in failed:
            for k in ("id", "category", "criterion", "status", "evidence", "principle"):
                assert k in entry, f"failed_items entry missing key '{k}'"
            assert entry["status"] == "fail"

    # 10. warned_items array length matches summary.warn count and item shape is correct.
    def test_checklist_summary_warned_items_array(self) -> None:
        overrides = {"POS_01": "warn", "POS_02": "warn", "POS_03": "warn"}
        payload = _make_valid_checklist_input(input_mode="document", overrides=overrides)
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        summary = data["summary"]
        warned = summary["warned_items"]
        assert isinstance(warned, list)
        assert len(warned) == summary["warn"], "warned_items length must equal summary.warn"
        assert len(warned) == 3
        for entry in warned:
            for k in ("id", "category", "criterion", "status", "evidence", "principle"):
                assert k in entry, f"warned_items entry missing key '{k}'"
            assert entry["status"] == "warn"

    # 11. Backward-compat: legacy flat fields still present at top level alongside summary.
    def test_checklist_backward_compat_flat_fields(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        # All legacy flat fields must remain at top level for backward compatibility.
        for legacy_key in (
            "pass_count",
            "fail_count",
            "warn_count",
            "na_count",
            "total",
            "score_pct",
            "items",
        ):
            assert legacy_key in data, f"legacy top-level key '{legacy_key}' must remain for backward compat"
        # And the new summary block coexists.
        assert "summary" in data
        # Sanity: legacy and summary fields agree.
        assert data["pass_count"] == data["summary"]["pass"]
        assert data["fail_count"] == data["summary"]["fail"]
        assert data["warn_count"] == data["summary"]["warn"]
        assert data["na_count"] == data["summary"]["not_applicable"]
        assert data["score_pct"] == data["summary"]["score_pct"]
        assert data["total"] == data["summary"]["total"]


# ===========================================================================
# compose_report.py tests
# ===========================================================================


def _make_product_profile(
    *,
    company_name: str = "TestCo",
    slug: str = "testco",
    run_id: str = "20260319T143045Z",
) -> dict[str, Any]:
    """Build a product_profile.json artifact."""
    return {
        "company_name": company_name,
        "slug": slug,
        "product_description": "A test product for automated testing.",
        "target_customers": ["SMBs", "Enterprise"],
        "value_propositions": ["Fast deployment", "High accuracy"],
        "differentiation_claims": ["Best-in-class latency"],
        "stage": "seed",
        "sector": "SaaS",
        "business_model": "SaaS",
        "input_mode": "conversation",
        "source_materials": ["founder conversation"],
        "metadata": {"run_id": run_id},
    }


def _make_landscape_artifact(
    *,
    run_id: str = "20260319T143045Z",
    competitors: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a landscape.json artifact (output of validate_landscape)."""
    if competitors is None:
        competitors = [
            _make_competitor("Alpha Corp", "alpha-corp", "direct"),
            _make_competitor("Beta Inc", "beta-inc", "direct"),
            _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
            _make_competitor("Delta Co", "delta-co", "emerging"),
            _make_competitor("Manual Process", "manual-process", "do_nothing"),
        ]
    return {
        "competitors": competitors,
        "input_mode": "conversation",
        "warnings": warnings or [],
        "_produced_by": "validate_landscape",
        "metadata": {"run_id": run_id},
    }


def _make_positioning_artifact(
    *,
    run_id: str = "20260319T143045Z",
    accepted_warnings: list[dict[str, Any]] | None = None,
    assessment_mode: str | None = None,
    views: list[dict[str, Any]] | None = None,
    moat_assessments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a positioning.json artifact."""
    if views is None:
        views = [
            {
                "id": "primary",
                "x_axis": {
                    "name": "Deployment Speed",
                    "description": "How fast to deploy",
                    "rationale": "Key differentiator for SMBs",
                },
                "y_axis": {
                    "name": "Detection Accuracy",
                    "description": "Threat detection accuracy",
                    "rationale": "Table-stakes dimension",
                },
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("alpha-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                    _make_positioning_point("gamma-ltd", 50, 50),
                    _make_positioning_point("delta-co", 20, 60),
                    _make_positioning_point("manual-process", 95, 15),
                ],
            }
        ]
    if moat_assessments is None:
        moat_assessments = {}
        for slug in ["_startup", "alpha-corp", "beta-inc", "gamma-ltd", "delta-co", "manual-process"]:
            moat_assessments[slug] = {
                "moats": [
                    _make_moat_entry("network_effects", status="moderate"),
                    _make_moat_entry("data_advantages", status="moderate"),
                    _make_moat_entry("switching_costs", status="moderate"),
                    _make_moat_entry("regulatory_barriers", status="absent"),
                    _make_moat_entry("cost_structure", status="weak"),
                    _make_moat_entry("brand_reputation", status="weak"),
                ]
            }
    result: dict[str, Any] = {
        "views": views,
        "moat_assessments": moat_assessments,
        "differentiation_claims": [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data shows <5ms",
                "challenge": "No third-party validation",
                "verdict": "holds",
            }
        ],
        "metadata": {"run_id": run_id},
    }
    if accepted_warnings is not None:
        result["accepted_warnings"] = accepted_warnings
    if assessment_mode is not None:
        result["assessment_mode"] = assessment_mode
    return result


def _make_moat_scores_artifact(
    *,
    run_id: str = "20260319T143045Z",
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a moat_scores.json artifact."""
    return {
        "companies": {
            "_startup": {
                "moats": [
                    _make_moat_entry("network_effects", status="moderate"),
                    _make_moat_entry("data_advantages", status="strong"),
                ],
                "moat_count": 2,
                "strongest_moat": "data_advantages",
                "overall_defensibility": "moderate",
            },
            "alpha-corp": {
                "moats": [
                    _make_moat_entry("network_effects", status="strong"),
                    _make_moat_entry("data_advantages", status="strong"),
                ],
                "moat_count": 2,
                "strongest_moat": "network_effects",
                "overall_defensibility": "high",
            },
        },
        "comparison": {
            "by_dimension": {
                "network_effects": {"_startup": "moderate", "alpha-corp": "strong"},
                "data_advantages": {"_startup": "strong", "alpha-corp": "strong"},
            },
            "startup_rank": {
                "network_effects": {"rank": 2, "total": 2},
                "data_advantages": {"rank": 1, "total": 2},
            },
        },
        "warnings": warnings or [],
        "_produced_by": "score_moats",
        "metadata": {"run_id": run_id},
    }


def _make_positioning_scores_artifact(
    *,
    run_id: str = "20260319T143045Z",
    views: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a positioning_scores.json artifact."""
    if views is None:
        views = [
            {
                "view_id": "primary",
                "x_axis_name": "Deployment Speed",
                "y_axis_name": "Detection Accuracy",
                "x_axis_rationale": "Key differentiator for SMBs",
                "y_axis_rationale": "Table-stakes dimension",
                "x_axis_vanity_flag": False,
                "y_axis_vanity_flag": False,
                "differentiation_score": 75.0,
                "startup_x_rank": 1,
                "startup_y_rank": 3,
                "competitor_count": 5,
            }
        ]
    return {
        "views": views,
        "overall_differentiation": 75.0,
        "differentiation_claims": [
            {
                "claim": "Best latency in market",
                "verifiable": True,
                "evidence": "Benchmark data",
                "challenge": "No validation",
                "verdict": "holds",
            }
        ],
        "warnings": warnings or [],
        "_produced_by": "score_positioning",
        "metadata": {"run_id": run_id},
    }


def _make_checklist_artifact(
    *,
    run_id: str = "20260319T143045Z",
    score_pct: float = 82.6,
) -> dict[str, Any]:
    """Build a checklist.json artifact."""
    items = []
    for item_id in CHECKLIST_IDS:
        items.append(
            {
                "id": item_id,
                "category": item_id.split("_")[0],
                "label": f"Label for {item_id}",
                "status": "pass",
                "evidence": f"Evidence for {item_id}",
            }
        )
    return {
        "items": items,
        "score_pct": score_pct,
        "pass_count": 22,
        "warn_count": 1,
        "fail_count": 1,
        "na_count": 1,
        "total": 25,
        "input_mode": "conversation",
        "_produced_by": "checklist",
        "metadata": {"run_id": run_id},
    }


def _make_artifact_dir(
    tmp_path: str,
    *,
    run_id: str = "20260319T143045Z",
    include_product_profile: bool = True,
    include_landscape: bool = True,
    include_positioning: bool = True,
    include_moat_scores: bool = True,
    include_positioning_scores: bool = True,
    include_checklist: bool = True,
    landscape_overrides: dict[str, Any] | None = None,
    positioning_overrides: dict[str, Any] | None = None,
    moat_scores_overrides: dict[str, Any] | None = None,
    positioning_scores_overrides: dict[str, Any] | None = None,
    checklist_overrides: dict[str, Any] | None = None,
    product_profile_overrides: dict[str, Any] | None = None,
) -> str:
    """Write all required artifacts to a temp dir and return the path."""
    os.makedirs(tmp_path, exist_ok=True)

    if include_product_profile:
        pp = _make_product_profile(run_id=run_id)
        if product_profile_overrides:
            pp.update(product_profile_overrides)
        with open(os.path.join(tmp_path, "product_profile.json"), "w") as f:
            json.dump(pp, f)

    if include_landscape:
        ls = _make_landscape_artifact(run_id=run_id)
        if landscape_overrides:
            ls.update(landscape_overrides)
        with open(os.path.join(tmp_path, "landscape.json"), "w") as f:
            json.dump(ls, f)

    if include_positioning:
        pos = _make_positioning_artifact(run_id=run_id)
        if positioning_overrides:
            pos.update(positioning_overrides)
        with open(os.path.join(tmp_path, "positioning.json"), "w") as f:
            json.dump(pos, f)

    if include_moat_scores:
        ms = _make_moat_scores_artifact(run_id=run_id)
        if moat_scores_overrides:
            ms.update(moat_scores_overrides)
        with open(os.path.join(tmp_path, "moat_scores.json"), "w") as f:
            json.dump(ms, f)

    if include_positioning_scores:
        ps = _make_positioning_scores_artifact(run_id=run_id)
        if positioning_scores_overrides:
            ps.update(positioning_scores_overrides)
        with open(os.path.join(tmp_path, "positioning_scores.json"), "w") as f:
            json.dump(ps, f)

    if include_checklist:
        cl = _make_checklist_artifact(run_id=run_id)
        if checklist_overrides:
            cl.update(checklist_overrides)
        with open(os.path.join(tmp_path, "checklist.json"), "w") as f:
            json.dump(cl, f)

    return tmp_path


class TestCompose:
    """Tests for compose_report.py."""

    # 1. All artifacts present — exits 0, has report_markdown
    def test_compose_valid_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            assert "report_markdown" in data
            assert "metadata" in data
            assert "warnings" in data
            assert "artifacts_loaded" in data
            assert "scoring_summary" in data
            assert data["metadata"]["company_name"] == "TestCo"
            assert data["scoring_summary"]["checklist_score_pct"] == 82.6
            assert data["scoring_summary"]["overall_differentiation"] == 75.0
            assert data["scoring_summary"]["startup_defensibility"] == "moderate"

    # 1b. Compose reads checklist score from summary block (post-v0.4.2 shape).
    def test_compose_reads_checklist_score_from_summary_block(self) -> None:
        """Compose must prefer summary.score_pct over the legacy flat score_pct.

        Uses divergent values (summary=91.0, flat=88.0): if compose accidentally
        reads only the legacy flat field, this assertion sees 88.0 and fails.
        Guards against regression of the summary-read branch in compose_report.py.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite checklist.json with the new summary-block shape, where
            # summary.score_pct (91.0) differs from legacy flat score_pct (88.0).
            cl_with_summary = {
                "items": [
                    {
                        "id": item_id,
                        "category": item_id.split("_")[0],
                        "label": f"Label for {item_id}",
                        "status": "pass",
                        "evidence": f"Evidence for {item_id}",
                    }
                    for item_id in CHECKLIST_IDS
                ],
                "summary": {
                    "score_pct": 91.0,  # summary value — MUST be the one compose reads
                    "overall_status": "strong",
                    "total": 25,
                    "pass": 24,
                    "fail": 0,
                    "warn": 1,
                    "not_applicable": 0,
                    "failed_items": [],
                    "warned_items": [],
                },
                # Legacy flat fields with a DIFFERENT score_pct (the fallback path).
                "score_pct": 88.0,
                "pass_count": 24,
                "fail_count": 0,
                "warn_count": 1,
                "na_count": 0,
                "total": 25,
                "input_mode": "conversation",
                "_produced_by": "checklist",
                "metadata": {"run_id": "20260319T143045Z"},
            }
            with open(os.path.join(tmp, "checklist.json"), "w") as f:
                json.dump(cl_with_summary, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            # The summary-block value (91.0) must win over the legacy flat (88.0).
            assert data["scoring_summary"]["checklist_score_pct"] == 91.0

    # 2. Missing landscape.json -> MISSING_LANDSCAPE (high)
    def test_compose_missing_landscape_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_landscape=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_LANDSCAPE" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_LANDSCAPE")
            assert warn["severity"] == "high"

    # 3. Missing positioning_scores.json -> high severity
    def test_compose_missing_optional_artifact_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_positioning_scores=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_POSITIONING_SCORES" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_POSITIONING_SCORES")
            assert warn["severity"] == "high"

    # 4. --strict exits 1 on high-severity warning
    def test_compose_strict_mode_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_landscape=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--strict"])
            assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"

    # 5. Scoring slug not in landscape -> orphan warning
    def test_compose_orphan_competitor_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Use only 3 competitors in landscape but positioning has slugs not in landscape
            sparse_comps = [
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "direct"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
                _make_competitor("Delta Co", "delta-co", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": sparse_comps})
            # Add an orphan slug in moat_scores
            orphan_moat = _make_moat_scores_artifact()
            orphan_moat["companies"]["orphan-slug"] = {
                "moats": [_make_moat_entry("network_effects")],
                "moat_count": 1,
                "strongest_moat": "network_effects",
                "overall_defensibility": "low",
            }
            with open(os.path.join(tmp, "moat_scores.json"), "w") as f:
                json.dump(orphan_moat, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            # Should have an orphan warning for orphan-slug (not for _startup)
            messages = " ".join(w["message"] for w in data["warnings"])
            assert "orphan-slug" in messages

    # 6. Mismatched run_id -> STALE_ARTIFACT
    def test_compose_stale_artifact_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite checklist with a different run_id
            cl = _make_checklist_artifact(run_id="20260101T000000Z")
            with open(os.path.join(tmp, "checklist.json"), "w") as f:
                json.dump(cl, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "STALE_ARTIFACT" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "STALE_ARTIFACT")
            assert warn["severity"] == "high"

    # 7. Competitor with sourced_fields_count < 3 -> SHALLOW_COMPETITOR_PROFILE
    def test_compose_shallow_profile_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shallow = _make_competitor(
                "Shallow Co",
                "shallow-co",
                "direct",
                research_depth="partial",
                sourced_fields_count=1,
            )
            comps = [
                shallow,
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            # Update positioning/moat artifacts to include shallow-co
            pos = _make_positioning_artifact()
            pos["views"][0]["points"].append(_make_positioning_point("shallow-co", 40, 40))
            pos["moat_assessments"]["shallow-co"] = {"moats": [_make_moat_entry("network_effects")]}
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                json.dump(pos, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "SHALLOW_COMPETITOR_PROFILE" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "SHALLOW_COMPETITOR_PROFILE")
            assert warn["severity"] == "medium"
            assert "shallow-co" in warn["message"].lower() or "Shallow Co" in warn["message"]
            assert "research_depth" in warn["message"], "message must keep the raw field for the agent"

    # 7b. SHALLOW_COMPETITOR_PROFILE founder_message: plain-language, no raw enum token
    def test_compose_shallow_profile_founder_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shallow = _make_competitor(
                "Shallow Co",
                "shallow-co",
                "direct",
                research_depth="partial",
                sourced_fields_count=1,
            )
            comps = [
                shallow,
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            pos = _make_positioning_artifact()
            pos["views"][0]["points"].append(_make_positioning_point("shallow-co", 40, 40))
            pos["moat_assessments"]["shallow-co"] = {"moats": [_make_moat_entry("network_effects")]}
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                json.dump(pos, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            warn = next(w for w in data["warnings"] if w["code"] == "SHALLOW_COMPETITOR_PROFILE")
            assert "founder_message" in warn
            founder_msg = warn["founder_message"]
            assert "research_depth" not in founder_msg
            assert "partial" not in founder_msg
            assert "shallow-co" in founder_msg, (
                "the producer authors the message with the slug it has — substitution happens at render"
            )
            # The RENDERED warning must carry the display NAME, not the slug: a slug in the warnings
            # list is as unusable to a founder as one in a heading, and compose substitutes it at the
            # render boundary rather than every producer rewriting its message text.
            rendered = founder_msg.replace("shallow-co", "Shallow Co")
            assert rendered in data["report_markdown"], (
                "the warning should be rendered with the competitor's display name substituted"
            )
            assert "'shallow-co'" not in data["report_markdown"]

    # 8. Vanity-flagged view -> VANITY_AXIS_WARNING
    def test_compose_vanity_axis_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vanity_views = [
                {
                    "view_id": "primary",
                    "x_axis_name": "Speed",
                    "y_axis_name": "Quality",
                    "x_axis_rationale": "rationale",
                    "y_axis_rationale": "rationale",
                    "x_axis_vanity_flag": True,
                    "y_axis_vanity_flag": False,
                    "differentiation_score": 60.0,
                    "startup_x_rank": 1,
                    "startup_y_rank": 2,
                    "competitor_count": 5,
                }
            ]
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": vanity_views},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "VANITY_AXIS_WARNING" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "VANITY_AXIS_WARNING")
            assert warn["severity"] == "medium"

    # 9. MOAT_WITHOUT_EVIDENCE forwarded from moat_scores warnings
    def test_compose_moat_without_evidence_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            moat_warns = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "severity": "medium",
                    "message": "alpha-corp: network_effects rated 'strong' with insufficient evidence",
                    "company": "alpha-corp",
                    "moat_id": "network_effects",
                }
            ]
            _make_artifact_dir(
                tmp,
                moat_scores_overrides={"warnings": moat_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MOAT_WITHOUT_EVIDENCE" in codes

    # 9b. RESEARCHED_WITHOUT_SOURCE forwarded from moat_scores warnings, medium severity,
    # and acceptable via accepted_warnings (the same pattern as MOAT_WITHOUT_EVIDENCE).
    def test_compose_researched_without_source_warns_medium_and_acceptable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            moat_warns = [
                {
                    "code": "RESEARCHED_WITHOUT_SOURCE",
                    "severity": "medium",
                    "message": "alpha-corp: network_effects evidence_source is 'researched' but no source was provided",
                    "company": "alpha-corp",
                    "moat_id": "network_effects",
                }
            ]
            _make_artifact_dir(
                tmp,
                moat_scores_overrides={"warnings": moat_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "RESEARCHED_WITHOUT_SOURCE" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "RESEARCHED_WITHOUT_SOURCE")
            assert warn["severity"] == "medium"

            # Medium severity doesn't block --strict on its own (only high-severity does) —
            # confirm --strict still passes, then confirm acceptance via positioning.json's
            # accepted_warnings marks the warning acknowledged in the composed report.
            rc2, _data2, stderr2 = run_script("compose_report.py", args=["--dir", tmp, "--strict", "--pretty"])
            assert rc2 == 0, stderr2

            positioning_path = os.path.join(tmp, "positioning.json")
            with open(positioning_path, encoding="utf-8") as f:
                positioning = json.load(f)
            positioning["accepted_warnings"] = [
                {"code": "RESEARCHED_WITHOUT_SOURCE", "match": "alpha-corp", "reason": "test acceptance"}
            ]
            with open(positioning_path, "w", encoding="utf-8") as f:
                json.dump(positioning, f)
            rc3, data3, stderr3 = run_script("compose_report.py", args=["--dir", tmp, "--strict", "--pretty"])
            assert rc3 == 0, f"Expected exit 0 after acceptance, got {rc3}. stderr: {stderr3}"
            assert data3 is not None
            warn3 = next(w for w in data3["warnings"] if w["code"] == "RESEARCHED_WITHOUT_SOURCE")
            assert warn3.get("acknowledged") is True

    # 10. MISSING_DO_NOTHING forwarded from landscape warnings
    def test_compose_missing_do_nothing_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            land_warns = [
                {
                    "code": "MISSING_DO_NOTHING",
                    "severity": "medium",
                    "message": "No do_nothing or adjacent competitor found",
                }
            ]
            _make_artifact_dir(
                tmp,
                landscape_overrides={"warnings": land_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_DO_NOTHING" in codes

    # 10b. NO_RECENT_DEVELOPMENTS forwarded from landscape warnings — this is the
    # inertness guard: the warning is only useful to a founder if it survives the
    # compose_report.py forwarding loop (`if code in WARNING_SEVERITY`). Without
    # NO_RECENT_DEVELOPMENTS registered in WARNING_SEVERITY, this silently drops.
    def test_compose_no_recent_developments_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            land_warns = [
                {
                    "code": "NO_RECENT_DEVELOPMENTS",
                    "severity": "medium",
                    "message": "No competitor has any recent_developments entries.",
                }
            ]
            _make_artifact_dir(
                tmp,
                landscape_overrides={"warnings": land_warns},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "NO_RECENT_DEVELOPMENTS" in codes, (
                "NO_RECENT_DEVELOPMENTS must be registered in WARNING_SEVERITY, or forwarding "
                "silently drops it (compose_report.py's landscape-warning forwarding loop "
                "only appends codes present in WARNING_SEVERITY)"
            )
            warn = next(w for w in data["warnings"] if w["code"] == "NO_RECENT_DEVELOPMENTS")
            assert warn["severity"] == "medium"

    # 11. RESEARCH_DEPTH_LOW: founder_provided + few sourced competitors
    def test_compose_research_depth_low_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # All competitors with low sourced_fields_count
            comps = [
                _make_competitor("A", "a", "direct", research_depth="founder_provided", sourced_fields_count=1),
                _make_competitor("B", "b", "direct", research_depth="founder_provided", sourced_fields_count=1),
                _make_competitor("C", "c", "adjacent", research_depth="founder_provided", sourced_fields_count=2),
                _make_competitor("D", "d", "emerging", research_depth="founder_provided", sourced_fields_count=0),
                _make_competitor("E", "e", "do_nothing", research_depth="founder_provided", sourced_fields_count=0),
            ]
            # landscape enriched has research_depth; compose reads it from landscape metadata
            # landscape.json doesn't have top-level research_depth, but the enriched one does
            # Actually, looking at the schema: landscape_enriched.json has research_depth but
            # landscape.json (output of validate_landscape) does not have a top-level research_depth.
            # The compose should look at competitor-level research_depth.
            # Per the task spec: "landscape research_depth == 'founder_provided' AND fewer than 4..."
            # We need the metadata-level research_depth. Let me add it to the landscape.
            _make_artifact_dir(
                tmp,
                landscape_overrides={
                    "competitors": comps,
                    "research_depth": "founder_provided",
                },
            )
            # Update positioning to match slugs
            pos = _make_positioning_artifact(
                views=[
                    {
                        "id": "primary",
                        "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                        "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                        "points": [
                            _make_positioning_point("_startup", 90, 85),
                            _make_positioning_point("a", 60, 40),
                            _make_positioning_point("b", 30, 70),
                            _make_positioning_point("c", 50, 50),
                            _make_positioning_point("d", 20, 60),
                            _make_positioning_point("e", 95, 15),
                        ],
                    }
                ],
                moat_assessments={
                    slug: {"moats": [_make_moat_entry("network_effects")]}
                    for slug in ["_startup", "a", "b", "c", "d", "e"]
                },
            )
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                json.dump(pos, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "RESEARCH_DEPTH_LOW" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "RESEARCH_DEPTH_LOW")
            assert warn["severity"] == "medium"

    # 12. SEQUENTIAL_FALLBACK: assessment_mode == "sequential"
    def test_compose_sequential_fallback_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_overrides={"assessment_mode": "sequential"})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "SEQUENTIAL_FALLBACK" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "SEQUENTIAL_FALLBACK")
            assert warn["severity"] == "info"

    # 13. Accepted warnings downgrades medium to acknowledged
    def test_compose_accepted_warnings_downgrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create a scenario with MOAT_WITHOUT_EVIDENCE forwarded from moat_scores
            moat_warns = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "severity": "medium",
                    "message": "alpha-corp: network_effects rated 'strong' with insufficient evidence",
                    "company": "alpha-corp",
                    "moat_id": "network_effects",
                }
            ]
            accepted = [
                {
                    "code": "MOAT_WITHOUT_EVIDENCE",
                    "match": "alpha-corp",
                    "reason": "Acceptable given source constraints",
                }
            ]
            _make_artifact_dir(
                tmp,
                moat_scores_overrides={"warnings": moat_warns},
                positioning_overrides={"accepted_warnings": accepted},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            moat_w = next(w for w in data["warnings"] if w["code"] == "MOAT_WITHOUT_EVIDENCE")
            assert moat_w["severity"] == "acknowledged"

    # 14. High-severity code in accepted_warnings is ignored
    def test_compose_high_severity_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            accepted = [
                {
                    "code": "MISSING_LANDSCAPE",
                    "match": "landscape",
                    "reason": "We know it's missing",
                }
            ]
            _make_artifact_dir(
                tmp,
                include_landscape=False,
                positioning_overrides={"accepted_warnings": accepted},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            land_w = next(w for w in data["warnings"] if w["code"] == "MISSING_LANDSCAPE")
            # Should NOT be acknowledged — high severity cannot be accepted
            assert land_w["severity"] == "high"

    # 15. FOUNDER_OVERRIDE_COUNT counts founder_override evidence sources
    def test_compose_founder_override_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create positioning with some founder_override evidence_sources
            views = [
                {
                    "id": "primary",
                    "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                    "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                    "points": [
                        {
                            "competitor": "_startup",
                            "x": 90,
                            "y": 85,
                            "x_evidence": "e1",
                            "y_evidence": "e2",
                            "x_evidence_source": "founder_override",
                            "y_evidence_source": "founder_override",
                        },
                        {
                            "competitor": "alpha-corp",
                            "x": 60,
                            "y": 40,
                            "x_evidence": "e1",
                            "y_evidence": "e2",
                            "x_evidence_source": "researched",
                            "y_evidence_source": "founder_override",
                        },
                        _make_positioning_point("beta-inc", 30, 70),
                        _make_positioning_point("gamma-ltd", 50, 50),
                        _make_positioning_point("delta-co", 20, 60),
                        _make_positioning_point("manual-process", 95, 15),
                    ],
                }
            ]
            # Also add founder_override in moat assessments
            moat_assessments: dict[str, Any] = {}
            for slug in ["_startup", "alpha-corp", "beta-inc", "gamma-ltd", "delta-co", "manual-process"]:
                moat_assessments[slug] = {
                    "moats": [
                        _make_moat_entry(
                            "network_effects",
                            evidence_source="founder_override" if slug == "_startup" else "researched",
                        ),
                        _make_moat_entry("data_advantages"),
                    ]
                }
            _make_artifact_dir(
                tmp,
                positioning_overrides={
                    "views": views,
                    "moat_assessments": moat_assessments,
                },
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            # 3 founder_override in positioning points (2 for _startup + 1 for alpha-corp y)
            # + 1 founder_override in moat assessments (_startup network_effects)
            # = 4 total
            assert data["metadata"]["founder_override_count"] == 4
            codes = [w["code"] for w in data["warnings"]]
            assert "FOUNDER_OVERRIDE_COUNT" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "FOUNDER_OVERRIDE_COUNT")
            assert warn["severity"] == "low"

    # 16. Report markdown has expected sections
    def test_compose_report_markdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            md = data["report_markdown"]
            assert "# Competitive Positioning Analysis" in md
            assert "TestCo" in md
            assert "## Executive Summary" in md
            assert "## Competitor Landscape" in md
            assert "## Positioning Analysis" in md
            assert "## Moat Assessment" in md
            assert "## Differentiation Stress-Test" in md
            assert "## Key Findings" in md
            assert "founder skills" in md
            assert "lool ventures" in md
            assert "Competitive Positioning Coach" in md

    # 17. Missing positioning.json -> MISSING_POSITIONING (high)
    def test_compose_missing_positioning_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_positioning=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            codes = [w["code"] for w in data["warnings"]]
            assert "MISSING_POSITIONING" in codes
            warn = next(w for w in data["warnings"] if w["code"] == "MISSING_POSITIONING")
            assert warn["severity"] == "high"

    # 18. Orphan slugs in positioning.json views/moat_assessments -> CORRUPT_ARTIFACT
    def test_compose_orphan_positioning_slug_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # positioning.json has an orphan slug in views[].points
            views = [
                {
                    "id": "primary",
                    "x_axis": {"name": "X", "description": "...", "rationale": "r"},
                    "y_axis": {"name": "Y", "description": "...", "rationale": "r"},
                    "points": [
                        _make_positioning_point("_startup", 90, 85),
                        _make_positioning_point("alpha-corp", 60, 40),
                        _make_positioning_point("beta-inc", 30, 70),
                        _make_positioning_point("gamma-ltd", 50, 50),
                        _make_positioning_point("delta-co", 20, 60),
                        _make_positioning_point("manual-process", 95, 15),
                        _make_positioning_point("orphan-view-slug", 70, 70),
                    ],
                }
            ]
            moat_assessments: dict[str, Any] = {}
            for slug in [
                "_startup",
                "alpha-corp",
                "beta-inc",
                "gamma-ltd",
                "delta-co",
                "manual-process",
                "orphan-moat-slug",
            ]:
                moat_assessments[slug] = {"moats": [_make_moat_entry("network_effects")]}
            _make_artifact_dir(
                tmp,
                positioning_overrides={
                    "views": views,
                    "moat_assessments": moat_assessments,
                },
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            messages = " ".join(w["message"] for w in data["warnings"])
            assert "orphan-view-slug" in messages
            assert "orphan-moat-slug" in messages

    # 18b. Slug-keyed points normalised; no spurious INCOMPLETE_SCORING
    def test_compose_normalizes_slug_key_points(self) -> None:
        """compose_report.py normalizes slug-keyed points; no spurious INCOMPLETE_SCORING."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc_base, data_base, _ = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc_base == 0
            assert data_base is not None
            base_incomplete = [w for w in data_base["warnings"] if w.get("code") == "INCOMPLETE_SCORING"]

        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            for view in positioning["views"]:
                for point in view["points"]:
                    point["slug"] = point.pop("competitor")
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            incomplete = [w for w in data["warnings"] if w.get("code") == "INCOMPLETE_SCORING"]
            assert len(incomplete) == len(base_incomplete), (
                f"Slug normalization failed: got {len(incomplete)} INCOMPLETE_SCORING "
                f"warnings vs {len(base_incomplete)} baseline. Warnings: {incomplete}"
            )

    # 18c. Array moat_assessments normalised; founder_override_count preserved
    def test_compose_normalizes_array_moat_assessments(self) -> None:
        """compose_report.py normalizes array moat_assessments; founder_override_count preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            first_slug = next(s for s in positioning["moat_assessments"] if s != "_startup")
            positioning["moat_assessments"][first_slug]["moats"][0]["evidence_source"] = "founder_override"
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc_base, data_base, _ = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc_base == 0
            assert data_base is not None
            base_override_count = data_base["metadata"]["founder_override_count"]
            assert base_override_count > 0, "Baseline must have at least one founder_override"

        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            first_slug = next(s for s in positioning["moat_assessments"] if s != "_startup")
            positioning["moat_assessments"][first_slug]["moats"][0]["evidence_source"] = "founder_override"
            dict_moats = positioning["moat_assessments"]
            array_moats = []
            for slug, company_data in dict_moats.items():
                entry = {"slug": slug}
                entry.update(company_data)
                array_moats.append(entry)
            positioning["moat_assessments"] = array_moats
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            actual_count = data["metadata"]["founder_override_count"]
            assert actual_count == base_override_count, (
                f"Array moat normalization failed: founder_override_count="
                f"{actual_count} vs baseline={base_override_count}"
            )

    # 19. INCOMPLETE_SCORING: landscape competitor missing from moat_scores
    def test_compose_incomplete_scoring_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # landscape has foo, but moat_scores.companies does not
            comps = [
                _make_competitor("Foo Corp", "foo", "direct"),
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            # moat_scores only has _startup and alpha-corp (no foo)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            incomplete = [w for w in data["warnings"] if w["code"] == "INCOMPLETE_SCORING"]
            assert len(incomplete) > 0, "Expected at least one INCOMPLETE_SCORING warning"
            assert all(w["severity"] == "medium" for w in incomplete)
            foo_warns = [w for w in incomplete if "foo" in w["message"]]
            # foo is missing from both moat_scores and positioning views
            assert len(foo_warns) >= 1, f"Expected INCOMPLETE_SCORING for 'foo', got: {incomplete}"

    # 19b. INCOMPLETE_SCORING founder_message: plain-language, reaches report.md
    def test_compose_incomplete_scoring_founder_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            comps = [
                _make_competitor("Foo Corp", "foo", "direct"),
                _make_competitor("Alpha Corp", "alpha-corp", "direct"),
                _make_competitor("Beta Inc", "beta-inc", "adjacent"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            foo_warns = [w for w in data["warnings"] if w["code"] == "INCOMPLETE_SCORING" and "foo" in w["message"]]
            assert len(foo_warns) >= 1
            for w in foo_warns:
                assert "founder_message" in w
                founder_msg = w["founder_message"]
                assert "moat_scores" not in founder_msg
                # Rendered with the display name substituted for the slug (see the shallow-profile
                # test above for why the substitution lives at the render boundary).
                rendered = founder_msg.replace("foo", "Foo Corp")
                assert rendered in data["report_markdown"]


class TestComposeRecentDevelopmentsSection:
    """The 'What's Changed Recently' report section renders dated + sourced
    recent_developments grouped by competitor, most recent first, and is
    omitted entirely (no heading at all) when no competitor has any."""

    def test_section_renders_when_data_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            comps = [
                _make_competitor(
                    "Alpha Corp",
                    "alpha-corp",
                    "direct",
                    recent_developments=[
                        _make_recent_development(
                            date="2026-03",
                            dev_type="funding",
                            summary="Raised a $20M Series B.",
                            source="https://example.com/news/series-b",
                        ),
                        _make_recent_development(
                            date="2025-11",
                            dev_type="leadership",
                            summary="New VP of Sales hired.",
                            source="https://example.com/news/vp-sales",
                        ),
                    ],
                ),
                _make_competitor("Beta Inc", "beta-inc", "direct"),
                _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
                _make_competitor("Delta Co", "delta-co", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(
                tmp,
                landscape_overrides={"competitors": comps, "landscape_as_of": "2026-06-15"},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            report = data["report_markdown"]
            assert "## What's Changed Recently" in report
            assert "Raised a $20M Series B." in report
            assert "New VP of Sales hired." in report
            assert "https://example.com/news/series-b" in report
            # Most recent first: 2026-03 entry must appear before the 2025-11 one.
            assert report.index("Raised a $20M Series B.") < report.index("New VP of Sales hired.")

    def test_section_absent_when_no_developments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)  # default competitors have no recent_developments
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            assert "What's Changed Recently" not in data["report_markdown"]

    def test_section_absent_when_all_developments_empty_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            comps = [
                _make_competitor("Alpha Corp", "alpha-corp", "direct", recent_developments=[]),
                _make_competitor("Beta Inc", "beta-inc", "direct", recent_developments=[]),
                _make_competitor("Gamma Ltd", "gamma-ltd", "adjacent"),
                _make_competitor("Delta Co", "delta-co", "emerging"),
                _make_competitor("Manual Process", "manual-process", "do_nothing"),
            ]
            _make_artifact_dir(tmp, landscape_overrides={"competitors": comps})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            assert "What's Changed Recently" not in data["report_markdown"]


class TestComposeScoringBasis:
    """compose_report.py must render the declared scoring basis with its human
    label, and 'Not declared' — never a silent default of 'shipped' — when the
    scored artifact never carries the field, in both report_markdown and
    report.json's scoring_summary."""

    def test_scoring_basis_not_declared_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)  # default positioning_scores has no scoring_basis key
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["scoring_summary"]["scoring_basis"] == "Not declared"
            assert "**Scoring Basis:** Not declared" in data["report_markdown"]

    def test_scoring_basis_shipped_label_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_scores_overrides={"scoring_basis": "shipped"})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["scoring_summary"]["scoring_basis"] == "Shipped / verifiable surface"
            assert "**Scoring Basis:** Shipped / verifiable surface" in data["report_markdown"]

    def test_scoring_basis_roadmap_12mo_label_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_scores_overrides={"scoring_basis": "roadmap_12mo"})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["scoring_summary"]["scoring_basis"] == "12-month roadmap"
            assert "**Scoring Basis:** 12-month roadmap" in data["report_markdown"]

    def test_scoring_basis_mixed_label_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_scores_overrides={"scoring_basis": "mixed"})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["scoring_summary"]["scoring_basis"] == "Mixed"
            assert "**Scoring Basis:** Mixed" in data["report_markdown"]


class TestComposeFounderOverrideUnion:
    """metadata.founder_override_count (and the FOUNDER_OVERRIDE_COUNT warning)
    must be the UNION of moat_scores.json and positioning.json's draft
    moat_assessments block, deduplicated by (slug, moat_id) — a founder moat
    override recorded in only one of the two sources must still be counted,
    and the same override present in both must be counted once, not twice."""

    def test_override_recorded_only_in_moat_scores_is_counted_even_when_draft_omits_the_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            ms_path = os.path.join(tmp, "moat_scores.json")
            with open(ms_path) as f:
                moat_scores = json.load(f)
            moat_scores["companies"]["alpha-corp"]["moats"][0]["evidence_source"] = "founder_override"
            with open(ms_path, "w") as f:
                json.dump(moat_scores, f)

            # SKILL.md now instructs writing {} or omitting moat_assessments in the
            # positioning.json draft entirely (it's superseded by moat_scores.json).
            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            del positioning["moat_assessments"]
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"compose must succeed with moat_assessments omitted: {stderr}"
            assert data is not None
            assert data["metadata"]["founder_override_count"] >= 1, (
                "a founder_override recorded only in moat_scores.json must be counted "
                "even when positioning.json omits moat_assessments entirely"
            )
            codes = [w["code"] for w in data["warnings"]]
            assert "FOUNDER_OVERRIDE_COUNT" in codes

    def test_override_recorded_only_in_positioning_draft_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)  # default moat_scores.json has no founder_override
            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            positioning["moat_assessments"]["alpha-corp"]["moats"][0]["evidence_source"] = "founder_override"
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["metadata"]["founder_override_count"] >= 1

    def test_same_override_present_in_both_sources_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            ms_path = os.path.join(tmp, "moat_scores.json")
            with open(ms_path) as f:
                moat_scores = json.load(f)
            moat_scores["companies"]["alpha-corp"]["moats"][0]["evidence_source"] = "founder_override"
            same_moat_id = moat_scores["companies"]["alpha-corp"]["moats"][0]["id"]
            with open(ms_path, "w") as f:
                json.dump(moat_scores, f)

            pos_path = os.path.join(tmp, "positioning.json")
            with open(pos_path) as f:
                positioning = json.load(f)
            for moat in positioning["moat_assessments"]["alpha-corp"]["moats"]:
                if moat["id"] == same_moat_id:
                    moat["evidence_source"] = "founder_override"
            with open(pos_path, "w") as f:
                json.dump(positioning, f)

            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert data["metadata"]["founder_override_count"] == 1, (
                f"the same (slug, moat_id) override present in both moat_scores.json and "
                f"positioning.json's draft must be counted ONCE, got "
                f"{data['metadata']['founder_override_count']}"
            )

    def test_compose_succeeds_when_moat_assessments_is_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, positioning_overrides={"moat_assessments": {}})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"compose must succeed when moat_assessments == {{}}: {stderr}"
            assert data is not None
            assert "Traceback" not in stderr


class TestScorePositioningValidation:
    """Additional validation tests for score_positioning.py."""

    # Malformed axis (missing name) exits 1
    def test_score_positioning_malformed_axis_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {},  # missing 'name'
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "name" in stderr.lower()

    # Duplicate competitor slugs within a view exits 1
    def test_score_positioning_duplicate_points_fails(self) -> None:
        views = [
            {
                "id": "primary",
                "x_axis": {"name": "X", "description": "...", "rationale": "x rationale"},
                "y_axis": {"name": "Y", "description": "...", "rationale": "y rationale"},
                "points": [
                    _make_positioning_point("_startup", 90, 85),
                    _make_positioning_point("acme-corp", 60, 40),
                    _make_positioning_point("acme-corp", 50, 50),  # duplicate
                    _make_positioning_point("beta-inc", 30, 70),
                ],
            }
        ]
        payload = _make_valid_positioning_input(views=views)
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}. stderr: {stderr}"
        assert "duplicate" in stderr.lower()


# ===========================================================================
# Validation gate tests — script provenance and self-grading detection
# ===========================================================================


class TestProvenanceStamps:
    """Tests for _produced_by provenance stamps in scoring scripts."""

    def test_score_moats_has_produced_by(self) -> None:
        payload = _make_valid_moat_input()
        rc, data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("_produced_by") == "score_moats"

    def test_score_positioning_has_produced_by(self) -> None:
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("_produced_by") == "score_positioning"

    def test_checklist_has_produced_by(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script("checklist.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("_produced_by") == "checklist"

    def test_validate_landscape_has_produced_by(self) -> None:
        payload = _make_valid_landscape()
        rc, data, stderr = run_script("validate_landscape.py", stdin_data=json.dumps(payload))
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data.get("_produced_by") == "validate_landscape"


class TestValidationGates:
    """Tests for compose_report.py validation gates."""

    def test_compose_unvalidated_artifact_warns(self) -> None:
        """Artifact without _produced_by triggers UNVALIDATED_ARTIFACT (high)."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite moat_scores.json without _produced_by
            ms = _make_moat_scores_artifact()
            # Ensure no _produced_by key
            ms.pop("_produced_by", None)
            with open(os.path.join(tmp, "moat_scores.json"), "w") as f:
                json.dump(ms, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            unval = [w for w in data["warnings"] if w["code"] == "UNVALIDATED_ARTIFACT"]
            assert len(unval) >= 1, (
                f"Expected UNVALIDATED_ARTIFACT warning, got: {[w['code'] for w in data['warnings']]}"
            )
            assert unval[0]["severity"] == "high"
            assert "moat_scores.json" in unval[0]["message"]

    def test_compose_checklist_all_pass_warns(self) -> None:
        """All-pass checklist triggers CHECKLIST_ALL_PASS (info)."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(
                tmp,
                checklist_overrides={
                    "fail_count": 0,
                    "warn_count": 0,
                    "pass_count": 23,
                    "na_count": 2,
                    "score_pct": 100.0,
                    "_produced_by": "checklist",
                },
            )
            # Also add _produced_by to other artifacts to avoid UNVALIDATED_ARTIFACT noise
            for fname, producer in [
                ("landscape.json", "validate_landscape"),
                ("moat_scores.json", "score_moats"),
                ("positioning_scores.json", "score_positioning"),
            ]:
                path = os.path.join(tmp, fname)
                with open(path) as f:
                    artifact = json.load(f)
                artifact["_produced_by"] = producer
                with open(path, "w") as f:
                    json.dump(artifact, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            all_pass = [w for w in data["warnings"] if w["code"] == "CHECKLIST_ALL_PASS"]
            assert len(all_pass) == 1, (
                f"Expected CHECKLIST_ALL_PASS warning, got: {[w['code'] for w in data['warnings']]}"
            )
            assert all_pass[0]["severity"] == "info"


# === v0.4.1 Phase 3 Task 8: compose on-disk verification + tolerant JSON extraction ===


def test_compose_verifies_outputs_exist_after_write(tmp_path: Any) -> None:
    """After successful compose, both report.json and report.md must exist on disk."""
    import pathlib

    review_dir = pathlib.Path(str(tmp_path)) / "cp-testco"
    review_dir.mkdir()
    _make_artifact_dir(str(review_dir))
    json_path = str(review_dir / "report.json")
    md_path = str(review_dir / "report.md")
    rc, _, err = run_script(
        "compose_report.py",
        ["-d", str(review_dir), "-o", json_path, "--write-md", md_path],
    )
    assert rc == 0, err
    assert os.path.isfile(json_path)
    assert os.path.isfile(md_path)
    assert os.path.getsize(json_path) > 0
    assert os.path.getsize(md_path) > 0


def test_compose_exits_nonzero_if_write_md_path_unwritable(tmp_path: Any) -> None:
    """Compose must exit nonzero if --write-md target dir doesn't exist and can't be created."""
    import pathlib

    review_dir = pathlib.Path(str(tmp_path)) / "cp-testco"
    review_dir.mkdir()
    _make_artifact_dir(str(review_dir))
    # Point --write-md at a path inside a read-only parent
    ro_parent = pathlib.Path(str(tmp_path)) / "readonly"
    ro_parent.mkdir(mode=0o555)
    bad_md_path = str(ro_parent / "no-write" / "report.md")
    json_path = str(review_dir / "report.json")
    rc, _, err = run_script(
        "compose_report.py",
        ["-d", str(review_dir), "-o", json_path, "--write-md", bad_md_path],
    )
    assert rc != 0, "compose should exit nonzero when --write-md target is unwritable"
    # Cleanup: restore writable mode so tmp_path can be deleted
    os.chmod(str(ro_parent), 0o755)


# === v0.4.1 Phase 3 Task 8: tolerant JSON extraction ===


def test_extract_dispatch_json_raw_object() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_dispatch_json_fenced() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_dispatch_json_nested() -> None:
    """Critical regression test: must not truncate on inner }."""
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = '```json\n{"a": {"b": 1}, "c": 2}\n```'
    assert extract_dispatch_json(text) == {"a": {"b": 1}, "c": 2}


def test_extract_dispatch_json_embedded_in_prose() -> None:
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = 'Here is the result:\n{"a": 1, "b": 2}\nLet me know if anything is wrong.'
    assert extract_dispatch_json(text) == {"a": 1, "b": 2}


def test_extract_dispatch_json_raises_when_no_json() -> None:
    import sys

    import pytest

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts"),
    )
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    with pytest.raises(ValueError):
        extract_dispatch_json("Just some prose with no JSON object anywhere.")


# ===========================================================================
# v0.4.2 Phase 1 Task 1: visualize.py tolerance for new + legacy checklist shapes
# ===========================================================================


def _run_visualize_raw(args: list[str]) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(CP_SCRIPTS_DIR, "visualize.py"), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


class TestVisualizeChecklistShapes:
    """Verify visualize.py works for both new (summary block) and legacy (flat) checklist artifacts."""

    def test_visualize_reads_summary_block(self) -> None:
        """visualize.py runs successfully when checklist.json has the new summary block."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite checklist.json with the new summary-block shape
            # (legacy flat fields kept too — additive).
            cl_summary_shape = {
                "items": [
                    {
                        "id": item_id,
                        "category": item_id.split("_")[0],
                        "label": f"Label for {item_id}",
                        "status": "pass",
                        "evidence": f"Evidence for {item_id}",
                    }
                    for item_id in CHECKLIST_IDS
                ],
                # New summary block — DIFFERENT value from the legacy flat field.
                # If compose accidentally falls through to the flat field, the assertion
                # below would see 88.0 (flat) instead of 91.0 (summary) and fail.
                "summary": {
                    "score_pct": 91.0,
                    "overall_status": "strong",
                    "total": 25,
                    "pass": 24,
                    "fail": 0,
                    "warn": 1,
                    "not_applicable": 0,
                    "failed_items": [],
                    "warned_items": [],
                },
                # Legacy flat fields (also present, but with a DIFFERENT score_pct
                # so we can distinguish which branch compose actually read).
                "score_pct": 88.0,
                "pass_count": 24,
                "fail_count": 0,
                "warn_count": 1,
                "na_count": 0,
                "total": 25,
                "input_mode": "conversation",
                "_produced_by": "checklist",
                "metadata": {"run_id": "20260319T143045Z"},
            }
            with open(os.path.join(tmp, "checklist.json"), "w") as f:
                json.dump(cl_summary_shape, f)

            # First compose so report.json exists (visualize uses it for the badge).
            rc_c, _, stderr_c = run_script(
                "compose_report.py",
                args=["--dir", tmp, "-o", os.path.join(tmp, "report.json")],
            )
            assert rc_c == 0, f"compose failed: {stderr_c}"
            # Compose must read score_pct from the summary block (91.0), NOT the
            # legacy flat field (88.0). This proves the summary-read branch is
            # exercised and the fallback isn't masking a regression.
            with open(os.path.join(tmp, "report.json")) as f:
                rep = json.load(f)
            assert rep["scoring_summary"]["checklist_score_pct"] == 91.0

            rc, html_out, stderr = _run_visualize_raw(["--dir", tmp])
            assert rc == 0, f"visualize failed (summary shape): {stderr}"
            assert "<html" in html_out.lower()
            assert "competitive positioning" in html_out.lower()

    def test_visualize_reads_legacy_flat_fields(self) -> None:
        """visualize.py runs successfully when checklist.json has only legacy flat fields (no summary block)."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite checklist.json with the legacy flat-only shape (no summary block).
            cl_legacy = {
                "items": [
                    {
                        "id": item_id,
                        "category": item_id.split("_")[0],
                        "label": f"Label for {item_id}",
                        "status": "pass",
                        "evidence": f"Evidence for {item_id}",
                    }
                    for item_id in CHECKLIST_IDS
                ],
                "score_pct": 75.0,
                "pass_count": 20,
                "fail_count": 2,
                "warn_count": 1,
                "na_count": 2,
                "total": 25,
                "input_mode": "conversation",
                "_produced_by": "checklist",
                "metadata": {"run_id": "20260319T143045Z"},
                # NOTE: no "summary" key — pre-Phase-1 artifact shape.
            }
            with open(os.path.join(tmp, "checklist.json"), "w") as f:
                json.dump(cl_legacy, f)

            # Compose first so the report.json badge data exists.
            rc_c, c_data, stderr_c = run_script(
                "compose_report.py", args=["--dir", tmp, "--pretty", "-o", os.path.join(tmp, "report.json")]
            )
            assert rc_c == 0, f"compose failed: {stderr_c}"
            # Compose must still pick up the legacy flat score_pct (fallback path).
            with open(os.path.join(tmp, "report.json")) as f:
                rep = json.load(f)
            assert rep["scoring_summary"]["checklist_score_pct"] == 75.0

            rc, html_out, stderr = _run_visualize_raw(["--dir", tmp])
            assert rc == 0, f"visualize failed (legacy shape): {stderr}"
            assert "<html" in html_out.lower()
            assert "competitive positioning" in html_out.lower()


# ---------------------------------------------------------------------------
# v0.4.2 Mitigation 2: coaching_payload + uuid insertion marker
# ---------------------------------------------------------------------------

# Helper: build a checklist.json artifact that includes the summary block
# (post-v0.4.2 shape) so coaching_payload has real data to draw from.


def _make_checklist_with_summary(
    *,
    run_id: str = "20260319T143045Z",
    fail: int = 0,
    warn: int = 0,
    failed_items: list[dict] | None = None,
    warned_items: list[dict] | None = None,
) -> dict:
    """Build a checklist.json artifact with a proper summary block."""
    items = []
    for item_id in CHECKLIST_IDS:
        items.append(
            {
                "id": item_id,
                "category": item_id.split("_")[0],
                "label": f"Label for {item_id}",
                "status": "pass",
                "evidence": f"Evidence for {item_id}",
            }
        )
    pass_count = 25 - fail - warn
    return {
        "items": items,
        "summary": {
            "score_pct": 92.0,
            "overall_status": "strong",
            "total": 25,
            "pass": pass_count,
            "fail": fail,
            "warn": warn,
            "not_applicable": 0,
            "failed_items": failed_items or [],
            "warned_items": warned_items or [],
        },
        "score_pct": 92.0,
        "pass_count": pass_count,
        "fail_count": fail,
        "warn_count": warn,
        "na_count": 0,
        "total": 25,
        "input_mode": "conversation",
        "_produced_by": "checklist",
        "metadata": {"run_id": run_id},
    }


def _make_v042_artifact_dir(
    checklist_overrides: dict | None = None,
) -> str:
    """Build a complete artifact dir with a summary-block checklist for v0.4.2 tests."""
    tmp = tempfile.mkdtemp()
    _make_artifact_dir(tmp)
    # Replace the checklist with a version that has a summary block.
    cl = _make_checklist_with_summary()
    if checklist_overrides:
        cl.update(checklist_overrides)
    with open(os.path.join(tmp, "checklist.json"), "w") as f:
        json.dump(cl, f)
    return tmp


def test_compose_emits_coaching_payload() -> None:
    """compose emits a coaching_payload block with all v0.4.2 fields."""
    import re

    d = _make_v042_artifact_dir()
    rc, data, err = run_script("compose_report.py", args=["--dir", d, "--pretty"])
    assert rc == 0, err
    assert data is not None
    assert "coaching_payload" in data, "report.json missing coaching_payload block"

    payload = data["coaching_payload"]
    assert payload["schema_version"] == "v0.4.2-competitive-positioning"

    # All expected top-level keys present
    for key in (
        "schema_version",
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "company_name",
        "review_dir",
        "report_path",
        "insertion_marker",
        # The coaching agent is asked for a defensibility roadmap while being
        # forbidden to read report.md. Without this it can only invent moat
        # claims, appended beside the real scored table in the same
        # investor-facing deliverable.
        "defensibility",
    ):
        assert key in payload, f"coaching_payload missing key: {key}"

    # No stage or is_ai_company (competitive-positioning has no analog)
    assert "stage" not in payload, "coaching_payload must not include 'stage'"
    assert "is_ai_company" not in payload, "coaching_payload must not include 'is_ai_company'"

    # Summary mirrors checklist counts
    s = payload["summary"]
    for sk in ("score_pct", "overall_status", "total", "pass", "fail", "warn", "not_applicable"):
        assert sk in s, f"coaching_payload.summary missing {sk}"

    # Company surfaced from product_profile
    assert payload["company_name"] == "TestCo"

    # Insertion marker matches uuid format
    assert re.fullmatch(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", payload["insertion_marker"]), (
        f"unexpected marker shape: {payload['insertion_marker']}"
    )

    # Backward-compat: existing top-level keys still present
    assert "report_markdown" in data
    assert "metadata" in data
    assert "warnings" in data


def test_compose_inserts_uuid_marker() -> None:
    """report.md contains exactly one uuid marker matching coaching_payload.insertion_marker."""
    import re

    d = _make_v042_artifact_dir()
    rc, data, err = run_script("compose_report.py", args=["--dir", d, "--pretty"])
    assert rc == 0, err
    assert data is not None

    md = data["report_markdown"]
    matches = re.findall(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", md)
    assert len(matches) == 1, f"expected exactly one marker, found {len(matches)}: {matches}"
    assert matches[0] == data["coaching_payload"]["insertion_marker"], (
        "marker in report_markdown must equal coaching_payload.insertion_marker"
    )


def test_compose_warns_on_marker_collision() -> None:
    """Body content containing the marker substring triggers MARKER_COLLISION (non-fatal)."""
    # Adversarial: inject the marker substring into the company name so it is rendered
    # verbatim in the report title and executive summary sections.
    adversarial_name = "TestCo <!-- COACHING_INSERTION_POINT_aaaaaaaa --> Ltd"

    tmp = tempfile.mkdtemp()
    _make_artifact_dir(tmp, product_profile_overrides={"company_name": adversarial_name})
    # Use a checklist with a summary block.
    cl = _make_checklist_with_summary()
    with open(os.path.join(tmp, "checklist.json"), "w") as f:
        json.dump(cl, f)

    rc, data, err = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
    # Compose still succeeds (warning, not error)
    assert rc == 0, err
    assert data is not None
    codes = [w["code"] for w in data["warnings"]]
    assert "MARKER_COLLISION" in codes, f"expected MARKER_COLLISION in warnings, got: {codes}"


def test_payload_arrays_match_summary_counts() -> None:
    """coaching_payload.failed_items length matches summary.fail; warned_items matches summary.warn."""
    failed_items = [
        {"id": CHECKLIST_IDS[0], "category": "COVER", "label": "L0", "evidence": "e"},
        {"id": CHECKLIST_IDS[1], "category": "COVER", "label": "L1", "evidence": "e"},
    ]
    warned_items = [
        {"id": CHECKLIST_IDS[2], "category": "COVER", "label": "L2", "evidence": "e"},
    ]
    cl = _make_checklist_with_summary(
        fail=2,
        warn=1,
        failed_items=failed_items,
        warned_items=warned_items,
    )
    cl["summary"]["score_pct"] = 88.0
    cl["summary"]["pass"] = 22

    tmp = tempfile.mkdtemp()
    _make_artifact_dir(tmp)
    with open(os.path.join(tmp, "checklist.json"), "w") as f:
        json.dump(cl, f)

    rc, data, err = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert len(payload["failed_items"]) == payload["summary"]["fail"] == 2
    assert len(payload["warned_items"]) == payload["summary"]["warn"] == 1


# ===========================================================================
# Audit regression tests (a4: competitive-positioning)
# ===========================================================================


class TestChecklistInputModeAndRunIdFlags:
    """checklist.py --input-mode / --run-id flags (audit cp-1, MAJOR).

    The CHECKLIST sub-agent returns items only. The main thread stamps the real
    input_mode and run_id via CLI flags so deck/document runs gate correctly and
    checklist.json carries a run_id for the Context B verifier.
    """

    def _items_only(self) -> str:
        payload = _make_valid_checklist_input(input_mode="deck")
        # Strip the fields the sub-agent must NOT supply.
        payload.pop("input_mode", None)
        payload.pop("metadata", None)
        return json.dumps(payload)

    def test_input_mode_flag_overrides_gating_for_deck(self) -> None:
        # Items-only input + --input-mode deck: NARR_03 stays active, EVID_04 gated.
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck"],
            stdin_data=self._items_only(),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["input_mode"] == "deck"
        by_id = {item["id"]: item for item in data["items"]}
        # Deck gates EVID_04 only — NARR_03 must remain active (deck cross-check applies).
        assert by_id["EVID_04"]["status"] == "not_applicable"
        assert by_id["NARR_03"]["status"] != "not_applicable"

    def test_missing_input_mode_flag_defaults_to_conversation(self) -> None:
        # Without --input-mode and without input_mode in JSON, default is conversation.
        rc, data, stderr = run_script("checklist.py", stdin_data=self._items_only())
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["input_mode"] == "conversation"

    def test_input_mode_flag_precedence_over_stdin(self) -> None:
        # CLI flag must win over the input_mode in the stdin JSON.
        payload = _make_valid_checklist_input(input_mode="conversation")
        payload.pop("metadata", None)
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "document"],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["input_mode"] == "document"
        by_id = {item["id"]: item for item in data["items"]}
        # document gates NARR_03 only, not EVID_04.
        assert by_id["NARR_03"]["status"] == "not_applicable"
        assert by_id["EVID_04"]["status"] != "not_applicable"

    def test_run_id_flag_stamps_metadata(self) -> None:
        # --run-id must populate result.metadata.run_id even with items-only input.
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck", "--run-id", "20260611T120000Z"],
            stdin_data=self._items_only(),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["metadata"].get("run_id") == "20260611T120000Z"

    def test_run_id_flag_overrides_stdin_metadata(self) -> None:
        # --run-id (CLI) wins over any metadata embedded in the stdin JSON.
        payload = _make_valid_checklist_input(run_id="STALE_FROM_STDIN")
        payload.pop("input_mode", None)
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--run-id", "AUTHORITATIVE"],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert data["metadata"].get("run_id") == "AUTHORITATIVE"

    def test_invalid_input_mode_flag_rejected(self) -> None:
        # argparse choices reject an unknown mode (exit 2).
        rc, _data, _stderr = run_script(
            "checklist.py",
            args=["--input-mode", "bogus"],
            stdin_data=self._items_only(),
        )
        assert rc == 2


class TestScoreMoatsNonStringEvidence:
    """score_moats.py must reject non-string evidence with a structured error,
    not a raw TypeError traceback (audit cp-scripts-5)."""

    def test_null_evidence_strong_status(self) -> None:
        payload = {
            "moat_assessments": {
                "_startup": {
                    "moats": [
                        {
                            "id": "network_effects",
                            "status": "strong",
                            "evidence": None,
                            "evidence_source": "researched",
                            "trajectory": "building",
                        }
                    ]
                }
            },
            "metadata": {"run_id": "20260611T120000Z"},
        }
        rc, _data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}"
        assert "must be a string" in stderr
        assert "Traceback" not in stderr

    def test_numeric_evidence_estimated_confidence(self) -> None:
        payload = {
            "moat_assessments": {
                "_startup": {
                    "moats": [
                        {
                            "id": "network_effects",
                            "status": "moderate",
                            "evidence": 42,
                            "evidence_source": "agent_estimate",
                            "trajectory": "stable",
                        }
                    ]
                }
            },
            "data_confidence": "estimated",
            "metadata": {"run_id": "20260611T120000Z"},
        }
        rc, _data, stderr = run_script("score_moats.py", stdin_data=json.dumps(payload))
        assert rc == 1, f"Expected exit 1, got {rc}"
        assert "must be a string" in stderr
        assert "Traceback" not in stderr


class TestComposeNonDictArtifact:
    """compose_report.py must flag a top-level-array artifact as CORRUPT_ARTIFACT,
    not crash with AttributeError (audit cp-scripts-2)."""

    def test_array_landscape_degrades_to_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            # Overwrite landscape.json with a top-level JSON array.
            with open(os.path.join(tmp, "landscape.json"), "w") as f:
                f.write('["not", "a", "dict"]')
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert "Traceback" not in stderr
            assert data is not None
            codes = {w["code"] for w in data["warnings"]}
            assert "CORRUPT_ARTIFACT" in codes

    def test_array_artifact_blocks_under_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            with open(os.path.join(tmp, "positioning.json"), "w") as f:
                f.write("[1, 2, 3]")
            rc, _data, stderr = run_script(
                "compose_report.py",
                args=["--dir", tmp, "--strict", "-o", os.path.join(tmp, "report.json")],
            )
            assert "Traceback" not in stderr
            assert rc == 1


class TestComposeExecutiveSummaryStrongThreshold:
    """The executive-summary 'strong' label and 'strong differentiation' paragraph
    must use the same >=75 threshold (audit cp-scripts-3). A score in [70, 75)
    labelled Moderate must not be described as strong in the paragraph below."""

    def test_score_72_not_described_as_strong(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"overall_differentiation": 72.0},
                moat_scores_overrides=None,
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            md = data["report_markdown"]
            # The score label for 72 is "Moderate"; the paragraph must not call it strong.
            assert "Moderate — differentiated but the lead is narrow" in md
            assert "strong competitive differentiation" not in md

    def test_score_80_still_described_as_strong(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"overall_differentiation": 80.0},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            assert data is not None
            assert "strong competitive differentiation" in data["report_markdown"]


class TestComposeNonStringViewId:
    """compose_report.py _section_positioning must coerce a non-string view_id
    rather than crash on .title() (audit cp-scripts-7)."""

    def test_numeric_view_id_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            ps_path = os.path.join(tmp, "positioning_scores.json")
            with open(ps_path) as f:
                ps = json.load(f)
            if ps.get("views"):
                ps["views"][0]["view_id"] = 42
            with open(ps_path, "w") as f:
                json.dump(ps, f)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert "Traceback" not in stderr
            assert data is not None


class TestComposeMergeIntegrity:
    """compose_report.py must cross-check positioning.json points against the
    points passed through positioning_scores.json (finding 35): score_positioning.py
    passes each view's input points straight through unmodified, so
    positioning_scores.json is the authoritative post-scoring coordinate record.
    positioning.json is supposed to be hand-merged to match it; a skipped or
    partial merge must be caught (CORRUPT_ARTIFACT, high, blocking under --strict)
    rather than silently composing a report over stale/placeholder coordinates.
    """

    _PRIMARY_POINTS = [
        _make_positioning_point("_startup", 90, 85),
        _make_positioning_point("alpha-corp", 60, 40),
        _make_positioning_point("beta-inc", 30, 70),
        _make_positioning_point("gamma-ltd", 50, 50),
        _make_positioning_point("delta-co", 20, 60),
        _make_positioning_point("manual-process", 95, 15),
    ]

    @staticmethod
    def _scores_view(points: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "view_id": "primary",
            "x_axis_name": "Deployment Speed",
            "y_axis_name": "Detection Accuracy",
            "x_axis_rationale": "Key differentiator for SMBs",
            "y_axis_rationale": "Table-stakes dimension",
            "x_axis_vanity_flag": False,
            "y_axis_vanity_flag": False,
            "differentiation_score": 75.0,
            "startup_x_rank": 1,
            "startup_y_rank": 3,
            "competitor_count": 5,
            "points": points,
        }

    def _mismatch_codes_and_messages(self, tmp: str) -> tuple[list[str], str]:
        rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
        assert data is not None
        assert "Traceback" not in stderr
        codes = [w["code"] for w in data["warnings"]]
        messages = " ".join(w["message"] for w in data["warnings"])
        return codes, messages

    # 1. Fully stale merge — every competitor still at draft coordinates
    def test_full_mismatch_produces_blocking_corrupt_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scores_points = [_make_positioning_point(p["competitor"], 1, 1) for p in self._PRIMARY_POINTS]
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": [self._scores_view(scores_points)]},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            merge_warnings = [w for w in data["warnings"] if "differ from positioning_scores.json" in w["message"]]
            assert merge_warnings, f"Expected a merge-integrity warning, got: {data['warnings']}"
            warn = merge_warnings[0]
            assert warn["code"] == "CORRUPT_ARTIFACT"
            assert warn["severity"] == "high"
            for slug in ("alpha-corp", "beta-inc", "gamma-ltd", "delta-co", "manual-process"):
                assert slug in warn["message"]

            # High severity blocks under --strict
            rc_strict, _out, stderr_strict = run_script(
                "compose_report.py", args=["--dir", tmp, "--pretty", "--strict"]
            )
            assert rc_strict == 1, f"Expected --strict to block on a merge mismatch. stderr: {stderr_strict}"

    # 2. Correctly merged — points match exactly -> no false positive
    def test_matching_points_compose_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": [self._scores_view(list(self._PRIMARY_POINTS))]},
            )
            codes, messages = self._mismatch_codes_and_messages(tmp)
            assert "differ from positioning_scores.json" not in messages
            assert not [c for c in codes if c == "CORRUPT_ARTIFACT"]

    # 3. Partial merge — one competitor updated, one left stale
    def test_partial_merge_catches_only_stale_competitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scores_points = [dict(p) for p in self._PRIMARY_POINTS]
            for p in scores_points:
                if p["competitor"] == "gamma-ltd":
                    p["x"], p["y"] = 99, 99  # this one was never merged back
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": [self._scores_view(scores_points)]},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert data is not None
            merge_warnings = [w for w in data["warnings"] if "differ from positioning_scores.json" in w["message"]]
            assert len(merge_warnings) == 1, f"Expected exactly one merge warning, got: {merge_warnings}"
            msg = merge_warnings[0]["message"]
            assert "gamma-ltd" in msg
            for slug in ("alpha-corp", "beta-inc", "delta-co", "manual-process"):
                assert slug not in msg

    # 4. positioning_scores.json view with no points at all -> degrade explicitly
    def test_missing_points_in_scores_view_degrades_without_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scores_view = self._scores_view([])
            del scores_view["points"]
            _make_artifact_dir(
                tmp,
                positioning_scores_overrides={"views": [scores_view]},
            )
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"
            assert "Traceback" not in stderr
            assert data is not None
            messages = " ".join(w["message"] for w in data["warnings"])
            assert "differ from positioning_scores.json" not in messages


class TestValidateLandscapeNoStdinFlag:
    """validate_landscape.py must no longer expose the dead --stdin flag
    (audit cp-scripts-9)."""

    def test_stdin_flag_removed(self) -> None:
        rc, _stdout, stderr = run_script_raw(
            "validate_landscape.py",
            args=["--stdin"],
            stdin_data=json.dumps(_make_valid_landscape()),
        )
        # Unknown flag → argparse exit 2 + "unrecognized arguments".
        assert rc == 2
        assert "unrecognized arguments" in stderr or "--stdin" in stderr


# === run_id CLI stamping (alignment with the cross-skill contract) ===


class TestRunIdStamping:
    """All three passthrough producers accept --run-id; CLI value is stamped
    into metadata.run_id and overrides any run_id from stdin metadata
    (CLI > stdin), so the Context B run_id-parity check holds even when the
    sub-agent omits or misreports metadata."""

    def test_validate_landscape_cli_run_id_overrides_stdin(self) -> None:
        payload = _make_valid_landscape()
        payload["metadata"] = {"run_id": "STDIN"}
        rc, data, stderr = run_script("validate_landscape.py", ["--run-id", "CLI-WINS"], stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None and data["metadata"]["run_id"] == "CLI-WINS"

    def test_score_moats_cli_run_id_stamped_when_stdin_absent(self) -> None:
        payload = _make_valid_moat_input()
        payload.pop("metadata", None)
        rc, data, stderr = run_script("score_moats.py", ["--run-id", "CLI-ONLY"], stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None and data["metadata"]["run_id"] == "CLI-ONLY"

    def test_score_positioning_cli_run_id_overrides_stdin(self) -> None:
        payload = _make_valid_positioning_input()
        payload["metadata"] = {"run_id": "STDIN"}
        rc, data, stderr = run_script("score_positioning.py", ["--run-id", "CLI-WINS"], stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None and data["metadata"]["run_id"] == "CLI-WINS"


# ===========================================================================
# Artifact self-sufficiency — items 1, 2, 3
# ===========================================================================


class TestComposePositioningPointsTable:
    """compose_report.py _section_positioning renders per-view points evidence table (item 1)."""

    def test_points_table_rendered_in_positioning_section(self) -> None:
        """Evidence coordinates from positioning.json views[].points appear in the report.

        Column headers come from positioning_scores.json (x_axis_name / y_axis_name);
        the points evidence text comes from positioning.json views[].points.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # positioning.json: provide evidence-rich points under the "primary" view
            views_with_evidence = [
                {
                    "id": "primary",
                    "x_axis": {
                        "name": "Deployment Speed",
                        "description": "How fast",
                        "rationale": "Key differentiator",
                    },
                    "y_axis": {
                        "name": "Detection Accuracy",
                        "description": "Accuracy",
                        "rationale": "Table-stakes",
                    },
                    "points": [
                        {
                            "competitor": "_startup",
                            "x": 90,
                            "y": 85,
                            "x_evidence": "Deploys in under 5 minutes per benchmark",
                            "y_evidence": "All data stored on-prem per architecture docs",
                            "x_evidence_source": "researched",
                            "y_evidence_source": "researched",
                        },
                        {
                            "competitor": "alpha-corp",
                            "x": 60,
                            "y": 40,
                            "x_evidence": "Alpha Corp requires 2-day setup",
                            "y_evidence": "Alpha Corp uses cloud storage",
                            "x_evidence_source": "researched",
                            "y_evidence_source": "researched",
                        },
                    ],
                }
            ]
            _make_artifact_dir(tmp, positioning_overrides={"views": views_with_evidence})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"compose failed: {stderr}"
            assert data is not None
            md = data["report_markdown"]
            # Column headers come from positioning_scores.json axis names (fixture defaults)
            assert "Deployment Speed" in md, "x-axis name should appear in points table header"
            assert "Detection Accuracy" in md, "y-axis name should appear in points table header"
            # Evidence text for at least one point
            assert "Deploys in under 5 minutes" in md or "alpha-corp" in md, (
                "Evidence text or competitor slug should appear in points table"
            )
            # x/y coordinates
            assert "90" in md and "85" in md, "Coordinate values should appear in points table"

    def test_points_table_not_rendered_without_positioning(self) -> None:
        """No crash when positioning.json is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp, include_positioning=False)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert "Traceback" not in stderr
            assert data is not None

    def test_evidence_truncated_at_120_chars(self) -> None:
        """Evidence strings longer than 120 chars are truncated in the table."""
        with tempfile.TemporaryDirectory() as tmp:
            long_evidence = "A" * 200 + " end"
            views_with_long = [
                {
                    "id": "primary",
                    "x_axis": {"name": "Speed", "description": "d", "rationale": "r"},
                    "y_axis": {"name": "Privacy", "description": "d", "rationale": "r"},
                    "points": [
                        {
                            "competitor": "_startup",
                            "x": 90,
                            "y": 85,
                            "x_evidence": long_evidence,
                            "y_evidence": "short",
                            "x_evidence_source": "researched",
                            "y_evidence_source": "researched",
                        },
                    ],
                }
            ]
            _make_artifact_dir(tmp, positioning_overrides={"views": views_with_long})
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            md = data["report_markdown"]  # type: ignore[index]
            # The " end" suffix beyond 120 chars should NOT appear
            assert " end" not in md, "Evidence beyond 120 chars should be truncated"
            # But some of the evidence should appear
            assert "AAAA" in md, "Truncated evidence prefix should appear"


class TestComposeMoatEvidenceAndLeader:
    """compose_report.py _section_moat_assessment renders evidence text and leader context (items 2-3)."""

    def test_moat_evidence_text_appears_in_report(self) -> None:
        """Moat evidence text appears as bullets under the moat table."""
        with tempfile.TemporaryDirectory() as tmp:
            # Build moat_scores with evidence on the _startup moats
            ms = _make_moat_scores_artifact()
            ms["companies"]["_startup"]["moats"] = [
                {
                    "id": "network_effects",
                    "status": "strong",
                    "evidence": "Has 50K active users sharing data; network value grows with square of users",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "Integration depth locks in enterprise workflows",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
            ]
            # Add other moats missing from CANONICAL to avoid MISSING_CANONICAL warnings failing the test
            for m_id in ["data_advantages", "regulatory_barriers", "cost_structure", "brand_reputation"]:
                ms["companies"]["_startup"]["moats"].append(
                    {
                        "id": m_id,
                        "status": "weak",
                        "evidence": "Limited.",
                        "evidence_source": "agent_estimate",
                        "trajectory": "stable",
                    }
                )
            _make_artifact_dir(tmp, moat_scores_overrides=ms)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, f"compose failed: {stderr}"
            md = data["report_markdown"]  # type: ignore[index]
            assert "50K active users" in md, "Moat evidence text should appear in report"
            assert "Integration depth" in md, "Second moat evidence text should appear in report"

    def test_moat_ranking_shows_leader_context(self) -> None:
        """Leader name and status appear in the startup ranking section."""
        with tempfile.TemporaryDirectory() as tmp:
            ms = _make_moat_scores_artifact()
            # alpha-corp is stronger in network_effects → _startup is rank 2
            _make_artifact_dir(tmp, moat_scores_overrides=ms)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            md = data["report_markdown"]  # type: ignore[index]
            # Rank line must mention the leader when _startup is not rank 1
            assert "leader:" in md or "alpha-corp" in md, "Leader context should appear in moat ranking section"

    def test_moat_dimension_matrix_rendered(self) -> None:
        """Per-dimension comparison matrix with company rows appears in report."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_artifact_dir(tmp)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            md = data["report_markdown"]  # type: ignore[index]
            # Matrix section header
            assert "Moat Dimension Comparison Matrix" in md, "Matrix section should appear"
            # Legend
            assert "S=Strong" in md, "Legend line should appear"
            # _startup row marker
            assert "_startup_" in md, "_startup row should appear in matrix"

    def test_moat_matrix_uses_status_initials(self) -> None:
        """Status initials (S/M/W/—) appear in the matrix rows."""
        with tempfile.TemporaryDirectory() as tmp:
            ms = _make_moat_scores_artifact()
            # Give _startup a 'strong' data_advantages so S appears
            for moat in ms["companies"]["_startup"]["moats"]:
                if moat["id"] == "data_advantages":
                    moat["status"] = "strong"
            _make_artifact_dir(tmp, moat_scores_overrides=ms)
            rc, data, stderr = run_script("compose_report.py", args=["--dir", tmp, "--pretty"])
            assert rc == 0, stderr
            md = data["report_markdown"]  # type: ignore[index]
            assert " S " in md or "| S " in md or " S|" in md, (
                "Status initial 'S' should appear in the matrix for strong moat"
            )


# ===========================================================================
# SKILL.md / agent.md / artifact-schemas.md contract tests
#
# These lock in guidance/template fixes that behavior tests can't reach —
# the *content* of what the main thread and sub-agent are told to do.
# ===========================================================================


def test_skill_md_step0_uses_resolver_for_agent_paths() -> None:
    """Step 0 must derive HANDOFF_AGENT/ANALYSIS_DIR_AGENT via resolve_artifacts_root.py's
    --handoff-dir-agent / --analysis-dir-agent flags, not by hand-splicing the printed
    AGENT_ARTIFACTS_ROOT with a free-form skill-name/slug/run-id string — the same class of
    non-determinism the script was built to remove for the bare artifacts root."""
    skill_md = _read(CP_SKILL_MD)
    # Anchor without the trailing punctuation — the sentence continues differently
    # now that the block routes between modes, and the assertion is about what the
    # block contains, not how its lead-in is punctuated.
    start = skill_md.index("After Step 1 (when the slug is known)")
    end = skill_md.index("### Step 1: Read or Create Founder Context")
    block = skill_md[start:end]
    assert "--handoff-dir-agent" in block, "Step 0 should compute HANDOFF_AGENT via the resolver, not hand-splice it"
    assert "--analysis-dir-agent" in block, (
        "Step 0 should compute ANALYSIS_DIR_AGENT via the resolver, not hand-splice it"
    )


def test_skill_md_step1_lists_full_stage_enum() -> None:
    """Step 1's founder_context.py init example must inline the full --stage enum so the
    agent doesn't guess a token (e.g. 'seriesa') and hit an argparse error/retry — same fix
    already applied to market-sizing's Step 1."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Step 2: Build Product Profile")
    block = skill_md[start:end]
    for stage in ("pre-seed", "seed", "series-a", "series-b", "series-c", "series-d", "later"):
        assert stage in block, f"--stage enum value '{stage}' not inlined in Step 1"


def test_skill_md_step1_carveout_is_non_binary() -> None:
    """Step 1's deck/materials carve-out must derive the four basics field-by-field,
    NOT all-or-nothing: deriving three and missing one must not send the agent back to
    asking for all four. A missing-but-implied field should be inferred from a clear
    signal (geography from a phone country code, stage from a fundraise signal, etc.)
    rather than gated, and AskUserQuestion must be reserved for only the genuinely
    underivable field(s). Regression guard: the prior binary wording ('fall back to
    AskUserQuestion when one or more cannot be derived') made a single un-derivable
    field (an unstated geography behind a +972 phone) re-gate all four."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Step 2: Build Product Profile")
    block = skill_md[start:end].lower()
    # Non-binary: the four basics are treated independently.
    assert any(phrase in block for phrase in ("field-by-field", "independently", "never all-or-nothing")), (
        "Step 1 carve-out must state the four basics are derived independently (non-binary)"
    )
    # Ask only for the missing field(s), not all four.
    assert "only those" in block or "only the missing" in block or "only for" in block, (
        "Step 1 carve-out must instruct asking AskUserQuestion for only the underivable field(s)"
    )
    # Ambiguous-signal inference heuristic (derive-then-proceed instead of gating).
    assert "infer" in block, "Step 1 carve-out must describe inferring a missing field from a signal"
    assert "+972" in block or "phone country code" in block or "fundraise signal" in block, (
        "Step 1 carve-out must give a concrete inference signal (e.g. phone country code, fundraise signal)"
    )


def test_skill_md_step1_lists_sector_type_enum() -> None:
    """Step 1 must also mention --sector-type and its enum so the agent knows the override
    exists before hitting the runtime 'set explicitly with --sector-type' warning."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 1: Read or Create Founder Context")
    end = skill_md.index("### Step 2: Build Product Profile")
    block = skill_md[start:end]
    assert "--sector-type" in block
    for sector_type in ("saas", "ai-native", "marketplace", "hardware", "hardware-subscription"):
        assert sector_type in block, f"--sector-type enum value '{sector_type}' not inlined in Step 1"


def test_skill_md_find_artifact_has_example_invocation() -> None:
    """Step 7b's cross-skill lookup must show a concrete find_artifact.py invocation
    (with --skill and --artifact) so the agent doesn't guess the wrong flags."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("**7b — Cross-skill lookups:**")
    end = skill_md.index("**7c", start)
    block = skill_md[start:end]
    assert "--skill" in block and "--artifact" in block, (
        "Step 7b must include an example find_artifact.py invocation with --skill/--artifact"
    )


def test_skill_md_declined_additions_recorded() -> None:
    """Step 4 must state that declined suggested_additions are retained (not discarded),
    so the gap-detection knowledge persists into landscape.json instead of being lost."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 4: Research & Enrich Competitors")
    end = skill_md.index("### Step 5", start)
    block = skill_md[start:end].lower()
    assert "declined" in block or "not approved" in block, (
        "Step 4 must address recording/retaining declined suggested_additions"
    )


def test_skill_md_moat_scoring_dispatch_requires_source_citation() -> None:
    """The MOAT_SCORING dispatch prompt must tell the sub-agent to attach a source (URL or
    search query) beside every evidence_source:'researched' moat, matching score_moats.py's
    (warn-only) RESEARCHED_WITHOUT_SOURCE check."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("**MOAT_SCORING dispatch prompt:**")
    end = skill_md.index("**POSITIONING_SCORING dispatch prompt:**")
    block = skill_md[start:end]
    assert "source" in block.lower()
    assert '"source"' in block, "MOAT_SCORING template should show the 'source' field in its JSON example"


def test_skill_md_landscape_research_dispatch_requires_source_citation() -> None:
    """The LANDSCAPE_RESEARCH dispatch prompt must tell the sub-agent to attach a 'sources'
    citation dict beside per-field evidence_source:'researched' values, matching
    validate_landscape.py's (warn-only) RESEARCHED_WITHOUT_SOURCE check."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 4: Research & Enrich Competitors")
    end = skill_md.index("### Gate 2: Founder Validation of Axis Selection")
    block = skill_md[start:end]
    assert '"sources"' in block, "LANDSCAPE_RESEARCH template should show the 'sources' field in its JSON example"


def test_agent_md_moat_scoring_subtype_requires_source_citation() -> None:
    agent_md = _read(CP_AGENT_MD)
    start = agent_md.index("#### MOAT_SCORING subtype")
    end = agent_md.index("#### POSITIONING_SCORING subtype")
    block = agent_md[start:end]
    assert "source" in block.lower()
    assert '"source"' in block


def test_agent_md_landscape_research_subtype_requires_source_citation() -> None:
    agent_md = _read(CP_AGENT_MD)
    start = agent_md.index("#### LANDSCAPE_RESEARCH subtype")
    end = agent_md.index("#### COMPETITOR_VERIFICATION subtype")
    block = agent_md[start:end]
    assert '"sources"' in block


def test_skill_md_step5_documents_positioning_json_points_merge() -> None:
    """After piping the POSITIONING_SCORING hand-off through score_positioning.py, SKILL.md
    must explicitly instruct the main thread to carry the sub-agent's assigned coordinates
    back into positioning.json's views[].points[] (the draft written before dispatch was a
    placeholder) — otherwise nothing ever updates the file compose_report.py/visualize.py/
    explore.py actually read points from."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 5: Positioning & Moat Assessment")
    end = skill_md.index("### Step 6: Score Checklist")
    block = skill_md[start:end]
    assert "merge" in block.lower(), "Step 5 must document the points merge-back into positioning.json"
    assert "positioning.json" in block


def test_skill_md_states_mechanical_fix_vs_content_authoring_carve_out() -> None:
    """The 'main thread must not author analytical content' rule needs an explicit carve-out
    for MECHANICAL fixes (schema near-miss renames, merging a sub-agent's own coordinates back
    into positioning.json) — otherwise the blanket rule reads as forbidding the Step 5 points
    merge and the producers' own auto-normalization too."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Context A hand-off protocol")
    end = skill_md.index("### Step 4: Research & Enrich Competitors")
    block = skill_md[start:end]
    assert "mechanical" in block.lower(), "Expected an explicit mechanical-fix-vs-content-authoring carve-out"


def test_skill_md_step4_additions_gate_uses_two_step_protocol() -> None:
    """The Step 4 suggested_additions mini-gate must follow the same two-step (chat message
    THEN AskUserQuestion) pattern Gates 1 and 2 use, or explicitly say it's an inline prompt —
    plain prose left the format to guesswork."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 4: Research & Enrich Competitors")
    end = skill_md.index("### Gate 2: Founder Validation of Axis Selection")
    block = skill_md[start:end]
    assert "MANDATORY STOP" in block or "inline prompt" in block.lower(), (
        "Step 4's suggested_additions mini-gate must either use the two-step gate protocol "
        "or explicitly state it's an inline (non-hard-gate) prompt"
    )


def test_skill_md_step2_flags_stale_source_vintage() -> None:
    """Step 2 should tell the agent to flag a deck/source whose copyright or vintage predates
    the analysis by a wide margin — competitor data from a stale deck may already be outdated."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 2: Build Product Profile")
    end = skill_md.index("### Step 3: Identify Competitors")
    block = skill_md[start:end]
    assert any(kw in block.lower() for kw in ("vintage", "stale", "copyright date", "outdated")), (
        "Step 2 should mention flagging stale source-material vintage to the founder"
    )


def test_agent_md_context_b_writes_raw_markdown_not_json() -> None:
    """R2 coaching-transport fix (supersedes the old escaped-JSON guardrail
    this test used to assert): the Context B commentary hand-off is now RAW
    markdown, written directly with the Write tool — the JSON transport
    envelope is built deterministically by md_to_commentary.py on the main
    thread, not hand-escaped by the sub-agent. See
    test_agent_coaching_writes_raw_markdown_no_json_escaping for the full
    assertion set."""
    agent_md = _read(CP_AGENT_MD)
    start = agent_md.index("### Context B — Post-compose coaching dispatch")
    end = agent_md.index("## Core Principles")
    block = agent_md[start:end]
    assert "plain markdown" in block.lower()
    assert "single pass" not in block.lower()


def test_artifact_schemas_documents_moat_source_field() -> None:
    schemas = _read(CP_ARTIFACT_SCHEMAS_MD)
    start = schemas.index("### moats[] entry")
    end = schemas.index("### differentiation_claims[] entry")
    block = schemas[start:end]
    assert "`source`" in block or "| `source` " in block


def test_artifact_schemas_documents_competitor_sources_field() -> None:
    schemas = _read(CP_ARTIFACT_SCHEMAS_MD)
    assert "`sources`" in schemas or "| `sources` " in schemas


def test_artifact_schemas_documents_researched_without_source_code() -> None:
    schemas = _read(CP_ARTIFACT_SCHEMAS_MD)
    start = schemas.index("## Warning Severity Reference")
    block = schemas[start:]
    assert "RESEARCHED_WITHOUT_SOURCE" in block


def test_skill_md_step2_deck_mode_notes_large_pdf_page_ranges() -> None:
    """The Read tool refuses a >10-page PDF without an explicit page range (max 20 pages per
    call) — Step 2's 'read ALL pages systematically' instruction should say to chunk large
    decks into page-range reads instead of leaving the agent to discover the limit at runtime."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 2: Build Product Profile")
    end = skill_md.index("### Step 3: Identify Competitors")
    block = skill_md[start:end]
    assert "page" in block.lower() and ("range" in block.lower() or "chunk" in block.lower()), (
        "Step 2 should mention reading large decks in page-range chunks"
    )


# ============================================================
# R2 coaching-transport fix: raw-markdown Context-B pipe
# ============================================================


def test_skill_md_coaching_pipe_uses_format_markdown_adapter() -> None:
    """R2 coaching-transport fix: Step 7c's Context-B pipe must gate the raw
    .md hand-off with check_handoff.py --format=markdown and transform it
    through the shared md_to_commentary.py adapter before insert_coaching.py
    — never hand the sub-agent a JSON-escaping burden."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 7: Compose, Validate, and Post-Compose Coaching")
    end = skill_md.index("### Step 8: Deliver Artifacts")
    step7 = skill_md[start:end]
    assert "--format=markdown" in step7
    assert "md_to_commentary.py" in step7
    assert "OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md" in step7
    assert "coaching_commentary_output.json" not in step7


def test_skill_md_coaching_exit7_repair_dispatch() -> None:
    """The content-shape gate's new exit 7 (shape-invalid: receipt-shaped or
    marker-bearing hand-off) must branch to a repair-dispatch, mirroring the
    other typed exits."""
    skill_md = _read(CP_SKILL_MD)
    start = skill_md.index("### Step 7: Compose, Validate, and Post-Compose Coaching")
    end = skill_md.index("### Step 8: Deliver Artifacts")
    step7 = skill_md[start:end]
    assert "Exit 7" in step7
    assert "repair-dispatch" in step7.lower()
    idx = step7.index("Exit 7")
    window = step7[idx : idx + 300].lower()
    assert "coaching commentary" in window or "coaching markdown" in window


def test_agent_coaching_writes_raw_markdown_no_json_escaping() -> None:
    """R2 coaching-transport fix: agents/competitive-positioning.md's Context B
    section must instruct the sub-agent to write RAW markdown (no JSON
    envelope, no hand-escaping) — the escaping moves into
    md_to_commentary.py's json.dumps, which cannot emit malformed JSON. The
    old 'escape every newline as \\n / every quote as \\"' guardrail (the
    thing that broke ~17-22% of the time) must be gone."""
    agent_body = _read(CP_AGENT_MD)
    idx = agent_body.index("### Context B")
    section = agent_body[idx : idx + 4000]
    assert "plain markdown" in section.lower()
    assert "do not escape anything" in section.lower() or "do not escape" in section.lower()
    assert "escaped as `\\n`" not in agent_body
    assert 'escaped as `\\"`' not in agent_body
    assert "no pretty-print" not in agent_body.lower()


# ---------------------------------------------------------------------------
# Defensibility payload + the moat_count doc-vs-code contract
# ---------------------------------------------------------------------------


def test_coaching_payload_carries_scored_moat_data() -> None:
    """The defensibility block must hold real scores, not placeholders.

    The coaching agent is asked "which moats to invest in, in what order" and is
    forbidden to read report.md. Every field it needs to answer that has to be in
    the payload, or the only way to comply is to make the numbers up — and the
    commentary lands in the same report as the scored table.
    """
    d = _make_v042_artifact_dir()
    rc, data, err = run_script("compose_report.py", args=["--dir", d, "--pretty"])
    assert rc == 0, err
    assert data is not None

    defensibility = data["coaching_payload"]["defensibility"]
    for key in ("moat_count", "strongest_moat", "overall_defensibility", "moats"):
        assert key in defensibility, f"defensibility missing {key}"

    assert isinstance(defensibility["moats"], list)
    assert defensibility["moats"], "per-dimension statuses are required to order a roadmap"
    for moat in defensibility["moats"]:
        assert set(moat) == {"id", "status"}, f"unexpected moat shape: {moat}"
        assert moat["status"] in ("strong", "moderate", "weak", "absent", "not_applicable")

    # Values must be read from moat_scores.json, not invented by compose.
    with open(os.path.join(d, "moat_scores.json")) as f:
        startup = json.load(f)["companies"]["_startup"]
    assert defensibility["moat_count"] == startup["moat_count"]
    assert defensibility["overall_defensibility"] == startup["overall_defensibility"]
    assert defensibility["strongest_moat"] == startup["strongest_moat"]


def test_skill_md_moat_count_definition_matches_score_moats() -> None:
    """SKILL.md's stated moat_count rule must match what score_moats.py computes.

    This drifted: SKILL.md said "dimensions rated `strong` or `moderate`" while the
    script counts everything not `absent`/`not_applicable` (so `weak` counts too),
    exactly as artifact-schemas.md documents. A narrator reading the SKILL.md line
    correctly concluded the rubric had been violated on a two-weak-moat company —
    it hadn't; the prose was wrong. Guarding the direction of the fix so nobody
    "reconciles" the correct script to the incorrect doc.
    """
    skill_dir = os.path.dirname(CP_SCRIPTS_DIR)
    with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
        skill_md = f.read()
    with open(os.path.join(CP_SCRIPTS_DIR, "score_moats.py"), encoding="utf-8") as f:
        script = f.read()

    # The code is the source of truth: it filters on absent/not_applicable.
    assert 'm["status"] not in ("absent", "not_applicable")' in script, (
        "score_moats.py no longer computes moat_count by excluding absent/not_applicable — "
        "if this changed deliberately, update SKILL.md and this test together"
    )

    # The prose must describe that rule, and must NOT describe the old wrong one.
    flat = " ".join(skill_md.split())
    assert "Moat count = dimensions with **any** status other than `absent` / `not_applicable`" in flat, (
        "SKILL.md's moat_count definition no longer matches score_moats.py"
    )
    assert "Moat count = dimensions rated `strong` or `moderate`" not in flat, (
        "SKILL.md has reverted to the incorrect moat_count definition"
    )


# ---------------------------------------------------------------------------
# Mode-gated items must not require evidence they will never use
#
# checklist.py auto-gates EVID_04 (deck/conversation) and NARR_03
# (conversation/document) to not_applicable and OVERWRITES their evidence with
# GATE_MESSAGE. Requiring a non-empty string for them anyway rejects the whole
# batch over a value that is discarded — a live run hit exactly that: the
# sub-agent reasonably left them empty in conversation mode, the batch
# hard-failed, and the run paid a repair dispatch to write text nothing reads.
# ---------------------------------------------------------------------------


def _checklist_items(blank: set[str]) -> list[dict]:
    return [{"id": i, "status": "pass", "evidence": ("" if i in blank else "ok")} for i in CHECKLIST_IDS]


def test_mode_gated_items_accept_empty_evidence() -> None:
    """EVID_04/NARR_03 blank in conversation mode is valid, not a hard failure."""
    rc, data, err = run_script(
        "checklist.py",
        args=["--pretty", "--input-mode", "conversation"],
        stdin_data=json.dumps({"items": _checklist_items({"EVID_04", "NARR_03"})}),
    )
    assert rc == 0, f"gated blanks must not fail the batch: {err}"
    assert data is not None
    gated = {i["id"]: i for i in data["items"] if i["id"] in {"EVID_04", "NARR_03"}}
    for item in gated.values():
        assert item["status"] == "not_applicable"
        assert "Auto-gated" in item["evidence"], "the gate message must still be written"


def test_non_gated_items_still_require_evidence() -> None:
    """The exemption is scoped: an ungated item with blank evidence still fails."""
    rc, _, err = run_script(
        "checklist.py",
        args=["--input-mode", "conversation"],
        stdin_data=json.dumps({"items": _checklist_items({"POS_03"})}),
    )
    assert rc == 1
    assert "POS_03" in err


def test_the_exemption_is_mode_sensitive() -> None:
    """NARR_03 is gated in conversation but NOT in deck mode — so it still fails there.

    Pins that the exemption reads MODE_GATING rather than hard-coding ids.
    """
    rc, _, err = run_script(
        "checklist.py",
        args=["--input-mode", "deck"],
        stdin_data=json.dumps({"items": _checklist_items({"NARR_03"})}),
    )
    assert rc == 1, "NARR_03 is not gated in deck mode, so blank evidence must still fail"
    assert "NARR_03" in err


# ===========================================================================
# _axis_compat.py — axis_rationale() unit tests
#
# Regression coverage for the silently-lost axis rationale defect: dispatch
# templates instructed the sub-agent to write the rationale as a view-level
# sibling (view["x_axis_rationale"]) while the canonical schema shape is
# nested (view["x_axis"]["rationale"]). _axis_compat.axis_rationale() is the
# single tolerant reader shared by score_positioning.py, visualize.py, and
# explore.py — no per-file reimplementation.
# ===========================================================================


def _import_axis_rationale() -> Any:
    """Import _axis_compat.axis_rationale via sys.path, matching the existing
    _dispatch_json import convention used elsewhere in this file."""
    import sys as _sys

    scripts_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "competitive-positioning", "scripts")
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    from _axis_compat import axis_rationale  # type: ignore[import-not-found]

    return axis_rationale


def test_axis_compat_nested_wins_when_only_nested_present() -> None:
    axis_rationale = _import_axis_rationale()
    view = {"x_axis": {"name": "Speed", "rationale": "Nested rationale"}}
    assert axis_rationale(view, "x") == "Nested rationale"


def test_axis_compat_sibling_fallback_when_nested_absent() -> None:
    axis_rationale = _import_axis_rationale()
    view = {"x_axis": {"name": "Speed"}, "x_axis_rationale": "Sibling rationale"}
    assert axis_rationale(view, "x") == "Sibling rationale"


def test_axis_compat_nested_wins_when_both_present_and_differ() -> None:
    """Precedence is fixed: nested wins silently, even when both are present
    and disagree — the schema is the authority."""
    axis_rationale = _import_axis_rationale()
    view = {
        "x_axis": {"name": "Speed", "rationale": "Nested wins"},
        "x_axis_rationale": "Sibling loses",
    }
    assert axis_rationale(view, "x") == "Nested wins"


def test_axis_compat_empty_string_when_neither_present() -> None:
    axis_rationale = _import_axis_rationale()
    view = {"x_axis": {"name": "Speed"}}
    assert axis_rationale(view, "x") == ""


def test_axis_compat_empty_string_when_view_has_no_axis_key_at_all() -> None:
    axis_rationale = _import_axis_rationale()
    assert axis_rationale({}, "y") == ""


def test_axis_compat_axis_parameter_selects_the_right_key() -> None:
    """Confirms the `axis` parameter selects the matching nested/sibling key
    pair, not just "x" regardless of the argument."""
    axis_rationale = _import_axis_rationale()
    view = {"y_axis_rationale": "Y sibling rationale"}
    assert axis_rationale(view, "y") == "Y sibling rationale"
    assert axis_rationale(view, "x") == ""


def test_axis_compat_non_string_nested_rationale_falls_back_to_sibling() -> None:
    """A malformed nested rationale (wrong type) must not crash — and must not
    be treated as a present value that blocks the sibling fallback."""
    axis_rationale = _import_axis_rationale()
    view = {"x_axis": {"name": "Speed", "rationale": 123}, "x_axis_rationale": "Sibling rationale"}
    assert axis_rationale(view, "x") == "Sibling rationale"


# ===========================================================================
# score_positioning.py — sibling-shaped rationale, RATIONALE_MISSING,
# optional label, views_fingerprint
# ===========================================================================


def _make_sibling_rationale_view(view_id: str = "primary") -> dict[str, Any]:
    """A view carrying axis rationale as a view-level sibling instead of
    nested — the shape real dispatch templates historically produced."""
    return {
        "id": view_id,
        "x_axis": {"name": "Deployment Speed"},
        "x_axis_rationale": "Speed-to-value differentiates for SMB buyers",
        "y_axis": {"name": "Data Privacy Level"},
        "y_axis_rationale": "Privacy is a growing buyer concern",
        "points": [
            _make_positioning_point("_startup", 90, 85),
            _make_positioning_point("acme-corp", 60, 40),
        ],
    }


class TestScorePositioningAxisRationale:
    """Regression coverage for the silently-lost axis rationale defect (Task 1)."""

    def test_sibling_shaped_rationale_surfaces_in_output(self) -> None:
        payload = _make_valid_positioning_input(views=[_make_sibling_rationale_view()])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        view = data["views"][0]
        assert view["x_axis_rationale"] == "Speed-to-value differentiates for SMB buyers"
        assert view["y_axis_rationale"] == "Privacy is a growing buyer concern"

    def test_nested_rationale_still_wins_over_sibling(self) -> None:
        view = _make_sibling_rationale_view()
        view["x_axis"]["rationale"] = "Nested wins"
        payload = _make_valid_positioning_input(views=[view])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        assert data["views"][0]["x_axis_rationale"] == "Nested wins"

    def test_missing_rationale_on_both_axes_emits_two_rationale_missing_warnings(self) -> None:
        view = {
            "id": "primary",
            "x_axis": {"name": "Deployment Speed"},
            "y_axis": {"name": "Data Privacy Level"},
            "points": [
                _make_positioning_point("_startup", 90, 85),
                _make_positioning_point("acme-corp", 60, 40),
            ],
        }
        payload = _make_valid_positioning_input(views=[view])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert codes.count("RATIONALE_MISSING") == 2
        rationale_warnings = [w for w in data["warnings"] if w["code"] == "RATIONALE_MISSING"]
        messages = " ".join(w["message"] for w in rationale_warnings)
        assert "primary" in messages
        assert "X-axis" in messages
        assert "Y-axis" in messages
        for w in rationale_warnings:
            assert w["severity"] == "medium"

    def test_missing_rationale_on_one_axis_emits_exactly_one_warning(self) -> None:
        view = _make_sibling_rationale_view()
        del view["y_axis_rationale"]
        payload = _make_valid_positioning_input(views=[view])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        rationale_warnings = [w for w in data["warnings"] if w["code"] == "RATIONALE_MISSING"]
        assert len(rationale_warnings) == 1
        assert "Y-axis" in rationale_warnings[0]["message"]
        assert "primary" in rationale_warnings[0]["message"]

    def test_fully_present_nested_rationale_emits_no_rationale_missing_warning(self) -> None:
        """Regression guard: the baseline factory's canonical nested-shaped
        view must not spuriously trip the new warning."""
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        codes = [w["code"] for w in data["warnings"]]
        assert "RATIONALE_MISSING" not in codes


class TestScorePositioningLabel:
    """Optional `label` on views[] (Task 4) — passthrough only, never
    required, never inferred from `id`."""

    def test_label_passes_through_when_present(self) -> None:
        view = _make_valid_positioning_input()["views"][0]
        view["label"] = "Speed vs. Privacy"
        payload = _make_valid_positioning_input(views=[view])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        assert data["views"][0]["label"] == "Speed vs. Privacy"

    def test_label_absent_stays_absent(self) -> None:
        """Every existing artifact/fixture lacks `label` — absence must be
        silent, never defaulted or inferred from `id`."""
        payload = _make_valid_positioning_input()
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        assert "label" not in data["views"][0]

    def test_non_enum_id_does_not_fail_validation(self) -> None:
        """`id` accepts a descriptive slug, not just primary/secondary —
        validation must not enforce an enum on it."""
        view = _make_valid_positioning_input()["views"][0]
        view["id"] = "speed-vs-privacy"
        payload = _make_valid_positioning_input(views=[view])
        rc, data, stderr = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc == 0, stderr
        assert data is not None
        assert data["views"][0]["view_id"] == "speed-vs-privacy"


class TestScorePositioningViewsFingerprint:
    """views_fingerprint (Task 2) — order-insensitive over views/points,
    prose-excluded (evidence, rationale, provenance don't move the map)."""

    def test_fingerprint_is_present_and_stable_for_identical_input(self) -> None:
        payload = _make_valid_positioning_input()
        rc1, data1, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        rc2, data2, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload))
        assert rc1 == 0, stderr1
        assert rc2 == 0, stderr2
        assert data1 is not None
        assert data2 is not None
        assert "views_fingerprint" in data1
        assert len(data1["views_fingerprint"]) == 64  # sha256 hex digest length
        assert data1["views_fingerprint"] == data2["views_fingerprint"]

    def test_fingerprint_ignores_point_order(self) -> None:
        base = _make_valid_positioning_input()
        rc1, data1, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(base))
        assert rc1 == 0, stderr1
        assert data1 is not None

        reordered = _make_valid_positioning_input()
        reordered["views"][0]["points"] = list(reversed(reordered["views"][0]["points"]))
        rc2, data2, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(reordered))
        assert rc2 == 0, stderr2
        assert data2 is not None

        assert data1["views_fingerprint"] == data2["views_fingerprint"]

    def test_fingerprint_ignores_reworded_evidence(self) -> None:
        base = _make_valid_positioning_input()
        rc1, data1, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(base))
        assert rc1 == 0, stderr1
        assert data1 is not None

        reworded = _make_valid_positioning_input()
        for p in reworded["views"][0]["points"]:
            p["x_evidence"] = "Completely reworded evidence text, same coordinates"
            p["y_evidence"] = "Another completely different sentence"
        rc2, data2, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(reworded))
        assert rc2 == 0, stderr2
        assert data2 is not None

        assert data1["views_fingerprint"] == data2["views_fingerprint"], (
            "reworded evidence text must not change the fingerprint — it is prose, not identity"
        )

    def test_fingerprint_changes_on_moved_coordinate(self) -> None:
        base = _make_valid_positioning_input()
        rc1, data1, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(base))
        assert rc1 == 0, stderr1
        assert data1 is not None

        moved = _make_valid_positioning_input()
        moved["views"][0]["points"][0]["x"] = moved["views"][0]["points"][0]["x"] - 1
        rc2, data2, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(moved))
        assert rc2 == 0, stderr2
        assert data2 is not None

        assert data1["views_fingerprint"] != data2["views_fingerprint"]

    def test_fingerprint_ignores_view_order(self) -> None:
        view_a = _make_valid_positioning_input()["views"][0]
        view_b = {
            "id": "secondary",
            "x_axis": {"name": "Price"},
            "y_axis": {"name": "Support"},
            "points": [
                _make_positioning_point("_startup", 20, 20),
                _make_positioning_point("acme-corp", 80, 80),
            ],
        }
        payload_ab = _make_valid_positioning_input(views=[view_a, view_b])
        payload_ba = _make_valid_positioning_input(views=[view_b, view_a])

        rc1, data1, stderr1 = run_script("score_positioning.py", stdin_data=json.dumps(payload_ab))
        rc2, data2, stderr2 = run_script("score_positioning.py", stdin_data=json.dumps(payload_ba))
        assert rc1 == 0, stderr1
        assert rc2 == 0, stderr2
        assert data1 is not None
        assert data2 is not None

        assert data1["views_fingerprint"] == data2["views_fingerprint"]


# ---------------------------------------------------------------------------
# checklist.py --positioning-scores / graded_against
#
# A live run re-scored positioning (a second view added, coordinates moved) and
# re-composed the report WITHOUT re-running the checklist. Nothing detected it:
# the run_id was unchanged, so STALE_ARTIFACT cannot fire — while POS_04's pass
# condition reads score_positioning.py's rank data directly. graded_against
# records which map was graded so compose can catch the mismatch.
# ---------------------------------------------------------------------------


class TestChecklistGradedAgainst:
    """`--positioning-scores` records the graded map's fingerprint. Absent is silent."""

    @staticmethod
    def _ps_file(tmp_path: Any, payload: Any) -> str:
        p = tmp_path / "positioning_scores.json"
        p.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
        return str(p)

    def test_records_fingerprint_verbatim_when_given(self, tmp_path: Any) -> None:
        fp = "ab12" * 16
        path = self._ps_file(tmp_path, {"views_fingerprint": fp, "views": []})
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck", "--run-id", "R1", "--positioning-scores", path],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert data["graded_against"] == {"views_fingerprint": fp}, (
            "the fingerprint must be copied verbatim — checklist.py must never recompute it"
        )

    def test_absent_when_flag_omitted(self) -> None:
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck", "--run-id", "R1"],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert "graded_against" not in data, "absent must stay absent — never inferred"

    def test_missing_file_omits_field_without_failing(self, tmp_path: Any) -> None:
        """The checklist is deliverable-critical; an optional provenance read must not block it."""
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script(
            "checklist.py",
            args=[
                "--input-mode",
                "deck",
                "--run-id",
                "R1",
                "--positioning-scores",
                str(tmp_path / "nope.json"),
            ],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert "graded_against" not in data
        assert "graded_against" in stderr, "the omission must be visible on stderr"

    def test_invalid_json_omits_field_without_failing(self, tmp_path: Any) -> None:
        path = self._ps_file(tmp_path, "{not json")
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck", "--run-id", "R1", "--positioning-scores", path],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert "graded_against" not in data
        assert "graded_against" in stderr

    def test_file_without_fingerprint_omits_field(self, tmp_path: Any) -> None:
        path = self._ps_file(tmp_path, {"views": [], "overall_differentiation": 50})
        payload = _make_valid_checklist_input()
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "deck", "--run-id", "R1", "--positioning-scores", path],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert "graded_against" not in data

    def test_existing_gating_and_run_id_unaffected(self, tmp_path: Any) -> None:
        """The new flag must not disturb mode gating or run_id stamping."""
        path = self._ps_file(tmp_path, {"views_fingerprint": "cd" * 32})
        payload = _make_valid_checklist_input(input_mode="conversation")
        rc, data, stderr = run_script(
            "checklist.py",
            args=["--input-mode", "conversation", "--run-id", "RX", "--positioning-scores", path],
            stdin_data=json.dumps(payload),
        )
        assert rc == 0, stderr
        assert data is not None
        assert data["metadata"]["run_id"] == "RX"
        gated = [i for i in data["items"] if i["status"] == "not_applicable"]
        assert gated, "conversation mode must still auto-gate research-dependent items"


class TestValidateLandscapeDeferredCarryAndDerive:
    """`--carry-deferred` / `--derive-deferred`: the deferred-candidate chain, made mechanical.

    Both of these replace an INSTRUCTION that was measured unreliable across two live Cowork runs.
    The field has to survive from the competitor-set gate into `landscape.json` so the later
    additions gate can re-offer the declined candidates. Originally the main thread wrote it into
    `landscape_draft.json` and the research sub-agent copied it through. Run A's sub-agent dropped
    the field entirely; run B's main thread created the key and left it empty. A courier that
    complies half the time is not a mechanism, so the producer now reads the draft directly and, as a
    last resort, derives the set from the blind-recall diff.
    """

    @staticmethod
    def _draft(tmp_path: Any, deferred: Any) -> str:
        p = tmp_path / "landscape_draft.json"
        p.write_text(json.dumps({"competitors": [], "deferred_recall_candidates": deferred}), encoding="utf-8")
        return str(p)

    @staticmethod
    def _verification(tmp_path: Any, unmatched: list[dict[str, Any]]) -> str:
        p = tmp_path / "competitor_verification.json"
        p.write_text(json.dumps({"recall_gaps": {"unmatched": unmatched}}), encoding="utf-8")
        return str(p)

    def _run(self, payload: dict[str, Any], *args: str) -> tuple[int, dict | None, str]:
        return run_script("validate_landscape.py", args=["--as-of", AS_OF, *args], stdin_data=json.dumps(payload))

    # --- carry ---------------------------------------------------------

    def test_carries_deferred_from_the_draft_when_stdin_lacks_it(self, tmp_path: Any) -> None:
        """Run A's shape: the sub-agent dropped the field, so stdin has none."""
        draft = self._draft(tmp_path, [{"name": "Backstage", "slug": "backstage"}])
        rc, data, stderr = self._run(_make_valid_landscape(), "--carry-deferred", draft)
        assert rc == 0, stderr
        assert data is not None
        assert [c["slug"] for c in data["deferred_recall_candidates"]] == ["backstage"]

    def test_stdin_value_wins_over_the_draft(self, tmp_path: Any) -> None:
        """A sub-agent that DID copy (and may have enriched) must not be clobbered."""
        draft = self._draft(tmp_path, [{"name": "Backstage", "slug": "backstage"}])
        payload = _make_valid_landscape()
        payload["deferred_recall_candidates"] = [{"name": "FromStdin", "slug": "from-stdin"}]
        rc, data, stderr = self._run(payload, "--carry-deferred", draft)
        assert rc == 0, stderr
        assert data is not None
        assert [c["slug"] for c in data["deferred_recall_candidates"]] == ["from-stdin"]

    def test_a_promoted_candidate_is_dropped_from_the_carry(self, tmp_path: Any) -> None:
        """A candidate that reached competitors[] is no longer deferred — re-offering it would
        re-propose something the founder already accepted."""
        payload = _make_valid_landscape()
        adopted = payload["competitors"][0]["slug"]
        draft = self._draft(tmp_path, [{"name": "A", "slug": adopted}, {"name": "B", "slug": "still-deferred"}])
        rc, data, stderr = self._run(payload, "--carry-deferred", draft)
        assert rc == 0, stderr
        assert data is not None
        assert [c["slug"] for c in data["deferred_recall_candidates"]] == ["still-deferred"]

    def test_unreadable_draft_is_a_note_not_a_failure(self, tmp_path: Any) -> None:
        """A convenience field must never block the landscape producer."""
        rc, data, stderr = self._run(_make_valid_landscape(), "--carry-deferred", str(tmp_path / "nope.json"))
        assert rc == 0, stderr
        assert data is not None
        assert data["deferred_recall_candidates"] == [], "an unreadable draft yields an empty list, not entries"
        assert "carry-deferred" in stderr

    # --- derive --------------------------------------------------------

    def test_derives_from_the_recall_diff_when_the_draft_is_empty(self, tmp_path: Any) -> None:
        """Run B's shape: the key existed but was an empty list, so there was nothing to carry.

        A recall candidate still absent from competitors[] was not adopted — that IS the definition
        of deferred, so it is derivable rather than remembered.
        """
        draft = self._draft(tmp_path, [])
        verification = self._verification(
            tmp_path,
            [{"name": "Pipedream", "slug": "pipedream", "why_considered": "same job", "sources": ["https://x"]}],
        )
        rc, data, stderr = self._run(
            _make_valid_landscape(), "--carry-deferred", draft, "--derive-deferred", verification
        )
        assert rc == 0, stderr
        assert data is not None
        derived = data["deferred_recall_candidates"]
        assert [c["slug"] for c in derived] == ["pipedream"]
        assert derived[0]["why_considered"] == "same job", "the derivation must keep the candidate's rationale"

    def test_derivation_excludes_an_adopted_candidate(self, tmp_path: Any) -> None:
        payload = _make_valid_landscape()
        adopted = payload["competitors"][0]["slug"]
        verification = self._verification(
            tmp_path, [{"name": "A", "slug": adopted}, {"name": "B", "slug": "not-adopted"}]
        )
        rc, data, stderr = self._run(payload, "--derive-deferred", verification)
        assert rc == 0, stderr
        assert data is not None
        assert [c["slug"] for c in data["deferred_recall_candidates"]] == ["not-adopted"]

    def test_carry_takes_precedence_over_derive(self, tmp_path: Any) -> None:
        draft = self._draft(tmp_path, [{"name": "FromDraft", "slug": "from-draft"}])
        verification = self._verification(tmp_path, [{"name": "FromDiff", "slug": "from-diff"}])
        rc, data, stderr = self._run(
            _make_valid_landscape(), "--carry-deferred", draft, "--derive-deferred", verification
        )
        assert rc == 0, stderr
        assert data is not None
        assert [c["slug"] for c in data["deferred_recall_candidates"]] == ["from-draft"]

    def test_no_flags_means_an_empty_list_never_invented_entries(self) -> None:
        """The key is always present so absence is discriminating for the delivery gate; what must
        never appear is a fabricated candidate."""
        rc, data, stderr = self._run(_make_valid_landscape())
        assert rc == 0, stderr
        assert data is not None
        assert data["deferred_recall_candidates"] == []
