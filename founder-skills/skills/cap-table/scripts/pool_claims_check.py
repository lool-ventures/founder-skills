#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check the coaching commentary's option-pool sizing claims before it is inserted into report.md.

The commentary does not discuss the pool's sizing -- each scenario's Option pool section does -- but a coach can
still write about it. This runs the same judge the paid cap-table lanes use (`_pool_sizing_claims.py`, held
byte-identical to the tests' copy) on the commentary, against the run's computed figures, and is the step that
writes the only file `pool_check_release.py` releases to `insert_coaching.py`: a run that skips it has nothing
to insert. The file it writes is deliberately not insert_coaching's envelope (`checked_commentary_markdown`, not
`commentary_markdown`), so fed to insert_coaching directly it is refused.

    pool_claims_check.py coaching.md --scenarios scenarios.json -o coaching.checked.json

Exit 0: the checked file is written (clean, not judged, stripped, or the check could not run once it had this
run's figures -- past that point it never blocks delivery). Exit 2: this run's scenarios.json is missing, unreadable
or carries no run_id; nothing is written but a `refused` record, so a mistyped path cannot skip the judge. Exit 9:
findings; the segments are on stdout as JSON and nothing is written, so the main thread makes ONE corrective dispatch
naming them, then runs this again, with `--strip` if they are still there. `--strip` removes each flagged claim with
its bullet or paragraph (and a lead-in or heading left with nothing under it), adds one founder-facing line saying
so, and leaves `coaching.md` as it was.

Every run writes `<coaching.md>.pool-check.json`: {run_id, sha256 of coaching.md, scenarios_sha256 of the
scenarios.json it judged against, action, findings, reason, output_sha256 of the file it wrote}. When the
check cannot run after reading the run, it passes the commentary through with ERROR_NOTE appended, and the
record carries `code: POOL_CHECK_NOT_RUN`, `severity: medium`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pool_sizing_claims as judge  # noqa: E402
import _pool_text  # noqa: E402

EXIT_FINDINGS = 9
# Not insert_coaching's key: only pool_check_release.py turns this file into the envelope it reads.
CHECKED_KEY = "checked_commentary_markdown"
STRIP_NOTE = (
    "What this commentary said about the option pool that could not be checked against the computed figures was "
    "removed; each scenario's Option pool section in this report is the reference."
)
# When the check cannot run, the commentary still goes in, but not as if it had passed: the founder reads this line
# (compose ran before the commentary existed, so no report warning can say it), and the record carries the code.
ERROR_NOTE = (
    "What this commentary says about the option pool could not be checked against the computed figures for this "
    "report; each scenario's Option pool section in this report is the reference."
)
_JUDGED_BASES = frozenset({"post_money", "pre_money"})
NO_POOL_TARGET = "no scenario has a pool target"


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def modeled_basis(scenarios_doc: dict[str, Any]) -> tuple[str | None, str]:
    """The one basis every pool scenario was solved on, or (None, why the judge cannot take this run)."""
    bases = set()
    for s in scenarios_doc.get("scenarios") or []:
        params, co = (s or {}).get("parameters") or {}, (s or {}).get("computed_outputs") or {}
        if params.get("target_pool_percent"):
            bases.add(_pool_text._solved_pool_basis(params, co))
    if not bases:
        return None, NO_POOL_TARGET
    if len(bases) > 1:
        return None, "the scenarios were solved on different pool bases"
    basis = next(iter(bases))
    if basis not in _JUDGED_BASES:
        return None, f"the judge takes a post-money or pre-money pool, not {basis or 'an unmodelled basis'}"
    return basis, ""


def exempt_text(scenarios_doc: dict[str, Any], cap_state: dict[str, Any]) -> str:
    """What this run's Option pool sections say, rebuilt from its scenarios with the builder that renders them.
    Rebuilt, never parsed out of a report: a report is text the commentary can imitate (its heading) or already
    contain (a resume), and either exempted everything after it."""
    return "\n".join(
        "\n".join(_pool_text.pool_section_markdown(_pool_text.pool_section(s, cap_state)))
        for s in scenarios_doc.get("scenarios") or []
        if isinstance(s, dict)
    )


def findings_for(
    commentary: str, scenarios_doc: dict[str, Any], basis: str, cap_state: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """The judge's findings, less any segment this run's own Option pool sections state."""
    report_segments = set(judge._segments(exempt_text(scenarios_doc, cap_state or {})))
    found = judge.pool_sizing_findings(commentary, modeled_basis=basis, **judge.judge_arguments(scenarios_doc))
    return [f for f in found if f["segment"] not in report_segments]


# Entirely bold, and not ending like a sentence: a bolded takeaway ("**... this round.**", "**... (before
# signing).**") is content. A closing parenthesis counts as a sentence end: "(...)" rarely closes a heading.
_BOLD_LINE = re.compile(r"\*\*[^*\n]*[^*\n.!?)]\*\*:?")


def _is_heading(block: str) -> bool:
    """A markdown heading, or a line that is entirely bold and not a sentence -- which reads as one."""
    b = block.strip()
    return b.startswith("#") or bool(_BOLD_LINE.fullmatch(b))


def _blocks(commentary: str) -> list[tuple[str, int, int]]:
    """Blank-line blocks as (text, start, end) over `commentary`, with a heading line that opens a longer block
    split off it, so the heading's fate is decided on its own."""
    out: list[tuple[str, int, int]] = []
    pos = 0
    for b in re.split(r"\n\s*\n", commentary):
        at = commentary.index(b, pos)
        pos = at + len(b)
        first, sep, rest = b.partition("\n")
        if sep and rest.strip() and _is_heading(first):
            out.append((first, at, at + len(first)))
            out.append((rest, at + len(first) + 1, at + len(b)))
        else:
            out.append((b, at, at + len(b)))
    return out


def _hit(findings: list[dict[str, Any]], start: int, end: int) -> bool:
    return any(f["start"] < end and f["end"] > start for f in findings)


def strip(commentary: str, findings: list[dict[str, Any]]) -> str:
    """Remove each flagged claim, then whatever introduced only it, then add STRIP_NOTE once, at the end.

    A block with bullet lines loses only its flagged lines; its lead-in (a line ending ":") goes only when no
    bullet under it survives. A prose block that carries a flagged claim goes whole. A heading (a `#` line, or a
    line that is entirely bold) is its own block even when no blank line follows it, and goes only when no block
    survives under it before the next heading; a lead-in block (ending ":") goes when the block it
    introduced went.
    """
    kept: list[str | None] = []
    for b, b_start, b_end in _blocks(commentary):
        if not _hit(findings, b_start, b_end):
            kept.append(b)
            continue
        lines = b.split("\n")
        if not any(judge._BULLET.match(ln) for ln in lines):
            kept.append(None)
            continue
        line_at, out = b_start, []
        for ln in lines:
            if not _hit(findings, line_at, line_at + len(ln)):
                out.append(ln)
            line_at += len(ln) + 1
        if not any(judge._BULLET.match(ln) for ln in out):
            out = [ln for ln in out if not ln.rstrip().endswith(":")]
        kept.append("\n".join(out) if any(x.strip() for x in out) else None)
    result: list[str] = []
    for i, k_b in enumerate(kept):
        if k_b is None:
            continue
        b = k_b
        if _is_heading(b):
            under = []
            for k in kept[i + 1 :]:
                if k is not None and _is_heading(k):
                    break
                under.append(k)
            if under and all(k is None for k in under):
                continue
        elif b.rstrip().endswith(":") and i + 1 < len(kept) and kept[i + 1] is None:
            continue
        result.append(b)
    body = "\n\n".join(result).strip()
    return f"{body}\n\n{STRIP_NOTE}\n" if body else f"{STRIP_NOTE}\n"


def _refuse_input(record: dict[str, Any], record_path: str, reason: str) -> int:
    """Exit 2 with the reason on stdout and stderr, -o untouched, and a record the release will not pass."""
    record.update(action="refused", reason=reason)
    _write_json(record_path, record)
    print(json.dumps({"status": "refused", "reason": reason}))
    print(f"pool_claims_check: refused: {reason}", file=sys.stderr)
    return 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("coaching_md")
    p.add_argument("--scenarios", required=True)
    p.add_argument("-o", "--output", required=True, help="the checked commentary envelope insert_coaching.py reads")
    p.add_argument("--strip", action="store_true", help="remove flagged claims instead of reporting them")
    a = p.parse_args()
    record_path = f"{a.coaching_md}.pool-check.json"
    with open(a.coaching_md, encoding="utf-8") as f:
        commentary = f.read()
    record: dict[str, Any] = {"run_id": None, "sha256": _sha256(a.coaching_md), "findings": [], "reason": ""}
    # This run's figures, or a refusal. Failing open here would let a mistyped path skip the judge, so only a check
    # that has read the run may pass the commentary through without judging it.
    try:
        with open(a.scenarios, encoding="utf-8") as f:
            scenarios_doc = json.load(f)
        run_id = (scenarios_doc.get("metadata") or {}).get("run_id")
    except (OSError, ValueError, AttributeError) as e:
        return _refuse_input(record, record_path, f"cannot read this run's scenarios.json ({type(e).__name__}: {e})")
    if not isinstance(run_id, str) or not run_id:
        return _refuse_input(record, record_path, "this run's scenarios.json carries no metadata.run_id")
    record["run_id"] = run_id
    # The figures the claims were judged against: a what-if that re-solves the scenarios makes this record stale,
    # so neither the release nor the insert takes it for the new figures.
    record["scenarios_sha256"] = _sha256(a.scenarios)
    try:
        # The pool sections' acquisition note reads the pre-round snapshot beside scenarios.json when a scenario
        # carries none of its own; without it the note is rebuilt from the scenario alone.
        cap_state: dict[str, Any] = {}
        cs_path = os.path.join(os.path.dirname(os.path.abspath(a.scenarios)), "cap_state.json")
        if os.path.isfile(cs_path):
            with open(cs_path, encoding="utf-8") as f:
                cap_state = json.load(f)
        basis, why = modeled_basis(scenarios_doc)
        found: list[dict[str, Any]] = []
        if basis is None and why == NO_POOL_TARGET:
            record.update(action="no_pool_target", reason=why)
        elif basis is None:
            # Not judged is not passed: the founder is told, exactly as when the check cannot run.
            record.update(action="not_judged", reason=why, code="POOL_CHECK_NOT_RUN", severity="medium")
        else:
            found = findings_for(commentary, scenarios_doc, basis, cap_state)
            record["findings"] = [{"segment": f["segment"], "reason": f["reason"]} for f in found]
            record["action"] = "clean" if not found else ("stripped" if a.strip else "findings")
    except Exception as e:  # noqa: BLE001 -- the check never blocks delivery; the record says it could not run
        print(
            f"pool_claims_check: could not check the commentary ({type(e).__name__}: {e}); passing it through",
            file=sys.stderr,
        )
        record.update(action="error", reason=f"{type(e).__name__}: {e}", code="POOL_CHECK_NOT_RUN", severity="medium")
        found = []
    _write_json(record_path, record)
    if record["action"] == "findings":
        print(json.dumps({"status": "findings", "findings": record["findings"]}, indent=2))
        return EXIT_FINDINGS
    if record["action"] == "stripped":
        text = strip(commentary, found)
    elif record["action"] in {"error", "not_judged"}:
        text = f"{commentary.rstrip()}\n\n{ERROR_NOTE}\n"
    else:
        text = commentary
    _write_json(a.output, {CHECKED_KEY: text})
    record["output_sha256"] = _sha256(a.output)
    # What insert_coaching compares the commentary against, when the report declares it needs this record.
    record["checked_commentary_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _write_json(record_path, record)
    print(json.dumps({"status": record["action"], "output_path": a.output, "record": record_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
