"""Single source of truth for the rule-pack version.

Reads ``metadata.version`` from ``../data/cap-table-rules.json`` at import
time and exposes it as ``RULE_PACK_VERSION``. Every math producer and report
footer binds to this constant instead of hardcoding a literal, so a rule-pack
version bump propagates without touching each script.

Defensive by contract: a missing/unreadable/malformed rule pack must never
crash a script at import. On any failure the module falls back to a hardcoded
version string.
"""

from __future__ import annotations

import json
import os

_FALLBACK_VERSION = "0.4.1"


def _read_rule_pack_version() -> str:
    """Return metadata.version from the shipped rule pack, or the fallback."""
    rules_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "data",
        "cap-table-rules.json",
    )
    try:
        with open(rules_path, encoding="utf-8") as fh:
            data = json.load(fh)
        version = data.get("metadata", {}).get("version")
        if isinstance(version, str) and version.strip():
            return version
    except Exception:
        # Never crash a producer on a doc read; fall through to the fallback.
        pass
    return _FALLBACK_VERSION


RULE_PACK_VERSION: str = _read_rule_pack_version()
