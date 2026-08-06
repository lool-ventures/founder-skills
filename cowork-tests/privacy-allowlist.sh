# Single source of truth for the verify-cassettes privacy allowlist.
# Sourced by cowork-tests/rerecord.sh AND .github/workflows/cowork-replay.yml (and reused for the
# email canary). Defining the array once means the gate and the canary can never drift apart.
#
# Class-scoped (cowork-harness 0.5.0): an allow cannot bleed across PII classes.
#   currency  via --allow         — synthetic $ figures the skills emit.
#   domain    via --allow-domain  — research/coaching skills cite 150+ PUBLIC third-party domains
#                                   (non-PII); an enumerated list would be unmaintainable. Applies ONLY
#                                   to domain findings — structurally cannot clear an email.
#   email     via --allow-email   — ONLY synthetic domains (acmecorp.com fictional; example.com is
#                                   RFC-2606 reserved). ANY other email FAILS = the live PII tripwire,
#                                   locked by canary/email-canary.cassette.json.
#
# NOTE (0.25.0+): the connected-folder scenario's read-only (mode:r) input — the synthetic Carta XLSX —
# is captured BODY-LESS (path + sha256; 0.26.0 tags it truncationReason:"readonly") instead of as a full
# binary body, so it no longer trips the scanner's `binary` class and needs no `--allow`. (Before 0.25.0
# it did; the entry was removed when cap-table-carta-folder was re-recorded on the 0.25.0 pin.) The
# other class flags: no
# `--allow-path`/`--allow-machine-inventory` — a local path or machine detail in a cassette is always a
# leak (record-time redaction via .cowork-redact.json is the source-side counterpart).
#
# NOTE (1.19.0+): host-inventory — NO allow entry, deliberately.
# The class flags a recording machine's own MCP servers / account / agents / skills frozen into a
# cassette by a host-inheriting tier — which is our tier, since `fidelity: cowork` resolves to hostloop.
# At 1.18.0 it reported 240 findings on this corpus, ALL of them `agents[] — founder-skills:<skill>`,
# i.e. the six agents of the plugin UNDER TEST, and we suppressed them with
# `--allow-host-inventory 'founder-skills:.*'`.
#
# 1.19.0 REMOVED THE NEED FOR THAT ENTRY. An agent or skill namespaced `<plugin>:<name>` whose plugin
# the same recording declares in `plugins[]` is now exempt automatically. The exemption is derived from
# the cassette, so it applies to recordings made before the release — no re-record. Measured on this
# corpus: 240 -> 0, and `verify-cassettes` output is BYTE-IDENTICAL with and without the old entry.
# The entry was deleted because a suppression that suppresses nothing is a standing invitation to
# misread the gate; a bare `.*` would have turned the backstop into decoration either way.
#
# THIS MAKES THE CLI FLOOR LOAD-BEARING. On a 1.18.0 CLI the exemption does not exist and this array
# reds on 240 non-findings (measured: `npx cowork-harness@1.18.0` -> exactly 240, exit 1). Every
# consumer of this file must floor at >=1.19.0. Unlike a missing flag, an older CLI here does not
# degrade quietly — it fails loudly and WRONGLY.
#
# STANDING RISK, and the reason this note is long. With no allow, the gate's green now depends on
# `plugins[]` carrying `founder-skills` in EVERY future recording. Measured failure mode: strip
# `plugins[]` from a single cassette and it alone yields 18 findings; corpus-wide the equivalent is
# 240+. Nothing tests that invariant. So if a future re-record ever reds this gate en masse with
# `agents[]` / `skills[]` findings on our OWN namespace, the cause is a missing `plugins[]`
# declaration, not a leak — do not "fix" it by re-adding an allow.
#
# NEW AXIS (1.19.0): `skills[]` is now read the same way `agents[]` is, with the same two exemptions
# (the agent's own built-ins, currently just `deep-research`; and a `<plugin>:<skill>` whose plugin the
# recording declares). Measured: all 21 cassettes carry a populated `skills[]` — 7 names, 0 flagged.
# That zero is STRUCTURAL, not earned: the axis is aimed at the `protocol` tier, where the harness
# keeps the operator's real CLAUDE_CONFIG_DIR. We record at hostloop, which does not. Non-vacuity was
# confirmed by probe, not by the population count: injecting a foreign skill name into a copy of a
# cassette fires `[host-inventory] skills[] — <name>`.
#
# The three predicates that would indicate a REAL leak — `mcp_servers[].name`,
# `account.email`/`.organization`/`.subscriptionType`, and a `mcp__<server>__...` tool naming a foreign
# server — return NONE across all 21 cassettes.
# What this does NOT cover (upstream's own docs/cassette.md): the command and plugin catalogs and
# command descriptions are ungated — no clean predicate exists for them, only an arbitrary threshold.
# (The SKILL catalog used to be on that list and no longer is; see NEW AXIS above.)
# Treat a green as a backstop against a known failure, not as proof a cassette is clean.
#
# EVERY --allow* regex here is FULL-MATCH, not substring. Keep this lesson even though the entry that
# produced it is gone: measured on the host-inventory class back when it had one, `founder-skills:.*`
# cleared all 240 while the tighter-looking `^founder-skills:` cleared ZERO, because an explicit anchor
# lands inside the harness's own wrapping and can never match. Write the pattern to
# cover the whole value, and re-count findings after editing one — an over-tight regex fails silently
# in the safe direction (findings stay) but an over-loose one disarms a class with no signal at all.
#
# HOW TO USE THIS FILE: sourcing it is NOT sufficient — it defines a bash ARRAY, not env vars. Expand it
# on the command line:  source privacy-allowlist.sh && cowork-harness verify-cassettes cassettes "${ALLOW[@]}"
# Sourcing alone leaves the gate unfiltered and reports ~7,200 synthetic-currency findings.
ALLOW=(
  --allow '\$\s*\d[\d.,]*\s*(?:[MmKkBb]|million|thousand|billion)?'
  --allow-domain '[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}'
  --allow-email '[A-Za-z0-9._%+\-]+@(?:acmecorp|example)\.com'
)
