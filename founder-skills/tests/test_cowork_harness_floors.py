"""Drift guards for the cowork-harness version surface and derived corpus facts.

Three tripwires, each for a defect this repo has actually shipped:

1. **Floor registry.** A harness floor is stated at several sites, deliberately NOT all the same
   number (recording needs more than replay), and an adoption pass has already updated the code and
   left the prose a major behind. `_FLOORS` is the declared table; each site is extracted from its own
   file and compared. Differing values stay legal — they must merely be declared.

2. **`uses:` vs `version:`.** The `uses:` ref pins the ACTION wrapper; the `version:` input pins the
   CLI. They move independently, which is how the wrapper pin sat on `@v1` while every step installed a
   2.x CLI. The majors must agree.

3. **Derived corpus facts.** Cassette count, format version and the canary's deliberate exception are
   measurable from the tree, and prose restating them has drifted repeatedly.
   `cowork-tests/cassette_inventory.py` exists to print them and is non-gating; this makes them fail.

SCOPE. These check STATED-vs-ACTUAL consistency, never whether a floor is the *right* floor. Nothing
here reads the harness or needs it installed — pure file reads, no `cowork` marker, so it runs in CI.

NON-VACUITY. Every extraction asserts its own pattern matched. A regex that silently stops matching
would otherwise turn each of these into a permanent green, which is the failure mode they exist to
prevent (this repo has already measured one structural assertion vacuous).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cowork-replay.yml"
RERECORD = REPO_ROOT / "cowork-tests" / "rerecord.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
REPLAY_TEST = REPO_ROOT / "founder-skills" / "tests" / "test_cowork_cassette_replay.py"
CASSETTE_DIR = REPO_ROOT / "cowork-tests" / "cassettes"
CANARY = REPO_ROOT / "cowork-tests" / "canary" / "email-canary.cassette.json"

# CI SELECTORS are PINNED EXACTLY (2026-08-27); FLOORS stay floors. The two answer different
# questions -- "which CLI runs this gate" vs "is this CLI new enough for the check to mean anything"
# -- and collapsing them is the error this split exists to prevent. Rationale:
# docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md SS7.4-7.5.
_CI_PIN = "2.4.0"

# The declared floor per site, with the reason it differs where it does.
_RECORDING_FLOOR = "2.4.0"
_REPLAY_FLOOR = "2.1.0"

# Sites that SELECT the CLI a gate runs. Exact, never a range: a caret auto-adopted every upstream
# release into CI with nobody choosing it (2.4.0 was live in these gates before its adoption plan was
# written), and five of the gates red on rules the harness adds.
_CI_PINS: dict[str, str] = {
    "workflow version: inputs": _CI_PIN,
    "workflow npm i -g": _CI_PIN,
    "pyproject marker": _CI_PIN,
    "CONTRIBUTING": _CI_PIN,
    # CLAUDE.md was an UNGATED pin site until 2026-08-27 -- it carried the same install line and no
    # test read it, so it could drift silently whatever value it held. Gated now.
    "CLAUDE.md": _CI_PIN,
}

_FLOORS: dict[str, str] = {
    # Recording bakes the harness version into the artifact, and a lane asserting
    # `present_files_called` at hostloop cannot be recorded below 2.2.0 (presence there comes from the
    # invocation count; below it, from the classified `presentedFiles` list, which drops the
    # non-absolute path host-path redaction produces — so the assert flips and `record` refuses).
    "rerecord.sh": _RECORDING_FLOOR,
    # The replay path has no measured requirement above 2.1.0, and raising `_MIN_HARNESS` would
    # convert a below-floor developer's red into a SILENT SKIP (`_require_harness` calls
    # `pytest.skip`) -- for exactly the developer it is meant to warn. Held deliberately, and it is
    # NOT a selector: it gates whether the replay test runs, not which CLI CI installs.
    "_MIN_HARNESS": _REPLAY_FLOOR,
}

# Cassette-format facts, derived from the tree by the assertions below.
_CASSETTE_VERSION = 12
_CANARY_CASSETTE_VERSION = 10  # hand-authored PII tripwire; never re-recorded.


def _found(matches: list[str], where: str) -> list[str]:
    """Fail when an extraction pattern matches nothing — a silent green is the defect."""
    assert matches, f"extraction found nothing in {where} — the pattern has rotted, not the floor"
    return matches


def test_rerecord_gate_and_message_agree_on_the_recording_floor() -> None:
    """The numeric gate and its FATAL string are separate edits; editing one is a real defect."""
    text = RERECORD.read_text(encoding="utf-8")
    major, minor = _RECORDING_FLOOR.split(".")[:2]

    gates = _found(re.findall(r'\[ "\$major" -eq (\d+) \] && \[ "\$minor" -ge (\d+) \]', text), "rerecord.sh gate")
    assert gates[0] == (major, minor), f"rerecord.sh numeric gate is {gates[0]}, declared floor is {_RECORDING_FLOOR}"

    msgs = _found(re.findall(r"FATAL: need >=(\d+\.\d+\.\d+)", text), "rerecord.sh FATAL message")
    assert msgs == [_RECORDING_FLOOR], (
        f"rerecord.sh FATAL message says {msgs}, declared floor is {_RECORDING_FLOOR} — "
        f"the gate and the message are adjacent lines and must be edited together"
    )


def test_ci_selector_pins_match_the_registry_and_carry_no_range() -> None:
    """Every site that decides WHICH CLI a gate runs is an exact version.

    The `[^^~>=]` guard is the load-bearing half: re-introducing a caret is the regression this
    replaced, and a pattern that only checked the NUMBER would pass on `^2.4.0`.
    """
    wf = WORKFLOW.read_text(encoding="utf-8")

    inputs = _found(re.findall(r'^\s*version: "([^"]+)"', wf, re.M), "workflow version: inputs")
    assert set(inputs) == {_CI_PINS["workflow version: inputs"]}, f"workflow version: inputs are {sorted(set(inputs))}"

    installs = _found(re.findall(r"npm i -g cowork-harness@([^\s`]+)", wf), "workflow npm i -g")
    assert set(installs) == {_CI_PINS["workflow npm i -g"]}, f"workflow npm installs are {sorted(set(installs))}"

    for label, path in (
        ("pyproject marker", PYPROJECT),
        ("CONTRIBUTING", CONTRIBUTING),
        ("CLAUDE.md", CLAUDE_MD),
    ):
        found = _found(
            re.findall(r"npm i -g cowork-harness@([^\s`]+)", path.read_text(encoding="utf-8")),
            label,
        )
        assert set(found) == {_CI_PINS[label]}, f"{label} states {sorted(set(found))}, want {_CI_PINS[label]}"

    every = set(inputs) | set(installs)
    for v in every:
        assert not v.startswith(("^", "~", ">", "=")), (
            f"CI selector {v!r} carries a RANGE. A caret auto-adopts upstream releases into CI with "
            f"nobody choosing it -- the posture retired 2026-08-27. Raise the pin deliberately instead."
        )


def test_replay_floor_matches_the_registry_and_stays_a_floor() -> None:
    mins = _found(
        re.findall(r"_MIN_HARNESS\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", REPLAY_TEST.read_text(encoding="utf-8")),
        "_MIN_HARNESS",
    )
    assert ".".join(mins[0]) == _FLOORS["_MIN_HARNESS"], f"_MIN_HARNESS is {mins[0]}"
    assert _FLOORS["_MIN_HARNESS"] != _CI_PIN, (
        "_MIN_HARNESS was raised to the CI pin. It is a SKIP GUARD, not a selector: raising it turns a "
        "below-floor developer's red into a silent skip. Pin CI, floor this."
    )


def test_action_ref_major_matches_the_cli_major_it_installs() -> None:
    """`uses:` pins the ACTION, `version:` pins the CLI — they move independently.

    A workflow left on `@v1` installs a 2.x CLI without complaint, so nothing surfaces the mismatch.
    """
    wf = WORKFLOW.read_text(encoding="utf-8")
    refs = _found(re.findall(r"uses: yaniv-golan/cowork-harness@v(\d+)", wf), "action uses: refs")
    versions = _found(re.findall(r'^\s*version: "\^?(\d+)\.', wf, re.M), "action version: inputs")

    assert len(refs) == len(versions), (
        f"{len(refs)} action step(s) but {len(versions)} version: input(s) — every step must pin the "
        f"CLI explicitly rather than riding the action's `latest` default"
    )
    assert set(refs) == set(versions), (
        f"action wrapper major(s) {sorted(set(refs))} != installed CLI major(s) {sorted(set(versions))}"
    )


def test_cassette_format_facts_are_what_prose_may_state() -> None:
    cassettes = sorted(CASSETTE_DIR.glob("*.cassette.json"))
    assert cassettes, "no committed cassettes found — path rotted"

    versions = {p.name: json.loads(p.read_text(encoding="utf-8")).get("cassetteVersion") for p in cassettes}
    off = {n: v for n, v in versions.items() if v != _CASSETTE_VERSION}
    assert not off, (
        f"cassette(s) not at v{_CASSETTE_VERSION}: {off}. If a re-record moved the format, update "
        f"_CASSETTE_VERSION here AND every prose site that states it (see cassette_inventory.py)"
    )

    canary = json.loads(CANARY.read_text(encoding="utf-8")).get("cassetteVersion")
    assert canary == _CANARY_CASSETTE_VERSION, (
        f"email canary is v{canary}, expected v{_CANARY_CASSETTE_VERSION}. It is hand-authored and must "
        f"never be re-recorded; hand-bump it only at a MIN_SUPPORTED_CASSETTE_VERSION raise"
    )
