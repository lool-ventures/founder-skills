"""Replay kept deck-review checklists through the arithmetic scoring of `numbers_consistent`.

NOT a test module (no `test_` prefix, so pytest does not collect it) -- a tool, because the data it
reads is machine-local: kept run dirs (`cowork-harness` runs, downloaded CI artifacts, local e2e
workdirs), which exist on a developer's machine and not in CI. Nothing it reads is committed.

WHY IT EXISTS. Scoring `numbers_consistent` from the reconciliation instead of the reviewer's
reading is a scoring change, and the CHANGELOG's "expected movement" line has to be a measurement
someone can re-run, not a number with no stated roots or dedup rule. This is that measurement.

What it does, per kept run dir holding both `checklist.json` and a `reconciliation.json` with the
SAME run id:
  * BEFORE: the stored items, summary recomputed by today's `checklist.py` (so the zero-weight
    competition mirror applies to both arms and the delta is this change alone);
  * AFTER: the same items with `_apply_numeric_scoring` applied.
Checklists are deduplicated by content hash (one run is often kept in several places). Run dirs are
printed by that hash only, never by path: a path carries the company's name.

It imports the PRODUCTION scorer rather than restating the rule, so it measures what ships.

    python3 founder-skills/tests/numbers_consistent_corpus.py [EXTRA_GLOB ...]

EXTRA_GLOB: more `**/checklist.json` globs to scan (e.g. a folder of downloaded CI artifacts).
"""

from __future__ import annotations

import collections
import copy
import glob
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "scripts"

#: Where kept run dirs live by default. Machine-local by nature.
DEFAULT_GLOBS = ("~/.cowork-harness/runs/**/checklist.json",)


def load_scorer() -> Any:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("dr_checklist_corpus", SCRIPTS / "checklist.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _run_id(data: dict[str, Any]) -> Any:
    meta = data.get("metadata")
    return meta.get("run_id") if isinstance(meta, dict) else None


def harvest(globs: list[str]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(content hash, checklist, reconciliation) per distinct deck-review checklist with a same-run reconciliation."""
    seen: set[str] = set()
    pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for pattern in globs:
        for path in sorted(glob.glob(os.path.expanduser(pattern), recursive=True)):
            if "deck-review" not in path:
                continue
            checklist = _read(path)
            recon = _read(os.path.join(os.path.dirname(path), "reconciliation.json"))
            if checklist is None or recon is None or not isinstance(checklist.get("items"), list):
                continue
            if not _run_id(checklist) or _run_id(checklist) != _run_id(recon):
                continue
            digest = hashlib.sha256(json.dumps(checklist, sort_keys=True).encode("utf-8")).hexdigest()[:10]
            if digest in seen:
                continue
            seen.add(digest)
            pairs.append((digest, checklist, recon))
    return pairs


def _status(items: list[dict[str, Any]]) -> str:
    return str(next((i.get("status") for i in items if i.get("id") == "numbers_consistent"), "?"))


def replay(scorer: Any, checklist: dict[str, Any], recon: dict[str, Any]) -> dict[str, Any]:
    before_items = copy.deepcopy([i for i in checklist["items"] if isinstance(i, dict)])
    before = scorer._recompute_summary(before_items)
    after_result = {"items": copy.deepcopy(before_items), "summary": before}
    after_result = scorer._apply_numeric_scoring(after_result, recon)
    after = after_result["summary"]
    return {
        "reconciliation": recon.get("status"),
        "comparisons": scorer.count_comparisons(recon),
        "status": (_status(before_items), _status(after_result["items"])),
        "score": (before["score_pct"], after["score_pct"]),
        "band": (before["overall_status"], after["overall_status"]),
    }


def main(argv: list[str]) -> int:
    scorer = load_scorer()
    pairs = harvest(list(DEFAULT_GLOBS) + argv)
    if not pairs:
        print("No kept deck-review checklist with a same-run reconciliation was found.")
        return 0
    moves: collections.Counter[str] = collections.Counter()
    deltas: list[float] = []
    band_changes = 0
    for digest, checklist, recon in pairs:
        row = replay(scorer, checklist, recon)
        old, new = row["status"]
        delta = round(row["score"][1] - row["score"][0], 1)
        deltas.append(delta)
        if old != new:
            moves[f"{old}->{new}"] += 1
        if row["band"][0] != row["band"][1]:
            band_changes += 1
        print(
            f"{digest}  recon={row['reconciliation']:<11} comparisons={row['comparisons']:<3} "
            f"numbers_consistent {old:>14} -> {new:<14} score {row['score'][0]:>5} -> {row['score'][1]:<5} "
            f"({delta:+}) band {row['band'][0]} -> {row['band'][1]}"
        )
    checked = sum(1 for _d, _c, r in pairs if r.get("status") == "checked")
    print()
    print(f"distinct checklists with a same-run reconciliation: {len(pairs)} ({checked} checked)")
    print(f"numbers_consistent moves: {sum(moves.values())} {dict(sorted(moves.items()))}")
    print(f"score delta: min {min(deltas):+} max {max(deltas):+} mean {sum(deltas) / len(deltas):+.2f}")
    print(f"band changes: {band_changes}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
