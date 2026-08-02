"""Token-free cowork-harness cassette replay, surfaced in the pytest workflow.

This is the `cowork` lane (`-m cowork`): it replays the committed cassettes under
`cowork-tests/cassettes/` through the cowork-harness pytest helper shipped inside the
npm package. `cowork.replay(...)` is deterministic and needs neither Docker nor an auth
token, so cassette health becomes visible in the same `uv run pytest` devs already run —
without joining the default suite (the packaged GitHub Action already replays in CI, and
machines without the harness must stay green).

Two tests:
  1. Parametrized replay over every cassette → the replay verdict is success. Redundant
     with CI replay by design; the point is local-workflow visibility.
  2. One fine-grained invariant the scenario YAML cannot express: a Python-level cross-field
     check over the re-driven ``cap_state.json`` body. On the replay lane the run's work dir
     is not materialized and ``Result.artifacts`` is empty (verified against the 0.24.0
     helper), so the body is read from the cassette's ``artifacts[].body`` — which IS the
     output the replay re-drives.

The `sys.path` bootstrap that makes `cowork_harness` importable is the sanctioned pattern
from the harness `python/README.md` (the helper module is not pip-installed); it must run
before the import, so the bootstrap and the guarded import stay together at the top of the
module rather than with the other top-level imports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CASSETTE_DIR = Path(__file__).resolve().parents[2] / "cowork-tests" / "cassettes"
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "cowork-tests" / "scenarios"

# Scenarios that intentionally have no committed cassette yet. Each entry MUST carry a
# one-line reason — this is an explicit allowlist, not a silence valve: a scenario landing
# with no cassette and no entry here must fail the parity test below, loudly, rather than
# quietly matching nothing (a directory glob finding zero new scenarios is not evidence
# anything is fine — see leak_scan.py's own docstring on that exact failure mode).
_NO_CASSETTE_ALLOWLIST: dict[str, str] = {
    "competitive-positioning-recall-adoption": (
        "not yet recorded (paid; pending the next rerecord.sh batch — see "
        "cowork-tests/rerecord.sh's cumulative cost pre-flight comment for the current count)"
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
_MIN_HARNESS = (1, 16, 0)


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


_CLI = _resolve_cli()
if _CLI is None:
    pytest.skip(
        "cowork-harness not installed (npm i -g cowork-harness@^1.17.0)",
        allow_module_level=True,
    )

_VERSION = _installed_version(_CLI)
if _VERSION is None or _VERSION < _MIN_HARNESS:
    _floor = ".".join(str(n) for n in _MIN_HARNESS)
    _found = ".".join(str(n) for n in _VERSION) if _VERSION else "unreadable"
    pytest.skip(
        f"cowork-harness {_found} is below the {_floor} replay floor — skipping rather than "
        f"replaying, because a cassette carrying a scenario key this CLI does not know is "
        f"replayed as if the key were absent and can return the opposite verdict silently. "
        f"Upgrade: npm i -g cowork-harness@^{_floor}",
        allow_module_level=True,
    )

# Bootstrap the helper module onto sys.path (dist/cli.js → package root → python/), per the
# harness python/README.md. Kept adjacent to its import, which must follow it.
_PYTHON_DIR = Path(_CLI).resolve().parents[1] / "python"
if str(_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_DIR))

from cowork_harness import Cowork  # type: ignore[import-not-found]  # noqa: E402  (runtime sys.path bootstrap above)


def _cassettes() -> list[Path]:
    return sorted(CASSETTE_DIR.glob("*.cassette.json"))


@pytest.fixture(scope="module")
def cowork() -> Cowork:
    return Cowork(cli=_CLI)


@pytest.mark.cowork
@pytest.mark.parametrize("cassette", _cassettes(), ids=lambda p: p.name.replace(".cassette.json", ""))
def test_cassette_replays_green(cowork: Cowork, cassette: Path) -> None:
    """Every committed cassette replays to a success verdict (token-free)."""
    result = cowork.replay(str(cassette))
    result.assert_success()


@pytest.mark.cowork
def test_every_scenario_has_a_cassette_or_is_allowlisted() -> None:
    """Every `cowork-tests/scenarios/*.yaml` must have a matching committed
    `cowork-tests/cassettes/<name>.cassette.json`, unless the gap is named in
    `_NO_CASSETTE_ALLOWLIST` with a reason. A new scenario landing with neither
    must fail loudly here rather than silently drifting — this is the parity
    gap the fleet has carried without a regression test (last measured: 22
    scenarios / 21 cassettes, the single gap now allowlisted above)."""
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


@pytest.mark.cowork
def test_cap_state_fully_diluted_covers_founder_shares() -> None:
    """A cross-field invariant on the re-driven cap_state that YAML `artifact_json` can't state.

    ``as_converted_totals.fully_diluted_shares`` must be at least the sum of the founders'
    common shares — a structural sanity check spanning two artifact regions. Read from the
    cassette body (the replay lane does not materialize the work dir).
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
