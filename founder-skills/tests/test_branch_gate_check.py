"""The tag-time paid-gate check, `.github/scripts/branch_gate_check.py`.

`publish-release` needs `verify-branch-gate`, which runs this script: a Release is created only when a
dispatched run of `skill-quality.yml` at the tagged commit concluded `success` on both paid jobs in its
latest attempt. The decision is a pure function (`judge`) tested here against fixtures shaped like the
real API objects (run 37973309434, the v0.17.3 release-branch dispatch; run 37987474294, the v0.17.3 tag
push whose attempt 1 failed and attempt 2 passed). The I/O wrapper is tested for failing CLOSED: an API
error ends the script non-zero, and the runs call reads every page.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
from typing import Any

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "branch_gate_check.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("branch_gate_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk: Any = _load()

SHA = "d4e337c4fe382b7d7ef55a7b55912c5258405367"
NEAR_MISS = "79296d4" + "0" * 33
E2E = "end-to-end smoke, 3 skills (real LLM)"
CORPUS = "Curated mutant corpus (cap-table)"


def _run(
    run_id: int = 37973309434,
    *,
    branch: str = "release/v0.17.3",
    event: str = "workflow_dispatch",
    sha: str = SHA,
    status: str = "completed",
    conclusion: str | None = "success",
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "event": event,
        "head_branch": branch,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "path": ".github/workflows/skill-quality.yml",
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
    }


def _jobs(e2e: str | None = "success", corpus: str | None = "success", attempt: int = 1) -> list[dict[str, Any]]:
    """The latest attempt's jobs, as `jobs?filter=latest` lists them. None = the job is absent."""
    jobs = [
        {"name": "Contract + Cowork-invariant tests (free, fast)", "conclusion": "success", "run_attempt": attempt},
        {"name": "Rehearse release notes (publishes nothing)", "conclusion": "skipped", "run_attempt": attempt},
        {"name": "Create the GitHub Release (tag runs only)", "conclusion": "skipped", "run_attempt": attempt},
    ]
    if e2e is not None:
        jobs.append({"name": E2E, "conclusion": e2e, "run_attempt": attempt})
    if corpus is not None:
        jobs.append({"name": CORPUS, "conclusion": corpus, "run_attempt": attempt})
    return jobs


def _judge(runs: list[dict[str, Any]], jobs: dict[Any, list[dict[str, Any]]]) -> tuple[Any, list[Any]]:
    accepted, rejected = chk.judge(runs, jobs, SHA)
    return accepted, rejected


def test_a_green_release_branch_dispatch_passes() -> None:
    run = _run()
    accepted, rejected = _judge([run], {run["id"]: _jobs()})
    assert accepted is run and rejected == []


def test_the_rehearsal_dispatch_is_rejected_although_the_run_concluded_success() -> None:
    """A `verify_release_notes_for` dispatch concludes `success` with both paid jobs skipped. Only the
    per-job check rejects it; the run's own conclusion must never be read."""
    run = _run(conclusion="success")
    accepted, rejected = _judge([run], {run["id"]: _jobs(e2e="skipped", corpus="success")})
    assert accepted is None
    assert "concluded 'skipped'" in rejected[0][1]


def test_a_failure_re_run_green_passes() -> None:
    """`filter=latest` lists attempt 2's jobs; a job carried over from attempt 1 keeps its conclusion."""
    run = _run(37987474294, attempt=2)
    accepted, _ = _judge([run], {run["id"]: _jobs(attempt=2)})
    assert accepted is run


def test_green_then_re_run_red_is_rejected() -> None:
    run = _run(attempt=2, conclusion="failure")
    accepted, rejected = _judge([run], {run["id"]: _jobs(e2e="failure", attempt=2)})
    assert accepted is None and "deck-review-e2e-smoke concluded 'failure'" in rejected[0][1]


def test_a_run_still_in_progress_is_rejected_with_a_re_run_instruction() -> None:
    run = _run(status="in_progress", conclusion=None)
    accepted, rejected = _judge([run], {run["id"]: _jobs(e2e=None)})
    assert accepted is None
    assert "still 'in_progress'" in rejected[0][1] and "re-run this job" in rejected[0][1]


@pytest.mark.parametrize("branch", ["release/v0.17.3", "main", "feature/x", "v0.17.3"])
def test_any_branch_at_the_exact_commit_passes(branch: str) -> None:
    """The commit identifies what was tested; the branch name adds no security. `v0.17.3` is the
    override's tag-ref dispatch."""
    run = _run(branch=branch)
    accepted, _ = _judge([run], {run["id"]: _jobs()})
    assert accepted is run


def test_a_run_at_a_near_miss_commit_on_the_same_branch_is_rejected_on_the_commit() -> None:
    """v0.17.2's branch had two dispatches; only the second was at the tagged commit."""
    run = _run(sha=NEAR_MISS)
    accepted, rejected = _judge([run], {run["id"]: _jobs()})
    assert accepted is None and "not this commit" in rejected[0][1]


def test_a_pull_request_run_at_the_commit_is_rejected() -> None:
    run = _run(37973311334, event="pull_request")
    accepted, rejected = _judge([run], {run["id"]: _jobs()})
    assert accepted is None and "not a dispatch" in rejected[0][1]


def test_e2e_failed_while_the_corpus_passed_is_rejected() -> None:
    run = _run()
    accepted, rejected = _judge([run], {run["id"]: _jobs(e2e="failure")})
    assert accepted is None and "deck-review-e2e-smoke" in rejected[0][1]


@pytest.mark.parametrize("missing", ["e2e", "corpus"])
def test_a_required_job_absent_from_the_list_is_rejected_never_skipped(missing: str) -> None:
    run = _run()
    jobs = _jobs(e2e=None) if missing == "e2e" else _jobs(corpus=None)
    accepted, rejected = _judge([run], {run["id"]: jobs})
    assert accepted is None and "not found" in rejected[0][1]


def test_a_run_with_no_jobs_listed_is_rejected() -> None:
    run = _run()
    no_jobs: list[dict[Any, list[dict[str, Any]]]] = [{}, {run["id"]: []}]
    for jobs in no_jobs:
        accepted, rejected = _judge([run], jobs)
        assert accepted is None and "no jobs" in rejected[0][1]


def test_no_runs_is_rejected() -> None:
    assert _judge([], {}) == (None, [])


def test_one_green_run_among_several_passes_and_the_red_sibling_is_reported() -> None:
    red, green = _run(1, conclusion="failure"), _run(2)
    accepted, rejected = _judge([red, green], {1: _jobs(e2e="failure"), 2: _jobs()})
    assert accepted is green and [r["id"] for r, _ in rejected] == [1]


# --- the I/O wrapper ---------------------------------------------------------------------------------


class _FakeGh:
    """Stands in for `subprocess.run(["gh", "api", ...])`, keyed on the endpoint argument."""

    def __init__(self, responses: dict[str, Any], fail: bool = False) -> None:
        self.responses, self.fail = responses, fail
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        assert kw.get("check") is True, "every gh call must be check=True"
        if self.fail:
            raise subprocess.CalledProcessError(1, cmd)
        endpoint = cmd[-1]
        key = next(k for k in self.responses if k in endpoint)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(self.responses[key]), "")


def _main(monkeypatch: pytest.MonkeyPatch, fake: _FakeGh, sha: str = SHA, tag: str = "v0.17.3") -> int:
    monkeypatch.setattr(chk.subprocess, "run", fake)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rc: int = chk.main(["--sha", sha, "--tag", tag, "--repo", "o/r"])
    return rc


def test_main_passes_and_reads_every_page_of_runs(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """`--paginate --slurp` returns a LIST of pages; the green run is on page 2 here."""
    pages = [{"workflow_runs": [_run(1, conclusion="failure")]}, {"workflow_runs": [_run(2)]}]
    fake = _FakeGh({"/runs?": pages, "runs/1/jobs": {"jobs": _jobs(e2e="failure")}, "runs/2/jobs": {"jobs": _jobs()}})
    assert _main(monkeypatch, fake) == 0
    runs_call = fake.calls[0]
    assert "--paginate" in runs_call and "--slurp" in runs_call
    assert f"head_sha={SHA}" in runs_call[-1] and "event=workflow_dispatch" in runs_call[-1]
    assert all("filter=latest" in c[-1] for c in fake.calls[1:])
    out = capsys.readouterr().out
    assert "passed" in out and "::warning::" in out and "runs/1" in out


def test_main_fails_naming_the_override_when_no_run_exists(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    fake = _FakeGh({"/runs?": [{"workflow_runs": []}]})
    assert _main(monkeypatch, fake) == 1
    err = capsys.readouterr().err
    # The literal the workflow's self-test greps for: only this line counts as a clean rejection.
    assert any(line.startswith("::error::no green paid-gate run at ") for line in err.splitlines()), err
    assert "gh workflow run skill-quality.yml --ref v0.17.3" in err
    assert "gh run rerun" in err and "30 days" in err and "gh release create" in err


def test_main_fails_closed_on_an_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _main(monkeypatch, _FakeGh({}, fail=True))


def test_main_fails_closed_on_an_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises((KeyError, SystemExit)):
        _main(monkeypatch, _FakeGh({"/runs?": {"message": "not a page list"}}))
    with pytest.raises(KeyError):
        _main(monkeypatch, _FakeGh({"/runs?": [{"workflow_runs": [_run()]}], "/jobs": {"message": "x"}}))


def test_an_abbreviated_sha_is_expanded_or_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API's head_sha filter matches only the full SHA: an abbreviated one returns zero runs, which
    would read as "no branch run". It is expanded through git, or refused."""
    monkeypatch.chdir(REPO)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert chk._full_sha(head[:12]) == head
    assert chk._full_sha(SHA) == SHA
    with pytest.raises(SystemExit):
        chk._full_sha("not-a-commit-anywhere")
