"""Drift guard: the cowork privacy allowlist has ONE source of truth.

The allowlist (`--allow*` flags for `verify-cassettes`) used to be duplicated across the workflow,
the README, and (would have been) the re-record script. It now lives only in
`cowork-tests/privacy-allowlist.sh`, sourced by both the workflow and `rerecord.sh`.

Scope: this is a RE-INLINING tripwire only — it does NOT validate allowlist correctness. The
email-class tripwire is the canary (`cowork-tests/canary/`); nothing auto-checks domain/currency
over-broadening, so keep those regexes under review on edit.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "cowork-tests" / "privacy-allowlist.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cowork-replay.yml"
RERECORD = REPO_ROOT / "cowork-tests" / "rerecord.sh"


def test_allowlist_file_defines_the_array() -> None:
    text = ALLOWLIST.read_text(encoding="utf-8")
    assert "ALLOW=(" in text
    for flag in ("--allow ", "--allow-domain ", "--allow-email "):
        assert flag in text, f"allowlist missing {flag!r}"


def test_workflow_sources_allowlist_and_does_not_reinline() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "source cowork-tests/privacy-allowlist.sh" in text
    # The workflow must NOT re-inline the flags (that's the drift surface we collapsed). Allow them
    # only in the explanatory comment prose, so check for the executable flag tokens specifically.
    assert "--allow-domain '" not in text, "workflow re-inlined the allowlist — source the file instead"
    assert "--allow-email '" not in text, "workflow re-inlined the allowlist — source the file instead"


def test_rerecord_script_sources_allowlist() -> None:
    text = RERECORD.read_text(encoding="utf-8")
    assert "source ./privacy-allowlist.sh" in text
    assert "--allow-domain '" not in text, "rerecord.sh re-inlined the allowlist — source the file instead"
