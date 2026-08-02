# Cap-table reliability bench

An **on-demand** reliability bench for the cap-table skill. It measures whether a
given model tier answers cap-table questions correctly **without** the skill (the
"alone" baseline) versus **with** the skill engaged, and whether the skill's
trigger fires on trap-topic questions.

This is a **model-acceptance tool, not a CI gate.** Run it by hand when adopting
or recommending a new model tier — it is not part of the per-PR test suite.

## What it measures

The bench data (`reliability-bench.json`) has two parts:

- **`trigger_cases`** — should the skill *auto-fire* on a trap-topic question?
  Trap topics with numbers, dates, or eligibility at stake should trigger; pure
  glossary questions should not. (Triggering is verified in the Cowork runtime;
  the runner below scores answer quality, not triggering.)
- **`correctness_cases`** (facts) and **`computation_cases`** (math, with
  canonical numbers) — is the answer correct, and does it respect the reliance
  boundary? Canonical numbers are the cap-table skill's deterministic-solver
  outputs. Correctness cases also check that the model does **not** state a
  definitive eligibility/qualification conclusion without deferring to counsel
  (the reliance boundary); stating the underlying date or clock fact is fine.

Answers are graded by an LLM judge against each case's `canonical` answer and
`judge_rubric`, tolerant of phrasing, rounding, and date format.

## How to run

List the cases without running anything:

```bash
uv run python run_reliability_bench.py --list
```

Run the "alone" baseline for a model tier and write results:

```bash
uv run python run_reliability_bench.py \
  --condition alone --cases all --model <tier> --judge-model sonnet --out results.json
```

Run the A/B (alone vs skill-engaged) in one pass:

```bash
uv run python run_reliability_bench.py --condition both --cases all --model <tier> --out results.json
```

Estimate a pass rate across repeated runs (useful for flaky/borderline cases):

```bash
uv run python run_reliability_bench.py --condition alone --repeats 5 --model <tier>
```

### Flags

- `--condition {alone,skill,both}` — `alone` runs the model with no skill
  (`claude --disable-slash-commands`); `skill` runs it with the founder-skills
  plugin engaged; `both` runs the A/B. Default `alone`.
- `--cases {facts,computation,all}` — which case group to run. Default `all`.
- `--ids <id> [<id> ...]` — run only specific case ids.
- `--repeats N` — runs per case per condition, for rate estimation. Default `1`.
- `--model <tier>` — model for the *answer* (alone/skill). Default: CLI default.
- `--judge-model <tier>` — model for the LLM judge. Default `sonnet`.
- `--scorer {judge,string}` — LLM judge (default) or deterministic string check.
- `--timeout <seconds>` — per-call timeout. Default `900`.
- `--out <file>` — write the full per-run results JSON.
- `--list` — list the selected cases and exit.

## When to run it

Run the bench as a **model-acceptance step** when adopting or recommending a new
model tier, and record the per-tier correctness (and reliance-boundary) results.
**Sonnet 4.6 is the support floor** — the minimum tier real users run — so a new
tier should at least match it before being recommended.

---

## Pipeline-bypass telemetry (`bypass_telemetry.py`)

A separate, read-only tool that measures a different failure mode: whether the
agent **actually ran the deterministic pipeline** in a Cowork run, or **bypassed
it** — hand-rolling an analysis and producing no canonical artifacts (a
process/provenance loss, not necessarily a correctness loss). Rationale: measure
the bypass rate per tier before deciding whether to harden the skill against it,
so the decision rests on data rather than a single observation (observed once on
Opus 4.8 — n=1 — vs zero on the Sonnet 4.6 floor in early runs).

Unlike the LLM-judge bench above, this does not call a model — it inspects kept
cowork-harness run dirs (`--keep`/`--run-dir`) and classifies each:

- `pipeline_ran` — the canonical solver/compose artifacts are present.
- `partial` — a cap-table artifacts dir exists but core artifacts are missing.
- `bypassed` — no canonical artifacts, but the run produced something else
  (ad-hoc files in `outputs/`) → a genuine bypass.
- `no_output` / `error` — nothing produced / not inspectable (inconclusive;
  excluded from the rate).

`bypass_rate = bypassed / (pipeline_ran + partial + bypassed)`, grouped by the
model tier read from each run's `events.jsonl`.

```bash
# classify one or more kept run dirs and print the per-tier bypass rate
uv run python bypass_telemetry.py /tmp/ct-run-1 /tmp/ct-run-2 --pretty
# machine-readable
uv run python bypass_telemetry.py /tmp/ct-* -o bypass_telemetry.json
```

To build a real rate, run the harness ≥10× per tier with `--keep --run-dir`
(e.g. the S-6 triple or the flip), then point this tool at the run dirs. Tests:
`uv run pytest evals/cap-table/test_bypass_telemetry.py` (synthetic fixtures;
not in the per-PR suite).

---

## Harness-native reliability (cowork-harness 0.24.0)

The LLM-judge bench above measures **answer quality** (free-text, no skill runtime).
A complementary measurement — does the cap-table **pipeline** land correct canonical
artifacts reliably, across model tiers — is delegated to the cowork-harness's own
variance machinery, which is stronger than a hand-rolled repeat loop (it owns the
flakiness contract, per-assertion attribution, and cost accounting).

### Per-tier flakiness (`--repeat` via `--use-harness-repeat`)

Runs a cowork-harness **scenario** (its `assert:` block) N times and consumes the
harness's variance rollup — pass rate, per-assertion pass/fail attribution,
verdict-signal histogram, cost totals — instead of the bench counting passes:

```bash
# from evals/cap-table/ — needs the live lane (Docker + staged agent + token)
uv run python run_reliability_bench.py \
  --use-harness-repeat ../../cowork-tests/scenarios/cap-table-safe-full.yaml \
  --repeats 10 --min-pass-rate 0.9 --max-budget-usd 25 --out harness-repeat.json
```

`--stop-on-diverge` stops the loop the moment both a pass and a fail are seen (that
batch always fails — divergence *is* the flakiness signal). `--max-budget-usd` caps
cumulative spend (a clean early stop is a warning, not a failure). Kept run dirs still
feed `bypass_telemetry.py` for the pipeline-ran-vs-bypassed rate.

### Model-tier acceptance matrix (`run --matrix`)

The one-command model-acceptance gate: run one representative cap-table scenario across
the support floor + candidate tiers, each tier judged against a pass-rate threshold.
`--matrix` composes with `--repeat` (each tier runs as its own repeat batch). The tier
list lives in [`matrices/model-tiers.yaml`](matrices/model-tiers.yaml):

```bash
cowork-harness run ../../cowork-tests/scenarios/cap-table-safe-full.yaml \
  --matrix matrices/model-tiers.yaml \
  --repeat 5 --min-pass-rate 0.8 --max-cells 8 --concurrency 2 \
  --allow-truncated-matrix --allow-budget-stop \
  --output-format json > model-tiers-acceptance.json
```

`--allow-truncated-matrix` / `--allow-budget-stop` are required on cowork-harness 0.27.0+:
an incomplete batch (a `--max-cells`-capped matrix, or a `--repeat` cut short by a budget /
divergence stop) is a hard verdict fail by default. This is an acceptance gate that
deliberately caps cells and stops early, so it opts into the incomplete batch.

The `models:` axis overrides the scenario session's pinned model per cell; the JSON
envelope carries an additive `matrixRepeat.cells[]` (one full rollup per tier). Any cell
below `--min-pass-rate` fails the matrix — it is a compatibility gate, not a survey.
**Sonnet 4.6 is the support floor**; a candidate tier must at least match it. Record the
per-tier results in the model-tier acceptance note (see the repo `CLAUDE.md` release
process) alongside the `bypass_telemetry.py` rate.

### Reliability trend across re-records (`stats`)

Every `run`/`record` appends one line to `<runsRoot>/index.jsonl` (the harness-default
`~/.cowork-harness/runs`, which `rerecord.sh` now uses). `cowork-harness stats` reads it
back as the standing answer to "how has cap-table reliability trended across re-records":

```bash
cowork-harness stats cap-table-safe-full --last 20 --metric pass-rate   # per-scenario window
cowork-harness stats --since 2026-07-01                                  # date-windowed
cowork-harness stats --reindex                                          # backfill pre-index runs once
```

`--baseline` / `--branch` / `--since` filter; `--last <n>` windows per scenario. Requires
the persistent runs root (not a `/tmp` root, which discards cross-run history).
