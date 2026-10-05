"""competitive-positioning's `record_deferred_recall.py`: the writer for Gate 1's declined recall
candidates. It appends to `landscape_draft.json` in place, so the draft's `_produced_by` stamp must
survive, or compose reports the run as UNVALIDATED_ARTIFACT at high severity."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any

TESTS_DIR = pathlib.Path(__file__).resolve().parent
CP_SCRIPTS = TESTS_DIR.parent / "skills" / "competitive-positioning" / "scripts"
SCRIPT = CP_SCRIPTS / "record_deferred_recall.py"
FIXTURE_DIR = TESTS_DIR / "fixtures" / "competitive-positioning"


def _entry(slug: str, **over: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "category": "adjacent",
        "why_considered": f"a buyer weighing this job would look at {slug}",
        "sources": [f"https://example.com/{slug}"],
    }
    entry.update(over)
    return entry


def _run(draft: pathlib.Path, payload: Any, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--draft", str(draft), *extra],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
    )


def _draft(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "landscape_draft.json"
    shutil.copy(FIXTURE_DIR / "landscape_draft.json", path)
    return path


def test_appends_an_entry_and_keeps_every_other_key(tmp_path: pathlib.Path) -> None:
    draft = _draft(tmp_path)
    before = json.loads(draft.read_text(encoding="utf-8"))
    assert before["_produced_by"] == "persist_agent_artifact"  # the stamp is really there to keep

    proc = _run(draft, _entry("ramp"), "--pretty")
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["ok"] is True and receipt["added"] == ["ramp"]

    after = json.loads(draft.read_text(encoding="utf-8"))
    assert after["deferred_recall_candidates"] == [_entry("ramp")]
    assert {k: v for k, v in after.items() if k != "deferred_recall_candidates"} == before


def test_sources_may_be_url_objects(tmp_path: pathlib.Path) -> None:
    draft = _draft(tmp_path)
    entry = _entry("brex", sources=[{"url": "https://example.com/brex", "title": "Brex"}], category=None)
    proc = _run(draft, [entry])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(draft.read_text(encoding="utf-8"))["deferred_recall_candidates"] == [entry]


def test_dedups_by_slug_keeping_the_first(tmp_path: pathlib.Path) -> None:
    draft = _draft(tmp_path)
    first = _entry("ramp", why_considered="the first reason")
    assert _run(draft, [first]).returncode == 0

    again = _entry("ramp", why_considered="a later reason")
    proc = _run(draft, [again, _entry("brex"), _entry("brex", why_considered="dup within input")])
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["added"] == ["brex"]
    assert receipt["skipped_duplicate_slugs"] == ["ramp", "brex"]

    kept = json.loads(draft.read_text(encoding="utf-8"))["deferred_recall_candidates"]
    assert [c["slug"] for c in kept] == ["ramp", "brex"]
    assert kept[0]["why_considered"] == "the first reason"
    assert kept[1]["why_considered"] == _entry("brex")["why_considered"]


def test_dedup_compares_slugs_normalized_like_verify_competitors(tmp_path: pathlib.Path) -> None:
    """`Ramp, Inc.` and `ramp` are one company to verify_competitors.py, so they are one candidate here."""
    draft = _draft(tmp_path)
    assert _run(draft, [_entry("ramp")]).returncode == 0
    proc = _run(draft, [_entry("Ramp, Inc."), _entry("Brex_Card"), _entry("brex-card")])
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["added"] == ["Brex_Card"]
    assert receipt["skipped_duplicate_slugs"] == ["Ramp, Inc.", "brex-card"]
    kept = json.loads(draft.read_text(encoding="utf-8"))["deferred_recall_candidates"]
    assert [c["slug"] for c in kept] == ["ramp", "Brex_Card"]


def test_a_candidate_already_in_competitors_is_skipped(tmp_path: pathlib.Path) -> None:
    """Adopted into competitors[] means not deferred. The fixture draft lists `xero` and `pilot-com`."""
    draft = _draft(tmp_path)
    proc = _run(draft, [_entry("Xero"), _entry("pilot.com"), _entry("ramp")])
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["added"] == ["ramp"]
    assert receipt["skipped_already_competitors"] == ["Xero", "pilot.com"]
    kept = json.loads(draft.read_text(encoding="utf-8"))["deferred_recall_candidates"]
    assert [c["slug"] for c in kept] == ["ramp"]


def test_a_bad_entry_is_refused_without_touching_the_draft(tmp_path: pathlib.Path) -> None:
    draft = _draft(tmp_path)
    original = draft.read_bytes()
    # One good entry beside a bad one: all-or-nothing, so the good one is not written either.
    for bad in (
        [_entry("ramp"), _entry("brex", sources=[])],
        [_entry("ramp"), _entry("brex", sources=[""])],
        [_entry("ramp"), _entry("brex", sources=[{"title": "no url"}])],
        [_entry("ramp"), {"name": "Brex", "slug": "brex"}],
        [_entry("ramp", category=7)],
        "not json",
        "[]",
    ):
        proc = _run(draft, bad)
        assert proc.returncode != 0, bad
        assert proc.stderr.strip(), bad
        assert json.loads(proc.stdout)["validation"]["status"] == "invalid", bad
        assert draft.read_bytes() == original, f"draft changed on a refused input: {bad!r}"
    assert not list(tmp_path.glob(".record_deferred_recall.*")), "a temp file was left behind"


def test_a_draft_whose_field_is_not_a_list_is_refused(tmp_path: pathlib.Path) -> None:
    draft = _draft(tmp_path)
    data = json.loads(draft.read_text(encoding="utf-8"))
    data["deferred_recall_candidates"] = {"ramp": {}}
    draft.write_text(json.dumps(data), encoding="utf-8")
    original = draft.read_bytes()
    proc = _run(draft, [_entry("brex")])
    assert proc.returncode == 1, proc.stderr
    assert "'deferred_recall_candidates' must be an array" in proc.stderr, proc.stderr
    assert draft.read_bytes() == original


def test_compose_over_a_draft_the_script_wrote_raises_no_unvalidated_artifact(tmp_path: pathlib.Path) -> None:
    """Through compose: the fixture set's warning codes are unchanged after the script has written the
    draft. The baseline is measured on the untouched copy, so the comparison is not to a hand-list."""

    def codes(run_dir: pathlib.Path) -> set[str]:
        proc = subprocess.run(
            [sys.executable, str(CP_SCRIPTS / "compose_report.py"), "--dir", str(run_dir)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[:400]
        return {w["code"] for w in json.loads(proc.stdout)["warnings"]}

    baseline_dir = tmp_path / "baseline"
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE_DIR, baseline_dir)
    shutil.copytree(FIXTURE_DIR, run_dir)
    baseline = codes(baseline_dir)
    assert "UNVALIDATED_ARTIFACT" not in baseline

    proc = _run(run_dir / "landscape_draft.json", [_entry("ramp"), _entry("brex")])
    assert proc.returncode == 0, proc.stderr
    draft = json.loads((run_dir / "landscape_draft.json").read_text(encoding="utf-8"))
    assert [c["slug"] for c in draft["deferred_recall_candidates"]] == ["ramp", "brex"]
    assert draft["_produced_by"] == "persist_agent_artifact"

    assert codes(run_dir) == baseline
