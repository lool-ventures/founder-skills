# Contributing to founder-skills

Thanks for your interest in contributing! Whether you're fixing a bug, improving an existing skill, or building a new one — we'd love your help. By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

Questions? Start a thread in [GitHub Discussions](https://github.com/lool-ventures/founder-skills/discussions).

## Getting Started

```bash
# Fork and clone
git clone https://github.com/<your-username>/founder-skills.git
cd founder-skills

# Install dependencies (requires Python 3.10+ and uv)
uv sync --extra dev

# Activate the repo's git hooks (ruff format/lint + privacy-leak guard + DCO sign-off gate)
git config core.hooksPath scripts/hooks
```

> Run that `core.hooksPath` line once per clone. Without it the DCO gate below is not enforced
> locally, and you will only discover an unsigned commit when CI rejects your PR.

## Development Workflow

1. **Branch from `main`** using a descriptive prefix:
   - `feat/` — new functionality
   - `fix/` — bug fixes
   - `skill/` — new skill end-to-end

2. **Before pushing**, run all checks:
   ```bash
   uv run ruff check .                                        # lint
   uv run ruff format --check .                               # format check
   uv run mypy founder-skills/skills/market-sizing/scripts/     # typecheck per skill
   uv run mypy founder-skills/skills/deck-review/scripts/
   uv run mypy founder-skills/skills/ic-sim/scripts/
   uv run mypy founder-skills/skills/financial-model-review/scripts/
   uv run mypy founder-skills/skills/competitive-positioning/scripts/
   uv run mypy founder-skills/skills/cap-table/scripts/
   uv run mypy founder-skills/tests/
   uv run pytest                                               # tests (e2e auto-skips without auth)
   ```

   The deck-review e2e smoke (`tests/test_e2e_deck_review.py`) is gated by the `e2e` marker and skips unless one of these is set: `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, or local `claude /login` auth (macOS Keychain or `~/.claude/.credentials.json`). To explicitly skip it for a faster run:

   ```bash
   uv run pytest -m "not e2e and not mutation"
   ```

3. **If you touched a skill body, agent, reference, or command**, also run the two Cowork gates below — they run on every PR and are not covered by `ruff`/`mypy`/`pytest`.

4. **Open a PR** against `main`. The PR template will guide you through the checklist.

## Testing under Claude Cowork

Most of these skills are run by founders inside **Claude Cowork**, whose runtime differs from the Claude Code CLI in ways ordinary unit tests cannot see: an append-only `outputs/` mount, a host/VM split that changes which paths a sub-agent can reach, its own serving origin for generated HTML artifacts, and a plugin-root namespace that differs between the agent loop and in-VM bash. Bugs in that class are invisible to `pytest` and only appear in front of a founder.

Two CI jobs cover it, both token-free, both runnable locally. They use [`cowork-harness`](https://github.com/yaniv-golan/cowork-harness) (MIT), a Cowork-runtime emulator installed as a dev-time CLI — it is **not** part of the distributed plugin and is not a runtime dependency:

```bash
npm i -g cowork-harness@3.2.0           # Node 22+; EXACT, matching CI — see the pin note in .github/workflows/cowork-replay.yml

# 1. Static analysis over every skill body, agent, reference and command
cowork-harness analyze-skill founder-skills/ --strict
cowork-harness lint-skill founder-skills/skills/*/ --strict

# 2. Deterministic replay of recorded Cowork runs (no model, no Docker, no token)
uv run pytest -m cowork
```

The `cowork` lane **auto-skips** when the CLI is absent, so you are not required to install it — but if you changed a skill's prose, its dispatch templates, or a script that writes founder-facing files, run the static gates before pushing. They catch, for example, an HTML artifact whose Submit button silently fails under Cowork's origin, and a script path that resolves in the CLI but not in the VM.

**Recording new cassettes is local and paid, and is not expected of contributors.** Replay uses cassettes committed to `cowork-tests/cassettes/`; re-recording needs Docker, staged Cowork agent binaries and a model token. See [`cowork-tests/README.md`](cowork-tests/README.md) if you need to understand or refresh them — otherwise a maintainer will handle it.

**Privacy guard.** The pre-commit hook you enabled above also scans for confidential data. It checks file *paths* as well as content, so naming a fixture after a real company will block the commit even if the file's contents are synthetic. Real founder documents belong outside the repo entirely; synthetic fixtures go under `tests/fixtures/`.

## DCO Sign-Off

All commits must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/) (DCO). This certifies that you have the right to submit the code under the project's open-source license.

Sign off every commit:

```bash
git commit -s -m "feat: add new skill"
```

This adds a `Signed-off-by: Your Name <your@email.com>` line. If you forget, amend:

```bash
git commit --amend -s
```

The `commit-msg` hook enforces this locally — it rejects a commit with no sign-off, or one whose
sign-off doesn't match the commit author (the same check the CI-side DCO app performs). It validates
rather than auto-adding the trailer: a sign-off certifies that *you* have the right to submit the work,
so a hook that added it silently would be certifying on your behalf. `git commit --no-verify` bypasses
it if you ever genuinely need to.

`-s` composes with every other flag, including a heredoc message (`git commit -s -F - <<'EOF' … EOF`) —
the trailer is appended to the existing trailer block.

## Adding a New Skill

Read [DESIGN.md](DESIGN.md) first — it explains the artifact pipeline, script-backed workflow, and coaching philosophy that every skill follows.

A complete skill consists of:

```
founder-skills/
  skills/<name>/
    SKILL.md              # Skill definition (workflow, phases, outputs)
    scripts/              # Python scripts (PEP 723 inline metadata)
      checklist.py        # Validation/scoring script
      compose_report.py   # Report assembly script
      ...
    references/           # Reference materials, rubrics, examples
  agents/<name>.md        # Agent definition (frontmatter + system prompt)
  tests/test_<name>.py    # Regression tests
```

Use the existing skills (`market-sizing`, `deck-review`, `ic-sim`, `financial-model-review`, `competitive-positioning`, `cap-table`) as templates. Skills and agents are auto-discovered from the directory structure — no registration needed. Key conventions:

- **Scripts** output JSON to stdout, warnings/errors to stderr
- **Scripts** support `--pretty` for human-readable output and `-o <file>` to write to file
- **Scripts** use PEP 723 inline metadata for dependencies
- **Agent definitions** go in `founder-skills/agents/<name>.md`

## Improving Existing Skills

These changes are generally welcome without prior discussion:

- Fixing bugs in scripts
- Improving reference materials and rubrics
- Adding test cases
- Clarifying agent prompts

For larger changes — restructuring a workflow, changing scoring methodology, altering output formats — please open an issue first to discuss the approach.

## Pull Request Process

- **One logical change per PR.** Don't bundle unrelated fixes.
- **Link to an issue** when one exists (`Closes #123`).
- **All CI checks must pass** — lint, typecheck, and tests.
- **DCO sign-off required** on every commit.
- **New skills** must include SKILL.md, agent definition, tests, and reference files.

## Releasing

Release process, versioning rules, and the tag-triggered e2e gate are documented in [VERSIONING.md](VERSIONING.md). Only maintainers cut releases — contributors don't need this unless a PR requires a version bump.

## Code Style

[Ruff](https://docs.astral.sh/ruff/) handles linting and formatting. Key settings:

- 120-character line limit
- PEP 723 inline metadata for script dependencies
- JSON to stdout, warnings/errors to stderr

Don't worry about formatting — just run `uv run ruff format .` before committing.

## Reporting Bugs

**Security vulnerabilities:** do not file a public issue — see [SECURITY.md](SECURITY.md) for private reporting instructions.

For everything else, use the [bug report template](https://github.com/lool-ventures/founder-skills/issues/new?template=bug_report.md). Include which skill is affected and steps to reproduce.

## Suggesting Features

Use the [feature request template](https://github.com/lool-ventures/founder-skills/issues/new?template=feature_request.md) for new skill ideas or improvements. For open-ended discussion, use [GitHub Discussions](https://github.com/lool-ventures/founder-skills/discussions).

## Feedback

Using the plugin and have feedback? Run `/founder-skills:feedback` in your session — it drafts a message (bug, idea, help, or a win to share) and gives you a link to submit yourself; nothing is sent automatically. Prefer to browse? Post in [Discussions](https://github.com/lool-ventures/founder-skills/discussions). For anything private, email [founder-skills@lool.vc](mailto:founder-skills@lool.vc).
