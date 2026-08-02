# /// script
# requires-python = ">=3.10"
# ///
"""Check the reserved no-change prefix against what a run's gates ACTUALLY emitted.

`test_skill_contract.py` pins that a SKILL.md *declares* the rule. It cannot see
runtime behaviour, and prose guidance about model behaviour is exactly the class
this repo has shipped inert. This closes that gap from the other side: it reads a
completed run's `events.jsonl` and checks the emitted `AskUserQuestion` options.

**Why this is not a scenario assert.** It would be better as one, and it cannot
be: the harness's `question_asked` matches against a questions sidecar that
carries question TEXT only — verified against a real run's `trace.json`, where
every entry is a bare question string with no options. No assert in the harness
vocabulary inspects emitted option labels. So the durable check lives here, gets
pointed at a run directory, and is re-runnable against any future run.

Checks, per gate that fired:
  1. EXACTLY one option carries the prefix. Not at-least-one — at-least-one is
     satisfied by the failure mode being prevented (a gate where every option
     reads as consent while some of them mutate).
  2. No MUTATING option carries it. This is the negative case, and it is the one
     a declaration test can never reach.

Exit 0 = every gate conformed. Exit 1 = a violation. Exit 2 = no gates found
(evidence unavailable — never reported as a pass, since a run where no gate
fired proves nothing about gates).

`<run-dir>` also accepts a single committed cassette file (`*.cassette.json`):
CI never spawns an agent (`replay` is a deterministic cassette playback), so
there is no live `events.jsonl` for CI to read. A cassette's frozen `events`
array holds the identical line strings — the same reading `leak_scan.py`
already relies on — so pointing this at a cassette is real evidence, not a
weaker substitute.

    python3 cowork-tests/gate_prefix_check.py <run-dir | cassette.json> [--prefix "No changes — "]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections.abc import Iterator
from typing import Any

NO_CHANGE_PREFIX = "No changes — "

# A label is "mutating" if it proposes a change to the analysis. Kept to verbs
# that appear in an option LABEL, deliberately narrow: this decides whether to
# FAIL a run, so a false positive is expensive. It is a heuristic and is only
# ever used to strengthen check 2 — check 1 (exactly-one) is exact and does not
# depend on it.
_MUTATING = re.compile(
    r"\b(add|adds|adding|remove|removes|removing|swap|drop|replace|"
    r"re-?categoris|re-?categoriz|re-?score|change|changing|merge|merging|include)\b",
    re.IGNORECASE,
)


def _walk_questions(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield every {question, options} object, at any nesting depth."""
    if depth > 8:
        return
    if isinstance(obj, dict):
        if "question" in obj and isinstance(obj.get("options"), list):
            yield obj
        for v in obj.values():
            yield from _walk_questions(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_questions(v, depth + 1)


def _labels(q: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for o in q.get("options", []):
        lab = o.get("label") if isinstance(o, dict) else o
        if isinstance(lab, str) and lab.strip():
            out.append(lab)
    return out


def _event_lines(run_dir: pathlib.Path) -> Iterator[str]:
    """Yield raw event-JSON-line strings from a run dir's `events.jsonl` file(s),
    OR — when `run_dir` is a single committed cassette file — from its frozen
    `events` array.

    CI never produces a run directory: `replay` is a deterministic cassette
    playback that never spawns an agent, so there is no `events.jsonl` for CI to
    read. A committed cassette's `events` array IS the same evidence, verbatim —
    each entry is the identical JSON-encoded line a live run writes to
    `events.jsonl` (verified against a recorded cassette). `leak_scan.py` already
    reads a cassette this way for the same reason (its own module docstring:
    "any events.jsonl transcript" or a cassette's `events` list); this mirrors
    that established convention rather than inventing a second one.
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


def collect_gates(run_dir: pathlib.Path) -> list[tuple[str, list[str]]]:
    """Every AskUserQuestion gate emitted in the run, de-duplicated.

    A gate is commonly recorded more than once (the tool_use and its echo), so
    identical (question, options) pairs collapse — otherwise a conforming gate
    would be counted twice and a violating one reported twice.
    """
    gates: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for line in _event_lines(run_dir):
        if "AskUserQuestion" not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for q in _walk_questions(event):
            labels = _labels(q)
            if not labels:
                continue
            key = (str(q.get("question", ""))[:200], tuple(labels))
            if key in seen:
                continue
            seen.add(key)
            gates.append((str(q.get("question", "")), labels))
    return gates


_DASH_RE = re.compile(r"\s*[-–—]\s*")  # hyphen, en-dash, em-dash — any spacing


def _canon(text: str) -> str:
    """Fold dash variants and whitespace before comparing.

    The prefix is written with an em-dash, and a model may emit an en-dash, a
    plain hyphen, or any of those UNSPACED ("No changes—looks good"). Matching
    only the spaced literal would score a lookalike as zero-carrying and report
    a DESIGN failure where the design actually held — the worst kind of wrong
    answer from a checker, because it condemns a working rule. An unspaced
    em-dash is not a hypothetical: it is a plausible, common model rendering,
    caught by review before this shipped rather than by a live false-red.

    A caveat this function cannot fully close, recorded rather than hidden: the
    harness's own scripted-answer matcher (`SCRIPTED_SEPARATORS = ":(,—–"` in
    `dist/decide/decider.js`) accepts em-dash and en-dash as boundary separators
    but NOT a plain hyphen, and never treats bare whitespace as a boundary. So a
    hyphen-emitting run can pass THIS checker while the harness's own `choose:`
    scenario dies unanswered on the identical label — the two tools are not
    reconciled on that one variant, and no amount of folding here changes what
    the harness itself accepts.
    """
    folded = _DASH_RE.sub("—", text)
    return re.sub(r"\s+", " ", folded).strip()


def check(gates: list[tuple[str, list[str]]], prefix: str, *, require_exactly_one: bool = True) -> list[str]:
    """Check the reserved prefix per gate.

    `require_exactly_one` distinguishes the two gate families. **Confirm-gates**
    (is this right? proceed?) always have a legitimate no-change branch, so
    exactly one option must carry the token. **Data-entry gates** — which ask for
    a fact, e.g. a stage or a jurisdiction — have no such branch, and demanding
    one there would force authors to invent a fake "no change" option on a
    question that asks for information. For those the rule is only that the token
    is RESERVED: at most one, possibly none. Same token, different arity.
    """
    problems: list[str] = []
    canon_prefix = _canon(prefix)
    for question, labels in gates:
        carrying = [x for x in labels if _canon(x).startswith(canon_prefix)]
        stem = question[:90]
        bad = len(carrying) != 1 if require_exactly_one else len(carrying) > 1
        if bad:
            kind = "exactly-one" if require_exactly_one else "at-most-one"
            problems.append(
                f"[{kind}] {len(carrying)} of {len(labels)} options carry {prefix!r}\n"
                f"    gate: {stem}\n    options: {' | '.join(labels)}"
            )
        for lab in carrying:
            tail = _canon(lab)[len(canon_prefix) :]
            if _MUTATING.search(tail):
                problems.append(f"[reserved] a mutating option carries the no-change prefix: {lab!r}\n    gate: {stem}")
    return problems


def _load_slug_normalizer() -> Any:
    """Import `normalize_competitor_slug` from the producer that OWNS it.

    `recall_gaps.unmatched[].slug` is written through `normalize_competitor_slug`
    (lowercase, strip a corp suffix, non-alnum -> hyphen). `landscape.json`'s
    slugs are agent-authored and only kebab-case-checked, never run through that
    normalizer — `validate_landscape.py` enforces format, not a canonical form.
    A raw string comparison between the two therefore has a FALSE-NEGATIVE risk
    exactly where this check matters most: an entry authored into `landscape.json`
    as `FieldPulse` (kebab-case is format-checked, not lowercase-enforced) would
    leak past a raw comparison against the already-normalized `fieldpulse` recall
    offered — case-sensitive string equality, `"fieldpulse" != "FieldPulse"` —
    the one check whose entire purpose is catching a silent leak, silently
    missing one.

    Duplicating the three-line function was considered and rejected: two copies
    drift, and a drifted copy here is invisible until it produces exactly the
    silent miss this exists to prevent. Importing the real one means a change to
    the normalizer is automatically picked up on both sides of the diff it feeds.
    Fails LOUD (raises) rather than falling back to unnormalized comparison,
    which is a fail-CLOSED for a false-negative risk we already know about.
    """
    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "founder-skills"
        / "skills"
        / "competitive-positioning"
        / "scripts"
        / "verify_competitors.py"
    )
    if not path.exists():
        raise RuntimeError(
            f"cannot load the slug normalizer from {path} — refusing to fall back to an "
            "unnormalized comparison, which would silently under-report leaks"
        )
    import importlib.util

    spec = importlib.util.spec_from_file_location("verify_competitors", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_competitor_slug


def _read_json_artifact(run_dir: pathlib.Path, filename: str) -> Any | None:
    """Read a named JSON artifact from a run dir, OR from a single committed cassette.

    Cassette mode only sees an artifact whose body was INLINED at record time —
    large artifacts are recorded hash-only (manifest entry, no body), so this
    correctly returns None for one rather than fabricating content. Same
    limitation `test_cowork_cassette_replay.py`'s `_artifact_body` documents for
    the identical reason.
    """
    if run_dir.is_file():
        try:
            doc = json.loads(run_dir.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        artifacts = doc.get("artifacts") if isinstance(doc, dict) else None
        for artifact in artifacts or []:
            if not isinstance(artifact, dict) or "body" not in artifact:
                continue
            if str(artifact.get("path", "")).endswith(filename):
                try:
                    return json.loads(artifact["body"])
                except (json.JSONDecodeError, TypeError):
                    return None
        return None
    path = next(iter(sorted(run_dir.rglob(filename))), None)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_substance(run_dir: pathlib.Path) -> tuple[list[str], dict[str, Any]]:
    """Did taking the no-change branch actually leave the competitor set alone?

    Honouring the prefix in FORM while mutating anyway is the failure the label
    check cannot see, so this compares what the blind recall check offered
    (`recall_gaps.unmatched`) against what ended up in `landscape.json`. Any
    offered candidate that reached the final set means the branch was not
    honoured. Run this ONLY on a run where the no-change branch was taken —
    on an adoption run these slugs are supposed to appear.

    Both sides are normalized through `normalize_competitor_slug` before
    comparing — see `_load_slug_normalizer`'s docstring for why a raw-string
    comparison here is unsafe.
    """
    ver = _read_json_artifact(run_dir, "competitor_verification.json")
    land = _read_json_artifact(run_dir, "landscape.json")
    if ver is None or land is None:
        return (["evidence unavailable: competitor_verification.json or landscape.json not found"], {})
    normalize = _load_slug_normalizer()
    offered_raw = [
        u.get("slug")
        for u in (ver.get("recall_gaps") or {}).get("unmatched", [])
        if isinstance(u, dict) and u.get("slug")
    ]
    offered = [normalize(s) for s in offered_raw]
    final = {normalize(c.get("slug", "")) for c in land.get("competitors", [])}
    leaked = sorted(s for s in offered if s in final)
    info = {"offered_by_recall": offered_raw, "final_set_size": len(final), "leaked": leaked}
    if not offered:
        return (["evidence unavailable: recall offered no candidates, so 'unchanged' is untestable"], info)
    if leaked:
        return (
            [
                f"[substance] the no-change branch was taken, but {len(leaked)} recall "
                f"candidate(s) still entered the final set (normalized slugs): {', '.join(leaked)}"
            ],
            info,
        )
    return ([], info)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=pathlib.Path)
    ap.add_argument("--prefix", default=NO_CHANGE_PREFIX)
    ap.add_argument(
        "--at-most-one",
        action="store_true",
        help="data-entry gates: the token is reserved but not required (default: exactly-one, for confirm-gates)",
    )
    ap.add_argument(
        "--substance",
        action="store_true",
        help="also assert no recall candidate entered the final set (no-change runs only)",
    )
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if not args.run_dir.exists():
        print(f"Error: {args.run_dir} does not exist", file=sys.stderr)
        return 2

    gates = collect_gates(args.run_dir)
    if not gates:
        print(
            "evidence unavailable: no AskUserQuestion gates found in this run — "
            "a run where no gate fired proves nothing about gates",
            file=sys.stderr,
        )
        return 2

    gate_problems = check(gates, args.prefix, require_exactly_one=not args.at_most_one)
    # Count conforming from the gate list itself, keyed the SAME way
    # collect_gates de-duplicates (question + its options) — keying on question
    # text alone would undercount when two distinct gates happen to share
    # wording, treating them as one.
    offending = {
        (q, tuple(labels))
        for q, labels in gates
        if check([(q, labels)], args.prefix, require_exactly_one=not args.at_most_one)
    }
    problems = list(gate_problems)
    substance: dict[str, Any] = {}
    substance_unavailable = False
    if args.substance:
        sub_problems, substance = check_substance(args.run_dir)
        substance_unavailable = any(p.startswith("evidence unavailable") for p in sub_problems)
        problems.extend(sub_problems)
    summary = {
        "gates_found": len(gates),
        "gates_conforming": len(gates) - len(offending),
        "problems": problems,
        "prefix": args.prefix,
        "substance": substance,
    }
    print(json.dumps(summary, indent=2 if args.pretty else None, ensure_ascii=False))
    # An evidence-unavailable substance result is not a violation and must not
    # share exit 1 with one — the module contract reserves exit 2 for "nothing
    # to check here", and conflating the two makes exit code alone unable to
    # tell an automation "this run proved nothing" apart from "this run failed".
    if substance_unavailable and not gate_problems:
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 2
    if problems:
        print(f"\n{len(problems)} violation(s) across {len(gates)} gate(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"\n✓ all {len(gates)} gate(s) conform", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
