## What

Brief description of what changed and why.

## Related issue

Closes #

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy` passes for affected skill directories
- [ ] `uv run pytest` passes
- [ ] If a skill body, agent, reference or command changed: `cowork-harness analyze-skill founder-skills/ --strict` and `cowork-harness lint-skill founder-skills/skills/*/ --strict` pass (see [Testing under Claude Cowork](../CONTRIBUTING.md#testing-under-claude-cowork))
- [ ] `uv run pytest -m cowork` passes, or skipped because the harness CLI isn't installed
- [ ] Commits are signed off (`git commit -s`) per DCO
- [ ] New skills include: SKILL.md, agent definition, tests, and reference files
