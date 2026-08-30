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
COWORK_README = REPO_ROOT / "cowork-tests" / "README.md"
REPLAY_TEST = REPO_ROOT / "founder-skills" / "tests" / "test_cowork_cassette_replay.py"
CASSETTE_DIR = REPO_ROOT / "cowork-tests" / "cassettes"
CANARY = REPO_ROOT / "cowork-tests" / "canary" / "email-canary.cassette.json"

# CI SELECTORS are PINNED EXACTLY (2026-08-27); FLOORS stay floors. The two answer different
# questions -- "which CLI runs this gate" vs "is this CLI new enough for the check to mean anything"
# -- and collapsing them is the error this split exists to prevent. Rationale:
# docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md SS7.4-7.5.
_CI_PIN = "3.0.0"

# The declared floor per site, with the reason it differs where it does.
_RECORDING_FLOOR = "3.0.0"
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
    # So was test_cowork_cassette_replay.py's SKIP MESSAGE, which told a developer to install
    # `@^2.1.0` at the exact moment they install -- putting them on a different CLI from CI, which is
    # the skew the pin exists to remove. The message is an instruction site; `_MIN_HARNESS` in the
    # same file is a floor and is asserted separately below.
    "replay-test skip message": _CI_PIN,
}

_FLOORS: dict[str, str] = {
    # Recording bakes the harness version into the artifact, and a lane asserting
    # `present_files_called` at hostloop cannot be recorded below 2.2.0 (presence there comes from the
    # invocation count; below it, from the classified `presentedFiles` list, which drops the
    # non-absolute path host-path redaction produces — so the assert flips and `record` refuses).
    # The replay path has no measured requirement above 2.1.0, and raising `_MIN_HARNESS` would
    # convert a below-floor developer's red into a SILENT SKIP (`_require_harness` calls
    # `pytest.skip`) -- for exactly the developer it is meant to warn. Held deliberately, and it is
    # NOT a selector: it gates whether the replay test runs, not which CLI CI installs.
    "_MIN_HARNESS": _REPLAY_FLOOR,
    # NOTE there is no "rerecord.sh" entry. There was one, and it was DEAD: nothing read it (the
    # recording-floor test compares against `_RECORDING_FLOOR` directly), so setting it to "9.9.9"
    # left the suite green. A registry entry that reads as gating and gates nothing is the exact
    # failure this module exists to prevent, so it is removed rather than wired up twice.
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

    skip_msgs = _found(
        re.findall(r"cowork-harness@\{_CI_PIN\}", REPLAY_TEST.read_text(encoding="utf-8")),
        "replay-test skip message",
    )
    assert len(skip_msgs) == 2, f"expected 2 pinned install hints in the replay test, found {len(skip_msgs)}"
    pin_const = _found(
        re.findall(r'^_CI_PIN\s*=\s*"([^"]+)"', REPLAY_TEST.read_text(encoding="utf-8"), re.M),
        "replay-test _CI_PIN",
    )
    assert pin_const[0] == _CI_PINS["replay-test skip message"], f"replay-test _CI_PIN is {pin_const[0]}"

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


def test_rerecord_floor_header_agrees_with_its_own_gate() -> None:
    """The header is the FOURTH floor site, and it is the one that has actually drifted.

    `rerecord.sh` itself says to change all four (header, gate, FATAL message, `_RECORDING_FLOOR`)
    and records that this header "WAS ONE MINOR BEHIND THE GATE when 2.3.0 was adopted". The test
    that exists to stop that read the gate and the message and NOT the header — so the one site with
    a documented drift history was the one nothing checked.
    """
    header = _found(
        re.findall(r"^# FLOOR: >=(\d+\.\d+\.\d+)", RERECORD.read_text(encoding="utf-8"), re.M),
        "rerecord.sh FLOOR: header",
    )
    assert header[0] == _RECORDING_FLOOR, (
        f"rerecord.sh's `# FLOOR: >=` header says {header[0]}, the declared recording floor is "
        f"{_RECORDING_FLOOR} — this header has drifted behind its own gate before"
    )


def test_cowork_readme_floor_list_matches_the_registry() -> None:
    """cowork-tests/README.md IS the repo's floor-list document, and nothing read it.

    The 2.4.0 adoption updated the code and left this file describing a `>= 2.2.0` recording floor
    and `^2.1.0` CI carets — the precise "prose a major behind" failure the module's docstring claims
    to prevent. Assert the two numbers it must carry rather than its wording, so it can be rewritten
    freely but cannot state a stale version.
    """
    text = COWORK_README.read_text(encoding="utf-8")
    assert f">= {_RECORDING_FLOOR}" in text or f">={_RECORDING_FLOOR}" in text, (
        f"cowork-tests/README.md never states the recording floor {_RECORDING_FLOOR}"
    )
    assert f"`{_CI_PIN}`" in text, f"cowork-tests/README.md never states the CI pin {_CI_PIN}"
    stale = re.findall(r"\^\d+\.\d+\.\d+", text)
    allowed = {f"^{_REPLAY_FLOOR}"}
    assert not (set(stale) - allowed), (
        f"cowork-tests/README.md still describes CI selectors as caret ranges: "
        f"{sorted(set(stale) - allowed)} — they are pinned exactly at {_CI_PIN}"
    )


def test_prose_pin_statements_are_not_stale() -> None:
    """The English sentences that DESCRIBE the pins must state the pins.

    The 3.0.0 adoption moved every gated site, went green, and left EIGHT prose statements saying
    `2.5.0` — including this workflow's own "Version policy" header and the step NAME on the install
    step whose `run:` had just been bumped, so CI logs would have read "pinned 2.5.0" while installing
    3.0.0. That is the exact failure this module's docstring claims to prevent ("an adoption pass has
    already updated the code and left the prose a major behind"), committed in the sites the module
    did not read.

    Gated here rather than left to review because the drift is invisible: nothing executes prose, and
    the numbers only disagree with reality, never with each other.

    THE COUNT IS PART OF THE ASSERTION, and it is not decoration. Mutation-tested on the way in: all
    ten value-swaps red, but DELETING one of the two `PINNED EXACTLY at` sentences left the other
    matching and the test GREEN — a non-emptiness check cannot see a sentence disappear when a
    sibling survives. Pinning the expected occurrence count closes that. If you legitimately add or
    remove one of these sentences, update its count deliberately; that edit is the point.

    SCOPE. Only statements about the CURRENT posture are matched. Release history ("2.5.0 refuses
    ...", "THE FLOOR WAS 1.25.0") is deliberately untouched — it is accurate about its own release
    and must stay readable, which is why these patterns key on present-tense policy phrasing rather
    than on the bare version string.
    """
    wf = WORKFLOW.read_text(encoding="utf-8")
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    readme = COWORK_README.read_text(encoding="utf-8")

    # (label, text, pattern, expected occurrences, expected value)
    sites: tuple[tuple[str, str, str, int, str], ...] = (
        ("workflow version-policy header", wf, r"PINNED EXACTLY at (\d+\.\d+\.\d+)", 1, _CI_PIN),
        ("workflow 'now PINNED at' note", wf, r"sites are now PINNED at (\d+\.\d+\.\d+)", 1, _CI_PIN),
        ("workflow 'the exact' note", wf, r"all four are now the exact `(\d+\.\d+\.\d+)`", 1, _CI_PIN),
        ("workflow install step NAME", wf, r"- name: Install cowork-harness \(pinned (\d+\.\d+\.\d+)", 1, _CI_PIN),
        ("CLAUDE.md 'PINNED EXACTLY at'", claude, r"PINNED EXACTLY at `(\d+\.\d+\.\d+)`", 2, _CI_PIN),
        ("CLAUDE.md registry description (pin)", claude, r"pinned exactly, `(\d+\.\d+\.\d+)`\)", 1, _CI_PIN),
        ("CLAUDE.md 'RECORDING floor'", claude, r"RECORDING floor `>=(\d+\.\d+\.\d+)`", 1, _RECORDING_FLOOR),
        (
            "CLAUDE.md registry description (floor)",
            claude,
            r"FLOORS \(recording `>=(\d+\.\d+\.\d+)`",
            1,
            _RECORDING_FLOOR,
        ),
        (
            "CLAUDE.md 'rerecord.sh enforces'",
            claude,
            r"`rerecord\.sh` enforces a \*\*harness floor of `>=(\d+\.\d+\.\d+)`\*\*",
            1,
            _RECORDING_FLOOR,
        ),
        ("cowork README 'the floor is now'", readme, r"the floor is now (\d+\.\d+\.\d+)", 1, _RECORDING_FLOOR),
    )

    for label, text, pattern, count, want in sites:
        got = _found(re.findall(pattern, text), label)
        assert len(got) == count, (
            f"{label}: expected {count} statement(s), found {len(got)}. A sentence was added or "
            f"removed — update the declared count deliberately (see this test's docstring: a bare "
            f"non-emptiness check let a DELETED sentence pass)"
        )
        assert set(got) == {want}, f"{label} states {sorted(set(got))}, registry says {want}"
