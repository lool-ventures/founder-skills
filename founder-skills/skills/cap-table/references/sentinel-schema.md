# Fast-Assess Sentinel Contract

This document defines the contract between cap-table's fast-assess mode and downstream cross-skill consumers (`financial-model-review`, `ic-sim`, `fundraise-readiness`, future `cross-document-consistency`).

## What the sentinel marks

`fast_assess_only.json` is written by `scripts/quick_assess.py` to indicate that the cap-table skill ran in fast-assess mode — a 1-page directional founder-facing review that does NOT produce the canonical JSON artifact set. Without this sentinel, a future consumer that finds a missing `report.json` cannot distinguish three states:

| State | Signal | Consumer action |
|---|---|---|
| Cap-table never ran | No `report.json`, no `fast_assess_only.json`, no `report_fast_assess.md` | Prompt founder to run cap-table |
| Cap-table ran in full pipeline | `report.json` exists with full schema; structured artifact set present | Consume normally |
| Cap-table ran in fast-assess mode | `fast_assess_only.json` exists; `report_fast_assess.md` exists; `report.json` absent | Either use sentinel's `headline_data` directly, or prompt founder for a full re-run |

## Directory convention

Fast-assess writes to `cap-table-{slug}-fastassess/` (single-dash suffix). The full pipeline writes to `cap-table-{slug}/`. Both directories can coexist for the same slug; consumers pick the directory matching what they need:

- A consumer needing structured artifacts (counsel packet, scenarios, rule audit) looks at `cap-table-{slug}/` first
- A consumer that can degrade to headline numbers (founder %, PPS) can fall back to `cap-table-{slug}-fastassess/fast_assess_only.json` if the full review is absent

**Precedence:** full pipeline beats fast-assess. Fast-assess is by design directional; full is by design authoritative.

**Naming pin:** `-fastassess` is a single-dash suffix, NOT `--fastassess` (double-dash). The single dash means `find_artifact.py`'s rerun-separator parser (`{slug}--{run_id}`) treats `{slug}-fastassess` as a complete slug — distinct from the full-pipeline slug — so a `find_artifact --skill cap-table --artifact cap_state.json --slug {slug}` lookup naturally won't pick up the fast-assess dir. This is a load-bearing property: don't change the naming without updating the helper.

## Sentinel schema

Authoritative: `references/schemas/fast_assess_only.schema.json` (Draft 2020-12).

Key fields:

- `mode: "fast_assess"` — discriminator
- `run_id` — unique per invocation
- `company_name` / `company_slug` — engagement identity
- `created_at` — UTC ISO-8601 timestamp
- `rule_pack_version` — `cap-table-rules.json` version the math producers cited
- `inputs_fingerprint` — `{sha256, components}` over founder-supplied inputs (prompt + attached docs). Lets consumers detect "inputs changed since fast-assess ran" and decide whether to trust the cached sentinel.
- `fast_assess_report_path` — absolute path to the markdown deliverable
- `produces_canonical_artifacts: false` — explicit marker; replaces a hardcoded missing-artifacts list to avoid drift when the canonical artifact set evolves
- `headline_data` — denormalized {`scenarios_summarized`, `founder_impact`, `branch_summary`, `drivers`} (mirrors `coaching_payload` field names so consumers can reuse parsers)
- `rerun_hint` — human-readable instruction for getting full artifacts

## Consumer-detection contract (future work)

`find_artifact.py` is NOT currently sentinel-aware. The two-directory naming scheme cooperates with it correctly for canonical-artifact lookups — a consumer asking for `cap_state.json` will naturally not find one in the fast-assess directory. But a future consumer wishing to detect fast-assess explicitly should:

1. Use `find_artifact.py --skill cap-table --artifact fast_assess_only.json --slug {slug}-fastassess`
2. If exit code 0, parse the JSON, branch on whether `headline_data` is sufficient for the consumer's needs
3. Otherwise prompt the founder for a full cap-table review

When the first downstream consumer ships, that's the moment to add a `--mode-aware` flag to `find_artifact.py` if convenience warrants it.

## Cross-mode divergence detection (future work)

When both `cap-table-{slug}/report.json` AND `cap-table-{slug}-fastassess/fast_assess_only.json` exist for the same slug, `compose_report.py` can compare `inputs_fingerprint` and the headline founder ownership. If the fast-assess answer materially diverged from the full result (e.g., founder ownership delta > 2pp), emit a coaching warning. Free product win — debugging gold for users AND skill authors. Tracked as a Phase-2 follow-up.

## Cleanup contract

**Never auto-delete cross-mode.** Both directories can coexist as the founder iterates. The fast-assess sentinel becomes stale-but-informative when the full pipeline runs against the same inputs; that's fine. If the founder explicitly asks to "clear cap-table state" the dispatching agent can `rm -rf cap-table-{slug}*` — but never silently.
