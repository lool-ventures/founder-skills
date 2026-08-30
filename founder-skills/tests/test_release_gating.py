"""The release chain: whenever `publish-release` runs, everything it depends on must run too.

WHY THIS EXISTS. `publish-release` gained `needs: [deck-review-e2e-smoke, mutation-corpus]`. In GitHub
Actions **a skipped dependency skips the dependent** unless the dependent's own `if:` calls a status
function (`always()`, `success()`), and `publish-release`'s does not. So a `mutation-corpus` whose `if:`
stops firing on a tag push does not merely stop gating -- it silently stops the Release from publishing
at all.

That failure is invisible until a release, and this repo has already shipped **four tags with no
Release** because a release step lived only in prose. The chain is also unexercised by construction:
the newest tag (v0.10.0) predates the `publish-release` job, so the tag path has never run.

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

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skill-quality.yml"

# The context a release tag push presents. `inputs` is EMPTY, not absent: on a `push` the context is
# null and Actions coerces null == '' to true. That coercion is real but untested on this repo's tag
# path, which is why the workflow was changed so the release chain no longer depends on it -- see the
# comment on `deck-review-e2e-smoke`'s condition.
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

# FROZEN. Left side: the `if:` verbatim (None = no condition, which means "always runs"). Right side:
# whether that condition is TRUE ON A TAG PUSH, derived by hand. Change a condition and this reds --
# that is the point. Re-derive the boolean by reading the new condition, never by running the evaluator
# below and copying its answer, which would make the freeze a mirror of the thing it cross-checks.
FROZEN_CONDITIONS: dict[str, tuple[str | None, bool]] = {
    "contract-tests": (None, True),
    "mutation-corpus": (
        "github.event_name == 'workflow_dispatch' || startsWith(github.ref, 'refs/tags/v')",
        True,
    ),
    "deck-review-e2e-smoke": (
        "github.event_name != 'pull_request' && "
        "(github.event_name != 'workflow_dispatch' || inputs.verify_release_notes_for == '')",
        True,
    ),
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
    while expr.startswith("(") and expr.endswith(")") and _split_top(expr[1:-1], ")") is None:
        inner = expr[1:-1]
        if _balanced(inner):
            expr = inner.strip()
        else:
            break

    for op, combine in (("||", any), ("&&", all)):
        parts = _split_top(expr, op)
        if parts:
            return bool(combine(evaluate(p, ctx) for p in parts))

    m = re.fullmatch(r"startsWith\((.+?),\s*('.*?')\)", expr)
    if m:
        return str(_operand(m.group(1), ctx)).startswith(str(_operand(m.group(2), ctx)))
    for op in ("==", "!="):
        parts = _split_top(expr, op)
        if parts and len(parts) == 2:
            left, right = (_operand(p, ctx) for p in parts)
            return bool(left == right) if op == "==" else bool(left != right)
    raise UnknownExpression(
        f"unparseable condition {expr!r}. Extend the evaluator deliberately and re-derive the frozen "
        "truth values; do not widen it until this passes."
    )


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
    assert closure == {"deck-review-e2e-smoke", "mutation-corpus", "contract-tests"}, (
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
