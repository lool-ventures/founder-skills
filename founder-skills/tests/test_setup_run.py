from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
    "setup_run.py",
)


def _run(args: list[str], cwd: str) -> tuple[int, dict | None, str]:
    res = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=cwd)
    parsed = json.loads(res.stdout) if res.stdout.strip() else None
    return res.returncode, parsed, res.stderr


def test_setup_run_creates_review_dir_under_artifacts_root() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        rc, out, err = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--pretty"],
            cwd=d,
        )
        assert rc == 0, err
        assert out is not None
        assert out["slug"] == "acme-corp"
        assert out["review_dir"] == os.path.join(artifacts_root, "deck-review-acme-corp")
        assert os.path.isdir(out["review_dir"])
        assert out["artifacts_root"] == artifacts_root


def test_setup_run_generates_iso_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        rc, out, _ = _run(
            ["--artifacts-root", os.path.join(d, "artifacts"), "--slug", "x", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert re.match(r"^\d{8}T\d{6}Z$", out["run_id"])


def test_setup_run_cleans_existing_artifacts_with_clean_flag() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        # Plant stale files
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            with open(os.path.join(review_dir, name), "w") as f:
                f.write("stale")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            assert not os.path.exists(os.path.join(review_dir, name))


def _plant_gate(review_dir: str, run_id: str, answer: str | None, source: str = "founder") -> None:
    """An answered gate carries a source by default, because a real one always does —
    `gate_state.py answer` requires `--source`. The source-less case is a distinct
    condition with its own tests below; these ones are about run_id parity."""
    os.makedirs(review_dir, exist_ok=True)
    body: dict = {"metadata": {"run_id": run_id}}
    if answer is not None:
        body["answer"] = answer
        body["answer_source"] = source
    with open(os.path.join(review_dir, "gate_state.json"), "w") as f:
        json.dump(body, f)


def test_setup_run_resume_answered_matching_run_id_preserves_gate_state() -> None:
    """Answered gate with run_id matching --run-id -> resume true; --clean keeps gate_state.json."""
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        _plant_gate(review_dir, "r1", "Looks right")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "r1", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is True
        assert out["gate_answer"] == "Looks right"
        assert out["gate_run_id"] == "r1"
        # resume -> --clean must NOT delete the gate
        assert os.path.exists(os.path.join(review_dir, "gate_state.json"))


def test_setup_run_clean_deletes_stale_answered_gate_on_run_id_mismatch() -> None:
    """Answered gate from a PRIOR run (run_id mismatch) -> resume false; --clean deletes the stale gate."""
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        _plant_gate(review_dir, "old-run", "Looks right")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "new-run", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is False
        # stale answered gate from a completed prior run must be removed
        assert not os.path.exists(os.path.join(review_dir, "gate_state.json"))


def test_setup_run_unanswered_gate_is_not_a_resume_and_preserved_without_clean() -> None:
    """Gate with no answer -> resume false; without --clean it is preserved."""
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        _plant_gate(review_dir, "r1", None)
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "r1", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is False
        assert out["gate_answer"] == ""
        # no --clean -> nothing is removed
        assert os.path.exists(os.path.join(review_dir, "gate_state.json"))


def test_setup_run_without_clean_flag_preserves_files() -> None:
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        with open(os.path.join(review_dir, "deck_inventory.json"), "w") as f:
            f.write("kept")
        _run(["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--pretty"], cwd=d)
        with open(os.path.join(review_dir, "deck_inventory.json")) as f:
            assert f.read() == "kept"


def test_setup_run_takes_override_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        rc, out, _ = _run(
            [
                "--artifacts-root",
                os.path.join(d, "artifacts"),
                "--slug",
                "x",
                "--run-id",
                "20260101T000000Z",
                "--pretty",
            ],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["run_id"] == "20260101T000000Z"


# ---------------------------------------------------------------------------
# New: resume preserves same-run pipeline artifacts under --clean
# ---------------------------------------------------------------------------


def test_resume_with_clean_preserves_pre_gate_pipeline_artifacts() -> None:
    """On a valid resume (answered gate whose run_id matches --run-id), --clean
    must NOT delete deck_inventory.json or stage_profile.json.  They are
    same-run checkpoints; re-running Steps 2-3 is only necessary when they are
    absent or carry a different run_id.  compose_report.py's run_id parity check
    is the safety net against stale content.
    """
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        _plant_gate(review_dir, "r1", "Looks right")
        # Plant same-run pipeline artifacts
        for name in ("deck_inventory.json", "stage_profile.json"):
            with open(os.path.join(review_dir, name), "w") as f:
                f.write("same-run-content")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "r1", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is True
        # All three artifacts must survive --clean on a resume
        for name in ("deck_inventory.json", "stage_profile.json", "gate_state.json"):
            path = os.path.join(review_dir, name)
            assert os.path.exists(path), f"{name} was deleted by --clean during a resume (must be preserved)"


def test_fresh_run_with_clean_still_deletes_pre_gate_pipeline_artifacts() -> None:
    """A fresh (non-resume) run with --clean must delete deck_inventory.json and
    stage_profile.json even when they are present from a previous run.
    resume must be False in the JSON output.
    """
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        os.makedirs(review_dir)
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            with open(os.path.join(review_dir, name), "w") as f:
                f.write("stale")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "new-run", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is False
        for name in ("deck_inventory.json", "stage_profile.json", "report.md"):
            assert not os.path.exists(os.path.join(review_dir, name)), f"{name} should be deleted on a fresh run"


def test_stale_gate_run_id_mismatch_with_clean_deletes_pipeline_artifacts() -> None:
    """Answered gate from a PRIOR run (run_id mismatch) -> resume is False.
    --clean must delete deck_inventory.json, stage_profile.json, AND gate_state.json.
    """
    with tempfile.TemporaryDirectory() as d:
        artifacts_root = os.path.join(d, "artifacts")
        review_dir = os.path.join(artifacts_root, "deck-review-acme-corp")
        _plant_gate(review_dir, "old-run", "Looks right")
        for name in ("deck_inventory.json", "stage_profile.json"):
            with open(os.path.join(review_dir, name), "w") as f:
                f.write("old-run-content")
        rc, out, _ = _run(
            ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", "new-run", "--clean", "--pretty"],
            cwd=d,
        )
        assert rc == 0
        assert out is not None
        assert out["resume"] is False
        for name in ("deck_inventory.json", "stage_profile.json", "gate_state.json"):
            assert not os.path.exists(os.path.join(review_dir, name)), (
                f"{name} should be deleted when run_id mismatches (stale prior run)"
            )


# ---------------------------------------------------------------------------
# Resume eligibility and checkpoint preservation are SEPARATE decisions, and collapsing
# them is why the obvious fix does not work. The skill always passes `--clean`, and the
# code was `if args.clean and not resume: delete`. So "re-ask the gate but keep the
# checkpoints" — the correct handling of an answer whose source is unrecorded — was not
# expressible: turning resume off deleted the very artifacts it wanted kept, throwing
# away the most expensive stretch of the pipeline to re-ask one question.
#
# These are the two-turn lifecycle tests. The paid deck-review e2e structurally cannot
# cover this: it exposes no question tool, instructs the model not to ask, and supplies
# no answer turn, so there is no second turn for it to observe. A green e2e is not F4
# coverage and must not be read as any.
# ---------------------------------------------------------------------------


def _plant_sourced_gate(
    review_dir: str, run_id: str, answer: str, source: str | None, gate_id: str = "stage_confirmation"
) -> None:
    """A planted gate carries a `gate_id`, because a real one always does — `emit`
    schema-validates it as required. The auto-satisfy pair is re-checked at read time, so
    a fixture omitting it is not merely incomplete, it exercises a different branch."""
    os.makedirs(review_dir, exist_ok=True)
    body: dict = {"metadata": {"run_id": run_id}, "gate_id": gate_id, "answer": answer}
    if source is not None:
        body["answer_source"] = source
    with open(os.path.join(review_dir, "gate_state.json"), "w") as f:
        json.dump(body, f)


def _plant_checkpoints(review_dir: str) -> None:
    for name in ("deck_inventory.json", "stage_profile.json"):
        with open(os.path.join(review_dir, name), "w") as f:
            f.write("{}")


def _turn(d: str, run_id: str) -> dict:
    artifacts_root = os.path.join(d, "artifacts")
    rc, out, _ = _run(
        ["--artifacts-root", artifacts_root, "--slug", "acme-corp", "--run-id", run_id, "--clean", "--pretty"],
        cwd=d,
    )
    assert rc == 0
    assert out is not None
    return out


def test_a_founder_sourced_answer_resumes() -> None:
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", "founder")
        _plant_checkpoints(review_dir)
        out = _turn(d, "r1")
        assert out["resume"] is True
        assert out["answer_source"] == "founder"
        assert os.path.exists(os.path.join(review_dir, "deck_inventory.json"))


def test_an_auto_satisfied_answer_also_resumes() -> None:
    """Auto-satisfy is a legitimate path — the founder answered in Step 1. Recording it
    is the point; blocking it would defeat the step it exists to skip."""
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", "auto_satisfied")
        _plant_checkpoints(review_dir)
        out = _turn(d, "r1")
        assert out["resume"] is True
        assert out["answer_source"] == "auto_satisfied"


def test_an_answer_with_no_recorded_source_re_asks_but_keeps_the_checkpoints() -> None:
    """The defect this fix exists for, and the reason the two variables had to split.

    An answered same-run gate carrying no `answer_source` was written by a path that
    bypassed the CLI or predates it, so it cannot be audited — re-ask it. But Steps 2-3
    already ran for this run_id, and re-running them is three dispatches, two of which
    read the deck. Keep them.
    """
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", None)
        _plant_checkpoints(review_dir)
        out = _turn(d, "r1")
        assert out["resume"] is False, "an unauditable answer must not silently resume"
        for name in ("deck_inventory.json", "stage_profile.json"):
            assert os.path.exists(os.path.join(review_dir, name)), f"{name} was deleted to re-ask one question"


def test_a_prior_runs_answer_is_still_stale_however_it_was_sourced() -> None:
    """The run_id rule is unchanged and takes precedence: a `founder` source on a
    DIFFERENT run's gate is a real answer to a question about a different run."""
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "old-run", "Looks right", "founder")
        _plant_checkpoints(review_dir)
        out = _turn(d, "new-run")
        assert out["resume"] is False
        assert not os.path.exists(os.path.join(review_dir, "gate_state.json"))
        for name in ("deck_inventory.json", "stage_profile.json"):
            assert not os.path.exists(os.path.join(review_dir, name)), "a fresh run must not inherit checkpoints"


def test_the_two_turn_gate_lifecycle_end_to_end() -> None:
    """Turn 1 emits and is answered; turn 2 resumes on the answer turn 1 recorded."""
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")

        first = _turn(d, "r1")
        assert first["resume"] is False, "a run with no gate on disk is not a resume"

        gate_path = os.path.join(review_dir, "gate_state.json")
        gate_script = os.path.join(os.path.dirname(SCRIPT), "gate_state.py")
        body = {
            "gate_id": "stage_confirmation",
            "question": "Does this stage detection look right?",
            "options": ["Looks right", "Different stage"],
            "context_summary": "Detected: Seed",
        }
        emit = subprocess.run(
            [sys.executable, gate_script, "emit", "--run-id", "r1", "-o", gate_path],
            input=json.dumps(body),
            capture_output=True,
            text=True,
        )
        assert emit.returncode == 0, emit.stderr
        _plant_checkpoints(review_dir)
        ans = subprocess.run(
            [
                sys.executable,
                gate_script,
                "answer",
                "--file",
                gate_path,
                "--answer",
                "Looks right",
                "--source",
                "founder",
            ],
            capture_output=True,
            text=True,
        )
        assert ans.returncode == 0, ans.stderr

        second = _turn(d, "r1")
        assert second["resume"] is True
        assert second["gate_answer"] == "Looks right"
        assert second["answer_source"] == "founder"
        assert os.path.exists(os.path.join(review_dir, "deck_inventory.json"))


def test_auto_satisfied_is_re_checked_at_read_time_not_trusted() -> None:
    """`gate_state.py` enforces the auto-satisfy pair at write time, and that check was
    routable around through `emit`. A rule that authorises skipping a founder's decision
    should not rest on one choke point, so it is re-checked here — whatever put the file
    on disk, an `auto_satisfied` source outside its one legal pair does not resume."""
    for gate_id, answer in (
        ("out_of_scope_choice", "Proceed anyway (best-effort)"),
        ("stage_choice", "Series A"),
        ("stage_confirmation", "Different stage"),
    ):
        with tempfile.TemporaryDirectory() as d:
            review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
            _plant_sourced_gate(review_dir, "r1", answer, "auto_satisfied", gate_id=gate_id)
            out = _turn(d, "r1")
            assert out["resume"] is False, f"{gate_id}/{answer!r} self-authorised a resume"

    # The one legal pair still resumes, or the guard has eaten the feature.
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", "auto_satisfied")
        assert _turn(d, "r1")["resume"] is True


def test_checkpoint_reuse_is_reported_separately_from_gate_resume() -> None:
    """Splitting the two variables inside `setup_run.py` bought nothing on its own.

    The unauditable-answer case returns `resume: false` and preserves the checkpoints —
    but SKILL.md keys its "skip Steps 2 and 3" branch on `resume`, so the preserved
    artifacts were re-run and overwritten anyway, and the expensive stretch the
    preservation exists to protect was spent regardless.

    The consumer needs the second variable by name, so it is reported by name.
    """
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", None)
        _plant_checkpoints(review_dir)
        out = _turn(d, "r1")
        assert out["resume"] is False, "the gate must still be re-asked"
        assert out["reuse_checkpoints"] is True, "the preserved checkpoints are not reported as reusable"

    # A genuine resume reuses them too.
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "artifacts", "deck-review-acme-corp")
        _plant_sourced_gate(review_dir, "r1", "Looks right", "founder")
        _plant_checkpoints(review_dir)
        out = _turn(d, "r1")
        assert out["resume"] is True and out["reuse_checkpoints"] is True

    # A fresh run has nothing to reuse, and says so.
    with tempfile.TemporaryDirectory() as d:
        out = _turn(d, "r1")
        assert out["resume"] is False and out["reuse_checkpoints"] is False
