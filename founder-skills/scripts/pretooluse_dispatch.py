#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""PreToolUse on Agent/Task/AskUserQuestion: one process runs every check, the first hold wins.

Every dispatch and every question in every session with the plugin starts this, so the checks share one
python start rather than one each, and each returns at its own tool-name and prefix tests before
reading anything. Fails open:
any error, any unexpected shape, exit 0 with no stdout and one stderr line.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import Any

# The agent check runs first: a dispatch addressed to the wrong agent is answered with the agent to
# name before anything is compared against its prompt. The asked-gate check comes next and before the
# figures check: on a market-sizing sizing dispatch it decides both questions in one hold. The holds come
# before the prompt check, so a step that must wait for a question is held rather than rewritten.
# The no-ask check comes before the review-page check: in a run whose request said not to ask, no question
# is put at all, so the review page's "send it first, then ask again" never applies there.
# The question check answers only AskUserQuestion, and every dispatch check only Agent/Task: each returns
# at its own tool-name test, so the order between the two groups decides nothing.
CHECKS = (
    "dispatch_type_check",
    "asked_gate_check",
    "two_figures_check",
    "dispatch_prompt_check",
    "no_ask_check",
    "review_page_check",
)


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
