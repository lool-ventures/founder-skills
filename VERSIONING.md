# Versioning Policy

## Overview

founder-skills is a single Claude Cowork/Code plugin distributed via Git marketplace.
There is one version to track.

| Component | Version Source | Format |
|-----------|----------------|--------|
| Plugin | `founder-skills/.claude-plugin/plugin.json` → `version` | SemVer |

`pyproject.toml` also carries a version for dev tooling. Keep it in sync manually.

## Semantic Versioning

We follow [SemVer 2.0.0](https://semver.org/).

### When to Bump MAJOR (breaking change)

- Removing a skill or agent
- Changing script JSON output structure in incompatible ways
- Removing or renaming script flags

### When to Bump MINOR (new feature, backwards-compatible)

- Adding a new skill or agent
- Adding new scripts or optional script flags
- Adding new fields to script JSON output (additive)

### When to Bump PATCH (bug fix, backwards-compatible)

- Fixing script bugs without changing the output contract
- Skill content rewrites or improvements (SKILL.md, agent prompts)
- Reference material updates
- Documentation improvements that ship inside the plugin

These are bumps by *policy*, and the CI path filter (below) enforces them: it
forces a bump for any non-test file under `founder-skills/` — including in-plugin
Markdown (`skills/*/SKILL.md`, `skills/*/references/*.md`, `agents/*.md`) — and for
`pyproject.toml`. Only repository-level Markdown (README, CONTRIBUTING, `docs/`) is
exempt.

### No Version Bump Needed

- CI workflow changes (`.github/`)
- Test additions or fixes (`founder-skills/tests/`)
- Repository-level docs and other markdown (`*.md`: README, CONTRIBUTING, this file, `docs/`)
- `.gitignore` / `.editorconfig` / `uv.lock`

## Pre-1.0

The plugin is currently at 0.x.y. Per [SemVer spec item 4](https://semver.org/#spec-item-4):

> Major version zero (0.y.z) is for initial development. Anything MAY change at any time.

This means minor bumps (0.1 → 0.2) may include breaking changes.

## Changelog Format

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/) with one addition:
every version entry must start with a `### Highlights` section.

```markdown
## [0.2.0] - 2026-XX-XX

### Highlights

1-3 sentences in plain language summarizing why users should update.
Write for the founder, not the developer.

### Added
- ...

### Fixed
- ...
```

## Release Discipline

Two non-negotiable rules. CI enforces the second mechanically (see `.github/workflows/version-check.yml`).

### 1. `main` is the only canonical release branch

The marketplace clone tracks `main`. A release that lives on a feature branch — even if tagged — has not been released to consumers.

- Every release must merge to `main`. A `release/vX.Y.Z` branch exists only to run the release gate before `main` moves, and is deleted once `main` carries the release (this repository's `delete_branch_on_merge` setting usually does that itself); it is never a substitute for `main`.
- The `version` field on `main` is what users actually see (the marketplace clone tracks `main`), so **pushing `main` is the distribution event**. Tags do not change what users install. The paid release gate (`deck-review-e2e-smoke` and `mutation-corpus` in `.github/workflows/skill-quality.yml`) therefore runs once, on the release branch, before `main` is pushed. The tag push does not run it again: its `verify-branch-gate` job checks that the tag matches both `pyproject.toml` and `plugin.json`, checks the Scoring changes section, and finds the green release-branch run at the tagged commit before the Release is created — see "How to Release" below and the Release Process section of CLAUDE.md.

### 2. Every content change on `main` must bump the version

`claude plugin update` keys off `plugin.json#version`. If two commits land on `main` under the same version, the second is invisible to anyone who installed at the first — `update` becomes a permanent no-op for them.

- Treat `plugin.json#version` as immutable per `main` commit-state.
- If you've already pushed `0.4.0` and need to add a fix: bump to `0.4.1`. Don't sneak fixes under the existing version.
- The version bump should be the **last** commit of a release branch — never the first. A fix found while the release branch is still under test, before `main` carries the version, goes below the bump commit with no new bump (see "How to Release"); once `main` carries the version, any further fix needs a new bump.

The "No Version Bump Needed" cases above (CI workflow changes, test-only changes, repository markdown, lockfile) are exactly the paths the CI check's `requires_bump()` filter exempts. The filter forces a bump for any other file under `founder-skills/` and for `pyproject.toml` — note this includes `plugin.json` metadata-only edits (description/author), which therefore do require a bump despite being non-functional.

## How to Release

Releases are manual up to the tag push; CI then creates the GitHub Release. `main` does not move until the release has passed the paid gate on its own branch. On version bump:

1. Update `version` in `founder-skills/.claude-plugin/plugin.json`
2. Update `version` in `pyproject.toml` to match
3. Update `CHANGELOG.md` — add a `## [X.Y.Z]` section for the new version (this repository keeps no `[Unreleased]` section; the release scripts read only versioned headings), with `### Highlights` first, and a `### Scoring changes` section ("None." when nothing changed), which is checked at tag time
4. Commit on local `main` with a sign-off (`git commit -s`; this should be the **last** commit of the release), and run `scripts/pre-tag.sh vX.Y.Z`. Do not push `main` yet.
5. Push a release branch and open a PR from it. The PR is the record of the release, and runs the free checks: `ci.yml` (lint, typecheck, tests, privacy guard, manifest validation), the version-bump check, skill-quality's contract tests and its self-test of the tag-time check, `cowork-replay.yml` when its paths changed, and DCO. Write the notes to a file first, so a failure stops before the PR opens:

```bash
git push origin HEAD:refs/heads/release/v0.2.0
python3 .github/scripts/changelog-notes.py v0.2.0 > /tmp/notes.md
gh pr create --base main --head release/v0.2.0 --title "release: v0.2.0" --body-file /tmp/notes.md
```

6. **Run the paid gate on the branch** and wait for `deck-review-e2e-smoke` and `mutation-corpus` to go green: `gh workflow run skill-quality.yml --ref release/v0.2.0`. On a red lane, read the failing assertion first; a re-run is paid, so re-run once only for what reads as LLM variance. On a real failure, `main` has not moved and no user has the build, so the fix needs no new bump: put it below the release commit (amend it in, or rebase it under), add it to this version's `CHANGELOG.md` section, re-run `scripts/pre-tag.sh v0.2.0`, then `git push --force-with-lease origin HEAD:refs/heads/release/v0.2.0` and dispatch again.
7. **Green: fast-forward `main`, then tag.** Green means the paid gate and every PR check (`gh pr checks release/v0.2.0`): the push to `main` goes around branch protection, so nothing else enforces them. Check that a green run tested `git rev-parse HEAD`, with the same check the tag will run (free): `GH_REPO=lool-ventures/founder-skills python3 .github/scripts/branch_gate_check.py --sha "$(git rev-parse HEAD)" --tag v0.2.0`. This push ships the release to users. Per GitHub's behaviour, the PR is marked merged when its head reaches `main`; do not use the PR's merge, squash or rebase buttons (a merge commit is unsigned, and a rebase changes the commits the gate tested).

```bash
git push origin HEAD:main
git tag v0.2.0
git push origin v0.2.0
```

8. Delete the release branch if it still exists. This repository is set to delete a merged PR's head branch (`delete_branch_on_merge`), and the PR is marked merged when its head reaches `main`, so it is usually gone already: `git ls-remote --exit-code origin refs/heads/release/v0.2.0 && git push origin :release/v0.2.0`.
9. The GitHub Release is created for you. The tag push does not run the paid gate again: its `verify-branch-gate` job checks the version and the Scoring changes section and finds the green release-branch run at the tagged commit, and the `publish-release` job in `.github/workflows/skill-quality.yml` runs once that job and the free contract tests (`contract-tests`, a third check that can withhold the Release) are green, taking the notes and title from that version's `CHANGELOG.md` section. Do not also run `gh release create` by hand — whichever runs second fails on "release already exists". To check the notes before tagging, without publishing anything: `gh workflow run skill-quality.yml -f verify_release_notes_for=vX.Y.Z`. If the verification is red because the branch run was still in progress, or on a transient error, re-run the tag run's failed jobs (`gh run rerun <run id> --failed`, free), which re-fires `publish-release` too. If no green branch run exists at the tagged commit (a hotfix), dispatch the paid gate on the tag (`gh workflow run skill-quality.yml --ref vX.Y.Z`; a dispatch never publishes), then re-run the tag run's failed jobs once it is green. A run can be re-run only within 30 days of its first attempt, and a re-run uses the workflow file at that run's own commit; past either, publish by hand. If the version or Scoring check fails for real, the version has already shipped on `main`: keep the tag, which marks what shipped, leave it without a Release, and release the next patch version. Do not delete the tag — the next release's Scoring changes check diffs from the previous version's tag and fails when it is missing — and never re-tag a version `main` has carried. If the job fails and you must publish by hand, use the command in the Release Process section of CLAUDE.md.

## Tag Naming

| Pattern | Example |
|---------|---------|
| `vX.Y.Z` | `v0.1.0` |
