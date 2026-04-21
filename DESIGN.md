# Design Principles

This document explains the *why* behind how founder-skills are built. [CONTRIBUTING.md](CONTRIBUTING.md) covers the mechanics of contributing; this covers the philosophy.

## Founder-First Coaching

Every skill is a coaching session, not an evaluation. The goal is to prepare founders for investor scrutiny — not to judge them.

- Celebrate what's strong before flagging what needs work
- Frame every concern as actionable: not "this will worry investors" but "here's what to prepare"
- Distinguish between a weak business and weak framing — founders often have the right answer but present it poorly
- Your loyalty is to the founder, not to a hypothetical investor

## Script-Backed Workflows

Every computation runs through Python scripts, never through LLM arithmetic.

**Why:** LLMs are unreliable at math. A market sizing that's off by 10x because the model fumbled a multiplication destroys credibility. Scripts produce deterministic, auditable, reproducible results.

**In practice:**
- Scoring, sensitivity analysis, checklist validation, and report composition all run through scripts
- Agents are explicitly instructed: "NEVER do arithmetic in your head"
- Scripts output JSON to stdout, warnings/errors to stderr
- All scripts support `--pretty` for human-readable output and `-o <file>` for file output

## The Artifact Pipeline

Every skill follows a phased workflow that produces intermediate JSON artifacts, which compose into a final report. This is the core architectural pattern.

```
Phase 1 → artifact_1.json
Phase 2 → artifact_2.json (may read artifact_1)
  ...
Phase N → compose_report.py reads ALL artifacts → final report
```

**Why artifacts instead of one-shot generation:**
- Each phase can be validated independently
- Cross-artifact consistency checks catch contradictions (e.g., methodology says "top-down" but sizing results only contain bottom-up)
- Artifacts are reusable — IC simulation imports market-sizing and deck-review artifacts
- Debugging is straightforward: inspect the artifact where things went wrong

**Artifact conventions:**
- Stored in `$ARTIFACTS_ROOT/{skill}-{company-slug}/` where `ARTIFACTS_ROOT` defaults to `$(pwd)/artifacts` (or the first mounted workspace in Cowork)
- Written as structured JSON via heredoc (`cat <<'EOF' > file.json`)
- Skipped steps produce a stub: `{"skipped": true, "reason": "..."}`
- Agents must deposit each artifact before proceeding — no skipping ahead

## Cross-Artifact Validation

The `compose_report.py` script in each skill doesn't just assemble — it validates. Each runs multiple independent checks (7–14 depending on the skill):

- **Missing artifacts** — required files must exist
- **Consistency checks** — methodology must match results, checklist must have the right item count, assumptions must appear in both validation and sensitivity analysis
- **Quality checks** — unsourced assumptions, narrow sensitivity ranges, refuted claims without explanation

Checks are classified by severity:
- **High** — integrity violations that block the report (missing artifacts, overclaimed validation, checklist failures)
- **Medium** — quality concerns included as warnings (unsourced assumptions, discrepancies)

High-severity issues trigger a refinement loop: fix the underlying artifact, re-run compose, repeat. Medium-severity warnings can be acknowledged by the agent via an `accepted_warnings` array in the methodology artifact.

## Evidence Grounding

Skills require external evidence, not just reasoning from the prompt.

- **Market sizing** mandates WebSearch validation against industry reports, government data, and analyst estimates. Every assumption is categorized by confidence: `sourced` (2+ independent sources), `partially_supported` (1 source), `derived` (calculated from sourced data), or `agent_estimate` (judgment call)
- **Deck review** requires every critique to cite a specific best-practice principle — no vague feedback like "the team slide could be stronger"
- **IC simulation** grounds every partner position in specific evidence from the startup's materials, and uses WebSearch to research real fund thesis, portfolio, and partners in fund-specific mode

Source quality hierarchy (market sizing): government/regulatory > analyst reports > industry associations > academic research > business press > company blogs.

## Stress-Test Your Own Assumptions

Good analysis acknowledges uncertainty. Skills are designed to pressure-test themselves.

- **Sensitivity analysis** varies each parameter independently and ranks by impact on the bottom line (SOM swing)
- **Confidence-based range widening** automatically expands ranges for less-certain inputs: `sourced` assumptions get no minimum range, `derived` assumptions get ±30%, `agent_estimate` gets ±50%
- **Self-check checklists** score the analysis against known pitfalls (22 items for market sizing, 35 for deck review, 46 for financial model review, 28 for IC simulation, 25 for competitive positioning)

If a checklist item fails, the report flags it. The agent doesn't hide weaknesses — it explains them and coaches on how to address them.

## Stage Awareness

Advice is calibrated to fundraising stage where the skill warrants it. A pre-seed deck is judged differently than a Series A deck.

- **Deck review** detects stage from signals (revenue, team size, raise amount) and applies stage-specific criteria and benchmarks
- **IC simulation** uses stage context from the startup profile to guide partner assessments; stage-calibrated thresholds are documented in the evaluation criteria reference file and applied by agents during assessment

## Sub-Agent Architecture

Skills offload context-heavy and parallelizable work to Task sub-agents. This serves two purposes:

**Context offloading:** Extraction sub-agents read source files (pitch decks, spreadsheets, market data), load reference files, and return only a structured summary — keeping raw document content and search results out of the main agent's context. A pitch deck can be 15-20 slides of raw content; a web research phase can produce 15-30 KB of search results. The main agent needs only the distilled output to direct subsequent steps.

- Market sizing: extraction sub-agent reads materials and writes `inputs.json` + `methodology.json`, returns a company brief and data availability summary
- Market sizing: research sub-agents run WebSearch and return structured assumptions arrays, not raw search results
- Financial model review: extraction sub-agent parses Excel/CSV via `extract_model.py` and constructs `inputs.json`, returns data sufficiency verdict

**Parallel independent work:** When steps have no data dependency, sub-agents run them concurrently in a single message. This both saves time and — for assessment tasks — prevents convergence bias where sequential generation causes later outputs to echo earlier ones.

- Market sizing: sensitivity + checklist run in parallel after the reality check passes
- Financial model review: checklist scoring + metrics/runway run in parallel
- IC simulation: three partner assessments (Visionary, Operator, Analyst) run as parallel sub-agents, producing genuinely independent perspectives that create real debate

**Return contracts:** Every sub-agent invocation specifies exactly what to return (file paths, key metrics, summary stats) with an explicit "do not echo the full artifact/document back" constraint. This is what makes context offloading effective — without the constraint, sub-agents would dump everything back into the main context.

**No worktree isolation:** Sub-agents must write artifacts to the main `$ANALYSIS_DIR`. Using `isolation: "worktree"` would write files into a temporary copy that the main agent can't see.

## Graceful Degradation

Skills work with whatever's available:

- **Input flexibility** — accept PDFs, slides, markdown, or plain text descriptions
- **Sub-agent fallback** — if the Task tool is unavailable, fall back to sequential generation in the main context
- **Prior artifact import** — IC simulation imports market-sizing and deck-review artifacts when available, but works without them
- **Path resolution** — try `CLAUDE_PLUGIN_ROOT` first, fall back to Glob-based discovery

## Adding a New Skill

When building a new skill, follow these principles:

1. **Design the artifact pipeline first.** What phases does the analysis need? What does each artifact contain? What cross-artifact checks matter?
2. **Scripts for computation, agents for judgment.** If it can be wrong because of arithmetic, put it in a script. If it requires nuance, context, or creativity, let the agent handle it.
3. **Define your checklist.** Every skill should have a self-check that catches common mistakes. The checklist is both a quality gate and a teaching tool.
4. **Ground claims in evidence.** Specify what external validation looks like for your domain. What sources matter? What confidence categories apply?
5. **Coach, don't judge.** Frame every output as preparation and improvement, not as a score to optimize.
