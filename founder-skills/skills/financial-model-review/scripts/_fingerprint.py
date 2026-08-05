"""Stable fingerprints of a producer's INPUTS, so a stale output can be detected.

run_id parity cannot see this class of staleness. Every artifact in a run shares one run_id, and
`apply_corrections.py` rewrites `inputs.json` WITHIN a run — so an output computed before the founder's
corrections and one computed after carry the same run_id and look consistent.

The comparison that works is against the CURRENT inputs: the verifier recomputes the fingerprint of
`inputs.json` as it stands now and checks each output's recorded value against it. Comparing outputs'
fingerprints to each other is not enough, because all of them can agree while all of them are stale.

`metadata` is excluded so that stamping a run_id is not itself a change of inputs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Recorded by each producer under this key, alongside metadata.run_id.
GRADED_AGAINST = "graded_against"


def fingerprint(data: Any) -> str:
    """Order-insensitive hash of a JSON-serialisable document, excluding `metadata`.

    Excluding `metadata` keeps a run_id stamp from reading as an inputs change. Everything else counts:
    for a financial model, a changed figure anywhere is a changed input, so there is no prose to strip
    the way a scored map has prose to strip.
    """
    material = data
    if isinstance(data, dict):
        material = {k: v for k, v in data.items() if k != "metadata"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fingerprint_file(path: str) -> str | None:
    """Fingerprint a JSON file on disk. None when missing or unparseable.

    None means "cannot compare", which a caller must not treat as a match.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return fingerprint(json.load(f))
    except (OSError, json.JSONDecodeError):
        return None


def stamp(result: dict[str, Any], dependencies: dict[str, Any]) -> None:
    """Record, on a producer's output, the fingerprint of each input it consumed.

    `dependencies` maps a dependency name (`inputs.json`) to the loaded document it was computed from.
    A dependency whose document is absent is recorded as None rather than omitted, so a later read can
    tell "this producer does not depend on it" from "it was missing when this ran".
    """
    if not dependencies:
        return
    result.setdefault(GRADED_AGAINST, {})
    for name, doc in dependencies.items():
        result[GRADED_AGAINST][name] = fingerprint(doc) if doc is not None else None


def stamp_hashes(result: dict[str, Any], hashes: dict[str, str | None]) -> None:
    """Record fingerprints that were computed EARLIER, before the producer ran.

    Prefer this over `stamp()` at the end of a producer. A compute step may MUTATE the document it was
    handed — `unit_economics._compute_metrics` adds `unit_economics.ltv` to its input — and hashing
    afterwards then fingerprints something that never existed on disk. The verifier hashes the file, so
    the two can never agree, and the result is a staleness error on a perfectly current artifact.

    That failure mode is worse than a missed detection: a false alarm on a gate with no documented
    remedy invites clearing it by editing the artifact, which is exactly what one live run did.
    """
    if not hashes:
        return
    result.setdefault(GRADED_AGAINST, {})
    for name, digest in hashes.items():
        result[GRADED_AGAINST][name] = digest
