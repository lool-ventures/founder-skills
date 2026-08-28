"""Typed loader for cap-table artifacts (cap-table-data-contract §4.5b).

A STRICT READER for cap-table artifacts. It is NOT on any production path.

Measured 2026-08-28: zero producers import this module; 32 cap-table scripts `json.load`
directly, and SKILL.md never mentions a §3.5 read-allowlist. Its only caller is
tests/test_chain_integration_v050.py, where 4 of 13 tests drive it. An earlier version of
this docstring claimed "every consumer goes through one of the load_* functions", which was
false and had already misled a reader into believing a rewrite here reached production.

Keep it for the invariants it enforces on read (schema version, mirror drift, and the
semantic checks below), and use it deliberately -- but do not cite it as a mandatory path.
The load_*
functions. The loader:

1. Validates the artifact against its declared JSON schema.
2. Stamps + checks `metadata.schema_version` against the producer-declared
   version constant. A mismatch raises E_SCHEMA_VERSION_MISMATCH (the
   v0.4.x → v0.5.0 hard-reject path).
3. Runs §4.5 semantic invariants on load (not just at canonicalization).
4. For cap_state: re-derives mirrored fields from instruments.json (if
   present in the same workspace) and raises E_MIRRORED_FIELD_DRIFT on
   disagreement.

The loader returns plain dicts (not dataclasses) for v0.5.0 simplicity;
callers use ordinary dict access. v0.6.0+ may tighten into frozen
dataclass projections.

Strict-by-default: every `validate_*` flag defaults to True. A consumer
that needs to skip a check passes the flag explicitly (e.g., extraction
scripts pass `validate_mirror=False` since they're operating at the input
boundary before cap_state exists).

Error format: all `E_*` raises carry a structured payload accessible via
`e.code`, `e.path`, `e.expected`, `e.actual` for programmatic recovery.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cap_table_schema_validator import (  # type: ignore[import-not-found]  # noqa: E402
    check_misplaced_top_level_keys as _check_misplaced_top_level_keys,
)
from _cap_table_schema_validator import (  # type: ignore[import-not-found]  # noqa: E402
    drop_nulls_on_optional_strings as _drop_nulls_on_optional_strings,
)
from _cap_table_schema_validator import validate as _validate_schema  # type: ignore[import-not-found]  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "schemas",
)

CAP_STATE_SCHEMA_VERSION = "v0.5.0-cap-state"
INSTRUMENTS_SCHEMA_VERSION = "v0.5.0-instruments"
INPUTS_SCHEMA_VERSION = "v0.5.0-inputs"


class ArtifactIOError(ValueError):
    """Raised when an artifact load fails any validation.

    Attributes:
        code: structured error code (`E_*`).
        path: JSON pointer or filesystem path to the offending element.
        expected: what the loader expected.
        actual: what the loader observed.
    """

    def __init__(self, code: str, message: str, *, path: str = "", expected: Any = None, actual: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.expected = expected
        self.actual = actual


def _load_schema(name: str) -> dict[str, Any]:
    with open(os.path.join(_SCHEMA_DIR, name), encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _check_schema_version(data: dict[str, Any], expected: str, artifact: str, path: Path) -> None:
    actual = (data.get("metadata") or {}).get("schema_version")
    if actual != expected:
        raise ArtifactIOError(
            "E_SCHEMA_VERSION_MISMATCH",
            f"{artifact} at {path} has metadata.schema_version={actual!r}; "
            f"v0.5.0 requires {expected!r}. Delete the artifact and re-run from inputs.json. "
            f"(See contract §10.1 / §10.3.)",
            path=str(path),
            expected=expected,
            actual=actual,
        )


def _check_semantic_invariants_cap_state(cap_state: dict[str, Any], path: Path) -> None:
    """Run a subset of §4.5 invariants on load (the cheap, high-signal ones).

    cap_state.py runs the full set at canonicalization. The loader re-runs
    on every load so that a hand-edited cap_state.json (rare but possible)
    can't sneak past.
    """
    # Founder shares > 0 if any founder
    founders = cap_state.get("founders") or []
    if founders and sum(int(f.get("common_shares", 0)) for f in founders) <= 0:
        raise ArtifactIOError(
            "E_FOUNDER_SHARES_REQUIRED",
            "cap_state.founders is non-empty but total common_shares is 0.",
            path=str(path),
        )
    # FD = sum invariant
    totals = cap_state.get("as_converted_totals") or {}
    if totals:
        expected_fd = (
            int(totals.get("common_shares", 0))
            + int(totals.get("preferred_shares_as_converted", 0))
            + int(totals.get("options_outstanding", 0))
            + int(totals.get("options_available", 0))
            + int(totals.get("warrants_underlying_total", 0))
        )
        actual_fd = int(totals.get("fully_diluted_shares", 0))
        if expected_fd != actual_fd:
            raise ArtifactIOError(
                "E_FD_SUM_MISMATCH",
                f"as_converted_totals.fully_diluted_shares ({actual_fd}) != sum of components ({expected_fd}).",
                path=str(path),
                expected=expected_fd,
                actual=actual_fd,
            )
    # cap_table_history monotonic (AD ratchets down)
    history = cap_state.get("cap_table_history") or []
    for h in history:
        if h.get("event_type") == "anti_dilution_applied":
            prev = h.get("previous_ccp")
            new = h.get("new_ccp")
            if prev is not None and new is not None and float(new) > float(prev) + 1e-9:
                raise ArtifactIOError(
                    "E_AD_RATCHET_UP_NOT_ALLOWED",
                    f"cap_table_history event {h.get('round_id')} has new_ccp ({new}) > previous_ccp ({prev}); "
                    f"AD only ratchets down.",
                    path=str(path),
                )


def _check_mirror_drift(cap_state: dict[str, Any], instruments: dict[str, Any], path: Path) -> None:
    """Re-derive mirrored fields from instruments.json and check parity (§2.1).

    Mirrored fields per the contract:
    - cap_state.outstanding_safes[].mfn_status derived from instruments.safes[].mfn_provision.
    - cap_state.outstanding_options[].plan_type mirrored from instruments.option_grants[].plan_type.
    - cap_state.outstanding_notes[].subtype mirrored from instruments.convertible_notes[].subtype.
    - cap_state.outstanding_warrants[].settlement_type mirrored from instruments.warrants[].settlement_type.

    Disagreement raises E_MIRRORED_FIELD_DRIFT with a structured diff.
    """
    # Build lookup indices
    safe_by_id = {s["id"]: s for s in instruments.get("safes") or []}
    note_by_id = {n["id"]: n for n in instruments.get("convertible_notes") or []}
    grant_by_id = {g["id"]: g for g in instruments.get("option_grants") or []}
    warrant_by_id = {w["id"]: w for w in instruments.get("warrants") or []}

    # outstanding_safes mfn_status parity
    expected: Any
    actual: Any
    for cs in cap_state.get("outstanding_safes") or []:
        sid = cs.get("safe_id")
        src = safe_by_id.get(sid) or {}
        from cap_state import _derive_mfn_status  # local import to avoid cycle

        expected = _derive_mfn_status(src) if src else "absent"
        actual = cs.get("mfn_status", "absent")
        if actual != expected:
            raise ArtifactIOError(
                "E_MIRRORED_FIELD_DRIFT",
                f"outstanding_safes[{sid}].mfn_status: cap_state has {actual!r}, instruments derives {expected!r}.",
                path=f"outstanding_safes[{sid}].mfn_status",
                expected=expected,
                actual=actual,
            )

    # outstanding_options.plan_type parity
    for co in cap_state.get("outstanding_options") or []:
        gid = co.get("grant_id")
        src = grant_by_id.get(gid) or {}
        if src:
            expected = src.get("plan_type")
            actual = co.get("plan_type")
            if actual != expected:
                raise ArtifactIOError(
                    "E_MIRRORED_FIELD_DRIFT",
                    f"outstanding_options[{gid}].plan_type: cap_state has {actual!r}, instruments has {expected!r}.",
                    path=f"outstanding_options[{gid}].plan_type",
                    expected=expected,
                    actual=actual,
                )

    # outstanding_notes.subtype parity
    for cn in cap_state.get("outstanding_notes") or []:
        nid = cn.get("note_id")
        src = note_by_id.get(nid) or {}
        if src and src.get("subtype") is not None:
            expected = src.get("subtype")
            actual = cn.get("subtype")
            if actual != expected:
                raise ArtifactIOError(
                    "E_MIRRORED_FIELD_DRIFT",
                    f"outstanding_notes[{nid}].subtype: cap_state has {actual!r}, instruments has {expected!r}.",
                    path=f"outstanding_notes[{nid}].subtype",
                    expected=expected,
                    actual=actual,
                )

    # outstanding_warrants.settlement_type parity
    for cw in cap_state.get("outstanding_warrants") or []:
        wid = cw.get("warrant_id")
        src = warrant_by_id.get(wid) or {}
        if src:
            expected = src.get("settlement_type")
            actual = cw.get("settlement_type")
            if actual != expected:
                raise ArtifactIOError(
                    "E_MIRRORED_FIELD_DRIFT",
                    f"outstanding_warrants[{wid}].settlement_type: cap_state has {actual!r}, "
                    f"instruments has {expected!r}.",
                    path=f"outstanding_warrants[{wid}].settlement_type",
                    expected=expected,
                    actual=actual,
                )


def load_cap_state(
    workspace_dir: str | Path,
    *,
    validate_mirror: bool = True,
    validate_invariants: bool = True,
    validate_schema_version: bool = True,
    validate_schema: bool = True,
    filename: str = "cap_state.json",
) -> dict[str, Any]:
    """Load cap_state.json with full validation.

    Raises:
        FileNotFoundError: file missing.
        ArtifactIOError(E_SCHEMA_VERSION_MISMATCH): wrong schema_version.
        ArtifactIOError(E_MIRRORED_FIELD_DRIFT): mirror disagreement.
        ArtifactIOError(E_*): semantic invariant violations.
    """
    path = Path(workspace_dir) / filename
    data = _read_json(path)
    if validate_schema_version:
        _check_schema_version(data, CAP_STATE_SCHEMA_VERSION, "cap_state.json", path)
    if validate_schema:
        schema = _load_schema("cap_state.schema.json")
        errors = _validate_schema(data, schema)
        if errors:
            raise ArtifactIOError(
                "E_CAP_STATE_SCHEMA_INVALID",
                f"cap_state.json schema validation failed: {'; '.join(errors)}",
                path=str(path),
            )
    if validate_invariants:
        _check_semantic_invariants_cap_state(data, path)
    if validate_mirror:
        instr_path = Path(workspace_dir) / "instruments.json"
        if instr_path.exists():
            instruments = _read_json(instr_path)
            _check_mirror_drift(data, instruments, path)
    return data


def load_instruments(
    workspace_dir: str | Path,
    *,
    validate_schema_version: bool = True,
    validate_schema: bool = True,
    filename: str = "instruments.json",
) -> dict[str, Any]:
    """Load instruments.json. Validates schema_version == 'v0.5.0-instruments'."""
    path = Path(workspace_dir) / filename
    data = _read_json(path)
    if validate_schema_version:
        _check_schema_version(data, INSTRUMENTS_SCHEMA_VERSION, "instruments.json", path)
    if validate_schema:
        schema = _load_schema("instruments.schema.json")
        errors = _validate_schema(data, schema)
        if errors:
            raise ArtifactIOError(
                "E_INSTRUMENTS_SCHEMA_INVALID",
                f"instruments.json schema validation failed: {'; '.join(errors)}",
                path=str(path),
            )
    # Targeted mis-key guard: preferred_series belongs in inputs.json, not instruments.json. The
    # instruments schema has no such property, so without this the key silently drops rather than
    # rejecting (see `_cap_table_schema_validator.check_misplaced_top_level_keys`).
    misplaced_errors = _check_misplaced_top_level_keys(data, "instruments.json")
    if misplaced_errors:
        raise ArtifactIOError(
            "E_MISPLACED_KEY_PREFERRED_SERIES",
            "; ".join(misplaced_errors),
            path=str(path),
        )
    # Hard-reject the deprecated top-level 'notes' key (§10.1)
    if "notes" in data and "convertible_notes" not in data:
        raise ArtifactIOError(
            "E_DEPRECATED_KEY_NOTES",
            "instruments.json uses the deprecated top-level key 'notes'. "
            "Rename to 'convertible_notes' per v0.5.0 schema. (See contract §6.6 / §10.1.)",
            path=str(path),
        )
    return data


def load_inputs(
    workspace_dir: str | Path,
    *,
    validate_schema_version: bool = True,
    validate_schema: bool = True,
    filename: str = "inputs.json",
) -> dict[str, Any]:
    """Load inputs.json. Validates schema_version == 'v0.5.0-inputs'."""
    path = Path(workspace_dir) / filename
    data = _read_json(path)
    if validate_schema_version:
        _check_schema_version(data, INPUTS_SCHEMA_VERSION, "inputs.json", path)
    if validate_schema:
        schema = _load_schema("inputs.schema.json")
        # See drop_nulls_on_optional_strings: `null` on an optional bare-string field is a type
        # error while omission is fine, and nothing signposts the difference to whoever wrote it.
        _drop_nulls_on_optional_strings(data, schema)
        errors = _validate_schema(data, schema)
        if errors:
            raise ArtifactIOError(
                "E_INPUTS_SCHEMA_INVALID",
                f"inputs.json schema validation failed: {'; '.join(errors)}",
                path=str(path),
            )
    # v0.4.10 carve-out (§10.2): rewrite top-level pay_to_play_detected into aoa_findings
    if "pay_to_play_detected" in data:
        sys.stderr.write(
            "W_DEPRECATED_KEY_PAY_TO_PLAY_AT_TOP_LEVEL: inputs.pay_to_play_detected "
            "at top level; rewriting under inputs.aoa_findings.pay_to_play_detected.\n"
        )
        aoa = dict(data.get("aoa_findings") or {})
        aoa.setdefault("pay_to_play_detected", bool(data["pay_to_play_detected"]))
        data["aoa_findings"] = aoa
        data.pop("pay_to_play_detected", None)
    return data


def load_scenarios(
    workspace_dir: str | Path,
    *,
    validate_schema: bool = True,
    filename: str = "scenarios.json",
) -> dict[str, Any]:
    """Load scenarios.json. No schema_version stamp (produced per-run)."""
    path = Path(workspace_dir) / filename
    data = _read_json(path)
    if validate_schema:
        schema = _load_schema("scenarios.schema.json")
        errors = _validate_schema(data, schema)
        if errors:
            raise ArtifactIOError(
                "E_SCENARIOS_SCHEMA_INVALID",
                f"scenarios.json schema validation failed: {'; '.join(errors)}",
                path=str(path),
            )
    return data
