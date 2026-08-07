#!/usr/bin/env python3
"""Print the measured state of the committed cassette corpus.

Why this exists: the corpus size, its `environment.harnessVersion` spread and its
`cassetteVersion` split are VOLATILE facts that were restated in prose across CLAUDE.md,
cowork-tests/README.md, cowork-tests/rerecord.sh and .github/workflows/cowork-replay.yml —
and went wrong in every one of them, repeatedly, including inside a sentence that itself
said "re-derive this count after every re-record". Prose cannot be kept true by instruction.

So: derive, never restate. Prose sites carry a dated number plus a pointer to this script;
this script carries none of its own.

Deliberately prints no verdict and exits 0 on a readable corpus — it is an instrument, not a
gate. The gates are in founder-skills/tests/test_cowork_cassette_replay.py.

Run:  python cowork-tests/cassette_inventory.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASSETTE_DIR = HERE / "cassettes"
SCENARIOS_DIR = HERE / "scenarios"


def main() -> int:
    cassettes = sorted(CASSETTE_DIR.glob("*.cassette.json"))
    scenarios = sorted(SCENARIOS_DIR.glob("*.yaml"))

    harness: Counter[str] = Counter()
    fmt: Counter[str] = Counter()
    for path in cassettes:
        data = json.loads(path.read_text(encoding="utf-8"))
        harness[str((data.get("environment") or {}).get("harnessVersion", "MISSING"))] += 1
        fmt[str(data.get("cassetteVersion", "MISSING"))] += 1

    cassette_names = {p.name[: -len(".cassette.json")] for p in cassettes}
    uncassetted = sorted({p.stem for p in scenarios} - cassette_names)

    print(f"cassettes: {len(cassettes)}   scenarios: {len(scenarios)}")

    print("\nenvironment.harnessVersion:")
    for version, count in sorted(harness.items()):
        print(f"  {version:>10}  {count}")

    print("\ncassetteVersion:")
    for version, count in sorted(fmt.items()):
        print(f"  {version:>10}  {count}")

    print(f"\nun-cassetted scenarios: {len(uncassetted)}")
    for name in uncassetted:
        print(f"  {name}")
    print(
        "\n(Reasons for each un-cassetted scenario, and the parity gate itself, live in\n"
        " _NO_CASSETTE_ALLOWLIST in founder-skills/tests/test_cowork_cassette_replay.py.)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
