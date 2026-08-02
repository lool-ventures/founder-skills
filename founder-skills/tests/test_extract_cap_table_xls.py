"""Fix B1 — legacy binary `.xls` gets a founder-friendly blocker, not a cryptic BadZipFile.

Fixtures are synthetic (8 OLE2 magic bytes + padding) — no real workbook committed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_cap_table as ect  # type: ignore[import-not-found]  # noqa: E402

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512  # legacy .xls magic + padding


def _run(path: str, mode: str, tmp_path: Path | None = None) -> dict[str, Any]:
    cmd = [sys.executable, str(SCRIPTS / "extract_cap_table.py"), f"--mode={mode}", "--xlsx", path]
    stdin = None
    if mode == "freeform-emit":
        stdin = '{"blocks":[]}'
        if tmp_path is not None:
            cmd += ["--dir", str(tmp_path)]
    out = subprocess.run(cmd, capture_output=True, text=True, input=stdin)
    return json.loads(out.stdout)  # type: ignore[no-any-return]


def test_open_xlsx_raises_legacy_xls(tmp_path: Path) -> None:
    p = tmp_path / "legacy.xls"
    p.write_bytes(_OLE2)
    with pytest.raises(ect.LegacyXlsError) as ei:
        ect._open_xlsx(str(p))
    assert "re-save" in ei.value.message.lower() and ".xlsx" in ei.value.message


@pytest.mark.parametrize("mode", ["auto", "grid", "carta", "freeform-emit"])
def test_named_xls_friendly_blocker_all_modes(tmp_path: Path, mode: str) -> None:
    p = tmp_path / "cap.xls"
    p.write_bytes(_OLE2)
    rec = _run(str(p), mode)
    assert rec["ok"] is False
    # Caught by _check_supported_input_type (extension) before any mode dispatch.
    assert rec["blocker"] == "unsupported_input_type"
    assert rec.get("mode") == mode
    assert ".xlsx" in rec["remedy"] and "BadZipFile" not in json.dumps(rec)


def test_freeform_emit_file_not_found(tmp_path: Path) -> None:
    # file_not_found receipt carries mode — exercised before _open_xlsx.
    absent = tmp_path / "absent.xlsx"  # inside tmp_path but never written → guaranteed non-existent
    rec = _run(str(absent), "freeform-emit", tmp_path)
    assert rec["ok"] is False and rec["mode"] == "freeform-emit"
    assert rec["blocker"] == "file_not_found"


def test_freeform_emit_no_inputs_json(tmp_path: Path) -> None:
    # no_inputs_json receipt carries mode — fires when _open_xlsx succeeds but --dir lacks inputs.json.
    # Uses a real (empty) OOXML workbook; openpyxl is a runtime dep so it is always importable.
    import openpyxl  # type: ignore[import-untyped]  # noqa: PLC0415

    p = tmp_path / "cap.xlsx"
    openpyxl.Workbook().save(str(p))
    rec = _run(str(p), "freeform-emit", tmp_path)
    assert rec["ok"] is False and rec["mode"] == "freeform-emit"
    assert rec["blocker"] == "no_inputs_json"


def test_freeform_emit_bad_stdin_shape(tmp_path: Path) -> None:
    # bad_input receipt carries mode — fires after file-existence check, before _open_xlsx.
    # The OLE2 file exists on disk so the existence check passes; bad stdin shape fires first.
    p = tmp_path / "cap.xlsx"
    p.write_bytes(_OLE2)
    cmd = [
        sys.executable,
        str(SCRIPTS / "extract_cap_table.py"),
        "--mode=freeform-emit",
        "--xlsx",
        str(p),
        "--dir",
        str(tmp_path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, input="{}")  # missing "blocks" → bad_input
    rec = json.loads(out.stdout)
    assert rec["ok"] is False and rec["mode"] == "freeform-emit"
    assert rec["blocker"] == "bad_input"


@pytest.mark.parametrize("mode", ["grid", "carta", "auto", "freeform-emit"])
def test_misnamed_ole2_as_xlsx_caught_by_magic(tmp_path: Path, mode: str) -> None:
    # A legacy .xls misnamed .xlsx slips past the extension check → caught by the OLE2 magic in _open_xlsx.
    p = tmp_path / "cap.xlsx"
    p.write_bytes(_OLE2)
    rec = _run(str(p), mode, tmp_path)
    assert rec["ok"] is False and rec["blocker"] == "legacy_xls"
    assert rec.get("mode") == mode
    msg = rec.get("error", "") + rec.get("remedy", "")
    assert ".xlsx" in msg and "re-save" in msg.lower() and "BadZipFile" not in msg
