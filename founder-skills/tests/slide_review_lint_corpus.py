"""Replay kept deck-review slide reviews through `slide_reviews.py`'s numeric lint.

NOT a test module (no `test_` prefix, so pytest does not collect it) -- a tool, because the data it
reads is machine-local: kept run dirs (`cowork-harness` runs, downloaded CI artifacts, local e2e
workdirs), which exist on a developer's machine and not in CI. Nothing it reads is committed.

WHY IT EXISTS. The lint flags a slide review that says two figures disagree when the arithmetic did
not find that disagreement. It is warn-only because its vocabulary is an enumerated list, and an
enumerated list is porous both ways; whether it should ever do more than warn is a question of how
often it fires and how many of its unbacked hits are real. This is that measurement.

What it does, per kept run dir holding both `slide_reviews.json` and a `reconciliation.json` with the
SAME run id: runs `numeric_lint` and prints each hit as where it is, the phrase that matched, and
whether the arithmetic backs it. Slide reviews are deduplicated by content hash (one run is often kept
in several places). Runs are printed by that hash only, never by path, and a hit never by its text: a
path, and a reviewer's sentence, can carry the company's name and its figures. To judge an unbacked
hit, open the run's file locally.

It imports the PRODUCTION lint rather than restating the vocabulary, so it measures what ships.

    python3 founder-skills/tests/slide_review_lint_corpus.py [EXTRA_GLOB ...]

EXTRA_GLOB: more `**/slide_reviews.json` globs to scan (e.g. a folder of downloaded CI artifacts).
"""

from __future__ import annotations

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
DEFAULT_GLOBS = ("~/.cowork-harness/runs/**/slide_reviews.json",)


def load_lint() -> Any:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("dr_slide_reviews_corpus", SCRIPTS / "slide_reviews.py")
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
    """(content hash, slide reviews, reconciliation) per distinct slide review with a same-run reconciliation."""
    seen: set[str] = set()
    pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for pattern in globs:
        for path in sorted(glob.glob(os.path.expanduser(pattern), recursive=True)):
            if "/fixtures/" in path:
                continue
            reviews = _read(path)
            recon = _read(os.path.join(os.path.dirname(path), "reconciliation.json"))
            if reviews is None or recon is None or not isinstance(reviews.get("reviews"), list):
                continue
            if not _run_id(reviews) or _run_id(reviews) != _run_id(recon):
                continue
            digest = hashlib.sha256(json.dumps(reviews, sort_keys=True).encode("utf-8")).hexdigest()[:10]
            if digest in seen:
                continue
            seen.add(digest)
            pairs.append((digest, reviews, recon))
    return pairs


def main(argv: list[str]) -> int:
    lint = load_lint()
    pairs = harvest(list(DEFAULT_GLOBS) + argv)
    if not pairs:
        print("No kept deck-review slide review with a same-run reconciliation was found.")
        return 0
    hits_total = 0
    unbacked_total = 0
    runs_firing = 0
    for digest, reviews, recon in pairs:
        hits = lint.numeric_lint(reviews, recon)
        if hits:
            runs_firing += 1
        for hit in hits:
            hits_total += 1
            unbacked_total += 0 if hit["backed"] else 1
            print(f"{digest}  {'backed  ' if hit['backed'] else 'UNBACKED'}  {hit['where']:<40} {hit['phrase']!r}")
    print()
    print(f"distinct slide reviews with a same-run reconciliation: {len(pairs)} ({runs_firing} with a hit)")
    print(f"hits: {hits_total}  unbacked: {unbacked_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
