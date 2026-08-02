"""Tests for `_docx_text` — the stdlib tracked-changes-aware DOCX reader.

All fixtures are built programmatically (minimal WordprocessingML zips) — no real documents committed.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "cap-table" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _docx_text  # type: ignore[import-not-found]  # noqa: E402

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _build(body_inner: str, extra_parts: dict[str, str] | None = None) -> bytes:
    """Minimal .docx (zip) carrying the given `<w:body>` inner XML."""
    doc = f'<?xml version="1.0"?><w:document {_NS}><w:body>{body_inner}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        for name, xml in (extra_parts or {}).items():
            z.writestr(name, xml)
    return buf.getvalue()


def _r(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _ins(text: str) -> str:
    return f'<w:ins w:id="1" w:author="x"><w:r><w:t>{text}</w:t></w:r></w:ins>'


def _del(text: str) -> str:
    return f'<w:del w:id="2" w:author="x"><w:r><w:delText>{text}</w:delText></w:r></w:del>'


def _move_from(text: str) -> str:
    return f'<w:moveFrom w:id="3"><w:r><w:t>{text}</w:t></w:r></w:moveFrom>'


def _move_to(text: str) -> str:
    return f'<w:moveTo w:id="4"><w:r><w:t>{text}</w:t></w:r></w:moveTo>'


def _p(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def _write(tmp_path: Path, data: bytes, name: str = "d.docx") -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ---------------------------------------------------------------- detection


def test_detect_clean(tmp_path: Path) -> None:
    path = _write(tmp_path, _build(_p(_r("hello world"))))
    d = _docx_text.detect_tracked_changes(path)
    assert d == {"has_tracked_changes": False, "ins": 0, "del": 0, "move": 0}


def test_detect_redline_counts(tmp_path: Path) -> None:
    body = _p(_r("base "), _ins("added"), _del("removed"))
    path = _write(tmp_path, _build(body))
    d = _docx_text.detect_tracked_changes(path)
    assert d["has_tracked_changes"] is True
    assert d["ins"] == 1 and d["del"] == 1


def test_detect_move_only_redline(tmp_path: Path) -> None:
    # A move-only redline must still register as tracked (the prior flat ins/del scan would miss it).
    body = _p(_move_from("clause")) + _p(_move_to("clause"))
    path = _write(tmp_path, _build(body))
    d = _docx_text.detect_tracked_changes(path)
    assert d["has_tracked_changes"] is True
    assert d["move"] == 2


# ---------------------------------------------------------------- accept-view extraction


def test_accept_includes_inserted_excludes_struck(tmp_path: Path) -> None:
    body = _p(_r("cap is "), _del("$1,000,000"), _ins("$2,000,000"), _r(" final"))
    path = _write(tmp_path, _build(body))
    txt = _docx_text.extract_text(path)
    assert "$2,000,000" in txt  # inserted final term — python-docx .text would DROP this
    assert "$1,000,000" not in txt  # struck — excluded from the accepted view
    assert "cap is" in txt and "final" in txt


def test_accept_move_keeps_destination_drops_origin(tmp_path: Path) -> None:
    body = _p(_move_from("MOVED")) + _p(_r("middle")) + _p(_move_to("MOVED"))
    path = _write(tmp_path, _build(body))
    txt = _docx_text.extract_text(path)
    # The moved clause must appear exactly once (at its destination), not zero or twice.
    assert txt.count("MOVED") == 1


def test_accept_nested_del_inside_ins_excluded(tmp_path: Path) -> None:
    # Text inserted then struck within the same redline: a <w:del> inside a <w:ins> → excluded.
    nested = '<w:ins w:id="9"><w:del w:id="10"><w:r><w:delText>X</w:delText></w:r></w:del></w:ins>'
    body = _p(_r("a "), nested, _r(" b"))
    path = _write(tmp_path, _build(body))
    txt = _docx_text.extract_text(path)
    assert "X" not in txt
    assert "a" in txt and "b" in txt


def test_accept_table_cells_captured(tmp_path: Path) -> None:
    # Table text lives in document.xml — python-docx `d.paragraphs` would MISS it; the walk captures it.
    body = f"<w:tbl><w:tr><w:tc>{_p(_r('Valuation Cap'))}</w:tc><w:tc>{_p(_r('$10,000,000'))}</w:tc></w:tr></w:tbl>"
    path = _write(tmp_path, _build(body))
    txt = _docx_text.extract_text(path)
    assert "Valuation Cap" in txt and "$10,000,000" in txt


def test_accept_hyperlink_wrapped_run(tmp_path: Path) -> None:
    body = _p(_r("see "), "<w:hyperlink><w:r><w:t>terms</w:t></w:r></w:hyperlink>")
    path = _write(tmp_path, _build(body))
    assert "terms" in _docx_text.extract_text(path)


def test_accept_preserves_space_run_text(tmp_path: Path) -> None:
    body = _p('<w:r><w:t xml:space="preserve">lead </w:t></w:r>', _r("tail"))
    path = _write(tmp_path, _build(body))
    assert "lead tail" in _docx_text.extract_text(path)


def test_accept_includes_header_footer(tmp_path: Path) -> None:
    body = _p(_r("body text"))
    parts = {
        "word/header1.xml": f"<w:hdr {_NS}>{_p(_r('HEADER MARK'))}</w:hdr>",
        "word/footer1.xml": f"<w:ftr {_NS}>{_p(_r('FOOTER MARK'))}</w:ftr>",
    }
    path = _write(tmp_path, _build(body, parts))
    txt = _docx_text.extract_text(path)
    assert "body text" in txt and "HEADER MARK" in txt and "FOOTER MARK" in txt


def test_reject_mode_unsupported(tmp_path: Path) -> None:
    path = _write(tmp_path, _build(_p(_r("x"))))
    with pytest.raises(ValueError):
        _docx_text.extract_text(path, revisions="reject")


# ---------------------------------------------------------------- CLI


def test_cli_detect(tmp_path: Path) -> None:
    path = _write(tmp_path, _build(_p(_r("base "), _ins("new"))))
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "_docx_text.py"), path, "--detect"],
        capture_output=True,
        text=True,
        check=True,
    )
    rec = json.loads(out.stdout)
    assert rec["ok"] is True and rec["mode"] == "docx-probe" and rec["has_tracked_changes"] is True


def test_cli_extract(tmp_path: Path) -> None:
    body = _p(_r("keep "), _del("drop"), _ins("add"))
    path = _write(tmp_path, _build(body))
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "_docx_text.py"), path, "--extract"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "keep" in out.stdout and "add" in out.stdout and "drop" not in out.stdout
