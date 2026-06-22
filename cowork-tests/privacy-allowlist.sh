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
ALLOW=(
  --allow '\$\s*\d[\d.,]*\s*(?:[MmKkBb]|million|thousand|billion)?'
  --allow-domain '[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}'
  --allow-email '[A-Za-z0-9._%+\-]+@(?:acmecorp|example)\.com'
)
