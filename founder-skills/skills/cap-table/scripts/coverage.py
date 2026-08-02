#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Coverage registry loader + the pure is_covered() decision rule.

A deal is `covered` iff every required primitive is usable, every multi-primitive
combination is expressible via priced_round.couples or a flip combinable_via_sequence
route, AND no required pair appears in incompatible_couples. See design spec §3.1.
"""

from __future__ import annotations

import json
import os
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_REGISTRY = os.path.join(_HERE, "..", "references", "coverage.json")


def load_registry(path: str | None = None) -> dict[str, Any]:
    with open(path or _REGISTRY, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def is_covered(required: list[str], registry: dict[str, Any]) -> dict[str, Any]:
    prims = registry["primitives"]
    uncovered: list[dict[str, Any]] = []

    # (1) each required primitive must be usable.
    for name in required:
        spec = prims.get(name)
        if spec is None:
            uncovered.append({"primitive": name, "reason": "unknown primitive"})
            continue
        comp = spec.get("completeness")
        if comp == "not_covered":
            uncovered.append({"primitive": name, "reason": "not_covered"})
        elif comp == "structural_only":
            # usable standalone, or in a combinable_via_sequence pairing.
            combinable = set(spec.get("combinable_via_sequence", []))
            others = [r for r in required if r != name]
            if others and not combinable.issuperset(_round_like(others, prims)):
                uncovered.append(
                    {"primitive": name, "reason": "structural_only not combinable with " + ",".join(others)}
                )

    # (2) no required pair may appear in any incompatible_couples list.
    req_set = set(required)
    for spec in prims.values():
        for pair in spec.get("incompatible_couples", []):
            if set(pair).issubset(req_set):
                uncovered.append({"combination": list(pair), "reason": "declared incompatible"})

    covered = len(uncovered) == 0
    return {"covered": covered, "uncovered_parts": uncovered}


def _round_like(others: list[str], prims: dict[str, Any]) -> set[str]:
    """The subset of `others` that a structural_only primitive must be sequence-combinable with.
    For flip the only supported partner is priced_round; couplings carried *inside* priced_round
    (safe/note/pool/AD/acquisition) ride along with it and are not separately sequence-gated."""
    coupled = set(prims.get("priced_round", {}).get("couples", []))
    return {o for o in others if o not in coupled}
