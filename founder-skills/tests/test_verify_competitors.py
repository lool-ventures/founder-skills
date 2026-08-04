"""Tests for verify_competitors.py — the adversarial competitor-set verification
validator (structure + show-your-work gate + summary)."""

import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "skills/competitive-positioning/scripts/verify_competitors.py"


def _run(payload: dict, *args: str) -> "subprocess.CompletedProcess[str]":
    cmd = [sys.executable, str(SCRIPT), "--run-id", "R1", *args]
    return subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)


def _base() -> dict:
    return {
        "startup_characterization": {
            "buyer": "SMB FSM operators",
            "job_to_be_done": "dispatch techs",
            "category": "FSM",
            "monetization": "SaaS",
            "evidence_source": "founder_provided",
        },
        "verdicts": [
            {
                "slug": "servicetitan",
                "verdict": "genuine",
                "independent_characterization": {
                    "buyer": "field-service SMBs",
                    "job_to_be_done": "dispatch techs",
                    "category": "FSM",
                    "monetization": "SaaS",
                    "evidence_source": "researched",
                },
                "overlap": {"buyer": True, "job_to_be_done": True, "category": True},
                "reasoning": "same buyer and job",
                "confidence": "high",
                "recommended_action": "keep",
            },
            {
                "slug": "calendly",
                "verdict": "not_a_competitor",
                "independent_characterization": {
                    "buyer": "knowledge workers",
                    "job_to_be_done": "self-book meetings",
                    "category": "meeting scheduling",
                    "monetization": "SaaS",
                    "evidence_source": "researched",
                },
                "overlap": {"buyer": False, "job_to_be_done": False, "category": False},
                "reasoning": "schedules meetings not field techs; different buyer",
                "confidence": "high",
                "recommended_action": "challenge_removal",
            },
        ],
        "metadata": {"run_id": "R1"},
    }


def test_valid_payload_computes_summary() -> None:
    p = _run(_base())
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    s = out["summary"]
    assert s["total"] == 2 and s["genuine"] == 1 and s["not_a_competitor"] == 1
    assert s["flagged"] == 1 and s["flagged_slugs"] == ["calendly"]
    assert out["validation"]["status"] == "ok"


def test_flag_without_reasoning_is_rejected() -> None:
    payload = _base()
    payload["verdicts"][1]["reasoning"] = "   "
    p = _run(payload)
    assert p.returncode == 1
    out = json.loads(p.stdout)
    assert out["validation"]["status"] == "error"
    assert any("reasoning" in e for e in out["validation"]["errors"])


def test_flag_without_independent_characterization_is_rejected() -> None:
    payload = _base()
    payload["verdicts"][1]["independent_characterization"]["buyer"] = ""
    p = _run(payload)
    assert p.returncode == 1
    assert any("buyer" in e for e in json.loads(p.stdout)["validation"]["errors"])


def test_bad_verdict_enum_rejected() -> None:
    payload = _base()
    payload["verdicts"][1]["verdict"] = "maybe"
    p = _run(payload)
    assert p.returncode == 1


def test_genuine_verdict_does_not_require_reasoning() -> None:
    # The show-your-work gate applies only to flagged (non-genuine) verdicts.
    payload = _base()
    payload["verdicts"][0]["reasoning"] = ""
    p = _run(payload)
    assert p.returncode == 0, p.stderr


def test_landscape_slug_missing_verdict_rejected(tmp_path: pathlib.Path) -> None:
    land = tmp_path / "landscape.json"
    land.write_text(json.dumps({"competitors": [{"slug": "servicetitan"}, {"slug": "calendly"}, {"slug": "jobber"}]}))
    p = _run(_base(), "--landscape", str(land))
    assert p.returncode == 1
    assert any("jobber" in e for e in json.loads(p.stdout)["validation"]["errors"])


def test_run_id_mismatch_rejected() -> None:
    payload = _base()
    payload["metadata"]["run_id"] = "OTHER"
    p = _run(payload)  # --run-id R1
    assert p.returncode == 1


def test_output_file_written_and_receipt_emitted(tmp_path: pathlib.Path) -> None:
    out_path = tmp_path / "competitor_verification.json"
    p = _run(_base(), "-o", str(out_path), "--pretty")
    assert p.returncode == 0, p.stderr
    receipt = json.loads(p.stdout)
    assert receipt["ok"] is True and receipt["flagged"] == 1
    written = json.loads(out_path.read_text())
    assert written["_produced_by"] == "verify_competitors", (
        "the stamp is the BARE module name, derived from __file__ — see test_producer_stamps_match_module_names"
    )
    assert written["summary"]["flagged_slugs"] == ["calendly"]


# ---------------------------------------------------------------------------
# --blind-set (recall_gaps diff)
# ---------------------------------------------------------------------------


def _landscape(tmp_path: pathlib.Path, slugs: list[str]) -> pathlib.Path:
    land = tmp_path / "landscape.json"
    land.write_text(json.dumps({"competitors": [{"slug": s} for s in slugs]}))
    return land


def _landscape_full(tmp_path: pathlib.Path, competitors: list[dict], name: str = "landscape.json") -> pathlib.Path:
    """Like `_landscape` but each competitor entry can carry the full draft
    shape (name/description/key_differentiators/constituents) that the
    slug-variant/constituent/text-overlap demotion passes read."""
    land = tmp_path / name
    land.write_text(json.dumps({"competitors": competitors}))
    return land


def _blind(candidates: list[dict]) -> dict:
    return {"candidates": candidates, "metadata": {"run_id": "R1"}}


def _verdict_for(slug: str) -> dict:
    """A trivially-valid 'genuine' verdict for `slug` — used to satisfy
    validate()'s landscape-slug-coverage gate when a test's --landscape file
    carries slugs unrelated to _base()'s two verdicts."""
    return {
        "slug": slug,
        "verdict": "genuine",
        "independent_characterization": {
            "buyer": "buyer",
            "job_to_be_done": "job",
            "category": "category",
            "monetization": "SaaS",
            "evidence_source": "researched",
        },
        "overlap": {"buyer": True, "job_to_be_done": True, "category": True},
        "reasoning": "",
        "confidence": "high",
        "recommended_action": "keep",
    }


def _payload_for_slugs(slugs: list[str]) -> dict:
    return {
        "startup_characterization": {
            "buyer": "buyer",
            "job_to_be_done": "job",
            "category": "category",
            "monetization": "SaaS",
            "evidence_source": "founder_provided",
        },
        "verdicts": [_verdict_for(s) for s in slugs],
        "metadata": {"run_id": "R1"},
    }


def test_no_blind_set_flag_output_is_byte_identical_to_baseline() -> None:
    # Absence of --blind-set must not add an (even empty) recall_gaps key.
    p = _run(_base())
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert "recall_gaps" not in out


def test_blind_set_without_landscape_exits_2(tmp_path: pathlib.Path) -> None:
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(json.dumps(_blind([])))
    p = _run(_base(), "--blind-set", str(blind_path))
    assert p.returncode == 2
    # Assert the specific custom message, not just "--landscape" — argparse's own
    # "unrecognized arguments" usage banner also happens to print the flag's
    # name+metavar, which would make a bare substring check pass vacuously
    # against the pre-fix CLI (which doesn't know --blind-set at all).
    assert "requires --landscape" in p.stderr


def test_blind_set_matched_unmatched_draft_only_partition(tmp_path: pathlib.Path) -> None:
    # Draft has servicetitan + calendly (both verdicted in _base()) + jobber (extra,
    # to exercise draft_only — verdict cross-check is skipped since we don't pass
    # --landscape through validate()'s slug-coverage gate here beyond what _base covers).
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "ServiceTitan",  # matches draft's "servicetitan"
                        "why_considered": "same buyer",
                        "sources": ["https://example.com/st"],
                    },
                    {
                        "name": "Workiz",  # NOT in draft -> recall gap
                        "why_considered": "field-service scheduling for SMBs",
                        "sources": ["https://example.com/workiz"],
                    },
                ]
            )
        )
    )
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["blind_set_size"] == 2
    assert gaps["matched"] == ["servicetitan"]
    assert gaps["unmatched"] == [
        {
            "slug": "workiz",
            "name": "Workiz",
            "why_considered": "field-service scheduling for SMBs",
            "sources": ["https://example.com/workiz"],
        }
    ]
    # calendly is in the draft but the blind agent never surfaced it.
    assert gaps["draft_only"] == ["calendly"]
    assert gaps["dropped"] == []
    assert "NOT evidence" in gaps["note"]


def test_blind_set_drops_unsourced_candidate(tmp_path: pathlib.Path) -> None:
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Mystery Co",
                        "why_considered": "heard about it somewhere",
                        "sources": [],  # empty -> unsourced, must be dropped not laundered in
                    }
                ]
            )
        )
    )
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["unmatched"] == []
    assert len(gaps["dropped"]) == 1
    assert gaps["dropped"][0]["name"] == "Mystery Co"
    assert "sources" in gaps["dropped"][0]["reason"]


def test_blind_set_empty_candidates_is_not_an_error(tmp_path: pathlib.Path) -> None:
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(json.dumps(_blind([])))
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps == {
        "blind_set_size": 0,
        "matched": [],
        "unmatched": [],
        "probable_duplicates": [],
        "draft_only": [],
        "dropped": [],
        "note": gaps["note"],  # content asserted below
    }
    assert "legitimately finds no additional competitors" in gaps["note"]


def test_blind_set_missing_candidates_key_is_not_an_error(tmp_path: pathlib.Path) -> None:
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(json.dumps({"metadata": {"run_id": "R1"}}))  # no "candidates" key
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["blind_set_size"] == 0
    assert gaps["matched"] == gaps["unmatched"] == gaps["draft_only"] == gaps["dropped"] == []
    assert gaps["probable_duplicates"] == []


def test_blind_set_malformed_json_exits_1(tmp_path: pathlib.Path) -> None:
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text("{not valid json")
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 1
    assert "blind-set" in p.stderr.lower() or "json" in p.stderr.lower()


def test_blind_set_unreadable_file_exits_1(tmp_path: pathlib.Path) -> None:
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    missing = tmp_path / "does_not_exist.json"
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(missing))
    assert p.returncode == 1


def test_normalize_slug_variants_via_cli(tmp_path: pathlib.Path) -> None:
    # Exercises normalize_competitor_slug indirectly. The landscape here must
    # stay exactly {servicetitan, calendly} to match _base()'s verdict
    # coverage (an unrelated gate in validate()) — so this test proves the
    # normalizer two ways within that constraint:
    #   1. "ServiceTitan, Inc." (comma+suffix variant) matches draft's
    #      already-normalized "servicetitan" -> no false recall gap.
    #   2. "Housecall Pro" (space-separated) and "Corp" (suffix token that
    #      IS the entire name, guarded against being stripped to "") both
    #      normalize correctly and surface as distinct, non-empty unmatched
    #      slugs rather than colliding or vanishing.
    land = _landscape(tmp_path, ["servicetitan", "calendly"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "ServiceTitan, Inc.",
                        "why_considered": "direct overlap",
                        "sources": ["https://example.com/1"],
                    },
                    {
                        "name": "Housecall Pro",
                        "why_considered": "direct overlap",
                        "sources": ["https://example.com/2"],
                    },
                    {
                        "name": "Corp",  # entire name IS a suffix token -> must not become ""
                        "why_considered": "edge case",
                        "sources": ["https://example.com/3"],
                    },
                ]
            )
        )
    )
    p = _run(_base(), "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["matched"] == ["servicetitan"]
    unmatched_slugs = sorted(u["slug"] for u in gaps["unmatched"])
    assert unmatched_slugs == ["corp", "housecall-pro"]
    assert gaps["draft_only"] == ["calendly"]


# ---------------------------------------------------------------------------
# probable_duplicates demotion (slug_variant / constituent) and the
# possible_overlap_with annotation. See CONTRACT.md's "Task 1/2/3" for the
# exact rules; these tests use the real measured examples from that spec.
# ---------------------------------------------------------------------------


def test_slug_variant_demotes_oversized_chiller_status_quo(tmp_path: pathlib.Path) -> None:
    # Real measured case: the blind agent's "oversized-chiller-status-quo"
    # IS the draft's "oversize-chillers-status-quo" (oversized/oversize,
    # chiller/chillers are prefix pairs; status/quo are exact pairs).
    land = _landscape_full(tmp_path, [{"slug": "oversize-chillers-status-quo", "name": "Oversized Chiller Status Quo"}])
    payload = _payload_for_slugs(["oversize-chillers-status-quo"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Oversized Chiller Status Quo",
                        "slug": "oversized-chiller-status-quo",
                        "why_considered": "same category as the drafted status-quo entry",
                        "sources": ["https://example.com/x"],
                    }
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["unmatched"] == []
    assert gaps["probable_duplicates"] == [
        {
            "slug": "oversized-chiller-status-quo",
            "name": "Oversized Chiller Status Quo",
            "matched_draft_slug": "oversize-chillers-status-quo",
            "rule": "slug_variant",
        }
    ]


def test_square_vs_squarespace_not_demoted_no_exact_token_pair(tmp_path: pathlib.Path) -> None:
    # Brand-prefix guard: single-token slugs with no exact pair must never
    # demote on a bare prefix relation alone.
    land = _landscape_full(tmp_path, [{"slug": "squarespace", "name": "Squarespace"}])
    payload = _payload_for_slugs(["squarespace"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(_blind([{"name": "Square", "why_considered": "payments adjacency", "sources": ["https://x/1"]}]))
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    assert [u["slug"] for u in gaps["unmatched"]] == ["square"]


def test_chart_vs_chartio_not_demoted_no_exact_token_pair(tmp_path: pathlib.Path) -> None:
    land = _landscape_full(tmp_path, [{"slug": "chartio", "name": "Chartio"}])
    payload = _payload_for_slugs(["chartio"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(_blind([{"name": "Chart", "why_considered": "analytics adjacency", "sources": ["https://x/1"]}]))
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    assert [u["slug"] for u in gaps["unmatched"]] == ["chart"]


def test_thermal_battery_vs_thermal_batteries_not_demoted_documented_limitation(tmp_path: pathlib.Path) -> None:
    # Documented limitation: "-y" -> "-ies" is not a proper-prefix pair
    # (they diverge before either is a prefix of the other), so this
    # slug-variant pair is NOT caught by the token matcher. This test
    # pins the current (imperfect) behaviour rather than a bug.
    land = _landscape_full(tmp_path, [{"slug": "thermal-batteries", "name": "Thermal Batteries"}])
    payload = _payload_for_slugs(["thermal-batteries"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(_blind([{"name": "Thermal Battery", "why_considered": "same tech", "sources": ["https://x/1"]}]))
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    assert [u["slug"] for u in gaps["unmatched"]] == ["thermal-battery"]


def test_slug_variant_matching_is_order_independent(tmp_path: pathlib.Path) -> None:
    # The candidate's tokens are given in a completely different order than
    # the draft slug's tokens (status, quo, oversized, chiller vs the
    # draft's oversize, chillers, status, quo). A naive positional/greedy
    # comparison would fail here; maximum bipartite matching must not.
    land = _landscape_full(tmp_path, [{"slug": "oversize-chillers-status-quo", "name": "Oversized Chiller Status Quo"}])
    payload = _payload_for_slugs(["oversize-chillers-status-quo"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Status Quo Oversized Chiller",
                        "why_considered": "reordered tokens vs the drafted slug",
                        "sources": ["https://example.com/x"],
                    }
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["unmatched"] == []
    assert len(gaps["probable_duplicates"]) == 1
    assert gaps["probable_duplicates"][0]["rule"] == "slug_variant"
    assert gaps["probable_duplicates"][0]["matched_draft_slug"] == "oversize-chillers-status-quo"


def test_constituent_membership_demotes_via_exact_lookup(tmp_path: pathlib.Path) -> None:
    # Real measured case: "sunamp" is named inside a cohort entry's
    # constituents (pcm-tes-entrants = "Rondo, Antora, Sunamp").
    land = _landscape_full(
        tmp_path,
        [
            {
                "slug": "pcm-tes-entrants",
                "name": "PCM TES Entrants",
                "constituents": ["Rondo", "Antora", "Sunamp"],
            }
        ],
    )
    payload = _payload_for_slugs(["pcm-tes-entrants"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Sunamp",
                        "why_considered": "PCM thermal-battery vendor",
                        "sources": ["https://example.com/sunamp"],
                    }
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["unmatched"] == []
    assert gaps["probable_duplicates"] == [
        {"slug": "sunamp", "name": "Sunamp", "matched_draft_slug": "pcm-tes-entrants", "rule": "constituent"}
    ]


def test_sunamp_without_constituents_field_stays_unmatched_with_overlap_annotation(tmp_path: pathlib.Path) -> None:
    # Same "Sunamp" candidate, but the draft entry has NO constituents field
    # — only prose mentioning "Sunamp" in its description. Task 2 (exact
    # constituent lookup) must not fire; Task 3 may annotate, but the entry
    # stays a gap (possible_overlap_with is an annotation, not a demotion).
    land = _landscape_full(
        tmp_path,
        [
            {
                "slug": "pcm-tes-entrants",
                "name": "PCM TES Entrants",
                "description": (
                    "A cohort of phase-change-material thermal-storage entrants including Rondo, Antora, and Sunamp."
                ),
            }
        ],
    )
    payload = _payload_for_slugs(["pcm-tes-entrants"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Sunamp",
                        "why_considered": "PCM thermal-battery vendor",
                        "sources": ["https://example.com/sunamp"],
                    }
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    assert len(gaps["unmatched"]) == 1
    assert gaps["unmatched"][0]["slug"] == "sunamp"
    assert gaps["unmatched"][0]["possible_overlap_with"] == "pcm-tes-entrants"


def test_chilled_water_tes_tanks_text_overlap_never_demotes_regression(tmp_path: pathlib.Path) -> None:
    # Regression guard for the false-demote hazard: an earlier text-substring
    # heuristic was measured to falsely demote chilled-water-tes-tanks (among
    # others) — the single most valuable candidate in the run it was tested
    # against. Even with several of its tokens ("chilled", "water", "tanks")
    # present in the draft's prose, this must stay a gap, never disappear.
    land = _landscape_full(
        tmp_path,
        [
            {
                "slug": "chilled-water-systems",
                "name": "Chilled Water Systems",
                "description": "Legacy chilled water plants store water in insulated tanks for peak shaving.",
            }
        ],
    )
    payload = _payload_for_slugs(["chilled-water-systems"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Chilled Water TES Tanks",
                        "why_considered": "thermal energy storage entrant",
                        "sources": ["https://example.com/cwt"],
                    }
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    assert [u["slug"] for u in gaps["unmatched"]] == ["chilled-water-tes-tanks"]


def test_unmatched_never_grows_relative_to_pre_pass_set(tmp_path: pathlib.Path) -> None:
    # Demote-only invariant: Task 1 (slug_variant) and Task 2 (constituent)
    # may only MOVE a surviving candidate out of unmatched into
    # probable_duplicates; Task 3 (text annotation) never removes or adds
    # anything. So the pre-pass survivor count (candidates that passed
    # per-candidate validation and did not exact-match the draft) must equal
    # len(unmatched) + len(probable_duplicates) — unmatched can only shrink.
    land = _landscape_full(
        tmp_path,
        [
            {"slug": "oversize-chillers-status-quo", "name": "Oversized Chiller Status Quo"},
            {
                "slug": "pcm-tes-entrants",
                "name": "PCM TES Entrants",
                "constituents": ["Rondo", "Antora", "Sunamp"],
            },
            {
                "slug": "liquid-cooling-vendors",
                "name": "Liquid Cooling Vendors",
                "description": "Cohort including Vertiv, JetCool, and LiquidStack.",
            },
        ],
    )
    payload = _payload_for_slugs(["oversize-chillers-status-quo", "pcm-tes-entrants", "liquid-cooling-vendors"])
    candidates = [
        {
            "name": "Oversized Chiller Status Quo",
            "slug": "oversized-chiller-status-quo",
            "why_considered": "slug variant of the drafted status-quo entry",
            "sources": ["https://example.com/1"],
        },
        {
            "name": "Sunamp",
            "why_considered": "constituent of the drafted PCM TES cohort",
            "sources": ["https://example.com/2"],
        },
        {
            "name": "Vertiv",
            "why_considered": "text overlap with the liquid-cooling cohort only, never demoted",
            "sources": ["https://example.com/3"],
        },
        {
            "name": "Genuinely New Startup",
            "why_considered": "a real recall gap not present anywhere in the draft",
            "sources": ["https://example.com/4"],
        },
    ]
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(json.dumps(_blind(candidates)))
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]

    pre_pass_survivors = len(candidates)  # none dropped, none exact-match the draft
    assert len(gaps["unmatched"]) + len(gaps["probable_duplicates"]) == pre_pass_survivors
    assert len(gaps["unmatched"]) < pre_pass_survivors  # something WAS demoted

    demoted_slugs = {d["slug"] for d in gaps["probable_duplicates"]}
    assert demoted_slugs == {"oversized-chiller-status-quo", "sunamp"}

    unmatched_slugs = {u["slug"] for u in gaps["unmatched"]}
    assert unmatched_slugs == {"vertiv", "genuinely-new-startup"}
    vertiv_entry = next(u for u in gaps["unmatched"] if u["slug"] == "vertiv")
    assert vertiv_entry.get("possible_overlap_with") == "liquid-cooling-vendors"


def test_overlap_annotation_requires_whole_name_not_a_single_token(tmp_path: pathlib.Path) -> None:
    """The `possible_overlap_with` hint must fire on the candidate's WHOLE name, not any token.

    Measured on a real run, a single-token rule annotated 5 of 7 gaps and most were misleading:
    `johnson-controls` matched a Trane entry on the word "controls", `cold-utes` on "cold",
    `bess-peak-shaving` on "peak". That is industry vocabulary, not evidence a competitor is
    already represented — and telling a founder a real gap is already covered is the harm the
    annotation exists to avoid. A miss costs only a hint, so the rule is biased toward silence.
    """
    land = _landscape_full(
        tmp_path,
        [
            {
                "slug": "trane-calmac",
                "name": "Trane Technologies",
                "description": "Bundled with chiller, controls and nationwide service; cold storage at peak.",
            }
        ],
    )
    payload = _payload_for_slugs(["trane-calmac"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            _blind(
                [
                    {
                        "name": "Johnson Controls",
                        "why_considered": "named among major TES vendors",
                        "sources": ["https://example.com/jci"],
                    },
                    {
                        "name": "Cold UTES",
                        "why_considered": "underground cold storage",
                        "sources": ["https://example.com/utes"],
                    },
                ]
            )
        )
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == []
    by_slug = {u["slug"]: u for u in gaps["unmatched"]}
    assert set(by_slug) == {"johnson-controls", "cold-utes"}
    for slug, entry in by_slug.items():
        assert "possible_overlap_with" not in entry, (
            f"{slug} was annotated on a single shared token — the whole-name rule was not applied"
        )


def test_overlap_annotation_fires_on_a_verbatim_cohort_member(tmp_path: pathlib.Path) -> None:
    """The counterpart: a true cohort member IS named verbatim in the cohort's prose, so the
    whole-name rule still catches it — annotation only, the entry stays a gap."""
    land = _landscape_full(
        tmp_path,
        [
            {
                "slug": "pcm-tes-entrants",
                "name": "PCM and next-generation thermal entrants",
                "description": "Rondo, Antora and Sunamp are funding the category.",
            }
        ],
    )
    payload = _payload_for_slugs(["pcm-tes-entrants"])
    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(_blind([{"name": "Sunamp", "why_considered": "PCM modules", "sources": ["https://example.com/s"]}]))
    )
    p = _run(payload, "--landscape", str(land), "--blind-set", str(blind_path))
    assert p.returncode == 0, p.stderr
    gaps = json.loads(p.stdout)["recall_gaps"]
    assert gaps["probable_duplicates"] == [], "a text hint must never demote"
    assert [u["slug"] for u in gaps["unmatched"]] == ["sunamp"]
    assert gaps["unmatched"][0].get("possible_overlap_with") == "pcm-tes-entrants"
