# Email tripwire canary

`email-canary.cassette.json` is a tiny, purpose-built cassette (not a recording) whose only job is to
contain a **non-synthetic** email — `analyst@realstartup.com` (a made-up address; not real PII) — that
the production privacy allowlist must **flag**.

The CI privacy step (`.github/workflows/cowork-replay.yml`) runs `verify-cassettes --skip-staleness` on this
file with the **same** `$ALLOW` list (sourced from `cowork-tests/privacy-allowlist.sh`) it uses for the real
cassettes, and **fails the job if the canary does NOT trip**. This locks the email PII tripwire — the one guard the synthetic-only posture leans on
hardest — against a regression. (It nearly died once: an *unanchored* domain allow silently suppressed
every email finding by matching the domain inside the address. The canary makes that failure loud.)

This file lives OUTSIDE `cowork-tests/cassettes/` so the real privacy/replay/staleness gates never scan
it. Do not move it under `cassettes/`. If you change the allowlist and the canary stops tripping, the
allowlist has a hole — fix the allowlist, not the canary.
