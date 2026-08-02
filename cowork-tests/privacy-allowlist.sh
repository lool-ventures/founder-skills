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
ALLOW=(
  --allow '\$\s*\d[\d.,]*\s*(?:[MmKkBb]|million|thousand|billion)?'
  --allow-domain '[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}'
  --allow-email '[A-Za-z0-9._%+\-]+@(?:acmecorp|example)\.com'
)
