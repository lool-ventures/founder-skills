# Contributing to founder-skills

Thanks for your interest in contributing! Whether you're fixing a bug, improving an existing skill, or building a new one — we'd love your help.

Questions? Start a thread in [GitHub Discussions](https://github.com/lool-ventures/founder-skills/discussions).

## Getting Started

```bash
# Fork and clone
git clone https://github.com/<your-username>/founder-skills.git
cd founder-skills

# Install dependencies (requires Python 3.12+ and uv)
uv sync --extra dev
```

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
   uv run mypy founder-skills/tests/
   uv run pytest                                               # tests
   ```

3. **Open a PR** against `main`. The PR template will guide you through the checklist.

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

Use the existing skills (`market-sizing`, `deck-review`, `ic-sim`, `financial-model-review`, `competitive-positioning`) as templates. Skills and agents are auto-discovered from the directory structure — no registration needed. Key conventions:

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

## Code Style

[Ruff](https://docs.astral.sh/ruff/) handles linting and formatting. Key settings:

- 120-character line limit
- PEP 723 inline metadata for script dependencies
- JSON to stdout, warnings/errors to stderr

Don't worry about formatting — just run `uv run ruff format .` before committing.

## Reporting Bugs

Use the [bug report template](https://github.com/lool-ventures/founder-skills/issues/new?template=bug_report.md). Include which skill is affected and steps to reproduce.

## Suggesting Features

Use the [feature request template](https://github.com/lool-ventures/founder-skills/issues/new?template=feature_request.md) for new skill ideas or improvements. For open-ended discussion, use [GitHub Discussions](https://github.com/lool-ventures/founder-skills/discussions).
