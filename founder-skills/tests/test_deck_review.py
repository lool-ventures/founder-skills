#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for deck review scripts.

Run: pytest founder-skills/tests/test_deck_review.py -v
All tests use subprocess to exercise the scripts exactly as the agent does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECK_REVIEW_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts")
SKILL_MD_PATH = os.path.join(os.path.dirname(DECK_REVIEW_DIR), "SKILL.md")


def run_script(name: str, args: list[str] | None = None, stdin_data: str | None = None) -> tuple[int, dict | None, str]:
    """Run a script and return (exit_code, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, os.path.join(DECK_REVIEW_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return result.returncode, data, result.stderr


def run_script_raw(name: str, args: list[str] | None = None, stdin_data: str | None = None) -> tuple[int, str, str]:
    """Like run_script but returns (exit_code, raw_stdout, stderr)."""
    cmd = [sys.executable, os.path.join(DECK_REVIEW_DIR, name)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# -- All 35 canonical checklist IDs --

_CHECKLIST_IDS = [
    # Narrative Flow
    "purpose_clear",
    "headlines_carry_story",
    "narrative_arc_present",
    "strongest_proof_early",
    "story_stands_alone",
    # Slide Content
    "problem_quantified",
    "solution_shows_workflow",
    "why_now_has_catalyst",
    "market_bottom_up",
    "competition_honest",
    "business_model_clear",
    "gtm_has_proof",
    "team_has_depth",
    # Stage Fit
    "stage_appropriate_structure",
    "stage_appropriate_traction",
    "stage_appropriate_financials",
    "ask_ties_to_milestones",
    "round_size_realistic",
    # Design & Readability
    "one_idea_per_slide",
    "minimal_text",
    "slide_count_appropriate",
    "consistent_design",
    "mobile_readable",
    # Common Mistakes
    "no_vague_purpose",
    "no_nice_to_have_problem",
    "no_hype_without_proof",
    "no_features_over_outcomes",
    "no_dodged_competition",
    # AI Company
    "ai_retention_rebased",
    "ai_cost_to_serve_shown",
    "ai_defensibility_beyond_model",
    "ai_responsible_controls",
    # Diligence Readiness
    "numbers_consistent",
    "data_room_ready",
    "contact_info_present",
]


def _make_checklist_items(
    overrides: dict[str, dict] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Build a 35-item checklist payload."""
    overrides = overrides or {}
    exclude = exclude or []
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in exclude:
            continue
        if cid in overrides:
            items.append({"id": cid, **overrides[cid]})
        else:
            items.append({"id": cid, "status": "pass", "evidence": "test", "notes": None})
    return items


# -- Checklist tests --


def test_checklist_all_pass() -> None:
    """All 35 items pass."""
    payload = json.dumps({"items": _make_checklist_items()})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["total"] == 35
    assert s["pass"] == 35
    assert s["fail"] == 0
    assert s["warn"] == 0
    assert s["score_pct"] == 100.0
    assert s["overall_status"] == "strong"
    assert len(s["failed_items"]) == 0
    assert len(s["warned_items"]) == 0


def test_checklist_score_thresholds() -> None:
    """Test all four overall_status thresholds."""
    # Strong: >=85% -- with 4 AI N/A, 31 applicable, need 27 pass = 87.1%
    ai_na = {
        cid: {"status": "not_applicable", "evidence": "N/A", "notes": "Not AI"}
        for cid in [
            "ai_retention_rebased",
            "ai_cost_to_serve_shown",
            "ai_defensibility_beyond_model",
            "ai_responsible_controls",
        ]
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=ai_na)})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "strong"
        assert data["summary"]["score_pct"] == 100.0

    # Needs work: 50-69% -- 15 pass out of 31 applicable = 48.4% -> major_revision
    # Let's do 16 pass = 51.6% -> needs_work
    fail_ids = _CHECKLIST_IDS[5:20]  # 15 items fail
    overrides = dict(ai_na)
    for cid in fail_ids:
        overrides[cid] = {"status": "fail", "evidence": "test", "notes": "test fail"}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "needs_work"

    # Major revision: <50% -- 14 pass out of 31 = 45.2%
    fail_ids_more = _CHECKLIST_IDS[4:21]  # 17 items fail
    overrides2 = dict(ai_na)
    for cid in fail_ids_more:
        overrides2[cid] = {"status": "fail", "evidence": "test", "notes": "test fail"}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides2)})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    if data:
        assert data["summary"]["overall_status"] == "major_revision"


def test_checklist_warn_status() -> None:
    """Warn items counted correctly and listed in warned_items."""
    overrides = {
        "headlines_carry_story": {"status": "warn", "evidence": "test", "notes": "Mixed headlines"},
        "minimal_text": {"status": "warn", "evidence": "test", "notes": "Some dense slides"},
        "competition_honest": {"status": "fail", "evidence": "test", "notes": "Missing"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    s = data["summary"]
    assert s["warn"] == 2
    assert s["fail"] == 1
    assert s["pass"] == 32
    warned_ids = {w["id"] for w in s["warned_items"]}
    assert warned_ids == {"headlines_carry_story", "minimal_text"}
    failed_ids = {f["id"] for f in s["failed_items"]}
    assert failed_ids == {"competition_honest"}


def test_checklist_by_category() -> None:
    """by_category counts are correct."""
    overrides = {
        "purpose_clear": {"status": "fail", "evidence": "test", "notes": "Vague"},
        "headlines_carry_story": {"status": "warn", "evidence": "test", "notes": "Mixed"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    cat = data["summary"]["by_category"]
    nf = cat.get("Narrative Flow", {})
    assert nf.get("pass") == 3
    assert nf.get("fail") == 1
    assert nf.get("warn") == 1


def _assert_validation_errors(data: dict | None, *fragments: str) -> None:
    """Assert data has validation.status == 'invalid' and errors contain all fragments."""
    assert data is not None, "expected JSON output with validation errors"
    assert data["validation"]["status"] == "invalid"
    joined = " ".join(data["validation"]["errors"]).lower()
    for frag in fragments:
        assert frag.lower() in joined, f"expected '{frag}' in validation errors: {data['validation']['errors']}"


def test_checklist_missing_items() -> None:
    """Only 32 items -- should produce validation error."""
    items = _make_checklist_items(exclude=["data_room_ready", "contact_info_present", "numbers_consistent"])
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "missing")


def test_checklist_duplicate_id() -> None:
    """36 items with a duplicate -- should produce validation error."""
    items = _make_checklist_items()
    items.append({"id": "purpose_clear", "status": "pass", "evidence": "dup", "notes": None})
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "duplicate")


def test_checklist_unknown_id() -> None:
    """Unknown ID -- should produce validation error."""
    items = _make_checklist_items()
    items[0] = {"id": "bogus_criterion", "status": "pass", "evidence": "test", "notes": None}
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "unknown")


def test_checklist_invalid_status() -> None:
    """Status 'maybe' -- should produce validation error."""
    overrides = {"purpose_clear": {"status": "maybe", "evidence": "test", "notes": None}}
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "invalid")


def test_checklist_non_dict_item() -> None:
    """Non-dict item in checklist items array -> validation error."""
    payload = json.dumps({"items": ["not_a_dict"]})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    _assert_validation_errors(data, "must be an object")


def test_checklist_output_flag() -> None:
    """checklist.py with -o writes to file, stdout empty."""
    payload = json.dumps({"items": _make_checklist_items()})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "checklist.py", ["--pretty", "--run-id", "test-run", "-o", tmp], stdin_data=payload
        )
        assert rc == 0, f"rc={rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp) as fh:
            data = json.load(fh)
        assert "summary" in data
        assert len(data["items"]) == 35
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_checklist_omits_null_evidence_and_notes() -> None:
    """Pass items without evidence/notes must NOT emit null keys (schema types them as string)."""
    # All-pass, no evidence/notes supplied at all.
    items = [{"id": cid, "status": "pass"} for cid in _CHECKLIST_IDS]
    payload = json.dumps({"items": items})
    rc, data, _ = run_script("checklist.py", ["--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    for item in data["items"]:
        assert "evidence" not in item, f"{item['id']} emitted a null evidence key"
        assert "notes" not in item, f"{item['id']} emitted a null notes key"


def test_checklist_output_validates_against_schema() -> None:
    """Real -o producer output (all pass, no evidence) must pass checklist.schema.json — no false SCHEMA_VIOLATION."""
    sys.path.insert(0, DECK_REVIEW_DIR)
    from _artifact_writer import load_schema  # type: ignore[import-not-found]  # noqa: E402
    from _schema_validator import validate as _schema_validate  # type: ignore[import-not-found]  # noqa: E402

    items = [{"id": cid, "status": "pass"} for cid in _CHECKLIST_IDS]
    payload = json.dumps({"items": items})
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, _, stderr = run_script_raw("checklist.py", ["--run-id", "r1", "-o", tmp], stdin_data=payload)
        assert rc == 0, stderr
        with open(tmp) as fh:
            data = json.load(fh)
        schema = load_schema(os.path.join(DECK_REVIEW_DIR, "..", "references", "schemas", "checklist.schema.json"))
        errs = _schema_validate(data, schema)
        assert errs == [], f"producer output should be schema-clean, got: {errs}"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_checklist_fixture_matches_producer_shape_and_schema() -> None:
    """The committed checklist fixture must validate against the schema and carry no null evidence/notes."""
    sys.path.insert(0, DECK_REVIEW_DIR)
    from _artifact_writer import load_schema  # type: ignore[import-not-found]  # noqa: E402
    from _schema_validator import validate as _schema_validate  # type: ignore[import-not-found]  # noqa: E402

    fixture_path = os.path.join(SCRIPT_DIR, "fixtures", "deck-review", "checklist.json")
    with open(fixture_path) as f:
        fixture = json.load(f)
    schema = load_schema(os.path.join(DECK_REVIEW_DIR, "..", "references", "schemas", "checklist.schema.json"))
    errs = _schema_validate(fixture, schema)
    assert errs == [], f"fixture must be schema-clean, got: {errs}"
    # Must carry the producer's validation block and never a null evidence/notes key.
    assert "validation" in fixture
    for item in fixture["items"]:
        # Keys are omitted when absent; when present they must be non-null strings.
        if "evidence" in item:
            assert item["evidence"] is not None
        if "notes" in item:
            assert item["notes"] is not None


def test_checklist_o_mode_validation_failure_exits_1_no_write() -> None:
    """In -o mode, invalid input -> stderr + exit 1, and NO artifact is written."""
    items = _make_checklist_items(exclude=["data_room_ready"])  # missing item
    payload = json.dumps({"items": items})
    d = tempfile.mkdtemp(prefix="test-checklist-fail-")
    out = os.path.join(d, "checklist.json")
    try:
        rc, stdout, stderr = run_script_raw("checklist.py", ["--run-id", "r1", "-o", out], stdin_data=payload)
        assert rc == 1, f"expected exit 1, got {rc}; stdout={stdout}"
        assert "validation failed" in stderr.lower()
        assert not os.path.exists(out), "no artifact must be written on validation failure"
    finally:
        if os.path.exists(out):
            os.unlink(out)
        os.rmdir(d)


def _load_stage_profile_module() -> Any:
    """Load stage_profile.py by path (it's a standalone script, not a package).
    stage_profile.py does `from _artifact_writer import ...` as a bare sibling
    import, so DECK_REVIEW_DIR must be on sys.path before exec_module — without
    it this only works by accident, when some earlier test in the same process
    happened to insert it first."""
    import importlib.util

    if DECK_REVIEW_DIR not in sys.path:
        sys.path.insert(0, DECK_REVIEW_DIR)
    path = os.path.join(DECK_REVIEW_DIR, "stage_profile.py")
    spec = importlib.util.spec_from_file_location("deck_review_stage_profile_module", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deck_review_stage_profile_module"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_skill_md_stage_choice_options_match_stage_profile_enum() -> None:
    """SKILL.md's stage_choice gate (offered when the founder says the detected
    stage is wrong) must offer exactly the stages stage_profile.py's
    --rebuild-stage accepts (argparse choices=sorted(_STAGE_TABLE.keys())) — an
    option outside that set fails argparse when the founder's pick is rebuilt.
    Import the constant from stage_profile.py; never hardcode the expected set
    here, or prose and code can silently desync."""
    mod = _load_stage_profile_module()
    expected = set(mod._STAGE_TABLE.keys())
    assert expected, "stage_profile.py's _STAGE_TABLE must not be empty"

    with open(SKILL_MD_PATH, encoding="utf-8") as f:
        skill_md = f.read()

    anchor = "each label with the `--rebuild-stage` token it maps to:"
    end_marker = "that is the complete enum"
    start = skill_md.find(anchor)
    assert start != -1, "SKILL.md must state the stage_choice candidates with their --rebuild-stage tokens"
    end = skill_md.find(end_marker, start)
    assert end != -1, "SKILL.md's stage token list must be terminated by the '...is the complete enum' marker"
    segment = skill_md[start + len(anchor) : end]
    found_tokens = set(re.findall(r"`([a-z_]+)`", segment))
    assert found_tokens == expected, (
        f"SKILL.md's stage_choice candidates ({sorted(found_tokens)}) must match "
        f"stage_profile.py's --rebuild-stage enum ({sorted(expected)})"
    )


def test_skill_md_stage_choice_offers_four_not_the_whole_enum() -> None:
    """The enum is the candidate SET; the gate may only OFFER four of it.

    `AskUserQuestion` renders at most four options, so a spec mandating all
    five meant the model silently forfeited one every time the gate fired.
    The rule that makes four sound is that the dropped stage is the one the
    profile currently holds — which the founder has just rejected, so it can
    never be the answer.

    Deliberately asserted as prose, not as a count of a declared array: the
    offered set is computed per run from the current profile, so there is no
    static list to check. That also means the fleet arity parser must keep
    reading this spec as prose — a static four-item array here would be wrong.
    """
    mod = _load_stage_profile_module()
    with open(SKILL_MD_PATH, encoding="utf-8") as f:
        skill_md = f.read()

    # The enum is stated in full (guarded for token-parity by the test above),
    # but the count must NOT be restated in prose — a hardcoded "five" desyncs
    # silently the moment _STAGE_TABLE changes.
    assert "renders at most four options" in skill_md, (
        "SKILL.md must state the AskUserQuestion four-option limit as the reason the gate offers a subset"
    )
    assert "the enum minus the stage `stage_profile.json` currently holds" in skill_md, (
        "SKILL.md must state WHICH stage is dropped — 'offer four' without the drop rule is unimplementable"
    )
    # The iterated path (reject -> rebuild -> reject again) is the only way the
    # rule goes wrong: dropping the originally-detected stage re-offers what the
    # founder just rejected and hides the one they now want.
    assert "drop the stage the profile holds NOW" in skill_md, (
        "SKILL.md must pin the drop to the CURRENT profile stage, not the first detection"
    )
    assert "offer **exactly four:" in skill_md, (
        "SKILL.md must mandate exactly four offered options — 'at most four' alone permits three, "
        "which would drop a reachable stage for no reason"
    )
    spelled_counts = [w for w in ("these five", "exactly these five", "all five") if w in skill_md]
    assert not spelled_counts, (
        f"SKILL.md restates the enum size as prose ({spelled_counts}); it must derive from the token "
        f"list alone ({len(mod._STAGE_TABLE)} tokens today) or it desyncs when the enum changes"
    )


def test_stage_enum_is_still_five_so_offering_four_remains_all_but_one() -> None:
    """The load-bearing arithmetic behind offering four.

    Dropping one stage is safe ONLY because the enum has exactly five members
    and `AskUserQuestion` renders four — so "the enum minus the current stage"
    is every remaining stage, and nothing reachable is withheld.

    Add a sixth stage and that silently stops being true: four options would
    omit two stages, one of which the founder might actually want, and the
    reasoning in SKILL.md `:377` would still read as if it held. Nothing else
    in the suite would notice — the token-parity test above would keep passing,
    because SKILL.md would still list the full enum.

    If this fails because a stage was added, `:377` needs redesigning (a
    two-step gate, or grouping), not a bigger number here.
    """
    mod = _load_stage_profile_module()
    schema_path = os.path.join(os.path.dirname(DECK_REVIEW_DIR), "references", "schemas", "stage_profile.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    table_tokens = set(mod._STAGE_TABLE.keys())
    schema_tokens = set(schema["properties"]["detected_stage"]["enum"])

    assert table_tokens == schema_tokens, (
        f"stage_profile.py's _STAGE_TABLE {sorted(table_tokens)} and the schema's detected_stage enum "
        f"{sorted(schema_tokens)} have diverged — :377's option set is built from the first and "
        "validated against the second"
    )
    assert len(table_tokens) == 5, (
        f"the stage enum now has {len(table_tokens)} members, not 5. deck-review SKILL.md:377 offers "
        "four options and justifies it as 'the enum minus the stage already rejected' — that is only "
        "'every remaining stage' at exactly five. Redesign the gate; do not edit this number."
    )
    # detected_stage must stay required: "no stage detected" is the other way
    # the drop rule loses its subject.
    assert "detected_stage" in schema.get("required", []), (
        "detected_stage must remain required — :377 drops 'the stage the profile currently holds', "
        "which presumes there always is one"
    )


# -- Compose report tests --


def _make_artifact_dir(artifacts: dict[str, dict]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-deck-review-")
    for name, data in artifacts.items():
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)
    return d


_VALID_INVENTORY = {
    "metadata": {"run_id": "run-test"},
    "company_name": "TestCo",
    "review_date": "2026-02-20",
    "input_format": "pdf",
    "total_slides": 11,
    "claimed_stage": "seed",
    "claimed_raise": "$4M",
    "ai_company_status": "not_ai",
    "ai_evidence": "No AI claim and not AI.",
    "slides": [
        {
            "number": 1,
            "headline": "TestCo -- Cloud Accounting for SMBs",
            "content_summary": "Company intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
    ],
}

_VALID_PROFILE = {
    "metadata": {"run_id": "run-test"},
    "detected_stage": "seed",
    "confidence": "high",
    "evidence": ["Claims $2M ARR", "Raising $4M"],
    "is_ai_company": False,
    "ai_evidence": "No AI mentioned",
    "expected_framework": ["purpose_traction", "problem", "solution"],
    "stage_benchmarks": {
        "round_size_range": "$2M-$6M",
        "expected_traction": "$300K-$500K ARR",
        "runway_expectation": "18-24 months",
    },
    "reference_file_read": ["deck-best-practices.md"],
}

_VALID_REVIEWS = {
    "metadata": {"run_id": "run-test"},
    "reviews": [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["Could add ICP specificity"],
            "recommendations": ["Add target customer segment"],
            "best_practice_refs": ["Sequoia: single declarative sentence"],
        },
    ],
    "missing_slides": [],
    "overall_narrative_assessment": "Good flow overall.",
}

_VALID_CHECKLIST = {
    "metadata": {"run_id": "run-test"},
    "items": [
        # Schema-clean shape: evidence is a string; notes is omitted when absent
        # (the producer omits null keys — see test_checklist_omits_null_evidence_and_notes).
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test"}
        for cid in _CHECKLIST_IDS
    ],
    "summary": {
        "total": 35,
        "pass": 35,
        "fail": 0,
        "warn": 0,
        "not_applicable": 0,
        "score_pct": 100.0,
        "overall_status": "strong",
        "by_category": {},
        "failed_items": [],
        "warned_items": [],
    },
}


def _run_compose(artifact_dir: str, extra_args: list[str] | None = None) -> tuple[int, dict | None, str]:
    """Run compose_report.py with given artifact dir."""
    args = ["--dir", artifact_dir, "--pretty"]
    if extra_args:
        args.extend(extra_args)
    return run_script("compose_report.py", args)


def test_compose_complete_set() -> None:
    """All 4 artifacts valid -> no missing artifacts, report non-empty."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    v = data["validation"]
    assert len(v["artifacts_missing"]) == 0
    assert len(data["report_markdown"]) > 100
    codes = [w["code"] for w in v["warnings"]]
    assert "MISSING_ARTIFACT" not in codes


def test_compose_missing_required() -> None:
    """No checklist.json -> MISSING_ARTIFACT warning."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MISSING_ARTIFACT" in codes


def test_compose_stage_mismatch() -> None:
    """Inventory claims pre_seed, profile detects series_a -> STAGE_MISMATCH."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "pre_seed"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" in codes


def test_compose_slide_count_extreme_low() -> None:
    """3 slides -> SLIDE_COUNT_EXTREME."""
    inventory = dict(_VALID_INVENTORY)
    inventory["total_slides"] = 3
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SLIDE_COUNT_EXTREME" in codes


def test_compose_slide_count_extreme_high() -> None:
    """25 slides -> SLIDE_COUNT_EXTREME."""
    inventory = dict(_VALID_INVENTORY)
    inventory["total_slides"] = 25
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "SLIDE_COUNT_EXTREME" in codes


def test_compose_duplicate_slide_number_warns() -> None:
    """Two inventory slides sharing a number -> DUPLICATE_SLIDE_NUMBER warning (item 16)."""
    inventory = dict(_VALID_INVENTORY)
    inventory["slides"] = [
        {
            "number": 1,
            "headline": "First Headline (kept)",
            "content_summary": "Company intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
        {
            "number": 1,
            "headline": "Second Headline (dropped)",
            "content_summary": "Duplicate-numbered slide",
            "visuals": "",
            "word_count_estimate": 10,
        },
    ]
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warnings = data["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "DUPLICATE_SLIDE_NUMBER" in codes
    dup_warning = next(w for w in warnings if w["code"] == "DUPLICATE_SLIDE_NUMBER")
    assert dup_warning["severity"] == "medium"
    assert "1" in dup_warning["message"]


def test_compose_duplicate_slide_number_heading_keeps_first_headline() -> None:
    """On a duplicate-numbered deck, the heading quotes the FIRST headline, not the last.

    Matches visualize.py's `_chart_slide_map`, which also keeps first occurrence on a
    duplicate slide number (see `# Build slide data indexed by slide number (keep first
    occurrence)`), so the two surfaces agree instead of disagreeing on which headline wins.
    """
    inventory = dict(_VALID_INVENTORY)
    inventory["slides"] = [
        {
            "number": 1,
            "headline": "First Headline (kept)",
            "content_summary": "Company intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
        {
            "number": 1,
            "headline": "Second Headline (dropped)",
            "content_summary": "Duplicate-numbered slide",
            "visuals": "",
            "word_count_estimate": 10,
        },
    ]
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "First Headline (kept)" in report
    assert "Second Headline (dropped)" not in report


def test_compose_uncited_critique() -> None:
    """Slide review with weaknesses but no best_practice_refs -> UNCITED_CRITIQUE."""
    reviews = {
        "reviews": [
            {
                "slide_number": 1,
                "maps_to": "purpose",
                "strengths": [],
                "weaknesses": ["Purpose is vague"],
                "recommendations": ["Make it clearer"],
                "best_practice_refs": [],
            }
        ],
        "missing_slides": [],
        "overall_narrative_assessment": "Weak.",
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": reviews,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNCITED_CRITIQUE" in codes


def test_compose_ai_criteria_skipped() -> None:
    """AI company detected but all AI criteria not_applicable -> AI_CRITERIA_SKIPPED."""
    # ai_company_status drives the check; profile.is_ai_company is secondary (backward-compat).
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "ai_core"
    inventory["ai_evidence"] = "ML model in core value prop."
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = True
    # Checklist with AI items as not_applicable
    ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in ai_ids:
            items.append(
                {
                    "id": cid,
                    "category": "AI",
                    "label": "AI",
                    "status": "not_applicable",
                    "evidence": "N/A",
                    "notes": None,
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 31,
            "fail": 0,
            "warn": 0,
            "not_applicable": 4,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "AI_CRITERIA_SKIPPED" in codes


def test_compose_ai_criteria_skipped_founder_message() -> None:
    """founder_message states the plain-language consequence -- no raw enum token,
    and reaches report.md instead of the agent-facing `message`."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "ai_core"
    inventory["ai_evidence"] = "ML model in core value prop."
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = True
    ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in ai_ids:
            items.append(
                {
                    "id": cid,
                    "category": "AI",
                    "label": "AI",
                    "status": "not_applicable",
                    "evidence": "N/A",
                    "notes": None,
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 31,
            "fail": 0,
            "warn": 0,
            "not_applicable": 4,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "AI_CRITERIA_SKIPPED")
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    assert "not_applicable" not in founder_msg
    assert founder_msg in data["report_markdown"]


def test_compose_ai_criteria_on_non_ai_and_founder_message() -> None:
    """A non-AI company penalized on AI-specific criteria: message keeps the raw
    criterion ids for the agent; founder_message states the plain-language
    consequence without any raw ids."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "not_ai"
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = False
    penalized_ids = {"ai_retention_rebased", "ai_cost_to_serve_shown"}
    other_ai_ids = {"ai_defensibility_beyond_model", "ai_responsible_controls"}
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in penalized_ids:
            items.append(
                {
                    "id": cid,
                    "category": "AI",
                    "label": "AI",
                    "status": "fail",
                    "evidence": "not shown",
                    "notes": None,
                }
            )
        elif cid in other_ai_ids:
            items.append(
                {
                    "id": cid,
                    "category": "AI",
                    "label": "AI",
                    "status": "not_applicable",
                    "evidence": "N/A",
                    "notes": None,
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 31,
            "fail": 2,
            "warn": 0,
            "not_applicable": 2,
            "score_pct": 88.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": sorted(penalized_ids),
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "AI_CRITERIA_ON_NON_AI" in codes
    warning = next(w for w in data["validation"]["warnings"] if w["code"] == "AI_CRITERIA_ON_NON_AI")
    for cid in penalized_ids:
        assert cid in warning["message"], "message must keep the raw criterion ids for the agent"
    assert "founder_message" in warning
    founder_msg = warning["founder_message"]
    for cid in penalized_ids:
        assert cid not in founder_msg
    assert founder_msg in data["report_markdown"]


def test_compose_checklist_critical() -> None:
    """Checklist with 12 failures -> CHECKLIST_FAILURES_CRITICAL."""
    fail_ids = _CHECKLIST_IDS[:12]
    items = []
    for cid in _CHECKLIST_IDS:
        if cid in fail_ids:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "fail",
                    "evidence": "test",
                    "notes": "bad",
                }
            )
        else:
            items.append(
                {
                    "id": cid,
                    "category": "Test",
                    "label": "Test",
                    "status": "pass",
                    "evidence": "test",
                    "notes": None,  # type: ignore[dict-item]
                }
            )
    checklist = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 23,
            "fail": 12,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 65.7,
            "overall_status": "needs_work",
            "by_category": {},
            "failed_items": [{"id": cid} for cid in fail_ids],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CHECKLIST_FAILURES_CRITICAL" in codes


def test_compose_strict_mode() -> None:
    """Missing artifact + --strict -> exit 1."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    rc, data, _ = _run_compose(d, extra_args=["--strict"])
    assert rc == 1
    assert data is not None


def test_compose_accepted_warning() -> None:
    """Accepted warning -> severity downgraded to acknowledged."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "reason": "Intentional -- raising Series A early", "match": "claims"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "acknowledged"


def test_compose_corrupt_artifact() -> None:
    """Corrupt JSON artifact -> CORRUPT_ARTIFACT warning, not MISSING_ARTIFACT."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    # Write corrupt JSON to checklist.json
    with open(os.path.join(d, "checklist.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "CORRUPT_ARTIFACT" in codes
    # checklist.json should NOT appear as MISSING_ARTIFACT
    missing_msgs = [w["message"] for w in data["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    assert not any("checklist.json" in m for m in missing_msgs)


def test_compose_severity_map_complete() -> None:
    """WARNING_SEVERITY contains all expected codes."""
    snippet = (
        f"import sys, os; sys.path.insert(0, '{DECK_REVIEW_DIR}'); "
        "from compose_report import WARNING_SEVERITY; "
        "import json; print(json.dumps(WARNING_SEVERITY))"
    )
    result = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True)
    try:
        sev_map = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(f"can't import WARNING_SEVERITY: stdout={result.stdout}, stderr={result.stderr}") from exc

    expected = [
        "CORRUPT_ARTIFACT",
        "MISSING_ARTIFACT",
        "STALE_ARTIFACT",
        "SCHEMA_VIOLATION",
        "MISSING_METADATA",
        "CHECKLIST_FAILURES_CRITICAL",
        "STAGE_MISMATCH",
        "SLIDE_COUNT_EXTREME",
        "UNCITED_CRITIQUE",
        "AI_CRITERIA_SKIPPED",
        "STAGE_OUT_OF_SCOPE",
        "UNSUPPORTED_CHECKLIST_CRITIQUE",
        "CHECKLIST_VALIDATION_FAILED",
        "AI_CRITERIA_ON_NON_AI",
        "AI_CRITERIA_MISSING",
        "NAME_DRIFT",
        "MARKER_COLLISION",
        "UNSUBSTANTIATED_AI_CLAIM",
        "DUPLICATE_SLIDE_NUMBER",
    ]
    assert len(sev_map) == len(expected), f"expected {len(expected)} codes, got {len(sev_map)}"
    for code in expected:
        assert code in sev_map, f"{code} missing from severity map"
    assert sev_map["STALE_ARTIFACT"] == "high"
    assert sev_map["STAGE_OUT_OF_SCOPE"] == "low"


def test_compose_stale_artifact_mismatched_run_ids() -> None:
    """Mismatched run_id across artifacts triggers STALE_ARTIFACT warning."""
    import copy

    inventory: dict[str, Any] = copy.deepcopy(_VALID_INVENTORY)
    inventory["metadata"] = {"run_id": "run-001"}
    profile: dict[str, Any] = copy.deepcopy(_VALID_PROFILE)
    profile["metadata"] = {"run_id": "run-001"}
    reviews: dict[str, Any] = copy.deepcopy(_VALID_REVIEWS)
    reviews["metadata"] = {"run_id": "run-002"}  # stale!
    checklist: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    checklist["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": reviews,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" in codes


def test_compose_matching_run_ids_no_stale_warning() -> None:
    """Matching run_id across all artifacts produces no STALE_ARTIFACT warning."""
    import copy

    artifacts: dict[str, dict[Any, Any]] = {
        "deck_inventory.json": copy.deepcopy(_VALID_INVENTORY),
        "stage_profile.json": copy.deepcopy(_VALID_PROFILE),
        "slide_reviews.json": copy.deepcopy(_VALID_REVIEWS),
        "checklist.json": copy.deepcopy(_VALID_CHECKLIST),
    }
    for art in artifacts.values():
        art["metadata"] = {"run_id": "run-001"}
    d = _make_artifact_dir(artifacts)
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_no_run_ids_graceful() -> None:
    """No run_id in any artifact -> graceful degradation, no STALE_ARTIFACT."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STALE_ARTIFACT" not in codes


def test_compose_stage_out_of_scope_detected() -> None:
    """detected_stage 'series_b' -> STAGE_OUT_OF_SCOPE warning."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_b"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_OUT_OF_SCOPE"]
    assert stage_w[0]["severity"] == "low"


def test_compose_stage_out_of_scope_claimed() -> None:
    """claimed_stage 'growth' + detected_stage 'series_a' -> STAGE_OUT_OF_SCOPE warning."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "growth"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes


def test_compose_stage_in_scope() -> None:
    """detected_stage 'seed' -> no STAGE_OUT_OF_SCOPE warning."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_no_stage_warnings_when_claimed_stage_omitted() -> None:
    """Deck states no stage (key omitted) -> no STAGE_MISMATCH / STAGE_OUT_OF_SCOPE."""
    inventory = dict(_VALID_INVENTORY)
    inventory.pop("claimed_stage")
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_no_stage_warnings_when_claimed_stage_null() -> None:
    """Deck states no stage (explicit null) -> no stage warnings and no SCHEMA_VIOLATION."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = None
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes
    assert "STAGE_OUT_OF_SCOPE" not in codes
    assert "SCHEMA_VIOLATION" not in codes


def test_compose_not_stated_sentinel_treated_as_absent() -> None:
    """A 'not stated' sentinel is not a stage assertion -> no stage warnings."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "Not stated"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_descriptive_claimed_stage_skips_stage_checks() -> None:
    """A descriptive (non-token) claimed_stage is not a stage assertion -> no stage warnings."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "the deck does not state a stage"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes
    assert "STAGE_OUT_OF_SCOPE" not in codes


def test_compose_recognized_claimed_stage_still_fires_out_of_scope() -> None:
    """A recognized-but-out-of-range claimed stage (series_c) still fires STAGE_OUT_OF_SCOPE."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "series_c"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_OUT_OF_SCOPE" in codes


def test_compose_report_sections() -> None:
    """Report markdown contains expected section headers."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    report = data["report_markdown"]
    assert "Pitch Deck Review: TestCo" in report
    assert "## Executive Summary" in report
    assert "## Stage Context" in report
    assert "## Slide-by-Slide Feedback" in report
    assert "## Checklist Results" in report
    assert "## Top 5 Priority Fixes" in report
    assert "## Appendix: Full Checklist" in report


def test_compose_strict_mode_writes_output_file() -> None:
    """--strict -o should write output file THEN exit 1."""
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
        }
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = run_script_raw(
            "compose_report.py",
            ["--dir", d, "--pretty", "--strict", "-o", tmp],
        )
        assert rc == 1
        assert os.path.exists(tmp)
        with open(tmp) as fh:
            data = json.load(fh)
        assert "report_markdown" in data
        assert "_strict_failed" not in json.dumps(data)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_compose_stage_mismatch_normalized() -> None:
    """pre-seed (hyphen) vs pre_seed (underscore) should NOT trigger STAGE_MISMATCH."""
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "pre-seed"
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "pre_seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "STAGE_MISMATCH" not in codes


def test_compose_malformed_field_types() -> None:
    """Artifact with wrong field type (string instead of list) should not crash."""
    checklist = dict(_VALID_CHECKLIST)
    checklist["items"] = "not a list"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None


def test_compose_malformed_by_category_does_not_crash() -> None:
    """summary.by_category set to a non-dict value (passes schema) must not crash rendering."""
    import copy

    checklist: dict[str, Any] = copy.deepcopy(_VALID_CHECKLIST)
    checklist["summary"]["by_category"] = {"Narrative Flow": "oops-not-a-dict"}
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0, stderr
    assert data is not None
    assert len(data["report_markdown"]) > 100


def test_compose_marker_collision_status_not_clean() -> None:
    """When MARKER_COLLISION is the only warning, status must be 'warnings', not 'clean'."""
    import copy

    reviews = copy.deepcopy(_VALID_REVIEWS)
    # Embed the marker prefix in a RENDERED body field so the pre-scan trips
    # MARKER_COLLISION (overall_narrative_assessment is rendered into the report).
    reviews["overall_narrative_assessment"] = "Narrative: <!-- COACHING_INSERTION_POINT_deadbeef --> embedded"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": reviews,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes
    # status must reflect the appended warning, not the pre-marker-append snapshot
    assert data["validation"]["status"] == "warnings"


def test_compose_acknowledged_warnings_counted_in_stderr() -> None:
    """Accepted (acknowledged) warnings are counted in the stderr summary line; no dead 'info' bucket."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "reason": "Intentional", "match": "claims"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, _, stderr = _run_compose(d)
    assert rc == 0
    assert "acknowledged" in stderr
    assert "info" not in stderr.lower().split("warnings:")[-1].split("\n")[0]


def test_compose_ai_criteria_missing_no_warning() -> None:
    """AI company with checklist missing AI items -> NO AI_CRITERIA_SKIPPED."""
    profile = dict(_VALID_PROFILE)
    profile["is_ai_company"] = True
    # Checklist with NO ai_ items at all (items list doesn't contain them)
    ai_ids = {
        "ai_retention_rebased",
        "ai_cost_to_serve_shown",
        "ai_defensibility_beyond_model",
        "ai_responsible_controls",
    }
    items = [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test", "notes": None}
        for cid in _CHECKLIST_IDS
        if cid not in ai_ids
    ]
    # Also need the AI items to be absent. But the checklist validator requires all 35.
    # The compose script reads checklist.json as an artifact - it doesn't re-validate.
    # So we can provide a checklist artifact with items that exclude AI items.
    checklist = {
        "items": items,
        "summary": {
            "total": 31,
            "pass": 31,
            "fail": 0,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "AI_CRITERIA_SKIPPED" not in codes


def test_compose_accepted_warning_case_insensitive() -> None:
    """Case-insensitive matching in accepted_warnings."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "reason": "Intentional raise", "match": "CLAIMS"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "acknowledged"


def test_compose_accepted_warning_missing_reason_skipped() -> None:
    """Accepted warning without reason field is skipped."""
    profile = dict(_VALID_PROFILE)
    profile["detected_stage"] = "series_a"
    profile["accepted_warnings"] = [
        {"code": "STAGE_MISMATCH", "match": "claims"},
    ]
    inventory = dict(_VALID_INVENTORY)
    inventory["claimed_stage"] = "seed"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, stderr = _run_compose(d)
    assert rc == 0
    assert data is not None
    stage_w = [w for w in data["validation"]["warnings"] if w["code"] == "STAGE_MISMATCH"]
    assert len(stage_w) == 1
    assert stage_w[0]["severity"] == "medium"  # NOT acknowledged
    assert "reason" in stderr.lower()


def test_checklist_fail_without_evidence_warned() -> None:
    """Fail item with empty evidence -> advisory stderr warning."""
    overrides = {
        "purpose_clear": {"status": "fail", "evidence": "", "notes": "bad"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, stderr = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "evidence" in stderr.lower()


def test_checklist_pass_without_evidence_warned() -> None:
    """Pass item with empty evidence -> non-fatal stderr warning + a structured
    entry in validation.warnings, but the run stays green: unlike a fail/warn
    item missing evidence (a hard error above), a self-graded pass with no
    evidence must NOT block the run or flip validation.status to invalid — it
    was previously never checked at all, so this only adds visibility."""
    overrides = {
        "purpose_clear": {"status": "pass", "evidence": "", "notes": "looks fine"},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    rc, data, stderr = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert "evidence" in stderr.lower()
    assert data["validation"]["status"] == "valid"
    assert data["validation"]["errors"] == []
    warnings = data["validation"]["warnings"]
    assert any("purpose_clear" in w and "pass" in w for w in warnings), warnings
    # Still counted as a pass — the warning is advisory, not a status override.
    assert data["summary"]["pass"] == 35
    assert data["summary"]["score_pct"] == 100.0


def test_checklist_pass_without_evidence_does_not_block_o_mode(tmp_path: Path) -> None:
    """In -o (producer) mode, a pass item with no evidence must still write the
    artifact and exit 0 — the new check is advisory-only, unlike the existing
    hard block on fail/warn items missing evidence."""
    overrides = {
        "purpose_clear": {"status": "pass", "evidence": "", "notes": None},
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})
    out = str(tmp_path / "checklist.json")
    rc, stdout, stderr = run_script_raw("checklist.py", ["--run-id", "test-run", "-o", out], stdin_data=payload)
    assert rc == 0, stderr
    assert os.path.exists(out), "artifact must still be written for an advisory-only warning"
    with open(out) as f:
        data = json.load(f)
    assert data["validation"]["status"] == "valid"
    assert any("purpose_clear" in w for w in data["validation"]["warnings"])


def test_checklist_no_pass_evidence_warnings_on_well_evidenced_run() -> None:
    """Regression guard: a normal run where every pass item carries evidence
    produces an empty validation.warnings list — the new check must not fire
    false positives on a clean run."""
    payload = json.dumps({"items": _make_checklist_items()})
    rc, data, _ = run_script("checklist.py", ["--pretty", "--run-id", "test-run"], stdin_data=payload)
    assert rc == 0
    assert data is not None
    assert data["validation"]["warnings"] == []


# ---------------------------------------------------------------------------
# Framing disclaimer tests
# ---------------------------------------------------------------------------


def _complete_artifacts() -> dict[str, dict]:
    """Return all 4 valid deck-review artifacts."""
    return {
        "deck_inventory.json": _VALID_INVENTORY,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": _VALID_REVIEWS,
        "checklist.json": _VALID_CHECKLIST,
    }


def test_compose_benchmarks_framing() -> None:
    """Report contains 'reference data' framing for stage benchmarks."""
    d = _make_artifact_dir(_complete_artifacts())
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d, "--pretty"])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "reference data" in md


def test_compose_slide_framing() -> None:
    """Report contains agent evaluation framing for slide reviews."""
    d = _make_artifact_dir(_complete_artifacts())
    rc, data, _stderr = run_script("compose_report.py", ["--dir", d, "--pretty"])
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    assert "agent" in md.lower()


def test_checklist_output_includes_metadata_run_id(tmp_path: Path) -> None:
    """checklist.py output includes metadata.run_id when --run-id is provided."""
    items = [{"id": id_, "status": "pass", "evidence": "x", "notes": "y"} for id_ in _CHECKLIST_IDS]
    out = str(tmp_path / "checklist.json")
    rc, _, err = run_script(
        "checklist.py",
        ["--run-id", "20260503T120000Z", "-o", out],
        stdin_data=json.dumps({"items": items}),
    )
    assert rc == 0, err
    with open(out) as f:
        checklist = json.load(f)
    assert checklist["metadata"]["run_id"] == "20260503T120000Z"
    assert len(checklist["items"]) == 35


def test_compose_emits_schema_violation_for_malformed_checklist(tmp_path: Path) -> None:
    """A checklist.json that's section-keyed (issue #2 shape) must trigger SCHEMA_VIOLATION."""
    review_dir = tmp_path / "deck-review-acme"
    review_dir.mkdir()
    # Write valid inventory, profile, reviews
    (review_dir / "deck_inventory.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "Acme",
                "review_date": "2026-05-03",
                "input_format": "pdf",
                "total_slides": 1,
                "ai_company_status": "not_ai",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    (review_dir / "stage_profile.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "detected_stage": "seed",
                "confidence": "high",
                "evidence": [],
                "is_ai_company": False,
                "expected_framework": [],
                "stage_benchmarks": {"round_size_range": "x", "expected_traction": "y", "runway_expectation": "z"},
                "reference_file_read": [],
            }
        )
    )
    (review_dir / "slide_reviews.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "reviews": [],
                "missing_slides": [],
                "overall_narrative_assessment": "x",
            }
        )
    )
    # Malformed checklist — section-keyed, exactly the shape from issue #2
    (review_dir / "checklist.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "narrative_section": {"items": []},
                "summary": {
                    "total": 35,
                    "pass": 30,
                    "fail": 5,
                    "warn": 0,
                    "not_applicable": 0,
                    "score_pct": 85.7,
                    "overall_status": "strong",
                },
            }
        )
    )

    rc, out, stderr = run_script(
        "compose_report.py",
        ["--dir", str(review_dir), "--pretty"],
    )
    assert out is not None, stderr
    warnings = out["validation"]["warnings"]
    codes = [w["code"] for w in warnings]
    assert "SCHEMA_VIOLATION" in codes
    schema_warning = next(w for w in warnings if w["code"] == "SCHEMA_VIOLATION")
    assert "checklist.json" in schema_warning["message"]
    assert schema_warning["severity"] == "high"


def test_compose_emits_missing_metadata_for_artifact_without_run_id(tmp_path: Path) -> None:
    review_dir = tmp_path / "deck-review-acme"
    review_dir.mkdir()
    # Inventory with NO metadata block (issue #1 shape) — note: missing metadata means
    # MISSING_METADATA fires; the inventory loads and ai_company_status is readable.
    (review_dir / "deck_inventory.json").write_text(
        json.dumps(
            {
                "company_name": "Acme",
                "review_date": "2026-05-03",
                "input_format": "pdf",
                "total_slides": 1,
                "ai_company_status": "not_ai",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    # All others have metadata
    (review_dir / "stage_profile.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "detected_stage": "seed",
                "confidence": "high",
                "evidence": [],
                "is_ai_company": False,
                "expected_framework": [],
                "stage_benchmarks": {"round_size_range": "x", "expected_traction": "y", "runway_expectation": "z"},
                "reference_file_read": [],
            }
        )
    )
    (review_dir / "slide_reviews.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "reviews": [],
                "missing_slides": [],
                "overall_narrative_assessment": "x",
            }
        )
    )
    items = [{"id": id_, "category": "x", "label": "x", "status": "pass"} for id_ in _CHECKLIST_IDS]
    (review_dir / "checklist.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "items": items,
                "summary": {
                    "total": 35,
                    "pass": 35,
                    "fail": 0,
                    "warn": 0,
                    "not_applicable": 0,
                    "score_pct": 100.0,
                    "overall_status": "strong",
                },
            }
        )
    )

    rc, out, _ = run_script("compose_report.py", ["--dir", str(review_dir), "--pretty"])
    assert out is not None
    codes = [w["code"] for w in out["validation"]["warnings"]]
    assert "MISSING_METADATA" in codes


def test_compose_writes_report_md_directly(tmp_path: Path) -> None:
    """compose --write-md emits report.md alongside report.json with the same markdown."""
    review_dir = tmp_path / "deck-review-acme"
    review_dir.mkdir()
    items = [{"id": id_, "category": "x", "label": "x", "status": "pass"} for id_ in _CHECKLIST_IDS]
    (review_dir / "deck_inventory.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "Acme",
                "review_date": "2026-05-03",
                "input_format": "pdf",
                "total_slides": 1,
                "ai_company_status": "not_ai",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    (review_dir / "stage_profile.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "detected_stage": "seed",
                "confidence": "high",
                "evidence": [],
                "is_ai_company": False,
                "expected_framework": [],
                "stage_benchmarks": {"round_size_range": "x", "expected_traction": "y", "runway_expectation": "z"},
                "reference_file_read": [],
            }
        )
    )
    (review_dir / "slide_reviews.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "reviews": [],
                "missing_slides": [],
                "overall_narrative_assessment": "x",
            }
        )
    )
    (review_dir / "checklist.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "items": items,
                "summary": {
                    "total": 35,
                    "pass": 35,
                    "fail": 0,
                    "warn": 0,
                    "not_applicable": 0,
                    "score_pct": 100.0,
                    "overall_status": "strong",
                },
            }
        )
    )
    json_path = str(review_dir / "report.json")
    md_path = str(review_dir / "report.md")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", str(review_dir), "-o", json_path, "--write-md", md_path],
    )
    assert rc == 0, err
    with open(json_path) as f:
        composed = json.load(f)
    with open(md_path) as f:
        md_text = f.read()
    # The two must be byte-identical (modulo trailing newline)
    assert composed["report_markdown"].rstrip("\n") == md_text.rstrip("\n")
    # And also a valid round-trip JSON (folds in the v1 Task 11 self-check)
    with open(json_path) as f:
        json.load(f)


def test_compose_emits_name_drift_when_report_contains_close_variant(tmp_path: Path) -> None:
    """NAME_DRIFT fires when slide content has variants of company_name.

    Fixture uses placeholder names ('Acmecorp' canonical, 'ACMECORP' case-variant in
    headline, 'Acmacorp' near-miss spelling in content_summary) — never use real
    founder names from prior reviews in committed test fixtures.
    """
    review_dir = tmp_path / "deck-review-acmecorp"
    review_dir.mkdir()
    items = [{"id": id_, "category": "x", "label": "x", "status": "pass"} for id_ in _CHECKLIST_IDS]
    (review_dir / "deck_inventory.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "Acmecorp",
                "review_date": "2026-05-03",
                "input_format": "pdf",
                "total_slides": 1,
                "ai_company_status": "not_ai",
                "slides": [
                    {
                        "number": 1,
                        "headline": "ACMECORP: Cloud platform for SMBs",
                        "content_summary": "Acmacorp provides accounting tools.",
                    }
                ],
            }
        )
    )
    (review_dir / "stage_profile.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "detected_stage": "seed",
                "confidence": "high",
                "evidence": [],
                "is_ai_company": False,
                "expected_framework": [],
                "stage_benchmarks": {"round_size_range": "x", "expected_traction": "y", "runway_expectation": "z"},
                "reference_file_read": [],
            }
        )
    )
    (review_dir / "slide_reviews.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "reviews": [],
                "missing_slides": [],
                "overall_narrative_assessment": "x",
            }
        )
    )
    (review_dir / "checklist.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "items": items,
                "summary": {
                    "total": 35,
                    "pass": 35,
                    "fail": 0,
                    "warn": 0,
                    "not_applicable": 0,
                    "score_pct": 100.0,
                    "overall_status": "strong",
                },
            }
        )
    )
    rc, out, _ = run_script("compose_report.py", ["--dir", str(review_dir), "--pretty"])
    assert out is not None
    codes = [w["code"] for w in out["validation"]["warnings"]]
    assert "NAME_DRIFT" in codes


def _name_drift_codes(company_name: str, *, headline: str = "", content_summary: str = "") -> list[str]:
    """Compose one slide with the given brand + text and return the warning codes."""
    inventory = dict(_VALID_INVENTORY)
    inventory["company_name"] = company_name
    inventory["slides"] = [
        {
            "number": 1,
            "headline": headline,
            "content_summary": content_summary,
            "visuals": "",
            "word_count_estimate": 10,
        }
    ]
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0 and data is not None
    return [w["code"] for w in data["validation"]["warnings"]]


def test_compose_no_name_drift_for_brand_inside_domain_or_email() -> None:
    """A conventionally-lowercase brand inside a domain/email is not name drift."""
    codes = _name_drift_codes(
        "Acmecorp",
        content_summary="Visit acmecorp.net or write to sam@acmecorp.net for a demo.",
    )
    assert "NAME_DRIFT" not in codes


def test_compose_no_name_drift_for_lowercase_common_word() -> None:
    """An ordinary lowercase word within edit distance of the brand is not name drift."""
    # SequenceMatcher("brandly", "brandy").ratio() == 0.923 -> trips the current fuzzy path.
    codes = _name_drift_codes("Brandly", content_summary="aged brandy tasting notes")
    assert "NAME_DRIFT" not in codes


def test_compose_no_name_drift_for_lowercase_product_term_echoing_brand() -> None:
    """A lowercase common noun the deck uses as a product term is not name drift."""
    codes = _name_drift_codes("Mesh", content_summary="our mesh routing layer connects every device")
    assert "NAME_DRIFT" not in codes


def test_compose_name_drift_fires_for_cased_misspelling() -> None:
    """A cased misspelling of the brand still flags NAME_DRIFT (true positive preserved)."""
    codes = _name_drift_codes("Acmecorp", content_summary="Acmacorp provides accounting tools.")
    assert "NAME_DRIFT" in codes


def test_compose_name_drift_fires_for_all_caps_variant() -> None:
    """An ALL-CAPS variant of the brand still flags NAME_DRIFT (true positive preserved)."""
    codes = _name_drift_codes("Acmecorp", headline="ACMECORP: Cloud platform for SMBs")
    assert "NAME_DRIFT" in codes


def test_compose_no_name_drift_for_singular_of_plural_brand() -> None:
    """A cased singular of a plural brand name is morphology, not drift."""
    # SequenceMatcher("foo", "foos").ratio() == 0.857 -> trips the fuzzy path today.
    codes = _name_drift_codes("Foos", content_summary="Each Foo ships with a sensor kit.")
    assert "NAME_DRIFT" not in codes


def test_compose_no_name_drift_for_plural_of_brand() -> None:
    """A cased plural of the brand name is morphology, not drift."""
    codes = _name_drift_codes("Foo", content_summary="Foos deployed across three regions.")
    assert "NAME_DRIFT" not in codes


def test_compose_no_name_drift_for_cased_word_sharing_brand_root() -> None:
    """A capitalized product noun that is the brand minus its leading affix is not drift."""
    # SequenceMatcher("foos", "efoos").ratio() == 0.889 -> trips the fuzzy path today.
    codes = _name_drift_codes("eFoos", content_summary="Foos connect to the hub over BLE.")
    assert "NAME_DRIFT" not in codes


def test_compose_name_drift_fires_for_internal_extra_letter() -> None:
    """An internally-altered cased variant still flags (doubled interior letter)."""
    codes = _name_drift_codes("Acmecorp", content_summary="Acmeecorp provides accounting tools.")
    assert "NAME_DRIFT" in codes


# === v0.4.1 Phase 3 Task 7: compose post-write verification ===


def _make_full_review_dir(review_dir: Path) -> None:
    """Populate review_dir with all 4 valid artifacts needed for compose."""
    items = [{"id": id_, "category": "x", "label": "x", "status": "pass"} for id_ in _CHECKLIST_IDS]
    (review_dir / "deck_inventory.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "Acme",
                "review_date": "2026-05-03",
                "input_format": "pdf",
                "total_slides": 1,
                "ai_company_status": "not_ai",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    (review_dir / "stage_profile.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "detected_stage": "seed",
                "confidence": "high",
                "evidence": [],
                "is_ai_company": False,
                "expected_framework": [],
                "stage_benchmarks": {
                    "round_size_range": "x",
                    "expected_traction": "y",
                    "runway_expectation": "z",
                },
                "reference_file_read": [],
            }
        )
    )
    (review_dir / "slide_reviews.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "reviews": [],
                "missing_slides": [],
                "overall_narrative_assessment": "x",
            }
        )
    )
    (review_dir / "checklist.json").write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "items": items,
                "summary": {
                    "total": 35,
                    "pass": 35,
                    "fail": 0,
                    "warn": 0,
                    "not_applicable": 0,
                    "score_pct": 100.0,
                    "overall_status": "strong",
                },
            }
        )
    )


def test_compose_verifies_outputs_exist_after_write(tmp_path: Path) -> None:
    """After successful compose, both report.json and report.md must exist on disk."""
    review_dir = tmp_path / "deck-review-acme"
    review_dir.mkdir()
    _make_full_review_dir(review_dir)
    json_path = str(review_dir / "report.json")
    md_path = str(review_dir / "report.md")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", str(review_dir), "-o", json_path, "--write-md", md_path],
    )
    assert rc == 0, err
    assert os.path.isfile(json_path)
    assert os.path.isfile(md_path)
    assert os.path.getsize(json_path) > 0
    assert os.path.getsize(md_path) > 0


def test_compose_exits_nonzero_if_write_md_path_unwritable(tmp_path: Path) -> None:
    """Compose must exit nonzero if --write-md target dir doesn't exist and can't be created."""
    review_dir = tmp_path / "deck-review-acme"
    review_dir.mkdir()
    _make_full_review_dir(review_dir)
    # Point --write-md at a path inside a read-only parent
    ro_parent = tmp_path / "readonly"
    ro_parent.mkdir(mode=0o555)
    bad_md_path = str(ro_parent / "no-write" / "report.md")
    json_path = str(review_dir / "report.json")
    rc, _, err = run_script(
        "compose_report.py",
        ["--dir", str(review_dir), "-o", json_path, "--write-md", bad_md_path],
    )
    assert rc != 0, "compose should exit nonzero when --write-md target is unwritable"
    # Cleanup: restore writable mode so tmp_path can be deleted
    os.chmod(ro_parent, 0o755)


# === v0.4.1 Phase 3 Task 7: tolerant JSON extraction ===


def test_extract_dispatch_json_raw_object() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_dispatch_json_fenced() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    assert extract_dispatch_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_dispatch_json_nested() -> None:
    """Critical regression test: must not truncate on inner }."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = '```json\n{"a": {"b": 1}, "c": 2}\n```'
    assert extract_dispatch_json(text) == {"a": {"b": 1}, "c": 2}


def test_extract_dispatch_json_embedded_in_prose() -> None:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    text = 'Here is the result:\n{"a": 1, "b": 2}\nLet me know if anything is wrong.'
    assert extract_dispatch_json(text) == {"a": 1, "b": 2}


def test_extract_dispatch_json_raises_when_no_json() -> None:
    import sys

    import pytest

    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "deck-review", "scripts"))
    from _dispatch_json import extract_dispatch_json  # type: ignore[import-not-found]

    with pytest.raises(ValueError):
        extract_dispatch_json("Just some prose with no JSON object anywhere.")


# -- v0.4.2 Mitigation 2: coaching_payload + uuid insertion marker --


def _make_v042_artifact_dir(
    inventory_overrides: dict | None = None,
    profile_overrides: dict | None = None,
    reviews_overrides: dict | None = None,
    checklist_overrides: dict | None = None,
) -> str:
    """Build a complete artifact dir with valid run_ids, applying optional overrides."""
    inventory = {**_VALID_INVENTORY, **(inventory_overrides or {})}
    profile = {**_VALID_PROFILE, **(profile_overrides or {})}
    reviews = {**_VALID_REVIEWS, **(reviews_overrides or {})}
    checklist = {**_VALID_CHECKLIST, **(checklist_overrides or {})}
    return _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": profile,
            "slide_reviews.json": reviews,
            "checklist.json": checklist,
        }
    )


def test_compose_emits_coaching_payload() -> None:
    """compose emits a coaching_payload block with all v0.4.2 fields."""
    import re

    d = _make_v042_artifact_dir()
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    assert "coaching_payload" in data, "report.json missing coaching_payload block"

    payload = data["coaching_payload"]
    assert payload["schema_version"] == "v0.4.2-deck-review"

    # All expected top-level keys present
    for key in (
        "schema_version",
        "summary",
        "failed_items",
        "warned_items",
        "high_severity_warnings",
        "stage",
        "ai_company_status",
        "company_name",
        "review_dir",
        "report_path",
        "insertion_marker",
    ):
        assert key in payload, f"coaching_payload missing key: {key}"

    # Summary mirrors checklist counts
    s = payload["summary"]
    for sk in ("score_pct", "overall_status", "total", "pass", "fail", "warn", "not_applicable"):
        assert sk in s, f"coaching_payload.summary missing {sk}"

    # Stage / company / ai surfaced from artifacts
    assert payload["stage"] == "seed"
    assert payload["ai_company_status"] == "not_ai"
    assert payload["company_name"] == "TestCo"

    # Insertion marker matches uuid format
    assert re.fullmatch(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", payload["insertion_marker"]), (
        f"unexpected marker shape: {payload['insertion_marker']}"
    )

    # Backward-compat: existing top-level keys still present
    assert "report_markdown" in data
    assert "validation" in data


def test_compose_inserts_uuid_marker() -> None:
    """report.md contains exactly one uuid marker matching coaching_payload.insertion_marker."""
    import re

    d = _make_v042_artifact_dir()
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None

    md = data["report_markdown"]
    matches = re.findall(r"<!-- COACHING_INSERTION_POINT_[0-9a-f]{8} -->", md)
    assert len(matches) == 1, f"expected exactly one marker, found {len(matches)}: {matches}"
    assert matches[0] == data["coaching_payload"]["insertion_marker"], (
        "marker in report.md must equal coaching_payload.insertion_marker"
    )


def test_compose_warns_on_marker_collision() -> None:
    """Body content containing the marker substring triggers MARKER_COLLISION (non-fatal)."""
    # Adversarial: an evidence string that contains the literal marker substring.
    adversarial_items = [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test", "notes": None}
        for cid in _CHECKLIST_IDS
    ]
    # Inject marker substring into one fail item's evidence (which is rendered in report.md)
    adversarial_items[0] = {
        "id": _CHECKLIST_IDS[0],
        "category": "Narrative Flow",
        "label": "Test fail",
        "status": "fail",
        "evidence": "Sneaky body content with <!-- COACHING_INSERTION_POINT_aaaaaaaa --> embedded",
        "notes": "Watch out",
    }
    checklist_overrides = {
        "items": adversarial_items,
        "summary": {
            "total": 35,
            "pass": 34,
            "fail": 1,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 97.1,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [
                {
                    "id": _CHECKLIST_IDS[0],
                    "category": "Narrative Flow",
                    "label": "Test fail",
                    "evidence": "Sneaky body content with <!-- COACHING_INSERTION_POINT_aaaaaaaa --> embedded",
                    "notes": "Watch out",
                }
            ],
            "warned_items": [],
        },
    }

    d = _make_v042_artifact_dir(checklist_overrides=checklist_overrides)
    rc, data, err = _run_compose(d)
    # Compose still succeeds (warning, not error)
    assert rc == 0, err
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "MARKER_COLLISION" in codes, f"expected MARKER_COLLISION in warnings, got: {codes}"


def test_payload_arrays_match_summary_counts() -> None:
    """coaching_payload.failed_items length matches summary.fail; warned_items matches summary.warn."""
    items = [
        {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "test", "notes": None}
        for cid in _CHECKLIST_IDS
    ]
    # 2 fails, 1 warn
    items[0] = {
        "id": _CHECKLIST_IDS[0],
        "category": "Narrative Flow",
        "label": "L0",
        "status": "fail",
        "evidence": "e",
        "notes": "n",
    }
    items[1] = {
        "id": _CHECKLIST_IDS[1],
        "category": "Narrative Flow",
        "label": "L1",
        "status": "fail",
        "evidence": "e",
        "notes": "n",
    }
    items[2] = {
        "id": _CHECKLIST_IDS[2],
        "category": "Narrative Flow",
        "label": "L2",
        "status": "warn",
        "evidence": "e",
        "notes": "n",
    }

    failed_items = [
        {"id": _CHECKLIST_IDS[0], "category": "Narrative Flow", "label": "L0", "evidence": "e", "notes": "n"},
        {"id": _CHECKLIST_IDS[1], "category": "Narrative Flow", "label": "L1", "evidence": "e", "notes": "n"},
    ]
    warned_items = [
        {"id": _CHECKLIST_IDS[2], "category": "Narrative Flow", "label": "L2", "evidence": "e", "notes": "n"},
    ]
    checklist_overrides = {
        "items": items,
        "summary": {
            "total": 35,
            "pass": 32,
            "fail": 2,
            "warn": 1,
            "not_applicable": 0,
            "score_pct": 91.4,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": failed_items,
            "warned_items": warned_items,
        },
    }

    d = _make_v042_artifact_dir(checklist_overrides=checklist_overrides)
    rc, data, err = _run_compose(d)
    assert rc == 0, err
    assert data is not None
    payload = data["coaching_payload"]
    assert len(payload["failed_items"]) == payload["summary"]["fail"] == 2
    assert len(payload["warned_items"]) == payload["summary"]["warn"] == 1


# ============================================================
# Artifact self-sufficiency fixes (items 1-4)
# ============================================================


def _complete_artifacts_with_slide() -> dict[str, dict]:
    """All 4 valid artifacts with a slide that has a headline."""
    inventory = dict(_VALID_INVENTORY)
    inventory["slides"] = [
        {
            "number": 1,
            "headline": "TestCo — Cloud Accounting for SMBs",
            "content_summary": "Company intro",
            "visuals": "Logo",
            "word_count_estimate": 15,
        },
        {
            "number": 2,
            "headline": "Problem: Accounting is Broken",
            "content_summary": "Problem description",
        },
    ]
    reviews = dict(_VALID_REVIEWS)
    reviews["reviews"] = [
        {
            "slide_number": 1,
            "maps_to": "purpose_traction",
            "strengths": ["Clear one-liner"],
            "weaknesses": ["Could add ICP specificity"],
            "recommendations": ["Add target customer segment"],
            "best_practice_refs": ["Sequoia: single declarative sentence"],
        },
        {
            "slide_number": 2,
            "maps_to": "problem",
            "strengths": [],
            "weaknesses": ["Not quantified"],
            "recommendations": ["Add market size"],
            "best_practice_refs": ["YC: problem slide must quantify pain"],
        },
    ]
    return {
        "deck_inventory.json": inventory,
        "stage_profile.json": _VALID_PROFILE,
        "slide_reviews.json": reviews,
        "checklist.json": _VALID_CHECKLIST,
    }


def test_compose_slide_feedback_includes_headline() -> None:
    """Slide headers in report include the slide headline when inventory is present."""
    d = _make_artifact_dir(_complete_artifacts_with_slide())
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Slide headers must include the headline in quotes
    assert '### Slide 1: "TestCo — Cloud Accounting for SMBs"' in md
    assert '### Slide 2: "Problem: Accounting is Broken"' in md


def test_compose_slide_feedback_graceful_without_inventory() -> None:
    """Slide headers fall back to 'Slide N (maps_to)' when inventory is missing."""
    d = _make_artifact_dir(
        {
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Falls back to plain slide header
    assert "### Slide 1 (purpose_traction)" in md


def test_compose_full_checklist_has_evidence_column() -> None:
    """Full checklist appendix includes an Evidence column."""
    d = _make_artifact_dir(_complete_artifacts_with_slide())
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # The appendix header must have Evidence
    assert "| Evidence |" in md
    # Every item row should render evidence — the fixture uses "test" as evidence
    assert "test" in md.split("## Appendix: Full Checklist")[1]


def test_compose_full_checklist_evidence_empty_safe() -> None:
    """Full checklist appendix does not crash when evidence is missing."""
    checklist_no_evidence = {
        "metadata": {"run_id": "run-test"},
        "items": [{"id": cid, "category": "Test", "label": "TestLabel", "status": "pass"} for cid in _CHECKLIST_IDS],
        "summary": {
            "total": 35,
            "pass": 35,
            "fail": 0,
            "warn": 0,
            "not_applicable": 0,
            "score_pct": 100.0,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist_no_evidence,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    assert "## Appendix: Full Checklist" in data["report_markdown"]


def test_compose_warned_items_include_evidence() -> None:
    """Warned items in checklist section include 'Basis:' evidence line."""
    checklist_with_warn = {
        "metadata": {"run_id": "run-test"},
        "items": [
            {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "ok"}
            for cid in _CHECKLIST_IDS
        ],
        "summary": {
            "total": 35,
            "pass": 34,
            "fail": 0,
            "warn": 1,
            "not_applicable": 0,
            "score_pct": 97.1,
            "overall_status": "strong",
            "by_category": {},
            "failed_items": [],
            "warned_items": [
                {
                    "id": "minimal_text",
                    "category": "Design & Readability",
                    "label": "Minimal Text",
                    "evidence": "Slide 4 has 200+ words",
                    "notes": "Dense slides hurt readability",
                }
            ],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist_with_warn,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Evidence for warned items must appear as Basis line
    assert "*Basis: Slide 4 has 200+ words*" in md


def test_compose_exec_summary_scoring_footnote() -> None:
    """Executive summary includes scoring formula footnote and score-if-all-fixed."""
    checklist_mixed = {
        "metadata": {"run_id": "run-test"},
        "items": [
            {"id": cid, "category": "Test", "label": "Test", "status": "pass", "evidence": "ok"}
            for cid in _CHECKLIST_IDS
        ],
        "summary": {
            "total": 35,
            "pass": 28,
            "fail": 4,
            "warn": 3,
            "not_applicable": 0,
            "score_pct": 80.0,
            "overall_status": "solid",
            "by_category": {},
            "failed_items": [],
            "warned_items": [],
        },
    }
    d = _make_artifact_dir(
        {
            "deck_inventory.json": _VALID_INVENTORY,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": checklist_mixed,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    md = data["report_markdown"]
    # Footnote must state the formula
    assert "pass ÷ applicable" in md
    # Score-if-all-fixed: (28+4+3)/35 = 100%
    assert "100.0%" in md or "If all fixable items were resolved" in md


# ---------------------------------------------------------------------------
# ai_company_status gating tests (TDD — new feature)
# ---------------------------------------------------------------------------


_AI_CRITERIA_IDS = [
    "ai_retention_rebased",
    "ai_cost_to_serve_shown",
    "ai_defensibility_beyond_model",
    "ai_responsible_controls",
]


def _make_all_evaluated_checklist_items() -> list[dict]:
    """All 35 items evaluated (the sub-agent assesses all — producer does gating)."""
    overrides = {
        cid: {"status": "fail", "evidence": "No evidence of this in the deck.", "notes": "Evaluated."}
        for cid in _AI_CRITERIA_IDS
    }
    return _make_checklist_items(overrides=overrides)


def test_checklist_gating_not_ai_forces_ai_criteria_not_applicable(tmp_path: Path) -> None:
    """When --inventory ai_company_status=not_ai, the 4 AI criteria are forced to
    not_applicable with the Auto-gated evidence prefix — regardless of sub-agent status."""
    inv_path = tmp_path / "deck_inventory.json"
    inv_path.write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "TestCo",
                "review_date": "2026-06-01",
                "input_format": "pdf",
                "total_slides": 10,
                "ai_company_status": "not_ai",
                "ai_evidence": "No AI claim.",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for ai_id in _AI_CRITERIA_IDS:
        item = items_by_id[ai_id]
        assert item["status"] == "not_applicable", f"{ai_id} should be not_applicable for not_ai, got {item['status']}"
        assert item.get("evidence", "").startswith("Auto-gated:"), (
            f"{ai_id} evidence should start with 'Auto-gated:', got: {item.get('evidence')}"
        )
        assert "not_ai" in item.get("evidence", ""), f"{ai_id} evidence should mention not_ai"

    # Summary must reflect 4 N/A
    summary = data["summary"]
    assert summary["not_applicable"] == 4, f"expected 4 N/A, got {summary['not_applicable']}"


def test_checklist_gating_ai_core_keeps_sub_agent_statuses(tmp_path: Path) -> None:
    """When --inventory ai_company_status=ai_core, the 4 AI criteria are kept as-is (scored)."""
    inv_path = tmp_path / "deck_inventory.json"
    inv_path.write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "TestCo",
                "review_date": "2026-06-01",
                "input_format": "pdf",
                "total_slides": 10,
                "ai_company_status": "ai_core",
                "ai_evidence": "ML model in core value prop.",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for ai_id in _AI_CRITERIA_IDS:
        item = items_by_id[ai_id]
        # Sub-agent set them to fail; ai_core keeps them scored (not forced N/A)
        assert item["status"] == "fail", f"{ai_id} should remain 'fail' for ai_core, got {item['status']}"
        assert not item.get("evidence", "").startswith("Auto-gated:"), (
            f"{ai_id} evidence should NOT be Auto-gated for ai_core"
        )


def test_checklist_gating_ai_claimed_unverified_keeps_sub_agent_statuses(tmp_path: Path) -> None:
    """When --inventory ai_company_status=ai_claimed_unverified, the 4 AI criteria are kept
    as-is (scored — bar is relevant because they claim it)."""
    inv_path = tmp_path / "deck_inventory.json"
    inv_path.write_text(
        json.dumps(
            {
                "metadata": {"run_id": "r1"},
                "company_name": "TestCo",
                "review_date": "2026-06-01",
                "input_format": "pdf",
                "total_slides": 10,
                "ai_company_status": "ai_claimed_unverified",
                "ai_evidence": "Deck says 'AI-powered' but no core-AI signals.",
                "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
            }
        )
    )
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for ai_id in _AI_CRITERIA_IDS:
        item = items_by_id[ai_id]
        # Sub-agent set them to fail; ai_claimed_unverified keeps them scored
        assert item["status"] == "fail", f"{ai_id} should remain 'fail' for ai_claimed_unverified, got {item['status']}"
        assert not item.get("evidence", "").startswith("Auto-gated:"), (
            f"{ai_id} evidence should NOT be Auto-gated for ai_claimed_unverified"
        )


def test_checklist_gating_absent_inventory_no_gating(tmp_path: Path) -> None:
    """When --inventory is NOT provided, no gating is applied — backward-compatible."""
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for ai_id in _AI_CRITERIA_IDS:
        item = items_by_id[ai_id]
        # No --inventory: sub-agent's fail status unchanged
        assert item["status"] == "fail", f"{ai_id} should remain 'fail' when no --inventory, got {item['status']}"


# ---------------------------------------------------------------------------
# input_format="text" -> Design & Readability gating tests (TDD — new feature)
# ---------------------------------------------------------------------------

_DESIGN_CRITERIA_IDS = [
    "one_idea_per_slide",
    "minimal_text",
    "slide_count_appropriate",
    "consistent_design",
    "mobile_readable",
]


def _make_all_evaluated_checklist_items_design_fail() -> list[dict]:
    """All 35 items evaluated; the 5 Design & Readability items scored fail (as a
    sub-agent would on a text-described deck if it were not gated) so a passing
    gating test can distinguish gated-N/A from an unrelated sub-agent 'pass'."""
    overrides = {
        cid: {"status": "fail", "evidence": "No slide to assess for this.", "notes": "Evaluated."}
        for cid in _DESIGN_CRITERIA_IDS
    }
    return _make_checklist_items(overrides=overrides)


def _inventory_with_input_format(input_format: str) -> dict:
    # ai_company_status="ai_core" is a deliberate no-op for the AI gate (see
    # test_checklist_gating_ai_core_keeps_sub_agent_statuses) so these tests
    # isolate the Design gate; a combined-gates test covers both firing together.
    return {
        "metadata": {"run_id": "r1"},
        "company_name": "TestCo",
        "review_date": "2026-06-01",
        "input_format": input_format,
        "total_slides": 10,
        "ai_company_status": "ai_core",
        "ai_evidence": "ML model in core value prop.",
        "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
    }


def test_checklist_gating_input_format_text_forces_design_not_applicable(tmp_path: Path) -> None:
    """When --inventory's input_format=="text" (founder described slides in
    conversation rather than uploading a file), the 5 Design & Readability
    criteria are forced to not_applicable with the Auto-gated evidence prefix —
    regardless of what the sub-agent scored them, exactly mirroring the
    ai_company_status=not_ai AI-criteria gate."""
    inv_path = tmp_path / "deck_inventory.json"
    inv_path.write_text(json.dumps(_inventory_with_input_format("text")))
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items_design_fail()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for design_id in _DESIGN_CRITERIA_IDS:
        item = items_by_id[design_id]
        assert item["status"] == "not_applicable", (
            f"{design_id} should be not_applicable for input_format=text, got {item['status']}"
        )
        assert item.get("evidence", "").startswith("Auto-gated:"), (
            f"{design_id} evidence should start with 'Auto-gated:', got: {item.get('evidence')}"
        )
        assert "input_format=text" in item.get("evidence", ""), f"{design_id} evidence should mention input_format"

    # Summary must reflect 5 N/A and drop them from the applicable denominator.
    summary = data["summary"]
    assert summary["not_applicable"] == 5, f"expected 5 N/A, got {summary['not_applicable']}"


def test_checklist_gating_input_format_pdf_keeps_sub_agent_statuses(tmp_path: Path) -> None:
    """When --inventory's input_format is a real file format (e.g. pdf), the 5
    Design & Readability criteria are kept as the sub-agent scored them — the
    gate is a no-op outside input_format=='text'."""
    inv_path = tmp_path / "deck_inventory.json"
    inv_path.write_text(json.dumps(_inventory_with_input_format("pdf")))
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items_design_fail()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for design_id in _DESIGN_CRITERIA_IDS:
        item = items_by_id[design_id]
        assert item["status"] == "fail", f"{design_id} should remain 'fail' for input_format=pdf, got {item['status']}"
        assert not item.get("evidence", "").startswith("Auto-gated:"), (
            f"{design_id} evidence should NOT be Auto-gated for input_format=pdf"
        )


def test_checklist_gating_absent_inventory_no_design_gating(tmp_path: Path) -> None:
    """When --inventory is NOT provided, no Design gating is applied either —
    backward-compatible, same as the AI-criteria gate."""
    out_path = str(tmp_path / "checklist.json")
    payload = json.dumps({"items": _make_all_evaluated_checklist_items_design_fail()})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for design_id in _DESIGN_CRITERIA_IDS:
        item = items_by_id[design_id]
        assert item["status"] == "fail", f"{design_id} should remain 'fail' when no --inventory, got {item['status']}"


def test_checklist_gating_ai_and_design_gates_both_apply(tmp_path: Path) -> None:
    """not_ai + input_format=='text' together gate 4 AI + 5 Design criteria (9
    total) in one pass — the two gates must compose rather than one clobbering
    the other's recomputed summary."""
    inv_path = tmp_path / "deck_inventory.json"
    inventory = _inventory_with_input_format("text")
    inventory["ai_company_status"] = "not_ai"
    inventory["ai_evidence"] = "No AI claim."
    inv_path.write_text(json.dumps(inventory))
    out_path = str(tmp_path / "checklist.json")
    overrides = {
        cid: {"status": "fail", "evidence": "No evidence of this in the deck.", "notes": "Evaluated."}
        for cid in (*_AI_CRITERIA_IDS, *_DESIGN_CRITERIA_IDS)
    }
    payload = json.dumps({"items": _make_checklist_items(overrides=overrides)})

    rc, stdout, stderr = run_script_raw(
        "checklist.py",
        ["--run-id", "r1", "--inventory", str(inv_path), "--pretty", "-o", out_path],
        stdin_data=payload,
    )
    assert rc == 0, stderr
    with open(out_path) as f:
        data = json.load(f)

    items_by_id = {i["id"]: i for i in data["items"]}
    for gated_id in (*_AI_CRITERIA_IDS, *_DESIGN_CRITERIA_IDS):
        assert items_by_id[gated_id]["status"] == "not_applicable", gated_id
    summary = data["summary"]
    assert summary["not_applicable"] == 9, f"expected 9 N/A (4 AI + 5 Design), got {summary['not_applicable']}"
    # 35 total - 9 N/A = 26 applicable, all pass -> 100%.
    assert summary["score_pct"] == 100.0


# ---------------------------------------------------------------------------
# UNSUBSTANTIATED_AI_CLAIM compose warning tests (TDD)
# ---------------------------------------------------------------------------


def test_compose_unsubstantiated_ai_claim_warning_for_ai_claimed_unverified(tmp_path: Path) -> None:
    """ai_company_status=ai_claimed_unverified -> UNSUBSTANTIATED_AI_CLAIM warning (medium)."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "ai_claimed_unverified"
    inventory["ai_evidence"] = "Deck says 'AI-powered' but no core-AI signals."
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNSUBSTANTIATED_AI_CLAIM" in codes
    w = next(w for w in data["validation"]["warnings"] if w["code"] == "UNSUBSTANTIATED_AI_CLAIM")
    assert w["severity"] == "medium"
    assert "ai_claimed_unverified" in w["message"]


def test_compose_no_unsubstantiated_ai_claim_for_ai_core(tmp_path: Path) -> None:
    """ai_company_status=ai_core -> no UNSUBSTANTIATED_AI_CLAIM warning."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "ai_core"
    inventory["ai_evidence"] = "ML model in core value prop."
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNSUBSTANTIATED_AI_CLAIM" not in codes


def test_compose_no_unsubstantiated_ai_claim_for_not_ai(tmp_path: Path) -> None:
    """ai_company_status=not_ai -> no UNSUBSTANTIATED_AI_CLAIM warning."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "not_ai"
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    codes = [w["code"] for w in data["validation"]["warnings"]]
    assert "UNSUBSTANTIATED_AI_CLAIM" not in codes


def test_compose_ai_company_status_in_coaching_payload(tmp_path: Path) -> None:
    """coaching_payload carries ai_company_status from inventory (not is_ai_company from profile)."""
    inventory = dict(_VALID_INVENTORY)
    inventory["ai_company_status"] = "ai_claimed_unverified"
    inventory["ai_evidence"] = "Claims AI."
    d = _make_artifact_dir(
        {
            "deck_inventory.json": inventory,
            "stage_profile.json": _VALID_PROFILE,
            "slide_reviews.json": _VALID_REVIEWS,
            "checklist.json": _VALID_CHECKLIST,
        }
    )
    rc, data, _ = _run_compose(d)
    assert rc == 0
    assert data is not None
    payload = data["coaching_payload"]
    assert "ai_company_status" in payload
    assert payload["ai_company_status"] == "ai_claimed_unverified"
    assert "is_ai_company" not in payload, "coaching_payload must not include old 'is_ai_company' key"


def test_deck_inventory_schema_requires_ai_company_status(tmp_path: Path) -> None:
    """deck_inventory.py rejects JSON missing ai_company_status (required field)."""
    import subprocess as _sp

    script = os.path.join(DECK_REVIEW_DIR, "deck_inventory.py")
    bad_input = {
        "company_name": "TestCo",
        "review_date": "2026-06-01",
        "input_format": "pdf",
        "total_slides": 1,
        # ai_company_status intentionally missing
        "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
    }
    out_path = str(tmp_path / "out.json")
    result = _sp.run(
        [sys.executable, script, "--run-id", "r1", "-o", out_path],
        input=json.dumps(bad_input),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "deck_inventory.py should reject missing ai_company_status"
    assert not os.path.exists(out_path), "no artifact should be written on validation failure"


def test_deck_inventory_schema_rejects_invalid_ai_company_status(tmp_path: Path) -> None:
    """deck_inventory.py rejects ai_company_status with an invalid enum value."""
    import subprocess as _sp

    script = os.path.join(DECK_REVIEW_DIR, "deck_inventory.py")
    bad_input = {
        "company_name": "TestCo",
        "review_date": "2026-06-01",
        "input_format": "pdf",
        "total_slides": 1,
        "ai_company_status": "yes_ai",  # invalid enum value
        "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
    }
    out_path = str(tmp_path / "out.json")
    result = _sp.run(
        [sys.executable, script, "--run-id", "r1", "-o", out_path],
        input=json.dumps(bad_input),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "deck_inventory.py should reject invalid ai_company_status enum"
    assert not os.path.exists(out_path)


def test_deck_inventory_accepts_null_claimed_stage(tmp_path: Path) -> None:
    """A deck that states no stage may set claimed_stage to null -> artifact written, exit 0."""
    import subprocess as _sp

    script = os.path.join(DECK_REVIEW_DIR, "deck_inventory.py")
    good_input = {
        "company_name": "TestCo",
        "review_date": "2026-06-01",
        "input_format": "pdf",
        "total_slides": 1,
        "ai_company_status": "not_ai",
        "claimed_stage": None,
        "slides": [{"number": 1, "headline": "h", "content_summary": "s"}],
    }
    out_path = str(tmp_path / "out.json")
    result = _sp.run(
        [sys.executable, script, "--run-id", "r1", "-o", out_path],
        input=json.dumps(good_input),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"null claimed_stage should be accepted; stderr: {result.stderr}"
    assert os.path.exists(out_path), "artifact must be written when claimed_stage is null"


def _run_deck_inventory(tmp_path: Path, slides: list[dict]) -> tuple[int, dict, str]:
    """Run deck_inventory.py with the given slides; return (rc, receipt, stderr)."""
    import subprocess as _sp

    script = os.path.join(DECK_REVIEW_DIR, "deck_inventory.py")
    payload = {
        "company_name": "TestCo",
        "review_date": "2026-06-01",
        "input_format": "pdf",
        "total_slides": len(slides),
        "ai_company_status": "not_ai",
        "slides": slides,
    }
    out_path = str(tmp_path / "out.json")
    result = _sp.run(
        [sys.executable, script, "--run-id", "r1", "-o", out_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, receipt, result.stderr


def test_deck_inventory_warns_on_duplicate_slide_numbers(tmp_path: Path) -> None:
    """Two slides sharing a number -> non-fatal receipt + stderr warning, artifact still written."""
    slides = [
        {"number": 20, "headline": "a", "content_summary": "s"},
        {"number": 20, "headline": "b", "content_summary": "s"},
    ]
    rc, receipt, stderr = _run_deck_inventory(tmp_path, slides)
    assert rc == 0
    assert os.path.exists(str(tmp_path / "out.json"))
    assert "warnings" in receipt, "duplicate slide numbers must surface a receipt warning"
    joined = " ".join(receipt["warnings"]).lower()
    assert "duplicate" in joined and "20" in joined
    assert "duplicate" in stderr.lower()


def test_deck_inventory_warns_on_non_sequential_slide_numbers(tmp_path: Path) -> None:
    """A gap in slide numbers -> non-fatal receipt warning, artifact still written."""
    slides = [
        {"number": 1, "headline": "a", "content_summary": "s"},
        {"number": 3, "headline": "b", "content_summary": "s"},
    ]
    rc, receipt, _ = _run_deck_inventory(tmp_path, slides)
    assert rc == 0
    assert "warnings" in receipt
    joined = " ".join(receipt["warnings"]).lower()
    assert "sequential" in joined or "non-sequential" in joined


def test_deck_inventory_clean_slides_no_warnings(tmp_path: Path) -> None:
    """Contiguous slide numbers -> no warnings key in the receipt (no happy-path noise)."""
    slides = [
        {"number": 1, "headline": "a", "content_summary": "s"},
        {"number": 2, "headline": "b", "content_summary": "s"},
        {"number": 3, "headline": "c", "content_summary": "s"},
    ]
    rc, receipt, _ = _run_deck_inventory(tmp_path, slides)
    assert rc == 0
    assert "warnings" not in receipt
