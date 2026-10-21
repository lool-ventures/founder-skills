"""The two inputs `slide_reviews.py` needs beside the reconciliation, for tests that only want a slide reviews file.

`slide_reviews.py` takes `--ledger` and `--deck-text` with `--reconciliation`: together they decide whether
Step 3.95's machine-read check had to run. A ledger with no figures and a text-only deck text say it did not, so
a test that is about something else gets the producer's old behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path


def slide_review_inputs(directory: str | Path, run_id: str) -> list[str]:
    """Write a figure-free ledger and a deck text for `run_id` under `directory` (beside, never over, a test's
    own files); return the `--ledger` / `--deck-text` arguments."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    ledger = d / f"sr-ledger-{run_id}.json"
    ledger.write_text(json.dumps({"figures": [], "metadata": {"run_id": run_id}}), encoding="utf-8")
    deck_text = d / f"sr-deck-text-{run_id}.md"
    deck_text.write_text(
        f"---\nrun_id: {run_id}\nsource: pasted\npages_source: {{1: pasted}}\n---\n## Slide 1\n\nText\n",
        encoding="utf-8",
    )
    return ["--ledger", str(ledger), "--deck-text", str(deck_text)]
