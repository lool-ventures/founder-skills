"""No step writes its output over one of the files it reads.

A producer asked to save its result (`-o`, `--write-md`, `--output-json`, ...) onto one of its own inputs used to
do it: the input was read, then replaced by the output, and the run went on from a file that no longer held what
the earlier step wrote. `refuse_output_onto_input` is called first in each writer's `main`, right after its
arguments are parsed and before any gate, ledger or file is touched, and refuses that call: stdout carries
`{"status": "rejected", "code": "OUTPUT_IS_INPUT", ...}`, one line goes to stderr, the exit code is 1, and
nothing is written. On every other call it returns without printing anything.

What counts as an input:
- every token of the command line (and the value of each `--flag=value`) that names an existing regular file,
  once each output's own occurrence is set aside. stdin is never an input, so a documented in-place fix that
  reads stdin and writes back the same file stays legal; a directory is never an input either;
- `extra`: files the script reads that its command line does not name, such as the artifacts a compose reads
  from `--dir`.
A match is a path that resolves to the same file (`realpath`), or, when both exist, the same inode (a hard
link, or a case variant on a case-folding volume). Two outputs naming one file are refused too.

`in_place`: inputs the script reads in full and then rewrites through its output by design (market-sizing's
documented `market_sizing.py --replay sizing.json ... -o sizing.json`). An output naming one of them is not
refused; anything else still is.

`protect`: for a writer whose `-o` is a receipt beside a store it edits, an existing `-o` is also refused
when it is one of the skill's canonical artifacts (`protect` lists their paths) or a JSON object carrying
`metadata.run_id`, which every canonical artifact does and no receipt does. A receipt from an earlier call
is not refused, so the documented reuse of one receipt path for several documents keeps working.

The plugin-root `scripts/` holds the canonical copy and every skill's `scripts/` an identical one (skill scripts
run by path and cannot import across directories); a test holds the copies equal.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Sequence

CODE = "OUTPUT_IS_INPUT"


def _tokens(argv: Sequence[str]) -> list[str]:
    out: list[str] = []
    for tok in argv:
        out.append(tok)
        if tok.startswith("-") and "=" in tok:
            out.append(tok.split("=", 1)[1])
    return out


def _same(a: str, b: str) -> bool:
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    if os.path.exists(a) and os.path.exists(b):
        try:
            return os.path.samefile(a, b)
        except OSError:
            return False
    return False


def _is_run_artifact(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    meta = data.get("metadata") if isinstance(data, dict) else None
    return isinstance(meta, dict) and "run_id" in meta


def find_collision(
    outputs: Iterable[str | None],
    *,
    argv: Sequence[str] | None = None,
    extra: Iterable[str | None] = (),
    protect: Iterable[str] | None = None,
    in_place: Iterable[str | None] = (),
) -> tuple[str, str, str] | None:
    """(output, the file it collides with, why) for the first collision, else None. Reads no file except
    an existing output when `protect` is given."""
    outs = [o for o in outputs if o]
    if not outs:
        return None
    remaining = _tokens(sys.argv[1:] if argv is None else argv)
    for o in outs:
        if o in remaining:
            remaining.remove(o)
    inputs = [t for t in remaining if os.path.isfile(t)]
    inputs += [e for e in extra if e and os.path.isfile(e)]
    rewritten = [p for p in in_place if p]
    inputs = [i for i in inputs if not any(_same(i, p) for p in rewritten)]
    for i, o in enumerate(outs):
        for other in outs[i + 1 :]:
            if _same(o, other):
                return o, other, "output"
        for path in inputs:
            if _same(o, path):
                return o, path, "input"
        protected = protect is not None and os.path.isfile(o)
        if protected and (any(_same(o, p) for p in protect or ()) or _is_run_artifact(o)):
            return o, o, "artifact"
    return None


def refuse_output_onto_input(
    outputs: Iterable[str | None],
    *,
    script: str,
    argv: Sequence[str] | None = None,
    extra: Iterable[str | None] = (),
    protect: Iterable[str] | None = None,
    in_place: Iterable[str | None] = (),
) -> None:
    """Exit 1 `OUTPUT_IS_INPUT`, writing nothing, when an output names one of this call's inputs (or, with
    `protect`, an existing analysis file). Returns silently otherwise."""
    hit = find_collision(outputs, argv=argv, extra=extra, protect=protect, in_place=in_place)
    if hit is None:
        return
    out, other, why = hit
    out_abs, other_abs = os.path.abspath(out), os.path.abspath(other)
    if why == "artifact":
        what = f"{out_abs}, an existing analysis file this step does not write"
    elif why == "output":
        what = f"{other_abs}, which another output of this call also names"
    else:
        what = f"{other_abs}, one of this step's own inputs"
    message = (
        f"the output path names {what}; drop the output flag, or point it at a new file, never at a file this "
        "step reads"
    )
    body = {"status": "rejected", "code": "OUTPUT_IS_INPUT", "message": message, "output": out_abs, "input": other_abs}
    sys.stdout.write(json.dumps(body) + "\n")
    print(f"Error: {script}: the output names {what}; nothing was written", file=sys.stderr)
    sys.exit(1)
