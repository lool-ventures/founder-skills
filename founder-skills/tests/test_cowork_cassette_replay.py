"""Token-free cowork-harness cassette replay, surfaced in the pytest workflow.

This is the `cowork` lane (`-m cowork`): it replays the committed cassettes under
`cowork-tests/cassettes/` through the cowork-harness pytest helper shipped inside the
npm package. `cowork.replay(...)` is deterministic and needs neither Docker nor an auth
token, so cassette health becomes visible in the same `uv run pytest` devs already run —
without joining the default suite (the packaged GitHub Action already replays in CI, and
machines without the harness must stay green).

The tests, in file order:
  1. ``test_cassette_replays_green`` — parametrized replay over every cassette → the replay
     verdict is success. Redundant with CI replay by design; the point is local-workflow
     visibility. This is the only one that drives the harness CLI.
  2. ``test_every_scenario_has_a_cassette_or_is_allowlisted`` — scenario↔cassette parity
     against ``_NO_CASSETTE_ALLOWLIST``. Pure file reads.
  3. ``test_cap_state_fully_diluted_covers_founder_shares`` — one fine-grained invariant the
     scenario YAML cannot express: a Python-level cross-field check over the re-driven
     ``cap_state.json`` body. On the replay lane the run's work dir is not materialized and
     ``Result.artifacts`` is empty (verified against the 0.24.0 helper), so the body is read
     from the cassette's ``artifacts[].body`` — which IS the output the replay re-drives.

Name them rather than counting them: this header said "Two tests" against a module holding
three, and omitted the parity test entirely — introduced by the same commit that un-inerted
it. A restated count drifts; an enumeration that names its members is checkable by reading.

Only the first needs the harness. The other two read committed files, so they
carry no `cowork` marker, take no `cowork` fixture, and run everywhere — including CI.
That split is deliberate and was previously absent: a module-level `pytest.skip` gated the
whole file on the CLI, so on any machine without it (every CI run) all three reported as a
single `1 skipped` line and the two file-reading guards were inert without anything saying
so. The skip now lives in the `cowork` fixture. Do not hoist it back to module level.

The `sys.path` bootstrap that makes `cowork_harness` importable is the sanctioned pattern
from the harness `python/README.md` (the helper module is not pip-installed); it must run
before the import, so both live inside the fixture. The module-level `Cowork` name is a
`TYPE_CHECKING`-only import: `from __future__ import annotations` defers annotations at
runtime but ruff (F821) and mypy (name-defined) still resolve them statically.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    # Annotation-only. The runtime import lives in the `cowork` fixture, after the sys.path
    # bootstrap that makes it resolvable. `from __future__ import annotations` defers the
    # annotation at RUNTIME but NOT for ruff (F821) or mypy (name-defined) — both still
    # resolve it statically, so this guard is load-bearing, not decorative.
    from cowork_harness import Cowork  # type: ignore[import-not-found]

CASSETTE_DIR = Path(__file__).resolve().parents[2] / "cowork-tests" / "cassettes"
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "cowork-tests" / "scenarios"

# Scenarios that intentionally have no committed cassette yet. Each entry MUST carry a
# one-line reason — this is an explicit allowlist, not a silence valve: a scenario landing
# with no cassette and no entry here must fail the parity test below, loudly, rather than
# quietly matching nothing (a directory glob finding zero new scenarios is not evidence
# anything is fine — see leak_scan.py's own docstring on that exact failure mode).
_NO_CASSETTE_ALLOWLIST: dict[str, str] = {
    "market-sizing-smoke": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Superseded by "
        "market-sizing-remote-lane for the tripwire. Deleting it is net positive: it removes one of three "
        "documented delivery_check WARN cases and closes the long-standing 'present_files_called authored but "
        "never evaluated' item — a cassette-less lane has nothing frozen to diverge from. ~$4.05."
    ),
    "deck-review-stage-disagreement": (
        "un-cassetted because it CANNOT record green: it is measuring a real defect. Three paid "
        "recordings, three different behaviours — the producer's sentence reached the founder "
        "verbatim in the gate question, then paraphrased, then not at all. The producer emits it "
        "only in its stdout receipt, so whether the founder ever sees it depends on the agent "
        "relaying it, which SKILL.md asks for in prose and prose does not enforce. The lane is "
        "correct and the fix is not yet, so this stays red rather than being loosened until it "
        "passes. Do not record it, and do not relax the assert to make it green — the assert is "
        "already matched on the property (the deck's claim is NAMED beside the confirmed stage) "
        "rather than on any wording. It is also the only deck in the corpus that contradicts "
        "itself about its own stage: the smoke deck says seed and reads seed, and the gate-stop "
        "deck is out of scope on both counts."
    ),
    "deck-review-numeric-chain": (
        "deliberately un-cassetted: the LIVE verification lane for the numeric chain (Steps 3.5-3.9). "
        "Most of what it verifies is PROSE — three dispatch templates asking a sub-agent to extract a "
        "ledger at full scale, to transcribe blind, and to withdraw a contradiction on one of exactly "
        "two grounds. A cassette freezes one past agent's behaviour and re-asserts it, which is the "
        "opposite of what this lane is for; it already found one defect (an invented `kind` value) that "
        "a frozen recording would have preserved rather than surfaced. Recording it costs a paid run "
        "(~$4.7 / 21 min measured 2026-08-14) and pins the behaviour it currently measures."
    ),
    "competitive-positioning-deck-no-slide": (
        "deliberately un-cassetted: this is the LIVE verification lane for the 2026-08 remediation, "
        "whose whole purpose is to exercise prose fixes against a real agent. A cassette freezes the "
        "scenario AND the agent's recorded behaviour, so replaying one would re-assert a past run "
        "rather than test the current skill — exactly the property this lane exists to avoid. Record "
        "it only if it is ever wanted as a regression gate, and note that recording it costs a paid "
        "run and pins the behaviour it currently measures."
    ),
    "market-sizing-fx-conversion": (
        "deliberately un-cassetted, same reasoning as the deck-no-slide lane above: this is the LIVE "
        "verification lane for producer-side FX, and half that fix is PROSE — the dispatch templates "
        "ask a sub-agent to tag a foreign-currency figure, and SKILL.md asks the main thread to look a "
        "rate up and re-pipe. A cassette would freeze one past agent's behaviour and re-assert it, "
        "which is precisely what this lane must not do. Verified live 2026-08-04: the sub-agent "
        "emitted industry_total_currency=USD, the main thread supplied a sourced dated rate, and the "
        "conversion landed in sizing.json and in both deliverables ($4.84, 1283s)."
    ),
    "competitive-positioning-recall-adoption": (
        "not yet recorded (paid; pending the next rerecord.sh batch — see "
        "cowork-tests/rerecord.sh's cumulative cost pre-flight comment for the current count)"
    ),
    "cap-table-acquisition": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Its assert-KEY set is a "
        "verified strict subset of cap-table-safe-full's, same default.yaml session, no distinct delivery shape. "
        "~$2.88."
    ),
    "cap-table-carta": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Carta-XLSX upload lane. "
        "Session (carta.yaml) and fixture both retained; the frozen record of one past extraction is what goes. "
        "~$2.49."
    ),
    "cap-table-extract-safe": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). SAFE-PDF upload lane. "
        "Session (safe-cap-discount.yaml) and fixture retained. ~$3.16."
    ),
    "cap-table-fast-assess": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). The lightweight/concise "
        "answer path. Cheapest carrier of computer_links_resolve_if_present, which has three other carriers. "
        "~$0.98."
    ),
    "cap-table-lane3-freeform": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Freeform-spreadsheet "
        "lane. Session (lane3-freeform.yaml) and gen_lane3_fixture.py retained. ~$3.16."
    ),
    "cap-table-note-conversion": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Assert-key subset of "
        "cap-table-safe-full (tied on item count, subset on keys). ~$2.54."
    ),
    "cap-table-priced-ad": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Assert-key subset of "
        "cap-table-safe-full. ~$2.62."
    ),
    "competitive-positioning-false-positive": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). Half of the adversarial "
        "verification A/B. Deleting one half destroys the comparison, so both halves went together. ~$7.39."
    ),
    "competitive-positioning-genuine-control": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). The other half of that "
        "A/B pair, and the corpus's thinnest cost sample (n=1). ~$7.22."
    ),
    "competitive-positioning-no-change": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). The closest call on the "
        "list: its header names it the runtime verification of the reserved 'No changes — ' prefix and the mirror "
        "of the recall-adoption lane. Deleted because competitive-positioning-smoke (kept) carries MORE "
        "occurrences of that prefix and also selects the no-change branch at every gate, and check_substance() "
        "takes a run dir, never a cassette. ~$8.05."
    ),
    "ic-sim-contested": (
        "DELIBERATELY UN-CASSETTED as of 2026-08-24 — the cassette was deleted, the scenario kept. Rationale for "
        "the whole batch: a cassette replays FROZEN events and re-evaluates frozen assertions against them, so it "
        "cannot detect a skill-behaviour regression — measured, 18 of the then-22 cassettes were recorded against "
        "since-changed skills and all 22 still replayed green. The corpus therefore bought a per-skill staleness "
        "tripwire, analyzer fixtures, and documentation of a past paid run, at $86.36 per hash-format epoch. Full "
        "analysis, including what each deletion gives up: "
        "docs/internal/2026-08-24-cassette-corpus-value-analysis.md. Re-record on purpose with `rerecord.sh "
        "<name>` (the bare form only refreshes scenarios that already have a cassette). The contested-debate "
        "path, distinct from ic-sim-smoke's consensus path. ic-sim keeps its tripwire via -smoke. ~$5.40."
    ),
}

# The floor is load-bearing on THIS path, and not because of a missing feature.
# An unknown top-level scenario key inside a frozen cassette is carried but never
# consulted: replay reads that object as passthrough and behaves exactly as if the
# key were absent. So a stale CLI does not refuse the cassette — it replays under
# the old semantics and can return the OPPOSITE verdict with no signal. Frozen
# *assertions* are validated and hard-reject, so this is not "replay validates
# nothing"; only the scenario object is passthrough. `lane:` is the first key we
# use that behaves this way.
_MIN_HARNESS = (2, 1, 0)


def _installed_version(cli: str) -> tuple[int, ...] | None:
    """Read the version from the package.json beside the resolved CLI.

    Read from disk rather than `--version`, which a linked working checkout can
    answer with the version it claims rather than the one it is.
    """
    pkg = Path(cli).resolve().parents[1] / "package.json"
    try:
        raw = json.loads(pkg.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None
    parts: list[int] = []
    for chunk in str(raw).split("-")[0].split("."):
        if not chunk.isdigit():
            return None
        parts.append(int(chunk))
    return tuple(parts) or None


def _resolve_cli() -> str | None:
    """Locate the harness `dist/cli.js`, in the order the README sanctions.

    COWORK_HARNESS_CLI (explicit) → the `cowork-harness` bin's package dir → the global
    npm root. Returns None when the harness is not installed (the module then skips).
    """
    env = os.environ.get("COWORK_HARNESS_CLI")
    if env and Path(env).exists():
        return env

    bin_path = shutil.which("cowork-harness")
    if bin_path:
        # The bin is a symlink into <npm-global>/cowork-harness/; resolve to the package dir.
        pkg = Path(bin_path).resolve().parent.parent / "cowork-harness"
        cli = pkg / "dist" / "cli.js"
        if cli.exists():
            return str(cli)

    try:
        npm_root = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    cli = Path(npm_root) / "cowork-harness" / "dist" / "cli.js"
    return str(cli) if cli.exists() else None


def _require_harness() -> str:
    """Resolve the harness CLI or skip. FIXTURE-scoped by design — never module-level.

    This used to be a pair of `pytest.skip(..., allow_module_level=True)` calls, which made
    EVERY test in this file inert wherever the harness is absent — i.e. every CI run, since
    `ci.yml` installs pytest but never the harness. Two tests below read committed files and
    need no harness at all, so they were silently not running in CI. Worse, a module-level
    skip collapses the whole module into a single `1 skipped` line, so nothing indicated the
    coverage was missing. Skipping per-fixture keeps that failure from recurring: only the
    tests that actually drive the CLI can skip.
    """
    cli = _resolve_cli()
    if cli is None:
        floor = ".".join(str(n) for n in _MIN_HARNESS)
        pytest.skip(f"cowork-harness not installed (npm i -g cowork-harness@^{floor})")

    version = _installed_version(cli)
    if version is None or version < _MIN_HARNESS:
        floor = ".".join(str(n) for n in _MIN_HARNESS)
        found = ".".join(str(n) for n in version) if version else "unreadable"
        pytest.skip(
            f"cowork-harness {found} is below the {floor} replay floor — skipping rather than "
            f"replaying, because a cassette carrying a scenario key this CLI does not know is "
            f"replayed as if the key were absent and can return the opposite verdict silently. "
            f"Upgrade: npm i -g cowork-harness@^{floor}"
        )
    return cli


def _cassettes() -> list[Path]:
    return sorted(CASSETTE_DIR.glob("*.cassette.json"))


@pytest.fixture(scope="module")
def cowork() -> Cowork:
    cli = _require_harness()
    # Bootstrap the helper module onto sys.path (dist/cli.js → package root → python/), per
    # the harness python/README.md. It must run before the import, so the two stay together.
    python_dir = Path(cli).resolve().parents[1] / "python"
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))

    from cowork_harness import Cowork as _Cowork  # type: ignore[import-not-found]

    return _Cowork(cli=cli)


@pytest.mark.cowork
@pytest.mark.parametrize("cassette", _cassettes(), ids=lambda p: p.name.replace(".cassette.json", ""))
def test_cassette_replays_green(cowork: Cowork, cassette: Path) -> None:
    """Every committed cassette replays to a success verdict (token-free)."""
    result = cowork.replay(str(cassette))
    result.assert_success()


def test_every_scenario_has_a_cassette_or_is_allowlisted() -> None:
    """Every `cowork-tests/scenarios/*.yaml` must have a matching committed
    `cowork-tests/cassettes/<name>.cassette.json`, unless the gap is named in
    `_NO_CASSETTE_ALLOWLIST` with a reason. A new scenario landing with neither
    must fail loudly here rather than silently drifting.

    Deliberately carries NO scenario/cassette counts: this docstring used to state
    a "last measured" pair, and it drifted (it said 22/21 with one allowlist entry
    while the tree held 24/21 with three). A count restated in prose beside the
    code that derives it is the exact defect this test exists to catch. The
    assertions below are the current count; run them.

    No harness required — pure file reads — so this must NOT carry the `cowork`
    marker or depend on the `cowork` fixture, or it goes inert in CI."""
    scenario_names = {p.stem for p in SCENARIOS_DIR.glob("*.yaml")}
    cassette_names = {p.name[: -len(".cassette.json")] for p in CASSETTE_DIR.glob("*.cassette.json")}

    stale_allowlist = set(_NO_CASSETTE_ALLOWLIST) - scenario_names
    assert not stale_allowlist, (
        f"_NO_CASSETTE_ALLOWLIST names scenario(s) that no longer exist (renamed or removed) — "
        f"remove the stale entry: {sorted(stale_allowlist)}"
    )

    now_cassetted = set(_NO_CASSETTE_ALLOWLIST) & cassette_names
    assert not now_cassetted, (
        f"_NO_CASSETTE_ALLOWLIST entry now HAS a committed cassette — remove it so the entry "
        f"doesn't mask a future real gap under the same name: {sorted(now_cassetted)}"
    )

    missing = scenario_names - cassette_names - set(_NO_CASSETTE_ALLOWLIST)
    assert not missing, (
        f"scenario(s) with no committed cassette and no allowlist reason — either record a "
        f"cassette by name (cowork-tests/rerecord.sh <name>) or add a one-line reason to "
        f"_NO_CASSETTE_ALLOWLIST in this file: {sorted(missing)}"
    )


def test_cap_state_fully_diluted_covers_founder_shares() -> None:
    """A cross-field invariant on the re-driven cap_state that YAML `artifact_json` can't state.

    ``as_converted_totals.fully_diluted_shares`` must be at least the sum of the founders'
    common shares — a structural sanity check spanning two artifact regions. Read from the
    cassette body (the replay lane does not materialize the work dir).

    Reads a committed file and drives no CLI, so — like the parity test above — it carries
    no `cowork` marker and takes no `cowork` fixture, and therefore runs in CI.
    """
    cassette = CASSETTE_DIR / "cap-table-safe-full.cassette.json"
    doc = json.loads(cassette.read_text())

    cap_state = _artifact_body(doc, "cap_state.json")
    assert cap_state is not None, "cap_state.json body not inlined in the cassette manifest"

    fully_diluted = cap_state["as_converted_totals"]["fully_diluted_shares"]
    founder_common = sum(f["common_shares"] for f in cap_state["founders"])
    assert founder_common > 0, "expected the synthetic founders to hold common shares"
    assert fully_diluted >= founder_common, (
        f"fully_diluted_shares ({fully_diluted}) < sum of founder common ({founder_common})"
    )


def _artifact_body(cassette_doc: dict[str, Any], filename: str) -> Any | None:
    """Return the parsed JSON body of the first artifact whose path ends with `filename`.

    Cassette artifacts carry either an inlined `body` (small JSON producers) or a hash-only
    manifest entry (large/base64 deliverables); returns None when the body is not inlined.
    """
    for artifact in cassette_doc.get("artifacts", []) or []:
        if artifact.get("path", "").endswith(filename) and "body" in artifact:
            return json.loads(artifact["body"])
    return None
