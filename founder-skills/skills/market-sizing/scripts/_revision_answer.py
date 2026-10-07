"""Step 6d's revise-or-deliver answer: which findings ask the question, and what counts as its record.

One owner for both sides: `record_revision_answer.py` writes the record, `compose_report.py` reads it,
and both decide "does this review ask the question" with `qualifying_parameters`. Two copies of that
rule would let the recorder accept a record compose then refuses, or the reverse.
"""

from __future__ import annotations

import json
import os
from typing import Any

FILENAME = "revision_answer.json"
ANSWERS = ("deliver", "revise")
# `founder`: the question was put to the founder. `no_questions`: the founder asked not to be asked, so
# option 1 was taken (Step 6d); the answer is still recorded, or that run would read as "never offered".
# `host`: the request that started the run answered it (`FS_HOST_ANSWER ms_revision=deliver`), applied by
# `record_revision_answer.py --from-pre-answer` from the run's ledger.
SOURCES = ("founder", "no_questions", "host")


def qualifying_parameters(redteam: Any) -> list[str]:
    """The parameters named by the review's accepted `high` findings -- the findings that ask the question.

    Accepted findings only: `rejected` ones never reach the founder. Any named parameter counts, not only
    a founder-stated one; Step 6d asks whenever a high finding names a parameter.
    """
    if not isinstance(redteam, dict):
        return []
    out = {
        f["parameter"].strip()
        for f in redteam.get("findings") or []
        if isinstance(f, dict)
        and f.get("severity") == "high"
        and isinstance(f.get("parameter"), str)
        and f["parameter"].strip()
    }
    return sorted(out)


def record_path(analysis_dir: str, run_id: str) -> str:
    return os.path.join(analysis_dir, "handoff", run_id, FILENAME)


def recorded(analysis_dir: str, run_id: str, parameters: list[str]) -> bool:
    """Is there an answer for THIS run's findings? A record from an earlier run of the same slug, or one
    written for other findings, is not an answer to the question these findings ask."""
    try:
        with open(record_path(analysis_dir, run_id), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(rec, dict):
        return False
    meta = rec.get("metadata")
    covered = rec.get("parameters")
    return (
        isinstance(meta, dict)
        and meta.get("run_id") == run_id
        and rec.get("answer") in ANSWERS
        and rec.get("source") in SOURCES
        and isinstance(covered, list)
        and set(parameters) <= {p for p in covered if isinstance(p, str)}
    )
