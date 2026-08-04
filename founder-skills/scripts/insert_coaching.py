#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Insert coaching commentary into report.md at the compose-emitted marker.

Deterministic replacement for the Context B agent-side insertion protocol:
the 6-state Grep idempotency matrix, the Edit-via-uuid-marker choreography,
and the run_id-parity verification previously expressed as natural-language
agent-body instructions. The agent now only composes the commentary text;
this script does everything mechanical.

Usage:
    echo '{"commentary_markdown": "..."}' | \
        python insert_coaching.py --report <report.md> \
            --marker '<!-- COACHING_INSERTION_POINT_a1b2c3d4 -->' \
            --verify-artifact <inputs.json> --verify-artifact <sizing.json>

    python insert_coaching.py --commentary-file <staged.json> \
        --report <report.md> --marker '<exact marker>'

Input JSON (stdin or --commentary-file): {"commentary_markdown": "<text>"}.
The commentary text is inserted verbatim as "## Coaching Commentary\\n\\n"
+ text, replacing the exact marker string (never the marker prefix).

Idempotency matrix on (commentary_count, marker_count) in report.md:
    (0, 1)  -> insert (the normal path)
    (1, 0)  -> already inserted; no-op success (resume-safe)
    all other states -> exit 1 with the same diagnostic strings the agent
    bodies used, so existing triage docs stay valid.

run_id parity: each --verify-artifact JSON must carry metadata.run_id and
all values must be equal. Parity runs BEFORE the write so a parity failure
leaves report.md untouched.

Write strategy: the new content is built fully in memory, then written in
a single in-place pass (open "w" on the same path). Never delete/recreate
and never os.replace -- Cowork's outputs/ denies deletion and rename.

Output: JSON receipt to stdout (--pretty for indented output; -o writes
the receipt to a file and emits a confirmation receipt to stdout).

Exit codes:
    0 = inserted or already inserted (receipt on stdout)
    1 = blocked (diagnostic JSON on stdout, human-readable line on stderr)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

COMMENTARY_HEADING = "## Coaching Commentary"


def _blocked(reason: str, pretty: bool, output: str | None) -> int:
    payload: dict[str, object] = {"status": "blocked", "reason": reason}
    _emit(payload, pretty, output)
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 1


def _emit(payload: dict[str, object], pretty: bool, output: str | None) -> None:
    indent = 2 if pretty else None
    out = json.dumps(payload, indent=indent) + "\n"
    if output:
        abs_path = os.path.abspath(output)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(out)
        receipt = {"written": abs_path, "bytes": len(out.encode("utf-8"))}
        sys.stdout.write(json.dumps(receipt) + "\n")
    else:
        sys.stdout.write(out)


def _load_commentary(commentary_file: str | None) -> tuple[str | None, str | None]:
    """Return (commentary_markdown, error_reason)."""
    try:
        if commentary_file:
            with open(commentary_file, encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        return None, f"cannot read commentary input: {exc}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"commentary input is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "commentary input must be a JSON object"
    commentary = parsed.get("commentary_markdown")
    if not isinstance(commentary, str) or not commentary.strip():
        return None, "commentary_markdown missing or empty"
    return commentary, None


def _matrix_reason(commentary_count: int, marker_count: int) -> str | None:
    """The 6-state idempotency matrix. None means 'proceed' or 'already
    inserted' (the two success states, distinguished by the caller)."""
    if commentary_count >= 2:
        return f"duplicate commentary detected (count={commentary_count})"
    if marker_count >= 2:
        return f"compose emitted multiple markers (count={marker_count}); compose bug"
    if commentary_count == 1 and marker_count == 1:
        return "partial-state corruption: commentary present but marker not consumed"
    if commentary_count == 0 and marker_count == 0:
        return (
            "compose did not emit insertion marker — or report.md may be "
            "truncated by an interrupted insert; re-run "
            "`compose_report.py --write-md` and retry"
        )
    return None


def _verify_run_id_parity(artifact_paths: list[str]) -> tuple[str | None, str | None]:
    """Return (run_id, error_reason). All artifacts must carry an equal
    metadata.run_id."""
    run_ids: dict[str, str] = {}
    for path in artifact_paths:
        name = os.path.basename(path)
        if not os.path.isfile(path):
            return None, f"{name} not found at {path}"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"run_id mismatch: {name} unreadable as JSON ({exc})"
        run_id = None
        if isinstance(data, dict):
            metadata = data.get("metadata")
            if isinstance(metadata, dict):
                run_id = metadata.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return None, f"run_id mismatch: {name} has no metadata.run_id"
        run_ids[name] = run_id
    distinct = sorted(set(run_ids.values()))
    if len(distinct) > 1:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(run_ids.items()))
        return None, f"run_id mismatch: {detail}"
    return (distinct[0] if distinct else None), None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Insert coaching commentary into report.md")
    p.add_argument("--report", required=True, help="Path to report.md")
    p.add_argument(
        "--marker",
        required=True,
        help="EXACT insertion marker string emitted by compose (never the prefix)",
    )
    p.add_argument(
        "--commentary-file",
        help="Read commentary JSON from this file instead of stdin",
    )
    p.add_argument(
        "--verify-artifact",
        action="append",
        default=[],
        metavar="PATH",
        help="JSON artifact whose metadata.run_id must match all others (repeatable)",
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    p.add_argument("-o", "--output", help="Write receipt to file instead of stdout")
    return p.parse_args()


def _scan_commentary(commentary: str) -> dict[str, list[str]]:
    """Report internal tokens in the coaching commentary. Never rewrites it.

    WHY THIS LIVES HERE. Each skill's `compose_report.py` scans the report it assembles, but the
    Coaching Commentary is not in that string — compose emits a marker, and this script replaces the
    marker afterwards. So the compose-time scan structurally CANNOT see the commentary, which is
    model-authored prose and therefore the likeliest place for an internal token to appear. This is the
    one shared place every skill's commentary passes through.

    REPORTS, does not substitute. Two reasons: this script's contract is verbatim insertion (its test
    suite pins that, and transport fidelity for quotes/newlines is the reason the envelope exists), and
    commentary may legitimately quote the founder's OWN field or column names, which we must not
    silently reword. The actionable fix is upstream in the coaching dispatch template.

    Non-blocking by design — a token in coaching text must never cost a founder their report. Delivery
    enforcement, where a skill has it, belongs in that skill's verify gate.
    """
    try:
        shared = os.path.dirname(os.path.abspath(__file__))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]
    except ImportError:
        return {"enums": [], "filenames": []}
    found: dict[str, list[str]] = _founder_text.scan(commentary)
    for token in found["enums"]:
        print(
            f"note: coaching commentary contains the internal token '{token}' — a founder cannot act on it",
            file=sys.stderr,
        )
    for name in found["filenames"]:
        print(
            f"note: coaching commentary names the internal file '{name}' — drop the reference",
            file=sys.stderr,
        )
    return found


def main() -> None:
    args = parse_args()
    pretty: bool = args.pretty
    output: str | None = args.output

    try:
        with open(args.report, encoding="utf-8") as f:
            report_text = f.read()
    except OSError as exc:
        sys.exit(_blocked(f"report.md not readable at {args.report}: {exc}", pretty, output))

    commentary_count = report_text.count(COMMENTARY_HEADING)
    marker_count = report_text.count(args.marker)

    reason = _matrix_reason(commentary_count, marker_count)
    if reason is not None:
        sys.exit(_blocked(reason, pretty, output))

    run_id, parity_error = _verify_run_id_parity(args.verify_artifact)
    if parity_error is not None:
        sys.exit(_blocked(parity_error, pretty, output))

    already_inserted = commentary_count == 1 and marker_count == 0
    if already_inserted:
        _emit(
            {
                "status": "already_inserted",
                "report_path": os.path.abspath(args.report),
                "run_id": run_id,
                "verified_artifacts": len(args.verify_artifact),
            },
            pretty,
            output,
        )
        sys.exit(0)

    # State (0, 1): insert.
    commentary, load_error = _load_commentary(args.commentary_file)
    if load_error is not None or commentary is None:
        sys.exit(_blocked(load_error or "commentary_markdown missing or empty", pretty, output))

    replacement = f"{COMMENTARY_HEADING}\n\n{commentary.strip()}"
    new_text = report_text.replace(args.marker, replacement, 1)

    # Post-insert self-check on the in-memory content BEFORE touching disk.
    new_commentary_count = new_text.count(COMMENTARY_HEADING)
    new_marker_count = new_text.count(args.marker)
    if new_commentary_count != 1 or new_marker_count != 0:
        sys.exit(
            _blocked(
                f"post-insert self-check failed: commentary count="
                f"{new_commentary_count} (expected 1), marker count="
                f"{new_marker_count} (expected 0) — commentary text may "
                f"contain the heading or the marker string; report.md was "
                f"NOT modified",
                pretty,
                output,
            )
        )

    # Single in-place write pass (no delete/recreate, no os.replace —
    # Cowork's outputs/ denies deletion and rename).
    try:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(new_text)
    except OSError as exc:
        sys.exit(_blocked(f"write-back to {args.report} failed: {exc}", pretty, output))

    _emit(
        {
            "status": "inserted",
            "report_path": os.path.abspath(args.report),
            "run_id": run_id,
            "verified_artifacts": len(args.verify_artifact),
            "commentary_bytes": len(commentary.encode("utf-8")),
            "founder_text_findings": _scan_commentary(commentary),
        },
        pretty,
        output,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
