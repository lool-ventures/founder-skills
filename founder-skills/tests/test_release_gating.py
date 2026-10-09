"""The release chain: whenever `publish-release` runs, everything it depends on must run too.

THE CHAIN. The paid gate (`deck-review-e2e-smoke` and `mutation-corpus`) runs ONCE per release, on a
`workflow_dispatch` of the release branch. A tag push does not run it again: `publish-release` needs
`verify-branch-gate`, which proves a dispatched run at the tagged commit concluded `success` on both
paid jobs (`.github/scripts/branch_gate_check.py`), and `contract-tests`, which runs the free suite.

WHY THIS EXISTS. In GitHub Actions **a skipped dependency skips the dependent** unless the dependent's
own `if:` calls a status function (`always()`, `success()`), and `publish-release`'s does not. So a
`verify-branch-gate` whose `if:` stops firing on a tag push does not merely stop gating -- it silently
stops the Release from publishing at all. The converse is the other half: a status function in
`publish-release`'s `if:`, or a `continue-on-error` on the verification, would publish WITHOUT the
evidence. Both directions are pinned here.

That failure is invisible until a release, and this repo has already shipped **four tags with no
Release** because a release step lived only in prose. This chain is first exercised at a release;
`branch-gate-selftest` runs the check itself under a job token on every pull request that matches the
workflow's paths filter, so the script and its token are not first run then.

TWO INDEPENDENT CHECKS, because they fail differently and a single one hides the other:

  1. FREEZE. Each job-level `if:` is pinned verbatim beside a hand-derived truth value for a tag push.
     An edit to a condition reds here and forces someone to re-derive that value by hand. This cannot
     be wrong about GitHub's semantics because it does not model them -- it models a human decision.

  2. EVALUATE. A small evaluator for the expression grammar actually present in this file, run over the
     transitive `needs` closure under a simulated tag push. This catches a *combination* the frozen
     per-job values do not: a closure that grows a new member nobody re-derived.

The evaluator is the part that can be wrong, so it is built to refuse rather than guess: an unknown
context property RAISES. A naive evaluator that defaulted `github.actor` to False, or a newly-added
`inputs.<name>` to '', would green a job GitHub actually skips -- which is the precise failure this
whole file exists to prevent, arriving through the tool meant to detect it.

SCOPE. This asserts the WIRING, never that a job passes. Whether `mutation-corpus` is green is that
job's business; whether a green one is allowed to gate the Release is this file's.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skill-quality.yml"
BRANCH_GATE_SCRIPT = REPO_ROOT / ".github" / "scripts" / "branch_gate_check.py"

# Jobs that SPEND: the paid release gate. They must never run on a tag push (the tag reads their
# result from the dispatched run instead) and never on a pull request.
PAID_JOBS = {"deck-review-e2e-smoke", "mutation-corpus"}

# The context a release tag push presents. `inputs` is EMPTY, not absent: on a `push` the context is
# null and Actions coerces null == '' to true. No condition in the release closure reads `inputs`, so
# the chain does not depend on that coercion.
TAG_PUSH: dict[str, Any] = {
    "github.event_name": "push",
    "github.ref": "refs/tags/v0.11.0",
    "inputs": {},
}

# A dispatch aimed at a tag ref. This is the DANGEROUS context, not `pull_request`: the repo's own
# history records a guard that would have published from a rehearsal dispatch, and `verify-release-notes`
# exists to be run this way. `publish-release` must be false here.
TAG_DISPATCH: dict[str, Any] = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/tags/v0.11.0",
    "inputs": {"verify_release_notes_for": "v0.11.0"},
}

# The paid release gate: a dispatch of the release branch with no inputs. A dispatch without an input
# presents it as '' (run 37973309434 ran the paid job under a condition reading
# `inputs.verify_release_notes_for == ''`).
RELEASE_BRANCH_DISPATCH: dict[str, Any] = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/release/v0.11.0",
    "inputs": {},
}

PULL_REQUEST: dict[str, Any] = {
    "github.event_name": "pull_request",
    "github.ref": "refs/pull/1/merge",
    "inputs": {},
}

# CLEAR `founder-skills/tests/__pycache__` BEFORE TRUSTING A RUN THAT EDITED THIS BLOCK. Measured: a
# break-test swapped 'refs/tags/v' for 'refs/heads/' -- both 11 characters -- so the source SIZE was
# unchanged, and Python's mtime+size invalidation served the mutated bytecode after the source had been
# restored. The file greps clean while the test reports a condition that appears nowhere in it, which
# reads as a bug in the guard rather than a stale artifact. Same class as the repo's standing note that
# an mtime-preserving restore leaves a stale .pyc serving old behaviour.
#
# FROZEN. Left side: the `if:` verbatim (None = no condition, which means "always runs"). Right side:
# whether that condition is TRUE ON A TAG PUSH, derived by hand. Change a condition and this reds --
# that is the point. Re-derive the boolean by reading the new condition, never by running the evaluator
# below and copying its answer, which would make the freeze a mirror of the thing it cross-checks.
FROZEN_CONDITIONS: dict[str, tuple[str | None, bool]] = {
    "contract-tests": (None, True),
    "mutation-corpus": ("github.event_name == 'workflow_dispatch'", False),
    "deck-review-e2e-smoke": (
        "github.event_name == 'workflow_dispatch' && inputs.verify_release_notes_for == ''",
        False,
    ),
    "verify-branch-gate": (
        "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')",
        True,
    ),
    # False on a tag push and OUTSIDE the release closure: it calls the live API, and a transient
    # error there must never skip a Release.
    "branch-gate-selftest": ("github.event_name == 'pull_request'", False),
    "publish-release": (
        "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')",
        True,
    ),
    "verify-release-notes": (
        "github.event_name == 'workflow_dispatch' && inputs.verify_release_notes_for != ''",
        False,
    ),
}


class UnknownExpression(Exception):
    """The evaluator met something it does not model. Never silently defaulted."""


def _jobs() -> dict[str, dict[str, Any]]:
    return dict(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"])


def _needs(job: dict[str, Any]) -> list[str]:
    n = job.get("needs")
    if n is None:
        return []
    return [n] if isinstance(n, str) else list(n)


def _normalize(expr: str | None) -> str | None:
    """YAML block scalars fold newlines; compare on collapsed whitespace."""
    return None if expr is None else " ".join(expr.split())


def _operand(token: str, ctx: dict[str, Any]) -> Any:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1]
    if token in ("true", "false"):
        return token == "true"
    if token in ctx:
        return ctx[token]
    if token.startswith("inputs."):
        # Absent on a push (null), and null == '' in an Actions expression. Modelled explicitly
        # rather than by a bare `.get(..., "")` so that an input this repo does not declare still
        # raises below.
        name = token.split(".", 1)[1]
        declared = _declared_inputs()
        if name not in declared:
            raise UnknownExpression(f"{token!r} is not an input this workflow declares: {sorted(declared)}")
        return ctx["inputs"].get(name, "")
    raise UnknownExpression(
        f"unknown context property {token!r}. The evaluator refuses rather than defaulting: a "
        "silent default would green a job GitHub actually skips, which is the failure this file exists "
        "to catch. Model it explicitly and re-derive the frozen truth values."
    )


def _declared_inputs() -> set[str]:
    on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # `on:` parses as the boolean True in YAML 1.1 unless quoted.
    trigger = on.get("on", on.get(True, {})) or {}
    return set((trigger.get("workflow_dispatch") or {}).get("inputs") or {})


def _split_top(expr: str, op: str) -> list[str] | None:
    """Split on `op` at paren depth 0. Returns None when the operator is not present at top level."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(expr):
        c = expr[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            parts.append(expr[start:i])
            i += len(op)
            start = i
            continue
        i += 1
    if not parts:
        return None
    parts.append(expr[start:])
    return parts


def evaluate(expr: str | None, ctx: dict[str, Any]) -> bool:
    """Evaluate one job-level `if:`. Raises `UnknownExpression` on anything unmodelled.

    `||` binds looser than `&&` in GitHub's grammar, so it is split first -- the same order Python
    and C use, and the order a reader assumes.
    """
    if expr is None:
        return True
    expr = " ".join(expr.split()).strip()
    # Strip ONE fully-enclosing paren pair at a time. The `_balanced` test is what makes this safe:
    # `(a) && (b)` also starts with "(" and ends with ")", and stripping there would corrupt it --
    # `a) && (b` is unbalanced, so the loop stops.
    #
    # A third conjunct used to sit here, `_split_top(expr[1:-1], ")") is None`. It was a CONSTANT:
    # `_split_top` decrements depth on ")" in an earlier branch than the one that could match it as an
    # operator, so splitting on ")" returns None for every input -- verified exhaustively over ~600k
    # strings. It read as a safety check and could not fail, in the one file whose thesis is that a
    # guard must be able to fail. Removed rather than repaired: `_balanced` already does the work.
    while expr.startswith("(") and expr.endswith(")") and _balanced(expr[1:-1]):
        expr = expr[1:-1].strip()

    for op, combine in (("||", any), ("&&", all)):
        parts = _split_top(expr, op)
        if parts:
            return bool(combine(evaluate(p, ctx) for p in parts))

    m = re.fullmatch(r"startsWith\((.+?),\s*('.*?')\)", expr)
    if m:
        haystack = str(_operand(m.group(1), ctx))
        needle = str(_operand(m.group(2), ctx))
        return haystack.casefold().startswith(needle.casefold())
    for op in ("==", "!="):
        parts = _split_top(expr, op)
        if parts and len(parts) == 2:
            left, right = (_operand(p, ctx) for p in parts)
            return _eq(left, right) if op == "==" else not _eq(left, right)
    raise UnknownExpression(
        f"unparseable condition {expr!r}. Extend the evaluator deliberately and re-derive the frozen "
        "truth values; do not widen it until this passes."
    )


def _eq(left: Any, right: Any) -> bool:
    """GitHub's `==`: docs state plainly "GitHub ignores case when comparing strings." `startsWith`,
    `contains`, and `endsWith` each carry their own "This function is not case sensitive." Only the
    string case matters here -- `_operand` never returns anything but `str` or `bool`, and case has no
    meaning for a bool, so this does not need (and does not attempt) GitHub's fuller numeric/array
    coercion rules for `==`."""
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    return bool(left == right)


def _balanced(s: str) -> bool:
    depth = 0
    for c in s:
        depth += c == "("
        depth -= c == ")"
        if depth < 0:
            return False
    return depth == 0


def _closure(start: str, jobs: dict[str, dict[str, Any]]) -> set[str]:
    """Every job `start` transitively depends on. Transitive matters: `deck-review-e2e-smoke` needs
    `contract-tests`, so a skip three levels up still skips the Release."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        for dep in _needs(jobs[current]):
            assert dep in jobs, f"{current} needs {dep!r}, which is not a job in this workflow"
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def test_frozen_conditions_still_match_the_workflow() -> None:
    """A changed `if:` reds here, so nobody edits one without re-deriving what it means for a release."""
    jobs = _jobs()
    assert set(jobs) == set(FROZEN_CONDITIONS), (
        "the workflow's job set changed; add the new job to FROZEN_CONDITIONS with a hand-derived "
        f"tag-push truth value. workflow={sorted(jobs)} frozen={sorted(FROZEN_CONDITIONS)}"
    )
    for name, job in jobs.items():
        frozen, _ = FROZEN_CONDITIONS[name]
        assert _normalize(job.get("if")) == _normalize(frozen), (
            f"{name}'s `if:` changed.\n  frozen:  {frozen!r}\n  current: {job.get('if')!r}\n"
            "Re-derive by hand whether it is still true on a tag push, update FROZEN_CONDITIONS, and "
            "check the release closure still holds."
        )


def test_publish_release_closure_all_runs_on_a_tag_push() -> None:
    """The property that matters: a skipped dependency skips the Release.

    Checked against the FROZEN hand-derived values and the EVALUATOR independently, so a mistake in
    either one is visible rather than absorbed.
    """
    jobs = _jobs()
    closure = _closure("publish-release", jobs)
    assert closure == {"verify-branch-gate", "contract-tests"}, (
        f"the release dependency closure changed: {sorted(closure)}. Every member must run on a tag "
        "push or the Release silently does not publish."
    )
    for name in sorted(closure | {"publish-release"}):
        frozen_expr, frozen_value = FROZEN_CONDITIONS[name]
        assert frozen_value, (
            f"{name} is in `publish-release`'s dependency closure but FROZEN_CONDITIONS records it as "
            "NOT running on a tag push. A skipped dependency skips the dependent, so this does not "
            "merely weaken the gate — it stops the Release publishing."
        )
        assert evaluate(frozen_expr, TAG_PUSH) is True, (
            f"{name}'s condition evaluates FALSE on a tag push: {frozen_expr!r}. "
            "It is in the release closure, so the Release would not publish."
        )


def test_publish_release_does_not_fire_on_a_dispatch_at_a_tag_ref() -> None:
    """Non-vacuity, aimed at the dangerous context rather than a convenient one.

    `pull_request` would also return False and prove the evaluator can, but nobody has ever nearly
    published from a PR. The rehearsal dispatch is the case this repo actually had to guard, and
    `verify-release-notes` is documented as safe to run against a tag.
    """
    expr, _ = FROZEN_CONDITIONS["publish-release"]
    assert evaluate(expr, TAG_DISPATCH) is False, (
        "a workflow_dispatch aimed at a tag ref would publish a Release. The rehearsal is sold as a "
        "cheap safety net; publishing from it is not cheap."
    )


def test_the_evaluator_refuses_what_it_does_not_model() -> None:
    """The evaluator's own guard. A silent default is worse than no evaluator.

    Both classes: a context property that PARSES but is not modelled, and an expression shape that
    does not parse at all. Neither may return a bool.
    """
    with pytest.raises(UnknownExpression):
        evaluate("github.actor == 'nobody'", TAG_PUSH)
    with pytest.raises(UnknownExpression):
        evaluate("inputs.not_a_declared_input == ''", TAG_PUSH)
    with pytest.raises(UnknownExpression):
        evaluate("contains(github.ref, 'v')", TAG_PUSH)


def test_string_comparisons_are_case_insensitive_like_githubs() -> None:
    """GitHub's docs, verbatim: `==` -- "GitHub ignores case when comparing strings" -- and
    `startsWith()` -- "This function is not case sensitive." A case-sensitive evaluator disagrees with
    GitHub on these inputs (would report False for all three below), which is a spurious-red risk, not
    a false-green one -- but every literal in FROZEN_CONDITIONS today happens to be lowercase, so that
    divergence is accidental, not designed in. Pin GitHub's real behaviour rather than relying on luck.
    """
    assert evaluate("startsWith(github.ref, 'REFS/TAGS/V')", TAG_PUSH) is True
    assert evaluate("github.event_name == 'PUSH'", TAG_PUSH) is True
    assert evaluate("github.event_name != 'PUSH'", TAG_PUSH) is False


def test_evaluator_agrees_with_the_frozen_values_everywhere() -> None:
    """Cross-check, and the reason both halves exist.

    A disagreement means either a frozen value was derived wrongly by hand or the evaluator models
    something wrongly. Either is worth a red; silently trusting one over the other is not.
    """
    for name, (expr, frozen_value) in FROZEN_CONDITIONS.items():
        assert evaluate(expr, TAG_PUSH) is frozen_value, (
            f"{name}: hand-derived {frozen_value}, evaluator says {evaluate(expr, TAG_PUSH)} for "
            f"{expr!r}. One of the two is wrong -- resolve it rather than adjusting whichever is easier."
        )


def test_no_paid_job_runs_on_a_tag_push_or_a_pull_request() -> None:
    """The paid gate runs once per release, on the dispatched branch run. A tag that ran it again paid
    twice and, at a measured coin flip, withheld the Release on a flake of a gate already passed."""
    jobs = _jobs()
    closure = _closure("publish-release", jobs)
    assert PAID_JOBS.isdisjoint(closure), f"a paid job is back in the release closure: {sorted(closure)}"
    for name in sorted(PAID_JOBS):
        expr, frozen_value = FROZEN_CONDITIONS[name]
        assert frozen_value is False and evaluate(expr, TAG_PUSH) is False, f"{name} runs on a tag push"
        assert evaluate(expr, PULL_REQUEST) is False, f"{name} runs on a pull request"


def test_the_paid_gate_still_runs_on_a_release_branch_dispatch() -> None:
    """Non-vacuity for the test above: moving the paid jobs off the tag must not move them off the
    release branch too, and the rehearsal dispatch must stay free of the paid lanes."""
    for name in sorted(PAID_JOBS):
        expr, _ = FROZEN_CONDITIONS[name]
        assert evaluate(expr, RELEASE_BRANCH_DISPATCH) is True, f"{name} no longer runs on the release branch"
    for name in ("publish-release", "verify-branch-gate", "branch-gate-selftest"):
        expr, _ = FROZEN_CONDITIONS[name]
        assert evaluate(expr, RELEASE_BRANCH_DISPATCH) is False, f"{name} runs on a release-branch dispatch"
    e2e, _ = FROZEN_CONDITIONS["deck-review-e2e-smoke"]
    assert evaluate(e2e, TAG_DISPATCH) is False, "the release-notes rehearsal would spend on the paid lanes"


def test_publish_cannot_run_without_the_verification() -> None:
    """The verification is a DIRECT need, publish's `if:` has no status function (which would run it
    past a failed or skipped need), the two `if:`s are equal (so the need is never skipped while
    publish runs), and nothing on the verification may fail open."""
    jobs = _jobs()
    publish, verify = jobs["publish-release"], jobs["verify-branch-gate"]
    assert "verify-branch-gate" in _needs(publish)
    cond = _normalize(publish.get("if")) or ""
    for fn in ("always(", "success(", "failure(", "cancelled("):
        assert fn not in cond, f"publish-release's `if:` calls {fn}): it would publish past a failed verification"
    assert _normalize(verify.get("if")) == _normalize(publish.get("if"))
    assert verify.get("permissions") == {"actions": "read", "contents": "read"}, verify.get("permissions")
    assert "continue-on-error" not in verify, "verify-branch-gate may not continue on error"
    for step in verify["steps"]:
        assert "continue-on-error" not in step, f"a verify-branch-gate step continues on error: {step}"
        assert "if" not in step, f"a verify-branch-gate step is conditional, so it can be skipped: {step}"
    assert any("branch_gate_check.py" in str(step.get("run", "")) for step in verify["steps"])


def test_the_selftest_runs_on_pull_requests_outside_the_release_closure() -> None:
    jobs = _jobs()
    selftest = jobs["branch-gate-selftest"]
    expr, _ = FROZEN_CONDITIONS["branch-gate-selftest"]
    assert evaluate(expr, PULL_REQUEST) is True
    assert "branch-gate-selftest" not in _closure("publish-release", jobs)
    assert selftest.get("permissions") == {"actions": "read", "contents": "read"}, selftest.get("permissions")
    assert "continue-on-error" not in selftest
    run = " ".join(str(step.get("run", "")) for step in selftest["steps"])
    assert run.count("branch_gate_check.py") == 2, "one expected pass and one expected failure"
    # The negative arm must require the CLEAN rejection: a crash also exits non-zero.
    assert "grep -q '^::error::no green paid-gate run at ' negative.log" in run, "the negative arm accepts any failure"


def test_the_script_matches_the_workflow_s_display_names() -> None:
    """The jobs API reports display names, so the tag-time check matches those. A rename of either job's
    `name:` reds here, free, instead of withholding the next Release."""
    spec = importlib.util.spec_from_file_location("branch_gate_check", BRANCH_GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    jobs = _jobs()
    assert set(mod.REQUIRED_JOBS) == PAID_JOBS
    for job_id, name in mod.REQUIRED_JOBS.items():
        assert jobs[job_id]["name"] == name, (job_id, jobs[job_id]["name"], name)
