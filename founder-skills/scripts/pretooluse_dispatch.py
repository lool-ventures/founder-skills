#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""PreToolUse on Agent/Task: one process runs every dispatch check, the first hold wins.

Every dispatch in every session with the plugin starts this, so the checks share one python start
rather than one each, and each returns at its own prefix test before reading anything. Fails open:
any error, any unexpected shape, exit 0 with no stdout and one stderr line.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import Any

# The agent check runs first: a dispatch addressed to the wrong agent is answered with the agent to
# name before anything is compared against its prompt.
CHECKS = ("dispatch_type_check", "two_figures_check", "dispatch_prompt_check")


def _load(name: str) -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            for name in CHECKS:
                try:
                    decision = _load(name).decide(payload)
                except Exception as e:  # noqa: BLE001 - one broken check must not silence the other
                    print(f"pretooluse_dispatch: {name}: {type(e).__name__}: {e}", file=sys.stderr)
                    continue
                if decision is not None:
                    sys.stdout.write(json.dumps(decision))
                    break
    except Exception as e:  # noqa: BLE001 - a hook that crashes holds nothing and confuses everyone
        print(f"pretooluse_dispatch: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
