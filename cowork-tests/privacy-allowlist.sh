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
# NOTE (1.18.0+): host-inventory. The class flags a recording machine's own MCP servers / account /
# agents frozen into a cassette by a host-inheriting tier — which is our tier, since `fidelity: cowork`
# resolves to hostloop. Measured on the committed corpus at adoption: 240 findings, ALL of them
# `agents[] — founder-skills:<skill>`, i.e. the six agents of the plugin UNDER TEST. Those are the
# fixture, not the host: the class flags an `agents[]` entry outside the built-in roster, and a mounted
# plugin's own agents are outside it by construction. The three predicates that would indicate a REAL
# leak — `mcp_servers[].name`, `account.email`/`.organization`/`.subscriptionType`, and a
# `mcp__<server>__…` tool naming a foreign server — return NONE across all 21 cassettes.
# The allow is scoped to our own plugin namespace ON PURPOSE. A bare `.*` would disarm the class and
# turn a privacy backstop into decoration; enumerating the six agents would red CI the day a seventh
# lands, for a non-finding. Anything genuinely foreign still fires.
# What this does NOT cover (upstream's own docs/cassette.md): the command / skill / plugin catalogs and
# command descriptions are ungated — no clean predicate exists for them, only an arbitrary threshold.
# Treat a green as a backstop against a known failure, not as proof a cassette is clean.
#
# EVERY --allow* regex here is FULL-MATCH, not substring. Measured on the host-inventory class:
# `founder-skills:.*` clears all 240; the tighter-looking `^founder-skills:` clears ZERO, because an
# explicit anchor lands inside the harness's own wrapping and can never match. Write the pattern to
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
  --allow-host-inventory 'founder-skills:.*'
)
