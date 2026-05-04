"""Tolerant JSON extraction from sub-agent final messages.

Used by tests; the SKILL.md prose tells the main-thread model to apply
this protocol when parsing sub-agent replies. The model can do this
mentally; the Python implementation is for testability.
"""

from __future__ import annotations

import json
import re


def extract_dispatch_json(agent_final_message: str) -> dict:  # type: ignore[type-arg]
    """Tolerant JSON extraction from a sub-agent's final assistant message.

    Handles three common shapes:
    1. Raw JSON: `{"a": 1}`
    2. Fenced JSON: ` ```json\\n{"a": 1}\\n``` `
    3. JSON embedded in prose: `Here is the result: {"a": 1}\\nLet me know...`

    Uses json.JSONDecoder.raw_decode to advance through the buffer and find
    the first balanced JSON object. Correct on nested objects and string
    values containing braces.

    Raises ValueError if no parseable JSON object found.
    """
    text = agent_final_message.strip()

    # 1. If wrapped in ```json ... ``` (or plain ``` ... ```) fence, strip it.
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    decoder = json.JSONDecoder()

    # 2. Try direct parse via raw_decode.
    try:
        obj, _idx = decoder.raw_decode(text)
        if isinstance(obj, dict):
            return obj  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass

    # 3. Walk through the text, finding each '{' and trying raw_decode there.
    for i in range(len(text)):
        if text[i] != "{":
            continue
        try:
            obj, _idx = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj  # type: ignore[return-value]
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not extract JSON object from sub-agent reply:\n{text[:500]}")
