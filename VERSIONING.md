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
- Skill content rewrites or improvements
- Reference material updates
- Documentation improvements

### No Version Bump Needed

- Metadata-only changes (description, author in plugin.json)
- CI workflow changes
- Test additions or fixes

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

- Every release must merge to `main`. No long-lived `release/*` branches as a substitute.
- Tagging is a courtesy for `git log` archeology; the `version` field on `main` is what users actually see.

### 2. Every content change on `main` must bump the version

`claude plugin update` keys off `plugin.json#version`. If two commits land on `main` under the same version, the second is invisible to anyone who installed at the first — `update` becomes a permanent no-op for them.

- Treat `plugin.json#version` as immutable per `main` commit-state.
- If you've already pushed `0.4.0` and need to add a fix: bump to `0.4.1`. Don't sneak fixes under the existing version.
- The version bump should be the **last** commit of a release branch (or part of the merge commit) — never the first. If you bump early and then add more commits, bump again before merging.

The "No Version Bump Needed" cases above (test-only changes, CI workflow changes, etc.) are exceptions enforced by the path filter in the CI check.

## How to Release

Releases are manual. On version bump:

1. Update `version` in `founder-skills/.claude-plugin/plugin.json`
2. Update `version` in `pyproject.toml` to match
3. Update `CHANGELOG.md` — move items from `[Unreleased]` to the new version, add `### Highlights`
4. Commit, push to `main` (this should be the **last** commit of the release; if more fixes follow, bump the patch version again)
5. Tag and create a GitHub Release:

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
gh release create v0.2.0 --title "v0.2.0" --notes-file <(sed -n '/^## \[0.2.0\]/,/^## \[/p' CHANGELOG.md | head -n -1)
```

The `gh release create` command extracts the changelog entry for the release notes.

## Tag Naming

| Pattern | Example |
|---------|---------|
| `vX.Y.Z` | `v0.1.0` |
