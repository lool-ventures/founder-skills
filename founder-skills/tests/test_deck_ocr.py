"""deck-review Step 3.95's machine read (`deck_ocr.py`), with stub binaries on an emptied PATH.

No real render or OCR runs: `pdfinfo`, `pdftoppm` and `tesseract` are shell stubs, so these pin the receipt,
the resume, the budget, the attempts, the cap and the not-applicable reasons, never OCR quality.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deck-review" / "scripts"
RUN = "20261021T090000Z"
_TSV_HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _stubs(tmp: Path, pages: int = 3, fail_page: int | None = None, sleep: float = 0) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "pdfinfo").write_text(f"#!/bin/sh\necho 'Pages:          {pages}'\n")
    fail = f'[ "$2" = "{fail_page}" ] && exit 1\n' if fail_page else ""
    pause = f"sleep {sleep}\n" if sleep else ""
    # pdftoppm -f N -l N -r DPI -png -singlefile PDF STEM: write STEM.png.
    (bin_dir / "pdftoppm").write_text(f'#!/bin/sh\n{fail}{pause}for a; do last="$a"; done\n: > "$last.png"\n')
    row = "5\t1\t1\t1\t1\t{n}\t0\t0\t10\t10\t91\t{w}"
    rows = "\\n".join(row.format(n=i, w=w) for i, w in enumerate(["ARR", "\\$1.2M"], 1))  # escaped for the stub's shell
    (bin_dir / "tesseract").write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "tesseract 9.9.9"; exit 0; fi\n'
        f'printf "{_TSV_HEAD}\\n{rows}\\n"\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return bin_dir


def _review(tmp: Path, slides: int = 3, figure_slides: tuple[int, ...] = (2, 3), deck: bytes = b"%PDF fake") -> Path:
    rv = tmp / "review"
    (rv / "handoff").mkdir(parents=True)
    (tmp / "deck.pdf").write_bytes(deck)
    sha = hashlib.sha256(deck).hexdigest()
    sources = "{" + ", ".join(f"{n}: inventory" for n in range(1, slides + 1)) + "}"
    body = "".join(f"## Slide {n}\n\ntext\n\n" for n in range(1, slides + 1))
    (rv / "deck_text.md").write_text(
        f"---\nrun_id: {RUN}\nsource: inventory\npages_source: {sources}\ndeck_sha256: {sha}\n---\n{body}"
    )
    figs = [{"id": f"f{n}", "raw": "$1.2M", "unit_kind": "money", "slide": n} for n in figure_slides]
    (rv / "ledger.json").write_text(json.dumps({"figures": figs, "metadata": {"run_id": RUN}}))
    relations = [{"operands": [f["id"] for f in figs[:-1]], "expected_id": figs[-1]["id"]}] if figs else []
    (rv / "reconciliation.json").write_text(
        json.dumps({"status": "ok", "relations": relations, "metadata": {"run_id": RUN}})
    )
    return rv


def _run(tmp: Path, bin_dir: Path | None, *extra: str, deck: str = "deck.pdf") -> tuple[int, dict[str, Any]]:
    rv = tmp / "review"
    env = {**os.environ, "PATH": str(bin_dir) if bin_dir else str(tmp / "empty")}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "deck_ocr.py"),
            "--deck",
            str(tmp / deck),
            "--ledger",
            str(rv / "ledger.json"),
            "--reconciliation",
            str(rv / "reconciliation.json"),
            "--deck-text",
            str(rv / "deck_text.md"),
            "--run-id",
            RUN,
            "-o",
            str(rv / "handoff" / "ocr"),
            *extra,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, json.loads(proc.stdout.splitlines()[-1])


def _receipt(tmp: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((tmp / "review" / "handoff" / "ocr" / "receipt.json").read_text())
    return loaded


def test_reads_the_in_scope_pages_and_writes_their_text(tmp_path: Path) -> None:
    _review(tmp_path)
    rc, out = _run(tmp_path, _stubs(tmp_path))
    assert rc == 0 and out["complete"] is True and out["pages"] == 2
    receipt = _receipt(tmp_path)
    assert receipt["scope_pages"] == [2, 3] and set(receipt["pages"]) == {"2", "3"}
    assert receipt["tesseract_version"] == "tesseract 9.9.9"
    assert (tmp_path / "review" / "handoff" / "ocr" / "p2.txt").read_text() == "ARR $1.2M"


def test_no_tools_is_unavailable_and_exits_zero(tmp_path: Path) -> None:
    _review(tmp_path)
    rc, out = _run(tmp_path, None)
    assert (rc, out["status"], out["reason"], out["complete"]) == (0, "unavailable", "no_ocr_tools", True)


def test_the_budget_stops_after_one_page_and_a_second_call_resumes(tmp_path: Path) -> None:
    _review(tmp_path)
    bin_dir = _stubs(tmp_path, sleep=0.3)
    rc, out = _run(tmp_path, bin_dir, "--budget-seconds", "0")
    assert (rc, out["complete"], out["pages"], out["pending"]) == (0, False, 1, 1)
    rc, out = _run(tmp_path, bin_dir, "--budget-seconds", "0")
    assert (rc, out["complete"], out["pages"]) == (0, True, 2)
    assert all(p["attempts"] == 1 for p in _receipt(tmp_path)["pages"].values()), "a resumed page is not re-read"


def test_a_page_that_fails_twice_is_failed(tmp_path: Path) -> None:
    _review(tmp_path)
    bin_dir = _stubs(tmp_path, fail_page=2)
    _run(tmp_path, bin_dir)
    rc, out = _run(tmp_path, bin_dir)
    assert rc == 0 and out["complete"] is True and out["failed"] == 1
    assert _receipt(tmp_path)["pages"]["2"] == {"kind": "failed", "attempts": 2}


def test_pages_past_the_cap_are_not_read(tmp_path: Path) -> None:
    _review(tmp_path, slides=4, figure_slides=(2, 3, 4))
    rc, out = _run(tmp_path, _stubs(tmp_path, pages=4), "--max-pages", "2")
    assert rc == 0 and out["complete"] is True and out["not_read"] == 1
    assert _receipt(tmp_path)["pages"]["4"]["kind"] == "not_read"


def test_a_changed_scope_restarts_the_receipt(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    bin_dir = _stubs(tmp_path)
    _run(tmp_path, bin_dir)
    ledger = json.loads((rv / "ledger.json").read_text())
    ledger["figures"].append({"id": "f1", "raw": "$9K", "unit_kind": "money", "slide": 1})
    (rv / "ledger.json").write_text(json.dumps(ledger))
    recon = json.loads((rv / "reconciliation.json").read_text())
    recon["relations"][0]["operands"].append("f1")
    (rv / "reconciliation.json").write_text(json.dumps(recon))
    rc, out = _run(tmp_path, bin_dir)
    assert rc == 0 and _receipt(tmp_path)["scope_pages"] == [1, 2, 3]
    assert all(p["attempts"] == 1 for p in _receipt(tmp_path)["pages"].values())


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("deck_mismatch", "not_applicable", "deck_mismatch"),
        ("page_count_mismatch", "not_applicable", "page_count_mismatch"),
        ("no_inventory", "not_applicable", "no_inventory"),
        ("no_figures", "no_figures", "no_figures"),
    ],
)
def test_not_applicable_reasons(tmp_path: Path, case: str, status: str, reason: str) -> None:
    rv = _review(tmp_path, figure_slides=() if case == "no_figures" else (2, 3))
    pages = 3
    if case == "deck_mismatch":
        (tmp_path / "deck.pdf").write_bytes(b"%PDF another file")
    elif case == "page_count_mismatch":
        pages = 5
    elif case == "no_inventory":
        text = (rv / "deck_text.md").read_text().replace("inventory}", "extracted}")
        text = text.replace("1: inventory, 2: inventory", "1: extracted, 2: extracted")
        (rv / "deck_text.md").write_text(text.replace("source: inventory", "source: extracted"))
    rc, out = _run(tmp_path, _stubs(tmp_path, pages=pages))
    assert (rc, out["status"], out["reason"], out["complete"]) == (0, status, reason, True)


def test_the_deck_check_runs_before_the_pdf_check(tmp_path: Path) -> None:
    """A PowerPoint passed in place of the converted PDF is a wrong deck, never "not a PDF"."""
    _review(tmp_path)
    (tmp_path / "deck.pptx").write_bytes(b"PK pptx")
    rc, out = _run(tmp_path, _stubs(tmp_path), deck="deck.pptx")
    assert (rc, out["reason"]) == (0, "deck_mismatch")


def test_a_missing_deck_is_refused_and_the_receipt_survives(tmp_path: Path) -> None:
    _review(tmp_path)
    bin_dir = _stubs(tmp_path)
    _run(tmp_path, bin_dir)
    before = (tmp_path / "review" / "handoff" / "ocr" / "receipt.json").read_text()
    rc, out = _run(tmp_path, bin_dir, deck="missing.pdf")
    assert (rc, out["code"]) == (1, "DECK_NOT_FOUND")
    assert (tmp_path / "review" / "handoff" / "ocr" / "receipt.json").read_text() == before


def test_an_output_that_is_a_file_is_refused(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    (rv / "handoff" / "ocr").write_text("not a folder")
    rc, out = _run(tmp_path, _stubs(tmp_path))
    assert (rc, out["code"]) == (1, "OUTPUT_NOT_DIR")
    assert (rv / "handoff" / "ocr").read_text() == "not a folder"


def test_an_unreadable_ledger_is_refused(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    (rv / "ledger.json").write_text("{not json")
    rc, out = _run(tmp_path, _stubs(tmp_path))
    assert (rc, out["code"]) == (1, "LEDGER_UNREADABLE")
    assert not (rv / "handoff" / "ocr").exists()


FIXTURE_DECK = Path(__file__).resolve().parent / "fixtures" / "deck-review" / "synthetic-image-deck.pdf"


@pytest.mark.skipif(
    not (shutil.which("pdftoppm") and shutil.which("tesseract")), reason="needs pdftoppm and tesseract on PATH"
)
def test_the_real_tools_find_the_fixture_decks_figures(tmp_path: Path) -> None:
    """With real binaries, the image fixture's three unit-economics and revenue figures are found as written."""
    rv = _review(tmp_path, slides=6, figure_slides=(), deck=FIXTURE_DECK.read_bytes())
    figs = [
        {"id": "rev", "raw": "$1.2M", "unit_kind": "money", "slide": 3},
        {"id": "gm", "raw": "75%", "unit_kind": "percent", "slide": 4},
        {"id": "gp", "raw": "$690K", "unit_kind": "money", "slide": 4},
    ]
    (rv / "ledger.json").write_text(json.dumps({"figures": figs, "metadata": {"run_id": RUN}}))
    recon = {"status": "checked", "relations": [{"operands": ["rev", "gm"], "expected_id": "gp"}]}
    (rv / "reconciliation.json").write_text(json.dumps({**recon, "metadata": {"run_id": RUN}}))
    rc, out = _run(tmp_path, Path(shutil.which("tesseract") or "").parent)
    assert rc == 0 and out["complete"] is True, out
    check = subprocess.run(
        [sys.executable, str(SCRIPTS / "ocr_check.py"), "--ledger", str(rv / "ledger.json")]
        + ["--reconciliation", str(rv / "reconciliation.json"), "--deck-text", str(rv / "deck_text.md")]
        + ["--ocr-dir", str(rv / "handoff" / "ocr"), "--run-id", RUN, "-o", str(rv / "ocr_check.json")],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout
    written = json.loads((rv / "ocr_check.json").read_text())
    assert written["status"] == "checked" and written["counts"]["found"] == 3, written
