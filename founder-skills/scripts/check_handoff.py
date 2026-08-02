#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Gate a Context A sub-agent's file hand-off before the producer pipe.

The sub-agent writes its raw output JSON to the OUTPUT_PATH given in its
dispatch prompt and returns a small receipt ({"status": "complete",
"output_path": "<echo>"}). The main thread runs this script BEFORE piping
the file into a producer script. Producer schema validation is NOT
duplicated here -- the producer pipe (which runs next) is that gate.

Usage:
    python check_handoff.py "$OUTPUT_PATH"
    echo "$AGENT_FINAL_MESSAGE" | \
        python check_handoff.py "$OUTPUT_PATH" --receipt-json - \
            --agent-path "$AGENT_NAMESPACE_PATH"

Two path namespaces (branch C, Cowork): the sub-agent's file tools are
rooted at the outputs mount while the main thread addresses the same
file under $OUTPUTS_ROOT, so the receipt echoes the agent-namespace
path, not the main-thread path. Pass the agent-side path (the exact
OUTPUT_PATH string from the dispatch prompt) via --agent-path; the
receipt's echoed path is accepted if it matches EITHER namespace.

Checks, in order:
    1. file exists and is non-empty        -> else exit 3
    2. file parses as JSON (--format=json, the default)
       OR passes the content-shape gate (--format=markdown) -> else exit 4 / 7
    3. (--receipt-json) receipt extracts and its output_path matches
       the expected path (or --agent-path) -> else exit 6 / exit 5

A one-line machine-readable JSON diagnostic is always written to stdout.

--format=markdown (R2 coaching-transport fix): the hand-off file is raw
commentary markdown, not JSON -- gate 2 does NOT parse the body as JSON
(exit 4 is unreachable in this mode). Instead it runs a content-shape
gate that rejects a body that is clearly not commentary:
  (a) receipt-shaped: the ENTIRE file parses as JSON to a dict carrying
      an "output_path" or "status" key (the agent wrote its receipt into
      OUTPUT_PATH by mistake). This is "the whole file IS that dict", not
      "the file contains a brace" -- real commentary may quote JSON.
  (b) marker-bearing: the file contains the literal coaching insertion
      marker substring (pass --marker for an exact match, or rely on the
      COACHING_INSERTION_POINT_ prefix detection) -- would double-insert.
Either failure exits 7 (shape-invalid), distinct from empty (3).

Exit codes (the SKILL.md recovery state machine branches on these):
    0 = ok -- pipe the file through the producer
    3 = missing, empty, or (markdown mode) whitespace-only file (the
        fabricated-receipt case) -> redo-dispatch
    4 = (--format=json only) file exists but is not valid JSON -> repair-dispatch
    5 = receipt parsed but its output_path differs from the expected
        path (the agent wrote somewhere else) -> repair-dispatch with the
        exact expected path
    6 = receipt unparseable / no output_path key -> corrective
        redo-dispatch with "return ONLY the receipt JSON"
    7 = (--format=markdown only) content-shape gate failed (receipt-shaped
        or marker-bearing body) -> repair-dispatch: "your file wasn't the
        coaching commentary -- write the coaching markdown, nothing else"
    8 = path-namespace mismatch: no file at the expected path, but one IS
        sitting where a DOUBLED agent-namespace prefix would have put it
        (needs --agent-path) -> re-dispatch with the corrected agent prefix.
        Reported ahead of exit 3 because both look identical from gate 1 yet
        need opposite responses: exit 3 means the receipt may be fabricated,
        exit 8 means the agent complied and the PATH was wrong.
        The `found_at` field is DIAGNOSTIC -- never read the hand-off from it.
        Exit 0 is what guarantees the file is at the contracted path, and every
        downstream producer pipe addresses $HANDOFF_DIR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

EXIT_OK = 0
EXIT_MISSING = 3
EXIT_BAD_JSON = 4
EXIT_PATH_MISMATCH = 5
EXIT_BAD_RECEIPT = 6
EXIT_SHAPE_INVALID = 7
EXIT_PATH_NAMESPACE = 8


def _namespace_mismatch_candidate(expected: str, agent_path: str | None) -> str | None:
    """Return the path a doubled agent-namespace prefix would have produced, if a file is there.

    DIAGNOSTIC ONLY. Callers must NOT read the hand-off from the returned path: exit 0 carries the
    invariant "it is safe to `cat $HANDOFF_DIR/<file>`", and every downstream producer pipe in every
    SKILL.md addresses `$HANDOFF_DIR`. Honouring a found-elsewhere file would silently void that
    invariant across ~50 bash references, and would be incoherent with EXIT_PATH_MISMATCH, which exists
    precisely to punish "the agent wrote somewhere else". It would also leave permanent litter: the
    outputs mount is write-allowed / delete-DENIED, so the stray tree is user-visible forever.

    The failure this detects: a relative agent-namespace prefix resolved against the outputs mount
    instead of the session root, yielding `<outputs>/<agent_prefix>/...` — a doubled segment. The
    resolver no longer emits the prefix that caused it, but a stale dispatch prompt, a paraphrased path,
    or an explicit COWORK_AGENT_ARTIFACTS_ROOT can still reproduce it, and the failure is otherwise
    indistinguishable from a fabricated receipt.

    Requires --agent-path (relative). Returns None when it cannot be computed, which includes every
    branch where the agent path is absolute or already a suffix of `expected` — i.e. it is provably
    inert outside the one topology that can double.
    """
    if not agent_path or os.path.isabs(agent_path):
        return None
    normalized = agent_path.strip("/")
    if not normalized:
        return None

    # The two paths address the same file in two namespaces, so they share a trailing run of segments.
    # Strip that shared tail off the absolute path to recover the outputs root the sub-agent's cwd is,
    # then re-apply the FULL agent-relative path to it — which is exactly what a sub-agent resolving its
    # relative path against the outputs mount would have produced.
    #
    #   expected   = <outputs>/artifacts/<dir>/handoff/<rid>/coaching.md
    #   agent_path =    mnt/outputs/artifacts/<dir>/handoff/<rid>/coaching.md
    #   shared tail =               artifacts/<dir>/handoff/<rid>/coaching.md
    #   candidate  = <outputs>/ + mnt/outputs/artifacts/<dir>/handoff/<rid>/coaching.md
    expected_parts = [p for p in expected.replace(os.sep, "/").split("/") if p]
    agent_parts = [p for p in normalized.split("/") if p]
    leading = "/" if expected.startswith("/") else ""

    # Do NOT greedily take the longest shared tail. The agent prefix's own last segment can coincide
    # with the outputs root's last segment (`mnt/outputs` under `<session>/mnt/outputs`), so a greedy
    # match consumes a segment that belongs to the root and computes a candidate one level too high.
    # Enumerate every plausible split instead and let the filesystem decide — safe, because a path is
    # only ever returned when a non-empty file is actually sitting there.
    for shared in range(min(len(agent_parts), len(expected_parts)), 0, -1):
        if expected_parts[-shared:] != agent_parts[-shared:]:
            continue
        outputs_root = leading + "/".join(expected_parts[: len(expected_parts) - shared])
        candidate = os.path.join(outputs_root, normalized)
        if os.path.normpath(candidate) == os.path.normpath(expected):
            # The agent path is already the whole tail: no extra prefix to double. This is the host-loop
            # and CLI case, which is why the probe is provably inert outside the topology that doubles.
            continue
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)

MARKER_PREFIX = "COACHING_INSERTION_POINT_"

# Unconditional -- this script is stateless and has no notion of which dispatch attempt it is
# checking, so the hint fires on every exit 3, not just a first attempt. A sub-agent whose
# declared tool list lacks Write cannot create OUTPUT_PATH at all, which looks identical to a
# fabricated receipt from this gate's vantage point (no file at the expected path either way).
MISSING_FILE_WRITE_HINT = (
    "a missing hand-off file can also mean the dispatched sub-agent's declared tool list lacks "
    "Write, not just that it fabricated the receipt -- check the agent's frontmatter tools list "
    "before spending a redo-dispatch"
)


def _diag(code: str, exit_code: int, **fields: object) -> int:
    payload: dict[str, object] = {"code": code, **fields}
    sys.stdout.write(json.dumps(payload) + "\n")
    return exit_code


def extract_json_tolerant(text: str) -> dict[str, object] | None:
    """Tolerant JSON extraction: strip a markdown fence if the whole text is
    fenced, try a direct parse, then brace-aware raw_decode from the first
    '{'. Returns the first JSON object found, or None."""
    stripped = text.strip()
    fence_match = _FENCE_RE.match(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    idx = stripped.find("{")
    while idx != -1:
        try:
            parsed, _end = decoder.raw_decode(stripped[idx:])
        except json.JSONDecodeError:
            idx = stripped.find("{", idx + 1)
            continue
        if isinstance(parsed, dict):
            return parsed
        idx = stripped.find("{", idx + 1)
    return None


def _paths_match(expected: str, claimed: str) -> bool:
    if expected == claimed:
        return True
    return os.path.normpath(os.path.abspath(expected)) == os.path.normpath(os.path.abspath(claimed))


def shape_invalid_reason(text: str, marker: str | None) -> str | None:
    """Content-shape gate for --format=markdown. Returns a rejection reason,
    or None if the body is acceptable as coaching commentary.

    Rejects iff the WHOLE file parses as a receipt-shaped JSON dict (not
    merely "contains a brace" -- legitimate commentary may quote JSON), or
    the file contains the literal coaching insertion marker substring.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and ("output_path" in parsed or "status" in parsed):
        return "the file is receipt-shaped JSON (has an output_path/status key), not commentary markdown"
    if marker is not None and marker in text:
        return f"the file contains the literal insertion marker {marker!r} -- would double-insert"
    if marker is None and MARKER_PREFIX in text:
        return f"the file contains the coaching insertion marker prefix {MARKER_PREFIX!r} -- would double-insert"
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gate a Context A/B file hand-off")
    p.add_argument("output_path", help="The OUTPUT_PATH given in the dispatch prompt")
    p.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help=(
            "json (default): the hand-off file must parse as JSON (gate 2 exit 4 on failure). "
            "markdown: the hand-off file is raw commentary markdown -- skip JSON parsing and "
            "run the content-shape gate instead (exit 7 on failure)."
        ),
    )
    p.add_argument(
        "--marker",
        metavar="MARKER",
        help="(--format=markdown) the exact coaching insertion marker string to detect in the body",
    )
    p.add_argument(
        "--receipt-json",
        metavar="FILE",
        help="Agent's final message (file path, or '-' for stdin) to cross-check the echoed output_path",
    )
    p.add_argument(
        "--agent-path",
        metavar="PATH",
        help=(
            "The OUTPUT_PATH as given in the dispatch prompt (agent namespace) "
            "when it differs from the main-thread path; the receipt echo is "
            "accepted if it matches either"
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    expected: str = args.output_path

    # Gate 1: file exists and is non-empty.
    if not os.path.isfile(expected) or os.path.getsize(expected) == 0:
        # Distinguish a path-namespace misresolution from a fabricated receipt BEFORE reporting the
        # latter. Both look identical here (no file at the expected path), but they need opposite
        # responses: a fabricated receipt needs a redo-dispatch, a misresolution needs the dispatch
        # re-issued with a corrected prefix. Reporting "the receipt may be fabricated" for a
        # well-behaved agent that wrote exactly where it was told sends the caller down the wrong branch.
        found_at = _namespace_mismatch_candidate(expected, args.agent_path)
        if found_at is not None:
            sys.exit(
                _diag(
                    "path_namespace_mismatch",
                    EXIT_PATH_NAMESPACE,
                    output_path=expected,
                    found_at=found_at,
                    detail=(
                        "the agent's relative OUTPUT_PATH resolved against the outputs mount instead of "
                        "the session root, producing a doubled prefix. The agent complied — do NOT treat "
                        "this as a fabricated receipt. Re-dispatch with the corrected agent-namespace "
                        "prefix. Do NOT read the hand-off from found_at: exit 0 is what guarantees the "
                        "hand-off is at the contracted path, and every downstream pipe depends on it."
                    ),
                )
            )
        sys.exit(
            _diag(
                "missing_or_empty",
                EXIT_MISSING,
                output_path=expected,
                detail="no file (or empty file) at the expected OUTPUT_PATH — the receipt may be fabricated",
                hint=MISSING_FILE_WRITE_HINT,
            )
        )

    # Gate 2: format-specific content check.
    try:
        with open(expected, encoding="utf-8-sig") as f:
            raw = f.read()
    except OSError as exc:
        sys.exit(
            _diag(
                "invalid_json",
                EXIT_BAD_JSON,
                output_path=expected,
                detail=str(exc),
            )
        )

    if args.format == "markdown":
        # Whitespace-only bodies are treated as missing/empty (exit 3), not
        # shape-invalid -- the size check above only catches truly empty files.
        if not raw.strip():
            sys.exit(
                _diag(
                    "missing_or_empty",
                    EXIT_MISSING,
                    output_path=expected,
                    detail="hand-off file is whitespace-only — the receipt may be fabricated",
                    hint=MISSING_FILE_WRITE_HINT,
                )
            )
        shape_reason = shape_invalid_reason(raw, args.marker)
        if shape_reason is not None:
            sys.exit(
                _diag(
                    "shape_invalid",
                    EXIT_SHAPE_INVALID,
                    output_path=expected,
                    detail=shape_reason,
                )
            )
    else:
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.exit(
                _diag(
                    "invalid_json",
                    EXIT_BAD_JSON,
                    output_path=expected,
                    detail=str(exc),
                )
            )

    # Gate 3 (optional): receipt cross-check.
    if args.receipt_json is not None:
        try:
            if args.receipt_json == "-":
                receipt_text = sys.stdin.read()
            else:
                with open(args.receipt_json, encoding="utf-8") as f:
                    receipt_text = f.read()
        except OSError as exc:
            sys.exit(
                _diag(
                    "receipt_unreadable",
                    EXIT_BAD_RECEIPT,
                    output_path=expected,
                    detail=str(exc),
                )
            )
        receipt = extract_json_tolerant(receipt_text)
        if receipt is None or not isinstance(receipt.get("output_path"), str):
            sys.exit(
                _diag(
                    "receipt_unparseable",
                    EXIT_BAD_RECEIPT,
                    output_path=expected,
                    detail="no JSON object with an output_path key could be extracted from the receipt",
                )
            )
        claimed = str(receipt["output_path"])
        agent_path: str | None = args.agent_path
        matched = _paths_match(expected, claimed) or (agent_path is not None and _paths_match(agent_path, claimed))
        if not matched:
            sys.exit(
                _diag(
                    "path_mismatch",
                    EXIT_PATH_MISMATCH,
                    output_path=expected,
                    agent_path=agent_path,
                    claimed_path=claimed,
                    detail="the agent's receipt echoes a different path — it wrote somewhere else",
                )
            )

    sys.exit(
        _diag(
            "ok",
            EXIT_OK,
            output_path=expected,
            bytes=os.path.getsize(expected),
        )
    )


if __name__ == "__main__":
    main()
