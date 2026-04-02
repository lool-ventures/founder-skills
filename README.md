<p align="center">
  <img src="assets/github_header.png" alt="founder skills — AI coaching agents for startup founders" />
</p>

[![Claude Cowork](https://img.shields.io/badge/Claude_Cowork-D97757?logo=claude&logoColor=fff)](https://claude.com/plugins)
[![Claude Code](https://img.shields.io/badge/Claude_Code-555?logo=claude&logoColor=fff)](https://code.claude.com/docs/en/plugins)
[![CI](https://github.com/lool-ventures/founder-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/lool-ventures/founder-skills/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/lool-ventures/founder-skills)
[![Built with Skill Creator Plus](https://img.shields.io/badge/Built_with-Skill_Creator_Plus-4ecdc4?style=flat-square)](https://github.com/yaniv-golan/skill-creator-plus)

Skills for startup founders by [lool ventures](https://lool.vc).

A [Claude Cowork](https://claude.com/blog/cowork-plugins) plugin that gives founders five AI-powered coaching agents: market sizing, pitch deck review, financial model review, IC simulation, and competitive positioning. Each agent follows a structured, script-backed workflow to produce analysis that holds up under investor scrutiny.

## Skills

![Market Sizing Agent](assets/market_sizing.png)

### Market Sizing Agent

Builds credible TAM/SAM/SOM analysis — the kind that earns investor trust rather than raising eyebrows.

**What it does:**
- Calculates TAM/SAM/SOM using top-down, bottom-up, or both approaches
- Validates market claims against external sources (analyst reports, government data, industry stats)
- Stress-tests assumptions with sensitivity analysis and confidence-based range widening
- Runs a 22-item self-check against common market sizing pitfalls
- Assembles a final report with cross-artifact consistency validation

**What to provide:** A pitch deck, financial model, market data, or just describe the business (product, target customer, geography, pricing). The agent will research external sources to validate and build the estimate.

**What you get back:** A structured report with TAM/SAM/SOM figures (top-down and/or bottom-up), sensitivity ranges showing best/worst case, a scored self-check against common pitfalls, and coaching commentary on what will hold up in diligence.

**Example prompts:**
- "Here's the deck for Acme Corp -- can you validate their market sizing?"
- "We're looking at a fintech startup in the payments space targeting SMBs in Europe. What's the market look like?"
- "What happens to the market sizing if the customer count is 30% lower than estimated?"

> Full workflow details: [`founder-skills/skills/market-sizing/SKILL.md`](founder-skills/skills/market-sizing/SKILL.md)

![Deck Review Agent](assets/deck_review.png)

### Deck Review Agent

Reviews pitch decks against 2026 investor best practices, calibrated by stage (pre-seed, seed, Series A).

**What it does:**
- Scores 35 criteria across 7 categories (pass/fail/warn/not_applicable)
- Detects fundraising stage and applies stage-specific expectations
- Reviews each slide from the investor's perspective with specific, actionable feedback
- Grounds every recommendation in a named best-practice principle
- Assembles a scored report with overall deck readiness assessment

**What to provide:** A pitch deck in any format — PDF, PowerPoint, markdown, or text descriptions of your slides.

**What you get back:** A slide-by-slide review from the investor's perspective, a scored checklist (35 criteria across 7 categories), an overall readiness rating (strong/solid/needs work/major revision), and coaching on the highest-leverage changes to make before sending.

**Example prompts:**
- "Here's our seed deck -- can you review it?"
- "Is this deck ready to send to investors? We're raising a pre-seed round."
- "I have 10 slides: Slide 1 is our company intro with the tagline 'AI-powered compliance for fintechs'..."

> Full workflow details: [`founder-skills/skills/deck-review/SKILL.md`](founder-skills/skills/deck-review/SKILL.md)

![IC Simulation Agent](assets/ic_sim.png)

### IC Simulation Agent

Simulates a realistic VC Investment Committee discussion with three partner archetypes debating a startup's merits, concerns, and deal terms -- scored across 28 dimensions.

**What it does:**
- Simulates three distinct partner perspectives: The Visionary (markets/timing), The Operator (execution/GTM), The Analyst (unit economics/financials)
- Runs partner assessments independently via sub-agents for genuine diversity of perspective
- Scores 28 dimensions across 7 categories (team, market, product, business model, financials, risk, fund fit)
- Checks portfolio conflicts against the fund's existing investments
- Supports fund-specific mode with WebSearch-backed fund research
- Imports prior market-sizing and deck-review artifacts for grounded analysis

**What to provide:** A pitch deck, financial model, data room contents, or a verbal description of the business. Optionally, name a specific fund to simulate (e.g. "How would Sequoia evaluate us?"). Works best after running market sizing and/or deck review first — those artifacts are imported automatically.

**What you get back:** A simulated IC debate with three distinct partner voices, a conviction score across 28 dimensions, a consensus verdict (invest/more diligence/pass/hard pass), portfolio conflict analysis, and coaching on exactly what to prepare before a real IC meeting.

**Example prompts:**
- "Simulate an IC discussion for our startup"
- "How would Sequoia's partners discuss our company?"
- "I just did market sizing and a deck review -- now simulate the IC"

> Full workflow details: [`founder-skills/skills/ic-sim/SKILL.md`](founder-skills/skills/ic-sim/SKILL.md)

![Financial Model Review Agent](assets/financial_model_review.png)

### Financial Model Review Agent

Reviews startup financial models for investor readiness — validating structure, unit economics, runway, and metrics against stage-appropriate standards.

**What it does:**
- Scores 46 criteria across 7 categories with profile-based auto-gating by stage, geography, and sector
- Computes and benchmarks 11 unit economics metrics against stage-appropriate targets
- Stress-tests runway under base, slow-growth, and crisis scenarios with decision-point analysis
- Supports Excel (.xlsx), CSV, Google Sheets exports, pitch decks, and conversational input
- Assembles a final report with cross-artifact consistency validation

**What to provide:** A financial model in any format — Excel spreadsheet, CSV, Google Sheets export, financial slides from a deck, or just describe the numbers in conversation. The agent adapts its analysis depth to the format provided.

**What you get back:** A scored checklist (46 criteria across 7 categories), benchmarked unit economics with ratings, multi-scenario runway projections with cash-out dates and decision points, an overall readiness rating (strong/solid/needs work/major revision), and coaching on the highest-leverage improvements.

**Example prompts:**
- "Review my financial model" (with an Excel file attached)
- "Here are our projections from the deck -- can you validate the unit economics?"
- "We're burning $80K/mo with $1.2M in the bank, growing 15% MoM. How does our runway look?"

> Full workflow details: [`founder-skills/skills/financial-model-review/SKILL.md`](founder-skills/skills/financial-model-review/SKILL.md)

![Competitive Positioning Agent](assets/competitive_positioning.png)

### Competitive Positioning Agent

Maps a startup's competitive landscape, scores differentiation and moat strength, and stress-tests positioning claims — producing investor-ready competitive analysis.

**What it does:**
- Identifies 5-7 competitors across direct, adjacent, emerging, and do-nothing categories
- Scores positioning on 2D axes with rank-based differentiation and vanity axis detection
- Assesses 6 canonical moat dimensions per company with trajectory tracking
- Stress-tests differentiation claims against competitive evidence
- Runs a 25-item quality checklist with mode-based gating
- Optionally enriches the landscape via research sub-agent with web search

**What to provide:** A pitch deck, product description, or conversation about the business. The agent will identify competitors, select meaningful positioning axes, and build the analysis. Works best after running deck review — competition slide claims are cross-validated automatically.

**What you get back:** A scored competitive landscape with positioning maps, moat radar charts, differentiation scores with stress-test results, a quality checklist, and an interactive explorer for navigating the competitive set.

**Example prompts:**
- "Analyze our competitive positioning"
- "Who are our main competitors and how do we differentiate?"
- "I just did a deck review -- now analyze our competitive positioning"

> Full workflow details: [`founder-skills/skills/competitive-positioning/SKILL.md`](founder-skills/skills/competitive-positioning/SKILL.md)

## Getting Started

### Claude Cowork

1. Open **Customize** in the sidebar
2. Click **+** on the **Personal Plugins** list
3. Choose **Browse Plugins**
4. Switch to the **Personal** tab
5. Click the **+** button
6. Choose **Add marketplace from GitHub**
7. Enter `lool-ventures/founder-skills`
8. **Sync**, then **Install**

### Claude Code

```
claude plugin marketplace add lool-ventures/founder-skills
claude plugin install founder-skills@lool-founder-skills
```

Once installed, the agents activate automatically when you ask about market sizing, deck review, financial model review, IC simulation, or competitive positioning. No additional configuration required.

### Manus

Manus [adopted the Agent Skills standard](https://manus.im/blog/manus-skills) in January 2026 and can read `SKILL.md` files and execute bundled scripts. The founder-skills Python scripts are already portable (pure CLI, JSON in/out), but the workflow instructions in our SKILL.md files are currently Claude-native (sub-agent orchestration, plugin hooks, path resolution). We plan to add Manus-compatible skill wrappers once the platform's skill discovery and marketplace layer stabilizes.

### ChatGPT / Codex

OpenAI has [adopted the skills standard](https://simonwillison.net/2025/Dec/12/openai-skills/) originally introduced by Anthropic, and skills now work across [ChatGPT, Codex CLI, and the OpenAI API](https://developers.openai.com/codex/skills/). The ecosystem is converging quickly but the plugin/marketplace layer is still a moving target. Once the dust settles, we plan to add first-class support for ChatGPT and Codex as well.

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Quick start:

```bash
git clone https://github.com/lool-ventures/founder-skills.git
cd founder-skills
uv sync --extra dev   # install dependencies + dev tools
uv run pytest          # run tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow.

## Troubleshooting

**Plugin not updating after a new release?** As of Feb 2026 (Claude Desktop for Mac v1.1.3963), the plugin cache does not always refresh when a marketplace is updated. This is a [known platform issue](https://github.com/anthropics/claude-code/issues/17361). To force an update:

1. Enable auto-update: `/plugin` > Marketplaces > select `lool-founder-skills` > "Enable auto-update"
2. If that doesn't work, clear the cache and reinstall:
   ```
   rm -rf ~/.claude/plugins/cache/lool-founder-skills
   ```
   Then restart Claude Code/Cowork and reinstall the plugin.

**In Cowork**, if the plugin shows stale data after updating, you may need to fully remove and re-add the marketplace from the Plugins sidebar.

## Privacy

This plugin runs entirely inside your local Claude session. No data is collected, transmitted, or shared with lool ventures.

## Contributing

We welcome contributions — new skills, improvements to existing ones, and bug fixes. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started and [DESIGN.md](DESIGN.md) for the principles behind how skills are built.

## Contact

- **Bug reports and feature requests** — [GitHub Issues](https://github.com/lool-ventures/founder-skills/issues)
- **Questions and discussion** — [GitHub Discussions](https://github.com/lool-ventures/founder-skills/discussions)
- **Security vulnerabilities** — [Report privately](https://github.com/lool-ventures/founder-skills/security/advisories/new) (see [SECURITY.md](SECURITY.md))
- **About lool ventures** — [lool.vc](https://lool.vc)

## License

[Apache 2.0](LICENSE)

---

Built with [Skill Creator Plus](https://github.com/yaniv-golan/skill-creator-plus).
