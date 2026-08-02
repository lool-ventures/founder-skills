# /// script
# requires-python = ">=3.10"
# ///
"""Check that a run DELIVERED its complete deliverable set, not just some of it.

`test_skill_contract.py` pins that a SKILL.md *instructs* delivery. It cannot see
runtime behaviour, and prose guidance about model behaviour is exactly the class
this repo has shipped inert. This closes that gap from the other side: it reads a
completed run's `events.jsonl` and compares what was PRESENTED against what was
PRODUCED.

**Why this is not a scenario assert.** It would be better as one, and it cannot
be: `present_files_called: true` asserts that *at least one* file was presented
— "no count, no per-file match" (`dist/types.js`, re-verified against the
installed cowork-harness 1.17.0: still `z.literal(true)` describing "at least
one file was actually delivered ... (presentedFiles is non-empty)"). So it is
green both before and after a
partial-delivery fix, which is precisely the defect the fleet delivery
instruction exists to close. Until the assertion vocabulary can express a
per-file match, the durable check lives here and gets pointed at a run directory.

**The evidence is exact, which is why this is mechanical rather than a hand-read.**
A delivery records a `tool_use` whose input enumerates the set:

    {"files": [{"file_path": ".../mnt/outputs/Acme_IC_Simulation.md"},
               {"file_path": ".../mnt/outputs/Acme_IC_Simulation.html"}]}

**What counts as a deliverable is the skill's own definition, not this script's.**
Two shapes exist in this fleet and the checker must handle both, because assuming
the first silently blinds it to the second:

  1. **Root-copy skills** (five of six). Their Deliver step copies finished files
     to the workspace root, and ic-sim's states why: the root is "the level the
     founder sees as deliverable cards; `artifacts/` below it is working state".
     So every regular file at the outputs ROOT is a deliverable; everything below
     is working state and is ignored. Scanning below would fail every run on its
     own intermediates.
  2. **No-root-copy skills.** financial-model-review has no root copy at all — it
     presents `report.md` / `report.html` / `explore.html` by path from under its
     review dir. A root-only scan finds nothing for it, so a PARTIAL delivery
     would score PASS (`missing = {} - presented` is empty) — the checker would
     be blind to the exact defect it exists for, on one sixth of the fleet.

So: when the root holds deliverables, they are the set. When it does not, the
canonical deliverable basenames found below it are the set. That also covers a
root-copy skill whose copy step never ran — the files still exist, still should
have been handed over, and reporting that as "nothing produced" would hide a real
failure behind a NOT-EXERCISED.

**A delivery that errored is not a delivery.** Each `tool_use` is reconciled with
its `tool_result`; a call whose result is an error contributes nothing to the
presented set. Otherwise a hallucinated path or a permission failure would credit
its filenames and score PASS while the founder received nothing.

**Scope: founder-skills runs.** The rule it enforces — everything produced for
the founder gets handed over — is this fleet's delivery contract, not a
universal one. A generic probe or an ad-hoc run that leaves a file at the outputs
root without presenting it will FAIL, correctly by this contract and
meaninglessly for that run. Point it at founder-skills runs and read a FAIL
elsewhere as "not applicable". Detecting the difference automatically would mean
enumerating what counts as one of our runs, which is the kind of guess this repo
has learned not to encode.

Exit 0 = every produced deliverable was presented. Exit 1 = a violation. Exit 2 =
NOT-EXERCISED or evidence unavailable. Exit 2 is never a pass: a run that
delivered nothing proves nothing about delivery.

`<run-dir>` also accepts a single committed cassette file (`*.cassette.json`):
CI never spawns an agent (`replay` is a deterministic cassette playback), so
there is no live run directory for CI to point this at. A cassette's frozen
`events` array and `artifacts[].path` list are the same evidence a run dir
carries, read the same way `leak_scan.py` already reads a cassette's `events`.

    python3 cowork-tests/delivery_check.py <run-dir | cassette.json> [--require ic-sim] [--lane remote]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Iterator
from typing import Any

# Both surfaces' delivery tools. Desktop-local Cowork serves the `mcp__cowork__`
# SDK-MCP tool; remote/cloud serves the agent-native one and cannot see an
# `mcp__` tool at all. A skill naming either would strand the other lane (which
# is why no SKILL.md names one) — but the CHECKER has to know both, because it
# reads what the agent actually reached for.
DELIVERY_TOOLS = ("mcp__cowork__present_files", "SendUserFile", "device_commit_files")

# Files at the outputs root that are not founder deliverables. Deliberately tiny:
# the skills' own contract is that the root IS the deliverable level, so anything
# there is an exception that has to be argued, not a convenience filter.
_NOT_DELIVERABLES = {".ds_store", "thumbs.db"}

# Canonical deliverable basenames, used ONLY when the outputs root holds none —
# i.e. for a skill that presents from its review dir, or a run whose root copy
# never happened. Restricted to composed final artifacts on purpose: adding an
# intermediate here would make every root-copy run fail on its own working state.
NESTED_DELIVERABLE_NAMES = frozenset(
    {
        "report.md",
        "report.html",
        "explore.html",
        "explorer.html",
        "counsel_packet.md",
        "report_fast_assess.md",
        "report_concise.md",
        "report_extraction_only.md",
    }
)

# Per-skill REQUIRED sets — the full-pipeline route only.
#
# Transcribed from each skill's Deliver step. Optional members are deliberately
# ABSENT: a `.html` that was never generated is not a delivery failure, and the
# scan above already catches one that WAS generated and not presented.
#
# Suffix-matched, not exact-matched: every skill prefixes the company name or
# slug at runtime (`{Company}_Market_Sizing.md`), so the stable part is the tail.
REQUIRED_SUFFIXES: dict[str, tuple[str, ...]] = {
    "market-sizing": ("_Market_Sizing.md",),
    "deck-review": ("_Deck_Review.md",),
    "ic-sim": ("_IC_Simulation.md",),
    # No workspace-root copy: presented by path from the review dir, which is why
    # the nested scan above exists.
    "financial-model-review": ("report.md", "report.html", "explore.html"),
    "competitive-positioning": ("_Competitive_Positioning.md",),
    "cap-table": (
        "_Cap_Table.md",
        "_Cap_Table.html",
        "_Cap_Table_Explorer.html",
        "_Counsel_Packet.md",
    ),
}


def _event_lines(run_dir: pathlib.Path) -> Iterator[str]:
    """Yield raw event-JSON-line strings from a run dir's `events.jsonl` file(s),
    OR — when `run_dir` is a single committed cassette file — from its frozen
    `events` array.

    CI never produces a run directory: `replay` is a deterministic cassette
    playback that never spawns an agent, so there is no `events.jsonl` for CI to
    read. A committed cassette's `events` array IS the same evidence, verbatim —
    each entry is the identical JSON-encoded line a live run writes to
    `events.jsonl` (verified against a recorded cassette). `leak_scan.py`
    already reads a cassette this way for the same reason; this mirrors that
    established convention rather than inventing a second one.
    """
    if run_dir.is_file():
        try:
            doc = json.loads(run_dir.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        events = doc.get("events") if isinstance(doc, dict) else None
        if isinstance(events, list):
            for line in events:
                yield line if isinstance(line, str) else json.dumps(line)
        return
    for path in sorted(run_dir.rglob("events.jsonl")):
        yield from path.read_text(encoding="utf-8", errors="replace").splitlines()


def _walk_blocks(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield every tool_use / tool_result block, at any nesting depth.

    Depth-limited and shape-tolerant for the same reason `gate_prefix_check.py`
    walks rather than indexes: the transcript envelope has changed shape across
    harness versions, and an indexed reader fails silently when it does.
    """
    if depth > 8:
        return
    if isinstance(obj, dict):
        if obj.get("type") in ("tool_use", "tool_result"):
            yield obj
        for v in obj.values():
            yield from _walk_blocks(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_blocks(v, depth + 1)


def collect_presented(run_dir: pathlib.Path) -> tuple[set[str], int, int]:
    """Basenames delivered, successful call count, and errored call count.

    Basenames, not full paths: the in-guest mount prefix differs from the host
    path the transcript records, and reconciling them would couple this checker
    to a mount layout that has already moved once.

    Two passes: collect every delivery call and its file list, then drop the ones
    whose `tool_result` came back an error. A failed call must not credit its
    filenames — that would turn a hallucinated path into a PASS.
    """
    per_call: dict[str, set[str]] = {}
    anonymous: set[str] = set()
    errored_ids: set[str] = set()
    calls = 0

    for line in _event_lines(run_dir):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for block in _walk_blocks(event):
            if block.get("type") == "tool_result":
                if block.get("is_error") and isinstance(block.get("tool_use_id"), str):
                    errored_ids.add(block["tool_use_id"])
                continue
            if block.get("name") not in DELIVERY_TOOLS:
                continue
            calls += 1
            raw = block.get("input")
            names: set[str] = set()
            if isinstance(raw, dict):
                for f in raw.get("files") or []:
                    fp = f.get("file_path") if isinstance(f, dict) else f
                    if isinstance(fp, str) and fp.strip():
                        names.add(pathlib.PurePosixPath(fp).name)
            call_id = block.get("id")
            if isinstance(call_id, str):
                per_call.setdefault(call_id, set()).update(names)
            else:
                anonymous |= names

    presented = set(anonymous)
    for call_id, names in per_call.items():
        if call_id not in errored_ids:
            presented |= names
    return presented, calls - len(errored_ids & per_call.keys()), len(errored_ids & per_call.keys())


def _collect_produced_from_cassette(cassette_path: pathlib.Path) -> tuple[set[str], pathlib.Path | None, bool]:
    """`collect_produced` for a single committed cassette (no live run dir).

    A cassette's `artifacts[].path` is root-relative to its `userVisibleRoots`
    (e.g. ``outputs/Foo.md``, ``outputs/artifacts/<dir>/report.md``) rather than
    the ``mnt/outputs/...`` a live run dir carries — same tree, different prefix
    — so this walks `artifacts` instead of the filesystem. The cassette PATH
    itself stands in for the `outputs_root` return value: it is never
    dereferenced, only checked for `is None` (evidence-available) by the caller.
    """
    try:
        doc = json.loads(cassette_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), None, True
    artifacts = doc.get("artifacts") if isinstance(doc, dict) else None
    if not isinstance(artifacts, list):
        return set(), None, True

    at_root: set[str] = set()
    nested: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        if not isinstance(path, str) or not path.startswith("outputs/"):
            continue
        rel = path[len("outputs/") :]
        if not rel:
            continue
        name = pathlib.PurePosixPath(rel).name
        if "/" in rel:
            if name.lower() in NESTED_DELIVERABLE_NAMES:
                nested.add(name)
        elif name and not name.startswith(".") and name.lower() not in _NOT_DELIVERABLES:
            at_root.add(name)

    if at_root:
        return at_root, cassette_path, True
    return nested, cassette_path, False


def collect_produced(run_dir: pathlib.Path) -> tuple[set[str], pathlib.Path | None, bool]:
    """Deliverables produced by the run, and whether they came from the root.

    Returns (names, outputs_root, from_root). `from_root` False means the root
    held nothing and these were found below it — see the module docstring for
    why that is a real case and not a fallback hack.
    """
    if run_dir.is_file():
        return _collect_produced_from_cassette(run_dir)

    roots = [p for p in run_dir.rglob("mnt/outputs") if p.is_dir()]
    if not roots:
        return set(), None, True
    root = sorted(roots)[0]

    at_root = {
        p.name
        for p in root.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name.lower() not in _NOT_DELIVERABLES
    }
    if at_root:
        return at_root, root, True

    nested = {p.name for p in root.rglob("*") if p.is_file() and p.name.lower() in NESTED_DELIVERABLE_NAMES}
    return nested, root, False


def check(
    produced: set[str],
    presented: set[str],
    calls: int,
    *,
    require: tuple[str, ...] = (),
    lane: str = "local",
    errored: int = 0,
) -> tuple[list[str], str]:
    """Compare the produced and presented sets. Returns (problems, outcome)."""
    problems: list[str] = []

    if errored:
        problems.append(
            f"[errored-delivery] {errored} delivery call(s) returned an error and were not counted — "
            "a failed call must not credit its filenames"
        )

    if not produced and calls == 0 and not errored:
        return ([], "NOT-EXERCISED")

    # The delivery tool is not served on the remote lane at all, so silence there
    # is the tool's absence and not the agent's failure. The distinction matters:
    # scoring it FAIL would manufacture a defect on the lane Cowork makes default
    # for new sessions, and scoring it PASS would hide a real one. Neither.
    if calls == 0 and not errored and lane == "remote":
        return (
            [
                f"[not-observable] {len(produced)} deliverable(s) produced and no delivery tool call — "
                f"expected on lane: remote, where the tool is not served. OBSERVED-IN-TRANSCRIPT-ONLY, "
                f"never a PASS: produced = {', '.join(sorted(produced))}"
            ],
            "NOT-EXERCISED",
        )

    if calls == 0 and produced:
        problems.append(
            f"[undelivered] {len(produced)} deliverable(s) produced, ZERO delivered: {', '.join(sorted(produced))}"
        )

    missing = sorted(produced - presented)
    if missing:
        problems.append(
            f"[incomplete] {len(missing)} of {len(produced)} produced deliverable(s) were never presented: "
            f"{', '.join(missing)}"
        )

    for suffix in require:
        if not any(name.endswith(suffix) for name in produced):
            problems.append(f"[missing-required] no file matching {suffix!r} was produced")
        elif not any(name.endswith(suffix) for name in presented):
            problems.append(f"[missing-required] a file matching {suffix!r} was produced but not presented")

    return (problems, "FAIL" if problems else "PASS")


def detect_lane(run_dir: pathlib.Path) -> str | None:
    """Read the lane the run actually declared, rather than trusting a flag.

    An operator who forgets `--lane remote` gets a false FAIL; one who passes it
    on a local run launders a real failure into NOT-EXERCISED. Both are avoidable
    — the harness records the lane in the turn result.

    A committed cassette carries the same fact directly at `scenario.lane` (no
    `result.json` file exists to `rglob` for — there is no run dir at all).
    """
    if run_dir.is_file():
        try:
            data = json.loads(run_dir.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        scenario = data.get("scenario") if isinstance(data, dict) else None
        lane = scenario.get("lane") if isinstance(scenario, dict) else None
        return lane if isinstance(lane, str) and lane else None
    for path in sorted(run_dir.rglob("result.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        # `scenario` is a bare NAME string in some result shapes and an object in
        # others — indexing it blind crashes on real evidence, which is how this
        # was found. Read defensively; the lane is optional metadata either way.
        lane = data.get("lane")
        if not isinstance(lane, str):
            scenario = data.get("scenario")
            lane = scenario.get("lane") if isinstance(scenario, dict) else None
        if isinstance(lane, str) and lane:
            return lane
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check a run delivered its complete deliverable set. Meaningful only against "
        "founder-skills runs: a generic probe that leaves an un-presented file at the outputs root "
        "will FAIL by this contract and that failure means nothing for such a run."
    )
    ap.add_argument("run_dir", type=pathlib.Path)
    ap.add_argument(
        "--require",
        choices=sorted(REQUIRED_SUFFIXES),
        help="also assert this skill's REQUIRED full-pipeline set was produced and presented. "
        "OFF by default: the route is chosen at runtime (fast-assess, extraction-only and concise "
        "deliver smaller sets), so requiring the full set blind would fail conforming runs.",
    )
    ap.add_argument(
        "--lane",
        choices=("local", "remote"),
        help="override the lane. Default: read it from the run's result.json, falling back to local.",
    )
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if not args.run_dir.exists():
        print(f"Error: {args.run_dir} does not exist", file=sys.stderr)
        return 2

    lane = args.lane or detect_lane(args.run_dir) or "local"
    presented, calls, errored = collect_presented(args.run_dir)
    produced, root, from_root = collect_produced(args.run_dir)

    if root is None:
        print(
            "evidence unavailable: no mnt/outputs directory in this run — cannot tell a complete "
            "delivery from a total failure",
            file=sys.stderr,
        )
        return 2

    require = REQUIRED_SUFFIXES.get(args.require, ()) if args.require else ()
    problems, outcome = check(produced, presented, calls, require=require, lane=lane, errored=errored)

    summary: dict[str, Any] = {
        "outcome": outcome,
        "lane": lane,
        "produced": sorted(produced),
        "produced_at_root": from_root,
        "presented": sorted(presented),
        "delivery_calls": calls,
        "errored_calls": errored,
        "problems": problems,
    }
    print(json.dumps(summary, indent=2 if args.pretty else None))

    if outcome == "NOT-EXERCISED":
        for p in problems:
            print(p, file=sys.stderr)
        print(
            "NOT-EXERCISED: nothing produced and nothing delivered — a gated stop, a rule-lookup, or a "
            "route with no deliverable. This is never a pass.",
            file=sys.stderr,
        )
        return 2

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    where = "the outputs root" if from_root else "below the outputs root"
    print(
        f"\nPASS: all {len(produced)} deliverable(s) found at {where} were presented across {calls} delivery call(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
