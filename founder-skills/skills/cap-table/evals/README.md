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
