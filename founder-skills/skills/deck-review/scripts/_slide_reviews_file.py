"""Whether this run's slide_reviews.json is usable, and its read token.

Two readers share the "is the file usable" half. `checklist.py` refuses a grade (`SLIDE_REVIEWS_MISSING`) when
the file is not usable, then compares the grade's echo with `token(...)`. `dr_dispatch_prompt.py` refuses to
print the CHECKLIST prompt until the file is usable, and imports only `usable`: the token is the proof that the
grader read the file, so the generator never reads it, prints it, or prints anything derived from it.

The token COMPARISON stays in `checklist.py`; this module only says whether the file is there for this run.
"""

from __future__ import annotations

import json
from typing import Any


def _load(path: str) -> tuple[Any, str | None]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "does not exist"
    except (OSError, ValueError):
        return None, "cannot be read as JSON"


def _meta(data: Any) -> dict[str, Any]:
    meta = data.get("metadata") if isinstance(data, dict) else None
    return meta if isinstance(meta, dict) else {}


def usable(path: str, run_id: str) -> tuple[bool, str | None]:
    """(ok, problem): the slide reviews at `path` are this run's and carry a read token. `problem` says why
    not, as the end of a sentence that starts "the slide reviews at <path> ..."."""
    data, problem = _load(path)
    if problem is None:
        token = _meta(data).get("read_token")
        if not isinstance(data, dict):
            problem = "is not a JSON object"
        elif data.get("skipped") is True:
            problem = "is a skipped stub, not slide reviews"
        elif _meta(data).get("run_id") != run_id:
            problem = "belongs to another run"
        elif not isinstance(token, str) or not token:
            problem = "carries no read token (it was not written by this version's slide-reviews step)"
    return problem is None, problem


def token(path: str, run_id: str) -> str:
    """The read token of a usable file. ValueError when the file is not usable."""
    ok, problem = usable(path, run_id)
    if not ok:
        raise ValueError(f"the slide reviews at {path} {problem}")
    data, _ = _load(path)
    return str(_meta(data)["read_token"])
