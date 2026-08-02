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
    assert written["_produced_by"] == "verify_competitors.py"
    assert written["summary"]["flagged_slugs"] == ["calendly"]


# ---------------------------------------------------------------------------
# --blind-set (recall_gaps diff)
# ---------------------------------------------------------------------------


def _landscape(tmp_path: pathlib.Path, slugs: list[str]) -> pathlib.Path:
    land = tmp_path / "landscape.json"
    land.write_text(json.dumps({"competitors": [{"slug": s} for s in slugs]}))
    return land


def _blind(candidates: list[dict]) -> dict:
    return {"candidates": candidates, "metadata": {"run_id": "R1"}}


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
