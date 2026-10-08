#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Apply founder corrections from the review playground artifact.

Reads a corrections JSON file (downloaded by the founder from the JSX artifact),
performs coercion, ILS normalization, time-series canonicalization, override
merging, and writes corrected_inputs.json + extraction_corrections.json.

Usage:
    python apply_corrections.py <corrections.json> --original <inputs.json> --output-dir <dir>
    python apply_corrections.py --set revenue.mrr=45000 [--set ...] --original <inputs.json> --output-dir <dir>

The second form is the CHAT route: a correction the founder states in conversation rather than
on the review page. It builds the same patch payload the page would download, computes the
base_hash of the original itself (a model cannot do that by hand, which is why chat corrections
previously had no route through this script), and then runs the unchanged pipeline -- so
coercion, path validation and the audit record are identical whichever way the founder
corrected. A value is read as JSON first (45000, true, null) and as text otherwise (series_a).

`--run-id R --origin O` ties the call to a run and says who supplied the corrections: `external`
(the service that ran the review), `upload` (the founder's corrections file from the review page),
`chat` (the founder, in conversation) or `inputs_review` (the inputs-review sub-agent). The origin is
required whenever a run id is given; only `upload` can be checked here (it must arrive as a file, not
as `--set`). Every call appends one line to extraction_corrections.history.jsonl, so a later call
cannot erase an earlier one; extraction_corrections.json holds only the last call.
Both records carry `channel`, which is HOW the values arrived and predates `origin`: `review_page` for a
corrections file, `chat` for `--set` values, whoever supplied either. WHO supplied them is `origin` (an
`external` call with `--set` is `channel: chat, origin: external`). The field keeps its earlier meaning so the
audit file keeps its shape; read `origin`, never `channel`, for the source.

Output:
    stdout: {"status": "completed"|"error", "correction_count": N, ...}
    files:  corrected_inputs.json, extraction_corrections.history.jsonl (appended),
            extraction_corrections.json (in output-dir)
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _run_ref import RUN_ID_RE  # noqa: E402

# ---------------------------------------------------------------------------
# Path navigation (shared with review_inputs.py)
# ---------------------------------------------------------------------------


# Optional fields a correction may ADD although the original never carried them. Everything else must
# already exist, so a typo cannot silently create a key. `unclassified_reason` is optional by design
# (an extraction may not record why the model is unclassified), and a founder's chat correction is
# exactly how the unknown case gets resolved.
# Paths a correction may add when the extraction left them out. The cash pair is what the hand-over
# asks for when runway could not be computed without a balance, and an absent key is the usual shape.
_OPTIONAL_SET_PATHS = frozenset({"company.unclassified_reason", "cash.current_balance", "cash.balance_date"})

# A run id names a directory, so a sub-path (`<id>/r2`) or anything shell-hostile is refused. The grammar
# is the plugin's one, from the sibling copy every skill carries.
_RUN_ID_RE = RUN_ID_RE

# Who supplied the corrections. Recorded, and checked only for `upload` (see main()).
_ORIGINS = ("external", "upload", "chat", "inputs_review")

_HISTORY_NAME = "extraction_corrections.history.jsonl"


def _navigate_part(obj: Any, part: str) -> Any:
    if obj is None or not isinstance(obj, dict):
        return None
    if "[" not in part:
        return obj.get(part)
    name, rest = part.split("[", 1)
    selector = rest.rstrip("]")
    arr = obj.get(name)
    if not isinstance(arr, list):
        return None
    if "=" in selector:
        k, v = selector.split("=", 1)
        return next((item for item in arr if isinstance(item, dict) and str(item.get(k)) == v), None)
    idx = int(selector) if selector.isdigit() else -1
    return arr[idx] if 0 <= idx < len(arr) else None


def _deep_get(data: dict[str, Any], dotted_path: str) -> Any:
    obj: Any = data
    for part in dotted_path.split("."):
        obj = _navigate_part(obj, part)
    return obj


def _set_by_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    obj: Any = data
    for part in parts[:-1]:
        nxt = _navigate_part(obj, part)
        if nxt is None:
            if "[" not in part and isinstance(obj, dict):
                obj[part] = {}
                nxt = obj[part]
            else:
                return
        obj = nxt
    last = parts[-1]
    if "[" not in last and isinstance(obj, dict):
        obj[last] = value


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------

_NUMERIC_PATHS = [
    "cash.current_balance",
    "cash.monthly_net_burn",
    "cash.debt",
    "revenue.mrr.value",
    "revenue.arr.value",
    "revenue.customers",
    "revenue.growth_rate_monthly",
    "revenue.churn_monthly",
    "revenue.nrr",
    "revenue.grr",
    "revenue.monthly_total",
    "cash.fundraising.target_raise",
    "cash.grants.iia_approved",
    "cash.grants.iia_pending",
    "cash.grants.iia_disbursement_months",
    "cash.grants.iia_start_month",
    "cash.grants.royalty_rate",
    "unit_economics.cac.total",
    "unit_economics.ltv.value",
    "unit_economics.ltv.inputs.arpu_monthly",
    "unit_economics.ltv.inputs.churn_monthly",
    "unit_economics.ltv.inputs.gross_margin",
    "unit_economics.gross_margin",
    "unit_economics.payback_months",
    "unit_economics.burn_multiple",
    "israel_specific.fx_rate_ils_usd",
    "israel_specific.ils_expense_fraction",
    "scenarios.base.growth_rate",
    "scenarios.base.burn_change",
    "scenarios.slow.growth_rate",
    "scenarios.slow.burn_change",
    "scenarios.crisis.growth_rate",
    "scenarios.crisis.burn_change",
    "bridge.runway_target_months",
]


def _coerce_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for path in _NUMERIC_PATHS:
        val = _deep_get(state, path)
        if val is None or isinstance(val, (int, float)):
            continue
        if isinstance(val, str):
            cleaned = val.strip().replace(",", "")
            if not cleaned or cleaned == "-" or cleaned == "\u2014":
                _set_by_path(state, path, None)
                continue
            try:
                n = float(cleaned)
                _set_by_path(state, path, int(n) if n == int(n) else n)
            except (ValueError, OverflowError):
                errors.append(
                    {
                        "code": "COERCION_ERROR",
                        "message": f"Cannot convert '{val}' to number",
                        "field": path,
                        "layer": 0,
                    }
                )
        else:
            errors.append(
                {
                    "code": "COERCION_ERROR",
                    "message": f"Expected number, got {type(val).__name__}",
                    "field": path,
                    "layer": 0,
                }
            )

    # Headcount array
    headcount = _deep_get(state, "expenses.headcount")
    if isinstance(headcount, list):
        for i, h in enumerate(headcount):
            if not isinstance(h, dict):
                continue
            for fld in ("count", "salary_annual", "burden_pct"):
                val = h.get(fld)
                if val is None or isinstance(val, (int, float)):
                    continue
                if isinstance(val, str):
                    cleaned = val.strip().replace(",", "")
                    if not cleaned or cleaned == "-":
                        h[fld] = None
                        continue
                    try:
                        n = float(cleaned)
                        h[fld] = int(n) if n == int(n) else n
                    except (ValueError, OverflowError):
                        errors.append(
                            {
                                "code": "COERCION_ERROR",
                                "message": f"Cannot convert '{val}' to number",
                                "field": f"expenses.headcount[{i}].{fld}",
                                "layer": 0,
                            }
                        )

    # Opex array
    opex = _deep_get(state, "expenses.opex_monthly")
    if isinstance(opex, list):
        for i, e in enumerate(opex):
            if not isinstance(e, dict):
                continue
            val = e.get("amount")
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if not cleaned or cleaned == "-":
                    e["amount"] = None
                    continue
                try:
                    n = float(cleaned)
                    e["amount"] = int(n) if n == int(n) else n
                except (ValueError, OverflowError):
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number",
                            "field": f"expenses.opex_monthly[{i}].amount",
                            "layer": 0,
                        }
                    )

    # COGS dict
    cogs = _deep_get(state, "expenses.cogs")
    if isinstance(cogs, dict):
        for k, val in cogs.items():
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if not cleaned or cleaned == "-":
                    cogs[k] = None
                    continue
                try:
                    n = float(cleaned)
                    cogs[k] = int(n) if n == int(n) else n
                except (ValueError, OverflowError):
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number",
                            "field": f"expenses.cogs.{k}",
                            "layer": 0,
                        }
                    )

    # Boolean coercion for time-series actual fields
    for ts_path in ("revenue.monthly", "revenue.quarterly"):
        arr = _deep_get(state, ts_path)
        if not isinstance(arr, list):
            continue
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            actual = entry.get("actual")
            if isinstance(actual, str):
                if actual.lower() == "true":
                    entry["actual"] = True
                elif actual.lower() == "false":
                    entry["actual"] = False

    return errors


# ---------------------------------------------------------------------------
# ILS normalization
# ---------------------------------------------------------------------------


def _normalize_to_usd(state: dict[str, Any], ils_fields: dict[str, bool]) -> None:
    fx = _deep_get(state, "israel_specific.fx_rate_ils_usd")
    if not isinstance(fx, (int, float)) or fx <= 0:
        return
    for field, is_ils in ils_fields.items():
        if not is_ils:
            continue
        val = _deep_get(state, field)
        if isinstance(val, (int, float)):
            _set_by_path(state, field, round(val / fx, 2))


# ---------------------------------------------------------------------------
# Time-series
# ---------------------------------------------------------------------------


def _canonicalize_time_series(state: dict[str, Any]) -> None:
    monthly = _deep_get(state, "revenue.monthly")
    if isinstance(monthly, list):
        monthly.sort(key=lambda e: e.get("month", "") if isinstance(e, dict) else "")
    quarterly = _deep_get(state, "revenue.quarterly")
    if isinstance(quarterly, list):
        quarterly.sort(key=lambda e: e.get("quarter", "") if isinstance(e, dict) else "")


_YYYY_MM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_YYYY_QN_RE = re.compile(r"^\d{4}-Q[1-4]$")


def _validate_time_series_keys(state: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    monthly = _deep_get(state, "revenue.monthly")
    if isinstance(monthly, list):
        for i, entry in enumerate(monthly):
            if not isinstance(entry, dict):
                continue
            m = entry.get("month")
            if m is not None and not _YYYY_MM_RE.match(str(m)):
                errors.append(
                    {
                        "code": "DATE_FORMAT_ERROR",
                        "message": f"Invalid month '{m}', expected YYYY-MM",
                        "field": f"revenue.monthly[{i}].month",
                        "layer": 0,
                    }
                )
    quarterly = _deep_get(state, "revenue.quarterly")
    if isinstance(quarterly, list):
        for i, entry in enumerate(quarterly):
            if not isinstance(entry, dict):
                continue
            q = entry.get("quarter")
            if q is not None and not _YYYY_QN_RE.match(str(q)):
                errors.append(
                    {
                        "code": "DATE_FORMAT_ERROR",
                        "message": f"Invalid quarter '{q}', expected YYYY-QN",
                        "field": f"revenue.quarterly[{i}].quarter",
                        "layer": 0,
                    }
                )
    return errors


# ---------------------------------------------------------------------------
# Override merging
# ---------------------------------------------------------------------------


def _merge_overrides(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, Any] = {}
    agent_keys: set[str] = set()
    for o in existing:
        k = f"{o.get('code', '')}|{o.get('field', '')}"
        merged[k] = o
        if o.get("reviewed_by") == "agent":
            agent_keys.add(k)
    for o in incoming:
        k = f"{o.get('code', '')}|{o.get('field', '')}"
        if k in agent_keys and o.get("reviewed_by") != "agent":
            continue
        merged[k] = o
    return list(merged.values())


# ---------------------------------------------------------------------------
# Row ID stripping
# ---------------------------------------------------------------------------

_ARRAY_PATHS = (
    "expenses.headcount",
    "expenses.opex_monthly",
    "revenue.monthly",
    "revenue.quarterly",
)


def _strip_row_ids(state: dict[str, Any]) -> None:
    for arr_path in _ARRAY_PATHS:
        arr = _deep_get(state, arr_path)
        if isinstance(arr, list):
            for entry in arr:
                if isinstance(entry, dict):
                    entry.pop("_row_id", None)


# ---------------------------------------------------------------------------
# Patch-based flow
# ---------------------------------------------------------------------------


def _canonical_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _apply_patches(
    original: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply patch-based changes to a deep copy of original.

    Returns (patched_state, corrections_for_audit, errors).
    """
    errors: list[dict[str, Any]] = []

    # Verify base_hash — required for new-style payloads
    base_hash = payload.get("base_hash")
    if base_hash is None:
        errors.append(
            {
                "code": "MISSING_BASE_HASH",
                "message": "base_hash is required for patch-based corrections",
                "field": "",
                "layer": 0,
            }
        )
        return {}, [], errors
    actual_hash = _canonical_hash(original)
    if base_hash != actual_hash:
        errors.append(
            {
                "code": "STALE_BASE",
                "message": f"Base hash mismatch — original has changed since review page was loaded. "
                f"Expected {base_hash[:20]}..., got {actual_hash[:20]}...",
                "field": "",
                "layer": 0,
            }
        )
        return {}, [], errors

    state = copy.deepcopy(original)
    changes = payload.get("changes", [])
    corrections: list[dict[str, Any]] = []

    for ch in changes:
        path = ch.get("path", "")
        expected_old = ch.get("expected_old")
        new_val = ch.get("new")
        change_type = ch.get("type", "scalar")

        # --- Path validation (applies to ALL change types) ---
        # Verify the path exists in original before writing.
        # _set_by_path auto-creates missing dict segments, so a typo like
        # "revenue.mrr.valeu" or "expenses.headcout" would silently add a
        # new key. We check the leaf key exists in its parent object.
        # This correctly handles null values (key exists, value is None).
        parts = path.split(".")
        leaf = parts[-1]
        parent_path = ".".join(parts[:-1])
        parent_obj = _deep_get(original, parent_path) if parent_path else original
        if not isinstance(parent_obj, dict) or (leaf not in parent_obj and path not in _OPTIONAL_SET_PATHS):
            errors.append(
                {
                    "code": "PATH_ERROR",
                    "message": f"Path '{path}' does not exist in original — possible typo",
                    "field": path,
                    "layer": 0,
                }
            )
            continue

        actual_old = _deep_get(state, path)

        if change_type == "replace_array":
            # For array replacements, expected_old is the array length
            actual_len = len(actual_old) if isinstance(actual_old, list) else 0
            if expected_old is not None and actual_len != expected_old:
                errors.append(
                    {
                        "code": "STALE_EDIT",
                        "message": f"Stale array edit at '{path}': expected length {expected_old}, found {actual_len}",
                        "field": path,
                        "layer": 0,
                    }
                )
                continue
            _set_by_path(state, path, new_val)
            new_len = len(new_val) if isinstance(new_val, list) else 0
            corrections.append(
                {
                    "path": path,
                    "type": "replace_array",
                    "was_length": actual_len,
                    "now_length": new_len,
                }
            )
            continue

        # Scalar change — verify expected_old matches (skip check if None)
        if expected_old is not None and actual_old != expected_old:
            # Tolerance for float comparison
            if isinstance(actual_old, (int, float)) and isinstance(expected_old, (int, float)):
                if abs(float(actual_old) - float(expected_old)) <= 0.01:
                    pass  # within tolerance, proceed
                else:
                    errors.append(
                        {
                            "code": "STALE_EDIT",
                            "message": f"Stale edit at '{path}': expected {expected_old}, found {actual_old}",
                            "field": path,
                            "layer": 0,
                        }
                    )
                    continue
            else:
                errors.append(
                    {
                        "code": "STALE_EDIT",
                        "message": f"Stale edit at '{path}': expected {expected_old}, found {actual_old}",
                        "field": path,
                        "layer": 0,
                    }
                )
                continue

        _set_by_path(state, path, new_val)
        corrections.append({"path": path, "was": actual_old, "now": new_val})

    if errors:
        return {}, [], errors

    return state, corrections, []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _payload_from_chat(sets: list[str], original: dict[str, Any]) -> dict[str, Any]:
    """The patch payload the review page would have downloaded, built from `--set PATH=VALUE` pairs.

    `expected_old` is left None: the stale-edit check exists because a page can be edited against a
    file that has since changed, and a chat correction has no such page. Path validation still runs
    downstream, so a misspelt path is refused rather than created. Returns {"errors": [...]} on a
    malformed pair so the caller can emit it through the same channel as every other refusal.
    """
    changes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in sets:
        if "=" not in raw:
            errors.append(
                {
                    "code": "INVALID_SET",
                    "message": f"--set expects PATH=VALUE, got {raw!r}",
                    "field": raw,
                    "layer": 0,
                }
            )
            continue
        path, text = raw.split("=", 1)
        path = path.strip()
        if not path:
            errors.append(
                {"code": "INVALID_SET", "message": f"--set has an empty path: {raw!r}", "field": raw, "layer": 0}
            )
            continue
        try:
            value: Any = json.loads(text)
        except json.JSONDecodeError:
            value = text
        changes.append({"path": path, "type": "scalar", "expected_old": None, "new": value})
    if errors:
        return {"errors": errors}
    return {
        "base_hash": _canonical_hash(original),
        "changes": changes,
        "warning_overrides": [],
        "ils_fields": {},
    }


# extraction_corrections.history.jsonl: one JSON object per line, appended and never rewritten. A
# crashed append can leave a torn line; this script skips such a line when numbering the next one and
# every reader must skip it too, never refuse on it, because the file outlives any one run.
# `correction_count` is the number of entries recorded, as in extraction_corrections.json;
# `changed_count` is how many of them changed a value, and is the count a gate reads.
# `corrected_sha256` is the sha256 of the corrected_inputs.json this call wrote. The line is
# synced before that file is moved into place, so a crash between the two leaves a line whose
# `corrected_sha256` does not match the file on disk: a reader must compare it before trusting the
# line's corrections to be in effect. Each call overwrites that file, so only the newest line can
# match it; an earlier line is checked against the inputs.json promoted right after its call.
# Calls are sequential on the main thread and take no lock, so seq can collide only under concurrent
# callers.


def _history_state(history_path: str) -> tuple[int, bool]:
    """(next seq, whether the next write must start a new line) for the history at `history_path`.

    The next seq is one past the highest seq among the lines that parse, or 1. A file whose last line
    has no line ending (an interrupted write) needs a leading newline so the new entry stands alone;
    the torn text itself is left where it is. An unreadable file raises OSError for the caller.
    """
    if not os.path.exists(history_path):
        return 1, False
    with open(history_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text.strip():
        return 1, False
    highest = 0
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        seq = entry.get("seq") if isinstance(entry, dict) else None
        if isinstance(seq, int) and not isinstance(seq, bool) and seq > highest:
            highest = seq
    return highest + 1, not text.endswith("\n")


def _is_change(correction: Any) -> bool:
    """Whether a recorded correction changed anything. An array replacement always counts."""
    if not isinstance(correction, dict):
        return True
    for before, after in (("was", "now"), ("old", "new")):
        if before in correction and after in correction:
            return bool(correction[before] != correction[after])
    return True


# corrected_inputs.json and extraction_corrections.json are each written to `<name>.tmp-<pid>` beside
# them and moved into place, so a tmp file of exactly that shape is this script's own and may be removed.
_TMP_RE = re.compile(r"^(?:corrected_inputs|extraction_corrections)\.json\.tmp-[0-9]+$")


def _remove_stale_tmps(output_dir: str) -> None:
    """Remove temporary files an interrupted earlier call of this script left in `output_dir`."""
    try:
        names = os.listdir(output_dir)
    except OSError:
        return
    for name in names:
        if _TMP_RE.match(name):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(output_dir, name))


def _write_tmp(path: str, data: Any) -> tuple[str, str]:
    """Write `data` as JSON beside `path` under a temporary name; the caller moves it into place.

    Returns (tmp path, sha256 hex of the bytes written).
    """
    tmp = f"{path}.tmp-{os.getpid()}"
    body = json.dumps(data, indent=2).encode("utf-8")
    try:
        with open(tmp, "wb") as f:
            f.write(body)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return tmp, hashlib.sha256(body).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply founder corrections")
    parser.add_argument("corrections", nargs="?", help="Path to corrections JSON file (omit when using --set)")
    parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="A correction stated in chat, e.g. revenue.mrr=45000. Repeatable. Mutually exclusive with a file.",
    )
    parser.add_argument("--original", required=True, help="Path to original inputs.json")
    parser.add_argument("--output-dir", required=True, help="Directory for output files")
    parser.add_argument(
        "--run-id",
        help="The run these corrections belong to: stamped on corrected_inputs.json and the audit. Requires --origin.",
    )
    parser.add_argument(
        "--origin",
        help=f"Who supplied the corrections: one of {', '.join(_ORIGINS)}. Required with --run-id.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON")
    parser.add_argument(
        "-o",
        "--output",
        help="Write the status JSON to this file instead of stdout (emits a JSON receipt on stdout)",
    )
    args = parser.parse_args()

    def _emit(result: dict[str, Any], args: argparse.Namespace) -> None:
        """Write the status JSON to stdout, or to -o with a stdout receipt."""
        data = json.dumps(result, indent=2 if args.pretty else None)
        if args.output:
            abs_path = os.path.abspath(args.output)
            parent = os.path.dirname(abs_path)
            if parent == "/":
                print(f"Error: output path resolves to root directory: {args.output}", file=sys.stderr)
                sys.exit(1)
            os.makedirs(parent, exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(data)
            receipt = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
            sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
        else:
            sys.stdout.write(data)
            sys.stdout.write("\n")

    def _read_json_file(path: str, field: str) -> dict[str, Any]:
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _emit(
                {
                    "status": "error",
                    "errors": [{"code": "READ_ERROR", "message": str(e), "field": field, "layer": 0}],
                },
                args,
            )
            sys.exit(1)
        if not isinstance(loaded, dict):
            _emit(
                {
                    "status": "error",
                    "errors": [
                        {
                            "code": "READ_ERROR",
                            "message": f"{field} must be a JSON object",
                            "field": field,
                            "layer": 0,
                        }
                    ],
                },
                args,
            )
            sys.exit(1)
        return loaded

    def _refuse(code: str, message: str, field: str) -> NoReturn:
        """Refuse before anything is written: diagnostic on stdout, one line on stderr, exit 1."""
        print(f"Error: {message}", file=sys.stderr)
        _emit({"status": "error", "errors": [{"code": code, "message": message, "field": field, "layer": 0}]}, args)
        sys.exit(1)

    if args.origin is not None and args.origin not in _ORIGINS:
        _refuse("INVALID_ORIGIN", f"--origin must be one of {', '.join(_ORIGINS)}, got {args.origin!r}", "origin")
    if args.run_id is not None:
        if not _RUN_ID_RE.match(args.run_id):
            _refuse(
                "INVALID_RUN_ID",
                f"--run-id must match {_RUN_ID_RE.pattern} (a single name, no path), got {args.run_id!r}",
                "run_id",
            )
        if args.origin is None:
            _refuse(
                "ORIGIN_REQUIRED",
                f"--run-id needs --origin ({', '.join(_ORIGINS)}): the audit must say who supplied the corrections",
                "origin",
            )
    if args.origin == "upload" and args.sets:
        _refuse(
            "ORIGIN_CHANNEL_MISMATCH",
            "--origin upload means the founder's corrections file; give that file, not --set",
            "origin",
        )

    if bool(args.corrections) == bool(args.sets):
        _emit(
            {
                "status": "error",
                "errors": [
                    {
                        "code": "INVALID_INVOCATION",
                        "message": (
                            "Give either a corrections file or one or more --set PATH=VALUE, not both and not neither."
                        ),
                        "field": "",
                        "layer": 0,
                    }
                ],
            },
            args,
        )
        sys.exit(1)

    original = _read_json_file(args.original, "original")
    channel = "review_page"
    if args.sets:
        channel = "chat"
        payload = _payload_from_chat(args.sets, original)
        if "errors" in payload:
            _emit({"status": "error", "errors": payload["errors"]}, args)
            sys.exit(1)
    else:
        payload = _read_json_file(args.corrections, "corrections")

    # Detect payload shape: new (changes[]) vs legacy (corrected{})
    if "changes" in payload:
        corrected, corrections, patch_errors = _apply_patches(original, payload)
        if patch_errors:
            _emit({"status": "error", "errors": patch_errors}, args)
            sys.exit(1)
    elif "corrected" in payload:
        print("Info: corrected-object payload (dispatch shape) — applying directly.", file=sys.stderr)
        corrections = payload.get("corrections", [])
        corrected = payload["corrected"]
        if not isinstance(corrected, dict):
            err = {
                "status": "error",
                "errors": [
                    {
                        "code": "INVALID_PAYLOAD",
                        "message": f"'corrected' must be a JSON object, got {type(corrected).__name__}",
                        "field": "corrected",
                        "layer": 0,
                    }
                ],
            }
            _emit(err, args)
            sys.exit(1)
    else:
        err = {
            "status": "error",
            "errors": [
                {
                    "code": "INVALID_PAYLOAD",
                    "message": "Payload must contain 'changes' or 'corrected'",
                    "field": "",
                    "layer": 0,
                }
            ],
        }
        _emit(err, args)
        sys.exit(1)

    # The origin must fit how the corrections arrived. `upload` is the review page's patch file,
    # `chat` is --set, and the inputs-review wrapper ({"corrected": ...}) comes only from that
    # sub-agent. `inputs_review` is recorded as given.
    shape = "changes" if "changes" in payload else "corrected"
    if args.origin == "chat" and not args.sets:
        _refuse(
            "ORIGIN_CHANNEL_MISMATCH", "--origin chat means corrections stated in chat; give them as --set", "origin"
        )
    if args.origin == "upload" and shape != "changes":
        _refuse(
            "ORIGIN_PAYLOAD_MISMATCH",
            "--origin upload needs the review page's corrections file (a 'changes' list with its base_hash)",
            "origin",
        )
    if shape == "corrected" and args.origin not in (None, "inputs_review"):
        _refuse(
            "ORIGIN_PAYLOAD_MISMATCH",
            f"a {{'corrected': ...}} payload comes from the inputs review; --origin {args.origin} cannot carry it",
            "origin",
        )
    if not isinstance(corrections, list):
        _refuse(
            "INVALID_CORRECTIONS",
            f"'corrections' must be a JSON array, got {type(corrections).__name__}",
            "corrections",
        )

    # A run's ledger: a finished review's inputs never move (only the cash follow-up it asked for). Loaded
    # here, not at import: the gate binder loads this file by path for its normalising steps alone.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _fmr_gates

    run_id = args.run_id or (original.get("metadata") or {}).get("run_id")
    # Naming no run into a dir that belongs to one: RUN_ID_REQUIRED, so no copy of the inputs skips the check.
    _fmr_gates.refuse_without_run_id(os.path.join(args.output_dir, "corrected_inputs.json"), run_id)
    _fmr_gates.refuse_finished_corrections(
        args.output_dir,
        run_id,
        {str(c.get("path")) if isinstance(c, dict) else "" for c in corrections} if shape == "changes" else {""},
        sum(1 for c in corrections if _is_change(c)),
    )

    overrides = payload.get("warning_overrides", [])
    ils_fields = payload.get("ils_fields", {})

    # 1. Coerce
    coercion_errors = _coerce_state(corrected)

    # 2. Validate time-series keys
    ts_errors = _validate_time_series_keys(corrected)

    all_errors = coercion_errors + ts_errors
    if all_errors:
        _emit({"status": "error", "errors": all_errors}, args)
        sys.exit(1)

    # 3. Normalize ILS → USD
    _normalize_to_usd(corrected, ils_fields)

    # 4. Canonicalize time-series
    _canonicalize_time_series(corrected)

    # 5. Preserve run_id, or stamp the one the caller named
    orig_metadata = original.get("metadata", {})
    corrected_metadata = corrected.get("metadata", {})
    if not isinstance(corrected_metadata, dict):
        corrected_metadata = {}
    if "run_id" in orig_metadata and "run_id" not in corrected_metadata:
        corrected_metadata["run_id"] = orig_metadata["run_id"]
    if args.run_id is not None:
        prior = corrected_metadata.get("run_id")
        if prior is not None and prior != args.run_id:
            print(f"Info: metadata.run_id {prior!r} replaced by --run-id {args.run_id!r}.", file=sys.stderr)
        corrected_metadata["run_id"] = args.run_id

    # 6. Merge overrides
    existing_overrides = orig_metadata.get("warning_overrides", [])
    if overrides or existing_overrides:
        corrected_metadata["warning_overrides"] = _merge_overrides(existing_overrides, overrides)
    corrected["metadata"] = corrected_metadata

    # 7. Strip _row_ids
    _strip_row_ids(corrected)

    # 8. Write files. The history is opened for append before anything is written, so a history that
    # cannot take the entry refuses the call with every output as it was. The corrected inputs go to
    # a temporary file and move into place only after the history line is down, so they are never
    # left without their audit.
    history_path = os.path.join(args.output_dir, _HISTORY_NAME)
    _remove_stale_tmps(args.output_dir)
    try:
        os.makedirs(args.output_dir, exist_ok=True)
        seq, needs_newline = _history_state(history_path)
        history_fd = os.open(history_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    except OSError as e:
        _refuse(
            "HISTORY_UNAVAILABLE",
            f"{_HISTORY_NAME} cannot be appended to ({e}); nothing was written",
            "history",
        )

    overrides_added = [{"code": o.get("code"), "field": o.get("field"), "reason": o.get("reason")} for o in overrides]
    changed = sum(1 for c in corrections if _is_change(c))
    unchanged = len(corrections) - changed
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    history_entry = {
        "seq": seq,
        "timestamp": timestamp,
        "run_id": args.run_id,
        "origin": args.origin,
        "channel": channel,
        "correction_count": len(corrections),
        "changed_count": changed,
        "unchanged_count": unchanged,
        "corrected_sha256": "",
        "corrections": corrections,
        "overrides_added": overrides_added,
    }
    audit = {
        "timestamp": timestamp,
        "source_file": "inputs.json",
        "channel": channel,
        "run_id": args.run_id,
        "origin": args.origin,
        "correction_count": len(corrections),
        "changed_count": changed,
        "unchanged_count": unchanged,
        "corrections": corrections,
        "override_count": len(overrides_added),
        "overrides_added": overrides_added,
    }

    corrected_path = os.path.join(args.output_dir, "corrected_inputs.json")
    audit_path = os.path.join(args.output_dir, "extraction_corrections.json")
    corrected_tmp = ""
    try:
        corrected_tmp, history_entry["corrected_sha256"] = _write_tmp(corrected_path, corrected)
        line = ("\n" if needs_newline else "") + json.dumps(history_entry, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        while data:
            written = os.write(history_fd, data)
            data = data[written:]
        os.fsync(history_fd)
    except OSError as e:
        if corrected_tmp:
            with contextlib.suppress(OSError):
                os.remove(corrected_tmp)
        _refuse(
            "HISTORY_UNAVAILABLE",
            f"the corrections could not be recorded ({e}); nothing was moved into place",
            "history",
        )
    finally:
        os.close(history_fd)
    audit_tmp = ""
    try:
        os.replace(corrected_tmp, corrected_path)
        audit_tmp, _ = _write_tmp(audit_path, audit)
        os.replace(audit_tmp, audit_path)
    except OSError as e:
        for tmp in (corrected_tmp, audit_tmp):
            if tmp:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
        _refuse(
            "WRITE_FAILED",
            f"the corrected files could not be moved into place ({e}); this call's history line may name a "
            "corrected_sha256 the file on disk does not have",
            "output",
        )

    # 9. Stdout result
    result = {
        "status": "completed",
        "correction_count": len(corrections),
        "corrected_inputs": corrected_path,
        "extraction_corrections": audit_path,
        "extraction_corrections_history": history_path,
        "history_seq": seq,
    }
    _emit(result, args)


if __name__ == "__main__":
    main()
