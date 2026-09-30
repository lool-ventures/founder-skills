"""Keep the first scored copy of a producer's output for this run, beside the output.

A score is re-piped after a founder corrects it at a gate, and the model then stamps the corrected
value `founder_override`. The same stamp was measured on a FIRST-pass moat rating, where the scoring
sub-agent had no founder input at all, and the report told the founder they had overridden a rating
they never saw. The stamp is model-written, so it cannot be what makes the report say "you changed
this". What can is a comparison with the value as first scored: this module keeps that value.

The copy is `<output>.first.json`, written only when none exists for this run (earliest wins). A
later re-pipe never replaces it, so re-running the producer cannot erase the difference it exists
to show. Written best-effort: a copy that cannot be written costs the "Founder Override" label
(renderers then show no override at all), never the producer's own output.
"""

from __future__ import annotations

import json
import os
from typing import Any


def first_copy_path(output_path: str) -> str:
    return f"{output_path}.first.json"


def _run_id(data: Any) -> Any:
    meta = data.get("metadata") if isinstance(data, dict) else None
    return meta.get("run_id") if isinstance(meta, dict) else None


def keep_first(output_path: str, result: dict[str, Any]) -> None:
    """Write `result` as the run's first copy unless one for the same run already exists."""
    path = first_copy_path(output_path)
    try:
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = None
    if existing is not None and _run_id(existing) == _run_id(result):
        return
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass
