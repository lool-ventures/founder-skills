---
paths:
  - "founder-skills/skills/*/SKILL.md"
  - "founder-skills/agents/**"
  - "founder-skills/.claude-plugin/plugin.json"
  - "founder-skills/scripts/session-setup.sh"
  - "founder-skills/skills/*/scripts/compose_report.py"
  - "founder-skills/tests/test_e2e_*.py"
  - "founder-skills/tests/_e2e_harness.py"
  - "founder-skills/tests/cowork_async_subagent_filter.py"
  - "founder-skills/tests/compose_invocations.py"
  - "pyproject.toml"
  - "founder-skills/tests/test_cowork_async_subagent_filter.py"
  - "founder-skills/tests/test_lane_connector_isolation.py"
  - "founder-skills/tests/test_lane_contradiction_checks.py"
  - "founder-skills/tests/test_lane_sdk_stream.py"
  - "founder-skills/tests/test_lane_tools.py"
---
## When to manually dispatch e2e on a PR

Per-PR e2e is off by default. Manually dispatch (`gh workflow run skill-quality.yml --ref <pr-branch>`) when the PR touches architectural surface that contract tests don't fully cover:

- `founder-skills/skills/*/SKILL.md` (frontmatter or trigger phrases)
- `founder-skills/agents/*.md` (tool declarations, model, frontmatter)
- `founder-skills/.claude-plugin/plugin.json`
- `founder-skills/scripts/session-setup.sh` (mutates `CLAUDE_ENV_FILE`)
- `founder-skills/skills/*/scripts/compose_report.py`, **but only when the change reaches the payload builder** — `_emit_coaching_payload` in five skills, `build_coaching_payload` in cap-table (which also runs `_assert_coaching_payload_privacy_clean` over the result; grep for the name rather than assuming, this differs per skill). That function IS the `coaching_payload` contract. `test_compose_invariants.py` checks its *shape* against synthetic fixtures; only e2e exercises the thing that shape exists for, namely a sub-agent reading the payload and writing usable commentary from it. **The check:** does the diff touch the payload builder or anything in its call graph? If yes, dispatch. If the change only alters how a section renders into `report.md`/`report.json`, the contract tests are sufficient and e2e buys nothing.
  This bullet used to name the whole file, which over-triggered: a rendering-only fix would read as needing a $10 paid run it cannot possibly exercise. Two such commits landed under the narrowed reading — a `-1` rank sentinel reaching founders, and a moat-radar caption — both rendering-only, both covered by contract tests, neither dispatched. **Watch the shared-helper case**: `report.md` prose and the payload can call the same helper, and a change there does reach the contract even though the diff looks like rendering. That is exactly why the trigger is the call graph and not the file.
- any of the four `founder-skills/tests/test_e2e_*.py` lanes (derive with `ls`), or `tests/_e2e_harness.py` (the SDK invocation itself)
- `founder-skills/tests/cowork_async_subagent_filter.py` and `compose_invocations.py` (CI-helper meta — if these break, contract tests pass vacuously)
- `pyproject.toml` `dependencies` list or `[project.optional-dependencies]` block (any runtime dep can shift SDK behavior)

Other PRs (skill-internal scripts, fixtures, docs, contract tests): contract tests are sufficient — skip the $10.

