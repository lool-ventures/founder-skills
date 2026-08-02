"""Unit tests for the runtime no-change-prefix checker."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "gate_prefix_check",
    pathlib.Path(__file__).resolve().parents[2] / "cowork-tests" / "gate_prefix_check.py",
)
assert _SPEC and _SPEC.loader
gpc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gpc)

P = gpc.NO_CHANGE_PREFIX


def test_conforming_gate_passes() -> None:
    gates = [("does this set look right?", [f"{P}looks good as drafted", "Add Kickserv", "Remove some"])]
    assert gpc.check(gates, P) == []


def test_zero_carrying_fails() -> None:
    gates = [("q", ["Looks good", "Add Kickserv"])]
    problems = gpc.check(gates, P)
    assert len(problems) == 1 and "exactly-one" in problems[0]


def test_two_carrying_fails() -> None:
    """At-least-one would pass this; exactly-one is the point."""
    gates = [("q", [f"{P}keep as drafted", f"{P}also fine", "Add Kickserv"])]
    problems = gpc.check(gates, P)
    assert len(problems) == 1 and "exactly-one" in problems[0]


def test_mutating_option_may_not_borrow_the_prefix() -> None:
    """The negative case a declaration test can never reach."""
    gates = [("q", [f"{P}add both Kickserv and Service Fusion", "Keep current 6"])]
    problems = gpc.check(gates, P)
    assert any("reserved" in p for p in problems)


def test_real_pre_fix_gates_are_rejected() -> None:
    """Verbatim from live runs before the fix — the checker must reject all of them."""
    for labels in (
        # run l6niqzf5mo
        [
            "Looks good, add FieldPulse",
            "Looks good as-is (keep 7)",
            "Add both FieldPulse and Service Fusion",
            "Remove or swap a competitor",
        ],
        # run l78j9nwiz4
        [
            "Looks good — add both Kickserv and Service Fusion",
            "Looks good — add only Kickserv",
            "Looks good — add only Service Fusion",
            "Looks good — keep current 6 only",
        ],
        # run l6ngg0gbyr — closest to spec, still no reserved handle
        ["Looks good", "Add some from the recall list", "Remove ServiceTitan", "Change axes"],
    ):
        assert gpc.check([("q", labels)], P), f"should have been rejected: {labels}"


@pytest.mark.parametrize("tail", ["keep the set as drafted", "proceed to scoring", "skip these"])
def test_benign_tails_are_not_flagged_as_mutating(tail: str) -> None:
    assert gpc.check([("q", [P + tail, "Change axes"])], P) == []


def test_duplicate_emissions_collapse(tmp_path: pathlib.Path) -> None:
    """A gate recorded twice must not be counted (or reported) twice."""
    ev = tmp_path / "events.jsonl"
    rec = (
        '{"name":"AskUserQuestion","input":{"questions":[{"question":"q",'
        '"options":[{"label":"Looks good"},{"label":"Add one"}]}]}}'
    )
    ev.write_text(rec + "\n" + rec + "\n", encoding="utf-8")
    assert len(gpc.collect_gates(tmp_path)) == 1


def _substance_run(tmp: pathlib.Path, offered: list[str], final: list[str]) -> pathlib.Path:
    import json as _j

    (tmp / "competitor_verification.json").write_text(
        _j.dumps({"recall_gaps": {"unmatched": [{"slug": s} for s in offered]}}), encoding="utf-8"
    )
    (tmp / "landscape.json").write_text(_j.dumps({"competitors": [{"slug": s} for s in final]}), encoding="utf-8")
    return tmp


def test_substance_passes_when_no_candidate_entered(tmp_path: pathlib.Path) -> None:
    d = _substance_run(tmp_path, offered=["workiz", "kickserv"], final=["jobber", "housecall-pro"])
    problems, info = gpc.check_substance(d)
    assert problems == [] and info["leaked"] == []


def test_substance_catches_form_honoured_but_set_mutated(tmp_path: pathlib.Path) -> None:
    """The failure the label check cannot see: prefix present, set changed anyway."""
    d = _substance_run(tmp_path, offered=["workiz", "kickserv"], final=["jobber", "workiz"])
    problems, info = gpc.check_substance(d)
    assert len(problems) == 1 and "substance" in problems[0] and info["leaked"] == ["workiz"]


def test_substance_reports_evidence_unavailable_rather_than_passing(tmp_path: pathlib.Path) -> None:
    """No candidates offered => 'unchanged' is untestable, and must not read as a pass."""
    d = _substance_run(tmp_path, offered=[], final=["jobber"])
    problems, _ = gpc.check_substance(d)
    assert problems and "evidence unavailable" in problems[0]


@pytest.mark.parametrize("dash", ["—", "–", "-"])
def test_dash_variants_all_count_as_carrying(dash: str) -> None:
    """A lookalike dash must not be scored as zero-carrying.

    Reporting a design failure when the design held is the worst wrong answer a
    checker can give, because it condemns a working rule.
    """
    label = f"No changes {dash} looks good as drafted"
    assert gpc.check([("q", [label, "Add Kickserv"])], P) == []


def test_at_most_one_allows_zero_for_data_entry_gates() -> None:
    """A gate asking for a fact has no legitimate no-change branch."""
    gates = [("What stage are you at?", ["Seed", "Series A", "Series B"])]
    assert gpc.check(gates, P, require_exactly_one=False) == []
    assert gpc.check(gates, P, require_exactly_one=True)  # exactly-one still rejects


def test_at_most_one_still_rejects_two() -> None:
    gates = [("q", [f"{P}keep", f"{P}also keep", "Seed"])]
    problems = gpc.check(gates, P, require_exactly_one=False)
    assert len(problems) == 1 and "at-most-one" in problems[0]


# --- regressions from the adversarial review of commits 5128602..fbf6607 ---


@pytest.mark.parametrize("dash", ["—", "–", "-"])
def test_unspaced_dash_counts_as_carrying(dash: str) -> None:
    """The review's finding: the original fold handled spaced dashes only.

    "No changes—looks good" (no surrounding spaces) is a plausible, common model
    rendering, not an edge case — and it scored zero-carrying before this fix,
    reporting a design failure where the design held.
    """
    assert gpc.check([("q", [f"No changes{dash}looks good", "Add Kickserv"])], P) == []


def test_substance_normalizes_slugs_before_comparing(tmp_path: pathlib.Path) -> None:
    """The review's finding: a raw comparison misses a leak whose slug form
    merely differs, silently, in the one check whose job is catching leaks.

    `recall_gaps.unmatched[].slug` is ALREADY normalized (verify_competitors.py
    stamps it via normalize_competitor_slug before this ever reaches JSON), but
    `landscape.json`'s slugs are agent-authored and only kebab-case-CHECKED, not
    normalized — validate_landscape.py's format check does not require lowercase
    to already hold. So a landscape entry written "FieldPulse" (uppercase,
    format check aside) is the realistic collision: raw "fieldpulse" != "FieldPulse"
    (case-sensitive), but both normalize to "fieldpulse". Verified against the
    real function, not assumed: normalize_competitor_slug("FieldPulse") ==
    normalize_competitor_slug("fieldpulse") == "fieldpulse".
    """
    d = _substance_run(tmp_path, offered=["fieldpulse"], final=["jobber", "FieldPulse"])
    problems, info = gpc.check_substance(d)
    assert len(problems) == 1 and "substance" in problems[0]
    assert info["leaked"] == ["fieldpulse"]


def test_substance_evidence_unavailable_exits_2_not_1(tmp_path: pathlib.Path) -> None:
    """The review's finding: evidence-unavailable and a real violation both
    exited 1, so a caller could not tell "this run proved nothing" apart from
    "this run failed" by exit code alone.
    """
    import subprocess
    import sys as _sys

    run_dir = _substance_run(tmp_path, offered=[], final=["jobber"])
    # A conforming gate, so the only problem is the substance evidence-unavailable.
    (run_dir / "events.jsonl").write_text(
        '{"name":"AskUserQuestion","input":{"questions":[{"question":"q",'
        f'"options":[{{"label":"{P}looks good"}},{{"label":"Add one"}}]}}]}}\n',
        encoding="utf-8",
    )
    script = pathlib.Path(__file__).resolve().parents[2] / "cowork-tests" / "gate_prefix_check.py"
    result = subprocess.run([_sys.executable, str(script), str(run_dir), "--substance"], capture_output=True, text=True)
    assert result.returncode == 2, f"expected exit 2 (evidence unavailable), got {result.returncode}: {result.stderr}"


# ------------------------------------------------- cassette-file mode (CI has no run dir)


def _write_cassette_gates(tmp_path: pathlib.Path, gate_records: list[str], *, name: str = "cassette") -> pathlib.Path:
    """A minimal committed-cassette shape carrying `events` as raw JSON-line
    strings — exactly what a live run writes to events.jsonl, verbatim."""
    import json as _j

    cassette = tmp_path / f"{name}.cassette.json"
    cassette.write_text(_j.dumps({"scenario": {}, "artifacts": [], "events": gate_records}), encoding="utf-8")
    return cassette


def test_cassette_mode_collect_gates() -> None:
    """CI's only evidence: gate_prefix_check pointed at a committed cassette
    file directly, reading its frozen `events` array instead of events.jsonl."""
    rec = (
        '{"name":"AskUserQuestion","input":{"questions":[{"question":"q",'
        '"options":[{"label":"' + P + 'looks good"},{"label":"Add one"}]}]}}'
    )
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cassette = _write_cassette_gates(pathlib.Path(td), [rec])
        gates = gpc.collect_gates(cassette)
        assert len(gates) == 1
        assert gpc.check(gates, P) == []


def test_cassette_mode_no_gates_is_evidence_unavailable() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cassette = _write_cassette_gates(pathlib.Path(td), [])
        assert gpc.collect_gates(cassette) == []


def test_cassette_mode_cli_at_most_one_exit_codes() -> None:
    """The exact invocation cowork-replay.yml / rerecord.sh use against a
    committed cassette: `--at-most-one`, no run dir on disk at all."""
    import subprocess
    import sys as _sys
    import tempfile

    script = pathlib.Path(__file__).resolve().parents[2] / "cowork-tests" / "gate_prefix_check.py"
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        # A data-entry gate (no legitimate no-change branch) must NOT fail under --at-most-one.
        ok = _write_cassette_gates(
            tmp,
            [
                '{"name":"AskUserQuestion","input":{"questions":[{"question":"stage?",'
                '"options":[{"label":"Seed"},{"label":"Series A"}]}]}}'
            ],
            name="ok",
        )
        result = subprocess.run(
            [_sys.executable, str(script), str(ok), "--at-most-one"], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

        # Two options carrying the reserved token is a real violation under either mode.
        bad = _write_cassette_gates(
            tmp,
            [
                '{"name":"AskUserQuestion","input":{"questions":[{"question":"q",'
                '"options":[{"label":"' + P + 'keep"},{"label":"' + P + 'also keep"}]}]}}'
            ],
            name="bad",
        )
        result = subprocess.run(
            [_sys.executable, str(script), str(bad), "--at-most-one"], capture_output=True, text=True
        )
        assert result.returncode == 1, result.stderr

        empty = _write_cassette_gates(tmp, [], name="empty")
        result = subprocess.run(
            [_sys.executable, str(script), str(empty), "--at-most-one"], capture_output=True, text=True
        )
        assert result.returncode == 2, result.stderr


def test_cassette_mode_check_substance_reads_inlined_artifact_bodies() -> None:
    """`--substance` on a cassette must read INLINED artifact bodies (`body`
    key), not rglob for a filename that has no filesystem existence here."""
    import json as _j
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cassette = pathlib.Path(td) / "c.cassette.json"
        doc = {
            "scenario": {},
            "events": [],
            "artifacts": [
                {
                    "path": "outputs/artifacts/x/competitor_verification.json",
                    "body": _j.dumps({"recall_gaps": {"unmatched": [{"slug": "workiz"}]}}),
                },
                {
                    "path": "outputs/artifacts/x/landscape.json",
                    "body": _j.dumps({"competitors": [{"slug": "jobber"}]}),
                },
            ],
        }
        cassette.write_text(_j.dumps(doc), encoding="utf-8")
        problems, info = gpc.check_substance(cassette)
        assert problems == []
        assert info["leaked"] == []


def test_cassette_mode_check_substance_hash_only_artifact_is_evidence_unavailable() -> None:
    """A large artifact recorded hash-only (no `body`) must not be silently
    treated as empty content — it must read as evidence-unavailable."""
    import json as _j
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cassette = pathlib.Path(td) / "c.cassette.json"
        doc = {
            "scenario": {},
            "events": [],
            "artifacts": [
                {"path": "outputs/artifacts/x/competitor_verification.json", "bytes": 999999, "sha256": "deadbeef"},
                {"path": "outputs/artifacts/x/landscape.json", "body": _j.dumps({"competitors": []})},
            ],
        }
        cassette.write_text(_j.dumps(doc), encoding="utf-8")
        problems, _info = gpc.check_substance(cassette)
        assert problems and "evidence unavailable" in problems[0]
